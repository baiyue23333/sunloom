# -*- coding: utf-8 -*-
"""画廊、配方、蒙版、回收站、登记表、质检与导出路由。"""
import base64
import io
import json
import os
import re
import shutil
import time
import urllib.parse
import zipfile
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import store
from svc_recipes import _parse_png_recipe, add_recipe, mirror_score, recipe_from_png
from svc_state import (
    COOP_ROOTS,
    DRAFT_RE,
    IMG_EXT,
    MASK_DIR,
    OUT_DIR,
    ROOT,
    TRASH_DIR,
    delete_roots,
    img_allowed,
    registry_entries,
)

router = APIRouter()


class LogReq(BaseModel):
    path: str
    verdict: str = "B"
    note: str = ""
    seed: Optional[int] = None
    tags: str = ""
    params: str = ""


class ExportReq(BaseModel):
    paths: List[str] = []
    fmt: str = "zip"


class RecipeInferReq(BaseModel):
    path: str
    blocks_pos: List[Dict[str, Any]] = []
    blocks_neg: List[Dict[str, Any]] = []
    prompt: str = ""
    negative: str = ""
    loras: List[Dict[str, Any]] = []
    steps: int = 30
    cfg: float = 5.5


class RecipeFromImageReq(BaseModel):
    path: str


class RecipeRegisterReq(BaseModel):
    path: str
    data: Dict[str, Any] = {}


class MaskSaveReq(BaseModel):
    image: str
    mask_b64: str
    name: str = ""


class DeleteReq(BaseModel):
    path: str
    permanent: bool = False


class RestoreReq(BaseModel):
    path: str


class GlitchReq(BaseModel):
    path: str
    intensity: float = 0.6


def _is_final_name(name):
    low = (name or "").lower()
    if not low.endswith(IMG_EXT):
        return False
    stem = os.path.splitext(low)[0]
    if stem in ("comp", "final") or stem.startswith("final"):
        return True
    if stem.startswith("_"):
        return False
    return not DRAFT_RE.search(stem)


def _coop_finals():
    found = []
    for root in COOP_ROOTS:
        if not os.path.isdir(root):
            continue
        for dp, dns, fns in os.walk(root):
            rel = os.path.relpath(dp, root)
            parts = [] if rel == "." else rel.split(os.sep)
            skip_tokens = ("retry", "improv", "preview", "draft", "reject")
            if any(x.lower().startswith("_") or x.lower() in skip_tokens for x in parts):
                dns[:] = []
                continue
            if len(parts) >= 2:
                dns[:] = []
                continue
            for name in fns:
                low = name.lower()
                if low in ("comp.png", "final.png") or low.startswith("final"):
                    p = os.path.join(dp, name)
                    if _is_final_name(name):
                        found.append((os.path.getmtime(p), p))
    return found


def _gallery_entries(dir):
    if dir == "coop":
        return _coop_finals()
    if dir == "all":
        extra = ([(os.path.getmtime(os.path.join(OUT_DIR, n)), os.path.join(OUT_DIR, n))
                  for n in os.listdir(OUT_DIR) if _is_final_name(n)]
                 if os.path.isdir(OUT_DIR) else [])
        return _coop_finals() + extra
    base = OUT_DIR if dir == "station_out" else os.path.join(ROOT, "SD-Picture", dir)
    if not os.path.isdir(base):
        return []
    return [(os.path.getmtime(os.path.join(base, n)), os.path.join(base, n))
            for n in os.listdir(base) if _is_final_name(n)]


@router.get("/api/gallery")
def api_gallery(dir: str = "station_out", limit: int = 60, offset: int = 0):
    files = sorted(_gallery_entries(dir), reverse=True)
    reg = {os.path.basename(r.get("file", "")): r for r in registry_entries()}
    total = len(files)
    sliced = files if limit <= 0 else files[offset:offset + limit]
    items = []
    for mt, p in sliced:
        name = os.path.basename(p)
        e = reg.get(name)
        label = os.path.relpath(p, os.path.join(ROOT, "SD-Picture")) if dir in ("coop", "all") else name
        items.append({"path": p, "name": name, "label": label, "mtime": int(mt),
                      "verdict": (e or {}).get("verdict", ""), "note": (e or {}).get("note", "")})
    return {"items": items, "total": total}


