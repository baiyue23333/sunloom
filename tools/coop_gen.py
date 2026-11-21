# -*- coding: utf-8 -*-
"""合作模式 · 生成式融合：背景画师先画，人物区用高去噪重绘（inpaint），风格可不同但光影同源。

用法:
  python tools/coop_gen.py --scene station --ratio 0.26 --ground-y 0.70 --x 0.34 --light left
  python tools/coop_gen.py --bg "已有背景.png" --ratio 0.26 ...
"""
import argparse, json, os, time, urllib.request
from PIL import Image, ImageDraw, ImageFilter

B = "http://127.0.0.1:8770"
ROOT = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from comfy_paths import COMFY_IN as CI
OUT = os.path.join(ROOT, "SD-Picture", "coop_gen")
W, H = 1536, 864

SCENES = {
 "station": "(abandoned train station reclaimed by vines:1.3), (long empty platform and rails:1.25), (drifting mist:1.15), (cold light from the far end:1.15)",
 "jungle": "(vast misty rainforest:1.3), (dense foliage and hanging vines:1.3), (shallow water reflection:1.2)",
 "cafe": "(quiet cafe interior:1.3), (wooden tables and warm lamps:1.2), (window light from the left:1.15)",
}
LIGHT = {"left":"(lit from the left:1.2), (shadow falling to the right:1.15)",
         "right":"(lit from the right:1.2), (shadow falling to the left:1.15)",
         "back":"(backlit, rim light on the silhouette:1.2)",
         "top":"(soft top light:1.2)"}

def post(p,o):
    r=urllib.request.Request(B+p,data=json.dumps(o).encode(),headers={"Content-Type":"application/json"})
    return json.loads(urllib.request.urlopen(r,timeout=180).read())
def get(p): return json.loads(urllib.request.urlopen(B+p,timeout=60).read())
def expand(pos,neg): return post("/api/expand",{"positive":pos,"negative":neg})
def run(prompt,neg,prefix,loras,seed,steps=30,cfg=5.5,mode="t2i",ref="",mask="",denoise=1.0,w=W,h=H):
    r=post("/api/run",{"prompt":prompt,"negative":neg,"width":w,"height":h,"steps":steps,"cfg":cfg,"seed":seed,
        "prefix":prefix,"loras":loras,"mode":mode,"reference":ref,"mask":mask,"denoise":denoise})
    t0=time.time()
    while time.time()-t0<900:
        j=get("/api/job/"+r["job_id"])
        try:
            _pg=float(j.get("progress") or 0.0)
            if _pg>0: print("PROGRESS %.3f"%_pg, flush=True)
        except Exception:
            pass
        if j.get("status") in ("done","error"):
            imgs=(j.get("result") or {}).get("images") or []
            if not imgs: raise RuntimeError(str(j.get("result",{}).get("error")))
            return imgs[0]
        time.sleep(2)
    raise TimeoutError("超时")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--scene",default="station",choices=list(SCENES))
    ap.add_argument("--prompt-scene",default="")
    ap.add_argument("--prompt-char",default="")
    ap.add_argument("--bg",default="",help="复用已有背景图")
    ap.add_argument("--scene-lora",default="anima-base-1-env_lora_a.safetensors")
    ap.add_argument("--char-lora",default="@style_lora_b_anima_ver20.safetensors")
    ap.add_argument("--ratio",type=float,default=0.26)
    ap.add_argument("--ground-y",type=float,default=0.70)
    ap.add_argument("--x",type=float,default=0.34)
    ap.add_argument("--light",default="left",choices=list(LIGHT))
    ap.add_argument("--seed",type=int,default=517301)
    ap.add_argument("--denoise",type=float,default=0.95)
    ap.add_argument("--blur",type=int,default=10)
    ap.add_argument("--char-weight",type=float,default=0.9)
    args=ap.parse_args()

    stamp=time.strftime("%Y%m%d_%H%M%S"); out=os.path.join(OUT,stamp); os.makedirs(out,exist_ok=True)
    light=LIGHT[args.light]

    if args.bg and os.path.isfile(args.bg):
        bg_path=args.bg; print("[1/3] 复用背景:",bg_path,flush=True)
    else:
        scene=args.prompt_scene or SCENES[args.scene]
        print("[1/3] 背景画师…",flush=True)
        ex=expand([{"token":"","text":scene+", "+light,"weight":1,"enabled":True}],
                  [{"token":"","text":"(people:1.35), (person:1.3)","weight":1,"enabled":True}])
        bg_path=run(ex["positive"],ex["negative"],"GEN_bg",[{"name":args.scene_lora,"weight":1.0}],args.seed)
        print("   ",bg_path,flush=True)

    bg=Image.open(bg_path).convert("RGB")
    fh=int(H*args.ratio); fx=int(W*args.x); fy=int(H*args.ground_y)
    box=(max(0,fx-int(fh*0.55)), max(0,fy-fh), min(W,fx+int(fh*0.55)), min(H,fy+int(fh*0.06)))
    mask=Image.new("L",(W,H),0); ImageDraw.Draw(mask).rectangle(box,fill=255)
    mask=mask.filter(ImageFilter.GaussianBlur(args.blur))
    mask_name="gen_mask_%dx%d_%d.png"%(W,H,args.seed); mask.save(os.path.join(CI,mask_name))
    print("[2/3] 人物区生成式重绘，box",box,flush=True)

    cp=args.prompt_char or ("1girl, solo, full body standing, wearing a long coat and trousers, "
                            "(bright even lighting:1.15), (visible face and eyes:1.2), (standing on the ground:1.2)")
    ex2=expand([{"token":"","text":cp+", "+light,"weight":1,"enabled":True}],
               [{"token":"","text":"(silhouette:1.25), (backlit:1.15), (close-up:1.2), (two people:1.25)","weight":1,"enabled":True}])
    gen=run(ex2["positive"],ex2["negative"],"GEN_char",[{"name":args.char_lora,"weight":args.char_weight}],
            args.seed,mode="inpaint",ref=bg_path,mask=mask_name,denoise=args.denoise)
    print("   ",gen,flush=True)

    print("[3/3] 低幅度统一（可选）…",flush=True)
    fin=run("(unified lighting:1.1), (subtle film grain:1.03)","(text:1.2)","GEN_final",[],
            args.seed,mode="i2i",ref=gen,denoise=0.12,steps=24,cfg=4.5)
    Image.open(fin).convert("RGB").save(os.path.join(out,"comp.png"))
    Image.open(bg_path).save(os.path.join(out,"bg.png"))
    json.dump({"mode":"gen","created":stamp,"bg":bg_path,"char_lora":args.char_lora,"scene_lora":args.scene_lora,
               "ratio":args.ratio,"ground_y":args.ground_y,"x":args.x,"light":args.light,"seed":args.seed,
               "denoise":args.denoise,"box":box,"comp":os.path.join(out,"comp.png")},
              open(os.path.join(out,"contract.json"),"w",encoding="utf-8"),ensure_ascii=False,indent=1)
    print("done:",out,flush=True)

if __name__=="__main__":
    main()
