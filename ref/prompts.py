
# -*- coding: utf-8 -*-
"""prompts.py - 唯一的宏加载/展开实现（expand.py 与工作站共用）。

历史教训：工作站曾自己实现一份 load/expand，结果漏掉了 expand.py 里的
@NEG_GARMENT / @OUTFIT 别名，导致模板里的宏没被展开、提示词里残留 "@NEG_GARMENT"。
以后只改这里。
"""
import json
import os
import re

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
}
STRIP_KEYS = set(STRIP_RULES)


def apply_strips(text, raw="", append_add=True):
    """按 @STRIP_* 去掉对应衣物片段，append_add=True 时在末尾补上替代描述。"""
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
    if append_add:
        for k in hits:
            add = STRIP_RULES[k][1]
            if add and add not in out:
                out = (out + ", " + add) if out else add
    return out, hits


def load_lib():
    with open(LIB, encoding="utf-8") as f:
        return json.load(f)



# 旧积木名 → 新名（2026-11-08 重命名，兼容老配方）
try:
    from gender_alias_new import GENDER_ALIASES
except Exception:
    try:
        from .gender_alias_new import GENDER_ALIASES
    except Exception:
        GENDER_ALIASES = {}

ALIASES = {
    # 2026-11-12：澪专属身份/体型积木改名
    '@ID': '@ID_F',
    '@ID_SOFT': '@ID_F_SOFT',
    '@ID_TIGHT': '@ID_F_TIGHT',
    '@ID_ADULT': '@ID_F_ADULT',
    '@BODY': '@BODY_MIO',
    '@BODY_B': '@BODY_MIO_B',
    '@CUSTOM_DUTCH': '@CAM_DUTCH',
    '@CUSTOM_FRAMEINFRAME': '@COMP_FRAMEINFRAME',
    '@CUSTOM_MULTIEXPO': '@FX_MULTIEXPO',
    '@CUSTOM_ZOOMBLUR': '@CAM_ZOOMBLUR',
    '@CUSTOM_SURREAL': '@STYLE_SURREAL',
    '@CUSTOM_FLOAT': '@POSE_FLOAT',
    '@CUSTOM_GRAPHIC': '@COMP_GRAPHIC',
    '@CUSTOM_ORBIT': '@CAM_ORBIT',
    '@CUSTOM_LIGHTRAY': '@LIGHT_RAY',
    '@CUSTOM_TILTSHIFT': '@COMP_TILTSHIFT',
    '@CUSTOM_SPOTCOLOR': '@FX_SPOTCOLOR',
    '@CUSTOM_REFLECTION': '@FX_REFLECTION',
    '@Customize': '@PROP_KEY',
}
# 性别拆分后：老名指向的新名若又被改名，再补一跳
ALIASES.update(GENDER_ALIASES)
ALIASES = {k: GENDER_ALIASES.get(v, v) for k, v in ALIASES.items()}




def split_clauses(text, parts=2):
    """按逗号把一段提示词拆成若干段，尽量等长。"""
    segs = [x.strip() for x in str(text or "").split(",") if x.strip()]
    if len(segs) <= parts:
        return [", ".join(segs)]
    out, step = [], max(1, len(segs) // parts)
    for i in range(0, len(segs), step):
        out.append(", ".join(segs[i:i + step]))
    return out[:parts] if len(out) >= parts else out


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
    # 长积木拆分版（保持原文不变，另给两块，便于分权重控制）
    try:
        if tokens.get("@OUTFIT"):
            parts = split_clauses(tokens["@OUTFIT"], 2)
            if len(parts) == 2:
                tokens.setdefault("@OUTFIT_A", parts[0])
                tokens.setdefault("@OUTFIT_B", parts[1])
        if tokens.get("@NEG_BASE"):
            parts = split_clauses(tokens["@NEG_BASE"], 2)
            if len(parts) == 2:
                tokens.setdefault("@NEG_BASE_A", parts[0])
                tokens.setdefault("@NEG_BASE_B", parts[1])
    except Exception:
        pass
    return tokens, lib, ch


def _resolve_alias(t):
    return ALIASES.get(t, t)


_ALIAS_PAIRS = sorted(ALIASES.items(), key=lambda kv: -len(kv[0]))


def apply_aliases(text):
    """把旧积木名换成新名。按名字长度倒序 + 词边界，避免 @ID 命中 @ID_SOFT。"""
    text = text or ''
    for old, new in _ALIAS_PAIRS:
        text = re.sub(re.escape(old) + r'(?![A-Za-z0-9_])', new, text)
    return text


def expand(text, tokens):
    out = apply_aliases(text)
    used = []
    for k, v in sorted(tokens.items(), key=lambda kv: -len(kv[0])):
        if k in out and v:
            pat = re.escape(k) + r"(?![A-Za-z0-9_])"
            if re.search(pat, out):
                out = re.sub(pat, lambda _m, _v=v: _v, out)
                used.append(k)
    return out, used


def expand_pair(pos, neg):
    tokens, lib, _ = load_tokens()
    p, pu = expand(apply_aliases(pos), tokens)
    n, nu = expand(neg, tokens)
    return {"positive": p, "negative": n, "used": sorted(set(pu + nu))}


def token_gender(tok, meta=None):
    """判定积木的性别标记（f/m/空串）。meta 可传完整的 lib['meta'] 或直接传 meta['gender']。"""
    gmap = (meta or {}).get("gender") if isinstance((meta or {}).get("gender"), dict) else (meta or {})
    g = gmap.get(tok)
    if g in ("f", "m"):
        return g
    if re.search(r"_M_|_M$", tok):
        return "m"
    if re.search(r"_F_|_F$", tok):
        return "f"
    return ""


def resolve_token(tok):
    """按 ALIASES 迭代解析旧积木名，返回 (新名, 是否发生改名)。"""
    cur, seen = tok, 0
    while cur in ALIASES and seen < 3:
        nxt = ALIASES[cur]
        if nxt == cur:
            break
        cur = nxt
        seen += 1
    return cur, (cur != tok)


def load_full_catalog():
    """加载完整积木目录：prompt_lib + 服装派生 + 角色卡视角块，返回 (tokens, notes, meta, lib, ch)。"""
    tokens, lib, ch = load_tokens()
    notes = dict(lib.get("notes") or {})
    meta = dict(lib.get("meta") or {})
    cards_dir = os.path.join(HERE, "cards")
    try:
        for fn in os.listdir(cards_dir):
            if not fn.endswith(".json"):
                continue
            with open(os.path.join(cards_dir, fn), encoding="utf-8") as f:
                c = json.load(f)
            for k, v in (c.get("views") or {}).items():
                tokens.setdefault(k, v)
    except Exception:
        pass
    return tokens, notes, meta, lib, ch
