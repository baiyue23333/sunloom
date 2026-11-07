# -*- coding: utf-8 -*-
"""promptlib.py - 把 ComfyUI 提词器节点（NSFWPromptSelector）接进工作站。

节点源码默认在 A:\\workflow\\ComfyUI-NSFW-PromptSelector，可用环境变量
PROMPT_SELECTOR_DIR 覆盖。该节点只依赖标准库，可直接 import，不需要 ComfyUI。
"""
import importlib
import os
import sys
import threading

SEL_DIR = os.environ.get("PROMPT_SELECTOR_DIR") or r"A:\workflow\ComfyUI-NSFW-PromptSelector"

_LOCK = threading.Lock()
_CLS = None

# 前端展示顺序：字段名 -> 类属性名
FIELDS = [
    ("触发词", "触发词选项", "multi"),
    ("场景类型", "场景类型选项", "one"),
    ("动作姿态", "动作姿态选项", "one"),
    ("服饰", "服饰选项", "one"),
    ("情绪氛围", "情绪氛围选项", "one"),
    ("运镜方式", "运镜方式选项", "one"),
    ("机位角度", "机位角度选项", "one"),
    ("光源类型", "光源类型选项", "one"),
    ("光线类型", "光线类型选项", "one"),
    ("镜头类型", "镜头类型选项", "one"),
    ("焦距", "焦距选项", "one"),
    ("色调", "色调选项", "one"),
    ("视觉风格", "视觉风格选项", "one"),
    ("特效镜头", "特效镜头选项", "one"),
    ("镜头滤镜", "镜头滤镜选项", "one"),
]

EXTRA_FIELDS = [
    ("质量等级", "质量等级选项"),
    ("负面提示词类型", "负面提示词预设选项"),
    ("随机选择", "随机选择选项"),
    ("预设配置", "预设选项"),
]

DEFAULTS = {
    "触发词": ["——"],
    "场景类型": "——",
    "动作姿态": "——",
    "服饰": "——",
    "情绪氛围": "——",
    "运镜方式": "——",
    "机位角度": "——",
    "光源类型": "——",
    "光线类型": "——",
    "镜头类型": "——",
    "焦距": "——",
    "色调": "——",
    "视觉风格": "——",
    "特效镜头": "——",
    "镜头滤镜": "——",
    "随机选择": "关闭",
    "预设配置": "——",
    "质量等级": "高质量",
    "权重_场景": 1.0,
    "权重_动作": 1.5,
    "权重_服饰": 0.8,
    "权重_情绪": 1.2,
    "自定义前缀": "",
    "自定义后缀": "",
    "负面提示词类型": "标准负面提示词",
    "自定义负面提示词": "",
}


def _cls():
    global _CLS
    with _LOCK:
        if _CLS is not None:
            return _CLS
        path = os.path.join(SEL_DIR, "prompt_selector.py")
        if not os.path.isfile(path):
            raise FileNotFoundError("找不到提词器节点: " + path)
        if SEL_DIR not in sys.path:
            sys.path.insert(0, SEL_DIR)
        mod = importlib.import_module("prompt_selector")
        _CLS = mod.NSFWPromptSelector
        return _CLS


def options():
    """返回全部可选项，给前端下拉框用。"""
    cls = _cls()
    out = {"fields": [], "weights": [], "source": SEL_DIR}
    for name, attr, kind in FIELDS:
        out["fields"].append({"name": name, "kind": kind, "items": list(getattr(cls, attr))})
    for name, attr in EXTRA_FIELDS:
        out["fields"].append({"name": name, "kind": "one", "items": list(getattr(cls, attr))})
    out["weights"] = ["权重_场景", "权重_动作", "权重_服饰", "权重_情绪"]
    out["texts"] = ["自定义前缀", "自定义后缀", "自定义负面提示词"]
    return out


def build(sel):
    """按选择生成 正面 / 负面 / 完整 三段提示词。"""
    cls = _cls()
    kwargs = {}
    for name, default in DEFAULTS.items():
        value = sel.get(name, default)
        if value is None or value == "":
            value = default
        if name in ("权重_场景", "权重_动作", "权重_服饰", "权重_情绪"):
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = default
        if name == "触发词":
            if isinstance(value, str):
                value = [value]
            value = [v for v in value if v] or list(default)
        kwargs[name] = value

    positive, negative, full = cls().generate_nsfw_prompt(**kwargs)
    positive = (positive or "").strip().rstrip(",").strip()
    negative = (negative or "").strip().rstrip(",").strip()
    return {
        "positive": positive,
        "negative": negative,
        "full": full,
        "pipelines": {"positive": positive, "negative": negative},
        "settings": {k: kwargs[k] for k in ("质量等级", "权重_场景", "权重_动作", "权重_服饰", "权重_情绪")},
    }
