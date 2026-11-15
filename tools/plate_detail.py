# -*- coding: utf-8 -*-
"""出图后的细节活：接触阴影 → 人物背面压暗 → 4× 超分 → 头发局部精修。

顺序不能反：超分会把缺阴影的"悬浮感"一起放大。
"""
import argparse
import json
import os
import sys
import time

from PIL import Image, ImageDraw, ImageFilter
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fusion
import hand_precise as hp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from comfy_paths import COMFY_OUT as OUT


def load_pts(json_path):
    d = json.load(open(json_path, encoding="utf-8"))
    if isinstance(d, dict):
        d = [d]
    p = (d[0].get("people") or [{}])[0]
    def trip(key):
        a = p.get(key) or []
        return [(a[i], a[i + 1], a[i + 2]) for i in range(0, len(a) - 2, 3)]
    return trip("pose_keypoints_2d"), trip("foot_keypoints_2d"), d[0].get("canvas_width"), d[0].get("canvas_height")


def feet_shadow(img, feet, strength=150):
    """脚底接触阴影：每只脚一个椭圆。"""
    if not feet:
        return img, 0
    W, H = img.size
    sh = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(sh)
    n = 0
    for x, y, s in feet:
        if s < 0.15 or x < 0 or y < 0:
            continue
        rx, ry = max(14, int(W * 0.028)), max(5, int(H * 0.012))
        d.ellipse((x - rx, y - ry * 0.4, x + rx, y + ry * 1.4), fill=strength)
        n += 1
    if not n:
        return img, 0
    sh = sh.filter(ImageFilter.GaussianBlur(max(6, int(H * 0.012))))
    a = np.asarray(img).astype(np.float32)
    a *= (1 - np.asarray(sh, dtype=np.float32)[..., None] / 255.0 * 0.75)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)), n


def darken_back(img, body_mask_path, factor=0.90):
    """人物背面压暗：逆光时背光面不该和亮面一样亮。"""
    m = Image.open(body_mask_path).convert("L").filter(ImageFilter.GaussianBlur(8))
    a = np.asarray(img).astype(np.float32)
    k = 1 - (1 - factor) * (np.asarray(m, dtype=np.float32) / 255.0)
    a *= k[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def sr(img, scale=4):
    import urllib.request
    from comfy_paths import COMFY_IN as CI
    API = "http://127.0.0.1:8188"
    name = "detail_in_%s.png" % time.strftime("%H%M%S")
    img.save(os.path.join(CI, name))
    g = {"1": {"class_type": "LoadImage", "inputs": {"image": name}},
         "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-AnimeSharp.safetensors"}},
         "3": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
         "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "DETAIL"}}}
    req = urllib.request.Request(API + "/prompt", data=json.dumps({"prompt": g}).encode(),
                                 headers={"Content-Type": "application/json"})
    pid = json.loads(urllib.request.urlopen(req, timeout=60).read())["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < 900:
        time.sleep(3)
        h = json.loads(urllib.request.urlopen(API + "/history/" + pid, timeout=30).read())
        if pid in h:
            for node in h[pid].get("outputs", {}).values():
                for im in node.get("images", []):
                    return Image.open(os.path.join(OUT, im["filename"])).convert("RGB")
            raise RuntimeError("超分没输出")
    raise TimeoutError("超分")


def hair_refine(img, head_box, prompt, neg, denoise=0.32, seed=0, loras=None):
    """头发局部：只在头肩区域低 denoise 重绘。"""
    from PIL import ImageDraw
    W, H = img.size
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).ellipse(head_box, fill=255)
    m = m.filter(ImageFilter.GaussianBlur(max(3, int(head_box[2] - head_box[0]) * 0.06)))
    name = "hairmask_%s.png" % time.strftime("%H%M%S")
    Image.merge("RGB", (m, m, m)).save(os.path.join(hp.CI, name))
    tmp = os.path.join(ROOT, "SD-Picture", "basebody", "_detail_tmp.png")
    img.save(tmp)
    body = {"prompt": prompt, "negative": neg, "mode": "inpaint", "reference": tmp,
            "mask": name, "denoise": denoise, "steps": 28, "cfg": 5.0, "seed": seed,
            "prefix": "HAIRFIX", "save_to": "paper", "width": W, "height": H,
            "loras": loras or []}
    jid = hp._post(hp.API + "/api/run", body)["job_id"]
    t0 = time.time()
    while time.time() - t0 < 900:
        time.sleep(3)
        st = hp._get(hp.API + "/api/job/" + jid)
        if st.get("status") in ("done", "error"):
            imgs = (st.get("result") or {}).get("images") or []
            if not imgs:
                raise RuntimeError("头发精修失败")
            return Image.open(imgs[0]).convert("RGB")
    raise TimeoutError("hair")


