# -*- coding: utf-8 -*-
"""合作流水线共享状态持久化、中间件清理、日志落盘与 manifest 读取辅助。"""
import json
import os
import subprocess
import sys
import time

import store
from svc_obs import warn
from svc_state import COOP_DIR, COOP_ROOTS, COOP_STATE, DRAFT_RE, IMG_EXT, ROOT, img_allowed

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


def cleanup_coop_dir(out_dir, final, keep_mid=False):
    """默认清理采样中间件；开启保留开关后保留全部过程图与遮罩。"""
    if keep_mid or os.environ.get("SUNLOOM_KEEP_COOP") == "1":
        COOP_STATE["log"] = (COOP_STATE.get("log") or "") + "\n[cleanup] 已保留全部调试中间件"
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
        COOP_STATE["log"] = (COOP_STATE.get("log") or "") + "\n[cleanup] 删除中间件 %d 个" % removed
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


def persist_coop_run():
    rid = COOP_STATE.get("id")
    if not rid:
        return
    try:
        store.upsert_coop_run({
            "id": rid,
            "started": COOP_STATE.get("started") or time.time(),
            "mode": COOP_STATE.get("mode") or "",
            "status": COOP_STATE.get("status") or "",
            "dir": COOP_STATE.get("dir") or "",
            "image": COOP_STATE.get("image") or "",
            "keep_intermediates": bool(COOP_STATE.get("keep_intermediates")),
            "log_tail": (COOP_STATE.get("log") or "")[-1200:],
        })
        store.trim_coop_runs(60)
    except Exception as e:
        warn("coop_run_persist", e, rid)


def coop_worker(args):
    keep_mid = bool(COOP_STATE.get("keep_intermediates"))
    out_dir_known = COOP_STATE.get("dir") or ""
    COOP_STATE.update(status="running", started=time.time(), log="", image="",
                      phase="准备", progress=0.02, phase_at=time.time())
    all_lines, log_fp = [], None
    try:
        if out_dir_known:
            try:
                os.makedirs(out_dir_known, exist_ok=True)
                log_fp = open(os.path.join(out_dir_known, "coop.log"), "a", encoding="utf-8")
            except Exception as e:
                warn("coop_log_open", e, out_dir_known)
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.Popen([sys.executable, COOP_STATE.get("tool") or COOP_TOOL] + args,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", env=env)
        lines = []
        for line in proc.stdout:
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
            _labels = (("采样", "采样", "保存") if COOP_STATE.get("mode") == "regional"
                       else ("背景", "人物", "合成"))
            if low.startswith("[1"):
                COOP_STATE.update(phase=_labels[0], progress=0.15, phase_at=time.time())
            elif low.startswith("[2"):
                COOP_STATE.update(phase=_labels[1], progress=0.55, phase_at=time.time())
            elif low.startswith("[3"):
                COOP_STATE.update(phase=_labels[2], progress=0.85, phase_at=time.time())
            elif low.startswith("PROGRESS"):
                try:
                    frac = float(low.split()[1])
                    base, target = {"背景": (0.15, 0.55), "人物": (0.55, 0.85),
                                    "合成": (0.85, 0.99)}.get(COOP_STATE.get("phase", "背景"), (0.15, 0.55))
                    COOP_STATE["progress"] = round(base + (target - base) * max(0.0, min(1.0, frac)), 3)
                except Exception:
                    pass
            elif low.startswith("done:"):
                done = low.split("done:", 1)[1].strip()
                out_dir, final = resolve_coop_final(done)
                COOP_STATE["dir"] = out_dir
                COOP_STATE["image"] = final
                if log_fp is None and out_dir:
                    write_coop_log(out_dir, all_lines)
                cleanup_coop_dir(out_dir, final, keep_mid=keep_mid)
                COOP_STATE.update(phase="完成", progress=0.99)
            if len(lines) > 200:
                lines = lines[-120:]
            COOP_STATE["log"] = "\n".join(lines)[-4000:]
        proc.wait(timeout=1800)
        COOP_STATE["status"] = "done" if COOP_STATE.get("dir") else "error"
        if COOP_STATE["status"] == "done":
            COOP_STATE.update(progress=1.0, phase="完成")
    except Exception as exc:
        all_lines.append("EXC: " + str(exc))
        COOP_STATE.update(status="error", log=str(exc)[:800])
    finally:
        if log_fp is not None:
            try:
                log_fp.close()
            except Exception:
                pass
        elif COOP_STATE.get("dir"):
            write_coop_log(COOP_STATE["dir"], all_lines)
        persist_coop_run()


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
