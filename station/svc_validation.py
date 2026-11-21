# -*- coding: utf-8 -*-
"""底模、LoRA 与生成参数准入，供所有出图入口复用。"""
import math
import os

from fastapi import HTTPException
from pydantic import ValidationError

from job_models import ImageParams
from svc_paths import output_dir


def validate_model(model=""):
    from svc_state import list_models
    name = str(model or "").strip()
    if name and (name not in set(list_models()) or not os.path.basename(name.replace("\\", "/")).lower().startswith("anima")):
        raise HTTPException(400, "未知或不兼容的 Anima 底模: " + name)
    return name


def validate_loras(loras):
    from svc_state import _lora_base_map, list_loras
    if len(loras or []) > 32:
        raise HTTPException(400, "LoRA 数量不能超过 32")
    active = []
    for item in loras or []:
        try:
            name = str(item["name"]).strip()
            weight = float(item.get("weight", 1.0))
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, "LoRA 参数无效")
        if not name or not math.isfinite(weight) or not -2 <= weight <= 2:
            raise HTTPException(400, "LoRA 名称或权重无效")
        if weight != 0:
            active.append({"name": name, "weight": weight})
    if not active:
        return []
    key = lambda name: name.replace("/", "\\").casefold()
    known = {key(n): n for n in list_loras()}
    meta = {key(n): v for n, v in _lora_base_map().items()}
    for item in active:
        name = item["name"]
        k = key(name)
        if k not in known or meta.get(k, {}).get("base") != "anima":
            raise HTTPException(400, "未知或不兼容的 Anima LoRA: " + name)
        item["name"] = known[k]
    return active


def validate_request(req):
    if hasattr(req, "model"):
        req.model = validate_model(req.model)
    req.loras = validate_loras(req.loras)
    return req


def validate_params(params):
    try:
        values = ImageParams(**{k: v for k, v in params.items() if k in ImageParams.__fields__})
    except ValidationError as exc:
        raise HTTPException(400, "生成参数无效: " + str(exc))
    result = dict(params)
    result.update(width=values.width, height=values.height, steps=values.steps, cfg=values.cfg,
                  prefix=values.prefix, model=validate_model(values.model), loras=validate_loras(values.loras))
    denoise = float(result.get("denoise", 1.0))
    if not math.isfinite(denoise) or not 0 <= denoise <= 1:
        raise HTTPException(400, "denoise 必须在 0 到 1 之间")
    output_dir(result.get("save_to", "station_out"), create=False)
    return result


def validate_coop(req):
    req.model = validate_model(req.model)
    req.extra_loras = validate_loras(req.extra_loras)
    for field, weight_key in (("scene_lora", "env_weight"), ("char_lora", "char_weight")):
        weight = float(getattr(req, weight_key))
        if not math.isfinite(weight) or not 0 <= weight <= 2:
            raise HTTPException(400, "合作 LoRA 权重必须在 0 到 2 之间")
        name = getattr(req, field)
        checked = validate_loras([{"name": name, "weight": weight}]) if name else []
        if checked:
            setattr(req, field, checked[0]["name"])
    for name in ("cfg", "ratio", "x", "ground_y"):
        if not math.isfinite(getattr(req, name)):
            raise HTTPException(400, name + " 必须为有限数值")
    if not 0 <= req.cfg <= 30 or not 0 <= req.ratio <= 1 or not 0 <= req.x <= 1 or not 0 <= req.ground_y <= 1:
        raise HTTPException(400, "合作构图或 CFG 超出范围")
    for name in ("width", "height"):
        value = getattr(req, name)
        if value and (value < 64 or value > 4096 or value % 8):
            raise HTTPException(400, "合作尺寸必须为 64-4096 范围内的 8 倍数")
    if not all(1 <= getattr(req, name) <= 100 for name in ("steps", "env_steps", "char_steps")):
        raise HTTPException(400, "合作步数必须在 1 到 100 之间")
