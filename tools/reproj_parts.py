# -*- coding: utf-8 -*-
"""重映工作台几何/骨架解析与遮罩辅助（从 coop_reproject.py 拆出）。"""
import json
import math
import os
import tempfile

import numpy as np
from PIL import Image, ImageChops, ImageFilter

import cutout
import hand_precise as hp
import plate_detail as pd
import sdp_body_mask as sbm


def align8(v, lo=256, hi=2048):
    v = max(lo, min(hi, int(round(v))))
    return max(lo, v - (v % 8))


def detect_safe(img_path):
    try:
        return hp.detect_raw(img_path)
    except Exception as e:  # noqa: BLE001
        print("[pose] 检测跳过:", str(e)[:80], flush=True)
        return {}


def _dilate_alpha(a, W, H):
    """二值稳固核心后外扩并轻量羽化，防止 02_body 发丝/饰品微移回贴时透出底板重影。"""
    core = a.point(lambda v: 255 if v >= 96 else (0 if v <= 16 else v))
    core = core.filter(ImageFilter.MaxFilter(17)).filter(ImageFilter.MaxFilter(11))
    return core.filter(ImageFilter.GaussianBlur(max(3, int(min(W, H) * 0.005))))


def _roi_birefnet_union(plate_path, sdp_m, W, H):
    """按 SDPose 人体框裁剪局部做 BiRefNet 轮廓合并，包住礼服裙摆与垂落外套而不误抓远处背景。"""
    bb = sdp_m.getbbox()
    if not bb:
        return None
    bx0, by0, bx1, by1 = bb
    bw, bh = bx1 - bx0, by1 - by0
    px, pt, pb = max(48, int(bw * 0.45)), max(32, int(bh * 0.16)), max(24, int(bh * 0.12))
    rx0, ry0 = max(0, bx0 - px), max(0, by0 - pt)
    rx1, ry1 = min(W, bx1 + px), min(H, by1 + pb)
    rw, rh = rx1 - rx0, ry1 - ry0
    if rw < 64 or rh < 64:
        return None
    fd, tmp_roi = tempfile.mkstemp(suffix=".png", prefix="reproj_roi_")
    os.close(fd)
    try:
        Image.open(plate_path).convert("RGB").crop((rx0, ry0, rx1, ry1)).save(tmp_roi)
        matte = cutout.make_matte(tmp_roi, backend="birefnet", crop=False)
        if isinstance(matte, str):
            matte = Image.open(matte)
        a = matte.convert("RGBA").split()[3]
        if a.size != (rw, rh):
            a = a.resize((rw, rh), Image.LANCZOS)
        fg_pct = float((np.asarray(a) >= 96).mean()) * 100.0
        if not (6.0 <= fg_pct <= 78.0):
            return None
        a = _dilate_alpha(a, W, H)
        canvas = Image.new("L", (W, H), 0)
        canvas.paste(a, (rx0, ry0))
        return ImageChops.lighter(sdp_m, canvas)
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp_roi)
        except OSError:
            pass


