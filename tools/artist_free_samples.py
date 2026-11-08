# -*- coding: utf-8 -*-
"""为每个画师 LoRA 生成自由发挥样张（0.6 / 1.0 / 1.3），并写索引给前端悬停预览用。"""
import json, os, re, sys, time, urllib.request

B = "http://127.0.0.1:8770"
ROOT = r"A:/workflow/dsh"
OUTDIR = os.path.join(ROOT, "SD-Picture", "artist_free")
INDEX = os.path.join(ROOT, "ref", "artist_free_index.json")
PROMPT = "1girl, solo, upper body, looking at viewer, grey background"
NEG = "lowres, blurry, bad anatomy, extra people, watermark, text"
SEED = 515151
W, H, STEPS, CFG = 640, 896, 26, 5.5
WEIGHTS = [0.6, 1.0, 1.3]

def post(p, o):
    r = urllib.request.Request(B + p, data=json.dumps(o).encode(),
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=180).read())

def get(p):
    return json.loads(urllib.request.urlopen(p if p.startswith("http") else B + p, timeout=60).read())

def slug(name):
    s = re.sub(r"\.safetensors$", "", name)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s[:40]

def main():
    b = get("/api/bootstrap")
    artists = [n for n in b["loras"]
               if not n.startswith("sunhimi_") and "turbo" not in n and "modare" not in n]
    idx = {}
    if os.path.isfile(INDEX):
        try: idx = json.load(open(INDEX, encoding="utf-8"))
        except Exception: idx = {}
    os.makedirs(OUTDIR, exist_ok=True)
    for name in artists:
        key = slug(name)
        idx.setdefault(name, {})
        for w in WEIGHTS:
            wk = "%g" % w
            if str(wk) in idx[name] and os.path.isfile(idx[name][str(wk)]):
                continue
            r = post("/api/run", {"prompt": PROMPT, "negative": NEG, "width": W, "height": H,
                                  "steps": STEPS, "cfg": CFG, "seed": SEED,
                                  "prefix": "AF_%s_%s" % (key, wk.replace('.', '')),
                                  "loras": [{"name": name, "weight": w}],
                                  "model": "anima-base-v1.0.safetensors"})
            t0 = time.time()
            path = None
            while time.time() - t0 < 600:
                j = get("/api/job/" + r["job_id"])
                if j.get("status") in ("done", "error"):
                    imgs = (j.get("result") or {}).get("images") or []
                    path = imgs[0] if imgs else None
                    break
                time.sleep(2)
            if path:
                idx[name][str(wk)] = path
                json.dump(idx, open(INDEX, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                print("ok", name, wk, path, flush=True)
            else:
                print("fail", name, wk, flush=True)

if __name__ == "__main__":
    main()
