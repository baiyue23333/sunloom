# -*- coding: utf-8 -*-
"""画家后端：anima（站内 i2i）与 sd15（本地图 + ControlNet）。

统一签名 render(painter=..., prompt=, negative=, lora=, init=, pose=, seed=, denoise=, size=) -> 本地图片路径
"""
import json, os, shutil, time, urllib.request, uuid
from PIL import Image

B = "http://127.0.0.1:8188"
API = "http://127.0.0.1:8770"
ROOT = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from comfy_paths import COMFY_IN as CI
from comfy_paths import COMFY_OUT as OUT
CKPT = "waiNSFWIllustrious_v90.safetensors"
CN = "controlnet-union-sd15.safetensors"


def _post(base, p, o):
    r = urllib.request.Request(base + p, data=json.dumps(o).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=180).read())


def _get(base, p):
    return json.loads(urllib.request.urlopen(base + p, timeout=60).read())


def upload(img, tag):
    os.makedirs(CI, exist_ok=True)
    name = "%s_%s.png" % (tag, time.strftime("%H%M%S"))
    img.save(os.path.join(CI, name))
    return name


def _wait_comfy(pid, timeout=1200):
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = _get(B, "/history/" + pid)
        if pid in h:
            e = h[pid]
            if e.get("status", {}).get("status_str") != "success":
                raise RuntimeError(str(e.get("status", {}).get("messages", []))[-300:])
            f = e["outputs"]["90"]["images"][0]["filename"]
            return os.path.join(OUT, f)
        time.sleep(2)
    raise TimeoutError("comfy timeout")


def render_anima(prompt, negative, lora, init, seed, denoise, size, steps=28, cfg=5.2, mask=None):
    w, h = size
    ref = os.path.abspath(init.path if hasattr(init, "path") else init)
    body = {"prompt": prompt, "negative": negative, "width": w, "height": h, "steps": steps, "cfg": cfg,
            "seed": seed, "prefix": "P_%s" % time.strftime("%H%M%S"), "denoise": denoise,
            "mode": "inpaint" if mask else "i2i", "reference": ref, "mask": mask or "",
            "save_to": "station_out",
            "loras": ([{"name": lora, "weight": 0.85}] if lora else [])}
    r = _post(API, "/api/run", body)
    t0 = time.time()
    while time.time() - t0 < 1200:
        j = _get(API, "/api/job/" + r["job_id"])
        if j.get("status") in ("done", "error"):
            imgs = (j.get("result") or {}).get("images") or []
            if not imgs:
                raise RuntimeError(str(j.get("result", {}))[-300:])
            return imgs[0]
        time.sleep(2)
    raise TimeoutError("anima timeout")


def render_sd15(prompt, negative, lora, init, seed, denoise, size, pose=None, steps=30, cfg=6.2,
                cn_strength=0.8, lora_w=0.85, mask=None):
    w, h = size
    g = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 1]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 1]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["1", 2]}},
        "_out": ["8", 0],
    }
    model = ["1", 0]
    if lora:
        g["2"] = {"class_type": "LoraLoader", "inputs": {"model": ["1", 0], "clip": ["1", 1], "lora_name": lora,
                                                         "strength_model": lora_w, "strength_clip": lora_w}}
        model = ["2", 0]
    pos, neg = ["3", 0], ["4", 0]
    latent = ["5", 0]
    cn_img = None
    if init:
        name = upload(Image.open(init).convert("RGB"), "init")
        g["20"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        g["21"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["20", 0], "vae": ["1", 2]}}
        latent = ["21", 0]
        if mask:
            g["22"] = {"class_type": "LoadImage", "inputs": {"image": mask}}
            g["23"] = {"class_type": "ImageToMask", "inputs": {"image": ["22", 0], "channel": "red"}}
            g["24"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["21", 0], "mask": ["23", 0]}}
            latent = ["24", 0]
    if pose:
        pname = upload(Image.open(pose).convert("RGB"), "pose")
        g["30"] = {"class_type": "LoadImage", "inputs": {"image": pname}}
        g["31"] = {"class_type": "Canny", "inputs": {"image": ["30", 0], "low_threshold": 0.25, "high_threshold": 0.65}}
        g["32"] = {"class_type": "ControlNetLoader", "inputs": {"control_net_name": CN}}
        g["33"] = {"class_type": "SetUnionControlNetType", "inputs": {"control_net": ["32", 0], "type": "canny/lineart/anime_lineart/mlsd"}}
        g["34"] = {"class_type": "ControlNetApplyAdvanced", "inputs": {"positive": pos, "negative": neg,
                                                                       "control_net": ["33", 0], "image": ["31", 0],
                                                                       "strength": cn_strength, "start_percent": 0.0,
                                                                       "end_percent": 0.9, "vae": ["1", 2]}}
        pos, neg = ["34", 0], ["34", 1]
    g["7"] = {"class_type": "KSampler", "inputs": {"model": model, "positive": pos, "negative": neg, "latent_image": latent,
                                                    "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler",
                                                    "scheduler": "normal", "denoise": denoise}}
    g["90"] = {"class_type": "SaveImage", "inputs": {"images": g.pop("_out"), "filename_prefix": "P_%s" % time.strftime("%H%M%S")}}
    pid = _post(B, "/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})["prompt_id"]
    return _wait_comfy(pid)


def render(painter, prompt, negative, lora, init, seed, denoise, size, pose=None, mask=None):
    try:
        import mem_plan
        mem_plan.schedule("sd15" if painter == "sd15" else "anima",
                          unet=CKPT if painter == "sd15" else "",
                          reason="painter:" + str(painter), context="coop")
    except Exception:
        pass
    if painter == "sd15":
        return render_sd15(prompt, negative, lora, init, seed, denoise, size, pose=pose, mask=mask)
    return render_anima(prompt, negative, lora, init, seed, denoise, size, mask=mask)
