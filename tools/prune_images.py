# -*- coding: utf-8 -*-
"""图片清理：列出「超过 N 天 + 未登记」的候选，默认只预览。

用法:
  python tools/prune_images.py                 # 预览（30 天）
  python tools/prune_images.py --days 60       # 改阈值
  python tools/prune_images.py --apply         # 移到 _trash_prune（可恢复）
  python tools/prune_images.py --apply --delete  # 直接删除
"""
import argparse, json, os, shutil, sqlite3, time, datetime

ROOT = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = [
    os.path.join(ROOT, "SD-Picture", "station_out"),
    os.path.join(ROOT, "SD-Picture", "remote_out"),
    os.path.join(ROOT, "comfy", "ComfyUI", "output"),
]
TRASH = os.path.join(ROOT, "_trash_prune")
DB = os.path.join(ROOT, "station", "data", "station.db")
IMG = (".png", ".jpg", ".jpeg", ".webp")


def registered():
    names, paths = set(), set()
    try:
        con = sqlite3.connect(DB); cur = con.cursor()
        cur.execute("SELECT data FROM registry")
        for (d,) in cur.fetchall():
            try:
                j = json.loads(d)
            except Exception:
                continue
            f = j.get("file") or ""
            if f:
                names.add(os.path.basename(f).lower()); paths.add(os.path.realpath(f).lower())
        con.close()
    except Exception:
        pass
    return names, paths


def protected_dirs():
    return [os.path.realpath(p) for p in [
        os.path.join(ROOT, "产出作品", "images"),
        os.path.join(ROOT, "产出作品", "画师参考"),
        os.path.join(ROOT, "SD-Picture", "artist_free"),
        os.path.join(ROOT, "ref", "images"),
    ]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--limit", type=int, default=20)
    a = ap.parse_args()

    names, paths = registered()
    prot = protected_dirs()
    cutoff = time.time() - a.days * 86400
    cand, keep_reg, keep_new, keep_prot = [], 0, 0, 0
    for base in SCAN:
        if not os.path.isdir(base):
            continue
        for dp, _, fs in os.walk(base):
            rp = os.path.realpath(dp).lower()
            in_prot = any(rp.startswith(p.lower()) for p in prot)
            for f in fs:
                if not f.lower().endswith(IMG):
                    continue
                p = os.path.join(dp, f)
                try:
                    st = os.stat(p)
                except Exception:
                    continue
                if in_prot:
                    keep_prot += 1; continue
                if f.lower() in names or os.path.realpath(p).lower() in paths:
                    keep_reg += 1; continue
                if st.st_mtime > cutoff:
                    keep_new += 1; continue
                cand.append((st.st_size, st.st_mtime, p))

    cand.sort(reverse=True)
    total = sum(s for s, _, _ in cand)
    print("扫描目录:", ", ".join(SCAN))
    print("阈值: 早于 %d 天 | 候选 %d 个, %.0f MB" % (a.days, len(cand), total / 1048576))
    print("保留: 已登记 %d / 近期 %d / 保护目录 %d" % (keep_reg, keep_new, keep_prot))
    for s, mt, p in cand[:a.limit]:
        print("  %7.1f MB  %s  %s" % (s / 1048576, datetime.datetime.fromtimestamp(mt).strftime("%Y-%m-%d"), p))
    if not a.apply:
        print("\n预览模式。执行: python tools/prune_images.py --apply  （移到 _trash_prune）")
        return
    os.makedirs(TRASH, exist_ok=True)
    moved = 0
    for s, _, p in cand:
        try:
            if a.delete:
                os.remove(p)
            else:
                rel = os.path.relpath(p, ROOT).replace("\\", "__")
                shutil.move(p, os.path.join(TRASH, rel))
            moved += 1
        except Exception as e:
            print("失败", p, e)
    print("已处理 %d 个, 释放 %.0f MB" % (moved, total / 1048576))
    if not a.delete:
        print("文件在", TRASH, "，确认无误后可用 --delete 再跑一次或手动清空")


if __name__ == "__main__":
    main()
