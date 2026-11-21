'use strict';
// LoRA 分类与下拉选项（纯函数，依赖全局 S）


const HEAVY_STYLE_LORAS = /^(style_lora_c|artist_lora_b_v4|artist_lora_c_v2|artist_lora_a_v1|artist_lora_d)/i;
function isHeavyStyleLora(name) { return HEAVY_STYLE_LORAS.test(String(name || '')); }

const LORA_NOTES = [
  ['@style_lora_b', 'anima · 弱3D（搭 @style_lora_b）'],
  ['style_lora_a', 'anima · 画风增强（搭 @painterly cine）'],
  ['local_char_lora_h2', '角色身份 h2'],
  ['local_char_lora_h4', '角色身份 h4'],
  ['local_char_lora_v2', '角色身份 v2'],
  ['BlueArchiveStyle', '蔚蓝档案画风'],
  ['Lucent', 'anima · 清透光感（重风格优先）'],
  ['artist_lora_b', 'anima · 厚涂画师'],
  ['artist_lora_a', 'anima · 插画线条画师'],
  ['artist_lora_c', 'anima · 平面插画画师'],
  ['artist_lora_d', 'anima · 暖肤色画师'],
  ['kieed', 'anima · 冷调画师'],
  ['painterly', '场景厚涂'],
  ['turbo', '加速 LoRA'],
  ['modare', '动作 LoRA'],
];

function loraNote(name) {
  const n = String(name || '');
  const hit = LORA_NOTES.find(([k]) => n.toLowerCase().includes(k.toLowerCase()));
  return hit ? hit[1] : '';
}

function loraRole(name) {
  const n = String(name || '');
  if (/^local_char_lora_/i.test(n)) return 'identity';
  if (/(skin_lora|style_lora_a|turbo|modare|lodestones|dmd|slider|tweaker|edit|context|detailer)/i.test(n)) return 'tool';
  if (isEnvLora(n)) return 'env';
  return 'artist';
}

function loraCat(name) {
  const n = String(name || '');
  if (/turbo/i.test(n)) return '加速';
  if (/modare/i.test(n)) return '动作';
  if (/skin_lora/i.test(n)) return '工具';
  if (/^local_char_lora_/i.test(n)) return '角色';
  if (/bg_detailer|detailer|background/i.test(n)) return '背景';
  if (isEnvLora(n) || /impasto|painterly/i.test(n)) return '厚涂';
  if (/^(nyalia|sola)|artist_lora_a_il|artist_lora_c_il/i.test(n)) return '画师';
  return '画师';
}

function loraBase(name) {
  // 2026-11-15：以 safetensors 元数据为准（anima / sd15 / moss / krea2）
  const meta = (typeof S !== 'undefined' && S.loraMeta) ? S.loraMeta[String(name)] : null;
  if (meta && meta.base) return meta.base;
  const n = String(name || '');
  if (/moss/i.test(n)) return 'moss';
  if (/krea|k2/i.test(n)) return 'krea2';
  if (/(_il\b|_il_|XL|illustrious|noob)/i.test(n)) return 'sd15';
  return 'anima';
}

function modelBase(name) {
  const n = String(name || '').toLowerCase();
  if (/moss/.test(n)) return 'moss';
  if (/krea/.test(n)) return 'krea2';
  if (/wai|sd15|illustrious|noob/.test(n)) return 'sd15';
  return 'anima';
}
function loraDefaultWeight(name) {
  const n = String(name || '');
  if (/^local_char_lora_|turbo|modare/i.test(n)) return 1;
  const tuned = artistDefaultWeight(n, '');
  return tuned != null ? tuned : 1;
}
function shortLoraName(f) {
  let s = String(f).replace(/\.safetensors$/i, '');
  s = s.replace(/^local_char_lora_/i, '').replace(/^style_lora_a.*$/i, 'style_lora_a').replace(/^style_lora_c\s+Anima Style LoRA_Bstyle_v1_anima_sun$/i, 'style_lora_c');
  return s.length > 22 ? s.slice(0, 21) + '…' : s;
}
function isEnvLora(name) {
  const n = String(name || '');
  const roles = (typeof S !== 'undefined' && S.loraRoles) || {};
  if ((roles.names || []).includes(n)) return true;
  const pats = roles.patterns || ['bg_detailer', 'impasto', 'painterly'];
  return pats.some(p => new RegExp(p, 'i').test(n));
}

