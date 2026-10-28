/* SUNLOOM block studio - generic frontend */
const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
const S = { tokens: {}, notes: {}, garments: {}, garmentDefault: "", templates: [],
            defaults: {}, model: {}, comfy: {}, blocks: { pos: [], neg: [] },
            gallery: [], idx: 0, curGarment: "" };

const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const CATS = [
  ["主体", ["@SUBJ", "@BODY", "@FACE"]],
  ["姿势", ["@POSE"]],
  ["表情", ["@MOOD", "@GAZE"]],
  ["手/发", ["@HAND", "@HAIR"]],
  ["机位", ["@CAM"]],
  ["打光", ["@LIGHT"]],
  ["氛围", ["@ATMO", "@TIME"]],
  ["服装", ["@OUT", "@FAB", "@DRAPE", "@OUTFIT"]],
  ["场景", ["@SET"]],
  ["道具", ["@PROP"]],
  ["构图", ["@COMP"]],
  ["风格", ["@STYLE"]],
  ["负向", ["@NEG"]],
];
function catOf(token) {
  const up = token.toUpperCase();
  for (const [name, prefixes] of CATS) {
    if (name === "主体") { if (["@SUBJ", "@BODY", "@FACE"].includes(up)) return name; continue; }
    if (prefixes.some(p => up.startsWith(p))) return name;
  }
  return "其他";
}
async function api(path, opts) {
  const r = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts || {}));
  if (!r.ok) { let t = ""; try { t = (await r.json()).detail || ""; } catch (e) {} throw new Error(t || ("HTTP " + r.status)); }
  return r.json();
}
function toast(msg) {
  let el = $("#toast");
  if (!el) { el = document.createElement("div"); el.id = "toast"; document.body.appendChild(el); }
  el.textContent = msg; el.classList.add("on");
  clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove("on"), 2400);
}
function openModal(title, html) {
  $("#modal-title").textContent = title;
  $("#modal-content").innerHTML = html;
  $("#modal").classList.add("on");
  $("#modal-close").onclick = () => $("#modal").classList.remove("on");
  $("#modal").onclick = e => { if (e.target.id === "modal") $("#modal").classList.remove("on"); };
}

/* ---------- palette ---------- */
function renderPalette() {
  const q = ($("#pal-search").value || "").toLowerCase();
  const groups = {};
  Object.keys(S.tokens).forEach(k => {
    const c = catOf(k);
    (groups[c] = groups[c] || []).push(k);
  });
  const order = CATS.map(c => c[0]).concat(["其他"]);
  let html = "";
  for (const c of order) {
    const items = (groups[c] || []).filter(k =>
      !q || k.toLowerCase().includes(q) || (S.tokens[k] || "").toLowerCase().includes(q));
    if (!items.length) continue;
    html += '<div class="pg"><div class="pg-head">' + c + "</div><div class=\"pg-items\">";
    for (const k of items) {
      html += '<button class="pg-item" data-tok="' + esc(k) + '" title="' + esc(S.notes[k] || "") + '">' + esc(k) + "</button>";
    }
    html += "</div></div>";
  }
  $("#pal-body").innerHTML = html || '<div class="hint">没有匹配的积木</div>';
  $$("#pal-body .pg-item").forEach(b => b.onclick = () => addBlock(b.dataset.tok));
}

function addBlock(tok) {
  const isNeg = catOf(tok) === "负向";
  const lane = isNeg ? S.blocks.neg : S.blocks.pos;
  if (!lane.find(b => b.token === tok)) lane.push({ token: tok, text: "", weight: 1, enabled: true });
  renderLanes();
}

function renderLanes() {
  const one = lane => lane.map((b, i) => {
    const label = b.token || (b.text || "").slice(0, 24);
    const w = '<input type="number" step="0.05" min="0.1" max="2" value="' + b.weight + '" data-i="' + i + '">';
    return '<div class="blk"><span class="bt">' + esc(label) + "</span>" + w +
           '<button class="bx" data-i="' + i + '">×</button></div>';
  }).join("") || '<div class="hint">左侧点积木添加</div>';
  const mk = (lane, sel, counter) => {
    const el = $(sel);
    el.innerHTML = one(lane);
    $$(sel + " .blk input").forEach(inp => inp.onchange = e => {
      lane[Number(e.target.dataset.i)].weight = Math.max(0.1, Math.min(2, Number(e.target.value) || 1));
      renderLanes(); scheduleExpand();
    });
    $$(sel + " .bx").forEach(b => b.onclick = () => { lane.splice(Number(b.dataset.i), 1); renderLanes(); scheduleExpand(); });
    $(counter).textContent = lane.length + " 块";
  };
  mk(S.blocks.pos, "#lane-pos", "#pos-count");
  mk(S.blocks.neg, "#lane-neg", "#neg-count");
  $("#prev-len").textContent = "";
}
function lanesText() {
  const render = lane => lane.map(b => {
    const raw = b.token || b.text;
    if (!raw) return "";
    return b.weight !== 1 ? "(" + raw + ":" + b.weight + ")" : raw;
  }).filter(Boolean).join(", ");
  return { positive: render(S.blocks.pos), negative: render(S.blocks.neg) };
}

/* ---------- expand / validate ---------- */
let expT = null;
function scheduleExpand() { clearTimeout(expT); expT = setTimeout(doExpand, 260); }
async function doExpand() {
  const t = lanesText();
  try {
    const r = await api("/api/expand", { method: "POST", body: JSON.stringify({
      positive: S.blocks.pos, negative: S.blocks.neg }) });
    $("#prev-body").innerHTML = '<div class="prev"><b>正向</b><pre>' + esc(r.positive) + "</pre>" +
      '<b>负向</b><pre>' + esc(r.negative) + "</pre>" +
      (r.notes && r.notes.length ? "<div class=hint>" + r.notes.map(esc).join("<br>") + "</div>" : "");
    $("#prev-len").textContent = "正向 " + r.pos_len + " 字符 / 负向 " + r.neg_len;
    return r;
  } catch (e) { toast("展开失败：" + e.message); }
}
async function validateNow() {
  const r = await api("/api/validate", { method: "POST", body: JSON.stringify({
    positive: S.blocks.pos, negative: S.blocks.neg }) });
  let html = "";
  if (r.errors.length) html += r.errors.map(e => '<div class="ve">✗ ' + esc(e.msg) + "</div>").join("");
  if (r.warnings.length) html += r.warnings.map(e => '<div class="vw">△ ' + esc(e.msg) + "</div>").join("");
  if (r.hints.length) html += r.hints.map(e => '<div class="vh">· ' + esc(e.msg) + "</div>").join("");
  if (!html) html = '<div class="vo">✓ 结构检查通过</div>';
  $("#val-body").innerHTML = html;
  $("#val-summary").textContent = r.ok ? "通过" : "有错误";
  $("#val-summary").className = "hint " + (r.ok ? "ok" : "bad");
  return r;
}

/* ---------- templates ---------- */
function renderTemplates() {
  if (!$("#tpl-card")) {
    $(".canvas").insertAdjacentHTML("afterbegin",
      '<div class="card" id="tpl-card" style="margin-bottom:14px"><div class="card-head"><h3>快速模板</h3>' +
      '<span class="hint">点一下就把整组积木摆好</span></div><div id="tpl-row" class="tpl-row"></div></div>');
  }
  const row = $("#tpl-row");
  row.innerHTML = S.templates.map((t, i) => '<button class="tpl-b" data-i="' + i + '">' + esc(t.name) + "</button>").join("");
  $$("#tpl-row .tpl-b").forEach(b => b.onclick = () => applyTemplate(Number(b.dataset.i)));
}
function applyTemplate(i) {
  const t = S.templates[i];
  if (!t) return;
  S.blocks.pos = (t.positive || []).map(b => ({ token: b.token || "", text: b.text || "", weight: b.weight || 1, enabled: true }));
  S.blocks.neg = (t.negative || []).map(b => ({ token: b.token || "", text: b.text || "", weight: b.weight || 1, enabled: true }));
  const p = t.params || {};
  if (p.size) $("#p-size").value = p.size;
  if (p.steps) $("#p-steps").value = p.steps;
  if (p.cfg) $("#p-cfg").value = p.cfg;
  renderLanes(); doExpand(); toast("已套用模板：" + t.name);
}

