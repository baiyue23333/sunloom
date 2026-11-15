// LoRA 分类 / 角色 / 底模识别（开源干净版：不包含任何内置私有 LoRA 清单）
function _loraRoles() { return (typeof S !== 'undefined' && S && S.loraRoles) || {}; }
function isEnvLora(f) {
  const n = String(f || '');
  const r = _loraRoles();
  if ((r.names || []).includes(n)) return true;
  return (r.patterns || ['painterly', 'impasto', 'background', 'environment', 'bg_detailer']).some(
    p => new RegExp(p, 'i').test(n)
  );
}
function isArtistLora(f) {
  const n = String(f || '');
  return !!n && !isCharLora(n) && loraBase(n) === 'anima';
}
function isCharLora(f) {
  const n = String(f || '').toLowerCase();
  if (!n) return false;
  const cardLoras = new Set((typeof S !== 'undefined' && S.cards || []).flatMap(
    c => (c.loras || []).map(l => String(l.name || '').toLowerCase())
  ));
  return cardLoras.has(n) || /^char_/i.test(n);
}
function loraRole(f) {
  if (!f) return '画师';
  if (isCharLora(f)) return '角色';
  return isEnvLora(f) ? '环境画师' : '人物画师';
}
function loraCat(f) {
  if (isCharLora(f)) return '角色';
  if (isEnvLora(f)) return '环境';
  return '画师';
}
function loraBase(f) {
  if (!f) return 'anima';
  const m = (typeof S !== 'undefined' && S && S.loraMeta) || {};
  if (m[f] && m[f].base) return m[f].base;
  const low = String(f).toLowerCase();
  if (/unknown|other/.test(low)) return 'other';
  return 'anima';
}
function shortLoraName(f) {
  let s = String(f || '').replace(/\.safetensors$/i, '');
  s = s.replace(/_anima(_v\d+)?$/i, '').replace(/^[\da-f]{6,}_/i, '');
  return s.length > 26 ? s.slice(0, 24) + '…' : s;
}
function loraOptionsHtml(selected) {
  const files = (typeof S !== 'undefined' && S.loraFiles) || [];
  const onlyAnima = files.filter(f => loraBase(f) === 'anima');
  const groups = { '人物画师（Anima）': [], '环境画师（Anima）': [], '角色 LoRA（Anima）': [] };
  onlyAnima.forEach(f => {
    const r = loraRole(f);
    if (r === '角色') groups['角色 LoRA（Anima）'].push(f);
    else if (r === '环境画师') groups['环境画师（Anima）'].push(f);
    else groups['人物画师（Anima）'].push(f);
  });
  let html = '<option value="">— 选择 Anima LoRA —</option>';
  Object.entries(groups).forEach(([label, list]) => {
    if (!list.length) return;
    html += '<optgroup label="' + label + '">';
    list.forEach(f => {
      const sel = f === selected ? ' selected' : '';
      html += '<option value="' + f.replace(/"/g, '&quot;') + '"' + sel + '>' + shortLoraName(f) + '</option>';
    });
    html += '</optgroup>';
  });
  return html;
}
function pickDefaultArtist() {
  const files = ((typeof S !== 'undefined' && S.loraFiles) || []).filter(f => loraBase(f) === 'anima' && !isCharLora(f));
  return files[0] || '';
}
function loraNote(f) { return ''; }
const HEAVY_STYLE_LORAS = new Set();
const LORA_NOTES = {};
const ARTIST_CHAR_DEFAULTS = {};
const FLAT_PRONE_ARTISTS = new Set();

function artistDefaultWeight(name, charName) {
  const st = (typeof S !== 'undefined' && S) ? S : {};
  const rec = (st.artistRecipes || {})[String(name || '')];
  if (rec) {
    if (charName && rec.byChar && rec.byChar[charName] != null) return Number(rec.byChar[charName]);
    if (rec.weight != null) return Number(rec.weight);
  }
  if (!name) return 1;
  if (isCharLora(name)) return 1.0;
  if (isEnvLora(name)) return 0.70;
  return 0.85;
}

function coopLoraDefaultWeight(name, role) {
  const st = (typeof S !== 'undefined' && S) ? S : {};
  const rec = (st.artistRecipes || {})[String(name || '')];
  if (rec && rec.coop_weight != null) return Number(rec.coop_weight);
  return role === 'env' ? 0.70 : 0.85;
}

function _escLoraHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function showLoraDataModal() {
  if (typeof openModal !== 'function') return;
  const st = (typeof S !== 'undefined' && S) ? S : {};
  const recipes = st.artistRecipes || {};
  const files = (st.loraFiles || []).filter(f => loraBase(f) === 'anima');
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

  const list = files.filter(f => !isCharLora(f));
  const rowsHtml = list.length ? list.map(name => {
    const rec = recipes[name] || {};
    const env = isEnvLora(name);
    const roleCls = env ? 'env' : 'artist';
    const roleTxt = env ? '环境画师' : '人物画师';
    const baseW = rec.weight != null ? Number(rec.weight) : artistDefaultWeight(name, curId);
    const coopW = rec.coop_weight != null ? Number(rec.coop_weight) : coopLoraDefaultWeight(name, roleCls);
    const isCur = (name === curChar || name === curEnv);
    const srcTxt = rec.note || (rec.weight != null ? '已保存本地配方' : (env ? 'Anima 环境厚涂通用推荐' : 'Anima 画师通用推荐（建议 0.80–1.00）'));
    return '<tr class="' + (isCur ? 'cur' : '') + '">'
      + '<td><b>' + _escLoraHtml(shortLoraName(name)) + '</b><div class="hint" style="font-size:10.5px">' + _escLoraHtml(name) + '</div></td>'
      + '<td><span class="tag ' + roleCls + '">' + roleTxt + '</span></td>'
      + '<td class="num">' + baseW.toFixed(2) + '</td>'
      + '<td class="num">' + (roleCls === 'env' ? 'env ' : 'char ') + coopW.toFixed(2) + '</td>'
      + '<td class="warn-num">1.10</td>'
      + '<td class="note">' + _escLoraHtml(srcTxt) + '</td>'
      + '<td><button type="button" class="ghost lora-data-apply" data-lora-apply="' + _escLoraHtml(name) + '" data-role="' + roleCls + '">应用</button></td>'
      + '</tr>';
  }).join('') : [
    ['环境画师类（painterly / impasto 等）', 'env', '环境画师', '0.70', 'env 0.70', '1.00', '阶段1 出板负责氛围与笔触；过高易糊建筑与水面细节'],
    ['人物画师类（Anima 风格 LoRA）', 'artist', '人物画师', '0.85', 'char 0.85', '1.05', '建议 0.80–1.00（强柔光/高饱和风格可降到 0.75–0.80）'],
    ['风格增强类（辅助对比/光影）', 'tool', '风格增强', '0.65', 'char 0.60', '0.80', '过高易改发色与服饰结构'],
    ['合作占比四档对照（ratio=人物占画高）', 'artist', '构图比例', '0.34 默认', '0.20 / 0.25 / 0.45', '—', '0.20 大景远人(80/20) · 0.25 风景带人(75/25) · 0.34 默认均衡(66/34) · 0.45 人物中景(55/45)'],
  ].map(r => '<tr><td><b>' + r[0] + '</b></td><td><span class="tag ' + r[1] + '">' + r[2] + '</span></td><td class="num">' + r[3] + '</td><td class="num">' + r[4] + '</td><td class="warn-num">' + r[5] + '</td><td class="note">' + r[6] + '</td><td>—</td></tr>').join('');

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
    +       '<span>角色 LoRA：<b>' + _escLoraHtml(curId ? shortLoraName(curId) : '未选') + '</b></span>'
    +     '</div>'
    +   '</div>'
    + '</div>'
    + '<div class="lora-data-scroll"><table class="lora-data-table">'
    +   '<thead><tr><th>LoRA（本机 Anima 扫描）</th><th>定位</th><th>底模默认</th><th>合作默认</th><th>警戒参考</th><th>说明 / 本地配方</th><th>操作</th></tr></thead>'
    +   '<tbody>' + rowsHtml + '</tbody>'
    + '</table></div>'
    + '<p class="hint" style="margin:0">合作模式默认环境 66% · 人物 34%（<code>ratio=0.34</code>），环境 LoRA <code>0.70</code> + 人物画师 <code>0.85</code>；表格内容自动读取你本机挂载的 Anima LoRA 与自定义配方。</p>'
    + '</div>';

  openModal('Anima 默认参数与合作占比', html);
  document.querySelectorAll('#modal-content .lora-data-apply').forEach(btn => {
    btn.onclick = () => {
      const name = btn.dataset.loraApply;
      const role = btn.dataset.role;
      if (role === 'env') {
        const w = coopLoraDefaultWeight(name, 'env');
        if (envEl) { envEl.value = name; envEl.dispatchEvent(new Event('change')); }
        if (ewEl) { ewEl.value = w.toFixed(2); delete ewEl.dataset.manual; }
        if (!st.coopOn && st.loras) {
          st.loras = st.loras.filter(l => !isEnvLora(l.name));
          st.loras.push({ name, weight: w });
          if (typeof renderLoras === 'function') renderLoras();
        }
        if (typeof toast === 'function') toast('已应用环境 ' + shortLoraName(name) + '（权重 ' + w.toFixed(2) + '）');
      } else {
        if (styleEl) styleEl.value = name;
        if (typeof applyStyleLora === 'function') applyStyleLora(name);
        if (cwEl) { cwEl.value = coopLoraDefaultWeight(name, 'char').toFixed(2); delete cwEl.dataset.manual; }
        if (typeof toast === 'function') toast('已应用 ' + shortLoraName(name));
      }
      if (typeof closeModal === 'function') closeModal();
    };
  });
}
