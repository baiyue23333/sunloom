# -*- coding: utf-8 -*-
"""b_lens 镜头优先：五类镜头词白名单 + 分阶段调度（唯一真相源）。

01_plate  镜头提位提权一次性确立（人物位置 / 前景遮挡 / 背景散景 / 占框留白）
02_body   只保留第 1 类（局部仍成立的透视与表现），第 2/3/4 类剥除
        命中第 3 类前景遮挡时置 protect_fg_depth，由 DA3 深度锁回虚化前景
03_face   按实测头部朝向过滤异瞳与五官词（与 station/ir.check_view 同款规则）

无任何 cam/comp/bokeh 积木时完全放手：ratio_mode=auto + 去摆拍自然朝向词。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, "ref"), os.path.join(ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import prompt_slim as slim
import prompts as plib

# 1 类：局部精修阶段仍然成立的光学视角与表现形式（剪影/隔玻璃/镜反射等）
_K1 = """
@CAM_GROUND @CAM_KNEE @CAM_HIGH @CAM_HIGH_WIDE @CAM_LOW_WIDE @CAM_LOW_THREEQ
@CAM_LOW_FLOOR_TILT @CAM_WORM @CAM_OVERHEAD @CAM_TOP @CAM_TOPDOWN_SCENE @CAM_HIP
@CAM_EYE @CAM_TELE @CAM_WIDE @CAM_DUTCH @CAM_DUTCH_CLOSE @CAM_ISOMETRIC
@CAM_PROFILE @CAM_THREEQ @CAM_THREEQ_WIDE @CAM_SIDE_FAR @CAM_BACKSIDE @CAM_BACK_FAR
@CAM_SHOULDER @CAM_WAIST_SIDE @CAM_SIDE_TRACKING @CAM_CORNER @CAM_FULL @CAM_MEDIUM
@CAM_BUST @CAM_COWBOY @CAM_POV @CAM_FOCAL_14MM @CAM_FOCAL_24MM @CAM_FOCAL_35MM
@CAM_FOCAL_50MM @CAM_FOCAL_85MM @CAM_FOCAL_135MM @CAM_LENS_FISHEYE @CAM_LENS_TILTSHIFT
@CAM_LENS_ANAMORPHIC @CAM_LENS_SWIRL_BOKEH @CAM_LENS_SOFT_DIFFUSION @CAM_REFLECTION_LOW
@COMP_TELE @COMP_WIDE @COMP_STD @COMP_DUTCH @COMP_TILTSHIFT @COMP_SILHOUETTE
@COMP_GLASS_LAYER @COMP_MIRROR @COMP_REFLECTION @COMP_GRAPHIC
"""
# 2 类：背景散景虚化（出板提权建散景，人体重绘剥除、靠遮罩锁焦外）
_K2 = "@BG_BOKEH @BG_CINEMA_BOKEH @ATMO_BOKEH"
# 3 类：前景虚化遮挡（出板建遮挡，人体重绘走 DA3 深度锁回）
_K3 = """
@CAM_PEEP_FOLIAGE @COMP_FOREGROUND @COMP_DEPTH_SANDWICH @CAM_DOORWAY @CAM_WINDOW
@COMP_EDGE_ANCHOR @COMP_LAYERED_PORTAL
"""
# 4 类：整幅占框/留白（只在 01_plate 用，局部框里带入会被画成大片天空）
_K4 = """
@COMP_VAST @COMP_FIGURE_SMALL @COMP_FIGURE_1_3 @COMP_FIGURE_1_4 @COMP_FIGURE_1_7
@COMP_FIGURE_1_10 @COMP_FIGURE_BOTTOM @COMP_FIGURE_EDGE @COMP_SINGLE_FIGURE
@COMP_THIRDS @COMP_CENTER @COMP_SYMMETRY @COMP_NEGATIVE @COMP_LOOKROOM @COMP_HEADROOM
@COMP_HORIZON_LOW @COMP_HORIZON_HIGH @COMP_GOLDEN @COMP_GOLDEN_SPIRAL @COMP_MINIMAL
@COMP_LAYERS @COMP_CROP @COMP_MACRO @COMP_FILL @COMP_FRAME @COMP_FRAMEINFRAME
@COMP_V_FRAME @COMP_LEADING @COMP_DIAGONAL @COMP_DIAGONAL_SHADOW @COMP_TRIANGLE
@COMP_CURVE @COMP_RHYTHM @COMP_RADIAL_BURST @COMP_OFF_BALANCE @COMP_LOW_CLEAR_SKY
@COMP_TIGHT_OVERLAP @CAM_ESTABLISH @CAM_FULL_WIDE
"""
# 5 类：对视/看镜头（其余未指定时默认自然朝向、不许摆拍正视）
_K5 = "@GAZE_CAMERA @GAZE_LOOKING_UP_CAMERA @CAM_CLOSEUP @CAM_EXTREME_CU @CAM_HIGH"


def _mk(s):
    return {t for t in s.split() if t.startswith("@")}


PERSPECTIVE_STYLE_KEEP = _mk(_K1)
BG_BOKEH_TOKS = _mk(_K2)
FG_OCCLUDE_TOKS = _mk(_K3)
FRAME_COMP_TOKS = _mk(_K4)
LOOK_AT_CAMERA_TOKS = _mk(_K5)

# 明显侧/背机位：出现时抑制"看镜头"词
SIDE_BACK_TOKS = {"@CAM_PROFILE", "@CAM_SIDE_FAR", "@CAM_BACKSIDE", "@CAM_BACK_FAR",
                  "@CAM_WAIST_SIDE", "@CAM_SIDE_TRACKING", "@CAM_THREEQ"}
# 未归类的 @CAM_/@COMP_ 一律当第 1 类（保守：两阶段都留）
PLATE_BOOST = 1.25
CANDID = "candid, natural orientation in scene, not looking at viewer"
LOOK_PHRASES = ("looking directly at the viewer", "looking at viewer",
                "eye contact with viewer", "making eye contact")
_FACE_FULL = "from behind, back view"

EYE_RED = re.compile(r"\bred[\s-]?eyes?\b", re.I)
EYE_GREY = re.compile(r"\bgrey[\s-]?eyes?\b|\bgray[\s-]?eyes?\b", re.I)
EYE_ANY = re.compile(r"\b(?:eyes?|two-tone eyes|fringe|blush|lips|face)\b", re.I)
_WRAP = re.compile(r"^\(\s*(.+?)\s*:\s*[\d.]+\s*\)$")
_WEIGHT_GROUP = re.compile(r"^\(\s*(.+)\s*:\s*([+-]?[\d.]+)\s*\)$", re.S)

_TOKENS = None


def tokens():
    global _TOKENS
    if _TOKENS is None:
        _TOKENS, _, _ = plib.load_tokens()
    return _TOKENS


def classify(tok):
    """返回 keep / bokeh / fg / frame / look；未登记的 @CAM_/@COMP_ 归 keep。"""
    t = str(tok or "").strip().upper()
    if t in BG_BOKEH_TOKS:
        return "bokeh"
    if t in FG_OCCLUDE_TOKS:
        return "fg"
    if t in FRAME_COMP_TOKS:
        return "frame"
    if t in LOOK_AT_CAMERA_TOKS:
        return "look"
    return "keep" if t.startswith(("@CAM_", "@COMP_")) else ""


def _bare(seg):
    s = str(seg or "").strip()
    m = _WRAP.match(s)
    if m:
        s = m.group(1).strip()
    return s.lower()


def _fmt(w):
    return ("%.2f" % w).rstrip("0").rstrip(".")


def phrase(tok, weight=1.0, boost=0.0):
    """展开成带权短语：原权重 <1.05 时按 boost 提权，手调更高权重保留。"""
    txt = (tokens().get(str(tok or "").upper()) or "").strip()
    if not txt or txt == "\u200b":
        return ""
    try:
        w = float(weight)
    except (TypeError, ValueError):
        w = 1.0
    if w <= 0:
        w = 1.0
    if boost and w <= 1.05:
        w = float(boost)
    return txt if abs(w - 1.0) < 1e-6 else "(%s:%s)" % (txt, _fmt(w))


def _items(cfg):
    spec = (cfg or {}).get("lens_spec") or {}
    out = []
    for key in ("cam_tokens", "comp_tokens", "bokeh_tokens", "gaze_tokens"):
        for it in (spec.get(key) or []):
            tok = it if isinstance(it, str) else str((it or {}).get("token") or "")
            try:
                w = 1.0 if isinstance(it, str) else float((it or {}).get("weight") or 1.0)
            except (TypeError, ValueError):
                w = 1.0
            tok = tok.strip().upper()
            if tok and tok not in [x[0] for x in out]:
                out.append((tok, w))
    return out


def build_lens_plan(cfg):
    """把前端 lens_spec 译成各阶段可执行的镜头计划（纯规则，不加载模型）。"""
    items = _items(cfg)
    cls = {"keep": [], "bokeh": [], "fg": [], "frame": [], "look": []}
    for tok, w in items:
        k = classify(tok)
        if k:
            cls[k].append((tok, w))
    spec = (cfg or {}).get("lens_spec") or {}
    has_cam = any(spec.get(k) for k in ("cam_tokens", "comp_tokens", "bokeh_tokens"))
    auto = not has_cam
    plate, body_drop, plate_drop = [], [], []
    for tok, w in items:
        k = classify(tok)
        if k:
            plate_drop.append(tokens().get(tok) or "")
        if k in ("bokeh", "fg", "frame"):
            body_drop.append(tokens().get(tok) or "")
            plate.append(phrase(tok, w, PLATE_BOOST))
        elif k in ("keep", "look"):
            plate.append(phrase(tok, w, PLATE_BOOST))
    cue = [x for x in plate if x]
    suppress = bool(cls["fg"]) or any(t in SIDE_BACK_TOKS for t, _w in items)
    if suppress:
        drop_low = [x.lower() for x in LOOK_PHRASES]
        cue = [x for x in cue if not any(d in x.lower() for d in drop_low)]
    return {
        "has_lens": bool(items),
        "auto_ratio": auto,
        "ratio_mode": "auto" if auto else "fixed",
        "count": len(items),
        "classes": {k: [t for t, _w in v] for k, v in cls.items()},
        "plate_cue": ", ".join(cue),
        "body_drop": [x for x in body_drop if x],
        "plate_drop": [x for x in plate_drop if x],
        "protect_fg_depth": bool(cls["fg"]),
        "suppress_look": suppress,
        "candid": bool(auto) and not cls["look"] and not any(t.startswith("@GAZE_") for t, _w in items),
    }


def strip_phrases(text, phrases):
    """按整句匹配剥除展开短语（用于 02_body 去掉第 2/3/4 类词）。"""
    drop = set()
    for ph in (phrases or []):
        for seg in slim.split_clauses(ph):
            b = _bare(seg)
            if len(b) >= 4:
                drop.add(b)
    if not drop or not text:
        return text or ""
    def strip_group(value):
        keep = []
        for seg in slim.split_clauses(value):
            if _bare(seg) in drop:
                continue
            weighted = _WEIGHT_GROUP.match(seg.strip())
            if weighted:
                inner = strip_group(weighted.group(1))
                if inner:
                    keep.append("(%s:%s)" % (inner, weighted.group(2)))
            else:
                keep.append(seg)
        return ", ".join(keep)

    return strip_group(text)


def plate_prompt(base, plan):
    """把提权镜头短语插到最前（=质量词之后、@SET_* 场景长段之前）。"""
    plan = plan or {}
    cue = plan.get("plate_cue") or ""
    base = strip_phrases(base or "", plan.get("plate_drop") or [])
    if plan.get("suppress_look"):
        base = strip_phrases(base, LOOK_PHRASES)
    result = slim.merge_neg(cue, base) if cue else base
    return slim.merge_neg(result, CANDID) if plan.get("candid") else result


def body_prompt(text, plan):
    """02_body 用：去掉第 2/3/4 类；命中前景遮挡时一并压掉对视词。"""
    out = strip_phrases(text or "", (plan or {}).get("body_drop") or [])
    if (plan or {}).get("suppress_look"):
        out = strip_phrases(out, LOOK_PHRASES)
    return out


def _drop_in_clause(seg, pat):
    s = pat.sub(" ", seg)
    s = re.sub(r"[\s,;/&]*(?:\band\b)?[\s,;/&]*$", "", s.strip())
    s = re.sub(r"^[\s,;/&]*(?:\band\b)?[\s,;/&]*", "", s)
    return re.sub(r"\s{2,}", " ", s).strip(" ,;/&")


def adapt_face_prompt(text, facing):
    """按 6 档朝向改修脸提示词：正脸全留；朝右去 red eye；朝左去 grey eye；背面全去五官。"""
    f = str(facing or "").strip().lower()
    if not text or not f:
        return text or ""
    if f == "back":
        keep = [s for s in slim.split_clauses(text) if not EYE_ANY.search(_bare(s))]
        return slim.merge_neg(", ".join(keep), _FACE_FULL)
    if f.endswith("_right"):
        pat = EYE_RED
    elif f.endswith("_left"):
        pat = EYE_GREY
    else:
        return text
    out = []
    for seg in slim.split_clauses(text):
        if not pat.search(_bare(seg)):
            out.append(seg)
            continue
        cleaned = _drop_in_clause(seg, pat)
        if cleaned:
            out.append(cleaned)
    return ", ".join(out)


FACING_CUE = {
    "three_quarter_left": "three-quarter view, face turned toward the left of the frame",
    "three_quarter_right": "three-quarter view, face turned toward the right of the frame",
    "profile_left": "left profile view, side of the face toward the left of the frame",
    "profile_right": "right profile view, side of the face toward the right of the frame",
    "back": _FACE_FULL,
    "front": "",
}


def facing_cue(facing):
    return FACING_CUE.get(str(facing or "").strip().lower(), "")
