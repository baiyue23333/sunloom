# -*- coding: utf-8 -*-
"""把现有 @SET_* 场景宏转成 schema 草案（结构可编辑，不丢原文）。

每套场景拆三层：
  locked  —— 结构：物件 + 数量 + 位置（权重照搬宏）
  free    —— 留给模型发挥：光、天气、配色、小道具
  forbidden—— 禁止项：悬空、堵动线、数量错
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "ref", "prompt_lib.json")
OUT = os.path.join(ROOT, "ref", "scene_schema.json")

WHERE_WORDS = ("along the wall", "around her", "beside her", "behind her", "in front of her",
               "overhead", "on the floor", "on the wall", "past the frame", "under her",
               "at her waist", "to the horizon", "in the foreground", "in the background",
               "receding into the distance")
PLURAL_HINTS = re.compile(r"\b(rows?|stacks?|pairs?|shelves|desks|chairs|lamps|windows|cabinets)\b", re.I)
GLOBAL_FORBIDDEN = ["floating objects", "objects clipping through walls", "empty foreground blocking the aisle"]


def clauses(text):
    out = []
    for m in re.finditer(r"\(([^():]+?):([0-9.]+)\)", text):
        out.append({"text": m.group(1).strip(), "weight": float(m.group(2))})
    if not out:
        for part in re.split(r",\s*", text):
            p = part.strip("() ")
            if p:
                out.append({"text": p, "weight": 1.0})
    return out


def where_of(t):
    low = t.lower()
    for w in WHERE_WORDS:
        if w in low:
            return w
    m = re.search(r"\b(on|at|in|under|beside|behind|along|around|above|below)\s+(the\s+)?([a-z ]{3,20})", low)
    return m.group(0) if m else ""


def convert(tokens):
    out = {}
    for k, v in tokens.items():
        if not k.startswith("@SET_"):
            continue
        name = k[5:].lower()
        cl = clauses(v)
        locked, review = [], []
        for c in cl:
            t = c["text"]
            plural = bool(PLURAL_HINTS.search(t))
            item = {
                "item": t,
                "count": 1,
                "count_hint": 2 if plural else 1,
                "weight": c["weight"],
                "where": where_of(t),
            }
            locked.append(item)
            if plural or not item["where"]:
                review.append(t[:60])
        out[name] = {
            "auto": True,
            "source_token": k,
            "locked": locked,
            "free": ["light quality", "weather and time", "color palette", "one small prop of the model's choice"],
            "circulation": "",
            "forbidden": list(GLOBAL_FORBIDDEN),
            "needs_review": review,
        }
    return out


def main():
    lib = json.load(open(LIB, encoding="utf-8"))
    sch = convert(lib.get("tokens") or {})
    json.dump(sch, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n = len(sch)
    locked = sum(len(v["locked"]) for v in sch.values())
    review = sum(len(v["needs_review"]) for v in sch.values())
    print("场景数 %d | 锁定条款 %d | 待人工确认 %d" % (n, locked, review))
    for name in list(sch)[:2]:
        print("\n==", name, json.dumps(sch[name]["locked"][:3], ensure_ascii=False))


if __name__ == "__main__":
    main()
