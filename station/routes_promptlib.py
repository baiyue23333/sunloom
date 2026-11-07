# -*- coding: utf-8 -*-
"""promptlib 路由：/api/promptlib/*（从 server.py 拆出）。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict

import promptlib

router = APIRouter()


class PromptLibReq(BaseModel):
    fields: Dict[str, Any] = {}


@router.get("/api/promptlib/options")
def api_promptlib_options():
    try:
        return promptlib.options()
    except Exception as e:
        raise HTTPException(500, "提词器加载失败：" + str(e))


@router.post("/api/promptlib/build")
def api_promptlib_build(req: PromptLibReq):
    try:
        return promptlib.build(req.fields or {})
    except Exception as e:
        raise HTTPException(400, "提词器生成失败：" + str(e))
