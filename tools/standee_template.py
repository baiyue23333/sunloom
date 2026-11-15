# -*- coding: utf-8 -*-
"""立绘模板：一张全身立绘 + 右上角放大的半身（淡化），合成一张角色立绘板。

      ┌───────────────────────────┐
      │  ┌─────┐      ╭──────────╮ │
      │  │     │      │  半身放大  │ │  ← 半身 = 取全身的头部到腰部
      │  │ 全身 │      │  淡化叠在  │ │     放大、贴右边缘、半透明
      │  │     │      │  右侧      │ │
      │  └─────┘      ╰──────────╯ │
      └───────────────────────────┘

用法：
    python tools/standee_template.py --in 立绘.png --out 立绘板.png
    python tools/standee_template.py --in 立绘.png --out out.png --fade 0.62 --crop 0.46

背景：输入带 alpha 就直接用；否则按四边中位色当背景做抠图（纯白/纯色底最准）。
"""
import argparse
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PIL import Image, ImageFilter
import numpy as np


def head_center_x(sub, top_ratio=0.24):
    """用人物最上面那一截（头）的水平中心当锚点，避免被扩散的头发带偏。"""
    m = np.array(sub.split()[-1]) > 8
    h = m.shape[0]
    band = m[:max(4, int(h * top_ratio))]
    cols = np.where(band.any(axis=0))[0]
    if not len(cols):
        return sub.size[0] / 2.0
    return (int(cols.min()) + int(cols.max())) / 2.0


def _bg_color(rgb):
    h, w = rgb.shape[:2]
    edge = np.stack([rgb[0, 0], rgb[0, w - 1], rgb[h - 1, 0], rgb[h - 1, w - 1]])
    return np.median(edge, axis=0)


