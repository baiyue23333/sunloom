# -*- coding: utf-8 -*-
"""给积木补分类（meta.subgroups）：把 token 归到面板分类，并按前缀给子分类。

  python tools/classify_blocks.py            # 预演
  python tools/classify_blocks.py --apply    # 写回 ref/prompt_lib.json

规则与前端 tokenCat() 保持一致；新增积木跑一次即可归位。
"""
import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "ref", "prompt_lib.json")

# 顺序有意义：先匹配到的胜出（与 app.js tokenCat 的 map 对应）
RULES = [
    ("@NEG", "neg"), ("@DRAPE", "drape"), ("@OUT", "outfit"), ("@MOOD", "mood"),
    ("@POSE", "pose"), ("@HOLD", "hold"), ("@WEAPON", "weapon"), ("@GAZE", "gaze"),
    ("@HAND", "hand"), ("@HAIR", "hair"), ("@FAB", "fabric"), ("@ATMO", "atmo"),
    ("@TIME", "time"), ("@SET", "set"), ("@PROP", "prop"), ("@COMP", "comp"),
    ("@STYLE", "style"), ("@CAM", "cam"), ("@LIGHT", "light"),
    ("@OBJ", "prop"), ("@INSTR", "prop"), ("@RIDE", "prop"), ("@ROLE", "prop"),
    ("@STRIP", "neg"), ("@WEATHER", "atmo"), ("@SEASON", "time"),
    ("@BODY", "body"), ("@FACE", "face"), ("@MAKEUP", "face"), ("@SKIN", "face"),
    ("@PIN", "acc"), ("@CLIP", "acc"), ("@BERET", "acc"), ("@HEADBAND", "acc"),
    ("@RIBBON", "acc"), ("@FLOWER_CROWN", "acc"), ("@HAIRPIN", "acc"),
    ("@MINI", "acc"), ("@FX", "style"), ("@CROP", "comp"), ("@BARE", "body"),
    ("@BG", "comp"), ("@HOSE", "outfit"), ("@NSFW", "nsfw"), ("@ID", "id"),
    ("@SINGLE", "id"), ("@ACC", "acc"),
]
NSFW = {"@MOOD_SMOKE", "@MOOD_ALCOHOL", "@MOOD_TIRED", "@MOOD_COLD", "@STYLE_NOIR",
        "@STYLE_GRAIN", "@MAKEUP_SICK", "@NEG_NSFW",
        "@NSFW_SULTRY", "@NSFW_WET_SKIN", "@NSFW_SILK_SLIP"}

# 场景规模：给 set 类再挂一个子分类
SMALL = {"@SET_BOOKSTORE", "@SET_PIANO", "@SET_LAUNDRY", "@SET_KITCHEN", "@SET_BATHROOM",
         "@SET_BEDROOM", "@SET_LIBRARY", "@SET_CAFE", "@SET_ARTROOM", "@SET_ELEVATOR",
         "@SET_BALCONY", "@SET_FLOWER_SHOP", "@SET_PARKING", "@SET_ALLEY",
         "@SET_CONVENIENCE", "@SET_TEA_HOUSE", "@SET_IZAKAYA", "@SET_RECORD_SHOP",
         "@SET_MUSIC_STUDIO", "@SET_BOOK_CAFE"}
MEDIUM = {"@SET_GREENHOUSE", "@SET_CORRIDOR", "@SET_CLASSROOM", "@SET_SHRINE", "@SET_TRAM",
          "@SET_SUBWAY", "@SET_ARCADE", "@SET_MARKET", "@SET_ONSEN", "@SET_SCHOOL_GATE",
          "@SET_ROOFTOP", "@SET_ROOFTOP_GARDEN", "@SET_PARK", "@SET_RIVERBANK",
          "@SET_CONSTRUCTION", "@SET_CITY_STREET", "@SET_GARDEN_PEONY",
          "@SET_BOTANICAL_BRIDGE", "@SET_TRAIN_CROSSING", "@SET_SHOPPING_ARCADE",
          "@SET_ROOFTOP_POOL", "@SET_GARDEN_COTTAGE", "@SET_UNDERPASS",
          "@SET_METRO_PLATFORM", "@SET_BAMBOO_GROVE", "@SET_ROOFTOP_BILLBOARD",
          "@SET_FERRY_DECK"}


def cat_of(name):
    n = name.upper()
    if n in NSFW:
        return "nsfw"
    for pre, cat in RULES:
        if n.startswith(pre):
            return cat
    if n in ("@ID", "@SINGLE", "@SINGLE_M"):
        return "id"
    return "custom"


def sub_of(name, cat):
    if cat == "set":
        if name in SMALL:
            return "set_small"
        if name in MEDIUM:
            return "set_medium"
        return "set_large"
    return cat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    d = json.load(open(LIB, encoding="utf-8"))
    tokens = d.get("tokens") or {}
    meta = d.setdefault("meta", {})
    subs = meta.setdefault("subgroups", {})
    changed = 0
    stat = {}
    for name in tokens:
        cat = cat_of(name)
        want = sub_of(name, cat)
        if subs.get(name) != want:
            subs[name] = want
            changed += 1
        stat[want] = stat.get(want, 0) + 1
    print("积木 %d 个，本次调整 %d 条" % (len(tokens), changed))
    for k, v in sorted(stat.items(), key=lambda x: -x[1]):
        print("  %-12s %d" % (k, v))
    if a.apply and changed:
        json.dump(d, open(LIB, "w", encoding="utf-8"), ensure_ascii=False)
        print("已写回", LIB)
    elif changed:
        print("（预演，加 --apply 才写回）")


if __name__ == "__main__":
    main()
