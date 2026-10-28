# -*- coding: utf-8 -*-
"""prompts.py - 词库与宏展开（通用版）"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
LIB = os.path.join(DATA, "prompt_lib.json")


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_tokens():
    lib = read_json(LIB, {"tokens": {}, "notes": {}}) or {}
    tokens = dict(lib.get("tokens") or {})
    notes = dict(lib.get("notes") or {})
    ch = read_json(os.path.join(DATA, "character.json"), {}) or {}
    gs = ch.get("garments") or {}
    if gs:
        key = ch.get("garment_default") or list(gs)[0]
        if key in gs:
            tokens["@OUTFIT"] = gs[key].get("prompt", "")
            notes["@OUTFIT"] = "Current outfit prompt (chosen on the Outfit page)"
        negs = [g.get("negative", "") for g in gs.values() if g.get("negative")]
        if negs:
            tokens["@NEG_OUTFIT"] = ", ".join(negs)
            notes["@NEG_OUTFIT"] = "Union of all outfit negatives"
    return tokens, lib, ch


def expand(text, tokens):
    out = text or ""
    used = []
    for k, v in sorted(tokens.items(), key=lambda kv: -len(kv[0])):
        if k in out and v:
            out = out.replace(k, v)
            used.append(k)
    return out, used


def expand_pair(pos, neg):
    tokens, _, _ = load_tokens()
    p, pu = expand(pos, tokens)
    n, nu = expand(neg, tokens)
    return {"positive": p, "negative": n, "used": sorted(set(pu + nu))}