/* ---------- run ---------- */
let polling = null;
async function runNow() {
  const v = await validateNow();
  if (!v.ok) { toast("结构检查没过，先修错误"); return; }
  const ex = await doExpand();
  if (!ex) return;
  const size = ($("#p-size").value || "1024x1536").split("x");
  const mode = $("#p-mode").value;
  const loras = ($("#p-loras").value || "").split(",").map(s => s.trim()).filter(Boolean).map(s => {
    const [n, w] = s.split(":"); return { name: n.trim(), weight: Number(w || 0.8) };
  });
  const body = {
    prompt: ex.positive, negative: ex.negative,
    width: Number(size[0]), height: Number(size[1]),
    steps: Number($("#p-steps").value || 28), cfg: Number($("#p-cfg").value || 5.5),
    seed: Number($("#p-seed").value || 0), prefix: $("#p-prefix").value || "img",
    loras, mode, blocks_pos: S.blocks.pos, blocks_neg: S.blocks.neg,
    reference: $("#p-ref").value || "", denoise: Number($("#p-denoise").value || 0.6)
  };
  $("#run").disabled = true; $("#run-msg").textContent = "提交中…";
  try {
    const r = await api("/api/run", { method: "POST", body: JSON.stringify(body) });
    toast("已排队，seed " + r.seed);
    pollJob(r.job_id);
  } catch (e) {
    $("#run").disabled = false; $("#run-msg").textContent = ""; toast("提交失败：" + e.message);
  }
}
function pollJob(jid) {
  clearInterval(polling);
  polling = setInterval(async () => {
    try {
      const j = await api("/api/job/" + jid);
      const pct = Math.round((j.progress || 0) * 100);
      $("#run-msg").textContent = j.status === "running" ? ("生成中 " + pct + "%  " + (j.elapsed || 0) + "s") : "";
      if (j.status === "done") {
        clearInterval(polling); $("#run").disabled = false;
        const imgs = j.result.images || [];
        $("#result").innerHTML = imgs.map(p =>
          '<img src="/api/img?path=' + encodeURIComponent(p) + '" style="width:100%;border-radius:12px;margin-top:8px;cursor:zoom-in" data-big="' + esc(p) + '">').join("");
        $$("#result img").forEach(im => im.onclick = () => showImage(im.dataset.big));
        $("#run-msg").textContent = "完成，用时 " + j.result.elapsed + "s";
      } else if (j.status === "error") {
        clearInterval(polling); $("#run").disabled = false;
        $("#run-msg").textContent = ""; toast("失败：" + (j.result.error || "未知错误"));
      }
    } catch (e) { clearInterval(polling); $("#run").disabled = false; }
  }, 1500);
}
function showImage(path) {
  openModal("查看", '<img src="/api/img?path=' + encodeURIComponent(path) + '" style="width:100%;border-radius:14px">' +
    '<div class="row2" style="margin-top:10px"><button class="ghost" id="im-recipe">查看参数</button>' +
    '<button class="ghost danger" id="im-del">删除</button></div>');
  $("#im-recipe").onclick = () => loadRecipe(path);
  $("#im-del").onclick = () => deleteImage(path);
}

/* ---------- gallery ---------- */
async function refreshGallery() {
  const q = $("#g-q").value || "";
  const r = await api("/api/gallery?limit=300&q=" + encodeURIComponent(q));
  S.gallery = r.items;
  $("#g-count").textContent = r.total + " 张";
  $("#g-grid").innerHTML = r.items.map(it =>
    '<div class="g-item"><img loading="lazy" src="/api/img?path=' + encodeURIComponent(it.path) + '" data-p="' + esc(it.path) + '">' +
    '<div class="g-meta"><b>' + esc(it.name) + "</b></div></div>").join("") || '<div class="hint">还没有图</div>';
  $$("#g-grid img").forEach(im => im.onclick = () => showImage(im.dataset.p));
}

/* ---------- library ---------- */
function renderLibrary() {
  const q = ($("#lib-q").value || "").toLowerCase();
  const keys = Object.keys(S.tokens).filter(k => !q || k.toLowerCase().includes(q) || (S.tokens[k] || "").toLowerCase().includes(q));
  $("#lib-count").textContent = keys.length + " 条";
  $("#lib-list").innerHTML = keys.map(k =>
    '<div class="lib-row" data-tok="' + esc(k) + '"><b>' + esc(k) + '</b><span class="hint">' +
    esc((S.notes[k] || S.tokens[k] || "").slice(0, 70)) + "</span></div>").join("");
  $$("#lib-list .lib-row").forEach(r => r.onclick = () => {
    const k = r.dataset.tok;
    $("#tk-name").value = k; $("#tk-text").value = S.tokens[k] || ""; $("#tk-note").value = S.notes[k] || "";
  });
}

/* ---------- outfits ---------- */
function renderGarments() {
  const keys = Object.keys(S.garments);
  $("#gm-list").innerHTML = keys.map(k =>
    '<div class="gm-item"><b>' + esc(S.garments[k].label || k) + '</b><span class="hint">' + esc(k) + " · " +
    esc(S.garments[k].use_for || "") + "</span></div>").join("");
  $$("#gm-list .gm-item").forEach((el, i) => el.onclick = () => editGarment(keys[i]));
  if (!S.curGarment && keys.length) editGarment(keys[0]);
}
function editGarment(key) {
  const g = S.garments[key] || {};
  S.curGarment = key;
  $("#gm-cur").textContent = key;
  $("#gm-key").value = key; $("#gm-label").value = g.label || "";
  $("#gm-use").value = g.use_for || ""; $("#gm-prompt").value = g.prompt || "";
  $("#gm-negative").value = g.negative || "";
}

/* ---------- recipe ---------- */
async function refreshRecipes() {
  const r = await api("/api/recipes?limit=200");
  $("#rc-count").textContent = r.total + " 条";
  $("#rc-list").innerHTML = r.items.map(it =>
    '<div class="lib-row" data-p="' + esc(it.path) + '"><b>' + esc(it.name) + "</b></div>").join("") ||
    '<div class="hint">还没有记录</div>';
  $$("#rc-list .lib-row").forEach(el => el.onclick = () => loadRecipe(el.dataset.p));
}
async function loadRecipe(path) {
  try {
    const r = await api("/api/recipe?path=" + encodeURIComponent(path));
    const blocks = (r.blocks_pos || []).map(b => b.token || b.text).filter(Boolean).join(", ");
    openModal("配方：" + (path.split(/[\\/]/).pop()),
      '<div class="kv"><span>模式</span><b>' + esc(r.mode) + "</b><span>种子</span><b>" + esc(r.seed) +
      "</b><span>尺寸</span><b>" + esc((r.size || []).join("×")) + "</b><span>步数 / CFG</span><b>" +
      esc(r.steps) + " / " + esc(r.cfg) + "</b><span>重绘</span><b>" + esc(r.denoise) + "</b></div>" +
      "<h4>正向</h4><pre>" + esc(r.positive) + "</pre><h4>负向</h4><pre>" + esc(r.negative) + "</pre>" +
      "<h4>积木</h4><pre>" + esc(blocks) + "</pre>");
  } catch (e) { toast(e.message); }
}

