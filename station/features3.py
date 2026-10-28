# -*- coding: utf-8 -*-
"""features3.py - compatibility endpoints for the ported private UI."""
import json
import os
from typing import Any, List, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import comfy as cf
import server as S

router = APIRouter()


@router.get("/api/templates")
def api_templates():
    items = S.read_json(os.path.join(S.DATA, "templates.json"), []) or []
    return {"items": items}


@router.get("/api/features")
def api_features():
    return {"groups": S._FEATURE_LIST}


@router.get("/api/registry")
def api_registry():
    return {"total": 0, "items": []}


class LogReq(BaseModel):
    path: str = ""
    rating: str = ""
    note: str = ""


@router.post("/api/log")
def api_log(req: LogReq):
    return {"ok": True}


@router.get("/api/presets")
def api_presets():
    return {"items": []}


@router.get("/api/last-graph")
def api_last_graph():
    return {"ok": False, "graph": None}


@router.get("/api/reliability")
def api_reliability():
    return {"items": {}, "marked": 0}


@router.get("/api/regress")
def api_regress():
    return {"ok": True, "checks": []}


@router.get("/api/qc")
def api_qc(path: str = ""):
    if not path or not os.path.isfile(path):
        raise HTTPException(404, "not found")
    try:
        from PIL import Image
        im = Image.open(path).convert("L")
        px = list(im.resize((64, 64)).getdata())
        avg = sum(px) / len(px)
        over = sum(1 for v in px if v > 250) / len(px)
        under = sum(1 for v in px if v < 5) / len(px)
        return {"avg": round(avg, 1), "over": round(over * 100, 2),
                "under": round(under * 100, 2), "ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/recipe/from-image")
def api_recipe_from_image():
    raise HTTPException(501, "从图推断配方需要额外能力，当前版本仅支持 PNG 元数据回填")


@router.post("/api/recipe/infer")
def api_recipe_infer():
    raise HTTPException(501, "配方推断未实现；可用「回填历史」从 PNG 元数据恢复")


@router.get("/api/train/profiles")
def api_train_profiles():
    return {"items": [{"id": "local", "label": "本机", "note": "需要 config.json 里的 kohya_dir"}]}


@router.post("/api/detect-hand-auto")
def api_detect_hand_auto():
    raise HTTPException(501, "自动手部检测需要 SDPose 自定义节点（见 tools/setup/README.md）；当前可改用框选式手部精修")


@router.post("/api/comfy/restart")
def api_comfy_restart():
    r = cf.free()
    return {"ok": True, "free": r,
            "note": "已释放显存；请手动重启 ComfyUI，或在引擎页点「启动」"}

@router.get("/api/env/requirements")
def api_env_requirements():
    import importlib.util
    checks = []
    def add(cid, label, ok, detail, script=""):
        checks.append({"id": cid, "label": label, "ok": bool(ok), "detail": detail,
                       "script": script, "optional": True})
    have = lambda m: importlib.util.find_spec(m) is not None
    add("onnxruntime", "打标依赖 onnxruntime", have("onnxruntime"),
        "pip install onnxruntime", "tools/setup/download_wd14.ps1")
    cfg = __import__("config").load()
    tagger = (cfg.get("tagger") or {}).get("model_dir", "")
    add("wd14", "WD14 模型", bool(tagger) and os.path.isdir(tagger),
        tagger or "未配置", "tools/setup/download_wd14.ps1")
    kohya = cfg.get("kohya_dir") or ""
    add("kohya", "kohya sd-scripts",
        bool(kohya) and os.path.isfile(os.path.join(kohya, "train_network.py")),
        kohya or "未配置", "tools/setup/install_kohya.ps1")
    st = cf.system_stats()
    add("comfy", "ComfyUI 在线", st.get("up"), st.get("version") or "offline",
        "tools/setup/install_comfyui.ps1")
    return {"checks": checks}

class TplSaveReq(BaseModel):
    name: str
    params: dict = {}
    positive: List[Any] = []
    negative: List[Any] = []


@router.post("/api/template/save")
def api_template_save(req: TplSaveReq):
    path = os.path.join(S.DATA, "templates.json")
    items = S.read_json(path, []) or []
    entry = {"name": req.name.strip(), "params": req.params or {},
             "positive": req.positive or [], "negative": req.negative or []}
    items = [it for it in items if it.get("name") != entry["name"]]
    items.append(entry)
    S.write_json(path, items)
    return {"ok": True, "items": items}
