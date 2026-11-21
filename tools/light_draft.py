# -*- coding: utf-8 -*-
"""程序化光影构图引导图（Light & Value Underpainting）：按站位与光源直接绘制大模糊明暗体块。"""
import math
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def build_light_draft(out_path, width, height, x_frac=0.36, gy_frac=0.90, ratio=0.45, light="left", seed=0):
    """生成方案甲光影引导底稿：冷暖纵深底色 + 窗光束 + 中灰人物受光块 + 方向投射影，经高模糊后供 i2i 成画。"""
    W, H = max(256, int(width)), max(256, int(height))
    # 1. 基础纵向环境透视渐变（顶部偏深冷，地平线略暗，地板暖木反光）
    yy = np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None]
    xx = np.linspace(0.0, 1.0, W, dtype=np.float32)[None, :]
    r = 46.0 + 68.0 * np.power(yy, 1.4) + 12.0 * np.exp(-((yy - 0.52) ** 2) / 0.04)
    g = 48.0 + 48.0 * np.power(yy, 1.4) + 10.0 * np.exp(-((yy - 0.52) ** 2) / 0.04)
    b = 62.0 + 20.0 * np.power(yy, 1.4) + 14.0 * np.exp(-((yy - 0.52) ** 2) / 0.04)
    arr = np.stack([np.broadcast_to(r, (H, W)), np.broadcast_to(g, (H, W)), np.broadcast_to(b, (H, W))], axis=-1)

    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGB")
    d = ImageDraw.Draw(im)

    # 2. 主光源窗区 + 投射到人物脚下/地面的光束
    cx = int(W * max(0.15, min(0.85, float(x_frac or 0.36))))
    feet_y = int(H * max(0.45, min(0.96, float(gy_frac or 0.90))))
    fh = max(64, int(H * max(0.20, min(0.85, float(ratio or 0.45)))))
    fw = max(32, int(fh * 0.38))

    if light == "right":
        d.ellipse((int(W * 0.62), -int(H * 0.12), int(W * 1.18), int(H * 0.72)), fill=(214, 212, 206))
        shadow_dir = -1
    elif light == "back":
        d.ellipse((int(W * 0.18), -int(H * 0.08), int(W * 0.82), int(H * 0.68)), fill=(218, 220, 226))
        shadow_dir = 0
    else:  # default "left"
        d.ellipse((-int(W * 0.18), -int(H * 0.12), int(W * 0.38), int(H * 0.72)), fill=(214, 212, 206))
        shadow_dir = 1

    # 3. 地面投射阴影（沿主光源反方向，不强加室内遮挡暗角）
    if shadow_dir != 0:
        dx = int(fh * 0.42) * shadow_dir
        d.polygon([(cx - int(fw * 0.28), feet_y - 4), (cx + int(fw * 0.28), feet_y - 4),
                   (cx + dx + int(fw * 0.35), feet_y + int(H * 0.06)),
                   (cx + dx - int(fw * 0.25), feet_y + int(H * 0.06))], fill=(46, 38, 34))
    else:
        d.ellipse((cx - int(fw * 0.65), feet_y - 6, cx + int(fw * 0.65), feet_y + int(H * 0.08)), fill=(46, 38, 34))

    # 5. 人物站位中灰体积块 + 受光边（不抢细节，只给潜空间明暗引导）
    top_y = max(0, feet_y - fh)
    hr = max(10, int(fh * 0.09))
    d.ellipse((cx - hr, top_y, cx + hr, top_y + int(hr * 2.2)), fill=(168, 154, 148))
    d.rounded_rectangle((cx - int(fw * 0.46), top_y + int(hr * 2.0), cx + int(fw * 0.46), top_y + int(fh * 0.62)),
                        radius=max(6, int(fw * 0.2)), fill=(154, 144, 142))
    d.rectangle((cx - int(fw * 0.34), top_y + int(fh * 0.60), cx + int(fw * 0.34), feet_y), fill=(116, 108, 112))
    # 受光轮廓亮边
    if shadow_dir == 1:
        d.line([(cx - int(fw * 0.42), top_y + hr), (cx - int(fw * 0.42), feet_y - 8)], fill=(235, 212, 178), width=max(4, int(W * 0.008)))
    elif shadow_dir == -1:
        d.line([(cx + int(fw * 0.42), top_y + hr), (cx + int(fw * 0.42), feet_y - 8)], fill=(235, 212, 178), width=max(4, int(W * 0.008)))

    # 6. 大高斯模糊 + 微颗粒防止色带
    blur_r = max(18, int(min(W, H) * 0.032))
    im = im.filter(ImageFilter.GaussianBlur(blur_r))
    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    out_arr = np.asarray(im, dtype=np.float32) + rng.normal(0.0, 3.0, (H, W, 3)).astype(np.float32)
    out_img = Image.fromarray(np.clip(out_arr, 0, 255).astype(np.uint8))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    out_img.save(out_path)
    return out_path


