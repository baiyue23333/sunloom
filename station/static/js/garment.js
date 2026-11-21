'use strict';

// 服装页主控：基础设定、正负文本、绑定型态与材质（延用主页积木逻辑）、部件/发饰与手持物武器事件绑定
const GM = {
  key: '',
  leftMode: 'garment',
  rightTab: 'garment',
  leftSearch: '',
  partToken: '',
  handToken: '',
  handCat: 'all',
  handSearch: '',
  bindEnabled: false,
  drapeBlocks: [],
  fabricBlocks: [],
  drapeSearch: '',
  fabricSearch: '',
};

function gmCurrentGender() {
  const el = $('#gm-gender');
  return (el && (el.value === 'm' || el.value === 'f')) ? el.value : (S.gender || 'f');
}

function gmNormBindBlock(b) {
  return {
    id: uid(),
    token: (b && b.token) || '',
    text: (b && b.text) || '',
    weight: Math.max(0, Math.min(3, Number(b && b.weight) || 1)),
    enabled: !b || b.enabled !== false,
  };
}

function gmSerializeBindBlocks(arr) {
  return (arr || []).map(b => ({
    token: b.token || '',
    text: b.text || '',
    weight: Number(b.weight) || 1,
    enabled: b.enabled !== false,
  }));
}

function gmSwitchRightTab(tab) {
  GM.rightTab = tab || 'garment';
  $$('#gm-right-tabs [data-gm-rtab]').forEach(b => b.classList.toggle('on', b.dataset.gmRtab === GM.rightTab));
  ['garment', 'part', 'hand'].forEach(k => {
    const p = $('#gm-panel-' + k);
    if (p) p.hidden = (k !== GM.rightTab);
  });
  if (GM.rightTab === 'hand') {
    renderHandList();
    if (!GM.handToken) {
      const first = Object.keys(S.tokens || {}).find(k => /^@(HOLD_[RL]_|WEAPON_)/.test(k) && tokenVisible(k));
      if (first) loadHandToken(first);
    }
  }
}

function gmSwitchLeftMode(mode) {
  GM.leftMode = mode || 'garment';
  $$('#gm-left-tabs [data-gm-lmode]').forEach(b => b.classList.toggle('on', b.dataset.gmLmode === GM.leftMode));
  renderGarmentList();
}

function gmBindArr(kind) {
  return kind === 'fabric' ? GM.fabricBlocks : GM.drapeBlocks;
}

function gmAddBindBlock(kind, tokenOrObj) {
  const arr = gmBindArr(kind);
  const res = addBlockToLanes(arr, [], 'positive', tokenOrObj, { dedupeAllTokens: true });
  if (!res) return false;
  renderBindLanes();
  return true;
}

function gmRenderOneBindLane(kind) {
  const arr = gmBindArr(kind);
  const box = $(kind === 'fabric' ? '#gm-fabric-lane' : '#gm-drape-lane');
  const cnt = $(kind === 'fabric' ? '#gm-fabric-count' : '#gm-drape-count');
  const laneCard = document.querySelector('#gm-bind-body [data-gm-bind="' + kind + '"]');
  if (cnt) cnt.textContent = arr.length + ' 块';
  if (!box) return;
  const emptyTip = kind === 'fabric'
    ? '从下方挑选写好的材质积木 (@FAB_*)，或点「+ 自定义」'
    : '从下方挑选写好的型态积木 (@DRAPE_*)，或点「+ 自定义」';
  box.innerHTML = arr.map(b => blockChipHtml(b, 'positive')).join('') || ('<span class="hint">' + emptyTip + '</span>');

  bindBlockLaneBox({
    root: laneCard || box,
    posBox: box,
    negBox: null,
    getArr: () => arr,
    onMove: (id, _from, _to, index) => {
      if (moveBlockInLanes(arr, [], id, 'positive', 'positive', index)) gmRenderOneBindLane(kind);
    },
    onDropToken: (_lane, d) => gmAddBindBlock(kind, d),
    onDropText: (_lane, raw) => gmAddBindBlock(kind, { text: raw }),
    onDelete: (_lane, id) => {
      removeBlockFromLanes(arr, [], 'positive', id);
      gmRenderOneBindLane(kind);
    },
    onToggle: (_lane, id) => {
      const b = arr.find(x => x.id === id);
      if (b) b.enabled = b.enabled === false;
      gmRenderOneBindLane(kind);
    },
    onWeight: (_lane, id, w) => {
      const b = arr.find(x => x.id === id);
      if (b) b.weight = w;
    },
    onEditFree: (b) => {
      openTextBlockDialog({
        lane: 'positive',
        text: b.text,
        weight: b.weight,
        title: '编辑自定义' + (kind === 'fabric' ? '材质' : '型态') + '块',
        onSave: (text, weight) => {
          b.text = text;
          b.weight = weight;
          gmRenderOneBindLane(kind);
        },
      });
    },
  });
}

