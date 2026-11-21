# -*- coding: utf-8 -*-
"""任务与 Comfy prompt 的归属、取消和终态写入。"""
from fastapi import HTTPException

import comfy as cf
from svc_state import JOBS, JOB_LOCK, job_save

ACTIVE = ("running", "queued", "pending", "starting")


def cancelled(jid):
    with JOB_LOCK:
        job = JOBS.get(jid) or {}
        parent = JOBS.get(job.get("parent_id")) or {}
        return job.get("status") == "cancelled" or parent.get("status") == "cancelled"


def finish(jid, status, **values):
    with JOB_LOCK:
        job = JOBS.get(jid)
        if not job:
            return
        if cancelled(jid):
            job.update(status="cancelled", result={"error": "任务已取消"})
        else:
            job.update(status=status, **values)
        job_save(jid)


def bind_prompt(jid, prompt_id):
    if not jid:
        return
    with JOB_LOCK:
        job = JOBS.get(jid)
        if not job:
            return
        job["prompt_id"] = prompt_id
        was_cancelled = cancelled(jid)
        job_save(jid)
    if was_cancelled:
        cf.cancel_prompt(prompt_id)


def cancel(jid):
    with JOB_LOCK:
        job = JOBS.get(jid)
        if not job:
            raise HTTPException(404, "unknown job")
        if job.get("status") not in ACTIVE:
            return {"interrupted": False, "status": job.get("status")}
        if job.get("kind") in ("train", "tag"):
            raise HTTPException(409, "此接口不支持停止训练或打标进程")
        children = [j for j in JOBS.values() if j.get("parent_id") == jid and j.get("status") in ACTIVE]
        targets = [job] + children
        prompts = {j["prompt_id"] for j in targets if j.get("prompt_id")}
        for target in targets:
            target.update(status="cancelled", result={"error": "任务已取消"})
            job_save(target["id"])
    interrupted = any([cf.cancel_prompt(prompt) for prompt in prompts])
    return {"interrupted": interrupted, "status": "cancelled"}


def validate_parent(parent_id):
    if not parent_id:
        return
    with JOB_LOCK:
        if parent_id not in JOBS:
            raise HTTPException(400, "父任务不存在")
        if JOBS[parent_id].get("status") not in ACTIVE:
            raise HTTPException(409, "父任务已经结束")


def attach_parent(jid, parent_id):
    if not parent_id:
        return
    with JOB_LOCK:
        JOBS[jid]["parent_id"] = parent_id
        if cancelled(jid):
            JOBS[jid].update(status="cancelled", result={"error": "父任务已取消"})
        job_save(jid)
