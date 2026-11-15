# -*- coding: utf-8 -*-
"""统一显存与内存调度器：覆盖底模单图/批处理与合作模式多模型切换。"""
import gc
import os
import threading
import time

import comfy as cf
from svc_obs import warn

PROFILES = {
    "aggressive": {
        "soft_free_mb": 2200,
        "hard_free_mb": 1400,
        "unload_on_switch": True,
        "comfy_idle_sec": 120,
        "ram_high_pct": 85.0,
    },
    "balanced": {
        "soft_free_mb": 1600,
        "hard_free_mb": 950,
        "unload_on_switch": True,
        "comfy_idle_sec": 300,
        "ram_high_pct": 88.0,
    },
    "performance": {
        "soft_free_mb": 1100,
        "hard_free_mb": 650,
        "unload_on_switch": False,
        "comfy_idle_sec": 600,
        "ram_high_pct": 92.0,
    },
}

_LOCK = threading.RLock()
_INIT_PROFILE = os.environ.get("SUNLOOM_MEM_PROFILE", "balanced").strip().lower()
if _INIT_PROFILE not in PROFILES:
    _INIT_PROFILE = "balanced"

_POLICY = {"profile": _INIT_PROFILE, **PROFILES[_INIT_PROFILE]}
if os.environ.get("SUNLOOM_COMFY_IDLE", "").strip().isdigit():
    _POLICY["comfy_idle_sec"] = int(os.environ["SUNLOOM_COMFY_IDLE"])

_STAGE = {"family": "", "unet": "", "since": 0.0, "hits": 0}
_STATS = {
    "keep_hits": 0,
    "soft_frees": 0,
    "hard_unloads": 0,
    "switch_unloads": 0,
    "oom_recoveries": 0,
    "ram_trims": 0,
    "idle_frees": 0,
    "manual_frees": 0,
    "reclaimed_vram_mb": 0,
}
_EVENTS = []
_MAX_EVENTS = 80
_STATE_MOD = None


def _state():
    global _STATE_MOD
    if _STATE_MOD is None:
        import svc_state
        _STATE_MOD = svc_state
    return _STATE_MOD


def _mb(raw):
    if raw is None:
        return None
    try:
        return round(float(raw) / (1024.0 * 1024.0))
    except Exception:
        return None


def _sys_snapshot():
    """采集当前进程 RAM 与 ComfyUI GPU 显存快照（MiB）。"""
    ram_total_gb, ram_used_gb, ram_free_gb, ram_pct, rss_mb = 0.0, 0.0, 0.0, 0.0, 0
    try:
        import psutil
        vm = psutil.virtual_memory()
        proc = psutil.Process()
        ram_total_gb = round(vm.total / 1e9, 1)
        ram_used_gb = round(vm.used / 1e9, 1)
        ram_free_gb = round(vm.available / 1e9, 1)
        ram_pct = round(float(vm.percent), 1)
        rss_mb = round(proc.memory_info().rss / 1e6)
    except Exception:
        pass
    cs = cf.system_stats() or {}
    return {
        "ram": {"total_gb": ram_total_gb, "used_gb": ram_used_gb, "free_gb": ram_free_gb, "percent": ram_pct},
        "station_mb": rss_mb,
        "comfy": cs,
        "vram_total_mb": _mb(cs.get("vram_total")),
        "vram_free_mb": _mb(cs.get("vram_free")),
    }


def _record(context, action, from_s, to_s, vram_before, vram_after, ram_pct, reason=""):
    reclaimed = 0
    if vram_before is not None and vram_after is not None and vram_after > vram_before:
        reclaimed = int(vram_after - vram_before)
        if reclaimed > 0:
            _STATS["reclaimed_vram_mb"] += reclaimed
    row = {
        "ts": round(time.time(), 3),
        "context": str(context or "base"),
        "action": str(action),
        "from_stage": from_s,
        "to_stage": to_s,
        "vram_before_mb": vram_before,
        "vram_after_mb": vram_after,
        "reclaimed_mb": reclaimed,
        "ram_pct": ram_pct,
        "reason": str(reason or "")[:120],
    }
    _EVENTS.append(row)
    if len(_EVENTS) > _MAX_EVENTS:
        del _EVENTS[:-_MAX_EVENTS]
    return row


