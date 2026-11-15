# -*- coding: utf-8 -*-
"""server.py - SUNLOOM 站台 FastAPI 装配入口（业务路由已拆分到 routes_* / svc_* 模块）。"""
import os
import sys
import threading
import time

# pythonw 下 stdout/stderr 是 None，先接到日志文件，否则 uvicorn 一启动就崩
_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "server.log")
if sys.stdout is None or sys.stderr is None:
    os.makedirs(os.path.dirname(_LOG), exist_ok=True)
    _f = open(_LOG, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _f
    sys.stderr = sys.stderr or _f
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import routes_cards  # noqa: E402
import routes_coop  # noqa: E402
import routes_gallery  # noqa: E402
import routes_hand  # noqa: E402
import routes_jobs  # noqa: E402
import routes_library  # noqa: E402
import routes_maint  # noqa: E402
import routes_mem  # noqa: E402
import routes_promptlib  # noqa: E402
from svc_recipes import (  # noqa: E402, F401
    _fit_mask_to_reference,
    _make_mask,
    _match_blocks,
    _normalize_mask,
    _parse_png_recipe,
    _prepare_reference,
    add_recipe,
    mirror_score,
)
from svc_state import (  # noqa: E402, F401
    JOBS,
    JOBS_MAX,
    _memory_loop,
    expand,
    job_new,
    load_tokens,
    read_json,
    write_json,
)

# 兼容现有测试（tests/coop_gallery_tests.py、tests/run_tests.py）对 server.* 内部符号的直接导入
_is_final_name = routes_gallery._is_final_name
_coop_finals = routes_gallery._coop_finals
_cleanup_coop_dir = routes_coop._cleanup_coop_dir
run_regress = routes_jobs.run_regress
comfy_supervisor = routes_maint.comfy_supervisor

app = FastAPI(title="Station")
for _mod in (
    routes_cards,
    routes_promptlib,
    routes_jobs,
    routes_coop,
    routes_gallery,
    routes_hand,
    routes_library,
    routes_maint,
    routes_mem,
):
    app.include_router(_mod.router)

app.mount("/", StaticFiles(directory=os.path.join(HERE, "static"), html=True), name="static")

if __name__ == "__main__":
    import socket
    import webbrowser
    import uvicorn

    _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _busy = _s.connect_ex(("127.0.0.1", 8770)) == 0
    _s.close()
    if _busy:
        print("LOOM: server already running on http://127.0.0.1:8770/")
        webbrowser.open("http://127.0.0.1:8770/")
        raise SystemExit(0)

    if os.environ.get("STATION_NO_SUPERVISOR") != "1":
        threading.Thread(target=comfy_supervisor, daemon=True).start()

    def _open():
        time.sleep(1.5)
        webbrowser.open("http://127.0.0.1:8770/")

    threading.Thread(target=_open, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8770, log_level="warning")

try:
    threading.Thread(target=_memory_loop, daemon=True, name="mem-idle").start()
except Exception:
    pass
