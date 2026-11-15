
import json, time, os, sys, urllib.request
ROOT = os.environ.get("SUNLOOM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import comfy_paths
def post(u, d):
    req = urllib.request.Request(u, data=json.dumps(d).encode(), headers={"Content-Type":"application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
def get(u): return json.loads(urllib.request.urlopen(u, timeout=30).read().decode())

C = comfy_paths.COMFY_URL
IMG = os.environ.get("PROBE_IMG") or os.path.join(ROOT, "SD-Picture", "station_out", "F5_artroom_133622_s880110.png")
INP = os.path.join(comfy_paths.comfy_in(), "pose_probe.png")
import shutil
shutil.copy2(IMG, INP)

wf = {
 "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sdpose_wholebody_fp16.safetensors"}},
 "2": {"class_type": "LoadImage", "inputs": {"image": "pose_probe.png"}},
 "3": {"class_type": "SDPoseKeypointExtractor", "inputs": {"model": ["1",0], "vae": ["1",2], "image": ["2",0], "batch_size": 1}},
 "4": {"class_type": "SavePoseKeypointsJSON", "inputs": {"keypoints": ["3",0], "prefix": "probe"}},
 "5": {"class_type": "SDPoseDrawKeypoints", "inputs": {"keypoints": ["3",0], "draw_body": True, "draw_hands": True,
        "draw_face": True, "draw_feet": False, "stick_width": 4, "face_point_size": 3,
        "score_threshold": 0.25, "draw_head": True}},
 "6": {"class_type": "SaveImage", "inputs": {"images": ["5",0], "filename_prefix": "probe_draw"}},
}
pid = post(C + "/prompt", {"prompt": wf})["prompt_id"]
print("queued", pid)
for _ in range(240):
    time.sleep(2)
    h = get(C + "/history/" + pid)
    if pid in h:
        st = h[pid]["status"]
        print("status", st.get("status_str"))
        for kind, payload in st.get("messages", []):
            if kind == "execution_error":
                print("ERR", payload.get("exception_type"), str(payload.get("exception_message"))[:300])
        outs = h[pid].get("outputs", {})
        print("outputs keys", list(outs.keys()))
        for k, v in outs.items():
            print("  node", k, json.dumps(v, ensure_ascii=False)[:300])
        break
