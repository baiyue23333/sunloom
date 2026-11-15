# -*- coding: utf-8 -*-
"""paper 模式的定稿 preset：把一组参数固化下来，确保每次复现同一张画面。

用法（在 argparse 建好之后、parse_args 之前）：
    import paper_preset
    paper_preset.apply(ap, preset_name, ROOT)
"""
import json
import os


def load(name, root):
    """读 ref/paper_presets.json 里的某一项；缺失返回空字典。"""
    path = os.path.join(root, "ref", "paper_presets.json")
    if not name or not os.path.isfile(path):
        return {}
    try:
        data = (json.load(open(path, encoding="utf-8")) or {}).get(name) or {}
    except Exception:
        return {}
    data.pop("note", None)
    rp = data.get("reuse_plate")
    if rp and not os.path.isabs(rp):
        data["reuse_plate"] = os.path.join(root, rp)
    return data


def apply(ap, name, root):
    """把 preset 里的字段设成 argparse 默认值；返回实际套用的字典。"""
    data = load(name, root)
    if data:
        ap.set_defaults(**data)
        print("[preset] 套用 %s" % name, flush=True)
    return data
