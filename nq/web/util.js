// Utilitaires : formats a la francaise, appels API (jeton pour les ecritures), stockage local tolerant aux pannes, petits helpers DOM.
const U = (() => {
  'use strict';
  const nf = (d) => new Intl.NumberFormat('fr-FR', {minimumFractionDigits: d, maximumFractionDigits: d});
  const cache = {};
  const fmt = (x, d = 2) => (x == null || !isFinite(x)) ? '—' : (cache[d] || (cache[d] = nf(d))).format(x).replace('-', '−');
  const sign = (x, d = 2) => (x == null || !isFinite(x)) ? '—' : (x > 0 ? '+' : '') + fmt(x, d);
  const usd = (x, d = 0) => (x == null || !isFinite(x)) ? '—' : fmt(x, d) + ' $';
  const susd = (x, d = 0) => (x == null || !isFinite(x)) ? '—' : sign(x, d) + ' $';
  const pct = (x, d = 0) => (x == null || !isFinite(x)) ? '—' : fmt(x * 100, d) + ' %';
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const cls = x => x > 0 ? 'pos' : x < 0 ? 'neg' : '';
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  let token = null;
  async function api(path, opts = {}) {
    const init = {cache: 'no-store'};
    if (opts.body !== undefined) {
      init.method = 'POST';
      init.headers = {'Content-Type': 'application/json', 'X-NQ-Token': token || ''};
      init.body = JSON.stringify(opts.body);
    }
    let r;
    try { r = await fetch(path, init); } catch (e) { throw new Error('Le terminal ne répond plus (fenêtre noire fermée ?)'); }
    let data = null;
    try { data = await r.json(); } catch (e) { /* corps vide */ }
    if (!r.ok) throw new Error((data && data.error) || ('Erreur ' + r.status));
    return data;
  }
  const setToken = t => { token = t; };

  // stockage local : peut etre indisponible (navigation privee, donnees bloquees) -> la page marche quand meme
  const store = {
    get(k, d) { try { const v = localStorage.getItem('nq.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('nq.' + k, JSON.stringify(v)); } catch (e) { /* ignore */ } },
  };

  let toastT = null;
  function toast(msg, bad = false) {
    const el = $('#toast');
    el.textContent = msg; el.className = bad ? 'bad' : ''; el.hidden = false;
    clearTimeout(toastT); toastT = setTimeout(() => { el.hidden = true; }, bad ? 6000 : 3000);
  }

  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  const hm = (tSec, tz) => new Intl.DateTimeFormat('fr-FR', {timeZone: tz === 'et' ? 'America/New_York' : 'Europe/Paris', hour: '2-digit', minute: '2-digit',
    second: '2-digit', hourCycle: 'h23'}).format(new Date(tSec * 1000));

  return {fmt, sign, usd, susd, pct, esc, cls, $, $$, api, setToken, store, toast, debounce, hm};
})();
