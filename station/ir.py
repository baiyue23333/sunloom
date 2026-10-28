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
        errors.append({"code": "NO_SUBJECT", "msg": "No subject block: add @SUBJ or describe the subject"})
    if not n.strip():
        errors.append({"code": "NEG_EMPTY", "msg": "Negative prompt is empty: add @NEG_BASE"})
    if n.strip() and not any(w in n for w in QUALITY_NEG):
        warnings.append({"code": "NO_QUALITY_NEG", "msg": "Negative lacks quality words (lowres/bad anatomy/...)"})
    if CUP_HOLD.search(p) and re.search(r"\bcup\b|\bmug\b|\bglass\b", n):
        hints.append({"code": "CUP_CONFLICT", "msg": "You hold a cup while the negative forbids it; the expander will drop cup terms automatically"})
    if "@cam" not in p:
        hints.append({"code": "NO_CAM", "msg": "Consider a camera block (@CAM_*) for framing control"})
    if "@light" not in p:
        hints.append({"code": "NO_LIGHT", "msg": "Consider a lighting block (@LIGHT_*) - it changes the image most"})
    if "@out" not in p:
        hints.append({"code": "NO_OUTFIT", "msg": "Consider an outfit block (@OUT_*) or @OUTFIT"})
    ok = not errors
    return {"ok": ok, "errors": errors, "warnings": warnings, "hints": hints}
