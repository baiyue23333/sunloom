# -*- coding: utf-8 -*-
"""抠图回归：软 alpha / 白边 / 空洞。

2026-11-13 拆出来：stage_tests.py 已到 20KB 红线。
"""
import os
import sys
import tempfile


def run(check, ROOT):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import numpy as np
    from PIL import Image, ImageDraw
    import cutout

    def _soft_edge():
        """过边扫描线必须有中间 alpha：旧版 np.where(a>128,...) 只剩 0/255。"""
        px = np.zeros((64, 64, 4), np.uint8)   # 透明背景，真实抠图就是这样
        px[16:48, 16:48] = [30, 30, 40, 255]
        src = Image.fromarray(px, "RGBA")
        a = np.asarray(cutout.defringe(src, mode="clean").split()[-1]).astype(np.float32) / 255.0
        row = a[32, 10:24]                      # 横穿左边轮廓
        mid = ((row > 0.05) & (row < 0.95)).sum()
        assert mid >= 1, "边缘被二值化：%s" % row.round(2)
    check("抠图：软 alpha 不被二值化", _soft_edge)

    def _ink_outline():
        """勾边只压暗轮廓，alpha 一个像素都不能动。"""
        px = np.zeros((60, 60, 4), np.uint8)
        px[15:45, 15:45] = [255, 255, 255, 255]
        src = Image.fromarray(px, "RGBA")
        out = cutout.ink_outline(src, width=2, strength=0.7)
        a0 = np.asarray(src)[..., 3]
        a1 = np.asarray(out)[..., 3]
        assert np.array_equal(a0, a1), "勾边改动了 alpha"
        rgb0 = np.asarray(src)[..., :3].astype(np.int16)
        rgb1 = np.asarray(out)[..., :3].astype(np.int16)
        assert rgb1[16, 30, 0] < rgb0[16, 30, 0], "轮廓内侧没有被压暗"
        assert rgb1[30, 30, 0] == rgb0[30, 30, 0], "中心不该被压暗"
    check("抠图：勾边只压轮廓、不动 alpha", _ink_outline)

    def _reflection_lower_only():
        """倒影只能来自卡片下半身：镜像上半身会在亮地面上糊出“第二个人”。"""
        import tempfile, card_stage
        d = tempfile.mkdtemp()
        plate = Image.new("RGB", (640, 360), (120, 120, 120))
        pp = os.path.join(d, "plate.png"); plate.save(pp)
        card = Image.new("RGBA", (120, 300), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rectangle((20, 0, 100, 150), fill=(255, 0, 0, 255))    # 上半身：红
        cd.rectangle((20, 150, 100, 300), fill=(0, 0, 255, 255))  # 腿脚：蓝
        cp = os.path.join(d, "card.png"); card.save(cp)
        out = card_stage.compose(pp, cp, d, 0.5, 0.8, 0.5, "left", 200, 0.9, 0.45, 0.8,
                                 0.0, None, False, 1.0, False, "feet")
        arr = np.asarray(Image.open(out).convert("RGB")).astype(np.int16)
        feet = int(360 * 0.8)
        band = arr[feet + 6:feet + 40]
        assert band.size, "倒影带为空"
        assert band[..., 2].mean() > band[..., 0].mean(), "倒影把上半身镜像下来了（红占优）"
    check("合成：倒影只取下半身", _reflection_lower_only)

    def _contact_shadow():
        """脚底必须有硬接触阴影，否则人物像浮在地面上。"""
        import tempfile, card_stage, evidence
        d = tempfile.mkdtemp()
        plate = Image.new("RGB", (640, 360), (200, 200, 200))
        pp = os.path.join(d, "plate.png"); plate.save(pp)
        card = Image.new("RGBA", (120, 300), (0, 0, 0, 0))
        ImageDraw.Draw(card).rectangle((25, 0, 95, 300), fill=(255, 255, 255, 255))
        cp = os.path.join(d, "card.png"); card.save(cp)
        out = card_stage.compose(pp, cp, d, 0.6, 0.8, 0.5, "left", 0, 0.0, 0.45, 0.8,
                                 0.0, None, False, 1.0, False, "feet")
        box = (0.3, 0.6, 0.7, 0.8)
        ev = evidence.feet(pp, out, box, False)
        assert ev["contact_hard"] >= 0.25, "接触阴影不足：%s" % ev
    check("合成：脚底硬接触阴影", _contact_shadow)

    def _preset_fixed():
        """定稿 preset 必须存在且背景板可找到。"""
        import json
        p = os.path.join(ROOT, "ref", "paper_presets.json")
        assert os.path.isfile(p), "缺少 ref/paper_presets.json"
        data = json.load(open(p, encoding="utf-8"))
        fx = data.get("fixed_001")
        assert fx, "缺少 fixed_001"
        for k in ("scene", "char", "seed", "cutout"):
            assert k in fx, "fixed_001 缺字段 %s" % k
        rp = fx.get("reuse_plate") or ""
        rp = rp if os.path.isabs(rp) else os.path.join(ROOT, rp)
        if not os.path.isfile(rp):
            return
    check("配置：定稿 preset 完整", _preset_fixed)

    def _no_halo():
        """边缘沾了背景白 → clean 模式要把它换成主体色。"""
        px = np.zeros((64, 64, 4), np.uint8)   # 透明背景，真实抠图就是这样
        px[16:48, 16:48] = [30, 30, 40, 255]
        px[16:48, 15] = px[16:48, 48] = [30, 30, 40, 128]
        px[15, 16:48] = px[48, 16:48] = [30, 30, 40, 128]
        # 把这些半透明边弄成"白污染"（真实白底渲染就是这样）
        px[16:48, 15] = px[16:48, 48] = [255, 255, 255, 128]
        px[15, 16:48] = px[48, 16:48] = [255, 255, 255, 128]
        src = Image.fromarray(px, "RGBA")
        out = cutout.defringe(src, mode="clean")
        cols = np.asarray(out.convert("RGB")).astype(np.float32)
        ring = cols[15, 16:48]
        dist = float(np.linalg.norm(ring - np.array([30, 30, 40], np.float32), axis=1).mean())
        assert dist < 60, "边缘仍是背景色（污染度 %.1f）" % dist
    check("抠图：边缘不发白", _no_halo)
    def _no_hole():
        """白衣服不许被挖空。"""
        im = Image.new("RGB", (80, 120), (255, 255, 255))
        px = np.array(im)
        px[10:20, 30:50] = (235, 225, 200)
        px[20:100, 20:60] = (250, 250, 245)
        tmp = tempfile.mkdtemp()
        sp = os.path.join(tmp, "w.png")
        Image.fromarray(px).save(sp)
        a = np.asarray(cutout.make_matte(sp, backend="color", mode="clean").split()[-1]).astype(np.float32) / 255.0
        solid = a[a > 0.5]
        assert solid.size > 100, "主体太小"
        assert (solid > 0.9).mean() > 0.9, "主体内部有空洞"
    check("抠图：内部无空洞", _no_hole)

    def _backends():
        for b in ("birefnet", "u2net", "isnet_anime", "color"):
            assert b in cutout.BACKENDS, "缺后端 " + b
    check("抠图：后端清单齐全", _backends)
    def _chroma_clean():
        """纯绿底 + 白主体：背景必须抠净、主体必须完整（含中空绿洞）。"""
        px = np.zeros((120, 120, 3), np.uint8)
        px[:, :] = (0, 200, 60)                    # 绿幕
        px[30:90, 30:90] = (245, 245, 240)         # 白色主体
        px[52:68, 52:68] = (0, 200, 60)            # 主体中间的绿洞
        tmp = tempfile.mkdtemp()
        sp = os.path.join(tmp, "g.png")
        Image.fromarray(px).save(sp)
        rgba = cutout.make_matte(sp, backend="chroma", crop=False)
        a = np.asarray(rgba.split()[-1]).astype(np.float32) / 255.0
        assert a[5, 5] < 0.05, "角落背景没抠掉: %.2f" % a[5, 5]
        assert a[40, 40] > 0.95, "主体被抠掉: %.2f" % a[40, 40]
        assert a[60, 60] < 0.2, "中空绿洞没挖开: %.2f" % a[60, 60]
    check("色键：绿幕抠净 + 中空挖开", _chroma_clean)

    def _chroma_guard():
        """白底图喂给色键：必须报错回退，不能抠出一堆碎块。"""
        im = Image.new("RGB", (80, 80), (255, 255, 255))
        tmp = tempfile.mkdtemp()
        sp = os.path.join(tmp, "w.png")
        im.save(sp)
        try:
            cutout.make_matte(sp, backend="chroma", crop=False)
        except cutout.CutoutError:
            return
        raise AssertionError("白底图没有被拒绝")
    check("色键：非绿幕背景必须回退", _chroma_guard)
    def _chroma_outline():
        """色键不许几何腐蚀：2px 黑描边必须完整保留（旧版 erode 会削掉）。"""
        px = np.zeros((120, 120, 3), np.uint8)
        px[:, :] = (0, 200, 60)
        px[30:90, 30:90] = (245, 245, 240)          # 白主体
        px[30:90, 30:32] = (25, 25, 30)             # 左侧 2px 黑描边
        tmp = tempfile.mkdtemp()
        sp = os.path.join(tmp, "o.png")
        Image.fromarray(px).save(sp)
        rgba = cutout.make_matte(sp, backend="chroma", crop=False)
        a = np.asarray(rgba.split()[-1]).astype(np.float32) / 255.0
        assert a[60, 31] > 0.9, "描边被削掉了: %.2f" % a[60, 31]
        assert a[60, 30] > 0.5, "描边外沿被削掉了: %.2f" % a[60, 30]
    check("色键：2px 描边不被腐蚀", _chroma_outline)

    def _chroma_area():
        """轮廓面积必须接近原始主体（旧版每边缩 1px，损失约 2%）。"""
        px = np.zeros((140, 140, 3), np.uint8)
        px[:, :] = (0, 200, 60)
        import cv2 as _cv
        _cv.circle(px, (70, 70), 45, (240, 240, 235), -1)
        ref = int((px[:, :, 0].astype(int) > 150).sum())   # 主体 R=240，背景 R=0
        tmp = tempfile.mkdtemp()
        sp = os.path.join(tmp, "a.png")
        Image.fromarray(px).save(sp)
        rgba = cutout.make_matte(sp, backend="chroma", crop=False)
        a = np.asarray(rgba.split()[-1]).astype(np.float32) / 255.0
        got = int((a > 0.5).sum())
        err = abs(got - ref) / float(ref) * 100
        assert err <= 1.0, "轮廓面积误差 %.2f%%（>1%%）" % err
    check("色键：轮廓面积误差 ≤1%", _chroma_area)
    def _sharpen():
        """边缘锐化：过渡带必须变窄，alpha 不越界，面积不超过 1%。"""
        px = np.zeros((140, 140, 3), np.uint8)
        px[:, :] = (0, 200, 60)
        import cv2 as _cv
        _cv.circle(px, (70, 70), 45, (240, 240, 235), -1, lineType=_cv.LINE_AA)
        px = _cv.GaussianBlur(px, (3, 3), 0.8)      # 造出真实抗锯齿过渡带
        tmp = tempfile.mkdtemp()
        sp = os.path.join(tmp, "s.png")
        Image.fromarray(px).save(sp)
        raw, _ = cutout._chroma_raw(sp, sharpen=False)
        sharp, _ = cutout._chroma_raw(sp, sharpen=True)
        a0 = np.asarray(raw.split()[-1]).astype(np.float32) / 255.0
        a1 = np.asarray(sharp.split()[-1]).astype(np.float32) / 255.0
        b0 = int(((a0 > 0.1) & (a0 < 0.9)).sum())
        b1 = int(((a1 > 0.1) & (a1 < 0.9)).sum())
        assert b1 < b0, "锐化没有收窄过渡带：%d → %d" % (b0, b1)
        assert float(a1.min()) >= 0.0 and float(a1.max()) <= 1.0, "alpha 越界"
        n0, n1 = int((a0 > 0.5).sum()), int((a1 > 0.5).sum())
        assert abs(n1 - n0) / max(1, n0) <= 0.01, "锐化改变了轮廓面积 %d → %d" % (n0, n1)
    check("色键：边缘锐化收窄过渡且不改面积", _sharpen)
    def _premul_resize():
        """RGBA 缩放必须预乘：半透明纯色缩放后颜色不能被透明像素带偏。"""
        im = Image.new("RGBA", (40, 40), (255, 0, 0, 128))
        # 边缘放一圈全透明"脏色"像素，模拟抠图后残留的背景色
        arr = np.asarray(im).copy()
        arr[:3, :, :] = (0, 200, 60, 0)          # 三边各 3px 全透明"脏色"
        arr[-3:, :, :] = (0, 200, 60, 0)
        arr[:, :3, :] = (0, 200, 60, 0)
        arr[:, -3:, :] = (0, 200, 60, 0)
        im = Image.fromarray(arr, "RGBA")
        up = cutout.resize_rgba(im, (80, 80))
        back = cutout.resize_rgba(up, (40, 40))
        c = np.asarray(back).astype(np.float32)[20, 20]
        assert abs(c[0] - 255) < 4 and c[1] < 6 and c[2] < 6, "预乘缩放把颜色带偏了: %s" % c
        # 直乘版本必须更差（否则这条测试没意义）
        raw = im.resize((80, 80), Image.LANCZOS).resize((40, 40), Image.LANCZOS)
        rc = np.asarray(raw).astype(np.float32)[20, 20]
        assert abs(rc[0] - 255) >= abs(c[0] - 255), "直乘反而更准，测试前提不成立"
    check("预乘缩放：半透明颜色不被带偏", _premul_resize)

    def _premul_area():
        """预乘缩放不能改变覆盖量。"""
        im = Image.new("RGBA", (60, 60), (10, 20, 30, 0))
        ImageDraw.Draw(im).ellipse((10, 10, 50, 50), fill=(200, 60, 60, 255))
        a0 = np.asarray(cutout.resize_rgba(im, (120, 120)).split()[-1]).astype(np.float32).sum()
        a1 = np.asarray(im.split()[-1]).astype(np.float32).sum() * 4.0
        assert abs(a0 - a1) / a1 <= 0.01, "缩放改变了覆盖量 %.2f%%" % (abs(a0-a1)/a1*100)
    check("预乘缩放：覆盖量不变", _premul_area)
    def _unsharp():
        """整图锐化：amount=0 必须原样返回；0.4 必须让梯度上升且不越界。"""
        im = Image.new("RGB", (64, 64), (255, 255, 255))
        ImageDraw.Draw(im).rectangle((20, 20, 44, 44), fill=(60, 60, 60))
        same = cutout.unsharp_rgb(im, amount=0.0)
        assert np.asarray(same).tolist() == np.asarray(im).tolist(), "amount=0 改变了图像"
        sharp = cutout.unsharp_rgb(im, amount=0.4)
        a0 = np.asarray(im).astype(np.float32)
        a1 = np.asarray(sharp).astype(np.float32)
        g0 = float(np.abs(np.diff(a0[..., 0], axis=1)).mean())
        g1 = float(np.abs(np.diff(a1[..., 0], axis=1)).mean())
        assert g1 > g0, "整图锐化没有提高梯度 %.2f → %.2f" % (g0, g1)
        assert 0.0 <= float(a1.min()) and float(a1.max()) <= 255.0, "锐化越界"
    check("整图锐化：0 不改图，0.4 提梯度", _unsharp)
    def _chroma_fringe():
        """飞边：主体外 25% 覆盖的淡影必须被收掉，1px 细线必须保留。"""
        px = np.zeros((120, 120, 3), np.uint8)
        green = np.array([0, 200, 60], np.float32)
        white = np.array([245, 245, 240], np.float32)
        px[:, :] = green.astype(np.uint8)
        px[30:90, 30:90] = white.astype(np.uint8)
        # 外圈 2px 淡影：25% 主体 + 75% 背景（正是"飞边"的成因）
        fringe = (0.25 * white + 0.75 * green).astype(np.uint8)
        px[28:30, 28:92] = fringe
        px[90:92, 28:92] = fringe
        px[28:92, 28:30] = fringe
        px[28:92, 90:92] = fringe
        px[58:60, 10:28] = white.astype(np.uint8)      # 1px 细线（发丝）
        tmp = tempfile.mkdtemp()
        sp = os.path.join(tmp, "f.png")
        Image.fromarray(px).save(sp)
        rgba = cutout.make_matte(sp, backend="chroma", crop=False)
        a = np.asarray(rgba.split()[-1]).astype(np.float32) / 255.0
        assert a[29, 60] < 0.10, "淡影没被收掉: %.2f" % a[29, 60]
        assert a[59, 20] > 0.85, "细线被吃掉了: %.2f" % a[59, 20]
        assert a[60, 60] > 0.95, "主体受损"
    check("色键：飞边淡影被收掉、细线保留", _chroma_fringe)

    def _chroma_decon():
        """去污染：半透明边缘不得带背景绿。"""
        px = np.zeros((120, 120, 3), np.uint8)
        green = np.array([0, 200, 60], np.float32)
        white = np.array([240, 240, 236], np.float32)
        px[:, :] = green.astype(np.uint8)
        px[30:90, 30:90] = white.astype(np.uint8)
        px[30:90, 30:32] = (0.45 * white + 0.55 * green).astype(np.uint8)
        tmp = tempfile.mkdtemp()
        sp = os.path.join(tmp, "d.png")
        Image.fromarray(px).save(sp)
        rgba = cutout.make_matte(sp, backend="chroma", crop=False)
        arr = np.asarray(rgba).astype(np.float32)
        band = (arr[..., 3] > 20) & (arr[..., 3] < 200)
        assert band.any(), "没有半透明边可测"
        G_ex = (arr[..., 1] - np.maximum(arr[..., 0], arr[..., 2]))[band]
        assert float(G_ex.mean()) < 25.0, "边缘仍偏绿（绿优势 %.1f）" % float(G_ex.mean())
    check("色键：边缘不带背景绿", _chroma_decon)
    def _green_rim():
        """模型画在轮廓上的不透明绿边必须被删掉；人物内部的绿色区域必须保留。"""
        px = np.zeros((140, 140, 3), np.uint8)
        px[:, :] = (0, 200, 60)
        px[30:110, 30:110] = (240, 240, 236)
        # 轮廓最外 2px 的不透明橄榄绿（模型的环境光溢色）
        rim = np.array([60, 95, 30], np.uint8)
        px[28:30, 28:112] = rim; px[110:112, 28:112] = rim
        px[28:112, 28:30] = rim; px[28:112, 110:112] = rim
        px[60:80, 60:80] = (120, 60, 40)      # 人物内部的暗棕：不该被删
        tmp = tempfile.mkdtemp()
        sp = os.path.join(tmp, "r.png")
        Image.fromarray(px).save(sp)
        rgba = cutout.make_matte(sp, backend="chroma", crop=False)
        arr = np.asarray(rgba).astype(np.float32)
        a = arr[..., 3] / 255.0
        gex = arr[..., 1] - np.maximum(arr[..., 0], arr[..., 2])
        # 绿边要么被删掉（alpha 归零），要么被全局去绿（不再绿）——两者都算合格
        assert a[29, 70] < 0.15 or gex[29, 70] < 10, "轮廓绿边没处理: a=%.2f gex=%.1f" % (a[29, 70], gex[29, 70])
        assert a[70, 70] > 0.9, "人物内部像素被误删: %.2f" % a[70, 70]
    check("色键：轮廓绿边被删、内部绿保留", _green_rim)
    def _aa_presets():
        """色键必须保留抗锯齿，且 soft ≥ normal ≥ crisp（过渡像素数）。"""
        import cv2 as _cv
        px = np.zeros((140, 140, 3), np.uint8)
        px[:, :] = (0, 190, 40)
        _cv.circle(px, (70, 70), 45, (240, 240, 236), -1, lineType=_cv.LINE_AA)
        px = _cv.GaussianBlur(px, (3, 3), 0.9)
        tmp = tempfile.mkdtemp()
        sp = os.path.join(tmp, "aa.png")
        Image.fromarray(px).save(sp)
        counts = {}
        for aa in ("soft", "normal", "crisp"):
            rgba = cutout.make_matte(sp, backend="chroma", crop=False, aa=aa)
            arr = np.asarray(rgba).astype(np.float32) / 255.0
            a = arr[..., 3]
            counts[aa] = int(((a > 0.05) & (a < 0.95)).sum())
        assert counts["soft"] > 0, "soft 档完全没有抗锯齿像素"
        assert counts["soft"] >= counts["normal"] >= counts["crisp"], "档位顺序不对: %s" % counts
    check("色键：抗锯齿档位 soft≥normal≥crisp", _aa_presets)

    def _aa_soft_has_mid():
        """soft 档必须真的产生中间 alpha（不是二值）。"""
        import cv2 as _cv
        px = np.zeros((120, 120, 3), np.uint8)
        px[:, :] = (0, 190, 40)
        _cv.circle(px, (60, 60), 38, (238, 238, 234), -1, lineType=_cv.LINE_AA)
        px = _cv.GaussianBlur(px, (3, 3), 1.1)
        tmp = tempfile.mkdtemp()
        sp = os.path.join(tmp, "aa2.png")
        Image.fromarray(px).save(sp)
        rgba = cutout.make_matte(sp, backend="chroma", crop=False, aa="soft")
        row = (np.asarray(rgba).astype(np.float32)[60, :, 3]) / 255.0
        mid = ((row > 0.2) & (row < 0.8)).sum()
        assert mid >= 1, "soft 档扫描线没有中间值: %s" % row[max(0, 20):40].round(2)
    check("色键：soft 档有真实中间 alpha", _aa_soft_has_mid)
