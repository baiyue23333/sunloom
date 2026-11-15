# -*- coding: utf-8 -*-
"""站点可观测性：结构化告警缓冲、缓存状态与 SQLite/旧 JSON 一致性报告。"""
import json
import os
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _d in (os.path.join(_ROOT, "core"), os.path.join(_ROOT, "tools")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import comfy_paths
import store

_LOCK = threading.RLock()
_WARNINGS = []
_COUNTS = {}
_MAX_WARNINGS = 100


def warn(where, exc, detail=""):
    """记录一条结构化告警（不静默吞掉真实异常）。"""
    msg = f"{type(exc).__name__}: {exc}" if isinstance(exc, BaseException) else str(exc)
    entry = {
        "ts": round(time.time(), 3),
        "where": str(where or "unknown"),
        "error": msg[:300],
        "detail": str(detail or "")[:200],
    }
    with _LOCK:
        _WARNINGS.append(entry)
        if len(_WARNINGS) > _MAX_WARNINGS:
            del _WARNINGS[:-_MAX_WARNINGS]
        _COUNTS[entry["where"]] = _COUNTS.get(entry["where"], 0) + 1
    try:
        print(f"[warn:{entry['where']}] {entry['error']} {entry['detail']}".rstrip(), flush=True)
    except Exception:
        pass
    return entry


def clear_warnings():
    with _LOCK:
        n = len(_WARNINGS)
        _WARNINGS.clear()
        _COUNTS.clear()
        return n


def _json_count(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, (dict, list)):
            return len(data)
    except Exception as e:
        warn("obs_json_count", e, path)
    return None


def build_report(state_mod):
    """汇总告警、数据库计数、遗留 JSON 漂移、缓存签名与运行时状态。"""
    with _LOCK:
        recent = list(reversed(_WARNINGS[-30:]))
        counts = dict(_COUNTS)
        total = len(_WARNINGS)
    db_counts = store.table_counts()
    legacy = {
        "recipes": {
            "authoritative": "sqlite",
            "db": db_counts.get("recipes", 0),
            "json": _json_count(getattr(state_mod, "RECIPE_PATH", "")),
            "json_path": getattr(state_mod, "RECIPE_PATH", ""),
        },
        "templates": {
            "authoritative": "sqlite",
            "db": db_counts.get("templates", 0),
            "json": _json_count(getattr(state_mod, "TPL", "")),
            "json_path": getattr(state_mod, "TPL", ""),
        },
        "cards": {
            "authoritative": "sqlite+ref/cards/*.json",
            "db": db_counts.get("cards", 0),
            "json": _json_count(getattr(state_mod, "CARDS", "")),
            "json_path": getattr(state_mod, "CARDS", ""),
        },
    }
    for v in legacy.values():
        v["drifted"] = v["json"] is not None and v["json"] != v["db"]

    jobs = getattr(state_mod, "JOBS", {}) or {}
    coop = getattr(state_mod, "COOP_STATE", {}) or {}
    cache_sig = getattr(state_mod, "_LORA_CACHE_META", {}).get("sig")
    try:
        import svc_mem
        mem_snap = svc_mem.status_payload()
        mem_info = {
            "policy": (mem_snap.get("scheduler") or {}).get("policy"),
            "current_stage": (mem_snap.get("scheduler") or {}).get("current_stage"),
            "stats": (mem_snap.get("scheduler") or {}).get("stats"),
            "vram_free_gb": round(((mem_snap.get("comfy") or {}).get("vram_free") or 0) / 1e9, 2),
            "vram_total_gb": round(((mem_snap.get("comfy") or {}).get("vram_total") or 0) / 1e9, 2),
            "ram_percent": (mem_snap.get("ram") or {}).get("percent"),
        }
    except Exception:
        mem_info = None
    return {
        "warnings": {"total": total, "by_where": counts, "recent": recent},
        "db": db_counts,
        "legacy_drift": legacy,
        "cache": {
            "lora_meta_count": len(getattr(state_mod, "_LORA_META_CACHE", {}) or {}),
            "lora_cache_sig": list(cache_sig) if cache_sig else None,
            "comfy_paths_ttl_sec": getattr(comfy_paths, "_TTL", None),
        },
        "runtime": {
            "jobs_in_memory": len(jobs),
            "jobs_running": sum(1 for j in jobs.values() if j.get("status") == "running"),
            "coop_status": coop.get("status", "idle"),
            "coop_mode": coop.get("mode", ""),
        },
        "memory": mem_info,
    }
