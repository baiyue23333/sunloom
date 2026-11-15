# -*- coding: utf-8 -*-
"""反方向：把一张成品图拆成「人物层 / 前景层 / 背景层」。

用的是 Qwen-Image-Layered（ComfyUI 内置节点），一次采样直接出多层 RGBA。
参数取自本机蓝图 blueprints/Image to Layers(Qwen-Image-Layered).json：
    CLIP qwen_2.5_vl_7b_fp8_scaled(type=qwen_image) + VAE qwen_image_layered_vae
    UNET qwen_image_layered_fp8mixed
    KSampler steps=20 cfg=2.5 euler/simple denoise=1
    LatentCut(dim=t, index=1, amount=16384) → LatentCutToBatch(dim=t, slice_size=1)

用法：
    python tools/layer_split.py --in 成品图.png --out 输出目录 [--layers 3] [--width 1024 --height 768]
"""
import argparse
import json
import os
import shutil
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMFY = os.environ.get("STATION_COMFY", "http://127.0.0.1:8188")
INP = os.path.join(ROOT, "comfy", "ComfyUI", "input")
from comfy_paths import COMFY_OUT as OUT


def _post(path, body):
    req = urllib.request.Request(COMFY + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def _get(path):
    with urllib.request.urlopen(COMFY + path, timeout=60) as r:
        return json.loads(r.read().decode())


def build(in_name, width, height, layers, seed, steps=20, cfg=2.5, prefix="layers"):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "qwen_image_layered_fp8mixed.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_layered_vae.safetensors"}},
        "4": {"class_type": "LoadImage", "inputs": {"image": in_name}},
        "5": {"class_type": "VAEEncode", "inputs": {"pixels": ["4", 0], "vae": ["3", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
        "7": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["6", 0], "latent": ["5", 0]}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
        "9": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["8", 0], "latent": ["5", 0]}},
        "10": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 1.0}},
        "11": {"class_type": "EmptyQwenImageLayeredLatentImage", "inputs": {
            "width": int(width), "height": int(height), "layers": int(layers), "batch_size": 1}},
        "12": {"class_type": "KSampler", "inputs": {
            "model": ["10", 0], "positive": ["7", 0], "negative": ["9", 0], "latent_image": ["11", 0],
            "seed": int(seed), "steps": int(steps), "cfg": float(cfg),
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "13": {"class_type": "LatentCut", "inputs": {
            "samples": ["12", 0], "dim": "t", "index": 1, "amount": 16384}},
        "14": {"class_type": "LatentCutToBatch", "inputs": {
            "samples": ["13", 0], "dim": "t", "slice_size": 1}},
        "15": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["3", 0]}},
        "16": {"class_type": "SaveImage", "inputs": {"images": ["15", 0], "filename_prefix": prefix}},
    }


def run(src, out_dir, layers=3, width=1024, height=768, seed=1234, timeout=3600):
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    name = "layers_in_%s.png" % time.strftime("%H%M%S")
    Image.open(src).convert("RGB").save(os.path.join(INP, name))
    pid = _post("/prompt", {"prompt": build(name, width, height, layers, seed)})["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(4)
        h = _get("/history/" + pid)
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") != "success":
                return {"error": json.dumps(st, ensure_ascii=False)[:400]}
            files = [i["filename"] for node in h[pid]["outputs"].values() for i in node.get("images", [])]
            saved = []
            for i, f in enumerate(files):
                dst = os.path.join(out_dir, "layer_%02d.png" % i)
                shutil.copy2(os.path.join(OUT, f), dst)
                saved.append(dst)
            return {"files": saved, "sec": round(time.time() - t0)}
    return {"error": "timeout"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--layers", type=int, default=3)
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--height", type=int, default=768)
    ap.add_argument("--seed", type=int, default=1234)
    a = ap.parse_args()
    r = run(a.src, a.dst, layers=a.layers, width=a.width, height=a.height, seed=a.seed)
    print(json.dumps(r, ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()
