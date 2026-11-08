
# -*- coding: utf-8 -*-
"""server.py - local block-building prompt station for the anima character system."""
import store
import io
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

# pythonw 下 stdout/stderr 是 None，先接到日志文件，否则 uvicorn 一启动就崩
_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "server.log")
if sys.stdout is None or sys.stderr is None:
    os.makedirs(os.path.dirname(_LOG), exist_ok=True)
    _f = open(_LOG, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _f
    sys.stderr = sys.stderr or _f
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REF = os.path.join(ROOT, "ref")
LIB = os.path.join(REF, "prompt_lib.json")
CHAR = os.path.join(REF, "character.json")
REG = os.path.join(REF, "registry.jsonl")
PRESETS = os.path.join(HERE, "data", "presets.json")
OUT_DIR = os.path.join(ROOT, "SD-Picture", "station_out")
COMFY_OUT = os.path.join(ROOT, "comfy", "ComfyUI", "output")
DOC_DIRS = [os.path.join(ROOT, "产出作品")]  # 文档唯一真相：产出作品/（ref/ 只放脚本与数据）
PY = sys.executable

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(os.path.join(HERE, "data"), exist_ok=True)

sys.path.insert(0, REF)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import comfy as cf  # noqa: E402
import graph as gf  # noqa: E402
import ir as irv  # noqa: E402
import prompts as pt  # noqa: E402
import promptlib  # noqa: E402

FEATURES = [
    {"group": "拼装", "items": [
        "拖拽/点击添加积木（机位、打光、身份、体型、表情、服装、型态、负向、场景）",
        "每块可调权重（写进提示词如 (bone:1.35)）、可临时停用、可删除、可左右拖动排序",
        "自由文本块：任意英文标签直接插入正向/负向",
        "实时展开预览：宏自动展开，显示字符数与使用了哪些宏",
        "快速模板：一键摆好一组积木（胸像窗光/夜灯/楼梯/门厅）",
        "参数：尺寸预设、步数、CFG、种子、前缀、任意多个 LoRA 与权重",
        "出图：进度条 + 预计耗时 + 完成后可直接登记 A/B/C" ]},
    {"group": "画师 LoRA · 弱 3D", "items": [
        "弱 3D 风格怎么写：@silver palace 权重 1.3（1.0 偏弱），只挂它一个 LoRA",
        "不要再叠 h2 / modare / Lucent —— 风格会互相抢，3D 感消失",
        "身份用文本（ivory white hair, heterochromia…），别用 @ID 积木",
        "场景/服装/光各留 1 块，块越多 LoRA 越被稀释",
        "参数 1024×1536 / 28 步 / CFG 5.5；灰底或浅景深都行",
        "词库→组合推荐里有现成模板：弱 3D 人像、弱 3D · 场景版" ]},
    {"group": "词库", "items": [
        "查看/搜索全部宏（@ID @BODY @FACE @CAM_* @OUT_* @DRAPE_* @LIGHT_* @NEG_*）",
        "新建、编辑、删除任意宏，保存即写入 prompt_lib.json",
        "服装编辑器：slip / initial 的正向、负向、型态（半脱/披肩/肘部/穿好）",
        "保存后积木库与预览立即生效（同一份数据源）" ]},
    {"group": "画廊", "items": [
        "浏览工作站输出 / remote_out / 原图，网格缩略图",
        "点击看大图 + 自动质检（平均亮度、脸部亮度、过曝%、死黑%、是否超标）",
        "在弹窗里直接登记 A/B/C 并写备注" ]},
    {"group": "登记表", "items": [
        "查看最近登记（时间、等级、备注、文件名）",
        "顶栏实时显示登记总数" ]},
    {"group": "训练", "items": [
        "数据集列表与样本数、已建缓存列表",
        "档位选择（auto/local/4090/t4/a100）、steps/rank/lr/保留数",
        "建缓存 / 用缓存训练，续训已有 LoRA",
        "只预演（dry-run）看实际参数，不占用显卡",
        "实时日志与进度解析" ]},
    {"group": "打标", "items": [
        "WD14 自动打标：触发词、附加词、阈值",
        "角色 LoRA 专用：删掉外观标签（发/眼/饰/服装）",
        "预览模式或直接写入 caption",
        "实时日志" ]},
    {"group": "维护", "items": [
        "磁盘用量（各图像目录、ComfyUI 输出、数据集）",
        "清理预演 / 执行清理（登记作品自动保留）",
        "文档浏览（画师手册、服装规格、打光规则、复盘、指南等）" ]},
    {"group": "全局", "items": [
        "顶栏状态：ComfyUI 版本/在线、队列长度、登记总数（15 秒自动刷新）",
        "所有改动直接写回 ref/prompt_lib.json、ref/character.json、ref/registry.jsonl",
        "快捷键：Esc 关闭弹窗" ]},
]

app = FastAPI(title="Station")

JOBS: Dict[str, dict] = {}
LAST_GRAPH: dict = {}


# ---------------- data helpers ----------------
def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}



def _snapshot(path):
    """每次写前存一份时间戳快照，防止多处写入互相覆盖后无法回滚。"""
    try:
        d = os.path.join(HERE, "data", "snapshots")
        os.makedirs(d, exist_ok=True)
        base = os.path.basename(path)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, os.path.join(d, base + "." + stamp + ".bak"))
        keep = sorted([x for x in os.listdir(d) if x.startswith(base + ".")])
        for old in keep[:-20]:
            try:
                os.remove(os.path.join(d, old))
            except OSError:
                pass
    except Exception:
        pass


def write_json(path, data):
    _snapshot(path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)




def load_tokens():
    tokens, lib, ch = pt.load_tokens()
    return tokens, lib, ch


def expand(text, tokens):
    return pt.expand(text, tokens)


def list_datasets():
    d = os.path.join(ROOT, "comfy", "ComfyUI", "input")
    if not os.path.isdir(d):
        return []
    return sorted([x for x in os.listdir(d) if os.path.isdir(os.path.join(d, x))])


def list_models():
    d = os.path.join(ROOT, "comfy", "ComfyUI", "models", "diffusion_models")
    try:
        return sorted(f for f in os.listdir(d) if f.endswith((".safetensors", ".gguf", ".sft")))
    except Exception:
        return []


def list_loras():
    d = os.path.join(ROOT, "comfy", "ComfyUI", "models", "loras")
    if not os.path.isdir(d):
        return []
    return sorted([x for x in os.listdir(d) if x.endswith(".safetensors")])


def dataset_samples(name):
    d = os.path.join(ROOT, "comfy", "ComfyUI", "input", name)
    n = 0
    for _, _, files in os.walk(d):
        n += len([f for f in files if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))])
    return n


def estimate_seconds(w, h, steps, batch=1, model=""):
    base = (w * h * steps * batch) * 1.60e-6 + 1.5
    if model and "29B" in str(model):
        base *= 2.8
    return round(base)


# ---------------- models ----------------
class Block(BaseModel):
    id: str = ""
    token: str = ""
    text: str = ""
    weight: float = 1.0
    enabled: bool = True


class ExpandReq(BaseModel):
    positive: List[Block] = []
    negative: List[Block] = []


class RunReq(BaseModel):
    prompt: str
    negative: str = ""
    width: int = 1024
    height: int = 1536
    steps: int = 30
    cfg: float = 5.5
    seed: int = 0
    prefix: str = "station"
    loras: List[Dict[str, Any]] = []
    save_to: str = "station_out"
    mode: str = "t2i"          # t2i | i2i | inpaint
    blocks_pos: List[Dict[str, Any]] = []
    blocks_neg: List[Dict[str, Any]] = []
    reference: str = ""        # i2i / inpaint 的底图（绝对路径或 ComfyUI input 内文件名）
    mask: str = ""             # inpaint 蒙版文件名（ComfyUI input 内）
    denoise: float = 0.6
    model: str = ""           # 空 = anima-base-v1.0；可切 anima29B_v10_int8.safetensors



LLM_DIRS = {
    "quality": os.path.join(ROOT, "models", "llm", "Qwen2.5-1.5B-Instruct"),
    "fast": os.path.join(ROOT, "models", "llm", "Qwen2.5-0.5B-Instruct"),
}
LLM_DIR = next((d for d in LLM_DIRS.values() if os.path.isdir(d)), LLM_DIRS["fast"])
_POLISHERS = {"quality": {"tok": None, "mdl": None}, "fast": {"tok": None, "mdl": None}}
_TORCH = {"m": None}


class PolishReq(BaseModel):
    text: str
    model: str = "quality"


def _get_polisher(which="quality"):
    which = "fast" if str(which).lower().startswith("fast") or "0.5" in str(which) else "quality"
    box = _POLISHERS[which]
    if box["mdl"] is not None:
        return box, which
    d = LLM_DIRS.get(which)
    if not d or not os.path.isdir(d):
        return None, which
    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM
        if _TORCH["m"] is None:
            _TORCH["m"] = torch
        tok = AutoTokenizer.from_pretrained(d)
        mdl = AutoModelForCausalLM.from_pretrained(d, torch_dtype=torch.float32)
        mdl.eval()
        box.update(tok=tok, mdl=mdl)
        return box, which
    except Exception:
        return None, which


@app.post("/api/polish")
def api_polish(req: PolishReq):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "empty text")
    box, which = _get_polisher(req.model)
    if not box:
        return {"text": text, "ok": False, "note": "本地润色模型未就绪（缺少 models/llm 下的目录）"}
    tok, mdl = box["tok"], box["mdl"]
    torch = _TORCH["m"]
    sys_p = ("You rewrite image-generation prompts into fluent, vivid English. "
             "Keep EVERY visual detail: clothing items, colors, accessories, pose, setting and lighting. "
             "Do not summarize, do not drop items, do not add new subjects. "
             "Output only the rewritten prompt, no explanations.")
    msgs = [{"role": "system", "content": sys_p}, {"role": "user", "content": text}]
    try:
        ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt")
        with torch.no_grad():
            out = mdl.generate(ids, max_new_tokens=220, do_sample=False)
        new = tok.decode(out[0][ids.shape[-1]:], skip_special_tokens=True).strip()
    except Exception as e:
        return {"text": text, "ok": False, "note": "润色失败: %s" % e}
    return {"text": new or text, "ok": True, "model": which}


class Tags2TextReq(BaseModel):
    blocks: List[Block] = []


_CTX = [
    ("@OUT", "outfit"), ("@HOSE", "outfit"), ("@SHOE", "outfit"),
    ("@POSE", "pose"), ("@SET", "scene"), ("@BG", "scene"),
    ("@LIGHT", "light"), ("@TIME", "light"), ("@ATMO", "atmo"), ("@WEATHER", "atmo"),
    ("@CAM", "camera"), ("@COMP", "camera"),
    ("@STYLE", "style"), ("@MOOD", "mood"), ("@GAZE", "face"), ("@FACE", "face"), ("@HAIR", "hair"),
    ("@BODY", "body"),
]


def _tag_cat(tok):
    t = (tok or "").upper()
    for pre, cat in _CTX:
        if t.startswith(pre):
            return cat
    return "extra"


def _clean(frag):
    import re as _re
    frag = _re.sub(r"\(([^():]+):[0-9.]+\)", r"\1", frag)
    for ch in "()[]'\"":
        frag = frag.replace(ch, "")
    frag = " ".join(frag.split()).strip(" ,.")
    if "@" in frag or len(frag) < 3:
        return ""
    return frag


def _with_article(phrase):
    if not phrase:
        return phrase
    low = phrase.lower()
    if low.startswith(("a ", "an ", "the ", "his ", "her ", "their ")):
        return phrase
    return "a " + phrase


