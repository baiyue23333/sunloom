# -*- coding: utf-8 -*-
"""从参考图一键提取 3D 骨架：调用 ComfyUI SDPoseKeypointExtractor 并反解 3D FK 关节角。"""
import base64
import io
import json
import math
import os
import time
import urllib.request

from PIL import Image
import comfy_paths

COMFY = os.environ.get("STATION_COMFY", os.environ.get("COMFY_API", "http://127.0.0.1:8188")).rstrip("/")

# COCO-18
NOSE, NECK = 0, 1
RS, RE, RW = 2, 3, 4
LS, LE, LW = 5, 6, 7
RH, RK, RA = 8, 9, 10
LH, LK, LA = 11, 12, 13


def _comfy(path, payload=None, timeout=120):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(COMFY + path, data=data, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())


def _extract_sdpose(img_path, timeout=90):
    name = f"posefit_{int(time.time() * 1000)}_{os.getpid()}.png"
    Image.open(img_path).convert("RGB").save(os.path.join(comfy_paths.comfy_in(), name))
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sdpose_wholebody_fp16.safetensors"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": name}},
        "3": {"class_type": "SDPoseKeypointExtractor", "inputs": {"model": ["1", 0], "vae": ["1", 2], "image": ["2", 0], "batch_size": 1}},
        "4": {"class_type": "SavePoseKeypointsJSON", "inputs": {"keypoints": ["3", 0], "prefix": "posefit"}},
    }
    pid = _comfy("/prompt", {"prompt": wf})["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = _comfy("/history/" + pid)
        if pid in h:
            ent = h[pid]
            if (ent.get("status") or {}).get("status_str") == "error":
                raise RuntimeError("SDPose 提骨失败")
            for node in (ent.get("outputs") or {}).values():
                for key in ("pose_keypoints_json", "text", "files", "filenames"):
                    val = node.get(key)
                    if isinstance(val, list) and val:
                        fn = val[0] if isinstance(val[0], str) else (val[0].get("filename") or "")
                        p = os.path.join(comfy_paths.comfy_out(), fn)
                        if os.path.isfile(p):
                            return json.load(open(p, encoding="utf-8"))
            # 兜底：从 ComfyUI output 目录找最新 posefit_*.json
            out_dir = comfy_paths.comfy_out()
            cands = sorted(
                (os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.startswith("posefit") and f.endswith(".json")),
                key=os.path.getmtime, reverse=True,
            )
            if cands:
                return json.load(open(cands[0], encoding="utf-8"))
            raise RuntimeError("SDPose 未输出关键点 JSON")
        time.sleep(1.0)
    raise TimeoutError("SDPose 提骨超时")


def _limb_angles(a, b, is_arm=True, side_sign=1.0):
    """根据 2D 屏幕矢量 (dx, dy) 估算局部 (rx 抬举, rz 外展) 角度。"""
    dx = b[0] - a[0]
    dy = b[1] - a[1]  # 屏幕 y 向下为正
    ln = max(1e-4, math.hypot(dx, dy))
    nx, ny = dx / ln, dy / ln
    # 垂下时 ny=1 -> rx=0; 举起时 ny=-1 -> rx=-160
    pitch = math.degrees(math.atan2(ny, max(0.15, abs(nx))))  # -90(up) .. +90(down)
    rx = round(max(-165.0, min(75.0, (pitch - 90.0) * 0.95)), 1)
    rz_raw = math.degrees(math.atan2(nx, max(0.2, ny)))
    if is_arm:
        rz = round(max(-85.0, min(85.0, rz_raw * 0.85)), 1)
    else:
        rz = round(max(-35.0, min(35.0, rz_raw * 0.65)), 1)
    return rx, rz


def _bend_angle(a, b, c):
    """三点夹角估算肘/膝弯曲度（0=伸直, 125=全折）。"""
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    l1, l2 = math.hypot(*v1), math.hypot(*v2)
    if l1 < 4 or l2 < 4:
        return 22.0
    cos_t = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))
    ang = 180.0 - math.degrees(math.acos(cos_t))
    return round(max(4.0, min(128.0, ang)), 1)


