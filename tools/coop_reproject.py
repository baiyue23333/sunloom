# -*- coding: utf-8 -*-
"""重映工作台：一次打底 → 人物高分重绘 → 脸/手局部精修 → 接触阴影。

全链路吃进工作台前端的真实正/负向、构图比例、尺寸与自选画师 LoRA，
不写死特定角色或画风。站台 /api/coop mode=reproject 调用。
"""
import argparse
import json
import os
import shutil
import sys
import time
import urllib.request

from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fusion
import hand_precise as hp
import mem_plan
import reproj_parts as parts
import reproj_provenance as rp

API = os.environ.get("SUNLOOM_API", "http://127.0.0.1:8770")
CI = hp.CI


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def _get(url):
    return json.loads(urllib.request.urlopen(url, timeout=60).read())


def _align8(v, lo=256, hi=2048):
    v = max(lo, min(hi, int(round(v))))
    return max(lo, v - (v % 8))


def _merge_loras(*groups):
    out, seen = [], {}
    for grp in groups:
        for item in (grp or []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            try:
                w = round(float(item.get("weight", 1.0)), 3)
            except (TypeError, ValueError):
                w = 1.0
            if w <= 0:
                continue
            if name in seen:
                idx = seen[name]
                if w > out[idx]["weight"]:
                    out[idx]["weight"] = w
            else:
                seen[name] = len(out)
                out.append({"name": name, "weight": w})
    return out


def _merge_neg(*parts_in):
    seen, items = set(), []
    for part in parts_in:
        for seg in str(part or "").split(","):
            s = seg.strip()
            k = s.lower()
            if s and k not in seen:
                seen.add(k)
                items.append(s)
    return ", ".join(items)


def _run_job(body, tag, timeout=900):
    jid = _post(API + "/api/run", body)["job_id"]
    t0 = time.time()
    last_p = -1.0
    while time.time() - t0 < timeout:
        time.sleep(1.5)
        st = _get(API + "/api/job/" + jid)
        p = float(st.get("progress") or 0.0)
        if p - last_p >= 0.05:
            last_p = p
            print("PROGRESS %.2f" % min(0.99, p), flush=True)
        status = st.get("status")
        if status == "done":
            imgs = (st.get("result") or {}).get("images") or []
            if not imgs:
                raise RuntimeError("%s: 输出为空" % tag)
            print("PROGRESS 1.00", flush=True)
            return imgs[0]
        if status == "error":
            raise RuntimeError("%s: %s" % (tag, str(st.get("result"))[:300]))
    raise TimeoutError("%s 超时" % tag)


def _repaint_body(plate_path, mask, steps_dir, char_prompt, neg_char, char_loras, steps, cfg, seed, style_suffix="", mf=None, model="", denoise_override=0.0):
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
    tw = _align8(cw * scale, min_w, 1024)
    th = _align8(ch * scale, 256, 1024)
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
    Image.merge("RGB", (mask_big, mask_big, mask_big)).save(os.path.join(CI, mask_name))
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
    res_path = _run_job(job_body, "人物重绘")

    back = Image.open(res_path).convert("RGB").resize((cw, ch), Image.LANCZOS)
    soft = crop_mask.filter(ImageFilter.GaussianBlur(max(3, int(min(cw, ch) * 0.012))))
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


def _load_cfg(a):
    cfg = {}
    if a.config and os.path.isfile(a.config):
        cfg = json.load(open(a.config, encoding="utf-8")) or {}
    return {
        "scene": cfg.get("scene") or a.scene,
        "char": cfg.get("char") if cfg.get("char") is not None else a.char,
        "neg_scene": cfg.get("neg_scene") or "",
        "neg_char": cfg.get("neg_char") or "",
        "face_prompt": cfg.get("face_prompt") or "",
        "hand_prompt": cfg.get("hand_prompt") or "",
        "width": _align8(cfg.get("width") or a.width or 1216, 512, 2048),
        "height": _align8(cfg.get("height") or a.height or 832, 512, 2048),
        "steps": min(36, max(18, int(cfg.get("steps") or 26))),
        "cfg": float(cfg.get("cfg") or 5.5),
        "seed": int(cfg.get("seed") or a.seed or 2026),
        "model": str(cfg.get("model") or "").strip(),
        "scene_lora": str(cfg.get("scene_lora") or "").strip(),
        "env_weight": float(cfg.get("env_weight") or 0.70),
        "char_lora": str(cfg.get("char_lora") or "").strip(),
        "char_weight": float(cfg.get("char_weight") or 0.85),
        "extra_loras": cfg.get("extra_loras") or [],
        "ratio": float(cfg.get("ratio") or 0.34),
        "ground_y": float(cfg.get("ground_y") or 0.88),
        "x": float(cfg.get("x") or 0.34),
        "expand_notes": cfg.get("expand_notes") or [],
        "client_meta": cfg.get("client_meta") or {},
        "style_suffix": cfg.get("style_suffix"),
        "face_suffix": cfg.get("face_suffix"),
        "hand_suffix": cfg.get("hand_suffix"),
        "keep_intermediates": bool(cfg.get("keep_intermediates")),
        "light": str(cfg.get("light") or "left").strip().lower(),
        "pipeline": str(cfg.get("pipeline") or "a").strip().lower(),
    }


def _split_clauses_safe(s):
    out, buf, depth = [], [], 0
    for ch in s or "":
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
        if ch == "," and depth == 0:
            part = "".join(buf).strip()
            if part:
                out.append(part)
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def _dedup_join(*chunks):
    seen, out = set(), []
    for chunk in chunks:
        for seg in _split_clauses_safe(chunk):
            key = seg.lower()
            if key not in seen:
                seen.add(key)
                out.append(seg)
    return ", ".join(out)


_proportion_cue = parts.proportion_cue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="")
    ap.add_argument("--scene", default="detailed anime illustration background")
    ap.add_argument("--char", default="")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--width", type=int, default=1216)
    ap.add_argument("--height", type=int, default=832)
    ap.add_argument("--out", default="")
    ap.add_argument("--keep-intermediates", action="store_true")
    a, _unknown = ap.parse_known_args()

    c = _load_cfg(a)
    if a.keep_intermediates:
        c["keep_intermediates"] = True
    out = a.out or os.path.join(ROOT, "SD-Picture", "reproject", str(c["seed"]))
    steps_dir = os.path.join(out, "steps")
    os.makedirs(steps_dir, exist_ok=True)
    with open(os.path.join(out, "plan.json"), "w", encoding="utf-8") as pf:
        json.dump(c, pf, ensure_ascii=False, indent=2)

    skip_names = {c["scene_lora"], c["char_lora"]} - {""}
    plate_extra = [
        {"name": x["name"], "weight": min(0.75, round(float(x.get("weight", 1.0)) * 0.80, 2))}
        for x in (c["extra_loras"] or [])
        if isinstance(x, dict) and str(x.get("name") or "").strip() not in skip_names
    ]
    is_b = (c["pipeline"] == "b" and bool(c["char"].strip()))
    is_m1 = (c["pipeline"] == "m1" and bool(c["char"].strip()))
    is_l = (c["pipeline"] in ("l", "m1") and bool(c["char"].strip()))
    plate_cw = 0.0 if is_b else (min(0.75 if is_l else 0.65, round(c["char_weight"] * (0.85 if is_l else 0.72), 2)) if (c["scene_lora"] or plate_extra) else min(0.85, c["char_weight"]))
    plate_loras = _merge_loras(
        [{"name": c["scene_lora"], "weight": c["env_weight"]}] if c["scene_lora"] else [],
        plate_extra,
        [{"name": c["char_lora"], "weight": plate_cw}] if (c["char_lora"] and plate_cw > 0) else [],
    )
    char_loras = _merge_loras(
        c["extra_loras"],
        [{"name": c["char_lora"], "weight": c["char_weight"]}] if c["char_lora"] else [],
        [{"name": c["scene_lora"], "weight": round(c["env_weight"] * 0.15, 2)}] if c["scene_lora"] else [],
    )
    detail_loras = _merge_loras(
        c["extra_loras"],
        [{"name": c["char_lora"], "weight": c["char_weight"]}] if c["char_lora"] else [],
    )

    prop_cue = _proportion_cue(c["scene"], c["char"], c["ratio"])
    plate_prompt = ("(empty scene, no people, no humans:1.3), " + c["scene"]) if is_b else (_dedup_join(c["scene"], c["char"], prop_cue) if c["char"].strip() else c["scene"])
    base_neg = "text, watermark, lowres, blurry, bad anatomy, extra fingers, deformed, sunflower hair ornament, sunflower hair ornament on head, sunflower in her hair, yellow petals in her hair, ai artifacts, jpeg artifacts, oversharpened, objects clipping into each other, furniture embedded in the wall, overlapping geometry"
    plate_neg = _merge_neg(c["neg_scene"], c["neg_char"]) or base_neg
    if is_b:
        plate_neg = _merge_neg(plate_neg, "1girl, 1boy, people, person, silhouette, figure")
    char_neg = _merge_neg(c["neg_char"], c["neg_scene"]) or base_neg
    suffixes = rp.resolve_suffixes(c)
    mf = rp.new_manifest(c, out, plate_prompt, plate_neg, char_neg, plate_loras, char_loras, detail_loras, suffixes)
    mp = mem_plan.Plan(context="coop")

    mp.schedule("anima", note="01_plate")
    print("[1/3] 出板 %dx%d loras=%d pipeline=%s" % (c["width"], c["height"], len(plate_loras), c["pipeline"]), flush=True)
    plate_steps = min(28, c["steps"])
    if is_l:
        import light_draft
        ld_path = light_draft.build_light_draft(os.path.join(steps_dir, "00_light_draft.png"),
                                                c["width"], c["height"], c["x"], c["ground_y"], c["ratio"], c["light"], c["seed"])
        plate_job = {
            "prompt": plate_prompt, "negative": plate_neg, "width": c["width"], "height": c["height"],
            "steps": plate_steps, "cfg": c["cfg"], "seed": c["seed"], "loras": plate_loras,
            "prefix": "REPROJ_light", "mode": "i2i", "reference": ld_path, "denoise": 0.84, "save_to": "paper",
        }
    else:
        plate_job = {
            "prompt": plate_prompt, "negative": plate_neg, "width": c["width"], "height": c["height"],
            "steps": plate_steps, "cfg": c["cfg"], "seed": c["seed"], "loras": plate_loras,
            "prefix": "REPROJ_plate", "mode": "t2i", "save_to": "paper",
        }
    if c["model"]:
        plate_job["model"] = c["model"]
    p1 = _run_job(plate_job, "出板")
    plate_path = os.path.join(steps_dir, "01_plate.png")
    shutil.copy2(p1, plate_path)
    rp.record_step(mf, "01_plate", status="ok", prompt=plate_prompt, negative=plate_neg,
                   steps=plate_steps, cfg=c["cfg"], seed=c["seed"], loras=plate_loras,
                   size=[c["width"], c["height"]], output=plate_path, sub_output=p1)
    mp.trim_py("01_plate_done")
    cur = plate_path

    if c["char"].strip():
        print("[2/3] 人物高分重绘 loras=%d pipeline=%s" % (len(char_loras), c["pipeline"]), flush=True)
        if is_b:
            cur, mask, body_txt, dn_ov = parts.run_b_stage(c, cur, steps_dir, char_loras, char_neg, mf, _run_job, _dedup_join, _merge_neg)
            use_loras = char_loras
        elif is_l:
            import light_draft
            cur, mask, body_txt, dn_ov, use_loras = light_draft.prepare_lm_body(c, cur, steps_dir, detail_loras, char_loras, mf, mp, _run_job, _dedup_join, is_m1)
        else:
            raw1 = parts.detect_safe(cur)
            mask, m_strat, m_cov = parts.build_body_mask(cur, raw1.get("json"), c["width"], c["height"], c["x"], c["ground_y"], c["ratio"])
            mf["mask"] = {"strategy": m_strat, "cov_pct": m_cov, "pose_json": raw1.get("json") or ""}
            body_txt, dn_ov, use_loras = c["char"], 0.0, char_loras
        mp.schedule("anima", note="02_body")
        cur = _repaint_body(cur, mask, steps_dir, body_txt, char_neg, use_loras if not is_b else char_loras,
                            c["steps"], c["cfg"], c["seed"], style_suffix=suffixes["style"], mf=mf, model=c["model"],
                            denoise_override=dn_ov)
        mp.trim_py("02_body_done")

        print("[3/3] 脸部/手部精修与合成", flush=True)
        cur_w, cur_h = Image.open(cur).size
        raw2 = parts.detect_safe(cur)
        pose2 = raw2.get("json")

        face_box = parts.face_box_from_pose(pose2, cur_w, cur_h)
        if face_box:
            f_ratio = face_box["h"] / float(cur_h)
            f_dn = 0.40 if f_ratio < 0.08 else (0.30 if f_ratio < 0.12 else 0.22)
            face_p = rp.append_suffix(c["face_prompt"].strip() or c["char"], suffixes["face"])
            print("[face] box=%s denoise=%.2f" % (face_box, f_dn), flush=True)
            try:
                cur, _ = hp.repaint(cur, face_box, face_p, char_neg, denoise=f_dn,
                                    scale=3.0, pad=0.45, steps=20, cfg=5.0,
                                    seed=c["seed"] + 2, loras=detail_loras,
                                    tag="face", max_side=832, shape="ellipse", model=c["model"])
                f_dst = os.path.join(steps_dir, "03_face.png")
                shutil.copy2(cur, f_dst)
                rp.record_step(mf, "03_face", status="ok", prompt=face_p, negative=char_neg,
                               denoise=f_dn, steps=20, cfg=5.0, seed=c["seed"] + 2,
                               loras=detail_loras, crop_box=face_box, output=f_dst)
                print("PROGRESS 0.45", flush=True)
            except Exception as e:  # noqa: BLE001
                rp.record_step(mf, "03_face", status="skipped", note=str(e)[:120], crop_box=face_box)
                print("[face] 跳过:", str(e)[:90], flush=True)

        hand_boxes = parts.hand_boxes_from_pose(pose2, cur_w, cur_h, face_box=face_box)
        hand_p = rp.append_suffix(c["hand_prompt"].strip() or "masterpiece, best quality, delicate anime hand, five separate slender fingers, clean finger joints", suffixes["hand"])
        hand_neg = _merge_neg("extra fingers, fused fingers, missing fingers, deformed hand, six fingers, mutated hands", char_neg)
        for idx, hb in enumerate(hand_boxes):
            print("[hand%d] %s %dx%d" % (idx + 1, hb.get("hand"), hb["w"], hb["h"]), flush=True)
            try:
                cur, _ = hp.repaint(cur, hb, hand_p, hand_neg, denoise=0.56,
                                    scale=3.5, pad=0.55, steps=24, cfg=5.2,
                                    seed=c["seed"] + 10 + idx, loras=detail_loras,
                                    tag="hand%d" % (idx + 1), max_side=768, model=c["model"])
                h_dst = os.path.join(steps_dir, "04_hands.png")
                shutil.copy2(cur, h_dst)
                rp.record_step(mf, "hand_%d" % (idx + 1), status="ok", hand=hb.get("hand"), prompt=hand_p,
                               negative=hand_neg, denoise=0.48, steps=20, cfg=5.0,
                               seed=c["seed"] + 10 + idx, loras=detail_loras, crop_box=hb, output=h_dst)
                print("PROGRESS %.2f" % (0.65 + 0.15 * (idx + 1)), flush=True)
            except Exception as e:  # noqa: BLE001
                rp.record_step(mf, "hand_%d" % (idx + 1), status="skipped", note=str(e)[:120], crop_box=hb)
                print("[hand%d] 跳过: %s" % (idx + 1, str(e)[:90]), flush=True)

        img = Image.open(cur).convert("RGB")
        img, fn = parts.apply_feet_shadow(img, pose2, light=("" if is_l else c["light"]), strength=(65 if is_l else 150))
        rp.record_step(mf, "05_shadow", status="ok", feet_count=fn)
        if fn:
            print("[shadow] %d 只脚落地阴影" % fn, flush=True)
    else:
        print("[2/3] 无人物提示词，跳过重绘", flush=True)
        print("[3/3] 完成合成", flush=True)
        img = Image.open(cur).convert("RGB")

    final = os.path.join(out, "comp.png")
    rp.save_comp_with_provenance(img, final, mf)
    rp.register_recipe(API, final, mf)
    mp.trim_py("finish")
    mem_plan.release(context="coop", reason="reproj_done")
    mp.save(out)
    print("PROGRESS 1.00", flush=True)
    print("done: " + final, flush=True)


if __name__ == "__main__":
    main()
