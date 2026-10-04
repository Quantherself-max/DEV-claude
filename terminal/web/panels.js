// Panneaux graphiques (V4) : un meme jeu de bougies, trois lectures.
//   main : confluences (mode Essentiel / Confluences / Tous), poches, zones
//   liq  : carte de chaleur des poches de liquidation, balayages, vraies liquidations, profil
//   vp   : VWAP jour / semaine / mois / annee (+ bandes), VWAP ancrees, volume profiles (TF et plage visible)
// Les panneaux partagent l'etat de app.js (window.LT.st) et sont synchronises (zoom, defilement, croix).
class Panel {
  constructor(host, kind) {
    this.host = host; this.kind = kind;
    const T = {main: 'Principal', liq: 'Liquidité', vp: 'VWAP · AVWAP · Volume Profile'}[kind];
    host.classList.add('panel', 'k-' + kind);
    host.innerHTML = `<div class="phead"><span class="ptitle">${T}</span><span class="ptools">${Panel.tools(kind)}</span>` +
      `<button class="pmax" title="Agrandir / revenir à la mise en page">⤢</button></div>` +
      `<div class="pbody"><canvas class="heat"></canvas><div class="chart"></div><canvas class="ov"></canvas><div class="tip" hidden></div></div>`;
    this.body = host.querySelector('.pbody');
    this.heatCv = host.querySelector('.heat'); this.hctx = this.heatCv.getContext('2d');
    this.ov = host.querySelector('.ov'); this.ctx = this.ov.getContext('2d');
    this.tipEl = host.querySelector('.tip');
    this.lines = []; this.layers = {}; this.sig = ''; this.n = 0; this.lastBar = 0; this.key = null; this.stamp = '';
    this.chart = LightweightCharts.createChart(host.querySelector('.chart'), {
      autoSize: true,
      layout: {background: {type: 'solid', color: 'rgba(0,0,0,0)'}, textColor: '#b2b5be', fontSize: 12},
      grid: {vertLines: {color: 'rgba(40,46,64,.35)'}, horzLines: {color: 'rgba(40,46,64,.35)'}},
      rightPriceScale: {borderColor: '#2a2e39', scaleMargins: {top: 0.08, bottom: 0.08}},
      timeScale: {borderColor: '#2a2e39', timeVisible: true, secondsVisible: false, rightOffset: 16},
      crosshair: {mode: LightweightCharts.CrosshairMode.Normal},
    });
    this.series = this.chart.addCandlestickSeries({upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
      wickUpColor: '#26a69a', wickDownColor: '#ef5350', priceLineColor: '#787b86',
      autoscaleInfoProvider: o => this.autoscale(o)});
    this.chart.subscribeClick(p => this.onClick(p));
    this.body.addEventListener('mousemove', ev => this.onMove(ev));
    this.body.addEventListener('mouseleave', () => { this.tipEl.hidden = true; });
    host.querySelector('.pmax').onclick = () => LT.maximize(kind);
    host.querySelector('.ptools').addEventListener('click', ev => this.onTool(ev));
    host.querySelector('.ptools').addEventListener('change', ev => this.onTool(ev));
    this.syncTools();
  }

