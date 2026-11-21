# -*- coding: utf-8 -*-
"""合作模式出图：背景画师 -> 人物画师 -> 合成导演。

用法:
  python tools/coop_render.py --scene station --ratio 0.22 --light left
  python tools/coop_render.py --prompt-scene "..." --prompt-char "..." --ratio 0.25

产物: SD-Picture/coop/<时间戳>/{bg.png,char.png,alpha.png,comp.png,contract.json}
"""
import argparse, json, os, time, urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

B = "http://127.0.0.1:8770"
ROOT = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from comfy_paths import COMFY_IN as CI
OUT_ROOT = os.path.join(ROOT, "SD-Picture", "coop")
W, H = 1536, 864

SCENES = {
    "station": ("(abandoned train station reclaimed by vines:1.35), (broken platform and rails:1.25), "
                "(drifting mist:1.2), (soft cold light from the far end:1.2), (vast empty hall:1.3)"),
    "jungle":  ("(vast misty rainforest interior:1.4), (dense foliage and hanging vines:1.3), "
                "(light rain:1.15), (soft diffuse light:1.2), (muted green palette:1.2)"),
    "cafe":    ("(quiet cafe interior:1.35), (wooden tables and warm lamps:1.25), "
                "(window light from the left:1.2), (empty seats:1.2)"),
}
LIGHT_PROMPT = {
    "left":  "lit from the left side, shadow falling to the right",
    "right": "lit from the right side, shadow falling to the left",
    "back":  "backlit, rim light along the shoulders, face in soft shade",
    "top":   "lit from above, soft top light, shadow under the chin",
}


def post(path, obj):
    req = urllib.request.Request(B + path, data=json.dumps(obj).encode(),
                                headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=180).read())


def get(path):
    return json.loads(urllib.request.urlopen(B + path, timeout=60).read())


def expand(pos, neg):
    return post("/api/expand", {"positive": pos, "negative": neg})


def run(prompt, negative, prefix, loras, seed, w, h, mode="t2i", ref="", mask="", denoise=0.6, steps=30, cfg=6.0):
    r = post("/api/run", {"prompt": prompt, "negative": negative, "width": w, "height": h, "steps": steps,
                          "cfg": cfg, "seed": seed, "prefix": prefix, "loras": loras,
                          "mode": mode, "reference": ref, "mask": mask, "denoise": denoise})
    t0 = time.time()
    while time.time() - t0 < 900:
        j = get("/api/job/" + r["job_id"])
        try:
            _pg = float(j.get("progress") or 0.0)
            if _pg > 0:
                print("PROGRESS %.3f" % _pg, flush=True)
        except Exception:
            pass
        if j.get("status") in ("done", "error"):
            imgs = (j.get("result") or {}).get("images") or []
            if not imgs:
                raise RuntimeError("生成失败: " + str(j.get("result", {}).get("error")))
            return imgs[0]
        time.sleep(2)
    raise TimeoutError("出图超时")


def key_bg(img, tol=44, blur=1.2):
    """按四角背景色抠图：背景透明，主体保留；含孔洞填充与最大连通域过滤。"""
    rgb = img.convert("RGB")
    a = np.asarray(rgb).astype(np.int16)
    h, w, _ = a.shape
    corners = np.concatenate([a[0:12, 0:12].reshape(-1, 3), a[0:12, w-12:w].reshape(-1, 3),
                              a[h-12:h, 0:12].reshape(-1, 3), a[h-12:h, w-12:w].reshape(-1, 3)])
    bgc = np.median(corners, axis=0)
    dist = np.sqrt(((a - bgc) ** 2).sum(axis=2))
    alpha = np.clip((dist - tol) / 55.0, 0, 1)
    binal = (alpha > 0.35).astype(np.uint8) * 255
    m = Image.fromarray(binal)
    m = m.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
    try:
        from scipy import ndimage
        lbl, n = ndimage.label(np.asarray(m) > 0)
        if n > 1:
            sizes = ndimage.sum(np.asarray(m) > 0, lbl, range(1, n + 1))
            keep = (np.argmax(sizes) + 1)
            m = Image.fromarray(((lbl == keep) * 255).astype(np.uint8))
        filled = ndimage.binary_fill_holes(np.asarray(m) > 0)
        m = Image.fromarray((filled * 255).astype(np.uint8))
    except Exception:
        m = m.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(9))
    m = m.filter(ImageFilter.GaussianBlur(blur))
    out = rgb.convert("RGBA")
    out.putalpha(m)
    return out


