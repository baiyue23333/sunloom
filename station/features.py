# -*- coding: utf-8 -*-
"""features.py - parity features: batch, inpaint, handfix, reproduce, masks, trash, export, backfill."""
import base64
from PIL import Image
import io
import json
import os
import re
import shutil
import time
import zipfile
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import comfy as cf
import config
import graph as gf
import server as S

router = APIRouter()

MASKS = os.path.join(S.HERE, "masks")
os.makedirs(MASKS, exist_ok=True)


# ---------------- models ----------------
class BatchReq(BaseModel):
    prompt: str
    negative: str = ""
    count: int = 4
    seed: int = 0
    width: int = 1024
    height: int = 1536
    steps: int = 30
    cfg: float = 5.5
    prefix: str = "batch"
    loras: List[Dict[str, Any]] = []
    blocks_pos: List[Dict[str, Any]] = []
    blocks_neg: List[Dict[str, Any]] = []


class InpaintReq(BaseModel):
    image: str
    box: str = ""
    mask_b64: str = ""
    feather: int = 8
    prompt: str = ""
    negative: str = ""
    denoise: float = 0.55
    steps: int = 26
    cfg: float = 5.2
    seed: int = 0
    prefix: str = "repaint"
    loras: List[Dict[str, Any]] = []


class ReproduceReq(BaseModel):
    image: str
    denoise: float = 0.55
    prompt: str = ""
    negative: str = ""
    width: int = 1024
    height: int = 1536
    steps: int = 30
    cfg: float = 5.5
    seed: int = 0
    prefix: str = "repro"
    loras: List[Dict[str, Any]] = []


class MaskSaveReq(BaseModel):
    image: str
    mask_b64: str
    name: str = ""


class PathReq(BaseModel):
    path: str


class RestoreReq(BaseModel):
    name: str


class ExportReq(BaseModel):
    paths: List[str] = []


# ---------------- helpers ----------------
def _mask_from_b64(ref_path, mask_b64, feather):
    from PIL import Image, ImageFilter
    raw = mask_b64.split(",", 1)[-1]
    try:
        data = base64.b64decode(raw)
    except Exception:
        raise HTTPException(400, "mask decode failed")
    src = Image.open(io.BytesIO(data))
    if src.mode == "RGBA":
        src = Image.alpha_composite(Image.new("RGBA", src.size, (0, 0, 0, 255)), src)
    # 画笔是红笔迹、框选是白块：统一取红通道再二值化（按亮度算会把红笔迹削成 44%）
    mask = src.convert("RGB").getchannel("R").point(lambda v: 255 if v >= 24 else 0)
    ref = Image.open(ref_path)
    if mask.size != ref.size:
        mask = mask.resize(ref.size, Image.LANCZOS)
    if feather:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=max(0.5, feather / 2.0)))
    inp = S.comfy_input_dir()
    if not inp:
        raise HTTPException(400, "comfy_dir is not configured")
    name = "mask_%s.png" % time.strftime("%H%M%S")
    mask.convert("RGB").save(os.path.join(inp, name))
    return name


def _run_inpaint(req: InpaintReq, mode="inpaint"):
    if not req.image or not os.path.isfile(req.image):
        raise HTTPException(400, "image not found")
    ref_name = S.prepare_reference(req.image)
    if req.mask_b64:
        mask_name = _mask_from_b64(req.image, req.mask_b64, req.feather)
    elif req.box:
        mask_name = S.make_mask(req.image, req.box, req.feather)
    else:
        raise HTTPException(400, "need box or mask_b64")
    cfg = config.load()
    seed = req.seed or int(time.time()) % 1000000
    params = {"prompt": req.prompt or "same art style, consistent rendering",
              "negative": req.negative, "steps": req.steps, "cfg": req.cfg, "seed": seed,
              "prefix": re.sub(r"[^A-Za-z0-9_-]", "_", req.prefix)[:40],
              "loras": req.loras, "denoise": req.denoise, "reference": ref_name, "mask": mask_name,
              "sampler": (cfg.get("defaults") or {}).get("sampler", "euler"),
              "scheduler": (cfg.get("defaults") or {}).get("scheduler", "simple")}
    jid = S.job_new(mode, params["prefix"])

    def work():
        try:
            wf, meta = gf.build("inpaint", params)
            if meta["missing"]:
                raise RuntimeError("ComfyUI is missing nodes: " + ", ".join(meta["missing"]))
            pid = cf.submit(wf)
            S.job_log(jid, "queued %s" % pid)
            res = cf.wait(pid, timeout=1800,
                          on_tick=lambda e: S.JOBS[jid].update(progress=min(0.95, e / 30.0)))
            if not res["ok"]:
                raise RuntimeError(res.get("error") or "inpaint failed")
            saved = [S.save_result(im, params["prefix"], seed) for im in res["images"]]
            saved = [s for s in saved if s]
            if not saved:
                raise RuntimeError("result file not found")
            from PIL import Image
            ref = Image.open(req.image)
            for p in saved:
                S.add_recipe(p, {"ts": time.time(), "mode": mode, "seed": seed,
                                 "size": list(ref.size), "steps": req.steps, "cfg": req.cfg,
                                 "denoise": req.denoise, "loras": req.loras,
                                 "positive": params["prompt"], "negative": req.negative,
                                 "reference": req.image, "mask": mask_name,
                                 "box": req.box, "workflow": "inpaint"})
            S.JOBS[jid].update(status="done", progress=1.0,
                               result={"images": saved, "seed": seed})
        except Exception as e:
            S.JOBS[jid].update(status="error", result={"error": str(e)[:500]})

    import threading
    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid, "seed": seed, "mask": mask_name}


