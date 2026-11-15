# -*- coding: utf-8 -*-
"""异型画布（paper_lineart）的离线检查：蒙版几何 + 接线。"""
import os
import sys


def run(check, ROOT):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import numpy as np
    from PIL import Image

    def _masks():
        import paper_lineart as pl
        names = pl.make_masks((500, 180, 780, 700), [(900, 500, 1200, 760)])
        ims = {}
        for k, n in names.items():
            import comfy_paths
            p = os.path.join(comfy_paths.COMFY_IN, n)
            ims[k] = np.asarray(Image.open(p).convert("L")) > 128
        assert not (ims["char"] & ims["fg"]).any(), "角色与前景蒙版重叠"
        union = ims["char"] | ims["fg"] | ims["env"]
        # 蒙版边缘做了羽化，二值化后会有 ~0.1% 的缝合线，允许到 99.5%
        assert union.mean() > 0.995, "蒙版没有覆盖整幅画布：%.3f" % union.mean()
        assert ims["env"].mean() > 0.6, "背景蒙版过小"

    check("异型画布：三块蒙版互斥且覆盖", _masks)

    def _wiring():
        src = open(os.path.join(ROOT, "tools", "paper_lineart.py"), encoding="utf-8").read()
        assert "def t2i(" in src and "def inpaint(" in src
        assert "env_artist" in src and "char_artist" in src, "角色/环境画师参数缺失"
        assert "SetLatentNoiseMask" not in src

    check("异型画布：线稿管线接线", _wiring)

    def _sanitizers():
        import paper_lineart as pl
        # 否定词里与正向冲突的必须被剔除（run3 曾因 'standing upright' 把角色否没）
        neg = pl.clean_neg("holding books, standing upright, low quality", "1girl, standing")
        assert "standing" not in neg, "冲突否定词未剔除: %s" % neg
        assert "low quality" in neg
        # 前景不能与场景冲突（run2 便利店被写成 library）
        kept = pl.clean_fg([{"prompt": "A hanging Library sign", "x": 0.5}], "convenience store")
        assert not kept, "冲突前景未过滤"
        kept2 = pl.clean_fg([{"prompt": "crates on the floor", "x": 0.5}], "convenience store")
        assert len(kept2) == 1

    check("异型画布：否定词与前景冲突清洗", _sanitizers)

    def _geometry():
        import paper_lineart as pl
        from PIL import Image
        import numpy as np
        # 线稿灰底必须被拉成白底（run4 半透明的根因）
        img = Image.new("RGB", (32, 32), (200, 200, 200))
        out = np.asarray(pl.white_levels(img)).mean()
        assert out > 240, "灰底未拉白：%.0f" % out
        assert pl.fg_kind("hanging neon sign") == "top"
        assert pl.fg_kind("door frame") == "side"
        assert pl.fg_kind("railing") == "bottom"

    check("异型画布：线稿白化与前景分类", _geometry)

    def _hand_poly():
        import json, tempfile
        import hand_precise as hp
        # 姿态 JSON 里的 21 点 → 凸包；缺失时必须返回 None（不能抛）
        pts = []
        for i in range(21):
            pts += [100 + (i % 5) * 12, 200 + (i % 7) * 9, 0.9]
        data = [{"canvas_width": 800, "canvas_height": 1000,
                 "people": [{"hand_right_keypoints_2d": pts}]}]
        p = os.path.join(tempfile.gettempdir(), "hand_pose_test.json")
        json.dump(data, open(p, "w", encoding="utf-8"))
        hull = hp.hand_polygon(p, "right")
        assert hull is not None and len(hull) >= 3, "凸包失败"
        xs = [pt[0][0] for pt in hull]
        assert min(xs) < 100 and max(xs) > 100 + 48, "凸包没有外扩"
        assert hp.hand_polygon(p, "left") is None, "空手应返回 None"

    check("手部：关键点凸包蒙版", _hand_poly)