@app.post("/api/tags2text")
def api_tags2text(req: Tags2TextReq):
    tokens, _lib, _ch = load_tokens()
    SKIP = ("@COMP",)
    IDENT = ("@SINGLE", "@ID")
    BOILER = ("1girl", "solo", "single character", "one continuous scene", "photoreal",
              "best quality", "masterpiece", "highres", "absurdres",
              "full-bleed", "no borders", "no panels", "composition")
    buckets = {}
    for b in req.blocks:
        if getattr(b, "enabled", True) is False:
            continue
        if b.token and b.token.startswith(SKIP):
            continue
        if b.token and b.token.startswith(IDENT):
            raw = expand(b.token, tokens)
            for part in str(raw).split(","):
                part = _clean(part)
                if not part:
                    continue
                if any(x in part.lower() for x in BOILER):
                    continue
                arr = buckets.setdefault("identity", [])
                if part not in arr:
                    arr.append(part)
            continue
        raw = expand(b.token, tokens) if b.token else (b.text or "")
        cat = _tag_cat(b.token) if b.token else "extra"
        for part in str(raw).split(","):
            part = _clean(part)
            if not part:
                continue
            arr = buckets.setdefault(cat, [])
            if part not in arr:
                arr.append(part)

    def take(*cats, limit=5):
        out = []
        for c in cats:
            for x in buckets.get(c, []):
                if x not in out and len(out) < limit:
                    out.append(x)
        return out

    def join_and(items):
        items = [x for x in items if x]
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        return ", ".join(items[:-1]) + " and " + items[-1]

    ident = take("identity", limit=6)
    if ident:
        for extra in ("heterochromia eyes, one red and one grey", "a sunflower hair ornament"):
            if extra not in ident:
                ident.append(extra)
    hair = take("hair", limit=2)
    face = take("face", limit=2)
    body = take("body", limit=2)
    outfit = take("outfit", limit=5)
    pose = take("pose", limit=2)
    scene = take("scene", limit=3)
    light = take("light", limit=2)
    atmo = take("atmo", limit=2)
    mood = take("mood", limit=1)
    camera = take("camera", limit=2)
    style = take("style", limit=2)
    extra = take("extra", limit=3)

    sents = []
    who = "A girl"
    feats = join_and(ident + body + hair + face)
    if feats:
        who += " with " + feats
    sents.append(who)
    if outfit:
        sents.append("She wears " + join_and(outfit))
    if pose:
        line = "She is " + join_and(pose)
        if scene:
            line += ", in " + _with_article(join_and(scene))
        sents.append(line)
    elif scene:
        sents.append("The setting is " + _with_article(join_and(scene)))
    if light or atmo:
        sents.append("The lighting is " + join_and(light + atmo))
    if mood:
        sents.append("The mood is " + join_and(mood))
    tail = join_and(camera + style + extra)
    if tail:
        sents.append("Shot as " + tail)
    text = ". ".join(x.rstrip(".") for x in sents if x).strip()
    if text and not text.endswith("."):
        text += "."
    return {"text": text, "buckets": {k: v for k, v in buckets.items()}}


class MaskReq(BaseModel):
    image: str
    box: str                  # "x,y,w,h" 写进原图像素
    prompt: str = ""
    negative: str = ""
    denoise: float = 0.45
    steps: int = 24
    cfg: float = 5.0
    seed: int = 0
    prefix: str = "handfix"
    loras: List[Dict[str, Any]] = []


class ReproReq(BaseModel):
    mode: str                 # keep_person | keep_image
    model: str = ""
    reference: str
    prompt: str = ""
    negative: str = ""
    denoise: float = 0.6
    width: int = 1024
    height: int = 1536
    steps: int = 30
    cfg: float = 5.5
    seed: int = 0
    prefix: str = "repro"
    loras: List[Dict[str, Any]] = []


# ---------------- 批量精品 ----------------
class BatchQReq(BaseModel):
    count: int = 4
    refine: bool = True
    denoise: float = 0.3
    steps: int = 0
    cfg: float = 0.0
    model: str = ""
    templates: List[str] = []
    loras: List[Dict[str, Any]] = []


def _batchq_loras(req):
    if req.loras:
        return req.loras
    return [{"name": "sunhimi_h4.safetensors", "weight": 0.65},
            {"name": "animaNai5E585B6E4B889.YDAV.safetensors", "weight": 0.66}]


def _run_batchq(req: BatchQReq, jid):
    import random as _rnd
    try:
        all_tpl = list(store.load_templates())
        pool = [t for t in all_tpl if not str(t.get("name", "")).startswith("风格") and "29B" not in str(t.get("name", ""))]
        if req.templates:
            want = set(req.templates)
            pool = [t for t in all_tpl if t.get("name") in want]
        if not pool:
            JOBS[jid].update(status="error", result={"error": "没有可用模板"})
            return
        loras = _batchq_loras(req)
        saved_all = []
        n = max(1, min(24, req.count))
        for i in range(n):
            tpl = _rnd.choice(pool)
            params = tpl.get("params") or {}
            size = str(params.get("size") or "1024x1536")
            try:
                w, h = [int(x) for x in size.split("x")]
            except Exception:
                w, h = 1024, 1536
            steps = req.steps or int(params.get("steps") or 30)
            cfg = req.cfg or float(params.get("cfg") or 5.5)
            model = req.model or str(params.get("model") or "")
            exp = api_expand(ExpandReq(positive=tpl.get("positive") or [], negative=tpl.get("negative") or []))
            seed = 100000 + _rnd.randint(0, 899999)
            label = "bq_%02d" % (i + 1)
            wf = cf.build_wf(exp["positive"], exp["negative"], w, h, steps, cfg, seed, loras, label, unet=(model or None))
            pid = cf.submit(wf)
            res = cf.wait(pid, timeout=1800)
            if not res.get("ok") or not res.get("images"):
                job_log(jid, "第 %d 张失败：%s" % (i + 1, res.get("error", ""))[:200])
                continue
            first = _save_result(res["images"][0], label, seed)
            if not first:
                continue
            add_recipe(first, {"ts": time.time(), "mode": "t2i", "workflow": "batchq",
                               "positive": exp["positive"], "negative": exp["negative"],
                               "blocks_pos": [(b.model_dump() if hasattr(b, "model_dump") else b) for b in (tpl.get("positive") or [])],
                               "blocks_neg": [(b.model_dump() if hasattr(b, "model_dump") else b) for b in (tpl.get("negative") or [])],
                               "size": [w, h], "steps": steps, "cfg": cfg, "seed": seed,
                               "loras": loras, "model": model})
            saved_all.append(first)
            if req.refine:
                ref = _prepare_reference(first)
                wf2 = cf.build_wf(exp["positive"], exp["negative"], w, h, max(12, steps - 4), cfg, seed,
                                  loras, label + "_ref", unet=(model or None))
                for nid, node in list(wf2.items()):
                    if node.get("class_type") == "EmptyLatentImage":
                        wf2.pop(nid, None)
                wf2["30"] = {"class_type": "LoadImage", "inputs": {"image": ref}}
                wf2["31"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["30", 0], "vae": ["3", 0]}}
                wf2["9"]["inputs"]["latent_image"] = ["31", 0]
                wf2["9"]["inputs"]["denoise"] = max(0.15, min(0.5, float(req.denoise)))
                pid2 = cf.submit(wf2)
                res2 = cf.wait(pid2, timeout=1800)
                if res2.get("ok") and res2.get("images"):
                    second = _save_result(res2["images"][0], label + "_ref", seed)
                    if second:
                        saved_all.append(second)
            JOBS[jid]["progress"] = (i + 1) / n
            job_log(jid, "完成 %d/%d：%s" % (i + 1, n, os.path.basename(first)))
        JOBS[jid].update(status="done", progress=1.0, result={"images": saved_all, "count": len(saved_all)})
    except Exception as e:
        JOBS[jid].update(status="error", result={"error": str(e)[:300]})
        job_log(jid, "ERROR " + str(e)[:300])


@app.post("/api/batch_quality")
def api_batch_quality(req: BatchQReq):
    jid = job_new("batchq", "batch")
    job_log(jid, "批量精品：%d 张，精修=%s" % (req.count, req.refine))
    threading.Thread(target=lambda: _run_batchq(req, jid), daemon=True).start()
    return {"job_id": jid, "count": req.count}


# ---------------- 一条龙：批量 → 评分 → 故障 ----------------
class AutoPipeReq(BaseModel):
    count: int = 4
    refine: bool = True
    denoise: float = 0.3
    glitch: float = 0.0
    keep: int = 2
    templates: List[str] = []
    loras: List[Dict[str, Any]] = []


def _run_autopipe(req: AutoPipeReq, jid):
    import random as _rnd
    try:
        all_tpl = list(store.load_templates())
        pool = [t for t in all_tpl if not str(t.get("name", "")).startswith("风格") and "29B" not in str(t.get("name", ""))]
        if req.templates:
            want = set(req.templates)
            pool = [t for t in all_tpl if t.get("name") in want]
        if not pool:
            JOBS[jid].update(status="error", result={"error": "没有可用模板"})
            return
        loras = req.loras or [{"name": "sunhimi_h4.safetensors", "weight": 0.65},
                              {"name": "animaNai5E585B6E4B889.YDAV.safetensors", "weight": 0.66}]
        made = []
        n = max(1, min(16, req.count))
        for i in range(n):
            tpl = _rnd.choice(pool)
            params = tpl.get("params") or {}
            size = str(params.get("size") or "1024x1536")
            try:
                w, h = [int(x) for x in size.split("x")]
            except Exception:
                w, h = 1024, 1536
            steps = int(params.get("steps") or 30)
            cfg = float(params.get("cfg") or 5.5)
            model = str(params.get("model") or "")
            exp = api_expand(ExpandReq(positive=tpl.get("positive") or [], negative=tpl.get("negative") or []))
            seed = 100000 + _rnd.randint(0, 899999)
            label = "ap_%02d" % (i + 1)
            wf = cf.build_wf(exp["positive"], exp["negative"], w, h, steps, cfg, seed, loras, label, unet=(model or None))
            res = cf.wait(cf.submit(wf), timeout=1800)
            if not res.get("ok") or not res.get("images"):
                job_log(jid, "第 %d 张失败" % (i + 1))
                continue
            first = _save_result(res["images"][0], label, seed)
            if not first:
                continue
            add_recipe(first, {"ts": time.time(), "mode": "t2i", "workflow": "autopipe",
                               "positive": exp["positive"], "negative": exp["negative"],
                               "blocks_pos": [(b.model_dump() if hasattr(b, "model_dump") else b) for b in (tpl.get("positive") or [])],
                               "blocks_neg": [(b.model_dump() if hasattr(b, "model_dump") else b) for b in (tpl.get("negative") or [])],
                               "size": [w, h], "steps": steps, "cfg": cfg, "seed": seed, "loras": loras, "model": model})
            best = first
            if req.refine:
                ref = _prepare_reference(first)
                wf2 = cf.build_wf(exp["positive"], exp["negative"], w, h, max(12, steps - 4), cfg, seed, loras,
                                  label + "_ref", unet=(model or None))
                for nid, node in list(wf2.items()):
                    if node.get("class_type") == "EmptyLatentImage":
                        wf2.pop(nid, None)
                wf2["30"] = {"class_type": "LoadImage", "inputs": {"image": ref}}
                wf2["31"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["30", 0], "vae": ["3", 0]}}
                wf2["9"]["inputs"]["latent_image"] = ["31", 0]
                wf2["9"]["inputs"]["denoise"] = max(0.15, min(0.5, float(req.denoise)))
                res2 = cf.wait(cf.submit(wf2), timeout=1800)
                if res2.get("ok") and res2.get("images"):
                    second = _save_result(res2["images"][0], label + "_ref", seed)
                    if second:
                        best = second
            try:
                score = float(mirror_score(best))
            except Exception:
                score = 0.0
            made.append({"path": best, "score": round(score, 3)})
            JOBS[jid]["progress"] = (i + 1) / n * 0.9
            job_log(jid, "完成 %d/%d 评分 %.1f" % (i + 1, n, score))
        made.sort(key=lambda x: -x["score"])
        keep = max(1, min(len(made), req.keep))
        kept = made[:keep]
        out = []
        for item in kept:
            p = item["path"]
            if req.glitch and req.glitch > 0:
                try:
                    import glitchify
                    dst = os.path.splitext(p)[0] + "_glitch.png"
                    glitchify.glitchify(p, dst, max(0.1, min(2.0, req.glitch)))
                    p = dst
                except Exception as e:
                    job_log(jid, "故障失败：" + str(e)[:120])
            out.append({"path": p, "score": item["score"]})
        JOBS[jid].update(status="done", progress=1.0, result={"kept": out, "all": made})
    except Exception as e:
        JOBS[jid].update(status="error", result={"error": str(e)[:300]})
        job_log(jid, "ERROR " + str(e)[:300])


