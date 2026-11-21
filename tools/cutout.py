# -*- coding: utf-8 -*-
"""抠图：BiRefNet（ComfyUI 原生）/ rembg 多后端 + 边缘去污。

2026-11-13 重写：旧版 defringe 会把 BiRefNet 的软 alpha 二值化（np.where(a>128,255,0)），
发丝全丢。现在默认 mode="soft" 保留连续 alpha；mode="hard" 保留旧行为便于回滚/对比。
"""
import json
import os
import time
import urllib.request

import numpy as np
from PIL import Image

ROOT = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMFY = os.environ.get("STATION_COMFY", os.environ.get("COMFY_API", "http://127.0.0.1:8188")).rstrip("/")


class CutoutError(RuntimeError):
    pass


def _cv():
    import cv2
    return cv2


def _border_bg(rgb, a, border=8):
    """背景色：优先取完全透明的像素，不够再取四边 border 宽的中位数。"""
    h, w = a.shape
    mask = a < 8
    if mask.sum() >= 256:
        px = rgb[mask]
    else:
        edge = np.zeros((h, w), bool)
        edge[:border] = edge[-border:] = True
        edge[:, :border] = edge[:, -border:] = True
        px = rgb[edge]
    return np.median(px.reshape(-1, 3), axis=0)


def _nearest_fg(rgb, a):
    """每个像素"本该是什么颜色" = 最近的实心像素颜色。

    不能用 cv2.dilate 迭代扩散：dilate 取邻域最大值，白底会把背景白当成前景，
    边缘反而被涂白（2026-11-13 实测）。用距离变换找真正的最近邻。
    """
    from scipy import ndimage
    known = a > 0.97
    if not known.any():
        return rgb.astype(np.float32).copy()
    idx = ndimage.distance_transform_edt(~known, return_distances=False, return_indices=True)
    return rgb.astype(np.float32)[tuple(idx)]


def defringe(im, shrink=1, soft=False, mode="clean", gamma=1.2, min_alpha=0.02, bg_color=None,
             edge_lo=0.02, edge_hi=5):
    """去边缘背景色晕。

    mode="clean"（默认，=hydrate）：先腐蚀掉被背景污染的一圈，用距离变换生成 1px 平滑过渡，
        颜色从内部扩散并模糊（直接取最近实心色会在描边/亮发间跳，产生颗粒）；
    mode="soft"：只做 alpha 加权去污（保留原色，发丝最自然，但白底图上会残留白边）；
    mode="hard"：旧行为（alpha 二值化 + 腐蚀），保留用于回滚与 A/B。
    """
    cv2 = _cv()
    a8 = np.asarray(im.split()[-1])
    rgb = np.asarray(im.convert("RGB")).astype(np.float32)
    a = np.clip(a8.astype(np.float32) / 255.0, 0.0, 1.0)
    bg = _border_bg(rgb, a8) if bg_color is None else np.asarray(bg_color, np.float32)

    if mode == "hard":
        out = rgb.copy()
        band = (a8 > 10) & (a8 <= 240)
        al = np.clip(a8.astype(np.float32) / 255.0, 0.15, 1.0)[..., None]
        unmix = (rgb - (1 - al) * bg) / al
        out[band] = np.clip(unmix[band], 0, 255)
        for _ in range(2):
            blur = cv2.blur(out, (3, 3))
            out[band] = 0.5 * out[band] + 0.5 * blur[band]
        if shrink:
            a8 = cv2.erode(a8, np.ones((2 * shrink + 1, 2 * shrink + 1), np.uint8))
        if soft:
            a8 = (np.clip((a8.astype(np.float32) - 6) / 210.0, 0, 1) ** 0.9 * 255).astype(np.uint8)
        else:
            a8 = np.where(a8 > 128, 255, 0).astype(np.uint8)
        a8 = _drop_specks(a8)
        a8 = cv2.GaussianBlur(a8, (3, 3), 0.6)
        return Image.fromarray(np.dstack([np.clip(out, 0, 255), a8]).astype(np.uint8), "RGBA")

    if mode in ("clean", "hydrate"):
        # 白底渲染的边缘里有 1~2px 是被背景白污染的，先把它腐蚀掉，再重建平滑过渡。
        cv2 = _cv()
        core = (a > 0.5).astype(np.uint8)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        for _ in range(max(1, int(round(shrink)))):
            core = cv2.erode(core, k)
        dist = cv2.distanceTransform(core, cv2.DIST_L2, 5)
        aa = np.clip(dist / max(0.8, float(gamma)), 0.0, 1.0)
        aa = aa * aa * (3.0 - 2.0 * aa)          # smoothstep：1px 干净过渡，不是锯齿
        # 颜色只取内部，扩散后模糊——直接取"最近实心色"会在描边/亮发之间跳，形成颗粒
        inner = rgb.copy()
        inner[core == 0] = 0.0
        cblur = int(edge_hi) if edge_hi >= 3 else 5
        fg = cv2.blur(inner, (cblur, cblur))
        wsum = cv2.blur(core.astype(np.float32), (cblur, cblur))
        fg = np.where(wsum[..., None] > 1e-3, fg / np.maximum(wsum[..., None], 1e-3), rgb)
        out = rgb.copy()
        band = aa < 0.995
        out[band] = np.clip(fg[band], 0, 255)
        a8 = _drop_specks((aa * 255.0).astype(np.uint8), thr=12)
        return Image.fromarray(np.dstack([np.clip(out, 0, 255), a8]).astype(np.uint8), "RGBA")

    # ---- soft ----
    a = np.where(a < min_alpha, 0.0, a)
    band = (a > 0.02) & (a < 0.98)
    al = np.clip(a, 0.05, 1.0)[..., None]
    unmix = (rgb - (1 - al) * bg) / al
    out = rgb.copy()
    out[band] = np.clip(unmix[band], 0, 255)
    # 只对边缘带的颜色做一次轻平滑，压掉去污噪声；实心区保持原样（不发糊）
    blur = cv2.blur(out, (3, 3))
    out[band] = 0.65 * out[band] + 0.35 * blur[band]
    if shrink:
        # 软模式下不整体腐蚀，只在最外侧极低 alpha 处收一点点，去掉贴边白氛
        weak = a < 0.12
        a = np.where(weak, a * 0.5, a)
    a = np.clip(a ** float(gamma), 0.0, 1.0)
    a8 = _drop_specks((a * 255).astype(np.uint8), thr=12)
    return Image.fromarray(np.dstack([np.clip(out, 0, 255), a8]).astype(np.uint8), "RGBA")


