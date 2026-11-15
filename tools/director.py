# -*- coding: utf-8 -*-
"""导演 diff：把一句话和当前画布变成新增/移除/参数/模式建议。"""
import re

MODES = ("regional", "paper", "b2", "gen", "sketch", "classic")
RANGES = {"steps": (10, 60), "cfg": (1.0, 10.0), "ratio": (0.30, 0.55),
          "env_w": (0.4, 0.8), "char_w": (0.4, 0.75)}
COOP_KEYS = ("ratio", "env_w", "char_w")
ALIASES = {
    "帽子": "hat", "帽": "hat", "眼镜": "glasses", "伞": "umbrella", "围巾": "scarf",
    "手套": "gloves", "耳环": "earrings", "项链": "necklace", "雨": "rain",
    "霓虹": "neon lights", "夜景": "night", "影子": "shadow", "阴影": "shadow",
}
SCENES = [
    (r"雨夜|夜雨|night rain", ["night", "rain", "neon lights"]),
    (r"夜景|夜晚|night", ["night"]),
    (r"黄昏|日落|golden hour", ["golden hour"]),
    (r"白天|daylight|day", ["day"]),
    (r"教室|classroom", ["classroom", "indoor"]),
    (r"街头|街道|street", ["street"]),
    (r"雪|snow", ["snow", "winter"]),
    (r"室内|indoor", ["indoor"]),
    (r"户外|outdoor", ["outdoor"]),
]
GROUPS = [
    (["day", "daylight", "golden hour", "sunset", "night", "midnight"],
     ["night", "day", "golden hour"]),
    (["rain", "snow", "fog"], ["rain", "snow", "night"]),
    (["indoor", "classroom", "bedroom", "outdoor", "street"], ["indoor", "outdoor", "classroom", "street"]),
]
BASE = [
    (r"黄昏|golden hour|日落", "golden hour"),
    (r"回眸|回头|looking back", "looking back at viewer"),
    (r"低机位|仰拍|from below", "from below"),
    (r"低角度|low angle", "low angle"),
    (r"夜景|night", "night"),
    (r"雨|rain", "rain"),
    (r"霓虹|neon", "neon lights"),
    (r"逆光|backlit", "backlit"),
    (r"浅景深|bokeh", "depth of field"),
    (r"特写|close", "close-up"),
    (r"全身|full body", "full body"),
]


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _items(arr):
    out = []
    for b in arr or []:
        if isinstance(b, dict):
            for k in ("text", "token"):
                v = str(b.get(k) or "").strip()
                if v:
                    out.append(v)
        elif isinstance(b, str):
            if b.strip():
                out.append(b.strip())
    return out


def state_texts(state):
    state = state or {}
    if state.get("coop"):
        lanes = state.get("coop_lanes") or {}
        pos = _items(lanes.get("commonPos")) + _items(lanes.get("envPos")) + _items(lanes.get("chrPos"))
        neg = _items(lanes.get("commonNeg")) + _items(lanes.get("chrNeg"))
    else:
        pos = _items(state.get("positive"))
        neg = _items(state.get("negative"))
    return pos, neg


def summarize(state):
    state = state or {}
    out = {}
    for k in ("coop", "mode", "steps", "cfg", "auto_compose", "ratio", "env_w", "char_w"):
        if k in state:
            out[k] = state[k]
    pos, neg = state_texts(state)
    out["positive"] = pos[:40]
    out["negative"] = neg[:40]
    exp = state.get("expanded") or {}
    if isinstance(exp, dict):
        out["expanded_positive"] = str(exp.get("positive") or "")[:600]
        out["expanded_negative"] = str(exp.get("negative") or "")[:300]
    out["loras"] = [str(x.get("name") or "") for x in (state.get("loras") or []) if isinstance(x, dict)][:8]
    return out


def build_prompt(text, state):
    system = ("你是出图导演。根据用户一句话和当前画布输出 JSON diff，不要解释。字段："
              "positive_add, negative_add（英文标签数组，最多 6 个）；"
              "positive_remove, negative_remove（要删掉的已有标签，最多 6 个）；"
              "params（仅 steps/cfg，合作模式可加 ratio/env_w/char_w）；"
              "mode（仅用户明确说模式时，取 regional/paper/b2/gen/sketch/classic）；notes。"
              "规则：已有标签不要重复；说“换成/改成/不要/去掉”时必须同时 remove 旧项；"
              "自动比例开启时不要给 ratio；非 regional 不要给 env_w/char_w。")
    user = ("示例：画布已有 hat/day，用户“不要帽子，换成雨夜” → "
            "{\"positive_add\":[\"night\",\"rain\",\"neon lights\"],\"positive_remove\":[\"hat\",\"day\"],"
            "\"negative_add\":[],\"negative_remove\":[],\"params\":{}}\n\n"
            "当前画布：" + str(summarize(state))[:2200] + "\n用户：" + str(text or ""))
    return system, user


def _match(tag, pool):
    t = norm(tag)
    if not t:
        return None
    for x in pool:
        n = norm(x)
        if n == t or (len(t) >= 4 and t in n):
            return x
    return None


