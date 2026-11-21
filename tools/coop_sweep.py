# -*- coding: utf-8 -*-
"""合作模式批量扫描：场景矩阵 / 权重矩阵 / 比例矩阵，跑完自动拼图。

  python tools/coop_sweep.py --matrix all
"""
import argparse, json, os, time, urllib.request
from PIL import Image, ImageDraw, ImageFont

API = "http://127.0.0.1:8770"
ROOT = "/root/autodl-tmp/sunloom"
OUT = os.path.join(ROOT, "SD-Picture", "sweep")

SCENES = [
    ("霓虹雨夜", "rainy neon alley at night, wet pavement, warm shop lights"),
    ("教室黄昏", "sunlit classroom in the afternoon, dust motes, wooden desks, big windows"),
    ("天台逆光", "rooftop at dusk, city skyline, chain-link fence, warm sunset light"),
    ("雪夜红灯", "snowy street at night, warm shop windows, falling snow"),
    ("森林清晨", "misty forest at dawn, tall trees, soft god rays"),
    ("地铁站台", "empty subway platform, tiled walls, fluorescent lights"),
    ("海边黄昏", "beach at sunset, wet sand reflections, distant waves"),
    ("图书馆", "old library, tall bookshelves, warm lamps, wooden floor"),
    ("雨夜车内", "inside a car at night, rain on window, city bokeh"),
    ("废墟工厂", "abandoned factory, broken windows, dust in light beams"),
]

BASE = {
    "mode": "regional",
    "scene_lora": "anima-base-1-env_lora_a.safetensors",
    "char_lora": "@style_lora_b_anima_ver20.safetensors",
    "ratio": 0.42, "ground_y": 0.90, "x": 0.40,
    "env_weight": 0.70, "char_weight": 0.60, "ll_strength": 1.0, "ll_end": 0.55,
}
CHAR = "1girl, solo, adult woman, white coat, standing"


def post(url, body):
    r = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=60).read())


def coop(body):
    j = post(API + "/api/coop", body)
    t = time.time()
    while time.time() - t < 900:
        s = json.loads(urllib.request.urlopen(API + "/api/coop/status", timeout=30).read())
        if s.get("status") == "done":
            return s.get("image")
        if s.get("status") == "error":
            return None
        time.sleep(3)
    return None


def run_matrix(name, items, seed0):
    os.makedirs(OUT, exist_ok=True)
    results = []
    for i, (label, override) in enumerate(items):
        body = dict(BASE)
        body.update(override)
        body.setdefault("seed", seed0 + i)
        img = coop(body)
        print("%s %s -> %s" % (name, label, img), flush=True)
        results.append({"label": label, "params": override, "image": img})
    json.dump(results, open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return results


def sheet(results, name, cols=4):
    rows = (len(results) + cols - 1) // cols
    w, h = 480, 274
    sh = Image.new("RGB", (cols * w + 20, rows * (h + 34) + 20), (16, 16, 20))
    dr = ImageDraw.Draw(sh)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    for i, r in enumerate(results):
        if not r["image"] or not os.path.exists(r["image"]):
            continue
        rr, cc = divmod(i, cols)
        x, y = 10 + cc * w, 10 + rr * (h + 34)
        im = Image.open(r["image"]).convert("RGB").resize((w - 10, h), Image.LANCZOS)
        sh.paste(im, (x, y))
        dr.text((x, y + h + 6), r["label"], fill=(240, 220, 160), font=font)
    out = os.path.join(OUT, name + ".jpg")
    sh.save(out, quality=88)
    print("sheet:", out, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", default="all", choices=["scenes", "weights", "ratio", "all"])
    a = ap.parse_args()

    if a.matrix in ("scenes", "all"):
        items = [(lab, {"prompt_scene": sc, "prompt_char": CHAR}) for lab, sc in SCENES]
        res = run_matrix("scenes", items, 890001)
        sheet(res, "scenes")

    if a.matrix in ("weights", "all"):
        scene = "rainy neon alley at night, wet pavement, warm shop lights"
        items = []
        for cw in (0.50, 0.60, 0.70):
            for le in (0.45, 0.55, 0.65):
                items.append(("char %.2f / ll_end %.2f" % (cw, le),
                              {"prompt_scene": scene, "prompt_char": CHAR, "char_weight": cw, "ll_end": le}))
        res = run_matrix("weights", items, 891001)
        sheet(res, "weights", cols=3)

    if a.matrix in ("ratio", "all"):
        scene = "rainy neon alley at night, wet pavement, warm shop lights"
        items = [("ratio %.2f" % rt, {"prompt_scene": scene, "prompt_char": CHAR, "ratio": rt})
                 for rt in (0.32, 0.36, 0.40, 0.44, 0.48, 0.52)]
        res = run_matrix("ratio", items, 892001)
        sheet(res, "ratio", cols=3)


if __name__ == "__main__":
    main()
