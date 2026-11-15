# -*- coding: utf-8 -*-
"""paper 模式的合成与验收：合成 → 脚底/倒影体检 → 不达标加强 → 评审修正。

拆成模块的原因：coop_paper.py 有 20KB 上限，且这段逻辑与"出图"完全无关。
"""
import json
import os
import shutil

import evidence
import stage_parse

FEET_DARK_MIN = 0.25   # 脚底暗部下限：低于它人物会像浮在地面上


def _review(comp, stage, no_review=False):
    if not (stage and not no_review):
        return None
    try:
        rv = stage_parse.review(comp, stage)
        return rv
    except Exception as e:  # noqa: BLE001
        print("[review] 失败: %s" % str(e)[:120], flush=True)
        return None


def finish(plate, scene, scene_path, out, ss, char_box, anchor, stage, layers,
           no_review=False):
    """合成并验收；返回 (comp_path, evidence)。"""
    import layers as layers_mod
    wet = bool((stage or {}).get("wet_ground"))
    comp = layers_mod.compose_layers(plate, scene_path, out, ss, char_box)
    if anchor == "bottom":
        ev = {"feet_dark": 1.0, "contact_hard": 1.0, "refl_delta": 99.0,
              "wet": wet, "anchor": "bottom"}
    else:
        ev = evidence.feet(plate, comp, char_box, wet)

    if anchor == "feet" and (ev["feet_dark"] < FEET_DARK_MIN or (wet and ev["refl_delta"] < 2)):
        print("[evidence] 脚底/倒影不足 %s，加强阴影重合成" % ev, flush=True)
        layers[0]["shadow_boost"] = 1.8
        scene_b = os.path.join(out, "scene_boost.json")
        json.dump(scene, open(scene_b, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        rb = os.path.join(out, "boost")
        os.makedirs(rb, exist_ok=True)
        cb = layers_mod.compose_layers(plate, scene_b, rb, ss, char_box)
        if os.path.isfile(cb):
            shutil.copyfile(cb, comp)
            ev = evidence.feet(plate, comp, char_box, wet)
            print("[evidence] 加强后 %s" % ev, flush=True)

    json.dump(ev, open(os.path.join(out, "evidence.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    rv = _review(comp, stage, no_review)
    if rv is not None:
        bad = anchor == "feet" and (ev["feet_dark"] < FEET_DARK_MIN or (wet and ev["refl_delta"] < 2))
        if bad:
            rv["ok"] = False
            rv.setdefault("items", {})["contact_shadow"] = "fail"
            rv["evidence"] = ev
        json.dump(rv, open(os.path.join(out, "review.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("[review] ok=%s issues=%s fix=%s" % (rv.get("ok"), rv.get("issues"), rv.get("fix")), flush=True)
        fix = rv.get("fix") or {}
        if fix and not rv.get("ok") and stage:
            st2 = json.loads(json.dumps(stage))
            slot = (st2.get("person_slots") or [{}])[0]
            for k in ("x", "ground_y", "scale"):
                if k in fix:
                    slot[k] = fix[k]
            scene["stage"] = st2
            scene_path2 = os.path.join(out, "scene_retry.json")
            json.dump(scene, open(scene_path2, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            retry = os.path.join(out, "retry")
            os.makedirs(retry, exist_ok=True)
            comp2 = layers_mod.compose_layers(plate, scene_path2, retry, ss, char_box)
            if os.path.isfile(comp2):
                shutil.copyfile(comp2, comp)
                print("[review] 已按评审参数重合成", flush=True)
    return comp, ev
