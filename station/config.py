# -*- coding: utf-8 -*-
"""config.py - reads data/config.json (written by the installer)"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CONFIG = os.path.join(DATA, "config.json")

DEFAULT = {
    "comfy_url": "http://127.0.0.1:8188",
    "model": {"unet_name": "", "clip_name": "", "vae_name": "", "clip_type": "stable_diffusion"},
    "defaults": {"size": "1024x1536", "steps": 28, "cfg": 5.5,
                 "sampler": "euler", "scheduler": "simple", "loras": []},
    "output_dir": "output",
}


def load():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    out = json.loads(json.dumps(DEFAULT))
    for k, v in (cfg or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def save(cfg):
    os.makedirs(DATA, exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
