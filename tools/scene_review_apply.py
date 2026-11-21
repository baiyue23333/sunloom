# -*- coding: utf-8 -*-
"""应用复核结果：把 review*_out.json 里的 fixed 写回 prompt_lib，再跑审计。"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "ref", "scene_batches")
LIB = os.path.join(ROOT, "ref", "prompt_lib.json")


def main():
    fixes = {}
    for i in (1, 2):
        p = os.path.join(DIR, "review%d_out.json" % i)
        if os.path.isfile(p):
            d = json.load(open(p, encoding="utf-8"))
            for k, v in d.items():
                if isinstance(v, dict) and v.get("fixed"):
                    fixes[k] = v["fixed"].strip()
    lib = json.load(open(LIB, encoding="utf-8"))
    tok = lib["tokens"]
    applied = 0
    for k, text in fixes.items():
        if k in tok:
            tok[k] = text
            applied += 1
    json.dump(lib, open(LIB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("复核修正写入:", applied, "/", len(fixes))
    for k, v in list(fixes.items())[:5]:
        print(" ", k, "->", v[:80])


if __name__ == "__main__":
    main()