def _trim_python_memory(aggressive=False):
    """回收 Python 临时缓冲与已完成任务的冗余内存日志（不动 SQLite）。"""
    gc.collect()
    st = _state()
    if aggressive:
        for j in list((getattr(st, "JOBS", None) or {}).values()):
            if j.get("status") != "running" and len(j.get("logs") or []) > 40:
                j["logs"] = j["logs"][-40:]
    _STATS["ram_trims"] += 1


def _do_comfy_free(unload_models, note="", wait_settle=False):
    r = cf.free(unload_models=unload_models, free_memory=True)
    if r.get("ok"):
        st = _state()
        st.MEM_LAST_FREE[0] = time.time()
        if unload_models:
            st.MEM_COMFY_FREED[0] += 1
        if wait_settle:
            time.sleep(0.35)
    return r


def get_policy():
    with _LOCK:
        return dict(_POLICY)


def set_policy(profile=None, overrides=None):
    """切换预设档位并允许覆盖单项阈值。"""
    with _LOCK:
        if profile is not None:
            p = str(profile).strip().lower()
            if p not in PROFILES:
                raise ValueError("未知内存策略档位: %s（可选 %s）" % (p, list(PROFILES)))
            _POLICY.clear()
            _POLICY.update({"profile": p, **PROFILES[p]})
        ov = overrides or {}
        for key in ("soft_free_mb", "hard_free_mb", "comfy_idle_sec"):
            if key in ov and ov[key] is not None:
                _POLICY[key] = max(0, int(ov[key]))
        if "ram_high_pct" in ov and ov["ram_high_pct"] is not None:
            _POLICY["ram_high_pct"] = max(50.0, min(99.0, float(ov["ram_high_pct"])))
        if "unload_on_switch" in ov and ov["unload_on_switch"] is not None:
            _POLICY["unload_on_switch"] = bool(ov["unload_on_switch"])
        return dict(_POLICY)


def _norm_stage(family, unet=""):
    fam = str(family or "anima").strip().lower() or "anima"
    un = str(unet or "").strip()
    if fam == "anima" and not un:
        un = "anima-base-v1.0.safetensors"
    return fam, un


def prepare_stage(family, unet="", reason="", context="base", force_unload=False):
    """进入生成/检测/抠图阶段前的智能显存调度。

    规则：
    1) 同家族且同 UNET：优先保留热模型（keep），仅在低于 soft/hard 水位时清缓存或强卸；
    2) 切换模型家族（如 anima <-> sdpose / birefnet / upscale / other）或更换 UNET：
       按策略触发 switch_unload 先释放旧权重，避免 8GB GPU 碎片化挤压与 OOM。
    """
    fam, un = _norm_stage(family, unet)
    target_label = "%s:%s" % (fam, os.path.basename(un) if un else "-")
    with _LOCK:
        st_mod = _state()
        st_mod.MEM_LAST_JOB[0] = time.time()
        snap = _sys_snapshot()
        ram_pct = snap["ram"]["percent"]
        vb = snap["vram_free_mb"]
        vt = snap["vram_total_mb"] or 0
        from_label = "%s:%s" % (_STAGE["family"], os.path.basename(_STAGE["unet"]) or "-") if _STAGE["family"] else "none"

        if not snap["comfy"].get("up"):
            _STAGE.update(family=fam, unet=un, since=time.time(), hits=1)
            row = _record(context, "skip_offline", from_label, target_label, vb, vb, ram_pct, reason)
            return {"action": "skip_offline", "event": row, "stage": dict(_STAGE)}

        same_stage = (_STAGE["family"] == fam and _STAGE["unet"] == un)
        soft_floor = int(_POLICY["soft_free_mb"])
        hard_floor = int(_POLICY["hard_free_mb"])
        action = "keep"
        need_unload = False
        need_soft = False

        if force_unload:
            action, need_unload = "hard_unload", True
        elif same_stage:
            if vb is not None and vb < hard_floor:
                action, need_unload = "hard_unload", True
            elif vb is not None and vb < soft_floor:
                action, need_soft = "soft_free", True
            else:
                _STATS["keep_hits"] += 1
        else:
            prev_exists = bool(_STAGE["family"])
            gpu_nearly_empty = (vt > 0 and vb is not None and vb >= vt * 0.85)
            if prev_exists and _POLICY["unload_on_switch"] and not gpu_nearly_empty:
                action, need_unload = "switch_unload", True
            elif vb is not None and vb < hard_floor:
                action, need_unload = "hard_unload", True
            elif vb is not None and vb < soft_floor:
                action, need_soft = "soft_free", True
            else:
                _STATS["keep_hits"] += 1

        if need_unload:
            r = _do_comfy_free(unload_models=True, note=reason, wait_settle=True)
            _trim_python_memory(aggressive=(ram_pct >= _POLICY["ram_high_pct"]))
            if r.get("ok"):
                if action == "switch_unload":
                    _STATS["switch_unloads"] += 1
                else:
                    _STATS["hard_unloads"] += 1
            else:
                action = "unload_fail"
        elif need_soft:
            r = _do_comfy_free(unload_models=False, note=reason, wait_settle=False)
            if ram_pct >= _POLICY["ram_high_pct"]:
                _trim_python_memory(aggressive=True)
            if r.get("ok"):
                _STATS["soft_frees"] += 1
            else:
                action = "soft_fail"
        elif ram_pct >= _POLICY["ram_high_pct"]:
            _trim_python_memory(aggressive=True)

        after = _sys_snapshot() if (need_unload or need_soft) else snap
        va = after["vram_free_mb"]
        if same_stage and not need_unload:
            _STAGE["hits"] = int(_STAGE.get("hits") or 0) + 1
        else:
            _STAGE.update(family=fam, unet=un, since=time.time(), hits=1)

        row = _record(context, action, from_label, target_label, vb, va, after["ram"]["percent"], reason)
        if action != "keep":
            print("[mem:%s] %s %s -> %s vram=%s->%sMB (%s)" % (
                context, action, from_label, target_label, vb, va, reason[:40]), flush=True)
        return {"action": action, "event": row, "stage": dict(_STAGE), "vram_free_mb": va}