# ---------------- batch ----------------
@router.post("/api/batch")
def api_batch(req: BatchReq):
    if not req.prompt.strip():
        raise HTTPException(400, "empty prompt")
    count = max(1, min(32, req.count))
    cfg = config.load()
    base = req.seed or int(time.time()) % 1000000
    seeds = [base + i for i in range(count)]
    jid = S.job_new("batch", "%s x%d" % (req.prefix, count))

    def work():
        saved, errors = [], []
        for i, seed in enumerate(seeds):
            try:
                params = {"prompt": req.prompt, "negative": req.negative,
                          "width": req.width, "height": req.height, "steps": req.steps,
                          "cfg": req.cfg, "seed": seed,
                          "prefix": re.sub(r"[^A-Za-z0-9_-]", "_", req.prefix)[:36],
                          "loras": req.loras, "denoise": 1.0,
                          "sampler": (cfg.get("defaults") or {}).get("sampler", "euler"),
                          "scheduler": (cfg.get("defaults") or {}).get("scheduler", "simple")}
                S.JOBS[jid].update(progress=i / count)
                wf, meta = gf.build("t2i", params)
                if meta["missing"]:
                    raise RuntimeError("missing nodes: " + ", ".join(meta["missing"]))
                pid = cf.submit(wf)
                res = cf.wait(pid, timeout=1800,
                              on_tick=lambda e: S.JOBS[jid].update(
                                  progress=min(0.98, (i + min(0.9, e / 60.0)) / count)))
                if not res["ok"]:
                    raise RuntimeError(res.get("error") or "failed")
                one = [S.save_result(im, params["prefix"], seed) for im in res["images"]]
                one = [s for s in one if s]
                for p in one:
                    S.add_recipe(p, {"ts": time.time(), "mode": "t2i", "seed": seed,
                                     "size": [req.width, req.height], "steps": req.steps,
                                     "cfg": req.cfg, "denoise": 1.0, "loras": req.loras,
                                     "positive": req.prompt, "negative": req.negative,
                                     "blocks_pos": req.blocks_pos, "blocks_neg": req.blocks_neg,
                                     "workflow": "t2i"})
                saved.extend(one)
                S.job_log(jid, "seed %s done (%d/%d)" % (seed, i + 1, count))
            except Exception as e:
                errors.append({"seed": seed, "error": str(e)[:300]})
                S.job_log(jid, "seed %s failed: %s" % (seed, str(e)[:200]))
        S.JOBS[jid].update(status="done" if saved else "error", progress=1.0,
                           result={"images": saved, "errors": errors, "seeds": seeds})

    import threading
    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid, "seeds": seeds, "count": count}


# ---------------- handfix / reproduce ----------------
@router.post("/api/handfix")
def api_handfix(req: InpaintReq):
    req.prompt = req.prompt or ("(detailed hand:1.4), (five fingers:1.35), "
                                "(natural hand pose:1.2), (same art style:1.25)")
    req.negative = req.negative or "extra fingers, fused fingers, deformed hand, bad anatomy"
    req.denoise = req.denoise or 0.45
    return _run_inpaint(req, "handfix")


@router.post("/api/inpaint")
def api_inpaint(req: InpaintReq):
    return _run_inpaint(req, "inpaint")


@router.post("/api/reproduce")
def api_reproduce(req: ReproduceReq):
    if not req.image or not os.path.isfile(req.image):
        raise HTTPException(400, "image not found")
    run = S.RunReq(prompt=req.prompt or "same character, same style, high quality",
                   negative=req.negative, width=req.width, height=req.height,
                   steps=req.steps, cfg=req.cfg, seed=req.seed, prefix=req.prefix,
                   loras=req.loras, mode="i2i", reference=req.image, denoise=req.denoise)
    return S.submit_job(run, "i2i")


