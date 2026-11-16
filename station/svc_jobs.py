# -*- coding: utf-8 -*-
"""出图任务执行引擎（单张、局部重绘、批量精品、一条龙）。"""
import os
import random as _rnd
import shutil
import time
from typing import Any, Dict, List

from pydantic import BaseModel

import comfy as cf
import graph as gf
import store
import svc_mem
from svc_recipes import _prepare_reference, add_recipe, mirror_score
from svc_state import (
    JOBS,
    LAST_GRAPH,
    OUT_DIR,
    ROOT,
    comfy_out,
    estimate_seconds,
    expand_blocks,
    job_log,
    job_save,
)


class Block(BaseModel):
    id: str = ""
    token: str = ""
    text: str = ""
    weight: float = 1.0
    enabled: bool = True


class ExpandReq(BaseModel):
    positive: List[Block] = []
    negative: List[Block] = []


class BatchQReq(BaseModel):
    count: int = 4
    refine: bool = True
    denoise: float = 0.3
    steps: int = 0
    cfg: float = 0.0
    model: str = ""
    templates: List[str] = []
    loras: List[Dict[str, Any]] = []


class AutoPipeReq(BaseModel):
    count: int = 4
    refine: bool = True
    denoise: float = 0.3
    glitch: float = 0.0
    keep: int = 2
    templates: List[str] = []
    loras: List[Dict[str, Any]] = []


def _node_class(node):
    return (node or {}).get("class_type") or (node or {}).get("type") or ""


def _save_result(im, label, seed):
    """把 ComfyUI 输出图片复制到站点的 station_out，返回本地路径。"""
    src_path = os.path.join(comfy_out(), im.get("subfolder", ""), im["filename"])
    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = time.strftime("%H%M%S")
    dst = os.path.join(OUT_DIR, "%s_%s_s%d.png" % (label, stamp, seed))
    if os.path.exists(src_path):
        if os.path.exists(dst):
            dst = os.path.join(OUT_DIR, "%s_%s_s%d_%s.png" % (label, stamp, seed, str(int(time.time() % 1000))))
        shutil.copy2(src_path, dst)
        return dst
    return ""


def _wf_unet(wf, fallback=""):
    for _n in (wf or {}).values():
        if _node_class(_n) == "UNETLoader":
            name = (_n.get("inputs") or {}).get("unet_name")
            if name:
                return str(name)
    return str(fallback or "anima-base-v1.0.safetensors")


def _wait_with_oom_retry(wf, jid, expect, reason, context="base", timeout=1800):
    """提交工作流并在首次 CUDA OOM 时强制清模恢复后自动重试一次。"""
    for attempt in range(2):
        pid = gf.submit(wf)
        if jid:
            def tick(elapsed):
                _pg = cf.progress_of(pid) if hasattr(cf, "progress_of") else None
                if _pg and _pg[1]:
                    JOBS[jid]["progress"] = min(0.99, 0.03 + 0.95 * (_pg[0] / _pg[1]))
                else:
                    JOBS[jid]["progress"] = min(0.99, elapsed / max(8.0, expect))
            res = cf.wait(pid, timeout=timeout, on_tick=tick)
        else:
            res = cf.wait(pid, timeout=timeout)
        if res.get("ok") or attempt == 1 or not cf.is_oom_error(res.get("error", "")):
            return pid, res
        svc_mem.recover_oom(reason, context=context)
        if jid:
            job_log(jid, "[memory] 检测到显存不足，已自动清模并重试 (%s)" % reason)
    return None, {"ok": False, "error": "oom retry exhausted"}