def release_stage(context="base", reason="", soft=False, trim_ram=True):
    """阶段结束后按需清理 Python 对象，可选轻量清 ComfyUI 缓存（不卸热模）。"""
    with _LOCK:
        snap = _sys_snapshot()
        ram_pct = snap["ram"]["percent"]
        vb = snap["vram_free_mb"]
        from_label = "%s:%s" % (_STAGE["family"], os.path.basename(_STAGE["unet"]) or "-") if _STAGE["family"] else "none"
        high_ram = ram_pct >= float(_POLICY["ram_high_pct"])
        if trim_ram or high_ram:
            _trim_python_memory(aggressive=high_ram)
        if not soft and not (vb is not None and vb < int(_POLICY["hard_free_mb"])):
            return {"action": "ram_gc" if high_ram else "noop", "ram_pct": ram_pct, "vram_free_mb": vb}

        if not snap["comfy"].get("up"):
            return {"action": "skip_offline", "ram_pct": ram_pct, "vram_free_mb": vb}
        unload = bool(vb is not None and vb < int(_POLICY["hard_free_mb"]))
        r = _do_comfy_free(unload_models=unload, note=reason, wait_settle=unload)
        act = ("hard_unload" if unload else "soft_free") if r.get("ok") else "release_fail"
        if r.get("ok"):
            if unload:
                _STATS["hard_unloads"] += 1
                _STAGE.update(family="", unet="", since=0.0, hits=0)
            else:
                _STATS["soft_frees"] += 1
        va = _sys_snapshot()["vram_free_mb"]
        row = _record(context, act, from_label, from_label, vb, va, ram_pct, reason)
        return {"action": act, "event": row, "vram_free_mb": va}


def recover_oom(reason="", context="base"):
    """检测到 CUDA OOM / alloc failed 时强制卸载模型并触发 GC，供上游安全重试一次。"""
    with _LOCK:
        snap = _sys_snapshot()
        vb = snap["vram_free_mb"]
        from_label = "%s:%s" % (_STAGE["family"], os.path.basename(_STAGE["unet"]) or "-") if _STAGE["family"] else "none"
        r = _do_comfy_free(unload_models=True, note="oom:" + reason, wait_settle=True)
        _trim_python_memory(aggressive=True)
        _STAGE.update(family="", unet="", since=0.0, hits=0)
        _STATS["oom_recoveries"] += 1
        after = _sys_snapshot()
        va = after["vram_free_mb"]
        row = _record(context, "oom_recover" if r.get("ok") else "oom_recover_fail",
                      from_label, "none", vb, va, after["ram"]["percent"], reason)
        warn("mem_oom_recover", RuntimeError("VRAM OOM recovery triggered"), "%s vram=%s->%sMB" % (reason, vb, va))
        return {"ok": bool(r.get("ok")), "event": row, "vram_free_mb": va}


