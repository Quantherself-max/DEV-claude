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
const timeFr = ms => new Date(ms).toLocaleString('fr-FR', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
const PER = {d:'#FFB300', w:'#4CAF50', m:'#42A5F5', y:'#EC407A'};
const PER_OPEN = {d:'#CE93D8', w:'#9CCC65', m:'#64B5F6', y:'#F06292'};
const PER_VP = {d:'#AB47BC', w:'#66BB6A', m:'#5C9DEB', y:'#EF6C9A'};
const PN = {d:'du jour', w:'de la semaine', m:'du mois', y:"de l'année"};

const periodOf = g => { const m = /^[pP]?([dwmyDWMY])/.exec(g); return m ? m[1].toLowerCase() : 'd'; };
function levelColor(lv) {
  if (lv.kind === 'liq') return lv.pool && lv.pool.side === 'long' ? UP : DN;
  if (lv.kind === 'avwap') return '#E0E0E0';
  if (lv.kind === 'hl') return '#D1D4DC';
  const p = periodOf(lv.group);
  return lv.kind === 'vwap' ? PER[p] : lv.kind === 'open' ? PER_OPEN[p] : PER_VP[p];
}
function explain(name) {
  let m;
  if (/^AVWAP/.test(name)) return 'VWAP ancrée à la date indiquée : prix moyen pondéré par le volume depuis cette date.';
  if ((m = /^([dwmy])VWAP$/.exec(name))) return `VWAP ${PN[m[1]]} en cours : prix moyen pondéré par le volume depuis le début de la période (UTC).`;
  if ((m = /^([dwmy])Open$/.exec(name))) return `Prix d'ouverture ${PN[m[1]]} en cours.`;
  if ((m = /^(p?)([dwmy])(POC|VAH|VAL|HVN)$/.exec(name))) {
    const what = {POC:'Point of Control (prix le plus échangé)', VAH:'haut de la Value Area (70 % du volume)', VAL:'bas de la Value Area (70 % du volume)', HVN:'High Volume Node (zone de fort volume)'}[m[3]];
    return `${what} du profil de volume ${m[1] ? 'précédent ' : 'en cours '}${PN[m[2]]}.`;
  }
  if ((m = /^P([DWMY])([HL])$/.exec(name))) return `Plus ${m[2] === 'H' ? 'haut' : 'bas'} ${PN[m[1].toLowerCase()].replace('du', 'du précédent').replace('de la', 'de la précédente').replace("de l'année", "de l'année précédente")} : liquidité classique (stops au-delà).`;
  if (/^Liq/.test(name)) return 'Poche de liquidation estimée à partir de l\'Open Interest (proxy).';
  return '';
}

const st = {symbol: null, tf: '1h', data: null, mode: 'conf', pools: true, sel: null, lines: [], key: null, version: 0, cfg: null, tab: 'levels', statSide: 'all', lastBar: 0, lastBarObj: null};
async function api(path, body) {
  const opt = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Terminal-Token': st.cfg ? st.cfg.csrf : ''}, body: JSON.stringify(body)};
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
  return j;
}

// ---------- graphique ----------
const chart = LightweightCharts.createChart($('#chart'), {
  autoSize: true,
  layout: {background: {type: 'solid', color: '#0b0e11'}, textColor: '#b2b5be', fontSize: 12},
  grid: {vertLines: {color: '#141824'}, horzLines: {color: '#141824'}},
  rightPriceScale: {borderColor: '#2a2e39', scaleMargins: {top: 0.08, bottom: 0.08}},
  timeScale: {borderColor: '#2a2e39', timeVisible: true, secondsVisible: false, rightOffset: 16},
  crosshair: {mode: LightweightCharts.CrosshairMode.Normal},
});
const series = chart.addCandlestickSeries({upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
  wickUpColor: '#26a69a', wickDownColor: '#ef5350', priceLineColor: '#787b86',
  autoscaleInfoProvider: orig => {                       // garde les poches et zones proches dans le cadre
    const r = orig(); const d = st.data;
    if (!r || !d) return r;
    const ex = d.liquidity.pools.map(p => p.price).concat(ladderZones(d).map(z => z.mid));
    if (ex.length) {
      r.priceRange.minValue = Math.min(r.priceRange.minValue, ...ex);
      r.priceRange.maxValue = Math.max(r.priceRange.maxValue, ...ex);
    }
    return r;
  }});
const overlay = $('#overlay'), ctx = overlay.getContext('2d');

const byId = (arr, k = 'id') => Object.fromEntries(arr.map(x => [x[k], x]));
const ladderZones = d => {
  const z = byId(d.zones);
  return [...d.ladder.above, ...d.ladder.inside, ...d.ladder.below].map(i => z[i]).filter(Boolean);
};

function setData(d) {
  const key = d.symbol + '|' + d.tf;
  const bars = d.candles.map(c => ({time: c[0], open: c[1], high: c[2], low: c[3], close: c[4]}));
  if (key !== st.key) {
    st.key = key;
    live.bar = null;
    series.setData(bars);
    const n = bars.length;
    chart.timeScale().setVisibleLogicalRange({from: Math.max(0, n - 130), to: n + 16});
    st.lastBar = n ? bars[n - 1].time : 0;
  } else {
    // mise a jour douce (ne deplace pas la vue) : la bibliotheque n'accepte que la derniere bougie ou une plus
    // recente. La bougie en cours garde les extremes et la cloture du flux temps reel s'il est plus frais.
    bars.filter(b => b.time >= st.lastBar).forEach(b => {
      const lb = live.bar;
      if (lb && lb.time === b.time && liveFresh()) {
        b = {...b, high: Math.max(b.high, lb.high), low: Math.min(b.low, lb.low), close: lb.close};
        live.bar = b;
      }
      series.update(b);
      st.lastBar = b.time;
    });
  }
  st.lastBarObj = bars.length ? {...bars[bars.length - 1]} : null;
  if (live.bar && st.lastBarObj && live.bar.time === st.lastBarObj.time) st.lastBarObj = {...live.bar};
}

// ---------- temps reel : flux des transactions Binance (WebSocket) directement dans le navigateur ----------
// Le prix et la bougie en cours bougent a chaque transaction ; le serveur, lui, recalcule niveaux, poches et
// alertes toutes les 10 s. Si le flux ne passe pas, secours : dernier prix demande au serveur chaque seconde.
const TF_SEC = {'5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400};
const live = {ws: null, sym: null, price: null, t: 0, wsT: 0, src: '', bar: null, barDirty: false, dirty: false,
  retry: 0, retryTimer: null, opened: 0, panelT: 0, polling: false};
const liveFresh = () => live.price != null && live.sym === st.symbol && Date.now() - live.t < 5000;
const livePrice = d => liveFresh() ? live.price : d.price;
function onTick(price, tms, src) {
  if (!(price > 0)) return;
  live.price = price; live.t = Date.now(); live.src = src; live.dirty = true;
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
    try { series.update(live.bar); st.lastBar = live.bar.time; } catch (e) { live.bar = null; }
    live.barDirty = false;
  }
  if (live.dirty) {
    const t = fmtP(live.price), lp = $('#ladderPrice');
    if ($('#price').textContent !== t) $('#price').textContent = t;
    if (lp && lp.textContent !== t) lp.textContent = t;
    if (Date.now() - live.panelT > 1000) { live.panelT = Date.now(); live.dirty = false; liveDistances(d); }
  }
}

function rebuildLines(d) {
  st.lines.forEach(l => series.removePriceLine(l));
  st.lines = [];
  const lv = byId(d.levels);
  let ids;
  if (st.mode === 'all') ids = d.levels.filter(l => l.kind !== 'liq' && l.inWindow).map(l => l.id);
  else {
    const set = new Set(ladderZones(d).flatMap(z => z.members));
    if (st.sel && st.sel.type === 'zone') (byId(d.zones)[st.sel.id]?.members || []).forEach(i => set.add(i));
    ids = [...set].filter(i => lv[i] && lv[i].kind !== 'liq');
  }
  if (st.sel && st.sel.type === 'level' && lv[st.sel.id] && !ids.includes(st.sel.id)) ids.push(st.sel.id);
  const style = {vwap: 0, avwap: 0, open: 1, vp: 2, hl: 4};
  ids.forEach(i => {
    const l = lv[i]; const sel = st.sel && st.sel.type === 'level' && st.sel.id === i;
    st.lines.push(series.createPriceLine({price: l.price, color: levelColor(l), lineWidth: sel ? 2 : 1,
      lineStyle: style[l.kind] ?? 0, axisLabelVisible: false, title: l.name}));
  });
}

// ---------- calque : zones de confluence et poches (barres en degrade ancrees sur la derniere bougie) ----------
function rgba(c, a) { return `rgba(${c[0]},${c[1]},${c[2]},${a})`; }
function layout() {
  const d = st.data; if (!d) return null;
  const ts = chart.timeScale();
  const lastT = d.candles[d.candles.length - 1][0];
  let xr = ts.timeToCoordinate(lastT);
  const plotW = ts.width();
  if (xr == null) xr = plotW - 80;
  return {d, xr, plotW};
}
function poolRect(p, L) {
  const y1 = series.priceToCoordinate(p.hi), y0 = series.priceToCoordinate(p.lo), yc = series.priceToCoordinate(p.price);
  if (y1 == null || y0 == null || yc == null) return null;
  const thick = Math.max(6, Math.abs(y0 - y1));
  const len = Math.max(36, L.plotW * 0.28 * Math.pow(p.rel, 0.7));
  return {x0: L.xr - len, x1: L.xr, yc, thick, len};
}
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
function tag(x, y, text, color, bg, bold) {
  ctx.font = (bold ? '700 ' : '500 ') + '11px sans-serif';
  const tw = ctx.measureText(text).width + 12, th = 17;
  ctx.fillStyle = bg; ctx.beginPath(); (ctx.roundRect ? ctx.roundRect(x, y - th / 2, tw, th, 8) : ctx.rect(x, y - th / 2, tw, th)); ctx.fill();
  ctx.fillStyle = color; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(text, x + 6, y + 0.5);
  return tw;
}
function draw() {
  const dpr = window.devicePixelRatio || 1, w = overlay.clientWidth, h = overlay.clientHeight;
  if (overlay.width !== Math.round(w * dpr) || overlay.height !== Math.round(h * dpr)) {
    overlay.width = Math.round(w * dpr); overlay.height = Math.round(h * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const L = layout(); if (!L) return;
  const {d, xr, plotW} = L;
  // zones de confluence : bandes ambrees discretes sur toute la largeur (nom seulement si selectionnee)
  const selZ = st.sel && st.sel.type === 'zone' ? st.sel.id : null;
  const zones = ladderZones(d);
  const zset = new Map(zones.map(z => [z.id, z]));
  if (selZ && !zset.has(selZ)) { const z = byId(d.zones)[selZ]; if (z) zset.set(selZ, z); }
  zset.forEach(z => {
    const yt = series.priceToCoordinate(z.hi), yb = series.priceToCoordinate(z.lo);
    if (yt == null || yb == null) return;
    const span = Math.abs(yb - yt), hh = Math.max(6, span), y = Math.min(yt, yb) - (hh - span) / 2, sel = z.id === selZ;
    ctx.fillStyle = `rgba(255,179,0,${sel ? 0.2 : 0.05 + 0.02 * Math.min(4, z.score)})`;
    ctx.fillRect(0, y, plotW, hh);
    if (sel) { ctx.strokeStyle = 'rgba(255,179,0,.85)'; ctx.lineWidth = 1; ctx.strokeRect(0.5, y + 0.5, plotW - 1, hh - 1); }
  });
  // poches de liquidite : barres en degrade + halo, etiquettes en pastille sans chevauchement
  const pills = [];
  if (st.pools) d.liquidity.pools.forEach((p, i) => {
    const r = poolRect(p, L); if (!r) return;
    const col = p.side === 'long' ? [61, 220, 151] : [255, 107, 107];
    const a = Math.min(0.9, 0.22 + 0.55 * Math.pow(p.rel, 0.8) + (p.magnet ? 0.1 : 0));
    const g = ctx.createLinearGradient(r.x1, 0, r.x0, 0);
    g.addColorStop(0, rgba(col, a)); g.addColorStop(1, rgba(col, 0));
    const g2 = ctx.createLinearGradient(r.x1, 0, r.x0, 0);
    g2.addColorStop(0, rgba(col, a * 0.18)); g2.addColorStop(1, rgba(col, 0));
    ctx.fillStyle = g2; ctx.fillRect(r.x0, r.yc - r.thick * 0.9, r.len, r.thick * 1.8);
    ctx.fillStyle = g; ctx.fillRect(r.x0, r.yc - r.thick / 2, r.len, r.thick);
    if (st.sel && st.sel.type === 'pool' && st.sel.id === i) { ctx.strokeStyle = rgba(col, 1); ctx.lineWidth = 1.5; ctx.strokeRect(r.x0, r.yc - r.thick / 2 - 2, r.len, r.thick + 4); }
    const dist = (p.price / livePrice(d) - 1) * 100;
    pills.push({y: r.yc, x1: r.x1, col, magnet: p.magnet, text: (p.magnet ? 'AIMANT ' : '') + fmtP(p.price) + '  ' + fmtPct(dist)});
  });
  placeLabels(pills, 19, 12, h - 30).forEach(it => {
    ctx.font = (it.magnet ? '700 ' : '500 ') + '11px sans-serif';
    const x = Math.min(it.x1 + 10, plotW - ctx.measureText(it.text).width - 14);
    if (Math.abs(it.ly - it.y) > 2) { ctx.strokeStyle = rgba(it.col, 0.6); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(it.x1, it.y); ctx.lineTo(x, it.ly); ctx.stroke(); }
    tag(x, it.ly, it.text, it.magnet ? '#0b0e11' : '#fff', rgba(it.col, it.magnet ? 0.92 : 0.55), it.magnet);
  });
  // noms des niveaux : membres de la zone selectionnee, niveau selectionne, ou tous en mode "Tous les niveaux"
  const lv = byId(d.levels), names = new Map();
  if (st.mode === 'all') d.levels.filter(l => l.kind !== 'liq' && l.inWindow).forEach(l => names.set(l.id, l));
  if (selZ) (byId(d.zones)[selZ]?.members || []).forEach(i => lv[i] && lv[i].kind !== 'liq' && names.set(i, lv[i]));
  if (st.sel && st.sel.type === 'level' && lv[st.sel.id]) names.set(st.sel.id, lv[st.sel.id]);
  const lab = [];
  names.forEach(l => { const y = series.priceToCoordinate(l.price); if (y != null) lab.push({y, l}); });
  placeLabels(lab, 15, 12, h - 30).forEach(it => {
    const c = levelColor(it.l);
    if (Math.abs(it.ly - it.y) > 2) { ctx.strokeStyle = 'rgba(180,184,196,.5)'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(0, it.y); ctx.lineTo(10, it.ly); ctx.stroke(); }
    ctx.font = '500 11px sans-serif';
    const txt = it.l.name + '  ' + fmtP(it.l.price), tw = ctx.measureText(txt).width + 22;
    ctx.fillStyle = 'rgba(11,14,17,.88)'; ctx.fillRect(10, it.ly - 8, tw, 16);
    ctx.fillStyle = c; ctx.fillRect(10, it.ly - 8, 3, 16);
    ctx.fillStyle = '#d1d4dc'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(txt, 19, it.ly + 0.5);
  });
}
let sig = '';
function loop() {
  const d = st.data;
  if (d) {
    const ts = chart.timeScale(), r = ts.getVisibleLogicalRange();
    const s = [series.priceToCoordinate(d.price) | 0, series.priceToCoordinate(d.price * 1.03) | 0,
      ts.timeToCoordinate(d.candles[d.candles.length - 1][0]) | 0, r ? (r.from | 0) + ':' + (r.to | 0) : '',
      overlay.clientWidth, overlay.clientHeight, st.version, (livePrice(d) / d.price).toFixed(4)].join();
    if (s !== sig) { sig = s; draw(); }
    liveRender();
  }
  requestAnimationFrame(loop);
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
  return `<div class="row${z.score < 3 ? ' weak' : ''}${sel}" data-zone="${z.id}">${ar}<span class="nm" title="${esc(names.join(' + '))}">${esc(names.join(' + '))}</span>` +
    `<span class="pv">${fmtP(z.mid)}</span><span class="sub"><span data-zd="${z.id}">${zoneDist(z, d, livePrice(d))}</span><span class="dots">${dots}</span>${z.hasMagnet ? ' · poche AIMANT' : ''}` +
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
      `<span class="nm">${p.magnet ? '<b>AIMANT</b> · ' : ''}${p.side === 'long' ? 'longs' : 'shorts'}</span><span class="pv">${fmtP(p.price)}</span>` +
      `<span class="sub"><span data-pd="${i}">${fmtPct(dist)}</span> · score ${p.score}${p.reach ? ' · <span class="pr">' + pr(p.reach['24']) + '</span> d\'y aller en 24 h' : ''}<div class="bar"><i style="width:${p.score}%;background:${c}"></i></div></span></div>`;
  });
  if (!pools.length) h = '<div class="muted">Aucune poche assez forte dans la fenêtre.</div>';
  const tot = q.sumLong + q.sumShort, up = tot ? q.sumShort / tot * 100 : 50;
  h += `<div class="imb"><i style="width:${up}%;background:${DN}"></i><i style="width:${100 - up}%;background:${UP}"></i></div>` +
    `<div class="muted" style="font-size:11px">au-dessus ${up.toFixed(0)} % · en dessous ${(100 - up).toFixed(0)} % · ${q.total} poches détectées → ${pools.length} retenues</div>`;
  $('#pools').innerHTML = h;
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
      return `<tr title="${esc(explain(m.name))}"><td><span class="chip" style="background:${levelColor(m)}"></span>${esc(m.name)}${m.pool && m.pool.magnet ? ' <b>AIMANT</b>' : ''}</td>` +
        `<td class="muted small">${f && f.n ? 'rebond ' + pr(f.p) + ' (n=' + f.n + ')' : ''}</td><td>${fmtP(m.price)}</td></tr>`;
    }).join('');
    const where = {above: 'Zone au-dessus du prix (résistance) : règle « aimant » → plutôt attirée vers le haut.', below: 'Zone sous le prix (support) : règle « aimant » → plutôt attirée vers le bas.', in: 'Le prix est dans la zone.'}[z.side];
    const p = z.prob;
    const bucket = p ? (p.bucket === '3+' ? '3 sources ou plus' : p.bucket + ' sources') : '';
    el.innerHTML = `<div><b>${ar} Confluence ${fmtP(z.mid)}</b> <span class="muted">${z.side === 'in' ? '' : fmtPct(z.distPct) + ' · ' + num(z.distAtr, 1) + ' ATR · '}score ${z.score}</span></div>` +
      `<table class="mem">${rows}</table>` +
      (p ? (z.side !== 'in' ? reachBlock(p.reach, `atteigne la zone (${num(p.distAtrH1, 1)} ATR 1h)`) : '') +
        `<div class="sect">Si le prix touche la zone</div>` + statLine(p.bounce, p.base, `Zones à ${bucket} (${p.side === 'support' ? 'support' : p.side === 'resistance' ? 'résistance' : 'tous'})`) + defNote()
        : '<div class="note">Probabilités : calcul de l\'historique en cours…</div>') +
      `<div class="note">${where} Hypothèse non validée.${z.hasMagnet ? ' Contient une poche de liquidation AIMANT.' : ''}</div>`;
  } else if (s.type === 'pool') {
    const p = d.liquidity.pools[s.id]; if (!p) { el.textContent = 'Poche disparue.'; return; }
    const dist = (p.price / d.price - 1) * 100, sw = d.sweeps && d.sweeps.stats;
    el.innerHTML = `<div><b>${p.side === 'long' ? '▼ Liquidations de longs' : '▲ Liquidations de shorts'} ${fmtP(p.price)}</b> ` +
      `<span class="muted">${fmtPct(dist)} · ${num(Math.abs(p.price - d.price) / d.atr, 1)} ATR</span></div>` +
      `<div class="note">Fourchette ${fmtP(p.lo)} – ${fmtP(p.hi)} · taille relative ${p.score}/100${p.magnet ? ' · <b>AIMANT</b> (la plus forte de ce côté)' : ''}</div>` +
      `<div class="bar"><i style="width:${p.score}%;background:${p.side === 'long' ? UP : DN}"></i></div>` +
      reachBlock(p.reach, 'atteigne la poche') +
      `<div class="sect">Après un balayage (journal des 30 derniers jours)</div>` + statLine(sw, base, 'Poches balayées') +
      `<div class="note">Estimation à partir de l'Open Interest : chaque hausse d'OI = nouvelles positions, réparties longs/shorts selon le <b>vrai volume acheteur agressif</b> (taker buy) de la bougie, puis par levier (100x 10 %, 50x 20 %, 25x 30 %, 10x 40 %) ; prix de liquidation = formule isolée + marge 0,4 %. Un niveau disparaît quand le prix le touche ; quand l'OI baisse, tout est réduit d'autant. <b>Proxy, pas de vraies liquidations.</b></div>`;
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
  rg.hidden = !c.regime; if (c.regime) { rg.textContent = c.regime.label; rg.title = 'Régime prix / Open Interest sur 4 h'; }
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

// ---------- selection / clic ----------
function select(sel) { st.sel = sel; st.version++; if (st.data) { rebuildLines(st.data); renderLadder(st.data); renderPools(st.data); renderDetail(st.data); } }
chart.subscribeClick(p => {
  const d = st.data, L = layout();
  if (!p.point || !d || !L) return;
  const {x, y} = p.point;
  if (st.pools) {
    for (let i = 0; i < d.liquidity.pools.length; i++) {
      const r = poolRect(d.liquidity.pools[i], L);
      if (r && x >= r.x0 - 4 && x <= r.x1 + 130 && Math.abs(y - r.yc) <= r.thick / 2 + 5) return select({type: 'pool', id: i});
    }
  }
  const zs = ladderZones(d);
  for (const z of zs) {
    const a = series.priceToCoordinate(z.hi), b = series.priceToCoordinate(z.lo);
    if (a == null || b == null) continue;
    const mid = (a + b) / 2, half = Math.max(5, Math.abs(a - b) / 2 + 3);
    if (Math.abs(y - mid) <= half) return select({type: 'zone', id: z.id});
  }
  let best = null, bd = 7;
  d.levels.forEach(l => {
    if (l.kind === 'liq') return;
    const visible = st.mode === 'all' ? l.inWindow : zs.some(z => z.members.includes(l.id));
    const yy = series.priceToCoordinate(l.price);
    if (visible && yy != null && Math.abs(yy - y) < bd) { bd = Math.abs(yy - y); best = l; }
  });
  select(best ? {type: 'level', id: best.id} : null);
});
document.addEventListener('click', e => {
  const z = e.target.closest('[data-zone]'), p = e.target.closest('[data-pool]');
  if (z) select({type: 'zone', id: z.dataset.zone});
  else if (p) select({type: 'pool', id: +p.dataset.pool});
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
  else if (!d && c.source === 'binance') banner('warn', '<span>Chargement de l\'historique Binance (1 à 2 minutes la première fois)…</span>');
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
function apply(d) {
  st.data = d;
  setData(d); header(d); rebuildLines(d); renderLadder(d); renderPools(d); renderDetail(d); renderContext(d); renderStats(d);
  st.version++;
}
let timer = null;
async function poll() {
  clearTimeout(timer);
  timer = setTimeout(poll, 4000);
  let d;
  try { d = await (await fetch(`/api/state?symbol=${st.symbol}&tf=${st.tf}`)).json(); }
  catch (e) { $('#status').textContent = 'terminal injoignable : la fenêtre du programme est-elle fermée ?'; $('#status').className = 'bad'; return; }
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
function buildControls(cfg) {
  st.cfg = cfg;
  if (!cfg.symbols.includes(st.symbol)) st.symbol = cfg.symbols[0];
  const sel = $('#symbol'); sel.innerHTML = cfg.symbols.map(s => `<option${s === st.symbol ? ' selected' : ''}>${s}</option>`).join('');
  sel.onchange = () => { st.symbol = sel.value; st.sel = null; st.data = null; liveConnect(); poll(); };
  const box = $('#tfs');
  box.innerHTML = cfg.tfs.map(t => `<button data-tf="${t}" class="${t === st.tf ? 'on' : ''}">${t}</button>`).join('');
  box.onclick = e => { const b = e.target.closest('button'); if (!b) return; st.tf = b.dataset.tf; st.sel = null; st.data = null;
    box.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); poll(); };
  document.querySelectorAll('input[name=mode]').forEach(r => r.onchange = () => { st.mode = r.value; if (st.data) { rebuildLines(st.data); st.version++; } });
  $('#showPools').onchange = e => { st.pools = e.target.checked; st.version++; };
  updateBanner(st.data);
  if (!live.ws || live.sym !== st.symbol || !cfg.wsBase) liveConnect();
}
// onglets du panneau de droite
$('#tabs').onclick = e => {
  const b = e.target.closest('button[data-tab]'); if (!b) return;
  st.tab = b.dataset.tab;
  document.querySelectorAll('#tabs button').forEach(x => x.classList.toggle('on', x === b));
  document.querySelectorAll('.pane').forEach(p => p.hidden = p.dataset.pane !== st.tab);
  try { localStorage.setItem('liqTab', st.tab); } catch (err) { /* stockage indisponible */ }
};
$('#stats').addEventListener('click', e => {
  const b = e.target.closest('button[data-side]'); if (!b) return;
  st.statSide = b.dataset.side; if (st.data) renderStats(st.data);
});

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
    $('#tgToken').value = '';
    $('#tgToken').placeholder = s.telegram.tokenHint ? `token enregistré (${s.telegram.tokenHint}) : laisse vide pour le garder` : '123456789:AA...';
    $('#tgChat').value = s.telegram.chatId || '';
    $('#tgState').textContent = s.telegram.configured ? '✓ configuré' : 'non configuré';
    $('#tgState').className = s.telegram.configured ? 'up' : '';
    $('#aScore').value = String(s.alertMinScore);
    $('#aTf').innerHTML = (st.cfg ? st.cfg.tfs : ['1h']).map(t => `<option${t === s.alertTf ? ' selected' : ''}>${t}</option>`).join('');
    $('#aCool').value = s.alertCooldownHours;
    $('#aSweep').checked = !!s.alertSweep;
  } catch (e) { $('#saveRes').textContent = 'Erreur : ' + e.message; }
}
const closeSettings = () => { M.hidden = true; };
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
$('#saveSettings').onclick = () => busy($('#saveSettings'), $('#saveRes'), async () => {
  const src = (document.querySelector('input[name=source]:checked') || {}).value;
  const before = st.cfg ? st.cfg.source + '|' + st.cfg.symbols.join(',') : '';
  const body = {source: src, symbols: $('#symbols').value.split(/[\s,;]+/).filter(Boolean), telegramChatId: $('#tgChat').value.trim(),
    alertMinScore: +$('#aScore').value, alertTf: $('#aTf').value, alertCooldownHours: +$('#aCool').value, alertSweep: $('#aSweep').checked};
  if ($('#tgToken').value.trim()) body.telegramToken = $('#tgToken').value.trim();
  await api('/api/settings', body);
  buildControls(await api('/api/config'));
  const reloaded = before !== st.cfg.source + '|' + st.cfg.symbols.join(',');
  closeSettings();
  if (reloaded) { st.data = null; st.key = null; st.sel = null; }
  toast(reloaded ? (st.cfg.source === 'binance' ? 'Enregistré. Chargement des vraies données Binance (1 à 2 min)…' : 'Enregistré. Rechargement des données…') : 'Réglages enregistrés.');
  poll(); renderAlerts();
});

(async () => {
  try { buildControls(await api('/api/config')); } catch (e) { $('#status').textContent = 'terminal injoignable'; return; }
  try { const t = localStorage.getItem('liqTab'); if (t && t !== 'levels') { const b = document.querySelector(`#tabs button[data-tab="${t}"]`); if (b) b.click(); } } catch (err) { /* rien */ }
  poll(); renderAlerts(); setInterval(renderAlerts, 15000); requestAnimationFrame(loop);
  setInterval(() => { livePoll(); liveBadge(); }, 1000);
  window.__term = {st, chart, series, select, draw, layout, poolRect, overlay, openSettings, live};      // pour les tests automatiques
})();
})();
