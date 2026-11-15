# -*- coding: utf-8 -*-
"""合作流水线、提示词展开/校验/修正、灯光引导与立绘模板路由。"""
import json
import os
import random as _rnd
import re
import threading
import time
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import ir as irv
from svc_coop import (
    cleanup_coop_dir as _cleanup_coop_dir,
    coop_dir_allowed,
    coop_worker as _coop_worker,
    list_coop_history,
    read_coop_manifest,
    resolve_coop_final as _resolve_coop_final,
)
from svc_jobs import Block, ExpandReq
from svc_state import COOP_DIR, COOP_STATE, MEM_LAST_JOB, OUT_DIR, ROOT, expand_blocks, img_allowed

router = APIRouter()


class ValidateReq(BaseModel):
    positive: List[Block] = []
    negative: List[Block] = []
    view: str = ""


class CoopReq(BaseModel):
    scene: str = "station"
    prompt_scene: str = ""
    prompt_char: str = ""
    scene_lora: str = ""
    char_lora: str = ""
    ratio: float = 0.34
    ground_y: float = 0.88
    x: float = 0.34
    light: str = "left"
    seed: int = 515501
    mode: str = "classic"
    bg_painter: str = "anima"
    char_painter: str = "anima"
    env_weight: float = 0.70
    char_weight: float = 0.85
    ll_strength: float = 1.0
    ll_end: float = 0.55
    fg: str = ""
    prop: str = ""
    footwear: str = ""
    scale_bias: float = 1.12
    char_size: str = "1024x1536"
    shot: str = "auto"
    priority: str = "auto"
    detail: str = "rich"
    sketch: str = ""
    auto_compose: bool = False
    neg_scene: str = ""
    neg_char: str = ""
    face_prompt: str = ""
    hand_prompt: str = ""
    width: int = 0
    height: int = 0
    steps: int = 28
    cfg: float = 5.5
    extra_loras: List[Dict[str, Any]] = []
    keep_intermediates: bool = False
    expand_notes: List[str] = []
    client_meta: Dict[str, Any] = {}
    style_suffix: Optional[str] = None
    face_suffix: Optional[str] = None
    hand_suffix: Optional[str] = None


class ComposeHintReq(BaseModel):
    prompt: str = ""
    seed: int = 0


class FixBlocksReq(BaseModel):
    blocks: List[Dict[str, Any]] = []
    negatives: List[Dict[str, Any]] = []


class LightGuideReq(BaseModel):
    blocks: List[Dict[str, Any]] = []
    negatives: List[Dict[str, Any]] = []
    mode: str = "free"


class StandeeReq(BaseModel):
    path: str
    fade: float = 0.75
    crop: float = 0.50
    size: int = 1792
    bg: str = "white"
    transparent: bool = False
    matte: str = "auto"
    sharpen: float = 0.0


def _heuristic_compose(prompt="", seed=0):
    p = (prompt or "").lower()
    ratio, gy, x = 0.34, 0.88, 0.34
    if re.search(r"close ?up|portrait|upper body|bust|face", p):
        ratio = 0.42
    elif re.search(r"wide|landscape|distant|scenery|sky|beach|field|forest|mountain|horizon", p):
        ratio = 0.20
    if re.search(r"indoor|interior|room|cafe|office|corridor|station|classroom", p):
        gy = 0.80
    if re.search(r"center|centred|symmetr|centered", p):
        x = 0.5
    rnd = _rnd.Random(int(seed or 0))
    return {"ratio": round(min(0.58, max(0.12, ratio + rnd.uniform(-0.02, 0.02))), 3),
            "ground_y": round(min(0.94, max(0.48, gy + rnd.uniform(-0.02, 0.02))), 3),
            "x": round(min(0.86, max(0.16, x + rnd.uniform(-0.03, 0.03))), 3),
            "by": "heuristic"}


def _compose_hint(prompt="", seed=0):
    h = _heuristic_compose(prompt, seed)
    p = (prompt or "").lower()
    if re.search(r"wide|landscape|distant|scenery|sky|beach|field|forest|mountain|horizon", p):
        h["ratio"] = min(h["ratio"], 0.30)
    if re.search(r"close ?up|portrait|upper body|bust", p):
        h["ratio"] = max(h["ratio"], 0.32)
    if re.search(r"station|street|room|corridor|cafe|interior|indoor", p):
        h["ratio"] = min(h["ratio"], 0.32)
    h["ratio"] = round(min(0.48, max(0.20, h["ratio"])), 3)
    h["ground_y"] = round(min(0.92, max(0.5, h["ground_y"])), 3)
    h["x"] = round(min(0.85, max(0.15, h["x"])), 3)
    return h