def sharp(a):
    import cv2
    return float(cv2.Laplacian(a, cv2.CV_32F).var())


def run(src, out_dir, seed=2026, hair=True, hair_denoise=0.32):
    os.makedirs(out_dir, exist_ok=True)
    img = Image.open(src).convert("RGB")
    W, H = img.size
    raw = hp.detect_raw(src)
    pose, feet, cw, ch = load_pts(raw["json"])
    print("[pose] 身体点 %d, 脚点 %d" % (len(pose), len(feet)), flush=True)

    t0 = time.time()
    img, n = feet_shadow(img, feet)
    print("[shadow] %d 只脚 %.0fs" % (n, time.time() - t0), flush=True)

    t0 = time.time()
    mpath = os.path.join(out_dir, "mask_body.png")
    if not os.path.exists(mpath):
        try:
            import sdp_body_mask as sbm
            bm, cov = sbm.body_mask(raw["json"], W, H)
            if bm is not None and cov > 2:
                bm.save(mpath)
                print("[mask] 人体 %.1f%%" % cov, flush=True)
        except Exception as e:  # noqa: BLE001
            print("[mask] 跳过:", str(e)[:60], flush=True)
    body = Image.open(mpath) if os.path.exists(mpath) else None
    if body is not None:
        img = darken_back(img, os.path.join(out_dir, "mask_body.png"))
        print("[darken] %.0fs" % (time.time() - t0), flush=True)
    else:
        print("[darken] 跳过（没有人体蒙版）", flush=True)

    before_edge = sharp(np.asarray(img.convert("L")))
    img.save(os.path.join(out_dir, "01_base.png"))

    if hair:
        # 只盖「发顶 + 发饰」：不碰肩线以下，否则会把军装重画
        good = [p for p in pose if p[2] > 0.2]
        nose = pose[0] if pose and pose[0][2] > 0.2 else None
        ears = [pose[16], pose[17]] if len(pose) > 17 else []
        ears = [p for p in ears if p[2] > 0.15]
        if nose:
            hcx, hcy = nose[0], nose[1]
        elif good:
            hcx = sum(p[0] for p in good) / len(good)
            hcy = min(p[1] for p in good)
        else:
            hcx, hcy = W / 2, H * 0.25
        if len(ears) == 2:
            hr = max(12.0, abs(ears[0][0] - ears[1][0]) * 1.9)
        else:
            sw2 = [p for p in pose[2:6] if p[2] > 0.2]
            hr = max(12.0, (abs(sw2[0][0] - sw2[1][0]) * 0.55) if len(sw2) >= 2 else W * 0.06)
        box = (hcx - hr * 1.25, hcy - hr * 1.35, hcx + hr * 1.25, hcy + hr * 0.85)
        print("[hair] 头框 r=%.0f box=%s" % (hr, [int(v) for v in box]), flush=True)
        t0 = time.time()
        img2 = hair_refine(img, box,
                           "(shoulder-length hair:1.3), long straight hair, (seasonal blooms hair ornament:1.2), "
                           "(detailed hair strands:1.2), backlit rim light, same art style",
                           "blurry, extra hair, weird ornament, text, watermark",
                           denoise=hair_denoise, seed=seed + 3,
                           loras=[{"name": "artist_style.safetensors", "weight": 0.5},
                                  {"name": "character_lora.safetensors", "weight": 0.9}])
        print("[hair] %.0fs" % (time.time() - t0), flush=True)
        img.save(os.path.join(out_dir, "03_hair_src.png"))
        img = img2
        img.save(os.path.join(out_dir, "04_hair.png"))

    t0 = time.time()
    big = sr(img)
    print("[sr] %dx%d %.0fs" % (big.width, big.height, time.time() - t0), flush=True)
    big.save(os.path.join(out_dir, "02_sr.png"))
    final = big.resize((big.width // 2, big.height // 2), Image.LANCZOS)
    final.save(os.path.join(out_dir, "comp_detail.png"))
    after_edge = sharp(np.asarray(final.convert("L")))
    print("[edge] %.0f -> %.0f" % (before_edge, after_edge), flush=True)
    print("OK", os.path.join(out_dir, "comp_detail.png"))
    return os.path.join(out_dir, "comp_detail.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--no-hair", action="store_true")
    ap.add_argument("--hair-denoise", type=float, default=0.20)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    out = a.out or os.path.join(ROOT, "SD-Picture", "detail", time.strftime("%Y%m%d_%H%M%S"))
    run(a.src, out, a.seed, not a.no_hair, a.hair_denoise)


if __name__ == "__main__":
    main()
