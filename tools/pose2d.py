# -*- coding: utf-8 -*-
"""2D OpenPose/DWPose 平面骨架库、参考图扒骨与 LLLite 引导（配合 anima-lllite-pose-1）。"""
import copy
import json
import math
import os
import shutil
import time
import urllib.request

from PIL import Image

import comfy_paths

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESET2D_PATH = os.path.join(ROOT, "ref", "pose2d_presets.json")
POSE2D_LLLITE = "anima-lllite-pose-1.safetensors"

# COCO-18 肢段配色与连接 (0Nose,1Neck,2RS,3RE,4RW,5LS,6LE,7LW,8RH,9RK,10RA,11LH,12LK,13LA,14REye,15LEye,16REar,17LEar)
LIMB_SEQ = [
    (1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7),
    (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13),
    (1, 0), (0, 14), (14, 16), (0, 15), (15, 17),
]
LIMB_COLORS = [
    (153, 0, 0), (153, 51, 0), (153, 102, 0), (153, 153, 0), (102, 153, 0), (51, 153, 0),
    (0, 153, 0), (0, 153, 51), (0, 153, 102), (0, 153, 153), (0, 102, 153), (0, 51, 153),
    (0, 0, 153), (51, 0, 153), (102, 0, 153), (153, 0, 153), (153, 0, 102),
]
JOINT_COLORS = [
    (255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0),
    (0, 255, 0), (0, 255, 85), (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255),
    (0, 0, 255), (85, 0, 255), (170, 0, 255), (255, 0, 255), (255, 0, 170), (255, 0, 85),
]
_MIRROR_PAIRS = [(2, 5), (3, 6), (4, 7), (8, 11), (9, 12), (10, 13), (14, 15), (16, 17)]


def load_pose2d_library():
    if os.path.isfile(PRESET2D_PATH):
        return json.load(open(PRESET2D_PATH, encoding="utf-8"))
    return {"presets": {}}


def pose2d_lllite_name():
    mp_dir = os.path.join(os.path.dirname(comfy_paths.COMFY_IN), "models", "model_patches")
    return POSE2D_LLLITE if os.path.isfile(os.path.join(mp_dir, POSE2D_LLLITE)) else ""


def mirror_pose2d(joints):
    """左右镜像 2D COCO-18 关节点字典（支持 str 或 int 键）。"""
    src = {int(k): [float(v[0]), float(v[1])] for k, v in (joints or {}).items() if isinstance(v, (list, tuple)) and len(v) >= 2}
    out = {k: [1.0 - v[0], v[1]] for k, v in src.items()}
    for a, b in _MIRROR_PAIRS:
        va, vb = out.get(a), out.get(b)
        if va is not None and vb is not None:
            out[a], out[b] = vb, va
        elif va is not None:
            out[b] = va
            out.pop(a, None)
        elif vb is not None:
            out[a] = vb
            out.pop(b, None)
    return {str(k): v for k, v in sorted(out.items())}


def _project_joints(joints, cx=0.5, gy=0.92, ratio=0.76, W=832, H=1152):
    """将归一化 2D 关节点按人物落点 (cx, gy) 与画面占比 ratio 映射到像素坐标。"""
    pts = {int(k): (float(v[0]), float(v[1])) for k, v in (joints or {}).items() if isinstance(v, (list, tuple)) and len(v) >= 2}
    if not pts:
        return {}
    xs = [p[0] for p in pts.values()]
    ys = [p[1] for p in pts.values()]
    span_y = max(0.15, max(ys) - min(ys))
    # 骨架最高点约在鼻/眼，到头顶留 6% 余量，脚踝到底约 3%
    target_h = float(H) * float(ratio) * 0.90
    scale = target_h / span_y
    mid_x = 0.5 * (min(xs) + max(xs))
    max_y = max(ys)
    foot_y = float(H) * float(gy) - float(H) * float(ratio) * 0.03
    cx_px = float(W) * float(cx)
    return {k: (cx_px + (x - mid_x) * scale, foot_y - (max_y - y) * scale) for k, (x, y) in pts.items()}


