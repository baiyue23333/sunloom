# -*- coding: utf-8 -*-
"""引导初始化、状态轮询、画师索引、积木/服装/模板/预设管理路由。"""
import json
import os
import subprocess
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import comfy as cf
import store
from svc_jobs import Block
from svc_obs import warn
from svc_state import (
    CHAR,
    LIB,
    OUT_DIR,
    PRESETS,
    PY,
    REF,
    ROOT,
    _load_json,
    _lora_base_map,
    list_datasets,
    list_loras,
    list_models,
    load_tokens,
    pt,
    read_json,
    write_json,
)

router = APIRouter()

ARTIST_RECIPES_PATH = os.path.join(REF, "artist_recipes.json")
FREE_INDEX = os.path.join(REF, "artist_free_index.json")
ENV_EXCLUDE = os.path.join(REF, "env_exclude.json")
LORA_ROLES = os.path.join(REF, "lora_roles.json")
CHAR_INDEX = os.path.join(REF, "artist_index_char.json")
ENV_INDEX = os.path.join(REF, "artist_index_env.json")
REF_INDEX = os.path.join(ROOT, "产出作品", "画师参考", "_index.json")


class ArtistRecipeReq(BaseModel):
    name: str
    weight: Optional[float] = None
    byChar: Dict[str, float] = {}
    note: str = ""


class TokenReq(BaseModel):
    name: str
    text: str
    category: str = "custom"
    subgroup: str = ""
    color: str = ""
    gender: str = ""
    owner: str = ""


class GarmentReq(BaseModel):
    key: str
    prompt: str = ""
    negative: str = ""
    drape: str = ""
    label: str = ""
    use_for: str = ""
    hands_left: str = ""
    hands_right: str = ""
    note: str = ""
    gender: str = "f"


class PresetReq(BaseModel):
    name: str
    positive: List[Block] = []
    negative: List[Block] = []
    params: Dict[str, Any] = {}


class TplSaveReq(BaseModel):
    name: str
    params: dict = {}
    positive: List[Any] = []
    negative: List[Any] = []


class ReliabilityReq(BaseModel):
    token: str
    status: str = ""
    note: str = ""


def _load_artist_recipes():
    return _load_json(ARTIST_RECIPES_PATH, {})


@router.get("/api/artist_recipes")
def api_artist_recipes():
    return {"items": _load_artist_recipes()}


