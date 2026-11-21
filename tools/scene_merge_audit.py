# -*- coding: utf-8 -*-
"""合并三批场景重写并审计。"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "ref", "scene_batches")
LIB = os.path.join(ROOT, "ref", "prompt_lib.json")

NUM = re.compile(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b", re.I)
PERSON = re.compile(r"\b(girl|women|woman|she|her|boy|people|person|crowd|hand)\b", re.I)
CONTACT = ("on the floor", "on the table", "against the wall", "tucked under", "standing on",
           "resting on", "leaning against", "on the wall", "on the counter", "on the ground",
           "on the shelf", "at the table", "beside", "in the corner", "set into", "fixed to",
           "on the desk", "on the bed", "on the stand", "at the counter", "in the",
           "along", "between", "under", "across", "over", "on the water", "on the quay",
           "on the tiles", "on the sand", "in the sand", "at the corner")
INDOOR_RE = re.compile(r"\b(room|hall|cafe|store|library|classroom|corridor|gym|office|"
                       r"lobby|theatre|arcade|subway|elevator|bathroom|bedroom|kitchen|"
                       r"museum|aquarium|cafeteria|bookstore|concourse|studio|greenhouse|"
                       r"temple|castle|onsen|laundromat)\b|\binside\b", re.I)


def strip_clauses(text):
    return re.sub(r"\([^():]*:[0-9.]+\)", " ", text)


def main(apply=False):
    out = {}
    for i in (1, 2, 3):
        p = os.path.join(DIR, "batch%d_out.json" % i)
        if os.path.isfile(p):
            out.update(json.load(open(p, encoding="utf-8")))
    lib = json.load(open(LIB, encoding="utf-8"))
    tok = lib["tokens"]
    keys = [k for k in tok if k.startswith("@SET_")]
    print("合并 %d 条 | 场景总数 %d" % (len(out), len(keys)))

    prob = {"missing": [], "no_num": [], "no_contact": [], "person": [], "short": [], "long": [],
            "door_missing": [], "door_extra": []}
    for k in keys:
        new = out.get(k)
        if not new:
            prob["missing"].append(k)
            continue
        new = new.strip()
        low = new.lower()
        n_num = len(NUM.findall(new))
        if n_num < 3:
            prob["no_num"].append((k, n_num))
        if not any(c in low for c in CONTACT):
            prob["no_contact"].append(k)
        if PERSON.search(strip_clauses(new)):
            prob["person"].append(k)
        if len(new) < 200:
            prob["short"].append((k, len(new)))
        if len(new) > 460:
            prob["long"].append((k, len(new)))
        head = ", ".join(low.split("), ")[:3]) + "),"
        OUT_RE = re.compile(r"\b(street|intersection|outdoor|open-air|beach|forest|park|field|"
                            r"road|bridge|platform|rooftop|balcony|alley|harbour|quay|desert|"
                            r"snowfield|riverbank|garden|yard)\b", re.I)
        indoor = bool(re.search(r"\binside\b", head)) or (
            bool(INDOOR_RE.search(head)) and not OUT_RE.search(head))
        if indoor and "door on a side wall" not in low:
            prob["door_missing"].append(k)
        if (not indoor) and "door on a side wall" in low:
            prob["door_extra"].append(k)

    for name, v in prob.items():
        if v:
            print("%-12s %2d %s" % (name, len(v), v[:6]))
    bad = sum(len(v) for v in prob.values())
    print("不合格项合计:", bad)
    if apply and bad == 0:
        for k, v in out.items():
            tok[k] = v.strip()
        json.dump(lib, open(LIB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("已写入 prompt_lib.json")
    elif apply:
        print("有不合格项，未写入")
    return prob


if __name__ == "__main__":
    main("--apply" in sys.argv)