def _drop_specks(a8, thr=24):
    """删掉远离主体的碎块；贴着最低点的那几条=脚/裙摆，保留。"""
    cv2 = _cv()
    n, labels, stats, _ = cv2.connectedComponentsWithStats((a8 > thr).astype(np.uint8), 8)
    if n <= 2:
        return a8
    h = a8.shape[0]
    bottoms = stats[1:, 1] + stats[1:, 3]
    keep = [i + 1 for i, b in enumerate(bottoms) if b > bottoms.max() - 0.18 * h]
    return np.where(np.isin(labels, keep), a8, 0).astype(np.uint8)


def _comfy(path, payload=None, timeout=120):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(COMFY + path, data=data, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _birefnet_raw(src, model="birefnet.safetensors", timeout=180):
    """ComfyUI 原生 BiRefNet，返回未裁切、未去污的 RGBA。"""
    from comfy_paths import COMFY_IN as inp, COMFY_OUT as outd
    try:
        import mem_plan
        mem_plan.schedule("birefnet", unet=model, reason="birefnet_cutout", context="coop")
    except Exception:
        pass
    name = "cutout_%d_%d.png" % (int(time.time() * 1000), os.getpid())
    Image.open(src).convert("RGB").save(os.path.join(inp, name))
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": name}},
        "2": {"class_type": "LoadBackgroundRemovalModel", "inputs": {"bg_removal_name": model}},
        "3": {"class_type": "RemoveBackground", "inputs": {"bg_removal_model": ["2", 0], "image": ["1", 0]}},
        "4": {"class_type": "InvertMask", "inputs": {"mask": ["3", 0]}},
        "5": {"class_type": "JoinImageWithAlpha", "inputs": {"image": ["1", 0], "alpha": ["4", 0]}},
        "6": {"class_type": "SaveImage", "inputs": {"images": ["5", 0], "filename_prefix": "CUTOUT"}},
    }
    try:
        pid = _comfy("/prompt", {"prompt": graph, "client_id": "sunloom_cutout"})["prompt_id"]
    except Exception as e:  # noqa: BLE001
        raise CutoutError("queue: %s" % str(e)[:200])
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = _comfy("/history/" + pid)
        if pid in h:
            entry = h[pid]
            if (entry.get("status") or {}).get("status_str") == "error":
                raise CutoutError("comfy error")
            for node in (entry.get("outputs") or {}).values():
                for img in node.get("images") or []:
                    path = os.path.join(outd, img.get("subfolder", ""), img.get("filename", ""))
                    if os.path.isfile(path):
                        return Image.open(path).convert("RGBA")
            raise CutoutError("no image")
        time.sleep(1)
    raise CutoutError("timeout")


