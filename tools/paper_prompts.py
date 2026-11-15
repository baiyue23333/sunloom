# -*- coding: utf-8 -*-
"""提示词拼装：人物卡/背景板的共享常量与清洗。"""
SHARP = "(sharp focus:1.05), (crisp lineart:1.1), (detailed eyes:1.1)"
PLATE_DETAIL = ("(complete illustration:1.1), (rich set dressing:1.15), "
                "(layered foreground midground background:1.2), (many small details:1.15), "
                "(atmospheric perspective:1.1), (painterly brushwork:1.05)")
BLUR_WORDS = ("depth of field", "bokeh", "out of focus", "blur", "shallow focus",
              "close-up", "upper body", "soft focus")
STYLE_DROP = ("soft", "painterly", "blur", "bokeh", "haze", "dreamy", "mist", "shallow")


def clean_char_prompt(text):
    """人物卡是独立画面：景深/特写这类构图词必须去掉。"""
    parts = [p.strip() for p in str(text).split(",") if p.strip()]
    keep = [p for p in parts if not any(w in p.lower() for w in BLUR_WORDS)]
    return ", ".join(keep), len(parts) - len(keep)


def stage_style_for_char(style):
    """只保留颜色/光源词，去掉会让人物发糊的风格词。"""
    parts = [p.strip() for p in str(style or "").split(",") if p.strip()]
    return ", ".join(p for p in parts if not any(w in p.lower() for w in STYLE_DROP))


def char_light_from(stage, default):
    """只用舞台光源写人物光；同向同色去重，没有冷光就不写冷边。"""
    lights = (stage or {}).get("lights") or []
    if not lights:
        return default
    parts, seen = [], set()
    for L in sorted(lights, key=lambda x: -float(x.get("strength", 0))):
        key = (L.get("dir"), L.get("color"))
        if key in seen:
            continue
        seen.add(key)
        parts.append("(%s light from the %s:1.15)" % (L.get("color"), L.get("dir")))
    return ", ".join(parts) if parts else default


def build_char(anime, base_char, framing, footwear, light_prompt, style_char, details_txt, inter_txt, transparent=False):
    frame = ("(upper body portrait:1.35), (waist-up:1.2), (looking at viewer:1.1)"
             if framing == "bust" else
             "(full body only:1.25), (full body from head to feet:1.3), (facing the viewer:1.15)")
    bg = ("(transparent background:1.6), (no background:1.4), "
          if transparent else
          "(simple light grey background:1.5), (plain background:1.3), ")
    return (base_char + ", " + anime + ", (single character:1.35), (one person only:1.3), "
            + frame + ", (no portrait inset:1.2), " + bg + footwear + ", "
            + light_prompt + ", " + SHARP + (", " + style_char if style_char else "")
            + (", " + details_txt if details_txt else "") + inter_txt)
