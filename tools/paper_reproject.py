# -*- coding: utf-8 -*-
"""重映：环境先行 → 人物后画（不再用草稿，也不再拼卡片）。

    ① 环境画师先画完整背景（t2i）
    ② 人物画师单独出一张全身，取剪影当蒙版（骨架定位）
    ③ 把剪影按站位贴到背景上，成为「人物区域」
    ④ 人物画师在这块区域里重绘（denoise 高，环境不动）
    ⑤ 接触阴影 + 融光

和线稿法的区别：环境是完整彩图，人物的光、透视、地面都直接继承，
不会出现「彩铅稿」那种半成品感。
"""
import argparse
import json
import os
import sys
import time
import urllib.request

from PIL import Image, ImageDraw, ImageFilter
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cutout
import fusion
import paper_lineart as pl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = pl.API
CI = pl.CI
CHAR_LORA = "artist_style.safetensors"
MIO_LORAS = [{"name": "artist_style.safetensors", "weight": 1.0},
             {"name": "character_lora.safetensors", "weight": 1.0}]
ENV_LORA = "env_style.safetensors"
W, H = 1344, 768


def _wait(jid, t=900):
    t0 = time.time()
    while time.time() - t0 < t:
        time.sleep(2)
        st = pl.get(API + "/api/job/" + jid)
        if st.get("status") in ("done", "error"):
            imgs = (st.get("result") or {}).get("images") or []
            if not imgs:
                raise RuntimeError(str(st.get("result"))[:300])
            return imgs[0]
    raise TimeoutError(jid)


def scene_plate(scene, lora, w, weight, seed):
    body = {"prompt": scene + ", (detailed background:1.2), (cinematic lighting:1.1)",
            "negative": "text, watermark, lowres, blurry, character, person, people",
            "width": W, "height": H, "steps": 30, "cfg": 5.5, "seed": seed,
            "prefix": "REPROJECT_plate", "mode": "t2i", "save_to": "paper",
            "loras": [{"name": lora, "weight": weight}]}
    return _wait(pl.post(API + "/api/run", body)["job_id"])


def char_figure(char, lora, weight, seed, loras=None):
    body = {"prompt": char + ", (full body:1.3), (standing:1.2), white background, simple pose",
            "negative": "text, watermark, lowres, blurry, multiple people, cropped, close-up",
            "width": 832, "height": 1216, "steps": 28, "cfg": 5.2, "seed": seed,
            "prefix": "REPROJECT_char", "mode": "t2i", "save_to": "paper",
            "loras": [{"name": lora, "weight": weight}]}
    return _wait(pl.post(API + "/api/run", body)["job_id"])


def repaint(plate, mask_name, prompt, negative, denoise, lora, weight, seed, steps=30, cfg=5.5, loras=None):
    body = {"prompt": prompt, "negative": negative, "mode": "inpaint",
            "reference": plate, "mask": mask_name, "denoise": denoise,
            "steps": steps, "cfg": cfg, "seed": seed, "prefix": "REPROJECT_char",
            "save_to": "paper", "width": W, "height": H,
            "loras": loras or [{"name": lora, "weight": weight}]}
    return _wait(pl.post(API + "/api/run", body)["job_id"])


def compose_mask(figure, box, out_dir, feather=6):
    """人物剪影 → 画布蒙版。"""
    matte = cutout.make_matte(figure, backend="birefnet", crop=False)
    if isinstance(matte, str):
        matte = Image.open(matte)
    a = matte.convert("RGBA").split()[3]
    x0, y0, x1, y1 = box
    canvas = Image.new("L", (W, H), 0)
    canvas.paste(a.resize((x1 - x0, y1 - y0), Image.LANCZOS), (x0, y0))
    canvas = canvas.filter(ImageFilter.GaussianBlur(feather))
    name = "reproject_mask_%s.png" % time.strftime("%H%M%S")
    Image.merge("RGB", (canvas, canvas, canvas)).save(os.path.join(CI, name))
    canvas.save(os.path.join(out_dir, "mask_char.png"))
    return name, canvas


