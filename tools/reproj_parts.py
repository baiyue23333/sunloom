# -*- coding: utf-8 -*-
"""重映工作台几何/骨架解析与遮罩辅助（从 coop_reproject.py 拆出）。"""
import json
import math
import os
import tempfile

import numpy as np
from PIL import Image, ImageChops, ImageFilter

import cutout
import hand_precise as hp
import plate_detail as pd
import sdp_body_mask as sbm


def detect_safe(img_path):
    try:
        return hp.detect_raw(img_path)
    except Exception as e:  # noqa: BLE001
        print("[pose] 检测跳过:", str(e)[:80], flush=True)
        return {}


def _roi_birefnet_union(plate_path, sdp_m, W, H):
    """按 SDPose 人体框裁剪局部做 BiRefNet 轮廓合并，包住礼服裙摆与垂落外套而不误抓远处背景。"""
    bb = sdp_m.getbbox()
    if not bb:
        return None
    bx0, by0, bx1, by1 = bb
    bw, bh = bx1 - bx0, by1 - by0
    px, pt, pb = max(48, int(bw * 0.45)), max(32, int(bh * 0.16)), max(24, int(bh * 0.12))
    rx0, ry0 = max(0, bx0 - px), max(0, by0 - pt)
    rx1, ry1 = min(W, bx1 + px), min(H, by1 + pb)
    rw, rh = rx1 - rx0, ry1 - ry0
    if rw < 64 or rh < 64:
        return None
    fd, tmp_roi = tempfile.mkstemp(suffix=".png", prefix="reproj_roi_")
    os.close(fd)
    try:
        Image.open(plate_path).convert("RGB").crop((rx0, ry0, rx1, ry1)).save(tmp_roi)
        matte = cutout.make_matte(tmp_roi, backend="birefnet", crop=False)
        if isinstance(matte, str):
            matte = Image.open(matte)
        a = matte.convert("RGBA").split()[3]
        if a.size != (rw, rh):
            a = a.resize((rw, rh), Image.LANCZOS)
        fg_pct = float((np.asarray(a) >= 96).mean()) * 100.0
        if not (6.0 <= fg_pct <= 78.0):
            return None
        a = a.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(max(3, int(min(W, H) * 0.006))))
        canvas = Image.new("L", (W, H), 0)
        canvas.paste(a, (rx0, ry0))
        return ImageChops.lighter(sdp_m, canvas)
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp_roi)
        except OSError:
            pass


