
# -*- coding: utf-8 -*-
"""prompts.py - 唯一的宏加载/展开实现（expand.py 与工作站共用）。

历史教训：工作站曾自己实现一份 load/expand，结果漏掉了 expand.py 里的
@NEG_GARMENT / @OUTFIT 别名，导致模板里的宏没被展开、提示词里残留 "@NEG_GARMENT"。
以后只改这里。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "prompt_lib.json")
CHAR = os.path.join(HERE, "character.json")


STRIP_RULES = {
    "@STRIP_SHOES": (["shoe", "shoes", "boot", "boots", "loafer", "loafers", "sneaker", "sneakers",
                      "sandal", "sandals", "geta", "heel", "heels", "footwear"], "bare feet, barefoot, visible toes"),
    "@STRIP_SOCKS": (["sock", "socks", "stocking", "stockings", "tights", "pantyhose", "thighhighs"], "bare legs"),
    "@STRIP_GLOVES": (["glove", "gloves", "mittens"], "bare hands"),
    "@STRIP_COAT": (["coat", "jacket", "parka", "overcoat", "cloak", "cape"], ""),
    "@STRIP_HAT": (["hat", "cap", "beret", "hood", "headband"], ""),
    "@STRIP_SUNFLOWER": (["sunflower"], ""),
}
STRIP_KEYS = set(STRIP_RULES)


def apply_strips(text, raw=""):
    """按 @STRIP_* 去掉对应衣物片段，并在末尾补上替代描述。"""
    import re as _re
    hits = [k for k in STRIP_RULES if k in (raw or "")]
    if not hits or not text:
        return text, []
    segs = [x.strip() for x in text.split(",")]
    def hated(seg):
        low = seg.lower()
        for k in hits:
            for word in STRIP_RULES[k][0]:
                if _re.search(r"(?<![a-z])" + _re.escape(word), low):
                    return True
        return False
    kept = [x for x in segs if x and not hated(x)]
    out = ", ".join(kept)
    for k in hits:
        add = STRIP_RULES[k][1]
        if add and add not in out:
            out = (out + ", " + add) if out else add
    return out, hits


def load_lib():
    with open(LIB, encoding="utf-8") as f:
        return json.load(f)


def load_tokens():
    """宏 = prompt_lib.tokens + character.json.garments（含别名）。"""
    lib = load_lib()
    tokens = dict(lib.get("tokens") or {})
    ch = {}
    try:
        with open(CHAR, encoding="utf-8") as f:
            ch = json.load(f)
    except FileNotFoundError:
        pass
    for key, g in (ch.get("garments") or {}).items():
        if g.get("prompt"):
            tokens["@OUT_" + key.upper()] = g["prompt"]
        if g.get("negative"):
            tokens["@NEG_" + key.upper()] = g["negative"]
    for k in STRIP_KEYS:
        tokens.setdefault(k, "\u200b")
    dflt = (ch.get("garments") and ch.get("garment_default")) or "initial"
    if "@OUT_" + dflt.upper() in tokens:
        tokens["@OUTFIT"] = tokens["@OUT_" + dflt.upper()]
        if "@NEG_" + dflt.upper() in tokens:
            tokens["@NEG_GARMENT"] = tokens["@NEG_" + dflt.upper()]
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
    tokens, lib, _ = load_tokens()
    p, pu = expand(pos, tokens)
    n, nu = expand(neg, tokens)
    return {"positive": p, "negative": n, "used": sorted(set(pu + nu))}
