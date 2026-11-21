# -*- coding: utf-8 -*-
"""SQLite 存储层：配方 / 登记 / 模板 / 角色卡。

- 首次使用会从旧的 JSON 文件导入一次（kv 表打标记，不会重复导入）
- 之后 JSON 只是导出格式，读写都走数据库（事务、并发安全）
- 可用 STATION_DB 环境变量指定库文件（测试用临时库）
"""
import json
import os
import sqlite3
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("STATION_DB") or os.path.join(os.path.dirname(HERE), "station", "data", "station.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (path TEXT PRIMARY KEY, ts REAL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS registry (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS templates (name TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cards (name TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS jobs_history (id TEXT PRIMARY KEY, ts REAL, kind TEXT, status TEXT, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS coop_runs (id TEXT PRIMARY KEY, ts REAL, mode TEXT, status TEXT, out_dir TEXT, final_image TEXT, data TEXT NOT NULL);
"""

_LOCK = threading.RLock()
_INITED = False
_PATHS = {}
_WARN_HOOK = None


def set_warn_hook(fn):
    """注册异常告警回调（由 station/svc_obs 注入，避免循环依赖）。"""
    global _WARN_HOOK
    _WARN_HOOK = fn


def _notify_warn(where, exc, detail=""):
    if _WARN_HOOK is not None:
        try:
            _WARN_HOOK(where, exc, detail)
            return
        except Exception:
            pass
    try:
        sys.stderr.write(f"[store:{where}] {exc} {detail}\n")
    except Exception:
        pass


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
    if not path or not os.path.isfile(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _notify_warn("store_json", e, path)
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
        except Exception as e:
            _notify_warn("load_recipes_row", e, path)
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


def trim_recipes(max_count=400):
    """按 ts 保留最新的 max_count 条配方，删掉超出的旧记录并返回被删条数。"""
    con = _conn()
    try:
        cur = con.execute(
            "DELETE FROM recipes WHERE path IN ("
            "SELECT path FROM recipes ORDER BY ts DESC, path DESC LIMIT -1 OFFSET ?)",
            (int(max_count),),
        )
        con.commit()
        return cur.rowcount or 0
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
        except Exception as e:
            _notify_warn("load_registry_row", e)
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
        rows = con.execute("SELECT name, data FROM templates ORDER BY rowid").fetchall()
    finally:
        con.close()
    out = []
    for name, data in rows:
        try:
            out.append(json.loads(data))
        except Exception as e:
            _notify_warn("load_templates_row", e, name)
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
        rows = con.execute("SELECT name, data FROM cards ORDER BY rowid").fetchall()
    finally:
        con.close()
    out = []
    for name, data in rows:
        try:
            out.append(json.loads(data))
        except Exception as e:
            _notify_warn("load_cards_row", e, name)
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


# ---------- jobs_history & coop_runs ----------
def upsert_job(job_dict):
    if not isinstance(job_dict, dict) or not job_dict.get("id"):
        return
    con = _conn()
    try:
        con.execute(
            "INSERT OR REPLACE INTO jobs_history(id, ts, kind, status, data) VALUES(?,?,?,?,?)",
            (str(job_dict["id"]), _num(job_dict.get("started") or job_dict.get("ts")),
             str(job_dict.get("kind") or ""), str(job_dict.get("status") or ""),
             json.dumps(job_dict, ensure_ascii=False)),
        )
        con.commit()
    finally:
        con.close()


def trim_jobs(max_count=120):
    con = _conn()
    try:
        cur = con.execute(
            "DELETE FROM jobs_history WHERE id IN ("
            "SELECT id FROM jobs_history ORDER BY ts DESC, id DESC LIMIT -1 OFFSET ?)",
            (int(max_count),),
        )
        con.commit()
        return cur.rowcount or 0
    finally:
        con.close()


def load_jobs(limit=120):
    con = _conn()
    try:
        rows = con.execute(
            "SELECT id, data FROM jobs_history ORDER BY ts DESC, id DESC LIMIT ?", (int(limit),)
        ).fetchall()
    finally:
        con.close()
    out = []
    for jid, data in rows:
        try:
            out.append(json.loads(data))
        except Exception as e:
            _notify_warn("load_jobs_row", e, jid)
    return out


def upsert_coop_run(run_dict):
    if not isinstance(run_dict, dict) or not run_dict.get("id"):
        return
    con = _conn()
    try:
        con.execute(
            "INSERT OR REPLACE INTO coop_runs(id, ts, mode, status, out_dir, final_image, data) VALUES(?,?,?,?,?,?,?)",
            (str(run_dict["id"]), _num(run_dict.get("started") or run_dict.get("ts")),
             str(run_dict.get("mode") or ""), str(run_dict.get("status") or ""),
             str(run_dict.get("dir") or ""), str(run_dict.get("image") or ""),
             json.dumps(run_dict, ensure_ascii=False)),
        )
        con.commit()
    finally:
        con.close()


def trim_coop_runs(max_count=60):
    con = _conn()
    try:
        cur = con.execute(
            "DELETE FROM coop_runs WHERE id IN ("
            "SELECT id FROM coop_runs ORDER BY ts DESC, id DESC LIMIT -1 OFFSET ?)",
            (int(max_count),),
        )
        con.commit()
        return cur.rowcount or 0
    finally:
        con.close()


def load_coop_runs(limit=40):
    con = _conn()
    try:
        rows = con.execute(
            "SELECT id, data FROM coop_runs ORDER BY ts DESC, id DESC LIMIT ?", (int(limit),)
        ).fetchall()
    finally:
        con.close()
    out = []
    for rid, data in rows:
        try:
            out.append(json.loads(data))
        except Exception as e:
            _notify_warn("load_coop_runs_row", e, rid)
    return out


def table_counts():
    con = _conn()
    try:
        out = {}
        for tbl in ("recipes", "registry", "templates", "cards", "jobs_history", "coop_runs"):
            out[tbl] = int(con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0])
        return out
    finally:
        con.close()


def export_snapshots(recipes_json="", templates_json="", cards_json=""):
    """显式把 SQLite 最新数据导出到 JSON 快照，消除遗留 JSON 与数据库的计数漂移。"""
    written = {}
    targets = [
        ("recipes", recipes_json, load_recipes),
        ("templates", templates_json, load_templates),
        ("cards", cards_json, load_cards),
    ]
    for name, path, loader in targets:
        if not path:
            continue
        data = loader()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=(2 if name != "recipes" else None))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        written[name] = len(data)
    return written
