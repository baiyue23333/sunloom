# -*- coding: utf-8 -*-
"""手部/姿态区域检测路由（SDPose 优先，失败时肤色启发式兜底）。"""
import os
import re
import shutil
import sys
import tempfile
import threading
import time

from fastapi import APIRouter, HTTPException

import comfy as cf
import graph as gf
import store
import svc_mem
from svc_recipes import _prepare_reference
from svc_state import DATA_DIR, ROOT, comfy_out, read_json, write_json

_TOOLS_DIR = os.path.join(ROOT, "tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

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


def _img_size(img_path):
    try:
        from PIL import Image
        with Image.open(img_path) as im:
            return im.size
    except Exception:
        return None


def _hand_boxes_from_pose(path, img_path=""):
    data = read_json(path, [])
    if isinstance(data, dict):
        data = [data]
    if not data:
        return []
    person = (data[0].get("people") or [{}])[0]
    wh = _img_size(img_path) if img_path else None
    w = int((wh[0] if wh else 0) or data[0].get("canvas_width") or 1024)
    h = int((wh[1] if wh else 0) or data[0].get("canvas_height") or 1536)
    try:
        import reproj_parts as _rp
        fb = _rp.face_box_from_pose(path, w, h)
        boxes = _rp.hand_boxes_from_pose(path, w, h, face_box=fb)
        out = []
        for b in boxes:
            item = {"x": int(b["x"]), "y": int(b["y"]), "w": int(b["w"]), "h": int(b["h"]),
                    "hand": b.get("hand", ""), "score": round(float(b.get("score") or 0), 3), "source": "pose"}
            if b.get("polygon"):
                item["polygon"] = b["polygon"]
            out.append(item)
        return out
    except Exception:
        pass
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
            return {"source": "pose(cache)", "json": hit, "boxes": _hand_boxes_from_pose(hit, path)}
        ref = _prepare_reference(path)
        tag = "p_" + re.sub(r"[^A-Za-z0-9]", "", os.path.splitext(os.path.basename(path))[0])[:18]
        svc_mem.prepare_stage("sdpose", unet="sdpose_wholebody_fp16.safetensors", reason="pose:" + tag, context="coop")
        js = _pose_run(ref, tag)
        cache[key] = js
        write_json(_POSE_CACHE_PATH, cache)
    return {"source": "pose", "json": js, "boxes": _hand_boxes_from_pose(js, path)}


def _read_saved_hand_boxes(path):
    rec = store.get_recipe(path) if path else None
    if isinstance(rec, dict) and "hand_boxes" in rec:
        return {
            "source": "saved(recipe)",
            "boxes": list(rec.get("hand_boxes") or []),
            "hand_prompt": str(rec.get("hand_prompt") or ""),
            "cached": True,
        }
    try:
        import reproj_provenance as _rprov
        png_meta = _rprov.read_hand_boxes_png(path)
        if png_meta is not None:
            return {
                "source": "saved(png)",
                "boxes": png_meta["boxes"],
                "hand_prompt": png_meta["hand_prompt"],
                "cached": True,
            }
    except Exception:
        pass
    return None


def _persist_hand_boxes(path, boxes, hand_prompt=""):
    try:
        import reproj_provenance as _rprov
        _rprov.embed_hand_boxes(path, boxes, hand_prompt)
    except Exception:
        pass
    try:
        rec = store.get_recipe(path)
        if isinstance(rec, dict):
            upd = dict(rec)
            upd["hand_boxes"] = list(boxes or [])
            if hand_prompt and not upd.get("hand_prompt"):
                upd["hand_prompt"] = hand_prompt
            store.upsert_recipe(path, upd)
    except Exception:
        pass


def ensure_image_hand_boxes(path, hand_prompt="", force=False, allow_skin_fallback=False):
    """确保图片附带手部坐标元数据（PNG + recipe）；默认只读取或用 SDPose 检出，不修改画面像素。"""
    if not path or not os.path.isfile(path):
        return {"source": "missing", "boxes": [], "hand_prompt": hand_prompt, "cached": False}
    if not force:
        saved = _read_saved_hand_boxes(path)
        if saved is not None:
            return saved
    src, boxes = "pose", []
    try:
        r = api_detect_hand_pose(path)
        src = r.get("source") or "pose"
        boxes = list(r.get("boxes") or [])
    except Exception as e:
        if not allow_skin_fallback:
            raise
        fallback = api_detect_hand(path)
        src = "skin(pose-fail)"
        boxes = list(fallback.get("boxes") or [])
        fallback["pose_error"] = str(e)[:200]
    _persist_hand_boxes(path, boxes, hand_prompt)
    return {"source": src, "boxes": boxes, "hand_prompt": hand_prompt, "cached": False}


@router.get("/api/hand-boxes")
def api_hand_boxes(path: str, detect: int = 0, force: int = 0):
    if not os.path.isfile(path):
        raise HTTPException(404, "图片不存在")
    if not force:
        saved = _read_saved_hand_boxes(path)
        if saved is not None:
            return saved
        if not detect:
            return {"source": "none", "boxes": [], "hand_prompt": "", "cached": False}
    try:
        return ensure_image_hand_boxes(path, force=bool(force), allow_skin_fallback=True)
    except Exception as e:
        raise HTTPException(500, "检测手部坐标失败: %s" % str(e)[:200])


@router.get("/api/detect-hand-auto")
def api_detect_hand_auto(path: str, force: int = 0):
    """优先返回已保存的手部坐标；必要时姿态模型检测，失败时才用肤色兜底并写回图片与配方。"""
    if not force:
        saved = _read_saved_hand_boxes(path)
        if saved is not None:
            return saved
    try:
        r = api_detect_hand_pose(path)
        boxes = list(r.get("boxes") or [])
        _persist_hand_boxes(path, boxes)
        return {"source": r.get("source") or ("pose" if boxes else "pose-empty"),
                "json": r.get("json"), "boxes": boxes, "cached": False}
    except Exception as e:
        try:
            fallback = api_detect_hand(path)
            fallback["source"] = "skin(pose-fail)"
            fallback["pose_error"] = str(e)[:200]
            _persist_hand_boxes(path, fallback.get("boxes") or [])
            return fallback
        except Exception as e2:
            raise HTTPException(500, "自动找手失败: %s / %s" % (e, e2))


def run_precise_handfix(req, jid, jobs_dict, job_log_fn, job_save_fn, add_recipe_fn, out_dir):
    """按人眼确认的手部坐标做局部超分放大精修，产出图保存至 station_out 并附带新坐标与配方。"""
    t0 = time.time()
    from svc_tasks import bind_prompt, cancelled, finish
    from svc_validation import validate_loras, validate_model

    def check_cancel():
        if cancelled(jid):
            raise RuntimeError("任务已取消")

    try:
        check_cancel()
        parts = [int(float(v.strip())) for v in str(req.box or "").split(",") if v.strip()]
        if len(parts) != 4 or parts[2] < 4 or parts[3] < 4:
            raise ValueError("box 格式应为 x,y,w,h")
        box = {"x": parts[0], "y": parts[1], "w": parts[2], "h": parts[3]}
        if req.polygon and len(req.polygon) >= 3:
            box["polygon"] = req.polygon
        rec = (store.get_recipe(req.image) or {}) if req.image else {}
        use_loras = validate_loras(list(req.loras or rec.get("detail_loras") or rec.get("loras") or []))
        use_model = validate_model(str(req.model or rec.get("model") or "").strip())
        prompt = (req.prompt or rec.get("hand_prompt")
                  or "delicate anime hand, five natural fingers, clean hand anatomy, same art style")
        negative = (req.negative or rec.get("negative")
                    or "extra fingers, fused fingers, missing fingers, deformed hands, bad anatomy, watermark, text, lowres")
        seed = int(req.seed or (int(time.time()) % 1000000))
        import hand_precise as _hp
        with tempfile.TemporaryDirectory(prefix="handfix_") as tmpd:
            tmp_src = os.path.join(tmpd, os.path.basename(req.image))
            shutil.copy2(req.image, tmp_src)
            patched, meta = _hp.repaint(
                tmp_src, box, prompt, negative,
                denoise=float(req.denoise), scale=3.5, pad=0.50,
                steps=int(req.steps), cfg=float(req.cfg),
                seed=seed, loras=use_loras, tag="handfix", max_side=768,
                shape=("rect" if box.get("polygon") else "ellipse"), model=use_model,
                parent_job_id=jid, on_prompt=lambda pid: bind_prompt(jid, pid), check_cancel=check_cancel,
            )
            check_cancel()
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, "%s_%s_s%d_%s.png" % (req.prefix or "handfix", time.strftime("%H%M%S"), seed, jid))
            shutil.copy2(patched, out_path)
        try:
            hb_res = ensure_image_hand_boxes(out_path, hand_prompt=prompt, force=True, allow_skin_fallback=False)
            out_boxes = hb_res.get("boxes") or []
        except Exception:
            out_boxes = []
        if not add_recipe_fn(out_path, {
            "ts": time.time(), "mode": "handfix", "workflow": "hand_precise",
            "positive": prompt, "negative": negative,
            "blocks_pos": rec.get("blocks_pos") or [], "blocks_neg": rec.get("blocks_neg") or [],
            "size": list(_img_size(out_path) or rec.get("size") or [1024, 1536]),
            "steps": int(req.steps), "cfg": float(req.cfg), "seed": seed,
            "denoise": float(req.denoise), "loras": use_loras,
            "detail_loras": rec.get("detail_loras") or use_loras,
            "model": use_model, "reference": req.image,
            "manifest_path": rec.get("manifest_path") or "",
            "hand_prompt": prompt, "hand_boxes": out_boxes, "handfix_box": box,
        }):
            raise RuntimeError("精修图已生成，但配方写入失败")
        check_cancel()
        finish(jid, "done", progress=1.0, result={
            "images": [out_path], "seed": seed, "workflow": "hand_precise",
            "denoise": float(req.denoise), "elapsed": round(time.time() - t0, 1),
            "hand_boxes": out_boxes, "meta": meta,
        })
        job_log_fn(jid, "handfix precise done: " + os.path.basename(out_path))
        job_save_fn(jid)
    except Exception as e:
        finish(jid, "error", result={"error": str(e)})
        job_log_fn(jid, "handfix EXC " + str(e)[:240])
        job_save_fn(jid)
