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
