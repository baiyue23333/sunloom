# -*- coding: utf-8 -*-
"""文件大小闸门：代码文件 >20KB 直接失败；文档只告警不拦。

  python tools/check_sizes.py
"""
import argparse, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMIT = 20 * 1024
CODE_EXTS = (".py", ".js", ".mjs", ".html", ".css", ".bat")
DOC_EXTS = (".md", ".json")
# ComfyUI-NSFW-PromptSelector 是外来的 ComfyUI 节点仓库（整份 vendored），不是第一方代码，
# 20KB 拆文件规则对它不适用，和 node_modules 一样跳过。
SKIP_DIRS = {"comfy", "SD-Picture", "_attic", "scratch", "models", "node_modules",
             "__pycache__", ".git", "_backups", "_archive", "plugins", "data", "image-annotator",
             "ComfyUI-NSFW-PromptSelector"}
EXEMPT = {"station/static/index.html", "station/static/style.css", "station/static/app.js"}
SKIP_FILES = {"package-lock.json", "pnpm-lock.yaml", "artist_free_index.json"}


def scan():
    code, docs = [], []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f in SKIP_FILES:
                continue
            ext = os.path.splitext(f)[1].lower()
            if ext not in CODE_EXTS and ext not in DOC_EXTS:
                continue
            p = os.path.join(base, f)
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            if size <= LIMIT:
                continue
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            item = (rel, size)
            if rel in EXEMPT:
                docs.append(item)
                continue
            (code if ext in CODE_EXTS else docs).append(item)
    return code, docs


def staged():
    """只查 git 暂存的新增/修改文件；代码超标返回 1，文档只告警。"""
    try:
        out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        print("check_sizes: 读取暂存区失败:", e)
        return 1
    code, docs = [], []
    for rel in [x.strip() for x in out.splitlines() if x.strip()]:
        rel = rel.replace("\\", "/")
        parts = rel.split("/")
        if any(d in SKIP_DIRS for d in parts[:-1]) or os.path.basename(rel) in SKIP_FILES:
            continue
        ext = os.path.splitext(rel)[1].lower()
        if ext not in CODE_EXTS and ext not in DOC_EXTS:
            continue
        p = os.path.join(ROOT, rel)
        try:
            size = os.path.getsize(p)
        except OSError:
            continue
        if size <= LIMIT:
            continue
        if rel in EXEMPT:
            continue
        (code if ext in CODE_EXTS else docs).append((rel, size))
    for rel, size in sorted(code, key=lambda x: -x[1]):
        print("OVERSIZE  %-58s %6.1f KB（>20KB）" % (rel, size / 1024))
    for rel, size in sorted(docs, key=lambda x: -x[1]):
        print("DOC-BIG   %-58s %6.1f KB（只告警）" % (rel, size / 1024))
    if code:
        print("\n提交被拦：%d 个代码文件超过 20KB，按功能拆文件后重新 git add。" % len(code))
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--staged", action="store_true", help="只检查 git 暂存区（pre-commit 用）")
    a = ap.parse_args()
    if a.staged:
        return staged()
    code, docs = scan()
    for path, size in sorted(code + docs, key=lambda x: -x[1]):
        tag = "OVERSIZE" if (path, size) in code else "DOC-BIG "
        print("%s  %-58s %6.1f KB" % (tag, path, size / 1024))
    if code:
        print("\n代码文件超标 %d 个：按功能拆文件后再提交。" % len(code))
        return 1
    if docs and not a.quiet:
        print("\n文档超标 %d 个（只告警，不拦）：需要时拆册。" % len(docs))
    print("SIZES OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
