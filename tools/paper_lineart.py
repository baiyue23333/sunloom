# -*- coding: utf-8 -*-
"""异型画布：先按区域画线稿，再按区域上色（不做卡片合成、不抠图）。

思路：蒙版是先验，不是事后分割 —— 角色/前景/环境各一块不规则蒙版，
同一块蒙版同时驱动「线稿」和「上色」，几何天然对齐。

流程：
    canvas 白底
      → 线稿：SD15 按 env → char → fg 依次 inpaint（denoise 0.92）
      → 上色：anima 按 env → char → fg 依次 inpaint（denoise 0.80~0.85）
      → 接触阴影直接画在画布上
"""
import argparse
import json
import os
import time
import urllib.request

from PIL import Image, ImageDraw, ImageFilter
import numpy as np

try:
    import paper_conductor
except Exception:  # noqa: BLE001
    paper_conductor = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.environ.get("SUNLOOM_API", "http://127.0.0.1:8770")
from comfy_paths import COMFY_IN as CI
W, H = 1344, 768

LINE_TAIL = ", (black ink lineart:1.4), (monochrome line drawing:1.3), (detailed linework:1.2)"
LINE_NEG = ("(photorealistic:1.2), (color:1.3), (painting:1.2), (gradient:1.1), "
            "text, watermark, lowres, blurry")


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def get(url):
    return json.loads(urllib.request.urlopen(url, timeout=60).read())


def inpaint(img_path, mask_name, prompt, negative, denoise, loras, steps=28, cfg=5.4,
            seed=0, model="", tag="stage"):
    """调站台跑一遍局部重绘，返回结果路径。"""
    body = {"prompt": prompt, "negative": negative, "width": W, "height": H,
            "steps": steps, "cfg": cfg, "seed": seed, "prefix": "LINEART_" + tag,
            "mode": "inpaint", "reference": img_path, "mask": mask_name,
            "denoise": denoise, "loras": loras, "save_to": "paper"}
    if model:
        body["model"] = model
    jid = post(API + "/api/run", body)["job_id"]
    t0 = time.time()
    while time.time() - t0 < 1800:
        time.sleep(2)
        st = get(API + "/api/job/" + jid)
        if st.get("status") in ("done", "error"):
            imgs = (st.get("result") or {}).get("images") or []
            if not imgs:
                raise RuntimeError("%s 失败: %s" % (tag, str(st.get("result"))[:200]))
            return imgs[0]
    raise TimeoutError(tag)


def t2i(prompt, negative, loras, out_dir, seed=0, steps=26, cfg=6.0,
        model="waiNSFWIllustrious_v90.safetensors", tag="env_line"):
    """整幅线稿用 t2i 出（第一遍没有可保留的内容，inpaint 没有意义）。"""
    body = {"prompt": prompt, "negative": negative, "width": W, "height": H,
            "steps": steps, "cfg": cfg, "seed": seed, "prefix": "LINEART_" + tag,
            "mode": "t2i", "save_to": "paper", "loras": loras, "model": model}
    jid = post(API + "/api/run", body)["job_id"]
    t0 = time.time()
    while time.time() - t0 < 900:
        time.sleep(2)
        st = get(API + "/api/job/" + jid)
        if st.get("status") in ("done", "error"):
            imgs = (st.get("result") or {}).get("images") or []
            if not imgs:
                raise RuntimeError("%s 失败: %s" % (tag, str(st.get("result"))[:200]))
            return imgs[0], round(time.time() - t0)
    raise TimeoutError(tag)


TOP_WORDS = ("hanging", "sign", "banner", "lamp", "lantern", "curtain", "flag", "chandelier",
              "signboard", "neon")
SIDE_WORDS = ("door", "frame", "wall", "pillar", "column", "window", "post", "pole")


def fg_kind(prompt):
    """前景按语义决定位置：悬挂→顶部，墙面/门框→侧边，其余→地面。"""
    p = (prompt or "").lower()
    if any(w in p for w in TOP_WORDS):
        return "top"
    if any(w in p for w in SIDE_WORDS):
        return "side"
    return "bottom"


NEG_DROP = ("standing", "upright", "sitting", "leaning", "walking", "hair", "dress",
            "white", "girl", "long")


def clean_neg(neg, positive):
    """去掉与正向提示词冲突的否定词（run: 'standing upright' 把角色生成否掉了）。"""
    pos = set(w.strip().lower() for w in positive.replace("(", " ").replace(")", " ").split(","))
    keep = []
    for part in (neg or "").split(","):
        p = part.strip()
        if not p:
            continue
        low = p.lower()
        if any(w in low for w in NEG_DROP) or any(w in low for w in pos):
            continue
        keep.append(p)
    return ", ".join(keep)


