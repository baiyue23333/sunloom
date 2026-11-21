# -*- coding: utf-8 -*-
"""结构审计修复：文件边界、请求准入、取消归属与存储单源。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch


def run(check, root, client):
    import routes_gallery as gallery
    import routes_jobs as routes
    import svc_paths as paths
    import svc_state as state
    import svc_tasks as tasks
    import svc_recipes as recipes
    from PIL import Image

    def file_boundaries():
        target = str(Path(root) / "README.md")
        assert client.get("/api/download", params={"path": target}).status_code == 403
        assert client.get("/api/doc", params={"path": target}).status_code == 403
        assert client.post("/api/export", json={"paths": [target]}).status_code == 403
        assert client.get("/api/gallery", params={"dir": "../../.."}).status_code == 403
        assert not paths.within("Z:/outside.png", ["A:/allowed"])
    check("文件边界：下载/文档/导出/画廊拒绝越界", file_boundaries)

    def valid_export():
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            src = base / "SD-Picture/station_out/test.png"
            src.parent.mkdir(parents=True)
            Image.new("RGB", (64, 64), "white").save(src)
            exports = base / "SD-Picture/exports"
            with patch.object(gallery, "ROOT", tmp), patch.object(gallery, "EXPORTS", str(exports)), \
                 patch.object(gallery, "img_allowed", side_effect=lambda p: paths.within(p, [str(src.parent)])):
                result = client.post("/api/export", json={"paths": [str(src)]})
                assert result.status_code == 200, result.text
                zipped = client.get("/api/download", params={"path": result.json()["zip"]})
                assert zipped.status_code == 200 and zipped.content.startswith(b"PK"), zipped.text[:80]
    check("文件边界：合法图片导出与 ZIP 下载仍可用", valid_export)

    def outputs_and_reference():
        from fastapi import HTTPException
        for name in ("../escape", "A:/escape", "station_out/../../escape"):
            try:
                paths.output_dir(name, create=False)
            except HTTPException as exc:
                assert exc.status_code in (400, 403)
            else:
                raise AssertionError("输出越界未拒绝: " + name)
        with tempfile.TemporaryDirectory() as tmp, patch.object(recipes, "comfy_in", return_value=tmp):
            try:
                recipes._prepare_reference(str(Path(root) / "README.md"))
            except HTTPException as exc:
                assert exc.status_code == 400
            else:
                raise AssertionError("非图片被拷入 Comfy input")
    check("文件边界：输出目录和底图类型受限", outputs_and_reference)

    def invalid_requests():
        bad = [dict(width=-8), dict(height=999999), dict(steps=-1), dict(cfg=-2),
               dict(width=513), dict(save_to="../../escape"), dict(mask="A:/outside.png", mode="inpaint")]
        with patch.object(routes, "threading") as threads, patch.object(routes, "comfy_in", return_value=tempfile.gettempdir()):
            for values in bad:
                response = client.post("/api/run", json=dict(prompt="audit", **values))
                assert response.status_code in (400, 422), (values, response.text)
            assert not threads.Thread.called
    check("请求准入：非法尺寸/步数/CFG/保存目录在建任务前拒绝", invalid_requests)

    def architecture():
        known = {"good.safetensors": {"base": "anima"}, "bad.safetensors": {"base": "krea2"}}
        with patch.object(state, "list_models", return_value=["anima-one.safetensors", "krea.safetensors"]), \
             patch.object(state, "list_loras", return_value=list(known)), patch.object(state, "_lora_base_map", return_value=known), \
             patch.object(routes, "threading") as threads, patch.object(routes, "comfy_in", return_value=tempfile.gettempdir()):
            for values in ({"model": "krea.safetensors"}, {"loras": [{"name": "bad.safetensors", "weight": 1}]}):
                response = client.post("/api/run", json=dict(prompt="audit", **values))
                assert response.status_code == 400, response.text
            assert not threads.Thread.called
            response = client.post("/api/run", json={"prompt": "audit", "model": "anima-one.safetensors",
                                                     "loras": [{"name": "good.safetensors", "weight": 0}]})
            assert response.status_code == 200, response.text
    check("请求准入：按架构拒绝底模/LoRA，零权重可禁用", architecture)

    def reproduction_model():
        model = "anima-selected.safetensors"
        with patch.object(state, "list_models", return_value=[model]), \
             patch.object(routes, "_prepare_reference", return_value="reference.png"), \
             patch.object(routes, "threading") as threads:
            result = routes.api_reproduce(routes.ReproReq(mode="keep_person", reference="source.png", model=model, prompt="audit"))
            target = threads.Thread.call_args.kwargs["target"]
            with patch.object(routes, "_submit") as submit:
                target()
                assert submit.call_args.args[1]["model"] == model
            assert result["job_id"]
    check("复现：选定底模传入执行器", reproduction_model)

    def cancellation():
        with patch.object(tasks.cf, "cancel_prompt", return_value=True) as cancel:
            assert client.post("/api/cancel/__unknown_repair__").status_code == 404
            assert not cancel.called
            jid = state.job_new("run", "cancel")
            state.JOBS[jid]["prompt_id"] = "owned-prompt"
            response = client.post("/api/cancel/" + jid)
            assert response.status_code == 200 and response.json()["status"] == "cancelled"
            cancel.assert_called_once_with("owned-prompt")
            tasks.finish(jid, "done", result={"images": ["later.png"]})
            assert state.JOBS[jid]["status"] == "cancelled"
            maintenance = state.job_new("train", "unsupported_cancel")
            cancel.reset_mock()
            assert client.post("/api/cancel/" + maintenance).status_code == 409
            assert not cancel.called and state.JOBS[maintenance]["status"] == "running"
    check("取消：未知 ID 不触发中断，取消后终态不被覆盖", cancellation)

    def targeted_transport():
        import comfy
        bodies = []

        class Reply:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"{}"

        def send(request, **kwargs):
            bodies.append((request.full_url.rsplit("/", 1)[-1], json.loads(request.data)))
            return Reply()

        with patch.object(comfy.urllib.request, "urlopen", side_effect=send):
            assert not comfy.interrupt()
            assert not bodies
            assert comfy.cancel_prompt("owned")
        assert ("queue", {"delete": ["owned"]}) in bodies
        assert ("interrupt", {"prompt_id": "owned"}) in bodies
    check("取消：HTTP 请求始终带 prompt 归属且无全局回退", targeted_transport)

    def nested_jobs():
        parent = state.job_new("handfix", "parent_http")
        with patch.object(routes, "threading"), patch.object(routes, "comfy_in", return_value=tempfile.gettempdir()):
            response = client.post("/api/run", json={"prompt": "audit", "parent_job_id": parent})
        assert response.status_code == 200, response.text
        child = response.json()["job_id"]
        assert state.JOBS[child]["parent_id"] == parent
        listed = client.get("/api/jobs?limit=120").json()["items"]
        assert next(item for item in listed if item["id"] == child)["parent_id"] == parent
        with patch.object(tasks.cf, "cancel_prompt", return_value=True):
            tasks.cancel(parent)
        assert state.JOBS[child]["status"] == "cancelled"
        with patch.object(routes, "threading") as threads:
            rejected = client.post("/api/run", json={"prompt": "audit", "parent_job_id": parent})
            assert rejected.status_code == 409 and not threads.Thread.called
    check("取消：嵌套精修任务继承父任务归属并拒绝取消后追加", nested_jobs)

    def import_order():
        rows = []
        for entry in ("routes_cards", "svc_state", "svc_obs"):
            code = ("import sys,os,json; from unittest.mock import patch; os.environ.pop('STATION_DB',None); "
                    "sys.path.insert(0," + repr(str(Path(root) / "station")) + "); "
                    "exec(\"with patch('sqlite3.connect'), patch('os.makedirs'):\\n import " + entry +
                    "\\n import store,core.store\\n print(json.dumps([store.DB,store is core.store]))\")")
            result = subprocess.run([sys.executable, "-B", "-c", code], cwd=root, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=20)
            assert result.returncode == 0, result.stderr
            rows.append(json.loads(result.stdout))
        assert all(same for _, same in rows), rows
        assert len({os.path.normcase(path) for path, _ in rows}) == 1, rows
        assert rows[0][0] == str(Path(root) / "station/data/station.db"), rows
    check("存储单源：不同导入顺序共用模块和 station.db", import_order)

    def routes_exact():
        import sys_check
        assert not sys_check.route_matches("/api/coop/not-a-route", "/api/coop/status")
        assert sys_check.route_matches("/api/job/abc", "/api/job/{jid}")
        assert not sys_check.route_matches("/api/job/abc/extra", "/api/job/{jid}")
        specs = [("/api/run", {"POST"})]
        assert sys_check.has_route("/api/run", "POST", specs)
        assert not sys_check.has_route("/api/run", "GET", specs)
    check("系统检查：完整路径与 HTTP 方法匹配", routes_exact)
