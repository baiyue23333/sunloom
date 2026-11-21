// 无骨 / 2骨 / 3骨 三档骨架控制与 2D OpenPose 交互画板
(function () {
  const LIMB_SEQ = [
    [1,2],[1,5],[2,3],[3,4],[5,6],[6,7],
    [1,8],[8,9],[9,10],[1,11],[11,12],[12,13],
    [1,0],[0,14],[14,16],[0,15],[15,17]
  ];
  const LIMB_COL = [
    '#990000','#993300','#996600','#999900','#669900','#339900',
    '#009900','#009933','#009966','#009999','#006699','#003399',
    '#000099','#330099','#660099','#990099','#990066'
  ];
  const J_COL = [
    '#ff0000','#ff5500','#ffaa00','#ffff00','#aaff00','#55ff00',
    '#00ff00','#00ff55','#00ffaa','#00ffff','#00aaff','#0055ff',
    '#0000ff','#5500ff','#aa00ff','#ff00ff','#ff00aa','#ff0055'
  ];
  const MIRROR_PAIRS = [[2,5],[3,6],[4,7],[8,11],[9,12],[10,13],[14,15],[16,17]];

  const S2 = {
    mode: 'none',
    lib2: null,
    preset: 'auto',
    mirror: false,
    joints2d: null,
    dragIdx: -1,
  };

  const $ = id => document.getElementById(id);
  const clone = o => JSON.parse(JSON.stringify(o || {}));

  function baseJoints() {
    if (S2.joints2d) return S2.joints2d;
    const ps = (S2.lib2 && S2.lib2.presets) || {};
    const first = Object.keys(ps)[0] || 'jump_joy';
    return clone(((ps[S2.preset] || ps[first] || {}).joints) || {});
  }

  function mirrored(src) {
    const o = {};
    Object.entries(src || {}).forEach(([k, v]) => { o[k] = [1 - Number(v[0]), Number(v[1])]; });
    MIRROR_PAIRS.forEach(([a, b]) => {
      const va = o[a], vb = o[b];
      if (va && vb) { o[a] = vb; o[b] = va; }
    });
    return o;
  }

  const MODES = ['none', '2d', '3d'];
  const MODE_LABELS = { none: '无骨', '2d': '2骨·平面', '3d': '3骨·透视' };

  function setMode(m, pctOverride) {
    S2.mode = MODES.includes(m) ? m : 'none';
    const idx = MODES.indexOf(S2.mode);
    const sl = $('coop-pose-slider');
    if (pctOverride == null && sl && Number(sl.value) !== idx) sl.value = String(idx);
    const lb = $('coop-pose-mode-label');
    if (lb) lb.textContent = MODE_LABELS[S2.mode] || '无骨';
    const tr = $('coop-pose-track');
    const pct = pctOverride != null ? Math.max(0, Math.min(100, pctOverride)) : (idx * 50);
    if (tr) tr.style.setProperty('--pose-pct', pct + '%');
    const sw = $('coop-pose-mode');
    if (sw) {
      sw.querySelectorAll('[data-pm]').forEach(el => {
        el.classList.toggle('on', el.dataset.pm === S2.mode);
      });
    }
    const p2 = $('coop-pose-2d-bar'), p3 = $('coop-pose-3d-bar'), pn = $('coop-pose-none-tip');
    if (p2) p2.hidden = (S2.mode !== '2d');
    if (p3) p3.hidden = (S2.mode !== '3d');
    if (pn) pn.hidden = (S2.mode !== 'none');
  }

  function draw2D() {
    const cv = $('pose2d-cv');
    if (!cv) return;
    const ctx = cv.getContext('2d');
    const W = cv.width, H = cv.height;
    ctx.fillStyle = '#07080d';
    ctx.fillRect(0, 0, W, H);

    // 叠加站位参考线 (ground_y, x, ratio)
    const cx = Number(($('coop-x') || {}).value) || 0.44;
    const gy = Number(($('coop-gy') || {}).value) || 0.88;
    const rt = Number(($('coop-ratio') || {}).value) || 0.44;
    ctx.strokeStyle = 'rgba(100,190,255,0.22)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(0, gy * H); ctx.lineTo(W, gy * H); ctx.stroke();
    ctx.strokeRect((cx - rt * 0.35) * W, (gy - rt) * H, rt * 0.70 * W, rt * H);
    ctx.setLineDash([]);

    const pts = S2.mirror ? mirrored(baseJoints()) : baseJoints();
    ctx.lineCap = 'round';
    LIMB_SEQ.forEach(([a, b], i) => {
      const pa = pts[a], pb = pts[b];
      if (!pa || !pb) return;
      ctx.strokeStyle = LIMB_COL[i];
      ctx.lineWidth = 5;
      ctx.beginPath(); ctx.moveTo(pa[0] * W, pa[1] * H); ctx.lineTo(pb[0] * W, pb[1] * H); ctx.stroke();
    });
    Object.entries(pts).forEach(([k, v]) => {
      const idx = Number(k);
      ctx.fillStyle = J_COL[idx] || '#fff';
      ctx.beginPath();
      ctx.arc(v[0] * W, v[1] * H, idx === S2.dragIdx ? 7 : 5, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.fillStyle = 'rgba(255,255,255,0.6)';
    ctx.font = '11px sans-serif';
    ctx.fillText('直接拖拽彩色关节点调整 2D 动态（虚线框为场景落点参考）', 10, 18);
  }

  async function loadPresets2D() {
    if (S2.lib2) return;
    try {
      const r = await fetch('/api/pose/presets').then(x => x.json());
      if (r && r.presets_2d) {
        S2.lib2 = { presets: r.presets_2d, patch_2d: r.patch_2d || '' };
        [$('coop-pose2d-preset'), $('pose2d-modal-preset')].forEach(el => {
          if (!el) return;
          const prev = el.value;
          el.innerHTML = el.id === 'coop-pose2d-preset'
            ? '<option value="auto">默认（由模型来定）</option>'
            : '';
          Object.entries(r.presets_2d).forEach(([k, v]) => {
            const o = document.createElement('option');
            o.value = k; o.textContent = v.label || k;
            el.appendChild(o);
          });
          if (prev && (prev === 'auto' || r.presets_2d[prev])) el.value = prev;
        });
      }
    } catch (e) { /* 忽略离线 */ }
  }

  async function extractFromFile(file) {
    if (!file) return;
    const tip = $('pose2d-ext-status');
    if (tip) tip.textContent = '扒骨中…';
    const b64 = await new Promise((res, rej) => {
      const fr = new FileReader();
      fr.onload = () => res(fr.result);
      fr.onerror = rej;
      fr.readAsDataURL(file);
    });
    const r = await fetch('/api/pose/extract', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_b64: b64 }),
    }).then(x => x.json());
    if (r && r.ok && r.joints2d) {
      S2.joints2d = r.joints2d;
      S2.mirror = false;
      setMode('2d');
      draw2D();
      if (tip) tip.textContent = '已扒出 2D 骨架';
    } else if (tip) {
      tip.textContent = (r && r.error) || '扒骨失败';
    }
  }

  function open2DModal() {
    if (!S2.preset || S2.preset === 'auto' || S2.preset === 'none') {
      const ps = (S2.lib2 && S2.lib2.presets) || {};
      S2.preset = Object.keys(ps)[0] || 'jump_joy';
    }
    const ms = $('pose2d-modal-preset');
    if (ms && S2.preset) ms.value = S2.preset;
    const m = $('pose2d-modal');
    if (m) m.hidden = false;
    draw2D();
    if (!S2.lib2) loadPresets2D().then(draw2D);
  }

  function init() {
    loadPresets2D();
    const sl = $('coop-pose-slider');
    const tr = $('coop-pose-track');
    if (sl) {
      sl.addEventListener('pointerdown', () => { if (tr) tr.classList.add('dragging'); });
      sl.addEventListener('input', () => {
        const v = Math.max(0, Math.min(2, Number(sl.value) || 0));
        const idx = Math.round(v);
        setMode(MODES[idx] || 'none', v * 50);
      });
      const snap = () => {
        if (tr) tr.classList.remove('dragging');
        const idx = Math.max(0, Math.min(2, Math.round(Number(sl.value) || 0)));
        setMode(MODES[idx] || 'none');
      };
      sl.addEventListener('change', snap);
      sl.addEventListener('pointerup', snap);
    }
    const sw = $('coop-pose-mode');
    if (sw) {
      sw.addEventListener('click', e => {
        const b = e.target.closest('[data-pm]');
        if (b) setMode(b.dataset.pm);
      });
    }
    const sel = $('coop-pose2d-preset'), ms = $('pose2d-modal-preset');
    if (sel) sel.addEventListener('change', () => { S2.preset = sel.value; S2.joints2d = null; if (ms) ms.value = sel.value; draw2D(); });
    if (ms) ms.addEventListener('change', () => { S2.preset = ms.value; S2.joints2d = null; if (sel) sel.value = ms.value; draw2D(); });
    const mr = $('coop-pose2d-mirror');
    if (mr) mr.addEventListener('change', () => { S2.mirror = mr.checked; draw2D(); });
    const ob = $('coop-pose2d-open');
    if (ob) ob.addEventListener('click', open2DModal);
    const xb = $('pose2d-close-btn'), ab = $('pose2d-apply-btn');
    if (xb) xb.addEventListener('click', () => { $('pose2d-modal').hidden = true; });
    if (ab) ab.addEventListener('click', () => { setMode('2d'); $('pose2d-modal').hidden = true; });
    const rb = $('pose2d-reset-btn');
    if (rb) rb.addEventListener('click', () => { S2.joints2d = null; S2.mirror = false; if (mr) mr.checked = false; draw2D(); });

    [$('pose2d-file'), $('coop-pose2d-file')].forEach(inp => {
      if (inp) inp.addEventListener('change', () => { if (inp.files && inp.files[0]) extractFromFile(inp.files[0]); });
    });
    const eb = $('coop-pose2d-extract');
    if (eb && $('coop-pose2d-file')) eb.addEventListener('click', () => $('coop-pose2d-file').click());

    const cv = $('pose2d-cv');
    if (cv) {
      const posOf = e => {
        const r = cv.getBoundingClientRect();
        return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height];
      };
      cv.addEventListener('pointerdown', e => {
        const [x, y] = posOf(e);
        const pts = S2.mirror ? mirrored(baseJoints()) : baseJoints();
        let best = -1, bd = 0.045;
        Object.entries(pts).forEach(([k, v]) => {
          const d = Math.hypot(v[0] - x, v[1] - y);
          if (d < bd) { bd = d; best = Number(k); }
        });
        if (best >= 0) {
          S2.dragIdx = best;
          if (!S2.joints2d) S2.joints2d = clone(baseJoints());
          if (S2.mirror) { S2.joints2d = mirrored(S2.joints2d); S2.mirror = false; if (mr) mr.checked = false; }
          cv.setPointerCapture(e.pointerId);
          draw2D();
        }
      });
      cv.addEventListener('pointermove', e => {
        if (S2.dragIdx < 0 || !S2.joints2d) return;
        const [x, y] = posOf(e);
        S2.joints2d[String(S2.dragIdx)] = [Math.max(0.02, Math.min(0.98, x)), Math.max(0.02, Math.min(0.98, y))];
        draw2D();
      });
      cv.addEventListener('pointerup', () => { S2.dragIdx = -1; draw2D(); });
    }
    setMode('none');
  }

  window.coopPoseConfig = function () {
    const pb = $('coop-pose-bar');
    if (pb && pb.hidden) return { mode: 'none', enabled: false };
    if (S2.mode === '2d') {
      return {
        mode: '2d',
        enabled: true,
        preset: S2.preset || 'auto',
        mirror: !!S2.mirror,
        strength: Number(($('pose2d-strength') || {}).value) || 1.25,
        end: Number(($('pose2d-end') || {}).value) || 0.48,
        joints2d: S2.joints2d || null,
      };
    }
    if (S2.mode === '3d' && typeof window.coopPose3DData === 'function') {
      return { mode: '3d', ...window.coopPose3DData(), enabled: true };
    }
    return { mode: 'none', enabled: false };
  };
  window.coopPoseSetMode = setMode;

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
