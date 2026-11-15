# -*- coding: utf-8 -*-
"""立体书 v3 专项：舞台解析 / 缓存 / 景物剥离 / 合成槽位。"""
import json
import os
import sys
import tempfile


def run(check, ROOT):
    sys.path.insert(0, os.path.join(ROOT, "tools"))

    def _clamp():
        import stage_parse
        s = stage_parse._clamp({"horizon_y": 0.9, "vanishing_x": 0.1,
                                "lights": [{"dir": "up", "color": "pink", "strength": 5}],
                                "objects": [{"name": "box!", "bbox": [0.6, 0.7, 0.5, 0.9]}],
                                "person_slots": [{"x": 2, "ground_y": 0.1, "scale": 9}]})
        assert 0.30 <= s["horizon_y"] <= 0.60, s["horizon_y"]
        assert s["lights"][0]["dir"] == "left" and s["lights"][0]["color"] == "neutral"
        assert s["objects"] == [], s["objects"]
        assert s["person_slots"][0]["x"] <= 0.90 and s["person_slots"][0]["scale"] <= 0.70
    check("舞台解析：越界钳制", _clamp)

    def _cache():
        from PIL import Image
        import stage_parse
        tmp = tempfile.mkdtemp()
        plate = os.path.join(tmp, "p.png")
        Image.new("RGB", (48, 32), (10, 20, 30)).save(plate)
        old_cache, old_model = stage_parse.CACHE, stage_parse._model
        stage_parse.CACHE = os.path.join(tmp, "cache.json")
        stage_parse._model = lambda: None
        try:
            stage_parse.parse(plate)
            assert stage_parse.parse(plate).get("by") == "cache"
        finally:
            stage_parse.CACHE, stage_parse._model = old_cache, old_model
    check("舞台解析：缓存命中", _cache)

    def _lift():
        from PIL import Image
        import card_stage
        import lift as lift_mod
        tmp = tempfile.mkdtemp()
        plate = os.path.join(tmp, "plate.png")
        Image.new("RGB", (300, 200), (40, 50, 60)).save(plate)
        dst = os.path.join(tmp, "lift.png")
        old = lift_mod.comfy_cutout

        def fake(src, out):
            Image.new("RGBA", (90, 60), (200, 30, 30, 255)).save(out)
            return out
        lift_mod.comfy_cutout = fake
        try:
            assert lift_mod.lift(plate, [0.3, 0.4, 0.6, 0.8], dst) == dst
            assert os.path.isfile(dst)
        finally:
            lift_mod.comfy_cutout = old
    check("景物剥离：bbox 裁剪 + 抠图", _lift)

    def _compose():
        from PIL import Image
        import card_stage
        import layers
        tmp = tempfile.mkdtemp()
        plate = os.path.join(tmp, "plate.png")
        card = os.path.join(tmp, "card.png")
        Image.new("RGB", (400, 300), (30, 30, 40)).save(plate)
        Image.new("RGBA", (80, 160), (240, 200, 120, 255)).save(card)
        stage = {"horizon_y": 0.4, "lights": [{"dir": "right", "color": "warm", "strength": 0.9}],
                 "person_slots": [{"x": 0.7, "ground_y": 0.9, "scale": 0.5}],
                 "wet_ground": False, "objects": []}
        card_stage.compose(plate, card, tmp, 0.3, 0.8, 0.3, "left", 200, 0.3, 0.3, 0.8, 0.0, stage, True)
        sc = json.load(open(os.path.join(tmp, "scene.json"), encoding="utf-8"))
        assert sc["stage"]["wet_ground"] is False
        box = sc["box"]
        assert abs((box[0] + box[2]) / 2 - 0.7 * 400) < 3, box
    check("合成：stage 槽位/湿地开关", _compose)

    def _ground_curve():
        from PIL import Image
        import card_stage
        import layers
        tmp = tempfile.mkdtemp()
        plate = os.path.join(tmp, "plate.png")
        card = os.path.join(tmp, "card.png")
        Image.new("RGB", (400, 300), (30, 30, 40)).save(plate)
        Image.new("RGBA", (80, 160), (240, 200, 120, 255)).save(card)
        stage = {"horizon_y": 0.4, "lights": [{"dir": "left", "color": "warm", "strength": 0.9}],
                 "ground": [[0.0, 0.8], [1.0, 0.8]],
                 "person_slots": [{"x": 0.5, "ground_y": 0.9, "scale": 0.42}],
                 "wet_ground": True, "objects": []}
        card_stage.compose(plate, card, tmp, 0.3, 0.9, 0.5, "left", 200, 0.3, 0.3, 0.8, 0.0, stage, True)
        sc = json.load(open(os.path.join(tmp, "scene.json"), encoding="utf-8"))
        assert sc["ground_y"] == 0.8, sc["ground_y"]
    check("合成：地面线插值优先", _ground_curve)

    def _light_dedupe():
        import coop_paper
        stage = {"lights": [{"dir": "left", "color": "warm", "strength": 0.9},
                            {"dir": "right", "color": "warm", "strength": 0.9}]}
        s = coop_paper.char_light_from(stage, "fallback")
        assert "cool" not in s, s
        assert s.count("warm") == 2, s
    check("人物光：同色光去重、无冷边", _light_dedupe)

    def _lift_fallback():
        from PIL import Image
        import lift as lift_mod
        tmp = tempfile.mkdtemp()
        plate = os.path.join(tmp, "plate.png")
        Image.new("RGB", (200, 160), (10, 10, 10)).save(plate)
        dst = os.path.join(tmp, "o.png")
        old_c, old_g = lift_mod.comfy_cutout, lift_mod._grabcut

        def empty(src, out):
            Image.new("RGBA", (40, 40), (0, 0, 0, 0)).save(out)
            return out
        lift_mod.comfy_cutout = empty
        lift_mod._grabcut = lambda crop, out: None
        try:
            assert lift_mod.lift(plate, [0.2, 0.2, 0.8, 0.8], dst) is None
        finally:
            lift_mod.comfy_cutout, lift_mod._grabcut = old_c, old_g
    check("景物剥离：空 alpha 走 GrabCut 仍空则跳过", _lift_fallback)

    def _review_items():
        import stage_parse
        old_model, old_call = stage_parse._model, stage_parse._call
        stage_parse._model = lambda: "mock"
        stage_parse._call = lambda *a, **k: '{"items":{"contact_shadow":"fail","reflection":"pass","scale":"pass","seam":"pass"},"fix":{"shadow":0.8}}'
        try:
            rv = stage_parse.review("x.png", {"lights": [], "person_slots": []})
            assert rv["ok"] is False and rv["items"]["contact_shadow"] == "fail"
        finally:
            stage_parse._model, stage_parse._call = old_model, old_call
    check("评审：逐项判定 + 单点修复", _review_items)

    def _stage_v2():
        import stage_parse
        s = stage_parse._clamp({
            "person_box": {"x": 0.4, "head_y": 0.8, "feet_y": 0.3, "shoulder_w": 0.2},
            "occluders": [{"name": "x", "polygon": [[0.1, 0.8], [0.2, 0.8], [0.2, 0.9]]},
                          {"name": "y", "polygon": [[0.5, 0.7], [0.7, 0.7], [0.7, 0.95], [0.5, 0.95]]}],
            "palette": {"light": "#ffcc88", "shadow": "nope", "ground": "#334455"},
            "style": "soft painterly",
        })
        assert s["person_box"] is None, s["person_box"]
        assert len(s["occluders"]) == 1, s["occluders"]
        assert s["palette"].get("light") == "#ffcc88" and "shadow" not in s["palette"]
        assert s["style"] == "soft painterly"
    check("舞台 v2：人物框/多边形/palette 钳制", _stage_v2)

    def _person_box_scale():
        from PIL import Image
        import card_stage
        import layers
        tmp = tempfile.mkdtemp()
        plate = os.path.join(tmp, "plate.png"); card = os.path.join(tmp, "card.png")
        Image.new("RGB", (400, 300), (40, 40, 50)).save(plate)
        Image.new("RGBA", (50, 100), (240, 200, 120, 255)).save(card)
        stage = {"horizon_y": 0.4, "lights": [], "ground": [[0, 0.8], [1, 0.8]],
                 "person_box": {"x": 0.6, "head_y": 0.4, "feet_y": 0.8, "shoulder_w": 0.1},
                 "person_slots": [{"x": 0.2, "ground_y": 0.9, "scale": 0.9}],
                 "wet_ground": True, "objects": []}
        card_stage.compose(plate, card, tmp, 0.3, 0.9, 0.2, "left", 200, 0.0, 0.3, 0.8, 0.0, stage, True)
        sc = json.load(open(os.path.join(tmp, "scene.json"), encoding="utf-8"))
        assert abs(sc["ground_y"] - 0.8) < 1e-6, sc["ground_y"]
        assert abs(sc["x"] - 0.6) < 1e-6, sc["x"]
    check("合成：person_box 覆盖 slot", _person_box_scale)

    def _light_bbox_shadow():
        from PIL import Image
        import numpy as np
        import card_stage
        import layers
        tmp = tempfile.mkdtemp()
        plate = os.path.join(tmp, "plate.png"); card = os.path.join(tmp, "card.png")
        Image.new("RGB", (400, 300), (200, 200, 200)).save(plate)
        Image.new("RGBA", (40, 100), (230, 200, 150, 255)).save(card)
        stage = {"horizon_y": 0.4, "ground": [[0, 0.8], [1, 0.8]],
                 "lights": [{"dir": "right", "color": "warm", "strength": 0.9, "bbox": [0.8, 0.2, 0.95, 0.35]}],
                 "person_slots": [{"x": 0.5, "ground_y": 0.8, "scale": 0.33}],
                 "wet_ground": False, "objects": []}
        card_stage.compose(plate, card, tmp, 0.33, 0.8, 0.5, "left", 255, 0.0, 0.2, 0.9, 0.0, stage, True)
        im = np.asarray(Image.open(os.path.join(tmp, "comp.png")).convert("L"), dtype=np.float32)
        left = im[245:265, 150:190].mean()
        right = im[245:265, 230:270].mean()
        assert left < right - 3, (left, right)
    check("合成：投影朝灯的反方向", _light_bbox_shadow)

    def _lift_poly_guard():
        import lift as lift_mod
        assert lift_mod.lift_poly("no.png", [[0.1, 0.1], [0.2, 0.1], [0.2, 0.2]], "x.png") is None
    check("景物剥离：多边形不足 4 点返回 None", _lift_poly_guard)

    def _popup_cutout():
        """抠图接线：默认 BiRefNet 由 paper_cut 负责，coop_paper 只调调度。"""
        import card_stage
        src = open(os.path.join(ROOT, "tools", "coop_paper.py"), encoding="utf-8").read()
        cut = open(os.path.join(ROOT, "tools", "paper_cut.py"), encoding="utf-8").read()
        assert hasattr(card_stage, "comfy_cutout"), "缺 ComfyUI BiRefNet 抠图"
        assert "key_white" not in src and "key_green" not in src, "立体书仍在用色键"
        assert "comfy_cutout" in cut, "paper_cut 未接 BiRefNet"
        assert "paper_cut.cut" in src, "coop_paper 未接抠图调度"
    check("立体书：BiRefNet 抠图接线", _popup_cutout)

    def _popup_scenery():
        """画师分工：人物卡用人物画师，景物/背景用环境画师（2026-11-13 用户指定）。"""
        src = open(os.path.join(ROOT, "tools", "coop_paper.py"), encoding="utf-8").read()
        assert "a.env_lora" not in src, "立体书景物仍在用旧的环境 LoRA 字段"
        assert "env_artist" in src and "char_artist" in src, "画师未拆成人物/环境两路"
        assert '"name": env_artist' in src, "景物未用环境画师"
        assert src.count('"name": char_artist') >= 2, "人物卡未用人物画师"
        assert "PAPER_FG" not in src and "PAPER_PROP" not in src, "立体书仍在生成独立道具卡"
        assert "SCENERY_W" in src and "0.6" in src and "0.65" in src, "景物权重未集中"
    check("立体书：景物统一画师", _popup_scenery)

    def _card_ok():
        from PIL import Image
        import evidence
        tmp = tempfile.mkdtemp()
        bad = os.path.join(tmp, "bad.png")
        Image.new("RGBA", (200, 200), (200, 100, 100, 255)).save(bad)
        assert evidence.card_ok(bad)[0] is False
        good = os.path.join(tmp, "good.png")
        Image.new("RGBA", (100, 300), (0, 0, 0, 0)).save(good)
        im = Image.open(good); im.paste((200, 100, 100, 255), (20, 10, 80, 295)); im.save(good)
        assert evidence.card_ok(good)[0] is True
    check("卡片体检：拒绝方图/接受全身", _card_ok)

    def _feet_evidence():
        from PIL import Image
        import evidence
        tmp = tempfile.mkdtemp()
        p = os.path.join(tmp, "p.png"); c = os.path.join(tmp, "c.png")
        Image.new("RGB", (200, 200), (180, 180, 180)).save(p)
        im = Image.new("RGB", (200, 200), (180, 180, 180))
        for x in range(80, 120):
            for y in range(150, 165):
                im.putpixel((x, y), (80, 80, 80))
        im.save(c)
        ev = evidence.feet(p, c, (0.4, 0.2, 0.6, 0.8), False)
        assert ev["feet_dark"] > 0.1, ev
    check("证据：脚底暗部可量化", _feet_evidence)

    def _shadow_boost():
        from PIL import Image
        import numpy as np
        import card_stage
        import layers
        tmp = tempfile.mkdtemp()
        plate = os.path.join(tmp, "plate.png"); card = os.path.join(tmp, "card.png")
        Image.new("RGB", (400, 300), (200, 200, 200)).save(plate)
        Image.new("RGBA", (60, 150), (200, 180, 140, 255)).save(card)
        stage = {"horizon_y": 0.4, "ground": [[0, 0.8], [1, 0.8]], "lights": [],
                 "person_slots": [{"x": 0.5, "ground_y": 0.8, "scale": 0.35}],
                 "wet_ground": False, "objects": []}
        vals = []
        for i, boost in enumerate((1.0, 2.0)):
            out = os.path.join(tmp, "b%d" % i)
            os.makedirs(out, exist_ok=True)
            scene = {"layers": [{"card": card, "ratio": 0.35, "ground_y": 0.8, "x": 0.5,
                                  "shadow": 255, "shadow_boost": boost, "slot": True}],
                     "plate": plate, "stage": stage}
            sp = os.path.join(out, "scene.json")
            json.dump(scene, open(sp, "w", encoding="utf-8"))
            import layers
            import layers
            comp = layers.compose_layers(plate, sp, out)
            im = np.asarray(Image.open(comp).convert("L"), dtype=np.float32)
            vals.append(im[240:252, 170:230].mean())
        assert vals[1] < vals[0] - 2, vals
    check("合成：shadow_boost 加深脚底", _shadow_boost)

    def _check_card():
        import stage_parse
        old_m, old_c = stage_parse._model, stage_parse._call
        stage_parse._model = lambda: "mock"
        stage_parse._call = lambda *a, **k: '{"faces":2,"full_body":true,"feet_visible":true,"note":"twin"}'
        try:
            r = stage_parse.check_card("x.png")
            assert r["ok"] is False and r["faces"] == 2, r
        finally:
            stage_parse._model, stage_parse._call = old_m, old_c
    check("卡片质检：双脸被拒绝", _check_card)

    def _ss_size():
        from PIL import Image
        import card_stage
        import layers
        tmp = tempfile.mkdtemp()
        plate = os.path.join(tmp, "plate.png"); card = os.path.join(tmp, "card.png")
        Image.new("RGB", (200, 120), (90, 90, 100)).save(plate)
        Image.new("RGBA", (40, 90), (230, 210, 170, 255)).save(card)
        stage = {"horizon_y": 0.4, "ground": [[0, 0.8], [1, 0.8]], "lights": [],
                 "person_box": {"x": 0.5, "head_y": 0.45, "feet_y": 0.8, "shoulder_w": 0.1},
                 "wet_ground": False, "objects": []}
        scene = {"layers": [{"card": card, "ratio": 0.35, "ground_y": 0.8, "x": 0.5, "slot": True}],
                 "plate": plate, "stage": stage}
        sp = os.path.join(tmp, "scene.json"); json.dump(scene, open(sp, "w", encoding="utf-8"))
        comp = layers.compose_layers(plate, sp, tmp, 2, (0.4, 0.5, 0.6, 0.8))
        assert Image.open(comp).size == (200, 120)
    check("合成：2× 超采样输出原尺寸", _ss_size)

    def _ss_sharpen_guard():
        from PIL import Image
        import card_stage
        import layers
        tmp = tempfile.mkdtemp()
        plate = os.path.join(tmp, "plate.png"); card = os.path.join(tmp, "card.png")
        Image.new("RGB", (120, 90), (100, 100, 110)).save(plate)
        Image.new("RGBA", (30, 60), (220, 200, 160, 255)).save(card)
        stage = {"horizon_y": 0.4, "ground": [[0, 0.8], [1, 0.8]], "lights": [],
                 "person_slots": [{"x": 0.5, "ground_y": 0.8, "scale": 0.4}],
                 "wet_ground": False, "objects": []}
        scene = {"layers": [{"card": card, "ratio": 0.4, "ground_y": 0.8, "x": 0.5, "slot": True}],
                 "plate": plate, "stage": stage}
        sp = os.path.join(tmp, "scene.json"); json.dump(scene, open(sp, "w", encoding="utf-8"))
        comp = layers.compose_layers(plate, sp, tmp, 2, (5, -1, -5, 9))
        assert os.path.isfile(comp)
    check("合成：锐化框越界不崩", _ss_sharpen_guard)

    def _fusion_lowfreq():
        from PIL import Image
        import numpy as np
        import fusion
        tmp = tempfile.mkdtemp()
        plate = Image.new("RGB", (200, 200), (20, 40, 220))
        card = Image.new("RGBA", (60, 90), (150, 150, 150, 255))
        out, ring = fusion.lowfreq_match(card, plate, (70, 80, 130, 170))
        arr = np.asarray(out.convert("RGB"), dtype=np.float32)
        assert arr[..., 2].mean() > 155, "蓝色环境没有进卡片"
        assert arr[..., 2].mean() <= 165, "低频搬过头"
        assert abs(ring[2] - 220) < 12, ring
    check("融合：低频色偏进入卡片", _fusion_lowfreq)

    def _tangent():
        import math, fusion
        a = fusion.ground_tangent([[0, 0.5], [1, 0.8]], 0.5)
        assert abs(a - math.atan2(0.3, 1)) < 1e-6, a
        assert fusion.ground_tangent([], 0.5) == 0.0
    check("融合：地面切线", _tangent)

    def _scale_bias_src():
        src = open(os.path.join(ROOT, "tools", "coop_paper.py"), encoding="utf-8").read()
        assert "--scale-bias" in src and "scale_bias" in src, "没有比例系数"
        sh = open(os.path.join(ROOT, "tools", "shot.py"), encoding="utf-8").read()
        assert "0.58" in sh or "0.68" in sh, "镜头上限没放宽"
    check("构图：比例系数已接线", _scale_bias_src)

    def _card_shoes():
        import stage_parse
        old_m, old_c = stage_parse._model, stage_parse._call
        stage_parse._model = lambda: "mock"
        stage_parse._call = lambda *a, **k: '{"faces":1,"full_body":true,"feet_visible":true,"shoes":false}'
        try:
            r = stage_parse.check_card("x.png", want_shoes=True)
            assert r["ok"] is False and r["shoes"] is False, r
            assert stage_parse.check_card("x.png", want_shoes=False)["ok"] is True
        finally:
            stage_parse._model, stage_parse._call = old_m, old_c
    check("卡片质检：没鞋判失败", _card_shoes)

    def _clean_char_prompt():
        import coop_paper
        txt = "(1girl:1.2), (soft bokeh background:1.3), (shallow depth of field:1.2), (upper body close-up:1.1), (white blouse:1.2)"
        out, n = coop_paper.clean_char_prompt(txt)
        assert n == 3 and "1girl" in out and "white blouse" in out, (out, n)
        assert "bokeh" not in out and "depth of field" not in out and "close-up" not in out
    check("提示词：人物剔除景深/特写块", _clean_char_prompt)

    def _stage_style_filter():
        import coop_paper
        s = coop_paper.stage_style_for_char("soft painterly anime, warm gaslight, wet stone, dreamy haze")
        assert "warm gaslight" in s and "wet stone" in s, s
        assert "soft" not in s and "painterly" not in s and "haze" not in s, s
    check("提示词：风格词过滤", _stage_style_filter)

    def _char_prompt_sharp():
        src = open(os.path.join(ROOT, "tools", "coop_paper.py"), encoding="utf-8").read()
        pr = open(os.path.join(ROOT, "tools", "paper_prompts.py"), encoding="utf-8").read()
        assert "sharp focus" in pr and "crisp lineart" in pr, "缺清晰度正向"
        assert "depth of field, bokeh" in src and "soft focus" in src, "缺模糊负向"
        assert "1024x1536" in src and "--char-size" in src, "缺人物尺寸"
    check("提示词：清晰度与尺寸接线", _char_prompt_sharp)

    def _char_empty_fallback():
        src = open(os.path.join(ROOT, "tools", "coop_paper.py"), encoding="utf-8").read()
        assert "full body standing" in src and "if not base_char.strip()" in src, "空提示词没回退"
    check("提示词：过滤后空串回退", _char_empty_fallback)

    def _ui_char_common():
        js = open(os.path.join(ROOT, "station", "static", "app.js"), encoding="utf-8").read()
        assert "function coopCharCommon" in js, "前端没有人物公共层过滤"
        assert "merge(coopCharCommon(cpos), blocks)" in js, "人物正面没走过滤"
        assert "cat === 'comp' || cat === 'cam'" in js, "comp/cam 没排除"
    check("提示词：前端分流 comp/cam 不再进人物", _ui_char_common)
