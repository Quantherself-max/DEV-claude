// Petits graphiques SVG sans dependance : lignes avec survol, calibration, frise des annonces, sparklines, jauges.
// Regles : traits fins (2 px), grille discrete, pas de double axe, texte en gris (jamais dans la couleur de la serie),
// bague de 2 px autour des points, infobulle au survol, identite des series par pastille + nom.
const Charts = (() => {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const SURFACE = '#131722';
  const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  let tipEl = null;
  function tip(html, x, y) {
    if (!tipEl) { tipEl = document.createElement('div'); tipEl.className = 'ctip'; document.body.appendChild(tipEl); }
    tipEl.innerHTML = html; tipEl.style.display = 'block';
    const w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    tipEl.style.left = Math.min(window.innerWidth - w - 8, x + 14) + 'px';
    tipEl.style.top = Math.max(4, Math.min(window.innerHeight - h - 8, y - h - 10)) + 'px';
  }
  const hideTip = () => { if (tipEl) tipEl.style.display = 'none'; };

  function ticks(lo, hi, n = 4) {
    if (!(hi > lo)) { hi = lo + 1; }
    const raw = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / mag;
    const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag, out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-6; v += step) out.push(+v.toFixed(10));
    return out;
  }
  const el = (name, attrs = {}, parent) => {
    const n = document.createElementNS(NS, name);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  };

  // ---- lignes (1 a 3 series) avec survol ----
  // opts: {series:[{name,color,pts:[[x,y]],area}], height, xFmt, yFmt, ref:{y,label}, yPad, xTicks}
  function line(host, opts) {
    host._opts = opts;
    if (!host._ro && window.ResizeObserver) { host._ro = new ResizeObserver(() => host._opts && line(host, host._opts)); host._ro.observe(host); }
    const W = Math.max(260, host.clientWidth || 600), H = opts.height || 180, m = {l: 48, r: 56, t: 10, b: 22};
    host.innerHTML = '';
    const all = opts.series.flatMap(s => s.pts);
    if (all.length < 2) { host.innerHTML = '<div class="muted small">Pas assez de données.</div>'; return; }
    let x0 = Math.min(...all.map(p => p[0])), x1 = Math.max(...all.map(p => p[0]));
    let y0 = Math.min(...all.map(p => p[1])), y1 = Math.max(...all.map(p => p[1]));
    if (opts.ref) { y0 = Math.min(y0, opts.ref.y); y1 = Math.max(y1, opts.ref.y); }
    const pad = (y1 - y0) * (opts.yPad ?? 0.08) || Math.abs(y0) * 0.01 || 1;
    y0 -= pad; y1 += pad;
    const X = x => m.l + (x - x0) / (x1 - x0 || 1) * (W - m.l - m.r), Y = y => m.t + (1 - (y - y0) / (y1 - y0)) * (H - m.t - m.b);
    const svg = el('svg', {class: 'ch', viewBox: `0 0 ${W} ${H}`, height: H}, host);
    const yf = opts.yFmt || (v => v.toFixed(2)), xf = opts.xFmt || (v => v);
    ticks(y0, y1, 4).forEach(v => {
      el('line', {x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), class: 'grid'}, svg);
      el('text', {x: m.l - 6, y: Y(v) + 3, 'text-anchor': 'end'}, svg).textContent = yf(v);
    });
    const nx = opts.xTicks || 5;
    for (let i = 0; i <= nx; i++) {
      const v = x0 + (x1 - x0) * i / nx;
      el('text', {x: X(v), y: H - 5, 'text-anchor': i === 0 ? 'start' : i === nx ? 'end' : 'middle'}, svg).textContent = xf(v);
    }
    if (opts.ref) {
      el('line', {x1: m.l, x2: W - m.r, y1: Y(opts.ref.y), y2: Y(opts.ref.y), stroke: '#4a4e5a', 'stroke-width': 1, 'stroke-dasharray': '3 3'}, svg);
      if (opts.ref.label) el('text', {x: W - m.r + 4, y: Y(opts.ref.y) + 3}, svg).textContent = opts.ref.label;
    }
    opts.series.forEach(s => {
      const d = s.pts.map((p, i) => (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join('');
      if (s.area) el('path', {d: d + `L${X(s.pts[s.pts.length - 1][0])} ${H - m.b}L${X(s.pts[0][0])} ${H - m.b}Z`, fill: s.color, 'fill-opacity': 0.1}, svg);
      el('path', {d, fill: 'none', stroke: s.color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'}, svg);
      const last = s.pts[s.pts.length - 1];
      el('circle', {cx: X(last[0]), cy: Y(last[1]), r: 4, fill: s.color, stroke: SURFACE, 'stroke-width': 2}, svg);
      el('text', {x: X(last[0]) + 8, y: Y(last[1]) + 3, style: 'fill:#d1d4dc;font-weight:600'}, svg).textContent = yf(last[1]);
    });
    if (opts.series.length > 1) {                                  // legende : pastille + nom (le texte reste gris)
      let lx = m.l;
      opts.series.forEach(s => {
        el('rect', {x: lx, y: 0, width: 10, height: 3, rx: 1.5, fill: s.color}, svg);
        const t = el('text', {x: lx + 14, y: 5}, svg); t.textContent = s.name; lx += 24 + s.name.length * 6;
      });
    }
    const cross = el('line', {y1: m.t, y2: H - m.b, stroke: '#6a6e7a', 'stroke-width': 1, visibility: 'hidden'}, svg);
    const dots = opts.series.map(s => el('circle', {r: 4, fill: s.color, stroke: SURFACE, 'stroke-width': 2, visibility: 'hidden'}, svg));
    const hit = el('rect', {x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent'}, svg);
    hit.addEventListener('mousemove', ev => {
      const r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) * W / r.width;
      const xv = x0 + (px - m.l) / (W - m.l - m.r) * (x1 - x0);
      let html = '', cx = null;
      opts.series.forEach((s, k) => {
        let best = s.pts[0];
        for (const p of s.pts) if (Math.abs(p[0] - xv) < Math.abs(best[0] - xv)) best = p;
        dots[k].setAttribute('cx', X(best[0])); dots[k].setAttribute('cy', Y(best[1])); dots[k].setAttribute('visibility', 'visible');
        cx = cx ?? X(best[0]);
        html += `<div><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${s.color};margin-right:6px"></span>${esc(s.name)} <b>${yf(best[1])}</b></div>`;
        if (k === 0) html = `<div class="muted">${xf(best[0])}</div>` + html;
      });
      cross.setAttribute('x1', cx); cross.setAttribute('x2', cx); cross.setAttribute('visibility', 'visible');
      tip(html, ev.clientX, ev.clientY);
    });
    hit.addEventListener('mouseleave', () => { cross.setAttribute('visibility', 'hidden'); dots.forEach(d => d.setAttribute('visibility', 'hidden')); hideTip(); });
  }

  // ---- calibration : probabilite annoncee (x) contre frequence reelle (y) ----
  function calib(host, bins, color = '#3987e5') {
    const W = Math.max(240, host.clientWidth || 360), H = 230, m = {l: 40, r: 14, t: 10, b: 32};
    host.innerHTML = '';
    if (!bins || bins.length < 2) { host.innerHTML = '<div class="muted small">Pas assez de données hors échantillon.</div>'; return; }
    const lo = Math.max(0, Math.min(...bins.map(b => Math.min(b.p, b.freq))) - 0.03), hi = Math.min(1, Math.max(...bins.map(b => Math.max(b.p, b.freq))) + 0.03);
    const S = v => (v - lo) / (hi - lo || 1);
    const X = v => m.l + S(v) * (W - m.l - m.r), Y = v => m.t + (1 - S(v)) * (H - m.t - m.b);
    const svg = el('svg', {class: 'ch', viewBox: `0 0 ${W} ${H}`, height: H}, host);
    ticks(lo * 100, hi * 100, 4).forEach(v => {
      el('line', {x1: m.l, x2: W - m.r, y1: Y(v / 100), y2: Y(v / 100), class: 'grid'}, svg);
      el('text', {x: m.l - 6, y: Y(v / 100) + 3, 'text-anchor': 'end'}, svg).textContent = v.toFixed(0) + ' %';
      el('text', {x: X(v / 100), y: H - 18, 'text-anchor': 'middle'}, svg).textContent = v.toFixed(0) + ' %';
    });
    el('text', {x: (W + m.l) / 2, y: H - 3, 'text-anchor': 'middle'}, svg).textContent = 'probabilité annoncée par le modèle';
    el('line', {x1: X(lo), y1: Y(lo), x2: X(hi), y2: Y(hi), stroke: '#6a6e7a', 'stroke-width': 1, 'stroke-dasharray': '3 3'}, svg);
    el('text', {x: X(hi) - 4, y: Y(hi) + 12, 'text-anchor': 'end'}, svg).textContent = 'calibration parfaite';
    el('path', {d: bins.map((b, i) => (i ? 'L' : 'M') + X(b.p) + ' ' + Y(b.freq)).join(''), fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round'}, svg);
    bins.forEach(b => {
      const c = el('circle', {cx: X(b.p), cy: Y(b.freq), r: 5, fill: color, stroke: SURFACE, 'stroke-width': 2}, svg);
      c.addEventListener('mousemove', ev => tip(`Annoncé <b>${(b.p * 100).toFixed(1)} %</b><br>Réalisé <b>${(b.freq * 100).toFixed(1)} %</b><br><span class="muted">${b.n} cas</span>`, ev.clientX, ev.clientY));
      c.addEventListener('mouseleave', hideTip);
    });
  }

  // ---- frise des annonces : passe (gauche) / a venir (droite) ----
  function timeline(host, events, now, opts = {}) {
    const W = Math.max(300, host.clientWidth || 700), H = 96, m = {l: 14, r: 14, t: 14, b: 26};
    const x0 = now - (opts.back || 3) * 86400000, x1 = now + (opts.fwd || 5) * 86400000;
    const X = t => m.l + (t - x0) / (x1 - x0) * (W - m.l - m.r);
    host.innerHTML = '';
    const svg = el('svg', {class: 'ch', viewBox: `0 0 ${W} ${H}`, height: H}, host);
    el('line', {x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, class: 'ax'}, svg);
    for (let d = Math.ceil(x0 / 86400000) * 86400000; d <= x1; d += 86400000) {
      el('line', {x1: X(d), x2: X(d), y1: m.t, y2: H - m.b, class: 'grid'}, svg);
      el('text', {x: X(d) + 3, y: H - 10}, svg).textContent = new Date(d).toLocaleDateString('fr-FR', {weekday: 'short', day: 'numeric'});
    }
    el('line', {x1: X(now), x2: X(now), y1: 4, y2: H - m.b, stroke: '#4c8dff', 'stroke-width': 2}, svg);
    el('text', {x: X(now) + 4, y: 11, style: 'fill:#d1d4dc'}, svg).textContent = 'maintenant';
    events.filter(e => e.t >= x0 && e.t <= x1).forEach(e => {
      const past = e.t <= now, r = e.impact === 3 ? 6 : 4, cy = H - m.b - 6 - (e.impact === 3 ? 30 : 12);
      el('line', {x1: X(e.t), x2: X(e.t), y1: cy, y2: H - m.b, stroke: past ? '#4a4e5a' : '#d95926', 'stroke-width': 1}, svg);
      const c = el('circle', {cx: X(e.t), cy, r, fill: past ? '#4a4e5a' : '#d95926', stroke: SURFACE, 'stroke-width': 2}, svg);
      c.addEventListener('mousemove', ev => tip(`<b>${esc(e.label || e.title)}</b><br>${new Date(e.t).toLocaleString('fr-FR', {weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'})}` +
        (e.forecast ? `<br>Consensus ${esc(e.forecast)} · précédent ${esc(e.previous || '-')}` : '') + (e.reaction && e.reaction.impulseLabel ? `<br>Surprise ${esc(e.reaction.impulseLabel)}` : ''), ev.clientX, ev.clientY));
      c.addEventListener('mouseleave', hideTip);
    });
  }

  // ---- sparkline en chaine SVG (sans survol : la valeur est ecrite a cote) ----
  function spark(vals, color = '#3987e5', w = 150, h = 34) {
    if (!vals || vals.length < 2) return '';
    const lo = Math.min(...vals), hi = Math.max(...vals), sp = hi - lo || 1;
    const pts = vals.map((v, i) => [i / (vals.length - 1) * (w - 6) + 3, h - 4 - (v - lo) / sp * (h - 8)]);
    const last = pts[pts.length - 1];
    return `<svg class="ch" viewBox="0 0 ${w} ${h}" height="${h}" preserveAspectRatio="none"><path d="${pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join('')}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/><circle cx="${last[0]}" cy="${last[1]}" r="3.5" fill="${color}" stroke="${SURFACE}" stroke-width="2"/></svg>`;
  }

  // ---- jauge -100..+100 ----
  function meter(score, lo = -100, hi = 100) {
    const pos = Math.max(0, Math.min(100, (score - lo) / (hi - lo) * 100));
    return `<div class="meter"><span class="tick" style="left:25%"></span><span class="tick" style="left:50%"></span><span class="tick" style="left:75%"></span><i style="left:${pos}%"></i></div>` +
      `<div class="mlab"><span>${lo}</span><span>0</span><span>+${hi}</span></div>`;
  }
  // ---- barre divergente (-1..1) ----
  function dvBar(v, max = 1, up = '#3ddc97', dn = '#ff6b6b') {
    const w = Math.min(50, Math.abs(v) / max * 50);
    return `<div class="dv"><u></u><i style="${v >= 0 ? 'left:50%' : `left:${50 - w}%`};width:${w}%;background:${v >= 0 ? up : dn}"></i></div>`;
  }
  return {line, calib, timeline, spark, meter, dvBar, hideTip, esc, ticks};
})();
