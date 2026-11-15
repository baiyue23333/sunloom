# -*- coding: utf-8 -*-
"""发布前洁净检查：确认仓库中没有敏感词、私钥文件、权重文件或私人路径。"""
import base64
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BLOCKED_B64 = [
  "c3VuaGltaQ==",
  "c3VuZmxvd2VyIGhhaXI=",
  "aGV0ZXJvY2hyb21pYQ==",
  "5ZCR5pel6JG1",
  "5byC6Imy556z",
  "5pel6L2u57uH6YCg",
  "c2R4bA==",
  "NDA5MA==",
  "YTEwMA==",
  "aDEwMA==",
  "56ef5Y2h",
  "566X5Yqb56ef55So",
  "dmFzdC5haQ==",
  "cnVucG9k",
  "c2VldGFjbG91ZA==",
  "YW5pbWFOYWk=",
  "c2lsdmVyIHBhbGFjZQ==",
  "THVjZW50IEJsb29t",
  "Qmx1ZUFyY2hpdmVTdHlsZUIx",
  "a2FuemFyaW4=",
  "YXNoaW1h",
  "a291a291eWE=",
  "a2EtOTk2YmVzaGk=",
  "cGFpbnRlcmx5LXYy",
  "U2tpbl9FbmhhbmNlcg==",
  "aXZvcnkgd2hpdGUgaGFpcg==",
  "56+g5a6u",
  "44G/44GK",
  "aWRfZl9taW8=",
  "Ym9keV9mX21pbw==",
  "bWlvX2JhY2s=",
  "aWRfbWlv",
  "c3RyaXBfc3VuZmxvd2Vy",
  "bmVnX2Zsb3dlcg==",
  "cHJvcF9zdW5mbG93ZXI=",
  "b3V0X2luaXRpYWw=",
  "bmVnX2luaXRpYWw=",
  "QTpcXHdvcmtmbG93"
]
BLOCKED = [base64.b64decode(x).decode("utf-8") for x in _BLOCKED_B64]
SKIP_DIRS = {".git", "__pycache__", "node_modules", "SD-Picture", "产出作品", "workspace"}
SKIP_FILES = {"check_clean.py"}
BINARY_EXTS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".onnx", ".gguf")
TEXT_EXTS = (".py", ".js", ".mjs", ".html", ".css", ".json", ".md", ".txt", ".ps1", ".bat", ".yaml", ".yml", ".toml")


def main():
    hits = []
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = [x for x in dns if x not in SKIP_DIRS]
        for fn in fns:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, ROOT)
            low = fn.lower()
            if low in SKIP_FILES:
                continue
            if low.endswith(BINARY_EXTS) or rel.replace("\\", "/") == "ref/remote.json":
                hits.append(f"{rel}: forbidden file")
                continue
            if not low.endswith(TEXT_EXTS):
                continue
            try:
                txt = open(p, "r", encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            low_txt = txt.lower()
            for b in BLOCKED:
                if b.lower() in low_txt:
                    hits.append(f"{rel}: matched {b!r}")
    if hits:
        print("FAILED privacy check:")
        for h in hits[:60]:
            print(" ", h)
        return 1
    print("clean: no blocked words or private artifacts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
