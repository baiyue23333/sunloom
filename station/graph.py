# -*- coding: utf-8 -*-
"""graph.py - workflow-as-data compiler (generic)"""
import json
import os
import time

import comfy

HERE = os.path.dirname(os.path.abspath(__file__))
WF_DIR = os.path.join(HERE, "workflows")

_NODES_CACHE = {"at": 0, "data": {}}
_NUM = {"width": int, "height": int, "seed": int, "steps": int, "cfg": float,
        "denoise": float, "batch_size": int}


def list_workflows():
    if not os.path.isdir(WF_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(WF_DIR) if f.endswith(".json"))


def load(name):
    with open(os.path.join(WF_DIR, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def comfy_nodes(force=False):
    now = time.time()
    if force or now - _NODES_CACHE["at"] > 60 or not _NODES_CACHE["data"]:
        info = comfy.object_info()
        _NODES_CACHE["data"] = {k: True for k in info} if info else {}
        _NODES_CACHE["at"] = now
    return _NODES_CACHE["data"]


def _value(key, params, cfg):
    model = cfg.get("model") or {}
    table = {
        "unet": model.get("unet_name", ""),
        "clip": model.get("clip_name", ""),
        "vae": model.get("vae_name", ""),
        "clip_type": model.get("clip_type", "stable_diffusion"),
    }
    if key in table:
        return table[key]
    val = params.get(key, "")
    caster = _NUM.get(key)
    if caster and str(val) != "":
        try:
            return caster(val)
        except Exception:
            return val
    return val


def _fill(obj, params, cfg):
    if isinstance(obj, str):
        if obj.startswith("{{") and obj.endswith("}}"):
            return _value(obj[2:-2], params, cfg)
        return obj
    if isinstance(obj, list):
        if len(obj) == 2 and isinstance(obj[0], str) and isinstance(obj[1], int):
            return [obj[0], obj[1]]
        return [_fill(v, params, cfg) for v in obj]
    if isinstance(obj, dict):
        return {k: _fill(v, params, cfg) for k, v in obj.items()}
    return obj


def _inject_loras(nodes, loras):
    if not loras:
        return nodes
    unet_id = None
    for nid, node in nodes.items():
        if node.get("class_type") == "UNETLoader":
            unet_id = nid
            break
    if not unet_id:
        return nodes
    prev = unet_id
    idx = 20
    for item in loras:
        name = (item or {}).get("name")
        if not name:
            continue
        nid = str(idx)
        nodes[nid] = {"class_type": "LoraLoaderModelOnly",
                      "inputs": {"model": [prev, 0], "lora_name": name,
                                 "strength_model": float(item.get("weight", 0.8))}}
        prev = nid
        idx += 1
    for nid, node in nodes.items():
        if nid == unet_id or nid.isdigit() and int(nid) >= 20:
            continue
        ins = node.get("inputs") or {}
        if ins.get("model") == [unet_id, 0]:
            ins["model"] = [prev, 0]
    return nodes


def build(name, params):
    wf = load(name)
    cfg = __import__("config").load()
    raw = wf.get("nodes") or {}
    for node in raw.values():
        if "type" in node and "class_type" not in node:
            node["class_type"] = node.pop("type")
    nodes = _fill(raw, params, cfg)
    nodes = _inject_loras(nodes, params.get("loras") or [])
    have = comfy_nodes()
    if not have:
        have = comfy_nodes(force=True)
    missing = [n for n in (wf.get("requires") or []) if n not in have]
    sampler = wf.get("sampler")
    denoise = None
    if sampler:
        n = nodes.get(sampler.get("node"))
        if n:
            denoise = n["inputs"].get("denoise")
    meta = {"workflow": wf.get("id", name), "missing": missing,
            "node_count": len(nodes), "denoise": denoise, "kind": wf.get("kind", "t2i")}
    return nodes, meta


def engine_info():
    st = comfy.system_stats()
    out = {"up": st.get("up"), "version": st.get("version"), "devices": st.get("devices"),
           "url": comfy.COMFY, "workflows": [], "custom_nodes": []}
    if st.get("up"):
        info = comfy.object_info()
        have = set(info) if info else set()
        for name in list_workflows():
            wf = load(name)
            miss = [n for n in (wf.get("requires") or []) if n not in have]
            out["workflows"].append({"name": name, "kind": wf.get("kind", "t2i"),
                                     "missing": miss, "node_count": len(wf.get("nodes") or {})})
        out["custom_nodes"] = [m for m in info.get("_meta", {})] if False else []
    return out
