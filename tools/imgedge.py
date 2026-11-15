"""边缘与图像处理：缩放、锐化、收边、轮廓配色（从 cutout.py 拆出，避免超 20KB）。"""
import numpy as np
from PIL import Image


def _cv():
    import cv2
    return cv2

def unsharp_rgb(im, amount=0.5, radius=1.0, threshold=0):
    """整图 unsharp mask：给边缘一个整体锐度，和只作用在 alpha 带的 sharpen_edge 互补。

    RGBA 输入会保留 alpha（只锐化 RGB）——否则透明输出会被压成 RGB。
    """
    cv2 = _cv()
    alpha = im.split()[-1] if im.mode == "RGBA" else None
    rgb = np.asarray(im.convert("RGB")).astype(np.float32)
    blur = cv2.GaussianBlur(rgb, (0, 0), float(radius))
    sharp = np.clip(rgb + float(amount) * (rgb - blur), 0, 255)
    if threshold > 0:
        mask = (np.abs(sharp - rgb).max(axis=2) >= float(threshold))[..., None]
        sharp = np.where(mask, sharp, rgb)
    out = Image.fromarray(sharp.astype(np.uint8), "RGB")
    if alpha is not None:
        out = out.convert("RGBA")
        out.putalpha(alpha)
    return out


def resize_rgba(im, size, resample=Image.LANCZOS):
    """RGBA 缩放必须走预乘，否则透明像素的 RGB 会混进边缘（发灰/发闷/黑边）。

    做法：拆通道 → 每通道按 float 预乘 → 分别 resize → 反预乘 → 合回。
    用 F 模式缩放而不是 uint8，避免低 alpha 处的量化损失。
    """
    im = im.convert("RGBA")
    if tuple(im.size) == tuple(size):
        return im
    r, g, b, a = im.split()
    af = a.convert("F")
    scale = Image.new("F", im.size, 1.0 / 255.0)
    # 预乘：通道 * (alpha/255)
    pm = [Image.fromarray(np.asarray(c.convert("F")) * np.asarray(af) * (1.0 / 255.0)) for c in (r, g, b)]
    a_s = Image.fromarray(np.asarray(af))
    chans = [c.resize(size, resample) for c in pm] + [a_s.resize(size, resample)]
    A = np.asarray(chans[3]).astype(np.float32) / 255.0
    out = []
    for c in chans[:3]:
        arr = np.asarray(c).astype(np.float32)
        out.append(np.where(A > 1e-4, arr / np.maximum(A, 1e-4), 0.0))
    res = np.dstack([np.clip(o, 0, 255) for o in out] + [np.clip(A * 255.0, 0, 255)])
    return Image.fromarray(np.round(res).astype(np.uint8), "RGBA")


def flatten_rim_color(im, band=1.6, inner=2.6, lo=0.25):
    """把轮廓最外一圈的颜色换成「往内 inner px 处」的颜色。

    模型会把绿幕的环境光画成一条深色描边（alpha 仍是 1），色键去绿之后它变成暗灰点，
    白底上就是一圈毛边。形状别动，只把最外 band px 的**颜色**换成内部色。
    """
    from scipy import ndimage
    arr = np.asarray(im).astype(np.float32)
    rgb, a = arr[..., :3].copy(), arr[..., 3] / 255.0
    transp = (a < 0.02).astype(np.uint8)
    dist = ndimage.distance_transform_edt(1 - transp)
    ring = (a > float(lo)) & (dist <= float(band))
    if not ring.any():
        return im
    # 内部参考：距透明区 >= inner 且不透明的像素
    known = (dist >= float(inner)) & (a > 0.9)
    if not known.any():
        return im
    idx = ndimage.distance_transform_edt(~known, return_distances=False, return_indices=True)
    idx = tuple(np.asarray(i).astype(np.intp) for i in idx)
    out = rgb.copy()
    out[ring] = rgb[idx][ring]
    res = np.dstack([np.clip(out, 0, 255), (a * 255.0)]).astype(np.uint8)
    return Image.fromarray(res, "RGBA")


