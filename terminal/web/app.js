(() => {
'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtP = p => p >= 1000 ? Math.round(p).toLocaleString('fr-FR') : p.toFixed(2).replace('.', ',');
const fmtPct = v => (v > 0 ? '+' : '') + v.toFixed(2).replace('.', ',') + ' %';
const UP = '#3ddc97', DN = '#ff6b6b', AMB = '#ffb300';
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

const st = {symbol: null, tf: '1h', data: null, mode: 'conf', pools: true, sel: null, lines: [], key: null, version: 0, cfg: null};

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
    series.setData(bars);
    const n = bars.length;
    chart.timeScale().setVisibleLogicalRange({from: Math.max(0, n - 130), to: n + 16});
  } else {
    bars.slice(-3).forEach(b => series.update(b));       // mise a jour douce : ne deplace pas la vue
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
    const dist = (p.price / d.price - 1) * 100;
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
      overlay.clientWidth, overlay.clientHeight, st.version].join();
    if (s !== sig) { sig = s; draw(); }
  }
  requestAnimationFrame(loop);
}

// ---------- panneaux ----------
function zoneRow(z, d) {
  const lv = byId(d.levels);
  const names = z.members.map(i => lv[i]).filter(Boolean).sort((a, b) => a.price - b.price).map(m => m.name);
  const ar = z.side === 'above' ? '<span class="ar up">▲</span>' : z.side === 'below' ? '<span class="ar dn">▼</span>' : '<span class="ar inz">◆</span>';
  const dots = '●'.repeat(Math.min(5, z.score));
  const sel = st.sel && st.sel.type === 'zone' && st.sel.id === z.id ? ' sel' : '';
  return `<div class="row${z.score < 3 ? ' weak' : ''}${sel}" data-zone="${z.id}">${ar}<span class="nm" title="${esc(names.join(' + '))}">${esc(names.join(' + '))}</span>` +
    `<span class="pv">${fmtP(z.mid)}</span><span class="sub">${z.side === 'in' ? 'le prix est dans la zone' : fmtPct(z.distPct) + ' · ' + z.distAtr.toFixed(1).replace('.', ',') + ' ATR'}<span class="dots">${dots}</span>${z.hasMagnet ? ' · poche AIMANT' : ''}</span></div>`;
}
function renderLadder(d) {
  const zs = byId(d.zones);
  let h = '';
  d.ladder.above.forEach(i => h += zoneRow(zs[i], d));
  d.ladder.inside.forEach(i => h += zoneRow(zs[i], d));
  h += `<div class="pricerow"><span>PRIX</span><span>${fmtP(d.price)}</span></div>`;
  d.ladder.below.forEach(i => h += zoneRow(zs[i], d));
  if (!d.zones.length) h = '<div class="muted">Aucune confluence pour l\'instant.</div>' + h;
  $('#ladder').innerHTML = h;
  $('#confHint').textContent = `${d.zones.length} zones · pâle = 2 sources`;
}
function renderPools(d) {
  const q = d.liquidity, pools = q.pools;
  let h = '';
  [...pools].sort((a, b) => b.price - a.price).forEach(p => {
    const i = pools.indexOf(p), dist = (p.price / d.price - 1) * 100, c = p.side === 'long' ? UP : DN;
    const sel = st.sel && st.sel.type === 'pool' && st.sel.id === i ? ' sel' : '';
    h += `<div class="row${sel}" data-pool="${i}"><span class="ar" style="color:${c}">${p.side === 'long' ? '▼' : '▲'}</span>` +
      `<span class="nm">${p.magnet ? '<b>AIMANT</b> · ' : ''}${p.side === 'long' ? 'longs' : 'shorts'}</span><span class="pv">${fmtP(p.price)}</span>` +
      `<span class="sub">${fmtPct(dist)} · score ${p.score}<div class="bar"><i style="width:${p.score}%;background:${c}"></i></div></span></div>`;
  });
  if (!pools.length) h = '<div class="muted">Aucune poche assez forte dans la fenêtre.</div>';
  const tot = q.sumLong + q.sumShort, up = tot ? q.sumShort / tot * 100 : 50;
  h += `<div class="imb"><i style="width:${up}%;background:${DN}"></i><i style="width:${100 - up}%;background:${UP}"></i></div>` +
    `<div class="muted" style="font-size:11px">au-dessus ${up.toFixed(0)} % · en dessous ${(100 - up).toFixed(0)} % · ${q.total} poches détectées → ${pools.length} retenues</div>`;
  $('#pools').innerHTML = h;
}
function renderDetail(d) {
  const el = $('#detail'), s = st.sel;
  if (!s) { el.className = 'muted'; el.textContent = 'Rien de sélectionné.'; return; }
  el.className = '';
  const lv = byId(d.levels);
  if (s.type === 'zone') {
    const z = byId(d.zones)[s.id]; if (!z) { el.textContent = 'Zone disparue.'; return; }
    const ar = {above: '▲', below: '▼', in: '◆'}[z.side];
    const rows = z.members.map(i => lv[i]).filter(Boolean).sort((a, b) => a.price - b.price).map(m =>
      `<tr title="${esc(explain(m.name))}"><td><span class="chip" style="background:${levelColor(m)}"></span>${esc(m.name)}${m.pool && m.pool.magnet ? ' <b>AIMANT</b>' : ''}</td><td>${fmtP(m.price)}</td></tr>`).join('');
    const where = {above: 'Zone au-dessus du prix : règle « aimant » → plutôt attirée vers le haut.', below: 'Zone sous le prix : règle « aimant » → plutôt attirée vers le bas.', in: 'Le prix est dans la zone.'}[z.side];
    el.innerHTML = `<div><b>${ar} Confluence ${fmtP(z.mid)}</b> <span class="muted">${z.side === 'in' ? '' : fmtPct(z.distPct) + ' · ' + z.distAtr.toFixed(1).replace('.', ',') + ' ATR · '}score ${z.score}</span></div>` +
      `<table class="mem">${rows}</table><div class="note">${where} Hypothèse non validée.${z.hasMagnet ? ' Contient une poche de liquidation AIMANT.' : ''}</div>` +
      `<div class="note">Historique de réaction du prix sur ce type de zone : pas encore calculé (prévu en V4).</div>`;
  } else if (s.type === 'pool') {
    const p = d.liquidity.pools[s.id]; if (!p) { el.textContent = 'Poche disparue.'; return; }
    const dist = (p.price / d.price - 1) * 100;
    el.innerHTML = `<div><b>${p.side === 'long' ? '▼ Liquidations de longs' : '▲ Liquidations de shorts'} ${fmtP(p.price)}</b> ` +
      `<span class="muted">${fmtPct(dist)} · ${(Math.abs(p.price - d.price) / d.atr).toFixed(1).replace('.', ',')} ATR</span></div>` +
      `<div class="note">Fourchette ${fmtP(p.lo)} – ${fmtP(p.hi)} · taille relative ${p.score}/100${p.magnet ? ' · <b>AIMANT</b> (la plus forte de ce côté)' : ''}</div>` +
      `<div class="bar"><i style="width:${p.score}%;background:${p.side === 'long' ? UP : DN}"></i></div>` +
      `<div class="note">Estimation à partir de l'Open Interest : chaque hausse d'OI = nouvelles positions, réparties longs/shorts selon la direction de la bougie, puis par levier (100x 10 %, 50x 20 %, 25x 30 %, 10x 40 %) ; prix de liquidation = formule isolée + marge 0,4 %. Un niveau disparaît quand le prix le touche. <b>Proxy, pas de vraies liquidations.</b></div>`;
  } else {
    const l = lv[s.id]; if (!l) { el.textContent = 'Niveau disparu.'; return; }
    el.innerHTML = `<div><b><span class="chip" style="background:${levelColor(l)}"></span>${esc(l.name)} ${fmtP(l.price)}</b> <span class="muted">${fmtPct(l.distPct)} · ${l.distAtr.toFixed(1).replace('.', ',')} ATR</span></div>` +
      `<div class="note">${esc(explain(l.name))}</div>${l.zone ? '<div class="note">Fait partie d\'une confluence (voir la liste).</div>' : ''}`;
  }
}
async function renderAlerts() {
  try {
    const a = await (await fetch('/api/alerts')).json();
    $('#alertHint').textContent = a.telegram ? 'Telegram actif' : 'Telegram non configuré (console seulement)';
    $('#alerts').className = a.log.length ? '' : 'muted';
    $('#alerts').innerHTML = a.log.length ? a.log.slice(0, 8).map(e => {
      const t = new Date(e.t * 1000).toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit'});
      return `<div class="alert"><time>${t}</time>${e.sent ? '✓' : '✗'} ${esc(e.text.split('\n')[0])}</div>`;
    }).join('') : `Aucune alerte envoyée. Règle : ${st.cfg ? 'score ≥ ' + st.cfg.alertMinScore + ' à moins de ' + st.cfg.alertMaxDistAtr + ' ATR (' + st.cfg.alertTf + ')' : ''}`;
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
function header(d) {
  $('#price').textContent = fmtP(d.price);
  $('#atr').textContent = `ATR ${st.tf} ${fmtP(d.atr)} (${d.atrPct.toFixed(2).replace('.', ',')} %)`;
  const sb = $('#srcBadge');
  sb.textContent = d.source === 'simulated' ? 'DONNÉES SIMULÉES' : 'BINANCE';
  sb.className = 'badge ' + (d.source === 'simulated' ? 'warn' : 'ok');
  const tb = $('#tgBadge');
  tb.textContent = st.cfg && st.cfg.telegram ? 'TELEGRAM ON' : 'TELEGRAM OFF';
  tb.className = 'badge ' + (st.cfg && st.cfg.telegram ? 'ok' : '');
  const age = Math.max(0, Math.round(Date.now() / 1000 - d.lastUpdate));
  $('#status').textContent = d.error ? 'erreur : ' + d.error : `mis à jour il y a ${age} s`;
  $('#status').className = d.error ? 'bad' : 'muted';
}
function apply(d) {
  st.data = d;
  setData(d); header(d); rebuildLines(d); renderLadder(d); renderPools(d); renderDetail(d);
  st.version++;
}
let timer = null;
async function poll() {
  clearTimeout(timer);
  try {
    const r = await fetch(`/api/state?symbol=${st.symbol}&tf=${st.tf}`);
    const d = await r.json();
    if (d.ready) apply(d);
    else { $('#status').textContent = d.error || 'chargement des données...'; $('#status').className = 'muted'; }
  } catch (e) { $('#status').textContent = 'terminal injoignable'; $('#status').className = 'bad'; }
  timer = setTimeout(poll, 4000);
}
function buildControls(cfg) {
  st.cfg = cfg; st.symbol = cfg.symbols[0];
  const sel = $('#symbol'); sel.innerHTML = cfg.symbols.map(s => `<option>${s}</option>`).join('');
  sel.onchange = () => { st.symbol = sel.value; st.sel = null; st.data = null; poll(); };
  const box = $('#tfs');
  box.innerHTML = cfg.tfs.map(t => `<button data-tf="${t}" class="${t === st.tf ? 'on' : ''}">${t}</button>`).join('');
  box.onclick = e => { const b = e.target.closest('button'); if (!b) return; st.tf = b.dataset.tf; st.sel = null; st.data = null;
    box.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); poll(); };
  document.querySelectorAll('input[name=mode]').forEach(r => r.onchange = () => { st.mode = r.value; if (st.data) { rebuildLines(st.data); st.version++; } });
  $('#showPools').onchange = e => { st.pools = e.target.checked; st.version++; };
}
(async () => {
  try { buildControls(await (await fetch('/api/config')).json()); } catch (e) { $('#status').textContent = 'terminal injoignable'; return; }
  poll(); renderAlerts(); setInterval(renderAlerts, 15000); requestAnimationFrame(loop);
  window.__term = {st, chart, series, select, draw, layout, poolRect, overlay};      // pour les tests automatiques
})();
})();
