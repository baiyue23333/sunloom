
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
import re
import sys

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in (os.path.join(_ROOT_DIR, "ref"), os.path.join(_ROOT_DIR, "tools")):
    if _d not in sys.path:
        sys.path.insert(0, _d)
import prompts as _prompts
try:
    from classify_blocks import MEDIUM as MEDIUM_SCENES, SMALL as SMALL_SCENES
except Exception:
    SMALL_SCENES, MEDIUM_SCENES = set(), set()

ROLE_BY_PREFIX = [
    ("@SINGLE", "identity"), ("@ID", "identity"),
    ("@BODY", "body"), ("@BARE", "body"),
    ("@FACE", "face"), ("@MAKEUP", "face"), ("@SKIN", "face"),
    ("@MOOD", "mood"), ("@GAZE", "gaze"), ("@HAND", "hand"), ("@HAIR", "hair"),
    ("@PIN", "acc"), ("@CLIP", "acc"), ("@BERET", "acc"), ("@HEADBAND", "acc"),
    ("@RIBBON", "acc"), ("@FLOWER_CROWN", "acc"), ("@HAIRPIN", "acc"),
    ("@MINI", "acc"), ("@ACC", "acc"),
    ("@CAM", "camera"), ("@COMP", "camera"), ("@CROP", "camera"), ("@BG", "camera"),
    ("@LIGHT", "light"), ("@ATMO", "light"), ("@TIME", "light"), ("@WEATHER", "light"), ("@SEASON", "light"),
    ("@SET", "scene"),
    ("@OUT", "garment"), ("@HOSE", "garment"), ("@FAB", "garment"), ("@DRAPE", "drape"),
    ("@ROLE", "prop"), ("@PROP", "prop"), ("@OBJ", "prop"), ("@INSTR", "prop"), ("@RIDE", "prop"),
    ("@HOLD", "hold"), ("@WEAPON", "weapon"),
    ("@STYLE", "style"), ("@FX", "style"),
    ("@NSFW", "nsfw"),
    ("@STRIP", "negative"),
    ("@NEG", "negative"),
]

STRONG_SCENE_ROLES = {"scene"}

