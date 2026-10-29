
'use strict';
window.onerror = (m, s, l, c, e) => { document.title = 'ERR: ' + m + ' @' + l; };
window.addEventListener('unhandledrejection', e => { document.title = 'REJ: ' + (e.reason && e.reason.message || e.reason); });
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
const S = {
  tokens: {}, garments: {}, presets: [],
  pos: [], neg: [],
  loras: [], compfy: {}, datasets: [], loraFiles: [],
  jobTimer: null, last: null, gallery: [], sel: null,
  hist: [], hi: -1, fav: [], rel: {}, selChip: null, gallerySel: {}, compareSel: [],
  tokenFilter: '', paletteFilter: '', libraryFilter: '',
};
const CAT_LABEL = {
  id:'身份', body:'体型', pose:'姿势', face:'表情', mood:'情绪', gaze:'视线', hand:'手部',
  hold:'手持物', weapon:'武器', hair:'头发',
  cam:'机位', light:'打光', atmo:'氛围', time:'时间',
  outfit:'服装', fabric:'材质', drape:'型态',
  set:'场景', prop:'道具', comp:'构图', style:'风格',
  neg:'负向', custom:'自定义'
};

const api = async (url, opt) => {
  const r = await fetch(url, opt ? { headers:{'Content-Type':'application/json'}, ...opt } : undefined);
  if (!r.ok) throw new Error(url + ' → ' + r.status + ' ' + (await r.text()).slice(0,120));
  return r.json();
};

const uid = () => Math.random().toString(36).slice(2, 9);

/* ---------- 分类推断 ---------- */
function tokenCat(name) {
  const n = name.toUpperCase();
  const map = [
    ['@SUBJ', 'id'], ['@BODY', 'body'], ['@FACE', 'face'], ['@OUTFIT', 'outfit'],
    ['@NEG', 'neg'], ['@DRAPE', 'drape'], ['@OUT', 'outfit'], ['@MOOD', 'mood'], ['@POSE', 'pose'],
    ['@HOLD', 'hold'], ['@WEAPON', 'weapon'],
    ['@GAZE', 'gaze'], ['@HAND', 'hand'], ['@HAIR', 'hair'], ['@FAB', 'fabric'],
    ['@ATMO', 'atmo'], ['@TIME', 'time'], ['@SET', 'set'], ['@PROP', 'prop'],
    ['@COMP', 'comp'], ['@STYLE', 'style'], ['@CAM', 'cam'], ['@LIGHT', 'light'],
  ];
  for (const [pre, cat] of map) if (n.startsWith(pre)) return cat;
  if (n === '@ID') return 'id';
  if (n === '@BODY') return 'body';
  if (n === '@FACE') return 'face';
  if (n === '@SINGLE') return 'id';
  return 'custom';
}

/* ---------- 初始化 ---------- */
function persistParams() {
  try {
    localStorage.setItem('loom.params', JSON.stringify({
      size: ($('#p-size') || {}).value,
      steps: Number(($('#p-steps') || {}).value) || undefined,
      cfg: Number(($('#p-cfg') || {}).value) || undefined,
      seed: ($('#p-seed') || {}).value,
      prefix: ($('#p-prefix') || {}).value,
      mode: ($('#p-mode') || {}).value,
      loras: S.loras || []
    }));
  } catch (e) {}
}

function persistLanes() {
  try { localStorage.setItem('loom.lanes', JSON.stringify({ p: S.pos || [], n: S.neg || [] })); } catch (e) {}
}

async function boot() {
  const b = await api('/api/bootstrap');
  S.tokens = b.tokens; S.notes = b.notes || {}; S.garments = b.garments; S.comfy = b.comfy;
  S.datasets = b.datasets; S.loraFiles = b.loras;
  S.defaults = b.defaults; S.paths = b.paths;
  $('#pill-comfy').textContent = b.comfy.up ? ('ComfyUI ' + b.comfy.version) : 'ComfyUI 未启动';
  $('#pill-comfy').className = 'pill ' + (b.comfy.up ? 'ok' : 'bad');
  $('#pill-queue').textContent = '队列 ' + (b.queue.running + b.queue.pending);
  const reg = await api('/api/registry?limit=1');
  $('#pill-reg').textContent = '登记 ' + reg.total;

  S.loras = (b.defaults.loras || []).map(x => ({...x}));
  try {
    const saved = JSON.parse(localStorage.getItem('loom.lanes') || 'null');
    if (saved && ((saved.p && saved.p.length) || (saved.n && saved.n.length))) {
      S.pos = saved.p || []; S.neg = saved.n || [];
    }
  } catch (e) {}
  try {
    const sp = JSON.parse(localStorage.getItem('loom.params') || 'null');
    if (sp) {
      if (sp.size && $('#p-size')) $('#p-size').value = sp.size;
      if (sp.steps) $('#p-steps').value = sp.steps;
      if (sp.cfg) $('#p-cfg').value = sp.cfg;
      if (sp.seed !== undefined && $('#p-seed')) $('#p-seed').value = sp.seed;
      if (sp.prefix && $('#p-prefix')) $('#p-prefix').value = sp.prefix;
      if (sp.mode && $('#p-mode')) $('#p-mode').value = sp.mode;
      if (Array.isArray(sp.loras) && sp.loras.length) S.loras = sp.loras;
    }
  } catch (e) {}
  renderPalette(); renderLanes(); renderLoras(); renderParams();
  await loadPresets();
  await loadTemplates();
  renderGallery();
  fillSelects();
  await loadLibrary();
  refreshMaint();
  const eta = estimate();
  $('#eta').textContent = eta + ' 秒/张';
}

function fillSelects() {
  const ds = $('#tr-dataset'), tg = $('#tg-dataset');
  ds.innerHTML = S.datasets.map(d => '<option>' + d + '</option>').join('');
  tg.innerHTML = ds.innerHTML;
  $('#tr-existing').innerHTML = '<option value="">不续训</option>' +
    S.loraFiles.map(l => '<option>' + l + '</option>').join('');
}


/* ---------- 撤销 / 重做 ---------- */
function snapState() { return JSON.stringify({ pos: S.pos, neg: S.neg }); }
function pushHistory() {
  const s = snapState();
  if (S.hist[S.hi] === s) return;
  S.hist = S.hist.slice(0, S.hi + 1);
  S.hist.push(s);
  if (S.hist.length > 60) S.hist.shift();
  S.hi = S.hist.length - 1;
}
function applyHistory() {
  const d = JSON.parse(S.hist[S.hi]);
  S.pos = d.pos; S.neg = d.neg;
  renderLanes(); expandPreview();
}
function undo() {
  if (S.hi <= 0) { toast('没有可撤销的操作'); return; }
  S.hi--; applyHistory(); toast('已撤销');
}
function redo() {
  if (S.hi >= S.hist.length - 1) { toast('没有可重做的操作'); return; }
  S.hi++; applyHistory(); toast('已重做');
}

/* ---------- 收藏 ---------- */
function toggleFav(token) {
  const i = S.fav.indexOf(token);
  if (i >= 0) S.fav.splice(i, 1); else S.fav.push(token);
  saveJSON('loom.fav', S.fav);
  renderPalette();
  toast(i >= 0 ? ('已取消收藏 ' + token) : ('已收藏 ' + token));
}

/* ---------- 积木库 ---------- */
function paletteGroups() {
  const groups = {};
  for (const [name, text] of Object.entries(S.tokens)) {
    const c = tokenCat(name);
    (groups[c] = groups[c] || []).push([name, text]);
  }
  return groups;
}

function renderPalette() {
  const box = $('#palette'), rail = $('#pal-rail');
  if (!box || !rail) return;
  const groups = paletteGroups();
  const order = ['id','body','pose','face','mood','gaze','hand','hold','weapon','hair','cam','light','atmo','time',
                 'outfit','fabric','drape','set','prop','comp','style','neg','custom'];
  const collapsed = S.collapsedCats || (S.collapsedCats = loadJSON('loom.collapsedCats', {}));
  let html = '', railHtml = '';
  // 收藏组（置顶）
  const favs = (S.fav || []).filter(k => S.tokens[k]);
  if (favs.length) {
    html += '<div class="pal-group fav-group" data-cat="custom"><span class="caret">▾</span>收藏' +
      '<span class="num">' + favs.length + '</span></div><div class="pal-items" data-items="fav">';
    for (const name of favs) {
      html += '<div class="pal-item" draggable="true" data-token="' + name + '" data-cat="custom">' +
        '<span class="tk">' + name + '</span>' +
        '<span class="fav on" data-fav="' + name + '" title="取消收藏">★</span>' +
        '<span class="add">＋</span></div>';
    }
    html += '</div>';
  }
  for (const key of order) {
    let items = (groups[key] || []).slice();
    if (S.paletteFilter) {
      const f = S.paletteFilter.toLowerCase();
      items = items.filter(([n, tx]) => n.toLowerCase().includes(f) || (tx || '').toLowerCase().includes(f));
    }
    if (!items.length) continue;
    const label = CAT_LABEL[key] || key;
    const closed = !!collapsed[key];
    html += '<div class="pal-group' + (closed ? ' closed' : '') + '" id="cat-' + key + '" data-cat="' + key + '">' +
      '<span class="caret">▾</span>' + label +
      '<span class="num">' + items.length + '</span></div>' +
      '<div class="pal-items' + (closed ? ' hidden' : '') + '" data-items="' + key + '">';
    for (const [name] of items) {
      const isFav = (S.fav || []).indexOf(name) >= 0;
      html += '<div class="pal-item" draggable="true" data-token="' + name + '" data-cat="' + key + '">'
        + '<span class="tk">' + name + '</span>'
        + '<span class="fav' + (isFav ? ' on' : '') + '" data-fav="' + name + '" title="收藏">' + (isFav ? '★' : '☆') + '</span>'
        + '<span class="add">＋</span></div>';
    }
    html += '</div>';
    railHtml += '<button class="rail-item" data-jump="' + key + '" data-cat="' + key +
      '" title="' + label + '"><i></i>' + label.slice(0, 2) + '</button>';
  }
  box.innerHTML = html || '<div class="hint">没有匹配的积木</div>';
  rail.innerHTML = railHtml;
  bindTips(box);

  $$('.pal-group', box).forEach(g => g.onclick = () => {
    const key = g.dataset.cat;
    const closed = !(collapsed[key]);
    collapsed[key] = closed;
    saveJSON('loom.collapsedCats', collapsed);
    const body = box.querySelector('.pal-items[data-items="' + key + '"]');
    if (body) body.classList.toggle('hidden', closed);
    g.classList.toggle('closed', closed);
  });

  $$('.pal-item .fav', box).forEach(st => st.onclick = e => {
    e.stopPropagation();
    toggleFav(st.dataset.fav);
  });
  $$('.pal-item', box).forEach(el => {
    el.addEventListener('click', () => addBlock('positive', el.dataset.token));
    el.addEventListener('dragstart', e => {
      e.dataTransfer.setData('text/plain', JSON.stringify({ token: el.dataset.token }));
      e.dataTransfer.effectAllowed = 'copy';
    });
  });

  $$('.rail-item', rail).forEach(btn => btn.onclick = () => {
    const key = btn.dataset.jump;
    if (collapsed[key]) {
      collapsed[key] = false;
      saveJSON('loom.collapsedCats', collapsed);
      const body = box.querySelector('.pal-items[data-items="' + key + '"]');
      const head = box.querySelector('#cat-' + key);
      if (body) body.classList.remove('hidden');
      if (head) head.classList.remove('closed');
    }
    scrollPalTo(key);
    $$('.rail-item', rail).forEach(b => b.classList.toggle('active', b === btn));
  });

  const spy = () => {
    let active = null;
    for (const g of $$('.pal-group', box)) {
      if (g.getBoundingClientRect().top - box.getBoundingClientRect().top <= 10) active = g.dataset.cat;
    }
    $$('.rail-item', rail).forEach(b => b.classList.toggle('active', b.dataset.jump === active));
  };
  box.onscroll = spy;
  spy();
}

function scrollPalTo(key) {
  const box = $('#palette'), target = document.getElementById('cat-' + key);
  if (!box || !target) return;
  const jump = () => {
    const delta = target.getBoundingClientRect().top - box.getBoundingClientRect().top;
    const top = box.scrollTop + delta - 8;
    box.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
  };
  jump();
  requestAnimationFrame(() => requestAnimationFrame(jump));
}

function loadJSON(k, dflt) {
  try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : dflt; } catch (e) { return dflt; }
}
function saveJSON(k, v) {
  try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {}
}

/* ---------- 抽屉 ---------- */
function setLibCollapsed(v) {
  document.body.classList.toggle('lib-collapsed', !!v);
  try { localStorage.setItem('loom.libCollapsed', v ? '1' : '0'); } catch (e) {}
}

/* ---------- 命令面板 ---------- */
function cmdIndex() {
  return Object.keys(S.tokens).map(name => ({ name, text: S.tokens[name], cat: tokenCat(name) }));
}
function openCmd(prefill) {
  const bar = $('#cmdbar');
  if (!bar) return;
  bar.classList.add('open');
  const inp = $('#cmd-input');
  inp.value = prefill || '';
  renderCmd(inp.value);
  setTimeout(() => inp.focus(), 30);
}
function closeCmd() {
  const bar = $('#cmdbar');
  if (bar) bar.classList.remove('open');
}
function renderCmd(q) {
  const list = $('#cmd-list');
  if (!list) return;
  const f = (q || '').toLowerCase().trim();
  const all = cmdIndex().filter(x => !f || x.name.toLowerCase().includes(f) || (x.text || '').toLowerCase().includes(f));
  S.cmdItems = all.slice(0, 80);
  S.cmdSel = 0;
  list.innerHTML = S.cmdItems.length
    ? S.cmdItems.map((x, i) => '<div class="cmd-item' + (i === 0 ? ' sel' : '') + '" data-i="' + i + '" data-cat="' + x.cat + '">' +
        '<i></i><b>' + x.name + '</b><span>' + esc((x.text || '').slice(0, 110)) + '</span></div>').join('')
    : '<div class="cmd-empty">没有匹配的积木；回车会把输入变成自由文本块</div>';
  $$('#cmd-list .cmd-item').forEach(el => el.onclick = () => cmdAdd(Number(el.dataset.i)));
}
function cmdMove(d) {
  const items = S.cmdItems || [];
  if (!items.length) return;
  S.cmdSel = Math.max(0, Math.min(items.length - 1, (S.cmdSel || 0) + d));
  $$('#cmd-list .cmd-item').forEach((el, i) => el.classList.toggle('sel', i === S.cmdSel));
  const cur = $('#cmd-list .cmd-item.sel');
  if (cur) cur.scrollIntoView({ block: 'nearest' });
}
function cmdAdd(i) {
  const it = (S.cmdItems || [])[i];
  if (!it) return;
  addBlock('positive', it.name);
  toast('已加入 ' + it.name);
  closeCmd();
}

/* ---------- 画布 ---------- */
function addBlock(lane, tokenOrObj) {
  // 负向积木永远进负向，避免 @NEG_* 跑到正向
  if (lane === 'positive') {
    const nm = typeof tokenOrObj === 'string' ? tokenOrObj : (tokenOrObj && tokenOrObj.token) || '';
    if (nm && tokenCat(nm) === 'neg') lane = 'negative';
  }
  pushHistory();
  const arr = lane === 'positive' ? S.pos : S.neg;
  if (typeof tokenOrObj === 'string') {
    arr.push({ id: uid(), token: tokenOrObj, text: '', weight: 1, enabled: true });
  } else {
    arr.push(Object.assign({ id: uid(), token:'', text:'', weight:1, enabled:true }, tokenOrObj));
  }
  renderLanes(); expandPreview();
}

function renderLanes() {
  for (const lane of ['positive', 'negative']) {
    const arr = lane === 'positive' ? S.pos : S.neg;
    const box = $('#lane-' + lane);
    box.innerHTML = arr.map((b, i) => {
      const label = b.token || '文本';
      const body = b.token ? '<span class="tk">' + b.token + '</span>'
        : '<span class="txt">' + esc(b.text || '（空）') + '</span>';
      const cat = b.token ? tokenCat(b.token) : 'custom';
      const relX = b.token && (S.rel || {})[b.token] === 'X';
      return '<div class="chip ' + (lane === 'positive' ? 'pos' : 'neg') + (b.enabled ? '' : ' off') +
        (relX ? ' rel-x' : '') +
        '" draggable="true" data-id="' + b.id + '" data-lane="' + lane + '" data-cat="' + cat + '"' +
        (b.token ? ' data-token="' + b.token + '"' : '') + '>' +
        '<span class="grab">⠿</span>' +
        '<button class="on" data-toggle="' + b.id + '" data-lane="' + lane + '">' + (b.enabled ? '●' : '○') + '</button>' +
        body +
        '<input type="number" step="0.05" min="0" max="3" value="' + b.weight + '" data-weight="' + b.id + '" data-lane="' + lane + '" title="权重">' +
        '<button class="x" data-del="' + b.id + '" data-lane="' + lane + '">×</button>' +
        '</div>';
    }).join('') || '<span class="hint">把左边积木拖到这里，或点击添加</span>';
    box.addEventListener('dragover', e => { e.preventDefault(); });
    box.addEventListener('drop', e => {
      e.preventDefault();
      const raw = e.dataTransfer.getData('text/plain');
      if (!raw) return;
      try {
        const d = JSON.parse(raw);
        addBlock(lane, d);
      } catch (err) {
        addBlock(lane, { text: raw });
      }
    });
  }
  bindTips($('#lane-positive'));
  bindTips($('#lane-negative'));
  $('#pos-count').textContent = S.pos.length + ' 块';
  $('#neg-count').textContent = S.neg.length + ' 块';
  bindLaneEvents();
}

