# -*- coding: utf-8 -*-
"""glitchify.py - 真实故障后期：大块破坏 / 切片位移 / 通道错位 / 胶片颗粒"""
import random, sys
from PIL import Image, ImageEnhance
import numpy as np

def glitchify(src, dst, intensity=0.6, seed=None, desat=0.35, grain=0.06):
    random.seed(seed)
    np.random.seed(seed or 0)
    im = Image.open(src).convert("RGB")
    w, h = im.size
    arr = np.array(im).astype(np.int16)

    # 1) 通道错位
    s = max(2, int(4 * intensity))
    arr[:, :, 0] = np.roll(arr[:, :, 0], s, axis=1)
    arr[:, :, 2] = np.roll(arr[:, :, 2], -s, axis=1)

    # 2) 大块破坏：黑块 / 彩色噪点 / 偏移切片
    n = int(10 + 14 * intensity)
    for _ in range(n):
        bw = random.randint(int(w * 0.06), int(w * 0.32))
        bh = random.randint(int(h * 0.03), int(h * 0.12))
        x = random.randint(0, max(0, w - bw)); y = random.randint(0, max(0, h - bh))
        r = random.random()
        if r < 0.5:
            arr[y:y+bh, x:x+bw] = 0
        elif r < 0.75:
            arr[y:y+bh, x:x+bw] = np.random.randint(0, 256, (bh, bw, 3), dtype=np.int16)
        else:
            patch = arr[y:y+bh, x:x+bw].copy()
            arr[y:y+bh, x:x+bw] = np.roll(patch, random.randint(-bw // 2, bw // 2), axis=1)

    # 3) 水平长条位移
    for _ in range(int(4 + 6 * intensity)):
        sy = random.randint(0, h - 1); sh = random.randint(int(h * 0.01), int(h * 0.04))
        dx = random.randint(-int(w * 0.2), int(w * 0.2))
        arr[sy:sy+sh] = np.roll(arr[sy:sy+sh], dx, axis=1)

    out = np.clip(arr, 0, 255).astype(np.uint8)
    img = Image.fromarray(out)

    # 4) 降饱和 + 颗粒（更接近参考图的胶片感）
    img = ImageEnhance.Color(img).enhance(max(0.0, 1.0 - desat * intensity))
    if grain > 0:
        g = np.random.normal(0, 255 * grain * intensity, (h, w, 1)).astype(np.int16)
        a = np.array(img).astype(np.int16)
        a = np.clip(a + g, 0, 255).astype(np.uint8)
        img = Image.fromarray(a)
    img.save(dst, quality=95)
    return dst

if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    inten = float(sys.argv[3]) if len(sys.argv) > 3 else 0.8
    print(glitchify(src, dst, inten, seed=11))
