# -*- coding: utf-8 -*-
"""物件盒校验器：给一组「物件:数量」，判定合法性与警告。

ERROR  : fixed 缺失 / 硬计数不符 / 互斥 / 特征种类不足
WARNING: range 越界 / linked_soft 比例偏离 / 中心区过挤
"""
import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOX = os.path.join(ROOT, "ref", "prop_box.json")


def load():
    return json.load(open(BOX, encoding="utf-8"))


def check(scene, sel):
    box = load()
    s = (box.get("scenes") or {}).get(scene)
    if not s:
        raise SystemExit("没有场景: " + scene)
    sel = {k: int(v) for k, v in (sel or {}).items()}
    errors, warnings = [], []

    sig = {it["item"]: it for it in s.get("signature") or []}
    sup = {it["item"]: it for it in s.get("supporting") or []}
    allitems = dict(sig)
    allitems.update(sup)

    # 1) 硬计数
    for hc in s.get("hard_counts") or []:
        n = sel.get(hc["item"], 0)
        if "exactly" in hc and n != hc["exactly"]:
            errors.append({"code": "HARD_COUNT", "item": hc["item"], "want": hc["exactly"], "got": n})
        if "at_least" in hc and n < hc["at_least"]:
            errors.append({"code": "HARD_COUNT", "item": hc["item"], "want": ">=" + str(hc["at_least"]), "got": n})

    # 2) fixed 特征家具
    for name, it in sig.items():
        c = it.get("count") or {}
        if c.get("type") == "fixed" and sel.get(name, 0) != c.get("value", 1):
            errors.append({"code": "FIXED_MISSING", "item": name, "want": c.get("value"), "got": sel.get(name, 0)})

    # 3) 特征种类数
    kinds = sum(1 for n in sig if sel.get(n, 0) > 0)
    if kinds < int(s.get("required_kinds") or 1):
        errors.append({"code": "NOT_ENOUGH_KINDS", "want": s.get("required_kinds"), "got": kinds})

    # 4) range / linked_soft
    for name, it in allitems.items():
        c = it.get("count") or {}
        n = sel.get(name, 0)
        if c.get("type") == "range":
            if not (c.get("min", 0) <= n <= c.get("max", 99)):
                warnings.append({"code": "OUT_OF_RANGE", "item": name, "range": [c.get("min"), c.get("max")], "got": n})
        if c.get("type") == "linked_soft":
            src = sel.get(c.get("from"), 0)
            if n == 0 and it.get("may_be_zero"):
                continue
            if src == 0:
                if n > 0:
                    errors.append({"code": "ORPHAN", "item": name, "msg": "依赖的 %s 不存在" % c.get("from")})
                continue
            r = n / float(src)
            if not (c.get("min", 0) <= r <= c.get("max", 9)):
                warnings.append({"code": "RATIO", "item": name, "ratio": round(r, 2),
                                 "range": [c.get("min"), c.get("max")]})
            if name == "chair" and float(c.get("max") or 9) <= 1.0 and n > src:
                errors.append({"code": "CHAIRS_GT_DESKS", "chairs": n, "desks": src})

    # 5) 中心区过挤（按 footprint 粗估）
    center = 0.0
    for name, it in allitems.items():
        if (it.get("prefer") == "center_floor") and sel.get(name, 0) > 0:
            center += float(it.get("footprint") or 1) * sel.get(name, 0)
    if center > 8:
        warnings.append({"code": "CENTER_CROWDED", "footprint": round(center, 1), "limit": 8})

    return {"scene": scene, "ok": not errors, "errors": errors, "warnings": warnings,
            "kinds": kinds, "selection": sel}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True)
    ap.add_argument("--items", default="", help="blackboard=1,student_desk=10,chair=7")
    a = ap.parse_args()
    sel = {}
    for part in a.items.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            sel[k.strip()] = int(v)
    r = check(a.scene, sel)
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
