// Grille multi-unites (V16) : le meme actif sur plusieurs unites de temps a la fois (2 a 5 graphiques, unite au choix pour chacun).
// Chaque graphique : bougies (la bougie en cours bouge a chaque transaction), VWAP du jour (+/- 1 ecart-type) et de la semaine, profil de la
// seance colle a l'echelle des prix (POC, VAH, VAL), plus hauts / bas de la veille, de la semaine et du mois precedents.
// Le reticule est synchronise : meme instant et meme prix sur tous les graphiques. Une ligne resume l'alignement des unites (des faits,
// pas un signal : aucun de ces alignements n'a ete valide par le backtest du terminal).
const MTF = (() => {
  'use strict';
  const TFS = ['5m', '15m', '1h', '4h', '1d'];
  const SEC = {'5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400};
  const NAME = {'5m': '5 min', '15m': '15 min', '1h': '1 heure', '4h': '4 heures', '1d': '1 jour'};
  const DEF = ['5m', '15m', '1h', '4h', '1d'];
  let LT = null, root = null, cells = null, charts = [], timer = null, on = false, raf = 0, alignAt = 0;

  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const pct = v => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(2).replace('.', ',') + ' %';
  function ema(vals, n) {
    const k = 2 / (n + 1), out = [];
    let e = null;
    vals.forEach((v, i) => { e = e == null ? v : v * k + e * (1 - k); out.push(i >= n - 1 ? e : null); });
    return out;
  }

  class Mini {
    constructor(host, idx) {
      this.host = host; this.idx = idx; this.data = null; this.bars = []; this.lines = []; this.sig = ''; this.cdKey = '';
      host.className = 'mcell';
      host.innerHTML = `<div class="mhead"><select data-mtf-tf="${idx}" aria-label="Unité de temps du graphique ${idx + 1}">${TFS.map(t => `<option value="${t}">${NAME[t]}</option>`).join('')}</select>` +
        `<span class="mfacts muted small"></span><span class="spacer"></span><span class="mcd muted small" title="Temps restant avant la clôture de la bougie en cours"></span>` +
        `<button class="mini mopen" title="Ouvrir cette unité dans le graphique principal (carnet, poches, zones…)">⤢</button></div>` +
        `<div class="mbody"><div class="chart"></div><canvas class="ov"></canvas></div>`;
      this.body = host.querySelector('.mbody');
      this.ov = host.querySelector('.ov'); this.ctx = this.ov.getContext('2d');
      this.chart = LightweightCharts.createChart(host.querySelector('.chart'), {autoSize: true, crosshair: {mode: LightweightCharts.CrosshairMode.Normal},
        rightPriceScale: {scaleMargins: {top: 0.08, bottom: 0.08}}, timeScale: {timeVisible: true, secondsVisible: false, rightOffset: 8}});
      this.series = this.chart.addCandlestickSeries({borderVisible: false, priceLineVisible: true, priceLineStyle: 2});
      const line = o => this.chart.addLineSeries({lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false, autoscaleInfoProvider: () => null, ...o});
      this.vD = line({lineWidth: 1.5}); this.uD = line({lineWidth: 1, lineStyle: 2}); this.lD = line({lineWidth: 1, lineStyle: 2}); this.vW = line({lineWidth: 1, lineStyle: 1});
      this.chart.subscribeCrosshairMove(p => sync(this, p));
      host.querySelector('select').addEventListener('change', e => { this.setTf(e.target.value); LT.st.mtf.tfs[this.idx] = this.tf; LT.savePrefs(); });
      host.querySelector('.mopen').onclick = () => LT.openTf(this.tf);
      this.applyTheme();
    }
    th() { return Panel.TH[LT.st.theme] || Panel.TH.nuit; }
    applyTheme() {
      const t = this.th();
      this.chart.applyOptions({layout: {background: {type: 'solid', color: t.bg}, textColor: t.text, fontFamily: t.font, fontSize: Math.min(11, t.fontSize)},
        grid: {vertLines: {color: t.grid}, horzLines: {color: t.grid}}, rightPriceScale: {borderColor: t.border}, timeScale: {borderColor: t.border},
        crosshair: {vertLine: {color: t.cross, labelBackgroundColor: t.crossLabel}, horzLine: {color: t.cross, labelBackgroundColor: t.crossLabel}}});
      this.series.applyOptions({upColor: t.up, downColor: t.down, wickUpColor: t.up, wickDownColor: t.down, priceLineColor: t.price});
      this.vD.applyOptions({color: t.vwap}); this.uD.applyOptions({color: t.band}); this.lD.applyOptions({color: t.band});
      this.vW.applyOptions({color: LT.st.theme === 'nuit' ? 'rgba(242,242,242,0.45)' : 'rgba(76,175,80,0.7)'});
      this.levelLines();
      this.sig = '';
    }
    setTf(tf) {
      this.tf = SEC[tf] ? tf : '1h';
      this.host.querySelector('select').value = this.tf;
      this.data = null; this.bars = []; this.series.setData([]); [this.vD, this.uD, this.lD, this.vW].forEach(s => s.setData([]));
      this.load(true);
    }
    async load(reset) {
      const sym = LT.st.symbol, tf = this.tf;
      if (!sym) return;
      let d;
      try { d = await LT.api(`/api/mtf?symbol=${sym}&tf=${tf}`); } catch (e) { this.host.querySelector('.mfacts').textContent = 'indisponible : ' + e.message; return; }
      if (sym !== LT.st.symbol || tf !== this.tf || !d.ready) return;
      const first = !this.data;
      this.data = d;
      const live = this.bars.length ? this.bars[this.bars.length - 1] : null;
      this.bars = d.candles.map(c => ({time: c[0], open: c[1], high: c[2], low: c[3], close: c[4]}));
      const last = this.bars[this.bars.length - 1];
      if (live && last && live.time === last.time) { last.high = Math.max(last.high, live.high); last.low = Math.min(last.low, live.low); last.close = live.close; }
      else if (live && last && live.time > last.time) this.bars.push(live);            // la transaction en direct a deja ouvert la bougie suivante
      this.series.setData(this.bars);
      const T = d.times || [], pts = v => T.map((t, i) => v && v[i] != null ? {time: t, value: v[i]} : {time: t});
      this.vD.setData(pts(d.vwapD));
      this.uD.setData(pts(d.vwapD && d.sdD ? d.vwapD.map((x, i) => x == null || d.sdD[i] == null ? null : x + d.sdD[i]) : null));
      this.lD.setData(pts(d.vwapD && d.sdD ? d.vwapD.map((x, i) => x == null || d.sdD[i] == null ? null : x - d.sdD[i]) : null));
      this.vW.setData(pts(d.vwapW));
      this.levelLines();
      if (first || reset) this.resetView();
      this.facts();
      this.sig = '';
    }
    resetView() {
      const n = this.bars.length; if (!n) return;
      const w = this.chart.timeScale().width() || 400, k = Math.max(1, Panel.profKinds(LT.st.mainOpts).length), f = Math.min(0.55, (k * (this.profW(w) + 8) + 28) / w);
      this.chart.timeScale().setVisibleLogicalRange({from: Math.max(0, n - 110), to: n + Math.ceil(110 * f / (1 - f)) + 3});
    }
    profW(w) { return Math.round(Math.min(90, Math.max(40, w * 0.16))); }
    levelLines() {
      this.lines.forEach(l => this.series.removePriceLine(l)); this.lines = [];
      const d = this.data; if (!d) return;
      (d.levels || []).forEach(l => this.lines.push(this.series.createPriceLine({price: l.price, color: LT.st.theme === 'nuit' ? 'rgba(170,170,170,0.55)' : 'rgba(180,184,196,0.55)',
        lineWidth: 1, lineStyle: 3, axisLabelVisible: false, title: ''})));
    }
    // bougie en cours mise a jour a chaque transaction (meme flux que le graphique principal)
    onTick(price, tms) {
      if (!this.bars.length) return;
      const per = SEC[this.tf], bt = Math.floor(tms / 1000 / per) * per, last = this.bars[this.bars.length - 1];
      if (bt < last.time) return;
      let b;
      if (bt === last.time) { b = last; b.high = Math.max(b.high, price); b.low = Math.min(b.low, price); b.close = price; }
      else { b = {time: bt, open: last.close, high: Math.max(last.close, price), low: Math.min(last.close, price), close: price}; this.bars.push(b); }
      try { this.series.update({...b}); } catch (e) { /* bougie hors d'ordre : la prochaine lecture remettra tout d'aplomb */ }
    }
    // faits de l'unite : variation de la bougie en cours, position face aux moyennes 20 et 50 bougies et a la VWAP du jour
    facts() {
      const b = this.bars, d = this.data;
      if (!b.length || !d) return null;
      const closes = b.map(x => x.close), e20 = ema(closes, 20), e50 = ema(closes, 50), last = b[b.length - 1];
      const m20 = e20[e20.length - 1], m50 = e50[e50.length - 1];
      const ref = d.vwapD || d.vwapW, refName = d.vwapD ? 'VWAP du jour' : 'VWAP de la semaine';    // en 1 jour, la VWAP du jour n'a pas de sens
      let vw = null; if (ref) for (let i = ref.length - 1; i >= 0; i--) if (ref[i] != null) { vw = ref[i]; break; }
      const f = {chg: (last.close / last.open - 1) * 100, ma: m20 == null || m50 == null ? 0 : last.close > m20 && last.close > m50 ? 1 : last.close < m20 && last.close < m50 ? -1 : 0,
        vwap: vw == null ? 0 : last.close > vw ? 1 : -1, poc: d.session && d.session.poc ? (last.close > d.session.poc ? 1 : -1) : 0};
      const up = 'up', dn = 'dn', word = (v, a, b2) => v > 0 ? `<b class="${up}">${a}</b>` : v < 0 ? `<b class="${dn}">${b2}</b>` : '<b class="muted">entre les deux</b>';
      const el = this.host.querySelector('.mfacts');
      el.innerHTML = `<b class="${f.chg >= 0 ? up : dn}">${pct(f.chg)}</b> · moyennes 20 et 50 : ${word(f.ma, 'au-dessus', 'en dessous')} · ${refName} : ${word(f.vwap, 'au-dessus', 'en dessous')}`;
      el.title = `${NAME[this.tf]} : bougie en cours ${pct(f.chg)} ; cours ${f.ma > 0 ? 'au-dessus' : f.ma < 0 ? 'en dessous' : 'entre'} des moyennes 20 et 50 bougies ; ` +
        `${f.vwap > 0 ? 'au-dessus' : 'en dessous'} de la ${refName} ; ${f.poc > 0 ? 'au-dessus' : 'en dessous'} du POC de la séance.`;
      this.f = f;
      return f;
    }
    // dessin par-dessus le graphique : profil de la seance (gris, bout bleu / blanc = surplus acheteurs / vendeurs) et POC, VAH, VAL
    draw() {
      const dpr = window.devicePixelRatio || 1, w = this.body.clientWidth, h = this.body.clientHeight, cv = this.ov;
      if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
      const ctx = this.ctx; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
      const t = this.th(), o = LT.st.mainOpts, d = this.data;
      if (!d) return;
      ctx.font = `500 9px ${t.font}`; ctx.textAlign = 'left'; ctx.textBaseline = 'bottom'; ctx.fillStyle = t.label;
      (d.levels || []).forEach(l => {                                             // nom des niveaux cles, au bord gauche, au-dessus de leur ligne
        const y = this.series.priceToCoordinate(l.price); if (y != null && y > 12 && y < h - 28) ctx.fillText(l.name, 4, y - 1);
      });
      const plotW = this.chart.timeScale().width(), kinds = Panel.profKinds(o), W = Math.round(this.profW(plotW) * (kinds.length > 1 ? 0.8 : 1));
      const r = kinds.length ? Panel.drawProfiles(ctx, this.series, d.profiles || {D: d.session}, kinds, plotW - 1, W, h, t, true) : {used: 0, cols: []};
      const dc = r.cols.find(c => c.k === 'D');
      if (dc) {
        ctx.font = `500 9px ${t.font}`; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
        [[dc.s.poc, 'POC'], [dc.s.vah, 'VAH'], [dc.s.val, 'VAL']].forEach(([px, lab]) => {
          const y = this.series.priceToCoordinate(px); if (y == null || y < 6 || y > h - 28) return;
          ctx.strokeStyle = lab === 'POC' ? 'rgba(236,236,236,.8)' : 'rgba(150,150,150,.45)'; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(dc.x - W - 2, Math.round(y) + 0.5); ctx.lineTo(dc.x, Math.round(y) + 0.5); ctx.stroke();
          ctx.fillStyle = t.label; ctx.fillText(lab, dc.x - W - 4, y);
        });
      }
      const per = SEC[this.tf], ts = this.chart.timeScale();
      const xOf = ms => { const bt = Math.floor(ms / 1000 / per) * per, x = ts.timeToCoordinate(bt); return x != null ? x : (this.bars.length && bt < this.bars[0].time ? 0 : null); };
      Panel.drawTpo(ctx, this.series, xOf, d.tpo, Panel.tpoKinds(o), plotW - (r.cols.length ? r.used + 22 : 0) - 4, h, t, true);
      if (o.absorb && d.absorb) Panel.absMarks(ctx, this.series, xOf, d.absorb, plotW - (r.cols.length ? r.used + 22 : 0) - 4, h, t, true);   // V21
    }
    tick() {
      if (!this.data) return;
      const s = [this.series.priceToCoordinate(this.data.price) | 0, this.body.clientWidth, this.body.clientHeight, this.chart.timeScale().width(), LT.st.theme,
        Panel.profKinds(LT.st.mainOpts).join('') + Panel.tpoKinds(LT.st.mainOpts).join('') + (LT.st.mainOpts.absorb ? 'A' : ''),
        (() => { const r = this.chart.timeScale().getVisibleLogicalRange(); return r ? r.from.toFixed(1) + ':' + r.to.toFixed(1) : ''; })()].join();
      if (s !== this.sig) { this.sig = s; this.draw(); }
      const per = SEC[this.tf], now = LT.serverNow() / 1000, left = Math.max(0, Math.ceil(Math.floor(now / per) * per + per - now));
      const two = n => String(n).padStart(2, '0');
      const txt = 'clôture dans ' + (left >= 86400 ? Math.floor(left / 3600) + ' h' : left >= 3600 ? `${Math.floor(left / 3600)}:${two(Math.floor(left % 3600 / 60))}:${two(left % 60)}` : `${two(Math.floor(left / 60))}:${two(left % 60)}`);
      if (txt !== this.cdKey) { this.cdKey = txt; this.host.querySelector('.mcd').textContent = txt; }
    }
    destroy() { this.chart.remove(); this.host.remove(); }
  }

  // reticule synchronise : l'instant survole devient, sur chaque autre graphique, la bougie de son unite qui le contient
  let syncing = false;
  function sync(src, p) {
    if (syncing) return;
    syncing = true;
    try {
      const price = p && p.point ? src.series.coordinateToPrice(p.point.y) : null, time = p && p.time;
      charts.forEach(c => {
        if (c === src) return;
        if (price == null || time == null || !c.bars.length) { c.chart.clearCrosshairPosition(); return; }
        const bt = Math.floor(time / SEC[c.tf]) * SEC[c.tf];
        if (bt < c.bars[0].time || bt > c.bars[c.bars.length - 1].time) { c.chart.clearCrosshairPosition(); return; }
        c.chart.setCrosshairPosition(price, bt, c.series);
      });
    } finally { syncing = false; }
  }

  // ligne d'alignement : combien d'unites sont au-dessus de leurs moyennes 20 et 50, de la VWAP du jour, du POC de la seance
  function align() {
    const el = root && root.querySelector('.mtfalign'); if (!el) return;
    const fs = charts.map(c => c.facts()).filter(Boolean), n = fs.length;
    if (!n) { el.textContent = ''; return; }
    const cnt = k => fs.filter(f => f[k] > 0).length, cntD = k => fs.filter(f => f[k] < 0).length;
    const part = (k, lab) => { const u = cnt(k), d2 = cntD(k); const cls = u === n ? 'up' : d2 === n ? 'dn' : 'amb';
      return `<b class="${cls}">${u === n ? `toutes au-dessus ${lab}` : d2 === n ? `toutes en dessous ${lab}` : `${u} sur ${n} au-dessus ${lab}`}</b>`; };
    el.innerHTML = `Alignement des ${n} unités : ${part('ma', 'de leurs moyennes 20 et 50 bougies')} · ${part('vwap', 'de la VWAP du jour (de la semaine en 1 jour)')} · ${part('poc', 'du POC de la séance')}`;
  }

  function loop() {
    if (!on) { raf = 0; return; }
    charts.forEach(c => c.tick());
    if (Date.now() - alignAt > 1000) { alignAt = Date.now(); align(); }
    raf = requestAnimationFrame(loop);
  }
  function build() {
    const st = LT.st, n = Math.max(2, Math.min(5, st.mtf.n || 4));
    while (charts.length > n) charts.pop().destroy();
    while (charts.length < n) {
      const el = document.createElement('section'); cells.appendChild(el);
      const c = new Mini(el, charts.length); charts.push(c);
      c.setTf(st.mtf.tfs[c.idx] || DEF[c.idx]);
    }
    cells.className = 'mtfcells n' + n;
    root.querySelectorAll('[data-mtf-n]').forEach(b => b.classList.toggle('on', +b.dataset.mtfN === n));
    setTimeout(() => charts.forEach(c => c.resetView()), 60);
  }
  function init(lt, host) {
    LT = lt; root = host;
    root.innerHTML = `<div class="mtfbar"><span class="muted small">Graphiques</span><span class="seg mini">${[2, 3, 4, 5].map(k => `<button data-mtf-n="${k}">${k}</button>`).join('')}</span>` +
      `<span class="mtfalign small" title="Faits, pas un signal : aucun de ces alignements n'a été validé par le backtest du terminal (le seul filtre validé est la tendance de fond, onglet Lecture)."></span></div><div class="mtfcells"></div>`;
    cells = root.querySelector('.mtfcells');
    root.addEventListener('click', e => {
      const b = e.target.closest('[data-mtf-n]');
      if (b) { LT.st.mtf.n = +b.dataset.mtfN; LT.savePrefs(); build(); }
    });
  }
  function show() {
    on = true;
    build();
    clearInterval(timer);
    timer = setInterval(() => charts.forEach((c, i) => setTimeout(() => c.load(false), i * 250)), 15000);   // bougies fermees et VWAP : toutes les 15 s
    if (!raf) raf = requestAnimationFrame(loop);
  }
  function hide() { on = false; clearInterval(timer); timer = null; }
  function refresh() { charts.forEach(c => { c.data = null; c.bars = []; c.load(true); }); }
  function onTick(price, tms) { if (on) charts.forEach(c => c.onTick(price, tms)); }
  function applyTheme() { charts.forEach(c => c.applyTheme()); }
  function redraw() { charts.forEach(c => { c.sig = ''; c.resetView(); }); }
  return {init, show, hide, refresh, onTick, applyTheme, redraw, TFS, DEF, active: () => on, charts: () => charts};
})();
