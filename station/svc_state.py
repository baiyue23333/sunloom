# -*- coding: utf-8 -*-
"""站点共享状态、路径探测（委托 tools/comfy_paths）、存储与任务调度基础。"""
import json
import os
import re
import shutil
import sys
import threading
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REF = os.path.join(ROOT, "ref")
CORE = os.path.join(ROOT, "core")
TOOLS = os.path.join(ROOT, "tools")

for _p in (REF, HERE, CORE, TOOLS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import comfy as cf  # noqa: E402
import comfy_paths  # noqa: E402
import prompts as pt  # noqa: E402
import store  # noqa: E402
from svc_obs import warn  # noqa: E402

DATA_DIR = os.path.join(HERE, "data")
LIB = os.path.join(REF, "prompt_lib.json")
CHAR = os.path.join(REF, "character.json")
REG = os.path.join(REF, "registry.jsonl")
PRESETS = os.path.join(DATA_DIR, "presets.json")
RECIPE_PATH = os.path.join(DATA_DIR, "recipes.json")
TPL = os.path.join(DATA_DIR, "templates.json")
CARDS = os.path.join(DATA_DIR, "cards.json")

OUT_DIR = os.path.join(ROOT, "SD-Picture", "station_out")
COOP_DIR = os.path.join(ROOT, "SD-Picture", "coop")
MASK_DIR = os.path.join(ROOT, "SD-Picture", "masks")
TRASH_DIR = os.path.join(ROOT, "SD-Picture", "_trash")
DRAFT_SCAN_ROOT = os.path.join(ROOT, "SD-Picture")
DOC_DIRS = [os.path.join(ROOT, "产出作品")]  # 文档唯一真相：产出作品/
PY = sys.executable

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
store.set_warn_hook(warn)
store.init(recipes_json=RECIPE_PATH, registry_jsonl=REG, templates_json=TPL, cards_json=CARDS)

JOBS = {}
JOBS_MAX = 200
LAST_GRAPH = {}
COOP_STATE = {"status": "idle", "dir": "", "image": "", "log": "", "started": 0.0}
MEM_LAST_JOB = [time.time()]
MEM_LAST_FREE = [0.0]
MEM_COMFY_FREED = [0]


def _hydrate_jobs():
    """启动时从 SQLite 载入最近任务，把上次遗留运行中任务标为 interrupted。"""
    for j in reversed(store.load_jobs(JOBS_MAX)):
        jid = j.get("id")
        if not jid:
            continue
        if j.get("status") == "running":
            j["status"] = "interrupted"
            j["result"] = j.get("result") or {"error": "站台重启导致任务中断"}
            store.upsert_job(j)
        JOBS[jid] = j


_hydrate_jobs()


def job_save(jid):
    j = JOBS.get(jid)
    if not j:
        return
    try:
        store.upsert_job(j)
        store.trim_jobs(JOBS_MAX)
    except Exception as e:
        warn("job_save", e, jid)

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
DRAFT_RE = re.compile(
    r"(^|[_\-])(bg|char|alpha|comp_raw|plate|mask|sketch|draft|fg|prop|card|lift|layer"
    r"|probe|test|preview|scan|sample|debug|tmp)([_.\-]|$)", re.I,
)
COOP_ROOTS = [
    COOP_DIR,
    os.path.join(ROOT, "SD-Picture", "coop2"),
    os.path.join(ROOT, "SD-Picture", "coop_b"),
    os.path.join(ROOT, "SD-Picture", "coop_gen"),
    os.path.join(ROOT, "SD-Picture"),
    os.path.join(ROOT, "SD-Picture", "regional"),
    os.path.join(ROOT, "SD-Picture", "paper"),
]

_LORA_META_CACHE = {}
_LORA_CACHE_META = {"sig": None}


def comfy_in():
    d = comfy_paths.comfy_in()
    os.makedirs(d, exist_ok=True)
    return d


def comfy_out():
    return comfy_paths.comfy_out()


def img_roots():
    return [
        os.path.join(ROOT, "SD-Picture"),
        os.path.join(ROOT, "产出作品", "画师参考"),
        comfy_paths.comfy_out(),
        comfy_paths.comfy_in(),
        comfy_paths.comfy_temp(),
        os.path.join(ROOT, "comfy", "ComfyUI", "output"),
        os.path.join(ROOT, "comfy", "ComfyUI", "temp"),
    ]


def delete_roots():
    return [os.path.join(ROOT, "SD-Picture"), comfy_paths.comfy_out()]


def img_allowed(path: str) -> bool:
    try:
        rp = os.path.realpath(path)
    except Exception:
        return False
    for root in img_roots():
        try:
            rr = os.path.realpath(root)
            if os.path.commonpath([rp, rr]) == rr:
                return True
        except ValueError:
            continue
    return False


def read_json(path, default=None):
    if not path or not os.path.isfile(path):
        return default if default is not None else {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        warn("read_json", e, path)
        return default if default is not None else {}


def _snapshot(path):
    """每次写前存一份时间戳快照，保留最新 3 份，防止多处写入覆盖后无法回滚。"""
    if not path or not os.path.isfile(path):
        return
    try:
        d = os.path.join(DATA_DIR, "snapshots")
        os.makedirs(d, exist_ok=True)
        base = os.path.basename(path)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, os.path.join(d, base + "." + stamp + ".bak"))
        keep = sorted([x for x in os.listdir(d) if x.startswith(base + ".")])
        for old in keep[:-3]:
            try:
                os.remove(os.path.join(d, old))
            except OSError as e:
                warn("snapshot_prune", e, old)
    except Exception as e:
        warn("snapshot", e, path)


def write_json(path, data):
    _snapshot(path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_tokens():
    return pt.load_tokens()


def expand(text, tokens):
    return pt.expand(text, tokens)


def list_datasets():
    d = comfy_in()
    if not os.path.isdir(d):
        return []
    return sorted([x for x in os.listdir(d) if os.path.isdir(os.path.join(d, x))])


def _load_json(path, default):
    if not path or not os.path.isfile(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        warn("load_json", e, path)
        return default


def list_models():
    got = cf.models("diffusion_models")
    if got:
        return sorted(f for f in got if f.endswith((".safetensors", ".gguf", ".sft")))
    for base in comfy_paths.comfy_models_dirs():
        d = os.path.join(base, "diffusion_models")
        if os.path.isdir(d):
            return sorted(f for f in os.listdir(d) if f.endswith((".safetensors", ".gguf", ".sft")))
    return []


def _lora_dir():
    cands = [os.environ.get("SUNLOOM_LORA_DIR") or ""]
    cands.extend(os.path.join(b, "loras") for b in comfy_paths.comfy_models_dirs())
    for c in cands:
        if c and os.path.isdir(c):
            return c
    return ""


def _lora_sig(root):
    ov_path = os.path.join(REF, "lora_base_overrides.json")
    try:
        ov_mt = os.stat(ov_path).st_mtime_ns
    except OSError:
        ov_mt = 0
    if not root or not os.path.isdir(root):
        return (root, 0, 0, ov_mt)
    max_mt, cnt = 0, 0
    for cur, _dirs, files in os.walk(root):
        try:
            max_mt = max(max_mt, os.stat(cur).st_mtime_ns)
        except OSError:
            pass
        cnt += sum(1 for f in files if f.endswith(".safetensors"))
    return (root, max_mt, cnt, ov_mt)


def _lora_base_map(force=False):
    """按 safetensors 头部判定每个 LoRA 的训练底模（带目录/覆盖表变更自动失效）。"""
    root = _lora_dir()
    sig = _lora_sig(root)
    if not force and _LORA_META_CACHE and _LORA_CACHE_META.get("sig") == sig:
        return _LORA_META_CACHE
    out = {}
    if not root:
        _LORA_META_CACHE.clear()
        _LORA_CACHE_META["sig"] = sig
        return out
    import struct
    for cur, _dirs, files in os.walk(root):
        for f in files:
            if not f.endswith(".safetensors"):
                continue
            rel = os.path.relpath(os.path.join(cur, f), root)
            key = rel.replace("/", "\\")
            arch, preset = "", ""
            fp = os.path.join(cur, f)
            try:
                with open(fp, "rb") as fh:
                    n = struct.unpack("<Q", fh.read(8))[0]
                    head = fh.read(n).decode("utf-8", "ignore")
                meta = (json.loads(head) or {}).get("__metadata__") or {}
                arch = str(meta.get("modelspec.architecture") or "").lower()
                preset = str(meta.get("ss_network_args") or "").lower()
            except Exception as e:
                warn("lora_header", e, rel)
            low = rel.lower()
            if "anima" in arch or "anima_full" in preset:
                base = "anima"
            elif "moss" in arch:
                base = "moss"
            elif "krea" in arch:
                base = "krea2"
            elif "stable-diffusion-xl" in arch:
                base = "other_xl"
            elif "stable-diffusion-v1" in arch:
                base = "anima" if "anima" in low else "other_xl"
            elif "moss" in low:
                base = "moss"
            elif re.search(r"(krea|k2)", low):
                base = "krea2"
            elif re.search(r"(_il\b|_il_|XL|illustrious|noob|other_xl)", low):
                base = "other_xl"
            elif "anima" in low:
                base = "anima"
            else:
                base = "unknown"
            out[key] = {"base": base, "arch": arch[:40]}
    ov_path = os.path.join(REF, "lora_base_overrides.json")
    if os.path.isfile(ov_path):
        try:
            with open(ov_path, encoding="utf-8") as f:
                ov = json.load(f) or {}
            for name, base in ov.items():
                if not name.startswith("_") and base and name in out:
                    out[name]["base"] = base
        except Exception as e:
            warn("lora_overrides", e, ov_path)
    _LORA_META_CACHE.clear()
    _LORA_META_CACHE.update(out)
    _LORA_CACHE_META["sig"] = sig
    return _LORA_META_CACHE


_HIDDEN_LORAS = {}


def list_loras():
    got = cf.models("loras")
    if got:
        return sorted(x for x in got if x.endswith(".safetensors") and x not in _HIDDEN_LORAS)
    d = _lora_dir()
    if not d:
        return []
    return sorted([x for x in os.listdir(d) if x.endswith(".safetensors") and x not in _HIDDEN_LORAS])


def dataset_samples(name):
    d = os.path.join(comfy_in(), name)
    n = 0
    for _, _, files in os.walk(d):
        n += len([f for f in files if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))])
    return n


def estimate_seconds(w, h, steps, batch=1, model=""):
    base = (w * h * steps * batch) * 1.60e-6 + 1.5
    if model and "29B" in str(model):
        base *= 2.8
    return round(base)


def _evict_jobs():
    if len(JOBS) <= JOBS_MAX:
        return
    done = [(j["started"], k) for k, j in JOBS.items() if j.get("status") != "running"]
    done.sort()
    for _, k in done[:max(0, len(JOBS) - JOBS_MAX)]:
        JOBS.pop(k, None)


def job_new(kind, label=""):
    MEM_LAST_JOB[0] = time.time()
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


def _running_jobs():
    return any(j.get("status") == "running" for j in JOBS.values())


def _memory_loop():
    """闲置回收与高 RAM 守护：委托 svc_mem.idle_tick 统一调度。"""
    import svc_mem
    while True:
        time.sleep(30)
        try:
            svc_mem.idle_tick(
                running_jobs=_running_jobs(),
                coop_running=(COOP_STATE.get("status") == "running"),
                last_job_ts=MEM_LAST_JOB[0],
            )
        except Exception as e:
            warn("memory_loop", e)


def registry_entries():
    return store.load_registry()


def expand_blocks(positive, negative):
    """展开正向/负向积木列表（含 @STRIP_* 脱除规则与杯子让路逻辑）。"""
    tokens, _, _ = load_tokens()
    strip_keys = getattr(pt, "STRIP_KEYS", set())
    strips = [b.token for b in list(positive) + list(negative)
              if b.enabled and (b.token or "") in strip_keys]
    strip_raw = " ".join(strips)
    unknown, rewrites = [], []
    stripped_any = [False]

    def render(blocks, do_strip=False):
        parts, used = [], []
        for b in blocks:
            if not b.enabled:
                continue
            raw = b.text or b.token
            if not raw:
                continue
            if (b.token or "") in strip_keys:
                continue
            ex, u = expand(raw, tokens)
            used.extend(u)
            resolved = pt.resolve_token(b.token)[0] if (b.token or "").startswith("@") else ""
            if resolved and resolved not in tokens and b.token in ex:
                unknown.append(b.token)
            if do_strip and strip_raw:
                ex2, _ = pt.apply_strips(ex, strip_raw, append_add=False)
                if ex2 != ex:
                    stripped_any[0] = True
                ex = ex2
            ex = ex.strip().strip(",")
            if not ex:
                continue
            if b.weight and abs(b.weight - 1.0) > 0.001:
                ex = "(%s:%s)" % (ex, b.weight)
            parts.append(ex)
        return ", ".join([p for p in parts if p]), sorted(set(used))

    pos, pos_used = render(positive, do_strip=bool(strip_raw))
    if strip_raw and strip_keys:
        for k, (_words, add) in getattr(pt, "STRIP_RULES", {}).items():
            if k in strips and add and add not in pos:
                pos = (pos + ", " + add) if pos else add
                stripped_any[0] = True
        if stripped_any[0]:
            msg = "脱除规则生效：" + ", ".join(sorted(set(strips)))
            rewrites.append({"rule": "strip", "tokens": sorted(set(strips)), "detail": msg})

    raw_pos = " ".join([(b.token or "") + " " + (b.text or "") for b in positive if b.enabled]).lower()
    cup_wanted = ("@hold_r_cup" in raw_pos or "@hold_l_cup" in raw_pos or ("holding" in raw_pos and "cup" in raw_pos))
    drinkware = ["cup", "mug", "teacup", "coffee cup", "saucer", "drinking glass",
                 "wine glass", "glass", "bottle", "holding a drink"]
    neg_blocks, notes = [], []
    if rewrites:
        notes.extend(r["detail"] for r in rewrites)
    removed_cup_tokens = []
    for b in negative:
        if not b.enabled:
            continue
        if cup_wanted and (b.token or "").upper() in ("@NEG_CUP", "@NEG_PROPS"):
            notes.append("已让路：负向移除了 " + (b.token or "杯子禁令") + "（你的正向要了杯子）")
            removed_cup_tokens.append(b.token or "")
            continue
        neg_blocks.append(b)
    neg, neg_used = render(neg_blocks)
    if cup_wanted:
        neg_before = neg
        for w in drinkware:
            neg = re.sub(r"(?i)(,\s*)?\b" + re.escape(w) + r"\b", "", neg)
        neg = re.sub(r"\s*,\s*(?=,)", "", neg).strip().strip(",").strip()
        rewrites.append({"rule": "cup_wanted", "removed_tokens": removed_cup_tokens,
                         "neg_changed": neg != neg_before, "detail": "正向含持杯意图，已让路清理负向饮具词"})
        if not removed_cup_tokens:
            notes.append("已让路：负向清掉了杯子相关词（正向要杯子）")
    if unknown:
        unk = sorted(set(unknown))
        notes.append("未识别宏（原样保留）：" + "、".join(unk))
        rewrites.append({"rule": "unknown_macro", "tokens": unk, "detail": "未识别宏原样保留"})
    return {"positive": pos, "negative": neg, "used": pos_used + neg_used,
            "pos_len": len(pos), "neg_len": len(neg), "notes": notes, "rewrites": rewrites}
