// UI 冒烟：自动拉起 headless Edge，打开工作站，跑最小交互检查
// 用法：node tools/ui_smoke.mjs [端口=8770]
import { spawn } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const PORT = process.argv[2] || '8770';
const DEBUG = 9338;
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const profile = mkdtempSync(join(tmpdir(), 'loom-smoke-'));
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

const edge = spawn(EDGE, ['--headless=new', '--no-sandbox', '--disable-gpu',
  '--remote-debugging-port=' + DEBUG, '--user-data-dir=' + profile, 'about:blank'], { stdio: 'ignore' });

const fail = async (msg) => { console.error('FAIL ' + msg); try { edge.kill(); } catch {} process.exit(1); };

let version = null;
for (let i = 0; i < 40; i++) {
  await sleep(500);
  try { version = await (await fetch('http://127.0.0.1:' + DEBUG + '/json/version')).json(); break; } catch {}
}
if (!version) await fail('Edge 调试端口未就绪');

const targets = await (await fetch('http://127.0.0.1:' + DEBUG + '/json')).json();
const page = targets.find(t => t.type === 'page');
if (!page) await fail('没有可用的页面目标');

const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0;
const pending = new Map();
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
};
const send = (method, params = {}) => new Promise(res => {
  const mid = ++id; pending.set(mid, res);
  ws.send(JSON.stringify({ id: mid, method, params }));
});
const evaluate = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result && r.result.exceptionDetails) return { error: r.result.exceptionDetails.exception?.description || 'eval error' };
  return { value: r.result && r.result.result ? r.result.result.value : undefined };
};

await send('Runtime.enable');
await send('Page.enable');
await send('Page.navigate', { url: 'http://127.0.0.1:' + PORT + '/?smoke=1&v=' + Date.now() });
await sleep(6000);

const checks = [
  ['标题', "document.title === 'SUNLOOM · 织日'"],
  ['积木面板', "document.querySelectorAll('.pal-item').length > 100"],
  ['主干结构', "document.querySelectorAll('.canvas .lane').length >= 5 && !!document.querySelector('aside.params') && !!document.querySelector('.palette-body')"],
  ['一键修正存在', "typeof fixFlow === 'function'"],
  ['LoRA 分类', "typeof loraCat === 'function' && loraCat('char_oc.safetensors') === '角色' && loraCat('bg_painterly.safetensors') === '环境' && loraCat('demo_artist.safetensors') === '画师'"],
  ['状态接口', "(async () => { const r = await fetch('/api/status'); const d = await r.json(); return !!(d.comfy && d.queue); })()"],
  ['无本地模型入口', "!document.querySelector('#btn-brain') && !document.querySelector('#llm-pick') && !document.querySelector('#btn-polish') && !document.querySelector('#btn-tags2text') && !document.querySelector('#btn-desc-compose') && !document.querySelector('#btn-artist-rec-main')"],
  ['重映三页签', "!!document.querySelector('.reproj-tabs') && document.querySelectorAll('[data-rtab]').length === 3 && !!document.querySelector('#reproj-add-scene') && !!document.querySelector('#reproj-views')"],
  ['修正接口', "(async () => { const r = await fetch('/api/fix/blocks', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({blocks:[{token:'@LIGHT_BACK'},{token:'@LIGHT_WIN'}], negatives:[]})}); const d = await r.json(); return d.by === 'rules' && d.issues.length > 0; })()"],
  ['LoRA底模过滤', "(() => { const groups = [...document.querySelectorAll('#style-lora optgroup')].map(g => g.label); const okFunc = typeof loraBase === 'function' && loraBase('demo_anima_v1.safetensors') === 'anima'; const okList = groups.every(x => x.includes('Anima')); return okFunc && okList; })()"],
  ['角色卡性别下拉', "(async () => { let created = false; if (!S.cards || !S.cards.length) { await fetch('/api/card/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: '__ui_smoke__', gender: 'f', tokens: ['@ID_F'], pos_blocks: [{ token: '@ID_F' }], neg_blocks: [] }) }); await loadCards(); created = true; } const c = S.cards.find(x => (x.gender || 'f') === S.gender) || S.cards[0]; if (!c) return false; S.gender = c.gender || 'f'; await loadCards(); const sel = document.querySelector('#card-sel'); if (!sel) return false; sel.value = c.name; cardPersonaEdit(); const ok = !!document.querySelector('#cp-gender') && document.querySelectorAll('#cp-gender option').length === 2; closeModal(); if (created) { await fetch('/api/card/__ui_smoke__', { method: 'DELETE' }); await loadCards(); } return ok; })()"],
  ['分类跳转', "(function(){ const b = document.querySelector('.rail-item'); if (!b) return false; b.click(); return typeof scrollPalTo === 'function' && b.classList.contains('active'); })()"],
  ['光引导', "(function(){ if (typeof renderGuideGlow !== 'function') return false; S.pos = []; S.neg = []; S.coopOn = false; S._glowDone = false; renderGuideGlow(); const n = document.querySelectorAll('.rail-item.need').length; return !!document.querySelector('#guide-mode') && n > 0; })()"],
  ['光引导脚本', "(async () => { const r = await fetch('/api/guide/light', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ blocks: [{ token: '@ID_F' }], negatives: [], mode: 'portrait' }) }); const d = await r.json(); return !!(d.roles && d.roles.length && d.tips && d.tips.light && d.ready === false); })()"],
  ['工作流向导', "(function(){ if (typeof renderGuide !== 'function' || typeof guideApply !== 'function') return false; const b = document.querySelector('#tabs button[data-tab=\"guide\"]'); if (!b) return false; b.click(); const n = document.querySelectorAll('#guide-steps li').length; const ok = n > 0 && !!document.querySelector('#open-guide') && !!document.querySelector('#view-guide'); return ok; })()"],
  ['合作随机可用', "(async () => { const wb = document.querySelector('#coop-workbench'); if (wb && wb.hidden) document.querySelector('#coop-toggle').click(); await new Promise(r => setTimeout(r, 120)); document.querySelector('#random-ok') || document.querySelector('#btn-random').click(); await new Promise(r => setTimeout(r, 1000)); return (S.coop.envPos || []).length > 0 && (S.coop.chrPos || []).length > 0; })()"],
  ['负向分流', "(function(){ const cases = [['@NEG_SUNDRESS','chrNeg'],['@NEG_FABRIC','chrNeg'],['@NEG_SHOES','chrNeg'],['@NEG_BASE','commonNeg'],['@NEG_PROPS','commonNeg'],['@NEG_LETTERBOX','commonNeg']]; return cases.every(function(c){ return coopBucketFor({ token: c[0] }, true) === c[1]; }); })()"],
  ['展开预览', "(async () => { S.coopOn = false; S.pos = [{id:'s1',token:'@ID',text:'',weight:1,enabled:true}]; S.neg = [{id:'n1',token:'@NEG_BASE',text:'',weight:1,enabled:true}]; await expandPreview(); const t = (document.querySelector('#preview-pos')||{}).textContent || ''; return t.toLowerCase().includes('young woman'); })()"],
];

let bad = 0;
for (const [name, expr] of checks) {
  const r = await evaluate(expr);
  if (r.error) { console.log('FAIL ' + name + ' -> ' + r.error); bad++; }
  else if (r.value === true) console.log('PASS ' + name);
  else { console.log('FAIL ' + name + ' -> ' + JSON.stringify(r.value)); bad++; }
}
try { ws.close(); } catch {}
try { edge.kill(); } catch {}
console.log(bad ? ('UI SMOKE FAILED ' + bad) : 'UI SMOKE OK');
process.exit(bad ? 1 : 0);
