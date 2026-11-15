# -*- coding: utf-8 -*-
"""分层接力：legacy_xl 草稿/光引导 → 后景 → 人物 → 前景（同一画布逐层 inpaint）。

  # 两步之一：在已有底图上补「人物精修 + 前景互动」
  python tools/coop_layers.py --mode post --base SD-Picture/regional/xxx/comp.png \
      --scene "rainy neon street" --char "1girl, white coat" --fg "rusty railing and weeds"

  # 两步之二：从 legacy_xl 草稿开始完整跑
  python tools/coop_layers.py --mode full --scene "..." --char "..."
"""
import argparse, json, os, subprocess, sys, time
from PIL import Image, ImageDraw, ImageFilter
import numpy as np

ROOT = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "http://127.0.0.1:8770"
from comfy_paths import COMFY_IN as CI
OUT = os.path.join(ROOT, "SD-Picture", "layers")
W, H = 1344, 768
legacy_xl = ""

import urllib.request


def _post(p, o):
    r = urllib.request.Request(API + p, data=json.dumps(o).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=120).read())


def _get(p):
    return json.loads(urllib.request.urlopen(API + p, timeout=60).read())


def wait_job(jid, tag):
    t0 = time.time()
    while time.time() - t0 < 900:
        j = _get("/api/job/" + jid)
        if j.get("status") in ("done", "error"):
            imgs = (j.get("result") or {}).get("images") or []
            if not imgs:
                raise RuntimeError(tag + ": " + str(j.get("result", {}))[:300])
            return imgs[0]
        time.sleep(2)
    raise TimeoutError(tag)


def inpaint(ref_path, mask_name, prompt, negative, denoise, loras, seed, tag):
    body = {"prompt": prompt, "negative": negative, "width": W, "height": H, "steps": 28, "cfg": 5.2,
            "seed": seed, "prefix": "LAY_" + tag, "mode": "inpaint", "reference": os.path.abspath(ref_path),
            "mask": mask_name, "denoise": denoise, "save_to": "station_out",
            "loras": loras}
    r = _post("/api/run", body)
    return wait_job(r["job_id"], tag)


def t2i(prompt, negative, seed, model="", steps=22, cfg=6.0, prefix="LAY_draft"):
    body = {"prompt": prompt, "negative": negative, "width": W, "height": H, "steps": steps,
            "cfg": cfg, "seed": seed, "prefix": prefix, "save_to": "station_out", "mode": "t2i", "loras": []}
    if model:
        body["model"] = model
    r = _post("/api/run", body)
    return wait_job(r["job_id"], prefix)


def save_mask(img, name):
    img.save(os.path.join(CI, name))
    return name


def rect_mask(box, feather=6, invert_box=None):
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    if invert_box:
        d.rectangle((0, 0, W, H), fill=255)
        d.rectangle(box, fill=0)
    else:
        d.rectangle(box, fill=255)
    return m.filter(ImageFilter.GaussianBlur(feather))


def band_mask(top_frac=0.80, cross_box=None, feather=8):
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    d.rectangle((0, int(H * top_frac), W, H), fill=255)
    if cross_box:
        d.rectangle(cross_box, fill=255)
    return m.filter(ImageFilter.GaussianBlur(feather))


def light_guide(src, out_path, blur=18, desat=0.75):
    im = Image.open(src).convert("RGB")
    g = im.filter(ImageFilter.GaussianBlur(blur))
    gray = g.convert("L").convert("RGB")
    g = Image.blend(g, gray, desat)
    g.save(out_path)
    return out_path


