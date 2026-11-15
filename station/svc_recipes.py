# -*- coding: utf-8 -*-
"""配方存储/反推/PNG 解析、底图与蒙版预处理、对称质检。"""
import json
import os
import re
import shutil
import time

from fastapi import HTTPException

import store
from svc_obs import warn
from svc_state import comfy_in, load_tokens


def _prepare_reference(path):
    """把底图拷进 ComfyUI/input，返回文件名。"""
    inp = comfy_in()
    src = path
    if not os.path.isabs(src):
        cand = os.path.join(inp, src)
        src = cand if os.path.exists(cand) else src
    if not os.path.isfile(src):
        raise HTTPException(400, "找不到底图: " + path)
    os.makedirs(inp, exist_ok=True)
    base = "ref_" + re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(src))
    dst = os.path.join(inp, base)
    if not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
        shutil.copy2(src, dst)
    return base


def _normalize_mask(path, feather=0):
    """把蒙版统一成「白=重绘」的二值图（取红通道，兼容画笔红笔迹与矩形白块）。"""
    from PIL import Image, ImageFilter
    im = Image.open(path)
    if im.mode == "RGBA":
        bg = Image.new("RGBA", im.size, (0, 0, 0, 255))
        im = Image.alpha_composite(bg, im)
    m = im.convert("RGB").getchannel("R")
    m = m.point(lambda v: 255 if v >= 24 else 0)
    if feather and feather > 0:
        m = m.filter(ImageFilter.GaussianBlur(radius=feather / 2.0))
    Image.merge("RGB", (m, m, m)).save(path)
    return path


def _make_mask(image_path, box, out_name=None):
    """用矩形框生成黑底白块蒙版，写进 ComfyUI/input。"""
    from PIL import Image, ImageDraw
    im = Image.open(image_path)
    w, h = im.size
    parts = [int(float(x.strip())) for x in box.replace("，", ",").split(",")]
    if len(parts) != 4:
        raise HTTPException(400, "box 需要 x,y,w,h")
    x, y, bw, bh = parts
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.rectangle([max(0, x), max(0, y), min(w - 1, x + bw), min(h - 1, y + bh)], fill=255)
    inp = comfy_in()
    name = out_name or ("mask_" + time.strftime("%H%M%S") + ".png")
    mask.save(os.path.join(inp, name))
    return name


def _fit_mask_to_reference(ref_name, mask_name):
    """蒙版尺寸与底图不一致时，等比缩放到图尺寸。"""
    try:
        from PIL import Image
        base = comfy_in()
        rp = os.path.join(base, ref_name)
        mp = os.path.join(base, mask_name)
        if not (os.path.isfile(rp) and os.path.isfile(mp)):
            return mask_name
        ref = Image.open(rp)
        m = Image.open(mp)
        if m.size == ref.size:
            return mask_name
        if m.mode not in ("L", "RGB", "RGBA"):
            m = m.convert("L")
        m = m.resize(ref.size, Image.LANCZOS)
        out = "mask_fit_%s.png" % time.strftime("%H%M%S")
        m.save(os.path.join(base, out))
        print("[mask-fit] %s -> %s (%s)" % (mask_name, out, ref.size), flush=True)
        return out
    except Exception as e:
        print("[mask-fit] failed:", e, flush=True)
        return mask_name


def add_recipe(path, data):
    """增量写入一条配方并裁剪旧记录，避免每次整表清空重写。"""
    if not path:
        return False
    try:
        store.upsert_recipe(path, data)
        store.trim_recipes(400)
        return True
    except Exception as e:
        warn("add_recipe", e, path)
        return False


def _match_blocks(text, tokens):
    """把展开后的提示词按「积木原文」从长到短匹配回去，得到近似积木列表。"""
    blocks, rest = [], text or ""
    for tok, txt in sorted(tokens.items(), key=lambda kv: -len(kv[1] or "")):
        frag = (txt or "")[:60]
        if not frag or frag not in rest:
            continue
        rest = rest.replace(frag, "\u0000", 1)
        blocks.append({"token": tok, "weight": 1, "enabled": True})
    return blocks


