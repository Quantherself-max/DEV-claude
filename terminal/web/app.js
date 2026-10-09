(() => {
'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtP = p => p >= 1000 ? Math.round(p).toLocaleString('fr-FR') : p.toFixed(2).replace('.', ',');
const fmtPct = v => (v > 0 ? '+' : '') + v.toFixed(2).replace('.', ',') + ' %';
const UP = '#3ddc97', DN = '#ff6b6b', AMB = '#ffb300';
const num = (v, d = 2) => v == null ? '-' : v.toFixed(d).replace('.', ',');
const sPct = (v, d = 2) => v == null ? '-' : (v > 0 ? '+' : '') + num(v, d) + ' %';
const pr = x => x == null ? '-' : x < 0.01 ? '<1 %' : x > 0.99 ? '>99 %' : Math.round(x * 100) + ' %';
// verdict : l'intervalle de confiance a 90 % du taux de rebond est-il entierement au-dessus / en dessous du hasard ?
function edgeOf(s, b) {
  if (!s || !s.n) return null;
  if (s.n < 30) return {cls: 'neu', txt: 'peu de données'};
  if (!b || !b.n) return {cls: 'neu', txt: '-'};
  if (s.lo > b.hi) return {cls: 'pos', txt: 'mieux que le hasard'};
  if (s.hi < b.lo) return {cls: 'neg', txt: 'moins bien que le hasard'};
  return {cls: 'neu', txt: '≈ hasard'};
}
const edgeChip = e => e ? `<span class="edge ${e.cls}">${e.txt}</span>` : '';
function ciBar(s, b) {                                  // echelle 20 % -> 80 %
  if (!s || !s.n) return '<div class="ci"></div>';
  const x = v => Math.max(0, Math.min(100, (v - 0.2) / 0.6 * 100));
  const e = edgeOf(s, b);
  return `<div class="ci ${e ? e.cls : ''}" title="rebond ${pr(s.p)} · intervalle 90 % : ${pr(s.lo)} – ${pr(s.hi)} · n=${s.n}">` +
    `<i style="left:${x(s.lo)}%;width:${Math.max(1, x(s.hi) - x(s.lo))}%"></i>` +
    (b && b.n ? `<u style="left:${x(b.p)}%"></u>` : '') + `<b style="left:${x(s.p)}%"></b></div>`;
}
// Biais du terminal (V13.1) : une idée en cours ou de moins de 24 h fixe le sens, toutes paires confondues (BTC et SOL bougent ensemble).
const PARIS_DT = new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
const parisAt = ms => PARIS_DT.format(new Date(ms)).replace(',', '');
function biasHtml(b) {
  if (!b) return '<span class="lt">Biais du terminal</span> <b class="muted">AUCUN</b> <span class="muted small">pas d\'idée en cours ni de moins de 24 h : la prochaine peut être un achat ou une vente</span>';
  const buy = b.side === 'long', sym = s => s.replace('USDT', '');
  const open = b.open.length ? `tant que ${b.open.length > 1 ? 'les idées' : 'l\'idée'} ${b.open.map(o => sym(o.symbol)).join(' et ')} ${b.open.length > 1 ? 'sont' : 'est'} en cours, et ` : '';
  return `<span class="lt">Biais du terminal</span> <b class="${buy ? 'up' : 'dn'}">${buy ? 'ACHAT' : 'VENTE'}</b> <span class="muted small">depuis l'idée ${sym(b.symbol)} du ${parisAt(b.created)} · aucune idée ${buy ? 'de vente' : 'd\'achat'}, sur aucune paire, ${open}pas avant le ${parisAt(b.until)}</span>`;
}
const againstBias = (b, side) => !!b && !!side && b.side !== side;
const usdFmt = v => v >= 1e9 ? (v / 1e9).toFixed(2).replace('.', ',') + ' Md$' : v >= 1e6 ? (v / 1e6).toFixed(1).replace('.', ',') + ' M$' : Math.round(v / 1e3) + ' k$';
const ageFmt = ms => { const h = ms / 3.6e6; return h < 1 ? Math.round(ms / 6e4) + ' min' : h < 48 ? Math.round(h) + ' h' : Math.round(h / 24) + ' j'; };
const timeFr = ms => new Date(ms).toLocaleString('fr-FR', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
const PER = {d:'#FFB300', w:'#4CAF50', m:'#42A5F5', y:'#EC407A'};
const PER_OPEN = {d:'#CE93D8', w:'#9CCC65', m:'#64B5F6', y:'#F06292'};
const PER_VP = {d:'#AB47BC', w:'#66BB6A', m:'#5C9DEB', y:'#EF6C9A'};
const PN = {d:'du jour', w:'de la semaine', m:'du mois', y:"de l'année"};

const periodOf = g => { const m = /^[pP]?([dwmyDWMY])/.exec(g); return m ? m[1].toLowerCase() : 'd'; };
function levelColor(lv) {
  if (lv.kind === 'liq') return lv.pool && lv.pool.side === 'long' ? UP : DN;
  if (lv.kind === 'avwap') return '#E0E0E0';
  if (lv.kind === 'xvp') return '#8FA8FF';
  if (lv.kind === 'hl') return '#D1D4DC';
  if (lv.kind === 'tpo') return /^Poor/.test(lv.name) ? '#FFB300' : '#B8B8B8';
  const p = periodOf(lv.group);
  return lv.kind === 'vwap' ? PER[p] : lv.kind === 'open' ? PER_OPEN[p] : PER_VP[p];
}
function explain(name) {
  let m;
  if (/^Single prints/.test(name)) return 'Single prints (TPO) : prix touchés par une seule tranche de temps de la séance, au milieu du profil. Le prix y est passé vite, sans s\'y arrêter ; zone non comblée depuis. Pas mesurée par le backtest du terminal.';
  if (/^Poor (high|low)/.test(name)) return 'Poor high / poor low (TPO) : le plus haut (ou le plus bas) de la séance a été touché par au moins deux tranches de temps, sans queue : enchère mal terminée, pas encore dépassée. Pas mesuré par le backtest du terminal.';
  if (/^AVWAP/.test(name)) return 'VWAP ancrée à la date indiquée : prix moyen pondéré par le volume depuis cette date.';
  if ((m = /^([dwmy])VWAP$/.exec(name))) return `VWAP ${PN[m[1]]} en cours : prix moyen pondéré par le volume depuis le début de la période (UTC).`;
  if ((m = /^([dwmy])Open$/.exec(name))) return `Prix d'ouverture ${PN[m[1]]} en cours.`;
  if ((m = /^(p?)([dwmy])(POC|VAH|VAL|HVN)$/.exec(name))) {
    const what = {POC:'Point of Control (prix le plus échangé)', VAH:'haut de la Value Area (70 % du volume)', VAL:'bas de la Value Area (70 % du volume)', HVN:'High Volume Node (zone de fort volume)'}[m[3]];
    return `${what} du profil de volume ${m[1] ? 'précédent ' : 'en cours '}${PN[m[2]]}.`;
  }
  if ((m = /^P([DWMY])([HL])$/.exec(name))) return `Plus ${m[2] === 'H' ? 'haut' : 'bas'} ${PN[m[1].toLowerCase()].replace('du', 'du précédent').replace('de la', 'de la précédente').replace("de l'année", "de l'année précédente")} : liquidité classique (stops au-delà).`;
  if (/^VP /.test(name)) return 'Niveau d\'un volume profile que tu as choisi (Détails ▾ → VP) : POC = prix le plus échangé, VAH / VAL = limites de la zone de valeur (70 % du volume), HVN = zone de fort volume.';
  if (/^Liq/.test(name)) return 'Poche de liquidation estimée à partir de l\'Open Interest (proxy).';
  return '';
}

const st = {symbol: null, tf: '1h', data: null, mode: 'ess', pools: true, ppools: true, sel: null, key: null, version: 0, cfg: null, tab: 'lecture', expert: false,
  statSide: 'all', lastBar: 0, lastBarObj: null, heat: null, liqs: null, an: null, series: null, vpd: null, serN: 0, vpFocus: null,
  liqOpts: {hours: 168, pools: true, sweeps: true, real: true, profile: true},
  vpOpts: {vD: true, vW: true, vM: false, vY: false, bands: false, avwap: true, profiles: true, range: false},
  layout: window.innerWidth >= 1500 ? '3' : window.innerWidth >= 1100 ? '2' : '1', prevLayout: null, sideOpen: true, sbCollapsed: false,
  page: 'desk', sub: 'synth', planOn: true, planKey: null, plan: null, planSig: '', sig: null,
  theme: 'nuit', mainOpts: {sess: true, sessW: false, sessM: false, tpoD: true, tpo4: true, tpo1: false, vwap: true, dom: false, big: true}, flow: null,
  mtf: {n: 4, tfs: ['5m', '15m', '1h', '4h', '1d']}, tpoKinds: {D: true, '4h': true, '1h': true}};
async function api(path, body) {
  const opt = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Terminal-Token': st.cfg ? st.cfg.csrf : ''}, body: JSON.stringify(body)};
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
  return j;
}

// ---------- etat partage, aides de dessin, panneaux ----------
const TF_SEC = {'5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400};
function rgba(c, a) { return `rgba(${c[0]},${c[1]},${c[2]},${a})`; }
const COL_L = [61, 220, 151], COL_S = [255, 107, 107];
const byId = (arr, k = 'id') => Object.fromEntries(arr.map(x => [x[k], x]));
const ladderZones = d => {
  const z = byId(d.zones);
  return [...d.ladder.above, ...d.ladder.inside, ...d.ladder.below].map(i => z[i]).filter(Boolean);
};
const essentialZones = d => { const z = byId(d.zones); return (d.ladder.essential || []).map(i => z[i]).filter(Boolean); };
const shownZones = d => st.mode === 'ess' ? essentialZones(d) : ladderZones(d);
const shownPools = (d, all) => {
  const ps = d.liquidity.pools.map((p, i) => ({p, i}));
  if (st.mode !== 'ess' || all) return ps;
  const cnt = {long: 0, short: 0};
  return ps.slice().sort((a, b) => impOf(b.p) - impOf(a.p)).filter(x => cnt[x.p.side]++ < 2);
};
// Importance d'une poche (V14) : taille + confluences autour + fraicheur, sur 100 ; rang de son cote (reference 1 h, la meme quelle que soit l'unite de temps).
const impOf = p => (p && p.imp && p.imp.score) || 0;
const sideWord = p => p.side === 'long' ? 'en dessous' : 'au-dessus';
const rankTag = p => p.rank ? `<b class="${p.rank === 1 ? 'amb' : ''}" title="Rang d'importance parmi les poches ${sideWord(p)} du prix (fenêtre 1 h)">N°${p.rank}</b> · ` : '';
const ageTxt = p => { const h = p.imp && p.imp.ageH; return h == null ? (p.born ? 'formée il y a ' + ageFmt(Date.now() - p.born) : 'plus ancienne que l\'historique') : 'formée il y a ' + ageFmt(h * 3.6e6); };
function impBar(p, c) {
  const i = p.imp; if (!i) return `<div class="bar"><i style="width:${p.score || 0}%;background:${c}"></i></div>`;
  return `<div class="bar stack" title="taille ${num(i.parts.size, 0)}/50 · confluences ${num(i.parts.conf, 0)}/30 · fraîcheur ${num(i.parts.age, 0)}/20"><i style="width:${i.parts.size}%;background:${c}"></i><i style="width:${i.parts.conf}%;background:${AMB}"></i><i style="width:${i.parts.age}%;background:#9fb4ff"></i></div>`;
}
const impLine = p => p.imp ? `importance <b>${p.imp.score}</b>/100 · ${p.imp.nConf ? p.imp.nConf + ' confluence' + (p.imp.nConf > 1 ? 's' : '') : 'aucune confluence'} · ${ageTxt(p)}` : ageTxt(p);
// Etiquettes sans chevauchement : on les repousse verticalement (ecart mini `gap`), puis on les ramene dans le cadre.
function placeLabels(items, gap, top, bottom) {
  items.sort((p, q) => p.y - q.y);
  let prev = top - gap;
  items.forEach(it => { it.ly = Math.max(it.y, prev + gap); prev = it.ly; });
  let next = bottom + gap;
  for (let i = items.length - 1; i >= 0; i--) { items[i].ly = Math.min(items[i].ly, next - gap); next = items[i].ly; }
  prev = top - gap;
  items.forEach(it => { it.ly = Math.max(it.ly, prev + gap); prev = it.ly; });
  return items;
}
// carte de chaleur : image en espace « bandes de prix x heures », peinte par tranches sous le graphique
function buildHeatImage(h) {
  const cv = document.createElement('canvas'); cv.width = h.n; cv.height = h.m;
  const c = cv.getContext('2d'), img = c.createImageData(h.n, h.m);
  for (let j = 0; j < h.m; j++) {
    const row = h.m - 1 - j;
    for (let i = 0; i < h.n; i++) {
      const vl = h.L[j * h.n + i], vs = h.S[j * h.n + i], v = Math.max(vl, vs);
      if (!v) continue;
      const col = vs > vl ? COL_S : COL_L, k = (row * h.n + i) * 4, boost = Math.max(0, (v - 190) / 65);
      img.data[k] = col[0] + (255 - col[0]) * boost * 0.45; img.data[k + 1] = col[1] + (255 - col[1]) * boost * 0.45;
      img.data[k + 2] = col[2] + (255 - col[2]) * boost * 0.45; img.data[k + 3] = Math.min(235, 235 * Math.pow(v / 255, 1.3));
    }
  }
  c.putImageData(img, 0, 0);
  return cv;
}

const panels = [];
const LAYOUTS = {'1': ['main'], liq: ['liq'], vp: ['vp'], '2': ['main', 'liq'], '3': ['main', 'liq', 'vp'], mtf: [], tpo: []};
const needs = k => LAYOUTS[st.layout].includes(k) && st.page === 'desk';
function savePrefs() {
  try { localStorage.setItem('liqPrefs', JSON.stringify({mode: st.mode, pools: st.pools, ppools: st.ppools, liqOpts: st.liqOpts, vpOpts: st.vpOpts, layout: st.layout, side: st.sideOpen, sb: st.sbCollapsed, plan: st.planOn, expert: st.expert, theme: st.theme, mainOpts: st.mainOpts, mtf: st.mtf, tpoKinds: st.tpoKinds})); } catch (e) { /* stockage indisponible */ }
}
function loadPrefs() {
  try {
    const p = JSON.parse(localStorage.getItem('liqPrefs') || '{}');
    if (['ess', 'conf', 'all'].includes(p.mode)) st.mode = p.mode;
    if (typeof p.pools === 'boolean') st.pools = p.pools;
    if (typeof p.ppools === 'boolean') st.ppools = p.ppools;
    Object.assign(st.liqOpts, p.liqOpts || {}); Object.assign(st.vpOpts, p.vpOpts || {});
    if (LAYOUTS[p.layout]) st.layout = p.layout;
    if (typeof p.side === 'boolean') st.sideOpen = p.side;
    if (typeof p.sb === 'boolean') st.sbCollapsed = p.sb;
    if (typeof p.plan === 'boolean') st.planOn = p.plan;
    if (typeof p.expert === 'boolean') st.expert = p.expert;
    if (['nuit', 'classique'].includes(p.theme)) st.theme = p.theme;
    Object.assign(st.mainOpts, p.mainOpts || {});
    if (p.tpoKinds && typeof p.tpoKinds === 'object') ['D', '4h', '1h'].forEach(k => { if (typeof p.tpoKinds[k] === 'boolean') st.tpoKinds[k] = p.tpoKinds[k]; });
    if (p.mtf && Array.isArray(p.mtf.tfs)) st.mtf = {n: Math.max(2, Math.min(5, +p.mtf.n || 4)), tfs: p.mtf.tfs.slice(0, 5)};
  } catch (e) { /* preferences illisibles : valeurs par defaut */ }
}
function syncAllTools() { panels.forEach(p => p.syncTools()); }
const needsSeries = () => needs('vp') || st.tab === 'vp' || (needs('main') && st.mainOpts.vwap);
function refreshAll() { panels.forEach(p => { p.stamp = ''; p.rebuildLines(); }); st.version++; if (needs('liq')) { pollHeat(); pollLiqs(); } if (needsSeries()) pollVP(); }
function syncRange() {
  const first = panels.find(p => p.visible()); if (!first) return;
  const r = first.chart.timeScale().getVisibleLogicalRange(); if (!r) return;
  panels.forEach(p => { if (p !== first && p.visible()) p.chart.timeScale().setVisibleLogicalRange(r); });
}
function applyLayout() {
  const want = LAYOUTS[st.layout];
  $('#desk').className = 'l' + st.layout;
  panels.forEach(p => p.host.classList.toggle('hide', !want.includes(p.kind)));
  const g = $('#mtfGrid');                                              // V16 : grille multi-unites
  if (g) { g.classList.toggle('hide', st.layout !== 'mtf'); if (st.layout === 'mtf' && st.page === 'desk') MTF.show(); else MTF.hide(); }
  const tg = $('#tpoGrid');                                             // V17 : vue TPO
  if (tg) { tg.classList.toggle('hide', st.layout !== 'tpo'); if (st.layout === 'tpo' && st.page === 'desk') TPO.show(); else TPO.hide(); }
  document.querySelectorAll('#layouts button').forEach(b => b.classList.toggle('on', b.dataset.layout === st.layout));
  $('#deskwrap').classList.toggle('noside', !st.sideOpen);
  $('#sideToggle').textContent = st.sideOpen ? 'Panneau ▸' : '◂ Panneau';
  setTimeout(() => { panels.forEach(p => p.visible() && p.resetView()); st.version++; refreshAll(); }, 90);
  savePrefs();
}
function maximize(kind) {
  const solo = kind === 'main' ? '1' : kind;
  if (st.layout === solo) st.layout = st.prevLayout && st.prevLayout !== solo ? st.prevLayout : '3';
  else { st.prevLayout = st.layout; st.layout = solo; }
  applyLayout();
}
function createPanels() {
  const desk = $('#desk');
  ['main', 'liq', 'vp'].forEach(k => { const el = document.createElement('section'); desk.appendChild(el); panels.push(new Panel(el, k)); });
  const g = document.createElement('section'); g.id = 'mtfGrid'; g.className = 'mtf hide'; desk.appendChild(g); MTF.init(window.LT, g);
  const tg = document.createElement('section'); tg.id = 'tpoGrid'; tg.className = 'tpo hide'; desk.appendChild(tg); TPO.init(window.LT, tg);
  let sr = false, sx = false;
  panels.forEach(p => {
    p.chart.timeScale().subscribeVisibleLogicalRangeChange(r => {
      if (sr || !r || !p.visible()) return;
      sr = true; panels.forEach(q => { if (q !== p && q.visible()) q.chart.timeScale().setVisibleLogicalRange(r); }); sr = false;
    });
    p.chart.subscribeCrosshairMove(param => {                      // la croix suit la meme heure dans les autres graphiques
      if (sx || !p.visible()) return;
      sx = true;
      const bar = param.seriesData && param.seriesData.get(p.series);
      panels.forEach(q => {
        if (q === p || !q.visible()) return;
        if (!param.time || !bar) q.chart.clearCrosshairPosition(); else q.chart.setCrosshairPosition(bar.close, param.time, q.series);
      });
      sx = false;
    });
  });
}
// ---------- temps reel : flux des transactions Binance (WebSocket) directement dans le navigateur ----------
// Le prix et la bougie en cours bougent a chaque transaction ; le serveur, lui, recalcule niveaux, poches et
// alertes toutes les 10 s. Si le flux ne passe pas, secours : dernier prix demande au serveur chaque seconde.
const live = {ws: null, sym: null, price: null, t: 0, wsT: 0, src: '', bar: null, barDirty: false, dirty: false,
  retry: 0, retryTimer: null, opened: 0, panelT: 0, polling: false};
const liveFresh = () => live.price != null && live.sym === st.symbol && Date.now() - live.t < 5000;
const livePrice = d => liveFresh() ? live.price : d.price;
function onTick(price, tms, src) {
  if (!(price > 0)) return;
  live.price = price; live.t = Date.now(); live.src = src; live.dirty = true;
  if (live.sym === st.symbol) { MTF.onTick(price, tms); TPO.onTick(price); }
  const d = st.data;
  if (!d || d.symbol !== live.sym || !st.lastBarObj) return;
  const per = TF_SEC[st.tf], bt = Math.floor(tms / 1000 / per) * per;
  if (bt < st.lastBar) return;                                  // transaction plus ancienne que la derniere bougie
  let b = live.bar && live.bar.time === bt ? live.bar : null;
  if (!b) b = st.lastBarObj.time === bt ? {...st.lastBarObj} : {time: bt, open: price, high: price, low: price, close: price};
  b.high = Math.max(b.high, price); b.low = Math.min(b.low, price); b.close = price;
  live.bar = b; live.barDirty = true;
}
function liveStop() {
  clearTimeout(live.retryTimer);
  if (live.ws) { const w = live.ws; live.ws = null; try { w.close(); } catch (e) { /* deja ferme */ } }
}
function liveConnect() {
  liveStop();
  if (live.sym !== st.symbol) { live.price = null; live.bar = null; }    // une reconnexion garde le dernier prix
  live.sym = st.symbol; live.wsT = 0;
  if (!st.cfg || !st.cfg.wsBase || !st.symbol) return;
  let ws;
  try { ws = new WebSocket(`${st.cfg.wsBase}/stream?streams=${st.symbol.toLowerCase()}@aggTrade`); }
  catch (e) { liveRetry(); return; }
  live.ws = ws; live.opened = Date.now();
  ws.onmessage = ev => {
    let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
    const x = m.data || m;
    if (x.e === 'aggTrade' && x.s === live.sym) { live.wsT = Date.now(); live.retry = 0; onTick(+x.p, x.T, 'ws'); }
  };
  ws.onerror = () => { try { ws.close(); } catch (e) { /* rien */ } };
  ws.onclose = () => { if (live.ws === ws) { live.ws = null; liveRetry(); } };
}
function liveRetry() {
  clearTimeout(live.retryTimer);
  const wait = Math.min(30000, 1000 * Math.pow(2, live.retry++));
  live.retryTimer = setTimeout(liveConnect, wait);
}
async function livePoll() {                                     // secours, une fois par seconde
  if (!st.cfg || !st.cfg.wsBase || !st.symbol || live.polling) return;
  // flux ouvert mais muet depuis 15 s : on le relance
  if (live.ws && Date.now() - Math.max(live.wsT, live.opened) > 15000) { live.retry = 0; liveConnect(); }
  if (Date.now() - live.wsT < 2500) return;                     // le flux temps reel fonctionne
  live.polling = true;
  try {
    const sym = st.symbol, r = await (await fetch(`/api/price?symbol=${sym}`)).json();
    if (r.price && sym === st.symbol && Date.now() - live.wsT >= 2500) onTick(r.price, r.t, 'rest');
  } catch (e) { /* le serveur est peut-etre arrete : le statut l'indique deja */ }
  finally { live.polling = false; }
}
function liveBadge() {
  const b = $('#liveBadge');
  if (!st.cfg || !st.cfg.wsBase) { b.hidden = true; return; }
  b.hidden = false;
  const ws = Date.now() - live.wsT < 2500, rest = !ws && liveFresh();
  const txt = ws ? '● TEMPS RÉEL' : rest ? '● PRIX ~1 s' : '● DIFFÉRÉ';
  if (b.textContent !== txt) {
    b.textContent = txt;
    b.className = 'badge ' + (ws ? 'ok' : rest ? 'warn' : '');
    b.title = ws ? 'Prix et bougie en cours mis à jour à chaque transaction (flux Binance).' :
      rest ? 'Le flux temps réel ne passe pas : prix demandé chaque seconde (reconnexion automatique).' :
      'Prix mis à jour avec les niveaux (toutes les ' + st.cfg.refresh + ' s).';
  }
}
function liveRender() {                                          // appele a chaque image
  const d = st.data;
  if (!d || !liveFresh()) return;
  if (live.barDirty && live.bar && live.bar.time >= st.lastBar) {
    panels.forEach(p => p.updateBar(live.bar)); st.lastBar = Math.max(st.lastBar, live.bar.time);
    live.barDirty = false;
  }
  if (live.dirty) {
    const t = fmtP(live.price), lp = $('#ladderPrice');
    if ($('#price').textContent !== t) $('#price').textContent = t;
    if (lp && lp.textContent !== t) lp.textContent = t;
    if (Date.now() - live.panelT > 1000) { live.panelT = Date.now(); live.dirty = false; liveDistances(d); }
  }
}

// ---------- panneaux ----------
function zoneDist(z, d, p) {
  if (z.side === 'in') return 'le prix est dans la zone';
  const edge = z.side === 'above' ? z.lo - p : z.hi - p;
  return fmtPct(edge / p * 100) + ' · ' + num(Math.abs(edge) / d.atr, 1) + ' ATR';
}
function liveDistances(d) {
  const p = livePrice(d), zs = byId(d.zones);
  document.querySelectorAll('#ladder [data-zd]').forEach(el => { const z = zs[el.dataset.zd]; if (z) el.textContent = zoneDist(z, d, p); });
  document.querySelectorAll('#pools [data-pd]').forEach(el => { const q = d.liquidity.pools[+el.dataset.pd]; if (q) el.textContent = fmtPct((q.price / p - 1) * 100); });
  const lp = $('#ladderPrice'); if (lp) lp.textContent = fmtP(p);
}
function probLine(z) {
  const p = z.prob;
  if (!p) return '<span class="prob muted">probabilités : calcul en cours…</span>';
  const parts = [];
  if (z.side !== 'in') parts.push(`<span class="pr">${pr(p.reach['24'])}</span> d'y aller en 24 h`);
  if (p.bounce && p.bounce.n) parts.push(`si touchée : rebond <span class="pr">${pr(p.bounce.p)}</span>${edgeChip(edgeOf(p.bounce, p.base))}`);
  return `<span class="prob">${parts.join(' · ')}</span>`;
}
function zoneRow(z, d) {
  const lv = byId(d.levels);
  const names = z.members.map(i => lv[i]).filter(Boolean).sort((a, b) => a.price - b.price).map(m => m.name);
  const ar = z.side === 'above' ? '<span class="ar up">▲</span>' : z.side === 'below' ? '<span class="ar dn">▼</span>' : '<span class="ar inz">◆</span>';
  const dots = '●'.repeat(Math.min(5, z.score));
  const sel = st.sel && st.sel.type === 'zone' && st.sel.id === z.id ? ' sel' : '';
  const ess = (d.ladder.essential || []).includes(z.id);
  return `<div class="row${z.score < 3 ? ' weak' : ''}${st.mode === 'ess' && !ess ? ' weak' : ''}${sel}" data-zone="${z.id}">${ar}<span class="nm" title="${esc(names.join(' + '))}">${ess ? '<b class="amb" title="Zone essentielle (tracée sur le graphique)">★</b> ' : ''}${esc(names.join(' + '))}</span>` +
    `<span class="pv">${fmtP(z.mid)}</span><span class="sub"><span data-zd="${z.id}">${zoneDist(z, d, livePrice(d))}</span><span class="dots">${dots}</span>${z.hasMagnet ? ' · plus grosse poche' : ''}` +
    probLine(z) + '</span></div>';
}
function renderLadder(d) {
  const zs = byId(d.zones);
  let h = '';
  d.ladder.above.forEach(i => h += zoneRow(zs[i], d));
  d.ladder.inside.forEach(i => h += zoneRow(zs[i], d));
  h += `<div class="pricerow"><span>PRIX</span><span id="ladderPrice">${fmtP(livePrice(d))}</span></div>`;
  d.ladder.below.forEach(i => h += zoneRow(zs[i], d));
  if (!d.zones.length) h = '<div class="muted">Aucune confluence pour l\'instant.</div>' + h;
  $('#ladder').innerHTML = h;
  $('#confHint').textContent = `${d.zones.length} zones · pâle = 2 sources`;
}
function renderPools(d) {
  const q = d.liquidity, pools = q.pools;
  let h = '';
  [...pools].sort((a, b) => b.price - a.price).forEach(p => {
    const i = pools.indexOf(p), dist = (p.price / livePrice(d) - 1) * 100, c = p.side === 'long' ? UP : DN;
    const sel = st.sel && st.sel.type === 'pool' && st.sel.id === i ? ' sel' : '';
    h += `<div class="row${sel}" data-pool="${i}"><span class="ar" style="color:${c}">${p.side === 'long' ? '▼' : '▲'}</span>` +
      `<span class="nm">${rankTag(p)}${p.side === 'long' ? 'longs' : 'shorts'} · ${usdFmt(p.size * p.price)}</span><span class="pv">${fmtP(p.price)}</span>` +
      `<span class="sub"><span data-pd="${i}">${fmtPct(dist)}</span> · ${impLine(p)}${p.reach ? ' · <span class="pr">' + pr(p.reach['24']) + '</span> d\'y aller en 24 h' : ''}${impBar(p, c)}</span></div>`;
  });
  if (!pools.length) h = '<div class="muted">Aucune poche assez forte dans la fenêtre.</div>';
  else h += '<div class="muted" style="font-size:11px;margin-top:4px">Barre : <span style="color:' + UP + '">taille</span> · <span class="amb">confluences</span> · <span style="color:#9fb4ff">fraîcheur</span>. N°1 = la plus importante de son côté (même rang en 15 min, 1 h ou 4 h). Clique une poche pour le détail.</div>';
  const tot = q.sumLong + q.sumShort, up = tot ? q.sumShort / tot * 100 : 50;
  h += `<div class="imb"><i style="width:${up}%;background:${DN}"></i><i style="width:${100 - up}%;background:${UP}"></i></div>` +
    `<div class="muted" style="font-size:11px">au-dessus ${up.toFixed(0)} % · en dessous ${(100 - up).toFixed(0)} % · ${q.total} poches détectées → ${pools.length} retenues</div>`;
  $('#pools').innerHTML = h;
}
function renderPricePools(d) {
  const el = $('#pricePools'); if (!el) return;
  const ps = (d.liquidity.pricePools || []).slice().sort((a, b) => b.price - a.price), px = livePrice(d);
  const all = d.liquidity.pricePools || [];
  el.innerHTML = ps.length ? ps.map(p => {
    const c = p.side === 'long' ? UP : DN, dist = (p.price / px - 1) * 100, k = all.indexOf(p);
    const sel = st.sel && st.sel.type === 'ppool' && st.sel.id === k ? ' sel' : '';
    return `<div class="row${sel}" data-ppool="${k}"><span class="ar" style="color:${c}">${p.side === 'long' ? '▼' : '▲'}</span><span class="nm">${rankTag(p)}${esc(p.src)}</span><span class="pv">${fmtP(p.price)}</span>` +
      `<span class="sub">${fmtPct(dist)} · ${impLine(p)}${impBar(p, c)}</span></div>`;
  }).join('') : '<div class="muted">Aucun plus haut / plus bas notable dans la fenêtre.</div>';
}
function renderPools2(d) {
  const el = $('#pools2'); if (!el) return;
  const ps = d.liquidity.pools.map((p, i) => ({p, i})).sort((a, b) => impOf(b.p) - impOf(a.p) || b.p.size * b.p.price - a.p.size * a.p.price);
  el.innerHTML = ps.length ? ps.map(({p, i}) => {
    const c = p.side === 'long' ? UP : DN, sel = st.sel && st.sel.type === 'pool' && st.sel.id === i ? ' sel' : '';
    return `<div class="row${sel}" data-pool="${i}"><span class="ar" style="color:${c}">${p.side === 'long' ? '▼' : '▲'}</span><span class="nm">${rankTag(p)}${p.side === 'long' ? 'longs' : 'shorts'} · ${usdFmt(p.size * p.price)}</span><span class="pv">${fmtP(p.price)}</span>` +
      `<span class="sub"><span data-pd="${i}">${fmtPct((p.price / livePrice(d) - 1) * 100)}</span> · ${impLine(p)}${p.reach ? ' · <span class="pr">' + pr(p.reach['24']) + '</span> d\'y aller en 24 h' : ''}${impBar(p, c)}</span></div>`;
  }).join('') : '<div class="muted">Aucune poche assez forte dans la fenêtre.</div>';
}
function renderLqLegend() {
  $('#lqLegend').innerHTML = `<div class="lgrow"><span class="lgbar" style="background:linear-gradient(90deg,transparent,#ff6b6b)"></span>Liquidations de <b>shorts</b> estimées (au-dessus du prix)</div>` +
    `<div class="lgrow"><span class="lgbar" style="background:linear-gradient(90deg,transparent,#3ddc97)"></span>Liquidations de <b>longs</b> estimées (sous le prix)</div>` +
    `<div class="lgrow"><span style="display:inline-block;width:12px;height:12px;transform:rotate(45deg);background:#3ddc97;margin:0 29px 0 4px"></span>Poche <b>balayée</b> (taille ~ part du total)</div>` +
    `<div class="lgrow"><span style="display:inline-block;width:14px;height:14px;border-radius:50%;border:2px solid #ff6b6b;background:#ff6b6b55;margin:0 27px 0 3px"></span>Liquidation <b>réelle</b> (Binance, taille ~ montant)</div>` +
    `<div class="note">Une colonne = une heure. Plus c'est lumineux, plus la poche est grosse. Les poches sont estimées à partir de l'Open Interest : elles montrent où les positions récentes seraient liquidées, pas des liquidations connues. Survole la carte pour lire une bande.</div>`;
}
function renderLqReal() {
  const el = $('#real'), r = st.liqs;
  if (!r) { el.textContent = 'Chargement…'; return; }
  if (!r.live) { el.innerHTML = '<div class="muted">Flux temps réel indisponible (mode simulé ou désactivé).</div>'; return; }
  const sm = r.summary || {}, row = (lab, v) => { const t = (v.long + v.short) || 1;
    return `<tr><td>${lab}</td><td class="r up">${usdFmt(v.long)}</td><td class="r dn">${usdFmt(v.short)}</td><td style="width:34%"><div class="imb" style="margin:0"><i style="width:${v.long / t * 100}%;background:${UP}"></i><i style="width:${v.short / t * 100}%;background:${DN}"></i></div></td><td class="r muted">${v.n}</td></tr>`; };
  const feed = r.status && r.status.liqs;
  el.innerHTML = `<table class="t"><tr><th></th><th class="r">Longs</th><th class="r">Shorts</th><th></th><th class="r">n</th></tr>${row('1 h', sm['1h'] || {long: 0, short: 0, n: 0})}${row('4 h', sm['4h'] || {long: 0, short: 0, n: 0})}${row('24 h', sm['24h'] || {long: 0, short: 0, n: 0})}</table>` +
    `<div class="note">Liquidations <b>réelles</b> vues par ton terminal (Binance ne publie que la plus grosse par seconde, et seulement depuis que le terminal tourne). Vert = positions longues liquidées, rouge = positions courtes.</div>` +
    `<div class="sect">Dernières</div>` + (r.events.length ? r.events.slice(-14).reverse().map(e => `<div class="alert"><time>${new Date(e.t).toLocaleTimeString('fr-FR')}</time><span class="${e.side === 'long' ? 'up' : 'dn'}">${e.side === 'long' ? 'long' : 'short'} liquidé</span> ${usdFmt(e.usd)} à ${fmtP(e.price)}</div>`).join('') : '<div class="muted">Aucune liquidation depuis l\'ouverture du terminal.</div>') +
    `<div class="note">Flux : ${feed && feed.connected ? '<span class="up">connecté</span>' : '<span class="dn">déconnecté</span>'}${feed && feed.error ? ' · ' + esc(feed.error) : ''}</div>`;
  $('#realHint').textContent = feed && feed.connected ? 'en direct' : 'hors ligne';
}
function reachBlock(reach, what) {
  if (!reach) return '';
  return `<div class="sect">Chance que le prix ${what}</div><div class="reach">` + ['4', '24', '72'].map(H =>
    `<span class="muted">${H} h</span><div class="bar"><i style="width:${Math.round((reach[H] || 0) * 100)}%;background:${AMB}"></i></div><span class="pr" style="text-align:right">${pr(reach[H])}</span>`).join('') + '</div>';
}
function statLine(s, b, label) {
  if (!s || !s.n) return `<div class="note">${label} : pas assez d'historique.</div>`;
  return `<div class="verdict">${label} : rebond <b>${pr(s.p)}</b> <span class="muted">(${pr(s.lo)}–${pr(s.hi)}, ${s.n} tests)</span>` +
    `${b && b.n ? ` · hasard ${pr(b.p)}` : ''} ${edgeChip(edgeOf(s, b))}</div>`;
}
function defNote() {
  const s = st.data && st.data.stats;
  const k = s && s.ready ? num(s.k, 1) : '1,5', H = s && s.ready ? s.horizon : 24;
  return `<div class="note">Rebond = dans les ${H} h après le contact, le prix s'éloigne de ${k} ATR (1h) du bon côté avant de casser de ${k} ATR. ` +
    `Mesuré sur l'historique de ${esc(st.symbol || '')}. « Hasard » = niveaux tirés au sort : s'il fait pareil, le niveau n'apporte rien.</div>`;
}
// Detail de l'importance (V14) : decomposition, fraicheur, confluences et ce que la mesure sur l'historique en dit.
function impDetail(p, kind) {
  const i = p.imp; if (!i) return `<div class="note">${ageTxt(p)}</div>`;
  const c = p.side === 'long' ? UP : DN, part = (t, v, mx, col, sub) => `<div class="improw"><span>${t}</span><div class="bar"><i style="width:${Math.round(v / mx * 100)}%;background:${col}"></i></div><b>${num(v, 0)}/${mx}</b><small class="muted">${sub}</small></div>`;
  const conf = (i.conf || []).map(x => `<li>${esc(x.what)} <span class="muted">(${esc(x.name)})</span> · ${fmtP(x.price)} <span class="muted">+${num(x.w, 0)}</span></li>`).join('');
  return `<div class="sect">Importance <b>${i.score}/100</b> · ${esc(i.grade)}${p.rank ? ` · <b class="${p.rank === 1 ? 'amb' : ''}">N°${p.rank}</b> ${sideWord(p)} du prix` : ' · hors de la fenêtre 1 h (pas de rang)'}</div>` +
    part('Taille', i.parts.size, 50, c, kind === 'liq' ? 'montant face à la plus grosse poche de la fenêtre 1 h' : 'force du niveau') +
    part('Confluences', i.parts.conf, 30, AMB, i.nConf ? i.nConf + ' niveau' + (i.nConf > 1 ? 'x' : '') + ' d\'autres sources à moins de 0,3 ATR 1 h' : 'aucun niveau d\'une autre source autour') +
    part('Fraîcheur', i.parts.age, 20, '#9fb4ff', ageTxt(p) + (i.maturity ? ' (' + esc(i.maturity) + ')' : '')) +
    (conf ? `<ul class="impconf">${conf}</ul>` : '') +
    `<div class="note"><b>Ce que dit la mesure</b> (BTC 2014-2026, 26 552 premiers contacts de plus hauts / plus bas, page Backtest → rapport « poches ») : au premier contact, une poche se retourne un peu plus souvent qu'un niveau au hasard (+2,8 points contre +0,6), surtout si elle a <b>moins de 24 h</b> ; après 10 jours, plus d'effet mesurable. Les confluences n'ajoutent presque rien au retournement, mais <b>plus il y en a, moins le prix va jusqu'à la poche</b> (il s'arrête avant). Aucune poche n'attire le prix plus que sa distance ne le prévoit.${kind === 'liq' ? ' Les poches estimées par l\'intérêt ouvert (29 jours d\'historique) ne sont pas testables : mêmes règles par prudence.' : ''}</div>`;
}
function renderDetail(d) {
  const el = $('#detail'), s = st.sel;
  if (!s) { el.className = 'muted'; el.textContent = 'Rien de sélectionné.'; return; }
  el.className = '';
  const lv = byId(d.levels);
  const base = d.stats && d.stats.ready ? d.stats.family['Hasard (témoin)'] : null;
  if (s.type === 'zone') {
    const z = byId(d.zones)[s.id]; if (!z) { el.textContent = 'Zone disparue.'; return; }
    const ar = {above: '▲', below: '▼', in: '◆'}[z.side];
    const rows = z.members.map(i => lv[i]).filter(Boolean).sort((a, b) => a.price - b.price).map(m => {
      const f = m.famStat;
      return `<tr title="${esc(explain(m.name))}"><td><span class="chip" style="background:${levelColor(m)}"></span>${esc(m.name)}${m.pool && m.pool.rank ? ' <b>N°' + m.pool.rank + '</b>' : ''}</td>` +
        `<td class="muted small">${f && f.n ? 'rebond ' + pr(f.p) + ' (n=' + f.n + ')' : ''}</td><td>${fmtP(m.price)}</td></tr>`;
    }).join('');
    const where = {above: 'Zone au-dessus du prix (résistance).', below: 'Zone sous le prix (support).', in: 'Le prix est dans la zone.'}[z.side];
    const p = z.prob;
    const bucket = p ? (p.bucket === '3+' ? '3 sources ou plus' : p.bucket + ' sources') : '';
    el.innerHTML = `<div><b>${ar} Confluence ${fmtP(z.mid)}</b> <span class="muted">${z.side === 'in' ? '' : fmtPct(z.distPct) + ' · ' + num(z.distAtr, 1) + ' ATR · '}score ${z.score}</span></div>` +
      `<table class="mem">${rows}</table>` +
      (p ? (z.side !== 'in' ? reachBlock(p.reach, `atteigne la zone (${num(p.distAtrH1, 1)} ATR 1h)`) : '') +
        `<div class="sect">Si le prix touche la zone</div>` + statLine(p.bounce, p.base, `Zones à ${bucket} (${p.side === 'support' ? 'support' : p.side === 'resistance' ? 'résistance' : 'tous'})`) + defNote()
        : '<div class="note">Probabilités : calcul de l\'historique en cours…</div>') +
      `<div class="note">${where} Hypothèse non validée.${z.hasMagnet ? ' Contient la plus grosse poche de liquidation de ce côté.' : ''}</div>`;
  } else if (s.type === 'pool') {
    const p = d.liquidity.pools[s.id]; if (!p) { el.textContent = 'Poche disparue.'; return; }
    const dist = (p.price / d.price - 1) * 100, sw = d.sweeps && d.sweeps.stats;
    el.innerHTML = `<div><b>${p.side === 'long' ? '▼ Liquidations de longs' : '▲ Liquidations de shorts'} ${fmtP(p.price)}</b> ` +
      `<span class="muted">${fmtPct(dist)} · ${num(Math.abs(p.price - d.price) / d.atr, 1)} ATR</span></div>` +
      `<div class="note">Fourchette ${fmtP(p.lo)} – ${fmtP(p.hi)} · ${p.size ? 'taille estimée ≈ <b>' + usdFmt(p.size * p.price) + '</b> de positions' : ''}${p.magnet ? ' · la plus grosse de ce côté dans cette vue' : ''}</div>` +
      impDetail(p, 'liq') +
      reachBlock(p.reach, 'atteigne la poche') +
      `<div class="sect">Après un balayage (journal des 30 derniers jours)</div>` + statLine(sw, base, 'Poches balayées') +
      `<div class="note">Estimation à partir de l'Open Interest : chaque hausse d'OI = nouvelles positions, réparties longs/shorts selon le <b>vrai volume acheteur agressif</b> (taker buy) de la bougie, puis par levier (100x 10 %, 50x 20 %, 25x 30 %, 10x 40 %) ; prix de liquidation = formule isolée + marge 0,4 %. Un niveau disparaît quand le prix le touche ; quand l'OI baisse, tout est réduit d'autant. <b>Proxy, pas de vraies liquidations.</b></div>`;
  } else if (s.type === 'ppool') {
    const p = (d.liquidity.pricePools || [])[s.id]; if (!p) { el.textContent = 'Poche disparue.'; return; }
    el.innerHTML = `<div><b>${p.side === 'long' ? '▼ Ordres d\'arrêt des acheteurs' : '▲ Ordres d\'arrêt des vendeurs'} · ${esc(p.src)} ${fmtP(p.price)}</b> ` +
      `<span class="muted">${fmtPct((p.price / d.price - 1) * 100)} · ${num(Math.abs(p.price - d.price) / d.atr, 1)} ATR</span></div>` +
      `<div class="note">${p.side === 'long' ? 'Sous ce creux, les acheteurs ont placé leurs stops' : 'Au-dessus de ce sommet, les vendeurs ont placé leurs stops'} : tout le monde voit ce niveau. Force ${p.score}/100 (mois > semaine > jour > creux ou sommet sur 1 h ; deux extrêmes au même prix comptent plus).</div>` +
      impDetail(p, 'stops') + (p.reach ? reachBlock(p.reach, 'atteigne ce niveau') : '');
  } else {
    const l = lv[s.id]; if (!l) { el.textContent = 'Niveau disparu.'; return; }
    const side = l.price < d.price ? 'support' : 'résistance';
    el.innerHTML = `<div><b><span class="chip" style="background:${levelColor(l)}"></span>${esc(l.name)} ${fmtP(l.price)}</b> <span class="muted">${fmtPct(l.distPct)} · ${num(l.distAtr, 1)} ATR</span></div>` +
      `<div class="note">${esc(explain(l.name))}</div>` +
      (l.family ? statLine(l.famStat, base, `${esc(l.family)} en ${side}`) + defNote() : '') +
      `${l.zone ? '<div class="note">Fait partie d\'une confluence (voir la liste).</div>' : ''}`;
  }
}
function renderContext(d) {
  const c = d.context, el = $('#context');
  if (!c) return;
  el.className = '';
  const sym = d.symbol.replace(/USDT$/, '');
  const cell = v => `<td class="${v > 0 ? 'up' : v < 0 ? 'dn' : ''}">${sPct(v)}</td>`;
  let h = '';
  if (c.regime) h += `<div class="verdict"><b>Régime 4 h :</b> ${esc(c.regime.label)}</div>`;
  h += `<table class="st"><tr><th></th><th>1 h</th><th>4 h</th><th>24 h</th></tr>` +
    `<tr><td class="muted">Prix</td>${cell(c.price.d1h)}${cell(c.price.d4h)}${cell(c.price.d24h)}</tr>` +
    `<tr><td class="muted">Open Interest</td>${cell(c.oi.d1h)}${cell(c.oi.d4h)}${cell(c.oi.d24h)}</tr></table>`;
  if (c.cvd) {
    const fmtV = v => v == null ? '-' : (v > 0 ? '+' : '') + Math.round(v).toLocaleString('fr-FR') + ' ' + sym;
    h += `<div class="sect">CVD (volume agressif acheteur − vendeur)</div><dl class="kv">` +
      `<dt>4 h</dt><dd class="${c.cvd.d4h > 0 ? 'up' : 'dn'}">${fmtV(c.cvd.d4h)} <span class="muted">(${num(c.cvd.buy4h, 1)} % achats)</span></dd>` +
      `<dt>24 h</dt><dd class="${c.cvd.d24h > 0 ? 'up' : 'dn'}">${fmtV(c.cvd.d24h)} <span class="muted">(${num(c.cvd.buy24h, 1)} % achats)</span></dd></dl>` +
      (c.cvd.div ? `<div class="note">⚠ Divergence ${esc(c.cvd.div)}</div>` : '');
  }
  h += '<div class="sect">Positionnement</div><dl class="kv">';
  if (c.funding) {
    const left = Math.max(0, c.funding.next - Date.now()), hh = Math.floor(left / 3.6e6), mm = Math.floor(left % 3.6e6 / 6e4);
    h += `<dt>Funding</dt><dd>${sPct(c.funding.now, 4)} <span class="muted">(moy. 7 j ${sPct(c.funding.avg7d, 4)})</span></dd>` +
      `<dt></dt><dd class="muted small">${esc(c.funding.label)} · prochain dans ${hh} h ${String(mm).padStart(2, '0')}</dd>`;
  }
  if (c.basis != null) h += `<dt>Basis perp/index</dt><dd>${sPct(c.basis, 3)}</dd>`;
  const ls = c.ls || {};
  if (ls.global) h += `<dt>L/S comptes</dt><dd>${num(ls.global.now)} <span class="muted">(${Math.round(ls.global.long * 100)} % longs${ls.global.d24h != null ? ', 24 h ' + (ls.global.d24h > 0 ? '+' : '') + num(ls.global.d24h) : ''})</span></dd>`;
  if (ls.top) h += `<dt>L/S top traders</dt><dd>${num(ls.top.now)} <span class="muted">(${Math.round(ls.top.long * 100)} % longs${ls.top.d24h != null ? ', 24 h ' + (ls.top.d24h > 0 ? '+' : '') + num(ls.top.d24h) : ''})</span></dd>`;
  if (c.coinbase) h += `<dt>Prime Coinbase</dt><dd>${sPct(c.coinbase.premium, 3)} <span class="muted">${esc(c.coinbase.label)}</span></dd>`;
  h += '</dl>';
  if (ls.global && ls.top) {
    const crowd = ls.global.long - ls.top.long;
    if (Math.abs(crowd) > 0.08) h += `<div class="note">${crowd > 0 ? 'La foule est plus longue que les gros comptes' : 'Les gros comptes sont plus longs que la foule'} (${Math.round(Math.abs(crowd) * 100)} pts d'écart).</div>`;
  }
  if (c.liq) h += `<div class="sect">Liquidations estimées encore ouvertes</div>` +
    `<div class="imb"><i style="width:${c.liq.long}%;background:${UP}"></i><i style="width:${c.liq.short}%;background:${DN}"></i></div>` +
    `<div class="muted small">longs (sous le prix) ${Math.round(c.liq.long)} % · shorts (au-dessus) ${Math.round(c.liq.short)} % · répartition par vrai volume acheteur sur ${Math.round(c.liq.taker)} % des bougies</div>`;
  const errs = Object.entries(c.errors || {});
  if (errs.length) h += `<div class="note">Indisponible pour l'instant : ${errs.map(([k]) => esc(k)).join(', ')}.</div>`;
  el.innerHTML = h;
  $('#ctxHint').textContent = d.source === 'simulated' ? 'données simulées' : 'Binance';
  const rg = $('#regime');
  const sq = c.squeeze && c.squeeze.state && c.squeeze.state.code !== 'none' ? c.squeeze.state : null;
  rg.hidden = !c.regime && !sq;
  if (sq) { rg.textContent = sq.label; rg.title = sq.text; }
  else if (c.regime) { rg.textContent = c.regime.label; rg.title = 'Régime prix / Open Interest sur 4 h'; }
}
function statTable(rows, base, side) {
  return `<table class="st"><tr><th></th><th>rebond</th><th style="width:42%"></th><th class="n">n</th></tr>` + rows.map(([name, v, cls]) => {
    const s = v && v[side];
    return `<tr class="${cls || ''}"><td>${esc(name)}</td><td class="pr">${s && s.n ? pr(s.p) : '-'}</td><td>${ciBar(s, base && base[side])}</td><td class="n">${s ? s.n : 0}</td></tr>`;
  }).join('') + '</table>';
}
function renderStats(d) {
  const s = d.stats, el = $('#stats');
  if (!s || !s.ready) { el.className = 'muted'; el.textContent = 'Calcul en cours sur l\'historique 1h (quelques secondes après le chargement)…'; return; }
  el.className = '';
  const base = s.family['Hasard (témoin)'], side = st.statSide;
  const fams = Object.keys(s.family).filter(f => f !== 'Hasard (témoin)').sort((a, b) => ((s.family[b][side] || {}).p || 0) - ((s.family[a][side] || {}).p || 0));
  const sides = [['all', 'tous'], ['support', 'supports'], ['resistance', 'résistances']];
  let h = `<div class="seg" id="statSide" style="margin-bottom:6px">${sides.map(([k, l]) => `<button data-side="${k}" class="${k === side ? 'on' : ''}">${l}</button>`).join('')}</div>`;
  h += '<div class="sect">Par type de niveau</div>' + statTable(fams.map(f => [f, s.family[f]]).concat([['Hasard (témoin)', base, 'base']]), base, side);
  h += '<div class="sect">Par nombre de sources dans la zone</div>' + statTable([['1 source', s.score['1']], ['2 sources', s.score['2']], ['3 ou plus', s.score['3+']], ['Hasard (témoin)', base, 'base']], base, side);
  h += '<div class="sect">Selon le flux de la bougie de contact</div><table class="st"><tr><th></th><th>observé</th><th>attendu</th><th>écart</th><th class="n">n</th></tr>' +
    [['avec', 'acheteurs sur support / vendeurs sur résistance'], ['contre', 'flux dans le sens de la cassure']].map(([k, t]) => {
      const v = s.flow[k] && s.flow[k][side];
      if (!v || !v.n) return `<tr><td title="${t}">${k}</td><td colspan="4" class="muted">-</td></tr>`;
      const gap = (v.p - v.expected) * 100, sig = Math.abs(v.p - v.expected) > (v.hi - v.lo) / 2;
      return `<tr><td title="${t}">${k === 'avec' ? 'flux avec le rebond' : 'flux contre'}</td><td class="pr">${pr(v.p)}</td><td class="pr muted">${pr(v.expected)}</td>` +
        `<td class="${sig ? (gap > 0 ? 'up' : 'dn') : 'muted'}">${gap > 0 ? '+' : ''}${num(gap, 1)} pt</td><td class="n">${v.n}</td></tr>`;
    }).join('') + '</table><div class="note">« Attendu » = ce que donnerait le hasard depuis la clôture de la bougie de contact. Seul l\'écart compte : un écart dans la marge d\'erreur (gris) ne prouve rien.</div>';
  h += defNote() + `<div class="note">Barre = intervalle de confiance à 90 % · trait orange = hasard. ${s.meta.bars.toLocaleString('fr-FR')} bougies 1h (${new Date(s.meta.from).toLocaleDateString('fr-FR')} → ${new Date(s.meta.to).toLocaleDateString('fr-FR')}), ${s.meta.events.toLocaleString('fr-FR')} contacts.</div>`;
  el.innerHTML = h;
  $('#statsHint').textContent = `${d.symbol} · mis à jour ${new Date(s.computedAt * 1000).toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit'})}`;
  const sw = d.sweeps, se = $('#sweeps');
  if (!sw || !sw.recent.length) { se.className = 'muted'; se.textContent = 'Aucun balayage significatif dans le journal (30 derniers jours d\'OI).'; return; }
  se.className = '';
  const lab = {bounce: 'rebond', break: 'continuation', open: 'en cours'};
  se.innerHTML = statLine(sw.stats, base, 'Après balayage') +
    `<table class="st"><tr><th>quand</th><th>poche</th><th>prix</th><th>part</th><th>suite</th></tr>` + sw.recent.map(e =>
      `<tr><td class="muted">${timeFr(e.t)}</td><td class="${e.side === 'long' ? 'up' : 'dn'}">${e.side === 'long' ? 'longs' : 'shorts'}</td><td>${fmtP(e.price)}</td>` +
      `<td>${Math.round(e.frac * 100)} %</td><td><span class="res ${e.result}">${lab[e.result] || e.result}</span></td></tr>`).join('') + '</table>' +
    '<div class="note">Part = taille de la poche balayée / total des liquidations estimées de ce côté. Rebond = le prix repart dans l\'autre sens après la chasse aux stops.</div>';
}
async function renderAlerts() {
  try {
    const a = await api('/api/alerts');
    $('#alertHint').textContent = a.telegram ? 'Telegram actif' : 'Telegram non configuré';
    const rule = st.cfg ? `Règle : score ≥ ${st.cfg.alertMinScore} à moins de ${st.cfg.alertMaxDistAtr} ATR (${st.cfg.alertTf}), puis « approche » à 0,5 ATR.` : '';
    const setup = a.telegram ? '' : '<div class="verdict">Les alertes ne partent que dans la console. <button data-open-settings>Configurer Telegram</button></div>';
    $('#alerts').className = '';
    $('#alerts').innerHTML = setup + (a.log.length ? a.log.slice(0, 20).map(e => {
      const t = new Date(e.t * 1000).toLocaleString('fr-FR', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
      return `<div class="alert" title="${esc(e.text)}"><time>${t}</time>${e.sent ? '✓' : '✗'} ${esc(e.text.split('\n')[0])}</div>`;
    }).join('') : '<div class="muted">Aucune alerte pour l\'instant.</div>') + `<div class="note">${rule}</div>`;
  } catch (e) { /* silencieux */ }
}

// ---------- selection ----------
function select(sel) {
  st.sel = sel; st.version++;
  if (st.data) {
    panels.forEach(p => p.rebuildLines());
    renderLadder(st.data); renderPools(st.data); renderPricePools(st.data); renderPools2(st.data); renderDetail(st.data);
    const d2 = $('#detail2'); if (d2) { d2.className = $('#detail').className; d2.innerHTML = $('#detail').innerHTML; }
  }
}
document.addEventListener('click', e => {
  const z = e.target.closest('[data-zone]'), p = e.target.closest('[data-pool]'), q = e.target.closest('[data-ppool]');
  if (z) select({type: 'zone', id: z.dataset.zone});
  else if (p) select({type: 'pool', id: +p.dataset.pool});
  else if (q) select({type: 'ppool', id: +q.dataset.ppool});
});

// ---------- donnees ----------
function banner(kind, html) {
  const b = $('#banner');
  if (!kind) { b.hidden = true; b.innerHTML = ''; return; }
  b.className = kind; b.hidden = false;
  if (b.innerHTML !== html) b.innerHTML = html;
}
function updateBanner(d) {
  const c = st.cfg;
  if (!c) return;
  if (d && d.error && d.source !== 'simulated') banner('bad', `<span>Problème de données Binance : ${esc(d.error)}</span><button data-open-settings>Tester la connexion</button>`);
  else if (!d && c.source === 'binance') banner('warn', '<span>Chargement de l\'historique Binance (la première fois : plusieurs minutes pour tout l\'historique depuis 2019, ensuite quelques secondes)…</span>');
  else if (c.source === 'simulated') banner('warn', '<span>⚠ Données <b>SIMULÉES</b> : les prix sont fictifs, c\'est pour découvrir le terminal.</span><button data-open-settings class="primary">Passer aux vraies données Binance</button>');
  else banner(null);
}
function header(d) {
  $('#price').textContent = fmtP(livePrice(d));
  $('#atr').textContent = `ATR ${st.tf} ${fmtP(d.atr)} (${num(d.atrPct)} %)`;
  const sb = $('#srcBadge');
  sb.textContent = d.source === 'simulated' ? 'DONNÉES SIMULÉES' : 'BINANCE';
  sb.className = 'badge ' + (d.source === 'simulated' ? 'warn' : 'ok');
  const tb = $('#tgBadge');
  tb.textContent = st.cfg && st.cfg.telegram ? 'TELEGRAM ON' : 'TELEGRAM OFF';
  tb.className = 'badge ' + (st.cfg && st.cfg.telegram ? 'ok' : '');
  const age = Math.max(0, Math.round(Date.now() / 1000 - d.lastUpdate));
  $('#status').textContent = d.error ? 'erreur' : `niveaux : il y a ${age} s`;
  $('#status').className = d.error ? 'bad' : 'muted';
  updateBanner(d);
}
// bougies du graphique : mise a jour douce (ne deplace pas la vue) ; la bougie en cours garde les extremes et la cloture du flux
function pushBars(d) {
  const key = d.symbol + '|' + d.tf, reset = key !== st.key;
  let bars = d.candles.map(c => ({time: c[0], open: c[1], high: c[2], low: c[3], close: c[4]}));
  if (reset) {
    st.key = key; live.bar = null;
    st.lastBar = bars.length ? bars[bars.length - 1].time : 0;
  } else {
    bars = bars.filter(b => b.time >= st.lastBar).map(b => {
      const lb = live.bar;
      if (lb && lb.time === b.time && liveFresh()) { b = {...b, high: Math.max(b.high, lb.high), low: Math.min(b.low, lb.low), close: lb.close}; live.bar = b; }
      st.lastBar = Math.max(st.lastBar, b.time);
      return b;
    });
  }
  panels.forEach(p => p.setBars(reset ? d.candles.map(c => ({time: c[0], open: c[1], high: c[2], low: c[3], close: c[4]})) : bars, reset));
  const all = d.candles[d.candles.length - 1];
  st.lastBarObj = {time: all[0], open: all[1], high: all[2], low: all[3], close: all[4]};
  if (live.bar && live.bar.time === st.lastBarObj.time) st.lastBarObj = {...live.bar};
  if (reset) setTimeout(() => { panels.forEach(p => p.visible() && p.resetView()); }, 150);
}
function apply(d) {
  if (d.liquidity && d.liquidity.extraPools && d.liquidity.extraPools.length) d.liquidity.pools = d.liquidity.pools.concat(d.liquidity.extraPools);   // N°1 et N°2 hors de la liste (affichage seul)
  st.data = d;
  if (d.now) st.clockOff = d.now - Date.now();
  pushBars(d); header(d); panels.forEach(p => p.rebuildLines());
  renderLadder(d); renderPools(d); renderPricePools(d); renderPools2(d); renderDetail(d); renderContext(d); renderStats(d);
  st.version++;
}
let timer = null;
async function poll() {
  clearTimeout(timer);
  timer = setTimeout(poll, 2000);
  let d;
  try {
    const r = await fetch(`/api/state?symbol=${st.symbol}&tf=${st.tf}`);
    const boot = r.headers.get('X-Terminal-Boot');                 // le terminal a redemarre (mise a jour installee) : on recharge la page
    if (boot && st.boot && boot !== st.boot) { location.reload(); return; }
    if (boot) st.boot = boot;
    d = await r.json();
  }
  catch (e) { $('#status').textContent = 'terminal injoignable : redémarrage en cours, ou la fenêtre du programme est fermée'; $('#status').className = 'bad'; return; }
  try {
    if (d.ready) apply(d);
    else {
      const err = d.error && d.error !== 'chargement des donnees...';
      $('#status').textContent = err ? 'erreur' : 'chargement des données...';
      $('#status').className = 'muted';
      if (err) banner('bad', `<span>Données indisponibles : ${esc(d.error)}</span><button data-open-settings>Tester la connexion</button>`);
      else updateBanner(null);
    }
  } catch (e) { console.error(e); $('#status').textContent = 'erreur d\'affichage : ' + e.message; $('#status').className = 'bad'; }
}
function resetSymbolData() {
  st.flow = null;
  st.sel = null; st.data = null; st.heat = null; st.liqs = null; st.an = null; st.series = null; st.vpd = null; st.key = null; st.sig = null; st.planKey = null; st.planSig = ''; st.plan = null;
}
function buildControls(cfg) {
  st.cfg = cfg;
  if (!cfg.symbols.includes(st.symbol)) st.symbol = cfg.symbols[0];
  const sel = $('#symbol'); sel.innerHTML = cfg.symbols.map(s => `<option${s === st.symbol ? ' selected' : ''}>${s}</option>`).join('');
  sel.onchange = () => { st.symbol = sel.value; resetSymbolData(); liveConnect(); cbConnect(); poll(); pollAnalysis(); refreshAll(); pollOverview(); pollSignals(); reloadSideTab(); MTF.refresh(); TPO.refresh(); };
  const box = $('#tfs');
  box.innerHTML = cfg.tfs.map(t => `<button data-tf="${t}" class="${t === st.tf ? 'on' : ''}">${t}</button>`).join('');
  box.onclick = e => { const b = e.target.closest('button'); if (!b) return; st.tf = b.dataset.tf; st.sel = null; st.data = null; st.series = null; st.vpd = null;
    box.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); poll(); refreshAll(); };
  updateBanner(st.data);
  if (!live.ws || live.sym !== st.symbol || !cfg.wsBase) liveConnect();
  if (cfg.cbWs && (!cb.ws || cb.sym !== st.symbol)) cbConnect();
}

// ---------- onglets du panneau de droite ----------
function showPane(name) {
  st.tab = name;
  document.querySelectorAll('#side .pane').forEach(p => p.hidden = p.dataset.pane !== name);
  document.querySelectorAll('#tabs button').forEach(x => x.classList.toggle('on', x.dataset.tab === name));
  try { localStorage.setItem('liqTab', name); } catch (err) { /* stockage indisponible */ }
  if (name === 'chat') loadChat();
  if (name === 'liquidity') { pollLiqs(); renderLqReal(); }
  if (name === 'vp') pollVP();
  if (name === 'signals') { pollSignals(); if (st.sig) Signals.render(st.sig); }
  if (name === 'mine') Strategy.show();
  if (name === 'lecture') Lecture.show();
}
// onglets detailles (contexte, stats, liquidite, profils, alertes) : caches par defaut, un bouton les affiche
function reloadSideTab() { if (st.tab === 'lecture') Lecture.show(); else if (st.tab === 'mine') Strategy.show(); }
const EXPERT_TABS = ['context', 'stats', 'liquidity', 'vp', 'alerts'];
function applyExpert() {
  document.querySelectorAll('#tabs button[data-expert], #sidebar a[data-expert]').forEach(b => { b.hidden = !st.expert; });
  const nt = $('#navExpertTxt'); if (nt) nt.textContent = 'Mode détaillé : ' + (st.expert ? 'oui' : 'non');
  const more = $('#tabMore'); if (more) { more.textContent = st.expert ? 'Détails ▴' : 'Détails ▾'; more.classList.toggle('on', st.expert); }
  if (!st.expert && EXPERT_TABS.includes(st.tab)) showPane('lecture');
}
const toggleExpert = () => { st.expert = !st.expert; applyExpert(); savePrefs(); };
$('#tabMore').onclick = toggleExpert;
$('#navExpert').onclick = e => { e.preventDefault(); toggleExpert(); };
$('#tabs').onclick = e => { const b = e.target.closest('button[data-tab]'); if (b) showPane(b.dataset.tab); };
$('#stats').addEventListener('click', e => {
  const b = e.target.closest('button[data-side]'); if (!b) return;
  st.statSide = b.dataset.side; if (st.data) renderStats(st.data);
});

// ---------- workspace : pages, menu lateral, mise en page ----------
const PAGES = {desk: 'Desk', overview: 'Overview', history: 'Historique', backtest: 'Backtest', analysis: 'Analyse'};
const SUBS = {synth: 'Biais & probabilités', macro: 'Macro & annonces', dom: 'Dominance BTC / alts', plan: 'Plan de trade', lex: 'Lexique du graphique'};
function navigate(page, sub) {
  if (!PAGES[page]) page = 'desk';
  st.page = page;
  if (page === 'analysis') st.sub = SUBS[sub] ? sub : (st.sub || 'synth');
  document.querySelectorAll('.page').forEach(p => p.hidden = p.dataset.page !== page);
  document.querySelectorAll('#sidebar a[data-nav]').forEach(a => a.classList.toggle('on', a.dataset.nav === page && (page !== 'analysis' || a.dataset.sub === st.sub)));
  $('#crumb').textContent = page === 'analysis' ? SUBS[st.sub] : PAGES[page];
  if (page === 'analysis') Analysis.show(st.sub);
  if (page === 'desk') setTimeout(() => { syncRange(); refreshAll(); }, 60);
  if (page === 'desk' && st.layout === 'mtf') MTF.show(); else MTF.hide();
  if (page === 'desk' && st.layout === 'tpo') TPO.show(); else TPO.hide();
  if (page === 'overview') pollOverview();
  if (page === 'backtest') Backtest.show();
  if (page === 'history') History.show();
  try { localStorage.setItem('liqPage', page + (page === 'analysis' ? '/' + st.sub : '')); } catch (e) { /* rien */ }
}
function routeFromHash() {
  const m = /^#\/([a-z]+)(?:\/([a-z]+))?/.exec(location.hash);
  if (m && m[1] === 'signals') { st.sideOpen = true; navigate('desk'); applyLayout(); showPane('signals'); document.querySelectorAll('#sidebar a[data-nav]').forEach(a => a.classList.toggle('on', a.dataset.nav === 'signals')); }
  else if (m) navigate(m[1], m[2]);
  else { let saved = null; try { saved = localStorage.getItem('liqPage'); } catch (e) { /* rien */ } const q = (saved || 'desk').split('/'); navigate(q[0], q[1]); }
}
window.addEventListener('hashchange', routeFromHash);
function applySidebar() { document.body.classList.toggle('sbmin', st.sbCollapsed); $('#sbToggle').textContent = st.sbCollapsed ? '»' : '«'; }
$('#sbToggle').onclick = () => { st.sbCollapsed = !st.sbCollapsed; applySidebar(); savePrefs(); setTimeout(() => { st.version++; }, 250); };
$('#layouts').onclick = e => { const b = e.target.closest('button[data-layout]'); if (b) { st.layout = b.dataset.layout; applyLayout(); } };
$('#sideToggle').onclick = () => { st.sideOpen = !st.sideOpen; applyLayout(); };

// ---------- carte de chaleur, liquidations reelles, VWAP / volume profiles : recuperation ----------
let heatTimer = null, liqTimer = null, vpTimer = null;
async function pollHeat() {
  clearTimeout(heatTimer);
  if (!needs('liq')) return;
  heatTimer = setTimeout(pollHeat, 45000);
  try {
    const sym = st.symbol, h = await api(`/api/heat?symbol=${sym}&hours=${st.liqOpts.hours}`);
    if (sym !== st.symbol || !h.ready) return;
    const dec = b64 => Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    h.L = dec(h.long); h.S = dec(h.short); h.img = buildHeatImage(h);
    st.heat = h; st.version++;
  } catch (e) { /* le serveur repondra au prochain essai */ }
}
async function pollLiqs() {
  clearTimeout(liqTimer);
  if (!(needs('liq') || st.tab === 'liquidity')) return;
  liqTimer = setTimeout(pollLiqs, 8000);
  try { st.liqs = await api(`/api/liqs?symbol=${st.symbol}&hours=24`); renderLqReal(); st.version++; } catch (e) { /* rien */ }
}
async function pollVP() {
  clearTimeout(vpTimer);
  if (!needsSeries()) return;
  vpTimer = setTimeout(pollVP, 20000);
  try {
    const sym = st.symbol, tf = st.tf;
    const [S, V] = await Promise.all([api(`/api/series?symbol=${sym}&tf=${tf}`), api(`/api/vp?symbol=${sym}&tf=${tf}`)]);
    if (sym !== st.symbol || tf !== st.tf) return;
    S.stampN = ++st.serN; st.series = S; st.vpd = V;
    if (V.ready && !V.profiles.find(p => p.id === st.vpFocus)) st.vpFocus = V.profiles[0] ? V.profiles[0].id : null;
    renderVPList(); st.version++;
  } catch (e) { /* rien */ }
}

// ---------- V15 : flux d'ordres (carnet aligne sur les prix, gros ordres, vitesse du ruban, latence) ----------
let flowTimer = null;
async function pollFlow() {
  clearTimeout(flowTimer);
  const o = st.mainOpts, main = panels.find(p => p.kind === 'main');
  if (!st.cfg || !needs('main') || !(o.dom || o.big) || !main || !main.visible() || document.hidden) { flowTimer = setTimeout(pollFlow, 1500); return; }
  flowTimer = setTimeout(pollFlow, o.dom ? 400 : 2000);
  const g = main.flowGeom(), sym = st.symbol;
  if (!g || !st.data) return;
  const since = st.data.candles.length ? st.data.candles[0][0] * 1000 : 0;
  try {
    const f = await api(`/api/flow?symbol=${sym}&step=${g.step}&rows=${o.dom ? g.rows : 4}&center=${g.center}&since=${since}`);
    if (sym === st.symbol) { st.flow = f; st.version++; }
  } catch (e) { /* le serveur repondra au prochain essai */ }
}
const fmtQty = q => q == null || isNaN(q) ? '-' : q >= 1e6 ? (q / 1e6).toFixed(1).replace('.', ',') + 'M' : q >= 1e4 ? Math.round(q / 1e3) + 'k' : q >= 1e3 ? (q / 1e3).toFixed(1).replace('.', ',') + 'k'
  : q >= 100 ? String(Math.round(q)) : q >= 10 ? q.toFixed(1).replace('.', ',') : q >= 1 ? q.toFixed(2).replace('.', ',') : q.toFixed(3).replace('.', ',');
const fmtUsdShort = v => v >= 1e6 ? (v / 1e6).toFixed(v >= 1e7 ? 0 : 1).replace('.', ',') + 'M' : v >= 1e3 ? Math.round(v / 1e3) + 'k' : String(Math.round(v || 0));
// ouvre une unite de la grille multi-unites dans le graphique principal (carnet, poches, zones…)
function openTf(tf) {
  if (!TF_SEC[tf]) return;
  if (tf !== st.tf) {
    st.tf = tf; st.sel = null; st.data = null; st.series = null; st.vpd = null; st.flow = null;
    document.querySelectorAll('#tfs button').forEach(x => x.classList.toggle('on', x.dataset.tf === tf)); poll();
  }
  st.layout = '1'; applyLayout();
}
function applyTheme() {
  document.body.classList.toggle('theme-nuit', st.theme === 'nuit');
  const b = $('#themeBtn'); if (b) b.textContent = st.theme === 'nuit' ? '☾ nuit' : '☀ classique';
  panels.forEach(p => p.applyTheme());
  MTF.applyTheme(); TPO.redraw();
  st.version++;
}

// ---------- gestion des volume profiles (onglet VP) ----------
const specText = s => s.kind === 'auto' ? 'Automatique (selon la timeframe)' : s.kind === 'rolling' ? `Glissant ${s.days} jours` : s.kind === 'since' ? `Depuis le ${s.date}` :
  ({day: 'Jour', week: 'Semaine', month: 'Mois', quarter: 'Trimestre', year: 'Année'}[s.period]) + (s.back ? ` -${s.back}` : ' en cours');
function renderVPList() {
  const V = st.vpd, el = $('#vpList'); if (!el) return;
  if (!V || !V.ready) { el.className = 'muted'; el.textContent = needs('vp') || st.tab === 'vp' ? 'Chargement…' : 'Ouvre le graphique VWAP · VP pour charger les profils.'; return; }
  el.className = '';
  const dt = t => new Date(t).toLocaleDateString('fr-FR', {day: '2-digit', month: '2-digit', year: '2-digit'});
  el.innerHTML = V.profiles.length ? `<table class="t"><tr><th>Profil</th><th>Fenêtre</th><th class="r">POC</th><th class="r">VAH</th><th class="r">VAL</th><th class="r">Barres</th></tr>` +
    V.profiles.map(p => `<tr data-vpf="${esc(p.id)}" class="${p.id === st.vpFocus ? 'hl' : ''}" style="cursor:pointer" title="Afficher l'histogramme de ce profil"><td><span class="chip" style="background:#4c8dff"></span>${esc(p.label)}</td>` +
      `<td class="muted small">${dt(p.t0)} → ${dt(p.t1)}</td><td class="r">${fmtP(p.poc)}</td><td class="r">${fmtP(p.vah)}</td><td class="r">${fmtP(p.val)}</td><td class="r muted">${p.bars}</td></tr>`).join('') + `</table>` :
    '<div class="muted">Aucun profil sur cette timeframe (pas assez de données).</div>';
  const hasAuto = V.specs.some(s => s.kind === 'auto');
  $('#vpAuto').checked = hasAuto;
  $('#vpAutoTxt').textContent = (V.auto[st.tf] || []).map(n => n >= 365 ? (n / 365) + ' an' + (n >= 730 ? 's' : '') : n + ' j').join(' · ');
  $('#vpSpecs').innerHTML = V.specs.filter(s => s.kind !== 'auto').map((s, i) => `<div class="alert"><span>${esc(specText(s))}</span> <button class="x" data-vprm="${i}" title="Retirer">×</button></div>`).join('') || '<div class="muted small">Aucun profil personnalisé.</div>';
  $('#vpAnchors').innerHTML = V.anchors.map((a, i) => `<div class="alert"><span>AVWAP ${esc(a)}</span> <button class="x" data-anrm="${i}" title="Retirer">×</button></div>`).join('') || '<div class="muted small">Aucune ancre ajoutée.</div>';
}
async function saveVP(specs, anchors) {
  const out = $('#vpRes');
  try {
    await api('/api/vps', {specs, anchors});
    out.className = 'up small'; out.textContent = '✓ enregistré';
    pollVP(); poll();
  } catch (e) { out.className = 'dn small'; out.textContent = e.message; }
  setTimeout(() => { out.textContent = ''; }, 4000);
}
document.addEventListener('click', e => {
  const r = e.target.closest('tr[data-vpf]');
  if (r) { st.vpFocus = r.dataset.vpf; renderVPList(); st.version++; }
  const rm = e.target.closest('[data-vprm]'), an = e.target.closest('[data-anrm]');
  if (rm && st.vpd) { const cust = st.vpd.specs.filter(s => s.kind !== 'auto'), auto = st.vpd.specs.filter(s => s.kind === 'auto'); cust.splice(+rm.dataset.vprm, 1); saveVP([...auto, ...cust], st.vpd.anchors); }
  if (an && st.vpd) { const a = st.vpd.anchors.slice(); a.splice(+an.dataset.anrm, 1); saveVP(st.vpd.specs, a); }
});
$('#vpKind').onchange = () => document.querySelectorAll('[data-for]').forEach(l => l.hidden = l.dataset.for !== $('#vpKind').value);
$('#vpAuto').onchange = e => {
  if (!st.vpd) return;
  const cust = st.vpd.specs.filter(s => s.kind !== 'auto');
  saveVP(e.target.checked ? [{kind: 'auto'}, ...cust] : cust, st.vpd.anchors);
};
$('#vpAdd').onclick = () => {
  if (!st.vpd) return;
  const k = $('#vpKind').value;
  const spec = k === 'rolling' ? {kind: 'rolling', days: +$('#vpDays').value} : k === 'since' ? {kind: 'since', date: $('#vpDate').value} : {kind: 'period', period: $('#vpPeriod').value, back: +$('#vpBack').value};
  saveVP([...st.vpd.specs, spec], st.vpd.anchors);
};
$('#anchorAdd').onclick = () => { if (st.vpd && $('#vpAnchorDate').value) saveVP(st.vpd.specs, [...st.vpd.anchors, $('#vpAnchorDate').value]); };

// ---------- Coinbase en direct (meme marche que le graphique TradingView en USD) ----------
const cb = {ws: null, price: null, t: 0, sym: null, retry: 0, timer: null};
function cbConnect() {
  clearTimeout(cb.timer);
  if (cb.ws) { const w = cb.ws; cb.ws = null; try { w.close(); } catch (e) { /* deja ferme */ } }
  const url = st.cfg && st.cfg.cbWs;
  if (!url || !st.symbol) { $('#cbPrice').hidden = true; return; }
  if (cb.sym !== st.symbol) { cb.price = null; }
  cb.sym = st.symbol;
  const product = st.symbol.replace(/USDT$/, '') + '-USD';
  let ws;
  try { ws = new WebSocket(url); } catch (e) { return; }
  cb.ws = ws;
  ws.onopen = () => ws.send(JSON.stringify({type: 'subscribe', product_ids: [product], channels: ['ticker']}));
  ws.onmessage = ev => { try { const m = JSON.parse(ev.data); if (m.type === 'ticker' && m.product_id === product && m.price) { cb.price = +m.price; cb.t = Date.now(); cb.retry = 0; } } catch (e) { /* ignore */ } };
  ws.onerror = () => { try { ws.close(); } catch (e) { /* rien */ } };
  ws.onclose = () => { if (cb.ws === ws) { cb.ws = null; cb.timer = setTimeout(cbConnect, Math.min(30000, 1000 * Math.pow(2, cb.retry++))); } };
}
function cbRender() {
  const el = $('#cbPrice');
  if (!st.cfg || !st.cfg.cbWs || cb.price == null || Date.now() - cb.t > 20000 || !st.data) { el.hidden = true; return; }
  const ref = livePrice(st.data), d = cb.price - ref;
  if (Math.abs(d) / ref > 0.03) { el.hidden = true; return; }               // écart > 3 % : mauvais produit ou donnée périmée, on n'affiche rien
  el.hidden = false;
  el.innerHTML = `Coinbase <b>${fmtP(cb.price)}</b> <span class="${d > 0 ? 'up' : d < 0 ? 'dn' : ''}">${d > 0 ? '+' : ''}${fmtP(Math.abs(d)) === '0,00' ? '0' : (d < 0 ? '−' : '') + fmtP(Math.abs(d))} (${fmtPct(d / ref * 100)})</span>`;
}

// ---------- analyse (biais, macro, dominance) ----------
let anTimer = null;
async function pollAnalysis() {
  clearTimeout(anTimer);
  anTimer = setTimeout(pollAnalysis, 15000);
  if (!st.symbol) return;
  try {
    const sym = st.symbol, an = await api(`/api/analysis?symbol=${sym}`);
    if (sym !== st.symbol || !an.ready) return;
    st.an = an; Analysis.render(an); riskChip();
  } catch (e) { $('#anStatus').textContent = 'analyse indisponible : ' + e.message; }
}
function riskChip() {
  const el = $('#riskChip'), r = st.an && st.an.macro && st.an.macro.risk;
  if (!r) { el.hidden = true; return; }
  const mins = (r.t - Date.now()) / 60000;
  if (mins < -30) { el.hidden = true; return; }
  const lvl = mins <= 90 ? 'danger' : mins <= 720 ? 'attention' : 'info';
  el.hidden = false; el.className = 'badge risk ' + lvl;
  const tm = Math.round(Math.abs(mins));
  el.textContent = (mins >= 0 ? '⚠ ' : '') + r.label + (mins >= 0 ? ' dans ' : ' il y a ') + (tm >= 60 ? Math.floor(tm / 60) + ' h ' + String(tm % 60).padStart(2, '0') : tm + ' min');
  el.title = 'Annonce majeure : ouvre l\'onglet Macro & annonces';
}
$('#riskChip').onclick = () => { const b = document.querySelector('#anTabs button[data-an="macro"]'); if (b) { b.click(); $('#analysis').scrollIntoView({behavior: 'smooth'}); } };

// ---------- idees de trade ----------
let sigTimer = null;
function activePlan() {
  const sg = st.sig && st.sig.symbols && st.sig.symbols[st.symbol];
  if (!st.planOn || !sg || !sg.ready) return null;
  let p = st.planKey ? sg.ideas.find(i => i.key === st.planKey) : sg.ideas.find(i => i.eligible);
  if (!p && !st.planKey) {                                           // pas d'idee : on suit l'idee envoyee encore ouverte
    const t = st.sig.desk.trades.find(x => x.symbol === st.symbol && ['pending', 'active', 'tp1'].includes(x.status));
    if (t) p = {key: t.id, side: t.side, entry: t.entry, stop: t.stop, tp1: t.tp1, tp2: t.tp2, score: t.score, kind: t.kind};
  }
  return p ? {symbol: st.symbol, side: p.side, entry: p.entry, stop: p.stop, tp1: p.tp1, tp2: p.tp2, score: p.score, key: p.key, kind: p.kind} : null;
}
function updatePlan() {
  const p = activePlan(), k = p ? [p.key, p.entry, p.stop, p.tp1, p.tp2].join() : '';
  if (k !== st.planSig) { st.planSig = k; st.plan = p; st.version++; panels.forEach(x => x.sig = ''); }
}
function sigChip() {
  const el = $('#sigChip'), sg = st.sig && st.sig.symbols && st.sig.symbols[st.symbol];
  const best = sg && sg.ready && sg.ideas.find(i => i.eligible);
  const open = st.sig && st.sig.desk && st.sig.desk.trades.find(t => t.symbol === st.symbol && ['pending', 'active', 'tp1'].includes(t.status));
  if (!best && !open) { el.hidden = true; return; }
  el.hidden = false;
  const i = best || open, buy = i.side === 'long';
  el.className = 'badge sig ' + (buy ? 'up' : 'dn');
  el.textContent = best ? `🎯 ${buy ? 'ACHAT' : 'VENTE'} ${Math.round(best.score)}/100` : `🎯 ${buy ? 'Achat' : 'Vente'} en cours`;
  el.title = best ? `Idée de trade ${buy ? "d'achat" : 'de vente'} : entrée ${fmtP(best.entry)}, stop ${fmtP(best.stop)}. Clique pour tout comprendre.` : 'Idée envoyée encore ouverte. Clique pour la suivre.';
}
$('#sigChip').onclick = () => { location.hash = '#/signals'; };
async function pollSignals() {
  clearTimeout(sigTimer);
  sigTimer = setTimeout(pollSignals, 6000);
  if (!st.symbol) return;
  try {
    const sym = st.symbol, r = await api(`/api/signals?symbol=${sym}`);
    if (sym !== st.symbol) return;
    st.sig = r; sigChip(); updatePlan();
    if (st.page === 'desk' && st.tab === 'signals') Signals.render(r);
  } catch (e) { /* le prochain passage reessaiera */ }
}
function setPlan(key) {
  if (key === 'off') st.planOn = false; else { st.planOn = true; st.planKey = key; }
  savePrefs(); syncAllTools(); updatePlan();
}

// ---------- reglages ----------
const M = $('#modal');
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, 4500); }
async function openSettings() {
  M.hidden = false;
  ['#binanceRes', '#chatRes', '#tgRes', '#saveRes'].forEach(k => $(k).textContent = '');
  $('#binanceList').innerHTML = '';
  try {
    const s = await api('/api/settings');
    document.querySelectorAll('input[name=source]').forEach(r => r.checked = r.value === s.source);
    $('#symbols').value = s.symbols.join(',');
    $('#histYears').value = String(s.historyYears || 0);
    $('#tgToken').value = '';
    $('#tgToken').placeholder = s.telegram.tokenHint ? `token enregistré (${s.telegram.tokenHint}) : laisse vide pour le garder` : '123456789:AA...';
    $('#tgChat').value = s.telegram.chatId || '';
    $('#tgState').textContent = s.telegram.configured ? '✓ configuré' : 'non configuré';
    $('#tgState').className = s.telegram.configured ? 'up' : '';
    $('#aScore').value = String(s.alertMinScore);
    $('#aTf').innerHTML = (st.cfg ? st.cfg.tfs : ['1h']).map(t => `<option${t === s.alertTf ? ' selected' : ''}>${t}</option>`).join('');
    $('#aCool').value = s.alertCooldownHours;
    $('#aSweep').checked = !!s.alertSweep;
    $('#aZones').checked = s.alertZones !== false;
    $('#aMode').value = s.alertMode === 'all' ? 'all' : 'ideas'; $('#aExtra').hidden = $('#aMode').value !== 'all';
    $('#aMacro').checked = s.alertMacro !== false;
    const x = s.x || {}; $('#xOn').checked = x.on !== false; $('#xAccounts').value = (x.accounts || []).join(', '); $('#xPosts').value = String(x.posts || 10);
    $('#xToken').value = ''; $('#xToken').placeholder = x.tokenHint ? `jeton enregistré (${x.tokenHint}) : laisse vide pour le garder` : 'Bearer token X (API officielle)'; $('#xRes').textContent = '';
    $('#sOn').checked = s.signalOn !== false; $('#sMin').value = s.signalMinScore; $('#sMax').value = s.signalMaxWeek; $('#sMaxSym').value = s.signalMaxPerSymbol; $('#sLev').value = s.signalLeverage; $('#sTrend').checked = s.signalTrendGate !== false; $('#sDir').value = s.signalDirection || 'both';
    const ch = s.chat || {}; $('#chatKey').value = ''; $('#chatKey').placeholder = ch.keyHint ? `clé enregistrée (${ch.keyHint}) : laisse vide pour la garder` : 'sk-ant-...';
    $('#chatWeb').checked = ch.web !== false; $('#chatTg').checked = ch.telegram !== false; $('#chatBudget').value = ch.budget != null ? ch.budget : 20; $('#chatInstallRes').textContent = '';
    try { const cs = await api('/api/chat'); $('#chatModel').innerHTML = cs.models.map(m => `<option value="${m.id}"${m.id === (ch.model || cs.model) ? ' selected' : ''}>${esc(m.name)} (${m.in} $ / ${m.out} $ par million de jetons)</option>`).join('');
      $('#chatState').textContent = !cs.configured ? 'clé manquante' : !cs.sdk ? 'module à installer' : `prêt · ${num(cs.spent, 2)} $ ce mois-ci`; $('#chatState').className = cs.configured && cs.sdk ? 'up' : 'amb';
      $('#chatInstall').hidden = cs.sdk; } catch (e) { /* ancien serveur */ }
    const u = s.update || {}; $('#updAuto').checked = u.auto !== false; $('#updBranch').value = u.branch || 'auto'; $('#updRes').textContent = '';
    $('#updToken').value = ''; $('#updToken').placeholder = u.tokenHint ? `jeton enregistré (${u.tokenHint}) : laisse vide pour le garder` : 'facultatif : github_pat_...';
    renderUpdate(await api('/api/update'));
  } catch (e) { $('#saveRes').textContent = 'Erreur : ' + e.message; }
}
// ---------- discussion avec Claude ----------
let chatTimer = null, chatPending = null;
function chatHtml(c) {
  const hist = c.history || [];
  const t = ms => new Date(ms).toLocaleString('fr-FR', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
  let h = hist.map(m => m.role === 'system' ? `<div class="sep">— ${esc(m.text)} —</div>` :
    `<div class="msg ${m.role}${m.ok === false ? ' bad' : ''}">${esc(m.text)}<small>${t(m.t)}${m.src === 'telegram' ? ' · Telegram' : ''}${m.usd ? ' · ' + num(m.usd, 3) + ' $' : ''}</small></div>`).join('');
  if (chatPending) h += `<div class="msg user">${esc(chatPending)}</div><div class="msg assistant"><span class="muted">Claude lit les données du terminal et réfléchit… (10 à 60 secondes)</span></div>`;
  if (!h) h = `<div class="muted small">${c.configured && c.sdk ? 'Pose ta première question : « pourquoi le BTC a perdu 2 % cet après-midi ? », « les shorts s\'accumulent sur SOL ? », « qu\'est-ce qui arrive cette semaine en macro ? »' :
    'Pour discuter avec Claude : <a href="#" data-open-settings>Réglages → 7. Discussion avec Claude</a> (clé API Anthropic, puis « Installer le module Claude »).'}</div>`;
  return h;
}
async function loadChat() {
  clearTimeout(chatTimer);
  if (st.tab !== 'chat' || st.page !== 'desk') return;
  try {
    const c = await api('/api/chat');
    const log = $('#chatLog'), atEnd = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    log.innerHTML = chatHtml(c);
    if (atEnd || chatPending) log.scrollTop = log.scrollHeight;
    $('#chatInfo').textContent = `${c.modelName} · ${num(c.spent, 2)} $ ce mois-ci${c.budget ? ' sur ' + num(c.budget, 0) + ' $' : ''}${c.telegramListening ? ' · Telegram actif' : c.telegramConfigured && c.configured ? ' · Telegram inactif' : ''}`;
  } catch (e) { $('#chatLog').innerHTML = `<div class="dn small">Discussion indisponible : ${esc(e.message)}</div>`; }
  chatTimer = setTimeout(loadChat, 15000);
}
$('#chatForm').addEventListener('submit', async e => {
  e.preventDefault();
  const q = $('#chatQ').value.trim();
  if (!q || chatPending) return;
  chatPending = q; $('#chatQ').value = ''; $('#chatSend').disabled = true; $('#chatRes').textContent = '';
  await loadChat();
  try {
    const r = await api('/api/chat', {question: q});
    $('#chatRes').className = r.ok ? 'muted small' : 'dn small';
    $('#chatRes').textContent = r.ok ? `répondu en ${num(r.seconds, 0)} s · ${num(r.usd, 3)} $` : r.answer;
  } catch (err) { $('#chatRes').className = 'dn small'; $('#chatRes').textContent = 'Erreur : ' + err.message; }
  chatPending = null; $('#chatSend').disabled = false;
  loadChat();
});
$('#chatQ').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#chatForm').requestSubmit(); } });
$('#chatReset').onclick = async () => { try { await api('/api/chat/reset', {}); } catch (e) { /* rien */ } loadChat(); };
$('#chatInstall').onclick = () => busy($('#chatInstall'), $('#chatInstallRes'), async () => {
  $('#chatInstallRes').textContent = 'installation (jusqu\'à une minute)…';
  const r = await api('/api/chat/install', {});
  $('#chatInstallRes').className = r.ok ? 'up' : 'dn';
  $('#chatInstallRes').textContent = (r.ok ? '✓ ' : '✗ ') + r.detail;
  $('#chatInstall').hidden = !!r.sdk;
});
// ---------- mise a jour automatique ----------
const sha7 = s => s ? String(s).slice(0, 7) : '?';
function renderUpdate(u) {
  if (!u) return;
  const i = u.installed || {}, l = u.latest;
  const when = t => t ? new Date(typeof t === 'number' ? t * 1000 : t).toLocaleString('fr-FR', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}) : '';
  $('#updState').textContent = u.error ? 'erreur' : u.state || '';
  $('#updState').className = u.error ? 'dn' : u.newer ? 'amb' : u.lastCheck ? 'up' : 'muted';
  const lines = [`Version installée : <b>${i.sha ? sha7(i.sha) : 'inconnue (installée à la main)'}</b>${i.message ? ' · ' + esc(i.message) : ''}${i.installedAt ? ' · le ' + when(i.installedAt) : ''}`];
  if (l) lines.push(`Dernière version publiée : <b>${sha7(l.sha)}</b> (${esc(l.branch || '')}) · ${esc(l.message || '')} · ${when(l.date)}`);
  if (u.lastCheck) lines.push(`Dernière vérification : ${when(u.lastCheck)} · état : ${esc(u.state || '')}`);
  if (u.error) lines.push(`<span class="dn">${esc(u.error)}</span>`);
  if (u.git) lines.push('Dossier géré par git : mets-le à jour avec « git pull » (la mise à jour automatique ne le touche pas).');
  if (!u.supervised) lines.push('Lancé sans la relance automatique : la nouvelle version s\'appliquera au prochain démarrage.');
  if (u.rolledBack) lines.push(`<span class="dn">La version ${sha7(u.rolledBack.sha)} s'est arrêtée en erreur au démarrage : l'ancienne a été remise en place.</span>`);
  if (u.launchers && u.launchers.length) lines.push('Nouveau lanceur disponible dans le dossier .update/lanceurs (à copier à la main, terminal fermé) : ' + u.launchers.map(esc).join(', '));
  $('#updInfo').innerHTML = lines.join('<br>');
}
$('#updCheck').onclick = () => busy($('#updCheck'), $('#updRes'), async () => {
  const u = await api('/api/update/check', {}); renderUpdate(u);
  $('#updRes').className = u.error ? 'dn' : 'up';
  $('#updRes').textContent = u.error ? '✗ ' + u.error : u.newer ? 'Nouvelle version disponible.' : '✓ Le terminal est à jour.';
});
$('#updApply').onclick = () => busy($('#updApply'), $('#updRes'), async () => {
  const u = await api('/api/update/apply', {}); renderUpdate(u);
  const res = u.result || {};
  $('#updRes').className = u.error ? 'dn' : 'up';
  $('#updRes').textContent = u.error ? '✗ ' + u.error : res.restart ? `✓ Installée (${(res.changed || []).length} fichiers) : redémarrage, la page va se recharger…` : '✓ Rien à installer : le terminal est à jour.';
});
async function updateNotice() {                                     // apres une mise a jour : un message, une seule fois par version
  try {
    const u = await api('/api/update'), j = u.justUpdated;
    let seen = ''; try { seen = localStorage.getItem('liqSeenUpdate') || ''; } catch (e) { /* stockage indisponible */ }
    if (j && j.sha && j.sha !== seen) {
      toast(`Terminal mis à jour (${sha7(j.sha)}) : ${j.message || 'nouvelle version'}`);
      try { localStorage.setItem('liqSeenUpdate', j.sha); } catch (e) { /* stockage indisponible */ }
    } else if (u.rolledBack && u.rolledBack.sha !== seen) {
      toast(`La nouvelle version (${sha7(u.rolledBack.sha)}) n'a pas démarré : l'ancienne a été remise en place.`);
      try { localStorage.setItem('liqSeenUpdate', u.rolledBack.sha); } catch (e) { /* stockage indisponible */ }
    }
  } catch (e) { /* ancien serveur */ }
}
const closeSettings = () => { M.hidden = true; };
$('#aMode').onchange = () => { $('#aExtra').hidden = $('#aMode').value !== 'all'; };
document.addEventListener('click', e => { if (e.target.closest('[data-open-settings]')) openSettings(); });
$('#openSettings').onclick = openSettings; $('#srcBadge').onclick = openSettings; $('#tgBadge').onclick = openSettings;
$('#closeSettings').onclick = closeSettings; $('#cancelSettings').onclick = closeSettings;
M.addEventListener('mousedown', e => { if (e.target === M) closeSettings(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !M.hidden) closeSettings(); });
async function busy(btn, out, fn) {
  btn.disabled = true; const old = out.textContent; out.className = 'muted'; out.textContent = 'en cours…';
  try { await fn(); } catch (e) { out.className = 'dn'; out.textContent = 'Erreur : ' + e.message; } finally { btn.disabled = false; if (out.textContent === 'en cours…') out.textContent = old; }
}
$('#testBinance').onclick = () => busy($('#testBinance'), $('#binanceRes'), async () => {
  const r = await api('/api/test/binance', {});
  const bad = r.results.filter(x => !x.ok && !/optionnel/.test(x.detail));
  $('#binanceList').innerHTML = r.results.map(x => `<div class="${x.ok ? 'up' : /optionnel/.test(x.detail) ? 'muted' : 'dn'}">${x.ok ? '✓' : '✗'} ${esc(x.name)} <span class="muted">${esc(x.detail)}</span></div>`).join('');
  $('#binanceRes').className = bad.length ? 'dn' : 'up';
  $('#binanceRes').textContent = bad.length ? 'Binance injoignable depuis ce PC (voir détail ; un VPN peut aider)' : 'Connexion OK : tu peux choisir Binance (réel).';
});
$('#findChat').onclick = () => busy($('#findChat'), $('#chatRes'), async () => {
  const r = await api('/api/telegram/chatid', {token: $('#tgToken').value.trim()});
  if (r.chats.length) { $('#tgChat').value = r.chats[0].id; $('#chatRes').className = 'up'; $('#chatRes').textContent = '✓ trouvé : ' + r.chats.map(c => c.name || c.id).join(', '); }
  else { $('#chatRes').className = 'dn'; $('#chatRes').textContent = r.detail; }
});
$('#testTg').onclick = () => busy($('#testTg'), $('#tgRes'), async () => {
  const r = await api('/api/test/telegram', {token: $('#tgToken').value.trim(), chatId: $('#tgChat').value.trim()});
  $('#tgRes').className = r.ok ? 'up' : 'dn';
  $('#tgRes').textContent = r.ok ? '✓ message envoyé : regarde Telegram' : '✗ ' + r.detail;
});
$('#testX').onclick = () => busy($('#testX'), $('#xRes'), async () => {
  const r = await api('/api/test/x', {token: $('#xToken').value.trim(), handle: $('#xAccounts').value});
  $('#xRes').className = r.ok ? 'up' : 'dn';
  $('#xRes').textContent = (r.ok ? '✓ ' : '✗ ') + r.detail;
});
$('#saveSettings').onclick = () => busy($('#saveSettings'), $('#saveRes'), async () => {
  const src = (document.querySelector('input[name=source]:checked') || {}).value;
  const before = st.cfg ? st.cfg.source + '|' + st.cfg.symbols.join(',') + '|' + (st.cfg.historyYears || 0) : '';
  const body = {source: src, symbols: $('#symbols').value.split(/[\s,;]+/).filter(Boolean), telegramChatId: $('#tgChat').value.trim(),
    alertMinScore: +$('#aScore').value, alertTf: $('#aTf').value, alertCooldownHours: +$('#aCool').value, alertSweep: $('#aSweep').checked, alertMode: $('#aMode').value, alertZones: $('#aZones').checked, alertMacro: $('#aMacro').checked, historyYears: +$('#histYears').value,
    xOn: $('#xOn').checked, xAccounts: $('#xAccounts').value, xPosts: +$('#xPosts').value,
    signalOn: $('#sOn').checked, signalMinScore: +$('#sMin').value, signalMaxWeek: +$('#sMax').value, signalMaxPerSymbol: +$('#sMaxSym').value, signalLeverage: +$('#sLev').value, signalTrendGate: $('#sTrend').checked, signalDirection: $('#sDir').value};
  if ($('#tgToken').value.trim()) body.telegramToken = $('#tgToken').value.trim();
  if ($('#xToken').value.trim()) body.xToken = $('#xToken').value.trim();
  if ($('#chatModel').value) body.chatModel = $('#chatModel').value;
  body.chatWeb = $('#chatWeb').checked; body.chatTelegram = $('#chatTg').checked; body.chatBudget = +$('#chatBudget').value || 0;
  if ($('#chatKey').value.trim()) body.chatKey = $('#chatKey').value.trim();
  body.updateAuto = $('#updAuto').checked; body.updateBranch = $('#updBranch').value.trim() || 'auto';
  if ($('#updToken').value.trim()) body.updateToken = $('#updToken').value.trim();
  await api('/api/settings', body);
  buildControls(await api('/api/config'));
  const reloaded = before !== st.cfg.source + '|' + st.cfg.symbols.join(',') + '|' + (st.cfg.historyYears || 0);
  closeSettings();
  if (reloaded) { st.data = null; st.key = null; st.sel = null; }
  toast(reloaded ? (st.cfg.source === 'binance' ? 'Enregistré. Chargement des vraies données Binance (1 à 2 min)…' : 'Enregistré. Rechargement des données…') : 'Réglages enregistrés.');
  poll(); renderAlerts(); pollSignals();
});


function loop() {
  if (st.data) { panels.forEach(p => p.tick()); liveRender(); }
  requestAnimationFrame(loop);
}
let ovTimer = null;
async function pollOverview() {
  clearTimeout(ovTimer);
  if (st.page !== 'overview') return;
  ovTimer = setTimeout(pollOverview, 6000);
  try { Overview.render(await api('/api/overview')); } catch (e) { $('#overview').innerHTML = `<div class="dn">Vue d'ensemble indisponible : ${esc(e.message)}</div>`; }
}
function openSymbol(sym, page) {
  if (st.cfg && st.cfg.symbols.includes(sym) && sym !== st.symbol) {
    st.symbol = sym; $('#symbol').value = sym; resetSymbolData(); liveConnect(); cbConnect(); poll(); pollAnalysis(); refreshAll(); reloadSideTab(); MTF.refresh(); TPO.refresh();
  }
  location.hash = page === 'analysis' ? '#/analysis/synth' : '#/desk';
}
(async () => {
  loadPrefs();
  let cfg;
  try { cfg = await api('/api/config'); } catch (e) { $('#status').textContent = 'terminal injoignable'; return; }
  window.LT = {serverNow: () => Date.now() + (st.clockOff || 0), st, api, fmtP, fmtPct, num, sPct, pr, edgeOf, edgeChip, TF_SEC, rgba, COL_L, COL_S, byId, ladderZones, essentialZones, shownZones,
    shownPools, impOf, fmtQty, fmtUsdShort, pollFlow, openTf, levelColor, livePrice, placeLabels, usdFmt, biasHtml, againstBias, parisAt, select, savePrefs, syncAllTools, refreshAll, maximize, pollHeat, PER, openSymbol, setPlan, updatePlan};
  Overview.init(window.LT);
  Signals.init(window.LT);
  Backtest.init(window.LT);
  History.init(window.LT);
  Strategy.init(window.LT);
  Lecture.init(window.LT);
  document.body.classList.toggle('theme-nuit', st.theme === 'nuit');
  createPanels();
  buildControls(cfg);
  applyTheme();
  $('#themeBtn').onclick = () => { st.theme = st.theme === 'nuit' ? 'classique' : 'nuit'; savePrefs(); applyTheme(); };
  pollFlow();
  Analysis.init(window.LT);
  renderLqLegend(); applySidebar(); applyLayout();
  applyExpert();
  try { const t = localStorage.getItem('liqTab'); showPane((['lecture', 'signals', 'levels', 'mine', 'chat'].includes(t) || (st.expert && EXPERT_TABS.includes(t))) ? t : 'lecture'); } catch (err) { showPane('lecture'); }
  $('#navSettings').onclick = e => { e.preventDefault(); openSettings(); };
  routeFromHash();
  poll(); pollAnalysis(); pollSignals(); renderAlerts(); setInterval(renderAlerts, 15000); requestAnimationFrame(loop); setTimeout(updateNotice, 2500);
  setInterval(() => {
    livePoll(); liveBadge(); cbRender(); riskChip();
    const lb = $('#liveBadge'), sb = $('#sbLive'); sb.hidden = lb.hidden; sb.textContent = lb.textContent; sb.className = lb.className;
  }, 1000);
  window.__term = {st, panels, select, openSettings, live, cb, Analysis, Signals, navigate, maximize, applyLayout, pollSignals};      // pour les tests automatiques
})();
})();
