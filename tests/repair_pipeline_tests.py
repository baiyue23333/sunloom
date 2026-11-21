# -*- coding: utf-8 -*-
"""结构审计修复：任务失败路径、并发隔离与批量执行一致性。"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import tempfile
import threading
import time
from unittest.mock import patch


@contextmanager
def execution_fixture(folder):
    import svc_jobs as jobs
    import svc_paths as paths
    with ExitStack() as stack:
        stack.enter_context(patch.object(paths, "PICTURES", str(Path(folder) / "images")))
        stack.enter_context(patch.object(jobs, "comfy_out", return_value=folder))
        stack.enter_context(patch.object(jobs.cf, "system_stats", return_value={"up": True}))
        stack.enter_context(patch.object(jobs.gf, "build", return_value=(
            {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "anima-base-v1.0.safetensors"}}},
            {"workflow": "anima_t2i", "missing": [], "denoise": 1})))
        prepare = stack.enter_context(patch.object(jobs.svc_mem, "prepare_stage", return_value={"action": "keep"}))
        stack.enter_context(patch.object(jobs.svc_mem, "release_stage", return_value={}))
        yield prepare


def run(check, root):
    import routes_coop as coop
    import svc_coop as worker
    import svc_jobs as jobs
    import svc_batch as batch
    import svc_state as state
    import svc_tasks as tasks
    import store
    from PIL import Image

    def coop_admission():
        barrier = threading.Barrier(2)

        def validated(req):
            barrier.wait(timeout=8)

        with tempfile.TemporaryDirectory() as tmp, patch.dict(state.COOP_STATE, {"status": "idle"}, clear=True), \
             patch.object(coop, "COOP_DIR", tmp), patch.object(coop, "validate_coop", side_effect=validated), \
             patch.object(coop, "threading") as threads:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(coop.api_coop, coop.CoopReq(mode="reproject", seed=123)) for _ in range(2)]
                responses = [future.result(timeout=12) for future in futures]
            assert sorted(r["ok"] for r in responses) == [False, True], responses
            assert threads.Thread.call_count == 1
            args = threads.Thread.call_args.kwargs["args"]
            assert len(args) == 2 and args[1]["id"] == state.COOP_STATE["id"]
            assert state.COOP_STATE["id"] in args[1]["dir"]
    check("合作任务：并发准入只接受一个任务且传递独立上下文", coop_admission)

    def context_isolation():
        with patch.dict(state.COOP_STATE, {"id": "new", "status": "running", "dir": "new-dir"}, clear=True):
            old = {"id": "old", "status": "running", "dir": "old-dir"}
            worker.publish_run(old, status="error", dir="old-failed")
            assert state.COOP_STATE["status"] == "running" and state.COOP_STATE["dir"] == "new-dir"
            assert old["status"] == "error"
    check("合作任务：旧 worker 不覆盖新任务状态", context_isolation)

    def child_completion():
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "comp.png"
            Image.new("RGB", (64, 64), "white").save(image)
            for code, valid in ((17, False), (0, False), (0, True)):
                rid = "repair_worker_%s_%s" % (code, valid)

                class Process:
                    def __init__(self, *args, **kwargs):
                        self.stdout = iter(["done: " + str(image) + "\n"] if valid else ["fatal simulated failure\n"])

                    def wait(self, timeout=None):
                        return code

                run = {"id": rid, "dir": tmp, "status": "starting", "mode": "reproject", "keep_intermediates": True}
                with patch.dict(state.COOP_STATE, run, clear=True), patch.object(worker.subprocess, "Popen", Process), \
                     patch.object(worker, "coop_dir_allowed", return_value=True):
                    worker.coop_worker([], run)
                    expected = "done" if code == 0 and valid else "error"
                    assert state.COOP_STATE["status"] == expected, state.COOP_STATE
                    persisted = next(item for item in store.load_coop_runs(60) if item["id"] == rid)
                    assert persisted["status"] == expected
    check("合作任务：退出码和有效成图共同决定持久化终态", child_completion)

    def empty_output():
        with tempfile.TemporaryDirectory() as tmp, execution_fixture(tmp):
            for result in ({"ok": True, "images": []}, {"ok": True, "images": [{"filename": "missing.png"}]}):
                jid = state.job_new("run", "empty")
                with patch.object(jobs, "_wait_with_oom_retry", return_value=("test", result)):
                    jobs._submit("t2i", {"prompt": "audit", "prefix": "repaint_repair"}, jid, "empty")
                assert state.JOBS[jid]["status"] == "error", state.JOBS[jid]
                assert not any(line.startswith("saved ") for line in state.JOBS[jid]["logs"])
                assert next(j for j in store.load_jobs(200) if j["id"] == jid)["status"] == "error"
    check("单图任务：空输出与缺失源文件均失败且不打印假保存", empty_output)

    def cancelled_submission():
        jid = state.job_new("run", "cancel_race")

        def submit(graph):
            tasks.cancel(jid)
            return "late-prompt"

        with patch.object(jobs.gf, "submit", side_effect=submit), patch.object(jobs.cf, "wait") as wait, \
             patch.object(tasks.cf, "cancel_prompt", return_value=True) as cancel:
            _, result = jobs._wait_with_oom_retry({}, jid, 1, "race")
        assert result.get("cancelled") and not wait.called
        cancel.assert_called_once_with("late-prompt")
        tasks.finish(jid, "done", result={"images": ["fake.png"]})
        assert state.JOBS[jid]["status"] == "cancelled"
    check("单图任务：提交期间取消也能回收所属 prompt", cancelled_submission)

    def batch_shared_engine():
        from job_models import BatchReq
        with tempfile.TemporaryDirectory() as tmp, execution_fixture(tmp) as prepare:
            src = Path(tmp) / "source.png"
            Image.new("RGB", (64, 64), "white").save(src)
            jid = state.job_new("batch", "repair_batch")
            seeds = [1001, 1002]
            state.JOBS[jid]["items"] = [{"seed": seed, "status": "pending", "image": ""} for seed in seeds]
            answers = [{"ok": False, "error": "CUDA out of memory"},
                       {"ok": True, "images": [{"filename": src.name}]},
                       {"ok": False, "error": "test execution failure"}]
            with patch.object(jobs.gf, "submit", side_effect=["one", "retry", "two"]), \
                 patch.object(jobs.cf, "wait", side_effect=answers), \
                 patch.object(jobs.svc_mem, "recover_oom", return_value={}) as recover:
                req = BatchReq(prompt="audit", count=2, width=512, height=512, steps=12, prefix="repaint_repair")
                batch.run_batch(req, jid, seeds)
            result = state.JOBS[jid]
            assert result["status"] == "partial", result
            assert result["result"]["succeeded"] == 1 and result["result"]["failed"] == 1
            assert prepare.call_count == 2 and recover.call_count == 1
            first = result["items"][0]
            assert os.path.isfile(first["image"]) and store.get_recipe(first["image"])
            persisted = {job["id"]: job for job in store.load_jobs(200)}
            assert jid in persisted and first["job_id"] in persisted
    check("批量任务：复用显存/OOM/配方/持久化链路并标记部分失败", batch_shared_engine)

    def parent_cancellation():
        parent = state.job_new("batch", "parent")
        child = state.job_new("batch_item", "child")
        state.JOBS[child].update(parent_id=parent, prompt_id="child-prompt")
        with patch.object(tasks.cf, "cancel_prompt", return_value=True) as cancel:
            tasks.cancel(parent)
        cancel.assert_called_once_with("child-prompt")
        assert state.JOBS[parent]["status"] == state.JOBS[child]["status"] == "cancelled"
    check("批量任务：取消父任务同时取消所属活动子任务", parent_cancellation)

    def handfix_persistence():
        import routes_hand as hand
        import hand_precise
        from job_models import MaskReq
        for cancel_during in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "source.png"
                Image.new("RGB", (64, 64), "white").save(source)
                store.upsert_recipe(str(source), {"size": [1024, 1536]})
                jid = state.job_new("handfix", "repair_hand")
                req = MaskReq(image=str(source), box="16,16,20,20", cfg=0, denoise=0, prefix="repair_hand")

                def repaint(*args, **kwargs):
                    assert kwargs["parent_job_id"] == jid and kwargs["cfg"] == kwargs["denoise"] == 0
                    if cancel_during:
                        tasks.cancel(jid)
                    return str(source), {}

                with patch.object(hand_precise, "repaint", side_effect=repaint), \
                     patch.object(hand, "ensure_image_hand_boxes", return_value={"boxes": []}), \
                     patch.object(tasks.cf, "cancel_prompt", return_value=True), \
                     patch.object(state, "job_save", wraps=state.job_save) as save:
                    hand.run_precise_handfix(req, jid, state.JOBS, state.job_log, save, jobs.add_recipe, tmp)
                    save.assert_called_with(jid)
                assert state.JOBS[jid]["status"] == ("cancelled" if cancel_during else "done"), state.JOBS[jid]
                if not cancel_during:
                    assert store.get_recipe(state.JOBS[jid]["result"]["images"][0])["size"] == [64, 64]
    check("精修接入：持久化回调带任务 ID 且不覆盖取消状态", handfix_persistence)