@router.post("/api/glitch")
def api_glitch(req: GlitchReq):
    import glitchify
    src = req.path
    if not os.path.isfile(src):
        raise HTTPException(404, "图片不存在")
    base, _ext = os.path.splitext(src)
    dst = base + "_glitch.png"
    glitchify.glitchify(src, dst, max(0.1, min(2.0, req.intensity)))
    return {"ok": True, "path": dst}


@router.get("/api/img")
def api_img(path: str):
    if not img_allowed(path):
        raise HTTPException(403, "路径不在允许目录内")
    if not os.path.isfile(path):
        raise HTTPException(404, "not found")
    return FileResponse(path)


@router.post("/api/log")
def api_log(req: LogReq):
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "file": req.path,
             "verdict": req.verdict, "note": req.note, "seed": req.seed,
             "tags": req.tags, "params": req.params}
    store.append_registry(entry)
    return {"ok": True, "entry": entry}


@router.get("/api/registry")
def api_registry(limit: int = 200):
    rows = registry_entries()
    return {"items": list(reversed(rows))[:limit], "total": len(rows)}


@router.get("/api/qc")
def api_qc(path: str):
    try:
        import numpy as np
        from PIL import Image
        im = Image.open(path).convert("RGB")
        arr = np.asarray(im).astype(np.float32) / 255.0
        lum = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]
        h, w = lum.shape
        face = lum[int(h * 0.08):int(h * 0.32), int(w * 0.3):int(w * 0.7)]
        over = float((lum > 0.98).mean())
        dead = float((lum < 0.02).mean())
        ms = mirror_score(path)
        return {"ok": True, "mirror": ms, "split_suspect": ms >= 0.86,
                "mean": round(float(lum.mean()), 3), "face_mean": round(float(face.mean()), 3),
                "highlight_pct": round(over * 100, 2), "dead_black_pct": round(dead * 100, 2),
                "overexposed": over > 0.04, "dead_black_bad": dead > 0.25}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/export")
def api_export(req: ExportReq):
    if not req.paths:
        raise HTTPException(400, "没有选图")
    out_dir = os.path.join(ROOT, "SD-Picture", "exports")
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(out_dir, "export_%s.zip" % ts)
    rp = store.load_recipes()
    lines, n = [], 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in req.paths:
            if not os.path.isfile(p):
                continue
            z.write(p, os.path.basename(p))
            n += 1
            r = rp.get(p)
            if r:
                z.writestr(os.path.splitext(os.path.basename(p))[0] + ".recipe.json",
                           json.dumps(r, ensure_ascii=False, indent=2))
                lines.append("### " + os.path.basename(p))
                lines.append("seed=%s steps=%s cfg=%s size=%s" % (r.get("seed"), r.get("steps"),
                                                                  r.get("cfg"), r.get("size")))
                lines.append("loras: " + ", ".join("%s x%s" % (l.get("name"), l.get("weight"))
                                                   for l in (r.get("loras") or [])))
                lines.append("POS: " + (r.get("positive") or "")[:2000])
                lines.append("NEG: " + (r.get("negative") or "")[:1200])
                lines.append("")
        z.writestr("prompts.txt", "\n".join(lines))
        z.writestr("README.txt", "导出时间 %s\n共 %d 张图，配方见 *.recipe.json 与 prompts.txt\n" % (ts, n))
    return {"ok": True, "zip": zip_path, "count": n, "url": "/api/download?path=" + urllib.parse.quote(zip_path)}


@router.get("/api/download")
def api_download(path: str):
    if not os.path.isfile(path):
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, filename=os.path.basename(path))


@router.post("/api/recipe/infer")
def api_recipe_infer(req: RecipeInferReq):
    if not os.path.isfile(req.path):
        raise HTTPException(404, "图片不存在")
    try:
        from PIL import Image
        with Image.open(req.path) as im:
            w, h = im.size
    except Exception:
        w, h = 1024, 1536
    m = re.search(r"_s(\d+)", os.path.basename(req.path))
    seed = int(m.group(1)) if m else 0
    prev = store.get_recipe(req.path) or {}
    rec = {
        "ts": os.path.getmtime(req.path), "mode": "t2i", "workflow": "anima_t2i",
        "positive": req.prompt, "negative": req.negative or prev.get("negative", ""),
        "blocks_pos": req.blocks_pos, "blocks_neg": req.blocks_neg,
        "size": [w, h], "steps": req.steps, "cfg": req.cfg, "seed": seed,
        "denoise": 1.0, "loras": req.loras, "reference": "", "mask": "",
        "inferred": True, "source_template": "当前积木推断",
        "note": "种子取自文件名，尺寸取自图片，其余为当前积木/参数。",
    }
    add_recipe(req.path, rec)
    return {"ok": True, "seed": seed, "size": [w, h]}


