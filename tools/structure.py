# -*- coding: utf-8 -*-
"""结构层：场景空镜 → 数字素体（可确定比例/落点/朝向）→ structure.png + manifest。

用法:
  python tools/structure.py --scene-prompt "..." --ratio 0.26 --ground-y 0.78 --x 0.34
"""
import argparse, json, os, shutil, time, urllib.request, uuid
from PIL import Image, ImageDraw, ImageFilter

B = "http://127.0.0.1:8188"
ROOT = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from comfy_paths import COMFY_IN as CI
OUT = os.path.join(ROOT, "SD-Picture", "coop_b")
CKPT = ""
CN = ""
W, H = 1344, 768


def post(p, o):
    r = urllib.request.Request(B + p, data=json.dumps(o).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=180).read())


def get(p):
    return json.loads(urllib.request.urlopen(B + p, timeout=60).read())


def run_graph(g, prefix, timeout=1200):
    g["90"] = {"class_type": "SaveImage", "inputs": {"images": g["_out"], "filename_prefix": prefix}}
    g.pop("_out", None)
    pid = post("/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = get("/history/" + pid)
        if pid in h:
            e = h[pid]
            if e.get("status", {}).get("status_str") != "success":
                raise RuntimeError(str(e.get("status", {}).get("messages", []))[-300:])
            f = e["outputs"]["90"]["images"][0]["filename"]
            return os.path.join(ROOT, "comfy", "ComfyUI", "output", f)
        time.sleep(2)
    raise TimeoutError("structure timeout")


def empty_scene(prompt, negative, lora, sketch_name, seed, w=W, h=H, steps=28, cfg=6.0):
    g = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["1", 2]}},
        "_out": ["8", 0],
    }
    pos, neg = ["2", 0], ["3", 0]
    if lora:
        g["2b"] = {"class_type": "LoraLoader", "inputs": {"model": ["1", 0], "clip": ["1", 1],
                                                          "lora_name": lora, "strength_model": 0.9, "strength_clip": 0.9}}
        g["2"]["inputs"]["clip"] = ["2b", 1]
        model = ["2b", 0]
    else:
        model = ["1", 0]
    if sketch_name:
        g["10"] = {"class_type": "LoadImage", "inputs": {"image": sketch_name}}
        g["11"] = {"class_type": "Canny", "inputs": {"image": ["10", 0], "low_threshold": 0.3, "high_threshold": 0.7}}
        g["12"] = {"class_type": "ControlNetLoader", "inputs": {"control_net_name": CN}}
        g["13"] = {"class_type": "SetUnionControlNetType", "inputs": {"control_net": ["12", 0], "type": "canny/lineart/anime_lineart/mlsd"}}
        g["14"] = {"class_type": "ControlNetApplyAdvanced", "inputs": {"positive": pos, "negative": neg, "control_net": ["13", 0],
                                                                       "image": ["11", 0], "strength": 0.7,
                                                                       "start_percent": 0.0, "end_percent": 0.85, "vae": ["1", 2]}}
        pos, neg = ["14", 0], ["14", 1]
    g["7"] = {"class_type": "KSampler", "inputs": {"model": model, "positive": pos, "negative": neg, "latent_image": ["4", 0],
                                                    "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler",
                                                    "scheduler": "normal", "denoise": 1.0}}
    return run_graph(g, "STRUCT_bg")


def _rrect(d, box, radius, fill):
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    if x1 <= x0:
        x1 = x0 + 1
    if y1 <= y0:
        y1 = y0 + 1
    r = int(max(0, min(radius, (x1 - x0) / 2 - 1, (y1 - y0) / 2 - 1)))
    d.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=fill)


