# -*- coding: utf-8 -*-
"""画师 LoRA 参考图：固定提示词/种子/参数，逐个画师出图并拼图。
用法：python tools/artist_refsheet.py [权重,逗号分隔] [输出路径]
"""
import json, os, sys, time, urllib.request
from PIL import Image, ImageDraw, ImageFont

B = "http://127.0.0.1:8770"
ROOT = r"A:/workflow/dsh"
OUT_DIR = os.path.join(ROOT, "SD-Picture", "station_out")
PROMPT = ("1girl, solo, upper body, ivory white hair, straight fringe, "
          "heterochromia one red and one grey eye, a sunflower hair ornament, "
          "navy sailor uniform, grey background")
NEG = "lowres, blurry, bad anatomy, extra people"
SEED = 424242
W, H, STEPS, CFG = 640, 896, 24, 5.5

def post(p, obj):
    req = urllib.request.Request(B + p, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=180).read())

def get(p):
    return json.loads(urllib.request.urlopen(B + p, timeout=60).read())

def render(prefix, loras):
    r = post("/api/run", {"prompt": PROMPT, "negative": NEG, "width": W, "height": H,
                          "steps": STEPS, "cfg": CFG, "seed": SEED, "prefix": prefix,
                          "loras": loras, "model": "anima-base-v1.0.safetensors"})
    t0 = time.time()
    while time.time() - t0 < 600:
        j = get("/api/job/" + r["job_id"])
        if j.get("status") in ("done", "error"):
            break
        time.sleep(2)
    if j.get("status") != "done":
        return None
    return (j.get("result") or {}).get("images", [None])[0]

def main():
    weights = [float(x) for x in (sys.argv[1].split(",") if len(sys.argv) > 1 else ["0.6", "1.0"])]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "SD-Picture", "_inspect", "画师参考图.png")
    b = get("/api/bootstrap")
    all_loras = b["loras"]
    artists = [n for n in all_loras if not n.startswith("sunhimi_") and "turbo" not in n and "modare" not in n]
    rows = []
    for w in weights:
        row = [("无画师", render("REF_none_%s" % str(w).replace(".", ""), []))]
        for name in artists:
            short = name.replace(".safetensors", "")[:18]
            img = render("REF_%s_%s" % (short.replace(" ", ""), str(w).replace(".", "")),
                         [{"name": name, "weight": w}])
            row.append(("%s · %.1f" % (short, w), img))
        rows.append(row)
        print("weight", w, "done")
    cell_w = 300
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 13)
    cols = len(rows[0]); rh = int(cell_w * H / W) + 20
    sheet = Image.new("RGB", (cols * cell_w, len(rows) * rh), (18, 18, 20))
    d = ImageDraw.Draw(sheet)
    for r, row in enumerate(rows):
        for c, (label, path) in enumerate(row):
            if not path or not os.path.isfile(path):
                continue
            im = Image.open(path).convert("RGB").resize((cell_w, int(cell_w * H / W)))
            sheet.paste(im, (c * cell_w, r * rh))
            d.text((c * cell_w + 4, r * rh + im.size[1] + 3), label, fill=(235, 225, 180), font=font)
    sheet.save(out)
    print("saved", out, sheet.size)

if __name__ == "__main__":
    main()
