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
from functools import partial

from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fusion
import hand_precise as hp
import lens_policy
import mem_plan
import prompt_slim as slim
import reproj_body
import reproj_parts as parts
import reproj_provenance as rp
import scale_probe

API = os.environ.get("SUNLOOM_API", "http://127.0.0.1:8770")
CI = hp.CI

# L2 分阶段瘦身（纯文本规则在 tools/prompt_slim.py）
_merge_neg = slim.merge_neg
_dedup_join = slim.dedup_join
_split_clauses_safe = slim.split_clauses
_align8 = parts.align8

# 基础负向：出板只带家具/穿模，人物只带手部；两阶段不再互相污染
_BASE_NEG_CORE = ("text, watermark, lowres, blurry, bad anatomy, deformed, "
                  "long hair ornament, long hair ornament on head, sunflower in her hair, "
                  "yellow petals in her hair, ai artifacts, jpeg artifacts, oversharpened")
_BASE_NEG_PLATE = _BASE_NEG_CORE + ", objects clipping into each other, furniture embedded in the wall, overlapping geometry"
_BASE_NEG_CHAR = _BASE_NEG_CORE + ", extra fingers, fused fingers, missing fingers, deformed hands, bad hand anatomy"


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def _get(url):
    return json.loads(urllib.request.urlopen(url, timeout=60).read())


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


_repaint_body = partial(reproj_body.repaint_body, run_job=_run_job)


