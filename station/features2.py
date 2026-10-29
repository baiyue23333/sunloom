# -*- coding: utf-8 -*-
"""features2.py - library/outfit full CRUD + optional training & tagging modules."""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import prompts as pt
import server as S

router = APIRouter()
HERE = S.HERE
DATA = S.DATA
DATASETS = os.path.join(DATA, "datasets")
TOOLS = os.path.join(os.path.dirname(HERE), "tools")


# ---------------- library ----------------
class MetaReq(BaseModel):
    name: str
    category: str = ""
    note: str = ""


class ImportReq(BaseModel):
    data: str = ""
    path: str = ""


@router.get("/api/library")
def api_library(q: str = "", cat: str = ""):
    tokens, lib, _ = pt.load_tokens()
    cats = (lib.get("meta") or {}).get("cats") or {}
    items = []
    for k, v in tokens.items():
        c = cats.get(k) or _guess_cat(k)
        if q and q.lower() not in k.lower() and q.lower() not in (v or "").lower():
            continue
        if cat and c != cat:
            continue
        items.append({"name": k, "text": v, "category": c,
                      "note": (lib.get("notes") or {}).get(k, "")})
    items.sort(key=lambda x: (x["category"], x["name"]))
    counts = {}
    for k, v in tokens.items():
        c = cats.get(k) or _guess_cat(k)
        counts[c] = counts.get(c, 0) + 1
    return {"items": items, "counts": counts, "total": len(tokens)}


def _guess_cat(name):
    up = name.upper()
    table = [
        ("主体", ["@SUBJ", "@BODY", "@FACE"]),
        ("姿势", ["@POSE"]), ("表情", ["@MOOD", "@GAZE"]), ("手发", ["@HAND", "@HAIR"]),
        ("机位", ["@CAM"]), ("打光", ["@LIGHT"]), ("氛围", ["@ATMO", "@TIME"]),
        ("服装", ["@OUT", "@FAB", "@DRAPE", "@OUTFIT"]), ("场景", ["@SET"]),
        ("道具", ["@PROP"]), ("构图", ["@COMP"]), ("风格", ["@STYLE"]), ("负向", ["@NEG"]),
    ]
    for label, prefixes in table:
        if any(up.startswith(p) for p in prefixes):
            return label
    return "其他"


@router.post("/api/token/meta")
def api_token_meta(req: MetaReq):
    _, lib, _ = pt.load_tokens()
    lib.setdefault("meta", {}).setdefault("cats", {})
    if req.category:
        lib["meta"]["cats"][req.name] = req.category
    if req.note:
        lib.setdefault("notes", {})[req.name] = req.note
    pt.write_json(pt.LIB, lib)
    return {"ok": True}


@router.post("/api/library/import")
def api_library_import(req: ImportReq):
    raw = req.data
    if not raw and req.path and os.path.isfile(req.path):
        raw = open(req.path, encoding="utf-8").read()
    if not raw:
        raise HTTPException(400, "empty import")
    try:
        data = json.loads(raw)
    except Exception:
        raise HTTPException(400, "import must be JSON")
    tokens, lib, _ = pt.load_tokens()
    added = 0
    for k, v in (data.get("tokens") or data).items():
        if not isinstance(v, str):
            continue
        key = k if k.startswith("@") else "@" + k.upper()
        if key not in tokens:
            added += 1
        lib.setdefault("tokens", {})[key] = v
    for k, v in ((data.get("notes") or {}).items() if isinstance(data, dict) else []):
        lib.setdefault("notes", {})[k] = v
    for k, v in ((data.get("cats") or {}).items() if isinstance(data, dict) else []):
        lib.setdefault("meta", {}).setdefault("cats", {})[k] = v
    pt.write_json(pt.LIB, lib)
    return {"ok": True, "added": added, "total": len(lib.get("tokens") or {})}


@router.get("/api/library/export")
def api_library_export():
    _, lib, _ = pt.load_tokens()
    out = os.path.join(DATA, "library_export.json")
    payload = {"tokens": lib.get("tokens") or {}, "notes": lib.get("notes") or {},
               "cats": (lib.get("meta") or {}).get("cats") or {}}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return FileResponse(out, filename="library.json", media_type="application/json")


# ---------------- outfits ----------------
class GarmentFullReq(BaseModel):
    key: str
    label: str = ""
    use_for: str = ""
    prompt: str = ""
    negative: str = ""
    material: str = ""
    drape: str = ""


@router.post("/api/garment/default")
def api_garment_default(req: GarmentFullReq):
    path = os.path.join(DATA, "character.json")
    ch = S.read_json(path, {}) or {}
    if req.key not in (ch.get("garments") or {}):
        raise HTTPException(404, "no such outfit")
    ch["garment_default"] = req.key
    S.write_json(path, ch)
    return {"ok": True, "default": req.key}


