# -*- coding: utf-8 -*-
"""gender split v1:
1) 女性专属积木加 _F_ 标记；男性积木统一 _M_ 标记
2) 新增 5 个女性身份
3) 旧名全部写入 ALIASES（向后兼容）
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "ref", "prompt_lib.json")

GROUPS = ("ID", "BODY", "FACE", "HAIR", "HAND", "POSE", "SINGLE")

NEW_IDS = {
    "@ID_F_AYA": "(black bob hair:1.35), (blunt bangs:1.2), (amber eyes:1.3), "
                 "(small mole under her left eye:1.2), (round face:1.15), fair skin",
    "@ID_F_RIN": "(silver short hair:1.35), (sharp eyes:1.25), (ice blue eyes:1.3), "
                 "(straight nose:1.15), (cool expression:1.2), fair skin",
    "@ID_F_YUKI": "(long chestnut hair:1.35), (soft waves:1.2), (green eyes:1.3), "
                  "(warm smile:1.15), (gentle face:1.2), light freckles",
    "@ID_F_SORA": "(violet twin tails:1.35), (high ribbon ties:1.2), (violet eyes:1.3), "
                  "(playful grin:1.2), (small fang:1.15), fair skin",
    "@ID_F_HANA": "(honey blonde wavy hair:1.35), (hazel eyes:1.3), (freckles across her nose:1.2), "
                  "(sunny expression:1.15), (warm tan:1.1)",
}


def rename_key(k):
    """返回 (新名 or None)。"""
    if not any(k.startswith("@" + g + "_") or k == "@" + g for g in GROUPS):
        return None
    # 男性统一：*_MALE_* → *_M_*，*_MALE → *_M
    if "_MALE_" in k:
        return k.replace("_MALE_", "_M_")
    if k.endswith("_MALE"):
        return k[:-len("MALE")] + "M"
    # 已带 _M_ 男性标记：保持
    if re.search(r"_M_", k) or k.endswith("_M"):
        return None
    # 男性专属角色块（@BODY_MIO 之类其实是女性角色，不能改）
    if k.startswith("@BODY_MIO"):
        return k.replace("@BODY_", "@BODY_F_")
    if k.startswith("@ID_F"):
        return k.replace("@ID_", "@ID_F_")
    # 其余女性：插入 _F_
    parts = k.split("_")
    head, tail = parts[0], "_".join(parts[1:])
    return head + "_F_" + tail if tail else head + "_F"


def main():
    lib = json.load(open(LIB, encoding="utf-8"))
    tok = lib["tokens"]
    mapping = {}
    for k in list(tok):
        nk = rename_key(k)
        if nk and nk not in tok and nk != k:
            mapping[k] = nk
    # 重命名（先复制再删旧）
    for old, new in mapping.items():
        tok[new] = tok[old]
    for old in mapping:
        del tok[old]
    # 新增女性身份
    for k, v in NEW_IDS.items():
        tok.setdefault(k, v)
    # meta.subgroups 同步
    meta = lib.get("meta") or {}
    subs = meta.get("subgroups") or {}
    meta["subgroups"] = {mapping.get(k, k): v for k, v in subs.items()}
    lib["meta"] = meta
    json.dump(lib, open(LIB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("重命名", len(mapping), "个 | 新增女性身份", len(NEW_IDS), "个 | 总 token", len(tok))
    alias_lines = "\n".join("    %r: %r," % (o, n) for o, n in sorted(mapping.items()))
    open(os.path.join(ROOT, "ref", "gender_alias_new.py"), "w", encoding="utf-8").write(
        "# 由 tools/gender_split.py 生成\nGENDER_ALIASES = {\n" + alias_lines + "\n}\n")
    print("别名表:", os.path.join(ROOT, "ref", "gender_alias_new.py"))


if __name__ == "__main__":
    main()