function bindLaneEvents() {
  $$('[data-del]').forEach(el => el.onclick = () => {
    const arr = el.dataset.lane === 'positive' ? S.pos : S.neg;
    pushHistory();
    const i = arr.findIndex(b => b.id === el.dataset.del);
    if (i >= 0) arr.splice(i, 1);
    renderLanes(); expandPreview();
  });
  $$('[data-toggle]').forEach(el => el.onclick = () => {
    const arr = el.dataset.lane === 'positive' ? S.pos : S.neg;
    pushHistory();
    const b = arr.find(x => x.id === el.dataset.toggle);
    if (b) b.enabled = !b.enabled;
    renderLanes(); expandPreview();
  });
  $$('[data-weight]').forEach(el => el.onchange = () => {
    const arr = el.dataset.lane === 'positive' ? S.pos : S.neg;
    pushHistory();
    const b = arr.find(x => x.id === el.dataset.weight);
    if (b) b.weight = parseFloat(el.value) || 1;
    expandPreview();
  });
  $$('.chip').forEach(el => {
    el.addEventListener('mousedown', e => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON') return;
      $$('.chip').forEach(c => c.classList.remove('sel'));
      el.classList.add('sel');
      S.selChip = { id: el.dataset.id, lane: el.dataset.lane };
    });
    el.addEventListener('dragstart', e => {
      e.dataTransfer.setData('text/plain', JSON.stringify({ move: el.dataset.id, lane: el.dataset.lane }));
      el.classList.add('dragging');
    });
    el.addEventListener('dragend', () => el.classList.remove('dragging'));
    el.addEventListener('dblclick', () => editFreeText(el));
  });
  $$('.lane-body').forEach(box => {
    const lane = box.closest('.lane').dataset.lane;
    box.addEventListener('dragover', e => { e.preventDefault(); });
    box.addEventListener('drop', e => {
      e.preventDefault();
      const raw = e.dataTransfer.getData('text/plain');
      if (!raw) return;
      let d = null;
      try { d = JSON.parse(raw); } catch (err) { d = { text: raw }; }
      if (d.move) {
        const from = d.lane === 'positive' ? S.pos : S.neg;
        const i = from.findIndex(x => x.id === d.move);
        if (i >= 0) {
          const [blk] = from.splice(i, 1);
          (lane === 'positive' ? S.pos : S.neg).push(blk);
          renderLanes(); expandPreview();
        }
      } else {
        addBlock(lane, d);
      }
    });
  });
}

function editFreeText(chipEl) {
  const id = chipEl.dataset.id, lane = chipEl.dataset.lane;
  const arr = lane === 'positive' ? S.pos : S.neg;
  const b = arr.find(x => x.id === id);
  if (!b || b.token) return;
  const v = prompt('文本块内容', b.text || '');
  if (v !== null) { b.text = v; renderLanes(); expandPreview(); }
}

function esc(s) { return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

async function expandPreview() {
  persistLanes();
  persistParams();
  try {
    const r = await api('/api/expand', { method:'POST', body: JSON.stringify({ positive: S.pos, negative: S.neg }) });
    $('#preview-pos').textContent = r.positive || '（空）';
    $('#preview-neg').textContent = r.negative || '（空）';
    $('#expand-used').textContent = '正向 ' + r.pos_len + ' 字符 / 负向 ' + r.neg_len + ' 字符 · 用了 ' + r.used.length + ' 个宏';
    S.lastExpanded = r;
  if (r.notes && r.notes.length) {
    const used = $('#expand-used');
    if (used) used.textContent = '· ' + r.notes.join(' · ');
  }
    updateEta();
    validateBlocks();
  } catch (e) { console.error(e); }
}

/* ---------- 参数 ---------- */
function renderParams() {
  if (!$('#p-size')) return;
}
function size() {
  const [w, h] = ($('#p-size').value || '1024x1536').split('x').map(Number);
  return { w, h };
}
function estimate() {
  const { w, h } = size();
  const steps = Number($('#p-steps').value) || 30;
  return Math.round(w * h * steps * 1.6e-6 + 1.5);
}
function updateEta() {
  const { w, h } = size();
  const steps = Number($('#p-steps').value) || 30;
  const sec = Math.round(w * h * steps * 1.6e-6 + 1.5);
  S.eta = sec;
  $('#eta').textContent = '预计 ' + sec + ' 秒/张';
}

function renderLoras() {
  const box = $('#lora-list');
  box.innerHTML = S.loras.map((l, i) =>
    '<div class="lora-row">' +
    '<select data-lora-name="' + i + '">' + S.loraFiles.map(f =>
      '<option' + (f === l.name ? ' selected' : '') + '>' + f + '</option>').join('') + '</select>' +
    '<input type="number" step="0.01" value="' + l.weight + '" data-lora-w="' + i + '">' +
    '<button class="x" data-lora-del="' + i + '">×</button></div>').join('');
  $$('[data-lora-name]').forEach(el => el.onchange = () => { S.loras[el.dataset.loraName].name = el.value; });
  $$('[data-lora-w]').forEach(el => el.onchange = () => { S.loras[el.dataset.loraW].weight = parseFloat(el.value) || 0; });
  $$('[data-lora-del]').forEach(el => el.onclick = () => { S.loras.splice(Number(el.dataset.loraDel), 1); renderLoras(); });
  $('#lora-add').onclick = () => { S.loras.push({ name: S.loraFiles[0] || '', weight: 0.5 }); renderLoras(); };
}

/* ---------- 出图 ---------- */
async function run() {
  if (!S.lastExpanded || !S.lastExpanded.positive.trim()) { alert('正向提示词为空'); return; }
  const { w, h } = size();
  $('#run-btn').disabled = true;
  $('#run-status').textContent = '提交中…';
  $('#run-bar').style.width = '2%';
  try {
    const r = await api('/api/run', { method:'POST', body: JSON.stringify({
      prompt: S.lastExpanded.positive,
      negative: S.lastExpanded.negative,
      width: w, height: h,
      steps: Number($('#p-steps').value) || 30,
      cfg: Number($('#p-cfg').value) || 5.5,
      seed: Number($('#p-seed').value) || 0,
      prefix: $('#p-prefix').value || 'st',
      loras: S.loras.map(l => ({ name: l.name, weight: Number(l.weight) })),
      blocks_pos: S.pos.map(b => ({ token: b.token || '', text: b.text || '', weight: Number(b.weight) || 1, enabled: b.enabled !== false })),
      blocks_neg: S.neg.map(b => ({ token: b.token || '', text: b.text || '', weight: Number(b.weight) || 1, enabled: b.enabled !== false })),
    })});
    S.last = { job: r.job_id, seed: r.seed };
    $('#run-status').textContent = '排队中 · seed ' + r.seed + ' · 预计 ' + r.estimate + ' 秒';
    pollJob(r.job_id, 'run');
  } catch (e) {
    $('#run-btn').disabled = false;
    $('#run-status').textContent = '失败：' + e.message;
  }
}

async function pollJob(jid, kind) {
  clearInterval(S.jobTimer);
  S.jobTimer = setInterval(async () => {
    let j;
    try { j = await api('/api/job/' + jid); } catch (e) { return; }
    if (kind === 'run') {
      $('#run-bar').style.width = Math.round((j.progress || 0) * 100) + '%';
      const left = Math.max(0, Math.round((S.eta || 60) - (j.elapsed || 0)));
      $('#run-status').textContent = (j.status === 'running' ? '生成中 ' + (j.elapsed||0) + 's · 约剩 ' + left + 's' : j.status) +
        ' · ' + Math.round((j.progress||0) * 100) + '%';
    }
    if (j.logs && j.logs.length) {
      if (kind === 'train') $('#tr-log').textContent = j.logs.join('\n');
      if (kind === 'tag') $('#tg-log').textContent = j.logs.join('\n');
    }
    if (j.status === 'done' || j.status === 'error' || j.status === 'cancelled') {
      clearInterval(S.jobTimer);
      if (kind === 'run') {
        $('#run-btn').disabled = false;
        if (j.status === 'done' && j.result && j.result.images && j.result.images.length) {
          showResult(j.result.images[0], j.result.seed, j.result.elapsed);
          $('#run-bar').style.width = '100%';
          $('#run-status').textContent = '完成 · ' + j.result.elapsed + 's';
        } else {
          $('#run-status').textContent = '失败：' + ((j.result && j.result.error) || j.status);
        }
      }
      if (kind === 'train') { $('#tr-run').disabled = false; $('#tr-dry').disabled = false; }
      if (kind === 'tag') { $('#tg-run').disabled = false; }
    }
  }, 1200);
}

function showResult(path, seed, elapsed) {
  const { w, h } = size();
  const square = Math.abs(w - h) < 4;
  $('#result').innerHTML =
    '<img class="clickable" id="result-img" src="/api/img?path=' + encodeURIComponent(path) + '">' +
    (square ? '<div class="warn">方图更容易出双人分屏；若出现两个人物，建议换 1024×1536 或点「重抽」。</div>' : '') +
    '<div class="logbar">' +
    '<input id="log-note" placeholder="备注（可空，例如：外套长度对）">' +
    '<div class="verdicts">' +
    '<button data-v="A">A</button><button data-v="B">B</button><button data-v="C">C</button>' +
    '</div></div>' +
    '<div class="row2" style="margin-top:6px">' +
    '<button class="ghost" id="rerun">重抽</button>' +
    '<button class="ghost" id="open-file">画廊</button>' +
    '</div>' +
    '<div class="row2" style="margin-top:6px">' +
    '<button class="ghost" id="handfix-btn">手部精修</button>' +
    '<button class="ghost" id="repro-btn">复现</button>' +
    '</div>' +
    '<div class="row2" style="margin-top:6px">' +
    '<button class="ghost" id="batch-btn">批量</button>' +
    '<button class="ghost" id="params-btn">参数</button>' +
    '</div>' +
    '<div class="hint">seed ' + seed + ' · ' + elapsed + 's · ' + path.split('\\').pop() + '</div>';
  const ri = $('#result-img');
  if (ri) ri.onclick = () => openImage(path);
  $$('#result .verdicts button').forEach(b => b.onclick = () => {
    logPick(path, b.dataset.v, ($('#log-note') || {}).value || '');
  });
  $('#rerun').onclick = () => { $('#p-seed').value = ''; run(); };
  const hb = $('#handfix-btn');
  if (hb) hb.onclick = () => openHandfix(path);
  const rb = $('#repro-btn');
  if (rb) rb.onclick = () => openReproPage(path);
  const bb = $('#batch-btn');
  if (bb) bb.onclick = () => openBatch();
  const pb = $('#params-btn');
  if (pb) pb.onclick = () => openRecipe(path);
  $('#open-file').onclick = () => { const a = document.querySelector('#tabs button[data-tab="gallery"]'); if (a) a.click(); };
}

async function logPick(path, verdict, note) {
  const body = { path, verdict, note: note === undefined ? '' : note,
    seed: S.last ? S.last.seed : null, params: 'station ' + ($('#p-size').value || '') };
  try {
    await api('/api/log', { method: 'POST', body: JSON.stringify(body) });
    const reg = await api('/api/registry?limit=1');
    $('#pill-reg').textContent = '登记 ' + reg.total;
    toast('已登记 ' + verdict + (note ? ' · ' + note : ''));
  } catch (e) {
    toast('登记失败：' + e.message, true);
  }
}

/* ---------- 画廊 ---------- */
async function renderGallery() {
  const dir = $('#g-dir').value;
  const r = await api('/api/gallery?dir=' + encodeURIComponent(dir) + '&limit=400');
  S.gallery = r.items;
  let rec = { items: [] };
  try { rec = await api('/api/recipes?limit=500'); } catch (e) {}
  const withRecipe = new Set((rec.items || []).map(x => x.path));

  const rating = ($('#g-rating') || {}).value || '';
  const recipe = ($('#g-recipe') || {}).value || '';
  const days = Number(($('#g-date') || {}).value) || 0;
  const q = (($('#g-q') || {}).value || '').toLowerCase().trim();
  const now = Date.now() / 1000;

  const items = r.items.filter(it => {
    if (rating === 'none' && it.verdict) return false;
    if (rating && rating !== 'none' && it.verdict !== rating) return false;
    if (recipe === '1' && !withRecipe.has(it.path)) return false;
    if (recipe === '0' && withRecipe.has(it.path)) return false;
    if (days && (now - (it.mtime || 0)) > days * 86400) return false;
    if (q && !(it.name.toLowerCase().includes(q) || (it.note || '').toLowerCase().includes(q))) return false;
    return true;
  });

  const selMode = !!S.gallerySelect;
  const total = $('#g-total');
  if (total) total.textContent = items.length + ' / ' + r.total + ' 张';

  $('#gallery').innerHTML = items.map(it => {
    const on = S.gallerySel[it.path] ? ' on' : '';
    return '<div class="g-item' + on + '" data-path="' + it.path + '">'
      + '<img loading="lazy" src="/api/img?path=' + encodeURIComponent(it.path) + '">'
      + (it.verdict ? '<span class="v ' + it.verdict + '">' + it.verdict + '</span>' : '')
      + (selMode ? '<span class="g-check">' + (S.gallerySel[it.path] ? '✓' : '') + '</span>' : '')
      + '<button class="g-params" data-params="' + it.path + '" title="查看这张图的积木与参数">参数</button>'
      + '<button class="g-del" data-del="' + it.path + '" title="移入回收站">×</button>'
      + '<div class="meta"><span>' + it.name.slice(0, 16) + '</span><span>' + (it.note || '') + '</span></div>'
      + '</div>';
  }).join('') || '<div class="hint">没有符合条件的图</div>';

  $$('-g-item').forEach(() => {});
  $$('.g-item').forEach(el => el.onclick = () => {
    if (S.gallerySelect) {
      const p = el.dataset.path;
      if (S.gallerySel[p]) delete S.gallerySel[p]; else S.gallerySel[p] = 1;
      renderGallery();
      return;
    }
    openImage(el.dataset.path);
  });
  $$('.g-item .g-params').forEach(btn => btn.onclick = e => {
    e.stopPropagation();
    openRecipe(btn.dataset.params);
  });
  $$('.g-item .g-del').forEach(btn => btn.onclick = async e => {
    e.stopPropagation();
    await deleteImage(btn.dataset.del);
    renderGallery();
  });
  const ex = $('#g-export');
  if (ex) {
    ex.style.display = selMode ? '' : 'none';
    ex.textContent = '导出选中（' + Object.keys(S.gallerySel).length + '）';
  }
}

async function exportSelected() {
  const paths = Object.keys(S.gallerySel);
  if (!paths.length) { toast('先点几张图选中', true); return; }
  try {
    const r = await api('/api/export', { method: 'POST', body: JSON.stringify({ paths }) });
    toast('已导出 ' + r.count + ' 张 → ' + r.zip.split('\\').pop());
    const box = $('#g-total');
    if (box) {
      box.innerHTML = '<a href="' + r.url + '" style="color:#ffe6b3">下载 ' + r.zip.split('\\').pop() + '</a>';
    }
  } catch (e) { toast('导出失败：' + e.message, true); }
}

let ZV = { scale: 1, tx: 0, ty: 0, fitted: false };

async function openImage(path) {
  const qc = await api('/api/qc?path=' + encodeURIComponent(path));
  openModal('预览 · 滚轮缩放 / 拖动平移 / Shift+拖框放大 / 双击 1:1',
    '<div class="zoom-wrap" id="zoom-wrap">' +
    '<img id="zoom-img" src="/api/img?path=' + encodeURIComponent(path) + '">' +
    '<div class="zoom-marquee" id="zoom-marquee"></div></div>' +
    '<div class="zoom-bar">' +
    '<button class="ghost" id="z-out">−</button>' +
    '<span id="zoom-pct" class="zoom-pct">100%</span>' +
    '<button class="ghost" id="z-in">+</button>' +
    '<button class="ghost" id="z-one">1:1</button>' +
    '<button class="ghost" id="z-fit">适应</button>' +
    '<button class="ghost" id="z-marquee">框选放大</button>' +
    '<button class="ghost" id="z-del" style="color:#ffb3a6">删除</button>' +
    '<span class="hint" style="margin-left:auto">' + esc(path.split('\\').pop()) + '</span>' +
    '</div>' +
    '<div class="logbar" style="margin-top:10px"><input id="m-note" placeholder="备注（可空）">' +
    '<div class="verdicts">' + ['A','B','C'].map(v => '<button data-v="' + v + '">' + v + '</button>').join('') +
    '</div></div>' +
    '<pre>' + esc(JSON.stringify(qc, null, 2)) + '</pre>');
  bindZoom();
  $$('#modal-content button[data-v]').forEach(b => b.onclick = async () => {
    await logPick(path, b.dataset.v, ($('#m-note') || {}).value || '');
    closeModal(); renderGallery();
  });
}

async function deleteImage(path) {
  const ok = confirm('把这张图移入回收站？\n' + path.split('\\').pop() + '\n（可在「维护」里彻底删或恢复）');
  if (!ok) return false;
  try {
    const r = await api('/api/delete-image', { method: 'POST', body: JSON.stringify({ path, permanent: false }) });
    toast('已移入回收站：' + (r.trash || '').split('\\').pop());
    return true;
  } catch (e) {
    toast('删除失败：' + e.message, true);
    return false;
  }
}

function bindZoom() {
  const wrap = $('#zoom-wrap'), img = $('#zoom-img'), mar = $('#zoom-marquee');
  if (!wrap || !img) return;
  ZV = { scale: 1, tx: 0, ty: 0, fitted: false };
  let marqueeMode = false;

  const apply = () => {
    img.style.transform = 'translate(' + ZV.tx + 'px,' + ZV.ty + 'px) scale(' + ZV.scale + ')';
    const pct = $('#zoom-pct');
    if (pct) pct.textContent = Math.round(ZV.scale * 100) + '%';
  };
  const fit = () => {
    const nw = img.naturalWidth || 1, nh = img.naturalHeight || 1;
    const w = wrap.clientWidth, h = wrap.clientHeight;
    ZV.scale = Math.min(w / nw, h / nh, 1);
    ZV.tx = (w - nw * ZV.scale) / 2;
    ZV.ty = (h - nh * ZV.scale) / 2;
    ZV.fitted = true;
    apply();
  };
  const zoomAt = (mx, my, factor) => {
    const next = Math.max(0.1, Math.min(8, ZV.scale * factor));
    const k = next / ZV.scale;
    ZV.tx = mx - (mx - ZV.tx) * k;
    ZV.ty = my - (my - ZV.ty) * k;
    ZV.scale = next;
    ZV.fitted = false;
    apply();
  };

  // 框选区域 -> 填满视口
  const zoomToRect = (bx, by, bw, bh) => {
    const w = wrap.clientWidth, h = wrap.clientHeight;
    const ix = (bx - ZV.tx) / ZV.scale;
    const iy = (by - ZV.ty) / ZV.scale;
    const iw = bw / ZV.scale;
    const ih = bh / ZV.scale;
    if (iw < 4 || ih < 4) return;
    const next = Math.max(0.1, Math.min(8, Math.min(w / iw, h / ih) * 0.96));
    ZV.scale = next;
    ZV.tx = w / 2 - (ix + iw / 2) * next;
    ZV.ty = h / 2 - (iy + ih / 2) * next;
    ZV.fitted = false;
    apply();
    toast('已放大到选区 ' + Math.round(iw) + ' × ' + Math.round(ih) + ' px');
  };

  img.onload = fit;
  if (img.complete) fit();

  wrap.addEventListener('wheel', e => {
    e.preventDefault();
    const r = wrap.getBoundingClientRect();
    zoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.18 : 1 / 1.18);
  }, { passive: false });

  let drag = null, sel = null;

  wrap.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    const r = wrap.getBoundingClientRect();
    if (marqueeMode || e.shiftKey) {
      e.preventDefault();
      sel = { x0: e.clientX - r.left, y0: e.clientY - r.top, x1: e.clientX - r.left, y1: e.clientY - r.top };
      if (mar) { mar.style.display = 'block'; drawSel(); }
    } else {
      drag = { x: e.clientX, y: e.clientY, tx: ZV.tx, ty: ZV.ty };
      wrap.classList.add('grabbing');
    }
  });

  const drawSel = () => {
    if (!sel || !mar) return;
    const x = Math.min(sel.x0, sel.x1), y = Math.min(sel.y0, sel.y1);
    const w = Math.abs(sel.x1 - sel.x0), h = Math.abs(sel.y1 - sel.y0);
    mar.style.left = x + 'px'; mar.style.top = y + 'px';
    mar.style.width = w + 'px'; mar.style.height = h + 'px';
  };

  window.addEventListener('mousemove', e => {
    if (sel) {
      const r = wrap.getBoundingClientRect();
      sel.x1 = e.clientX - r.left; sel.y1 = e.clientY - r.top;
      drawSel();
      return;
    }
    if (!drag) return;
    ZV.tx = drag.tx + (e.clientX - drag.x);
    ZV.ty = drag.ty + (e.clientY - drag.y);
    apply();
  });

  window.addEventListener('mouseup', () => {
    if (sel) {
      const x = Math.min(sel.x0, sel.x1), y = Math.min(sel.y0, sel.y1);
      const w = Math.abs(sel.x1 - sel.x0), h = Math.abs(sel.y1 - sel.y0);
      if (mar) mar.style.display = 'none';
      if (w > 10 && h > 10) zoomToRect(x, y, w, h);
      sel = null;
      return;
    }
    drag = null;
    wrap.classList.remove('grabbing');
  });

  wrap.addEventListener('dblclick', e => {
    const r = wrap.getBoundingClientRect();
    if (ZV.scale > 1.05) fit();
    else zoomAt(e.clientX - r.left, e.clientY - r.top, 1 / ZV.scale);
  });

  $('#z-in').onclick = () => { const r = wrap.getBoundingClientRect(); zoomAt(r.width / 2, r.height / 2, 1.25); };
  $('#z-out').onclick = () => { const r = wrap.getBoundingClientRect(); zoomAt(r.width / 2, r.height / 2, 1 / 1.25); };
  $('#z-one').onclick = () => { const r = wrap.getBoundingClientRect(); zoomAt(r.width / 2, r.height / 2, 1 / ZV.scale); };
  $('#z-fit').onclick = fit;

  const db = $('#z-del');
  if (db) db.onclick = async () => {
    if (!(await deleteImage(path))) return;
    closeModal();
    renderGallery();
  };

  const mb = $('#z-marquee');
  if (mb) mb.onclick = () => {
    marqueeMode = !marqueeMode;
    mb.classList.toggle('active', marqueeMode);
    wrap.style.cursor = marqueeMode ? 'crosshair' : 'grab';
    toast(marqueeMode ? '框选模式：在图上拖一个框' : '已回到拖动平移');
  };

  // 演示/截图：?zoomrect=0.2,0.1,0.3,0.3 （相对原图的比例）
  const zr = location.search.match(/zoomrect=([0-9.,]+)/);
  if (zr) {
    const p = zr[1].split(',').map(Number);
    if (p.length === 4) setTimeout(() => {
      const w = wrap.clientWidth, h = wrap.clientHeight;
      const nw = img.naturalWidth || 1, nh = img.naturalHeight || 1;
      fit();
      const bx = ZV.tx + p[0] * nw * ZV.scale;
      const by = ZV.ty + p[1] * nh * ZV.scale;
      zoomToRect(bx, by, p[2] * nw * ZV.scale, p[3] * nh * ZV.scale);
    }, 300);
  }
}

