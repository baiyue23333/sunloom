
# -*- coding: utf-8 -*-
"""train_lora.py — 用 ComfyUI 内置训练节点训角色 LoRA（anima）

流程: LoadImageTextDataSetFromFolder -> MakeTrainingDataset -> TrainLoraNode -> SaveLoRA
"""
import argparse, json, sys, time, urllib.request
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

def post(url, data):
    req = urllib.request.Request(url, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read().decode())

ap = argparse.ArgumentParser()
ap.add_argument("--dataset", default="lora_local_char_lora")
ap.add_argument("--steps", type=int, default=1800)
ap.add_argument("--rank", type=int, default=8)
ap.add_argument("--lr", type=float, default=1e-4)
ap.add_argument("--batch", type=int, default=1)
ap.add_argument("--accum", type=int, default=4)
ap.add_argument("--prefix", default="local_char_lora_anima")
ap.add_argument("--offload", action="store_true", default=False)
ap.add_argument("--gc", action="store_true", default=True)
ap.add_argument("--no-gc", dest="gc", action="store_false")
ap.add_argument("--profile", default="", choices=["", "local", "gpu", "t4", "gpu"],
                help="按显卡一键套参数：local/gpu/t4/gpu")
ap.add_argument("--profile-auto", action="store_true", help="读 GPU 显存自动选档")
ap.add_argument("--dry-run", action="store_true", help="只打印参数，不提交")
ap.add_argument("--existing-lora", default="[None]", help="续训：已有 LoRA 文件名，如 local_char_lora_h2.safetensors")
ap.add_argument("--keep", type=int, default=3, help="同前缀只保留最近 N 个产物（0=不清理）")
ap.add_argument("--list-profiles", action="store_true")
ap.add_argument("--cache", default="", help="用已编码缓存训练（LoadTrainingDataset 的 folder_name）")
ap.add_argument("--build-cache", default="", help="只编码并存缓存，不训练")
a = ap.parse_args()

# ---- 分档参数（吸收 Colab notebook 的 GPU_PROFILE 思路）----
PROFILES = {
    "local": dict(rank=8,  batch=1, accum=4, lr=5e-5, gc=True,  offload=True,  note="4060 8G, 512x512, slow but stable"),
    "gpu":  dict(rank=16, batch=2, accum=2, lr=2e-5, gc=True,  offload=False, note="gpu 24G, 768x768, measured 11 min / 400 iters"),
    "t4":    dict(rank=16, batch=1, accum=4, lr=2e-5, gc=True,  offload=True,  note="T4 16G, 768x768, needs block swap"),
    "gpu":  dict(rank=16, batch=1, accum=4, lr=2e-5, gc=False, offload=False, note="GPU 40G, 1024x1024"),
}

def detect_profile():
    try:
        import subprocess
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total,name", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=15).stdout.strip()
        line = out.splitlines()[0] if out else ""
        mb = int(line.split(",")[0].replace("MiB", "").strip()) if line else 0
        low = line.lower()
        if "gpu" in low:
            return "gpu"
        if "t4" in low:
            return "t4"
        if mb >= 20000:
            return "gpu"
        return "local"
    except Exception:
        return "local"

if a.profile_auto and not a.profile:
    a.profile = detect_profile()

if a.profile:
    p = PROFILES[a.profile]
    a.rank = p["rank"]; a.batch = p["batch"]; a.accum = p["accum"]
    a.lr = p["lr"]; a.gc = p["gc"]; a.offload = p["offload"]
    print("[profile %s] %s" % (a.profile, p["note"]))
    print("  rank=%d batch=%d accum=%d lr=%g gc=%s offload=%s"
          % (a.rank, a.batch, a.accum, a.lr, a.gc, a.offload))

if a.list_profiles:
    for k, p in PROFILES.items():
        print("%-6s rank=%d batch=%d accum=%d lr=%g gc=%s offload=%s | %s"
              % (k, p["rank"], p["batch"], p["accum"], p["lr"], p["gc"], p["offload"], p["note"]))
    sys.exit(0)

if a.dry_run:
    print("[dry-run] dataset=%s steps=%d (迭代=%d)" % (a.dataset, a.steps, a.steps * a.accum))
    sys.exit(0)

def submit(wf, tag=""):
    t0 = time.time()
    r = post("http://127.0.0.1:8188/prompt", {"prompt": wf})
    pid = r["prompt_id"]
    print(tag, "queued", pid, flush=True)
    for i in range(7200):
        time.sleep(5)
        try:
            h = json.loads(urllib.request.urlopen(f"http://127.0.0.1:8188/history/{pid}", timeout=30).read().decode())
        except Exception:
            h = {}
        if pid in h:
            st = h[pid].get("status", {})
            print(tag, "DONE", json.dumps(st)[:300], flush=True)
            return st
        if i % 6 == 0:
            try:
                q = json.loads(urllib.request.urlopen("http://127.0.0.1:8188/queue", timeout=20).read().decode())
                print(tag, "waiting... %ds queue_running=%d" % (time.time() - t0, len(q.get("queue_running", []))), flush=True)
            except Exception:
                pass
    return {}

ENC = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "anima-base-v1.0.safetensors", "weight_dtype": "default"}},
    "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_06b_base.safetensors", "type": "stable_diffusion", "device": "default"}},
    "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
    "4": {"class_type": "LoadImageTextDataSetFromFolder", "inputs": {"folder": a.dataset}},
    "5": {"class_type": "MakeTrainingDataset", "inputs": {
        "images": ["4", 0], "vae": ["3", 0], "clip": ["2", 0], "texts": ["4", 1]}},
    "6": {"class_type": "SaveTrainingDataset", "inputs": {
        "latents": ["5", 0], "conditioning": ["5", 1],
        "folder_name": a.build_cache, "shard_size": 1000}},
}