def mannequin(size, bbox, pose="standing", shade=(172, 172, 176)):
    """灰模人体：头/颈/胸/腰/胯/四肢，比例按成人 7.5 头身。"""
    w, h = size
    x0, y0, x1, y1 = bbox
    fh = y1 - y0
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = (x0 + x1) / 2
    head_r = fh * 0.052
    head_cy = y0 + head_r * 1.05
    neck_top = head_cy + head_r * 0.92
    shoulder_y = y0 + fh * 0.155
    chest_y = y0 + fh * 0.255
    waist_y = y0 + fh * 0.395
    hip_y = y0 + fh * 0.505
    knee_y = y0 + fh * 0.745
    foot_y = y1

    shoulder_w = fh * 0.185
    waist_w = fh * 0.125
    hip_w = fh * 0.165
    limb_w = fh * 0.055

    d.ellipse((cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r), fill=shade + (255,))
    _rrect(d, (cx - head_r * .34, neck_top, cx + head_r * .34, shoulder_y), head_r * .3, shade + (245,))
    d.polygon([(cx - shoulder_w / 2, shoulder_y + fh * .012), (cx + shoulder_w / 2, shoulder_y + fh * .012),
               (cx + waist_w / 2, waist_y), (cx - waist_w / 2, waist_y)], fill=shade + (240,))
    d.polygon([(cx - waist_w / 2, waist_y - fh * .01), (cx + waist_w / 2, waist_y - fh * .01),
               (cx + hip_w / 2, hip_y), (cx - hip_w / 2, hip_y)], fill=shade + (240,))
    for sign in (-1, 1):
        sx = cx + sign * (shoulder_w / 2 - limb_w * .35)
        hx = cx + sign * (hip_w / 2 + limb_w * .15)
        if pose == "walk":
            hx += sign * fh * .02
        d.line([(sx, shoulder_y + fh * .02), (sx + sign * fh * .012, chest_y), (hx, hip_y + fh * .01)],
               fill=shade + (235,), width=int(limb_w))
        _rrect(d, (hx - limb_w * .42, hip_y + fh * .005, hx + limb_w * .42, hip_y + fh * .19), limb_w * .4, shade + (230,))
    for sign in (-1, 1):
        lx = cx + sign * hip_w * .22
        d.line([(lx, hip_y), (lx + sign * fh * .012, knee_y), (lx + sign * fh * .006, foot_y - fh * .012)],
               fill=shade + (240,), width=int(limb_w * 1.05))
        _rrect(d, (lx - limb_w * .5, foot_y - fh * .014, lx + limb_w * .62, foot_y), 2, (86, 86, 92, 255))
    soft = img.filter(ImageFilter.GaussianBlur(max(1.2, fh * 0.004)))
    return soft


import re as _re

_DROP = _re.compile(r"(figure|person|people|human|1girl|1boy|her\b|his\b|woman|man\b|"
                    r"frame height|distance shot|shot\b|camera|wide-angle|lens)", _re.I)


def sanitize_scene(prompt):
    """去掉场景提示词里的人物/相机/镜头词，只留环境。"""
    parts = [x.strip() for x in (prompt or "").split(",") if x.strip()]
    keep = [x for x in parts if not _DROP.search(x)]
    return ", ".join(keep) if keep else (prompt or "")


def sketchify(img):
    """成图 -> 低信息草图：灰度 + 色调块 + 暗线。"""
    from PIL import ImageOps
    g = img.convert("L")
    tone = ImageOps.posterize(g, 3)
    edges = g.filter(ImageFilter.GaussianBlur(1.0)).filter(ImageFilter.FIND_EDGES)
    edges = edges.point(lambda v: 255 if v > 26 else 0).filter(ImageFilter.GaussianBlur(0.6))
    lines = Image.new("L", img.size, 45)
    out = Image.composite(lines, tone, edges)
    return Image.merge("RGB", (out, out, out))


