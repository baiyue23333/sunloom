# -*- coding: utf-8 -*-
"""SUNLOOM block studio - generic backend (FastAPI)."""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import comfy as cf
import config
import graph as gf
import ir as irv
import prompts as pt

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
STATIC = os.path.join(HERE, "static")
DOCS = os.path.join(os.path.dirname(HERE), "docs")
CFG = config.load()
OUT_DIR = os.path.join(HERE, CFG.get("output_dir") or "output")
TRASH = os.path.join(OUT_DIR, "_trash")
RECIPES = os.path.join(DATA, "recipes.json")

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(DATA, exist_ok=True)

app = FastAPI(title="SUNLOOM block studio")
JOBS: Dict[str, Dict[str, Any]] = {}


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------------- models ----------------
class Block(BaseModel):
    token: str = ""
    text: str = ""
    weight: float = 1.0
    enabled: bool = True


class ExpandReq(BaseModel):
    positive: List[Block] = []
    negative: List[Block] = []


class ValidateReq(BaseModel):
    positive: List[Block] = []
    negative: List[Block] = []


class RunReq(BaseModel):
    prompt: str
    negative: str = ""
    width: int = 1024
    height: int = 1536
    steps: int = 28
    cfg: float = 5.5
    seed: int = 0
    prefix: str = "img"
    loras: List[Dict[str, Any]] = []
    mode: str = "t2i"
    reference: str = ""
    denoise: float = 0.6
    blocks_pos: List[Block] = []
    blocks_neg: List[Block] = []


class TokenReq(BaseModel):
    name: str
    text: str = ""
    category: str = "note"
    note: str = ""


class GarmentReq(BaseModel):
    key: str
    label: str = ""
    use_for: str = ""
    prompt: str = ""
    negative: str = ""
    material: str = ""
    drape: str = ""


class DeleteReq(BaseModel):
    path: str


class ConfigReq(BaseModel):
    unet_name: str = ""
    clip_name: str = ""
    vae_name: str = ""
    clip_type: str = "stable_diffusion"
    comfy_dir: str = ""


class InpaintReq(BaseModel):
    image: str
    box: str = ""
    mask_b64: str = ""
    feather: int = 0
    prompt: str = ""
    negative: str = ""
    denoise: float = 0.6
    steps: int = 26
    cfg: float = 5.2
    seed: int = 0
    prefix: str = "repaint"
    loras: List[Dict[str, Any]] = []


# ---------------- helpers ----------------
def job_new(kind, label=""):
    jid = uuid.uuid4().hex[:10]
    JOBS[jid] = {"id": jid, "kind": kind, "label": label, "status": "running",
                 "progress": 0.0, "logs": [], "result": None, "started": time.time()}
    return jid


def job_log(jid, line):
    j = JOBS.get(jid)
    if not j:
        return
    j["logs"].append(str(line)[:500])
    if len(j["logs"]) > 300:
        j["logs"] = j["logs"][-300:]


def estimate_seconds(w, h, steps):
    return round(float(w) * float(h) * float(steps) * 1.6e-6 + 1.5, 1)


def comfy_input_dir():
    cfg = config.load()
    d = cfg.get("comfy_dir") or os.environ.get("COMFY_DIR", "")
    if not d:
        return ""
    p = os.path.join(d, "input")
    return p if os.path.isdir(p) else ""


def prepare_reference(path):
    if not path or not os.path.isfile(path):
        raise HTTPException(400, "reference image not found")
    inp = comfy_input_dir()
    if not inp:
        raise HTTPException(400, "comfy_dir is not configured (installer writes it into data/config.json)")
    name = "ref_" + re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(path))[:60]
    shutil.copy2(path, os.path.join(inp, name))
    return name


def make_mask(ref_path, box, feather=0):
    from PIL import Image, ImageDraw, ImageFilter
    inp = comfy_input_dir()
    if not inp:
        raise HTTPException(400, "comfy_dir is not configured")
    x, y, w, h = [int(v) for v in str(box).split(",")]
    im = Image.open(ref_path)
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rectangle([x, y, x + w, y + h], fill=255)
    if feather:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=feather / 2.0))
    name = "mask_%s.png" % time.strftime("%H%M%S")
    mask.convert("RGB").save(os.path.join(inp, name))
    return name


def save_result(im, label, seed):
    cfg = config.load()
    base = cfg.get("comfy_output") or ""
    if not base and cfg.get("comfy_dir"):
        base = os.path.join(cfg["comfy_dir"], "output")
    src = os.path.join(base or "", im.get("subfolder", ""), im["filename"])
    if not os.path.isfile(src):
        return ""
    dst = os.path.join(OUT_DIR, "%s_%s_s%d.png" % (label, time.strftime("%H%M%S"), seed))
    shutil.copy2(src, dst)
    return dst