function renderBindLanes() {
  const chk = $('#gm-bind-on');
  const body = $('#gm-bind-body');
  if (chk) chk.checked = !!GM.bindEnabled;
  if (body) body.hidden = !GM.bindEnabled;
  if (!GM.bindEnabled) return;
  gmRenderOneBindLane('drape');
  gmRenderOneBindLane('fabric');
  renderBindPickers();
}

function gmRenderPickGrid(kind, prefix, boxSel, searchVal) {
  const box = $(boxSel);
  if (!box) return;
  const gNow = gmCurrentGender();
  const q = (searchVal || '').trim().toLowerCase();
  const items = Object.keys(S.tokens || {}).filter(k => {
    if (!k.startsWith(prefix)) return false;
    const tg = tokenGender(k);
    if ((tg === 'f' || tg === 'm') && tg !== gNow) return false;
    if (!q) return true;
    const txt = S.tokens[k] || '', nt = (S.notes || {})[k] || '';
    return k.toLowerCase().includes(q) || txt.toLowerCase().includes(q) || nt.toLowerCase().includes(q);
  }).sort();

  const cat = kind === 'fabric' ? 'fabric' : 'drape';
  box.innerHTML = items.length ? items.map(k =>
    '<div class="pal-item" draggable="true" data-token="' + esc(k) + '" data-cat="' + cat + '"' + tintAttrs(k) + '>' +
      '<span class="tk">' + esc(k) + '</span><span class="add">＋</span></div>'
  ).join('') : '<span class="hint">没有匹配的积木</span>';
  bindTips(box);

  box.querySelectorAll('.pal-item').forEach(el => {
    el.onclick = () => gmAddBindBlock(kind, el.dataset.token);
    el.ondragstart = e => {
      e.dataTransfer.setData('text/plain', JSON.stringify({ token: el.dataset.token }));
      e.dataTransfer.effectAllowed = 'copy';
    };
  });
}

function renderBindPickers() {
  if (!GM.bindEnabled) return;
  gmRenderPickGrid('drape', '@DRAPE_', '#gm-drape-pick', GM.drapeSearch);
  gmRenderPickGrid('fabric', '@FAB_', '#gm-fabric-pick', GM.fabricSearch);
}

function loadGarment(key) {
  const g = (S.garments || {})[key];
  if (!g) return;
  GM.key = key;
  S.garmentKey = key;
  if ($('#gm-key2')) $('#gm-key2').value = key;
  if ($('#gm-label')) $('#gm-label').value = g.label || '';
  if ($('#gm-use')) $('#gm-use').value = g.use_for || '';
  if ($('#gm-gender')) $('#gm-gender').value = (g.gender === 'm' ? 'm' : 'f');
  if ($('#gm-parts')) $('#gm-parts').value = Array.isArray(g.parts) ? g.parts.join(', ') : '';
  if ($('#gm-note')) $('#gm-note').value = g.note || '';
  if ($('#gm-prompt2')) $('#gm-prompt2').value = g.prompt || '';
  if ($('#gm-neg2')) $('#gm-neg2').value = g.negative || '';
  if ($('#gm-hand-r')) $('#gm-hand-r').value = g.hands_right || '';
  if ($('#gm-hand-l')) $('#gm-hand-l').value = g.hands_left || '';
  if ($('#gm-hd-garment-name')) $('#gm-hd-garment-name').textContent = (g.label || key) + ' (' + key + ')';

  GM.bindEnabled = !!g.bind_enabled;
  GM.drapeBlocks = Array.isArray(g.drape_blocks) ? g.drape_blocks.map(gmNormBindBlock) : [];
  GM.fabricBlocks = Array.isArray(g.fabric_blocks) ? g.fabric_blocks.map(gmNormBindBlock) : [];

  renderGarmentList(key);
  updateGarmentPreviewImg(key);
  renderBindLanes();
  const st = $('#gm-status');
  if (st) st.textContent = '编辑中：' + key;
}

