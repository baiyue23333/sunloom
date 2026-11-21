# -*- coding: utf-8 -*-
"""B 线 · 动作导引精绘（V1.5 方案甲）：
平光动作人物卡 -> env_steps 结构空景拼接草稿 -> 全图无蒙版 0.74 + AnimaLLLiteApply 同生(带 SDPose 门禁)
-> 1.5× AnimeSharp + 2×2 切片 -> 吃重 scene_lora 的窄区 0.48 协同精修 + 带环境光词低噪锁脸。
"""
import os
import re
import shutil
import numpy as np
from PIL import Image, ImageFilter

import cutout
import depth_occlude
import light_draft as ld
import pose2d
import pose3d
import reproj_parts as parts
import reproj_provenance as rp
import scale_probe
import scene_hints


def _infer_mood(scene_text):
    low = str(scene_text or "").lower()
    if re.search(r"\b(night|neon|midnight|evening|dark street)\b|夜|霓虹", low):
        return "night"
    if re.search(r"\b(sunset|dusk|golden\s+hour|afternoon|twilight)\b|黄昏|夕阳|傍晚", low):
        return "sunset"
    if re.search(r"\b(indoor|cafe|room|classroom|library|hallway)\b|室内|咖啡|教室", low):
        return "indoor"
    return "day"


def neutral_mood_press(fg_rgba, mood):
    """无方向性时段整体曝光对齐：仅将棚拍亮度/基色收敛进目标时段范围，把具体光源方位完全交给 Step 3 同生。"""
    rgb = np.asarray(fg_rgba.convert("RGB"), dtype=np.float32)
    if mood == "night":
        rgb = rgb * np.array([0.58, 0.61, 0.74], dtype=np.float32) + np.array([6.0, 8.0, 18.0], dtype=np.float32)
    elif mood == "sunset":
        rgb = rgb * np.array([0.93, 0.85, 0.80], dtype=np.float32) + np.array([10.0, 6.0, 4.0], dtype=np.float32)
    elif mood == "indoor":
        rgb = rgb * np.array([0.90, 0.88, 0.85], dtype=np.float32) + np.array([6.0, 4.0, 2.0], dtype=np.float32)
    else:
        rgb = rgb * 0.94
    out = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    out.putalpha(fg_rgba.split()[3])
    return out


