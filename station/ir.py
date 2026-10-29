# -*- coding: utf-8 -*-
"""ir.py - prompt structure checks (generic)"""
import re

SUBJECT_WORDS = ("girl", "boy", "woman", "man", "character", "subject", "person", "solo", "people")
QUALITY_NEG = ("lowres", "bad anatomy", "bad hands", "watermark", "worst quality", "blurry")
CUP_HOLD = re.compile(r"holding[^,]{0,24}cup|cup in her hand", re.I)


def _joined(blocks, tokens=None):
    parts = []
    for b in blocks or []:
        if not b.get("enabled", True):
            continue
        raw = b.get("token") or b.get("text") or ""
        if tokens and raw:
            try:
                import prompts
                raw, _ = prompts.expand(raw, tokens)
            except Exception:
                pass
        parts.append(raw + " " + (b.get("text") or "" if b.get("token") else ""))
    return " ".join(parts).lower()


def validate(pos, neg, tokens=None):
    p, n = _joined(pos, tokens), _joined(neg, tokens)
    names = {(b.get("token") or "").upper() for b in (pos or []) if b.get("enabled", True)}
    errors, warnings, hints = [], [], []

    if not any(w in p for w in SUBJECT_WORDS):
        errors.append({"code": "NO_SUBJECT", "msg": "缺主体：加 @SUBJ，或描述画面主体"})
    if not n.strip():
        errors.append({"code": "NEG_EMPTY", "msg": "负向为空：至少加 @NEG_BASE"})
    if n.strip() and not any(w in n for w in QUALITY_NEG):
        warnings.append({"code": "NO_QUALITY_NEG", "msg": "负向缺少质量词（lowres / bad anatomy 等）"})
    if CUP_HOLD.search(p) and re.search(r"\bcup\b|\bmug\b|\bglass\b", n):
        hints.append({"code": "CUP_CONFLICT", "msg": "正向拿杯、负向禁杯：展开时会自动放宽杯具词"})
    if not any(nm.startswith("@CAM") for nm in names):
        hints.append({"code": "NO_CAM", "msg": "建议加机位积木（@CAM_*）"})
    if not any(nm.startswith("@LIGHT") for nm in names):
        hints.append({"code": "NO_LIGHT", "msg": "建议加打光积木（@LIGHT_*），它影响最大"})
    if not any(nm.startswith("@OUT") or nm == "@OUTFIT" for nm in names):
        hints.append({"code": "NO_OUTFIT", "msg": "建议加服装积木（@OUT_* 或 @OUTFIT）"})

    if "@COMP_CENTER" in names and ({"@COMP_THIRDS", "@COMP_GOLDEN"} & names):
        warnings.append({"code": "COMP_CENTER_CONFLICT", "msg": "居中与三分/黄金分割同时开，画面会打架"})
    if "@COMP_TELE" in names and "@COMP_WIDE" in names:
        warnings.append({"code": "COMP_LENS_CONFLICT", "msg": "长焦压缩与广角同时开，镜头语言矛盾"})
    if "@COMP_SYMMETRY" in names and "@COMP_DUTCH" in names:
        warnings.append({"code": "COMP_TILT_CONFLICT", "msg": "对称构图配荷兰角，对称会被倾斜破坏"})
    if "@COMP_CROP" in names and "@CAM_FULL" in names:
        warnings.append({"code": "COMP_CROP_FULL", "msg": "切边紧框与全身机位冲突"})
    if "@COMP_FILL" in names and ({"@COMP_WIDE", "@COMP_NEGATIVE"} & names):
        warnings.append({"code": "COMP_FILL_CONFLICT", "msg": "满幅与广角/负空间冲突"})
    if "@COMP_HORIZON_LOW" in names and "@COMP_HORIZON_HIGH" in names:
        warnings.append({"code": "COMP_HORIZON_CONFLICT", "msg": "高地平线与低地平线不能同时成立"})
    if "@COMP_MACRO" in names and "@CAM_FULL" in names:
        warnings.append({"code": "COMP_MACRO_FULL", "msg": "微距特写与全身机位冲突"})
    if "@COMP_SILHOUETTE" in names:
        hints.append({"code": "COMP_SILHOUETTE_FACE", "msg": "剪影会吃掉脸，主体描述基本失效"})
    ok = not errors
    return {"ok": ok, "errors": errors, "warnings": warnings, "hints": hints}
