# -*- coding: utf-8 -*-
"""去掉指向 adaln_modulation（1 维调制参数）的 LoRA 键，输出可用的 clean 版本。"""
import json, struct, sys, os
import torch
from safetensors.torch import load_file, save_file
src=sys.argv[1]; dst=sys.argv[2]
sd=load_file(src)
bad=[k for k in sd if "adaln_modulation" in k]
keep={k:v for k,v in sd.items() if "adaln_modulation" not in k}
save_file(keep, dst)
print("dropped", len(bad), "kept", len(keep), "->", dst)