def add_recipe(path, data):
    db = read_json(RECIPES, {}) or {}
    db[path] = data
    if len(db) > 500:
        for k in sorted(db, key=lambda k: db[k].get("ts", 0))[: len(db) - 500]:
            db.pop(k, None)
    write_json(RECIPES, db)


# ---------------- static ----------------
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/api/img")
def api_img(path: str):
    if not os.path.isfile(path):
        raise HTTPException(404, "not found")
    return FileResponse(path)


# ---------------- bootstrap / expand / validate ----------------


_FEATURE_LIST = [
    {"group": "拼装", "items": ["积木库：分类、收藏、拖拽添加", "正负向画布：权重、停用、删除、排序",
                                 "描述卡片、文本块、标签块", "展开预览与结构检查", "快速模板"]},
    {"group": "出图", "items": ["文生图 / 图生图", "LoRA 多行", "批量多 seed", "配方自动记录"]},
    {"group": "重绘", "items": ["画笔 / 橡皮 / 框选、羽化", "蒙版库", "手部精修（框选）", "图生图复现"]},
    {"group": "数据", "items": ["词库分类 / 导入导出", "服装默认 / 复制 / 导入导出", "配方回填"]},
    {"group": "可选模块", "items": ["打标（WD14）", "训练（kohya），需要本机 kohya_dir"]},
]


def _defaults_superset(cfg):
    d = dict(cfg.get("defaults") or {})
    size = str(d.get("size") or "1024x1536")
    try:
        w, h = [int(x) for x in size.lower().split("x")]
    except Exception:
        w, h = 1024, 1536
    d.setdefault("width", w)
    d.setdefault("height", h)
    d.setdefault("steps", 28)
    d.setdefault("cfg", 5.5)
    return d


