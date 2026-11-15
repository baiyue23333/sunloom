# -*- coding: utf-8 -*-
"""镜头语言：shot/priority -> 人物高度、卡片取景、合成锚点。"""
SHOTS = {
    "far": (0.18, 0.28, 0.24),
    "mid": (0.35, 0.48, 0.42),
    "near": (0.55, 0.68, 0.60),
    "closeup": (0.80, 0.95, 0.86),
}
PRIORITY_SHOT = {"character": "near", "balanced": "mid", "scenery": "far"}


def clamp(v, lo, hi):
    return max(lo, min(hi, float(v)))


def resolve(shot="auto", priority="auto", stage=None, bias=1.0):
    """返回 (shot, ratio, framing, anchor)。手动 > 构图优先 > 7B > mid。"""
    st = stage or {}
    sh = str(shot or "auto").lower()
    pri = str(priority or "auto").lower()
    if sh not in SHOTS:
        if pri in PRIORITY_SHOT:
            sh = PRIORITY_SHOT[pri]
        else:
            sh = str(st.get("shot", "mid")).lower()
            if sh not in SHOTS:
                sh = "mid"
    lo, hi, base = SHOTS[sh]
    ratio = clamp(base * (1.0 if sh == "closeup" else float(bias)), lo, hi)
    framing = "bust" if sh == "closeup" else "full"
    anchor = "bottom" if sh == "closeup" else "feet"
    return sh, ratio, framing, anchor
