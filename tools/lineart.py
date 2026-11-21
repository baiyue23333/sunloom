# -*- coding: utf-8 -*-
"""线稿层：从抠好的图上抽线 → 白底让模型重画一遍 → multiply 叠回去。

为什么要从抠图结果抽线，而不是单独生成一张线稿：
    我们的底模是 Qwen-Image，没有可用的 ControlNet（models/controlnet 里只有一个
    SD15 专用的 union 模型；comfyui_controlnet_aux 处于 .disabled）。
    两次独立生成无法保证姿势一致，线稿就叠不上。从同一张图抽线，对齐是 1:1 的。

为什么在**白底**重画：
    上一次 relign 在纯绿底上做 i2i，饱和绿经 VAE 往返产生品红噪点（实测描线覆盖率
    0.789 → 0.452）。白底没有这个问题。

用法：
    python tools/lineart.py --in 抠图.png --out 结果.png [--denoise 0.30] [--strength 0.55]
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
import cv2
from PIL import Image

PROMPT = ("clean black lineart on pure white background, continuous ink outlines, "
          "anime illustration line drawing, uniform line weight")
NEG = ("(broken outline:1.4), (dashed line:1.35), dotted line, gray shading, color, "
       "gradient, background objects, blurry, jpeg artifacts")


def _post(path, body):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def _get(path):
    with urllib.request.urlopen(API + path, timeout=60) as r:
        return json.loads(r.read().decode())


def extract_lines(rgba, lo=12.0, hi=52.0):
    """从 RGBA 里抽线：明显暗于局部中值的位置算线。返回 0..1 的线强度。"""
    arr = np.asarray(rgba).astype(np.float32)
    rgb, a = arr[..., :3], arr[..., 3] / 255.0
    L = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    bg = cv2.medianBlur(np.clip(L, 0, 255).astype(np.uint8), 9).astype(np.float32)
    m = np.clip((bg - L - lo) / max(1e-3, hi - lo), 0, 1)
    m = cv2.GaussianBlur(m, (3, 3), 0.6)
    return m * (a > 0.02)


def to_white(m):
    """线强度 → 白底黑线图。"""
    g = (255.0 * (1.0 - np.clip(m, 0, 1))).astype(np.uint8)
    return Image.fromarray(np.dstack([g, g, g]), "RGB")


def redraw(line_png, out_ref, denoise=0.30, seed=0, steps=24, cfg=4.5):
    line_png.save(out_ref)
    body = {"mode": "keep_image", "reference": out_ref, "prompt": PROMPT, "negative": NEG,
            "denoise": float(denoise), "width": int(line_png.width), "height": int(line_png.height),
            "steps": int(steps), "cfg": float(cfg), "seed": int(seed), "prefix": "lineart",
            "loras": []}
    jid = _post("/api/reproduce", body)["job_id"]
    for _ in range(400):
        time.sleep(2)
        j = _get("/api/job/" + jid)
        if j.get("status") in ("done", "error", "cancelled"):
            if j["status"] != "done":
                raise RuntimeError("线稿重画失败: %s" % (j.get("error", "")[:200]))
            return j["result"]["images"][0]
    raise RuntimeError("线稿重画超时")


def _line_from_white(path):
    """白底重画图 → 线强度（0=白，1=黑）。"""
    im = Image.open(path).convert("RGB")
    g = np.asarray(im).astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    return np.clip((255.0 - g) / 255.0, 0, 1)


def overlay(rgba, line_m, strength=0.55):
    arr = np.asarray(rgba).astype(np.float32)
    rgb, a = arr[..., :3], arr[..., 3]
    m = (np.clip(line_m, 0, 1) * (a > 20) * float(strength))[..., None]
    out = rgb * (1.0 - m)
    return Image.fromarray(np.dstack([np.clip(out, 0, 255), a]).astype(np.uint8), "RGBA")


def build(src_rgba, out_path, denoise=0.30, strength=0.55, seed=0, keep=None):
    d = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(d, exist_ok=True)
    ref = keep or os.path.join(d, "_lineart_ref.png")
    m0 = extract_lines(src_rgba)
    line_png = to_white(m0)
    draw_path = redraw(line_png, ref, denoise=denoise, seed=seed)
    m1 = _line_from_white(draw_path)
    # 只用重画图里"有内容"的部分，避免它把整片涂灰
    cover = float((m1 > 0.2).mean())
    if cover < 0.002 or cover > 0.6:
        raise RuntimeError("线稿重画不可用（覆盖率 %.3f）" % cover)
    out = overlay(src_rgba, m1, strength=strength)
    out.save(out_path)
    return {"out": out_path, "ref": ref, "redraw": draw_path, "cover": cover}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True, help="已抠好的 RGBA 图")
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--denoise", type=float, default=0.30)
    ap.add_argument("--strength", type=float, default=0.55)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    r = build(Image.open(a.src).convert("RGBA"), a.dst, denoise=a.denoise,
              strength=a.strength, seed=a.seed)
    print("OK", r["out"], "| 线覆盖 %.3f" % r["cover"])


if __name__ == "__main__":
    main()
