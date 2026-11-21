# -*- coding: utf-8 -*-
"""B 线镜头优先（b_lens）回归：五类镜头调度 / 六档朝向 / 侧背修脸门控 / 前端透传。

由 run_tests.py 调用（validate_tests.py 已接近 20KB，独立成分册）。
"""
import argparse
import json
import os
import re
import tempfile


def run(check, ROOT):
    tools_dir = os.path.join(ROOT, "tools")
    if tools_dir not in os.sys.path:
        os.sys.path.insert(0, tools_dir)

    def _classes():
        import lens_policy as lp
        assert lp.classify("@CAM_GROUND") == "keep"
        assert lp.classify("@COMP_SILHOUETTE") == "keep"
        assert lp.classify("@BG_CINEMA_BOKEH") == "bokeh"
        assert lp.classify("@ATMO_BOKEH") == "bokeh"
        assert lp.classify("@CAM_PEEP_FOLIAGE") == "fg"
        assert lp.classify("@COMP_DEPTH_SANDWICH") == "fg"
        assert lp.classify("@COMP_VAST") == "frame"
        assert lp.classify("@COMP_FIGURE_SMALL") == "frame"
        assert lp.classify("@GAZE_CAMERA") == "look"
        assert lp.classify("@CAM_CLOSEUP") == "look"
        assert lp.classify("@OUT_SCHOOL") == "" and lp.classify("") == ""
        # 白名单里的宏必须真实存在（防止拼错死块）
        toks = lp.tokens()
        miss = [t for s in (lp.PERSPECTIVE_STYLE_KEEP, lp.BG_BOKEH_TOKS, lp.FG_OCCLUDE_TOKS,
                            lp.FRAME_COMP_TOKS, lp.LOOK_AT_CAMERA_TOKS) for t in s if t not in toks]
        assert not miss, miss[:6]
    check("b_lens 五类镜头白名单", _classes)

    def _plan_with_lens():
        import lens_policy as lp
        cfg = {"lens_spec": {
            "cam_tokens": [{"token": "@CAM_TELE", "weight": 1.0},
                           {"token": "@CAM_PEEP_FOLIAGE", "weight": 1.4}],
            "comp_tokens": [{"token": "@COMP_SILHOUETTE", "weight": 1.0},
                            {"token": "@COMP_FIGURE_SMALL", "weight": 1.0}],
            "bokeh_tokens": [{"token": "@BG_BOKEH", "weight": 1.0}],
            "gaze_tokens": [{"token": "@GAZE_CAMERA", "weight": 1.0}]}}
        toks = lp.tokens()
        p = lp.build_lens_plan(cfg)
        assert p["has_lens"] and p["ratio_mode"] == "fixed" and not p["auto_ratio"], p
        cue = p["plate_cue"]
        # 未手调权重的镜头块自动提权；手调 1.4 保留
        assert "(telephoto compression" in cue and cue.count(":1.25)") >= 2, cue
        assert ":1.4)" in cue and "(medium candid shot peeking" in cue, cue
        # 第 2/3/4 类只进母板，02_body 剥除
        assert p["protect_fg_depth"] is True and p["suppress_look"] is True
        assert "looking directly at the viewer" not in cue, cue
        bokeh_ph, fig_ph = toks["@BG_BOKEH"], toks["@COMP_FIGURE_SMALL"]
        assert bokeh_ph in p["body_drop"] and fig_ph in p["body_drop"] and toks["@CAM_TELE"] not in p["body_drop"]
        assert "@CAM_TELE" in p["classes"]["keep"] and "@BG_BOKEH" in p["classes"]["bokeh"]
        assert lp.plate_prompt("scene text", p).startswith("(telephoto compression"), lp.plate_prompt("scene text", p)[:80]
        body = lp.body_prompt("1girl, " + toks["@CAM_TELE"] + ", " + bokeh_ph + ", " + fig_ph + ", standing", p)
        assert toks["@CAM_TELE"] in body and bokeh_ph not in body and fig_ph not in body, body
    check("b_lens 出板提权与 02 分类剥除", _plan_with_lens)

    def _plan_no_lens():
        import lens_policy as lp
        for cfg in ({}, {"lens_spec": {}}):
            p = lp.build_lens_plan(cfg)
            assert p["ratio_mode"] == "auto" and p["auto_ratio"], p
            assert p["plate_cue"] == "" and p["body_drop"] == [] and not p["protect_fg_depth"], p
            assert p["candid"] is True, p
        # 只挂视线积木：仍算「无镜头积木」交给模型自判，但不硬塞相反的 candid
        gaze = lp.build_lens_plan({"lens_spec": {"gaze_tokens": [{"token": "@GAZE_CAMERA"}]}})
        assert gaze["auto_ratio"] and gaze["candid"] is False, gaze
        assert "telephoto" not in gaze["plate_cue"] and "wide shot" not in gaze["plate_cue"], gaze["plate_cue"]
        busy = lp.build_lens_plan({"lens_spec": {"cam_tokens": [{"token": "@CAM_PEEP_FOLIAGE"}]}})
        assert busy["auto_ratio"] is False and busy["candid"] is False
    check("b_lens 无镜头积木时完全放手", _plan_no_lens)

    def _facing():
        import scale_probe as sp

        def write(pts, name):
            kp = [0.0] * (18 * 3)
            for i, (x, y, c) in enumerate(pts):
                kp[i * 3:i * 3 + 3] = [x, y, c]
            p = os.path.join(td, name + ".json")
            open(p, "w", encoding="utf-8").write(json.dumps(
                [{"canvas_width": 832, "canvas_height": 1152, "people": [{"pose_keypoints_2d": kp}]}]))
            return p

        def person(nose=None, reye=None, leye=None, rear=None, lear=None):
            p = [(0, 0, 0)] * 18
            p[1], p[2], p[5] = (400, 240, 0.9), (350, 250, 0.9), (450, 250, 0.9)
            if nose:
                p[0] = (nose, 180, 0.9)
            if reye:
                p[14] = reye
            if leye:
                p[15] = leye
            if rear:
                p[16] = rear
            if lear:
                p[17] = lear
            return p

        with tempfile.TemporaryDirectory(prefix="lens_face_") as td:
            cases = [
                ("front", person(400, (380, 170, 0.9), (420, 170, 0.9), (350, 175, 0.9), (450, 175, 0.9))),
                ("three_quarter_right", person(432, (385, 170, 0.9), (418, 172, 0.9), (350, 180, 0.9))),
                # 双耳齐见时的 3/4：靠「鼻子偏近转向侧耳朵」判方向
                ("three_quarter_right", person(425, (388, 170, 0.9), (415, 172, 0.9), (362, 180, 0.9), (455, 178, 0.9))),
                ("three_quarter_left", person(368, (382, 172, 0.9), (415, 170, 0.9), None, (450, 180, 0.9))),
                ("three_quarter_left", person(375, (385, 172, 0.9), (412, 170, 0.9), (345, 178, 0.9), (438, 180, 0.9))),
                ("profile_right", person(462, None, (415, 175, 0.9), (350, 180, 0.9))),
                ("profile_left", person(338, (383, 175, 0.9), None, None, (450, 180, 0.9))),
                ("back", person()),
            ]
            for idx, (want, pts) in enumerate(cases):
                got = sp.infer_head_facing(write(pts, "c%d_%s" % (idx, want)), 832, 1152)
                assert got == want, (want, got)
            assert sp.infer_head_facing("", 832, 1152) == ""
    check("六档头部朝向识别", _facing)

    def _face_prompt():
        import lens_policy as lp
        src = "grey eye, red eye, long eyelashes, soft blush, long hair ornament"
        assert lp.adapt_face_prompt(src, "front") == src
        right = lp.adapt_face_prompt(src, "profile_right").lower()
        assert "grey eye" in right and "red eye" not in right and "blush" in right, right
        left = lp.adapt_face_prompt(src, "three_quarter_left").lower()
        assert "red eye" in left and "grey eye" not in left, left
        back = lp.adapt_face_prompt(src, "back").lower()
        assert "grey eye" not in back and "red eye" not in back and "blush" not in back, back
        assert "from behind, back view" in back and "long hair ornament" in back, back
        assert lp.adapt_face_prompt("", "back") == ""
        assert lp.facing_cue("front") == "" and "profile" in lp.facing_cue("profile_left")
    check("侧/背修脸词过滤与朝向词", _face_prompt)

    def _routing():
        import coop_reproject as cr
        rows = (("b_lens", "b_lens"), ("lens", "b_lens"), ("b_char", "b_char"), ("b", "b"), ("a", "a"), ("", "a"))
        for raw, exp in rows:
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
                json.dump({"pipeline": raw, "lens_spec": {"cam_tokens": [{"token": "@CAM_TELE"}]}}, f)
                p = f.name
            try:
                c = cr._load_cfg(argparse.Namespace(config=p, scene="s", char="c", seed=1, width=1216, height=832))
                assert c["pipeline"] == exp, (raw, c["pipeline"])
                assert c["lens_spec"].get("cam_tokens"), (raw, c["lens_spec"])
            finally:
                try:
                    os.remove(p)
                except OSError:
                    pass
        import coop_lens_first, reproj_body, lens_policy
        for fn in (coop_lens_first.run_lens_first_pipeline, reproj_body.repaint_body,
                   lens_policy.build_lens_plan, cr._repaint_body):
            assert callable(fn)
        mf = {"lens": {}}
        assert mf["lens"] == {}
    check("b_lens 路由与模块接线", _routing)

    def _frontend():
        idx = open(os.path.join(ROOT, "station", "static", "index.html"), encoding="utf-8").read()
        js = open(os.path.join(ROOT, "station", "static", "app.js"), encoding="utf-8").read()
        ph = open(os.path.join(ROOT, "station", "static", "js", "coop_pipe.js"), encoding="utf-8").read()
        assert '<option value="b_lens" selected>' in idx, "b_lens 未设为默认"
        seg = idx[idx.index('id="coop-b-variant"'):]
        seg = seg[:seg.index("</select>")]
        assert seg.index('value="b_lens"') < seg.index('value="b_char"') < seg.index('value="b">'), "下拉顺序不对"
        assert 'id="coop-pose-bar" class="pose-bar-wrap" style="margin-top:8px" hidden' in idx, "姿态栏没有默认隐藏"
        assert "function coopLensSpec()" in js and "coop_lens_spec" not in js
        for k in ("cam_tokens:", "comp_tokens:", "bokeh_tokens:", "gaze_tokens:"):
            assert k in js, "lens_spec 缺 " + k
        assert "pipeNow === 'b_lens' ? cpos : coopCharCommon(cpos)" in js, "b_lens 仍被预先过滤镜头词"
        assert "lens_spec: coopLensSpec()" in js and "pipeline: pipeNow," in js, "coopStartReal 未透传"
        version = re.search(r"/app\.js\?v=(\d+)", idx)
        assert version and int(version.group(1)) >= 451 and "coop_pipe.js?v=8" in idx, "前端版本号没 bump"
        assert "'b_lens'" in ph and "curVariant !== 'b_char'" in ph, "coop_pipe 未接线 pose-bar 显隐"
    check("b_lens 前端透传（静态）", _frontend)