/* ---------- 词库 ---------- */
async function loadLibrary(filter) {
  const q = (filter === undefined ? (S.libraryFilter || '') : filter).toLowerCase();
  S.libraryFilter = q;
  const letter = S.libLetter || '';
  const order = ['id','body','pose','face','mood','gaze','hand','hold','weapon','hair','cam','light','atmo','time',
                 'outfit','fabric','drape','set','prop','comp','style','neg','custom'];
  const all = Object.entries(S.tokens)
    .filter(([n, tx]) => !q || n.toLowerCase().includes(q) || (tx || '').toLowerCase().includes(q));
  const AZ = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');
  const letters = {};
  all.forEach(([n]) => {
    const ch = (n.replace(/^@/, '')[0] || '#').toUpperCase();
    letters[ch] = (letters[ch] || 0) + 1;
  });
  const azBar = $('#lib-az');
  if (azBar) {
    azBar.innerHTML = '<button class="az' + (letter ? '' : ' on') + '" data-l="">全部</button>' +
      AZ.map(ch => '<button class="az' + (letter === ch ? ' on' : '') + (letters[ch] ? '' : ' off') +
        '" data-l="' + ch + '">' + ch + '</button>').join('');
    $$('#lib-az .az').forEach(b => b.onclick = () => {
      S.libLetter = b.dataset.l || '';
      loadLibrary(S.libraryFilter);
    });
  }

  const groups = {};
  all.forEach(([n, tx]) => {
    const ch = (n.replace(/^@/, '')[0] || '#').toUpperCase();
    if (letter && ch !== letter) return;
    const c = tokenCat(n);
    (groups[c] = groups[c] || []).push([n, tx]);
  });

  let out = '';
  for (const key of order) {
    const items = (groups[key] || []).sort((a, b) => a[0].localeCompare(b[0]));
    if (!items.length) continue;
    out += '<div class="tgroup" data-cat="' + key + '">' + (CAT_LABEL[key] || key) +
      '<span class="n">' + items.length + '</span></div>';
    for (const [n, tx] of items) {
      out += '<div class="trow" data-token="' + n + '" data-cat="' + key + '">' +
        '<span class="k">' + n + '</span>' +
        '<span class="v">' + esc((tx || '').slice(0, 120)) + '</span></div>';
    }
  }
  $('#token-table').innerHTML = out || '<div class="hint" style="padding:12px">没有匹配的积木</div>';
  bindTips($('#token-table'));
  $$('#token-table .trow').forEach(el => el.onclick = () => {
    const n = el.dataset.token;
    $('#tk-name').value = n; $('#tk-text').value = S.tokens[n] || '';
    $('#tk-note').value = (S.notes || {})[n] || '';
    $('#tk-cat').value = tokenCat(n);
  });
}

async function saveNote() {
  const name = $('#tk-name').value.trim();
  if (!name) return alert('先选一个积木');
  const r = await api('/api/token/note', { method: 'POST', body: JSON.stringify({ name, text: $('#tk-note').value, category: 'note' }) });
  S.notes = r.notes;
  renderPalette();
  toast('备注已保存');
}

async function saveToken() {
  const name = $('#tk-name').value.trim();
  const text = $('#tk-text').value.trim();
  if (!name) return alert('需要名称');
  await api('/api/token/save', { method:'POST', body: JSON.stringify({ name, text, category:$('#tk-cat').value }) });
  S.tokens = (await api('/api/bootstrap')).tokens;
  renderPalette(); loadLibrary($('#lib-search').value);
}

async function delToken() {
  const name = $('#tk-name').value.trim();
  if (!name || !confirm('删除 ' + name + ' ?')) return;
  const r = await api('/api/token/delete', { method:'POST', body: JSON.stringify({ name, text:'', category:'custom' }) });
  S.tokens = r.tokens; renderPalette(); loadLibrary();
}

/* ---------- 服装 ---------- */
function renderGarmentList(activeKey) {
  const box = $('#gm-list');
  if (!box) return;
  const gs = S.garments || {};
  const keys = Object.keys(gs);
  box.innerHTML = keys.length ? keys.map(k => {
    const g = gs[k] || {};
    const on = k === activeKey ? ' on' : '';
    return '<div class="gm-item' + on + '" data-key="' + k + '">' +
      '<b>' + esc(g.label || k) + '</b><span class="key">' + k + '</span>' +
      '<span class="use">' + esc(g.use_for || '') + '</span>' +
      '<span class="len">' + ((g.prompt || '').length) + ' 字符</span></div>';
  }).join('') : '<div class="hint">还没有服装</div>';
  $$('#gm-list .gm-item').forEach(el => el.onclick = () => loadGarment(el.dataset.key));
}

function appendToGarmentPrompt(text) {
  appendToField('#gm-prompt2', text);
}

function appendToField(sel, text) {
  const ta = $(sel);
  if (!ta) return;
  const v = (ta.value || '').trim();
  ta.value = (v ? v.replace(/,\s*$/, '') + ', ' : '') + text;
}

function renderGarmentChips() {
  const drape = $('#gm-drapes'), pose = $('#gm-poses');
  if (drape) {
    const ds = Object.keys(S.tokens).filter(k => k.startsWith('@DRAPE_')).sort();
    drape.innerHTML = ds.map(k => '<button class="gchip" data-drape="' + k + '">' + k.replace('@DRAPE_', '') + '</button>').join('');
    $$('#gm-drapes .gchip').forEach(b => b.onclick = () => appendToGarmentPrompt(S.tokens[b.dataset.drape] || ''));
  }
  if (pose) {
    const ps = Object.keys(S.tokens).filter(k => k.startsWith('@POSE_')).sort();
    pose.innerHTML = ps.map(k => '<button class="gchip pose" data-pose="' + k + '">' + k.replace('@POSE_', '') + '</button>').join('');
    $$('#gm-poses .gchip').forEach(b => b.onclick = () => appendToGarmentPrompt(S.tokens[b.dataset.pose] || ''));
  }

  const mk = (el, list, cls, attr, target) => {
    if (!el) return;
    el.innerHTML = list.map(k => '<button class="gchip ' + cls + '" ' + attr + '="' + k + '">' +
      k.replace(/^@(HOLD_[RL]_|WEAPON_)/, '') + '</button>').join('');
    $$('#' + el.id + ' .gchip').forEach(b => b.onclick = () => appendToField(target, S.tokens[b.dataset.hold || b.dataset.weapon] || ''));
  };
  const holds = Object.keys(S.tokens).filter(k => k.startsWith('@HOLD_')).sort();
  mk($('#gm-hold-r'), holds.filter(k => k.startsWith('@HOLD_R_')), 'hold', 'data-hold', '#gm-hand-r');
  mk($('#gm-hold-l'), holds.filter(k => k.startsWith('@HOLD_L_')), 'hold', 'data-hold', '#gm-hand-l');
  mk($('#gm-weapons'), Object.keys(S.tokens).filter(k => k.startsWith('@WEAPON_')).sort(), 'weapon', 'data-weapon', '#gm-hand-r');
}

function loadGarment(key) {
  const g = (S.garments || {})[key];
  if (!g) return;
  S.garmentKey = key;
  if ($('#gm-key2')) $('#gm-key2').value = key;
  if ($('#gm-label')) $('#gm-label').value = g.label || '';
  if ($('#gm-use')) $('#gm-use').value = g.use_for || '';
  if ($('#gm-prompt2')) $('#gm-prompt2').value = g.prompt || '';
  if ($('#gm-neg2')) $('#gm-neg2').value = g.negative || '';
  if ($('#gm-hand-r')) $('#gm-hand-r').value = g.hands_right || '';
  if ($('#gm-hand-l')) $('#gm-hand-l').value = g.hands_left || '';
  renderGarmentList(key);
  renderGarmentChips();
  const st = $('#gm-status');
  if (st) st.textContent = '编辑中：' + key;
}

function newGarment() {
  S.garmentKey = '';
  if ($('#gm-key2')) $('#gm-key2').value = '';
  if ($('#gm-label')) $('#gm-label').value = '';
  if ($('#gm-use')) $('#gm-use').value = '';
  if ($('#gm-prompt2')) $('#gm-prompt2').value = '';
  if ($('#gm-neg2')) $('#gm-neg2').value = '';
  if ($('#gm-hand-r')) $('#gm-hand-r').value = '';
  if ($('#gm-hand-l')) $('#gm-hand-l').value = '';
  renderGarmentList('');
  renderGarmentChips();
  const st = $('#gm-status');
  if (st) st.textContent = '新建：填 key 与名称后保存';
}

async function saveGarment() {
  const key = ($('#gm-key2') ? $('#gm-key2').value : '').trim();
  if (!key) { alert('先填 key（英文，如 slip2）'); return; }
  if (!/^[a-z0-9_]+$/i.test(key)) { alert('key 只能包含字母、数字、下划线'); return; }
  const body = {
    key,
    label: ($('#gm-label') || {}).value || '',
    use_for: ($('#gm-use') || {}).value || '',
    prompt: ($('#gm-prompt2') || {}).value || '',
    negative: ($('#gm-neg2') || {}).value || '',
    hands_left: ($('#gm-hand-l') || {}).value || '',
    hands_right: ($('#gm-hand-r') || {}).value || '',
  };
  try {
    const r = await api('/api/garment/save', { method: 'POST', body: JSON.stringify(body) });
    S.garments = r.garments || S.garments;
    loadGarment(key);
    toast('已保存服装 ' + key);
  } catch (e) { toast('保存失败：' + e.message, true); }
}