def run_char_first_pipeline(c, steps_dir, scene_loras, char_loras, detail_loras, char_neg, suffixes,
                            mf, mp, run_job, dedup_join, merge_neg, repaint_body_fn):
    """V1.5 方案甲 B 线：平光动作卡 -> 结构空景拼图 -> 全图 0.74+LLLite 同生 -> 1.5x+2x2 -> 吃重 scene_lora 0.48 精修。"""
    hint = scene_hints.analyze_scene_layering(c["scene"], c["char"])
    layer_mode = str(c.get("layer_mode") or "auto").strip().lower()
    if layer_mode in ("", "auto"):
        layer_mode = hint["layer_mode"]
    mf["layer_mode"] = layer_mode
    mf["scene_hint"] = hint

    env_steps = min(50, max(12, int(c.get("env_steps") or c["steps"] or 24)))
    char_steps = min(50, max(12, int(c.get("char_steps") or c["steps"] or 30)))
    cogen_steps = min(50, max(env_steps, char_steps))
    W, H = c["width"], c["height"]
    ratio_mode = str(c.get("ratio_mode") or "fixed").strip().lower()
    mood = _infer_mood(c["scene"])
    print("[b_char] env=%d char=%d mood=%s layer=%s rm=%s" % (env_steps, char_steps, mood, layer_mode, ratio_mode), flush=True)

    pose_cfg = c.get("pose") if isinstance(c.get("pose"), dict) else {}
    pose_mode = str(pose_cfg.get("mode") or ("3d" if pose_cfg.get("enabled") else "none")).strip().lower()
    if pose_mode not in ("none", "2d", "3d"):
        pose_mode = "none"
    cam_pitch = float(pose_cfg.get("cam_pitch") or 4.0)
    persp_cue = "high-angle view, looking down" if cam_pitch >= 16 else ("low-angle view, looking up" if cam_pitch <= -12 else "eye-level perspective")
    facing_cue = "from behind, back view" if pose_cfg.get("facing") == "back" else ""

    # 1. 空景底稿先行，auto 模式下先看景试站探测自然比例与站位
    mp.schedule("anima", note="01b_bg_draft")
    bg_raw = run_job({
        "prompt": dedup_join("(empty scene, no people, no humans:1.35)", c["scene"], persp_cue, "intricate background architecture and sky"),
        "negative": merge_neg(c["neg_scene"], "1girl, 1boy, people, person, silhouette, figure, crowd"),
        "width": W, "height": H, "steps": env_steps, "cfg": c["cfg"], "seed": c["seed"] + 21,
        "loras": scene_loras, "prefix": "BCHAR_BGD", "mode": "t2i", "save_to": "paper",
        **({"model": c["model"]} if c["model"] else {}),
    }, "结构空景底稿")
    bg_draft = os.path.join(steps_dir, "01b_bg_draft.png")
    shutil.copy2(bg_raw, bg_draft)

    probe_res, pinfo = None, {}
    if ratio_mode == "auto":
        probe_res = scale_probe.probe_natural_scale(
            bg_draft, c["char"], c["scene"], c["neg_scene"], c.get("scene_lora", ""), c.get("env_weight", 0.70),
            W, H, steps_dir, c["seed"], run_job, cfg=c["cfg"], model=c["model"],
        )
        pinfo = probe_res.get("info") or {}
        mf["scale_probe"] = {**{k: v for k, v in probe_res.items() if k != "info"}, "info": {k: v for k, v in pinfo.items() if k != "neck"}}

    # 2. 纯平光完整动作人物卡
    mp.schedule("anima", note="01_char_card")
    has_shoes = bool(re.search(r"\b(shoe|shoes|boots|sneaker|loafer|heel|sandal|slipper)\b|鞋|靴", c["char"], re.I))
    shoe_cue = "" if has_shoes else "wearing neat shoes"
    ex_p, ex_f = ("", "") if ratio_mode != "auto" else scale_probe.extra_posture_cues(c, pose_mode, pinfo, facing_cue)
    eff_facing = facing_cue or ex_f
    c_prompt = dedup_join(c["char"], shoe_cue, eff_facing, ex_p,
                          "soft even diffuse studio lighting, no directional shadow, full body, head to toe in frame, solid neutral mid-grey background, fully clothed",
                          persp_cue)
    c_neg = merge_neg(char_neg, "dramatic side shadow, harsh shadow, nude, naked, topless, nipples, barefoot, naked feet, complex background, scenery, outdoors, furniture, bench, wooden bench, chair, railing, planter box, table, floor shadow, white background")
    c_loras = detail_loras or char_loras
    c_x = pinfo.get("x_est") if (ratio_mode == "auto" and pinfo.get("ok") and not c.get("x_locked")) else (c["x"] or 0.36)
    c_gy = pinfo.get("ground_y_est") if (ratio_mode == "auto" and pinfo.get("ok")) else (c["ground_y"] or 0.90)
    c_rt = pinfo.get("ratio_est") if (ratio_mode == "auto" and pinfo.get("ok")) else (c["ratio"] or 0.42)
    contact_ref = scale_probe.build_contact_canvas(bg_draft, 832, 1152, c_x, c_gy, c_rt,
                                                   out_path=os.path.join(steps_dir, "00_contact_sketch.png"))
    pose_str = float(pose_cfg.get("strength") or (1.25 if pose_mode == "2d" else 0.62))
    pose_end = float(pose_cfg.get("end") or (0.48 if pose_mode == "2d" else 0.30))
    pose_char_p = None
    if pose_mode == "2d" and pose2d.pose2d_lllite_name():
        pose_char_p = pose2d.resolve_pose2d_image(pose_cfg, (832, 1152), cx=0.5, gy=0.92, ratio=0.76, out_path=os.path.join(steps_dir, "00_pose_char.png"))
        if pose_char_p:
            mf["pose"] = {**pose_cfg, "mode": "2d", "patch": pose2d.pose2d_lllite_name()}
            c_raw = pose2d.run_job_with_pose2d(pose_char_p, c_prompt, c_neg, 832, 1152, char_steps, c["cfg"], c["seed"] + 11, c_loras, "BCHAR_CHAR2D", ref_img_path=contact_ref, denoise=0.89, model=c["model"], strength=pose_str, end_percent=pose_end)
    elif pose_mode == "3d" and pose3d.pose_lllite_name():
        pose_char_p = pose3d.resolve_pose_image(pose_cfg, (832, 1152), cx=0.5, gy=0.92, ratio=0.76, out_path=os.path.join(steps_dir, "00_pose_char.png"))
        if pose_char_p:
            mf["pose"] = {**pose_cfg, "mode": "3d", "patch": pose3d.pose_lllite_name()}
            c_raw = pose3d.run_job_with_pose(pose_char_p, c_prompt, c_neg, 832, 1152, char_steps, c["cfg"], c["seed"] + 11, c_loras, "BCHAR_CHAR3D", ref_img_path=contact_ref, denoise=0.89, model=c["model"], strength=pose_str, end_percent=pose_end)
    if not pose_char_p:
        c_raw = run_job({
            "prompt": c_prompt, "negative": c_neg, "width": 832, "height": 1152, "steps": char_steps, "cfg": c["cfg"],
            "seed": c["seed"] + 11, "loras": c_loras, "prefix": "BCHAR_CHAR", "mode": "i2i", "reference": contact_ref, "denoise": 0.89, "save_to": "paper",
            **({"model": c["model"]} if c["model"] else {}),
        }, "接触轮廓人物卡")
    char_card = os.path.join(steps_dir, "01_char_card.png")
    shutil.copy2(c_raw, char_card)

    if ratio_mode == "auto":
        matte_u = cutout.make_matte(char_card, backend="birefnet", crop=False)
        card_pj = parts.detect_safe(char_card).get("json")
        fg, px, py, box, lll_box, used_ratio, used_gy, used_x, align_note = scale_probe.place_matte_by_probe(
            matte_u, card_pj, Image.open(char_card).size, probe_res, W, H,
            x_locked=bool(c.get("x_locked")), x_hint=c["x"] or 0.34,
        )
        mf["scale_align"] = align_note
    else:
        fg, px, py, box, lll_box, used_ratio, used_gy, used_x = scale_probe.place_fixed_matte(
            cutout.make_matte(char_card, backend="birefnet", crop=True), c["ratio"], c["ground_y"], c["x"], W, H)

    draft_im = Image.open(bg_draft).convert("RGB")
    fg_n = neutral_mood_press(fg, mood)
    draft_im.paste(fg_n.convert("RGB"), (px, py), fg_n.split()[3].filter(ImageFilter.GaussianBlur(1.2)))
    draft_p = os.path.join(steps_dir, "02_draft.png")
    draft_im.save(draft_p)

    # 3. 单次三区遮罩融合同生（合并原 03_cogen + 02_body，减少重复人物重绘）
    mp.schedule("anima", note="03_cogen")
    sl_w = min(0.68, max(0.45, round(float(c.get("env_weight") or 0.70) * 0.72, 2)))
    cl_w = round(float(c.get("char_weight") or 0.85) * 0.65, 2)
    cogen_loras = [{"name": c["scene_lora"], "weight": sl_w}] if c["scene_lora"] else []
    if c["char_lora"] and cl_w > 0:
        cogen_loras.append({"name": c["char_lora"], "weight": cl_w})
    for ex in (c.get("extra_loras") or []):
        if isinstance(ex, dict) and str(ex.get("name") or "").strip():
            cogen_loras.append({"name": ex["name"], "weight": round(float(ex.get("weight", 1.0)) * 0.68, 2)})

    cogen_pos = dedup_join("solo, 1girl", c["char"], eff_facing, c["scene"], "rich intricate environmental detail, dramatic coherent lighting, natural ground reflection and cast shadow", persp_cue)
    cogen_neg = merge_neg(c["neg_scene"], "2girls, multiple girls, extra people, crowd, another person, duplicate person, floating, bad anatomy, extra limbs")
    cogen_p = os.path.join(steps_dir, "01_plate.png")
    used_seed = c["seed"] + 31
    pose_scene_p = None
    scene_mode = pose_mode
    if pose_mode in ("2d", "none") and pose2d.pose2d_lllite_name():
        # 直接从拼好的 02_draft.png 抽取 0px 像素对齐骨架，且在 i2i 阶段关闭眼/耳彩点防止重影双脸
        j2d_draft = pose2d.extract_pose2d_from_image(draft_p)
        if j2d_draft:
            pose_scene_p = pose2d.resolve_pose2d_image(
                {"mode": "2d", "joints2d": j2d_draft}, (W, H),
                out_path=os.path.join(steps_dir, "00_pose_scene.png"),
                preserve_coords=True, draw_face_dots=False,
            )
            if pose_scene_p:
                scene_mode = "2d"
                pose_str = float(pose_cfg.get("strength") or 0.90) if pose_mode == "2d" else 0.90
                pose_end = min(0.35, float(pose_cfg.get("end") or 0.35))
    elif pose_mode == "3d" and pose3d.pose_lllite_name():
        pose_scene_p = pose3d.resolve_pose_image(pose_cfg, (W, H), cx=used_x, gy=used_gy,
                                                 ratio=used_ratio, out_path=os.path.join(steps_dir, "00_pose_scene.png"))

    # 三区连续噪点遮罩：远景 82(0.24噪)防融化；外轮廓+投影 255(0.74满噪)生光影；人物内核 155(0.45噪)保 2D 结构与异瞳不翻面
    cogen_mask_p = pose2d.build_cogen_mask(fg, px, py, W, H, steps_dir)

    for attempt, (dn, sd) in enumerate([(0.74, c["seed"] + 31), (0.66, c["seed"] + 1031)]):
        if pose_scene_p and scene_mode == "2d":
            out_raw = pose2d.run_job_with_pose2d(
                pose_scene_p, cogen_pos, cogen_neg, W, H, cogen_steps, c["cfg"], sd, cogen_loras,
                "BCHAR_COGEN2D", ref_img_path=draft_p, denoise=dn, model=c["model"],
                strength=pose_str, end_percent=pose_end, noise_mask_path=cogen_mask_p,
            )
        elif pose_scene_p and scene_mode == "3d":
            out_raw = pose3d.run_job_with_pose(
                pose_scene_p, cogen_pos, cogen_neg, W, H, cogen_steps, c["cfg"], sd, cogen_loras,
                "BCHAR_COGEN3D", ref_img_path=draft_p, denoise=dn, model=c["model"],
                strength=pose_str, end_percent=pose_end, noise_mask_path=cogen_mask_p,
            )
        else:
            out_raw = scale_probe.run_i2i_lllite(draft_p, lll_box, cogen_pos, cogen_neg, W, H, cogen_steps, c["cfg"], sd, dn,
                                                 cogen_loras, "BCHAR_COGEN", model=c["model"], ll_strength=0.80, ll_end=0.45)
        shutil.copy2(out_raw, cogen_p)
        used_seed = sd
        pj = parts.detect_safe(cogen_p).get("json")
        if pj and parts.face_box_from_pose(pj, W, H):
            print("[b_char] 03_cogen SDPose PASS (dn=%.2f attempt=%d)" % (dn, attempt + 1), flush=True)
            break
    rp.record_step(mf, "01_plate", status="ok", prompt=cogen_pos, negative=cogen_neg,
                   steps=cogen_steps, cfg=c["cfg"], seed=used_seed, loras=cogen_loras, size=[W, H], output=cogen_p)
    mp.trim_py("03_cogen_done")

    # 4. 1.5x 扩幅（默认跳过 2x2 切片与二次重绘；仅在勾选 tile_bg 时加跑背景切片精绘）
    cur_up, W2, H2 = parts.upscale_plate_safe(cogen_p, steps_dir, scale=1.5)
    raw_up = parts.detect_safe(cur_up)
    pose_up = raw_up.get("json")
    cur_bg = cur_up
    if bool(c.get("tile_bg", False)) and scene_loras:
        body_mask, strat, cov = parts.build_body_mask(cur_up, pose_up, W2, H2, used_x, used_gy, used_ratio)
        mf["mask"] = {"strategy": f"bchar_{strat}", "cov_pct": cov, "pose_json": pose_up or ""}
        if body_mask is not None:
            keep_pad = body_mask.filter(ImageFilter.MaxFilter(25)).filter(ImageFilter.GaussianBlur(10))
            cur_bg = ld.tiled_scene_refine(cur_up, steps_dir, c["scene"], c["neg_scene"], scene_loras, keep_pad,
                                             c["seed"] + 100, run_job, cfg=c["cfg"], model=c["model"],
                                             steps=max(16, env_steps - 2), denoise=0.38)

    if layer_mode in ("two_half", "three_depth"):
        s_box = [int(v * (W2 / float(W))) for v in box]
        clean_bg_up = os.path.join(steps_dir, "01b_clean_bg_up.png")
        Image.open(bg_draft).convert("RGB").resize((W2, H2), Image.LANCZOS).save(clean_bg_up)
        if layer_mode == "two_half":
            alpha_full = Image.new("L", (W2, H2), 0)
            sw_b, sh_b = max(1, s_box[2] - s_box[0]), max(1, s_box[3] - s_box[1])
            fg_crop = fg.split()[3].crop((box[0] - px, box[1] - py, box[2] - px, box[3] - py))
            alpha_full.paste(fg_crop.resize((sw_b, sh_b), Image.LANCZOS), (s_box[0], s_box[1]))
            out_im, ok_bite = depth_occlude.apply_ground_bite(clean_bg_up, Image.open(cur_bg), alpha_full, s_box)
            print("[b_char] 脚底纹理咬合: %s" % ("applied" if ok_bite else "skipped"), flush=True)
            if ok_bite:
                out_im.save(cur_bg)
        else:
            out_im, ok_occ, note = depth_occlude.apply_depth_occlusion(clean_bg_up, Image.open(cur_bg), s_box, used_gy, steps_dir)
            print("[b_char] DA3 前景提层: %s" % note, flush=True)
            if ok_occ:
                out_im.save(cur_bg)

    pose_final = parts.detect_safe(cur_bg).get("json") or pose_up
    return cur_bg, pose_final