@router.post("/api/recipe/from-image")
def api_recipe_from_image(req: RecipeFromImageReq):
    if not os.path.isfile(req.path):
        raise HTTPException(404, "图片不存在")
    r = recipe_from_png(req.path, upsert=True)
    if not r:
        raise HTTPException(400, "这张图里没有 ComfyUI 元数据")
    return {"ok": True, "recipe": r}


@router.post("/api/recipe/backfill")
def api_recipe_backfill():
    db = store.load_recipes()
    n, skipped = 0, 0
    for d in ("station_out", "harvest", "remote_out"):
        folder = os.path.join(ROOT, "SD-Picture", d)
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if not name.lower().endswith(".png"):
                continue
            path = os.path.join(folder, name)
            if path in db and db[path].get("exact"):
                skipped += 1
                continue
            r = recipe_from_png(path, upsert=False)
            if not r:
                skipped += 1
                continue
            store.upsert_recipe(path, r)
            n += 1
    total = len(store.load_recipes())
    return {"ok": True, "recovered": n, "skipped": skipped, "total": total}


@router.get("/api/recipe")
def api_recipe(path: str):
    r = store.get_recipe(path)
    if not r:
        raise HTTPException(404, "这张图没有配方记录")
    r = dict(r)
    if not r.get("blocks_pos") or not r.get("blocks_neg"):
        pr = _parse_png_recipe(path) if os.path.isfile(path) else None
        if pr:
            if not r.get("blocks_pos") and pr.get("blocks_pos"):
                r["blocks_pos"] = pr["blocks_pos"]
                r["blocks_guess"] = True
            if not r.get("blocks_neg") and pr.get("blocks_neg"):
                r["blocks_neg"] = pr["blocks_neg"]
                r["blocks_guess"] = True
            if r.get("blocks_guess"):
                store.upsert_recipe(path, r)
    r["path"] = path
    return r


@router.post("/api/recipe/register")
def api_recipe_register(req: RecipeRegisterReq):
    if not req.path or not os.path.isfile(req.path):
        raise HTTPException(404, "图片不存在")
    if not img_allowed(req.path):
        raise HTTPException(403, "路径不在允许目录内")
    data = dict(req.data or {})
    data.setdefault("ts", os.path.getmtime(req.path))
    ok = add_recipe(req.path, data)
    return {"ok": bool(ok), "path": req.path}


@router.get("/api/recipes/export")
def api_recipes_export():
    return JSONResponse(store.load_recipes())


@router.get("/api/recipes")
def api_recipes(limit: int = 60):
    db = store.load_recipes()
    items, missing = [], 0
    for path, r in db.items():
        if not os.path.isfile(path):
            missing += 1
            continue
        items.append({"path": path, "name": os.path.basename(path),
                      "ts": r.get("ts", 0), "mode": r.get("mode", ""),
                      "lora_n": len(r.get("loras") or []),
                      "has_manifest": bool(r.get("manifest_path"))})
    items.sort(key=lambda x: -x["ts"])
    return {"total": len(items), "missing": missing, "items": items[:limit]}


@router.post("/api/mask/save")
def api_mask_save(req: MaskSaveReq):
    if not req.mask_b64:
        raise HTTPException(400, "蒙版为空")
    os.makedirs(MASK_DIR, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_-]", "", os.path.splitext(os.path.basename(req.image))[0])[:40] or "mask"
    tag = re.sub(r"[^A-Za-z0-9_-]", "", req.name or "")[:20]
    fname = "%s_%s.png" % (stem, tag or time.strftime("%H%M%S"))
    path = os.path.join(MASK_DIR, fname)
    raw = req.mask_b64.split(",", 1)[-1]
    try:
        data = base64.b64decode(raw)
    except Exception:
        raise HTTPException(400, "蒙版解码失败")
    try:
        from PIL import Image
        src = Image.open(io.BytesIO(data))
        if src.mode == "RGBA":
            src = Image.alpha_composite(Image.new("RGBA", src.size, (0, 0, 0, 255)), src)
        m = src.convert("RGB").getchannel("R").point(lambda v: 255 if v >= 24 else 0)
        rgba = Image.new("RGBA", src.size, (0, 0, 0, 0))
        rgba.paste((255, 45, 85, 255), mask=m)
        rgba.save(path)
    except Exception:
        with open(path, "wb") as f:
            f.write(data)
    return {"ok": True, "path": path, "name": fname}


