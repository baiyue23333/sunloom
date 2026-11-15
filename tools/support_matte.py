# -*- coding: utf-8 -*-
"""实验：给透明卡铺「互补支撑色」再重抠（3D 打印支撑思路）。

结论：后处理阶段铺支撑不能恢复已经和原背景混合的发梢；
支撑色还可能被 BiRefNet 判成主体（实测出现黑块）。
保留为实验工具，不接入主流程。
"""
import os
import numpy as np
from PIL import Image


def _nearest_fg(rgb, a, iters=64):
    import cv2
    known = (a > 40).astype(np.uint8)
    col = rgb.astype(np.float32).copy()
    k = np.ones((3, 3), np.uint8)
    for _ in range(iters):
        dil = cv2.dilate(col, k)
        kd = cv2.dilate(known, k)
        new = (known == 0) & (kd > 0)
        if not new.any():
            break
        col[new] = dil[new]
        known[new] = 1
    return col


def support_image(rgba):
    """背景 = 最近前景色的反色；边缘按当前 alpha 混合。"""
    a = np.asarray(rgba.split()[3], dtype=np.float32) / 255.0
    rgb = np.asarray(rgba.convert("RGB"), dtype=np.float32)
    bg = 255.0 - _nearest_fg(rgb, a * 255)
    out = a[..., None] * rgb + (1 - a[..., None]) * bg
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def iterate(card_path, out_dir, rounds=2):
    """铺支撑 -> 重抠，最多 rounds 轮；返回最后一轮路径。"""
    from cutout import comfy_cutout
    os.makedirs(out_dir, exist_ok=True)
    im = Image.open(card_path).convert("RGBA")
    cur = os.path.join(out_dir, "round0.png")
    im.save(cur)
    for i in range(1, rounds + 1):
        sup = support_image(im)
        sp = os.path.join(out_dir, "support%d.png" % i)
        sup.save(sp)
        nxt = os.path.join(out_dir, "round%d.png" % i)
        comfy_cutout(sp, nxt)
        im = Image.open(nxt).convert("RGBA")
        cur = nxt
    return cur