if a.build_cache:
    print("[build-cache] dataset=%s -> datasets/%s" % (a.dataset, a.build_cache))
    submit(ENC, "[cache]")
    import glob as _g, os as _os
    _root = _os.environ.get("SUNLOOM_ROOT") or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    _comfy = _os.environ.get("SUNLOOM_COMFY") or _os.path.join(_root, "comfy")
    d = _os.path.join(_comfy, "ComfyUI", "datasets", a.build_cache)
    shards = _g.glob(_os.path.join(d, "shard_*.pkl"))
    print("缓存文件:", len(shards), "个 ->", d if shards else "(未生成)")
    sys.exit(0)

if a.cache:
    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "anima-base-v1.0.safetensors", "weight_dtype": "default"}},
        "4": {"class_type": "LoadTrainingDataset", "inputs": {"folder_name": a.cache}},
        "6": {"class_type": "TrainLoraNode", "inputs": {
            "model": ["1", 0], "latents": ["4", 0], "positive": ["4", 1],
            "batch_size": a.batch, "grad_accumulation_steps": a.accum, "steps": a.steps,
            "learning_rate": a.lr, "rank": a.rank, "optimizer": "AdamW", "loss_function": "MSE",
            "seed": 20261026, "training_dtype": "bf16", "lora_dtype": "bf16",
            "quantized_backward": False, "algorithm": "LoRA",
            "gradient_checkpointing": a.gc, "checkpoint_depth": 1, "offloading": a.offload,
            "existing_lora": a.existing_lora, "bucket_mode": True, "bypass_mode": False}},
        "7": {"class_type": "SaveLoRA", "inputs": {"lora": ["6", 0], "prefix": a.prefix, "steps": ["6", 2]}},
    }
    print("[cache] 使用 LoadTrainingDataset:", a.cache)
    submit(wf, "[train]")
    sys.exit(0)

wf = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "anima-base-v1.0.safetensors", "weight_dtype": "default"}},
    "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_06b_base.safetensors", "type": "stable_diffusion", "device": "default"}},
    "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
    "4": {"class_type": "LoadImageTextDataSetFromFolder", "inputs": {"folder": a.dataset}},
    "5": {"class_type": "MakeTrainingDataset", "inputs": {
        "images": ["4", 0], "vae": ["3", 0], "clip": ["2", 0], "texts": ["4", 1]}},
    "6": {"class_type": "TrainLoraNode", "inputs": {
        "model": ["1", 0],
        "latents": ["5", 0],
        "positive": ["5", 1],
        "batch_size": a.batch,
        "grad_accumulation_steps": a.accum,
        "steps": a.steps,
        "learning_rate": a.lr,
        "rank": a.rank,
        "optimizer": "AdamW",
        "loss_function": "MSE",
        "seed": 20261026,
        "training_dtype": "bf16",
        "lora_dtype": "bf16",
        "quantized_backward": False,
        "algorithm": "LoRA",
        "gradient_checkpointing": a.gc,
        "checkpoint_depth": 1,
        "offloading": a.offload,
        "existing_lora": a.existing_lora,
        "bucket_mode": True,
        "bypass_mode": False}},
    "7": {"class_type": "SaveLoRA", "inputs": {"lora": ["6", 0], "prefix": a.prefix, "steps": ["6", 2]}},
}

t0 = time.time()
r = post("http://127.0.0.1:8188/prompt", {"prompt": wf})
pid = r["prompt_id"]
print("queued", pid, flush=True)
last = 0
for i in range(7200):
    time.sleep(5)
    try:
        h = json.loads(urllib.request.urlopen(f"http://127.0.0.1:8188/history/{pid}", timeout=30).read().decode())
    except Exception:
        h = {}
    if pid in h:
        st = h[pid].get("status", {})
        print("DONE", json.dumps(st)[:300], flush=True)
        break
    if i % 6 == 0:
        try:
            q = json.loads(urllib.request.urlopen("http://127.0.0.1:8188/queue", timeout=20).read().decode())
            print("waiting... %ds queue_running=%d queue_pending=%d" % (time.time()-t0, len(q.get('queue_running', [])), len(q.get('queue_pending', []))), flush=True)
        except Exception as e:
            print("queue err", e, flush=True)
# ---- 成功后：打印产物位置 + 保留策略（吸收 notebook 的滚动保留思路）----
try:
    import glob, os
    _root = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _comfy = os.environ.get("SUNLOOM_COMFY") or os.path.join(_root, "comfy")
    outdir = os.path.join(_comfy, "ComfyUI", "output")
    made = sorted(glob.glob(os.path.join(outdir, a.prefix + "*.safetensors")), key=os.path.getmtime)
    if made:
        print("产物:", os.path.basename(made[-1]), "(%.0f MB)" % (os.path.getsize(made[-1]) / 1048576))
    if a.keep and len(made) > a.keep:
        for old in made[:-a.keep]:
            try:
                os.remove(old)
                print("清理旧产物:", os.path.basename(old))
            except Exception:
                pass
except Exception as e:
    print("保留策略跳过:", e, flush=True)

print("total %.0fs" % (time.time()-t0), flush=True)