def build_body_mask(plate_path, pose_json, W, H, cx_frac, gy_frac, ratio):
    sdp_fb = None
    if pose_json and os.path.isfile(pose_json):
        try:
            m, cov = sbm.body_mask(pose_json, W, H, grow=1.22)
            if m is not None and 1.0 <= cov <= 78.0:
                merged = _roi_birefnet_union(plate_path, m, W, H)
                if merged is not None:
                    mcov = float(np.asarray(merged).mean()) / 255.0 * 100.0
                    print("[mask] BiRefNet+SDPose %.1f%%" % mcov, flush=True)
                    return merged, "birefnet+sdpose", round(mcov, 2)
                print("[mask] SDPose 骨架 %.1f%%" % cov, flush=True)
                return m, "sdpose", round(cov, 2)
            if m is not None and 0.25 <= cov < 1.0:
                sdp_fb = (m, cov)
        except Exception as e:  # noqa: BLE001
            print("[mask] 骨架失败:", str(e)[:70], flush=True)

    try:
        matte = cutout.make_matte(plate_path, backend="birefnet", crop=False)
        if isinstance(matte, str):
            matte = Image.open(matte)
        a = matte.convert("RGBA").split()[3]
        if a.size != (W, H):
            a = a.resize((W, H), Image.LANCZOS)
        cov = float(np.asarray(a).mean()) / 255.0 * 100.0
        if (0.5 if sdp_fb is None else 1.8) <= cov <= 72.0:
            print("[mask] BiRefNet %.1f%%" % cov, flush=True)
            return _dilate_alpha(a, W, H), "birefnet", round(cov, 2)
    except Exception as e:  # noqa: BLE001
        print("[mask] BiRefNet 跳过:", str(e)[:70], flush=True)

    if sdp_fb is not None:
        print("[mask] SDPose 小人保留 %.2f%%" % sdp_fb[1], flush=True)
        return sdp_fb[0], "sdpose_small", round(sdp_fb[1], 2)

    fh = max(64, int(H * max(0.18, min(0.88, ratio or 0.30))))
    fw = int(fh * 0.48)
    cx = int(W * max(0.15, min(0.85, cx_frac or 0.34)))
    feet = int(H * max(0.45, min(0.96, gy_frac or 0.88)))
    box = (max(0, cx - fw // 2), max(0, feet - fh), min(W, cx + fw // 2), feet)
    m = sbm._humanoid(Image.new("L", (W, H), 0), box, W, H)
    m = m.filter(ImageFilter.GaussianBlur(max(6, int(min(W, H) * 0.01))))
    cov = float(np.asarray(m).mean()) / 255.0 * 100.0
    print("[mask] 回退人形站位框 cov=%.1f%%" % cov, flush=True)
    return m, "geometric_fallback", round(cov, 2)


def face_box_from_pose(pose_json, W, H):
    if not pose_json or not os.path.isfile(pose_json):
        return None
    pts, _, _ = sbm.load_pose(pose_json)
    if len(pts) < 18:
        return None

    def pt(i):
        x, y, s = pts[i]
        return (x, y) if s > 0.18 and 0 <= x <= W and 0 <= y <= H else None

    face_pts = [p for p in (pt(0), pt(14), pt(15), pt(16), pt(17)) if p]
    if len(face_pts) < 2 and not (pt(0) or pt(1)):
        return None
    ears, eyes, rs, ls = [pt(16), pt(17)], [pt(14), pt(15)], pt(2), pt(5)
    if ears[0] and ears[1]:
        r = max(14.0, math.hypot(ears[0][0] - ears[1][0], ears[0][1] - ears[1][1]) * 0.95)
    elif eyes[0] and eyes[1]:
        r = max(14.0, math.hypot(eyes[0][0] - eyes[1][0], eyes[0][1] - eyes[1][1]) * 1.95)
    elif rs and ls:
        r = max(14.0, math.hypot(rs[0] - ls[0], rs[1] - ls[1]) * 0.42)
    else:
        r = max(16.0, min(W, H) * 0.05)

    if face_pts:
        cx = sum(p[0] for p in face_pts) / len(face_pts)
        cy = sum(p[1] for p in face_pts) / len(face_pts) - r * 0.08
    else:
        neck = pt(1)
        cx, cy = neck[0], neck[1] - r * 1.1

    x0, y0 = int(max(0, cx - r * 1.15)), int(max(0, cy - r * 1.25))
    x1, y1 = int(min(W, cx + r * 1.15)), int(min(H, cy + r * 1.05))
    bw, bh = x1 - x0, y1 - y0
    if bw < 14 or bh < 14:
        return None
    return {"x": x0, "y": y0, "w": bw, "h": bh}


def hand_boxes_from_pose(pose_json, W, H, face_box=None):
    if not pose_json or not os.path.isfile(pose_json):
        return []
    try:
        data = json.load(open(pose_json, encoding="utf-8"))
        if isinstance(data, dict):
            data = [data]
        person = (data[0].get("people") or [{}])[0]
    except Exception:
        return []

    fh = float(face_box["h"]) if face_box else min(W, H) * 0.14
    max_rad = max(42.0, fh * 1.45)
    out = []
    for key, label in (("hand_left_keypoints_2d", "left"), ("hand_right_keypoints_2d", "right")):
        arr = person.get(key) or []
        pts = [(arr[i], arr[i + 1], arr[i + 2]) for i in range(0, len(arr) - 2, 3)]
        valid = [p for p in pts if p[2] > 0.18 and 0 <= p[0] <= W and 0 <= p[1] <= H]
        if len(valid) < 6:
            continue
        mx = float(np.median([p[0] for p in valid]))
        my = float(np.median([p[1] for p in valid]))
        valid = [p for p in valid if math.hypot(p[0] - mx, p[1] - my) <= max_rad]
        if len(valid) < 6:
            continue
        xs, ys = [p[0] for p in valid], [p[1] for p in valid]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 10.0)
        pad = 0.24 * span + 10
        x0, y0 = int(max(0, min(xs) - pad)), int(max(0, min(ys) - pad))
        x1, y1 = int(min(W, max(xs) + pad)), int(min(H, max(ys) + pad))
        bw, bh = x1 - x0, y1 - y0
        area = (bw * bh) / float(W * H)
        if bw < 12 or bh < 12 or area < 0.00035 or area > 0.16 or max(bw, bh) > max(fh * 2.1, min(W, H) * 0.25):
            continue
        if x0 <= 2 or y0 <= 2 or x1 >= W - 2 or y1 >= H - 2:
            continue
        score = max(p[2] for p in valid)
        box = {"x": x0, "y": y0, "w": bw, "h": bh, "hand": label, "score": float(score)}
        poly = hp.hand_polygon(pose_json, label)
        if poly is not None:
            box["polygon"] = poly.reshape(-1, 2).tolist()
        out.append(box)
    out.sort(key=lambda b: -b["score"])
    return out[:2]


def apply_feet_shadow(img, pose_json, light="", strength=150):
    if not pose_json or not os.path.isfile(pose_json):
        return img, 0
    W, H = img.size
    try:
        _, feet, _, _ = pd.load_pts(pose_json)
    except Exception:
        return img, 0
    visible_feet = [(x, y, s) for x, y, s in feet if s >= 0.2 and 4 <= x <= W - 4 and 4 <= y <= H - 4]
    if not visible_feet:
        return img, 0
    out, fn = pd.feet_shadow(img, visible_feet, strength=int(strength))
    if light in ("left", "right") and visible_feet:
        from PIL import ImageDraw
        fx = sum(p[0] for p in visible_feet) / len(visible_feet)
        fy = max(p[1] for p in visible_feet)
        dx = int(H * 0.13) * (1 if light == "left" else -1)
        sh = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(sh)
        x0, x1 = sorted([fx - int(W * 0.025), fx + dx + int(W * 0.025)])
        d.polygon([(fx - int(W * 0.022), fy - 2), (fx + int(W * 0.022), fy - 2),
                   (fx + dx + int(W * 0.03), fy + int(H * 0.032)), (fx + dx - int(W * 0.015), fy + int(H * 0.032))], fill=140)
        sh = sh.filter(ImageFilter.GaussianBlur(max(10, int(H * 0.02))))
        a = np.asarray(out).astype(np.float32)
        a *= (1.0 - np.asarray(sh, dtype=np.float32)[..., None] / 255.0 * 0.36)
        out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    return out, fn


def compose_char_on_scene(plate_path, char_path, steps_dir, x_frac, gy_frac, ratio, scale_canvas=1.5):
    """B 双画流水线：画布 1.5× 扩容留足人物像素 → 高分灰底人物抠图直贴 → 输出溶边遮罩。"""
    import fusion
    im = Image.open(plate_path).convert("RGB")
    W, H = im.size
    if scale_canvas > 1.01 and max(W, H) < 1600:
        nw = max(512, (int(round(W * scale_canvas)) // 8) * 8)
        nh = max(512, (int(round(H * scale_canvas)) // 8) * 8)
        im = im.resize((nw, nh), Image.LANCZOS)
        W, H = nw, nh
    matte = cutout.make_matte(char_path, backend="birefnet", crop=True)
    if isinstance(matte, str):
        matte = Image.open(matte)
    fg = matte.convert("RGBA")
    bb = fg.split()[3].getbbox()
    if bb:
        fg = fg.crop(bb)
    target_h = max(64, int(H * max(0.20, min(0.85, ratio or 0.40))))
    target_w = max(32, int(fg.width * (target_h / float(max(fg.height, 1)))))
    fg = fg.resize((target_w, target_h), Image.LANCZOS)
    cx = int(W * max(0.15, min(0.85, x_frac or 0.36)))
    feet_y = min(H, int(H * max(0.45, min(0.96, gy_frac or 0.88))))
    px = max(0, min(W - target_w, cx - target_w // 2))
    py = max(0, feet_y - target_h)
    try:
        fg, _ = fusion.lowfreq_match(fg, im, (px, py, px + target_w, py + target_h), weight=0.28)
    except Exception:
        pass
    alpha_soft = fg.split()[3].filter(ImageFilter.GaussianBlur(1.2))
    comp = im.copy()
    comp.paste(fg.convert("RGB"), (px, py), alpha_soft)
    pre_path = os.path.join(steps_dir, "02_pre_melt.png")
    comp.save(pre_path)
    mask = Image.new("L", (W, H), 0)
    mask.paste(fg.split()[3], (px, py))
    mask = mask.filter(ImageFilter.MaxFilter(15)).filter(ImageFilter.GaussianBlur(8))
    return pre_path, mask


def run_b_stage(c, cur, steps_dir, char_loras, char_neg, mf, run_job, dedup_join, merge_neg):
    """B 双画流水线人物阶段：灰底高分人物卡 → 1.5× 画布 BiRefNet 直贴 → 返回溶边输入与 0.52 重打光提示。"""
    p = dedup_join(c["char"], "full body standing, solid neutral mid-grey background, clean studio lighting")
    neg = merge_neg(char_neg, "complex background, scenery, outdoors, furniture, floor shadow, white background")
    job = {"prompt": p, "negative": neg, "width": 768, "height": 1152, "steps": min(28, c["steps"]),
           "cfg": c["cfg"], "seed": c["seed"] + 1, "loras": char_loras, "prefix": "REPROJ_bchar", "mode": "t2i", "save_to": "paper"}
    if c["model"]:
        job["model"] = c["model"]
    char_raw = run_job(job, "独立人物卡")
    pre, mask = compose_char_on_scene(cur, char_raw, steps_dir, c["x"], c["ground_y"], c["ratio"], scale_canvas=1.5)
    mf["mask"] = {"strategy": "standalone_birefnet_melt_1.5x", "cov_pct": 0.0, "pose_json": ""}
    ls = "warm key light from the left, " if c["light"] == "left" else ("warm key light from the right, " if c["light"] == "right" else "")
    btxt = dedup_join(c["char"], c["scene"], ls + "bright rim backlight wrapping hair and shoulders, ambient bounce shading, integrated into room lighting")
    return pre, mask, btxt, 0.52


def upscale_plate_safe(plate_path, steps_dir, scale=1.5):
    """L 流水线出板后安全扩充画幅（先走 mem_plan 卸底模跑 AnimeSharp，失败自动退回 Lanczos 防 OOM）。"""
    im = Image.open(plate_path).convert("RGB")
    W, H = im.size
    if scale <= 1.01 or max(W, H) >= 1600:
        return plate_path, W, H
    nw = min(2048, max(512, (int(round(W * scale)) // 8) * 8))
    nh = min(2048, max(512, (int(round(H * scale)) // 8) * 8))
    sr = hp.sr_upscale(im)
    base = sr if sr is not None else im
    up = base.resize((nw, nh), Image.LANCZOS)
    if sr is None:
        up = up.filter(ImageFilter.UnsharpMask(radius=1.1, percent=30, threshold=2))
    dst = os.path.join(steps_dir, "01b_upscaled.png")
    up.save(dst)
    print("[upscale] %dx%d -> %dx%d (%s)" % (W, H, nw, nh, "AnimeSharp" if sr is not None else "Lanczos"), flush=True)
    return dst, nw, nh


def proportion_cue(scene_text, char_text, ratio):
    """根据默认/选定人物占比（ratio=人物占画高）为 01_plate 补充景别提示；auto / <=0 时由模型自定，不注入。"""
    if not str(char_text or "").strip() or ratio is None or str(ratio).strip().lower() == "auto":
        return ""
    r = float(ratio)
    if r <= 0:
        return ""
    joined = (str(scene_text or "") + " " + str(char_text or "")).lower()
    if any(k in joined for k in ("close-up", "portrait", "upper body", "cowboy shot", "wide shot", "very wide", "distant view")):
        return ""
    if r <= 0.22:
        cue = "very wide shot, full body standing, distant small figure, expansive scenery surrounding character"
    elif r <= 0.29:
        cue = "wide shot, full body standing, figure occupying a quarter of frame height, expansive background visible"
    elif r <= 0.38:
        cue = "wide medium-long shot, full body standing, figure occupying one third of frame height, spacious environmental surroundings"
    else:
        cue = "medium full shot, full body standing, clear environmental background"
    # 已有显式全身/中景景别词时只保留占比与留白描述，不再叠第二套景别词
    if any(k in joined for k in ("full body", "full-body", "medium shot", "medium full", "long shot", "head-to-toe",
                                 "waist-up", "knee-up", "three-quarter", "bust shot", "chest up")):
        cue = ", ".join(s for s in cue.split(", ") if "shot" not in s and "full body" not in s)
    return cue


def refine_hands_on_image(img_path, loras=None, seed=0, model=""):
    """对单图出图结果做 SDPose 检手 + AnimeSharp 放大局部精修，返回修复手部数量。"""
    if not os.path.isfile(img_path):
        return 0
    W, H = Image.open(img_path).size
    raw = detect_safe(img_path)
    pjson = raw.get("json")
    if not pjson:
        return 0
    fb = face_box_from_pose(pjson, W, H)
    hbs = hand_boxes_from_pose(pjson, W, H, face_box=fb)
    if not hbs:
        return 0
    neg = "extra fingers, fused fingers, missing fingers, deformed hand, six fingers, mutated hands, bad anatomy, text, watermark, blurry"
    prompt = "masterpiece, best quality, delicate anime hand, five separate slender fingers, clean finger joints, same art style"
    cur, fixed = img_path, 0
    with tempfile.TemporaryDirectory(prefix="t2i_hand_") as tmpd:
        cur = os.path.join(tmpd, "src.png")
        Image.open(img_path).convert("RGB").save(cur)
        for idx, hb in enumerate(hbs):
            try:
                cur, _ = hp.repaint(cur, hb, prompt, neg, denoise=0.56, scale=3.5, pad=0.55,
                                    steps=24, cfg=5.2, seed=(int(seed) or 1000) + 10 + idx,
                                    loras=(loras or [])[:2], tag="t2ihand%d" % (idx + 1), max_side=768, model=model or "")
                fixed += 1
            except Exception as e:  # noqa: BLE001
                print("[t2i_handfix] 跳过:", str(e)[:80], flush=True)
        if fixed and os.path.isfile(cur):
            Image.open(cur).convert("RGB").save(img_path)
    return fixed