# -*- coding: utf-8 -*-
"""DA3 景深前景提层（分类 3）与脚底边缘纹理咬合（分类 2）。"""
import json
import os
import shutil
import time
import urllib.request
import numpy as np
from PIL import Image, ImageFilter

from comfy_paths import COMFY_IN as inp, COMFY_OUT as outd

COMFY = os.environ.get("STATION_COMFY", os.environ.get("COMFY_API", "http://127.0.0.1:8188"))


def _comfy(path, payload=None, timeout=120):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(COMFY + path, data=data, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def estimate_depth_and_sky(bg_path, steps_dir, model_name="depth_anything_3_mono_large.safetensors",
                           resolution=756, timeout=180):
    """调用 ComfyUI 原生 Depth Anything 3，返回 (depth_png_path, sky_mask_png_path)。"""
    try:
        import mem_plan
        mem_plan.schedule("birefnet", unet=model_name, reason="da3_depth_occlude", context="coop")
    except Exception:
        pass
    name = f"da3_{int(time.time() * 1000)}_{os.getpid()}.png"
    Image.open(bg_path).convert("RGB").save(os.path.join(inp, name))
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": name}},
        "2": {"class_type": "LoadDA3Model", "inputs": {"model_name": model_name, "weight_dtype": "default"}},
        "3": {"class_type": "DA3Inference", "inputs": {
            "da3_model": ["2", 0], "image": ["1", 0],
            "resolution": int(resolution), "resize_method": "upper_bound_resize", "mode": "mono",
        }},
        "4": {"class_type": "DA3Render", "inputs": {
            "da3_geometry": ["3", 0], "output": "depth",
            "output.normalization": "min_max", "output.apply_sky_clip": True,
        }},
        "5": {"class_type": "DA3Render", "inputs": {
            "da3_geometry": ["3", 0], "output": "sky_mask", "output.colored": False,
        }},
        "6": {"class_type": "SaveImage", "inputs": {"images": ["4", 0], "filename_prefix": "DA3_D"}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["5", 0], "filename_prefix": "DA3_S"}},
    }
    pid = _comfy("/prompt", {"prompt": graph, "client_id": "sunloom_da3"})["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = _comfy("/history/" + pid)
        if pid in h:
            entry = h[pid]
            if (entry.get("status") or {}).get("status_str") == "error":
                raise RuntimeError("DA3 ComfyUI error: %s" % str(entry.get("status"))[:200])
            depth_dst = os.path.join(steps_dir, "01d_da3_depth.png")
            sky_dst = os.path.join(steps_dir, "01d_da3_sky.png")
            for nid, node in (entry.get("outputs") or {}).items():
                for im in node.get("images") or []:
                    p = os.path.join(outd, im.get("subfolder", ""), im.get("filename", ""))
                    if os.path.isfile(p):
                        shutil.copy2(p, depth_dst if nid == "6" else sky_dst)
            if os.path.isfile(depth_dst) and os.path.isfile(sky_dst):
                return depth_dst, sky_dst
            raise RuntimeError("DA3 produced no images")
        time.sleep(0.8)
    raise TimeoutError("DA3 depth timeout")


def apply_depth_occlusion(bg_path, comp_img, box, ground_y, steps_dir):
    """按脚底平面深度锚点提取更近的非天空前景物体，直接从高清空景贴回人物前方。"""
    depth_p, sky_p = estimate_depth_and_sky(bg_path, steps_dir)
    bg = Image.open(bg_path).convert("RGB")
    W, H = bg.size
    d_arr = np.asarray(Image.open(depth_p).convert("L").resize((W, H), Image.BILINEAR), dtype=np.float32)
    s_arr = np.asarray(Image.open(sky_p).convert("L").resize((W, H), Image.BILINEAR), dtype=np.float32) / 255.0

    px, py, x1, y1 = [int(v) for v in box]
    px, py = max(0, px), max(0, py)
    x1, y1 = min(W, x1), min(H, y1)
    bw, bh = max(1, x1 - px), max(1, y1 - py)
    cx = (px + x1) // 2
    fy = min(H - 1, max(0, int(round(H * float(ground_y)))))

    # 取落脚点地面邻域非天空像素中位数作为人物所处平面的深度锚点（亮=近，暗=远）
    ay0, ay1 = max(0, fy - 14), min(H, fy + 18)
    ax0, ax1 = max(0, cx - int(bw * 0.45)), min(W, cx + int(bw * 0.45))
    anchor_d = d_arr[ay0:ay1, ax0:ax1]
    anchor_s = s_arr[ay0:ay1, ax0:ax1]
    valid = anchor_d[anchor_s < 0.35]
    d_ground = float(np.median(valid)) if valid.size else float(np.median(anchor_d))

    # 在人物框内找明显近于落脚平面且非天空的物体
    delta = max(14.0, 0.08 * 255.0)
    sub_d = d_arr[py:y1, px:x1]
    sub_s = s_arr[py:y1, px:x1]
    fg_sub = (sub_d > d_ground + delta) & (sub_s < 0.35)
    cov = float(fg_sub.mean()) if fg_sub.size else 0.0

    if cov < 0.02 or cov > 0.45:
        return comp_img, False, f"depth_cov_skip:{cov:.3f}"

    # 仅保留连通块 >= 人物框 0.4% 的实体前景块，过滤零星噪点
    try:
        import cv2
        num, labels, stats, _ = cv2.connectedComponentsWithStats(fg_sub.astype(np.uint8), 8)
        min_area = max(36, int(bw * bh * 0.004))
        keep = np.zeros_like(fg_sub, dtype=np.uint8)
        for idx in range(1, num):
            if stats[idx, cv2.CC_STAT_AREA] >= min_area:
                keep[labels == idx] = 255
    except Exception:
        keep = (fg_sub.astype(np.uint8) * 255)

    final_cov = float((keep > 0).mean())
    if final_cov < 0.02 or final_cov > 0.45:
        return comp_img, False, f"depth_clean_skip:{final_cov:.3f}"

    mask = Image.new("L", (W, H), 0)
    mask.paste(Image.fromarray(keep, "L"), (px, py))
    mask = mask.filter(ImageFilter.GaussianBlur(1.5))
    mask.save(os.path.join(steps_dir, "04_da3_fg_mask.png"))
    out = comp_img.convert("RGB").copy()
    out.paste(bg, (0, 0), mask)
    return out, True, f"depth_applied:{final_cov:.3f}(d_ground={d_ground:.1f})"


def apply_ground_bite(bg_path, comp_img, char_alpha_placed, box):
    """分类 2（轻微接地遮挡）：不重绘，用空景脚底高对比草尖/水波纹理咬合鞋尖最底 6%。"""
    bg = Image.open(bg_path).convert("RGB")
    W, H = bg.size
    px, py, x1, y1 = [max(0, int(v)) for v in box]
    x1, y1 = min(W, x1), min(H, y1)
    bh = max(1, y1 - py)
    band_h = max(8, int(round(bh * 0.065)))
    by0 = max(py, y1 - band_h)
    if by0 >= y1 or px >= x1:
        return comp_img, False

    bg_crop = np.asarray(bg.crop((px, by0, x1, y1)), dtype=np.float32)
    bg_blur = np.asarray(bg.crop((px, by0, x1, y1)).filter(ImageFilter.GaussianBlur(5)), dtype=np.float32)
    hf = np.abs(bg_crop - bg_blur).mean(axis=-1)
    thr = max(8.0, float(np.percentile(hf, 68)))
    raw_bite = np.clip((hf - thr * 0.65) / max(1.0, thr), 0.0, 1.0)

    # 越靠近鞋底最下缘咬合越强，上方渐变回 0；仅作用在人物非透明区
    vy = np.linspace(0.0, 1.0, y1 - by0, dtype=np.float32)[:, None] ** 1.3
    a_crop = np.asarray(char_alpha_placed.crop((px, by0, x1, y1)), dtype=np.float32) / 255.0
    bite = np.clip(raw_bite * vy * (a_crop > 0.20) * 0.85, 0.0, 0.85)

    mask = Image.new("L", (W, H), 0)
    mask.paste(Image.fromarray((bite * 255.0).astype(np.uint8), "L"), (px, by0))
    mask = mask.filter(ImageFilter.GaussianBlur(0.8))
    out = comp_img.convert("RGB").copy()
    out.paste(bg, (0, 0), mask)
    return out, True
