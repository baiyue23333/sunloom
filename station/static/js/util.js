'use strict';

// 基础工具：选择器 / 请求 / 存储 / 提示 —— 从 app.js 拆出，须先于 app.js 加载

const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

const api = async (url, opt) => {
  const r = await fetch(url, opt ? { headers:{'Content-Type':'application/json'}, ...opt } : undefined);
  if (!r.ok) throw new Error(url + ' → ' + r.status + ' ' + (await r.text()).slice(0,120));
  return r.json();
};

const uid = () => Math.random().toString(36).slice(2, 9);

function esc(s) { return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function toast(msg, bad) {
  let el = $('#toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.className = 'toast show' + (bad ? ' bad' : '');
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.className = 'toast'; }, 2600);
}

function loadJSON(k, dflt) {
  try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : dflt; } catch (e) { return dflt; }
}
function saveJSON(k, v) {
  try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {}
}

