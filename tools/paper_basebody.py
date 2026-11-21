# -*- coding: utf-8 -*-
"""素体法：环境画师一次画出「场景 + 素体」，人物画师只换脸/发/衣，最后手部 4× 超分精修。

为什么这么摆：重绘需要「已经存在的人」当起点，否则 denoise 低就续画地板、
denoise 高就换人。素体把这个起点交给环境画师，透视/光照/姿态天然一致。
"""
import argparse
import json
import os
import sys
import time

from PIL import Image, ImageFilter
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cutout
import hand_precise as hp
import sdp_body_mask as sbm
import paper_reproject as pr

ROOT = pr.ROOT
CI = pr.CI
W, H = pr.W, pr.H
MIO = [{"name": "style_lora_a5E585B6E4B889.YDAV.safetensors", "weight": 1.0},
       {"name": "local_char_lora_h2.safetensors", "weight": 1.0}]
# A 路线：背影。凡是「看不见的东西」一律不写，否则模型会把她转过来。
CHAR_BACK = ("(silver hair:1.3), long straight hair, (long hair ornament:1.25), "
            "(cream military dress:1.25), (slender figure:1.2), "
            "(from behind:1.4), (back view:1.35), (facing away:1.3), "
            "(both hands resting on the sill:1.2)")
NEG_BACK = ("facing viewer, front view, looking at viewer, face visible, two-tone eyes, "
            "red eyes, blush, smile, lips")


def base_plate(scene, seed, lora_weight=0.55, char_lora=False, w=None, h=None, raw=False):
    """环境画师画「场景 + 素体」。raw=True 时原样使用提示词，不追加素体描述。"""
    filler = "" if raw else (", one girl standing, leaning against the window sill, one hand resting on the sill, "
                             "plain white shirt and dark skirt, full body visible, (detailed background:1.2)")
    body = {"prompt": scene + filler,
            "negative": "text, watermark, lowres, blurry, multiple people, cropped, nude, close-up",
            "width": int(w or W), "height": int(h or H), "steps": 30, "cfg": 5.5, "seed": seed,
            "prefix": "BASEBODY_plate", "mode": "t2i", "save_to": "paper",
            "loras": ([{"name": pr.ENV_LORA, "weight": lora_weight}] +
                      ([{"name": "local_char_lora_h2.safetensors", "weight": 0.9}] if char_lora else []))}
    return pr._wait(pr.pl.post(pr.API + "/api/run", body)["job_id"])


def figure_mask(plate_path, out_dir):
    """从背景板里取出素体：优先 SDPose 骨架蒙版，失败才退化胶囊。"""
    a = None
    try:
        raw = hp.detect_raw(plate_path)
        if raw.get("json"):
            a, cov = sbm.body_mask(raw["json"], W, H)
            if a is not None:
                print("[mask] 骨架蒙版 覆盖 %.1f%%" % cov, flush=True)
    except Exception as e:  # noqa: BLE001
        print("[mask] 骨架失败:", str(e)[:80], flush=True)
    if a is None:
        cov = 0
    if a is None or cov < 3 or cov > 45:
        c = Image.new("L", (W, H), 0)
        from PIL import ImageDraw
        cx = int(W * 0.5)
        ImageDraw.Draw(c).rounded_rectangle((cx - 120, int(H * 0.25), cx + 120, int(H * 0.95)), 40, fill=255)
        a = c
        print("[mask] BiRefNet 不稳(%.1f%%)，退化为胶囊" % cov, flush=True)
    a = a.filter(ImageFilter.GaussianBlur(5))
    name = "basebody_mask_%s.png" % time.strftime("%H%M%S")
    Image.merge("RGB", (a, a, a)).save(os.path.join(CI, name))
    a.save(os.path.join(out_dir, "mask_char.png"))
    print("[mask] 覆盖 %.1f%%" % (np.asarray(a).mean() / 255 * 100), flush=True)
    return name, a


