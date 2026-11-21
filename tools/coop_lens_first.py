# -*- coding: utf-8 -*-
"""B 线 · 镜头优先（b_lens）三步主线。

Step1 01_plate  镜头一体母板：提权镜头短语 + 稳态封顶的 scene_lora，一次性确立
                物品位置 / 前后景虚化 / 人物站位与自然朝向；SDPose 空板兜底重出一次。
Step2 02_body   1.5× AnimeSharp 扩幅 → SDPose+BiRefNet 紧贴焦内遮罩 → 命中前景遮挡时用
                DA3 扣掉明显近于落脚平面且非天空的像素（锁回虚化前景）→ 第 2/3/4 类
                镜头词剥离 + 朝向感知 → 0.44~0.50 低噪 + 高权 char_lora 原位精修。
Step3 03_face   由 coop_reproject 接管：按实测朝向门控修脸（back 跳过 / 侧脸禁对称双瞳）。
"""
import os
import shutil

import numpy as np
from PIL import Image, ImageFilter

import depth_occlude
import lens_policy
import reproj_parts as parts
import reproj_provenance as rp
import sdp_body_mask as sbm
import scale_probe


def _plate(c, prompt, neg, loras, steps, seed, steps_dir, run_job, tag):
    job = {"prompt": prompt, "negative": neg, "width": c["width"], "height": c["height"],
           "steps": steps, "cfg": c["cfg"], "seed": int(seed), "loras": loras,
           "prefix": "LENS_plate", "mode": "t2i", "save_to": "paper"}
    if c["model"]:
        job["model"] = c["model"]
    dst = os.path.join(steps_dir, tag)
    shutil.copy2(run_job(job, "镜头母板"), dst)
    return dst


def _body_cov(pose_json, W, H):
    """SDPose 连基本人体轮廓都检不出 → 强场景吃人兜底判据（返回覆盖率%）。"""
    if not pose_json or not os.path.isfile(pose_json):
        return 0.0
    try:
        m, cov = sbm.body_mask(pose_json, W, H, grow=1.22)
        return float(cov or 0.0) if m is not None else 0.0
    except Exception:
        return 0.0


def _retry_loras(c, plate_loras):
    """重出时压降 scene_lora、提 char_lora，防长场景把人吞掉。"""
    out = []
    for it in (plate_loras or []):
        name = str((it or {}).get("name") or "")
        if not name:
            continue
        w = float((it or {}).get("weight", 1.0))
        if name == c.get("char_lora"):
            w = min(0.95, max(w, round(float(c.get("char_weight") or 0.85) * 1.15, 3)))
        elif name == c.get("scene_lora"):
            w = min(0.45, round(w * 0.55, 3))
        out.append({"name": name, "weight": round(w, 3)})
    return out


def _fg_protect(plate, body_mask, steps_dir, ground_y):
    """DA3 景深：把明显近于落脚平面且非天空的像素从人体遮罩里扣掉，锁回原图虚化前景。"""
    depth_p, sky_p = depth_occlude.estimate_depth_and_sky(plate, steps_dir)
    W, H = Image.open(plate).size
    d = np.asarray(Image.open(depth_p).convert("L").resize((W, H), Image.BILINEAR), dtype=np.float32)
    s = np.asarray(Image.open(sky_p).convert("L").resize((W, H), Image.BILINEAR), dtype=np.float32) / 255.0
    a = np.asarray(body_mask.convert("L"), dtype=np.float32)
    bb = body_mask.getbbox()
    if not bb:
        return None, "empty_mask"
    bx0, by0, bx1, by1 = bb
    bw = max(1, bx1 - bx0)
    cx = (bx0 + bx1) // 2
    fy = min(H - 1, max(0, int(round(H * float(ground_y or 0.88)))))
    ay0, ay1 = max(0, fy - 14), min(H, fy + 18)
    ax0, ax1 = max(0, cx - int(bw * 0.45)), min(W, cx + int(bw * 0.45))
    band_d, band_s = d[ay0:ay1, ax0:ax1], s[ay0:ay1, ax0:ax1]
    if not band_d.size:
        return None, "no_band"
    valid = band_d[band_s < 0.35]
    d_ground = float(np.median(valid)) if valid.size else float(np.median(band_d))
    near = (d > d_ground + max(14.0, 0.08 * 255.0)) & (s < 0.35) & (a > 8)
    frac = float(near.mean())
    if frac < 0.004:
        return None, "no_fg"
    solid = float((a > 96).sum()) or 1.0
    if float((near & (a > 96)).sum()) / solid > 0.35:
        return None, "fg_too_big"
    out = np.where(near, 0.0, a)
    mask = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "L")
    mask = mask.filter(ImageFilter.GaussianBlur(1.2))
    mask.save(os.path.join(steps_dir, "01d_fg_protect_mask.png"))
    return mask, "fg_lock:%.3f" % frac


