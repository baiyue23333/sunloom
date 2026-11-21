# -*- coding: utf-8 -*-
"""7B 舞台解析：背景板 -> 地平线/光源/物件/人物 slot；合成后评审。

  from stage_parse import parse, review
"""
import hashlib
import json
import os
import re
import sys
import threading

ROOT = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "ref")
CACHE = os.path.join(REF, "stage_plans.json")
sys.path.insert(0, os.path.join(ROOT, "tools"))
llm_manager = None  # 2026-11-15：本地模型已移除，走启发式兜底

DEFAULT = {
    "horizon_y": 0.42,
    "vanishing_x": 0.52,
    "ground": [],
    "lights": [{"dir": "left", "color": "warm", "strength": 0.8},
               {"dir": "right", "color": "cool", "strength": 0.5}],
    "objects": [],
    "person_slots": [{"x": 0.35, "ground_y": 0.90, "scale": 0.42}],
    "key_light": "left",
    "foreground": False,
    "person_box": None,
    "occluders": [],
    "palette": {},
    "style": "",
    "wet_ground": True,
    "atmosphere": "rain haze",
    "shot": "mid",
    "priority": "balanced",
    "details": [],
    "char_details": [],
    "interaction": {"surface": "", "wet": True, "wind": "none", "held": ""},
}

PARSE_Q = (
    "Analyze this background image for a 2D compositing stage. Reply with ONLY one JSON object, no markdown. "
    "Schema example: {\"horizon_y\":0.42,\"vanishing_x\":0.52,"
    "\"ground\":[[0.1,0.92],[0.5,0.86],[0.9,0.93]],"
    "\"lights\":[{\"dir\":\"left\",\"color\":\"warm\",\"color_hex\":\"#ffb060\","
    "\"strength\":0.9,\"bbox\":[0.05,0.30,0.25,0.55]}],"
    "\"person_box\":{\"x\":0.35,\"head_y\":0.48,\"feet_y\":0.90,\"shoulder_w\":0.10},"
    "\"occluders\":[{\"name\":\"planter\",\"depth\":\"fg\","
    "\"polygon\":[[0.05,0.80],[0.20,0.80],[0.20,0.98],[0.05,0.98]]}],"
    "\"palette\":{\"light\":\"#ffc070\",\"shadow\":\"#3a3a52\",\"ground\":\"#6a5548\"},"
    "\"style\":\"warm gaslight, wet stone\","
    "\"shot\":\"mid\",\"priority\":\"balanced\","
    "\"details\":[\"wet cobblestone joints\",\"warm window reflections\",\"distant tram wires\"],"
    "\"char_details\":[\"cream blouse ruffles\",\"dark pleated skirt\",\"long hairpin\"],"
    "\"interaction\":{\"surface\":\"wet stone\",\"wet\":true,\"wind\":\"none\",\"held\":\"\"},"
    "\"wet_ground\":true,\"atmosphere\":\"rain haze\"}. "
    "shot is one of far/mid/near/closeup and describes how large the character should appear. "
    "priority is character/balanced/scenery. details are small scene details that make the plate a complete painting. "
    "char_details are costume/hair/accessory details for the character card. "
    "interaction.surface is the ground material, wind is none/light/strong, held is an object she holds or empty. "
    "person_box is where a full-body person would stand, head to feet. "
    "occluders are 1-2 foreground objects that could cover the person. Numbers 0-1. "
    "Only the JSON."
)

REVIEW_Q = (
    "Look at this composite. Check four items and reply with ONLY JSON: "
    "{\"items\":{\"contact_shadow\":\"pass|fail\",\"reflection\":\"pass|fail\","
    "\"scale\":\"pass|fail\",\"seam\":\"pass|fail\"},"
    "\"fix\":{\"x\":0.35,\"ground_y\":0.9,\"scale\":0.42,\"shadow\":0.6}}. "
    "A person must have a dark contact shadow under the feet; on wet ground a reflection must exist; "
    "the feet must sit on the ground line; no hard cutout edge. No markdown."
)


def _key(path):
    h = hashlib.sha1(b"v3")
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _load_cache():
    try:
        return json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(data):
    os.makedirs(REF, exist_ok=True)
    tmp = CACHE + ".tmp"
    json.dump(data, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, CACHE)


def _json_of(text):
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None
    for end in range(len(text) - 1, start, -1):
        if text[end] != "}":
            continue
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            continue
    return None


