# -*- coding: utf-8 -*-
"""3D 动作骨架库与着色人偶渲染器（配合 toyxyz Anima ControlNet-LLLite）。"""
import copy
import json
import math
import os

import numpy as np
from PIL import Image

import comfy_paths

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESET_PATH = os.path.join(ROOT, "ref", "pose_presets.json")
POSE_LLLITE_OUTLINE = "anima_3dpose_outline_7000.safetensors"
POSE_LLLITE_BASE = "anima_3dpose_6200.safetensors"


def load_pose_library():
    if os.path.isfile(PRESET_PATH):
        return json.load(open(PRESET_PATH, encoding="utf-8"))
    return {"profiles": {}, "presets": {}}


def pose_lllite_name():
    """优先使用带互补色轮廓的 3D Pose LLLite，缺失时回退 6200 或空串。"""
    mp_dir = os.path.join(os.path.dirname(comfy_paths.COMFY_IN), "models", "model_patches")
    for fn in (POSE_LLLITE_OUTLINE, POSE_LLLITE_BASE):
        if os.path.isfile(os.path.join(mp_dir, fn)):
            return fn
    return ""


def _rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float32)


def _rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float32)


def _rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float32)


def _euler(rx=0.0, ry=0.0, rz=0.0):
    return _rot_y(math.radians(ry)) @ _rot_x(math.radians(rx)) @ _rot_z(math.radians(rz))


def mirror_pose(pose):
    """左右镜像 FK 姿势字典。"""
    p = copy.deepcopy(pose or {})
    p["pelvis_yaw"] = -float(p.get("pelvis_yaw", 0.0))
    for k in ("pelvis_tilt", "spine", "chest", "neck", "head"):
        v = p.get(k)
        if v and len(v) == 3:
            p[k] = [float(v[0]), -float(v[1]), -float(v[2])]
    for j in ("shoulder", "elbow", "hip", "knee", "ankle"):
        lk, rk = f"l_{j}", f"r_{j}"
        lv = list(p.get(lk) or [0, 0, 0])
        rv = list(p.get(rk) or [0, 0, 0])
        p[lk] = [float(rv[0]), -float(rv[1]), -float(rv[2])]
        p[rk] = [float(lv[0]), -float(lv[1]), -float(lv[2])]
    return p


