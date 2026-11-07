# -*- coding: utf-8 -*-
"""基线出图：固定配方 + 固定种子，输出到 产出作品/基线/，并统计亮度/饱和度。"""
import json, os, time, urllib.request, sys
B="http://127.0.0.1:8770"
ROOT=r"A:/workflow/dsh"
OUT=os.path.join(ROOT,"产出作品","基线")
def post(p,o):
    r=urllib.request.Request(B+p, data=json.dumps(o).encode(), headers={"Content-Type":"application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=180).read())
def get(p): return json.loads(urllib.request.urlopen(B+p, timeout=60).read())
POS=["@SINGLE","@ID","@FACE_SOFT","@CAM_MEDIUM","@LIGHT_WIN","@STYLE_SOFT"]
NEG=["@NEG_BASE","@NEG_HANDS","@NEG_REAL","@NEG_HARDCEL"]
def run(seed=1234, tag="base"):
    e=post("/api/expand", {"positive":[{"token":t} for t in POS], "negative":[{"token":t} for t in NEG]})
    loras=[{"name":"sunhimi_h2.safetensors","weight":0.5},{"name":"animaNai5E585B6E4B889.YDAV.safetensors","weight":0.66}]
    r=post("/api/run", {"prompt":e["positive"],"negative":e["negative"],"width":1024,"height":1536,"steps":28,"cfg":5.5,
        "seed":seed,"prefix":"baseline_"+tag,"loras":loras,"model":"anima-base-v1.0.safetensors",
        "blocks_pos":[{"token":t} for t in POS],"blocks_neg":[{"token":t} for t in NEG]})
    jid=r["job_id"]; t0=time.time()
    while time.time()-t0<600:
        j=get("/api/job/"+jid)
        if j.get("status") in ("done","error"): break
        time.sleep(2)
    if j.get("status")!="done": print("FAIL", j.get("result")); return None
    img=(j.get("result") or {}).get("images",[None])[0]
    os.makedirs(OUT, exist_ok=True)
    from PIL import Image, ImageStat
    st=ImageStat.Stat(Image.open(img).convert("RGB"))
    m=st.mean; lum=0.299*m[0]+0.587*m[1]+0.114*m[2]
    sat=ImageStat.Stat(Image.open(img).convert("HSV")).mean[1]
    dst=os.path.join(OUT, time.strftime("%Y%m%d_%H%M")+"_"+tag+"_s"+str(seed)+".png")
    import shutil; shutil.copy2(img, dst)
    print(json.dumps({"img":dst,"lum":round(lum,1),"sat":round(sat,1),"steps":28,"cfg":5.5}, ensure_ascii=False))
if __name__=="__main__":
    run(int(sys.argv[1]) if len(sys.argv)>1 else 1234, sys.argv[2] if len(sys.argv)>2 else "base")
