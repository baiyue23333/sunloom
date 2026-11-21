# -*- coding: utf-8 -*-
"""合作重映 L2：提示词分阶段瘦身（纯文本，不认 @宏）。

上游把积木展开成英文提示词后，这里只保留该阶段用得上的词：
  01_plate  场景全量 + 人物轮廓摘要（发色 / 服装主色 / 动作 / 景别）
  02_body   人物全文（场景词由前端泳道分流挡掉）
  03_face   @ID 的脸/眼/发饰 + @MOOD + @GAZE（face 后缀由 reproj_provenance 追加）
负向：出板不带手部词；人物与修脸不带家具/穿模词。

输入都是 expand_blocks() 展开后的英文串。未展开的画师触发词（如 @style_lora_b）
原样保留，避免瘦身把 LoRA 触发词一起吃掉。
"""
import re

# 服装词后仍然属于「主色 + 主件」的描述词，用来向前找颜色
_GARMENT_MODIFIERS = {
    "long", "short", "thin", "wide", "loose", "fitted", "oversized", "knit", "knitted",
    "wool", "woolen", "tailored", "pleated", "flared", "layered", "ribbed", "striped",
    "satin", "silk", "silken", "cotton", "linen", "leather", "denim", "velvet", "fur",
    "sheer", "high", "low", "knee", "ankle", "midi", "maxi", "thigh", "chiffon", "lace",
    "sailor", "detached", "sleeved", "sleeveless", "open", "cropped", "padded",
    "three-piece", "two-piece", "straight-leg",
    # 发型词：让 "black undercut hair" 这类也能向前找到颜色
    "undercut", "bob", "bun", "ponytail", "twintail", "twintails", "pigtail", "pigtails",
    "braid", "braids", "curly", "wavy", "messy", "bangs", "fringe", "tied", "slicked",
    "shaved", "crew", "pompadour", "mullet", "hime",
}

_COLOR_RE = re.compile(
    r"\b(?:ivory|white|snow|silver|grey|gray|ash|blonde|blond|golden|yellow|brown|"
    r"chestnut|auburn|red|pink|blue|green|purple|violet|black|platinum|raven|navy|"
    r"cream|camel|charcoal|beige|tan|khaki|maroon|teal|orange|lilac|mint|peach|coral|"
    r"lavender|dark|deep|pale|light|bright|soft)\b",
    re.I,
)
_HAIR_WORD_RE = re.compile(r"\bhair\b", re.I)
_ORNAMENT_RE = re.compile(
    r"\b(?:hair\s*ornament|hairpin|barrette|hair\s*clip|hair\s*ribbon|hairbow|"
    r"hair\s*bow|hairband|hair\s*band|hair\s*tie|flower\s*crown|headpiece)\b",
    re.I,
)

_GARMENT_WORDS = (
    "sailor blouse", "sailor uniform", "school uniform", "evening gown", "slip dress",
    "dress shirt", "pencil skirt", "trench coat", "overcoat", "sundress", "blazer", "cardigan", "sweater", "hoodie",
    "turtleneck", "camisole", "blouse", "shirt", "t-shirt", "bodice", "dress", "gown",
    "kimono", "yukata", "hanfu", "cheongsam", "qipao", "leotard", "swimsuit", "bikini",
    "jumpsuit", "romper", "skirt", "trousers", "pants", "jeans", "shorts", "overalls",
    "coat", "jacket", "vest", "suit", "uniform", "robe", "cape", "cloak", "apron",
    "socks", "stockings", "tights", "boots", "loafers", "sneakers", "sandals", "geta",
    "shoes", "heels", "pumps", "mittens", "gloves", "scarf", "top",
)
_GARMENT_RE = re.compile(
    r"\b(%s)\b" % "|".join(sorted((re.escape(g) for g in _GARMENT_WORDS), key=len, reverse=True)),
    re.I,
)