def _load_cfg(a):
    cfg = {}
    if a.config and os.path.isfile(a.config):
        cfg = json.load(open(a.config, encoding="utf-8")) or {}
    number = lambda key, default: default if cfg.get(key) in (None, "") else cfg[key]
    result = {
        "scene": cfg.get("scene") or a.scene,
        "char": cfg.get("char") if cfg.get("char") is not None else a.char,
        "neg_scene": cfg.get("neg_scene") or "",
        "neg_char": cfg.get("neg_char") or "",
        "face_prompt": cfg.get("face_prompt") or "",
        "hand_prompt": cfg.get("hand_prompt") or "",
        "char_plate": cfg.get("char_plate") or "",
        "neg_face": cfg.get("neg_face") or "",
        "width": _align8(cfg.get("width") or a.width or 1216, 512, 2048),
        "height": _align8(cfg.get("height") or a.height or 832, 512, 2048),
        "steps": min(50, max(12, int(cfg.get("steps") or 26))),
        "env_steps": min(50, max(12, int(cfg.get("env_steps") or cfg.get("steps") or 24))),
        "char_steps": min(50, max(12, int(cfg.get("char_steps") or cfg.get("steps") or 30))),
        "cfg": float(number("cfg", 5.5)),
        "seed": int(cfg.get("seed") or a.seed or 2026),
        "model": str(cfg.get("model") or "").strip(),
        "scene_lora": str(cfg.get("scene_lora") or "").strip(),
        "env_weight": float(number("env_weight", 0.70)),
        "char_lora": str(cfg.get("char_lora") or "").strip(),
        "char_weight": float(number("char_weight", 0.85)),
        "extra_loras": cfg.get("extra_loras") or [],
        "ratio": 0.0 if (str(cfg.get("ratio") or "").strip().lower() == "auto" or cfg.get("ratio_mode") == "auto") else float(cfg.get("ratio") or 0.34),
        "ratio_mode": str(cfg.get("ratio_mode") or ("auto" if str(cfg.get("ratio") or "").strip().lower() == "auto" else "fixed")).strip().lower(),
        "x_locked": bool(cfg.get("x_locked", False)),
        "probe_posture": bool(cfg.get("probe_posture", True)),
        "ground_y": float(number("ground_y", 0.88)),
        "x": float(number("x", 0.34)),
        "expand_notes": cfg.get("expand_notes") or [],
        "client_meta": cfg.get("client_meta") or {},
        "style_suffix": cfg.get("style_suffix"),
        "face_suffix": cfg.get("face_suffix"),
        "hand_suffix": cfg.get("hand_suffix"),
        "keep_intermediates": bool(cfg.get("keep_intermediates")),
        "tile_bg": bool(cfg.get("tile_bg", False)),
        "auto_handfix": bool(cfg.get("auto_handfix")),
        "light": str(cfg.get("light") or "left").strip().lower(),
        "pipeline": (lambda p: "b_char" if p in ("b_char", "char_first") else
                     ("b_lens" if p in ("b_lens", "lens") else
                      ("b" if p in ("b", "m1", "b_legacy") else "a")))(str(cfg.get("pipeline") or "a").strip().lower()),
        "lens_spec": cfg.get("lens_spec") if isinstance(cfg.get("lens_spec"), dict) else {},
        "layer_mode": str(cfg.get("layer_mode") or "auto").strip().lower(),
        "pose": cfg.get("pose") if isinstance(cfg.get("pose"), dict) else {},
    }
    # 零权重禁用该侧主 LoRA，后续阶段不能通过最小权重兜底重新挂回。
    if result["env_weight"] == 0:
        result["scene_lora"] = ""
    if result["char_weight"] == 0:
        result["char_lora"] = ""
    return result


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
    # b_lens：镜头计划先行——有镜头积木才 fixed，没有就完全放手给模型自判
    lens = lens_policy.build_lens_plan(c) if c["pipeline"] == "b_lens" else None
    if lens is not None:
        # 用户显式选了占比（ratio>0）就以用户为准；否则由镜头计划决定 auto / fixed
        c["ratio_mode"] = "fixed" if (c["ratio"] or 0) > 0 else lens["ratio_mode"]
        c["env_weight"] = min(0.82, float(c["env_weight"]))
    out = os.path.abspath(a.out or os.path.join(ROOT, "SD-Picture", "reproject", str(c["seed"])))
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
    plate_cw = (min(0.75 if is_b else 0.65, round(c["char_weight"] * (0.85 if is_b else 0.72), 2))
                if (c["scene_lora"] or plate_extra) else min(0.85, c["char_weight"]))
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

    # L2：出板只留人物轮廓摘要（发色/服装主色/动作/景别），脸与体型词留给 02_body/03_face
    plate_char = c["char_plate"].strip() or c["char"]
    pc = slim.contour_summary(plate_char) or plate_char
    prop_cue = "" if c["ratio_mode"] == "auto" else _proportion_cue(c["scene"], pc, c["ratio"])
    plate_prompt = _dedup_join(c["scene"], pc, prop_cue) if c["char"].strip() else c["scene"]
    if lens is not None:
        plate_prompt = lens_policy.plate_prompt(plate_prompt, lens)
    # 出板负向不带手部词；人物/修脸负向不带家具与穿模词
    plate_neg = slim.drop_hand_negatives(_merge_neg(c["neg_scene"], c["neg_char"])) or _BASE_NEG_PLATE
    char_neg = slim.drop_scene_structure_negatives(c["neg_char"] or _merge_neg(c["neg_scene"])) or _BASE_NEG_CHAR
    suffixes = rp.resolve_suffixes(c)
    mf = rp.new_manifest(c, out, plate_prompt, plate_neg, char_neg, plate_loras, char_loras, detail_loras, suffixes)
    mp = mem_plan.Plan(context="coop")

    is_bchar = (c["pipeline"] == "b_char" and bool(c["char"].strip()))
    is_blens = (c["pipeline"] == "b_lens" and bool(c["char"].strip()))
    if is_bchar:
        import coop_char_first
        sloras = [{"name": c["scene_lora"], "weight": c["env_weight"]}] if c["scene_lora"] else []
        cur, pose2 = coop_char_first.run_char_first_pipeline(
            c, steps_dir, sloras, char_loras, detail_loras, char_neg, suffixes, mf, mp,
            _run_job, _dedup_join, _merge_neg, _repaint_body)
        print("[3/3] 脸部/手部精修与合成", flush=True)
    elif is_blens:
        import coop_lens_first
        print("[b_lens] 镜头优先主线", flush=True)
        cur, pose2 = coop_lens_first.run_lens_first_pipeline(
            c, steps_dir, lens, plate_prompt, plate_neg, plate_loras, char_loras, detail_loras,
            char_neg, suffixes, mf, mp, _run_job, _dedup_join, _merge_neg, _repaint_body)
        print("[3/3] 脸部/手部精修与合成", flush=True)
    else:
        import light_draft
        cur, pose2 = light_draft.run_ab_stage(
            c, is_b, steps_dir, plate_prompt, plate_neg, plate_loras, char_loras, detail_loras,
            char_neg, suffixes, mf, mp, _run_job, _dedup_join, _repaint_body)

    if c["char"].strip():
        cur_w, cur_h = Image.open(cur).size

        face_box = parts.face_box_from_pose(pose2, cur_w, cur_h)
        facing = ""
        if is_blens:
            facing = ((scale_probe.infer_head_facing(pose2, cur_w, cur_h) if pose2 else "")
                      or (mf.get("lens") or {}).get("facing_step2") or "")
            mf["lens"] = dict(mf.get("lens") or {}, facing=facing)
            if facing == "back":
                print("[face] 实测背影，03_face 跳过（修脸会把人拧回正面）", flush=True)
                rp.record_step(mf, "03_face", status="skipped", note="facing_back")
                face_box = None
        if face_box:
            f_ratio = face_box["h"] / float(cur_h)
            f_dn = 0.28 if is_bchar else (0.45 if f_ratio < 0.08 else (0.38 if f_ratio < 0.145 else 0.34))
            f_steps = max(18, int(round(c["char_steps"] * 0.75))) if is_bchar else 20
            # 03_face：只留 @ID 的脸/眼/发饰 + @MOOD/@GAZE；b_char 同生线追加环境光词防把夜景/夕阳脸洗白
            face_base = c["face_prompt"].strip() or c["char"]
            face_core = slim.face_summary(face_base) or face_base
            if is_bchar and c["scene"].strip():
                face_core = _dedup_join(face_core, c["scene"], "coherent environmental lighting on face")
            if is_blens and facing:
                # 侧/斜侧：单侧视角词 + 异瞳单向过滤，禁止对称双瞳把侧脸拉回正面
                face_core = _dedup_join(lens_policy.adapt_face_prompt(face_core, facing),
                                        lens_policy.facing_cue(facing))
                print("[face] 朝向=%s" % facing, flush=True)
            face_p = rp.append_suffix(face_core, suffixes["face"])
            face_loras = list(detail_loras) + ([{"name": c["scene_lora"], "weight": 0.30}] if (is_bchar and c["scene_lora"]) else [])
            f_neg = slim.drop_scene_structure_negatives(
                slim.drop_hand_negatives(c["neg_face"] or char_neg)) or char_neg
            print("[face] box=%s denoise=%.2f steps=%d" % (face_box, f_dn, f_steps), flush=True)
            try:
                cur, _ = hp.repaint(cur, face_box, face_p, f_neg, denoise=f_dn,
                                    scale=3.0, pad=0.45, steps=f_steps, cfg=5.0,
                                    seed=c["seed"] + 2, loras=face_loras,
                                    tag="face", max_side=832, shape="ellipse", model=c["model"])
                f_dst = os.path.join(steps_dir, "03_face.png")
                shutil.copy2(cur, f_dst)
                rp.record_step(mf, "03_face", status="ok", prompt=face_p, negative=f_neg,
                               denoise=f_dn, steps=f_steps, cfg=5.0, seed=c["seed"] + 2,
                               loras=face_loras, crop_box=face_box, output=f_dst)
                print("PROGRESS 0.45", flush=True)
            except Exception as e:  # noqa: BLE001
                rp.record_step(mf, "03_face", status="skipped", note=str(e)[:120], crop_box=face_box)
                print("[face] 跳过:", str(e)[:90], flush=True)

        hand_boxes = parts.hand_boxes_from_pose(pose2, cur_w, cur_h, face_box=face_box)
        hand_p = rp.append_suffix(c["hand_prompt"].strip() or "masterpiece, best quality, delicate anime hand, five separate slender fingers, clean finger joints", suffixes["hand"])
        mf["prompts"]["hand_prompt"] = hand_p
        mf["hand_boxes"] = hand_boxes
        if c.get("auto_handfix"):
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
        else:
            rp.record_step(mf, "04_hands", status="deferred", count=len(hand_boxes), boxes=hand_boxes)
            print("[hands] 检出 %d 处手部坐标（人眼审核模式，不自动重绘）" % len(hand_boxes), flush=True)
            print("PROGRESS 0.90", flush=True)

        img = Image.open(cur).convert("RGB")
        sh_light = "" if (is_b or is_bchar) else c["light"]
        sh_str = 65 if is_b else (45 if is_bchar else 150)
        img, fn = parts.apply_feet_shadow(img, pose2, light=sh_light, strength=sh_str)
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