@router.post("/api/garment/duplicate")
def api_garment_duplicate(req: GarmentFullReq):
    path = os.path.join(DATA, "character.json")
    ch = S.read_json(path, {}) or {}
    gs = ch.get("garments") or {}
    if req.key not in gs:
        raise HTTPException(404, "no such outfit")
    base = req.key
    n = 2
    while ("%s_%d" % (base, n)) in gs:
        n += 1
    key = "%s_%d" % (base, n)
    g = dict(gs[base])
    g["label"] = (g.get("label") or base) + " 副本"
    gs[key] = g
    ch["garments"] = gs
    S.write_json(path, ch)
    return {"ok": True, "key": key, "garments": gs}


@router.get("/api/garments/export")
def api_garments_export():
    path = os.path.join(DATA, "character.json")
    ch = S.read_json(path, {}) or {}
    out = os.path.join(DATA, "outfits_export.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"garments": ch.get("garments") or {},
                   "garment_default": ch.get("garment_default", "")}, f, ensure_ascii=False, indent=2)
    return FileResponse(out, filename="outfits.json", media_type="application/json")


@router.post("/api/garments/import")
def api_garments_import(req: ImportReq):
    raw = req.data
    if not raw and req.path and os.path.isfile(req.path):
        raw = open(req.path, encoding="utf-8").read()
    try:
        data = json.loads(raw)
    except Exception:
        raise HTTPException(400, "import must be JSON")
    path = os.path.join(DATA, "character.json")
    ch = S.read_json(path, {}) or {}
    gs = ch.setdefault("garments", {})
    added = 0
    for k, v in (data.get("garments") or data).items():
        if isinstance(v, dict):
            if k not in gs:
                added += 1
            gs[k] = v
    if data.get("garment_default") in gs:
        ch["garment_default"] = data["garment_default"]
    S.write_json(path, ch)
    return {"ok": True, "added": added, "garments": gs}


# ---------------- datasets / tagging / training ----------------
@router.get("/api/datasets")
def api_datasets():
    os.makedirs(DATASETS, exist_ok=True)
    items = []
    for n in sorted(os.listdir(DATASETS)):
        d = os.path.join(DATASETS, n)
        if not os.path.isdir(d):
            continue
        imgs = [f for f in os.listdir(d) if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
        items.append({"name": n, "path": d, "images": len(imgs)})
    return {"items": items}


@router.get("/api/tag/check")
def api_tag_check():
    try:
        import onnxruntime  # noqa
        ok = True
        err = ""
    except Exception as e:
        ok, err = False, str(e)
    return {"ok": ok, "error": err,
            "model": (S.CFG.get("tagger") or {}).get("model_dir", ""),
            "script": os.path.join(TOOLS, "tag_wd14.py")}


class TagReq(BaseModel):
    dataset: str
    threshold: float = 0.35
    trigger: str = ""
    extra: str = ""
    write: bool = False
    preview: int = 5


@router.post("/api/tag/start")
def api_tag_start(req: TagReq):
    folder = os.path.join(DATASETS, req.dataset) if not os.path.isabs(req.dataset) else req.dataset
    if not os.path.isdir(folder):
        raise HTTPException(400, "dataset not found")
    script = os.path.join(TOOLS, "tag_wd14.py")
    args = [sys.executable, script, "--dir", folder, "--threshold", str(req.threshold),
            "--preview", str(req.preview)]
    model_dir = (S.CFG.get("tagger") or {}).get("model_dir", "")
    if model_dir:
        args += ["--model", model_dir]
    if req.trigger:
        args += ["--trigger", req.trigger]
    if req.extra:
        args += ["--extra", req.extra]
    if req.write:
        args += ["--write"]
    jid = S.job_new("tag", req.dataset)

    def work():
        try:
            p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace")
            for line in p.stdout:
                S.job_log(jid, line.rstrip())
            code = p.wait()
            S.JOBS[jid].update(status="done" if code == 0 else "error", progress=1.0,
                               result={"exit": code})
        except Exception as e:
            S.JOBS[jid].update(status="error", result={"error": str(e)[:400]})

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid, "cmd": " ".join(args)}


class TrainReq(BaseModel):
    dataset: str
    output: str = "my_lora"
    dim: int = 32
    epochs: int = 10
    batch: int = 1
    lr: float = 1e-4
    trigger: str = ""
    base_model: str = ""


@router.get("/api/train/check")
def api_train_check():
    kohya = (S.CFG.get("kohya_dir") or "")
    ok = bool(kohya) and os.path.isfile(os.path.join(kohya, "train_network.py"))
    return {"ok": ok, "kohya_dir": kohya,
            "script": os.path.join(TOOLS, "train_lora.ps1")}


