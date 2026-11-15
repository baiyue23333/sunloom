"""透明卡与合成：BiRefNet 抠图、投影/AO/倒影、按 7B 舞台参数落位。"""
import argparse, json, os, time, urllib.request
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops
ROOT = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "http://127.0.0.1:8770"
OUT = os.path.join(ROOT, "SD-Picture", "cards")
from cutout import CutoutError, comfy_cutout, defringe, resize_rgba


def _resize_rgba(im, size):
    """卡片缩放走预乘，避免透明像素的 RGB 糊到边缘。"""
    return resize_rgba(im, size)
import fusion
def post(p, o):
    r = urllib.request.Request(API + p, data=json.dumps(o).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=120).read())
def get(p):
    return json.loads(urllib.request.urlopen(API + p, timeout=60).read())
def run(body, tag):
    r = post("/api/run", body)
    pid = r["job_id"]
    t0 = time.time()
    while time.time() - t0 < 900:
        j = get("/api/job/" + pid)
        if j.get("status") in ("done", "error"):
            imgs = (j.get("result") or {}).get("images") or []
            if not imgs:
                raise RuntimeError(tag + ": " + str(j.get("result"))[:300])
            return imgs[0]
        time.sleep(2)
    raise TimeoutError(tag)
def matte(src, dst, trim=True, grow=0):
    from rembg import remove, new_session
    im = Image.open(src).convert("RGB")
    cut = remove(im, session=new_session("u2net"), alpha_matting=True,
                 alpha_matting_foreground_threshold=240, alpha_matting_background_threshold=10,
                 alpha_matting_erode_size=6)
    if grow:
        a = cut.split()[3].filter(ImageFilter.MaxFilter(grow * 2 + 1))
        cut.putalpha(a)
    if trim:
        bb = cut.getbbox()
        if bb:
            cut = cut.crop(bb)
    cut.save(dst)
    return dst
def matte_chroma(src, dst, key=(255, 0, 255), thr=90):
    """纯色键抠图：适合细结构（栏杆、草），带 despill。"""
    im = Image.open(src).convert("RGB")
    a = np.asarray(im, dtype=np.float32)
    k = np.array(key, dtype=np.float32)
    dist = np.sqrt(((a - k) ** 2).sum(axis=2))
    alpha = np.clip((dist - thr * 0.35) / (thr * 0.65), 0, 1)
    spill = np.clip((a[..., 0] + a[..., 2]) / 2.0 - a[..., 1], 0, 60) * 0.5
    a[..., 0] -= spill
    a[..., 2] -= spill
    out = np.dstack([np.clip(a, 0, 255), alpha * 255]).astype(np.uint8)
    cut = Image.fromarray(out, "RGBA")
    bb = cut.getbbox()
    if bb:
        cut = cut.crop(bb)
    cut.save(dst)
    return dst
