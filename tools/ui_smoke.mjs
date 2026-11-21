// UI 冒烟：自动拉起 headless Edge，打开工作站，跑最小交互检查
// 用法：node tools/ui_smoke.mjs [端口=8770]
import { spawn } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { COOP_START_CHECKS } from './ui_coop_start.mjs';

const PORT = process.argv[2] || '8770';
const DEBUG = 9338;
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const profile = mkdtempSync(join(tmpdir(), 'loom-smoke-'));
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// --remote-allow-origins=* ：Node 的 WebSocket 握手带 Origin，Chromium 111+ 默认拒绝
const EDGE_ARGS = ['--headless=new', '--no-sandbox', '--disable-gpu', '--disable-crash-reporter',
  '--no-first-run', '--remote-allow-origins=*', '--remote-debugging-port=' + DEBUG,
  '--user-data-dir=' + profile, 'about:blank'];
// 直接 spawn 在受限沙箱（Win 文件/管道策略）里会撞 mojo 通道 0x5 起不来，
// 退化到 PowerShell Start-Process 拉起（换独立 profile，避免上次残锁）。
const spawnEdge = (viaShell) => {
  if (!viaShell) return spawn(EDGE, EDGE_ARGS, { stdio: 'ignore' });
  const alt = EDGE_ARGS.map(a => a === '--user-data-dir=' + profile
    ? '--user-data-dir=' + mkdtempSync(join(tmpdir(), 'loom-smoke2-')) : a);
  const q = (s) => "'" + String(s).replace(/'/g, "''") + "'";
  return spawn('powershell.exe', ['-NoProfile', '-Command',
    'Start-Process -FilePath ' + q(EDGE) + ' -ArgumentList @(' + alt.map(q).join(',') + ') | Out-Null'],
    { stdio: 'ignore', windowsHide: true });
};

let edge = spawnEdge(false);
const fail = async (msg) => { console.error('FAIL ' + msg); try { edge.kill(); } catch {} process.exit(1); };

const probe = async (tries) => {
  for (let i = 0; i < tries; i++) {
    await sleep(500);
    try { return await (await fetch('http://127.0.0.1:' + DEBUG + '/json/version')).json(); } catch {}
  }
  return null;
};
let version = await probe(12);
if (!version && process.platform === 'win32') {
  try { edge.kill(); } catch {}
  edge = spawnEdge(true);
  version = await probe(30);
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
  ['LoRA 分类', "typeof loraCat === 'function' && loraCat('local_char_lora_h2.safetensors') === '角色'"],
  ['状态接口', "(async () => { const r = await fetch('/api/status'); const d = await r.json(); return !!(d.comfy && d.queue); })()"],
  ['无本地模型入口', "!document.querySelector('#btn-brain') && !document.querySelector('#llm-pick') && !document.querySelector('#btn-polish') && !document.querySelector('#btn-tags2text') && !document.querySelector('#btn-desc-compose') && !document.querySelector('#btn-artist-rec-main')"],
  ['重映三页签', "!!document.querySelector('.reproj-tabs') && document.querySelectorAll('[data-rtab]').length === 3 && !!document.querySelector('#reproj-add-scene') && !!document.querySelector('#reproj-views')"],
  ['修正接口', "(async () => { const r = await fetch('/api/fix/blocks', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({blocks:[{token:'@LIGHT_BACK'},{token:'@LIGHT_WIN'}], negatives:[]})}); const d = await r.json(); return d.by === 'rules' && d.issues.length > 0; })()"],
  ['LoRA底模过滤', "(() => { const meta = S.loraMeta || {}; const k = Object.keys(meta).find(x => /style_lora_a/i.test(x)); const okMeta = k && meta[k].base === 'anima' && Object.keys(meta).length > 40; const groups = [...document.querySelectorAll('#style-lora optgroup')].map(g => g.label); const opts = [...document.querySelectorAll('#style-lora option')].map(o => o.value).join('|'); const okList = groups.length > 0 && groups.every(x => x.startsWith('anima')) && !/moss|krea|suzuran|EndField|SushiSpin|houtei9|wooupp|lodestones/i.test(opts); return okMeta && okList; })()"],
  ['角色卡性别下拉', "(async () => { if (!S.cards || !S.cards.length) return false; const c = S.cards.find(x => (x.gender || 'f') === S.gender) || S.cards[0]; S.gender = c.gender || 'f'; await loadCards(); const sel = document.querySelector('#card-sel'); if (!sel) return false; sel.value = c.name; cardPersonaEdit(); const ok = !!document.querySelector('#cp-gender') && document.querySelectorAll('#cp-gender option').length === 2; closeModal(); return ok; })()"],
  ['分类跳转', "(function(){ const b = document.querySelector('.rail-item'); if (!b) return false; b.click(); return typeof scrollPalTo === 'function' && b.classList.contains('active'); })()"],
  ['光引导', "(function(){ if (typeof renderGuideGlow !== 'function') return false; S.pos = []; S.neg = []; S.coopOn = false; S._glowDone = false; renderGuideGlow(); const n = document.querySelectorAll('.rail-item.need').length; return !!document.querySelector('#guide-mode') && n > 0; })()"],
  ['光引导脚本', "(async () => { const r = await fetch('/api/guide/light', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ blocks: [{ token: '@ID_F' }], negatives: [], mode: 'portrait' }) }); const d = await r.json(); return !!(d.roles && d.roles.length && d.tips && d.tips.light && d.ready === false); })()"],
  ['工作流向导', "(function(){ if (typeof renderGuide !== 'function' || typeof guideApply !== 'function') return false; const b = document.querySelector('#tabs button[data-tab=\"guide\"]'); if (!b) return false; b.click(); const n = document.querySelectorAll('#guide-steps li').length; const ok = n > 0 && !!document.querySelector('#open-guide') && !!document.querySelector('#view-guide'); return ok; })()"],
  ['合作随机可用', "(async () => { const wb = document.querySelector('#coop-workbench'); if (wb && wb.hidden) document.querySelector('#coop-toggle').click(); await new Promise(r => setTimeout(r, 120)); document.querySelector('#random-ok') || document.querySelector('#btn-random').click(); await new Promise(r => setTimeout(r, 1000)); return (S.coop.envPos || []).length > 0 && (S.coop.chrPos || []).length > 0; })()"],
  ['只换场景只换装可用', "(async () => { if (S.coopOn) document.querySelector('#coop-toggle').click(); await new Promise(r => setTimeout(r, 100)); randomCompose(); await new Promise(r => setTimeout(r, 80)); const s0 = (S.pos.find(b => (b.token||'').startsWith('@SET_'))||{}).token; document.querySelector('#btn-rand-scene').click(); await new Promise(r => setTimeout(r, 80)); const s1 = (S.pos.find(b => (b.token||'').startsWith('@SET_'))||{}).token; const o0 = (S.pos.find(b => (b.token||'').startsWith('@OUT_'))||{}).token; document.querySelector('#btn-rand-outfit').click(); await new Promise(r => setTimeout(r, 80)); const o1 = (S.pos.find(b => (b.token||'').startsWith('@OUT_'))||{}).token; const p0 = (S.pos.find(b => (b.token||'').startsWith('@POSE_'))||{}).token; document.querySelector('#btn-rand-pose').click(); await new Promise(r => setTimeout(r, 80)); const p1 = (S.pos.find(b => (b.token||'').startsWith('@POSE_'))||{}).token; const c0 = (S.pos.find(b => (b.token||'').startsWith('@CAM_'))||{}).token; document.querySelector('#btn-rand-cam').click(); await new Promise(r => setTimeout(r, 80)); const c1 = (S.pos.find(b => (b.token||'').startsWith('@CAM_'))||{}).token; return !!s0 && !!s1 && s0 !== s1 && !!o0 && !!o1 && o0 !== o1 && !!p1 && p1 !== p0 && !!c0 && !!c1 && c0 !== c1; })()"],
  ['负向分流', "(function(){ const cases = [['@NEG_SUNDRESS','chrNeg'],['@NEG_FABRIC','chrNeg'],['@NEG_SHOES','chrNeg'],['@NEG_PLANT','chrNeg'],['@NEG_BASE','commonNeg'],['@NEG_PROPS','commonNeg'],['@NEG_LETTERBOX','commonNeg']]; return cases.every(function(c){ return coopBucketFor({ token: c[0] }, true) === c[1]; }); })()"],
  ['默认负向底线挂全模式', "(async () => { S.pos = []; S.neg = []; ensureDefaultNegs('global'); const hasAll = a => ['@NEG_BASE','@NEG_PLANT','@NEG_HANDS','@NEG_AI'].every(t => a.some(b => b.token === t)); const okG = hasAll(S.neg) && !S.neg.some(b => b.token === '@NEG_NO_CLIP'); S.pos = [{id:'st1',token:'@SET_CAFE',text:'',weight:1,enabled:true}]; ensureDefaultNegs('global'); const okGS = S.neg.some(b => b.token === '@NEG_NO_CLIP'); if (!S.coopOn) document.querySelector('#coop-toggle').click(); await new Promise(r => setTimeout(r, 80)); const cNeg = (S.coop.commonNeg || []).concat(S.coop.chrNeg || []); const okC = hasAll(cNeg) && cNeg.some(b => b.token === '@NEG_NO_CLIP'); if (S.coopOn) document.querySelector('#coop-toggle').click(); await new Promise(r => setTimeout(r, 80)); randomCompose(); await new Promise(r => setTimeout(r, 80)); const okR = hasAll(S.neg) && S.neg.some(b => b.token === '@NEG_NO_CLIP'); const negStep = guideSteps().find(s => s.key === 'neg'); const okW = !!(negStep && ['@NEG_BASE','@NEG_PLANT','@NEG_HANDS','@NEG_AI'].every(t => negStep.items.includes(t))); return okG && okGS && okC && okR && okW; })()"],
  ['合作参数区全保留与联动', "(async () => { const b = document.querySelector('#tabs button[data-tab=\"build\"]'); if (b) b.click(); if (!S.coopOn) document.querySelector('#coop-toggle').click(); await new Promise(r => setTimeout(r, 80)); const mf = document.querySelector('#p-model-field'), af = document.querySelector('#p-artist-field'), idf = document.querySelector('#p-identity-field'), mdl = document.querySelector('#p-model'), ast = document.querySelector('#artist-strength'), afree = document.querySelector('#artist-free'), idSel = document.querySelector('#identity-strength'), envChk = document.querySelector('#p-envdetail'); if (!mf || mf.hidden || !af || af.hidden || !idf || idf.hidden || !mdl || !ast || !afree || !idSel || !envChk) return false; const vis = [mdl, ast, afree, idSel, envChk].every(el => el.offsetParent !== null); const prevEd = envChk.checked; envChk.checked = true; envChk.dispatchEvent(new Event('change')); const hasEd = (S.coop.envPos || []).some(x => x && x.envdetail); envChk.checked = false; envChk.dispatchEvent(new Event('change')); const noEd = !(S.coop.envPos || []).some(x => x && x.envdetail); if (prevEd) { envChk.checked = true; envChk.dispatchEvent(new Event('change')); } idSel.value = '1'; idSel.dispatchEvent(new Event('change')); const hasTok = (S.coop.chrPos || []).some(x => /^@(ID|SINGLE)/.test(x.token || '')); idSel.value = '0'; idSel.dispatchEvent(new Event('change')); const hasMin = (S.coop.chrPos || []).some(x => x && x.identityMin); idSel.value = '0.5'; idSel.dispatchEvent(new Event('change')); return vis && hasEd && noEd && hasTok && hasMin; })()"],
  ['展开预览', "(async () => { S.coopOn = false; S.pos = [{id:'s1',token:'@ID',text:'',weight:1,enabled:true}]; S.neg = [{id:'n1',token:'@NEG_BASE',text:'',weight:1,enabled:true}]; await expandPreview(); const t = (document.querySelector('#preview-pos')||{}).textContent || ''; return t.toLowerCase().includes('white hair'); })()"],
  ['服装页重做与积木绑定', "(async () => { const b = document.querySelector('#tabs button[data-tab=\"garment\"]'); if (!b) return false; b.click(); await new Promise(r => setTimeout(r, 120)); const ltabs = document.querySelectorAll('#gm-left-tabs [data-gm-lmode]'); const rtabs = document.querySelectorAll('#gm-right-tabs [data-gm-rtab]'); const hasText = !!document.querySelector('#gm-prompt2') && !!document.querySelector('#gm-neg2') && ((document.querySelector('#gm-prompt2')||{}).value || '').length > 5; document.querySelector('[data-gm-lmode=\"part\"]').click(); const hasParts = document.querySelectorAll('#gm-list .gm-tok-item').length > 5; document.querySelector('[data-gm-lmode=\"hair\"]').click(); const hasHair = document.querySelectorAll('#gm-list .gm-tok-item').length > 3; document.querySelector('[data-gm-lmode=\"garment\"]').click(); const chk = document.querySelector('#gm-bind-on'); chk.checked = true; chk.dispatchEvent(new Event('change')); gmAddBindBlock('drape', '@DRAPE_OFF'); gmAddBindBlock('fabric', '@FAB_SATIN'); const hasBindChips = !!document.querySelector('#gm-drape-lane .chip[data-token=\"@DRAPE_OFF\"]') && !!document.querySelector('#gm-fabric-lane .chip[data-token=\"@FAB_SATIN\"]'); document.querySelector('[data-gm-rtab=\"hand\"]').click(); const hasHand = document.querySelectorAll('#gm-hd-list [data-hd-tok]').length > 5; document.querySelector('[data-gm-rtab=\"garment\"]').click(); chk.checked = false; chk.dispatchEvent(new Event('change')); const back = document.querySelector('#tabs button[data-tab=\"build\"]'); if (back) back.click(); return ltabs.length === 3 && rtabs.length === 3 && hasText && hasParts && hasHair && hasBindChips && hasHand; })()"],
  ['子分类归并无重复', "(async () => { S.tokenMeta = S.tokenMeta || {}; S.tokenMeta.subgroups = S.tokenMeta.subgroups || {}; const prev = S.tokenMeta.subgroups['@HAIR_F_WAVY_BANGS']; S.tokenMeta.subgroups['@HAIR_F_WAVY_BANGS'] = { label: '长度/轮廓', color: '#7aa2d6' }; renderPalette(); await loadLibrary(''); const pCnt = document.querySelectorAll('#palette [data-items=\"hair\"] .pal-sub[data-sub=\"长度/轮廓\"]').length; const lCnt = document.querySelectorAll('#token-table .tsub[data-sub=\"长度/轮廓\"]').length; if (prev === undefined) delete S.tokenMeta.subgroups['@HAIR_F_WAVY_BANGS']; else S.tokenMeta.subgroups['@HAIR_F_WAVY_BANGS'] = prev; renderPalette(); await loadLibrary(''); return pCnt === 1 && lCnt === 1; })()"],
  ['合作流水线 A/B 开关', "(() => { const box = document.querySelector('#coop-workbench > .card-head #coop-pipe-switch'), sel = document.querySelector('#coop-pipeline'); if (!box || !sel) return false; const prev = sel.value; const q = s => box.querySelector(s); if (box.querySelectorAll('.pipe-sub').length !== 0) return false; q('.pipe-ab-btn[data-fam=\"b\"]').click(); const okB = box.dataset.fam === 'b' && sel.value === 'b'; q('.pipe-ab-btn[data-fam=\"a\"]').click(); const okA = box.dataset.fam === 'a' && sel.value === 'a'; coopPipeSet(prev || 'a'); return okB && okA && sel.value === (prev === 'b' ? 'b' : 'a'); })()"],
  ['重映环境与人物独立步数及识别按钮', "(() => { const wb = document.querySelector('#coop-workbench'), es = document.querySelector('#coop-env-steps'), cs = document.querySelector('#coop-char-steps'), hb = document.querySelector('#coop-hint-btn'), bv = document.querySelector('#coop-b-variant'), lm = document.querySelector('#coop-layer-mode'); return !!(wb && es && cs && hb && bv && lm && Number(es.value) >= 12 && Number(cs.value) >= 12); })()"],
  ['重映无骨/2骨/3骨滑块与摆拍台', "(() => { const sl = document.querySelector('#coop-pose-slider'), ob2 = document.querySelector('#coop-pose2d-open'), ob3 = document.querySelector('#coop-pose-open'), m2 = document.querySelector('#pose2d-modal'), m3 = document.querySelector('#pose3d-modal'); if (!sl || sl.min !== '0' || sl.max !== '2' || !ob2 || !ob3 || !m2 || !m3) return false; sl.value = '1'; sl.dispatchEvent(new Event('input', {bubbles:true})); const p2ok = !document.querySelector('#coop-pose-2d-bar').hidden; ob2.click(); const ok2 = !m2.hidden; const x2 = document.querySelector('#pose2d-close-btn'); if (x2) x2.click(); sl.value = '2'; sl.dispatchEvent(new Event('input', {bubbles:true})); const p3ok = !document.querySelector('#coop-pose-3d-bar').hidden; ob3.click(); const ok3 = !m3.hidden; const x3 = document.querySelector('#pose3d-close-btn'); if (x3) x3.click(); sl.value = '0'; sl.dispatchEvent(new Event('input', {bubbles:true})); return p2ok && p3ok && ok2 && ok3 && typeof window.coopPoseConfig === 'function'; })()"],
  ['B线镜头优先默认与姿态栏联动', "(function(){ const bv = document.querySelector('#coop-b-variant'), pb = document.querySelector('#coop-pose-bar'), bar = document.querySelector('#coop-bchar-bar'); if (!bv || !pb || !bar) return false; const vals = [...bv.options].map(o => o.value); if (vals[0] !== 'b_lens' || !bv.querySelector('option[value=\"b_lens\"]').selected) return false; if (typeof coopPipeSet !== 'function') return false; coopPipeSet('b_lens'); const okLens = !bar.hidden && pb.hidden; bv.value = 'b_char'; bv.dispatchEvent(new Event('change')); const okChar = !bar.hidden && !pb.hidden; bv.value = 'b'; bv.dispatchEvent(new Event('change')); const okB = !bar.hidden && pb.hidden; bv.value = 'b_lens'; bv.dispatchEvent(new Event('change')); return okLens && okChar && okB; })()"],
  ['镜头积木透传 lens_spec', "(function(){ if (typeof coopLensSpec !== 'function' || typeof coopPipelineNow !== 'function') return false; const bak = JSON.stringify(S.coop || {}); S.coop = { commonPos: [{id:'c1',token:'@CAM_TELE',weight:1,enabled:true},{id:'c2',token:'@COMP_THIRDS',weight:1.4,enabled:true}], envPos: [{id:'e1',token:'@ATMO_BOKEH',weight:1,enabled:true}], chrPos: [], commonNeg: [], chrNeg: [] }; const sp = coopLensSpec(); try { S.coop = JSON.parse(bak); } catch (e) { S.coop = null; } const bv = document.querySelector('#coop-b-variant'); bv.value = 'b_lens'; bv.dispatchEvent(new Event('change')); return sp.cam_tokens.length === 1 && sp.cam_tokens[0].token === '@CAM_TELE' && sp.comp_tokens[0].weight === 1.4 && sp.bokeh_tokens[0].token === '@ATMO_BOKEH' && coopPipelineNow() === 'b_lens'; })()"],
  ['人眼审手默认不自动改手与弹窗接入', "(() => { const chk = document.querySelector('#p-handfix'); if (!chk || chk.checked) return false; return typeof refreshResultHandHint === 'function' && typeof openHandfix === 'function'; })()"],
  ...COOP_START_CHECKS,
];

let bad = 0;
for (const [name, expr] of checks) {
  const r = await evaluate(expr);
  if (r.error) { console.log('FAIL ' + name + ' -> ' + r.error); bad++; }
  else if (r.value === true) console.log('PASS ' + name);
  else { console.log('FAIL ' + name + ' -> ' + JSON.stringify(r.value)); bad++; }
}
try { await Promise.race([send('Browser.close'), sleep(1500)]); } catch {}
try { ws.close(); } catch {}
try { edge.kill(); } catch {}
await sleep(500);
console.log(bad ? ('UI SMOKE FAILED ' + bad) : 'UI SMOKE OK');
process.exit(bad ? 1 : 0);