/* ---------- engine ---------- */
async function refreshEngine() {
  const e = await api("/api/engine");
  $("#eng-sum").textContent = e.up ? ("ComfyUI " + e.version) : "离线";
  const dev = (e.devices || [])[0] || {};
  $("#eng-kv").innerHTML =
    '<span>地址</span><b>' + esc(e.url) + "</b><span>设备</span><b>" + esc(dev.name || "-") + "</b>" +
    '<span>显存</span><b>' + (dev.vram_free ? Math.round(dev.vram_free / 1073741824) + " / " + Math.round(dev.vram_total / 1073741824) + " GB" : "-") + "</b>";
  $("#eng-wf").innerHTML = (e.workflows || []).map(w =>
    '<div class="wf-row"><b>' + esc(w.name) + "</b>" +
    (w.kind && w.kind !== w.name ? ' <span class="hint">' + esc(w.kind) + "</span>" : "") +
    (w.missing.length ? ' <span class="bad">missing: ' + esc(w.missing.join(", ")) + "</span>" : ' <span class="ok">OK</span>') + "</div>").join("");
  if (!$("#cf-unet").value) $("#cf-unet").value = S.model.unet_name || "";
  if (!$("#cf-clip").value) $("#cf-clip").value = S.model.clip_name || "";
  if (!$("#cf-vae").value) $("#cf-vae").value = S.model.vae_name || "";
  if (!$("#cf-cliptype").value) $("#cf-cliptype").value = S.model.clip_type || "stable_diffusion";
}
async function saveConfig() {
  const r = await api("/api/config", { method: "POST", body: JSON.stringify({
    unet_name: $("#cf-unet").value, clip_name: $("#cf-clip").value, vae_name: $("#cf-vae").value,
    clip_type: $("#cf-cliptype").value, comfy_dir: $("#cf-dir").value }) });
  toast(r.ok ? "已保存 config.json" : "保存失败");
  S.model = r.model || S.model;
}

/* ---------- maintenance ---------- */
async function refreshMaint() {
  const m = await api("/api/maintenance");
  $("#mt-sum").textContent = "可用 " + m.disk.free_gb + " / " + m.disk.total_gb + " GB";
  $("#mt-kv").innerHTML = "<span>输出目录</span><b>" + m.output_mb + " MB</b><span>回收站</span><b>" + m.trash_mb + " MB</b>";
  const d = await api("/api/docs");
  $("#doc-list").innerHTML = d.items.map(it => '<button class="doc-b" data-n="' + esc(it.name) + '">' + esc(it.name) + "</button>").join("");
  $$("#doc-list .doc-b").forEach(b => b.onclick = async () => {
    const r = await fetch("/api/doc?name=" + encodeURIComponent(b.dataset.n));
    openModal(b.dataset.n, "<pre style='white-space:pre-wrap'>" + esc(await r.text()) + "</pre>");
  });
}