def mannequin_only(size, pose="standing", bg=(230, 230, 234)):
    """纯色底素体：人物占画面 80% 高，用于独立生成人物。"""
    w, h = size
    pad_top = int(h * 0.06)
    pad_bottom = int(h * 0.02)
    body_h = h - pad_top - pad_bottom
    body_w = int(body_h * 0.42)
    cx = w // 2
    box = (cx - body_w // 2, pad_top, cx + body_w // 2, pad_top + body_h)
    man = mannequin((w, h), box, pose)
    canvas = Image.new("RGB", (w, h), bg)
    canvas.paste(man, (0, 0), man)
    return canvas.filter(ImageFilter.GaussianBlur(2.0))


def build(scene_prompt, scene_lora="", ratio=0.26, ground_y=0.78, x=0.34, seed=1, pose="standing",
          sketch="", out_dir=None, light="left"):
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = out_dir or os.path.join(OUT, stamp)
    os.makedirs(out, exist_ok=True)

    scene_prompt = sanitize_scene(scene_prompt)
    neg = ("(people:1.4), (person:1.4), (human:1.4), (figure:1.4), 1girl, 1boy, "
           "(camera:1.3), (lens:1.3), (tripod:1.3), (letterbox:1.4), (black bars:1.4), (frame border:1.3), "
           "(statue:1.3), (sculpture:1.3), (mannequin:1.2), silhouette, text, watermark, lowres, blurry")
    prompt = (scene_prompt + ", (empty scene:1.2), (no people:1.2), (clear composition:1.1), "
              "(detailed environment:1.15), (soft volumetric light:1.1)")
    if light == "right":
        prompt += ", (light from the right:1.15)"
    elif light == "back":
        prompt += ", (backlit:1.15), (light from behind:1.15)"
    elif light == "top":
        prompt += ", (top light:1.12)"
    else:
        prompt += ", (light from the left:1.15)"

    bg_path = empty_scene(prompt, neg, scene_lora, sketch, seed)
    bg = Image.open(bg_path).convert("RGB")
    bg.save(os.path.join(out, "scene_empty.png"))
    sketch_img = sketchify(bg)
    sketch_img.save(os.path.join(out, "sketch.png"))

    fh = int(H * ratio)
    fw = int(fh * 0.52)
    cx = int(W * x)
    feet = int(H * ground_y)
    bbox = (max(0, cx - fw // 2), max(0, feet - fh), min(W, cx + fw // 2), min(H, feet))

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse((bbox[0] + fw * .10, feet - fh * .02, bbox[2] - fw * .10, feet + fh * .03), fill=(20, 20, 24, 170))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(3, fh // 28)))

    man = mannequin((W, H), bbox, pose)
    comp = bg.convert("RGBA")
    comp.alpha_composite(shadow)
    comp.alpha_composite(man)

    # 草图 = 人形剪影 + 低信息环境
    person = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    person.alpha_composite(shadow)
    person.alpha_composite(mannequin((W, H), bbox, pose, shade=(140, 140, 146)))
    sketch_person = Image.alpha_composite(sketch_img.convert("RGBA"), person).convert("RGB")

    env_only = sketch_img.convert("RGBA")
    hole = Image.new("L", (W, H), 0)
    pad = int(fh * 0.05)
    ImageDraw.Draw(hole).rectangle((max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                                    min(W, bbox[2] + pad), min(H, bbox[3] + pad)), fill=255)
    hole = hole.filter(ImageFilter.GaussianBlur(6))
    soft_fill = sketch_img.filter(ImageFilter.GaussianBlur(28))
    env_only.paste(soft_fill, (0, 0), hole)
    sketch_env = env_only.convert("RGB")

    st_path = os.path.join(out, "structure.png")
    sketch_person.save(st_path)
    env_path = os.path.join(out, "sketch_env.png")
    sketch_env.save(env_path)
    person_path = os.path.join(out, "sketch_person.png")
    sketch_person.save(person_path)

    name = "struct_%s.png" % stamp
    shutil.copy(st_path, os.path.join(CI, name))
    manifest = {"created": stamp, "dir": out, "structure": st_path,
                "structure_input": name, "scene_empty": os.path.join(out, "scene_empty.png"),
                "sketch_env": env_path, "sketch_person": person_path,
                "bbox": list(bbox), "ratio": ratio, "ground_y": ground_y, "x": x,
                "pose": pose, "seed": seed, "light": light, "size": [W, H]}
    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene-prompt", required=True)
    ap.add_argument("--scene-lora", default="")
    ap.add_argument("--ratio", type=float, default=0.26)
    ap.add_argument("--ground-y", type=float, default=0.78)
    ap.add_argument("--x", type=float, default=0.34)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--pose", default="standing", choices=["standing", "walk"])
    ap.add_argument("--sketch", default="")
    ap.add_argument("--light", default="left")
    a = ap.parse_args()
    m = build(a.scene_prompt, a.scene_lora, a.ratio, a.ground_y, a.x, a.seed, a.pose, a.sketch, None, a.light)
    print("done:", m["dir"], flush=True)
