#!/usr/bin/env python3
"""WD14-style tagger (optional module).

    python tools/tag_wd14.py --dir path/to/images --model path/to/wd14.onnx --threshold 0.35
                             [--trigger mychar] [--write] [--extra "1girl, solo"]

Writes a .txt next to every image (or prints a preview with --preview N).
Requires: onnxruntime, pillow, numpy, huggingface_hub (for auto download).
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image


def load_model(model_dir, repo="SmilingWolf/wd-eva02-large-tagger-v3"):
    import onnxruntime as ort
    if not model_dir:
        from huggingface_hub import snapshot_download
        model_dir = snapshot_download(repo)
    onnx = None
    for root, _, files in os.walk(model_dir):
        for f in files:
            if f.endswith(".onnx"):
                onnx = os.path.join(root, f)
                break
        if onnx:
            break
    csv = None
    for root, _, files in os.walk(model_dir):
        for f in files:
            if f == "selected_tags.csv":
                csv = os.path.join(root, f)
    if not onnx or not csv:
        raise SystemExit("model files not found (need *.onnx and selected_tags.csv)")
    sess = ort.InferenceSession(onnx, providers=["CPUExecutionProvider"])
    tags = []
    with open(csv, encoding="utf-8") as f:
        next(f)
        for line in f:
            parts = line.strip().split(",")
            if len(parts) >= 3:
                tags.append((parts[0], parts[2], parts[1]))  # tag_id, name, category
    return sess, tags


def preprocess(path, size):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
    im = im.resize((size, size), Image.BICUBIC)
    arr = np.asarray(im, dtype=np.float32)[:, :, ::-1]  # RGB -> BGR
    return arr[None, ...]


def predict(sess, tags, path, threshold, size):
    inp = sess.get_inputs()[0]
    arr = preprocess(path, size)
    out = sess.run(None, {inp.name: arr})[0][0]
    found = []
    for i, (_, name, cat) in enumerate(tags):
        if i < len(out) and out[i] >= threshold:
            found.append((name, float(out[i]), cat))
    found.sort(key=lambda x: -x[1])
    return [f[0] for f in found], found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--threshold", type=float, default=0.35)
    ap.add_argument("--trigger", default="")
    ap.add_argument("--extra", default="")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--preview", type=int, default=0)
    ap.add_argument("--size", type=int, default=448)
    args = ap.parse_args()

    sess, tags = load_model(args.model)
    exts = (".png", ".jpg", ".jpeg", ".webp")
    files = [f for f in sorted(os.listdir(args.dir)) if f.lower().endswith(exts)]
    if not files:
        raise SystemExit("no images in " + args.dir)
    for i, f in enumerate(files):
        path = os.path.join(args.dir, f)
        names, scored = predict(sess, tags, path, args.threshold, args.size)
        parts = []
        if args.trigger:
            parts.append(args.trigger)
        if args.extra:
            parts.extend([x.strip() for x in args.extra.split(",") if x.strip()])
        parts.extend(names)
        line = ", ".join(dict.fromkeys(parts))
        if args.write:
            with open(os.path.splitext(path)[0] + ".txt", "w", encoding="utf-8") as fp:
                fp.write(line)
        if args.preview and i < args.preview:
            print(f, "->", line[:300])
    print("done:", len(files), "images")


if __name__ == "__main__":
    main()