def run(scene, out_dir, seed=2026, denoise=0.62, fix_hands=True, hand_denoise=0.55):
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    plate = base_plate(scene, seed)
    Image.open(plate).save(os.path.join(out_dir, "01_plate_basebody.png"))
    print("[plate] %.0fs" % (time.time() - t0), flush=True)

    t0 = time.time()
    mask_name, mask = figure_mask(plate, out_dir)
    print("[mask] %.0fs" % (time.time() - t0), flush=True)

    t0 = time.time()
    out = pr.repaint(plate, mask_name,
                     CHAR_BACK + ", keep the original pose, same art style",
                     "text, watermark, lowres, blurry, multiple people, cropped limbs, " + NEG_BACK,
                     denoise, pr.CHAR_LORA, 1.0, seed + 1, loras=MIO)
    comp = Image.open(out).convert("RGB")
    comp.save(os.path.join(out_dir, "02_mio.png"))
    print("[mio] %.0fs" % (time.time() - t0), flush=True)

    # 手部：4× 超分 + 凸包蒙版重绘
    if fix_hands:
        t0 = time.time()
        try:
            boxes = hp.detect(comp.filename if hasattr(comp, "filename") else out)
        except Exception:
            boxes = []
        cur = os.path.join(out_dir, "02_mio.png")
        for i, b in enumerate(boxes[:2]):
            if b.get("score", 1) > 0.95 and i > 0:
                continue
            raw = hp.detect_raw(cur)
            cand = [x for x in (raw.get("boxes") or []) if x.get("hand") == b.get("hand")]
            if not cand:
                continue
            bb = dict(cand[0])
            poly = hp.hand_polygon(raw.get("json"), bb.get("hand", "right"))
            if poly is not None:
                bb["polygon"] = poly.reshape(-1, 2).tolist()
            cur, _ = hp.repaint(cur, bb, "anime style, cel shading, five natural fingers, same art style",
                                "extra fingers, fused fingers, deformed hand", hand_denoise,
                                3.0, 0.30, seed=seed + 10 + i, loras=MIO)
            print("[hand%d] -> %s" % (i + 1, os.path.basename(cur)), flush=True)
        comp = Image.open(cur).convert("RGB")
        print("[hand] %.0fs 复检 %s" % (time.time() - t0, json.dumps(hp.verify(cur), ensure_ascii=False)), flush=True)

    final = os.path.join(out_dir, "comp.png")
    comp.save(final)
    print("OK", final)
    return final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--denoise", type=float, default=0.62)
    ap.add_argument("--no-hands", action="store_true")
    ap.add_argument("--plate-only", action="store_true", help="只出环境板（场景+角色 LoRA），不换人")
    ap.add_argument("--plate-prompt", default="", help="出板提示词（空=用 --scene）")
    ap.add_argument("--prompt-file", default="", help="从文件读提示词")
    ap.add_argument("--blocks", default="", help="卡片|服装|视角|额外宏（逗号分隔）")
    ap.add_argument("--scene-schema", default="", help="ref/scene_schema.json 里的场景名")
    ap.add_argument("--width", type=int, default=0)
    ap.add_argument("--height", type=int, default=0)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    out = a.out or os.path.join(ROOT, "SD-Picture", "basebody", time.strftime("%Y%m%d_%H%M%S"))
    if a.prompt_file and os.path.isfile(a.prompt_file):
        a.plate_prompt = open(a.prompt_file, encoding="utf-8").read().strip()
    if a.blocks:
        card, garment, view, extra = (a.blocks.split("|") + ["", "", ""])[:4]
        extra_tokens = [x.strip() for x in extra.split(",") if x.strip()]
        import prompt_build
        r = prompt_build.build(card.strip(), garment.strip() or "casual_knit",
                               extra_tokens, id_blocks=[], view=view.strip(),
                               scene_schema=a.scene_schema)
        a.plate_prompt = r["positive"]
        print("[blocks] 校验:", json.dumps(r["report"].get("errors") or [], ensure_ascii=False),
              "视角:", json.dumps(r["view_errors"], ensure_ascii=False), flush=True)
        print("[blocks] 长度:", len(a.plate_prompt), flush=True)
        os.makedirs(out, exist_ok=True)
        open(os.path.join(out, "prompt.txt"), "w", encoding="utf-8").write(
            r["positive"] + "\n\n---NEG---\n\n" + r["negative"])
    if a.plate_only:
        p = base_plate(a.plate_prompt or a.scene, a.seed, char_lora=True, w=a.width, h=a.height, raw=bool(a.plate_prompt))
        os.makedirs(out, exist_ok=True)
        import shutil as _sh
        dst = os.path.join(out, "plate.png")
        _sh.copy2(p, dst)
        print("OK", dst)
        return
    run(a.scene, out, a.seed, a.denoise, not a.no_hands)


if __name__ == "__main__":
    main()
