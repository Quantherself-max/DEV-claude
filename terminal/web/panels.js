// Panneaux graphiques (V4) : un meme jeu de bougies, trois lectures.
//   main : confluences (mode Essentiel / Confluences / Tous), poches, zones
//   liq  : carte de chaleur des poches de liquidation, balayages, vraies liquidations, profil
//   vp   : VWAP jour / semaine / mois / annee (+ bandes), VWAP ancrees, volume profiles (TF et plage visible)
// Les panneaux partagent l'etat de app.js (window.LT.st) et sont synchronises (zoom, defilement, croix).
// V24.1 : couche SOUS les bougies (primitive de Lightweight Charts) : les bulles des gros ordres sont dessinees derriere les bougies,
// qui restent toujours entieres et lisibles par-dessus. Ancrees en temps et en prix : elles suivent le defilement et le zoom.
class FlowUnder {
  constructor() {
    this.items = []; this.sig = ''; this.req = null; this.chart = null; this.series = null;
    this.view = {zOrder: () => 'bottom', renderer: () => ({draw: target => this.draw(target)})};
  }
  attached(p) { this.chart = p.chart; this.series = p.series; this.req = p.requestUpdate; }
  detached() { this.req = null; this.chart = null; }
  updateAllViews() {}
  paneViews() { return [this.view]; }
  set(items) {
    const sig = items.map(b => `${b.time}|${b.price.toFixed(6)}|${b.r.toFixed(1)}|${b.dx.toFixed(1)}|${b.fa}`).join(';');
    if (sig === this.sig) return;
    this.sig = sig; this.items = items;
    if (this.req) this.req();
  }
  draw(target) {
    if (!this.items.length || !this.chart || !this.series) return;
    target.useMediaCoordinateSpace(({context: ctx}) => {
      const ts = this.chart.timeScale(), rgba = LT.rgba;
      for (const b of this.items) {
        const xc = ts.timeToCoordinate(b.time), y = this.series.priceToCoordinate(b.price);
        if (xc == null || y == null) continue;
        ctx.beginPath(); ctx.arc(xc + b.dx, y, b.r, 0, Math.PI * 2);
        ctx.fillStyle = rgba(b.c, b.fa); ctx.fill();
        ctx.lineWidth = b.lw; ctx.strokeStyle = rgba(b.c, b.sa); ctx.stroke();
      }
    });
  }
}

