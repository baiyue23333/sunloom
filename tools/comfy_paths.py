# -*- coding: utf-8 -*-
"""ComfyUI 目录探测（唯一入口）。

向 http://127.0.0.1:8188/system_stats 询问启动参数里的
--input-directory / --output-directory / --temp-directory，带 TTL 缓存；
ComfyUI 离线时优先回退 A:/Comfy-Desktop/ComfyUI-Shared（或 COMFY_SHARED_DIR），
再回退工作站本地 comfy/ComfyUI。
"""
import json
import os
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMFY_URL = os.environ.get("STATION_COMFY", "http://127.0.0.1:8188").rstrip("/")
_CACHE = {"ts": 0.0, "ok": False, "in": "", "out": "", "temp": ""}


def _default_base():
    for cand in (
        os.environ.get("COMFY_SHARED_DIR", ""),
        r"A:\Comfy-Desktop\ComfyUI-Shared",
        os.path.join(ROOT, "comfy", "ComfyUI"),
    ):
        if cand and os.path.isdir(cand):
            return cand
    return os.path.join(ROOT, "comfy", "ComfyUI")


def detect(force=False):
    now = time.time()
    ttl = 30.0 if _CACHE["ok"] else 5.0
    if not force and _CACHE["in"] and (now - _CACHE["ts"]) < ttl:
        return _CACHE["in"], _CACHE["out"]
    base = _default_base()
    inp = os.path.join(base, "input")
    out = os.path.join(base, "output")
    tmp = os.path.join(base, "temp")
    ok = False
    try:
        with urllib.request.urlopen(COMFY_URL + "/system_stats", timeout=2) as r:
            argv = (json.loads(r.read().decode()).get("system") or {}).get("argv") or []
        for i, a in enumerate(argv):
            if a == "--input-directory" and i + 1 < len(argv):
                inp = argv[i + 1]
            elif a == "--output-directory" and i + 1 < len(argv):
                out = argv[i + 1]
            elif a == "--temp-directory" and i + 1 < len(argv):
                tmp = argv[i + 1]
        ok = True
    except Exception:
        pass
    if tmp == os.path.join(base, "temp") and inp:
        cand_tmp = os.path.join(os.path.dirname(inp), "temp")
        if os.path.isdir(cand_tmp):
            tmp = cand_tmp
    _CACHE.update({"ts": now, "ok": ok, "in": inp, "out": out, "temp": tmp})
    return inp, out


def comfy_in(force=False):
    return detect(force=force)[0]


def comfy_out(force=False):
    return detect(force=force)[1]


def comfy_temp(force=False):
    detect(force=force)
    return _CACHE["temp"]


def comfy_models_dirs():
    inp, _ = detect()
    cands = [
        os.path.join(os.path.dirname(inp), "models"),
        r"A:\Comfy-Desktop\ComfyUI-Shared\models",
        os.path.join(ROOT, "comfy", "ComfyUI", "models"),
        os.path.join(ROOT, "comfy", "models"),
    ]
    seen, out = set(), []
    for p in cands:
        np = os.path.normcase(os.path.abspath(p))
        if np not in seen:
            seen.add(np)
            out.append(p)
    return out


def comfy_custom_nodes_dirs():
    inp, _ = detect()
    cands = [
        os.path.join(os.path.dirname(inp), "custom_nodes"),
        r"A:\Comfy-Desktop\ComfyUI-Shared\custom_nodes",
        os.path.join(ROOT, "comfy", "ComfyUI", "custom_nodes"),
    ]
    seen, out = set(), []
    for p in cands:
        np = os.path.normcase(os.path.abspath(p))
        if np not in seen:
            seen.add(np)
            out.append(p)
    return out


COMFY_IN, COMFY_OUT = detect()