function newGarment() {
  GM.key = '';
  S.garmentKey = '';
  if ($('#gm-key2')) $('#gm-key2').value = '';
  if ($('#gm-label')) $('#gm-label').value = '';
  if ($('#gm-use')) $('#gm-use').value = '';
  if ($('#gm-gender')) $('#gm-gender').value = S.gender || 'f';
  if ($('#gm-parts')) $('#gm-parts').value = '';
  if ($('#gm-note')) $('#gm-note').value = '';
  if ($('#gm-prompt2')) $('#gm-prompt2').value = '';
  if ($('#gm-neg2')) $('#gm-neg2').value = '';
  if ($('#gm-hand-r')) $('#gm-hand-r').value = '';
  if ($('#gm-hand-l')) $('#gm-hand-l').value = '';
  if ($('#gm-hd-garment-name')) $('#gm-hd-garment-name').textContent = '未选服装';
  GM.bindEnabled = false;
  GM.drapeBlocks = [];
  GM.fabricBlocks = [];
  renderGarmentList('');
  updateGarmentPreviewImg('');
  renderBindLanes();
  const st = $('#gm-status');
  if (st) st.textContent = '新建：填写基础设定与正负文本后保存';
}

async function saveGarment() {
  const key = (($('#gm-key2') ? $('#gm-key2').value : '') || '').trim();
  if (!key) { toast('先填 key（英文，如 slip2）', true); return; }
  if (!/^[a-z0-9_]+$/i.test(key)) { toast('key 只能包含字母、数字、下划线', true); return; }
  const prompt = (($('#gm-prompt2') || {}).value || '').trim();
  if (!prompt) { toast('正向描述文本不能为空', true); return; }

  const partsRaw = (($('#gm-parts') || {}).value || '').split(/[,，、\n]+/).map(s => s.trim()).filter(Boolean);
  const body = {
    key,
    label: (($('#gm-label') || {}).value || '').trim() || key,
    use_for: (($('#gm-use') || {}).value || '').trim(),
    parts: partsRaw,
    note: ($('#gm-note') || {}).value || '',
    gender: gmCurrentGender(),
    prompt,
    negative: (($('#gm-neg2') || {}).value || '').trim(),
    bind_enabled: !!GM.bindEnabled,
    drape_blocks: gmSerializeBindBlocks(GM.drapeBlocks),
    fabric_blocks: gmSerializeBindBlocks(GM.fabricBlocks),
    hands_right: ($('#gm-hand-r') || {}).value || '',
    hands_left: ($('#gm-hand-l') || {}).value || '',
  };
  try {
    const r = await api('/api/garment/save', { method: 'POST', body: JSON.stringify(body) });
    S.garments = r.garments || S.garments;
    const saved = S.garments[key] || body;
    gmSyncDerivedTokens(key, saved);
    if (saved.gender && saved.gender !== S.gender) {
      const gbtn = document.querySelector('#pal-gender button[data-g="' + saved.gender + '"]');
      if (gbtn) gbtn.click();
    }
    loadGarment(key);
    toast('已保存服装 ' + key);
  } catch (e) { toast('保存失败：' + e.message, true); }
}

async function deleteGarment() {
  const key = (($('#gm-key2') ? $('#gm-key2').value : '') || '').trim();
  if (!key) return;
  if (!confirm('删除服装《' + key + '》？这会从 character.json 里移除。')) return;
  try {
    const r = await api('/api/garment/delete', { method: 'POST', body: JSON.stringify({ key }) });
    S.garments = r.garments || {};
    const up = key.toUpperCase();
    delete S.tokens['@OUT_' + up];
    delete S.tokens['@NEG_' + up];
    S._negGarmentSet = null;
    if (typeof renderPalette === 'function') renderPalette();
    const first = Object.keys(S.garments).find(k => ((S.garments[k] || {}).gender || 'f') === S.gender)
      || Object.keys(S.garments)[0];
    if (first) loadGarment(first); else newGarment();
    toast('已删除 ' + key);
  } catch (e) { toast('删除失败：' + e.message, true); }
}

