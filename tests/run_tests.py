# -*- coding: utf-8 -*-
"""SUNLOOM 最小回归测试：python tests/run_tests.py

覆盖：
  1) 数据完整性（积木备注、模板引用、服装字段）
  2) 展开（无残留宏、权重范围）
  3) 校验器（缺身份、双服装、型态错配、构图互斥）
  4) 模板全部可展开
  5) 配方接口 + PNG 反推正负向（回归：曾经把正向认成负向）
  6) 蒙版归一化（回归：红通道羽化）
  7) 前端静态检查（回归：结果面板按钮绑定、配套函数、资源版本）
"""
import os
import re
import sys
import json
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "station"))
os.environ["STATION_NO_SUPERVISOR"] = "1"
# 测试用独立的临时库：每次从 JSON 重新导入，不碰线上的 station.db
TEST_DB = os.path.join(tempfile.gettempdir(), "sunloom-test.db")
for _suffix in ("", "-wal", "-shm"):
    try:
        os.remove(TEST_DB + _suffix)
    except OSError:
        pass
os.environ["STATION_DB"] = TEST_DB
os.chdir(os.path.join(ROOT, "station"))

PASS, FAIL, SKIP = [], [], []


def check(name, fn):
    try:
        fn()
        PASS.append(name)
        print("  PASS  " + name)
    except AssertionError as e:
        FAIL.append((name, str(e)))
        print("  FAIL  " + name + "  -> " + str(e))
    except Exception as e:  # noqa: BLE001
        FAIL.append((name, repr(e)))
        print("  FAIL  " + name + "  -> " + repr(e))


def section(title):
    print("\n== " + title + " ==")


