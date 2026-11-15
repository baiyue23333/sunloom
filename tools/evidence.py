# -*- coding: utf-8 -*-
"""合成证据与卡片体检：脚底暗部、湿地倒影、单人全身比例。"""
import numpy as np
from PIL import Image


def card_ok(path, min_aspect=1.15):
    """单卡体检：一个主体、竖向、覆盖率合理、脚在画面内。"""
    import cv2
    im = Image.open(path).convert("RGBA")
    a = np.asarray(im.split()[3])
    cov = float((a > 128).mean())
    if not (0.10 <= cov <= 0.80):
        return False, "coverage %.2f" % cov
    n, _, stats, _ = cv2.connectedComponentsWithStats((a > 128).astype(np.uint8), 8)
    big = [s for s in stats[1:] if s[4] > 0.05 * a.size]
    if len(big) > 1:
        return False, "components %d" % len(big)
    bb = im.getbbox()
    if not bb:
        return False, "empty"
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    if h < w * float(min_aspect):
        return False, "aspect %.2f" % (h / max(1, w))
    if (a.shape[0] - bb[3]) > max(4, a.shape[0] * 0.04):
        return False, "feet gap"
    return True, "ok"


def feet(plate_path, comp_path, box, wet=False):
    """box 归一化 (x0,y0,x1,y1)；返回脚底暗部比例与倒影差异。"""
    p = np.asarray(Image.open(plate_path).convert("L"), dtype=np.float32)
    c = np.asarray(Image.open(comp_path).convert("L"), dtype=np.float32)
    H, W = p.shape
    x0, y0, x1, y1 = [int(v) for v in (box[0] * W, box[1] * H, box[2] * W, box[3] * H)]
    cx = (x0 + x1) // 2
    w = max(6, (x1 - x0) // 2)
    ya, yb = max(0, y1 - 5), min(H, y1 + 9)
    base = p[ya:yb, max(0, cx - w):min(W, cx + w)].mean() + 1e-6
    cur = c[ya:yb, max(0, cx - w):min(W, cx + w)].mean()
    dark = float((base - cur) / base)
    contact = 0.0
    ca, cb = min(H - 1, y1 + 1), min(H, y1 + 7)
    if cb > ca:
        bp2 = p[ca:cb, max(0, cx - w):min(W, cx + w)].mean() + 1e-6
        bc2 = c[ca:cb, max(0, cx - w):min(W, cx + w)].mean()
        contact = float((bp2 - bc2) / bp2)
    refl = 0.0
    if wet and y1 + 10 < H:
        ra, rb = y1 + 4, min(H, y1 + max(24, (y1 - y0) // 3))
        bp = p[ra:rb, max(0, x0):min(W, x1)]
        bc = c[ra:rb, max(0, x0):min(W, x1)]
        if bp.size:
            refl = float(np.abs(bc - bp).mean())
    return {"feet_dark": round(dark, 3), "contact_hard": round(contact, 3),
            "refl_delta": round(refl, 2), "wet": bool(wet)}
