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
    errors, warnings, hints = [], [], []

    if not any(w in p for w in SUBJECT_WORDS):
        errors.append({"code": "NO_SUBJECT", "msg": "缺主体：加 @SUBJ，或描述画面主体"})
    if not n.strip():
        errors.append({"code": "NEG_EMPTY", "msg": "负向为空：至少加 @NEG_BASE"})
    if n.strip() and not any(w in n for w in QUALITY_NEG):
        warnings.append({"code": "NO_QUALITY_NEG", "msg": "负向缺少质量词（lowres / bad anatomy 等）"})
    if CUP_HOLD.search(p) and re.search(r"\bcup\b|\bmug\b|\bglass\b", n):
        hints.append({"code": "CUP_CONFLICT", "msg": "正向拿杯、负向禁杯：展开时会自动放宽杯具词"})
    if "@cam" not in p:
        hints.append({"code": "NO_CAM", "msg": "建议加机位积木（@CAM_*）"})
    if "@light" not in p:
        hints.append({"code": "NO_LIGHT", "msg": "建议加打光积木（@LIGHT_*），它影响最大"})
    if "@out" not in p:
        hints.append({"code": "NO_OUTFIT", "msg": "建议加服装积木（@OUT_* 或 @OUTFIT）"})
    ok = not errors
    return {"ok": ok, "errors": errors, "warnings": warnings, "hints": hints}
