# -*- coding: utf-8 -*-
"""D 方案：单次采样 + 区域控制（一位画布，两位画师融合）。

  python tools/coop_regional.py --scene "narrow alley, dumpsters, warm door light" --char "1girl, white dress" \
      --ratio 0.34 --ground-y 0.86 --x 0.36 --seed 600101
"""
import argparse, json, os, time, urllib.request, uuid
from PIL import Image, ImageDraw

B = "http://127.0.0.1:8188"
ROOT = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from comfy_paths import COMFY_IN as CI
OUT = os.path.join(ROOT, "SD-Picture", "regional")
W, H = 1344, 768
LLLITE = "anima-lllite-regional-exp-v3.safetensors"
LIGHT_TEXT = {
    "left": "(warm ambient light:1.1)",
    "right": "(warm ambient light:1.1)",
    "back": "(backlit:1.12)",
    "top": "(soft top light:1.08)",
}


def post(p, o):
    r = urllib.request.Request(B + p, data=json.dumps(o).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=120).read())


def get(p):
    return json.loads(urllib.request.urlopen(B + p, timeout=60).read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True)
    ap.add_argument("--char", default="1girl, solo, adult woman, white dress")
    ap.add_argument("--negative", default="multiple people, two girls, crowd, extra person, from behind, back view, "
                                         "duplicate, text, watermark, lowres, letterbox, black bars, border, blurry, "
                                         "lamp post, sun, halo, ring light, poster, portrait in window, giant face, billboard, "
                                         "overexposed, blown highlights, pure white sky, white window, two heads, twins, conjoined")
    ap.add_argument("--env-lora", default="anima-base-1-env_lora_a.safetensors")
    ap.add_argument("--env-w", type=float, default=0.7)
    ap.add_argument("--char-lora", default="@style_lora_b_anima_ver20.safetensors")
    ap.add_argument("--char-w", type=float, default=0.5)
    ap.add_argument("--ratio", type=float, default=0.34)
    ap.add_argument("--ground-y", type=float, default=0.86)
    ap.add_argument("--x", type=float, default=0.36)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--cfg", type=float, default=5.5)
    ap.add_argument("--seed", type=int, default=600001)
    ap.add_argument("--ll-strength", type=float, default=1.0)
    ap.add_argument("--ll-end", type=float, default=0.55)
    ap.add_argument("--light", default="left")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = a.out or os.path.join(OUT, stamp)
    os.makedirs(out, exist_ok=True)

    fh = int(H * a.ratio)
    fw = int(fh * 0.52)
    cx = int(W * a.x)
    feet = int(H * a.ground_y)
    top = max(0, feet - int(fh * 1.02))
    box = (max(0, cx - fw // 2), top, min(W, cx + fw // 2), feet)
    mask = Image.new("RGB", (W, H), (255, 255, 255))
    ImageDraw.Draw(mask).rectangle(box, fill=(220, 30, 30))
    mask_name = "region_%s.png" % stamp
    mask.save(os.path.join(CI, mask_name))
    mask.save(os.path.join(out, "region_mask.png"))

    side = "left" if a.x < 0.5 else "right"
    tags = ["(facing the viewer:1.15)", "(full body:1.1)", "(single figure:1.1)"]
    if a.ratio < 0.4:
        tags.append("(tall figure:1.1)")
    light = LIGHT_TEXT.get(a.light, "") if a.light == "back" else ""
    prompt = ("%s, %s, standing on the %s side of the frame, %s, %s, "
              "(painterly brushwork:1.12), (detailed background:1.12), (cinematic lighting:1.05)"
              % (a.char, ", ".join(tags), side, a.scene, light)).replace(", , ", ", ")

    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "anima-base-v1.0.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_06b_base.safetensors", "type": "stable_diffusion", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "4": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": a.env_lora, "strength_model": a.env_w}},
        "5": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["4", 0], "lora_name": a.char_lora, "strength_model": a.char_w}},
        "6": {"class_type": "ModelPatchLoader", "inputs": {"name": LLLITE}},
        "7": {"class_type": "LoadImage", "inputs": {"image": mask_name}},
        "8": {"class_type": "AnimaLLLiteApply", "inputs": {"model": ["5", 0], "model_patch": ["6", 0], "image": ["7", 0],
                                                          "strength": a.ll_strength, "start_percent": 0.0, "end_percent": a.ll_end}},
        "9": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "10": {"class_type": "CLIPTextEncode", "inputs": {"text": a.negative, "clip": ["2", 0]}},
        "11": {"class_type": "EmptyLatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}},
        "12": {"class_type": "KSampler", "inputs": {"model": ["8", 0], "positive": ["9", 0], "negative": ["10", 0],
                                                    "latent_image": ["11", 0], "seed": a.seed, "steps": a.steps,
                                                    "cfg": a.cfg, "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0}},
        "13": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["3", 0]}},
        "14": {"class_type": "SaveImage", "inputs": {"images": ["13", 0], "filename_prefix": "REG_%s" % stamp}},
    }
    print("[1/3] 提交采样（单次区域）…", flush=True)
    import mem_plan
    mp = mem_plan.Plan(context="coop")
    mp.schedule("anima", note="regional_sample")
    pid = post("/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})["prompt_id"]
    print("[2/3] 采样中…", flush=True)
    t0 = time.time()
    while time.time() - t0 < 900:
        h = get("/history/" + pid)
        if pid in h:
            e = h[pid]
            if e.get("status", {}).get("status_str") != "success":
                raise RuntimeError(str(e.get("status", {}).get("messages", []))[-300:])
            f = e["outputs"]["14"]["images"][0]["filename"]
            from comfy_paths import COMFY_OUT
            src = os.path.join(COMFY_OUT, f)
            print("[3/3] 保存…", flush=True)
            dst = os.path.join(out, "comp.png")
            Image.open(src).save(dst)
            json.dump({"prompt": prompt, "negative": a.negative, "box": list(box), "ratio": a.ratio,
                       "ground_y": a.ground_y, "x": a.x, "env_lora": a.env_lora, "env_w": a.env_w,
                       "char_lora": a.char_lora, "char_w": a.char_w, "ll_end": a.ll_end, "seed": a.seed,
                       "comp": dst}, open(os.path.join(out, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            mp.trim_py("regional_done")
            mp.save(out)
            print("done:", out, flush=True)
            return
        time.sleep(3)
    raise TimeoutError("regional")


if __name__ == "__main__":
    main()
