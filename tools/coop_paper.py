"""纸片模式：背景板 → 人物卡 → 前景卡 → 合成器（几何关系由合成器负责）。
  python tools/coop_paper.py --scene "rainy neon alley..." --char "1girl, white coat" \
      --artist "soft_style.safetensors" --ratio 0.46 --fg "rusty railing and weeds"
"""
import argparse, json, os, re, sys, time, urllib.request
from PIL import Image, ImageDraw, ImageFilter
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evidence
import stage_parse
import shot as shot_mod
import layers as layers_mod
import paper_assemble
import paper_conductor
import paper_cut
import paper_draft
import paper_fg
from paper_prompts import SHARP, PLATE_DETAIL, clean_char_prompt, stage_style_for_char, char_light_from, build_char
ROOT = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "http://127.0.0.1:8770"
OUT = os.path.join(ROOT, "SD-Picture", "paper")
W, H = 1344, 768
ANIME = "(anime illustration:1.1), (cel shading:1.05), (clean line art:1.05)"
SCENERY_W = {"plate": 0.6, "fg": 0.65, "prop": 0.65}
NEG = ("multiple people, crowd, text, watermark, lowres, letterbox, border, "
       "faceless, blank face, overexposed, blown highlights, "
       "soft focus, blurry, depth of field, bokeh, hazy, motion blur")
def post(u, o):
    r = urllib.request.Request(u, data=json.dumps(o).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=120).read())
def get(u):
    return json.loads(urllib.request.urlopen(u, timeout=60).read())