def _submit(mode, params, jid, label, wf_name=None):
    """编译图 -> 显存调度 -> 提交 -> 轮询（OOM 自动恢复重试） -> 落盘。"""
    if not cf.system_stats()["up"]:
        JOBS[jid].update(status="error", result={"error": "ComfyUI 未启动"})
        job_save(jid)
        return
    wf_map = {"t2i": "anima_t2i", "i2i": "anima_i2i", "inpaint": "anima_inpaint"}
    if wf_name is None:
        if mode not in wf_map:
            JOBS[jid].update(status="error", result={"error": "不支持的模式: %s" % mode})
            job_save(jid)
            return
        wf_name = wf_map[mode]
    try:
        wf, meta = gf.build(wf_name, params)
    except Exception as e:
        JOBS[jid].update(status="error", result={"error": "编译工作流失败: %s" % e})
        job_log(jid, "COMPILE ERROR " + str(e)[:200])
        job_save(jid)
        return
    _model = (params.get("model") or "").strip()
    if _model:
        for _n in wf.values():
            if _node_class(_n) == "UNETLoader":
                _n.setdefault("inputs", {})["unet_name"] = _model
    if meta["missing"]:
        msg = "ComfyUI 缺少节点: " + ", ".join(meta["missing"])
        JOBS[jid].update(status="error", result={"error": msg, "missing": meta["missing"]})
        job_log(jid, msg)
        job_save(jid)
        return
    try:
        unet_name = _wf_unet(wf, _model)
        sched = svc_mem.prepare_stage("anima", unet=unet_name, reason="%s:%s" % (mode, label), context="base")
        if sched.get("action") not in ("keep", "skip_offline"):
            job_log(jid, "[memory] %s (vram_free=%sMB)" % (sched.get("action"), sched.get("vram_free_mb")))
        LAST_GRAPH.clear()
        LAST_GRAPH.update({"__workflow": meta["workflow"], "nodes": wf})
        expect = estimate_seconds(params.get("width", 1024), params.get("height", 1536),
                                  params.get("steps", 30), model=params.get("model") or "")
        t0 = time.time()
        pid, res = _wait_with_oom_retry(wf, jid, expect, "%s:%s" % (mode, label), context="base", timeout=1800)
        job_log(jid, "queued %s (workflow=%s, denoise=%.2f)" % (pid, meta["workflow"], meta["denoise"]))
        if not res["ok"]:
            JOBS[jid].update(status="error", result={"error": res.get("error", "")})
            job_log(jid, "ERROR " + str(res.get("error", ""))[:300])
            job_save(jid)
            return
        saved = []
        cout = comfy_out()
        rewrite_notes = list(params.get("expand_notes") or [])
        client_meta = params.get("client_meta") or {}
        for im in res["images"]:
            src_path = os.path.join(cout, im.get("subfolder", ""), im["filename"])
            dst_dir = OUT_DIR if params.get("save_to", "station_out") == "station_out" else os.path.join(
                ROOT, "SD-Picture", params.get("save_to"))
            os.makedirs(dst_dir, exist_ok=True)
            stamp = time.strftime("%H%M%S")
            dst = os.path.join(dst_dir, "%s_%s_s%d.png" % (label, stamp, params.get("seed", 0)))
            if os.path.exists(src_path):
                shutil.copy2(src_path, dst)
                if mode == "t2i" and params.get("auto_handfix"):
                    try:
                        import reproj_parts as _rp_hand
                        fn_h = _rp_hand.refine_hands_on_image(dst, params.get("loras"), params.get("seed", 0), params.get("model") or "")
                        if fn_h:
                            rewrite_notes.append("自动手部精修：%d 处" % fn_h)
                    except Exception as _he:
                        job_log(jid, "handfix skip: " + str(_he)[:120])
                saved.append(dst)
                add_recipe(dst, {
                    "ts": time.time(),
                    "mode": mode,
                    "workflow": meta.get("workflow"),
                    "positive": params.get("prompt", ""),
                    "negative": params.get("negative", ""),
                    "blocks_pos": params.get("blocks_pos") or [],
                    "blocks_neg": params.get("blocks_neg") or [],
                    "size": [params.get("width"), params.get("height")],
                    "steps": params.get("steps"),
                    "cfg": params.get("cfg"),
                    "seed": params.get("seed"),
                    "denoise": params.get("denoise"),
                    "loras": params.get("loras") or [],
                    "model": params.get("model") or "",
                    "reference": params.get("reference", ""),
                    "mask": params.get("mask", ""),
                    "rewrite_notes": rewrite_notes,
                    "client_meta": client_meta,
                })
            job_log(jid, "saved " + os.path.basename(dst))
        score = mirror_score(saved[0]) if saved else 0.0
        JOBS[jid].update(status="done", progress=1.0,
                         result={"images": saved, "seed": params.get("seed"), "workflow": meta["workflow"],
                                 "denoise": meta["denoise"], "elapsed": round(time.time() - t0, 1),
                                 "mirror": score, "split_suspect": score >= 0.86,
                                 "rewrite_notes": rewrite_notes})
        job_save(jid)
    except Exception as e:
        JOBS[jid].update(status="error", result={"error": str(e)})
        job_log(jid, "EXC " + str(e)[:300])
        job_save(jid)
    finally:
        svc_mem.release_stage(context="base", reason="%s:%s" % (mode, label), soft=False)


