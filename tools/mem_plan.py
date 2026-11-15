# -*- coding: utf-8 -*-
"""合作模式与子进程显存/内存调度器（接入站台 /api/memory/schedule，离线可自动回退）。"""
import gc
import json
import os
import subprocess
import time
import urllib.request

API = os.environ.get("SUNLOOM_API", "http://127.0.0.1:8770")
COMFY = os.environ.get("STATION_COMFY", os.environ.get("COMFY_API", "http://127.0.0.1:8188"))
_ROWS = []


def comfy_vram():
    """读取 ComfyUI /system_stats 显存快照 -> (free_mb, total_mb)，失败返回 (None, None)。"""
    try:
        with urllib.request.urlopen(COMFY + "/system_stats", timeout=2) as r:
            s = json.loads(r.read().decode("utf-8"))
        dev = (s.get("devices") or [{}])[0] if isinstance(s.get("devices"), list) else {}
        vf, vt = dev.get("vram_free"), dev.get("vram_total")
        if vf is not None and vt is not None:
            return round(float(vf) / (1024.0 * 1024.0)), round(float(vt) / (1024.0 * 1024.0))
    except Exception:
        pass
    return None, None


def vram():
    """当前显存已用量（MiB），优先算 ComfyUI total-free，回退 nvidia-smi。"""
    vf, vt = comfy_vram()
    if vf is not None and vt is not None:
        return max(0, int(vt - vf))
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=6).stdout.strip().split("\n")[0]
        return int(out)
    except Exception:
        return None


def rss_mb():
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1e6)
    except Exception:
        return None


def _post_json(url, body, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def free_comfy(reason="", unload_models=True):
    """请求站台释放 ComfyUI 显存；站台未起时直连 ComfyUI /free。"""
    ok, action = False, "manual_free" if unload_models else "soft_free"
    try:
        res = _post_json(API + "/api/memory/free", {"soft": not unload_models, "reason": reason or "coop"})
        ok = bool(res.get("ok", True))
    except Exception:
        try:
            _post_json(COMFY + "/free", {"unload_models": bool(unload_models), "free_memory": True}, timeout=20)
            ok = True
        except Exception:
            ok = False
    vf, vt = comfy_vram()
    _ROWS.append({"ts": round(time.time(), 1), "phase": action, "note": reason,
                  "ok": ok, "vram_free_mb": vf, "vram_total_mb": vt, "rss_mb": rss_mb()})
    return ok


def schedule(family, unet="", reason="", context="coop", force_unload=False):
    """在子进程各模型阶段切换前，向站台统一调度器申请预算/切换释放。"""
    try:
        res = _post_json(API + "/api/memory/schedule", {
            "action": "prepare", "family": family, "unet": unet,
            "reason": reason, "context": context, "force_unload": bool(force_unload),
        }, timeout=45)
        ev = res.get("event") or {}
        row = {
            "ts": round(time.time(), 1), "phase": "schedule:%s" % family,
            "action": res.get("action", "keep"), "note": reason,
            "vram_free_mb": res.get("vram_free_mb"), "reclaimed_mb": ev.get("reclaimed_mb", 0),
            "rss_mb": rss_mb(),
        }
        _ROWS.append(row)
        return res
    except Exception:
        vf, vt = comfy_vram()
        act = "offline_keep"
        if vf is not None and vf < 1200:
            free_comfy(reason=reason or family, unload_models=True)
            act = "offline_unload"
        return {"action": act, "vram_free_mb": vf}


def release(context="coop", reason="", soft=False):
    """阶段结束后触发站台 RAM 收缩与子进程 GC。"""
    gc.collect()
    try:
        return _post_json(API + "/api/memory/schedule", {
            "action": "release", "context": context, "reason": reason, "soft": bool(soft),
        }, timeout=30)
    except Exception:
        return {"action": "local_gc"}


def unload_llm(reason=""):
    """兼容旧调用（7B 本地 LLM 已下线，仅作阶段清理与记录）。"""
    gc.collect()
    vf, vt = comfy_vram()
    _ROWS.append({"ts": round(time.time(), 1), "phase": "unload_llm", "note": reason,
                  "ok": True, "vram_free_mb": vf, "vram_total_mb": vt, "rss_mb": rss_mb()})
    return True


class Plan:
    def __init__(self, context="coop"):
        self.t0 = time.time()
        self.context = context
        self.marks = []

    def mark(self, phase, note=""):
        vf, vt = comfy_vram()
        row = {
            "t": round(time.time() - self.t0, 1),
            "phase": phase,
            "note": note,
            "vram_free_mb": vf,
            "vram_total_mb": vt,
            "vram_mb": max(0, int(vt - vf)) if (vf is not None and vt is not None) else vram(),
            "rss_mb": rss_mb(),
        }
        self.marks.append(row)
        print("[mem] %-12s %-26s vram_free=%sMB rss=%sMB" % (
            phase[:12], note[:26], row["vram_free_mb"], row["rss_mb"]), flush=True)
        return row

    def schedule(self, family, unet="", note="", force_unload=False):
        res = schedule(family, unet=unet, reason=note or family, context=self.context, force_unload=force_unload)
        act = res.get("action", "keep")
        self.mark("sched:%s" % family, "%s (%s)" % (note or family, act))
        return res

    def trim_py(self, note=""):
        gc.collect()
        return self.mark("trim_py", note or "gc.collect")

    def free_comfy(self, note="", unload_models=True):
        ok = free_comfy(note, unload_models=unload_models)
        self.mark("free_comfy" if unload_models else "soft_free", note)
        return ok

    def unload_llm(self, note=""):
        self.mark("unload_llm", note)
        return unload_llm(note)

    def save(self, out_dir):
        path = os.path.join(out_dir, "mem_plan.json")
        try:
            os.makedirs(out_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"context": self.context, "total_sec": round(time.time() - self.t0, 1),
                           "marks": self.marks, "events": _ROWS[-80:]}, f, ensure_ascii=False, indent=1)
        except Exception as e:
            print("[mem] 保存失败: %s" % e, flush=True)
        return path
