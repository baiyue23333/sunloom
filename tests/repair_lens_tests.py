# -*- coding: utf-8 -*-
"""B 线修复契约：零值、实际提示词、失败门禁与重试血缘。"""
import argparse
import json
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch


def run(check, root):
    import coop_reproject as cr
    import coop_lens_first as line
    import lens_policy as policy
    from PIL import Image

    def zeros():
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"env_weight": 0, "char_weight": 0, "scene_lora": "scene", "char_lora": "char",
                       "x": 0, "ground_y": 0, "cfg": 0}, f)
            filename = f.name
        try:
            cfg = cr._load_cfg(argparse.Namespace(config=filename, scene="s", char="c", seed=1, width=512, height=512))
            assert all(cfg[key] == 0 for key in ("env_weight", "char_weight", "x", "ground_y", "cfg")), cfg
            assert cfg["scene_lora"] == cfg["char_lora"] == ""
        finally:
            Path(filename).unlink()
    check("合作参数：零权重/CFG/坐标不被默认值覆盖", zeros)

    def weighted_clauses():
        token = "@COMP_FIGURE_SMALL"
        plan = policy.build_lens_plan({"lens_spec": {"comp_tokens": [{"token": token, "weight": 1.4}]}})
        text = policy.phrase(token, 1.4)
        body = policy.body_prompt("1girl, " + text, plan)
        assert text not in body and "one fifth" not in body, body
        partial = policy.strip_phrases("(keep this, drop this:1.4)", ["drop this"])
        assert partial == "(keep this:1.4)", partial
    check("镜头分流：加权多子句可剥除且保留剩余权重", weighted_clauses)

    def real_plate():
        gaze = policy.tokens()["@GAZE_CAMERA"]
        plan = policy.build_lens_plan({"lens_spec": {"cam_tokens": [{"token": "@CAM_PROFILE"}],
                                                    "gaze_tokens": [{"token": "@GAZE_CAMERA"}]}})
        prompt = policy.plate_prompt("a cafe, (" + gaze + ":1.4)", plan)
        assert plan["suppress_look"] and gaze not in prompt, prompt
        natural = policy.plate_prompt("a cafe, 1girl", policy.build_lens_plan({}))
        assert policy.CANDID in natural, natural
        for token in ("@GAZE_CAMERA", "@GAZE_DOWN"):
            p = policy.build_lens_plan({"lens_spec": {"gaze_tokens": [{"token": token}]}})
            assert not p["candid"], p
    check("镜头出板：最终提示词落实对视抑制与自然朝向", real_plate)

    class Plan:
        def schedule(self, *args, **kwargs):
            pass

        def trim_py(self, *args, **kwargs):
            pass

    def fixture(folder):
        p1, p2 = Path(folder) / "original.png", Path(folder) / "retry.png"
        Image.new("RGB", (64, 64), "white").save(p1)
        Image.new("RGB", (64, 64), "black").save(p2)
        cfg = {"width": 64, "height": 64, "env_steps": 12, "char_steps": 12, "steps": 12,
               "cfg": 5.5, "seed": 10, "model": "", "scene_lora": "scene", "char_lora": "char", "char_weight": 0.85,
               "x": 0.34, "ground_y": 0.88, "ratio": 0, "char": "1girl, standing"}
        return p1, p2, cfg

    def gate():
        with tempfile.TemporaryDirectory() as tmp:
            p1, p2, cfg = fixture(tmp)
            manifest = {"steps": []}
            repaint = Mock(return_value=str(p1))
            with patch.object(line, "_plate", side_effect=[str(p1), str(p2)]), \
                 patch.object(line.parts, "detect_safe", return_value={}), patch.object(line, "_body_cov", return_value=0), \
                 patch.object(line.parts, "upscale_plate_safe", return_value=(str(p1), 64, 64)), \
                 patch.object(line.parts, "build_body_mask", return_value=(Image.new("L", (64, 64), 128), "geometric_fallback", 8.0)):
                result, pose = line.run_lens_first_pipeline(cfg, tmp, policy.build_lens_plan({}), "audit", "negative", [], [], [],
                                                           "negative", {"style": ""}, manifest, Plan(), None,
                                                           lambda *xs: ", ".join(xs), None, repaint)
            assert not repaint.called and result == str(p1)
            assert manifest["lens"]["facing_step2"] == ""
            assert any(step["step"] == "02_body" and step["status"] == "skipped" for step in manifest["steps"])
    check("B线门禁：无有效人体蒙版不盲画且未知朝向不当正面", gate)

    def provenance():
        class Stop(Exception):
            pass

        for coverage, expected_seed, expected_name in (([0.5, 0.2], 10, "original.png"), ([0.2, 0.5], 323, "retry.png")):
            with tempfile.TemporaryDirectory() as tmp:
                p1, p2, cfg = fixture(tmp)
                manifest = {"steps": []}
                loras = [{"name": "scene", "weight": 0.70}, {"name": "char", "weight": 0.50}]
                with patch.object(line, "_plate", side_effect=[str(p1), str(p2)]), \
                     patch.object(line.parts, "detect_safe", return_value={}), patch.object(line, "_body_cov", side_effect=coverage), \
                     patch.object(line.parts, "upscale_plate_safe", side_effect=Stop):
                    try:
                        line.run_lens_first_pipeline(cfg, tmp, {}, "audit", "negative", loras, [], [], "negative", {},
                                                     manifest, Plan(), None, None, None, None)
                    except Stop:
                        pass
                step = manifest["steps"][0]
                assert step["seed"] == expected_seed and Path(step["output"]).name == expected_name, step
                expected_loras = loras if expected_seed == 10 else line._retry_loras(cfg, loras)
                assert step["loras"] == expected_loras, step
    check("B线血缘：所选原板/重试板的图、种子与 LoRA 同步", provenance)