def run(body, tag):
    j = post(API + "/api/run", body)
    pid = j["job_id"]
    t0 = time.time()
    while time.time() - t0 < 900:
        s = get(API + "/api/job/" + pid)
        if s.get("status") in ("done", "error"):
            imgs = (s.get("result") or {}).get("images") or []
            if not imgs:
                raise RuntimeError(tag + ": " + str(s.get("result"))[:300])
            return imgs[0]
        time.sleep(2)
    raise TimeoutError(tag)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="")
    ap.add_argument("--char", default="1girl, solo, adult woman, white coat, standing")
    ap.add_argument("--artist", default="soft_style.safetensors")
    ap.add_argument("--artist-char", default="", help="人物画师 LoRA（空=用 --artist）")
    ap.add_argument("--artist-env", default="", help="环境画师 LoRA（空=用 --artist）")
    ap.add_argument("--artist-w", type=float, default=0.65)
    ap.add_argument("--fg", default="")
    ap.add_argument("--prop", default="")
    ap.add_argument("--ratio", type=float, default=0.46)
    ap.add_argument("--ground-y", type=float, default=0.90)
    ap.add_argument("--x", type=float, default=0.38)
    ap.add_argument("--light", default="left")
    ap.add_argument("--char-light", default="(warm light from the left:1.2), (cool rim light from the right:1.1), (night scene lighting:1.15)")
    ap.add_argument("--seed", type=int, default=940001)
    ap.add_argument("--out", default="")
    ap.add_argument("--reuse-plate", default="")
    ap.add_argument("--no-stage", action="store_true")
    ap.add_argument("--no-review", action="store_true")
    ap.add_argument("--supersample", type=int, default=2)
    ap.add_argument("--scale-bias", type=float, default=1.12)
    ap.add_argument("--footwear", default="(dark brown leather shoes:1.25), (wearing shoes:1.2)")
    ap.add_argument("--char-size", default="1024x1536")
    ap.add_argument("--cutout-res", type=int, default=1024, help="2.1 抠图分辨率；人物卡越大越该调高")
    ap.add_argument("--draft", default="legacy_xl", help="草稿画师：legacy_xl=先出结构草图再交环境画师；空=不草图")
    ap.add_argument("--draft-model", default="")
    ap.add_argument("--draft-denoise", type=float, default=0.58)
    ap.add_argument("--no-fusion", action="store_true")
    ap.add_argument("--shot", default="auto")
    ap.add_argument("--priority", default="auto")
    ap.add_argument("--detail", default="rich")
    ap.add_argument("--plate-size", default="1536x1024")
    ap.add_argument("--cutout", default="biref", choices=["biref"],
                    help="biref=BiRefNet（默认，失败时自动回退 u2net）")
    ap.add_argument("--refl", type=float, default=0.05, help="地面倒影强度，0=关闭")
    ap.add_argument("--preset", default="fixed_001", help="ref/paper_presets.json 的键；空串=不套用")
    _pre, _ = ap.parse_known_args()
    if _pre.preset:
        import paper_preset
        paper_preset.apply(ap, _pre.preset, ROOT)
    a = ap.parse_args()
    if not a.scene:
        raise SystemExit("--scene 必填（或用 --preset 提供 scene）")
    import mem_plan
    MEM = mem_plan.Plan()
    paper_cut.CUTOUT_MODE = a.cutout
    paper_cut.MEM = MEM
    MEM.mark("start", "preset=%s cutout=%s refl=%.2f" % (a.preset, a.cutout, a.refl))
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = a.out or os.path.join(OUT, stamp)
    os.makedirs(out, exist_ok=True)
    char_artist = a.artist_char or a.artist
    env_artist = a.artist_env or a.artist
    print("[artist] 人物=%s · 环境=%s" % (char_artist, env_artist), flush=True)
    fg_prop = ", ".join([x for x in (a.fg, a.prop) if x])
    if a.reuse_plate and os.path.exists(a.reuse_plate):
        plate = a.reuse_plate
        print("[1/5] 复用背景板 %s" % plate, flush=True)
    else:
        print("[1/5] 背景板（景物入画，无人物）…", flush=True)
        try:
            pw, ph = [int(v) for v in str(a.plate_size).lower().split("x")]
        except Exception:
            pw, ph = 1536, 1024
        prompt = (a.scene + (", " + fg_prop if fg_prop else "") +
                  ", " + PLATE_DETAIL + ", (no people:1.3), (cinematic lighting:1.05)")
        def _plate(pr, seed, tag):
            return run({"prompt": pr,
                        "negative": "people, person, 1girl, 1boy, human, character, "
                                    "empty, sparse, flat lighting, low detail, " + NEG,
                        "width": pw, "height": ph, "steps": 30, "cfg": 5.4, "seed": seed,
                        "prefix": "PAPER_PLATE", "mode": "t2i", "save_to": "paper",
                        "loras": [{"name": env_artist, "weight": SCENERY_W["plate"]}]}, tag)
        draft_path = ""
        if (a.draft or "").lower() == "legacy_xl":
            import paper_draft
            draft_path = paper_draft.make(run, a.scene, a.seed, a.draft_model, W, H, out)
        try:
            if draft_path:
                # 环境画师第 1 次：吃草稿出正式背景板
                img = run({"prompt": prompt,
                           "negative": "people, person, 1girl, 1boy, human, character, "
                                       "empty, sparse, flat lighting, " + NEG,
                           "width": W, "height": H, "steps": 30, "cfg": 5.4, "seed": a.seed,
                           "mode": "i2i", "reference": draft_path, "denoise": a.draft_denoise,
                           "prefix": "PAPER_PLATE", "save_to": "paper",
                           "loras": [{"name": env_artist, "weight": SCENERY_W["plate"]}]}, "plate")
            else:
                img = _plate(prompt, a.seed, "plate")
        except Exception as e:  # noqa: BLE001
            print("[plate] %dx%d 失败，回退 1344x768: %s" % (pw, ph, str(e)[:80]), flush=True)
            pw, ph = W, H
            img = _plate(prompt, a.seed, "plate")
        plate = os.path.join(out, "plate.png")
        Image.open(img).convert("RGB").resize((W, H), Image.LANCZOS).save(plate)
    stage = None
    if not a.no_stage:
        print("[2/5] 7B 舞台解析…", flush=True)
        try:
            stage = stage_parse.parse(plate)
            json.dump(stage, open(os.path.join(out, "stage.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("[stage] by=%s horizon=%.2f lights=%d objects=%d slot=%s" % (
                stage.get("by"), stage.get("horizon_y", 0), len(stage.get("lights") or []),
                len(stage.get("objects") or []), stage.get("person_slots")), flush=True)
        except Exception as e:  # noqa: BLE001
            print("[stage] 解析失败，走默认参数: %s" % str(e)[:120], flush=True)
            stage = None
    plan = paper_conductor.plan(plate, stage, a.scene)
    try:
        json.dump(plan, open(os.path.join(out, "plan.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except Exception:
        pass
    print("[conductor] by=%s fg=%d inter=%s" % (
        plan.get("by"), len(plan.get("foreground") or []),
        (plan.get("interaction") or "")[:60]), flush=True)
    MEM.unload_llm("舞台解析结束")
    if (stage and not a.reuse_plate and a.detail == "rich" and stage.get("details")):
        try:
            more = ", ".join(stage["details"][:5]) + ((", " + plan["env_extra"]) if plan.get("env_extra") else "")
            print("[plate] 细节回灌：%s" % more[:120], flush=True)
            img2 = _plate(prompt + ", " + more, a.seed + 7, "plate2")
            Image.open(img2).convert("RGB").resize((W, H), Image.LANCZOS).save(plate)
        except Exception as e:  # noqa: BLE001
            print("[plate] 细节回灌失败: %s" % str(e)[:80], flush=True)
    shot_name, ratio, framing, anchor = shot_mod.resolve(a.shot, a.priority, stage, a.scale_bias)
    print("[shot] %s · %s · %.2f · %s" % (shot_name, framing, ratio, anchor), flush=True)
    ground_y, pos_x = a.ground_y, a.x
    if stage and stage.get("person_box"):
        pb = stage["person_box"]
        ground_y, pos_x = float(pb["feet_y"]), float(pb["x"])
    elif stage and stage.get("person_slots"):
        slot = stage["person_slots"][0]
        ground_y, pos_x = float(slot["ground_y"]), float(slot["x"])
    light_prompt = char_light_from(stage, a.char_light)
    if stage and stage.get("style"):
        light_prompt = light_prompt + ", " + str(stage["style"])[:90]
    print("[3/5] 人物卡…", flush=True)
    want_shoes = not any(k in a.footwear.lower() for k in ("barefoot", "bare feet", "裸足"))
    shoe_neg = "" if want_shoes else "barefoot, bare feet, "
    base_char, dropped = clean_char_prompt(a.char)
    if not base_char.strip():
        base_char = "1girl, solo, full body standing"
    if dropped:
        print("[prompt] 人物剔除构图/景深块 %d 个" % dropped, flush=True)
    style_char = stage_style_for_char((stage or {}).get("style"))
    details_txt = ", ".join((stage or {}).get("char_details") or [])
    inter = (stage or {}).get("interaction") or {}
    inter_txt = "".join([", (wet sheen on shoes:1.08)" if inter.get("wet") else "",
                         ", (wind-blown hair:1.12)" if inter.get("wind") in ("light", "strong") else "",
                         ", (holding %s:1.15)" % inter["held"] if inter.get("held") else ""])
    if plan.get("interaction"):
        inter_txt += ", (%s:1.15)" % plan["interaction"]
    if plan.get("char_extra"):
        details_txt = (details_txt + ", " + plan["char_extra"]).strip(", ")
    char_prompt = build_char(ANIME, base_char, framing, a.footwear, light_prompt,
                             style_char, details_txt, inter_txt, False)
    print("[char] %s" % char_prompt[:400], flush=True)
    neg_char = ("scenery, background objects, grey background, white background, "
                "gradient background, multiple views, character sheet, portrait inset, "
                "extra head, duplicate, " + shoe_neg + NEG +
                (", " + plan["char_neg"] if plan.get("char_neg") else ""))
    try:
        cw_, ch_ = [int(v) for v in str(a.char_size).lower().split("x")]
    except Exception:
        cw_, ch_ = 1024, 1536
    def _char(w, h, tag):
        return run({"prompt": char_prompt, "negative": neg_char,
                    "width": w, "height": h, "steps": 30, "cfg": 5.4, "seed": a.seed + 1,
                    "prefix": "PAPER_CHAR", "mode": "t2i", "save_to": "paper",
                    "loras": [{"name": char_artist, "weight": a.artist_w}]}, tag)
    raw = os.path.join(out, "char_raw.png")
    try:
        img = _char(cw_, ch_, "char")
    except Exception as e:  # noqa: BLE001
        print("[char] %dx%d 失败，回退 960x1280: %s" % (cw_, ch_, str(e)[:80]), flush=True)
        cw_, ch_ = 960, 1280
        img = _char(cw_, ch_, "char")
    Image.open(img).convert("RGB").save(raw)
    card = paper_cut.cut(raw, os.path.join(out, "char.png"), "char", resolution=a.cutout_res)
    im = Image.open(card).convert("RGBA")
    a_ = im.split()[3]
    rgb_ = im.convert("RGB").filter(ImageFilter.UnsharpMask(radius=1.2, percent=70, threshold=3))
    rgb_.putalpha(a_)
    rgb_.save(card)
    ok, why = evidence.card_ok(card)
    qa = stage_parse.check_card(raw, want_shoes=want_shoes) if stage else {"ok": True, "faces": None}
    if not qa.get("ok", True):
        ok, why = False, "faces=%s" % qa.get("faces")
    print("[char] 体检 %s (%s)" % ("ok" if ok else "fail", why), flush=True)
    if not ok:
        try:
            img2 = run({"prompt": char_prompt + ", (full body from head to feet:1.45), (feet visible:1.3)",
                        "negative": "cropped feet, close-up, portrait, character sheet, multiple views, "
                                    "extra head, duplicate, " + shoe_neg + NEG,
                        "width": cw_, "height": ch_, "steps": 30, "cfg": 5.4, "seed": a.seed + 11,
                        "prefix": "PAPER_CHAR2", "mode": "t2i", "save_to": "paper",
                        "loras": [{"name": char_artist, "weight": a.artist_w}]}, "char2")
            raw2 = os.path.join(out, "char2_raw.png")
            Image.open(img2).convert("RGB").save(raw2)
            card2 = paper_cut.cut(raw2, os.path.join(out, "char2.png"), "char2")
            ok2, why2 = evidence.card_ok(card2)
            qa2 = stage_parse.check_card(raw2, want_shoes=want_shoes) if stage else {"ok": True}
            if not qa2.get("ok", True):
                ok2, why2 = False, "faces=%s" % qa2.get("faces")
            print("[char] 重生成 %s (%s)" % ("ok" if ok2 else "fail", why2), flush=True)
            if ok2:
                card = card2
        except Exception as e:  # noqa: BLE001
            print("[char] 重生成失败: %s" % str(e)[:100], flush=True)
    if framing == "bust":
        pos_x = 0.5
        im = Image.open(card).convert("RGBA")
        bb = im.getbbox() or (0, 0, im.width, im.height)
        cut = bb[1] + int((bb[3] - bb[1]) * 0.56)
        bust = im.crop((bb[0], bb[1], bb[2], cut))
        bust.save(os.path.join(out, "char_bust.png"))
        card = os.path.join(out, "char_bust.png")
    _cw = max(1, int(Image.open(card).width * (H * ratio) / Image.open(card).height))
    _fh = int(H * ratio)
    _cx, _feet = int(W * pos_x), int(H * ground_y)
    if anchor == "bottom":
        char_box = ((_cx - _cw / 2) / W, (H - _fh) / H, (_cx + _cw / 2) / W, 1.0)
    else:
        char_box = ((_cx - _cw / 2) / W, (_feet - _fh) / H, (_cx + _cw / 2) / W, _feet / H)
    layers = [{"card": card, "ratio": ratio, "ground_y": ground_y, "x": pos_x,
               "light": a.light, "shadow": 255, "refl": a.refl, "ambient": 0.92, "grade": 0.2,
               "solid": False, "poisson": 0, "slot": True, "anchor": anchor}]
    layers += paper_fg.build(run, plan, out, env_artist, a.seed, a.light, SCENERY_W, NEG, paper_cut.cut)
    print("[4/5] 景物剥离…", flush=True)
    if stage and stage.get("objects"):
        cw = max(1, int(Image.open(card).width * (H * ratio) / Image.open(card).height))
        fh = int(H * ratio)
        cx, feet = int(W * pos_x), int(H * ground_y)
        char_box = ((cx - cw / 2) / W, (feet - fh) / H, (cx + cw / 2) / W, feet / H)
        def _area(o):
            b = o["bbox"]
            return (b[2] - b[0]) * (b[3] - b[1])
        objs = [o for o in stage["objects"] if o.get("occludes") and o.get("depth") in ("fg", "mid")]
        if not objs:
            objs = [o for o in stage["objects"] if o.get("depth") in ("fg", "mid")
                    and o["bbox"][3] > 0.72 and _area(o) > 0.005]
        objs.sort(key=lambda o: (o["bbox"][2] - o["bbox"][0]) * (o["bbox"][3] - o["bbox"][1]), reverse=True)
        skipped = []
        cw0 = max(1, int(Image.open(card).width * (H * ratio) / Image.open(card).height))
        fh0 = int(H * ratio)
        cxc, cfeet = int(W * pos_x), int(H * ground_y)
        cbox = ((cxc - cw0 * 0.7) / W, (cfeet - fh0 * 1.05) / H,
                (cxc + cw0 * 0.7) / W, (cfeet + fh0 * 0.10) / H)
        def _hit(poly):
            xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
            return not (max(xs) < cbox[0] or min(xs) > cbox[2] or max(ys) < cbox[1] or min(ys) > cbox[3])
        for i, oc in enumerate([o for o in (stage.get("occluders") or []) if _hit(o["polygon"])][:1]):
            dst = os.path.join(out, "poly_%d.png" % i)
            try:
                from lift import lift_poly
                if lift_poly(plate, oc["polygon"], dst):
                    xs = [p[0] for p in oc["polygon"]]; ys = [p[1] for p in oc["polygon"]]
                    layers.insert(0, {"card": dst, "ratio": max(0.06, max(ys) - min(ys)),
                                      "ground_y": max(ys), "x": (min(xs) + max(xs)) / 2,
                                      "light": a.light, "shadow": 170, "refl": 0.0,
                                      "ambient": 0.86, "grade": 0.28})
            except Exception as e:  # noqa: BLE001
                skipped.append({"name": oc.get("name"), "why": str(e)[:60]})
        for i, o in enumerate(objs[:2]):
            dst = os.path.join(out, "lift_%d.png" % i)
            try:
                from lift import lift
                if not lift(plate, o["bbox"], dst):
                    skipped.append({"name": o.get("name"), "why": "empty alpha"})
                    continue
            except Exception as e:  # noqa: BLE001
                print("[lift] %s 失败: %s" % (o.get("name"), str(e)[:80]), flush=True)
                continue
            x0, y0, x1, y1 = o["bbox"]
            layer = {"card": dst, "ratio": max(0.06, y1 - y0), "ground_y": y1, "x": (x0 + x1) / 2,
                     "light": a.light, "shadow": 170, "refl": 0.0, "ambient": 0.86, "grade": 0.28}
            overlap = not (x1 < char_box[0] or x0 > char_box[2] or y1 < char_box[1] or y0 > char_box[3])
            if overlap:
                layers.append(layer)
            else:
                layers.insert(0, layer)
            print("[lift] %s bbox=%s %s" % (o.get("name"), [round(v, 2) for v in o["bbox"]],
                                            "人物前" if overlap else "人物后"), flush=True)
    print("[5/5] 合成…", flush=True)
    scene = {"layers": layers, "plate": plate, "params": vars(a), "stage": stage or {},
             "no_fusion": bool(a.no_fusion)}
    try:
        scene["lift_skipped"] = skipped
    except NameError:
        scene["lift_skipped"] = []
    scene_path = os.path.join(out, "scene.json")
    json.dump(scene, open(scene_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ss = max(1, int(getattr(a, "supersample", 2)))
    MEM.free_comfy("2.1 → 合成")
    MEM.mark("compose", "supersample=%d" % ss)
    comp, ev = paper_assemble.finish(plate, scene, scene_path, out, ss, char_box,
                                    anchor, stage, layers, a.no_review)
    try:
        stage_parse.unload()
    except Exception:
        pass
    try:
        MEM.save(out)
    except Exception:
        pass
    print("done:", comp, flush=True)
if __name__ == "__main__":
    main()
