
# -*- coding: utf-8 -*-
"""ir.py - 积木 -> 提示词 IR 的校验器。

设计：积木不再是字符串拼接，而是带 role 的结构；校验器保证
  ① 身份锁在
  ② 服装与型态兼容
  ③ 负向有底线且顺序正确
  ④ 场景强时自动提示服装保护
"""
import json
import os

ROLE_BY_PREFIX = [
    ("@SINGLE", "identity"), ("@ID", "identity"),
    ("@BODY", "body"), ("@FACE", "face"),
    ("@MOOD", "mood"), ("@GAZE", "gaze"), ("@HAND", "hand"), ("@HAIR", "hair"),
    ("@CAM", "camera"), ("@COMP", "camera"),
    ("@LIGHT", "light"), ("@ATMO", "light"), ("@TIME", "light"), ("@WEATHER", "light"), ("@SEASON", "light"),
    ("@SET", "scene"),
    ("@OUT", "garment"), ("@FAB", "garment"), ("@DRAPE", "drape"),
    ("@ROLE", "prop"), ("@PROP", "prop"), ("@OBJ", "prop"), ("@INSTR", "prop"), ("@RIDE", "prop"),
    ("@STYLE", "style"),
    ("@NEG", "negative"),
]

STRONG_SCENE_ROLES = {"scene"}

_WORN = {"@DRAPE_WORN", "@DRAPE_REF"}
DRAPE_GARMENT = {
    "slip": {"@DRAPE_OFF", "@DRAPE_CAPE", "@DRAPE_ELBOW", "@DRAPE_HALF", "@DRAPE_HOLD", "@DRAPE_SHRUG"},
    "initial": _WORN,
    "casual_knit": _WORN | {"@DRAPE_SHRUG", "@DRAPE_OFF"},
    "school": _WORN,
    "gala": _WORN | {"@DRAPE_OFF"},
    "raincoat": _WORN | {"@DRAPE_CAPE"},
    "gym": _WORN,
    "winter": _WORN | {"@DRAPE_CAPE"},
    "yukata": _WORN | {"@DRAPE_OFF"},
    "smock": _WORN | {"@DRAPE_OFF"},
    "maid": _WORN,
    "swimsuit": _WORN,
    "hanfu": _WORN | {"@DRAPE_OFF"},
    "suit": _WORN,
    "santa": _WORN,
    "idol": _WORN,
    "loungewear": _WORN,
    "cheongsam": _WORN,
    "overalls": _WORN,
    "sundress": _WORN | {"@DRAPE_OFF"},
}

RULES_DOC = [
    "身份：正向必须包含 @ID（或含身份锁的等价文本）",
    "服装：@OUT_SLIP 与 @OUT_INITIAL 不能同时出现",
    "型态：@DRAPE_* 必须与服装套装匹配（slip 用半脱系；initial/school/gym 用穿好系；gala/yukata/smock 可半脱）",
    "负向：必须含 @NEG_BASE；若有手部动作，建议加 @NEG_HAND_ART",
    "顺序：负向里 @NEG_CUP / @NEG_HANDS 应排在最前两位",
    "场景：场景块权重 > 1.15 时会被服装吃掉，建议同时加强服装或加 @NEG_FABRIC",
]


def role_of(token):
    for pre, role in ROLE_BY_PREFIX:
        if token.startswith(pre):
            return role
    return "misc"


