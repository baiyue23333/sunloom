# -*- coding: utf-8 -*-
"""训练、WD14 打标、磁盘维护、半成品清理、文档与 ComfyUI 守护路由。"""
import os
import re
import shutil
import subprocess
import time

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from svc_paths import require_file

import comfy as cf
from svc_state import (
    DOC_DIRS,
    DRAFT_RE,
    DRAFT_SCAN_ROOT,
    IMG_EXT,
    JOBS,
    PY,
    REF,
    ROOT,
    TRASH_DIR,
    comfy_in,
    comfy_out,
    dataset_samples,
    job_log,
    job_new,
    list_datasets,
    registry_entries,
)

router = APIRouter()

FEATURES = [
    {"group": "拼装", "items": [
        "拖拽/点击添加积木（机位、打光、身份、体型、表情、服装、型态、负向、场景）",
        "每块可调权重（写进提示词如 (bone:1.35)）、可临时停用、可删除、可左右拖动排序",
        "自由文本块：任意英文标签直接插入正向/负向",
        "实时展开预览：宏自动展开，显示字符数与使用了哪些宏",
        "快速模板：一键摆好一组积木（胸像窗光/夜灯/楼梯/门厅）",
        "参数：尺寸预设、步数、CFG、种子、前缀、任意多个 LoRA 与权重",
        "出图：进度条 + 预计耗时 + 完成后可直接登记 A/B/C"]},
    {"group": "画师 LoRA · 弱 3D", "items": [
        "弱 3D 风格怎么写：@style_lora_b 权重 1.3（1.0 偏弱），只挂它一个 LoRA",
        "不要再叠 h2 / modare / Lucent —— 风格会互相抢，3D 感消失",
        "身份用文本（silver hair, two-tone eyes…），别用 @ID 积木",
        "场景/服装/光各留 1 块，块越多 LoRA 越被稀释",
        "参数 1024×1536 / 28 步 / CFG 5.5；灰底或浅景深都行",
        "词库→组合推荐里有现成模板：弱 3D 人像、弱 3D · 场景版"]},
    {"group": "词库", "items": [
        "查看/搜索全部宏（@ID @BODY @FACE @CAM_* @OUT_* @DRAPE_* @LIGHT_* @NEG_*）",
        "新建、编辑、删除任意宏，保存即写入 prompt_lib.json",
        "服装编辑器：slip / initial 的正向、负向、型态（半脱/披肩/肘部/穿好）",
        "保存后积木库与预览立即生效（同一份数据源）"]},
    {"group": "画廊", "items": [
        "浏览工作站输出 / remote_out / 原图，网格缩略图",
        "点击看大图 + 自动质检（平均亮度、脸部亮度、过曝%、死黑%、是否超标）",
        "在弹窗里直接登记 A/B/C 并写备注"]},
    {"group": "登记表", "items": [
        "查看最近登记（时间、等级、备注、文件名）",
        "顶栏实时显示登记总数"]},
    {"group": "训练", "items": [
        "数据集列表与样本数、已建缓存列表",
        "档位选择（auto/local/gpu/t4/gpu）、steps/rank/lr/保留数",
        "建缓存 / 用缓存训练，续训已有 LoRA",
        "只预演（dry-run）看实际参数，不占用显卡",
        "实时日志与进度解析"]},
    {"group": "打标", "items": [
        "WD14 自动打标：触发词、附加词、阈值",
        "角色 LoRA 专用：删掉外观标签（发/眼/饰/服装）",
        "预览模式或直接写入 caption",
        "实时日志"]},
    {"group": "维护", "items": [
        "磁盘用量（各图像目录、ComfyUI 输出、数据集）",
        "清理预演 / 执行清理（登记作品自动保留）",
        "文档浏览（画师手册、服装规格、打光规则、复盘、指南等）"]},
    {"group": "全局", "items": [
        "顶栏状态：ComfyUI 版本/在线、队列长度、登记总数（15 秒自动刷新）",
        "所有改动直接写回 ref/prompt_lib.json、ref/character.json、ref/registry.jsonl",
        "快捷键：Esc 关闭弹窗"]},
]


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


def _comfy_datasets_dir():
    return os.path.join(os.path.dirname(comfy_in()), "datasets")


@router.get("/api/train/profiles")
def api_profiles():
    out = {}
    try:
        r = subprocess.run([PY, os.path.join(REF, "train_lora.py"), "--list-profiles"],
                           capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
        out["text"] = r.stdout.strip()
    except Exception as e:
        out["error"] = str(e)
    out["datasets"] = [{"name": d, "samples": dataset_samples(d)} for d in list_datasets()]
    caches = _comfy_datasets_dir()
    out["caches"] = sorted(os.listdir(caches)) if os.path.isdir(caches) else []
    return out


@router.post("/api/train/start")
def api_train_start(req: TrainReq):
    import threading
    jid = job_new("train", req.dataset)
    args = [PY, os.path.join(REF, "train_lora.py"), "--dataset", req.dataset,
            "--steps", str(req.steps), "--keep", str(req.keep), "--prefix", req.prefix]
    for flag, val in (("--profile", req.profile), ("--rank", req.rank), ("--lr", req.lr),
                      ("--cache", req.cache), ("--build-cache", req.build_cache),
                      ("--existing-lora", req.existing_lora)):
        if val:
            args += [flag, str(val)]
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
            JOBS[jid].update(status="done" if code == 0 else "error", progress=1.0, result={"exit": code})
        except Exception as e:
            JOBS[jid].update(status="error", result={"error": str(e)})

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid, "cmd": " ".join(args)}