def render_dwpose(joints_or_name, size=(832, 1152), cx=0.5, gy=0.92, ratio=0.76, mirror=False,
                  preserve_coords=False, draw_face_dots=True):
    """将 2D COCO-18 关节点渲染为标准 DWPose 黑底彩色骨架图。"""
    import cv2
    import numpy as np

    W, H = int(size[0]), int(size[1])
    lib = load_pose2d_library()
    presets = lib.get("presets") or {}
    if isinstance(joints_or_name, str):
        joints = (presets.get(joints_or_name) or next(iter(presets.values()), {})).get("joints") or {}
    else:
        joints = joints_or_name or {}
    if mirror:
        joints = mirror_pose2d(joints)

    if preserve_coords:
        pts = {int(k): (float(v[0]) * W, float(v[1]) * H)
               for k, v in (joints or {}).items() if isinstance(v, (list, tuple)) and len(v) >= 2}
    else:
        pts = _project_joints(joints, cx=cx, gy=gy, ratio=ratio, W=W, H=H)
    skip_k = set() if draw_face_dots else {14, 15, 16, 17}
    canvas = np.zeros((H, W, 3), dtype=np.uint8)
    sw = max(3, int(round(min(W, H) / 180.0)))
    for (a, b), col in zip(LIMB_SEQ, LIMB_COLORS):
        if a in skip_k or b in skip_k or a not in pts or b not in pts:
            continue
        p1, p2 = pts[a], pts[b]
        mx, my = (p1[0] + p2[0]) * 0.5, (p1[1] + p2[1]) * 0.5
        length = math.hypot(p1[0] - p2[0], p1[1] - p2[1])
        if length < 2:
            continue
        ang = math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))
        poly = cv2.ellipse2Poly((int(mx), int(my)), (max(1, int(length / 2)), sw), int(ang), 0, 360, 15)
        cv2.fillConvexPoly(canvas, poly, col)
    for k, (x, y) in pts.items():
        if k not in skip_k and 0 <= k < len(JOINT_COLORS):
            cv2.circle(canvas, (int(x), int(y)), sw, JOINT_COLORS[k], thickness=-1)
    return Image.fromarray(canvas)


def extract_pose2d_from_image(img_path):
    """用站台 SDPose 从人物图/参考图自动抽取归一化 COCO-18 2D 骨架 JSON。"""
    import reproj_parts as parts
    if not img_path or not os.path.isfile(img_path):
        return {}
    res = parts.detect_safe(img_path)
    pj = res.get("json")
    if not pj or not os.path.isfile(pj):
        return {}
    data = json.load(open(pj, encoding="utf-8"))
    item = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
    people = item.get("people") or []
    if not people:
        return {}
    arr = people[0].get("pose_keypoints_2d") or []
    if len(arr) < 54:
        return {}
    cw = float(item.get("canvas_width") or 0)
    ch = float(item.get("canvas_height") or 0)
    if cw <= 1 or ch <= 1:
        with Image.open(img_path) as im:
            cw, ch = float(im.width), float(im.height)
    out = {}
    for i in range(18):
        x, y, s = float(arr[i * 3]), float(arr[i * 3 + 1]), float(arr[i * 3 + 2])
        if s > 0.18 and x >= 0 and y >= 0:
            out[str(i)] = [round(x / cw, 4), round(y / ch, 4)]
    return out if len(out) >= 8 else {}


def resolve_pose2d_image(pose_cfg, size, cx=0.5, gy=0.92, ratio=0.76, out_path=None,
                         preserve_coords=False, draw_face_dots=True):
    """按 2D 骨架配置渲染黑底 DWPose 条件图；未启用或无权重时返回 None。"""
    if not isinstance(pose_cfg, dict) or str(pose_cfg.get("mode") or "") != "2d":
        return None
    if not pose2d_lllite_name():
        return None
    lib = load_pose2d_library()
    presets = lib.get("presets") or {}
    preset = str(pose_cfg.get("preset") or "").strip()
    if preset in ("none", "auto") and not pose_cfg.get("joints2d"):
        return None
    joints = copy.deepcopy(pose_cfg.get("joints2d") or (presets.get(preset) or next(iter(presets.values()), {})).get("joints") or {})
    if not joints:
        return None
    im = render_dwpose(joints, size=size, cx=cx, gy=gy, ratio=ratio,
                       mirror=bool(pose_cfg.get("mirror", False)),
                       preserve_coords=preserve_coords, draw_face_dots=draw_face_dots)
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        im.save(out_path)
        return out_path
    return im


