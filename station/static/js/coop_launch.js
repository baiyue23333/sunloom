// 合作提交生命周期：受理前不轮询旧任务，失败信息保留在状态栏。
const CoopLaunch = {
  pending: false, epoch: 0, jobId: '', error: '',
  run(work) {
    if (this.pending) return Promise.resolve(null);
    this.pending = true;
    this.epoch++;
    this.jobId = '';
    this.error = '';
    if (coopTimer) { clearInterval(coopTimer); coopTimer = null; }
    const button = document.querySelector('#run-btn');
    if (button) button.disabled = true;
    return Promise.resolve().then(work).catch(error => this.fail(error));
  },
  accept(id) {
    this.pending = false;
    this.jobId = id || '';
  },
  fail(error) {
    this.pending = false;
    this.epoch++;
    this.jobId = '';
    this.error = (error && error.message) || String(error || '未知错误');
    if (coopTimer) { clearInterval(coopTimer); coopTimer = null; }
    const status = document.querySelector('#run-status');
    if (status) status.textContent = '合作启动失败：' + this.error;
    const button = document.querySelector('#run-btn');
    if (button) button.disabled = false;
    toast('合作启动失败：' + this.error, true);
    console.error('[coop/start]', error);
    api('/api/coop/client-error', {method:'POST', body:JSON.stringify({message:this.error.slice(0,1500)})}).catch(() => {});
    return null;
  },
  current(epoch, state) {
    if (epoch !== this.epoch || this.pending || this.error) return false;
    return !this.jobId || state.id === this.jobId;
  }
};
