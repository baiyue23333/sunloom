'use strict';

// 服装页：左侧 服装/部件/发饰列表、悬停预览、部件发饰编辑、手持物与武器编辑
const PREVIEW_VER = '20261113c';
let _gmHoverCard = null;
let _gmHoverTimer = null;
let _gmHoverGlobalBound = false;

function hideGarmentHover() {
  if (_gmHoverTimer) { clearTimeout(_gmHoverTimer); _gmHoverTimer = null; }
  if (_gmHoverCard) { _gmHoverCard.remove(); _gmHoverCard = null; }
  document.querySelectorAll('.garment-hover').forEach(el => el.remove());
}

function bindGarmentHover() {
  const box = $('#gm-list');
  if (!box) return;
  if (!_gmHoverGlobalBound) {
    _gmHoverGlobalBound = true;
    window.addEventListener('scroll', hideGarmentHover, true);
    window.addEventListener('blur', hideGarmentHover);
    document.addEventListener('mousedown', hideGarmentHover);
  }
  if (!box.dataset.hoverLeaveBound) {
    box.dataset.hoverLeaveBound = '1';
    box.addEventListener('mouseleave', hideGarmentHover);
  }
  $$('#gm-list .gm-item[data-key]').forEach(el => {
    el.addEventListener('mouseleave', hideGarmentHover);
    el.onmouseenter = () => {
      hideGarmentHover();
      _gmHoverTimer = setTimeout(() => {
        if (!el.isConnected || !el.matches(':hover')) return;
        const key = el.dataset.key;
        const g = (S.garments || {})[key] || {};
        const r = el.getBoundingClientRect();
        const card = document.createElement('div');
        card.className = 'artist-hover garment-hover';
        card.innerHTML = '<div class="ah-title">' + esc(g.label || key) +
          '<span class="ah-kind">服装展示</span></div>' +
          '<div class="ah-thumbs"><figure class="ah-item"><img alt="" src="/api/garment_preview?key=' +
          encodeURIComponent(key) + '&v=' + encodeURIComponent(PREVIEW_VER) +
          '" onerror="this.parentNode.parentNode.dataset.empty=1">' +
          '</figure></div>' +
          '<div class="hint" style="margin-top:6px">素体穿着效果；没有图说明还没生成</div>';
        document.body.appendChild(card);
        _gmHoverCard = card;
        const clamp = () => {
          if (!_gmHoverCard || _gmHoverCard !== card) return;
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
          im.addEventListener('error', () => {
            const h = card && card.querySelector('.hint');
            if (h) h.textContent = '还没生成这套的展示图';
            clamp();
          });
        }
        requestAnimationFrame(clamp);
      }, 360);
    };
  });
}

function gmIsHairAccToken(tok) {
  return /^(?:@HAIRPIN_|@CLIP_|@PIN_|@HEADBAND_|@RIBBON_|@BERET$|@MINI_TOPHAT$|@FLOWER_CROWN$|@STRIP_HAT$|@STRIP_PLANT$|@ACC_M_(?:BEANIE|CAP|EARCUFF|EARRING)$|@ACC_F_EARRINGS$)/.test(tok);
}

function gmIsPartToken(tok) {
  if (gmIsHairAccToken(tok)) return false;
  return /^(?:@HOSE_|@BARE_FEET$|@OUT_(?:TIGHTS|SOCKS)$|@STRIP_(?:SHOES|SOCKS|COAT|GLOVES)$|@ACC_)/.test(tok);
}

function gmLeftTokenTag(tok) {
  if (tok.startsWith('@HOSE_') || /^@OUT_(TIGHTS|SOCKS)$/.test(tok)) return '丝袜/袜饰';
  if (tok === '@BARE_FEET') return '足部';
  if (tok.startsWith('@STRIP_')) return '脱除';
  if (tok.startsWith('@HAIRPIN_') || tok.startsWith('@CLIP_') || tok.startsWith('@PIN_')) return '发夹/发簪';
  if (/^@(BERET|MINI_TOPHAT|ACC_M_(BEANIE|CAP))/.test(tok)) return '帽饰';
  if (/^@(HEADBAND_|RIBBON_|FLOWER_CROWN)/.test(tok)) return '头饰';
  if (/EARRING|EARCUFF/.test(tok)) return '耳饰';
  if (/GLASSES/.test(tok)) return '眼镜';
  return '配饰';
}

function gmSendTokenToWork(tok) {
  if (!tok) return;
  addBlock('positive', tok);
  toast('已送到工作台：' + tok);
}

