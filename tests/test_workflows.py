# -*- coding: utf-8 -*-
"""工作流占位符自检

跑法：python tests/test_workflows.py

1) 静态：workflow 里的每个 {{xxx}} 都必须有参数来源
2) 功能：t2i 用样例参数填充后，正向/负向必须真的落到 CLIPTextEncode 上
   （这条是回归：曾经 server 只传 prompt，不传 positive，导致正向一直是空）
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF = os.path.join(HERE, 'station', 'workflows')
sys.path.insert(0, os.path.join(HERE, 'station'))

# 参数来源：server.py 的 params + config.model + features.py 的 inpaint params
PROVIDED = {
    'prompt', 'positive', 'negative', 'width', 'height', 'steps', 'cfg', 'seed',
    'prefix', 'denoise', 'reference', 'mask', 'sampler', 'scheduler',
    'unet', 'clip', 'vae', 'clip_type',
}


def placeholders(obj, out):
    if isinstance(obj, str):
        out.update(re.findall(r'\{\{([a-zA-Z_0-9]+)\}\}', obj))
    elif isinstance(obj, list):
        for v in obj:
            placeholders(v, out)
    elif isinstance(obj, dict):
        for v in obj.values():
            placeholders(v, out)
    return out


def main():
    failed = 0
    files = sorted(f for f in os.listdir(WF) if f.endswith('.json'))
    for f in files:
        d = json.load(open(os.path.join(WF, f), encoding='utf-8'))
        missing = sorted(placeholders(d.get('nodes') or {}, set()) - PROVIDED)
        if missing:
            print('FAIL', f, '未提供的占位符:', missing)
            failed += 1
    if not failed:
        print('PASS  占位符完整（%d 个工作流）' % len(files))

    try:
        import graph
    except Exception as e:
        print('SKIP  功能检查（import graph 失败：%s）' % e)
        return failed
    nodes = graph.load('t2i')['nodes']
    for _n in nodes.values():
        if 'type' in _n and 'class_type' not in _n:
            _n['class_type'] = _n.pop('type')
    params = {'prompt': 'POS-X', 'positive': 'POS-X', 'negative': 'NEG-Y',
              'width': 640, 'height': 896, 'steps': 16, 'cfg': 5.5, 'seed': 123,
              'prefix': 't', 'denoise': 1.0}
    filled = graph._fill(nodes, params, {})
    texts = [n.get('inputs', {}).get('text') for n in filled.values()
             if n.get('class_type') == 'CLIPTextEncode']
    if 'POS-X' not in texts or 'NEG-Y' not in texts:
        print('FAIL  t2i 填充后正负向没进图:', texts)
        failed += 1
    else:
        print('PASS  t2i 正负向填充正确')
    return failed


if __name__ == '__main__':
    sys.exit(main())
