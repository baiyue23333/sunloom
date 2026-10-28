# -*- coding: utf-8 -*-
"""comfy.py - minimal ComfyUI client"""
import json
import os
import time
import urllib.error
import urllib.request

import config

CFG = config.load()
COMFY = os.environ.get("SUNLOOM_COMFY_URL", CFG.get("comfy_url") or "http://127.0.0.1:8188").rstrip("/")


def _get(path, timeout=15):
    with urllib.request.urlopen(COMFY + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def system_stats():
    try:
        s = _get("/system_stats", 4)
        devs = []
        for d in (s.get("devices") or []):
            devs.append({"name": d.get("name"), "vram_total": d.get("vram_total"),
                         "vram_free": d.get("vram_free")})
        return {"up": True, "version": (s.get("system") or {}).get("comfyui_version", "?"),
                "devices": devs}
    except Exception:
        return {"up": False, "version": None, "devices": []}


def queue_state():
    try:
        q = _get("/queue", 4)
        return {"running": len(q.get("queue_running", [])), "pending": len(q.get("queue_pending", []))}
    except Exception:
        return {"running": 0, "pending": 0}


def object_info():
    try:
        return _get("/object_info", 60)
    except Exception:
        return {}


def submit(wf):
    req = urllib.request.Request(COMFY + "/prompt", data=json.dumps({"prompt": wf}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))["prompt_id"]
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "ignore")
        except Exception:
            pass
        detail = body[:400]
        try:
            d = json.loads(body)
            parts = []
            for nid, ne in (d.get("node_errors") or {}).items():
                for err in ne.get("errors", []):
                    parts.append("node %s %s: %s" % (nid, err.get("type"),
                                                      err.get("details") or err.get("message")))
            detail = "; ".join(parts) or detail
        except Exception:
            pass
        raise RuntimeError("ComfyUI rejected the prompt: " + detail)


def history(pid):
    try:
        h = _get("/history/" + pid, 10)
        return h.get(pid)
    except Exception:
        return None


def interrupt():
    try:
        req = urllib.request.Request(COMFY + "/interrupt", data=b"{}",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass


def free():
    try:
        req = urllib.request.Request(COMFY + "/free",
                                     data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def wait(pid, timeout=1800, on_tick=None):
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = history(pid)
        if h:
            st = h.get("status", {})
            if st.get("status_str") == "error":
                msg = ""
                for kind, payload in st.get("messages", []):
                    if kind == "execution_error":
                        msg = payload.get("exception_message", "")[:400]
                return {"ok": False, "error": msg or "execution error"}
            imgs = []
            for node in (h.get("outputs") or {}).values():
                for im in node.get("images", []):
                    imgs.append(im)
            if imgs:
                return {"ok": True, "images": imgs}
            return {"ok": False, "error": "no images"}
        if on_tick:
            on_tick(time.time() - t0)
        time.sleep(1.5)
    return {"ok": False, "error": "timeout"}
