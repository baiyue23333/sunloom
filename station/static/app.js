
'use strict';
window.onerror = (m, s, l, c, e) => { document.title = 'ERR: ' + m + ' @' + l; };
window.addEventListener('unhandledrejection', e => { document.title = 'REJ: ' + (e.reason && e.reason.message || e.reason); });
const S = {
  tokens: {}, garments: {}, presets: [], aliases: {},
  pos: [], neg: [],
  loras: [], compfy: {}, datasets: [], loraFiles: [],
  jobTimer: null, last: null, gallery: [], sel: null,
  hist: [], hi: -1, fav: [], rel: {}, selChip: null, gallerySel: {}, compareSel: [],
  tokenFilter: '', paletteFilter: '', libraryFilter: '',
  gender: 'f',   // 积木性别：f=女（默认）/ m=男
};

// 身份积木：@ID / @ID_F / @ID_F_SOFT / @ID_MALE… 与 @SINGLE / @SINGLE_M 都算
const isIdentityToken = t => /^@(ID|SINGLE)(_|$)/.test(String(t || ''));
function resolveToken(name) {
  let cur = String(name || '');
  for (let i = 0; i < 3 && S.aliases && S.aliases[cur]; i++) cur = S.aliases[cur];
  return cur;
}
// 积木归属与性别（数据在 ref/prompt_lib.json 的 meta.gender / meta.owner）
function tokenGender(name) {
  const g = ((S.tokenMeta || {}).gender || {})[name];
  if (g) return g;
  // 服装派生的 @OUT_<KEY> / @NEG_<KEY> 没有单独条目，性别跟着服装走
  const m = /^@(?:OUT|NEG)_(.+)$/.exec(String(name || ''));
  if (m) {
    const gar = (S.garments || {})[m[1].toLowerCase()];
    if (gar) return gar.gender || 'f';
  }
  return '';
}
function tokenOwner(name) { return ((S.tokenMeta || {}).owner || {})[name] || ''; }
function currentCardName() { return (($('#card-sel') || {}).value) || ''; }
// 积木库的单一可见性入口：性别不符或属于别的角色卡 → 不可见
function tokenVisible(name) {
  const g = tokenGender(name);
  if (S.gender === 'm' ? g === 'f' : g === 'm') return false;
  const own = tokenOwner(name);
  return !own || own === currentCardName();
}

const CAT_LABEL = {
  set_small:'场景·小', set_medium:'场景·中', set_large:'场景·大', acc:'发饰',
  id:'身份', body:'体型', pose:'姿势', face:'脸型', mood:'情绪', gaze:'视线', hand:'手部',
  hold:'手持物', weapon:'武器', hair:'头发',
  cam:'机位', light:'打光', atmo:'氛围', time:'时间',
  outfit:'服装', fabric:'材质', drape:'型态',
  set:'场景', prop:'道具', comp:'构图', style:'风格',
  neg:'负向', custom:'自定义', nsfw:'NSFW'
};




/* ---------- 分类推断 ---------- */
const RAIL_SHORT = { nsfw: '18+' };

const NSFW_TOKENS = new Set(['@MOOD_SMOKE','@MOOD_ALCOHOL','@MOOD_TIRED','@MOOD_COLD','@STYLE_NOIR','@STYLE_GRAIN','@MAKEUP_SICK','@NEG_NSFW']);


/* ---------- 场景尺度分类（小 / 中 / 大） ---------- */
const SET_SCALE_MAP = (() => {
  const m = {};
  const add = (arr, tag) => arr.forEach(t => { m[t] = tag; });
  add(["@SET_BOOKSTORE","@SET_PIANO","@SET_LAUNDRY","@SET_KITCHEN","@SET_BATHROOM","@SET_BEDROOM","@SET_LIBRARY","@SET_CAFE","@SET_ARTROOM","@SET_ELEVATOR","@SET_BALCONY","@SET_FLOWER_SHOP","@SET_PARKING","@SET_ALLEY"], 'set_small');
  add(["@SET_GREENHOUSE","@SET_CORRIDOR","@SET_CLASSROOM","@SET_SHRINE","@SET_TRAM","@SET_SUBWAY","@SET_ARCADE","@SET_MARKET","@SET_ONSEN","@SET_SCHOOL_GATE","@SET_ROOFTOP","@SET_ROOFTOP_GARDEN","@SET_PARK","@SET_RIVERBANK","@SET_CONSTRUCTION","@SET_CITY_STREET","@SET_GARDEN_PEONY"], 'set_medium');
  add(["@SET_STATION","@SET_AIRPORT","@SET_MUSEUM","@SET_CASTLE","@SET_TEMPLE","@SET_FOREST","@SET_BEACH","@SET_SNOWFIELD","@SET_RUINS","@SET_DESERT","@SET_HARBOR","@SET_MALL","@SET_SCHOOLYARD","@SET_AQUARIUM","@SET_THEATER","@SET_FESTIVAL","@SET_BRIDGE","@SET_GYM","@SET_CAFETERIA","@SET_LIBRARY_HALL","@SET_OFFICE","@SET_HOTEL_LOBBY","@SET_STATION_HALL","@SET_STADIUM","@SET_CITY_BLOCK","@SET_CITY_SKYLINE","@SET_JUNGLE_POOL"], 'set_large');
  return m;
})();

const ACC_SET = ['@PIN', '@CLIP', '@HAIRPIN', '@BERET', '@MINI', '@HEADBAND', '@RIBBON', '@FLOWER_CROWN', '@ACC'];

function tokenCat(name) {
  const up = name.toUpperCase();
  if (ACC_SET.some(p => up.startsWith(p))) return 'acc';
  const n = name.toUpperCase();
  const tax = S.taxonomy || {};
  const nsfwList = Array.isArray(tax.nsfw_tokens) ? tax.nsfw_tokens : null;
  if (nsfwList ? nsfwList.includes(n) : NSFW_TOKENS.has(n)) return 'nsfw';
  const map = Array.isArray(tax.prefix_rules) && tax.prefix_rules.length ? tax.prefix_rules : [
    ['@NEG', 'neg'], ['@DRAPE', 'drape'], ['@OUT', 'outfit'], ['@MOOD', 'mood'], ['@POSE', 'pose'],
    ['@HOLD', 'hold'], ['@WEAPON', 'weapon'],
    ['@GAZE', 'gaze'], ['@HAND', 'hand'], ['@HAIR', 'hair'], ['@FAB', 'fabric'],
    ['@ATMO', 'atmo'], ['@TIME', 'time'], ['@SET', 'set'], ['@PROP', 'prop'],
    ['@COMP', 'comp'], ['@STYLE', 'style'], ['@CAM', 'cam'], ['@LIGHT', 'light'],
    ['@OBJ', 'prop'], ['@INSTR', 'prop'], ['@RIDE', 'prop'], ['@ROLE', 'prop'], ['@STRIP', 'neg'],
    ['@WEATHER', 'atmo'], ['@SEASON', 'time'],
    ['@BODY', 'body'], ['@FACE', 'face'], ['@HAIR', 'hair'], ['@MAKEUP', 'face'],
    ['@PIN', 'hair'], ['@CLIP', 'hair'], ['@BERET', 'hair'], ['@MINI_TOPHAT', 'hair'], ['@HEADBAND', 'hair'], ['@RIBBON', 'hair'], ['@FLOWER_CROWN', 'hair'],
    ['@HAIRPIN', 'hair'], ['@MINI', 'hair'], ['@FX', 'style'], ['@CROP', 'comp'], ['@BARE', 'body'], ['@SKIN', 'face'],
    ['@BG', 'comp'], ['@HOSE', 'outfit'], ['@ID', 'id'],
  ];
  for (const [pre, cat] of map) if (n.startsWith(pre)) return cat;
  if (n === '@ID_F' || n === '@SINGLE' || n === '@SINGLE_M') return 'id';
  return 'custom';
}


/* ---------- 画师 LoRA 悬停预览 ---------- */
function bindArtistHover(sel, kind) {
  if (!sel) sel = $('#style-lora');
  kind = kind || (sel && sel.id === 'coop-slora' ? 'env' : 'char');
  if (!sel || sel.dataset.hoverBound) return;
  sel.dataset.hoverBound = '1';
  let card = null, timer = null, seq = 0, hovered = false;
  const hide = () => { clearTimeout(timer); if (card) { card.remove(); card = null; } };
  const show = async (name) => {
    hide();
    if (!name) return;
    const my = ++seq;
    let k = kind === 'auto' ? 'char' : kind;
    if (kind !== 'env') {
      try { if (typeof isEnvLora === 'function' && isEnvLora(name)) k = 'env'; } catch (e) {}
    }
    let data;
    try { data = await api('/api/artist_preview?kind=' + k + '&name=' + encodeURIComponent(name)); } catch (e) { return; }
    if (my !== seq || !hovered) return;
    const r = sel.getBoundingClientRect();
    card = document.createElement('div');
    card.className = 'artist-hover ' + k;
    const title = '<div class="ah-title">' + esc((typeof shortLoraName === 'function' ? shortLoraName(name) : name)) +
      '<span class="ah-kind">' + (k === 'env' ? '环境画师' : '人物画师') + '</span></div>';
    const items = (data.items || []).slice(0, 3);
    const hasRef = !!(data.ref && !items.some(it => it.path === data.ref));
    const refCard = hasRef
      ? ('<figure class="ah-item ah-ref-card"><img src="/api/img?path=' + encodeURIComponent(data.ref) + '&t=' + (data.ref_mtime || '') + '"><figcaption>参考图</figcaption></figure>')
      : '';
    const thumbs = items.map(it =>
      '<figure class="ah-item"><img src="/api/img?path=' + encodeURIComponent(it.path) + '&t=' + (it.mtime || '') + '"><figcaption>' +
      it.weight.toFixed(2).replace(/0$/, '') + '</figcaption></figure>').join('');
    const adv = (data.advice || []).map(a => '<li><b>' + a.weight.toFixed(1) + '</b> ' + esc(a.text) + '</li>').join('');
    card.innerHTML = title +
      ((refCard || thumbs) ? '<div class="ah-thumbs' + (hasRef ? ' has-ref' : '') + '">' + refCard + thumbs + '</div>' : '<div class="ah-empty">样张生成中，稍后悬停再看</div>') +
      '<ul class="ah-advice">' + adv + '</ul>';
    document.body.appendChild(card);
    const clamp = () => {
      if (!card) return;
      const w = card.offsetWidth, h = card.offsetHeight;
      let left = r.left - w - 12;
      if (left < 8) left = Math.min(r.right + 12, window.innerWidth - w - 8);
      let top = r.top - 8;
      if (top + h > window.innerHeight - 8) top = Math.max(8, window.innerHeight - h - 8);
      card.style.left = Math.max(8, left) + 'px';
      card.style.top = top + 'px';
    };
    clamp();
    requestAnimationFrame(clamp);
    card.querySelectorAll('img').forEach(img => { img.addEventListener('load', clamp); });
  };
  sel.addEventListener('mouseenter', () => { hovered = true; clearTimeout(timer); timer = setTimeout(() => show(sel.value), 350); });
  sel.addEventListener('mouseleave', () => { hovered = false; hide(); });
  sel.addEventListener('change', () => { if (hovered) show(sel.value); else hide(); });
  window.addEventListener('scroll', hide, true);
}

function bindAllArtistHovers() {
  try { bindArtistHover($('#style-lora'), 'char'); } catch (e) {}
  try { bindArtistHover(document.querySelector('#coop-slora-row #coop-slora'), 'env'); } catch (e) {}
}

/* ---------- 初始化 ---------- */
// 当前 LoRA 组合里有没有画师 LoRA。
function isRealArtistLora(name) {
  try {
    if (!name) return false;
    return typeof loraCat === 'function' && loraCat(name) === '画师';
  } catch (e) { return false; }
}

function hasArtistLoraIn(list) {
  try {
    return (list || []).some(l => l && isRealArtistLora(l.name));
  } catch (e) { return false; }
}

function persistParams() {
  try {
    // 有画师时留一份"上次好用的组合"，供下次加载时兜底恢复
    if (hasArtistLoraIn(S.loras)) {
      try { localStorage.setItem('loom.loras.lastGood', JSON.stringify(S.loras)); } catch (e) {}
    }
    localStorage.setItem('loom.params', JSON.stringify({
      model: ($('#p-model') || {}).value || '',
      refine: ($('#p-refine') || {}).value || '0',
      size: ($('#p-size') || {}).value,
      sizeWH: ($('#p-size') || {}).value === 'custom' ? [($('#p-w') || {}).value, ($('#p-h') || {}).value] : null,
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

const TIPS_HTML = [
    '<h4 class="rc-h">出图基本盘</h4>',
    '<p class="hint">1024×1024，26–30 步，CFG 5.5；重映一次约 2 分 50 秒（出板 + 头发精修 + 超分）。</p>',
    '<h4 class="rc-h">身份与角色卡</h4>',
    '<p class="hint">角色卡决定身份 / 体型 / 服装；卡分女 / 男，先切积木库性别再应用。</p>',
    '<h4 class="rc-h">画师 LoRA</h4>',
    '<p class="hint">只显示当前底模可用的：anima 底模下看不到 MOSS / Krea2 等其他架构。人物画师与角色 LoRA 分开。</p>',
    '<h4 class="rc-h">一键修正</h4>',
    '<p class="hint">按规则检查多机位、性别冲突、背影配正面光、正负串道；结果可勾选「移除 / 替换」，只改积木不改画面。</p>',
    '<h4 class="rc-h">分类光引导</h4>',
    '<p class="hint">工具栏「引导」选自由 / 人像 / 场景 / 剧情；亮的分类表示还缺，悬停可看建议积木。</p>',
    '<h4 class="rc-h">出问题先查</h4>',
    '<p class="hint">① 步数 <26 会发灰；② 场景图别同时挂 @STYLE_；③ LoRA 底模是否匹配；④ 背影别留眼睛词。</p>',
    '<p class="hint">完整版见 产出作品/工作站提示卡.md 与 工作站说明.md</p>'
  ].join('');

function fillModelSelect() {
  const sel = $('#p-model');
  if (!sel) return;
  let savedModel = '';
  try { savedModel = (JSON.parse(localStorage.getItem('loom.params') || '{}').model) || ''; } catch (e) {}
  const all = S.models && S.models.length ? S.models : ['anima-base-v1.0.safetensors'];
  const animaList = (typeof modelBase === 'function') ? all.filter(f => modelBase(f) === 'anima') : all;
  const list = animaList.length ? animaList : all;
  const rawCur = (S.model || savedModel || 'anima-base-v1.0.safetensors');
  const cur = list.includes(rawCur) ? rawCur : list[0];
  S.model = cur;
  sel.innerHTML = list.map(f => '<option' + (f === cur ? ' selected' : '') + '>' + f + '</option>').join('');
  sel.value = cur;
  sel.onchange = () => {
    S.model = sel.value;
    const want = (typeof modelBase === 'function') ? modelBase(sel.value) : 'anima';
    S.loras = (S.loras || []).filter(l => !loraBase(l.name) || loraBase(l.name) === want);
    if (typeof renderLoras === 'function') renderLoras();
    if (typeof renderStyleLoraOptions === 'function') renderStyleLoraOptions();
    if (typeof coopFillLoras === 'function') { try { coopFillLoras(); } catch (e) {} }
    const label = { anima: 'anima', other_xl: '其他', moss: 'MOSS', krea2: 'Krea2' }[want] || want;
    toast('已切到 ' + label + '：LoRA 列表只显示该底模可用的');
  };
}

function bindSubgroupEditor() {
  const cat = $('#tk-cat');
  const sel = $('#tk-sub-sel');
  if (!cat || !sel) return;
  cat.onchange = () => buildSubOptions(cat.value, '__auto__');
  sel.onchange = toggleSubNew;
  buildSubOptions(cat.value, '__auto__');
}

async function boot() {
  const b = await api('/api/bootstrap');
  S.tokens = b.tokens; S.notes = b.notes || {}; S.loraMeta = b.lora_meta || {}; S.tokenMeta = b.token_meta || {}; S.aliases = b.aliases || {}; S.taxonomy = b.taxonomy || {}; S.garments = b.garments; S.comfy = b.comfy;
  S.datasets = b.datasets; S.loraFiles = b.loras; S.models = b.models || []; S.altModels = b.alt_models || []; S.loraRoles = b.lora_roles || {}; S.envExclude = b.env_exclude || [];
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
      if ($('#p-refine')) $('#p-refine').value = sp.refine || '0';
      if (sp.sizeWH && $('#p-w') && $('#p-h')) { $('#p-w').value = sp.sizeWH[0]; $('#p-h').value = sp.sizeWH[1]; }
      if (sp.size && $('#p-size')) $('#p-size').value = sp.size;
      if (sp.steps) $('#p-steps').value = sp.steps;
      if (sp.cfg) $('#p-cfg').value = sp.cfg;
      if (sp.seed !== undefined && $('#p-seed')) $('#p-seed').value = sp.seed;
      if (sp.prefix && $('#p-prefix')) $('#p-prefix').value = sp.prefix;
      if (sp.mode && $('#p-mode')) $('#p-mode').value = sp.mode;
      if (Array.isArray(sp.loras) && sp.loras.length) S.loras = sp.loras;
    }
    // 一次性把历史保存的 LoRA 权重归一为 1.0（之后仍可手动改，不会被覆盖）
    try {
      if (!localStorage.getItem('loom.loras.allOne.v1') && Array.isArray(S.loras) && S.loras.length) {
        let changed = 0;
        S.loras = S.loras.map(l => {
          if (Number(l.weight) !== 1) { changed++; return { ...l, weight: 1 }; }
          return l;
        });
        localStorage.setItem('loom.loras.allOne.v1', '1');
        if (changed) setTimeout(() => { try { toast('LoRA 权重已统一为 1.0（' + changed + ' 个）'); } catch (e) {} }, 900);
      }
    } catch (e) {}
    // 一次性迁移：底模画师与合作模式人物画师默认留空（之后可手动选）
    try {
      if (!localStorage.getItem('loom.artistDefaultBlank.v1')) {
        S.loras = (S.loras || []).filter(l => loraCat(l.name) !== '画师');
        localStorage.removeItem('loom.styleLora');
        localStorage.removeItem('loom.loras.lastGood');
        const sp = JSON.parse(localStorage.getItem('loom.params') || '{}');
        if (Array.isArray(sp.loras)) {
          sp.loras = sp.loras.filter(l => loraCat(l.name) !== '画师');
          localStorage.setItem('loom.params', JSON.stringify(sp));
        }
        localStorage.setItem('loom.artistDefaultBlank.v1', '1');
      }
    } catch (e) {}
  } catch (e) {}
  renderPalette();
  bindSubgroupEditor(); renderLanes(); renderLoras(); renderParams(); fillModelSelect();
  try {
    if (!localStorage.getItem('loom.refineOffMigrated')) {
      localStorage.setItem('loom.refineOffMigrated', '1');
      const rsel = document.querySelector('#p-refine');
      if (rsel) rsel.value = '0';
      const sp = JSON.parse(localStorage.getItem('loom.params') || '{}');
      sp.refine = '0';
      localStorage.setItem('loom.params', JSON.stringify(sp));
    }
  } catch (e) {}
  const styleSel = document.querySelector('#style-sel');
  const styleInp = document.querySelector('#style-custom');
  if (styleSel) {
    styleSel.onchange = () => {
      if (styleInp) styleInp.style.display = styleSel.value === 'custom' ? '' : 'none';
      if (styleSel.value !== 'custom') applyStyle(styleSel.value);
    };
  }
  if (styleInp) {
    styleInp.onchange = () => { if (styleSel && styleSel.value === 'custom') applyStyle('custom', styleInp.value); };
  }
  restoreStyle();
  const freeBtn = document.querySelector('#artist-free');
  if (freeBtn) freeBtn.onclick = applyArtistFree;
  const slSel = document.querySelector('#style-lora');
  if (slSel) {
    renderStyleLoraOptions();
  bindArtistHover();
    slSel.onchange = () => {
      applyStyleLora(slSel.value);
      const cw = $('#coop-char-w');
      if (cw && !cw.dataset.manual && typeof coopLoraDefaultWeight === 'function') {
        cw.value = coopLoraDefaultWeight(slSel.value, 'char').toFixed(2);
      }
    };
  }
  const tipsOpen = () => openModal('提示卡', TIPS_HTML);
  const tipsBtn = document.querySelector('#btn-tips');
  if (tipsBtn) tipsBtn.onclick = tipsOpen;
  const tipsFab = document.querySelector('#tips-fab');
  if (tipsFab) tipsFab.onclick = tipsOpen;
  const pDataBtn = document.querySelector('#btn-param-data');
  if (pDataBtn) pDataBtn.onclick = () => { if (typeof showLoraDataModal === 'function') showLoraDataModal(); };
  const gm = document.querySelector('#guide-mode');
  if (gm) {
    gm.value = loadJSON('loom.glowMode', 'free') || 'free';
    gm.onchange = () => { saveJSON('loom.glowMode', gm.value); S._glowDone = false; renderGuideGlow(); };
  }
  const sfix = document.querySelector('#btn-smartfix');
  if (sfix) sfix.onclick = fixFlow;
  const randBtn = document.querySelector('#btn-random');
  if (randBtn) randBtn.onclick = () => {
    S._coopRouting = false;
    try { randomCompose(); } finally { S._coopRouting = true; }
    setTimeout(coopAfterGlobalEdit, 0);
  };
  const rsBtn = document.querySelector('#btn-rand-scene');
  if (rsBtn) rsBtn.onclick = () => {
    if (S.coopOn && typeof coopToGlobal === 'function') coopToGlobal();
    S._coopRouting = false;
    try { randomSceneOnly(); } finally { S._coopRouting = true; }
    setTimeout(coopAfterGlobalEdit, 0);
  };
  const roBtn = document.querySelector('#btn-rand-outfit');
  if (roBtn) roBtn.onclick = () => {
    if (S.coopOn && typeof coopToGlobal === 'function') coopToGlobal();
    S._coopRouting = false;
    try { randomOutfitOnly(); } finally { S._coopRouting = true; }
    setTimeout(coopAfterGlobalEdit, 0);
  };
  try { reprojInit(); } catch (e) {}
  await loadPresets();
  await loadTemplates();
  renderGallery();
  fillSelects();
  await loadLibrary();
  renderCombos();
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
function snapState() { return JSON.stringify({ pos: S.pos, neg: S.neg, coop: S.coop || null, coopOn: !!S.coopOn }); }
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
  if (d.coop !== undefined && d.coop) S.coop = d.coop;
  if (S.coopOn && S.coop) { renderCoopLanes(); coopBind(); }
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
function jumpToCategory(cat) {
  const box = document.querySelector('.pal-items[data-items="' + cat + '"]');
  if (!box) return;
  S.collapsedCats = S.collapsedCats || {};
  if (S.collapsedCats[cat]) { S.collapsedCats[cat] = false; renderPalette(); }
  const again = document.querySelector('.pal-items[data-items="' + cat + '"]');
  if (again) again.scrollIntoView({ block: 'center', behavior: 'smooth' });
  const head = document.querySelector('.pal-group[data-cat="' + cat + '"]');
  if (head) { head.classList.add('flash'); setTimeout(() => head.classList.remove('flash'), 900); }
  toast('已跳到分类：' + cat);
}


/* 场景类型（子颜色） */
const SCENE_FAMILY_MAP = (() => {
  const m = {};
  const add = (a, f) => a.forEach(t => { m[t] = f; });
  add(["@SET_BEACH","@SET_HARBOR","@SET_RIVERBANK","@SET_AQUARIUM","@SET_ONSEN","@SET_JUNGLE_POOL"], 'water');
  add(["@SET_CITY_STREET","@SET_CITY_BLOCK","@SET_CITY_SKYLINE","@SET_ALLEY","@SET_MALL","@SET_OFFICE","@SET_HOTEL_LOBBY","@SET_STATION_HALL","@SET_STATION","@SET_AIRPORT","@SET_BRIDGE","@SET_PARKING","@SET_ROOFTOP","@SET_ROOFTOP_GARDEN","@SET_CONSTRUCTION","@SET_MARKET","@SET_FESTIVAL","@SET_SCHOOL_GATE"], 'urban');
  add(["@SET_CLASSROOM","@SET_GYM","@SET_CAFETERIA","@SET_SCHOOLYARD","@SET_LIBRARY","@SET_LIBRARY_HALL","@SET_CORRIDOR","@SET_ARTROOM"], 'school');
  add(["@SET_SHRINE","@SET_TEMPLE","@SET_CASTLE","@SET_THEATER","@SET_MUSEUM","@SET_ONSEN"], 'culture');
  add(["@SET_FOREST","@SET_SNOWFIELD","@SET_DESERT","@SET_GARDEN_PEONY","@SET_PARK","@SET_GREENHOUSE"], 'nature');
  add(["@SET_BOOKSTORE","@SET_PIANO","@SET_LAUNDRY","@SET_KITCHEN","@SET_BATHROOM","@SET_BEDROOM","@SET_CAFE","@SET_FLOWER_SHOP","@SET_BALCONY","@SET_ELEVATOR","@SET_TRAM","@SET_SUBWAY","@SET_ARCADE"], 'indoor');
  return m;
})();
function setFamilyOf(name) { return SCENE_FAMILY_MAP[String(name || '').toUpperCase()] || 'indoor'; }


/* 分类子组（label / color / tokens） */
const SUBGROUP_DEFS = {
  outfit: [
    { label: '默认套装', color: '#d98c72', tokens: [] },
    { label: '日常便服', color: '#7aa2d6', tokens: [] },
    { label: '校园制服', color: '#7fc79a', tokens: [] },
    { label: '正式礼服', color: '#d9b268', tokens: [] },
    { label: '主题造型', color: '#a78bd6', tokens: [] },
    { label: '散件', color: '#6fc2c9', tokens: [] },
  ],
  hair: [
    { label: '长度/轮廓', color: '#7aa2d6', tokens: ['@HAIR_BOB','@HAIR_HIME','@HAIR_WAVY','@HAIR_CURLY','@HAIR_STRAND','@HAIR_TUCKED'] },
    { label: '扎发', color: '#7fc79a', tokens: ['@HAIR_TWINTAIL','@HAIR_PONY_HIGH','@HAIR_PONY_SIDE','@HAIR_BRAID','@HAIR_TWIN_BRAID','@HAIR_BUN','@HAIR_HALF_UP'] },
    { label: '状态', color: '#d9b268', tokens: ['@HAIR_WIND','@HAIR_DAMP','@HAIR_MESSY'] },
  ],
  acc: [
    { label: '发夹/发簪', color: '#d98c72', tokens: ['@PIN_MOON','@PIN_FEATHER','@PIN_HEART','@PIN_CROSS','@HAIRPIN_ROSE','@HAIRPIN_STAR'] },
    { label: '帽子/头饰', color: '#a78bd6', tokens: ['@BERET','@MINI_TOPHAT','@HEADBAND_PEARL','@RIBBON_BOW','@FLOWER_CROWN'] },
    { label: '发夹造型', color: '#6fc2c9', tokens: ['@CLIP_CAT_EAR','@CLIP_BUTTERFLY'] },
  ],
  weapon: [
    { label: '冷兵器', color: '#d98c72', tokens: ['@WEAPON_SWORD','@WEAPON_KATANA','@WEAPON_DAGGER','@WEAPON_SPEAR','@WEAPON_SCYTHE','@WEAPON_CHAIN'] },
    { label: '火器', color: '#7aa2d6', tokens: ['@WEAPON_RIFLE','@WEAPON_PISTOL'] },
    { label: '远程/长柄', color: '#7fc79a', tokens: ['@WEAPON_BOW','@WEAPON_STAFF'] },
    { label: '用法', color: '#d9b268', tokens: ['@WEAPON_GRIP','@WEAPON_SHIELD'] },
  ],
  "cam": [
    { label: "近景", color: "#e08a7a", tokens: ["@CAM_BUST","@CAM_CLOSEUP","@CAM_HIP","@CAM_PROFILE"] },
    { label: "全身/中景", color: "#7aa2d6", tokens: ["@CAM_BACKSIDE","@CAM_FULL","@CAM_MEDIUM","@CAM_REAR","@CAM_THREEQ"] },
    { label: "角度", color: "#a78bd6", tokens: ["@CAM_EYE","@CAM_GROUND","@CAM_HIGH","@CAM_KNEE","@CAM_OVERHEAD","@CAM_POV","@CAM_TOP","@CAM_WORM"] },
    { label: "镜头效果", color: "#6fc2c9", tokens: ["@CAM_DUTCH","@CAM_FISHEYE","@CAM_ORBIT","@CAM_SHOULDER","@CAM_TELE","@CAM_WIDE","@CAM_ZOOMBLUR"] },
    { label: "远景/框景", color: "#d9b268", tokens: ["@CAM_BACK_FAR","@CAM_CORNER","@CAM_DOORWAY","@CAM_ESTABLISH","@CAM_FULL_WIDE","@CAM_HIGH_WIDE","@CAM_LOW_WIDE","@CAM_SIDE_FAR","@CAM_WINDOW"] },
  ],
  "mood": [
    { label: "轻快/正向", color: "#7fc79a", tokens: ["@MOOD_AMUSED","@MOOD_CALM","@MOOD_EXCITED","@MOOD_RELIEVED","@MOOD_SHY","@MOOD_SMUG","@MOOD_TEASING","@MOOD_TENDER"] },
    { label: "低沉/负向", color: "#7aa2d6", tokens: ["@MOOD_ANGRY","@MOOD_COLD","@MOOD_DETACHED","@MOOD_EMBARRASSED","@MOOD_SAD","@MOOD_SLEEPY","@MOOD_TIRED","@MOOD_WISTFUL"] },
    { label: "状态/其它", color: "#d9b268", tokens: ["@MOOD_ALCOHOL","@MOOD_FOCUSED","@MOOD_SMOKE","@MOOD_SURPRISED","@MOOD_THINKING"] },
  ],
  "gaze": [
    { label: "朝向", color: "#a78bd6", tokens: ["@GAZE_ASIDE","@GAZE_CAMERA","@GAZE_DOWN","@GAZE_FAR","@GAZE_UP","@GAZE_WINDOW"] },
    { label: "眼态", color: "#6fc2c9", tokens: ["@GAZE_BLINK","@GAZE_CLOSED"] },
  ],
  "time": [
    { label: "日间", color: "#d9b268", tokens: ["@TIME_AFTERNOON","@TIME_DAWN","@TIME_MORNING","@TIME_NOON"] },
    { label: "黄昏/夜", color: "#7aa2d6", tokens: ["@TIME_BLUE","@TIME_DUSK","@TIME_NIGHT"] },
  ],
  "atmo": [
    { label: "光与尘", color: "#d9b268", tokens: ["@ATMO_BOKEH","@ATMO_DUST","@ATMO_KOMOREKI","@ATMO_PETALS"] },
    { label: "气候/天象", color: "#7aa2d6", tokens: ["@ATMO_FOG","@ATMO_MOON","@ATMO_RAIN"] },
    { label: "人造氛围", color: "#a78bd6", tokens: ["@ATMO_CANDLE","@ATMO_GRID","@ATMO_LAMP","@ATMO_NEON"] },
  ],
  "hand": [
    { label: "手部动作", color: "#d98c72", tokens: ["@HAND_BEHIND","@HAND_BOOK","@HAND_CHIN","@HAND_COLLAR","@HAND_CUFF","@HAND_FOLD","@HAND_HAIR","@HAND_KNEES","@HAND_PEACE","@HAND_POCKET","@HAND_WARM","@HAND_WAVE"] },
  ],
  "light": [
    { label: "自然光", color: "#d9b268", tokens: ["@LIGHT_WIN","@LIGHT_GOLDEN","@LIGHT_SIDE","@LIGHT_SOFT","@LIGHT_SOFT_WARM","@LIGHT_SHEEN"] },
    { label: "人造光", color: "#a78bd6", tokens: ["@LIGHT_NEON","@LIGHT_CANDLE","@LIGHT_STUDIO","@LIGHT_NIGHT","@LIGHT_TOP"] },
    { label: "氛围光", color: "#6fc2c9", tokens: ["@LIGHT_BACK","@LIGHT_RIM","@LIGHT_RAY"] },
  ],
  "pose": [
    { label: "站/靠", color: "#7fc79a", tokens: ["@POSE_ARMS_CROSSED","@POSE_HANDS_POCKETS","@POSE_LEAN","@POSE_LEAN_RAIL","@POSE_STAND"] },
    { label: "坐/卧", color: "#7aa2d6", tokens: ["@POSE_CROSS_LEGS","@POSE_CROUCH","@POSE_CURL","@POSE_KNEEL","@POSE_KNEEL_ONE","@POSE_LIE","@POSE_LIE_BACK","@POSE_LIE_SIDE","@POSE_SIT","@POSE_SIT_FLOOR","@POSE_SIT_SIDE","@POSE_SLEEP_SIT","@POSE_SQUAT"] },
    { label: "文静", color: "#8fa8c8", tokens: ["@POSE_HANDS_FOLDED","@POSE_LAP_HANDS","@POSE_LOOK_DOWN","@POSE_PRAY","@POSE_QUIET_TURN","@POSE_READ_BOOK","@POSE_SCARF_WRAP","@POSE_TEA_CUP","@POSE_WINDOW_GAZE"] },
    { label: "活泼", color: "#f0a05a", tokens: ["@POSE_BALANCE","@POSE_DANCE_STEP","@POSE_HANDS_UP_CHEER","@POSE_HOP","@POSE_JUMP_TWIST","@POSE_KICK","@POSE_PEEK","@POSE_PIGGYBACK_WAVE","@POSE_RUN","@POSE_RUN_TURN","@POSE_SKIP","@POSE_SPIN_SKIRT","@POSE_STRETCH_YAWN","@POSE_TILT_HEAD"] },
    { label: "手部小动作", color: "#d9b268", tokens: ["@POSE_ADJUST_COLLAR","@POSE_BLOW_KISS","@POSE_CHEEK_PEACE","@POSE_CHIN_REST","@POSE_CLAP","@POSE_FINGER_GUN","@POSE_FIST_PUMP","@POSE_HANDS_CLASP","@POSE_HAND_ON_HAIR","@POSE_HEART_HANDS","@POSE_HOLD_HEM","@POSE_PEACE","@POSE_POINT","@POSE_POUT","@POSE_SALUTE","@POSE_THUMBS_UP","@POSE_TOUCH_FACE","@POSE_TUCK_HAIR","@POSE_WAVE","@POSE_WINK_PEACE"] },
    { label: "动作", color: "#d98c72", tokens: ["@POSE_ARCH_BACK","@POSE_BACK","@POSE_BENT_OVER","@POSE_FLOAT","@POSE_JUMP","@POSE_LOOK_BACK","@POSE_LOOK_UP","@POSE_SPIN","@POSE_STRETCH","@POSE_STRETCH_UP","@POSE_TIPTOE","@POSE_WALK"] },
  ],
  "comp": [
    { label: "取景", color: "#7aa2d6", tokens: ["@COMP_FOREGROUND","@COMP_CENTER","@COMP_THIRDS","@COMP_FILL","@COMP_CROP","@COMP_MACRO","@COMP_FRAME"] },
    { label: "线条", color: "#7fc79a", tokens: ["@COMP_LEADING","@COMP_DIAGONAL","@COMP_CURVE","@COMP_TRIANGLE","@COMP_SYMMETRY","@COMP_RHYTHM"] },
    { label: "视角", color: "#a78bd6", tokens: ["@COMP_LOW","@COMP_OVERHEAD","@COMP_OVER_SHOULDER","@COMP_DUTCH","@COMP_HORIZON_LOW","@COMP_HORIZON_HIGH","@COMP_TELE","@COMP_WIDE"] },
    { label: "特技", color: "#6fc2c9", tokens: ["@COMP_MIRROR","@COMP_DOF","@COMP_NEGATIVE","@COMP_GOLDEN","@COMP_MINIMAL","@COMP_LOOKROOM","@COMP_LAYERS","@COMP_REFLECTION","@COMP_SILHOUETTE","@COMP_FRAMEINFRAME","@COMP_GRAPHIC","@COMP_TILTSHIFT","@COMP_VAST","@COMP_STD"] },
  ],
  "prop": [
    { label: "植物/光", color: "#d9b268", tokens: ["@PROP_LANTERN","@PROP_BALLOON"] },
    { label: "文具/艺术", color: "#7fc79a", tokens: ["@PROP_BOOK","@PROP_BRUSH","@PROP_PALETTE","@PROP_CANVAS","@PROP_LETTER"] },
    { label: "生活", color: "#7aa2d6", tokens: ["@PROP_CAMERA","@PROP_VINYL","@PROP_HEADPHONES","@PROP_BLANKET","@PROP_UMBRELLA","@PROP_KEY"] },
    { label: "乐器", color: "#d98c72", tokens: ["@PROP_VIOLIN"] },
  ],
  "style": [
    { label: "绘画", color: "#7fc79a", tokens: ["@STYLE_PAINTERLY","@STYLE_WATERCOLOR","@STYLE_SOFT","@STYLE_FLAT","@STYLE_CEL","@STYLE_LINE","@STYLE_ANIME","@STYLE_PASTEL"] },
    { label: "影像", color: "#7aa2d6", tokens: ["@STYLE_FILM","@STYLE_PHOTO","@STYLE_NOIR","@STYLE_GRAIN"] },
    { label: "特效", color: "#a78bd6", tokens: ["@STYLE_GLITCH","@STYLE_DATAMOSH","@STYLE_SURREAL","@STYLE_CHROMA","@STYLE_WATER"] },
  ],
  "neg": [
    { label: "基础", color: "#d98c72", tokens: ["@NEG_BASE","@NEG_BASE_A","@NEG_BASE_B","@NEG_EXPO","@NEG_ANATOMY","@NEG_AI","@NEG_PERSPECTIVE","@NEG_BLUR","@NEG_OVEREXP","@NEG_SKIN","@NEG_CHILD","@NEG_NSFW"] },
    { label: "服装/细节", color: "#d9b268", tokens: ["@NEG_FABRIC","@NEG_DRAPE_ON","@NEG_DRAPE_OFF","@NEG_HEM","@NEG_SHOES","@NEG_SOCKS","@NEG_THICKHOSE","@NEG_GARMENT","@NEG_COLORBLEED","@NEG_ACC_FACE","@NEG_LONGHAIR","@NEG_CEL","@NEG_REAL","@NEG_HARDCEL"] },
    { label: "布局", color: "#7aa2d6", tokens: ["@NEG_TEXT","@NEG_DOUBLE","@NEG_BGCLUTTER","@NEG_DIORAMA","@NEG_LETTERBOX","@NEG_GLITCHBAND","@NEG_OUTLINE","@NEG_CHIBI"] },
    { label: "手/道具", color: "#7fc79a", tokens: ["@NEG_HANDS","@NEG_CUP","@NEG_BEDSIDE","@NEG_DESK","@NEG_TABLE","@NEG_HAND_ART","@NEG_PROPS"] },
  ],
};
const SUBGROUP_MAP = (() => { const m = {}; for (const [cat,arr] of Object.entries(SUBGROUP_DEFS)) { arr.forEach((g,i) => g.tokens.forEach(t => { m[t] = { cat, idx: i, label: g.label, color: g.color }; })); } return m; })();
function tintAttrs(name) {
  const g = subgroupOf(name);
  return g ? ' data-tint="1" style="--sc:' + g.color + '55"' : '';
}



/* 服装子分组（2026-11-08） */
const OUTFIT_FAMILY = {
  '日常便服': ['casual_knit','hoodie_casual','denim_set','cardigan_set','overalls','loungewear','sundress','sundress_floral','pajama','initial_fine_lite'],
  '校园制服': ['school','school_bare','sailor_winter','gym','lab_coat','smock'],
  '正式礼服': ['gala','initial_fine','initial_fine_gala','cheongsam','hanfu','suit','idol'],
  '主题造型': ['maid','santa','swimsuit','yukata','yukata_bare','raincoat','winter'],
  '默认套装': ['initial'],
  '散件': ['tights']
};
const OUTFIT_FAMILY_COLOR = {
  '日常便服': '#7aa2d6', '校园制服': '#7fc79a', '正式礼服': '#d9b268',
  '主题造型': '#a78bd6', '默认套装': '#d98c72', '散件': '#6fc2c9'
};
function outfitFamilyOf(name) {
  const k = String(name || '').toUpperCase();
  if (/^@HOSE_/.test(k) || /^@OUT_(TIGHTS|SOCKS)/.test(k)) return '散件';
  if (/^@OUTFIT/.test(k) || k === '@OUT_CASUAL_KNIT') return '默认套装';
  const key = k.replace(/^@OUT_/, '').toLowerCase();
  for (const [fam, keys] of Object.entries(OUTFIT_FAMILY)) if (keys.includes(key)) return fam;
  return '散件';
}

const SUBGROUP_PREFIX_RULES = {
  neg: [
    [/^@NEG_(BASE|EXPO|ANATOMY|AI|PERSPECTIVE|BLUR|OVEREXP|SKIN|CHILD|NSFW)/, '基础'],
    [/^@NEG_(TEXT|DOUBLE|BGCLUTTER|DIORAMA|LETTERBOX|GLITCHBAND|OUTLINE|CHIBI)/, '布局'],
    [/^@NEG_(HANDS|CUP|BEDSIDE|DESK|TABLE|HAND_ART|PROPS)/, '手/道具']
  ]
};

function subgroupOf(name) {
  const key = String(name || '').toUpperCase();
  // 只有编辑器写入的 {label,color} 才算自定义子分组；
  // classify_blocks.py 写的是分类字符串（"hair"/"body"），不能当 label 用，否则标题渲染成 undefined
  const custom = (S.tokenMeta && S.tokenMeta.subgroups) ? S.tokenMeta.subgroups[key] : null;
  if (custom && typeof custom === 'object' && custom.label) {
    return { cat: tokenCat(key), idx: 90, label: custom.label, color: custom.color || '#7aa2d6', custom: true };
  }
  const hit = SUBGROUP_MAP[key] || SUBGROUP_MAP[key.replace(/_(F|M)(?=_|$)/, '')];
  if (hit) return hit;
  const cat = tokenCat(key);
  if (cat === 'outfit') {
    const fam = outfitFamilyOf(key);
    const defs = SUBGROUP_DEFS.outfit || [];
    const idx = defs.findIndex(d => d.label === fam);
    return { cat, idx: idx >= 0 ? idx : 98, label: fam, color: OUTFIT_FAMILY_COLOR[fam] || '#7d8798' };
  }
  const rules = SUBGROUP_PREFIX_RULES[cat] || [];
  for (const [re, label] of rules) {
    if (re.test(key)) {
      const defs = SUBGROUP_DEFS[cat] || [];
      const idx = defs.findIndex(d => d.label === label);
      const def = idx >= 0 ? defs[idx] : null;
      return { cat, idx: idx >= 0 ? idx : 98, label, color: def ? def.color : '#7d8798' };
    }
  }
  if (cat === 'neg') {
    const defs = SUBGROUP_DEFS.neg || [];
    const idx = defs.findIndex(d => d.label === '服装/细节');
    return { cat, idx: idx >= 0 ? idx : 98, label: '服装/细节', color: idx >= 0 ? defs[idx].color : '#d9b268' };
  }
  return null;
}


/* 场景 × 机位 兼容表（2026-11-08） */
const CAM_FRAMING = {
  '@CAM_CLOSEUP': 'near', '@CAM_BUST': 'near', '@CAM_PROFILE': 'near', '@CAM_HIP': 'near',
  '@CAM_MEDIUM': 'mid', '@CAM_THREEQ': 'mid',
  '@CAM_FULL': 'far', '@CAM_BACKSIDE': 'far', '@CAM_REAR': 'far'
};
// 每个尺度的场景，适合哪些景别
const SCENE_CAM_RULES = {
  small: ['near', 'mid'],
  medium: ['near', 'mid', 'far'],
  large: ['mid', 'far']
};
function sceneScaleKey(name) {
  const t = setScaleOf(name);
  return t === '小' ? 'small' : t === '中' ? 'medium' : 'large';
}
function camFraming(cam) { return CAM_FRAMING[cam] || 'mid'; }
function sceneCamCompatible(sceneTok, camTok) {
  if (!sceneTok || !camTok) return true;
  const sc = sceneScaleKey(sceneTok);
  return (SCENE_CAM_RULES[sc] || []).includes(camFraming(camTok));
}

function setScaleOf(name) {
  const k = String(name || '').toUpperCase();
  for (const sc of ['set_small', 'set_medium', 'set_large']) {
    if ((SET_SCALE_MAP[k] || '') === sc) return sc === 'set_small' ? '小' : sc === 'set_medium' ? '中' : '大';
  }
  return '中';
}

function paletteGroups() {
  const groups = {};
  for (const [name, text] of Object.entries(S.tokens)) {
    if (!tokenVisible(name)) continue;   // 性别不符 / 属于别人的角色卡
    const c = tokenCat(name);
    (groups[c] = groups[c] || []).push([name, text]);
  }
  return groups;
}


/* ---------- 分类光引导（2026-11-08） ---------- */
const GUIDE_CATS = ['id', 'body', 'face', 'cam', 'light', 'time', 'set', 'outfit', 'pose', 'mood', 'gaze', 'comp', 'neg'];
const GUIDE_PRIORITY = {
  free: GUIDE_CATS,
  portrait: ['face', 'gaze', 'cam', 'light', 'mood', 'body', 'comp', 'outfit', 'id', 'set', 'time', 'pose', 'neg'],
  scene: ['set', 'time', 'light', 'comp', 'cam', 'mood', 'pose', 'outfit', 'id', 'body', 'face', 'gaze', 'neg'],
  story: ['pose', 'mood', 'gaze', 'comp', 'cam', 'set', 'light', 'outfit', 'face', 'body', 'id', 'time', 'neg']
};
function localGuideRoles(mode, cov) {
  const order = GUIDE_PRIORITY[mode] || GUIDE_CATS;
  const missing = GUIDE_CATS.filter(k => !cov[k]);
  return order.filter(k => missing.includes(k)).slice(0, 4);
}
function glowMode() {
  const el = $('#guide-mode');
  const v = el ? el.value : (loadJSON('loom.glowMode', 'free') || 'free');
  return v || 'free';
}
function categoryCoverage() {
  let pos = S.pos || [];
  const neg = S.neg || [];
  if (S.coopOn && S.coop) pos = pos.concat(S.coop.envPos || [], S.coop.chrPos || [], S.coop.commonPos || []);
  const hasTok = re => pos.some(b => re.test(b.token || ''));
  const hasText = re => pos.some(b => !b.token && re.test(b.text || ''));
  const hasNeg = re => neg.some(b => re.test(b.token || ''));
  return {
    id: hasTok(/^@ID/) || (hasText(/shoulder-length hair/i) && hasText(/warm brown eyes|expressive eyes/i)),
    body: hasTok(/^@BODY_/),
    face: hasTok(/^@FACE_/),
    cam: hasTok(/^@CAM_/),
    light: hasTok(/^@LIGHT_/),
    time: hasTok(/^@TIME_/),
    set: hasTok(/^@SET_/),
    outfit: hasTok(/^@OUT_/) || hasTok(/^@OUTFIT/),
    pose: hasTok(/^@POSE_/),
    mood: hasTok(/^@MOOD_/),
    gaze: hasTok(/^@GAZE_/),
    comp: hasTok(/^@COMP_/),
    neg: hasNeg(/^@NEG_BASE/)
  };
}
function artistCovered() {
  return (S.loras || []).some(l => { try { return loraCat(l.name) === '画师'; } catch (e) { return false; } });
}
let _guideSeq = 0, _guideTimer = null, _guideSig = '', _guideBusy = false;
function applyGuideRoles(roles, on) {
  const set = new Set(on ? (roles || []) : []);
  $$('.rail-item').forEach(b => {
    const cat = b.dataset.cat || '';
    b.classList.toggle('need', set.has(cat));
  });
  $$('.pal-group').forEach(g => {
    const cat = g.dataset.cat || '';
    g.classList.toggle('need', set.has(cat));
  });
  const badge = $('#pal-artist-need');
  if (badge) {
    const miss = on && !artistCovered();
    badge.hidden = !miss;
    badge.textContent = miss ? '画师' : '';
  }
}
function guideSignature() {
  const blocks = (S.pos || []).map(b => b.token || b.text || '').concat(
    S.coopOn && S.coop ? [].concat(S.coop.envPos || [], S.coop.chrPos || [], S.coop.commonPos || []).map(b => b.token || b.text || '') : []);
  return JSON.stringify({ m: glowMode(), b: blocks });
}
let _lightSeq = 0, _lightTimer = null;

// 光引导（规则脚本 /api/guide/light，无模型）：补全建议写进分类的悬停提示
async function fetchLightGuide() {
  const mode = glowMode();
  if (mode === 'off') return;
  const seq = ++_lightSeq;
  const pos = (S.pos || []).map(b => ({ token: b.token || '', text: b.text || '', weight: Number(b.weight) || 1 }));
  const neg = (S.neg || []).map(b => ({ token: b.token || '', text: b.text || '', weight: 1 }));
  if (S.coopOn && S.coop) {
    (S.coop.envPos || []).concat(S.coop.chrPos || [], S.coop.commonPos || []).forEach(b =>
      pos.push({ token: b.token || '', text: b.text || '', weight: Number(b.weight) || 1 }));
    (S.coop.chrNeg || []).concat(S.coop.commonNeg || []).forEach(b =>
      neg.push({ token: b.token || '', text: b.text || '', weight: 1 }));
  }
  try {
    const res = await fetch('/api/guide/light', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ blocks: pos, negatives: neg, mode: mode }) });
    const r = await res.json();
    if (seq !== _lightSeq || !r || !Array.isArray(r.roles)) return;
    applyGuideRoles(r.roles, true);
    S.lightTips = r.tips || {};
    S.lightReady = !!r.ready;
    $$('.rail-item').forEach(b => {
      const tips = (S.lightTips || {})[b.dataset.cat];
      const base = b.title.split('｜')[0];
      b.title = (tips && tips.length) ? (base + '｜缺：试 ' + tips.join(' / ')) : base;
    });
  } catch (e) { /* 失败就保留本地规则的结果 */ }
}

function renderGuideGlow() {
  const mode = glowMode();
  const on = mode !== 'off';
  const cov = categoryCoverage();
  const local = on ? localGuideRoles(mode, cov) : [];
  applyGuideRoles(local, on);
  const prio = GUIDE_PRIORITY[mode] || [];
  const ready = on && prio.every(k => cov[k]);
  if (ready && !S._glowDone) { S._glowDone = true; toast('主分类齐了，可以出图'); }
  if (!ready) S._glowDone = false;

  if (_lightTimer) clearTimeout(_lightTimer);
  _lightTimer = setTimeout(fetchLightGuide, 500);
}

function renderPalette() {
  const box = $('#palette'), rail = $('#pal-rail');
  if (!box || !rail) return;
  const groups = paletteGroups();
  const order = ['id','body','face','hair','acc','cam','set','prop','light','time','atmo',
                 'outfit','fabric','drape','mood','gaze','pose','hand','hold','weapon',
                 'comp','style','neg','nsfw','custom'];
  const collapsed = S.collapsedCats || (S.collapsedCats = loadJSON('loom.collapsedCats', {}));
  let html = '', railHtml = '';
  const hiddenNeg = S.showCompanionNeg ? new Set() : companionNegSet();
  // 收藏组（置顶）
  const favs = (S.fav || []).filter(k => S.tokens[k] && !hiddenNeg.has(k));
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
    if (hiddenNeg.size) items = items.filter(([n]) => !hiddenNeg.has(n));
    if (!items.length) continue;
    const label = CAT_LABEL[key] || key;
    const closed = !!collapsed[key];
    html += '<div class="pal-group' + (closed ? ' closed' : '') + '" id="cat-' + key + '" data-cat="' + key + '">' +
      '<span class="caret">▾</span>' + label +
      '<span class="num">' + items.length + '</span></div>' +
      '<div class="pal-items' + (closed ? ' hidden' : '') + '" data-items="' + key + '">';
    if (key === 'set') {
      const order2 = ['小', '中', '大'];
      items.sort((a, b) => order2.indexOf(setScaleOf(a[0])) - order2.indexOf(setScaleOf(b[0])));
      let cur = '';
      for (const [name] of items) {
        const sc = setScaleOf(name);
        if (sc !== cur) {
          cur = sc;
          html += '<div class="pal-sub" data-sub="' + sc + '">' + sc + '场景</div>';
        }
        const isFav = (S.fav || []).indexOf(name) >= 0;
        html += '<div class="pal-item sc-' + (sc === '小' ? 'small' : sc === '中' ? 'medium' : 'large') + '" draggable="true" data-token="' + name + '" data-cat="' + key + '" title="' + sc + '场景">'
          
          + '<span class="tk">' + name + '</span>'
          + '<span class="fav' + (isFav ? ' on' : '') + '" data-fav="' + name + '" title="收藏">' + (isFav ? '★' : '☆') + '</span>'
          + '<span class="add">＋</span></div>';
      }
      html += '</div>';
      railHtml += '<button class="rail-item" data-jump="' + key + '" data-cat="' + key + '" title="' + label + '"><i></i>' + (RAIL_SHORT[key] || label.slice(0, 2)) + '</button>';
      continue;
    }
    const defs = SUBGROUP_DEFS[key];
    if (defs) {
      const rank = t => { const g = subgroupOf(t); return g ? g.idx : 99; };
      items.sort((a, b) => rank(a[0]) - rank(b[0]));
      let curIdx = -2, curLabel = '';
      for (const [name] of items) {
        const g = subgroupOf(name);
        const gi = g ? g.idx : 99;
        const lab0 = g ? g.label : '其他';
        if (lab0 !== curLabel) {
          curIdx = gi; curLabel = lab0;
          const lab = g ? g.label : '其他';
          const col = g ? g.color : '#7d8798';
          html += '<div class="pal-sub" data-sub="' + esc(lab) + '" style="border-color:' + col + ';color:' + col + '">' + esc(lab) + '</div>';
        }
        const isFav = (S.fav || []).indexOf(name) >= 0;
        html += '<div class="pal-item" draggable="true" data-token="' + name + '" data-cat="' + key + '"' + tintAttrs(name) + '>'
          + '<span class="tk">' + name + '</span>'
          + '<span class="fav' + (isFav ? ' on' : '') + '" data-fav="' + name + '" title="收藏">' + (isFav ? '★' : '☆') + '</span>'
          + '<span class="add">＋</span></div>';
      }
      html += '</div>';
      railHtml += '<button class="rail-item" data-jump="' + key + '" data-cat="' + key + '" title="' + label + '"><i></i>' + (RAIL_SHORT[key] || label.slice(0, 2)) + '</button>';
      continue;
    }
    const szTag = '';
    for (const [name] of items) {
      const isFav = (S.fav || []).indexOf(name) >= 0;
      html += '<div class="pal-item" draggable="true" data-token="' + name + '" data-cat="' + key + '">'
        + (szTag ? '<span class="sz sz-' + szTag + '" title="' + szTag + '场景">' + szTag + '</span>' : '')
        + '<span class="tk">' + name + '</span>'
        + '<span class="fav' + (isFav ? ' on' : '') + '" data-fav="' + name + '" title="收藏">' + (isFav ? '★' : '☆') + '</span>'
        + '<span class="add">＋</span></div>';
    }
    html += '</div>';
    railHtml += '<button class="rail-item" data-jump="' + key + '" data-cat="' + key +
      '" title="' + label + '"><i></i>' + (RAIL_SHORT[key] || label.slice(0, 2)) + '</button>';
  }
  box.innerHTML = html || '<div class="hint">没有匹配的积木</div>';
  rail.innerHTML = railHtml;
  renderGuideGlow();
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
    let lpTimer = null, longPressed = false;
    el.addEventListener('pointerdown', () => {
      longPressed = false;
      lpTimer = setTimeout(() => { longPressed = true; jumpToCategory(el.dataset.cat); }, 560);
    });
    const cancelLp = () => { if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; } };
    el.addEventListener('pointerup', cancelLp);
    el.addEventListener('pointerleave', cancelLp);
    el.addEventListener('click', () => { if (longPressed) { longPressed = false; return; } addBlock('positive', el.dataset.token); });
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
    if (box._jumpingUntil && Date.now() < box._jumpingUntil) return;
    let active = null;
    for (const g of $$('.pal-group', box)) {
      if (g.getBoundingClientRect().top - box.getBoundingClientRect().top <= 12) active = g.dataset.cat;
    }
    $$('.rail-item', rail).forEach(b => b.classList.toggle('active', b.dataset.jump === active));
  };
  box.onscroll = spy;
  spy();
}

function scrollPalTo(key) {
  const box = $('#palette'), target = document.getElementById('cat-' + key);
  if (!box || !target) return;
  box._jumpingUntil = Date.now() + 260;
  const delta = target.getBoundingClientRect().top - box.getBoundingClientRect().top;
  const top = Math.max(0, box.scrollTop + delta - 4);
  try { box.scrollTo({ top, behavior: 'instant' }); } catch (e) { box.scrollTop = top; }
  target.classList.add('flash');
  setTimeout(() => target.classList.remove('flash'), 800);
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


/* ---------- 组合建议（只提示，不自动加） ---------- */
const SUGGEST = {
  '@SET_ONSEN': [{ t: '@TIME_NIGHT', why: '温泉夜景' }, { t: '@LIGHT_CANDLE', why: '水汽暖光' }, { t: '@BG_DARKFALL', why: '蒸汽暗调' }],
  '@ID_F_ADULT': [{ t: '@NEG_CHILD', why: '防幼态' }],
  '@FACE_FADULT': [{ t: '@NEG_CHILD', why: '防幼态' }],
  '@BODY_F_ADULT': [{ t: '@NEG_CHILD', why: '防幼态' }],
  '@ID_M_ADULT': [{ t: '@NEG_CHILD', why: '防幼态' }],
  '@SET_BEDROOM': [{ t: '@TIME_MORNING', why: '晨光透窗' }, { t: '@OUT_PAJAMA', why: '居家睡衣' }, { t: '@NEG_DIORAMA', why: '防微缩房' }],
  '@SET_CLASSROOM': [{ t: '@TIME_AFTERNOON', why: '午后斜光' }, { t: '@BG_CLEAN', why: '教室整洁' }],
  '@SET_MARKET': [{ t: '@TIME_NIGHT', why: '夜市灯串' }, { t: '@LIGHT_NEON', why: '霓虹补色' }],
  '@SET_ARCADE': [{ t: '@LIGHT_NEON', why: '机台霓虹' }, { t: '@BG_BOKEH', why: '机台光斑' }],
  '@SET_SHRINE': [{ t: '@TIME_DUSK', why: '黄昏参道' }],
  '@SET_STATION': [{ t: '@TIME_NIGHT', why: '夜行站台' }, { t: '@BG_BOKEH', why: '站台灯串' }],
  '@SET_MUSEUM': [{ t: '@BG_CLEAN', why: '展馆留白' }],
  '@SET_FOREST': [{ t: '@LIGHT_GOLDEN', why: '林间光柱' }],
  '@SET_BEACH': [{ t: '@TIME_NOON', why: '正午海面' }, { t: '@NEG_OVEREXP', why: '白色过曝' }],
  '@CAM_TOP': [{ t: '@COMP_CENTER', why: '俯视偏中心' }],
  '@CAM_WORM': [{ t: '@COMP_LOW', why: '低机位构图' }],
  '@POSE_CROUCH': [{ t: '@COMP_TRIANGLE', why: '蹲姿三角' }],
  '@POSE_LIE': [{ t: '@NEG_DIORAMA', why: '防微缩房' }, { t: '@NEG_LONGHAIR', why: '限发长' }],
  '@MOOD_SMOKE': [{ t: '@STYLE_NOIR', why: '黑电影光' }, { t: '@ATMO_FOG', why: '烟雾层次' }],
  '@MOOD_ALCOHOL': [{ t: '@STYLE_NOIR', why: '酒吧暗调' }, { t: '@LIGHT_CANDLE', why: '暖点光' }],
  '@MAKEUP_SICK': [{ t: '@STYLE_GRAIN', why: '病态配颗粒' }],
  '@OUT_GALA': [{ t: '@CAM_FULL', why: '拖尾要全身' }, { t: '@BG_DARKFALL', why: '礼服压暗' }],
  '@OUT_YUKATA': [{ t: '@SET_ROOFTOP', why: '夏祭屋顶' }],
  '@COMP_NEGATIVE': [{ t: '@COMP_MINIMAL', why: '留白配极简' }, { t: '@BG_CLEAN', why: '留白配净背景' }],
  '@WEAPON_SCYTHE': [{ t: '@CAM_FULL', why: '长柄需要全身' }],
};

function suggestFor(token) {
  const c = resolveToken(token);
  const list = SUGGEST[token] || SUGGEST[c] || SUGGEST[c.replace(/_(F|M)(?=_|$)/, '')] || [];
  return list.filter(h => !S.pos.some(b => b.token === h.t) && !S.neg.some(b => b.token === h.t));
}

/* ---------- 画布 ---------- */
/* 专属负向：由某个正向块配对产生（服装→@NEG_<KEY>、型态→@NEG_DRAPE_*、手部→@NEG_HAND_ART 等）。
   默认在积木库里隐藏，加入对应正向块后自动出现在负向泳道；可在积木库头部勾选显示。 */
function companionNegSet() {
  const set = new Set();
  const has = t => !!(t && S.tokens && S.tokens[t]);
  for (const k of Object.keys(S.tokens || {})) {
    if (k.startsWith('@OUT_')) {
      const neg = k.replace('@OUT_', '@NEG_');
      if (has(neg)) set.add(neg);
    }
  }
  ['@NEG_GARMENT', '@NEG_DRAPE_ON', '@NEG_DRAPE_OFF', '@NEG_HAND_ART'].forEach(k => {
    if (has(k)) set.add(k);
  });
  return set;
}

/* 配套积木：加正向时顺手把对偶/配套的一起放好（已有的跳过） */
// 场景 → 背景处理（自动补一块，可手动删）
const BG_LINK = {
  '@SET_MARKET': '@BG_BOKEH', '@SET_ARCADE': '@BG_BOKEH', '@SET_ROOFTOP': '@BG_BOKEH',
  '@SET_BALCONY': '@BG_BOKEH', '@SET_STATION': '@BG_BOKEH', '@SET_CITY_STREET': '@BG_BOKEH',
  '@SET_ARTROOM': '@BG_CLEAN', '@SET_LIBRARY': '@BG_CLEAN', '@SET_MUSEUM': '@BG_CLEAN',
};

const HAIR_ACCESSORIES = new Set(['@HAIRPIN_ROSE', '@HAIRPIN_STAR', '@CLIP_BUTTERFLY', '@PIN_MOON', '@MINI_TOPHAT', '@BERET', '@HEADBAND_PEARL', '@RIBBON_BOW', '@PIN_FEATHER', '@PIN_HEART', '@PIN_CROSS', '@FLOWER_CROWN', '@CLIP_CAT_EAR']);

const CHIBI_BODIES = new Set(['@BODY_F_CHIBI', '@BODY_F_CHIBI_SD', '@BODY_CHIBI', '@BODY_CHIBI_SD']);
const OUTLINE_SOURCES = new Set(['@STYLE_GLITCH', '@FX_BLACK_BLOCKS', '@FX_BAND_GLITCH', '@STYLE_SOFT']);
function companionsOf(token) {
  const out = [];
  const has = t => !!(t && S.tokens && S.tokens[t]);
  if (!token) return out;
  if (token === '@OUTFIT') {
    if (has('@NEG_GARMENT')) out.push({ lane: 'negative', token: '@NEG_GARMENT' });
  } else if (token.startsWith('@OUT_')) {
    const neg = token.replace('@OUT_', '@NEG_');
    if (has(neg)) out.push({ lane: 'negative', token: neg });
  }
  if (CHIBI_BODIES.has(token)) {
    const fc = has('@FACE_FCHIBI') ? '@FACE_FCHIBI' : '@FACE_CHIBI';
    if (has(fc)) out.push({ lane: 'positive', token: fc });
    if (has('@NEG_CHIBI')) out.push({ lane: 'negative', token: '@NEG_CHIBI' });
  }
  if (OUTLINE_SOURCES.has(token) && has('@NEG_OUTLINE')) out.push({ lane: 'negative', token: '@NEG_OUTLINE' });
  if (HAIR_ACCESSORIES.has(token)) {
    if (has('@NEG_ACC_FACE')) out.push({ lane: 'negative', token: '@NEG_ACC_FACE' });
  }
  if (token.startsWith('@DRAPE_')) {
    const worn = ['@DRAPE_WORN', '@DRAPE_ARMS', '@DRAPE_WAIST'].includes(token);
    const target = worn ? '@NEG_DRAPE_OFF' : '@NEG_DRAPE_ON';
    if (has(target)) out.push({ lane: 'negative', token: target });
  }
  if (token.startsWith('@WEAPON_') && token !== '@WEAPON_GRIP' && has('@WEAPON_GRIP')) {
    out.push({ lane: 'positive', token: '@WEAPON_GRIP' });
  }
  // 手部动作 → 手指负向（IR 里早就有这条提示，现在顺手补上）
  if (token.startsWith('@HAND_') && has('@NEG_HAND_ART')) {
    out.push({ lane: 'negative', token: '@NEG_HAND_ART' });
  }
  const bg = BG_LINK[token];
  if (bg && has(bg)) out.push({ lane: 'positive', token: bg });
  // 虚化/暗光 → 去黑边负向（黑边几乎总在这些场景出现，自动补一块，可删）
  if (token === '@BARE_FEET') {
    if (has('@NEG_SHOES')) out.push({ lane: 'negative', token: '@NEG_SHOES' });
    if (has('@NEG_SOCKS')) out.push({ lane: 'negative', token: '@NEG_SOCKS' });
  }
  const negLink = { '@BG_BOKEH': '@NEG_LETTERBOX', '@STYLE_NOIR': '@NEG_LETTERBOX' }[token];
  if (negLink && has(negLink)) out.push({ lane: 'negative', token: negLink });
  if (token === '@CROP_FULL' && has('@NEG_LETTERBOX')) out.push({ lane: 'negative', token: '@NEG_LETTERBOX' });
  return out;
}

function addBlock(lane, tokenOrObj) {
  if (S.coopOn && S.coop && S._coopRouting !== false) {
    const tok = typeof tokenOrObj === 'string' ? tokenOrObj : ((tokenOrObj && tokenOrObj.token) || '');
    const txt = (typeof tokenOrObj === 'object' && tokenOrObj) ? (tokenOrObj.text || '') : '';
    if (tok && /^@SET_/.test(tok) && typeof reprojAddScene === 'function') {
      reprojAddScene(tok);
      return;
    }
    if (tok && typeof reprojIsMainGarmentToken === 'function' && reprojIsMainGarmentToken(tok) && typeof reprojSetGarment === 'function') {
      reprojSetGarment(tok);
      return;
    }
    const isNeg = lane === 'negative' || (tok && tokenCat(tok) === 'neg');
    const target = coopBucketFor({ token: tok }, isNeg);
    const SINGLE = /^@(ID|SINGLE|BODY_|FACE_|STYLE_|LIGHT_|CAM_|SET_|OUT_|TIME_|COMP_|POSE_|MOOD_|GAZE_)/;
    const arr = S.coop[target] = S.coop[target] || [];
    if (tok && /^@ID_/.test(tok)) {
      for (let i = arr.length - 1; i >= 0; i--) { if (/^@ID_/.test(arr[i].token || '')) arr.splice(i, 1); }
      if (tok.endsWith('_ADULT')) {
        for (let i = arr.length - 1; i >= 0; i--) { if (/_PETITE$/.test(arr[i].token || '')) arr.splice(i, 1); }
      }
    }
    if (tok && /^@BODY_/.test(tok)) {
      for (let i = arr.length - 1; i >= 0; i--) { if (/^@BODY_/.test(arr[i].token || '')) arr.splice(i, 1); }
    }
    if (tok && SINGLE.test(tok) && arr.some(b => b.token === tok)) { toast('已有 ' + tok + '，不重复添加', true); return; }
    arr.push({ id: uid(), token: tok, text: txt, weight: 1, enabled: true });
    renderCoopLanes(); coopBind(); expandPreview();
    return;
  }
  const _t0 = typeof tokenOrObj === 'string' ? tokenOrObj : (tokenOrObj && tokenOrObj.token) || '';
  if (/\.safetensors$/i.test(_t0)) { toast('LoRA 文件名不能当积木', true); return; }
  const _x0 = typeof tokenOrObj === 'object' && tokenOrObj ? String(tokenOrObj.text || '').trim() : '';
  if (!_t0 && !_x0) { toast('空积木已忽略（没有 token 也没有文本）', true); return; }
  if (lane === 'positive') {
    const nm = typeof tokenOrObj === 'string' ? tokenOrObj : (tokenOrObj && tokenOrObj.token) || '';
    if (nm && tokenCat(nm) === 'neg') lane = 'negative';
  }
  pushHistory();
  const arr = lane === 'positive' ? S.pos : S.neg;
  const token = typeof tokenOrObj === 'string' ? tokenOrObj : (tokenOrObj && tokenOrObj.token) || '';
  if (lane === 'positive' && token && /^@ID_/.test(token)) {
    for (let i = arr.length - 1; i >= 0; i--) { if (/^@ID_/.test(arr[i].token || '')) arr.splice(i, 1); }
    if (token.endsWith('_ADULT')) {
      for (let i = arr.length - 1; i >= 0; i--) { if (/_PETITE$/.test(arr[i].token || '')) arr.splice(i, 1); }
    }
  }
  if (lane === 'positive' && token && /^@BODY_/.test(token)) {
    for (let i = arr.length - 1; i >= 0; i--) { if (/^@BODY_/.test(arr[i].token || '')) arr.splice(i, 1); }
  }
  const SINGLE = /^@(ID|SINGLE|BODY_|FACE_|STYLE_|LIGHT_|CAM_|SET_|OUT_|TIME_|COMP_|POSE_|MOOD_|GAZE_)/;
  if (token && SINGLE.test(token) && arr.some(b => b.token === token)) { toast('已有 ' + token + '，不重复添加', true); return; }
  if (typeof tokenOrObj === 'string') {
    arr.push({ id: uid(), token: tokenOrObj, text: '', weight: 1, enabled: true });
  } else {
    arr.push(Object.assign({ id: uid(), token:'', text:'', weight:1, enabled:true }, tokenOrObj));
  }
  // 加正向时同步配套（服装→负向、型态→对偶负向、武器→GRIP）
  const extra = [];
  if (lane === 'positive' && token) {
    for (const c of companionsOf(token)) {
      const target = c.lane === 'positive' ? S.pos : S.neg;
      if (target.some(b => b.token === c.token)) continue;
      target.push({ id: uid(), token: c.token, text: '', weight: 1, enabled: true, auto: true });
      extra.push(c.token);
    }
  }
  renderLanes(); expandPreview();
  if (extra.length) toast('已同步加入配套：' + extra.join('、'));
  // 组合建议：只提示，不自动加；同一块只提示一次
  if (lane === 'positive' && token) {
    const hints = suggestFor(token);
    if (hints.length) {
      S.hinted = S.hinted || {};
      if (!S.hinted[token]) {
        S.hinted[token] = true;
        setTimeout(() => {
          toast('建议：' + hints.map(h => h.t + '（' + h.why + '）').join('、'));
        }, extra.length ? 1400 : 0);
      }
    }
  }
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
      const scCls = (b.token && /^@SET_/.test(b.token)) ? ' sc-' + (setScaleOf(b.token) === '小' ? 'small' : setScaleOf(b.token) === '中' ? 'medium' : 'large') : '';
      const relX = b.token && (S.rel || {})[b.token] === 'X';
      return '<div class="chip' + scCls + ' ' + (lane === 'positive' ? 'pos' : 'neg') + (b.enabled ? '' : ' off') +
        (relX ? ' rel-x' : '') +
        '" draggable="true" data-id="' + b.id + '" data-lane="' + lane + '" data-cat="' + cat + '"' +
        (b.token ? tintAttrs(b.token) : '') +
        (b.token ? ' data-token="' + b.token + '"' : '') + '>' +
        '<span class="grab">⠿</span>' +
        '<button class="on" data-toggle="' + b.id + '" data-lane="' + lane + '">' + (b.enabled ? '●' : '○') + '</button>' +
        body +
        '<input type="number" step="0.05" min="0" max="3" value="' + b.weight + '" data-weight="' + b.id + '" data-lane="' + lane + '" title="权重">' +
        '<button class="x" data-del="' + b.id + '" data-lane="' + lane + '">×</button>' +
        '</div>';
    }).join('') || '<span class="hint">把左边积木拖到这里，或点击添加</span>';
    try { if (typeof bindTips === 'function') bindTips(box); } catch (e) {}
    if (!box.dataset.dropBound) {
      box.dataset.dropBound = '1';
    box.addEventListener('dragover', e => { e.preventDefault(); });
    box.addEventListener('drop', e => {
      e.preventDefault();
      const raw = e.dataTransfer.getData('text/plain');
      if (!raw) return;
      let d = null;
      try { d = JSON.parse(raw); } catch (err) { d = null; }
      if (d && d.move) {
        moveBlock(d.move, d.lane, lane, dropIndex(box, e.clientY));
        return;
      }
      if (d && d.token) { addBlock(lane, d); return; }
      if (raw.trim().length > 1) addBlock(lane, { text: raw }); else toast('空拖拽已忽略', true);
    });
    }
  }
  bindTips($('#lane-positive'));
  bindTips($('#lane-negative'));
  $('#pos-count').textContent = S.pos.length + ' 块';
  $('#neg-count').textContent = S.neg.length + ' 块';
  bindLaneEvents();
}

function dropIndex(box, clientY) {
  const chips = [...box.querySelectorAll('.chip')];
  for (let i = 0; i < chips.length; i++) {
    const r = chips[i].getBoundingClientRect();
    if (clientY < r.top + r.height / 2) return i;
  }
  return chips.length;
}

function moveBlock(id, fromLane, toLane, index) {
  const src = fromLane === 'positive' ? S.pos : S.neg;
  const dst = toLane === 'positive' ? S.pos : S.neg;
  const i = src.findIndex(b => b.id === id);
  if (i < 0) return;
  pushHistory();
  const [item] = src.splice(i, 1);
  const at = Math.max(0, Math.min(typeof index === 'number' ? index : dst.length, dst.length));
  if (src === dst && i < at) at = Math.max(0, at - 1);
  dst.splice(at, 0, item);
  renderLanes(); expandPreview();
}

function bindLaneEvents() {
  $$('[data-del]').forEach(el => el.onclick = () => {
    const arr = el.dataset.lane === 'positive' ? S.pos : S.neg;
    pushHistory();
    const i = arr.findIndex(b => b.id === el.dataset.del);
    if (i < 0) return;
    const gone = arr.splice(i, 1)[0];
    // 联动删除：删正向块时，把它自动带出来的配套负向一起删掉（手动加的不动）
    if (el.dataset.lane === 'positive' && gone && gone.token) {
      const comps = companionsOf(gone.token);
      const wantNeg = comps.filter(c => c.lane === 'negative').map(c => c.token);
      const wantPos = comps.filter(c => c.lane === 'positive').map(c => c.token);
      S.neg = S.neg.filter(b => !(b.auto && wantNeg.indexOf(b.token) >= 0));
      S.pos = S.pos.filter(b => !(b.auto && wantPos.indexOf(b.token) >= 0));
    }
    renderLanes(); expandPreview();
  });
  $$('[data-toggle]').forEach(el => el.onclick = () => {
    const arr = el.dataset.lane === 'positive' ? S.pos : S.neg;
    pushHistory();
    const b = arr.find(x => x.id === el.dataset.toggle);
    if (b) b.enabled = !b.enabled;
    renderLanes(); expandPreview();
  });
  $$('[data-weight]').forEach(el => { el.addEventListener('click', e => e.stopPropagation()); el.addEventListener('dblclick', e => e.stopPropagation()); });
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
    el.addEventListener('dblclick', (e) => {
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON')) return;
      const arr = el.dataset.lane === 'positive' ? S.pos : S.neg;
      const b = arr.find(x => x.id === el.dataset.id);
      if (!b) return;
      if (b.token) openBlockDetail(b, el.dataset.lane); else editFreeText(el);
    });
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
  const id = chipEl.dataset.id, coopLane = chipEl.dataset.coopLane;
  if (coopLane) {
    const c = coopEnsure(), arr = c[coopLane] || [];
    const b = arr.find(x => x.id === id);
    if (!b || b.token) return;
    const lane = coopLane.endsWith('Neg') ? 'negative' : 'positive';
    openTextBlockDialog({
      lane, text: b.text, weight: b.weight, title: '编辑文本块',
      onSave: (text, weight, lane2) => {
        if (lane2 === lane) { b.text = text; b.weight = weight; }
        else {
          const i = arr.indexOf(b);
          if (i >= 0) arr.splice(i, 1);
          const target = coopBucketFor({ token: '', text }, lane2 === 'negative');
          (c[target] = c[target] || []).push(Object.assign({}, b, { text, weight }));
        }
        renderCoopLanes(); coopBind(); expandPreview();
      }
    });
    return;
  }
  const lane = chipEl.dataset.lane;
  const arr = lane === 'positive' ? S.pos : S.neg;
  const b = arr.find(x => x.id === id);
  if (!b || b.token) return;
  openTextBlockDialog({
    lane, text: b.text, weight: b.weight, title: '编辑文本块',
    onSave: (text, weight, lane2) => {
      if (lane2 === lane) { b.text = text; b.weight = weight; }
      else {
        const i = arr.indexOf(b);
        if (i >= 0) arr.splice(i, 1);
        (lane2 === 'positive' ? S.pos : S.neg).push(Object.assign({}, b, { text, weight }));
      }
      renderLanes(); expandPreview();
    }
  });
}



async function expandPreview() {
  // 随机/换场景/换服装期间（_coopRouting=false）不要把还没分流的 S.pos 冲掉
  if (S.coopOn && S._coopRouting !== false && typeof coopToGlobal === 'function') coopToGlobal();
  persistLanes();
  persistParams();
  try {
    const r = await api('/api/expand', { method:'POST', body: JSON.stringify({ positive: S.pos, negative: S.neg }) });
    $('#preview-pos').textContent = r.positive || '（空）';
    $('#preview-neg').textContent = r.negative || '（空）';
    $('#expand-used').textContent = '正向 ' + r.pos_len + ' 字符 / 负向 ' + r.neg_len + ' 字符 · 用了 ' + r.used.length + ' 个宏';
    S.lastExpanded = r;
    const box = $('#preview-coop');
    if (box) {
      box.hidden = !S.coopOn;
      if (S.coopOn) {
        const c = coopEnsure();
        const call = (pos, neg) => api('/api/expand', { method: 'POST', body: JSON.stringify({ positive: pos, negative: neg }) });
        const merge = (a, b) => {
          const seen = new Set(), out = [];
          (a || []).concat(b || []).forEach(x => {
            const k = x.token || ('txt:' + (x.text || ''));
            if (seen.has(k)) return;
            seen.add(k); out.push(x);
          });
          return out;
        };
        const cpos = c.commonPos || [], cneg = c.commonNeg || [];
        Promise.all([
          call(merge(merge(cpos, c.envPos), reprojExtraEnv()), cneg),
          call(merge(cpos, c.chrPos), merge(cneg, c.chrNeg))
        ]).then(([e, ch]) => {
          if ($('#preview-env-pos')) $('#preview-env-pos').textContent = e.positive || '（空）';
          if ($('#preview-env-neg')) $('#preview-env-neg').textContent = cneg.length ? '（公共负向见下方）' : '（空）';
          if ($('#preview-chr-pos')) $('#preview-chr-pos').textContent = ch.positive || '（空）';
          if ($('#preview-chr-neg')) $('#preview-chr-neg').textContent = ch.negative || '（空）';
          const sum = $('#coop-split-summary');
          if (sum) {
            const cnt = k => (c[k] || []).length;
            sum.textContent = '分流：公共 ' + cnt('commonPos') + ' · 环境 ' + cnt('envPos') + ' · 人物 ' +
              cnt('chrPos') + ' · 公共负 ' + cnt('commonNeg') + ' · 人物负 ' + cnt('chrNeg');
          }
        }).catch(() => {});
      }
    }
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
  const sel = $('#p-size');
  if (sel && sel.value === 'custom') {
    const cw = Math.min(2048, Math.max(256, Math.round((Number($('#p-w').value) || 1024) / 8) * 8));
    const ch = Math.min(2048, Math.max(256, Math.round((Number($('#p-h').value) || 1536) / 8) * 8));
    return { w: cw, h: ch };
  }
  const [w, h] = ((sel && sel.value) || '1024x1536').split('x').map(Number);
  return { w, h };
}

function vramGB() {
  return ((S.comfy && S.comfy.vram_total) ? S.comfy.vram_total : 24e9) / 1e9;
}

function sizeRisk(w, h) {
  const px = w * h;
  const gb = vramGB();
  const warnMP = gb * 0.12;   // 8GB→0.96MP，24GB→2.88MP
  const badMP = gb * 0.20;    // 8GB→1.7MP，24GB→4.8MP
  if (px / 1e6 > badMP) return 'bad';
  if (px / 1e6 > warnMP) return 'warn';
  return 'ok';
}

function updateSizeHint() {
  const box = $('#size-hint');
  if (!box) return;
  const { w, h } = size();
  const mp = (w * h / 1e6).toFixed(2);
  const steps = Number($('#p-steps').value) || 30;
  const sec = Math.round((w * h * steps * 1.6e-6 + 1.5) * modelFactor());
  const r = sizeRisk(w, h);
  const gb = vramGB();
  let txt = w + ' × ' + h + ' · ' + mp + ' MP · 预计 ' + sec + ' 秒/张';
  if (r === 'warn') txt += ' · ⚠ 接近显存上限（' + gb.toFixed(0) + ' GB）';
  if (r === 'bad') {
    const lim = Math.floor(Math.sqrt(gb * 0.18 * 1e6 * 2 / 3) / 8) * 8;
    txt += ' · ⚠ 很可能 OOM，建议不超过 ' + lim + ' × ' + Math.round(lim * 1.5 / 8) * 8;
  }
  box.textContent = txt;
  box.className = 'size-hint' + (r === 'ok' ? '' : ' ' + r);
}
function modelFactor() {
  const m = (($('#p-model') || {}).value || '');
  return /29B/i.test(m) ? 2.8 : 1;
}
function estimate() {
  const { w, h } = size();
  const steps = Number($('#p-steps').value) || 30;
  return Math.round((w * h * steps * 1.6e-6 + 1.5) * modelFactor());
}
function updateEta() {
  const { w, h } = size();
  const steps = Number($('#p-steps').value) || 30;
  const sec = Math.round(w * h * steps * 1.6e-6 + 1.5);
  S.eta = sec;
  $('#eta').textContent = '预计 ' + sec + ' 秒/张';
  updateSizeHint();
}

const LORA_CAT_ORDER = ['角色', '画师', '背景', '厚涂', '动作', '风格', '加速'];
function renderLoras() {
  if (S.loras) S.loras = S.loras.filter(l => !l.name || typeof loraCompatible !== 'function' || loraCompatible(l.name));
  if (typeof renderStyleLoraOptions === 'function') setTimeout(renderStyleLoraOptions, 0);
  const box = $('#lora-list');
  box.innerHTML = S.loras.map((l, i) =>
    '<div class="lora-row">' +
    '<select data-lora-name="' + i + '" title="' + (l.name || '') + '">' + loraOptionsHtml(l.name) + '</select>' +
    '<input type="number" step="0.01" value="' + l.weight + '" data-lora-w="' + i + '">' +
    '<button class="x" data-lora-del="' + i + '">×</button></div>').join('');
  $$('[data-lora-name]').forEach(el => el.onchange = () => {
    const it = S.loras[el.dataset.loraName];
    it.name = el.value;
    it.weight = loraCat(el.value) === '画师'
      ? ((typeof artistDefaultWeight === 'function' && artistDefaultWeight(el.value, currentCharLora())) || loraDefaultWeight(el.value))
      : loraDefaultWeight(el.value);
    if (typeof isHeavyStyleLora === 'function' && isHeavyStyleLora(el.value)) toast('画师 LoRA 建议 0.6–1.3（标准 1.0）；低于 0.6 像没开，高于 1.3 容易糊', true);
    renderLoras();
  });
  $$('[data-lora-w]').forEach(el => {
    const save = () => {
      const v = parseFloat(el.value);
      if (!Number.isFinite(v)) return;
      const l = S.loras[Number(el.dataset.loraW)];
      if (!l) return;
      l.weight = v;
      // 手动填的值就是最终值：标记 force，后续自动流程不再夹紧
      l.force = true;
      if (typeof artistLimit === 'function' && v > artistLimit(l.name) + 1e-6) {
        toast('⚠ 权重 ' + v + ' 超过建议上限 ' + artistLimit(l.name) + '，画面可能糊或串色（已补 @NEG_COLORBLEED）', true);
      }
    };
    el.oninput = save; el.onchange = save;
    el.onblur = async () => {
      save();
      const l = S.loras[Number(el.dataset.loraW)];
      if (l && loraCat(l.name) === '画师' && !l.force) {
        try {
          const byChar = {}; const ch = currentCharLora(); if (ch) byChar[ch] = l.weight;
          await api('/api/artist_recipe', { method: 'POST', body: JSON.stringify({ name: l.name, weight: l.weight, byChar }) });
          S.artistRecipes = S.artistRecipes || {};
          S.artistRecipes[l.name] = { weight: l.weight, byChar };
          toast('已记住 ' + shortLoraName(l.name) + ' 的权重 ' + l.weight);
        } catch (e) {}
      }
    };
  });
  $$('[data-lora-del]').forEach(el => el.onclick = () => { S.loras.splice(Number(el.dataset.loraDel), 1); renderLoras(); });
  if (typeof bindArtistHover === 'function') $$('#lora-list [data-lora-name]').forEach(el => bindArtistHover(el, 'auto'));
  // 原做法：加一行，行内下拉自己挑（选项按底模过滤，带分组和悬浮备注）
  $('#lora-add').onclick = () => {
    const lastEmpty = (S.loras || []).some(l => !l.name);
    if (!lastEmpty) { S.loras.push({ name: '', weight: 1 }); renderLoras(); }
    const rows = $$('#lora-list select');
    const last = rows[rows.length - 1];
    if (last) { try { last.focus(); } catch (e) {} }
  };
}

/* ---------- 出图 ---------- */

function applyArtistStrength() {
  const el = $('#artist-strength');
  const mult = el ? Number(el.value) : 1;
  const art = (S.loras || []).find(l => { try { return loraCat(l.name) === '画师'; } catch (e) { return false; } });
  if (!art) { toast('还没有选画师 LoRA，强度会在下次选择时生效'); return; }
  const base = (typeof styleLoraWeight === 'function' ? styleLoraWeight(art.name) : 1);
  const w = Math.round(base * mult * 100) / 100;
  art.weight = w;
  if (typeof artistLimit === 'function' && w > artistLimit(art.name) + 1e-6) {
    toast('⚠ ' + w + ' 超过建议上限 ' + artistLimit(art.name), true);
  }
  renderLoras();
  toast(shortLoraName(art.name) + ' → ' + w + '（' + mult + '×）');
}

const STYLE_TEXT_RE = /soft focus|muted colors|clean anime illustration|soft cel shading|gentle gradient/;

function identityChangeGuard(prev) {
  // 身份档位任何时候都立刻作用到画布，不再要求"必须有权重 ≥0.8 的画师"
  applyIdentityLevel(false);
}

function identityLevel() {
  const el = $('#identity-strength');
  const v = el ? Number(el.value) : 0.5;
  return Number.isFinite(v) ? v : 0.5;
}

function selectedCharCard() {
  const name = (($('#card-sel') || {}).value) || '';
  return (S.cards || []).find(x => x.name === name) || null;
}

// 身份档位落地：0=最小身份词（一个人/女人）、0.5=弱身份文本、1=专有身份积木（未选角色卡时仅保留无 owner 的公开身份积木）
function applyIdentityLevel(silent) {
  if (!S.pos) S.pos = [];
  const lvl = identityLevel();
  const card = selectedCharCard();
  const weakText = (card && card.identity_weak) || (S.gender === 'm' ? TEXT_ID_MALE : TEXT_ID);
  const before = S.pos.length;
  const IDENT_RE = /short dark hair|shoulder-length hair|warm brown eyes/i;

  const keptPublic = !card
    ? S.pos.filter(b => b && !b.cardIdentity && isIdentityToken(b.token) && !tokenOwner(b.token) && !/^@SINGLE/i.test(b.token || '')).map(b => b.token)
    : [];

  // 先把所有"身份痕迹"摘掉：身份积木、身份文本、角色卡特征块、上一次的最小身份词
  S.pos = S.pos.filter(b => {
    if (!b) return false;
    if (b.identityMin || b.cardIdentity) return false;
    if (isIdentityToken(b.token)) return false;
    if (!b.token && IDENT_RE.test(String(b.text || ''))) return false;
    return true;
  });

  if (lvl >= 1) {
    let toks;
    if (card && (card.tokens || []).length) {
      toks = card.tokens.map(resolveToken);
    } else if (card) {
      toks = S.gender === 'm' ? ['@SINGLE_M', '@ID_M'] : ['@SINGLE_F', '@ID_F'];
    } else {
      const baseSolo = S.gender === 'm' ? '@SINGLE_M' : '@SINGLE_F';
      toks = keptPublic.length ? [baseSolo].concat(keptPublic) : (S.gender === 'm' ? ['@SINGLE_M', '@ID_M'] : ['@SINGLE_F']);
    }
    toks.forEach(t => {
      if (t && !S.pos.some(b => b.token === t)) {
        S.pos.unshift({ id: uid(), token: t, text: '', weight: 1, enabled: true, cardIdentity: !!card });
      }
    });
  } else if (lvl > 0) {
    S.pos.unshift({ id: uid(), token: '', text: weakText, weight: lvl, enabled: true, cardIdentity: !!card });
  } else {
    S.pos.unshift({ id: uid(), token: '', text: S.gender === 'm' ? TEXT_ID_MIN_MALE : TEXT_ID_MIN, weight: 1, enabled: true, identityMin: true });
  }

  const changed = before !== S.pos.length ? 1 : 0;
  if (!silent) {
    try { renderLanes(); expandPreview(); } catch (e) {}
    if (lvl >= 1 && !card && S.gender !== 'm' && !keptPublic.length) {
      toast('未选角色卡：仅保留通用 @SINGLE_F（不加载私有身份积木；如需锁角色请先在「角色卡」中选择）');
    } else {
      toast('身份档位：' + (lvl >= 1 ? (card ? '强身份（角色卡专有积木）' : '强身份（公开通用积木）') : lvl > 0 ? '弱身份（文本描述）' : '不锁（最小身份词）'));
    }
  }
  return changed;
}

function artistDilutionGuard() {
  // 画师权重较高时，按“身份强度”决定保留多少 OC 特征（0=交给画师，1=死锁）
  const artist = (S.loras || []).find(l => {
    try { return loraCat(l.name) === '画师' && Number(l.weight) >= 0.8; } catch (e) { return false; }
  });
  if (!artist) return 0;
  const lvl = identityLevel();
  let changed = 0;
  const before = (S.pos || []).length;

  // 画风竞争文本一律移除
  S.pos = S.pos.filter(b => {
    if (b.token) return true;
    const tx = String(b.text || '').toLowerCase();
    if (/soft focus|muted colors|clean anime illustration|soft cel shading|gentle gradient/.test(tx)) { changed++; return false; }
    return true;
  });
  S.pos = S.pos.filter(b => {
    const t = b.token || '';
    if (t.startsWith('@STYLE_')) { changed++; return false; }
    if (lvl < 1 && isIdentityToken(t)) { changed++; return false; }
    return true;
  });

  changed += applyIdentityLevel(true);
  if (changed) {
    // 身份块是"就地替换"：改完必须立刻重绘画布，否则看起来像多了一块隐藏积木
    try { renderLanes(); expandPreview(); } catch (e) {}
    toast('画师模式（身份 ' + lvl + '）：身份块已' + (lvl >= 1 ? '换成身份积木' : (lvl < 1 ? '换成弱身份文本' : '清空')) +
      '（' + before + '→' + S.pos.length + ' 块）');
  }
  return changed;
}

const STYLE_LOCK_APPLY = () => {
  artistDilutionGuard();
  // 只补基础负向 @NEG_BASE；画风/光型/其他负向一律不自动加（2026-11-08）
  if (!S.neg.some(b => b.token === '@NEG_BASE')) {
    S.neg.push({ id: uid(), token: '@NEG_BASE', text: '', weight: 1, enabled: true });
  }
  S.loras = (S.loras || []).map(l => {
    const w = Number(l.weight);
    if (!Number.isFinite(w) || w <= 0) return Object.assign({}, l, { weight: loraDefaultWeight(l.name) });
    return l;
  });
  let loraChanged = false;
  const hLoRas = S.loras.filter(l => isCharLora(l.name));
  if (hLoRas.length > 1) {
    const keep = hLoRas[hLoRas.length - 1];
    S.loras = S.loras.filter(l => !isCharLora(l.name) || l === keep);
    loraChanged = true;
    toast('只保留一个角色 LoRA：' + keep.name);
  }

  if (typeof renderLanes === 'function') renderLanes();
  if (loraChanged && typeof renderLoras === 'function') renderLoras();
};

const IDENT_TRAITS = [
  { key: 'hair', test: /shoulder-length hair|bob cut/i, add: 'shoulder-length hair' }
];
function lostTraits(src, out) {
  return IDENT_TRAITS.filter(t => t.test.test(src || '') && !t.test.test(out || ''));
}

const ID_LORA_GUARD = () => 0;


const STYLE_LORA_GUARD = () => 0;

const FACE_CHIBI_GUARD = () => {
  const hasChibiBody = S.pos.some(b => CHIBI_BODIES.has(b.token));
  const isFaceChibi = b => b.token === '@FACE_FCHIBI' || b.token === '@FACE_CHIBI';
  const faceChibi = S.pos.find(isFaceChibi);
  let changed = 0;
  if (faceChibi && !hasChibiBody) {
    S.pos.splice(S.pos.indexOf(faceChibi), 1);
    const soft = S.tokens['@FACE_FSOFT'] ? '@FACE_FSOFT' : '@FACE_SOFT';
    if (!S.pos.some(b => b.token === '@FACE_FSOFT' || b.token === '@FACE_SOFT')) S.pos.push({ id: uid(), token: soft, text: '', weight: 1, enabled: true });
    toast('单独的 Q 版脸会造成 Q 化，已换回 ' + soft);
    changed++;
  }
  if (hasChibiBody && !S.pos.some(isFaceChibi)) {
    S.pos.push({ id: uid(), token: S.tokens['@FACE_FCHIBI'] ? '@FACE_FCHIBI' : '@FACE_CHIBI', text: '', weight: 1, enabled: true });
    changed++;
  }
  return changed;
};

const SCENE_CAM_WARN = () => {
  const scene = (S.pos.find(b => (b.token || '').startsWith('@SET_')) || {}).token;
  const cam = (S.pos.find(b => (b.token || '').startsWith('@CAM_')) || {}).token;
  if (scene && cam && !sceneCamCompatible(scene, cam)) {
    toast('场景与机位不搭：' + scene + '（' + setScaleOf(scene) + '）配 ' + cam + '，建议换 ' + (sceneScaleKey(scene) === 'large' ? '@CAM_MEDIUM 或 @CAM_FULL' : '@CAM_BUST 或 @CAM_MEDIUM'), true);
    return 1;
  }
  return 0;
};

const CAM_CONFLICT_GUARD = () => {
  const hasSingle = S.pos.some(b => ['@SINGLE', '@SINGLE_F', '@SINGLE_M'].includes(b.token));
  const hasScene = S.pos.some(b => (b.token || '').startsWith('@SET_'));
  const wide = new Set(['@CAM_FULL', '@CAM_MEDIUM']);
  if (hasScene) wide.add('@CAM_THREEQ');
  const bad = S.pos.filter(b => wide.has(b.token));
  if (!hasSingle || !bad.length) return 0;
  S.pos = S.pos.filter(b => !wide.has(b.token));
  toast('构图冲突：@SINGLE 已声明“填满画面”，已移除 ' + bad.map(b => b.token).join('/'));
  return bad.length;
};

const PALE_LORA_WARN = () => 0;

const STYLE_SCENE_WARN = () => {
  const style = S.pos.find(b => /^@STYLE_/.test(b.token || ''));
  const scene = S.pos.some(b => /^@(SET_|BG_)/.test(b.token || ''));
  if (style && scene) toast('提醒：' + style.token + ' 会把场景压成白底，做场景图建议去掉画风积木', true);
  return 0;
};

const ARTIST_LAYOUT_WARN = () => {
  const artist = (S.loras || []).find(l => loraCat(l.name) === '画师');
  if (!artist || Number(artist.weight) < 0.5) return 0;
  const blockers = S.pos.filter(b => isIdentityToken(b.token) || ['@BODY_SOFT', '@BODY_F_SOFT', '@BODY_F', '@BODY_F', '@CAM_CLOSEUP', '@CAM_BUST'].includes(b.token));
  if (blockers.length) toast('画师 ' + shortLoraName(artist.name) + ' 权重 ' + artist.weight + ' 时建议用文本身份，' + blockers.map(b => b.token).join('/') + ' 会压构图', true);
  return 0;
};

async function smartFix() {
  pushHistory();
  let changed = 0;
  const empties = S.pos.filter(b => !b.token && !String(b.text || '').trim());
  if (empties.length) { S.pos = S.pos.filter(b => b.token || String(b.text || '').trim()); changed += empties.length; }
  const seen = new Set();
  S.pos = S.pos.filter(b => { if (!b.token) return true; if (seen.has(b.token)) { changed++; return false; } seen.add(b.token); return true; });
  changed += CAM_CONFLICT_GUARD();
  changed += FACE_CHIBI_GUARD();
  changed += ID_LORA_GUARD();
  changed += STYLE_LORA_GUARD();
  SCENE_CAM_WARN();
  PALE_LORA_WARN();
  STYLE_SCENE_WARN();
  ARTIST_LAYOUT_WARN();
  renderLanes();
  try { await expandPreview(); } catch (e) {}
  toast(changed ? ('已修正 ' + changed + ' 项') : '结构没问题');
  return changed;
}

// 一键修正：规则引擎（/api/fix/blocks），无本地模型
async function fixFlow() {
  const btn = document.querySelector('#btn-smartfix');
  if (btn) btn.classList.add('loading');
  try {
    const blocks = (S.pos || []).map(b => ({ token: b.token || '', text: b.text || '', weight: Number(b.weight) || 1, enabled: b.enabled !== false }));
    const negatives = (S.neg || []).map(b => ({ token: b.token || '', text: b.text || '', weight: 1, enabled: b.enabled !== false }));
    const r = await api('/api/fix/blocks', { method: 'POST', body: JSON.stringify({ blocks, negatives }) });
    const issues = (r && r.issues) || [];
    if (!issues.length) { toast('没有发现需要修正的地方'); return; }
    const laneCN = { positive: '正向', negative: '负向' };
    const rows = issues.map((it, i) =>
      '<label class="fix-row" style="display:flex;gap:8px;align-items:flex-start;margin:6px 0">' +
      '<input type="checkbox" class="fix-pick" data-i="' + i + '" checked style="width:auto;margin-top:3px">' +
      '<span><b>' + esc(it.token || '（文本块）') + '</b><em style="color:#9aa3b2;font-style:normal"> · ' +
      (laneCN[it.lane] || it.lane) + ' · ' + (it.action === 'replace' ? '替换' : '移除') + '</em>' +
      '<br><span class="hint">' + esc(it.reason) + (it.replace ? ' → ' + esc(it.replace) : '') + '</span></span></label>').join('');
    openModal('一键修正 · ' + issues.length + ' 条（规则判断）',
      '<p class="hint">规则引擎逐条判定；勾选后按“移除/替换”执行，取消勾选就保留。</p>' +
      '<div style="max-height:46vh;overflow:auto;margin:8px 0">' + rows + '</div>' +
      '<div class="row2" style="margin-top:10px">' +
      '<button class="primary" id="fix-apply">执行（' + issues.length + '）</button>' +
      '<button class="ghost" id="fix-cancel">取消</button></div>');
    $('#fix-cancel').onclick = closeModal;
    const applyBtn = $('#fix-apply');
    document.querySelectorAll('.fix-pick').forEach(cb => {
      cb.onchange = () => {
        const n = document.querySelectorAll('.fix-pick:checked').length;
        applyBtn.textContent = '执行（' + n + '）';
        applyBtn.disabled = n === 0;
      };
    });
    applyBtn.onclick = () => {
      const chosen = [].slice.call(document.querySelectorAll('.fix-pick'))
        .filter(cb => cb.checked).map(cb => issues[Number(cb.dataset.i)]);
      if (!chosen.length) { closeModal(); return; }
      pushHistory();
      chosen.forEach(it => {
        const tok = it.token || '';
        if (!tok) return;
        const arr = it.lane === 'negative' ? S.neg : S.pos;
        if (it.action === 'replace' && it.replace) {
          (arr || []).forEach(b => { if (b.token === tok) b.token = it.replace; });
        } else {
          if (it.lane === 'negative') S.neg = (S.neg || []).filter(b => b.token !== tok);
          else S.pos = (S.pos || []).filter(b => b.token !== tok);
        }
      });
      try { if (S.coopOn && typeof renderCoopLanes === 'function') renderCoopLanes(); else renderLanes(); } catch (e) {}
      try { expandPreview(); } catch (e) {}
      closeModal();
      toast('已按规则修正 ' + chosen.length + ' 条');
    };
  } catch (e) {
    toast('规则检查失败：' + e.message, true);
  } finally {
    if (btn) btn.classList.remove('loading');
  }
}


const STYLE_TEXT = {
  cel: 'cel shading, flat colors',
  anime: 'anime cel shading, clean lineart',
  flat: 'flat colors, minimal shading',
  water: 'watercolor style, soft pigment bleed',
  line: 'clean lineart, crisp outlines',
};

const TEXT_ID = '1girl, solo, short dark hair, straight fringe, warm brown eyes, calm expression';
// 不锁身份时用的最小身份词：保证还是"一个人"，但不锁 OC 特征
const TEXT_ID_MIN = '1girl, solo, woman';
// 男性版文本身份（通用男性，不含澪的特征）
const TEXT_ID_MALE = '1boy, solo, short black hair, dark brown eyes';
const TEXT_ID_MIN_MALE = '1boy, solo, man';
// 只补画师模型训练 metadata 里的真实触发词，不额外注入互相打架的形容词
const ARTIST_TRIGGERS = {};
function artistTrigger(name) {
  const n = String(name || '');
  const key = Object.keys(ARTIST_TRIGGERS).find(k => n.includes(k));
  return key ? ARTIST_TRIGGERS[key] : '';
}

const ARTIST_NOTES = {};

const ARTIST_DROP_DEFAULT = [];
const GENERIC_ARTIST = { weight: 0.7, drop: ARTIST_DROP_DEFAULT, add: [], textId: true };
const ARTIST_RECIPES = {};
function artistRecipe(name) {
  const n = String(name || '');
  const key = Object.keys(ARTIST_RECIPES).find(k => n.includes(k));
  const base = Object.assign({}, GENERIC_ARTIST, key ? ARTIST_RECIPES[key] : {});
  // 权重单一来源：优先学习值，其次角色默认表，最后 1.0
  const learned = (typeof artistDefaultWeight === 'function') ? artistDefaultWeight(name, currentCharLora()) : null;
  base.weight = (learned != null ? learned : 1.0);
  const ov = (S.artistRecipes || {})[n] || (S.artistRecipes || {})[n.replace('.safetensors', '')];
  if (ov && ov.weight != null) base.weight = ov.weight;
  return base;
}

function isHeavyStyleLora(name) {
  // 只有"画师"类且默认权重要在 0.6 以上时才提示，避免每选一次都弹
  try { return loraCat(name) === '画师'; } catch (e) { return false; }
}

function styleLoraWeight(name) {
  const rec = artistRecipe(name);
  if (rec) return rec.weight;
  if (/turbo/i.test(name)) return 0.75;
  return 0.2;
}

function renderStyleLoraOptions() {
  const sel = document.querySelector('#style-lora');
  if (!sel) return;
  const cur = (S.loras || []).find(l => loraCat(l.name) === '画师');
  // 画师下拉永远按当前底模过滤（以前合作模式下 _anyBase 会放行所有底模，
  // 结果非 Anima 底模混入，选中无法加载）；
  // 同时只要画师类，别把 加速/动作/角色/场景厚涂 混进来
  S._anyBase = false;
  S._artistOnly = true;
  try {
    sel.innerHTML = '<option value="">无</option>' + loraOptionsHtml(cur ? cur.name : '');
  } finally {
    S._anyBase = false;
    S._artistOnly = false;
  }
}

function currentCharLora() {
  const l = (S.loras || []).find(x => loraCat(x.name) === '角色');
  return l ? l.name : '';
}

function applyArtistFree() {
  const sel = document.querySelector('#style-lora');
  const name = sel ? sel.value : '';
  if (!name) { toast('先选一位画师 LoRA', true); return; }
  pushHistory();
  const baseText = S.gender === 'm' ? '1boy, solo' : '1girl, solo';
  const trig = artistTrigger(name);
  S.pos = [{ id: uid(), token: '', text: trig ? (baseText + ', ' + trig) : baseText, weight: 1, enabled: true }];
  S.neg = ['@NEG_BASE'].map(t => ({ id: uid(), token: t, text: '', weight: 1, enabled: true }));
  S.loras = (S.loras || []).filter(l => loraCat(l.name) !== '画师');
  const w = (typeof artistDefaultWeight === 'function' ? artistDefaultWeight(name, currentCharLora()) : null) || 1.0;
  S.loras.push({ name, weight: w });
  renderLoras(); renderLanes(); expandPreview();
  toast('画师自由发挥：' + shortLoraName(name) + ' ' + w + '（画布已简化）');
}

function applyStyleLora(name) {
  pushHistory();
  const prevForced = (S.loras || []).find(l => l.name === name && l.force);
  S.loras = (S.loras || []).filter(l => loraCat(l.name) !== '画师');
  S.pos = S.pos.filter(b => !b.artist);
    if (name) {
    const charName = currentCharLora();
    const learned = (S.artistRecipes || {})[name];
    const w = (learned && learned.byChar && learned.byChar[charName])
      || (typeof artistDefaultWeight === 'function' ? artistDefaultWeight(name, charName) : null)
      || styleLoraWeight(name);
    const mult = Number(($('#artist-strength') || {}).value) || 1;
    const baseW = prevForced ? prevForced.weight : (w * mult);
    S.loras = (S.loras || []).filter(l => l.name !== name);
    S.loras.push({ name, weight: Math.round(baseW * 100) / 100, force: !!prevForced });
    if (typeof artistLimit === 'function' && baseW > artistLimit(name) + 1e-6) {
      toast('⚠ 这次权重 ' + baseW + ' 超过建议上限 ' + artistLimit(name) + '，可能糊或串色', true);
    }
  }
  if (name) {
    const rec = artistRecipe(name);
    if (rec) {
      const removed = [];
      const dropList = identityLevel() >= 1 ? rec.drop.filter(t => !isIdentityToken(t)) : rec.drop;
      const dropIdent = identityLevel() < 1 && rec.drop.some(t => isIdentityToken(t));
      S.pos = S.pos.filter(b => {
        if (dropList.includes(b.token) || (dropIdent && isIdentityToken(b.token))) { removed.push(b.token); return false; }
        return true;
      });
      for (const t of rec.add) if (!S.pos.some(b => b.token === t)) S.pos.push({ id: uid(), token: t, text: '', weight: 1, enabled: true });
      if (rec.textId && identityLevel() > 0 && !S.pos.some(b => !b.token && /shoulder-length hair/i.test(b.text || ''))) {
        S.pos.unshift({ id: uid(), token: '', text: TEXT_ID, weight: 1, enabled: true });
      }
      if (removed.length || rec.add.length) toast('画师适配：' + (removed.length ? '移除 ' + removed.join('/') + ' ' : '') + (rec.add.length ? '补 ' + rec.add.join('/') : ''));
    }
  }
  const trig = name ? artistTrigger(name) : '';
  if (trig && !S.pos.some(b => String(b.text || '').toLowerCase().includes(trig.toLowerCase()))) {
    S.pos.push({ id: uid(), token: '', text: trig, weight: 1, enabled: true, artist: true });
  }
  const note = Object.keys(ARTIST_NOTES).find(k => String(name || '').includes(k));
  saveJSON('loom.styleLora', name || '');
  renderLoras(); renderStyleLoraOptions(); expandPreview();
  const cur = (S.loras || []).find(l => l.name === name);
  toast(name
    ? ('画师 LoRA：' + shortLoraName(name) + ' ' + (cur ? cur.weight : '') + (note ? '｜' + ARTIST_NOTES[note] : ''))
    : '画师 LoRA：无', !!note);
}


/* ---------- 合作模式（coop） ---------- */
function coopFillLoras() {
  const env = document.querySelector('#coop-slora-row #coop-slora');
  if (env) {
    const cur = env.value;
    S._envOnly = true;
    S._anyBase = false;  // 环境画师同样按当前底模过滤
    try { env.innerHTML = loraOptionsHtml(cur); } finally { S._anyBase = false; S._envOnly = false; }
    const list = [].map.call(env.options, o => o.value).filter(Boolean);
    if (!list.includes(cur)) {
      const hit = list.find(f => /painterly|bg_detailer|impasto/i.test(f)) || list[0] || '';
      env.value = hit;
    }
  }
  if (typeof renderStyleLoraOptions === 'function') renderStyleLoraOptions();
  coopSyncWeightInputs();
}

function coopSyncWeightInputs() {
  const envSel = document.querySelector('#coop-slora-row #coop-slora') || $('#coop-slora');
  const charSel = $('#style-lora');
  const ew = $('#coop-env-w');
  const cw = $('#coop-char-w');
  if (ew && !ew.dataset.manual && typeof coopLoraDefaultWeight === 'function') {
    ew.value = coopLoraDefaultWeight(envSel ? envSel.value : '', 'env').toFixed(2);
  }
  if (cw && !cw.dataset.manual && typeof coopLoraDefaultWeight === 'function') {
    cw.value = coopLoraDefaultWeight(charSel ? charSel.value : '', 'char').toFixed(2);
  }
}

let coopTimer = null;
function coopPoll() {
  api('/api/coop/status').then(r => {
    const st = $('#run-status');
    const STATUS_CN = { idle: '就绪', running: '运行中', done: '完成', error: '失败' };
    if (st) st.textContent = (r.status === 'running'
      ? (r.phase || '运行中') + ' · ' + Math.round((r.progress || 0) * 100) + '% · ' + r.elapsed + 's'
      : (STATUS_CN[r.status] || r.status));
    const pct = Math.round((r.progress || 0) * 100) + '%';
    const rb = $('#run-bar'); if (rb) rb.style.width = pct;
    const fl = $('#coop-float'), fbar = $('#coop-float-bar'), fph = $('#coop-float-phase'), fpc = $('#coop-float-pct');
    if (fl) {
      if (r.status === 'running') {
        fl.hidden = false;
        if (fph) fph.textContent = '合作模式 · ' + (r.phase || '运行中');
        if (fpc) fpc.textContent = pct;
        if (fbar) fbar.style.width = pct;
      } else if (r.status === 'done') {
        if (fph) fph.textContent = '合作模式 · 完成';
        if (fpc) fpc.textContent = '100%';
        if (fbar) fbar.style.width = '100%';
        setTimeout(() => { const x = $('#coop-float'); if (x) x.hidden = true; }, 4000);
      } else if (r.status === 'error') {
        if (fph) fph.textContent = '合作模式 · 失败';
        setTimeout(() => { const x = $('#coop-float'); if (x) x.hidden = true; }, 6000);
      }
    }
    if (st && r.status === 'running') st.textContent = '合作模式 · ' + (r.phase || '') + ' · ' + pct;
    if (r.status === 'done' && r.image) {
      if (rb) rb.style.width = '100%';
      if (st) st.textContent = '合作模式 · 完成 · ' + (r.elapsed || 0) + 's';
      if (coopTimer) { clearInterval(coopTimer); coopTimer = null; }
      if (S._coopShownPath !== r.image) {
        S._coopShownPath = r.image;
        const bt = document.querySelector('#tabs button[data-tab=build]');
        if (bt && !bt.classList.contains('active')) bt.click();
        try { showResult([r.image], S._coopSeed || 0, r.elapsed || 0); } catch (e) {}
        const el = $('#result');
        if (el) { const d = el.closest('details'); if (d) d.open = true; try { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (e) {} }
      }
    }
    if (r.status === 'error') {
      if (st) st.textContent = '合作模式 · 失败';

      if (coopTimer) { clearInterval(coopTimer); coopTimer = null; }
    }
  }).catch(() => {});
}


/* 拼装页合作模式：四排积木工作台 */
const COOP_LANES = {
  commonPos: { box: '#coop-common-pos-lane', cnt: '#coop-common-pos-count' },
  commonNeg: { box: '#coop-common-neg-lane', cnt: '#coop-common-neg-count' },
  envPos: { box: '#coop-env-pos-lane', cnt: '#coop-env-pos-count' },
  chrPos: { box: '#coop-chr-pos-lane', cnt: '#coop-chr-pos-count' },
  chrNeg: { box: '#coop-chr-neg-lane', cnt: '#coop-chr-neg-count' }
};

// 分流规则（A 方案）：公共 = 契约层，环境/人物 = 主体层
const SHARED_CATS = ['light', 'cam', 'comp', 'style'];
const ENV_CATS = ['set', 'prop', 'atmo', 'time'];

const CHAR_TEXT = /1girl|1boy|solo|character|she\b|he\b|hair|eyes|dress|skirt|shirt|coat|uniform|breasts|body/i;
const ENV_TEXT = /scenery|background|room|street|forest|sky|wall|window|desk|chair|city|village|indoor|outdoor|rain|snow|fog|storm|night|neon|sunset|sunrise|golden hour|beach|garden|mountain|field|alley|classroom|cafe|bedroom/i;

function negGarmentSet() {
  if (S._negGarmentSet) return S._negGarmentSet;
  const set = new Set();
  Object.keys(S.garments || {}).forEach(k => set.add('@NEG_' + k.toUpperCase()));
  S._negGarmentSet = set;
  return set;
}

function coopBucketFor(b, isNeg) {
  const tok = String((b && b.token) || '');
  const txt = String((b && b.text) || '');
  let cat = 'custom';
  try { cat = tokenCat(tok); } catch (e) {}
  if (isNeg) {
    // 服装配套负向（@NEG_<服装key>）按词库实际服装键判断，别漏 sundress / casual_knit 这类
    if (negGarmentSet().has(tok)) return 'chrNeg';
    if (/^@NEG_(ANATOMY|HANDS|HAND_|SKIN|FACE|MALE|BODY|DRAPE|STRIP|HETEROC|HAIR|HEM|FABRIC|GARMENT|LONGHAIR|ACC_FACE|CHILD|CHIBI|SHOES|SOCKS|THICKHOSE|HOSE)/.test(tok)) return 'chrNeg';
    return 'commonNeg';
  }
  if (tok && SHARED_CATS.includes(cat)) return 'commonPos';
  if (tok && ENV_CATS.includes(cat)) return 'envPos';
  if (tok) return 'chrPos';
  if (ENV_TEXT.test(txt) && !CHAR_TEXT.test(txt)) return 'envPos';
  return 'chrPos';
}

function coopCharCommon(blocks) {
  return (blocks || []).filter(b => {
    const tok = String((b && b.token) || '').toUpperCase();
    const cat = tokenCat(tok);
    if (tok === '@CAM_FULL') return true;
    if (cat === 'comp' || cat === 'cam') return false;
    if (cat === 'atmo' && /bokeh|fog|blur|haze|depth of field/i.test(String((b && b.text) || ''))) return false;
    return true;
  });
}

function coopEnsure() {
  if (!S.coop) S.coop = { commonPos: [], commonNeg: [], envPos: [], chrPos: [], chrNeg: [] };
  return S.coop;
}

function coopSplit() {
  const c = coopEnsure();
  const buckets = { commonPos: [], envPos: [], chrPos: [], commonNeg: [], chrNeg: [] };
  (S.pos || []).forEach(b => buckets[coopBucketFor(b, false)].push(Object.assign({}, b, { id: uid() })));
  (S.neg || []).forEach(b => buckets[coopBucketFor(b, true)].push(Object.assign({}, b, { id: uid() })));
  c.commonPos = buckets.commonPos;
  c.envPos = buckets.envPos;
  c.chrPos = buckets.chrPos;
  c.commonNeg = buckets.commonNeg;
  c.chrNeg = buckets.chrNeg;
  S.coopLastSplit = { commonPos: c.commonPos.length, envPos: c.envPos.length, chrPos: c.chrPos.length,
                      commonNeg: c.commonNeg.length, chrNeg: c.chrNeg.length };
}

function coopChip(b, lane) {
  const label = b.token || '文本';
  const body = b.token ? '<span class="tk">' + b.token + '</span>'
    : '<span class="txt">' + esc(b.text || '（空）') + '</span>';
  const cat = b.token ? tokenCat(b.token) : 'custom';
  return '<div class="chip ' + (lane.endsWith('Pos') ? 'pos' : 'neg') + (b.enabled ? '' : ' off') + '"' +
    ' data-coop-lane="' + lane + '" data-id="' + b.id + '" data-cat="' + cat + '"' +
    (b.token ? ' data-token="' + b.token + '"' : '') + '>' +
    '<span class="grab">⠿</span>' +
    '<button class="on" data-coop-toggle="' + b.id + '" data-coop-lane="' + lane + '">' + (b.enabled ? '●' : '○') + '</button>' +
    body +
    '<input type="number" step="0.05" min="0" max="3" value="' + b.weight + '" data-coop-weight="' + b.id + '" data-coop-lane="' + lane + '">' +
    '<button class="x" data-coop-del="' + b.id + '" data-coop-lane="' + lane + '">×</button>' +
    '</div>';
}

function renderCoopLanes() {
  const c = coopEnsure();
  Object.entries(COOP_LANES).forEach(([lane, cfg]) => {
    const box = $(cfg.box); if (!box) return;
    const arr = c[lane] || [];
    const slotBlk = lane === 'envPos'
      ? arr.find(b => b && /^@SET_/.test(String(b.token || '')))
      : (lane === 'chrPos' && typeof reprojMainGarmentBlock === 'function' ? reprojMainGarmentBlock(arr) : null);
    const visArr = slotBlk ? arr.filter(b => b !== slotBlk) : arr;
    const slotHint = lane === 'envPos'
      ? '主场景已在上方以单独积木显示，此处可继续添加氛围/时段/自定义文本'
      : '主服装已在上方以单独积木显示，此处可继续添加身份/体型/表情/动作等积木';
    box.innerHTML = visArr.map(b => coopChip(b, lane)).join('') || (slotBlk
      ? '<span class="hint">' + slotHint + '</span>'
      : '<span class="hint">点上方 + 文本，或从左侧积木拖进来</span>');
    const cnt = $(cfg.cnt); if (cnt) cnt.textContent = arr.length + ' 块';
    try { if (typeof bindTips === 'function') bindTips(box); } catch (e) {}
    box.querySelectorAll('.chip').forEach(el => {
      el.addEventListener('dblclick', ev => {
        if (ev.target && (ev.target.tagName === 'INPUT' || ev.target.tagName === 'BUTTON')) return;
        const id = el.dataset.id, ln = el.dataset.coopLane;
        const b = (coopEnsure()[ln] || []).find(x => x.id === id);
        if (!b) return;
        if (b.token && typeof openBlockDetail === 'function') openBlockDetail(b, ln.endsWith('Neg') ? 'negative' : 'positive');
        else if (typeof editFreeText === 'function') editFreeText(el);
      });
    });
    if (!box.dataset.dropBound) {
      box.dataset.dropBound = '1';
      box.addEventListener('dragover', e => e.preventDefault());
      box.addEventListener('drop', e => {
        e.preventDefault();
        const raw = e.dataTransfer.getData('text/plain');
        if (!raw) return;
        let d = null; try { d = JSON.parse(raw); } catch (err) { d = null; }
        if (d && d.move) return;
        if (d && d.token && lane === 'envPos' && /^@SET_/.test(d.token) && typeof reprojAddScene === 'function') {
          reprojAddScene(d.token);
          return;
        }
        if (d && d.token && lane === 'chrPos' && typeof reprojIsMainGarmentToken === 'function' && reprojIsMainGarmentToken(d.token)) {
          if (typeof reprojSetGarment === 'function') { reprojSetGarment(d.token); return; }
        }
        const arr2 = coopEnsure()[lane] || (coopEnsure()[lane] = []);
        if (d && d.token) arr2.push({ id: uid(), token: d.token, text: '', weight: 1, enabled: true });
        else if (raw.trim().length > 1) arr2.push({ id: uid(), token: '', text: raw.trim(), weight: 1, enabled: true });
        else return;
        renderCoopLanes(); coopBind(); expandPreview();
      });
    }
  });
  try { if (typeof reprojSyncFromLanes === 'function') reprojSyncFromLanes(); } catch (e) {}
  coopBindChips(document);
}

function coopBindChips(root) {
  const scope = root || document;
  scope.querySelectorAll('[data-coop-del]').forEach(el => {
    el.onclick = ev => {
      ev.stopPropagation();
      const c = coopEnsure(); const lane = el.dataset.coopLane;
      const victim = (c[lane] || []).find(b => b.id === el.dataset.coopDel);
      c[lane] = (c[lane] || []).filter(b => b.id !== el.dataset.coopDel);
      if (lane === 'chrPos' && victim && typeof reprojIsMainGarmentToken === 'function' && reprojIsMainGarmentToken(victim.token)) {
        const negTok = String(victim.token || '').replace(/^@OUT_/, '@NEG_');
        c.chrNeg = (c.chrNeg || []).filter(b => b.token !== negTok);
        if (typeof reprojState === 'function') reprojState().garment = '';
      }
      renderCoopLanes(); coopBind(); expandPreview();
    };
  });
  scope.querySelectorAll('[data-coop-toggle]').forEach(el => {
    el.onclick = ev => {
      ev.stopPropagation();
      const c = coopEnsure(); const lane = el.dataset.coopLane;
      const b = (c[lane] || []).find(x => x.id === el.dataset.coopToggle);
      if (b) { b.enabled = !b.enabled; renderCoopLanes(); coopBind(); expandPreview(); }
    };
  });
  scope.querySelectorAll('[data-coop-weight]').forEach(el => {
    el.onchange = () => {
      const c = coopEnsure(); const lane = el.dataset.coopLane;
      const b = (c[lane] || []).find(x => x.id === el.dataset.coopWeight);
      if (b) { b.weight = Math.max(0, Math.min(3, Number(el.value) || 1)); expandPreview(); }
    };
  });
}

function coopBind() {
  coopBindChips(document);
  document.querySelectorAll('[data-coop-add]').forEach(el => {
    el.onclick = () => {
      const c = coopEnsure(); const lane = el.dataset.coopAdd;
      (c[lane] = c[lane] || []).push({ id: uid(), token: '', text: '', weight: 1, enabled: true });
      renderCoopLanes(); coopBind();
    };
  });
  document.querySelectorAll('[data-coop-clear]').forEach(el => {
    el.onclick = () => {
      const c = coopEnsure(); c[el.dataset.coopClear] = [];
      renderCoopLanes(); coopBind(); expandPreview();
    };
  });
}

function coopToGlobal() {
  const c = coopEnsure();
  const dedupe = arrs => {
    const seen = new Set(), out = [];
    arrs.forEach(arr => (arr || []).forEach(b => {
      if (!b) return;
      const k = b.token ? ('tok:' + b.token) : ('txt:' + (b.text || '').trim() + ':' + b.id);
      if (b.token && seen.has(k)) return;
      if (b.token) seen.add(k);
      out.push(Object.assign({}, b));
    }));
    return out;
  };
  S.pos = dedupe([c.commonPos, c.envPos, c.chrPos]);
  S.neg = dedupe([c.commonNeg, c.chrNeg]);
}

function coopSyncLoras(on) {
  const envSel = document.querySelector('#coop-slora-row #coop-slora') || $('#coop-slora');
  const envName = envSel ? envSel.value : '';
  if (on) {
    S._coopLoraBackup = JSON.parse(JSON.stringify(S.loras || []));
    if (envName && !(S.loras || []).some(l => l.coop === 'env')) {
      const ew = (typeof coopLoraDefaultWeight === 'function') ? coopLoraDefaultWeight(envName, 'env') : 0.70;
      (S.loras = S.loras || []).push({ name: envName, weight: ew, coop: 'env' });
    }
  } else {
    S.loras = (S.loras || []).filter(l => l.coop !== 'env');
    if (S._coopLoraBackup) { S.loras = S._coopLoraBackup; S._coopLoraBackup = null; }
  }
  if (typeof renderLoras === 'function') renderLoras();
}

function coopAfterGlobalEdit() {
  if (!S.coopOn) return;
  coopSplit();
  renderCoopLanes();
  coopBind();
  expandPreview();
}

function coopToggle() {
  const wb = $('#coop-workbench');
  const on = wb.hasAttribute('hidden');
  if (on) wb.removeAttribute('hidden'); else wb.setAttribute('hidden', '');
  S.coopOn = on;
  $$('.lane.card[data-lane]').forEach(c => { c.style.display = on ? 'none' : ''; });
  const panel = $('#coop-panel'); if (panel) panel.open = false;
  const envSel = $('#coop-slora-row'); if (envSel) envSel.hidden = !on;
  const mf = $('#p-model-field'); if (mf) mf.hidden = on;
  const af = $('#p-artist-field'); if (af) af.hidden = on;
  if (on) { coopSplit(); renderCoopLanes(); coopBind(); coopFillLoras(); }
  coopSyncLoras(on);
  expandPreview();
  const btn = $('#coop-toggle');
  if (btn) btn.classList.toggle('on', on);
  if (typeof coopAdvApply === 'function') coopAdvApply();
  saveJSON('loom.coopOn', on);
  toast(on ? '合作模式：四排工作台已切换' : '已回到常规拼装');
}

function coopPromptOf(lane) {
  const c = coopEnsure();
  const arr = (c[lane] || []).filter(b => b.enabled !== false);
  return { positive: lane.endsWith('Pos') ? arr : [], negative: [] };
}

function coopLightFromBlocks() {
  const c = coopEnsure();
  const toks = (c.commonPos || []).concat(c.envPos || []).map(b => String(b.token || '')).join(' ');
  if (/@LIGHT_BACK/.test(toks)) return 'back';
  if (/@LIGHT_TOP/.test(toks)) return 'top';
  return 'left';
}

// 重映工作台只用到少量通用参数
function coopAdvApply() {
  const sel = $('#coop-mode');
  if (!sel) return;
  const m = sel.value;
  const coop = !!S.coopOn;
  const panel = $('#coop-panel');
  if (panel) panel.style.display = coop ? '' : 'none';
  const show = (id, on) => { const el = $('#' + id); if (el) el.style.display = on ? '' : 'none'; };
  show('coop-regional-fields', coop && m === 'regional');
  show('coop-paper-fields', coop && m === 'paper');
  show('coop-painter-fields', coop && m === 'b2');
  show('coop-sketch-field', coop && (m === 'b2' || m === 'gen' || m === 'sketch' || m === 'classic'));
}

// 细化环境：勾选就往画布补一条环境细节积木，取消就摘掉（带 envdetail 标记便于定位）
const ENV_DETAIL_TEXT = 'detailed background, rich surface textures and environment details, clear atmospheric depth';
function bindEnvDetail() {
  const chk = $('#p-envdetail');
  if (!chk) return;
  let migrated = false;
  [S.pos || [], (S.coop && S.coop.envPos) || []].forEach(arr => arr.forEach(b => {
    if (b && b.envdetail && b.text !== ENV_DETAIL_TEXT) { b.text = ENV_DETAIL_TEXT; migrated = true; }
  }));
  if (migrated) {
    try { if (S.coopOn && typeof renderCoopLanes === 'function') renderCoopLanes(); else renderLanes(); expandPreview(); } catch (e) {}
  }
  const lane = () => (S.coopOn ? (coopEnsure().envPos = coopEnsure().envPos || []) : (S.pos = S.pos || []));
  const has = () => {
    if (S.coopOn) return (coopEnsure().envPos || []).some(b => b && b.envdetail);
    return (S.pos || []).some(b => b && b.envdetail);
  };
  const apply = () => {
    const on = !!chk.checked;
    if (on && !has()) {
      lane().push({ id: uid(), token: '', text: ENV_DETAIL_TEXT, weight: 1, enabled: true, envdetail: true });
    } else if (!on && has()) {
      if (S.coopOn) coopEnsure().envPos = (coopEnsure().envPos || []).filter(b => !(b && b.envdetail));
      else S.pos = (S.pos || []).filter(b => !(b && b.envdetail));
    } else return;
    try { if (S.coopOn && typeof renderCoopLanes === 'function') renderCoopLanes(); else renderLanes(); expandPreview(); } catch (e) {}
    saveJSON('loom.envDetail', on);
  };
  chk.onchange = apply;
  try { if (loadJSON('loom.envDetail', false) && !has()) { chk.checked = true; apply(); } } catch (e) {}
}

function coopRegionalBind() {
  const sel = $('#coop-mode');
  if (!sel) return;
  if (!sel._advBound) { sel._advBound = true; sel.addEventListener('change', coopAdvApply); }
  // 工作台参数按需展开
  const panel = $('#coop-panel');
  if (panel && !panel._advBound) {
    panel._advBound = true;
    panel.removeAttribute('open');
    panel.addEventListener('toggle', () => { if (panel.open) coopAdvApply(); });
  }
  coopAdvApply();
}

function coopAutoBind() {
  const chk = $('#coop-auto');
  if (!chk) return;
  const apply = () => {
    const on = !!chk.checked;
    ['#coop-ratio'].forEach(sel => {
      const el = $(sel); if (el) { el.disabled = on; el.style.opacity = on ? 0.5 : 1; }
    });
  };
  chk.onchange = apply;
  apply();
}

const COMP_FIGURE_RATIO = {
  '@COMP_FIGURE_1_3': 0.33, '@COMP_FIGURE_1_4': 0.25, '@COMP_FIGURE_1_5': 0.20,
  '@COMP_FIGURE_1_7': 0.14, '@COMP_FIGURE_1_10': 0.10,
  '@COMP_FIGURE_SMALL': 0.20, '@COMP_FIGURE_BOTTOM': 0.24, '@COMP_FIGURE_EDGE': 0.26
};

function coopComposeFromBlocks(fallbackRatio) {
  const c = coopEnsure();
  const toks = (c.commonPos || []).concat(c.envPos || [], c.chrPos || []).map(b => String(b.token || ''));
  const has = t => toks.includes(t);
  let ratio = fallbackRatio;
  for (const [t, v] of Object.entries(COMP_FIGURE_RATIO)) { if (has(t)) { ratio = v; break; } }
  let ground = 0.88, x = 0.34;
  if (has('@COMP_FIGURE_BOTTOM')) ground = 0.94;
  else if (has('@COMP_LOW')) ground = 0.86;
  else if (has('@COMP_OVERHEAD')) ground = 0.72;
  if (has('@COMP_CENTER') || has('@COMP_SYMMETRY')) x = 0.5;
  else if (has('@COMP_THIRDS')) x = 0.34;
  if (has('@COMP_FIGURE_EDGE')) x = 0.16;
  const byBlocks = toks.some(t => CT_COMP_RE.test(t));
  if (!byBlocks) ratio = fallbackRatio || 0.34;
  return { ratio: Math.round(ratio * 1000) / 1000, ground_y: ground, x: x,
           byBlocks: byBlocks };
}

const CT_COMP_RE = /^@COMP_/;

function coopSeedValue() {
  const raw = (($('#p-seed') || {}).value || '').trim();
  const n = Number(raw);
  if (raw && Number.isFinite(n) && n > 0) return n;
  return Math.floor(Math.random() * 900000) + 100000;
}

function coopPlanRender(by) {
  // 2026-11-15：合作模式固定为重映，旧的 regional/paper/b2 名称不再显示
  const txt = '重映 · 出板 → 人物重绘 → 修脸修手' + (by ? ' · ' + by : '');
  const el = $('#coop-plan');
  if (el) el.innerHTML = '<div class="coop-plan-main">' + txt + '</div>';
  const bi = $('#brain-coop-plan');
  if (bi) bi.innerHTML = txt;
  const inline = $('#coop-plan-inline');
  if (inline) inline.textContent = '出板 → 重绘 → 精修';
}

async function coopApplyRoute() {
  // 2026-11-15：本地模型已移除，构图比例用规则推算（默认环境 66% / 人物 34%，env=0.70 / char=0.85）
  const presetRatio = Number(($('#coop-ratio') || {}).value) || 0.34;
  const plan = coopComposeFromBlocks(presetRatio);
  const envLora = (($('#coop-slora') || {}).value) || '';
  const charLora = (($('#style-lora') || {}).value) || '';
  const defEnvW = (typeof coopLoraDefaultWeight === 'function') ? coopLoraDefaultWeight(envLora, 'env') : 0.70;
  const defCharW = (typeof coopLoraDefaultWeight === 'function') ? coopLoraDefaultWeight(charLora, 'char') : 0.85;
  S._coopRoute = {
    ratio: plan.ratio,
    env_w: Number(($('#coop-env-w') || {}).value) || defEnvW,
    char_w: Number(($('#coop-char-w') || {}).value) || defCharW,
    env_lora: envLora,
    char_lora: charLora,
    by: '规则'
  };
  try { coopPlanRender('规则'); } catch (e) {}
}

function coopStart() {
  const st = $('#run-status'); if (st) st.textContent = '重映 · 准备构图…';
  coopApplyRoute().then(() => coopStartReal()).catch(() => coopStartReal());
}

function coopStartReal() {
  const _rb0 = $('#run-bar'); if (_rb0) _rb0.style.width = '0%';
  const _rs0 = $('#run-status'); if (_rs0) _rs0.textContent = '合作模式 · 启动中…';
  S._coopJustStarted = Date.now();
  if (coopTimer) clearInterval(coopTimer);
  coopTimer = setInterval(coopPoll, 2000);
  coopPoll();
  const c = coopEnsure();
  const manual = Number(($('#coop-ratio') || {}).value) || 0.34;
  const CT_PLAN = coopComposeFromBlocks(manual);
  const call = (pos, neg) => api('/api/expand', { method: 'POST', body: JSON.stringify({ positive: pos, negative: neg }) });
  const merge = (a, b) => {
    const seen = new Set(), out = [];
    (a || []).concat(b || []).forEach(x => {
      const k = (x.enabled === false ? 'off|' : '') + (x.token || ('txt:' + (x.text || '')));
      if (seen.has(k)) return;
      seen.add(k); out.push(x);
    });
    return out;
  };
  const cpos = c.commonPos || [], cneg = c.commonNeg || [];
  const rawChr = (c.chrPos || []).slice();
  const blocks = rawChr.length
    ? rawChr
    : [{ id: uid(), token: '', text: '1girl, solo, full body standing', weight: 1, enabled: true }];
  const facePicked = rawChr.filter(b => /^@(ID|SINGLE|FACE|HAIR|ACC|MOOD|GAZE|POSE|INTERACT)/i.test(String(b.token || '')) || (!b.token && String(b.text || '').trim()));
  const handPicked = rawChr.concat(c.envPos || []).filter(b => /^@(HAND|HOLD|WEAPON|INSTR)/i.test(String(b.token || '')));
  const allNeg = merge(cneg, c.chrNeg);
  Promise.all([
    call(merge(cpos, c.envPos), cneg),
    call(merge(merge(coopCharCommon(cpos), blocks), reprojExtraChar()), allNeg),
    facePicked.length ? call(merge(coopCharCommon(cpos), facePicked), allNeg) : Promise.resolve({ positive: '' }),
    handPicked.length ? call(handPicked, allNeg) : Promise.resolve({ positive: '' })
  ]).then(([env, chr, faceExp, handExp]) => {
    const sz = (typeof size === 'function') ? size() : { w: 1216, h: 832 };
    const charLoraVal = ($('#style-lora') || {}).value || '';
    const sceneLoraVal = (document.querySelector('#coop-slora-row #coop-slora') || $('#coop-slora') || {}).value || '';
    const extraLoras = (S.loras || [])
      .filter(l => l && l.name && !l.coop && l.name !== charLoraVal && l.name !== sceneLoraVal)
      .map(l => ({ name: l.name, weight: Number(l.weight) || 1.0 }));
    const charTrig = artistTrigger(charLoraVal);
    const withTrig = (t) => (charTrig && t && !t.toLowerCase().includes(charTrig.toLowerCase())) ? (t + ', ' + charTrig) : t;
    const body = {
      prompt_scene: env.positive || '',
      prompt_char: withTrig(chr.positive || ''),
      neg_scene: env.negative || '',
      neg_char: chr.negative || '',
      face_prompt: withTrig((faceExp && faceExp.positive) || ''),
      hand_prompt: (handExp && handExp.positive) || '',
      width: sz.w || 1216,
      height: sz.h || 832,
      steps: Number(($('#p-steps') || {}).value) || 28,
      cfg: Number(($('#p-cfg') || {}).value) || 5.5,
      scene_lora: (document.querySelector('#coop-slora-row #coop-slora') || $('#coop-slora') || {}).value || '',
      char_lora: charLoraVal,
      extra_loras: extraLoras,
      ratio: CT_PLAN.ratio,
      ground_y: CT_PLAN.ground_y,
      x: CT_PLAN.x,
      light: coopLightFromBlocks(),
      seed: S._coopSeed = coopSeedValue(),
      mode: 'reproject',
      pipeline: ($('#coop-pipeline') || {}).value || 'a',
      bg_painter: ($('#coop-bg-painter') || {}).value || 'anima',
      char_painter: ($('#coop-char-painter') || {}).value || 'anima',
      env_weight: Number(($('#coop-env-w') || {}).value) || ((typeof coopLoraDefaultWeight === 'function') ? coopLoraDefaultWeight((document.querySelector('#coop-slora-row #coop-slora') || $('#coop-slora') || {}).value || '', 'env') : 0.70),
      char_weight: Number(($('#coop-char-w') || {}).value) || ((typeof coopLoraDefaultWeight === 'function') ? coopLoraDefaultWeight(charLoraVal, 'char') : 0.85),
      ll_strength: Number(($('#coop-ll-strength') || {}).value) || 1.0,
      ll_end: Number(($('#coop-ll-end') || {}).value) || 0.55,
      fg: ($('#coop-fg') || {}).value || '',
      prop: ($('#coop-prop') || {}).value || '',
      footwear: ($('#coop-footwear') || {}).value || '',
      scale_bias: Number(($('#coop-scale-bias') || {}).value) || 1.12,
      char_size: ($('#coop-char-size') || {}).value || '1024x1536',
      shot: ($('#coop-shot') || {}).value || 'auto',
      priority: ($('#coop-priority') || {}).value || 'auto',
      detail: ($('#coop-detail') || {}).value || 'rich',
      sketch: ($('#coop-sketch') || {}).value || '',
      auto_compose: true,
      keep_intermediates: !!($('#coop-keep-mid') && $('#coop-keep-mid').checked),
      expand_notes: [].concat((env && env.notes) || [], (chr && chr.notes) || [], (faceExp && faceExp.notes) || [], (handExp && handExp.notes) || []),
      client_meta: (typeof window.loomClientMeta === 'function') ? window.loomClientMeta() : {}
    };
    return api('/api/coop', { method: 'POST', body: JSON.stringify(body) });
  }).then(r => {
    if (!r || !r.ok) { toast((r && r.note) || '合作模式忙'); return; }
    if (r.hint) {
      const set = (sel, v) => { const el = $(sel); if (el) el.value = v; };
      set('#coop-ratio', r.ratio); set('#coop-gy', r.ground_y); set('#coop-x', r.x);
      toast('构图：高度 ' + r.ratio + ' · 脚底 ' + r.ground_y + ' · 左右 ' + r.x + '（' + '规则' + '）');
    }
    toast('合作模式已启动：出板 → 人物重绘 → 修脸修手');
    if (coopTimer) clearInterval(coopTimer);
    coopTimer = setInterval(coopPoll, 3000);
    coopPoll();
  }).catch(() => toast('合作模式启动失败', true));
}

function applyStyle(kind, custom) {
  pushHistory();
  S.pos = S.pos.filter(b => !/^@STYLE_/.test(b.token || ''));
  let label = '默认';
  if (kind === 'custom') {
    const t = String(custom || '').trim();
    if (t) { S.pos.push({ id: uid(), token: '', text: t, weight: 1, enabled: true }); label = t.slice(0, 24); }
  } else if (typeof STYLE_TEXT !== 'undefined' && STYLE_TEXT[kind]) {
    S.pos.push({ id: uid(), token: '', text: STYLE_TEXT[kind], weight: 1, enabled: true });
    label = kind;
  }
  saveJSON('loom.style', { kind, custom: custom || '' });
  renderLoras(); renderLanes(); expandPreview();
  toast('风格已切到：' + label);
}

function restoreStyle() {
  const v = loadJSON('loom.style', null);
  if (!v || !v.kind) return;
  const sel = $('#style-sel'); if (sel) sel.value = v.kind;
  const inp = $('#style-custom'); if (inp) { inp.value = v.custom || ''; inp.style.display = v.kind === 'custom' ? '' : 'none'; }
}

async function run() {
  S._refined = false;
  STYLE_LOCK_APPLY();
  if (($('#p-smartfix') || {}).checked) { try { await smartFix(); } catch (e) {} }
  try { await expandPreview(); } catch (e) {}
  const _hasText = S.pos.some(b => !b.token && (b.text || '').trim());
  const _hasStyleTok = S.pos.some(b => /^@(STYLE|LIGHT)_/.test(b.token || ''));
  if (_hasText && _hasStyleTok) toast('提示：自然语言文本块与 @STYLE_/@LIGHT_ 混用容易出怪图，建议只留一种', true);
  const _steps = Number(($('#p-steps') || {}).value) || 0;
  if (_steps && _steps < 22) toast('步数 ' + _steps + ' 偏低：16 步左右会明显发灰，正式出图建议 ≥26', true);
  const _mdl = (($('#p-model') || {}).value || '');
  if (!S.lastExpanded || !S.lastExpanded.positive.trim()) { alert('正向提示词为空'); return; }
  const { w, h } = size();
  const risk = sizeRisk(w, h);
  if (risk === 'bad' && !confirm('当前 ' + w + '×' + h + ' (' + (w * h / 1e6).toFixed(2) + ' MP) 很可能爆显存，继续吗？')) return;
  if (risk === 'warn') toast('⚠ 分辨率接近显存上限，留意 OOM');
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
      loras: S.loras.filter(l => l.name).map(l => ({ name: l.name, weight: Number(l.weight) })),
      model: (($('#p-model') || {}).value || ''),
      blocks_pos: S.pos.map(b => ({ token: b.token || '', text: b.text || '', weight: Number(b.weight) || 1, enabled: b.enabled !== false })),
      blocks_neg: S.neg.map(b => ({ token: b.token || '', text: b.text || '', weight: Number(b.weight) || 1, enabled: b.enabled !== false })),
      expand_notes: (S.lastExpanded && S.lastExpanded.notes) || [],
      auto_handfix: Boolean(($('#p-handfix') || {}).checked),
      client_meta: (typeof window.loomClientMeta === 'function') ? window.loomClientMeta() : {}
    })});
    S.last = { job: r.job_id, seed: r.seed };
    $('#run-status').textContent = '排队中 · seed ' + r.seed + ' · 预计 ' + r.estimate + ' 秒';
    pollJob(r.job_id, 'run');
  } catch (e) {
    $('#run-btn').disabled = false;
    $('#run-status').textContent = '失败：' + e.message;
  }
}

const autoRefine = () => Number(($('#p-refine') || {}).value) || 0;
// 刷新后恢复：把还在跑的任务接回来（普通出图/精修/批量 + 合作模式）
async function resumeLastJob() {
  let rec = null;
  try { rec = loadJSON('loom.lastJob', null); } catch (e) {}
  if (rec && rec.id && (Date.now() - (rec.ts || 0) < 6 * 3600 * 1000)) {
    let j = null;
    try { j = await api('/api/job/' + encodeURIComponent(rec.id)); } catch (e) { j = null; }
    const st = $('#run-status'), bar = $('#run-bar'), btn = $('#run-btn');
    if (j && (j.status === 'running' || j.status === 'queued' || j.status === 'pending')) {
      if (st) st.textContent = '恢复中：任务还在跑（' + (rec.kind === 'train' ? '训练' : rec.kind === 'tag' ? '打标' : '出图') + '）';
      if (bar) bar.style.width = Math.round((j.progress || 0) * 100) + '%';
      if (btn) btn.disabled = true;
      pollJob(rec.id, rec.kind || 'run');
    } else if (j && j.status === 'done') {
      if (st) st.textContent = '上次任务已完成';
      if (bar) bar.style.width = '100%';
      saveJSON('loom.lastJob', null);
    } else {
      try { saveJSON('loom.lastJob', null); } catch (e) {}
    }
  }
  // 合作模式有独立的进度轮询
  try {
    const cs = await api('/api/coop/status');
    if (cs && cs.status === 'running') {
      const fl = $('#coop-float');
      if (fl) fl.hidden = false;
      if (!coopTimer) { coopTimer = setInterval(coopPoll, 2000); coopPoll(); }
    }
  } catch (e) {}
}

async function pollJob(jid, kind) {
  clearInterval(S.jobTimer);
  // 刷新页面也能续上进度条：记住这个任务
  try { saveJSON('loom.lastJob', { id: jid, kind: kind, ts: Date.now() }); } catch (e) {}
  S.jobTimer = setInterval(async () => {
    let j;
    try { j = await api('/api/job/' + jid); } catch (e) { return; }
    if (kind === 'run') {
      const _pct = Math.round((j.progress || 0) * 100) + '%';
  $('#run-bar').style.width = _pct;
  const _fl = $('#coop-float');
  if (_fl) {
    _fl.hidden = false;
    const _ph = $('#coop-float-phase'), _pc = $('#coop-float-pct'), _pb = $('#coop-float-bar');
    if (_ph) _ph.textContent = '出图 · 生成中';
    if (_pc) _pc.textContent = _pct;
    if (_pb) _pb.style.width = _pct;
  }
      const pct = Math.round((j.progress || 0) * 100);
      const left = Math.max(0, Math.round((S.eta || 60) - (j.elapsed || 0)));
      const tail = left > 0 ? ('约剩 ' + left + 's') : '收尾中';
      $('#run-status').textContent = (j.status === 'running' ? '生成中 ' + (j.elapsed||0) + 's · ' + tail : j.status) + ' · ' + pct + '%';
    }
    if (j.logs && j.logs.length) {
      if (kind === 'train') $('#tr-log').textContent = j.logs.join('\n');
      if (kind === 'tag') $('#tg-log').textContent = j.logs.join('\n');
    }
    if (j.status === 'done' || j.status === 'error' || j.status === 'cancelled') {
      clearInterval(S.jobTimer);
      try { saveJSON('loom.lastJob', null); } catch (e) {}
      if (kind === 'run') {
        $('#run-btn').disabled = false;
        if (j.status === 'done' && j.result && j.result.images && j.result.images.length) {
          const _rf = autoRefine();
          if (_rf > 0 && !S._refined) {
            S._refined = true;
            const _src = j.result.images[0];
            $('#run-status').textContent = '精修中…';
            try {
              const _rec = await api('/api/recipe?path=' + encodeURIComponent(_src));
              const _r = await api('/api/reproduce', { method: 'POST', body: JSON.stringify({
                mode: 'keep_person', reference: _src, prompt: _rec.positive || '', negative: _rec.negative || '',
                denoise: _rf, width: (_rec.size && _rec.size[0]) || 1024, height: (_rec.size && _rec.size[1]) || 1536,
                steps: _rec.steps || 26, cfg: _rec.cfg || 5.2, seed: _rec.seed || 0, prefix: 'refine', loras: _rec.loras || [], model: _rec.model || (($('#p-model') || {}).value || '') }) });
              if (_r.job_id) { pollJob(_r.job_id, 'run'); return; }
            } catch (e) { toast('精修失败，用原图：' + e.message, true); }
          }
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

function showResult(input, seed, elapsed) {
  const list = Array.isArray(input) ? input.slice() : [input];
  S.rl = list; S.ri = 0;
  renderResultView(seed, elapsed);
}

function refreshRecipesIfVisible() {
  const tab = document.querySelector('#tabs button.active');
  if (tab && tab.dataset.tab === 'recipe') loadRecipes();
}

function renderResultView(seed, elapsed) {
  const list = S.rl || [];
  const path = list[S.ri] || '';
  const { w, h } = size();
  const square = Math.abs(w - h) < 4;
  const multi = list.length > 1;
  S.lastResultPath = path;
  $('#result').innerHTML =
    '<div class="result-frame">' +
    '<img class="clickable" id="result-img" src="/api/img?path=' + encodeURIComponent(path) + '">' +
    (multi ? '<button class="rnav prev" id="r-prev" title="上一张">‹</button><button class="rnav next" id="r-next" title="下一张">›</button><span class="rcount">' + (S.ri + 1) + ' / ' + list.length + '</span>' : '') +
    '</div>' +
    (square ? '<div class="warn">方图更容易出双人分屏；若出现两个人物，建议换 1024×1536 或点「重抽」。</div>' : '') +
    '<div class="logbar">' +
    '<input id="log-note" placeholder="备注（可空，例如：外套长度对）">' +
    '<div class="verdicts"><button data-v="A">A</button><button data-v="B">B</button><button data-v="C">C</button></div></div>' +
    '<div class="row2" style="margin-top:6px"><button class="ghost" id="rerun">重抽</button><button class="ghost" id="open-file">画廊</button></div>' +
    '<div class="row2" style="margin-top:6px"><button class="primary" id="result-refine">精修</button><button class="ghost danger" id="result-del">删除</button></div>' +
    '<div class="row2" style="margin-top:6px"><button class="ghost" id="handfix-btn">手部精修</button><button class="ghost" id="standee-btn" title="全身 + 右上放大淡化的半身（立绘模板）">立绘模板</button></div>' +
    '<div class="row2" style="margin-top:6px"><button class="ghost" id="repro-btn">复现</button><button class="ghost" id="batch-btn">批量</button></div>' +
    '<div class="row2" style="margin-top:6px"><button class="ghost" id="params-btn">参数</button></div>' +
    '<div class="hint">seed ' + seed + ' · ' + elapsed + 's · ' + String(path).split(/[\\/]/).pop() + '</div>';
  const ri = $('#result-img');
  if (ri) ri.onclick = () => openImage(path);
  const pv = $('#r-prev'), nx = $('#r-next');
  if (pv) pv.onclick = () => { S.ri = (S.ri - 1 + list.length) % list.length; renderResultView(seed, elapsed); };
  if (nx) nx.onclick = () => { S.ri = (S.ri + 1) % list.length; renderResultView(seed, elapsed); };
  $$('#result .verdicts button').forEach(b => b.onclick = () => { logPick(path, b.dataset.v, ($('#log-note') || {}).value || ''); });
  $('#rerun').onclick = () => { $('#p-seed').value = ''; run(); };
  const hb = $('#handfix-btn');
  if (hb) hb.onclick = () => openHandfix(path);
  const sd = $('#standee-btn');
  if (sd) sd.onclick = async () => {
    sd.disabled = true; sd.textContent = '合成中…';
    try {
      const r = await api('/api/standee', { method: 'POST', body: JSON.stringify({ path, fade: 0.62 }) });
      if (!r || !r.ok) { toast('立绘模板失败', true); return; }
      S.rl = (S.rl || []).concat([r.path]);
      S.ri = S.rl.length - 1;
      renderResultView(seed, elapsed);
      toast('立绘模板已生成');
    } catch (e) { toast('立绘模板失败：' + e.message, true); }
    finally { sd.disabled = false; sd.textContent = '立绘模板'; }
  };
  const rb = $('#repro-btn');
  if (rb) rb.onclick = () => openReproPage(path);
  const bb = $('#batch-btn');
  if (bb) bb.onclick = () => openBatch();
  const pb = $('#params-btn');
  if (pb) pb.onclick = () => openRecipe(path);
  const rf = $('#result-refine');
  if (rf) rf.onclick = () => refineImage(path);
  const rd = $('#result-del');
  if (rd) rd.onclick = async () => { if (await deleteImage(path)) { S.rl = (S.rl || []).filter(x => x !== path); if (S.rl.length) { S.ri = Math.min(S.ri, S.rl.length - 1); renderResultView(seed, elapsed); } else { $('#result').innerHTML = '<div class="hint">已删除，画布还在，可以重抽。</div>'; } renderGallery(); } };
  $('#open-file').onclick = () => { const a = document.querySelector('#tabs button[data-tab="gallery"]'); if (a) a.click(); };
}

async function refineImage(path) {
  const v = prompt('精修强度（0.2–0.45，建议 0.3）', '0.3');
  if (v === null) return;
  try {
    let rec = null;
    try { rec = await api('/api/recipe?path=' + encodeURIComponent(path)); } catch (e) { rec = null; }
    const sz = size();
    const ex = S.lastExpanded || {};
    const payload = {
      mode: 'keep_person', reference: path,
      prompt: (rec && rec.positive) || ex.positive || '',
      negative: (rec && rec.negative) || ex.negative || '',
      denoise: Math.max(0.1, Math.min(0.6, parseFloat(v) || 0.3)),
      width: (rec && rec.size && rec.size[0]) || sz.w,
      height: (rec && rec.size && rec.size[1]) || sz.h,
      steps: (rec && rec.steps) || Number($('#p-steps').value) || 26,
      cfg: (rec && rec.cfg) || Number($('#p-cfg').value) || 5.2,
      seed: (rec && rec.seed) || 0, prefix: 'refine',
      loras: (rec && rec.loras && rec.loras.length) ? rec.loras : S.loras,
      model: (rec && rec.model) || (($('#p-model') || {}).value || '')
    };
    const r = await api('/api/reproduce', { method: 'POST', body: JSON.stringify(payload) });
    toast('精修已提交');
    $('#run-bar').style.width = '2%';
    $('#run-status').textContent = '精修排队中…';
    const t = setInterval(async () => {
      let j; try { j = await api('/api/job/' + r.job_id); } catch (e) { return; }
      const pct = Math.round((j.progress || 0) * 100);
      $('#run-bar').style.width = pct + '%';
      const el = j.elapsed || 0;
      $('#run-status').textContent = (j.status === 'running' ? '精修中 ' + el + 's' : j.status) + ' · ' + pct + '%';
      if (j.status === 'running') return;
      clearInterval(t);
      $('#run-bar').style.width = '100%';
      if (j.status === 'done' && j.result && j.result.images && j.result.images.length) {
        const img = j.result.images[0];
        S.rl = (S.rl || []).concat([img]); S.ri = S.rl.length - 1;
        renderResultView(j.result.seed, j.result.elapsed);
        $('#run-status').textContent = '精修完成 · ' + (j.result.elapsed || 0) + 's';
        toast('精修完成');
      } else { $('#run-status').textContent = '精修失败'; toast('精修失败', true); }
    }, 1500);
  } catch (e) { toast('精修失败：' + e.message, true); }
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
let _gallerySeq = 0;
async function renderGallery() {
  const seq = ++_gallerySeq;
  const host = $('#gallery');
  // 首次进入时给个占位，别让画布一片黑
  if (host && !host.querySelector('.g-item, .hint')) host.innerHTML = '<div class="hint">加载中…</div>';
  const dir = $('#g-dir').value;
  const r = await api('/api/gallery?dir=' + encodeURIComponent(dir) + '&limit=0');
  if (seq !== _gallerySeq) return;   // 期间又触发了一次渲染，丢弃这次结果
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

  const selMode = !!S.gallerySelect || !!S.galleryDelMode;
  const total = $('#g-total');
  if (total) total.textContent = items.length + ' / ' + r.total + ' 张';

  $('#gallery').innerHTML = items.map(it => {
    const on = S.gallerySel[it.path] ? ' on' : '';
    return '<div class="g-item' + on + '" data-path="' + it.path + '">'
      + '<img loading="lazy" src="/api/img?path=' + encodeURIComponent(it.path) + '">'
      + (it.verdict ? '<span class="v ' + it.verdict + '">' + it.verdict + '</span>' : '')
      + (selMode ? '<span class="g-check">' + (S.gallerySel[it.path] ? '✓' : '') + '</span>' : '')
      + '<button class="g-params" data-params="' + it.path + '" title="查看这张图的积木与参数">参数</button>'

      + '<div class="meta"><span>' + (it.label || it.name).slice(0, 28) + '</span><span>' + (it.note || '') + '</span></div>'
      + '</div>';
  }).join('') || '<div class="hint">没有符合条件的图</div>';

  $$('.g-item').forEach(el => el.onclick = () => {
    if (S.gallerySelect || S.galleryDelMode) {
      const p = el.dataset.path;
      if (S.gallerySel[p]) delete S.gallerySel[p]; else S.gallerySel[p] = 1;
      // 原地改这一块，别整页重渲染（否则所有缩略图都要重新加载）
      el.classList.toggle('on', !!S.gallerySel[p]);
      const chk = el.querySelector('.g-check');
      if (chk) chk.textContent = S.gallerySel[p] ? '✓' : '';
      updateGallerySelectionUI();
      return;
    }
    openImage(el.dataset.path);
  });
  $$('.g-item .g-params').forEach(btn => btn.onclick = e => {
    e.stopPropagation();
    openRecipe(btn.dataset.params);
  });
  const ex = $('#g-export');
  if (ex) ex.style.display = S.gallerySelect ? '' : 'none';
  const bd = $('#g-bulk-del');
  if (bd) bd.style.display = S.galleryDelMode ? '' : 'none';
  updateGallerySelectionUI();
  if (bd) {
    bd.onclick = async () => {
      const paths = Object.keys(S.gallerySel);
      if (!paths.length) { toast('先点几张图选中', true); return; }
      if (!confirm('把选中的 ' + paths.length + ' 张图移入回收站？\n（可在「维护」里恢复）')) return;
      bd.disabled = true;
      const done = [];
      await Promise.all(paths.map(async p => {
        try { await api('/api/delete-image', { method: 'POST', body: JSON.stringify({ path: p, permanent: false }) }); done.push(p); } catch (e) {}
      }));
      bd.disabled = false;
      S.gallerySel = {};
      removeGalleryTiles(done);
      updateGallerySelectionUI();
      toast('已移入回收站 ' + done.length + ' 张');
    };
  }
}

// 批量删除后只把对应格子从 DOM 摘掉，不重渲染（避免整页缩略图重载闪黑）
function removeGalleryTiles(paths) {
  const host = $('#gallery');
  if (!host || !paths || !paths.length) return;
  const set = new Set(paths);
  $$('.g-item').forEach(el => { if (set.has(el.dataset.path)) el.remove(); });
  S.gallery = (S.gallery || []).filter(it => !set.has(it.path));
  const left = host.querySelectorAll('.g-item').length;
  if (!left && !host.querySelector('.hint')) host.innerHTML = '<div class="hint">没有符合条件的图</div>';
  const total = $('#g-total');
  if (total) {
    const m = /\/\s*(\d+)/.exec(total.textContent || '');
    const totalN = m ? Math.max(0, Number(m[1]) - set.size) : null;
    total.textContent = left + (totalN !== null ? ' / ' + totalN : '') + ' 张';
  }
}

function updateGallerySelectionUI() {
  const n = Object.keys(S.gallerySel || {}).length;
  const ex = $('#g-export');
  if (ex) { ex.style.display = S.gallerySelect ? '' : 'none'; ex.textContent = '导出选中（' + n + '）'; }
  const bd = $('#g-bulk-del');
  if (bd) { bd.style.display = S.galleryDelMode ? '' : 'none'; bd.textContent = '删除选中（' + n + '）'; }
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

function importRecipe(r) {
  const before = (S.pos || []).length + (S.neg || []).length;
  if (typeof pushHistory === 'function') pushHistory();
  const pick = b => ({ id: uid(), token: b.token || '', text: b.text || '', weight: Number(b.weight) || 1, enabled: b.enabled !== false });
  S.pos = (r.blocks_pos || []).filter(b => b.token || b.text).map(pick);
  S.neg = (r.blocks_neg || []).filter(b => b.token || b.text).map(pick);
  const size = (r.size && r.size.length === 2) ? r.size : null;
  if (size) {
    const val = size[0] + 'x' + size[1];
    const sel = $('#p-size');
    if (sel && [...sel.options].some(o => o.value === val)) sel.value = val;
    else if (sel) { sel.value = 'custom'; $('#p-w').value = size[0]; $('#p-h').value = size[1]; }
    const cs = $('#custom-size');
    if (cs) cs.hidden = !(sel && sel.value === 'custom');
  }
  if (r.steps && $('#p-steps')) $('#p-steps').value = r.steps;
  if (r.cfg && $('#p-cfg')) $('#p-cfg').value = r.cfg;
  if (r.seed !== undefined && $('#p-seed')) $('#p-seed').value = r.seed;
  if (Array.isArray(r.loras) && r.loras.length) {
    S.loras = r.loras.map(l => ({ name: l.name, weight: Number(l.weight) || 1 }));
    renderLoras();
  }
  const b = document.querySelector('#tabs button[data-tab="build"]');
  if (b) b.click();
  renderLanes();
  expandPreview();
  if (typeof updateEta === 'function') updateEta();
  if (typeof persistParams === 'function') persistParams();
  toast('已导入并清空原画布（原 ' + before + ' 块）→ ' + S.pos.length + ' 正 / ' + S.neg.length + ' 负 · seed ' + (r.seed ?? '随机'));
}

const RAND_SCENE = {
  '@SET_ONSEN':  { time: ['@TIME_NIGHT','@TIME_DUSK'], light: ['@LIGHT_CANDLE','@LIGHT_RIM'], pose: ['@POSE_SIT'], atmo: ['@ATMO_FOG'], mood: ['@MOOD_CALM','@MOOD_TENDER','@MOOD_SHY'] },
  '@SET_BEACH':  { time: ['@TIME_NOON','@TIME_AFTERNOON','@TIME_DUSK'], light: ['@LIGHT_WIN','@LIGHT_GOLDEN','@LIGHT_BACK'], pose: ['@POSE_STAND','@POSE_WALK'], atmo: ['@ATMO_PETALS'], mood: ['@MOOD_AMUSED','@MOOD_RELIEVED'] },
  '@SET_GARDEN_PEONY': { time: ['@TIME_MORNING','@TIME_AFTERNOON'], light: ['@LIGHT_BACK','@LIGHT_WIN'], pose: ['@POSE_SIT','@POSE_STAND'], atmo: ['@ATMO_KOMOREKI','@ATMO_PETALS'], mood: ['@MOOD_CALM','@MOOD_WISTFUL'] },
  '@SET_FOREST': { time: ['@TIME_MORNING','@TIME_DUSK'], light: ['@LIGHT_BACK','@LIGHT_GOLDEN'], pose: ['@POSE_STAND','@POSE_WALK'], atmo: ['@ATMO_KOMOREKI','@ATMO_FOG'], mood: ['@MOOD_WISTFUL','@MOOD_CALM'] },
  '@SET_FLOWER_SHOP': { time: ['@TIME_MORNING','@TIME_AFTERNOON'], light: ['@LIGHT_WIN'], pose: ['@POSE_STAND'], atmo: ['@ATMO_PETALS'], mood: ['@MOOD_AMUSED','@MOOD_CALM'] },
  '@SET_GREENHOUSE': { time: ['@TIME_MORNING','@TIME_AFTERNOON'], light: ['@LIGHT_WIN','@LIGHT_BACK'], pose: ['@POSE_STAND'], atmo: ['@ATMO_KOMOREKI'], mood: ['@MOOD_CALM'] },
  '@SET_CAFE':   { time: ['@TIME_AFTERNOON','@TIME_MORNING','@TIME_DUSK'], light: ['@LIGHT_WIN','@LIGHT_GOLDEN'], pose: ['@POSE_SIT'], atmo: ['@ATMO_DUST','@ATMO_LAMP'], mood: ['@MOOD_CALM','@MOOD_THINKING'] },
  '@SET_LIBRARY':{ time: ['@TIME_AFTERNOON','@TIME_MORNING'], light: ['@LIGHT_WIN','@LIGHT_SIDE'], pose: ['@POSE_SIT'], atmo: ['@ATMO_DUST','@ATMO_LAMP'], mood: ['@MOOD_FOCUSED','@MOOD_CALM'] },
  '@SET_BOOKSTORE':{ time: ['@TIME_AFTERNOON','@TIME_DUSK'], light: ['@LIGHT_WIN'], pose: ['@POSE_STAND','@POSE_LEAN'], atmo: ['@ATMO_DUST'], mood: ['@MOOD_FOCUSED','@MOOD_THINKING'] },
  '@SET_BEDROOM':{ time: ['@TIME_MORNING','@TIME_NIGHT'], light: ['@LIGHT_WIN','@LIGHT_CANDLE'], pose: ['@POSE_SIT','@POSE_LIE'], atmo: ['@ATMO_DUST'], mood: ['@MOOD_SLEEPY','@MOOD_CALM'] },
  '@SET_BATHROOM':{ time: ['@TIME_MORNING','@TIME_NIGHT'], light: ['@LIGHT_WIN','@LIGHT_CANDLE'], pose: ['@POSE_STAND'], atmo: ['@ATMO_FOG'], mood: ['@MOOD_CALM'] },
  '@SET_CLASSROOM':{ time: ['@TIME_AFTERNOON','@TIME_MORNING'], light: ['@LIGHT_WIN'], pose: ['@POSE_SIT','@POSE_STAND'], atmo: ['@ATMO_DUST'], mood: ['@MOOD_CALM','@MOOD_THINKING'] },
  '@SET_ARTROOM':{ time: ['@TIME_AFTERNOON'], light: ['@LIGHT_WIN','@LIGHT_SIDE'], pose: ['@POSE_SIT','@POSE_STAND'], atmo: ['@ATMO_DUST'], mood: ['@MOOD_FOCUSED'] },
  '@SET_KITCHEN':{ time: ['@TIME_MORNING','@TIME_AFTERNOON'], light: ['@LIGHT_WIN'], pose: ['@POSE_STAND'], atmo: [], mood: ['@MOOD_AMUSED','@MOOD_CALM'] },
  '@SET_LAUNDRY':{ time: ['@TIME_MORNING','@TIME_AFTERNOON'], light: ['@LIGHT_WIN'], pose: ['@POSE_STAND','@POSE_LEAN'], atmo: [], mood: ['@MOOD_RELIEVED'] },
  '@SET_CORRIDOR':{ time: ['@TIME_AFTERNOON','@TIME_DUSK'], light: ['@LIGHT_WIN','@LIGHT_BACK'], pose: ['@POSE_STAND','@POSE_WALK'], atmo: ['@ATMO_DUST'], mood: ['@MOOD_DETACHED'] },
  '@SET_MUSEUM':{ time: ['@TIME_AFTERNOON'], light: ['@LIGHT_STUDIO','@LIGHT_SIDE'], pose: ['@POSE_STAND'], atmo: ['@ATMO_DUST'], mood: ['@MOOD_CALM'] },
  '@SET_ELEVATOR':{ time: ['@TIME_NIGHT','@TIME_AFTERNOON'], light: ['@LIGHT_TOP'], pose: ['@POSE_STAND'], atmo: [], mood: ['@MOOD_DETACHED'] },
  '@SET_STATION':{ time: ['@TIME_DUSK','@TIME_NIGHT','@TIME_BLUE'], light: ['@LIGHT_BACK','@LIGHT_RIM'], pose: ['@POSE_STAND','@POSE_WALK'], atmo: ['@ATMO_DUST'], mood: ['@MOOD_WISTFUL'] },
  '@SET_SUBWAY':{ time: ['@TIME_NIGHT','@TIME_BLUE'], light: ['@LIGHT_TOP','@LIGHT_RIM'], pose: ['@POSE_STAND','@POSE_SIT'], atmo: ['@ATMO_DUST'], mood: ['@MOOD_TIRED','@MOOD_DETACHED'] },
  '@SET_TRAM':{ time: ['@TIME_DUSK','@TIME_MORNING'], light: ['@LIGHT_WIN','@LIGHT_GOLDEN'], pose: ['@POSE_SIT'], atmo: ['@ATMO_DUST'], mood: ['@MOOD_WISTFUL'] },
  '@SET_AIRPORT':{ time: ['@TIME_MORNING','@TIME_DUSK'], light: ['@LIGHT_WIN','@LIGHT_BACK'], pose: ['@POSE_WALK','@POSE_STAND'], atmo: ['@ATMO_DUST'], mood: ['@MOOD_DETACHED'] },
  '@SET_MARKET':{ time: ['@TIME_NIGHT','@TIME_DUSK'], light: ['@LIGHT_NEON','@LIGHT_RIM'], pose: ['@POSE_STAND','@POSE_WALK'], atmo: ['@ATMO_NEON','@ATMO_BOKEH'], mood: ['@MOOD_AMUSED','@MOOD_EXCITED'] },
  '@SET_ROOFTOP':{ time: ['@TIME_DUSK','@TIME_BLUE','@TIME_NIGHT'], light: ['@LIGHT_BACK','@LIGHT_RIM','@LIGHT_NEON'], pose: ['@POSE_STAND','@POSE_LEAN'], atmo: ['@ATMO_MOON','@ATMO_BOKEH'], mood: ['@MOOD_WISTFUL','@MOOD_DETACHED'] },
  '@SET_BALCONY':{ time: ['@TIME_DUSK','@TIME_BLUE'], light: ['@LIGHT_BACK','@LIGHT_GOLDEN'], pose: ['@POSE_LEAN','@POSE_STAND'], atmo: ['@ATMO_BOKEH'], mood: ['@MOOD_CALM','@MOOD_WISTFUL'] },
  '@SET_ARCADE':{ time: ['@TIME_NIGHT'], light: ['@LIGHT_NEON'], pose: ['@POSE_STAND'], atmo: ['@ATMO_NEON'], mood: ['@MOOD_EXCITED','@MOOD_AMUSED'] },
  '@SET_SHRINE':{ time: ['@TIME_DUSK','@TIME_MORNING'], light: ['@LIGHT_GOLDEN','@LIGHT_BACK'], pose: ['@POSE_STAND'], atmo: ['@ATMO_PETALS','@ATMO_DUST'], mood: ['@MOOD_CALM'] },
  '@SET_TEMPLE':{ time: ['@TIME_DAWN','@TIME_DUSK'], light: ['@LIGHT_GOLDEN','@LIGHT_BACK'], pose: ['@POSE_STAND'], atmo: ['@ATMO_FOG'], mood: ['@MOOD_CALM'] },
  '@SET_CASTLE':{ time: ['@TIME_DUSK','@TIME_NIGHT'], light: ['@LIGHT_CANDLE','@LIGHT_BACK'], pose: ['@POSE_STAND','@POSE_SIT'], atmo: ['@ATMO_DUST'], mood: ['@MOOD_CALM'] },
  '@SET_RUINS':{ time: ['@TIME_DUSK','@TIME_NOON'], light: ['@LIGHT_SIDE','@LIGHT_GOLDEN'], pose: ['@POSE_STAND','@POSE_WALK'], atmo: ['@ATMO_DUST'], mood: ['@MOOD_WISTFUL'] },
  '@SET_DESERT':{ time: ['@TIME_NOON','@TIME_DUSK'], light: ['@LIGHT_SIDE','@LIGHT_GOLDEN'], pose: ['@POSE_WALK','@POSE_STAND'], atmo: ['@ATMO_DUST'], mood: ['@MOOD_TIRED'] },
  '@SET_SNOWFIELD':{ time: ['@TIME_MORNING','@TIME_BLUE'], light: ['@LIGHT_BACK','@LIGHT_WIN'], pose: ['@POSE_STAND','@POSE_WALK'], atmo: ['@ATMO_FOG'], mood: ['@MOOD_CALM','@MOOD_COLD'] },
  '@SET_PIANO':{ time: ['@TIME_AFTERNOON','@TIME_DUSK'], light: ['@LIGHT_WIN','@LIGHT_GOLDEN'], pose: ['@POSE_SIT'], atmo: ['@ATMO_DUST'], mood: ['@MOOD_CALM'] },
  '@SET_SCHOOL_GATE':{ time: ['@TIME_MORNING','@TIME_AFTERNOON'], light: ['@LIGHT_WIN','@LIGHT_GOLDEN'], pose: ['@POSE_STAND','@POSE_WALK'], atmo: ['@ATMO_PETALS'], mood: ['@MOOD_CALM'] },
};

function weightedPick(arr, tok) {
  const notes = (S.notes && S.notes[tok]) || '';
  const w = notes.indexOf('成功') >= 0 ? 3 : 1;
  let total = arr.reduce((s, t) => s + ((S.notes && S.notes[t] || '').indexOf('成功') >= 0 ? 3 : 1), 0);
  let x = Math.random() * total;
  for (const t of arr) { x -= ((S.notes && S.notes[t] || '').indexOf('成功') >= 0 ? 3 : 1); if (x <= 0) return t; }
  return arr[arr.length - 1] || tok;
}

const RAND_PRIVATE_OUTFITS = new Set(['slip', 'pajama', 'loungewear']);
const RAND_PRIVATE_SCENES = new Set(['@SET_BEDROOM', '@SET_BATHROOM', '@SET_BALCONY', '@SET_ONSEN']);
const RAND_OUTDOOR = new Set(['@SET_BEACH', '@SET_FOREST', '@SET_GARDEN_PEONY', '@SET_SHRINE', '@SET_TEMPLE', '@SET_RUINS', '@SET_DESERT', '@SET_SNOWFIELD', '@SET_MARKET', '@SET_ROOFTOP', '@SET_SCHOOL_GATE', '@SET_FLOWER_SHOP', '@SET_STATION', '@SET_CASTLE']);
const RAND_SOCKED_OUTFITS = new Set(['school', 'sailor_winter', 'maid', 'santa']);
const RAND_HOSE_POOL = ['@HOSE_KNEE_WHITE', '@HOSE_THIGH_BLACK', '@HOSE_LACE_TOP', '@HOSE_ANKLE_WHITE', '@HOSE_SLOUCH', '@HOSE_FISHNET', '@HOSE_STRIPED', '@HOSE_ARGYLE'];

const RAND_SCENE_OUTFIT = {
  '@SET_ONSEN': ['yukata', 'slip', 'loungewear'], '@SET_BEACH': ['swimsuit', 'sundress_floral', 'sundress'],
  '@SET_CLASSROOM': ['school', 'sailor_winter', 'lab_coat'], '@SET_SCHOOL_GATE': ['school', 'sailor_winter'],
  '@SET_LIBRARY': ['cardigan_set', 'lab_coat', 'school'], '@SET_BOOKSTORE': ['cardigan_set', 'casual_knit', 'school'],
  '@SET_CAFE': ['cardigan_set', 'casual_knit', 'school'], '@SET_BEDROOM': ['pajama', 'loungewear', 'slip', 'cardigan_set'],
  '@SET_GYM': ['gym', 'hoodie_casual'], '@SET_SHRINE': ['yukata', 'hanfu', 'cheongsam'],
  '@SET_TEMPLE': ['yukata', 'hanfu'], '@SET_GARDEN_PEONY': ['sundress_floral', 'sundress', 'cardigan_set'],
  '@SET_MARKET': ['casual_knit', 'denim_set', 'hoodie_casual', 'sailor_winter'],
  '@SET_ROOFTOP': ['casual_knit', 'denim_set', 'school'], '@SET_BALCONY': ['casual_knit', 'denim_set', 'slip'],
  '@SET_STATION': ['sailor_winter', 'casual_knit', 'denim_set'], '@SET_SUBWAY': ['sailor_winter', 'denim_set', 'hoodie_casual'],
  '@SET_CORRIDOR': ['school', 'sailor_winter', 'lab_coat', 'denim_set'], '@SET_ARTROOM': ['school', 'cardigan_set', 'lab_coat'],
  '@SET_FLOWER_SHOP': ['sundress_floral', 'cardigan_set'], '@SET_GREENHOUSE': ['sundress_floral', 'sundress'],
  '@SET_DESERT': ['denim_set', 'hanfu', 'sundress_floral'], '@SET_SNOWFIELD': ['winter', 'sailor_winter', 'santa'],
  '@SET_FOREST': ['cardigan_set', 'sundress_floral', 'hanfu'], '@SET_RUINS': ['hanfu', 'sundress_floral', 'denim_set'],
  '@SET_CASTLE': ['hanfu', 'gala', 'cheongsam'], '@SET_AIRPORT': ['denim_set', 'casual_knit', 'suit'],
  '@SET_TRAM': ['cardigan_set', 'denim_set', 'school'], '@SET_PIANO': ['gala', 'initial_fine', 'cheongsam'],
  '@SET_LAUNDRY': ['casual_knit', 'loungewear', 'hoodie_casual'], '@SET_KITCHEN': ['casual_knit', 'loungewear', 'sundress'],
  '@SET_BATHROOM': ['slip', 'loungewear', 'pajama'], '@SET_ELEVATOR': ['suit', 'denim_set', 'school'],
  '@SET_MUSEUM': ['gala', 'lab_coat', 'cheongsam'], '@SET_ARCADE': ['hoodie_casual', 'denim_set', 'casual_knit'],
};
function sceneOutfitFor(scene) { return RAND_SCENE_OUTFIT[scene] || []; }

function randPickPool(pool) { return pool[Math.floor(Math.random() * pool.length)]; }
function randReplace(prefix, newTok) {
  S.pos = S.pos.map(b => (b.token || '').startsWith(prefix) ? Object.assign({}, b, { token: newTok }) : b);
}
function randCurrent(prefix) {
  const b = S.pos.find(x => (x.token || '').startsWith(prefix));
  return b ? b.token : '';
}

function randomSceneOnly() {
  const scenes = Object.keys(S.tokens || {}).filter(t => t.startsWith('@SET_') && !(S.notes[t] || '').includes('失败'));
  if (!scenes.length) return;
  const cur = randCurrent('@SET_');
  const hist = (S._randHist || []).slice(-3).map(h => h.scene);
  const pool = scenes.filter(t => t !== cur && !hist.includes(t));
  const next = randPickPool(pool.length ? pool : scenes.filter(t => t !== cur));
  if (!next) return;
  randReplace('@SET_', next);
  renderLanes(); expandPreview();
  toast('只换场景：' + next.replace('@SET_', ''));
}

function randomOutfitOnly() {
  // 只在本性别可穿的服装里挑（之前会跨性别换出男装）
  const garments = Object.keys(S.garments || {}).filter(k => ((S.garments[k] || {}).gender || 'f') === S.gender);
  if (!garments.length) return;
  const scene = randCurrent('@SET_');
  const cur = (randCurrent('@OUT_') || '').replace('@OUT_', '').toLowerCase();
  let pool = sceneOutfitFor(scene).filter(k => garments.includes(k));
  if (!pool.length) pool = garments.filter(k => !['swimsuit', 'school_bare', 'yukata_bare'].includes(k));
  pool = pool.filter(k => k !== cur);
  const next = randPickPool(pool.length ? pool : garments.filter(k => k !== cur));
  if (!next) return;
  const oldKey = cur.toUpperCase();
  randReplace('@OUT_', '@OUT_' + next.toUpperCase());
  S.neg = S.neg.map(b => (b.token === '@NEG_' + oldKey) ? Object.assign({}, b, { token: '@NEG_' + next.toUpperCase() }) : b);
  renderLanes(); expandPreview();
  const label = (S.garments[next] && S.garments[next].label) || next;
  toast('只换服装：' + label);
}

const RAND_TIME_LIGHT = {
  '@TIME_MORNING': ['@LIGHT_WIN', '@LIGHT_SIDE', '@LIGHT_TOP'],
  '@TIME_AFTERNOON': ['@LIGHT_WIN', '@LIGHT_GOLDEN', '@LIGHT_SIDE'],
  '@TIME_DUSK': ['@LIGHT_GOLDEN', '@LIGHT_RIM', '@LIGHT_BACK'],
  '@TIME_NIGHT': ['@LIGHT_NEON', '@LIGHT_CANDLE', '@LIGHT_TOP', '@LIGHT_STUDIO'],
  '@TIME_NOON': ['@LIGHT_WIN', '@LIGHT_TOP'],
  '@TIME_DAWN': ['@LIGHT_RAY', '@LIGHT_BACK']
};
const RAND_CAM_BY_FRAME = {
  near: ['@CAM_BUST', '@CAM_CLOSEUP', '@CAM_PROFILE', '@CAM_HIP'],
  mid: ['@CAM_MEDIUM', '@CAM_THREEQ', '@CAM_HIGH'],
  far: ['@CAM_FULL', '@CAM_BACKSIDE', '@CAM_REAR', '@CAM_TOP', '@CAM_WORM']
};
const RAND_COMP_BY_FRAME = {
  near: ['@COMP_CENTER', '@COMP_THIRDS', '@COMP_MACRO', '@COMP_DOF', '@COMP_FRAME', '@COMP_LOOKROOM'],
  mid: ['@COMP_THIRDS', '@COMP_LEADING', '@COMP_LAYERS', '@COMP_FRAME', '@COMP_CURVE', '@COMP_OVER_SHOULDER'],
  far: ['@COMP_WIDE', '@COMP_VAST', '@COMP_LEADING', '@COMP_SYMMETRY', '@COMP_HORIZON_HIGH', '@COMP_LAYERS', '@COMP_SILHOUETTE']
};
const RAND_SCENE_ONLY_OUTFITS = {
  '@SET_BEACH': ['swimsuit', 'sundress'],
  '@SET_ONSEN': ['yukata', 'loungewear'],
  '@SET_FESTIVAL': ['yukata'],
  '@SET_SHRINE': ['yukata', 'casual_knit'],
  '@SET_SNOWFIELD': ['winter'],
  '@SET_STADIUM': ['gym', 'casual_knit'],
  '@SET_GYM': ['gym'],
  '@SET_CAFETERIA': ['school', 'casual_knit'],
  '@SET_SCHOOLYARD': ['school', 'gym'],
  '@SET_HARBOR': ['raincoat', 'casual_knit'],
  '@SET_OFFICE': ['suit'],
  '@SET_HOTEL_LOBBY': ['gala', 'suit'],
  '@SET_THEATER': ['gala', 'idol'],
  '@SET_CLASSROOM': ['school'],
  '@SET_STATION_HALL': ['school', 'winter'],
  '@SET_AIRPORT': ['casual_knit', 'suit'],
};

// 随机一套的第二道工序：把组合交给「当前档位的全局模型」审校，冲突处自动替换/删除。
// 画布先出图，模型回来后原地改积木；失败/超时就保持原样，不打扰用户。
let _randAuditSeq = 0;
let _randAuditTimer = null;
const AUDIT_PROTECT_POS = new Set(['@ID', '@ID_F', '@ID_MALE', '@ID_M', '@SINGLE', '@SINGLE_F', '@SINGLE_M']);
// 与服务器同一套底线：这些只能换、不能删
const AUDIT_REPLACE_ONLY = ['@OUT_', '@BODY_', '@FACE_'];

function scheduleRandomAudit(ctx) {
  clearTimeout(_randAuditTimer);
  _randAuditTimer = setTimeout(() => { auditRandomSet(ctx); }, 350);
}

async function auditRandomSet(ctx) {
  const seq = ++_randAuditSeq;
  const snapPos = (S.pos || []).map(b => ({ id: b.id, token: b.token || '', text: b.text || '', weight: Number(b.weight) || 1 }));
  const snapNeg = (S.neg || []).map(b => ({ id: b.id, token: b.token || '', text: b.text || '', weight: 1 }));
  if (!snapPos.some(b => b.token)) return;
  let res = null;
  try {
    res = await api('/api/fix/blocks', { method: 'POST', body: JSON.stringify({ blocks: snapPos, negatives: snapNeg }) });
  } catch (e) { return; }
  if (seq !== _randAuditSeq) return;
  const issues = (res && res.issues) || [];
  const done = [];
  for (const it of issues) {
    const tok = String(it.token || '');
    if (!tok || it.level !== 'error') continue;
    if (it.action === 'remove') {
      const inPos = (S.pos || []).some(b => b.token === tok);
      if (inPos && AUDIT_PROTECT_POS.has(tok)) continue;
      if (it.lane === 'negative' && tok === '@NEG_BASE') continue;
      if (it.lane === 'negative') S.neg = (S.neg || []).filter(b => b.token !== tok);
      else S.pos = (S.pos || []).filter(b => b.token !== tok);
      done.push(tok);
    } else if (it.action === 'replace' && it.replace) {
      if (it.lane === 'negative') (S.neg || []).forEach(b => { if (b.token === tok) b.token = it.replace; });
      else (S.pos || []).forEach(b => { if (b.token === tok) b.token = it.replace; });
      done.push(tok + '→' + it.replace);
    }
  }
  if (!done.length) return;
  try { renderLanes(); expandPreview(); } catch (e) {}
  toast('规则修正 ' + done.length + ' 处：' + done.slice(0, 4).join('、'));
}

function randomCompose() {
  // 只抽当前性别 + 未被别的角色卡占用的积木
  const all = Object.keys(S.tokens || {}).filter(t => { try { return tokenVisible(t); } catch (e) { return true; } });
  if (!all.length) return;
  const forGender = t => {
    let c = resolveToken(t);
    if (S.gender === 'm' && /_F(_|$)/.test(c)) {
      const m = c.replace(/_F(_|$)/, '_M$1');
      if (all.includes(m)) c = m;
    }
    return c;
  };
  const has = t => !!t && all.includes(forGender(t));
  const hist = S._randHist || [];
  const last = hist[hist.length - 1] || {};
  const last2 = hist[hist.length - 2] || {};
  const pick = a => a[Math.floor(Math.random() * a.length)];
  const fromPrefix = p => all.filter(t => t.startsWith(p) && !(S.notes[t] || '').includes('失败'));
  const without = (arr, vals) => arr.filter(t => !vals.includes(t));

  // 1. 场景
  let scenePool = without(fromPrefix('@SET_'), [last.scene, last2.scene]);
  const scene = scenePool.length ? pick(scenePool) : pick(fromPrefix('@SET_'));
  const prof = RAND_SCENE[scene] || {};
  const scale = scene ? sceneScaleKey(scene) : 'medium';

  // 2. 景别与机位：先定 framing，再选具体机位
  const framingPool = scale === 'large' ? ['mid', 'far'] : scale === 'small' ? ['near', 'mid'] : ['near', 'mid', 'far'];
  const framing = pick(framingPool);
  let camPool = RAND_CAM_BY_FRAME[framing].filter(has);
  camPool = without(camPool, [last.cam]);
  if (!camPool.length) camPool = RAND_CAM_BY_FRAME[framing].filter(has);
  const cam = camPool.length ? pick(camPool) : '';

  // 3. 服装
  const outfitsAll = Object.keys(S.garments || {})
    .filter(k => !['school_bare', 'yukata_bare'].includes(k))
    .filter(k => ((S.garments[k] || {}).gender || 'f') === S.gender);
  let outfitPool = (RAND_SCENE_ONLY_OUTFITS[scene] || sceneOutfitFor(scene) || []).filter(k => outfitsAll.includes(k));
  if (S.gender !== 'm' && RAND_PRIVATE_SCENES.has(scene)) outfitPool = outfitPool.concat(['pajama', 'loungewear'].filter(k => outfitsAll.includes(k)));
  outfitPool = without(outfitPool, [last.outfit, last2.outfit]);
  if (!outfitPool.length) outfitPool = outfitsAll.filter(k => !['swimsuit'].includes(k));
  const outfit = outfitPool.length ? pick(outfitPool) : Object.keys(S.garments || {})[0];

  // 4. 时间与光：同一套光源表，避免"清晨 + 霓虹"
  let timePool = ((prof.time && prof.time.length) ? prof.time : fromPrefix('@TIME_')).filter(has);
  timePool = without(timePool, [last.time]);
  const time = timePool.length ? pick(timePool) : '';
  let lightPool = ((prof.light && prof.light.length) ? prof.light : (RAND_TIME_LIGHT[time] || [])).filter(has);
  if (!lightPool.length) lightPool = fromPrefix('@LIGHT_').filter(has);
  
  lightPool = without(lightPool, [last.light]);
  const light = lightPool.length ? pick(lightPool) : '';

  // 5. 姿势 / 视线 / 情绪 / 氛围
  const needPose = framing !== 'near';
  let posePool = ((prof.pose && prof.pose.length) ? prof.pose.map(forGender) : fromPrefix('@POSE_')).filter(has);
  posePool = posePool.filter(t => !/_LIE$/.test(t) || framing === 'far').filter(t => t !== last.pose);
  const pose = needPose && posePool.length ? pick(posePool) : '';
  const gazePool = fromPrefix('@GAZE_').filter(t => t !== '@GAZE_CLOSED');
  const gaze = (framing === 'near' && has('@GAZE_CAMERA') && Math.random() < 0.65)
    ? '@GAZE_CAMERA' : (gazePool.length ? pick(gazePool) : '');
  const moodPool = ((prof.mood && prof.mood.length) ? prof.mood : fromPrefix('@MOOD_')).filter(has);
  const mood = moodPool.length && Math.random() < 0.55 ? pick(moodPool) : '';
  const atmoPool = ((prof.atmo && prof.atmo.length) ? prof.atmo : fromPrefix('@ATMO_')).filter(has)
    .filter(t => RAND_OUTDOOR.has(scene) || !/RAIN|PETALS|MOON/.test(t));
  const atmo = atmoPool.length && Math.random() < 0.3 ? pick(atmoPool) : '';

  // 6. 构图：与景别匹配
  const compPool = RAND_COMP_BY_FRAME[framing].filter(has);
  const comp = compPool.length && Math.random() < 0.35 ? pick(compPool) : '';

  // 7. 身份：三种模式，按景别降级
  const roll = Math.random();
  let identityMode;
  if (framing === 'near') identityMode = roll < 0.15 ? 'none' : roll < 0.55 ? 'text' : 'block';
  else identityMode = roll < 0.2 ? 'none' : 'text';

  // 8. 画师
  let artistName = '';
  if (Math.random() < 0.25) {
    const pool = (S.loraFiles || []).filter(f => loraCat(f) === '画师' && !(typeof isFlatProneArtist === 'function' && isFlatProneArtist(f)));
    if (pool.length) {
      artistName = pick(pool);
      S.loras = (S.loras || []).filter(l => loraCat(l.name) !== '画师');
      const cw = (typeof artistDefaultWeight === 'function' ? artistDefaultWeight(artistName, currentCharLora()) : null) || 1.0;
      S.loras.push({ name: artistName, weight: cw });
    }
  }

  // 9. 组装
  const blocks = [];
  const add = t => { const c = forGender(t); if (t && all.includes(c)) blocks.push({ id: uid(), token: c, text: '', weight: 1, enabled: true }); };
  // 选了角色卡就用她的身份特征积木/弱身份文本，没选才走通用兜底
  const rc = (S.cards || []).find(x => x.name === ((($('#card-sel') || {}).value) || ''));
  if (identityMode === 'block') {
    const toks = (rc && (rc.tokens || []).length) ? rc.tokens
      : (S.gender === 'm' ? ['@SINGLE_M', '@ID_M'] : ['@SINGLE_F', '@ID_F']);
    toks.forEach(t => add(t));
  } else {
    const txt = identityMode === 'text'
      ? ((rc && rc.identity_weak) || (S.gender === 'm' ? TEXT_ID_MALE : TEXT_ID))
      : (S.gender === 'm' ? '1boy, solo' : '1girl, solo');
    blocks.push({ id: uid(), token: '', text: txt, weight: 1, enabled: true });
  }
  add(pick(fromPrefix('@BODY_').filter(t => !/_(ADULT|YOUTH|CHIBI|CHIBI_SD)$/.test(t))) || '');
  add(pick(fromPrefix('@FACE_').filter(t => !/_CHIBI$/.test(t))) || '');
  const randTrig = artistName ? artistTrigger(artistName) : '';
  if (randTrig) blocks.push({ id: uid(), token: '', text: randTrig, weight: 1, enabled: true, artist: true });
  add(gaze); add(cam); add(time); add(light); add(scene);
  add('@OUT_' + String(outfit).toUpperCase());
  add(pose); add(mood); add(atmo); add(comp);
  if (!RAND_SOCKED_OUTFITS.has(outfit) && Math.random() < 0.3) {
    const hose = RAND_HOSE_POOL.filter(has);
    if (hose.length) add(pick(hose));
  }
  // 近景 + 场景：景深锚
  if (scene && framing === 'near') {
    blocks.push({ id: uid(), token: '', text: 'shallow depth of field, softly blurred background behind the subject, standing close to the camera', weight: 1, enabled: true });
  }

  // 10. 负向
  const negToks = ['@NEG_BASE', '@NEG_HANDS'];
  const outfitNeg = '@NEG_' + String(outfit).toUpperCase();
  if (has(outfitNeg)) negToks.push(outfitNeg);
  if (pose) negToks.push(S.gender === 'm' ? '@NEG_MALE_BODY' : '@NEG_ANATOMY');
  if (S.gender === 'm') negToks.push('@NEG_MALE_FACE');
  

  S.pos = blocks;
  S.neg = negToks.filter(has).map(t => ({ id: uid(), token: t, text: '', weight: 1, enabled: true }));

  // 11. LoRA：只修非法值，不再覆盖用户权重
  S.loras = (S.loras || []).map(l => {
    const w = Number(l.weight);
    if (!Number.isFinite(w) || w <= 0) {
      const cat = loraCat(l.name);
      const dflt = cat === '角色' ? loraDefaultWeight(l.name) : (typeof artistDefaultWeight === 'function' ? artistDefaultWeight(l.name, currentCharLora()) : null) || loraDefaultWeight(l.name);
      return Object.assign({}, l, { weight: dflt });
    }
    return l;
  });

  const seed = 100000 + Math.floor(Math.random() * 899999);
  const sizeSel = document.querySelector('#p-size');
  if (sizeSel && [...sizeSel.options].some(o => o.value === '1024x1536')) sizeSel.value = '1024x1536';
  const customSize = document.querySelector('#custom-size');
  if (customSize) customSize.hidden = true;
  if (document.querySelector('#p-seed')) document.querySelector('#p-seed').value = seed;
  if (document.querySelector('#p-steps')) document.querySelector('#p-steps').value = 30;
  if (document.querySelector('#p-cfg')) document.querySelector('#p-cfg').value = 5.5;

  S._randHist = hist.concat([{ scene, outfit, cam, pose, time, light, framing, identityMode }]).slice(-8);
  renderLanes();
  expandPreview();
  if (typeof updateEta === 'function') updateEta();
  const label = (S.garments[outfit] && S.garments[outfit].label) || outfit;
  toast('随机：' + String(scene || '').replace('@SET_', '') + ' · ' + label + ' · ' +
        ({ near: '近景', mid: '中景', far: '远景' }[framing] || '') + ' · ' +
        String(light || '无光').replace('@LIGHT_', '') + ' · 身份 ' + identityMode + ' · seed ' + seed);

  // 画面先出，再把这一套交给当前档位的模型审校（异步、不阻塞按钮）
  scheduleRandomAudit({ scene, outfit, framing, light });
}


function randomComposePlaceholder() {}

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
    '<button class="ghost" id="z-refine">精修</button>' +
    '<button class="ghost" id="z-del" style="color:#ffb3a6">删除</button>' +
    '<span class="hint" style="margin-left:auto">' + esc(path.split('\\').pop()) + '</span>' +
    '</div>' +
    '<div class="logbar" style="margin-top:10px"><input id="m-note" placeholder="备注（可空）">' +
    '<div class="verdicts">' + ['A','B','C'].map(v => '<button data-v="' + v + '">' + v + '</button>').join('') +
    '</div></div>' +
    '<pre>' + esc(JSON.stringify(qc, null, 2)) + '</pre>');
  bindZoom(path);
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

function bindZoom(path) {
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
    ZV.scale = Math.min(w / nw, h / nh, 4);   // 允许放大填满窗口，最多 4x
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
  const zref = $('#z-refine');
  if (zref) zref.onclick = async () => {
    const v = prompt('精修强度（0.2–0.45，建议 0.3）', '0.3');
    if (v === null) return;
    zref.classList.add('loading');
    try {
      const rec = await api('/api/recipe?path=' + encodeURIComponent(path));
      const w = (rec.size && rec.size[0]) || 1024, h = (rec.size && rec.size[1]) || 1536;
      const r = await api('/api/reproduce', { method: 'POST', body: JSON.stringify({
        mode: 'keep_person', reference: path, prompt: rec.positive || '', negative: rec.negative || '',
        denoise: Math.max(0.1, Math.min(0.6, parseFloat(v) || 0.3)),
        width: w, height: h, steps: rec.steps || 26, cfg: rec.cfg || 5.2,
        seed: rec.seed || 0, prefix: 'refine', loras: rec.loras || [], model: rec.model || (($('#p-model') || {}).value || '') }) });
      toast('精修已提交：' + (r.job_id || ''));
      closeModal();
      if (r.job_id) pollJob(r.job_id, 'run');
    } catch (e) { toast('精修失败：' + e.message, true); }
    finally { zref.classList.remove('loading'); }
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

/* ---------- 词库：组合推荐 ---------- */
const COMBOS = [
  { name: '弱 3D 人像', preset: 'soft3d', tokens: [] },
  { name: '弱 3D · 场景版', preset: 'soft3d_scene', tokens: [] },
  { name: '场景大片（小人物）', preset: 'epic', tokens: [] },
  { name: '场景大片 · 俯拍', preset: 'epic_top', tokens: [] },
  { name: '电影感封面', tokens: ['@COMP_FRAMEINFRAME', '@BG_DARKFALL', '@LIGHT_RIM'] },
  { name: '梦境', tokens: ['@STYLE_SURREAL', '@POSE_F_FLOAT', '@ATMO_FOG'] },
  { name: '海报', tokens: ['@FX_SPOTCOLOR', '@COMP_GRAPHIC', '@COMP_MINIMAL'] },
  { name: '冲击力', tokens: ['@CUSTOM_FORESHORTEN', '@CAM_ZOOMBLUR', '@COMP_LOW'] },
  { name: '叙事', tokens: ['@FX_MULTIEXPO', '@FX_REFLECTION', '@SET_STATION'] },
  { name: '微缩世界', tokens: ['@COMP_TILTSHIFT', '@CAM_HIGH', '@SET_MARKET'] },
  { name: '夜景大片', tokens: ['@SET_ROOFTOP', '@BG_BOKEH', '@LIGHT_NEON', '@NEG_SKIN'] },
  { name: '干净棚拍', tokens: ['@BG_CLEAN', '@LIGHT_STUDIO', '@COMP_MINIMAL'] },
  { name: '温泉夜', tokens: ['@SET_ONSEN', '@TIME_NIGHT', '@BG_DARKFALL', '@LIGHT_CANDLE'] },
  { name: '雨天情绪', tokens: ['@ATMO_RAIN', '@COMP_REFLECTION', '@BG_BOKEH'] },
  { name: '夏日祭', tokens: ['@SET_MARKET', '@OUT_YUKATA', '@LIGHT_GOLDEN', '@BG_BOKEH'] },
  { name: '居家慵懒', tokens: ['@SET_BEDROOM', '@OUT_PAJAMA', '@TIME_MORNING', '@HAIR_F_MESSY'] },
];

function userCombos() {
  try { return JSON.parse(localStorage.getItem('loom.combos') || '[]'); } catch (e) { return []; }
}
function saveUserCombos(arr) {
  localStorage.setItem('loom.combos', JSON.stringify(arr));
}
function allCombos() {
  return COMBOS.concat(userCombos().map(c => Object.assign({ user: true }, c)));
}


function applySoft3DPreset() { toast('请在风格选择框选定一个 Anima 画师 LoRA 后直接预览'); }


function applySoft3DScenePreset() { toast('请在画布添加 @SET_* 与可选 Anima LoRA'); }

function applyEpicPreset() {
  S.loras = [];
  const mk = (t) => ({ id: uid(), token: t, text: '', weight: 1, enabled: true });
  S.pos = [
    { id: uid(), token: '', weight: 1, enabled: true,
      text: 'vast misty jungle interior, ancient moss-covered trees, hanging vines and ferns, steady rain, shallow water with reflections, a tiny lone girl in a dark coat walking along a thin path' },
    mk('@COMP_FIGURE_SMALL'), mk('@STYLE_ENVPAINT'), mk('@COMP_SINGLE_FIGURE')
  ];
  S.neg = [mk('@NEG_BASE'), mk('@NEG_PORTRAIT')];
  const setVal = (sel, v) => { const el = $(sel); if (el) el.value = v; };
  setVal('#artist-strength', '1');
  setVal('#identity-strength', '0');
  setVal('#p-size', '1536x864');
  setVal('#p-steps', '30');
  setVal('#p-cfg', '6');
  setVal('#p-seed', String(Math.floor(Math.random() * 900000) + 100000));
  const cs = $('#custom-size'); if (cs) cs.hidden = true;
  renderLoras(); renderLanes(); expandPreview();
  if (typeof updateEta === 'function') updateEta();
  toast('已套用「场景大片」：不带画师 LoRA、1536×864 宽幅、环境为主、人物缩到很远');
}
function applyEpicTopPreset() {
  S.loras = [];
  const mk = (t) => ({ id: uid(), token: t, text: '', weight: 1, enabled: true });
  S.pos = [
    { id: uid(), token: '', weight: 1, enabled: true,
      text: 'vast misty rainforest, dense foliage and hanging vines, light rain, soft diffuse light, muted green palette, a lone girl in a long coat walking a narrow path' },
    mk('@CAM_TOPDOWN_SCENE'), mk('@COMP_FIGURE_SMALL'), mk('@COMP_SINGLE_FIGURE')
  ];
  S.neg = [mk('@NEG_BASE'), mk('@NEG_PORTRAIT')];
  const setVal = (sel, v) => { const el = $(sel); if (el) el.value = v; };
  setVal('#artist-strength', '1');
  setVal('#identity-strength', '0');
  setVal('#p-size', '1536x864');
  setVal('#p-steps', '30');
  setVal('#p-cfg', '6');
  setVal('#p-seed', String(Math.floor(Math.random() * 900000) + 100000));
  const cs = $('#custom-size'); if (cs) cs.hidden = true;
  renderLoras(); renderLanes(); expandPreview();
  if (typeof updateEta === 'function') updateEta();
  toast('已套用「场景大片·俯拍」：高处俯视、人物占 1/5、环境为主');
}
function renderCombos() {
  const box = document.querySelector('#combo-list');
  if (!box) return;
  const list = allCombos();
  box.innerHTML = list.map((c, i) => {
    const toks = c.tokens.filter(t => S.tokens[t]);
    const desc = c.preset === 'soft3d' ? '通用人像预设 · 28 步 / CFG 5.5'
      : c.preset === 'soft3d_scene' ? '咖啡馆 + 开衫 + 窗光'
      : c.preset === 'epic' ? '无画师 LoRA · 1536×864 · 环境为主 · 小人物'
      : c.preset === 'epic_top' ? '俯拍 · 人物 1/5 · 1536×864' : toks.map(t => t.replace('@', '')).join(' · ');
    return '<div class="combo-item' + (c.user ? ' user' : '') + '" data-combo="' + i + '">' +
      '<b>' + esc(c.name) + '</b><span>' + desc + '</span>' +
      (c.user ? '<span class="combo-del" data-del-combo="' + i + '" title="删除">×</span>' : '') + '</div>';
  }).join('');
  box.querySelectorAll('[data-del-combo]').forEach(x => {
    x.onclick = ev => {
      ev.stopPropagation();
      const idx = +x.dataset.delCombo;
      const c = allCombos()[idx];
      if (!c || !c.user) return;
      if (!confirm('删除组合「' + c.name + '」？')) return;
      const list = userCombos().filter(u => u.name !== c.name);
      saveUserCombos(list);
      renderCombos();
    };
  });
  box.querySelectorAll('.combo-item').forEach(el => {
    el.onclick = () => {
      const c = allCombos()[+el.dataset.combo];
      if (c && c.preset === 'soft3d') { applySoft3DPreset(); return; }
      if (c && c.preset === 'soft3d_scene') { applySoft3DScenePreset(); return; }
      if (c && c.preset === 'epic') { applyEpicPreset(); return; }
      if (c && c.preset === 'epic_top') { applyEpicTopPreset(); return; }
      const toks = c.tokens.filter(t => S.tokens[t]);
      let added = 0;
      toks.forEach(t => {
        const lane = tokenCat(t) === 'neg' ? 'negative' : 'positive';
        const arr = lane === 'negative' ? S.neg : S.pos;
        if (arr.some(b => b.token === t)) return;
        addBlock(lane, t); added++;
      });
      const b = document.querySelector('#tabs button[data-tab="build"]');
      if (b) b.click();
      toast(added ? ('已加入「' + c.name + '」：' + added + ' 块') : ('「' + c.name + '」已经在画布上了'));
    };
  });
}

/* ---------- 词库 ---------- */
async function loadLibrary(filter) {
  const q = (filter === undefined ? (S.libraryFilter || '') : filter).toLowerCase();
  S.libraryFilter = q;
  const letter = S.libLetter || '';
  const order = ['id','body','pose','face','mood','gaze','hand','hold','weapon','hair','cam','light','atmo','time',
                 'outfit','fabric','drape','set','prop','comp','style','nsfw','neg','custom'];
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
  const rowHtml = (n, tx, key) => {
    const scCls = key === 'set' ? ' sc-' + (setScaleOf(n) === '小' ? 'small' : setScaleOf(n) === '中' ? 'medium' : 'large') : '';
    return '<div class="trow' + scCls + '" data-token="' + n + '" data-cat="' + key + '"' + tintAttrs(n) + '>' +
      '<span class="k">' + n + '</span>' +
      '<span class="v">' + esc((tx || '').slice(0, 120)) + '</span></div>';
  };
  for (const key of order) {
    let items = (groups[key] || []).slice();
    if (!items.length) continue;
    out += '<div class="tgroup" data-cat="' + key + '">' + (CAT_LABEL[key] || key) +
      '<span class="n">' + items.length + '</span></div>';

    if (key === 'set') {
      // 场景：小 / 中 / 大
      const order2 = ['小', '中', '大'];
      items.sort((a, b) => order2.indexOf(setScaleOf(a[0])) - order2.indexOf(setScaleOf(b[0])) || a[0].localeCompare(b[0]));
      let cur = '';
      for (const [n, tx] of items) {
        const sc = setScaleOf(n);
        if (sc !== cur) {
          cur = sc;
          const cnt = items.filter(([x]) => setScaleOf(x) === sc).length;
          out += '<div class="tsub" data-sub="' + sc + '">' + sc + '场景<span class="n">' + cnt + '</span></div>';
        }
        out += rowHtml(n, tx, key);
      }
      continue;
    }

    const defs = SUBGROUP_DEFS[key];
    if (defs) {
      const rank = t => { const g = subgroupOf(t); return g ? g.idx : 99; };
      items.sort((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0]));
      let curIdx = -2, curLabel = '';
      for (const [n, tx] of items) {
        const g = subgroupOf(n);
        const gi = g ? g.idx : 99;
        const lab0 = g ? g.label : '其他';
        if (lab0 !== curLabel) {
          curIdx = gi; curLabel = lab0;
          const lab = g ? g.label : '其他';
          const cnt = items.filter(([x]) => { const gg = subgroupOf(x); return (gg ? gg.idx : 99) === gi; }).length;
          out += '<div class="tsub" data-sub="' + esc(lab) + '" style="border-color:' + (g ? g.color : '#7d8798') + '">' +
            esc(lab) + '<span class="n">' + cnt + '</span></div>';
        }
        out += rowHtml(n, tx, key);
      }
      continue;
    }

    items.sort((a, b) => a[0].localeCompare(b[0]));
    for (const [n, tx] of items) out += rowHtml(n, tx, key);
  }
  renderSubgroupManager();
  $('#token-table').innerHTML = out || '<div class="hint" style="padding:12px">没有匹配的积木</div>';
  bindTips($('#token-table'));
  $$('#token-table .trow').forEach(el => el.onclick = () => {
    const n = el.dataset.token;
    $('#tk-name').value = n; $('#tk-text').value = S.tokens[n] || '';
    $('#tk-note').value = (S.notes || {})[n] || '';
    $('#tk-cat').value = tokenCat(n);
    const sgNow = subgroupOf(n);
    buildSubOptions(tokenCat(n), sgNow ? sgNow.label : '__auto__');
    const sg = subgroupOf(n);
    if ($('#tk-sub')) $('#tk-sub').value = sg ? sg.label : '';
    if ($('#tk-sub-color') && sg) $('#tk-sub-color').value = sg.color || '#7aa2d6';
  });
}



function subLabelsFor(cat) {
  const defs = SUBGROUP_DEFS[cat] || [];
  const builtin = defs.map(d => d.label);
  const custom = [];
  const subs = (S.tokenMeta && S.tokenMeta.subgroups) || {};
  for (const v of Object.values(subs)) {
    if (!v || !v.label) continue;
    if (!builtin.includes(v.label) && !custom.some(c => c.label === v.label)) custom.push({ label: v.label, color: v.color });
  }
  return { builtin, custom };
}

function buildSubOptions(cat, selected) {
  const sel = $('#tk-sub-sel');
  if (!sel) return;
  const { builtin, custom } = subLabelsFor(cat);
  const opts = ['<option value="__auto__">按内置规则分组</option>'];
  for (const l of builtin) opts.push('<option value="' + esc(l) + '">' + esc(l) + '（内置）</option>');
  for (const c of custom) opts.push('<option value="' + esc(c.label) + '">' + esc(c.label) + '（自定义）</option>');
  opts.push('<option value="__custom__">＋ 新建子分类…</option>');
  sel.innerHTML = opts.join('');
  sel.value = selected && [...sel.options].some(o => o.value === selected) ? selected : '__auto__';
  toggleSubNew();
}

function toggleSubNew() {
  const sel = $('#tk-sub-sel');
  const box = $('#tk-sub-new');
  if (!sel || !box) return;
  box.hidden = sel.value !== '__custom__';
}

function subColorFor(cat, label) {
  const subs = (S.tokenMeta && S.tokenMeta.subgroups) || {};
  for (const v of Object.values(subs)) if (v && v.label === label && v.color) return v.color;
  const defs = SUBGROUP_DEFS[cat] || [];
  const hit = defs.find(d => d.label === label);
  return hit ? hit.color : '#7aa2d6';
}

function renderSubgroupManager() {
  const box = $('#tk-sub-list-box');
  const dl = $('#tk-sub-list');
  const subs = (S.tokenMeta && S.tokenMeta.subgroups) || {};
  const labels = {};
  for (const [tok, v] of Object.entries(subs)) {
    const l = v && v.label ? v.label : '';
    if (!l) continue;
    (labels[l] = labels[l] || { color: v.color, tokens: [] }).tokens.push(tok);
  }
  if (dl) dl.innerHTML = Object.keys(labels).map(l => '<option value="' + esc(l) + '">').join('');
  if (!box) return;
  const entries = Object.entries(labels);
  box.innerHTML = entries.length
    ? entries.map(([l, v]) => '<span class="chip on" data-sub-label="' + esc(l) + '" style="border-left-color:' + (v.color || '#7aa2d6') + '">' +
        esc(l) + ' · ' + v.tokens.length + '<b class="x" data-sub-del="' + esc(l) + '">×</b></span>').join('')
    : '<span class="hint">还没有自定义子分类</span>';
  $$('[data-sub-del]').forEach(el => el.onclick = async () => {
    const l = el.dataset.subDel;
    const toks = (labels[l] || {}).tokens || [];
    if (!toks.length) return;
    if (!confirm('清除子分类「' + l + '」？' + toks.length + ' 个积木将回到内置规则')) return;
    for (const tok of toks) {
      try {
        await api('/api/token/save', { method: 'POST', body: JSON.stringify({ name: tok, text: S.tokens[tok] || '', category: tokenCat(tok), subgroup: '', color: '' }) });
      } catch (e) {}
    }
    const b = await api('/api/bootstrap');
    S.tokens = b.tokens; S.notes = b.notes; S.tokenMeta = b.token_meta || {};
    renderSubgroupManager(); loadLibrary(); renderPalette();
    toast('已清除子分类「' + l + '」');
  });
}

async function saveToken() {
  const name = $('#tk-name').value.trim();
  const text = $('#tk-text').value.trim();
  if (!name) { toast('需要名称', true); return; }
  let sub = '';
  let subColor = '#7aa2d6';
  const selSub = $('#tk-sub-sel');
  if (selSub) {
    if (selSub.value === '__custom__') {
      sub = (($('#tk-sub') || {}).value || '').trim();
      subColor = ($('#tk-sub-color') || {}).value || '#7aa2d6';
    } else if (selSub.value !== '__auto__') {
      sub = selSub.value;
      subColor = subColorFor($('#tk-cat').value, sub);
    }
  }
  const saved = await api('/api/token/save', { method:'POST', body: JSON.stringify({ name, text, category:$('#tk-cat').value, subgroup: sub, color: subColor }) });
  if (saved && saved.subgroups) {
    S.tokenMeta = S.tokenMeta || {};
    S.tokenMeta.subgroups = saved.subgroups;
    renderSubgroupManager();
  }
  // 保存时把备注一起写掉（不再单独一个「保存备注」按钮）
  try {
    const r = await api('/api/token/note', { method: 'POST', body: JSON.stringify({ name, text: $('#tk-note').value, category: 'note' }) });
    if (r && r.notes) S.notes = r.notes;
  } catch (e) {}
  S.tokens = (await api('/api/bootstrap')).tokens;
  renderPalette(); renderCombos(); loadLibrary($('#lib-search').value);
  toast('已保存 ' + name + '（含备注）');
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
  const keys = Object.keys(gs).filter(k => ((gs[k] || {}).gender || 'f') === S.gender);
  box.innerHTML = keys.length ? keys.map(k => {
    const g = gs[k] || {};
    const on = k === activeKey ? ' on' : '';
    return '<div class="gm-item' + on + '" data-key="' + k + '" title="' + esc(g.note || '') + '">' +
      '<b>' + esc(g.label || k) + '</b><span class="key">' + k + '</span>' +
      '<span class="use">' + esc(g.use_for || '') + '</span>' +
      '<span class="len">' + ((g.prompt || '').length) + ' 字符</span>' +
      (g.note ? '<span class="note">' + esc(g.note.slice(0, 26)) + (g.note.length > 26 ? '…' : '') + '</span>' : '') +
      '</div>';
  }).join('') : '<div class="hint">还没有服装</div>';
  $$('#gm-list .gm-item').forEach(el => el.onclick = () => loadGarment(el.dataset.key));
  bindGarmentHover();
}

// 服装展示图的版本戳：换图后改这里，浏览器就不会拿旧缓存
const PREVIEW_VER = '20261113c';

// 服装悬停：显示"素体穿着这套服装"的样张
function bindGarmentHover() {
  const box = $('#gm-list');
  if (!box) return;
  let card = null, timer = null;
  const hide = () => { clearTimeout(timer); if (card) { card.remove(); card = null; } };
  box.addEventListener('mouseleave', hide);
  $$('#gm-list .gm-item').forEach(el => {
    el.onmouseenter = () => {
      hide();
      timer = setTimeout(() => {
        const key = el.dataset.key;
        const g = (S.garments || {})[key] || {};
        const r = el.getBoundingClientRect();
        card = document.createElement('div');
        card.className = 'artist-hover garment-hover';
        card.innerHTML = '<div class="ah-title">' + esc(g.label || key) +
          '<span class="ah-kind">服装展示</span></div>' +
          '<div class="ah-thumbs"><figure class="ah-item"><img alt="" src="/api/garment_preview?key=' +
          encodeURIComponent(key) + '&v=' + encodeURIComponent(PREVIEW_VER) +
          '" onerror="this.parentNode.parentNode.dataset.empty=1">' +
          '</figure></div>' +
          '<div class="hint" style="margin-top:6px">素体穿着效果；没有图说明还没生成</div>';
        document.body.appendChild(card);
        // 图片还没加载时 offsetHeight 是 0，算出来的 top 会把卡片顶到视口外；
        // 所以加载完（以及窗口尺寸变化时）都要重新定位
        const clamp = () => {
          if (!card) return;
          const w = card.offsetWidth, h = card.offsetHeight;
          let left = r.right + 12;
          if (left + w > window.innerWidth - 8) left = Math.max(8, r.left - w - 12);
          let top = r.top - 8;
          if (top + h > window.innerHeight - 8) top = Math.max(8, window.innerHeight - h - 8);
          if (top < 8) top = 8;
          card.style.left = Math.max(8, left) + 'px';
          card.style.top = top + 'px';
        };
        clamp();
        const im = card.querySelector('img');
        if (im) {
          im.addEventListener('load', clamp);
          im.addEventListener('error', () => { const h = card && card.querySelector('.hint'); if (h) h.textContent = '还没生成这套的展示图'; card && clamp(); });
        }
        requestAnimationFrame(clamp);
      }, 400);
    };
  });
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
  if ($('#gm-note')) $('#gm-note').value = g.note || '';
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
  if ($('#gm-note')) $('#gm-note').value = '';
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
    note: ($('#gm-note') || {}).value || '',
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
  refreshMemory();
  if ($('#mt-mem-refresh')) $('#mt-mem-refresh').onclick = refreshMemory;
  if ($('#mt-mem-free')) $('#mt-mem-free').onclick = async () => {
    if (!confirm('释放 ComfyUI 模型？下次出图会重新加载。')) return;
    const r = await api('/api/memory/free', { method: 'POST' });
    toast('已释放：可用 ' + r.before.free_gb + ' → ' + r.after.free_gb + ' GB');
    refreshMemory();
  };
  $$('#doc-list button').forEach(el => el.onclick = async () => {
    const r = await api('/api/doc?path=' + encodeURIComponent(el.dataset.doc));
    openModal(el.textContent, '<pre>' + esc(r.text) + '</pre>');
  });
}

async function refreshMemory() {
  try {
    const m = await api('/api/memory');
    const r = m.ram || {}, cf = m.comfy || {}, auto = m.auto || {};
    if ($('#mt-mem')) $('#mt-mem').textContent = '系统 ' + r.used_gb + ' / ' + r.total_gb + ' GB · ' + r.percent + '%';
    const rows = [
      ['系统可用', r.free_gb + ' GB'],
      ['站台进程', m.station_mb + ' MB'],
      ['ComfyUI', cf.up ? ('VRAM 空闲 ' + Math.round((cf.vram_free || 0) / 1e9) + ' / ' + Math.round((cf.vram_total || 0) / 1e9) + ' GB') : '离线'],
      ['自动回收', 'Comfy ' + Math.round((auto.comfy_idle_sec || 0) / 60) + ' 分'],
    ];
    if ($('#mt-mem-kv')) $('#mt-mem-kv').innerHTML = rows.map(x =>
      '<span class="k">' + x[0] + '</span><span class="v">' + x[1] + '</span>').join('');
  } catch (e) {}
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
  const w = parseFloat($('#desc-weight').value) || 1.0;
  addBlock(lane, { text: txt, weight: w });
  toast('已插入' + (lane === 'positive' ? '正向' : '负向') + ' · 权重 ' + w);
}

async function saveDescAsBlock() {
  const txt = ($('#desc-text').value || '').trim();
  if (!txt) { toast('先写一段描述', true); return; }
  openModal('存为积木',
    '<div class="field"><label>积木名（自动加 @USER_ 前缀）</label>' +
      '<input id="sd-name" placeholder="例如 BOOKSHOP" value="DESC"></div>' +
    '<div class="field"><label>内容</label><textarea id="sd-text" rows="4">' + esc(txt) + '</textarea></div>' +
    '<div class="row2"><button class="ghost" id="sd-cancel">取消</button>' +
      '<button class="primary" id="sd-ok">保存为积木</button></div>' +
    '<p class="hint">存好后会出现在左侧「自定义」分类里，可以重复使用。</p>');
  $('#sd-cancel').onclick = closeModal;
  $('#sd-ok').onclick = async () => {
    const name = ($('#sd-name').value || '').trim();
    const body = ($('#sd-text').value || '').trim();
    if (!name || !body) { toast('名字和内容都不能空', true); return; }
    const token = '@USER_' + name.toUpperCase().replace(/[^A-Z0-9_]/g, '_');
    try {
      await api('/api/token/save', { method: 'POST', body: JSON.stringify({ name: token, text: body, category: 'custom' }) });
      S.tokens = (await api('/api/bootstrap')).tokens;
      renderPalette();
      closeModal();
      toast('已存为 ' + token);
    } catch (e) { toast('保存失败：' + e.message, true); }
  };
}

/* ---------- IR 校验 ---------- */
const LABEL_MAP = {
  id:'身份', single:'单人', win:'窗光', soft:'柔光', rim:'轮廓光', candle:'烛光', golden:'金色光', neon:'霓虹', night:'夜', top:'顶光', back:'逆光',
  corridor:'走廊', cafe:'咖啡厅', station:'站台', tram:'电车', laundry:'洗衣房', bedroom:'卧室', garden:'花园', beach:'海滩',
  full:'全身', bust:'胸像', medium:'半身', threeq:'3/4', closeup:'特写',
  denim_set:'牛仔套装', school:'校服', pajama:'睡衣', hoodie_casual:'卫衣', loungewear:'家居服',
};

function buildSetupSummary() {
  const short = (t) => String(t).replace(/^@/, '').replace(/^(OUT|SET|BG|LIGHT|TIME|STYLE|CAM|COMP|POSE|GAZE|ID|SINGLE)_/, '').toLowerCase();
  const pick = (re) => S.pos.filter(b => b.token && re.test(b.token)).map(b => short(b.token));
  const groups = [
    ['身份', pick(/^@(ID|SINGLE)$/)],
    ['服装', pick(/^@OUT_/)],
    ['场景', pick(/^@SET_|^@BG_/)],
    ['光', pick(/^@LIGHT_|^@TIME_/)],
    ['风格', pick(/^@STYLE_/)],
    ['镜头', pick(/^@CAM_|^@COMP_/)],
    ['姿势', pick(/^@POSE_|^@GAZE_/)],
  ];
  const zh = (x) => LABEL_MAP[x] || x;
  const first = groups.filter(([, v]) => v.length).map(([k, v]) => k + ' ' + (k === '身份' ? '锁定' : v.slice(0, 2).map(zh).join('/'))).join(' · ');
  const loras = (S.loras || []).map(l => String(l.name || '').replace(/\.safetensors$/i, '').replace(/[0-9A-F]{6,}.*$/i, '').replace(/[._-]+$/, '') + ' ' + Number(l.weight).toFixed(2)).join(' + ') || '无';
  const sz = ($('#p-size') || {}).value === 'custom' ? (($('#p-w') || {}).value + '×' + ($('#p-h') || {}).value) : String(($('#p-size') || {}).value || '').replace('x', '×');
  const second = [sz, (($('#p-steps') || {}).value || '') + ' 步', 'CFG ' + (($('#p-cfg') || {}).value || ''), '精修 ' + (($('#p-refine') || {}).value || '0'), 'LoRA ' + loras].filter(Boolean).join(' · ');
  const textBlock = S.pos.find(b => !b.token && (b.text || '').trim());
  const head = textBlock ? '文本模式（' + textBlock.text.trim().length + ' 字符）' : (first || '未放置积木');
  return '<span class="ok-t">✓ 通过</span> ' + esc(head) + '<br><span class="kv">' + esc(second) + '</span>';
}

async function validateBlocks() {
  const bar = $('#validate-bar');
  if (!bar) return;
  try {
    const viewTok = (S.reproj && S.reproj.view) ||
      ((S.pos || []).map(b => b.token || '').find(t => /^@(ID_F_.*_(BACK|TQ_BACK|SIDE_[LR]|GLANCE_[LR]))/.test(t)) || '');
    const v = await api('/api/validate', { method: 'POST', body: JSON.stringify({ positive: S.pos, negative: S.neg, view: viewTok }) });
    S.validation = v;
    const parts = [];
    const brief = (arr, n) => {
      const head = arr.slice(0, n).map(e => esc(e.msg)).join('；');
      return head + (arr.length > n ? '；等 ' + arr.length + ' 条' : '');
    };
    if (v.errors.length) parts.push('<b class="err">' + v.errors.length + ' 个错误</b>：' + brief(v.errors, 2));
    if (v.warnings.length) parts.push('<b class="warn-t">' + v.warnings.length + ' 个警告</b>：' + brief(v.warnings, 2));
    if (v.hints.length) parts.push('<b class="hint-t">建议</b>：' + brief(v.hints, 1));
    const bad = S.pos.concat(S.neg).filter(b => b.token && (S.rel || {})[b.token] === 'X');
    if (bad.length) {
      parts.push('<b class="warn-t">⚠ 实测失败积木</b>：' +
        [...new Set(bad.map(b => b.token))].join('、') + '（自动探针判定不达标）');
    }
    bar.innerHTML = parts.length ? parts.join('<br>') : buildSetupSummary();
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
    '<div class="field"><label>提示词（只描述要画的那块）</label><textarea id="hf-p" rows="3">hand with five fingers, fingers pressing the piano keys, detailed fingers, same art style</textarea></div>' +
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
            const _imgs = items.filter(x => x.status === 'done' && x.image).map(x => x.image);
            if (_imgs.length) { showResult(_imgs, 'batch', '—'); }
            toast('批量完成 ' + doneN + ' 张，可在结果区左右翻看');
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
  if (cnt) cnt.textContent = r.total + ' 张' + (r.missing ? ('（失效路径 ' + r.missing + '）') : '');
  if (!box) return;
  if (!r.items.length) {
    box.innerHTML = '<div class="hint">还没有配方记录。出图时会自动记下积木、参数与 LoRA。</div>';
    return;
  }
  box.innerHTML = r.items.map(it =>
    '<div class="rc-item" data-path="' + esc(it.path) + '" title="单击看配方 · 双击看大图">' +
    '<img loading="lazy" src="/api/img?path=' + encodeURIComponent(it.path) + '">' +
    '<div class="m"><b>' + esc(it.name.slice(0, 22)) + '</b>' +
    '<span>' + (it.mode || '') + ' · ' + (it.lora_n || 0) + ' LoRA</span></div>' +
    '<input type="checkbox" class="rc-check" data-cmp-path="' + esc(it.path) + '" title="加入对比">' +
    '</div>').join('');
  $$('#rc-list .rc-item').forEach(el => {
    el.onclick = () => openRecipe(el.dataset.path, true);
    el.ondblclick = (e) => { e.preventDefault(); if (typeof openImage === 'function') openImage(el.dataset.path); };
  });
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
  S.rcPath = path;
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
    ((r.rewrite_notes && r.rewrite_notes.length) ? ('<h4 class="rc-h">规则自动改写</h4><pre class="prompt-preview">' + esc(r.rewrite_notes.join('\n')) + '</pre>') : '') +
    ((r.client_meta && r.client_meta.ls_keys) ? ('<p class="hint">前端状态快照：' + esc(r.client_meta.ls_keys.join(', ')) + '</p>') : '') +
    '<div class="row2" style="margin-top:10px">' +
      '<button class="primary" id="rc-import">一键导入该配方</button>' +
      '<button class="ghost" id="rc-copy">复制正向</button>' +
      ((r.mode === 'reproject' || r.manifest_path) ? '<button class="ghost" id="rc-manifest">重映过程清单</button>' : '') +
      '</div>';
  const mfBtn = $('#rc-manifest');
  if (mfBtn) mfBtn.onclick = () => { if (typeof showCoopManifest === 'function') showCoopManifest(path, true); };
  const imp = $('#rc-import');
  if (imp) imp.onclick = () => importRecipe(r);
  const cp = $('#rc-copy');
  if (cp) cp.onclick = async () => {
    try { await navigator.clipboard.writeText(r.positive || ''); toast('正向已复制'); }
    catch (e) { toast('复制失败：' + e.message, true); }
  };
  if (body) body.ondblclick = () => { if (S.rcPath && typeof openImage === 'function') openImage(S.rcPath); };
  $$('#rc-list .rc-item').forEach(el => el.classList.toggle('on', el.dataset.path === path));
}

/* ---------- 通用 ---------- */


function openModal(title, html) {
  $('#modal-title').textContent = title;
  $('#modal-content').innerHTML = html;
  $('#modal').classList.add('open');
}
function closeModal() { $('#modal').classList.remove('open'); }

/* ---------- 文本块 / 积木详情（专用弹窗） ---------- */
function openTextBlockDialog(opts) {
  opts = opts || {};
  let lane = opts.lane === 'negative' ? 'negative' : 'positive';
  const title = opts.title || '添加文本块';
  openModal(title,
    '<div class="field"><label>放进哪一侧</label><div class="row2">' +
      '<button class="ghost wide tx-lane' + (lane === 'positive' ? ' on' : '') + '" data-lane="positive">正向</button>' +
      '<button class="ghost wide tx-lane' + (lane === 'negative' ? ' on' : '') + '" data-lane="negative">负向</button>' +
    '</div></div>' +
    '<div class="field"><label>内容（英文标签或中文描述都行）</label>' +
      '<textarea id="tx-text" rows="5" placeholder="例：sitting on the stairs, warm afternoon light from the left">' + esc(opts.text || '') + '</textarea></div>' +
    '<div class="row2">' +
      '<div class="field"><label>权重</label><input id="tx-weight" type="number" step="0.05" min="0.3" max="2" value="' + (opts.weight || 1) + '"></div>' +
      '<div class="field"><label>&nbsp;</label><button class="primary wide" id="tx-ok">加入画布</button></div>' +
    '</div>' +
    '<p class="hint">加进画布后可以拖动排序、改权重、双击再看内容。</p>');
  $$('#modal-content .tx-lane').forEach(b => b.onclick = () => {
    lane = b.dataset.lane;
    $$('#modal-content .tx-lane').forEach(x => x.classList.toggle('on', x === b));
  });
  const txt = $('#tx-text');
  if (txt) { txt.focus(); txt.setSelectionRange(txt.value.length, txt.value.length); }
  $('#tx-ok').onclick = () => {
    const text = ($('#tx-text').value || '').trim();
    if (!text) { toast('内容不能空', true); return; }
    const weight = Math.max(0.3, Math.min(2, parseFloat($('#tx-weight').value) || 1));
    closeModal();
    if (opts.onSave) opts.onSave(text, weight, lane);
    else { addBlock(lane, { text, weight }); toast('已加入' + (lane === 'positive' ? '正向' : '负向')); }
  };
}

function openBlockDetail(b, lane) {
  const token = b.token || '';
  const txt = (S.tokens || {})[token] || '';
  const note = (S.notes || {})[token] || '（这块还没有备注）';
  const rel = (S.rel || {})[token] || '';
  const cat = CAT_LABEL[tokenCat(token)] || tokenCat(token);
  const relBadge = rel === 'X' ? '<span class="rc-chip" data-cat="neg">实测失败</span>'
    : rel === 'OK' ? '<span class="rc-chip" data-cat="id">实测可用</span>'
    : rel === '?' ? '<span class="rc-chip">部分成立</span>' : '<span class="hint">未测</span>';
  openModal(token + ' · ' + cat,
    '<div class="rc-kv" style="margin:0 0 10px">' +
      '<span class="k">分类</span><span class="v">' + esc(cat) + '</span>' +
      '<span class="k">权重</span><span class="v">×' + (b.weight === undefined ? 1 : b.weight) + '</span>' +
      '<span class="k">位置</span><span class="v">' + (lane === 'negative' ? '负向' : '正向') + '</span>' +
      '<span class="k">状态</span><span class="v">' + relBadge + '</span>' +
    '</div>' +
    '<h4 class="rc-h">展开后的提示词</h4>' +
    '<pre class="prompt-preview">' + esc(txt || '（这个词没有内容）') + '</pre>' +
    '<h4 class="rc-h">备注</h4><p class="hint" style="margin:0">' + esc(note) + '</p>' +
    '<div class="row2" style="margin-top:12px">' +
      '<button class="ghost" id="bd-copy">复制提示词</button>' +
      '<button class="primary" id="bd-close">关闭</button></div>');
  $('#bd-copy').onclick = async () => {
    try { await navigator.clipboard.writeText(txt); toast('已复制 ' + token); }
    catch (e) { toast('复制失败：' + e.message, true); }
  };
  $('#bd-close').onclick = closeModal;
}

function applyTemplate(tpl, appendMode) {
  const isAppend = !!appendMode;
  if (!isAppend) pushHistory();
  const norm = b => Object.assign({ id: uid(), weight: 1, enabled: true, text: '' }, b);
  const mergeInto = (cur, incoming) => {
    const seen = new Set(cur.map(b => (b.token || '') + '|' + (b.text || '')));
    let added = 0;
    for (const b of incoming) {
      const key = (b.token || '') + '|' + (b.text || '');
      if (seen.has(key)) continue;
      seen.add(key); cur.push(norm(b)); added++;
    }
    return added;
  };
  if (isAppend) {
    if ((tpl.name || '').startsWith('风格')) {
      const isStyleFx = t => /^@STYLE_/.test(t.token || '') || /^@FX_(BLACK_BLOCKS|BAND_GLITCH)$/.test(t.token || '');
      S.pos = S.pos.filter(b => !isStyleFx(b));
      S.neg = S.neg.filter(b => !/^@NEG_(OUTLINE|GLITCHBAND)$/.test(b.token));
    }
    const a = mergeInto(S.pos, tpl.positive || []);
    const b = mergeInto(S.neg, tpl.negative || []);
    toast('已叠加：+' + a + ' 正 / +' + b + ' 负');
  } else {
    S.pos = (tpl.positive || []).map(norm);
    S.neg = (tpl.negative || []).map(norm);
  }
  const moved = S.pos.filter(b => b.token && tokenCat(b.token) === 'neg');
  if (moved.length) {
    S.pos = S.pos.filter(b => !(b.token && tokenCat(b.token) === 'neg'));
    S.neg = S.neg.concat(moved);
  }
  if (!isAppend && tpl.params) {
    if (tpl.params.size) {
      const sel = $('#p-size');
      const opt = [...sel.options].find(o => o.value === tpl.params.size);
      if (opt) sel.value = tpl.params.size;
      else { sel.value = 'custom'; const wh = String(tpl.params.size).split('x'); $('#p-w').value = wh[0]; $('#p-h').value = wh[1]; const cs = $('#custom-size'); if (cs) cs.hidden = false; }
    }
    if (tpl.params.model) {
      const ms = $('#p-model');
  if (ms && S.altModels && S.altModels.length && !ms.dataset.altAdded) {
    ms.dataset.altAdded = '1';
    S.altModels.forEach(f => { if (![...ms.options].some(o => o.value === f)) ms.insertAdjacentHTML('beforeend', '<option value="' + f + '">' + f + '</option>'); });
  }
      if (ms && [...ms.options].some(o => o.value === tpl.params.model)) { ms.value = tpl.params.model; S.model = tpl.params.model; }
    }
    if (tpl.params.steps) $('#p-steps').value = tpl.params.steps;
    if (tpl.params.cfg) $('#p-cfg').value = tpl.params.cfg;
  }
  renderLanes(); expandPreview();
}

async function loadTemplates() {
  const r = await api('/api/templates');
  S.templates = r.items || [];
  $('#tpl-row').innerHTML = S.templates.map((t, i) =>
    '<button class="ghost" data-tpl="' + i + '">' + t.name + '</button>').join('');
  $$('#tpl-row button[data-tpl]').forEach(el => el.onclick = (ev) => { const t = S.templates[Number(el.dataset.tpl)]; applyTemplate(t, ev.shiftKey || (t.name || '').startsWith('风格')); });
}

async function loadPresets() {
  const r = await api('/api/presets');
  S.presets = r.items || [];
}


/* ---------- 工作流向导 ---------- */
function guideModeValue() {
  const m = S.guide && S.guide.picks && S.guide.picks.mode && S.guide.picks.mode[0];
  if (m === '__mode__:coop') return 'coop';
  if (m === '__mode__:direct') return 'direct';
  return S.coopOn ? 'coop' : 'direct';
}

function _guideMeta(t, stKey) {
  if (t === '__mode__:direct') return { label: '常规直出（单图）', note: 'Anima 单图 T2I · 自由度最高，推荐 1024×1536' };
  if (t === '__mode__:coop') return { label: '合作重映（场景+人物）', note: '出板→人物重绘→修脸修手 · 默认环境 66% / 人物 34%' };
  if (t === '__free__') return { label: '不锁角色（自由发挥）', note: '只留基础 1girl/1boy，完全交给画师 LoRA 发挥' };
  if (t.startsWith('__card__:')) {
    const cn = t.slice(9);
    const card = (S.cards || []).find(c => c.name === cn);
    return { label: '角色卡 · ' + cn, note: (card && card.persona) ? String(card.persona).split(/\n/)[0].slice(0, 30) : '绑定角色卡专属正负向与 LoRA' };
  }
  if (t.startsWith('__ratio__:')) {
    const r = t.slice(10);
    const map = { '0.20': '环境 80% / 人物 20%（大景远人）', '0.25': '环境 75% / 人物 25%（风景带人）', '0.34': '环境 66% / 人物 34%（默认 1/3 全身）', '0.45': '环境 55% / 人物 45%（人物中景）' };
    return { label: map[r] || ('占比 ' + r), note: '合作出板默认人物占画高 ' + r };
  }
  if (stKey === 'artist') {
    if (t === '__none__') return { label: '不指定（纯底模）', note: '仅使用 Anima 原生画风' };
    const env = typeof isEnvLora === 'function' && isEnvLora(t);
    const cw = typeof coopLoraDefaultWeight === 'function' ? coopLoraDefaultWeight(t, env ? 'env' : 'artist') : (env ? 0.70 : 0.85);
    const bw = typeof artistDefaultWeight === 'function' ? artistDefaultWeight(t, '') : (env ? 0.70 : 0.85);
    return {
      label: (typeof shortLoraName === 'function' ? shortLoraName(t) : t),
      note: (env ? '环境 LoRA · 推荐 ' + cw.toFixed(2) : '人物画师 · 单图 ' + bw.toFixed(2) + ' / 合作 ' + cw.toFixed(2))
    };
  }
  return { label: t, note: (S.notes || {})[t] || '' };
}

function guideSteps() {
  const canon = t => resolveToken(t);
  const pick = arr => arr.map(canon).filter(t => !!(S.tokens && S.tokens[t]) && (typeof tokenVisible !== 'function' || tokenVisible(t)));
  const isCoop = guideModeValue() === 'coop';
  const g = (typeof S.gender === 'string' && S.gender === 'm') ? 'm' : 'f';
  const cards = (S.cards || []).filter(c => (c.gender || 'f') === g).map(c => '__card__:' + c.name);
  const idPub = pick(g === 'm'
    ? ['@SINGLE_M', '@ID_M_SOFT', '@ID_M', '@ID_M_TIGHT', '@ID_M_KAI', '@ID_M_REN', '@ID_M_TAKU']
    : ['@SINGLE_F', '@ID_F_SOFT', '@ID_F', '@ID_F_TIGHT', '@ID_F_AYA', '@ID_F_RIN', '@ID_F_YUKI', '@ID_F_SORA', '@ID_F_HANA']);
  const outfits = Object.keys(S.garments || {}).map(k => '@OUT_' + k.toUpperCase())
    .filter(t => !!(S.tokens && S.tokens[t]) && (typeof tokenVisible !== 'function' || tokenVisible(t)));
  const sets = pick(['@SET_CAFE','@SET_BEDROOM','@SET_LIBRARY','@SET_ROOFTOP','@SET_BEACH','@SET_CLASSROOM',
                     '@SET_KITCHEN','@SET_CITY_STREET','@SET_GREENHOUSE','@SET_ONSEN','@SET_SCHOOL_GATE','@SET_MUSEUM']);
  const lights = pick(['@LIGHT_WIN','@LIGHT_GOLDEN','@LIGHT_NIGHT','@LIGHT_NEON','@LIGHT_RIM','@LIGHT_STUDIO',
                       '@TIME_MORNING','@TIME_AFTERNOON','@TIME_DUSK','@TIME_NIGHT','@TIME_DAWN']);
  const moods = pick(['@MOOD_CALM','@MOOD_AMUSED','@MOOD_SHY','@MOOD_EXCITED','@MOOD_TENDER','@MOOD_FOCUSED',
                      '@MOOD_SLEEPY','@MOOD_SURPRISED']);
  const gazes = pick(['@GAZE_CAMERA','@GAZE_ASIDE','@GAZE_DOWN','@GAZE_UP','@GAZE_FAR']);
  const animaLoras = (S.loraFiles || []).filter(f => {
    if (typeof loraBase === 'function' && loraBase(f) !== 'anima') return false;
    if (/turbo|modare/i.test(f)) return false;
    const cat = typeof loraCat === 'function' ? loraCat(f) : '';
    if (cat === '角色' || cat === '加速' || cat === '动作') return false;
    return isCoop ? (cat === '画师' || cat === '环境' || cat === '厚涂' || (typeof isEnvLora === 'function' && isEnvLora(f))) : cat === '画师';
  });
  const comps = pick(['@COMP_CENTER','@COMP_THIRDS','@COMP_FRAME','@COMP_NEGATIVE','@COMP_DIAGONAL']);
  return [
    { cats:[], key:'mode', title:'出图模式', sub:'先选走「常规单图直出」还是「合作重映三阶段」', multi:1,
      items: ['__mode__:direct', '__mode__:coop'] },
    { cats:['id'], key:'subject', title:'角色与身份', sub:'可选自由发挥、自有角色卡或公开预设（未选卡不会带出私有积木）', multi:2,
      items: ['__free__'].concat(cards, idPub) },
    { cats:['cam'], key:'cam', title:'机位', sub: isCoop ? '合作模式建议全身/中远景，保留足够环境空间' : '决定镜头景别与角度，先选一个', multi:1,
      items: pick(isCoop ? ['@CAM_FULL','@CAM_THREEQ','@CAM_MEDIUM','@CAM_LOW','@CAM_HIGH','@CAM_BUST']
                         : ['@CAM_BUST','@CAM_MEDIUM','@CAM_FULL','@CAM_CLOSEUP','@CAM_THREEQ','@CAM_PROFILE','@CAM_HIGH','@CAM_TOP','@CAM_WORM']) },
    { cats:['set'], key:'set', title:'场景', sub: isCoop ? '合作重映会自动放进「① 环境」主场景槽' : '可选；不选场景则保留干净背景', multi:1, skip:true, items: sets },
    { cats:['light','time'], key:'light', title:'打光与时段', sub:'先定主光源，可再补 1 块时段氛围', multi:2, skip:true, items: lights },
    { cats:['outfit'], key:'outfit', title:'服装', sub:'按当前性别过滤，选 1 套即可（自动带出配套负向）', multi:1, skip:true, items: outfits },
    { cats:['mood','gaze','hand'], key:'mood', title:'表情与视线', sub:'可选，最多两块', multi:2, skip:true, items: moods.concat(gazes) },
    { cats:['comp'], key:'comp', title: isCoop ? '构图与占比' : '构图', sub: isCoop ? '可设环境/人物默认占比（默认环境 66% / 人物 34%）' : '可选；按需要选构图规则', multi:2, skip:true,
      items: isCoop ? ['__ratio__:0.20', '__ratio__:0.25', '__ratio__:0.34', '__ratio__:0.45'].concat(comps) : comps },
    { cats:['artist'], key:'artist', title: isCoop ? '环境与画师 LoRA' : '画师 LoRA',
      sub: isCoop ? '仅显示 Anima 底模 LoRA；可同时选 1 个环境 LoRA + 1 个画师（自动带默认权重）' : '仅显示 Anima 底模画师 LoRA，自动带出推荐权重与触发词',
      multi: isCoop ? 2 : 1, skip:true, items: ['__none__'].concat(animaLoras) },
    { cats:['neg'], key:'neg', title:'负向底线', sub:'建议保留默认底线', multi:2, fixed:true,
      items: pick(g === 'm' ? ['@NEG_BASE','@NEG_HANDS','@NEG_MALE_BODY'] : ['@NEG_BASE','@NEG_HANDS']) },
  ];
}

function renderGuide() {
  const wrap = document.querySelector('#view-guide');
  if (!wrap) return;
  if (!S.guide) S.guide = { step: 0, picks: {} };
  const steps = guideSteps();
  const g = S.guide;
  if (g.step >= steps.length) g.step = steps.length - 1;
  const st = steps[g.step];
  const chosen = Array.from(new Set(g.picks[st.key] || (st.key === 'neg' ? st.items.slice() : [])));

  const stepsEl = document.querySelector('#guide-steps');
  if (stepsEl) {
    stepsEl.innerHTML = steps.map((s, i) => {
      const n = (g.picks[s.key] || (s.key === 'neg' ? s.items : [])).length;
      return '<li data-step="' + i + '" class="' + (i === g.step ? 'on' : '') + (i < g.step ? ' done' : '') + '">' +
        '<span class="idx">' + (i + 1) + '</span><span class="tt">' + s.title + '</span>' +
        (n ? '<span class="n">' + n + '</span>' : '') + '</li>';
    }).join('');
    stepsEl.querySelectorAll('li').forEach(li => li.onclick = () => { g.step = +li.dataset.step; g._scrolledStep = -1; renderGuide(); guidePreview(); });
  }

  const title = document.querySelector('#guide-title');
  if (title) title.textContent = '第 ' + (g.step + 1) + ' / ' + steps.length + ' 步 · ' + st.title;
  const sub = document.querySelector('#guide-sub');
  if (sub) sub.textContent = st.sub || '';

  const opts = document.querySelector('#guide-options');
  if (opts) {
    opts.innerHTML = st.items.map(t => {
      const on = chosen.includes(t) || (st.key === 'mode' && !chosen.length && t === ('__mode__:' + guideModeValue()));
      const meta = _guideMeta(t, st.key);
      const nt = meta.note ? meta.note.replace(/\s+/g, ' ').slice(0, 30) : '';
      return '<button class="guide-chip' + (on ? ' on' : '') + '" data-token="' + esc(t) + '" title="' + esc(meta.note) + '">' +
        '<span>' + esc(meta.label) + '</span>' + (nt ? '<span class="nt">' + esc(nt) + '</span>' : '') + '</button>';
    }).join('') || '<span class="hint">这一步没有可选项</span>';
    opts.querySelectorAll('.guide-chip').forEach(b => b.onclick = () => {
      const t = b.dataset.token;
      let arr = (g.picks[st.key] || (st.key === 'neg' ? st.items.slice() : [])).slice();
      if (arr.includes(t)) arr = arr.filter(x => x !== t);
      else {
        if (st.key === 'subject' && (t === '__free__' || t.startsWith('__card__:'))) arr = [t];
        else if (st.key === 'subject') arr = arr.filter(x => x !== '__free__' && !x.startsWith('__card__:')).slice(-(st.multi - 1)).concat([t]);
        else if (st.key === 'comp' && t.startsWith('__ratio__:')) arr = arr.filter(x => !x.startsWith('__ratio__:')).slice(-(st.multi - 1)).concat([t]);
        else if (st.key === 'artist' && t === '__none__') arr = ['__none__'];
        else if (st.key === 'artist') {
          arr = arr.filter(x => x !== '__none__');
          if (st.multi === 1) arr = [t];
          else {
            const isE = typeof isEnvLora === 'function' && isEnvLora(t);
            arr = arr.filter(x => (typeof isEnvLora === 'function' && isEnvLora(x)) !== isE).concat([t]);
          }
        } else {
          if (st.multi === 1) arr = [t];
          else if (arr.length >= st.multi) arr.shift();
          arr.push(t);
        }
      }
      if (st.fixed) arr = arr.length ? arr : st.items.slice();
      g.picks[st.key] = arr;
      renderGuide();
    });
  }

  const picked = document.querySelector('#guide-picked');
  if (picked) picked.innerHTML = chosen.length ? chosen.map(t => '<span class="chip on">' + esc(_guideMeta(t, st.key).label) + '</span>').join('') : '<span class="hint">还没选</span>';

  const prev = document.querySelector('#guide-prev');
  const next = document.querySelector('#guide-next');
  const skip = document.querySelector('#guide-skip');
  if (prev) prev.disabled = g.step === 0;
  if (next) next.textContent = g.step === steps.length - 1 ? '完成，放进画布 ✓' : '下一步 →';
  if (skip) { skip.style.display = st.skip ? '' : 'none'; }

  const bar = document.querySelector('#guide-bar');
  if (bar) bar.style.width = Math.round(((g.step + 1) / steps.length) * 100) + '%';
  const pre = document.querySelector('#guide-preview');
  if (pre) {
    const posTokens = [];
    const negTokens = [];
    steps.forEach(s => {
      if (s.key === 'mode' || s.key === 'artist') return;
      const arr = g.picks[s.key] || (s.key === 'neg' ? s.items : []);
      arr.forEach(t => {
        if (!t || t.startsWith('__')) return;
        (s.key === 'neg' ? negTokens : posTokens).push(t);
      });
    });
    if (!posTokens.length) { pre.textContent = '选几块试试…'; renderGuidePalette(); scrollGuidePaletteTo(st); return; }
    api('/api/expand', { method:'POST', body: JSON.stringify({
      positive: posTokens.map(t => ({ token: t })), negative: negTokens.map(t => ({ token: t })) }) })
      .then(r => { pre.textContent = (r.positive || '') + (negTokens.length ? '\n\n[负向] ' + (r.negative || '') : ''); })
      .catch(() => { pre.textContent = '（预览失败）'; });
  }
  renderGuidePalette();
  scrollGuidePaletteTo(st);
}


function guidePick(tok) {
  const steps = guideSteps();
  if (!S.guide) S.guide = { step: 0, picks: {} };
  const g = S.guide;
  const st = steps[g.step];
  let arr = (g.picks[st.key] || (st.key === 'neg' ? st.items.slice() : [])).slice();
  if (arr.includes(tok)) arr = arr.filter(x => x !== tok);
  else {
    if (st.multi === 1) arr = [tok];
    else if (arr.length >= st.multi) arr.shift();
    arr.push(tok);
  }
  if (st.fixed) arr = arr.length ? arr : st.items.slice();
  g.picks[st.key] = arr;
  if (st.key !== 'neg') {
    const negComps = companionsOf(tok).filter(c => c.lane === 'negative').map(c => c.token);
    const posComps = companionsOf(tok).filter(c => c.lane === 'positive').map(c => c.token);
    if (negComps.length && g.suppressNeg) g.suppressNeg = g.suppressNeg.filter(x => negComps.indexOf(x) < 0);
    if (posComps.length && g.suppressPos) g.suppressPos = g.suppressPos.filter(x => posComps.indexOf(x) < 0);
  }
  renderGuide();
  renderGuidePalette();
}

function renderGuideCurrent() {
  const steps = guideSteps();
  const g = S.guide || { picks: {} };
  const pos = [], neg = [];
  steps.forEach(st => {
    const arr = g.picks[st.key] || (st.key === 'neg' ? st.items : []);
    if (st.key === 'mode' || st.key === 'artist') return;
    arr.forEach(t => {
      if (!t || t.startsWith('__')) return;
      if (st.key === 'neg') { if (!neg.includes(t)) neg.push(t); }
      else if (!pos.includes(t)) pos.push(t);
    });
  });
  pos.forEach(t => companionsOf(t).forEach(c => {
    if (c.lane === 'negative') {
      if (S.guide.suppressNeg && S.guide.suppressNeg.indexOf(c.token) >= 0) return;
      if (!neg.includes(c.token)) neg.push(c.token);
    } else {
      if (S.guide.suppressPos && S.guide.suppressPos.indexOf(c.token) >= 0) return;
      if (!pos.includes(c.token)) pos.push(c.token);
    }
  }));
  const chip = (t, isNeg) => {
    const cat = tokenCat(t);
    return '<span class="gc-chip' + (isNeg ? ' neg' : '') + '" data-cat="' + cat + '" data-token="' + t + '">' + t +
      '<span class="gc-x" data-gc-del="' + t + '" data-gc-lane="' + (isNeg ? 'neg' : 'pos') + '" title="移除">×</span></span>';
  };
  const boxP = document.querySelector('#gc-pos'), boxN = document.querySelector('#gc-neg');
  if (boxP) boxP.innerHTML = pos.length ? pos.map(t => chip(t, false)).join('') : '<span class="hint">还没选，从右侧积木库点选</span>';
  if (boxN) boxN.innerHTML = neg.length ? neg.map(t => chip(t, true)).join('') : '<span class="hint">自动补配套负向</span>';
  const np = document.querySelector('#gc-pos-n'), nn = document.querySelector('#gc-neg-n');
  if (np) np.textContent = pos.length + ' 块';
  if (nn) nn.textContent = neg.length + ' 块';
  boxP && boxP.querySelectorAll('.gc-chip').forEach(el => {
    el.onclick = () => { if (boxP) {} };
    el.onmouseenter = ev => showTip(ev, el.dataset.token);
    el.onmousemove = ev => moveTip(ev);
    el.onmouseleave = () => hideTip();
  });
  boxN && boxN.querySelectorAll('.gc-chip').forEach(el => {
    el.onmouseenter = ev => showTip(ev, el.dataset.token);
    el.onmousemove = ev => moveTip(ev);
    el.onmouseleave = () => hideTip();
  });
  document.querySelectorAll('[data-gc-del]').forEach(x => {
    x.onclick = ev => {
      ev.stopPropagation();
      const t = x.getAttribute('data-gc-del');
      if (x.dataset.gcLane === 'pos') {
        let picked = false;
        steps.forEach(st => {
          if (st.key === 'neg') return;
          const arr = S.guide.picks[st.key] || [];
          if (arr.indexOf(t) >= 0) { S.guide.picks[st.key] = arr.filter(v => v !== t); picked = true; }
        });
        if (!picked) {
          S.guide.suppressPos = S.guide.suppressPos || [];
          if (S.guide.suppressPos.indexOf(t) < 0) S.guide.suppressPos.push(t);
        }
      } else {
        const negArr = S.guide.picks['neg'] || [];
        if (negArr.indexOf(t) >= 0) S.guide.picks['neg'] = negArr.filter(v => v !== t);
        else { S.guide.suppressNeg = S.guide.suppressNeg || []; if (S.guide.suppressNeg.indexOf(t) < 0) S.guide.suppressNeg.push(t); }
      }
      renderGuide();
    };
  });
}

function scrollGuidePaletteTo(st) {
  if (!st || !st.cats || !S.guide) return;
  if (S.guide._scrolledStep === S.guide.step) return;
  const box = document.querySelector('#guide-pal-body');
  if (!box) return;
  let target = null;
  for (const c of st.cats) {
    const el = box.querySelector('.pal-group[data-cat="' + c + '"]');
    if (el) { target = el; break; }
  }
  if (!target) return;
  const top = target.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop - 6;
  box.scrollTop = Math.max(0, top);
  S.guide._scrolledStep = S.guide.step;
}

function renderGuidePalette() {
  renderGuideCurrent();
  const box = document.querySelector('#guide-pal-body');
  if (!box) return;
  const q = ((S.guideFilter || '')).toLowerCase();
  const hidden = S.showCompanionNeg ? new Set() : companionNegSet();
  const order = ['id','body','pose','face','mood','gaze','hand','hold','weapon','hair','cam','light','atmo','time',
                 'outfit','fabric','drape','set','prop','comp','style','nsfw','neg','custom'];
  const groups = {};
  Object.keys(S.tokens || {}).forEach(k => {
    if (hidden.has(k)) return;
    if (typeof tokenVisible === 'function' && !tokenVisible(k)) return;
    if (q && !k.toLowerCase().includes(q)) return;
    const c = tokenCat(k);
    (groups[c] = groups[c] || []).push(k);
  });
  let html = '';
  for (const key of order) {
    const items = (groups[key] || []).sort();
    if (!items.length) continue;
    html += '<div class="pal-group" data-cat="' + key + '"><span class="caret">▾</span>' +
      (CAT_LABEL[key] || key) + '<span class="num">' + items.length + '</span></div><div class="pal-items">';
    for (const t of items) {
      const fav = (S.fav || []).includes(t);
      html += '<div class="pal-item" data-token="' + t + '" data-cat="' + key + '"><span class="tk">' + t + '</span>' +
        '<span class="fav' + (fav ? ' on' : '') + '" data-fav="' + t + '" title="收藏">★</span>' +
        '<span class="add">＋</span></div>';
    }
    html += '</div>';
  }
  box.innerHTML = html || '<div class="hint" style="padding:8px">没有匹配的积木</div>';
  box.querySelectorAll('.pal-item').forEach(el => {
    const tok = el.dataset.token;
    el.onclick = () => guidePick(tok);
    el.onmouseenter = ev => showTip(ev, tok);
    el.onmousemove = ev => moveTip(ev);
    el.onmouseleave = () => hideTip();
  });
  box.querySelectorAll('.fav').forEach(st => {
    st.onclick = ev => {
      ev.stopPropagation();
      const t = st.dataset.fav;
      S.fav = S.fav || [];
      S.fav = S.fav.includes(t) ? S.fav.filter(x => x !== t) : S.fav.concat(t);
      saveJSON('loom.fav', S.fav);
      renderGuidePalette(); renderPalette();
    };
  });
}

function guidePreview() {
  const steps = guideSteps();
  const g = S.guide || { picks: {} };
  const pos = [], neg = [];
  const pushTok = (lane, t) => {
    if (!t || t === '__none__' || /\.safetensors$/i.test(t)) return;
    const arr = lane === 'negative' ? neg : pos;
    if (arr.some(b => b.token === t)) return;
    arr.push({ id: uid(), token: t, text: '', weight: 1, enabled: true });
    if (typeof companionsOf === 'function') {
      companionsOf(t).forEach(c => {
        const target = c.lane === 'negative' ? neg : pos;
        if (!target.some(b => b.token === c.token)) target.push({ id: uid(), token: c.token, text: '', weight: 1, enabled: true, auto: true });
      });
    }
  };
  steps.forEach(s => (g.picks[s.key] || (s.key === 'neg' ? s.items : [])).forEach(t => {
    if (!t || t.startsWith('__')) return;
    pushTok(s.key === 'neg' ? 'negative' : 'positive', t);
  }));
  const chip = b => '<span class="chip on">' + esc(b.token || b.text.slice(0, 18)) + '</span>';
  const gp = document.querySelector('#gc-pos'), gn = document.querySelector('#gc-neg');
  if (gp) gp.innerHTML = pos.length ? pos.map(chip).join('') : '<span class="hint">空</span>';
  if (gn) gn.innerHTML = neg.length ? neg.map(chip).join('') : '<span class="hint">空</span>';
  const gpn = document.querySelector('#gc-pos-n'), gnn = document.querySelector('#gc-neg-n');
  if (gpn) gpn.textContent = pos.length + ' 块';
  if (gnn) gnn.textContent = neg.length + ' 块';
  clearTimeout(guidePreview._t);
  guidePreview._t = setTimeout(async () => {
    try {
      const r = await api('/api/expand', { method: 'POST', body: JSON.stringify({ positive: pos, negative: neg }) });
      const box = document.querySelector('#guide-preview');
      if (box) box.textContent = (r.positive || '') + '\n---\n' + (r.negative || '');
    } catch (e) {}
  }, 240);
}

function guideApply() {
  pushHistory();
  const steps = guideSteps();
  const g = S.guide || { picks: {} };
  const mode = guideModeValue();
  const wantCoop = mode === 'coop';
  let added = 0;

  const b = document.querySelector('#tabs button[data-tab="build"]');
  if (b) b.click();
  if (!wantCoop && S.coopOn && typeof coopToggle === 'function') coopToggle();

  const subjPicks = g.picks['subject'] || [];
  const cardToken = subjPicks.find(t => t.startsWith('__card__:'));
  const wantFree = subjPicks.includes('__free__');
  const ratioPick = (g.picks['comp'] || []).find(t => t.startsWith('__ratio__:'));
  const artistPicks = (g.picks['artist'] || []).filter(x => x && x !== '__none__');
  const envLoraPick = artistPicks.find(x => typeof isEnvLora === 'function' && isEnvLora(x));
  const charLoraPick = artistPicks.find(x => !(typeof isEnvLora === 'function' && isEnvLora(x)));

  const prevRouting = S._coopRouting;
  S._coopRouting = false;
  try {
    S.pos = [];
    S.neg = [];
    if (S.coop) S.coop = { commonPos: [], commonNeg: [], envPos: [], chrPos: [], chrNeg: [] };

    const posTokens = [];
    steps.forEach(s => {
      if (s.key === 'mode' || s.key === 'artist' || s.key === 'neg') return;
      Array.from(new Set(g.picks[s.key] || [])).forEach(t => {
        if (!t || t.startsWith('__') || ((S.loraFiles || []).includes(t) && typeof loraCat === 'function' && loraCat(t) !== '角色')) return;
        posTokens.push(t);
      });
    });

    const cardSel = $('#card-sel');
    const idSel = $('#identity-strength');
    if (cardToken) {
      const cname = cardToken.slice(9);
      const card = (S.cards || []).find(c => c.name === cname);
      if (cardSel) cardSel.value = cname;
      if (card) {
        S.loras = (S.loras || []).filter(l => loraCat(l.name) !== '角色').concat((card.loras || []).map(l => ({ name: l.name, weight: Number(l.weight) || 1 })));
        const lvl = idSel ? Number(idSel.value) : 0.5;
        if (lvl >= 1) {
          (card.tokens || []).map(resolveToken).forEach(tok => { if (!S.pos.some(x => x.token === tok)) { S.pos.push({ id: uid(), token: tok, text: '', weight: 1, enabled: true, cardIdentity: true }); added++; } });
        } else if (lvl > 0) {
          const wt = (card.identity_weak || '').trim() || TEXT_ID;
          S.pos.push({ id: uid(), token: '', text: wt, weight: lvl, enabled: true, cardIdentity: true }); added++;
        }
        (card.neg_blocks || []).forEach(nb => {
          const tok = (nb && nb.token) || '', txt = (nb && nb.text) || '';
          if ((tok || txt.trim()) && (!tok || !S.neg.some(x => x.token === tok))) {
            S.neg.push({ id: uid(), token: tok, text: tok ? '' : txt, weight: Number(nb && nb.weight) || 1, enabled: true, cardIdentity: true });
          }
        });
      }
    } else {
      if (cardSel) cardSel.value = '';
      S.loras = (S.loras || []).filter(l => loraCat(l.name) !== '角色');
      if (wantFree) {
        if (idSel) idSel.value = '0';
        S.pos.push({ id: uid(), token: '', text: S.gender === 'm' ? TEXT_ID_MIN_MALE : TEXT_ID_MIN, weight: 1, enabled: true, identityMin: true });
        added++;
      }
    }

    posTokens.forEach(t => {
      if (S.pos.some(x => x.token === t)) return;
      addBlock('positive', t); added++;
    });
    const negTokens = g.picks['neg'] || steps.find(s => s.key === 'neg').items;
    negTokens.forEach(t => {
      if (!t || t.startsWith('__') || S.neg.some(x => x.token === t)) return;
      addBlock('negative', t); added++;
    });

    const supPos = g.suppressPos || [], supNeg = g.suppressNeg || [];
    if (supPos.length || supNeg.length) {
      S.pos = S.pos.filter(x => !(x.auto && supPos.indexOf(x.token) >= 0));
      S.neg = S.neg.filter(x => !(x.auto && supNeg.indexOf(x.token) >= 0));
    }

    const slSel = $('#style-lora');
    if (slSel) slSel.value = charLoraPick || '';
    if (typeof applyStyleLora === 'function') applyStyleLora(charLoraPick || '');
    if (charLoraPick) added++;
  } finally {
    S._coopRouting = prevRouting;
  }

  if (wantCoop) {
    if (!S.coopOn && typeof coopToggle === 'function') coopToggle();
    else if (typeof coopSplit === 'function') { coopSplit(); renderCoopLanes(); coopBind(); }
    if (ratioPick) {
      const rSel = $('#coop-ratio');
      if (rSel) rSel.value = ratioPick.slice(10);
    }
    const envSel = document.querySelector('#coop-slora-row #coop-slora') || $('#coop-slora');
    if (envLoraPick && envSel) {
      envSel.value = envLoraPick;
      envSel.dispatchEvent(new Event('change'));
      added++;
    }
    const cwEl = $('#coop-char-w');
    if (cwEl && charLoraPick && typeof coopLoraDefaultWeight === 'function') {
      cwEl.value = coopLoraDefaultWeight(charLoraPick, 'char').toFixed(2);
      delete cwEl.dataset.manual;
    }
  } else {
    renderLanes();
  }
  if (typeof renderLoras === 'function') renderLoras();
  expandPreview();
  toast('向导（' + (wantCoop ? '合作重映' : '常规直出') + '）已填入 ' + added + ' 项到工作台');
}

/* ---------- 事件绑定 ---------- */
function bindUI() {
  $$('#tabs button').forEach(b => b.onclick = () => {
    $$('#tabs button').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    $$('.view').forEach(v => v.classList.remove('active'));
    $('#view-' + b.dataset.tab).classList.add('active');
    if (b.dataset.tab === 'guide') renderGuide();
    if (b.dataset.tab === 'library') renderCombos();
    if (b.dataset.tab === 'gallery') renderGallery();
    if (b.dataset.tab === 'recipe') loadRecipes();
    if (b.dataset.tab === 'train') trainInfo();
    if (b.dataset.tab === 'maint') refreshMaint();
    if (b.dataset.tab === 'engine') loadEngine();
  });
  const gcPosClear = $('#gc-pos-clear'), gcNegClear = $('#gc-neg-clear');
  if (gcPosClear) gcPosClear.onclick = () => {
    const steps = guideSteps();
    steps.forEach(st => { if (st.key !== 'neg') delete S.guide.picks[st.key]; });
    renderGuide(); toast('已清空正向选择');
  };
  if (gcNegClear) gcNegClear.onclick = () => {
    S.guide.picks['neg'] = []; renderGuide(); toast('已清空负向选择');
  };
  const gSearch = $('#guide-search');
  if (gSearch) gSearch.oninput = e => { S.guideFilter = e.target.value; renderGuidePalette(); };
  const openGuide = $('#open-guide');
  if (openGuide) openGuide.onclick = () => { const b = document.querySelector('#tabs button[data-tab="guide"]'); if (b) b.click(); };
  const gPrev = $('#guide-prev'), gNext = $('#guide-next'), gSkip = $('#guide-skip');
  if (gPrev) gPrev.onclick = () => { if (S.guide && S.guide.step > 0) { S.guide.step--; renderGuide(); } };
  if (gNext) gNext.onclick = () => {
    const n = guideSteps().length;
    if (!S.guide) S.guide = { step: 0, picks: {} };
    if (S.guide.step >= n - 1) guideApply(); else { S.guide.step++; renderGuide(); }
  };
  if (gSkip) gSkip.onclick = () => {
    if (!S.guide) S.guide = { step: 0, picks: {} };
    S.guide.step = Math.min(S.guide.step + 1, guideSteps().length - 1);
    renderGuide();
  };
  $('#palette-search').oninput = e => { S.paletteFilter = e.target.value; renderPalette(); };
  const comboNew = $('#combo-save-new'), comboForm = $('#combo-save-form');
  const comboName = $('#combo-save-name');
  if (comboNew && comboForm) {
    comboNew.onclick = () => {
      comboForm.hidden = !comboForm.hidden;
      if (!comboForm.hidden) { comboName.value = ''; comboName.focus(); }
    };
    $('#combo-save-cancel').onclick = () => { comboForm.hidden = true; };
    $('#combo-save-btn').onclick = () => {
      const name = (comboName.value || '').trim();
      if (!name) return toast('给组合起个名字');
      const toks = S.pos.concat(S.neg).map(b => b.token).filter(Boolean);
      if (!toks.length) return toast('画布还是空的');
      const list = userCombos().filter(c => c.name !== name);
      list.push({ name: name, tokens: Array.from(new Set(toks)) });
      saveUserCombos(list);
      comboForm.hidden = true;
      renderCombos();
      toast('已保存组合「' + name + '」（' + toks.length + ' 块）');
    };
  }
  const showNeg = $('#pal-show-neg');
  if (showNeg) {
    S.showCompanionNeg = loadJSON('loom.showCompanionNeg', false);
    showNeg.checked = !!S.showCompanionNeg;
    showNeg.onchange = e => {
      S.showCompanionNeg = e.target.checked;
      saveJSON('loom.showCompanionNeg', S.showCompanionNeg);
      renderPalette();
    };
  }
  // 性别开关：切女/男，同步更新主积木库、向导、角色卡与服装页
  const genderBtns = () => $$('#pal-gender button, #guide-gender button');
  if (genderBtns().length) {
    S.gender = loadJSON('loom.gender', 'f') === 'm' ? 'm' : 'f';
    const syncGender = () => {
      genderBtns().forEach(b => b.classList.toggle('on', b.dataset.g === S.gender));
    };
    const pruneGuideGender = () => {
      if (!S.guide || !S.guide.picks) return;
      ['subject', 'outfit', 'neg'].forEach(k => {
        const arr = S.guide.picks[k];
        if (!Array.isArray(arr)) return;
        S.guide.picks[k] = arr.filter(t => {
          if (!t || t === '__free__') return true;
          if (t.startsWith('__card__:')) {
            const card = (S.cards || []).find(c => c.name === t.slice(9));
            return !card || (card.gender || 'f') === S.gender;
          }
          if (t.startsWith('__')) return true;
          return typeof tokenVisible !== 'function' || tokenVisible(t);
        });
      });
    };
    syncGender();
    genderBtns().forEach(b => b.onclick = () => {
      if (b.dataset.g === S.gender) return;
      S.gender = b.dataset.g;
      saveJSON('loom.gender', S.gender);
      syncGender();
      renderPalette();
      try { loadCards(); } catch (e) {}
      try { if (typeof renderGarmentList === 'function') renderGarmentList(); } catch (e) {}
      pruneGuideGender();
      try { renderGuide(); } catch (e) {}
      if (S.gender === 'm' && currentCardName()) {
        const card = (S.cards || []).find(x => x.name === currentCardName());
        if (card && (card.gender || 'f') !== 'm') toast('男性模式：' + card.name + ' 是女性角色卡，专属积木已隐藏', true);
      }
      toast('已切换：' + (S.gender === 'm' ? '男性版' : '女性版'));
    });
  }
  $('#lib-search').oninput = e => loadLibrary(e.target.value);
  document.querySelectorAll('[data-adddesc]').forEach(b => b.onclick = () => {
    openTextBlockDialog({ lane: b.dataset.adddesc, title: '插入描述', weight: 1.1 });
  });
  document.querySelectorAll('[data-addtext]').forEach(b => b.onclick = () => {
    openTextBlockDialog({ lane: b.dataset.addtext, title: '添加文本块' });
  });
  const dp = $('#desc-pos'); if (dp) dp.onclick = () => insertDesc('positive');
  const dn = $('#desc-neg'); if (dn) dn.onclick = () => insertDesc('negative');
  const ds = $('#desc-save'); if (ds) ds.onclick = () => saveDescAsBlock();
  const tplCreate = $('#tpl-create');
  if (tplCreate && !tplCreate.dataset.bound) { tplCreate.dataset.bound = '1'; tplCreate.onclick = saveCurrentAsTemplate; }
  $$('[data-clear]').forEach(b => b.onclick = () => {
    pushHistory();
    if (b.dataset.clear === 'positive') S.pos = []; else S.neg = [];
    renderLanes(); expandPreview();
  });
  $('#run-btn').onclick = () => { if (S.coopOn) { coopStart(); } else { run(); } };
  const goTab = name => { const b = document.querySelector('#tabs button[data-tab="' + name + '"]'); if (b) b.click(); };

  const pc0 = $('#pal-collapse');
  if (pc0) pc0.onclick = () => setLibCollapsed(true);
  const fab = $('#lib-fab');
  if (fab) fab.onclick = () => setLibCollapsed(false);
  setLibCollapsed(false);  // 不再收起积木库

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
  const pSize = $('#p-size'), customSize = $('#custom-size');
  const syncCustom = () => {
    if (customSize) customSize.hidden = !(pSize && pSize.value === 'custom');
    updateEta();
  };
  if (pSize) pSize.onchange = syncCustom;
  ['#p-w', '#p-h'].forEach(sel => { const el = $(sel); if (el) el.oninput = updateEta; });
  syncCustom();
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
    if (S.gallerySelect) S.galleryDelMode = false;
    if (!S.gallerySelect) S.gallerySel = {};
    gsel.textContent = S.gallerySelect ? '退出选择' : '选择导出';
    renderGallery();
  };
  const gdelMode = $('#g-del-mode');
  if (gdelMode) gdelMode.onclick = () => {
    S.galleryDelMode = !S.galleryDelMode;
    if (S.galleryDelMode) S.gallerySelect = false;
    if (!S.galleryDelMode) S.gallerySel = {};
    gdelMode.textContent = S.galleryDelMode ? '退出删除' : '批量删除';
    if (gsel) gsel.textContent = '选择导出';
    renderGallery();
  };

  const gexp = $('#g-export');
  if (gexp) gexp.onclick = exportSelected;
  $('#g-refresh').onclick = renderGallery;
  $('#tk-save').onclick = saveToken;
  $('#tk-del').onclick = delToken;
  // 备注已合并进「保存」
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
  const mtClassify = $('#mt-classify');
  if (mtClassify) mtClassify.onclick = async () => {
    try {
      const r = await fetch('/api/lib/classify?apply=true', { method: 'POST' }).then(x => x.json());
      $('#mt-log').textContent = r.output || '';
      toast(r.ok ? '积木分类已更新' : '分类失败，看日志');
    } catch (e) { toast('分类失败：' + e.message, true); }
  };
  const draftsDry = $('#mt-drafts-dry');
  if (draftsDry) draftsDry.onclick = async () => {
    try {
      const r = await fetch('/api/maintenance/drafts?dry=true', { method: 'POST' }).then(x => x.json());
      $('#mt-log').textContent = '半成品 ' + r.count + ' 个 · ' + r.mb + ' MB\n' + (r.sample || []).join('\n');
      toast('半成品 ' + r.count + ' 个 · ' + r.mb + ' MB');
    } catch (e) { toast('预演失败：' + e.message, true); }
  };
  const draftsRun = $('#mt-drafts-run');
  if (draftsRun) draftsRun.onclick = async () => {
    try {
      const pre = await fetch('/api/maintenance/drafts?dry=true', { method: 'POST' }).then(x => x.json());
      if (!pre.count) { toast('没有半成品需要清理'); return; }
      if (!confirm('把 ' + pre.count + ' 个半成品（' + pre.mb + ' MB）移到回收站？\n成品、服装样张不动。')) return;
      const r = await fetch('/api/maintenance/drafts?dry=false', { method: 'POST' }).then(x => x.json());
      $('#mt-log').textContent = '已移入回收站 ' + r.moved + ' / ' + r.count + ' 个 · ' + r.mb + ' MB\n' + (r.trash || '');
      toast('已清理 ' + r.moved + ' 个半成品');
    } catch (e) { toast('清理失败：' + e.message, true); }
  };
  $('#help-btn').onclick = async () => {
    const r = await api('/api/features');
    const body = r.groups.map(g =>
      '<h4 style="margin:14px 0 6px">' + g.group + '</h4><ul style="margin:0;padding-left:18px">' +
      g.items.map(i => '<li style="font-size:12.5px;color:#c3c9d6;margin:2px 0">' + i + '</li>').join('') + '</ul>').join('');
    openModal('功能总览', body);
  };
  coopFillLoras();
  if (typeof coopAutoBind === 'function') coopAutoBind();
  if (typeof coopRegionalBind === 'function') coopRegionalBind();
  if (typeof bindEnvDetail === 'function') bindEnvDetail();
  const syncPainter = (sel, target) => {
    if (!sel) return;
    sel.addEventListener('change', () => {
      const t = $(target);
      if (t) t.value = (typeof loraBase === 'function' && loraBase(sel.value) === 'other') ? 'other' : 'anima';
    });
  };
  syncPainter(document.querySelector('#coop-slora-row #coop-slora'), '#coop-bg-painter');
  syncPainter($('#style-lora'), '#coop-char-painter');
  const asel = $('#artist-strength');
  if (asel) asel.onchange = applyArtistStrength;
  const isel = $('#identity-strength');
  if (isel) {
    let prevId = isel.value;
    isel.addEventListener('focus', () => { prevId = isel.value; });
    isel.onchange = () => { identityChangeGuard(prevId); prevId = isel.value; };
  }
  bindAllArtistHovers();
  if ($('#coop-slora')) {
    const envPick = document.querySelector('#coop-slora-row #coop-slora') || $('#coop-slora');
    envPick.addEventListener('change', () => {
      if (!S.coopOn) return;
      S.loras = (S.loras || []).filter(l => l.coop !== 'env');
      const v = envPick.value;
      const ew = (typeof coopLoraDefaultWeight === 'function') ? coopLoraDefaultWeight(v, 'env') : 0.70;
      if (v) S.loras.push({ name: v, weight: ew, coop: 'env' });
      const ewi = $('#coop-env-w'); if (ewi && !ewi.dataset.manual) ewi.value = ew.toFixed(2);
      if (typeof renderLoras === 'function') renderLoras();
    });
  }
  ['#coop-env-w', '#coop-char-w'].forEach(sel => {
    const el = $(sel);
    if (el) el.addEventListener('change', () => { el.dataset.manual = '1'; });
  });
  const replan = () => coopApplyRoute().then(() => toast('模型已重新判断')).catch(() => toast('判断失败', true));
  if ($('#coop-replan')) $('#coop-replan').onclick = replan;
  if ($('#coop-replan-inline')) $('#coop-replan-inline').onclick = replan;
  if ($('#coop-mode')) $('#coop-mode').addEventListener('change', () => coopPlanRender(''));
  coopPlanRender('');
  if ($('#coop-toggle')) {
    $('#coop-toggle').onclick = coopToggle;
    if (loadJSON('loom.coopOn', false)) { try { coopToggle(); } catch (e) {} }
  }
  $('#modal-close').onclick = closeModal;
  $('#modal').onclick = e => {
    if (e.target.id !== 'modal') return;
    if (document.querySelector('.brain-shell')) return;
    closeModal();
  };
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
  try { resumeLastJob(); } catch (e) {}
  const gk0 = Object.keys(S.garments || {})[0]; if (gk0) loadGarment(gk0); else newGarment();
  loadRecipes();
  expandPreview();
  const pollStatus = async () => {
    try {
      const st = await api('/api/status');
      const q = { comfy: st.comfy, queue: st.queue };
      $('#pill-comfy').textContent = q.comfy.up ? ('ComfyUI ' + q.comfy.version) : 'ComfyUI 启动中…';
      $('#pill-comfy').className = 'pill ' + (q.comfy.up ? 'ok' : 'bad');
      const n = q.queue.running + q.queue.pending;
      $('#pill-queue').textContent = '队列 ' + n;
      $('#pill-queue').className = 'pill' + (n > 0 ? ' run' : '');
    } catch (e) {}
    setTimeout(pollStatus, (S.comfy && S.comfy.up) ? 15000 : 3000);
  };
  pollStatus();
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
                     cfg: Number($('#tpl-cfg').value || 5.5) , model: ($('#p-model') || {}).value || '' };
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
  const keepName = sel.value;   // 保存/刷新后保持当前选中的卡，不然要重新选
  const g = (typeof S.gender === 'string' && S.gender === 'm') ? 'm' : 'f';
  const list = (S.cards || []).filter(c => (c.gender || 'f') === g);
  sel.innerHTML = (list.length
    ? '<option value="">（不选角色）</option>' + list.map(c =>
        '<option value="' + esc(c.name) + '">' + esc(c.name) + ((c.gender || 'f') === 'm' ? ' · 男' : ' · 女') + '</option>').join('')
    : '<option value="">（没有' + (g === 'm' ? '男' : '女') + '性角色卡）</option>');
  if (keepName && list.some(c => c.name === keepName)) sel.value = keepName;
  if (!sel._cardBound) {
    sel._cardBound = true;
    sel.onchange = () => {
      try { renderPalette(); } catch (e) {}
      if (sel.value) return;
      // 没选角色：把私有/角色卡特征积木、角色 LoRA 一并摘掉
      const isCardPrivate = b => b && (b.cardIdentity || !!tokenOwner(b.token));
      const hadPos = (S.pos || []).some(isCardPrivate);
      const hadNeg = (S.neg || []).some(isCardPrivate);
      const hadRoleLora = (S.loras || []).some(l => loraCat(l.name) === '角色');
      if (hadPos) S.pos = (S.pos || []).filter(b => !isCardPrivate(b));
      if (hadNeg) S.neg = (S.neg || []).filter(b => !isCardPrivate(b));
      if (hadRoleLora) {
        S.loras = (S.loras || []).filter(l => loraCat(l.name) !== '角色');
        try { if (typeof renderLoras === 'function') renderLoras(); } catch (e) {}
      }
      if (!hadPos && !hadNeg && !hadRoleLora) return;
      try { if (S.coopOn && typeof renderCoopLanes === 'function') renderCoopLanes(); else renderLanes(); } catch (e) {}
      try { expandPreview(); } catch (e) {}
      toast('未选角色卡：已移除私有特征积木与角色 LoRA');
    };
  }
}

function currentBaseModel() {
  return (($('#p-model') || {}).value) || '';
}

function cardApply() {
  const sel = $('#card-sel');
  const c = (S.cards || []).find(x => x.name === (sel && sel.value));
  if (!c) { toast('先保存一张角色卡'); return; }
  if ((c.gender || 'f') !== S.gender) {
    toast('这张卡是' + ((c.gender || 'f') === 'm' ? '男' : '女') + '性角色，先切换积木库的性别再应用', true);
    return;
  }
  pushHistory();
  S.loras = (c.loras || []).map(l => ({ name: l.name, weight: Number(l.weight) || 1 }));
  (c.loras || []).forEach(l => { if (!S.loraFiles.includes(l.name)) S.loraFiles.push(l.name); });
  renderLoras();

  // 身份调度：强身份 → 专有积木块；弱身份 → 文本；换底模 → 自动降级为弱身份
  const lvl = Number(($('#identity-strength') || {}).value);
  const cardBase = c.base || '';
  const cur = currentBaseModel();
  const baseMismatch = !!(cardBase && cur && loraBase(cur) !== loraBase(cardBase));
  const useStrong = lvl >= 1 && !baseMismatch;

  // 先清掉上一张卡的痕迹：身份积木以及带 cardIdentity 标记的文本块
  S.pos = (S.pos || []).filter(b => !isIdentityToken(b.token) || !useStrong);
  S.pos = (S.pos || []).filter(b => !b.cardIdentity);

  if (useStrong) {
    (c.tokens || []).map(resolveToken).forEach(tok => {
      if (!S.pos.some(b => b.token === tok)) {
        S.pos.push({ id: uid(), token: tok, text: '', weight: 1, enabled: true, cardIdentity: true });
      }
    });
    if (!S.pos.some(b => isIdentityToken(b.token))) {
      const fallback = (c.tokens || []).map(resolveToken).find(t => isIdentityToken(t))
        || (S.gender === 'm' ? '@ID_M' : '@ID_F');
      S.pos.unshift({ id: uid(), token: fallback, text: '', weight: 1, enabled: true, cardIdentity: true });
    }
  } else if (lvl > 0) {
    const weak = (c.identity_weak || '').trim() || ('1girl, solo, ' + ((c.persona || '').split(/\n/)[0] || c.name) + ', short dark hair');
    S.pos.push({ id: uid(), token: '', text: weak, weight: lvl, enabled: true, cardIdentity: true });
  }

  // 专属负向：和正向一样带 cardIdentity 标记，取消选角时一并摘掉
  S.neg = (S.neg || []).filter(b => !b.cardIdentity);
  (c.neg_blocks || []).forEach(b => {
    const tok = (b && b.token) || '';
    const txt = (b && b.text) || '';
    if (!tok && !txt.trim()) return;
    if (tok && S.neg.some(x => x.token === tok)) return;
    S.neg.push({ id: uid(), token: tok, text: tok ? '' : txt, weight: Number(b && b.weight) || 1, enabled: true, cardIdentity: true });
  });

  renderLanes(); expandPreview();
  toast('已应用角色卡：' + c.name + (baseMismatch ? '（底模不同，已用弱身份）' : (useStrong ? '（强身份积木）' : '')));
}

// 修改角色卡：人设 / 弱身份 / 底模 / 角色 LoRA / 专属正向 / 专属负向
function cardBlocksOf(card, lane) {
  const raw = lane === 'pos'
    ? ((card.pos_blocks && card.pos_blocks.length) ? card.pos_blocks : (card.tokens || []))
    : (card.neg_blocks || []);
  return raw.map(x => (typeof x === 'string')
    ? { token: x.startsWith('@') ? x : '', text: x.startsWith('@') ? '' : x, weight: 1 }
    : { token: x.token || '', text: x.text || '', weight: Number(x.weight) || 1 });
}

// 用工作台同款 chip 样式画一个小泳道
function renderCardBlocks(host, blocks, lane) {
  if (!host) return;
  host.innerHTML = blocks.map((b, i) => {
    const body = b.token ? '<span class="tk">' + esc(b.token) + '</span>'
      : '<span class="txt">' + esc(b.text || '（空）') + '</span>';
    const cat = b.token ? tokenCat(b.token) : 'custom';
    return '<div class="chip ' + (lane === 'pos' ? 'pos' : 'neg') + '" data-i="' + i + '" data-cat="' + cat + '"' +
      (b.token ? ' data-token="' + esc(b.token) + '"' : '') + '>' +
      body +
      '<input type="number" step="0.05" min="0" max="3" value="' + b.weight + '" data-w="' + i + '" title="权重">' +
      '<button class="x" data-x="' + i + '">×</button></div>';
  }).join('') || '<span class="hint">还没有积木</span>';
  host.querySelectorAll('[data-w]').forEach(inp => inp.oninput = () => {
    blocks[Number(inp.dataset.w)].weight = Number(inp.value) || 1;
  });
  host.querySelectorAll('[data-x]').forEach(btn => btn.onclick = () => {
    blocks.splice(Number(btn.dataset.x), 1);
    renderCardBlocks(host, blocks, lane);
  });
}

function cardPersonaEdit() {
  const sel = $('#card-sel');
  const name = sel && sel.value;
  const c = (S.cards || []).find(x => x.name === name);
  if (!c) { toast('先选一张角色卡', true); return; }
  const pos = cardBlocksOf(c, 'pos');
  const neg = cardBlocksOf(c, 'neg');

  const models = [...new Set([...(S.models || []), ...(S.altModels || [])])];
  const baseOpts = '<option value="">（不限，换底模时自动降级弱身份）</option>' +
    models.map(m => '<option value="' + esc(m) + '"' + (m === (c.base || '') ? ' selected' : '') + '>' + esc(m) + '</option>').join('');
  const loras = (S.loraFiles || []).slice().sort((a, b) => (loraCat(b) === '角色' ? 1 : 0) - (loraCat(a) === '角色' ? 1 : 0));
  const curLora = (c.loras || []).find(l => { try { return loraCat(l.name) === '角色'; } catch (e) { return false; } }) || (c.loras || [])[0] || {};
  const loraOpts = '<option value="">（不指定角色 LoRA）</option>' + loras.map(n =>
    '<option value="' + esc(n) + '"' + (n === curLora.name ? ' selected' : '') + '>' + esc(shortLoraName(n)) + ' · ' + esc(loraCat(n)) + '</option>').join('');
  const tokenList = '<datalist id="cp-token-list">' +
    Object.keys(S.tokens || {}).filter(tokenVisible).map(t => '<option value="' + esc(t) + '">').join('') + '</datalist>';

  openModal('修改 · ' + c.name,
    '<p class="hint">专属正向/负向就是这张卡的特征积木：点「应用」时落进画布，取消选角时自动摘掉。</p>' +
    '<div class="field"><label>人设（可多行）</label><textarea id="cp-persona" rows="4">' + esc(c.persona || '') + '</textarea></div>' +
    '<div class="field"><label>弱身份文本（换底模/弱身份时使用）</label>' +
      '<textarea id="cp-weak" rows="3" placeholder="1girl, solo, short dark hair, warm brown eyes, anime character">' +
      esc(c.identity_weak || '') + '</textarea></div>' +
    '<div class="row2">' +
      '<div class="field"><label>对应底模</label><select id="cp-base">' + baseOpts + '</select></div>' +
      '<div class="field"><label>角色 LoRA</label><select id="cp-lora">' + loraOpts + '</select></div>' +
    '</div>' +
    '<div class="row2">' +
      '<div class="field"><label>LoRA 权重</label><input id="cp-lora-w" type="number" step="0.05" min="0.1" max="2" value="' +
        (Number(curLora.weight) || 1) + '"></div>' +
      '<div class="field"><label>性别</label><select id="cp-gender">' +
        '<option value="f"' + (((c.gender || S.gender) === 'f') ? ' selected' : '') + '>女</option>' +
        '<option value="m"' + (((c.gender || S.gender) === 'm') ? ' selected' : '') + '>男</option></select></div>' +
    '</div>' +
    '<div class="field"><label>专属正向（身份 / 体型 / 表情…）</label><div id="cp-pos" class="card-blocks"></div>' +
      '<div class="row2" style="margin-top:6px"><input id="cp-pos-add" placeholder="积木名或文本，例 @ID_F" list="cp-token-list">' +
      '<button class="ghost" id="cp-pos-btn">＋ 加</button></div></div>' +
    '<div class="field"><label>专属负向（跟着这张卡一起落进负向）</label><div id="cp-neg" class="card-blocks"></div>' +
      '<div class="row2" style="margin-top:6px"><input id="cp-neg-add" placeholder="积木名或文本，例 @NEG_COLORBLEED" list="cp-token-list">' +
      '<button class="ghost" id="cp-neg-btn">＋ 加</button></div></div>' + tokenList +
    '' +
    '<div class="row2" style="margin-top:8px"><button class="ghost" id="cp-cancel">取消</button>' +
      '<button class="primary" id="cp-save">保存</button></div>' +
    '<div id="cp-out" class="hint" style="margin-top:6px"></div>');

  const posHost = $('#cp-pos'), negHost = $('#cp-neg');
  renderCardBlocks(posHost, pos, 'pos');
  renderCardBlocks(negHost, neg, 'neg');
  const addTo = (blocks, host, inputId, lane) => {
    const inp = $('#' + inputId);
    const v = ((inp && inp.value) || '').trim();
    if (!v) return;
    if (v.startsWith('@')) {
      if (!(S.tokens || {})[v]) { toast('没有这个积木：' + v, true); return; }
      blocks.push({ token: v, text: '', weight: 1 });
    } else {
      blocks.push({ token: '', text: v, weight: 1 });
    }
    if (inp) inp.value = '';
    renderCardBlocks(host, blocks, lane);
  };
  $('#cp-pos-btn').onclick = () => addTo(pos, posHost, 'cp-pos-add', 'pos');
  $('#cp-neg-btn').onclick = () => addTo(neg, negHost, 'cp-neg-add', 'neg');
  ['cp-pos-add', 'cp-neg-add'].forEach(id => {
    const el = $('#' + id);
    if (el) el.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); $(id === 'cp-pos-add' ? '#cp-pos-btn' : '#cp-neg-btn').click(); } };
  });

  $('#cp-cancel').onclick = closeModal;

  const save = $('#cp-save');
  if (save) save.onclick = async () => {
    const lname = ($('#cp-lora') || {}).value || '';
    const lw = Number(($('#cp-lora-w') || {}).value) || 1;
    const keep = (c.loras || []).filter(l => { try { return loraCat(l.name) !== '角色'; } catch (e) { return true; } });
    const loras = lname ? keep.concat([{ name: lname, weight: lw }]) : keep;
    const body = {
      name: c.name, loras,
      pos_blocks: pos.filter(b => b.token || (b.text || '').trim()),
      neg_blocks: neg.filter(b => b.token || (b.text || '').trim()),
      tokens: pos.filter(b => b.token).map(b => b.token),
      note: c.note || '',
      persona: ($('#cp-persona').value || '').trim(),
      identity_weak: ($('#cp-weak').value || '').trim(),
      base: ($('#cp-base') || {}).value || '',
      gender: (($('#cp-gender') || {}).value) || c.gender || S.gender,
      views: c.views || null,
    };
    try {
      const r = await api('/api/card/save', { method: 'POST', body: JSON.stringify(body) });
      S.cards = r.items || [];
      await loadCards();
      closeModal();
      toast('已保存：' + c.name + '（正向 ' + body.tokens.length + ' / 负向 ' + body.neg_blocks.length + '）');
    } catch (e) { toast('保存失败：' + e.message, true); }
  };
}

// 「写入」：独立页面，选人物 LoRA（带权重）+ 人设 + 弱身份，存成一张卡
function cardWrite() {
  const sel = $('#card-sel');
  const cur = (S.cards || []).find(x => x.name === (sel && sel.value)) || {};
  const keepRoles = ['角色'];
  const loraFiles = (S.loraFiles || []).filter(n => {
    try { return loraCat(n) === '角色'; } catch (e) { return false; }
  });
  const curLora = (cur.loras || []).find(l => /char_|角色/i.test(l.name || '')) || (cur.loras || [])[0] || {};
  const opts = loraFiles.map(n => '<option value="' + esc(n) + '"' + (n === curLora.name ? ' selected' : '') + '>' + esc(shortLoraName(n)) + '</option>').join('');
  openModal('写入角色卡',
    '<p class="hint">这张卡记录：人物 LoRA（含权重）、人设、身份积木。应用时才导入画布。</p>' +
    '<div class="field"><label>角色名</label><input id="cw-name" value="' + esc(cur.name || '') + '" placeholder="例如 小绫 / Aya"></div>' +
    '<div class="row2">' +
      '<div class="field"><label>人物 LoRA</label><select id="cw-lora">' + (opts || '<option value="">（没有角色类 LoRA）</option>') + '</select></div>' +
      '<div class="field"><label>权重</label><input id="cw-weight" type="number" step="0.05" value="' + (Number(curLora.weight) || 1) + '"></div>' +
    '</div>' +
    '<div class="field"><label>人设</label><textarea id="cw-persona" rows="4">' + esc(cur.persona || '') + '</textarea></div>' +
    '<div class="field"><label>弱身份文本（换底模时使用）</label><textarea id="cw-weak" rows="3">' + esc(cur.identity_weak || '') + '</textarea></div>' +
    '<div class="field"><label>身份积木（逗号分隔的 @ 积木）</label><input id="cw-tokens" value="' + esc((cur.tokens || []).join(', ')) + '" placeholder="@ID_F, @FACE_FSOFT"></div>' +
    '<div class="row2"><button class="ghost" id="cw-cancel">取消</button>' +
      '<button class="primary" id="cw-ok">写入</button></div>');
  $('#cw-cancel').onclick = closeModal;
  const ok = $('#cw-ok');
  if (ok) ok.onclick = async () => {
    const name = ($('#cw-name').value || '').trim();
    if (!name) { toast('角色名不能空', true); return; }
    const lname = ($('#cw-lora').value || '').trim();
    if (!lname) { toast('先选一个人物 LoRA', true); return; }
    const weight = Number($('#cw-weight').value) || 1;
    const tokens = ($('#cw-tokens').value || '').split(/[,，\s]+/).map(s => s.trim()).filter(s => s.startsWith('@'));
    try {
      const r = await api('/api/card/save', { method: 'POST', body: JSON.stringify({
        name, loras: [{ name: lname, weight }], tokens,
        pos_blocks: tokens.map(t => ({ token: t, text: '', weight: 1 })),
        persona: ($('#cw-persona').value || '').trim(),
        identity_weak: ($('#cw-weak').value || '').trim(),
        base: currentBaseModel(), note: cur.note || '', gender: cur.gender || S.gender,
        views: cur.views || null,
      }) });
      S.cards = r.items || [];
      await loadCards();
      closeModal();
      toast('已写入角色卡：' + name);
    } catch (e) { toast('写入失败：' + e.message, true); }
  };
}

async function cardSave() {
  const keep = ['id', 'body', 'face', 'hair', 'custom'];
  const tokens = [...new Set(S.pos.filter(b => b.token && keep.includes(tokenCat(b.token)))
    .map(b => b.token))];
  const loras = (S.loras || []).map(l => ({ name: l.name, weight: l.weight }));
  openModal('保存角色卡',
    '<div class="field"><label>名字</label><input id="cs-name" placeholder="例如 小绫 / Aya"></div>' +
    '<p class="hint">会保存 <b>' + loras.length + '</b> 个 LoRA、<b>' + tokens.length + '</b> 个身份积木' +
      (tokens.length ? '：' + esc(tokens.join(' ')) : '（当前画布没有身份类积木）') + '</p>' +
    '<div class="row2"><button class="ghost" id="cs-cancel">取消</button>' +
      '<button class="primary" id="cs-ok">保存</button></div>');
  $('#cs-cancel').onclick = closeModal;
  const inp = $('#cs-name');
  if (inp) inp.focus();
  $('#cs-ok').onclick = async () => {
    const name = ($('#cs-name').value || '').trim();
    if (!name) { toast('名字不能空', true); return; }
    try {
      const prev = (S.cards || []).find(x => x.name === name) || {};
      const r = await api('/api/card/save', { method: 'POST',
        body: JSON.stringify({ name, loras, tokens,
          pos_blocks: tokens.map(t => ({ token: t, text: '', weight: 1 })),
          persona: prev.persona || '', identity_weak: prev.identity_weak || '',
          base: prev.base || currentBaseModel(), gender: prev.gender || S.gender,
          views: prev.views || null }) });
      S.cards = r.items || [];
      await loadCards();
      closeModal();
      toast('已保存角色卡：' + name + '（' + loras.length + ' LoRA / ' + tokens.length + ' 标签）');
    } catch (e) { toast('保存失败：' + e.message, true); }
  };
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
  bind('#card-write', cardWrite);
  bind('#card-save', cardSave);
  bind('#card-persona', cardPersonaEdit);
  bind('#card-del', cardDelete);
  bind('#card-export', () => {
    const name = ($('#card-sel') || {}).value;
    if (!name) { toast('先选一张角色卡再导出', true); return; }
    window.location = '/api/card/export?name=' + encodeURIComponent(name);
  });
  bind('#card-import', () => {
    openModal('导入角色卡',
      '<div class="field"><label>情况一：粘贴 JSON</label>' +
        '<textarea id="ci-json" rows="6" placeholder=\'[{"name":"角色名","loras":[...],"tokens":[...]}\'></textarea></div>' +
      '<div class="field"><label>情况二：填本地 JSON 路径</label>' +
        '<input id="ci-path" placeholder="A:\\...\\character_cards.json"></div>' +
      '<div class="row2"><button class="ghost" id="ci-cancel">取消</button>' +
        '<button class="primary" id="ci-ok">导入</button></div>' +
      '<p class="hint">两种填一种就行：JSON 优先，没有 JSON 才按路径读。</p>');
    $('#ci-cancel').onclick = closeModal;
    $('#ci-ok').onclick = async () => {
      const data = ($('#ci-json').value || '').trim();
      const path = ($('#ci-path').value || '').trim();
      if (!data && !path) { toast('JSON 或路径填一个', true); return; }
      try {
        const r = await api('/api/cards/import', { method: 'POST',
          body: JSON.stringify(data ? { data } : { path }) });
        S.cards = r.items || [];
        await loadCards();
        closeModal();
        toast('导入完成，新增 ' + r.added + ' 张');
      } catch (e) { toast('导入失败：' + e.message, true); }
    };
  });
})();

/* ---------- 提词器（ComfyUI NSFWPromptSelector 桥，正负分流） ---------- */
(function initPromptLib() {
  const btn = $('#open-plib');
  if (!btn) return;
  const TAG = 'plib';
  let OPT = null;

  const esc2 = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  async function loadOptions() {
    if (OPT) return OPT;
    OPT = await api('/api/promptlib/options');
    return OPT;
  }

  function selectHtml(f, idx) {
    const opts = f.items.map(v => '<option value="' + esc2(v) + '"' + (v === '——' ? ' selected' : '') + '>' + esc2(v) + '</option>').join('');
    if (f.kind === 'multi') {
      return '<div class="field"><label>' + esc2(f.name) + '</label>' +
        '<select id="plib-f' + idx + '" multiple size="6">' + opts + '</select></div>';
    }
    return '<div class="field"><label>' + esc2(f.name) + '</label>' +
      '<select id="plib-f' + idx + '">' + opts + '</select></div>';
  }

  function collect(fs) {
    const fields = {};
    fs.forEach((f, i) => {
      const el = $('#plib-f' + i);
      if (!el) return;
      fields[f.name] = f.kind === 'multi'
        ? Array.from(el.selectedOptions).map(o => o.value)
        : el.value;
    });
    (OPT.weights || []).forEach((w, i) => {
      const el = $('#plib-w' + i);
      if (el) fields[w] = parseFloat(el.value) || 0;
    });
    fields['自定义前缀'] = ($('#plib-pre').value || '').trim();
    fields['自定义后缀'] = ($('#plib-suf').value || '').trim();
    return fields;
  }

  function dropTagged(lane) {
    const arr = lane === 'positive' ? S.pos : S.neg;
    for (let i = arr.length - 1; i >= 0; i--) {
      if (arr[i].plib === TAG) arr.splice(i, 1);
    }
  }

  async function write(side, fs) {
    let r;
    try {
      r = await api('/api/promptlib/build', { method: 'POST', body: JSON.stringify({ fields: collect(fs) }) });
    } catch (e) { toast('生成失败：' + e.message, true); return; }
    const pos = (r.positive || '').trim().replace(/[,\s]+$/, '');
    const neg = (r.negative || '').trim().replace(/[,\s]+$/, '');
    if (side !== 'negative') {
      dropTagged('positive');
      if (pos) addBlock('positive', { text: pos, weight: 1, plib: TAG });
    }
    if (side !== 'positive') {
      dropTagged('negative');
      if (neg) addBlock('negative', { text: neg, weight: 1, plib: TAG });
    }
    renderLanes();
    closeModal();
    toast('已写入' + (side === 'positive' ? '正向管线' : side === 'negative' ? '负向管线' : '正向 + 负向管线'));
  }

  btn.onclick = async () => {
    try { await loadOptions(); } catch (e) { toast('提词器选项加载失败：' + e.message, true); return; }
    const fs = OPT.fields || [];
    let html = '<p class="hint">选条件后直接写入对应跑道：正向进正向、负向进负向，各成一块，可再调权重/停用。</p><div class="plib-grid">';
    fs.forEach((f, i) => { html += selectHtml(f, i); });
    html += '</div>';
    html += '<div class="row2" style="margin-top:8px">' +
      '<div class="field"><label>自定义前缀</label><input id="plib-pre" placeholder="可空"></div>' +
      '<div class="field"><label>自定义后缀</label><input id="plib-suf" placeholder="可空"></div></div>';
    html += '<div class="row2" style="margin-top:8px">' + (OPT.weights || []).map((w, i) =>
      '<div class="field"><label>' + esc2(w) + '</label><input id="plib-w' + i + '" type="number" step="0.1" min="0" max="2" value="' +
      ({ '权重_场景': 1.0, '权重_动作': 1.5, '权重_服饰': 0.8, '权重_情绪': 1.2 }[w]) + '"></div>').join('') + '</div>';
    html += '<div class="row2" style="margin-top:12px">' +
      '<button class="primary" id="plib-both">写入正负向</button>' +
      '<button class="ghost" id="plib-only-pos">只写正向</button>' +
      '<button class="ghost" id="plib-only-neg">只写负向</button>' +
      '<button class="ghost" id="plib-cancel">关闭</button></div>';
    openModal('提词器', html);
    $('#plib-cancel').onclick = closeModal;
    $('#plib-both').onclick = () => write('both', fs);
    $('#plib-only-pos').onclick = () => write('positive', fs);
    $('#plib-only-neg').onclick = () => write('negative', fs);
  };
})();

// ---------------- 智囊（语言层） ----------------

// ---------------- 通用下拉选择器（.llm-pick 样式类名保留） ----------------
// items() 返回 [{value,title,desc}]；current() 返回当前值；onPick(v) 处理选中。
function makePicker(cfg) {
  const { btn, menu, items, current, onPick, labelOf, titleOf } = cfg;
  if (!btn || !menu) return null;
  const escv = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const close = () => { menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); };
  const sync = () => {
    if (labelOf) btn.innerHTML = labelOf() + '<span class="llm-caret">▾</span>';
    if (titleOf) { const t = titleOf(); if (t) btn.title = t; }
  };
  const open = () => {
    const cur = current ? current() : '';
    const list = (items && items()) || [];
    menu.innerHTML = list.length
      ? list.map(it =>
          '<div class="llm-pick-item' + (it.value === cur ? ' on' : '') + '" data-v="' + escv(it.value) + '" role="option">' +
            '<span class="t">' + escv(it.title) + '</span>' +
            '<span class="d">' + escv(it.desc || '') + '</span></div>').join('')
      : '<div class="llm-pick-item"><span class="t">没有可选项</span></div>';
    menu.querySelectorAll('.llm-pick-item[data-v]').forEach(el => {
      el.onclick = () => { onPick(el.dataset.v); sync(); close(); };
    });
    if (menu.parentNode !== document.body) document.body.appendChild(menu);
    const r = btn.getBoundingClientRect();
    menu.style.left = Math.round(r.left) + 'px';
    menu.style.top = Math.round(r.bottom + 6) + 'px';
    menu.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
  };
  btn.onclick = (e) => { e.stopPropagation(); menu.hidden ? open() : close(); };
  document.addEventListener('click', (e) => { if (!menu.hidden && !menu.contains(e.target) && e.target !== btn) close(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
  window.addEventListener('scroll', () => close(), true);
  window.addEventListener('resize', () => close());
  sync();
  return { open, close, sync };
}

// 代码里直接改 select.value 时也同步按钮文字（值变更不触发 change）
function bindSelectValueSync(sel, picker) {
  if (!sel || !picker) return;
  try {
    const d = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
    Object.defineProperty(sel, 'value', {
      get() { return d.get.call(this); },
      set(v) { d.set.call(this, v); picker.sync(); },
    });
  } catch (e) {}
}

// ---------------- 通用下拉选择器 ----------------

// ---------------- 引导选择器（同一套通用组件） ----------------

/* ---------- 重映工作台：页签 + 独立主场景/主服装积木槽（无本地模型） ---------- */
function reprojState() {
  if (!S.reproj) S.reproj = { garment: '', view: '', door: true };
  return S.reproj;
}

function reprojFindGarmentKey(tok) {
  const up = String(tok || '').toUpperCase();
  if (!up.startsWith('@OUT_')) return '';
  const raw = up.slice(5).toLowerCase();
  const g = S.garments || {};
  if (g[raw] && !/^neg_/i.test(raw)) return raw;
  return '';
}

function reprojIsMainGarmentToken(tok) {
  const up = String(tok || '').toUpperCase();
  if (/^@OUT_/.test(up) && !/^@OUT_(TIGHTS|SOCKS)$/.test(up)) return true;
  if (/^@OUTFIT(_[AB])?$/.test(up)) return true;
  return false;
}

function reprojMainGarmentBlock(arr) {
  return (arr || []).find(b => b && reprojFindGarmentKey(b.token))
    || (arr || []).find(b => b && reprojIsMainGarmentToken(b.token))
    || null;
}

function reprojBindSlotChip(slotNameEl, lane) {
  if (!slotNameEl) return;
  try { if (typeof bindTips === 'function') bindTips(slotNameEl); } catch (e) {}
  slotNameEl.querySelectorAll('.chip').forEach(el => {
    el.addEventListener('dblclick', ev => {
      if (ev.target && (ev.target.tagName === 'INPUT' || ev.target.tagName === 'BUTTON')) return;
      const id = el.dataset.id, ln = el.dataset.coopLane || lane;
      const b = (coopEnsure()[ln] || []).find(x => x.id === id);
      if (b && b.token && typeof openBlockDetail === 'function') {
        openBlockDetail(b, ln.endsWith('Neg') ? 'negative' : 'positive');
      }
    });
  });
}

function reprojSceneThemeTitle(tok) {
  const note = String((S.notes && S.notes[tok]) || '').trim();
  if (note) {
    const first = note.split(/[:：。，,（(]/)[0].trim();
    if (first) return first;
  }
  return String(tok || '').replace(/^@SET_/, '').replace(/_/g, ' ');
}

function reprojSceneThemeChip(b) {
  const title = reprojSceneThemeTitle(b.token);
  return '<div class="chip pos reproj-theme-card' + (b.enabled === false ? ' off' : '') + '"' +
    ' data-coop-lane="envPos" data-id="' + b.id + '" data-cat="set" data-token="' + esc(b.token) + '">' +
    '<button type="button" class="on" data-coop-toggle="' + b.id + '" data-coop-lane="envPos">' + (b.enabled === false ? '○' : '●') + '</button>' +
    '<button type="button" class="reproj-theme-btn" id="reproj-add-scene" title="跳转到左侧场景分类">' +
      '<span class="reproj-theme-title">' + esc(title) + '</span>' +
      '<span class="tk">' + esc(b.token) + '</span>' +
    '</button>' +
    '<button type="button" class="x" data-coop-del="' + b.id + '" data-coop-lane="envPos" title="移除主场景">×</button>' +
    '</div>';
}

function reprojSyncSceneWeight(sceneBlk) {
  const wbox = $('#reproj-scene-wbox');
  const wr = $('#reproj-scene-wr');
  const wn = $('#reproj-scene-weight');
  if (!wbox || !wr || !wn) return;
  const has = !!sceneBlk;
  wbox.classList.toggle('disabled', !has);
  wr.disabled = !has;
  wn.disabled = !has;
  const w = has ? (Number(sceneBlk.weight) || 1) : 1;
  wr.value = String(w);
  wn.value = String(w);
}

function reprojGarmentThemeChip(b, gKey) {
  const g = (S.garments && S.garments[gKey]) || {};
  const label = g.label || (S.notes && S.notes[b.token] && S.notes[b.token].split(/[:：。，,（(]/)[0].trim()) || b.token.replace(/^@(OUT_)?/, '');
  return '<div class="chip pos reproj-theme-card' + (b.enabled === false ? ' off' : '') + '"' +
    ' data-coop-lane="chrPos" data-id="' + b.id + '" data-cat="outfit" data-token="' + esc(b.token) + '">' +
    '<button type="button" class="on" data-coop-toggle="' + b.id + '" data-coop-lane="chrPos">' + (b.enabled === false ? '○' : '●') + '</button>' +
    '<button type="button" class="reproj-theme-btn" data-rcat="outfit" data-rlane="chrPos" title="跳转到左侧服装分类">' +
      '<span class="reproj-theme-title">' + esc(label) + '</span>' +
      '<span class="tk">' + esc(b.token) + '</span>' +
    '</button>' +
    '<button type="button" class="x" data-coop-del="' + b.id + '" data-coop-lane="chrPos" title="卸下服装">×</button>' +
    '</div>';
}

function reprojSyncGarmentWeight(garmentBlk) {
  const wbox = $('#reproj-garment-wbox');
  const wr = $('#reproj-garment-wr');
  const wn = $('#reproj-garment-weight');
  if (!wbox || !wr || !wn) return;
  const has = !!garmentBlk;
  wbox.classList.toggle('disabled', !has);
  wr.disabled = !has;
  wn.disabled = !has;
  const w = has ? (Number(garmentBlk.weight) || 1) : 1;
  wr.value = String(w);
  wn.value = String(w);
}

function reprojSyncCatPills(c) {
  document.querySelectorAll('.reproj-cat-pills[data-cat-lane]').forEach(bar => {
    const lane = bar.getAttribute('data-cat-lane');
    const arr = (c && c[lane]) || [];
    const mainGarment = lane === 'chrPos' ? reprojMainGarmentBlock(arr) : null;
    const counts = {};
    arr.forEach(b => {
      if (!b || !b.token || b.enabled === false || b === mainGarment) return;
      let cat = '';
      try { cat = tokenCat(b.token); } catch (e) {}
      if (cat) counts[cat] = (counts[cat] || 0) + 1;
    });
    bar.querySelectorAll('.rcat-pill').forEach(btn => {
      const cat = btn.dataset.rcat;
      const n = counts[cat] || 0;
      btn.classList.toggle('has', n > 0);
      if (!btn.dataset.baseLabel) btn.dataset.baseLabel = (btn.textContent || '').trim();
      const label = btn.dataset.baseLabel || CAT_LABEL[cat] || cat;
      btn.innerHTML = '<i></i>' + esc(label) + (n > 0 ? ' · ' + n : '');
    });
  });
}

function reprojSyncFromLanes() {
  const c = coopEnsure();
  const st = reprojState();

  // 主场景独立积木块同步（焦点落在主题 + 右侧场景权重）
  const sceneSlot = $('#reproj-scene-slot');
  const sceneName = $('#reproj-scene-name');
  const sceneBlk = (c.envPos || []).find(b => b && /^@SET_/.test(String(b.token || ''))) || null;
  if (sceneSlot && sceneName) {
    sceneSlot.classList.toggle('has-scene', !!sceneBlk);
    sceneName.innerHTML = sceneBlk
      ? reprojSceneThemeChip(sceneBlk)
      : '<button type="button" class="reproj-theme-empty" id="reproj-add-scene">＋ 去左侧选场景（或拖入 @SET_*）</button>';
    if (sceneBlk) reprojBindSlotChip(sceneName, 'envPos');
  }
  reprojSyncSceneWeight(sceneBlk);

  // 主服装独立积木块同步（与主场景一致：焦点落在服装名 + 右侧服装权重）
  const garmentSlot = $('#reproj-garment-slot');
  const garmentName = $('#reproj-garment-name');
  const garmentBlk = reprojMainGarmentBlock(c.chrPos || []);
  const gKey = garmentBlk ? (reprojFindGarmentKey(garmentBlk.token) || String(garmentBlk.token || '').replace(/^@OUT_/, '').toLowerCase()) : '';
  st.garment = garmentBlk && reprojFindGarmentKey(garmentBlk.token) ? reprojFindGarmentKey(garmentBlk.token) : '';
  if (garmentSlot && garmentName) {
    garmentSlot.classList.toggle('has-scene', !!garmentBlk);
    garmentName.innerHTML = garmentBlk
      ? reprojGarmentThemeChip(garmentBlk, gKey)
      : '<button type="button" class="reproj-theme-empty" data-rcat="outfit" data-rlane="chrPos">＋ 去左侧选服装（或拖入 @OUT_*）</button>';
    if (garmentBlk) reprojBindSlotChip(garmentName, 'chrPos');
  }
  reprojSyncGarmentWeight(garmentBlk);
  reprojSyncCatPills(c);
}

function reprojSetGarment(keyOrToken) {
  pushHistory();
  const c = coopEnsure();
  c.chrPos = c.chrPos || [];
  c.chrNeg = c.chrNeg || [];
  const oldKeys = new Set();
  const curKey = reprojState().garment;
  if (curKey) oldKeys.add(curKey.toUpperCase());
  c.chrPos.forEach(b => {
    const gk = reprojFindGarmentKey(b && b.token);
    if (gk) oldKeys.add(gk.toUpperCase());
  });
  c.chrPos = c.chrPos.filter(b => !(b && (reprojFindGarmentKey(b.token) || reprojIsMainGarmentToken(b.token))));
  c.chrNeg = c.chrNeg.filter(b => !(b && oldKeys.has(String(b.token || '').replace(/^@NEG_/, '').toUpperCase()) && /^@NEG_/.test(String(b.token || ''))));
  const raw = String(keyOrToken || '').trim();
  let tok = '';
  let cleanKey = '';
  if (raw) {
    tok = raw.startsWith('@') ? raw.toUpperCase() : ('@OUT_' + raw.toUpperCase());
    cleanKey = reprojFindGarmentKey(tok);
    c.chrPos.unshift({ id: uid(), token: tok, text: '', weight: 1, enabled: true });
    if (tok.startsWith('@OUT_')) {
      const negTok = tok.replace(/^@OUT_/, '@NEG_');
      if (S.tokens && S.tokens[negTok] && !c.chrNeg.some(b => b && b.token === negTok)) {
        c.chrNeg.push({ id: uid(), token: negTok, text: '', weight: 1, enabled: true, auto: true });
      }
    }
  }
  reprojState().garment = cleanKey;
  renderCoopLanes(); coopBind(); expandPreview();
}

function reprojFillViews() {
  const box = $('#reproj-views');
  if (!box) return;
  const name = ($('#card-sel') || {}).value || '';
  const card = (S.cards || []).find(c => c.name === name);
  const views = (card && card.views) || {};
  const keys = Object.keys(views);
  if (!keys.length) { box.innerHTML = '<span class="hint">先选角色卡</span>'; return; }
  box.innerHTML = keys.map(k => '<button class="rbtn" data-view="' + k + '">' +
    esc(k.replace('', '').replace(/_/g, ' ')) + '</button>').join('');
  box.querySelectorAll('[data-view]').forEach(b => {
    b.onclick = () => {
      box.querySelectorAll('.rbtn').forEach(x => x.classList.remove('on'));
      b.classList.add('on');
      reprojState().view = b.dataset.view;
    };
  });
}

function reprojBindSlotDrop(slotEl, matchFn, applyFn) {
  if (!slotEl || slotEl.dataset.dropBound) return;
  slotEl.dataset.dropBound = '1';
  slotEl.addEventListener('dragover', e => {
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    slotEl.classList.add('drag-over');
  });
  slotEl.addEventListener('dragleave', e => {
    if (!e.relatedTarget || !slotEl.contains(e.relatedTarget)) slotEl.classList.remove('drag-over');
  });
  slotEl.addEventListener('drop', e => {
    e.preventDefault();
    slotEl.classList.remove('drag-over');
    const raw = e.dataTransfer.getData('text/plain');
    if (!raw) return;
    let d = null; try { d = JSON.parse(raw); } catch (err) { d = null; }
    let tok = d && d.token ? d.token : '';
    if (!tok && d && d.move && d.lane) {
      const moved = (coopEnsure()[d.lane] || []).find(b => b && b.id === d.move);
      if (moved && moved.token) tok = moved.token;
    }
    if (tok && matchFn(tok)) applyFn(tok);
  });
}

function reprojInit() {
  reprojFillViews();
  const dr = $('#reproj-door');
  if (dr && !dr._bound) { dr._bound = true; dr.onchange = () => { reprojState().door = dr.checked; expandPreview(); }; }
  const cs = $('#card-sel');
  if (cs && !cs._reprojBound) { cs._reprojBound = true; cs.addEventListener('change', () => setTimeout(reprojFillViews, 50)); }
  const wr = $('#reproj-scene-wr'), wn = $('#reproj-scene-weight');
  const setSceneWeight = raw => {
    const c = coopEnsure();
    const blk = (c.envPos || []).find(b => b && /^@SET_/.test(String(b.token || '')));
    if (!blk) return;
    const w = Math.round(Math.max(0.3, Math.min(2, Number(raw) || 1)) * 100) / 100;
    blk.weight = w;
    if (wr) wr.value = String(w);
    if (wn) wn.value = String(w);
    expandPreview();
  };
  if (wr && !wr._bound) { wr._bound = true; wr.oninput = () => setSceneWeight(wr.value); }
  if (wn && !wn._bound) { wn._bound = true; wn.onchange = () => setSceneWeight(wn.value); }
  const gwr = $('#reproj-garment-wr'), gwn = $('#reproj-garment-weight');
  const setGarmentWeight = raw => {
    const c = coopEnsure();
    const blk = reprojMainGarmentBlock(c.chrPos || []);
    if (!blk) return;
    const w = Math.round(Math.max(0.3, Math.min(2, Number(raw) || 1)) * 100) / 100;
    blk.weight = w;
    if (gwr) gwr.value = String(w);
    if (gwn) gwn.value = String(w);
    expandPreview();
  };
  if (gwr && !gwr._bound) { gwr._bound = true; gwr.oninput = () => setGarmentWeight(gwr.value); }
  if (gwn && !gwn._bound) { gwn._bound = true; gwn.onchange = () => setGarmentWeight(gwn.value); }
  reprojBindSlotDrop($('#reproj-scene-slot'), t => /^@SET_/.test(t), t => reprojAddScene(t));
  reprojBindSlotDrop($('#reproj-garment-slot'), t => reprojIsMainGarmentToken(t), t => reprojSetGarment(t));
  try { reprojSyncFromLanes(); } catch (e) {}
}

function reprojExtraEnv() {
  const st = reprojState(), out = [];
  if (st.door) out.push({ id: uid(), token: '', text: 'a wooden door on a side wall', weight: 1, enabled: true });
  return out;
}

function reprojExtraChar() {
  const st = reprojState(), out = [], c = coopEnsure();
  if (st.view) out.push({ id: uid(), token: st.view, weight: 1, enabled: true });
  if (st.garment) {
    const key = st.garment.toUpperCase();
    const hasOut = (c.chrPos || []).some(b => b && b.token === '@OUT_' + key);
    const hasNeg = (c.chrNeg || []).some(b => b && b.token === '@NEG_' + key);
    if (!hasOut && S.tokens && S.tokens['@OUT_' + key]) out.push({ id: uid(), token: '@OUT_' + key, weight: 1, enabled: true });
    if (!hasNeg && S.tokens && S.tokens['@NEG_' + key]) out.push({ id: uid(), token: '@NEG_' + key, weight: 1, enabled: true });
  }
  return out;
}

function reprojAddScene(token) {
  pushHistory();
  const c = coopEnsure();
  c.envPos = (c.envPos || []).filter(x => !(x && /^@SET_/.test(String(x.token || ''))));
  c.envPos.unshift({ id: uid(), token: token, text: '', weight: 1, enabled: true });
  try { renderCoopLanes(); coopBind(); expandPreview(); } catch (e) {}
  try { closeModal(); } catch (e) {}
}

function reprojJumpPalette(cat) {
  if (document.body.classList.contains('lib-collapsed') && typeof setLibCollapsed === 'function') {
    setLibCollapsed(false);
  }
  const railBtn = document.querySelector('#pal-rail .rail-item[data-jump="' + cat + '"]');
  if (railBtn) { railBtn.click(); return; }
  try {
    S.collapsedCats = S.collapsedCats || {};
    if (S.collapsedCats[cat]) { S.collapsedCats[cat] = false; saveJSON('loom.collapsedCats', S.collapsedCats); renderPalette(); }
    if (typeof scrollPalTo === 'function') scrollPalTo(cat);
  } catch (e) {}
}

document.addEventListener('click', ev => {
  const t = ev.target;
  if (!t || !t.closest) return;
  const tab = t.closest('[data-rtab]');
  if (tab) {
    const want = tab.dataset.rtab;
    document.querySelectorAll('[data-rtab]').forEach(x => x.classList.toggle('on', x === tab));
    ['env', 'char', 'out'].forEach(k => {
      const el = document.getElementById('rtab-' + k);
      if (el) el.hidden = (k !== want);
    });
    return;
  }
  const rcatBtn = t.closest('[data-rcat]');
  if (rcatBtn) {
    const cat = rcatBtn.dataset.rcat;
    reprojJumpPalette(cat);
    toast('左侧已定位到：' + (CAT_LABEL[cat] || cat));
    return;
  }
  if (t.closest('#reproj-add-scene')) {
    reprojJumpPalette('set');
    toast('左侧已定位到：' + (CAT_LABEL.set || '场景'));
    return;
  }
  if (t.closest('#reproj-clear-garment')) { reprojSetGarment(''); return; }
});
