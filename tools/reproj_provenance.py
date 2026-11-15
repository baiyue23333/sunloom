# -*- coding: utf-8 -*-
"""重映工作台全链路血缘：步骤清单（manifest.json）、PNG 元数据嵌入与配方入库。"""
import json
import os
import time
import urllib.request

from PIL import PngImagePlugin

DEFAULT_STYLE_SUFFIX = ", same lighting and palette"
DEFAULT_FACE_SUFFIX = ", clean eyes, crisp facial linework, same art style"
DEFAULT_HAND_SUFFIX = "five natural fingers, clean hand anatomy, same art style"


def resolve_suffixes(cfg):
    cfg = cfg or {}
    return {
        "style": DEFAULT_STYLE_SUFFIX if cfg.get("style_suffix") is None else str(cfg.get("style_suffix")),
        "face": DEFAULT_FACE_SUFFIX if cfg.get("face_suffix") is None else str(cfg.get("face_suffix")),
        "hand": DEFAULT_HAND_SUFFIX if cfg.get("hand_suffix") is None else str(cfg.get("hand_suffix")),
    }


def append_suffix(base, suffix):
    b = (base or "").strip()
    s = (suffix or "").strip()
    if not s:
        return b
    if not b:
        return s.lstrip(", ").strip()
    if s.startswith(","):
        return b + s
    return b + ", " + s


def new_manifest(cfg, out_dir, plate_prompt, plate_neg, char_neg, plate_loras, char_loras, detail_loras, suffixes):
    return {
        "version": 1,
        "mode": "reproject",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "out_dir": out_dir,
        "manifest_path": os.path.join(out_dir, "manifest.json"),
        "effective_params": dict(cfg or {}),
        "prompts": {
            "plate_positive": plate_prompt,
            "plate_negative": plate_neg,
            "char_negative": char_neg,
        },
        "loras": {
            "plate": plate_loras,
            "char": char_loras,
            "detail": detail_loras,
        },
        "suffixes": suffixes,
        "expand_notes": list((cfg or {}).get("expand_notes") or []),
        "client_meta": (cfg or {}).get("client_meta") or {},
        "mask": {},
        "steps": [],
        "final_image": "",
    }


def record_step(mf, name, **fields):
    entry = {"step": name, "ts": round(time.time(), 3)}
    for k, v in fields.items():
        if v is not None:
            entry[k] = v
    mf.setdefault("steps", []).append(entry)


def write_manifest(mf):
    path = mf.get("manifest_path") or os.path.join(mf.get("out_dir") or ".", "manifest.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(mf, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def save_comp_with_provenance(img, final_path, mf):
    mf["final_image"] = final_path
    mf["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    mpath = write_manifest(mf)
    cfg = mf.get("effective_params") or {}
    prompts = mf.get("prompts") or {}
    compact = {
        "manifest_path": mpath,
        "plate_prompt": prompts.get("plate_positive", ""),
        "plate_neg": prompts.get("plate_negative", ""),
        "effective_params": {k: cfg.get(k) for k in ("width", "height", "steps", "cfg", "seed", "ratio", "ground_y", "x")},
        "loras": {"plate": (mf.get("loras") or {}).get("plate") or []},
    }
    meta = PngImagePlugin.PngInfo()
    meta.add_text("sunloom_mode", "reproject")
    meta.add_text("sunloom_manifest", json.dumps(compact, ensure_ascii=False))
    meta.add_text(
        "parameters",
        "%s\nNegative prompt: %s\nSteps: %s, CFG scale: %s, Seed: %s, Size: %sx%s, Mode: reproject"
        % (prompts.get("plate_positive", ""), prompts.get("plate_negative", ""),
           cfg.get("steps"), cfg.get("cfg"), cfg.get("seed"), cfg.get("width"), cfg.get("height")),
    )
    img.save(final_path, pnginfo=meta)
    return mpath


def register_recipe(api_url, final_path, mf):
    cfg = mf.get("effective_params") or {}
    prompts = mf.get("prompts") or {}
    payload = {
        "path": final_path,
        "data": {
            "ts": time.time(),
            "mode": "reproject",
            "workflow": "coop_reproject",
            "positive": prompts.get("plate_positive", ""),
            "negative": prompts.get("plate_negative", ""),
            "size": [cfg.get("width"), cfg.get("height")],
            "steps": cfg.get("steps"),
            "cfg": cfg.get("cfg"),
            "seed": cfg.get("seed"),
            "denoise": 1.0,
            "loras": (mf.get("loras") or {}).get("plate") or [],
            "manifest_path": mf.get("manifest_path", ""),
            "rewrite_notes": mf.get("expand_notes") or [],
            "client_meta": mf.get("client_meta") or {},
            "exact": True,
        },
    }
    try:
        req = urllib.request.Request(
            api_url.rstrip("/") + "/api/recipe/register",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        print("[provenance] 注册配方失败:", str(e)[:120], flush=True)
