# -*- coding: utf-8 -*-
"""手部高分辨率精修：裁切 → 放大 → 重绘 → 贴回 → 姿态复检。

为什么需要它：站台现有的 /api/handfix 是整图蒙版重绘，
手在 1344×768 里只有 40~60px，模型画不出五根手指。

链：
    1) SDPose 检测手（/api/detect-hand-pose）得到手框
    2) 带边距裁切，放大 3~4 倍（上限 1024）
    3) 在放大图上按「手框」重绘（保留袖口/手腕上下文）
    4) 缩回、羽化贴回原图
    5) 再跑一次 SDPose，比较手部关键点数量与分数（验收）
"""
import argparse
import json
import os
import time
import urllib.request
import urllib.parse

from PIL import Image, ImageDraw, ImageFilter
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.environ.get("SUNLOOM_API", "http://127.0.0.1:8770")
from comfy_paths import COMFY_IN as CI
from comfy_paths import COMFY_OUT as OUT
CF = os.environ.get("STATION_COMFY", os.environ.get("COMFY_API", "http://127.0.0.1:8188"))


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def _get(url):
    return json.loads(urllib.request.urlopen(url, timeout=60).read())


def detect(path):
    """SDPose 手部检测，返回 [{x,y,w,h,score,points,hand}]。"""
    q = urllib.parse.quote(os.path.abspath(path))
    r = _get(API + "/api/detect-hand-pose?path=" + q)
    return r.get("boxes") or []


SR_MODEL = "4x-AnimeSharp.safetensors"


def sr_upscale(img, on_prompt=None, check_cancel=None):
    """用 AnimeSharp 4x 超分；失败返回 None（调用方回退 Lanczos）。"""
    try:
        try:
            import mem_plan
            mem_plan.schedule("upscale", unet=SR_MODEL, reason="sr_upscale", context="coop")
        except Exception:
            pass
        name = "srin_%s.png" % time.strftime("%H%M%S")
        img.save(os.path.join(CI, name))
        g = {"1": {"class_type": "LoadImage", "inputs": {"image": name}},
             "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": SR_MODEL}},
             "3": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
             "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "SRHAND"}}}
        jid = _post(CF + "/prompt", {"prompt": g})["prompt_id"]
        if on_prompt:
            on_prompt(jid)
        t0 = time.time()
        while time.time() - t0 < 300:
            if check_cancel:
                check_cancel()
            time.sleep(2)
            h = _get(CF + "/history/" + jid)
            if jid in h:
                outs = h[jid].get("outputs") or {}
                for node in outs.values():
                    for im in node.get("images", []):
                        return Image.open(os.path.join(OUT, im["filename"])).convert("RGB")
                return None
        return None
    except Exception as e:  # noqa: BLE001
        print("[sr] 跳过:", str(e)[:80])
        return None


def detect_raw(path):
    q = urllib.parse.quote(os.path.abspath(path))
    return _get(API + "/api/detect-hand-pose?path=" + q)


def hand_points(pose_json, hand="right"):
    """姿态 JSON → 21 个 (x, y, score)。"""
    try:
        data = json.load(open(pose_json, encoding="utf-8"))
        if isinstance(data, dict):
            data = [data]
        person = (data[0].get("people") or [{}])[0]
        arr = person.get("hand_%s_keypoints_2d" % hand) or []
        pts = [(arr[i], arr[i + 1], arr[i + 2]) for i in range(0, len(arr) - 2, 3)]
        return [(x, y) for x, y, s in pts if s > 0.1 and x >= 0 and y >= 0]
    except Exception:
        return []


