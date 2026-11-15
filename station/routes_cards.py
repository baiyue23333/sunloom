# -*- coding: utf-8 -*-
"""cards 路由：/api/cards 与 /api/card/*（从 server.py 拆出）。"""
import json
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

import store
from svc_obs import warn

router = APIRouter()

# 每张角色卡同时落一个独立文件：ref/cards/<角色名>.json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARD_DIR = os.path.join(ROOT, "ref", "cards")


def _card_file(name):
    safe = "".join(ch for ch in str(name or "").strip() if ch not in '\\/:*?"<>|').strip() or "card"
    return os.path.join(CARD_DIR, safe + ".json")


def _read_card_file(name):
    fp = _card_file(name)
    if not os.path.isfile(fp):
        return {}
    try:
        with open(fp, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        warn("card_read", e, fp)
        return {}


def _mirror(entry):
    """把一张卡写成独立文件（导出/导入/迁移都以这个文件为准）。"""
    fp = _card_file(entry.get("name"))
    try:
        os.makedirs(CARD_DIR, exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=1)
    except Exception as e:
        warn("card_mirror", e, fp)


class CardReq(BaseModel):
    name: str
    loras: List[Dict[str, Any]] = []
    tokens: List[str] = []
    # 专属正向/负向：工作台同款积木块 [{token, text, weight}, ...]
    # tokens 保留为"正向 token 列表"，给老逻辑和导入导出用
    pos_blocks: List[Dict[str, Any]] = []
    neg_blocks: List[Dict[str, Any]] = []
    note: str = ""
    # 人设：强身份走 tokens（@ID 一类积木），弱身份走 identity_weak 文本；
    # base 记录这张卡对应的底模，换底模时自动降级为弱身份
    persona: str = ""
    identity_weak: str = ""
    base: str = ""
    gender: str = "f"   # f / m
    views: Optional[Dict[str, Any]] = None


class CardImportReq(BaseModel):
    data: str = ""
    path: str = ""
    overwrite: bool = False


@router.get("/api/cards")
def api_cards():
    items = store.load_cards()
    # 视角块优先取 DB，缺失时从卡片文件补回
    for it in items:
        if it.get("views"):
            continue
        views = _read_card_file(it.get("name")).get("views") or {}
        if views:
            it["views"] = views
    return {"items": items}


@router.post("/api/card/save")
def api_card_save(req: CardReq):
    items = store.load_cards()
    name = req.name.strip()
    prev = next((it for it in items if it.get("name") == name), {})
    disk = _read_card_file(name)
    views = req.views if req.views is not None else (prev.get("views") or disk.get("views") or {})
    pos_blocks = req.pos_blocks or []
    tokens = req.tokens or [b.get("token") for b in pos_blocks if b.get("token")]
    entry = {"name": name, "loras": req.loras or [],
             "tokens": [t for t in tokens if t], "pos_blocks": pos_blocks,
             "neg_blocks": req.neg_blocks or [], "note": req.note or "",
             "persona": req.persona or "", "identity_weak": req.identity_weak or "",
             "base": req.base or "", "gender": req.gender or "f"}
    if views:
        entry["views"] = views
    items = [it for it in items if it.get("name") != entry["name"]]
    items.append(entry)
    store.save_cards(items)
    _mirror(entry)
    return {"ok": True, "items": items}


@router.post("/api/card/delete")
def api_card_delete(req: CardReq):
    items = store.load_cards()
    items = [it for it in items if it.get("name") != req.name]
    store.save_cards(items)
    try:
        p = _card_file(req.name)
        if os.path.isfile(p):
            os.remove(p)
    except Exception as e:
        warn("card_delete_file", e, req.name)
    return {"ok": True, "items": items}


@router.get("/api/cards/export")
def api_cards_export():
    return JSONResponse(store.load_cards())


@router.get("/api/card/export")
def api_card_export(name: str = ""):
    """导出单个角色：优先给独立文件，没有就现写一份。"""
    items = store.load_cards()
    entry = next((it for it in items if it.get("name") == name), None)
    if not entry:
        raise HTTPException(404, "没有这张角色卡")
    p = _card_file(name)
    if not os.path.isfile(p):
        _mirror(entry)
    return FileResponse(p, filename=os.path.basename(p), media_type="application/json")


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
    items = store.load_cards()
    by_name = {it.get("name"): i for i, it in enumerate(items) if it.get("name")}
    added, updated, skipped_names = 0, 0, []
    for c in incoming:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        cname = c["name"]
        if cname not in by_name:
            by_name[cname] = len(items)
            items.append(c)
            _mirror(c)
            added += 1
        elif req.overwrite:
            items[by_name[cname]] = c
            _mirror(c)
            updated += 1
        else:
            skipped_names.append(cname)
    store.save_cards(items)
    return {"ok": True, "added": added, "updated": updated,
            "skipped": len(skipped_names), "skipped_names": skipped_names, "items": items}
