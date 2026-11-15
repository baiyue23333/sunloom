# -*- coding: utf-8 -*-
"""性别隔离与通用女性/男性积木及角色卡增删回归。"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "ref")
OLD = ["@ID", "@ID_SOFT", "@ID_TIGHT", "@ID_ADULT", "@BODY", "@BODY_B"]
GENERIC_F = ["@ID_F", "@ID_F_SOFT", "@ID_F_TIGHT", "@ID_F_ADULT", "@BODY_F", "@BODY_F_B"]
MALE_FAMILIES = ["@ID_M", "@SINGLE_M", "@BODY_M", "@FACE_M", "@HAIR_M_SHORT",
                 "@FAB_M_WOOL", "@DRAPE_M_OPEN", "@POSE_M_HANDS_POCKET", "@HAND_M_POCKET",
                 "@ACC_M_WATCH", "@HOSE_M_SOCKS", "@NEG_MALE_BODY"]


def lib_gender():
    lib = json.load(open(os.path.join(REF, "prompt_lib.json"), encoding="utf-8"))
    return (lib.get("meta") or {}).get("gender") or {}


def run(c, tokens, notes, check, section):
    import ref.prompts as pt
    section("性别与角色绑定")

    def _generic_gender():
        left = [t for t in OLD if t in tokens]
        assert not left, "旧名还在: %s" % left
        miss = [t for t in GENERIC_F if t not in tokens]
        assert not miss, "缺失通用女性积木: %s" % miss
        g = lib_gender()
        assert g.get("@ID_M") == "m" and g.get("@ID_F") == "f", "性别元数据缺失"

    check("通用男女外貌积木与性别元数据完整", _generic_gender)

    def _alias():
        r = c.post("/api/expand", json={"positive": [{"token": "@ID_SOFT"}], "negative": []}).json()
        out = r.get("positive") or ""
        assert "@" not in out, out[:80]
        assert "young woman" in out.lower() and "brown eyes" in out.lower(), out[:80]

    check("旧名别名展开正常（不串残余）", _alias)

    def _male():
        miss = [t for t in MALE_FAMILIES if t not in tokens]
        assert not miss, "男性积木缺失: %s" % miss
        bad = [t for t in MALE_FAMILIES if not (notes.get(t) or "").strip()]
        assert not bad, "男性积木缺备注: %s" % bad
        male = [t for t, g in lib_gender().items() if g == "m" and t in tokens]
        assert len(male) >= 100, "男性积木只有 %d 个（要求 ≥100）" % len(male)

    check("通用男性积木 ≥100 且有备注", _male)

    def _garments():
        ch = json.load(open(os.path.join(REF, "character.json"), encoding="utf-8"))
        gs = ch.get("garments") or {}
        male = [k for k, g in gs.items() if (g.get("gender") or "f") == "m"]
        assert len(male) >= 20, "男装只有 %d 套（要求 ≥20）" % len(male)
        for k in male:
            g = gs[k]
            for f in ("label", "note", "parts", "prompt", "negative"):
                assert g.get(f), "男装 %s 缺 %s" % (k, f)
            assert "@OUT_" + k.upper() in tokens, "男装 %s 缺 @OUT 宏" % k
            assert "@NEG_" + k.upper() in tokens, "男装 %s 缺 @NEG 宏" % k

    check("男版服装 8 套且派生宏齐全", _garments)

    def _filter_male():
        g = lib_gender()
        for k in GENERIC_F:
            assert g.get(k) == "f", f"{k} 应为女性 f，实际 {g.get(k)}"
        for k in MALE_FAMILIES:
            assert k in tokens, f"男性积木缺失 {k}"
            assert g.get(k) == "m", f"{k} 应为男性 m，实际 {g.get(k)}"

    check("性别过滤归类一致", _filter_male)

    def _card_roundtrip():
        cname = "__smoke_gender_card__"
        r = c.post("/api/card/save", json={
            "name": cname, "gender": "f", "persona": "测试角色",
            "pos_blocks": [{"token": "@ID_F"}], "neg_blocks": [{"token": "@NEG_BASE"}],
            "tokens": ["@ID_F"],
        })
        assert r.status_code == 200, r.text
        items = c.get("/api/cards").json().get("items") or []
        got = next((x for x in items if x.get("name") == cname), None)
        assert got and got.get("gender") == "f", "角色卡保存失败"
        c.delete("/api/card/" + cname)

    check("角色卡性别字段增删闭环", _card_roundtrip)