def try_rembg(img):
    try:
        from rembg import remove
        return remove(img.convert("RGB")).convert("RGBA")
    except Exception as exc:
        print("   rembg 不可用:", str(exc)[:80], flush=True)
        return None


def match_tone(ch, bg, x, y, strength=0.55):
    """把人物层的亮度/色度往背景地板区域靠，减少贴纸感。"""
    w, h = ch.size
    patch = bg.crop((max(0, x), max(0, y - h), min(bg.width, x + w), min(bg.height, y)))
    if patch.size != (w, h):
        patch = patch.resize((w, h))
    ca = np.asarray(ch.convert('RGB')).astype(np.float32)
    pa = np.asarray(patch.convert('RGB')).astype(np.float32)
    c_mean, c_std = ca.reshape(-1, 3).mean(0), ca.reshape(-1, 3).std(0) + 1e-6
    p_mean, p_std = pa.reshape(-1, 3).mean(0), pa.reshape(-1, 3).std(0) + 1e-6
    norm = (ca - c_mean) / c_std * p_std + p_mean
    out = np.clip(ca * (1 - strength) + norm * strength, 0, 255)
    res = Image.fromarray(out.astype(np.uint8)).convert('RGBA')
    res.putalpha(ch.split()[3])
    return res


def ground_color(bg, x, y):
    box = bg.crop((max(0, x - 60), max(0, y - 12), min(bg.width, x + 60), min(bg.height, y + 12)))
    arr = np.asarray(box).reshape(-1, 3)
    return [int(v) for v in arr.mean(axis=0)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="station", choices=list(SCENES))
    ap.add_argument("--prompt-scene", default="")
    ap.add_argument("--prompt-char", default="")
    ap.add_argument("--scene-lora", default="anima-base-1-env_lora_a.safetensors")
    ap.add_argument("--char-lora", default="@style_lora_b_anima_ver20.safetensors")
    ap.add_argument("--ratio", type=float, default=0.22, help="人物身高 / 画面高度")
    ap.add_argument("--ground-y", type=float, default=0.70, help="地平线（脚底位置）0-1")
    ap.add_argument("--x", type=float, default=0.30, help="人物中心 x 0-1")
    ap.add_argument("--light", default="left", choices=list(LIGHT_PROMPT))
    ap.add_argument("--seed", type=int, default=515501)
    ap.add_argument("--fuse", type=float, default=0.1, help="局部融合重绘幅度")
    args = ap.parse_args()

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(OUT_ROOT, stamp)
    os.makedirs(out_dir, exist_ok=True)

    scene_prompt = args.prompt_scene or SCENES[args.scene]
    char_prompt = args.prompt_char or ("1girl, solo, (full body standing:1.35), "
                                       "(wearing a long beige coat and dark trousers, boots:1.3), "
                                       "(visible face and eyes:1.2), (whole figure with margin around it:1.25), "
                                       "(plain solid light gray background:1.2), (soft neutral studio light:1.15)")
    light = LIGHT_PROMPT[args.light]

    print("[1/6] 背景段…", flush=True)
    ex = expand([{"token": "", "text": scene_prompt, "weight": 1, "enabled": True}],
                [{"token": "", "text": "(people:1.3), (person:1.3)", "weight": 1, "enabled": True}])
    bg_path = run(ex["positive"], ex["negative"], "COOP_bg", [{"name": args.scene_lora, "weight": 1.0}],
                  args.seed, W, H)
    bg = Image.open(bg_path).convert("RGB")
    print("   ", bg_path, flush=True)

    print("[2/6] 人物段…", flush=True)
    char_full = char_prompt + ", (" + light + ":1.25)"
    ex2 = expand([{"token": "", "text": char_full, "weight": 1, "enabled": True}],
                 [{"token": "", "text": "(scenery:1.4), (props:1.2), (cropped legs:1.3), (close-up:1.2)", "weight": 1, "enabled": True}])
    ch_path = run(ex2["positive"], ex2["negative"], "COOP_char", [{"name": args.char_lora, "weight": 1.0}],
                  args.seed, 768, 1152)
    print("   ", ch_path, flush=True)
    ch_img = Image.open(ch_path).convert("RGB")

    print("[3/6] 抠图…", flush=True)
    alpha = try_rembg(ch_img)
    if alpha is None:
        alpha = key_bg(ch_img)
        print("   rembg 不可用，使用色键", flush=True)
    cover = float((np.asarray(alpha)[:, :, 3] > 40).mean())
    print("   覆盖率 %.2f" % cover, flush=True)
    alpha.save(os.path.join(out_dir, "char.png"))

    print("[4/6] 落位…", flush=True)
    bb = alpha.getbbox()
    if not bb:
        raise RuntimeError("人物抠图为空")
    ch = alpha.crop(bb)
    target_h = int(bg.height * args.ratio)
    ch = ch.resize((max(1, int(ch.width * target_h / ch.height)), target_h), Image.LANCZOS)
    feet_y = int(bg.height * args.ground_y)
    cx = int(bg.width * args.x)
    x0 = cx - ch.width // 2
    y0 = feet_y - ch.height

    ch = match_tone(ch, bg, x0, feet_y, 0.55)

    print("[5/6] 阴影与合成…", flush=True)
    gc = ground_color(bg, cx, feet_y)
    shadow = Image.new("RGBA", (ch.width, ch.height), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse((ch.width * 0.18, ch.height * 0.93, ch.width * 0.82, ch.height * 1.03),
               fill=(int(gc[0] * 0.42), int(gc[1] * 0.42), int(gc[2] * 0.42), 160))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(2, target_h // 16)))
    comp = bg.convert("RGBA")
    comp.alpha_composite(shadow, (x0, y0))
    comp.alpha_composite(ch, (x0, y0))
    pre = os.path.join(out_dir, "comp_raw.png")
    comp.convert("RGB").save(pre)

    print("[6/6] 融合…", flush=True)
    mask = Image.new("L", (bg.width, bg.height), 0)
    ImageDraw.Draw(mask).rectangle((x0 - 6, y0 - 6, x0 + ch.width + 6, feet_y + 4), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(10))
    mask_name = "coop_mask_%dx%d.png" % (bg.width, bg.height)
    mask.save(os.path.join(CI, mask_name))
    ex3 = expand([{"token": "", "text": "(a girl standing on the platform:1.25), (" + light + ":1.2), "
                                          "(contact shadow under her feet:1.25), (matching colors:1.15)",
                   "weight": 1, "enabled": True}],
                 [{"token": "", "text": "(letterbox:1.2), (two people:1.3)", "weight": 1, "enabled": True}])
    fused = run(ex3["positive"], ex3["negative"], "COOP_fuse", [], args.seed, bg.width, bg.height,
                mode="inpaint", ref=pre, mask=mask_name, denoise=args.fuse, steps=24, cfg=4.8)
    fin = run("(unified color grading:1.1), (subtle film grain:1.05)", "(text:1.2)", "COOP_grade", [],
              args.seed, bg.width, bg.height, mode="i2i", ref=fused, denoise=0.08, steps=20, cfg=4.2)
    Image.open(fin).convert("RGB").save(os.path.join(out_dir, "comp.png"))

    contract = {
        "mode": "coop", "created": stamp, "scene": args.scene, "scene_prompt": scene_prompt,
        "char_prompt": char_full, "scene_lora": args.scene_lora, "char_lora": args.char_lora,
        "ratio": args.ratio, "ground_y": args.ground_y, "x": args.x, "light": args.light,
        "fuse": args.fuse, "seed": args.seed, "size": [bg.width, bg.height], "ground_color": gc,
        "layers": {"bg": bg_path, "char": ch_path, "raw": pre, "comp": os.path.join(out_dir, "comp.png")},
    }
    json.dump(contract, open(os.path.join(out_dir, "contract.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("done:", out_dir, flush=True)


if __name__ == "__main__":
    main()
