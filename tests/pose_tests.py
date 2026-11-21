# -*- coding: utf-8 -*-
"""2D / 3D 动作骨架库、提取拟合与预览接口回归（由 validate_tests.py 调用）。"""
import argparse
import json
import os
import tempfile


def run_checks(check):
    def _pose_tests():
        import numpy as np
        import pose3d
        lib = pose3d.load_pose_library()
        presets = lib.get("presets") or {}
        assert "rooftop_cheer" in presets and "dynamic_lean" in presets, list(presets.keys())
        im = pose3d.render_mannequin("rooftop_cheer", size=(256, 320), profile="petite", outline_px=4)
        assert im.size == (256, 320) and im.mode == "RGB", im.size
        im_m = pose3d.render_mannequin("rooftop_cheer", size=(256, 320), mirror=True, outline_px=0)
        assert im_m.size == (256, 320)
        mp = pose3d.mirror_pose(presets["rooftop_cheer"])
        assert mp["l_shoulder"][0] == presets["rooftop_cheer"]["r_shoulder"][0]

        import coop_reproject
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"scene": "bridge", "char": "1girl", "pose": {"mode": "2d", "enabled": True, "preset": "jump_joy"}}, f)
            p = f.name
        try:
            c = coop_reproject._load_cfg(argparse.Namespace(config=p, scene="bridge", char="1girl", seed=1, width=896, height=1216))
            assert (c.get("pose") or {}).get("mode") == "2d" and c["pose"]["preset"] == "jump_joy", c.get("pose")
        finally:
            try:
                os.remove(p)
            except OSError:
                pass

        import routes_pose
        res = routes_pose.api_pose_presets()
        assert res["ok"] and len(res["presets"]) >= 20, len(res["presets"])
        prev = routes_pose.api_pose_preview(routes_pose.PosePreviewReq(preset="dynamic_lean", width=256, height=320))
        assert prev["ok"] and prev["image"].startswith("data:image/png;base64,"), list(prev.keys())
        th = routes_pose.api_pose_thumb("walk_turn", "petite")
        assert th.status_code == 200 and th.body.startswith(b"\x89PNG")

        im_j = pose3d.render_mannequin("jump_joy", size=(320, 420), cx=0.5, gy=0.92, ratio=0.76, outline_px=4)
        assert np.asarray(im_j)[0].max() == 0, "jump_joy top row clipped"

        import pose_fit, sdp_body_mask, routes_coop
        kps = [600,300,0.9, 600,360,0.9, 550,360,0.9, 520,440,0.9, 500,520,0.9, 650,360,0.9, 680,440,0.9, 710,510,0.9,
               565,540,0.9, 560,680,0.9, 555,820,0.9, 635,540,0.9, 645,680,0.9, 655,820,0.9, 0,0,0, 0,0,0, 0,0,0, 0,0,0]
        fitted = pose_fit.keypoints_to_pose({"people": [{"pose_keypoints_2d": kps}]})
        assert "joints" in fitted and "l_shoulder" in fitted["joints"]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fj:
            json.dump([{"canvas_width": 1344, "canvas_height": 1824, "people": [{"pose_keypoints_2d": kps}]}], fj)
            jp = fj.name
        try:
            mk, cov = sdp_body_mask.body_mask(jp, 1344, 1824)
            assert mk is not None and cov > 1.0
        finally:
            try:
                os.remove(jp)
            except OSError:
                pass
        hr = routes_coop.api_coop_hint(routes_coop.HintReq(scene="@SET_CAFE", char="@POSE_SIT"))
        assert hr["tier"] in ("switch_a", "two_layer", "two_half", "three_depth") and hr["keyword"] != ""

        import pose2d
        lib2 = pose2d.load_pose2d_library()
        assert "jump_joy" in (lib2.get("presets") or {}), lib2
        im2 = pose2d.render_dwpose("jump_joy", size=(256, 320), mirror=True)
        assert im2.size == (256, 320) and im2.mode == "RGB", im2.size
        assert len(res.get("presets_2d") or {}) >= 8, res
        prev2 = routes_pose.api_pose_preview2d(routes_pose.Pose2DPreviewReq(preset="jump_joy", width=256, height=320))
        assert prev2["ok"] and prev2["image"].startswith("data:image/png;base64,"), list(prev2.keys())

    check("无骨/2骨/3骨动作骨架库与渲染预览接口", _pose_tests)
