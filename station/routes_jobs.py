# -*- coding: utf-8 -*-
"""出图任务、引擎体检、可观测性与回归检查路由（显存路由见 routes_mem.py）。"""
import json
import os
import re
import shutil
import threading
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import comfy as cf
import graph as gf
import store
from svc_jobs import (
    AutoPipeReq,
    BatchQReq,
    _run_autopipe,
    _run_batchq,
    _save_result,
    _submit,
)
from svc_recipes import (
    _fit_mask_to_reference,
    _make_mask,
    _normalize_mask,
    _prepare_reference,
)
from svc_obs import build_report, clear_warnings, warn
import svc_state
from svc_state import (
    CARDS,
    JOBS,
    LAST_GRAPH,
    RECIPE_PATH,
    ROOT,
    TPL,
    comfy_in,
    estimate_seconds,
    job_log,
    job_new,
    job_save,
    list_models,
    load_tokens,
)

router = APIRouter()


class RunReq(BaseModel):
    prompt: str
    negative: str = ""
    width: int = 1024
    height: int = 1536
    steps: int = 30
    cfg: float = 5.5
    seed: int = 0
    prefix: str = "station"
    loras: List[Dict[str, Any]] = []
    save_to: str = "station_out"
    mode: str = "t2i"          # t2i | i2i | inpaint
    blocks_pos: List[Dict[str, Any]] = []
    blocks_neg: List[Dict[str, Any]] = []
    reference: str = ""
    mask: str = ""
    denoise: float = 0.6
    model: str = ""
    expand_notes: List[str] = []
    client_meta: Dict[str, Any] = {}
    auto_handfix: bool = False


class MaskReq(BaseModel):
    image: str
    box: str
    prompt: str = ""
    negative: str = ""
    denoise: float = 0.45
    steps: int = 24
    cfg: float = 5.0
    seed: int = 0
    prefix: str = "handfix"
    loras: List[Dict[str, Any]] = []


class ReproReq(BaseModel):
    mode: str
    model: str = ""
    reference: str
    prompt: str = ""
    negative: str = ""
    denoise: float = 0.6
    width: int = 1024
    height: int = 1536
    steps: int = 30
    cfg: float = 5.5
    seed: int = 0
    prefix: str = "repro"
    loras: List[Dict[str, Any]] = []


class InpaintReq(BaseModel):
    image: str
    box: str = ""
    mask_b64: str = ""
    mask_feather: int = 0
    prompt: str = ""
    negative: str = ""
    denoise: float = 0.6
    steps: int = 26
    cfg: float = 5.2
    seed: int = 0
    prefix: str = "repaint"
    engine: str = "anima"
    loras: List[Dict[str, Any]] = []


class BatchReq(BaseModel):
    blocks_pos: List[Dict[str, Any]] = []
    blocks_neg: List[Dict[str, Any]] = []
    prompt: str
    negative: str = ""
    width: int = 1024
    height: int = 1536
    steps: int = 30
    cfg: float = 5.5
    count: int = 4
    seed_start: int = 0
    seed_step: int = 1
    prefix: str = "batch"
    loras: List[Dict[str, Any]] = []
    mode: str = "t2i"
    reference: str = ""


@router.post("/api/batch_quality")
def api_batch_quality(req: BatchQReq):
    jid = job_new("batchq", "batch")
    job_log(jid, "批量精品：%d 张，精修=%s" % (req.count, req.refine))
    threading.Thread(target=lambda: _run_batchq(req, jid), daemon=True).start()
    return {"job_id": jid, "count": req.count}


@router.post("/api/autopipe")
def api_autopipe(req: AutoPipeReq):
    jid = job_new("autopipe", "auto")
    job_log(jid, "一条龙：%d 张 → 保留 %d，故障 %s" % (req.count, req.keep, req.glitch))
    threading.Thread(target=lambda: _run_autopipe(req, jid), daemon=True).start()
    return {"job_id": jid}


@router.get("/api/job/{jid}")
def job_get(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "unknown job")
    j["elapsed"] = round(time.time() - j["started"], 1)
    return j