/* ---------- boot ---------- */
async function boot() {
  const r = await api("/api/bootstrap");
  S.tokens = r.tokens; S.notes = r.notes; S.garments = r.garments; S.garmentDefault = r.garment_default;
  S.templates = r.templates; S.defaults = r.defaults; S.model = r.model; S.comfy = r.comfy;
  const d = S.defaults || {};
  if (d.size) $("#p-size").value = d.size;
  if (d.steps) $("#p-steps").value = d.steps;
  if (d.cfg) $("#p-cfg").value = d.cfg;
  $("#pill-comfy").textContent = r.comfy.up ? ("ComfyUI " + r.comfy.version) : "ComfyUI 离线";
  $("#eta").textContent = "预计 " + Math.round(Number(($("#p-size").value || "1024x1536").split("x")[0]) * Number(($("#p-size").value || "1024x1536").split("x")[1]) * Number($("#p-steps").value) * 1.6e-6 + 1.5) + "s";
  renderPalette(); renderTemplates(); renderLanes(); renderLibrary(); renderGarments(); refreshGallery(); refreshRecipes(); refreshMaint();
  const startTab = (location.hash || "").replace("#", "");
  if (startTab && $("#view-" + startTab)) switchTab(startTab, false);
  if (new URLSearchParams(location.search).get("demo")) applyTemplate(0);
  $("#pill-comfy").onclick = async () => {
    const b = await api("/api/bootstrap");
    if (b.comfy.up) window.open(b.comfy.url, "_blank", "noopener");
    else toast("ComfyUI 离线：先启动 ComfyUI，或在引擎页点「启动」");
  };
  setInterval(async () => {
    try { const q = await api("/api/bootstrap"); $("#pill-comfy").textContent = q.comfy.up ? ("ComfyUI " + q.comfy.version) : "ComfyUI 离线"; } catch (e) {}
  }, 15000);
}
function switchTab(name, push) {
  $$("#tabs button").forEach(x => x.classList.toggle("on", x.dataset.tab === name));
  $$(".view").forEach(v => v.style.display = "none");
  const v = $("#view-" + name); if (v) v.style.display = "block";
  if (push !== false && location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
  if (name === "gallery") refreshGallery();
  if (name === "recipe") refreshRecipes();
  if (name === "engine") refreshEngine();
  if (name === "maint") refreshMaint();
  if (name === "library") renderLibrary();
  if (name === "outfit") renderGarments();
}
$$("#tabs button").forEach(b => b.onclick = () => switchTab(b.dataset.tab));
window.addEventListener("hashchange", () => {
  const n = (location.hash || "").replace("#", "");
  if (n && $("#view-" + n)) switchTab(n, false);
});
$("#pal-toggle").onclick = e => {
  const body = $("#pal-body"), hidden = body.style.display === "none";
  body.style.display = hidden ? "" : "none";
  e.target.textContent = hidden ? "收起" : "展开";
};
$("#pal-search").oninput = renderPalette;
$("#pos-clear").onclick = () => { S.blocks.pos = []; renderLanes(); doExpand(); };
$("#neg-clear").onclick = () => { S.blocks.neg = []; renderLanes(); doExpand(); };
$("#val-run").onclick = () => validateNow();
$("#run").onclick = runNow;
$("#g-q").oninput = () => { clearTimeout(window._gq); window._gq = setTimeout(refreshGallery, 200); };
$("#lib-q").oninput = renderLibrary;
$("#tk-save").onclick = async () => {
  const name = $("#tk-name").value.trim();
  if (!name) return toast("名字不能空");
  await api("/api/token/save", { method: "POST", body: JSON.stringify({
    name, text: $("#tk-text").value, note: $("#tk-note").value }) });
  S.tokens[name.startsWith("@") ? name : "@" + name.toUpperCase()] = $("#tk-text").value;
  S.notes[name] = $("#tk-note").value;
  renderPalette(); renderLibrary(); toast("已保存 " + name);
};
$("#tk-del").onclick = async () => {
  const name = $("#tk-name").value.trim();
  if (!name) return;
  await api("/api/token/delete", { method: "POST", body: JSON.stringify({ name }) });
  delete S.tokens[name]; renderPalette(); renderLibrary(); toast("已删除 " + name);
};
$("#gm-save").onclick = async () => {
  const key = $("#gm-key").value.trim();
  if (!key) return toast("key 不能空");
  const r = await api("/api/garment/save", { method: "POST", body: JSON.stringify({
    key, label: $("#gm-label").value, use_for: $("#gm-use").value,
    prompt: $("#gm-prompt").value, negative: $("#gm-negative").value }) });
  S.garments = r.garments; renderGarments(); toast("已保存");
};
$("#gm-del").onclick = async () => {
  const key = $("#gm-key").value.trim();
  if (!key || !confirm("删除套装 " + key + "？")) return;
  try { const r = await api("/api/garment/delete", { method: "POST", body: JSON.stringify({ key }) });
    S.garments = r.garments; S.curGarment = ""; renderGarments(); }
  catch (e) { toast(e.message); }
};
$("#gm-new").onclick = () => {
  S.curGarment = "";
  $("#gm-key").value = ""; $("#gm-label").value = ""; $("#gm-use").value = "";
  $("#gm-prompt").value = ""; $("#gm-negative").value = ""; $("#gm-cur").textContent = "(新)";
};
$("#p-mode").onchange = () => {
  const i2i = $("#p-mode").value === "i2i";
  $("#ref-field").style.display = i2i ? "" : "none";
  $("#denoise-field").style.display = i2i ? "" : "none";
};
$("#p-size").onchange = $("#p-steps").oninput = () => {};
$("#eng-free").onclick = async () => { const r = await api("/api/comfy/free", { method: "POST" }); toast(r.ok ? "已释放" : ("失败：" + (r.error || ""))); };
$("#eng-start").onclick = async () => { const r = await api("/api/comfy/start", { method: "POST" }); toast(r.ok ? "正在启动…" : ("失败：" + (r.error || ""))); };
$("#eng-open").onclick = () => window.open(S.comfy.url || "http://127.0.0.1:8188", "_blank", "noopener");
$("#eng-check").onclick = async () => {
  const r = await api("/api/pipeline/check");
  const el = $("#eng-check-out"); el.style.display = "block";
  el.textContent = r.checks.map(c => (c.ok ? "OK   " : "FAIL ") + c.name + "  " + c.detail).join("\n");
};
$("#cf-save").onclick = saveConfig;
$("#mt-clean").onclick = async () => {
  if (!confirm("清空回收站？不可恢复。")) return;
  const r = await api("/api/maintenance/cleanup", { method: "POST" });
  toast("已删除 " + r.removed + " 个文件"); refreshMaint();
};
$("#mt-refresh").onclick = refreshMaint;
$("#pill-docs").onclick = async () => {
  const d = await api("/api/docs");
  openModal("文档", d.items.map(it => '<div><b>' + esc(it.name) + "</b></div>").join(""));
};
async function deleteImage(path) {
  if (!confirm("删除这张图？（进回收站，可在维护页清空）")) return;
  await api("/api/delete-image", { method: "POST", body: JSON.stringify({ path }) });
  $("#modal").classList.remove("on"); refreshGallery();
}
window.addEventListener("keydown", e => {
  if (e.key === "Escape") $("#modal").classList.remove("on");
});

/* ================= parity features ================= */
S.fav = new Set(JSON.parse(localStorage.getItem("sunloom.fav") || "[]"));
S.selMode = false;
S.sel = new Set();
const _origRenderPalette = renderPalette;
renderPalette = function () {
  const q = ($("#pal-search").value || "").toLowerCase();
  const groups = {};
  Object.keys(S.tokens).forEach(k => {
    const c = catOf(k);
    (groups[c] = groups[c] || []).push(k);
  });
  const order = ["收藏"].concat(CATS.map(c => c[0])).concat(["其他"]);
  let html = "";
  for (const c of order) {
    let items;
    if (c === "收藏") items = [...S.fav].filter(k => S.tokens[k]);
    else items = (groups[c] || []);
    items = items.filter(k => !q || k.toLowerCase().includes(q) || (S.tokens[k] || "").toLowerCase().includes(q));
    if (!items.length) continue;
    html += '<div class="pg"><div class="pg-head">' + (c === "收藏" ? "★ 收藏" : c) + '</div><div class="pg-items">';
    for (const k of items) {
      const isFav = S.fav.has(k);
      html += '<button class="pg-item" data-tok="' + esc(k) + '" title="' + esc(S.notes[k] || "") + '">' +
        '<span class="fav" data-fav="' + esc(k) + '">' + (isFav ? "★" : "☆") + "</span>" + esc(k) + "</button>";
    }
    html += "</div></div>";
  }
  $("#pal-body").innerHTML = html || '<div class="hint">没有匹配的积木</div>';
  $$("#pal-body .pg-item").forEach(b => b.onclick = () => addBlock(b.dataset.tok));
  $$("#pal-body .fav").forEach(s => s.onclick = e => {
    e.stopPropagation();
    const k = s.dataset.fav;
    if (S.fav.has(k)) S.fav.delete(k); else S.fav.add(k);
    localStorage.setItem("sunloom.fav", JSON.stringify([...S.fav]));
    renderPalette();
  });
};

/* undo / redo */
let hist = [], hIdx = -1, histLock = false;
function snapshot() {
  if (histLock) return;
  const snap = JSON.stringify({ p: S.blocks.pos, n: S.blocks.neg });
  if (hist[hIdx] === snap) return;
  hist = hist.slice(0, hIdx + 1);
  hist.push(snap);
  if (hist.length > 60) { hist.shift(); }
  hIdx = hist.length - 1;
}
const _origRenderLanes = renderLanes;
renderLanes = function () {
  _origRenderLanes();
  snapshot();
};
function undoRedo(dir) {
  if (!hist.length) return;
  const next = hIdx + dir;
  if (next < 0 || next >= hist.length) return;
  hIdx = next;
  histLock = true;
  const st = JSON.parse(hist[hIdx]);
  S.blocks.pos = st.p; S.blocks.neg = st.n;
  renderLanes();
  histLock = false;
  doExpand();
  toast(dir < 0 ? "已撤销" : "已重做");
}

/* gallery filters + selection + export */
const _origRefreshGallery = refreshGallery;
refreshGallery = async function () {
  const q = $("#g-q").value || "";
  const since = $("#g-since") ? $("#g-since").value : "";
  const recipe = $("#g-recipe") ? $("#g-recipe").value : "";
  const r = await api("/api/gallery?limit=300&q=" + encodeURIComponent(q) +
    "&since=" + encodeURIComponent(since) + "&recipe=" + encodeURIComponent(recipe));
  S.gallery = r.items;
  $("#g-count").textContent = r.total + " 张";
  $("#g-grid").innerHTML = r.items.map(it =>
    '<div class="g-item"><img loading="lazy" src="/api/img?path=' + encodeURIComponent(it.path) +
    '" data-p="' + esc(it.path) + '">' +
    (S.selMode ? '<input type="checkbox" class="g-sel" data-p="' + esc(it.path) + '"' +
      (S.sel.has(it.path) ? " checked" : "") + ">" : "") +
    '<div class="g-meta"><b>' + esc(it.name) + "</b>" +
    (it.has_recipe ? ' <span class="ok">·配方</span>' : "") + "</div></div>").join("") ||
    '<div class="hint">还没有图</div>';
  $$("#g-grid img").forEach(im => im.onclick = () => showImage(im.dataset.p));
  $$("#g-grid .g-sel").forEach(cb => cb.onchange = () => {
    if (cb.checked) S.sel.add(cb.dataset.p); else S.sel.delete(cb.dataset.p);
    $("#g-export").textContent = "导出选中(" + S.sel.size + ")";
  });
};

async function exportSelected() {
  if (!S.sel.size) return toast("先勾选图片");
  const r = await api("/api/export", { method: "POST", body: JSON.stringify({ paths: [...S.sel] }) });
  toast("已导出 " + r.name);
  const el = $("#g-export");
  if (el) {
    el.textContent = "下载 " + r.name;
    el.onclick = () => { window.location = r.url; };
  }
}

/* trash */
async function refreshTrash() {
  const t = await api("/api/trash");
  const el = $("#mt-trash-list");
  if (!el) return;
  const cnt = $("#mt-trash-count");
  if (cnt) cnt.textContent = t.count + " 个 / " + t.mb + " MB";
  el.innerHTML = t.items.map(i =>
    '<div class="lib-row"><b>' + esc(i.name) + '</b><span class="hint">' + esc(i.day) +
    ' · ' + Math.round(i.size / 1024) + ' KB <button class="ghost tiny" data-restore="' + esc(i.name) + '">恢复</button></span></div>'
  ).join("") || '<div class="hint">回收站是空的</div>';
  $$("#mt-trash-list [data-restore]").forEach(b => b.onclick = async () => {
    await api("/api/trash/restore", { method: "POST", body: JSON.stringify({ name: b.dataset.restore }) });
    toast("已恢复"); refreshTrash(); refreshGallery();
  });
}

/* batch */
async function openBatch() { $("#batch-modal").classList.add("on"); }
async function runBatch() {
  const size = ($("#bt-size").value || "1024x1536").split("x");
  const ex = await doExpand();
  if (!ex) return;
  const body = {
    prompt: ex.positive, negative: ex.negative,
    count: Number($("#bt-count").value || 4), seed: Number($("#bt-seed").value || 0),
    width: Number(size[0]), height: Number(size[1]),
    steps: Number($("#bt-steps").value || 28), cfg: Number($("#p-cfg").value || 5.5),
    prefix: $("#bt-prefix").value || "batch",
    loras: ($("#p-loras").value || "").split(",").map(s => s.trim()).filter(Boolean).map(s => {
      const [n, w] = s.split(":"); return { name: n.trim(), weight: Number(w || 0.8) };
    }),
    blocks_pos: S.blocks.pos, blocks_neg: S.blocks.neg
  };
  try {
    const r = await api("/api/batch", { method: "POST", body: JSON.stringify(body) });
    $("#bt-msg").textContent = "开始 " + r.count + " 张…";
    $("#bt-out").innerHTML = "";
    const t = setInterval(async () => {
      const j = await api("/api/job/" + r.job_id);
      $("#bt-msg").textContent = j.status === "running"
        ? "生成中 " + Math.round((j.progress || 0) * 100) + "%"
        : (j.status === "done" ? "完成 " + ((j.result.images || []).length) + " 张" : "失败");
      if (j.status !== "running") {
        clearInterval(t);
        const imgs = (j.result && j.result.images) || [];
        $("#bt-out").innerHTML = imgs.map(p =>
          '<div class="g-item"><img src="/api/img?path=' + encodeURIComponent(p) + '" data-p="' + esc(p) + '"></div>').join("");
        $$("#bt-out img").forEach(im => im.onclick = () => showImage(im.dataset.p));
        refreshGallery();
      }
    }, 1500);
  } catch (e) { $("#bt-msg").textContent = "失败：" + e.message; }
}

/* paint */
const P = { img: null, mask: null, drawing: false, start: null, mode: "brush" };
function ptCanvas() { return $("#pt-canvas"); }
function ptSetupCanvas() {
  const img = $("#pt-img"), c = ptCanvas();
  if (!img.src) return;
  const r = img.getBoundingClientRect();
  c.width = Math.max(1, Math.round(r.width));
  c.height = Math.max(1, Math.round(r.height));
  c.style.width = r.width + "px"; c.style.height = r.height + "px";
}
function ptLoad(path) {
  return new Promise(res => {
    const img = $("#pt-img");
    img.onload = () => { P.img = path; ptSetupCanvas(); $("#pt-hint").textContent = path; $("#pt-run").disabled = false; res(true); };
    img.onerror = () => { toast("图片加载失败"); res(false); };
    img.src = "/api/img?path=" + encodeURIComponent(path);
  });
}
function ptPos(e, c) {
  const r = c.getBoundingClientRect();
  return [e.clientX - r.left, e.clientY - r.top];
}
function ptBind() {
  const c = ptCanvas();
  c.onmousedown = e => {
    if (!P.img) return;
    P.drawing = true; P.start = ptPos(e, c);
    if (P.mode === "box") {
      P.snapshot = c.getContext("2d").getImageData(0, 0, c.width, c.height);
    }
  };
  c.onmousemove = e => {
    if (!P.drawing) return;
    const ctx = c.getContext("2d");
    const [x, y] = ptPos(e, c);
    if (P.mode === "box") {
      ctx.putImageData(P.snapshot, 0, 0);
      ctx.fillStyle = "rgba(255,255,255,.55)";
      const w = x - P.start[0], h = y - P.start[1];
      ctx.fillRect(P.start[0], P.start[1], w, h);
    } else {
      ctx.globalCompositeOperation = P.mode === "erase" ? "destination-out" : "source-over";
      ctx.fillStyle = "rgba(255,255,255,.6)";
      ctx.beginPath();
      ctx.arc(x, y, Number($("#pt-size").value || 30) / 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalCompositeOperation = "source-over";
    }
  };
  c.onmouseup = c.onmouseleave = () => { P.drawing = false; };
}
function ptMaskB64() {
  const c = ptCanvas();
  const d = c.getContext("2d").getImageData(0, 0, c.width, c.height);
  let painted = false;
  for (let i = 3; i < d.data.length; i += 4) { if (d.data[i] > 8) { painted = true; break; } }
  if (!painted) return "";
  const out = document.createElement("canvas");
  out.width = c.width; out.height = c.height;
  const ctx = out.getContext("2d");
  ctx.fillStyle = "#000"; ctx.fillRect(0, 0, out.width, out.height);
  ctx.drawImage(c, 0, 0);
  return out.toDataURL("image/png");
}
async function ptRun() {
  const b64 = ptMaskB64();
  if (!b64) return toast("先在图上画一块区域");
  $("#pt-run").disabled = true;
  $("#pt-msg").textContent = "提交中…";
  try {
    const r = await api("/api/inpaint", { method: "POST", body: JSON.stringify({
      image: P.img, mask_b64: b64, feather: Number($("#pt-feather").value || 10),
      prompt: $("#pt-prompt").value || "(detailed hand:1.4), same art style",
      denoise: Number($("#pt-denoise").value || 0.55), steps: Number($("#pt-steps").value || 26),
      cfg: 5.2, prefix: "repaint"
    }) });
    const t = setInterval(async () => {
      const j = await api("/api/job/" + r.job_id);
      $("#pt-msg").textContent = j.status === "running" ? "重绘中 " + Math.round((j.progress || 0) * 100) + "%" : "";
      if (j.status !== "running") {
        clearInterval(t); $("#pt-run").disabled = false;
        if (j.status === "done") {
          const p = j.result.images[0];
          $("#pt-msg").innerHTML = '<a class="ok" href="/api/img?path=' + encodeURIComponent(p) + '" target="_blank">完成，打开结果</a>';
          refreshGallery();
        } else {
          $("#pt-msg").textContent = "失败：" + (j.result.error || "");
        }
      }
    }, 1500);
  } catch (e) { $("#pt-run").disabled = false; $("#pt-msg").textContent = "失败：" + e.message; }
}
function ptSaveMask() {
  const b64 = ptMaskB64();
  if (!b64) return toast("蒙版是空的");
  api("/api/mask/save", { method: "POST", body: JSON.stringify({ image: P.img, mask_b64: b64 }) })
    .then(() => { toast("已保存蒙版"); refreshMasks(); });
}
async function refreshMasks() {
  if (!P.img) return;
  const r = await api("/api/mask/list?image=" + encodeURIComponent(P.img));
  $("#pt-mask-list").innerHTML = r.items.map(it =>
    '<img class="mask-thumb" src="/api/mask/img?name=' + encodeURIComponent(it.name) + '" title="' + esc(it.name) + '">').join("") ||
    '<div class="hint">这张图还没有存过蒙版</div>';
  $$("#pt-mask-list .mask-thumb").forEach(im => im.onclick = () => ptApplyMask(im.title));
}
function ptApplyMask(name) {
  const img = new Image();
  img.onload = () => {
    const c = ptCanvas();
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.drawImage(img, 0, 0, c.width, c.height);
    toast("已套用蒙版");
  };
  img.src = "/api/mask/img?name=" + encodeURIComponent(name);
}
async function rpRun() {
  const ref = $("#rp-ref2").value.trim();
  if (!ref) return toast("先填参考图路径");
  const ex = await doExpand();
  $("#rp-msg").textContent = "提交中…";
  try {
    const r = await api("/api/reproduce", { method: "POST", body: JSON.stringify({
      image: ref, denoise: Number($("#rp-denoise").value || 0.55),
      prompt: $("#rp-prompt").value || (ex && ex.positive) || "",
      negative: (ex && ex.negative) || "", steps: Number($("#rp-steps").value || 30),
      cfg: Number($("#p-cfg").value || 5.5), prefix: "repro"
    }) });
    const t = setInterval(async () => {
      const j = await api("/api/job/" + r.job_id);
      $("#rp-msg").textContent = j.status === "running" ? "生成中 " + Math.round((j.progress || 0) * 100) + "%" : "";
      if (j.status !== "running") {
        clearInterval(t);
        if (j.status === "done") {
          const p = j.result.images[0];
          $("#rp-out").innerHTML = '<img src="/api/img?path=' + encodeURIComponent(p) + '" style="width:100%;border-radius:12px" data-p="' + esc(p) + '">';
          $$("#rp-out img").forEach(im => im.onclick = () => showImage(im.dataset.p));
          refreshGallery();
        } else { $("#rp-msg").textContent = "失败：" + (j.result.error || ""); }
      }
    }, 1500);
  } catch (e) { $("#rp-msg").textContent = "失败：" + e.message; }
}

/* tab + bindings */
const _origSwitchTab = switchTab;
switchTab = function (name, push) {
  _origSwitchTab(name, push);
  if (name === "paint") { setTimeout(refreshMasks, 50); }
  if (name === "maint") { setTimeout(refreshTrash, 50); }
};
$("#g-since") && ($("#g-since").onchange = () => refreshGallery());
$("#g-recipe") && ($("#g-recipe").onchange = () => refreshGallery());
$("#g-select") && ($("#g-select").onclick = () => {
  S.selMode = !S.selMode; S.sel.clear();
  $("#g-select").classList.toggle("primary", S.selMode);
  $("#g-export").style.display = S.selMode ? "" : "none";
  $("#g-export").textContent = "导出选中(0)";
  refreshGallery();
});
$("#g-export") && ($("#g-export").onclick = exportSelected);
$("#rc-backfill") && ($("#rc-backfill").onclick = async () => {
  const r = await api("/api/recipe/backfill", { method: "POST", body: "{}" });
  toast("回填 " + r.recovered + " 条");
  refreshRecipes();
});
$("#batch-open") && ($("#batch-open").onclick = openBatch);
$("#batch-close") && ($("#batch-close").onclick = () => $("#batch-modal").classList.remove("on"));
$("#bt-run") && ($("#bt-run").onclick = runBatch);
$("#pt-load") && ($("#pt-load").onclick = () => {
  const p = prompt("图片路径（本地绝对路径，或在画廊里点「大图」后复制）");
  if (p) ptLoad(p.trim());
});
$("#pt-clear") && ($("#pt-clear").onclick = () => {
  const c = ptCanvas(); c.getContext("2d").clearRect(0, 0, c.width, c.height);
});
$("#pt-mode") && ($("#pt-mode").onchange = e => { P.mode = e.target.value; });
$("#pt-run") && ($("#pt-run").onclick = ptRun);
$("#pt-mask-save") && ($("#pt-mask-save").onclick = ptSaveMask);
$("#rp-run") && ($("#rp-run").onclick = rpRun);
$("#mt-trash-restore-all") && ($("#mt-trash-restore-all").onclick = async () => {
  const r = await api("/api/trash/restore-all", { method: "POST", body: "{}" });
  toast("已恢复 " + r.count + " 个"); refreshTrash(); refreshGallery();
});
$("#mt-trash-purge") && ($("#mt-trash-purge").onclick = async () => {
  if (!confirm("清空回收站？不可恢复。")) return;
  const r = await api("/api/trash/purge", { method: "POST", body: "{}" });
  toast("已删除 " + r.removed + " 个"); refreshTrash();
});
window.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
    e.preventDefault(); undoRedo(e.shiftKey ? 1 : -1);
  }
  if (e.key === "Escape") $("#batch-modal").classList.remove("on");
});
ptBind();
setTimeout(ptBind, 500);