@router.get("/api/mask/list")
def api_mask_list(image: str = "", limit: int = 40):
    os.makedirs(MASK_DIR, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_-]", "", os.path.splitext(os.path.basename(image))[0])[:40] if image else ""
    items = []
    for n in os.listdir(MASK_DIR):
        if not n.lower().endswith(".png") or (stem and not n.startswith(stem)):
            continue
        p = os.path.join(MASK_DIR, n)
        items.append({"name": n, "path": p, "ts": os.path.getmtime(p), "size": os.path.getsize(p)})
    items.sort(key=lambda x: -x["ts"])
    return {"items": items[:limit], "total": len(items)}


@router.post("/api/delete-image")
def api_delete_image(req: DeleteReq):
    path = os.path.abspath(req.path)
    if not os.path.isfile(path):
        raise HTTPException(404, "文件不存在")
    if not any(os.path.commonpath([path, os.path.abspath(r)]) == os.path.abspath(r) for r in delete_roots()):
        raise HTTPException(403, "只允许删除 SD-Picture 或 ComfyUI output 下的文件")
    if req.permanent:
        os.remove(path)
        return {"ok": True, "mode": "deleted", "path": path}
    day = time.strftime("%Y%m%d")
    dst_dir = os.path.join(TRASH_DIR, day)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(path))
    if os.path.exists(dst):
        dst = os.path.join(dst_dir, "%s_%s%s" % (
            os.path.splitext(os.path.basename(path))[0], time.strftime("%H%M%S"), os.path.splitext(path)[1]))
    shutil.move(path, dst)
    try:
        with open(dst + ".json", "w", encoding="utf-8") as f:
            json.dump({"orig": path, "at": time.time()}, f, ensure_ascii=False)
    except Exception:
        pass
    return {"ok": True, "mode": "trash", "path": path, "trash": dst}


def _restore_file(p):
    meta = p + ".json"
    orig = None
    if os.path.isfile(meta):
        try:
            orig = json.load(open(meta, encoding="utf-8")).get("orig")
        except Exception:
            orig = None
    if not orig:
        orig = os.path.join(ROOT, "SD-Picture", "harvest", os.path.basename(p))
    os.makedirs(os.path.dirname(orig), exist_ok=True)
    if os.path.exists(orig):
        base, ext = os.path.splitext(orig)
        orig = base + "_restored" + time.strftime("%H%M%S") + ext
    shutil.move(p, orig)
    try:
        os.remove(meta)
    except Exception:
        pass
    return orig


@router.post("/api/trash/restore")
def api_trash_restore(req: RestoreReq):
    if not os.path.isfile(req.path):
        raise HTTPException(404, "回收站里没有这个文件")
    if os.path.commonpath([os.path.abspath(req.path), TRASH_DIR]) != os.path.abspath(TRASH_DIR):
        raise HTTPException(403, "只能恢复回收站里的文件")
    return {"ok": True, "restored": _restore_file(req.path)}


@router.post("/api/trash/restore-all")
def api_trash_restore_all():
    done = []
    if os.path.isdir(TRASH_DIR):
        for dp, _, fs in os.walk(TRASH_DIR):
            for f in fs:
                if not f.endswith(".json"):
                    try:
                        done.append(_restore_file(os.path.join(dp, f)))
                    except Exception:
                        pass
    return {"ok": True, "count": len(done), "restored": done[:50]}


@router.post("/api/trash/purge")
def api_trash_purge():
    n = 0
    if os.path.isdir(TRASH_DIR):
        for dp, _, fs in os.walk(TRASH_DIR):
            for f in fs:
                try:
                    os.remove(os.path.join(dp, f))
                    n += 1
                except Exception:
                    pass
        for dp, ds, _ in os.walk(TRASH_DIR, topdown=False):
            for d in ds:
                try:
                    os.rmdir(os.path.join(dp, d))
                except Exception:
                    pass
    return {"ok": True, "removed": n}


@router.get("/api/trash")
def api_trash():
    items = []
    if os.path.isdir(TRASH_DIR):
        for dp, _, fs in os.walk(TRASH_DIR):
            for f in fs:
                p = os.path.join(dp, f)
                items.append({"path": p, "name": f, "size": os.path.getsize(p)})
    total = sum(x["size"] for x in items)
    return {"count": len(items), "mb": round(total / 1048576, 1), "items": items[:200]}