function renderGarmentList(activeKey) {
  hideGarmentHover();
  const box = $('#gm-list');
  if (!box) return;
  const mode = GM.leftMode || 'garment';
  const q = (GM.leftSearch || '').trim().toLowerCase();
  const hint = $('#gm-left-hint');

  if (mode === 'garment') {
    const gs = S.garments || {};
    const cur = activeKey !== undefined ? activeKey : GM.key;
    const keys = Object.keys(gs).filter(k => {
      const g = gs[k] || {};
      if ((g.gender || 'f') !== S.gender) return false;
      if (!q) return true;
      return k.toLowerCase().includes(q) || (g.label || '').toLowerCase().includes(q)
        || (g.use_for || '').toLowerCase().includes(q) || (g.note || '').toLowerCase().includes(q);
    });
    box.innerHTML = keys.length ? keys.map(k => {
      const g = gs[k] || {};
      const on = k === cur ? ' on' : '';
      return '<div class="gm-item' + on + '" data-key="' + esc(k) + '" title="' + esc(g.note || '') + '">' +
        '<b>' + esc(g.label || k) + '</b><span class="key">' + esc(k) + '</span>' +
        '<span class="use">' + esc(g.use_for || '') + (g.bind_enabled ? ' · 已绑型态/材质' : '') + '</span>' +
        '<span class="len">' + ((g.prompt || '').length) + ' 字符</span>' +
        (g.note ? '<span class="note">' + esc(g.note.slice(0, 26)) + (g.note.length > 26 ? '…' : '') + '</span>' : '') +
        '</div>';
    }).join('') : '<div class="hint">没有匹配的服装</div>';
    $$('#gm-list .gm-item').forEach(el => el.onclick = () => {
      hideGarmentHover();
      gmSwitchRightTab('garment');
      loadGarment(el.dataset.key);
    });
    bindGarmentHover();
    if (hint) hint.textContent = '悬停服装查看素体立绘；点击加载到右侧「服装编辑」。';
    return;
  }

  const pred = mode === 'hair' ? gmIsHairAccToken : gmIsPartToken;
  const toks = Object.keys(S.tokens || {}).filter(k => {
    if (!pred(k)) return false;
    if (typeof tokenVisible === 'function' && !tokenVisible(k)) return false;
    if (!q) return true;
    const txt = S.tokens[k] || '', nt = (S.notes || {})[k] || '';
    return k.toLowerCase().includes(q) || txt.toLowerCase().includes(q) || nt.toLowerCase().includes(q);
  }).sort();

  box.innerHTML = toks.length ? toks.map(k => {
    const on = k === GM.partToken ? ' on' : '';
    const cat = tokenCat(k);
    const note = (S.notes || {})[k] || S.tokens[k] || '';
    return '<div class="gm-item gm-tok-item' + on + '" data-tok="' + esc(k) + '" data-token="' + esc(k) + '" data-cat="' + cat + '">' +
      '<div class="gm-tok-main"><span class="gm-tok-name">' + esc(k) + '</span>' +
      '<span class="gm-tok-tag">' + esc(gmLeftTokenTag(k)) + '</span></div>' +
      '<span class="gm-tok-note">' + esc(note) + '</span>' +
      '<button type="button" class="ghost tiny gm-quick-add" data-send-tok="' + esc(k) + '" title="按主页逻辑送到工作台">＋</button>' +
      '</div>';
  }).join('') : '<div class="hint">没有匹配的' + (mode === 'hair' ? '发饰' : '部件') + '</div>';
  bindTips(box);

  box.querySelectorAll('.gm-tok-item').forEach(el => {
    el.onclick = () => loadPartToken(el.dataset.tok);
  });
  box.querySelectorAll('[data-send-tok]').forEach(btn => {
    btn.onclick = ev => { ev.stopPropagation(); gmSendTokenToWork(btn.dataset.sendTok); };
  });
  if (hint) hint.textContent = (mode === 'hair' ? '发饰' : '部件') + '：点击到右侧「部件 / 发饰」编辑，点「＋」送到工作台。';
}

