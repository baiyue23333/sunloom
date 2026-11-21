
# -*- coding: utf-8 -*-
"""pipeline_check.py - 统一管线体检（命令行与工作站共用同一份逻辑）"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
COMFY = os.environ.get("STATION_COMFY", "http://127.0.0.1:8188")


def _load_tokens():
    lib = json.load(open(os.path.join(HERE, "prompt_lib.json"), encoding="utf-8"))
    tokens = dict(lib.get("tokens") or {})
    ch = json.load(open(os.path.join(HERE, "character.json"), encoding="utf-8"))
    for key, g in (ch.get("garments") or {}).items():
        if g.get("prompt"):
            tokens["@OUT_" + key.upper()] = g["prompt"]
        if g.get("negative"):
            tokens["@NEG_" + key.upper()] = g["negative"]
    return tokens, ch


def _expand(text, tokens):
    try:
        import prompts as _p
        return _p.expand(text, tokens)
    except Exception:
        out, used = text, []
        for k, v in sorted(tokens.items(), key=lambda kv: -len(kv[0])):
            if k in out and v:
                pat = re.escape(k) + r"(?![A-Za-z0-9_])"
                if re.search(pat, out):
                    out = re.sub(pat, lambda _m, _v=v: _v, out)
                    used.append(k)
        return out, used


def _comfy_up():
    try:
        with urllib.request.urlopen(COMFY + "/system_stats", timeout=4) as r:
            d = json.loads(r.read().decode())
        return True, d.get("system", {}).get("comfyui_version", "?")
    except Exception:
        return False, None


def start_comfy(wait=80):
    if _comfy_up()[0]:
        return True, "ComfyUI 已运行"
    com = os.path.join(ROOT, "comfy")
    py = os.path.join(com, "venv", "Scripts", "python.exe")
    wd = os.path.join(com, "ComfyUI")
    if not os.path.isfile(py):
        desktop_exe = os.environ.get("COMFY_DESKTOP_EXE") or os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "Programs", "ComfyUI", "ComfyUI.exe"
        )
        if not os.path.isfile(desktop_exe):
            return False, "当前使用 Comfy Desktop（未内置本地 venv），请手动启动 ComfyUI Desktop 监听 8188"
        subprocess.Popen([desktop_exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        lock = os.path.join(com, ".autostart.lock")
        try:
            if os.path.exists(lock) and time.time() - os.path.getmtime(lock) < 120:
                return False, "启动冷却中（120 秒内已尝试过）"
            with open(lock, "w") as f:
                f.write(str(time.time()))
        except Exception:
            pass
        args = [py, "main.py", "--listen", "127.0.0.1", "--port", "8188",
                "--reserve-vram", "0.6", "--disable-auto-launch"]
        subprocess.Popen(args, cwd=wd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    t0 = time.time()
    while time.time() - t0 < wait:
        time.sleep(2)
        if _comfy_up()[0]:
            return True, "ComfyUI 已就绪（%.0fs）" % (time.time() - t0)
    return False, "启动后 %d 秒内未就绪" % wait


def run_checks():
    checks = []

    def add(cid, name, ok, detail, fix=""):
        checks.append({"id": cid, "name": name, "ok": bool(ok), "detail": detail, "fix": fix})

    # 1 提示词库
    try:
        tokens, ch = _load_tokens()
        add("tokens", "提示词积木库", len(tokens) >= 20, "已加载 %d 块积木" % len(tokens),
            "检查 ref/prompt_lib.json 是否合法 JSON，可在词库页保存一次")
    except Exception as e:
        tokens, ch = {}, {}
        add("tokens", "提示词积木库", False, "读取失败: %s" % e,
            "确认 ref/prompt_lib.json 存在；损坏时从 产出作品 目录恢复")

    # 2 服装
    try:
        g = (ch or {}).get("garments") or {}
        ok = all(k in g and g[k].get("prompt") for k in ("slip", "casual_knit"))
        add("garments", "两套服装", ok,
            "slip %d 字符 / casual_knit %d 字符" % (len(g.get("slip", {}).get("prompt", "")),
                                                len(g.get("casual_knit", {}).get("prompt", ""))),
            "在 词库→服装 补全文案后保存")
    except Exception as e:
        add("garments", "两套服装", False, str(e), "检查 ref/character.json 的 garments")

    # 3 宏展开
    try:
        # 2026-11-12：澪的身份/体型积木改名，自检也跟着用新名
        out, used = _expand("@SINGLE_F, @CAM_BUST, @ID_F, @OUT_GENERIC, @DRAPE_WORN, @BODY_F, @FACE_F", tokens)
        left = re.findall(r"@[A-Z_]+", out)
        add("expand", "宏展开", not left,
            "展开 %d 字符，命中 %d 个宏%s" % (len(out), len(used),
                                             ("，残留 " + ",".join(left[:5])) if left else ""),
            "残留宏表示未定义：在词库新建同名积木，或从模板移除")
    except Exception as e:
        add("expand", "宏展开", False, str(e), "用命令行 expand.py 复现")

    # 4 ComfyUI
    up, ver = _comfy_up()
    add("comfy", "ComfyUI 服务", up, ("版本 " + str(ver)) if up else "未连接 " + COMFY,
        "启动 ComfyUI Desktop 或运行 python ref/check_all.py --fix")

    # 5 模型（优先问 ComfyUI 的 /models，搬家后仍然准）
    try:
        import sys
        tools_dir = os.path.join(ROOT, "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import comfy_paths
        roots = comfy_paths.comfy_models_dirs()

        def _comfy_models(sub):
            try:
                import urllib.request as _u
                with _u.urlopen("http://127.0.0.1:8188/models/" + sub, timeout=6) as r:
                    import json as _j
                    return [x for x in _j.loads(r.read().decode()) if isinstance(x, str)]
            except Exception:
                return []

        need = [("diffusion_models", "anima-base-v1.0.safetensors", "主模型"),
                ("text_encoders", "qwen_3_06b_base.safetensors", "文本编码器"),
                ("vae", "qwen_image_vae.safetensors", "VAE")]
        miss = []
        for sub, fn, label in need:
            got = _comfy_models(sub)
            if got:
                if fn not in got:
                    miss.append(label)
            elif not any(os.path.isfile(os.path.join(r, sub, fn)) for r in roots):
                miss.append(label)
        add("models", "anima 三件套", not miss,
            ("缺失 " + "、".join(miss)) if miss else "主模型/文本编码器/VAE 齐全",
            "把缺失文件放进 ComfyUI models 对应子目录")
    except Exception as e:
        add("models", "anima 三件套", False, str(e), "检查 models 目录")

    # 6 LoRA
    try:
        try:
            import urllib.request as _u
            import json as _j
            with _u.urlopen("http://127.0.0.1:8188/models/loras", timeout=6) as r:
                loras = sorted(x for x in _j.loads(r.read().decode()) if isinstance(x, str) and x.endswith(".safetensors"))
        except Exception:
            loras = []
            for r in roots:
                d = os.path.join(r, "loras")
                if os.path.isdir(d):
                    loras = sorted(x for x in os.listdir(d) if x.endswith(".safetensors"))
                    break
        has = any("local_char_lora_h2" in x for x in loras)
        add("loras", "身份 LoRA", has,
            ("共 %d 个，含 local_char_lora_h2" % len(loras)) if has else "未找到 local_char_lora_h2",
            "把 local_char_lora_h2.safetensors 放进 models/loras")
    except Exception as e:
        add("loras", "身份 LoRA", False, str(e), "检查 models/loras")

    # 7 输出目录
    out_dir = os.path.join(ROOT, "SD-Picture", "station_out")
    try:
        os.makedirs(out_dir, exist_ok=True)
        probe = os.path.join(out_dir, ".write_probe")
        open(probe, "w").write("ok")
        os.remove(probe)
        add("outdir", "输出目录", True, out_dir, "")
    except Exception as e:
        add("outdir", "输出目录", False, str(e), "确认 SD-Picture/station_out 可写")

    # 8 登记
    try:
        reg = os.path.join(HERE, "registry.jsonl")
        n = 0
        bad = 0
        if os.path.exists(reg):
            for line in open(reg, encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                n += 1
                try:
                    json.loads(line)
                except Exception:
                    bad += 1
        add("registry", "采用登记", bad == 0, "%d 条%s" % (n, ("，%d 行损坏" % bad) if bad else ""),
            "修复或删除 registry.jsonl 里损坏的行")
    except Exception as e:
        add("registry", "采用登记", False, str(e), "检查 ref/registry.jsonl")

    # 9 磁盘
    try:
        free = shutil.disk_usage(ROOT).free / 1073741824
        add("disk", "磁盘空间", free > 5, "可用 %.1f GB" % free, "维护页清理，或删旧实验图")
    except Exception as e:
        add("disk", "磁盘空间", False, str(e), "检查磁盘挂载")

    # 10/11 脚本
    for cid, name, fn in (("train", "训练脚本", "train_lora.py"), ("tag", "打标脚本", "tag_wd14.py")):
        pth = os.path.join(HERE, fn)
        add(cid, name, os.path.isfile(pth), pth, "确认 ref/%s 存在" % fn)

    bad = [c for c in checks if not c["ok"]]
    return {"checks": checks, "ok": not bad, "failed": len(bad), "total": len(checks)}

