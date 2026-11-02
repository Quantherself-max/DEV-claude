// Graphiques supplémentaires (« + Graphique ») : jusqu'à 3 petits graphiques sous le graphique principal, chacun avec sa propre unité de temps.
// Bougies, VWAP de séance, VWAP de la semaine, niveaux clés (POC, VAH / VAL, POC vierges, veille, IB...) et absorptions qui tiennent encore.
// Les unités choisies sont gardées dans le navigateur.
const Minis = (() => {
  'use strict';
  const LC = LightweightCharts;
  const {$, api, store} = U;
  const MAX = 3;
  const KEY = new Set(['poc', 'vah', 'val', 'ppoc', 'pdh', 'pdl', 'ibh', 'ibl', 'onh', 'onl', 'npoc', 'nwpoc', 'wpoc', 'mpoc', 'pwh', 'pwl', 'sph', 'spl']);
  const COLORS = {nuit: ['#3b82f6', '#e5e7eb'], classic: ['#26a69a', '#ef5350']};
  let host, cb, list = [], seq = 0;

  const fmtTime = (sec, withDate) => new Intl.DateTimeFormat('fr-FR', Object.assign({timeZone: cb.tz() === 'et' ? 'America/New_York' : 'Europe/Paris',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}, withDate ? {day: '2-digit', month: '2-digit'} : {})).format(new Date(sec * 1000));

  function init(el, callbacks) {
    host = el; cb = callbacks;
    for (const tf of (store.get('minis', []) || []).slice(0, MAX)) if ((cb.tfs() || []).includes(tf)) add(tf);
    layout();
    setInterval(() => { if (!document.hidden) list.forEach(m => poll(m)); }, 2500);
  }

  const save = () => store.set('minis', list.map(m => m.tf));

  function layout() {
    host.hidden = !list.length;
    const b = $('#addChart');
    if (b) b.disabled = list.length >= MAX;
  }

  function add(tf) {
    if (list.length >= MAX) return;
    const tfs = cb.tfs() || ['5m'];
    tf = tfs.includes(tf) ? tf : (tfs.find(t => !list.some(m => m.tf === t) && t !== '1m') || tfs[0]);
    const el = document.createElement('div');
    el.className = 'mini';
    el.innerHTML = `<header><select title="Unité de temps">${tfs.map(t => `<option${t === tf ? ' selected' : ''}>${t}</option>`).join('')}</select>`
      + `<span class="lbl"></span><button title="Retirer ce graphique">✕</button></header><div class="mc"></div>`;
    host.appendChild(el);
    const chart = LC.createChart(el.querySelector('.mc'), {
      autoSize: true, layout: {background: {color: '#0b0e11'}, textColor: '#aab0bd', fontSize: 10},
      grid: {vertLines: {color: '#141925'}, horzLines: {color: '#141925'}}, crosshair: {mode: 0},
      rightPriceScale: {borderColor: '#2a2e39'},
      timeScale: {borderColor: '#2a2e39', timeVisible: true, secondsVisible: false, rightOffset: 4, barSpacing: 5,
        tickMarkFormatter: (t, type) => type >= 3 ? fmtTime(t) : fmtTime(t, true).slice(0, 5)},
      localization: {timeFormatter: t => fmtTime(t, true)},
    });
    const [up, dn] = COLORS[cb.theme()] || COLORS.nuit;
    const m = {id: ++seq, tf, el, chart, lines: [], lineSig: '', fitted: false, busy: false,
      candle: chart.addCandlestickSeries({upColor: up, downColor: dn, borderVisible: false, wickUpColor: up, wickDownColor: dn,
        priceFormat: {type: 'price', precision: 2, minMove: 0.25}}),
      vw: chart.addLineSeries({color: '#ffb300', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false}),
      ww: chart.addLineSeries({color: '#c084fc', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        autoscaleInfoProvider: () => null})};
    el.querySelector('select').onchange = e => { m.tf = e.target.value; m.fitted = false; m.lineSig = ''; save(); poll(m); };
    el.querySelector('button').onclick = () => remove(m);
    list.push(m);
    save(); layout(); poll(m);
  }

  function remove(m) {
    try { m.chart.remove(); } catch (e) { /* deja retire */ }
    m.el.remove();
    list = list.filter(x => x !== m);
    save(); layout();
  }

  async function poll(m) {
    if (m.busy) return;
    m.busy = true;
    try { draw(m, await api(`/api/bars?tf=${encodeURIComponent(m.tf)}&limit=300`)); }
    catch (e) { /* le prochain passage reessaiera */ }
    finally { m.busy = false; }
  }

  const series = (bars, vals) => bars.map((b, i) => vals && vals[i] != null ? {time: b.t, value: vals[i]} : {time: b.t});

  function draw(m, p) {
    if (!list.includes(m) || p.tf !== m.tf) return;
    m.candle.setData(p.bars.map(b => ({time: b.t, open: b.o, high: b.h, low: b.l, close: b.c})));
    m.vw.setData(series(p.bars, p.vwapRth && p.vwapRth.v));
    m.ww.setData(cb.opts().vwapW && p.vwapWeek ? series(p.bars, p.vwapWeek.v) : []);
    if (!m.fitted && p.bars.length) {
      m.chart.timeScale().setVisibleLogicalRange({from: Math.max(-2, p.bars.length - 90), to: p.bars.length + 4});
      m.fitted = true;
    }
    const last = p.bars[p.bars.length - 1];
    m.el.querySelector('.lbl').textContent = last ? `${last.c.toFixed(2)} · VWAP ${p.vwapRth && p.vwapRth.v[p.bars.length - 1] != null ? p.vwapRth.v[p.bars.length - 1].toFixed(2) : '—'}` : '';
    // niveaux clés + absorptions qui tiennent : lignes de prix (redessinées seulement si elles changent)
    const lv = (cb.levels() || []).filter(x => KEY.has(x.kind));
    const ab = cb.opts().abs ? (p.absorptions || []).filter(a => a.status === 'active') : [];
    const want = lv.map(x => ({price: x.price, color: x.kind.startsWith('n') ? '#fb7185' : x.group === 'profil' ? '#c084fc' : '#f472b6', title: x.name.replace('séance', '').trim()}))
      .concat(ab.map(a => ({price: a.price, color: a.side === 'bull' ? '#3ddc97' : '#ff6b6b', title: 'ABS ' + Math.round(a.qty)})));
    const sig = want.map(w => w.title + w.price).join(',');
    if (sig === m.lineSig) return;
    m.lineSig = sig;
    for (const l of m.lines) { try { m.candle.removePriceLine(l); } catch (e) { /* deja retiree */ } }
    m.lines = want.map(w => m.candle.createPriceLine({price: w.price, color: w.color, lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: w.title}));
  }

  function setTheme(name) {
    const [up, dn] = COLORS[name] || COLORS.nuit;
    list.forEach(m => m.candle.applyOptions({upColor: up, downColor: dn, wickUpColor: up, wickDownColor: dn}));
  }

  return {init, add: () => add(), setTheme, refresh: () => list.forEach(m => { m.lineSig = ''; poll(m); })};
})();
