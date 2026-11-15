/* 系统透明度与全链路血缘诊断面板 */
(function () {
  function escH(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  window.loomClientMeta = function () {
    const keys = [];
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.startsWith('loom.')) keys.push(k);
      }
    } catch (e) {}
    return {
      ls_keys: keys.sort(),
      coop_keep_mid: !!(document.querySelector('#coop-keep-mid') && document.querySelector('#coop-keep-mid').checked),
    };
  };

  function collectLocalStorageRows() {
    const rows = [];
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (!k || !k.startsWith('loom.')) continue;
        const val = localStorage.getItem(k) || '';
        rows.push({ key: k, bytes: val.length, preview: val.slice(0, 120) });
      }
    } catch (e) {}
    rows.sort((a, b) => a.key.localeCompare(b.key));
    return rows;
  }

  async function showCoopManifest(target, isFilePath) {
    const q = isFilePath
      ? ('path=' + encodeURIComponent(target))
      : ('dir=' + encodeURIComponent(target));
    let d;
    try {
      d = await api('/api/coop/manifest?' + q);
    } catch (e) {
      toast('读取重映清单失败：' + e.message, true);
      return;
    }
    const mf = d.manifest || {};
    const cfg = d.config || mf.effective_params || {};
    const mask = mf.mask || {};
    const steps = mf.steps || [];
    const notes = mf.expand_notes || cfg.expand_notes || [];
    const suffixes = mf.suffixes || {};
    const mp = d.mem_plan || {};
    const mpMarks = mp.marks || [];

    const memHtml = mpMarks.length
      ? '<div style="font-size:12px;margin-bottom:8px">' + mpMarks.map(m =>
          '<div><code>' + escH(m.t) + 's</code> · <b>' + escH(m.phase) + '</b>' +
          (m.note ? (' · ' + escH(m.note)) : '') +
          ' · free=' + escH(m.vram_free_mb == null ? '?' : m.vram_free_mb + 'MB') +
          ' · rss=' + escH(m.rss_mb == null ? '?' : m.rss_mb + 'MB') + '</div>'
        ).join('') + '</div>'
      : '';

    const stepHtml = steps.length
      ? steps.map(s =>
          '<div style="border:1px solid rgba(255,255,255,.12);border-radius:6px;padding:6px 8px;margin-bottom:6px">' +
            '<b>' + escH(s.step) + '</b> · <span>' + escH(s.status || '') + '</span>' +
            (s.denoise !== undefined ? (' · denoise=' + escH(s.denoise)) : '') +
            (s.seed !== undefined ? (' · seed=' + escH(s.seed)) : '') +
            (s.crop_box ? (' · box=' + escH(JSON.stringify(s.crop_box))) : '') +
            (s.note ? (' · <span style="color:#ffcf70">' + escH(s.note) + '</span>') : '') +
            (s.prompt ? ('<div class="hint" style="margin-top:3px;word-break:break-word">P: ' + escH(s.prompt) + '</div>') : '') +
          '</div>'
        ).join('')
      : '<p class="hint">没有步骤清单（可能是旧版生成或尚未写入 manifest.json）。</p>';

    const imgsHtml = (d.steps_files || []).length
      ? '<div style="display:flex;gap:8px;flex-wrap:wrap;margin:6px 0">' +
        d.steps_files.map(p =>
          '<a href="/api/img?path=' + encodeURIComponent(p) + '" target="_blank" style="text-align:center;font-size:11px;color:#ccc">' +
            '<img src="/api/img?path=' + encodeURIComponent(p) + '" style="height:88px;border-radius:4px;display:block;margin-bottom:2px">' +
            escH(p.split(/[\\/]/).pop()) +
          '</a>'
        ).join('') + '</div>'
      : '';

    openModal('重映全链路血缘 · ' + escH((d.dir || '').split(/[\\/]/).pop()),
      '<div class="kv" style="margin-bottom:8px">' +
        '<span>目录</span><b>' + escH(d.dir || '') + '</b>' +
        '<span>画布 / 步数 / CFG / 种子</span><b>' + escH(cfg.width || '?') + '×' + escH(cfg.height || '?') +
          ' · ' + escH(cfg.steps || '?') + '步 · CFG ' + escH(cfg.cfg || '?') + ' · seed ' + escH(cfg.seed || '?') + '</b>' +
        '<span>遮罩策略</span><b>' + escH(mask.strategy || '无') +
          (mask.cov_pct !== undefined ? ('（覆盖率 ' + escH(mask.cov_pct) + '%）') : '') + '</b>' +
        '<span>隐式词尾</span><b style="font-size:12px">' + escH(JSON.stringify(suffixes)) + '</b>' +
      '</div>' +
      (notes.length ? ('<h4 class="rc-h">规则自动改写回执</h4><pre class="prompt-preview">' + escH(notes.join('\n')) + '</pre>') : '') +
      '<h4 class="rc-h">分步执行记录</h4>' + stepHtml +
      (imgsHtml ? ('<h4 class="rc-h">过程中间件</h4>' + imgsHtml) : '') +
      (memHtml ? ('<h4 class="rc-h">显存调度记录 (mem_plan.json)</h4>' + memHtml) : '') +
      '<h4 class="rc-h">完整子进程日志 (coop.log)</h4>' +
      '<pre class="console small" style="max-height:220px;overflow:auto">' + escH(d.log || '（无日志文件）') + '</pre>'
    );
  }
  window.showCoopManifest = showCoopManifest;

  async function openTransparencyModal() {
    let obs = {}, jobs = { items: [] }, coops = { items: [] }, mem = {};
    try {
      [obs, jobs, coops, mem] = await Promise.all([
        api('/api/observability'),
        api('/api/jobs?limit=12'),
        api('/api/coop/list?limit=10'),
        api('/api/memory'),
      ]);
    } catch (e) {
      toast('读取诊断信息失败：' + e.message, true);
      return;
    }
    const w = obs.warnings || {};
    const db = obs.db || {};
    const drift = obs.legacy_drift || {};
    const cache = obs.cache || {};
    const lsRows = collectLocalStorageRows();
    const sched = mem.scheduler || {};
    const pol = sched.policy || {};
    const stg = sched.current_stage || {};
    const mstats = sched.stats || {};
    const mevents = sched.recent_events || [];
    const ram = mem.ram || {};
    const cfMem = mem.comfy || {};
    const vfGb = cfMem.vram_free != null ? (cfMem.vram_free / 1e9).toFixed(2) : '?';
    const vtGb = cfMem.vram_total != null ? (cfMem.vram_total / 1e9).toFixed(2) : '?';

    const profileBtns = [
      ['aggressive', '省显存'],
      ['balanced', '均衡'],
      ['performance', '性能'],
    ].map(([k, lbl]) => {
      const act = pol.profile === k;
      return '<button class="' + (act ? 'primary' : 'ghost') + ' tiny" data-mem-prof="' + k + '">' +
        lbl + ' (' + k + ')</button>';
    }).join('');

    const memEvHtml = mevents.slice(0, 8).map(ev =>
      '<div style="font-size:12px;margin-bottom:3px">[' + escH(ev.context) + '] <b>' + escH(ev.action) + '</b> · ' +
      escH(ev.from_stage) + ' → ' + escH(ev.to_stage) + ' · vram=' +
      escH(ev.vram_before_mb == null ? '?' : ev.vram_before_mb) + '→' +
      escH(ev.vram_after_mb == null ? '?' : ev.vram_after_mb) + 'MB' +
      (ev.reclaimed_mb ? (' <span style="color:#7fe3a8">(+' + escH(ev.reclaimed_mb) + 'MB)</span>') : '') +
      (ev.reason ? (' · <span class="hint">' + escH(ev.reason) + '</span>') : '') + '</div>'
    ).join('') || '<p class="hint">尚无阶段调度记录。</p>';

    const driftHtml = Object.entries(drift).map(([k, v]) =>
      '<div><b>' + escH(k) + '</b>：真源=<code>' + escH(v.authoritative) + '</code> · DB=' + escH(v.db) +
      ' · 旧JSON=' + escH(v.json === null ? '无' : v.json) +
      (v.drifted ? ' <span style="color:#ffcf70">[存在漂移]</span>' : ' <span style="color:#7fe3a8">[已对齐]</span>') + '</div>'
    ).join('');

    const warnHtml = (w.recent && w.recent.length)
      ? w.recent.slice(0, 12).map(it =>
          '<div style="font-size:12px;margin-bottom:4px">[' + escH(it.where) + '] ' + escH(it.error) +
          (it.detail ? (' <span class="hint">(' + escH(it.detail) + ')</span>') : '') + '</div>'
        ).join('')
      : '<p class="hint">暂无静默错误或告警。</p>';

    const lsHtml = lsRows.length
      ? lsRows.map(r =>
          '<div style="display:flex;align-items:center;gap:8px;font-size:12px;margin-bottom:4px">' +
            '<code style="min-width:190px">' + escH(r.key) + '</code>' +
            '<span class="hint" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escH(r.bytes + ' B · ' + r.preview) + '</span>' +
            '<button class="ghost tiny" data-ls-del="' + escH(r.key) + '">清</button>' +
          '</div>'
        ).join('')
      : '<p class="hint">浏览器本地没有 loom.* 缓存键。</p>';

    const coopHtml = (coops.items || []).map(it =>
      '<div style="display:flex;align-items:center;gap:8px;font-size:12px;margin-bottom:4px">' +
        '<span style="flex:1">' + escH(it.name || it.id) + ' · ' + escH(it.mode || '-') + ' · ' + escH(it.status || '-') + '</span>' +
        ((it.has_manifest || it.has_log)
          ? ('<button class="ghost tiny" data-coop-dir="' + escH(it.dir) + '">血缘/日志</button>')
          : '<span class="hint">无清单</span>') +
      '</div>'
    ).join('') || '<p class="hint">暂无合作记录。</p>';

    const jobsHtml = (jobs.items || []).slice(0, 8).map(j =>
      '<div style="font-size:12px;margin-bottom:3px"><code>' + escH(j.id) + '</code> · ' +
      escH(j.kind) + ' · ' + escH(j.label) + ' · <b>' + escH(j.status) + '</b></div>'
    ).join('') || '<p class="hint">暂无任务记录。</p>';

    openModal('系统状态与数据透明度',
      '<div class="row2" style="margin-bottom:10px">' +
        '<button class="ghost" id="obs-refresh-lora">刷新 LoRA 缓存 (' + escH(cache.lora_meta_count || 0) + ')</button>' +
        '<button class="ghost" id="obs-sync-json">同步 DB → 旧 JSON 快照</button>' +
        '<button class="ghost" id="obs-clear-warn">清空告警 (' + escH(w.total || 0) + ')</button>' +
      '</div>' +
      '<h4 class="rc-h">显存与内存调度（底模 + 合作全链路）</h4>' +
      '<div style="font-size:12px;line-height:1.65;margin-bottom:8px">' +
        '<div>VRAM 可用 <b>' + escH(vfGb) + ' / ' + escH(vtGb) + ' GB</b> · ' +
        'RAM <b>' + escH(ram.percent == null ? '?' : ram.percent) + '%</b>（余 ' + escH(ram.free_gb || '?') + ' GB） · ' +
        '站台 ' + escH(mem.station_mb || 0) + ' MB · 常驻阶段 <code>' +
        escH((stg.family || 'idle') + (stg.unet ? ':' + stg.unet : '')) + '</code>（命中 ' + escH(stg.hits || 0) + '）</div>' +
        '<div>热命中=' + escH(mstats.keep_hits || 0) + ' · 轻清缓存=' + escH(mstats.soft_frees || 0) +
        ' · 切换卸模=' + escH(mstats.switch_unloads || 0) + ' · 低显存卸模=' + escH(mstats.hard_unloads || 0) +
        ' · OOM恢复=' + escH(mstats.oom_recoveries || 0) + ' · 释放累计=' + escH(mstats.reclaimed_vram_mb || 0) + 'MB</div>' +
        '<div class="row2" style="margin-top:6px">' + profileBtns +
          '<button class="ghost tiny" id="mem-soft-free">仅清碎片(保热模)</button>' +
          '<button class="ghost tiny" id="mem-hard-free">彻底卸模释放</button>' +
        '</div>' +
      '</div>' + memEvHtml +
      '<h4 class="rc-h">存储真源与计数（SQLite）</h4>' +
      '<div style="font-size:12px;line-height:1.6">' +
        'recipes=' + escH(db.recipes) + ' · registry=' + escH(db.registry) +
        ' · templates=' + escH(db.templates) + ' · cards=' + escH(db.cards) +
        ' · jobs_history=' + escH(db.jobs_history) + ' · coop_runs=' + escH(db.coop_runs) +
        driftHtml +
      '</div>' +
      '<h4 class="rc-h">服务端可观测告警</h4>' + warnHtml +
      '<h4 class="rc-h">最近合作流水线（可查每步 prompt / 遮罩 / 完整日志）</h4>' + coopHtml +
      '<h4 class="rc-h">持久化任务记录（重启不丢失）</h4>' + jobsHtml +
      '<h4 class="rc-h">浏览器 localStorage 黑盒状态（' + lsRows.length + ' 项）</h4>' + lsHtml
    );

    $$('#modal-content [data-mem-prof]').forEach(btn => {
      btn.onclick = async () => {
        await api('/api/memory/policy', { method: 'POST', body: JSON.stringify({ profile: btn.dataset.memProf }) });
        toast('显存策略已切换为：' + btn.dataset.memProf);
        openTransparencyModal();
      };
    });
    const sFreeBtn = $('#mem-soft-free');
    if (sFreeBtn) sFreeBtn.onclick = async () => {
      const r = await api('/api/memory/free', { method: 'POST', body: JSON.stringify({ soft: true, reason: 'ui_soft' }) });
      toast('已轻清缓存：VRAM ' + (r.before && r.before.vram_free_mb) + '→' + (r.after && r.after.vram_free_mb) + 'MB');
      openTransparencyModal();
    };
    const hFreeBtn = $('#mem-hard-free');
    if (hFreeBtn) hFreeBtn.onclick = async () => {
      const r = await api('/api/memory/free', { method: 'POST', body: JSON.stringify({ soft: false, reason: 'ui_hard' }) });
      toast('已卸载模型：VRAM ' + (r.before && r.before.vram_free_mb) + '→' + (r.after && r.after.vram_free_mb) + 'MB');
      openTransparencyModal();
    };

    const refBtn = $('#obs-refresh-lora');
    if (refBtn) refBtn.onclick = async () => {
      const r = await api('/api/loras/refresh', { method: 'POST' });
      S.loraFiles = r.loras || S.loraFiles;
      S.loraMeta = r.lora_meta || S.loraMeta;
      toast('LoRA 缓存已刷新：' + r.count + ' 个');
      openTransparencyModal();
    };
    const syncBtn = $('#obs-sync-json');
    if (syncBtn) syncBtn.onclick = async () => {
      const r = await api('/api/data/sync_json', { method: 'POST' });
      toast('已同步快照：' + JSON.stringify(r.written || {}));
      openTransparencyModal();
    };
    const clrBtn = $('#obs-clear-warn');
    if (clrBtn) clrBtn.onclick = async () => {
      await api('/api/observability/clear', { method: 'POST' });
      toast('告警缓冲已清空');
      openTransparencyModal();
    };
    $$('#modal-content [data-ls-del]').forEach(btn => {
      btn.onclick = () => {
        localStorage.removeItem(btn.dataset.lsDel);
        toast('已清除 ' + btn.dataset.lsDel);
        openTransparencyModal();
      };
    });
    $$('#modal-content [data-coop-dir]').forEach(btn => {
      btn.onclick = () => showCoopManifest(btn.dataset.coopDir, false);
    });
  }
  window.openTransparencyModal = openTransparencyModal;

  document.addEventListener('DOMContentLoaded', () => {
    const b1 = document.querySelector('#btn-transparency');
    if (b1) b1.onclick = openTransparencyModal;
    const b2 = document.querySelector('#mt-obs-open');
    if (b2) b2.onclick = openTransparencyModal;
    const lr = document.querySelector('#mt-lora-refresh');
    if (lr) lr.onclick = async () => {
      const r = await api('/api/loras/refresh', { method: 'POST' });
      if (window.S) { S.loraFiles = r.loras || S.loraFiles; S.loraMeta = r.lora_meta || S.loraMeta; }
      toast('LoRA 底模缓存已刷新：' + r.count + ' 个');
    };
    const sj = document.querySelector('#mt-sync-json');
    if (sj) sj.onclick = async () => {
      const r = await api('/api/data/sync_json', { method: 'POST' });
      toast('已把 SQLite 同步到 JSON 快照：' + JSON.stringify(r.written || {}));
    };
  });
})();