def main():
    import server
    from fastapi.testclient import TestClient

    c = TestClient(server.app)
    boot = c.get("/api/bootstrap").json()
    tokens = boot["tokens"]
    notes = boot["notes"]
    garments = boot["garments"]

    section("数据完整性")
    def _notes():
        missing = [k for k in tokens if not (notes.get(k) or "").strip()]
        assert not missing, "缺备注: %s" % missing[:8]
    check("每个积木都有备注", _notes)

    def _junk():
        bad = [k for k, v in tokens.items() if (v or "").strip().lower() in ("", "null", "undefined")]
        assert not bad, "空/占位积木: %s" % bad[:8]
    check("没有空或 null 积木", _junk)

    def _garments():
        for k, g in garments.items():
            for f in ("prompt", "negative", "note", "parts"):
                assert (g.get(f) or ([] if f == "parts" else "")), "服装 %s 缺 %s" % (k, f)
            assert "@OUT_" + k.upper() in tokens, "服装 %s 缺 @OUT 宏" % k
            assert "@NEG_" + k.upper() in tokens, "服装 %s 缺 @NEG 宏" % k
    check("服装字段与派生宏齐全", _garments)

    templates = c.get("/api/templates").json()["items"]
    def _tpl_tokens():
        bad = []
        for t in templates:
            for b in (t.get("positive") or []) + (t.get("negative") or []):
                tok = b.get("token")
                if tok and tok not in tokens:
                    bad.append(t["name"] + ":" + tok)
        assert not bad, "模板引用不存在的宏: %s" % bad[:6]
    check("模板引用的宏都存在", _tpl_tokens)

    section("展开")
    def _expand_all():
        bad = []
        for k in sorted(tokens):
            e = c.post("/api/expand", json={"positive": [{"token": k}], "negative": []}).json()
            out = e.get("positive") or ""
            if "@" in out:
                left = [w for w in out.split() if w.startswith("@")]
                bad.append(k + " -> " + ",".join(left[:3]))
            if k != "@OUTFIT" and not k.startswith("@STRIP_") and len(out) < 8:
                bad.append(k + " 展开为空")
        assert not bad, "残留宏/空展开: %s" % bad[:6]
    check("245+ 积木逐个展开无残留", _expand_all)

    def _weights():
        bad = []
        for k in sorted(tokens):
            out = c.post("/api/expand", json={"positive": [{"token": k}], "negative": []}).json()["positive"]
            for w in re.findall(r":([0-9.]+)\)", out):
                try:
                    v = float(w)
                except ValueError:
                    continue
                if not (0.4 <= v <= 2.0):
                    bad.append("%s: %s" % (k, w))
        assert not bad, "权重越界: %s" % bad[:6]
    check("权重都在 0.4-2.0", _weights)

    section("校验器")
    def _validate(pos, neg):
        return c.post("/api/validate", json={"positive": [{"token": t} for t in pos],
                                             "negative": [{"token": t} for t in neg]}).json()

    def _no_identity():
        r = _validate(["@CAM_BUST"], ["@NEG_BASE"])
        codes = [e["code"] for e in r["errors"]]
        assert "NO_IDENTITY" in codes, codes
    check("缺 @ID 报错", _no_identity)

    def _garment_conflict():
        r = _validate(["@ID", "@OUT_SLIP", "@OUT_GALA"], ["@NEG_BASE"])
        codes = [e["code"] for e in r["errors"]]
        assert "GARMENT_CONFLICT" in codes, codes
    check("两套服装冲突", _garment_conflict)

    def _drape_mismatch():
        r = _validate(["@ID", "@OUT_SLIP", "@DRAPE_WORN"], ["@NEG_BASE"])
        codes = [e["code"] for e in r["warnings"]]
        assert "DRAPE_GARMENT_MISMATCH" in codes, codes
    check("型态不适用于该套装", _drape_mismatch)

    def _comp_conflict():
        r = _validate(["@ID", "@COMP_CENTER", "@COMP_THIRDS"], ["@NEG_BASE"])
        codes = [e["code"] for e in r["warnings"]]
        assert "COMP_CENTER_CONFLICT" in codes, codes
    check("居中 x 三分互斥", _comp_conflict)

    def _clean():
        r = _validate(["@ID", "@OUT_SLIP", "@DRAPE_OFF", "@CAM_BUST"], ["@NEG_BASE", "@NEG_HANDS"])
        assert not r["errors"], r["errors"]
    check("正常组合无 error", _clean)

    section("模板")
    def _templates():
        assert len(templates) >= 20, "模板只有 %d 个" % len(templates)
        bad = []
        for t in templates:
            e = c.post("/api/expand", json={"positive": t["positive"], "negative": t["negative"]}).json()
            if "@" in e["positive"] or "@" in e["negative"]:
                bad.append(t["name"])
            if len(e["positive"]) < 80 or len(e["negative"]) < 20:
                bad.append(t["name"] + "(太短)")
        assert not bad, bad[:6]
    check("全部模板可展开", _templates)

    section("配方")
    def _recipes():
        r = c.get("/api/recipes").json()
        if r["total"] == 0:
            SKIP.append("/api/recipes 列表（无配方）")
            print("  SKIP  /api/recipes（没有配方）")
            return
        row = r["items"][0]
        assert row.get("name") and "path" in row
    check("/api/recipes 列表", _recipes)

    def _recipe_one():
        rows = c.get("/api/recipes").json()["items"]
        bad = []
        for row in rows[:10]:
            d = c.get("/api/recipe", params={"path": row["path"]}).json()
            if not (d.get("positive") or "").strip():
                bad.append(row["name"])
        assert not bad, "正向为空: %s" % bad
    check("配方正向非空（抽 10）", _recipe_one)

    def _png_parse():
        p = os.path.join(ROOT, "SD-Picture", "station_out", "st_230550_s459068.png")
        if not os.path.isfile(p):
            SKIP.append("PNG 反推（缺测试图）")
            print("  SKIP  PNG 反推（缺测试图）")
            return
        r = server._parse_png_recipe(p)
        assert r and "ivory white hair" in r["positive"], (r or {}).get("positive", "")[:60]
        assert "split screen" in r["negative"], (r or {}).get("negative", "")[:60]
    check("PNG 反推正负向不串（回归）", _png_parse)

    section("蒙版")
    def _mask():
        from PIL import Image
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "m.png")
        im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        for y in range(16, 48):
            for x in range(16, 48):
                im.putpixel((x, y), (255, 0, 0, 255))
        im.save(src)
        out = server._normalize_mask(src, feather=0)
        with Image.open(out) as o:
            px = o.convert("L").load()
            assert px[32, 32] == 255, "中间只有 %d（羽化 bug 回归）" % px[32, 32]
            assert px[2, 2] == 0, "外面不该有值"
    check("蒙版归一化保留满强度（回归）", _mask)

    section("前端静态")
    js = open(os.path.join(ROOT, "station", "static", "app.js"), encoding="utf-8").read()
    html = open(os.path.join(ROOT, "station", "static", "index.html"), encoding="utf-8").read()

    def _panel_binding():
        assert "$$('#result" in js, "结果面板没有用 $$ 绑定"
        m = re.search(r"(?<!\$)\$\('#result [^']*'\)\.forEach", js)
        assert not m, "结果面板又用了 $().forEach：" + (m.group(0) if m else "")
    check("结果面板用 $$ 绑定（回归）", _panel_binding)

    def _companions():
        assert "function companionsOf" in js, "缺配套函数"
        for k in ("@OUT_", "@DRAPE_", "@WEAPON_"):
            assert k in js, "配套函数缺 %s 分支" % k
    check("配套积木函数存在", _companions)

    def _guide():
        assert 'id="view-guide"' in html or "id='view-guide'" in html, "缺向导页面"
        assert 'id="open-guide"' in html, "拼装页缺向导入口"
        assert "function renderGuide" in js and "function guideApply" in js, "缺向导逻辑"
        assert "guideApply" in js and "S.pos.some(b => b.token === t)" in js, "向导应用没去重"
    check("工作流向导（静态）", _guide)

    def _assets():
        m = re.search(r"/app\.js\?v=(\d+)", html)
        assert m, "index.html 没带版本号"
        assert os.path.isfile(os.path.join(ROOT, "station", "static", "app.js"))
    check("静态资源版本号", _assets)

    section("存储层（SQLite）")
    import store

    def _store_migrated():
        assert len(store.load_recipes()) == len(json.load(open(os.path.join(ROOT, "station", "data", "recipes.json"), encoding="utf-8"))), "配方导入数量不符"
        tpl = store.load_templates()
        assert len(tpl) >= 20, "模板只导入 %d 个" % len(tpl)
        if not store.load_registry():
            SKIP.append("JSON 导入登记表（无 registry.jsonl）")
            print("  SKIP  登记表（仓库无 registry.jsonl）")
            return
    check("JSON 一次性导入 SQLite", _store_migrated)

    def _store_roundtrip():
        cards = store.load_cards()
        store.save_cards(cards)
        assert len(store.load_cards()) == len(cards), "角色卡写回数量变化"
        n = len(store.load_registry())
        store.append_registry({"ts": "2026-10-31T00:00:00", "file": "__test__.png", "verdict": "A"})
        assert len(store.load_registry()) == n + 1, "登记追加失败"
        rec = store.load_recipes()
        store.save_recipes(rec)
        assert len(store.load_recipes()) == len(rec), "配方写回数量变化"
    check("存储读写往返", _store_roundtrip)

    section("负向联动")
    def _pairs():
        js = open(os.path.join(ROOT, "station", "static", "app.js"), encoding="utf-8").read()
        assert "function companionNegSet" in js, "缺 companionNegSet"
        assert "@NEG_HAND_ART" in js and "@HAND_" in js, "手部 → @NEG_HAND_ART 联动缺失"
        assert "hiddenNeg.size" in js, "积木库没过滤专属负向"
        assert "pal-show-neg" in js, "缺「显示专属负向」开关"
    check("专属负向隐藏与手部联动（静态）", _pairs)

    def _garment_neg():
        missing = [k for k in garments if ("@NEG_" + k.upper()) not in tokens]
        assert not missing, "缺配套负向: %s" % missing
    check("每套服装都有配套负向", _garment_neg)

    def _drape_neg():
        for d in ("@NEG_DRAPE_ON", "@NEG_DRAPE_OFF"):
            assert d in tokens, "缺 " + d
    check("型态成对负向存在", _drape_neg)

    section("接口契约")
    def _status_contract():
        r = c.get("/api/status")
        assert r.status_code == 200, r.status_code
        d = r.json()
        assert set(d) == {"comfy", "queue"}, d
        assert "up" in d["comfy"] and "version" in d["comfy"], d
        assert isinstance(d["queue"].get("running"), int), d
        assert len(r.content) < 2048, "status 负载过大：%d 字节" % len(r.content)
    check("/api/status 契约与轻量", _status_contract)

    def _img_guard():
        bad = c.get("/api/img", params={"path": "C:/Windows/win.ini"})
        assert bad.status_code == 403, "越界路径应 403，实际 %s" % bad.status_code
        good = c.get("/api/img", params={"path": os.path.join(ROOT, "SD-Picture")})
        assert good.status_code in (200, 404, 403), good.status_code
    check("/api/img 目录白名单", _img_guard)

    def _run_guard():
        r = c.post("/api/run", json={"prompt": "   "})
        assert r.status_code == 400, r.status_code
    check("/api/run 拒绝空提示词", _run_guard)

    def _expand_contract():
        r = c.post("/api/expand", json={"positive": [{"token": "@ID"}], "negative": [{"token": "@NEG_BASE"}]}).json()
        assert "white hair" in r["positive"], r["positive"][:80]
        assert "lowres" in r["negative"] or len(r["negative"]) > 10, r["negative"][:80]
    check("/api/expand 展开契约", _expand_contract)

    def _jobs_cap():
        import server as sv
        for i in range(sv.JOBS_MAX + 30):
            jid = sv.job_new("test", "cap")
            sv.JOBS[jid]["status"] = "done"
        assert len(sv.JOBS) <= sv.JOBS_MAX + 1, len(sv.JOBS)
    check("JOBS 上限淘汰", _jobs_cap)

    section("服务自检")
    def _regress():
        r = c.get("/api/regress").json()
        if not any(x["name"] == "ComfyUI 在线" and x["ok"] for x in r["checks"]):
            SKIP.append("ComfyUI 离线，跳过整体 regress")
            print("  SKIP  /api/regress（ComfyUI 离线）")
            return
        assert r["ok"], [(x["name"], x["ok"]) for x in r["checks"] if not x["ok"]]
    check("/api/regress 全绿", _regress)

    print("\n" + "-" * 46)
    print("PASS %d  FAIL %d  SKIP %d" % (len(PASS), len(FAIL), len(SKIP)))
    if FAIL:
        for n, e in FAIL:
            print("  x " + n + " -> " + e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