function updateGarmentPreviewImg(key) {
  const box = $('#gm-preview-box');
  const img = $('#gm-preview-img');
  const empty = $('#gm-preview-empty');
  const cap = $('#gm-preview-cap');
  if (!box || !img || !empty) return;
  if (!key) {
    img.hidden = true; img.removeAttribute('src');
    empty.hidden = false; empty.textContent = '保存后可查看立绘展示';
    box.classList.remove('has-img');
    if (cap) cap.textContent = '新建服装';
    return;
  }
  const src = '/api/garment_preview?key=' + encodeURIComponent(key) + '&v=' + encodeURIComponent(PREVIEW_VER);
  img.onload = () => {
    img.hidden = false; empty.hidden = true;
    box.classList.add('has-img');
    if (cap) cap.textContent = '点击图片放大查看';
  };
  img.onerror = () => {
    img.hidden = true; empty.hidden = false;
    empty.textContent = '还没生成展示图';
    box.classList.remove('has-img');
    if (cap) cap.textContent = '暂无立绘参考';
  };
  img.src = src;
}

function gmSyncDerivedTokens(key, g) {
  const up = key.toUpperCase();
  const label = g.label || key;
  if (g.prompt) S.tokens['@OUT_' + up] = g.prompt;
  else delete S.tokens['@OUT_' + up];
  if (g.negative) S.tokens['@NEG_' + up] = g.negative;
  else delete S.tokens['@NEG_' + up];
  S.notes = S.notes || {};
  S.notes['@OUT_' + up] = (g.note || '').trim() || (label + '：这套服装的正向提示词，服装页里可编辑。');
  const neg = (g.negative || '').trim();
  S.notes['@NEG_' + up] = label + ' 的配套负向' + (neg ? ('：' + neg.slice(0, 60) + (neg.length > 60 ? '…' : '')) : '。') + '（服装页可改）';
  S._negGarmentSet = null;
  if (typeof renderPalette === 'function') renderPalette();
}

function gmNormalizeTokName(raw, prefix) {
  let name = String(raw || '').trim().toUpperCase().replace(/\s+/g, '_');
  if (!name) return '';
  if (!name.startsWith('@')) name = (prefix || '@') + name;
  return name;
}

async function gmSaveLibToken(opts) {
  const name = gmNormalizeTokName(opts.rawName, opts.prefix);
  if (!name || name === '@') { toast('请填写词条名', true); return ''; }
  if (!/^@[A-Z0-9_]+$/i.test(name)) { toast('词条名只允许字母、数字、下划线', true); return ''; }
  const text = (opts.text || '').trim();
  if (!text) { toast('英文描述不能为空', true); return ''; }
  const note = (opts.note || '').trim();
  const gender = opts.gender || '';
  const cat = tokenCat(name);
  const r = await api('/api/token/save', {
    method: 'POST',
    body: JSON.stringify({ name, text, category: cat, subgroup: '', color: '', gender }),
  });
  if (r && r.tokens) S.tokens = r.tokens;
  S.tokenMeta = S.tokenMeta || {};
  if (r && r.gender) S.tokenMeta.gender = r.gender;
  const nr = await api('/api/token/note', {
    method: 'POST',
    body: JSON.stringify({ name, text: note, category: 'note' }),
  });
  if (nr && nr.notes) S.notes = nr.notes;
  if (typeof renderPalette === 'function') renderPalette();
  return name;
}

async function gmDeleteLibToken(name) {
  if (!name) return false;
  if (!confirm('删除词条《' + name + '》？这会从词库中移除。')) return false;
  const r = await api('/api/token/delete', { method: 'POST', body: JSON.stringify({ name, text: '', category: 'custom' }) });
  if (r && r.tokens) S.tokens = r.tokens;
  else delete S.tokens[name];
  if (typeof renderPalette === 'function') renderPalette();
  return true;
}

/* ---------- 部件 / 发饰编辑 ---------- */
function loadPartToken(tok) {
  if (!tok || !(S.tokens || {})[tok]) return;
  GM.partToken = tok;
  gmSwitchRightTab('part');
  if ($('#gm-tk-name')) $('#gm-tk-name').value = tok;
  if ($('#gm-tk-prefix')) $('#gm-tk-prefix').value = '';
  if ($('#gm-tk-gender')) $('#gm-tk-gender').value = tokenGender(tok) || '';
  if ($('#gm-tk-text')) $('#gm-tk-text').value = S.tokens[tok] || '';
  if ($('#gm-tk-note')) $('#gm-tk-note').value = (S.notes || {})[tok] || '';
  if ($('#gm-tk-status')) $('#gm-tk-status').textContent = '编辑中：' + tok;
  const comps = typeof companionsOf === 'function' ? companionsOf(tok) : [];
  if ($('#gm-tk-companions')) {
    $('#gm-tk-companions').textContent = comps.length
      ? ('送到工作台时会自动配套：' + comps.map(c => c.token || c.text).join('、'))
      : '无额外自动配套积木';
  }
  renderGarmentList();
}