def manual_free(soft=False, reason="manual"):
    """用户手动触发释放（soft=True 只清碎片保热模型）。"""
    with _LOCK:
        before = _sys_snapshot()
        vb = before["vram_free_mb"]
        from_label = "%s:%s" % (_STAGE["family"], os.path.basename(_STAGE["unet"]) or "-") if _STAGE["family"] else "none"
        cr = _do_comfy_free(unload_models=not soft, note=reason, wait_settle=not soft)
        _trim_python_memory(aggressive=True)
        _STATS["manual_frees"] += 1
        if not soft and cr.get("ok"):
            _STAGE.update(family="", unet="", since=0.0, hits=0)
        after = _sys_snapshot()
        va = after["vram_free_mb"]
        act = "manual_soft_free" if soft else "manual_free"
        row = _record("manual", act, from_label, from_label if soft else "none", vb, va, after["ram"]["percent"], reason)
        return {
            "ok": True,
            "soft": bool(soft),
            "comfy": cr,
            "before": {"free_gb": before["ram"]["free_gb"], "station_mb": before["station_mb"], "vram_free_mb": vb},
            "after": {"free_gb": after["ram"]["free_gb"], "station_mb": after["station_mb"], "vram_free_mb": va},
            "event": row,
        }


def idle_tick(running_jobs, coop_running, last_job_ts):
    """后台巡检：闲置超时按策略释放 ComfyUI，高 RAM 水位主动收缩 Python 缓冲。"""
    if running_jobs or coop_running:
        return None
    with _LOCK:
        snap = _sys_snapshot()
        ram_pct = snap["ram"]["percent"]
        if ram_pct >= float(_POLICY["ram_high_pct"]):
            _trim_python_memory(aggressive=True)
            vb = snap["vram_free_mb"]
            if snap["comfy"].get("up") and cf.queue_state().get("running", 0) == 0 and _STAGE["family"]:
                r = _do_comfy_free(unload_models=False, note="ram_high", wait_settle=False)
                if r.get("ok"):
                    _STATS["soft_frees"] += 1
                    va = _sys_snapshot()["vram_free_mb"]
                    return _record("idle", "ram_high_trim", _STAGE["family"], _STAGE["family"], vb, va, ram_pct, "RAM %.1f%%" % ram_pct)

        idle = int(_POLICY["comfy_idle_sec"])
        if idle > 0 and time.time() - float(last_job_ts) > idle:
            if snap["comfy"].get("up") and cf.queue_state().get("running", 0) == 0 and (_STAGE["family"] or (snap["vram_free_mb"] or 0) < (snap["vram_total_mb"] or 0) * 0.7):
                vb = snap["vram_free_mb"]
                from_label = _STAGE["family"] or "unknown"
                r = _do_comfy_free(unload_models=True, note="idle", wait_settle=False)
                if r.get("ok"):
                    _STAGE.update(family="", unet="", since=0.0, hits=0)
                    _STATS["idle_frees"] += 1
                    va = _sys_snapshot()["vram_free_mb"]
                    print("[memory] comfy models freed (idle=%ds)" % idle, flush=True)
                    return _record("idle", "idle_free", from_label, "none", vb, va, ram_pct, "idle>%ds" % idle)
    return None


def status_payload():
    """汇总 /api/memory 返回结构（完全向后兼容既有 ram/station_mb/comfy/auto 字段）。"""
    with _LOCK:
        snap = _sys_snapshot()
        st = _state()
        return {
            "ram": snap["ram"],
            "station_mb": snap["station_mb"],
            "comfy": snap["comfy"],
            "auto": {
                "comfy_idle_sec": int(_POLICY["comfy_idle_sec"]),
                "comfy_freed": st.MEM_COMFY_FREED[0],
                "last_free": int(st.MEM_LAST_FREE[0]),
            },
            "scheduler": {
                "policy": dict(_POLICY),
                "current_stage": dict(_STAGE),
                "stats": dict(_STATS),
                "recent_events": list(reversed(_EVENTS[-15:])),
            },
        }


def events_payload(limit=50):
    with _LOCK:
        lim = max(1, min(_MAX_EVENTS, int(limit or 50)))
        return {
            "policy": dict(_POLICY),
            "current_stage": dict(_STAGE),
            "stats": dict(_STATS),
            "events": list(reversed(_EVENTS[-lim:])),
        }
