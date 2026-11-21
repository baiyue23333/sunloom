# -*- coding: utf-8 -*-
"""2D/3D 动作骨架库、参考图扒 2D 骨与实时预览接口。"""
import base64
import io
import os
import sys
import tempfile
from typing import Any, Dict, Optional

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import pose2d  # noqa: E402
import pose3d  # noqa: E402

router = APIRouter()


class PosePreviewReq(BaseModel):
    preset: str = "walk_turn"
    profile: str = "petite"
    mirror: bool = False
    cam_yaw: float = 0.0
    cam_pitch: float = 4.0
    cx: float = 0.5
    gy: float = 0.92
    ratio: float = 0.76
    width: int = 384
    height: int = 512
    outline: bool = True
    joints: Optional[Dict[str, Any]] = None


class Pose2DPreviewReq(BaseModel):
    preset: str = "jump_joy"
    mirror: bool = False
    cx: float = 0.5
    gy: float = 0.92
    ratio: float = 0.76
    width: int = 384
    height: int = 512
    joints2d: Optional[Dict[str, Any]] = None


class PoseExtractReq(BaseModel):
    image_b64: str = ""
    path: str = ""


@router.get("/api/pose/presets")
def api_pose_presets():
    lib3 = pose3d.load_pose_library()
    lib2 = pose2d.load_pose2d_library()
    return {
        "ok": True,
        "patch": pose3d.pose_lllite_name(),
        "patch_2d": pose2d.pose2d_lllite_name(),
        "profiles": lib3.get("profiles") or {},
        "presets": lib3.get("presets") or {},
        "presets_2d": lib2.get("presets") or {},
    }


@router.post("/api/pose/preview")
def api_pose_preview(req: PosePreviewReq):
    lib = pose3d.load_pose_library()
    presets = lib.get("presets") or {}
    pose = dict(presets.get(req.preset) or next(iter(presets.values())))
    if isinstance(req.joints, dict):
        for k, v in req.joints.items():
            pose[k] = v
    w = max(192, min(1024, int(req.width or 384)))
    h = max(192, min(1280, int(req.height or 512)))
    im = pose3d.render_mannequin(
        pose, size=(w, h), cx=float(req.cx), gy=float(req.gy), ratio=float(req.ratio),
        cam_yaw=float(req.cam_yaw), cam_pitch=float(req.cam_pitch),
        profile=str(req.profile or "petite"), mirror=bool(req.mirror),
        outline_px=4 if req.outline else 0,
    )
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return {"ok": True, "image": "data:image/png;base64," + b64, "patch": pose3d.pose_lllite_name()}


@router.get("/api/pose/thumb/{preset}")
def api_pose_thumb(preset: str, profile: str = "petite"):
    im = pose3d.render_mannequin(preset, size=(128, 168), cx=0.5, gy=0.92, ratio=0.76, profile=profile, outline_px=2)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.post("/api/pose/preview2d")
def api_pose_preview2d(req: Pose2DPreviewReq):
    lib = pose2d.load_pose2d_library()
    presets = lib.get("presets") or {}
    joints = req.joints2d or (presets.get(req.preset) or next(iter(presets.values()), {})).get("joints") or {}
    w = max(192, min(1024, int(req.width or 384)))
    h = max(192, min(1280, int(req.height or 512)))
    im = pose2d.render_dwpose(joints, size=(w, h), cx=float(req.cx), gy=float(req.gy),
                              ratio=float(req.ratio), mirror=bool(req.mirror))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return {"ok": True, "image": "data:image/png;base64," + b64, "patch": pose2d.pose2d_lllite_name()}


@router.post("/api/pose/from_image")
@router.post("/api/pose/extract")
def api_pose_extract(req: PoseExtractReq):
    tmp = None
    try:
        src = str(req.path or "").strip()
        if not src and req.image_b64:
            raw = req.image_b64.split(",", 1)[-1]
            fd, tmp = tempfile.mkstemp(suffix=".png", prefix="pose2d_ext_")
            os.close(fd)
            with open(tmp, "wb") as f:
                f.write(base64.b64decode(raw))
            src = tmp
        if not src or not os.path.isfile(src):
            return {"ok": False, "error": "未提供有效图片"}
        joints = pose2d.extract_pose2d_from_image(src)
        if not joints:
            return {"ok": False, "error": "未检出完整人体骨架（请换全身/半身清晰图）"}
        out = {"ok": True, "joints2d": joints}
        try:
            import pose_fit, reproj_parts
            pj = (reproj_parts.detect_safe(src) or {}).get("json")
            if pj and os.path.isfile(pj):
                fit = pose_fit.keypoints_to_pose(pj)
                if isinstance(fit, dict):
                    out["joints"] = fit.get("joints")
                    out["facing"] = fit.get("facing", "auto")
        except Exception:
            pass
        return out
    finally:
        if tmp and os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