def grade(rgb, ref, strength=0.3):
    a = np.asarray(rgb, dtype=np.float32)
    b = np.asarray(ref, dtype=np.float32)
    am, ast = a.reshape(-1, 3).mean(0), a.reshape(-1, 3).std(0) + 1e-6
    bm, bst = b.reshape(-1, 3).mean(0), b.reshape(-1, 3).std(0) + 1e-6
    out = a * (1 - strength) + ((a - am) / ast * bst + bm) * strength
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
def compose(plate_path, card_path, out_dir, ratio, ground_y, x, light="left",
            shadow=200, refl=0.09, grade_w=0.45, ambient=0.80, poisson=0.0, stage=None, use_slot=False,
            shadow_boost=1.0, no_fusion=False, anchor="feet"):
    os.makedirs(out_dir, exist_ok=True)
    plate = Image.open(plate_path).convert("RGB")
    W, H = plate.size
    if use_slot and stage and stage.get("person_box"):
        pb = stage["person_box"]
        ground_y = float(pb["feet_y"])
        x = float(pb["x"])
    elif use_slot and stage and stage.get("person_slots"):
        slot = stage["person_slots"][0]
        ratio = float(slot.get("scale", ratio))
        ground_y = float(slot.get("ground_y", ground_y))
        x = float(slot.get("x", x))
    if use_slot and stage and stage.get("ground"):
        pts = sorted(stage.get("ground") or [])
        for i in range(len(pts) - 1):
            if pts[i][0] <= x <= pts[i + 1][0]:
                t = (x - pts[i][0]) / max(1e-6, pts[i + 1][0] - pts[i][0])
                gy = pts[i][1] * (1 - t) + pts[i + 1][1] * t
                if abs(gy - ground_y) > 0.01:
                    ground_y = gy
                break
    if stage and stage.get("wet_ground") is False:
        refl = 0.0
    card = Image.open(card_path).convert("RGBA")
    fh = int(H * ratio)
    cw = max(1, int(card.width * fh / card.height))
    card = _resize_rgba(card, (cw, fh))
    alpha = card.split()[3].point(lambda v: 255 if v > 30 else 0).filter(ImageFilter.GaussianBlur(0.6))
    card.putalpha(alpha)
    feet = H if anchor == "bottom" else int(H * ground_y)
    cx = int(W * x)
    bb = alpha.getbbox()
    ab = (bb[3] - 1) if bb else fh - 1
    x0, y0 = cx - cw // 2, (H - fh) if anchor == "bottom" else feet - ab
    patch = plate.crop((max(0, x0), max(0, y0), min(W, x0 + cw), min(H, y0 + fh))).resize((cw, fh))
    ring = (128.0, 128.0, 128.0)
    try:
        if no_fusion:
            rgb = fusion.grade(card.convert("RGB"), patch, grade_w)
        else:
            graded0, ring = fusion.lowfreq_match(card, plate, (x0, y0, x0 + cw, y0 + fh), weight=0.35)
            rgb = graded0.convert("RGB")
    except Exception:
        rgb = fusion.grade(card.convert("RGB"), patch, grade_w)
        print("[fusion] fallback", flush=True)
    arr = np.asarray(rgb, dtype=np.float32)
    target = (0.2126 * ring[0] + 0.7152 * ring[1] + 0.0722 * ring[2]) * 0.98 + 3
    cur = float(arr.mean()) + 1e-6
    k = min(1.00, max(0.82, target / cur))
    arr *= k
    has_cool = any(L.get("color") == "cool" for L in (stage or {}).get("lights", []))
    if has_cool:
        gw = np.linspace(1.10, 0.88, arr.shape[1], dtype=np.float32)[None, :]
        arr[..., 2] *= (2.0 - gw) * 1.02 * ambient
    else:
        gw = np.linspace(1.08, 0.96, arr.shape[1], dtype=np.float32)[None, :]
    arr[..., 0] *= gw * ambient
    arr[..., 1] *= ambient
    vshade = np.linspace(1.02, 0.70, arr.shape[0], dtype=np.float32)[:, None]
    arr *= vshade[..., None]
    rgb = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    graded = rgb.convert("RGBA")
    graded.putalpha(alpha)
    sign = -1 if light == "right" else 1
    if stage and stage.get("lights"):
        strongest = max(stage["lights"], key=lambda L: float(L.get("strength", 0)))
        sign = -1 if strongest.get("dir") == "right" else 1
    if anchor == "bottom":
        comp = plate.convert("RGB").convert("RGBA")
    else:
        sh = Image.new("L", (W, H), 0)
        sd = ImageDraw.Draw(sh)
        sx = cx + sign * int(cw * 0.20)
        ang = fusion.ground_tangent((stage or {}).get("ground"), x) if stage else 0.0
        sf = min(1.12, max(0.78, 1.35 - fusion.local_lum(plate, cx, feet) / 255.0 * 0.7))
        sd.polygon(fusion.ellipse_points(sx, feet, cw * 0.55, fh * 0.028, ang),
                   fill=min(255, int(shadow * shadow_boost * sf)))
        sh = sh.filter(ImageFilter.GaussianBlur(max(3, fh // 24)))
        sd = ImageDraw.Draw(sh)
        L = int(fh * 0.42)
        vx, vy = float(sign) * L, fh * 0.12
        if stage and stage.get("lights"):
            st = max(stage["lights"], key=lambda x: float(x.get("strength", 0)))
            bb = st.get("bbox")
            if bb:
                lx, ly = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
                dx, dy = x - lx, ground_y - ly
                n = max(1e-6, (dx * dx + dy * dy) ** 0.5)
                vx, vy = dx / n * L, dy / n * L
        px, py = -vy * 0.30, vx * 0.30
        sd.polygon([(cx - cw * 0.14, feet), (cx + cw * 0.14, feet),
                    (cx + vx + cw * 0.10, feet + vy + py),
                    (cx + vx - cw * 0.10, feet + vy - py),
                    (cx - cw * 0.06, feet + fh * 0.04)], fill=min(255, int(shadow * 0.50 * shadow_boost * sf)))
        sh = sh.filter(ImageFilter.GaussianBlur(max(5, fh // 22)))
        comp = plate.convert("RGB")
        dark = Image.fromarray(np.clip(np.asarray(comp, dtype=np.float32) * (1 - np.asarray(sh, dtype=np.float32)[..., None] / 255.0 * 0.85), 0, 255).astype(np.uint8))
        comp = dark.convert("RGBA")
        ao = Image.new("L", (W, H), 0)
        ad = ImageDraw.Draw(ao)
        ad.ellipse((cx - cw * 0.32, feet - fh * 0.028, cx + cw * 0.32, feet + fh * 0.016), fill=245)
        ao = ao.filter(ImageFilter.GaussianBlur(max(2, fh // 44)))
        comp = Image.fromarray(np.clip(np.asarray(comp.convert("RGB"), dtype=np.float32) *
                                       (1 - np.asarray(ao, dtype=np.float32)[..., None] / 255.0 * 0.88), 0, 255).astype(np.uint8)).convert("RGBA")
        # 硬接触阴影：跨度取自角色真实脚底像素，不用固定椭圆（否则脚是“浮”在影子上）
        a_np = np.asarray(alpha, dtype=np.uint8)
        rows = np.nonzero(a_np.max(axis=1) > 128)[0]
        contact = int(rows[-1]) if rows.size else int(ab)
        band = a_np[max(0, contact - max(2, int(fh * 0.03))):contact + 1]
        cols = np.nonzero(band.max(axis=0) > 128)[0] if band.size else []
        if len(cols):
            fx0, fx1 = int(cols[0]), int(cols[-1]) + 1
        else:
            fx0, fx1 = int(cw * 0.36), int(cw * 0.64)
        fy = int(y0 + contact)
        # 两层接触阴影，且按地面透视倾斜：硬核贴脚 + 宽软 AO
        ang = fusion.ground_tangent((stage or {}).get("ground"), x) if stage else 0.0
        hw = max(8, int((fx1 - fx0) * 0.85))
        hcx = x0 + (fx0 + fx1) // 2
        hh = max(4, int(fh * 0.022))
        hard = Image.new("L", (W, H), 0)
        hd = ImageDraw.Draw(hard)
        hd.polygon(fusion.ellipse_points(hcx, fy, hw * 1.6, hh * 2.4, ang), fill=150)
        hd.polygon(fusion.ellipse_points(hcx, fy - hh * 0.1, hw * 0.95, hh * 1.1, ang), fill=245)
        hard = hard.filter(ImageFilter.GaussianBlur(max(3, fh // 90)))
        comp = Image.fromarray(np.clip(np.asarray(comp.convert("RGB"), dtype=np.float32) *
                                       (1 - np.asarray(hard, dtype=np.float32)[..., None] / 255.0 * 0.92), 0, 255).astype(np.uint8)).convert("RGBA")
        CONTACT_DROP = int(hh * 1.4)   # 倒影从接触阴影下方起算，避免叠在脚底发光
        pool = Image.new("L", (W, H), 0)
        ImageDraw.Draw(pool).ellipse((cx - cw * 1.5, feet - fh * 0.34, cx + cw * 1.5, feet - fh * 0.03), fill=55)
        pool = pool.filter(ImageFilter.GaussianBlur(max(6, fh // 10)))
        glow = Image.new("RGB", (W, H), (255, 190, 130))
        base_rgb = comp.convert("RGB")
        lit = ImageChops.screen(base_rgb, Image.composite(glow, Image.new("RGB", (W, H), (0, 0, 0)), pool))
        comp = Image.composite(lit, base_rgb, pool).convert("RGBA")
        if refl > 0:
            rh = max(24, min(int(fh * 0.42), H - feet))
            # 只镜像下 45%（腿脚）：整卡镜像会在亮地面上糊出“第二个人”的虚影
            src_h = max(8, int(fh * 0.45))
            leg = card.crop((0, fh - src_h, cw, fh)).transpose(Image.FLIP_TOP_BOTTOM)
            rf = _resize_rgba(leg, (cw, rh)).filter(ImageFilter.GaussianBlur(4.5))
            foot = plate.crop((x0, feet, x0 + cw, feet + rh)).resize((cw, rh))
            rf = Image.blend(rf.convert("RGB"), foot, 0.18).convert("RGBA")
            fa = rf.split()[3]
            grad = Image.fromarray(
                ((np.linspace(190, 0, rh, dtype=np.float32) ** 1.6)[:, None] *
                 np.ones((1, cw), np.float32)).astype(np.uint8))
            fa = Image.composite(fa, Image.new("L", (cw, rh), 0), grad).point(lambda v: int(v * min(1.0, refl * 1.6)))
            rf.putalpha(fa)
            comp.paste(rf, (x0, min(H - 1, feet + CONTACT_DROP)), fa)
    if stage:
        hy = int(H * float(stage.get("horizon_y", 0.42)))
        if 0 < hy < H:
            far = comp.crop((0, 0, W, hy)).filter(ImageFilter.GaussianBlur(1.2))
            grad = Image.linear_gradient("L").resize((W, hy)).transpose(Image.FLIP_TOP_BOTTOM)
            comp.paste(far, (0, 0), grad)
    if poisson:
        try:
            import cv2
            base = cv2.cvtColor(np.asarray(comp.convert("RGB")), cv2.COLOR_RGB2BGR)
            cut = cv2.cvtColor(np.asarray(graded.convert("RGB")), cv2.COLOR_RGB2BGR)
            m = np.asarray(alpha.point(lambda v: 255 if v > 128 else 0))
            m = cv2.erode(m, np.ones((3, 3), np.uint8))
            if m.any():
                blended = cv2.seamlessClone(cut, base, m, (x0 + cw // 2, y0 + fh // 2), cv2.NORMAL_CLONE)
                comp = Image.fromarray(cv2.cvtColor(blended, cv2.COLOR_BGR2RGB)).convert("RGBA")
            else:
                comp.alpha_composite(graded, (x0, y0))
        except Exception:
            comp.alpha_composite(graded, (x0, y0))
    else:
        comp.alpha_composite(graded, (x0, y0))
    # 环境光 spill：最强灯的颜色扫在人物受光侧
    if stage and stage.get("lights"):
        try:
            st0 = max(stage["lights"], key=lambda x: float(x.get("strength", 0)))
            hexv = (stage.get("palette") or {}).get("light") or "#ffc070"
            lc = tuple(int(hexv[i:i+2], 16) for i in (1, 3, 5))
            if st0.get("dir") == "right":
                gx = np.linspace(0.0, 1.0, cw, dtype=np.float32)[None, :]
            else:
                gx = np.linspace(1.0, 0.0, cw, dtype=np.float32)[None, :]
            gy = np.linspace(0.72, 0.22, fh, dtype=np.float32)[:, None]
            ga = (gx * gy * 0.13 * float(st0.get("strength", 0.7)))
            ga = np.repeat(ga[..., None], 3, axis=2)
            base = np.asarray(graded.convert("RGB"), dtype=np.float32)
            spill = base * (1 - ga) + np.array(lc, dtype=np.float32)[None, None, :] * ga
            graded = Image.fromarray(np.clip(spill, 0, 255).astype(np.uint8)).convert("RGBA")
            graded.putalpha(alpha)
        except Exception:
            pass
    haze = Image.new("RGB", (cw, fh), (60, 90, 140))
    haze_a = alpha.point(lambda v: int(v * 0.05))
    mixed = Image.composite(haze, comp.crop((x0, y0, x0 + cw, y0 + fh)).convert("RGB"), haze_a)
    comp.paste(mixed, (x0, y0), haze_a)
    inner = alpha.filter(ImageFilter.MinFilter(3))
    line = Image.fromarray(np.clip(np.asarray(alpha, dtype=np.int16) - np.asarray(inner, dtype=np.int16), 0, 255).astype(np.uint8))
    line = line.filter(ImageFilter.GaussianBlur(0.5)).point(lambda v: int(v * 0.32))
    outline = Image.new("RGBA", graded.size, (22, 18, 16, 255)); outline.putalpha(line)
    comp.alpha_composite(outline, (x0, y0))
    out = os.path.join(out_dir, "comp.png")
    comp.convert("RGB").save(out)
    json.dump({"plate": plate_path, "card": card_path, "ratio": ratio, "ground_y": ground_y, "x": x,
               "light": light, "size": [W, H], "box": [x0, y0, x0 + cw, y0 + fh], "brightness_k": round(k, 3),
               "stage": stage or {}},
              open(os.path.join(out_dir, "scene.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("done:", out, "k=%.2f" % k, flush=True)
    return out
