# -*- coding: utf-8 -*-
"""实验：BiRefNet trimap + pymatting KNN 软蒙版。

决策门未通过：发梢变软，但整体收缩/白边更明显，未接入 cutout。
保留供复现；生产仍走 cutout.defringe。
"""
import time

import numpy as np
from PIL import Image


def _cv():
    import cv2
    return cv2


def trimap(alpha, fg=0.97, bg=0.03, erode=3, dilate=5):
    """0=确定背景，1=确定前景，0.5=未知。alpha 为 0..1 float。"""
    cv2 = _cv()
    fgm = (alpha >= fg).astype(np.uint8)
    bgm = (alpha <= bg).astype(np.uint8)
    if fgm.sum() == 0:
        fgm = (alpha >= max(0.5, float(np.percentile(alpha, 90)))).astype(np.uint8)
    if bgm.sum() == 0:
        bgm = (alpha <= max(0.01, float(np.percentile(alpha, 5)))).astype(np.uint8)
    k = np.ones((2 * erode + 1, 2 * erode + 1), np.uint8)
    fgm = cv2.erode(fgm, k) if erode else fgm
    k2 = np.ones((2 * dilate + 1, 2 * dilate + 1), np.uint8)
    bgm = cv2.erode(bgm, k2) if dilate else bgm
    tri = np.full(alpha.shape, 0.5, np.float32)
    tri[bgm > 0] = 0.0
    tri[fgm > 0] = 1.0
    return tri


def _bbox(alpha, pad=0.08):
    ys, xs = np.where(alpha > 0.02)
    if len(xs) == 0:
        return None
    h, w = alpha.shape
    x0, x1 = xs.min(), xs.max() + 1
    y0, y1 = ys.min(), ys.max() + 1
    px, py = int((x1 - x0) * pad), int((y1 - y0) * pad)
    return max(0, x0 - px), max(0, y0 - py), min(w, x1 + px), min(h, y1 + py)


def refine(im, max_seconds=8.0, bg_color=None, decontaminate=True):
    """返回 RGBA。失败时抛异常，由调用方回退 defringe。"""
    t0 = time.time()
    im = im.convert("RGBA")
    rgb = np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0
    a0 = np.asarray(im.split()[3], dtype=np.float32) / 255.0
    box = _bbox(a0)
    if box is None:
        raise ValueError("empty alpha")
    x0, y0, x1, y1 = box
    crop_a = a0[y0:y1, x0:x1]
    crop_rgb = rgb[y0:y1, x0:x1]

    if bg_color is None:
        bgm = crop_a <= 0.03
        if bgm.sum() >= 256:
            bgpix = crop_rgb[bgm]
        else:
            bgpix = np.concatenate([rgb[:8].reshape(-1, 3), rgb[-8:].reshape(-1, 3),
                                    rgb[:, :8].reshape(-1, 3), rgb[:, -8:].reshape(-1, 3)])
        bg_color = np.median(bgpix, axis=0)
        bg_std = float(np.mean(np.std(bgpix, axis=0)))
        if bg_std > 0.30:
            raise ValueError("background not uniform (%.2f)" % bg_std)

    tri = trimap(crop_a)
    unknown = float((tri == 0.5).mean())
    if unknown < 0.005 or unknown > 0.85:
        raise ValueError("bad trimap %.3f" % unknown)

    from pymatting import estimate_alpha_knn
    h, w = tri.shape
    scale = min(1.0, 640.0 / max(h, w))
    if scale < 0.999:
        import cv2 as _cv2
        sw, sh = max(8, int(round(w * scale))), max(8, int(round(h * scale)))
        small_rgb = _cv2.resize(crop_rgb, (sw, sh), interpolation=_cv2.INTER_AREA)
        small_tri = _cv2.resize(tri, (sw, sh), interpolation=_cv2.INTER_NEAREST)
        small = estimate_alpha_knn(small_rgb.astype(np.float64), small_tri.astype(np.float64))
        alpha = _cv2.resize(np.clip(small.astype(np.float32), 0, 1), (w, h), interpolation=_cv2.INTER_LINEAR)
    else:
        alpha = estimate_alpha_knn(crop_rgb.astype(np.float64), tri.astype(np.float64))
        alpha = np.clip(alpha.astype(np.float32), 0.0, 1.0)
    out_a = crop_a.copy()
    band = tri == 0.5
    out_a[band] = np.maximum(alpha[band], crop_a[band])
    out_a[tri == 1.0] = np.maximum(crop_a[tri == 1.0], alpha[tri == 1.0])
    out_a[tri == 0.0] = 0.0

    # 前景去污：I = aF + (1-a)B => F = (I-(1-a)B)/a
    aa = np.clip(out_a, 0.0, 1.0)[..., None]
    bg = bg_color.reshape(1, 1, 3).astype(np.float32)
    fg = np.where(aa > 0.04, (crop_rgb - (1 - aa) * bg) / np.maximum(aa, 0.04), crop_rgb)
    fg = np.clip(fg, 0.0, 1.0)
    if not decontaminate:
        fg = crop_rgb.copy()
    # 只改边缘带，实心区保持原色
    edge = (out_a > 0.02) & (out_a < 0.98)
    fg[~edge] = crop_rgb[~edge]
    if time.time() - t0 > max_seconds:
        raise TimeoutError("matte too slow")

    full_a = a0.copy()
    full_a[y0:y1, x0:x1] = out_a
    full_rgb = rgb.copy()
    full_rgb[y0:y1, x0:x1] = fg

    # 去掉远处的小碎块，但保留贴底的脚/裙摆
    cv2 = _cv()
    hard = (full_a > 0.2).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(hard, 8)
    if n > 2:
        h = hard.shape[0]
        bottoms = stats[1:, 1] + stats[1:, 3]
        keep = [i + 1 for i, b in enumerate(bottoms) if b > bottoms.max() - 0.2 * h]
        full_a = np.where(np.isin(labels, keep), full_a, 0.0)
    out = Image.fromarray(np.dstack([(full_rgb * 255).astype(np.uint8),
                                     (np.clip(full_a, 0, 1) * 255).astype(np.uint8)]), "RGBA")
    return out
