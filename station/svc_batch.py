# -*- coding: utf-8 -*-
"""批量编排：单次执行复用 svc_jobs，终态区分成功、部分失败与失败。"""
import os

import svc_jobs as jobs
import svc_mem
from svc_recipes import _prepare_reference
from svc_state import JOBS, JOB_LOCK, job_log, job_new, job_save
from svc_tasks import cancelled, finish


def _summary(jid, succeeded, failed, **result):
    status = "done" if succeeded and not failed else ("partial" if succeeded else "error")
    result.update(succeeded=succeeded, failed=failed)
    if not succeeded:
        result.setdefault("error", "所有批量项目均未产图")
    finish(jid, status, progress=1.0, result=result)


def run_batch(req, jid, seeds):
    try:
        for index, seed in enumerate(seeds):
            if cancelled(jid):
                break
            item = JOBS[jid]["items"][index]
            child = job_new("batch_item", "%s_%02d" % (req.prefix, index + 1))
            with JOB_LOCK:
                JOBS[child]["parent_id"] = jid
                item.update(job_id=child, status="running")
                job_save(child)
                job_save(jid)
            params = {"prompt": req.prompt, "negative": req.negative, "width": req.width, "height": req.height,
                      "steps": req.steps, "cfg": req.cfg, "seed": seed, "prefix": JOBS[child]["label"],
                      "loras": req.loras, "model": req.model, "denoise": 1.0,
                      "blocks_pos": req.blocks_pos, "blocks_neg": req.blocks_neg, "save_to": "station_out"}
            try:
                if req.mode == "i2i":
                    params["reference"] = _prepare_reference(req.reference)
                jobs._submit(req.mode, params, child, JOBS[child]["label"])
                outcome = JOBS[child]
                result = outcome.get("result") or {}
                images = result.get("images") or []
                item.update(status=outcome["status"], image=images[0] if images else "")
                if not images and item["status"] == "done":
                    item["status"] = "error"
                if item["status"] != "done":
                    item["error"] = result.get("error") or "未产图"
            except Exception as exc:
                finish(child, "error", result={"error": str(exc)})
                item.update(status="error", error=str(exc)[:300])
            JOBS[jid]["progress"] = (index + 1) / len(seeds)
            job_log(jid, "%s %d/%d seed=%s" % (item["status"], index + 1, len(seeds), seed))
            job_save(jid)
        items = JOBS[jid]["items"]
        if cancelled(jid):
            for item in items:
                if item["status"] in ("pending", "running"):
                    item.update(status="cancelled")
            finish(jid, "cancelled")
        else:
            succeeded = sum(item["status"] == "done" for item in items)
            _summary(jid, succeeded, len(items) - succeeded, items=items,
                     images=[item["image"] for item in items if item.get("image")])
    except Exception as exc:
        finish(jid, "error", result={"error": str(exc)[:300]})


def run_batchq(req, jid):
    try:
        pool = jobs._tpl_pool(req.templates)
        if not pool:
            raise RuntimeError("没有可用模板")
        loras = jobs._default_loras(req.loras)
        saved, succeeded, failed = [], 0, 0
        for index in range(req.count):
            if cancelled(jid):
                break
            first, exp, w, h, steps, cfg, seed, label, model, err = jobs._sample_from_pool(
                pool, loras, "batchq", "bq", index, req.model, req.steps, req.cfg, jid=jid)
            if not first:
                failed += 1
                job_log(jid, "第 %d 张失败：%s" % (index + 1, err))
                continue
            succeeded += 1
            saved.append(first)
            if req.refine and not cancelled(jid):
                second = jobs._make_refine(exp, w, h, steps, cfg, seed, loras, label, model, first, req.denoise, jid=jid)
                if second:
                    saved.append(second)
                else:
                    failed += 1
                    job_log(jid, "第 %d 张精修失败，已保留原图" % (index + 1))
            JOBS[jid]["progress"] = (index + 1) / req.count
            job_save(jid)
        _summary(jid, succeeded, failed, images=saved, count=len(saved))
    except Exception as exc:
        finish(jid, "error", result={"error": str(exc)[:300]})
    finally:
        svc_mem.release_stage(context="batch", reason="batchq", soft=svc_mem.get_policy().get("profile") == "aggressive")


def run_autopipe(req, jid):
    try:
        pool = jobs._tpl_pool(req.templates)
        if not pool:
            raise RuntimeError("没有可用模板")
        loras = jobs._default_loras(req.loras)
        made, failed = [], 0
        for index in range(req.count):
            if cancelled(jid):
                break
            first, exp, w, h, steps, cfg, seed, label, model, err = jobs._sample_from_pool(
                pool, loras, "autopipe", "ap", index, jid=jid)
            if not first:
                failed += 1
                job_log(jid, "第 %d 张失败：%s" % (index + 1, err))
                continue
            best = first
            if req.refine and not cancelled(jid):
                second = jobs._make_refine(exp, w, h, steps, cfg, seed, loras, label, model, first, req.denoise, jid=jid)
                if second:
                    best = second
                else:
                    failed += 1
            made.append({"path": best, "score": round(float(jobs.mirror_score(best)), 3)})
            JOBS[jid]["progress"] = (index + 1) / req.count * 0.9
            job_save(jid)
        made.sort(key=lambda item: item["score"])
        kept = []
        for item in made[:req.keep]:
            path = item["path"]
            if req.glitch > 0 and not cancelled(jid):
                import glitchify
                destination = os.path.splitext(path)[0] + "_glitch.png"
                glitchify.glitchify(path, destination, max(0.1, min(2.0, req.glitch)))
                path = destination
            kept.append({"path": path, "score": item["score"]})
        _summary(jid, len(made), failed, kept=kept, all=made)
    except Exception as exc:
        finish(jid, "error", result={"error": str(exc)[:300]})
    finally:
        svc_mem.release_stage(context="batch", reason="autopipe", soft=svc_mem.get_policy().get("profile") == "aggressive")