_POSE_RE = re.compile(
    r"\b(?:standing|sitting|seated|walking|running|leaning|kneeling|crouching|squatting|"
    r"lying|reclining|turning|looking back|glancing back|reaching|stretching|jumping|"
    r"floating|holding|carrying|raising|lifting|waving|pointing|resting|hugging|"
    r"arms? (?:crossed|akimbo|raised|outstretched)|hands? (?:behind|on|in))\b",
    re.I,
)
_SHOT_RE = re.compile(
    r"\b(?:full[- ]body|medium shot|long shot|wide shot|very wide shot|close[- ]?up|"
    r"upper body|bust shot|cowboy shot|three[- ]quarter|knee[- ]up|head[- ]and[- ]shoulders|"
    r"establishing shot|from behind|from above|from below|profile view|portrait)\b",
    re.I,
)
_COUNT_RE = re.compile(
    r"^(?:1girl|1boy|2girls|2boys|3girls|multiple girls|multiple boys|solo|female|male)$",
    re.I,
)
_PERSON_M_RE = re.compile(r"\b(?:he|him|his|boy|man|male|gentleman)\b", re.I)
_PERSON_F_RE = re.compile(r"\b(?:she|her|hers|girl|woman|female|lady)\b", re.I)

_FACE_WORD_RE = re.compile(
    r"\b(?:face|facial|eyes?|eyelash(?:es)?|eyelid|iris(?:es)?|pupils?|two-tone eyes|"
    r"eyebrows?|brow|lips?|mouth|nose|cheeks?|cheekbones?|blush|skin|complexion|jawline|scar|expression|smile|smirk|"
    r"frown|gaze|looking|staring|stare|glance|ornament|hairpin|barrette|hair\s*clip|"
    r"headpiece|flower\s*crown|makeup|eyeshadow|eyeliner|mascara)(?![-a-z])",
    re.I,
)
_BODY_WORD_RE = re.compile(
    r"\b(?:breasts?|waist|hips?|thighs?|legs?|arms?|shoulders?|collarbone|torso|body|"
    r"feet|foot|toes|hands?|fingers?|navel|belly)\b",
    re.I,
)

# 出板阶段去掉的手部负向（小人物只有轮廓，手部词只会干扰场景）
_HAND_TERMS = (
    "extra fingers", "fused fingers", "missing fingers", "deformed hand", "deformed hands",
    "bad hand anatomy", "bad hand", "bad hands", "bad hand pose", "floating fingers",
    "poorly drawn hands", "mutated hands", "six fingers", "hand proportions",
    "delicate hands", "slender fingers", "small hands", "disembodied hand", "third hand",
    "floating hand", "extra hands", "fused hand",
)
# 人物/修脸阶段去掉的家具与穿模负向（局部重绘画不出家具，压着反而伤背景）
_SCENE_TERMS = (
    "clipping into each other", "embedded in the wall", "passing through the shelf",
    "sunk into the floor", "overlapping geometry", "parts merging",
    "floating disconnected props", "hovering furniture", "pasted sticker cutout edges",
    "unattached shadows", "desk clutter", "pen holder", "table setting", "bed lamp",
    "lamp base", "clutter on the bed", "pillow stack", "blanket pile", "cutlery",
    "laptop", "papers", "phone", "plate", "bowl",
)


def _terms_re(terms):
    parts = [r"\s+".join(re.escape(w) for w in t.split()) for t in terms]
    return re.compile(r"(?<![a-z])(?:%s)(?![a-z])" % "|".join(parts), re.I)


_HAND_RE = _terms_re(_HAND_TERMS)
_SCENE_RE = _terms_re(_SCENE_TERMS)


def split_clauses(text):
    """按顶层逗号切分；括号权重组 (xxx:1.2) 整体保留。"""
    out, buf, depth = [], [], 0
    for ch in text or "":
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [s.strip() for s in out if s.strip()]


def merge_neg(*parts):
    """合并多段提示词：按顶层逗号切分、大小写归一后去重，保留首次顺序。"""
    seen, out = set(), []
    for part in parts:
        for seg in split_clauses(part):
            key = seg.lower()
            if key not in seen:
                seen.add(key)
                out.append(seg)
    return ", ".join(out)


dedup_join = merge_neg


