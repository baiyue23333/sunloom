# -*- coding: utf-8 -*-
"""分类光引导（纯规则，不依赖任何语言模型）。

输入当前积木（正向/负向/合作泳道），输出：
  covered  每个大类的覆盖情况
  roles    应该点亮的分类（按当前模式优先级排序）
  tips     每个缺失分类的建议积木（从词库挑，最多 3 个）
  ready    当前模式的主分类是否齐了
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "ref", "prompt_lib.json")

CATS = ["id", "body", "face", "cam", "light", "time", "set", "outfit", "pose", "mood", "gaze", "comp", "neg"]
LABELS = {"id": "身份", "body": "体型", "face": "脸型", "cam": "机位", "light": "打光", "time": "时间",
          "set": "场景", "outfit": "服装", "pose": "姿势", "mood": "情绪", "gaze": "视线", "comp": "构图", "neg": "负向"}
PRIORITY = {
    "free": CATS,
    "portrait": ["face", "gaze", "cam", "light", "mood", "body", "comp", "outfit", "id", "set", "time", "pose", "neg"],
    "scene": ["set", "time", "light", "comp", "cam", "mood", "pose", "outfit", "id", "body", "face", "gaze", "neg"],
    "story": ["pose", "mood", "gaze", "comp", "cam", "set", "light", "outfit", "face", "body", "id", "time", "neg"],
}
# 每类的候选（按常用度），只保留词库里存在的
CANDIDATES = {
    "id": ["@ID_F", "@ID_F_AYA", "@ID_F_RIN", "@ID_F_YUKI", "@ID_F_NANA", "@ID_M_KAI", "@ID_M_REN", "@ID_M_SHUN"],
    "body": ["@BODY_F", "@BODY_F_SLIM", "@BODY_F_SOFT", "@BODY_M_SLIM", "@BODY_M_ATHLETIC"],
    "face": ["@FACE_F", "@FACE_F_SOFT", "@FACE_F_SHARP", "@FACE_F_COOL", "@FACE_M", "@FACE_M_SHARP"],
    "cam": ["@CAM_MEDIUM", "@CAM_BUST", "@CAM_FULL", "@CAM_THREEQ", "@CAM_COWBOY", "@CAM_KNEE", "@CAM_HIGH"],
    "light": ["@LIGHT_WIN", "@LIGHT_GOLDEN", "@LIGHT_SOFT", "@LIGHT_NIGHT", "@LIGHT_CANDLE", "@LIGHT_BACK", "@LIGHT_SPLIT"],
    "time": ["@TIME_AFTERNOON", "@TIME_DUSK", "@TIME_TWILIGHT", "@TIME_NIGHT", "@TIME_MORNING"],
    "set": ["@SET_LIBRARY", "@SET_CAFE", "@SET_BEDROOM", "@SET_CLASSROOM", "@SET_GREENHOUSE", "@SET_ALLEY"],
    "outfit": ["@OUT_CASUAL_KNIT", "@OUT_SCHOOL", "@OUT_SLIP", "@OUT_HOODIE_CASUAL", "@OUT_WINTER"],
    "pose": ["@POSE_F_STAND", "@POSE_F_SIT", "@POSE_F_LEAN", "@POSE_F_WALK", "@POSE_F_LOOK_BACK", "@POSE_M_SIT_BENCH"],
    "mood": ["@MOOD_CALM", "@MOOD_TENDER", "@MOOD_SHY", "@MOOD_AMUSED", "@MOOD_FOCUSED"],
    "gaze": ["@GAZE_CAMERA", "@GAZE_ASIDE", "@GAZE_DOWN", "@GAZE_WINDOW", "@GAZE_FAR"],
    "comp": ["@COMP_CENTER", "@COMP_THIRDS", "@COMP_FIGURE_EDGE", "@COMP_FIGURE_BOTTOM", "@COMP_MACRO"],
    "neg": ["@NEG_BASE", "@NEG_ANATOMY", "@NEG_HAND_ART", "@NEG_LETTERBOX"],
}
PREFIX = {"id": ("@ID", "@SINGLE"), "body": ("@BODY_",), "face": ("@FACE_",), "cam": ("@CAM_",),
          "light": ("@LIGHT_",), "time": ("@TIME_",), "set": ("@SET_",), "outfit": ("@OUT_", "@OUTFIT"),
          "pose": ("@POSE_",), "mood": ("@MOOD_",), "gaze": ("@GAZE_",), "comp": ("@COMP_",),
          "neg": ("@NEG_BASE",)}


def _tokens():
    try:
        lib = json.load(open(LIB, encoding="utf-8"))
        return set((lib.get("tokens") or {}).keys())
    except Exception:
        return set()


def _block_tokens(blocks):
    out = []
    for b in blocks or []:
        t = str((b or {}).get("token") or "").strip()
        if t:
            out.append(t)
    return out


def _has_text(blocks, words):
    import re
    pat = re.compile("|".join(words), re.I)
    return any(not (b or {}).get("token") and pat.search(str((b or {}).get("text") or "")) for b in blocks or [])


def analyze(blocks, negatives=None, mode="free"):
    """返回 {mode, covered, missing, roles, tips, ready, summary}。"""
    lib = _tokens()
    pos = list(blocks or [])
    neg = list(negatives or [])
    pos_t = _block_tokens(pos)
    neg_t = _block_tokens(neg)

    def has_any(prefixes):
        return any(t.startswith(prefixes) for t in pos_t)

    covered = {c: has_any(PREFIX[c]) for c in CATS if c != "neg"}
    covered["neg"] = any(t.startswith(("@NEG_BASE",)) for t in neg_t)
    # 文本兜底：弱身份/散文也能算
    if not covered["id"]:
        covered["id"] = _has_text(pos, ["silver hair", "two-tone eyes", "long hair ornament"])
    if not covered["light"]:
        covered["light"] = _has_text(pos, ["window light", "sunlight", "backlight", "golden hour"])
    if not covered["set"]:
        covered["set"] = _has_text(pos, ["room", "street", "indoor", "outdoor", "background"])
    missing = [c for c in CATS if not covered[c]]
    order = PRIORITY.get(mode) or CATS
    roles = [c for c in order if c in missing][:4]

    tips = {}
    for c in missing:
        cands = [t for t in CANDIDATES.get(c, []) if not lib or t in lib]
        tips[c] = [t for t in cands if t not in pos_t][:3]

    prio = PRIORITY.get(mode) or []
    ready = bool(prio) and all(covered.get(c) for c in prio)
    if ready:
        summary = "主分类齐了，可以出图"
    else:
        first = roles[:2]
        summary = "还缺：" + "、".join(LABELS[c] for c in first) if first else "已经够齐了"
    return {"mode": mode, "covered": covered, "missing": missing, "roles": roles,
            "tips": tips, "ready": ready, "summary": summary}


if __name__ == "__main__":
    import sys
    data = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    print(json.dumps(analyze(data.get("blocks") or [], data.get("negatives") or [],
                              data.get("mode") or "free"), ensure_ascii=False, indent=1))
