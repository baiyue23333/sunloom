# -*- coding: utf-8 -*-
"""剪影蒙版：白底黑剪影 -> 二值 mask（填洞/最大连通域/羽化）。"""
import json
import os
import time
import urllib.request

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "http://127.0.0.1:8770"


def _post(path, obj):
    req = urllib.request.Request(API + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def _get(path):
    return json.loads(urllib.request.urlopen(API + path, timeout=60).read())


def run(body, tag):
    pid = _post("/api/run", body)["job_id"]
    t0 = time.time()
    while time.time() - t0 < 600:
        s = _get("/api/job/" + pid)
        if s.get("status") in ("done", "error"):
            imgs = (s.get("result") or {}).get("images") or []
            if not imgs:
                raise RuntimeError(tag + ": " + str(s.get("result"))[:200])
            return imgs[0]
        time.sleep(2)
    raise TimeoutError(tag)


def mask_from_image(im, thresh=110, min_area=0.05, max_area=0.85):
    """黑剪影 -> 羽化 L mask；失败返回 None。"""
    import cv2
    g = np.asarray(im.convert("L"))
    m = (g < thresh).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    if n < 2:
        return None
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    m = (lab == idx).astype(np.uint8) * 255
    area = float((m > 0).mean())
    if not (min_area <= area <= max_area):
        return None
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    m = np.zeros_like(m)
    cv2.drawContours(m, cnts, -1, 255, -1)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    al = Image.fromarray(m).filter(ImageFilter.GaussianBlur(1.5))
    return al


def make(desc, seed, w=1024, h=1536, out=""):
    prompt = ("(solid black silhouette of %s:1.5), (pure white background:1.4), "
              "(flat vector silhouette:1.2), (no details:1.2), (no shading:1.2), "
              "(no background objects:1.2), (full body:1.2)" % desc)
    img = run({"prompt": prompt,
               "negative": "color, gradient, background scenery, text, watermark, "
                           "multiple figures, close-up, cropped legs",
               "width": w, "height": h, "steps": 24, "cfg": 4.5, "seed": seed,
               "prefix": "SILHOUETTE", "mode": "t2i", "save_to": "paper"}, "silhouette")
    im = Image.open(img).convert("RGB")
    al = mask_from_image(im)
    if al is None:
        return None, im
    out = out or img.replace(".png", "_mask.png")
    al.save(out)
    return out, im