def build_skeleton(pose, profile_name="petite", mirror=False):
    lib = load_pose_library()
    profiles = lib.get("profiles") or {}
    pr = profiles.get(profile_name) or next(iter(profiles.values()))
    if mirror:
        pose = mirror_pose(pose)
    primitives = []

    def add_ellipsoid(pid, center, rx_mat, radii):
        primitives.append(("ellipsoid", int(pid), np.asarray(center, np.float32), rx_mat.astype(np.float32), np.asarray(radii, np.float32)))

    def add_capsule(pid, a, b, r0, r1):
        primitives.append(("capsule", int(pid), np.asarray(a, np.float32), np.asarray(b, np.float32), float(r0), float(r1)))

    p_rot = _rot_y(math.radians(pose.get("pelvis_yaw", 0))) @ _euler(*pose.get("pelvis_tilt", (0, 0, 0)))
    pelvis = np.array([0.0, 0.52, 0.0], dtype=np.float32)

    s_rot = p_rot @ _euler(*pose.get("spine", (0, 0, 0)))
    c_rot = s_rot @ _euler(*pose.get("chest", (0, 0, 0)))
    n_rot = c_rot @ _euler(*pose.get("neck", (0, 0, 0)))
    h_rot = n_rot @ _euler(*pose.get("head", (0, 0, 0)))

    waist = pelvis + p_rot @ np.array([0.0, 0.095, 0.0], np.float32)
    chest = waist + s_rot @ np.array([0.0, 0.130, 0.0], np.float32)
    neck_base = chest + c_rot @ np.array([0.0, 0.082, 0.0], np.float32)
    head_c = neck_base + n_rot @ np.array([0.0, 0.092, 0.0], np.float32)

    add_ellipsoid(1, pelvis, p_rot, pr["pelvis_r"])
    add_capsule(1, pelvis + p_rot @ np.array([0, 0.02, 0], np.float32), waist, pr["pelvis_r"][0] * 0.78, pr["waist_r"])
    add_capsule(1, waist, chest + c_rot @ np.array([0, 0.015, 0], np.float32), pr["waist_r"], pr["chest_r"][0] * 0.88)
    add_ellipsoid(1, chest, c_rot, pr["chest_r"])
    sh_l = neck_base + c_rot @ np.array([-pr["shoulder_w"] * 0.48, -0.024, 0.0], np.float32)
    sh_r = neck_base + c_rot @ np.array([pr["shoulder_w"] * 0.48, -0.024, 0.0], np.float32)
    add_capsule(1, sh_l, sh_r, 0.032, 0.032)

    add_capsule(2, chest + c_rot @ np.array([0, 0.03, 0], np.float32), head_c - n_rot @ np.array([0, 0.04, 0], np.float32), pr["neck_r"] * 1.1, pr["neck_r"])
    add_ellipsoid(2, head_c, h_rot, pr["head_r"])
    nose = head_c + h_rot @ np.array([0.0, -0.008, pr["head_r"][2] * 0.96], np.float32)
    add_ellipsoid(2, nose, h_rot, (0.011, 0.014, 0.017))

    for pid, side, sx in ((3, "l", -1.0), (4, "r", 1.0)):
        sh = neck_base + c_rot @ np.array([sx * pr["shoulder_w"] * 0.5, -0.025, 0.0], np.float32)
        ua_rot = c_rot @ _euler(*pose.get(f"{side}_shoulder", (0, 0, 0)))
        ua_len, ua_r0, ua_r1 = pr["upper_arm"]
        el = sh + ua_rot @ np.array([0.0, -ua_len, 0.0], np.float32)
        add_capsule(pid, sh, el, ua_r0, ua_r1)

        el_ang = pose.get(f"{side}_elbow", (20, 0, 0))
        fa_rot = ua_rot @ _euler(-abs(el_ang[0]), el_ang[1], el_ang[2])
        fa_len, fa_r0, fa_r1 = pr["forearm"]
        wr = el + fa_rot @ np.array([0.0, -fa_len, 0.0], np.float32)
        add_capsule(pid, el, wr, fa_r0, fa_r1)

        hd_len, hd_w, hd_t = pr["hand"]
        hd_c = wr + fa_rot @ np.array([0.0, -hd_len * 0.52, 0.0], np.float32)
        add_ellipsoid(pid, hd_c, fa_rot, (hd_t, hd_len * 0.55, hd_w))

    for pid, side, sx in ((5, "l", -1.0), (6, "r", 1.0)):
        hp = pelvis + p_rot @ np.array([sx * pr["hip_w"] * 0.5, -0.02, 0.0], np.float32)
        th_rot = p_rot @ _euler(*pose.get(f"{side}_hip", (0, 0, 0)))
        th_len, th_r0, th_r1 = pr["thigh"]
        kn = hp + th_rot @ np.array([0.0, -th_len, 0.0], np.float32)
        add_capsule(pid, hp, kn, th_r0, th_r1)

        kn_ang = pose.get(f"{side}_knee", (10, 0, 0))
        cf_rot = th_rot @ _euler(abs(kn_ang[0]), kn_ang[1], kn_ang[2])
        cf_len, cf_r0, cf_r1 = pr["calf"]
        ak = kn + cf_rot @ np.array([0.0, -cf_len, 0.0], np.float32)
        add_capsule(pid, kn, ak, cf_r0, cf_r1)

        ft_rot = cf_rot @ _euler(*pose.get(f"{side}_ankle", (0, 0, 0)))
        toe = ak + ft_rot @ np.array([0.0, -0.022, pr["foot_len"]], np.float32)
        add_capsule(pid, ak + ft_rot @ np.array([0, -0.018, -0.015], np.float32), toe, pr["foot_r"], pr["foot_r"] * 0.72)

    return primitives


