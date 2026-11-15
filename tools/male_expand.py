# -*- coding: utf-8 -*-
"""补男性身份 3 个 + 男性姿态 20 个。"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "ref", "prompt_lib.json")

IDS = {
    "@ID_M_KAI": "(black undercut hair:1.35), (dark brown eyes:1.3), (sharp jawline:1.25), "
                 "(small scar across his left brow:1.2), (lean muscular build:1.15)",
    "@ID_M_REN": "(silver grey medium hair:1.35), (calm grey eyes:1.3), (thin rimless glasses:1.2), "
                 "(slender tall build:1.2), (quiet expression:1.15)",
    "@ID_M_TAKU": "(messy brown hair:1.35), (hazel eyes:1.3), (light stubble:1.15), "
                  "(broad shoulders:1.2), (relaxed expression:1.15)",
}

POSES = {
    "@POSE_M_LEAN_RAILING": "(both forearms resting on a railing:1.3), (looking away:1.2)",
    "@POSE_M_SIT_DESK": "(sitting on the edge of a desk:1.3), (one ankle crossed over the other:1.2)",
    "@POSE_M_READ_BOOK": "(holding a book open in one hand:1.35), (eyes down on the page:1.2)",
    "@POSE_M_DRINK_CUP": "(raising a cup to his mouth:1.35), (elbow bent:1.2)",
    "@POSE_M_PHONE": "(holding a phone in one hand:1.3), (looking at the screen:1.25)",
    "@POSE_M_HANDS_CLASP_BACK": "(both hands clasped behind his back:1.35), (chest out:1.15)",
    "@POSE_M_LOOK_SIDE": "(head turned to one side:1.3), (eyes off camera:1.2)",
    "@POSE_M_WALK_FORWARD": "(walking toward the camera:1.35), (one arm swinging:1.2)",
    "@POSE_M_RUN": "(running mid-stride:1.35), (body leaning forward:1.25)",
    "@POSE_M_STRETCH_UP": "(one arm stretched overhead:1.3), (body lengthened:1.2)",
    "@POSE_M_SIT_FLOOR": "(sitting on the floor:1.3), (one knee up:1.25), (forearm on the knee:1.2)",
    "@POSE_M_KNEEL_ONE": "(kneeling on one knee:1.35), (hand on the raised knee:1.2)",
    "@POSE_M_CROUCH": "(crouching low:1.3), (forearms on his knees:1.25)",
    "@POSE_M_LEAN_DOOR": "(shoulder against a door frame:1.35), (arms crossed:1.2)",
    "@POSE_M_ADJUST_TIE": "(fingers adjusting his tie:1.35), (chin slightly lifted:1.15)",
    "@POSE_M_HAND_HAIR": "(one hand pushing his hair back:1.3), (eyes narrowed:1.15)",
    "@POSE_M_WAVE": "(raising one hand in a wave:1.3), (relaxed smile:1.15)",
    "@POSE_M_SALUTE": "(right hand at his brow in a salute:1.35), (back straight:1.2)",
    "@POSE_M_THUMBS_POCKET": "(both thumbs hooked in his pockets:1.3), (weight on one leg:1.2)",
    "@POSE_M_CROSS_LEGS_SIT": "(sitting with legs crossed:1.3), (hands resting on his knee:1.2)",
}


def main():
    lib = json.load(open(LIB, encoding="utf-8"))
    tok, notes = lib["tokens"], lib["notes"]
    g = lib.setdefault("meta", {}).setdefault("gender", {})
    add = 0
    for k, v in list(IDS.items()) + list(POSES.items()):
        if k in tok:
            continue
        tok[k] = v
        notes[k] = ("男性身份：" + k.split("_")[-1].title()) if k.startswith("@ID_") else ("男性姿态：" + k[6:].replace("_", " ").title())
        g[k] = "m"
        add += 1
    json.dump(lib, open(LIB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    male = sum(1 for v in g.values() if v == "m")
    print("新增", add, "个 | 男性积木合计", male, "| 总 token", len(tok))


if __name__ == "__main__":
    main()
