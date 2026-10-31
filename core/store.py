# -*- coding: utf-8 -*-
"""SQLite 存储层：配方 / 登记 / 模板 / 角色卡。

- 首次使用会从旧的 JSON 文件导入一次（kv 表打标记，不会重复导入）
- 之后 JSON 只是导出格式，读写都走数据库（事务、并发安全）
- 可用 STATION_DB 环境变量指定库文件（测试用临时库）
"""
import json
import os
import sqlite3
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("STATION_DB") or os.path.join(HERE, "data", "station.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (path TEXT PRIMARY KEY, ts REAL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS registry (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS templates (name TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cards (name TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""

_LOCK = threading.RLock()
_INITED = False
_PATHS = {}


def set_db(path):
    """显式指定库文件（在 init 之前调用）。"""
    global DB
    DB = path


def init(recipes_json="", registry_jsonl="", templates_json="", cards_json=""):
    """登记旧文件位置并确保表存在 / 完成一次性导入。"""
    global _INITED
    with _LOCK:
        _PATHS.update({
            "recipes": recipes_json, "registry": registry_jsonl,
            "templates": templates_json, "cards": cards_json,
        })
        con = _conn()
        con.close()
        if not _INITED:
            _migrate()
            _INITED = True


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _conn():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB, timeout=20)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SCHEMA)
    return con


def _json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _migrate():
    con = _conn()
    try:
        row = con.execute("SELECT v FROM kv WHERE k='imported'").fetchone()
        if row:
            return
        rec = _PATHS.get("recipes")
        if rec and os.path.isfile(rec):
            db = _json(rec, {}) or {}
            con.executemany("INSERT OR REPLACE INTO recipes(path, ts, data) VALUES(?,?,?)",
                            [(p, _num(r.get("ts")), json.dumps(r, ensure_ascii=False))
                             for p, r in db.items()])
        reg = _PATHS.get("registry")
        if reg and os.path.isfile(reg):
            with open(reg, encoding="utf-8") as f:
                rows = []
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    rows.append((_num(obj.get("ts")), json.dumps(obj, ensure_ascii=False)))
            con.executemany("INSERT INTO registry(ts, data) VALUES(?,?)", rows)
        tpl = _PATHS.get("templates")
        if tpl and os.path.isfile(tpl):
            items = _json(tpl, []) or []
            con.executemany("INSERT OR REPLACE INTO templates(name, data) VALUES(?,?)",
                            [(str(i.get("name") or ("tpl-%d" % n)), json.dumps(i, ensure_ascii=False))
                             for n, i in enumerate(items)])
        cards = _PATHS.get("cards")
        if cards and os.path.isfile(cards):
            items = _json(cards, []) or []
            con.executemany("INSERT OR REPLACE INTO cards(name, data) VALUES(?,?)",
                            [(str(i.get("name") or ("card-%d" % n)), json.dumps(i, ensure_ascii=False))
                             for n, i in enumerate(items)])
        con.execute("INSERT INTO kv(k, v) VALUES('imported', '1')")
        con.commit()
    finally:
        con.close()


# ---------- recipes ----------
def load_recipes():
    con = _conn()
    try:
        rows = con.execute("SELECT path, data FROM recipes").fetchall()
    finally:
        con.close()
    out = {}
    for path, data in rows:
        try:
            out[path] = json.loads(data)
        except Exception:
            continue
    return out


def save_recipes(db):
    con = _conn()
    try:
        con.execute("DELETE FROM recipes")
        con.executemany("INSERT INTO recipes(path, ts, data) VALUES(?,?,?)",
                        [(p, _num((r or {}).get("ts")), json.dumps(r, ensure_ascii=False))
                         for p, r in (db or {}).items()])
        con.commit()
    finally:
        con.close()


def upsert_recipe(path, obj):
    con = _conn()
    try:
        con.execute("INSERT OR REPLACE INTO recipes(path, ts, data) VALUES(?,?,?)",
                    (path, _num((obj or {}).get("ts")), json.dumps(obj, ensure_ascii=False)))
        con.commit()
    finally:
        con.close()


def get_recipe(path):
    con = _conn()
    try:
        row = con.execute("SELECT data FROM recipes WHERE path=?", (path,)).fetchone()
    finally:
        con.close()
    return json.loads(row[0]) if row else None


# ---------- registry ----------
def load_registry():
    con = _conn()
    try:
        rows = con.execute("SELECT data FROM registry ORDER BY id").fetchall()
    finally:
        con.close()
    out = []
    for (data,) in rows:
        try:
            out.append(json.loads(data))
        except Exception:
            pass
    return out


def append_registry(obj, ts=None):
    con = _conn()
    try:
        con.execute("INSERT INTO registry(ts, data) VALUES(?,?)",
                    (_num(ts if ts is not None else (obj or {}).get("ts")),
                     json.dumps(obj, ensure_ascii=False)))
        con.commit()
    finally:
        con.close()


# ---------- templates ----------
def load_templates():
    con = _conn()
    try:
        rows = con.execute("SELECT data FROM templates ORDER BY rowid").fetchall()
    finally:
        con.close()
    out = []
    for (data,) in rows:
        try:
            out.append(json.loads(data))
        except Exception:
            pass
    return out


def save_templates(items):
    con = _conn()
    try:
        con.execute("DELETE FROM templates")
        con.executemany("INSERT OR REPLACE INTO templates(name, data) VALUES(?,?)",
                        [(str(i.get("name") or ("tpl-%d" % n)), json.dumps(i, ensure_ascii=False))
                         for n, i in enumerate(items or [])])
        con.commit()
    finally:
        con.close()


# ---------- cards ----------
def load_cards():
    con = _conn()
    try:
        rows = con.execute("SELECT data FROM cards ORDER BY rowid").fetchall()
    finally:
        con.close()
    out = []
    for (data,) in rows:
        try:
            out.append(json.loads(data))
        except Exception:
            pass
    return out


def save_cards(items):
    con = _conn()
    try:
        con.execute("DELETE FROM cards")
        con.executemany("INSERT OR REPLACE INTO cards(name, data) VALUES(?,?)",
                        [(str(i.get("name") or ("card-%d" % n)), json.dumps(i, ensure_ascii=False))
                         for n, i in enumerate(items or [])])
        con.commit()
    finally:
        con.close()
