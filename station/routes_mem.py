# -*- coding: utf-8 -*-
"""显存/内存监测、策略切换与阶段调度路由。"""
import os
import subprocess
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import comfy as cf
import svc_mem

router = APIRouter()


class MemoryFreeReq(BaseModel):
    soft: bool = False
    reason: str = "manual"


class MemoryPolicyReq(BaseModel):
    profile: Optional[str] = None
    soft_free_mb: Optional[int] = None
    hard_free_mb: Optional[int] = None
    comfy_idle_sec: Optional[int] = None
    ram_high_pct: Optional[float] = None
    unload_on_switch: Optional[bool] = None


class MemoryScheduleReq(BaseModel):
    action: str = "prepare"  # prepare | release | recover | free
    family: str = "anima"
    unet: str = ""
    reason: str = ""
    context: str = "coop"
    soft: bool = False
    force_unload: bool = False


@router.get("/api/memory")
def api_memory():
    return svc_mem.status_payload()


@router.get("/api/memory/events")
def api_memory_events(limit: int = 50):
    return svc_mem.events_payload(limit=limit)


@router.post("/api/memory/free")
def api_memory_free(req: Optional[MemoryFreeReq] = None):
    r = req or MemoryFreeReq()
    return svc_mem.manual_free(soft=r.soft, reason=r.reason)


@router.post("/api/memory/policy")
def api_memory_policy(req: MemoryPolicyReq):
    try:
        pol = svc_mem.set_policy(
            profile=req.profile,
            overrides={
                "soft_free_mb": req.soft_free_mb,
                "hard_free_mb": req.hard_free_mb,
                "comfy_idle_sec": req.comfy_idle_sec,
                "ram_high_pct": req.ram_high_pct,
                "unload_on_switch": req.unload_on_switch,
            },
        )
        return {"ok": True, "policy": pol}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/memory/schedule")
def api_memory_schedule(req: MemoryScheduleReq):
    act = (req.action or "prepare").strip().lower()
    if act == "prepare":
        return svc_mem.prepare_stage(
            req.family, unet=req.unet, reason=req.reason,
            context=req.context, force_unload=req.force_unload,
        )
    if act == "release":
        return svc_mem.release_stage(context=req.context, reason=req.reason, soft=req.soft)
    if act == "recover":
        return svc_mem.recover_oom(reason=req.reason, context=req.context)
    if act == "free":
        return svc_mem.manual_free(soft=req.soft, reason=req.reason or req.context)
    raise HTTPException(400, "不支持的调度动作: %s" % act)


@router.post("/api/comfy/free")
def api_comfy_free():
    res = svc_mem.manual_free(soft=False, reason="comfy_free")
    cf_res = res.get("comfy") or {}
    return {"ok": bool(cf_res.get("ok")), "error": cf_res.get("error", ""), "vram_free_mb": (res.get("after") or {}).get("vram_free_mb")}


@router.post("/api/comfy/restart")
def api_comfy_restart():
    """杀掉 ComfyUI 进程，交给 supervisor 自动拉起。"""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/FI", "IMAGENAME eq python.exe", "/FI", "WINDOWTITLE eq *"],
                           capture_output=True)
        return {"ok": True, "note": "supervisor 会在 60 秒内自动拉起"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
