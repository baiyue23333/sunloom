
# -*- coding: utf-8 -*-
"""seed_blocks.py — 批量创作新积木（含备注）"""
import json

P = r"A:\workflow\dsh\ref\prompt_lib.json"
lib = json.load(open(P, encoding="utf-8"))
toks = lib["tokens"]
notes = lib.setdefault("notes", {})

BLOCKS = {
# ---------------- 情绪 ----------------
"@MOOD_SLEEPY": ("(half-lidded eyes:1.3), (drowsy expression:1.25), (soft parted lips:1.15)",
    "刚醒/困倦。配 @TIME_DAWN 或 @ATMO_LAMP_GLOW 很稳；不要配 @GAZE_AT_CAMERA，会变呆。"),
"@MOOD_SURPRISED": ("(raised eyebrows:1.2), (slightly open mouth:1.2), (wide eyes:1.25)",
    "惊讶。权重别超 1.2，容易变惊恐。适合抓拍式构图。"),
"@MOOD_AMUSED": ("(subtle smirk:1.3), (one corner of the mouth lifted:1.2), (amused eyes:1.2)",
    "憋笑/坏笑。比 smile 高级，不张嘴也能读出来。"),
"@MOOD_SHY": ("(blushing cheeks:1.3), (looking away:1.25), (small pursed smile:1.2)",
    "害羞。视线会自动偏开，和 @GAZE_ASIDE 同义叠加会过；二选一。"),
"@MOOD_DETACHED": ("(blank calm expression:1.3), (unreadable eyes:1.25), (lips relaxed:1.15)",
    "疏离/冷淡。适合夜灯、走廊、背影。会压掉腮红，想要血色就别用。"),
"@MOOD_FOCUSED": ("(focused gaze:1.3), (slightly furrowed brows:1.2), (closed mouth:1.15)",
    "专注（看书、调相机）。配 @HAND_BOOK 或 @PROP_CAMERA。"),
"@MOOD_WISTFUL": ("(wistful expression:1.3), (distant look:1.25), (faint sad smile:1.2)",
    "怅然。黄昏/蓝调时刻的最佳拍档，眼神会自然放空。"),
"@MOOD_CALM": ("(gentle closed-lip smile:1.25), (calm eyes:1.2)",
    "平静。@FACE 的加强版，需要更克制的表情时替换 @FACE。"),

# ---------------- 视线 ----------------
"@GAZE_CAMERA": ("(looking directly at the viewer:1.35)", "正面视线。会立刻变成“证件照”感，慎配全身。"),
"@GAZE_DOWN": ("(looking down:1.3)", "看下方（书、手、台阶）。低头会挡眼，注意刘海长度。"),
"@GAZE_WINDOW": ("(looking out the window:1.3)", "望窗外。侧脸+逆光最好看。"),
"@GAZE_CLOSED": ("(eyes closed:1.35)", "闭眼。适合微风、祈祷、听音乐。别配 @ID 的红眼权重过高。"),
"@GAZE_ASIDE": ("(looking aside:1.3), (eyes to the side:1.2)", "侧目。比转头含蓄，能保留正脸构图。"),
"@GAZE_FAR": ("(gazing into the distance:1.3), (unfocused eyes:1.15)", "望远。适合大场景、空旷背景。"),

# ---------------- 手部 ----------------
"@HAND_CHIN": ("(one hand resting under her chin:1.3)", "托腮。思考/等待。注意手指数量，建议抽 2 张。"),
"@HAND_BOOK": ("(both hands holding an open book:1.3)", "捧书。和 @PROP_BOOK 二选一，别叠加。"),
"@HAND_CUFF": ("(one hand adjusting her coat cuff:1.3)", "整理袖口。小动作，画面立刻有生活感。"),
"@HAND_HAIR": ("(one hand tucking hair behind her ear:1.3)", "别头发。经典但有效，会露出耳朵和颈线。"),
"@HAND_KNEES": ("(both hands resting on her knees:1.25)", "手放膝上。坐姿默认，最不容易崩手。"),
"@HAND_POCKET": ("(one hand in her coat pocket:1.3)", "手插口袋。站姿显松弛，但会藏住手（省得画手）。"),
"@HAND_COLLAR": ("(one hand at her collar:1.25)", "手扶领口。和 @DRAPE_HOLD 接近，二选一。"),
"@HAND_WARM": ("(both hands holding a warm mug:1.3)", "捧杯暖手。注意：会招来杯子，必须配 @NEG_CUP；不想画杯子就别用。"),

# ---------------- 头发 ----------------
"@HAIR_WIND": ("(hair blown by the wind:1.35), (loose strands across her face:1.2)",
    "风吹发。天台/海边/黄昏必备，但会挡眼，建议配 @GAZE_FAR。"),
"@HAIR_TUCKED": ("(hair tucked behind one ear:1.25)", "单侧别到耳后。露出颈部与耳饰，画面更透气。"),
"@HAIR_STRAND": ("(a loose strand of hair in front of her lips:1.2)", "一缕发丝贴唇。特写加分项。"),
"@HAIR_DAMP": ("(slightly damp hair:1.2), (a few strands sticking to her cheek:1.15)",
    "微湿发。雨后/刚洗过。克制使用，权重高会变油腻。"),

# ---------------- 材质 ----------------
"@FAB_SATIN": ("(satin sheen:1.3), (soft specular highlights along the folds:1.25)", "缎面高光。简版黄裙的灵魂。"),
"@FAB_FUR": ("(fluffy fur texture:1.3), (backlit rim on the fur:1.25)", "毛绒逆光边缘。夜灯/逆光下最出彩。"),
"@FAB_WOOL": ("(matte wool texture:1.25), (crisp fabric edges:1.2)", "呢料。初始军装外套用它压住“缎面感”。"),
"@FAB_FOLDS": ("(natural fabric folds:1.25), (folds following her pose:1.2)", "褶皱走向。站/坐姿切换时很有用。"),
"@FAB_SHEER": ("(sheer black pantyhose:1.25), (subtle skin tone through the fabric:1.15)", "黑丝的通透感。权重过高会变灰。"),

# ---------------- 氛围 ----------------
"@ATMO_DUST": ("(dust motes floating in the light:1.3)", "光柱里的浮尘。窗光/顶光神器。"),
"@ATMO_GRID": ("(window frame shadows across the wall:1.3), (hard geometric light:1.2)", "窗格光斑。方窗/百叶都适用。"),
"@ATMO_LAMP": ("(warm lamp glow out of frame:1.3), (soft pool of light:1.25)", "画外暖灯。夜戏最安全的补光。"),
"@ATMO_CANDLE": ("(candlelight:1.3), (flickering warm highlights:1.2)", "烛光。近景慎用，容易过曝。"),
"@ATMO_MOON": ("(cool moonlight:1.3), (blue rim light:1.2)", "冷月光。配 @MOOD_DETACHED 很绝。"),
"@ATMO_RAIN": ("(rain streaks on the window:1.3), (wet reflections:1.25)", "雨窗。注意别让雨丝糊脸。"),
"@ATMO_NEON": ("(neon reflections on wet ground:1.3), (colored rim light:1.2)", "霓虹。会污染肤色，建议权重 1.15 以内。"),
"@ATMO_BOKEH": ("(shallow depth of field:1.3), (soft bokeh lights in the background:1.25)", "背景散景。人像必备，能救杂乱背景。"),

# ---------------- 时间 ----------------
"@TIME_DAWN": ("(early morning:1.25), (cool pale light:1.2)", "清晨。冷白偏青，适合刚醒。"),
"@TIME_NOON": ("(harsh midday sun:1.25)", "正午。光硬，阴影短，慎用。"),
"@TIME_DUSK": ("(golden hour:1.3), (long warm shadows:1.25)", "黄昏。最宽容的光，几乎不翻车。"),
"@TIME_BLUE": ("(blue hour:1.3), (deep blue ambient:1.25)", "蓝调时刻。冷暖对撞，夜景片首选。"),
"@TIME_NIGHT": ("(deep night:1.25), (dark surroundings:1.2)", "深夜。只是压暗，不提供光源，要配 @ATMO_LAMP 或 @ATMO_MOON。"),

# ---------------- 场景 ----------------
"@SET_GREENHOUSE": ("(inside a glass greenhouse:1.3), (green leaves around:1.2), (condensation on glass:1.15)",
    "温室。绿植会抢色，建议低权重、加 @ATMO_BOKEH。"),
"@SET_BOOKSTORE": ("(old bookstore:1.3), (tall wooden shelves:1.25), (dusty warm light:1.2)", "旧书店。暖调，适合读到入神。"),
"@SET_PIANO": ("(piano room:1.3), (grand piano at the edge of frame:1.2)", "琴房。钢琴别放正中，容易变演奏会。"),
"@SET_TRAM": ("(inside an old tram:1.3), (window reflections:1.2)", "电车。移动光斑，适合 @GAZE_WINDOW。"),
"@SET_ROOFTOP": ("(rooftop at dusk:1.3), (city skyline below:1.2)", "天台黄昏。风大，配 @HAIR_WIND。"),
"@SET_LAUNDRY": ("(small laundromat:1.3), (rows of washing machines:1.2)", "洗衣房。冷白灯，蓝调。"),
"@SET_CORRIDOR": ("(long corridor:1.3), (doors on both sides:1.2)", "长廊。透视强，适合低机位。"),
"@SET_STATION": ("(empty train platform at night:1.3), (platform lights:1.2)", "空站台。离别感专用。"),

# ---------------- 道具 ----------------
"@PROP_SUNFLOWER": ("(holding a single sunflower:1.3)", "手持向日葵。主题呼应；注意别和发饰重复。"),
"@PROP_BOOK": ("(an open book in her hands:1.25)", "书。和 @HAND_BOOK 二选一。"),
"@PROP_CAMERA": ("(an old film camera hanging from her neck:1.25)", "胶片机。复古感，注意肩带别穿模。"),
"@PROP_VINYL": ("(holding a vinyl record sleeve:1.2)", "黑胶唱片。配 @SET_BOOKSTORE 或 @ATMO_LAMP。"),
"@PROP_UMBRELLA": ("(a closed umbrella held at her side:1.25)", "合着的伞。开伞容易崩结构，建议只画合伞。"),
"@PROP_HEADPHONES": ("(headphones around her neck:1.25)", "脖子上挂耳机。现代感，注意别压住蝴蝶结。"),
"@PROP_BLANKET": ("(a soft blanket over her shoulders:1.25)", "毛毯披肩。替代外套的居家感。"),
"@PROP_LETTER": ("(holding a folded letter:1.2)", "信纸。和站台/门厅搭配有故事感。"),

# ---------------- 构图 ----------------
"@COMP_FOREGROUND": ("(foreground blur from a curtain or plant:1.3)", "前景遮挡虚化。立刻有电影感。"),
"@COMP_LOW": ("(low angle shot:1.3)", "低机位。显腿长，但容易脸变形，别配 @CAM_BUST。"),
"@COMP_OVERHEAD": ("(overhead shot from above:1.3)", "俯拍。适合坐姿/仰头，顶光配合。"),
"@COMP_OVER_SHOULDER": ("(over the shoulder view:1.3)", "过肩。需要前景人物，单人时容易变双人，慎用。"),
"@COMP_MIRROR": ("(seen in a mirror reflection:1.3)", "镜中像。构图有趣，但容易出两个“她”（模型会当双人画）。"),
"@COMP_DOF": ("(shallow depth of field:1.3), (blurred background:1.2)", "浅景深。和 @ATMO_BOKEH 重复，二选一。"),

# ---------------- 风格 ----------------
"@STYLE_CEL": ("(cel shading:1.3), (flat colors with clean lines:1.2)", "赛璐璐。压画风 LoRA 的厚涂感。"),
"@STYLE_WATER": ("(watercolor edges:1.25), (soft pigment bleed:1.2)", "水彩边。适合情绪片，慎用于全身。"),
"@STYLE_FILM": ("(film grain:1.25), (slight halation:1.2)", "胶片颗粒。夜戏增强氛围。"),
"@STYLE_SOFT": ("(soft focus:1.25), (dreamy glow:1.2)", "柔焦。权重高会糊，建议 1.15。"),
"@STYLE_CHROMA": ("(subtle chromatic aberration at the edges:1.2)", "边缘色差。极轻的镜头感，别超过 1.2。"),

# ---------------- 负向 ----------------
"@NEG_HAND_ART": ("(extra fingers:1.4), (fused fingers:1.3), (missing fingers:1.3), (bad hand proportions:1.3)",
    "手部灾难包。需要手的构图（托腮/捧书）必带。"),
"@NEG_TEXT": ("(text:1.3), (watermark:1.3), (signature:1.2), (logo:1.2)", "文字水印。出图带字时优先查这个。"),
"@NEG_DOUBLE": ("(double exposure:1.3), (ghosting:1.25)", "重影/双重曝光。修复“半透明第二个人”。"),
"@NEG_BGCLUTTER": ("(cluttered background:1.25), (messy room:1.2)", "背景杂乱。和 @ATMO_BOKEH 相反的作用力。"),
"@NEG_AI": ("(ai artifacts:1.3), (jpeg artifacts:1.2), (oversharpened:1.15)", "AI 伪影包。"),
"@NEG_PERSPECTIVE": ("(distorted perspective:1.25), (warped face:1.3)", "透视崩坏。低机位/广角时带。"),
}

added = 0
for name, (text, note) in BLOCKS.items():
    toks[name] = text
    notes[name] = note
    added += 1

lib["tokens"] = toks
lib["notes"] = notes
json.dump(lib, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("新增积木", added, "｜总计 tokens", len(toks), "｜notes", len(notes))
