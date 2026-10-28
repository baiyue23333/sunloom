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
boot();