def cut_subject(im, tol=36, soft=32, blur=0.6, min_alpha=0.20, gamma=1.5):
    """抠图：软边 alpha + 去背景色污染（decontaminate），避免白发/发丝出现白边。

    alpha  = clamp((色差 - tol) / soft, 0, 1)，再按 min_alpha 清零 + gamma 加速衰减
    前景色 = (C - (1-alpha) * bg) / alpha   ← 把混进来的背景白减掉

    min_alpha / gamma 是为了压掉"低 alpha 白雾"：背景噪声会给整个画面糊一层
    10–30% 的白，叠在放大的人物上会把脸压淡（2026-11-13 实测踩到）。
    """
    rgb = np.array(im.convert("RGB")).astype(np.float32)
    bg = _bg_color(rgb)
    diff = np.abs(rgb - bg[..., :]).sum(axis=2)
    a = np.clip((diff - tol) / max(1.0, soft), 0.0, 1.0)
    if min_alpha > 0:
        a = np.where(a < float(min_alpha), 0.0, a)
    if gamma and gamma != 1:
        a = np.power(a, float(gamma))
    aa = np.maximum(a, 1e-3)[..., None]
    fg = np.clip((rgb - (1.0 - a[..., None]) * bg) / aa, 0, 255)

    if blur:
        # alpha 平滑 + 颜色溢出：透明像素的 RGB 还是白的，直接模糊会把白色带进发丝。
        # 用 alpha 加权的模糊把"人物颜色"铺到边缘，再除回 alpha —— 但**只在边缘用**，
        # 内部像素保留原始锐度，否则整张图会被抹糊（2026-11-13 实测）。
        m = a[..., None]
        pre = Image.fromarray(np.clip(fg * m, 0, 255).astype(np.uint8))
        al_i = Image.fromarray(np.clip(a * 255.0, 0, 255).astype(np.uint8))
        pre_b = np.array(pre.filter(ImageFilter.GaussianBlur(float(blur)))).astype(np.float32)
        al_b = np.array(al_i.filter(ImageFilter.GaussianBlur(float(blur)))).astype(np.float32)
        den = np.maximum(al_b / 255.0, 1e-3)[..., None]
        bled = np.clip(pre_b / den, 0, 255)
        w = np.clip((1.0 - a) * 2.5, 0.0, 1.0)[..., None]   # 边缘权重：黄心=1，内部=0
        fg = fg * (1.0 - w) + bled * w
        a = al_b / 255.0

    out = np.dstack([fg, a * 255.0]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def subject_rgba(im_path, matte="auto", tol=36, soft=32, min_alpha=0.18, aa=None):
    """取人物 RGBA（已裁到包围盒）。

    auto/comfy：走 ComfyUI 的 BiRefNet 抠图（tools/cutout.py）——白发的角色也能保住；
    color：退回"与四边中位色作差"的快速抠图（无 ComfyUI 时兜底）。
    """
    if matte == "hybrid":
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import cutout
        try:
            from PIL import Image as _I
            im = cutout.hybrid_matte(im_path, aa=aa)     # 模型轮廓 + 色键配色
            bb = im.getbbox()
            return im.crop(bb) if bb else im
        except Exception:
            pass
    if matte == "chroma":
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import cutout
        try:
            return cutout.make_matte(im_path, backend="chroma", crop=True, aa=aa)
        except Exception:
            pass   # 背景不纯就按原路走 BiRefNet，不硬抠
    if matte in ("auto", "comfy"):
        try:
            import sys as _sys
            _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import cutout
            import tempfile
            dst = os.path.join(tempfile.gettempdir(), "standee_cut_%d.png" % os.getpid())
            cutout.comfy_cutout(im_path, dst)
            rgba = Image.open(dst).convert("RGBA")
            try:
                os.remove(dst)
            except OSError:
                pass
            if rgba.size[0] > 8 and rgba.size[1] > 8:
                return rgba
            raise RuntimeError("抠图结果为空")
        except Exception:
            if matte == "comfy":
                raise
    im = Image.open(im_path)
    cut = cut_subject(im, tol=tol, soft=soft, min_alpha=min_alpha)
    box = cut.split()[-1].point(lambda v: 255 if v > 8 else 0).getbbox() or (0, 0, im.width, im.height)
    return cut.crop(box)


def _soften_alpha(img, px=1.0):
    """轻微模糊 alpha：向外半像素级地扩一点，补掉两层之间的细白缝。

    不用 MaxFilter——那会让边缘那些"去污染"过的深色像素变成不透明，勾出一圈黑边。
    """
    if px <= 0:
        return img
    al = img.split()[-1].filter(ImageFilter.GaussianBlur(float(px)))
    img.putalpha(al)
    return img


COLOR_NAMES = {"white": (255, 255, 255), "black": (0, 0, 0),
               "cream": (246, 241, 230), "paper": (248, 246, 240)}


def _parse_color(s):
    s = str(s or "").strip().lower()
    if s in COLOR_NAMES:
        return COLOR_NAMES[s]
    if s.startswith("#") and len(s) in (4, 7):
        h = s[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        try:
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return None
    return None


def _cover_fit(im, W, H):
    """等比放大到铺满画布再居中裁切（不拉伸）。"""
    s = max(W / float(im.width), H / float(im.height))
    w, h = max(1, int(im.width * s + 0.5)), max(1, int(im.height * s + 0.5))
    im = im.resize((w, h), Image.LANCZOS)
    left, top = (w - W) // 2, (h - H) // 2
    return im.crop((left, top, left + W, top + H))


def _flatten(canvas, bg, W, H):
    """把透明画布压到背景上；bg 为 none/transparent 时原样返回 RGBA。"""
    key = str(bg or "").strip().lower()
    if key in ("", "none", "transparent", "alpha"):
        return canvas
    color = _parse_color(key)
    if color is not None:
        out = Image.new("RGB", (W, H), color)
        out.paste(canvas, (0, 0), canvas)
        return out
    if not os.path.isfile(bg):
        raise FileNotFoundError("背景图不存在: %s" % bg)
    base = Image.open(bg).convert("RGB")
    base = _cover_fit(base, W, H)
    base.paste(canvas, (0, 0), canvas)
    return base


def build(in_path, out_path, fade=0.75, crop=0.50, size=1792,
          body_h=0.92, body_x=0.38, head_h=0.94, head_cx=0.70, bottom_fade=0.26,
          tol=36, soft=32, min_alpha=0.18, grow=None, bg="white", matte="auto",
          sharpen=0.0, sharpen_after=0.5, global_sharpen=0.4, aa="crisp"):
    """立绘模板：左全身 + 右放大半身。

    分层合成（两层都抠图，透明底叠加）：
      ① 放大层：取上半身放大铺右侧，alpha 乘 fade + 底部渐隐；
      ② 全身层：同样抠图，压在放大层之上；alpha 再外扩 grow 像素，
         避免和放大层之间留下 1px 白缝；
      ③ 两层边缘都用 color bleed 处理过，白底不会渗出来；
      ④ bg 决定最后怎么压平：none=保留 alpha、#rrggbb/white /图片路径=叠在背景上。
    """
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import cutout

    sub = subject_rgba(in_path, matte=matte, tol=tol, soft=soft, min_alpha=min_alpha, aa=aa)
    # chroma 的 alpha 已经是最终值、也没有"两层之间的白缝"，再模糊 alpha 只会把描线一起弄软
    if grow is None:
        grow = 0.0 if matte == "chroma" else 1.0
    if sharpen and sharpen > 0:
        sub = cutout.sharpen_edge(sub, alpha_amount=float(sharpen))
    bw, bh = sub.size

    W = H = int(size)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))   # 起点必须透明，否则 --transparent 形同虚设

    # ① 放大的人物
    head = sub.crop((0, 0, bw, max(1, int(bh * crop))))
    th = int(H * head_h)
    tw = max(1, int(head.width * th / head.height))
    head = cutout.rechoke(cutout.resize_rgba(head, (tw, th)))   # 2.4× 放大后把软带收回 1px
    anc = head_center_x(sub) * (tw / float(bw))
    a = np.array(head.split()[-1]).astype(np.float32) * float(fade)
    if bottom_fade > 0:
        y = np.arange(th)[:, None]
        cut_y = int(th * (1 - bottom_fade))
        ramp = np.clip((th - y) / max(1.0, th - cut_y), 0.0, 1.0)
        a = a * np.where(y < cut_y, 1.0, ramp)
    head.putalpha(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)))
    canvas.alpha_composite(head, (int(W * head_cx - anc), 0))

    # ② 角色本身（压在放大层上面）
    th2 = int(H * body_h)
    tw2 = max(1, int(bw * th2 / bh))
    body = cutout.resize_rgba(sub, (tw2, th2))
    if sharpen_after and sharpen_after > 0:
        body = cutout.sharpen_edge(body, alpha_amount=float(sharpen_after))
    body = _soften_alpha(body, grow)
    canvas.alpha_composite(body, (int(W * body_x - tw2 / 2), int(H * 0.97 - th2)))

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
    out = _flatten(canvas, bg, W, H)
    if global_sharpen and global_sharpen > 0:
        out = cutout.unsharp_rgb(out, amount=float(global_sharpen), radius=1.0)
    out.save(out_path)
    return out_path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--fade", type=float, default=0.75, help="半身不透明度 0-1：越大越实（0.75 为定稿）")
    ap.add_argument("--crop", type=float, default=0.50, help="半身取全身的上部比例")
    ap.add_argument("--size", type=int, default=1792, help="输出画布边长（默认 1792，和 1216×1664 的底图接近 1:1）")
    ap.add_argument("--body-h", type=float, default=0.92)
    ap.add_argument("--body-x", type=float, default=0.38, help="全身中心位置（约 4:6，偏向中间）")
    ap.add_argument("--head-h", type=float, default=0.94, help="半身高度占画布比例")
    ap.add_argument("--head-cx", type=float, default=0.70, help="放大的半身（按头的中心）在画布上的横向位置")
    ap.add_argument("--tol", type=float, default=36, help="抠图容差，越大越容易把浅色当成背景")
    ap.add_argument("--soft", type=float, default=32, help="抠图软边宽度")
    ap.add_argument("--min-alpha", type=float, default=0.10, help="低于这个不透明度的边缘一律清零（压白雾）")
    ap.add_argument("--grow", type=float, default=None,
                    help="全身层 alpha 模糊半径（补两层白缝）；chroma 默认 0，其它默认 1.0")
    ap.add_argument("--sharpen-after", type=float, default=0.5,
                    help="缩放后的边缘锐化强度，0 关闭（默认 0.5）")
    ap.add_argument("--global-sharpen", type=float, default=0.4,
                    help="整图锐化强度（unsharp，默认 0.4）；0 关闭，>0.7 会出光晕")
    ap.add_argument("--aa", default="crisp", choices=["soft", "normal", "crisp"],
                    help="边缘抗锯齿档位：soft 过渡最柔(+飞边) / normal / crisp 最硬(默认)")
    ap.add_argument("--bg", default="white",
                    help="背景：none/transparent 输出透明 PNG；white/black/cream/paper 或 #rrggbb；或图片路径")
    ap.add_argument("--transparent", action="store_true", help="等价于 --bg none（保留旧参数）")
    ap.add_argument("--matte", default="auto", choices=["auto", "comfy", "color", "chroma"],
                    help="抠图方式：comfy=BiRefNet（默认优先，白发也能保住）/ color=颜色差兜底")
    ap.add_argument("--bottom-fade", type=float, default=0.24, help="半身底部渐隐比例")
    a = ap.parse_args()
    bg = "none" if a.transparent else a.bg
    out = build(a.src, a.dst, a.fade, a.crop, a.size, a.body_h, a.body_x,
                a.head_h, a.head_cx, a.bottom_fade, a.tol, a.soft, a.min_alpha, a.grow,
                bg=bg, matte=a.matte, sharpen_after=a.sharpen_after,
                global_sharpen=a.global_sharpen, aa=a.aa)
    print("OK " + out)


if __name__ == "__main__":
    main()