@router.post("/api/expand")
def api_expand(req: ExpandReq):
    return expand_blocks(req.positive, req.negative)


@router.post("/api/validate")
def api_validate(req: ValidateReq):
    return irv.validate([b.dict() for b in req.positive], [b.dict() for b in req.negative], view=req.view or "")


@router.post("/api/guide/light")
def api_guide_light(req: LightGuideReq):
    """分类光引导：纯规则，不加载模型。"""
    import light_guide
    return light_guide.analyze(req.blocks, req.negatives, req.mode or "free")


@router.post("/api/fix/blocks")
def api_fix_blocks(req: FixBlocksReq):
    """一键修正：纯规则审校，不加载任何模型。"""
    import prompt_fix
    return prompt_fix.audit(req.blocks, req.negatives)


@router.post("/api/compose_hint")
def api_compose_hint(req: ComposeHintReq):
    return _compose_hint(req.prompt, req.seed)


@router.post("/api/standee")
def api_standee(req: StandeeReq):
    """立绘模板：一张全身立绘 → 左边全身 + 右边放大淡化的半身。"""
    if not req.path or not os.path.isfile(req.path):
        raise HTTPException(404, "找不到这张图")
    import standee_template
    bg = "none" if req.transparent else (req.bg or "white")
    warn = ""
    if bg not in ("none", "transparent", "white", "black", "cream", "paper") and not bg.startswith("#"):
        if not os.path.isfile(bg):
            warn = "背景图不存在，已回退纯白"
            bg = "white"
        elif not img_allowed(bg):
            raise HTTPException(400, "背景图必须在 SD-Picture / 画师参考 / ComfyUI 输入输出目录内")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(OUT_DIR, "standee_%s_%d.png" % (stamp, int(time.time() * 1000) % 1000))
    try:
        standee_template.build(
            req.path, out, fade=float(req.fade), crop=float(req.crop),
            size=int(req.size) or 1792, bg=bg,
            matte=req.matte if req.matte in ("auto", "comfy", "color", "chroma") else "auto",
            sharpen=float(req.sharpen or 0.0),
        )
    except Exception as e:
        raise HTTPException(500, "立绘模板失败: %s" % e)
    res = {"ok": True, "path": out, "bg": bg,
           "transparent": bg in ("none", "transparent"),
           "preview": "/api/img?path=" + urllib.parse.quote(out)}
    if warn:
        res["warning"] = warn
    return res


