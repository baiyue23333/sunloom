# -*- coding: utf-8 -*-
"""按模板重绘手部：给「捏 / 握 / 张掌」定姿势，而不是靠提示词猜。

模板来自 SDPose 的 21 点，已归一化到「腕→中指根」坐标系，存在 ref/hand_grips.json。
应用时用目标手的腕 + 中指根做相似变换，把模板贴到这只手上。
"""
import argparse
import json
import math
import os
import sys
import time

from PIL import Image, ImageDraw, ImageFilter
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hand_precise as hp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL_PATH = os.path.join(ROOT, "ref", "hand_grips.json")
CI = hp.CI


def load(grip=None):
    d = json.load(open(TPL_PATH, encoding="utf-8"))
    if grip:
        if grip not in d:
            raise KeyError("没有模板 %s，可选 %s" % (grip, list(d)))
        return {grip: d[grip]}
    return d


def fit(points, wrist, mcp, scale=1.0):
    """把归一化模板放到目标手的坐标系里。"""
    dx, dy = mcp[0] - wrist[0], mcp[1] - wrist[1]
    L = (math.hypot(dx, dy) or 1.0) * scale
    ux, uy = dx / L, dy / L
    vx, vy = -uy, ux
    out = []
    for nx, ny in points:
        x = wrist[0] + (nx * vx + ny * ux) * L
        y = wrist[1] + (nx * vy + ny * uy) * L
        out.append((x, y))
    return out


def hull_of(points, expand=0.15):
    import cv2
    arr = np.array([[int(x), int(y)] for x, y in points], dtype=np.int32)
    hull = cv2.convexHull(arr)
    cx, cy = hull[:, 0, 0].mean(), hull[:, 0, 1].mean()
    return [[int(cx + (x - cx) * (1 + expand)), int(cy + (y - cy) * (1 + expand))]
            for x, y in hull[:, 0, :]]


def apply(src, grip, prompt, negative="", hand="auto", scale=1.0, denoise=0.6, seed=0,
          loras=None, show_guide=True):
    raw = hp.detect_raw(src)
    boxes = raw.get("boxes") or []
    if not boxes:
        raise RuntimeError("没有检测到手")
    if hand == "auto":
        b = dict(boxes[0])
    else:
        cand = [x for x in boxes if x.get("hand") == hand] or boxes
        b = dict(cand[0])

    # 目标手的 21 点（用于定位模板）
    pts = hp.hand_points(raw.get("json"), b.get("hand", "right"))
    if not pts:
        raise RuntimeError("拿不到目标手关键点")
    wrist, mcp = pts[0], pts[9]
    tpl = load(grip)[grip]["points"]
    fitted = fit(tpl, wrist, mcp, scale)
    b["polygon"] = hull_of(fitted, 0.18)
    b["guide"] = fitted if show_guide else None
    dst, meta = hp.repaint(src, b, prompt, negative, denoise, 3.0, 0.32, seed=seed, loras=loras)
    meta["grip"] = grip
    meta["hand"] = b.get("hand")
    return dst, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--grip", default="power", choices=["power", "palm", "pinch"])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--negative", default="")
    ap.add_argument("--hand", default="auto")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--denoise", type=float, default=0.6)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-guide", action="store_true")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    t0 = time.time()
    dst, meta = apply(a.src, a.grip, a.prompt, a.negative, a.hand, a.scale,
                      a.denoise, a.seed, show_guide=not a.no_guide)
    if a.out:
        import shutil
        shutil.copy2(dst, a.out)
        dst = a.out
    print("结果:", dst)
    print("调试:", json.dumps(meta, ensure_ascii=False))
    print("复检:", json.dumps(hp.verify(dst), ensure_ascii=False))
    print("用时 %.0fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