function sendGarmentToWork() {
  const key = (($('#gm-key2') ? $('#gm-key2').value : '') || GM.key || '').trim();
  if (!key || !(S.garments || {})[key]) {
    toast('请先保存这套服装，再送到工作台', true);
    return;
  }
  const tok = '@OUT_' + key.toUpperCase();
  const buildTab = document.querySelector('#tabs button[data-tab="build"]');
  if (buildTab) buildTab.click();
  addBlock('positive', tok);
  toast('已将 ' + tok + ' 加入工作台');
}

function syncGarmentGender() {
  renderGarmentList(GM.key);
  const cur = GM.key && (S.garments || {})[GM.key];
  if (cur && (cur.gender || 'f') !== S.gender) {
    const first = Object.keys(S.garments || {}).find(k => ((S.garments[k] || {}).gender || 'f') === S.gender);
    if (first) loadGarment(first); else newGarment();
  } else if (!GM.key && $('#gm-gender')) {
    $('#gm-gender').value = S.gender;
    renderBindPickers();
  }
  if (GM.rightTab === 'hand') renderHandList();
}

function onGarmentTabOpen() {
  hideGarmentHover();
  renderGarmentList(GM.key);
  renderBindLanes();
  if (GM.rightTab === 'hand') renderHandList();
}