# 抗锯齿档位：**收边与 alpha 锐化各砍一半过渡宽度**，所以要一起调。
# 实测（standee_v4）过渡宽度：都不开 0.90px → 只收边 0.68 → 只锐化 0.40 → 都开 0.15。
AA_PRESETS = {
    "soft":   {"choke": 0.00, "sharpen_alpha": 0.0},   # 最柔：0.90px 过渡，飞边最多
    "normal": {"choke": 0.10, "sharpen_alpha": 0.4},   # 折中
    "crisp":  {"choke": 0.25, "sharpen_alpha": 0.9},   # 最硬：飞边最少（旧默认）
}


def aa_to_kwargs(aa):
    """档位名或数值 → 色键参数。数值只改 choke（兼容旧调用）。"""
    if aa is None:
        aa = "crisp"      # 默认保持旧行为，档位需显式指定
    if isinstance(aa, str):
        if aa not in AA_PRESETS:
            raise CutoutError("未知抗锯齿档位: %s（可选 %s）" % (aa, list(AA_PRESETS)))
        return dict(AA_PRESETS[aa])
    return {"choke": float(aa)}


def _key_hue(rgb_key):
    cv2 = _cv()
    px = np.clip(np.asarray(rgb_key, np.float32).reshape(1, 1, 3), 0, 255).astype(np.uint8)
    return float(cv2.cvtColor(px, cv2.COLOR_RGB2HSV)[0, 0, 0]) * 2.0


