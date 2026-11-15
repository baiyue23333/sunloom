# -*- coding: utf-8 -*-
"""环境画师的第二次调用：生成前景卡（挡在角色前面的近景元素）。

分工：草稿(legacy_xl) → 环境(env_artist ×2：背景板 + 前景卡) → 人物(artist_style)。
前景抠图固定走 BiRefNet：2.1 一次要 5 分钟，前景不值得。
"""
import os


def build(run, plan, out, env_artist, seed, light, scene_w, neg, cut):
    """按调度给的前景清单生成卡片，返回可直接塞进 layers 的字典列表。"""
    from PIL import Image
    layers = []
    for i, f in enumerate((plan.get("foreground") or [])[:2]):
        f["scale"] = max(0.15, min(0.45, float(f.get("scale", 0.3))))
        try:
            raw = os.path.join(out, "fg_raw_%d.png" % i)
            img = run({"prompt": f["prompt"] + ", (close-up foreground element:1.2), "
                                        "(detailed:1.05), (cinematic lighting:1.05)",
                       "negative": "person, 1girl, 1boy, character, face, " + neg,
                       "width": 1024, "height": 1024, "steps": 28, "cfg": 5.4,
                       "seed": seed + 31 + i, "prefix": "PAPER_FG", "mode": "t2i",
                       "save_to": "paper",
                       "loras": [{"name": env_artist, "weight": scene_w["fg"]}]}, "fg%d" % i)
            Image.open(img).convert("RGB").save(raw)
            card = cut(raw, os.path.join(out, "fg_%d.png" % i), "fg%d" % i, backend="biref")
            layers.append({"card": card, "ratio": f["scale"], "ground_y": 1.02,
                           "x": f["x"], "light": light, "shadow": 0, "refl": 0.0,
                           "ambient": 0.9, "grade": 0.25, "anchor": "bottom"})
            print("[fg] %s (x=%.2f scale=%.2f)" % (f["prompt"][:40], f["x"], f["scale"]), flush=True)
        except Exception as e:  # noqa: BLE001
            print("[fg] 失败: %s" % str(e)[:120], flush=True)
    return layers