# ---------------- masks ----------------
@router.post("/api/mask/save")
def api_mask_save(req: MaskSaveReq):
    if not req.mask_b64:
        raise HTTPException(400, "empty mask")
    raw = req.mask_b64.split(",", 1)[-1]
    try:
        data = base64.b64decode(raw)
    except Exception:
        raise HTTPException(400, "mask decode failed")
    stem = re.sub(r"[^A-Za-z0-9_-]", "", os.path.splitext(os.path.basename(req.image))[0])[:40] or "mask"
    tag = re.sub(r"[^A-Za-z0-9_-]", "", req.name or "")[:20]
    name = "%s_%s.png" % (stem, tag or time.strftime("%H%M%S"))
    try:
        src = Image.open(io.BytesIO(data))
        if src.mode == "RGBA":
            src = Image.alpha_composite(Image.new("RGBA", src.size, (0, 0, 0, 255)), src)
        m = src.convert("RGB").getchannel("R").point(lambda v: 255 if v >= 24 else 0)
        rgba = Image.new("RGBA", src.size, (0, 0, 0, 0))
        rgba.paste((255, 45, 85, 255), mask=m)
        rgba.save(os.path.join(MASKS, name))
    except Exception:
        with open(os.path.join(MASKS, name), "wb") as fh:
            fh.write(data)
    return {"ok": True, "name": name}


@router.get("/api/mask/list")
def api_mask_list(image: str = ""):
    stem = re.sub(r"[^A-Za-z0-9_-]", "", os.path.splitext(os.path.basename(image))[0])[:40] if image else ""
    items = []
    for n in sorted(os.listdir(MASKS), reverse=True):
        if not n.lower().endswith(".png"):
            continue
        if stem and not n.startswith(stem):
            continue
        p = os.path.join(MASKS, n)
        items.append({"name": n, "path": p, "mtime": int(os.path.getmtime(p))})
    return {"items": items[:60]}


@router.get("/api/mask/img")
def api_mask_img(name: str):
    p = os.path.abspath(os.path.join(MASKS, name))
    if not p.startswith(os.path.abspath(MASKS)) or not os.path.isfile(p):
        raise HTTPException(404, "not found")
    return FileResponse(p)


# ---------------- trash ----------------
def _trash_items():
    items = []
    if os.path.isdir(S.TRASH):
        for day in sorted(os.listdir(S.TRASH), reverse=True):
            d = os.path.join(S.TRASH, day)
            if not os.path.isdir(d):
                continue
            for n in sorted(os.listdir(d)):
                p = os.path.join(d, n)
                if os.path.isfile(p):
                    items.append({"name": n, "path": p, "day": day,
                                  "size": os.path.getsize(p)})
    return items


@router.get("/api/trash")
def api_trash():
    items = _trash_items()
    return {"items": items, "count": len(items),
            "mb": round(sum(i["size"] for i in items) / 1048576, 1)}


@router.post("/api/trash/restore")
def api_trash_restore(req: RestoreReq):
    for it in _trash_items():
        if it["name"] == req.name:
            dst = os.path.join(S.OUT_DIR, it["name"])
            if os.path.exists(dst):
                base, ext = os.path.splitext(req.name)
                dst = os.path.join(S.OUT_DIR, "%s_%s%s" % (base, time.strftime("%H%M%S"), ext))
            shutil.move(it["path"], dst)
            return {"ok": True, "path": dst}
    raise HTTPException(404, "not in trash")


@router.post("/api/trash/restore-all")
def api_trash_restore_all():
    n = 0
    for it in _trash_items():
        dst = os.path.join(S.OUT_DIR, it["name"])
        if os.path.exists(dst):
            base, ext = os.path.splitext(it["name"])
            dst = os.path.join(S.OUT_DIR, "%s_%s%s" % (base, n, ext))
        try:
            shutil.move(it["path"], dst)
            n += 1
        except Exception:
            pass
    return {"ok": True, "count": n}


@router.post("/api/trash/purge")
def api_trash_purge():
    n = 0
    for it in _trash_items():
        try:
            os.remove(it["path"])
            n += 1
        except Exception:
            pass
    return {"ok": True, "removed": n}