def run_job_with_pose2d(pose_img_path, prompt, negative, width, height, steps, cfg, seed, loras, prefix,
                        ref_img_path=None, denoise=1.0, model="", strength=1.25, end_percent=0.48,
                        noise_mask_path=None, timeout=600):
    """通过 AnimaLLLiteApply 绑定 2D DWPose 骨架图（anima-lllite-pose-1）出图或同生。"""
    patch_name = pose2d_lllite_name()
    if not patch_name:
        raise RuntimeError("未找到 anima-lllite-pose-1.safetensors")
    cf = os.environ.get("STATION_COMFY", os.environ.get("COMFY_API", "http://127.0.0.1:8188"))
    ts = f"{int(time.time() * 1000)}_{os.getpid()}"
    cn_name = f"2dpose_{prefix}_{ts}.png"
    shutil.copy2(pose_img_path, os.path.join(comfy_paths.COMFY_IN, cn_name))

    unet = model or "anima-base-v1.0.safetensors"
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_06b_base.safetensors", "type": "stable_diffusion", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
    }
    if ref_img_path:
        ref_name = f"2dref_{prefix}_{ts}.png"
        Image.open(ref_img_path).convert("RGB").resize((int(width), int(height)), Image.LANCZOS).save(os.path.join(comfy_paths.COMFY_IN, ref_name))
        g["4"] = {"class_type": "LoadImage", "inputs": {"image": ref_name}}
        g["12"] = {"class_type": "ImageScale", "inputs": {"image": ["4", 0], "upscale_method": "lanczos", "width": int(width), "height": int(height), "crop": "center"}}
        g["13"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["12", 0], "vae": ["3", 0]}}
        lat_node = ["13", 0]
        if noise_mask_path and os.path.isfile(noise_mask_path):
            m_name = f"2dmask_{prefix}_{ts}.png"
            Image.open(noise_mask_path).convert("L").resize((int(width), int(height)), Image.BILINEAR).save(os.path.join(comfy_paths.COMFY_IN, m_name))
            g["14"] = {"class_type": "LoadImageMask", "inputs": {"image": m_name, "channel": "red"}}
            g["15"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["13", 0], "mask": ["14", 0]}}
            lat_node = ["15", 0]
    else:
        g["4"] = {"class_type": "EmptyLatentImage", "inputs": {"width": int(width), "height": int(height), "batch_size": 1}}
        lat_node = ["4", 0]

    m_out = ["1", 0]
    nid = 20
    for item in (loras or []):
        name = str(item.get("name") or "").strip()
        w = float(item.get("weight", 1.0))
        if not name or w <= 0:
            continue
        k = str(nid)
        g[k] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": m_out, "lora_name": name, "strength_model": w}}
        m_out = [k, 0]
        nid += 1

    g["30"] = {"class_type": "ModelPatchLoader", "inputs": {"name": patch_name}}
    g["31"] = {"class_type": "LoadImage", "inputs": {"image": cn_name}}
    g["32"] = {"class_type": "AnimaLLLiteApply", "inputs": {
        "model": m_out, "model_patch": ["30", 0], "image": ["31", 0],
        "strength": float(strength), "start_percent": 0.0, "end_percent": float(end_percent),
    }}
    g["9"] = {"class_type": "KSampler", "inputs": {
        "model": ["32", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": lat_node,
        "seed": int(seed), "steps": int(steps), "cfg": float(cfg),
        "sampler_name": "euler", "scheduler": "simple", "denoise": float(denoise),
    }}
    g["10"] = {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}}
    g["11"] = {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": prefix}}

    req = urllib.request.Request(cf + "/prompt", data=json.dumps({"prompt": g, "client_id": "sunloom_2dpose"}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    pid = json.loads(urllib.request.urlopen(req, timeout=60).read())["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(2)
        h = json.loads(urllib.request.urlopen(cf + "/history/" + pid, timeout=60).read())
        if pid in h:
            ent = h[pid]
            if ent.get("status", {}).get("status_str") != "success":
                raise RuntimeError("2D Pose Comfy 失败: " + str(ent.get("status", {}).get("messages", []))[-300:])
            for node in (ent.get("outputs") or {}).values():
                for im in node.get("images", []):
                    return os.path.join(comfy_paths.COMFY_OUT, im["filename"])
            raise RuntimeError("2D Pose 未返回图片")
    raise TimeoutError("2D Pose Comfy 超时")


def build_cogen_mask(fg, px, py, W, H, steps_dir):
    """无侵蚀三区连续噪点遮罩：远景 82(0.24噪)防融景，外扩羽化环+投影 255(0.74噪)融光生影，完整人物前景 145(0.42噪)保头/手/腿不断层。"""
    import numpy as np
    from PIL import ImageDraw, ImageFilter

    tw, th = fg.size
    feet_y = py + th
    cm = Image.new("L", (W, H), 82)
    # 仅在人物贴边羽化带与脚底投影区给 255（避免头顶上方大片满噪长出重影头/发饰）
    dx0, dy0 = max(0, px), max(0, py)
    dx1, dy1 = min(W, px + tw), min(H, py + th)
    sx0, sy0 = dx0 - px, dy0 - py
    sx1, sy1 = sx0 + (dx1 - dx0), sy0 + (dy1 - dy0)
    full_a = np.asarray(fg.split()[3])
    fg_canvas = Image.new("L", (W, H), 0)
    if dx1 > dx0 and dy1 > dy0:
        fg_canvas.paste(Image.fromarray(np.where(full_a[sy0:sy1, sx0:sx1] >= 128, 255, 0).astype(np.uint8), "L"), (dx0, dy0))
    halo = fg_canvas.filter(ImageFilter.MaxFilter(max(15, int(min(W, H) * 0.024) | 1)))
    halo_d = ImageDraw.Draw(halo)
    ex0, ey0 = max(0, px - int(tw * 0.35)), max(0, feet_y - int(th * 0.18))
    ex1, ey1 = min(W, px + tw + int(tw * 0.45)), min(H, feet_y + int(th * 0.20))
    if ex1 > ex0 and ey1 > ey0:
        halo_d.ellipse((ex0, ey0, ex1, ey1), fill=255)
    arr = np.where(np.asarray(halo) >= 128, 255, 82).astype(np.uint8)
    if dx1 > dx0 and dy1 > dy0:
        roi = arr[dy0:dy1, dx0:dx1]
        arr[dy0:dy1, dx0:dx1] = np.where(full_a[sy0:sy1, sx0:sx1] >= 128, 145, roi)
    cm = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(max(8, int(min(W, H) * 0.012))))
    out_p = os.path.join(steps_dir, "00_cogen_mask.png")
    cm.save(out_p)
    return out_p
