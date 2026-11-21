# -*- coding: utf-8 -*-
"""场景与动作提示词层级判定：区分无遮挡(两层)、轻微接地(两层半)、景深提层(三层DA3)与强交互(建议切A)。"""
import re

_SWITCH_A_RULES = (
    (r"\b(sitting|seated|sit on|sitting on|bench|chair|stool|sofa|couch)\b|坐着|坐在|长椅|椅子|沙发", "存在坐姿/家具接触"),
    (r"\b(behind\s+(a\s+|the\s+)?(table|desk|counter|bar|podium)|leaning\s+(on|against|over)|resting\s+elbows|lying\s+on|kneeling\s+on)\b|趴在|靠在|栏杆上|桌后|柜台后", "存在桌椅/栏杆物理交互"),
    (r"\b(from\s+above|high\s+angle|bird'?s?\s*eye|worm'?s?\s*eye|fisheye|dutch\s+angle)\b|俯拍|仰拍|大广角", "存在强俯仰或广角透视"),
)

_THREE_DEPTH_RULES = (
    (r"\b(foreground\s+(fence|railing|wall|pillar|pillars|column|columns|bush|bushes|tree|trees|branches|hedge)|behind\s+(fence|railing|pillars?|columns?|bushes?|trees?|hedge))\b|前景(围栏|栏杆|柱|树|灌木)|在(栏杆|围栏|柱子|树丛)后", "存在前景景深穿插遮挡"),
)

_TWO_HALF_RULES = (
    (r"\b(tall\s+grass|grassland|meadow|reeds|wheat\s+field|shallow\s+water|puddle|ankle[- ]deep|water\s+surface|fallen\s+leaves|snowfield|flower\s+petals)\b|草地|草丛|芦苇|浅水|水洼|积水|落叶|雪地|花瓣", "存在草地/浅水/落叶等轻微接地遮挡"),
)


def analyze_scene_layering(scene_text: str, char_text: str = "") -> dict:
    """根据场景与人物提示词判定建议层级与流水线。"""
    combined = f"{scene_text or ''}\n{char_text or ''}".strip()
    low = combined.lower()

    for pat, why in _SWITCH_A_RULES:
        m = re.search(pat, low, re.I)
        if m:
            return {
                "tier": "switch_a",
                "layer_mode": "two_layer",
                "suggest_pipeline": "a",
                "label": "建议切 A · 强交互",
                "reason": f"{why}（命中：{m.group(0)}），建议走 A 混绘同框处理",
                "keyword": m.group(0),
            }

    for pat, why in _THREE_DEPTH_RULES:
        m = re.search(pat, low, re.I)
        if m:
            return {
                "tier": "three_depth",
                "layer_mode": "three_depth",
                "suggest_pipeline": "b_char",
                "label": "三层 · DA3 景深提层",
                "reason": f"{why}（命中：{m.group(0)}），用 DA3 提取近景盖回人物前",
                "keyword": m.group(0),
            }

    for pat, why in _TWO_HALF_RULES:
        m = re.search(pat, low, re.I)
        if m:
            return {
                "tier": "two_half",
                "layer_mode": "two_half",
                "suggest_pipeline": "b_char",
                "label": "两层半 · 脚底咬合",
                "reason": f"{why}（命中：{m.group(0)}），仅在脚底做空景纹理咬合",
                "keyword": m.group(0),
            }

    return {
        "tier": "two_layer",
        "layer_mode": "two_layer",
        "suggest_pipeline": "b_char",
        "label": "两层 · 无遮挡",
        "reason": "开阔站姿/无明显前景遮挡词，两层直出最干净",
        "keyword": "",
    }