@app.post("/api/autopipe")
def api_autopipe(req: AutoPipeReq):
    jid = job_new("autopipe", "auto")
    job_log(jid, "一条龙：%d 张 → 保留 %d，故障 %s" % (req.count, req.keep, req.glitch))
    threading.Thread(target=lambda: _run_autopipe(req, jid), daemon=True).start()
    return {"job_id": jid}


class ValidateReq(BaseModel):
    positive: List[Block] = []
    negative: List[Block] = []


class LogReq(BaseModel):
    path: str
    verdict: str = "B"
    note: str = ""
    seed: Optional[int] = None
    tags: str = ""
    params: str = ""


class TokenReq(BaseModel):
    name: str
    text: str
    category: str = "custom"
    subgroup: str = ""
    color: str = ""


class GarmentReq(BaseModel):
    key: str
    prompt: str = ""
    negative: str = ""
    drape: str = ""
    label: str = ""
    use_for: str = ""
    hands_left: str = ""
    hands_right: str = ""
    note: str = ""


class PresetReq(BaseModel):
    name: str
    positive: List[Block] = []
    negative: List[Block] = []
    params: Dict[str, Any] = {}


class TrainReq(BaseModel):
    dataset: str
    profile: str = "auto"
    steps: int = 100
    rank: int = 0
    lr: float = 0.0
    cache: str = ""
    build_cache: str = ""
    existing_lora: str = ""
    keep: int = 3
    dry_run: bool = True
    prefix: str = "station_lora"


class TagReq(BaseModel):
    dataset: str
    trigger: str = ""
    extra: str = "1girl"
    write: bool = False
    drop_appearance: bool = True
    threshold: float = 0.35


# ---------------- jobs ----------------
JOBS_MAX = 200


def _evict_jobs():
    if len(JOBS) <= JOBS_MAX:
        return
    done = [(j["started"], k) for k, j in JOBS.items() if j.get("status") != "running"]
    done.sort()
    for _, k in done[:max(0, len(JOBS) - JOBS_MAX)]:
        JOBS.pop(k, None)


def job_new(kind, label=""):
    jid = uuid.uuid4().hex[:10]
    _evict_jobs()
    JOBS[jid] = {"id": jid, "kind": kind, "label": label, "status": "running",
                 "progress": 0.0, "logs": [], "result": None, "started": time.time()}
    return jid


def job_log(jid, line):
    j = JOBS.get(jid)
    if not j:
        return
    j["logs"].append(line.rstrip())
    if len(j["logs"]) > 400:
        j["logs"] = j["logs"][-400:]


@app.get("/api/job/{jid}")
def job_get(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "unknown job")
    j["elapsed"] = round(time.time() - j["started"], 1)
    return j



@app.get("/api/reliability")
def api_reliability():
    """从备注里最后一条「实测(…)」推断积木可信度：OK / X / ?。"""
    tokens, lib, _ = load_tokens()
    notes = (lib or {}).get("notes") or {}
    out = {}
    for k in tokens:
        n = notes.get(k) or ""
        idx = n.rfind("实测(")
        if idx < 0:
            continue
        tail = n[idx:]
        if "失败" in tail:
            out[k] = "X"
        elif "成功" in tail or "成立" in tail:
            out[k] = "OK"
        else:
            out[k] = "?"
    return {"items": out, "total": len(out),
            "x": sum(1 for v in out.values() if v == "X")}


@app.post("/api/comfy/free")
def api_comfy_free():
    try:
        req = urllib.request.Request(cf.COMFY + "/free",
                                     data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@app.post("/api/comfy/restart")
def api_comfy_restart():
    """杀掉 ComfyUI 进程，交给 supervisor 自动拉起。"""
    import subprocess
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/FI", "IMAGENAME eq python.exe",
                            "/FI", "WINDOWTITLE eq *"], capture_output=True)
        return {"ok": True, "note": "supervisor 会在 60 秒内自动拉起"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


class ExportReq(BaseModel):
    paths: List[str] = []
    fmt: str = "zip"


@app.post("/api/export")
def api_export(req: ExportReq):
    import zipfile
    if not req.paths:
        raise HTTPException(400, "没有选图")
    out_dir = os.path.join(ROOT, "SD-Picture", "exports")
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(out_dir, "export_%s.zip" % ts)
    rp = store.load_recipes()
    lines = []
    n = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in req.paths:
            if not os.path.isfile(p):
                continue
            z.write(p, os.path.basename(p))
            n += 1
            r = rp.get(p)
            if r:
                z.writestr(os.path.splitext(os.path.basename(p))[0] + ".recipe.json",
                           json.dumps(r, ensure_ascii=False, indent=2))
                lines.append("### " + os.path.basename(p))
                lines.append("seed=%s steps=%s cfg=%s size=%s" % (r.get("seed"), r.get("steps"),
                                                                  r.get("cfg"), r.get("size")))
                lines.append("loras: " + ", ".join("%s x%s" % (l.get("name"), l.get("weight"))
                                                   for l in (r.get("loras") or [])))
                lines.append("POS: " + (r.get("positive") or "")[:2000])
                lines.append("NEG: " + (r.get("negative") or "")[:1200])
                lines.append("")
        z.writestr("prompts.txt", "\n".join(lines))
        z.writestr("README.txt", "导出时间 %s\n共 %d 张图，配方见 *.recipe.json 与 prompts.txt\n" % (ts, n))
    return {"ok": True, "zip": zip_path, "count": n, "url": "/api/download?path=" + urllib.parse.quote(zip_path)}


@app.get("/api/download")
def api_download(path: str):
    if not os.path.isfile(path):
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, filename=os.path.basename(path))


# ---------------- bootstrap ----------------
ARTIST_RECIPES_PATH = os.path.join(ROOT, "ref", "artist_recipes.json")


def _load_artist_recipes():
    try:
        with open(ARTIST_RECIPES_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


@app.get("/api/artist_recipes")
def api_artist_recipes():
    return {"items": _load_artist_recipes()}


class ArtistRecipeReq(BaseModel):
    name: str
    weight: Optional[float] = None
    byChar: Dict[str, float] = {}
    note: str = ""


@app.post("/api/artist_recipe")
def api_artist_recipe(req: ArtistRecipeReq):
    items = _load_artist_recipes()
    key = req.name
    cur = items.get(key, {})
    if req.weight is not None:
        cur["weight"] = round(float(req.weight), 3)
    if req.byChar:
        cur.setdefault("byChar", {}).update({k: round(float(v), 3) for k, v in req.byChar.items()})
    if req.note:
        cur["note"] = req.note
    items[key] = cur
    os.makedirs(os.path.dirname(ARTIST_RECIPES_PATH), exist_ok=True)
    with open(ARTIST_RECIPES_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    return {"ok": True, "items": items}




FREE_INDEX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ref", "artist_free_index.json")
REF_INDEX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "产出作品", "画师参考", "_index.json")


@app.get("/api/artist_preview")
def api_artist_preview(name: str = ""):
    """画师悬停预览：自由发挥样张 + 权重建议。"""
    idx = {}
    try:
        with open(FREE_INDEX, encoding="utf-8") as f:
            idx = json.load(f)
    except Exception:
        idx = {}
    entry = idx.get(name) or {}
    items = []
    for k in sorted(entry, key=lambda x: float(x)):
        path = entry[k]
        if path and os.path.isfile(path):
            items.append({"weight": float(k), "path": path})
    advice = [
        {"weight": 0.6, "text": "轻：只借笔触，构图/角色更自由，适合日常与场景"},
        {"weight": 1.0, "text": "标准：风格与角色平衡，最稳"},
        {"weight": 1.3, "text": "重：风格压过一切，可能吞细节/偏色"},
    ]
    ref = ""
    try:
        with open(REF_INDEX, encoding="utf-8") as f:
            ridx = json.load(f)
        ref = ridx.get(name) or ""
    except Exception:
        ref = ""
    return {"name": name, "ref": ref, "items": items, "advice": advice}


@app.get("/api/status")
def api_status():
    """轻量状态，给前端轮询用（bootstrap 约 180KB）。"""
    st = cf.system_stats()
    if not st.get("up"):
        time.sleep(0.4)
        st = cf.system_stats()
    q = cf.queue_state() if st.get("up") else {"running": 0, "pending": 0}
    return {"comfy": {"up": bool(st.get("up")), "version": st.get("version"), "url": cf.COMFY},
            "queue": {"running": q.get("running", 0), "pending": q.get("pending", 0)}}


@app.get("/api/bootstrap")
def bootstrap():
    tokens, lib, ch = load_tokens()
    # 服装派生的 @OUT_*/@NEG_* 也用服装页里的注释，让悬停有内容
    notes = dict(lib.get("notes") or {})
    for key, g in (ch.get("garments") or {}).items():
        meta = g.get("label") or key
        notes.setdefault("@OUT_" + key.upper(),
                         (g.get("note") or "").strip() or (meta + "：这套服装的正向提示词，服装页里可编辑。"))
        neg = (g.get("negative") or "").strip()
        neg_txt = ("：" + neg[:60] + ("…" if len(neg) > 60 else "")) if neg else "。"
        notes.setdefault("@NEG_" + key.upper(),
                         meta + " 的配套负向" + neg_txt + "（服装页可改）")
    notes.setdefault("@OUTFIT_A", "默认套装上半段（拆分版，便于单独调权重）")
    notes.setdefault("@OUTFIT_B", "默认套装下半段（拆分版）")
    notes.setdefault("@NEG_BASE_A", "基础负向上半段：画质与结构")
    notes.setdefault("@NEG_BASE_B", "基础负向下半段：伪影与文字")
    notes.setdefault("@OUTFIT", "当前默认套装的正向（由服装页 garment_default 决定）")
    notes.setdefault("@NEG_GARMENT", "当前默认套装的配套负向")
    return {
        "tokens": tokens,
        "notes": notes,
        "token_meta": lib.get("meta", {}),
        "garments": ch.get("garments", {}),
        "character": {k: v for k, v in ch.items() if k != "garments"},
        "comfy": dict(cf.system_stats(), url=cf.COMFY),
        "queue": cf.queue_state(),
        "datasets": list_datasets(),
        "loras": list_loras(),
        "models": list_models(),
        "defaults": {
            "width": 1024, "height": 1536, "steps": 30, "cfg": 5.5,
            "loras": [
                {"name": "sunhimi_h2.safetensors", "weight": 0.5},
                {"name": "animaNai5E585B6E4B889.YDAV.safetensors", "weight": 0.66},
            ],
        },
        "paths": {"root": ROOT, "ref": REF, "out": OUT_DIR},
    }


@app.post("/api/expand")
def api_expand(req: ExpandReq):
    tokens, _, _ = load_tokens()
    strips = [b.token for b in (list(req.positive) + list(req.negative)) if (b.token or "") in getattr(pt, "STRIP_KEYS", set())]

    def render(blocks):
        parts, used = [], []
        for b in blocks:
            if not b.enabled:
                continue
            raw = b.text or b.token
            if not raw:
                continue
            if (b.token or "") in getattr(pt, "STRIP_KEYS", set()):
                strips.append(b.token)
                continue
            ex, u = expand(raw, tokens)
            used.extend(u)
            ex = ex.strip().strip(",")
            if b.weight and abs(b.weight - 1.0) > 0.001:
                ex = "(%s:%s)" % (ex, b.weight)
            parts.append(ex)
        text = ", ".join([p for p in parts if p])
        return text, sorted(set(used))

    pos, pos_used = render(req.positive)
    if getattr(pt, "STRIP_KEYS", None) and strips:
        pos, _strip_hits = pt.apply_strips(pos, " ".join(strips))

    # ---- 冲突让路：正向要杯子 / 拿东西时，负向自动撤掉对应禁令 ----
    raw_pos = " ".join([(b.token or "") + " " + (b.text or "") for b in req.positive if b.enabled]).lower()
    cup_wanted = ("@hold_r_cup" in raw_pos or "@hold_l_cup" in raw_pos
                  or ("holding" in raw_pos and "cup" in raw_pos))
    drinkware = ["cup", "mug", "teacup", "coffee cup", "saucer", "drinking glass",
                 "wine glass", "glass", "bottle", "holding a drink"]
    neg_blocks = []
    notes = []
    for b in req.negative:
        if not b.enabled:
            continue
        if cup_wanted and (b.token or "").upper() in ("@NEG_CUP", "@NEG_PROPS"):
            notes.append("已让路：负向移除了 " + (b.token or "杯子禁令") + "（你的正向要了杯子）")
            continue
        neg_blocks.append(b)
    neg, neg_used = render(neg_blocks)
    if cup_wanted:
        for w in drinkware:
            neg = re.sub(r"(?i)(,\s*)?\b" + re.escape(w) + r"\b", "", neg)
        neg = re.sub(r"\s*,\s*(?=,)", "", neg).strip().strip(",").strip()
        if not notes:
            notes.append("已让路：负向清掉了杯子相关词（正向要杯子）")
    return {"positive": pos, "negative": neg, "used": pos_used + neg_used,
            "pos_len": len(pos), "neg_len": len(neg), "notes": notes}


def _prepare_reference(path):
    """把底图拷进 ComfyUI/input，返回文件名。"""
    src = path
    if not os.path.isabs(src):
        cand = os.path.join(ROOT, "comfy", "ComfyUI", "input", src)
        src = cand if os.path.exists(cand) else src
    if not os.path.isfile(src):
        raise HTTPException(400, "找不到底图: " + path)
    inp = os.path.join(ROOT, "comfy", "ComfyUI", "input")
    os.makedirs(inp, exist_ok=True)
    base = "ref_" + re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(src))
    dst = os.path.join(inp, base)
    if not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
        shutil.copy2(src, dst)
    return base