async function deleteGarment() {
  const key = ($('#gm-key2') ? $('#gm-key2').value : '').trim();
  if (!key) return;
  if (!confirm('删除服装《' + key + '》？这会从 character.json 里移除。')) return;
  try {
    const r = await api('/api/garment/delete', { method: 'POST', body: JSON.stringify({ key }) });
    S.garments = r.garments || {};
    const first = Object.keys(S.garments)[0];
    if (first) loadGarment(first); else newGarment();
    toast('已删除 ' + key);
  } catch (e) { toast('删除失败：' + e.message, true); }
}

async function trainInfo() {
  const r = await api('/api/train/profiles');
  $('#tr-profiles').textContent = (r.text || '').split('\n')[0] || '';
  const caches = r.caches || [];
  $('#tr-cache').innerHTML = '<option value="">不用</option>' + caches.map(c => '<option>' + c + '</option>').join('');
}
async function startTrain(dry) {
  const body = {
    dataset: $('#tr-dataset').value,
    profile: $('#tr-profile').value,
    steps: Number($('#tr-steps').value) || 100,
    rank: Number($('#tr-rank').value) || 0,
    lr: Number($('#tr-lr').value) || 0,
    cache: $('#tr-cache').value,
    build_cache: $('#tr-buildcache').value.trim(),
    existing_lora: $('#tr-existing').value,
    keep: Number($('#tr-keep').value) || 3,
    dry_run: dry,
    prefix: 'station_lora',
  };
  $('#tr-run').disabled = true; $('#tr-dry').disabled = true;
  $('#tr-log').textContent = '提交中…';
  const r = await api('/api/train/start', { method:'POST', body: JSON.stringify(body) });
  $('#tr-log').textContent = '$ ' + r.cmd + '\n';
  pollJob(r.job_id, 'train');
}

/* ---------- 打标 ---------- */
async function startTag() {
  const body = {
    dataset: $('#tg-dataset').value,
    trigger: $('#tg-trigger').value.trim(),
    extra: $('#tg-extra').value.trim(),
    write: $('#tg-write').value === '1',
    drop_appearance: $('#tg-drop').checked,
    threshold: Number($('#tg-threshold').value) || 0.35,
  };
  $('#tg-run').disabled = true; $('#tg-log').textContent = '提交中…';
  const r = await api('/api/tag/start', { method:'POST', body: JSON.stringify(body) });
  $('#tg-log').textContent = '$ ' + r.cmd + '\n';
  pollJob(r.job_id, 'tag');
}

/* ---------- 维护 ---------- */
function equalizeMaint() {
  const cards = $$('.maint-grid > .card');
  if (cards.length < 2) return;
  const L = cards[0], R = cards[1];
  R.style.height = 'auto';
  const h = Math.max(360, L.offsetHeight);
  R.style.height = h + 'px';
}

function setMaintLog(txt) {
  const el = $('#mt-log');
  if (!el) return;
  el.textContent = txt || '';
  el.style.display = (txt && String(txt).trim()) ? '' : 'none';
  setTimeout(equalizeMaint, 0);
}

async function refreshMaint() {
  const m = await api('/api/maintenance');
  $('#mt-disk').textContent = '可用 ' + m.disk.free_gb + ' GB / ' + m.disk.total_gb + ' GB';
  $('#mt-sizes').innerHTML = Object.entries(m.sizes).map(([k, v]) =>
    '<span class="k">' + k + '</span><span class="v">' + v + ' MB</span>').join('');
  $('#rg-count').textContent = m.registry + ' 条';
  const reg = await api('/api/registry?limit=80');
  $('#rg-table').innerHTML = reg.items.map(e =>
    '<div class="rg-row" data-path="' + (e.file || '') + '"><span>' + (e.ts || '').slice(5, 16) + '</span>' +
    '<span class="v v-' + (e.verdict || '') + '">' + (e.verdict || '') + '</span>' +
    '<span>' + esc((e.note || '') + ' · ' + (e.file || '').split('\\').pop()) + '</span></div>').join('');
  try {
    const tr = await api('/api/trash');
    let kEl = document.getElementById('tr-k');
    const kv = $('#mt-sizes');
    if (!kEl && kv) {
      kEl = document.createElement('span'); kEl.id = 'tr-k'; kEl.className = 'k'; kEl.textContent = '回收站';
      kv.appendChild(kEl);
      const vEl = document.createElement('span'); vEl.id = 'tr-v'; vEl.className = 'v';
      kv.appendChild(vEl);
    }
    const vEl = document.getElementById('tr-v');
    if (vEl) vEl.textContent = tr.count + ' 张 / ' + tr.mb + ' MB';
    const rs = $('#mt-restore'); const pg = $('#mt-purge');
    if (rs) rs.onclick = async () => {
      if (!confirm('把回收站里的 ' + tr.count + ' 张图全部恢复回原目录？')) return;
      const r = await api('/api/trash/restore-all', { method: 'POST' });
      toast('已恢复 ' + r.count + ' 张');
      refreshMaint();
    };
    if (pg) pg.onclick = async () => {
      if (!confirm('清空回收站？' + tr.count + ' 张图将无法恢复。')) return;
      const r = await api('/api/trash/purge', { method: 'POST' });
      toast('已删除 ' + r.removed + ' 个文件');
      refreshMaint();
    };
  } catch (e) {}
  setTimeout(equalizeMaint, 0);
  const ml = $('#mt-log');
  if (ml && !(ml.textContent || '').trim()) ml.style.display = 'none';
  const docs = await api('/api/docs');
  $('#doc-list').innerHTML = docs.items.map(d =>
    '<button data-doc="' + d.path + '">' + d.name + '</button>').join('');
  $$('#rg-table .rg-row').forEach(el => el.onclick = () => { if (el.dataset.path) openImage(el.dataset.path); });
  $$('#doc-list button').forEach(el => el.onclick = async () => {
    const r = await api('/api/doc?path=' + encodeURIComponent(el.dataset.doc));
    openModal(el.textContent, '<pre>' + esc(r.text) + '</pre>');
  });
}

async function cleanup(dry) {
  setMaintLog('清理中…');
  const r = await api('/api/maintenance/cleanup?dry=' + (dry ? 'true' : 'false'), { method:'POST' });
  setMaintLog(r.output || '');
  refreshMaint();
}

/* ---------- 悬停备注 ---------- */
let TIP = null;
function tipEl() {
  if (!TIP) {
    TIP = document.createElement('div');
    TIP.id = 'tip';
    document.body.appendChild(TIP);
  }
  return TIP;
}
function showTip(ev, token) {
  const note = (S.notes || {})[token];
  const body = note || '（还没有备注，可在「词库」里补一句）';
  const el = tipEl();
  el.innerHTML = '<b>' + token + '</b><span>' + esc(body) + '</span>';
  el.classList.add('show');
  moveTip(ev);
}
function moveTip(ev) {
  const el = tipEl();
  const w = el.offsetWidth || 260, h = el.offsetHeight || 60;
  let x = ev.clientX + 14, y = ev.clientY + 16;
  if (x + w > window.innerWidth - 8) x = ev.clientX - w - 12;
  if (y + h > window.innerHeight - 8) y = ev.clientY - h - 12;
  el.style.left = x + 'px';
  el.style.top = y + 'px';
}
function hideTip() { if (TIP) TIP.classList.remove('show'); }
function bindTips(root) {
  $$('[data-token]', root || document).forEach(el => {
    if (el.dataset.tipBound) return;
    el.dataset.tipBound = '1';
    el.addEventListener('mouseenter', e => showTip(e, el.dataset.token));
    el.addEventListener('mousemove', moveTip);
    el.addEventListener('mouseleave', hideTip);
  });
}

/* ---------- 描述面板 ---------- */
function insertDesc(lane) {
  const txt = ($('#desc-text').value || '').trim();
  if (!txt) { alert('先写一段描述'); return; }
  const w = parseFloat($('#desc-weight').value) || 1.1;
  addBlock(lane, { text: txt, weight: w });
  toast('已插入' + (lane === 'positive' ? '正向' : '负向') + ' · 权重 ' + w);
}

async function saveDescAsBlock() {
  const txt = ($('#desc-text').value || '').trim();
  if (!txt) { alert('先写一段描述'); return; }
  const name = prompt('给这块积木起个名字（会自动加 @USER_ 前缀）', 'BOOKSHOP');
  if (!name) return;
  const token = '@USER_' + name.toUpperCase().replace(/[^A-Z0-9_]/g, '_');
  const r = await api('/api/token/save', { method: 'POST', body: JSON.stringify({ name: token, text: txt, category: 'custom' }) });
  S.tokens = (await api('/api/bootstrap')).tokens;
  renderPalette();
  toast('已存为 ' + token);
}

/* ---------- IR 校验 ---------- */
async function validateBlocks() {
  const bar = $('#validate-bar');
  if (!bar) return;
  try {
    const v = await api('/api/validate', { method: 'POST', body: JSON.stringify({ positive: S.pos, negative: S.neg }) });
    S.validation = v;
    const parts = [];
    if (v.errors.length) parts.push('<b class="err">' + v.errors.length + ' 个错误</b>：' + v.errors.map(e => esc(e.msg)).join('；'));
    if (v.warnings.length) parts.push('<b class="warn-t">' + v.warnings.length + ' 个警告</b>：' + v.warnings.map(e => esc(e.msg)).join('；'));
    if (v.hints.length) parts.push('<b class="hint-t">建议</b>：' + v.hints.map(e => esc(e.msg)).join('；'));
    const bad = S.pos.concat(S.neg).filter(b => b.token && (S.rel || {})[b.token] === 'X');
    if (bad.length) {
      parts.push('<b class="warn-t">⚠ 实测失败积木</b>：' +
        [...new Set(bad.map(b => b.token))].join('、') + '（自动探针判定不达标）');
    }
    bar.innerHTML = parts.length ? parts.join('<br>') : '✓ 结构检查通过（身份/服装/型态/负向齐全）';
    bar.className = 'validate-bar ' + (v.errors.length ? 'bad' : (v.warnings.length ? 'warn' : 'ok'));
  } catch (e) { bar.textContent = ''; }
}

/* ---------- 引擎页 ---------- */
async function loadEngine() {
  let e;
  try { e = await api('/api/engine'); } catch (err) { $('#eng-summary').textContent = '读取失败'; return; }
  try { S.lastGraph = await api('/api/last-graph'); } catch (err) {}
  S.engine = e;
  $('#eng-summary').textContent = e.up ? '在线 ' + (e.version || '') : '离线';
  const sys = e.system || {};
  const dev = (e.devices || [])[0] || {};
  $('#eng-kv').innerHTML = [
    ['地址', e.comfy],
    ['版本', e.version || '—'],
    ['前端要求', e.frontend || '—'],
    ['显卡', (dev.name || '—') + ' · ' + Math.round((dev.vram_total || 0) / 1073741824) + 'GB'],
    ['队列', (e.queue ? e.queue.running + ' 跑 / ' + e.queue.pending + ' 等' : '—')],
  ].map(([k, v]) => '<span class="k">' + k + '</span><span class="v">' + esc(String(v)) + '</span>').join('');

  $('#eng-wf').innerHTML = (e.workflows || []).map(w =>
    '<div class="rg-row" style="grid-template-columns:150px 1fr"><span>' + w.name + '</span><span class="hint">' +
    (w.missing && w.missing.length ? '缺节点: ' + w.missing.join(', ') : '节点齐全 · ' + w.requires.length + ' 个依赖') +
    '</span></div>').join('');

  $('#eng-custom').innerHTML = (e.custom_nodes || []).map(n => '<button class="ghost">' + esc(n) + '</button>').join('') || '<span class="hint">无</span>';
  const pipe = S.lastGraph;
  $('#eng-pipe').textContent = pipe ? JSON.stringify(pipe, null, 2).slice(0, 4000)
    : '出图一次后，这里显示提交给 ComfyUI 的真实节点图。';
  $('#eng-pipe-hint').textContent = pipe ? (pipe.__workflow || '') : '';
}

async function runRegress() {
  const box = $('#regress-out');
  box.textContent = '检查中…';
  try {
    const r = await api('/api/regress');
    box.innerHTML = r.checks.map(c =>
      '<div class="chk-row ' + (c.ok ? 'ok' : 'bad') + '"><span class="chk-mark">' + (c.ok ? '✓' : '✗') + '</span>' +
      '<span class="chk-name">' + esc(c.name) + '</span><span class="chk-detail">' + esc(c.detail) + '</span></div>' +
      (c.ok ? '' : '<div class="chk-fix">修法：' + esc(c.fix) + '</div>')).join('');
  } catch (e) { box.textContent = '失败：' + e.message; }
}

/* ---------- 管线自检 ---------- */
async function pipelineCheck(auto) {
  let r;
  try { r = await api('/api/pipeline/check'); } catch (e) { return; }
  S.pipeline = r;
  const pill = $('#pill-check');
  if (pill) {
    pill.textContent = r.ok ? ('自检 ' + r.total + '/' + r.total) : ('自检 ' + (r.total - r.failed) + '/' + r.total);
    pill.className = 'pill ' + (r.ok ? 'ok' : 'bad');
  }
  const rows = r.checks.map(c =>
    '<div class="chk-row ' + (c.ok ? 'ok' : 'bad') + '">' +
    '<span class="chk-mark">' + (c.ok ? '✓' : '✗') + '</span>' +
    '<span class="chk-name">' + c.name + '</span>' +
    '<span class="chk-detail">' + esc(c.detail || '') + '</span></div>' +
    (c.ok ? '' : '<div class="chk-fix">修法：' + esc(c.fix || '') + '</div>')).join('');
  const head = r.ok
    ? '<p class="hint">全部 ' + r.total + ' 项通过，可以直接出图。</p>'
    : '<p class="hint" style="color:#c0392b">' + r.failed + ' 项异常，按下面的修法处理后点「重新自检」。</p>';
  const comfyBad = r.checks.some(c => c.id === 'comfy' && !c.ok);
  const html = head + '<div class="chk-list">' + rows + '</div>' +
    '<div style="margin-top:10px;display:flex;gap:8px">' +
    '<button class="primary" id="chk-again">重新自检</button>' +
    (comfyBad ? '<button class="ghost" id="chk-comfy">启动 ComfyUI</button>' : '') +
    '</div>';
  if (auto && r.ok) { openModal('管线自检 · 通过', html); }
  else { openModal(r.ok ? '管线自检 · 通过' : '管线自检 · 有异常', html); }
  const again = $('#chk-again');
  if (again) again.onclick = () => pipelineCheck(false);
  const cbtn = $('#chk-comfy');
  if (cbtn) cbtn.onclick = async () => {
    cbtn.disabled = true;
    cbtn.textContent = '启动中…（最长 80 秒）';
    const r2 = await api('/api/comfy/start', { method: 'POST' });
    if (r2.ok) pipelineCheck(false);
    else { cbtn.disabled = false; cbtn.textContent = '启动失败，点这里重试'; alert(r2.error || '启动失败'); }
  };
}

/* ---------- 复现页 ---------- */
async function runReproTab() {
  const ref = $('#rp-ref').value.trim();
  if (!ref) { alert('需要底图路径'); return; }
  $('#rp-go2').disabled = true;
  $('#rp-status').textContent = '提交中…';
  try {
    const r = await api('/api/reproduce', { method: 'POST', body: JSON.stringify({
      mode: $('#rp-mode2').value, reference: ref, prompt: $('#rp-p2').value,
      negative: (S.lastExpanded && S.lastExpanded.negative) || '',
      denoise: Number($('#rp-d2').value) || 0.78,
      width: Number($('#rp-w').value) || 1024, height: Number($('#rp-h').value) || 1536,
      steps: Number($('#rp-steps').value) || 28, cfg: Number($('#rp-cfg').value) || 5.4,
      prefix: 'repro', loras: S.loras }) });
    $('#rp-status').textContent = '生成中…';
    pollRepro(r.job_id);
  } catch (e) {
    $('#rp-go2').disabled = false;
    $('#rp-status').textContent = '失败：' + e.message;
  }
}

async function pollRepro(jid) {
  clearInterval(S.reproTimer);
  S.reproTimer = setInterval(async () => {
    let j;
    try { j = await api('/api/job/' + jid); } catch (e) { return; }
    $('#rp-status').textContent = '生成中 ' + (j.elapsed || 0) + 's · ' + Math.round((j.progress || 0) * 100) + '%';
    if (j.status !== 'running') {
      clearInterval(S.reproTimer);
      $('#rp-go2').disabled = false;
      const res = j.result || {};
      if (res.images && res.images.length) {
        $('#rp-status').textContent = '完成 · ' + res.elapsed + 's';
        const p = res.images[0];
        $('#rp-result').innerHTML = '<img src="/api/img?path=' + encodeURIComponent(p) + '">' +
          '<div class="logbar"><input id="rp-note" placeholder="备注（可空）">' +
          '<div class="verdicts"><button data-rv="A">A</button><button data-rv="B">B</button><button data-rv="C">C</button></div></div>';
        document.querySelectorAll('#rp-result [data-rv]').forEach(b => b.onclick = () =>
          logPick(p, b.dataset.rv, ($('#rp-note') || {}).value || ''));
      } else {
        $('#rp-status').textContent = '失败：' + (res.error || j.status);
      }
    }
  }, 1200);
}

