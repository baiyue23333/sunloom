# -*- coding: utf-8 -*-
"""提示板规则回归（从 run_tests 拆出，避免主文件超 20KB）。"""
import os
import sys


def run(check, ROOT):
    sys.path.insert(0, os.path.join(ROOT, "station"))
    import ir

    def codes(r):
        return [x["code"] for x in r["errors"] + r["warnings"] + r["hints"]]

    def _rules():
        r = ir.validate([{"token": "@ID_F"}, {"token": "@CAM_MEDIUM"}, {"token": "@CAM_BUST"}], [{"token": "@NEG_BASE"}])
        assert "MULTI_CAM" in codes(r), codes(r)
        r = ir.validate([{"token": "@ID_F"}, {"token": "@SET_CAFE"}, {"token": "@SET_LIBRARY"}], [{"token": "@NEG_BASE"}])
        assert "MULTI_SET" in codes(r), codes(r)
        r = ir.validate([{"token": "@ID_F"}, {"token": "@NOPE_X"}], [{"token": "@NEG_BASE"}])
        assert "UNKNOWN_TOKEN" in codes(r), codes(r)
        r = ir.validate([{"token": "@ID_F"}], [{"token": "@NEG_BASE"}, {"token": "@OUT_SCHOOL"}])
        assert "NEG_POS_MIX" in codes(r), codes(r)
        r = ir.validate([{"token": "@ID_F"}, {"token": "@OUT_SCHOOL_M"}], [{"token": "@NEG_BASE"}])
        assert "GENDER_OUTFIT" in codes(r), codes(r)
        r = ir.validate([{"token": "@ID_F"}, {"token": "@LIGHT_WIN"}], [{"token": "@NEG_BASE"}], view="@CAM_BACKSIDE")
        assert "BACK_FRONT_LIGHT" in codes(r), codes(r)
        r = ir.validate([{"token": "@ID_F"}], [{"token": "@NEG_CUP"}, {"token": "@NEG_BASE"}])
        assert "NEG_ORDER" not in codes(r), codes(r)
        r = ir.validate([{"token": "@ID_F"}, {"token": "@SET_LIBRARY"}, {"token": "@CAM_BUST"}], [{"token": "@NEG_BASE"}])
        assert "SCENE_HEAVY" not in codes(r), codes(r)
        # 2026-11-16 提示词组合回归：别名/禁用/strip/加权括号/前缀/背影光/重映去重
        assert "NEG_POS_MIX" not in codes(ir.validate([{"token": "@ID_F"}], [{"token": "@NEG_BASE"}, {"token": "@STRIP_SHOES"}]))
        assert "FRAMING_CONFLICT" in codes(ir.validate([{"token": "@SINGLE_F"}, {"token": "@CAM_FULL"}], [{"token": "@NEG_BASE"}]))
        assert "STYLE_SET_CONFLICT" not in codes(ir.validate([{"token": "@ID_F"}, {"token": "@SET_CORRIDOR"}, {"token": "@STYLE_SOFT", "enabled": False}], [{"token": "@NEG_BASE"}]))
        assert "DRAPE_GARMENT_MISMATCH" not in codes(ir.validate([{"token": "@ID_F"}, {"token": "@OUT_CARDIGAN_SET"}, {"token": "@DRAPE_OFF"}], [{"token": "@NEG_BASE"}]))
    check("提示板规则更新", _rules)

    def _compose_fixes():
        sys.path.insert(0, os.path.join(ROOT, "ref"))
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import prompts as pt
        import prompt_fix
        import svc_state
        from svc_jobs import Block
        import coop_reproject

        tokens, _, _ = pt.load_tokens()
        ex_u, used_u = pt.expand("@CAM_FULL_UNKNOWN", tokens)
        assert ex_u == "@CAM_FULL_UNKNOWN" and not used_u, (ex_u, used_u)

        for out_tok, strip_tok in (("@OUT_WINTER", "@STRIP_COAT"), ("@OUT_SLIP", "@STRIP_SHOES")):
            res = svc_state.expand_blocks([Block(token=out_tok, weight=1.2)], [Block(token=strip_tok)])
            p = res["positive"]
            assert p.count("(") == p.count(")") and p.count("(") == 1, (out_tok, strip_tok, p)

        fx = prompt_fix.audit([{"token": "@ID_F"}, {"token": "@LIGHT_BACK"}], [{"token": "@NEG_BASE"}, {"token": "@STRIP_SHOES"}])
        assert not fx["issues"], fx["issues"]
        fx_back = prompt_fix.audit([{"token": "@ID_F"}, {"token": "@CAM_BACKSIDE"}, {"token": "@LIGHT_SOFT"}], [{"token": "@NEG_BASE"}])
        reps = [i["replace"] for i in fx_back["issues"] if i.get("action") == "replace"]
        assert "@LIGHT_BACK" in reps and all(r in tokens for r in reps if r.startswith("@")), fx_back["issues"]

        joined = coop_reproject._dedup_join("rim light, (soft glow, warm:1.1), cafe interior", "rim light, (soft glow, warm:1.1), 1girl")
        assert joined.count("rim light") == 1 and joined.count("(soft glow, warm:1.1)") == 1, joined
    check("提示词组合修复回归", _compose_fixes)
