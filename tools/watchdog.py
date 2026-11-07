# -*- coding: utf-8 -*-
"""SUNLOOM 看护进程：8770（工作站）/ 8188（ComfyUI）掉线自动拉起。"""
import os, socket, subprocess, sys, time, datetime

ROOT = r"A:/workflow/dsh"
PY = r"C:/Users/A2870/AppData/Local/Programs/Python/Python310/python.exe"
COMFY_PY = os.path.join(ROOT, "comfy", "venv", "Scripts", "python.exe")
COMFY_WD = os.path.join(ROOT, "comfy", "ComfyUI")
LOG = os.path.join(ROOT, "logs")
LOCK = os.path.join(LOG, "watchdog.lock")

def log(msg):
    os.makedirs(LOG, exist_ok=True)
    with open(os.path.join(LOG, "watchdog.log"), "a", encoding="utf-8") as f:
        f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "  " + msg + "\n")

def up(port):
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=2)
        s.close()
        return True
    except Exception:
        return False

def start_comfy():
    os.makedirs(LOG, exist_ok=True)
    out = open(os.path.join(ROOT, "comfy", "comfy_start.log"), "ab")
    subprocess.Popen([COMFY_PY, "main.py", "--listen", "127.0.0.1", "--port", "8188",
                      "--reserve-vram", "0.6", "--disable-auto-launch",
                      "--preview-method", "none", "--dont-print-server"],
                     cwd=COMFY_WD, stdout=out, stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log("started ComfyUI (8188)")

def start_station():
    os.makedirs(LOG, exist_ok=True)
    out = open(os.path.join(LOG, "station.log"), "ab")
    subprocess.Popen([PY, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8770", "--no-access-log"],
                     cwd=os.path.join(ROOT, "station"), stdout=out, stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log("started station (8770)")

def main():
    os.makedirs(LOG, exist_ok=True)
    if os.path.exists(LOCK):
        try:
            other = int(open(LOCK).read().strip())
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, other)
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                print("watchdog already running", other)
                return
        except Exception:
            pass
    open(LOCK, "w").write(str(os.getpid()))
    log("watchdog started pid=%d" % os.getpid())
    cool = {"comfy": 0.0, "station": 0.0}
    while True:
        now = time.time()
        if not up(8188) and now - cool["comfy"] > 150:
            cool["comfy"] = now
            try: start_comfy()
            except Exception as e: log("comfy start failed: %s" % e)
        if not up(8770) and now - cool["station"] > 60:
            cool["station"] = now
            try: start_station()
            except Exception as e: log("station start failed: %s" % e)
        time.sleep(20)

if __name__ == "__main__":
    main()