@router.post("/api/artist_recipe")
def api_artist_recipe(req: ArtistRecipeReq):
    items = _load_artist_recipes()
    key = req.name
    cur = items.get(key, {})
    if req.weight is not None:
        cur["weight"] = round(float(req.weight), 3)
    if req.byChar:
        cur.setdefault("byChar", {}).update({k: round(float(v), 3) for k, v in req.byChar.items()})
    if req.note:
        cur["note"] = req.note
    items[key] = cur
    os.makedirs(os.path.dirname(ARTIST_RECIPES_PATH), exist_ok=True)
    with open(ARTIST_RECIPES_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    return {"ok": True, "items": items}


@router.get("/api/artist_preview")
def api_artist_preview(name: str = "", kind: str = "char"):
    """画师悬停预览：人物画师看肖像，环境画师看空景。"""
    primary = ENV_INDEX if kind == "env" else CHAR_INDEX
    other = CHAR_INDEX if kind == "env" else ENV_INDEX
    idx, alt = {}, {}
    for path, box in ((primary, idx), (other, alt), (FREE_INDEX, alt)):
        try:
            with open(path, encoding="utf-8") as f:
                for k, v in json.load(f).items():
                    box.setdefault(k, v)
        except Exception:
            continue
    ref, ref_mtime = "", 0
    if kind != "env":
        try:
            with open(REF_INDEX, encoding="utf-8") as f:
                ref = (json.load(f) or {}).get(name) or ""
        except Exception:
            ref = ""
        if ref and os.path.isfile(ref):
            ref_mtime = int(os.path.getmtime(ref))
        else:
            ref = ""
    entry = idx.get(name) or alt.get(name) or {}
    items = []
    for k in sorted(entry, key=lambda x: float(x)):
        path = entry[k]
        if path and os.path.isfile(path):
            items.append({"weight": float(k), "path": path, "mtime": int(os.path.getmtime(path))})
    items = items[:3]
    if not items and ref:
        items = [{"weight": 1.0, "path": ref, "mtime": ref_mtime}]
    if kind == "env":
        advice = [
            {"weight": 0.6, "text": "轻：只补细节与空气感，场景构图自由"},
            {"weight": 1.0, "text": "标准：环境质感与层次平衡"},
            {"weight": 1.3, "text": "重：材质与光感压过构图，可能过曝"},
        ]
    else:
        advice = [
            {"weight": 0.6, "text": "轻：只借笔触，构图/角色更自由"},
            {"weight": 1.0, "text": "标准：风格与角色平衡，最稳"},
            {"weight": 1.3, "text": "重：风格压过一切，可能吞细节/偏色"},
        ]
    return JSONResponse(
        {"name": name, "kind": kind, "ref": ref, "ref_mtime": ref_mtime, "items": items, "advice": advice},
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/status")
def api_status():
    """轻量状态，给前端轮询用（bootstrap 约 180KB）。"""
    st = cf.system_stats()
    if not st.get("up"):
        time.sleep(0.4)
        st = cf.system_stats()
    q = cf.queue_state() if st.get("up") else {"running": 0, "pending": 0}
    return {"comfy": {"up": bool(st.get("up")), "version": st.get("version"), "url": cf.COMFY},
            "queue": {"running": q.get("running", 0), "pending": q.get("pending", 0)}}


def _taxonomy_payload():
    try:
        import classify_blocks as cb
        return {
            "prefix_rules": [[p, c] for p, c in cb.RULES],
            "nsfw_tokens": sorted(cb.NSFW),
            "small_scenes": sorted(cb.SMALL),
            "medium_scenes": sorted(cb.MEDIUM),
        }
    except Exception as e:
        warn("taxonomy_load", e)
        return {}


@router.get("/api/bootstrap")
def bootstrap():
    tokens, lib, ch = load_tokens()
    notes = dict(lib.get("notes") or {})
    for key, g in (ch.get("garments") or {}).items():
        meta = g.get("label") or key
        notes.setdefault("@OUT_" + key.upper(),
                         (g.get("note") or "").strip() or (meta + "：这套服装的正向提示词，服装页里可编辑。"))
        neg = (g.get("negative") or "").strip()
        neg_txt = ("：" + neg[:60] + ("…" if len(neg) > 60 else "")) if neg else "。"
        notes.setdefault("@NEG_" + key.upper(), meta + " 的配套负向" + neg_txt + "（服装页可改）")
    notes.setdefault("@OUTFIT_A", "默认套装上半段（拆分版，便于单独调权重）")
    notes.setdefault("@OUTFIT_B", "默认套装下半段（拆分版）")
    notes.setdefault("@NEG_BASE_A", "基础负向上半段：画质与结构")
    notes.setdefault("@NEG_BASE_B", "基础负向下半段：伪影与文字")
    notes.setdefault("@OUTFIT", "当前默认套装的正向（由服装页 garment_default 决定）")
    notes.setdefault("@NEG_GARMENT", "当前默认套装的配套负向")
    return {
        "tokens": tokens,
        "notes": notes,
        "token_meta": lib.get("meta", {}),
        "aliases": dict(getattr(pt, "ALIASES", {}) or {}),
        "taxonomy": _taxonomy_payload(),
        "garments": ch.get("garments", {}),
        "character": {k: v for k, v in ch.items() if k != "garments"},
        "comfy": dict(cf.system_stats(), url=cf.COMFY),
        "queue": cf.queue_state(),
        "datasets": list_datasets(),
        "loras": list_loras(),
        "lora_meta": _lora_base_map(),
        "alt_models": [],
        "lora_roles": _load_json(LORA_ROLES, {}),
        "env_exclude": (_load_json(ENV_EXCLUDE, {}) or {}).get("names", []),
        "models": list_models(),
        "defaults": {
            "width": 1024, "height": 1536, "steps": 30, "cfg": 5.5,
            "loras": [],
        },
        "paths": {"root": ROOT, "ref": REF, "out": OUT_DIR},
    }


@router.post("/api/loras/refresh")
def api_loras_refresh():
    meta = _lora_base_map(force=True)
    return {"ok": True, "count": len(meta), "loras": list_loras(), "lora_meta": meta}


@router.post("/api/token/reliability")
def api_token_reliability(req: ReliabilityReq):
    st = (req.status or "").strip().upper()
    if st not in ("OK", "X", "?", ""):
        raise HTTPException(400, "status 须为 OK / X / ? 或空字符串")
    lib = read_json(LIB, {"tokens": {}}) or {}
    meta = lib.setdefault("meta", {})
    rel = meta.setdefault("reliability", {})
    tok = req.token if req.token.startswith("@") else "@" + req.token.upper()
    if not st:
        rel.pop(tok, None)
    else:
        rel[tok] = {"status": st, "note": (req.note or "").strip(), "updated_at": round(time.time(), 1)}
    write_json(LIB, lib)
    return {"ok": True, "token": tok, "reliability": rel.get(tok)}


@router.post("/api/token/note")
def api_token_note(req: TokenReq):
    lib = read_json(LIB, {"tokens": {}}) or {}
    notes = lib.setdefault("notes", {})
    name = req.name if req.name.startswith("@") else "@" + req.name.upper()
    if req.text.strip():
        notes[name] = req.text.strip()
    else:
        notes.pop(name, None)
    write_json(LIB, lib)
    return {"ok": True, "notes": notes}


@router.post("/api/token/save")
def api_token_save(req: TokenReq):
    lib = read_json(LIB, {"tokens": {}}) or {}
    toks = lib.setdefault("tokens", {})
    name = req.name if req.name.startswith("@") else "@" + req.name.upper()
    toks[name] = req.text
    meta = lib.setdefault("meta", {})
    subs = meta.setdefault("subgroups", {})
    if req.subgroup.strip():
        subs[name] = {"label": req.subgroup.strip(), "color": req.color.strip() or "#7aa2d6"}
    else:
        subs.pop(name, None)
    if req.gender.strip():
        meta.setdefault("gender", {})[name] = req.gender.strip()
    if req.owner.strip():
        meta.setdefault("owner", {})[name] = req.owner.strip()
    write_json(LIB, lib)
    return {"ok": True, "name": name, "tokens": toks, "subgroups": subs}


@router.post("/api/token/delete")
def api_token_delete(req: TokenReq):
    lib = read_json(LIB, {"tokens": {}}) or {}
    toks = lib.get("tokens", {})
    toks.pop(req.name, None)
    write_json(LIB, lib)
    return {"ok": True, "tokens": toks}


@router.post("/api/garment/delete")
def api_garment_delete(req: GarmentReq):
    ch = read_json(CHAR, {}) or {}
    gs = ch.get("garments", {})
    if req.key not in gs:
        raise HTTPException(404, "没有这套服装")
    if len(gs) <= 1:
        raise HTTPException(400, "至少保留一套服装")
    gs.pop(req.key)
    write_json(CHAR, ch)
    return {"ok": True, "garments": gs}


@router.post("/api/garment/save")
def api_garment_save(req: GarmentReq):
    ch = read_json(CHAR, {}) or {}
    g = ch.setdefault("garments", {}).setdefault(req.key, {})
    g["prompt"] = req.prompt
    g["negative"] = req.negative
    if req.label:
        g["label"] = req.label
    if req.use_for:
        g["use_for"] = req.use_for
    if req.hands_left:
        g["hands_left"] = req.hands_left
    if req.hands_right:
        g["hands_right"] = req.hands_right
    if req.drape:
        g["drape"] = {"state": req.drape, "terms": []}
    if req.note is not None:
        g["note"] = req.note
    if req.gender:
        g["gender"] = req.gender
    write_json(CHAR, ch)
    return {"ok": True, "garments": ch.get("garments", {})}


@router.get("/api/templates")
def api_templates():
    return {"items": store.load_templates()}


@router.post("/api/template/save")
def api_template_save(req: TplSaveReq):
    items = store.load_templates()
    entry = {"name": req.name.strip(), "params": req.params or {},
             "positive": req.positive or [], "negative": req.negative or []}
    items = [it for it in items if it.get("name") != entry["name"]]
    items.append(entry)
    store.save_templates(items)
    return {"ok": True, "items": items}


@router.get("/api/presets")
def api_presets():
    return {"items": read_json(PRESETS, []) or []}


@router.post("/api/presets/save")
def api_presets_save(req: PresetReq):
    items = read_json(PRESETS, []) or []
    items = [x for x in items if x.get("name") != req.name]
    items.append(req.dict())
    write_json(PRESETS, items)
    return {"ok": True, "items": items}


@router.post("/api/lib/classify")
def api_lib_classify(apply: bool = Query(True)):
    """给积木补分类（meta.subgroups）；新加积木后跑一次即可归位。"""
    args = [PY, os.path.join(ROOT, "tools", "classify_blocks.py")]
    if apply:
        args.append("--apply")
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    return {"ok": r.returncode == 0, "output": (r.stdout or "")[-2000:]}


@router.get("/api/garment_preview")
def api_garment_preview(key: str = ""):
    if not key:
        raise HTTPException(400, "缺少 key")
    st_path = os.path.join(REF, "garment_standee.json")
    if os.path.isfile(st_path):
        try:
            st = json.load(open(st_path, encoding="utf-8"))
            sp = st.get(key, "")
            if sp and os.path.isfile(sp):
                return FileResponse(sp, headers={"Cache-Control": "no-store, max-age=0"})
        except Exception as e:
            warn("garment_standee_read", e, st_path)
    p = os.path.join(ROOT, "SD-Picture", "garment_previews", key + ".png")
    if not os.path.isfile(p):
        prev_path = os.path.join(REF, "garment_previews.json")
        if os.path.isfile(prev_path):
            try:
                idx = json.load(open(prev_path, encoding="utf-8"))
                p = idx.get(key, "")
            except Exception as e:
                warn("garment_previews_read", e, prev_path)
                p = ""
        else:
            p = ""
    if not p or not os.path.isfile(p):
        raise HTTPException(404, "还没有展示图")
    return FileResponse(p, headers={"Cache-Control": "no-store, max-age=0"})
