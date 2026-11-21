
# -*- coding: utf-8 -*-
"""cleanup.py — 清理明显错误/多图合并/碎片图片，保留登记与成品"""
import json, os, glob, shutil

ROOT = r"A:\project\dsh"
REG = os.path.join(ROOT, "ref", "registry.jsonl")
DRY = os.environ.get("CLEAN_DRY", "0") == "1"

# 1) 受保护：登记表里出现过的图
protected = set()
if os.path.exists(REG):
    for line in open(REG, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            p = json.loads(line)["file"]
        except Exception:
            continue
        protected.add(os.path.basename(p).lower())

KEEP_NAMES = {
    # 成品与关键实验
    "f1_hall_1.png", "f1_hall_2.png", "f2_window_2.png", "f3_stairs_2.png",
    "d01_1.png", "d02_1.png", "d03_1.png", "d05_1.png", "d06_1.png", "d07_1.png", "d09_1.png", "d10_1.png",
    "bs_960002.png", "bk_970001.png", "it11_bench45.png", "fxb_3.png", "fxa_2.png", "d03_cold_2.png",
    "it19_stair135.png", "stS4_1.png", "sts4_1.png", "dq_elb2_1.png", "dq_hold2_1.png",
    "pwv6_1.png", "pwv6_3.png", "c3_hall_off_2.png", "c2_stair_worn_1.png",
    "ref_bust55.png",
}

def keep(path, extra_dirs_whitelist=()):
    n = os.path.basename(path).lower()
    if n in protected or n in KEEP_NAMES:
        return True
    return False

TASKS = []

def plan(dirpath, keep_pred, note):
    if not os.path.isdir(dirpath):
        return
    files = [p for p in glob.glob(os.path.join(dirpath, "**", "*.png"), recursive=True)]
    dele = [p for p in files if not keep_pred(p)]
    TASKS.append((dirpath, note, len(files), len(dele), sum(os.path.getsize(p) for p in dele), dele))

# 质检目录：只留登记过的
plan(os.path.join(ROOT, "产出作品", "质检"), keep, "QC 标注副本（派生物）")

# 迭代目录：留登记的 + 前 6 张
def keep_head(dirpath, n=6):
    files = sorted(glob.glob(os.path.join(dirpath, "*.png")))
    head = set(os.path.basename(p).lower() for p in files[:n])
    return lambda p: keep(p) or os.path.basename(p).lower() in head

plan(os.path.join(ROOT, "SD-Picture", "iter"), keep_head(os.path.join(ROOT, "SD-Picture", "iter")), "第一轮 30 张（h1 时代）")
plan(os.path.join(ROOT, "SD-Picture", "iter2"), keep_head(os.path.join(ROOT, "SD-Picture", "iter2")), "第二轮 30 张")
plan(os.path.join(ROOT, "SD-Picture", "design10"), keep_head(os.path.join(ROOT, "SD-Picture", "design10"), 4), "10 设计（白裙错版）")
plan(os.path.join(ROOT, "SD-Picture", "design_fix"), keep_head(os.path.join(ROOT, "SD-Picture", "design_fix"), 3), "服装锁修复验证")
plan(os.path.join(ROOT, "SD-Picture", "eval_h2"), keep_head(os.path.join(ROOT, "SD-Picture", "eval_h2"), 6), "h2 对比实验")
plan(os.path.join(ROOT, "SD-Picture", "exp_identity"), keep_head(os.path.join(ROOT, "SD-Picture", "exp_identity"), 6), "身份 A/B 实验")
plan(os.path.join(ROOT, "SD-Picture", "slim_test"), keep_head(os.path.join(ROOT, "SD-Picture", "slim_test"), 2), "提示词瘦身（全错）")
plan(os.path.join(ROOT, "SD-Picture", "garment_test"), keep_head(os.path.join(ROOT, "SD-Picture", "garment_test"), 2), "服装 LoRA（平涂）")
plan(os.path.join(ROOT, "SD-Picture", "posed"), lambda p: False, "姿势通道失败品")
plan(os.path.join(ROOT, "SD-Picture", "harvest", "harvest", "design"), keep_head(os.path.join(ROOT, "SD-Picture", "harvest", "harvest", "design"), 3), "远程 design（白裙错版）")
plan(os.path.join(ROOT, "SD-Picture", "harvest", "harvest", "design_fix"), keep_head(os.path.join(ROOT, "SD-Picture", "harvest", "harvest", "design_fix"), 2), "远程 design_fix")
plan(os.path.join(ROOT, "SD-Picture", "harvest", "harvest", "slim_test"), keep_head(os.path.join(ROOT, "SD-Picture", "harvest", "harvest", "slim_test"), 1), "远程 slim_test")
plan(os.path.join(ROOT, "SD-Picture", "harvest", "harvest", "garment_test"), keep_head(os.path.join(ROOT, "SD-Picture", "harvest", "harvest", "garment_test"), 1), "远程 garment_test")
plan(os.path.join(ROOT, "SD-Picture", "harvest", "harvest", "eval_h2"), keep_head(os.path.join(ROOT, "SD-Picture", "harvest", "harvest", "eval_h2"), 6), "远程 eval_h2")
plan(os.path.join(ROOT, "SD-Picture", "harvest", "harvest", "exp_identity"), keep_head(os.path.join(ROOT, "SD-Picture", "harvest", "harvest", "exp_identity"), 6), "远程 exp_identity")
plan(os.path.join(ROOT, "SD-Picture", "harvest", "harvest", "iter3"), keep_head(os.path.join(ROOT, "SD-Picture", "harvest", "harvest", "iter3"), 10), "远程 100 轮")

# remote_out：留登记 + 成品名，其余按前缀白名单
GOOD_PREFIX = ("f1_", "f2_", "f3_", "d0", "d1", "bs_", "bk_", "dq_", "pwv6", "c3_", "c2_", "fin1_win_1", "fin2_stair_2")
def keep_remote(p):
    n = os.path.basename(p).lower()
    if keep(p):
        return True
    return any(n.startswith(x) for x in GOOD_PREFIX)
plan(os.path.join(ROOT, "SD-Picture", "remote_out"), keep_remote, "远程输出（坏图）")

# 原图：留登记 + 最近 100 张
raw = os.path.join(ROOT, "SD-Picture", "原图")
if os.path.isdir(raw):
    files = sorted(glob.glob(os.path.join(raw, "*.png")), key=os.path.getmtime, reverse=True)
    newest = set(os.path.basename(p).lower() for p in files[:100])
    plan(raw, lambda p: keep(p) or os.path.basename(p).lower() in newest, "原图（旧测试图）")

# _inspect：只留最近 12 个
ins = os.path.join(ROOT, "SD-Picture", "_inspect")
if os.path.isdir(ins):
    files = sorted(glob.glob(os.path.join(ins, "*.png")), key=os.path.getmtime, reverse=True)
    newest = set(os.path.basename(p).lower() for p in files[:12])
    plan(ins, lambda p: os.path.basename(p).lower() in newest, "_inspect 拼图（旧）")

total_files = total_bytes = 0
for dirpath, note, n, nd, nb, dele in TASKS:
    total_files += nd
    total_bytes += nb
    print("%-40s %-22s 共%4d 删%4d (%5.0f MB)" % (os.path.basename(dirpath) or dirpath, note, n, nd, nb / 1048576))
print("-" * 90)
print("合计删除 %d 个文件，释放 %.0f MB" % (total_files, total_bytes / 1048576))

if DRY:
    print("[DRY RUN] 未删除")
else:
    for dirpath, note, n, nd, nb, dele in TASKS:
        for p in dele:
            try:
                os.remove(p)
            except Exception:
                pass
    print("已删除")

