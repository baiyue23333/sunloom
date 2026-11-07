
# -*- coding: utf-8 -*-
"""comfy.py - minimal ComfyUI client for the station (anima t2i)"""
import json
import os
import time
import urllib.request
import urllib.error
import urllib.parse
import threading, uuid

try:
    import aiohttp
except Exception:
    aiohttp = None

CLIENT_ID = uuid.uuid4().hex
PROGRESS = {}
_watch_started = False

COMFY = os.environ.get("STATION_COMFY", "http://127.0.0.1:8188")


def _get(path, timeout=15):
    with urllib.request.urlopen(COMFY + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def system_stats():
    try:
        s = _get("/system_stats", 4)
        dev = (s.get("devices") or [{}])[0] if isinstance(s.get("devices"), list) else {}
        return {
            "up": True,
            "version": s.get("system", {}).get("comfyui_version", "?"),
            "vram_total": dev.get("vram_total"),
            "vram_free": dev.get("vram_free"),
            "device": dev.get("name"),
        }
    except Exception:
        return {"up": False, "version": None}


def queue_state():
    try:
        q = _get("/queue", 4)
        return {"running": len(q.get("queue_running", [])), "pending": len(q.get("queue_pending", []))}
    except Exception:
        return {"running": 0, "pending": 0}


def build_wf(prompt, negative, width, height, steps, cfg, seed, loras, prefix,
             sampler="euler", scheduler="simple", unet=None):
    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet or "anima-base-v1.0.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_06b_base.safetensors", "type": "stable_diffusion", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
        "8": {"class_type": "EmptyLatentImage", "inputs": {"width": int(width), "height": int(height), "batch_size": 1}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": prefix}},
    }
    src = ["1", 0]
    for i, spec in enumerate(loras or []):
        nid = str(20 + i)
        wf[nid] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": src, "lora_name": spec["name"], "strength_model": float(spec["weight"])}}
        src = [nid, 0]
    wf["9"] = {"class_type": "KSampler", "inputs": {
        "model": src, "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["8", 0],
        "seed": int(seed), "steps": int(steps), "cfg": float(cfg),
        "sampler_name": sampler, "scheduler": scheduler, "denoise": 1.0}}
    return wf


def submit(wf):
    start_watch()
    req = urllib.request.Request(COMFY + "/prompt", data=json.dumps({"prompt": wf, "client_id": CLIENT_ID}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))["prompt_id"]
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "ignore")
        except Exception:
            pass
        detail = ""
        try:
            d = json.loads(body)
            parts = []
            for node_id, ne in (d.get("node_errors") or {}).items():
                for err in ne.get("errors", []):
                    parts.append("node %s %s: %s" % (node_id, err.get("type"), err.get("details") or err.get("message")))
            detail = "; ".join(parts) or (d.get("error") or {}).get("message", "")
        except Exception:
            detail = body[:300]
        raise RuntimeError("ComfyUI 拒绝提交（%s）：%s" % (e.code, detail[:400]))


def history(pid):
    try:
        h = _get("/history/" + pid, 10)
        return h.get(pid)
    except Exception:
        return None


def view_url(filename, subfolder=""):
    q = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": "output"})
    return COMFY + "/view?" + q


def interrupt():
    try:
        req = urllib.request.Request(COMFY + "/interrupt", data=b"{}",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()
        return True
    except Exception:
        return False


def wait(pid, timeout=900, on_tick=None):
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = history(pid)
        if h:
            status = h.get("status", {})
            if status.get("status_str") == "error":
                msg = ""
                for kind, payload in status.get("messages", []):
                    if kind == "execution_error":
                        msg = payload.get("exception_message", "")[:400]
                return {"ok": False, "error": msg or "execution error"}
            imgs = []
            for node in h.get("outputs", {}).values():
                for im in node.get("images", []):
                    imgs.append(im)
            if imgs:
                return {"ok": True, "images": imgs}
            return {"ok": False, "error": "no images"}
        if on_tick:
            on_tick(time.time() - t0)
        time.sleep(1.5)
    return {"ok": False, "error": "timeout"}


def _watch_loop():
    import asyncio
    async def run():
        url = COMFY.replace("http://", "ws://").replace("https://", "wss://") + "/ws?clientId=" + CLIENT_ID
        async with aiohttp.ClientSession() as sess:
            async with sess.ws_connect(url, heartbeat=30) as ws:
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    try:
                        d = json.loads(msg.data)
                    except Exception:
                        continue
                    t = d.get("type")
                    data = d.get("data") or {}
                    if t == "progress":
                        pid = data.get("prompt_id")
                        if pid:
                            PROGRESS[pid] = (int(data.get("value") or 0), int(data.get("max") or 1))
                    elif t == "executing" and data.get("node") is None and data.get("prompt_id"):
                        PROGRESS.pop(data["prompt_id"], None)
    while True:
        try:
            asyncio.run(run())
        except Exception:
            time.sleep(3)


def start_watch():
    global _watch_started
    if _watch_started or aiohttp is None:
        return
    _watch_started = True
    threading.Thread(target=_watch_loop, daemon=True).start()


def progress_of(pid):
    return PROGRESS.get(pid)