def _tpl_pool(want_names):
    all_tpl = list(store.load_templates())
    if want_names:
        want = set(want_names)
        return [t for t in all_tpl if t.get("name") in want]
    return [t for t in all_tpl
            if not str(t.get("name", "")).startswith("风格") and "29B" not in str(t.get("name", ""))]


def _default_loras(req_loras):
    """Use explicitly requested LoRAs without hardcoded personal weights."""
    return list(req_loras or [])



def _dump_blocks(raw):
    return [(b.model_dump() if hasattr(b, "model_dump") else b) for b in (raw or [])]


def _make_refine(exp, w, h, steps, cfg, seed, loras, label, model, first, denoise):
    ref = _prepare_reference(first)
    wf2 = cf.build_wf(exp["positive"], exp["negative"], w, h, max(12, steps - 4), cfg, seed,
                      loras, label + "_ref", unet=(model or None))
    for nid, node in list(wf2.items()):
        if node.get("class_type") == "EmptyLatentImage":
            wf2.pop(nid, None)
    wf2["30"] = {"class_type": "LoadImage", "inputs": {"image": ref}}
    wf2["31"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["30", 0], "vae": ["3", 0]}}
    wf2["9"]["inputs"]["latent_image"] = ["31", 0]
    wf2["9"]["inputs"]["denoise"] = max(0.15, min(0.5, float(denoise)))
    svc_mem.prepare_stage("anima", unet=(model or "anima-base-v1.0.safetensors"),
                          reason="refine:" + label, context="base")
    _, res2 = _wait_with_oom_retry(wf2, None, 30.0, "refine:" + label, context="base", timeout=1800)
    if res2.get("ok") and res2.get("images"):
        return _save_result(res2["images"][0], label + "_ref", seed)
    return ""


def _sample_from_pool(pool, loras, workflow_tag, label_prefix, i, model_override="", steps_override=0, cfg_override=0.0):
    tpl = _rnd.choice(pool)
    params = tpl.get("params") or {}
    size = str(params.get("size") or "1024x1536")
    try:
        w, h = [int(x) for x in size.split("x")]
    except Exception:
        w, h = 1024, 1536
    steps = steps_override or int(params.get("steps") or 30)
    cfg = cfg_override or float(params.get("cfg") or 5.5)
    model = model_override or str(params.get("model") or "")
    pos_b = [Block(**b) if isinstance(b, dict) else b for b in (tpl.get("positive") or [])]
    neg_b = [Block(**b) if isinstance(b, dict) else b for b in (tpl.get("negative") or [])]
    exp = expand_blocks(pos_b, neg_b)
    seed = 100000 + _rnd.randint(0, 899999)
    label = "%s_%02d" % (label_prefix, i + 1)
    wf = cf.build_wf(exp["positive"], exp["negative"], w, h, steps, cfg, seed, loras, label, unet=(model or None))
    svc_mem.prepare_stage("anima", unet=(model or "anima-base-v1.0.safetensors"),
                          reason="batch:" + label, context="base")
    _, res = _wait_with_oom_retry(wf, None, 30.0, "batch:" + label, context="base", timeout=1800)
    if not res.get("ok") or not res.get("images"):
        return None, exp, w, h, steps, cfg, seed, label, model, res.get("error", "")
    first = _save_result(res["images"][0], label, seed)
    if first:
        add_recipe(first, {"ts": time.time(), "mode": "t2i", "workflow": workflow_tag,
                           "positive": exp["positive"], "negative": exp["negative"],
                           "blocks_pos": _dump_blocks(tpl.get("positive")),
                           "blocks_neg": _dump_blocks(tpl.get("negative")),
                           "size": [w, h], "steps": steps, "cfg": cfg, "seed": seed,
                           "loras": loras, "model": model})
    return first, exp, w, h, steps, cfg, seed, label, model, ""


