# -*- coding: utf-8 -*-
"""用工作站现有的积木系统拼提示词：卡片身份 + 服装块 + 场景/镜头/光宏 → 校验 → 展开。

不手写英文。服装从 ref/character.json 的 garments 里取（casual_knit 等），
身份从 ref/cards/*.json 的 pos_blocks 取，其余走 ref/prompt_lib.json 的宏。
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ref"))
sys.path.insert(0, os.path.join(ROOT, "station"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import prompts as plib
import ir


def load_card(name):
    p = os.path.join(ROOT, "ref", "cards", name + ".json")
    if not os.path.isfile(p):
        raise SystemExit("没有卡片: " + p)
    return json.load(open(p, encoding="utf-8"))


def load_garment(name):
    d = json.load(open(os.path.join(ROOT, "ref", "character.json"), encoding="utf-8"))
    g = (d.get("garments") or {}).get(name)
    if not g:
        raise SystemExit("没有服装: " + name)
    return g


def build(card_name, garment, extra_tokens, expand_llm=False, brief="",
          id_blocks=None, view="", scene_schema=""):
    card = load_card(card_name)
    g = load_garment(garment)
    tokens, lib, ch = plib.load_tokens()
    for k, v in (card.get("views") or {}).items():
        tokens[k] = v

    if id_blocks is None:
        id_blocks = ["@ID_F", "@BODY_MIO", "@FACE"]
    want = set(id_blocks)
    pos_blocks = [dict(b) for b in (card.get("pos_blocks") or []) if b.get("token") in want]
    keep_order = [b["token"] for b in pos_blocks]
    pos_blocks.sort(key=lambda b: keep_order.index(b["token"]))
    neg_blocks = [dict(b) for b in (card.get("neg_blocks") or [])]
    scene_extra, scene_forb = "", ""
    if scene_schema:
        import scene_compile
        scene_extra, scene_forb = scene_compile.compile_scene(scene_schema)
        extra_tokens = [x for x in extra_tokens if not x.startswith("@SET_")]
    pos_blocks.append({"token": "@NO_CLIP", "weight": 1.0, "text": ""})
    if view:
        pos_blocks.append({"token": view, "weight": 1.0, "text": ""})
        pos_blocks.append({"token": "", "weight": 1.0,
                           "text": "(single character:1.4), (one girl only:1.3), (no second figure:1.3)"})
        # 背影视角：换成不含脸部描述的光块
        if view.upper().endswith(("_BACK", "_TQ_BACK")):
            extra_tokens = ["@LIGHT_WIN_BACK" if x == "@LIGHT_WIN" else x for x in extra_tokens]
    pos_blocks.append({"token": "@OUT_" + garment.upper(), "weight": 1.0, "text": ""})
    if scene_extra:
        pos_blocks.append({"token": "", "weight": 1.0, "text": scene_extra})
    for tk in extra_tokens:
        pos_blocks.append({"token": tk, "weight": 1.0, "text": ""})

    # 校验（身份锁 / 服装型态 / 负向底线）
    report = ir.validate(pos_blocks, neg_blocks, view=view)

    # 展开：token 部分 + 服装块原文
    pos_text, used_pos = plib.expand(", ".join([b["token"] for b in pos_blocks if b.get("token")]), tokens)
    texts = [b["text"] for b in pos_blocks if not b.get("token") and b.get("text")]
    if texts:
        pos_text = (pos_text + ", " + ", ".join(texts)).strip(", ")
    extra_neg = ("two girls, duplicate, twin, second figure, split composition, "
                 "objects clipping into each other, furniture embedded in the wall, "
                 "table passing through the shelf, chair sunk into the floor, overlapping geometry")
    if scene_forb:
        neg_text_extra = scene_forb + ", " + extra_neg
    else:
        neg_text_extra = extra_neg
    neg_text, used_neg = plib.expand(", ".join([b["token"] for b in neg_blocks if b.get("token")]), tokens)

    view_errors = ir.check_view(pos_text, view) if view else []
    prop_errors = ir.check_props(pos_text)
    report.setdefault("errors", [])
    if neg_text_extra:
        neg_text = (neg_text + ", " + neg_text_extra).strip(", ")
    out = {"positive": pos_text, "negative": neg_text, "report": report,
           "view": view, "view_errors": view_errors, "prop_errors": prop_errors,
           "used_pos": used_pos, "used_neg": used_neg,
           "garment_label": g.get("label", ""), "garment_prompt": g.get("prompt", "")}

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", default="角色Mio")
    ap.add_argument("--garment", default="casual_knit")
    ap.add_argument("--tokens", default="@SET_LIBRARY,@CAM_MEDIUM,@CAM_THREEQ,@LIGHT_WIN")
    ap.add_argument("--id", default="@ID_F,@BODY_MIO,@FACE")
    ap.add_argument("--view", default="")
    ap.add_argument("--all-views", action="store_true")
    ap.add_argument("--scene-schema", default="")
    a = ap.parse_args()
    extra = [t.strip() for t in a.tokens.split(",") if t.strip()]
    ids = [x.strip() for x in a.id.split(",") if x.strip()]
    if a.view and a.id == "@ID_F,@BODY_MIO,@FACE":
        ids = []   # 视角块已含可见身份，避免重复
    if a.all_views:
        card = load_card(a.card)
        for name in (card.get("views") or {}):
            r = build(a.card, a.garment, extra, False, id_blocks=[], view=name)
            print("\n=== %s" % name)
            print("正向:", r["positive"][:420])
            print("视角检查:", json.dumps(r["view_errors"], ensure_ascii=False))
            print("道具检查:", json.dumps(r["prop_errors"], ensure_ascii=False))
        return
    r = build(a.card, a.garment, extra, id_blocks=ids, view=a.view, scene_schema=a.scene_schema)
    print("== 服装:", r["garment_label"])
    print("== 校验:", json.dumps(r["report"], ensure_ascii=False))
    print("== 用到的宏:", ", ".join(r["used_pos"]))
    print("== 正向长度:", len(r["positive"]), "(建议 ≤900)" if len(r["positive"]) > 900 else "")
    print("== 正向:", r["positive"][:700])
    print("== 负向长度:", len(r["negative"]))
    print("== 负向:", r["negative"][:300])
    rep = r["report"]


if __name__ == "__main__":
    main()