def _list_datasets():
    base = os.path.join(DATA, "datasets")
    items = []
    if os.path.isdir(base):
        for n in sorted(os.listdir(base)):
            p = os.path.join(base, n)
            if not os.path.isdir(p):
                continue
            imgs = [f for f in os.listdir(p) if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
            items.append({"name": n, "path": p, "images": len(imgs)})
    return items


def _list_loras():
    cfg = config.load()
    root = cfg.get("comfy_dir") or ""
    out = []
    for sub in ("models/loras", "models/Lora", "models/lycoris"):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for base, dirs, files in os.walk(d):
            for f in files:
                if f.lower().endswith((".safetensors", ".pt", ".ckpt")):
                    out.append({"name": f, "path": os.path.join(base, f)})
    out.sort(key=lambda x: x["name"].lower())
    return out

@app.get("/api/bootstrap")
def bootstrap():
    tokens, lib, ch = pt.load_tokens()
    cfg = config.load()
    comfy_st = cf.system_stats()
    tpl = read_json(os.path.join(DATA, "templates.json"), []) or []
    return {
        "tokens": tokens,
        "notes": lib.get("notes") or {},
        "garments": ch.get("garments") or {},
        "garment_default": ch.get("garment_default") or "",
        "templates": tpl,
        "defaults": _defaults_superset(cfg),
        "model": cfg.get("model") or {},
        "datasets": _list_datasets(),
        "loras": _list_loras(),
        "character": {k: v for k, v in (ch or {}).items() if k != "garments"},
        "features": _FEATURE_LIST,
        "registry": {"total": 0, "items": []},
        "comfy": dict(comfy_st, url=cf.COMFY),
        "queue": cf.queue_state(),
        "paths": {"root": HERE, "output": OUT_DIR},
    }


CUP_HOLD = re.compile(r"(holding[^,]{0,24}cup)|(cup in her hand)", re.I)
DRINKWARE = ["cup", "mug", "teacup", "coffee cup", "saucer", "drinking glass", "wine glass", "bottle"]


@app.post("/api/expand")
def api_expand(req: ExpandReq):
    tokens, _, _ = pt.load_tokens()

    def render(blocks):
        parts, used = [], []
        for b in blocks:
            if not b.enabled:
                continue
            raw = b.text or b.token
            if not raw:
                continue
            ex, u = pt.expand(raw, tokens)
            used.extend(u)
            ex = ex.strip().strip(",")
            if b.weight and abs(b.weight - 1.0) > 0.001:
                ex = "(%s:%s)" % (ex, b.weight)
            parts.append(ex)
        return ", ".join([p for p in parts if p]), sorted(set(used))

    pos, pu = render(req.positive)
    raw_pos = " ".join([(b.token or "") + " " + (b.text or "") for b in req.positive if b.enabled])
    cup_wanted = bool(CUP_HOLD.search(raw_pos)) or "@PROP_CUP" in raw_pos
    notes = []
    neg_blocks = []
    for b in req.negative:
        if not b.enabled:
            continue
        if cup_wanted and (b.token or "").upper() == "@NEG_CUP":
            notes.append("Negative auto-relaxed: dropped @NEG_CUP because the positive holds a cup")
            continue
        neg_blocks.append(b)
    neg, nu = render(neg_blocks)
    if cup_wanted:
        for w in DRINKWARE:
            neg = re.sub(r"(?i)\b" + re.escape(w) + r"\b", "", neg)
        neg = re.sub(r"\s*,\s*,+", ", ", neg).strip().strip(",").strip()
    return {"positive": pos, "negative": neg, "used": sorted(set(pu + nu)),
            "pos_len": len(pos), "neg_len": len(neg), "notes": notes}


@app.post("/api/validate")
def api_validate(req: ValidateReq):
    tokens, _, _ = pt.load_tokens()
    return irv.validate([b.dict() for b in req.positive], [b.dict() for b in req.negative], tokens)


# ---------------- run ----------------
def submit_job(req: RunReq, mode: str):
    cfg = config.load()
    seed = req.seed or int(time.time()) % 1000000
    prefix = re.sub(r"[^A-Za-z0-9_-]", "_", req.prefix or "img")[:40]
    params = {"prompt": req.prompt, "negative": req.negative, "width": req.width,
              "height": req.height, "steps": req.steps, "cfg": req.cfg, "seed": seed,
              "prefix": prefix, "loras": req.loras,
              "sampler": (cfg.get("defaults") or {}).get("sampler", "euler"),
              "scheduler": (cfg.get("defaults") or {}).get("scheduler", "simple"),
              "denoise": 1.0}
    wf_name = "t2i"
    if mode == "i2i":
        params["reference"] = prepare_reference(req.reference)
        params["denoise"] = req.denoise
        wf_name = "i2i"
    jid = job_new(mode, prefix)
    blocks_pos = [b.dict() for b in req.blocks_pos]
    blocks_neg = [b.dict() for b in req.blocks_neg]

    def work():
        try:
            wf, meta = gf.build(wf_name, params)
            if meta["missing"]:
                raise RuntimeError("ComfyUI is missing nodes: " + ", ".join(meta["missing"]))
            pid = cf.submit(wf)
            job_log(jid, "queued %s (workflow=%s)" % (pid, meta["workflow"]))
            expect = estimate_seconds(req.width, req.height, req.steps)
            t0 = time.time()
            res = cf.wait(pid, timeout=1800,
                          on_tick=lambda e: JOBS[jid].update(progress=min(0.97, e / max(8.0, expect))))
            if not res["ok"]:
                raise RuntimeError(res.get("error") or "generation failed")
            saved = [save_result(im, prefix, seed) for im in res["images"]]
            saved = [s for s in saved if s]
            if not saved:
                raise RuntimeError("result file not found (check output_dir / comfy_output in config)")
            for p in saved:
                add_recipe(p, {"ts": time.time(), "mode": mode, "seed": seed,
                               "size": [req.width, req.height], "steps": req.steps, "cfg": req.cfg,
                               "denoise": params.get("denoise"), "loras": req.loras,
                               "positive": req.prompt, "negative": req.negative,
                               "blocks_pos": blocks_pos, "blocks_neg": blocks_neg,
                               "reference": params.get("reference", ""),
                               "workflow": meta["workflow"]})
            JOBS[jid].update(status="done", progress=1.0,
                             result={"images": saved, "seed": seed, "elapsed": round(time.time() - t0, 1)})
        except Exception as e:
            JOBS[jid].update(status="error", result={"error": str(e)[:500]})

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid, "seed": seed, "mode": mode}


@app.post("/api/run")
def api_run(req: RunReq):
    if not req.prompt.strip():
        raise HTTPException(400, "empty prompt")
    if req.mode == "i2i" and not req.reference:
        raise HTTPException(400, "i2i needs a reference image")
    return submit_job(req, req.mode)


@app.get("/api/job/{jid}")
def api_job(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "unknown job")
    j["elapsed"] = round(time.time() - j["started"], 1)
    return j


