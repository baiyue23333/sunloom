# -*- coding: utf-8 -*-
"""抠图基准：固定样本 × 多后端，算出光晕/发丝/实心度，出一张对比表。

用法：
    python tools/matte_bench.py                 # 全部样本 × 全部组合
    python tools/matte_bench.py --backends birefnet --modes soft
    python tools/matte_bench.py --limit 3

产物：
    SD-Picture/_matte_bench/<组合>/<样本>.png      绿底合成（看白边）
    SD-Picture/_matte_bench/metrics.json          数值
    SD-Picture/_matte_bench/对比总表.png           人眼复核用
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cutout  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "SD-Picture", "_matte_bench")
GREEN = np.array([0, 255, 0], np.float32)

# 固定样本：白底立绘（最难）+ 服装板 + 带背景的图
SOURCES = [
    "产出作品/风格参考/立绘_全身/初始服装_精细.png",
    "产出作品/风格参考/立绘_全身/anima_turbo12.png",
    "产出作品/风格参考/立绘_全身/sheetC.png",
    "产出作品/风格参考/立绘_全身/poseD.png",
    "产出作品/2026/11/13/服装参考/01_slip.png",
    "产出作品/2026/11/13/服装参考/09_yukata.png",
    "产出作品/2026/11/13/服装参考/30_lab_coat.png",
    "SD-Picture/station_out/garment_initial_124914_s707919.png",
    "SD-Picture/station_out/garment_gala_143250_s731676.png",
    "SD-Picture/station_out/garment_hanfu_132253_s795028.png",
]


def load_rgba(path):
    im = Image.open(path).convert("RGB")
    w = 900
    if im.width > w:
        im = im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)
    return im


def nearest_fg(rgb, a):
    """每个像素的"应该是的前景色" = 最近实心像素的颜色（和 cutout 用同一套）。"""
    from scipy import ndimage
    known = a > 0.95
    if not known.any():
        return rgb.copy()
    idx = ndimage.distance_transform_edt(~known, return_distances=False, return_indices=True)
    return rgb[tuple(idx)]


def metrics(rgba):
    """halo 越低越好；soft 越高=发丝留得多；fill 越高=白衣服没破洞。"""
    import cv2
    rgb = np.asarray(rgba.convert("RGB")).astype(np.float32)
    a = np.asarray(rgba.split()[-1]).astype(np.float32) / 255.0
    band = (a > 0.10) & (a < 0.90)
    fg = nearest_fg(rgb, a)
    bgmask = a < 0.02
    bcol = np.median(rgb[bgmask].reshape(-1, 3), axis=0) if bgmask.sum() > 64 else GREEN
    scale = np.maximum(1.0, np.linalg.norm(fg[band] - bcol[None, :], axis=1)) if band.any() else np.array([1.0])
    # 污染度：边缘颜色里混进了多少背景色（0=干净，1=完全是背景色）
    halo = float(np.clip(np.linalg.norm(rgb[band] - fg[band], axis=1) / scale, 0, 1).mean() * 100) if band.any() else 0.0
    solid = a > 0.02
    soft = float(((a > 0.02) & (a < 0.5)).sum()) / max(1, int(solid.sum()))
    core = cv2.erode((a > 0.5).astype(np.uint8), np.ones((11, 11), np.uint8)) > 0
    fill = float((a[core] > 0.95).mean()) if core.any() else 0.0
    return {"halo": round(halo, 2), "soft": round(soft, 4), "fill": round(fill, 3),
            "size": [rgba.width, rgba.height]}


def green_comp(rgba):
    rgb = np.asarray(rgba.convert("RGB")).astype(np.float32)
    a = np.asarray(rgba.split()[-1]).astype(np.float32) / 255.0
    out = rgb * a[..., None] + GREEN * (1 - a[..., None])
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def raw_for(tmp, backend, cache):
    """同一个后端只跑一次模型，两种去污模式复用结果。"""
    if backend not in cache:
        t0 = time.time()
        rgba = cutout.raw_matte(tmp, backend=backend)
        bb = rgba.getbbox()
        if bb:
            rgba = rgba.crop(bb)
        cache[backend] = (rgba, time.time() - t0)
    return cache[backend]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backends", default="birefnet,u2net,color")
    ap.add_argument("--modes", default="hard,soft,clean")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    combos = []
    for b in [x.strip() for x in a.backends.split(",") if x.strip()]:
        for m in [x.strip() for x in a.modes.split(",") if x.strip()]:
            if b == "color" and m == "hard":
                continue
            combos.append((b, m))

    srcs = SOURCES[:a.limit] if a.limit else SOURCES
    os.makedirs(OUT, exist_ok=True)
    results = {}
    rows = []

    for rel in srcs:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            print("跳过（不存在）", rel, flush=True)
            continue
        im = load_rgba(path)
        tmp = os.path.join(OUT, "_src.png")
        im.save(tmp)
        name = os.path.splitext(os.path.basename(rel))[0]
        row = {"source": name}
        cache = {}
        for (b, m) in combos:
            key = b + "-" + m
            try:
                raw, secs = raw_for(tmp, b, cache)
                t1 = time.time()
                rgba = cutout.defringe(raw, mode=m)
                secs = secs + (time.time() - t1)
            except Exception as e:  # noqa: BLE001
                print("  %-18s %-6s FAIL %s" % (name[:18], b, str(e)[:80]), flush=True)
                row[key] = {"error": str(e)[:120]}
                continue
            d = os.path.join(OUT, key)
            os.makedirs(d, exist_ok=True)
            green_comp(rgba).save(os.path.join(d, name + ".png"))
            mt = metrics(rgba)
            mt["secs"] = round(secs, 2)
            row[key] = mt
            print("  %-18s %-16s halo %5.2f  soft %.3f  fill %.3f  %4.1fs"
                  % (name[:18], key, mt["halo"], mt["soft"], mt["fill"], secs), flush=True)
        results[name] = row
        rows.append((name, row))
    try:
        os.remove(os.path.join(OUT, "_src.png"))
    except OSError:
        pass

    with open(os.path.join(OUT, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)

    # 对比总表：一行一个样本，一格一个组合（绿底缩略图 + halo）
    W = 150
    cells = []
    for name, row in rows:
        line = []
        for (b, m) in combos:
            key = b + "-" + m
            p = os.path.join(OUT, key, name + ".png")
            if not os.path.isfile(p):
                line.append(None)
                continue
            t = Image.open(p).convert("RGB")
            h = int(t.height * W / t.width)
            t = t.resize((W, h), Image.LANCZOS)
            d = ImageDraw.Draw(t)
            mt = row.get(key) or {}
            d.rectangle((0, 0, W, 16), fill=(0, 0, 0))
            d.text((3, 3), "%s h%.1f s%.2f" % (b[:6], mt.get("halo", 0), mt.get("soft", 0)), fill=(255, 255, 255))
            line.append(t)
        cells.append((name, line))
    if cells:
        ch = max(t.height for _, line in cells for t in line if t)
        sheet = Image.new("RGB", (W * len(combos), ch * len(cells)), (245, 245, 245))
        for i, (name, line) in enumerate(cells):
            for j, t in enumerate(line):
                if t:
                    sheet.paste(t, (j * W, i * ch))
        sheet.save(os.path.join(OUT, "对比总表.png"))
        print("对比总表:", os.path.join(OUT, "对比总表.png"))
    print("指标:", os.path.join(OUT, "metrics.json"))


if __name__ == "__main__":
    main()