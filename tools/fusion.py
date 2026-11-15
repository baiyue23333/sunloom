# -*- coding: utf-8 -*-
"""低频光照匹配与地面切线：把人物卡并进场景，而不是整张套色。"""
import math
import numpy as np
from PIL import Image, ImageFilter


def _lum(rgb):
    return float(0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2])


def ring_stats(plate, box, pad=0.12):
    """人物框外扩环带（排除人物本体）的均值色。box 为像素坐标。"""
    W, H = plate.size
    x0, y0, x1, y1 = box
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    ex0, ey0 = int(max(0, x0 - w * pad)), int(max(0, y0 - h * pad))
    ex1, ey1 = int(min(W, x1 + w * pad)), int(min(H, y1 + h * pad))
    crop = np.asarray(plate.crop((ex0, ey0, ex1, ey1)), dtype=np.float32)
    if crop.size == 0:
        return (128.0, 128.0, 128.0)
    # 中间挖掉人物框，避免把人物自己算进环境
    cx0, cy0 = x0 - ex0, y0 - ey0
    cx1, cy1 = min(crop.shape[1], x1 - ex0), min(crop.shape[0], y1 - ey0)
    m = np.ones(crop.shape[:2], bool)
    if cx1 > cx0 and cy1 > cy0:
        m[max(0, cy0):cy1, max(0, cx0):cx1] = False
    if not m.any():
        m[:] = True
    return tuple(float(v) for v in crop[m].mean(axis=0))


def lowfreq_match(card, plate, box, weight=0.55, radius=None):
    """只搬低频色偏，保留卡片高频细节。返回 (RGBA, 环带均值)。"""
    W, H = plate.size
    x0, y0, x1, y1 = [int(v) for v in box]
    cw, ch = max(1, x1 - x0), max(1, y1 - y0)
    ring = ring_stats(plate, (x0, y0, x1, y1))
    rgb = card.convert("RGB")
    r = max(4, int((radius or ch / 12.0)))
    low = np.asarray(rgb.filter(ImageFilter.GaussianBlur(r)), dtype=np.float32)
    base = np.asarray(rgb, dtype=np.float32)
    delta = np.array(ring, dtype=np.float32) - low.reshape(-1, 3).mean(axis=0)
    delta = np.clip(delta, -18, 18) * float(weight)
    out = np.clip(base + delta[None, None, :], 0, 255).astype(np.uint8)
    im = Image.fromarray(out, "RGB").convert("RGBA")
    im.putalpha(card.split()[3])
    return im, ring


def ground_tangent(points, x):
    """地面折线在 x 处的切线角（像素坐标，y 向下）。"""
    pts = sorted([(float(p[0]), float(p[1])) for p in (points or [])])
    for i in range(len(pts) - 1):
        if pts[i][0] <= x <= pts[i + 1][0]:
            dx = pts[i + 1][0] - pts[i][0]
            dy = pts[i + 1][1] - pts[i][1]
            return math.atan2(dy, max(1e-6, dx))
    return 0.0


def local_lum(plate, cx, cy, r=18):
    W, H = plate.size
    crop = plate.crop((max(0, cx - r), max(0, cy - r), min(W, cx + r), min(H, cy + r)))
    if crop.size[0] == 0:
        return 128.0
    return float(np.asarray(crop.convert("L"), dtype=np.float32).mean())


def ellipse_points(cx, cy, a, b, ang, n=48):
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    ca, sa = math.cos(ang), math.sin(ang)
    x = cx + a * np.cos(t) * ca - b * np.sin(t) * sa
    y = cy + a * np.cos(t) * sa + b * np.sin(t) * ca
    return list(zip(x.tolist(), y.tolist()))