def shadow(canvas, box, strength=150):
    x0, y0, x1, y1 = box
    cx = (x0 + x1) // 2
    hw = max(12, int((x1 - x0) * 0.55))
    hh = max(6, int((y1 - y0) * 0.02))
    sh = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sh).ellipse((cx - hw, y1 - hh, cx + hw, y1 + hh * 1.5), fill=strength)
    sh = sh.filter(ImageFilter.GaussianBlur(10))
    arr = np.asarray(canvas).astype(np.float32)
    arr *= (1 - np.asarray(sh, dtype=np.float32)[..., None] / 255.0 * 0.8)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def run(scene, char, out_dir, seed=2026, char_x=0.42, char_h=0.62, ground=0.92,
        env_w=0.6, char_w=0.65, denoise=0.85):
    os.makedirs(out_dir, exist_ok=True)
    log = []

    t0 = time.time()
    plate = scene_plate(scene, ENV_LORA, env_w, 0.55, seed)
    log.append(("plate", round(time.time() - t0)))
    Image.open(plate).save(os.path.join(out_dir, "01_plate.png"))
    print("[plate] %.0fs" % (time.time() - t0), flush=True)

    # 7B 读背景板：拿到互动动作和可依靠物的大致横向位置
    plan = {}
    try:
        import paper_conductor
        plan = paper_conductor.plan(plate, None, scene)
        print("[conductor] %s | %s" % (plan.get("by"), (plan.get("interaction") or "")[:70]), flush=True)
    except Exception as e:  # noqa: BLE001
        print("[conductor] 跳过:", str(e)[:80], flush=True)
    inter = (plan.get("interaction") or "").strip()
    fgs = plan.get("foreground") or []
    if char_x <= 0 and not fgs:
        char_x = 0.5
        print("[anchor] 无前景框，回退 x=0.50", flush=True)
    if char_x <= 0 and fgs:
        char_x = max(0.25, min(0.75, float(fgs[0].get("x", 0.5))))
        print("[anchor] 按锚点定位 x=%.2f" % char_x, flush=True)

    t0 = time.time()
    CL = MIO_LORAS if os.environ.get("REPROJECT_MIO") else None
    inter_txt = (char + ", " + inter) if inter else char
    fig = char_figure(inter_txt, CHAR_LORA, char_w, seed, loras=CL)
    log.append(("figure", round(time.time() - t0)))
    Image.open(fig).save(os.path.join(out_dir, "02_figure.png"))
    print("[char] %.0fs" % (time.time() - t0), flush=True)

    fh = int(H * char_h)
    fw = int(fh * 0.46)
    cx, feet = int(W * char_x), int(H * ground)
    box = (max(0, cx - fw // 2), max(0, feet - fh), min(W, cx + fw // 2), min(H, feet))

    t0 = time.time()
    mask_name, mask = compose_mask(fig, box, out_dir)
    log.append(("mask", round(time.time() - t0)))
    print("[mask] %.0fs 覆盖 %.1f%%" % (time.time() - t0, np.asarray(mask).mean() / 255 * 100), flush=True)

    t0 = time.time()
    out = repaint(plate, mask_name,
                  (char + ", " + inter + ", same art style") if inter else char + ", same art style",
                  "text, watermark, lowres, blurry, multiple people, cropped limbs",
                  denoise, CHAR_LORA, char_w, seed + 1, loras=CL)
    log.append(("repaint", round(time.time() - t0)))
    print("[repaint] %.0fs" % (time.time() - t0), flush=True)

    comp = Image.open(out).convert("RGB")
    comp.save(os.path.join(out_dir, "03_reproject.png"))

    # 融光 + 接触阴影
    try:
        graded, _ = fusion.lowfreq_match(comp.crop(box).convert("RGBA"), comp, box, weight=0.18)
        m = mask.crop(box).filter(ImageFilter.GaussianBlur(3))
        comp.paste(graded.convert("RGB"), box, m)
    except Exception as e:  # noqa: BLE001
        print("[fusion] 跳过", str(e)[:80], flush=True)
    comp = shadow(comp, box)
    final = os.path.join(out_dir, "comp.png")
    comp.save(final)
    json.dump({"steps": log, "box": box, "mask": mask_name}, open(os.path.join(out_dir, "plan.json"), "w"))
    return final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True)
    ap.add_argument("--char", required=True)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--x", type=float, default=0.0, help="<=0 表示由 7B 锚点决定")
    ap.add_argument("--char-h", type=float, default=0.62)
    ap.add_argument("--ground", type=float, default=0.92)
    ap.add_argument("--denoise", type=float, default=0.85)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    out = a.out or os.path.join(ROOT, "SD-Picture", "reproject", time.strftime("%Y%m%d_%H%M%S"))
    p = run(a.scene, a.char, out, a.seed, a.x, a.char_h, a.ground, denoise=a.denoise)
    print("OK", p)


if __name__ == "__main__":
    main()
