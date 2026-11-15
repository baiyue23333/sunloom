# -*- coding: utf-8 -*-
"""三位画师的调度：先让 7B 读完背景板，再决定每个人画什么。

分工：
    人物画师  —— 角色本体（含与场景的互动：手里拿什么、碰着什么、脚踩在哪）
    环境画师  —— 背景板（在已有 stage 细节上补充光影与氛围）
    前景画师  —— 挡在角色前面的近景元素（栏杆、门框、植物、挂灯）

为什么要有这一层：直接把 --scene 丢给三位画师，三人各画各的，
角色与场景没有关系（人物像贴上去的）。这一层负责把"关系"写进每个人的提示词。
"""
import json
import re

llm_manager = None  # 2026-11-15：本地模型已移除，走启发式兜底

SCHEMA = (
    '{"interaction":"角色与场景的具体接触（一句话，英文，如 holding a red umbrella / '
    'one hand touching the wet wall）",'
    '"char_extra":"给人物画师的补充提示词（英文，逗号分隔，10 个词以内）",'
    '"char_neg":"人物要避免的东西（英文，逗号分隔）",'
    '"env_extra":"给环境画师的补充提示词（英文，逗号分隔）",'
    '"foreground":[{"prompt":"前景物件的英文描述","x":0.5,"scale":0.35}]}'
)
Q = ("You are art-directing a layered illustration. Look at this background plate. "
     "Foreground means large near-camera objects (railings, door frames, plants, hanging signs) that partially block the view, "
     "never props the character holds. "
     "Decide: 1) how the character standing in this scene must physically interact with it; "
     "2) extra prompt words for the character painter; 3) extra words for the environment painter; "
     "4) one or two foreground OCCLUDERS that sit between the camera and the character and are NOT held by her "
     "Reply with ONLY one JSON object, no markdown, matching this schema: " + SCHEMA)


def _fallback(stage, scene=""):
    """没有 VL 时，从 stage 里能拿到的信息拼一份。"""
    inter = (stage or {}).get("interaction") or {}
    held = inter.get("held") or ""
    bits = []
    if held:
        bits.append("holding %s" % held)
    if inter.get("wet"):
        bits.append("standing on wet ground with subtle reflection")
    return {
        "by": "fallback",
        "interaction": ", ".join(bits),
        "char_extra": ", ".join(stage.get("char_details") or []) if stage else "",
        "char_neg": "",
        "env_extra": ", ".join(stage.get("details") or []) if stage else "",
        "foreground": [],
    }


def _parse(text):
    m = re.search(r"\{[\s\S]*\}", text or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    out = {"by": "vl", "interaction": str(data.get("interaction") or "")[:200],
           "char_extra": str(data.get("char_extra") or "")[:200],
           "char_neg": str(data.get("char_neg") or "")[:160],
           "env_extra": str(data.get("env_extra") or "")[:200],
           "foreground": []}
    BAD_FG = ("held by", "holding", "character", "girl", "she ", "hand")
    for f in (data.get("foreground") or [])[:2]:
        if not isinstance(f, dict) or not f.get("prompt"):
            continue
        if any(b in str(f["prompt"]).lower() for b in BAD_FG):
            continue   # 角色手里的东西不是前景遮挡物
        try:
            x = max(0.08, min(0.92, float(f.get("x", 0.5))))
            sc = max(0.12, min(0.75, float(f.get("scale", 0.35))))
        except Exception:
            x, sc = 0.5, 0.35
        out["foreground"].append({"prompt": str(f["prompt"])[:160], "x": x, "scale": sc})
    return out


def plan(plate, stage, scene=""):
    """读背景板 → 返回各方提示词。任何失败都退化成 stage 拼装。"""
    if llm_manager is None:
        return _fallback(stage, scene)
    mid = None
    try:
        mid = llm_manager.pick(["qwen2.5-vl-7b", "qwen2.5-vl-3b"])
    except Exception:
        mid = None
    if not mid:
        return _fallback(stage, scene)
    try:
        text = llm_manager.vision(mid, plate, Q, max_tokens=460)
        got = _parse(text)
        if got:
            return got
    except Exception as e:  # noqa: BLE001
        print("[conductor] VL 失败: %s" % str(e)[:100], flush=True)
    return _fallback(stage, scene)