# ---------------- gallery / recipes ----------------
@app.get("/api/gallery")
def api_gallery(limit: int = 300, q: str = "", since: str = "", recipe: str = ""):
    db = read_json(RECIPES, {}) or {}
    cutoff = 0
    if since == "today":
        cutoff = time.time() - 86400
    elif since == "week":
        cutoff = time.time() - 7 * 86400
    items = []
    for name in os.listdir(OUT_DIR):
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        if q and q.lower() not in name.lower():
            continue
        p = os.path.join(OUT_DIR, name)
        mt = os.path.getmtime(p)
        if cutoff and mt < cutoff:
            continue
        has = p in db
        if recipe == "yes" and not has:
            continue
        if recipe == "no" and has:
            continue
        items.append({"path": p, "name": name, "mtime": int(mt),
                      "size": os.path.getsize(p), "has_recipe": has})
    items.sort(key=lambda x: -x["mtime"])
    return {"items": items[:limit], "total": len(items)}


@app.post("/api/delete-image")
def api_delete_image(req: DeleteReq):
    p = os.path.abspath(req.path)
    if not os.path.isfile(p):
        raise HTTPException(404, "not found")
    if os.path.commonpath([p, os.path.abspath(OUT_DIR)]) != os.path.abspath(OUT_DIR):
        raise HTTPException(403, "only files inside output can be deleted")
    dst_dir = os.path.join(TRASH, time.strftime("%Y%m%d"))
    os.makedirs(dst_dir, exist_ok=True)
    shutil.move(p, os.path.join(dst_dir, os.path.basename(p)))
    return {"ok": True}


@app.get("/api/recipes")
def api_recipes(limit: int = 100):
    db = read_json(RECIPES, {}) or {}
    items = [{"path": p, "name": os.path.basename(p), "ts": r.get("ts", 0)}
             for p, r in db.items() if os.path.isfile(p)]
    items.sort(key=lambda x: -x["ts"])
    return {"total": len(items), "items": items[:limit]}


@app.get("/api/recipe")
def api_recipe(path: str):
    db = read_json(RECIPES, {}) or {}
    r = db.get(path)
    if not r:
        raise HTTPException(404, "no recipe for this image")
    return dict(r, path=path)


# ---------------- tokens / garments ----------------
@app.post("/api/token/save")
def api_token_save(req: TokenReq):
    tokens, lib, _ = pt.load_tokens()
    name = req.name if req.name.startswith("@") else "@" + req.name.upper()
    lib.setdefault("tokens", {})[name] = req.text
    if req.note:
        lib.setdefault("notes", {})[name] = req.note
    if req.category:
        lib.setdefault("meta", {}).setdefault("cats", {})[name] = req.category
    pt.write_json(pt.LIB, lib)
    return {"ok": True, "name": name}


@app.post("/api/token/delete")
def api_token_delete(req: TokenReq):
    _, lib, _ = pt.load_tokens()
    lib.get("tokens", {}).pop(req.name, None)
    lib.get("notes", {}).pop(req.name, None)
    pt.write_json(pt.LIB, lib)
    return {"ok": True}


@app.post("/api/token/note")
def api_token_note(req: TokenReq):
    _, lib, _ = pt.load_tokens()
    lib.setdefault("notes", {})[req.name] = req.note or req.text
    pt.write_json(pt.LIB, lib)
    return {"ok": True}


@app.post("/api/garment/save")
def api_garment_save(req: GarmentReq):
    p = os.path.join(DATA, "character.json")
    ch = read_json(p, {}) or {}
    gs = ch.setdefault("garments", {})
    g = gs.setdefault(req.key, {})
    if req.label:
        g["label"] = req.label
    if req.use_for:
        g["use_for"] = req.use_for
    if req.prompt:
        g["prompt"] = req.prompt
    if req.negative:
        g["negative"] = req.negative
    if getattr(req, "material", ""):
        g["material"] = req.material
    if getattr(req, "drape", ""):
        g["drape"] = req.drape
    write_json(p, ch)
    return {"ok": True, "garments": gs}


@app.post("/api/garment/delete")
def api_garment_delete(req: GarmentReq):
    p = os.path.join(DATA, "character.json")
    ch = read_json(p, {}) or {}
    gs = ch.get("garments") or {}
    if req.key not in gs:
        raise HTTPException(404, "no such outfit")
    if len(gs) <= 1:
        raise HTTPException(400, "keep at least one outfit")
    gs.pop(req.key)
    write_json(p, ch)
    return {"ok": True, "garments": gs}


