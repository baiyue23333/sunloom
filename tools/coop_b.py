# -*- coding: utf-8 -*-
"""B2：legacy_xl 草图 → 环境画师（挖空人区）→ 人物画师（剪影）→ 合成。

  python tools/coop_b.py --scene-prompt "..." --ratio 0.34 --ground-y 0.86
"""
import argparse, gc, json, os, sys, time
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mem_plan
import painters
import structure

ROOT = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "SD-Picture", "coop_b")
W, H = 1344, 768
LIGHT_TEXT = {"left": "(lit from the left:1.25)", "right": "(lit from the right:1.25)",
              "back": "(backlit, rim light:1.25)", "top": "(soft top light:1.25)"}


def is_legacy_xl_lora(name):
    n = (name or "").lower()
    return any(k in n for k in ("_il", "xl", "illustrious", "noob"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene-prompt", default="")
    ap.add_argument("--prompt-scene", default="")
    ap.add_argument("--prompt-char", default="")
    ap.add_argument("--scene-lora", default="")
    ap.add_argument("--sketch", default="")
    ap.add_argument("--char-prompt", default="1girl, solo, single character, adult woman, tall slender, full body standing, long coat, (detailed face:1.2), (bright even lighting:1.1)")
    ap.add_argument("--bg-painter", default="anima", choices=["anima", "legacy_xl"])
    ap.add_argument("--char-painter", default="anima", choices=["anima", "legacy_xl"])
    ap.add_argument("--bg-lora", default="")
    ap.add_argument("--char-lora", default="")
    ap.add_argument("--ratio", type=float, default=0.34)
    ap.add_argument("--ground-y", type=float, default=0.86)
    ap.add_argument("--x", type=float, default=0.36)
    ap.add_argument("--pose", default="standing", choices=["standing", "walk"])
    ap.add_argument("--light", default="left")
    ap.add_argument("--seed", type=int, default=530001)
    ap.add_argument("--structure", default="", help="复用已有 structure 目录")
    ap.add_argument("--denoise-bg", type=float, default=0.0)
    ap.add_argument("--denoise-char", type=float, default=0.0)
    ap.add_argument("--harmonize", type=float, default=0.10)
    a = ap.parse_args()

    scene_prompt = a.prompt_scene or a.scene_prompt
    if not scene_prompt:
        raise SystemExit("需要 --scene-prompt 或 --prompt-scene")
    if a.prompt_char:
        a.char_prompt = a.prompt_char

    bg_lora = a.bg_lora or a.scene_lora or ("" if a.bg_painter == "legacy_xl" else "painterly_env.safetensors")
    char_lora = a.char_lora or ("" if a.char_painter == "legacy_xl" else "soft_style.safetensors")
    for name, lora in ((a.bg_painter, bg_lora), (a.char_painter, char_lora)):
        if name == "anima" and is_legacy_xl_lora(lora):
            raise SystemExit("anima 画家不能挂 legacy_xl LoRA：%s" % lora)
        if name == "legacy_xl" and not is_legacy_xl_lora(lora):
            raise SystemExit("legacy_xl 画家需要 legacy_xl LoRA：%s" % lora)

    if a.structure:
        man = json.load(open(os.path.join(a.structure, "manifest.json"), encoding="utf-8"))
        out = a.structure
    else:
        man = structure.build(scene_prompt, "", a.ratio, a.ground_y, a.x, a.seed, a.pose, a.sketch, None, a.light)
        out = man["dir"]
    mp = mem_plan.Plan(context="coop")
    mp.mark("b2_start", "bg=%s char=%s" % (a.bg_painter, a.char_painter))
    bbox = tuple(man["bbox"])
    fh = bbox[3] - bbox[1]

    # ---- 1) 环境画师：从草图重画，人区已挖空 ----
    print("[1/3] 环境画师：%s（草图 → 环境）" % a.bg_painter, flush=True)
    d_bg = a.denoise_bg or (0.82 if a.bg_painter == "legacy_xl" else 0.75)
    bg_prompt = (scene_prompt + ", (detailed environment:1.2), (clean composition:1.05), "
                 + LIGHT_TEXT.get(a.light, LIGHT_TEXT["left"]))
    bg_neg = ("(people:1.4), (person:1.4), (figure:1.4), 1girl, 1boy, human, (camera:1.3), (lens:1.3), "
              "(letterbox:1.4), (black bars:1.4), (frame border:1.3), text, watermark, lowres, blurry")
    bg_path = painters.render(a.bg_painter, bg_prompt, bg_neg, bg_lora, man["sketch_env"], a.seed, d_bg, (W, H))
    bg = Image.open(bg_path).convert("RGB")
    bg.save(os.path.join(out, "bg.png"))
    print("   ", bg_path, flush=True)

    # ---- 2) 人物画师：从草图的人形剪影重画 ----
    print("[2/3] 人物画师：%s（剪影 → 人物）" % a.char_painter, flush=True)
    m = int(fh * 0.22)
    cb = (max(0, bbox[0] - m), max(0, bbox[1] - m), min(W, bbox[2] + m), min(H, bbox[3] + m))
    crop = Image.open(man["sketch_person"]).convert("RGB").crop(cb)
    scale = 960 / crop.height
    crop = crop.resize((int(crop.width * scale) // 8 * 8, 960), Image.LANCZOS)
    crop = crop.filter(ImageFilter.GaussianBlur(1.5))
    crop_path = os.path.join(out, "char_init.png")
    crop.save(crop_path)

    arr = np.asarray(bg.resize((64, 64))).reshape(-1, 3).mean(0)
    temp = "(warm ambient light:1.15)" if arr[0] >= arr[2] else "(cool ambient light:1.15)"
    d_char = a.denoise_char or (0.86 if a.char_painter == "legacy_xl" else 0.80)
    char_prompt = a.char_prompt + ", " + LIGHT_TEXT.get(a.light, LIGHT_TEXT["left"]) + ", " + temp
    ch_path = painters.render(a.char_painter, char_prompt,
                              "child, chibi, doll, big head, silhouette, two people, scenery, text, watermark, cropped",
                              char_lora, crop_path, a.seed + 7, d_char,
                              (crop.width, crop.height),
                              pose=crop_path if a.char_painter == "legacy_xl" else None)
    print("   ", ch_path, flush=True)

    # ---- 3) 合成：不再擦除，人直接盖在挖空处 ----
    print("[3/3] 合成", flush=True)
    mp.free_comfy("b2_rembg", unload_models=False)
    from rembg import remove, new_session
    sess = new_session("u2net")
    alpha = remove(Image.open(ch_path).convert("RGB"), session=sess, alpha_matting=True,
                   alpha_matting_foreground_threshold=240, alpha_matting_background_threshold=10,
                   alpha_matting_erode_size=6)
    del sess
    gc.collect()
    bb = alpha.getbbox() or (0, 0, alpha.width, alpha.height)
    piece = alpha.crop(bb)
    piece = piece.resize((max(1, int(piece.width * fh / piece.height)), fh), Image.LANCZOS)
    x0 = int((bbox[0] + bbox[2]) / 2 - piece.width / 2)
    y0 = bbox[3] - piece.height

    patch = bg.crop((max(0, x0), max(0, y0), min(W, x0 + piece.width), min(H, y0 + piece.height))).resize(piece.size)
    ca = np.asarray(piece.convert("RGB")).astype(np.float32)
    pa = np.asarray(patch).astype(np.float32)
    cm, cs = ca.reshape(-1, 3).mean(0), ca.reshape(-1, 3).std(0) + 1e-6
    pm, ps = pa.reshape(-1, 3).mean(0), pa.reshape(-1, 3).std(0) + 1e-6
    tone = 0.3
    p2 = Image.fromarray(np.clip(ca * (1 - tone) + ((ca - cm) / cs * ps + pm) * tone, 0, 255).astype(np.uint8)).convert("RGBA")
    p2.putalpha(piece.split()[3])

    gc = np.asarray(bg.crop((max(0, x0), max(0, y0), min(W, x0 + piece.width), min(H, y0 + piece.height)))).reshape(-1, 3).mean(0)
    sh = Image.new("RGBA", piece.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse((piece.width * .16, piece.height * .95, piece.width * .84, piece.height * 1.02),
                               fill=(int(gc[0] * .42), int(gc[1] * .42), int(gc[2] * .42), 165))
    sh = sh.filter(ImageFilter.GaussianBlur(max(2, fh // 22)))

    comp = bg.convert("RGBA")
    comp.alpha_composite(sh, (x0, y0))
    comp.alpha_composite(p2, (x0, y0))
    comp = comp.convert("RGB")
    comp.save(os.path.join(out, "comp_raw.png"))

    if a.harmonize > 0:
        print("[3/3] 边缘统一 denoise=%.2f" % a.harmonize, flush=True)
        short_char = (a.char_prompt or "1girl, solo")[:100]
        hp = painters.render("anima",
                             scene_prompt + ", " + short_char + ", (consistent lighting:1.2), (unified color:1.1)",
                             "text, watermark, split screen", "", os.path.join(out, "comp_raw.png"),
                             a.seed + 11, a.harmonize, (W, H))
        comp = Image.open(hp).convert("RGB")
    comp.save(os.path.join(out, "comp.png"))

    meta = dict(man)
    meta.update({"mode": "b2", "bg_painter": a.bg_painter, "char_painter": a.char_painter,
                 "bg_lora": bg_lora, "char_lora": char_lora, "denoise_bg": d_bg, "denoise_char": d_char,
                 "harmonize": a.harmonize, "comp": os.path.join(out, "comp.png")})
    json.dump(meta, open(os.path.join(out, "coop_b.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    mp.trim_py("b2_finish")
    mem_plan.release(context="coop", reason="b2_done")
    mp.save(out)
    print("done:", out, flush=True)


if __name__ == "__main__":
    main()
