# -*- coding: utf-8 -*-
"""合作模式 v2：先构图稿，再双线（背景/人物），最后合成。

用法:
  python tools/coop_sketch.py --scene station --ratio 0.24 --ground-y 0.72 --x 0.34 --light left
  python tools/coop_sketch.py --sketch "A:/path/to/draft.png"    # 用你自己的草图

产物: SD-Picture/coop2/<时间戳>/{sketch.png, scene.png, char.png, comp.png, contract.json}
"""
import argparse, json, os, time, urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

B = "http://127.0.0.1:8770"
ROOT = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from comfy_paths import COMFY_IN as CI
OUT_ROOT = os.path.join(ROOT, "SD-Picture", "coop2")
W, H = 1536, 864

SCENES = {
    "station": "(abandoned train station reclaimed by vines:1.3), (long empty platform and rails:1.25), "
               "(drifting mist:1.15), (cold light from the far end:1.15)",
    "jungle": "(vast misty rainforest:1.3), (dense foliage and hanging vines:1.3), (shallow water reflection:1.2)",
    "cafe": "(quiet cafe interior:1.3), (wooden tables and warm lamps:1.2), (window light from the left:1.15)",
}
LIGHT_TEXT = {
    "left": "light comes from the left, shadows fall to the right",
    "right": "light comes from the right, shadows fall to the left",
    "back": "backlit from the far end, rim light on the silhouette",
    "top": "light comes from above, soft top light",
}


def post(p, o):
    req = urllib.request.Request(B + p, data=json.dumps(o).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=180).read())


def get(p):
    return json.loads(urllib.request.urlopen(B + p, timeout=60).read())


def expand(pos, neg):
    return post("/api/expand", {"positive": pos, "negative": neg})


def run(prompt, neg, prefix, loras, seed, w, h, mode="t2i", ref="", mask="", denoise=1.0, steps=30, cfg=6.0):
    r = post("/api/run", {"prompt": prompt, "negative": neg, "width": w, "height": h, "steps": steps, "cfg": cfg,
                          "seed": seed, "prefix": prefix, "loras": loras, "mode": mode,
                          "reference": ref, "mask": mask, "denoise": denoise})
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
    raise TimeoutError("超时")


def try_rembg(img):
    try:
        from rembg import remove
        return remove(img.convert("RGB")).convert("RGBA")
    except Exception as exc:
        print("  rembg 不可用:", str(exc)[:70], flush=True)
        return None


