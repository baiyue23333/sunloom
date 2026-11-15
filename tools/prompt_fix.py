# -*- coding: utf-8 -*-
"""一键修正：纯规则的积木组合审校（不依赖任何语言模型）。

输入/输出与前端对齐：
  audit(blocks, negatives) -> {"issues": [...], "by": "rules", "stats": {...}}
  issue = {token, lane, level, reason, action: remove|replace, replace}

规则是确定性的：同样的组合永远得到同样的结论，0 秒出结果。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REF_DIR = os.path.join(ROOT, "ref")
if _REF_DIR not in sys.path:
    sys.path.insert(0, _REF_DIR)
import prompts as _prompts

_ID = re.compile(r"^@ID_")
_CAM = re.compile(r"^@CAM_")
_LIGHT = re.compile(r"^@LIGHT_")
_SCENE = re.compile(r"^@SET_")
_STYLE = re.compile(r"^@STYLE_")
_OUT = re.compile(r"^@OUT_")
_DRAPE = re.compile(r"^@DRAPE_")
_POSE = re.compile(r"^@POSE_")
_MOOD = re.compile(r"^@MOOD_")
_COMP_FIG = re.compile(r"^@COMP_FIGURE_")
_NEG = re.compile(r"^@NEG_")

BACK_VIEW_RE = re.compile(r"(^@(?:CAM_BACKSIDE|CAM_BACK_FAR|CAM_REAR|POSE_[FM]_BACK|POSE_M_WALK_AWAY)$|\bBACK VIEW\b|\bFROM BEHIND\b)", re.I)
FACE_WORDS = re.compile(r"\beye\b|\beyes\b|expressive eyes|blush|\bsmile\b|\blips\b|\bfringe\b|\bface\b", re.I)
TWIN_FLOWER_RE = re.compile(r"\b(twin|two|multiple|extra|duplicate)\s+seasonal blooms?\b", re.I)
FRONT_LIGHT = {"@LIGHT_WIN", "@LIGHT_SOFT", "@LIGHT_GOLDEN", "@LIGHT_FRONT"}


def _load():
    """词库 + 服装派生宏 + 各角色卡的视角块，共用 ref/prompts.load_full_catalog。"""
    tokens, notes, meta, _, _ = _prompts.load_full_catalog()
    return tokens, notes, meta


def _resolve(tok, aliases=None):
    """旧名 -> 新名；返回 (新名, 是否改过名)。"""
    if aliases is None:
        return _prompts.resolve_token(tok)
    cur, seen = tok, 0
    while cur in aliases and seen < 3:
        nxt = aliases[cur]
        if nxt == cur:
            break
        cur = nxt
        seen += 1
    return cur, (cur != tok)


def _gender(tok, meta):
    return _prompts.token_gender(tok, meta)


def audit(blocks, negatives=None):
    """blocks/negatives: [{"token": "@X", "text": "", "weight": 1.0, "enabled": true}]"""
    tokens, notes, meta = _load()
    aliases = dict(_prompts.ALIASES or {})
    blocks = [b for b in (blocks or []) if isinstance(b, dict)]
    negatives = [b for b in (negatives or []) if isinstance(b, dict)]
    issues = []
    stats = {"blocks": len(blocks), "negatives": len(negatives), "rules": 0}

    def add(tok, lane, level, reason, action="remove", replace=""):
        issues.append({"token": tok, "lane": lane, "level": level, "reason": reason,
                       "action": action, "replace": replace})
        stats["rules"] += 1

    pos = []
    for b in blocks:
        if b.get("enabled") is False:
            continue
        tok = str(b.get("token") or "").strip()
        txt = str(b.get("text") or "").strip()
        w = float(b.get("weight") or 1.0)
        if not tok and not txt:
            add(tok, "positive", "warn", "空文本块", "remove")
            continue
        if tok:
            new, renamed = _resolve(tok, aliases)
            if renamed:
                add(tok, "positive", "info", "旧积木名，已改名为 %s" % new, "replace", new)
                tok = new
            if tok not in tokens:
                add(tok, "positive", "error", "词库里没有这个积木", "remove")
                continue
        pos.append({"token": tok, "text": txt, "weight": w})

    toks = [b["token"] for b in pos if b["token"]]

    # 重复
    seen = set()
    for b in pos:
        t = b["token"]
        if not t:
            continue
        if t in seen:
            add(t, "positive", "warn", "重复积木", "remove")
        seen.add(t)

    # 机位/光位/场景/服装/姿态/情绪 只能各一份
    def keep_first(pattern, label, level="warn"):
        arr = [t for t in dict.fromkeys(toks) if pattern.match(t)]
        for t in arr[1:]:
            add(t, "positive", level, "同时有 %d 个%s积木，只用第一个" % (len(arr), label), "remove")
        return arr

    cam = keep_first(_CAM, "机位")
    keep_first(_LIGHT, "光位")
    scenes = keep_first(_SCENE, "场景", "error")
    outfits = keep_first(_OUT, "服装", "error")
    keep_first(_POSE, "姿态")
    keep_first(_MOOD, "情绪")
    keep_first(_STYLE, "画风")
    comp_fig = keep_first(_COMP_FIG, "构图")

    # 画风 + 场景
    if any(_STYLE.match(t) for t in toks) and scenes:
        for t in [t for t in toks if _STYLE.match(t)]:
            add(t, "positive", "warn", "画风积木会让场景变成白底", "remove")

    # 型态必须有服装
    if any(_DRAPE.match(t) for t in toks) and not outfits:
        for t in [t for t in toks if _DRAPE.match(t)]:
            add(t, "positive", "warn", "型态积木没有对应服装", "remove")

    # 身份与性别
    ids = [t for t in toks if _ID.match(t) or t in ("@SINGLE", "@SINGLE_F", "@SINGLE_M")]
    id_genders = {_gender(t, meta) for t in ids} - {""}
    if len(ids) > 2:
        for t in ids[2:]:
            add(t, "positive", "warn", "身份积木超过 2 个，会互相打架", "remove")
    if len(id_genders) > 1:
        add(ids[-1] if ids else "", "positive", "error", "男女身份混用", "remove")
    g = next(iter(id_genders), "")
    if g and outfits:
        bad = [t for t in outfits if _gender(t, meta) and _gender(t, meta) != g]
        for t in bad:
            add(t, "positive", "error", "服装性别与身份不一致", "remove")
    if g and comp_fig:
        pass

    # 背影：眼睛/脸词、正面光（排除 @LIGHT_BACK 等光位块误判）
    backs = [t for t in toks if not _LIGHT.match(t) and BACK_VIEW_RE.search(t)]
    if backs:
        for t in list(toks):
            if _LIGHT.match(t) and t in FRONT_LIGHT:
                rep = (t + "_BACK") if (t + "_BACK") in tokens else ("@LIGHT_BACK" if "@LIGHT_BACK" in tokens else "")
                if rep:
                    add(t, "positive", "warn", "背影场景用了正面光", "replace", rep)
        if ids:
            for t in ids:
                txt = str(tokens.get(t, ""))
                if FACE_WORDS.search(txt):
                    body = t.replace("@ID_F_", "@BODY_F_").replace("@ID_M_", "@BODY_M_")
                    if body in tokens:
                        add(t, "positive", "warn", "身份块含脸/眼词，背影会把她转过来", "replace", body)
                    elif t.startswith("@ID_F") and "@BODY_F_B" in tokens:
                        add(t, "positive", "warn", "身份块含脸/眼词，背影会把她转过来", "replace", "@BODY_F_B")
                    else:
                        add(t, "positive", "warn", "身份块含脸/眼词，背影会把角色转过来", "remove")

    # 构图冲突
    if any(t.endswith("_CENTER") for t in comp_fig) and any(t.endswith("_THIRDS") for t in comp_fig):
        add(comp_fig[-1], "positive", "warn", "中心构图与三分构图同时存在", "remove")

    # 权重异常
    for b in pos:
        if b["token"] and not (0.3 <= b["weight"] <= 1.6):
            add(b["token"], "positive", "info", "权重 %.2f 超出常用范围（0.3~1.6）" % b["weight"], "replace", b["token"])

    # 积木过多
    if len([t for t in toks]) > 40:
        add("", "positive", "warn", "积木 %d 块，超过 40 块后模型会忽略后半段" % len(toks), "remove")

    # 负向
    seen_neg = set()
    for b in negatives:
        if b.get("enabled") is False:
            continue
        tok = str(b.get("token") or "").strip()
        txt = str(b.get("text") or "").strip()
        if not tok and not txt:
            add("", "negative", "warn", "空负向块", "remove")
            continue
        if tok:
            new, renamed = _resolve(tok, aliases)
            if renamed:
                add(tok, "negative", "info", "旧积木名，已改名为 %s" % new, "replace", new)
                tok = new
            if tok not in tokens:
                add(tok, "negative", "error", "负向积木不在词库", "remove")
                continue
            if not _NEG.match(tok) and not tok.startswith(("@NEG", "@CROP", "@STRIP")):
                add(tok, "negative", "error", "正向积木被放进了负向", "remove")
            if tok in seen_neg:
                add(tok, "negative", "warn", "重复负向积木", "remove")
            seen_neg.add(tok)
        else:
            pos_words = " ".join(str(tokens.get(t, "")) for t in toks)
            low_txt = TWIN_FLOWER_RE.sub("", txt.lower())
            for w in ("white hair", "shoulder-length hair", "seasonal blooms"):
                if w in low_txt and w in pos_words.lower():
                    add("", "negative", "warn", "负向里出现正向身份词「%s」" % w, "remove")
                    break

    # 拆分统计
    stats["tokens"] = len(toks)
    stats["errors"] = len([i for i in issues if i["level"] == "error"])
    stats["warns"] = len([i for i in issues if i["level"] == "warn"])
    return {"issues": issues, "by": "rules", "stats": stats}


def apply_fixes(blocks, negatives, issues):
    """按 issues 返回修好的 (blocks, negatives)：replace 换 token，remove 删块。"""
    rm_pos = {i["token"] for i in issues if i["lane"] == "positive" and i["action"] == "remove" and i["token"]}
    rep_pos = {i["token"]: i["replace"] for i in issues if i["lane"] == "positive" and i["action"] == "replace" and i["replace"]}
    rm_neg = {i["token"] for i in issues if i["lane"] == "negative" and i["action"] == "remove" and i["token"]}
    rep_neg = {i["token"]: i["replace"] for i in issues if i["lane"] == "negative" and i["action"] == "replace" and i["replace"]}
    out_pos, out_neg = [], []
    for b in blocks or []:
        t = str((b or {}).get("token") or "")
        if t and t in rm_pos:
            continue
        if t and t in rep_pos and rep_pos[t] != t:
            b = dict(b, token=rep_pos[t])
        out_pos.append(b)
    for b in negatives or []:
        t = str((b or {}).get("token") or "")
        if t and t in rm_neg:
            continue
        if t and t in rep_neg and rep_neg[t] != t:
            b = dict(b, token=rep_neg[t])
        out_neg.append(b)
    return out_pos, out_neg


if __name__ == "__main__":
    import sys
    data = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    print(json.dumps(audit(data.get("blocks") or [], data.get("negatives") or []), ensure_ascii=False, indent=1))