/* image modal with inpaint + handfix actions */
showImage = function (path) {
  openModal("查看",
    '<img src="/api/img?path=' + encodeURIComponent(path) + '" style="width:100%;border-radius:14px">' +
    '<div class="row2" style="margin-top:10px">' +
      '<button class="ghost" id="im-recipe">查看参数</button>' +
      '<button class="ghost" id="im-paint">去重绘</button>' +
    '</div><div class="row2" style="margin-top:8px">' +
      '<button class="ghost" id="im-hand">手部精修</button>' +
      '<button class="ghost danger" id="im-del">删除</button>' +
    '</div><div class="hint" id="im-msg" style="margin-top:8px"></div>');
  $("#im-recipe").onclick = () => loadRecipe(path);
  $("#im-del").onclick = () => deleteImage(path);
  $("#im-paint").onclick = () => { $("#modal").classList.remove("on"); switchTab("paint"); ptLoad(path); };
  $("#im-hand").onclick = () => runHandfix(path);
};
async function runHandfix(path) {
  const box = prompt("手部大致区域：x,y,w,h（相对原图像素）", "400,600,200,200");
  if (!box) return;
  $("#im-msg").textContent = "提交手部精修…";
  try {
    const r = await api("/api/handfix", { method: "POST", body: JSON.stringify({
      image: path, box: box.trim(), feather: 10, denoise: 0.45,
      steps: 26, cfg: 5.0, prefix: "handfix"
    }) });
    const t = setInterval(async () => {
      const j = await api("/api/job/" + r.job_id);
      $("#im-msg").textContent = j.status === "running"
        ? "精修中 " + Math.round((j.progress || 0) * 100) + "%" : "";
      if (j.status !== "running") {
        clearInterval(t);
        if (j.status === "done") {
          const p = j.result.images[0];
          $("#im-msg").innerHTML = '<a class="ok" href="/api/img?path=' + encodeURIComponent(p) + '" target="_blank">完成，打开结果</a>';
          refreshGallery();
        } else {
          $("#im-msg").textContent = "失败：" + (j.result.error || "");
        }
      }
    }, 1500);
  } catch (e) { $("#im-msg").textContent = "失败：" + e.message; }
}


