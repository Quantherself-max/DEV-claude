// V40 : onglet GEX, une page à part pour le gamma des options BTC (Deribit, Bybit, OKX). Au centre, le profil du gamma par strike (prix à
// la verticale ; vert à droite = gamma positif, rouge à gauche = négatif), comme les profils GEX des plateformes d'options, avec la courbe du
// gamma total (où serait le régime si le prix allait là), la bascule, les murs, le plus fort gamma, le max pain et le mouvement attendu.
// À droite : régime, niveaux avec leur distance et leurs confluences VWAP, flux de couverture, mouvement attendu et DVOL, comparaison des
// échéances (toutes, 7 jours, prochaine), échéances Deribit (intérêt ouvert, put / call, max pain), part de chaque bourse, lecture complète.
// Survol : le détail d'un strike. Molette : zoom sur les prix. Le même calcul que sur le graphique (engine/gamma.py) : hypothèse sur le sens
// des teneurs de marché, effet non mesuré sur le passé.
const GEXV = (() => {
  'use strict';
  let LT = null, root = null, on = false, timer = null, data = null, err = null, busy = false, hover = null, livePx = null;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const O = () => LT.st.gexView;
  const fmtP = v => v == null ? '—' : Math.round(v).toLocaleString('fr-FR').replace(/ | /g, ' ');
  const sgn = v => v > 0 ? '+' : v < 0 ? '−' : '';
  const musd = v => v == null ? '—' : sgn(v) + (Math.abs(v) >= 1e9 ? (Math.abs(v) / 1e9).toFixed(2).replace('.', ',') + ' Md$' : (Math.abs(v) / 1e6).toFixed(Math.abs(v) >= 1e8 ? 0 : 1).replace('.', ',') + ' M$');
  const pct = (v, d = 1) => v == null ? '—' : sgn(v) + Math.abs(v).toFixed(d).replace('.', ',') + ' %';
  const DAY = new Intl.DateTimeFormat('fr-FR', {timeZone: 'UTC', weekday: 'short', day: '2-digit', month: '2-digit'});
  const COL = {callwall: '#e879f9', putwall: '#22d3ee', flip: '#facc15', absgamma: '#f8fafc', maxpain: '#fb923c', emup: '#94a3b8', emdn: '#94a3b8', strike: '#a78bfa'};
  const NAME = {callwall: 'Mur de calls', putwall: 'Mur de puts', flip: 'Bascule du gamma', absgamma: 'Plus fort gamma', maxpain: 'Max pain',
    emup: 'Haut attendu 24 h', emdn: 'Bas attendu 24 h', strike: 'Strike chargé'};
  const ROLE = {callwall: 'résistance probable', putwall: 'support probable une fois touché', flip: 'change le régime', absgamma: 'aimant, pivot',
    maxpain: 'aimant faible avant l\'échéance', emup: '2 chances sur 3 de rester dessous', emdn: '2 chances sur 3 de rester dessus', strike: 'palier'};

  function init(lt, host) {
    LT = lt; root = host;
    const o = O();
    const sel = (k, opts, title) => `<label class="small" title="${esc(title)}"><select data-gx="${k}">${opts.map(([v, n]) => `<option value="${v}"${String(o[k]) === String(v) ? ' selected' : ''}>${esc(n)}</option>`).join('')}</select></label>`;
    root.innerHTML = `<div class="gexbar"><b class="gexttl">GEX · options BTC</b>` +
      sel('scope', [['all', 'toutes les échéances'], ['week', '7 prochains jours'], ['front', 'prochaine échéance']], 'Options prises en compte : toutes les échéances (niveaux de fond), 7 prochains jours, ou seulement la prochaine échéance (niveaux du jour)') +
      sel('src', [['all', 'toutes les bourses'], ['deribit', 'Deribit seul']], 'Deribit, Bybit et OKX ensemble, ou Deribit seul') +
      sel('range', [[5, '± 5 %'], [10, '± 10 %'], [15, '± 15 %'], [25, '± 25 %']], 'Fourchette de prix affichée autour du prix (molette sur le profil : zoom)') +
      sel('bars', [['net', 'barres nettes'], ['split', 'calls et puts']], 'Une barre nette par strike, ou les calls (à droite) et les puts (à gauche) séparés') +
      `<label class="small" title="La courbe du gamma total : le régime qu'on aurait si le prix allait à cette hauteur"><input type="checkbox" data-gx="curve"${o.curve ? ' checked' : ''}> courbe du total</label>` +
      `<span class="gexreg"></span><span class="spacer"></span><span class="gexmeta muted small"></span>` +
      `<a class="small" href="/docs/guide_gamma.pdf" target="_blank" rel="noopener">Comprendre chaque niveau (PDF) →</a></div>` +
      `<div class="gexmain"><div class="gexchart"><canvas></canvas><div class="gextip" hidden></div></div><div class="gexside"></div></div>`;
    root.addEventListener('change', e => {
      const t = e.target.closest('[data-gx]'); if (!t) return;
      const k = t.dataset.gx;
      O()[k] = t.type === 'checkbox' ? t.checked : k === 'range' ? +t.value : t.value;
      LT.savePrefs();
      if (k === 'scope' || k === 'src') load(true); else draw();
    });
    const cv = root.querySelector('canvas');
    cv.addEventListener('mousemove', e => { const r = cv.getBoundingClientRect(); hover = {x: e.clientX - r.left, y: e.clientY - r.top}; draw(); });
    cv.addEventListener('mouseleave', () => { hover = null; draw(); });
    cv.addEventListener('wheel', e => {
      e.preventDefault();
      const o2 = O(), steps = [3, 5, 7.5, 10, 15, 20, 25];
      let i = steps.findIndex(x => x >= o2.range); if (i < 0) i = steps.length - 1;
      i = Math.max(0, Math.min(steps.length - 1, i + (e.deltaY > 0 ? 1 : -1)));
      o2.range = steps[i]; const s2 = root.querySelector('[data-gx="range"]'); if (s2 && [...s2.options].some(x => +x.value === o2.range)) s2.value = o2.range;
      LT.savePrefs(); draw();
    }, {passive: false});
  }

  async function load(force) {
    if (!on || (busy && !force)) return;
    busy = true;
    try {
      const o = O(), r = await LT.api(`/api/gex?scope=${o.scope}&src=${o.src}`);
      if (r.ok) { data = r; err = null; livePx = null; } else { err = r.why || 'gamma indisponible'; if (!data) data = null; }
    } catch (e) { err = 'terminal injoignable'; } finally { busy = false; }
    render();
  }

  // ---------- profil (canevas) ----------
  function draw() {
    if (!on || !root) return;
    const cv = root.querySelector('canvas'), box = root.querySelector('.gexchart'), tip = root.querySelector('.gextip');
    const W = box.clientWidth, H = box.clientHeight, dpr = window.devicePixelRatio || 1;
    if (!W || !H) return;
    cv.width = W * dpr; cv.height = H * dpr; cv.style.width = W + 'px'; cv.style.height = H + 'px';
    const ctx = cv.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#0b0e11'; ctx.fillRect(0, 0, W, H);
    ctx.font = '11px ui-monospace, Menlo, monospace'; ctx.textBaseline = 'middle';
    if (!data) { ctx.fillStyle = '#8a90a0'; ctx.textAlign = 'center'; ctx.fillText(err || 'chargement du gamma…', W / 2, H / 2); tip.hidden = true; return; }
    const b = data.brief, o = O(), px = livePx || data.price || b.spot, split = o.bars === 'split';
    const lo = px * (1 - o.range / 100), hi = px * (1 + o.range / 100);
    const L = 66, R = W - 128, T = 14, B = H - 34, cx = (L + R) / 2;
    const Y = p => T + (hi - p) / (hi - lo) * (B - T);
    const st = (b.strikes || []).filter(x => x.strike >= lo && x.strike <= hi);
    const mx = Math.max(1, ...st.map(x => split ? Math.max(x.calls, -x.puts) : Math.abs(x.net)));
    const X = v => cx + v / mx * (R - cx) * 0.96;
    // zones (dans cette vue à part, en léger fond)
    (b.zones || []).forEach(z => {
      if (!z.sign || z.hi < lo || z.lo > hi) return;
      const a = Y(Math.min(hi, z.hi)), c = Y(Math.max(lo, z.lo));
      ctx.fillStyle = z.sign > 0 ? 'rgba(61,220,151,.045)' : 'rgba(255,107,107,.055)'; ctx.fillRect(L, a, R - L, c - a);
    });
    // mouvement attendu 24 h : bande grise
    const em = b.em && b.em.day;
    if (em) { ctx.fillStyle = 'rgba(148,163,184,.07)'; ctx.fillRect(L, Y(Math.min(hi, em.up)), R - L, Y(Math.max(lo, em.down)) - Y(Math.min(hi, em.up))); }
    // grille des prix
    const span = hi - lo, stepP = [50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000].find(s => span / s <= (B - T) / 26) || 20000;
    ctx.textAlign = 'right';
    for (let p = Math.ceil(lo / stepP) * stepP; p <= hi; p += stepP) {
      const y = Y(p); ctx.strokeStyle = 'rgba(120,130,150,.12)'; ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(R, y); ctx.stroke();
      ctx.fillStyle = '#7d8596'; ctx.fillText(fmtP(p), L - 8, y);
    }
    ctx.strokeStyle = 'rgba(160,170,190,.35)'; ctx.beginPath(); ctx.moveTo(cx, T); ctx.lineTo(cx, B); ctx.stroke();
    // barres par strike
    const gap = st.length > 1 ? Math.min(...st.slice(1).map((x, i) => Math.abs(Y(x.strike) - Y(st[i].strike)))) : 10;
    const th = Math.max(1.5, Math.min(12, gap * 0.72));
    let hv = null;
    st.forEach(x => {
      const y = Y(x.strike);
      if (hover && Math.abs(hover.y - y) <= Math.max(th, gap / 2)) hv = x;
      const parts = split ? [[x.calls, '#3ddc97'], [x.puts, '#ff6b6b']] : [[x.net, x.net >= 0 ? '#3ddc97' : '#ff6b6b']];
      parts.forEach(([v, c]) => {
        if (!v) return;
        const x0 = Math.min(cx, X(v)), w = Math.abs(X(v) - cx);
        ctx.fillStyle = c; ctx.globalAlpha = hv === x ? 1 : 0.82; ctx.fillRect(x0, y - th / 2, Math.max(1, w), th);
        ctx.shadowBlur = 0;
      });
      ctx.globalAlpha = 1;
    });
    // courbe du gamma total
    if (o.curve) {
      const cv2 = (b.curve || []).filter(([p]) => p >= lo && p <= hi);
      const cm = Math.max(1, ...cv2.map(([, v]) => Math.abs(v)));
      ctx.strokeStyle = '#4c8dff'; ctx.lineWidth = 1.6; ctx.beginPath();
      cv2.forEach(([p, v], i) => { const xx = cx + v / cm * (R - cx) * 0.9, yy = Y(p); if (i) ctx.lineTo(xx, yy); else ctx.moveTo(xx, yy); });
      ctx.stroke(); ctx.lineWidth = 1;
    }
    // niveaux : trait sur toute la largeur, étiquette à droite
    const labels = [];
    (b.levels || []).forEach(k => {
      if (k.price < lo || k.price > hi || k.kind === 'strike') return;
      const y = Y(k.price), c = COL[k.kind] || '#a78bfa';
      ctx.strokeStyle = c; ctx.setLineDash(k.kind === 'flip' ? [] : k.kind.startsWith('em') ? [3, 5] : k.kind === 'maxpain' ? [2, 3] : [8, 4]);
      ctx.lineWidth = k.kind === 'flip' ? 1.6 : 1.2; ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(R, y); ctx.stroke(); ctx.setLineDash([]); ctx.lineWidth = 1;
      labels.push({y, c, t: `${({callwall: 'mur calls', putwall: 'mur puts', flip: 'bascule', absgamma: 'plus fort Γ', maxpain: 'max pain', emup: 'haut 24 h', emdn: 'bas 24 h'})[k.kind] || k.kind} ${fmtP(k.price)}`, dark: !k.kind.startsWith('em')});
    });
    // prix
    const yp = Y(px);
    ctx.strokeStyle = '#ffffff'; ctx.setLineDash([4, 3]); ctx.beginPath(); ctx.moveTo(L, yp); ctx.lineTo(R, yp); ctx.stroke(); ctx.setLineDash([]);
    labels.push({y: yp, c: '#ffffff', t: `prix ${fmtP(px)}`, dark: true});
    LT.placeLabels(labels, 17, T + 8, B - 8).forEach(l => {
      ctx.font = '600 11px ui-monospace, Menlo, monospace'; const tw = ctx.measureText(l.t).width + 10;
      ctx.fillStyle = l.dark ? l.c : 'rgba(71,85,105,.9)'; ctx.fillRect(R + 6, l.ly - 8, Math.min(tw, W - R - 8), 16);
      ctx.fillStyle = l.dark ? '#0b0e11' : '#e6e8ee'; ctx.textAlign = 'left'; ctx.fillText(l.t, R + 11, l.ly + 0.5, W - R - 16);
      if (Math.abs(l.ly - l.y) > 2) { ctx.strokeStyle = l.c; ctx.beginPath(); ctx.moveTo(R, l.y); ctx.lineTo(R + 6, l.ly); ctx.stroke(); }
    });
    ctx.font = '11px ui-monospace, Menlo, monospace';
    // échelle du bas : millions de dollars par 1 %
    ctx.fillStyle = '#7d8596'; ctx.textAlign = 'center';
    [[-mx, L + 30], [0, cx], [mx, R - 30]].forEach(([v, x]) => ctx.fillText(v ? musd(v) : '0', x, H - 14));
    ctx.textAlign = 'left'; ctx.fillStyle = '#5f6778'; ctx.textAlign = 'center'; ctx.fillText(W < 560 ? '← négatif · dollars par 1 % · positif →' : '← gamma négatif · gamma de chaque strike, en dollars par 1 % de mouvement · gamma positif →', cx, H - 3);
    // survol : détail du strike
    if (hv && hover) {
      tip.hidden = false;
      tip.innerHTML = `<b>${fmtP(hv.strike)}</b> · ${pct((hv.strike / px - 1) * 100)}<br>calls ${musd(hv.calls)} · puts ${musd(hv.puts)}<br>net <b class="${hv.net >= 0 ? 'up' : 'dn'}">${musd(hv.net)}</b> par 1 %`;
      tip.style.left = Math.min(W - 190, hover.x + 14) + 'px'; tip.style.top = Math.max(4, hover.y - 30) + 'px';
    } else tip.hidden = true;
  }

  // ---------- panneau de droite ----------
  function render() {
    if (!on || !root) return;
    const side = root.querySelector('.gexside'), reg = root.querySelector('.gexreg'), meta = root.querySelector('.gexmeta');
    draw();
    if (!data) { side.innerHTML = `<div class="gexcard muted">${esc(err || 'chargement…')}</div>`; reg.innerHTML = ''; meta.textContent = ''; return; }
    const b = data.brief, px = livePx || data.price || b.spot;
    const age = b.t ? Math.round((LT.serverNow() - b.t) / 60000) : null;
    meta.textContent = `${age != null ? `options lues il y a ${age} min` : ''}${b.stale ? ' (anciennes)' : ''}${err ? ' · ' + err : ''}`;
    reg.innerHTML = `<span class="gexchip ${b.sign > 0 ? 'up' : b.sign < 0 ? 'dn' : ''}">${b.sign > 0 ? 'gamma positif' : b.sign < 0 ? 'gamma négatif' : 'gamma neutre'} ${musd(b.total)} par 1 %</span>`;
    const card = (t, body) => `<div class="gexcard"><div class="gexh">${t}</div>${body}</div>`;
    const flips = b.flipDistPct != null ? `Prix ${b.flipDistPct >= 0 ? 'au-dessus' : 'en dessous'} de la bascule (${pct(b.flipDistPct)}).` : 'Pas de bascule dans la fourchette.';
    const regime = card('Régime', `<div class="gexbig ${b.sign > 0 ? 'up' : b.sign < 0 ? 'dn' : ''}">${b.sign > 0 ? 'Marché plutôt amorti' : b.sign < 0 ? 'Marché plutôt amplifié' : 'Neutre'}</div>` +
      `<p class="small">${esc(flips)} ${b.sign > 0 ? 'Les teneurs de marché vendraient les hausses et achèteraient les baisses : on joue plutôt les bornes.' : b.sign < 0 ? 'Les teneurs de marché suivraient le mouvement : les cassures peuvent aller plus loin.' : ''}</p>`);
    const lv = (b.levels || []).filter(k => k.kind !== 'strike' || (k.vwap && k.vwap.length));
    const levels = card('Niveaux', `<table class="gextab"><tr><th></th><th>prix</th><th>écart</th><th>taille</th></tr>` + lv.map(k =>
      `<tr title="${esc(ROLE[k.kind] || '')}"><td><i class="gexdot" style="background:${COL[k.kind] || '#a78bfa'}"></i>${esc(NAME[k.kind] || k.label)}${k.alsoAbs ? ' <span class="muted">(plus fort Γ)</span>' : ''}` +
      `${k.vwap && k.vwap.length ? `<div class="muted small">≈ ${esc(k.vwap.map(v => v.name).join(', '))}</div>` : ''}</td>` +
      `<td>${fmtP(k.price)}</td><td class="${k.distPct >= 0 ? 'up' : 'dn'}">${pct(k.distPct)}</td><td>${k.gex != null && !['flip', 'maxpain', 'emup', 'emdn'].includes(k.kind) ? musd(k.gex) : ''}</td></tr>`).join('') + '</table>');
    const fl = b.flows || [];
    const flows = card('Ce que feraient les teneurs de marché', `<table class="gextab"><tr><th>si le prix…</th><th>monte</th><th>baisse</th></tr>` +
      fl.map(f => `<tr><td>de ${String(f.pct).replace('.', ',')} %</td><td class="${f.up > 0 ? 'up' : 'dn'}">${f.up > 0 ? 'achat' : 'vente'} ${musd(Math.abs(f.up)).replace(/^[+−]/, '')}</td>` +
        `<td class="${f.down > 0 ? 'up' : 'dn'}">${f.down > 0 ? 'achat' : 'vente'} ${musd(Math.abs(f.down)).replace(/^[+−]/, '')}</td></tr>`).join('') +
      `</table><p class="muted small">Vente dans la hausse et achat dans la baisse : ils freinent. Achat dans la hausse : ils accélèrent.</p>`);
    const em = b.em || {}, dv = data.dvol;
    const moves = card('Mouvement attendu (options)', `<table class="gextab">` +
      (em.day ? `<tr><td>24 heures</td><td>±${pct(em.day.pct).replace(/^[+−]/, '')}</td><td>${fmtP(em.day.down)} – ${fmtP(em.day.up)}</td></tr>` : '') +
      (em.week ? `<tr><td>7 jours</td><td>±${pct(em.week.pct).replace(/^[+−]/, '')}</td><td>${fmtP(em.week.down)} – ${fmtP(em.week.up)}</td></tr>` : '') + '</table>' +
      (dv ? `<p class="small">DVOL (volatilité implicite à 30 jours) <b>${dv.value.toFixed(1).replace('.', ',')}</b>${dv.chg24h != null ? ` · 24 h ${pct(dv.chg24h * 100)}` : ''}${dv.rank != null ? ` · plus haut que ${Math.round(dv.rank * 100)} % des 14 derniers jours` : ''}</p>` : '') +
      `<p class="muted small">Environ 2 chances sur 3 que le prix reste dans la fourchette.</p>`);
    const C = data.compare || {}, SC = [['all', 'toutes'], ['week', '7 jours'], ['front', 'prochaine']];
    const cmp = card('Selon les échéances prises en compte', `<table class="gextab"><tr><th></th>${SC.map(([k, n]) => `<th${k === b.scope ? ' class="on"' : ''}>${n}</th>`).join('')}</tr>` +
      [['régime', g => g ? `<span class="${g.total > 0 ? 'up' : 'dn'}">${musd(g.total)}</span>` : '—'], ['bascule', g => g ? fmtP(g.flip) : '—'], ['mur de calls', g => g ? fmtP(g.callWall) : '—'],
        ['mur de puts', g => g ? fmtP(g.putWall) : '—'], ['plus fort Γ', g => g ? fmtP(g.absGamma) : '—']]
        .map(([n, f]) => `<tr><td>${n}</td>${SC.map(([k]) => `<td${k === b.scope ? ' class="on"' : ''}>${f(C[k])}</td>`).join('')}</tr>`).join('') +
      `</table><p class="muted small">Les niveaux de la prochaine échéance sont plus proches du prix et réagissent plus vite ; ceux de toutes les échéances tiennent plusieurs jours.</p>`);
    const ex = data.expiries || [];
    const exps = card('Échéances Deribit', `<table class="gextab"><tr><th>date</th><th>dans</th><th>ouvert</th><th>put / call</th><th>max pain</th></tr>` +
      ex.map(e => `<tr><td>${esc(DAY.format(new Date(e.expiry)))}</td><td>${e.daysLeft < 1 ? Math.round(e.daysLeft * 24) + ' h' : Math.round(e.daysLeft) + ' j'}</td><td>${musd(e.oiUsd).replace(/^[+−]/, '')}</td>` +
        `<td>${e.putCall != null ? e.putCall.toFixed(2).replace('.', ',') : '—'}</td><td>${fmtP(e.maxPain)}</td></tr>`).join('') +
      `</table><p class="muted small">Échéances à 08:00 UTC. Put / call au-dessus de 1 : plus de puts (protections) que de calls.</p>`);
    const srcs = card('Bourses', (b.sources || []).map(s => `<div class="gexsrc"><span>${esc(s.ex)}</span><span class="gexsbar"><i style="width:${Math.round((s.share || 0) * 100)}%"></i></span><span>${Math.round((s.share || 0) * 100)} %</span></div>`).join('') +
      (b.othersError ? `<p class="dn small">${esc(b.othersError)}</p>` : '') + `<p class="muted small">Part de l'intérêt ouvert (en BTC) dans le calcul. Le CME et les options sur les ETF bitcoin ne sont pas lus.</p>`);
    const note = card('Lecture complète', `<p class="small">${esc(data.note)}</p><p class="muted small">Prix du BTC ${fmtP(px)}. Hypothèse habituelle sur le sens des teneurs de marché (acheteurs des calls, vendeurs des puts) ; effet non mesuré sur le passé : contexte, hors score des idées.</p>`);
    side.innerHTML = regime + levels + flows + moves + cmp + exps + srcs + note;
  }

  function show() {
    const was = on;
    on = true;
    render();
    if (!was) { load(true); clearInterval(timer); timer = setInterval(() => load(false), 20000); window.addEventListener('resize', draw); }
    setTimeout(draw, 120);
  }
  function hide() { on = false; clearInterval(timer); timer = null; window.removeEventListener('resize', draw); }
  let lastTick = 0;
  function onTick(price, sym) {                                       // prix en direct du BTC : seule la ligne du prix bouge entre deux chargements
    if (!on || sym !== 'BTCUSDT' || !(price > 0)) return;
    livePx = price;
    const now = Date.now();
    if (now - lastTick < 700) return;
    lastTick = now; draw();
  }
  return {init, show, hide, onTick, redraw: draw, active: () => on};
})();