def _chroma_raw(src, key=None, lo=0.10, shrink=0, ramp=0.0, dark=60, despill=True, sharpen=True,
                choke=0.25, decontaminate=True, rim_green=15, rim_dist=3.0, rim_alpha=0.7,
                rim_dark=150, despill_all=2.0,
                sharpen_alpha=0.9):
    """绿幕色键 v2：按绿色占比出 alpha，**不做几何腐蚀**。

    旧版用 erode 1px + 距离变换：轮廓每边缩 1px，而线稿正好长在最外 1~2px，
    于是"发丝被裁、描线消失"（2026-11-13 用户指出）。现在轮廓完全由颜色决定：

        E = G - max(R,B)                绿色优势
        e = E / max(G,1)                按亮度归一 → 阴影绿同样成立
        a = 1 - clip(e / e_bg)          50% 混合得到 0.5（真实覆盖率）
        深色像素（max < dark）一律 a=1    线稿必须保留
    """
    cv2 = _cv()
    im = Image.open(src).convert("RGB")
    rgb = np.asarray(im).astype(np.float32)
    h, w = rgb.shape[:2]
    b = 20
    ring = np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3),
                           rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])
    if key is None:
        key = np.median(ring, axis=0)
        std = float(np.mean(np.std(ring, axis=0)))
        if std > 12.0:
            raise CutoutError("背景不纯（边框 std %.1f），不是绿幕" % std)
        # 绿幕的判据是"绿通道明显占优"，不是固定色相区间：
        # 实测模型给的是 (0,102,71)，色相 162°，落在常见绿色区间之外但确实是绿幕
        if not (key[1] > key[0] + 20 and key[1] > key[2] + 8):
            raise CutoutError("背景不是绿幕（RGB %s）" % np.round(key).astype(int).tolist())
    key = np.asarray(key, np.float32)

    def _excess(arr):
        return arr[..., 1] - np.maximum(arr[..., 0], arr[..., 2])

    e_bg = float(_excess(key)) / max(1.0, float(key[1]))
    if e_bg <= 0.02:
        raise CutoutError("背景绿色优势太弱（e_bg %.3f），不是绿幕" % e_bg)
    e = _excess(rgb) / np.maximum(rgb[..., 1], 1.0)
    a = 1.0 - np.clip(e / e_bg, 0.0, 1.0)

    # 模型会把背景绿当环境光画进轮廓最外 1~2px（实拍 1614 个**不透明暗橄榄绿**像素，
    # 96% 距透明区 ≤1px）。色键抠不掉（它不是背景色）、去污染又会被染成人物色，只能按位置删。
    # 判据必须是「贴边 + 足够不透明 + 暗色」：合法抗锯齿是"白+绿"的亮混合，不能被误删。
    if rim_green > 0:
        # 判据：**不透明**（a>rim_alpha）+ 绿占优 + 贴边。
        # 合法抗锯齿的 alpha 是渐变的（多在 0.2~0.6），不会被这条命中；
        # 而模型画进轮廓的溢色是实心不透明的（实测 1541 个绿像素 alpha 中位 1.0），
        # 之前用"必须够暗"做门槛把一半漏了（黑底上一串绿点，2026-11-13 实测）。
        gex0 = rgb[..., 1] - np.maximum(rgb[..., 0], rgb[..., 2])
        cand = (a > float(rim_alpha)) & (gex0 > float(rim_green))
        if cand.any():
            transp = (a < 0.02).astype(np.uint8)
            dist = cv2.distanceTransform(1 - transp, cv2.DIST_L2, 5)
            a = np.where(cand & (dist <= float(rim_dist)), 0.0, a)

    # 线稿保护：暗像素一律不透明。**但必须排除"暗绿"**——背景是纯绿时，
    # 轮廓上的抗锯齿/阴影绿是暗的（实测 (13,45,12)），不能被当成线稿，
    # 否则它们会以 alpha=1 留在轮廓外，变成一串不透明绿点（2026-11-13 实测 479 个）。
    dark_px = rgb.max(axis=2) < float(dark)
    gex_now = rgb[..., 1] - np.maximum(rgb[..., 0], rgb[..., 2])
    a = np.where(dark_px & (gex_now <= 15), 1.0, a)
    if shrink:
        # 兼容旧参数：极轻微收边（默认 0，不做几何腐蚀）
        a = np.where(a < 0.5, a * 0.5, a)
    a = np.where(a < float(lo), 0.0, a)                   # 噪声地板
    if choke > 0:
        # 收边：把淡影尾巴砍掉，只保留 1px 抗锯齿。
        # 实测：不收边时轮廓外 2px 环里 62% 的像素是半透明（飞边来源）
        a = np.clip((a - float(choke)) / max(1e-3, 0.85 - float(choke)), 0.0, 1.0)


    al = np.clip(a, 0.05, 1.0)[..., None]
    fg = np.clip((rgb - (1.0 - al) * key) / al, 0, 255)
    if decontaminate:
        # 半透明像素的颜色改成最近的实心色：否则它们带的是「人物+绿」的混合色，
        # 换到白底就是一圈灰白飞边（实测灰边强度 58.8）
        part = (a > 0.02) & (a < 0.75)
        if part.any():
            fg = np.where(part[..., None], _nearest_fg(fg, a), fg)
            # 「最近实心色」常常就是 1~2px 宽的深色描边，直接用它会在边缘留一圈暗色。
            # 再过一次 5×5 中值：细描边被滤掉，留下主体的大面积色（2026-11-13 实测偏暗占比 16%）。
            med = cv2.medianBlur(np.clip(fg, 0, 255).astype(np.uint8), 5).astype(np.float32)
            fg = np.where(part[..., None], med, fg)
    if despill:
        lim = np.maximum(fg[..., 0], fg[..., 2]) + 6.0
        edge = (a > 0.02) & (a < 0.995)
        fg[..., 1] = np.where(edge, np.minimum(fg[..., 1], lim), fg[..., 1])
    if despill_all > 0:
        # 全局去绿：模型会把绿幕的溢色直接画进画面（深橄榄绿，alpha 还是 1），
        # 局部规则怎么调都会漏。这里对所有像素把 G 压到 max(R,B)+阈值——
        # 画面上不存在绿，就不可能有绿点/绿边（2026-11-13 黑底实测一串绿点）。
        lim_all = np.maximum(fg[..., 0], fg[..., 2]) + float(despill_all)
        fg[..., 1] = np.minimum(fg[..., 1], lim_all)
    a8 = _drop_specks((a * 255.0).astype(np.uint8), thr=12)   # 轮廓外孤立碎点
    out = Image.fromarray(np.dstack([np.clip(fg, 0, 255), a8]).astype(np.uint8), "RGBA")
    if sharpen and sharpen_alpha > 0:
        out = sharpen_edge(out, alpha_amount=float(sharpen_alpha), max_delta=40)  # 限幅防振铃
    return out, key


# 图像处理辅助搬去 imgedge.py（cutout.py 超 20KB 红线），这里重新导出保持调用方不变
from imgedge import (  # noqa: F401
    unsharp_rgb, resize_rgba, flatten_rim_color, rechoke, sharpen_edge, refine_edge,
    deveil_alpha, ink_outline,
)

def _rembg_raw(src, model="u2net"):
    from rembg import new_session, remove
    im = Image.open(src).convert("RGB")
    return remove(im, session=new_session(model)).convert("RGBA")