def hand_polygon(pose_json, hand="right", expand=0.12):
    """从姿态 JSON 取 21 点，做凸包；拿不到就返回 None。"""
    try:
        data = json.load(open(pose_json, encoding="utf-8"))
        if isinstance(data, dict):
            data = [data]
        person = (data[0].get("people") or [{}])[0]
        arr = person.get("hand_%s_keypoints_2d" % hand) or []
        pts = [(arr[i], arr[i + 1], arr[i + 2]) for i in range(0, len(arr) - 2, 3)]
        pts = [(x, y) for x, y, s in pts if s > 0.15 and x >= 0 and y >= 0]
        if len(pts) < 6:
            return None
        import cv2
        arr2 = np.array(pts, dtype=np.int32)
        hull = cv2.convexHull(arr2)
        cx, cy = hull[:, 0, 0].mean(), hull[:, 0, 1].mean()
        hull = np.array([[[int(cx + (x - cx) * (1 + expand)), int(cy + (y - cy) * (1 + expand))]]
                         for x, y in hull[:, 0, :]], dtype=np.int32)
        return hull
    except Exception:
        return None


def repaint(src, box, prompt, negative="", denoise=0.6, scale=3.0, pad=0.35,
            steps=26, cfg=5.2, seed=0, loras=None, tag="hand", max_side=1024, shape="rect", model="",
            parent_job_id="", on_prompt=None, check_cancel=None):
    """裁切放大后重绘，贴回原图。返回 (新图路径, 调试信息)。"""
    im = Image.open(src).convert("RGB")
    W, H = im.size
    x, y, w, h = int(box["x"]), int(box["y"]), max(8, int(box["w"])), max(8, int(box["h"]))
    px, py = int(w * pad), int(h * pad)
    x0, y0 = max(0, x - px), max(0, y - py)
    x1, y1 = min(W, x + w + px), min(H, y + h + py)
    crop = im.crop((x0, y0, x1, y1))

    if check_cancel:
        check_cancel()
    sr = sr_upscale(crop, on_prompt=on_prompt, check_cancel=check_cancel) if scale > 0 else None
    if check_cancel:
        check_cancel()
    if sr is not None:
        big = sr
        tw, th = big.width, big.height
        if max(tw, th) > max_side:
            r = max_side / float(max(tw, th))
            tw, th = int(tw * r), int(th * r)
        tw = max(64, tw // 8 * 8)
        th = max(64, th // 8 * 8)
        big = big.resize((tw, th), Image.LANCZOS)
    else:
        r = min(scale if scale > 0 else 1.0, max_side / float(max(crop.width, crop.height, 1)))
        tw = max(64, int(crop.width * r) // 8 * 8)
        th = max(64, int(crop.height * r) // 8 * 8)
        big = crop.resize((tw, th), Image.LANCZOS)
    # 模板骨架提示（细线）：让模型看到指节走向
    if box.get("guide"):
        gd = ImageDraw.Draw(big)
        gp = [((gx - x0) * tw / crop.width, (gy - y0) * th / crop.height) for gx, gy in box["guide"]]
        for i in range(len(gp) - 1):
            gd.line([gp[i], gp[i + 1]], fill=(120, 90, 80), width=3)

    # 蒙版：放大图里的局部框（白=重绘），四周留出上下文
    mx0 = int((x - x0) * tw / crop.width)
    my0 = int((y - y0) * th / crop.height)
    mx1 = int((x + w - x0) * tw / crop.width)
    my1 = int((y + h - y0) * th / crop.height)
    m = Image.new("L", (tw, th), 0)
    md = ImageDraw.Draw(m)
    poly = box.get("polygon")
    if poly:
        # 指关节凸包微外扩：留出指尖重分离余量，同时不误伤袖口
        pts = [((px - x0) * tw / crop.width, (py - y0) * th / crop.height) for px, py in poly]
        md.polygon([(p[0], p[1]) for p in pts], fill=255)
        m = m.filter(ImageFilter.MaxFilter(9))
    elif shape == "ellipse":
        md.ellipse((mx0, my0, mx1, my1), fill=255)
    else:
        md.rectangle((mx0, my0, mx1, my1), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(max(2, int((mx1 - mx0) * 0.06))))
    stamp = "%s_%s_%03d" % (tag, time.strftime("%H%M%S"), int(time.time() * 1000) % 1000)
    mask_name = "handmask_%s.png" % stamp
    Image.merge("RGB", (m, m, m)).save(os.path.join(CI, mask_name))

    big_path = os.path.join(os.path.dirname(src), "_big_%s.png" % stamp)
    big.save(big_path)
    try:
        import mem_plan
        mem_plan.schedule("anima", reason="repaint_" + tag, context="coop")
    except Exception:
        pass

    body = {"prompt": prompt, "negative": negative or
            "extra fingers, fused fingers, missing fingers, deformed hand, bad anatomy, "
            "text, watermark, lowres, blurry",
            "mode": "inpaint", "reference": big_path, "mask": mask_name,
            "denoise": denoise, "steps": steps, "cfg": cfg,
            "seed": seed or int(time.time()) % 1000000,
            "loras": loras or [], "prefix": "HAND_" + tag, "save_to": "paper",
            "width": tw, "height": th}
    if model:
        body["model"] = model
    if parent_job_id:
        body["parent_job_id"] = parent_job_id
    jid = _post(API + "/api/run", body)["job_id"]
    t0 = time.time()
    res = None
    while time.time() - t0 < 600:
        if check_cancel:
            check_cancel()
        time.sleep(2)
        st = _get(API + "/api/job/" + jid)
        if st.get("status") in ("done", "error", "cancelled", "interrupted"):
            imgs = (st.get("result") or {}).get("images") or []
            if imgs:
                res = imgs[0]
            break
    if not res:
        raise RuntimeError("手部重绘失败")

    new_big = Image.open(res).convert("RGB")
    back = new_big.resize(crop.size, Image.LANCZOS)
    soft = m.resize(crop.size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(2))
    # 融光：把手部低频色调拉回原图，否则贴回处会偏亮/偏冷
    try:
        import fusion
        graded, _ = fusion.lowfreq_match(back.convert("RGBA"), im, (x0, y0, x1, y1), weight=0.35)
        back = graded.convert("RGB")
    except Exception as e:  # noqa: BLE001
        print("[harmonize] 跳过:", str(e)[:80])
    out = im.copy()
    out.paste(back, (x0, y0), soft)
    dst = os.path.join(os.path.dirname(src), "patch_%s.png" % stamp)
    out.save(dst)
    return dst, {"crop": [x0, y0, x1, y1], "upscale": [tw, th], "denoise": denoise}


def verify(path):
    """复检：手部关键点数量与最高分。"""
    boxes = detect(path)
    return [{"hand": b.get("hand"), "points": b.get("points"), "score": b.get("score")} for b in boxes]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--prompt", default="hand with five natural fingers, relaxed pose")
    ap.add_argument("--negative", default="")
    ap.add_argument("--scale", type=float, default=3.0)
    ap.add_argument("--denoise", type=float, default=0.6)
    ap.add_argument("--pad", type=float, default=0.35)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--index", type=int, default=0, help="第几只手（按分数降序）")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    before = verify(a.src)
    print("检测到手框:", json.dumps(before, ensure_ascii=False))
    boxes = detect(a.src)
    if not boxes:
        print("未检测到手，退出")
        return
    b = dict(boxes[min(a.index, len(boxes) - 1)])
    raw = detect_raw(a.src)
    poly = hand_polygon(raw.get("json"), b.get("hand", "right"))
    if poly is not None:
        b["polygon"] = poly.reshape(-1, 2).tolist()
        print("蒙版: 凸包 %d 点" % len(b["polygon"]))
    print("精修手:", b.get("hand"), b.get("x"), b.get("y"), b.get("w"), b.get("h"))
    dst, meta = repaint(a.src, b, a.prompt, a.negative, a.denoise, a.scale, a.pad, seed=a.seed)
    if a.out:
        import shutil
        shutil.copy2(dst, a.out)
        dst = a.out
    after = verify(dst)
    print("贴回:", dst)
    print("调试:", json.dumps(meta, ensure_ascii=False))
    print("复检:", json.dumps(after, ensure_ascii=False))


if __name__ == "__main__":
    main()
