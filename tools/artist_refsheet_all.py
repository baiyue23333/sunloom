# -*- coding: utf-8 -*-
"""每个画师一张参考图：弱身份(0.5) + CAM_BUST + 灰背景，展示画师本色。"""
import json, os, re, time, urllib.request
B="http://127.0.0.1:8770"
OUT_DIR = r"A:/workflow/dsh/产出作品/画师参考"
os.makedirs(OUT_DIR, exist_ok=True)
def post(p,o):
    r=urllib.request.Request(B+p,data=json.dumps(o).encode(),headers={"Content-Type":"application/json"})
    return json.loads(urllib.request.urlopen(r,timeout=180).read())
def get(p): return json.loads(urllib.request.urlopen(p if p.startswith("http") else B+p,timeout=60).read())
b=get("/api/bootstrap")
artists=[n for n in b["loras"] if not n.startswith("sunhimi_") and "turbo" not in n and "modare" not in n]
WEIGHT={"animaNai5E585B6E4B889.YDAV.safetensors":0.6,"Anima_Real_Skin_Enhancer.safetensors":0.3}
ID="1girl, solo, upper body, ivory white hair, straight fringe, heterochromia one red and one grey eye"
NEG="lowres, blurry, bad anatomy, extra people, watermark, text"
os.makedirs(r"A:/workflow/dsh/scratch/refs", exist_ok=True)
out={}
for name in artists:
    w=WEIGHT.get(name,1.0)
    prompt=ID+", grey background, (soft studio light:1.05)"
    r=post("/api/run",{"prompt":prompt,"negative":NEG,"width":1024,"height":1536,"steps":28,"cfg":5.5,
        "seed":515151,"prefix":"REF_"+re.sub(r'[^A-Za-z0-9]+','_',name)[:30],
        "loras":[{"name":name,"weight":w}]})
    t0=time.time(); path=None
    while time.time()-t0<420:
        j=get("/api/job/"+r["job_id"])
        if j.get("status") in ("done","error"):
            imgs=(j.get("result") or {}).get("images") or []
            path=imgs[0] if imgs else None; break
        time.sleep(2)
    if path and os.path.isfile(path):
        dest=os.path.join(OUT_DIR, re.sub(r'[^A-Za-z0-9]+','_',name)[:40]+".png")
        import shutil; shutil.copyfile(path, dest)
        out[name]=dest
        print("ok", name, "->", dest, flush=True)
    else:
        print("fail", name, flush=True)
json.dump(out, open(r"A:/workflow/dsh/产出作品/画师参考/_index.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
