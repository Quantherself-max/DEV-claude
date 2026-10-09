// Vue TPO (V17) : profils de marche des dernieres seances d'1 jour (tranches de 30 min), de 4 heures et d'1 heure (tranches de 5 min).
// Chaque tranche a sa lettre (A, B, C...) posee sur les prix qu'elle a touches. Lecture : POC (ligne la plus longue), zone de valeur
// (barre a gauche de la colonne), single prints (rectangle gris : prix touches par une seule tranche ; prolonge vers la droite tant qu'il
// n'est pas comble), queues (lettres plus sombres aux extremites : rejet net), poor high / poor low (trait orange : enchere mal terminee,
// prolonge tant qu'il n'est pas depasse), premiere heure de la seance d'1 jour (barre verte). Rien de tout cela n'est mesure par le backtest.
const TPO = (() => {
  'use strict';
  const KINDS = [['D', '1 jour', '30 min'], ['4h', '4 heures', '5 min'], ['1h', '1 heure', '5 min']];
  let LT = null, root = null, on = false, timer = null, data = {}, raf = 0, hover = null;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const th = () => Panel.TH[LT.st.theme] || Panel.TH.nuit;
  const PARIS = new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', day: '2-digit', month: '2-digit'});
  const HOUR = new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', hour: '2-digit', minute: '2-digit'});

  function init(lt, host) {
    LT = lt; root = host;
    root.innerHTML = `<div class="tpobar"><span class="muted small">Séances TPO</span>${KINDS.map(([k, lab]) => `<label><input type="checkbox" data-tpo-k="${k}"> ${lab}</label>`).join('')}` +
      `<span class="muted small tpolegend">lettres = tranches de temps · <b>POC</b> clair · barre bleue = zone de valeur · <span class="tsp">▭</span> single prints (prolongées tant qu'elles ne sont pas comblées) · ` +
      `<span class="tpr">━</span> poor high / low · barre verte = première heure du jour · heures de Paris</span></div><div class="tpocols"></div>`;
    root.addEventListener('change', e => {
      const c = e.target.closest('[data-tpo-k]'); if (!c) return;
      LT.st.tpoKinds[c.dataset.tpoK] = c.checked; LT.savePrefs(); build(); load();
    });
  }
  function kinds() { return KINDS.filter(([k]) => LT.st.tpoKinds[k]); }
  function build() {
    const cols = root.querySelector('.tpocols'), ks = kinds();
    root.querySelectorAll('[data-tpo-k]').forEach(c => c.checked = !!LT.st.tpoKinds[c.dataset.tpoK]);
    cols.style.gridTemplateColumns = `repeat(${Math.max(1, ks.length)}, minmax(0, 1fr))`;
    cols.innerHTML = ks.length ? ks.map(([k, lab, br]) => `<section class="tpocol" data-k="${k}"><div class="mhead"><b>TPO ${lab}</b><span class="muted small">tranches de ${br}</span><span class="spacer"></span><span class="muted small" data-info></span></div>` +
      `<div class="mbody"><canvas></canvas><div class="tip" hidden></div></div></section>`).join('') : '<div class="muted" style="padding:20px">Coche au moins un type de séance.</div>';
    cols.querySelectorAll('.tpocol').forEach(sec => {
      const cv = sec.querySelector('canvas');
      cv.addEventListener('mousemove', ev => { const r = cv.getBoundingClientRect(); hover = {k: sec.dataset.k, x: ev.clientX - r.left, y: ev.clientY - r.top}; draw(sec.dataset.k); });
      cv.addEventListener('mouseleave', () => { hover = null; sec.querySelector('.tip').hidden = true; draw(sec.dataset.k); });
    });
  }
  async function load() {
    const sym = LT.st.symbol;
    if (!sym || !on) return;
    await Promise.all(kinds().map(async ([k]) => {
      const sec = root.querySelector(`.tpocol[data-k="${k}"]`); if (!sec) return;
      const rows = Math.max(12, Math.floor((sec.querySelector('.mbody').clientHeight - 40) / 12));
      try {
        const d = await LT.api(`/api/tpo?symbol=${sym}&kind=${k}&rows=${rows}`);
        if (sym === LT.st.symbol) { data[k] = d; draw(k); }
      } catch (e) { sec.querySelector('[data-info]').textContent = 'indisponible : ' + e.message; }
    }));
  }
  // dessin d'une colonne : les seances les plus recentes a droite, pres de l'echelle des prix
  function draw(k) {
    const sec = root && root.querySelector(`.tpocol[data-k="${k}"]`), d = data[k];
    if (!sec || !d || !d.ready) return;
    const cv = sec.querySelector('canvas'), body = sec.querySelector('.mbody'), dpr = window.devicePixelRatio || 1;
    const w = body.clientWidth, h = body.clientHeight, t = th(), rgba = LT.rgba, fmtP = LT.fmtP;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); cv.style.width = w + 'px'; cv.style.height = h + 'px'; }
    const ctx = cv.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = t.bg === 'rgba(0,0,0,0)' ? '#0b0e11' : t.bg; ctx.fillRect(0, 0, w, h);
    const ss = d.sessions || [], step = d.step;
    if (!ss.length || !step) return;
    const axisW = 64, top = 8, bottom = 24, plotW = w - axisW;
    // largeur des colonnes : lettres (7 px) si au moins 2 seances tiennent, sinon blocs (4 ou 3 px)
    const maxC = s => Math.max(...s.rows.map(r => r[1]));
    let cw = 7, fit = [];
    for (const [c, need] of [[7, 2], [4, 3], [3, 1]]) {
      cw = c; fit = []; let used = 0;
      for (let i = ss.length - 1; i >= 0; i--) { const wd = maxC(ss[i]) * c + 14; if (used + wd > plotW - 4) break; used += wd; fit.unshift(ss[i]); }
      if (fit.length >= Math.min(need, ss.length)) break;
    }
    if (!fit.length) return;
    let lo = Math.min(...fit.map(s => s.low)), hi = Math.max(...fit.map(s => s.high));
    if (d.price) { lo = Math.min(lo, d.price); hi = Math.max(hi, d.price); }
    lo -= step; hi += step;
    const Y = p => top + (hi - p) / (hi - lo) * (h - top - bottom), rowH = Math.max(1, Y(0) - Y(step));
    // echelle des prix
    ctx.font = `500 10px ${t.font}`; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillStyle = t.text;
    const every = Math.max(1, Math.ceil(36 / rowH));
    for (let p = Math.ceil(lo / step) * step, i = 0; p <= hi; p += step, i++) {
      if (Math.round(p / step) % every) continue;
      ctx.fillText(fmtP(p), plotW + 6, Y(p));
      ctx.fillStyle = t.grid; ctx.fillRect(0, Math.round(Y(p)), plotW, 1); ctx.fillStyle = t.text;
    }
    // colonnes
    let x = plotW - 4;
    const placed = [];
    for (let i = fit.length - 1; i >= 0; i--) {
      const s = fit[i], wd = maxC(s) * cw + 14, x0 = x - wd;
      placed.unshift({s, x0, wd});
      x = x0;
    }
    placed.forEach(({s, x0, wd}) => {
      const m = s.marks || {}, ext = !s.marks || m.current ? x0 + wd : plotW;      // marques encore ouvertes : prolongees jusqu'a l'echelle
      // single prints : rectangle gris (prolonge si non comble)
      s.singles.forEach(([a, b], j) => {
        const open = m.singles && m.singles[j] && !m.singles[j][2];
        const yt = Y(b), yb = Y(a);
        ctx.fillStyle = open ? t.spFill : 'rgba(150,150,150,0.06)'; ctx.fillRect(x0, yt, (open ? plotW : x0 + wd) - x0, yb - yt);
        ctx.strokeStyle = open ? t.spLine : 'rgba(150,150,150,0.15)'; ctx.lineWidth = 1; ctx.strokeRect(Math.round(x0) + 0.5, Math.round(yt) + 0.5, (open ? plotW : x0 + wd) - x0 - 1, Math.max(1, yb - yt - 1));
      });
      // zone de valeur et premiere heure
      ctx.fillStyle = 'rgba(120,173,247,0.6)'; ctx.fillRect(x0 + 1, Y(s.vah), 2, Y(s.val) - Y(s.vah));
      if (s.ib) { ctx.fillStyle = 'rgba(61,220,151,0.6)'; ctx.fillRect(x0 + 4, Y(s.ib[1]), 2, Y(s.ib[0]) - Y(s.ib[1])); }
      // lettres (ou blocs)
      const tailHi = s.tailHigh, tailLo = s.tailLow, n = s.brackets || 1;
      ctx.font = `600 ${Math.min(11, Math.max(8, rowH - 1))}px ${t.font}`; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      s.rows.forEach(([p, cnt, lets]) => {
        const y = Y(p + step / 2), poc = s.poc >= p && s.poc < p + step;
        const tail = (tailHi && p >= tailHi[0] - 1e-9) || (tailLo && p + step <= tailLo[1] + 1e-9);
        if (poc) { ctx.fillStyle = 'rgba(236,236,236,0.12)'; ctx.fillRect(x0, Y(p + step), wd - 6, rowH); }
        for (let q = 0; q < lets.length; q++) {
          const idx = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'.indexOf(lets[q]), f = n > 1 ? idx / (n - 1) : 1;
          const col = poc ? rgba(t.vpPoc, 1) : tail ? rgba(t.vpGrey, 0.9) : `rgba(${Math.round(150 + 90 * f)},${Math.round(160 + 50 * f)},${Math.round(175 + 72 * f)},0.95)`;
          ctx.fillStyle = col;
          if (cw >= 7 && rowH >= 8) ctx.fillText(lets[q], x0 + 8 + q * cw, y + 0.5);
          else ctx.fillRect(x0 + 8 + q * cw, Y(p + step) + 1, Math.max(1, cw - 1), Math.max(1, rowH - 2));
        }
      });
      // poor high / poor low
      [['poorHigh', 'high', s.high], ['poorLow', 'low', s.low]].forEach(([key, lab, px]) => {
        if (!s[key]) return;
        const active = !m[key] || m[key].active, y = Math.round(Y(px)) + 0.5;
        ctx.strokeStyle = t.poor; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(x0 + 6, y); ctx.lineTo(x0 + wd - 6, y); ctx.stroke();
        if (active && ext > x0 + wd) { ctx.setLineDash([4, 4]); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x0 + wd - 6, y); ctx.lineTo(ext, y); ctx.stroke(); ctx.setLineDash([]); }
        ctx.font = `500 9px ${t.font}`; ctx.fillStyle = t.poor; ctx.textAlign = 'left'; ctx.textBaseline = lab === 'high' ? 'bottom' : 'top';
        ctx.fillText('poor ' + lab, x0 + 8, lab === 'high' ? y - 2 : y + 2);
      });
      // date / heure de la seance
      ctx.font = `500 9.5px ${t.font}`; ctx.fillStyle = m.current ? rgba(t.vpBuy, 1) : t.label; ctx.textAlign = 'left'; ctx.textBaseline = 'bottom';
      const when = new Date(s.start);
      ctx.fillText((k === 'D' ? PARIS.format(when) : HOUR.format(when)) + (m.current ? ' · en cours' : ''), x0 + 6, h - 6);
    });
    // prix actuel
    if (d.price) {
      const y = Math.round(Y(d.price)) + 0.5;
      ctx.strokeStyle = t.price; ctx.lineWidth = 1; ctx.setLineDash([2, 3]); ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(plotW, y); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = t.price; ctx.fillRect(plotW + 2, y - 9, axisW - 4, 18);
      ctx.fillStyle = t.priceText; ctx.font = `600 10px ${t.font}`; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(fmtP(d.price), plotW + 6, y);
    }
    sec.querySelector('[data-info]').textContent = `${fit.length} séances · une ligne = ${fmtP(step)} $`;
    // bulle au survol : prix, nombre de lettres et lettres de la ligne
    const tip = sec.querySelector('.tip');
    if (hover && hover.k === k) {
      const p = hi - (hover.y - top) / (h - top - bottom) * (hi - lo), sx = placed.find(c => hover.x >= c.x0 && hover.x < c.x0 + c.wd);
      if (sx) {
        const r = sx.s.rows.find(r => p >= r[0] && p < r[0] + step), when = new Date(sx.s.start);
        tip.innerHTML = `<b>${esc(k === 'D' ? PARIS.format(when) : HOUR.format(when))}</b> · ${fmtP(Math.floor(p / step) * step)} – ${fmtP(Math.floor(p / step) * step + step)}<br>` +
          (r ? `${r[1]} tranche${r[1] > 1 ? 's' : ''} : ${esc(r[2])}` : 'aucune tranche à ce prix') +
          `<br><span class="muted">POC ${fmtP(sx.s.poc)} · zone de valeur ${fmtP(sx.s.val)} – ${fmtP(sx.s.vah)}</span>`;
        tip.style.left = Math.min(w - 230, hover.x + 12) + 'px'; tip.style.top = Math.max(4, hover.y - 10) + 'px'; tip.hidden = false;
      } else tip.hidden = true;
    }
  }
  function drawAll() { kinds().forEach(([k]) => draw(k)); }
  function show() {
    const was = on;
    on = true;
    build(); drawAll();
    if (!was) { load(); clearInterval(timer); timer = setInterval(load, 20000); }
    setTimeout(drawAll, 120);                                         // apres le changement de mise en page (panneau lateral...)
    window.addEventListener('resize', drawAll);
  }
  function hide() { on = false; clearInterval(timer); timer = null; window.removeEventListener('resize', drawAll); }
  function refresh() { data = {}; if (on) { build(); load(); } }
  // prix en direct : seule la ligne du prix bouge entre deux chargements (redessin au plus toutes les 0,5 s)
  let lastTick = 0;
  function onTick(price) {
    if (!on || !(price > 0)) return;
    Object.values(data).forEach(d => { d.price = price; });
    const now = Date.now();
    if (now - lastTick < 500 || raf) return;
    lastTick = now; raf = requestAnimationFrame(() => { raf = 0; drawAll(); });
  }
  return {init, show, hide, refresh, onTick, redraw: drawAll, active: () => on};
})();
