# -*- coding: utf-8 -*-
"""场景叙述与防穿模体检：支撑面、数量词、人物漏词、时令光影/前景视角越权检查。"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "ref", "prompt_lib.json")
FURN = ("table", "chair", "desk", "lamp", "bookcase", "bookshelf", "shelf", "ladder",
        "counter", "bed", "sofa", "bench", "cabinet", "stool", "rug", "plant", "crate",
        "piano", "easel", "machine", "vending", "pylon", "trunk", "barrel")
REL_RE = re.compile(r"\b(on|in|at|against|under|above|over|from|beside|along|between|within|across|into|behind|around|near|by|lining|covering|framing|filling)\b", re.I)
SUPPORT = ("on the floor", "on the ground", "against the wall", "against the bookcase",
           "against the counter", "against the back wall", "tucked under", "tucked at",
           "standing on", "resting on", "leaning against", "set into", "fixed to",
           "bolted to", "mounted on", "hung on", "in the corner", "on the table",
           "on the counter", "on the desk", "on the rug", "on the deck", "on the quay",
           "on the sidewalk", "on the lawn", "along the wall", "along the path",
           "at the table", "under the window", "beside", "in the water", "on the sand")
NUM_RE = re.compile(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b", re.I)
PERSON_RE = re.compile(r"\b(girl|women|woman|she|her|boy|people|person|crowd|hand)\b", re.I)
TIME_LIGHT_RE = re.compile(
    r"\b(morning|afternoon|evening|night|dusk|dawn|noon|last light|winter|summer|autumn)\b|"
    r"\b(daylight|sunlight|sunbeams|harsh sun|low sun|raking|overcast|deep blue sky|fading to amber|fine rain|wind lifting)\b",
    re.I,
)
CAM_LEAK_RE = re.compile(r"\b(foreground|seen from|left wall|right wall|on the left|on the right|empty)\b", re.I)


def audit_scenes():
    """检查全库 @SET_* 场景叙述质量；返回 {bad_support, bad_narr}。"""
    tok = json.load(open(LIB, encoding="utf-8"))["tokens"]
    keys = sorted(k for k in tok if k.startswith("@SET_"))
    bad_support, bad_narr = [], []
    for k in keys:
        text = re.sub(r"\(([^():]*):[0-9.]+\)", r"\1", tok[k])
        for clause in [c.strip() for c in text.split(",") if c.strip()]:
            low = clause.lower()
            if any(f in low for f in FURN) and not any(s in low for s in SUPPORT) and not REL_RE.search(low):
                bad_support.append((k, clause[:70]))
        if len(NUM_RE.findall(text)) < 3:
            bad_narr.append((k, "count<3"))
        if PERSON_RE.search(text):
            bad_narr.append((k, "person:" + ",".join(PERSON_RE.findall(text))))
        if TIME_LIGHT_RE.search(text):
            bad_narr.append((k, "time_light:" + ",".join(TIME_LIGHT_RE.findall(text)[0])))
        if CAM_LEAK_RE.search(text):
            bad_narr.append((k, "cam_leak:" + ",".join(CAM_LEAK_RE.findall(text))))
    return {"count": len(keys), "bad_support": bad_support, "bad_narr": bad_narr}


def main():
    r = audit_scenes()
    print("场景: %d | 缺支撑面的家具子句: %d | 叙述冲突: %d" % (r["count"], len(r["bad_support"]), len(r["bad_narr"])))
    for b in (r["bad_support"] + r["bad_narr"])[:12]:
        print(" ", b[0], "::", b[1])
    if r["bad_support"] or r["bad_narr"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
