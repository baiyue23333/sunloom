# -*- coding: utf-8 -*-
"""合作成品画廊过滤与中间件清理。"""
import os, shutil, sys, tempfile


def run(check, ROOT):
    def _coop_gallery():
        sys.path.insert(0, os.path.join(ROOT, "station"))
        import server
        assert server._is_final_name("comp.png") and not server._is_final_name("bg.png")
        assert not server._is_final_name("char_raw.png") and not server._is_final_name("_layer_00.png")
        tmp = tempfile.mkdtemp()
        try:
            for n in ("comp.png", "bg.png", "char.png", "comp_raw.png", "plate.png", "contract.json"):
                open(os.path.join(tmp, n), "w").write("x")
            server._cleanup_coop_dir(tmp, os.path.join(tmp, "comp.png"))
            assert sorted(os.listdir(tmp)) == ["comp.png", "contract.json"], "中间件没清干净"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        finals = server._coop_finals()
        assert all(os.path.basename(p) in ("comp.png", "final.png") for _, p in finals), "画廊混入中间件"

    check("合作成品：画廊过滤/清理", _coop_gallery)