def _normalize_mask(path, feather=0):
    """把蒙版统一成「白=重绘」的二值图（取红通道，兼容画笔的红笔迹与矩形白块）。
    feather>0 时对二值图做高斯羽化。写回原文件（RGB 三通道一致）。"""
    from PIL import Image, ImageFilter
    im = Image.open(path)
    if im.mode == "RGBA":
        bg = Image.new("RGBA", im.size, (0, 0, 0, 255))
        im = Image.alpha_composite(bg, im)
    m = im.convert("RGB").getchannel("R")
    m = m.point(lambda v: 255 if v >= 24 else 0)
    if feather and feather > 0:
        m = m.filter(ImageFilter.GaussianBlur(radius=feather / 2.0))
    Image.merge("RGB", (m, m, m)).save(path)
    return path


def _make_mask(image_path, box, out_name=None):
    """用矩形框生成黑底白块蒙版，写进 ComfyUI/input。"""
    from PIL import Image, ImageDraw
    im = Image.open(image_path)
    w, h = im.size
    parts = [int(float(x.strip())) for x in box.replace("，", ",").split(",")]
    if len(parts) != 4:
        raise HTTPException(400, "box 需要 x,y,w,h")
    x, y, bw, bh = parts
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.rectangle([max(0, x), max(0, y), min(w - 1, x + bw), min(h - 1, y + bh)], fill=255)
    inp = os.path.join(ROOT, "comfy", "ComfyUI", "input")
    name = out_name or ("mask_" + time.strftime("%H%M%S") + ".png")
    mask.save(os.path.join(inp, name))
    return name



RECIPE_PATH = os.path.join(HERE, "data", "recipes.json")


def add_recipe(path, data):
    """把一张图的配方记下来（按路径索引，最多 400 条）。"""
    if not path:
        return
    try:
        db = store.load_recipes()
        db[path] = data
        if len(db) > 400:
            for k in sorted(db, key=lambda x: db[x].get("ts", 0))[:len(db) - 400]:
                db.pop(k, None)
        store.save_recipes(db)
    except Exception:
        pass



class RecipeInferReq(BaseModel):
    path: str
    blocks_pos: List[Dict[str, Any]] = []
    blocks_neg: List[Dict[str, Any]] = []
    prompt: str = ""
    negative: str = ""
    loras: List[Dict[str, Any]] = []
    steps: int = 30
    cfg: float = 5.5


@app.post("/api/recipe/infer")
def api_recipe_infer(req: RecipeInferReq):
    """给旧图补一份「推断配方」：种子取自文件名，尺寸取自图片，其余用调用方给的。"""
    if not os.path.isfile(req.path):
        raise HTTPException(404, "图片不存在")
    try:
        from PIL import Image
        with Image.open(req.path) as im:
            w, h = im.size
    except Exception:
        w, h = 1024, 1536
    m = re.search(r"_s(\d+)", os.path.basename(req.path))
    seed = int(m.group(1)) if m else 0
    db = store.load_recipes()
    db[req.path] = {
        "ts": os.path.getmtime(req.path),
        "mode": "t2i",
        "workflow": "anima_t2i",
        "positive": req.prompt,
        "negative": req.negative or (db.get(req.path) or {}).get("negative", ""),
        "blocks_pos": req.blocks_pos,
        "blocks_neg": req.blocks_neg,
        "size": [w, h],
        "steps": req.steps,
        "cfg": req.cfg,
        "seed": seed,
        "denoise": 1.0,
        "loras": req.loras,
        "reference": "",
        "mask": "",
        "inferred": True,
        "source_template": "当前积木推断",
        "note": "种子取自文件名，尺寸取自图片，其余为当前积木/参数。",
    }
    store.save_recipes(db)
    return {"ok": True, "seed": seed, "size": [w, h]}



def _match_blocks(text, tokens):
    """把展开后的提示词按「积木原文」从长到短匹配回去，得到近似积木列表。"""
    blocks, rest = [], text or ""
    for tok, txt in sorted(tokens.items(), key=lambda kv: -len(kv[1] or "")):
        frag = (txt or "")[:60]
        if not frag or frag not in rest:
            continue
        rest = rest.replace(frag, "\u0000", 1)
        blocks.append({"token": tok, "weight": 1, "enabled": True})
    return blocks


def _parse_png_recipe(path):
    """从 ComfyUI 写进 PNG 的 prompt JSON 里还原配方。"""
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        with Image.open(path) as im:
            raw = im.info.get("prompt")
            size = list(im.size)
    except Exception:
        return None
    if not raw:
        return None
    try:
        g = json.loads(raw)
    except Exception:
        return None
    texts, loras = [], []
    sampler, latent, ref = None, None, ""
    enc_pos, enc_neg = "", ""   # KSampler 里真正接的是哪两个 CLIPTextEncode
    for n in g.values():
        ct = n.get("class_type")
        if ct == "CLIPTextEncode":
            texts.append(n.get("inputs", {}).get("text", ""))
        elif ct in ("KSampler", "KSamplerAdvanced"):
            sampler = n.get("inputs") or {}

            def _enc(link):
                if isinstance(link, list) and link:
                    node = g.get(str(link[0]))
                    if node and node.get("class_type") == "CLIPTextEncode":
                        return node.get("inputs", {}).get("text", "") or ""
                return ""

            enc_pos = _enc(sampler.get("positive"))
            enc_neg = _enc(sampler.get("negative"))
        elif ct == "EmptyLatentImage":
            latent = n.get("inputs") or {}
        elif ct == "LoraLoaderModelOnly":
            loras.append({"name": n["inputs"].get("lora_name"),
                          "weight": n["inputs"].get("strength_model")})
        elif ct == "LoadImage":
            ref = n.get("inputs", {}).get("image", "")
    if enc_pos or enc_neg:
        pos, neg = enc_pos, enc_neg
    else:
        # 老图兜底：按内容猜（以前的逻辑，容易把不带 1girl 的正向误判成负向）
        pos = next((t for t in texts if "1girl" in t or ", solo" in t or t.strip().startswith("(1girl")), "")
        neg = next((t for t in texts if t is not pos), "")
    tokens, _, _ = load_tokens()
    blocks = _match_blocks(pos, tokens)
    blocks_neg = _match_blocks(neg, tokens)
    mode = "inpaint" if any(n.get("class_type") == "SetLatentNoiseMask" for n in g.values()) else (
        "i2i" if ref else "t2i")
    return {
        "positive": pos, "negative": neg,
        "blocks_pos": blocks, "blocks_neg": blocks_neg, "blocks_guess": True,
        "size": [latent.get("width", size[0]), latent.get("height", size[1])] if latent else size,
        "steps": sampler.get("steps") if sampler else None,
        "cfg": sampler.get("cfg") if sampler else None,
        "seed": sampler.get("seed") if sampler else None,
        "denoise": sampler.get("denoise") if sampler else None,
        "loras": loras, "reference": ref, "mode": mode,
    }


class RecipeFromImageReq(BaseModel):
    path: str


@app.post("/api/recipe/from-image")
def api_recipe_from_image(req: RecipeFromImageReq):
    if not os.path.isfile(req.path):
        raise HTTPException(404, "图片不存在")
    r = _parse_png_recipe(req.path)
    if not r:
        raise HTTPException(400, "这张图里没有 ComfyUI 元数据")
    r.update({"ts": os.path.getmtime(req.path), "workflow": "png_metadata",
              "exact": True, "inferred": False, "source_template": "PNG 元数据"})
    db = store.load_recipes()
    db[req.path] = r
    store.save_recipes(db)
    return {"ok": True, "recipe": r}


@app.post("/api/recipe/backfill")
def api_recipe_backfill():
    db = store.load_recipes()
    n = 0
    skipped = 0
    for d in ("station_out", "harvest", "remote_out"):
        folder = os.path.join(ROOT, "SD-Picture", d)
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if not name.lower().endswith(".png"):
                continue
            path = os.path.join(folder, name)
            if path in db and db[path].get("exact"):
                skipped += 1
                continue
            r = _parse_png_recipe(path)
            if not r:
                skipped += 1
                continue
            r.update({"ts": os.path.getmtime(path), "workflow": "png_metadata",
                      "exact": True, "inferred": False, "source_template": "PNG 元数据"})
            db[path] = r
            n += 1
    store.save_recipes(db)
    return {"ok": True, "recovered": n, "skipped": skipped, "total": len(db)}



MASK_DIR = os.path.join(ROOT, "SD-Picture", "masks")


class MaskSaveReq(BaseModel):
    image: str
    mask_b64: str
    name: str = ""