/* ================= library / outfit / training parity ================= */
const CATS_UI = ["主体","姿势","表情","手发","机位","打光","氛围","服装","场景","道具","构图","风格","负向","其他"];
const CAT_COLOR = {"主体":"#7fd7ff","姿势":"#ffd166","表情":"#ff9fc4","手发":"#c9a7ff",
  "机位":"#9be7c4","打光":"#ffe08a","氛围":"#8ecbff","服装":"#ffb37a","场景":"#a8e6a1",
  "道具":"#f2c0ff","构图":"#8fd3d3","风格":"#ffcf9e","负向":"#ff9b9b","其他":"#b8c0cc"};
const _libCtx = { q: "", cat: "", sort: true };

function fillCatSelects() {
  const opts = CATS_UI.map(c => '<option value="' + c + '">' + c + "</option>").join("");
  const lc = $("#lib-cat");
  if (lc && lc.options.length <= 1) lc.insertAdjacentHTML("beforeend", opts);
  const tc = $("#tk-cat");
  if (tc && tc.options.length === 0) tc.innerHTML = opts;
}

renderLibrary = async function () {
  fillCatSelects();
  const q = ($("#lib-q").value || "");
  const r = await api("/api/library?q=" + encodeURIComponent(q) + "&cat=" + encodeURIComponent($("#lib-cat").value || ""));
  $("#lib-count").textContent = r.total + " 条";
  const items = r.items.slice();
  if (_libCtx.sort) items.sort((a, b) => a.name.localeCompare(b.name));
  else items.sort((a, b) => (a.category + a.name).localeCompare(b.category + b.name));
  $("#lib-list").innerHTML = items.map(it =>
    '<div class="lib-row" data-tok="' + esc(it.name) + '">' +
      '<b><i class="cdot" style="background:' + (CAT_COLOR[it.category] || "#888") + '"></i>' +
      esc(it.name) + ' <span class="hint">' + esc(it.category) + "</span></b>" +
      '<span class="hint">' + esc((it.note || it.text || "").slice(0, 78)) + "</span></div>").join("");
  $$("#lib-list .lib-row").forEach(row => row.onclick = () => {
    const k = row.dataset.tok;
    $("#tk-name").value = k; $("#tk-text").value = S.tokens[k] || "";
    $("#tk-note").value = S.notes[k] || "";
    const it = items.find(x => x.name === k);
    if (it) $("#tk-cat").value = it.category;
  });
};

/* library actions */
$("#lib-sort") && ($("#lib-sort").onclick = () => {
  _libCtx.sort = !_libCtx.sort;
  $("#lib-sort").textContent = _libCtx.sort ? "A→Z" : "分组";
  renderLibrary();
});
$("#lib-cat") && ($("#lib-cat").onchange = () => renderLibrary());
$("#lib-export") && ($("#lib-export").onclick = () => { window.location = "/api/library/export"; });
$("#lib-import") && ($("#lib-import").onclick = async () => {
  const txt = prompt("粘贴词库 JSON（或填本地路径）");
  if (!txt) return;
  const isPath = txt.length < 300 && !txt.trim().startsWith("{");
  const r = await api("/api/library/import", { method: "POST",
    body: JSON.stringify(isPath ? { path: txt.trim() } : { data: txt }) });
  toast("导入完成，新增 " + r.added + " 条");
  const b = await api("/api/bootstrap");
  S.tokens = b.tokens; S.notes = b.notes;
  renderPalette(); renderLibrary();
});
$("#tk-save") && ($("#tk-save").addEventListener("click", async () => {
  const name = $("#tk-name").value.trim();
  if (!name) return toast("名字不能空");
  await api("/api/token/save", { method: "POST", body: JSON.stringify({
    name, text: $("#tk-text").value, note: $("#tk-note").value }) });
  await api("/api/token/meta", { method: "POST", body: JSON.stringify({
    name: name.startsWith("@") ? name : "@" + name.toUpperCase(),
    category: $("#tk-cat").value, note: $("#tk-note").value }) });
  const b = await api("/api/bootstrap");
  S.tokens = b.tokens; S.notes = b.notes;
  renderPalette(); renderLibrary(); toast("已保存");
}));

