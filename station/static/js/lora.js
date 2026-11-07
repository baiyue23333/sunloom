'use strict';
// LoRA 分类与下拉选项（纯函数，依赖全局 S）


const HEAVY_STYLE_LORAS = /^(Lucent Bloom|Anima_Real_Skin_Enhancer|ashima_v4|koukouya_v2|kanzarin_v1|ka-996beshi)/i;
function isHeavyStyleLora(name) { return HEAVY_STYLE_LORAS.test(String(name || '')); }

function loraCat(name) {
  const n = String(name || '');
  if (/turbo/i.test(n)) return '加速';
  if (/modare/i.test(n)) return '动作';
  if (/^sunhimi_/i.test(n)) return '角色';
  return '画师';
}
function loraDefaultWeight(name) {
  const cat = loraCat(name);
  if (cat === '角色') return 0.65;
  if (cat === '加速') return 0.75;
  return 0.66;
}
function shortLoraName(f) {
  let s = String(f).replace(/\.safetensors$/i, '');
  s = s.replace(/^sunhimi_/i, '').replace(/^animaNai.*$/i, 'animaNai(风格)').replace(/^Lucent Bloom\s+Anima Style LoRA_Bstyle_v1_anima_sun$/i, 'Lucent Bloom(风格)');
  return s.length > 22 ? s.slice(0, 21) + '…' : s;
}
function loraOptionsHtml(sel) {
  const groups = {};
  for (const f of S.loraFiles) (groups[loraCat(f)] ||= []).push(f);
  return LORA_CAT_ORDER.filter(c => groups[c] && groups[c].length).map(c =>
    '<optgroup label="' + c + '（' + groups[c].length + '）">' +
    groups[c].map(f => '<option value="' + f + '"' + (f === sel ? ' selected' : '') + ' title="' + f + '">' + shortLoraName(f) + '' + '</option>').join('') +
    '</optgroup>').join('');
}



// 画师 × 角色 的最优权重（实测/经验值；未列的组合走 fallback）
const ARTIST_CHAR_DEFAULTS = {
  'Lucent': { 'sunhimi_h2': 0.7, 'sunhimi_h4': 0.7, 'sunhimi_v2': 0.65, fallback: 0.65 },
  'ashima': { 'sunhimi_h2': 0.7, 'sunhimi_h4': 0.7, 'sunhimi_v2': 0.65, fallback: 0.65 },
  'koukouya': { 'sunhimi_h2': 0.7, 'sunhimi_h4': 0.7, 'sunhimi_v2': 0.65, fallback: 0.65 },
  'kanzarin': { 'sunhimi_h2': 0.7, 'sunhimi_h4': 0.7, 'sunhimi_v2': 0.65, fallback: 0.65 },
  'ka-996beshi': { 'sunhimi_h2': 0.7, 'sunhimi_h4': 0.7, 'sunhimi_v2': 0.65, fallback: 0.65 },
  'Skin_Enhancer': { 'sunhimi_h2': 0.25, 'sunhimi_h4': 0.25, 'sunhimi_v2': 0.22, fallback: 0.22 },
  'animaNai': { 'sunhimi_h2': 0.66, 'sunhimi_h4': 0.66, 'sunhimi_v2': 0.6, fallback: 0.6 },
};
function artistCharKey(name) {
  const n = String(name || '');
  return Object.keys(ARTIST_CHAR_DEFAULTS).find(k => n.includes(k)) || '';
}
function artistDefaultWeight(name, charName) {
  const key = artistCharKey(name);
  if (!key) return null;
  const row = ARTIST_CHAR_DEFAULTS[key];
  const c = String(charName || '').replace(/\.safetensors$/i, '');
  for (const k of Object.keys(row)) {
    if (k !== 'fallback' && c && c.includes(k)) return row[k];
  }
  return row.fallback;
}