function newPartToken(mode) {
  GM.partToken = '';
  gmSwitchRightTab('part');
  if ($('#gm-tk-name')) $('#gm-tk-name').value = '';
  if ($('#gm-tk-prefix')) $('#gm-tk-prefix').value = mode === 'hair' ? '@CLIP_' : '@HOSE_';
  if ($('#gm-tk-gender')) $('#gm-tk-gender').value = S.gender || '';
  if ($('#gm-tk-text')) $('#gm-tk-text').value = '';
  if ($('#gm-tk-note')) $('#gm-tk-note').value = '';
  if ($('#gm-tk-status')) $('#gm-tk-status').textContent = '新建' + (mode === 'hair' ? '发饰' : '部件');
  if ($('#gm-tk-companions')) $('#gm-tk-companions').textContent = '';
}

/* ---------- 手持物与武器编辑 ---------- */
function renderHandList() {
  const box = $('#gm-hd-list');
  if (!box) return;
  const q = (GM.handSearch || '').trim().toLowerCase();
  const cat = GM.handCat || 'all';
  const list = Object.keys(S.tokens || {}).filter(k => {
    if (!/^@(HOLD_[RL]_|WEAPON_)/.test(k)) return false;
    if (typeof tokenVisible === 'function' && !tokenVisible(k)) return false;
    if (cat === 'hold_r' && !k.startsWith('@HOLD_R_')) return false;
    if (cat === 'hold_l' && !k.startsWith('@HOLD_L_')) return false;
    if (cat === 'weapon' && !k.startsWith('@WEAPON_')) return false;
    if (q) {
      const txt = S.tokens[k] || '', nt = (S.notes || {})[k] || '';
      if (!k.toLowerCase().includes(q) && !txt.toLowerCase().includes(q) && !nt.toLowerCase().includes(q)) return false;
    }
    return true;
  }).sort();

  box.innerHTML = list.length ? list.map(k => {
    const on = k === GM.handToken ? ' on' : '';
    const c = tokenCat(k);
    return '<div class="pal-item' + on + '" data-hd-tok="' + esc(k) + '" data-token="' + esc(k) + '" data-cat="' + c + '">' +
      '<span class="tk">' + esc(k) + '</span>' +
      '<button type="button" class="ghost tiny" data-hd-add="' + esc(k) + '" title="送到工作台" style="padding:1px 7px">＋</button>' +
      '</div>';
  }).join('') : '<div class="hint" style="padding:8px">没有匹配的手持物或武器</div>';
  bindTips(box);

  box.querySelectorAll('[data-hd-tok]').forEach(el => { el.onclick = () => loadHandToken(el.dataset.hdTok); });
  box.querySelectorAll('[data-hd-add]').forEach(btn => {
    btn.onclick = ev => { ev.stopPropagation(); gmSendTokenToWork(btn.dataset.hdAdd); };
  });
}

function loadHandToken(tok) {
  if (!tok || !(S.tokens || {})[tok]) return;
  GM.handToken = tok;
  if ($('#gm-hd-name')) $('#gm-hd-name').value = tok;
  if ($('#gm-hd-kind')) {
    $('#gm-hd-kind').value = tok.startsWith('@HOLD_L_') ? '@HOLD_L_' : (tok.startsWith('@WEAPON_') ? '@WEAPON_' : '@HOLD_R_');
  }
  if ($('#gm-hd-gender')) $('#gm-hd-gender').value = tokenGender(tok) || '';
  if ($('#gm-hd-text')) $('#gm-hd-text').value = S.tokens[tok] || '';
  if ($('#gm-hd-note')) $('#gm-hd-note').value = (S.notes || {})[tok] || '';
  if ($('#gm-hd-status')) $('#gm-hd-status').textContent = '编辑中：' + tok;
  renderHandList();
}

function newHandToken() {
  GM.handToken = '';
  if ($('#gm-hd-name')) $('#gm-hd-name').value = '';
  if ($('#gm-hd-gender')) $('#gm-hd-gender').value = '';
  if ($('#gm-hd-text')) $('#gm-hd-text').value = '';
  if ($('#gm-hd-note')) $('#gm-hd-note').value = '';
  if ($('#gm-hd-status')) $('#gm-hd-status').textContent = '新建手持物 / 武器词条';
  renderHandList();
}
