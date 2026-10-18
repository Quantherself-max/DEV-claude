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
// Idées en cours (V25.2) : une idée dans l'autre sens arrive en couverture (la première reste ouverte), sauf réglage « une seule direction à la fois ».
const PARIS_DT = new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
const parisAt = ms => ms == null || !isFinite(ms) ? '-' : PARIS_DT.format(new Date(ms)).replace(',', '');      // une date absente ne casse jamais l'affichage
const sideName = o => `${o.side === 'long' ? 'achat' : 'vente'} ${o.symbol.replace('USDT', '')}`;
function biasHtml(b) {
  if (!b) return '<span class="lt">Biais du terminal</span> <b class="muted">AUCUN</b> <span class="muted small">pas d\'idée en cours : la prochaine peut être un achat ou une vente</span>';
  const open = b.open || [], names = [...new Set(open.map(sideName))];
  if (b.mixed) return `<span class="lt">Biais du terminal</span> <b class="amb">COUVERT</b> <span class="muted small">${names.join(', ')} en cours en même temps : chaque idée garde son stop et ses objectifs</span>`;
  const buy = b.side === 'long', plural = open.length > 1;
  const since = plural ? `(la plus récente depuis le ${parisAt(b.created)})` : `depuis le ${parisAt(b.created)}`;
  const rest = b.mode === 'never'
    ? `aucune idée ${buy ? 'de vente' : 'd\'achat'}, sur aucune paire, tant qu${plural ? '\'elles ne sont pas terminées' : '\'elle n\'est pas terminée'}`
    : `${buy ? 'une vente' : 'un achat'} peut quand même arriver, en couverture, sans ${plural ? 'les ' : 'l\''}annuler`;
  return `<span class="lt">Biais du terminal</span> <b class="${buy ? 'up' : 'dn'}">${buy ? 'ACHAT' : 'VENTE'}</b> <span class="muted small">${names.join(', ')} en cours ${since} · ${rest}</span>`;
}
// Une idée face aux idées en cours : null si rien n'est en cours dans l'autre sens ; sinon bloquée (réglage) ou envoyée en couverture.
function oppOf(b, side) {
  if (!b || !side) return null;
  const opp = (b.open || []).filter(o => o.side && o.side !== side);
  if (!opp.length) return null;
  const names = [...new Set(opp.map(o => (o.side === 'long' ? 'l\'achat ' : 'la vente ') + o.symbol.replace('USDT', '')))].join(' et ');
  return b.mode === 'never' ? {blocked: true, names, text: `bloquée : contredirait ${names} en cours`}
    : {blocked: false, names, text: `couverture de ${names} en cours, sans ${opp.length > 1 ? 'les ' : 'l\''}annuler`};
}
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
  if (/^Single prints/.test(name)) return 'Single prints (TPO) : prix touchés par une seule tranche de temps de la séance (4 heures pour la semaine, 1 jour pour le mois), au milieu du profil. Le prix y est passé vite, sans s\'y arrêter ; zone non comblée depuis. Mesuré sur le bitcoin : pas un aimant (le prix y revient plutôt MOINS souvent qu\'à un prix comparable) et, au retour, elles ne tiennent pas mieux qu\'un autre prix. Elles signalent un mouvement convaincu.';
  if (/^Poor (high|low)/.test(name)) return 'Poor high / poor low (TPO) : le plus haut (ou le plus bas) de la séance a été touché par au moins deux tranches de temps, sans queue : enchère mal terminée, pas encore dépassée. Mesuré : plus souvent dépassés qu\'un extrême avec queue sur 1 jour, 4 heures et 1 heure ; pas d\'effet démontré sur la semaine et le mois.';
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
  layout: 'main', prevLayout: null, sideOpen: true, sbCollapsed: false, ws: {}, instTab: null, minGrade: 9, heatEx: ['binance', 'okx', 'bybit', 'coinbase'], bookHeat: null, liqMap: null, ind: null,
  page: 'desk', sub: 'synth', planOn: true, planKey: null, plans: [], planHide: [], planShow: [], planSig: '', sig: null,
  theme: 'nuit', mainOpts: {sess: true, sessW: false, sessM: false, nodes: true, dpoc: true, npoc: true, tpoM: true, tpoW: true, tpoD: true, tpo4: false, tpo1: false, vwap: true, dom: false, big: true, bigMin: 2, bigLabels: 'top', absorb: true, absorbMode: 'fortes', gex: true,
    vwapW: false, vwapM: false, vwapY: false, avwap: false, vol: true, heat: false, liqmap: false, oi: false, delta: false, deltaCvd: true, zones: true}, flow: null,
  mtf: {n: 4, tfs: ['5m', '15m', '1h', '4h', '1d']}, tpoKinds: {M: true, W: true, D: true, '4h': false, '1h': false},
  tpoOpts: {mode: 'auto', fine: false, vol: true, comp: true, naked: true, ib: true}};
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
// V28 : seules les zones dont la note sur 14 atteint le seuil choisi (9 par défaut), quand l'élément « Confluences » est affiché
const shownZones = d => st.mainOpts.zones ? (d.zones || []).filter(z => (z.grade || 0) >= (st.minGrade || 9)) : [];
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
// V28 : main = Graphique (épuré), blank = Vierge, heat = Heatmap du carnet ; les trois sont le graphique principal avec SES éléments (desk.js) ;
// 3 = Grille (principal + liquidité + VWAP·VP) ; pair = onglet « BTC + SOL » (deux instruments côte à côte, setups liés)
const LAYOUTS = {main: ['main'], blank: ['main'], heat: ['main'], '1': ['main'], liq: ['liq'], vp: ['vp'], '2': ['main', 'liq'], '3': ['main', 'liq', 'vp'], mtf: [], tpo: [], pair: []};
const needs = k => (LAYOUTS[st.layout] || LAYOUTS.main).includes(k) && st.page === 'desk';
function savePrefs() {
  try { localStorage.setItem('liqPrefs', JSON.stringify({mode: st.mode, pools: st.pools, ppools: st.ppools, liqOpts: st.liqOpts, vpOpts: st.vpOpts, layout: st.layout, side: st.sideOpen, sb: st.sbCollapsed, plan: st.planOn, planHide: st.planHide.slice(-80), planShow: st.planShow.slice(-80), expert: st.expert, theme: st.theme, mainOpts: st.mainOpts, mtf: st.mtf, tpoKinds: st.tpoKinds, tpoOpts: st.tpoOpts, ws: st.ws, instTab: st.instTab, v: 28})); } catch (e) { /* stockage indisponible */ }
}
function loadPrefs() {
  try {
    const p = JSON.parse(localStorage.getItem('liqPrefs') || '{}');
    if (['ess', 'conf', 'all'].includes(p.mode)) st.mode = p.mode;
    if (typeof p.pools === 'boolean') st.pools = p.pools;
    if (typeof p.ppools === 'boolean') st.ppools = p.ppools;
    Object.assign(st.liqOpts, p.liqOpts || {}); Object.assign(st.vpOpts, p.vpOpts || {});
    if (LAYOUTS[p.layout]) st.layout = p.layout === '1' ? 'main' : p.layout;
    // V28 : un espace par instrument (vue et éléments de chaque vue) ; les réglages d'avant la V28 (graphique chargé) ne sont pas repris : épuré
    if (p.v >= 28 && p.ws && typeof p.ws === 'object') st.ws = p.ws;
    else st.layout = 'main';
    if (typeof p.instTab === 'string') st.instTab = p.instTab;
    if (typeof p.side === 'boolean') st.sideOpen = p.side;
    if (typeof p.sb === 'boolean') st.sbCollapsed = p.sb;
    if (typeof p.plan === 'boolean') st.planOn = p.plan;
    if (Array.isArray(p.planHide)) st.planHide = p.planHide.filter(x => typeof x === 'string');
    if (Array.isArray(p.planShow)) st.planShow = p.planShow.filter(x => typeof x === 'string');
    if (typeof p.expert === 'boolean') st.expert = p.expert;
    if (['nuit', 'classique'].includes(p.theme)) st.theme = p.theme;
    // V20 : TPO semaine et mois. Preferences enregistrees avant (sans semaine / mois) : semaine et mois affiches, 4 h et 1 h retires des
    // graphiques et de la vue TPO (les single prints de haute unite de temps sont moins nombreuses et plus lisibles) ; tout reste reglable.
    const v20 = p.mainOpts && typeof p.mainOpts.tpoW !== 'boolean';
    Object.assign(st.mainOpts, p.mainOpts || {});
    if (v20) Object.assign(st.mainOpts, {tpoM: true, tpoW: true, tpo4: false, tpo1: false});
    if (p.tpoOpts && typeof p.tpoOpts === 'object') Object.keys(st.tpoOpts).forEach(k => { if (typeof p.tpoOpts[k] === typeof st.tpoOpts[k]) st.tpoOpts[k] = p.tpoOpts[k]; });
    if (p.tpoKinds && typeof p.tpoKinds === 'object' && typeof p.tpoKinds.W === 'boolean') ['M', 'W', 'D', '4h', '1h'].forEach(k => { if (typeof p.tpoKinds[k] === 'boolean') st.tpoKinds[k] = p.tpoKinds[k]; });
    else if (p.tpoKinds && typeof p.tpoKinds === 'object' && typeof p.tpoKinds.D === 'boolean') st.tpoKinds.D = p.tpoKinds.D;
    if (p.mtf && Array.isArray(p.mtf.tfs)) st.mtf = {n: Math.max(2, Math.min(5, +p.mtf.n || 4)), tfs: p.mtf.tfs.slice(0, 5)};
  } catch (e) { /* preferences illisibles : valeurs par defaut */ }
}
function syncAllTools() { panels.forEach(p => p.syncTools()); }
const needsSeries = () => needs('vp') || st.tab === 'vp' || (needs('main') && ['vwap', 'vwapW', 'vwapM', 'vwapY', 'avwap'].some(k => st.mainOpts[k]));
function refreshAll() { panels.forEach(p => { p.stamp = ''; p.rebuildLines(); }); st.version++; if (needs('liq')) { pollHeat(); pollLiqs(); } if (needsSeries()) pollVP(); }
function syncRange() {
  const first = panels.find(p => p.visible()); if (!first) return;
  const r = first.chart.timeScale().getVisibleLogicalRange(); if (!r) return;
  panels.forEach(p => { if (p !== first && p.visible()) p.chart.timeScale().setVisibleLogicalRange(r); });
}
function applyLayout() {
  const heatOk = !st.cfg || (st.cfg.heatmapSymbols || ['BTCUSDT']).includes(st.symbol);
  if (st.layout === 'heat' && !heatOk) st.layout = 'main';
  if (st.layout === 'pair' && st.instTab !== 'PAIR') st.layout = 'main';
  if (!LAYOUTS[st.layout]) st.layout = 'main';
  const want = LAYOUTS[st.layout];
  $('#desk').className = 'l' + st.layout;
  Desk.apply();
  panels.forEach(p => p.host.classList.toggle('hide', !want.includes(p.kind)));
  const g = $('#mtfGrid');                                              // V16 : grille multi-unites ; V28 : aussi l'onglet « BTC + SOL »
  if (g) {
    const on = st.layout === 'mtf' || st.layout === 'pair';
    g.classList.toggle('hide', !on);
    if (on && st.page === 'desk') { if (st.layout === 'pair') MTF.showPair(st.cfg ? st.cfg.symbols.slice(0, 2) : []); else MTF.show(); } else MTF.hide();
  }
  const hb = document.querySelector('#layouts [data-layout="heat"]'); if (hb) hb.hidden = !heatOk;
  $('#layouts').hidden = st.layout === 'pair';
  document.body.classList.toggle('pairmode', st.layout === 'pair');
  const pl = $('#pairHint'); if (pl) pl.hidden = st.layout !== 'pair';
  Desk.renderTabs(); Desk.renderLegend(); setTimeout(() => Desk.pollHeat(true), 300);
  const tg = $('#tpoGrid');                                             // V17 : vue TPO
  if (tg) { tg.classList.toggle('hide', st.layout !== 'tpo'); if (st.layout === 'tpo' && st.page === 'desk') TPO.show(); else TPO.hide(); }
  document.querySelectorAll('#layouts button').forEach(b => b.classList.toggle('on', b.dataset.layout === st.layout || (b.dataset.layout === 'main' && st.layout === '1')));
  $('#deskwrap').classList.toggle('noside', !st.sideOpen);
  $('#sideToggle').textContent = st.sideOpen ? 'Panneau ▸' : '◂ Panneau';
  setTimeout(() => { panels.forEach(p => p.visible() && p.resetView()); st.version++; refreshAll(); }, 90);
  savePrefs();
}
function maximize(kind) {
  const solo = kind === 'main' ? 'main' : kind;
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
  const g = z.grade != null ? z.grade : z.score, dots = `<b title="Note sur 14 : ${esc((z.gradeParts || []).map(p => p.name + ' ' + p.pts).join(', '))}">${g}/14</b>`;
  const sel = st.sel && st.sel.type === 'zone' && st.sel.id === z.id ? ' sel' : '';
  const ess = (z.grade || 0) >= (st.minGrade || 9);                                     // V28 : dessinée sur le graphique (note au moins égale au seuil)
  return `<div class="row${ess ? '' : ' weak'}${sel}" data-zone="${z.id}">${ar}<span class="nm" title="${esc(names.join(' + '))}">${ess ? '<b class="amb" title="Note au moins égale au seuil : dessinée sur le graphique">★</b> ' : ''}${esc(names.join(' + '))}</span>` +
    `<span class="pv" title="${z.key != null ? `prix clé (médiane pondérée des niveaux) ${fmtP(z.key)} · cœur ${fmtP(z.core[0])} – ${fmtP(z.core[1])}` + (z.vpoc ? ` · prix le plus échangé ${fmtP(z.vpoc)}` : '') : ''}">${fmtP(z.key != null ? z.key : z.mid)}</span><span class="sub"><span data-zd="${z.id}">${zoneDist(z, d, livePrice(d))}</span><span class="dots">${dots}</span>${z.hasMagnet ? ' · plus grosse poche' : ''}` +
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
  $('#confHint').textContent = `${d.zones.length} zones · note sur 14 · ★ = dessinée (au moins ${st.minGrade || 9}/14)`;
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
    const PREC = {fine: 'précise', moyenne: 'moyenne', large: 'large'};
    const precHtml = z.key != null ? `<div class="sect">Où agir dans la zone</div><table class="t">` +
      `<tr><td>Prix clé <span class="muted small">(médiane des niveaux, chacun pesé selon son échelle de temps)</span></td><td class="r"><b>${fmtP(z.key)}</b></td></tr>` +
      `<tr><td>Cœur <span class="muted small">(la moitié centrale du poids des niveaux)</span></td><td class="r">${fmtP(z.core[0])} – ${fmtP(z.core[1])}</td></tr>` +
      (z.vpoc ? `<tr><td>Prix le plus échangé <span class="muted small">(14 derniers jours, bougies 5 min)</span></td><td class="r">${fmtP(z.vpoc)}</td></tr>` : '') +
      `<tr><td>Largeur <span class="muted small">(toute la zone / cœur)</span></td><td class="r">${num(z.widthAtr, 2)} / ${num(z.coreAtr, 2)} ATR · ${PREC[z.precision] || '—'}</td></tr></table>` : '';
    el.innerHTML = `<div><b>${ar} Confluence ${fmtP(z.key != null ? z.key : z.mid)}</b> <span class="muted">${z.side === 'in' ? '' : fmtPct(z.distPct) + ' · ' + num(z.distAtr, 1) + ' ATR · '}note <b>${z.grade != null ? z.grade : z.score}/14</b></span></div>` +
      ((z.gradeParts || []).length ? `<div class="gparts">${z.gradeParts.map(p => `<span class="pill" title="${esc((p.what || []).join(', '))}">${esc(p.name)} ${p.pts}/2</span>`).join(' ')}</div>` : '') +
      `<table class="mem">${rows}</table>` + precHtml +
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
const NEED_API = 31;                                                   // adresses /api attendues par ces pages (V17 : /api/tpo, V18 : /api/macroweek, V19 : TPO enrichi, V20 : TPO semaine et mois, V21 : absorptions, V24 : fiche détaillée des idées /api/history/trade, V24.2 : diagnostic Telegram /api/telegram/diagnose, V25 : /api/macromonth, V25.1 et V25.2 : idées dans l'autre sens et leur réglage, V25.3 : état d'envoi de chaque configuration, V26 : gamma des options BTC, V28 : heatmap du carnet /api/heatmap)
const LAUNCHER = /Mac/.test(navigator.platform || navigator.userAgent) ? 'Lancer-Terminal-Mac.command' : 'Lancer-Terminal-Windows.bat';
const serverOld = () => !!st.cfg && !(st.cfg.api >= NEED_API);
function updateBanner(d) {
  const c = st.cfg;
  if (!c) return;
  if (serverOld()) banner('bad', `<span>⚠ Le <b>programme</b> du terminal qui tourne sur ton PC est une <b>ancienne version</b> : les nouvelles pages sont arrivées, mais pas le moteur (la vue TPO et le bilan macro, entre autres, ne peuvent pas marcher). ` +
    `<b>Ferme la fenêtre noire « Liq Terminal »</b> (ou Ctrl+C dedans), puis relance <b>${LAUNCHER}</b>.</span>`);
  else if (st.stale) banner(c.supervised ? 'warn' : 'bad', c.supervised ? '<span>Nouvelle version copiée dans le dossier du terminal : redémarrage automatique en cours…</span>'
    : `<span>⚠ Une <b>nouvelle version</b> a été copiée dans le dossier du terminal : <b>ferme la fenêtre noire « Liq Terminal »</b> puis relance <b>${LAUNCHER}</b> pour l'utiliser.</span>`);
  else if (d && d.error && d.source !== 'simulated') banner('bad', `<span>Problème de données Binance : ${esc(d.error)}</span><button data-open-settings>Tester la connexion</button>`);
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
  const tb = $('#tgBadge'), ts = (st.cfg && st.cfg.telegramState) || {};
  tb.textContent = ts.error ? 'TELEGRAM ERREUR' : st.cfg && st.cfg.telegram ? 'TELEGRAM ON' : 'TELEGRAM OFF';
  tb.className = 'badge ' + (ts.error ? 'bad' : st.cfg && st.cfg.telegram ? 'ok' : '');
  tb.title = (ts.reason || 'Configurer Telegram dans les réglages') + ' — clique pour le diagnostic.';
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
  Desk.renderLegend();
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
    st.stale = r.headers.get('X-Terminal-Stale') === '1';             // V17.1 : nouvelle version copiee, ancien programme encore lance
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
// unité de temps du graphique ; V28 : retenue par la vue en cours (la Heatmap garde ses 5 minutes, le Graphique son heure)
function setTf(tf) {
  if (!st.cfg || !st.cfg.tfs.includes(tf)) return;
  const changed = tf !== st.tf;
  st.tf = tf; Desk.rememberTf(tf);
  document.querySelectorAll('#tfs button').forEach(x => x.classList.toggle('on', x.dataset.tf === tf));
  if (!changed) return;
  st.sel = null; st.data = null; st.series = null; st.vpd = null; st.bookHeat = null; st.liqMap = null; st.ind = null; poll(); refreshAll();
}
function resetSymbolData() {
  st.flow = null;
  st.sel = null; st.data = null; st.heat = null; st.liqs = null; st.an = null; st.series = null; st.vpd = null; st.key = null; st.sig = null; st.planKey = null; st.planSig = ''; st.plans = [];
  st.bookHeat = null; st.liqMap = null; st.ind = null;
}
function buildControls(cfg) {
  st.cfg = cfg;
  if (!st.symbol && st.instTab && cfg.symbols.includes(st.instTab)) st.symbol = st.instTab;     // V28 : on reprend sur l'onglet d'instrument quitté
  if (!cfg.symbols.includes(st.symbol)) st.symbol = cfg.symbols[0];
  const sel = $('#symbol'); sel.innerHTML = cfg.symbols.map(s => `<option${s === st.symbol ? ' selected' : ''}>${s}</option>`).join('');
  sel.onchange = () => {
    st.symbol = sel.value; st.instTab = st.symbol; st.layout = Desk.wsOf(st.symbol).layout || 'main';      // V28 : chaque instrument garde sa vue
    resetSymbolData(); Desk.apply(); applyLayout(); liveConnect(); cbConnect(); poll(); pollAnalysis(); refreshAll(); pollOverview(); pollSignals(); reloadSideTab(); MTF.refresh(); TPO.refresh();
  };
  if (!st.instTab || (st.instTab !== 'PAIR' && !cfg.symbols.includes(st.instTab))) st.instTab = st.symbol;
  st.layout = st.instTab === 'PAIR' && cfg.symbols.length >= 2 ? 'pair' : (Desk.wsOf(st.symbol).layout || 'main');
  const vt = Desk.VIEWS[st.layout] ? Desk.curSet().tf : null;                    // la vue reprend son unité de temps
  if (vt && cfg.tfs.includes(vt)) st.tf = vt;
  Desk.renderTabs();
  const box = $('#tfs');
  box.innerHTML = cfg.tfs.map(t => `<button data-tf="${t}" class="${t === st.tf ? 'on' : ''}">${t}</button>`).join('');
  box.onclick = e => { const b = e.target.closest('button'); if (b) setTf(b.dataset.tf); };
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
  if (name === 'mine') Strategy.show();
  if (name === 'lecture') Lecture.show();
}
// onglets detailles (contexte, stats, liquidite, profils, alertes) : caches par defaut, un bouton les affiche
function reloadSideTab() { if (st.tab === 'lecture') Lecture.show(); else if (st.tab === 'mine') Strategy.show(); }
const EXPERT_TABS = ['context', 'stats', 'liquidity', 'vp', 'alerts'];
function applyExpert() {
  document.querySelectorAll('#tabs button[data-expert], #sidebar a[data-expert], #anTabs button[data-expert]').forEach(b => { b.hidden = !st.expert; });
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
const PAGES = {desk: 'Desk', overview: 'Overview', signals: 'Idées de trade', history: 'Historique', backtest: 'Backtest', analysis: 'Analyse'};
const SUBS = {macro: 'Macro', synth: 'Biais & probabilités', dom: 'Dominance BTC / alts'};
const OLD_SUBS = {week: 'macro', month: 'macro', plan: 'macro', lex: 'macro'};            // V27 : anciennes pages (favoris) -> Macro
function navigate(page, sub) {
  if (!PAGES[page]) page = 'desk';
  st.page = page;
  if (page === 'analysis') st.sub = SUBS[sub] ? sub : OLD_SUBS[sub] || (SUBS[st.sub] ? st.sub : 'macro');
  document.querySelectorAll('.page').forEach(p => p.hidden = p.dataset.page !== page);
  document.querySelectorAll('#sidebar a[data-nav]').forEach(a => a.classList.toggle('on', a.dataset.nav === page && (page !== 'analysis' || a.dataset.sub === st.sub)));
  $('#crumb').textContent = page === 'analysis' ? SUBS[st.sub] : PAGES[page];
  if (page === 'analysis') Analysis.show(st.sub); else Macro.hide();
  if (page === 'signals') { pollSignals(); if (st.sig) Signals.render(st.sig); }
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
  if (m) navigate(m[1], m[2]);
  else { let saved = null; try { saved = localStorage.getItem('liqPage'); } catch (e) { /* rien */ } const q = (saved || 'desk').split('/'); navigate(q[0], q[1]); }
}
window.addEventListener('hashchange', routeFromHash);
function applySidebar() { document.body.classList.toggle('sbmin', st.sbCollapsed); $('#sbToggle').textContent = st.sbCollapsed ? '»' : '«'; }
$('#sbToggle').onclick = () => { st.sbCollapsed = !st.sbCollapsed; applySidebar(); savePrefs(); setTimeout(() => { st.version++; }, 250); };
$('#layouts').onclick = e => { const b = e.target.closest('button[data-layout]'); if (b) { Desk.rememberTf(st.tf); st.layout = b.dataset.layout; Desk.onLayout(st.layout); applyLayout(); } };
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
  if (!st.cfg || !needs('main') || !(o.dom || o.big || o.absorb) || !main || !main.visible() || document.hidden) { flowTimer = setTimeout(pollFlow, 1500); return; }
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
  const exTxt = x => x == null ? '' : x >= 0.995 ? '<span class="up" title="Calculé sur chaque transaction de Binance : volume au prix près">◆ exact</span>'
    : x > 0.005 ? `<span title="Part du volume calculée sur chaque transaction ; le reste est réparti d'après les bougies">◆ ${Math.round(x * 100)} %</span>` : '<span class="muted" title="Réparti d\'après les bougies (transactions pas encore téléchargées pour cette période)">estimé</span>';
  el.innerHTML = V.profiles.length ? `<table class="t"><tr><th>Profil</th><th>Fenêtre</th><th class="r">POC</th><th class="r">VAH</th><th class="r">VAL</th><th class="r">Précision</th></tr>` +
    V.profiles.map(p => `<tr data-vpf="${esc(p.id)}" class="${p.id === st.vpFocus ? 'hl' : ''}" style="cursor:pointer" title="Afficher l'histogramme de ce profil"><td><span class="chip" style="background:#4c8dff"></span>${esc(p.label)}</td>` +
      `<td class="muted small">${dt(p.t0)} → ${dt(p.t1)}</td><td class="r">${fmtP(p.poc)}</td><td class="r">${fmtP(p.vah)}</td><td class="r">${fmtP(p.val)}</td><td class="r small">${exTxt(p.exact)}</td></tr>`).join('') + `</table>` :
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
  el.title = 'Annonce majeure : ouvre la page Macro';
}
$('#riskChip').onclick = () => { location.hash = '#/analysis/macro'; };

// ---------- idees de trade ----------
let sigTimer = null;
// V25.3 : sur le graphique, les idées ENVOYÉES (niveaux figés, à partir de la bougie où elles sont parties) ; la configuration du moment
// (recalculée sans cesse, donc mobile) n'apparaît que si tu la demandes, marquée « pas envoyée ».
const OPEN_ST = ['pending', 'active', 'tp1'], RECENT_MS = 2 * 3600e3;
// V26 : chaque trait se masque ou se réaffiche, idée par idée (choix gardé). V28 (moins de bruit) : par défaut, seulement les idées en
// cours, et celles exécutées puis terminées depuis moins de 2 heures (pour voir leur résultat) ; un ordre jamais exécuté disparaît dès
// qu'il expire. Toute idée se réaffiche à la demande (élément « Idées envoyées » du menu « ＋ Éléments »).
function planVisible(t, now = Date.now()) {
  if (st.planHide.includes(t.id)) return false;
  return st.planShow.includes(t.id) || OPEN_ST.includes(t.status) || (!!t.filledAt && (t.endAt || t.closedAt || 0) > now - RECENT_MS);
}
function activePlans() {
  const sig = st.sig, sg = sig && sig.symbols && sig.symbols[st.symbol];
  if (!st.planOn || !sig || !sig.desk) return [];
  const now = Date.now();
  const plans = (sig.desk.trades || []).filter(t => t.symbol === st.symbol && t.mode !== 'alerte' && planVisible(t, now))
    .slice(0, 8).map(t => ({kind: 'sent', key: t.id, symbol: t.symbol, side: t.side, entry: t.entry, stop: t.stop, tp1: t.tp1, tp2: t.tp2, score: t.score,
      created: t.created, n: t.n, status: t.status, result: t.result, end: t.status === 'closed' ? (t.endAt || t.closedAt) : null, sentOk: t.sent !== false}));
  if (st.planKey && sg && sg.ready) {
    const i = sg.ideas.find(x => x.key === st.planKey);
    if (i && !(i.send && i.send.state === 'sent' && plans.some(p => p.key === i.send.id)))
      plans.push({kind: 'live', key: i.key, symbol: st.symbol, side: i.side, entry: i.entry, stop: i.stop, tp1: i.tp1, tp2: i.tp2, score: i.score,
        why: i.send && i.send.text, state: i.send && i.send.state});
  }
  return plans;
}
function updatePlan() {
  const ps = activePlans(), k = ps.map(p => [p.key, p.kind, p.status, p.entry, p.stop, p.tp1, p.tp2].join()).join('|');
  if (k !== st.planSig) { st.planSig = k; st.plans = ps; st.version++; panels.forEach(x => x.sig = ''); syncAllTools(); }
}
function togglePlan(id) {                                              // idée envoyée : masquer si elle est dessinée, sinon l'afficher
  const t = ((st.sig && st.sig.desk && st.sig.desk.trades) || []).find(x => x.id === id);
  const shown = st.planOn && t && planVisible(t);
  st.planHide = st.planHide.filter(x => x !== id); st.planShow = st.planShow.filter(x => x !== id);
  (shown ? st.planHide : st.planShow).push(id);
  if (!shown) st.planOn = true;
  savePrefs(); syncAllTools(); updatePlan();
}
function planReset() { st.planHide = []; st.planShow = []; st.planOn = true; savePrefs(); syncAllTools(); updatePlan(); }
function sigChip() {
  const el = $('#sigChip'), sg = st.sig && st.sig.symbols && st.sig.symbols[st.symbol];
  const open = st.sig && st.sig.desk && st.sig.desk.trades.find(t => t.symbol === st.symbol && t.mode !== 'alerte' && OPEN_ST.includes(t.status));
  const best = sg && sg.ready && sg.ideas.find(i => i.eligible && !(i.send && i.send.state === 'sent'));
  if (!best && !open) { el.hidden = true; return; }
  el.hidden = false;
  if (open) {                                                         // une idee envoyee en cours passe d'abord : c'est elle qui compte
    const buy = open.side === 'long';
    el.className = 'badge sig ' + (buy ? 'up' : 'dn');
    el.textContent = `🎯 ${buy ? 'Achat' : 'Vente'} envoyé${buy ? '' : 'e'} le ${parisAt(open.created)}`;
    el.title = `Idée envoyée sur Telegram le ${parisAt(open.created)} : entrée ${fmtP(open.entry)}, stop ${fmtP(open.stop)} (niveaux figés). Clique pour la suivre.`;
    return;
  }
  const buy = best.side === 'long', s = best.send || {};
  el.className = 'badge sig muted';
  el.textContent = `🔎 ${buy ? 'Achat' : 'Vente'} ${Math.round(best.score)}/100 · ${s.state === 'next' ? 'part dans un instant' : 'pas envoyée'}`;
  el.title = `Configuration du moment (recalculée en continu, ses niveaux bougent) : ${s.text || 'pas envoyée'}. Clique pour tout comprendre.`;
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
    if (st.page === 'signals' || st.page === 'desk') Signals.render(r);    // V30 : le panneau de droite du Desk montre les idées
  } catch (e) { /* le prochain passage reessaiera */ }
}
function setPlan(key) {                                               // 'off' : tout masquer ; 'on' : réafficher ; clé : configuration du moment ; null : la retirer
  if (key === 'off') st.planOn = false;
  else if (key === 'on') st.planOn = true;
  else { st.planKey = key; if (key) st.planOn = true; }
  savePrefs(); syncAllTools(); updatePlan();
}

// ---------- reglages ----------
const M = $('#modal');
// V23 : etat des transactions exactes (une ligne par paire)
function renderFpState(tr, source) {
  const el = $('#fpState');
  if (!el) return;
  if (source !== 'binance') { el.textContent = 'Disponible avec les vraies données Binance.'; return; }
  const rows = Object.values(tr || {});
  if (!rows.length) { el.textContent = 'Désactivé.'; return; }
  el.innerHTML = rows.map(t => {
    const base = String(t.symbol || '').replace(/USDT$/, '');
    const today = t.today != null ? Math.round(t.today * 100) + ' %' : '—';
    const err = t.error ? ` · <span class="dn">${String(t.error).replace(/[<>&]/g, '')}</span>` : '';
    return `<b>${base}</b> : ${t.complete}/${t.days} jours complets, aujourd'hui ${today}` +
      (t.current ? ` · téléchargement du ${t.current}` : '') + (t.behindSec != null && t.behindSec > 120 ? ` · rattrapage (${Math.round(t.behindSec / 60)} min de retard)` : '') +
      (t.step ? ` · pas de ${t.step} $${t.exactPrices ? ' (chaque prix exact)' : ''}` : '') + ` · ${t.mb || 0} Mo` + err;
  }).join('<br>');
}

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
    $('#fpDays').value = String(s.footprintDays ?? 62);
    renderFpState(s.trades, s.source);
    $('#tgToken').value = '';
    $('#tgToken').placeholder = s.telegram.tokenHint ? `token enregistré (${s.telegram.tokenHint}) : laisse vide pour le garder` : '123456789:AA...';
    $('#tgChat').value = s.telegram.chatId || '';
    $('#tgState').textContent = s.telegram.error ? '✗ envoi refusé' : s.telegram.configured ? '✓ configuré' : 'non configuré';
    $('#tgState').className = s.telegram.error ? 'dn' : s.telegram.configured ? 'up' : '';
    $('#tgFile').textContent = s.telegram.envFile ? 'Réglages enregistrés dans : ' + s.telegram.envFile : '';
    $('#tgDiag').innerHTML = '';
    $('#aScore').value = String(s.alertMinScore);
    $('#aTf').innerHTML = (st.cfg ? st.cfg.tfs : ['1h']).map(t => `<option${t === s.alertTf ? ' selected' : ''}>${t}</option>`).join('');
    $('#aCool').value = s.alertCooldownHours;
    $('#aSweep').checked = !!s.alertSweep;
    $('#aZones').checked = s.alertZones !== false;
    $('#mwTg').checked = !!s.macroWeekTelegram;
    $('#mmTg').checked = !!s.macroMonthTelegram;
    $('#aMode').value = s.alertMode === 'all' ? 'all' : 'ideas'; $('#aExtra').hidden = $('#aMode').value !== 'all';
    $('#aMacro').checked = s.alertMacro !== false;
    const x = s.x || {}; $('#xOn').checked = x.on !== false; $('#xAccounts').value = (x.accounts || []).join(', '); $('#xPosts').value = String(x.posts || 10);
    $('#xToken').value = ''; $('#xToken').placeholder = x.tokenHint ? `jeton enregistré (${x.tokenHint}) : laisse vide pour le garder` : 'Bearer token X (API officielle)'; $('#xRes').textContent = '';
    $('#sOn').checked = s.signalOn !== false; $('#sMin').value = s.signalMinScore; $('#sMax').value = s.signalMaxWeek; $('#sMaxSym').value = s.signalMaxPerSymbol; $('#sLev').value = s.signalLeverage; $('#sTrend').checked = s.signalTrendGate !== false; $('#sDir').value = s.signalDirection || 'both'; $('#sOpp').value = s.signalOpposite || 'hedge';
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
$('#openSettings').onclick = openSettings; $('#srcBadge').onclick = openSettings;
$('#tgBadge').onclick = async () => {                                     // V25 : le badge ouvre les reglages sur Telegram et lance le diagnostic
  await openSettings();
  const sec = $('#tgDiag'); if (sec) sec.closest('section').scrollIntoView({block: 'start'});
  diagTelegram();
};
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
  $('#tgRes').textContent = r.ok ? '✓ message envoyé : regarde Telegram' + (r.saved ? ' · token et chat id enregistrés' : '') : '✗ ' + r.detail;
  if (r.saved) { buildControls(await api('/api/config')); $('#tgState').textContent = '✓ configuré'; $('#tgState').className = 'up'; $('#tgToken').value = ''; }
});
// V25 : diagnostic pas a pas (fichier des reglages, token, conversation, lecture des messages, dernier envoi)
async function diagTelegram() {
  $('#tgDiag').innerHTML = '<li class="muted">Vérification…</li>';
  try {
    const r = await api('/api/telegram/diagnose', {token: $('#tgToken').value.trim(), chatId: $('#tgChat').value.trim()});
    $('#tgDiag').innerHTML = r.steps.map(x => `<li class="${x.ok === true ? 'up' : x.ok === false ? 'dn' : 'amb'}"><b>${x.ok === true ? '✓' : x.ok === false ? '✗' : '•'} ${esc(x.name)}</b> : ${esc(x.detail)}` +
      (x.fix ? `<div class="fix">${esc(x.fix)}</div>` : '') + '</li>').join('') +
      `<li class="${r.ok ? 'up' : 'dn'}"><b>${r.ok ? 'Tout est en ordre.' : 'Corrige le premier point en rouge, puis relance le diagnostic.'}</b></li>`;
  } catch (e) { $('#tgDiag').innerHTML = `<li class="dn">Diagnostic impossible : ${esc(e.message)}</li>`; }
}
$('#diagTg').onclick = diagTelegram;
$('#testX').onclick = () => busy($('#testX'), $('#xRes'), async () => {
  const r = await api('/api/test/x', {token: $('#xToken').value.trim(), handle: $('#xAccounts').value});
  $('#xRes').className = r.ok ? 'up' : 'dn';
  $('#xRes').textContent = (r.ok ? '✓ ' : '✗ ') + r.detail;
});
$('#saveSettings').onclick = () => busy($('#saveSettings'), $('#saveRes'), async () => {
  const src = (document.querySelector('input[name=source]:checked') || {}).value;
  const before = st.cfg ? st.cfg.source + '|' + st.cfg.symbols.join(',') + '|' + (st.cfg.historyYears || 0) : '';
  const body = {source: src, symbols: $('#symbols').value.split(/[\s,;]+/).filter(Boolean), telegramChatId: $('#tgChat').value.trim(),
    alertMinScore: +$('#aScore').value, alertTf: $('#aTf').value, alertCooldownHours: +$('#aCool').value, alertSweep: $('#aSweep').checked, alertMode: $('#aMode').value, alertZones: $('#aZones').checked, alertMacro: $('#aMacro').checked, macroWeekTelegram: $('#mwTg').checked, macroMonthTelegram: $('#mmTg').checked, historyYears: +$('#histYears').value, footprintDays: +$('#fpDays').value,
    xOn: $('#xOn').checked, xAccounts: $('#xAccounts').value, xPosts: +$('#xPosts').value,
    signalOn: $('#sOn').checked, signalMinScore: +$('#sMin').value, signalMaxWeek: +$('#sMax').value, signalMaxPerSymbol: +$('#sMaxSym').value, signalLeverage: +$('#sLev').value, signalTrendGate: $('#sTrend').checked, signalDirection: $('#sDir').value, signalOpposite: $('#sOpp').value};
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
  if (st.data) { panels.forEach(p => p.tick()); liveRender(); Desk.tick(); }
  requestAnimationFrame(loop);
}
let ovTimer = null;
async function pollOverview() {
  clearTimeout(ovTimer);
  if (st.page !== 'overview') return;
  ovTimer = setTimeout(pollOverview, 6000);
  try { Overview.render(await api('/api/overview')); } catch (e) { $('#overview').innerHTML = `<div class="dn">Vue d'ensemble indisponible : ${esc(e.message)}</div>`; }
}
// V28 : un seul témoin d'état dans l'en-tête (le détail s'ouvre d'un clic) : source, prix en direct, Telegram, niveaux
function headStatus() {
  const src = $('#srcBadge'), tg = $('#tgBadge'), lv = $('#liveBadge'), stt = $('#status');
  const bad = /bad/.test(stt.className) || /bad/.test(tg.className), warn = /warn/.test(lv.className) || (!lv.hidden && !/ok/.test(lv.className) && st.cfg && st.cfg.wsBase);
  const sim = st.cfg && st.cfg.source === 'simulated';
  const txt = /injoignable/.test(stt.textContent) ? 'terminal injoignable' : `${sim ? 'Données simulées' : 'Binance'}${lv.hidden ? '' : ' · ' + lv.textContent.replace('● ', '').toLowerCase()}${/ERREUR/.test(tg.textContent) ? ' · Telegram en erreur' : ''}`;
  const dot = bad ? 'bad' : sim || warn ? 'warn' : 'ok';
  const t = $('#hStatusTxt'), d = $('#hDot');
  if (t.textContent !== txt) t.textContent = txt;
  if (d.className !== dot) d.className = dot;
}
$('#hStatus').onclick = e => { e.stopPropagation(); const p = $('#hStatusPop'); p.hidden = !p.hidden; };
document.addEventListener('click', e => { const p = $('#hStatusPop'); if (!p.hidden && !e.target.closest('.hstat')) p.hidden = true; });
function switchSymbol(sym) { const sel = $('#symbol'); if (!st.cfg || !st.cfg.symbols.includes(sym)) return; sel.value = sym; sel.onchange(); }
function openSymbol(sym, page) {
  if (st.cfg && st.cfg.symbols.includes(sym) && sym !== st.symbol) switchSymbol(sym);
  location.hash = page === 'analysis' ? '#/analysis/synth' : page === 'signals' ? '#/signals' : '#/desk';
}
(async () => {
  loadPrefs();
  let cfg;
  try { cfg = await api('/api/config'); } catch (e) { $('#status').textContent = 'terminal injoignable'; return; }
  window.LT = {serverNow: () => Date.now() + (st.clockOff || 0), st, api, fmtP, fmtPct, num, sPct, pr, edgeOf, edgeChip, TF_SEC, rgba, COL_L, COL_S, byId, ladderZones, essentialZones, shownZones,
    serverOld, LAUNCHER, OPEN_ST, shownPools, impOf, fmtQty, fmtUsdShort, pollFlow, openTf, levelColor, livePrice, placeLabels, usdFmt, biasHtml, oppOf, parisAt, select, savePrefs, syncAllTools, refreshAll, maximize, pollHeat, PER, openSymbol, setPlan, updatePlan, togglePlan, planReset, planVisible,
    panels: () => panels, switchSymbol, applyLayout, setTf};
  Desk.init(window.LT);
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
  try { const t = localStorage.getItem('liqTab'); showPane((['lecture', 'levels', 'mine', 'chat'].includes(t) || (st.expert && EXPERT_TABS.includes(t))) ? t : 'lecture'); } catch (err) { showPane('lecture'); }
  $('#navSettings').onclick = e => { e.preventDefault(); openSettings(); };
  routeFromHash();
  poll(); pollAnalysis(); pollSignals(); renderAlerts(); setInterval(renderAlerts, 15000); requestAnimationFrame(loop); setTimeout(updateNotice, 2500);
  setInterval(() => {
    livePoll(); liveBadge(); cbRender(); riskChip(); headStatus();
    const lb = $('#liveBadge'), sb = $('#sbLive'); sb.hidden = lb.hidden; sb.textContent = lb.textContent; sb.className = lb.className;
  }, 1000);
  window.__term = {st, panels, select, openSettings, live, cb, Analysis, Signals, navigate, maximize, applyLayout, pollSignals};      // pour les tests automatiques
})();
})();