def finalize(patch, state, by="llm", text=""):
    patch = patch if isinstance(patch, dict) else {}
    pos, neg = state_texts(state)
    notes = []

    def arr(name):
        out = []
        for x in patch.get(name) or []:
            if isinstance(x, dict):
                x = x.get("text") or x.get("tag") or x.get("token") or ""
            x = str(x).strip()
            if x and norm(x) not in [norm(y) for y in out]:
                out.append(x)
        return out[:6]

    adds_p, adds_n = arr("positive_add"), arr("negative_add")
    rem_p, rem_n = arr("positive_remove"), arr("negative_remove")
    skipped = []
    keep_p, keep_n = [], []
    for x in adds_p:
        if _match(x, pos + keep_p):
            skipped.append(x)
        else:
            keep_p.append(x)
    for x in adds_n:
        if _match(x, neg + keep_n):
            skipped.append(x)
        else:
            keep_n.append(x)

    rem_all = [norm(x) for x in rem_p + rem_n]
    keep_p = [x for x in keep_p if norm(x) not in rem_all]
    keep_n = [x for x in keep_n if norm(x) not in rem_all]

    removed_p, missing_p = [], []
    for x in rem_p:
        hit = _match(x, pos)
        if hit and norm(hit) not in [norm(y) for y in removed_p]:
            removed_p.append(hit)
        elif not hit:
            missing_p.append(x)
    removed_n, missing_n = [], []
    for x in rem_n:
        hit = _match(x, neg)
        if hit and norm(hit) not in [norm(y) for y in removed_n]:
            removed_n.append(hit)
        elif not hit:
            missing_n.append(x)

    params = {}
    raw = patch.get("params") if isinstance(patch.get("params"), dict) else {}
    for k, (lo, hi) in RANGES.items():
        if k not in raw:
            continue
        try:
            v = float(raw[k])
        except Exception:
            continue
        if state and not state.get("coop") and k in COOP_KEYS:
            notes.append(k + " 需要合作模式，未应用")
            continue
        if state and k == "ratio" and state.get("auto_compose"):
            notes.append("自动比例开启，ratio 未应用")
            continue
        if state and k in ("env_w", "char_w") and state.get("mode") != "regional":
            notes.append(k + " 仅在 regional 模式生效")
            continue
        params[k] = int(round(v)) if k == "steps" else round(min(hi, max(lo, v)), 2)

    mode = str(patch.get("mode") or "").strip()
    if mode and mode not in MODES:
        notes.append("忽略无效模式：" + mode)
        mode = ""
    if mode and not re.search(r"paper|立体书|regional|单次区域|b2|结构共享|gen|生成式|sketch|草图|classic|经典|合作模式", text or "", re.I):
        mode = ""
    return {"ok": True, "by": by, "positive_add": keep_p, "negative_add": keep_n,
            "positive_remove": removed_p, "negative_remove": removed_n,
            "skipped": skipped, "missing_remove": missing_p + missing_n,
            "params": params, "mode": mode, "notes": notes}


def merge(llm, rule, text):
    """规则命中的场景/删除优先并入模型输出，避免小模型漏改或乱删。"""
    out = dict(llm if isinstance(llm, dict) else {})
    for k in ("positive_add", "negative_add"):
        out[k] = list(out.get(k) or [])
        for x in (rule or {}).get(k) or []:
            if norm(x) not in [norm(y) for y in out[k]]:
                out[k].append(x)
    known = any(re.search(pat, text or "", re.I) for pat, _ in BASE) and len(text or "") <= 50
    if known:
        out["positive_add"] = list((rule or {}).get("positive_add") or [])
    explicit = bool(re.search(r"不要|去掉|删掉|移除|拿掉|别要|换成|改成|变成", text or ""))
    for k in ("positive_remove", "negative_remove"):
        out[k] = list(out.get(k) or []) if explicit else []
        for x in (rule or {}).get(k) or []:
            if norm(x) not in [norm(y) for y in out[k]]:
                out[k].append(x)
    for k in ("params", "mode", "notes"):
        if not out.get(k):
            out[k] = (rule or {}).get(k) or ({} if k == "params" else ("" if k == "mode" else []))
    return out


def rules(text, state=None):
    p = (text or "").lower()
    state = state or {}
    pos, neg = state_texts(state)
    adds_p, adds_n, rem_p, rem_n = [], [], [], []
    notes = []

    # 替换：先按组移除旧标签，再加新场景
    for m in re.finditer(r"(?:换成|改成|变成)([^，。；,;]+)", p):
        phrase = m.group(1)
        new_tags = []
        for pat, tags in SCENES:
            if re.search(pat, phrase, re.I):
                new_tags += tags
        for tag in new_tags:
            if tag not in adds_p:
                adds_p.append(tag)
        for group, _ in GROUPS:
            if any(any(norm(t) in norm(x) for t in group) for x in new_tags):
                for old in pos:
                    if any(norm(g) in norm(old) for g in group) and old not in rem_p:
                        rem_p.append(old)
        if not new_tags:
            notes.append("没认出要换成的场景：" + phrase.strip())

    # 删除：不要/去掉 + 名词
    for m in re.finditer(r"(?:不要|去掉|删掉|移除|拿掉|别要)([^，。；,;]+)", p):
        phrase = m.group(1)
        mapped = None
        for k, v in ALIASES.items():
            if k in phrase:
                mapped = v
                break
        if mapped:
            if mapped not in rem_p:
                rem_p.append(mapped)
        else:
            hit = None
            for x in pos + neg:
                if norm(phrase) and (norm(phrase) in norm(x) or norm(x) in norm(phrase)):
                    hit = x
                    break
            if hit and hit not in rem_p:
                rem_p.append(hit)
            else:
                notes.append("没找到可移除的：" + phrase.strip())

    for pat, tag in BASE:
        if re.search(pat, p, re.I) and tag not in adds_p:
            adds_p.append(tag)
    if re.search(r"特写|close[- ]?up|半身", p):
        pass
    return {"positive_add": adds_p[:6], "negative_add": adds_n[:6],
            "positive_remove": rem_p[:6], "negative_remove": rem_n[:6],
            "params": {}, "notes": notes}
