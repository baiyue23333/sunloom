# -*- coding: utf-8 -*-
"""cards 路由：/api/cards 与 /api/card/*（从 server.py 拆出）。"""
import json
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Any, Dict, List

import store

router = APIRouter()


class CardReq(BaseModel):
    name: str
    loras: List[Dict[str, Any]] = []
    tokens: List[str] = []
    note: str = ""


class CardImportReq(BaseModel):
    data: str = ""
    path: str = ""


@router.get("/api/cards")
def api_cards():
    return {"items": store.load_cards()}


@router.post("/api/card/save")
def api_card_save(req: CardReq):
    items = store.load_cards()
    entry = {"name": req.name.strip(), "loras": req.loras or [],
             "tokens": req.tokens or [], "note": req.note or ""}
    items = [it for it in items if it.get("name") != entry["name"]]
    items.append(entry)
    store.save_cards(items)
    return {"ok": True, "items": items}


@router.post("/api/card/delete")
def api_card_delete(req: CardReq):
    items = store.load_cards()
    items = [it for it in items if it.get("name") != req.name]
    store.save_cards(items)
    return {"ok": True, "items": items}


@router.get("/api/cards/export")
def api_cards_export():
    return JSONResponse(store.load_cards())


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
    names = {it.get("name") for it in items}
    added = 0
    for c in incoming:
        if isinstance(c, dict) and c.get("name") and c["name"] not in names:
            items.append(c)
            added += 1
    store.save_cards(items)
    return {"ok": True, "added": added, "items": items}
