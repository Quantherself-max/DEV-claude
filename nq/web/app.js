// Démarrage, vues (onglets de graphiques), menu d'indicateurs, tiroir « Outils » et rafraîchissements. Chaque lecture est protégée contre le
// chevauchement (une requête lente n'en empile pas d'autres) et la page signale clairement quand le terminal ne répond plus.
(() => {
  'use strict';
  const {$, $$, api, fmt, sign, usd, susd, esc, store} = U;

  // ---------- vues : chaque onglet garde SON unité de temps et SES indicateurs ----------
  const DEFAULT_VIEW = {name: 'Vue 1', tf: '1m', profiles: ['rth'], vwapS: true, bands: true, vwapG: true, vwapW: true, vwapM: false,
    lvlMode: 'key', groups: {veille: true, nuit: true, seance: true, profil: true, gex: true, rond: false}, zones: false, singles: true,
    abs: 'top', delta: false, bigs: false, cvdMode: 'line', deltaHist: true, cvdScope: 'gx', gexBars: true};
  const PROFILES = [['rth', 'Séance (9 h 30 – 16 h)'], ['gx', 'Globex (24 h)'], ['prev', 'Veille (séance)'], ['week', 'Semaine'], ['pweek', 'Semaine précédente'],
    ['month', 'Mois'], ['pmonth', 'Mois précédent']];
  const norm = v => Object.assign({}, DEFAULT_VIEW, v || {}, {groups: Object.assign({}, DEFAULT_VIEW.groups, (v || {}).groups || {})});
  let views = (store.get('views', null) || []).map(norm);
  if (!views.length) views = [norm({id: 1}), norm({id: 2, name: 'Vue 2', tf: '5m', profiles: ['rth', 'week'], delta: false})];
  views.forEach((v, i) => { v.id = v.id || i + 1; });

  const S = {theme: store.get('theme', 'nuit'), tz: store.get('tz', 'paris'), tab: store.get('tab', 'lecture'), drawer: store.get('drawer', false),
    view: store.get('view', views[0].id), pos: store.get('pos', ''), boot: null, state: null, price: null, acct: null, lv: null, gex: null, fails: 0, barsKey: null};
  if (!views.some(v => v.id === S.view)) S.view = views[0].id;
  const V = () => views.find(v => v.id === S.view) || views[0];
  const saveViews = () => store.set('views', views);

  const getLast = () => S.price;
  const getPos = () => S.pos;
  const setPos = v => { S.pos = v || ''; store.set('pos', S.pos); };
  const tzNow = () => S.tz;

  // ---------- lectures périodiques ----------
  function every(fn, ms, name) {
    let busy = false;
    const run = async () => {
      if (busy || (document.hidden && !(name === 'signals' && store.get('alerts', false)))) return;    // page cachée : seules les alertes continuent
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
    if (S.boot && st.boot !== S.boot) { location.reload(); return; }        // le terminal a redémarré (nouvelle version) : on recharge la page
    S.boot = st.boot; S.state = st;
    const prev = S.price, p = st.last ? st.last.p : null;
    S.price = p;
    const pe = $('#price');
    pe.textContent = p == null ? '—' : fmt(p, 2);
    if (prev != null && p != null && p !== prev) { pe.className = p > prev ? 'up' : 'dn'; }
    $('#contract').textContent = st.contract.code;
    $('#roll').textContent = st.contract.rollSoon ? `roll → ${st.contract.next} dans ${Math.max(0, Math.round(st.contract.rollInDays))} j` : '';
    $('#clkParis').textContent = st.clock.paris; $('#clkEt').textContent = st.clock.et;
    $('#phase').textContent = st.clock.phase.label;
    const m = st.clock.marks[0];
    $('#nextMark').textContent = m ? `${m.label} dans ${m.in} min (${m.paris})` : '';
    const sb = $('#srcBadge');
    if (st.source.simulated) { sb.textContent = 'DONNÉES SIMULÉES'; sb.className = 'badge sim'; sb.title = 'Prix fictifs. Pour les vraies données : NinjaTrader + NQTickLogger (Outils → Source)'; }
    else {
      const est = st.deltaReal != null && st.deltaReal < 0.8;
      sb.textContent = (st.source.label || 'Source') + (st.source.auto ? ' · NinjaTrader' : '') + (est ? ' · delta estimé' : ''); sb.className = 'badge ' + (est ? 'warn' : 'ok');
      sb.title = est ? 'Le côté de l\'agresseur n\'est pas fourni : delta et CVD sont estimés par la règle du tick' : 'Vraies transactions, côté de l\'agresseur fourni : delta et CVD réels';
    }
    const oi = st.oi, oc = $('#oiChip');
    if (oi) { oc.textContent = `OI ${fmt(oi.oi, 0)}` + (oi.change != null ? ` (${sign(oi.change, 0)})` : ''); oc.className = 'badge ' + (oi.change > 0 ? 'ok' : oi.change < 0 ? 'bad' : ''); }
    else { oc.textContent = 'OI —'; oc.className = 'badge'; }
    if (st.status.state === 'error') banner(st.status.msg, true);
    else if (st.status.state === 'empty') banner(st.status.msg + ' Vérifie la source (Outils → Source).', false);
    else if (st.status.state === 'loading') banner(st.status.msg, false);
    else banner('');
    document.title = p == null ? 'NQ Scalp Terminal' : `${fmt(p, 2)} · NQ Scalp`;
    if (S.tab === 'fp' && S.drawer) Panels.footprint(S.fp, st.tape, V().tf);
  }

  async function pollBars() {
    const tf = V().tf, key = S.view + '|' + tf;
    const since = S.barsKey === key ? NQChart.lastTime() : null;
    const p = await api(`/api/bars?tf=${tf}&limit=600` + (since ? `&since=${since * 1000}` : ''));
    if (V().tf !== tf || S.view + '|' + tf !== key) return;                  // la vue a changé pendant la requête
    if (!p.bars.length) return;
    NQChart.apply(p, p.full);
    S.barsKey = key;
  }

  async function pollProfile() {
    const keys = V().profiles || [];
    const data = await Promise.all(keys.map(k => api('/api/profile?which=' + k).catch(() => null)));
    NQChart.setProfiles(keys.map((k, i) => ({key: k, data: data[i]})));
  }

  async function pollLevels() {
    const lv = await api('/api/levels');
    S.lv = lv;
    NQChart.setLevels(lv.levels); NQChart.setZones(lv.zones); NQChart.setSingles(lv.singles);
    if (S.price != null && S.drawer && S.tab === 'levels') Panels.levels(lv, S.price, NQChart.absZones());
  }

  async function pollGex() {
    const g = await api('/api/gex');
    S.gex = g;
    NQChart.setGex(g.state === 'ready' ? g : null);
    const c = $('#gexChip');
    if (g.state === 'ready') {
      const z = (g.levels || []).find(x => x.kind === 'gzero');
      c.textContent = `GEX ${g.regime === 'positif' ? '+' : '−'}` + (z ? ` · HVL ${fmt(z.price, 0)}` : '');
      c.className = 'badge ' + (g.regime === 'positif' ? 'ok' : 'warn');
    } else { c.textContent = g.state === 'off' ? 'GEX off' : 'GEX …'; c.className = 'badge' + (g.state === 'error' ? ' bad' : ''); }
    if (S.drawer && S.tab === 'gex') Panels.gex(g, S.state ? S.state.oi : null);
  }

  async function pollContext() {
    if (!(S.drawer && S.tab === 'lecture')) return;
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
    if (!(S.drawer && S.tab === 'fp')) return;
    S.fp = await api(`/api/footprint?tf=${V().tf}&n=2`);
    Panels.footprint(S.fp, S.state ? S.state.tape : [], V().tf);
  }

  async function pollSource() {
    if (!(S.drawer && S.tab === 'source')) return;
    Panels.source(await api('/api/source'));
  }

  // les setups sont lus aussi onglet fermé si les alertes ou le tracé sur le graphique sont actifs
  const setupOpts = () => ({lines: store.get('setupLines', true), alerts: store.get('alerts', false), min: Number(store.get('alertMin', 55)) || 0});
  async function pollSignals() {
    const o = setupOpts(), open = S.drawer && S.tab === 'setups';
    if (!open && !o.lines && !o.alerts) { NQChart.setSetup(null); return; }
    const d = await api(`/api/signals?tf=${V().tf}` + (S.pos ? '&pos=' + encodeURIComponent(S.pos) : ''));
    if (open) Panels.setups(d);
    const top = d && d.ready && d.setups && d.setups.length && !d.setups[0].suppressed ? d.setups[0] : null;
    NQChart.setSetup(o.lines ? top : null);
    trackSetup(top, o.min);
    if (o.alerts && top && top.score >= o.min) alertSetup(top, d.tf);
  }

  // ---------- alertes ----------
  const lastAlert = {long: {k: '', t: 0, on: false}, short: {k: '', t: 0, on: false}};
  let audio = null;
  function beep(up) {
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      const t0 = audio.currentTime;
      (up ? [660, 990] : [990, 660]).forEach((f, i) => {
        const o = audio.createOscillator(), g = audio.createGain();
        o.frequency.value = f; o.type = 'sine';
        g.gain.setValueAtTime(0.0001, t0 + i * 0.16); g.gain.exponentialRampToValueAtTime(0.2, t0 + i * 0.16 + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + i * 0.16 + 0.14);
        o.connect(g).connect(audio.destination); o.start(t0 + i * 0.16); o.stop(t0 + i * 0.16 + 0.15);
      });
    } catch (e) { /* audio indisponible */ }
  }
  function trackSetup(top, min) {
    for (const side of ['long', 'short']) if (!top || top.side !== side || top.score < min) lastAlert[side].on = false;
  }
  function alertSetup(s, tf) {
    const la = lastAlert[s.side], now = Date.now(), k = s.kind;
    const fresh = !la.on || la.k !== k;
    la.on = true;
    if (!fresh || now - la.t < 60_000) { la.k = k; return; }
    Object.assign(la, {k, t: now});
    const msg = `${s.side === 'long' ? 'ACHAT' : 'VENTE'} ${s.kind === 'momentum' ? 'momentum' : 'retournement'} · score ${Math.round(s.score)} · entrée ${fmt(s.entry, 2)} · stop ${fmt(s.stop, 2)} (${tf || V().tf})`;
    beep(s.side === 'long');
    U.toast('Setup : ' + msg);
    try { if ('Notification' in window && Notification.permission === 'granted') new Notification('NQ Scalp · setup', {body: msg, tag: 'nq-setup-' + s.side}); } catch (e) { /* ignore */ }
  }

  // ---------- interface ----------
  function legend(r, hover) {
    const el = $('#legend');
    if (!r) { el.innerHTML = ''; return; }
    const up = r.c >= r.o ? 'pos' : 'neg';
    const cv = V().cvdScope === 'rth' ? r.cr : r.cg;
    el.innerHTML = `<b>${hover ? U.hm(r.t, S.tz).slice(0, 5) : 'dernière'}</b> O <b>${fmt(r.o, 2)}</b> H <b>${fmt(r.h, 2)}</b> L <b>${fmt(r.l, 2)}</b> C <b class="${up}">${fmt(r.c, 2)}</b>`
      + ` · Δ <b class="${U.cls(r.d)}">${sign(r.d, 0)}</b>` + (cv != null ? ` · CVD <b class="${U.cls(cv)}">${fmt(cv, 0)}</b>` : '') + ` · vol <b>${fmt(r.v, 0)}</b>`
      + (r.vr && r.vr.v != null ? ` · VWAP <b style="color:var(--vw)">${fmt(r.vr.v, 2)}</b>` : '');
  }

  function chartOpts(v) {
    return {vwapS: v.vwapS, bands: v.bands, vwapG: v.vwapG, vwapW: v.vwapW, vwapM: v.vwapM, lvlMode: v.lvlMode, groups: v.groups, zones: v.zones,
      singles: v.singles, abs: v.abs, delta: v.delta, bigs: v.bigs, cvdMode: v.cvdMode, deltaHist: v.deltaHist, cvdScope: v.cvdScope, gexBars: v.gexBars};
  }

  function renderViews() {
    $('#views').innerHTML = views.map(v => `<button class="vtab${v.id === S.view ? ' on' : ''}" data-id="${v.id}" title="Double-clic : renommer">`
      + `${esc(v.name)} <small>${esc(v.tf)}</small>${views.length > 1 ? `<span class="vx" data-x="${v.id}" title="Fermer cette vue">✕</span>` : ''}</button>`).join('');
    $$('#views .vtab').forEach(b => {
      b.onclick = e => {
        const x = e.target.closest('[data-x]');
        if (x) { closeView(Number(x.dataset.x)); return; }
        switchView(Number(b.dataset.id));
      };
      b.ondblclick = () => {
        const v = views.find(x => x.id === Number(b.dataset.id));
        const n = prompt('Nom de la vue', v.name);
        if (n && n.trim()) { v.name = n.trim().slice(0, 24); saveViews(); renderViews(); }
      };
    });
    $$('#tfs button').forEach(b => b.classList.toggle('on', b.dataset.m === V().tf));
  }

  function switchView(id) {
    if (id === S.view && S.barsKey) return;
    S.view = id; store.set('view', id);
    applyView(true);
  }

  function applyView(reload) {
    const v = V();
    NQChart.setOptions(chartOpts(v));
    renderViews();
    if (S.lv) NQChart.setLevels(S.lv.levels);
    if (reload) {
      NQChart.reset(); S.barsKey = null;
      pollBars().catch(() => {}); pollProfile().catch(() => {}); pollFp().catch(() => {});
    }
    if (!$('#indPanel').hidden) buildIndicators();
    Minis.refresh();
  }

  function closeView(id) {
    if (views.length < 2) return;
    views = views.filter(v => v.id !== id); saveViews();
    if (S.view === id) { S.view = views[0].id; store.set('view', S.view); applyView(true); } else renderViews();
  }

  function addView() {
    const cur = V(), id = Math.max(...views.map(v => v.id)) + 1;
    views.push(Object.assign(JSON.parse(JSON.stringify(cur)), {id, name: 'Vue ' + id}));
    saveViews(); switchView(id);
  }

  // ---------- menu d'indicateurs : sections, recherche, défilement ----------
  function setView(patch, opts = {}) {
    const v = V();
    Object.assign(v, patch);
    saveViews();
    NQChart.setOptions(chartOpts(v));
    if (opts.profiles) { NQChart.setProfiles([]); pollProfile().catch(() => {}); }
    if (opts.reload) applyView(true);
    if (opts.levels && S.lv) NQChart.setLevels(S.lv.levels);
    Minis.refresh();
    buildIndicators();
  }

  function buildIndicators() {
    const v = V(), f = ($('#indFilter').value || '').trim().toLowerCase();
    const chk = (label, on, act, extra = '') => ({label, html: `<label class="irow" data-act="${act}"><input type="checkbox"${on ? ' checked' : ''}>${extra}<span>${label}</span></label>`});
    const seg = (label, cur, act, opts) => ({label, html: `<div class="small">${label}</div><div class="iseg" data-seg="${act}">`
      + opts.map(([k, t]) => `<button data-v="${k}" class="${cur === k ? 'on' : ''}">${t}</button>`).join('') + '</div>'});
    const sections = [
      ['Profils de volume · superposables', PROFILES.map(([k, t]) => chk(t, v.profiles.includes(k), 'p:' + k, `<span class="sw" style="background:${NQChart.colors[k]}"></span>`))
        .concat([{label: 'aide profils', html: '<div class="small">Plusieurs profils cochés se superposent, chacun dans sa couleur (zone de valeur plus marquée, POC en tirets). Un seul : acheteurs / vendeurs séparés.</div>'}])],
      ['VWAP', [chk('VWAP de séance', v.vwapS, 'b:vwapS'), chk('Bandes ±1σ / ±2σ (séance)', v.bands, 'b:bands'), chk('VWAP Globex (24 h)', v.vwapG, 'b:vwapG'),
        chk('VWAP de la semaine ±1σ', v.vwapW, 'b:vwapW'), chk('VWAP du mois ±1σ', v.vwapM, 'b:vwapM')]],
      ['Niveaux', [seg('Lignes de niveaux', v.lvlMode, 'lvlMode', [['off', 'Aucune'], ['key', 'Clés'], ['all', 'Toutes']]),
        chk('Veille (H, L, clôture, POC, VAH, VAL)', v.groups.veille, 'g:veille'), chk('Nuit, Asie, Londres', v.groups.nuit, 'g:nuit'),
        chk('Séance (ouverture, IB, POC / VA en formation)', v.groups.seance, 'g:seance'), chk('Structure (semaine, mois, POC vierges, single prints)', v.groups.profil, 'g:profil'),
        chk('GEX (call wall, put wall, zéro gamma, strikes)', v.groups.gex, 'g:gex'), chk('Nombres ronds', v.groups.rond, 'g:rond'),
        chk('Zones de confluence (bandes bleues)', v.zones, 'b:zones'), chk('Single prints et queues (bandes)', v.singles, 'b:singles')]],
      ['Order flow', [seg('Absorptions (ABS sous / sur les bougies)', v.abs, 'abs', [['top', 'Les meilleures'], ['all', 'Toutes'], ['off', 'Aucune']]),
        {label: 'aide abs', html: '<div class="small">« Les meilleures » : fortes, répétées au même prix (×2), testées, ou faites sur un niveau clé (★).</div>'},
        chk('Delta chiffré sous les bougies (zoomer)', v.delta, 'b:delta'), chk('Gros ordres (bulles)', v.bigs, 'b:bigs')]],
      ['Panneau du bas (CVD et delta)', [seg('CVD', v.cvdMode, 'cvdMode', [['line', 'Ligne'], ['candles', 'Bougies']]),
        seg('Remise à zéro du CVD', v.cvdScope, 'cvdScope', [['gx', 'Globex (18 h ET)'], ['rth', 'Séance (9 h 30)']]),
        chk('Delta par barre (histogramme)', v.deltaHist, 'b:deltaHist')]],
      ['Options (GEX)', [chk('Profil GEX par strike (barres à gauche)', v.gexBars, 'b:gexBars'),
        {label: 'actualiser gex', html: '<button class="irow" data-gexrefresh style="width:100%;justify-content:center">Actualiser les données d\'options</button>'}]],
      ['Affichage (toutes les vues)', [seg('Heures', S.tz, 'tz', [['paris', 'Paris'], ['et', 'New York']]),
        seg('Bougies', S.theme, 'theme', [['nuit', 'Nuit (bleu / blanc)'], ['classic', 'Classique (vert / rouge)']])]],
    ];
    $('#indBody').innerHTML = sections.map(([title, items]) => {
      const vis = items.filter(it => !f || (title + ' ' + it.label).toLowerCase().includes(f));
      return vis.length ? `<div class="isec"><h3>${esc(title)}</h3>${vis.map(it => it.html).join('')}</div>` : '';
    }).join('') || '<div class="small" style="padding:10px 0">Aucun indicateur ne correspond.</div>';
    $$('#indBody [data-act]').forEach(el => el.querySelector('input').onchange = e => {
      const [kind, key] = el.dataset.act.split(':'), on = e.target.checked;
      if (kind === 'p') {
        const ps = V().profiles.filter(x => x !== key);
        if (on) ps.push(key);
        setView({profiles: PROFILES.map(p => p[0]).filter(k => ps.includes(k))}, {profiles: true});
      } else if (kind === 'g') setView({groups: Object.assign({}, V().groups, {[key]: on})}, {levels: true});
      else setView({[key]: on});
    });
    $$('#indBody [data-seg]').forEach(box => $$('button', box).forEach(b => b.onclick = () => {
      const key = box.dataset.seg, val = b.dataset.v;
      if (key === 'tz') { S.tz = val; store.set('tz', val); NQChart.setTz(val); buildIndicators(); return; }
      if (key === 'theme') { S.theme = val; store.set('theme', val); NQChart.setTheme(val); Minis.setTheme(val); buildIndicators(); return; }
      setView({[key]: val}, {levels: key === 'lvlMode'});
    }));
    const gr = $('#indBody [data-gexrefresh]');
    if (gr) gr.onclick = async () => { try { await api('/api/gex/refresh', {body: {}}); U.toast('Données d\'options demandées : quelques secondes.'); setTimeout(() => pollGex().catch(() => {}), 6000); } catch (e) { U.toast(e.message, true); } };
  }

  function toggleIndicators(force) {
    const p = $('#indPanel'), b = $('#indBtn');
    const open = force != null ? force : p.hidden;
    p.hidden = !open; b.classList.toggle('on', open);
    if (open) {
      const r = b.getBoundingClientRect();
      p.style.top = (r.bottom + 6) + 'px';
      p.style.left = Math.max(8, Math.min(window.innerWidth - 350, r.right - 340)) + 'px';
      buildIndicators(); $('#indFilter').focus();
    }
  }

  // ---------- tiroir « Outils » ----------
  function setDrawer(open) {
    S.drawer = open; store.set('drawer', open);
    $('#side').hidden = !open; $('main').classList.toggle('drawer', open); $('#drawerBtn').classList.toggle('on', open);
    if (open) refreshTab();
  }
  function showTab(name) {
    S.tab = name; store.set('tab', name);
    $$('#tabs button[data-tab]').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
    $$('.tabpage').forEach(p => { p.hidden = p.id !== 'tab-' + name; });
    if (!S.drawer) setDrawer(true); else refreshTab();
  }
  function refreshTab() {
    const t = S.tab;
    if (t === 'fp') pollFp().catch(() => {});
    if (t === 'setups') pollSignals().catch(() => {});
    if (t === 'lecture') pollContext().catch(() => {});
    if (t === 'levels' && S.lv && S.price != null) Panels.levels(S.lv, S.price, NQChart.absZones());
    if (t === 'gex') pollGex().catch(() => {});
    if (t === 'source') pollSource().catch(() => {});
  }

  async function start() {
    let cfg;
    try { cfg = await api('/api/config'); } catch (e) { banner(e.message, true); setTimeout(start, 2000); return; }
    U.setToken(cfg.token); S.boot = cfg.boot;
    if (!store.get('tzInit', false)) { S.tz = cfg.displayTz || S.tz; store.set('tzInit', true); }
    views.forEach(v => { if (!cfg.tfs.includes(v.tf)) v.tf = '1m'; });
    $('#tfs').innerHTML = cfg.tfs.map(t => `<button data-m="${t}">${t}</button>`).join('');
    $$('#tfs button').forEach(b => b.onclick = () => { V().tf = b.dataset.m; saveViews(); applyView(true); });
    NQChart.init($('#price-chart'), $('#cvd-chart'), $('#overlay'));
    NQChart.onLegend(legend);
    NQChart.setTheme(S.theme); NQChart.setTz(S.tz);
    Minis.init($('#multi'), {tfs: () => cfg.tfs || ['1m'], tz: tzNow, theme: () => S.theme, opts: () => ({vwapW: V().vwapW, abs: V().abs !== 'off'}),
      levels: () => (S.lv ? S.lv.levels : [])});
    $('#addChart').onclick = () => Minis.add();
    $('#addView').onclick = addView;
    $('#indBtn').onclick = () => toggleIndicators();
    $('#indClose').onclick = () => toggleIndicators(false);
    $('#indFilter').oninput = () => buildIndicators();
    document.addEventListener('keydown', e => { if (e.key === 'Escape') toggleIndicators(false); });
    document.addEventListener('mousedown', e => { if (!$('#indPanel').hidden && !e.target.closest('#indPanel') && !e.target.closest('#indBtn')) toggleIndicators(false); });
    $('#drawerBtn').onclick = () => setDrawer(!S.drawer);
    $('#drawerClose').onclick = () => setDrawer(false);
    $$('#tabs button[data-tab]').forEach(b => b.onclick = () => showTab(b.dataset.tab));
    $('#acctChip').onclick = () => showTab('account');
    $('#oiChip').onclick = () => showTab('gex');
    $('#gexChip').onclick = () => showTab('gex');
    $('#srcBadge').onclick = () => showTab('source');

    Panels.init({getLast, getPos, setPos, tz: tzNow, showTab, tfs: () => (cfg.tfs || ['1m']), onSetupOpts: () => pollSignals().catch(() => {}),
      refreshAccount: () => pollAccount().catch(e => U.toast(e.message, true)), refreshSource: () => pollSource().catch(() => {})});
    $$('#tabs button[data-tab]').forEach(b => b.classList.toggle('on', b.dataset.tab === S.tab));
    $$('.tabpage').forEach(p => { p.hidden = p.id !== 'tab-' + S.tab; });
    setDrawer(S.drawer);
    applyView(false);
    every(pollState, 1000, 'state');
    every(pollBars, 1000, 'bars');
    every(pollProfile, 3000, 'profile');
    every(pollLevels, 5000, 'levels');
    every(pollGex, 30000, 'gex');
    every(pollContext, 4000, 'context');
    every(pollAccount, 3000, 'account');
    every(pollSignals, 2500, 'signals');
    every(pollFp, 2000, 'fp');
    every(pollSource, 3000, 'source');
  }

  start();
})();
