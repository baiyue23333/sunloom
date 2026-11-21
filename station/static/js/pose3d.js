// 3D 摆拍舞台：画布直拖 IK、构图同框、缩略图动作墙、参考图提骨与 LLLite 实时预览
(function () {
  const IK = window.POSE3D_IK;
  const S = {
    lib: null, preset: 'auto', profile: 'petite', mirror: false,
    cam_yaw: 0, cam_pitch: 4, strength: 0.62, end: 0.30,
    facing: 'auto', autoExact: true, joints: null,
    exactUrl: '', useExact: false, cat: 'all',
    cx: 0.5, gy: 0.90, ratio: 0.46,
    hoverId: '', activeId: '',
  };
  let exactTimer = null;
  let lastProj = null;

  const $ = id => document.getElementById(id);
  const clone = p => JSON.parse(JSON.stringify(p || {}));

  function currentPose() {
    if (S.joints) return S.joints;
    const ps = (S.lib && S.lib.presets) || {};
    const first = Object.keys(ps)[0] || 'walk_turn';
    return clone(ps[S.preset] || ps[first] || {});
  }

  function currentProfile() {
    return ((S.lib && S.lib.profiles) || {})[S.profile] || {
      shoulder_w: 0.20, hip_w: 0.14, upper_arm: [0.14,0.028,0.022],
      forearm: [0.13,0.023,0.018], thigh: [0.215,0.047,0.035], calf: [0.215,0.035,0.022], foot_len: 0.104,
      head_r: [0.064, 0.078, 0.068],
    };
  }

  function syncPlacementFromPage() {
    try {
      if (typeof CT_PLAN === 'object' && CT_PLAN) {
        S.cx = Number(CT_PLAN.x) || 0.5;
        S.gy = Number(CT_PLAN.ground_y) || 0.88;
        S.ratio = Number(CT_PLAN.ratio) || 0.44;
      }
    } catch (e) {}
  }

  function pushPlacementToPage() {
    try {
      if (typeof CT_PLAN === 'object' && CT_PLAN) {
        CT_PLAN.x = Number(S.cx.toFixed(3));
        CT_PLAN.ground_y = Number(S.gy.toFixed(3));
        CT_PLAN.ratio = Number(S.ratio.toFixed(3));
      }
      const set = (id, v) => { const el = $(id); if (el) el.value = v; };
      set('#coop-x', S.cx.toFixed(2));
      set('#coop-gy', S.gy.toFixed(2));
      set('#coop-ratio', S.ratio.toFixed(2));
    } catch (e) {}
  }

  function fitCanvasSize() {
    const cv = $('pose3d-cv');
    if (!cv) return { W: 320, H: 420 };
    const pw = Number(($('p-w') || {}).value) || 896;
    const ph = Number(($('p-h') || {}).value) || 1216;
    const ar = pw / Math.max(1, ph);
    let W = 340, H = Math.round(340 / ar);
    if (H > 430) { H = 430; W = Math.round(430 * ar); }
    if (W < 230) W = 230;
    if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
    return { W, H };
  }

  function scheduleExact() {
    if (!S.autoExact) return;
    if (exactTimer) clearTimeout(exactTimer);
    exactTimer = setTimeout(() => refreshExact(true), 280);
  }

  function drawViewport() {
    const cv = $('pose3d-cv');
    if (!cv || !IK) return;
    const { W, H } = fitCanvasSize();
    const ctx = cv.getContext('2d');
    ctx.fillStyle = '#07090f';
    ctx.fillRect(0, 0, W, H);

    if (S.useExact && S.exactUrl) {
      const im = new Image();
      im.onload = () => {
        ctx.drawImage(im, 0, 0, W, H);
        drawOverlay(ctx, W, H, lastProj ? lastProj.handles2d : []);
      };
      im.src = S.exactUrl;
      return;
    }

    const camR = IK.mm(IK.rotY(IK.rad(S.cam_yaw)), IK.rotX(IK.rad(S.cam_pitch)));
    const { segs, balls, handles } = IK.buildSkeleton(currentPose(), currentProfile(), S.mirror);
    const persp = 0.22;
    let ysMin = 999, topSpan = 0.2;
    const camPts = [];
    segs.forEach(([a, b, r]) => { camPts.push([IK.mv(camR, a), r], [IK.mv(camR, b), r]); });
    balls.forEach(([c, r]) => { camPts.push([IK.mv(camR, c), r]); });
    camPts.forEach(([cp, r]) => { if (cp[1] - r < ysMin) ysMin = cp[1] - r; });
    camPts.forEach(([cp, r]) => {
      const sp = ((cp[1] + r) - ysMin) / Math.max(0.35, 1 - cp[2] * persp);
      if (sp > topSpan) topSpan = sp;
    });
    const scale = (H * S.ratio) / Math.max(0.2, topSpan);
    const ox = W * S.cx, oy = H * S.gy;
    const proj = p => {
      const c = IK.mv(camR, p);
      const pf = 1 / Math.max(0.35, 1 - c[2] * persp);
      return [ox + c[0] * scale * pf, oy - (c[1] - ysMin) * scale * pf, c[2], pf];
    };

    // 地平线与脚底地面网格
    const hy = oy - Math.max(0.18, 0.52 - ysMin) * scale;
    ctx.strokeStyle = 'rgba(110,160,255,0.22)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(0, hy); ctx.lineTo(W, hy); ctx.stroke();
    ctx.setLineDash([]);
    ctx.strokeStyle = 'rgba(130,150,210,0.16)';
    ctx.lineWidth = 1;
    for (let g = -3; g <= 3; g++) {
      const a = proj([g * 0.14, ysMin, -0.4]), b = proj([g * 0.14, ysMin, 0.4]);
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      const c = proj([-0.42, ysMin, g * 0.13]), d = proj([0.42, ysMin, g * 0.13]);
      ctx.beginPath(); ctx.moveTo(c[0], c[1]); ctx.lineTo(d[0], d[1]); ctx.stroke();
    }

    const items = [];
    segs.forEach(([a, b, r, col]) => {
      const pa = proj(a), pb = proj(b);
      items.push({ z: (pa[2] + pb[2]) * 0.5, kind: 'seg', pa, pb, r: r * scale * pa[3], col });
    });
    balls.forEach(([c, r, col]) => {
      const pc = proj(c);
      items.push({ z: pc[2], kind: 'ball', pc, r: r * scale * pc[3], col });
    });
    items.sort((x, y) => x.z - y.z);
    items.forEach(it => {
      if (it.kind === 'seg') {
        ctx.lineCap = 'round';
        ctx.strokeStyle = '#aff500';
        ctx.lineWidth = it.r * 2 + 3.5;
        ctx.beginPath(); ctx.moveTo(it.pa[0], it.pa[1]); ctx.lineTo(it.pb[0], it.pb[1]); ctx.stroke();
        const grad = ctx.createLinearGradient(it.pa[0] - it.r, it.pa[1] - it.r, it.pb[0] + it.r, it.pb[1] + it.r);
        grad.addColorStop(0, '#b5a2ff'); grad.addColorStop(1, '#5844a6');
        ctx.strokeStyle = grad;
        ctx.lineWidth = it.r * 2;
        ctx.beginPath(); ctx.moveTo(it.pa[0], it.pa[1]); ctx.lineTo(it.pb[0], it.pb[1]); ctx.stroke();
      } else {
        ctx.fillStyle = '#aff500';
        ctx.beginPath(); ctx.arc(it.pc[0], it.pc[1], it.r + 1.8, 0, Math.PI * 2); ctx.fill();
        const g = ctx.createRadialGradient(it.pc[0] - it.r * 0.3, it.pc[1] - it.r * 0.3, it.r * 0.1, it.pc[0], it.pc[1], it.r);
        g.addColorStop(0, '#c7b8ff'); g.addColorStop(1, '#5c47aa');
        ctx.fillStyle = it.col === '#c7f53b' ? '#c7f53b' : g;
        ctx.beginPath(); ctx.arc(it.pc[0], it.pc[1], it.r, 0, Math.PI * 2); ctx.fill();
      }
    });

    const handles2d = handles.map(h => {
      const p2 = proj(h.pos);
      return { ...h, sx: p2[0], sy: p2[1], sz: p2[2], pf: p2[3] };
    });
    lastProj = { camR, scale, ox, oy, ysMin, persp, W, H, handles2d };
    drawOverlay(ctx, W, H, handles2d);
  }

  function drawOverlay(ctx, W, H, handles2d) {
    (handles2d || []).forEach(h => {
      const active = (h.id === S.hoverId || h.id === S.activeId);
      ctx.beginPath();
      ctx.arc(h.sx, h.sy, active ? 7 : 4.5, 0, Math.PI * 2);
      ctx.fillStyle = active ? '#00f5d4' : (h.kind === 'move' ? 'rgba(255,204,102,0.85)' : 'rgba(255,255,255,0.75)');
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = '#07090f';
      ctx.stroke();
    });
    ctx.fillStyle = 'rgba(255,255,255,0.72)';
    ctx.font = '11px sans-serif';
    ctx.fillText(`左键拖关节点摆骨 · 拖重心移站位 · 右键/空白转视角 (${Math.round(S.cam_yaw)}°,${Math.round(S.cam_pitch)}°) · 滚轮缩放 ${(S.ratio * 100).toFixed(0)}%`, 8, 16);
  }

  const SLIDERS = (IK && IK.SLIDERS) || [];

  function buildSliders() {
    const box = $('pose3d-sliders');
    if (!box) return;
    const pose = currentPose();
    box.innerHTML = '';
    SLIDERS.forEach(([label, key, idx, mn, mx]) => {
      const val = idx === null ? Number(pose[key] || 0) : Number((pose[key] || [0,0,0])[idx] || 0);
      const row = document.createElement('label');
      row.className = 'pose3d-srow';
      row.innerHTML = `<span>${label} <b class="pv">${Math.round(val)}°</b></span><input type="range" min="${mn}" max="${mx}" step="2" value="${Math.round(val)}">`;
      const inp = row.querySelector('input'), pv = row.querySelector('.pv');
      inp.addEventListener('input', () => {
        const v = Number(inp.value);
        pv.textContent = v + '°';
        if (!S.joints) S.joints = clone(currentPose());
        if (idx === null) S.joints[key] = v;
        else {
          if (!Array.isArray(S.joints[key])) S.joints[key] = [0,0,0];
          S.joints[key][idx] = v;
        }
        S.useExact = false;
        if (S.preset === 'none') S.preset = 'walk_turn';
        syncTopBar();
        drawViewport();
        scheduleExact();
      });
      box.appendChild(row);
    });
  }

  function renderGallery() {
    const box = $('pose3d-gallery');
    if (!box || !S.lib) return;
    box.innerHTML = '';
    Object.entries(S.lib.presets || {}).forEach(([k, v]) => {
      if (S.cat !== 'all' && (v.cat || 'stand') !== S.cat) return;
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'pose3d-card' + (S.preset === k ? ' on' : '');
      b.innerHTML = `<img src="/api/pose/thumb/${encodeURIComponent(k)}.png?profile=${encodeURIComponent(S.profile)}" loading="lazy" alt=""><span>${v.label || k}</span>`;
      b.addEventListener('click', () => {
        S.preset = k; S.joints = null; S.useExact = false;
        S.facing = v.facing || 'auto';
        const fs = $('pose3d-facing'); if (fs) fs.value = S.facing;
        const ms = $('pose3d-modal-preset'); if (ms) ms.value = k;
        syncTopBar(); buildSliders(); renderGallery(); drawViewport(); scheduleExact();
      });
      box.appendChild(b);
    });
  }

  function syncTopBar() {
    const sel = $('coop-pose-preset'); if (sel) sel.value = S.preset;
    const pr = $('coop-pose-profile'); if (pr) pr.value = S.profile;
    const mr = $('coop-pose-mirror'); if (mr) mr.checked = S.mirror;
  }

  async function refreshExact(silent) {
    const { W, H } = fitCanvasSize();
    const btn = $('pose3d-exact-btn');
    if (btn && !silent) btn.textContent = '渲染中…';
    try {
      const r = await fetch('/api/pose/preview', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          preset: (S.preset === 'none' || S.preset === 'auto') ? 'walk_turn' : S.preset,
          profile: S.profile, mirror: S.mirror,
          cam_yaw: S.cam_yaw, cam_pitch: S.cam_pitch,
          cx: S.cx, gy: S.gy, ratio: S.ratio,
          width: W, height: H, outline: true, joints: S.joints,
        }),
      }).then(x => x.json());
      if (r && r.image) { S.exactUrl = r.image; S.useExact = true; }
    } catch (e) {} finally {
      if (btn) btn.textContent = '精确 LLLite 预览';
      drawViewport();
    }
  }

  async function loadPresets() {
    if (S.lib) return;
    try {
      const r = await fetch('/api/pose/presets').then(x => x.json());
      if (r && r.ok) {
        S.lib = r;
        const sel = $('coop-pose-preset'), msel = $('pose3d-modal-preset');
        [sel, msel].forEach(el => {
          if (!el) return;
          const prev = el.value;
          el.innerHTML = el === sel ? '<option value="auto">默认（由模型来定）</option>' : '';
          Object.entries(r.presets || {}).forEach(([k, v]) => {
            const o = document.createElement('option');
            o.value = k; o.textContent = v.label || k;
            el.appendChild(o);
          });
          if (prev) el.value = prev;
        });
        renderGallery();
      }
    } catch (e) {}
  }

  function openModal() {
    if (S.preset === 'none' || S.preset === 'auto') S.preset = 'walk_turn';
    syncPlacementFromPage();
    const ms = $('pose3d-modal-preset'); if (ms && S.lib) ms.value = S.preset;
    syncTopBar(); buildSliders(); renderGallery(); drawViewport(); scheduleExact();
    const m = $('pose3d-modal'); if (m) m.hidden = false;
    if (!S.lib) loadPresets().then(() => { if (ms) ms.value = S.preset; buildSliders(); renderGallery(); drawViewport(); });
  }

  function handleUpload(file) {
    if (!file) return;
    const btn = $('pose3d-upload-btn');
    if (btn) btn.textContent = '提骨中…';
    const rd = new FileReader();
    rd.onload = async () => {
      try {
        const r = await fetch('/api/pose/from_image', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ image: String(rd.result || '') }),
        }).then(x => x.json());
        if (r && r.ok && r.joints) {
          S.joints = r.joints; S.mirror = false;
          if (S.preset === 'none') S.preset = 'walk_turn';
          S.facing = r.facing || 'auto';
          const fs = $('pose3d-facing'); if (fs) fs.value = S.facing;
          S.useExact = false; syncTopBar(); buildSliders(); drawViewport(); scheduleExact();
          if (typeof toast === 'function') toast('已从参考图提取 3D 骨架');
        } else if (typeof toast === 'function') toast((r && r.detail) || '提骨失败', true);
      } catch (e) {
        if (typeof toast === 'function') toast('提骨请求失败', true);
      } finally { if (btn) btn.textContent = '参考图提骨'; }
    };
    rd.readAsDataURL(file);
  }

  function init() {
    loadPresets();
    const on = (id, ev, fn) => { const el = $(id); if (el) el.addEventListener(ev, fn); };
    on('coop-pose-preset', 'change', e => {
      S.preset = e.target.value; S.joints = null; S.useExact = false;
      const p = ((S.lib && S.lib.presets) || {})[S.preset];
      S.facing = (p && p.facing) || 'auto';
    });
    on('coop-pose-profile', 'change', e => { S.profile = e.target.value; S.useExact = false; renderGallery(); drawViewport(); scheduleExact(); });
    on('coop-pose-mirror', 'change', e => { S.mirror = e.target.checked; S.useExact = false; drawViewport(); scheduleExact(); });
    on('coop-pose-open', 'click', openModal);
    on('pose3d-modal-preset', 'change', e => {
      S.preset = e.target.value; S.joints = null; S.useExact = false;
      const p = ((S.lib && S.lib.presets) || {})[S.preset];
      S.facing = (p && p.facing) || 'auto';
      const fs = $('pose3d-facing'); if (fs) fs.value = S.facing;
      syncTopBar(); buildSliders(); renderGallery(); drawViewport(); scheduleExact();
    });
    on('pose3d-facing', 'change', e => { S.facing = e.target.value; });
    on('pose3d-auto-exact', 'change', e => { S.autoExact = e.target.checked; if (S.autoExact) scheduleExact(); });
    on('pose3d-exact-btn', 'click', () => refreshExact(false));
    on('pose3d-reset-btn', 'click', () => {
      S.joints = null; S.cam_yaw = 0; S.cam_pitch = 4; S.mirror = false; S.useExact = false;
      syncTopBar(); buildSliders(); drawViewport(); scheduleExact();
    });
    on('pose3d-apply-btn', 'click', () => {
      if (S.preset === 'none') S.preset = 'walk_turn';
      pushPlacementToPage(); syncTopBar(); $('pose3d-modal').hidden = true;
    });
    on('pose3d-close-btn', 'click', () => { $('pose3d-modal').hidden = true; });
    on('pose3d-upload-btn', 'click', () => { const f = $('pose3d-file'); if (f) f.click(); });
    on('pose3d-file', 'change', e => { handleUpload(e.target.files && e.target.files[0]); e.target.value = ''; });
    const cats = $('pose3d-cats');
    if (cats) cats.addEventListener('click', e => {
      const b = e.target.closest('[data-pcat]'); if (!b) return;
      S.cat = b.dataset.pcat;
      cats.querySelectorAll('[data-pcat]').forEach(x => x.classList.toggle('on', x === b));
      renderGallery();
    });

    const cv = $('pose3d-cv');
    if (cv && IK) {
      let drag = null;
      cv.addEventListener('contextmenu', e => e.preventDefault());
      cv.addEventListener('wheel', e => {
        e.preventDefault();
        S.ratio = IK.clamp(S.ratio + (e.deltaY < 0 ? 0.03 : -0.03), 0.18, 0.85);
        S.useExact = false; pushPlacementToPage(); drawViewport(); scheduleExact();
      }, { passive: false });
      cv.addEventListener('pointerdown', e => {
        const r = cv.getBoundingClientRect();
        const mx = (e.clientX - r.left) * (cv.width / r.width);
        const my = (e.clientY - r.top) * (cv.height / r.height);
        let hit = null;
        if (e.button === 0 && lastProj) {
          let best = 16;
          lastProj.handles2d.forEach(h => {
            const d = Math.hypot(h.sx - mx, h.sy - my);
            if (d < best) { best = d; hit = h; }
          });
        }
        if (hit && hit.kind === 'ik') {
          if (S.mirror) { S.joints = IK.mirrorPose(currentPose()); S.mirror = false; syncTopBar(); }
          else if (!S.joints) S.joints = clone(currentPose());
          S.activeId = hit.id;
          drag = { mode: 'ik', hit, x: e.clientX, y: e.clientY, startPos: [...hit.pos] };
        } else if (hit && hit.kind === 'move') {
          S.activeId = hit.id;
          drag = { mode: 'move', x: e.clientX, y: e.clientY, cx: S.cx, gy: S.gy };
        } else if (hit && hit.kind === 'head') {
          if (!S.joints) S.joints = clone(currentPose());
          S.activeId = hit.id;
          drag = { mode: 'head', x: e.clientX, y: e.clientY, head: [...(S.joints.head || [0,0,0])] };
        } else {
          drag = { mode: 'orbit', x: e.clientX, y: e.clientY, yaw: S.cam_yaw, pitch: S.cam_pitch };
        }
        cv.setPointerCapture(e.pointerId);
      });
      cv.addEventListener('pointermove', e => {
        const r = cv.getBoundingClientRect();
        const mx = (e.clientX - r.left) * (cv.width / r.width);
        const my = (e.clientY - r.top) * (cv.height / r.height);
        if (!drag) {
          let hv = '';
          if (lastProj) {
            let best = 16;
            lastProj.handles2d.forEach(h => { const d = Math.hypot(h.sx - mx, h.sy - my); if (d < best) { best = d; hv = h.id; } });
          }
          if (hv !== S.hoverId) { S.hoverId = hv; cv.style.cursor = hv ? 'pointer' : 'grab'; drawViewport(); }
          return;
        }
        const dx = (e.clientX - drag.x) * (cv.width / r.width);
        const dy = (e.clientY - drag.y) * (cv.height / r.height);
        if (drag.mode === 'orbit') {
          S.cam_yaw = IK.clamp(drag.yaw + dx * 0.45, -135, 135);
          S.cam_pitch = IK.clamp(drag.pitch - dy * 0.35, -35, 45);
        } else if (drag.mode === 'move') {
          S.cx = IK.clamp(drag.cx + dx / cv.width, 0.12, 0.88);
          S.gy = IK.clamp(drag.gy + dy / cv.height, 0.48, 0.96);
          pushPlacementToPage();
        } else if (drag.mode === 'head') {
          S.joints.head = [IK.clamp(drag.head[0] + dy * 0.35, -45, 45), IK.clamp(drag.head[1] + dx * 0.45, -55, 55), drag.head[2] || 0];
          buildSliders();
        } else if (drag.mode === 'ik' && lastProj) {
          const sc = lastProj.scale * (drag.hit.pf || 1);
          const dCam = [dx / sc, -dy / sc, 0];
          const dWorld = IK.mv(IK.tr(lastProj.camR), dCam);
          const target = IK.add(drag.startPos, dWorld);
          const sol = IK.solveLimbIK(drag.hit.rootPos, target, drag.hit.L1, drag.hit.L2, drag.hit.parentRot, drag.hit.limb === 'arm');
          const sd = drag.hit.side;
          if (drag.hit.limb === 'arm') { S.joints[sd + '_shoulder'] = sol.root; S.joints[sd + '_elbow'] = sol.mid; }
          else { S.joints[sd + '_hip'] = sol.root; S.joints[sd + '_knee'] = sol.mid; }
          buildSliders();
        }
        S.useExact = false;
        drawViewport();
      });
      cv.addEventListener('pointerup', () => {
        if (drag) { drag = null; S.activeId = ''; drawViewport(); scheduleExact(); }
      });
    }
  }

  window.coopPose3DData = function () {
    const facing = (S.facing && S.facing !== 'auto') ? S.facing : (IK ? IK.facingFromYaw(currentPose(), S.cam_yaw) : 'front');
    return {
      preset: S.preset || 'auto',
      profile: S.profile || 'petite',
      mirror: !!S.mirror, cam_yaw: Number(S.cam_yaw) || 0, cam_pitch: Number(S.cam_pitch) || 4,
      strength: Number(($('pose3d-strength') || {}).value) || S.strength,
      end: Number(($('pose3d-end') || {}).value) || S.end,
      facing, joints: S.joints || null,
    };
  };
  if (typeof window.coopPoseConfig !== 'function') {
    window.coopPoseConfig = function () {
      const en = S.preset && S.preset !== 'none';
      return { mode: en ? '3d' : 'none', enabled: !!en, ...window.coopPose3DData() };
    };
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
