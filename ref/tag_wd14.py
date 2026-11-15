
# -*- coding: utf-8 -*-
"""tag_wd14.py — 本地 WD14 自动打标（ONNX）

用法:
  python ref\tag_wd14.py --dir "comfy/ComfyUI/input/lora_face" --preview 3
  python ref\tag_wd14.py --dir ... --write --trigger my_character --char-threshold 1.1
"""
import argparse
import csv
import os
import sys

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import numpy as np
from PIL import Image

MODEL = "SmilingWolf/wd-eva02-large-tagger-v3"


def load_model(repo):
    from huggingface_hub import hf_hub_download
    import onnxruntime as ort

    onnx_path = hf_hub_download(repo, "model.onnx")
    csv_path = hf_hub_download(repo, "selected_tags.csv")
    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    tags = []
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tags.append((row.get("name", ""), row.get("category", "0")))
    return sess, tags


def preprocess(im, size):
    im = im.convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    im = Image.alpha_composite(bg, im).convert("RGB")
    w, h = im.size
    s = max(w, h)
    canvas = Image.new("RGB", (s, s), (255, 255, 255))
    canvas.paste(im, ((s - w) // 2, (s - h) // 2))
    canvas = canvas.resize((size, size), Image.BICUBIC)
    arr = np.asarray(canvas).astype(np.float32)
    return arr[None, ...]  # NHWC


def predict(sess, tags, im, threshold, char_threshold):
    inp = sess.get_inputs()[0]
    size = int(inp.shape[1]) if isinstance(inp.shape[1], int) else 448
    x = preprocess(im, size)
    name = inp.name
    probs = sess.run(None, {name: x})[0][0]
    out = []
    for i, p in enumerate(probs):
        if i >= len(tags):
            break
        tag, cat = tags[i]
        if not tag or tag.startswith("rating_"):
            continue
        lim = char_threshold if cat == "4" else threshold
        if p >= lim:
            out.append((tag, float(p)))
    out.sort(key=lambda t: -t[1])
    return [t for t, _ in out]


def iter_images(root):
    for dirpath, _, files in os.walk(root):
        for f in sorted(files):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                yield os.path.join(dirpath, f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--threshold", type=float, default=0.35)
    ap.add_argument("--char-threshold", type=float, default=1.1, help="1.1 = 抑制角色标签")
    ap.add_argument("--trigger", default="")
    ap.add_argument("--extra", default="", help="追加固定词，如 '1girl, upper body'")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--preview", type=int, default=0)
    ap.add_argument("--drop", default="bikini,swimsuit,swimwear,_skin,navel,virtual_youtuber,topless,nude",
                    help="误判关键词（子串匹配），逗号分隔")
    ap.add_argument("--keep-mis", action="store_true", help="保留误判标签（默认清掉）")
    ap.add_argument("--drop-appearance", action="store_true",
                    help="角色 LoRA 专用：删掉外观类标签（发/眼/饰/服），让身份并进触发词")
    ap.add_argument("--appearance-words",
                    default="hair,eye,iris,ornament,flower,ahoge,twintails,dress,pantyhose,"
                            "background,general,transparent,skirt,uniform,ribbon",
                    help="外观类关键词（子串匹配）")
    a = ap.parse_args()

    sess, tags = load_model(a.model)
    n = 0
    for p in iter_images(a.dir):
        cap = predict(sess, tags, Image.open(p), a.threshold, a.char_threshold)
        if not a.keep_mis:
            drops = [x.strip().lower() for x in a.drop.split(",") if x.strip()]
            cap = [c for c in cap if not any(d in c.lower() for d in drops)]
        parts = [x for x in (a.trigger.strip(), a.extra.strip()) if x]
        if a.drop_appearance:
            words = [w.strip().lower() for w in a.appearance_words.split(",") if w.strip()]
            cap = [c for c in cap if not any(w in c.lower() for w in words)]
        seen, merged = set(), []
        for tok in [p for part in parts for p in part.split(",")] + cap:
            k = tok.strip().lower()
            if k and k not in seen:
                seen.add(k)
                merged.append(tok.strip())
        text = ", ".join(merged)
        if a.write:
            with open(os.path.splitext(p)[0] + ".txt", "w", encoding="utf-8") as f:
                f.write(text)
        elif n < a.preview:
            print(os.path.basename(p), "->", text[:160])
        n += 1
    print("tagged", n, "images" + (" (written)" if a.write else " (preview only)"))


if __name__ == "__main__":
    main()