PLACE_WORDS = ("library", "bookstore", "bookshelf", "classroom", "forest", "beach", "spaceship",
               "castle", "desert", "underwater")


def clean_fg(items, scene):
    """前景描述不能和用户给的场景冲突（run2: 便利店线稿被 VL 说成 library 招牌）。"""
    sc = (scene or "").lower()
    out = []
    for it in items or []:
        p = (it.get("prompt") or "").strip()
        if not p:
            continue
        low = p.lower()
        if any(w in low for w in PLACE_WORDS) and not any(w in sc for w in PLACE_WORDS):
            continue
        out.append(it)
    return out


def make_masks(char_box, fg_boxes, feather=10):
    """char=胶囊，fg=椭圆，env=剩余部分。返回 (masks, names)。"""
    m_char = Image.new("L", (W, H), 0)
    x0, y0, x1, y1 = char_box
    r = max(12, int((x1 - x0) * 0.28))
    d = ImageDraw.Draw(m_char)
    d.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=255)
    m_fg = Image.new("L", (W, H), 0)
    for b in fg_boxes:
        ImageDraw.Draw(m_fg).ellipse(b, fill=255)
    m_env = m_char.filter(ImageFilter.MaxFilter(3)).point(lambda v: 255 if v == 0 else 0)
    m_env = Image.fromarray(np.maximum(np.asarray(m_env), 0)).filter(ImageFilter.GaussianBlur(feather))
    m_char = m_char.filter(ImageFilter.GaussianBlur(6))
    names = {}
    for name, im in (("char", m_char), ("fg", m_fg), ("env", m_env)):
        n = "mask_%s_%s.png" % (name, time.strftime("%H%M%S"))
        rgb = Image.merge("RGB", (im, im, im))
        rgb.save(os.path.join(CI, n))
        names[name] = n
    return names


def white_levels(img):
    """线稿底是灰的，上色后灰底残留 = 角色看起来半透明。按分位数自动定白场。"""
    a = np.asarray(img.convert("RGB")).astype(np.float32)
    lum = a.mean(axis=2)
    hi = float(np.percentile(lum, 90))
    lo = float(np.percentile(lum, 3))
    if hi - lo < 12:  # 空白页/纯色：直接给白
        return Image.new("RGB", img.size, (255, 255, 255))
    a = (a - lo) / (hi - lo) * 255.0
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def guide_figure(canvas, box, tone=150):
    """在角色区画一个灰人形，给模型尺寸参照（否则会在蒙版里画个小的）。"""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    im = canvas.copy()
    d = ImageDraw.Draw(im)
    hd = int(w * 0.30)
    d.ellipse((x0 + w // 2 - hd // 2, y0 + int(h * 0.02), x0 + w // 2 + hd // 2,
               y0 + int(h * 0.02) + hd), fill=(tone, tone, tone))
    d.polygon([(x0 + int(w * 0.22), y0 + int(h * 0.10)), (x0 + int(w * 0.78), y0 + int(h * 0.10)),
               (x0 + int(w * 0.66), y0 + int(h * 0.55)), (x0 + int(w * 0.34), y0 + int(h * 0.55))],
              fill=(tone, tone, tone))
    d.polygon([(x0 + int(w * 0.34), y0 + int(h * 0.53)), (x0 + int(w * 0.50), y1),
               (x0 + int(w * 0.62), y1), (x0 + int(w * 0.66), y0 + int(h * 0.53))],
              fill=(tone, tone, tone))
    return im


def harmonize(canvas, char_box, mask_path, weight=0.22):
    """把角色区域的低频色/亮度拉到和底色一致（run2 里角色饱和度 54.5 vs 环境 68.2）。"""
    try:
        import fusion
        card = canvas.crop(char_box).convert("RGBA")
        graded = fusion.lowfreq_match(card, canvas, char_box, weight=weight)
        if isinstance(graded, tuple):
            graded = graded[0]
        m = Image.open(os.path.join(CI, mask_path)).convert("L").crop(char_box)
        m = m.filter(ImageFilter.GaussianBlur(3))
        out = canvas.copy()
        out.paste(graded.convert("RGB"), char_box, m)
        return out, True
    except Exception as e:  # noqa: BLE001
        print("[harmonize] 跳过: %s" % str(e)[:120], flush=True)
        return canvas, False