@router.post("/api/train/start")
def api_train_start(req: TrainReq):
    folder = os.path.join(DATASETS, req.dataset) if not os.path.isabs(req.dataset) else req.dataset
    if not os.path.isdir(folder):
        raise HTTPException(400, "dataset not found")
    kohya = (S.CFG.get("kohya_dir") or "")
    if not kohya or not os.path.isfile(os.path.join(kohya, "train_network.py")):
        raise HTTPException(400, "kohya sd-scripts 未配置：先运行 tools/setup/install_kohya.ps1，或在 config.json 写 kohya_dir")
    script = os.path.join(TOOLS, "train_lora.ps1")
    args = ["powershell", "-ExecutionPolicy", "Bypass", "-File", script,
            "-Dataset", folder, "-OutputName", req.output, "-KohyaDir", kohya,
            "-Dim", str(req.dim), "-Epochs", str(req.epochs), "-BatchSize", str(req.batch),
            "-LR", str(req.lr)]
    if req.base_model:
        args += ["-BaseModel", req.base_model]
    if req.trigger:
        args += ["-Trigger", req.trigger]
    jid = S.job_new("train", req.output)

    def work():
        try:
            p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace")
            for line in p.stdout:
                S.job_log(jid, line.rstrip())
                m = re.search(r"(\d+)\s*/\s*(\d+)", line)
                if m:
                    try:
                        S.JOBS[jid]["progress"] = min(0.99, int(m.group(1)) / max(1, int(m.group(2))))
                    except Exception:
                        pass
            code = p.wait()
            S.JOBS[jid].update(status="done" if code == 0 else "error", progress=1.0,
                               result={"exit": code})
        except Exception as e:
            S.JOBS[jid].update(status="error", result={"error": str(e)[:400]})

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid}

# ---------------- loras ----------------
@router.get("/api/loras")
def api_loras():
    cfg = __import__("config").load()
    root = cfg.get("comfy_dir") or ""
    found = []
    for sub in ("models/loras", "models/Lora", "models/lycoris"):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for base, dirs, files in os.walk(d):
            for f in files:
                if f.lower().endswith((".safetensors", ".pt", ".ckpt")):
                    rel = os.path.relpath(os.path.join(base, f), d).replace("\\", "/")
                    found.append({"name": rel, "size": os.path.getsize(os.path.join(base, f))})
    found.sort(key=lambda x: x["name"].lower())
    defaults = (cfg.get("defaults") or {}).get("loras") or []
    return {"items": found, "defaults": defaults,
            "dir": os.path.join(root, "models/loras") if root else ""}

# ---------------- character cards ----------------
class CardReq(BaseModel):
    name: str
    loras: List[Dict[str, Any]] = []
    tokens: List[str] = []
    note: str = ""


class CardImportReq(BaseModel):
    data: str = ""
    path: str = ""


def _cards_path():
    return os.path.join(S.DATA, "cards.json")


@router.get("/api/cards")
def api_cards():
    return {"items": S.read_json(_cards_path(), []) or []}


@router.post("/api/card/save")
def api_card_save(req: CardReq):
    items = S.read_json(_cards_path(), []) or []
    entry = {"name": req.name.strip(), "loras": req.loras or [],
             "tokens": req.tokens or [], "note": req.note or ""}
    items = [it for it in items if it.get("name") != entry["name"]]
    items.append(entry)
    S.write_json(_cards_path(), items)
    return {"ok": True, "items": items}


@router.post("/api/card/delete")
def api_card_delete(req: CardReq):
    items = S.read_json(_cards_path(), []) or []
    items = [it for it in items if it.get("name") != req.name]
    S.write_json(_cards_path(), items)
    return {"ok": True, "items": items}


@router.get("/api/cards/export")
def api_cards_export():
    return FileResponse(_cards_path(), filename="character_cards.json",
                        media_type="application/json")


@router.post("/api/cards/import")
def api_cards_import(req: CardImportReq):
    raw = req.data
    if not raw and req.path and os.path.isfile(req.path):
        raw = open(req.path, encoding="utf-8").read()
    if not raw:
        raise HTTPException(400, "empty import")
    try:
        data = json.loads(raw)
    except Exception:
        raise HTTPException(400, "import must be JSON")
    incoming = data.get("items") if isinstance(data, dict) else data
    if not isinstance(incoming, list):
        raise HTTPException(400, "expect a list of cards")
    items = S.read_json(_cards_path(), []) or []
    names = {it.get("name") for it in items}
    added = 0
    for c in incoming:
        if isinstance(c, dict) and c.get("name") and c["name"] not in names:
            items.append(c)
            added += 1
    S.write_json(_cards_path(), items)
    return {"ok": True, "added": added, "items": items}
