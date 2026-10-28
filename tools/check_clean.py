#!/usr/bin/env python3
"""Scan the repository for words that must never be published.

The word list is stored base64-encoded so that the public repository itself
does not contain those strings.

Usage: python tools/check_clean.py
"""
import base64
import json
import os
import sys

_WORDS_B64 = (
    "WyJzdW5oaW1pIiwgInN1bmZsb3dlciBoYWlyIiwgImhldGVyb2Nocm9taWEiLCAi5ZCR5pel6JG1"
    "IiwgIuW8guiJsueesyIsICLml6Xova7nu4fpgKAiLCAic2R4bCIsICI0MDkwIiwgImExMDAiLCAi"
    "aDEwMCIsICLnp5/ljaEiLCAi566X5Yqb56ef55SoIiwgInZhc3QuYWkiLCAicnVucG9kIl0="
)

ALLOW_EXT = {".py", ".js", ".html", ".css", ".json", ".md", ".ps1", ".txt", ".yml", ".yaml"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {"__pycache__", "output", ".git", "node_modules"}


def blocked_words():
    return json.loads(base64.b64decode("".join(_WORDS_B64)).decode("utf-8"))


def main():
    words = blocked_words()
    hits = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f == "check_clean.py" or f == ".gitignore":
                continue
            if os.path.splitext(f)[1].lower() not in ALLOW_EXT:
                continue
            p = os.path.join(base, f)
            try:
                text = open(p, encoding="utf-8", errors="ignore").read().lower()
            except Exception:
                continue
            for w in words:
                if w in text:
                    hits.append((os.path.relpath(p, ROOT), w))
    if hits:
        print("BLOCKED words found:")
        for p, w in hits:
            print("  %s  <- %s" % (p, w))
        return 1
    print("clean: no blocked words")
    return 0


if __name__ == "__main__":
    sys.exit(main())