function openReproPage(path) {
  $('#rp-ref').value = path || '';
  $('#rp-p2').value = (S.lastExpanded && S.lastExpanded.positive) || '';
  document.querySelector('#tabs button[data-tab="repro"]').click();
  setTimeout(rpLoadImage, 60);
}

/* ---------- 复现页：局部重绘 ---------- */
let RP = { path: null, box: null, mode: 'brush', ink: false, undo: [] };

function rpLoadImage() {
  const path = ($('#rp-ref') || {}).value || '';
  const img = $('#rp-inp-img'), sel = $('#rp-inp-sel');
  if (!path) { toast('先填底图路径', true); return; }
  RP = { path, box: null, mode: RP.mode || 'brush', ink: false, undo: [] };
  if (sel) { sel.style.display = 'none'; sel.style.width = '0px'; sel.style.height = '0px'; }
  if (img) img.src = '/api/img?path=' + encodeURIComponent(path);
  const ro = $('#rp-inp-readout');
  if (ro) ro.textContent = '已载入，在图上拖一个框';
  const btn = $('#rp-inp-go');
  if (btn) btn.disabled = true;
  const cv = $('#rp-inp-canvas');
  if (cv) {
    const setup = () => {
      cv.width = img.naturalWidth || 1024;
      cv.height = img.naturalHeight || 1536;
      const ctx = cv.getContext('2d');
      ctx.clearRect(0, 0, cv.width, cv.height);
      RP.ink = false;
    };
    if (img.complete && img.naturalWidth) setup(); else img.onload = setup;
  }
  rpBindBox();
  rpBindBrush();
  rpSetMode(RP.mode || 'brush');
  rpMaskRefresh();
}

function rpSetMode(mode) {
  RP.mode = mode;
  const wrap = $('#rp-inp-wrap');
  if (wrap) wrap.classList.toggle('box-mode', mode === 'box');
  $$('.mask-tools .mode').forEach(b => b.classList.toggle('on', b.dataset.maskMode === mode));
  const ro = $('#rp-inp-readout');
  if (ro) ro.textContent = mode === 'box' ? '框选模式：拖一个矩形' :
    (mode === 'erase' ? '橡皮：擦掉蒙版' : '画笔：在要重画的地方涂');
}

function rpHasInk() {
  const cv = $('#rp-inp-canvas');
  if (!cv || !cv.width) return 0;
  const t = document.createElement('canvas');
  t.width = 96; t.height = Math.max(1, Math.round(96 * cv.height / cv.width));
  const c = t.getContext('2d');
  c.drawImage(cv, 0, 0, t.width, t.height);
  const d = c.getImageData(0, 0, t.width, t.height).data;
  let n = 0;
  for (let i = 3; i < d.length; i += 4) if (d[i] > 12) n++;
  return n / (t.width * t.height);
}

function rpPushUndo() {
  const cv = $('#rp-inp-canvas');
  if (!cv) return;
  RP.undo = RP.undo || [];
  RP.undo.push(cv.getContext('2d').getImageData(0, 0, cv.width, cv.height));
  if (RP.undo.length > 10) RP.undo.shift();
}

function rpUpdateInk() {
  const ratio = rpHasInk();
  RP.ink = ratio > 0.0005;
  const btn = $('#rp-inp-go'); if (btn) btn.disabled = !RP.ink && !RP.box;
  const ro = $('#rp-inp-readout');
  if (ro) ro.textContent = RP.ink ? ('蒙版覆盖 ' + (ratio * 100).toFixed(1) + '%') : '蒙版为空，请画或改框选';
}

function rpUndo() {
  const cv = $('#rp-inp-canvas');
  if (!cv || !RP.undo || !RP.undo.length) { toast('没有可撤销的笔迹'); return; }
  cv.getContext('2d').putImageData(RP.undo.pop(), 0, 0);
  rpUpdateInk();
}

function rpBindBrush() {
  const cv = $('#rp-inp-canvas'), wrap = $('#rp-inp-wrap');
  if (!cv || !wrap || cv.dataset.bound === '1') return;
  cv.dataset.bound = '1';
  const ctx = cv.getContext('2d');
  let drawing = false, last = null;

  const toCanvas = ev => {
    const r = cv.getBoundingClientRect();
    return {
      x: (ev.clientX - r.left) * (cv.width / r.width),
      y: (ev.clientY - r.top) * (cv.height / r.height),
    };
  };
  const line = (a, b) => {
    const size = Number(($('#rp-inp-size') || {}).value) || 26;
    const w = size * (cv.width / (cv.getBoundingClientRect().width || cv.width));
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.lineWidth = Math.max(2, w);
    ctx.strokeStyle = '#ff2d55';
    ctx.globalCompositeOperation = (RP.mode === 'erase') ? 'destination-out' : 'source-over';
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
    if (RP.mode !== 'erase') RP.ink = true;
  };

  cv.addEventListener('mousedown', e => {
    if (RP.mode === 'box') return;
    e.preventDefault();
    rpPushUndo();
    drawing = true;
    last = toCanvas(e);
    line(last, last);
    const ro = $('#rp-inp-readout'); if (ro) ro.textContent = '正在画蒙版…';
  });
  cv.addEventListener('mousemove', e => {
    if (!drawing) return;
    const p = toCanvas(e);
    line(last, p);
    last = p;
  });
  window.addEventListener('mouseup', () => {
    if (!drawing) return;
    drawing = false;
    rpUpdateInk();
  });

  $$('.mask-tools .mode').forEach(b => b.onclick = () => rpSetMode(b.dataset.maskMode));
  const ms = $('#rp-mask-save'); if (ms) ms.onclick = rpMaskSave;
  const mo = $('#rp-mask-open'); if (mo) mo.onclick = rpMaskRefresh;
  const cb = $('#rp-inp-clearbtn');
  if (cb) cb.onclick = () => {
    rpPushUndo();
    ctx.clearRect(0, 0, cv.width, cv.height);
    rpUpdateInk();
    const ro = $('#rp-inp-readout'); if (ro) ro.textContent = RP.box ? '蒙版已清空（仍有框选）' : '蒙版已清空';
  };
  const ub = $('#rp-inp-undo');
  if (ub) ub.onclick = rpUndo;
}

async function rpMaskSave() {
  const img = ($('#rp-ref') || {}).value || RP.path;
  if (!img) { alert('先载入底图'); return; }
  if (!RP.ink) { alert('蒙版是空的，先画几笔'); return; }
  try {
    const r = await api('/api/mask/save', { method: 'POST', body: JSON.stringify({
      image: img, mask_b64: rpMaskDataURL() }) });
    toast('蒙版已保存：' + r.name);
    rpMaskRefresh();
  } catch (e) { toast('保存失败：' + e.message, true); }
}

async function rpMaskRefresh() {
  const box = $('#rp-mask-list'), cnt = $('#rp-mask-count');
  if (!box) return;
  const img = ($('#rp-ref') || {}).value || RP.path || '';
  let r;
  try { r = await api('/api/mask/list?image=' + encodeURIComponent(img)); } catch (e) { return; }
  if (cnt) cnt.textContent = r.total ? r.total + ' 个' : '空';
  if (!r.items.length) {
    box.innerHTML = '<div class="hint">还没有蒙版。画好点「存蒙版」。</div>';
    return;
  }
  box.innerHTML = r.items.map(it =>
    '<div class="mask-item" data-mask="' + esc(it.path) + '">' +
    '<img src="/api/img?path=' + encodeURIComponent(it.path) + '">' +
    '<div class="m"><b>' + esc(it.name) + '</b><span>' + Math.round(it.size / 1024) + ' KB</span></div></div>').join('');
  $$('#rp-mask-list .mask-item').forEach(el => el.onclick = () => rpApplyMask(el.dataset.mask));
}

function rpApplyMask(path) {
  const cv = $('#rp-inp-canvas');
  if (!cv) return;
  const im = new Image();
  im.onload = () => {
    const ctx = cv.getContext('2d');
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.drawImage(im, 0, 0, cv.width, cv.height);
    RP.ink = true;
    const btn = $('#rp-inp-go'); if (btn) btn.disabled = false;
    const ro = $('#rp-inp-readout'); if (ro) ro.textContent = '已套用蒙版：' + path.split('\\').pop();
    $$('#rp-mask-list .mask-item').forEach(el => el.classList.toggle('on', el.dataset.mask === path));
    toast('已套用蒙版');
  };
  im.src = '/api/img?path=' + encodeURIComponent(path);
}

function rpMaskDataURL() {
  const cv = $('#rp-inp-canvas');
  if (!cv) return '';
  const off = document.createElement('canvas');
  off.width = cv.width; off.height = cv.height;
  const c = off.getContext('2d');
  c.fillStyle = '#000';
  c.fillRect(0, 0, off.width, off.height);
  c.drawImage(cv, 0, 0);
  return off.toDataURL('image/png');
}

function rpBindBox() {
  const wrap = $('#rp-inp-wrap'), img = $('#rp-inp-img'), sel = $('#rp-inp-sel');
  if (!wrap || !img || !sel || wrap.dataset.bound === '1') return;
  wrap.dataset.bound = '1';
  let dragging = false, sx = 0, sy = 0;
  const toNatural = ev => {
    const r = img.getBoundingClientRect();
    const x = Math.max(0, Math.min(r.width, ev.clientX - r.left));
    const y = Math.max(0, Math.min(r.height, ev.clientY - r.top));
    return { x, y };
  };
  wrap.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    e.preventDefault();
    dragging = true;
    const p = toNatural(e); sx = p.x; sy = p.y;
    sel.style.display = 'block';
    sel.style.left = p.x + 'px'; sel.style.top = p.y + 'px';
    sel.style.width = '0px'; sel.style.height = '0px';
  });
  wrap.addEventListener('mousemove', e => {
    if (!dragging) return;
    const p = toNatural(e);
    const x = Math.min(sx, p.x), y = Math.min(sy, p.y);
    const w = Math.abs(p.x - sx), h = Math.abs(p.y - sy);
    sel.style.left = x + 'px'; sel.style.top = y + 'px';
    sel.style.width = w + 'px'; sel.style.height = h + 'px';
    rpReadBox();
  });
  window.addEventListener('mouseup', () => { if (!dragging) return; dragging = false; rpReadBox(); });
  const clr = $('#rp-inp-clear');
  if (clr) clr.onclick = () => {
    RP.box = null;
    sel.style.display = 'none'; sel.style.width = '0px'; sel.style.height = '0px';
    const ro = $('#rp-inp-readout'); if (ro) ro.textContent = '未选择区域';
    const btn = $('#rp-inp-go'); if (btn) btn.disabled = true;
  };
  const load = $('#rp-inp-load');
  if (load) load.onclick = rpLoadImage;
  const go = $('#rp-inp-go');
  if (go) go.onclick = runRepaint;
}

function rpReadBox() {
  const img = $('#rp-inp-img'), sel = $('#rp-inp-sel');
  if (!img || !sel || !img.naturalWidth) return;
  const r = img.getBoundingClientRect();
  const kx = img.naturalWidth / r.width, ky = img.naturalHeight / r.height;
  const x = Math.round(parseFloat(sel.style.left || 0) * kx);
  const y = Math.round(parseFloat(sel.style.top || 0) * ky);
  const w = Math.round(parseFloat(sel.style.width || 0) * kx);
  const h = Math.round(parseFloat(sel.style.height || 0) * ky);
  if (w < 8 || h < 8) return;
  RP.box = { x, y, w, h };
  const ro = $('#rp-inp-readout');
  if (ro) ro.textContent = '已选 ' + w + ' × ' + h + '（原图像素）';
  const btn = $('#rp-inp-go'); if (btn) btn.disabled = false;
  const p = $('#rp-inp-p');
  if (p && !p.value.trim() && S.lastExpanded) p.value = S.lastExpanded.positive.slice(0, 400);
}

async function runRepaint() {
  const useMask = RP.ink;
  if (!RP.box && !useMask) { alert('先在图上画蒙版，或切「框选」拖一个框'); return; }
  const img = ($('#rp-ref') || {}).value || RP.path;
  if (!img) { alert('底图路径为空'); return; }
  const box = [RP.box.x, RP.box.y, RP.box.w, RP.box.h].join(',');
  const go = $('#rp-inp-go');
  go.disabled = true; go.textContent = '提交中…';
  try {
    const r = await api('/api/inpaint', { method: 'POST', body: JSON.stringify({
      image: img, box,
      mask_b64: useMask ? rpMaskDataURL() : '',
      mask_feather: Number(($('#rp-inp-feather') || {}).value) || 0,
      prompt: ($('#rp-inp-p') || {}).value || '',
      negative: (S.lastExpanded && S.lastExpanded.negative) || '',
      denoise: Number(($('#rp-inp-d') || {}).value) || 0.6,
      steps: Number(($('#rp-inp-steps') || {}).value) || 26,
      cfg: Number(($('#rp-cfg') || {}).value) || 5.4,
      prefix: 'repaint', loras: S.loras }) });
    $('#rp-status').textContent = '局部重绘中…';
    pollRepro(r.job_id);
  } catch (e) {
    alert('失败：' + e.message);
    go.disabled = false; go.textContent = '执行局部重绘';
  }
}

/* ---------- 手部精修 / 复现 ---------- */
let HF = { path: null, box: null };

function openHandfix(path) {
  HF = { path, box: null };
  openModal('手部精修（在图上拖框）',
    '<div class="hf-grid"><div>' +
    '<div class="hf-wrap" id="hf-wrap"><img id="hf-img" src="/api/img?path=' + encodeURIComponent(path) + '">' +
    '<div class="hf-sel" id="hf-sel"></div></div>' +
    '<div class="hf-readout" id="hf-readout">未选择区域（在图上拖出要重画的手）</div>' +
    '</div><div>' +
    '<div class="field"><label>重绘幅度</label><input id="hf-d" type="number" step="0.05" value="0.55"></div>' +
    '<div class="field"><label>提示词（只描述要画的那块）</label><textarea id="hf-p" rows="3">(hand with five fingers:1.4), (fingers pressing the piano keys:1.4), (detailed fingers:1.35), same art style</textarea></div>' +
    '<div class="row2"><div class="field"><label>x</label><input id="hf-x" readonly></div>' +
    '<div class="field"><label>y</label><input id="hf-y" readonly></div></div>' +
    '<div class="row2"><div class="field"><label>宽</label><input id="hf-w" readonly></div>' +
    '<div class="field"><label>高</label><input id="hf-h" readonly></div></div>' +
    '<button class="ghost wide" id="hf-auto" style="margin-bottom:8px">自动找手</button>' +
    '<button class="ghost wide" id="hf-reset" style="margin-bottom:8px">重选</button>' +
    '<button class="primary wide" id="hf-go" disabled>开始精修</button>' +
    '<p class="hint" style="margin-top:8px">框贴着手，别罩住脸；denoise 0.45–0.6 最稳。<br>自动找手是启发式（肤色+指缝），会把人脸/调色板误判，选中后请核对。</p>' +
    '</div></div>');
  bindHandfix();
  setTimeout(() => { if (!location.search.includes('box=')) autoDetectHand(); }, 500);
  const m = location.search.match(/box=([0-9,]+)/);
  if (m) setTimeout(() => applyDemoBox(m[1].split(',').map(Number)), 300);
}

function applyDemoBox(box) {
  const img = $('#hf-img'), sel = $('#hf-sel');
  if (!img || !sel || box.length !== 4) return;
  const r = img.getBoundingClientRect();
  const kx = r.width / img.naturalWidth, ky = r.height / img.naturalHeight;
  sel.style.display = 'block';
  sel.style.left = (box[0] * kx) + 'px';
  sel.style.top = (box[1] * ky) + 'px';
  sel.style.width = (box[2] * kx) + 'px';
  sel.style.height = (box[3] * ky) + 'px';
  updateBoxFromSel();
}

