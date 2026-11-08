# -*- coding: utf-8 -*-
"""一键启动：看护 + 工作站(8770) + ComfyUI(8188)，已在跑的跳过。
不依赖 .bat，可被快捷方式直接调用（pythonw tools/launch_all.py）。
"""
import os, socket, subprocess, sys, time, webbrowser

ROOT = r"A:/workflow/dsh"
PY = r"C:/Users/A2870/AppData/Local/Programs/Python/Python310/python.exe"
PYW = r"C:/Users/A2870/AppData/Local/Programs/Python/Python310/pythonw.exe"
COMFY_PY = os.path.join(ROOT, "comfy", "venv", "Scripts", "python.exe")
COMFY_WD = os.path.join(ROOT, "comfy", "ComfyUI")
LOG = os.path.join(ROOT, "logs")

def up(port):
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=1.5)
        s.close()
        return True
    except Exception:
        return False

def spawn(args, cwd, logname):
    os.makedirs(LOG, exist_ok=True)
    out = open(os.path.join(LOG, logname), "ab")
    subprocess.Popen(args, cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

def main():
    # 看护
    try:
        if not os.path.exists(os.path.join(LOG, "watchdog.lock")):
            spawn([PYW, os.path.join(ROOT, "tools", "watchdog.py")], ROOT, "watchdog.out")
    except Exception:
        pass
    # 工作站
    if not up(8770):
        spawn([PY, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8770", "--no-access-log"],
              os.path.join(ROOT, "station"), "station.log")
        time.sleep(2)
    # ComfyUI
    if not up(8188):
        spawn([COMFY_PY, "main.py", "--listen", "127.0.0.1", "--port", "8188",
               "--reserve-vram", "0.6", "--disable-auto-launch",
               "--preview-method", "none", "--dont-print-server"], COMFY_WD, "comfy_start.log")
        for _ in range(45):
            time.sleep(2)
            if up(8188):
                break
    # 打开页面
    try:
        webbrowser.open("http://127.0.0.1:8770/")
    except Exception:
        pass
    print("launch ok: station", up(8770), "comfy", up(8188))

if __name__ == "__main__":
    main()
