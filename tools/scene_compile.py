# -*- coding: utf-8 -*-
"""schema → 场景提示词片段。

只输出 locked + circulation；free 层完全留白，交给模型。
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCH = os.path.join(ROOT, "ref", "scene_schema.json")
NUM = {1: "one", 2: "two", 3: "three", 4: "four"}


def load():
    return json.load(open(SCH, encoding="utf-8"))


def compile_scene(name):
    s = load().get(name)
    if not s:
        raise SystemExit("没有场景 schema: " + name)
    parts = []
    for it in s.get("locked") or []:
        n = int(it.get("count") or 1)
        num = NUM.get(n, str(n))
        txt = it["item"]
        if txt.lower().startswith(("a ", "an ", "the ", "inside", "on ", "in ", "at ", "under", "beside", "along")):
            num = ""
        where = it.get("where") or ""
        if where and where not in txt:
            txt = "%s %s" % (txt, where)
        head = (num + " ") if num else ""
        parts.append("(%s%s:%.2f)" % (head, txt, float(it.get("weight") or 1.2)))
    circ = s.get("circulation")
    if circ:
        parts.append("(%s:1.15)" % circ)
    forb = ", ".join(s.get("forbidden") or [])
    return ", ".join(parts), forb


if __name__ == "__main__":
    import sys
    t, f = compile_scene(sys.argv[1] if len(sys.argv) > 1 else "library")
    print(t)
    print("\nFORBIDDEN:", f)
