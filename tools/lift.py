# -*- coding: utf-8 -*-
"""从背景板按 bbox 剥离物件：BiRefNet 优先，GrabCut 兜底。"""
import os

import numpy as np
from PIL import Image

from cutout import CutoutError, comfy_cutout


def _grabcut(crop, dst):
    import cv2
    im = cv2.imread(crop)
    if im is None:
        return None
    h, w = im.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    rect = (max(1, w // 12), max(1, h // 12), max(2, w - w // 6), max(2, h - h // 6))
    try:
        cv2.grabCut(im, mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
    except Exception:
        return None
    a = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    a = cv2.GaussianBlur(a, (3, 3), 0.6)
    rgba = np.dstack([cv2.cvtColor(im, cv2.COLOR_BGR2RGB), a])
    im2 = Image.fromarray(rgba, "RGBA")
    bb = im2.getbbox()
    if not bb:
        return None
    im2.crop(bb).save(dst)
    return dst


def lift_poly(plate_path, polygon, dst):
    """多边形种子 GrabCut 剥离；失败返回 None。"""
    import cv2
    from cutout import defringe
    if not polygon or len(polygon) < 4:
        return None
    plate = Image.open(plate_path).convert("RGB")
    W, H = plate.size
    pts = [(max(0, min(W - 1, int(x * W))), max(0, min(H - 1, int(y * H)))) for x, y in polygon]
    if len(pts) < 4:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    pad = 6
    x0, y0 = max(0, min(xs) - pad), max(0, min(ys) - pad)
    x1, y1 = min(W, max(xs) + pad), min(H, max(ys) + pad)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    crop = plate.crop((x0, y0, x1, y1))
    crop.save(dst.replace(".png", "_poly.png"))
    img = cv2.cvtColor(np.asarray(crop), cv2.COLOR_RGB2BGR)
    mask = np.zeros(img.shape[:2], np.uint8)
    cv2.fillPoly(mask, [np.array([[(x - x0), (y - y0)] for x, y in pts], np.int32)], 255)
    mask[mask == 0] = cv2.GC_PR_BGD
    mask[mask == 255] = cv2.GC_PR_FGD
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(img, mask, None, bgd, fgd, 4, cv2.GC_INIT_WITH_MASK)
    except Exception:
        return None
    a = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    im = Image.fromarray(np.dstack([np.asarray(crop), a]), "RGBA")
    bb = im.getbbox()
    if not bb:
        return None
    im = defringe(im.crop(bb))
    if (np.asarray(im.split()[3]) > 250).mean() < 0.03:
        return None
    im.save(dst)
    return dst


def lift(plate_path, bbox, dst):
    """bbox 归一化 [x0,y0,x1,y1]；失败返回 None。"""
    plate = Image.open(plate_path).convert("RGB")
    W, H = plate.size
    x0, y0, x1, y1 = bbox
    mx, my = (x1 - x0) * 0.04, (y1 - y0) * 0.04
    box = (max(0, int((x0 - mx) * W)), max(0, int((y0 - my) * H)),
           min(W, int((x1 + mx) * W)), min(H, int((y1 + my) * H)))
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        return None
    crop = dst.replace(".png", "_crop.png")
    plate.crop(box).save(crop)
    ok = False
    try:
        comfy_cutout(crop, dst)
        a = np.asarray(Image.open(dst).split()[3], dtype=np.float32)
        ok = (a > 250).mean() >= 0.05
    except (CutoutError, OSError):
        ok = False
    if not ok:
        if not _grabcut(crop, dst):
            return None
        a = np.asarray(Image.open(dst).split()[3], dtype=np.float32)
        if (a > 250).mean() < 0.03:
            return None
    return dst