def _colors_before(text, end):
    """从 end 往前找紧邻的颜色词；越过服装/发型描述词，遇到其它词就停。"""
    words = list(re.finditer(r"[a-z][a-z'-]*", (text or "")[:end], re.I))
    colors = []
    for m in reversed(words):
        w = m.group(0).lower()
        if _COLOR_RE.fullmatch(w):
            colors.append(w)
        elif w in _GARMENT_MODIFIERS:
            continue
        else:
            break
    return " ".join(reversed(colors))


def _garment_hint(low):
    m = _GARMENT_RE.search(low)
    if not m:
        return ""
    colors = _colors_before(low, m.start())
    return (colors + " " + m.group(1)) if colors else ""


def _garment_phrase(low, m):
    """没有颜色时的主件兜底：服装词 + 紧邻最多两个描述词（long wool coat）。"""
    mods = []
    for w in reversed(list(re.finditer(r"[a-z][a-z'-]*", low[:m.start()]))):
        if w.group(0).lower() in _GARMENT_MODIFIERS and len(mods) < 2:
            mods.append(w.group(0).lower())
        else:
            break
    return " ".join(list(reversed(mods)) + [m.group(1)])


def contour_summary(text):
    """出板用人物轮廓：人数 + 发色 + 服装主色/主件 + 动作 + 景别。"""
    if not (text or "").strip():
        return ""
    picks = {"count": [], "hair": [], "garment": [], "pose": [], "shot": [], "macro": []}
    segs = split_clauses(text)
    if not any(_COUNT_RE.match(seg) for seg in segs):
        # 身份块本身不一定带 1girl/1boy；出板必须明确画一个人，否则可能只剩一个空场景
        male = _PERSON_M_RE.search(text or "")
        female = _PERSON_F_RE.search(text or "")
        if male and not female:
            picks["count"].append("1boy")
        elif female and not male:
            picks["count"].append("1girl")
        else:
            picks["count"].append("solo")
    for seg in segs:
        if seg.startswith("@"):
            picks["macro"].append(seg)
            continue
        low = seg.lower()
        if _COUNT_RE.match(seg):
            picks["count"].append(seg)
            continue
        hair = _HAIR_WORD_RE.search(low)
        if hair and not _ORNAMENT_RE.search(low):
            colors = _colors_before(low, hair.start())
            if colors:
                picks["hair"].append(colors + " hair")
        hint = _garment_hint(low)
        if not hint and not picks["garment"]:
            gm = _GARMENT_RE.search(low)
            hint = _garment_phrase(low, gm) if gm else ""
        if hint:
            picks["garment"].append(hint)
        if _POSE_RE.search(low):
            picks["pose"].append(seg)
        if _SHOT_RE.search(low):
            picks["shot"].append(seg)
    out, seen = [], set()
    for key, cap in (("count", 2), ("hair", 1), ("garment", 3), ("pose", 2), ("shot", 2), ("macro", 3)):
        for item in picks[key][:cap]:
            k = item.lower()
            if k not in seen:
                seen.add(k)
                out.append(item)
    return ", ".join(out)


def face_summary(text):
    """修脸用摘要：只留脸/眼/睫毛/皮肤/发饰/表情/视线，不带服装与体型。"""
    out, seen = [], set()
    for seg in split_clauses(text):
        low = seg.lower()
        keep = seg.startswith("@") or (_FACE_WORD_RE.search(low) and not _BODY_WORD_RE.search(low))
        if not keep or low in seen:
            continue
        seen.add(low)
        out.append(seg)
        if len(out) >= 12:
            break
    return ", ".join(out)


def _drop_clauses(text, pattern):
    return ", ".join(seg for seg in split_clauses(text) if not pattern.search(seg))


def drop_hand_negatives(text):
    """出板负向：去掉手部词。"""
    return _drop_clauses(text, _HAND_RE)


def drop_scene_structure_negatives(text):
    """人物/修脸负向：去掉家具、桌面/床边杂物与穿模词。"""
    return _drop_clauses(text, _SCENE_RE)
