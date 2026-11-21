# -*- coding: utf-8 -*-
"""把全部 @SET_* 场景宏升级成新格式：结构锚点 + 明确数量 + 接触声明 + 室内加门。

原宏备份到 ref/scene_blocks_legacy.json
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "ref", "prompt_lib.json")
LEGACY = os.path.join(ROOT, "ref", "scene_blocks_legacy.json")

INDOOR = ("inside", "indoor", "room", "hall", "cafe", "store", "library", "classroom",
          "corridor", "gym", "office", "lobby", "theatre", "arcade", "subway", "elevator",
          "bathroom", "bedroom", "kitchen", "laundry", "museum", "mall", "aquarium",
          "cafeteria", "stage", "studio", "greenhouse", "temple", "castle", "onsen")
MULTI = {"rows": "two rows of", "row": "one row of", "stacks": "two stacks of",
         "stack": "one stack of", "pairs": "two pairs of", "crowd": "a crowd of"}


def clauses(text):
    out = []
    for m in re.finditer(r"\(([^():]+?):([0-9.]+)\)", text):
        out.append((m.group(1).strip(), float(m.group(2))))
    if not out:
        for part in re.split(r",\s*", text):
            p = part.strip("() ")
            if p:
                out.append((p, 1.0))
    return out


def normalize(clause):
    low = clause.lower()
    for k, v in MULTI.items():
        if low.startswith(k + " "):
            rest = clause[len(k):].strip()
            if rest.lower().startswith("of "):
                rest = rest[3:]
            return (v + " " + rest).strip(), True
    # 数字缺失的家具类，补 "one "
    furn = ("table", "chair", "desk", "lamp", "shelf", "bookshelf", "bookcase", "sofa",
            "bench", "counter", "cabinet", "stool", "crate", "rug", "plant")
    first = low.split()[0] if low.split() else ""
    if first in furn and first[0] not in "0123456789" and not low.startswith(("a ", "an ", "the ")):
        return "one " + clause, True
    return clause, False


def upgrade(text):
    cl = clauses(text)
    if not cl:
        return text, {"added": 0, "door": False}
    indoor = any(w in text.lower() for w in INDOOR)
    parts, added = [], 0
    for i, (c, w) in enumerate(cl):
        if i == 0:
            parts.append("(%s:%.2f)" % (c, w))
            continue
        nc, ch = normalize(c)
        added += 1 if ch else 0
        parts.append("(%s:%.2f)" % (nc, w))
    if indoor and "door" not in text.lower():
        parts.append("(a wooden door on a side wall:1.15)")
    return ", ".join(parts), {"added": added, "door": indoor}


def main():
    lib = json.load(open(LIB, encoding="utf-8"))
    tok = lib.get("tokens") or {}
    legacy = {}
    n_door = n_add = 0
    samples = []
    for k in list(tok):
        if not k.startswith("@SET_"):
            continue
        old = tok[k]
        legacy[k] = old
        new, meta = upgrade(old)
        if new != old:
            tok[k] = new
            n_door += 1 if meta["door"] else 0
            n_add += meta["added"]
            if len(samples) < 3:
                samples.append((k, old[:150], new[:220]))
    json.dump(legacy, open(LEGACY, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(lib, open(LIB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("升级场景 %d 个 | 加门 %d 个 | 补数量 %d 处" % (len(legacy), n_door, n_add))
    for k, o, n in samples:
        print("\n==", k)
        print(" 旧:", o)
        print(" 新:", n)


if __name__ == "__main__":
    main()