@router.get("/api/reliability")
def api_reliability():
    """优先读取结构化 meta.reliability，缺省时兼容旧备注里的「实测(…)」。"""
    tokens, lib, _ = load_tokens()
    lib = lib or {}
    struct_map = (lib.get("meta") or {}).get("reliability") or lib.get("reliability") or {}
    notes = lib.get("notes") or {}
    out, details = {}, {}
    structured_cnt, legacy_cnt = 0, 0
    for k in tokens:
        s_entry = struct_map.get(k)
        if isinstance(s_entry, dict) and s_entry.get("status") in ("OK", "X", "?"):
            st = s_entry["status"]
            out[k] = st
            details[k] = {"status": st, "note": s_entry.get("note", ""),
                          "source": "structured", "updated_at": s_entry.get("updated_at")}
            structured_cnt += 1
            continue
        if isinstance(s_entry, str) and s_entry in ("OK", "X", "?"):
            out[k] = s_entry
            details[k] = {"status": s_entry, "note": "", "source": "structured", "updated_at": None}
            structured_cnt += 1
            continue
        n = notes.get(k) or ""
        idx = n.rfind("实测(")
        if idx < 0:
            continue
        tail = n[idx:]
        st = "X" if "失败" in tail else ("OK" if ("成功" in tail or "成立" in tail) else "?")
        out[k] = st
        details[k] = {"status": st, "note": tail, "source": "legacy_note", "updated_at": None}
        legacy_cnt += 1
    return {
        "items": out, "total": len(out), "x": sum(1 for v in out.values() if v == "X"),
        "structured": structured_cnt, "legacy_parsed": legacy_cnt, "details": details,
    }


@router.post("/api/run")
def api_run(req: RunReq):
    if req.mode not in ("t2i", "i2i", "inpaint"):
        raise HTTPException(400, "不支持的模式: %s" % req.mode)
    if req.model and req.model not in set(list_models()):
        raise HTTPException(400, "未知底模: %s" % req.model)
    if not req.prompt.strip():
        raise HTTPException(400, "empty prompt")
    prefix = re.sub(r"[^A-Za-z0-9_\-]", "_", req.prefix or "station")[:40]
    seed = req.seed or int(time.time()) % 1000000
    jid = job_new("run", prefix)
    params = {"prompt": req.prompt, "negative": req.negative, "width": req.width, "height": req.height,
              "steps": req.steps, "cfg": req.cfg, "seed": seed, "prefix": prefix,
              "loras": req.loras, "save_to": req.save_to, "denoise": req.denoise,
              "blocks_pos": req.blocks_pos, "blocks_neg": req.blocks_neg, "model": req.model,
              "expand_notes": req.expand_notes, "client_meta": req.client_meta,
              "auto_handfix": bool(req.auto_handfix)}
    inp = comfy_in()
    if req.mode in ("i2i", "inpaint"):
        params["reference"] = _prepare_reference(req.reference)
    if req.mode == "inpaint":
        params["mask"] = req.mask or _make_mask(os.path.join(inp, params["reference"]), "0,0,10,10")
    if req.mask:
        if not os.path.isfile(os.path.join(inp, req.mask)):
            saved = os.path.join(ROOT, "SD-Picture", "masks", req.mask)
            if os.path.isfile(saved):
                shutil.copy2(saved, os.path.join(inp, req.mask))
        try:
            _normalize_mask(os.path.join(inp, params["mask"]), 0)
        except Exception as e:
            warn("mask_normalize", e, params.get("mask", ""))
        params["mask"] = _fit_mask_to_reference(params["reference"], params["mask"])
    threading.Thread(target=lambda: _submit(req.mode, params, jid, prefix), daemon=True).start()
    return {"job_id": jid, "seed": seed, "estimate": estimate_seconds(req.width, req.height, req.steps, model=req.model),
            "mode": req.mode}


@router.post("/api/inpaint")
def api_inpaint(req: InpaintReq):
    """通用局部重绘：框内按给的提示词重画，框外不动。"""
    import base64
    if not req.box and not req.mask_b64:
        raise HTTPException(400, "需要 box 或 mask_b64")
    if not os.path.isfile(req.image):
        raise HTTPException(400, "底图不存在")
    inp = comfy_in()
    ref_name = _prepare_reference(req.image)
    ref_path = os.path.join(inp, ref_name)
    if req.mask_b64:
        raw = req.mask_b64.split(",", 1)[-1]
        try:
            data = base64.b64decode(raw)
        except Exception:
            raise HTTPException(400, "蒙版解码失败")
        mask_name = "mask_br_%s.png" % time.strftime("%H%M%S")
        with open(os.path.join(inp, mask_name), "wb") as f:
            f.write(data)
    else:
        mask_name = _make_mask(ref_path, req.box)
    try:
        _normalize_mask(os.path.join(inp, mask_name), req.mask_feather or 0)
    except Exception as e:
        print("[mask-normalize] failed:", e, flush=True)
    mask_name = _fit_mask_to_reference(ref_name, mask_name)
    prompt = req.prompt or "same character, same art style, detailed"
    negative = req.negative or "extra fingers, deformed hands, bad anatomy, watermark, text, lowres"
    seed = req.seed or int(time.time()) % 1000000
    wf_name = "anima_inpaint"
    jid = job_new("repaint", req.prefix)
    params = {"prompt": prompt, "negative": negative,
              "width": 1024, "height": 1536, "steps": req.steps, "cfg": req.cfg, "seed": seed,
              "prefix": req.prefix, "loras": req.loras, "denoise": req.denoise,
              "reference": ref_name, "mask": mask_name, "save_to": "station_out"}
    threading.Thread(target=lambda: _submit("inpaint", params, jid, req.prefix, wf_name=wf_name), daemon=True).start()
    return {"job_id": jid, "seed": seed, "mask": mask_name, "denoise": req.denoise,
            "engine": "anima", "workflow": wf_name, "box": req.box, "feather": req.mask_feather}


