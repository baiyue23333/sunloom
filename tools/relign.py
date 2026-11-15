# -*- coding: utf-8 -*-
"""抠完之后让模型重描一次边。

流程：
  ① 原图 → hybrid matte（形+色）
  ② 合成到纯绿底 → ref.png
  ③ 站台 /api/reproduce (keep_image) 低 denoise 跑一遍，让模型重描线条
  ④ 重画图 → chroma 取色；**形状仍用 ① 的 alpha**
  ⑤ 出图

用法：
  python tools/relign.py --in 原图.png --out 结果.png [--denoise 0.3] [--seed 0]
"""
import argparse
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
API = "http://127.0.0.1:8770"

import numpy as np
from PIL import Image
import cutout

PROMPT = ("clean continuous lineart, (unbroken outer contour:1.4), same character, same pose, "
          "same colors, flat pure green background, crisp thin outlines, anime illustration")
NEG = ("(broken outline:1.4), (dashed line:1.35), (dotted line:1.3), (green rim light:1.35), "
       "extra objects, changed pose, changed hairstyle, blurry, jpeg artifacts")


def _post(path, body):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def _get(path):
    with urllib.request.urlopen(API + path, timeout=60) as r:
        return json.loads(r.read().decode())


def green_ref(src, ref_path, rgb=(0, 255, 0)):
    """把 hybrid matte 合成到纯绿底，作为 i2i 参考图。"""
    sub = cutout.hybrid_matte(src)
    bg = Image.new("RGB", sub.size, rgb)
    bg.paste(sub, (0, 0), sub)
    bg.save(ref_path)
    return sub, bg.size


def redraw(ref_path, size, denoise=0.30, seed=0, steps=24, cfg=4.5):
    body = {"mode": "keep_image", "reference": ref_path, "prompt": PROMPT, "negative": NEG,
            "denoise": float(denoise), "width": int(size[0]), "height": int(size[1]),
            "steps": int(steps), "cfg": float(cfg), "seed": int(seed),
            "prefix": "relign", "loras": [{"name": "character_lora.safetensors", "weight": 0.8},
                                          {"name": "artist_style.safetensors", "weight": 0.85}]}
    r = _post("/api/reproduce", body)
    jid = r["job_id"]
    for _ in range(400):
        time.sleep(2)
        j = _get("/api/job/" + jid)
        if j.get("status") in ("done", "error", "cancelled"):
            if j["status"] != "done":
                raise RuntimeError("重画失败: %s" % j.get("error", "")[:200])
            return j["result"]["images"][0]
    raise RuntimeError("重画超时")


def build(src, out_path, denoise=0.30, seed=0, keep_ref=None):
    """核心：形状用原 matte，颜色用重画图。"""
    ref_path = keep_ref or os.path.join(os.path.dirname(os.path.abspath(out_path)), "_relign_ref.png")
    sub, size = green_ref(src, ref_path)
    draw_path = redraw(ref_path, size, denoise=denoise, seed=seed)
    # 重画图取色（chroma 已经做了去绿 + 去污染）
    color = cutout.make_matte(draw_path, backend="chroma", crop=False)
    if color.size != size:
        color = color.resize(size, Image.LANCZOS)
    ca = np.asarray(color).astype(np.float32)
    sa = np.asarray(sub.split()[-1]).astype(np.float32)
    out = Image.fromarray(np.dstack([ca[..., :3], sa]).astype(np.uint8), "RGBA")
    out = cutout.flatten_rim_color(out)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    out.save(out_path)
    return {"out": out_path, "ref": ref_path, "redraw": draw_path, "size": size}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--denoise", type=float, default=0.30)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    r = build(a.src, a.dst, denoise=a.denoise, seed=a.seed)
    print("OK", r["out"])
    print("参考图", r["ref"])
    print("重画图", r["redraw"])


if __name__ == "__main__":
    main()