def render_mannequin(pose_or_name, size=(832, 1152), cx=0.5, gy=0.92, ratio=0.76,
                     cam_yaw=0.0, cam_pitch=4.0, profile="petite", mirror=False,
                     base_color=(142, 118, 224), outline_px=4, outline_color=(175, 245, 0)):
    W, H = int(size[0]), int(size[1])
    lib = load_pose_library()
    presets = lib.get("presets") or {}
    pose = presets.get(pose_or_name) if isinstance(pose_or_name, str) else pose_or_name
    if not pose:
        pose = next(iter(presets.values()))
    prims = build_skeleton(pose, profile_name=profile, mirror=mirror)

    cam_r = _euler(cam_pitch, cam_yaw, 0.0)
    persp = 0.22
    ys_min = 999.0
    pts_top = []
    for prm in prims:
        if prm[0] == "ellipsoid":
            _, _, c, _, rad = prm
            cp = cam_r @ c
            r_m = float(np.max(rad))
            ys_min = min(ys_min, cp[1] - r_m)
            pts_top.append((cp[1] + r_m, cp[2]))
        else:
            _, _, a, b, r0, r1 = prm
            for p, r in ((a, r0), (b, r1)):
                cp = cam_r @ p
                ys_min = min(ys_min, cp[1] - r)
                pts_top.append((cp[1] + r, cp[2]))

    top_span = max(((y - ys_min) / max(0.35, 1.0 - z * persp)) for y, z in pts_top)
    fig_h_px = H * float(ratio)
    scale = fig_h_px / max(0.2, top_span)
    half = 0.5 if min(W, H) >= 512 else 1.0
    sw, sh = max(160, int(round(W * half))), max(160, int(round(H * half)))
    s_scale = scale * (sh / float(H))
    ox = sw * float(cx)
    oy = sh * float(gy)

    zbuf = np.full((sh, sw), -1e6, dtype=np.float32)
    nbuf = np.zeros((sh, sw, 3), dtype=np.float32)
    pbuf = np.zeros((sh, sw), dtype=np.uint8)

    def proj(p3):
        cp = cam_r @ p3
        pf = 1.0 / (1.0 - cp[2] * persp)
        return ox + cp[0] * s_scale * pf, oy - (cp[1] - ys_min) * s_scale * pf, cp[2], pf

    for prm in prims:
        if prm[0] == "ellipsoid":
            _, pid, c, rmat, rad = prm
            c_cam, rm_cam = cam_r @ c, cam_r @ rmat
            sx, sy, _, pf = proj(c)
            rmax = float(np.max(rad)) * s_scale * pf * 1.15
            x0, x1 = max(0, int(sx - rmax)), min(sw, int(sx + rmax) + 1)
            y0, y1 = max(0, int(sy - rmax)), min(sh, int(sy + rmax) + 1)
            if x1 <= x0 or y1 <= y0:
                continue
            yy, xx = np.mgrid[y0:y1, x0:x1]
            px, py = (xx - ox) / (s_scale * pf), -(yy - oy) / (s_scale * pf) + ys_min
            inv_s = rm_cam.T / rad[:, None]
            dx, dy = px - c_cam[0], py - c_cam[1]
            v0x = inv_s[0, 0] * dx + inv_s[0, 1] * dy
            v0y = inv_s[1, 0] * dx + inv_s[1, 1] * dy
            v0z = inv_s[2, 0] * dx + inv_s[2, 1] * dy
            vz = inv_s[:, 2]
            A = float(np.dot(vz, vz))
            B = 2.0 * (v0x * vz[0] + v0y * vz[1] + v0z * vz[2])
            C = v0x * v0x + v0y * v0y + v0z * v0z - 1.0
            disc = B * B - 4.0 * A * C
            hit = disc >= 0
            if not np.any(hit):
                continue
            t = np.where(hit, (-B + np.sqrt(np.maximum(disc, 0.0))) / (2.0 * A), -1e6)
            z_world = c_cam[2] + t
            upd = hit & (z_world > zbuf[y0:y1, x0:x1])
            if not np.any(upd):
                continue
            lx, ly, lz = v0x + t * vz[0], v0y + t * vz[1], v0z + t * vz[2]
            nx = inv_s[0, 0] * lx + inv_s[1, 0] * ly + inv_s[2, 0] * lz
            ny = inv_s[0, 1] * lx + inv_s[1, 1] * ly + inv_s[2, 1] * lz
            nz = inv_s[0, 2] * lx + inv_s[1, 2] * ly + inv_s[2, 2] * lz
            nlen = np.sqrt(nx * nx + ny * ny + nz * nz + 1e-8)
            zbuf[y0:y1, x0:x1] = np.where(upd, z_world, zbuf[y0:y1, x0:x1])
            pbuf[y0:y1, x0:x1] = np.where(upd, pid, pbuf[y0:y1, x0:x1])
            for ch, nc in enumerate((nx / nlen, ny / nlen, nz / nlen)):
                nbuf[y0:y1, x0:x1, ch] = np.where(upd, nc, nbuf[y0:y1, x0:x1, ch])
        else:
            _, pid, a, b, r0, r1 = prm
            ac, bc = cam_r @ a, cam_r @ b
            sax, say, _, pfa = proj(a)
            sbx, sby, _, pfb = proj(b)
            pfm = 0.5 * (pfa + pfb)
            rm = max(r0, r1) * s_scale * pfm * 1.15
            x0, x1 = max(0, int(min(sax, sbx) - rm)), min(sw, int(max(sax, sbx) + rm) + 1)
            y0, y1 = max(0, int(min(say, sby) - rm)), min(sh, int(max(say, sby) + rm) + 1)
            if x1 <= x0 or y1 <= y0:
                continue
            yy, xx = np.mgrid[y0:y1, x0:x1]
            px, py = (xx - ox) / (s_scale * pfm), -(yy - oy) / (s_scale * pfm) + ys_min
            ab = bc - ac
            ab2 = float(ab[0] * ab[0] + ab[1] * ab[1]) + 1e-8
            u = np.clip(((px - ac[0]) * ab[0] + (py - ac[1]) * ab[1]) / ab2, 0.0, 1.0)
            rad_l = r0 + u * (r1 - r0)
            dx, dy = px - (ac[0] + u * ab[0]), py - (ac[1] + u * ab[1])
            d2, r2 = dx * dx + dy * dy, rad_l * rad_l
            hit = d2 <= r2
            if not np.any(hit):
                continue
            dz = np.sqrt(np.maximum(r2 - d2, 0.0))
            z_world = (ac[2] + u * ab[2]) + dz
            upd = hit & (z_world > zbuf[y0:y1, x0:x1])
            if not np.any(upd):
                continue
            zbuf[y0:y1, x0:x1] = np.where(upd, z_world, zbuf[y0:y1, x0:x1])
            pbuf[y0:y1, x0:x1] = np.where(upd, pid, pbuf[y0:y1, x0:x1])
            for ch, nc in enumerate((dx / np.maximum(rad_l, 1e-6), dy / np.maximum(rad_l, 1e-6), dz / np.maximum(rad_l, 1e-6))):
                nbuf[y0:y1, x0:x1, ch] = np.where(upd, nc, nbuf[y0:y1, x0:x1, ch])

    fg = zbuf > -1e5
    l1 = np.array([0.42, 0.60, 0.68], np.float32)
    l1 /= np.linalg.norm(l1)
    h1 = l1 + np.array([0.0, 0.0, 1.0], np.float32)
    h1 /= np.linalg.norm(h1)
    ndotl = np.clip(nbuf[..., 0] * l1[0] + nbuf[..., 1] * l1[1] + nbuf[..., 2] * l1[2], 0.0, 1.0)
    ndoth = np.clip(nbuf[..., 0] * h1[0] + nbuf[..., 1] * h1[1] + nbuf[..., 2] * h1[2], 0.0, 1.0)
    rim = np.clip(1.0 - nbuf[..., 2], 0.0, 1.0) ** 2.0
    diff = 0.24 + 0.78 * ndotl + 0.10 * rim
    spec = 0.38 * (ndoth ** 24.0)

    col = np.array(base_color, np.float32)[None, None, :]
    rgb = np.zeros((sh, sw, 3), np.float32)
    rgb[fg] = np.clip(col * diff[fg, None] + 255.0 * spec[fg, None], 0, 255)
    img = Image.fromarray(rgb.astype(np.uint8)).resize((W, H), Image.LANCZOS)

    if outline_px > 0:
        import cv2
        arr = np.asarray(img).copy()
        fg_full = np.asarray(Image.fromarray((fg * 255).astype(np.uint8)).resize((W, H), Image.NEAREST)) > 127
        p_full = np.asarray(Image.fromarray(pbuf).resize((W, H), Image.NEAREST))
        z_full = np.asarray(Image.fromarray(zbuf).resize((W, H), Image.BILINEAR))
        px_w = max(2, int(round(outline_px * min(W, H) / 768.0)))
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (px_w * 2 + 1, px_w * 2 + 1))
        outer = (cv2.dilate(fg_full.astype(np.uint8), k) > 0) & (~fg_full)
        p_diff = (p_full != np.roll(p_full, 1, 0)) | (p_full != np.roll(p_full, 1, 1))
        z_diff = (np.abs(z_full - np.roll(z_full, 1, 0)) > 0.025) | (np.abs(z_full - np.roll(z_full, 1, 1)) > 0.025)
        inner = fg_full & p_diff & z_diff
        inner = cv2.dilate(inner.astype(np.uint8), np.ones((max(2, px_w // 2 + 1),) * 2, np.uint8)) > 0
        arr[outer | inner] = np.array(outline_color, np.uint8)
        img = Image.fromarray(arr)
    return img


def resolve_pose_image(pose_cfg, size, cx=0.5, gy=0.92, ratio=0.76, out_path=None):
    """按配置字典生成/保存 3D 绑骨条件图；未启用或无权重时返回 None。"""
    if not isinstance(pose_cfg, dict) or not pose_cfg.get("enabled"):
        return None
    preset = str(pose_cfg.get("preset") or "").strip()
    if preset in ("none", "auto") and not pose_cfg.get("joints"):
        return None
    lib = load_pose_library()
    base = copy.deepcopy((lib.get("presets") or {}).get(preset) or next(iter((lib.get("presets") or {}).values())))
    if isinstance(pose_cfg.get("joints"), dict):
        for k, v in pose_cfg["joints"].items():
            base[k] = v
    patch_name = pose_lllite_name()
    outline = 4 if patch_name == POSE_LLLITE_OUTLINE else 0
    img = render_mannequin(
        base, size=size, cx=cx, gy=gy, ratio=ratio,
        cam_yaw=float(pose_cfg.get("cam_yaw", 0.0)),
        cam_pitch=float(pose_cfg.get("cam_pitch", 4.0)),
        profile=str(pose_cfg.get("profile") or "petite"),
        mirror=bool(pose_cfg.get("mirror", False)),
        outline_px=outline,
    )
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        img.save(out_path)
        return out_path
    return img


def run_job_with_pose(pose_img_path, prompt, negative, width, height, steps, cfg, seed, loras, prefix,
                      ref_img_path=None, denoise=1.0, model="", strength=0.76, end_percent=0.45,
                      noise_mask_path=None, timeout=600):
    """通过 ComfyUI 原生 ModelPatchLoader + AnimaLLLiteApply 绑定 3D 骨架出图或同生。"""
    import shutil
    import time
    import urllib.request

    patch_name = pose_lllite_name()
    if not patch_name:
        raise RuntimeError("未找到 anima_3dpose_*_lllite 模型文件")
    cf = os.environ.get("STATION_COMFY", os.environ.get("COMFY_API", "http://127.0.0.1:8188"))
    ts = f"{int(time.time() * 1000)}_{os.getpid()}"
    cn_name = f"3dpose_{prefix}_{ts}.png"
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
        ref_name = f"3dref_{prefix}_{ts}.png"
        Image.open(ref_img_path).convert("RGB").resize((int(width), int(height)), Image.LANCZOS).save(os.path.join(comfy_paths.COMFY_IN, ref_name))
        g["4"] = {"class_type": "LoadImage", "inputs": {"image": ref_name}}
        g["12"] = {"class_type": "ImageScale", "inputs": {"image": ["4", 0], "upscale_method": "lanczos", "width": int(width), "height": int(height), "crop": "center"}}
        g["13"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["12", 0], "vae": ["3", 0]}}
        lat_node = ["13", 0]
        if noise_mask_path and os.path.isfile(noise_mask_path):
            m_name = f"3dmask_{prefix}_{ts}.png"
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

    req = urllib.request.Request(cf + "/prompt", data=json.dumps({"prompt": g, "client_id": "sunloom_3dpose"}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    pid = json.loads(urllib.request.urlopen(req, timeout=60).read())["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(2)
        h = json.loads(urllib.request.urlopen(cf + "/history/" + pid, timeout=60).read())
        if pid in h:
            ent = h[pid]
            if ent.get("status", {}).get("status_str") != "success":
                raise RuntimeError("3D Pose Comfy 失败: " + str(ent.get("status", {}).get("messages", []))[-300:])
            for node in (ent.get("outputs") or {}).values():
                for im in node.get("images", []):
                    return os.path.join(comfy_paths.COMFY_OUT, im["filename"])
            raise RuntimeError("3D Pose 未返回图片")
    raise TimeoutError("3D Pose Comfy 超时")