@router.post("/api/handfix")
def api_handfix(req: MaskReq):
    if not req.box:
        raise HTTPException(400, "需要 box")
    ref_name = _prepare_reference(req.image)
    ref_path = os.path.join(comfy_in(), ref_name)
    mask_name = _make_mask(ref_path, req.box)
    prompt = req.prompt or "detailed hand, natural fingers, correct anatomy, smooth shading, same art style"
    negative = req.negative or "extra fingers, fused fingers, missing fingers, deformed hands, bad anatomy, watermark, text, lowres"
    seed = req.seed or int(time.time()) % 1000000
    wf_name = "anima_inpaint"
    jid = job_new("handfix", req.prefix)
    params = {"prompt": prompt, "negative": negative,
              "width": 1024, "height": 1536, "steps": req.steps, "cfg": req.cfg, "seed": seed,
              "prefix": req.prefix, "loras": req.loras, "denoise": req.denoise,
              "reference": ref_name, "mask": mask_name, "save_to": "station_out"}
    threading.Thread(target=lambda: _submit("inpaint", params, jid, req.prefix, wf_name=wf_name), daemon=True).start()
    return {"job_id": jid, "seed": seed, "mask": mask_name, "denoise": req.denoise, "engine": "anima", "workflow": wf_name}


@router.post("/api/reproduce")
def api_reproduce(req: ReproReq):
    """复现模式：keep_person=保人物换画面；keep_image=保画面换人物。"""
    ref_name = _prepare_reference(req.reference)
    seed = req.seed or int(time.time()) % 1000000
    loras = req.loras
    if req.mode == "keep_image" and loras:
        loras = [{"name": x["name"], "weight": min(0.85, float(x.get("weight", 0.5)) + 0.1)} for x in loras]
    jid = job_new("repro_" + req.mode, req.prefix)
    params = {"prompt": req.prompt, "negative": req.negative, "width": req.width, "height": req.height,
              "steps": req.steps, "cfg": req.cfg, "seed": seed, "prefix": req.prefix,
              "loras": loras, "denoise": req.denoise, "reference": ref_name, "save_to": "station_out"}
    threading.Thread(target=lambda: _submit("i2i", params, jid, req.prefix), daemon=True).start()
    return {"job_id": jid, "seed": seed, "mode": req.mode, "denoise": req.denoise}


@router.post("/api/batch")
def api_batch(req: BatchReq):
    if not req.prompt.strip():
        raise HTTPException(400, "empty prompt")
    count = max(1, min(12, req.count))
    seeds = [(req.seed_start or int(time.time()) % 1000000) + i * max(1, req.seed_step) for i in range(count)]
    jid = job_new("batch", req.prefix)
    JOBS[jid]["items"] = [{"seed": s, "status": "pending", "image": ""} for s in seeds]

    def work():
        done = 0
        for idx, seed in enumerate(seeds):
            try:
                params = {"prompt": req.prompt, "negative": req.negative, "width": req.width,
                          "height": req.height, "steps": req.steps, "cfg": req.cfg, "seed": seed,
                          "prefix": "%s_%02d" % (req.prefix, idx + 1), "loras": req.loras,
                          "denoise": 1.0, "blocks_pos": req.blocks_pos, "blocks_neg": req.blocks_neg}
                if req.mode == "i2i":
                    params["reference"] = _prepare_reference(req.reference)
                wf, meta = gf.build("anima_i2i" if req.mode == "i2i" else "anima_t2i", params)
                if meta["missing"]:
                    raise RuntimeError("缺节点: " + ", ".join(meta["missing"]))
                pid = gf.submit(wf)
                res = cf.wait(pid, timeout=1800)
                if not res["ok"]:
                    raise RuntimeError(str(res.get("error")))
                saved = [x for x in (_save_result(im, params["prefix"], seed) for im in res["images"]) if x]
                JOBS[jid]["items"][idx].update(status="done", image=saved[0] if saved else "")
                job_log(jid, "done %d/%d seed=%d" % (idx + 1, count, seed))
            except Exception as e:
                JOBS[jid]["items"][idx].update(status="error", error=str(e)[:200])
                job_log(jid, "ERR %d: %s" % (idx + 1, str(e)[:160]))
            done += 1
            JOBS[jid]["progress"] = done / float(count)
        JOBS[jid].update(status="done", result={"items": JOBS[jid]["items"]})

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid, "count": count, "seeds": seeds}


