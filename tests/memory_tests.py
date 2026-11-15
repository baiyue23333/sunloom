# -*- coding: utf-8 -*-
"""显存与内存调度回归测试：策略档位、热命中/分层清理、切换卸模、OOM 自动重试、coop mem_plan。"""
import json
import os
import tempfile


def run(check, ROOT, c):
    import comfy as cf
    import svc_jobs
    import svc_mem
    import svc_state
    import mem_plan

    def _with_mock_comfy(fake_vram_free_mb, fake_vram_total_mb=8188):
        """构造局部桩替换 comfy.system_stats / comfy.free，并保护现场还原。"""
        calls = []
        state = {"free_mb": fake_vram_free_mb}
        orig_stats, orig_free = cf.system_stats, cf.free

        def m_stats():
            return {
                "up": True, "version": "test",
                "vram_total": int(fake_vram_total_mb * 1024 * 1024),
                "vram_free": int(state["free_mb"] * 1024 * 1024),
                "device": "mock-8g",
            }

        def m_free(unload_models=True, free_memory=True):
            calls.append({"unload": bool(unload_models), "free_memory": bool(free_memory)})
            if unload_models:
                state["free_mb"] = max(state["free_mb"], 6400)
            else:
                state["free_mb"] = max(state["free_mb"], 2400)
            return {"ok": True, "unload_models": bool(unload_models)}

        cf.system_stats = m_stats
        cf.free = m_free
        return calls, state, (orig_stats, orig_free)

    def _t_policy_and_endpoints():
        orig = svc_mem.get_policy()
        try:
            r0 = c.get("/api/memory").json()
            assert "scheduler" in r0 and "policy" in r0["scheduler"]
            r_ag = c.post("/api/memory/policy", json={"profile": "aggressive"})
            assert r_ag.status_code == 200 and r_ag.json()["policy"]["soft_free_mb"] == 2200
            r_bad = c.post("/api/memory/policy", json={"profile": "ultra_unknown"})
            assert r_bad.status_code == 400
            r_ev = c.get("/api/memory/events?limit=10").json()
            assert "events" in r_ev and "stats" in r_ev
        finally:
            svc_mem.set_policy(orig["profile"], orig)

    check("内存策略档位切换与 /api/memory 契约", _t_policy_and_endpoints)

    def _t_stage_keep_soft_switch():
        orig_pol = svc_mem.get_policy()
        orig_stage = dict(svc_mem._STAGE)
        calls, state, (os0, of0) = _with_mock_comfy(3500)
        try:
            svc_mem.set_policy("balanced")
            svc_mem._STAGE.update(family="", unet="", since=0.0, hits=0)

            # 1) 首次进入 anima -> 无旧模型，不调 /free
            r1 = svc_mem.prepare_stage("anima", "anima-base-v1.0.safetensors", reason="t1", context="base")
            assert r1["action"] == "keep" and len(calls) == 0

            # 2) 同底模且显存充足(3500 >= 1600) -> 热命中 keep，不卸模
            r2 = svc_mem.prepare_stage("anima", "anima-base-v1.0.safetensors", reason="t2", context="base")
            assert r2["action"] == "keep" and len(calls) == 0

            # 3) 同底模显存进入软水位(1300 < 1600) -> 仅轻清缓存(unload_models=False)
            state["free_mb"] = 1300
            r3 = svc_mem.prepare_stage("anima", "anima-base-v1.0.safetensors", reason="t3", context="base")
            assert r3["action"] == "soft_free" and calls[-1]["unload"] is False

            # 4) 同底模显存跌破硬水位(700 < 950) -> 硬卸载防 OOM
            state["free_mb"] = 700
            r4 = svc_mem.prepare_stage("anima", "anima-base-v1.0.safetensors", reason="t4", context="base")
            assert r4["action"] == "hard_unload" and calls[-1]["unload"] is True

            # 5) 从 anima 切换到 sdpose -> 触发 switch_unload
            state["free_mb"] = 2500
            r5 = svc_mem.prepare_stage("sdpose", "sdpose_wholebody_fp16.safetensors", reason="pose", context="coop")
            assert r5["action"] == "switch_unload" and calls[-1]["unload"] is True

            # 6) 再切回 anima，经 /api/memory/schedule 走 HTTP 调度
            state["free_mb"] = 2800
            r6 = c.post("/api/memory/schedule", json={
                "action": "prepare", "family": "anima", "unet": "anima-base-v1.0.safetensors",
                "reason": "back_to_anima", "context": "coop",
            })
            assert r6.status_code == 200 and r6.json()["action"] == "switch_unload"
        finally:
            cf.system_stats, cf.free = os0, of0
            svc_mem._STAGE.update(orig_stage)
            svc_mem.set_policy(orig_pol["profile"], orig_pol)

    check("底模热命中 / 分级释放 / 异构切换调度", _t_stage_keep_soft_switch)

    def _t_oom_auto_retry():
        import graph as gf
        orig_pol = svc_mem.get_policy()
        orig_stage = dict(svc_mem._STAGE)
        orig_submit, orig_wait = gf.submit, cf.wait
        calls, state, (os0, of0) = _with_mock_comfy(2600)
        sub_cnt = [0]
        try:
            def m_submit(wf):
                sub_cnt[0] += 1
                return "pid_%d" % sub_cnt[0]

            def m_wait(pid, timeout=1800, on_tick=None):
                if pid == "pid_1":
                    return {"ok": False, "error": "CUDA out of memory. Tried to allocate 1.2 GiB"}
                return {"ok": True, "images": []}

            gf.submit, cf.wait = m_submit, m_wait
            jid = svc_state.job_new("test", "oom")
            _, res = svc_jobs._wait_with_oom_retry({"1": {}}, jid, 10.0, "oom_test", context="base", timeout=10)
            assert res["ok"] is True and sub_cnt[0] == 2, (sub_cnt[0], res)
            assert any(x["unload"] is True for x in calls), calls
            assert any("清模并重试" in l for l in svc_state.JOBS[jid]["logs"])
        finally:
            gf.submit, cf.wait = orig_submit, orig_wait
            cf.system_stats, cf.free = os0, of0
            svc_mem._STAGE.update(orig_stage)
            svc_mem.set_policy(orig_pol["profile"], orig_pol)

    check("CUDA OOM 自动清模恢复并重试一次", _t_oom_auto_retry)

    def _t_coop_mem_plan():
        orig_vram = mem_plan.comfy_vram
        orig_post = mem_plan._post_json
        mem_plan.comfy_vram = lambda: (3200, 8188)

        def m_post(url, body, timeout=30):
            return {"action": "switch_unload" if body.get("family") != "anima" else "keep",
                    "vram_free_mb": 3200, "event": {"reclaimed_mb": 1200}}

        mem_plan._post_json = m_post
        try:
            mp = mem_plan.Plan(context="coop")
            mp.schedule("anima", note="01_plate")
            mp.schedule("birefnet", note="body_mask")
            mp.schedule("anima", note="02_body")
            mp.trim_py("done")
            with tempfile.TemporaryDirectory() as td:
                p = mp.save(td)
                data = json.load(open(p, encoding="utf-8"))
                assert os.path.isfile(p) and len(data["marks"]) == 4
                assert data["context"] == "coop"
        finally:
            mem_plan.comfy_vram = orig_vram
            mem_plan._post_json = orig_post

    check("合作模式 mem_plan 阶段调度与 mem_plan.json 落盘", _t_coop_mem_plan)