# ---------------- export / download ----------------
@router.post("/api/export")
def api_export(req: ExportReq):
    paths = [p for p in req.paths if os.path.isfile(p)]
    if not paths:
        raise HTTPException(400, "nothing selected")
    out_dir = os.path.join(S.OUT_DIR, "exports")
    os.makedirs(out_dir, exist_ok=True)
    name = "export_%s.zip" % time.strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(out_dir, name)
    db = S.read_json(S.RECIPES, {}) or {}
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        lines = []
        for p in paths:
            z.write(p, os.path.basename(p))
            r = db.get(p)
            if r:
                z.writestr(os.path.basename(p) + ".recipe.json",
                           json.dumps(r, ensure_ascii=False, indent=2))
                lines.append("%s seed=%s steps=%s cfg=%s" % (
                    os.path.basename(p), r.get("seed"), r.get("steps"), r.get("cfg")))
                lines.append("  + " + (r.get("positive") or "")[:400])
                lines.append("  - " + (r.get("negative") or "")[:400])
        z.writestr("prompts.txt", "\n".join(lines) or "(no recipes)")
        z.writestr("README.txt", "SUNLOOM export, %d image(s)\n" % len(paths))
    return {"ok": True, "path": dst, "name": name,
            "url": "/api/download?path=" + urllib_quote(dst)}


def urllib_quote(s):
    import urllib.parse
    return urllib.parse.quote(s, safe="")


@router.get("/api/download")
def api_download(path: str):
    p = os.path.abspath(path)
    if not p.startswith(os.path.abspath(S.OUT_DIR)) or not os.path.isfile(p):
        raise HTTPException(404, "not found")
    return FileResponse(p, filename=os.path.basename(p))


# ---------------- recipe backfill from PNG ----------------
from prompts import load_tokens as _load_tokens


def _match_blocks(text, tokens):
    """把展开后的提示词按积木原文从长到短匹配回去。"""
    blocks, rest = [], text or ""
    for tok, txt in sorted(tokens.items(), key=lambda kv: -len(kv[1] or "")):
        frag = (txt or "")[:60]
        if not frag or frag not in rest:
            continue
        rest = rest.replace(frag, "\u0000", 1)
        blocks.append({"token": tok, "weight": 1, "enabled": True})
    return blocks


def _parse_png_prompt(path):
    try:
        from PIL import Image
        im = Image.open(path)
        info = im.info or {}
        raw = info.get("prompt")
        if not raw:
            return None
        data = json.loads(raw)
    except Exception:
        return None
    nodes = data.get("prompt") if isinstance(data, dict) and "prompt" in data else data
    if not isinstance(nodes, dict):
        return None
    by_id = {k: v for k, v in nodes.items() if isinstance(v, dict)}
    ks = None
    for n in by_id.values():
        if n.get("class_type") == "KSampler":
            ks = n
            break
    if not ks:
        return None
    ins = ks.get("inputs") or {}

    def text_of(link):
        if not isinstance(link, list) or not link:
            return ""
        n = by_id.get(str(link[0]))
        if not n:
            return ""
        t = (n.get("inputs") or {}).get("text", "")
        if isinstance(t, str):
            return t
        return ""

    pos = text_of(ins.get("positive"))
    neg = text_of(ins.get("negative"))
    width = height = None
    for n in by_id.values():
        if n.get("class_type") == "EmptyLatentImage":
            width = (n.get("inputs") or {}).get("width")
            height = (n.get("inputs") or {}).get("height")
            break
    loras = []
    for n in by_id.values():
        if n.get("class_type") == "LoraLoaderModelOnly":
            i = n.get("inputs") or {}
            if i.get("lora_name"):
                loras.append({"name": i.get("lora_name"), "weight": i.get("strength_model", 1.0)})
    tokens, _, _ = _load_tokens()
    return {"ts": os.path.getmtime(path), "mode": "png_metadata", "seed": ins.get("seed"),
            "size": [width, height], "steps": ins.get("steps"), "cfg": ins.get("cfg"),
            "denoise": ins.get("denoise"), "loras": loras,
            "positive": pos, "negative": neg, "workflow": "png_metadata",
            "blocks_pos": _match_blocks(pos, tokens), "blocks_neg": _match_blocks(neg, tokens),
            "blocks_guess": True,
            "exact": True, "inferred": False}


@router.post("/api/recipe/backfill")
def api_backfill():
    db = S.read_json(S.RECIPES, {}) or {}
    n = skipped = 0
    for base, dirs, files in os.walk(S.OUT_DIR):
        if os.path.basename(base) in ("exports", "_trash"):
            continue
        for f in files:
            if not f.lower().endswith(".png"):
                continue
            p = os.path.join(base, f)
            if p in db and db[p].get("exact"):
                skipped += 1
                continue
            r = _parse_png_prompt(p)
            if not r:
                skipped += 1
                continue
            db[p] = r
            n += 1
    S.write_json(S.RECIPES, db)
    return {"ok": True, "recovered": n, "skipped": skipped, "total": len(db)}