@router.get("/api/last-graph")
def api_last_graph():
    return LAST_GRAPH or {}


@router.get("/api/engine")
def api_engine():
    info = gf.engine_info()
    try:
        info["queue"] = cf.queue_state()
    except Exception:
        info["queue"] = {"running": 0, "pending": 0}
    return info


def run_regress():
    """静态不变量检查：文档/数据/图/模板是否互相一致。"""
    checks = []

    def add(name, ok, detail, fix=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "fix": fix})

    tokens, lib, ch = load_tokens()
    notes = lib.get("notes", {})

    bad_left = []
    for tpl in store.load_templates():
        for b in (tpl.get("positive") or []) + (tpl.get("negative") or []):
            tok = b.get("token")
            if tok and tok not in tokens:
                bad_left.append(tpl.get("name", "?") + ":" + tok)
    add("模板引用的宏都存在", not bad_left, ", ".join(bad_left[:5]) or "OK",
        "模板里引用了不存在的积木，去词库补或从模板删")

    lib_tokens = lib.get("tokens") or {}
    untested = [k for k in lib_tokens if k.startswith("@") and k not in notes]
    add("每个积木有备注", len(untested) == 0, "%d 个缺备注" % len(untested),
        "缺备注：" + ", ".join(untested[:5]))

    up = cf.system_stats()["up"]
    add("ComfyUI 在线", up, "在线" if up else "离线，节点检查已跳过",
        "启动 ComfyUI（引擎页有一键启动），或等 supervisor 自动拉起")
    if up:
        have_nodes = gf.comfy_nodes(force=True)
        missing_wf = []
        for name in gf.list_workflows():
            wf = gf.load(name)
            miss = [n for n in wf.get("requires", []) if n not in have_nodes]
            if miss:
                missing_wf.append(name + ":" + ",".join(miss))
        add("工作流所需节点齐全", not missing_wf, "; ".join(missing_wf) or "OK",
            "ComfyUI 版本变化或缺自定义节点；在「引擎」页查看")
    else:
        add("工作流所需节点齐全", False, "跳过（ComfyUI 离线）", "先启动 ComfyUI")

    dup = []
    for name in gf.list_workflows():
        wf = gf.load(name)
        if "nodes" not in wf or not wf.get("nodes"):
            dup.append(name)
    add("工作流 JSON 结构完整", not dup, ", ".join(dup) or "OK", "缺 sampler/nodes 字段")
    add("两套服装存在", all(k in (ch.get("garments") or {}) for k in ("slip", "casual_knit")),
        ", ".join((ch.get("garments") or {}).keys()), "补 character.json")
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


@router.get("/api/regress")
def api_regress():
    return run_regress()


@router.post("/api/cancel/{jid}")
def api_cancel(jid: str):
    ok = cf.interrupt()
    j = JOBS.get(jid)
    if j:
        j["status"] = "cancelled"
        job_save(jid)
    return {"interrupted": ok}


@router.get("/api/jobs")
def api_jobs(limit: int = 40):
    items = sorted(JOBS.values(), key=lambda j: -float(j.get("started") or 0))
    return {"total": len(items), "items": [
        {"id": j.get("id"), "kind": j.get("kind"), "label": j.get("label"),
         "status": j.get("status"), "progress": j.get("progress", 0.0),
         "started": j.get("started", 0), "result": j.get("result")}
        for j in items[:max(1, min(120, int(limit)))]
    ]}


@router.get("/api/observability")
def api_observability():
    return build_report(svc_state)


@router.post("/api/observability/clear")
def api_observability_clear():
    return {"ok": True, "cleared": clear_warnings()}


@router.post("/api/data/sync_json")
def api_data_sync_json():
    """将 SQLite 最新内容显式同步回遗留 JSON 快照，消除数据漂移。"""
    written = store.export_snapshots(recipes_json=RECIPE_PATH, templates_json=TPL, cards_json=CARDS)
    return {"ok": True, "written": written}
