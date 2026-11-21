# -*- coding: utf-8 -*-
"""兼容层：真正的实现在 core/store.py（私有版与开源版共享同一份）。"""
import os
import sys

_STATION = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_STATION)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from core import store as _store  # noqa: E402

# 所有入口共享同一个模块对象，包括 DB、_INITED 与告警钩子。
sys.modules[__name__] = _store