def _tile_weight(w, h, x0, y0, x1, y1, W, H, pad=180):
    wy = np.ones(h, dtype=np.float32)
    wx = np.ones(w, dtype=np.float32)
    if x0 > 0:
        wx[:pad] = np.minimum(wx[:pad], np.linspace(0.0, 1.0, min(pad, w), dtype=np.float32)[:len(wx[:pad])])
    if x1 < W:
        wx[-pad:] = np.minimum(wx[-pad:], np.linspace(1.0, 0.0, min(pad, w), dtype=np.float32)[-len(wx[-pad:]):])
    if y0 > 0:
        wy[:pad] = np.minimum(wy[:pad], np.linspace(0.0, 1.0, min(pad, h), dtype=np.float32)[:len(wy[:pad])])
    if y1 < H:
        wy[-pad:] = np.minimum(wy[-pad:], np.linspace(1.0, 0.0, min(pad, h), dtype=np.float32)[-len(wy[-pad:]):])
    return (wy[:, None] * wx[None, :])[..., None]


def tiled_scene_refine(plate_path, steps_dir, scene_prompt, neg_scene, scene_loras, mask_keep, seed_base, run_job, cfg=5.5, model="", steps=22, denoise=0.42):
    """M1 双底片激进精绘：2×2 重叠切片（每片 ≤1024×720 防 OOM）单挂环境 LoRA 补足道具笔触，再保留原人物遮罩区域。"""
    im = Image.open(plate_path).convert("RGB")
    W, H = im.size
    # 横竖屏自适应切片尺寸（横屏 ≤1024×720、竖屏 ≤720×1024），确保 2×2 至少重叠 160px 不留黑带
    lim_w, lim_h = (720, 1024) if H > W else (1024, 720)
    tw = min(W, max(lim_w, ((W // 2 + 96 + 7) // 8) * 8)) if W > lim_w else (W // 8) * 8
    th = min(H, max(lim_h, ((H // 2 + 96 + 7) // 8) * 8)) if H > lim_h else (H // 8) * 8
    tiles = [(0, 0, tw, th), (W - tw, 0, W, th), (0, H - th, tw, H), (W - tw, H - th, W, H)]
    acc = np.zeros((H, W, 3), dtype=np.float32)
    wsum = np.zeros((H, W, 1), dtype=np.float32)
    detail_p = scene_prompt + ", crisp architectural and surface textures, clean lighting continuity, intricate painterly brushwork"
    neg_p = (neg_scene + ", 1girl, 1boy, people, character, human silhouette, person shadow, cast shadow of a person") if neg_scene else "1girl, 1boy, people, character, human silhouette, person shadow, cast shadow of a person"
    for idx, (x0, y0, x1, y1) in enumerate(tiles):
        cw, ch = x1 - x0, y1 - y0
        crop_p = os.path.join(steps_dir, "_m1_tile_%d.png" % idx)
        im.crop((x0, y0, x1, y1)).save(crop_p)
        job = {"prompt": detail_p, "negative": neg_p, "mode": "i2i", "reference": crop_p,
               "denoise": float(denoise), "steps": min(50, max(12, int(steps))), "cfg": cfg, "seed": int(seed_base) + idx,
               "width": cw, "height": ch, "loras": scene_loras, "prefix": "M1_TILE%d" % idx, "save_to": "paper"}
        if model:
            job["model"] = model
        res_p = run_job(job, "背景切片%d" % (idx + 1))
        arr = np.asarray(Image.open(res_p).convert("RGB").resize((cw, ch), Image.LANCZOS), dtype=np.float32)
        wm = _tile_weight(cw, ch, x0, y0, x1, y1, W, H, pad=min(180, cw // 4, ch // 4))
        acc[y0:y1, x0:x1] += arr * wm
        wsum[y0:y1, x0:x1] += wm
    src_arr = np.asarray(im, dtype=np.float32)
    blended = np.where(wsum > 1e-5, acc / np.maximum(wsum, 1e-5), src_arr)
    refined = Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8))
    if mask_keep is not None:
        refined.paste(im, (0, 0), mask_keep.filter(ImageFilter.GaussianBlur(10)))
    dst = os.path.join(steps_dir, "01c_tiled_bg.png")
    refined.save(dst)
    print("[m1] 2x2 背景切片精绘完成 %dx%d" % (W, H), flush=True)
    return dst


def prepare_lm_body(c, cur, steps_dir, detail_loras, char_loras, mf, mp, run_job, dedup_join, is_m1):
    """L / M1 流水线全身重绘准备：1.5× 安全扩幅 + M1 2×2 背景切片精绘 + 纯人物 LoRA 与降噪参数。"""
    import reproj_parts as parts
    cur, pw, ph = parts.upscale_plate_safe(cur, steps_dir, scale=1.5)
    mp.schedule("anima", note="02_body")
    raw1 = parts.detect_safe(cur)
    mask, m_strat, m_cov = parts.build_body_mask(cur, raw1.get("json"), pw, ph, c["x"], c["ground_y"], c["ratio"])
    mf["mask"] = {"strategy": m_strat, "cov_pct": m_cov, "pose_json": raw1.get("json") or ""}
    use_loras = char_loras
    if is_m1:
        sloras = [{"name": c["scene_lora"], "weight": min(0.95, max(0.75, c["env_weight"]))}] if c["scene_lora"] else []
        if sloras:
            cur = tiled_scene_refine(cur, steps_dir, c["scene"], c["neg_scene"], sloras, mask, c["seed"] + 100, run_job, cfg=c["cfg"], model=c["model"])
        use_loras = detail_loras or char_loras
    btxt = dedup_join(c["char"], "intricate clothing folds, delicate hair strands, clean shoes, sharp anime lineart" if is_m1 else "crisp detailed clothing folds, clean shoes")
    return cur, mask, btxt, (0.64 if is_m1 else 0.54), use_loras


def run_ab_stage(c, is_b, steps_dir, plate_prompt, plate_neg, plate_loras, char_loras, detail_loras, char_neg, suffixes, mf, mp, run_job, dedup_join, repaint_body_fn):
    """执行 A 混绘(含 SDPose 门禁防畸形/禁盲画) / 旧 B 双画的 Stage 1-2，返回 (cur, pose2)。"""
    import shutil
    import reproj_parts as parts
    import reproj_provenance as rp
    mp.schedule("anima", note="01_plate")
    plate_steps = min(50, max(12, int(c.get("env_steps") or c["steps"])))
    char_steps = min(50, max(12, int(c.get("char_steps") or c["steps"])))
    print("[1/3] 出板 %dx%d steps=%d loras=%d pipeline=%s" % (c["width"], c["height"], plate_steps, len(plate_loras), c["pipeline"]), flush=True)

    def _run_plate(sd):
        if is_b:
            ld_path = build_light_draft(os.path.join(steps_dir, "00_light_draft.png"),
                                        c["width"], c["height"], c["x"], c["ground_y"], c["ratio"], c["light"], sd)
            job = {"prompt": plate_prompt, "negative": plate_neg, "width": c["width"], "height": c["height"],
                   "steps": plate_steps, "cfg": c["cfg"], "seed": sd, "loras": plate_loras,
                   "prefix": "REPROJ_light", "mode": "i2i", "reference": ld_path, "denoise": 0.88, "save_to": "paper"}
        else:
            import pose2d, pose3d
            pose_cfg = c.get("pose") if isinstance(c.get("pose"), dict) else {}
            pm = str(pose_cfg.get("mode") or ("3d" if pose_cfg.get("enabled") else "none")).strip().lower()
            if pm == "2d" and pose2d.pose2d_lllite_name():
                pp = pose2d.resolve_pose2d_image(pose_cfg, (c["width"], c["height"]), cx=c["x"], gy=c["ground_y"], ratio=c["ratio"],
                                                 out_path=os.path.join(steps_dir, "00_pose_plate.png"))
                if pp:
                    mf["pose"] = {**pose_cfg, "mode": "2d", "patch": pose2d.pose2d_lllite_name()}
                    return pose2d.run_job_with_pose2d(pp, plate_prompt, plate_neg, c["width"], c["height"], plate_steps,
                                                      c["cfg"], sd, plate_loras, "REPROJ_plate2D", model=c["model"],
                                                      strength=float(pose_cfg.get("strength") or 1.25),
                                                      end_percent=float(pose_cfg.get("end") or 0.48))
            if pm == "3d" and pose3d.pose_lllite_name():
                pp = pose3d.resolve_pose_image(pose_cfg, (c["width"], c["height"]), cx=c["x"], gy=c["ground_y"], ratio=c["ratio"],
                                               out_path=os.path.join(steps_dir, "00_pose_plate.png"))
                if pp:
                    mf["pose"] = {**pose_cfg, "mode": "3d", "patch": pose3d.pose_lllite_name()}
                    return pose3d.run_job_with_pose(pp, plate_prompt, plate_neg, c["width"], c["height"], plate_steps,
                                                    c["cfg"], sd, plate_loras, "REPROJ_plate3D", model=c["model"],
                                                    strength=float(pose_cfg.get("strength") or 0.62),
                                                    end_percent=float(pose_cfg.get("end") or 0.30))
            job = {"prompt": plate_prompt, "negative": plate_neg, "width": c["width"], "height": c["height"],
                   "steps": plate_steps, "cfg": c["cfg"], "seed": sd, "loras": plate_loras,
                   "prefix": "REPROJ_plate", "mode": "t2i", "save_to": "paper"}
        if c["model"]:
            job["model"] = c["model"]
        return run_job(job, "出板")

    p1 = _run_plate(c["seed"])
    cur = os.path.join(steps_dir, "01_plate.png")
    shutil.copy2(p1, cur)
    used_seed = c["seed"]
    if not c["char"].strip():
        rp.record_step(mf, "01_plate", status="ok", prompt=plate_prompt, negative=plate_neg,
                       steps=plate_steps, cfg=c["cfg"], seed=used_seed, loras=plate_loras,
                       size=[c["width"], c["height"]], output=cur, sub_output=p1)
        mp.trim_py("01_plate_done")
        return cur, None

    if is_b:
        rp.record_step(mf, "01_plate", status="ok", prompt=plate_prompt, negative=plate_neg,
                       steps=plate_steps, cfg=c["cfg"], seed=used_seed, loras=plate_loras,
                       size=[c["width"], c["height"]], output=cur, sub_output=p1)
        mp.trim_py("01_plate_done")
        print("[2/3] 人物高分重绘 steps=%d loras=%d pipeline=%s" % (char_steps, len(char_loras), c["pipeline"]), flush=True)
        cur, mask, body_txt, dn_ov, use_loras = prepare_lm_body(c, cur, steps_dir, detail_loras, char_loras, mf, mp, run_job, dedup_join, True)
    else:
        raw1 = parts.detect_safe(cur)
        mask, m_strat, m_cov = parts.build_body_mask(cur, raw1.get("json"), c["width"], c["height"], c["x"], c["ground_y"], c["ratio"])
        if m_strat not in ("birefnet+sdpose", "sdpose"):
            print("[gate] A 出板未检出完整骨架(%s)，换种自动重抽一次" % m_strat, flush=True)
            used_seed = c["seed"] + 77
            p1_r = _run_plate(used_seed)
            cur_r = os.path.join(steps_dir, "01_plate_retry.png")
            shutil.copy2(p1_r, cur_r)
            raw_r = parts.detect_safe(cur_r)
            mask_r, strat_r, cov_r = parts.build_body_mask(cur_r, raw_r.get("json"), c["width"], c["height"], c["x"], c["ground_y"], c["ratio"])
            if strat_r in ("birefnet+sdpose", "sdpose") or (m_strat == "geometric_fallback" and strat_r != "geometric_fallback"):
                shutil.copy2(cur_r, cur)
                p1, raw1, mask, m_strat, m_cov = p1_r, raw_r, mask_r, strat_r, cov_r
        rp.record_step(mf, "01_plate", status="ok", prompt=plate_prompt, negative=plate_neg,
                       steps=plate_steps, cfg=c["cfg"], seed=used_seed, loras=plate_loras,
                       size=[c["width"], c["height"]], output=cur, sub_output=p1)
        mp.trim_py("01_plate_done")
        mf["mask"] = {"strategy": m_strat, "cov_pct": m_cov, "pose_json": raw1.get("json") or ""}
        if m_strat == "geometric_fallback":
            print("[gate] 重抽仍无有效骨架，禁用 geometric_fallback 盲画并保留原板", flush=True)
            rp.record_step(mf, "02_body", status="skipped", note="no_sdpose_guard")
            return cur, raw1.get("json")
        print("[2/3] 人物高分重绘 steps=%d mask=%s" % (char_steps, m_strat), flush=True)
        body_txt, dn_ov, use_loras = c["char"], 0.0, char_loras

    mp.schedule("anima", note="02_body")
    cur = repaint_body_fn(cur, mask, steps_dir, body_txt, char_neg, use_loras, char_steps, c["cfg"], used_seed,
                          style_suffix=suffixes["style"], mf=mf, model=c["model"], denoise_override=dn_ov)
    mp.trim_py("02_body_done")
    print("[3/3] 脸部/手部精修与合成", flush=True)
    return cur, parts.detect_safe(cur).get("json")