def ground_shadow(base_path, out_path, box, strength=150):
    base = Image.open(base_path).convert("RGBA")
    x0, y0, x1, y1 = box
    fh = y1 - y0
    fw = x1 - x0
    cx = (x0 + x1) // 2
    patch = np.asarray(base.crop((max(0, cx - 20), max(0, y1 - 30), min(W, cx + 20), min(H, y1 + 10)))).reshape(-1, 4).mean(0)
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    d.ellipse((cx - fw * 0.55, y1 - fh * 0.02, cx + fw * 0.55, y1 + fh * 0.05),
              fill=(int(patch[0] * 0.35), int(patch[1] * 0.35), int(patch[2] * 0.35), strength))
    sh = sh.filter(ImageFilter.GaussianBlur(max(3, fh // 22)))
    base = Image.alpha_composite(base, sh)
    base.convert("RGB").save(out_path)
    return out_path


def pose_outline(far_path, box, out_path):
    """在底图上画人物轮廓 + 头部椭圆，作为人物 pass 的尺度/姿势先验。"""
    import structure
    man = structure.mannequin((W, H), box, "standing", shade=(150, 150, 155))
    edges = man.split()[3].filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 40 else 0)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    line = Image.new("RGBA", (W, H), (150, 150, 152, 255))
    layer.paste(line, (0, 0), edges)
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = box
    fw = x1 - x0
    fh = y1 - y0
    hb = (x0 + fw * 0.28, y0 + fh * 0.015, x0 + fw * 0.72, y0 + fh * 0.14)
    d.ellipse(hb, outline=(150, 150, 152, 255), width=2)
    d.line((hb[0] + (hb[2] - hb[0]) * 0.5, hb[1] + 4, hb[0] + (hb[2] - hb[0]) * 0.5, hb[3] - 4),
           fill=(150, 150, 152, 255), width=2)
    prior = Image.alpha_composite(Image.open(far_path).convert("RGBA"), layer).convert("RGB")
    prior.save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="post", choices=["post", "full"])
    ap.add_argument("--base", default="")
    ap.add_argument("--scene", required=True)
    ap.add_argument("--char", default="1girl, solo, adult woman, white coat, standing")
    ap.add_argument("--fg", default="rusty railing and overgrown weeds in the foreground")
    ap.add_argument("--env-lora", default="painterly_env.safetensors")
    ap.add_argument("--char-lora", default="soft_style.safetensors")
    ap.add_argument("--ratio", type=float, default=0.36)
    ap.add_argument("--ground-y", type=float, default=0.88)
    ap.add_argument("--x", type=float, default=0.38)
    ap.add_argument("--seed", type=int, default=620001)
    ap.add_argument("--char-denoise", type=float, default=0.82)
    ap.add_argument("--fg-denoise", type=float, default=0.58)
    ap.add_argument("--far-denoise", type=float, default=0.58)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = a.out or os.path.join(OUT, stamp)
    os.makedirs(out, exist_ok=True)

    fh = int(H * a.ratio)
    fw = int(fh * 0.46)
    cx = int(W * a.x)
    feet = int(H * a.ground_y)
    box = (cx - fw // 2, feet - fh, cx + fw // 2, feet)
    fg_cross = (max(0, cx - int(fw * 0.85)), feet - int(fh * 0.12), min(W, cx + int(fw * 0.85)), feet)

    neg = "two people, duplicate, text, watermark, lowres, letterbox, blurry"

    if a.mode == "full":
        print("[1/5] legacy_xl 草稿…", flush=True)
        draft = t2i(a.scene + ", wide shot, cinematic lighting, no people",
                    "people, person, 1girl, 1boy, human, text, watermark", a.seed, model=legacy_xl, steps=20, cfg=6.0)
        draft_path = os.path.join(out, "00_draft.png")
        Image.open(draft).convert("RGB").save(draft_path)
        print("[2/5] 光引导（模糊去色，只做光照参考）…", flush=True)
        guide = light_guide(draft_path, os.path.join(out, "01_light.png"), blur=20, desat=0.7)
        # 后景初值 = 草稿 0.7 + 光引导 0.3：保留构图，吸收光照
        d = Image.open(draft_path).convert("RGB")
        g = Image.open(guide).convert("RGB")
        canvas = os.path.join(out, "02_base.png")
        Image.blend(d, g, 0.3).save(canvas)
    else:
        if not a.base:
            raise SystemExit("post 模式需要 --base")
        canvas = a.base
        draft_path = a.base
        Image.open(canvas).convert("RGB").save(os.path.join(out, "02_base.png"))

    print("[3/5] 后景画家（人区留空）…" if a.mode == "full" else "[1/4] 人物精修…", flush=True)
    if a.mode == "full":
        m = save_mask(rect_mask(box, feather=5, invert_box=box), "lay_far_%s.png" % stamp)
        far = inpaint(os.path.join(out, "02_base.png"), m,
                      a.scene + ", (detailed environment:1.2), (no people:1.25), (painterly:1.1)",
                      neg, a.far_denoise, [{"name": a.env_lora, "weight": 0.75}], a.seed + 1, "far")
        far_path = os.path.join(out, "03_far.png")
        Image.open(far).convert("RGB").save(far_path)
        canvas = far_path
    else:
        far_path = os.path.join(out, "02_base.png")
        canvas = far_path

    print("[4/5] 人物画家（人区重绘）…" if a.mode == "full" else "[2/4] 前景互动…", flush=True)
    if a.mode == "full":
        prior_path = pose_outline(far_path, box, os.path.join(out, "03b_char_prior.png"))
        m = save_mask(rect_mask(box, feather=4), "lay_char_%s.png" % stamp)
        d_char = a.char_denoise or 0.82
        ch = inpaint(prior_path, m,
                     a.char + ", facing the viewer, front view, (detailed face:1.35), looking at viewer, "
                     "full body, standing in the foreground, (lit by the scene light:1.2), (contact shadow:1.1)",
                     neg + ", from behind, back view, faceless, blank face, hood, small figure, distant", d_char,
                     [{"name": a.char_lora, "weight": 0.55}], a.seed + 2, "char")
        ch_path = os.path.join(out, "04_char.png")
        Image.open(ch).convert("RGB").save(ch_path)
        canvas = ch_path
        print("[5/5] 前景收尾（压住人物边缘）…", flush=True)
    else:
        ch_path = canvas

    m = save_mask(band_mask(top_frac=0.88, cross_box=fg_cross), "lay_fg_%s.png" % stamp)
    fg_neg = neg + ", (people:1.5), (person:1.5), 1girl, 1boy, human, character, face"
    fg = inpaint(ch_path, m,
                 a.scene + ", " + a.fg + ", (foreground layer:1.3), (thick vegetation and railing:1.25), (occluding the lower body:1.15), (no people:1.3)",
                 fg_neg, a.fg_denoise, [{"name": a.env_lora, "weight": 0.6}], a.seed + 3, "fg")
    fg_path = os.path.join(out, "05_fg.png")
    Image.open(fg).convert("RGB").save(fg_path)

    comp = ground_shadow(fg_path, os.path.join(out, "comp.png"), box)
    meta = {"mode": a.mode, "scene": a.scene, "char": a.char, "fg": a.fg, "box": list(box),
            "far_denoise": a.far_denoise, "char_denoise": a.char_denoise or 0.78, "fg_denoise": a.fg_denoise,
            "seed": a.seed, "stages": sorted(os.path.basename(x) for x in os.listdir(out))}
    json.dump(meta, open(os.path.join(out, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("done:", out, flush=True)


if __name__ == "__main__":
    main()