def _run_batchq(req: BatchQReq, jid):
    try:
        pool = _tpl_pool(req.templates)
        if not pool:
            JOBS[jid].update(status="error", result={"error": "没有可用模板"})
            return
        loras = _default_loras(req.loras)
        saved_all, n = [], max(1, min(24, req.count))
        for i in range(n):
            first, exp, w, h, steps, cfg, seed, label, model, err = _sample_from_pool(
                pool, loras, "batchq", "bq", i, req.model, req.steps, req.cfg)
            if not first:
                job_log(jid, "第 %d 张失败：%s" % (i + 1, err)[:200])
                continue
            saved_all.append(first)
            if req.refine:
                second = _make_refine(exp, w, h, steps, cfg, seed, loras, label, model, first, req.denoise)
                if second:
                    saved_all.append(second)
            JOBS[jid]["progress"] = (i + 1) / n
            job_log(jid, "完成 %d/%d：%s" % (i + 1, n, os.path.basename(first)))
        JOBS[jid].update(status="done", progress=1.0, result={"images": saved_all, "count": len(saved_all)})
        job_save(jid)
    except Exception as e:
        JOBS[jid].update(status="error", result={"error": str(e)[:300]})
        job_log(jid, "ERROR " + str(e)[:300])
        job_save(jid)
    finally:
        svc_mem.release_stage(context="batch", reason="batchq", soft=(svc_mem.get_policy().get("profile") == "aggressive"))


def _run_autopipe(req: AutoPipeReq, jid):
    try:
        pool = _tpl_pool(req.templates)
        if not pool:
            JOBS[jid].update(status="error", result={"error": "没有可用模板"})
            return
        loras = _default_loras(req.loras)
        made, n = [], max(1, min(16, req.count))
        for i in range(n):
            first, exp, w, h, steps, cfg, seed, label, model, _ = _sample_from_pool(
                pool, loras, "autopipe", "ap", i)
            if not first:
                job_log(jid, "第 %d 张失败" % (i + 1))
                continue
            best = first
            if req.refine:
                second = _make_refine(exp, w, h, steps, cfg, seed, loras, label, model, first, req.denoise)
                if second:
                    best = second
            try:
                score = float(mirror_score(best))
            except Exception:
                score = 0.0
            made.append({"path": best, "score": round(score, 3)})
            JOBS[jid]["progress"] = (i + 1) / n * 0.9
            job_log(jid, "完成 %d/%d 评分 %.1f" % (i + 1, n, score))
        made.sort(key=lambda x: -x["score"])
        kept = made[:max(1, min(len(made), req.keep))]
        out = []
        for item in kept:
            p = item["path"]
            if req.glitch and req.glitch > 0:
                try:
                    import glitchify
                    dst = os.path.splitext(p)[0] + "_glitch.png"
                    glitchify.glitchify(p, dst, max(0.1, min(2.0, req.glitch)))
                    p = dst
                except Exception as e:
                    job_log(jid, "故障失败：" + str(e)[:120])
            out.append({"path": p, "score": item["score"]})
        JOBS[jid].update(status="done", progress=1.0, result={"kept": out, "all": made})
        job_save(jid)
    except Exception as e:
        JOBS[jid].update(status="error", result={"error": str(e)[:300]})
        job_log(jid, "ERROR " + str(e)[:300])
        job_save(jid)
    finally:
        svc_mem.release_stage(context="batch", reason="autopipe", soft=(svc_mem.get_policy().get("profile") == "aggressive"))