/* outfit full */
const _origEditGarment = editGarment;
editGarment = function (key) {
  _origEditGarment(key);
  const g = S.garments[key] || {};
  if ($("#gm-material")) $("#gm-material").value = g.material || "";
  if ($("#gm-drape")) $("#gm-drape").value = g.drape || "";
  if ($("#gm-preview")) $("#gm-preview").textContent =
    "展开预览：" + [g.prompt, g.material, g.drape].filter(Boolean).join(", ");
  if ($("#gm-default")) $("#gm-default").textContent =
    (S.garmentDefault === key) ? "★ 当前默认" : "设为默认";
};
const _origRenderGarments = renderGarments;
renderGarments = function () {
  _origRenderGarments();
  $$("#gm-list .gm-item").forEach((el, i) => {
    const keys = Object.keys(S.garments);
    if (keys[i] === S.garmentDefault) el.innerHTML = el.innerHTML.replace("<b>", '<b style="color:#ffd98a">★ ');
  });
};
$("#gm-default") && ($("#gm-default").onclick = async () => {
  const key = $("#gm-key").value.trim();
  if (!key) return;
  const r = await api("/api/garment/default", { method: "POST", body: JSON.stringify({ key }) });
  S.garmentDefault = r.default;
  renderGarments(); editGarment(key); toast("默认套装：" + key);
});
$("#gm-dup") && ($("#gm-dup").onclick = async () => {
  const key = $("#gm-key").value.trim();
  if (!key) return;
  const r = await api("/api/garment/duplicate", { method: "POST", body: JSON.stringify({ key }) });
  S.garments = r.garments; renderGarments(); editGarment(r.key); toast("已复制为 " + r.key);
});
$("#gm-export") && ($("#gm-export").onclick = () => { window.location = "/api/garments/export"; });
$("#gm-import") && ($("#gm-import").onclick = async () => {
  const txt = prompt("粘贴套装 JSON（或填本地路径）");
  if (!txt) return;
  const isPath = txt.length < 300 && !txt.trim().startsWith("{");
  const r = await api("/api/garments/import", { method: "POST",
    body: JSON.stringify(isPath ? { path: txt.trim() } : { data: txt }) });
  S.garments = r.garments; renderGarments(); toast("导入 " + r.added + " 套");
});
const _origGmSave = $("#gm-save") && $("#gm-save").onclick;
$("#gm-save") && ($("#gm-save").onclick = async () => {
  const key = $("#gm-key").value.trim();
  if (!key) return toast("key 不能空");
  const r = await api("/api/garment/save", { method: "POST", body: JSON.stringify({
    key, label: $("#gm-label").value, use_for: $("#gm-use").value,
    prompt: $("#gm-prompt").value, negative: $("#gm-negative").value,
    material: $("#gm-material").value, drape: $("#gm-drape").value }) });
  S.garments = r.garments; S.garmentDefault = r.default || S.garmentDefault;
  renderGarments(); editGarment(key); toast("已保存");
});

/* datasets / train / tag */
async function refreshDatasets() {
  const r = await api("/api/datasets");
  const opts = r.items.map(d => '<option value="' + esc(d.name) + '">' + esc(d.name) + " (" + d.images + " 张)</option>").join("") ||
    '<option value="">先放数据集到 station/data/datasets/</option>';
  ["#tg-dataset", "#tr-dataset"].forEach(sel => { const el = $(sel); if (el) el.innerHTML = opts; });
  if ($("#tr-sum")) {
    const c = await api("/api/train/check");
    $("#tr-sum").textContent = c.ok ? "kohya 就绪" : "kohya 未配置";
  }
  if ($("#tg-sum")) {
    const c = await api("/api/tag/check");
    $("#tg-sum").textContent = c.ok ? "onnxruntime 就绪" : ("缺依赖：" + (c.error || "").slice(0, 40));
  }
}
function pollLogs(jid, outSel, msgSel, onDone) {
  const t = setInterval(async () => {
    const j = await api("/api/job/" + jid);
    const el = $(outSel);
    if (el) {
      el.textContent = (j.logs || []).join("\n");
      el.scrollTop = el.scrollHeight;
    }
    if (msgSel) $(msgSel).textContent = j.status === "running" ? "运行中 " + Math.round((j.progress || 0) * 100) + "%" : "";
    if (j.status !== "running") {
      clearInterval(t);
      if (msgSel) $(msgSel).textContent = j.status === "done" ? "完成" : ("失败：" + ((j.result && (j.result.error || j.result.exit)) || ""));
      if (onDone) onDone(j);
    }
  }, 1500);
}
$("#tg-run") && ($("#tg-run").onclick = async () => {
  try {
    const r = await api("/api/tag/start", { method: "POST", body: JSON.stringify({
      dataset: $("#tg-dataset").value, threshold: Number($("#tg-thresh").value || 0.35),
      trigger: $("#tg-trigger").value, extra: $("#tg-extra").value,
      write: $("#tg-write").checked, preview: Number($("#tg-preview").value || 5) }) });
    $("#tg-out").textContent = "";
    pollLogs(r.job_id, "#tg-out", "#tg-msg");
  } catch (e) { $("#tg-msg").textContent = "失败：" + e.message; }
});
$("#tr-run") && ($("#tr-run").onclick = async () => {
  try {
    const r = await api("/api/train/start", { method: "POST", body: JSON.stringify({
      dataset: $("#tr-dataset").value, output: $("#tr-output").value || "my_lora",
      dim: Number($("#tr-dim").value || 32), epochs: Number($("#tr-epochs").value || 10),
      batch: Number($("#tr-batch").value || 1), lr: Number($("#tr-lr").value || 1e-4),
      trigger: $("#tr-trigger").value, base_model: $("#tr-base").value }) });
    $("#tr-out").textContent = "";
    pollLogs(r.job_id, "#tr-out", "#tr-msg");
  } catch (e) { $("#tr-msg").textContent = "失败：" + e.message; }
});

/* tab hook */
const _origSwitchTab2 = switchTab;
switchTab = function (name, push) {
  _origSwitchTab2(name, push);
  if (name === "tag" || name === "train") setTimeout(refreshDatasets, 50);
  if (name === "library") setTimeout(renderLibrary, 50);
};


/* ================= rich UI parity ================= */
let LORA_CACHE = [];

function loraRows() {
  return $$("#lora-rows .lora-row").map(row => {
    const name = row.querySelector("select").value;
    const w = Number(row.querySelector("input").value || 0.8);
    return name ? { name, weight: w } : null;
  }).filter(Boolean);
}
function loraRowHtml(name, weight) {
  const opts = LORA_CACHE.map(it => '<option value="' + esc(it.name) + '"' +
    (it.name === name ? " selected" : "") + ">" + esc(it.name) + "</option>").join("");
  return '<div class="lora-row"><select>' + opts + "</select>" +
    '<input type="number" step="0.05" value="' + (weight || 0.8) + '">' +
    '<button class="bx">×</button></div>';
}
async function initLoras() {
  try {
    const r = await api("/api/loras");
    LORA_CACHE = r.items || [];
    const box = $("#lora-rows");
    if (!box) return;
    box.innerHTML = "";
    const defaults = r.defaults || [];
    if (defaults.length) {
      defaults.forEach(d => box.insertAdjacentHTML("beforeend", loraRowHtml(d.name, d.weight)));
    } else if (LORA_CACHE.length) {
      box.insertAdjacentHTML("beforeend", loraRowHtml(LORA_CACHE[0].name, 0.8));
    }
    bindLoraRows();
  } catch (e) {}
}
function bindLoraRows() {
  $$("#lora-rows .lora-row .bx").forEach(b => b.onclick = () => {
    b.closest(".lora-row").remove();
  });
}
$("#lora-add") && ($("#lora-add").onclick = () => {
  if (!LORA_CACHE.length) return toast("没找到 LoRA 文件（先绑定 comfy_dir）");
  $("#lora-rows").insertAdjacentHTML("beforeend", loraRowHtml(LORA_CACHE[0].name, 0.8));
  bindLoraRows();
});