@app.post("/api/mask/save")
def api_mask_save(req: MaskSaveReq):
    if not req.mask_b64:
        raise HTTPException(400, "蒙版为空")
    os.makedirs(MASK_DIR, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_-]", "", os.path.splitext(os.path.basename(req.image))[0])[:40] or "mask"
    tag = re.sub(r"[^A-Za-z0-9_-]", "", req.name or "")[:20]
    fname = "%s_%s%s.png" % (stem, tag or time.strftime("%H%M%S"), "")
    path = os.path.join(MASK_DIR, fname)
    raw = req.mask_b64.split(",", 1)[-1]
    try:
        data = base64.b64decode(raw)
    except Exception:
        raise HTTPException(400, "蒙版解码失败")
    # 存成「透明底 + 红笔迹」的 RGBA：套回画布时不会把底图盖黑，也能再次导出
    try:
        from PIL import Image
        src = Image.open(io.BytesIO(data))
        if src.mode == "RGBA":
            src = Image.alpha_composite(Image.new("RGBA", src.size, (0, 0, 0, 255)), src)
        m = src.convert("RGB").getchannel("R").point(lambda v: 255 if v >= 24 else 0)
        rgba = Image.new("RGBA", src.size, (0, 0, 0, 0))
        rgba.paste((255, 45, 85, 255), mask=m)
        rgba.save(path)
    except Exception:
        with open(path, "wb") as f:
            f.write(data)
    return {"ok": True, "path": path, "name": fname}


@app.get("/api/mask/list")
def api_mask_list(image: str = "", limit: int = 40):
    os.makedirs(MASK_DIR, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_-]", "", os.path.splitext(os.path.basename(image))[0])[:40] if image else ""
    items = []
    for n in os.listdir(MASK_DIR):
        if not n.lower().endswith(".png"):
            continue
        if stem and not n.startswith(stem):
            continue
        p = os.path.join(MASK_DIR, n)
        items.append({"name": n, "path": p, "ts": os.path.getmtime(p),
                      "size": os.path.getsize(p)})
    items.sort(key=lambda x: -x["ts"])
    return {"items": items[:limit], "total": len(items)}


@app.get("/api/recipe")
def api_recipe(path: str):
    db = store.load_recipes()
    r = db.get(path)
    if not r:
        raise HTTPException(404, "这张图没有配方记录")
    r = dict(r)
    # 老记录没存积木：从 PNG 里的 ComfyUI 元数据补回来（标注为近似）
    if not r.get("blocks_pos") or not r.get("blocks_neg"):
        pr = _parse_png_recipe(path) if os.path.isfile(path) else None
        if pr:
            if not r.get("blocks_pos") and pr.get("blocks_pos"):
                r["blocks_pos"] = pr["blocks_pos"]
                r["blocks_guess"] = True
            if not r.get("blocks_neg") and pr.get("blocks_neg"):
                r["blocks_neg"] = pr["blocks_neg"]
                r["blocks_guess"] = True
            if r.get("blocks_guess"):
                db[path] = dict(r)
                db[path].pop("path", None)
                store.save_recipes(db)
    r["path"] = path
    return r


@app.get("/api/recipes/export")
def api_recipes_export():
    """把数据库里的配方导回 JSON（备份/迁移用）。"""
    return JSONResponse(store.load_recipes())


@app.get("/api/recipes")
def api_recipes(limit: int = 60):
    db = store.load_recipes()
    items = []
    for path, r in db.items():
        if not os.path.isfile(path):
            continue
        items.append({"path": path, "name": os.path.basename(path),
                      "ts": r.get("ts", 0), "mode": r.get("mode", ""),
                      "lora_n": len(r.get("loras") or [])})
    items.sort(key=lambda x: -x["ts"])
    return {"total": len(items), "items": items[:limit]}


def _node_class(node):
    return (node or {}).get("class_type") or (node or {}).get("type") or ""


def _submit(mode, params, jid, label, wf_name=None):
    """编译图 -> 提交 -> 轮询 -> 落盘。"""
    if not cf.system_stats()["up"]:
        JOBS[jid].update(status="error", result={"error": "ComfyUI 未启动"})
        return
    if wf_name is None:
        wf_name = {"t2i": "anima_t2i", "i2i": "anima_i2i", "inpaint": "anima_inpaint"}[mode]
    try:
        wf, meta = gf.build(wf_name, params)
    except Exception as e:
        JOBS[jid].update(status="error", result={"error": "编译工作流失败: %s" % e})
        job_log(jid, "COMPILE ERROR " + str(e)[:200])
        return
    _model = (params.get("model") or "").strip()
    if _model:
        for _n in wf.values():
            if _node_class(_n) == "UNETLoader":
                _n.setdefault("inputs", {})["unet_name"] = _model
    if meta["missing"]:
        msg = "ComfyUI 缺少节点: " + ", ".join(meta["missing"])
        JOBS[jid].update(status="error", result={"error": msg, "missing": meta["missing"]})
        job_log(jid, msg)
        return
    try:
        LAST_GRAPH.clear()
        LAST_GRAPH.update({"__workflow": meta["workflow"], "nodes": wf})
        pid = gf.submit(wf)
        job_log(jid, "queued %s (workflow=%s, denoise=%.2f)" % (pid, meta["workflow"], meta["denoise"]))
        expect = estimate_seconds(params.get("width", 1024), params.get("height", 1536), params.get("steps", 30), model=params.get("model") or "")
        t0 = time.time()

        def tick(elapsed):
            _pg = cf.progress_of(pid) if hasattr(cf, "progress_of") else None
            if _pg and _pg[1]:
                JOBS[jid]["progress"] = min(0.99, 0.03 + 0.95 * (_pg[0] / _pg[1]))
            else:
                JOBS[jid]["progress"] = min(0.99, elapsed / max(8.0, expect))

        res = cf.wait(pid, timeout=1800, on_tick=tick)
        if not res["ok"]:
            JOBS[jid].update(status="error", result={"error": res.get("error", "")})
            job_log(jid, "ERROR " + str(res.get("error", ""))[:300])
            return
        saved = []
        for im in res["images"]:
            src_path = os.path.join(COMFY_OUT, im.get("subfolder", ""), im["filename"])
            dst_dir = OUT_DIR if params.get("save_to", "station_out") == "station_out" else os.path.join(ROOT, "SD-Picture", params.get("save_to"))
            os.makedirs(dst_dir, exist_ok=True)
            stamp = time.strftime("%H%M%S")
            dst = os.path.join(dst_dir, "%s_%s_s%d.png" % (label, stamp, params.get("seed", 0)))
            if os.path.exists(src_path):
                shutil.copy2(src_path, dst)
                saved.append(dst)
                add_recipe(dst, {
                    "ts": time.time(),
                    "mode": mode,
                    "workflow": meta.get("workflow"),
                    "positive": params.get("prompt", ""),
                    "negative": params.get("negative", ""),
                    "blocks_pos": params.get("blocks_pos") or [],
                    "blocks_neg": params.get("blocks_neg") or [],
                    "size": [params.get("width"), params.get("height")],
                    "steps": params.get("steps"),
                    "cfg": params.get("cfg"),
                    "seed": params.get("seed"),
                    "denoise": params.get("denoise"),
                    "loras": params.get("loras") or [],
                    "model": params.get("model") or "",
                    "reference": params.get("reference", ""),
                    "mask": params.get("mask", ""),
                })
            job_log(jid, "saved " + os.path.basename(dst))
        score = mirror_score(saved[0]) if saved else 0.0
        JOBS[jid].update(status="done", progress=1.0,
                         result={"images": saved, "seed": params.get("seed"), "workflow": meta["workflow"],
                                 "denoise": meta["denoise"], "elapsed": round(time.time() - t0, 1),
                                 "mirror": score, "split_suspect": score >= 0.86})
    except Exception as e:
        JOBS[jid].update(status="error", result={"error": str(e)})
        job_log(jid, "EXC " + str(e)[:300])


@app.post("/api/run")
def api_run(req: RunReq):
    if not req.prompt.strip():
        raise HTTPException(400, "empty prompt")
    prefix = re.sub(r"[^A-Za-z0-9_\-]", "_", req.prefix or "station")[:40]
    seed = req.seed or int(time.time()) % 1000000
    jid = job_new("run", prefix)
    params = {"prompt": req.prompt, "negative": req.negative, "width": req.width, "height": req.height,
              "steps": req.steps, "cfg": req.cfg, "seed": seed, "prefix": prefix,
              "loras": req.loras, "save_to": req.save_to, "denoise": req.denoise,
              "blocks_pos": req.blocks_pos, "blocks_neg": req.blocks_neg, "model": req.model}
    if req.mode in ("i2i", "inpaint"):
        params["reference"] = _prepare_reference(req.reference)
    if req.mode == "inpaint":
        params["mask"] = req.mask or _make_mask(os.path.join(ROOT, "comfy", "ComfyUI", "input", params["reference"]), "0,0,10,10")
    threading.Thread(target=lambda: _submit(req.mode, params, jid, prefix), daemon=True).start()
    return {"job_id": jid, "seed": seed, "estimate": estimate_seconds(req.width, req.height, req.steps, model=req.model),
            "mode": req.mode}



class InpaintReq(BaseModel):
    image: str
    box: str = ""
    mask_b64: str = ""
    mask_feather: int = 0
    prompt: str = ""
    negative: str = ""
    denoise: float = 0.6
    steps: int = 26
    cfg: float = 5.2
    seed: int = 0
    prefix: str = "repaint"
    engine: str = "anima"
    loras: List[Dict[str, Any]] = []


@app.post("/api/inpaint")
def api_inpaint(req: InpaintReq):
    """通用局部重绘：框内按给的提示词重画，框外不动。"""
    if not req.box and not req.mask_b64:
        raise HTTPException(400, "需要 box 或 mask_b64")
    if not os.path.isfile(req.image):
        raise HTTPException(400, "底图不存在")
    ref_name = _prepare_reference(req.image)
    ref_path = os.path.join(ROOT, "comfy", "ComfyUI", "input", ref_name)
    if req.mask_b64:
        # 画笔蒙版：dataURL -> PNG -> ComfyUI input
        raw = req.mask_b64.split(",", 1)[-1]
        try:
            data = base64.b64decode(raw)
        except Exception:
            raise HTTPException(400, "蒙版解码失败")
        mask_name = "mask_br_%s.png" % time.strftime("%H%M%S")
        with open(os.path.join(ROOT, "comfy", "ComfyUI", "input", mask_name), "wb") as f:
            f.write(data)
    else:
        mask_name = _make_mask(ref_path, req.box)
    # 二值化 + 羽化：画笔是红笔迹、框选是白块，统一取红通道
    try:
        _normalize_mask(os.path.join(ROOT, "comfy", "ComfyUI", "input", mask_name),
                        req.mask_feather or 0)
    except Exception as e:
        print("[mask-normalize] failed:", e, flush=True)
    prompt = req.prompt or ("sunhimi, (same character:1.3), (same art style:1.25), (detailed:1.15)")
    negative = req.negative or "extra fingers, deformed hands, bad anatomy, watermark, text, lowres"
    seed = req.seed or int(time.time()) % 1000000
    wf_name = "anima_inpaint"   # SDXL 管线已下线（2026-10-29）
    jid = job_new("repaint", req.prefix)
    params = {"prompt": prompt, "negative": negative,
              "width": 1024, "height": 1536, "steps": req.steps, "cfg": req.cfg, "seed": seed,
              "prefix": req.prefix, "loras": req.loras, "denoise": req.denoise,
              "reference": ref_name, "mask": mask_name, "save_to": "station_out"}
    threading.Thread(target=lambda: _submit("inpaint", params, jid, req.prefix, wf_name=wf_name),
                     daemon=True).start()
    return {"job_id": jid, "seed": seed, "mask": mask_name, "denoise": req.denoise,
            "engine": "anima", "workflow": wf_name, "box": req.box,
            "feather": req.mask_feather}