def _parse_png_recipe(path):
    """从 ComfyUI 写进 PNG 的 prompt JSON（或重映 manifest 元数据）里还原配方。"""
    try:
        from PIL import Image
    except Exception:
        return None
    if not os.path.isfile(path):
        return None
    try:
        with Image.open(path) as im:
            raw = im.info.get("prompt")
            reproj_raw = im.info.get("sunloom_manifest")
            size = list(im.size)
    except Exception as e:
        warn("png_open", e, path)
        return None
    if not raw and reproj_raw:
        try:
            mf = json.loads(reproj_raw)
            cfg = mf.get("effective_params") or mf.get("input_config") or {}
            tokens, _, _ = load_tokens()
            pos = mf.get("plate_prompt") or cfg.get("scene") or ""
            neg = mf.get("plate_neg") or ""
            return {
                "positive": pos, "negative": neg,
                "blocks_pos": _match_blocks(pos, tokens), "blocks_neg": _match_blocks(neg, tokens),
                "blocks_guess": True, "size": [cfg.get("width", size[0]), cfg.get("height", size[1])],
                "steps": cfg.get("steps"), "cfg": cfg.get("cfg"), "seed": cfg.get("seed"),
                "denoise": 1.0, "loras": (mf.get("loras") or {}).get("plate") or [],
                "reference": "", "mode": "reproject", "manifest_path": mf.get("manifest_path", ""),
            }
        except Exception as e:
            warn("png_manifest_parse", e, path)
    if not raw:
        return None
    try:
        g = json.loads(raw)
    except Exception as e:
        warn("png_prompt_json", e, path)
        return None
    texts, loras = [], []
    sampler, latent, ref = None, None, ""
    enc_pos, enc_neg = "", ""
    for n in g.values():
        ct = n.get("class_type")
        if ct == "CLIPTextEncode":
            texts.append(n.get("inputs", {}).get("text", ""))
        elif ct in ("KSampler", "KSamplerAdvanced"):
            sampler = n.get("inputs") or {}

            def _enc(link):
                if isinstance(link, list) and link:
                    node = g.get(str(link[0]))
                    if node and node.get("class_type") == "CLIPTextEncode":
                        return node.get("inputs", {}).get("text", "") or ""
                return ""

            enc_pos = _enc(sampler.get("positive"))
            enc_neg = _enc(sampler.get("negative"))
        elif ct == "EmptyLatentImage":
            latent = n.get("inputs") or {}
        elif ct == "LoraLoaderModelOnly":
            loras.append({"name": n["inputs"].get("lora_name"),
                          "weight": n["inputs"].get("strength_model")})
        elif ct == "LoadImage":
            ref = n.get("inputs", {}).get("image", "")
    if enc_pos or enc_neg:
        pos, neg = enc_pos, enc_neg
    else:
        pos = next((t for t in texts if "1girl" in t or ", solo" in t or t.strip().startswith("(1girl")), "")
        neg = next((t for t in texts if t is not pos), "")
    tokens, _, _ = load_tokens()
    blocks = _match_blocks(pos, tokens)
    blocks_neg = _match_blocks(neg, tokens)
    mode = "inpaint" if any(n.get("class_type") == "SetLatentNoiseMask" for n in g.values()) else (
        "i2i" if ref else "t2i")
    return {
        "positive": pos, "negative": neg,
        "blocks_pos": blocks, "blocks_neg": blocks_neg, "blocks_guess": True,
        "size": [latent.get("width", size[0]), latent.get("height", size[1])] if latent else size,
        "steps": sampler.get("steps") if sampler else None,
        "cfg": sampler.get("cfg") if sampler else None,
        "seed": sampler.get("seed") if sampler else None,
        "denoise": sampler.get("denoise") if sampler else None,
        "loras": loras, "reference": ref, "mode": mode,
    }


def recipe_from_png(path, upsert=True):
    """解析单张 PNG 的精确配方，可选写入 SQLite。"""
    r = _parse_png_recipe(path)
    if not r:
        return None
    r.update({"ts": os.path.getmtime(path), "workflow": "png_metadata",
              "exact": True, "inferred": False, "source_template": "PNG 元数据"})
    if upsert:
        add_recipe(path, r)
    return r


def mirror_score(path):
    """粗略判断是否左右镜像分屏：左右两半高度相似 -> 疑似分屏。"""
    try:
        import numpy as np
        from PIL import Image
        im = Image.open(path).convert("L").resize((256, 256))
        a = np.asarray(im).astype(np.float32) / 255.0
        left = a[:, :128]
        right = np.fliplr(a[:, 128:])
        diff = float(np.abs(left - right).mean())
        return round(1.0 - diff, 3)
    except Exception:
        return 0.0
