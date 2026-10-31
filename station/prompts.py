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
            notes["@OUTFIT"] = "当前默认套装（服装页可切换默认套）"
        negs = [g.get("negative", "") for g in gs.values() if g.get("negative")]
        if negs:
            tokens["@NEG_OUTFIT"] = ", ".join(negs)
            notes["@NEG_OUTFIT"] = "所有服装负向的并集：不确定穿哪套时兜底用"
        # 每套服装同时暴露正向与配套负向，供「加正向自动带配套」使用
        for k2, g2 in gs.items():
            tk = "@OUT_" + str(k2).upper()
            nk = "@NEG_" + str(k2).upper()
            if (g2.get("prompt") or "").strip():
                tokens[tk] = g2["prompt"].strip()
                notes[tk] = (g2.get("label") or k2) + "：" + (g2.get("use_for") or "服装页可编辑")
            if (g2.get("negative") or "").strip():
                tokens[nk] = g2["negative"].strip()
                notes[nk] = (g2.get("label") or k2) + " 的配套负向"
    lib = dict(lib)
    lib["notes"] = notes
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
