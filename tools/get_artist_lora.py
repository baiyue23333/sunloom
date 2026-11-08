# -*- coding: utf-8 -*-
"""从 Civitai 拉一个画师 LoRA 并跑通：下载 → 校验 → 装进 ComfyUI → 出三档样张。

用法：
  python tools/get_artist_lora.py --url "https://civitai.com/models/1478417?modelVersionId=2955844"
  python tools/get_artist_lora.py --version 2955844 --token <API_TOKEN>
  python tools/get_artist_lora.py --url ... --dry-run

环境变量 CIVITAI_TOKEN 也可提供 token（私有/需登录的模型）。
"""
import argparse, json, os, re, subprocess, sys, urllib.request

ROOT = r"A:/workflow/dsh"
LORA_DIR = os.path.join(ROOT, "comfy", "ComfyUI", "models", "loras")
API = "https://civitai.com/api/v1/model-versions/%s"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SUNLOOM/1.0"
PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or "http://127.0.0.1:7897"


def opener():
    h = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    return urllib.request.build_opener(h)


def parse_version(url):
    m = re.search(r"modelVersionId=(\d+)", url or "")
    if m:
        return m.group(1)
    m = re.search(r"/api/download/models/(\d+)", url or "")
    return m.group(1) if m else None


def fetch_meta(version, token):
    req = urllib.request.Request(API % version, headers={"User-Agent": UA})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with opener().open(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def pick_file(meta):
    files = meta.get("files") or []
    for f in files:
        if str(f.get("name", "")).lower().endswith(".safetensors"):
            return f
    return files[0] if files else None


def download(version, token, dest):
    # 用 curl 跟随重定向（urllib 跨域会丢 Authorization，导致拿到登录页）
    url0 = "https://civitai.com/api/download/models/%s" % version
    cmd = ["curl", "-sL", "--proxy", PROXY, "-o", dest + ".part", "-w", "%{http_code} %{content_type}", url0]
    if token:
        cmd[3:3] = ["-H", "Authorization: Bearer " + token]
    print("  下载中…")
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit("curl 失败：" + (out.stderr or "")[:200])
    code, _, ctype = (out.stdout or "").partition(" ")
    if "html" in ctype.lower():
        raise SystemExit("下载到登录页（HTTP %s），token 无效或已过期。" % code)
    os.replace(dest + ".part", dest)
    return dest


def _old_download(version, token, dest):
    url = "https://civitai.com/api/download/models/%s" % version
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    tmp = dest + ".part"
    try:
        resp = opener().open(req, timeout=120)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise SystemExit("Civitai 返回 %d：需要 API token。到 civitai.com → Account settings → API Keys 生成，"
                             "然后 --token <KEY> 或设置环境变量 CIVITAI_TOKEN。" % e.code)
        raise
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "text/html" in ctype:
        raise SystemExit("下载到的是登录页（Content-Type: text/html），请提供 API token 后重试。")
    with resp as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                sys.stdout.write("\r  %5.1f%%  %d/%d MB" % (done * 100.0 / total, done >> 20, total >> 20))
                sys.stdout.flush()
    print()
    os.replace(tmp, dest)
    return dest


def check_safetensors(path):
    with open(path, "rb") as f:
        head = f.read(8)
    n = int.from_bytes(head, "little")
    return 0 < n < 200 * 1024 * 1024


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    ap.add_argument("--version", default="")
    ap.add_argument("--token", default=os.environ.get("CIVITAI_TOKEN", ""))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    ver = a.version or parse_version(a.url)
    if not ver:
        sys.exit("需要 --url（带 modelVersionId）或 --version")
    try:
        meta = fetch_meta(ver, a.token)
        f = pick_file(meta) or {}
        name = f.get("name") or ("lora_%s.safetensors" % ver)
        print("模型：", meta.get("modelName") or (meta.get("model") or {}).get("name", ""))
        print("版本：", meta.get("name"), "| 基底：", meta.get("baseModel"))
        print("文件：", name, "%.0f MB" % ((f.get("sizeKB") or 0) / 1024.0))
    except Exception as e:
        print("查询元数据失败（可能被墙/需要登录）：", e)
        name = "lora_%s.safetensors" % ver
        print("将直接按版本号下载，文件名暂定：", name)
    if a.dry_run:
        return
    os.makedirs(LORA_DIR, exist_ok=True)
    dest = os.path.join(LORA_DIR, name)
    if os.path.isfile(dest) and os.path.getsize(dest) > 1024 * 1024:
        print("已存在，跳过下载：", dest)
    else:
        download(ver, a.token, dest)
    if not check_safetensors(dest):
        sys.exit("文件不是合法 safetensors，可能下载失败或被登录拦截")
    print("已安装：", dest)
    print("下一步：python tools/artist_free_samples.py  （会为新画师补 0.6/1.0/1.3 样张）")


if __name__ == "__main__":
    main()
