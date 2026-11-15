# -*- coding: utf-8 -*-
"""paper 模式的抠图调度：使用 BiRefNet，失败时回退 u2net。

拆出来是为了 coop_paper.py 不超过 20KB 上限，同时让抠图后端只有一处开关。
"""

CUTOUT_MODE = "biref"   # biref (ComfyUI BiRefNet，失败回退 u2net)
MEM = None              # 保留兼容参数（已退役 Qwen-2.1 显存切换）


def _u2net(src, dst):
    from rembg import remove, new_session
    from PIL import Image
    im = Image.open(src).convert("RGB")
    cut = remove(im, session=new_session("u2net"), alpha_matting=True,
                 alpha_matting_foreground_threshold=240,
                 alpha_matting_background_threshold=10,
                 alpha_matting_erode_size=6)
    bb = cut.getbbox()
    if bb:
        cut = cut.crop(bb)
    cut.save(dst)
    return dst


def cut(src, dst, tag="", backend=None, resolution=1024):
    """把 src 抠成透明 PNG 存到 dst，返回 dst。"""
    from cutout import comfy_cutout, CutoutError
    try:
        return comfy_cutout(src, dst)
    except CutoutError as e:
        print("[cutout] %s 回退 u2net: %s" % (tag, str(e)[:120]), flush=True)
        return _u2net(src, dst)
