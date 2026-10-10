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
      `<div class="pbody"><canvas class="heat"></canvas><div class="chart"></div><canvas class="ov"></canvas><div class="ptag" hidden></div><div class="cdwn" hidden title="Temps restant avant la clôture de la bougie en cours"></div><div class="tip" hidden></div></div>`;
    this.body = host.querySelector('.pbody');
    this.heatCv = host.querySelector('.heat'); this.hctx = this.heatCv.getContext('2d');
    this.ov = host.querySelector('.ov'); this.ctx = this.ov.getContext('2d');
    this.tipEl = host.querySelector('.tip');
    this.cd = host.querySelector('.cdwn'); this.cdKey = ''; this.ptag = host.querySelector('.ptag');
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
      wickUpColor: '#26a69a', wickDownColor: '#ef5350', priceLineColor: '',
      autoscaleInfoProvider: o => this.autoscale(o)});
    this.applyTheme();
    this.chart.subscribeClick(p => this.onClick(p));
    this.body.addEventListener('mousemove', ev => this.onMove(ev));
    this.body.addEventListener('mouseleave', () => { this.tipEl.hidden = true; });
    host.querySelector('.pmax').onclick = () => LT.maximize(kind);
    host.querySelector('.ptools').addEventListener('click', ev => this.onTool(ev));
    host.querySelector('.ptools').addEventListener('change', ev => this.onTool(ev));
    this.syncTools();
  }

  // ---------- styles (V15) : « nuit » (fond noir, bougies bleues / blanches, chiffres a chasse fixe) ou « classique » ----------
  static TH = {
    nuit: {bg: '#0f0f0f', text: '#8a8a8a', fontSize: 11, font: 'ui-monospace, "SF Mono", Menlo, Consolas, "Roboto Mono", monospace', grid: 'rgba(255,255,255,0.028)',
      border: '#1d1d1d', up: '#6f9fe0', down: '#d9d9d9', ownTag: true, price: '#78adf7', priceText: '#0b0b0b', cd: '#141414', cdText: '#a0a0a0',
      cross: '#5a5a5a', crossLabel: '#2a2a2a', vwap: '#8296c0', band: 'rgba(120,173,247,0.32)', vpGrey: [98, 98, 98], vpVA: [124, 124, 124], vpPoc: [236, 236, 236],
      vpBuy: [120, 173, 247], vpSell: [242, 242, 242], label: '#9a9a9a', domBg: 'rgba(8,8,8,0.12)',
      vpW: [86, 102, 138], vpWVA: [112, 132, 178], vpM: [134, 112, 88], vpMVA: [170, 142, 108],
      spFill: 'rgba(170,170,170,0.12)', spLine: 'rgba(190,190,190,0.30)', poor: 'rgba(255,179,0,0.75)'},
    classique: {bg: 'rgba(0,0,0,0)', text: '#b2b5be', fontSize: 12, font: '-apple-system, BlinkMacSystemFont, "Trebuchet MS", Roboto, Ubuntu, sans-serif',
      grid: 'rgba(40,46,64,.35)', border: '#2a2e39', up: '#26a69a', down: '#ef5350', ownTag: false, price: '#4c8dff', priceText: '#ffffff', cd: null, cdText: '#ffffff',
      cross: '#758696', crossLabel: '#4c525e', vwap: '#FFB300', band: 'rgba(255,179,0,0.4)', vpGrey: [90, 98, 120], vpVA: [112, 126, 160], vpPoc: [255, 179, 0],
      vpBuy: [61, 220, 151], vpSell: [255, 107, 107], label: '#a8acb8', domBg: 'rgba(11,14,17,0.14)',
      vpW: [70, 110, 170], vpWVA: [96, 140, 205], vpM: [150, 118, 80], vpMVA: [190, 150, 100],
      spFill: 'rgba(160,165,180,0.13)', spLine: 'rgba(180,184,196,0.35)', poor: 'rgba(255,179,0,0.8)'},
  };
  th() { return Panel.TH[LT.st.theme] || Panel.TH.nuit; }
  applyTheme() {
    const t = this.th();
    this.chart.applyOptions({layout: {background: {type: 'solid', color: t.bg}, textColor: t.text, fontFamily: t.font, fontSize: t.fontSize},
      grid: {vertLines: {color: t.grid}, horzLines: {color: t.grid}}, rightPriceScale: {borderColor: t.border}, timeScale: {borderColor: t.border},
      crosshair: {vertLine: {color: t.cross, labelBackgroundColor: t.crossLabel}, horzLine: {color: t.cross, labelBackgroundColor: t.crossLabel}}});
    this.series.applyOptions({upColor: t.up, downColor: t.down, wickUpColor: t.up, wickDownColor: t.down, lastValueVisible: !t.ownTag});
    this.host.classList.toggle('th-nuit', LT.st.theme === 'nuit');
    for (const k in this.layers) { this.chart.removeSeries(this.layers[k].s); delete this.layers[k]; }
    this.cdKey = ''; this.stamp = ''; this.sig = '';
  }
  // largeurs (pixels) du profil de la seance et du carnet, colles a droite du graphique principal
  static DOMW = 318;
  static profKinds(o) { return ['D', 'W', 'M'].filter(k => o && o[{D: 'sess', W: 'sessW', M: 'sessM'}[k]]); }
  static tpoKinds(o) { return ['M', 'W', 'D', '4h', '1h'].filter(k => o && o[{M: 'tpoM', W: 'tpoW', D: 'tpoD', '4h': 'tpo4', '1h': 'tpo1'}[k]]); }
  // V17 : profils de volume colles a droite, une colonne par periode (jour au bord de l'echelle, puis semaine, puis mois)
  static drawProfiles(ctx, series, profs, kinds, x1, W, h, t, small = false) {
    const rgba = LT.rgba, NAME = {D: 'jour', W: 'semaine', M: 'mois'}, cols = [];
    let x = x1;
    kinds.forEach(k => {
      const s = profs && profs[k];
      if (!s || !s.rows || !s.rows.length) return;
      const g = k === 'D' ? t.vpGrey : k === 'W' ? t.vpW : t.vpM, gva = k === 'D' ? t.vpVA : k === 'W' ? t.vpWVA : t.vpMVA;
      const mx = Math.max(...s.rows.map(r => r[1])) || 1, len = {};
      s.rows.forEach(([lo, v, b]) => {
        const yt = series.priceToCoordinate(lo + s.step), yb = series.priceToCoordinate(lo);
        if (yt == null || yb == null || yb < 0 || yt > h) return;
        const hh = Math.max(1, yb - yt - (yb - yt > 3 ? 1 : 0)), l = v / mx * W, mid = lo + s.step / 2;
        const poc = s.poc >= lo && s.poc < lo + s.step, inVA = mid >= s.val && mid <= s.vah;
        len[lo] = l;
        ctx.fillStyle = rgba(poc ? t.vpPoc : inVA ? gva : g, poc ? 0.9 : inVA ? 0.8 : 0.55);
        ctx.fillRect(x - l, yt, l, hh);
        if (b != null && v > 0) {
          const dl = Math.abs(2 * b - v) / mx * W;
          if (dl >= 1) { ctx.fillStyle = rgba(2 * b >= v ? t.vpBuy : t.vpSell, 0.95); ctx.fillRect(x - l, yt, dl, hh); }
        }
      });
      if (k !== 'D') {                                        // semaine / mois : POC nomme, VAH et VAL en pointilles sur leur colonne
        ctx.font = `500 9px ${t.font}`; ctx.textAlign = 'left'; ctx.textBaseline = 'bottom';
        [[s.poc, true], [s.vah, false], [s.val, false]].forEach(([px, strong]) => {
          const y = series.priceToCoordinate(px); if (y == null || y < 8 || y > h - 30) return;
          ctx.strokeStyle = strong ? 'rgba(236,236,236,.75)' : rgba(gva, 0.8); ctx.lineWidth = 1; ctx.setLineDash(strong ? [] : [3, 3]);
          ctx.beginPath(); ctx.moveTo(x - W, Math.round(y) + 0.5); ctx.lineTo(x, Math.round(y) + 0.5); ctx.stroke(); ctx.setLineDash([]);
          if (strong) { ctx.fillStyle = t.label; ctx.fillText('POC ' + NAME[k], x - W + 1, y - 1); }
        });
      }
      // V19 : noeuds de volume sur le bord gauche de la colonne (bleu = HVN, zone d'acceptation ; violet = LVN, zone de rejet) et titre
      ctx.font = `500 9px ${t.font}`; ctx.textBaseline = 'middle'; ctx.textAlign = 'right';
      [[s.hvn, 'rgba(120,173,247,0.9)', 'HVN'], [s.lvn, 'rgba(190,120,255,0.9)', 'LVN']].forEach(([arr, col, lab]) => (arr || []).forEach(([a, b]) => {
        const ya = series.priceToCoordinate(a), yb = series.priceToCoordinate(b);
        if (ya == null || yb == null || ya < 0 || yb > h) return;
        ctx.fillStyle = col; ctx.fillRect(x - W - 4, yb, 2, Math.max(2, ya - yb));
        if (!small && (ya - yb >= 10 || lab === 'LVN')) ctx.fillText(lab, x - W - 7, (ya + yb) / 2);
      }));
      ctx.textAlign = 'left'; ctx.textBaseline = 'top'; ctx.fillStyle = t.label;
      if (!small) ctx.fillText(NAME[k] + (s.shape ? ' · forme ' + s.shape : ''), x - W, 4);
      cols.push({k, x, W, s, len});
      x -= W + 8;
    });
    return {used: x1 - x, cols};
  }
  // V19 : POC / VAH / VAL evolutifs de la seance du jour (valeur au fil de la seance), noeuds de volume en bandes, POC vierges des jours / semaines passes
  drawVpExtras(L, h) {
    const st = LT.st, o = st.mainOpts, ctx = this.ctx, t = this.th(), rgba = LT.rgba, fmtP = LT.fmtP, d = L.d;
    const D = (d.profiles || {}).D || d.session, xr = this.rightLimit || L.plotW;
    if (o.nodes && D && o.sess) {
      [[D.hvn, 'rgba(120,173,247,0.05)'], [D.lvn, 'rgba(190,120,255,0.06)']].forEach(([arr, col]) => (arr || []).forEach(([a, b]) => {
        const ya = this.series.priceToCoordinate(a), yb = this.series.priceToCoordinate(b);
        if (ya == null || yb == null) return;
        ctx.fillStyle = col; ctx.fillRect(0, yb, xr, Math.max(1, ya - yb));
      }));
    }
    if (o.dpoc && D && D.developing && D.developing.length > 1 && st.tf !== '1d') {
      const pts = D.developing.map(([tm, poc, vah, val]) => ({x: this.timeX(tm / 1000, L), poc, vah, val})).filter(p => p.x != null && p.x <= xr);
      const line = (key, col, dash, wdt) => {
        ctx.strokeStyle = col; ctx.lineWidth = wdt; ctx.setLineDash(dash); ctx.beginPath();
        let started = false, py = null;
        pts.forEach(p => {
          const y = this.series.priceToCoordinate(p[key]); if (y == null) return;
          if (!started) { ctx.moveTo(p.x, y); started = true; } else { ctx.lineTo(p.x, py); ctx.lineTo(p.x, y); }   // marches d'escalier
          py = y;
        });
        if (started && py != null) ctx.lineTo(Math.min(xr, pts[pts.length - 1].x + 6), py);
        ctx.stroke(); ctx.setLineDash([]);
      };
      line('vah', rgba(t.vpBuy, 0.45), [3, 3], 1);
      line('val', rgba(t.vpBuy, 0.45), [3, 3], 1);
      line('poc', 'rgba(236,236,236,0.7)', [], 1.2);
    }
    if (o.npoc) {
      const np = (d.levels || []).filter(l => l.kind === 'npoc').map(l => ({l, y: this.series.priceToCoordinate(l.price)})).filter(x => x.y != null && x.y > 8 && x.y < h - 30)
        .sort((a, b) => Math.abs(a.l.distAtr) - Math.abs(b.l.distAtr)).slice(0, 6);
      ctx.font = `500 9.5px ${t.font}`; ctx.textAlign = 'right'; ctx.textBaseline = 'bottom';
      np.forEach(({l, y}) => {
        const yy = Math.round(y) + 0.5, m = /nPOC ([JS])-(\d+)/.exec(l.name) || [], lab = `POC vierge ${m[1] || ''}-${m[2] || '?'} ${fmtP(l.price)}`;
        ctx.strokeStyle = m[1] === 'S' ? rgba(t.vpWVA || [112, 132, 178], 0.75) : 'rgba(236,236,236,0.5)'; ctx.lineWidth = 1; ctx.setLineDash([1, 3]);
        ctx.beginPath(); ctx.moveTo(xr * 0.35, yy); ctx.lineTo(xr - 2, yy); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = 'rgba(200,200,200,0.85)'; ctx.fillText(lab, xr - 6, yy - 1);
      });
    }
  }
  // V17 : single prints non comblees (rectangle gris) et poor highs / lows non repares (pointilles), de la seance jusqu'a xr.
  // V20 : semaine et mois dessines en premier, trait plus epais et fond un peu plus marque (zones rares et larges).
  static drawTpo(ctx, series, xOf, marks, kinds, xr, h, t, small) {
    if (!marks || !kinds.length) return;
    const TXT = {M: 'mois', W: 'semaine', D: '1 j', '4h': '4 h', '1h': '1 h'}, HTF = {M: true, W: true};
    ctx.font = `500 ${small ? 8.5 : 9.5}px ${t.font}`;
    const taken = [], free = (x, y) => !taken.some(q => Math.abs(q[0] - x) < 110 && Math.abs(q[1] - y) < 11);  // pas d'etiquettes superposees
    kinds.forEach(k => (marks[k] || []).forEach(ss => {
      let x0 = xOf(ss.start);
      x0 = Math.max(0, x0 == null ? 0 : x0);
      if (x0 >= xr - 4) return;
      ss.singles.forEach(([lo, hi, filled]) => {
        if (filled) return;
        const yt = series.priceToCoordinate(hi), yb = series.priceToCoordinate(lo);
        if (yt == null || yb == null || yb < 0 || yt > h - 26) return;
        const hh = Math.max(2, yb - yt), big = HTF[k];
        ctx.fillStyle = t.spFill; ctx.fillRect(x0, yt, xr - x0, hh);
        if (big) ctx.fillRect(x0, yt, xr - x0, hh);                                     // fond deux fois plus marque
        ctx.strokeStyle = t.spLine; ctx.lineWidth = big ? 1.6 : 1; ctx.strokeRect(Math.round(x0) + 0.5, Math.round(yt) + 0.5, Math.max(1, xr - x0 - 1), Math.max(1, hh - 1));
        if (hh >= 11 && free(x0, yt)) { taken.push([x0, yt]); ctx.fillStyle = t.label; ctx.textAlign = 'left'; ctx.textBaseline = 'top'; ctx.fillText('single prints ' + TXT[k], x0 + 3, yt + 2); }
      });
      [['poorHigh', 'poor high'], ['poorLow', 'poor low']].forEach(([key, lab]) => {
        const pm = ss[key];
        if (!pm || !pm.active) return;
        const y = series.priceToCoordinate(pm.price);
        if (y == null || y < 4 || y > h - 26) return;
        ctx.strokeStyle = t.poor; ctx.lineWidth = 1; ctx.setLineDash([5, 4]);
        ctx.beginPath(); ctx.moveTo(x0, Math.round(y) + 0.5); ctx.lineTo(xr, Math.round(y) + 0.5); ctx.stroke(); ctx.setLineDash([]);
        const ly = key === 'poorHigh' ? y - 6 : y + 6;
        if (!free(xr - 60, ly)) return;
        taken.push([xr - 60, ly]);
        ctx.fillStyle = t.poor; ctx.textAlign = 'right'; ctx.textBaseline = key === 'poorHigh' ? 'bottom' : 'top';
        ctx.fillText(`${lab} ${TXT[k]}`, xr - 4, key === 'poorHigh' ? y - 1 : y + 1);
      });
    }));
    ctx.textBaseline = 'middle';
  }
  overlayW(plotW) {
    const o = LT.st.mainOpts || {}, k = Panel.profKinds(o).length, W = Math.round(Math.min(150, Math.max(70, plotW * 0.15)) * (k > 1 ? 0.8 : 1));
    return {W, sess: k ? k * (W + 8) + 30 : 0, dom: o.dom ? Panel.DOMW + 12 : 0};
  }
  // place vide a droite des bougies (en bougies) pour que le profil et le carnet ne cachent pas les dernieres bougies
  rightSpace() {
    if (this.kind !== 'main') return 16;
    const plotW = this.chart.timeScale().width() || Math.max(300, this.body.clientWidth - 70), ow = this.overlayW(plotW);
    const f = Math.min(0.72, (ow.sess + ow.dom + 24) / plotW);
    return Math.max(16, Math.ceil(130 * f / (1 - f)) + 4);
  }
  static nice(raw) {
    if (!(raw > 0)) return 1;
    const e = Math.pow(10, Math.floor(Math.log10(raw)));
    for (const m of [1, 2, 2.5, 5, 10]) if (m * e >= raw * 0.999) return +(m * e).toPrecision(6);
    return 10 * e;
  }
  // tranche de prix du carnet : environ 15 pixels par ligne, centree sur le milieu de l'ecran
  flowGeom() {
    const h = this.body.clientHeight, s = this.series;
    const p0 = s.coordinateToPrice(h / 2), p1 = s.coordinateToPrice(h / 2 + 15), pt = s.coordinateToPrice(0), pb = s.coordinateToPrice(h);
    if (p0 == null || p1 == null || pt == null || pb == null) return null;
    return {step: Panel.nice(Math.abs(p0 - p1)), rows: Math.ceil(h / 15) + 6, center: (pt + pb) / 2};
  }

  // ---------- barre d'outils ----------
  static tools(kind) {
    if (kind === 'main') return `<label title="Seulement les 2 zones les plus importantes de chaque côté du prix"><input type="radio" name="mode" value="ess"> Essentiel</label>` +
      `<label title="Toutes les zones de confluence proches"><input type="radio" name="mode" value="conf"> Confluences</label>` +
      `<label title="Tous les niveaux de la fenêtre"><input type="radio" name="mode" value="all"> Tous</label>` +
      `<label title="Poches de liquidations estimées par l'Open Interest"><input type="checkbox" data-opt="pools"> Poches</label>` +
      `<label title="Ordres d'arrêt visibles dans le prix : plus haut / plus bas de la veille, de la semaine, du mois, creux et sommets récents"><input type="checkbox" data-opt="ppools"> Plus hauts / bas</label>` +
      `<label title="Entrée, stop et objectifs de l'idée de trade du moment"><input type="checkbox" data-opt="plan"> Plan</label>` +
      `<label title="Profil de volume du jour (depuis 00 h UTC), collé à l'échelle des prix : volume par prix, part des acheteurs (bleu) ou des vendeurs (blanc), POC / VAH / VAL"><input type="checkbox" data-mo="sess"> Profil J</label>` +
      `<label title="Profil de volume de la semaine en cours (depuis lundi 00 h UTC), à gauche du profil du jour"><input type="checkbox" data-mo="sessW"> S</label>` +
      `<label title="Profil de volume du mois en cours (depuis le 1er, 00 h UTC)"><input type="checkbox" data-mo="sessM"> M</label>` +
      `<label title="Nœuds de volume du profil du jour : bandes bleues = zones d'acceptation (HVN, beaucoup d'échanges), violettes = zones de rejet (LVN, le prix les traverse vite)"><input type="checkbox" data-mo="nodes"> Nœuds</label>` +
      `<label title="POC (trait clair), VAH et VAL (pointillés bleus) du jour tels qu'ils ont évolué au fil de la séance"><input type="checkbox" data-mo="dpoc"> POC évolutif</label>` +
      `<label title="POC des jours et semaines passés jamais retraversés depuis (pointillés), les plus proches du prix"><input type="checkbox" data-mo="npoc"> POC vierges</label>` +
      `<label title="TPO du mois (tranches d'1 jour) : single prints non comblées (rectangle gris, trait épais) et poor highs / lows non réparés (pointillés)"><input type="checkbox" data-mo="tpoM"> TPO mois</label>` +
      `<label title="TPO de la semaine (lundi 00 h UTC, tranches de 4 heures)"><input type="checkbox" data-mo="tpoW"> semaine</label>` +
      `<label title="TPO des séances d'1 jour (tranches de 30 minutes)"><input type="checkbox" data-mo="tpoD"> 1 j</label>` +
      `<label title="TPO des séances de 4 heures"><input type="checkbox" data-mo="tpo4"> 4 h</label>` +
      `<label title="TPO des séances d'1 heure (beaucoup de marques : à utiliser en 5 ou 15 minutes)"><input type="checkbox" data-mo="tpo1"> 1 h</label>` +
      `<label title="VWAP du jour et bandes à ±1 écart-type"><input type="checkbox" data-mo="vwap"> VWAP</label>` +
      `<label title="Carnet d'ordres en direct aligné sur les prix : taille en attente (Binance), nombre d'ordres (OKX), volume échangé à chaque prix"><input type="checkbox" data-mo="dom"> Carnet</label>` +
      `<label title="Gros ordres exécutés (losanges) : bleu = acheteur agressif, blanc = vendeur agressif"><input type="checkbox" data-mo="big"> Gros ordres</label>` +
      `<button class="mini" data-flowreset title="Remettre à zéro le volume échangé affiché dans le carnet">↺ volumes</button>`;
    if (kind === 'liq') return `<span class="seg mini" data-hours><button data-h="24">24 h</button><button data-h="72">3 j</button><button data-h="168">7 j</button><button data-h="0">29 j</button></span>` +
      `<label><input type="checkbox" data-lq="pools"> Poches</label><label><input type="checkbox" data-lq="sweeps"> Balayages</label>` +
      `<label><input type="checkbox" data-lq="real"> Réel</label><label><input type="checkbox" data-lq="profile"> Profil</label>`;
    return `<label><input type="checkbox" data-vp="vD"> J</label><label><input type="checkbox" data-vp="vW"> S</label>` +
      `<label><input type="checkbox" data-vp="vM"> M</label><label><input type="checkbox" data-vp="vY"> A</label>` +
      `<label title="Bandes ±2σ des VWAP affichées"><input type="checkbox" data-vp="bands"> ±2σ</label>` +
      `<label><input type="checkbox" data-vp="avwap"> AVWAP</label>` +
      `<label title="Volume profile des fenêtres choisies (Détails ▾ → VP)"><input type="checkbox" data-vp="profiles"> VP</label>` +
      `<label title="Volume profile de la plage visible à l'écran, à la résolution de la timeframe"><input type="checkbox" data-vp="range"> Plage visible</label>`;
  }
  syncTools() {
    const st = LT.st, h = this.host;
    h.querySelectorAll('input[name=mode]').forEach(r => r.checked = r.value === st.mode);
    h.querySelectorAll('[data-opt=pools]').forEach(c => c.checked = st.pools);
    h.querySelectorAll('[data-opt=ppools]').forEach(c => c.checked = st.ppools);
    h.querySelectorAll('[data-opt=plan]').forEach(c => c.checked = st.planOn);
    h.querySelectorAll('[data-mo]').forEach(c => c.checked = !!st.mainOpts[c.dataset.mo]);
    h.querySelectorAll('[data-flowreset]').forEach(b => b.hidden = !st.mainOpts.dom);
    h.querySelectorAll('[data-lq]').forEach(c => c.checked = !!st.liqOpts[c.dataset.lq]);
    h.querySelectorAll('[data-vp]').forEach(c => c.checked = !!st.vpOpts[c.dataset.vp]);
    h.querySelectorAll('[data-hours] button').forEach(b => b.classList.toggle('on', +b.dataset.h === st.liqOpts.hours));
  }
  onTool(ev) {
    const t = ev.target, st = LT.st;
    if (ev.type === 'click' && t.closest('[data-hours] button')) {
      st.liqOpts.hours = +t.closest('button').dataset.h; LT.savePrefs(); LT.syncAllTools(); LT.pollHeat(); return;
    }
    if (ev.type === 'click' && t.closest('[data-flowreset]')) {
      LT.api('/api/flow/reset', {symbol: st.symbol}).then(() => LT.pollFlow()).catch(() => {}); return;
    }
    if (ev.type !== 'change') return;
    if (t.dataset.mo) {
      st.mainOpts[t.dataset.mo] = t.checked; this.stamp = '';
      LT.savePrefs(); LT.syncAllTools(); LT.refreshAll(); if (['dom', 'sess', 'sessW', 'sessM'].includes(t.dataset.mo)) this.resetView();
      if (typeof MTF !== 'undefined') MTF.redraw(); LT.pollFlow(); return;
    }
    if (t.name === 'mode') { st.mode = t.value; }
    else if (t.dataset.opt === 'pools') { st.pools = t.checked; }
    else if (t.dataset.opt === 'ppools') { st.ppools = t.checked; }
    else if (t.dataset.opt === 'plan') { st.planOn = t.checked; LT.updatePlan(); }
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
    if (this.kind === 'main') {
      ex = d.liquidity.pools.map(p => p.price).concat(LT.shownZones(d).map(z => z.mid));
      const pl = LT.st.plan;
      if (pl && pl.symbol === LT.st.symbol) ex = ex.concat([pl.entry, pl.stop, pl.tp1].concat(pl.tp2 != null ? [pl.tp2] : []));
    }
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
      this.chart.timeScale().setVisibleLogicalRange({from: Math.max(0, this.n - 130), to: this.n + this.rightSpace()});
      this.lastBar = this.n ? bars[this.n - 1].time : 0; this.stamp = '';
      for (const k in this.layers) { this.chart.removeSeries(this.layers[k].s); delete this.layers[k]; }
    } else {
      bars.filter(b => b.time >= this.lastBar).forEach(b => this.updateBar(b));
    }
  }
  resetView() {
    if (this.n) this.chart.timeScale().setVisibleLogicalRange({from: Math.max(0, this.n - 130), to: this.n + this.rightSpace()});
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
    if (this.kind !== 'vp' && this.kind !== 'main') return;
    const st = LT.st, S = st.series, d = st.data, o = st.vpOpts, t = this.th();
    const ok = S && S.ready && d && S.symbol === d.symbol && S.tf === d.tf;
    const want = [];
    if (ok && this.kind === 'main') {
      if (st.mainOpts.vwap && S.vwap.D) {
        want.push({id: 'mV', name: 'VWAP', color: t.vwap, w: 1.5, v: S.vwap.D, mainLabel: 'VWAP'});
        for (const [id, k, lab] of [['mU', 1, '+1σ'], ['mL', -1, '−1σ']])
          want.push({id, name: 'VWAP ' + lab, color: t.band, w: 1, st: 2, v: S.vwap.D.map((x, i) => x == null || S.sd.D[i] == null ? null : x + k * S.sd.D[i]), mainLabel: lab});
      }
    } else if (ok) {
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
    this.countdown();
  }
  // compte a rebours de la bougie en cours, sous l'etiquette du prix (comme TradingView) : hh:mm:ss, ou mm:ss sous une heure
  countdown() {
    const st = LT.st, lb = st.lastBarObj, el = this.cd, per = LT.TF_SEC[st.tf];
    const y = lb && per ? this.series.priceToCoordinate(lb.close) : null, t = this.th(), tag = this.ptag;
    if (y == null || !this.visible()) { if (!el.hidden) el.hidden = true; if (!tag.hidden) tag.hidden = true; return; }
    const now = LT.serverNow() / 1000, left = Math.max(0, Math.ceil(Math.floor(now / per) * per + per - now));       // les bougies sont alignees sur l'epoque UTC
    const two = n => String(n).padStart(2, '0');
    const txt = left >= 3600 ? `${Math.floor(left / 3600)}:${two(Math.floor(left % 3600 / 60))}:${two(left % 60)}` : `${two(Math.floor(left / 60))}:${two(left % 60)}`;
    const w = this.chart.priceScale('right').width(), top = Math.round(y + (t.ownTag ? 9 : 11)), bg = t.cd || (lb.close >= lb.open ? '#26a69a' : '#ef5350');
    const key = [txt, w, top, bg, t.ownTag ? lb.close : ''].join('|');
    if (key === this.cdKey) return;
    this.cdKey = key;
    el.textContent = txt; el.style.width = w + 'px'; el.style.top = top + 'px'; el.style.background = bg; el.style.color = t.cdText; el.hidden = false;
    if (t.ownTag) {                                  // style nuit : etiquette de prix bleue, decompte en dessous (comme dans la video)
      tag.textContent = LT.fmtP(lb.close); tag.style.width = w + 'px'; tag.style.top = Math.round(y - 9) + 'px';
      tag.style.background = t.price; tag.style.color = t.priceText; tag.hidden = false;
    } else if (!tag.hidden) tag.hidden = true;
  }
  draw() {
    const dpr = window.devicePixelRatio || 1, w = this.body.clientWidth, h = this.body.clientHeight;
    for (const cv of [this.ov, this.heatCv]) {
      if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    }
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0); this.hctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.ctx.clearRect(0, 0, w, h); this.hctx.clearRect(0, 0, w, h);
    this._occ = [];
    const L = this.layout(); if (!L) return;
    this._L = L;
    if (this.kind === 'liq') { this.drawHeat(L, w, h); this.drawLiq(L, w, h); }
    else if (this.kind === 'vp') { this.applySeries(); this.drawVP(L, w, h); }
    else { this.applySeries(); this.drawMain(L, w, h); }
  }
  // evite qu'une etiquette en recouvre une autre (zones, plus hauts / bas, noms de niveaux) : decale vers la droite, derriere celle qui gene
  place(x, y, w, h, limit) {
    const occ = this._occ || (this._occ = []);
    let x0 = x;
    for (let k = 0; k < 6; k++) {
      const hit = occ.find(r => x0 < r.x1 && x0 + w > r.x0 && y - h / 2 < r.y1 && y + h / 2 > r.y0);
      if (!hit) break;
      x0 = hit.x1 + 6;
    }
    if (limit != null && x0 + w > limit) x0 = x;                           // plus de place a droite : on garde la position d'origine
    occ.push({x0, x1: x0 + w, y0: y - h / 2, y1: y + h / 2});
    return x0;
  }
  // comme place(), mais si la ligne est pleine jusqu'au bord, essaie juste au-dessus ou en dessous (etiquettes des plus hauts / bas, V14)
  placeXY(x, y, w, h, limit) {
    const occ = this._occ || (this._occ = []);
    const hits = (x0, yy) => occ.find(r => x0 < r.x1 && x0 + w > r.x0 && yy - h / 2 < r.y1 && yy + h / 2 > r.y0);
    for (const dy of [0, h + 2, -(h + 2), 2 * (h + 2), -2 * (h + 2)]) {
      const yy = y + dy;
      let x0 = x;
      for (let k = 0; k < 6 && hits(x0, yy); k++) x0 = hits(x0, yy).x1 + 6;
      if (!hits(x0, yy) && (limit == null || x0 + w <= limit)) { occ.push({x0, x1: x0 + w, y0: yy - h / 2, y1: yy + h / 2}); return {x: x0, y: yy}; }
    }
    return {x: this.place(x, y, w, h, limit), y};
  }
  tag(x, y, text, color, bg, bold, flex) {
    const ctx = this.ctx;
    ctx.font = (bold ? '700 ' : '500 ') + '11px sans-serif';
    const tw = ctx.measureText(text).width + 12, th = 17;
    const lim = this._L ? (this.kind === 'main' && this.rightLimit ? this.rightLimit : this._L.plotW) - 6 : null;
    if (flex) ({x, y} = this.placeXY(x, y, tw, th, lim));
    else x = this.place(x, y, tw, th, lim);
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
      const top = p.rank === 1, a = Math.min(0.9, 0.22 + 0.55 * Math.pow(p.rel || 0, 0.8) + (top ? 0.1 : 0));
      const g = ctx.createLinearGradient(r.x0, 0, r.x1, 0);
      g.addColorStop(0, rgba(col, r.edge ? a * 0.55 : 0.02)); g.addColorStop(r.edge ? 0.04 : 0.55, rgba(col, a * (r.edge ? 0.9 : 0.55))); g.addColorStop(1, rgba(col, a));
      ctx.fillStyle = rgba(col, a * 0.1); ctx.fillRect(r.x0, r.yc - r.thick * 0.9, r.len, r.thick * 1.8);
      ctx.fillStyle = g; ctx.fillRect(r.x0, r.yc - r.thick / 2, r.len, r.thick);
      if (r.edge) { ctx.fillStyle = rgba(col, Math.min(1, a + 0.25)); ctx.fillRect(r.x0, r.yc - r.thick / 2, 2, r.thick); }
      if (st.sel && st.sel.type === 'pool' && st.sel.id === i) { ctx.strokeStyle = rgba(col, 1); ctx.lineWidth = 1.5; ctx.strokeRect(r.x0, r.yc - r.thick / 2 - 2, r.len, r.thick + 4); }
      const dist = (p.price / LT.livePrice(d) - 1) * 100;
      const age = p.imp && p.imp.ageH != null ? (p.imp.ageH < 48 ? Math.round(p.imp.ageH) + ' h' : Math.round(p.imp.ageH / 24) + ' j') : '';
      pills.push({y: r.yc, x1: r.x1, col, magnet: top, text: (p.rank && p.rank <= 2 ? 'N°' + p.rank + ' ' : '') + LT.fmtP(p.price) + '  ' + LT.fmtPct(dist) + (p.imp ? '  ·  ' + p.imp.score + '/100' : '') + (age ? '  ·  ' + age : '')});
    });
    LT.placeLabels(pills, 19, 12, h - 30).forEach(it => {
      ctx.font = (it.magnet ? '700 ' : '500 ') + '11px sans-serif';
      const x = Math.min(it.x1 + 10, (this.kind === 'main' && this.rightLimit ? this.rightLimit : plotW) - ctx.measureText(it.text).width - 14);
      if (Math.abs(it.ly - it.y) > 2) { ctx.strokeStyle = rgba(it.col, 0.6); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(it.x1, it.y); ctx.lineTo(x, it.ly); ctx.stroke(); }
      this.tag(x, it.ly, it.text, it.magnet ? '#0b0e11' : '#fff', rgba(it.col, it.magnet ? 0.92 : 0.55), it.magnet);
    });
  }
  drawPricePools(L, h) {
    const st = LT.st, d = st.data;
    if (!st.ppools || !d || !d.liquidity || !d.liquidity.pricePools) return;
    const ctx = this.ctx, plotW = L.plotW, price = LT.livePrice(d), items = [];
    const near = d.liquidity.pricePools.filter(p => p.score >= 65 || (p.rank && p.rank <= 2)).sort((a, b) => Math.abs(a.price - price) - Math.abs(b.price - price)).slice(0, 8);
    near.forEach(p => {
      const y = this.series.priceToCoordinate(p.price);
      if (y == null || y < 4 || y > h - 4) return;
      const col = p.side === 'long' ? LT.COL_L : LT.COL_S;
      ctx.strokeStyle = LT.rgba(col, 0.55); ctx.lineWidth = 1; ctx.setLineDash([2, 4]);
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(plotW, y); ctx.stroke(); ctx.setLineDash([]);
      const age = p.imp && p.imp.ageH != null ? (p.imp.ageH < 48 ? Math.round(p.imp.ageH) + ' h' : Math.round(p.imp.ageH / 24) + ' j') : '';
      items.push({y, col, text: `${p.rank && p.rank <= 2 ? 'N°' + p.rank + ' ' : ''}${p.src} ${LT.fmtP(p.price)}${p.imp ? ' · ' + p.imp.score + '/100' : ''}${age ? ' · ' + age : ''}`});
    });
    LT.placeLabels(items.map(it => ({...it})), 16, 12, h - 30).forEach(it => {
      this.tag(8, it.ly, it.text, '#e6e8ee', LT.rgba(it.col, 0.38), false, true);
    });
  }
  drawPlan(L, h) {
    const p = LT.st.plan;
    if (!p || p.symbol !== LT.st.symbol) return;
    const ctx = this.ctx, plotW = this.kind === 'main' && this.rightLimit ? Math.max(200, this.rightLimit) : L.plotW, Y = v => this.series.priceToCoordinate(v);
    const ye = Y(p.entry), ys = Y(p.stop), y1 = Y(p.tp1), y2 = p.tp2 != null ? Y(p.tp2) : null;
    if (ye == null || ys == null || y1 == null) return;
    const x0 = Math.max(40, plotW * 0.5);
    ctx.fillStyle = 'rgba(255,107,107,.10)'; ctx.fillRect(x0, Math.min(ye, ys), plotW - x0, Math.abs(ys - ye));
    ctx.fillStyle = 'rgba(61,220,151,.10)'; ctx.fillRect(x0, Math.min(ye, y1), plotW - x0, Math.abs(y1 - ye));
    const pc = v => ((v / p.entry - 1) * 100), fmt = LT.fmtP, sp = v => (v > 0 ? '+' : '') + LT.num(v) + ' %';
    const items = [
      {y: ye, col: '#5ab0ff', dash: [6, 4], text: `${p.side === 'long' ? 'ACHAT' : 'VENTE'} · entrée ${fmt(p.entry)}`},
      {y: ys, col: '#ff6b6b', dash: [3, 3], text: `Stop ${fmt(p.stop)} (${sp(pc(p.stop))})`},
      {y: y1, col: '#3ddc97', dash: [3, 3], text: `Objectif 1 ${fmt(p.tp1)} (${sp(pc(p.tp1))})`}];
    if (y2 != null) items.push({y: y2, col: '#3ddc97', dash: [2, 5], text: `Objectif 2 ${fmt(p.tp2)} (${sp(pc(p.tp2))})`});
    items.forEach(it => { ctx.strokeStyle = it.col; ctx.lineWidth = 1.2; ctx.setLineDash(it.dash); ctx.beginPath(); ctx.moveTo(x0 - 30, it.y); ctx.lineTo(plotW, it.y); ctx.stroke(); });
    ctx.setLineDash([]);
    LT.placeLabels(items.map(it => ({...it})), 18, 12, h - 30).forEach(it => {
      ctx.font = '600 11px sans-serif';
      const tw = ctx.measureText(it.text).width + 14, x = Math.max(8, plotW - tw - 10);
      this.tag(x, it.ly, it.text, '#fff', it.col === '#5ab0ff' ? 'rgba(52,120,200,.85)' : it.col === '#ff6b6b' ? 'rgba(200,60,60,.85)' : 'rgba(30,150,100,.85)', true);
    });
  }
  drawMain(L, w, h) {
    const ctx = this.ctx, st = LT.st, {d, plotW} = L, byId = LT.byId, fmtP = LT.fmtP, pr = LT.pr;
    const sessW = this.drawSession(L, h);
    this.rightLimit = plotW - sessW - (st.mainOpts.dom ? Panel.DOMW + 12 : 0);
    this.drawVpExtras(L, h);
    Panel.drawTpo(ctx, this.series, ms => this.timeX(ms / 1000, L), d.tpo, Panel.tpoKinds(st.mainOpts), this.rightLimit - 2, h, this.th(), false);
    const selZ = st.sel && st.sel.type === 'zone' ? st.sel.id : null;
    const zset = new Map(LT.shownZones(d).map(z => [z.id, z]));
    if (selZ && !zset.has(selZ)) { const z = byId(d.zones)[selZ]; if (z) zset.set(selZ, z); }
    const zl = [];
    zset.forEach(z => {
      const yt = this.series.priceToCoordinate(z.hi), yb = this.series.priceToCoordinate(z.lo);
      if (yt == null || yb == null) return;
      const span = Math.abs(yb - yt), hh = Math.max(6, span), y = Math.min(yt, yb) - (hh - span) / 2, sel = z.id === selZ;
      ctx.fillStyle = `rgba(255,179,0,${sel ? 0.14 : 0.045 + 0.015 * Math.min(4, z.score)})`;
      ctx.fillRect(0, y, plotW, hh);
      // V19 : coeur de la zone (plus marque), prix cle (trait) et prix le plus echange (petit losange blanc au bord droit)
      if (z.core && z.key != null) {
        const ca = this.series.priceToCoordinate(z.core[1]), cb = this.series.priceToCoordinate(z.core[0]), yk = this.series.priceToCoordinate(z.key);
        if (ca != null && cb != null && Math.abs(cb - ca) >= 2 && Math.abs(cb - ca) < hh - 1) { ctx.fillStyle = `rgba(255,179,0,${sel ? 0.16 : 0.08 + 0.015 * Math.min(4, z.score)})`; ctx.fillRect(0, Math.min(ca, cb), plotW, Math.abs(cb - ca)); }
        if (yk != null) { ctx.strokeStyle = `rgba(255,179,0,${sel ? 0.95 : 0.6})`; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(0, Math.round(yk) + 0.5); ctx.lineTo(plotW, Math.round(yk) + 0.5); ctx.stroke(); }
        const yv = z.vpoc ? this.series.priceToCoordinate(z.vpoc) : null, xv = (this.rightLimit || plotW) - 10;
        if (yv != null) { ctx.fillStyle = 'rgba(236,236,236,0.85)'; ctx.beginPath(); ctx.moveTo(xv, yv - 4); ctx.lineTo(xv + 4, yv); ctx.lineTo(xv, yv + 4); ctx.lineTo(xv - 4, yv); ctx.fill(); }
      }
      if (sel) { ctx.strokeStyle = 'rgba(255,179,0,.85)'; ctx.lineWidth = 1; ctx.strokeRect(0.5, y + 0.5, plotW - 1, hh - 1); }
      if (st.mode === 'ess') zl.push({y: (z.key != null ? (this.series.priceToCoordinate(z.key) ?? y + hh / 2) : y + hh / 2), z});
    });
    this.drawPools(L, h);
    this.drawPlan(L, h);
    const lv = byId(d.levels);
    if (st.mode === 'ess') LT.placeLabels(zl, 17, 12, h - 30).forEach(it => {
      const z = it.z, ar = z.side === 'above' ? '▲' : z.side === 'below' ? '▼' : '◆', col = z.side === 'above' ? '#3ddc97' : z.side === 'below' ? '#ff6b6b' : '#ffb300';
      const reach = z.prob && z.side !== 'in' ? ' · ' + pr(z.prob.reach['24']) + '/24 h' : '';
      const txt = `${ar} ${fmtP(z.key != null ? z.key : z.mid)}  ${'●'.repeat(Math.min(5, z.score))}${reach}`;
      ctx.font = '600 11px sans-serif';
      const tw = ctx.measureText(txt).width + 18;
      const zx = this.place(10, it.ly, tw, 18, (this.rightLimit || plotW) - 6);
      ctx.fillStyle = 'rgba(11,14,17,.9)'; ctx.fillRect(zx, it.ly - 9, tw, 18);
      ctx.fillStyle = col; ctx.fillRect(zx, it.ly - 9, 3, 18);
      ctx.fillStyle = '#e1e3ea'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(txt, zx + 9, it.ly + 0.5);
    });
    this.drawPricePools(L, h);                                              // apres les zones : celles-ci gardent la place, les plus hauts / bas se decalent
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
      const txt = it.l.name + '  ' + fmtP(it.l.price), tw = ctx.measureText(txt).width + 22, xx = this.place(st.mode === 'ess' ? 190 : 10, it.ly, tw, 16, (this.rightLimit || plotW) - 6);
      ctx.fillStyle = 'rgba(11,14,17,.88)'; ctx.fillRect(xx, it.ly - 8, tw, 16);
      ctx.fillStyle = c; ctx.fillRect(xx, it.ly - 8, 3, 16);
      ctx.fillStyle = '#d1d4dc'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(txt, xx + 9, it.ly + 0.5);
    });
    this.drawVwapTags(L, h);
    this.drawBig(L, h);
    this.drawFlow(L, h, plotW - sessW);
    this.drawFooter(L, h);
  }

  // ---- V15 / V17 : profils colles a l'echelle des prix (gris = volume, bout bleu / blanc = surplus d'acheteurs / de vendeurs) ----
  drawSession(L, h) {
    const st = LT.st, t = this.th(), ctx = this.ctx, rgba = LT.rgba, fmtP = LT.fmtP, kinds = Panel.profKinds(st.mainOpts);
    const profs = L.d.profiles || {D: L.d.session};
    if (!kinds.length) return 0;
    const W = this.overlayW(L.plotW).W, x1 = L.plotW - 1;
    const r = Panel.drawProfiles(ctx, this.series, profs, kinds, x1, W, h, t);
    const d = r.cols.find(c => c.k === 'D');
    if (d) {                                                    // jour : delta chiffre, POC / VAH / VAL et reperes de la seance
      const s = d.s, len = d.len;
      ctx.font = `500 10px ${t.font}`; ctx.textBaseline = 'middle';
      (s.marks || []).forEach(([px, dv]) => {
        const y = this.series.priceToCoordinate(px); if (y == null || y < 10 || y > h - 30) return;
        const lo = Math.floor(px / s.step + 1e-9) * s.step, k = Object.keys(len).find(x => Math.abs(+x - lo) < s.step / 2);
        ctx.fillStyle = dv > 0 ? rgba(t.vpBuy, 1) : rgba(t.vpSell, 0.95); ctx.textAlign = 'right';
        ctx.fillText((dv > 0 ? '+' : '−') + LT.fmtQty(Math.abs(dv)), d.x - (k != null ? len[k] : W) - 4, y);
      });
      const items = [[s.poc, 'POC', true], [s.vah, 'VAH'], [s.val, 'VAL'], [s.high, 'HAUT SÉANCE ' + fmtP(s.high)], [s.low, 'BAS SÉANCE ' + fmtP(s.low)]];
      if (s.prevClose) items.push([s.prevClose, 'CLÔTURE VEILLE ' + fmtP(s.prevClose)]);
      const lab = items.map(([px, text, strong]) => ({y: this.series.priceToCoordinate(px), text, strong})).filter(it => it.y != null && it.y > 8 && it.y < h - 32);
      LT.placeLabels(lab, 13, 10, h - 32).forEach(it => {
        ctx.strokeStyle = it.strong ? 'rgba(236,236,236,.85)' : 'rgba(150,150,150,.5)'; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(d.x - W - 4, Math.round(it.y) + 0.5); ctx.lineTo(d.x, Math.round(it.y) + 0.5); ctx.stroke();
        ctx.textAlign = 'right';
        if (it.text.length <= 4) { ctx.fillStyle = t.label; ctx.fillText(it.text, d.x - W - 6, it.ly); return; }
        const tw = ctx.measureText(it.text).width + 8;
        ctx.fillStyle = 'rgba(10,10,10,.45)'; ctx.fillRect(d.x - tw - 2, it.ly - 7, tw, 14);
        ctx.fillStyle = t.label; ctx.fillText(it.text, d.x - 6, it.ly);
      });
    }
    return r.cols.length ? r.used + 30 : 0;
  }
  drawVwapTags(L, h) {
    const ctx = this.ctx, t = this.th(), fmtP = LT.fmtP;
    for (const k in this.layers) {
      const m = this.layers[k].meta; if (!m || !m.mainLabel) continue;
      let v = null; for (let i = m.v.length - 1; i >= 0; i--) if (m.v[i] != null) { v = m.v[i]; break; }
      const y = v == null ? null : this.series.priceToCoordinate(v);
      if (y == null || y < 8 || y > h - 30) continue;
      ctx.font = `500 10px ${t.font}`; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillStyle = m.mainLabel === 'VWAP' ? t.vwap : t.label;
      const text = m.mainLabel === 'VWAP' ? 'VWAP ' + fmtP(v) : m.mainLabel, tw = ctx.measureText(text).width;
      ctx.fillText(text, Math.min(L.xr + 8, (this.rightLimit || L.plotW) - tw - 6), y);
    }
  }
  // ---- V15 : gros ordres executes (losanges) ----
  drawBig(L, h) {
    const st = LT.st, f = st.flow, t = this.th(), ctx = this.ctx, rgba = LT.rgba;
    if (!st.mainOpts.big || !f || f.symbol !== L.d.symbol || !f.big || !f.big.length) return;
    const thr = f.threshold || 1;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    f.big.forEach(b => {
      const x = this.timeX(b.t / 1000, L), y = this.series.priceToCoordinate(b.price);
      if (x == null || y == null || x < 0 || x > L.plotW || y < 4 || y > h - 28) return;
      const r = Math.max(7, Math.min(15, 6 + 3.2 * Math.log2(1 + b.usd / thr))), col = b.side === 'buy' ? t.vpBuy : t.vpSell;
      ctx.beginPath(); ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y); ctx.closePath();
      ctx.fillStyle = 'rgba(12,12,12,0.6)'; ctx.fill();
      ctx.strokeStyle = rgba(col, 0.95); ctx.lineWidth = 1.3; ctx.stroke();
      ctx.font = `600 ${r >= 11 ? 9 : 8}px ${t.font}`; ctx.fillStyle = rgba(col, 1);
      ctx.fillText(LT.fmtUsdShort(b.usd), x, y + 0.5);
    });
  }
  // ---- V15 : carnet d'ordres aligne sur les prix, a gauche du profil ----
  drawFlow(L, h, xr) {
    const st = LT.st, f = st.flow, t = this.th(), ctx = this.ctx, rgba = LT.rgba, fq = LT.fmtQty;
    if (!st.mainOpts.dom || !f || f.symbol !== L.d.symbol) return;
    const C = [['bidS', 78], ['sell', 46], ['px', 70], ['buy', 46], ['askS', 78]];
    const totalW = Panel.DOMW, x0 = Math.max(4, xr - totalW - 6), X = {};
    let x = x0; C.forEach(([k, w]) => { X[k] = [x, w]; x += w; });
    ctx.fillStyle = t.domBg; ctx.fillRect(x0 - 4, 0, totalW + 8, h - 26);
    const head = (k, text, col) => { if (!X[k]) return; ctx.fillStyle = col || t.label; ctx.textAlign = 'center'; ctx.fillText(text, X[k][0] + X[k][1] / 2, 9); };
    ctx.font = `600 9.5px ${t.font}`; ctx.textBaseline = 'middle';
    head('bidS', 'ACHAT', rgba(t.vpBuy, 1)); head('sell', 'VOL'); head('px', `RUBAN ${f.tape ? String(f.tape.perSec).replace('.', ',') : '-'}/s`); head('buy', 'VOL'); head('askS', 'VENTE');
    const warn = !f.ready ? 'carnet en attente…' : !f.book.synced ? 'carnet Binance : synchronisation…' : !f.orders.synced ? 'nombre d\'ordres OKX indisponible' : '';
    if (warn) { ctx.fillStyle = '#ffb300'; ctx.textAlign = 'center'; ctx.fillText(warn, x0 + totalW / 2, 21); }
    const rows = f.rows || [];
    if (!rows.length) return;
    const mxS = Math.max(...rows.map(r => Math.max(r[1], r[2]))) || 1, px = LT.livePrice(L.d);
    const txt = (k, s, align, col) => { if (!X[k]) return; const [x, w] = X[k]; ctx.fillStyle = col; ctx.textAlign = align;
      ctx.fillText(s, align === 'right' ? x + w - 3 : align === 'left' ? x + 3 : x + w / 2, txt.y); };
    // nombre d'ordres (OKX) au bord exterieur de la colonne : le chiffre puis une barre par ordre (6 au plus)
    const ticks = (k, n, outer, col, y, rh) => {
      if (!X[k] || n <= 0) return;
      const [x, w] = X[k], m = Math.min(n, 6), bh = Math.max(4, Math.min(10, rh - 5));
      ctx.fillStyle = col;
      for (let i = 0; i < m; i++) ctx.fillRect(outer === 'left' ? x + 21 + i * 3 : x + w - 23 - i * 3, y - bh / 2, 2, bh);
      ctx.font = `500 9px ${t.font}`; ctx.textAlign = outer === 'left' ? 'left' : 'right';
      ctx.fillText(String(n), outer === 'left' ? x + 2 : x + w - 2, y);
    };
    rows.forEach(r => {
      const [lo, bid, ask, bn, an, buy, sell] = r, hi = lo + f.step;
      const yt = this.series.priceToCoordinate(hi), yb = this.series.priceToCoordinate(lo);
      if (yt == null || yb == null) return;
      const y = (yt + yb) / 2, rh = Math.abs(yb - yt);
      if (y < 30 || y > h - 30) return;
      const cur = px >= lo && px < hi;
      if (bid > 0) { const w = bid / mxS * X.bidS[1]; ctx.fillStyle = rgba(t.vpBuy, 0.13); ctx.fillRect(X.bidS[0] + X.bidS[1] - w, yt + 1, w, Math.max(1, rh - 2)); }
      if (ask > 0) { const w = ask / mxS * X.askS[1]; ctx.fillStyle = rgba(t.vpSell, 0.09); ctx.fillRect(X.askS[0], yt + 1, w, Math.max(1, rh - 2)); }
      if (cur) { ctx.fillStyle = t.price; ctx.fillRect(X.px[0] + 2, yt + 1, X.px[1] - 4, Math.max(1, rh - 2)); }
      txt.y = y; ctx.font = `500 10.5px ${t.font}`;
      ctx.shadowColor = 'rgba(0,0,0,0.85)'; ctx.shadowBlur = cur ? 0 : 3;              // fond presque transparent : un halo garde les chiffres lisibles
      txt('px', LT.fmtP(lo), 'center', cur ? t.priceText : t.label);
      ctx.shadowBlur = 3;
      if (bid > 0) txt('bidS', fq(bid), 'right', rgba(t.vpBuy, 1));
      if (ask > 0) { ctx.textAlign = 'left'; txt('askS', fq(ask), 'left', rgba(t.vpSell, 0.95)); }
      if (sell > 0) txt('sell', fq(sell), 'right', sell >= buy ? rgba(t.vpSell, 0.9) : t.label);
      if (buy > 0) txt('buy', fq(buy), 'left', buy >= sell ? rgba(t.vpBuy, 1) : t.label);
      ticks('bidS', bn, 'left', rgba(t.vpBuy, 0.75), y, rh);
      ticks('askS', an, 'right', rgba(t.vpSell, 0.7), y, rh);
      ctx.shadowBlur = 0;
    });
    ctx.shadowBlur = 0; ctx.shadowColor = 'transparent';
  }
  // ---- V15 : ligne d'etat en bas a gauche (latence, vitesse du ruban, seuil des gros ordres) ----
  drawFooter(L, h) {
    const st = LT.st, f = st.flow, t = this.th(), ctx = this.ctx;
    if (!f || f.symbol !== L.d.symbol || !(st.mainOpts.dom || st.mainOpts.big)) return;
    const ms = v => v == null ? '-' : Math.max(0, Math.round(v)) + ' ms';
    const parts = [`flux ${ms(f.latency && f.latency.trades)}`, `carnet ${ms(f.latency && f.latency.book)}`,
      `${f.tape ? String(f.tape.perSec).replace('.', ',') : '-'} transactions/s`, `gros ordre ≥ ${LT.fmtUsdShort(f.threshold || 0)} $`];
    if (f.simulated) parts.push('données simulées');
    ctx.font = `500 10px ${t.font}`; ctx.fillStyle = t.label; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    ctx.fillText(parts.join('  ·  '), 8, h - 36);
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