BACKENDS = ("birefnet", "u2net", "isnet_anime", "color", "chroma")


def raw_matte(src, backend="birefnet", **kw):
    """不裁切、不去污的原始 RGBA；颜色差抠图保留给无 ComfyUI 的环境。"""
    if backend == "birefnet":
        return _birefnet_raw(src, **kw)
    if backend in ("u2net", "isnet_anime"):
        return _rembg_raw(src, "isnet-anime" if backend == "isnet_anime" else "u2net")
    if backend == "color":
        return _color_raw(src)
    if backend == "chroma":
        rgba, _key = _chroma_raw(src, **kw)
        return rgba
    raise CutoutError("unknown backend: %s" % backend)


def _color_raw(src, tol=36, soft=32, min_alpha=0.18):
    """与四边中位色作差（白底角色可用，彩色/复杂背景会崩）。"""
    im = Image.open(src)
    rgb = np.asarray(im.convert("RGB")).astype(np.float32)
    h, w = rgb.shape[:2]
    edge = np.stack([rgb[0, 0], rgb[0, w - 1], rgb[h - 1, 0], rgb[h - 1, w - 1]])
    bg = np.median(edge, axis=0)
    diff = np.abs(rgb - bg).sum(axis=2)
    a = np.clip((diff - tol) / max(1.0, soft), 0.0, 1.0)
    a = np.where(a < min_alpha, 0.0, a) ** 1.5
    aa = np.maximum(a, 1e-3)[..., None]
    fg = np.clip((rgb - (1.0 - a[..., None]) * bg) / aa, 0, 255)
    return Image.fromarray(np.dstack([fg, a * 255.0]).astype(np.uint8), "RGBA")


def make_matte(src, backend="birefnet", mode="clean", soft=False, crop=True, aa=None,
               rim_flatten=1, **kw):
    """抠图 + 去污 + 裁包围盒。调用方拿到的就是可直接合成的 RGBA。

    aa: 抗锯齿档位 soft / normal / crisp（或直接给 choke 数值）。
        色键走这条；birefnet 等其它后端忽略。
    """
    if backend == "chroma":
        preset = aa_to_kwargs(aa)
        for k, v in preset.items():
            kw.setdefault(k, v)
    im = raw_matte(src, backend=backend, **kw)
    if crop:
        bb = im.getbbox()
        if bb:
            im = im.crop(bb)
    if backend == "chroma":
        if rim_flatten > 0:
            im = flatten_rim_color(im)   # 最外一圈换成内部色，去掉模型画的深色描边
        return im    # 色键的 alpha 已经是最终值，再套 hydrate 会二次收缩（轮廓被裁）
    return defringe(im, soft=soft, mode=mode)


def hybrid_matte(src, aa="crisp", lo=0.35, hi=0.8, despill_all=2.0):
    """轮廓用 BiRefNet（平滑连续），颜色用色键（已去绿、去污染）。

    纯色键的轮廓受画面内容影响（断续描边、绿点）；模型蒙版的轮廓不受这些影响，
    但它的颜色是原图颜色（带绿色污染）。两者合起来：模型的形 + 色键的色。
    """
    chroma = raw_matte(src, backend="chroma", **aa_to_kwargs(aa))
    model = raw_matte(src, backend="birefnet")
    if model.size != chroma.size:
        model = model.resize(chroma.size, Image.LANCZOS)
    ca = np.asarray(chroma).astype(np.float32)
    ma = np.asarray(model.split()[-1]).astype(np.float32) / 255.0
    ma = np.clip((ma - float(lo)) / max(1e-3, float(hi) - float(lo)), 0.0, 1.0)
    rgb = ca[..., :3].copy()
    if despill_all > 0:
        lim = np.maximum(rgb[..., 0], rgb[..., 2]) + float(despill_all)
        rgb[..., 1] = np.minimum(rgb[..., 1], lim)
    out = Image.fromarray(np.dstack([np.clip(rgb, 0, 255), ma * 255.0]).astype(np.uint8), "RGBA")
    return flatten_rim_color(out)


def comfy_cutout(src, dst, model="birefnet.safetensors", timeout=180, soft=False,
                 backend="birefnet", mode="clean"):
    """兼容旧签名：BiRefNet → 裁包围盒 → 去污 → 存盘。"""
    kw = {}
    if backend == "birefnet":
        kw = {"model": model, "timeout": timeout}
    im = make_matte(src, backend=backend, mode=mode, soft=soft, crop=True, **kw)
    im.save(dst)
    return dst