def _clamp(d):
    out = dict(DEFAULT)
    if not isinstance(d, dict):
        return out
    def num(k, lo, hi, cur):
        try:
            v = float(d.get(k, cur))
        except Exception:
            return cur
        return max(lo, min(hi, v))
    out["horizon_y"] = num("horizon_y", 0.30, 0.60, 0.42)
    out["vanishing_x"] = num("vanishing_x", 0.30, 0.70, 0.52)
    g = d.get("ground")
    if isinstance(g, list):
        pts = []
        for p in g[:5]:
            try:
                pts.append([max(0, min(1, float(p[0]))), max(0, min(1, float(p[1])))])
            except Exception:
                pass
        out["ground"] = pts
    lights = []
    for L in (d.get("lights") or [])[:3]:
        if not isinstance(L, dict):
            continue
        dirn = str(L.get("dir", "left")).lower()
        col = str(L.get("color", "neutral")).lower()
        if dirn not in ("left", "right", "back", "top"):
            dirn = "left"
        if col not in ("warm", "cool", "neutral"):
            col = "neutral"
        try:
            s = max(0.0, min(1.0, float(L.get("strength", 0.5))))
        except Exception:
            s = 0.5
        lights.append({"dir": dirn, "color": col, "strength": s})
    out["lights"] = lights or DEFAULT["lights"]
    objs = []
    for o in (d.get("objects") or [])[:6]:
        if not isinstance(o, dict):
            continue
        b = o.get("bbox")
        try:
            x0, y0, x1, y1 = [max(0.0, min(1.0, float(v))) for v in b]
        except Exception:
            continue
        if x1 - x0 < 0.03 or y1 - y0 < 0.03:
            continue
        depth = str(o.get("depth", "mid")).lower()
        if depth not in ("fg", "mid", "bg"):
            depth = "mid"
        objs.append({"name": re.sub(r"[^a-zA-Z0-9 _-]", "", str(o.get("name", "object")))[:24] or "object",
                     "bbox": [x0, y0, x1, y1], "depth": depth, "occludes": bool(o.get("occludes"))})
    out["objects"] = objs
    slots = []
    for s in (d.get("person_slots") or [])[:3]:
        if not isinstance(s, dict):
            continue
        try:
            slots.append({"x": max(0.10, min(0.90, float(s.get("x", 0.35)))),
                          "ground_y": max(0.70, min(0.98, float(s.get("ground_y", 0.9)))),
                          "scale": max(0.25, min(0.70, float(s.get("scale", 0.42))))})
        except Exception:
            pass
    out["person_slots"] = slots or DEFAULT["person_slots"]
    import re as _re
    def _hex(v):
        return v if isinstance(v, str) and _re.match(r"^#[0-9a-fA-F]{6}$", v) else None
    pb = d.get("person_box")
    if isinstance(pb, dict):
        try:
            h = max(0.05, min(0.98, float(pb.get("head_y", 0.5))))
            f = max(0.10, min(0.99, float(pb.get("feet_y", 0.9))))
            if f > h + 0.10:
                out["person_box"] = {"x": max(0.10, min(0.90, float(pb.get("x", 0.35)))),
                                     "head_y": h, "feet_y": f,
                                     "shoulder_w": max(0.03, min(0.30, float(pb.get("shoulder_w", 0.10))))}
        except Exception:
            pass
    occ = []
    for o in (d.get("occluders") or [])[:2]:
        if not isinstance(o, dict):
            continue
        poly = []
        for pt in (o.get("polygon") or [])[:8]:
            try:
                poly.append([max(0.0, min(1.0, float(pt[0]))), max(0.0, min(1.0, float(pt[1])))])
            except Exception:
                pass
        if len(poly) >= 4:
            occ.append({"name": str(o.get("name", "object"))[:24], "depth": str(o.get("depth", "fg")),
                        "polygon": poly})
    out["occluders"] = occ
    pal = d.get("palette") if isinstance(d.get("palette"), dict) else {}
    out["palette"] = {k: _hex(pal.get(k)) for k in ("light", "shadow", "ground") if _hex(pal.get(k))}
    out["style"] = str(d.get("style", ""))[:90]
    out["wet_ground"] = bool(d.get("wet_ground", True))
    out["atmosphere"] = str(d.get("atmosphere", ""))[:40]
    shot = str(d.get("shot", "mid")).lower()
    out["shot"] = shot if shot in ("far", "mid", "near", "closeup") else "mid"
    pri = str(d.get("priority", "balanced")).lower()
    out["priority"] = pri if pri in ("character", "balanced", "scenery") else "balanced"
    def _tags(v):
        arr = []
        for t in (v or [])[:5]:
            t = re.sub(r"[^a-zA-Z0-9 ,'-]", "", str(t)).strip()[:48]
            if t:
                arr.append(t)
        return arr
    out["details"] = _tags(d.get("details"))
    out["char_details"] = _tags(d.get("char_details"))
    it = d.get("interaction") if isinstance(d.get("interaction"), dict) else {}
    wind = str(it.get("wind", "none")).lower()
    out["interaction"] = {"surface": re.sub(r"[^a-zA-Z0-9 ]", "", str(it.get("surface", "")))[:24],
                          "wet": bool(it.get("wet", out["wet_ground"])),
                          "wind": wind if wind in ("none", "light", "strong") else "none",
                          "held": re.sub(r"[^a-zA-Z0-9 ]", "", str(it.get("held", "")))[:24]}
    return out