def validate(pos_blocks, neg_blocks):
    """pos/neg: [{"token": "@ID", "weight": 1.0, "text": ""}]"""
    errors, warnings, hints = [], [], []

    pos = [(b.get("token") or "", float(b.get("weight") or 1.0), b.get("text") or "") for b in pos_blocks]
    neg = [(b.get("token") or "", float(b.get("weight") or 1.0), b.get("text") or "") for b in neg_blocks]
    pos_tokens = [t for t, _, _ in pos if t]
    roles = {}
    for t, w, _ in pos:
        if t:
            roles.setdefault(role_of(t), []).append((t, w))

    # ① 身份
    ID_WORDS = ("white hair", "ivory white hair", "heterochromia", "sunflower hair ornament")
    has_id = "@ID" in pos_tokens or any(any(w in (x or "").lower() for w in ID_WORDS) for _, _, x in pos)
    if not has_id:
        errors.append({"code": "NO_IDENTITY", "msg": "缺身份锁 @ID，人物会漂",
                       "fix": "把 @ID 拖进正向，权重 1.0"})

    # ② 服装互斥（任意两套同时出现都算冲突）
    outfits = sorted({t for t in pos_tokens if t.startswith("@OUT_")})
    if len(outfits) > 1:
        errors.append({"code": "GARMENT_CONFLICT", "msg": "两套服装同时出现：" + " + ".join(outfits),
                       "fix": "只留一套；两套混用会变婚纱/晚礼服"})

    # ③ 型态与服装匹配
    garment = outfits[0][5:].lower() if outfits else None
    drapes = [t for t in pos_tokens if t.startswith("@DRAPE_")]
    if garment and drapes:
        allowed = DRAPE_GARMENT.get(garment, set())
        bad = [d for d in drapes if d not in allowed]
        if bad:
            warnings.append({"code": "DRAPE_GARMENT_MISMATCH",
                             "msg": "%s 与 %s 不搭" % ("、".join(bad), "@OUT_" + garment.upper()),
                             "fix": "slip 用 @DRAPE_OFF/@DRAPE_ELBOW；initial/school/gym 用 @DRAPE_WORN；gala/yukata/smock 可 @DRAPE_OFF"})

    # ④ 负向底线
    if not any(t == "@NEG_BASE" for t, _, _ in neg):
        warnings.append({"code": "NO_NEG_BASE", "msg": "负向缺 @NEG_BASE，容易出现低质量/分屏",
                         "fix": "负向第一块放 @NEG_BASE"})
    if "@CAM_CLOSEUP" in pos_tokens and "@STYLE_SOFT" in pos_tokens:
        warnings.append({"code": "CLOSEUP_SOFT_WASH",
                         "msg": "特写 + 柔画风会糊成一片，二选一，或把 @STYLE_SOFT 换成 @STYLE_CEL"})
    head = [t for t, _, _ in neg if t][:2]
    if any(t in ("@NEG_CUP", "@NEG_HANDS") for t, _, _ in neg) and not any(t in ("@NEG_CUP", "@NEG_HANDS") for t in head):
        warnings.append({"code": "NEG_ORDER", "msg": "杯子/手的负向没在最前，容易被稀释",
                         "fix": "把 @NEG_CUP 或 @NEG_HANDS 拖到负向第一位"})

    # ⑤ 手部动作提示
    if "hand" in roles and not any(t == "@NEG_HAND_ART" for t, _, _ in neg):
        hints.append({"code": "HAND_NO_GUARD", "msg": "有手部动作但没加 @NEG_HAND_ART",
                      "fix": "加一块 @NEG_HAND_ART 防多指"})

    # ⑥ 场景强度 vs 服装
    scene_w = max([w for t, w in roles.get("scene", [])] or [0])
    if scene_w > 1.15 and "@OUT_INITIAL" in pos_tokens:
        hints.append({"code": "SCENE_EATS_GARMENT",
                      "msg": "场景权重 %.2f，初始服装有被吃掉的风险（实测出现过白裙漂移）" % scene_w,
                      "fix": "把场景压到 1.1 以下，或加 @NEG_FABRIC + 加强 @OUT_INITIAL 权重"})

    # ⑦ 构图互斥：同一张图只能有一个主构图
    def _pick(*names):
        return [n for n in names if n in pos_tokens]

    if "@COMP_CENTER" in pos_tokens and _pick("@COMP_THIRDS", "@COMP_GOLDEN"):
        warnings.append({"code": "COMP_CENTER_CONFLICT",
                         "msg": "居中构图与三分法/黄金分割同时开，画面会打架",
                         "fix": "只留一个：居中 → 稳；三分/黄金 → 松"})
    if "@COMP_THIRDS" in pos_tokens and "@COMP_GOLDEN" in pos_tokens:
        hints.append({"code": "COMP_THIRDS_GOLDEN",
                      "msg": "三分法与黄金分割近似，重复了",
                      "fix": "二选一即可，不必叠加"})
    if "@COMP_TELE" in pos_tokens and "@COMP_WIDE" in pos_tokens:
        warnings.append({"code": "COMP_LENS_CONFLICT",
                         "msg": "长焦压缩与广角同时开，镜头语言矛盾",
                         "fix": "@COMP_TELE 人像 / @COMP_WIDE 环境，选一个"})
    if "@COMP_SYMMETRY" in pos_tokens and "@COMP_DUTCH" in pos_tokens:
        warnings.append({"code": "COMP_TILT_CONFLICT",
                         "msg": "对称构图配荷兰角，对称会被倾斜破坏",
                         "fix": "要对称就别歪，要歪就别对称"})
    if "@COMP_CROP" in pos_tokens and "@CAM_FULL" in pos_tokens:
        warnings.append({"code": "COMP_CROP_FULL",
                         "msg": "切边紧框与全身机位冲突（全身边就没有裁切）",
                         "fix": "换 @CAM_BUST 或去掉 @COMP_CROP"})
    if "@COMP_FILL" in pos_tokens and _pick("@COMP_WIDE", "@COMP_NEGATIVE"):
        warnings.append({"code": "COMP_FILL_CONFLICT",
                         "msg": "满幅与广角/负空间同时开，一个要填满一个要留白",
                         "fix": "满幅配 @CAM_BUST；要环境就删 @COMP_FILL"})
    if "@COMP_MACRO" in pos_tokens and "@CAM_FULL" in pos_tokens:
        warnings.append({"code": "COMP_MACRO_FULL",
                         "msg": "微距特写与全身机位冲突",
                         "fix": "微距只拍局部，机位换 @CAM_BUST 或去掉 @COMP_MACRO"})
    if "@COMP_HORIZON_LOW" in pos_tokens and "@COMP_HORIZON_HIGH" in pos_tokens:
        warnings.append({"code": "COMP_HORIZON_CONFLICT",
                         "msg": "高地平线与低地平线不能同时成立",
                         "fix": "二选一：低地平线给人留天，高地平线给人留地"})
    if "@COMP_SILHOUETTE" in pos_tokens:
        hints.append({"code": "COMP_SILHOUETTE_FACE",
                      "msg": "剪影会吃掉脸和异瞳，@ID 基本失效",
                      "fix": "只在明确要轮廓时用；要脸就别加 @COMP_SILHOUETTE"})
    if "@COMP_STD" in pos_tokens and _pick("@COMP_TELE", "@COMP_WIDE"):
        hints.append({"code": "COMP_STD_LENS",
                      "msg": "标准镜头与长焦/广角重复",
                      "fix": "镜头语言留一个就够"})
    if "@COMP_LOOKROOM" in pos_tokens and not any(t.startswith("@GAZE") for t in pos_tokens):
        hints.append({"code": "COMP_LOOKROOM_NO_GAZE",
                      "msg": "视线留白没有配 @GAZE_*，模型不知道她看哪边",
                      "fix": "加一块 @GAZE_LEFT / @GAZE_RIGHT / @GAZE_DOWN"})

    return {"ok": not errors, "errors": errors, "warnings": warnings, "hints": hints,
            "stats": {"pos": len(pos), "neg": len(neg), "roles": {k: len(v) for k, v in roles.items()}}}
