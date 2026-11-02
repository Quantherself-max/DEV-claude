// Graphique : bougies + volume + VWAP de seance (et bandes) + VWAP Globex, niveaux en lignes de prix, panneau CVD / delta synchronise, et une couche canvas
// par-dessus le prix (profil de volume colle a l'echelle des prix, zones de confluence, bulles des gros ordres).
const NQChart = (() => {
  'use strict';
  const LC = LightweightCharts;
  const THEMES = {
    nuit: {up: '#3b82f6', dn: '#e5e7eb', volUp: 'rgba(59,130,246,.30)', volDn: 'rgba(229,231,235,.22)'},
    classic: {up: '#26a69a', dn: '#ef5350', volUp: 'rgba(38,166,154,.30)', volDn: 'rgba(239,83,80,.28)'},
  };
  const LEVEL_STYLE = {   // [couleur, epaisseur, style : 0 plein, 1 pointille, 2 tirets]
    pdh: ['#f5a97f', 1, 2], pdl: ['#f5a97f', 1, 2], pdc: ['#f5a97f', 1, 1], ppoc: ['#f472b6', 2, 0], pvah: ['#f472b6', 1, 2], pval: ['#f472b6', 1, 2],
    onh: ['#b794f6', 1, 1], onl: ['#b794f6', 1, 1], asih: ['#8b7ab8', 1, 1], asil: ['#8b7ab8', 1, 1], lonh: ['#9c88d6', 1, 1], lonl: ['#9c88d6', 1, 1],
    open: ['#5eead4', 1, 1], ibh: ['#5eead4', 1, 2], ibl: ['#5eead4', 1, 2], poc: ['#f472b6', 2, 0], vah: ['#f472b6', 1, 2], val: ['#f472b6', 1, 2],
    r100: ['#4b5563', 1, 1], r50: ['#323945', 1, 1],
    // structure : semaine / mois / POC vierges / single prints
    wpoc: ['#c084fc', 2, 0], wvah: ['#c084fc', 1, 2], wval: ['#c084fc', 1, 2], pwpoc: ['#a78bfa', 1, 0], pwvah: ['#a78bfa', 1, 2], pwval: ['#a78bfa', 1, 2],
    pwh: ['#a78bfa', 1, 1], pwl: ['#a78bfa', 1, 1], mpoc: ['#38bdf8', 2, 0], mvah: ['#38bdf8', 1, 2], mval: ['#38bdf8', 1, 2],
    npoc: ['#fb7185', 2, 1], nwpoc: ['#f43f5e', 2, 1], sph: ['#fbbf24', 1, 1], spl: ['#fbbf24', 1, 1],
  };
  const MINOR = new Set(['wvah', 'wval', 'pwvah', 'pwval', 'mvah', 'mval', 'pwpoc']);   // bords des profils composites : seulement en « Tous »
  const SHORT = {'High veille': 'H veille', 'Low veille': 'L veille', 'Clôture veille': 'Clôt. veille', 'POC veille': 'POC veille', 'VAH veille': 'VAH veille',
    'VAL veille': 'VAL veille', 'Ouverture 9h30': 'Open 9h30'};

  let chart, cvdChart, candle, vol, vwapS = {}, vwapG, vwapW = {}, vwapM = {}, cvdLine, dHist, overlay, ctx;
  let rows = [];                       // [{t, o, h, l, c, v, d, vr:{...}, vg, cr, cg}] : tout ce que le serveur a donne, par barre
  let step = 60, theme = 'nuit', tz = 'paris', cvdScope = 'rth';
  let profile = null, profile2 = null, vpMode = 'rth', levelMode = 'key', levels = [], zones = [], bigs = [], marks = [], singles = [];
  let opts = {zones: false, bigs: true, abs: true, vwapW: true, vwapM: false, singles: true};
  let lines = [], lineSig = '', sig = '', syncing = false;
  const listeners = {legend: null};

  const tzName = () => tz === 'et' ? 'America/New_York' : 'Europe/Paris';
  const fmtTime = (sec, withDate) => new Intl.DateTimeFormat('fr-FR', Object.assign({timeZone: tzName(), hour: '2-digit', minute: '2-digit', hourCycle: 'h23'},
    withDate ? {day: '2-digit', month: '2-digit'} : {})).format(new Date(sec * 1000));
  const common = () => ({
    autoSize: true,
    layout: {background: {color: '#0b0e11'}, textColor: '#aab0bd', fontSize: 11},
    grid: {vertLines: {color: '#141925'}, horzLines: {color: '#141925'}},
    crosshair: {mode: 0},
    rightPriceScale: {borderColor: '#2a2e39', minimumWidth: 76},
    timeScale: {borderColor: '#2a2e39', timeVisible: true, secondsVisible: false, rightOffset: 10, barSpacing: 7, minBarSpacing: 1.5,
      tickMarkFormatter: (t, type) => type >= 3 ? fmtTime(t) : fmtTime(t, true).slice(0, 5)},
    localization: {timeFormatter: t => fmtTime(t, true) + ' ' + (tz === 'et' ? 'ET' : 'Paris')},
  });

  function init(elPrice, elCvd, canvas) {
    overlay = canvas; ctx = canvas.getContext('2d');
    chart = LC.createChart(elPrice, Object.assign(common(), {timeScale: Object.assign(common().timeScale, {visible: false})}));
    cvdChart = LC.createChart(elCvd, common());
    const th = THEMES[theme];
    candle = chart.addCandlestickSeries({upColor: th.up, downColor: th.dn, borderVisible: false, wickUpColor: th.up, wickDownColor: th.dn,
      priceFormat: {type: 'price', precision: 2, minMove: 0.25}});
    vol = chart.addHistogramSeries({priceFormat: {type: 'volume'}, priceScaleId: 'vol', lastValueVisible: false, priceLineVisible: false});
    chart.priceScale('vol').applyOptions({scaleMargins: {top: 0.86, bottom: 0}});
    // `auto: false` : la ligne ne compte pas dans l'echelle automatique (les bandes a ±2σ, a 100 points du prix, ecraseraient les bougies)
    const line = (color, w, style, title, auto = true) => chart.addLineSeries(Object.assign({color, lineWidth: w, lineStyle: style, priceLineVisible: false, lastValueVisible: !!title,
      title: title || '', crosshairMarkerVisible: false, priceFormat: {type: 'price', precision: 2, minMove: 0.25}}, auto ? {} : {autoscaleInfoProvider: () => null}));
    vwapS = {v: line('#ffb300', 2, 0, 'VWAP'), u1: line('rgba(255,179,0,.65)', 1, 2, '', false), l1: line('rgba(255,179,0,.65)', 1, 2, '', false),
      u2: line('rgba(255,179,0,.38)', 1, 1, '', false), l2: line('rgba(255,179,0,.38)', 1, 1, '', false)};
    vwapG = line('rgba(122,162,255,.55)', 1, 2, '', false);
    // VWAP de la semaine (violet) et du mois (bleu ciel), avec leur bande ±1σ
    vwapW = {v: line('#c084fc', 2, 0, 'VWAP sem.', false), u1: line('rgba(192,132,252,.45)', 1, 2, '', false), l1: line('rgba(192,132,252,.45)', 1, 2, '', false)};
    vwapM = {v: line('#38bdf8', 2, 0, 'VWAP mois', false), u1: line('rgba(56,189,248,.40)', 1, 2, '', false), l1: line('rgba(56,189,248,.40)', 1, 2, '', false)};
    cvdLine = cvdChart.addLineSeries({color: '#4c8dff', lineWidth: 2, priceLineVisible: false, title: 'CVD', priceFormat: {type: 'volume'}});
    dHist = cvdChart.addHistogramSeries({priceScaleId: 'delta', priceFormat: {type: 'volume'}, lastValueVisible: false, priceLineVisible: false});
    cvdChart.priceScale('delta').applyOptions({scaleMargins: {top: 0.70, bottom: 0}});
    const link = (a, b) => a.timeScale().subscribeVisibleLogicalRangeChange(r => {
      if (syncing || !r) return;
      syncing = true; try { b.timeScale().setVisibleLogicalRange(r); } finally { syncing = false; }
    });
    link(chart, cvdChart); link(cvdChart, chart);
    chart.subscribeCrosshairMove(p => crosshair(p));
    cvdChart.subscribeCrosshairMove(p => {
      if (typeof chart.setCrosshairPosition !== 'function') return;
      if (!p.time) { chart.clearCrosshairPosition(); return; }
      const r = byTime(p.time); if (r) chart.setCrosshairPosition(r.c, p.time, candle);
    });
    new ResizeObserver(() => { sig = ''; }).observe(elPrice);
    requestAnimationFrame(loop);
  }

  const byTime = t => { for (let i = rows.length - 1; i >= 0; i--) if (rows[i].t === t) return rows[i]; return null; };

  function crosshair(p) {
    const r = p && p.time ? byTime(p.time) : rows[rows.length - 1];
    if (listeners.legend) listeners.legend(r || null, !!(p && p.time));
    if (p && p.time && r && typeof cvdChart.setCrosshairPosition === 'function') {
      const v = cvdScope === 'rth' ? r.cr : r.cg;
      if (v != null) cvdChart.setCrosshairPosition(v, p.time, cvdLine);
    } else if (typeof cvdChart.clearCrosshairPosition === 'function') cvdChart.clearCrosshairPosition();
  }

  // ---------- donnees ----------
  const lineData = (key) => rows.map(r => {
    const v = key === 'vg' ? r.vg : r.vr[key];
    return v == null ? {time: r.t} : {time: r.t, value: v};
  });
  const anchData = (src, key, on) => rows.map(r => { const v = on && r[src] ? r[src][key] : null; return v == null ? {time: r.t} : {time: r.t, value: v}; });
  const pt = (r, src, key, on) => { const v = on && r[src] ? r[src][key] : null; return v == null ? {time: r.t} : {time: r.t, value: v}; };
  const cvdData = () => rows.map(r => { const v = cvdScope === 'rth' ? r.cr : r.cg; return v == null ? {time: r.t} : {time: r.t, value: v}; });
  const th = () => THEMES[theme];
  const barOf = r => ({time: r.t, open: r.o, high: r.h, low: r.l, close: r.c});
  const volOf = r => ({time: r.t, value: r.v, color: r.c >= r.o ? th().volUp : th().volDn});
  const deltaOf = r => ({time: r.t, value: r.d, color: r.d >= 0 ? 'rgba(61,220,151,.75)' : 'rgba(255,107,107,.75)'});

  function pick(p, i) {
    const vr = {};
    for (const k of ['v', 'u1', 'l1', 'u2', 'l2']) vr[k] = p.vwapRth[k][i];
    const sub = s => s ? {v: s.v[i], u1: s.u1[i], l1: s.l1[i]} : null;
    return Object.assign({}, p.bars[i], {vr, vg: p.vwapGx.v[i], vw: sub(p.vwapWeek), vm: sub(p.vwapMonth), cr: p.cvdRth[i], cg: p.cvdGx[i]});
  }

  function redrawAll() {
    candle.setData(rows.map(barOf)); vol.setData(rows.map(volOf));
    for (const k of Object.keys(vwapS)) vwapS[k].setData(lineData(k));
    vwapG.setData(lineData('vg'));
    for (const k of ['v', 'u1', 'l1']) { vwapW[k].setData(anchData('vw', k, opts.vwapW)); vwapM[k].setData(anchData('vm', k, opts.vwapM)); }
    cvdLine.setData(cvdData()); dHist.setData(rows.map(deltaOf));
    applyMarkers();
  }

  // full : remplace tout (changement d'unite de temps, premier chargement) ; sinon met a jour la fin
  function apply(p, full) {
    step = p.step / 1000;                 // le serveur donne des ms ; les temps du graphique sont en secondes
    marks = p.absorptions || []; bigs = p.bigs || [];
    if (full) {
      rows = p.bars.map((_, i) => pick(p, i));
      redrawAll();
      const n = rows.length;
      if (n) { chart.timeScale().setVisibleLogicalRange({from: Math.max(-2, n - 150), to: n + 8}); }
    } else {
      for (let i = 0; i < p.bars.length; i++) {
        const r = pick(p, i), last = rows[rows.length - 1];
        if (last && r.t < last.t) continue;
        if (last && r.t === last.t) rows[rows.length - 1] = r; else rows.push(r);
        candle.update(barOf(r)); vol.update(volOf(r));
        for (const k of Object.keys(vwapS)) vwapS[k].update(r.vr[k] == null ? {time: r.t} : {time: r.t, value: r.vr[k]});
        vwapG.update(r.vg == null ? {time: r.t} : {time: r.t, value: r.vg});
        for (const k of ['v', 'u1', 'l1']) { vwapW[k].update(pt(r, 'vw', k, opts.vwapW)); vwapM[k].update(pt(r, 'vm', k, opts.vwapM)); }
        const cv = cvdScope === 'rth' ? r.cr : r.cg;
        cvdLine.update(cv == null ? {time: r.t} : {time: r.t, value: cv}); dHist.update(deltaOf(r));
      }
      applyMarkers();
    }
    crosshair(null);
    sig = '';
  }

  // les absorptions sont dessinées sur le canvas, à leur prix (voir draw) : plus de flèches au-dessus / au-dessous des bougies
  function applyMarkers() { candle.setMarkers([]); }

  // ---------- reglages d'affichage ----------
  function setTheme(name) {
    theme = THEMES[name] ? name : 'nuit';
    const t = th();
    candle.applyOptions({upColor: t.up, downColor: t.dn, wickUpColor: t.up, wickDownColor: t.dn});
    if (rows.length) vol.setData(rows.map(volOf));
  }
  function setTz(v) { tz = v === 'et' ? 'et' : 'paris'; chart.applyOptions({localization: common().localization}); cvdChart.applyOptions({localization: common().localization}); }
  function setCvdScope(v) {
    cvdScope = v === 'gx' ? 'gx' : 'rth';
    cvdLine.applyOptions({title: cvdScope === 'gx' ? 'CVD Globex' : 'CVD séance'});
    if (rows.length) cvdLine.setData(cvdData());
  }
  function setOptions(o) {
    const vw = ('vwapW' in o && o.vwapW !== opts.vwapW) || ('vwapM' in o && o.vwapM !== opts.vwapM);
    Object.assign(opts, o); applyMarkers(); sig = '';
    if (vw && rows.length) for (const k of ['v', 'u1', 'l1']) { vwapW[k].setData(anchData('vw', k, opts.vwapW)); vwapM[k].setData(anchData('vm', k, opts.vwapM)); }
  }
  function setVpMode(m) { vpMode = m; sig = ''; }
  function setProfile2(p) { profile2 = p && !p.empty ? p : null; sig = ''; }
  function setSingles(z) { singles = z || []; sig = ''; }
  function setProfile(p) { profile = p && !p.empty ? p : null; sig = ''; }
  function setZones(z) { zones = z || []; sig = ''; }

  function setLevels(list, mode) {
    levels = list || []; if (mode) levelMode = mode;
    const want = levelMode === 'off' ? [] : levels.filter(x => !/^VWAP/.test(x.name) && (levelMode === 'all' || (x.group !== 'rond' && !MINOR.has(x.kind))));
    const s = levelMode + '|' + want.map(x => x.name + x.price).join(',');
    if (s === lineSig) return;
    lineSig = s;
    for (const l of lines) { try { candle.removePriceLine(l); } catch (e) { /* deja retiree */ } }
    lines = want.map(x => {
      const st = LEVEL_STYLE[x.kind] || ['#6b7280', 1, 2];
      return candle.createPriceLine({price: x.price, color: st[0], lineWidth: st[1], lineStyle: st[2], axisLabelVisible: x.group !== 'rond', title: SHORT[x.name] || x.name});
    });
  }

  // setup proposé (onglet Setups) : entrée, stop et objectifs tracés sur le graphique
  let setupLines = [], setupSig = '';
  function setSetup(st) {
    const s = st ? [st.side, st.entry, st.stop, (st.targets || []).join(',')].join('|') : '';
    if (s === setupSig) return;
    setupSig = s;
    for (const l of setupLines) { try { candle.removePriceLine(l); } catch (e) { /* deja retiree */ } }
    setupLines = [];
    if (!st) return;
    const L = (price, color, style, title) => candle.createPriceLine({price, color, lineWidth: 2, lineStyle: style, axisLabelVisible: true, title});
    setupLines.push(L(st.entry, '#e5e7eb', 2, (st.side === 'long' ? 'ACHAT ' : 'VENTE ') + Math.round(st.score) + ''));
    setupLines.push(L(st.stop, '#ef4444', 0, 'STOP'));
    (st.targets || []).slice(0, 2).forEach((t, i) => setupLines.push(L(t, '#22c55e', i ? 2 : 0, 'OBJ ' + (i + 1))));
  }

  // ---------- couche canvas ----------
  const psWidth = () => { try { return chart.priceScale('right').width() || 76; } catch (e) { return 76; } };

  function loop() {
    try {
      const W = overlay.clientWidth, H = overlay.clientHeight;
      const last = rows[rows.length - 1];
      const rng = chart.timeScale().getVisibleLogicalRange();
      const s = [W, H, psWidth(), last ? candle.priceToCoordinate(last.c) : 0, last ? chart.timeScale().timeToCoordinate(last.t) : 0, rng ? rng.from.toFixed(2) + rng.to.toFixed(2) : '',
        profile ? candle.priceToCoordinate(profile.poc) : 0, profile ? candle.priceToCoordinate(profile.vah) : 0].join('|');
      if (s !== sig) { sig = s; draw(W, H); }
    } catch (e) { /* le graphique n'est pas encore pret */ }
    requestAnimationFrame(loop);
  }

  function draw(W, H) {
    const dpr = window.devicePixelRatio || 1;
    if (overlay.width !== Math.round(W * dpr) || overlay.height !== Math.round(H * dpr)) { overlay.width = Math.round(W * dpr); overlay.height = Math.round(H * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const right = W - psWidth();
    const Y = p => candle.priceToCoordinate(p);
    ctx.font = '10px -apple-system,Segoe UI,Roboto,sans-serif';

    if (opts.zones) for (const z of zones) {
      const y1 = Y(z.hi + 0.25), y2 = Y(z.lo - 0.25);
      if (y1 == null || y2 == null) continue;
      const a = Math.min(0.22, 0.05 + z.score * 0.02);
      ctx.fillStyle = `rgba(76,141,255,${a})`; ctx.fillRect(0, y1, right, Math.max(5, y2 - y1));
      ctx.fillStyle = 'rgba(160,190,255,.85)'; ctx.textAlign = 'left';
      ctx.fillText(`zone ${z.score}`, 6, y1 + 10);
    }

    if (profile && vpMode !== 'off') {
      const rowsP = profile.rows, tick = profile.tick || 0.25;
      let mx = 0; for (const r of rowsP) mx = Math.max(mx, r.s + r.b);
      const maxW = Math.min(170, right * 0.24);
      for (const r of rowsP) {
        const yt = Y(r.hi + tick / 2), yb = Y(r.lo - tick / 2);
        if (yt == null || yb == null) continue;
        const tot = r.s + r.b, w = mx ? tot / mx * maxW : 0, h = Math.max(1, yb - yt - 1);
        const ws = tot ? w * r.s / tot : 0, x0 = right - w;
        const k = r.va ? 1 : 0.5;
        ctx.fillStyle = `rgba(255,107,107,${0.62 * k})`; ctx.fillRect(x0, yt, ws, h);
        ctx.fillStyle = `rgba(61,220,151,${0.62 * k})`; ctx.fillRect(x0 + ws, yt, w - ws, h);
        if (r.poc) { ctx.fillStyle = 'rgba(244,114,182,.95)'; ctx.fillRect(0, yt + h / 2 - 0.5, right, 1.2); }
      }
      const lab = (price, txt, color) => {
        const y = Y(price); if (y == null) return;
        ctx.strokeStyle = color; ctx.setLineDash([4, 3]); ctx.beginPath(); ctx.moveTo(right - maxW - 14, y); ctx.lineTo(right, y); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = color; ctx.textAlign = 'right'; ctx.fillText(txt, right - maxW - 18, y - 3);
      };
      lab(profile.vah, 'VAH', 'rgba(244,114,182,.9)'); lab(profile.val, 'VAL', 'rgba(244,114,182,.9)'); lab(profile.poc, 'POC', 'rgba(244,114,182,1)');
      if (profile.label) { ctx.fillStyle = 'rgba(200,205,220,.8)'; ctx.textAlign = 'right'; ctx.fillText('Profil : ' + profile.label, right - 6, 14); }
    }

    // second profil (semaine, mois...) : à GAUCHE du graphique, plus discret, pour lire le jour dans la structure
    if (profile2) {
      const rowsP = profile2.rows, tick = profile2.tick || 0.25;
      let mx = 0; for (const r of rowsP) mx = Math.max(mx, r.s + r.b);
      const maxW = Math.min(150, right * 0.2);
      for (const r of rowsP) {
        const yt = Y(r.hi + tick / 2), yb = Y(r.lo - tick / 2);
        if (yt == null || yb == null) continue;
        const tot = r.s + r.b, w = mx ? tot / mx * maxW : 0, h = Math.max(1, yb - yt - 1);
        ctx.fillStyle = r.va ? 'rgba(192,132,252,.30)' : 'rgba(192,132,252,.14)'; ctx.fillRect(0, yt, w, h);
        if (r.poc) { ctx.fillStyle = 'rgba(192,132,252,.95)'; ctx.fillRect(0, yt + h / 2 - 0.5, maxW + 30, 1.5); }
      }
      ctx.fillStyle = 'rgba(205,190,240,.85)'; ctx.textAlign = 'left';
      ctx.fillText('Profil 2 : ' + (profile2.label || ''), 6, H - 30);
      for (const [p, t] of [[profile2.vah, 'VAH'], [profile2.val, 'VAL'], [profile2.poc, 'POC']]) {
        const y = Y(p); if (y == null) continue;
        ctx.fillStyle = 'rgba(205,190,240,.9)'; ctx.fillText(t + ' ' + p.toFixed(2), maxW + 34, y + 3);
      }
    }

    // single prints (jaune) et queues (violet) : bandes horizontales ; celles des séances passées non comblées sont les plus marquées
    if (opts.singles) for (const z of singles) {
      const y1 = Y(z.hi + 0.125), y2 = Y(z.lo - 0.125);
      if (y1 == null || y2 == null) continue;
      const tail = z.kind !== 'single', a = z.current ? 0.07 : 0.13;
      ctx.fillStyle = tail ? `rgba(167,139,250,${a})` : `rgba(251,191,36,${a})`;
      ctx.fillRect(0, y1, right, Math.max(2, y2 - y1));
      ctx.strokeStyle = tail ? 'rgba(167,139,250,.5)' : 'rgba(251,191,36,.55)'; ctx.setLineDash([2, 4]);
      ctx.strokeRect(0.5, y1 + 0.5, right - 1, Math.max(2, y2 - y1));
      ctx.setLineDash([]);
      ctx.fillStyle = tail ? 'rgba(200,185,255,.9)' : 'rgba(251,210,90,.9)'; ctx.textAlign = 'left';
      const lx = profile2 ? Math.min(150, right * 0.2) + 110 : 8;            // à droite du profil 2 et de ses étiquettes
      const lbl = (tail ? (z.kind === 'queue haute' ? 'Queue haute' : 'Queue basse') : 'Single print') + ' ' + z.day.slice(8, 10) + '/' + z.day.slice(5, 7)
        + (z.filled > 0 ? ` · comblé ${Math.round(z.filled * 100)} %` : (z.current ? ' · en cours' : ' · vierge'));
      ctx.fillText(lbl, lx, Math.max(y1 + 11, 34));
    }

    // absorptions à LEUR prix : trait de la barre d'absorption jusqu'à sa cassure (ou jusqu'au bord si elle tient), épaisseur = force
    if (opts.abs && rows.length) {
      const ts = chart.timeScale();
      for (const a of marks) {
        const bt = Math.floor(a.t / step) * step, x0 = ts.timeToCoordinate(bt), y = Y(a.price);
        if (x0 == null || y == null || x0 > right) continue;
        const live = a.status === 'active';
        if (!live && a.strength < 0.55) continue;                         // zones cassées faibles : du bruit, on ne les montre pas
        let x1 = right;
        if (!live && a.end != null) { const xe = ts.timeToCoordinate(Math.floor(a.end / step) * step); x1 = xe == null ? right : Math.min(right, Math.max(xe, x0 + 6)); }
        const bull = a.side === 'bull', c = bull ? '61,220,151' : '255,107,107';
        ctx.strokeStyle = `rgba(${c},${live ? 0.9 : 0.5})`; ctx.lineWidth = 1 + 2.5 * a.strength;
        ctx.beginPath(); ctx.moveTo(Math.max(0, x0), y); ctx.lineTo(x1, y); ctx.stroke(); ctx.lineWidth = 1;
        // triangle à la barre d'absorption
        ctx.fillStyle = `rgba(${c},${live ? 1 : 0.5})`; ctx.beginPath();
        if (bull) { ctx.moveTo(x0, y + 3); ctx.lineTo(x0 - 5, y + 11); ctx.lineTo(x0 + 5, y + 11); }
        else { ctx.moveTo(x0, y - 3); ctx.lineTo(x0 - 5, y - 11); ctx.lineTo(x0 + 5, y - 11); }
        ctx.fill();
        if (!live && a.status === 'cassée') {                              // croix à la cassure
          ctx.strokeStyle = `rgba(${c},.8)`; ctx.beginPath(); ctx.moveTo(x1 - 3, y - 3); ctx.lineTo(x1 + 3, y + 3); ctx.moveTo(x1 - 3, y + 3); ctx.lineTo(x1 + 3, y - 3); ctx.stroke();
        }
        if (live) {
          ctx.fillStyle = `rgba(${c},1)`; ctx.textAlign = 'right';
          ctx.fillText(`ABS ${Math.round(a.qty)}${a.count > 1 ? ' ×' + a.count : ''}${a.tests ? ' · ' + a.tests + ' test' + (a.tests > 1 ? 's' : '') : ''}`, x1 - 4, bull ? y + 12 : y - 4);
        }
      }
    }

    if (opts.bigs && bigs.length && rows.length) {
      const big = Math.max(...bigs.map(b => b.q));
      for (const b of bigs) {
        const bt = Math.floor(b.t / step) * step, x = chart.timeScale().timeToCoordinate(bt), y = candle.priceToCoordinate(b.p);
        if (x == null || y == null || x < 0 || x > right) continue;
        const r = Math.max(4, Math.min(20, Math.sqrt(b.q) * 1.5));
        ctx.beginPath(); ctx.arc(x, y, r, 0, 7);
        ctx.fillStyle = b.s > 0 ? 'rgba(61,220,151,.34)' : 'rgba(255,107,107,.34)'; ctx.fill();
        ctx.strokeStyle = b.s > 0 ? 'rgba(61,220,151,.9)' : 'rgba(255,107,107,.9)'; ctx.lineWidth = 1; ctx.stroke();
        if (b.q >= big * 0.5) { ctx.fillStyle = '#e8eaf0'; ctx.textAlign = 'center'; ctx.fillText(String(b.q), x, y + 3); }
      }
    }
  }

  return {init, apply, setTheme, setTz, setCvdScope, setOptions, setVpMode, setProfile, setProfile2, setSingles, setZones, setLevels, setSetup,
    absZones: () => marks.filter(a => a.status === 'active'),
    onLegend: fn => { listeners.legend = fn; }, lastRow: () => rows[rows.length - 1] || null, count: () => rows.length,
    lastTime: () => rows.length ? rows[rows.length - 1].t : null};
})();