# ---------------- engine / maintenance ----------------
@app.post("/api/config")
def api_config(req: ConfigReq):
    cfg = config.load()
    cfg.setdefault("model", {})
    for k in ("unet_name", "clip_name", "vae_name", "clip_type"):
        v = getattr(req, k)
        if v:
            cfg["model"][k] = v
    if req.comfy_dir:
        cfg["comfy_dir"] = req.comfy_dir
    config.save(cfg)
    return {"ok": True, "model": cfg.get("model"), "comfy_dir": cfg.get("comfy_dir", "")}


@app.get("/api/engine")
def api_engine():
    return gf.engine_info()


@app.post("/api/comfy/free")
def api_comfy_free():
    return cf.free()


@app.post("/api/comfy/start")
def api_comfy_start():
    cfg = config.load()
    d = cfg.get("comfy_dir") or ""
    if not d or not os.path.isdir(d):
        return {"ok": False, "error": "comfy_dir is not configured"}
    py = sys.executable
    main = os.path.join(d, "main.py")
    if not os.path.isfile(main):
        return {"ok": False, "error": "main.py not found under comfy_dir"}
    subprocess.Popen([py, main, "--listen", "127.0.0.1", "--port", "8188"],
                     cwd=d, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "note": "starting; give it 20-60 seconds"}


@app.get("/api/docs")
def api_docs():
    items = []
    if os.path.isdir(DOCS):
        for n in sorted(os.listdir(DOCS)):
            if n.endswith(".md"):
                items.append({"name": n, "size": os.path.getsize(os.path.join(DOCS, n))})
    return {"items": items}


@app.get("/api/doc")
def api_doc(name: str):
    p = os.path.abspath(os.path.join(DOCS, name))
    if not p.startswith(os.path.abspath(DOCS)) or not os.path.isfile(p):
        raise HTTPException(404, "not found")
    return FileResponse(p)


@app.get("/api/maintenance")
def api_maintenance():
    sizes = {}
    for d in ("output", "_trash"):
        p = os.path.join(HERE, d) if d != "_trash" else TRASH
    def dir_size(p):
        total = 0
        for dp, _, fs in os.walk(p):
            for f in fs:
                try:
                    total += os.path.getsize(os.path.join(dp, f))
                except Exception:
                    pass
        return total
    import shutil as sh
    du = sh.disk_usage(HERE)
    return {"disk": {"free_gb": round(du.free / 1073741824, 1),
                     "total_gb": round(du.total / 1073741824, 1)},
            "output_mb": round(dir_size(OUT_DIR) / 1048576, 1),
            "trash_mb": round(dir_size(TRASH) / 1048576, 1)}


@app.post("/api/maintenance/cleanup")
def api_cleanup():
    n = 0
    if os.path.isdir(TRASH):
        for dp, _, fs in os.walk(TRASH):
            for f in fs:
                try:
                    os.remove(os.path.join(dp, f))
                    n += 1
                except Exception:
                    pass
    return {"ok": True, "removed": n}


@app.get("/api/pipeline/check")
def api_pipeline():
    checks = []
    def add(name, ok, detail, fix=""):
        checks.append({"id": name, "name": name, "ok": bool(ok), "detail": detail, "fix": fix})

    tokens, lib, ch = pt.load_tokens()
    add("tokens", len(tokens) > 10, "%d blocks" % len(tokens), "add blocks in the Library page")
    cfg = config.load()
    model = cfg.get("model") or {}
    add("model", bool(model.get("unet_name")) and "your-" not in model.get("unet_name", ""),
        "unet=%s" % (model.get("unet_name") or "(empty)"),
        "run install/bind_pipeline.ps1 to bind your model")
    st = cf.system_stats()
    add("comfy", st["up"], "ComfyUI %s" % (st.get("version") or "offline"),
        "start ComfyUI or use Engine page")
    if st["up"]:
        info = cf.object_info()
        for name in gf.list_workflows():
            wf = gf.load(name)
            miss = [n for n in (wf.get("requires") or []) if n not in info]
            add("wf_" + name, not miss, ", ".join(miss) or "OK",
                "update ComfyUI or install missing custom nodes")
    return {"ok": all(c["ok"] for c in checks), "total": len(checks),
            "failed": sum(0 if c["ok"] else 1 for c in checks), "checks": checks}

# ---------------- parity features ----------------
from features import router as _features_router  # noqa: E402

app.include_router(_features_router)

from features2 import router as _features2_router  # noqa: E402

app.include_router(_features2_router)

from features3 import router as _features3_router  # noqa: E402

app.include_router(_features3_router)

# 让旧版 UI 的 /app.js、/style.css 从 static 根路径访问
app.mount("/", StaticFiles(directory=STATIC, html=True), name="root")
