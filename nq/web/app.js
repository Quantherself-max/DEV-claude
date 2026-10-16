// Demarrage et rafraichissements. Chaque lecture est protegee contre le chevauchement (une requete lente n'en empile pas d'autres) et la page signale
// clairement quand le terminal ne repond plus.
(() => {
  'use strict';
  const {$, $$, api, fmt, sign, usd, susd, esc, store} = U;
  const S = {tf: store.get('tf', '1m'), theme: store.get('theme', 'nuit'), tz: store.get('tz', 'paris'), lvl: store.get('lvl', 'key'), vp: store.get('vp', 'rth'),
    cvd: store.get('cvd', 'gx'), zones: store.get('zones', false), bigs: store.get('bigs', true), abs: store.get('abs', true), tab: store.get('tab', 'lecture'),
    pos: store.get('pos', ''), boot: null, state: null, price: null, acct: null, lv: null, fails: 0};

  const getLast = () => S.price;
  const getPos = () => S.pos;
  const setPos = v => { S.pos = v || ''; store.set('pos', S.pos); };
  const tzNow = () => S.tz;

  // ---------- lectures periodiques ----------
  function every(fn, ms, name) {
    let busy = false;
    const run = async () => {
      if (busy || document.hidden) return;
      busy = true;
      try { await fn(); if (name === 'state') S.fails = 0; }
      catch (e) { if (name === 'state') { S.fails++; if (S.fails >= 3) banner(e.message, true); } }
      finally { busy = false; }
    };
    run(); setInterval(run, ms);
    return run;
  }

  function banner(msg, bad) {
    const b = $('#banner');
    if (!msg) { b.hidden = true; return; }
    b.textContent = msg; b.className = bad ? 'bad' : ''; b.hidden = false;
  }

  async function pollState() {
    const st = await api('/api/state');
    if (S.boot && st.boot !== S.boot) { location.reload(); return; }        // le terminal a redemarre (nouvelle version) : on recharge la page
    S.boot = st.boot; S.state = st;
    const prev = S.price, p = st.last ? st.last.p : null;
    S.price = p;
    const pe = $('#price');
    pe.textContent = p == null ? '—' : fmt(p, 2);
    if (prev != null && p != null && p !== prev) { pe.className = p > prev ? 'up' : 'dn'; }
    $('#contract').textContent = st.contract.code;
    $('#roll').textContent = st.contract.rollSoon ? `roll → ${st.contract.next} dans ${Math.max(0, Math.round(st.contract.rollInDays))} j` : '';
    $('#clkParis').textContent = st.clock.paris; $('#clkEt').textContent = st.clock.et;
    const ph = st.clock.phase;
    $('#phase').textContent = ph.label;
    const m = st.clock.marks[0];
    $('#nextMark').textContent = m ? `${m.label} dans ${m.in} min (${m.paris})` : '';
    const sb = $('#srcBadge');
    if (st.source.simulated) { sb.textContent = 'DONNÉES SIMULÉES'; sb.className = 'badge sim'; sb.title = 'Prix fictifs : rien ici ne dit quoi que ce soit du vrai marché'; }
    else {
      const est = st.deltaReal != null && st.deltaReal < 0.8;
      sb.textContent = (st.source.label || 'Source') + (est ? ' · delta estimé' : ''); sb.className = 'badge ' + (est ? 'warn' : 'ok');
      sb.title = est ? 'Le côté de l\'agresseur n\'est pas fourni : delta et CVD sont estimés par la règle du tick' : 'Côté de l\'agresseur fourni par la source : delta et CVD réels';
    }
    if (st.status.state === 'error') banner(st.status.msg, true);
    else if (st.status.state === 'empty') banner(st.status.msg + ' Vérifie la source (README).', false);
    else if (st.status.state === 'loading') banner(st.status.msg, false);
    else banner('');
    document.title = p == null ? 'NQ Scalp Terminal' : `${fmt(p, 2)} · NQ Scalp`;
    if (S.tab === 'fp') Panels.footprint(S.fp, st.tape, S.tf);
    $('#bigstrip').innerHTML = st.bigs.length ? st.bigs.map(b => `<span class="bp ${b.s > 0 ? 'pos' : 'neg'}">${U.hm(b.t / 1000, S.tz).slice(0, 8)} ${b.s > 0 ? '▲' : '▼'} ${b.q} @ ${fmt(b.p, 2)}</span>`).join('') : '<span class="muted">aucun pour l\'instant</span>';
  }

  async function pollBars() {
    const since = NQChart.lastTime();
    const q = `/api/bars?tf=${S.tf}&limit=600` + (since && S.barsTf === S.tf ? `&since=${since * 1000}` : '');
    const p = await api(q);
    if (!p.bars.length) return;
    NQChart.apply(p, p.full);
    S.barsTf = S.tf;
  }

  async function pollProfile() {
    if (S.vp === 'off') { NQChart.setProfile(null); return; }
    NQChart.setProfile(await api('/api/profile?which=' + S.vp));
  }

  async function pollLevels() {
    const lv = await api('/api/levels');
    S.lv = lv;
    NQChart.setLevels(lv.levels, S.lvl); NQChart.setZones(lv.zones);
    if (S.price != null) Panels.levels(lv, S.price);
  }

  async function pollContext() {
    Panels.lecture(await api('/api/context' + (S.pos ? '?pos=' + encodeURIComponent(S.pos) : '')), S.state);
  }

  async function pollAccount() {
    const [a, perf] = await Promise.all([api('/api/account' + (S.pos ? '?pos=' + encodeURIComponent(S.pos) : '')), api('/api/account/perf')]);
    S.acct = a;
    Panels.account(a, perf);
    const chip = $('#acctChip');
    const kind = {ok: 'ok', warn: 'warn', danger: 'bad', breached: 'bad', passed: 'ok'}[a.status] || '';
    chip.className = 'badge ' + kind;
    chip.textContent = a.status === 'breached' ? 'Lucid · PLANCHER ATTEINT' : a.status === 'passed' ? 'Lucid · VALIDÉ' : `Lucid · marge ${usd(a.buffer)} · jour ${susd(a.dayPnl)}`;
  }

  async function pollFp() {
    if (S.tab !== 'fp') return;
    S.fp = await api(`/api/footprint?tf=${S.tf === '1m' ? '1m' : S.tf}&n=2`);
    Panels.footprint(S.fp, S.state ? S.state.tape : [], S.tf);
  }

  async function pollSignals() {
    if (S.tab !== 'setups') return;
    Panels.setups(await api(`/api/signals?tf=${S.tf}` + (S.pos ? '&pos=' + encodeURIComponent(S.pos) : '')));
  }

  // ---------- interface ----------
  function legend(r, hover) {
    const el = $('#legend');
    if (!r) { el.innerHTML = ''; return; }
    const up = r.c >= r.o ? 'pos' : 'neg';
    el.innerHTML = `<b>${hover ? U.hm(r.t, S.tz).slice(0, 5) : 'dernière'}</b> O <b>${fmt(r.o, 2)}</b> H <b>${fmt(r.h, 2)}</b> L <b>${fmt(r.l, 2)}</b> C <b class="${up}">${fmt(r.c, 2)}</b>`
      + ` · Δ <b class="${U.cls(r.d)}">${sign(r.d, 0)}</b> · vol <b>${fmt(r.v, 0)}</b>` + (r.vr && r.vr.v != null ? ` · VWAP <b style="color:var(--vw)">${fmt(r.vr.v, 2)}</b>` : '');
  }

  function seg(id, key, onSet) {
    const box = $(id);
    const paint = () => $$('button', box).forEach(b => b.classList.toggle('on', b.dataset.m === String(S[key])));
    $$('button', box).forEach(b => b.onclick = () => { S[key] = b.dataset.m; store.set(key, S[key]); paint(); onSet(S[key]); });
    paint();
  }

  function showTab(name) {
    S.tab = name; store.set('tab', name);
    $$('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
    $$('.tabpage').forEach(p => { p.hidden = p.id !== 'tab-' + name; });
    if (name === 'fp') pollFp().catch(() => {});
    if (name === 'setups') pollSignals().catch(() => {});
  }

  async function start() {
    let cfg;
    try { cfg = await api('/api/config'); } catch (e) { banner(e.message, true); setTimeout(start, 2000); return; }
    U.setToken(cfg.token); S.boot = cfg.boot;
    if (!store.get('tzInit', false)) { S.tz = cfg.displayTz || S.tz; store.set('tzInit', true); }
    // unites de temps
    $('#tfs').innerHTML = cfg.tfs.map(t => `<button data-m="${t}">${t}</button>`).join('');
    seg('#tfs', 'tf', () => { NQChart.apply({step: 60, bars: [], vwapRth: {}, vwapGx: {}, cvdRth: [], cvdGx: []}, true); S.barsTf = null; pollBars().catch(() => {}); pollFp().catch(() => {}); });
    NQChart.init($('#price-chart'), $('#cvd-chart'), $('#overlay'));
    NQChart.onLegend(legend);
    NQChart.setTheme(S.theme); NQChart.setTz(S.tz); NQChart.setCvdScope(S.cvd); NQChart.setVpMode(S.vp);
    NQChart.setOptions({zones: S.zones, bigs: S.bigs, abs: S.abs});
    seg('#lvlMode', 'lvl', v => { NQChart.setLevels(S.lv ? S.lv.levels : [], v); });
    seg('#vpMode', 'vp', v => { NQChart.setVpMode(v); pollProfile().catch(() => {}); });
    seg('#cvdMode', 'cvd', v => NQChart.setCvdScope(v));
    seg('#tzMode', 'tz', v => { NQChart.setTz(v); });
    for (const [id, key] of [['#optZones', 'zones'], ['#optBigs', 'bigs'], ['#optAbs', 'abs']]) {
      const cb = $(id); cb.checked = !!S[key];
      cb.onchange = () => { S[key] = cb.checked; store.set(key, cb.checked); NQChart.setOptions({[key]: cb.checked}); };
    }
    const theme = () => { $('#themeBtn').textContent = S.theme === 'nuit' ? '☾ nuit' : '☀ classique'; };
    theme();
    $('#themeBtn').onclick = () => { S.theme = S.theme === 'nuit' ? 'classic' : 'nuit'; store.set('theme', S.theme); NQChart.setTheme(S.theme); theme(); };
    $$('#tabs button').forEach(b => b.onclick = () => showTab(b.dataset.tab));
    $('#acctChip').onclick = () => showTab('account');

    Panels.init({getLast, getPos, setPos, tz: tzNow, showTab, tfs: () => (cfg.tfs || ['1m']),
      refreshAccount: () => pollAccount().catch(e => U.toast(e.message, true))});
    showTab(S.tab);
    every(pollState, 1000, 'state');
    every(pollBars, 1000, 'bars');
    every(pollProfile, 3000, 'profile');
    every(pollLevels, 5000, 'levels');
    every(pollContext, 4000, 'context');
    every(pollAccount, 3000, 'account');
    every(pollSignals, 2500, 'signals');
    every(pollFp, 2000, 'fp');
  }

  start();
})();