def run_lens_first_pipeline(c, steps_dir, lens, plate_prompt, plate_neg, plate_loras,
                            char_loras, detail_loras, char_neg, suffixes, mf, mp,
                            run_job, dedup_join, merge_neg, repaint_body_fn):
    """b_lens 主线：镜头一体母板 → 扩幅景深保护 + 朝向感知原位精修；返回 (当前图, 骨架 JSON)。"""
    lens = lens or lens_policy.build_lens_plan({})
    plate_steps = min(50, max(12, int(c.get("env_steps") or c["steps"])))
    char_steps = min(50, max(12, int(c.get("char_steps") or c["steps"])))
    W, H = c["width"], c["height"]
    mf["lens"] = {k: lens.get(k) for k in ("has_lens", "auto_ratio", "ratio_mode", "classes",
                                           "protect_fg_depth", "suppress_look", "count", "plate_cue")}
    print("[b_lens] 镜头积木=%d auto_ratio=%s protect_fg=%s" % (
        lens.get("count") or 0, lens.get("auto_ratio"), lens.get("protect_fg_depth")), flush=True)

    # Step 1：镜头一体母板
    mp.schedule("anima", note="01_plate")
    cur = _plate(c, plate_prompt, plate_neg, plate_loras, plate_steps, c["seed"], steps_dir, run_job, "01_plate.png")
    used_seed = c["seed"]
    used_loras = plate_loras
    pose = parts.detect_safe(cur).get("json")
    cov = _body_cov(pose, W, H)
    if cov < 0.8:
        retry_seed = c["seed"] + 313
        retry_loras = _retry_loras(c, plate_loras)
        print("[b_lens] 母板未检出人体(cov=%.2f%%)，压降 scene_lora 重出" % cov, flush=True)
        alt = _plate(c, plate_prompt, plate_neg, retry_loras, plate_steps,
                      retry_seed, steps_dir, run_job, "01_plate_retry.png")
        alt_pose = parts.detect_safe(alt).get("json")
        alt_cov = _body_cov(alt_pose, W, H)
        if alt_cov >= cov:
            cur, pose, cov = alt, alt_pose, alt_cov
            used_seed, used_loras = retry_seed, retry_loras
    rp.record_step(mf, "01_plate", status="ok", prompt=plate_prompt, negative=plate_neg,
                   steps=plate_steps, cfg=c["cfg"], seed=used_seed, loras=used_loras,
                   size=[W, H], output=cur, body_cov=round(cov, 2))
    mp.trim_py("01_plate_done")

    # Step 2：扩幅 + 景深保护 + 朝向感知原位精修
    mp.schedule("anima", note="02_body")
    cur_up, W2, H2 = parts.upscale_plate_safe(cur, steps_dir, scale=1.5)
    pose_up = parts.detect_safe(cur_up).get("json") or pose
    facing = scale_probe.infer_head_facing(pose_up, W2, H2) or ""
    mf["lens"]["facing_step2"] = facing
    mask, strat, mcov = parts.build_body_mask(cur_up, pose_up, W2, H2, c["x"], c["ground_y"], c["ratio"])
    mf["mask"] = {"strategy": "b_lens_%s" % strat, "cov_pct": mcov, "pose_json": pose_up or ""}
    if strat == "geometric_fallback" or mask is None or not mask.getbbox():
        rp.record_step(mf, "02_body", status="skipped", note="no_valid_body_mask", output=cur_up)
        print("[gate] B线未取得有效人体蒙版，保留原板并跳过盲画", flush=True)
        return cur_up, pose_up
    if lens.get("protect_fg_depth"):
        try:
            pm, note = _fg_protect(cur_up, mask, steps_dir, c["ground_y"])
        except Exception as e:  # noqa: BLE001
            pm, note = None, "da3_skip:%s" % str(e)[:60]
        if pm is not None:
            mask = pm
        mf["lens"]["fg_protect"] = note
        print("[b_lens] 前景深度锁回: %s" % note, flush=True)

    body_txt = lens_policy.body_prompt(c["char"], lens)
    body_txt = lens_policy.adapt_face_prompt(body_txt, facing)
    cue = lens_policy.facing_cue(facing)
    if cue:
        body_txt = dedup_join(body_txt, cue)
    dn = 0.50 if str(facing).startswith("profile") else 0.46
    print("[b_lens] 02_body mask=%s 朝向=%s denoise=%.2f" % (strat, facing, dn), flush=True)
    res = repaint_body_fn(cur_up, mask, steps_dir, body_txt, char_neg, detail_loras or char_loras,
                          char_steps, c["cfg"], used_seed, style_suffix=suffixes["style"],
                          mf=mf, model=c["model"], denoise_override=dn)
    mp.trim_py("02_body_done")
    pose_final = parts.detect_safe(res).get("json") or pose_up
    return res, pose_final