@router.post("/api/tag/start")
def api_tag_start(req: TagReq):
    import threading
    jid = job_new("tag", req.dataset)
    folder = os.path.join(comfy_in(), req.dataset)
    args = [PY, os.path.join(REF, "tag_wd14.py"), "--dir", folder, "--threshold", str(req.threshold)]
    if req.trigger:
        args += ["--trigger", req.trigger]
    if req.extra:
        args += ["--extra", req.extra]
    args += ["--write"] if req.write else ["--preview", "12"]
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
            JOBS[jid].update(status="done" if code == 0 else "error", progress=1.0, result={"exit": code})
        except Exception as e:
            JOBS[jid].update(status="error", result={"error": str(e)})

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid, "cmd": " ".join(args)}


def _dir_mb(p):
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


@router.get("/api/maintenance")
def api_maint():
    disk = shutil.disk_usage(ROOT)
    return {
        "disk": {"free_gb": round(disk.free / 1073741824, 1), "total_gb": round(disk.total / 1073741824, 1)},
        "sizes": {
            "原图": _dir_mb(os.path.join(ROOT, "SD-Picture", "原图")),
            "remote_out": _dir_mb(os.path.join(ROOT, "SD-Picture", "remote_out")),
            "station_out": _dir_mb(os.path.join(ROOT, "SD-Picture", "station_out")),
            "harvest": _dir_mb(os.path.join(ROOT, "SD-Picture", "harvest")),
            "comfy output": _dir_mb(comfy_out()),
            "datasets": _dir_mb(_comfy_datasets_dir()),
        },
        "registry": len(registry_entries()),
    }


@router.post("/api/maintenance/cleanup")
def api_cleanup(dry: bool = Query(True)):
    args = [PY, os.path.join(REF, "cleanup.py")]
    env = dict(os.environ)
    env["CLEAN_DRY"] = "1" if dry else "0"
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=600)
    return {"dry": dry, "output": (r.stdout or "")[-4000:]}


def _draft_files():
    out = []
    if not os.path.isdir(DRAFT_SCAN_ROOT):
        return out
    for dp, dns, fns in os.walk(DRAFT_SCAN_ROOT):
        rel = os.path.relpath(dp, DRAFT_SCAN_ROOT)
        parts = [] if rel == "." else rel.split(os.sep)
        if any(p.lower() in ("_trash", "garment_previews") for p in parts):
            dns[:] = []
            continue
        for n in fns:
            low = n.lower()
            if not low.endswith(IMG_EXT):
                continue
            stem = os.path.splitext(low)[0]
            if stem in ("comp", "final") or stem.startswith("final"):
                continue
            if stem.startswith("_") or DRAFT_RE.search(stem) or any(p.startswith("_") for p in parts):
                out.append(os.path.join(dp, n))
    return out


@router.post("/api/maintenance/drafts")
def api_cleanup_drafts(dry: bool = Query(True)):
    files = _draft_files()
    total_mb = 0.0
    for p in files:
        try:
            total_mb += os.path.getsize(p) / 1048576.0
        except OSError:
            pass
    if dry:
        return {"dry": True, "count": len(files), "mb": round(total_mb, 1),
                "sample": [os.path.basename(x) for x in files[:12]]}
    dst_dir = os.path.join(TRASH_DIR, "drafts_" + time.strftime("%Y%m%d"))
    os.makedirs(dst_dir, exist_ok=True)
    moved = 0
    for p in files:
        try:
            dst = os.path.join(dst_dir, os.path.basename(p))
            if os.path.exists(dst):
                base, ext = os.path.splitext(os.path.basename(p))
                dst = os.path.join(dst_dir, "%s_%s%s" % (base, time.strftime("%H%M%S"), ext))
            shutil.move(p, dst)
            moved += 1
        except Exception:
            pass
    return {"dry": False, "count": len(files), "moved": moved, "mb": round(total_mb, 1), "trash": dst_dir}


@router.get("/api/features")
def api_features():
    return {"groups": FEATURES}


@router.get("/api/docs")
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


@router.get("/api/doc")
def api_doc(path: str):
    path = require_file(path, DOC_DIRS, (".md",))
    with open(path, encoding="utf-8", errors="replace") as f:
        return {"text": f.read()}


@router.get("/api/pipeline/check")
def api_pipeline_check():
    import pipeline_check
    return pipeline_check.run_checks()


@router.post("/api/comfy/start")
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