  // ---------- barre d'outils ----------
  static tools(kind) {
    if (kind === 'main') return `<label title="Seulement les 2 zones les plus importantes de chaque côté du prix"><input type="radio" name="mode" value="ess"> Essentiel</label>` +
      `<label title="Toutes les zones de confluence proches"><input type="radio" name="mode" value="conf"> Confluences</label>` +
      `<label title="Tous les niveaux de la fenêtre"><input type="radio" name="mode" value="all"> Tous</label>` +
      `<label><input type="checkbox" data-opt="pools"> Poches</label>`;
    if (kind === 'liq') return `<span class="seg mini" data-hours><button data-h="24">24 h</button><button data-h="72">3 j</button><button data-h="168">7 j</button><button data-h="0">29 j</button></span>` +
      `<label><input type="checkbox" data-lq="pools"> Poches</label><label><input type="checkbox" data-lq="sweeps"> Balayages</label>` +
      `<label><input type="checkbox" data-lq="real"> Réel</label><label><input type="checkbox" data-lq="profile"> Profil</label>`;
    return `<label><input type="checkbox" data-vp="vD"> J</label><label><input type="checkbox" data-vp="vW"> S</label>` +
      `<label><input type="checkbox" data-vp="vM"> M</label><label><input type="checkbox" data-vp="vY"> A</label>` +
      `<label title="Bandes ±2σ des VWAP affichées"><input type="checkbox" data-vp="bands"> ±2σ</label>` +
      `<label><input type="checkbox" data-vp="avwap"> AVWAP</label>` +
      `<label title="Volume profile des fenêtres choisies (onglet VP)"><input type="checkbox" data-vp="profiles"> VP</label>` +
      `<label title="Volume profile de la plage visible à l'écran, à la résolution de la timeframe"><input type="checkbox" data-vp="range"> Plage visible</label>`;
  }
  syncTools() {
    const st = LT.st, h = this.host;
    h.querySelectorAll('input[name=mode]').forEach(r => r.checked = r.value === st.mode);
    h.querySelectorAll('[data-opt=pools]').forEach(c => c.checked = st.pools);
    h.querySelectorAll('[data-lq]').forEach(c => c.checked = !!st.liqOpts[c.dataset.lq]);
    h.querySelectorAll('[data-vp]').forEach(c => c.checked = !!st.vpOpts[c.dataset.vp]);
    h.querySelectorAll('[data-hours] button').forEach(b => b.classList.toggle('on', +b.dataset.h === st.liqOpts.hours));
  }
  onTool(ev) {
    const t = ev.target, st = LT.st;
    if (ev.type === 'click' && t.closest('[data-hours] button')) {
      st.liqOpts.hours = +t.closest('button').dataset.h; LT.savePrefs(); LT.syncAllTools(); LT.pollHeat(); return;
    }
    if (ev.type !== 'change') return;
    if (t.name === 'mode') { st.mode = t.value; }
    else if (t.dataset.opt === 'pools') { st.pools = t.checked; }
    else if (t.dataset.lq) { st.liqOpts[t.dataset.lq] = t.checked; }
    else if (t.dataset.vp) { st.vpOpts[t.dataset.vp] = t.checked; this.stamp = ''; }
    else return;
    LT.savePrefs(); LT.syncAllTools(); LT.refreshAll();
  }

  visible() { return this.host.offsetParent !== null; }

  // ---------- donnees ----------
  autoscale(orig) {
    const r = orig(), d = LT.st.data;
    if (!r || !d) return r;
    let ex = [];
    if (this.kind === 'main') ex = d.liquidity.pools.map(p => p.price).concat(LT.shownZones(d).map(z => z.mid));
    else if (this.kind === 'liq') ex = d.liquidity.pools.map(p => p.price);
    if (ex.length) {
      r.priceRange.minValue = Math.min(r.priceRange.minValue, ...ex);
      r.priceRange.maxValue = Math.max(r.priceRange.maxValue, ...ex);
    }
    return r;
  }
  setBars(bars, reset) {
    if (reset) {
      this.series.setData(bars); this.n = bars.length;
      this.chart.timeScale().setVisibleLogicalRange({from: Math.max(0, this.n - 130), to: this.n + 16});
      this.lastBar = this.n ? bars[this.n - 1].time : 0; this.stamp = '';
      for (const k in this.layers) { this.chart.removeSeries(this.layers[k].s); delete this.layers[k]; }
    } else {
      bars.filter(b => b.time >= this.lastBar).forEach(b => this.updateBar(b));
    }
  }
  resetView() {
    if (this.n) this.chart.timeScale().setVisibleLogicalRange({from: Math.max(0, this.n - 130), to: this.n + 16});
  }
  updateBar(b) {
    if (b.time < this.lastBar) return;
    try { this.series.update(b); } catch (e) { return; }
    if (b.time > this.lastBar) this.n++;
    this.lastBar = b.time;
  }