_WORN = {"@DRAPE_WORN", "@DRAPE_REF", "@DRAPE_SLEEVES_ROLLED", "@DRAPE_CARDIGAN_TIED"}
DRAPE_GARMENT = {
    "slip": {"@DRAPE_OFF", "@DRAPE_CAPE", "@DRAPE_ELBOW", "@DRAPE_HOLD"},
    "initial": _WORN,
    "casual_knit": _WORN | {"@DRAPE_OFF"},
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
for _gk in ("maid", "swimsuit", "school", "school_bare", "gym", "pajama", "loungewear",
            "apron_m", "gym_m", "hakama_m", "jersey_m", "jinbei_m", "swim_m", "yukata_m"):
    DRAPE_GARMENT[_gk] = _WORN
for _gk in ("denim_set", "hoodie_casual", "initial_fine_gala", "initial_fine_lite", "lab_coat",
            "sailor_winter", "sunbloom", "sundress_floral"):
    DRAPE_GARMENT[_gk] = _WORN | {"@DRAPE_OPEN_FRONT", "@DRAPE_BELT"}
for _gk in ("cardigan_set", "initial_fine", "yukata_bare"):
    DRAPE_GARMENT[_gk] = _WORN | {"@DRAPE_OFF", "@DRAPE_ELBOW", "@DRAPE_ONE_SHOULDER", "@DRAPE_ARMS"}
_M_OUT = {"@DRAPE_M_OPEN", "@DRAPE_M_OPEN_COAT", "@DRAPE_M_COLLAR_UP", "@DRAPE_M_BELTED"}
_M_TOP = {"@DRAPE_M_CUFF", "@DRAPE_M_TUCKED", "@DRAPE_M_HALF", "@DRAPE_M_UNBUTTONED", "@DRAPE_M_OVERSIZE", "@DRAPE_M_COLLAR_POPPED"}
for _gk in ("coat_m", "winter_m"):
    DRAPE_GARMENT[_gk] = _WORN | _M_OUT | {"@DRAPE_M_SCARF_WRAP"}
for _gk in ("leather_m", "raincoat_m", "labcoat_m", "school_m", "suit_m", "tuxedo_m"):
    DRAPE_GARMENT[_gk] = _WORN | _M_OUT | {"@DRAPE_M_CUFF", "@DRAPE_M_UNBUTTONED", "@DRAPE_M_COLLAR_POPPED"}
for _gk in ("casual_m", "hoodie_m", "tracksuit_m", "uniform_m", "vest_m"):
    DRAPE_GARMENT[_gk] = _WORN | _M_TOP

RULES_DOC = [
    "身份：正向必须包含 @ID（或含身份锁的等价文本）",
    "服装：@OUT_SLIP 与 @OUT_GENERIC 不能同时出现",
    "型态：@DRAPE_* 必须与服装套装匹配（slip 用半脱系；initial/school/gym 用穿好系；gala/yukata/smock 可半脱）",
    "负向：必须含 @NEG_BASE；若有手部动作，建议加 @NEG_HAND_ART",
    "场景：场景块权重 > 1.15 时会被服装吃掉，建议同时加强服装或加 @NEG_FABRIC",
]


def role_of(token):
    for pre, role in ROLE_BY_PREFIX:
        if token.startswith(pre):
            return role
    return "misc"


def validate(pos_blocks, neg_blocks, view=""):
    """pos/neg: [{"token": "@ID", "weight": 1.0, "text": ""}]"""
    errors, warnings, hints = [], [], []

    def _norm(blocks):
        out = []
        for b in blocks:
            if b.get("enabled", True) is False:
                continue
            t = str(b.get("token") or "")
            if t:
                t = _prompts.resolve_token(t)[0]
            out.append((t, float(b.get("weight") or 1.0), b.get("text") or ""))
        return out

    pos, neg = _norm(pos_blocks), _norm(neg_blocks)
    pos_tokens = [t for t, _, _ in pos if t]
    roles = {}
    for t, w, _ in pos:
        if t:
            roles.setdefault(role_of(t), []).append((t, w))

    # ① 身份
    ID_WORDS = ("white hair", "silver hair", "two-tone eyes", "long hair ornament")
    # 身份积木：@ID_F / @ID_MALE / @ID_SOFT… 与 @SINGLE / @SINGLE_M 都算
    has_id = bool(view) or any(t.startswith(("@ID", "@SINGLE")) for t in pos_tokens) or any(
        any(w in (x or "").lower() for w in ID_WORDS) for _, _, x in pos)
    if not has_id:
        errors.append({"code": "NO_IDENTITY", "msg": "缺身份锁 @ID，人物会漂",
                       "fix": "把身份积木（@ID_F / @ID_M_KAI 之类）拖进正向，权重 1.0"})

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


    # ⑥ 构图声明冲突：@SINGLE 自带“填满画面”，再叠广角会把镜头推远
    WIDE_CAMS = {"@CAM_FULL", "@CAM_MEDIUM"}
    has_single = any(t in ("@SINGLE", "@SINGLE_F", "@SINGLE_M") for t in pos_tokens)
    if has_single and any(t in WIDE_CAMS for t in pos_tokens):
        warnings.append({"code": "FRAMING_CONFLICT",
                         "msg": "@SINGLE 与 @CAM_FULL/@CAM_MEDIUM 打架，容易出“空房间 + 小人”",
                         "fix": "去掉广角机位，或改用 @CAM_BUST / @CAM_CLOSEUP"})
    if has_single and any(t.startswith("@SET_") for t in pos_tokens) and "@CAM_THREEQ" in pos_tokens:
        warnings.append({"code": "FRAMING_SCENE_CONFLICT",
                         "msg": "有场景时 @SINGLE + @CAM_THREEQ 会拉远，场景压过人物",
                         "fix": "去掉 @CAM_THREEQ，或用 @CAM_BUST"})

    # ⑦ 场景过长：稀释角色细节
    scene_len = 0
    try:
        from prompts import load_tokens as _lt
        _tokens, _lib, _ = _lt()
        for t, _, _ in pos:
            if t.startswith("@SET_"):
                scene_len = max(scene_len, len(_tokens.get(t, "")))
    except Exception:
        scene_len = 0
    if scene_len > 380:
        hints.append({"code": "SCENE_HEAVY",
                      "msg": "场景描述 %d 字，明显偏长" % scene_len,
                      "fix": "搭配 @CAM_BUST/@CAM_CLOSEUP，或删掉场景里最远的元素"})

    # ⑦b 场景 × 机位
    NEAR = {"@CAM_CLOSEUP", "@CAM_BUST", "@CAM_PROFILE", "@CAM_HIP", "@CAM_EXTREME_CU"}
    WIDE = {"@CAM_FULL", "@CAM_FULL_WIDE", "@CAM_ESTABLISH", "@CAM_MEDIUM", "@CAM_BACKSIDE"}
    cams = [t for t in pos_tokens if t.startswith("@CAM_")]
    large_scene = any(t.startswith("@SET_") and t not in SMALL_SCENES and t not in MEDIUM_SCENES for t in pos_tokens)
    if (large_scene or scene_len > 380) and any(c in NEAR for c in cams):
        hints.append({"code": "SCENE_CAM_MISMATCH",
                      "msg": "大场景配近景，背景空间容易被裁掉",
                      "fix": "换成 @CAM_MEDIUM / @CAM_FULL，或改用小场景"})
    small_scene = any(t in SMALL_SCENES for t in pos_tokens)
    if small_scene and any(c in WIDE for c in cams):
        hints.append({"code": "SCENE_CAM_MISMATCH",
                      "msg": "小场景配远景，空间会撑不住",
                      "fix": "换成 @CAM_BUST / @CAM_CLOSEUP"})

    # ⑧ 洗白光型
    for t, _, _ in pos:
        if t.startswith("@LIGHT_"):
            pass
    flat_words = ("gentle contrast", "soft grey daylight", "gradual shadow falloff", "flat lighting")
    for t, _, x in pos:
        low = (x or "").lower()
        if any(w in low for w in flat_words):
            warnings.append({"code": "FLAT_LIGHT",
                             "msg": "自定义光描述里有降对比词（%s），画面会发灰" % (t or "文本块"),
                             "fix": "改成 directional light / crisp shadow edge / clear contrast"})
            break

    # ⑤ 手部动作提示
    if "hand" in roles and not any(t == "@NEG_HAND_ART" for t, _, _ in neg):
        hints.append({"code": "HAND_NO_GUARD", "msg": "有手部动作但没加 @NEG_HAND_ART",
                      "fix": "加一块 @NEG_HAND_ART 防多指"})

    # ⑥ 场景强度 vs 服装
    scene_w = max([w for t, w in roles.get("scene", [])] or [0])
    if scene_w > 1.15 and "@OUT_GENERIC" in pos_tokens:
        hints.append({"code": "SCENE_EATS_GARMENT",
                      "msg": "场景权重 %.2f，初始服装有被吃掉的风险（实测出现过白裙漂移）" % scene_w,
                      "fix": "把场景压到 1.1 以下，或加 @NEG_FABRIC + 加强 @OUT_GENERIC 权重"})

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
                      "fix": "加一块 @GAZE_ASIDE / @GAZE_SIDE_GLANCE / @GAZE_DOWN"})

    # ⑨ 提示板新规则（2026-11-16），共用 ref/prompts.py 的词库与性别判定
    try:
        _tk2, _notes2, _meta_all, _lib2, _ch2 = _prompts.load_full_catalog()
    except Exception:
        _tk2, _meta_all = {}, {}

    def _gender2(t):
        return _prompts.token_gender(t, _meta_all)

    camera_toks = [t for t in pos_tokens if t.startswith("@CAM_")]
    light_toks = [t for t in pos_tokens if t.startswith("@LIGHT_")]
    set_toks = [t for t in pos_tokens if t.startswith("@SET_")]
    if len(camera_toks) > 1:
        errors.append({"code": "MULTI_CAM", "msg": "同时有 %d 个机位积木，只会生效一个" % len(camera_toks),
                       "fix": "只留一个机位"})
    if len(light_toks) > 1:
        warnings.append({"code": "MULTI_LIGHT", "msg": "同时有 %d 个光位积木，光会打架" % len(light_toks),
                         "fix": "只留一个主光"})
    if len(set_toks) > 1:
        errors.append({"code": "MULTI_SET", "msg": "同时有 %d 个场景块" % len(set_toks),
                       "fix": "只留一个场景"})
    if any(t.startswith("@STYLE_") for t in pos_tokens) and set_toks:
        warnings.append({"code": "STYLE_SET_CONFLICT", "msg": "@STYLE_ 会把场景压成白底",
                         "fix": "场景图里去掉 @STYLE_"})

    id_genders = {_gender2(t) for t in pos_tokens if t.startswith(("@ID", "@SINGLE"))} - {""}
    if len(id_genders) > 1:
        errors.append({"code": "GENDER_MIX", "msg": "男女身份积木同时出现", "fix": "只留当前性别的身份块"})
    elif id_genders:
        _g = next(iter(id_genders))
        bad_out = [t for t in pos_tokens if t.startswith("@OUT_") and _gender2(t) and _gender2(t) != _g]
        if bad_out:
            errors.append({"code": "GENDER_OUTFIT", "msg": "服装性别与身份不一致：" + "、".join(bad_out),
                           "fix": "换回同性别服装"})

    _v = (view or "").upper()
    if _v.endswith("_BACK") or _v.endswith("_TQ_BACK") or _v.endswith("_BACKSIDE"):
        if "@LIGHT_WIN" in pos_tokens:
            warnings.append({"code": "BACK_FRONT_LIGHT", "msg": "背影用了正面光 @LIGHT_WIN",
                             "fix": "换成 @LIGHT_WIN_BACK"})
        if any(re.search(r"\beye\b|two-tone eyes|\bfringe\b|blush", x or "", re.I) for _t, _w, x in pos):
            warnings.append({"code": "BACK_FACE_WORDS", "msg": "背影块里还有脸/眼词，容易转正面",
                             "fix": "删掉眼睛/脸相关描述"})

    unknown = []
    for _t in pos_tokens + [t for t, _w, _x in neg if t]:
        if _t in _tk2:
            continue
        if _prompts.resolve_token(_t)[0] in _tk2:
            continue
        unknown.append(_t)
    if unknown:
        errors.append({"code": "UNKNOWN_TOKEN", "msg": "词库里没有：" + "、".join(sorted(set(unknown))[:6]),
                       "fix": "删掉或换成库里的积木"})

    misplaced = [t for t in [x for x, _w, _x in neg if x]
                 if not t.startswith(("@NEG_", "@CROP_", "@STRIP_"))]
    if misplaced:
        errors.append({"code": "NEG_POS_MIX", "msg": "正向积木被放进负向：" + "、".join(misplaced[:6]),
                       "fix": "把它拖回正向"})

    try:
        _est = sum(len(_tk2.get(t, "")) for t in pos_tokens) + sum(len(x) for _t, _w, x in pos if not _t)
        if _est > 1000:
            hints.append({"code": "PROMPT_LONG", "msg": "正向约 %d 字，后半段容易被忽略" % _est,
                          "fix": "压到 900 字以内：删重复的装饰与远景描述"})
    except Exception:
        pass

    return {"ok": not errors, "errors": errors, "warnings": warnings, "hints": hints,
            "stats": {"pos": len(pos), "neg": len(neg), "roles": {k: len(v) for k, v in roles.items()}}}


