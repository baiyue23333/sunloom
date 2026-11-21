# -*- coding: utf-8 -*-
"""骨架蒙版：SDPose 的 18 个身体点 → 躯干多边形 + 四肢粗带 + 头部椭圆。

适用前提：画面里**已经有人**（素体法）。在空区域上没得用。
"""
import json
import math
import os

from PIL import Image, ImageDraw, ImageFilter
import numpy as np

# COCO-18 顺序
NOSE, NECK = 0, 1
RS, RE, RW = 2, 3, 4
LS, LE, LW = 5, 6, 7
RH, RK, RA = 8, 9, 10
LH, LK, LA = 11, 12, 13
REYE, LEYE, REAR, LEAR = 14, 15, 16, 17


def load_pose(json_path):
    d = json.load(open(json_path, encoding="utf-8"))
    if isinstance(d, dict):
        d = [d]
    p = (d[0].get("people") or [{}])[0]
    arr = p.get("pose_keypoints_2d") or []
    pts = [(arr[i], arr[i + 1], arr[i + 2]) for i in range(0, len(arr) - 2, 3)]
    return pts, int(d[0].get("canvas_width") or 0), int(d[0].get("canvas_height") or 0)


def _humanoid(M, box, W, H):
    """骨架塌缩时的兜底：按人体比例画一个人形蒙版。"""
    x0, y0, x1, y1 = [int(v) for v in box]
    bw, bh = max(8, x1 - x0), max(20, y1 - y0)
    d = ImageDraw.Draw(M)
    cx = (x0 + x1) / 2
    # 头
    hr = bh * 0.085
    d.ellipse((cx - hr, y0, cx + hr, y0 + hr * 2.1), fill=255)
    # 躯干（肩宽 → 腰宽）
    sw, hw = bw * 0.5, bw * 0.38
    d.polygon([(cx - sw, y0 + bh * 0.12), (cx + sw, y0 + bh * 0.12),
               (cx + hw, y0 + bh * 0.55), (cx - hw, y0 + bh * 0.55)], fill=255)
    # 腿
    lw = max(6, int(bw * 0.19))
    for sx in (-1, 1):
        lx = cx + sx * hw * 0.45
        d.line([(lx, y0 + bh * 0.53), (lx + sx * bw * 0.06, y1)], fill=255, width=lw)
    # 手臂
    aw = max(5, int(bw * 0.13))
    for sx in (-1, 1):
        d.line([(cx + sx * sw * 0.85, y0 + bh * 0.14),
                (cx + sx * sw * 1.05, y0 + bh * 0.52)], fill=255, width=aw)
    return M


def body_mask(json_path, W, H, grow=1.12):
    """返回 (mask L 图, 覆盖率%)；点不够时返回 (None, 0)。"""
    pts, pw, ph = load_pose(json_path)
    if len(pts) < 14:
        return None, 0.0
    ok = [p for p in pts if p[2] > 0.2 and p[0] >= 0 and p[1] >= 0]
    if len(ok) < 8:
        return None, 0.0

    def pt(i):
        x, y, s = pts[i]
        return (x, y) if s > 0.2 else None

    # 用肩膀宽度做身体尺度（侧身/四分之三视角肩宽会收窄，用身高兜底避免细线条过细）
    ys_all = [p[1] for p in ok]
    body_h_est = max(20.0, max(ys_all) - min(ys_all))
    rs, ls = pt(RS), pt(LS)
    if rs and ls:
        sw = max(math.hypot(rs[0] - ls[0], rs[1] - ls[1]), body_h_est * 0.14)
    else:
        sw = max(40.0, body_h_est * 0.22)

    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)

    # 躯干：肩—髋多边形
    rh, lh = pt(RH), pt(LH)
    torso = [p for p in (rs, ls, lh, rh) if p]
    if len(torso) >= 3:
        d.polygon(torso, fill=255)
    elif pt(NECK):
        nx, ny = pt(NECK)
        d.ellipse((nx - sw * 0.45, ny, nx + sw * 0.45, ny + sw * 1.2), fill=255)

    # 头部：以鼻/颈为心，肩宽的 0.42 为半径
    head_c = pt(NOSE) or pt(NECK)
    if head_c:
        r = max(10, sw * 0.42)
        d.ellipse((head_c[0] - r, head_c[1] - r * 1.15, head_c[0] + r, head_c[1] + r * 1.15), fill=255)

    # 四肢：粗线（半径按肩宽比例）
    limb_w = max(6, int(sw * 0.34 * grow))
    for chain in ((RS, RE, RW), (LS, LE, LW), (RH, RK, RA), (LH, LK, LA)):
        seq = [pt(i) for i in chain]
        for a, b in zip(seq, seq[1:]):
            if a and b:
                d.line([a, b], fill=255, width=limb_w)
                for c in (a, b):
                    d.ellipse((c[0] - limb_w / 2, c[1] - limb_w / 2, c[0] + limb_w / 2, c[1] + limb_w / 2), fill=255)

    cov = float(np.asarray(m).mean()) / 255 * 100
    # 骨架若真塌缩（高度过矮 / 有效点不足 / 覆盖率极低），改用人形模板；避免高分辨率画布正常张腿姿势被误判
    ys = [p[1] for p in ok]
    top, bot = min(ys), max(ys)
    body_h = max(20, bot - top)
    if body_h < H * 0.08 or cov < 0.8 or (sw < body_h * 0.07 and len(ok) < 10):
        xs = [p[0] for p in ok]
        cx = float(np.median(xs))
        bw2 = max(body_h * 0.34, sw * 2.2)
        box = (cx - bw2 / 2, top - body_h * 0.06, cx + bw2 / 2, bot + body_h * 0.03)
        m2 = _humanoid(Image.new("L", (W, H), 0), box, W, H)
        m = m2
        cov = float(np.asarray(m).mean()) / 255 * 100
        print("[mask] 骨架塌缩(肩宽 %.0f / 身高 %.0f)，用人形模板 %.1f%%" % (sw, body_h, cov), flush=True)
    m = m.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(max(4, sw * 0.06)))
    cov = float(np.asarray(m).mean()) / 255 * 100
    return m, cov
