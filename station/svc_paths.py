# -*- coding: utf-8 -*-
"""按用途校验文件边界；不允许绝对输出目录、父目录或目录联接逃逸。"""
import os
import re

from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PICTURES = os.path.join(ROOT, "SD-Picture")
EXPORTS = os.path.join(PICTURES, "exports")
OUTPUT_NAMES = frozenset(("station_out", "paper", "harvest", "remote_out"))
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def within(path, roots):
    if not isinstance(path, str) or not path or "\x00" in path:
        return False
    try:
        target = os.path.normcase(os.path.realpath(path))
        for root in roots:
            if root:
                base = os.path.normcase(os.path.realpath(root))
                try:
                    if os.path.commonpath((target, base)) == base:
                        return True
                except ValueError:
                    continue
    except (OSError, ValueError, TypeError):
        pass
    return False


def require_file(path, roots, extensions=None):
    if not within(path, roots):
        raise HTTPException(403, "路径不在该功能允许目录内")
    if extensions and os.path.splitext(path)[1].lower() not in extensions:
        raise HTTPException(403, "不允许的文件类型")
    if not os.path.isfile(path):
        raise HTTPException(404, "文件不存在")
    return os.path.realpath(path)


def output_dir(name="station_out", create=True):
    if name not in OUTPUT_NAMES:
        raise HTTPException(400, "不支持的保存目录")
    path = os.path.join(PICTURES, name)
    if not within(path, (PICTURES,)):
        raise HTTPException(403, "输出目录越界")
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def safe_prefix(value, default="station"):
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(value or default))[:40] or default


def image_ok(path):
    from PIL import Image
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, ValueError, SyntaxError):
        return False