function loraCompatible(name) {
  if (typeof S !== 'undefined' && S._anyBase) return true;
  const sel = (typeof $ === 'function') ? $('#p-model') : null;
  const mdl = (sel && sel.value) || '';
  const want = (typeof modelBase === 'function') ? modelBase(mdl) : 'anima';
  return loraBase(name) === want;
}

function loraOptionsHtml(sel) {
  const wantEnv = !!S._envOnly;
  const anyBase = !!S._anyBase;
  const artistOnly = !!(S._artistOnly);   // 人物画师下拉：只要画师类
  const generic = !wantEnv && !anyBase && !artistOnly;   // 普通 LoRA 行：全部列出
  const allow = ['artist', 'env'];
  const groups = {};
  for (const f of S.loraFiles) {
    // style_lora_a 的 role 是 tool（画风增强），但它是常用画师位选项，合作模式里也必须能选到
    if (!generic && allow.indexOf(loraRole(f)) < 0 && !/style_lora_a/i.test(f)) continue;
    // 人物画师下拉只留 role=artist（排除 环境/工具/身份/加速/动作）
    if (artistOnly && loraRole(f) !== 'artist' && !/style_lora_a/i.test(f)) continue;
    // 不论哪种模式，都按当前底模过滤；正在用的那个值例外，避免显示为空
    if (typeof loraCompatible === 'function' && !loraCompatible(f) && f !== sel) continue;
    if (/skin_lora/i.test(f) && f !== sel) continue;
    if (wantEnv && (S.envExclude || []).indexOf(f) >= 0) continue;
    const b = (typeof loraBase === 'function') ? loraBase(f) : 'anima';
    const baseLabel = { anima: 'anima', sd15: 'SD15', moss: 'MOSS', krea2: 'Krea2' }[b] || b;
    const key = baseLabel + ' · ' + loraCat(f);
    (groups[key] ||= []).push(f);
  }
  const order = Object.keys(groups).sort((a, b) => (a.startsWith('anima') ? -1 : 1) - (b.startsWith('anima') ? -1 : 1));
  return order.map(k =>
    '<optgroup label="' + k + '（' + groups[k].length + '）">' +
    groups[k].map(f => {
      const note = (typeof loraNote === 'function') ? loraNote(f) : '';
      const title = (k + (note ? ' · ' + note : '')).replace(/"/g, '');
      return '<option value="' + f + '"' + (f === sel ? ' selected' : '') + ' title="' + title + '">' +
        shortLoraName(f) + (note ? ' · ' + note : '') + '</option>';
    }).join('') +
    '</optgroup>').join('');
}

// 画师 × 角色 的最优权重（实测/经验值；未列的组合走 fallback）
// 2026-11-16 实测推荐权重（640x896/832x1216 Anima 底模多权重扫描 + 合作模式双 LoRA 实测）：
// fallback = 底模单图独立权重，local_char_lora_* = 搭配角色 LoRA 权重，coop = 合作模式推荐权重，limit = 过曝/发灰警戒线
const ARTIST_CHAR_DEFAULTS = {
  'painterly':      { local_char_lora_h2: 0.70, local_char_lora_h4: 0.70, local_char_lora_v2: 0.70, coop: 0.70, limit: 1.00, fallback: 0.70 },
  '@style_lora_b': { local_char_lora_h2: 1.00, local_char_lora_h4: 1.00, local_char_lora_v2: 0.95, coop: 1.00, limit: 1.25, fallback: 1.10 },
  'BlueArchive':    { local_char_lora_h2: 0.80, local_char_lora_h4: 0.80, local_char_lora_v2: 0.75, coop: 0.85, limit: 1.05, fallback: 0.85 },
  'Lucent':         { local_char_lora_h2: 0.75, local_char_lora_h4: 0.75, local_char_lora_v2: 0.70, coop: 0.75, limit: 0.95, fallback: 0.80 },
  'artist_lora_b':         { local_char_lora_h2: 0.85, local_char_lora_h4: 0.85, local_char_lora_v2: 0.80, coop: 0.85, limit: 1.10, fallback: 0.90 },
  'artist_lora_d':    { local_char_lora_h2: 0.80, local_char_lora_h4: 0.80, local_char_lora_v2: 0.75, coop: 0.85, limit: 1.05, fallback: 0.85 },
  'artist_lora_a':       { local_char_lora_h2: 0.85, local_char_lora_h4: 0.85, local_char_lora_v2: 0.80, coop: 0.85, limit: 1.05, fallback: 0.90 },
  'kieed':          { local_char_lora_h2: 0.90, local_char_lora_h4: 0.90, local_char_lora_v2: 0.85, coop: 0.90, limit: 1.10, fallback: 0.95 },
  'artist_lora_c':       { local_char_lora_h2: 0.95, local_char_lora_h4: 0.95, local_char_lora_v2: 0.90, coop: 0.95, limit: 1.25, fallback: 1.00 },
  'style_lora_a':       { local_char_lora_h2: 0.60, local_char_lora_h4: 0.60, local_char_lora_v2: 0.55, coop: 0.60, limit: 0.80, fallback: 0.65 },
};
function artistCharKey(name) {
  const n = String(name || '');
  return Object.keys(ARTIST_CHAR_DEFAULTS).find(k => n.includes(k)) || '';
}
function artistLimit(name) {
  const key = artistCharKey(name);
  return (key && ARTIST_CHAR_DEFAULTS[key].limit) || 1.15;
}

function artistDefaultWeight(name, charName) {
  if (typeof window !== 'undefined' && window.LOOM_USE_TUNED_WEIGHTS === false) return 1;
  const key = artistCharKey(name);
  if (!key) return 1;
  const row = ARTIST_CHAR_DEFAULTS[key];
  const c = String(charName || '').replace(/\.safetensors$/i, '');
  for (const k of Object.keys(row)) {
    if (k !== 'fallback' && k !== 'coop' && k !== 'limit' && c && c.includes(k)) return row[k];
  }
  return row.fallback;
}

function coopLoraDefaultWeight(name, role) {
  const key = artistCharKey(name);
  if (key && ARTIST_CHAR_DEFAULTS[key].coop != null) return ARTIST_CHAR_DEFAULTS[key].coop;
  return role === 'env' ? 0.70 : 0.85;
}


// 天生偏扁平的画师：低权重 + 自动补“反扁平”负向
const FLAT_PRONE_ARTISTS = ['artist_lora_c'];
const ANTI_FLAT_NEG = 'flat colors, vector art, posterized, plain shading, low detail, flat lighting';
function isFlatProneArtist(name) {
  return FLAT_PRONE_ARTISTS.some(k => String(name || '').includes(k));
}

const LORA_DATA_ROLE_LABEL = {
  'painterly':      ['环境厚涂', 'env',    '0.50 偏写实硬朗；0.70 建筑清晰兼顾笔触；1.00 水面略糊'],
  '@style_lora_b': ['弱 3D 风格', 'artist', '需 @style_lora_b；1.10 五官金饰最佳，1.30 暗部偏浓'],
  'BlueArchive':    ['蔚蓝清亮', 'artist', '0.85 线条与肤色最通透；1.20 明显起雾发灰'],
  'Lucent':         ['柔光通透', 'artist', '0.75-0.80 柔光恰当；1.00+ 易过曝（缺人物词易出草稿）'],
  'artist_lora_b':         ['厚涂浓色', 'artist', '0.90 发丝光影饱满；1.15 暗部偏硬（修正旧值 0.31）'],
  'artist_lora_d':    ['暖肤锐眼', 'artist', '0.85 暖肤通透与睫毛清晰最佳；1.20 泛白发雾'],
  'artist_lora_a':       ['清晰线条', 'artist', '0.85-0.95 轮廓清爽自然；1.20 发梢散乱'],
  'kieed':          ['冷调清冷', 'artist', '0.95 冷色眼瞳与蕾丝细节最佳；1.20 偏暗发灰'],
  'artist_lora_c':       ['平面简洁', 'artist', '风格温和可控，1.00 平涂色块与轮廓清晰'],
  'style_lora_a':       ['风格增强', 'tool',   '需 @painterly cine；0.65 光影提升自然，0.85+ 改发色'],
};

function _escLoraHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function showLoraDataModal() {
  if (typeof openModal !== 'function') return;
  const st = (typeof S !== 'undefined' && S) ? S : {};
  const recipes = st.artistRecipes || {};
  const files = st.loraFiles || [];
  const styleEl = document.querySelector('#style-lora');
  const envEl = document.querySelector('#coop-slora-row #coop-slora') || document.querySelector('#coop-slora');
  const ratioEl = document.querySelector('#coop-ratio');
  const ewEl = document.querySelector('#coop-env-w');
  const cwEl = document.querySelector('#coop-char-w');
  const curChar = styleEl ? styleEl.value : '';
  const curEnv = envEl ? envEl.value : '';
  const curId = (typeof currentCharLora === 'function') ? currentCharLora() : '';
  const curRatio = ratioEl ? Number(ratioEl.value || 0.34) : 0.34;
  const envPct = Math.round((1 - curRatio) * 100);
  const chrPct = Math.round(curRatio * 100);

  const seen = new Set();
  const names = [];
  Object.keys(ARTIST_CHAR_DEFAULTS).forEach(k => {
    const match = files.find(f => f.includes(k)) || Object.keys(recipes).find(f => f.includes(k));
    if (match && !seen.has(match)) { seen.add(match); names.push(match); }
  });
  Object.keys(recipes).forEach(n => { if (!seen.has(n)) { seen.add(n); names.push(n); } });

  const rowsHtml = names.map(name => {
    const key = artistCharKey(name);
    const d = ARTIST_CHAR_DEFAULTS[key] || {};
    const rec = recipes[name] || {};
    const roleMeta = LORA_DATA_ROLE_LABEL[key] || [loraCat(name), loraRole(name)];
    const roleTxt = roleMeta[0], roleCls = roleMeta[1];
    const baseW = rec.weight != null ? Number(rec.weight) : (d.fallback != null ? d.fallback : 1);
    const byC = rec.byChar || d;
    const h2W = byC['local_char_lora_h2.safetensors'] != null ? byC['local_char_lora_h2.safetensors'] : (byC.local_char_lora_h2 != null ? byC.local_char_lora_h2 : '—');
    const v2W = byC['local_char_lora_v2.safetensors'] != null ? byC['local_char_lora_v2.safetensors'] : (byC.local_char_lora_v2 != null ? byC.local_char_lora_v2 : h2W);
    const coopW = rec.coop_weight != null ? Number(rec.coop_weight) : coopLoraDefaultWeight(name, roleCls);
    const lim = artistLimit(name);
    const isCur = (name === curChar || name === curEnv);
    const noteTxt = rec.note || roleMeta[2] || loraNote(name) || '—';
    const coopPrefix = roleCls === 'env' ? 'env ' : 'char ';
    return '<tr class="' + (isCur ? 'cur' : '') + '">'
      + '<td><b>' + _escLoraHtml(shortLoraName(name)) + '</b><div class="hint" style="font-size:10.5px">' + _escLoraHtml(name) + '</div></td>'
      + '<td><span class="tag ' + roleCls + '">' + _escLoraHtml(roleTxt) + '</span></td>'
      + '<td class="num">' + baseW.toFixed(2) + '</td>'
      + '<td class="num">' + (typeof h2W === 'number' ? h2W.toFixed(2) : h2W) + ' / ' + (typeof v2W === 'number' ? v2W.toFixed(2) : v2W) + '</td>'
      + '<td class="num">' + coopPrefix + coopW.toFixed(2) + '</td>'
      + '<td class="warn-num">' + Number(lim).toFixed(2) + '</td>'
      + '<td class="note">' + _escLoraHtml(noteTxt) + '</td>'
      + '<td><button type="button" class="ghost lora-data-apply" data-lora-apply="' + _escLoraHtml(name) + '" data-role="' + roleCls + '">应用</button></td>'
      + '</tr>';
  }).join('');

  const html = '<div class="lora-data-wrap">'
    + '<div class="lora-data-summary">'
    +   '<div class="lora-data-card"><h4>合作模式（重映）默认参数与占比</h4>'
    +     '<div class="lora-data-kv">'
    +       '<span>当前占比：<b>环境 ' + envPct + '% · 人物 ' + chrPct + '%</b>（ratio=' + curRatio.toFixed(2) + '）</span>'
    +       '<span>默认推荐：<b>环境 66% / 人物 34%</b>（<code>0.34</code> · 1/3 全身）</span>'
    +       '<span>双 LoRA 默认：<b>env=' + _escLoraHtml(ewEl ? ewEl.value : '0.70') + '</b> · <b>char=' + _escLoraHtml(cwEl ? cwEl.value : '0.85') + '</b></span>'
    +       '<span>构图基准：<code>ground_y=0.88</code> · <code>x=0.34</code></span>'
    +     '</div>'
    +   '</div>'
    +   '<div class="lora-data-card"><h4>当前工作台生效状态</h4>'
    +     '<div class="lora-data-kv">'
    +       '<span>模式：<b>' + (st.coopOn ? '合作重映' : '常规拼装') + '</b></span>'
    +       '<span>人物画师：<b>' + _escLoraHtml(curChar ? shortLoraName(curChar) : '未选') + '</b></span>'
    +       '<span>环境 LoRA：<b>' + _escLoraHtml(curEnv ? shortLoraName(curEnv) : '未选') + '</b></span>'
    +       '<span>角色卡 LoRA：<b>' + _escLoraHtml(curId ? shortLoraName(curId) : '未选') + '</b></span>'
    +     '</div>'
    +   '</div>'
    + '</div>'
    + '<div class="lora-data-scroll"><table class="lora-data-table">'
    +   '<thead><tr><th>LoRA</th><th>定位</th><th>底模单图</th><th>搭角色卡 (h2/v2)</th><th>合作模式</th><th>警戒上限</th><th>实测结论（Anima）</th><th>操作</th></tr></thead>'
    +   '<tbody>' + rowsHtml + '</tbody>'
    + '</table></div>'
    + '<p class="hint" style="margin:0">基准：RTX 4060 Anima 底模（单图 640×896 22步 + 合作重映 1216×832 三阶段）；占比预设：0.20（80/20）/ 0.25（75/25）/ <b>0.34（66/34 默认）</b> / 0.45（55/45）。高亮行为当前正在使用的 LoRA。</p>'
    + '</div>';

  openModal('画师 LoRA 实测推荐值与合作占比', html);
  document.querySelectorAll('#modal-content .lora-data-apply').forEach(btn => {
    btn.onclick = () => {
      const name = btn.dataset.loraApply;
      const role = btn.dataset.role;
      if (role === 'env') {
        const w = coopLoraDefaultWeight(name, 'env');
        if (envEl) {
          envEl.value = name;
          envEl.dispatchEvent(new Event('change'));
        }
        if (ewEl) { ewEl.value = w.toFixed(2); delete ewEl.dataset.manual; }
        if (!st.coopOn && st.loras) {
          st.loras = st.loras.filter(l => loraRole(l.name) !== 'env');
          st.loras.push({ name, weight: w });
          if (typeof renderLoras === 'function') renderLoras();
        }
        if (typeof toast === 'function') toast('已应用环境 ' + shortLoraName(name) + '（权重 ' + w.toFixed(2) + '）');
      } else {
        if (styleEl) styleEl.value = name;
        if (typeof applyStyleLora === 'function') applyStyleLora(name);
        if (cwEl) {
          const cw = coopLoraDefaultWeight(name, 'char');
          cwEl.value = cw.toFixed(2);
          delete cwEl.dataset.manual;
        }
        if (typeof toast === 'function') toast('已应用 ' + shortLoraName(name));
      }
      if (typeof closeModal === 'function') closeModal();
    };
  });
}
