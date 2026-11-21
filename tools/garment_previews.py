# -*- coding: utf-8 -*-
"""服装展示图：给每件服装跑一张"素体穿着"的样张，供服装库悬停预览。

  python tools/garment_previews.py            # 只补缺失的
  python tools/garment_previews.py --all      # 全部重跑
  python tools/garment_previews.py --only maid

产出：SD-Picture/garment_previews/<key>.png + ref/garment_previews.json
"""
import argparse
import json
import os
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "http://127.0.0.1:8770"
OUT = os.path.join(ROOT, "SD-Picture", "garment_previews")
INDEX = os.path.join(ROOT, "ref", "garment_previews.json")

# 素体立绘：不挂任何人物 LoRA，只让底模画一个穿着这套服装的人
BODY = ("1girl, solo, adult woman, full body standing, straight-on, arms down, "
        "looking at viewer, (plain light gray background:1.3), "
        "(detailed face:1.2), (clear shading:1.25), (visible midtones:1.2), "
        "clean lineart, (whole body from head to feet:1.25)")
NEG = ("(background:1.4), scenery, depth of field, blurry, bad anatomy, extra limbs, "
       "cropped, out of frame, watermark, text, "
       "overexposed, washed out, pale, flat lighting, monochrome, lineart, "
       "halftone, screentone, dot pattern, photo, photorealistic, 3d render, "
       "ugly, distorted face, deformed face, "
       "nude, naked, topless, bottomless, nipples, areola, censored")


def post(url, data):
    req = urllib.request.Request(url, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read().decode())


def get(url):
    return json.loads(urllib.request.urlopen(url, timeout=30).read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--steps", type=int, default=32)
    ap.add_argument("--size", default="832x1216")
    a = ap.parse_args()

    boot = get(API + "/api/bootstrap")
    garments = boot.get("garments") or {}
    os.makedirs(OUT, exist_ok=True)
    index = {}
    if os.path.isfile(INDEX):
        try:
            index = json.load(open(INDEX, encoding="utf-8"))
        except Exception:
            index = {}
    w, h = [int(x) for x in a.size.lower().split("x")]
    todo = []
    for key, g in garments.items():
        if a.only and key != a.only:
            continue
        dst = os.path.join(OUT, key + ".png")
        if not a.all and os.path.isfile(dst):
            index[key] = dst
            continue
        todo.append((key, g, dst))

    print("待生成 %d 件（共 %d）" % (len(todo), len(garments)))
    for i, (key, g, dst) in enumerate(todo, 1):
        prompt = BODY + ", " + (g.get("prompt") or "")
        neg = NEG + ", " + (g.get("negative") or "")
        print("[%d/%d] %s ..." % (i, len(todo), key), flush=True)
        try:
            r = post(API + "/api/run", {
                "prompt": prompt, "negative": neg, "width": w, "height": h,
                "steps": a.steps, "cfg": 5.5, "seed": 0,
                "prefix": "gv_" + str(key).replace(" ", "_"),
                # 只用画风增强 LoRA（style_lora_a），不挂任何人物 LoRA
                "loras": [{"name": "style_lora_a5E585B6E4B889.YDAV.safetensors", "weight": 0.66}],
                "model": "anima-base-v1.0.safetensors",
                "blocks_pos": [], "blocks_neg": [],
            })
        except Exception as e:
            print("  提交失败:", e, flush=True)
            continue
        jid = r.get("job_id")
        path = ""
        for _ in range(120):
            time.sleep(2)
            try:
                j = get(API + "/api/job/" + jid)
            except Exception:
                continue
            if j.get("status") == "done":
                res = j.get("result") or {}
                imgs = res.get("images") or []
                if imgs and isinstance(imgs[0], str):
                    path = imgs[0]
                break
            if j.get("status") not in ("running", None):
                break
        if path and os.path.isfile(path):
            import shutil
            shutil.copy2(path, dst)
            index[key] = dst
            print("  ->", dst, flush=True)
        else:
            print("  失败/超时:", path, flush=True)

    json.dump(index, open(INDEX, "w", encoding="utf-8"), ensure_ascii=False)
    print("索引已写:", INDEX, "共", len(index), "件")


if __name__ == "__main__":
    main()
