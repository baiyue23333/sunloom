
# -*- coding: utf-8 -*-
"""graph.py - 把 workflow JSON 编译成 ComfyUI 图，并检查节点可用性。"""
import copy
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WFDIR = os.path.join(HERE, "workflows")
COMFY = os.environ.get("STATION_COMFY", "http://127.0.0.1:8188")

_CACHE = {"nodes": None, "ts": 0}


def _get(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def comfy_nodes(force=False):
    """返回 ComfyUI 已安装节点类集合（缓存 120 秒）。"""
    now = time.time()
    if force or not _CACHE["nodes"] or now - _CACHE["ts"] > (120 if _CACHE["nodes"] else 20):
        try:
            info = _get(COMFY + "/object_info", 20)
            _CACHE["nodes"] = set(info.keys())
            _CACHE["ts"] = now
        except Exception:
            _CACHE["nodes"] = set()
            _CACHE["ts"] = now
    return _CACHE["nodes"]


def load(name):
    with open(os.path.join(WFDIR, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def list_workflows():
    return sorted(x[:-5] for x in os.listdir(WFDIR) if x.endswith(".json"))


def missing_nodes(wf):
    have = comfy_nodes()
    return [n for n in wf.get("requires", []) if n not in have]


def _fill(val, params):
    if isinstance(val, str):
        if val.startswith("{{") and val.endswith("}}"):
            key = val[2:-2]
            return params.get(key, val)
        out = val
        for k, v in params.items():
            out = out.replace("{{" + k + "}}", str(v))
        return out
    if isinstance(val, list):
        return [_fill(v, params) for v in val]
    if isinstance(val, dict):
        return {k: _fill(v, params) for k, v in val.items()}
    return val


def build(name, params):
    """编译图；返回 (graph, meta)。meta 里记录缺节点与实际 denoise。"""
    wf = load(name)
    if not comfy_nodes():
        comfy_nodes(force=True)   # 冷启动时缓存为空，强制刷一次
    missing = missing_nodes(wf)
    nodes = copy.deepcopy(wf["nodes"])
    nodes = {k: {"class_type": v["type"], "inputs": _fill(v["inputs"], params)} for k, v in nodes.items()}

    sp = wf.get("sampler")
    if not sp:
        return nodes, {"workflow": wf["id"], "missing": missing, "denoise": None, "node_count": len(nodes)}
    sid = sp["node"]
    nodes[sid] = {"class_type": "KSampler", "inputs": {
        "model": list(sp["model_from"]),
        "positive": ["6", 0], "negative": ["7", 0],
        "latent_image": list(sp["latent_from"]),
        "seed": int(params.get("seed", 0)),
        "steps": int(params.get("steps", 30)),
        "cfg": float(params.get("cfg", 5.5)),
        "sampler_name": params.get("sampler", "euler"),
        "scheduler": params.get("scheduler", "simple"),
        "denoise": float(params.get("denoise", 1.0)) if wf.get("has_denoise") else 1.0,
    }}

    loras = [x for x in (params.get("loras") or []) if x.get("name")]
    if loras:
        src = list(sp["model_from"])
        for i, spec in enumerate(loras):
            nid = str(20 + i)
            nodes[nid] = {"class_type": "LoraLoaderModelOnly", "inputs": {
                "model": src, "lora_name": spec["name"], "strength_model": float(spec.get("weight", 0.5))}}
            src = [nid, 0]
        nodes[sid]["inputs"]["model"] = src

    meta = {"workflow": wf["id"], "missing": missing, "denoise": nodes[sid]["inputs"]["denoise"],
            "node_count": len(nodes)}
    return nodes, meta


def submit(graph, pid=None):
    body = {"prompt": graph}
    if pid:
        body["client_id"] = pid
    req = urllib.request.Request(COMFY + "/prompt", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))["prompt_id"]


def engine_info():
    """版本、节点可用性、自定义节点目录、队列。"""
    st, stats_err = None, None
    try:
        st = _get(COMFY + "/system_stats", 8)
    except Exception as e:
        stats_err = str(e)
    out = {"comfy": COMFY, "up": st is not None, "error": stats_err, "system": (st or {}).get("system", {})}
    if st:
        sysd = st.get("system", {})
        out["version"] = sysd.get("comfyui_version")
        out["frontend"] = sysd.get("required_frontend_version")
        out["packages"] = sysd.get("comfy_package_versions", [])[:8]
        out["devices"] = [{"name": d.get("name"), "vram_total": d.get("vram_total"),
                           "vram_free": d.get("vram_free")} for d in st.get("devices", [])]
    wfs = []
    have = comfy_nodes(force=bool(st))
    for name in list_workflows():
        wf = load(name)
        wfs.append({"name": name, "id": wf.get("id"), "requires": wf.get("requires", []),
                    "missing": [n for n in wf.get("requires", []) if n not in have]})
    out["workflows"] = wfs
    try:
        out["custom_nodes"] = sorted(os.listdir(os.path.join(os.path.dirname(HERE), "comfy", "ComfyUI", "custom_nodes")))
    except Exception:
        out["custom_nodes"] = []
    return out