def tone_match(ch, bg, x, y, strength=0.5):
    w, h = ch.size
    patch = bg.crop((max(0, x), max(0, y - h), min(bg.width, x + w), min(bg.height, y)))
    if patch.size != (w, h):
        patch = patch.resize((w, h))
    ca = np.asarray(ch.convert("RGB")).astype(np.float32)
    pa = np.asarray(patch.convert("RGB")).astype(np.float32)
    cm, cs = ca.reshape(-1, 3).mean(0), ca.reshape(-1, 3).std(0) + 1e-6
    pm, ps = pa.reshape(-1, 3).mean(0), pa.reshape(-1, 3).std(0) + 1e-6
    out = np.clip(ca * (1 - strength) + ((ca - cm) / cs * ps + pm) * strength, 0, 255)
    res = Image.fromarray(out.astype(np.uint8)).convert("RGBA")
    res.putalpha(ch.split()[3])
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="station", choices=list(SCENES))
    ap.add_argument("--prompt-scene", default="")
    ap.add_argument("--prompt-char", default="")
    ap.add_argument("--sketch", default="", help="用户草稿路径；空 = 自动生成")
    ap.add_argument("--scene-lora", default="painterly_env.safetensors")
    ap.add_argument("--char-lora", default="soft_style.safetensors")
    ap.add_argument("--ratio", type=float, default=0.24)
    ap.add_argument("--ground-y", type=float, default=0.72)
    ap.add_argument("--x", type=float, default=0.34)
    ap.add_argument("--light", default="left", choices=list(LIGHT_TEXT))
    ap.add_argument("--seed", type=int, default=516001)
    ap.add_argument("--sketch-steps", type=int, default=22)
    ap.add_argument("--scene-t2i", action="store_true", default=True, help="场景段从零生成，草图只作构图契约")
    ap.add_argument("--scene-denoise", type=float, default=0.68)
    ap.add_argument("--char-denoise", type=float, default=0.88)
    args = ap.parse_args()

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(OUT_ROOT, stamp)
    os.makedirs(out_dir, exist_ok=True)

    scene_txt = args.prompt_scene or SCENES[args.scene]
    light = LIGHT_TEXT[args.light]

    # 0) 构图稿
    if args.sketch:
        sketch_path = args.sketch
        sketch = Image.open(sketch_path).convert("RGB").resize((W, H))
        sketch.save(os.path.join(out_dir, "sketch.png"))
        print("[0/4] 用户草图:", sketch_path, flush=True)
    else:
        print("[0/4] 构图稿…", flush=True)
        sp = ("(grayscale tonal value sketch:1.35), (no color:1.25), (soft tonal blocks:1.2), (full-bleed edge to edge:1.2), "
              + scene_txt + ", (a small human figure standing at about %d%% of the frame height:1.35), " % int(args.ratio * 100)
              + "(" + light + ":1.2)")
        ex = expand([{"token": "", "text": sp, "weight": 1, "enabled": True}],
                    [{"token": "", "text": "(detailed textures:1.2), (letterbox:1.3), (black borders:1.3)", "weight": 1, "enabled": True}])
        sketch_path = run(ex["positive"], ex["negative"], "COOP2_sketch", [], args.seed, W, H,
                          steps=args.sketch_steps, cfg=5.0)
        sketch = Image.open(sketch_path).convert("RGB").resize((W, H))
        sketch.save(os.path.join(out_dir, "sketch.png"))
        print("   ", sketch_path, flush=True)

    # 1) 背景线：草图为底图
    print("[1/4] 背景线…", flush=True)
    ex1 = expand([{"token": "", "text": scene_txt + ", (" + light + ":1.2), (photorealistic detail, textured surfaces:1.3), (not a sketch, no flat colors:1.25)", "weight": 1, "enabled": True}],
                 [{"token": "", "text": "(people:1.35), (person:1.3), (two people:1.3)", "weight": 1, "enabled": True}])
    scene_path = run(ex1["positive"], ex1["negative"], "COOP2_scene",
                     [{"name": args.scene_lora, "weight": 1.0}], args.seed, W, H,
                     mode=("t2i" if getattr(args, "scene_t2i", True) else "i2i"),
                     ref=("" if getattr(args, "scene_t2i", True) else sketch_path),
                     denoise=(1.0 if getattr(args, "scene_t2i", True) else args.scene_denoise), steps=28)
    scene = Image.open(scene_path).convert("RGB")
    print("   ", scene_path, flush=True)

    # 2) 人物线：从草图上裁人物区域
    print("[2/4] 人物线…", flush=True)
    fh = int(H * args.ratio)
    fx = int(W * args.x)
    fy = int(H * args.ground_y)
    box = (max(0, fx - int(fh * 0.9)), max(0, fy - fh - int(fh * 0.15)),
           min(W, fx + int(fh * 0.9)), min(H, fy + int(fh * 0.15)))
    crop = sketch.crop(box)
    crop_path = os.path.join(out_dir, "sketch_crop.png")
    crop.save(crop_path)
    use_crop = False
    cp = args.prompt_char or ("1girl, solo, full body standing, long coat, (detailed face and shading:1.3), (not flat colors:1.2), (plain light gray background:1.25), "
                              "(matching the sketch silhouette:1.2), (" + light + ":1.15)")
    ex2 = expand([{"token": "", "text": cp, "weight": 1, "enabled": True}],
                 [{"token": "", "text": "(scenery:1.35), (props:1.2), (cropped feet:1.25)", "weight": 1, "enabled": True}])
    ch_path = run(ex2["positive"], ex2["negative"], "COOP2_char",
                  [{"name": args.char_lora, "weight": 1.0}], args.seed, 768, 1152,
                  mode="i2i" if use_crop else "t2i", ref=crop_path if use_crop else "",
                  denoise=args.char_denoise, steps=28)
    ch = Image.open(ch_path).convert("RGB")
    print("   ", ch_path, flush=True)

    alpha = try_rembg(ch)
    if alpha is None:
        alpha = ch.convert("RGBA")
    alpha.save(os.path.join(out_dir, "char.png"))

    # 3) 合成
    print("[3/4] 合成…", flush=True)
    bb = alpha.getbbox()
    if not bb:
        raise RuntimeError("人物抠图为空")
    piece = alpha.crop(bb)
    target_h = int(H * args.ratio)
    piece = piece.resize((max(1, int(piece.width * target_h / piece.height)), target_h), Image.LANCZOS)
    x0 = fx - piece.width // 2
    y0 = fy - piece.height
    piece = tone_match(piece, scene, x0, fy, 0.28)

    gc = np.asarray(scene.crop((max(0, fx - 60), fy - 10, min(W, fx + 60), min(H, fy + 10)))).reshape(-1, 3).mean(0)
    shadow = Image.new("RGBA", piece.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((piece.width * .2, piece.height * .93, piece.width * .8, piece.height * 1.03),
                                   fill=(int(gc[0] * .4), int(gc[1] * .4), int(gc[2] * .4), 160))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(2, target_h // 16)))
    comp = scene.convert("RGBA")
    comp.alpha_composite(shadow, (x0, y0))
    comp.alpha_composite(piece, (x0, y0))
    raw = os.path.join(out_dir, "comp_raw.png")
    comp.convert("RGB").save(raw)

    # 4) 融合
    print("[4/4] 融合…", flush=True)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rectangle((x0 - 6, y0 - 6, x0 + piece.width + 6, fy + 4), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(10))
    mask_name = "coop2_mask_%dx%d.png" % (W, H)
    mask.save(os.path.join(CI, mask_name))
    ex3 = expand([{"token": "", "text": "(a girl standing on the ground:1.2), (" + light + ":1.15), (contact shadow:1.2)",
                   "weight": 1, "enabled": True}],
                 [{"token": "", "text": "(letterbox:1.2)", "weight": 1, "enabled": True}])
    fused = run(ex3["positive"], ex3["negative"], "COOP2_fuse", [], args.seed, W, H,
                mode="inpaint", ref=raw, mask=mask_name, denoise=0.07, steps=24, cfg=4.8)
    Image.open(fused).convert("RGB").save(os.path.join(out_dir, "comp.png"))

    json.dump({"mode": "coop2", "created": stamp, "sketch": os.path.join(out_dir, "sketch.png"),
               "scene_lora": args.scene_lora, "char_lora": args.char_lora, "ratio": args.ratio,
               "ground_y": args.ground_y, "x": args.x, "light": args.light, "seed": args.seed,
               "layers": {"scene": scene_path, "char": ch_path, "raw": raw, "comp": os.path.join(out_dir, "comp.png")}},
              open(os.path.join(out_dir, "contract.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("done:", out_dir, flush=True)


if __name__ == "__main__":
    main()
