// Graphique : bougies + volume + VWAP (séance et bandes, Globex, semaine, mois), niveaux en lignes de prix, absorptions en marqueurs « ABS »
// au-dessus / au-dessous des bougies, panneau du bas synchronisé (CVD en ligne ou en bougies, delta par barre), et une couche canvas par-dessus
// le prix : profils de volume SUPERPOSABLES collés à l'échelle des prix, GEX par strike, single prints, zones, delta chiffré, gros ordres.
const NQChart = (() => {
  'use strict';
  const LC = LightweightCharts;
  const THEMES = {
    nuit: {up: '#3b82f6', dn: '#e5e7eb', volUp: 'rgba(59,130,246,.30)', volDn: 'rgba(229,231,235,.22)'},
    classic: {up: '#26a69a', dn: '#ef5350', volUp: 'rgba(38,166,154,.30)', volDn: 'rgba(239,83,80,.28)'},
  };
  const LEVEL_STYLE = {   // [couleur, épaisseur, style : 0 plein, 1 pointillé, 2 tirets]
    pdh: ['#f5a97f', 1, 2], pdl: ['#f5a97f', 1, 2], pdc: ['#f5a97f', 1, 1], ppoc: ['#f472b6', 2, 0], pvah: ['#f472b6', 1, 2], pval: ['#f472b6', 1, 2],
    onh: ['#b794f6', 1, 1], onl: ['#b794f6', 1, 1], asih: ['#8b7ab8', 1, 1], asil: ['#8b7ab8', 1, 1], lonh: ['#9c88d6', 1, 1], lonl: ['#9c88d6', 1, 1],
    open: ['#5eead4', 1, 1], ibh: ['#5eead4', 1, 2], ibl: ['#5eead4', 1, 2], poc: ['#f472b6', 2, 0], vah: ['#f472b6', 1, 2], val: ['#f472b6', 1, 2],
    r100: ['#4b5563', 1, 1], r50: ['#323945', 1, 1],
    wpoc: ['#c084fc', 2, 0], wvah: ['#c084fc', 1, 2], wval: ['#c084fc', 1, 2], pwpoc: ['#a78bfa', 1, 0], pwvah: ['#a78bfa', 1, 2], pwval: ['#a78bfa', 1, 2],
    pwh: ['#a78bfa', 1, 1], pwl: ['#a78bfa', 1, 1], mpoc: ['#38bdf8', 2, 0], mvah: ['#38bdf8', 1, 2], mval: ['#38bdf8', 1, 2],
    npoc: ['#fb7185', 2, 1], nwpoc: ['#f43f5e', 2, 1], sph: ['#fbbf24', 1, 1], spl: ['#fbbf24', 1, 1],
    gcall: ['#22c55e', 2, 0], gput: ['#ef4444', 2, 0], gzero: ['#facc15', 2, 2], gpos: ['#4ade80', 1, 1], gneg: ['#f87171', 1, 1],
  };
  const MINOR = new Set(['wvah', 'wval', 'pwvah', 'pwval', 'mvah', 'mval', 'pwpoc', 'asih', 'asil', 'lonh', 'lonl', 'gpos', 'gneg']);   // seulement en « Tous »
  const SHORT = {'High veille': 'H veille', 'Low veille': 'L veille', 'Clôture veille': 'Clôt. veille', 'Ouverture 9h30': 'Open 9h30'};
  const PCOLORS = {rth: '#4c8dff', gx: '#7aa2ff', prev: '#f5a97f', week: '#c084fc', pweek: '#a78bfa', month: '#38bdf8', pmonth: '#22d3ee'};

  let chart, cvdChart, candle, vol, vwapS = {}, vwapG, vwapW = {}, vwapM = {}, cvdLine, cvdCandle, dHist, overlay, ctx;
  let rows = [], times = new Set();
  let step = 60, theme = 'nuit', tz = 'paris';
  let profiles = [], levels = [], zones = [], bigs = [], marks = [], singles = [], gexData = null;
  let opts = {vwapS: true, bands: true, vwapG: true, vwapW: true, vwapM: false, lvlMode: 'key', groups: {veille: true, nuit: true, seance: true, profil: true, gex: true, rond: false},
    zones: false, singles: true, abs: 'top', delta: false, bigs: false, cvdMode: 'line', deltaHist: true, cvdScope: 'gx', gexBars: true};
  let lines = [], lineSig = '', sig = '', syncing = false, markSig = '';
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
    const t = THEMES[theme];
    candle = chart.addCandlestickSeries({upColor: t.up, downColor: t.dn, borderVisible: false, wickUpColor: t.up, wickDownColor: t.dn,
      priceFormat: {type: 'price', precision: 2, minMove: 0.25}});
    vol = chart.addHistogramSeries({priceFormat: {type: 'volume'}, priceScaleId: 'vol', lastValueVisible: false, priceLineVisible: false});
    chart.priceScale('vol').applyOptions({scaleMargins: {top: 0.86, bottom: 0}});
    // `auto: false` : la ligne ne compte pas dans l'échelle automatique (les bandes à ±2σ écraseraient les bougies)
    const line = (color, w, style, title, auto = true) => chart.addLineSeries(Object.assign({color, lineWidth: w, lineStyle: style, priceLineVisible: false, lastValueVisible: !!title,
      title: title || '', crosshairMarkerVisible: false, priceFormat: {type: 'price', precision: 2, minMove: 0.25}}, auto ? {} : {autoscaleInfoProvider: () => null}));
    vwapS = {v: line('#ffb300', 2, 0, 'VWAP'), u1: line('rgba(255,179,0,.65)', 1, 2, '', false), l1: line('rgba(255,179,0,.65)', 1, 2, '', false),
      u2: line('rgba(255,179,0,.38)', 1, 1, '', false), l2: line('rgba(255,179,0,.38)', 1, 1, '', false)};
    vwapG = line('rgba(122,162,255,.55)', 1, 2, '', false);
    vwapW = {v: line('#c084fc', 2, 0, 'VWAP sem.', false), u1: line('rgba(192,132,252,.45)', 1, 2, '', false), l1: line('rgba(192,132,252,.45)', 1, 2, '', false)};
    vwapM = {v: line('#38bdf8', 2, 0, 'VWAP mois', false), u1: line('rgba(56,189,248,.40)', 1, 2, '', false), l1: line('rgba(56,189,248,.40)', 1, 2, '', false)};
    cvdLine = cvdChart.addLineSeries({color: '#4c8dff', lineWidth: 2, priceLineVisible: false, title: 'CVD', priceFormat: {type: 'volume'}});
    cvdCandle = cvdChart.addCandlestickSeries({upColor: '#3ddc97', downColor: '#ff6b6b', borderVisible: false, wickUpColor: '#3ddc97', wickDownColor: '#ff6b6b',
      priceLineVisible: false, title: 'CVD', priceFormat: {type: 'volume'}});
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
    applyVisibility();
    requestAnimationFrame(loop);
  }

  const byTime = t => { for (let i = rows.length - 1; i >= 0; i--) if (rows[i].t === t) return rows[i]; return null; };
  const cvdOf = r => opts.cvdScope === 'rth' ? r.cr : r.cg;
  const cvdOhlcOf = r => opts.cvdScope === 'rth' ? r.cor : r.cog;

  function crosshair(p) {
    const r = p && p.time ? byTime(p.time) : rows[rows.length - 1];
    if (listeners.legend) listeners.legend(r || null, !!(p && p.time));
    if (p && p.time && r && typeof cvdChart.setCrosshairPosition === 'function') {
      const v = cvdOf(r);
      if (v != null) cvdChart.setCrosshairPosition(v, p.time, opts.cvdMode === 'candles' ? cvdCandle : cvdLine);
    } else if (typeof cvdChart.clearCrosshairPosition === 'function') cvdChart.clearCrosshairPosition();
  }

  // ---------- données ----------
  const pt = (r, v) => v == null ? {time: r.t} : {time: r.t, value: v};
  const th = () => THEMES[theme];
  const barOf = r => ({time: r.t, open: r.o, high: r.h, low: r.l, close: r.c});
  const volOf = r => ({time: r.t, value: r.v, color: r.c >= r.o ? th().volUp : th().volDn});
  const deltaOf = r => ({time: r.t, value: r.d, color: r.d >= 0 ? 'rgba(61,220,151,.75)' : 'rgba(255,107,107,.75)'});
  const cvdBarOf = r => { const o = cvdOhlcOf(r); return o ? {time: r.t, open: o[0], high: o[1], low: o[2], close: o[3]} : {time: r.t}; };
  const SERIES = () => [
    [vwapS.v, r => r.vr.v, opts.vwapS], [vwapS.u1, r => r.vr.u1, opts.vwapS && opts.bands], [vwapS.l1, r => r.vr.l1, opts.vwapS && opts.bands],
    [vwapS.u2, r => r.vr.u2, opts.vwapS && opts.bands], [vwapS.l2, r => r.vr.l2, opts.vwapS && opts.bands], [vwapG, r => r.vg, opts.vwapG],
    [vwapW.v, r => r.vw && r.vw.v, opts.vwapW], [vwapW.u1, r => r.vw && r.vw.u1, opts.vwapW], [vwapW.l1, r => r.vw && r.vw.l1, opts.vwapW],
    [vwapM.v, r => r.vm && r.vm.v, opts.vwapM], [vwapM.u1, r => r.vm && r.vm.u1, opts.vwapM], [vwapM.l1, r => r.vm && r.vm.l1, opts.vwapM]];

  function pick(p, i) {
    const vr = {};
    for (const k of ['v', 'u1', 'l1', 'u2', 'l2']) vr[k] = p.vwapRth[k][i];
    const sub = s => s ? {v: s.v[i], u1: s.u1[i], l1: s.l1[i]} : null;
    return Object.assign({}, p.bars[i], {vr, vg: p.vwapGx.v[i], vw: sub(p.vwapWeek), vm: sub(p.vwapMonth), cr: p.cvdRth[i], cg: p.cvdGx[i],
      cor: p.cvdOhlcRth ? p.cvdOhlcRth[i] : null, cog: p.cvdOhlcGx ? p.cvdOhlcGx[i] : null});
  }

  function setLines() { for (const [s, f, on] of SERIES()) s.setData(on ? rows.map(r => pt(r, f(r))) : []); }
  function setCvd() {
    cvdLine.setData(opts.cvdMode === 'line' ? rows.map(r => pt(r, cvdOf(r))) : []);
    cvdCandle.setData(opts.cvdMode === 'candles' ? rows.map(cvdBarOf) : []);
    dHist.setData(opts.deltaHist ? rows.map(deltaOf) : []);
    const name = opts.cvdScope === 'gx' ? 'CVD Globex' : 'CVD séance';
    cvdLine.applyOptions({title: name}); cvdCandle.applyOptions({title: name});
  }

  function redrawAll() {
    times = new Set(rows.map(r => r.t));
    candle.setData(rows.map(barOf)); vol.setData(rows.map(volOf));
    setLines(); setCvd(); applyMarkers(true);
  }

  // full : remplace tout (changement d'unité de temps ou de vue, premier chargement) ; sinon met à jour la fin
  function apply(p, full) {
    step = p.step / 1000;                 // le serveur donne des ms ; les temps du graphique sont en secondes
    marks = p.absorptions || []; bigs = p.bigs || [];
    if (full) {
      rows = p.bars.map((_, i) => pick(p, i));
      redrawAll();
      const n = rows.length;
      if (n) chart.timeScale().setVisibleLogicalRange({from: Math.max(-2, n - 150), to: n + 8});
    } else {
      const ser = SERIES();
      for (let i = 0; i < p.bars.length; i++) {
        const r = pick(p, i), last = rows[rows.length - 1];
        if (last && r.t < last.t) continue;
        if (last && r.t === last.t) rows[rows.length - 1] = r; else { rows.push(r); times.add(r.t); }
        candle.update(barOf(r)); vol.update(volOf(r));
        for (const [s, f, on] of ser) if (on) s.update(pt(r, f(r)));
        if (opts.cvdMode === 'line') cvdLine.update(pt(r, cvdOf(r))); else cvdCandle.update(cvdBarOf(r));
        if (opts.deltaHist) dHist.update(deltaOf(r));
      }
      applyMarkers(false);
    }
    crosshair(null);
    sig = '';
  }

  function reset() {
    rows = []; times = new Set(); marks = []; bigs = []; markSig = '';
    candle.setData([]); vol.setData([]);
    for (const [s] of SERIES()) s.setData([]);
    cvdLine.setData([]); cvdCandle.setData([]); dHist.setData([]); candle.setMarkers([]);
    sig = '';
  }

  // ---------- absorptions : marqueurs ABS au-dessus (vendeuse) / au-dessous (acheteuse) des bougies ----------
  // « meilleures » : seulement celles que le serveur note « top » (forte, répétée, testée ou faite SUR un niveau clé) ; une par bougie (la mieux notée).
  function applyMarkers(force) {
    const keep = opts.abs === 'off' ? [] : marks.filter(a => opts.abs === 'all' || a.top);
    const best = new Map();
    for (const a of keep) {
      const bt = Math.floor(a.t / step) * step;
      if (!times.has(bt)) continue;
      const k = bt + a.side, cur = best.get(k);
      if (!cur || (a.score || 0) > (cur.score || 0)) best.set(k, Object.assign({bt}, a));
    }
    const list = [...best.values()].sort((x, y) => x.bt - y.bt);
    const s = list.map(a => a.bt + a.side + a.count + (a.level || '') + (a.top ? 1 : 0)).join(',');
    if (!force && s === markSig) return;
    markSig = s;
    candle.setMarkers(list.map(a => {
      const bull = a.side === 'bull', strong = a.top;
      const txt = 'ABS' + (a.count > 1 ? ' ×' + a.count : '') + (a.level ? ' ★' : '');
      return {time: a.bt, position: bull ? 'belowBar' : 'aboveBar', shape: bull ? 'arrowUp' : 'arrowDown', text: txt, size: strong ? 1.6 : 0.9,
        color: bull ? (strong ? '#3ddc97' : 'rgba(61,220,151,.55)') : (strong ? '#ff6b6b' : 'rgba(255,107,107,.55)')};
    }));
  }

  // ---------- réglages d'affichage ----------
  function applyVisibility() {
    cvdLine.applyOptions({visible: opts.cvdMode === 'line'}); cvdCandle.applyOptions({visible: opts.cvdMode === 'candles'});
  }
  function setTheme(name) {
    theme = THEMES[name] ? name : 'nuit';
    const t = th();
    candle.applyOptions({upColor: t.up, downColor: t.dn, wickUpColor: t.up, wickDownColor: t.dn});
    if (rows.length) vol.setData(rows.map(volOf));
  }
  function setTz(v) { tz = v === 'et' ? 'et' : 'paris'; chart.applyOptions({localization: common().localization}); cvdChart.applyOptions({localization: common().localization}); }
  function setOptions(o) {
    const prev = JSON.stringify(opts);
    opts = Object.assign({}, opts, o, {groups: Object.assign({}, opts.groups, o.groups || {})});
    if (JSON.stringify(opts) === prev) return;
    applyVisibility();
    if (rows.length) { setLines(); setCvd(); applyMarkers(true); }
    lineSig = ''; setLevels(levels);
    sig = '';
  }
  function setProfiles(list) { profiles = (list || []).filter(x => x && x.data && !x.data.empty); sig = ''; }
  function setSingles(z) { singles = z || []; sig = ''; }
  function setZones(z) { zones = z || []; sig = ''; }
  function setGex(g) { gexData = g && g.strikes ? g : null; sig = ''; }

  function setLevels(list) {
    levels = list || [];
    const want = opts.lvlMode === 'off' ? [] : levels.filter(x => !/^VWAP/.test(x.name) && opts.groups[x.group] !== false
      && (opts.lvlMode === 'all' || (x.group !== 'rond' && !MINOR.has(x.kind))));
    const s = want.map(x => x.name + x.price).join(',');
    if (s === lineSig) return;
    lineSig = s;
    for (const l of lines) { try { candle.removePriceLine(l); } catch (e) { /* déjà retirée */ } }
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
    for (const l of setupLines) { try { candle.removePriceLine(l); } catch (e) { /* déjà retirée */ } }
    setupLines = [];
    if (!st) return;
    const L = (price, color, style, title) => candle.createPriceLine({price, color, lineWidth: 2, lineStyle: style, axisLabelVisible: true, title});
    setupLines.push(L(st.entry, '#e5e7eb', 2, (st.side === 'long' ? 'ACHAT ' : 'VENTE ') + Math.round(st.score)));
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
      const p0 = profiles[0] && profiles[0].data;
      const s = [W, H, psWidth(), last ? candle.priceToCoordinate(last.c) : 0, last ? chart.timeScale().timeToCoordinate(last.t) : 0, rng ? rng.from.toFixed(2) + rng.to.toFixed(2) : '',
        p0 ? candle.priceToCoordinate(p0.poc) : 0, chart.timeScale().options().barSpacing].join('|');
      if (s !== sig) { sig = s; draw(W, H); }
    } catch (e) { /* le graphique n'est pas encore prêt */ }
    requestAnimationFrame(loop);
  }

  const kfmt = v => { const a = Math.abs(v); return (v < 0 ? '−' : '+') + (a >= 1000 ? (a / 1000).toFixed(a >= 10000 ? 0 : 1) + 'k' : Math.round(a)); };

  function drawProfile(p, color, right, maxW, Y, single, idx) {
    const rowsP = p.rows, tick = p.tick || 0.25;
    let mx = 0; for (const r of rowsP) mx = Math.max(mx, r.s + r.b);
    for (const r of rowsP) {
      const yt = Y(r.hi + tick / 2), yb = Y(r.lo - tick / 2);
      if (yt == null || yb == null) continue;
      const tot = r.s + r.b, w = mx ? tot / mx * maxW : 0, h = Math.max(1, yb - yt - 1), x0 = right - w;
      if (single) {                                   // un seul profil : acheteurs / vendeurs agressifs séparés, comme avant
        const ws = tot ? w * r.s / tot : 0, k = r.va ? 1 : 0.5;
        ctx.fillStyle = `rgba(255,107,107,${0.62 * k})`; ctx.fillRect(x0, yt, ws, h);
        ctx.fillStyle = `rgba(61,220,151,${0.62 * k})`; ctx.fillRect(x0 + ws, yt, w - ws, h);
      } else {                                        // superposés : chacun sa couleur, zone de valeur plus marquée
        ctx.globalAlpha = r.va ? 0.34 : 0.16; ctx.fillStyle = color; ctx.fillRect(x0, yt, w, h); ctx.globalAlpha = 1;
      }
    }
    const lab = (price, txt, dash) => {
      const y = Y(price); if (y == null) return;
      ctx.strokeStyle = single ? 'rgba(244,114,182,.9)' : color; ctx.setLineDash(dash); ctx.beginPath();
      ctx.moveTo(single ? 0 : right - maxW - 30, y); ctx.lineTo(right, y); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = single ? 'rgba(244,114,182,1)' : color; ctx.textAlign = 'right';
      ctx.fillText(txt, right - maxW - 34 - (single ? 0 : 0), y - 3 - (single ? 0 : idx * 0));
    };
    const short = single ? '' : ' ' + (p.label || '').replace(/ \(.*\)$/, '').toLowerCase();
    lab(p.poc, 'POC' + short, single ? [] : [6, 3]);
    lab(p.vah, 'VAH' + short, [4, 3]); lab(p.val, 'VAL' + short, [4, 3]);
  }

  function draw(W, H) {
    const dpr = window.devicePixelRatio || 1;
    if (overlay.width !== Math.round(W * dpr) || overlay.height !== Math.round(H * dpr)) { overlay.width = Math.round(W * dpr); overlay.height = Math.round(H * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const right = W - psWidth();
    const Y = p => candle.priceToCoordinate(p);
    const ts = chart.timeScale();
    ctx.font = '10px -apple-system,Segoe UI,Roboto,sans-serif';

    if (opts.zones) for (const z of zones) {
      const y1 = Y(z.hi + 0.25), y2 = Y(z.lo - 0.25);
      if (y1 == null || y2 == null) continue;
      ctx.fillStyle = `rgba(76,141,255,${Math.min(0.22, 0.05 + z.score * 0.02)})`; ctx.fillRect(0, y1, right, Math.max(5, y2 - y1));
      ctx.fillStyle = 'rgba(160,190,255,.85)'; ctx.textAlign = 'left'; ctx.fillText(`zone ${z.score}`, 6, y1 + 10);
    }

    // single prints (jaune) et queues (violet)
    if (opts.singles) for (const z of singles) {
      const y1 = Y(z.hi + 0.125), y2 = Y(z.lo - 0.125);
      if (y1 == null || y2 == null) continue;
      const tail = z.kind !== 'single', a = z.current ? 0.07 : 0.13;
      ctx.fillStyle = tail ? `rgba(167,139,250,${a})` : `rgba(251,191,36,${a})`;
      ctx.fillRect(0, y1, right, Math.max(2, y2 - y1));
      ctx.strokeStyle = tail ? 'rgba(167,139,250,.5)' : 'rgba(251,191,36,.55)'; ctx.setLineDash([2, 4]);
      ctx.strokeRect(0.5, y1 + 0.5, right - 1, Math.max(2, y2 - y1)); ctx.setLineDash([]);
      ctx.fillStyle = tail ? 'rgba(200,185,255,.9)' : 'rgba(251,210,90,.9)'; ctx.textAlign = 'left';
      const lbl = (tail ? (z.kind === 'queue haute' ? 'Queue haute' : 'Queue basse') : 'Single print') + ' ' + z.day.slice(8, 10) + '/' + z.day.slice(5, 7)
        + (z.filled > 0 ? ` · comblé ${Math.round(z.filled * 100)} %` : (z.current ? ' · en cours' : ' · vierge'));
      if (y2 > 40 && y1 + 11 < H - 20) ctx.fillText(lbl, gexData && opts.gexBars ? 150 : 8, Math.max(y1 + 11, 34));
    }

    // GEX par strike (options, ramené au NQ) : barres depuis la GAUCHE, vert = gamma positif, rouge = négatif
    if (gexData && opts.gexBars && gexData.strikes.length) {
      let mx = 0; for (const s of gexData.strikes) mx = Math.max(mx, Math.abs(s.net));
      const maxW = Math.min(130, right * 0.16);
      for (const s of gexData.strikes) {
        const y = Y(s.price); if (y == null || !mx) continue;
        const w = Math.abs(s.net) / mx * maxW;
        ctx.fillStyle = s.net >= 0 ? 'rgba(74,222,128,.55)' : 'rgba(248,113,113,.55)';
        ctx.fillRect(0, y - 1.5, w, 3);
      }
      ctx.fillStyle = 'rgba(200,205,220,.75)'; ctx.textAlign = 'left';
      ctx.fillText(`GEX ${gexData.underlying || ''} par strike (différé) · régime ${gexData.regime || '—'}`, 6, H - 30);
    }

    // profils de volume superposés, collés à l'échelle des prix
    if (profiles.length) {
      const maxW = Math.min(170, right * 0.24), single = profiles.length === 1;
      profiles.forEach((p, i) => drawProfile(p.data, PCOLORS[p.key] || '#9ca3af', right, maxW, Y, single, i));
      ctx.textAlign = 'right';
      profiles.forEach((p, i) => {
        ctx.fillStyle = single ? 'rgba(200,205,220,.8)' : (PCOLORS[p.key] || '#9ca3af');
        ctx.fillText((single ? 'Profil : ' : '■ ') + (p.data.label || p.key), right - 6, 14 + i * 12);
      });
    }

    // delta chiffré sous chaque bougie (quand les bougies sont assez larges)
    if (opts.delta && rows.length && ts.options().barSpacing >= 18) {
      const rng = ts.getVisibleLogicalRange();
      if (rng) {
        const a = Math.max(0, Math.floor(rng.from)), b = Math.min(rows.length - 1, Math.ceil(rng.to));
        ctx.textAlign = 'center';
        for (let i = a; i <= b; i++) {
          const r = rows[i], x = ts.timeToCoordinate(r.t), y = Y(r.l);
          if (x == null || y == null || x > right) continue;
          ctx.fillStyle = r.d >= 0 ? 'rgba(61,220,151,.95)' : 'rgba(255,107,107,.95)';
          ctx.fillText(kfmt(r.d), x, y + (opts.abs !== 'off' ? 26 : 13));
        }
      }
    }

    if (opts.bigs && bigs.length && rows.length) {
      const big = Math.max(...bigs.map(b => b.q));
      for (const b of bigs) {
        const bt = Math.floor(b.t / step) * step, x = ts.timeToCoordinate(bt), y = Y(b.p);
        if (x == null || y == null || x < 0 || x > right) continue;
        const r = Math.max(4, Math.min(20, Math.sqrt(b.q) * 1.5));
        ctx.beginPath(); ctx.arc(x, y, r, 0, 7);
        ctx.fillStyle = b.s > 0 ? 'rgba(61,220,151,.34)' : 'rgba(255,107,107,.34)'; ctx.fill();
        ctx.strokeStyle = b.s > 0 ? 'rgba(61,220,151,.9)' : 'rgba(255,107,107,.9)'; ctx.lineWidth = 1; ctx.stroke();
        if (b.q >= big * 0.5) { ctx.fillStyle = '#e8eaf0'; ctx.textAlign = 'center'; ctx.fillText(String(b.q), x, y + 3); }
      }
    }
  }

  return {init, apply, reset, setTheme, setTz, setOptions, setProfiles, setSingles, setZones, setLevels, setSetup, setGex,
    absZones: () => marks.filter(a => a.status === 'active'), colors: PCOLORS,
    onLegend: fn => { listeners.legend = fn; }, lastRow: () => rows[rows.length - 1] || null, count: () => rows.length,
    lastTime: () => rows.length ? rows[rows.length - 1].t : null};
})();