function bindHandfix() {
  const wrap = $('#hf-wrap'), img = $('#hf-img'), sel = $('#hf-sel');
  let dragging = false, sx = 0, sy = 0;

  const toNatural = (ev) => {
    const r = img.getBoundingClientRect();
    const x = Math.max(0, Math.min(r.width, ev.clientX - r.left));
    const y = Math.max(0, Math.min(r.height, ev.clientY - r.top));
    return { x, y, nx: x / r.width * img.naturalWidth, ny: y / r.height * img.naturalHeight };
  };

  wrap.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    e.preventDefault();
    dragging = true;
    const p = toNatural(e);
    sx = p.x; sy = p.y;
    sel.style.display = 'block';
    sel.style.left = p.x + 'px'; sel.style.top = p.y + 'px';
    sel.style.width = '0px'; sel.style.height = '0px';
  });

  wrap.addEventListener('mousemove', e => {
    if (!dragging) return;
    const p = toNatural(e);
    const x = Math.min(sx, p.x), y = Math.min(sy, p.y);
    const w = Math.abs(p.x - sx), h = Math.abs(p.y - sy);
    sel.style.left = x + 'px'; sel.style.top = y + 'px';
    sel.style.width = w + 'px'; sel.style.height = h + 'px';
    updateBoxFromSel();
  });

  window.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    updateBoxFromSel();
  });

  const autoBtn = $('#hf-auto');
  if (autoBtn) autoBtn.onclick = autoDetectHand;
  $('#hf-reset').onclick = () => {
    HF.box = null; sel.style.display = 'none'; sel.style.width = '0px'; sel.style.height = '0px';
    ['hf-x','hf-y','hf-w','hf-h'].forEach(id => { $('#' + id).value = ''; });
    $('#hf-readout').textContent = '未选择区域（拖动图片框选手部）';
    $('#hf-go').disabled = true;
  };

  $('#hf-go').onclick = async () => {
    if (!HF.box) { alert('先在图上拖一个框'); return; }
    const box = [HF.box.x, HF.box.y, HF.box.w, HF.box.h].join(',');
    $('#hf-go').disabled = true;
    $('#hf-go').textContent = '提交中…';
    try {
      const r = await api('/api/handfix', { method: 'POST', body: JSON.stringify({
        image: HF.path, box, prompt: $('#hf-p').value, denoise: Number($('#hf-d').value) || 0.55,
        steps: 26, cfg: 5.2, prefix: 'handfix', loras: S.loras }) });
      closeModal();
      pollJob(r.job_id, 'run');
      $('#run-status').textContent = '手部精修中…';
    } catch (e) {
      alert('失败：' + e.message);
      $('#hf-go').disabled = false;
      $('#hf-go').textContent = '开始精修';
    }
  };
}

async function autoDetectHand() {
  const img = $('#hf-img');
  if (!img) return;
  const readout = $('#hf-readout');
  readout.textContent = '正在自动找手…';
  try {
    const r = await api('/api/detect-hand-auto?path=' + encodeURIComponent(HF.path));
    document.querySelectorAll('.hf-cand').forEach(el => el.remove());
    HF.cands = r.boxes || [];
    if (!HF.cands.length) {
      readout.textContent = '没找到候选（肤色/轮廓不匹配）。请手动拖框。';
      return;
    }
    const wrap = $('#hf-wrap');
    const rect = img.getBoundingClientRect();
    const kx = rect.width / img.naturalWidth, ky = rect.height / img.naturalHeight;
    HF.cands.forEach((b, i) => {
      const d = document.createElement('div');
      d.className = 'hf-cand';
      d.style.left = (b.x * kx) + 'px';
      d.style.top = (b.y * ky) + 'px';
      d.style.width = (b.w * kx) + 'px';
      d.style.height = (b.h * ky) + 'px';
      d.dataset.i = i;
      d.innerHTML = '<span>' + (i + 1) + '</span>';
      d.onclick = e => { e.stopPropagation(); pickCandidate(i); };
      wrap.appendChild(d);
    });
    const src = r.source || '';
    const srcText = src.startsWith('pose') ? '姿态模型' : '肤色兜底';
    readout.textContent = '找到 ' + HF.cands.length + ' 个候选（来源：' + srcText + '，点一下选中；不对就手动拖）';
  } catch (e) {
    readout.textContent = '自动找手失败：' + e.message;
  }
}

function pickCandidate(i) {
  const b = (HF.cands || [])[i];
  if (!b) return;
  HF.box = { x: b.x, y: b.y, w: b.w, h: b.h };
  const img = $('#hf-img'), sel = $('#hf-sel');
  const rect = img.getBoundingClientRect();
  const kx = rect.width / img.naturalWidth, ky = rect.height / img.naturalHeight;
  sel.style.display = 'block';
  sel.style.left = (b.x * kx) + 'px'; sel.style.top = (b.y * ky) + 'px';
  sel.style.width = (b.w * kx) + 'px'; sel.style.height = (b.h * ky) + 'px';
  $('#hf-x').value = b.x; $('#hf-y').value = b.y; $('#hf-w').value = b.w; $('#hf-h').value = b.h;
  $('#hf-go').disabled = false;
  $('#hf-readout').textContent = '候选 ' + (i + 1) + '：' + b.w + ' × ' + b.h +
    '（指缝 ' + (b.defects || 0) + '，置信 ' + b.score + '）';
}

function updateBoxFromSel() {
  const img = $('#hf-img'), sel = $('#hf-sel');
  if (!img || !sel || !img.naturalWidth) return;
  const r = img.getBoundingClientRect();
  const kx = img.naturalWidth / r.width, ky = img.naturalHeight / r.height;
  const x = Math.round(parseFloat(sel.style.left || 0) * kx);
  const y = Math.round(parseFloat(sel.style.top || 0) * ky);
  const w = Math.round(parseFloat(sel.style.width || 0) * kx);
  const h = Math.round(parseFloat(sel.style.height || 0) * ky);
  if (w < 8 || h < 8) return;
  HF.box = { x, y, w, h };
  $('#hf-x').value = x; $('#hf-y').value = y; $('#hf-w').value = w; $('#hf-h').value = h;
  $('#hf-readout').textContent = '已选 ' + w + ' × ' + h + '（原图像素）';
  $('#hf-go').disabled = false;
}

function openRepro(path) {
  openModal('复现模式',
    '<div class="field"><label>模式</label><select id="rp-mode">' +
    '<option value="keep_person">保人物 · 换画面（改场景/姿势，denoise 0.7–0.8）</option>' +
    '<option value="keep_image">保画面 · 换人物（同构图，改人/风格，denoise 0.6–0.75）</option>' +
    '</select></div>' +
    '<div class="field"><label>重绘幅度</label><input id="rp-d" type="number" step="0.05" value="0.72"></div>' +
    '<div class="field"><label>提示词（复现目标）</label><textarea id="rp-p" rows="4"></textarea></div>' +
    '<p class="hint">说明：保画面换人物需要「另一个身份 LoRA」；只有 h2 时只能改风格/发色，换不了整张脸。</p>' +
    '<button class="primary wide" id="rp-go">开始复现</button>');
  $('#rp-p').value = (S.lastExpanded && S.lastExpanded.positive) || '';
  $('#rp-go').onclick = async () => {
    $('#rp-go').disabled = true;
    $('#rp-go').textContent = '提交中…';
    try {
      const r = await api('/api/reproduce', { method: 'POST', body: JSON.stringify({
        mode: $('#rp-mode').value, reference: path, prompt: $('#rp-p').value,
        negative: (S.lastExpanded && S.lastExpanded.negative) || '',
        denoise: Number($('#rp-d').value) || 0.72, width: 1024, height: 1536,
        steps: 28, cfg: 5.4, prefix: 'repro', loras: S.loras }) });
      closeModal();
      pollJob(r.job_id, 'run');
    } catch (e) { alert('失败：' + e.message); $('#rp-go').disabled = false; $('#rp-go').textContent = '开始复现'; }
  };
}

/* ---------- 批量 ---------- */
async function openBatch() {
  if (!S.lastExpanded || !S.lastExpanded.positive) await expandPreview();
  const seed = Number($('#p-seed').value) || 0;
  const _q = new URLSearchParams(location.search);
  const _sz = size();
  const w = Number(_q.get('bw')) || _sz.w;
  const h = Number(_q.get('bh')) || _sz.h;
  const stepsN = Number(_q.get('bsteps')) || Number($('#p-steps').value) || 30;
  openModal('批量生成',
    '<p class="hint">用当前正向/负向与参数，连续出 N 张；种子从起始值按步长递增。</p>' +
    '<p class="hint">当前：' + w + '×' + h + ' · ' + stepsN + ' 步 · 正向 ' + (S.lastExpanded ? S.lastExpanded.positive.length : 0) + ' 字符</p>' +
    '<div class="row2"><div class="field"><label>张数（1–12）</label><input id="bt-count" type="number" value="4" min="1" max="12"></div>' +
    '<div class="field"><label>种子步长</label><input id="bt-step" type="number" value="1"></div></div>' +
    '<div class="field"><label>起始种子（0=随机）</label><input id="bt-seed" type="number" value="' + seed + '"></div>' +
    '<button class="primary wide" id="bt-go">开始批量</button>' +
    '<div id="bt-progress" class="hint" style="margin-top:10px">准备中…</div>' +
    '<div class="pbar"><i id="bt-bar" style="width:0%"></i></div>' +
    '<div id="bt-grid" class="gallery" style="margin-top:10px"></div>' +
    '<div class="row2" style="margin-top:10px">' +
    '<button class="ghost" id="bt-gallery">打开画廊</button>' +
    '<button class="ghost" id="bt-close">关闭</button></div>');
  if (_q.get('brun')) setTimeout(() => { const g = $('#bt-go'); if (g) g.click(); }, 300);
  const bindBatchGrid = () => {
    $$('#bt-grid .g-item[data-img]').forEach(el => el.onclick = () => openImage(el.dataset.img));
  };
  $('#bt-gallery').onclick = () => { closeModal(); const b = document.querySelector('#tabs button[data-tab="gallery"]'); if (b) b.click(); renderGallery(); };
  $('#bt-close').onclick = closeModal;

  $('#bt-go').onclick = async () => {
    if (!S.lastExpanded || !S.lastExpanded.positive) {
      try { await expandPreview(); } catch (e) {}
    }
    const ex = S.lastExpanded;
    if (!ex || !ex.positive) { alert('提示词还没展开：先在「拼装」里放几块积木'); return; }
    const count = Math.max(1, Math.min(12, Number($('#bt-count').value) || 4));
    $('#bt-go').disabled = true;
    $('#bt-go').textContent = '提交中…';
    try {
      const r = await api('/api/batch', { method: 'POST', body: JSON.stringify({
        prompt: ex.positive, negative: ex.negative,
        width: Number(_q.get('bw')) || size().w,
        height: Number(_q.get('bh')) || size().h,
        steps: Number(_q.get('bsteps')) || Number($('#p-steps').value) || 30,
        cfg: Number($('#p-cfg').value) || 5.5,
        count: Number(_q.get('bcount')) || count,
        seed_start: Number($('#bt-seed').value) || 0,
        seed_step: Number($('#bt-step').value) || 1,
        prefix: 'bt', loras: S.loras, blocks_pos: S.pos, blocks_neg: S.neg }) });
      $('#bt-go').textContent = '生成中…（可关窗，后台继续）';

      const timer = setInterval(async () => {
        let j;
        try { j = await api('/api/job/' + r.job_id); } catch (e) { return; }
        const items = j.items || [];
        const doneN = items.filter(x => x.status === 'done').length;
        const pct = Math.round((j.progress || 0) * 100);
        $('#bt-progress').textContent = '进度 ' + pct + '% · 完成 ' + doneN + '/' + items.length +
          (j.status === 'running' ? '' : ' · ' + (j.status === 'done' ? '全部结束' : j.status));
        const bar = $('#bt-bar');
        if (bar) bar.style.width = pct + '%';
        $('#bt-grid').innerHTML = items.map(it => it.image
          ? '<div class="g-item" data-img="' + esc(it.image) + '" title="点击放大 / 登记 / 删除">' +
            '<img loading="lazy" src="/api/img?path=' + encodeURIComponent(it.image) + '">' +
            '<span class="v">' + it.status[0].toUpperCase() + '</span>' +
            '<div class="meta"><span>s' + it.seed + '</span><span>' + it.status + '</span></div></div>'
          : '<div class="g-item" style="display:flex;align-items:center;justify-content:center;color:#8b93a2;font-size:12px"' +
            (it.error ? ' title="' + esc(it.error) + '"' : '') + '>s' + it.seed + '<br>' + it.status + '</div>').join('');
        bindBatchGrid();

        if (j.status !== 'running') {
          clearInterval(timer);
          $('#bt-go').disabled = false;
          $('#bt-go').textContent = '再跑一批';
          if (doneN) {
            toast('批量完成 ' + doneN + ' 张，已存入画廊');
            renderGallery();
          }
        }
      }, 1500);
    } catch (e) {
      alert('批量失败：' + e.message);
      $('#bt-go').disabled = false;
      $('#bt-go').textContent = '开始批量';
    }
  };
}

/* ---------- 配方 ---------- */
async function loadRecipes() {
  let r;
  try { r = await api('/api/recipes?limit=120'); } catch (e) { return; }
  const box = $('#rc-list');
  const cnt = $('#rc-count');
  if (cnt) cnt.textContent = r.total + ' 张';
  if (!box) return;
  if (!r.items.length) {
    box.innerHTML = '<div class="hint">还没有配方记录。出图时会自动记下积木、参数与 LoRA。</div>';
    return;
  }
  box.innerHTML = r.items.map(it =>
    '<div class="rc-item" data-path="' + esc(it.path) + '">' +
    '<img loading="lazy" src="/api/img?path=' + encodeURIComponent(it.path) + '">' +
    '<div class="m"><b>' + esc(it.name.slice(0, 22)) + '</b>' +
    '<span>' + (it.mode || '') + ' · ' + (it.lora_n || 0) + ' LoRA</span></div>' +
    '<input type="checkbox" class="rc-check" data-cmp-path="' + esc(it.path) + '" title="加入对比">' +
    '</div>').join('');
  $$('#rc-list .rc-item').forEach(el => el.onclick = () => openRecipe(el.dataset.path, true));
  $$('#rc-list .rc-check').forEach(cb => {
    cb.onclick = e => { e.stopPropagation(); toggleCompare(cb.dataset.cmpPath); };
    cb.checked = S.compareSel.indexOf(cb.dataset.cmpPath) >= 0;
  });
}

function toggleCompare(path) {
  const i = S.compareSel.indexOf(path);
  if (i >= 0) S.compareSel.splice(i, 1);
  else {
    if (S.compareSel.length >= 4) { toast('最多选 4 张对比', true); return; }
    S.compareSel.push(path);
  }
  $$('#rc-list .rc-item').forEach(el => el.classList.toggle('on', S.compareSel.indexOf(el.dataset.path) >= 0));
  toast('已选 ' + S.compareSel.length + ' 张');
}

