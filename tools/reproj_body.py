# -*- coding: utf-8 -*-
"""02_body 局部原位精修（从 reproj_parts 拆出，保持单文件 <20KB）。"""
import os
import time

from PIL import Image, ImageFilter

import fusion
import hand_precise as hp
import reproj_provenance as rp
from reproj_parts import align8


def repaint_body(plate_path, mask, steps_dir, char_prompt, neg_char, char_loras, steps, cfg, seed,
                 style_suffix="", mf=None, model="", denoise_override=0.0, run_job=None):
    """局部原位精修（02_body）：蒙版外扩裁切 → 对齐采样 → inpaint → 低频配色融合 → 软边贴回。"""
    im = Image.open(plate_path).convert("RGB")
    W, H = im.size
    if mask.size != (W, H):
        mask = mask.resize((W, H), Image.LANCZOS)
    bbox = mask.getbbox()
    if not bbox:
        if mf is not None:
            rp.record_step(mf, "02_body", status="skipped", note="empty_mask_bbox")
        return plate_path
    bx0, by0, bx1, by1 = bbox
    bw, bh = bx1 - bx0, by1 - by0
    pad_x, pad_y = max(24, int(bw * 0.22)), max(24, int(bh * 0.18))
    x0, y0 = max(0, bx0 - pad_x), max(0, by0 - pad_y)
    x1, y1 = min(W, bx1 + pad_x), min(H, by1 + pad_y)
    cw, ch = x1 - x0, y1 - y0
    # 防止裁成极端窄条（如 416x1016）：横向补足背景视域到健康比例（>= 0.62），背景侧 mask 保持为 0 不改背景
    if cw < int(ch * 0.62) and W > cw:
        want_w = min(W, int(ch * 0.62))
        cx_mid = (x0 + x1) // 2
        x0 = max(0, min(W - want_w, cx_mid - want_w // 2))
        x1 = x0 + want_w
        cw = x1 - x0
    area_frac = (cw * ch) / float(W * H)

    crop_img = im.crop((x0, y0, x1, y1))
    crop_mask = mask.crop((x0, y0, x1, y1))
    long_side = max(cw, ch)
    target_long = 1024 if (denoise_override > 0 or area_frac < 0.45) else min(1024, max(768, long_side))
    scale = max(1.0, target_long / float(max(long_side, 1)))
    min_w = 512 if (cw < ch and W >= 512) else 256
    tw = align8(cw * scale, min_w, 1024)
    th = align8(ch * scale, 256, 1024)
    if tw != cw or th != ch:
        crop_big = crop_img.resize((tw, th), Image.LANCZOS)
        mask_big = crop_mask.resize((tw, th), Image.LANCZOS)
    else:
        crop_big, mask_big = crop_img, crop_mask

    denoise = float(denoise_override) if denoise_override > 0 else (0.50 if area_frac < 0.30 else (0.42 if area_frac < 0.55 else 0.36))
    tag = "%s_%03d" % (time.strftime("%H%M%S"), int(time.time() * 1000) % 1000)
    big_path = os.path.join(steps_dir, "_body_crop_%s.png" % tag)
    crop_big.save(big_path)
    mask_name = "reproj_body_%s.png" % tag
    Image.merge("RGB", (mask_big, mask_big, mask_big)).save(os.path.join(hp.CI, mask_name))
    mask.save(os.path.join(steps_dir, "mask_body.png"))

    body_prompt = rp.append_suffix(char_prompt, style_suffix)
    body_steps = min(24, max(18, int(steps) - 4))
    print("[body] 占比=%.1f%% 裁切=%dx%d -> 采样=%dx%d denoise=%.2f" %
          (area_frac * 100, cw, ch, tw, th, denoise), flush=True)
    job_body = {
        "prompt": body_prompt, "negative": neg_char, "mode": "inpaint",
        "reference": big_path, "mask": mask_name, "denoise": denoise,
        "steps": body_steps, "cfg": cfg, "seed": seed + 1, "loras": char_loras,
        "prefix": "REPROJ_body", "save_to": "paper", "width": tw, "height": th,
    }
    if model:
        job_body["model"] = model
    res_path = run_job(job_body, "人物重绘")

    back = Image.open(res_path).convert("RGB").resize((cw, ch), Image.LANCZOS)
    soft = crop_mask.filter(ImageFilter.GaussianBlur(max(3, int(min(cw, ch) * 0.007))))
    try:
        graded, _ = fusion.lowfreq_match(back.convert("RGBA"), im, (x0, y0, x1, y1), weight=0.20)
        back = graded.convert("RGB")
    except Exception as e:  # noqa: BLE001
        print("[fusion] 跳过:", str(e)[:70], flush=True)
    out = im.copy()
    out.paste(back, (x0, y0), soft)
    dst = os.path.join(steps_dir, "02_body.png")
    out.save(dst)
    if mf is not None:
        rp.record_step(mf, "02_body", status="ok", prompt=body_prompt, negative=neg_char,
                       denoise=denoise, steps=body_steps, cfg=cfg, seed=seed + 1, loras=char_loras,
                       crop_box=[x0, y0, x1, y1], sample_size=[tw, th], output=dst, sub_output=res_path)
    return dst
