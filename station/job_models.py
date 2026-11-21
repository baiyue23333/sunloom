# -*- coding: utf-8 -*-
"""出图入口共用参数约束；零权重与零 CFG 是有效数值。"""
import math
from typing import Any, Dict, List

from pydantic import BaseModel, Field, root_validator, validator
from svc_paths import output_dir, safe_prefix


class ImageParams(BaseModel):
    width: int = Field(1024, ge=64, le=4096, multiple_of=8)
    height: int = Field(1536, ge=64, le=4096, multiple_of=8)
    steps: int = Field(30, ge=1, le=100)
    cfg: float = Field(5.5, ge=0, le=30)
    seed: int = Field(0, ge=0, le=18446744073709551615)
    prefix: str = "station"
    loras: List[Dict[str, Any]] = []
    model: str = ""

    @validator("cfg")
    def finite_cfg(cls, value):
        if not math.isfinite(value):
            raise ValueError("CFG 必须为有限数值")
        return value

    @validator("prefix", pre=True, always=True)
    def prefix_name(cls, value):
        return safe_prefix(value)

    @root_validator(skip_on_failure=True)
    def pixel_budget(cls, values):
        if values["width"] * values["height"] > 8388608:
            raise ValueError("画布不能超过 8MP")
        return values


class RunReq(ImageParams):
    prompt: str
    negative: str = ""
    save_to: str = "station_out"
    mode: str = "t2i"
    blocks_pos: List[Dict[str, Any]] = []
    blocks_neg: List[Dict[str, Any]] = []
    reference: str = ""
    mask: str = ""
    denoise: float = Field(0.6, ge=0, le=1)
    expand_notes: List[str] = []
    client_meta: Dict[str, Any] = {}
    auto_handfix: bool = False
    parent_job_id: str = ""

    @validator("save_to")
    def output_name(cls, value):
        output_dir(value, create=False)
        return value


class MaskReq(ImageParams):
    image: str
    box: str
    prompt: str = ""
    negative: str = ""
    denoise: float = Field(0.45, ge=0, le=1)
    steps: int = Field(24, ge=1, le=100)
    cfg: float = Field(5.0, ge=0, le=30)
    prefix: str = "handfix"
    polygon: List[Any] = []
    precise: bool = True


class ReproReq(ImageParams):
    mode: str
    reference: str
    prompt: str = ""
    negative: str = ""
    denoise: float = Field(0.6, ge=0, le=1)
    prefix: str = "repro"


class InpaintReq(ImageParams):
    image: str
    box: str = ""
    mask_b64: str = ""
    mask_feather: int = Field(0, ge=0, le=128)
    prompt: str = ""
    negative: str = ""
    denoise: float = Field(0.6, ge=0, le=1)
    steps: int = Field(26, ge=1, le=100)
    cfg: float = Field(5.2, ge=0, le=30)
    prefix: str = "repaint"
    engine: str = "anima"


class BatchReq(ImageParams):
    blocks_pos: List[Dict[str, Any]] = []
    blocks_neg: List[Dict[str, Any]] = []
    prompt: str
    negative: str = ""
    count: int = Field(4, ge=1, le=12)
    seed_start: int = Field(0, ge=0, le=18446744073709551615)
    seed_step: int = Field(1, ge=1, le=1000000)
    prefix: str = "batch"
    mode: str = "t2i"
    reference: str = ""


class BatchQReq(BaseModel):
    count: int = Field(4, ge=1, le=24)
    refine: bool = True
    denoise: float = Field(0.3, ge=0, le=1)
    steps: int = Field(0, ge=0, le=100)
    cfg: float = Field(0.0, ge=0, le=30)
    model: str = ""
    templates: List[str] = []
    loras: List[Dict[str, Any]] = []


class AutoPipeReq(BaseModel):
    count: int = Field(4, ge=1, le=16)
    refine: bool = True
    denoise: float = Field(0.3, ge=0, le=1)
    glitch: float = Field(0.0, ge=0, le=2)
    keep: int = Field(2, ge=1, le=16)
    templates: List[str] = []
    loras: List[Dict[str, Any]] = []
