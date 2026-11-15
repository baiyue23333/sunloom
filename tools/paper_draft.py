# -*- coding: utf-8 -*-
"""草稿画师（legacy_xl）：先出结构草图，交给环境画师做 i2i 底稿。

三位画师分工：
    草稿  —— legacy_xl，负责构图与光位（本模块）
    环境  —— env_artist，调用两次：背景板（吃草稿）+ 前景卡
    人物  —— artist_style，角色本体
"""
import os


def make(run, scene, seed, model, w, h, out_dir, prefix="PAPER_DRAFT"):
    """生成草图并存档；失败返回空串（调用方回退到直接出背景板）。"""
    from PIL import Image
    try:
        print("[draft] legacy_xl 结构草图…", flush=True)
        img = run({"prompt": scene + ", (wide establishing shot:1.2), (composition sketch:1.1), night scene",
                   "negative": "people, person, character, text, watermark",
                   "width": w, "height": h, "steps": 24, "cfg": 6.0, "seed": seed,
                   "prefix": prefix, "mode": "t2i", "save_to": "paper", "model": model}, "draft")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "draft.png")
        Image.open(img).convert("RGB").resize((w, h), Image.LANCZOS).save(path)
        print("[draft] 完成 %s" % path, flush=True)
        return path
    except Exception as e:  # noqa: BLE001
        print("[draft] 失败，直接出背景板: %s" % str(e)[:100], flush=True)
        return ""