def build_body_mask(plate_path, pose_json, W, H, cx_frac, gy_frac, ratio):
    sdp_fb = None
    if pose_json and os.path.isfile(pose_json):
        try:
            m, cov = sbm.body_mask(pose_json, W, H, grow=1.22)
            if m is not None and 1.0 <= cov <= 78.0:
                merged = _roi_birefnet_union(plate_path, m, W, H)
                if merged is not None:
                    mcov = float(np.asarray(merged).mean()) / 255.0 * 100.0
                    print("[mask] BiRefNet+SDPose %.1f%%" % mcov, flush=True)
                    return merged, "birefnet+sdpose", round(mcov, 2)
                print("[mask] SDPose 骨架 %.1f%%" % cov, flush=True)
                return m, "sdpose", round(cov, 2)
            if m is not None and 0.25 <= cov < 1.0:
                sdp_fb = (m, cov)
        except Exception as e:  # noqa: BLE001
            print("[mask] 骨架失败:", str(e)[:70], flush=True)

    try:
        matte = cutout.make_matte(plate_path, backend="birefnet", crop=False)
        if isinstance(matte, str):
            matte = Image.open(matte)
        a = matte.convert("RGBA").split()[3]
        if a.size != (W, H):
            a = a.resize((W, H), Image.LANCZOS)
        cov = float(np.asarray(a).mean()) / 255.0 * 100.0
        if (0.5 if sdp_fb is None else 1.8) <= cov <= 72.0:
            print("[mask] BiRefNet %.1f%%" % cov, flush=True)
            return a.filter(ImageFilter.MaxFilter(7)).filter(
                ImageFilter.GaussianBlur(max(4, int(min(W, H) * 0.008)))
            ), "birefnet", round(cov, 2)
    except Exception as e:  # noqa: BLE001
        print("[mask] BiRefNet 跳过:", str(e)[:70], flush=True)

    if sdp_fb is not None:
        print("[mask] SDPose 小人保留 %.2f%%" % sdp_fb[1], flush=True)
        return sdp_fb[0], "sdpose_small", round(sdp_fb[1], 2)

    fh = max(64, int(H * max(0.18, min(0.88, ratio or 0.30))))
    fw = int(fh * 0.48)
    cx = int(W * max(0.15, min(0.85, cx_frac or 0.34)))
    feet = int(H * max(0.45, min(0.96, gy_frac or 0.88)))
    box = (max(0, cx - fw // 2), max(0, feet - fh), min(W, cx + fw // 2), feet)
    m = sbm._humanoid(Image.new("L", (W, H), 0), box, W, H)
    m = m.filter(ImageFilter.GaussianBlur(max(6, int(min(W, H) * 0.01))))
    cov = float(np.asarray(m).mean()) / 255.0 * 100.0
    print("[mask] 回退人形站位框 cov=%.1f%%" % cov, flush=True)
    return m, "geometric_fallback", round(cov, 2)


def face_box_from_pose(pose_json, W, H):
    if not pose_json or not os.path.isfile(pose_json):
        return None
    pts, _, _ = sbm.load_pose(pose_json)
    if len(pts) < 18:
        return None

    def pt(i):
        x, y, s = pts[i]
        return (x, y) if s > 0.18 and 0 <= x <= W and 0 <= y <= H else None

    face_pts = [p for p in (pt(0), pt(14), pt(15), pt(16), pt(17)) if p]
    if len(face_pts) < 2 and not (pt(0) or pt(1)):
        return None
    ears, eyes, rs, ls = [pt(16), pt(17)], [pt(14), pt(15)], pt(2), pt(5)
    if ears[0] and ears[1]:
        r = max(14.0, math.hypot(ears[0][0] - ears[1][0], ears[0][1] - ears[1][1]) * 0.95)
    elif eyes[0] and eyes[1]:
        r = max(14.0, math.hypot(eyes[0][0] - eyes[1][0], eyes[0][1] - eyes[1][1]) * 1.95)
    elif rs and ls:
        r = max(14.0, math.hypot(rs[0] - ls[0], rs[1] - ls[1]) * 0.42)
    else:
        r = max(16.0, min(W, H) * 0.05)

    if face_pts:
        cx = sum(p[0] for p in face_pts) / len(face_pts)
        cy = sum(p[1] for p in face_pts) / len(face_pts) - r * 0.08
    else:
        neck = pt(1)
        cx, cy = neck[0], neck[1] - r * 1.1

    x0, y0 = int(max(0, cx - r * 1.15)), int(max(0, cy - r * 1.25))
    x1, y1 = int(min(W, cx + r * 1.15)), int(min(H, cy + r * 1.05))
    bw, bh = x1 - x0, y1 - y0
    if bw < 14 or bh < 14:
        return None
    return {"x": x0, "y": y0, "w": bw, "h": bh}


def hand_boxes_from_pose(pose_json, W, H, face_box=None):
    if not pose_json or not os.path.isfile(pose_json):
        return []
    try:
        data = json.load(open(pose_json, encoding="utf-8"))
        if isinstance(data, dict):
            data = [data]
        person = (data[0].get("people") or [{}])[0]
    except Exception:
        return []

    fh = float(face_box["h"]) if face_box else min(W, H) * 0.14
    max_rad = max(42.0, fh * 1.45)
    out = []
    for key, label in (("hand_left_keypoints_2d", "left"), ("hand_right_keypoints_2d", "right")):
        arr = person.get(key) or []
        pts = [(arr[i], arr[i + 1], arr[i + 2]) for i in range(0, len(arr) - 2, 3)]
        valid = [p for p in pts if p[2] > 0.18 and 0 <= p[0] <= W and 0 <= p[1] <= H]
        if len(valid) < 6:
            continue
        mx = float(np.median([p[0] for p in valid]))
        my = float(np.median([p[1] for p in valid]))
        valid = [p for p in valid if math.hypot(p[0] - mx, p[1] - my) <= max_rad]
        if len(valid) < 6:
            continue
        xs, ys = [p[0] for p in valid], [p[1] for p in valid]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 10.0)
        pad = 0.24 * span + 10
        x0, y0 = int(max(0, min(xs) - pad)), int(max(0, min(ys) - pad))
        x1, y1 = int(min(W, max(xs) + pad)), int(min(H, max(ys) + pad))
        bw, bh = x1 - x0, y1 - y0
        area = (bw * bh) / float(W * H)
        if bw < 12 or bh < 12 or area < 0.00035 or area > 0.16 or max(bw, bh) > max(fh * 2.1, min(W, H) * 0.25):
            continue
        if x0 <= 2 or y0 <= 2 or x1 >= W - 2 or y1 >= H - 2:
            continue
        score = max(p[2] for p in valid)
        box = {"x": x0, "y": y0, "w": bw, "h": bh, "hand": label, "score": float(score)}
        poly = hp.hand_polygon(pose_json, label)
        if poly is not None:
            box["polygon"] = poly.reshape(-1, 2).tolist()
        out.append(box)
    out.sort(key=lambda b: -b["score"])
    return out[:2]


def apply_feet_shadow(img, pose_json):
    if not pose_json or not os.path.isfile(pose_json):
        return img, 0
    W, H = img.size
    try:
        _, feet, _, _ = pd.load_pts(pose_json)
    except Exception:
        return img, 0
    visible_feet = [(x, y, s) for x, y, s in feet if s >= 0.2 and 4 <= x <= W - 4 and 4 <= y <= H - 4]
    if not visible_feet:
        return img, 0
    return pd.feet_shadow(img, visible_feet)
