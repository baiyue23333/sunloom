# -*- coding: utf-8 -*-
"""兼容层：真正的实现在 core/store.py（私有版与开源版共享同一份）。"""
import os
import sys

_STATION = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_STATION)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.environ.setdefault("STATION_DB", os.path.join(_STATION, "data", "station.db"))

from core.store import *  # noqa: E402,F401,F403
from core.store import init, load_recipes, save_recipes, upsert_recipe, get_recipe  # noqa: E402,F401
from core.store import load_registry, append_registry  # noqa: E402,F401
from core.store import load_templates, save_templates, load_cards, save_cards  # noqa: E402,F401
