# -*- coding: utf-8 -*-
"""给积木打性别 / 归属标记（prompt_lib.meta.gender / meta.owner）。

规则：
  男性：@ID_MALE*、@SINGLE_M、@BODY_MALE*、@FACE_MALE*、@HAIR_M_*、@FAB_M_*、
        @DRAPE_M_*、@POSE_M_*、@HAND_M_*、@ACC_M_*、@HOSE_M_*、@NEG_MALE_*
  女性：@ID_F*、@BODY_*（非 MALE）、@FACE_*（非 MALE）、@HAIR_*（非 M）、
        @HOSE_*、@MAKEUP_*、@SKIN_*、@SINGLE
  其余不写 = 中性（两种性别都可见）
归属：角色卡 tokens 里的身份/体型积木 → meta.owner = 卡名

用法：
    python tools/tag_gender.py            # 预演
    python tools/tag_gender.py --apply    # 写回
    python tools/tag_gender.py --force    # 已有标记也重算
"""
import glob
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "ref", "prompt_lib.json")
CARDS = os.path.join(ROOT, "ref", "cards")

MALE_PREFIX = ("@ID_M", "@SINGLE_M", "@BODY_M", "@FACE_M", "@HAIR_M_", "@FAB_M_",
               "@DRAPE_M_", "@POSE_M_", "@HAND_M_", "@ACC_M_", "@HOSE_M_", "@NEG_MALE_")
FEMALE_PREFIX = ("@ID_F", "@SINGLE_F", "@BODY_F_", "@FACE_F", "@HAIR_F_",
                 "@DRAPE_F_", "@POSE_F_", "@HAND_F_", "@ACC_F_", "@HOSE_",
                 "@MAKEUP_", "@SKIN_", "@NSFW_SILK_SLIP")


def gender_of(name):
    if name.startswith(MALE_PREFIX):
        return "m"
    if name == "@SINGLE" or name.startswith(FEMALE_PREFIX):
        return "f"
    return ""


def owners():
    out = {}
    for p in sorted(glob.glob(os.path.join(CARDS, "*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                card = json.load(f)
        except Exception:
            continue
        name = card.get("name") or os.path.basename(p)[:-5]
        for t in card.get("tokens") or []:
            if t.startswith(("@ID", "@BODY")):
                out[t] = name
    return out


def main():
    apply = "--apply" in sys.argv
    force = "--force" in sys.argv
    with open(LIB, encoding="utf-8") as f:
        lib = json.load(f)
    tokens = lib.get("tokens") or {}
    meta = lib.setdefault("meta", {})
    g = meta.setdefault("gender", {})
    own = meta.setdefault("owner", {})

    changed, skipped = 0, 0
    for t in tokens:
        want = gender_of(t)
        if not want:
            continue
        if g.get(t) and not force:
            skipped += 1
            continue
        if g.get(t) != want:
            g[t] = want
            changed += 1

    own_changed = 0
    for t, name in owners().items():
        if t in tokens and own.get(t) != name:
            own[t] = name
            own_changed += 1

    stat = {}
    for v in g.values():
        stat[v] = stat.get(v, 0) + 1
    print("性别标记：新增/修正 %d，已存在跳过 %d，当前 m=%d f=%d 中性=%d"
          % (changed, skipped, stat.get("m", 0), stat.get("f", 0), len(tokens) - len(g)))
    print("归属标记：%d 条 %s" % (own_changed or len(own), json.dumps(own, ensure_ascii=False)))

    if not apply:
        print("（预演，加 --apply 才写回）")
        return
    if changed or own_changed:
        with open(LIB, "w", encoding="utf-8") as f:
            json.dump(lib, f, ensure_ascii=False, indent=1)
        print("已写回 " + LIB)
    else:
        print("没有需要改的")


if __name__ == "__main__":
    main()