@app.post("/api/handfix")
def api_handfix(req: MaskReq):
    if not req.box:
        raise HTTPException(400, "需要 box")
    ref_name = _prepare_reference(req.image)
    ref_path = os.path.join(ROOT, "comfy", "ComfyUI", "input", ref_name)
    mask_name = _make_mask(ref_path, req.box)
    prompt = req.prompt or ("sunhimi, (detailed hand:1.3), (natural fingers:1.3), "
                            "(correct anatomy:1.25), smooth shading, same art style")
    negative = req.negative or ("extra fingers, fused fingers, missing fingers, deformed hands, "
                                "bad anatomy, watermark, text, lowres")
    seed = req.seed or int(time.time()) % 1000000
    wf_name = "anima_inpaint"   # SDXL 管线已下线（2026-10-29）
    jid = job_new("handfix", req.prefix)
    params = {"prompt": prompt, "negative": negative,
              "width": 1024, "height": 1536, "steps": req.steps, "cfg": req.cfg, "seed": seed,
              "prefix": req.prefix, "loras": req.loras, "denoise": req.denoise,
              "reference": ref_name, "mask": mask_name, "save_to": "station_out"}
    threading.Thread(target=lambda: _submit("inpaint", params, jid, req.prefix, wf_name=wf_name),
                     daemon=True).start()
    return {"job_id": jid, "seed": seed, "mask": mask_name, "denoise": req.denoise, "engine": "anima", "workflow": wf_name}


@app.post("/api/reproduce")
def api_reproduce(req: ReproReq):
    """复现模式：keep_person=保人物换画面；keep_image=保画面换人物。"""
    ref_name = _prepare_reference(req.reference)
    seed = req.seed or int(time.time()) % 1000000
    loras = req.loras
    if req.mode == "keep_image" and loras:
        loras = [{"name": x["name"], "weight": min(0.85, float(x.get("weight", 0.5)) + 0.1)} for x in loras]
    jid = job_new("repro_" + req.mode, req.prefix)
    params = {"prompt": req.prompt, "negative": req.negative, "width": req.width, "height": req.height,
              "steps": req.steps, "cfg": req.cfg, "seed": seed, "prefix": req.prefix,
              "loras": loras, "denoise": req.denoise, "reference": ref_name, "save_to": "station_out"}
    threading.Thread(target=lambda: _submit("i2i", params, jid, req.prefix), daemon=True).start()
    return {"job_id": jid, "seed": seed, "mode": req.mode, "denoise": req.denoise}




def _save_result(im, label, seed):
    """把 ComfyUI 输出图片复制到站点的 station_out，返回本地路径。"""
    src_path = os.path.join(COMFY_OUT, im.get("subfolder", ""), im["filename"])
    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = time.strftime("%H%M%S")
    dst = os.path.join(OUT_DIR, "%s_%s_s%d.png" % (label, stamp, seed))
    if os.path.exists(src_path):
        if os.path.exists(dst):
            dst = os.path.join(OUT_DIR, "%s_%s_s%d_%s.png" % (label, stamp, seed, str(int(time.time() % 1000))))
        shutil.copy2(src_path, dst)
        return dst
    return ""


class BatchReq(BaseModel):
    blocks_pos: List[Dict[str, Any]] = []
    blocks_neg: List[Dict[str, Any]] = []
    prompt: str
    negative: str = ""
    width: int = 1024
    height: int = 1536
    steps: int = 30
    cfg: float = 5.5
    count: int = 4
    seed_start: int = 0
    seed_step: int = 1
    prefix: str = "batch"
    loras: List[Dict[str, Any]] = []
    mode: str = "t2i"
    reference: str = ""


@app.post("/api/batch")
def api_batch(req: BatchReq):
    if not req.prompt.strip():
        raise HTTPException(400, "empty prompt")
    count = max(1, min(12, req.count))
    seeds = [ (req.seed_start or int(time.time()) % 1000000) + i * max(1, req.seed_step) for i in range(count) ]
    jid = job_new("batch", req.prefix)
    JOBS[jid]["items"] = [{"seed": s, "status": "pending", "image": ""} for s in seeds]

    def work():
        done = 0
        for idx, seed in enumerate(seeds):
            try:
                params = {"prompt": req.prompt, "negative": req.negative, "width": req.width,
                          "height": req.height, "steps": req.steps, "cfg": req.cfg, "seed": seed,
                          "prefix": "%s_%02d" % (req.prefix, idx + 1), "loras": req.loras,
                          "denoise": 1.0,
                          "blocks_pos": req.blocks_pos, "blocks_neg": req.blocks_neg}
                if req.mode == "i2i":
                    params["reference"] = _prepare_reference(req.reference)
                wf, meta = gf.build("anima_i2i" if req.mode == "i2i" else "anima_t2i", params)
                if meta["missing"]:
                    raise RuntimeError("缺节点: " + ", ".join(meta["missing"]))
                pid = gf.submit(wf)
                res = cf.wait(pid, timeout=1800)
                if not res["ok"]:
                    raise RuntimeError(str(res.get("error")))
                saved = [_save_result(im, params["prefix"], seed) for im in res["images"]]
                saved = [x for x in saved if x]
                JOBS[jid]["items"][idx].update(status="done", image=saved[0] if saved else "")
                job_log(jid, "done %d/%d seed=%d" % (idx + 1, count, seed))
            except Exception as e:
                JOBS[jid]["items"][idx].update(status="error", error=str(e)[:200])
                job_log(jid, "ERR %d: %s" % (idx + 1, str(e)[:160]))
            done += 1
            JOBS[jid]["progress"] = done / float(count)
        JOBS[jid].update(status="done", result={"items": JOBS[jid]["items"]})

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid, "count": count, "seeds": seeds}



TRASH_DIR = os.path.join(ROOT, "SD-Picture", "_trash")
DELETE_ROOTS = [os.path.join(ROOT, "SD-Picture"), COMFY_OUT]


class DeleteReq(BaseModel):
    path: str
    permanent: bool = False


@app.post("/api/delete-image")
def api_delete_image(req: DeleteReq):
    path = os.path.abspath(req.path)
    if not os.path.isfile(path):
        raise HTTPException(404, "文件不存在")
    if not any(os.path.commonpath([path, os.path.abspath(r)]) == os.path.abspath(r) for r in DELETE_ROOTS):
        raise HTTPException(403, "只允许删除 SD-Picture 或 ComfyUI output 下的文件")
    if req.permanent:
        os.remove(path)
        return {"ok": True, "mode": "deleted", "path": path}
    day = time.strftime("%Y%m%d")
    dst_dir = os.path.join(TRASH_DIR, day)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(path))
    if os.path.exists(dst):
        dst = os.path.join(dst_dir, "%s_%s%s" % (os.path.splitext(os.path.basename(path))[0],
                                                 time.strftime("%H%M%S"), os.path.splitext(path)[1]))
    shutil.move(path, dst)
    try:
        with open(dst + ".json", "w", encoding="utf-8") as f:
            json.dump({"orig": path, "at": time.time()}, f, ensure_ascii=False)
    except Exception:
        pass
    return {"ok": True, "mode": "trash", "path": path, "trash": dst}




class RestoreReq(BaseModel):
    path: str


def _restore_file(p):
    meta = p + ".json"
    orig = None
    if os.path.isfile(meta):
        try:
            orig = json.load(open(meta, encoding="utf-8")).get("orig")
        except Exception:
            orig = None
    if not orig:
        orig = os.path.join(ROOT, "SD-Picture", "harvest", os.path.basename(p))
    os.makedirs(os.path.dirname(orig), exist_ok=True)
    if os.path.exists(orig):
        base, ext = os.path.splitext(orig)
        orig = base + "_restored" + time.strftime("%H%M%S") + ext
    shutil.move(p, orig)
    try:
        os.remove(meta)
    except Exception:
        pass
    return orig


@app.post("/api/trash/restore")
def api_trash_restore(req: RestoreReq):
    if not os.path.isfile(req.path):
        raise HTTPException(404, "回收站里没有这个文件")
    if os.path.commonpath([os.path.abspath(req.path), TRASH_DIR]) != os.path.abspath(TRASH_DIR):
        raise HTTPException(403, "只能恢复回收站里的文件")
    dst = _restore_file(req.path)
    return {"ok": True, "restored": dst}


@app.post("/api/trash/restore-all")
def api_trash_restore_all():
    done = []
    if os.path.isdir(TRASH_DIR):
        for dp, _, fs in os.walk(TRASH_DIR):
            for f in fs:
                if f.endswith(".json"):
                    continue
                try:
                    done.append(_restore_file(os.path.join(dp, f)))
                except Exception:
                    pass
    return {"ok": True, "count": len(done), "restored": done[:50]}


@app.post("/api/trash/purge")
def api_trash_purge():
    n = 0
    if os.path.isdir(TRASH_DIR):
        for dp, _, fs in os.walk(TRASH_DIR):
            for f in fs:
                try:
                    os.remove(os.path.join(dp, f))
                    n += 1
                except Exception:
                    pass
        for dp, ds, _ in os.walk(TRASH_DIR, topdown=False):
            for d in ds:
                try:
                    os.rmdir(os.path.join(dp, d))
                except Exception:
                    pass
    return {"ok": True, "removed": n}


@app.get("/api/trash")
def api_trash():
    items = []
    if os.path.isdir(TRASH_DIR):
        for dp, _, fs in os.walk(TRASH_DIR):
            for f in fs:
                p = os.path.join(dp, f)
                items.append({"path": p, "name": f, "size": os.path.getsize(p)})
    total = sum(x["size"] for x in items)
    return {"count": len(items), "mb": round(total / 1048576, 1), "items": items[:200]}


@app.post("/api/validate")
def api_validate(req: ValidateReq):
    return irv.validate([b.dict() for b in req.positive], [b.dict() for b in req.negative])



