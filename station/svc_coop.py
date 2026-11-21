# -*- coding: utf-8 -*-
"""合作流水线共享状态持久化、中间件清理、日志落盘与 manifest 读取辅助。"""
import json
import os
import queue
import subprocess
import sys
import threading
import time

import store
from svc_obs import warn
from svc_state import COOP_DIR, COOP_LOCK, COOP_ROOTS, COOP_STATE, DRAFT_RE, IMG_EXT, ROOT, img_allowed
from svc_paths import image_ok

COOP_TOOL = os.path.join(ROOT, "tools", "coop_render.py")


def resolve_coop_final(done):
    done = (done or "").strip().strip('"')
    if os.path.isfile(done):
        return os.path.dirname(done), done
    out = done
    for name in ("comp.png", "final.png"):
        p = os.path.join(out, name)
        if os.path.isfile(p):
            return out, p
    if os.path.isdir(out):
        for f in sorted(os.listdir(out)):
            if f.lower().startswith("final") and f.lower().endswith(IMG_EXT):
                return out, os.path.join(out, f)
    return out, ""


def publish_run(run, **changes):
    run.update(changes)
    with COOP_LOCK:
        if COOP_STATE.get("id") == run.get("id"):
            COOP_STATE.update(run)


def cleanup_coop_dir(out_dir, final, keep_mid=False, run=None):
    """默认清理采样中间件；开启保留开关后保留全部过程图与遮罩。"""
    run = COOP_STATE if run is None else run
    if keep_mid or os.environ.get("SUNLOOM_KEEP_COOP") == "1":
        publish_run(run, log=(run.get("log") or "") + "\n[cleanup] 已保留全部调试中间件")
        return 0
    if not out_dir or not os.path.isdir(out_dir):
        return 0
    keep = os.path.basename(final or "")
    removed = 0
    for f in os.listdir(out_dir):
        p = os.path.join(out_dir, f)
        if not os.path.isfile(p) or f == keep or f.lower().endswith((".json", ".log")):
            continue
        stem = os.path.splitext(f)[0].lower()
        if (DRAFT_RE.search(stem) or stem.startswith(("char", "plate", "lift_", "comp_raw", "bg_", "alpha", "_layer"))
                or "_raw" in stem):
            try:
                os.remove(p)
                removed += 1
            except Exception as e:
                warn("coop_cleanup", e, p)
    if removed:
        publish_run(run, log=(run.get("log") or "") + "\n[cleanup] 删除中间件 %d 个" % removed)
    return removed


def write_coop_log(out_dir, lines):
    if not out_dir:
        return
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "coop.log"), "w", encoding="utf-8") as lf:
            lf.write("\n".join(lines) + ("\n" if lines else ""))
    except Exception as e:
        warn("coop_log_write", e, out_dir)


def persist_coop_run(run=None):
    with COOP_LOCK:
        run = dict(COOP_STATE if run is None else run)
    rid = run.get("id")
    if not rid:
        return
    try:
        store.upsert_coop_run({
            "id": rid,
            "started": run.get("started") or time.time(),
            "mode": run.get("mode") or "",
            "status": run.get("status") or "",
            "dir": run.get("dir") or "",
            "image": run.get("image") or "",
            "keep_intermediates": bool(run.get("keep_intermediates")),
            "error": run.get("error") or "",
            "log_tail": (run.get("log") or "")[-1200:],
        })
        store.trim_coop_runs(60)
    except Exception as e:
        warn("coop_run_persist", e, rid)


def _stream_lines(proc, timeout=1800):
    lines = queue.Queue()

    def pump():
        try:
            for line in proc.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            proc.kill()
            proc.wait(timeout=5)
            raise TimeoutError("合作子进程超时")
        try:
            line = lines.get(timeout=min(1.0, remaining))
        except queue.Empty:
            continue
        if line is None:
            return
        yield line