function bindGarmentEditor() {
  $$('#gm-left-tabs [data-gm-lmode]').forEach(btn => {
    btn.onclick = () => gmSwitchLeftMode(btn.dataset.gmLmode);
  });
  $$('#gm-right-tabs [data-gm-rtab]').forEach(btn => {
    btn.onclick = () => gmSwitchRightTab(btn.dataset.gmRtab);
  });
  const lsearch = $('#gm-left-search');
  if (lsearch) lsearch.oninput = e => { GM.leftSearch = e.target.value; renderGarmentList(); };

  const gnew = $('#gm-new');
  if (gnew) gnew.onclick = () => {
    if (GM.leftMode === 'garment') { gmSwitchRightTab('garment'); newGarment(); }
    else newPartToken(GM.leftMode);
  };
  const gsave = $('#gm-save2'); if (gsave) gsave.onclick = saveGarment;
  const gdel = $('#gm-del2'); if (gdel) gdel.onclick = deleteGarment;
  const gsend = $('#gm-send-work'); if (gsend) gsend.onclick = sendGarmentToWork;

  const gGender = $('#gm-gender');
  if (gGender) gGender.onchange = () => renderBindPickers();

  const bindOn = $('#gm-bind-on');
  if (bindOn) bindOn.onchange = () => { GM.bindEnabled = !!bindOn.checked; renderBindLanes(); };

  const dCustom = $('#gm-drape-custom');
  if (dCustom) dCustom.onclick = () => openTextBlockDialog({
    lane: 'positive',
    title: '添加自定义型态块',
    onSave: (text, weight) => gmAddBindBlock('drape', { text, weight }),
  });
  const fCustom = $('#gm-fabric-custom');
  if (fCustom) fCustom.onclick = () => openTextBlockDialog({
    lane: 'positive',
    title: '添加自定义材质块',
    onSave: (text, weight) => gmAddBindBlock('fabric', { text, weight }),
  });
  const dClear = $('#gm-drape-clear');
  if (dClear) dClear.onclick = () => { GM.drapeBlocks = []; renderBindLanes(); };
  const fClear = $('#gm-fabric-clear');
  if (fClear) fClear.onclick = () => { GM.fabricBlocks = []; renderBindLanes(); };
  const dSearch = $('#gm-drape-search');
  if (dSearch) dSearch.oninput = e => { GM.drapeSearch = e.target.value; renderBindPickers(); };
  const fSearch = $('#gm-fabric-search');
  if (fSearch) fSearch.oninput = e => { GM.fabricSearch = e.target.value; renderBindPickers(); };

  const pbox = $('#gm-preview-box');
  if (pbox) pbox.onclick = () => {
    const img = $('#gm-preview-img');
    if (!img || img.hidden || !img.src) return;
    const label = (($('#gm-label') || {}).value || '').trim() || GM.key || '服装预览';
    openModal(label + ' · 展示图',
      '<img src="' + esc(img.src) + '" style="display:block;max-width:100%;max-height:78vh;margin:0 auto;border-radius:12px">');
  };

  // 部件 / 发饰编辑事件
  const tkSave = $('#gm-tk-save');
  if (tkSave) tkSave.onclick = async () => {
    try {
      const name = await gmSaveLibToken({
        rawName: ($('#gm-tk-name') || {}).value,
        prefix: ($('#gm-tk-prefix') || {}).value || '@',
        text: ($('#gm-tk-text') || {}).value,
        note: ($('#gm-tk-note') || {}).value,
        gender: ($('#gm-tk-gender') || {}).value || '',
      });
      if (!name) return;
      loadPartToken(name);
      toast('已保存词条 ' + name);
    } catch (e) { toast('保存失败：' + e.message, true); }
  };
  const tkDel = $('#gm-tk-del');
  if (tkDel) tkDel.onclick = async () => {
    const name = (($('#gm-tk-name') || {}).value || '').trim();
    if (await gmDeleteLibToken(name)) {
      GM.partToken = '';
      if ($('#gm-tk-name')) $('#gm-tk-name').value = '';
      if ($('#gm-tk-text')) $('#gm-tk-text').value = '';
      if ($('#gm-tk-note')) $('#gm-tk-note').value = '';
      renderGarmentList();
      toast('已删除 ' + name);
    }
  };
  const tkSend = $('#gm-tk-send');
  if (tkSend) tkSend.onclick = () => {
    const name = gmNormalizeTokName(($('#gm-tk-name') || {}).value, ($('#gm-tk-prefix') || {}).value);
    if (!name || !(S.tokens || {})[name]) { toast('请先选择或保存词条', true); return; }
    gmSendTokenToWork(name);
  };

  // 手持物与武器编辑事件
  $$('#gm-hd-cats [data-gm-hcat]').forEach(btn => {
    btn.onclick = () => {
      GM.handCat = btn.dataset.gmHcat;
      $$('#gm-hd-cats [data-gm-hcat]').forEach(b => b.classList.toggle('on', b === btn));
      renderHandList();
    };
  });
  const hdSearch = $('#gm-hd-search');
  if (hdSearch) hdSearch.oninput = e => { GM.handSearch = e.target.value; renderHandList(); };
  const hdNew = $('#gm-hd-new'); if (hdNew) hdNew.onclick = newHandToken;
  const hdSave = $('#gm-hd-save');
  if (hdSave) hdSave.onclick = async () => {
    try {
      const name = await gmSaveLibToken({
        rawName: ($('#gm-hd-name') || {}).value,
        prefix: ($('#gm-hd-kind') || {}).value || '@HOLD_R_',
        text: ($('#gm-hd-text') || {}).value,
        note: ($('#gm-hd-note') || {}).value,
        gender: ($('#gm-hd-gender') || {}).value || '',
      });
      if (!name) return;
      loadHandToken(name);
      toast('已保存词条 ' + name);
    } catch (e) { toast('保存失败：' + e.message, true); }
  };
  const hdDel = $('#gm-hd-del');
  if (hdDel) hdDel.onclick = async () => {
    const name = (($('#gm-hd-name') || {}).value || '').trim();
    if (await gmDeleteLibToken(name)) {
      GM.handToken = '';
      newHandToken();
      toast('已删除 ' + name);
    }
  };
  const hdSend = $('#gm-hd-send');
  if (hdSend) hdSend.onclick = () => {
    const name = gmNormalizeTokName(($('#gm-hd-name') || {}).value, ($('#gm-hd-kind') || {}).value);
    if (!name || !(S.tokens || {})[name]) { toast('请先选择或保存词条', true); return; }
    gmSendTokenToWork(name);
  };
  const fillHand = (sel) => {
    const txt = (($('#gm-hd-text') || {}).value || '').trim();
    const ta = $(sel);
    if (!txt || !ta) return;
    const v = (ta.value || '').trim();
    ta.value = (v ? v.replace(/,\s*$/, '') + ', ' : '') + txt;
  };
  const fr = $('#gm-hand-fill-r'); if (fr) fr.onclick = () => fillHand('#gm-hand-r');
  const fl = $('#gm-hand-fill-l'); if (fl) fl.onclick = () => fillHand('#gm-hand-l');
  const hs = $('#gm-hand-save');
  if (hs) hs.onclick = () => {
    if (!GM.key) { toast('请先在左侧选择一套服装', true); return; }
    saveGarment();
  };
}
