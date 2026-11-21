// 合作流水线 A/B 开关（重映工作台标题行内）：A（成熟混绘）/ B（B 线：镜头优先 b_lens 默认 / 绑骨空景 b_char / 旧双画 b）。
// 真实取值写回隐藏的 #coop-pipeline（coopStartReal 读取），并记住上次选择。
(function () {
  const KEY = 'loom.coopPipeline';
  const TIPS = {
    a: 'A · 快速混绘：同框出板 + SDPose 骨架门禁（快且擅长坐靠强交互）',
    b: '旧 B · 双画原型：光影定板 → 1.5× 扩幅 → 2×2 切片（对照基线）',
    b_char: 'B · 绑骨/空景(V1.5)：平光动作卡 + 结构空景全图同生 + 1.5×/2×2 协同精修',
    b_lens: '新 B · 镜头优先(推荐)：镜头一体母板 → 景深保护 + 朝向感知原位精修 → 朝向门控修脸',
  };
  const norm = v => (v === 'b_char' || v === 'char_first') ? 'b_char'
    : ((v === 'b_lens' || v === 'lens') ? 'b_lens' : ((v === 'b' || v === 'm1') ? 'b' : 'a'));
  const famOf = v => (v === 'a' ? 'a' : 'b');
  const sel = () => document.getElementById('coop-pipeline');
  const vsel = () => document.getElementById('coop-b-variant');
  const store = v => { try { localStorage.setItem(KEY, v); } catch (e) { /* 隐私模式 */ } };
  const load = () => { try { return localStorage.getItem(KEY) || ''; } catch (e) { return ''; } };

  function current() {
    const s = sel();
    return norm(String((s && s.value) || 'a').toLowerCase());
  }

  function render() {
    const box = document.getElementById('coop-pipe-switch');
    if (!box) return;
    const v = current(), fam = famOf(v);
    box.dataset.fam = fam;
    box.querySelectorAll('.pipe-ab-btn').forEach(b => {
      const on = b.dataset.fam === fam;
      b.classList.toggle('on', on);
      b.setAttribute('aria-checked', on ? 'true' : 'false');
    });
    const bv = vsel();
    const curVariant = (bv && fam === 'b') ? bv.value : v;
    const bar = document.getElementById('coop-bchar-bar');
    if (bar) bar.hidden = (fam !== 'b');
    const pbar = document.getElementById('coop-pose-bar');
    if (pbar) pbar.hidden = (fam !== 'b' || curVariant !== 'b_char');
    const inline = document.getElementById('coop-plan-inline');
    if (inline) inline.title = TIPS[curVariant] || TIPS.a;
  }

  function set(v) {
    const s = sel();
    const nv = norm(String(v || 'a').toLowerCase());
    if (!s) return;
    if (nv === 'b_char' || nv === 'b_lens') {
      const bv = vsel();
      if (bv) bv.value = nv;
      s.value = 'b';
    } else {
      s.value = nv;
    }
    store(s.value);
    s.dispatchEvent(new Event('change', { bubbles: true }));
    render();
  }

  async function detectHint() {
    const bar = document.getElementById('coop-hint-bar');
    const msg = document.getElementById('coop-hint-msg');
    const swA = document.getElementById('coop-hint-switch-a');
    const lsel = document.getElementById('coop-layer-mode');
    if (!bar || !msg) return;
    let sceneTxt = '', charTxt = '';
    let envBlocks = [], chrBlocks = [];
    try {
      if (typeof coopComposeFromBlocks === 'function') {
        const plan = coopComposeFromBlocks(0.34);
        envBlocks = (plan.envPos || []).map(b => ({ token: b.token || '', text: b.text || '', weight: Number(b.weight) || 1, enabled: true }));
        chrBlocks = (plan.chrPos || []).map(b => ({ token: b.token || '', text: b.text || '', weight: Number(b.weight) || 1, enabled: true }));
        sceneTxt = envBlocks.map(b => b.token || b.text).filter(Boolean).join(', ');
        charTxt = chrBlocks.map(b => b.token || b.text).filter(Boolean).join(', ');
      }
    } catch (e) { /* 忽略 */ }
    if (!sceneTxt && document.getElementById('coop-env-pos-lane')) {
      sceneTxt = document.getElementById('coop-env-pos-lane').textContent || '';
    }
    if (!charTxt && document.getElementById('coop-chr-pos-lane')) {
      charTxt = document.getElementById('coop-chr-pos-lane').textContent || '';
    }
    bar.hidden = false;
    msg.textContent = '识别场景提示词中…';
    try {
      const r = await fetch('/api/coop/hint', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scene: sceneTxt, char: charTxt, env_blocks: envBlocks, chr_blocks: chrBlocks }),
      }).then(x => x.json());
      msg.textContent = (r.label || '') + '：' + (r.reason || '');
      if (swA) swA.hidden = (r.tier !== 'switch_a');
      if (lsel && ['two_layer', 'two_half', 'three_depth'].includes(r.layer_mode)) {
        lsel.value = r.layer_mode;
      }
    } catch (e) {
      msg.textContent = '识别失败，请检查站台连接';
    }
  }

  function init() {
    const box = document.getElementById('coop-pipe-switch'), s = sel();
    if (!box || !s) return;
    const saved = load();
    if (saved) s.value = norm(saved.toLowerCase());
    box.addEventListener('click', e => {
      const ab = e.target.closest('.pipe-ab-btn');
      if (ab) set(ab.dataset.fam);
    });
    const bv = vsel();
    if (bv) bv.addEventListener('change', () => render());
    const hb = document.getElementById('coop-hint-btn');
    if (hb) hb.addEventListener('click', detectHint);
    const swA = document.getElementById('coop-hint-switch-a');
    if (swA) swA.addEventListener('click', () => { set('a'); swA.hidden = true; });
    box.addEventListener('keydown', e => {
      if (!e.target.closest('.pipe-ab')) return;
      if (e.key === 'ArrowLeft') { set('a'); e.preventDefault(); }
      if (e.key === 'ArrowRight') { set('b'); e.preventDefault(); }
    });
    s.addEventListener('change', render);
    render();
  }

  window.coopPipeSet = set;
  window.coopPipeFamily = current;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