function openCompare() {
  const picks = S.compareSel.slice();
  if (picks.length < 2) { toast('至少选 2 张', true); return; }
  const html = '<div class="cmp-bar"><button class="ghost tiny" id="cmp-fit">适应</button>' +
    '<button class="ghost tiny" id="cmp-one">1:1</button>' +
    '<span class="hint" id="cmp-pct">100%</span>' +
    '<span class="hint" style="margin-left:auto">滚轮同步缩放 ' + picks.length + ' 张</span></div>' +
    '<div class="cmp-grid">' + picks.map(p =>
      '<div class="cmp-cell"><img src="/api/img?path=' + encodeURIComponent(p) + '" data-cmp>' +
      '<div class="cmp-name">' + esc(p.split('\\').pop()) + '</div></div>').join('') + '</div>';
  openModal('配方对比', html);
  let scale = 1;
  const imgs = $$('#modal-content img[data-cmp]');
  const apply = () => {
    imgs.forEach(im => { im.style.transform = 'scale(' + scale + ')'; });
    const pct = $('#cmp-pct'); if (pct) pct.textContent = Math.round(scale * 100) + '%';
  };
  imgs.forEach(im => {
    im.style.transformOrigin = 'center center';
    im.style.cursor = 'zoom-in';
    im.onwheel = e => {
      e.preventDefault();
      scale = Math.max(0.2, Math.min(6, scale * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
      apply();
    };
  });
  const fit = $('#cmp-fit'); if (fit) fit.onclick = () => { scale = 1; apply(); };
  const one = $('#cmp-one'); if (one) one.onclick = () => { scale = 2; apply(); };
}

function fmtTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const p2 = n => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + p2(d.getMonth() + 1) + '-' + p2(d.getDate()) + ' ' +
    p2(d.getHours()) + ':' + p2(d.getMinutes());
}

function blockChips(blocks, lane, emptyHint) {
  if (!blocks || !blocks.length) return '<span class="hint">' + (emptyHint || '（没有记录积木）') + '</span>';
  return blocks.map(b => {
    const name = b.token || '文本';
    const w = b.weight === undefined ? 1 : b.weight;
    const off = b.enabled === false ? ' off' : '';
    const cat = b.token ? tokenCat(b.token) : 'custom';
    return '<span class="rc-chip' + off + '" data-cat="' + cat + '">' + esc(name) +
      '<i>×' + w + '</i></span>';
  }).join('');
}

async function openRecipe(path, stay) {
  const tabBtn = document.querySelector('#tabs button[data-tab="recipe"]');
  if (!stay && tabBtn) tabBtn.click();
  const body = $('#rc-body');
  if (!body) return;
  body.innerHTML = '<p class="hint">读取配方…</p>';
  let r;
  try { r = await api('/api/recipe?path=' + encodeURIComponent(path)); }
  catch (e) {
    // 先试：从 PNG 内嵌的 ComfyUI 元数据恢复精确配方
    try {
      const r2 = await api('/api/recipe/from-image', { method: 'POST', body: JSON.stringify({ path }) });
      if (r2 && r2.ok) { toast('已从图片元数据恢复精确配方'); loadRecipes(); return openRecipe(path, true); }
    } catch (e2) {}
    body.innerHTML = '<p class="hint">这张图没有配方记录，且 PNG 里也没有 ComfyUI 元数据。</p>' +
      '<button class="primary wide" id="rc-infer" style="margin-top:10px">用当前积木补一份配方（推断）</button>' +
      '<p class="hint" style="margin-top:8px">会用你现在的积木 + 文件名里的种子 + 图片尺寸生成，并标注「推断」。</p>';
    const inf = $('#rc-infer');
    if (inf) inf.onclick = async () => {
      inf.disabled = true; inf.textContent = '推断中…';
      try {
        const ex = S.lastExpanded || await expandPreview();
        const r2 = await api('/api/recipe/infer', { method: 'POST', body: JSON.stringify({
          path, blocks_pos: S.pos, blocks_neg: S.neg, prompt: ex.positive, negative: ex.negative,
          loras: S.loras, steps: Number($('#p-steps').value) || 30, cfg: Number($('#p-cfg').value) || 5.5 }) });
        toast('已生成推断配方');
        openRecipe(path, true);
        loadRecipes();
      } catch (err) { toast('推断失败：' + err.message, true); inf.disabled = false; }
    };
    return;
  }
  const nameEl = $('#rc-name');
  if (nameEl) nameEl.textContent = path.split('\\').pop();
  const local = ['inpaint', 'repaint', 'handfix', 'i2i', 'repro'].includes(String(r.mode || ''));
  const emptyHint = local
    ? '（' + (r.mode || '局部重绘') + ' 只记录局部提示词，没有整图积木）'
    : '（这张图生成时没带积木记录：可能是旧版本或非拼装页入口）';
  const loras = (r.loras || []).map(l => '<span class="rc-chip" data-cat="id">' +
    esc(l.name) + '<i>×' + (l.weight !== undefined ? l.weight : '?') + '</i></span>').join('') || '<span class="hint">无</span>';
  body.innerHTML =
    '<div class="rc-head"><img src="/api/img?path=' + encodeURIComponent(path) + '">' +
      '<div class="rc-kv">' +
        '<span class="k">时间</span><span class="v">' + fmtTime(r.ts) + '</span>' +
        (r.inferred ? '<span class="k">来源</span><span class="v" style="color:#ffcf70">推断 · ' + esc(r.source_template || '手动') + '</span>' : '') +
        (r.blocks_guess ? '<span class="k">积木</span><span class="v" style="color:#ffcf70">按提示词反推 · 权重不精确</span>' : '') +
        '<span class="k">模式</span><span class="v">' + esc(r.mode || '') + '</span>' +
        '<span class="k">工作流</span><span class="v">' + esc(r.workflow || '') + '</span>' +
        '<span class="k">尺寸</span><span class="v">' + (r.size || []).join(' × ') + '</span>' +
        '<span class="k">步数 / CFG</span><span class="v">' + r.steps + ' / ' + r.cfg + '</span>' +
        '<span class="k">种子</span><span class="v">' + r.seed + '</span>' +
        '<span class="k">denoise</span><span class="v">' + (r.denoise === null || r.denoise === undefined ? '-' : r.denoise) + '</span>' +
        (r.reference ? '<span class="k">底图</span><span class="v">' + esc(String(r.reference).split('\\').pop()) + '</span>' : '') +
      '</div></div>' +
    '<h4 class="rc-h">正向积木</h4><div class="rc-chips">' + blockChips(r.blocks_pos, null, emptyHint) + '</div>' +
    '<h4 class="rc-h">负向积木</h4><div class="rc-chips">' + blockChips(r.blocks_neg, null, emptyHint) + '</div>' +
    '<h4 class="rc-h">LoRA</h4><div class="rc-chips">' + loras + '</div>' +
    '<h4 class="rc-h">展开后的正向</h4><pre class="prompt-preview">' + esc(r.positive || '') + '</pre>' +
    '<h4 class="rc-h">展开后的负向</h4><pre class="prompt-preview neg">' + esc(r.negative || '') + '</pre>' +
    '<div class="row2" style="margin-top:10px">' +
      '<button class="ghost" id="rc-copy">复制正向</button>' +
      '<button class="ghost" id="rc-img">看图</button></div>';
  const cp = $('#rc-copy');
  if (cp) cp.onclick = async () => {
    try { await navigator.clipboard.writeText(r.positive || ''); toast('正向已复制'); }
    catch (e) { toast('复制失败：' + e.message, true); }
  };
  const im = $('#rc-img');
  if (im) im.onclick = () => openImage(path);
  $$('#rc-list .rc-item').forEach(el => el.classList.toggle('on', el.dataset.path === path));
}

/* ---------- 通用 ---------- */
function toast(msg, bad) {
  let el = $('#toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.className = 'toast show' + (bad ? ' bad' : '');
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.className = 'toast'; }, 2600);
}

function openModal(title, html) {
  $('#modal-title').textContent = title;
  $('#modal-content').innerHTML = html;
  $('#modal').classList.add('open');
}
function closeModal() { $('#modal').classList.remove('open'); }

function applyTemplate(tpl) {
  pushHistory();
  S.pos = (tpl.positive || []).map(b => Object.assign({ id: uid(), weight: 1, enabled: true, text: '' }, b));
  S.neg = (tpl.negative || []).map(b => Object.assign({ id: uid(), weight: 1, enabled: true, text: '' }, b));
  // 模板里混进正向的负向积木，自动挪回负向
  const moved = S.pos.filter(b => b.token && tokenCat(b.token) === 'neg');
  if (moved.length) {
    S.pos = S.pos.filter(b => !(b.token && tokenCat(b.token) === 'neg'));
    S.neg = S.neg.concat(moved);
  }
  if (tpl.params) {
    if (tpl.params.size) $('#p-size').value = tpl.params.size;
    if (tpl.params.steps) $('#p-steps').value = tpl.params.steps;
    if (tpl.params.cfg) $('#p-cfg').value = tpl.params.cfg;
  }
  renderLanes(); expandPreview();
}

async function loadTemplates() {
  const r = await api('/api/templates');
  S.templates = r.items || [];
  $('#tpl-row').innerHTML = S.templates.map((t, i) =>
    '<button class="ghost" data-tpl="' + i + '">' + t.name + '</button>').join('') +
    '<button class="ghost" id="tpl-create">＋ 创造</button>';
  $$('#tpl-row button[data-tpl]').forEach(el => el.onclick = () => applyTemplate(S.templates[Number(el.dataset.tpl)]));
  const tc = $('#tpl-create');
  if (tc) tc.onclick = saveCurrentAsTemplate;
}

async function loadPresets() {
  const r = await api('/api/presets');
  S.presets = r.items || [];
}

/* ---------- 事件绑定 ---------- */
function bindUI() {
  $$('#tabs button').forEach(b => b.onclick = () => {
    $$('#tabs button').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    $$('.view').forEach(v => v.classList.remove('active'));
    $('#view-' + b.dataset.tab).classList.add('active');
    if (b.dataset.tab === 'gallery') renderGallery();
    if (b.dataset.tab === 'train') trainInfo();
    if (b.dataset.tab === 'maint') refreshMaint();
    if (b.dataset.tab === 'engine') loadEngine();
  });
  $('#palette-search').oninput = e => { S.paletteFilter = e.target.value; renderPalette(); };
  $('#lib-search').oninput = e => loadLibrary(e.target.value);
  document.querySelectorAll('[data-adddesc]').forEach(b => b.onclick = () => {
    const lane = b.dataset.adddesc;
    const v = prompt('写一段画面描述（中文也行，模型会按英文标签理解；建议用英文关键词混写）', '');
    if (!v) return;
    const w = parseFloat(prompt('这段描述的权重（0.6–1.5，默认 1.1）', '1.1') || '1.1') || 1.1;
    addBlock(lane, { text: v, weight: w });
  });
  document.querySelectorAll('[data-addtext]').forEach(b => b.onclick = () => {
    const lane = b.dataset.addtext;
    const v = prompt('文本块内容（可直接写英文标签）', '');
    if (v) addBlock(lane, { text: v });
  });
  $$('[data-clear]').forEach(b => b.onclick = () => {
    pushHistory();
    if (b.dataset.clear === 'positive') S.pos = []; else S.neg = [];
    renderLanes(); expandPreview();
  });
  $('#run-btn').onclick = run;
  const goTab = name => { const b = document.querySelector('#tabs button[data-tab="' + name + '"]'); if (b) b.click(); };

  const pc0 = $('#pal-collapse');
  if (pc0) pc0.onclick = () => setLibCollapsed(true);
  const fab = $('#lib-fab');
  if (fab) fab.onclick = () => setLibCollapsed(false);
  setLibCollapsed(localStorage.getItem('loom.libCollapsed') === '1');

  const cmd = $('#cmdbar');
  if (cmd) {
    cmd.addEventListener('mousedown', e => { if (e.target === cmd) closeCmd(); });
    const inp = $('#cmd-input');
    inp.addEventListener('input', () => renderCmd(inp.value));
    inp.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown') { e.preventDefault(); cmdMove(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); cmdMove(-1); }
      else if (e.key === 'Enter') {
        e.preventDefault();
        if (e.shiftKey || !(S.cmdItems || []).length) {
          const v = inp.value.trim();
          if (v) { addBlock('positive', { text: v }); toast('已作为文本块加入'); closeCmd(); }
        } else {
          cmdAdd(S.cmdSel || 0);
        }
      } else if (e.key === 'Escape') { closeCmd(); }
    });
  }
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      if (cmd && cmd.classList.contains('open')) closeCmd(); else openCmd('');
    }
    if (e.key === 'Escape' && cmd && cmd.classList.contains('open')) closeCmd();
  });
  const pc = $('#pill-comfy');
  if (pc) {
    pc.title = '打开 ComfyUI 客户端（新标签页）';
    pc.onclick = async () => {
      let up = !!(S.comfy && S.comfy.up);
      let url = (S.comfy && S.comfy.url) || 'http://127.0.0.1:8188';
      if (!up) {
        try {
          const b = await api('/api/bootstrap');
          S.comfy = b.comfy || S.comfy;
          up = !!(b.comfy && b.comfy.up);
          url = (b.comfy && b.comfy.url) || url;
          $('#pill-comfy').textContent = up ? ('ComfyUI ' + b.comfy.version) : 'ComfyUI 未启动';
          $('#pill-comfy').className = 'pill ' + (up ? 'ok' : 'bad');
        } catch (e) {}
      }
      if (up) {
        window.open(url, '_blank', 'noopener');
        toast('已打开 ComfyUI：' + url);
      } else {
        pipelineCheck(false);
      }
    };
  }
  const pq = $('#pill-queue');
  if (pq) pq.onclick = async () => {
    try {
      const b = await api('/api/bootstrap');
      const q = b.queue || { running: 0, pending: 0 };
      openModal('队列',
        '<div class="kv"><span class="k">运行中</span><span class="v">' + q.running + '</span>' +
        '<span class="k">排队</span><span class="v">' + q.pending + '</span>' +
        '<span class="k">ComfyUI</span><span class="v">' + (b.comfy.up ? b.comfy.version : '未启动') + '</span></div>' +
        '<p class="hint" style="margin-top:10px">队列由 ComfyUI 管理；这里只读。</p>' +
        '<div class="row2"><button class="ghost" id="q-engine">打开引擎页</button>' +
        '<button class="ghost" id="q-refresh">刷新</button></div>');
      $('#q-engine').onclick = () => { closeModal(); goTab('engine'); };
      $('#q-refresh').onclick = () => { closeModal(); pq.onclick(); };
    } catch (e) { toast('读取队列失败：' + e.message, true); }
  };
  const pr = $('#pill-reg');
  if (pr) pr.onclick = () => goTab('maint');
  const pk = $('#pill-check');
  if (pk) pk.onclick = () => pipelineCheck(false);
  const bb2 = $('#batch-btn2');
  if (bb2) bb2.onclick = async () => {
    try {
      if (!S.lastExpanded || !S.lastExpanded.positive) await expandPreview();
      await openBatch();
    } catch (e) { toast('打开批量失败：' + e.message, true); }
  };
  $('#p-size').onchange = updateEta;
  $('#p-steps').oninput = updateEta;
  $('#p-cfg').oninput = updateEta;
  $('#p-seed').oninput = updateEta;
  $('#g-dir').onchange = renderGallery;
  ['g-rating', 'g-recipe', 'g-date'].forEach(id => {
    const el = $('#' + id);
    if (el) el.onchange = renderGallery;
  });
  let gqTimer = null;
  const gq = $('#g-q');
  if (gq) gq.oninput = () => { clearTimeout(gqTimer); gqTimer = setTimeout(renderGallery, 250); };
  const gsel = $('#g-select');
  if (gsel) gsel.onclick = () => {
    S.gallerySelect = !S.gallerySelect;
    if (!S.gallerySelect) S.gallerySel = {};
    gsel.textContent = S.gallerySelect ? '退出选择' : '选择导出';
    renderGallery();
  };
  const gexp = $('#g-export');
  if (gexp) gexp.onclick = exportSelected;
  $('#g-refresh').onclick = renderGallery;
  $('#tk-save').onclick = saveToken;
  $('#tk-del').onclick = delToken;
  $('#tk-note-save').onclick = saveNote;
  const gnew = $('#gm-new'); if (gnew) gnew.onclick = newGarment;
  const gsave = $('#gm-save2'); if (gsave) gsave.onclick = saveGarment;
  const gdel = $('#gm-del2'); if (gdel) gdel.onclick = deleteGarment;
  rpBindBox();
  const rcl = $('#rp-inp-load');
  if (rcl) rcl.onclick = rpLoadImage;
  const rcb = $('#rc-backfill');
  if (rcb) rcb.onclick = async () => {
    rcb.disabled = true; rcb.textContent = '回填中…';
    try {
      const r = await api('/api/recipe/backfill', { method: 'POST' });
      toast('恢复 ' + r.recovered + ' 张（跳过 ' + r.skipped + '）');
      loadRecipes();
    } catch (e) { toast('回填失败：' + e.message, true); }
    rcb.disabled = false; rcb.textContent = '回填历史';
  };
  const efree = $('#eng-free');
  if (efree) efree.onclick = async () => {
    efree.disabled = true; efree.textContent = '释放中…';
    try {
      const r = await api('/api/comfy/free', { method: 'POST' });
      toast(r.ok ? '已释放显存与模型' : ('失败：' + (r.error || '')), !r.ok);
    } catch (e) { toast('失败：' + e.message, true); }
    efree.disabled = false; efree.textContent = '释放显存';
  };
  const erst = $('#eng-restart');
  if (erst) erst.onclick = async () => {
    if (!confirm('重启 ComfyUI？supervisor 会在 60 秒内拉起。')) return;
    erst.disabled = true; erst.textContent = '重启中…';
    try { await api('/api/comfy/restart', { method: 'POST' }); toast('已发送重启，约 60 秒后可用'); }
    catch (e) { toast('失败：' + e.message, true); }
    setTimeout(() => { erst.disabled = false; erst.textContent = '重启 ComfyUI'; }, 30000);
  };
  const rcmp = $('#rc-compare');
  if (rcmp) rcmp.onclick = openCompare;
  const eopen = $('#eng-open');
  if (eopen) eopen.onclick = () => {
    const url = (S.comfy && S.comfy.url) || 'http://127.0.0.1:8188';
    window.open(url, '_blank', 'noopener');
  };
  $('#tr-run').onclick = () => startTrain(false);
  $('#tr-dry').onclick = () => startTrain(true);
  $('#tg-run').onclick = startTag;
  $('#mt-dry').onclick = () => cleanup(true);
  $('#mt-run').onclick = () => { if (confirm('执行清理？登记作品会保留')) cleanup(false); };
  $('#help-btn').onclick = async () => {
    const r = await api('/api/features');
    const body = r.groups.map(g =>
      '<h4 style="margin:14px 0 6px">' + g.group + '</h4><ul style="margin:0;padding-left:18px">' +
      g.items.map(i => '<li style="font-size:12.5px;color:#c3c9d6;margin:2px 0">' + i + '</li>').join('') + '</ul>').join('');
    openModal('功能总览', body);
  };
  $('#modal-close').onclick = closeModal;
  $('#modal').onclick = e => { if (e.target.id === 'modal') closeModal(); };
  let rzT = null;
  window.addEventListener('resize', () => { clearTimeout(rzT); rzT = setTimeout(equalizeMaint, 150); });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
    const modalOpen = $('#modal').classList.contains('open');
    if (modalOpen && ['1', '2', '3'].includes(e.key)) {
      const v = ['A', 'B', 'C'][Number(e.key) - 1];
      const btn = document.querySelector('#modal-content button[data-v="' + v + '"], #modal-content button[data-rv="' + v + '"]');
      if (btn) { e.preventDefault(); btn.click(); }
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
      // 手修弹窗里画布可见时，Ctrl+Z 撤笔迹，而不是撤积木
      const cv = $('#rp-inp-canvas');
      if (!e.shiftKey && cv && cv.width && cv.getBoundingClientRect().width > 0) {
        e.preventDefault();
        rpUndo();
        return;
      }
      e.preventDefault();
      if (e.shiftKey) redo(); else undo();
      return;
    }
    if ((e.key === 'Delete' || e.key === 'Backspace') && S.selChip && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) {
      const lane = S.selChip.lane === 'positive' ? 'positive' : 'negative';
      const arr = lane === 'positive' ? S.pos : S.neg;
      const i = arr.findIndex(b => b.id === S.selChip.id);
      if (i >= 0) {
        e.preventDefault();
        pushHistory();
        arr.splice(i, 1);
        S.selChip = null;
        renderLanes(); expandPreview();
        toast('已删除选中的积木');
      }
    }
  });
}

