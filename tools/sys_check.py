# -*- coding: utf-8 -*-
"""系统逻辑验证：路由覆盖 + 关键接口 + 出图链路。

  python tools/sys_check.py            # 快速（不含 7B/视觉）
  python tools/sys_check.py --deep     # 加路由/质检
"""
import argparse, base64, io, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

ROOT = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = "http://127.0.0.1:8770"
OK, BAD = [], []


def rec(name, ok, detail=""):
    (OK if ok else BAD).append((name, detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (("  -> " + str(detail)[:180]) if detail and not ok else ""))


def get(p, raw=False):
    try:
        with urllib.request.urlopen(B + p, timeout=180) as r:
            body = r.read()
            return r.status, body if raw else json.loads(body.decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def post(p, o):
    req = urllib.request.Request(B + p, data=json.dumps(o).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=400) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def wait_job(jid, timeout=300):
    t = time.time()
    while time.time() - t < timeout:
        _, j = get("/api/job/" + jid)
        if j.get("status") in ("done", "error"):
            return j
        time.sleep(2)
    return {"status": "timeout", "result": {}}


def run_image(body, tag):
    s, d = post("/api/run", body)
    if s != 200:
        return None, "submit %s %s" % (s, d)
    j = wait_job(d["job_id"])
    imgs = (j.get("result") or {}).get("images") or []
    if j.get("status") != "done" or not imgs:
        return None, str(j.get("result"))[:160]
    return imgs[0], ""


def check_routes():
    sys.path.insert(0, os.path.join(ROOT, "station"))
    os.chdir(os.path.join(ROOT, "station"))
    import server
    routes = {getattr(r, "path", "") for r in server.app.routes}
    pats = [re.sub(r"\{[^}]+\}", "", r) for r in routes if r.startswith("/api/")]
    js_files = [os.path.join(ROOT, "station", "static", "app.js")]
    js_dir = os.path.join(ROOT, "station", "static", "js")
    if os.path.isdir(js_dir):
        js_files.extend(os.path.join(js_dir, f) for f in os.listdir(js_dir) if f.endswith(".js"))
    used = set()
    for path in js_files:
        if os.path.isfile(path):
            txt = open(path, encoding="utf-8").read()
            used.update(u.rstrip(".") for u in re.findall(r"/api/[A-Za-z0-9_/{}.\-]+", txt))
    miss = []
    for u in sorted(used):
        if u in routes or any(u.startswith(p) and p for p in pats):
            continue
        miss.append(u)
    rec("前端调用的 /api 路径都存在", not miss, miss)


def main(deep=False):
    print("== 接口 ==")
    s, b = get("/api/bootstrap")
    rec("bootstrap", s == 200 and "tokens" in b and "models" in b, s)
    s, st = get("/api/status")
    rec("ComfyUI 在线", s == 200 and st.get("comfy", {}).get("up"), s)
    s, mem = get("/api/memory")
    rec("内存接口", s == 200 and (mem.get("ram") or {}).get("total_gb", 0) > 0 and "comfy" in mem, s)

    s, e = post("/api/expand", {"positive": [{"token": "@ID", "text": "", "weight": 1}], "negative": []})
    rec("expand 正常", s == 200 and isinstance(e.get("positive"), str) and "shoulder-length hair" in e.get("positive", ""), s)

    s, h = post("/api/compose_hint", {"prompt": "wide rainy neon street", "seed": 9})
    rec("compose_hint", s == 200 and 0.2 <= h.get("ratio", 0) <= 0.6, (s, h))

    s, fx = post("/api/fix/blocks", {
        "blocks": [{"token": "@CAM_BUST", "weight": 1}, {"token": "@CAM_FULL", "weight": 1}],
        "negatives": [],
    })
    rec("规则修正 /api/fix/blocks", s == 200 and fx.get("by") == "rules" and len(fx.get("issues") or []) >= 1, (s, fx))

    s, lg = post("/api/guide/light", {"blocks": [{"token": "@ID_F"}], "negatives": [], "mode": "free"})
    rec("光线向导 /api/guide/light", s == 200 and lg.get("covered", {}).get("id") and "tips" in lg, (s, lg))

    s, bad2 = post("/api/run", {"prompt": "x", "mode": "t2i", "model": "nope.safetensors"})
    rec("未知底模返回 400", s == 400, (s, bad2))

    s, pc = get("/api/pipeline/check")
    rec("链路体检 /api/pipeline/check", s == 200 and isinstance(pc.get("checks"), list), s)

    s, gc = get("/api/gallery?dir=coop&limit=0")
    gok = s == 200 and all(
        (i.get("name") or "").lower() in ("comp.png", "final.png") or (i.get("name") or "").lower().startswith("final")
        for i in gc.get("items") or []
    )
    rec("画廊·合作成品", gok, (s, gc.get("total")))

    s, v = post("/api/validate", {"positive": [{"token": "@ID_F", "text": "", "weight": 1}], "negative": []})
    rec("/api/validate", s == 200 and "warnings" in v, s)

    s400, _ = post("/api/coop", {"mode": "legacy_xl", "scene": "x"})
    rec("未知合作模式 400", s400 == 400, s400)

    s, cs = get("/api/coop/status")
    rec("coop 状态", s == 200 and "status" in cs, s)
    s, cl = get("/api/coop/list")
    rec("coop 列表", s == 200 and "items" in cl, s)

    if deep:
        print("== 出图链路（--deep）==")
        img, err = run_image({"prompt": "a red apple on a table", "negative": "text", "width": 512, "height": 512,
                              "steps": 6, "cfg": 4.0, "seed": 910001, "prefix": "SYSC", "mode": "t2i",
                              "save_to": "station_out", "loras": []}, "t2i")
        rec("t2i 出图", bool(img) and os.path.isfile(img), err)
        if img:
            s, body = get("/api/img?path=" + urllib.parse.quote(img), raw=True)
            rec("/api/img 返回图片", s == 200 and len(body) > 1000, s)

            s, mk = post("/api/mask/save", {"image": img, "mask_b64": _mask_b64(), "name": "sys"})
            rec("mask/save", s == 200 and mk.get("ok"), (s, mk))
            if s == 200:
                img2, err2 = run_image({"prompt": "a blue apple", "negative": "text", "width": 512, "height": 512,
                                        "steps": 6, "cfg": 4.0, "seed": 910002, "prefix": "SYSCI", "mode": "inpaint",
                                        "reference": img, "mask": mk["name"], "denoise": 0.8,
                                        "save_to": "station_out", "loras": []}, "inpaint")
                rec("inpaint（用 masks 目录的蒙版）", bool(img2), err2)

            s, ip = post("/api/inpaint", {"image": img, "box": "180,180,160,160", "prompt": "blue apple", "negative": "text",
                                          "denoise": 0.8, "steps": 6, "cfg": 4.0, "seed": 910003, "prefix": "SYSIP"})
            if s == 200:
                j = wait_job(ip["job_id"])
                rec("/api/inpaint 框选", j.get("status") == "done", j.get("result"))
            else:
                rec("/api/inpaint 框选", False, s)

            s, qc = get("/api/qc?path=" + urllib.parse.quote(img))
            rec("/api/qc", s == 200 and "mirror" in qc, s)

    check_routes()
    print("\n%d PASS / %d FAIL" % (len(OK), len(BAD)))
    if BAD:
        for n, d in BAD:
            print("  -", n, str(d)[:160])
        sys.exit(1)


def _mask_b64():
    from PIL import Image, ImageDraw
    m = Image.new("RGB", (512, 512), (0, 0, 0))
    ImageDraw.Draw(m).rectangle((180, 180, 340, 340), fill=(255, 255, 255))
    buf = io.BytesIO()
    m.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--deep", action="store_true")
    a = ap.parse_args()
    main(a.deep)