def deveil_alpha(im, floor=8):
    """去掉 Qwen-Image 2.1 原生 RGBA 的淡蒙层。

    实测：约 40% 的像素 alpha 落在 1~7，是 VAE 解码的浮底，肉眼看不见但会在
    深色背景上晕成一层灰。低于 floor 归零，其余线性拉回 0~255。
    """
    import numpy as np
    a = np.asarray(im)
    if a.ndim != 3 or a.shape[-1] != 4:
        return im
    out = a.astype(np.float32).copy()
    out[..., 3] = np.clip((out[..., 3] - float(floor)) / max(1.0, 255.0 - float(floor)), 0, 1) * 255.0
    from PIL import Image
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def ink_outline(im, width=1.6, strength=0.72, soft=0.8):
    """沿着 alpha 轮廓画一道内描边（勾边）。

    为什么不用模型：实测让 Qwen-Image 2.1「加线」会重构图（角色缩 30%、透明底丢失）。
    alpha 是精确的，直接由它生成轮廓，位置一定对得上。

    width    : 描边宽度（px）
    strength : 压暗强度 0~1
    """
    import numpy as np
    import cv2
    from PIL import Image
    if im.mode != "RGBA":
        return im
    a = np.asarray(im).astype(np.float32)
    alpha = a[..., 3] / 255.0
    core = (alpha > 0.5).astype(np.uint8)
    k = max(1, int(round(width)))
    inner = cv2.erode(core, np.ones((2 * k + 1, 2 * k + 1), np.uint8))
    ring = (core == 1) & (inner == 0)
    m = ring.astype(np.float32)
    m = cv2.GaussianBlur(m, (3, 3), soft) if soft > 0 else m
    rgb = a[..., :3] * (1.0 - (m * float(strength))[..., None])
    out = np.dstack([np.clip(rgb, 0, 255), a[..., 3]])
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def rechoke(im, lo=0.2, hi=0.8):
    """把 alpha 重新映射回 1px 过渡。

    放大层（2.4×）会把 1px 的半透明带放大成 2~3px，肉眼就是毛边；
    在放大之后再收一次，软带回到 1px。只改 alpha，不动颜色。
    """
    a = np.asarray(im.split()[-1]).astype(np.float32) / 255.0
    a = np.clip((a - float(lo)) / max(1e-3, float(hi) - float(lo)), 0.0, 1.0)
    out = im.copy()
    out.putalpha(Image.fromarray((a * 255.0).astype(np.uint8)))
    return out


def sharpen_edge(im, alpha_amount=0.9, color_amount=0.45, radius=0.8, band=(0.05, 0.95),
                 max_delta=0):
    """边缘锐化：alpha 做 unsharp（过渡更紧），颜色只在过渡带轻度锐化（不提亮背景）。"""
    cv2 = _cv()
    a = np.asarray(im.split()[-1]).astype(np.float32)
    rgb = np.asarray(im.convert("RGB")).astype(np.float32)
    m = (a > band[0] * 255) & (a < band[1] * 255)
    if not m.any():
        return im
    blur_a = cv2.GaussianBlur(a, (0, 0), float(radius))
    delta = a - blur_a
    if max_delta and max_delta > 0:
        delta = np.clip(delta, -float(max_delta), float(max_delta))
    sharp_a = np.clip(a + float(alpha_amount) * delta, 0, 255)
    # 只在过渡带替换，实心区和全透明区保持原样（否则会出锯齿/振铃）
    a2 = np.where(m, sharp_a, a)
    blur_c = cv2.GaussianBlur(rgb, (0, 0), float(radius))
    sharp_c = np.clip(rgb + float(color_amount) * (rgb - blur_c), 0, 255)
    c2 = np.where(m[..., None], sharp_c, rgb)
    out = Image.fromarray(np.dstack([c2, a2]).astype(np.uint8), "RGBA")
    return out


def refine_edge(im, lo=0.05, hi=0.95, k=3):
    """边缘细化：只在过渡带做中值，压掉颗粒，不改轮廓位置。"""
    cv2 = _cv()
    a = np.asarray(im.split()[-1])
    band = (a > lo * 255) & (a < hi * 255)
    if not band.any():
        return im
    med = cv2.medianBlur(a, int(k))
    im.putalpha(Image.fromarray(np.where(band, med, a).astype(np.uint8)))
    return im
