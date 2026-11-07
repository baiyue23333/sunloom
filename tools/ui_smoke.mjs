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
  ['一键修正存在', "typeof smartFix === 'function'"],
  ['LoRA 分类', "typeof loraCat === 'function' && loraCat('sunhimi_h2.safetensors') === '角色'"],
  ['状态接口', "(async () => { const r = await fetch('/api/status'); const d = await r.json(); return !!(d.comfy && d.queue); })()"],
  ['展开预览', "(async () => { S.pos = [{id:'s1',token:'@ID',text:'',weight:1,enabled:true}]; S.neg = [{id:'n1',token:'@NEG_BASE',text:'',weight:1,enabled:true}]; await expandPreview(); const t = (document.querySelector('#preview-pos')||{}).textContent || ''; return t.toLowerCase().includes('white hair'); })()"],
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
