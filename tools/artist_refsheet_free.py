# -*- coding: utf-8 -*-
"""画师参考图（自由版）：只给最少的提示词，让 LoRA 自己发挥。"""
import json, os, sys, time, urllib.request
from PIL import Image, ImageDraw, ImageFont

B = "http://127.0.0.1:8770"
ROOT = r"A:/workflow/dsh"
OUT = os.path.join(ROOT, "SD-Picture", "station_out")
PROMPT = "1girl, solo, upper body, looking at viewer, grey background"
NEG = "lowres, blurry, bad anatomy, extra people, watermark, text"
SEED = 515151
W, H, STEPS, CFG = 640, 896, 26, 5.5

def post(p, o):
    r = urllib.request.Request(B + p, data=json.dumps(o).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=180).read())

def get(p):
    return json.loads(urllib.request.urlopen(B + p, timeout=60).read())

def run(prefix, name, w):
    loras = [{"name": name, "weight": w}] if name else []
    r = post("/api/run", {"prompt": PROMPT, "negative": NEG, "width": W, "height": H, "steps": STEPS,
                          "cfg": CFG, "seed": SEED, "prefix": prefix, "loras": loras,
                          "model": "anima-base-v1.0.safetensors"})
    t0 = time.time()
    while time.time() - t0 < 600:
        j = get("/api/job/" + r["job_id"])
        if j.get("status") in ("done", "error"):
            break
        time.sleep(2)
    return (j.get("result") or {}).get("images", [None])[0]

def main():
    weights = [float(x) for x in sys.argv[1].split(",")] if len(sys.argv) > 1 else [1.0, 1.4]
    b = get("/api/bootstrap")
    names = [n for n in b["loras"] if not n.startswith("sunhimi_") and "turbo" not in n and "modare" not in n]
    rows = []
    for w in weights:
        row = [("baseline", run("FREE_none_%s" % w, None, 0))]
        for n in names:
            row.append(("%s %.1f" % (n.split('.')[0][:18], w), run("FREE_%s_%s" % (n.split('.')[0][:14].replace(' ', ''), w), n, w)))
        rows.append(row)
        print("weight", w, "done")
    cw = 300
    f = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 12)
    rh = int(cw * H / W) + 18
    sheet = Image.new("RGB", (len(names + [0]) * cw, len(rows) * rh), (18, 18, 20))
    d = ImageDraw.Draw(sheet)
    for r, row in enumerate(rows):
        for c, (label, path) in enumerate(row):
            if not path or not os.path.isfile(path):
                continue
            im = Image.open(path).convert("RGB").resize((cw, int(cw * H / W)))
            sheet.paste(im, (c * cw, r * rh))
            d.text((c * cw + 3, r * rh + im.size[1] + 2), label, fill=(235, 225, 180), font=f)
    out = os.path.join(ROOT, "SD-Picture", "_inspect", "画师参考图_自由版.png")
    sheet.save(out)
    print("saved", out, sheet.size)

if __name__ == "__main__":
    main()
