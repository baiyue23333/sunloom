# -*- coding: utf-8 -*-
"""蒙版内生成人物：中性灰底 + 剪影 mask + inpaint，导出 RGBA（alpha=mask）。"""
import json
import os
import shutil
import time
import urllib.request

import numpy as np
from PIL import Image

ROOT = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "http://127.0.0.1:8770"
INPUT = os.path.join(ROOT, "comfy", "ComfyUI", "input")


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


def assemble(rgb, mask, cut=None, band=4):
    """alpha 用 mask；若给 cut（BiRefNet RGBA），只在边界带取二者较大值。"""
    import cv2
    al = np.asarray(mask.convert("L"), dtype=np.uint8)
    if cut is not None:
        ca = np.asarray(cut.convert("RGBA").split()[3], dtype=np.uint8)
        if ca.shape != al.shape:
            ca = np.asarray(Image.fromarray(ca).resize(mask.size, Image.LANCZOS))
        edge = cv2.dilate((al > 24).astype(np.uint8), np.ones((2 * band + 1,) * 2, np.uint8)) > 0
        al = np.where(edge, np.maximum(al, ca), al).astype(np.uint8)
    out = rgb.convert("RGB").copy()
    out.putalpha(Image.fromarray(al))
    return out


def make(char_prompt, mask_path, out_path, seed, w=1024, h=1536, loras=None, cut=None, negative=""):
    os.makedirs(INPUT, exist_ok=True)
    ref = Image.new("RGB", (w, h), (128, 128, 128))
    ref_name = "maskcard_ref_%d.png" % int(time.time() * 1000)
    ref.save(os.path.join(INPUT, ref_name))
    mname = "maskcard_mask_%d.png" % int(time.time() * 1000)
    shutil.copyfile(mask_path, os.path.join(INPUT, mname))
    img = run({"prompt": char_prompt, "negative": negative,
               "width": w, "height": h, "steps": 30, "cfg": 5.4, "seed": seed,
               "prefix": "MASK_CARD", "mode": "inpaint", "reference": ref_name,
               "mask": mname, "denoise": 1.0, "save_to": "paper", "loras": loras or []}, "mask_card")
    rgb = Image.open(img).convert("RGB")
    al = Image.open(mask_path).convert("L").resize(rgb.size, Image.LANCZOS)
    out = assemble(rgb, al, cut)
    out.save(out_path)
    return out_path
