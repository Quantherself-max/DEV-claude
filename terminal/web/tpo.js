// Vue TPO (V17, refaite en V19) : profils de marché des séances d'1 jour (tranches de 30 min), de 4 heures et d'1 heure (tranches de 5 min).
// Chaque tranche a sa lettre (A, B, C...) posée sur les prix qu'elle a touchés. Sur chaque séance : zone de valeur (fond bleuté), POC (ligne
// surlignée), première heure (barre verte et objectifs d'extension), ouverture (▶) et clôture (◀), volume et delta à chaque prix (barres fines),
// single prints (rectangle gris), poor high / low (trait orange), queues (lettres sombres), POC vierges (pointillés prolongés). À droite :
// profil composite des dernières séances et ses zones fortes (HVN) et faibles (LVN). Molette : zoom ; glisser : déplacer ; Maj + molette ou
// glisser horizontalement : séances plus anciennes ; double-clic : recadrer. Les taux affichés viennent de la mesure sur l'historique.
const TPO = (() => {
  'use strict';
  const KINDS = [['D', '1 jour', '30 min'], ['4h', '4 heures', '5 min'], ['1h', '1 heure', '5 min']];
  const N = {D: 30, '4h': 42, '1h': 48};
  const LET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
  let LT = null, root = null, on = false, timer = null, raf = 0, lastTick = 0;
  const pending = new Set();
  const data = {}, view = {};
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const th = () => Panel.TH[LT.st.theme] || Panel.TH.nuit;
  const pct = (v, d = 0) => v == null ? '—' : (v * 100).toFixed(d).replace('.', ',') + ' %';
  const num = (v, d = 1) => v == null ? '—' : v.toFixed(d).replace('.', ',').replace('-', '−');
  const PARIS = new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', weekday: 'short', day: '2-digit', month: '2-digit'});
  const HOUR = new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', hour: '2-digit', minute: '2-digit'});
  const when = (k, t) => k === 'D' ? PARIS.format(new Date(t)) : HOUR.format(new Date(t));
  const opts = () => LT.st.tpoOpts;
  const V = k => (view[k] = view[k] || {zoom: 1, center: null, offset: 0, hover: null, drag: null});
  const SHAPE_SHORT = {P: 'P', b: 'b', D: 'D', I: 'I', B: 'B'};
  const VERD = {net: ['ok', 'mesuré'], contraire: ['warn', 'effet contraire'], instable: ['warn', 'instable'], faible: ['warn', 'faible'], description: ['', 'fréquence'], hasard: ['', '≈ hasard'], insuffisant: ['', '—']};

  function init(lt, host) {
    LT = lt; root = host;
    const o = opts();
    root.innerHTML = `<div class="tpobar"><span class="muted small">Séances</span>${KINDS.map(([k, lab]) => `<label><input type="checkbox" data-tpo-k="${k}"> ${lab}</label>`).join('')}` +
      `<span class="tpsep"></span><label class="small">Affichage <select data-tpo-o="mode"><option value="auto">automatique</option><option value="letters">lettres</option><option value="blocks">blocs</option></select></label>` +
      `<label class="small" title="Lignes plus fines : plus de détails, mais les taux mesurés correspondent aux lignes normales"><input type="checkbox" data-tpo-o="fine"> lignes fines</label>` +
      `<label class="small" title="Volume échangé à chaque prix (bleu : acheteurs agressifs dominants, blanc : vendeurs)"><input type="checkbox" data-tpo-o="vol"> volume</label>` +
      `<label class="small" title="Profil composite des dernières séances terminées, avec ses zones fortes (HVN) et faibles (LVN)"><input type="checkbox" data-tpo-o="comp"> composite</label>` +
      `<label class="small" title="POC jamais retraversés depuis leur séance, prolongés jusqu'à l'échelle des prix"><input type="checkbox" data-tpo-o="naked"> POC vierges</label>` +
      `<label class="small" title="Première heure (initial balance) et ses objectifs d'extension x1,5 et x2"><input type="checkbox" data-tpo-o="ib"> première heure</label>` +
      `<span class="spacer"></span><span class="muted small">molette : zoom · glisser : déplacer · Maj + molette : séances plus anciennes · double-clic : recadrer</span></div>` +
      `<div class="tpocols"></div><details class="tpostudy"><summary>Ce que dit l'historique sur ces repères</summary><div class="tpostudybody muted small">Chargement…</div></details>`;
    window.addEventListener('mouseup', () => Object.values(view).forEach(v => { v.drag = null; }));
    root.querySelectorAll('[data-tpo-o]').forEach(el => {
      const key = el.dataset.tpoO;
      if (el.type === 'checkbox') el.checked = !!o[key]; else el.value = o[key];
    });
    root.addEventListener('change', e => {
      const c = e.target.closest('[data-tpo-k]');
      if (c) { LT.st.tpoKinds[c.dataset.tpoK] = c.checked; LT.savePrefs(); build(); load(); return; }
      const t = e.target.closest('[data-tpo-o]');
      if (!t) return;
      const key = t.dataset.tpoO;
      opts()[key] = t.type === 'checkbox' ? t.checked : t.value;
      LT.savePrefs();
      if (key === 'fine') { Object.keys(data).forEach(k => delete data[k]); load(); } else drawAll();
    });
  }
  function kinds() { return KINDS.filter(([k]) => LT.st.tpoKinds[k]); }
  function build() {
    const cols = root.querySelector('.tpocols'), ks = kinds();
    root.querySelectorAll('[data-tpo-k]').forEach(c => c.checked = !!LT.st.tpoKinds[c.dataset.tpoK]);
    cols.style.gridTemplateColumns = `repeat(${Math.max(1, ks.length)}, minmax(0, 1fr))`;
    cols.innerHTML = ks.length ? ks.map(([k, lab, br]) => `<section class="tpocol" data-k="${k}"><div class="mhead"><b>TPO ${lab}</b><span class="muted small">tranches de ${br}</span>` +
      `<span class="spacer"></span><span class="muted small" data-info></span></div><div class="tpoctx" data-ctx></div>` +
      `<div class="mbody"><canvas></canvas><div class="tip" hidden></div><div class="tpomsg" hidden></div></div><div class="tpofoot muted small" data-foot></div></section>`).join('') :
      '<div class="muted" style="padding:20px">Coche au moins un type de séance.</div>';
    cols.querySelectorAll('.tpocol').forEach(sec => bind(sec));
  }
  // ---------- interactions ----------
  function bind(sec) {
    const k = sec.dataset.k, cv = sec.querySelector('canvas');
    const pos = ev => { const r = cv.getBoundingClientRect(); return {x: ev.clientX - r.left, y: ev.clientY - r.top}; };
    cv.addEventListener('mousemove', ev => {
      const v = V(k), p = pos(ev);
      if (v.drag) {
        const g = v.geo;
        if (g) {
          v.center = v.drag.center + (p.y - v.drag.y) / g.plotH * g.span;
          const sw = Math.max(30, g.avgW || 80), steps = Math.round((p.x - v.drag.x) / sw);
          v.offset = Math.max(0, Math.min(maxOffset(k), v.drag.offset + steps));
        }
      }
      v.hover = p;
      schedule(k);
    });
    cv.addEventListener('mouseleave', () => { const v = V(k); v.hover = null; v.drag = null; sec.querySelector('.tip').hidden = true; schedule(k); });
    cv.addEventListener('mousedown', ev => { const v = V(k), p = pos(ev); v.drag = {x: p.x, y: p.y, center: v.center ?? (v.geo ? v.geo.center : null), offset: v.offset}; });
    cv.addEventListener('dblclick', () => { Object.assign(V(k), {zoom: 1, center: null, offset: 0}); schedule(k); });
    cv.addEventListener('wheel', ev => {
      ev.preventDefault();
      const v = V(k), g = v.geo;
      if (!g) return;
      if (ev.shiftKey || Math.abs(ev.deltaX) > Math.abs(ev.deltaY)) {
        const d = (ev.shiftKey ? ev.deltaY : ev.deltaX) > 0 ? 1 : -1;
        v.offset = Math.max(0, Math.min(maxOffset(k), v.offset + d));
      } else {
        const p = pos(ev), price = g.priceAt(p.y), f = ev.deltaY < 0 ? 1.18 : 1 / 1.18;
        v.zoom = Math.max(1, Math.min(14, v.zoom * f));
        const span = g.fullSpan / v.zoom, frac = (p.y - g.top) / g.plotH;
        v.center = price + (frac - 0.5) * span;                     // le prix sous la souris reste sous la souris
      }
      schedule(k);
    }, {passive: false});
  }
  const maxOffset = k => Math.max(0, ((data[k] && data[k].sessions) || []).length - 1);
  function schedule(k) {
    kinds().forEach(([kk]) => { if (!k || kk === k) pending.add(kk); });
    if (raf) return;
    raf = requestAnimationFrame(() => { raf = 0; const ks = [...pending]; pending.clear(); ks.forEach(draw); });
  }
  // ---------- donnees ----------
  function message(html) {
    root.querySelectorAll('.tpocol').forEach(sec => { const m = sec.querySelector('.tpomsg'); m.innerHTML = html || ''; m.hidden = !html; });
  }
  async function load() {
    const sym = LT.st.symbol;
    if (!sym || !on) return;
    if (LT.serverOld()) {                                             // nouvelles pages, ancien programme : /api/tpo n'existe pas encore
      message(`<b>Le programme du terminal qui tourne est une ancienne version</b> : il ne sait pas encore calculer le TPO.<br>` +
        `Ferme la fenêtre noire « Liq Terminal » (ou Ctrl+C dedans), puis relance <b>${esc(LT.LAUNCHER)}</b>.`);
      return;
    }
    message('');
    const fine = opts().fine, rowsOf = {D: 120, '4h': 72, '1h': 40};
    await Promise.all(kinds().map(async ([k]) => {
      const sec = root.querySelector(`.tpocol[data-k="${k}"]`); if (!sec) return;
      try {
        const d = await LT.api(`/api/tpo?symbol=${sym}&kind=${k}&n=${N[k]}${fine ? '&rows=' + rowsOf[k] : ''}`);
        if (sym === LT.st.symbol) { data[k] = d; V(k).offset = Math.min(V(k).offset, maxOffset(k)); draw(k); renderCtx(k); renderStudy(); }
      } catch (e) {
        sec.querySelector('[data-info]').textContent = 'indisponible : ' + e.message;
        const m = sec.querySelector('.tpomsg');
        m.innerHTML = /^HTTP 404$/.test(e.message) ? `Le programme du terminal ne connaît pas encore le TPO : ferme la fenêtre noire « Liq Terminal » puis relance <b>${esc(LT.LAUNCHER)}</b>.`
          : `TPO indisponible pour le moment : ${esc(e.message)}`;
        m.hidden = false;
      }
    }));
  }
  // ---------- contexte de la seance en cours et chiffres mesures (HTML) ----------
  function renderCtx(k) {
    const sec = root.querySelector(`.tpocol[data-k="${k}"]`), d = data[k];
    if (!sec || !d || !d.sessions || !d.sessions.length) return;
    const s = d.sessions[d.sessions.length - 1], c = s.ctx || {}, st = d.study, chips = [];
    const chip = (txt, title, cls = '') => chips.push(`<span class="tpochip ${cls}" title="${esc(title)}">${esc(txt)}</span>`);
    if (c.dayType) {
      const f = st && st.dayTypes ? Object.entries(st.dayTypes).filter(([g]) => g.split('_')[0] === c.dayType.code).reduce((a, [, v]) => a + v, 0) : null;
      chip(c.dayType.label + (c.dayType.provisional ? ' (en cours)' : ''), c.dayType.text + (f ? ` Fréquence sur l'historique : ${pct(f)} des séances.` : ''), 'type');
    }
    if (s.shape) chip('forme ' + SHAPE_SHORT[s.shape], s.shapeText || '');
    if (c.va) chip({higher: 'valeur ↑', lower: 'valeur ↓', inside: 'valeur intérieure', outside: 'valeur extérieure', overlapHigher: 'valeur ↗', overlapLower: 'valeur ↘'}[c.va.code] || c.va.code, c.va.text);
    const e8 = c.eighty, rate8 = st && st.eighty ? ` Mesuré sur l'historique : objectif atteint ${pct(st.eighty.rate)} du temps (${st.eighty.n} cas), pas 80 %.` : '';
    if (c.open) {
      const og = st && st.openSame && st.openSame.groups ? st.openSame.groups[c.open.code] : null;
      chip({aboveRange: 'ouverture hors fourchette ↑', belowRange: 'ouverture hors fourchette ↓', aboveValue: 'ouverture au-dessus de la valeur', belowValue: 'ouverture sous la valeur', inValue: 'ouverture dans la valeur'}[c.open.code] || c.open.code,
        c.open.text + (og ? ` Mesuré : ces séances finissent en hausse ${pct(og.up)} du temps (moyenne ${pct(st.openSame.base)}), amplitude ×${num(og.rangeX, 2)}.` : '') +
        (k === 'D' && e8 && !e8.trigger ? ` Si deux tranches de 30 min clôturent dans la valeur précédente, la « règle des 80 % » visera ${LT.fmtP(e8.target)}.` + rate8 : ''),
        c.open.code === 'belowValue' || c.open.code === 'belowRange' ? 'up' : c.open.code === 'aboveValue' || c.open.code === 'aboveRange' ? 'dn' : '');
    }
    if (k === 'D' && e8 && e8.trigger) chip(`règle des 80 % : ${e8.reached ? 'objectif atteint' : 'objectif ' + LT.fmtP(e8.target)}`,
      `Ouverture hors de la valeur précédente puis deux tranches clôturées dedans : objectif l'autre bord (${LT.fmtP(e8.target)}).` + rate8, e8.reached ? 'ok' : 'warn');
    if (s.ibStats && s.ibStats.complete) chip(`1re heure ${s.ibStats.extUp > 0 && s.ibStats.extDn > 0 ? 'cassée des deux côtés' : s.ibStats.extUp > 0 ? 'cassée par le haut' : s.ibStats.extDn > 0 ? 'cassée par le bas' : 'intacte'}`,
      `Hauteur de la première heure : ${LT.fmtP(s.ibStats.range)}. Extensions : haut ×${num(1 + s.ibStats.extUp, 2)}, bas ×${num(1 + s.ibStats.extDn, 2)}.` +
      (st && st.ib ? ` Mesuré : une cassure atteint ×1,5 ${pct(st.ib.ext15)} du temps et ×2 ${pct(st.ib.ext2)}.` : ''));
    chip(`rotation ${s.rotation > 0 ? '+' : ''}${s.rotation}`, 'Facteur de rotation : +1 / −1 par plus haut et plus bas plus hauts / plus bas que la tranche précédente. Positif : les acheteurs mènent la séance.', s.rotation > 3 ? 'up' : s.rotation < -3 ? 'dn' : '');
    const tA = s.tpoAbove || 0, tB = s.tpoBelow || 0;
    if (tA + tB) chip(`lettres ${Math.round(tA / (tA + tB) * 100)} % au-dessus du POC`, 'Répartition des lettres de part et d\'autre du POC : beaucoup au-dessus = la séance a surtout échangé plus haut que son prix central.');
    sec.querySelector('[data-ctx]').innerHTML = chips.join('');
    const foot = [];
    if (st) {
      foot.push(`<span title="Mesuré sur ${esc(st.symbol)} (${esc(st.from)} → ${esc(st.to)}, ${st.n} séances)${st.proxy ? ' : mesure du bitcoin, pas de cette paire' : ''}">Mesuré :</span>`);
      foot.push(`<span class="pr">━</span> poor high / low dépassé dès la séance suivante ${pct(st.poor.rate)} (extrême avec queue : ${pct(st.poor.excess)})`);
      foot.push(`POC retraversé ${pct(st.poc.rate)} (témoin ${pct(st.poc.control)})`);
      foot.push(`<span class="tsp">▭</span> single prints comblés en ${st.singles.h} séances ${pct(st.singles.rate)} (témoin ${pct(st.singles.control)})`);
    }
    sec.querySelector('[data-foot]').innerHTML = foot.join(' · ');
  }
  function renderStudy() {
    const body = root.querySelector('.tpostudybody');
    const items = [], seen = new Set();
    let src = null;
    kinds().forEach(([k]) => { const st = data[k] && data[k].study; if (st) { src = st; (st.summary || []).forEach(x => { if (!seen.has(x.text)) { seen.add(x.text); items.push(x); } }); } });
    if (!src) { body.innerHTML = 'Pas encore de mesure disponible pour cette paire.'; return; }
    body.innerHTML = `<p>Mesure faite avec exactement le moteur du terminal sur ${esc(src.symbol)} (${esc(src.source || '')}), ${esc(src.from)} → ${esc(src.to)}` +
      `${src.proxy ? ' — mesure du bitcoin, pas encore de rapport pour cette paire (outil : tools/run_tpo_study.py)' : ''}. Chaque repère est comparé à un témoin placé à la même distance du prix. ` +
      `« Mesuré » = écart net et de même sens sur les deux moitiés de la période.</p><ul>` +
      items.map(x => { const v = VERD[x.verdict] || VERD.insuffisant; return `<li><span class="pill ${v[0]}">${v[1]}</span> ${esc(x.text)}</li>`; }).join('') + '</ul>';
  }
  // ---------- dessin ----------
  function draw(k) {
    const sec = root && root.querySelector(`.tpocol[data-k="${k}"]`), d = data[k];
    if (!sec || !d || !d.ready) return;
    const cv = sec.querySelector('canvas'), body = sec.querySelector('.mbody'), dpr = window.devicePixelRatio || 1;
    const w = body.clientWidth, h = body.clientHeight, t = th(), rgba = LT.rgba, fmtP = LT.fmtP, o = opts(), v = V(k);
    if (!w || !h) return;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); cv.style.width = w + 'px'; cv.style.height = h + 'px'; }
    const ctx = cv.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const bg = t.bg === 'rgba(0,0,0,0)' ? '#0b0e11' : t.bg;
    ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);
    const ss = d.sessions || [], step = d.step;
    if (!ss.length || !step) return;
    const comp = o.comp && d.composite ? d.composite : null;
    const axisW = 66, compW = comp ? Math.min(110, Math.max(70, w * 0.12)) : 0, top = 8, bottom = 30;
    const plotR = w - axisW - compW - (comp ? 8 : 0), plotH = h - top - bottom;
    // largeur des colonnes : lettres (7 px) si au moins 2 seances tiennent, sinon blocs (4 ou 3 px) ; volume : barres fines a droite des lettres
    const maxC = s => Math.max(...s.rows.map(r => r[1]));
    const volW = o.vol ? 22 : 0;
    const visible = ss.slice(0, ss.length - v.offset);
    let cw = 7, fit = [];
    const modes = o.mode === 'letters' ? [[7, 1]] : o.mode === 'blocks' ? [[4, 2], [3, 1]] : [[7, 2], [4, 3], [3, 1]];
    for (const [c, need] of modes) {
      cw = c; fit = []; let used = 0;
      for (let i = visible.length - 1; i >= 0; i--) { const wd = maxC(visible[i]) * c + 16 + volW; if (used + wd > plotR - 4) break; used += wd; fit.unshift(visible[i]); }
      if (fit.length >= Math.min(need, visible.length)) break;
    }
    if (!fit.length) fit = visible.slice(-1);
    // echelle des prix : fourchette des seances visibles (et du prix), puis zoom / deplacement
    let lo = Math.min(...fit.map(s => s.low)), hi = Math.max(...fit.map(s => s.high));
    if (d.price) { lo = Math.min(lo, d.price); hi = Math.max(hi, d.price); }
    lo -= step; hi += step;
    const fullSpan = hi - lo, span = fullSpan / v.zoom;
    const center = v.center != null ? v.center : (lo + hi) / 2;
    const pTop = center + span / 2;
    const Y = p => top + (pTop - p) / span * plotH;
    const priceAt = y => pTop - (y - top) / plotH * span;
    const rowH = Math.max(1, Y(0) - Y(step));
    v.geo = {top, plotH, span, fullSpan, center, priceAt, avgW: 0};
    ctx.save();
    ctx.beginPath(); ctx.rect(0, 0, plotR + compW + (comp ? 8 : 0), h - bottom + 2); ctx.clip();
    // grille et repere de prix
    ctx.font = `500 10px ${t.font}`;
    const every = Math.max(1, Math.ceil(30 / rowH));
    ctx.fillStyle = t.grid;
    for (let p = Math.ceil(priceAt(h - bottom) / step) * step; p <= pTop; p += step) {
      if (Math.round(p / step) % every) continue;
      ctx.fillRect(0, Math.round(Y(p)), plotR, 1);
    }
    // placement des seances (les plus recentes a droite)
    let x = plotR - 4;
    const placed = [];
    for (let i = fit.length - 1; i >= 0; i--) { const s = fit[i], wd = maxC(s) * cw + 16 + volW, x0 = x - wd; placed.unshift({s, x0, wd}); x = x0; }
    v.geo.avgW = placed.length ? placed.reduce((a, c) => a + c.wd, 0) / placed.length : 80;
    // zones du composite (HVN / LVN) en fond, sur toute la largeur
    if (comp) {
      (comp.hvn || []).forEach(([a, b]) => { ctx.fillStyle = 'rgba(120,173,247,0.045)'; ctx.fillRect(0, Y(b), plotR, Y(a) - Y(b)); });
      (comp.lvn || []).forEach(([a, b]) => { ctx.fillStyle = 'rgba(255,179,0,0.04)'; ctx.fillRect(0, Y(b), plotR, Y(a) - Y(b)); });
    }
    const LI = l => LET.indexOf(l);
    placed.forEach(({s, x0, wd}, idx) => {
      const m = s.marks || {}, cur = !!m.current, n = s.brackets || 1, lx = x0 + 9, lettersW = maxC(s) * cw;
      const ibN = s.ibMs && s.bracketMs ? Math.ceil(s.ibMs / s.bracketMs) : 0;
      // separation et zone de valeur
      if (idx) { ctx.fillStyle = 'rgba(255,255,255,0.035)'; ctx.fillRect(Math.round(x0), top, 1, plotH); }
      ctx.fillStyle = 'rgba(120,173,247,0.07)'; ctx.fillRect(x0 + 2, Y(s.vah), wd - 4, Y(s.val) - Y(s.vah));
      ctx.fillStyle = 'rgba(120,173,247,0.65)'; ctx.fillRect(x0 + 2, Y(s.vah), 2, Y(s.val) - Y(s.vah));
      // premiere heure
      if (o.ib && s.ib) {
        ctx.fillStyle = 'rgba(61,220,151,0.75)'; ctx.fillRect(x0 + 5, Y(s.ib[1]), 2, Y(s.ib[0]) - Y(s.ib[1]));
        if (cur && s.ibStats && s.ibStats.complete) {
          ctx.setLineDash([2, 3]); ctx.strokeStyle = 'rgba(61,220,151,0.55)'; ctx.lineWidth = 1;
          ctx.font = `500 9px ${t.font}`; ctx.fillStyle = 'rgba(61,220,151,0.8)'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
          [['up15', '×1,5'], ['up2', '×2'], ['dn15', '×1,5'], ['dn2', '×2']].forEach(([key, lab]) => {
            const p = s.ibStats.targets[key], y = Math.round(Y(p)) + 0.5;
            if (y < top || y > h - bottom) return;
            ctx.beginPath(); ctx.moveTo(x0 + 5, y); ctx.lineTo(x0 + wd - 2, y); ctx.stroke();
            ctx.fillText(lab, x0 + wd - 22, y - 5);
          });
          ctx.setLineDash([]);
        }
      }
      // single prints : rectangle gris (prolonge jusqu'a l'echelle tant qu'il n'est pas comble)
      s.singles.forEach(([a, b], j) => {
        const open = m.singles && m.singles[j] && !m.singles[j][2], yt = Y(b), yb = Y(a), xr = open ? plotR : x0 + wd;
        ctx.fillStyle = open ? t.spFill : 'rgba(150,150,150,0.05)'; ctx.fillRect(x0, yt, xr - x0, yb - yt);
        ctx.strokeStyle = open ? t.spLine : 'rgba(150,150,150,0.14)'; ctx.lineWidth = 1;
        if (open && xr > x0 + wd) ctx.setLineDash([3, 3]);
        ctx.strokeRect(Math.round(x0) + 0.5, Math.round(yt) + 0.5, xr - x0 - 1, Math.max(1, yb - yt - 1)); ctx.setLineDash([]);
      });
      // volume et delta a chaque prix
      const vmax = o.vol ? Math.max(1e-12, ...s.rows.map(r => r[3] || 0)) : 0, vx = lx + lettersW + 3;
      // lettres ou blocs
      const tailHi = s.tailHigh, tailLo = s.tailLow, fs = Math.min(11, Math.max(8, rowH - 1));
      ctx.font = `600 ${fs}px ${t.font}`; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      const showLetters = cw >= 7 && rowH >= 8;
      s.rows.forEach(r => {
        const p = r[0], cnt = r[1], lets = r[2], y1 = Y(p + step), y = Y(p + step / 2);
        if (y1 > h - bottom || Y(p) < top) return;
        const poc = s.poc >= p && s.poc < p + step;
        const tail = (tailHi && p >= tailHi[0] - 1e-9) || (tailLo && p + step <= tailLo[1] + 1e-9);
        if (poc) { ctx.fillStyle = 'rgba(236,236,236,0.12)'; ctx.fillRect(x0 + 2, y1, wd - 4, rowH); }
        for (let q = 0; q < lets.length; q++) {
          const idx2 = LI(lets[q]), f = n > 1 ? idx2 / (n - 1) : 1, isIb = idx2 < ibN, last = cur && idx2 === n - 1;
          ctx.fillStyle = last ? 'rgba(255,196,64,0.98)' : poc ? rgba(t.vpPoc, 1) : tail ? rgba(t.vpGrey, 0.95) : isIb && o.ib ? `rgba(${Math.round(80 + 60 * f)},${Math.round(190 + 30 * f)},${Math.round(140 + 40 * f)},0.95)`
            : `rgba(${Math.round(140 + 100 * f)},${Math.round(150 + 60 * f)},${Math.round(170 + 77 * f)},0.95)`;
          if (showLetters) ctx.fillText(lets[q], lx + q * cw, y + 0.5);
          else ctx.fillRect(lx + q * cw, y1 + (rowH > 3 ? 1 : 0), Math.max(1, cw - 1), Math.max(1, rowH - (rowH > 3 ? 2 : 0)));
        }
        if (o.vol && r[3] > 0) {
          const bw = Math.max(1, (volW - 4) * r[3] / vmax), dl = r[4];
          ctx.fillStyle = poc || (s.vpoc >= p && s.vpoc < p + step) ? 'rgba(236,236,236,0.75)' : dl == null ? rgba(t.vpVA, 0.6) : dl >= 0 ? rgba(t.vpBuy, 0.65) : rgba(t.vpSell, 0.45);
          ctx.fillRect(vx, y1 + (rowH > 3 ? 1 : 0), bw, Math.max(1, rowH - (rowH > 3 ? 2 : 0)));
        }
      });
      // ouverture et cloture
      ctx.fillStyle = 'rgba(200,200,200,0.85)';
      const yo = Y(s.open);
      ctx.beginPath(); ctx.moveTo(x0 + 2, yo - 4); ctx.lineTo(x0 + 7, yo); ctx.lineTo(x0 + 2, yo + 4); ctx.fill();
      if (!cur) {
        const yc = Y(s.close), xc = lx + lettersW + (o.vol ? volW : 0) + 2;
        ctx.beginPath(); ctx.moveTo(xc + 5, yc - 4); ctx.lineTo(xc, yc); ctx.lineTo(xc + 5, yc + 4); ctx.fill();
      }
      // poor high / poor low
      [['poorHigh', 'high', s.high], ['poorLow', 'low', s.low]].forEach(([key, lab, px]) => {
        if (!s[key]) return;
        const active = !m[key] || m[key].active, y = Math.round(Y(px)) + 0.5;
        ctx.strokeStyle = t.poor; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(x0 + 6, y); ctx.lineTo(x0 + wd - 4, y); ctx.stroke();
        if (active && !cur) { ctx.setLineDash([4, 4]); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x0 + wd - 4, y); ctx.lineTo(plotR, y); ctx.stroke(); ctx.setLineDash([]); }
        ctx.font = `500 9px ${t.font}`; ctx.fillStyle = t.poor; ctx.textAlign = 'left'; ctx.textBaseline = lab === 'high' ? 'bottom' : 'top';
        ctx.fillText('poor ' + lab, x0 + 9, lab === 'high' ? y - 2 : y + 2);
      });
      // POC vierge
      if (o.naked && m.poc && m.poc.naked) {
        const y = Math.round(Y(s.poc)) + 0.5;
        ctx.strokeStyle = 'rgba(236,236,236,0.55)'; ctx.lineWidth = 1; ctx.setLineDash([1, 3]);
        ctx.beginPath(); ctx.moveTo(x0 + wd - 4, y); ctx.lineTo(plotR, y); ctx.stroke(); ctx.setLineDash([]);
      }
    });
    // composite a droite : barres (lettres cumulees), zone de valeur, POC, noeuds
    if (comp) {
      const cx0 = plotR + 8, cmax = Math.max(1, ...comp.rows.map(r => r[1]));
      ctx.fillStyle = 'rgba(255,255,255,0.03)'; ctx.fillRect(cx0 - 4, top, compW + 4, plotH);
      comp.rows.forEach(r => {
        const y1 = Y(r[0] + comp.step), y0 = Y(r[0]);
        if (y0 < top || y1 > h - bottom) return;
        const inVa = r[0] >= comp.val - 1e-9 && r[0] < comp.vah - 1e-9, isPoc = comp.poc >= r[0] && comp.poc < r[0] + comp.step;
        ctx.fillStyle = isPoc ? rgba(t.vpPoc, 0.8) : inVa ? rgba(t.vpVA, 0.45) : rgba(t.vpGrey, 0.35);
        ctx.fillRect(cx0, y1 + (y0 - y1 > 3 ? 1 : 0), Math.max(1, (compW - 8) * r[1] / cmax), Math.max(1, y0 - y1 - (y0 - y1 > 3 ? 2 : 0)));
      });
      ctx.font = `500 9px ${t.font}`; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      (comp.hvn || []).forEach(([a, b]) => { ctx.fillStyle = 'rgba(120,173,247,0.95)'; ctx.fillRect(cx0 - 4, Y(b), 2, Y(a) - Y(b)); ctx.fillText('HVN', cx0 + compW - 30, (Y(a) + Y(b)) / 2); });
      (comp.lvn || []).forEach(([a, b]) => { ctx.fillStyle = 'rgba(255,179,0,0.9)'; ctx.fillRect(cx0 - 4, Y(b), 2, Y(a) - Y(b)); ctx.fillText('LVN', cx0 + compW - 30, (Y(a) + Y(b)) / 2); });
      ctx.fillStyle = t.label; ctx.textBaseline = 'top'; ctx.fillText(`composite ${comp.n}`, cx0, top + 2);
    }
    ctx.restore();
    // libelles des seances (bas) : date / heure, type de journee
    ctx.font = `500 9.5px ${t.font}`; ctx.textAlign = 'left'; ctx.textBaseline = 'bottom';
    placed.forEach(({s, x0, wd}) => {
      const cur = s.marks && s.marks.current;
      ctx.fillStyle = cur ? rgba(t.vpBuy, 1) : t.label;
      ctx.fillText(when(k, s.start) + (cur ? ' · en cours' : ''), x0 + 6, h - 16, wd - 8);
      const c = s.ctx || {}, sub = [c.dayType ? c.dayType.label : null, s.shape ? 'forme ' + SHAPE_SHORT[s.shape] : null].filter(Boolean).join(' · ');
      if (sub) { ctx.fillStyle = 'rgba(150,150,150,0.8)'; ctx.fillText(sub, x0 + 6, h - 4, wd - 8); }
    });
    // echelle des prix
    ctx.font = `500 10px ${t.font}`; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillStyle = t.text;
    const ax = w - axisW + 4;
    for (let p = Math.ceil(priceAt(h - bottom) / step) * step; p <= pTop; p += step) {
      if (Math.round(p / step) % every) continue;
      const y = Y(p);
      if (y > top + 6 && y < h - bottom - 4) ctx.fillText(fmtP(p), ax, y);
    }
    // prix actuel
    if (d.price) {
      const y = Math.round(Y(d.price)) + 0.5;
      if (y > top && y < h - bottom) {
        ctx.strokeStyle = t.price; ctx.lineWidth = 1; ctx.setLineDash([2, 3]); ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w - axisW, y); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = t.price; ctx.fillRect(w - axisW + 1, y - 9, axisW - 2, 18);
        ctx.fillStyle = t.priceText; ctx.font = `600 10px ${t.font}`; ctx.fillText(fmtP(d.price), ax, y);
      }
    }
    sec.querySelector('[data-info]').textContent = `${placed.length} séance${placed.length > 1 ? 's' : ''}${v.offset ? ` (−${v.offset})` : ''} · une ligne = ${fmtP(step)} $${v.zoom > 1 ? ' · zoom ×' + num(v.zoom, 1) : ''}`;
    // reticule et bulle
    const tip = sec.querySelector('.tip');
    if (v.hover && !v.drag) {
      const hy = v.hover.y, hx = v.hover.x;
      if (hy > top && hy < h - bottom) {
        const p = priceAt(hy), y = Math.round(hy) + 0.5;
        ctx.strokeStyle = 'rgba(200,200,200,0.35)'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w - axisW, y); ctx.stroke();
        ctx.fillStyle = '#2a2f3a'; ctx.fillRect(w - axisW + 1, y - 9, axisW - 2, 18);
        ctx.fillStyle = '#e8e8e8'; ctx.font = `600 10px ${t.font}`; ctx.textAlign = 'left'; ctx.fillText(fmtP(p), ax, y);
        const sx = placed.find(c => hx >= c.x0 && hx < c.x0 + c.wd);
        if (sx) {
          const s = sx.s, r = s.rows.find(r => p >= r[0] && p < r[0] + step), c = s.ctx || {}, st = d.study;
          const sp = s.singles.find(([a, b]) => p >= a && p < b), mk = s.marks || {};
          let html = `<b>${esc(when(k, s.start))}</b> · ${fmtP(Math.floor(p / step) * step)} – ${fmtP(Math.floor(p / step) * step + step)}<br>` +
            (r ? `${r[1]} tranche${r[1] > 1 ? 's' : ''} : ${esc(r[2])}` + (r[3] ? `<br>volume ${num(r[3], 2)}${r[4] != null ? ` · delta ${r[4] >= 0 ? '+' : '−'}${num(Math.abs(r[4]), 2)}` : ''}` : '') : 'aucune tranche à ce prix');
          if (sp) html += `<br><span class="tipsp">single prints</span>${st ? ` : comblés en ${st.singles.h} séances ${pct(st.singles.rate)} du temps (témoin ${pct(st.singles.control)})` : ''}`;
          html += `<br><span class="muted">POC ${fmtP(s.poc)}${s.vpoc ? ` (volume ${fmtP(s.vpoc)})` : ''} · valeur ${fmtP(s.val)} – ${fmtP(s.vah)}${s.ib ? ` · 1re heure ${fmtP(s.ib[0])} – ${fmtP(s.ib[1])}` : ''}</span>`;
          if (mk.poc && mk.poc.naked) html += `<br><span class="muted">POC vierge${st ? ` : retraversé dès la séance suivante ${pct(st.poc.rate)} en moyenne (témoin ${pct(st.poc.control)})` : ''}</span>`;
          if (c.dayType) html += `<br><span class="muted">${esc(c.dayType.label)}${s.shapeText ? ' · ' + esc(s.shapeText) : ''}</span>`;
          tip.innerHTML = html;
          tip.style.left = Math.min(w - 250, hx + 14) + 'px'; tip.style.top = Math.max(4, Math.min(h - 120, hy - 10)) + 'px'; tip.hidden = false;
        } else tip.hidden = true;
      } else tip.hidden = true;
    } else tip.hidden = true;
  }
  function drawAll() { kinds().forEach(([k]) => draw(k)); }
  function show() {
    const was = on;
    on = true;
    build(); drawAll();
    kinds().forEach(([k]) => renderCtx(k)); renderStudy();
    if (!was) { load(); clearInterval(timer); timer = setInterval(load, 20000); }
    setTimeout(drawAll, 120);                                         // apres le changement de mise en page (panneau lateral...)
    window.addEventListener('resize', drawAll);
  }
  function hide() { on = false; clearInterval(timer); timer = null; window.removeEventListener('resize', drawAll); }
  function refresh() { Object.keys(data).forEach(k => delete data[k]); Object.keys(view).forEach(k => delete view[k]); if (on) { build(); load(); } }
  // prix en direct : seule la ligne du prix bouge entre deux chargements (redessin au plus toutes les 0,5 s)
  function onTick(price) {
    if (!on || !(price > 0)) return;
    Object.values(data).forEach(d => { d.price = price; });
    const now = Date.now();
    if (now - lastTick < 500) return;
    lastTick = now; schedule();
  }
  return {init, show, hide, refresh, onTick, redraw: drawAll, active: () => on};
})();