boot().then(async () => {
  bindUI();
  const tabParam = new URLSearchParams(location.search).get('tab');
  if (tabParam) {
    const tabBtn2 = document.querySelector('#tabs button[data-tab="' + tabParam + '"]');
    if (tabBtn2) tabBtn2.click();
  }
  if (location.search.includes('demo') && S.templates && S.templates.length) {
    applyTemplate(S.templates[0]);
    try {
      const g = await api('/api/gallery?dir=station_out&limit=1');
      if (g.items.length) showResult(g.items[0].path, 0, 0);
    } catch (e) {}
  }
  const bd = location.search.includes('batchdemo');
  if (bd) {
    setTimeout(async () => {
      if (!S.lastExpanded || !S.lastExpanded.positive) await expandPreview();
      openBatch();
    }, 900);
  }
  if (location.search.includes('lib=collapsed')) setLibCollapsed(true);
  if (location.search.includes('scrollrp')) {
    setTimeout(() => { window.scrollTo(0, document.body.scrollHeight); }, 1600);
  }
  const rpi = location.search.match(/rpimg=([^&]+)/);
  if (rpi) {
    setTimeout(() => {
      const p = decodeURIComponent(rpi[1]);
      const ref = $('#rp-ref'); if (ref) ref.value = p;
      const tab = document.querySelector('#tabs button[data-tab="repro"]'); if (tab) tab.click();
      rpLoadImage();
      setTimeout(() => {
        if (location.search.includes('rpbrush')) {
          const cv = $('#rp-inp-canvas');
          if (cv) {
            const im2 = $('#rp-inp-img');
            if ((!cv.width || cv.width < 10) && im2 && im2.naturalWidth) {
              cv.width = im2.naturalWidth; cv.height = im2.naturalHeight;
            }
            const ctx = cv.getContext('2d');
            const W = cv.width, H = cv.height;
            ctx.save();
            ctx.fillStyle = '#ff2d55';
            ctx.beginPath();
            ctx.ellipse(W * 0.5, H * 0.36, W * 0.09, H * 0.06, 0, 0, Math.PI * 2);
            ctx.fill();
            ctx.beginPath();
            ctx.ellipse(W * 0.56, H * 0.44, W * 0.06, H * 0.05, 0, 0, Math.PI * 2);
            ctx.fill();
            ctx.restore();
            RP.ink = true;
            const btn = $('#rp-inp-go'); if (btn) btn.disabled = false;
            const ro = $('#rp-inp-readout'); if (ro) ro.textContent = '蒙版已画（示例）';
          }
        }
        const bx = location.search.match(/rpbox=([0-9,]+)/);
        if (!bx) return;
        const b = bx[1].split(',').map(Number);
        const img = $('#rp-inp-img'), sel = $('#rp-inp-sel');
        if (!img || !sel || b.length !== 4) return;
        const r = img.getBoundingClientRect();
        const kx = r.width / (img.naturalWidth || 1), ky = r.height / (img.naturalHeight || 1);
        sel.style.display = 'block';
        sel.style.left = (b[0] * kx) + 'px'; sel.style.top = (b[1] * ky) + 'px';
        sel.style.width = (b[2] * kx) + 'px'; sel.style.height = (b[3] * ky) + 'px';
        rpReadBox();
      }, 700);
    }, 900);
  }
  const rq = location.search.match(/rc=([^&]+)/);
  if (rq) { setTimeout(() => openRecipe(decodeURIComponent(rq[1]), true), 900); }
  const jq = location.search.match(/jump=([a-z]+)/);
  if (jq) setTimeout(() => {
    const key = jq[1];
    if (S.collapsedCats && S.collapsedCats[key]) {
      S.collapsedCats[key] = false;
      saveJSON('loom.collapsedCats', S.collapsedCats);
      renderPalette();
    }
    scrollPalTo(key);
    $$('.rail-item').forEach(b => b.classList.toggle('active', b.dataset.jump === key));
  }, 900);
  const cq = location.search.match(/cmd=([^&]*)/);
  if (cq) { setTimeout(() => openCmd(decodeURIComponent(cq[1] || '')), 700); }
  const zd = location.search.match(/zoomdemo=([^&]+)/);
  if (zd) { setTimeout(() => openImage(decodeURIComponent(zd[1])), 700); }
  const hfd = location.search.match(/handfixdemo=([^&]+)/);
  if (hfd) { setTimeout(() => openHandfix(decodeURIComponent(hfd[1])), 600); }
  const ha = location.search.match(/handauto=([^&]+)/);
  if (ha) { setTimeout(() => { openHandfix(decodeURIComponent(ha[1])); setTimeout(autoDetectHand, 900); }, 600); }
  const hc = location.search.match(/hoverchip=([@A-Za-z0-9_]+)/);
  if (hc) {
    setTimeout(() => {
      const el = document.querySelector('#lane-positive .chip[data-token="' + hc[1] + '"]');
      if (el) { const r = el.getBoundingClientRect(); showTip({ clientX: r.left + r.width / 2, clientY: r.bottom }, hc[1]); }
    }, 800);
  }
  const hv = location.search.match(/hover=([@A-Za-z0-9_]+)/);
  if (hv) {
    const t = hv[1];
    const el = document.querySelector('[data-token="' + t + '"]');
    if (el) { const r = el.getBoundingClientRect(); showTip({ clientX: r.right, clientY: r.top + 10 }, t); }
  }
  const m = location.search.match(/tab=(\w+)/);
  if (m) { const btn = document.querySelector('#tabs button[data-tab="' + m[1] + '"]'); if (btn) btn.click(); }
  if (!location.search.includes('nocheck')) pipelineCheck(true);
  try {
    const rel = await api('/api/reliability');
    S.rel = rel.items || {};
    const x = (S.pos.concat(S.neg)).filter(b => b.token && S.rel[b.token] === 'X').length;
    if (x) renderLanes();
  } catch (e) {}
  S.fav = loadJSON('loom.fav', []);
  renderPalette();
  const gk0 = Object.keys(S.garments || {})[0]; if (gk0) loadGarment(gk0); else newGarment();
  loadRecipes();
  expandPreview();
  setInterval(async () => {
    try {
      const q = await api('/api/bootstrap');
      S.comfy = q.comfy || S.comfy;
      $('#pill-comfy').textContent = q.comfy.up ? ('ComfyUI ' + q.comfy.version) : 'ComfyUI 未启动';
      $('#pill-comfy').className = 'pill ' + (q.comfy.up ? 'ok' : 'bad');
      const n = q.queue.running + q.queue.pending;
      $('#pill-queue').textContent = '队列 ' + n;
      $('#pill-queue').className = 'pill' + (n > 0 ? ' run' : '');
    } catch (e) {}
  }, 15000);
});

function tplLine(b) {
  const name = b.token || '';
  const txt = b.text ? (name ? ' ' : '') + b.text : '';
  const w = (b.weight && Math.abs(b.weight - 1) > 0.001) ? '  ×' + b.weight : '';
  return (name || txt) + w;
}

function tplEditorHtml() {
  const row = (b, i) => {
    const cat = b.token ? tokenCat(b.token) : 'custom';
    const label = b.token || b.text || '';
    return '<div class="tpl-row2" data-i="' + i + '">' +
      '<span class="chip tpl-chip" data-cat="' + cat + '" title="' + esc(tplLine(b) + (S.notes[b.token] ? ' · ' + S.notes[b.token] : '')) + '">' +
      '<span class="nm">' + esc(label) + '</span></span>' +
      '<input class="tpl-w" type="number" step="0.05" min="0.1" max="2" value="' + (b.weight || 1) + '">' +
      '<button class="tpl-del bx" data-i="' + i + '">×</button></div>';
  };
  const col = (title, arr, key) =>
    '<div class="tpl-col"><h4>' + title + ' <span class="hint">' + arr.length + ' 块</span></h4>' +
    '<div class="tpl-list" id="tpl-' + key + '-list">' +
    (arr.length ? arr.map(row).join('') : '<div class="hint" style="padding:8px">（空）</div>') +
    '</div></div>';
  return '<div class="tpl-editor">' + col('正向', S.pos, 'pos') + col('负向', S.neg, 'neg') + '</div>' +
    '<div class="tpl-params">' +
    '<label>尺寸 <input id="tpl-size" value="' + ($('#p-size').value || '1024x1536') + '" style="width:120px"></label>' +
    '<label>步数 <input id="tpl-steps" type="number" value="' + ($('#p-steps').value || 28) + '" style="width:70px"></label>' +
    '<label>CFG <input id="tpl-cfg" type="number" step="0.1" value="' + ($('#p-cfg').value || 5.5) + '" style="width:70px"></label>' +
    '</div>';
}

async function saveCurrentAsTemplate() {
  if (!S.pos.length && !S.neg.length) { alert('先把积木摆好，再创造模板'); return; }
  openModal('创造模板',
    '<div class="field"><label>模板名</label><input id="tpl-name" placeholder="例如：夜雨·伞"></div>' +
    tplEditorHtml() +
    '<div class="hint" style="margin:6px 0 10px">权重与删除只影响这次保存，不改画布</div>' +
    '<div class="row2"><button class="ghost" id="tpl-cancel">取消</button>' +
    '<button class="primary" id="tpl-ok">确认创建</button></div>');
  const modal = $('#modal-content') || document;
  modal.querySelector('.modal-body') || null;
  const bindCol = (key, arr) => {
    $$('#tpl-' + key + '-list .tpl-row2').forEach(row => {
      const i = Number(row.dataset.i);
      row.querySelector('.tpl-w').onchange = e => {
        const v = Math.max(0.1, Math.min(2, Number(e.target.value) || 1));
        arr[i].weight = v;
      };
      row.querySelector('.tpl-del').onclick = () => {
        arr.splice(i, 1);
        openTplEditorRefresh();
      };
    });
  };
  bindCol('pos', S.pos);
  bindCol('neg', S.neg);
  $('#tpl-cancel').onclick = closeModal;
  $('#tpl-ok').onclick = async () => {
    const name = ($('#tpl-name').value || '').trim();
    if (!name) { alert('模板名不能空'); return; }
    const pick = b => ({ token: b.token || '', text: b.text || '', weight: b.weight || 1 });
    const params = { size: $('#tpl-size').value, steps: Number($('#tpl-steps').value || 28),
                     cfg: Number($('#tpl-cfg').value || 5.5) };
    try {
      const r = await api('/api/template/save', { method: 'POST', body: JSON.stringify({
        name, params, positive: S.pos.map(pick), negative: S.neg.map(pick) }) });
      S.templates = r.items || [];
      await loadTemplates();
      closeModal();
      toast('已保存模板：' + name);
    } catch (e) { alert('保存模板失败：' + e.message); }
  };

  function openTplEditorRefresh() {
    const nameEl = $('#tpl-name');
    const keep = nameEl ? nameEl.value : '';
    openModal('创造模板',
      '<div class="field"><label>模板名</label><input id="tpl-name" value="' + esc(keep) + '" placeholder="例如：夜雨·伞"></div>' +
      tplEditorHtml() +
      '<div class="hint" style="margin:6px 0 10px">权重与删除只影响这次保存，不改画布</div>' +
      '<div class="row2"><button class="ghost" id="tpl-cancel">取消</button>' +
      '<button class="primary" id="tpl-ok">确认创建</button></div>');
    bindCol('pos', S.pos);
    bindCol('neg', S.neg);
    $('#tpl-cancel').onclick = closeModal;
    $('#tpl-ok').onclick = async () => {
      const nm = ($('#tpl-name').value || '').trim();
      if (!nm) { alert('模板名不能空'); return; }
      const pick = b => ({ token: b.token || '', text: b.text || '', weight: b.weight || 1 });
      const params = { size: $('#tpl-size').value, steps: Number($('#tpl-steps').value || 28),
                       cfg: Number($('#tpl-cfg').value || 5.5) };
      try {
        const r = await api('/api/template/save', { method: 'POST', body: JSON.stringify({
          name: nm, params, positive: S.pos.map(pick), negative: S.neg.map(pick) }) });
        S.templates = r.items || [];
        await loadTemplates();
        closeModal();
        toast('已保存模板：' + nm);
      } catch (e) { alert('保存模板失败：' + e.message); }
    };
  }
}

(function bindParamPersistence() {
  const wrap = renderLoras;
  renderLoras = function () { wrap(); persistParams(); };
  ['#p-size', '#p-steps', '#p-cfg', '#p-seed', '#p-prefix', '#p-mode'].forEach(sel => {
    const el = $(sel);
    if (el) el.addEventListener('change', persistParams);
  });
})();

/* ---------- character cards ---------- */
async function loadCards() {
  try {
    const r = await api('/api/cards');
    S.cards = r.items || [];
  } catch (e) { S.cards = []; }
  const sel = $('#card-sel');
  if (!sel) return;
  sel.innerHTML = (S.cards.length
    ? S.cards.map(c => '<option>' + esc(c.name) + '</option>').join('')
    : '<option value="">（还没有角色卡）</option>');
}

function cardApply() {
  const sel = $('#card-sel');
  const c = (S.cards || []).find(x => x.name === (sel && sel.value));
  if (!c) { toast('先保存一张角色卡'); return; }
  S.loras = (c.loras || []).map(l => ({ name: l.name, weight: Number(l.weight) || 0.5 }));
  (c.loras || []).forEach(l => { if (!S.loraFiles.includes(l.name)) S.loraFiles.push(l.name); });
  renderLoras();
  (c.tokens || []).forEach(tok => {
    if (!S.pos.some(b => b.token === tok)) {
      S.pos.push({ id: uid(), token: tok, text: '', weight: 1, enabled: true });
    }
  });
  renderLanes(); expandPreview();
  toast('已应用角色卡：' + c.name);
}

async function cardSave() {
  const name = prompt('角色卡名字');
  if (!name) return;
  const keep = ['id', 'body', 'face', 'hair', 'custom'];
  const tokens = [...new Set(S.pos.filter(b => b.token && keep.includes(tokenCat(b.token)))
    .map(b => b.token))];
  const loras = (S.loras || []).map(l => ({ name: l.name, weight: l.weight }));
  const r = await api('/api/card/save', { method: 'POST',
    body: JSON.stringify({ name: name.trim(), loras, tokens }) });
  S.cards = r.items || [];
  await loadCards();
  toast('已保存角色卡：' + name + '（' + loras.length + ' LoRA / ' + tokens.length + ' 标签）');
}

async function cardDelete() {
  const name = ($('#card-sel') || {}).value;
  if (!name) return;
  if (!confirm('删除角色卡 ' + name + '？')) return;
  const r = await api('/api/card/delete', { method: 'POST', body: JSON.stringify({ name }) });
  S.cards = r.items || [];
  await loadCards();
  toast('已删除');
}

(async function bindCards() {
  await new Promise(r => setTimeout(r, 400));
  await loadCards();
  const bind = (sel, fn) => { const el = $(sel); if (el) el.onclick = fn; };
  bind('#card-apply', cardApply);
  bind('#card-save', cardSave);
  bind('#card-del', cardDelete);
  bind('#card-export', () => { window.location = '/api/cards/export'; });
  bind('#card-import', async () => {
    const txt = prompt('粘贴角色卡 JSON（或填本地路径）');
    if (!txt) return;
    const isPath = txt.length < 300 && !txt.trim().startsWith('{');
    try {
      const r = await api('/api/cards/import', { method: 'POST',
        body: JSON.stringify(isPath ? { path: txt.trim() } : { data: txt }) });
      S.cards = r.items || [];
      await loadCards();
      toast('导入完成，新增 ' + r.added + ' 张');
    } catch (e) { alert('导入失败：' + e.message); }
  });
})();