  // ---------- geometrie ----------
  layout() {
    const d = LT.st.data; if (!d) return null;
    const ts = this.chart.timeScale(), cs = d.candles;
    let xr = ts.timeToCoordinate(cs[cs.length - 1][0]);
    const plotW = ts.width();
    if (xr == null) xr = plotW - 80;
    const prev = cs.length > 1 ? ts.timeToCoordinate(cs[cs.length - 2][0]) : null;
    return {d, xr, plotW, barW: prev != null ? Math.max(1, xr - prev) : 6};
  }
  timeX(tsec, L) {
    const cs = L.d.candles, n = cs.length, ts = this.chart.timeScale(), per = LT.TF_SEC[LT.st.tf] || 3600;
    if (tsec >= cs[n - 1][0]) return L.xr + (tsec - cs[n - 1][0]) / per * L.barW;
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (cs[mid][0] <= tsec) lo = mid; else hi = mid; }
    const xa = ts.timeToCoordinate(cs[lo][0]), xb = ts.timeToCoordinate(cs[Math.min(n - 1, lo + 1)][0]);
    if (tsec < cs[0][0]) return xa == null ? null : xa - (cs[0][0] - tsec) / per * L.barW;
    if (xa == null || xb == null) return null;
    return xa + (xb - xa) * (tsec - cs[lo][0]) / ((cs[Math.min(n - 1, lo + 1)][0] - cs[lo][0]) || 1);
  }
  poolRect(p, L) {
    const y1 = this.series.priceToCoordinate(p.hi), y0 = this.series.priceToCoordinate(p.lo), yc = this.series.priceToCoordinate(p.price);
    if (y1 == null || y0 == null || yc == null) return null;
    const thick = Math.max(6, Math.abs(y0 - y1));
    let x0 = p.born ? this.timeX(p.born / 1000, L) : null;
    const minLen = 36, born = x0 != null;
    if (x0 == null || L.xr - x0 < minLen) x0 = L.xr - Math.max(minLen, L.plotW * 0.12 * Math.pow(p.rel, 0.7));
    const edge = born && x0 > 0;
    x0 = Math.max(0, x0);
    return {x0, x1: L.xr, yc, thick, len: L.xr - x0, edge};
  }

  // ---------- lignes de prix (mode Tous / zones selectionnees) ----------
  rebuildLines() {
    this.lines.forEach(l => this.series.removePriceLine(l));
    this.lines = [];
    const st = LT.st, d = st.data;
    if (this.kind !== 'main' || !d) return;
    const lv = LT.byId(d.levels);
    let ids = [];
    if (st.mode === 'all') ids = d.levels.filter(l => l.kind !== 'liq' && l.inWindow).map(l => l.id);
    else {
      const set = new Set(st.mode === 'conf' ? LT.ladderZones(d).flatMap(z => z.members) : []);
      if (st.sel && st.sel.type === 'zone') (LT.byId(d.zones)[st.sel.id]?.members || []).forEach(i => set.add(i));
      ids = [...set].filter(i => lv[i] && lv[i].kind !== 'liq');
    }
    if (st.sel && st.sel.type === 'level' && lv[st.sel.id] && !ids.includes(st.sel.id)) ids.push(st.sel.id);
    const style = {vwap: 0, avwap: 0, open: 1, vp: 2, xvp: 2, hl: 4};
    ids.forEach(i => {
      const l = lv[i], sel = st.sel && st.sel.type === 'level' && st.sel.id === i;
      this.lines.push(this.series.createPriceLine({price: l.price, color: LT.levelColor(l), lineWidth: sel ? 2 : 1,
        lineStyle: style[l.kind] ?? 0, axisLabelVisible: false, title: l.name}));
    });
  }

  // ---------- VWAP / AVWAP : series de lignes ----------
  applySeries() {
    if (this.kind !== 'vp') return;
    const st = LT.st, S = st.series, d = st.data, o = st.vpOpts;
    const ok = S && S.ready && d && S.symbol === d.symbol && S.tf === d.tf;
    const want = [];
    if (ok) {
      const PER = LT.PER, bandCol = {D: '#FFB30066', W: '#4CAF5066', M: '#42A5F566', Y: '#EC407A66'};
      const NM = {D: 'VWAP J', W: 'VWAP S', M: 'VWAP M', Y: 'VWAP A'};
      for (const k of ['D', 'W', 'M', 'Y']) {
        if (!o['v' + k] || !S.vwap[k]) continue;
        want.push({id: 'v' + k, name: NM[k], color: PER[k.toLowerCase()], w: 2, v: S.vwap[k]});
        if (o.bands) {
          want.push({id: 'u' + k, name: NM[k] + ' +2σ', color: bandCol[k], w: 1, st: 2, v: S.vwap[k].map((x, i) => x == null || S.sd[k][i] == null ? null : x + 2 * S.sd[k][i]), noLabel: true});
          want.push({id: 'l' + k, name: NM[k] + ' −2σ', color: bandCol[k], w: 1, st: 2, v: S.vwap[k].map((x, i) => x == null || S.sd[k][i] == null ? null : x - 2 * S.sd[k][i]), noLabel: true});
        }
      }
      const AC = ['#E0E0E0', '#B0BEC5', '#90A4AE', '#78909C', '#607D8B', '#546E7A'];
      if (o.avwap) S.avwap.forEach((a, i) => want.push({id: 'a' + i, name: a.label, color: AC[i % AC.length], w: i === 0 ? 2 : 1.5, v: a.v}));
    }
    const stamp = ok ? `${S.symbol}|${S.tf}|${S.times.length}|${S.times[S.times.length - 1]}|${S.stampN || 0}|${want.map(w => w.id).join()}` : 'none';
    if (stamp === this.stamp) return;
    this.stamp = stamp;
    for (const k in this.layers) if (!want.some(w => w.id === k)) { this.chart.removeSeries(this.layers[k].s); delete this.layers[k]; }
    want.forEach(w => {
      let L = this.layers[w.id];
      if (!L) {
        L = this.layers[w.id] = {s: this.chart.addLineSeries({color: w.color, lineWidth: w.w, lineStyle: w.st || 0, lastValueVisible: false,
          priceLineVisible: false, crosshairMarkerVisible: false, autoscaleInfoProvider: () => null})};
      }
      L.meta = w;
      L.s.setData(S.times.map((t, i) => w.v[i] == null ? {time: t} : {time: t, value: w.v[i]}));
    });
  }

  // ---------- dessin ----------
  tick() {
    const st = LT.st, d = st.data;
    if (!d || !this.visible()) return;
    const ts = this.chart.timeScale(), r = ts.getVisibleLogicalRange();
    const s = [this.series.priceToCoordinate(d.price) | 0, this.series.priceToCoordinate(d.price * 1.03) | 0,
      ts.timeToCoordinate(d.candles[d.candles.length - 1][0]) | 0, r ? r.from.toFixed(1) + ':' + r.to.toFixed(1) : '',
      this.body.clientWidth, this.body.clientHeight, st.version, (LT.livePrice(d) / d.price).toFixed(4)].join();
    if (s !== this.sig) { this.sig = s; this.draw(); }
  }
  draw() {
    const dpr = window.devicePixelRatio || 1, w = this.body.clientWidth, h = this.body.clientHeight;
    for (const cv of [this.ov, this.heatCv]) {
      if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    }
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0); this.hctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.ctx.clearRect(0, 0, w, h); this.hctx.clearRect(0, 0, w, h);
    const L = this.layout(); if (!L) return;
    if (this.kind === 'liq') { this.drawHeat(L, w, h); this.drawLiq(L, w, h); }
    else if (this.kind === 'vp') { this.applySeries(); this.drawVP(L, w, h); }
    else this.drawMain(L, w, h);
  }
  tag(x, y, text, color, bg, bold) {
    const ctx = this.ctx;
    ctx.font = (bold ? '700 ' : '500 ') + '11px sans-serif';
    const tw = ctx.measureText(text).width + 12, th = 17;
    ctx.fillStyle = bg; ctx.beginPath(); (ctx.roundRect ? ctx.roundRect(x, y - th / 2, tw, th, 8) : ctx.rect(x, y - th / 2, tw, th)); ctx.fill();
    ctx.fillStyle = color; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(text, x + 6, y + 0.5);
    return tw;
  }
  drawPools(L, h) {
    const ctx = this.ctx, st = LT.st, {d, plotW} = L, pills = [];
    if (!(st.pools || this.kind === 'liq') || (this.kind === 'liq' && !st.liqOpts.pools)) return;
    const rgba = LT.rgba;
    LT.shownPools(d, this.kind === 'liq').forEach(({p, i}) => {
      const r = this.poolRect(p, L); if (!r) return;
      const col = p.side === 'long' ? LT.COL_L : LT.COL_S;
      const a = Math.min(0.9, 0.22 + 0.55 * Math.pow(p.rel, 0.8) + (p.magnet ? 0.1 : 0));
      const g = ctx.createLinearGradient(r.x0, 0, r.x1, 0);
      g.addColorStop(0, rgba(col, r.edge ? a * 0.55 : 0.02)); g.addColorStop(r.edge ? 0.04 : 0.55, rgba(col, a * (r.edge ? 0.9 : 0.55))); g.addColorStop(1, rgba(col, a));
      ctx.fillStyle = rgba(col, a * 0.1); ctx.fillRect(r.x0, r.yc - r.thick * 0.9, r.len, r.thick * 1.8);
      ctx.fillStyle = g; ctx.fillRect(r.x0, r.yc - r.thick / 2, r.len, r.thick);
      if (r.edge) { ctx.fillStyle = rgba(col, Math.min(1, a + 0.25)); ctx.fillRect(r.x0, r.yc - r.thick / 2, 2, r.thick); }
      if (st.sel && st.sel.type === 'pool' && st.sel.id === i) { ctx.strokeStyle = rgba(col, 1); ctx.lineWidth = 1.5; ctx.strokeRect(r.x0, r.yc - r.thick / 2 - 2, r.len, r.thick + 4); }
      const dist = (p.price / LT.livePrice(d) - 1) * 100;
      pills.push({y: r.yc, x1: r.x1, col, magnet: p.magnet, text: (p.magnet ? 'AIMANT ' : '') + LT.fmtP(p.price) + '  ' + LT.fmtPct(dist)});
    });
    LT.placeLabels(pills, 19, 12, h - 30).forEach(it => {
      ctx.font = (it.magnet ? '700 ' : '500 ') + '11px sans-serif';
      const x = Math.min(it.x1 + 10, plotW - ctx.measureText(it.text).width - 14);
      if (Math.abs(it.ly - it.y) > 2) { ctx.strokeStyle = rgba(it.col, 0.6); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(it.x1, it.y); ctx.lineTo(x, it.ly); ctx.stroke(); }
      this.tag(x, it.ly, it.text, it.magnet ? '#0b0e11' : '#fff', rgba(it.col, it.magnet ? 0.92 : 0.55), it.magnet);
    });
  }
  drawMain(L, w, h) {
    const ctx = this.ctx, st = LT.st, {d, plotW} = L, byId = LT.byId, fmtP = LT.fmtP, pr = LT.pr;
    const selZ = st.sel && st.sel.type === 'zone' ? st.sel.id : null;
    const zset = new Map(LT.shownZones(d).map(z => [z.id, z]));
    if (selZ && !zset.has(selZ)) { const z = byId(d.zones)[selZ]; if (z) zset.set(selZ, z); }
    const zl = [];
    zset.forEach(z => {
      const yt = this.series.priceToCoordinate(z.hi), yb = this.series.priceToCoordinate(z.lo);
      if (yt == null || yb == null) return;
      const span = Math.abs(yb - yt), hh = Math.max(6, span), y = Math.min(yt, yb) - (hh - span) / 2, sel = z.id === selZ;
      ctx.fillStyle = `rgba(255,179,0,${sel ? 0.2 : 0.07 + 0.025 * Math.min(4, z.score)})`;
      ctx.fillRect(0, y, plotW, hh);
      if (sel) { ctx.strokeStyle = 'rgba(255,179,0,.85)'; ctx.lineWidth = 1; ctx.strokeRect(0.5, y + 0.5, plotW - 1, hh - 1); }
      if (st.mode === 'ess') zl.push({y: y + hh / 2, z});
    });
    this.drawPools(L, h);
    const lv = byId(d.levels);
    if (st.mode === 'ess') LT.placeLabels(zl, 17, 12, h - 30).forEach(it => {
      const z = it.z, ar = z.side === 'above' ? '▲' : z.side === 'below' ? '▼' : '◆', col = z.side === 'above' ? '#3ddc97' : z.side === 'below' ? '#ff6b6b' : '#ffb300';
      const reach = z.prob && z.side !== 'in' ? ' · ' + pr(z.prob.reach['24']) + '/24 h' : '';
      const txt = `${ar} ${fmtP(z.mid)}  ${'●'.repeat(Math.min(5, z.score))}${reach}`;
      ctx.font = '600 11px sans-serif';
      const tw = ctx.measureText(txt).width + 18;
      ctx.fillStyle = 'rgba(11,14,17,.9)'; ctx.fillRect(10, it.ly - 9, tw, 18);
      ctx.fillStyle = col; ctx.fillRect(10, it.ly - 9, 3, 18);
      ctx.fillStyle = '#e1e3ea'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(txt, 19, it.ly + 0.5);
    });
    const names = new Map();
    if (st.mode === 'all') d.levels.filter(l => l.kind !== 'liq' && l.inWindow).forEach(l => names.set(l.id, l));
    if (selZ) (byId(d.zones)[selZ]?.members || []).forEach(i => lv[i] && lv[i].kind !== 'liq' && names.set(i, lv[i]));
    if (st.sel && st.sel.type === 'level' && lv[st.sel.id]) names.set(st.sel.id, lv[st.sel.id]);
    const lab = [];
    names.forEach(l => { const y = this.series.priceToCoordinate(l.price); if (y != null) lab.push({y, l}); });
    LT.placeLabels(lab, 15, 12, h - 30).forEach(it => {
      const c = LT.levelColor(it.l);
      if (Math.abs(it.ly - it.y) > 2) { ctx.strokeStyle = 'rgba(180,184,196,.5)'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(0, it.y); ctx.lineTo(10, it.ly); ctx.stroke(); }
      ctx.font = '500 11px sans-serif';
      const txt = it.l.name + '  ' + fmtP(it.l.price), tw = ctx.measureText(txt).width + 22, xx = st.mode === 'ess' ? 190 : 10;
      ctx.fillStyle = 'rgba(11,14,17,.88)'; ctx.fillRect(xx, it.ly - 8, tw, 16);
      ctx.fillStyle = c; ctx.fillRect(xx, it.ly - 8, 3, 16);
      ctx.fillStyle = '#d1d4dc'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(txt, xx + 9, it.ly + 0.5);
    });
  }

  // ---- carte de chaleur (couche SOUS le graphique) ----
  drawHeat(L, w, h) {
    const H = LT.st.heat, hctx = this.hctx; if (!H || !H.ready || !H.img) return;
    const x0 = this.timeX(H.t0 / 1000, L), x1 = this.timeX((H.t0 + H.n * H.dt) / 1000, L);
    if (x0 == null || x1 == null) return;
    hctx.save();
    hctx.beginPath(); hctx.rect(0, 0, Math.min(L.plotW, L.xr + L.barW * 1.5), h - 28); hctx.clip();
    hctx.imageSmoothingEnabled = true;
    const rowP = j => Math.exp((H.b0 + j) * H.step), K = 4;
    for (let j0 = 0; j0 < H.m; j0 += K) {
      const j1 = Math.min(H.m, j0 + K);
      const yb = this.series.priceToCoordinate(rowP(j0)), yt = this.series.priceToCoordinate(rowP(j1));
      if (yb == null || yt == null || yb < -20 || yt > h + 20) continue;
      hctx.drawImage(H.img, 0, H.m - j1, H.n, j1 - j0, x0, yt, x1 - x0, Math.max(1, yb - yt) + 0.5);
    }
    hctx.restore();
  }
  drawLiq(L, w, h) {
    const ctx = this.ctx, st = LT.st, o = st.liqOpts, {plotW} = L, H = st.heat, rgba = LT.rgba;
    if (H && H.ready && H.img && o.profile) {
      const maxLen = plotW * 0.16, i = H.n - 1;
      for (let j = 0; j < H.m; j++) {
        const vl = H.L[j * H.n + i], vs = H.S[j * H.n + i], v = Math.max(vl, vs); if (v < 40) continue;
        const yb = this.series.priceToCoordinate(Math.exp((H.b0 + j) * H.step)), yt = this.series.priceToCoordinate(Math.exp((H.b0 + j + 1) * H.step));
        if (yb == null || yt == null) continue;
        ctx.fillStyle = rgba(vs > vl ? LT.COL_S : LT.COL_L, 0.55);
        const len = v / 255 * maxLen;
        ctx.fillRect(plotW - len, yt, len, Math.max(1.2, yb - yt));
      }
    }
    this.drawPools(L, h);
    if (H && H.ready && o.sweeps) H.sweeps.forEach(s => {
      const x = this.timeX(s.t / 1000, L), y = this.series.priceToCoordinate(s.price);
      if (x == null || y == null || x < 0 || x > plotW) return;
      const r = 4 + Math.min(8, s.frac * 30);
      ctx.save(); ctx.translate(x, y); ctx.rotate(Math.PI / 4);
      ctx.fillStyle = rgba(s.side === 'long' ? LT.COL_L : LT.COL_S, 0.9); ctx.strokeStyle = '#0b0e11'; ctx.lineWidth = 2;
      ctx.fillRect(-r / 1.4, -r / 1.4, r * 1.4, r * 1.4); ctx.strokeRect(-r / 1.4, -r / 1.4, r * 1.4, r * 1.4); ctx.restore();
    });
    if (st.liqs && st.liqs.events && o.real) st.liqs.events.forEach(e => {
      const x = this.timeX(e.t / 1000, L), y = this.series.priceToCoordinate(e.price);
      if (x == null || y == null || x < 0 || x > plotW) return;
      const r = Math.max(3, Math.min(18, 2.5 + Math.sqrt(e.usd / 25000)));
      ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832);
      ctx.fillStyle = rgba(e.side === 'long' ? LT.COL_L : LT.COL_S, 0.45); ctx.fill();
      ctx.strokeStyle = rgba(e.side === 'long' ? LT.COL_L : LT.COL_S, 0.95); ctx.lineWidth = 1.5; ctx.stroke();
    });
  }

  // ---- VWAP / AVWAP / volume profiles ----
  hist(rows, poc, vah, val, side, base, maxFrac = 0.22) {
    const ctx = this.ctx, L = this._L, plotW = L.plotW;
    const maxV = Math.max(...rows.map(r => r[2])) || 1, maxLen = plotW * maxFrac;
    rows.forEach(([lo, hi, v]) => {
      const y1 = this.series.priceToCoordinate(hi), y0 = this.series.priceToCoordinate(lo);
      if (y1 == null || y0 == null) return;
      const len = v / maxV * maxLen, mid = (lo + hi) / 2, inVA = mid >= val && mid <= vah, isPoc = poc >= lo && poc <= hi;
      ctx.fillStyle = isPoc ? 'rgba(255,179,0,.75)' : LT.rgba(base, inVA ? 0.42 : 0.2);
      ctx.fillRect(side === 'right' ? plotW - len : 0, y1, len, Math.max(1, y0 - y1 - 0.6));
    });
  }
  rangeProfile(d) {
    const r = this.chart.timeScale().getVisibleLogicalRange(); if (!r) return null;
    const cs = d.candles, off = this.n - cs.length;
    const i0 = Math.max(0, Math.ceil(r.from) - off), i1 = Math.min(cs.length - 1, Math.floor(r.to) - off);
    if (i1 - i0 < 3) return null;
    let lo = Infinity, hi = -Infinity;
    for (let i = i0; i <= i1; i++) { lo = Math.min(lo, cs[i][3]); hi = Math.max(hi, cs[i][2]); }
    const N = 90, step = (hi - lo) / N || 1, rows = new Array(N).fill(0);
    for (let i = i0; i <= i1; i++) {
      const c = cs[i], v = c[5] || 0, a = c[3], b = c[2], span = Math.max(b - a, step * 0.2);
      if (v <= 0) continue;
      const j0 = Math.max(0, Math.floor((a - lo) / step)), j1 = Math.min(N - 1, Math.floor((b - lo) / step));
      for (let j = j0; j <= j1; j++) {
        const ov = Math.min(b, lo + (j + 1) * step) - Math.max(a, lo + j * step);
        rows[j] += v * Math.max(ov, 0) / span;
      }
    }
    const tot = rows.reduce((p, q) => p + q, 0); if (!(tot > 0)) return null;
    let pocJ = 0; rows.forEach((v, j) => { if (v > rows[pocJ]) pocJ = j; });
    let acc = rows[pocJ], up = pocJ, dn = pocJ;
    while (acc < tot * 0.7 && (up < N - 1 || dn > 0)) {
      const u = up < N - 1 ? rows[up + 1] : -1, dd = dn > 0 ? rows[dn - 1] : -1;
      if (u >= dd) { up++; acc += rows[up]; } else { dn--; acc += rows[dn]; }
    }
    return {rows: rows.map((v, j) => [lo + j * step, lo + (j + 1) * step, v]), poc: lo + (pocJ + 0.5) * step, vah: lo + (up + 1) * step, val: lo + dn * step,
      bars: i1 - i0 + 1};
  }
  drawVP(L, w, h) {
    this._L = L;
    const ctx = this.ctx, st = LT.st, o = st.vpOpts, {d, plotW} = L, fmtP = LT.fmtP, labels = [];
    const vd = st.vpd && st.vpd.ready && st.vpd.symbol === d.symbol && st.vpd.tf === d.tf ? st.vpd : null;
    if (o.profiles && vd && vd.profiles.length) {
      const focus = vd.profiles.find(p => p.id === st.vpFocus) || vd.profiles[0];
      this.hist(focus.rows, focus.poc, focus.vah, focus.val, 'right', [76, 141, 255]);
      vd.profiles.forEach((p, i) => {
        const xs = Math.max(0, this.timeX(p.start / 1000, L) ?? 0), isF = p.id === focus.id;
        [['POC', p.poc, 'rgba(255,179,0,.9)', 1.5, []], ['VAH', p.vah, 'rgba(120,170,255,.8)', 1, [4, 3]], ['VAL', p.val, 'rgba(120,170,255,.8)', 1, [4, 3]]].forEach(([nm, px, col, lw, dash]) => {
          const y = this.series.priceToCoordinate(px); if (y == null) return;
          ctx.strokeStyle = col; ctx.globalAlpha = isF ? 1 : 0.55; ctx.lineWidth = lw; ctx.setLineDash(dash);
          ctx.beginPath(); ctx.moveTo(xs, y); ctx.lineTo(plotW, y); ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
          if (nm === 'POC' || isF) labels.push({y, x: xs, text: `${p.label} ${nm} ${fmtP(px)}`, col});
        });
      });
    }
    if (o.range) {
      const rp = this.rangeProfile(d);
      if (rp) {
        this.hist(rp.rows, rp.poc, rp.vah, rp.val, 'left', [171, 71, 188], 0.2);
        const y = this.series.priceToCoordinate(rp.poc);
        if (y != null) labels.push({y, x: 6, text: `POC visible ${fmtP(rp.poc)}`, col: 'rgba(255,179,0,.9)', left: true});
      }
    }
    // etiquettes des VWAP / AVWAP au bord droit
    const lay = this.layers;
    for (const k in lay) {
      const m = lay[k].meta; if (!m || m.noLabel) continue;
      let v = null; for (let i = m.v.length - 1; i >= 0; i--) if (m.v[i] != null) { v = m.v[i]; break; }
      const y = v == null ? null : this.series.priceToCoordinate(v);
      if (y != null) labels.push({y, x: plotW - 4, text: `${m.name} ${fmtP(v)}`, col: m.color, right: true});
    }
    LT.placeLabels(labels.filter(l => l.y > 6 && l.y < h - 34), 16, 12, h - 30).forEach(it => {
      ctx.font = '600 11px sans-serif';
      const tw = ctx.measureText(it.text).width + 14, x = it.right ? Math.max(4, it.x - tw - 60) : Math.min(plotW - tw - 4, Math.max(4, it.x));
      if (Math.abs(it.ly - it.y) > 2) { ctx.strokeStyle = 'rgba(180,184,196,.4)'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x + tw / 2, it.y); ctx.lineTo(x + tw / 2, it.ly); ctx.stroke(); }
      ctx.fillStyle = 'rgba(11,14,17,.88)'; ctx.fillRect(x, it.ly - 8, tw, 16);
      ctx.fillStyle = it.col; ctx.fillRect(x, it.ly - 8, 3, 16);
      ctx.fillStyle = '#d1d4dc'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(it.text, x + 8, it.ly + 0.5);
    });
  }

  // ---------- interactions ----------
  onClick(p) {
    const st = LT.st, d = st.data, L = this.layout();
    if (!p.point || !d || !L) return;
    const {x, y} = p.point;
    if (this.kind === 'vp') return;
    if (this.kind === 'liq' || st.pools) {
      for (const {p: pool, i} of LT.shownPools(d, this.kind === 'liq')) {
        const r = this.poolRect(pool, L);
        if (r && x >= r.x0 - 4 && x <= r.x1 + 130 && Math.abs(y - r.yc) <= r.thick / 2 + 5) return LT.select({type: 'pool', id: i});
      }
    }
    if (this.kind === 'liq') return LT.select(null);
    const zs = st.mode === 'ess' ? LT.essentialZones(d) : LT.ladderZones(d);
    for (const z of zs) {
      const a = this.series.priceToCoordinate(z.hi), b = this.series.priceToCoordinate(z.lo);
      if (a == null || b == null) continue;
      const mid = (a + b) / 2, half = Math.max(5, Math.abs(a - b) / 2 + 3);
      if (Math.abs(y - mid) <= half) return LT.select({type: 'zone', id: z.id});
    }
    let best = null, bd = 7;
    d.levels.forEach(l => {
      if (l.kind === 'liq') return;
      const visible = st.mode === 'all' ? l.inWindow : st.mode === 'conf' && zs.some(z => z.members.includes(l.id));
      const yy = this.series.priceToCoordinate(l.price);
      if (visible && yy != null && Math.abs(yy - y) < bd) { bd = Math.abs(yy - y); best = l; }
    });
    LT.select(best ? {type: 'level', id: best.id} : null);
  }
  onMove(ev) {
    const st = LT.st, H = st.heat, tip = this.tipEl;
    if (this.kind !== 'liq' || !H || !H.ready || !st.data) { tip.hidden = true; return; }
    const r = this.body.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top, L = this.layout();
    if (!L || x > L.plotW) { tip.hidden = true; return; }
    const price = this.series.coordinateToPrice(y), tt = this.chart.timeScale().coordinateToTime(x);
    if (price == null || tt == null) { tip.hidden = true; return; }
    const j = Math.floor(Math.log(price) / H.step) - H.b0, i = Math.floor((tt * 1000 - H.t0) / H.dt);
    if (j < 0 || j >= H.m || i < 0 || i >= H.n) { tip.hidden = true; return; }
    const vl = H.L[j * H.n + i], vs = H.S[j * H.n + i], v = Math.max(vl, vs);
    const lo = Math.exp((H.b0 + j) * H.step), hi = Math.exp((H.b0 + j + 1) * H.step);
    const usd = v ? H.ref * Math.pow(v / 255, 1 / 0.85) * price : 0;
    tip.innerHTML = `<b>${LT.fmtP(lo)} – ${LT.fmtP(hi)}</b><br>${new Date(tt * 1000).toLocaleString('fr-FR', {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'})}<br>` +
      (v ? `<span class="${vs > vl ? 'dn' : 'up'}">${vs > vl ? 'Liquidations de shorts' : 'Liquidations de longs'}</span> ≈ <b>${LT.usdFmt(usd)}</b><br><span class="muted">estimation à partir de l'Open Interest</span>` : '<span class="muted">pas de poche estimée ici</span>');
    tip.hidden = false; tip.style.left = Math.min(r.width - 270, x + 14) + 'px'; tip.style.top = Math.max(4, y - 60) + 'px';
  }
}
