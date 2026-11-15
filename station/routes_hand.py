# -*- coding: utf-8 -*-
"""手部/姿态区域检测路由（SDPose 优先，失败时肤色启发式兜底）。"""
import os
import re
import threading
import time

from fastapi import APIRouter, HTTPException

import comfy as cf
import graph as gf
import svc_mem
from svc_recipes import _prepare_reference
from svc_state import DATA_DIR, comfy_out, read_json, write_json

router = APIRouter()

_POSE_CACHE_PATH = os.path.join(DATA_DIR, "pose_cache.json")
_POSE_LOCK = threading.Lock()


def _face_center(img):
    """用红眼定位脸：上半幅里最大的红色斑块。"""
    import cv2
    import numpy as np
    h, w = img.shape[:2]
    b, g, r = img[:, :, 0].astype(int), img[:, :, 1].astype(int), img[:, :, 2].astype(int)
    red = ((r > 130) & (g < 90) & (b < 90) & (np.abs(r - b) > 60)).astype(np.uint8) * 255
    red[int(h * 0.55):, :] = 0
    cnts, _ = cv2.findContours(red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in cnts:
        a = cv2.contourArea(c)
        if a < w * h * 0.00005 or a > w * h * 0.02:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        if best is None or a > best[0]:
            best = (a, x + bw // 2, y + bh // 2)
    return (best[1], best[2]) if best else None


def _skin_boxes(path, max_boxes=3):
    """启发式找手：肤色 + 指缝 + 色彩方差 + 用红眼排除脸。"""
    import cv2
    import numpy as np
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "读不到图片")
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    ycrcb = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
    mask = cv2.inRange(ycrcb, (0, 133, 77), (255, 180, 135))
    k = max(3, int(min(w, h) * 0.010))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    face = _face_center(img)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    total = w * h
    out = []
    for c in cnts:
        x, y, bw, bh = cv2.boundingRect(c)
        cx, cy = x + bw / 2, y + bh / 2
        area = cv2.contourArea(c)
        ratio = area / total
        if ratio < 0.0012 or ratio > 0.05:
            continue
        ar = bw / max(1, bh)
        if ar < 0.28 or ar > 3.4 or y < h * 0.15 or bw < w * 0.018 or bh < h * 0.015:
            continue
        if face and abs(cx - face[0]) < w * 0.16 and abs(cy - face[1]) < h * 0.16:
            continue
        m = np.zeros((h, w), np.uint8)
        cv2.drawContours(m, [c], -1, 255, -1)
        sat = hsv[:, :, 1][m > 0]
        sat_mean = float(sat.mean()) if sat.size else 0
        sat_std = float(sat.std()) if sat.size else 0
        hull = cv2.convexHull(c, returnPoints=False)
        ndef = 0
        try:
            d = cv2.convexityDefects(c, hull)
            if d is not None:
                for i in range(d.shape[0]):
                    if d[i, 0, 3] / 256.0 > max(6, min(w, h) * 0.012):
                        ndef += 1
        except Exception:
            pass
        fill = area / max(1, bw * bh)
        color_ok = (sat_mean < 100) and (sat_std < 58)
        score = (min(ndef, 5) * 0.2 + min(1.0, ratio / 0.015) * 0.2 + fill * 0.2
                 + (0.25 if color_ok else -0.15) + (-0.6 if sat_mean > 120 else 0))
        out.append({"x": int(x), "y": int(y), "w": int(bw), "h": int(bh),
                    "score": round(float(max(0.0, min(1.0, score))), 3),
                    "defects": int(ndef), "sat_mean": round(sat_mean, 1), "sat_std": round(sat_std, 1),
                    "ratio": round(float(ratio), 4), "color_ok": bool(color_ok)})
    out.sort(key=lambda d: (-d["defects"], -d["score"]))
    return out[:max_boxes], {"size": [w, h], "mask_pct": round(float((mask > 0).mean()) * 100, 2), "face": face}


@router.get("/api/detect-hand")
def api_detect_hand(path: str):
    boxes, meta = _skin_boxes(path)
    meta["count"] = len(boxes)
    meta["boxes"] = boxes
    return meta


def _pose_cache():
    return read_json(_POSE_CACHE_PATH, {}) or {}


def _pose_run(ref_name, tag):
    """跑一次 SDPose，返回 JSON 路径。"""
    wf, meta = gf.build("sdpose_probe", {"reference": ref_name, "prefix": tag})
    if meta["missing"]:
        raise HTTPException(503, "姿态节点缺失: " + ", ".join(meta["missing"]))
    pid = gf.submit(wf)
    t0 = time.time()
    while time.time() - t0 < 300:
        h = cf.history(pid)
        if h:
            st = h.get("status", {})
            if st.get("status_str") == "error":
                msg = ""
                for kind, payload in st.get("messages", []):
                    if kind == "execution_error":
                        msg = payload.get("exception_message", "")
                raise HTTPException(500, "姿态节点报错: " + str(msg)[:300])
            for node in (h.get("outputs") or {}).values():
                for t in (node.get("text") or []):
                    if isinstance(t, str) and t.endswith(".json") and os.path.isfile(t):
                        return t
            break
        time.sleep(1.5)
    pose_dir = os.path.join(comfy_out(), "pose")
    if os.path.isdir(pose_dir):
        cands = sorted([os.path.join(pose_dir, f) for f in os.listdir(pose_dir) if f.startswith(tag + "_")],
                       key=os.path.getmtime)
        if cands:
            return cands[-1]
    raise HTTPException(500, "没有生成姿态 JSON")


def _hand_boxes_from_pose(path):
    data = read_json(path, [])
    if isinstance(data, dict):
        data = [data]
    if not data:
        return []
    person = (data[0].get("people") or [{}])[0]
    w = int(data[0].get("canvas_width") or 1024)
    h = int(data[0].get("canvas_height") or 1536)
    out = []
    for key, label in (("hand_left_keypoints_2d", "left"), ("hand_right_keypoints_2d", "right")):
        arr = person.get(key) or []
        pts = [(arr[i], arr[i + 1], arr[i + 2]) for i in range(0, len(arr) - 2, 3)]
        valid = [p for p in pts if p[2] > 0.15 and p[0] >= 0 and p[1] >= 0]
        if len(valid) < 6:
            continue
        xs = [p[0] for p in valid]
        ys = [p[1] for p in valid]
        pad = 0.22 * max(max(xs) - min(xs), max(ys) - min(ys)) + 14
        x0 = int(max(0, min(xs) - pad))
        y0 = int(max(0, min(ys) - pad))
        x1 = int(min(w, max(xs) + pad))
        y1 = int(min(h, max(ys) + pad))
        bw, bh = x1 - x0, y1 - y0
        area = bw * bh / float(w * h)
        if area < 0.002 or area > 0.12 or x0 <= 2 or y0 <= 2 or x1 >= w - 2 or y1 >= h - 2:
            continue
        score = max(p[2] for p in valid)
        out.append({"x": x0, "y": y0, "w": bw, "h": bh, "hand": label,
                    "score": round(float(score), 3), "points": len(valid), "source": "pose"})
    out.sort(key=lambda d: -d["score"])
    return out[:2]


@router.get("/api/detect-hand-pose")
def api_detect_hand_pose(path: str):
    if not os.path.isfile(path):
        raise HTTPException(400, "图片不存在")
    st = os.stat(path)
    key = "%s|%d|%d" % (path, st.st_size, int(st.st_mtime))
    cache = _pose_cache()
    with _POSE_LOCK:
        hit = cache.get(key)
        if hit and os.path.isfile(hit):
            return {"source": "pose(cache)", "json": hit, "boxes": _hand_boxes_from_pose(hit)}
        ref = _prepare_reference(path)
        tag = "p_" + re.sub(r"[^A-Za-z0-9]", "", os.path.splitext(os.path.basename(path))[0])[:18]
        svc_mem.prepare_stage("sdpose", unet="sdpose_wholebody_fp16.safetensors", reason="pose:" + tag, context="coop")
        js = _pose_run(ref, tag)
        cache[key] = js
        write_json(_POSE_CACHE_PATH, cache)
    return {"source": "pose", "json": js, "boxes": _hand_boxes_from_pose(js)}


@router.get("/api/detect-hand-auto")
def api_detect_hand_auto(path: str):
    """姿态模型优先；失败时才用肤色兜底。"""
    try:
        r = api_detect_hand_pose(path)
        if r["boxes"]:
            return r
        return {"source": "pose-empty", "json": r.get("json"), "boxes": []}
    except Exception as e:
        try:
            fallback = api_detect_hand(path)
            fallback["source"] = "skin(pose-fail)"
            fallback["pose_error"] = str(e)[:200]
            return fallback
        except Exception as e2:
            raise HTTPException(500, "自动找手失败: %s / %s" % (e, e2))
