# -*- coding: utf-8 -*-
"""缺陷修复与数据透明度回归（从 run_tests.py 拆出，保持单文件 <20KB）。"""
import json
import os
import shutil
import sys
import tempfile


def run(check, ROOT, c, boot, store):
    def _card_views_and_import():
        cname = "__test_views_card__"
        try:
            r1 = c.post("/api/card/save", json={
                "name": cname, "tokens": ["@ID"], "views": {"side": ["@POSE_SIDE"]},
            })
            assert r1.status_code == 200, r1.text
            r2 = c.post("/api/card/save", json={"name": cname, "tokens": ["@ID"], "note": "edited"})
            assert r2.status_code == 200, r2.text
            got = next((x for x in c.get("/api/cards").json()["items"] if x.get("name") == cname), None)
            assert got and got.get("views") == {"side": ["@POSE_SIDE"]}, f"views 丢失: {got}"
            imp = c.post("/api/cards/import", json={"data": json.dumps([{"name": cname, "tokens": []}])}).json()
            assert cname in (imp.get("skipped_names") or []), imp
        finally:
            c.post("/api/card/delete", json={"name": cname})

    check("角色卡保存保留 views 与导入冲突报告", _card_views_and_import)

    def _obs_and_taxonomy():
        assert "prefix_rules" in (boot.get("taxonomy") or {}), "bootstrap 缺 taxonomy"
        obs = c.get("/api/observability").json()
        assert "warnings" in obs and "legacy_drift" in obs and "cache" in obs, obs
        rec = c.get("/api/recipes").json()
        assert "missing" in rec, rec
        jobs_r = c.get("/api/jobs").json()
        assert "items" in jobs_r, jobs_r
        rel = c.get("/api/reliability").json()
        assert "structured" in rel and "legacy_parsed" in rel and "details" in rel, rel
        exp = c.post("/api/expand", json={
            "positive": [{"token": "@HOLD_R_CUP"}], "negative": [{"token": "@NEG_CUP"}],
        }).json()
        assert any(x.get("rule") == "cup_wanted" for x in (exp.get("rewrites") or [])), exp

    check("可观测性 / taxonomy / 改写回执 / 可信度结构化", _obs_and_taxonomy)

    def _jobs_coop_store():
        store.upsert_job({"id": "t_job_1", "kind": "run", "label": "lbl", "status": "done", "started": 1.0})
        assert any(j.get("id") == "t_job_1" for j in store.load_jobs()), "jobs_history 读写失败"
        store.upsert_coop_run({"id": "t_coop_1", "mode": "reproject", "status": "done", "started": 2.0})
        assert any(x.get("id") == "t_coop_1" for x in store.load_coop_runs()), "coop_runs 读写失败"

    check("任务与合作历史 SQLite 持久化", _jobs_coop_store)

    def _reproj_png_roundtrip():
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        from PIL import Image
        import reproj_provenance as rp
        import svc_recipes as sr
        td = tempfile.mkdtemp(prefix="loom_prov_")
        try:
            fp = os.path.join(td, "comp.png")
            mf = rp.new_manifest({"width": 512, "height": 512, "steps": 20, "cfg": 5.5, "seed": 42},
                                 td, "test prompt", "bad neg", "bad neg",
                                 [{"name": "a.safetensors", "weight": 0.7}], [], [], rp.resolve_suffixes({}))
            rp.record_step(mf, "01_plate", status="ok", prompt="test prompt", seed=42)
            rp.save_comp_with_provenance(Image.new("RGB", (64, 64), (120, 120, 120)), fp, mf)
            assert os.path.isfile(os.path.join(td, "manifest.json")), "未写出 manifest.json"
            parsed = sr._parse_png_recipe(fp)
            assert parsed and parsed.get("mode") == "reproject" and parsed.get("manifest_path"), parsed
        finally:
            shutil.rmtree(td, ignore_errors=True)

    check("重映 PNG 元数据与 manifest 往返", _reproj_png_roundtrip)