class Panel {
  constructor(host, kind) {
    this.host = host; this.kind = kind;
    const T = {main: 'Principal', liq: 'Liquidité', vp: 'VWAP · AVWAP · Volume Profile'}[kind];
    host.classList.add('panel', 'k-' + kind);
    host.innerHTML = `<div class="phead"><span class="ptitle">${T}</span><span class="ptools">${Panel.tools(kind)}</span>` +
      `<button class="pmax" title="Agrandir / revenir à la mise en page">⤢</button></div>` +
      `<div class="pbody"><canvas class="heat"></canvas><div class="chart"></div><canvas class="ov"></canvas><div class="ptag" hidden></div><div class="cdwn" hidden title="Temps restant avant la clôture de la bougie en cours"></div><div class="tip" hidden></div>` +
      (kind === 'main' ? '<div class="legend" hidden></div>' : '') + '</div>';
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
    if (kind === 'main' && this.series.attachPrimitive) { this.under = new FlowUnder(); this.series.attachPrimitive(this.under); }
    if (kind === 'main') this.chart.subscribeCrosshairMove(p => {          // V30 : valeurs des sous-fenêtres à l'heure pointée
      const tt = p && p.time != null ? p.time : null;
      if (tt !== this.crossT) { this.crossT = tt; if (this.panes().length) this.sig = ''; }
    });
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
    this.chart.applyOptions({layout: {background: {type: 'solid', color: 'rgba(0,0,0,0)'}, textColor: t.text, fontFamily: t.font, fontSize: t.fontSize},
      grid: {vertLines: {color: t.grid}, horzLines: {color: t.grid}}, rightPriceScale: {borderColor: t.border}, timeScale: {borderColor: t.border},
      crosshair: {vertLine: {color: t.cross, labelBackgroundColor: t.crossLabel}, horzLine: {color: t.cross, labelBackgroundColor: t.crossLabel}}});
    this.series.applyOptions({upColor: t.up, downColor: t.down, wickUpColor: t.up, wickDownColor: t.down, lastValueVisible: !t.ownTag});
    this.host.classList.toggle('th-nuit', LT.st.theme === 'nuit');
    this.body.style.background = t.bg === 'rgba(0,0,0,0)' ? '' : t.bg;          // V28 : fond sous la heatmap du carnet
    if (this.vol) this.vol.applyOptions({priceLineVisible: false});
    for (const k in this.layers) { this.chart.removeSeries(this.layers[k].s); delete this.layers[k]; }
    this.cdKey = ''; this.stamp = ''; this.sig = '';
  }
  // largeurs (pixels) du profil de la seance et du carnet, colles a droite du graphique principal
  static DOMW = 318;
  static profKinds(o) { return ['D', 'W', 'M'].filter(k => o && o[{D: 'sess', W: 'sessW', M: 'sessM'}[k]]); }
  static get PANE() { return 0.17; }                 // hauteur d'une sous-fenêtre (part du graphique)
  static get FUND_UP() { return '#26a69a'; }         // V35 : funding positif (les acheteurs paient) / négatif (les vendeurs paient)
  static get FUND_DN() { return '#ef5350'; }
  // V35 : texte de la sous-fenêtre funding pour la bougie idx : taux, équivalent annuel, moyenne 7 jours, prochain versement
  static fundText(I, idx, mode) {
    const F = I.funding || [], v = F[idx], an = mode === 'an' || mode === true, f = (x, d) => (x >= 0 ? '+' : '−') + Math.abs(x).toFixed(d).replace('.', ',') + ' %';
    if (I.fundErr && !F.some(x => x != null)) return 'Funding · historique Binance injoignable pour l\'instant';
    if (v == null) return 'Funding · pas de versement pour cette bougie';
    const est = I.fundEst != null && idx >= I.fundEst, out = [];
    if (mode === 'cum') {                                                 // V37 : cumulé depuis le début du graphique
      const c = (I.fundCum || [])[idx];
      out.push(c == null ? 'Funding cumulé · -' : `Funding cumulé ${f(c, 3)} : ${c >= 0 ? 'un acheteur a payé, un vendeur a reçu' : 'un vendeur a payé, un acheteur a reçu'} cette part de sa position`);
      out.push(`bougie ${f(v, 4)} / 8 h`);
    } else out.push(an ? `Funding ${f(v * 1095, 1)} par an (${f(v, 4)} / 8 h)` : `Funding ${f(v, 4)} / 8 h (${f(v * 1095, 1)} par an)`);
    out.push(v >= 0.03 ? 'acheteurs à levier nombreux : ils paient cher' : v <= -0.01 ? 'vendeurs à levier nombreux : ils paient' : v < 0 ? 'les vendeurs paient' : 'neutre');
    if (est && I.fundNext) {
      const left = Math.max(0, I.fundNext - LT.serverNow()), hh = Math.floor(left / 3.6e6), mm = Math.floor(left % 3.6e6 / 6e4);
      out.push(`estimation en cours, versement dans ${hh} h ${String(mm).padStart(2, '0')}` + (I.fundHours && I.fundHours !== 8 ? ` (période de ${I.fundHours} h)` : ''));
    } else if (est) out.push('estimation en cours');
    if (I.fundAvg7 != null) out.push(`moyenne 7 j ${f(I.fundAvg7, 4)}`);
    return out.join(' · ');
  }
  // V37 : funding de toutes les bourses pondéré par l'intérêt ouvert, et la lecture des positions confirmée par le funding
  static fundAggText(I) {
    const g = I.fundAgg, f = x => (x >= 0 ? '+' : '−') + Math.abs(x).toFixed(4).replace('.', ',') + ' %', out = [];
    if (g && g.n > 1) out.push(`${g.n} bourses pondérées par l'intérêt ouvert ${f(g.rate8h)} / 8 h (` + g.rows.map(r => `${r.ex} ${Math.round(r.share * 100)} %`).join(', ') + ')');
    if (I.posNote) out.push({txt: I.posNote, col: '#f5c26b'});
    return out.length ? out : null;
  }
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
    if (o.dpoc && D && D.developing && D.developing.length > 1 && !['1d', '1w', '1M'].includes(st.tf)) {
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
  // V30 : marques TPO épurées (le serveur ne garde que les single prints non retraversées, aux bords exacts, et les poor highs / lows pas
  // encore dépassés) ; ici : la plus grande unité de temps d'abord, une marque déjà couverte par une plus grande n'est pas redessinée (son
  // étiquette dit « aussi 1 j »), et seulement les séances récentes de chaque unité
  static drawTpo(ctx, series, xOf, marks, kinds, xr, h, t, small) {
    if (!marks || !kinds.length) return;
    const TXT = {M: 'mois', W: 'semaine', D: '1 j', '4h': '4 h', '1h': '1 h'}, HTF = {M: true, W: true}, KEEP = {M: 6, W: 8, D: 6, '4h': 6, '1h': 4};
    const ORDER = ['M', 'W', 'D', '4h', '1h'].filter(k => kinds.includes(k));
    ctx.font = `500 ${small ? 8.5 : 9.5}px ${t.font}`;
    const taken = [], free = (x, y) => !taken.some(q => Math.abs(q[0] - x) < 110 && Math.abs(q[1] - y) < 11);  // pas d'etiquettes superposees
    const zones = [], lines = [];
    ORDER.forEach(k => (marks[k] || []).slice(-KEEP[k]).forEach(ss => {
      const x0 = Math.max(0, xOf(ss.start) == null ? 0 : xOf(ss.start));
      if (x0 >= xr - 4) return;
      (ss.singles || []).forEach(([lo, hi, filled]) => {
        if (filled) return;
        const same = zones.find(z => Math.min(hi, z.hi) - Math.max(lo, z.lo) >= 0.7 * (hi - lo));
        if (same) { if (!same.also.includes(TXT[k])) same.also.push(TXT[k]); return; }
        zones.push({lo, hi, k, x0, also: []});
      });
      [['poorHigh', 'poor high'], ['poorLow', 'poor low']].forEach(([key, lab]) => {
        const pm = ss[key];
        if (!pm || !pm.active) return;
        const same = lines.find(l => l.key === key && Math.abs(l.price - pm.price) <= pm.price * 0.0004);
        if (same) { if (!same.also.includes(TXT[k])) same.also.push(TXT[k]); return; }
        lines.push({key, lab, price: pm.price, k, x0, n: pm.n || 2, also: []});
      });
    }));
    zones.forEach(z => {
      const yt = series.priceToCoordinate(z.hi), yb = series.priceToCoordinate(z.lo);
      if (yt == null || yb == null || yb < 0 || yt > h - 26) return;
      const hh = Math.max(2, yb - yt), big = HTF[z.k];
      ctx.fillStyle = t.spFill; ctx.fillRect(z.x0, yt, xr - z.x0, hh);
      if (big) ctx.fillRect(z.x0, yt, xr - z.x0, hh);                                   // fond deux fois plus marque
      ctx.strokeStyle = t.spLine; ctx.lineWidth = big ? 1.6 : 1; ctx.strokeRect(Math.round(z.x0) + 0.5, Math.round(yt) + 0.5, Math.max(1, xr - z.x0 - 1), Math.max(1, hh - 1));
      if (hh >= 11 && free(z.x0, yt)) {
        taken.push([z.x0, yt]); ctx.fillStyle = t.label; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
        ctx.fillText(`single prints ${TXT[z.k]}${z.also.length ? ' · aussi ' + z.also.join(', ') : ''}`, z.x0 + 3, yt + 2);
      }
    });
    lines.forEach(l => {
      const y = series.priceToCoordinate(l.price);
      if (y == null || y < 4 || y > h - 26) return;
      ctx.strokeStyle = t.poor; ctx.lineWidth = HTF[l.k] ? 1.5 : 1; ctx.setLineDash([5, 4]);
      ctx.beginPath(); ctx.moveTo(l.x0, Math.round(y) + 0.5); ctx.lineTo(xr, Math.round(y) + 0.5); ctx.stroke(); ctx.setLineDash([]);
      const ly = l.key === 'poorHigh' ? y - 6 : y + 6;
      if (!free(xr - 60, ly)) return;
      taken.push([xr - 60, ly]);
      ctx.fillStyle = t.poor; ctx.textAlign = 'right'; ctx.textBaseline = l.key === 'poorHigh' ? 'bottom' : 'top';
      ctx.fillText(`${l.lab} ${TXT[l.k]}${l.n >= 3 ? ` (${l.n} tranches)` : ''}${l.also.length ? ' · aussi ' + l.also.join(', ') : ''}`, xr - 4, l.key === 'poorHigh' ? y - 1 : y + 1);
    });
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
  // V28 : graphique à éléments : un seul bouton « ＋ Éléments » (menu de desk.js) ; les éléments choisis sont listés dans la légende du graphique
  static tools(kind) {
    if (kind === 'main') return '<span class="viewname"></span><button type="button" class="ddb elbtn" data-elbtn title="Choisir ce qui est dessiné sur ce graphique">＋ Éléments</button>' +
      '<button class="mini" data-flowreset title="Remettre à zéro le volume échangé affiché dans le carnet">↺ volumes</button>';
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
    h.querySelectorAll('[data-flowreset]').forEach(b => b.hidden = !st.mainOpts.dom);
    h.querySelectorAll('[data-lq]').forEach(c => c.checked = !!st.liqOpts[c.dataset.lq]);
    h.querySelectorAll('[data-vp]').forEach(c => c.checked = !!st.vpOpts[c.dataset.vp]);
    h.querySelectorAll('[data-hours] button').forEach(b => b.classList.toggle('on', +b.dataset.h === st.liqOpts.hours));
    if (this.kind === 'main' && typeof Desk !== 'undefined') Desk.renderLegend();
  }
  onTool(ev) {
    const t = ev.target, st = LT.st;
    if (ev.type === 'click' && t.closest('[data-elbtn]')) { Desk.toggleChooser(t.closest('[data-elbtn]')); return; }
    if (ev.type === 'click' && t.closest('[data-hours] button')) {
      st.liqOpts.hours = +t.closest('button').dataset.h; LT.savePrefs(); LT.syncAllTools(); LT.pollHeat(); return;
    }
    if (ev.type === 'click' && t.closest('[data-flowreset]')) {
      LT.api('/api/flow/reset', {symbol: st.symbol}).then(() => LT.pollFlow()).catch(() => {}); return;
    }
    if (ev.type !== 'change') return;
    if (t.dataset.lq) { st.liqOpts[t.dataset.lq] = t.checked; }
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
      (LT.st.plans || []).filter(pl => pl.symbol === LT.st.symbol && pl.status !== 'closed')
        .forEach(pl => { ex = ex.concat([pl.entry, pl.stop, pl.tp1].concat(pl.tp2 != null ? [pl.tp2] : [])); });
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
      // V28 : VWAP de la semaine, du mois, de l'année et VWAP ancrés, comme éléments du graphique principal
      for (const [k, opt, lab] of [['W', 'vwapW', 'VWAP S'], ['M', 'vwapM', 'VWAP M'], ['Y', 'vwapY', 'VWAP A']])
        if (st.mainOpts[opt] && S.vwap[k]) want.push({id: 'm' + k, name: lab, color: LT.PER[k.toLowerCase()], w: 1.5, v: S.vwap[k], mainLabel: lab});
      if (st.mainOpts.avwap) (S.avwap || []).slice(0, 4).forEach((a, i) => want.push({id: 'mA' + i, name: a.label, color: ['#E0E0E0', '#B0BEC5', '#90A4AE', '#78909C'][i], w: 1.2, st: 1, v: a.v, mainLabel: a.label}));
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
    const now = LT.serverNow() / 1000, left = Math.max(0, Math.ceil(LT.barEnd(now, st.tf) - now));       // V36 : semaine du lundi, mois calendaire
    const txt = LT.leftTxt(left);
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
    else {
      this.applySeries(); this.syncVolume(L.d); this.syncSubcharts(L.d);
      const cb = this.candleBottom(h);                 // V30 : rien du graphique des prix ne déborde sur les sous-fenêtres
      this.ctx.save(); this.ctx.beginPath(); this.ctx.rect(0, 0, w, cb); this.ctx.clip();
      this.drawMain(L, w, h);
      this.ctx.restore();
      this.drawPanes(L, w, h);
    }
  }
  // ---- V30 : sous-fenêtres sous les bougies (intérêt ouvert en bougies, delta en barres et CVD), chacune sur sa propre échelle ;
  // V35 : funding en barres (% par 8 h ou par an), la dernière barre plus pâle (estimation de la période en cours) ;
  // V37 : intérêt ouvert en bougies ou en variation, coloré selon QUI OUVRE ou QUI FERME (prix x intérêt ouvert x delta) ; delta en coin
  // ou en dollars exacts ; CVD du perpétuel, du spot ou des deux, cumulé sur le graphique ou remis à zéro chaque jour, semaine ou mois ;
  // funding par 8 h, par an ou cumulé ; lectures chiffrées en tête de chaque fenêtre ----
  panes() {
    const o = LT.st.mainOpts || {};
    return this.kind === 'main' ? ['oi', 'delta', 'fund'].filter(k => o[k]) : [];
  }
  static get POS_COL() { return {0: '#7b8394', 1: '#26c281', 2: '#ff4d6d', 3: '#6ec8ff', 4: '#ffa64d'}; }
  static get POS_TXT() { return {0: 'intérêt ouvert stable', 1: 'acheteurs qui ouvrent', 2: 'vendeurs qui ouvrent', 3: 'vendeurs qui rachètent', 4: 'acheteurs qui sortent'}; }
  // montant court et signé : 1,2 k · 3,4 M · 1,25 Md
  static big(v, sign = true) {
    if (v == null || isNaN(v)) return '-';
    const x = Math.abs(v), sg = sign ? (v >= 0 ? '+' : '−') : (v < 0 ? '−' : ''), f = (n, d) => n.toFixed(d).replace('.', ',');
    const t = x >= 1e9 ? f(x / 1e9, 2) + ' Md' : x >= 1e6 ? f(x / 1e6, x >= 1e8 ? 0 : 1) + ' M' : x >= 1e4 ? f(x / 1e3, 0) + ' k' : x >= 1e3 ? f(x / 1e3, 1) + ' k' : x >= 10 ? f(x, 0) : f(x, 2);
    return sg + t;
  }
  // V37 : CVD remis à zéro au début de chaque jour / semaine / mois (UTC) ; sans effet si la bougie est déjà aussi longue que la période
  static cvdReset(I) {
    const r = (LT.st.mainOpts || {}).cvdReset, per = {D: ['1d', 86400], W: ['1w', 604800], M: ['1M', 2419200]}[r];
    return per && (LT.TF_SEC[I.tf] || 0) < per[1] ? per[0] : null;
  }
  static cvdLine(I, vals) {
    const rs = Panel.cvdReset(I);
    let run = 0, prev = null;
    return I.times.map((tm, i) => {
      if (rs) { const k = LT.barStart(tm, rs); if (prev !== null && k !== prev) run = 0; prev = k; }
      const v = vals[i]; if (v != null) run += v;
      return run;
    });
  }
  candleBottom(h) { return Math.max(40, (h - 26) * (1 - this.panes().length * Panel.PANE)); }
  syncSubcharts(d) {
    const st = LT.st, I = st.ind, o = st.mainOpts || {}, panes = this.panes(), n = panes.length, P = Panel.PANE, t = this.th();
    const ok = !!(I && I.ready && d && I.symbol === d.symbol && I.tf === d.tf);
    const cvdM = o.cvdMode || (o.deltaCvd ? 'perp' : 'off'), dOn = ok && panes.includes('delta'), fOn = ok && panes.includes('fund') && Array.isArray(I.funding);
    const want = {oiS: ok && panes.includes('oi') && o.oiMode !== 'chg', oiH: ok && panes.includes('oi') && o.oiMode === 'chg', dS: dOn,
      cvdS: dOn && (cvdM === 'perp' || cvdM === 'both'), spS: dOn && (cvdM === 'spot' || cvdM === 'both') && Array.isArray(I.spotDelta),
      fdS: fOn && o.fundMode !== 'cum', fdC: fOn && o.fundMode === 'cum' && Array.isArray(I.fundCum)};
    for (const k of Object.keys(want)) if (!want[k] && this[k]) { this.chart.removeSeries(this[k]); this[k] = null; }
    const base = {lastValueVisible: false, priceLineVisible: false, priceFormat: {type: 'volume'}};
    if (want.oiS && !this.oiS) this.oiS = this.chart.addCandlestickSeries({...base, priceScaleId: 'oi', borderVisible: false,
      upColor: '#4fc3f7', downColor: '#ffa64d', wickUpColor: '#4fc3f7', wickDownColor: '#ffa64d'});
    if (want.oiH && !this.oiH) this.oiH = this.chart.addHistogramSeries({...base, priceScaleId: 'oi'});
    if (want.dS && !this.dS) this.dS = this.chart.addHistogramSeries({...base, priceScaleId: 'dl'});
    const fpf = {type: 'price', precision: 4, minMove: 0.0001};
    if (want.fdS && !this.fdS) this.fdS = this.chart.addHistogramSeries({lastValueVisible: false, priceLineVisible: false, priceScaleId: 'fd', priceFormat: fpf});
    if (want.fdC && !this.fdC) this.fdC = this.chart.addLineSeries({lastValueVisible: false, priceLineVisible: false, priceScaleId: 'fd', priceFormat: fpf, color: '#f5c26b', lineWidth: 1.5, crosshairMarkerVisible: false});
    if (want.cvdS && !this.cvdS) this.cvdS = this.chart.addLineSeries({...base, priceScaleId: 'cvd', color: '#e8eaf0', lineWidth: 1.5, crosshairMarkerVisible: false});
    if (want.spS && !this.spS) this.spS = this.chart.addLineSeries({...base, priceScaleId: 'cvds', color: '#ffb74d', lineWidth: 1.5, crosshairMarkerVisible: false});
    const lk = [n, !!this.vol, ...Object.keys(want).map(k => !!this[k])].join();
    if (lk !== this.paneKey) {
      this.paneKey = lk;
      this.chart.priceScale('right').applyOptions({scaleMargins: {top: 0.08, bottom: 0.08 + n * P}});
      if (this.vol) this.chart.priceScale('vol').applyOptions({scaleMargins: {top: Math.max(0.3, 0.84 - n * P), bottom: n * P}});
      const pos = k => { const i = n - 1 - panes.indexOf(k); return {top: 1 - (i + 1) * P + 0.05, bottom: i * P + 0.012}; };   // V37 : place pour deux lignes de lecture
      if (this.oiS || this.oiH) this.chart.priceScale('oi').applyOptions({scaleMargins: pos('oi'), visible: false});
      if (this.fdS || this.fdC) this.chart.priceScale('fd').applyOptions({scaleMargins: pos('fund'), visible: false});
      for (const [id, k] of [['dl', 'dS'], ['cvd', 'cvdS'], ['cvds', 'spS']]) if (this[k]) this.chart.priceScale(id).applyOptions({scaleMargins: pos('delta'), visible: false});
      this.indKey = '';
    }
    if (!ok) return;
    const F = I.funding || [], an = o.fundMode === 'an', usd = o.deltaUnit === 'usd', SD = I.spotDelta || [], L = I.times.length - 1;
    const dk = [I.symbol, I.tf, I.times.length, I.times[L], JSON.stringify(I.oi[L]), I.delta[L], (I.pos || [])[L], SD.length, SD[SD.length - 1], F.length, F[F.length - 1], I.fundEst,
      o.fundMode, o.oiMode, o.oiColor, o.deltaUnit, cvdM, o.cvdReset, st.theme, lk].join('|');
    if (dk === this.indKey) return;
    this.indKey = dk;
    const up = t.up, dn = t.down, a = (c, al) => /^#[0-9a-f]{6}$/i.test(c) ? `rgba(${parseInt(c.slice(1, 3), 16)},${parseInt(c.slice(3, 5), 16)},${parseInt(c.slice(5, 7), 16)},${al})` : c;
    const posOn = o.oiColor !== 'dir' && Array.isArray(I.pos), PC = Panel.POS_COL;
    const pcol = i => { const c = posOn ? I.pos[i] : null; return c == null ? null : PC[c]; };
    if (this.oiS) this.oiS.setData(I.times.map((tm, i) => {
      const c = I.oi[i]; if (!c) return {time: tm};
      const col = pcol(i), b = {time: tm, open: c[0], high: c[1], low: c[2], close: c[3]};
      return col ? {...b, color: col, wickColor: col, borderColor: col} : b;
    }));
    if (this.oiH) this.oiH.setData(I.times.map((tm, i) => {
      const c = I.oi[i]; if (!c || c[0] == null) return {time: tm};
      const v = c[3] - c[0]; return {time: tm, value: v, color: pcol(i) || (v >= 0 ? '#4fc3f7' : '#ffa64d')};
    }));
    const DV = usd && Array.isArray(I.deltaUsd) ? I.deltaUsd : I.delta, SV = usd && Array.isArray(I.spotDeltaUsd) ? I.spotDeltaUsd : SD;
    if (this.dS) this.dS.setData(I.times.map((tm, i) => { const v = DV[i]; return v == null ? {time: tm} : {time: tm, value: v, color: v >= 0 ? a(up, 0.8) : a(dn, 0.8)}; }));
    if (this.cvdS) { const c = Panel.cvdLine(I, DV); this.cvdS.setData(I.times.map((tm, i) => ({time: tm, value: c[i]}))); }
    if (this.spS) { const c = Panel.cvdLine(I, SV); this.spS.setData(I.times.map((tm, i) => SV[i] == null && !c[i] ? {time: tm} : {time: tm, value: c[i]})); }
    if (this.fdS) this.fdS.setData(I.times.map((tm, i) => {               // fort (≥ 0,03 % ou ≤ −0,01 % par 8 h) : couleur pleine
      const v = F[i]; if (v == null) return {time: tm};
      const est = I.fundEst != null && i >= I.fundEst, strong = v >= 0.03 || v <= -0.01;
      return {time: tm, value: an ? v * 3 * 365 : v, color: a(v >= 0 ? Panel.FUND_UP : Panel.FUND_DN, est ? 0.35 : strong ? 0.95 : 0.55)};
    }));
    if (this.fdC) this.fdC.setData(I.times.map((tm, i) => I.fundCum[i] == null ? {time: tm} : {time: tm, value: I.fundCum[i]}));
  }
  // V37 : lectures en tête de chaque fenêtre (ligne 1 : la bougie visée ; ligne 2 : le résumé)
  paneLines(k, I, idx) {
    const o = LT.st.mainOpts || {}, unit = I.unit, pct = (x, d = 2) => (x >= 0 ? '+' : '−') + Math.abs(x * 100).toFixed(d).replace('.', ',') + ' %';
    if (k === 'fund') return [Panel.fundText(I, idx, o.fundMode), Panel.fundAggText(I)];
    if (k === 'oi') {
      const c = I.oi[idx];
      if (!c) return ['Intérêt ouvert · pas de relevé pour cette bougie'];
      const px = (I.close || [])[idx], first = I.oi.find(x => x), code = (I.pos || [])[idx], cf = (I.posConf || [])[idx];
      const l1 = [`Intérêt ouvert ${Panel.big(c[3], false)} ${unit}` + (px ? ` ≈ ${Panel.big(c[3] * px, false)} $` : '')];
      if (c[0]) l1.push(`bougie ${Panel.big(c[3] - c[0])} (${pct(c[3] / c[0] - 1)})`);
      if (code != null) l1.push({txt: Panel.POS_TXT[code] + (code && cf === false ? ' (contre le delta : ordres passifs)' : ''), col: Panel.POS_COL[code]});
      if (idx === I.times.length - 1 && I.oiLive) l1.push('relevé à l\'instant');
      else if (first && idx === I.times.length - 1) l1.push(`depuis le début du graphique ${pct(c[3] / first[3] - 1, 1)}`);
      const S = I.posSum;
      if (!S || !S.bars) return [l1];
      const l2 = [`${S.bars} dernières bougies${S.oiChg != null ? ` (intérêt ouvert ${pct(S.oiChg, 1)})` : ''}`];
      [[1, S.longsOpen], [2, S.shortsOpen], [3, S.shortsClose], [4, S.longsClose]].forEach(([cd, v]) => { if (v) l2.push({txt: `${Panel.POS_TXT[cd]} ${Panel.big(v)}`, col: Panel.POS_COL[cd], strong: cd === S.dominant}); });
      return [l1, l2];
    }
    const usd = o.deltaUnit === 'usd' && Array.isArray(I.deltaUsd), u = usd ? '$' : unit, cvdM = o.cvdMode || (o.deltaCvd ? 'perp' : 'off');
    if (!I.realDelta) return ['Delta · volume acheteur agressif inconnu'];
    const DV = usd ? I.deltaUsd : I.delta, v = DV[idx], rs = Panel.cvdReset(I), lab = rs ? {['1d']: ' du jour', ['1w']: ' de la semaine', ['1M']: ' du mois'}[rs] : '';
    const l1 = [`Delta ${v == null ? '-' : Panel.big(v) + ' ' + u}` + (usd ? (I.deltaExact >= 0.99 ? ' (exact)' : ` (${Math.round(I.deltaExact * 100)} % exact)`) : '')];
    let pc = null, sc = null;
    if (cvdM === 'perp' || cvdM === 'both') { pc = Panel.cvdLine(I, DV); l1.push({txt: `CVD perp${lab} ${Panel.big(pc[idx])} ${u}`, col: '#e8eaf0'}); }
    if (cvdM === 'spot' || cvdM === 'both') {
      if (!Array.isArray(I.spotDelta)) l1.push('CVD spot · chargement…');
      else if (!I.spotOk) l1.push(I.spotErr ? 'CVD spot · Binance spot injoignable' : 'CVD spot · pas de bougie spot');
      else { const SV = usd && I.spotDeltaUsd ? I.spotDeltaUsd : I.spotDelta; sc = Panel.cvdLine(I, SV); l1.push({txt: `CVD spot${lab} ${Panel.big(sc[idx])} ${u}`, col: '#ffb74d'}); }
    }
    if (!(pc && sc)) return [l1];
    const N = Math.min(idx, (I.posSum && I.posSum.bars) || 24), dp = pc[idx] - pc[idx - N], ds = sc[idx] - sc[idx - N];
    const lead = dp > 0 && ds > 0 ? 'spot et perpétuel achètent ensemble : mouvement sain' : dp < 0 && ds < 0 ? 'spot et perpétuel vendent ensemble' :
      dp > 0 ? 'le levier achète, le spot vend : hausse fragile' : 'le spot achète, le levier vend : les vendeurs à levier s\'exposent';
    return [l1, [`${N} dernières bougies : ${lead}`]];
  }
  drawPanes(L, w, h) {
    const panes = this.panes();
    if (!panes.length) return;
    const ctx = this.ctx, st = LT.st, I = st.ind, t = this.th(), P = Panel.PANE, H = h - 26, n = panes.length, plotW = L.plotW;
    const ok = !!(I && I.ready && I.symbol === L.d.symbol && I.tf === L.d.tf);
    let idx = ok ? I.times.length - 1 : -1;
    if (ok && this.crossT != null) { const k = I.times.indexOf(this.crossT); if (k >= 0) idx = k; }
    ctx.font = `500 11px ${t.font}`; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    const fit = parts => {                                                // petit écran : on garde les premiers morceaux qui tiennent
      const out = []; let wsum = 0;
      for (const p of parts) { const s = typeof p === 'string' ? p : p.txt, ww = ctx.measureText((out.length ? ' · ' : '') + s).width; if (out.length && wsum + ww > plotW - 16) break; out.push(p); wsum += ww; }
      return out;
    };
    panes.forEach((k, j) => {
      const y0 = Math.round(H * (1 - (n - j) * P)) + 0.5, ph = H * P;
      ctx.strokeStyle = 'rgba(120,130,150,.35)'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(0, y0); ctx.lineTo(plotW, y0); ctx.stroke();
      const lines = !ok || (k === 'fund' && !Array.isArray(I.funding)) ? [({oi: 'Intérêt ouvert', delta: 'Delta', fund: 'Funding'})[k] + ' · chargement…'] : this.paneLines(k, I, idx);
      const base = k === 'oi' ? '#8fd3f4' : k === 'fund' ? '#f5c26b' : '#cfd3dc';
      lines.filter(Boolean).slice(0, ph > 46 ? 2 : 1).forEach((ln, li) => {
        const parts = fit(typeof ln === 'string' ? ln.split(' · ') : ln), y = y0 + 2 + li * 16;
        const tw = parts.reduce((s2, p, i) => s2 + ctx.measureText((i ? ' · ' : '') + (typeof p === 'string' ? p : p.txt)).width, 0);
        ctx.fillStyle = 'rgba(10,12,16,.78)'; ctx.fillRect(4, y, tw + 10, 16);
        let x = 9;
        parts.forEach((p, i) => {
          if (i) { ctx.fillStyle = base; ctx.font = `500 11px ${t.font}`; ctx.fillText(' · ', x, y + 2); x += ctx.measureText(' · ').width; }
          const s2 = typeof p === 'string' ? p : p.txt;
          ctx.font = `${p.strong ? 700 : 500} 11px ${t.font}`; ctx.fillStyle = (typeof p === 'object' && p.col) || (li ? 'rgba(207,211,220,.85)' : base);
          ctx.fillText(s2, x, y + 2); x += ctx.measureText(s2).width;
        });
        ctx.font = `500 11px ${t.font}`;
      });
    });
    ctx.textBaseline = 'middle';
  }
  // V28 : barres de volume sous les bougies (élément « Volume »), sur leur propre échelle, en bas du graphique
  syncVolume(d) {
    const on = LT.st.mainOpts.vol && d && d.candles && d.candles.length;
    if (!on) { if (this.vol) { this.chart.removeSeries(this.vol); this.vol = null; this.volKey = ''; } return; }
    const t = this.th(), hexA = (c, a) => /^#[0-9a-f]{6}$/i.test(c) ? `rgba(${parseInt(c.slice(1, 3), 16)},${parseInt(c.slice(3, 5), 16)},${parseInt(c.slice(5, 7), 16)},${a})` : c;
    if (!this.vol) {
      this.vol = this.chart.addHistogramSeries({priceScaleId: 'vol', priceFormat: {type: 'volume'}, lastValueVisible: false, priceLineVisible: false});
      this.chart.priceScale('vol').applyOptions({scaleMargins: {top: 0.84, bottom: 0}, visible: false});
      this.volKey = ''; this.paneKey = '';
    }
    const cs = d.candles, last = cs[cs.length - 1], key = [d.symbol, d.tf, cs.length, last[0], last[5], LT.st.theme].join('|');
    if (key === this.volKey) return;
    this.volKey = key;
    const up = hexA(t.up, 0.34), dn = hexA(t.down, 0.22);
    this.vol.setData(cs.map(c => ({time: c[0], value: c[5] || 0, color: c[4] >= c[1] ? up : dn})));
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
  drawGex(L, h) {
    // V26 : gamma des options BTC. Barres de gamma par strike au bord gauche (vert : gamma positif, rouge : négatif), lignes du mur de calls,
    // du mur de puts et de la bascule, avec les VWAP et VWAP ancrés tout proches (confluences). V38 : zones de gamma positif / négatif,
    // strike au plus fort gamma, max pain, mouvement attendu 24 h, distance au prix, et deux lignes de lecture en bas à gauche.
    const st = LT.st, g = L.d.gex, mo = st.mainOpts;
    if (!mo.gex || st.symbol !== 'BTCUSDT' || !g || g.error || !g.levels) return;
    const ctx = this.ctx, plotW = this.kind === 'main' && this.rightLimit ? Math.max(200, this.rightLimit) : L.plotW, Y = v => this.series.priceToCoordinate(v);
    const fade = g.stale ? 0.45 : 1, bottom = h - (L.plotW < 600 ? 110 : 64);
    if (mo.gexZones !== false) (g.zones || []).forEach(z => {
      if (!z.sign) return;
      const yt = Y(z.hi), yb = Y(z.lo), a = yt == null ? 0 : yt, b = yb == null ? h : yb;
      if (b < 0 || a > h) return;
      ctx.fillStyle = z.sign > 0 ? `rgba(61,220,151,${0.035 * fade})` : `rgba(255,107,107,${0.045 * fade})`;
      ctx.fillRect(0, Math.max(0, a), plotW, Math.min(h, b) - Math.max(0, a));
    });
    const strikes = (g.strikes || []).map(x => ({...x, y: Y(x.strike)})).filter(x => x.y != null && x.y > 0 && x.y < h - 24);
    const split = mo.gexBars === 'split', barMax = Math.min(90, plotW * 0.12);
    const mx = Math.max(1, ...strikes.map(x => split ? Math.max(Math.abs(x.calls), Math.abs(x.puts)) : Math.abs(x.net)));
    ctx.globalAlpha = 0.55 * fade;
    strikes.forEach(x => {
      if (split) {
        ctx.fillStyle = '#3ddc97'; ctx.fillRect(0, x.y - 3, Math.max(1, barMax * Math.abs(x.calls) / mx), 3);
        ctx.fillStyle = '#ff6b6b'; ctx.fillRect(0, x.y, Math.max(1, barMax * Math.abs(x.puts) / mx), 3);
      } else {
        ctx.fillStyle = x.net >= 0 ? '#3ddc97' : '#ff6b6b'; ctx.fillRect(0, x.y - 2, Math.max(1, barMax * Math.abs(x.net) / mx), 4);
      }
    });
    ctx.globalAlpha = fade;
    const COL = Panel.GEX_COL, ESS = ['callwall', 'putwall', 'flip', 'absgamma', 'emup', 'emdn'], all = mo.gexLevels === 'all';
    const fmt = LT.fmtP, musd = v => v == null ? '' : ` · ${v > 0 ? '+' : '−'}${LT.num(Math.abs(v) / 1e6, 1)} M$ par 1 %`;
    const dist = k => k.distPct == null ? '' : Math.abs(k.distPct) < 0.05 ? ' · au prix' : ` · ${k.distPct > 0 ? '+' : '−'}${LT.num(Math.abs(k.distPct), 1)} %`;
    const labels = [];
    g.levels.forEach(k => {
      if (!all && !ESS.includes(k.kind) && !(k.kind === 'strike' && k.vwap && k.vwap.length)) return;
      const y = Y(k.price);
      if (y == null || y < 0 || y > h - 24) return;
      const em = k.kind === 'emup' || k.kind === 'emdn';
      ctx.strokeStyle = COL[k.kind] || COL.strike; ctx.lineWidth = k.kind === 'strike' || em ? 1 : 1.4;
      ctx.setLineDash(k.kind === 'flip' ? [7, 4] : k.kind === 'strike' ? [1, 4] : em ? [3, 5] : k.kind === 'maxpain' ? [2, 3] : [10, 3]);
      ctx.beginPath(); ctx.moveTo(barMax + 4, y); ctx.lineTo(plotW, y); ctx.stroke();
      if (k.kind === 'strike' && !all && !(k.vwap && k.vwap.length)) return;
      const conf = k.vwap && k.vwap.length ? ` ≈ ${k.vwap.map(v => v.name).slice(0, 2).join(', ')}` : '';
      const name = em ? (k.kind === 'emup' ? 'haut attendu 24 h' : 'bas attendu 24 h') : k.label.toLowerCase() + (k.alsoAbs ? ' (plus fort gamma)' : '');
      const val = ['flip', 'maxpain'].includes(k.kind) || em ? '' : musd(k.gex);
      labels.push({y, bg: Panel.GEX_BG[k.kind] || Panel.GEX_BG.strike, fg: em ? '#e6e8ee' : '#0b0e11', text: `Γ ${name} ${fmt(k.price)}${val}${dist(k)}${conf}`});
    });
    ctx.setLineDash([]);
    // la légende du graphique (en haut à gauche) ne doit pas cacher une étiquette : celles qui tombent à sa hauteur passent à sa droite
    const lgEl = this.host && this.host.querySelector('.legend'), cv = ctx.canvas.getBoundingClientRect();
    const lg = lgEl && !lgEl.hidden && lgEl.offsetHeight ? lgEl.getBoundingClientRect() : null;
    const lgBox = lg ? {top: lg.top - cv.top - 10, bot: lg.bottom - cv.top + 10, right: lg.right - cv.left + 8} : null;
    LT.placeLabels(labels, 16, 12, bottom).forEach(it => {
      const x = lgBox && it.ly >= lgBox.top && it.ly <= lgBox.bot ? Math.max(barMax + 8, lgBox.right) : barMax + 8;
      this.tag(x, it.ly, it.text, it.fg, it.bg, true, true);
    });
    // deux lignes de lecture en bas à gauche : le régime et ce que feraient les teneurs de marché
    // sur un écran étroit, chaque ligne passe à la ligne entre deux « · » plutôt que d'être écrasée
    const x0 = Math.max(barMax + 4, 46), avail = Math.max(120, plotW - x0 - 12), rows = [];             // 46 : laisse le logo du graphique visible
    Panel.gexLines(g).forEach((txt, i) => {
      ctx.font = (i ? '500' : '600') + ' 11px sans-serif';
      let cur = '';
      txt.split(' · ').forEach(part => {
        const next = cur ? cur + ' · ' + part : part;
        if (cur && ctx.measureText(next).width > avail) { rows.push({t: cur, i}); cur = part; } else cur = next;
      });
      if (cur) rows.push({t: cur, i});
    });
    const tw = Math.max(...rows.map(r => { ctx.font = (r.i ? '500' : '600') + ' 11px sans-serif'; return ctx.measureText(r.t).width; })) + 14;
    const y0 = h - 34 - 15 * (rows.length - 1);
    ctx.fillStyle = 'rgba(11,14,17,.8)'; ctx.fillRect(x0, y0 - 10, tw, 15 * rows.length + 4);
    ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    rows.forEach((r, j) => {
      ctx.font = (r.i ? '500' : '600') + ' 11px sans-serif';
      ctx.fillStyle = r.i ? '#c9ccd6' : g.sign > 0 ? '#3ddc97' : g.sign < 0 ? '#ff8a8a' : '#e6e8ee';
      ctx.fillText(r.t, x0 + 7, y0 - 1 + 15 * j);
    });
    if (g.stale) this.tag(barMax + 8, 14, 'Γ gamma : données de plus de 30 minutes', '#fff', 'rgba(90,96,112,.85)', false, true);
    ctx.globalAlpha = 1;
  }
  static get GEX_COL() { return {callwall: '#e879f9', putwall: '#22d3ee', flip: '#facc15', strike: '#a78bfa', absgamma: '#f8fafc', maxpain: '#fb923c', emup: '#94a3b8', emdn: '#94a3b8'}; }
  static get GEX_BG() {
    return {callwall: 'rgba(232,121,249,.88)', putwall: 'rgba(34,211,238,.88)', flip: 'rgba(250,204,21,.9)', strike: 'rgba(167,139,250,.88)',
      absgamma: 'rgba(248,250,252,.9)', maxpain: 'rgba(251,146,60,.9)', emup: 'rgba(71,85,105,.85)', emdn: 'rgba(71,85,105,.85)'};
  }
  static gexLines(g) {
    // ligne 1 : régime au prix et position face à la bascule ; ligne 2 : couverture estimée à ±2 %, mouvement attendu, calcul utilisé
    const n = (v, d = 1) => LT.num(Math.abs(v), d), m = v => `${n(v / 1e6, 0)} M$`;
    const reg = g.sign > 0 ? 'gamma positif : marché plutôt amorti' : g.sign < 0 ? 'gamma négatif : marché plutôt amplifié' : 'gamma neutre';
    const fl = g.flip != null && g.flipDistPct != null ? ` · prix ${g.flipDistPct >= 0 ? 'au-dessus' : 'en dessous'} de la bascule (${g.flipDistPct >= 0 ? '+' : '−'}${n(g.flipDistPct)} %)` : '';
    const f2 = (g.flows || []).find(f => f.pct === 2), flow = v => `${v > 0 ? 'achat' : 'vente'} ${m(v)}`;
    const em = g.em && g.em.day ? ` · attendu 24 h ±${n(g.em.day.pct)} %` : '';
    const src = (g.sources || []).map(s => s.ex).join(' + ');
    const scope = {all: 'toutes échéances', week: '7 jours', front: 'prochaine échéance'}[g.scope] || '';
    return [`Γ ${reg} · ${g.total >= 0 ? '+' : '−'}${n(g.total / 1e6)} M$ par 1 %${fl}`,
      `${f2 ? `si +2 % : ${flow(f2.up)} · si −2 % : ${flow(f2.down)}` : ''}${em} · ${scope}, ${src}`];
  }
  drawPlan(L, h) {
    // V25.3 : les idées ENVOYÉES, à leurs niveaux figés, à partir de la bougie où elles sont parties (trait vertical et date) ; terminées
    // depuis moins de 48 h : estompées avec leur résultat. La configuration du moment (pas envoyée, recalculée sans cesse) n'est dessinée
    // que si tu la demandes, en gris, collée au bord droit.
    const st = LT.st, plans = (st.plans || []).filter(p => p.symbol === st.symbol);
    if (!plans.length) return;
    const ctx = this.ctx, plotW = this.kind === 'main' && this.rightLimit ? Math.max(200, this.rightLimit) : L.plotW, Y = v => this.series.priceToCoordinate(v);
    const fmt = LT.fmtP, sp = (v, e) => { const x = (v / e - 1) * 100; return (x > 0 ? '+' : '') + LT.num(x) + ' %'; };
    const STATUS = {pending: 'ordre en attente', active: 'en position', tp1: 'objectif 1 atteint'};
    const RES = {stop: 'stop touché', tp1_be: 'objectif 1 puis sortie à l\'entrée', tp2: 'objectif 2 atteint', missed: 'objectif atteint sans exécution',
      expired: 'expirée sans exécution', expired_active: 'suivi arrêté', switch: 'fermée', switch_cancel: 'annulée'};
    const labels = [];
    plans.forEach(p => {
      const ye = Y(p.entry), ys = Y(p.stop), y1 = Y(p.tp1), y2 = p.tp2 != null ? Y(p.tp2) : null;
      if (ye == null || ys == null || y1 == null) return;
      const live = p.kind === 'live', done = p.status === 'closed', buy = p.side === 'long';
      let x0, x1 = plotW;
      if (live) x0 = Math.max(40, plotW * 0.84);
      else {
        const xs = this.timeX(p.created / 1000, L);
        x0 = xs == null ? 0 : Math.max(0, Math.min(plotW - 24, xs));
        if (done && p.end) { const xe = this.timeX(p.end / 1000, L); if (xe != null) x1 = Math.max(x0 + 6, Math.min(plotW, xe)); }
      }
      if (x1 <= 0) return;                                            // terminée avant le début de la fenêtre affichée
      const fade = done ? 0.45 : 1, a = done || live ? 0.05 : 0.10;
      ctx.fillStyle = `rgba(255,107,107,${a})`; ctx.fillRect(x0, Math.min(ye, ys), x1 - x0, Math.abs(ys - ye));
      ctx.fillStyle = `rgba(61,220,151,${a})`; ctx.fillRect(x0, Math.min(ye, y1), x1 - x0, Math.abs(y1 - ye));
      ctx.globalAlpha = fade;
      [[ye, '#5ab0ff', [6, 4]], [ys, '#ff6b6b', [3, 3]], [y1, '#3ddc97', [3, 3]]].concat(y2 != null ? [[y2, '#3ddc97', [2, 5]]] : []).forEach(([y, col, dash]) => {
        ctx.strokeStyle = live ? '#aeb4c2' : col; ctx.lineWidth = live ? 1 : 1.3; ctx.setLineDash(live ? [2, 4] : dash);
        ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke();
      });
      ctx.setLineDash([]);
      if (!live && x0 > 0) {                                          // repère d'envoi : trait vertical à l'heure où l'idée est partie
        const top = Math.min(ye, ys, y1, y2 ?? ye) - 12, bot = Math.max(ye, ys, y1, y2 ?? ye) + 12, col = buy ? 'rgba(61,220,151,.95)' : 'rgba(255,107,107,.95)';
        ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.setLineDash([4, 3]);
        ctx.beginPath(); ctx.moveTo(x0, top); ctx.lineTo(x0, bot); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = col; ctx.beginPath();                          // triangle sur l'entrée, dans le sens de l'idée
        if (buy) { ctx.moveTo(x0, ye - 7); ctx.lineTo(x0 - 6, ye + 4); ctx.lineTo(x0 + 6, ye + 4); } else { ctx.moveTo(x0, ye + 7); ctx.lineTo(x0 - 6, ye - 4); ctx.lineTo(x0 + 6, ye - 4); }
        ctx.fill();
        ctx.font = '700 10px sans-serif';
        this.tag(x0 + 4, buy ? bot + 9 : top - 9, `${buy ? 'achat' : 'vente'} envoyé${buy ? '' : 'e'} ici · ${LT.parisAt(p.created)}`, '#fff', buy ? 'rgba(30,150,100,.9)' : 'rgba(200,60,60,.9)', true, true);
      }
      ctx.globalAlpha = 1;
      const who = buy ? 'ACHAT' : 'VENTE', when = live ? '' : LT.parisAt(p.created);
      const head = live ? `${who} DU MOMENT · pas envoyée, bouge` :
        done ? `${who} ${when} · terminée : ${RES[p.result] || p.result}` :
        `${who} ${when} · ${STATUS[p.status] || p.status}${p.sentOk ? '' : ' · Telegram non confirmé'}`;
      const c = col => live ? '#8a90a0' : col;
      labels.push({y: ye, col: c('#5ab0ff'), text: `${head} · entrée ${fmt(p.entry)}`, fade, live});
      if (!done) {
        labels.push({y: ys, col: c('#ff6b6b'), text: `Stop ${fmt(p.stop)} (${sp(p.stop, p.entry)})`, fade, live});
        labels.push({y: y1, col: c('#3ddc97'), text: `Objectif 1 ${fmt(p.tp1)} (${sp(p.tp1, p.entry)})`, fade, live});
        if (y2 != null) labels.push({y: y2, col: c('#3ddc97'), text: `Objectif 2 ${fmt(p.tp2)} (${sp(p.tp2, p.entry)})`, fade, live});
      }
    });
    LT.placeLabels(labels.map(it => ({...it})), 18, 12, h - 30).forEach(it => {
      ctx.font = '600 11px sans-serif';
      const tw = ctx.measureText(it.text).width + 14, x = Math.max(8, plotW - tw - 10);
      ctx.globalAlpha = it.fade;
      this.tag(x, it.ly, it.text, '#fff', it.live ? 'rgba(90,96,112,.88)' : it.col === '#5ab0ff' ? 'rgba(52,120,200,.85)' : it.col === '#ff6b6b' ? 'rgba(200,60,60,.85)' : 'rgba(30,150,100,.85)', true);
      ctx.globalAlpha = 1;
    });
  }
  drawMain(L, w, h) {
    const ctx = this.ctx, st = LT.st, {d, plotW} = L, byId = LT.byId, fmtP = LT.fmtP, pr = LT.pr;
    this.drawBookHeat(L, h);
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
      zl.push({y: (z.key != null ? (this.series.priceToCoordinate(z.key) ?? y + hh / 2) : y + hh / 2), z});
    });
    this.drawPools(L, h);
    this.drawGex(L, h);
    this.drawPlan(L, h);
    const lv = byId(d.levels);
    LT.placeLabels(zl, 17, 12, h - 30).forEach(it => {
      const z = it.z, ar = z.side === 'above' ? '▲' : z.side === 'below' ? '▼' : '◆', col = z.side === 'above' ? '#3ddc97' : z.side === 'below' ? '#ff6b6b' : '#ffb300';
      const reach = z.prob && z.side !== 'in' ? ' · ' + pr(z.prob.reach['24']) + ' en 24 h' : '';
      const txt = `${ar} ${fmtP(z.key != null ? z.key : z.mid)} · ${z.grade != null ? z.grade : z.score}/14${reach}`;
      ctx.font = '600 11px sans-serif';
      const tw = ctx.measureText(txt).width + 18;
      const zx = this.place(10, it.ly, tw, 18, (this.rightLimit || plotW) - 6);
      ctx.fillStyle = 'rgba(11,14,17,.9)'; ctx.fillRect(zx, it.ly - 9, tw, 18);
      ctx.fillStyle = col; ctx.fillRect(zx, it.ly - 9, 3, 18);
      ctx.fillStyle = '#e1e3ea'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(txt, zx + 9, it.ly + 0.5);
    });
    this.drawPricePools(L, h);                                              // apres les zones : celles-ci gardent la place, les plus hauts / bas se decalent
    const names = new Map();
    if (selZ) (byId(d.zones)[selZ]?.members || []).forEach(i => lv[i] && lv[i].kind !== 'liq' && names.set(i, lv[i]));
    if (st.sel && st.sel.type === 'level' && lv[st.sel.id]) names.set(st.sel.id, lv[st.sel.id]);
    const lab = [];
    names.forEach(l => { const y = this.series.priceToCoordinate(l.price); if (y != null) lab.push({y, l}); });
    LT.placeLabels(lab, 15, 12, h - 30).forEach(it => {
      const c = LT.levelColor(it.l);
      if (Math.abs(it.ly - it.y) > 2) { ctx.strokeStyle = 'rgba(180,184,196,.5)'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(0, it.y); ctx.lineTo(10, it.ly); ctx.stroke(); }
      ctx.font = '500 11px sans-serif';
      const txt = it.l.name + '  ' + fmtP(it.l.price), tw = ctx.measureText(txt).width + 22, xx = this.place(190, it.ly, tw, 16, (this.rightLimit || plotW) - 6);
      ctx.fillStyle = 'rgba(11,14,17,.88)'; ctx.fillRect(xx, it.ly - 8, tw, 16);
      ctx.fillStyle = c; ctx.fillRect(xx, it.ly - 8, 3, 16);
      ctx.fillStyle = '#d1d4dc'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(txt, xx + 9, it.ly + 0.5);
    });
    this.drawVwapTags(L, h);
    this.drawBig(L, h);
    this.drawAbsorb(L, h);
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
      if (s.exact != null) {                                   // V23 : precision du profil (chaque transaction ou bougies)
        const ex = s.exact, tag = ex >= 0.995 ? '◆ au prix près' : ex > 0.005 ? `◆ ${Math.round(ex * 100)} % au prix près` : 'profil estimé (bougies)';
        ctx.font = `500 9px ${t.font}`; ctx.textAlign = 'right'; ctx.textBaseline = 'top';
        ctx.fillStyle = ex >= 0.995 ? rgba(t.vpBuy, 0.9) : t.label;
        ctx.textAlign = 'left';
        ctx.fillText(tag, d.x - W, 16);                        // sous l'en-tete de la colonne (« jour · forme »)
      }
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
  // ---- V15 : gros ordres executes ; V21.1 : regroupes par bougie, cote et prix, et filtres par taille ; V24.1 : bulles sous les bougies ----
  static bigSteps(sym) {
    const b = (sym || '').replace(/USDT$/, '');
    return b === 'BTC' ? [250e3, 5e5, 1e6, 2e6, 5e6] : b === 'ETH' ? [1e5, 2.5e5, 5e5, 1e6, 2e6] : [5e4, 1e5, 2.5e5, 5e5, 1e6];
  }
  static bigMinUsd(st) { const s = Panel.bigSteps(st.symbol); return s[Math.max(0, Math.min(s.length - 1, st.mainOpts.bigMin ?? 2))]; }
  static esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])); }
  // tailles du menu « Gros ordres » adaptees a la paire affichee (mises a jour quand la paire change)
  syncBigSel() {
    const st = LT.st;
    this.host.querySelectorAll('[data-mosel=bigMin]').forEach(sel => {
      if (sel.dataset.sym === String(st.symbol)) return;
      sel.innerHTML = Panel.bigSteps(st.symbol).map((v, i) => `<option value="${i}">≥ ${LT.fmtUsdShort(v)} $</option>`).join('');
      sel.dataset.sym = String(st.symbol); sel.value = String(st.mainOpts.bigMin ?? 2);
    });
  }
  // somme des gros ordres d'une meme bougie, d'un meme cote, a moins de 0,05 % l'un de l'autre ; seuls les groupes >= minUsd restent
  static clusterBig(big, perMs, minUsd) {
    const m = new Map();
    (big || []).forEach(b => {
      const bt = Math.floor(b.t / perMs) * perMs, key = `${b.side}|${bt}|${Math.round(Math.log(b.price) / 0.0005)}`;
      let g = m.get(key);
      if (!g) { g = {side: b.side, bt, t: b.t, t1: b.t, usd: 0, qty: 0, n: 0, pv: 0, lo: b.price, hi: b.price}; m.set(key, g); }
      g.usd += b.usd; g.qty += b.qty; g.n += 1; g.pv += b.price * b.usd; g.t = Math.min(g.t, b.t); g.t1 = Math.max(g.t1, b.t);
      g.lo = Math.min(g.lo, b.price); g.hi = Math.max(g.hi, b.price);
    });
    return [...m.values()].map(g => ({...g, price: g.pv / g.usd})).filter(g => g.usd >= minUsd);
  }
  // ---- V24.1 : lisibilite du flux d'ordres. Couleurs propres au flux, jamais celles des bougies (le style « nuit » a des bougies
  // bleues et blanches) : vert = acheteurs agressifs / mur qui soutient, rouge = vendeurs agressifs / mur qui bloque. Une forme par
  // type : bulle = gros ordre agressif, trait horizontal avec pattes = absorption en direct (mur), triangle = absorption sur la bougie.
  // Bulles transparentes avec un lisere sombre (la bougie reste visible), fusionnees quand elles se chevauchent, chiffres seulement
  // pour les plus importants (reglage « chiffres »), le detail au survol. ----
  static FLOW = {buy: [0, 214, 125], sell: [255, 72, 110]};
  static LABELS = {top: 3, all: 1e9, none: 0};
  static bubbleR(usd, minUsd) { return Math.max(2.5, Math.min(10, 2.5 + 2 * Math.log2(Math.max(1, usd / minUsd)))); }
  // bulles a l'ecran : vendeurs un peu a gauche du centre de la bougie, acheteurs un peu a droite (comme une empreinte) ; celles d'une
  // meme bougie et d'un meme cote qui se chevauchent sont fusionnees (total, prix moyen, fourchette de prix)
  static mergeBubbles(pts, minUsd) {
    const cols = new Map(), out = [];
    pts.forEach(p => { const k = p.side + '|' + p.bt; if (!cols.has(k)) cols.set(k, []); cols.get(k).push(p); });
    cols.forEach(arr => {
      arr.sort((a, b) => a.y - b.y);
      let cur = null;
      arr.forEach(p => {
        if (cur && Math.abs(p.y - cur.y) < (p.r + cur.r) * 0.7) {
          const usd = cur.usd + p.usd;
          cur.y = (cur.y * cur.usd + p.y * p.usd) / usd; cur.price = (cur.price * cur.usd + p.price * p.usd) / usd;
          cur.qty += p.qty; cur.n += p.n; cur.t = Math.min(cur.t, p.t); cur.t1 = Math.max(cur.t1, p.t1);
          cur.lo = Math.min(cur.lo, p.lo); cur.hi = Math.max(cur.hi, p.hi); cur.usd = usd; cur.r = Panel.bubbleR(usd, minUsd); cur.merged = true;
        } else {
          if (cur) out.push(cur);
          cur = {...p};
        }
      });
      if (cur) out.push(cur);
    });
    return out;
  }
  // etiquette a cote d'une marque, sans recouvrir une autre etiquette (essaie au-dessus puis au-dessous) ; false si pas de place
  placeTag(text, x, y, right, col, t) {
    const ctx = this.ctx, boxes = this._tagBoxes || (this._tagBoxes = []);
    ctx.font = `600 10px ${t.font}`;
    const tw = ctx.measureText(text).width + 8, th = 14, x0 = right ? x : x - tw;
    for (const dy of [0, -th - 2, th + 2, -2 * th - 4, 2 * th + 4]) {
      const y0 = y - th / 2 + dy;
      if (y0 < 4 || boxes.some(b => x0 < b.x + b.w && x0 + tw > b.x && y0 < b.y + b.h && y0 + th > b.y)) continue;
      boxes.push({x: x0, y: y0, w: tw, h: th});
      if (dy) { ctx.strokeStyle = LT.rgba(col, 0.5); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(right ? x - 2 : x + 2, y); ctx.lineTo(right ? x0 : x0 + tw, y0 + th / 2); ctx.stroke(); }
      ctx.fillStyle = 'rgba(8,10,14,0.85)'; ctx.fillRect(x0, y0, tw, th);
      ctx.fillStyle = LT.rgba(col, 1); ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(text, x0 + 4, y0 + th / 2 + 0.5);
      return true;
    }
    return false;
  }
  drawBig(L, h) {
    const st = LT.st, f = st.flow, t = this.th(), ctx = this.ctx, rgba = LT.rgba;
    this.bigHits = []; this._tagBoxes = [];
    this.syncBigSel();
    if (!st.mainOpts.big || !f || f.symbol !== L.d.symbol || !f.big || !f.big.length) { if (this.under) this.under.set([]); return; }
    const esc = Panel.esc, unit = esc((L.d.symbol || '').replace(/USDT$/, ''));
    const minUsd = Panel.bigMinUsd(st), per = (LT.TF_SEC[st.tf] || 3600) * 1000, last = f.big[f.big.length - 1];
    const key = `${f.symbol}|${f.big.length}|${last.t}|${minUsd}|${per}`;
    if (this._bigKey !== key) { this._bigKey = key; this._bigGroups = Panel.clusterBig(f.big, per, minUsd); }
    const fmtT = ms => new Date(ms).toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit', second: '2-digit'});
    const xr = (this.rightLimit || L.plotW) - 2, half = Math.max(2, Math.min(7, L.barW * 0.5)), pts = [];
    this._bigGroups.forEach(g => {
      const xc = this.timeX(g.bt / 1000, L), y = this.series.priceToCoordinate(g.price);
      if (xc == null || y == null || xc < -12 || xc > xr || y < 4 || y > h - 28) return;
      pts.push({...g, x: xc + (g.side === 'buy' ? half : -half), y, r: Panel.bubbleR(g.usd, minUsd)});
    });
    const bubbles = Panel.mergeBubbles(pts, minUsd).sort((a, b) => a.usd - b.usd);       // les plus gros dessines en dernier, au-dessus
    const top = new Set(bubbles.slice(-3));                                                 // les 3 plus gros visibles : pleins ; les autres : discrets
    const under = [];
    bubbles.forEach(b => {
      const c = Panel.FLOW[b.side], main = top.has(b);
      if (this.under) under.push({time: b.bt / 1000, price: b.price, dx: b.side === 'buy' ? half : -half, r: b.r, c, fa: main ? 0.6 : 0.24, sa: main ? 1 : 0.85, lw: main ? 1.6 : 1});
      else {                                                                                  // sans couche du dessous (ancienne bibliotheque) : par-dessus, transparent
        ctx.beginPath(); ctx.arc(b.x, b.y, b.r, 0, Math.PI * 2);
        ctx.fillStyle = rgba(c, main ? 0.35 : 0.1); ctx.fill();
        ctx.lineWidth = 1.2; ctx.strokeStyle = rgba(c, 0.9); ctx.stroke();
      }
      const many = b.n > 1, who = b.side === 'buy' ? 'acheteur' : 'vendeur';
      this.bigHits.push({x: b.x, y: b.y, r: b.r + 3, html: `<b class="${b.side === 'buy' ? 'up' : 'dn'}">${many ? `${b.n} gros ordres ${who}s agressifs` : `Gros ordre ${who} agressif`}</b><br>` +
        `${LT.fmtUsdShort(b.usd)} $ au total, ${LT.fmtQty(b.qty)} ${unit}, prix moyen ${LT.fmtP(b.price)}` + (b.hi > b.lo ? ` (de ${LT.fmtP(b.lo)} à ${LT.fmtP(b.hi)})` : '') + '<br>' +
        `<span class="muted">${many ? `de ${fmtT(b.t)} à ${fmtT(b.t1)}` : fmtT(b.t)}${b.merged ? ' · réunis en une bulle car trop proches à l\'écran' : ''} · affichés à partir de ${LT.fmtUsdShort(minUsd)} $</span>`});
    });
    if (this.under) this.under.set(under);
    const nLab = Panel.LABELS[st.mainOpts.bigLabels || 'top'] ?? 3;
    bubbles.slice().reverse().slice(0, nLab).forEach(b => {
      const buy = b.side === 'buy';
      this.placeTag(LT.fmtUsdShort(b.usd), buy ? b.x + b.r + 4 : b.x - b.r - 4, b.y, buy, Panel.FLOW[b.side], t);
    });
  }
  // ---- V21 : absorptions. Sur les bougies : delta fort CONTRE le sens de la bougie (triangle vert sous la bougie = vendeurs absorbes,
  // rouge au-dessus = acheteurs absorbes ; plein = forte ou au plus bas / haut ; anneau orange = sur une zone de confluence).
  // En direct (ruban + carnet) : « mur » au prix ou le volume agressif a ete absorbe (V24.1, voir plus bas). Bulle au survol. ----
  drawAbsorb(L, h) {
    const st = LT.st, ctx = this.ctx, t = this.th(), rgba = LT.rgba, d = L.d, xr = (this.rightLimit || L.plotW) - 2;
    this.absHits = [];
    if (!st.mainOpts.absorb) return;
    const UP = [61, 220, 151], DN = [255, 107, 107], a = d.absorb || {}, sd = a.study, unit = (d.symbol || '').replace(/USDT$/, '');
    const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
    const pct = v => v == null ? '—' : Math.round(v * 100) + ' %', n1 = v => v == null ? '—' : v.toFixed(1).replace('.', ',');
    const VERD = {net: 'effet net et stable', contraire: 'effet contraire', instable: 'écart non confirmé', hasard: 'pas d\'écart démontré', insuffisant: 'trop peu de cas'};
    const measured = (side, strong) => {
      const s0 = sd && sd[side], s = strong && s0 && s0.strong && s0.strong.up != null ? s0.strong : s0;
      if (!s || s.up == null) return 'Pas encore mesuré sur ce marché (calcul en tâche de fond après le démarrage).';
      return `Mesuré sur ce marché (${s === s0 ? 'toutes les absorptions' : `absorptions fortes, ${s.n} cas`}, bougies de ${sd.unit}${a.simulated ? ', données simulées' : ''}) : ` +
        `dans les ${sd.primary} bougies suivantes, le prix ${side === 'bull' ? 'monte' : 'baisse'} ${pct(s.up)} du temps, contre ${pct(s.upCtl)} après une bougie semblable au flux ordinaire : ${VERD[s.verdict] || s.verdict}.`;
    };
    const sgn = v => (v > 0 ? '+' : '−') + LT.fmtQty(Math.abs(v));
    Panel.absMarks(ctx, this.series, ms => this.timeX(ms / 1000, L), Panel.absShown(a.events, st), xr, h, t, false).forEach(({e, x, y, s}) => {
      const bull = e.side === 'bull';
      const when = new Date(e.t).toLocaleString('fr-FR', {weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
      this.absHits.push({x, y, r: s + 5, html: `<b class="${bull ? 'up' : 'dn'}">Absorption ${bull ? 'acheteuse (vendeurs absorbés)' : 'vendeuse (acheteurs absorbés)'}</b><br>` +
        `<span class="muted">bougie du ${esc(when)}</span><br>Delta <b>${sgn(e.delta)} ${esc(unit)}</b> (${n1(Math.abs(e.z))} écarts-types) et pourtant la bougie finit en ${bull ? 'hausse' : 'baisse'} : ` +
        `${bull ? 'les vendeurs' : 'les acheteurs'} agressifs ont été absorbés par des ordres passifs vers ${LT.fmtP(e.price)}.<br>` +
        `Volume ×${n1(e.vr)} la normale${e.extreme ? ` · au plus ${bull ? 'bas' : 'haut'} des 12 dernières bougies` : ''}${e.zone ? ' · <b>sur une zone de confluence</b>' : ''}.<br>` +
        `${e.strong ? '<b>Absorption forte</b>. ' : ''}<span class="muted">${esc(measured(e.side, e.strong))}</span>`});
    });
    const f = st.flow;                                                  // en direct : ruban et carnet
    if (!f || f.symbol !== d.symbol || !f.absorb || !f.absorb.length) return;
    const live = Panel.absLiveShown(f.absorb, st);
    const thr = f.absorbThr || 1, ST = {'en cours': 'en cours', 'confirmée': 'confirmée : le prix s\'est éloigné dans son sens', 'cassée': 'cassée : le prix est passé au travers', 'tenue': 'tenue (5 minutes sans départ)'};
    const per = (LT.TF_SEC[st.tf] || 3600) * 1000, nLab = Math.min(2, Panel.LABELS[st.mainOpts.bigLabels || 'top'] ?? 3), tags = [];
    // V24.1 : absorption en direct = « mur » au prix (trait horizontal sur la largeur de la bougie, pattes vers le cote ou le prix est
    // retenu : vers le haut = soutien, vers le bas = plafond) ; pointille = en cours, double trait = ordre reapprovisionne, pale et barre = cassee
    live.forEach(e => {
      let x = this.timeX(LT.barStart(Math.floor(e.t / 1000), st.tf), L);
      const y = this.series.priceToCoordinate(e.price + e.step / 2);
      const bull = e.side === 'bull', col = bull ? UP : DN, broken = e.status === 'cassée';
      const w = Math.max(10, Math.min(24, L.barW + 4 + 3 * Math.log2(1 + e.usd / thr))), cap = bull ? -5 : 5;   // a peine plus large que la bougie
      if (x != null && x + w / 2 > xr && x <= L.plotW + 2) x = xr - w / 2 - 2;            // bougie en cours cachee par le carnet : mur epingle au bord
      if (x == null || y == null || x < -w || x > xr || y < 6 || y > h - 30) return;
      const x0 = x - w / 2, x1 = x + w / 2;
      const wall = (dy) => { ctx.beginPath(); ctx.moveTo(x0, y + cap + dy); ctx.lineTo(x0, y + dy); ctx.lineTo(x1, y + dy); ctx.lineTo(x1, y + cap + dy); ctx.stroke(); };
      ctx.lineJoin = 'miter'; ctx.lineCap = 'butt';
      ctx.strokeStyle = 'rgba(0,0,0,0.65)'; ctx.lineWidth = 5; wall(0);                       // lisere sombre
      ctx.strokeStyle = rgba(col, broken ? 0.35 : 1); ctx.lineWidth = 2.6;
      if (e.status === 'en cours') ctx.setLineDash([4, 3]);
      wall(0);
      if (e.refill) { ctx.lineWidth = 1.4; wall(bull ? 3.5 : -3.5); }                        // ordre cache qui se recharge : double mur
      ctx.setLineDash([]);
      if (broken) { ctx.lineWidth = 1.4; ctx.beginPath(); ctx.moveTo(x - 4, y + 4); ctx.lineTo(x + 4, y - 4); ctx.stroke(); }
      if (!broken && ((e.ratio || 0) >= 2 || e.refill || e.status === 'confirmée')) tags.push({e, x1, y, col});
      const when = new Date(e.t).toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit', second: '2-digit'});
      this.absHits.push({x, y: y + cap / 2, r: w / 2 + 2, ry: 9, html: `<b class="${bull ? 'up' : 'dn'}">Absorption en direct · ${bull ? 'vendeurs absorbés (mur qui soutient)' : 'acheteurs absorbés (mur qui bloque)'}</b><br>` +
        `<span class="muted">${esc(when)} · ${LT.fmtP(e.price)} – ${LT.fmtP(e.price + e.step)}</span><br>` +
        `${LT.fmtUsdShort(e.usd)} $ ${bull ? 'vendus' : 'achetés'} agressivement à ce prix en moins d'une minute (delta ${sgn(e.delta)} ${esc(unit)}), sans que le prix passe au travers.<br>` +
        `Statut : <b>${esc(ST[e.status] || e.status)}</b>${e.refill ? '<br><b>Ordre réapprovisionné</b> (double trait) : il s\'est exécuté au moins deux fois la taille encore affichée dans le carnet (ordre caché probable).' : ''}` +
        `<br><span class="muted">Non mesuré sur l'historique (il faudrait chaque transaction et le carnet).</span>`});
    });
    tags.sort((a, b) => b.e.usd - a.e.usd).slice(0, nLab).forEach(g => this.placeTag(LT.fmtUsdShort(g.e.usd), g.x1 + 4, g.y, true, g.col, t));
  }
  // V21.1 : ce qui est affiche selon le reglage (« fortes » par defaut, « toutes »)
  static absShown(events, st) {
    return (st.mainOpts.absorbMode || 'fortes') === 'toutes' ? (events || []) : (events || []).filter(e => e.strong && e.top);
  }
  static absLiveShown(events, st) {
    if ((st.mainOpts.absorbMode || 'fortes') === 'toutes') return events || [];
    const now = LT.serverNow();                                         // horloge du serveur (celle du PC peut avoir quelques minutes d'ecart)
    return (events || []).filter(e => ((e.ratio || 0) >= 1.5 || e.refill) && now - e.t <= 3 * 3600e3 &&
      !(e.status === 'cassée' && now - (e.end || e.t) > 120e3));
  }
  // V21 : triangles d'absorption sur les bougies (graphique principal et grille multi-unites). Renvoie leurs positions.
  static absMarks(ctx, series, xOf, events, xr, h, t, small) {
    const rgba = LT.rgba, out = [], UP = [61, 220, 151], DN = [255, 107, 107];
    (events || []).forEach(e => {
      const x = xOf(e.t), yp = series.priceToCoordinate(e.price);
      if (x == null || yp == null || x < 0 || x > xr) return;
      const bull = e.side === 'bull', col = bull ? UP : DN, s = (small ? 2 : 3) + e.grade, y = bull ? yp + 6 + s : yp - 6 - s;
      if (y < 6 || y > h - 30) return;
      ctx.beginPath();
      if (bull) { ctx.moveTo(x, y - s); ctx.lineTo(x + s, y + s * 0.85); ctx.lineTo(x - s, y + s * 0.85); }
      else { ctx.moveTo(x, y + s); ctx.lineTo(x + s, y - s * 0.85); ctx.lineTo(x - s, y - s * 0.85); }
      ctx.closePath();
      ctx.fillStyle = e.grade >= 2 ? rgba(col, 0.95) : 'rgba(12,12,12,0.75)'; ctx.fill();
      ctx.strokeStyle = rgba(col, 1); ctx.lineWidth = 1.2; ctx.stroke();
      if (e.zone) { ctx.strokeStyle = 'rgba(255,179,0,0.9)'; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.arc(x, y, s + 4, 0, Math.PI * 2); ctx.stroke(); }
      if (e.grade >= 2 && !small) {
        ctx.font = `600 9px ${t.font}`; ctx.fillStyle = rgba(col, 1); ctx.textAlign = 'center'; ctx.textBaseline = bull ? 'top' : 'bottom';
        ctx.fillText((e.delta > 0 ? '+' : '−') + LT.fmtQty(Math.abs(e.delta)), x, bull ? y + s + 3 : y - s - 3);
      }
      out.push({e, x, y, s});
    });
    return out;
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
    const absNow = st.mainOpts.absorb ? Panel.absLiveShown(f.absorb, st).filter(e => e.t >= LT.serverNow() - 600000 && e.status !== 'cassée') : [];
    rows.forEach(r => {
      const [lo, bid, ask, bn, an, buy, sell] = r, hi = lo + f.step;
      const yt = this.series.priceToCoordinate(hi), yb = this.series.priceToCoordinate(lo);
      if (yt == null || yb == null) return;
      const y = (yt + yb) / 2, rh = Math.abs(yb - yt);
      if (y < 30 || y > h - 30) return;
      const cur = px >= lo && px < hi;
      const ab = absNow.find(e => e.price < hi && e.price + e.step > lo);           // V21 : absorption en direct a ce prix
      if (bid > 0) { const w = bid / mxS * X.bidS[1]; ctx.fillStyle = rgba(t.vpBuy, 0.13); ctx.fillRect(X.bidS[0] + X.bidS[1] - w, yt + 1, w, Math.max(1, rh - 2)); }
      if (ask > 0) { const w = ask / mxS * X.askS[1]; ctx.fillStyle = rgba(t.vpSell, 0.09); ctx.fillRect(X.askS[0], yt + 1, w, Math.max(1, rh - 2)); }
      if (cur) { ctx.fillStyle = t.price; ctx.fillRect(X.px[0] + 2, yt + 1, X.px[1] - 4, Math.max(1, rh - 2)); }
      if (ab) {                                                                      // apres le prix courant : toujours visible
        const ac = ab.side === 'bull' ? [61, 220, 151] : [255, 107, 107];
        if (!cur) { ctx.fillStyle = rgba(ac, 0.2); ctx.fillRect(X.px[0] + 2, yt + 1, X.px[1] - 4, Math.max(1, rh - 2)); }
        ctx.fillStyle = rgba(ac, 0.95); ctx.fillRect(X.px[0] - 2, yt + 1, 4, Math.max(1, rh - 2));
        ctx.font = `700 8px ${t.font}`; ctx.textAlign = 'left'; ctx.fillText('A', X.px[0] + 4, y);
      }
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

  // ---- V28 : heatmap du carnet d'ordres (couche SOUS les bougies) : une colonne par tranche de temps, une ligne par tranche de prix ----
  drawBookHeat(L, h) {                                // V29 : carte des liquidations (dessous), puis heatmap du carnet
    const st = LT.st;
    if (st.mainOpts.liqmap) this.drawHeatImage(L, h, st.liqMap);
    if (st.mainOpts.heat) this.drawHeatImage(L, h, st.bookHeat);
  }
  drawHeatImage(L, h, H) {
    const hctx = this.hctx;
    if (!H || !H.img || H.symbol !== L.d.symbol) return;
    const x0 = this.timeX(H.t0 / 1000, L), x1 = this.timeX(H.t1 / 1000, L);
    const yt = this.series.priceToCoordinate(H.lo + H.rows * H.rowsz), yb = this.series.priceToCoordinate(H.lo);
    if (x0 == null || x1 == null || yt == null || yb == null || x1 <= x0) return;
    hctx.save();
    hctx.beginPath(); hctx.rect(0, 0, L.plotW, this.candleBottom(h)); hctx.clip();
    hctx.imageSmoothingEnabled = false;
    hctx.drawImage(H.img, x0, yt, x1 - x0, yb - yt);
    hctx.restore();
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
    const zs = LT.shownZones(d);
    for (const z of zs) {
      const a = this.series.priceToCoordinate(z.hi), b = this.series.priceToCoordinate(z.lo);
      if (a == null || b == null) continue;
      const mid = (a + b) / 2, half = Math.max(5, Math.abs(a - b) / 2 + 3);
      if (Math.abs(y - mid) <= half) return LT.select({type: 'zone', id: z.id});
    }
    let best = null, bd = 7;
    d.levels.forEach(l => {
      if (l.kind === 'liq') return;
      const visible = false;
      const yy = this.series.priceToCoordinate(l.price);
      if (visible && yy != null && Math.abs(yy - y) < bd) { bd = Math.abs(yy - y); best = l; }
    });
    LT.select(best ? {type: 'level', id: best.id} : null);
  }
  onMove(ev) {
    const st = LT.st, H = st.heat, tip = this.tipEl;
    if (this.kind === 'main') {                                         // V21 : bulle des absorptions
      const r = this.body.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
      const near = (this.absHits || []).concat(this.bigHits || []).filter(q => Math.abs(q.x - x) <= q.r && Math.abs(q.y - y) <= (q.ry || q.r));
      const hit = near.sort((a, b) => Math.hypot(a.x - x, a.y - y) - Math.hypot(b.x - x, b.y - y))[0];   // la marque la plus proche du pointeur
      const hh = !hit && typeof Desk !== 'undefined' ? Desk.heatTip(this, x, y) : null;                 // V28 : montant en attente sous le pointeur
      if (hh) { tip.innerHTML = hh; tip.hidden = false; tip.style.left = Math.max(4, Math.min(r.width - 300, x + 14)) + 'px'; tip.style.top = Math.max(4, Math.min(r.height - 80, y - 30)) + 'px'; return; }
      if (!hit) { tip.hidden = true; return; }
      tip.innerHTML = hit.html; tip.hidden = false;
      tip.style.left = Math.max(4, Math.min(r.width - 340, x + 14)) + 'px'; tip.style.top = Math.max(4, Math.min(r.height - 190, y - 40)) + 'px';
      return;
    }
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
