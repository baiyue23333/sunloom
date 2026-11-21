# -*- coding: utf-8 -*-
"""B · V1.5 自然比例探测与关键点对齐：先让模型看空景试站 10 步定尺度与站位，再按解剖关键点缩放拼贴高清人物卡。"""
import json
import math
import os
import re
import time
import urllib.request
from PIL import Image, ImageDraw

from comfy_paths import COMFY_IN as CI, COMFY_OUT as CO
import prompt_slim as slim
import reproj_parts as parts
import sdp_body_mask as sbm

COMFY = os.environ.get("STATION_COMFY", os.environ.get("COMFY_API", "http://127.0.0.1:8188"))
LLLITE = "anima-lllite-regional-exp-v3.safetensors"


def _comfy(path, payload=None, timeout=120):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(COMFY + path, data=data, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def run_i2i_lllite(ref_path, box, prompt, negative, width, height, steps, cfg, seed, denoise, loras, prefix,
                   model="", ll_strength=0.80, ll_end=0.45, timeout=600):
    """无骨架时用 LLLite 区域补丁引导同生站位。"""
    ts = f"{int(time.time() * 1000)}_{os.getpid()}"
    ref_name, lll_name = f"bchar_ref_{ts}.png", f"bchar_lll_{ts}.png"
    Image.open(ref_path).convert("RGB").resize((width, height), Image.LANCZOS).save(os.path.join(CI, ref_name))
    rmask = Image.new("RGB", (width, height), (255, 255, 255))
    ImageDraw.Draw(rmask).rectangle(box, fill=(220, 30, 30))
    rmask.save(os.path.join(CI, lll_name))
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": model or "anima-base-v1.0.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_06b_base.safetensors", "type": "stable_diffusion", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "4": {"class_type": "LoadImage", "inputs": {"image": ref_name}},
        "12": {"class_type": "ImageScale", "inputs": {"image": ["4", 0], "upscale_method": "lanczos", "width": width, "height": height, "crop": "center"}},
        "13": {"class_type": "VAEEncode", "inputs": {"pixels": ["12", 0], "vae": ["3", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
    }
    m_out, nid = ["1", 0], 20
    for item in (loras or []):
        name, w = str(item.get("name") or "").strip(), float(item.get("weight", 1.0))
        if name and w > 0:
            g[str(nid)] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": m_out, "lora_name": name, "strength_model": w}}
            m_out, nid = [str(nid), 0], nid + 1
    if ll_strength > 0:
        try:
            g["30"] = {"class_type": "ModelPatchLoader", "inputs": {"name": LLLITE}}
            g["31"] = {"class_type": "LoadImage", "inputs": {"image": lll_name}}
            g["32"] = {"class_type": "AnimaLLLiteApply", "inputs": {"model": m_out, "model_patch": ["30", 0], "image": ["31", 0], "strength": float(ll_strength), "start_percent": 0.0, "end_percent": float(ll_end)}}
            m_out = ["32", 0]
        except Exception:
            pass
    g["9"] = {"class_type": "KSampler", "inputs": {"model": m_out, "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["13", 0], "seed": int(seed), "steps": int(steps), "cfg": float(cfg), "sampler_name": "euler", "scheduler": "simple", "denoise": float(denoise)}}
    g["10"] = {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}}
    g["11"] = {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": prefix}}
    pid = _comfy("/prompt", {"prompt": g, "client_id": "sunloom_bchar"})["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = _comfy("/history/" + pid)
        if pid in h:
            ent = h[pid]
            if (ent.get("status") or {}).get("status_str") == "error":
                raise RuntimeError("b_char cogen error: %s" % str(ent.get("status"))[:240])
            for node in (ent.get("outputs") or {}).values():
                for im in node.get("images") or []:
                    p = os.path.join(CO, im.get("subfolder", ""), im.get("filename", ""))
                    if os.path.isfile(p):
                        return p
            raise RuntimeError("b_char cogen produced no image")
        time.sleep(1.5)
    raise TimeoutError("b_char cogen timeout")


def _best_person_pts(pose_json):
    """从 SDPose JSON 中挑出有效点最多、纵向跨度最大的人物骨架。"""
    if not pose_json or not os.path.isfile(pose_json):
        return [], 0, 0
    d = json.load(open(pose_json, encoding="utf-8"))
    if isinstance(d, dict):
        d = [d]
    pw = int(d[0].get("canvas_width") or 0)
    ph = int(d[0].get("canvas_height") or 0)
    best_pts, best_score = [], (-1, -1.0)
    for item in d:
        for p in (item.get("people") or []):
            arr = p.get("pose_keypoints_2d") or []
            pts = [(float(arr[i]), float(arr[i + 1]), float(arr[i + 2])) for i in range(0, len(arr) - 2, 3)]
            ok = [pt for pt in pts if pt[2] > 0.20 and pt[0] >= 0 and pt[1] >= 0]
            if not ok:
                continue
            ys = [pt[1] for pt in ok]
            sc = (len(ok), max(ys) - min(ys))
            if sc > best_score:
                best_score = sc
                best_pts = pts
    return best_pts, pw, ph


def _vpt(pts, idx, sx=1.0, sy=1.0, thr=0.20):
    if idx >= len(pts):
        return None
    x, y, s = pts[idx]
    if s > thr and x >= 0 and y >= 0:
        return (x * sx, y * sy)
    return None


def _mid(pts, i1, i2, sx=1.0, sy=1.0):
    a, b = _vpt(pts, i1, sx, sy), _vpt(pts, i2, sx, sy)
    if a and b:
        return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)
    return a or b


def analyze_skeleton(pose_json, W, H):
    """提取颈/肩/胯/膝/踝中心、估计全身高比例及朝向/坐站姿态标签。"""
    pts, pw, ph = _best_person_pts(pose_json)
    if not pts:
        return {"ok": False}
    sx = (W / float(pw)) if pw > 0 else 1.0
    sy = (H / float(ph)) if ph > 0 else 1.0
    ok_pts = [(p[0] * sx, p[1] * sy) for p in pts if p[2] > 0.20 and p[0] >= 0 and p[1] >= 0]
    if len(ok_pts) < 8:
        return {"ok": False, "valid_count": len(ok_pts)}

    neck = _vpt(pts, sbm.NECK, sx, sy) or _mid(pts, sbm.RS, sbm.LS, sx, sy)
    nose = _vpt(pts, sbm.NOSE, sx, sy)
    reye, leye = _vpt(pts, sbm.REYE, sx, sy), _vpt(pts, sbm.LEYE, sx, sy)
    rs, ls = _vpt(pts, sbm.RS, sx, sy), _vpt(pts, sbm.LS, sx, sy)
    hips = _mid(pts, sbm.RH, sbm.LH, sx, sy)
    knees = _mid(pts, sbm.RK, sbm.LK, sx, sy)
    ankles = _mid(pts, sbm.RA, sbm.LA, sx, sy)

    sw = math.hypot(rs[0] - ls[0], rs[1] - ls[1]) if (rs and ls) else 0.0
    top_candidates = [p[1] for p in (nose, reye, leye, neck) if p]
    if top_candidates and neck:
        head_pad = max(12.0, (neck[1] - min(top_candidates)) * 1.15, sw * 0.35)
        top_y = max(0.0, min(top_candidates) - head_pad * 0.65)
    else:
        top_y = max(0.0, min(p[1] for p in ok_pts) - H * 0.04)

    span_ankle = (ankles[1] - neck[1]) if (neck and ankles and ankles[1] > neck[1] + 20) else 0.0
    span_knee = (knees[1] - neck[1]) if (neck and knees and knees[1] > neck[1] + 16) else 0.0
    span_hip = (hips[1] - neck[1]) if (neck and hips and hips[1] > neck[1] + 12) else 0.0
    if not (span_ankle or span_knee or span_hip):
        return {"ok": False, "valid_count": len(ok_pts)}

    ankles_in = bool(ankles and 0.15 * H <= ankles[1] <= 0.99 * H and span_ankle > 0)
    if ankles_in:
        ratio_est = max(0.20, min(0.92, (ankles[1] - top_y + H * 0.03) / float(H)))
        gy_est = min(0.98, (ankles[1] + H * 0.025) / float(H))
    elif span_knee > 0:
        ratio_est = max(0.22, min(1.05, ((knees[1] - top_y) / 0.72) / float(H)))
        gy_est = min(1.12, top_y / float(H) + ratio_est)
    else:
        ratio_est = max(0.22, min(1.15, ((hips[1] - top_y) / 0.47) / float(H)))
        gy_est = min(1.20, top_y / float(H) + ratio_est)

    cx_vals = [p[0] for p in (neck, hips, ankles) if p]
    cx = sum(cx_vals) / float(len(cx_vals)) if cx_vals else (W * 0.5)

    # 仅在明显特征满足时推断坐站与背向提示词，供「选项 2」对照
    facing_cue = ""
    if not nose and not reye and not leye and rs and ls and (rs[0] > ls[0] + sw * 0.25):
        facing_cue = "from behind, back view"
    posture_cue = ""
    if hips and knees and span_hip > 20 and (knees[1] - hips[1]) < span_hip * 0.58:
        posture_cue = "sitting"
    else:
        ra, la = _vpt(pts, sbm.RA, sx, sy), _vpt(pts, sbm.LA, sx, sy)
        if ra and la and span_hip > 20 and abs(ra[0] - la[0]) > span_hip * 0.42:
            posture_cue = "walking"

    return {
        "ok": True,
        "valid_count": len(ok_pts),
        "cx": cx,
        "top_y": top_y,
        "neck": neck,
        "hips": hips,
        "knees": knees,
        "ankles": ankles if ankles_in else None,
        "span_ankle": span_ankle if ankles_in else 0.0,
        "span_knee": span_knee,
        "span_hip": span_hip,
        "ratio_est": round(ratio_est, 3),
        "ground_y_est": round(gy_est, 3),
        "x_est": round(max(0.10, min(0.90, cx / float(W))), 3),
        "posture_cue": posture_cue,
        "facing_cue": facing_cue,
    }


def infer_head_facing(pose_json, W, H):
    """SDPose 18 点（鼻/双眼/双耳/双肩）→ 6 档朝向；无骨架返回空串。"""
    pts, pw, ph = _best_person_pts(pose_json)
    if not pts:
        return ""
    sx = (W / float(pw)) if pw > 0 else 1.0
    sy = (H / float(ph)) if ph > 0 else 1.0

    def g(i):
        return _vpt(pts, i, sx, sy)

    nose, reye, leye = g(sbm.NOSE), g(sbm.REYE), g(sbm.LEYE)
    rear, lear, rs, ls = g(sbm.REAR), g(sbm.LEAR), g(sbm.RS), g(sbm.LS)
    eyes = [p for p in (reye, leye) if p]
    if not eyes and not nose:
        return "back"
    if rear and lear:
        span = max(12.0, math.hypot(rear[0] - lear[0], rear[1] - lear[1]))
    elif eyes:
        span = max(12.0, math.hypot(eyes[0][0] - eyes[-1][0], eyes[0][1] - eyes[-1][1]) * 2.2)
    elif rs and ls:
        span = max(16.0, math.hypot(rs[0] - ls[0], rs[1] - ls[1]) * 0.55)
    else:
        span = 48.0
    score = 0.0
    if nose and eyes:
        mid = sum(p[0] for p in eyes) / float(len(eyes))
        score += max(-2.4, min(2.4, (nose[0] - mid) / (span * 0.32))) * 1.6
    if rear and not lear:
        score += 2.2
    elif lear and not rear:
        score -= 2.2
    if reye and not leye:
        score += 1.2
    elif leye and not reye:
        score -= 1.2
    if nose and rear and lear:
        # 3/4 侧转时鼻子靠近转向侧耳朵（面向画面右 → 右耳更近）
        dr = abs(nose[0] - lear[0]) - abs(nose[0] - rear[0])
        score += max(-2.0, min(2.0, -dr / (span * 0.55))) * 1.2
    amt, two_eyes = abs(score), bool(reye and leye)
    if amt < 0.9 or (rear and lear and two_eyes and amt < 1.4):
        return "front"
    kind = "three_quarter" if (two_eyes or amt < 1.2) else "profile"
    return "%s_%s" % (kind, "right" if score > 0 else "left")


def _clean_probe_scene(scene_text):
    s = re.sub(r"\(\s*(?:empty scene|no people|no humans)[^)]*\)", "", str(scene_text or ""), flags=re.I)
    s = re.sub(r"\b(?:empty scene|no people|no humans)\b", "", s, flags=re.I)
    return re.sub(r"\s*,\s*,+", ", ", s).strip(" ,")


def probe_natural_scale(bg_draft, char_text, scene_text, neg_scene, scene_lora, env_weight,
                        W, H, steps_dir, seed, run_job, cfg=5.5, model=""):
    """让模型看着刚画出的空景底稿跑 10 步轻量 i2i 试站，测量自然透视身高与站位。"""
    contour = slim.contour_summary(char_text) if char_text else "1girl, solo"
    clean_sc = _clean_probe_scene(scene_text)
    probe_pos = ", ".join(x for x in (
        "(1girl, solo, standing in scene, natural perspective scale, realistic human height:1.22)",
        contour, clean_sc
    ) if x)
    probe_neg = ", ".join(x for x in (
        str(neg_scene or "").strip(),
        "2girls, multiple girls, crowd, extra people, giant, miniature, doll, close-up portrait"
    ) if x)
    sl_w = round(min(0.45, max(0.0, float(env_weight or 0.70) * 0.55)), 2)
    probe_loras = [{"name": scene_lora, "weight": sl_w}] if (scene_lora and sl_w > 0) else []
    probe_dst = os.path.join(steps_dir, "00_scale_probe.png")

    for attempt, (dn, sd) in enumerate([(0.76, int(seed) + 5), (0.84, int(seed) + 15)]):
        job = {
            "prompt": probe_pos, "negative": probe_neg, "width": W, "height": H,
            "steps": 10, "cfg": float(cfg or 5.5), "seed": sd, "loras": probe_loras,
            "prefix": "BCHAR_PROBE", "mode": "i2i", "reference": os.path.abspath(bg_draft), "denoise": dn, "save_to": "paper",
            **({"model": model} if model else {}),
        }
        res_p = run_job(job, "自然比例探测(%d)" % (attempt + 1))
        Image.open(res_p).convert("RGB").save(probe_dst)
        pj = parts.detect_safe(probe_dst).get("json")
        info = analyze_skeleton(pj, W, H)
        if info.get("ok"):
            print("[b_char] scale_probe PASS dn=%.2f -> ratio=%.3f gy=%.3f x=%.3f (%s %s)" % (
                dn, info["ratio_est"], info["ground_y_est"], info["x_est"],
                info.get("posture_cue") or "-", info.get("facing_cue") or "-"
            ), flush=True)
            return {"ok": True, "image": probe_dst, "denoise": dn, "info": info}

    fb_ratio = 0.48 if H > W else 0.38
    print("[b_char] scale_probe 未检出完整骨架，温和回退 ratio=%.2f" % fb_ratio, flush=True)
    return {
        "ok": False, "image": probe_dst, "denoise": 0.84,
        "info": {"ok": False, "ratio_est": fb_ratio, "ground_y_est": 0.90, "x_est": 0.38, "posture_cue": "", "facing_cue": ""},
    }


def place_matte_by_probe(matte_uncropped, card_pose_json, card_size, probe_res, W, H,
                         x_locked=False, x_hint=0.34, fallback_ratio=0.48, fallback_gy=0.90):
    """按空景探测骨架与人物卡骨架的同部位跨度精准缩放，再对齐颈部/脚踝坐标。"""
    alpha = matte_uncropped.split()[3]
    bbox = alpha.getbbox() or (0, 0, matte_uncropped.width, matte_uncropped.height)
    matte = matte_uncropped.crop(bbox)
    cw_raw, ch_raw = card_size
    bx0, by0 = bbox[0], bbox[1]

    info = (probe_res or {}).get("info") or {}
    card_sk = analyze_skeleton(card_pose_json, cw_raw, ch_raw)

    def _shift(pt):
        return (pt[0] - bx0, pt[1] - by0) if pt else None

    anchor = "fallback"
    scale = None
    if info.get("ok") and card_sk.get("ok"):
        if info.get("span_ankle") and card_sk.get("span_ankle"):
            scale = info["span_ankle"] / float(card_sk["span_ankle"])
            anchor = "ankles"
        elif info.get("span_knee") and card_sk.get("span_knee"):
            scale = info["span_knee"] / float(card_sk["span_knee"])
            anchor = "knees"
        elif info.get("span_hip") and card_sk.get("span_hip"):
            scale = info["span_hip"] / float(card_sk["span_hip"])
            anchor = "hips"

    if scale is None:
        r_target = info.get("ratio_est") if info.get("ok") else float(fallback_ratio or (0.48 if H > W else 0.38))
        scale = (H * max(0.24, min(0.95, r_target))) / float(max(1, matte.height))
        anchor = "ratio_est" if info.get("ok") else "fallback"

    th = max(max(96, int(H * 0.24)), min(int(H * 1.35), int(round(matte.height * scale))))
    scale = th / float(max(1, matte.height))
    tw = max(32, int(round(matte.width * scale)))
    fg = matte.resize((tw, th), Image.LANCZOS)

    c_neck = _shift(card_sk.get("neck")) if card_sk.get("ok") else None
    c_ankles = _shift(card_sk.get("ankles")) if card_sk.get("ok") else None
    c_cx = (card_sk["cx"] - bx0) if card_sk.get("ok") else (matte.width * 0.5)

    cx_target = int(W * max(0.12, min(0.88, float(x_hint or 0.34)))) if x_locked else int(info.get("cx") or W * 0.38)
    px = max(0, min(max(0, W - tw), int(round(cx_target - c_cx * scale))))

    if anchor == "ankles" and info.get("ankles") and c_ankles:
        py = int(round(info["ankles"][1] - c_ankles[1] * scale))
        if py < int(0.02 * H) and (py + th) < int(0.96 * H):
            py = int(0.02 * H)
        if py + th > H:
            py = min(py, H - th) if th <= int(H * 0.96) else py
    elif anchor in ("knees", "hips") and info.get("neck") and c_neck:
        py = int(round(info["neck"][1] - c_neck[1] * scale))
    else:
        gy_target = info.get("ground_y_est") if info.get("ok") else float(fallback_gy or 0.90)
        py = int(round(H * min(0.98, gy_target) - th))
    py = max(-int(th * 0.08), py)
    if (info.get("top_y", H * 0.1) >= 0.02 * H) and py < int(0.02 * H) and anchor in ("ankles", "ratio_est", "fallback"):
        py = int(0.02 * H)

    feet_y = py + th
    box = (max(0, px), max(0, py), min(W, px + tw), min(H, feet_y))
    lpad = int(tw * 0.12)
    lll_box = (max(0, px - lpad), max(0, py - 8), min(W, px + tw + lpad), min(H, feet_y + 6))
    used_ratio = round(th / float(H), 3)
    used_gy = round(min(0.98, feet_y / float(H)), 3)
    used_x = round(max(0.10, min(0.90, (px + tw * 0.5) / float(W))), 3)
    note = f"{anchor}:ratio={used_ratio},gy={used_gy},x={used_x}"
    print("[b_char] probe_align", note, flush=True)
    return fg, px, py, box, lll_box, used_ratio, used_gy, used_x, note


def place_fixed_matte(matte, ratio, gy, x, W, H):
    """按显式固定占比与站位缩放裁切好的前景人物卡。"""
    ur, ug, ux = float(ratio or 0.42), float(gy or 0.90), float(x or 0.36)
    th = max(64, int(H * max(0.20, min(0.85, ur))))
    tw = max(32, int(matte.width * (th / float(max(matte.height, 1)))))
    fg = matte.resize((tw, th), Image.LANCZOS)
    px = max(0, min(W - tw, int(W * max(0.15, min(0.85, ux))) - tw // 2))
    py = max(0, min(H, int(H * max(0.45, min(0.96, ug)))) - th)
    box = (px, py, px + tw, py + th)
    lpad = int(tw * 0.12)
    lll_box = (max(0, px - lpad), max(0, py - 8), min(W, px + tw + lpad), min(H, py + th + 6))
    return fg, px, py, box, lll_box, ur, ug, ux


def extra_posture_cues(c, pose_mode, pinfo, facing_cue):
    """选项 2：若开启 probe_posture 且用户未手写坐站/背向，从探测图借入朝向与自然姿态。"""
    ex_p, ex_f = "", ""
    if bool(c.get("probe_posture", False)) and pose_mode == "none" and (pinfo or {}).get("ok"):
        if pinfo.get("facing_cue") and not facing_cue and not re.search(r"\b(from behind|back view)\b|背影|背面", c["char"], re.I):
            ex_f = pinfo["facing_cue"]
        if pinfo.get("posture_cue") and not re.search(r"\b(sit|sitting|kneel|lying|jump|walk|walking|run|running)\b|坐|站|走|跑|跳", c["char"], re.I):
            ex_p = pinfo["posture_cue"]
    return ex_p, ex_f


def build_contact_canvas(bg_draft, card_w, card_h, cx, gy, ratio, out_path=None):
    """按空景目标站位裁出对应透视区，提取去色淡环境接触描边叠在中性灰底上，供人物卡生成贴合椅面/地面/栏杆。"""
    import numpy as np
    from PIL import ImageFilter

    bg = Image.open(bg_draft).convert("L").filter(ImageFilter.GaussianBlur(1.3))
    W, H = bg.size
    h_bg = max(64.0, float(ratio or 0.40) * H)
    h_card = 0.76 * card_h
    s = h_bg / h_card
    crop_w, crop_h = card_w * s, card_h * s
    x_bg, y_top_bg = float(cx or 0.40) * W, float(gy or 0.88) * H - h_bg
    x0 = int(round(x_bg - crop_w * 0.50))
    y0 = int(round(y_top_bg - 0.16 * crop_h))
    arr = np.asarray(bg, dtype=np.float32)
    xs = np.clip(np.linspace(x0, x0 + crop_w - 1, card_w).round().astype(int), 0, W - 1)
    ys = np.clip(np.linspace(y0, y0 + crop_h - 1, card_h).round().astype(int), 0, H - 1)
    g = arr[np.ix_(ys, xs)]
    gx = np.abs(np.diff(g, axis=1, prepend=g[:, :1]))
    gy_d = np.abs(np.diff(g, axis=0, prepend=g[:1, :]))
    edge = np.clip((np.hypot(gx, gy_d) - 7.0) / 28.0, 0.0, 1.0)
    canvas = np.clip(144.0 - edge * 50.0, 60.0, 180.0).astype(np.uint8)
    out = Image.fromarray(np.stack([canvas, canvas, canvas], axis=-1), "RGB")
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        out.save(out_path)
        return out_path
    return out