def _face_center(img):
    """用红眼定位脸：上半幅里最大的红色斑块。"""
    import numpy as np
    h, w = img.shape[:2]
    b, g, r = img[:, :, 0].astype(int), img[:, :, 1].astype(int), img[:, :, 2].astype(int)
    red = ((r > 130) & (g < 90) & (b < 90) & (np.abs(r - b) > 60)).astype(np.uint8) * 255
    red[int(h * 0.55):, :] = 0
    import cv2
    cnts, _ = cv2.findContours(red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in cnts:
        a = cv2.contourArea(c)
        if a < w * h * 0.00005 or a > w * h * 0.02:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        if best is None or a > best[0]:
            best = (a, x + bw // 2, y + bh // 2)
    return (best[1], best[2]) if best else None


def _skin_boxes(path, max_boxes=3):
    """启发式找手：肤色 + 指缝 + 色彩方差 + 用红眼排除脸。"""
    import numpy as np
    import cv2
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "读不到图片")
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    ycrcb = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
    mask = cv2.inRange(ycrcb, (0, 133, 77), (255, 180, 135))
    k = max(3, int(min(w, h) * 0.010))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    face = _face_center(img)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    total = w * h
    out = []
    for c in cnts:
        x, y, bw, bh = cv2.boundingRect(c)
        cx, cy = x + bw / 2, y + bh / 2
        area = cv2.contourArea(c)
        ratio = area / total
        if ratio < 0.0012 or ratio > 0.05:
            continue
        ar = bw / max(1, bh)
        if ar < 0.28 or ar > 3.4:
            continue
        if y < h * 0.15:
            continue
        if bw < w * 0.018 or bh < h * 0.015:
            continue
        # 排除脸：脸中心和脸宽的 2.4 倍范围
        if face:
            fx, fy = face
            if abs(cx - fx) < w * 0.16 and abs(cy - fy) < h * 0.16:
                continue
        m = np.zeros((h, w), np.uint8)
        cv2.drawContours(m, [c], -1, 255, -1)
        sat = hsv[:, :, 1][m > 0]
        sat_mean = float(sat.mean()) if sat.size else 0
        sat_std = float(sat.std()) if sat.size else 0
        hull = cv2.convexHull(c, returnPoints=False)
        ndef = 0
        try:
            d = cv2.convexityDefects(c, hull)
            if d is not None:
                for i in range(d.shape[0]):
                    if d[i, 0, 3] / 256.0 > max(6, min(w, h) * 0.012):
                        ndef += 1
        except Exception:
            pass
        fill = area / max(1, bw * bh)
        color_ok = (sat_mean < 100) and (sat_std < 58)
        score = (min(ndef, 5) * 0.2 + min(1.0, ratio / 0.015) * 0.2 + fill * 0.2
                 + (0.25 if color_ok else -0.15)
                 + (-0.6 if sat_mean > 120 else 0))
        out.append({"x": int(x), "y": int(y), "w": int(bw), "h": int(bh),
                    "score": round(float(max(0.0, min(1.0, score))), 3),
                    "defects": int(ndef), "sat_mean": round(sat_mean, 1), "sat_std": round(sat_std, 1),
                    "ratio": round(float(ratio), 4), "color_ok": bool(color_ok)})
    out.sort(key=lambda d: (-d["defects"], -d["score"]))
    return out[:max_boxes], {"size": [w, h], "mask_pct": round(float((mask > 0).mean()) * 100, 2),
                             "face": face}


@app.get("/api/detect-hand")
def api_detect_hand(path: str):
    boxes, meta = _skin_boxes(path)
    meta["count"] = len(boxes)
    meta["boxes"] = boxes
    return meta



_POSE_CACHE_PATH = os.path.join(HERE, "data", "pose_cache.json")
_POSE_LOCK = threading.Lock()


def _pose_cache():
    return read_json(_POSE_CACHE_PATH, {}) or {}


def _pose_run(ref_name, tag):
    """跑一次 SDPose，返回 JSON 路径（输出是文本，不是图片，不能用 cf.wait）。"""
    wf, meta = gf.build("sdpose_probe", {"reference": ref_name, "prefix": tag})
    if meta["missing"]:
        raise HTTPException(503, "姿态节点缺失: " + ", ".join(meta["missing"]))
    pid = gf.submit(wf)
    t0 = time.time()
    while time.time() - t0 < 300:
        h = cf.history(pid)
        if h:
            st = h.get("status", {})
            if st.get("status_str") == "error":
                msg = ""
                for kind, payload in st.get("messages", []):
                    if kind == "execution_error":
                        msg = payload.get("exception_message", "")
                raise HTTPException(500, "姿态节点报错: " + str(msg)[:300])
            for node in (h.get("outputs") or {}).values():
                for t in (node.get("text") or []):
                    if isinstance(t, str) and t.endswith(".json") and os.path.isfile(t):
                        return t
            break
        time.sleep(1.5)
    pose_dir = os.path.join(COMFY_OUT, "pose")
    if os.path.isdir(pose_dir):
        cands = sorted([os.path.join(pose_dir, f) for f in os.listdir(pose_dir) if f.startswith(tag + "_")],
                       key=os.path.getmtime)
        if cands:
            return cands[-1]
    raise HTTPException(500, "没有生成姿态 JSON")


def _hand_boxes_from_pose(path):
    data = read_json(path, [])
    if isinstance(data, dict):
        data = [data]
    if not data:
        return []
    person = (data[0].get("people") or [{}])[0]
    W = int(data[0].get("canvas_width") or 1024)
    H = int(data[0].get("canvas_height") or 1536)
    out = []
    for key, label in (("hand_left_keypoints_2d", "left"), ("hand_right_keypoints_2d", "right")):
        arr = person.get(key) or []
        pts = [(arr[i], arr[i + 1], arr[i + 2]) for i in range(0, len(arr) - 2, 3)]
        valid = [p for p in pts if p[2] > 0.15 and p[0] >= 0 and p[1] >= 0]
        if len(valid) < 6:
            continue
        xs = [p[0] for p in valid]; ys = [p[1] for p in valid]
        pad = 0.22 * max(max(xs) - min(xs), max(ys) - min(ys)) + 14
        x0 = int(max(0, min(xs) - pad)); y0 = int(max(0, min(ys) - pad))
        x1 = int(min(W, max(xs) + pad)); y1 = int(min(H, max(ys) + pad))
        bw, bh = x1 - x0, y1 - y0
        area = bw * bh / float(W * H)
        if area < 0.002 or area > 0.12:
            continue
        # 贴边 = 大概率误检（手不在画面里）
        if x0 <= 2 or y0 <= 2 or x1 >= W - 2 or y1 >= H - 2:
            continue
        score = max(p[2] for p in valid)
        out.append({"x": x0, "y": y0, "w": bw, "h": bh, "hand": label,
                    "score": round(float(score), 3), "points": len(valid), "source": "pose"})
    out.sort(key=lambda d: -d["score"])
    return out[:2]


@app.get("/api/detect-hand-pose")
def api_detect_hand_pose(path: str):
    if not os.path.isfile(path):
        raise HTTPException(400, "图片不存在")
    st = os.stat(path)
    key = "%s|%d|%d" % (path, st.st_size, int(st.st_mtime))
    cache = _pose_cache()
    with _POSE_LOCK:
        hit = cache.get(key)
        if hit and os.path.isfile(hit):
            return {"source": "pose(cache)", "json": hit, "boxes": _hand_boxes_from_pose(hit)}
        ref = _prepare_reference(path)
        tag = "p_" + re.sub(r"[^A-Za-z0-9]", "", os.path.splitext(os.path.basename(path))[0])[:18]
        js = _pose_run(ref, tag)
        cache[key] = js
        write_json(_POSE_CACHE_PATH, cache)
    return {"source": "pose", "json": js, "boxes": _hand_boxes_from_pose(js)}


@app.get("/api/detect-hand-auto")
def api_detect_hand_auto(path: str):
    """姿态模型优先；它成功但没框到 → 直接说没找到（肤色兜底不可靠，只在姿态失败时用）。"""
    try:
        r = api_detect_hand_pose(path)
        if r["boxes"]:
            return r
        return {"source": "pose-empty", "json": r.get("json"), "boxes": []}
    except Exception as e:
        try:
            fallback = api_detect_hand(path)
            fallback["source"] = "skin(pose-fail)"
            fallback["pose_error"] = str(e)[:200]
            return fallback
        except Exception as e2:
            raise HTTPException(500, "自动找手失败: %s / %s" % (e, e2))


@app.get("/api/last-graph")
def api_last_graph():
    return LAST_GRAPH or {}


@app.get("/api/engine")
def api_engine():
    info = gf.engine_info()
    try:
        info["queue"] = cf.queue_state()
    except Exception:
        info["queue"] = {"running": 0, "pending": 0}
    return info


@app.get("/api/regress")
def api_regress():
    return run_regress()


def run_regress():
    """静态不变量检查：文档/数据/图/模板是否互相一致。"""
    checks = []

    def add(name, ok, detail, fix=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "fix": fix})

    tokens, lib, ch = load_tokens()
    notes = lib.get("notes", {})

    bad_left = []
    for tpl in (store.load_templates()):
        for b in (tpl.get("positive") or []) + (tpl.get("negative") or []):
            tok = b.get("token")
            if tok and tok not in tokens:
                bad_left.append(tpl.get("name", "?") + ":" + tok)
    add("模板引用的宏都存在", not bad_left, ", ".join(bad_left[:5]) or "OK",
        "模板里引用了不存在的积木，去词库补或从模板删")

    # 只要求 prompt_lib 里的积木有备注；服装派生的 @OUT_*/@NEG_* 是动态生成的，不算缺
    lib_tokens = (lib.get("tokens") or {})
    untested = [k for k in lib_tokens if k.startswith("@") and k not in notes]
    add("每个积木有备注", len(untested) == 0, "%d 个缺备注" % len(untested),
        "缺备注：" + ", ".join(untested[:5]))

    up = cf.system_stats()["up"]
    add("ComfyUI 在线", up, "在线" if up else "离线，节点检查已跳过",
        "启动 ComfyUI（引擎页有一键启动），或等 supervisor 自动拉起")
    if up:
        have_nodes = gf.comfy_nodes(force=True)
        missing_wf = []
        for name in gf.list_workflows():
            wf = gf.load(name)
            miss = [n for n in wf.get("requires", []) if n not in have_nodes]
            if miss:
                missing_wf.append(name + ":" + ",".join(miss))
        add("工作流所需节点齐全", not missing_wf, "; ".join(missing_wf) or "OK",
            "ComfyUI 版本变化或缺自定义节点；在「引擎」页查看")
    else:
        add("工作流所需节点齐全", False, "跳过（ComfyUI 离线）", "先启动 ComfyUI")

    dup = []
    for name in gf.list_workflows():
        wf = gf.load(name)
        if "nodes" not in wf or not wf.get("nodes"):
            dup.append(name)
            dup.append(name)
    add("工作流 JSON 结构完整", not dup, ", ".join(dup) or "OK", "缺 sampler/nodes 字段")

    add("两套服装存在", all(k in (ch.get("garments") or {}) for k in ("slip", "initial")),
        ", ".join((ch.get("garments") or {}).keys()), "补 character.json")

    return {"ok": all(c["ok"] for c in checks), "checks": checks}


@app.post("/api/cancel/{jid}")
def api_cancel(jid: str):
    ok = cf.interrupt()
    j = JOBS.get(jid)
    if j:
        j["status"] = "cancelled"
    return {"interrupted": ok}


# ---------------- gallery ----------------
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def registry_entries():
    return store.load_registry()


@app.get("/api/gallery")
def api_gallery(dir: str = "station_out", limit: int = 60, offset: int = 0):
    base = OUT_DIR if dir == "station_out" else os.path.join(ROOT, "SD-Picture", dir)
    if not os.path.isdir(base):
        return {"items": [], "total": 0}
    files = []
    for name in os.listdir(base):
        if name.lower().endswith(IMG_EXT):
            p = os.path.join(base, name)
            files.append((os.path.getmtime(p), p))
    files.sort(reverse=True)
    reg = {os.path.basename(r.get("file", "")): r for r in registry_entries()}
    items = []
    for mt, p in files[offset:offset + limit]:
        name = os.path.basename(p)
        e = reg.get(name)
        items.append({"path": p, "name": name, "mtime": int(mt),
                      "verdict": (e or {}).get("verdict", ""), "note": (e or {}).get("note", "")})
    return {"items": items, "total": len(files)}


class GlitchReq(BaseModel):
    path: str
    intensity: float = 0.6


@app.post("/api/glitch")
def api_glitch(req: GlitchReq):
    import glitchify
    src = req.path
    if not os.path.isfile(src):
        raise HTTPException(404, "图片不存在")
    base, _ext = os.path.splitext(src)
    dst = base + "_glitch.png"
    glitchify.glitchify(src, dst, max(0.1, min(2.0, req.intensity)))
    return {"ok": True, "path": dst}


IMG_ROOTS = [os.path.join(ROOT, "SD-Picture"),
             os.path.join(ROOT, "产出作品", "画师参考"),
             os.path.join(ROOT, "comfy", "ComfyUI", "output"),
             os.path.join(ROOT, "comfy", "ComfyUI", "input"),
             os.path.join(ROOT, "comfy", "ComfyUI", "temp")]


def _img_allowed(path: str) -> bool:
    try:
        rp = os.path.realpath(path)
    except Exception:
        return False
    for root in IMG_ROOTS:
        rr = os.path.realpath(root)
        try:
            if os.path.commonpath([rp, rr]) == rr:
                return True
        except ValueError:
            continue
    return False


@app.get("/api/img")
def api_img(path: str):
    if not _img_allowed(path):
        raise HTTPException(403, "路径不在允许目录内")
    if not os.path.isfile(path):
        raise HTTPException(404, "not found")
    return FileResponse(path)


@app.post("/api/log")
def api_log(req: LogReq):
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "file": req.path,
             "verdict": req.verdict, "note": req.note, "seed": req.seed,
             "tags": req.tags, "params": req.params}
    store.append_registry(entry)
    return {"ok": True, "entry": entry}


@app.get("/api/registry")
def api_registry(limit: int = 200):
    rows = registry_entries()
    return {"items": list(reversed(rows))[:limit], "total": len(rows)}


