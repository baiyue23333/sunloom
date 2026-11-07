# -*- coding: utf-8 -*-
"""提示词库快照/回滚。

用法：
  python tools/prompt_lib_snapshot.py save "备注"
  python tools/prompt_lib_snapshot.py list
  python tools/prompt_lib_snapshot.py restore <快照文件名>
"""
import hashlib, json, os, shutil, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "ref", "prompt_lib.json")
DIR = os.path.join(ROOT, "ref", "prompt_lib_versions")
INDEX = os.path.join(DIR, "index.json")


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def _load_index():
    if os.path.isfile(INDEX):
        return json.load(open(INDEX, encoding="utf-8"))
    return []


def save(note=""):
    os.makedirs(DIR, exist_ok=True)
    data = json.load(open(LIB, encoding="utf-8"))
    stamp = time.strftime("%Y%m%d_%H%M%S")
    name = "lib_%s_%s.json" % (stamp, _sha(LIB))
    shutil.copy2(LIB, os.path.join(DIR, name))
    idx = _load_index()
    idx.append({"file": name, "time": stamp, "note": note,
                "tokens": len(data.get("tokens", {})), "sha": _sha(LIB)})
    json.dump(idx, open(INDEX, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("saved", name, "tokens", len(data.get("tokens", {})))


def list_versions():
    for item in _load_index():
        print(item["file"], "|", item["time"], "|", item["tokens"], "tokens |", item["note"])


def restore(name):
    src = os.path.join(DIR, name)
    if not os.path.isfile(src):
        raise SystemExit("找不到快照：" + name)
    shutil.copy2(LIB, LIB + ".before-restore")
    shutil.copy2(src, LIB)
    print("restored", name, "(旧文件备份为 prompt_lib.json.before-restore)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "save"
    if cmd == "save":
        save(sys.argv[2] if len(sys.argv) > 2 else "")
    elif cmd == "list":
        list_versions()
    elif cmd == "restore" and len(sys.argv) > 2:
        restore(sys.argv[2])
    else:
        print(__doc__)
