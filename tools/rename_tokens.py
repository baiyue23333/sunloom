# -*- coding: utf-8 -*-
"""把"只属于某个角色"的积木改名，并同步所有引用点。

2026-11-12：澪专属的身份/体型积木从通用名改成带归属的名字，
    @ID -> @ID_F、@ID_SOFT -> @ID_F_SOFT、@ID_TIGHT -> @ID_F_TIGHT、
    @ID_ADULT -> @ID_F_ADULT、@BODY -> @BODY_MIO

覆盖：prompt_lib（tokens/notes/meta）、角色卡、模板（JSON 导出 + SQLite）。
默认预演，加 --apply 才落盘。老配方不迁移：ref/prompts.py 的 ALIASES 负责展开兼容。

用法：
    python tools/rename_tokens.py            # 预演
    python tools/rename_tokens.py --apply    # 写入
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "ref")
LIB = os.path.join(REF, "prompt_lib.json")
CARDS = os.path.join(REF, "cards")
TPL_JSON = os.path.join(ROOT, "station", "data", "templates.json")
CARDS_JSON = os.path.join(ROOT, "station", "data", "cards.json")

RENAME = {
    "@ID": "@ID_F",
    "@ID_SOFT": "@ID_F_SOFT",
    "@ID_TIGHT": "@ID_F_TIGHT",
    "@ID_ADULT": "@ID_F_ADULT",
    "@BODY": "@BODY_MIO",
    "@BODY_B": "@BODY_MIO_B",
}


def _map(t):
    return RENAME.get(t, t)


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def _rename_blocks(items):
    """模板/配方里的 [{token:...}, ...] 列表。"""
    n = 0
    for b in items or []:
        if isinstance(b, dict):
            t = b.get("token")
            if t in RENAME:
                b["token"] = RENAME[t]
                n += 1
    return n


def do_library(apply):
    lib = _read(LIB, None)
    if lib is None:
        return 0
    hit = []
    toks = lib.get("tokens") or {}
    for old, new in RENAME.items():
        if old in toks:
            hit.append(old)
            toks[new] = toks.pop(old)
    notes = lib.get("notes") or {}
    for old, new in RENAME.items():
        if old in notes:
            notes[new] = notes.pop(old)
    meta = lib.get("meta") or {}
    for key in ("subgroups", "gender", "owner"):
        box = meta.get(key) or {}
        for old, new in RENAME.items():
            if old in box:
                box[new] = box.pop(old)
    changed = len(hit)
    print("prompt_lib.json: 停用旧名 %d 个 %s" % (changed, hit))
    if changed and apply:
        lib["tokens"], lib["notes"], lib["meta"] = toks, notes, meta
        _write(LIB, lib)
    return changed


def do_cards(apply):
    total = 0
    for p in sorted(glob.glob(os.path.join(CARDS, "*.json"))):
        d = _read(p, None)
        if not isinstance(d, dict):
            continue
        toks = d.get("tokens") or []
        hit = [t for t in toks if t in RENAME]
        if not hit:
            continue
        d["tokens"] = [_map(t) for t in toks]
        total += len(hit)
        print("角色卡 %s: %d 个 %s" % (os.path.basename(p), len(hit), hit))
        if apply:
            _write(p, d)
    return total


def do_templates_json(apply):
    d = _read(TPL_JSON, None)
    if d is None:
        return 0
    items = d if isinstance(d, list) else (d.get("items") or [])
    n = 0
    for t in items:
        n += _rename_blocks(t.get("positive"))
        n += _rename_blocks(t.get("negative"))
    print("templates.json: %d 处" % n)
    if n and apply:
        _write(TPL_JSON, d)
    return n


def do_cards_json(apply):
    d = _read(CARDS_JSON, None)
    if d is None:
        return 0
    items = d if isinstance(d, list) else (d.get("items") or [])
    n = 0
    for c in items:
        toks = c.get("tokens") or []
        if any(t in RENAME for t in toks):
            c["tokens"] = [_map(t) for t in toks]
            n += 1
    print("cards.json: %d 张卡" % n)
    if n and apply:
        _write(CARDS_JSON, d)
    return n


def do_sqlite(apply):
    os.environ.setdefault("STATION_DB", os.path.join(ROOT, "station", "data", "station.db"))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    try:
        from core import store
    except Exception as e:
        print("SQLite: 跳过（%s）" % e)
        return 0
    tp = store.load_templates()
    n = 0
    for t in tp:
        n += _rename_blocks(t.get("positive"))
        n += _rename_blocks(t.get("negative"))
    print("SQLite templates: %d 处" % n)
    if n and apply:
        store.save_templates(tp)

    cards = store.load_cards()
    m = 0
    for c in cards:
        toks = c.get("tokens") or []
        if any(t in RENAME for t in toks):
            c["tokens"] = [_map(t) for t in toks]
            m += 1
    print("SQLite cards: %d 张卡" % m)
    if m and apply:
        store.save_cards(cards)
    return n + m


def main():
    apply = "--apply" in sys.argv
    print("=== 积木改名（%s）" % ("应用" if apply else "预演，不改文件"))
    total = 0
    total += do_library(apply)
    total += do_cards(apply)
    total += do_templates_json(apply)
    total += do_cards_json(apply)
    total += do_sqlite(apply)
    print("=== 合计 %d 处%s" % (total, "" if apply else "（预演）"))
    if not apply and total:
        print("确认无误后：python tools/rename_tokens.py --apply")


if __name__ == "__main__":
    main()
