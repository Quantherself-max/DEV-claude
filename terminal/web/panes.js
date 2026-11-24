// V53 : fenêtres sous le graphique principal (intérêt ouvert, delta et CVD, funding, flux par taille d'ordre du spot et du perpétuel).
// Avant, elles étaient dessinées DANS le graphique des prix (chacune sur une tranche de sa hauteur) : l'échelle des prix devait rester
// automatique et cinq fenêtres ne laissaient que 38 % de la hauteur aux bougies. Maintenant chacune a SON graphique, sous les bougies :
//   - le graphique des prix se manie librement (molette : zoom ; glisser : déplacer ; glisser l'échelle des prix : étirer les bougies en
//     hauteur ; glisser l'échelle du temps : les élargir ; double-clic sur une échelle : retour automatique) ;
//   - chaque fenêtre a sa barre (réglages, monter, descendre, lecture chiffrée, réduire, retirer), sa poignée pour changer sa hauteur
//     (double-clic : hauteurs d'origine) et sa propre échelle chiffrée, qui s'étire aussi ;
//   - le temps, le zoom et la croix suivent le graphique des prix (et le graphique des prix suit une fenêtre qu'on déplace).
// Les séries et les lectures restent calculées par panels.js (syncSubcharts, headPanes) ; ce module ne gère que les fenêtres.
class PaneStack {
  static get NAMES() { return {oi: 'Intérêt ouvert', delta: 'Delta et CVD', fund: 'Funding', szs: 'Flux par taille · spot', szp: 'Flux par taille · perpétuel'}; }
  static get HEAD() { return 22; }               // hauteur d'une fenêtre réduite (sa barre seule)
  static get SEP() { return 5; }                 // poignée au-dessus de chaque fenêtre
  static get MIN() { return 46; }                // hauteur minimale d'une fenêtre ouverte
  static defH(n) { return Math.min(0.17, 0.5 / Math.max(1, n)); }   // part de la hauteur par fenêtre : les bougies gardent au moins la moitié
  constructor(panel) {
    this.p = panel; this.win = {}; this.keys = []; this.w = 0; this.busy = false; this.xs = false; this.carKey = ''; this.tmp = null;
    this.times = null; this.tset = null;
    this.box = document.createElement('div'); this.box.className = 'psubs'; this.box.hidden = true;
    panel.host.appendChild(this.box);
    panel.chart.timeScale().subscribeVisibleLogicalRangeChange(r => this.follow(r));
    panel.chart.subscribeCrosshairMove(p => this.crossFromMain(p));
    this.box.addEventListener('click', e => this.onClick(e));
    this.box.addEventListener('dblclick', e => { if (e.target.closest('.psep') && typeof Desk !== 'undefined') Desk.paneAct(null, 'resetH'); });
    this.box.addEventListener('pointerdown', e => this.dragStart(e));
    if (window.ResizeObserver) new ResizeObserver(() => this.layout()).observe(panel.host);
    window.addEventListener('pointerup', () => Object.values(this.win).forEach(w => { if (w.down) { w.down = false; w.act = Date.now(); } }), true);
  }
  err(e) { if (typeof LT !== 'undefined' && LT.showErr) LT.showErr(e, 'fenêtres sous le graphique (synchronisation)'); }   // V53.1 : jamais dans la bibliothèque graphique
  cfg() { return typeof Desk !== 'undefined' && Desk.paneCfg ? Desk.paneCfg() : {order: [], h: {}, min: {}, read: {}}; }
  chart(k) { return this.win[k] ? this.win[k].chart : null; }
  has(tm) { return !this.tset || this.tset.has(tm); }
  // fenêtres voulues, dans l'ordre : création, retrait, rangement
  sync(keys) {
    for (const k of Object.keys(this.win)) if (!keys.includes(k)) {
      const w = this.win[k];
      try { w.chart.remove(); } catch (e) { /* déjà retiré */ }
      w.el.remove(); w.sep.remove(); delete this.win[k];
    }
    keys.forEach(k => { if (!this.win[k]) this.win[k] = this.make(k); });
    if (keys.join() !== this.keys.join()) {
      keys.forEach(k => { this.box.appendChild(this.win[k].sep); this.box.appendChild(this.win[k].el); });
      this.keys = keys.slice(); this.box.hidden = !keys.length;
      this.resetWidth();
      this.layout();
      this.follow(this.p.chart.timeScale().getVisibleLogicalRange());
    }
    this.carriers();
  }
  make(k) {
    const el = document.createElement('div'); el.className = 'pwin'; el.dataset.pk = k;
    const tg = k === 'delta' ? '<button type="button" class="tg" data-pa="bars" title="Afficher ou retirer les barres du delta (la force de chaque bougie)">▮ Barres</button>' +
      '<button type="button" class="tg" data-pa="line" title="Afficher ou retirer la ligne du CVD (le cumul du delta)">∿ CVD</button>' : '';
    el.innerHTML = '<div class="pchart"></div><div class="phd"><div class="phl"></div><span class="phb">' + tg +
      '<button type="button" data-pa="opts" data-elbtn title="Réglages de cette fenêtre (ouvre « ＋ Éléments » à sa ligne)">⚙</button>' +
      '<button type="button" data-pa="up" title="Monter la fenêtre">▲</button><button type="button" data-pa="down" title="Descendre la fenêtre">▼</button>' +
      '<button type="button" data-pa="read" title="Lecture chiffrée : deux lignes, une ligne, ou le nom seul">≡</button>' +
      '<button type="button" data-pa="min" title="Réduire la fenêtre à sa barre / la rouvrir">−</button>' +
      '<button type="button" data-pa="x" title="Retirer la fenêtre (« ▤ Fenêtres » ou « ＋ Éléments » pour la remettre)">✕</button></span></div>';
    const sep = document.createElement('div'); sep.className = 'psep'; sep.dataset.sep = k;
    sep.title = 'Glisser pour changer la hauteur · double-clic : hauteurs d\'origine';
    const chart = LightweightCharts.createChart(el.querySelector('.pchart'), {
      autoSize: true,
      layout: {background: {type: 'solid', color: 'rgba(0,0,0,0)'}, textColor: '#b2b5be', fontSize: 11, attributionLogo: false},   // le logo reste sur les bougies (et le lien en bas de page)
      rightPriceScale: {borderColor: '#2a2e39', scaleMargins: {top: 0.2, bottom: 0.06}, minimumWidth: this.w || 0},
      timeScale: {visible: false, rightOffset: 16},
      crosshair: {mode: LightweightCharts.CrosshairMode.Normal},
    });
    // porteuse invisible : les mêmes heures que les bougies, pour que la bougie n° i soit au même endroit dans chaque graphique
    const carrier = chart.addLineSeries({color: 'rgba(0,0,0,0)', lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
      priceFormat: {type: 'custom', minMove: 0.0001, formatter: v => Panel.subFmt(k, v)}});
    const w = {k, el, sep, chart, carrier, head: el.querySelector('.phl'), html: '', scales: new Set(['right']), anchor: null, vals: null, h: 0, mk: '', zones: {}};
    // une fenêtre ne mène le graphique des prix que quand on la manipule (molette, glisser, pincer) : une fenêtre qui naît ou reçoit ses
    // données a sa propre vue par défaut, qui ne doit pas remplacer celle des bougies
    const mark = () => { w.act = Date.now(); };
    el.addEventListener('wheel', mark, {passive: true, capture: true});
    el.addEventListener('pointerdown', () => { w.down = true; mark(); }, true);
    chart.timeScale().subscribeVisibleLogicalRangeChange(r => this.lead(w, r));
    chart.subscribeCrosshairMove(p => this.crossFromPane(w, p));
    this.theme(w);
    if (this.times) carrier.setData(this.times.map(t => ({time: t})));
    return w;
  }
  theme(w) {
    const t = this.p.th();
    w.chart.applyOptions({layout: {background: {type: 'solid', color: 'rgba(0,0,0,0)'}, textColor: t.text, fontFamily: t.font, fontSize: Math.min(11, t.fontSize)},
      grid: {vertLines: {color: t.grid}, horzLines: {color: t.grid}}, rightPriceScale: {borderColor: t.border}, timeScale: {borderColor: t.border},
      crosshair: {vertLine: {color: t.cross, labelBackgroundColor: t.crossLabel}, horzLine: {color: t.cross, labelBackgroundColor: t.crossLabel}}});
  }
  applyTheme() { Object.values(this.win).forEach(w => this.theme(w)); }
  // V53.2 : zones d'une fenêtre : {échelle: 'top' | 'bottom'} ; absente = toute la hauteur (le delta : CVD en haut, barres en bas)
  zones(k, z) { const w = this.win[k]; if (w && JSON.stringify(w.zones) !== JSON.stringify(z)) { w.zones = z; w.mk = ''; this.margins(w); } }
  scale(k, id) { const w = this.win[k]; if (w && !w.scales.has(id)) { w.scales.add(id); w.mk = ''; this.margins(w); } }
  anchor(k, series, vals) { const w = this.win[k]; if (w) { w.anchor = series; w.vals = vals; } }
  // heures des bougies du graphique des prix (et la bougie en direct si elle est plus récente)
  carriers() {
    const d = LT.st.data;
    if (!d || !d.candles || !d.candles.length) return;
    const cs = d.candles, last = Math.max(cs[cs.length - 1][0], this.p.lastBar || 0);
    const key = [d.symbol, d.tf, cs.length, cs[0][0], last, this.keys.join()].join('|');
    if (key === this.carKey) return;
    this.carKey = key;
    const times = cs.map(c => c[0]);
    if (last > times[times.length - 1]) times.push(last);
    this.times = times; this.tset = new Set(times);
    Object.values(this.win).forEach(w => w.carrier.setData(times.map(t => ({time: t}))));
    this.follow(this.p.chart.timeScale().getVisibleLogicalRange());
  }
  // ---- temps et zoom : le graphique des prix mène ; une fenêtre qu'on déplace ou zoome le fait suivre ----
  static same(a, b) { return a && b && Math.abs(a.from - b.from) < 1e-4 && Math.abs(a.to - b.to) < 1e-4; }
  setRange(c, r) { const ts = c.timeScale(); if (!PaneStack.same(ts.getVisibleLogicalRange(), r)) ts.setVisibleLogicalRange(r); }
  follow(r) {
    if (!r || this.busy || this.off) return;
    this.busy = true;
    try { Object.values(this.win).forEach(w => this.setRange(w.chart, r)); } catch (e) { this.err(e); } finally { this.busy = false; }
  }
  static touched(w) { return w.down || Date.now() - (w.act || 0) < 700; }
  lead(w, r) {
    if (!r || this.busy || !PaneStack.touched(w)) return;
    this.busy = true;
    try { this.setRange(this.p.chart, r); Object.values(this.win).forEach(o => { if (o !== w) this.setRange(o.chart, r); }); } catch (e) { this.err(e); } finally { this.busy = false; }
  }
  // ---- croix : la même heure dans les bougies et dans chaque fenêtre ----
  place(w, tm) {                                 // une fenêtre réduite n'a plus de graphique dessiné : pas de croix
    const v = tm == null || !w.vals || w.el.classList.contains('min') ? null : w.vals.get(tm);
    try { if (v == null || !w.anchor) w.chart.clearCrosshairPosition(); else w.chart.setCrosshairPosition(v, tm, w.anchor); } catch (e) { /* graphique pas encore dessiné */ }
  }
  crossFromMain(p) {
    if (this.xs || this.off || !this.keys.length) return;
    const tm = p && p.time != null ? p.time : null;
    this.xs = true;
    try { Object.values(this.win).forEach(w => this.place(w, tm)); } catch (e) { this.err(e); } finally { this.xs = false; }
  }
  crossFromPane(w, p) {
    if (this.xs) return;
    const tm = p && p.time != null ? p.time : null, P = this.p;
    this.xs = true;
    try {
      const c = tm == null ? null : P.closeAt(tm);
      try { if (c == null) P.chart.clearCrosshairPosition(); else P.chart.setCrosshairPosition(c, tm, P.series); } catch (e) { /* graphique masqué */ }
      Object.values(this.win).forEach(o => { if (o !== w) this.place(o, tm); });
      if (tm !== P.crossT) { P.crossT = tm; P.sig = ''; }
    } catch (e) { this.err(e); } finally { this.xs = false; }
  }
  // ---- même largeur d'échelle partout : les bougies et les fenêtres restent alignées à la bougie près ----
  resetWidth() {                                  // aussi à chaque changement d'instrument ou d'unité de temps : échelles des fenêtres en automatique
    this.w = 0;
    const o = {rightPriceScale: {minimumWidth: 0}};
    this.p.chart.applyOptions(o);
    Object.values(this.win).forEach(w => { w.chart.applyOptions(o); try { w.chart.priceScale('right').applyOptions({autoScale: true}); } catch (e) { /* rien */ } });
  }
  tick() {
    if (!this.keys.length) return;
    const r = this.p.chart.timeScale().getVisibleLogicalRange();      // une fenêtre qui a décalé sa vue seule (nouvelles données) se réaligne
    if (r && !this.keys.some(k => PaneStack.touched(this.win[k]))) {
      this.busy = true;
      try { this.keys.forEach(k => this.setRange(this.win[k].chart, r)); } catch (e) { this.err(e); } finally { this.busy = false; }
    }
    let m = this.p.chart.priceScale('right').width();
    for (const k of this.keys) m = Math.max(m, this.win[k].chart.priceScale('right').width());
    if (m > 0 && m !== this.w) {
      this.w = m;
      const o = {rightPriceScale: {minimumWidth: m}};
      this.p.chart.applyOptions(o); this.keys.forEach(k => this.win[k].chart.applyOptions(o));
      this.box.style.setProperty('--axw', m + 'px');
    }
  }
  // ---- hauteurs ----
  total() { const hd = this.p.host.querySelector('.phead'); return this.p.host.clientHeight - (hd ? hd.offsetHeight : 0); }
  minMain(tot) { return Math.max(140, Math.round(tot * (this.p.host.clientWidth < 620 ? 0.42 : 0.25))); }   // place gardée aux bougies (plus sur téléphone)
  layout() {
    if (!this.keys.length) { this.box.style.height = '0px'; return; }
    const tot = this.total();
    if (tot <= 0) return;
    const c = this.cfg(), n = this.keys.length, def = PaneStack.defH(n), tmp = this.tmp || {};
    const hs = this.keys.map(k => c.min[k] ? PaneStack.HEAD : Math.max(PaneStack.MIN, Math.round((tmp[k] != null ? tmp[k] : c.h[k] || def) * tot)));
    const room = tot - this.minMain(tot) - n * PaneStack.SEP;
    let sum = hs.reduce((a, b) => a + b, 0);
    if (sum > room) {                                                   // pas assez de place : les fenêtres ouvertes rétrécissent ensemble
      const so = this.keys.reduce((a, k, i) => a + (c.min[k] ? 0 : hs[i]), 0), f = so ? Math.max(0, room - (sum - so)) / so : 1;
      this.keys.forEach((k, i) => { if (!c.min[k]) hs[i] = Math.max(30, Math.floor(hs[i] * f)); });
      sum = hs.reduce((a, b) => a + b, 0);
    }
    this.keys.forEach((k, i) => { const w = this.win[k]; w.h = hs[i]; w.el.style.height = hs[i] + 'px'; w.el.classList.toggle('min', !!c.min[k]); });
    this.box.style.height = (sum + n * PaneStack.SEP) + 'px';
    this.margins();
  }
  // marge haute de chaque échelle : les barres et les courbes passent sous la lecture chiffrée, pas derrière
  margins(only) {
    (only ? [only] : Object.values(this.win)).forEach(w => {
      const h = w.h || w.el.offsetHeight;
      if (!h) return;
      const top = Math.min(0.7, ((w.head.offsetHeight || 16) + 6) / h), key = top.toFixed(3) + '|' + [...w.scales].join() + JSON.stringify(w.zones);
      if (key === w.mk) return;
      w.mk = key;
      const M = {top: {top, bottom: (1 - top) * 0.58}, bottom: {top: top + (1 - top) * 0.47, bottom: 0.03}};   // CVD : 42 % du haut ; barres : la moitié du bas
      w.scales.forEach(id => { try { w.chart.priceScale(id).applyOptions({scaleMargins: M[w.zones[id]] || {top, bottom: 0.06}}); } catch (e) { /* échelle pas encore créée */ } });
    });
  }
  dragStart(e) {
    const sep = e.target.closest('.psep');
    if (!sep || (e.button != null && e.button > 0) || typeof Desk === 'undefined') return;
    const c = this.cfg(), k = sep.dataset.sep, i = this.keys.indexOf(k), W = this.win[k];
    if (!W || c.min[k]) return;                                         // une fenêtre réduite se rouvre avec « − »
    let above = null;                                                   // la fenêtre ouverte juste au-dessus, sinon les bougies
    for (let j = i - 1; j >= 0; j--) if (!c.min[this.keys[j]]) { above = this.keys[j]; break; }
    e.preventDefault();
    const tot = this.total(), y0 = e.clientY, h0 = W.el.offsetHeight, a0 = above ? this.win[above].el.offsetHeight : this.p.body.offsetHeight;
    const minA = above ? PaneStack.MIN : this.minMain(tot);
    try { sep.setPointerCapture(e.pointerId); } catch (err) { /* ancien navigateur */ }
    sep.classList.add('drag');
    const move = ev => {
      const dy = Math.max(-(a0 - minA), Math.min(h0 - PaneStack.MIN, ev.clientY - y0));
      this.tmp = {[k]: (h0 - dy) / tot};
      if (above) this.tmp[above] = (a0 + dy) / tot;
      this.layout();
    };
    const up = () => {
      sep.classList.remove('drag');
      sep.removeEventListener('pointermove', move); sep.removeEventListener('pointerup', up); sep.removeEventListener('pointercancel', up);
      if (this.tmp) Desk.paneAct(null, 'h', this.tmp);
      this.tmp = null; this.layout();
    };
    sep.addEventListener('pointermove', move); sep.addEventListener('pointerup', up); sep.addEventListener('pointercancel', up);
  }
  onClick(e) {
    const b = e.target.closest('[data-pa]');
    if (!b || typeof Desk === 'undefined') return;
    const k = b.closest('.pwin').dataset.pk;
    if (b.dataset.pa === 'opts') Desk.paneOpts(k, b); else Desk.paneAct(k, b.dataset.pa);
  }
  // ---- lecture chiffrée en tête de fenêtre : rows = [[morceau, ...], ...] ; morceau = texte ou {txt, col, strong} ----
  head(k, rows, tip) {                           // V54 : morceaux {txt, col, k: 'name' | 'val' | 'chip'} ; tip = lecture complète, au survol
    const w = this.win[k];
    if (!w) return;
    const mode = this.cfg().read[k], h = w.h || w.el.offsetHeight || 999;
    const n = mode === 0 ? 0 : Math.min(mode == null ? 2 : mode, h < 150 ? 1 : 2);   // V53.2 : fenêtre basse : une seule ligne, la place va au graphique
    const shown = n === 0 ? [[{txt: PaneStack.NAMES[k], k: 'name'}]] : rows.filter(r => r && r.length).slice(0, n);
    const esc = s => String(s).replace(/[&<>"']/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch]));
    const col = c => typeof c === 'string' && /^[#a-z0-9(),.%\s]+$/i.test(c) ? c : '';
    const tt = tip ? ` title="${esc(tip)}"` : '';
    const html = shown.map((r, i) => `<div class="phr${i ? ' l2' : ''}"${tt}>` + r.map((p, j) => {
      const s = typeof p === 'string' ? p : p.txt, cl = typeof p === 'object' ? col(p.col) : '', kd = typeof p === 'object' ? p.k : '';
      const sep = j && !kd && !(typeof r[j - 1] === 'object' && r[j - 1].k) ? '<i> · </i>' : j ? ' ' : '';
      if (kd === 'name') return sep + `<span class="pn">${esc(s)}</span>`;
      if (kd === 'val') return sep + `<b class="pv"${cl ? ` style="color:${cl}"` : ''}>${esc(s)}</b>`;
      if (kd === 'chip') return sep + `<span class="pc"${cl ? ` style="color:${cl};border-color:${cl}"` : ''}>${esc(s)}</span>`;
      return sep + `<span${cl ? ` style="color:${cl}"` : ''}${typeof p === 'object' && p.strong ? ' class="b"' : ''}>${esc(s)}</span>`;
    }).join('') + '</div>').join('');
    if (html !== w.html) { w.html = html; w.head.innerHTML = html; w.mk = ''; this.margins(w); }
    if (k === 'delta') {                                                // boutons Barres / CVD : allumés quand affichés
      const o = (typeof LT !== 'undefined' && LT.st.mainOpts) || {}, on = {bars: o.deltaBars !== false, line: (o.cvdMode || 'off') !== 'off'};
      w.el.querySelectorAll('.tg').forEach(b => b.classList.toggle('on', !!on[b.dataset.pa]));
    }
  }
}
