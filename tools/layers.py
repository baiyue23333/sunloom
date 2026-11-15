# -*- coding: utf-8 -*-
"""多层合层：读 scene.json，逐层调 card_stage.compose。"""
import json
import os
from PIL import Image, ImageFilter
import card_stage


def compose_layers(plate_path, scene_path, out_dir, supersample=1, sharpen_box=None):
    scene = json.load(open(scene_path, encoding="utf-8"))
    os.makedirs(out_dir, exist_ok=True)
    plate = Image.open(plate_path).convert("RGB")
    # 复用的背景板可能带白边（生成时被 letterbox 过）：先裁掉再合成
    try:
        import numpy as _np
        _a = _np.asarray(plate)
        _rows = _a.mean(axis=(1, 2))
        _ok = _np.nonzero(_rows <= 245)[0]
        if _ok.size and (_ok[0] > 2 or _ok[-1] < _a.shape[0] - 3):
            _y0, _y1 = int(_ok[0]), int(_ok[-1]) + 1
            plate = plate.crop((0, _y0, _a.shape[1], _y1)).resize((_a.shape[1], _a.shape[0]), Image.LANCZOS)
            print("[plate] 去白边 %d/%d" % (_y0, _a.shape[0] - _y1), flush=True)
    except Exception:
        pass
    W, H = plate.size
    S = max(1, int(supersample))
    comp = plate.resize((W * S, H * S), Image.LANCZOS) if S > 1 else plate
    for idx, layer in enumerate(scene.get("layers", [])):
        if layer.get("full"):
            card = Image.open(layer["card"]).convert("RGBA")
            if card.size != (W, H):
                card = card.resize((W, H), Image.LANCZOS)
            comp = Image.alpha_composite(comp.convert("RGBA"), card).convert("RGB")
            continue
        card_path = layer["card"]
        if layer.get("solid"):
            im = Image.open(card_path).convert("RGBA")
            al = im.split()[3].point(lambda v: 255 if v > 96 else 0).filter(ImageFilter.GaussianBlur(0.8))
            im.putalpha(al)
            solid_path = card_path.replace(".png", "_solid.png")
            im.save(solid_path)
            card_path = solid_path
        ratio = float(layer.get("ratio", 0.4))
        gy = float(layer.get("ground_y", 0.9))
        x = float(layer.get("x", 0.5))
        light = layer.get("light", "left")
        shadow = int(layer.get("shadow", 200))
        refl = float(layer.get("refl", 0.0))
        ambient = float(layer.get("ambient", 0.9))
        grade_w = float(layer.get("grade", 0.35))
        tmp = os.path.join(out_dir, "_layer_%02d.png" % idx)
        comp.convert("RGB").save(tmp)
        out = card_stage.compose(tmp, card_path, os.path.join(out_dir, "_c%02d" % idx), ratio, gy, x,
                      light, shadow, refl, grade_w, ambient, float(layer.get("poisson", 0)),
                      scene.get("stage"), bool(layer.get("slot")), float(layer.get("shadow_boost", 1.0)),
                      bool(scene.get("no_fusion", False)), str(layer.get("anchor", "feet")))
        comp = Image.open(out).convert("RGB")
    if S > 1:
        comp = comp.resize((W, H), Image.LANCZOS)
    if sharpen_box:
        try:
            x0, y0, x1, y1 = [int(v) for v in (sharpen_box[0] * W, sharpen_box[1] * H,
                                                sharpen_box[2] * W, sharpen_box[3] * H)]
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(W, x1), min(H, y1)
            if x1 - x0 > 8 and y1 - y0 > 8:
                crop = comp.crop((x0, y0, x1, y1)).filter(
                    ImageFilter.UnsharpMask(radius=1.0, percent=90, threshold=2))
                comp.paste(crop, (x0, y0))
        except Exception:
            pass
    final = os.path.join(out_dir, "comp.png")
    comp.save(final)
    print("done:", final, flush=True)
    return final