@router.post("/api/coop")
def api_coop(req: CoopReq):
    if COOP_STATE.get("status") == "running":
        return {"ok": False, "note": "合作模式正在运行"}
    tool_map = {
        "reproject": "coop_reproject.py", "sketch": "coop_sketch.py", "gen": "coop_gen.py",
        "b2": "coop_b.py", "regional": "coop_regional.py", "paper": "coop_paper.py", "classic": "coop_render.py",
    }
    if req.mode not in tool_map:
        raise HTTPException(400, "不支持的合作模式: %s" % req.mode)
    MEM_LAST_JOB[0] = time.time()
    COOP_STATE["id"] = uuid.uuid4().hex[:10]
    COOP_STATE["tool"] = os.path.join(ROOT, "tools", tool_map[req.mode])
    COOP_STATE["mode"] = req.mode
    COOP_STATE["keep_intermediates"] = bool(req.keep_intermediates)
    COOP_STATE.update(status="starting", dir="", image="", log="", phase="准备", progress=0.0)
    hint = None
    if req.auto_compose:
        hint = _compose_hint(req.prompt_scene or req.prompt_char or req.scene, req.seed)
        if req.mode != "reproject" or not req.ratio or req.ratio <= 0:
            req.ratio = hint["ratio"]
    args = ["--ratio", str(req.ratio), "--ground-y", str(req.ground_y),
            "--x", str(req.x), "--seed", str(req.seed), "--light", req.light]
    if req.mode == "reproject":
        reproj_out = os.path.join(COOP_DIR, f"reproj_{time.strftime('%Y%m%d_%H%M%S')}_{req.seed}")
        os.makedirs(reproj_out, exist_ok=True)
        COOP_STATE["dir"] = reproj_out
        cfg_path = os.path.join(reproj_out, "reproj_cfg.json")
        cfg_payload = {
            "scene": req.prompt_scene or req.scene, "char": req.prompt_char or "",
            "neg_scene": req.neg_scene or "", "neg_char": req.neg_char or "",
            "face_prompt": req.face_prompt or "", "hand_prompt": req.hand_prompt or "",
            "width": req.width or 1216, "height": req.height or 832,
            "steps": req.steps or 28, "cfg": req.cfg or 5.5, "seed": req.seed,
            "scene_lora": req.scene_lora or "", "env_weight": req.env_weight,
            "char_lora": req.char_lora or "", "char_weight": req.char_weight,
            "extra_loras": req.extra_loras or [], "ratio": req.ratio,
            "ground_y": req.ground_y, "x": req.x,
            "keep_intermediates": bool(req.keep_intermediates),
            "expand_notes": req.expand_notes or [],
            "client_meta": req.client_meta or {},
            "style_suffix": req.style_suffix, "face_suffix": req.face_suffix, "hand_suffix": req.hand_suffix,
        }
        with open(cfg_path, "w", encoding="utf-8") as cf_f:
            json.dump(cfg_payload, cf_f, ensure_ascii=False, indent=2)
        args += ["--config", cfg_path, "--out", reproj_out]
        if req.keep_intermediates:
            args.append("--keep-intermediates")
    elif req.mode == "paper":
        args += ["--scene", req.prompt_scene or req.scene,
                 "--char", req.prompt_char or "1girl, solo, adult woman, white coat, standing",
                 "--artist", req.char_lora, "--artist-w", str(req.char_weight),
                 "--fg", req.fg, "--prop", req.prop,
                 "--scale-bias", str(req.scale_bias), "--char-size", req.char_size,
                 "--shot", req.shot, "--priority", req.priority, "--detail", req.detail,
                 "--ratio", str(req.ratio), "--ground-y", str(req.ground_y),
                 "--x", str(req.x), "--seed", str(req.seed), "--light", req.light]
        if req.footwear.strip():
            args += ["--footwear", req.footwear]
    elif req.mode == "regional":
        args += ["--scene", req.prompt_scene or req.scene,
                 "--char", req.prompt_char or "1girl, solo, adult woman, white dress",
                 "--env-lora", req.scene_lora, "--env-w", str(req.env_weight),
                 "--char-lora", req.char_lora, "--char-w", str(req.char_weight),
                 "--ll-strength", str(req.ll_strength), "--ll-end", str(req.ll_end)]
    elif req.mode == "b2":
        args += ["--prompt-scene", req.prompt_scene or req.scene,
                 "--scene-lora", req.scene_lora,
                 "--bg-painter", req.bg_painter, "--char-painter", req.char_painter]
        if req.prompt_char:
            args += ["--char-prompt", req.prompt_char]
        if req.sketch:
            args += ["--sketch", req.sketch]
    else:
        args += ["--prompt-scene", req.prompt_scene or req.scene,
                 "--scene-lora", req.scene_lora, "--char-lora", req.char_lora]
        if req.prompt_char:
            args += ["--prompt-char", req.prompt_char]
        if req.sketch:
            args += ["--sketch", req.sketch]
    threading.Thread(target=_coop_worker, args=(args,), daemon=True).start()
    return {"ok": True, "status": "running", "id": COOP_STATE["id"], "dir": COOP_STATE.get("dir", ""),
            "hint": hint, "ratio": req.ratio, "ground_y": req.ground_y, "x": req.x}


@router.get("/api/coop/status")
def api_coop_status():
    d = COOP_STATE.get("dir") or ""
    img = COOP_STATE.get("image") or ""
    if not img and d:
        img = os.path.join(d, "comp.png")
    el, prog = 0.0, COOP_STATE.get("progress", 0.0)
    if COOP_STATE.get("status") == "running":
        el = round(time.time() - COOP_STATE.get("started", time.time()), 1)
        base, target, eta = {"准备": (0.02, 0.15, 20), "背景": (0.15, 0.55, 150),
                             "人物": (0.55, 0.85, 90), "合成": (0.85, 0.99, 45)}.get(
            COOP_STATE.get("phase", ""), (0.02, 0.99, 300))
        frac = min(1.0, (time.time() - COOP_STATE.get("phase_at", time.time())) / eta)
        prog = round(base + (target - base) * frac, 3)
    return {"status": COOP_STATE.get("status"), "dir": d, "log": COOP_STATE.get("log", ""),
            "phase": COOP_STATE.get("phase", ""), "progress": prog, "elapsed": el,
            "image": img if img and os.path.isfile(img) else ""}


@router.get("/api/coop/list")
def api_coop_list(limit: int = 16):
    return {"items": list_coop_history(limit)}


@router.get("/api/coop/manifest")
def api_coop_manifest(dir: str = "", path: str = ""):
    target = dir.strip()
    if not target and path.strip():
        target = os.path.dirname(path.strip())
    if not target or not os.path.isdir(target) or not coop_dir_allowed(target):
        raise HTTPException(404, "找不到重映记录目录")
    return read_coop_manifest(target)
