# -*- coding: utf-8 -*-
"""项目搬家后，把库里记录的绝对路径重映射到当前项目根。

  python tools/fix_paths.py            # 预演（默认）
  python tools/fix_paths.py --apply    # 真写

处理：station/data/recipes.json（键）、station/data/station.db（recipes.path、registry.data.file）、
      station/data/pose_cache.json（键）。旧根一律按 "\sunloom\" / "\dsh\" 之后的部分接到当前 ROOT。
"""
import argparse, json, os, re, sqlite3, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "station", "data")
MARKERS = ("/sunloom/", "/dsh/", "/dsh/workflow/sunloom/")


def remap(p):
    """旧绝对路径 -> 当前 ROOT 下的路径；不是旧根就原样返回。"""
    if not p:
        return p
    q = p.replace("\\", "/")
    if q.lower().startswith(ROOT.replace("\\", "/").lower() + "/"):
        return p
    for m in MARKERS:
        i = q.find(m)
        if i >= 0:
            rest = q[i + len(m):]
            return os.path.normpath(os.path.join(ROOT, rest.replace("/", os.sep)))
    return p


def fix_recipes_json(apply):
    fp = os.path.join(DATA, "recipes.json")
    db = json.load(open(fp, encoding="utf-8"))
    out, moved, clash = {}, 0, 0
    for k, v in db.items():
        nk = remap(k)
        if nk != k:
            moved += 1
        if nk in out:
            clash += 1
            if (v.get("ts") or 0) <= (out[nk].get("ts") or 0):
                continue
        out[nk] = v
    live = sum(1 for k in out if os.path.isfile(k))
    print("recipes.json: %d -> %d 条，改路径 %d，撞键 %d，现存 %d" % (len(db), len(out), moved, clash, live))
    if apply:
        json.dump(out, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
    return moved


def fix_db(apply):
    fp = os.path.join(DATA, "station.db")
    c = sqlite3.connect(fp)
    rows = list(c.execute("select path from recipes"))
    changes = [(remap(p), p) for (p,) in rows if remap(p) != p]
    print("station.db recipes: %d 条，改 %d" % (len(rows), len(changes)))
    reg = list(c.execute("select id, data from registry"))
    regchg = []
    for i, dat in reg:
        try:
            o = json.loads(dat)
        except Exception:
            continue
        f = o.get("file")
        if f and remap(f) != f:
            o["file"] = remap(f)
            regchg.append((i, json.dumps(o, ensure_ascii=False)))
    print("station.db registry: %d 条，改 %d" % (len(reg), len(regchg)))
    if apply:
        for new, old in changes:
            c.execute("update recipes set path=? where path=?", (new, old))
        for i, dat in regchg:
            c.execute("update registry set data=? where id=?", (dat, i))
        c.commit()
    return len(changes) + len(regchg)


def fix_pose_cache(apply):
    fp = os.path.join(DATA, "pose_cache.json")
    if not os.path.isfile(fp):
        return 0
    d = json.load(open(fp, encoding="utf-8"))
    out, moved = {}, 0
    for k, v in d.items():
        parts = k.split("|", 1)
        nk = remap(parts[0]) + ("|" + parts[1] if len(parts) > 1 else "")
        if nk != k:
            moved += 1
        out[nk] = v
    print("pose_cache.json: %d 条，改 %d" % (len(d), moved))
    if apply and moved:
        json.dump(out, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
    return moved


def _sd_index():
    """SD-Picture 下 png 文件名 -> 路径列表（用于找回被挪走的图）。"""
    idx = {}
    for dp, _, fs in os.walk(os.path.join(ROOT, "SD-Picture")):
        for f in fs:
            if f.lower().endswith(".png"):
                idx.setdefault(f, []).append(os.path.join(dp, f))
    return idx


def repair_missing(apply):
    """路径存在但文件已经不在原处 -> 按唯一文件名找回；重名的不动，免得指错图。"""
    idx = _sd_index()

    def look(p):
        if not p or os.path.isfile(p):
            return p
        cands = idx.get(os.path.basename(p.replace("\\", "/")))
        if not cands or len(cands) > 1:
            return p
        return cands[0]

    fp = os.path.join(DATA, "recipes.json")
    db = json.load(open(fp, encoding="utf-8"))
    out, n = {}, 0
    for k, v in db.items():
        nk = look(k)
        if nk != k:
            n += 1
        if nk in out and (v.get("ts") or 0) <= (out[nk].get("ts") or 0):
            continue
        out[nk] = v
    print("recipes.json 找回: %d（现存 %d/%d）" % (n, sum(1 for k in out if os.path.isfile(k)), len(out)))
    if apply and n:
        json.dump(out, open(fp, "w", encoding="utf-8"), ensure_ascii=False)

    fp = os.path.join(DATA, "station.db")
    c = sqlite3.connect(fp)
    rows = [p for (p,) in c.execute("select path from recipes")]
    chg = [(look(p), p) for p in rows if look(p) != p]
    print("station.db 找回: %d（现存 %d/%d）" % (len(chg), sum(1 for p in rows if os.path.isfile(look(p))), len(rows)))
    reg = list(c.execute("select id, data from registry"))
    regchg = []
    for i, dat in reg:
        try:
            o = json.loads(dat)
        except Exception:
            continue
        f0 = o.get("file")
        f1 = look(f0)
        if f0 and f1 != f0:
            o["file"] = f1
            regchg.append((i, json.dumps(o, ensure_ascii=False)))
    print("registry 找回: %d" % len(regchg))
    if apply:
        for new, old in chg:
            c.execute("update recipes set path=? where path=?", (new, old))
        for i, dat in regchg:
            c.execute("update registry set data=? where id=?", (dat, i))
        c.commit()
    return n + len(chg) + len(regchg)


def fix_artist_index(apply):
    """画师悬停预览的样张索引：前缀重映射 + 按文件名找回（文件常在别的子目录）。"""
    idx = _sd_index()
    total_fixed = 0
    for fn in ("artist_index_char.json", "artist_index_env.json", "artist_free_index.json"):
        p = os.path.join(ROOT, "ref", fn)
        if not os.path.isfile(p):
            continue
        d = json.load(open(p, encoding="utf-8"))
        fixed = 0
        for k, entry in d.items():
            if not isinstance(entry, dict):
                continue
            for w, path in list(entry.items()):
                if not path or os.path.isfile(path):
                    continue
                np = remap(path)
                if not os.path.isfile(np):
                    cands = idx.get(os.path.basename(str(np).replace("\\", "/")))
                    if cands and len(cands) == 1:
                        np = cands[0]
                if np != path and os.path.isfile(np):
                    entry[w] = np
                    fixed += 1
        print("%s: 修 %d 条" % (fn, fixed))
        if apply and fixed:
            json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        total_fixed += fixed
    return total_fixed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真写库（默认只预演）")
    a = ap.parse_args()
    print("ROOT =", ROOT)
    print("模式 =", "APPLY" if a.apply else "预演")
    total = fix_recipes_json(a.apply) + fix_db(a.apply) + fix_pose_cache(a.apply)
    total += repair_missing(a.apply)
    total += fix_artist_index(a.apply)
    print("合计改动 %d 处" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