def coop_worker(args, run=None):
    with COOP_LOCK:
        run = dict(COOP_STATE if run is None else run)
    keep_mid = bool(run.get("keep_intermediates"))
    out_dir_known = run.get("dir") or ""
    publish_run(run, status="running", started=time.time(), log="", image="", error="",
                phase="准备", progress=0.02, phase_at=time.time())
    persist_coop_run(run)
    all_lines, log_fp = [], None
    try:
        if out_dir_known:
            try:
                os.makedirs(out_dir_known, exist_ok=True)
                log_fp = open(os.path.join(out_dir_known, "coop.log"), "a", encoding="utf-8")
            except Exception as e:
                warn("coop_log_open", e, out_dir_known)
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.Popen([sys.executable, run.get("tool") or COOP_TOOL] + args,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", env=env)
        lines = []
        for line in _stream_lines(proc):
            sline = line.rstrip()
            lines.append(sline)
            all_lines.append(sline)
            if log_fp is not None:
                try:
                    log_fp.write(sline + "\n")
                    log_fp.flush()
                except Exception:
                    pass
            low = line.strip()
            _labels = (("采样", "采样", "保存") if run.get("mode") == "regional"
                       else ("背景", "人物", "合成"))
            if low.startswith("[1"):
                publish_run(run, phase=_labels[0], progress=0.15, phase_at=time.time())
            elif low.startswith("[2"):
                publish_run(run, phase=_labels[1], progress=0.55, phase_at=time.time())
            elif low.startswith("[3"):
                publish_run(run, phase=_labels[2], progress=0.85, phase_at=time.time())
            elif low.startswith("PROGRESS"):
                try:
                    frac = float(low.split()[1])
                    base, target = {"背景": (0.15, 0.55), "人物": (0.55, 0.85),
                                    "合成": (0.85, 0.99)}.get(run.get("phase", "背景"), (0.15, 0.55))
                    publish_run(run, progress=round(base + (target - base) * max(0.0, min(1.0, frac)), 3))
                except Exception:
                    pass
            elif low.startswith("done:"):
                done = low.split("done:", 1)[1].strip()
                out_dir, final = resolve_coop_final(done)
                if not coop_dir_allowed(out_dir):
                    raise RuntimeError("合作输出目录越界")
                publish_run(run, dir=out_dir, image=final)
                if log_fp is None and out_dir:
                    write_coop_log(out_dir, all_lines)
            if len(lines) > 200:
                lines = lines[-120:]
            publish_run(run, log="\n".join(lines)[-4000:])
        code = proc.wait(timeout=10)
        if code != 0:
            raise RuntimeError("合作子进程退出码 %s" % code)
        final = run.get("image") or ""
        if not final or not image_ok(final):
            raise RuntimeError("合作任务未产出有效成图")
        cleanup_coop_dir(run["dir"], final, keep_mid=keep_mid, run=run)
        publish_run(run, status="done", progress=1.0, phase="完成")
    except Exception as exc:
        all_lines.append("EXC: " + str(exc))
        publish_run(run, status="error", error=str(exc)[:800], phase="失败",
                    log="\n".join(all_lines)[-4000:])
    finally:
        if log_fp is not None:
            try:
                log_fp.close()
            except Exception:
                pass
        elif run.get("dir"):
            write_coop_log(run["dir"], all_lines)
        persist_coop_run(run)


def coop_dir_allowed(d):
    try:
        rp = os.path.realpath(d)
    except Exception:
        return False
    for r in COOP_ROOTS:
        try:
            rr = os.path.realpath(r)
            if os.path.commonpath([rp, rr]) == rr:
                return True
        except ValueError:
            continue
    return img_allowed(rp)


def read_coop_manifest(target):
    out = {"dir": target, "manifest": None, "config": None, "mem_plan": None, "log": "", "steps_files": []}
    for key, fname in (("manifest", "manifest.json"), ("config", "reproj_cfg.json"), ("mem_plan", "mem_plan.json")):
        fp = os.path.join(target, fname)
        if os.path.isfile(fp):
            try:
                with open(fp, encoding="utf-8") as f:
                    out[key] = json.load(f)
            except Exception as e:
                warn("coop_manifest_read", e, fp)
    lp = os.path.join(target, "coop.log")
    if os.path.isfile(lp):
        try:
            with open(lp, encoding="utf-8", errors="replace") as f:
                out["log"] = f.read()[-24000:]
        except Exception as e:
            warn("coop_log_read", e, lp)
    steps_dir = os.path.join(target, "steps")
    if os.path.isdir(steps_dir):
        out["steps_files"] = sorted(
            os.path.join(steps_dir, x) for x in os.listdir(steps_dir) if x.lower().endswith(IMG_EXT)
        )
    return out


def list_coop_history(limit=16):
    seen, items = set(), []
    for r in store.load_coop_runs(limit):
        d = r.get("dir") or ""
        if d:
            seen.add(os.path.normpath(d))
        items.append({
            "id": r.get("id", ""), "name": os.path.basename(d) if d else r.get("id", ""),
            "dir": d, "image": r.get("image") or "", "mode": r.get("mode") or "",
            "status": r.get("status") or "", "ts": r.get("started") or 0,
            "has_manifest": bool(d and os.path.isfile(os.path.join(d, "manifest.json"))),
            "has_log": bool(d and os.path.isfile(os.path.join(d, "coop.log"))),
        })
    if os.path.isdir(COOP_DIR):
        for name in sorted(os.listdir(COOP_DIR), reverse=True)[:limit]:
            d = os.path.join(COOP_DIR, name)
            if not os.path.isdir(d) or os.path.normpath(d) in seen:
                continue
            _out, c = resolve_coop_final(d)
            items.append({
                "name": name, "dir": _out, "image": c, "mode": "reproject" if name.startswith("reproj_") else "",
                "status": "done" if c else "", "ts": os.path.getmtime(d),
                "has_manifest": os.path.isfile(os.path.join(_out, "manifest.json")),
                "has_log": os.path.isfile(os.path.join(_out, "coop.log")),
            })
    return items[:limit]
