# -*- coding: utf-8 -*-
"""v8 镜头/舞台 v3/特写锚点测试。"""
import json
import os
import sys
import tempfile

import numpy as np


def run(check, ROOT):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    def _shot_resolve():
        import shot
        s, r, f, a = shot.resolve("auto", "character", {"shot": "far"}, 1.0)
        assert s == "near" and f == "full" and a == "feet", (s, r, f, a)
        s2, r2, f2, a2 = shot.resolve("closeup", "scenery", {}, 1.2)
        assert s2 == "closeup" and f2 == "bust" and a2 == "bottom", (s2, r2, f2, a2)
        assert 0.70 <= r2 <= 0.86
        s3, r3, _, _ = shot.resolve("auto", "auto", {"shot": "far"}, 1.12)
        assert s3 == "far" and 0.18 <= r3 <= 0.28, (s3, r3)
    check("镜头：auto/优先/特写解析", _shot_resolve)

    def _stage_v3():
        import stage_parse
        s = stage_parse._clamp({"shot": "huge", "priority": "people",
                                "details": ["a", "b", "c", "d", "e", "f"],
                                "char_details": ["x"],
                                "interaction": {"surface": "wet stone!", "wind": "gale", "wet": True}})
        assert s["shot"] == "mid" and s["priority"] == "balanced", s
        assert len(s["details"]) == 5, s["details"]
        assert s["interaction"]["wind"] == "none" and "stone" in s["interaction"]["surface"]
    check("舞台 v3：镜头/细节/互动钳制", _stage_v3)

    def _closeup_anchor():
        from PIL import Image
        import numpy as np
        import layers
        tmp = tempfile.mkdtemp()
        plate = os.path.join(tmp, "plate.png"); card = os.path.join(tmp, "card.png")
        Image.new("RGB", (200, 200), (240, 240, 240)).save(plate)
        Image.new("RGBA", (80, 120), (220, 200, 170, 255)).save(card)
        stage = {"horizon_y": 0.4, "ground": [[0, 0.8], [1, 0.8]], "lights": [], "wet_ground": False}
        def run_anchor(anchor):
            out = os.path.join(tmp, anchor); os.makedirs(out, exist_ok=True)
            scene = {"layers": [{"card": card, "ratio": 0.5, "ground_y": 0.8, "x": 0.5,
                                  "slot": True, "anchor": anchor}], "plate": plate, "stage": stage}
            sp = os.path.join(out, "scene.json"); json.dump(scene, open(sp, "w", encoding="utf-8"))
            comp = layers.compose_layers(plate, sp, out, 1, None)
            return np.asarray(Image.open(comp).convert("L"), dtype=np.float32)
        run_anchor("feet")
        run_anchor("bottom")
        box_f = json.load(open(os.path.join(tmp, "feet", "_c00", "scene.json"), encoding="utf-8"))["box"]
        box_b = json.load(open(os.path.join(tmp, "bottom", "_c00", "scene.json"), encoding="utf-8"))["box"]
        assert abs(box_f[3] - 160) <= 2, box_f
        assert abs(box_b[3] - 200) <= 2, box_b
    check("合成：特写贴底不画脚底阴影", _closeup_anchor)

    def _plate_detail():
        import paper_prompts
        assert "complete illustration" in paper_prompts.PLATE_DETAIL
        src = open(os.path.join(ROOT, "tools", "coop_paper.py"), encoding="utf-8").read()
        assert "PLATE_DETAIL" in src and "details" in src, "背景板没接细节"
    check("提示词：背景板细节预算", _plate_detail)

    def _closeup_prompt():
        src = open(os.path.join(ROOT, "tools", "coop_paper.py"), encoding="utf-8").read()
        pr = open(os.path.join(ROOT, "tools", "paper_prompts.py"), encoding="utf-8").read()
        assert "upper body portrait" in pr and "waist-up" in pr, "特写取景词没接"
        assert "char_details" in src and "wind-blown hair" in src, "互动/细节没接"
    check("提示词：特写取景与互动", _closeup_prompt)

    def _ui_shot():
        js = open(os.path.join(ROOT, "station", "static", "app.js"), encoding="utf-8").read()
        html = open(os.path.join(ROOT, "station", "static", "index.html"), encoding="utf-8").read()
        # 2026-11-14：高级参数面板删除，合作模式固定重映；面板改为三页签 + 选择器
        assert "reproj-add-scene" in html and "reproj-views" in html, "重映面板没场景/视角控件"
        assert "reproj-tabs" in html and "rtab-char" in html, "重映面板没页签"
        assert "reprojExtraEnv" in js and "reprojExtraChar" in js, "前端没把选择器并进提示词"
        assert "reprojJumpPalette" in js and "reprojAddScene" in js, "场景跳转/落位函数缺失"
        assert "mode: 'reproject'" in js, "前端没固定重映模式"
    check("站台：重映工作台控件", _ui_shot)

    def _support_image():
        from PIL import Image
        import numpy as np
        import support_matte
        im = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        for x in range(10, 30):
            for y in range(10, 30):
                im.putpixel((x, y), (30, 60, 220, 255))
        out = np.asarray(support_matte.support_image(im).convert("RGB"), dtype=np.float32)
        assert out[0, 0, 0] > 150 and out[0, 0, 1] > 150 and out[0, 0, 2] < 100, out[0, 0]
    check("抠图实验：互补支撑色", _support_image)

    def _silhouette_mask():
        from PIL import Image, ImageDraw
        import silhouette
        im = Image.new("RGB", (200, 300), (255, 255, 255))
        d = ImageDraw.Draw(im)
        d.rectangle((60, 40, 140, 260), fill=(0, 0, 0))
        al = silhouette.mask_from_image(im)
        assert al is not None
        a = np.asarray(al)
        assert 0.15 < (a > 128).mean() < 0.45, (a > 128).mean()
        blank = silhouette.mask_from_image(Image.new("RGB", (100, 100), (255, 255, 255)))
        assert blank is None
    check("剪影：黑块成 mask，空白返回 None", _silhouette_mask)

    def _mask_assemble():
        from PIL import Image
        import mask_card
        rgb = Image.new("RGB", (40, 40), (200, 180, 160))
        m = Image.new("L", (40, 40), 0)
        for x in range(10, 30):
            for y in range(10, 30):
                m.putpixel((x, y), 255)
        out = mask_card.assemble(rgb, m)
        a = np.asarray(out.split()[3])
        assert a[20, 20] == 255 and a[0, 0] == 0
    check("蒙版卡：alpha 等于剪影", _mask_assemble)