# —— 视角 / 眼睛一致性（角色专属视角块用）——
EYE_RED = r"\bred eye\b|\bred eyes\b"
EYE_GREY = r"\bgrey eye\b|\bgray eye\b|\bgrey eyes\b|\bgray eyes\b"
EYE_ANY = r"\beye\b|\beyes\b|two-tone eyes|\bfringe\b|\bblush\b|\bsmile\b|\blips\b|\bface\b"


def check_view(text, view):
    """按视角块名检查眼睛/脸词是否矛盾。view 形如 @MIO_SIDE_R。"""
    import re
    v = (view or "").upper()
    errs = []
    has_red = bool(re.search(EYE_RED, text, re.I))
    has_grey = bool(re.search(EYE_GREY, text, re.I))
    has_eye = bool(re.search(EYE_ANY, text, re.I))
    if v.endswith("_BACK"):
        if has_eye:
            errs.append({"code": "EYES_IN_BACK", "msg": "背影块里出现脸/眼词，会把她转正面"})
    elif v.endswith("_SIDE_R"):
        if has_red:
            errs.append({"code": "EYE_COLOR_MISMATCH", "msg": "面朝画面右却写了红眼（红眼在画面左）"})
        if not has_grey:
            errs.append({"code": "EYE_MISSING", "msg": "面朝画面右应出现 grey eye"})
    elif v.endswith("_SIDE_L"):
        if has_grey:
            errs.append({"code": "EYE_COLOR_MISMATCH", "msg": "面朝画面左却写了灰眼（灰眼在画面右）"})
        if not has_red:
            errs.append({"code": "EYE_MISSING", "msg": "面朝画面左应出现 red eye"})
    elif v.endswith("_GLANCE_R"):
        if has_red:
            errs.append({"code": "EYE_COLOR_MISMATCH", "msg": "从右肩回眸应写 grey eye"})
    elif v.endswith("_GLANCE_L"):
        if has_grey:
            errs.append({"code": "EYE_COLOR_MISMATCH", "msg": "从左肩回眸应写 red eye"})
    return errs


STRUCT_NOUNS = ("ladder", "bookcase", "bookshelf", "table", "chair", "shelf")
CONTACT = ("on", "against", "in", "at", "resting", "leaning", "hanging", "standing", "beside", "under")


def check_props(text, window=10):
    """结构物件附近没有接触/位置词 → 悬空风险。"""
    import re
    words = re.findall(r"[a-z]+", (text or "").lower())
    errs = []
    for i, w in enumerate(words):
        if w in STRUCT_NOUNS:
            seg = words[max(0, i - window): i + window]
            if not any(c in seg for c in CONTACT):
                errs.append({"code": "PROP_NO_CONTACT", "msg": "%s 附近没有接触/位置词，可能悬空" % w})
    return errs
