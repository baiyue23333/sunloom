# -*- coding: utf-8 -*-
"""构图自己定：先出空房间，再按几何分区逐件放入家具/人物。

和 schema 的区别：位置由 plan 里的多边形给定，模型只负责「在这块区域里画这个物件」。
"""
import argparse
import json
import os
import sys
import time

from PIL import Image, ImageDraw, ImageFilter
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paper_reproject as pr
import hand_precise as hp

ROOT = pr.ROOT
W, H = 1024, 1024

ENV_LORA = pr.ENV_LORA
CHAR_LORAS = [{"name": "style_lora_a5E585B6E4B889.YDAV.safetensors", "weight": 1.0},
              {"name": "local_char_lora_h2.safetensors", "weight": 1.0}]

PLAN = {
  "base": "empty old library room, bare wooden floor, floor-to-ceiling bookcase along the back wall, tall window on the left, no furniture, warm afternoon light, (empty room:1.3)",
  "order": ["bookcase", "table", "chairs", "lamp", "ladder", "character"],
  "items": {
    "bookcase": {"poly": [[0.06, 0.06], [0.94, 0.06], [0.94, 0.56], [0.06, 0.56]],
                 "prompt": "a floor-to-ceiling wooden bookcase filled with old books, warm wood tone, (books aligned on shelves:1.2)",
                 "denoise": 0.80},
    "table": {"poly": [[0.04, 0.64], [0.44, 0.60], [0.46, 0.74], [0.02, 0.78]],
              "prompt": "a long wooden reading table with carved legs, dark polished top, seen from the side",
              "denoise": 0.85},
    "chairs": {"poly": [[0.08, 0.72], [0.20, 0.72], [0.20, 0.88], [0.08, 0.88]],
               "prompt": "a wooden chair with a curved back, tucked at the end of the reading table",
               "denoise": 0.85},
    "chairs2": {"poly": [[0.26, 0.70], [0.38, 0.70], [0.38, 0.86], [0.26, 0.86]],
                "prompt": "a wooden chair with a curved back, beside the reading table",
                "denoise": 0.85},
    "lamp": {"poly": [[0.18, 0.54], [0.26, 0.54], [0.26, 0.64], [0.18, 0.64]],
             "prompt": "a brass desk lamp with a warm glowing shade standing on the table",
             "denoise": 0.85},
    "ladder": {"poly": [[0.78, 0.24], [0.88, 0.28], [0.92, 0.86], [0.82, 0.86]],
               "prompt": "a wooden library ladder leaning against the bookcase, evenly spaced rungs, both feet on the floor",
               "denoise": 0.85},
    "character": {"poly": [[0.50, 0.30], [0.64, 0.30], [0.66, 0.88], [0.48, 0.88]],
                  "prompt": "", "denoise": 0.85},
  },
}


def mask_from(poly, blur=4):
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).polygon([(int(x * W), int(y * H)) for x, y in poly], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(blur))
    import uuid
    name = "planmask_%s.png" % uuid.uuid4().hex[:8]
    Image.merge("RGB", (m, m, m)).save(os.path.join(hp.CI, name))
    return name, m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--char-prompt", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    out = a.out or os.path.join(ROOT, "SD-Picture", "plan", time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out, exist_ok=True)

    t0 = time.time()
    body = {"prompt": PLAN["base"], "negative": "furniture, chairs, table, people, text, watermark, lowres",
            "width": W, "height": H, "steps": 30, "cfg": 5.5, "seed": a.seed,
            "prefix": "PLAN_base", "mode": "t2i", "save_to": "paper",
            "loras": [{"name": ENV_LORA, "weight": 0.55}]}
    base_img = pr._wait(pr.pl.post(pr.API + "/api/run", body)["job_id"])
    canvas = Image.open(base_img).convert("RGB")
    canvas.save(os.path.join(out, "00_empty.png"))
    print("[empty] %.0fs" % (time.time() - t0), flush=True)

    order = PLAN["order"] + ["chairs2"]
    for name in order:
        if name not in PLAN["items"]:
            continue
        it = PLAN["items"][name]
        mname, _ = mask_from(it["poly"])
        prompt = a.char_prompt if name == "character" else it["prompt"]
        if name == "character":
            loras = CHAR_LORAS
        else:
            loras = [{"name": ENV_LORA, "weight": 0.5}]
        cur_path = os.path.join(out, "current.png")
        canvas.save(cur_path)
        t0 = time.time()
        res = pr.repaint(cur_path, mname,
                         prompt, "text, watermark, lowres, blurry, duplicate, two objects",
                         it["denoise"], "", 1.0, a.seed + len(name), loras=loras)
        canvas = Image.open(res).convert("RGB")
        canvas.save(os.path.join(out, "%02d_%s.png" % (order.index(name) + 1, name)))
        print("[%s] %.0fs" % (name, time.time() - t0), flush=True)

    canvas.save(os.path.join(out, "comp_plan.png"))
    print("OK", os.path.join(out, "comp_plan.png"))


if __name__ == "__main__":
    main()