def run(scene, char, env_artist, char_artist, char_w, env_w, ratio, ground_y, x,
        fg_items, out_dir, seed=1234, draft_denoise=0.92,
        color_env=0.60, color_char=0.85, color_fg=0.75, steps=28, cfg=5.4, enrich=0.30):
    os.makedirs(out_dir, exist_ok=True)
    fh = int(H * ratio)
    fw = int(fh * 0.46)
    cx, feet = int(W * x), int(H * ground_y)
    char_box = (max(0, cx - fw // 2), max(0, feet - fh), min(W, cx + fw // 2), min(H, feet))
    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    canvas_path = os.path.join(out_dir, "canvas_00.png")
    canvas.save(canvas_path)
    log = []

    def step(tag, prompt, neg, dn, loras, model=""):
        nonlocal canvas, canvas_path
        t0 = time.time()
        key = "env" if tag.startswith("env") else ("char" if tag.startswith("char") else "fg")
        res = inpaint(canvas_path, masks[key],
                      prompt, neg, dn, loras, steps=steps, cfg=cfg, seed=seed,
                      model=model, tag=tag)
        canvas = Image.open(res).convert("RGB")
        canvas_path = os.path.join(out_dir, "canvas_%02d_%s.png" % (len(log) + 1, tag))
        canvas.save(canvas_path)
        log.append({"tag": tag, "sec": round(time.time() - t0), "denoise": dn, "out": canvas_path})
        print("[%s] %.0fs ok" % (tag, time.time() - t0), flush=True)
        return canvas

    sd15 = "waiNSFWIllustrious_v90.safetensors"
    # ① 线稿：整幅 t2i，再把角色/前景注入对应区域
    t0 = time.time()
    res, sec0 = t2i(scene + LINE_TAIL, LINE_NEG,
                    [{"name": env_artist, "weight": env_w}], out_dir, seed=seed)
    canvas = white_levels(Image.open(res).convert("RGB"))
    canvas_path = os.path.join(out_dir, "canvas_01_env_line.png")
    canvas.save(canvas_path)
    log.append({"tag": "env_line", "sec": sec0, "denoise": 1.0, "out": canvas_path})
    print("[env_line] %.0fs ok (t2i)" % sec0, flush=True)

    # 7B 读环境线稿，决定角色怎么互动、三块区域各画什么
    plan = {}
    if paper_conductor is not None:
        try:
            plan = paper_conductor.plan(canvas_path, None, scene)
            json.dump(plan, open(os.path.join(out_dir, "plan.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            print("[conductor] by=%s fg=%d inter=%s" % (
                plan.get("by"), len(plan.get("foreground") or []),
                (plan.get("interaction") or "")[:60]), flush=True)
        except Exception as e:  # noqa: BLE001
            print("[conductor] 失败，用命令行参数: %s" % str(e)[:100], flush=True)
            plan = {}
    if not fg_items and plan.get("foreground"):
        fg_items = clean_fg(plan["foreground"], scene)[:2]
        if not fg_items:
            fg_items = [{"prompt": "foreground shelf end and product boxes", "x": 0.78, "scale": 0.3}]
    fg_boxes = []
    for it in (fg_items or [])[:2]:
        s = float(it.get("scale", 0.3))
        bx = int(W * float(it.get("x", 0.5)))
        bw, bh = int(fh * s * 0.9), int(H * s * 0.55)
        kind = fg_kind(it.get("prompt", ""))
        if kind == "top":       # 悬挂物：贴顶
            fg_boxes.append((max(0, bx - bw), 0, min(W, bx + bw), min(H, int(H * 0.02) + bh)))
        elif kind == "side":    # 侧边：竖条
            fg_boxes.append((max(0, bx - bw // 2), int(H * 0.2), min(W, bx + bw // 2), min(H, int(H * 0.55))))
        else:                   # 地面物：贴底
            fg_boxes.append((max(0, bx - bw), max(0, H - bh - int(H * 0.02)),
                             min(W, bx + bw), min(H, H - int(H * 0.01))))
    masks = make_masks(char_box, fg_boxes)
    _extra = ", ".join(x for x in (plan.get("char_extra"), plan.get("interaction")) if x)
    _size = ", (full body:1.35), (single character:1.15), (standing tall:1.2)"
    canvas = guide_figure(canvas, char_box)
    canvas_path = os.path.join(out_dir, "canvas_01b_guide.png")
    canvas.save(canvas_path)
    step("char_line", (char + ", " + _extra if _extra else char) + _size + LINE_TAIL,
         LINE_NEG + (", " + clean_neg(plan["char_neg"], char) if plan.get("char_neg") else ""),
         draft_denoise, [{"name": char_artist, "weight": char_w}], sd15)
    if fg_items:
        step("fg_line", fg_items[0]["prompt"] + LINE_TAIL, LINE_NEG, draft_denoise,
             [{"name": env_artist, "weight": env_w}], sd15)
    # ② 上色
    # 只补充不覆盖：env_extra 只记录在 plan.json，不拼进提示词（run2 实测它会污染场景）
    step("env_color", scene + ", (detailed background:1.15), (cinematic lighting:1.05)",
         "text, watermark, lowres", color_env, [{"name": env_artist, "weight": env_w}])
    step("char_color", (char + ", " + _extra if _extra else char) + _size + ", (same character:1.2), (detailed:1.1)",
         "text, watermark, lowres",
         color_char, [{"name": char_artist, "weight": char_w}])
    if fg_items:
        step("fg_color", fg_items[0]["prompt"] + ", (detailed:1.1)", "text, watermark, lowres",
             color_fg, [{"name": env_artist, "weight": env_w}])
    # 显色：线稿保留优先（denoise 0.65）会偏淡，再补一遍低强度纯显色
    if enrich > 0:
        step("env_vivid", scene + ", (vivid colors:1.25), (saturated:1.15), (anime coloring:1.1)",
             "washout, faded, pale", enrich, [{"name": env_artist, "weight": env_w}])
        step("char_vivid", (char + ", " + _extra if _extra else char) + ", (vivid colors:1.25), (anime coloring:1.1)",
             "washout, faded, pale", enrich, [{"name": char_artist, "weight": char_w}])
    # 融光：把角色的低频色拉回环境
    canvas, ok_h = harmonize(canvas, char_box, masks["char"], weight=0.15)
    print("[harmonize] %s" % ("ok" if ok_h else "skipped"), flush=True)
    canvas_path = os.path.join(out_dir, "canvas_07_harmonized.png")
    canvas.save(canvas_path)
    # ③ 接触阴影
    sh = Image.new("L", (W, H), 0)
    hcx = (char_box[0] + char_box[2]) // 2
    hw = max(10, int((char_box[2] - char_box[0]) * 0.55))
    hh = max(4, int(fh * 0.02))
    ImageDraw.Draw(sh).ellipse((hcx - hw, feet - hh, hcx + hw, feet + hh * 1.6), fill=150)
    sh = sh.filter(ImageFilter.GaussianBlur(max(3, fh // 90)))
    arr = np.asarray(canvas).astype(np.float32)
    arr *= (1 - np.asarray(sh, dtype=np.float32)[..., None] / 255.0 * 0.85)
    final = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    final_path = os.path.join(out_dir, "comp.png")
    final.save(final_path)
    json.dump({"masks": masks, "char_box": char_box, "fg_boxes": fg_boxes, "steps": log},
              open(os.path.join(out_dir, "lineart_plan.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return final_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True)
    ap.add_argument("--char", required=True)
    ap.add_argument("--env-artist", default="style_lora_c  Anima Style LoRA_Bstyle_v1_anima_sun.safetensors")
    ap.add_argument("--char-artist", default="style_lora_a5E585B6E4B889.YDAV.safetensors")
    ap.add_argument("--env-w", type=float, default=0.6)
    ap.add_argument("--char-w", type=float, default=0.65)
    ap.add_argument("--ratio", type=float, default=0.46)
    ap.add_argument("--ground-y", type=float, default=0.9)
    ap.add_argument("--x", type=float, default=0.46)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--fg", default="", help="前景物件描述（逗号分隔可多个）")
    ap.add_argument("--fg-x", type=float, default=0.78)
    ap.add_argument("--fg-scale", type=float, default=0.32)
    ap.add_argument("--color-env", type=float, default=0.60)
    ap.add_argument("--color-char", type=float, default=0.72)
    ap.add_argument("--color-fg", type=float, default=0.72)
    ap.add_argument("--enrich", type=float, default=0.30)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    out = a.out or os.path.join(ROOT, "SD-Picture", "lineart", time.strftime("%Y%m%d_%H%M%S"))
    fg_items = []
    if a.fg.strip():
        for i, part in enumerate([x.strip() for x in a.fg.split(",") if x.strip()][:2]):
            fg_items.append({"prompt": part, "x": min(0.94, a.fg_x + i * 0.12),
                             "scale": a.fg_scale})
    p = run(a.scene, a.char, a.env_artist, a.char_artist, a.char_w, a.env_w,
            a.ratio, a.ground_y, a.x, fg_items, out, seed=a.seed,
            color_env=a.color_env, color_char=a.color_char, color_fg=a.color_fg, enrich=a.enrich)
    print("OK", p)


if __name__ == "__main__":
    main()