# ---------------- library ----------------
@app.post("/api/token/note")
def api_token_note(req: TokenReq):
    lib = read_json(LIB, {"tokens": {}}) or {}
    notes = lib.setdefault("notes", {})
    name = req.name if req.name.startswith("@") else "@" + req.name.upper()
    if req.text.strip():
        notes[name] = req.text.strip()
    else:
        notes.pop(name, None)
    write_json(LIB, lib)
    return {"ok": True, "notes": notes}


@app.post("/api/token/save")
def api_token_save(req: TokenReq):
    lib = read_json(LIB, {"tokens": {}}) or {}
    toks = lib.setdefault("tokens", {})
    name = req.name if req.name.startswith("@") else "@" + req.name.upper()
    toks[name] = req.text
    meta = lib.setdefault("meta", {})
    subs = meta.setdefault("subgroups", {})
    if req.subgroup.strip():
        subs[name] = {"label": req.subgroup.strip(), "color": req.color.strip() or "#7aa2d6"}
    else:
        subs.pop(name, None)
    write_json(LIB, lib)
    return {"ok": True, "name": name, "tokens": toks, "subgroups": subs}


@app.post("/api/token/delete")
def api_token_delete(req: TokenReq):
    lib = read_json(LIB, {"tokens": {}}) or {}
    toks = lib.get("tokens", {})
    toks.pop(req.name, None)
    write_json(LIB, lib)
    return {"ok": True, "tokens": toks}


@app.post("/api/garment/delete")
def api_garment_delete(req: GarmentReq):
    ch = read_json(CHAR, {}) or {}
    gs = ch.get("garments", {})
    if req.key not in gs:
        raise HTTPException(404, "没有这套服装")
    if len(gs) <= 1:
        raise HTTPException(400, "至少保留一套服装")
    gs.pop(req.key)
    write_json(CHAR, ch)
    return {"ok": True, "garments": gs}


@app.post("/api/garment/save")
def api_garment_save(req: GarmentReq):
    ch = read_json(CHAR, {}) or {}
    g = ch.setdefault("garments", {}).setdefault(req.key, {})
    g["prompt"] = req.prompt
    g["negative"] = req.negative
    if req.label:
        g["label"] = req.label
    if req.use_for:
        g["use_for"] = req.use_for
    if req.hands_left:
        g["hands_left"] = req.hands_left
    if req.hands_right:
        g["hands_right"] = req.hands_right
    if req.drape:
        g["drape"] = {"state": req.drape, "terms": []}
    if req.note is not None:
        g["note"] = req.note
    write_json(CHAR, ch)
    return {"ok": True, "garments": ch.get("garments", {})}


TPL = os.path.join(HERE, "data", "templates.json")


@app.get("/api/templates")
def api_templates():
    return {"items": store.load_templates()}


class TplSaveReq(BaseModel):
    name: str
    params: dict = {}
    positive: List[Any] = []
    negative: List[Any] = []


@app.post("/api/template/save")
def api_template_save(req: TplSaveReq):
    items = store.load_templates()
    entry = {"name": req.name.strip(), "params": req.params or {},
             "positive": req.positive or [], "negative": req.negative or []}
    items = [it for it in items if it.get("name") != entry["name"]]
    items.append(entry)
    store.save_templates(items)
    return {"ok": True, "items": items}


@app.get("/api/presets")
def api_presets():
    return {"items": read_json(PRESETS, []) or []}


@app.post("/api/presets/save")
def api_presets_save(req: PresetReq):
    items = read_json(PRESETS, []) or []
    items = [x for x in items if x.get("name") != req.name]
    items.append(req.dict())
    write_json(PRESETS, items)
    return {"ok": True, "items": items}


# ---------------- train / tag ----------------
@app.get("/api/train/profiles")
def api_profiles():
    out = {}
    try:
        r = subprocess.run([PY, os.path.join(REF, "train_lora.py"), "--list-profiles"],
                           capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
        out["text"] = r.stdout.strip()
    except Exception as e:
        out["error"] = str(e)
    out["datasets"] = [{"name": d, "samples": dataset_samples(d)} for d in list_datasets()]
    caches = os.path.join(ROOT, "comfy", "ComfyUI", "datasets")
    out["caches"] = sorted(os.listdir(caches)) if os.path.isdir(caches) else []
    return out


@app.post("/api/train/start")
def api_train_start(req: TrainReq):
    jid = job_new("train", req.dataset)
    args = [PY, os.path.join(REF, "train_lora.py"), "--dataset", req.dataset,
            "--steps", str(req.steps), "--keep", str(req.keep), "--prefix", req.prefix]
    if req.profile:
        args += ["--profile", req.profile]
    if req.rank:
        args += ["--rank", str(req.rank)]
    if req.lr:
        args += ["--lr", str(req.lr)]
    if req.cache:
        args += ["--cache", req.cache]
    if req.build_cache:
        args += ["--build-cache", req.build_cache]
    if req.existing_lora:
        args += ["--existing-lora", req.existing_lora]
    if req.dry_run:
        args += ["--dry-run"]

    def work():
        try:
            p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace", bufsize=1)
            for line in p.stdout:
                job_log(jid, line.strip())
                if "%" in line:
                    m = re.search(r"(\d+)%", line)
                    if m:
                        JOBS[jid]["progress"] = int(m.group(1)) / 100.0
            code = p.wait()
            JOBS[jid].update(status="done" if code == 0 else "error", progress=1.0,
                             result={"exit": code})
        except Exception as e:
            JOBS[jid].update(status="error", result={"error": str(e)})

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid, "cmd": " ".join(args)}


@app.post("/api/tag/start")
def api_tag_start(req: TagReq):
    jid = job_new("tag", req.dataset)
    folder = os.path.join(ROOT, "comfy", "ComfyUI", "input", req.dataset)
    args = [PY, os.path.join(REF, "tag_wd14.py"), "--dir", folder,
            "--threshold", str(req.threshold)]
    if req.trigger:
        args += ["--trigger", req.trigger]
    if req.extra:
        args += ["--extra", req.extra]
    if req.write:
        args += ["--write"]
    else:
        args += ["--preview", "12"]
    if req.drop_appearance:
        args += ["--drop-appearance"]

    def work():
        try:
            env = dict(os.environ)
            env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace", bufsize=1, env=env)
            for line in p.stdout:
                job_log(jid, line.strip())
            code = p.wait()
            JOBS[jid].update(status="done" if code == 0 else "error", progress=1.0,
                             result={"exit": code})
        except Exception as e:
            JOBS[jid].update(status="error", result={"error": str(e)})

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid, "cmd": " ".join(args)}


# ---------------- maintenance ----------------
@app.get("/api/maintenance")
def api_maint():
    def du(*parts):
        p = os.path.join(ROOT, *parts)
        if not os.path.isdir(p):
            return 0
        s = 0
        for dp, _, fs in os.walk(p):
            for f in fs:
                try:
                    s += os.path.getsize(os.path.join(dp, f))
                except OSError:
                    pass
        return round(s / 1048576, 1)

    disk = shutil.disk_usage(ROOT)
    return {
        "disk": {"free_gb": round(disk.free / 1073741824, 1), "total_gb": round(disk.total / 1073741824, 1)},
        "sizes": {
            "原图": du("SD-Picture", "原图"),
            "remote_out": du("SD-Picture", "remote_out"),
            "station_out": du("SD-Picture", "station_out"),
            "harvest": du("SD-Picture", "harvest"),
            "comfy output": du("comfy", "ComfyUI", "output"),
            "datasets": du("comfy", "ComfyUI", "datasets"),
        },
        "registry": len(registry_entries()),
    }


@app.post("/api/maintenance/cleanup")
def api_cleanup(dry: bool = Query(True)):
    args = [PY, os.path.join(REF, "cleanup.py")]
    env = dict(os.environ)
    env["CLEAN_DRY"] = "1" if dry else "0"
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, timeout=600)
    return {"dry": dry, "output": (r.stdout or "")[-4000:]}


@app.get("/api/features")
def api_features():
    return {"groups": FEATURES}


@app.get("/api/docs")
def api_docs():
    seen, out = set(), []
    for d in DOC_DIRS:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.endswith(".md") and name not in seen:
                seen.add(name)
                out.append({"name": name, "path": os.path.join(d, name)})
    out.sort(key=lambda x: x["name"])
    return {"items": out}


@app.get("/api/doc")
def api_doc(path: str):
    if not os.path.isfile(path):
        raise HTTPException(404, "not found")
    with open(path, encoding="utf-8", errors="replace") as f:
        return {"text": f.read()}



def mirror_score(path):
    """粗略判断是否左右镜像分屏：左右两半高度相似 → 疑似分屏。"""
    try:
        import numpy as np
        from PIL import Image
        im = Image.open(path).convert("L").resize((256, 256))
        a = np.asarray(im).astype(np.float32) / 255.0
        left = a[:, :128]
        right = np.fliplr(a[:, 128:])
        diff = float(np.abs(left - right).mean())
        return round(1.0 - diff, 3)
    except Exception:
        return 0.0


@app.get("/api/qc")
def api_qc(path: str):
    try:
        import numpy as np
        from PIL import Image
        im = Image.open(path).convert("RGB")
        arr = np.asarray(im).astype(np.float32) / 255.0
        lum = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]
        h, w = lum.shape
        face = lum[int(h * 0.08):int(h * 0.32), int(w * 0.3):int(w * 0.7)]
        over = float((lum > 0.98).mean())
        dead = float((lum < 0.02).mean())
        return {"ok": True, "mirror": mirror_score(path),
                "split_suspect": mirror_score(path) >= 0.86,
                "mean": round(float(lum.mean()), 3),
                "face_mean": round(float(face.mean()), 3),
                "highlight_pct": round(over * 100, 2),
                "dead_black_pct": round(dead * 100, 2),
                "overexposed": over > 0.04, "dead_black_bad": dead > 0.25}
    except Exception as e:
        return {"ok": False, "error": str(e)}



@app.get("/api/pipeline/check")
def api_pipeline_check():
    import pipeline_check
    return pipeline_check.run_checks()


@app.post("/api/comfy/start")
def api_comfy_start():
    import pipeline_check
    ok, msg = pipeline_check.start_comfy()
    return {"ok": ok, "detail": msg if ok else "", "error": "" if ok else msg}




def comfy_supervisor():
    """守护 ComfyUI：启动时若不在线就拉起，之后每 60 秒检查一次。"""
    import pipeline_check
    time.sleep(4)
    while True:
        try:
            if not cf.system_stats()["up"]:
                ok, msg = pipeline_check.start_comfy(wait=90)
                print("[supervisor] comfy", "started:" if ok else "FAILED:", msg, flush=True)
        except Exception as e:
            print("[supervisor] err", e, flush=True)
        time.sleep(60)




CARDS = os.path.join(HERE, "data", "cards.json")
store.init(recipes_json=RECIPE_PATH, registry_jsonl=REG,
           templates_json=TPL, cards_json=CARDS)

import routes_cards
import routes_promptlib

app.include_router(routes_cards.router)
app.include_router(routes_promptlib.router)

app.mount("/", StaticFiles(directory=os.path.join(HERE, "static"), html=True), name="static")


if __name__ == "__main__":
    import socket
    import threading
    import webbrowser
    import uvicorn

    _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _busy = _s.connect_ex(("127.0.0.1", 8770)) == 0
    _s.close()
    if _busy:
        print("LOOM: server already running on http://127.0.0.1:8770/")
        webbrowser.open("http://127.0.0.1:8770/")
        raise SystemExit(0)

    if os.environ.get("STATION_NO_SUPERVISOR") != "1":
        threading.Thread(target=comfy_supervisor, daemon=True).start()

    def _open():
        time.sleep(1.5)
        webbrowser.open("http://127.0.0.1:8770/")

    threading.Thread(target=_open, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8770, log_level="warning")