def keypoints_to_pose(pose_json):
    """把 COCO-18 关键点 JSON 拟合为 pose3d FK 关节字典。"""
    d = pose_json[0] if isinstance(pose_json, list) else pose_json
    people = d.get("people") or []
    if not people:
        raise ValueError("未检测到人物骨架")
    arr = people[0].get("pose_keypoints_2d") or []
    pts = [(float(arr[i]), float(arr[i + 1]), float(arr[i + 2])) for i in range(0, len(arr) - 2, 3)]

    def pt(idx):
        return pts[idx][:2] if idx < len(pts) and pts[idx][2] > 0.2 else None

    ls, rs = pt(LS), pt(RS)
    lh, rh = pt(LH), pt(RH)
    nose, neck = pt(NOSE), pt(NECK)

    # 人物在画面中 lr: 画面左通常是角色右(-X=l)或左(+X=r), 直接按 X 坐标配对到 -X("l") / +X("r")
    left_sh, right_sh = (rs, ls) if (rs and ls and rs[0] <= ls[0]) else (ls, rs)
    l_tag, r_tag = ("r", "l") if (rs and ls and rs[0] > ls[0]) else ("l", "r")
    sh_pairs = {"l": (pt(RS), pt(RE), pt(RW)) if l_tag == "l" else (pt(LS), pt(LE), pt(LW)),
                "r": (pt(LS), pt(LE), pt(LW)) if l_tag == "l" else (pt(RS), pt(RE), pt(RW))}
    leg_pairs = {"l": (pt(RH), pt(RK), pt(RA)) if l_tag == "l" else (pt(LH), pt(LK), pt(LA)),
                 "r": (pt(LH), pt(LK), pt(LA)) if l_tag == "l" else (pt(RH), pt(RK), pt(RA))}

    pelvis_yaw = 0.0
    facing = "front"
    if left_sh and right_sh and lh and rh:
        sw = abs(right_sh[0] - left_sh[0])
        torso_h = max(20.0, abs((lh[1] + rh[1]) * 0.5 - (left_sh[1] + right_sh[1]) * 0.5))
        ratio_sw = sw / torso_h
        if ratio_sw < 0.38:
            pelvis_yaw = 36.0 if (nose and nose[0] > (left_sh[0] + right_sh[0]) * 0.5) else -36.0
            facing = "side"
        if not nose:
            facing = "back"
            pelvis_yaw = 165.0

    joints = {
        "pelvis_yaw": round(pelvis_yaw, 1),
        "pelvis_tilt": [4, 0, 0],
        "spine": [0, 0, 0],
        "chest": [0, 0, 0],
        "neck": [0, 0, 0],
        "head": [0, 0, 0],
    }
    if nose and neck and left_sh and right_sh:
        mid_sh_x = 0.5 * (left_sh[0] + right_sh[0])
        sw_est = max(20.0, abs(right_sh[0] - left_sh[0]))
        head_yaw = max(-45.0, min(45.0, ((nose[0] - mid_sh_x) / sw_est) * 55.0))
        joints["head"] = [0, round(head_yaw, 1), 0]

    for sd, sx in (("l", -1.0), ("r", 1.0)):
        sh, el, wr = sh_pairs[sd]
        if sh and el:
            rx, rz = _limb_angles(sh, el, is_arm=True, side_sign=sx)
            joints[f"{sd}_shoulder"] = [rx, 0, rz]
            joints[f"{sd}_elbow"] = [_bend_angle(sh, el, wr) if wr else 24, 0, 0]
        else:
            joints[f"{sd}_shoulder"] = [10, 0, -14 * sx]
            joints[f"{sd}_elbow"] = [22, 0, 0]
        hp, kn, ak = leg_pairs[sd]
        if hp and kn:
            rx, rz = _limb_angles(hp, kn, is_arm=False, side_sign=sx)
            joints[f"{sd}_hip"] = [max(-105.0, min(55.0, rx)), 0, rz]
            joints[f"{sd}_knee"] = [_bend_angle(hp, kn, ak) if ak else 12, 0, 0]
        else:
            joints[f"{sd}_hip"] = [0, 0, -4 * sx]
            joints[f"{sd}_knee"] = [8, 0, 0]
        joints[f"{sd}_ankle"] = [0, 0, 0]

    return {"joints": joints, "facing": facing, "cam_yaw": 0, "cam_pitch": 4}


def fit_from_image(image_b64_or_path):
    """支持传入本地文件路径或 base64 dataURL，返回拟合后的 3D 关节字典。"""
    tmp_path = None
    if os.path.isfile(str(image_b64_or_path or "")):
        src = image_b64_or_path
    else:
        raw = str(image_b64_or_path or "")
        if "," in raw:
            raw = raw.split(",", 1)[1]
        im = Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
        tmp_path = os.path.join(comfy_paths.comfy_temp(), f"posefit_up_{int(time.time() * 1000)}.png")
        im.save(tmp_path)
        src = tmp_path
    try:
        pj = _extract_sdpose(src)
        return keypoints_to_pose(pj)
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