/* palette rail + drag & drop */
const _palRich = renderPalette;
renderPalette = function () {
  _palRich();
  const body = $("#pal-body"), rail = $("#pal-rail");
  if (!body || !rail) return;
  const heads = $$("#pal-body .pg-head");
  rail.innerHTML = heads.map((h, i) =>
    '<button class="rail-dot" data-i="' + i + '" title="' + esc(h.textContent) + '">' +
    esc(h.textContent.replace("★ ", "").slice(0, 2)) + "</button>").join("");
  $$("#pal-rail .rail-dot").forEach(btn => btn.onclick = () => {
    const t = heads[Number(btn.dataset.i)];
    if (t) t.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $$("#pal-body .pg-item").forEach(b => {
    b.setAttribute("draggable", "true");
    b.ondragstart = e => e.dataTransfer.setData("text/plain", b.dataset.tok);
  });
};
const _lanesRich = renderLanes;
renderLanes = function () {
  _lanesRich();
  $$(".lane-body").forEach(el => {
    el.ondragover = e => { e.preventDefault(); el.classList.add("drop-on"); };
    el.ondragleave = () => el.classList.remove("drop-on");
    el.ondrop = e => {
      e.preventDefault(); el.classList.remove("drop-on");
      const tok = e.dataTransfer.getData("text/plain");
      if (!tok) return;
      const neg = el.id === "lane-neg";
      const lane = neg ? S.blocks.neg : S.blocks.pos;
      if (!lane.find(b => b.token === tok)) lane.push({ token: tok, weight: 1 });
      renderLanes(); doExpand();
    };
  });
};

/* lane tools */
$$("[data-add]").forEach(btn => btn.onclick = () => {
  const kind = btn.dataset.add;
  if (kind === "desc") { $("#desc-text").focus(); return; }
  const text = prompt(kind === "tag" ? "标签文本（会作为一个块加入）" : "文本块（会作为一个块加入）");
  if (!text) return;
  const neg = btn.closest(".lane") && btn.closest(".lane").querySelector("#lane-neg");
  const lane = neg ? S.blocks.neg : S.blocks.pos;
  lane.push({ token: "", text: text.trim(), weight: 1 });
  renderLanes(); doExpand();
});

/* description card */
function descAdd(neg) {
  const text = $("#desc-text").value.trim();
  if (!text) return toast("先写一段描述");
  const w = Number($("#desc-weight").value || 1);
  (neg ? S.blocks.neg : S.blocks.pos).push({ token: "", text, weight: w });
  renderLanes(); doExpand();
  toast("已插入" + (neg ? "负向" : "正向"));
}
$("#desc-pos") && ($("#desc-pos").onclick = () => descAdd(false));
$("#desc-neg") && ($("#desc-neg").onclick = () => descAdd(true));
$("#desc-save") && ($("#desc-save").onclick = async () => {
  const text = $("#desc-text").value.trim();
  if (!text) return toast("先写一段描述");
  const name = prompt("存成积木，名字（@开头）", "@DESC_MY");
  if (!name) return;
  await api("/api/token/save", { method: "POST", body: JSON.stringify({
    name, text, note: "来自描述卡片" }) });
  const b = await api("/api/bootstrap");
  S.tokens = b.tokens; S.notes = b.notes;
  renderPalette(); renderLibrary(); toast("已保存为 " + name);
});

/* preview counts */
const _expandRich = doExpand;
doExpand = async function () {
  const r = await _expandRich();
  if (r && $("#prev-len")) {
    $("#prev-len").textContent = "正向 " + r.pos_len + " / 负向 " + r.neg_len +
      " / 用了 " + (r.used || []).length + " 个宏";
  }
  return r;
};

/* run with lora rows */
runNow = async function () {
  const v = await validateNow();
  if (!v.ok) { toast("结构检查没过，先修错误"); return; }
  const ex = await doExpand();
  if (!ex) return;
  const size = ($("#p-size").value || "1024x1536").split("x");
  const body = {
    prompt: ex.positive, negative: ex.negative,
    width: Number(size[0]), height: Number(size[1]),
    steps: Number($("#p-steps").value || 28), cfg: Number($("#p-cfg").value || 5.5),
    seed: Number($("#p-seed").value || 0), prefix: $("#p-prefix").value || "img",
    loras: loraRows(), mode: $("#p-mode").value, blocks_pos: S.blocks.pos, blocks_neg: S.blocks.neg,
    reference: $("#p-ref").value || "", denoise: Number($("#p-denoise").value || 0.6)
  };
  $("#run").disabled = true; $("#run-msg").textContent = "提交中…";
  try {
    const r = await api("/api/run", { method: "POST", body: JSON.stringify(body) });
    toast("已排队，seed " + r.seed);
    pollJob(r.job_id);
  } catch (e) { $("#run").disabled = false; $("#run-msg").textContent = ""; toast("提交失败：" + e.message); }
};
const _batchRich = typeof runBatch === "function" ? runBatch : null;
runBatch = async function () {
  const size = ($("#bt-size").value || "1024x1536").split("x");
  const ex = await doExpand();
  if (!ex) return;
  const body = {
    prompt: ex.positive, negative: ex.negative,
    count: Number($("#bt-count").value || 4), seed: Number($("#bt-seed").value || 0),
    width: Number(size[0]), height: Number(size[1]),
    steps: Number($("#bt-steps").value || 28), cfg: Number($("#p-cfg").value || 5.5),
    prefix: $("#bt-prefix").value || "batch", loras: loraRows(),
    blocks_pos: S.blocks.pos, blocks_neg: S.blocks.neg
  };
  const r = await api("/api/batch", { method: "POST", body: JSON.stringify(body) });
  $("#bt-msg").textContent = "开始 " + r.count + " 张…";
  $("#bt-out").innerHTML = "";
  const t = setInterval(async () => {
    const j = await api("/api/job/" + r.job_id);
    $("#bt-msg").textContent = j.status === "running"
      ? "生成中 " + Math.round((j.progress || 0) * 100) + "%"
      : (j.status === "done" ? "完成 " + ((j.result.images || []).length) + " 张" : "失败");
    if (j.status !== "running") {
      clearInterval(t);
      const imgs = (j.result && j.result.images) || [];
      $("#bt-out").innerHTML = imgs.map(p =>
        '<div class="g-item"><img src="/api/img?path=' + encodeURIComponent(p) + '" data-p="' + esc(p) + '"></div>').join("");
      $$("#bt-out img").forEach(im => im.onclick = () => showImage(im.dataset.p));
      refreshGallery();
    }
  }, 1500);
};

/* self check + overview */
$("#pill-selfcheck") && ($("#pill-selfcheck").onclick = async () => {
  const r = await api("/api/pipeline/check");
  openModal("环境自检",
    '<div class="hint">' + r.total + " 项，失败 " + r.failed + "</div>" +
    r.checks.map(c => '<div class="wf-row">' + (c.ok ? '<span class="ok">OK</span>' : '<span class="bad">FAIL</span>') +
      " " + esc(c.name) + ' <span class="hint">' + esc(c.detail || "") + "</span></div>").join(""));
});
$("#pill-overview") && ($("#pill-overview").onclick = () => openModal("功能总览",
  '<div class="hint" style="line-height:1.9">' +
  "<b>拼装</b>：积木库（分类/收藏/拖拽）、正负向画布、描述卡片、模板、展开预览、结构检查<br>" +
  "<b>出图</b>：文生图 / 图生图、LoRA 多行、批量多 seed<br>" +
  "<b>重绘</b>：画笔/橡皮/框选、羽化、蒙版库、图生图复现、手部精修<br>" +
  "<b>画廊</b>：筛选、多选导出 zip、大图操作<br>" +
  "<b>词库</b>：分类、A→Z、导入导出<br><b>服装</b>：默认/复制/材质型态/导入导出<br>" +
  "<b>配方</b>：回填、查看参数<br><b>打标/训练</b>：可选模块<br>" +
  "<b>引擎</b>：状态、工作流检查、模型绑定、释放显存<br><b>维护</b>：磁盘、回收站、文档</div>"));

/* init */
setTimeout(initLoras, 100);

boot();