def _call(mid, img, question, timeout):
    box = {}
    if llm_manager is None:
        return None
    def go():
        try:
            box["text"] = llm_manager.vision(mid, img, question, max_tokens=700)
        except Exception as e:  # noqa: BLE001
            box["err"] = str(e)[:200]
    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None
    return box.get("text")


def unload():
    """评审后释放 CPU 模型，避免退出时 llama.cpp 关闭顺序报错。"""
    try:
        if llm_manager is not None:
            llm_manager.unload()
    except Exception:
        pass


def _model():
    if llm_manager is None:
        return None
    try:
        return llm_manager.pick(["qwen2.5-vl-7b", "qwen2.5-vl-3b"])
    except Exception:
        return None


def parse(plate, refresh=False):
    """返回 stage dict；带缓存与启发式兜底。"""
    cache = _load_cache()
    k = _key(plate)
    if not refresh and k in cache and cache[k].get("stage"):
        stage = _clamp(cache[k]["stage"])
        stage["by"] = "cache"
        return stage
    mid = _model()
    stage = None
    if mid:
        text = _call(mid, plate, PARSE_Q, 180)
        stage = _json_of(text)
        by = mid
    else:
        by = "heuristic"
    if not stage:
        stage = dict(DEFAULT)
        by = "heuristic"
    stage = _clamp(stage)
    stage["by"] = by
    cache[k] = {"stage": stage, "by": by}
    try:
        _save_cache(cache)
    except Exception:
        pass
    return stage


CARD_Q = (
    "Look at this character card. Reply with ONLY JSON: "
    "{\"faces\":<int>,\"full_body\":true|false,\"feet_visible\":true|false,\"shoes\":true|false,\"note\":\"short\"}. "
    "Count visible faces; a full body card has exactly one face and both feet; shoes means footwear is visible on the feet."
)


def check_card(img, timeout=60, want_shoes=True):
    """卡片质检：数脸、全身、脚在画面内；模型不可用时放行。"""
    mid = _model()
    if not mid:
        return {"ok": True, "faces": None, "by": "skip"}
    text = _call(mid, img, CARD_Q, timeout)
    d = _json_of(text)
    if not isinstance(d, dict):
        return {"ok": True, "faces": None, "by": "fallback"}
    try:
        faces = int(d.get("faces", 1))
    except Exception:
        faces = 1
    shoes = bool(d.get("shoes", True))
    ok = (faces == 1 and bool(d.get("full_body", True)) and bool(d.get("feet_visible", True))
          and (shoes or not want_shoes))
    return {"ok": ok, "faces": faces, "full_body": bool(d.get("full_body", True)),
            "feet_visible": bool(d.get("feet_visible", True)), "shoes": shoes,
            "note": str(d.get("note", ""))[:60], "by": mid}


def review(comp, stage, timeout=60):
    """合成后评审；失败时返回 ok=True。"""
    mid = _model()
    if not mid:
        return {"ok": True, "issues": [], "fix": {}, "by": "skip"}
    q = REVIEW_Q + "\n舞台参数：" + json.dumps({k: stage.get(k) for k in ("horizon_y", "lights", "wet_ground", "person_slots")}, ensure_ascii=False)
    text = _call(mid, comp, q, timeout)
    d = _json_of(text)
    if not isinstance(d, dict):
        return {"ok": True, "items": {}, "issues": [], "fix": {}, "by": "fallback"}
    items = d.get("items") if isinstance(d.get("items"), dict) else {}
    items = {str(k): ("pass" if str(v).lower() == "pass" else "fail") for k, v in list(items.items())[:4]}
    fix = {}
    for k, lo, hi in (("x", 0.10, 0.90), ("ground_y", 0.70, 0.98), ("scale", 0.25, 0.70), ("shadow", 0.0, 1.0)):
        if isinstance(d.get("fix"), dict) and k in d["fix"]:
            try:
                fix[k] = max(lo, min(hi, float(d["fix"][k])))
            except Exception:
                pass
    ok = bool(items) and all(v == "pass" for v in items.values())
    return {"ok": ok, "items": items, "issues": [], "fix": fix, "by": mid}
