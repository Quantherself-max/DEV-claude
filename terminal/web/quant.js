// V45 : onglet Quant. Tout ce qui s'affiche ici vient de /api/quant (ingest/hub.py) : des sources publiques réelles lues en direct, calculées
// par le moteur exact (paquet quant : entiers et décimaux, aucun flottant dans les sommes). Une source qui ne répond pas affiche son erreur ;
// rien n'est jamais remplacé par une valeur fabriquée.
//   Régime de marché   prix + intérêt ouvert + financement + CVD des perpétuels + CVD du comptant, sur 15 minutes, 1 heure et 4 heures
//   CVD exact          transaction par transaction (côté de l'agresseur), contrôlé chaque minute contre la bougie officielle de Binance
// V45.1 : le moteur ne tourne que pendant que cet onglet est ouvert (il s'arrête 5 minutes après) : aucun effet sur le démarrage du terminal.
//   Divergences, absorptions, bourses (BTC), carnet (déséquilibre pondéré, murs, ordres retirés), profil de volume exact, dérivés,
//   options (volatilité, skew 25 delta, max pain, gamma), réseau Bitcoin.
// V48 : page réorganisée (synthèse en tête, puis cinq rubriques ; les explications sont repliées sous « Comment lire »), nouvelle carte
//   « Comptant contre perpétuels » (24 et 48 heures, bougies officielles d'une heure) et plus d'état des sources.
const QUANTV = (() => {
  'use strict';
  let LT = null, root = null, on = false, timer = null, data = null, err = null, busy = false, win = '1h', vwin = '1h';
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const sgn = v => v > 0 ? '+' : v < 0 ? '−' : '';
  const nf = (v, d = 0) => v == null || !isFinite(v) ? '—' : Math.abs(v).toLocaleString('fr-FR', {minimumFractionDigits: d, maximumFractionDigits: d}).replace(/ | /g, ' ');
  const sn = (v, d = 0) => v == null || !isFinite(v) ? '—' : sgn(v) + nf(v, d);
  const pct = (v, d = 1) => v == null || !isFinite(v) ? '—' : sgn(v) + nf(v * 100, d) + ' %';
  const usd = v => { if (v == null || !isFinite(v)) return '—'; const a = Math.abs(v);
    return a >= 1e9 ? nf(a / 1e9, 2) + ' Md$' : a >= 1e6 ? nf(a / 1e6, a >= 1e8 ? 0 : 1) + ' M$' : a >= 1e3 ? nf(a / 1e3, 0) + ' k$' : nf(a, 0) + ' $'; };
  const susd = v => v == null ? '—' : sgn(v) + usd(v);
  const px = v => v == null ? '—' : LT.fmtP ? LT.fmtP(v) : nf(v, 2);
  const HM = new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', hour: '2-digit', minute: '2-digit'});
  const DM = new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
  const DAYF = new Intl.DateTimeFormat('fr-FR', {timeZone: 'UTC', day: '2-digit', month: '2-digit'});
  const ago = ms => { if (ms == null) return '—'; const s = Math.max(0, Math.round(ms / 1000));
    return s < 90 ? `il y a ${s} s` : s < 5400 ? `il y a ${Math.round(s / 60)} min` : s < 172800 ? `il y a ${Math.round(s / 3600)} h` : `il y a ${Math.round(s / 86400)} j`; };
  const cls = v => v > 0 ? 'up' : v < 0 ? 'dn' : '';
  const WLAB = {'5m': '5 min', '15m': '15 min', '1h': '1 h', '4h': '4 h', '24h': '24 h'};
  const card = (title, body, extra = '') => `<section class="qcard ${extra}"><div class="qh">${title}</div>${body}</section>`;
  const bad = t => `<p class="muted small">${esc(t)}</p>`;
  const coin = () => (LT.st.symbol || '').replace(/USDT$/, '');

  function init(lt, host) {
    LT = lt; root = host;
    root.innerHTML = `<div class="qbar"><b class="qttl"></b><span class="qmeta muted small"></span><span class="spacer"></span>` +
      `<span class="muted small">Données réelles uniquement · calculs exacts</span></div><div class="qtop"></div><div class="qgrid"></div>`;
    root.addEventListener('click', e => {
      const b = e.target.closest('[data-qw]'); if (b) { win = b.dataset.qw; render(); return; }
      const v = e.target.closest('[data-qv]'); if (v) { vwin = v.dataset.qv; render(); }
    });
  }

  async function load() {
    if (busy || !on) return;
    busy = true;
    try {
      const r = await fetch(`/api/quant?symbol=${encodeURIComponent(LT.st.symbol)}`);
      if (!r.ok) throw new Error(r.status === 404 ? 'cette page demande la version 45 du terminal : ferme la fenêtre noire et relance-le' : 'HTTP ' + r.status);
      const d = await r.json();
      if (d.ok === false) { err = d.why || 'indisponible'; data = null; } else { data = d; err = null; }
    } catch (e) { err = String(e.message || e); }
    busy = false;
    render();
  }

  // ---------- outils de présentation ----------
  const help = html => `<details class="qhelp"><summary>Comment lire</summary>${html}</details>`;
  const sec = t => `<div class="qsec">${t}</div>`;
  const tile = (lab, val, sub, c = '') => `<div class="qtile"><div class="qtl">${lab}</div><div class="qtv ${c}">${val}</div><div class="qts muted">${sub || ''}</div></div>`;
  const CONV = {both_buy: 'Acheteuse forte', spot_vs_shorts: 'Comptant acheteur', spot_buy: 'Comptant acheteur', lev_buy_spot_sell: 'Levier seul · fragile',
    lev_buy: 'Levier acheteur', both_sell: 'Vendeuse forte', spot_sell: 'Comptant vendeur', lev_sell: 'Levier vendeur', flat: 'Neutre', missing: '—'};
  const bcls = b => b > 0 ? 'up' : b < 0 ? 'dn' : '';

  // ---------- synthèse ----------
  function summary(d) {
    const r = d.regime && d.regime['1h'], c = d.cvd && d.cvd.windows && d.cvd.windows['1h'], b = d.book, x = d.derivs || {};
    const sp = d.spotPerp && d.spotPerp.windows && d.spotPerp.windows['24h'];
    const last = d.cvd && d.cvd.last && d.cvd.last.perp;
    const t = [];
    t.push(tile('Prix', px(last || (sp && sp.perp && sp.perp.close)), sp && sp.perp && sp.perp.move != null ? `<span class="${cls(sp.perp.move)}">${pct(sp.perp.move, 2)}</span> sur 24 h` : ''));
    t.push(r && !r.error ? tile('Régime 1 h', esc(r.label), `force ${nf(r.score * 100)} %`, bcls(r.bias)) : tile('Régime 1 h', '—', r ? esc(r.error) : 'pas encore mesuré'));
    t.push(sp ? tile('Conviction 24 h', CONV[sp.read.code] || '—', sp.spot && sp.spot.imb != null && sp.perp && sp.perp.imb != null ?
      `comptant <span class="${cls(sp.spot.imb)}">${pct(sp.spot.imb)}</span> · perpétuels <span class="${cls(sp.perp.imb)}">${pct(sp.perp.imb)}</span>` : '', bcls(sp.read.bias))
      : tile('Conviction 24 h', '—', d.spotPerp && d.spotPerp.error ? esc(d.spotPerp.error) : 'chargement'));
    const cv = (n, w) => w && w.n ? tile(`CVD 1 h · ${n}`, susd(w.deltaUsd), `${pct(w.imb)} du volume`, cls(w.delta)) : tile(`CVD 1 h · ${n}`, '—', 'pas de données');
    t.push(cv('perpétuels', c && c.perp), cv('comptant', c && c.spot));
    t.push(b && !b.error ? tile('Carnet ± 0,5 %', pct(b.obi['0.005'], 0), `${usd(b.depth['0.005'].bid)} / ${usd(b.depth['0.005'].ask)}`, cls(b.obi['0.005'])) : tile('Carnet ± 0,5 %', '—', 'pas encore synchronisé'));
    t.push(tile('Financement / 8 h', pct(x.funding, 4), x.oi24h != null ? `intérêt ouvert <span class="${cls(x.oi24h)}">${pct(x.oi24h, 2)}</span> sur 24 h` : '', cls(x.funding)));
    const g = d.options && d.options.gex;
    if (g) t.push(tile('Bascule du gamma', px(g.flip), `calls ${px(g.callWall)} · puts ${px(g.putWall)}`));
    return `<div class="qtiles">${t.join('')}</div>`;
  }

  // ---------- flux d'ordres ----------
  function spotPerpCard(d) {
    const s = d.spotPerp;
    const title = 'Comptant contre perpétuels · conviction sur 24 et 48 heures';
    if (!s || s.error) return card(title, bad(s ? s.error : 'indisponible'), 'qwide');
    const W = s.windows || {};
    const imbs = [];
    ['24h', '48h'].forEach(k => ['spot', 'perp'].forEach(m => { const v = W[k] && W[k][m] && W[k][m].imb; if (v != null) imbs.push(Math.abs(v)); }));
    const scale = Math.max(0.05, ...imbs);                               // la barre la plus longue remplit la moitié ; au moins ± 5 %
    const bar = v => { const w = v == null ? 0 : Math.min(50, Math.abs(v) / scale * 50);
      return `<div class="qobar"><i class="${v >= 0 ? 'up' : 'dn'}" style="width:${w.toFixed(1)}%;${v >= 0 ? 'left:50%' : `left:${(50 - w).toFixed(1)}%`}"></i></div>`; };
    const line = (lab, x) => !x || x.error ? `<div class="qspr"><span>${lab}</span><span class="muted small qspe">${esc(x ? x.error : 'pas de données')}</span></div>` :
      `<div class="qspr"><span>${lab}</span>${bar(x.imb)}<b class="${cls(x.deltaUsd)}">${susd(x.deltaUsd)}</b><span class="${cls(x.imb)} small">${pct(x.imb)}</span></div>`;
    const block = k => { const w = W[k]; if (!w) return '';
      const mv = w.perp && w.perp.move != null ? ` · prix <span class="${cls(w.perp.move)}">${pct(w.perp.move, 2)}</span>` : '';
      const share = w.spotShareVol != null ? `<div class="muted small">Le comptant fait ${nf(w.spotShareVol * 100)} % du volume au marché et ${nf(w.spotShareBuy * 100)} % des achats.</div>` : '';
      return `<div class="qsp"><div class="qsph"><b>${k === '24h' ? '24 heures' : '48 heures'}</b><span class="muted small">${mv}</span></div>` +
        `<div class="qverdict ${bcls(w.read.bias)}">${esc(w.read.label)}</div>${line('Comptant', w.spot)}${line('Perpétuels', w.perp)}${share}</div>`; };
    return card(title, `<div class="qsps">${block('24h')}${block('48h')}</div>${hourly(s.series || [])}` + help(
      `<p class="small">Chaque bougie officielle d'une heure de Binance donne le volume acheté au marché (l'acheteur traverse l'écart) ; le reste est vendu au marché. Net = achats − ventes, en dollars. Le pourcentage est la part nette dans le volume de ce marché : c'est lui qui compare les deux marchés, car les perpétuels échangent bien plus que le comptant.</p>` +
      `<p class="small">Un marché « achète » quand sa part nette dépasse + 1 %, « vend » sous − 1 %. Le comptant, c'est de l'argent réel qui achète la pièce ; les perpétuels, c'est du levier. Comptant et perpétuels acheteurs : conviction forte. Perpétuels acheteurs et comptant vendeur : hausse portée par le levier, fragile (risque de liquidation des longs). Comptant acheteur et perpétuels vendeurs : accumulation face à des vendeurs à découvert, qui peut finir en rachat forcé des shorts.</p>` +
      `<p class="muted small">Barres d'une heure de 48 heures, l'heure en cours comprise (elle se complète au fil de l'heure). Relu chaque minute.</p>`), 'qwide');
  }

  function hourly(rows) {
    if (rows.length < 3) return '';
    const W = 600, lab = 14, lane = 56, gap = 8, H = 2 * (lab + lane) + gap, n = rows.length, bw = W / n;
    const draw = (idx, y0) => {
      const v = rows.map(r => r[idx]);
      const mx = Math.max(...v.map(x => Math.abs(x || 0))) || 1;
      const mid = y0 + lane / 2;
      let out = `<line x1="0" x2="${W}" y1="${mid}" y2="${mid}" stroke="rgba(148,163,184,.35)" stroke-width="0.6"/>`;
      v.forEach((x, i) => { if (x == null) return; const h = Math.abs(x) / mx * (lane / 2 - 1);
        out += `<rect x="${(i * bw + bw * 0.12).toFixed(1)}" width="${(bw * 0.76).toFixed(1)}" y="${(x >= 0 ? mid - h : mid).toFixed(1)}" height="${Math.max(0.6, h).toFixed(1)}" fill="${x >= 0 ? '#22c55e' : '#ef4444'}" opacity="0.85"/>`; });
      let c = 0; const cum = v.map(x => (c += x || 0));
      const lo = Math.min(0, ...cum), hi = Math.max(0, ...cum), sp = hi - lo || 1;
      out += `<polyline fill="none" stroke="#e5e7eb" stroke-width="1.2" points="${cum.map((y, i) => `${((i + 0.5) * bw).toFixed(1)},${(y0 + lane - 2 - (y - lo) / sp * (lane - 4)).toFixed(1)}`).join(' ')}"/>`;
      return out;
    };
    const cut = Math.max(0, n - 24) * bw;
    const y2 = 2 * lab + lane + gap;
    const pc = v => (v / H * 100).toFixed(1) + '%';
    const t0 = rows[0][0], tm = rows[Math.max(0, n - 24)][0];
    return `<div class="qhw"><svg class="qhourly" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${draw(1, lab)}${draw(2, y2)}` +
      `<line x1="${cut}" x2="${cut}" y1="0" y2="${H}" stroke="#38bdf8" stroke-width="1" stroke-dasharray="3 3"/></svg>` +
      `<span class="qhl" style="top:1px">Comptant · net par heure</span><span class="qhl" style="top:${pc(lab + lane + gap)}">Perpétuels · net par heure</span></div>` +
      `<div class="qhaxis small muted"><span>${DM.format(t0)}</span><span style="left:${(cut / W * 100).toFixed(1)}%">${DM.format(tm)} · début des 24 h</span><span>maintenant</span></div>` +
      `<div class="qlegend small muted">Barres : achats − ventes au marché de chaque heure · trait clair : cumul · chaque rangée à sa propre échelle</div>`;
  }

  function chart(series) {
    const p = (series && series.perp) || [], s = (series && series.spot) || [];
    if (p.length < 3) return bad('pas encore assez de minutes pour tracer le CVD');
    const W = 600, H = 150, t0 = p[0][0], t1 = p[p.length - 1][0];
    const line = (rows, idx, color, base) => {
      if (rows.length < 2) return '';
      const vals = rows.map(r => r[idx] - (base ? rows[0][idx] : 0));
      const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
      const pts = rows.map((r, i) => `${((r[0] - t0) / (t1 - t0 || 1) * W).toFixed(1)},${(H - 6 - (vals[i] - lo) / span * (H - 12)).toFixed(1)}`).join(' ');
      return `<polyline fill="none" stroke="${color}" stroke-width="1.4" points="${pts}"/>`;
    };
    return `<svg class="qchart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${line(p, 1, '#94a3b8', false)}${line(p, 2, '#22c55e', true)}${line(s, 2, '#38bdf8', true)}</svg>` +
      `<div class="qlegend small"><span style="color:#94a3b8">■ prix</span> <span style="color:#22c55e">■ CVD perpétuels</span> <span style="color:#38bdf8">■ CVD comptant</span>` +
      ` <span class="muted">· 24 h, barres de 5 min, chaque courbe à sa propre échelle</span></div>`;
  }

  function cvdCard(d) {
    const c = d.cvd;
    if (!c) return card('CVD exact', bad('indisponible'));
    const head = `<tr><th></th><th colspan="2">Perpétuels</th><th colspan="2">Comptant</th></tr>`;
    const rows = Object.keys(WLAB).map(k => {
      const w = c.windows[k]; if (!w) return '';
      const cell = x => x.n ? `<td class="${cls(x.delta)}">${sn(x.delta, Math.abs(x.delta) < 100 ? 2 : 0)} ${coin()}${x.cover < 0.9 ? ' ≈' : ''}</td><td class="${cls(x.imb)}">${pct(x.imb)}</td>` : '<td class="muted" colspan="2">pas de données</td>';
      return `<tr><td>${WLAB[k]}</td>${cell(w.perp)}${cell(w.spot)}</tr>`;
    }).join('');
    const it = d.integrity || {};
    const okLine = ['perp', 'spot'].map(m => { const x = it[m]; if (!x) return '';
      const n = (x.verified || 0) + (x.shifted || 0);
      return `<span class="${x.mismatch ? 'dn' : n ? 'up' : 'muted'}">${m === 'perp' ? 'perpétuels' : 'comptant'} ${x.mismatch ? 'anormal' : n ? 'conforme' : 'en attente'}</span>`; }).join(' · ');
    const one = (n, x) => x ? `${n} : ${nf(x.verified)} minutes identiques à la bougie officielle, ${nf(x.shifted)} décalées au passage de la minute, ` +
      `${nf(x.repaired)} complétées après une coupure ; résidu cumulé ${sn(x.residual, 3)} ${coin()} sur ${nf(x.volume)} contrôlées` +
      `${x.mismatch ? ' : <b class="dn">anormal</b>' : ''}${x.live ? '' : ' · flux en direct pas encore reçu'}` : '';
    return card('CVD exact · transaction par transaction', `<table class="qtab">${head}${rows}</table>` + chart(c.series) +
      `<p class="small">Contrôle contre les bougies officielles : ${okLine}</p>` +
      (it.perp && it.perp.last ? `<p class="small dn">Dernier écart : ${esc(it.perp.last)}</p>` : '') + help(
      `<p class="small">Delta = achats agressifs − ventes agressives ; le pourcentage est sa part du volume. « ≈ » : fenêtre couverte à moins de 90 %.</p>` +
      `<p class="small">Contrôle d'intégrité (toutes les 5 minutes). ${one('Perpétuels', it.perp)}.<br>${one('Comptant', it.spot)}.</p>` +
      `<p class="muted small">Une transaction agrégée de Binance ne porte qu'une heure pour toutes ses exécutions : quelques-unes sont rangées dans la minute voisine de celle de la bougie officielle. Le total reste exact ; un résidu qui grandit signalerait des transactions manquantes. Les minutes fermées affichées sont celles des bougies officielles.</p>`));
  }

  function venuesCard(d) {
    const v = d.venues;
    if (!v) return '';
    const w = v[vwin] || v['1h'];
    const btn = ['5m', '1h', '4h'].map(k => `<button data-qv="${k}" class="${k === vwin ? 'on' : ''}">${WLAB[k]}</button>`).join('');
    const rows = (w.venues || []).map(x => `<tr><td>${esc(x.name)}</td><td class="up">${usd(x.buyUsd)}</td><td class="dn">${usd(x.sellUsd)}</td>` +
      `<td class="${cls(x.deltaUsd)}"><b>${susd(x.deltaUsd)}</b></td><td class="${cls(x.imb)}">${pct(x.imb)}</td></tr>`).join('');
    return card('CVD par bourse · BTC, en dollars', `<div class="qseg">${btn}</div>` +
      (rows ? `<table class="qtab"><tr><th>Bourse</th><th>Achats</th><th>Ventes</th><th>Net</th><th>Part</th></tr>${rows}` +
        `<tr class="qtot"><td>Total</td><td class="up">${usd(w.buyUsd)}</td><td class="dn">${usd(w.sellUsd)}</td><td class="${cls(w.deltaUsd)}"><b>${susd(w.deltaUsd)}</b></td><td class="${cls(w.imb)}">${pct(w.imb)}</td></tr></table>`
        : bad('aucune transaction reçue')) +
      `<p class="muted small">Compté depuis ${v.since ? DM.format(v.since) : 'le démarrage'} (rien n'est enregistré terminal éteint).</p>`);
  }

  // ---------- signaux ----------
  function regimeCard(d) {
    const rows = ['15m', '1h', '4h'].map(k => {
      const r = d.regime && d.regime[k];
      if (!r) return '';
      if (r.error) return `<div class="qreg"><span class="qtag">${WLAB[k]}</span><span class="muted small">${esc(r.error)}</span></div>`;
      const i = r.inputs || {};
      const chips = [['prix', i.dp, 2], ['intérêt ouvert', i.doi, 2], ['perpétuels', i.perp, 1], ['comptant', i.spot, 1]]
        .map(([n, v, dec]) => `<span class="qchip ${cls(v)}">${n} ${v == null ? '—' : pct(v, dec)}</span>`).join('');
      const extra = [];
      if ((r.tags || []).length > 1) extra.push('aussi : ' + r.tags.slice(1).join(', ').replace(/_/g, ' '));
      if ((r.missing || []).length) extra.push('non mesuré : ' + r.missing.join(', '));
      if (r.cover && (r.cover.perp < 0.9 || r.cover.spot < 0.9)) extra.push(`fenêtre incomplète (perpétuels ${nf(r.cover.perp * 100)} %, comptant ${nf(r.cover.spot * 100)} %)`);
      return `<div class="qreg"><div class="qregh"><span class="qtag">${WLAB[k]}</span><b class="${bcls(r.bias)}">${esc(r.label)}</b>` +
        `<span class="qmeter" title="force ${nf(r.score * 100)} %"><i class="${bcls(r.bias)}" style="width:${Math.min(100, r.score * 100).toFixed(0)}%"></i></span></div>` +
        `<div class="qchips">${chips}</div>${(r.notes || []).length ? `<div class="small">${esc(r.notes.join(' ; '))}</div>` : ''}` +
        `${extra.length ? `<div class="muted small">${esc(extra.join(' · '))}</div>` : ''}</div>`;
    }).join('');
    return card('Régime de marché · 15 min, 1 h, 4 h', rows || bad('pas encore de mesure'));
  }

  function signalsCard(d) {
    const c = d.cvd || {};
    const dv = (c.divergences || []).map(x => `<li><span class="${x.side === 'bull' ? 'up' : 'dn'}">●</span> ${esc(x.text)}. <span class="muted">` +
      `${x.market === 'perp' ? 'Perpétuels' : 'Comptant'}, pivots ${HM.format(x.t1)} (${px(x.p1)}) et ${HM.format(x.t2)} (${px(x.p2)}), connue à ${HM.format(x.known)}</span></li>`);
    const ab = (c.absorptions || []).map(x => `<li><span class="${x.side === 'bull' ? 'up' : 'dn'}">●</span> ${HM.format(x.t)} · ${esc(x.text)} ` +
      `<span class="muted">(${x.market === 'perp' ? 'perpétuels' : 'comptant'}, delta ${sn(x.delta, 1)} ${coin()} = ${nf(x.imb * 100)} % du volume, ${nf(x.volRatio, 1)} fois le volume habituel, prix ${px(x.price)})</span></li>`);
    const fold = (items, none) => { if (!items.length) return `<ul class="qlist"><li class="muted">${none}</li></ul>`;
      const more = items.length > 4 ? `<details class="qmore"><summary>${items.length - 4} plus ancienne${items.length > 5 ? 's' : ''}</summary><ul class="qlist">${items.slice(4).join('')}</ul></details>` : '';
      return `<ul class="qlist">${items.slice(0, 4).join('')}</ul>${more}`; };
    return card('Divergences et absorptions',
      `<div class="qsub">Divergences prix / CVD · barres de 5 min, 24 h</div>${fold(dv, 'aucune')}` +
      `<div class="qsub">Absorptions · barres d'1 min, 6 h</div>${fold(ab, 'aucune')}` +
      help(`<p class="muted small">Une divergence n'apparaît qu'après la confirmation du second pivot (3 barres) : elle n'est jamais dessinée en avance. Une absorption est une minute de gros volume très déséquilibrée où le prix ne suit pas.</p>`));
  }

  // ---------- liquidité ----------
  function bookCard(d) {
    const b = d.book;
    if (!b || b.error) return card('Carnet d\'ordres', bad(b ? b.error : 'indisponible'));
    const bar = (k, lab) => { const v = b.obi[k]; const w = Math.min(50, Math.abs(v) * 50);
      return `<div class="qobi"><span>${lab}</span><div class="qobar"><i class="${v >= 0 ? 'up' : 'dn'}" style="width:${w.toFixed(1)}%;${v >= 0 ? 'left:50%' : `left:${(50 - w).toFixed(1)}%`}"></i></div>` +
        `<b class="${cls(v)}">${pct(v, 0)}</b><span class="muted small">${usd(b.depth[k].bid)} / ${usd(b.depth[k].ask)}</span></div>`; };
    const wl = side => (b.walls[side] || []).map(x => `<li><span class="${side === 'bid' ? 'up' : 'dn'}">${side === 'bid' ? 'achat' : 'vente'}</span> <b>${px(x.price)}</b> · ${usd(x.usd)} · ${nf(x.mult)} fois la médiane · à ${nf(x.dist * 100, 2)} %</li>`).join('');
    const ev = (b.events || []).slice(0, 6).map(e => `<li>${HM.format(e.t)} · mur ${e.side === 'bid' ? 'acheteur' : 'vendeur'} ${px(e.price)} (${usd(e.peak)}) <b>${esc(e.kind)}</b>` +
      ` <span class="muted">après ${nf(e.lifeMs / 1000)} s, ${usd(e.traded)} échangés dessus</span></li>`).join('');
    return card('Carnet d\'ordres · déséquilibre et murs', bar('0.001', '± 0,1 %') + bar('0.005', '± 0,5 %') + bar('0.01', '± 1 %') +
      `<div class="qsub">Murs dans ± 1 %</div><ul class="qlist">${wl('ask') + wl('bid') || '<li class="muted">aucun mur en ce moment</li>'}</ul>` +
      `<div class="qsub">Fin des murs suivis</div><ul class="qlist">${ev || '<li class="muted">aucun événement pour l\'instant</li>'}</ul>` +
      help(`<p class="small">+100 % = que des acheteurs en attente, −100 % = que des vendeurs ; un ordre proche du prix pèse plus qu'un ordre lointain. À droite : dollars en attente (achat / vente). Écart achat-vente : ${nf(b.spreadBps, 2)} point de base. Un mur fait au moins 8 fois la médiane des niveaux.</p>` +
      `<p class="muted small">« retiré » : disparu alors que le prix approchait, presque rien échangé dessus (possible ordre d'affichage, ce n'est qu'un indice). « exécuté » : réellement échangé. « absorbe » : toujours là après avoir été échangé plus que sa taille (ordre rechargé).</p>`));
  }

  function profileCard(d) {
    const p = d.profile;
    if (!p || p.error) return card('Profil de volume exact', bad(p ? p.error : 'indisponible'));
    const names = {day: 'Jour (UTC)', '24h': '24 heures', prevDay: 'Veille (UTC)'};
    const rows = Object.keys(names).map(k => { const w = p.windows[k]; if (!w) return '';
      if (w.error) return `<tr><td>${names[k]}</td><td class="muted qwrap" colspan="5">${esc(w.error)}</td></tr>`;
      return `<tr><td>${names[k]}${w.cover < 0.98 ? ' ≈' : ''}</td><td><b>${px(w.poc)}</b></td><td>${px(w.vah)}</td><td>${px(w.val)}</td><td>${nf(w.volume)}</td><td class="${cls(w.delta)}">${sn(w.delta)}</td></tr>`; }).join('');
    return card('Profil de volume exact', `<table class="qtab"><tr><th></th><th>POC</th><th>VAH</th><th>VAL</th><th>Volume</th><th>Delta</th></tr>${rows}</table>` +
      help(`<p class="muted small">Volume de chaque transaction réelle à son prix (lignes de ${nf(p.step, p.step < 1 ? 4 : 0)} $, pas de cotation ${p.tick}). Zone de valeur : 70 % du volume, par paires de lignes autour du POC. « ≈ » : période pas entièrement couverte par les transactions archivées.</p>`));
  }

  // ---------- dérivés ----------
  function derivsCard(d) {
    const x = d.derivs || {};
    const o = x.others || {};
    const line = (n, v) => v ? `<tr><td>${n}</td><td>${nf(v.oi)} ${coin()}</td><td>${usd(v.oiUsd)}</td><td class="${cls(v.funding)}">${pct(v.funding, 4)}</td></tr>` : `<tr><td>${n}</td><td class="muted" colspan="3">pas de données</td></tr>`;
    const bin = x.oi != null ? `<tr><td>Binance</td><td>${nf(x.oi)} ${coin()}</td><td>${x.mark ? usd(x.oi * x.mark) : '—'}</td><td class="${cls(x.funding)}">${pct(x.funding, 4)}</td></tr>` : `<tr><td>Binance</td><td class="muted" colspan="3">pas de données</td></tr>`;
    const chips = [['intérêt ouvert 1 h', x.oi1h], ['intérêt ouvert 24 h', x.oi24h]].map(([n, v]) => `<span class="qchip ${cls(v)}">${n} ${pct(v, 2)}</span>`).join('') +
      (x.longShare != null ? `<span class="qchip">${nf(x.longShare * 100, 1)} % des comptes longs</span>` : '') +
      (x.nextFunding ? `<span class="qchip">financement à ${HM.format(x.nextFunding)}</span>` : '');
    return card('Intérêt ouvert et financement', `<table class="qtab"><tr><th></th><th>Intérêt ouvert</th><th>En dollars</th><th>Financement / 8 h</th></tr>${bin}${line('Bybit', o.bybit)}${line('OKX', o.okx)}</table>` +
      `<div class="qchips">${chips}</div>`);
  }

  function optionsCard(d) {
    const o = d.options;
    if (!o) return '';
    if (o.error) return card('Options BTC · Deribit', bad(o.error));
    const g = o.gex || {};
    const sm = (o.smile || []).map(s => `<tr><td>${DAYF.format(s.expiry)}</td><td>${nf(s.days, s.days < 3 ? 1 : 0)} j</td><td>${s.atm == null ? '—' : nf(s.atm * 100, 1) + ' %'}</td>` +
      `<td class="${s.skew25 > 0 ? 'dn' : s.skew25 < 0 ? 'up' : ''}">${s.skew25 == null ? '—' : sn(s.skew25 * 100, 1)}</td><td>${s.fly25 == null ? '—' : sn(s.fly25 * 100, 1)}</td></tr>`).join('');
    const mp = (o.maxPain || []).map(m => `<tr><td>${DAYF.format(m.expiry)}</td><td>${nf(m.days, m.days < 3 ? 1 : 0)} j</td><td><b>${px(m.maxPain)}</b></td><td>${nf(m.calls)} / ${nf(m.puts)}</td><td>${m.putCall == null ? '—' : nf(m.putCall, 2)}</td></tr>`).join('');
    return card('Options BTC · Deribit', `<div class="qchips"><span class="qchip ${cls(g.total)}">gamma ${susd(g.total)} / 1 %</span><span class="qchip">bascule ${px(g.flip)}</span>` +
      `<span class="qchip">mur de calls ${px(g.callWall)}</span><span class="qchip">mur de puts ${px(g.putWall)}</span><span class="qchip">indice ${px(o.index)}</span></div>` +
      `<div class="qsub">Volatilité implicite et skew à 25 delta</div><table class="qtab"><tr><th>Échéance</th><th>Dans</th><th>Au prix</th><th>Skew</th><th>Butterfly</th></tr>${sm}</table>` +
      `<div class="qsub">Max pain et intérêt ouvert</div><table class="qtab"><tr><th>Échéance</th><th>Dans</th><th>Max pain</th><th>Calls / puts</th><th>Put / call</th></tr>${mp}</table>` +
      help(`<p class="muted small">Skew (put − call) positif : les puts de protection coûtent plus cher que les calls (crainte de baisse). Calls et puts en BTC. ${nf(o.n)} options lues, ${nf(o.withOi)} avec de l'intérêt ouvert · ${ago(d.now - o.t)}. Gamma : calls +, puts − (hypothèse habituelle sur les teneurs de marché, non observable). Sous la bascule du gamma, les teneurs de marché amplifient les mouvements ; au-dessus, ils les freinent.</p>`));
  }

  function chainCard(d) {
    const c = d.onchain;
    if (!c) return '';
    if (c.error) return card('Réseau Bitcoin', bad(c.error));
    const v = (x, f) => x && !x.error ? f(x) : `<span class="muted">${esc(x && x.error ? 'indisponible' : '—')}</span>`;
    const cm = c.coinmetrics && !c.coinmetrics.error ? c.coinmetrics : null;
    const L = cm ? cm.last : {}, Wk = cm && cm.weekAgo ? cm.weekAgo : {};
    const chg = k => L[k] != null && Wk[k] ? ` <span class="${cls(L[k] / Wk[k] - 1)} small">(${pct(L[k] / Wk[k] - 1)} en 7 j)</span>` : '';
    const rows = [
      ['MVRV', cm && L.CapMVRVCur != null ? `<b>${nf(L.CapMVRVCur, 3)}</b>` + chg('CapMVRVCur') : '<span class="muted">indisponible</span>'],
      ['Entrées sur les bourses (jour)', cm && L.FlowInExNtv != null ? nf(L.FlowInExNtv) + ' BTC' + chg('FlowInExNtv') : '<span class="muted">non fourni par l\'accès gratuit</span>'],
      ['Sorties des bourses (jour)', cm && L.FlowOutExNtv != null ? nf(L.FlowOutExNtv) + ' BTC' + chg('FlowOutExNtv') : '<span class="muted">non fourni par l\'accès gratuit</span>'],
      ['Adresses actives (jour)', cm && L.AdrActCnt != null ? nf(L.AdrActCnt) + chg('AdrActCnt') : '<span class="muted">indisponible</span>'],
      ['Transactions (jour)', cm && L.TxCnt != null ? nf(L.TxCnt) + chg('TxCnt') : '<span class="muted">indisponible</span>'],
      ['Frais conseillés', v(c.fees, f => `${nf(f.fastest)} sat/vB rapide · ${nf(f.hour)} en 1 heure · ${nf(f.economy)} économique`)],
      ['Transactions en attente', v(c.mempool, m => `${nf(m.count)} · ${nf(m.blocksToClear, 1)} blocs à vider`)],
      ['Puissance de calcul', v(c.hashrate, h => `${nf(h.hashrateEH)} EH/s`)],
      ['Difficulté', v(c.difficulty, x => `${sn(x.changePct, 2)} % dans ${nf(x.remainingBlocks)} blocs`)],
      ['Dernier bloc', v(typeof c.tip === 'number' ? {h: c.tip} : c.tip, t => nf(t.h))],
    ].map(([a, b]) => `<tr><td>${a}</td><td>${b}</td></tr>`).join('');
    return card('Réseau Bitcoin', `<table class="qtab qkv">${rows}</table>` +
      help(`<p class="muted small">MVRV : valeur de marché ÷ valeur réalisée (prix moyen d'acquisition des pièces) ; au-dessus de 1, le détenteur moyen est en gain. Sources : mempool.space et CoinMetrics (mesures quotidiennes, publiées avec un à deux jours de retard${cm ? ` ; dernier jour : ${DAYF.format(cm.t)}` : ''}).` +
      `${c.crossCheck && c.crossCheck.difficultyGapPct != null ? ` Difficulté recoupée avec blockchain.info : écart ${nf(c.crossCheck.difficultyGapPct, 4)} %.` : ''}</p>`));
  }

  function render() {
    if (!root) return;
    root.querySelector('.qttl').textContent = `Quant · ${coin()}`;
    const g = root.querySelector('.qgrid'), meta = root.querySelector('.qmeta'), top = root.querySelector('.qtop');
    if (!data || data.symbol !== LT.st.symbol) { meta.textContent = ''; top.innerHTML = ''; g.innerHTML = card('Moteur exact', bad(!data && err || 'Chargement…')); return; }
    meta.textContent = `mis à jour ${HM.format(data.now)}${err ? ' · ' + err : ''}` +
      (data.warming ? ' · démarrage du moteur : les premières mesures arrivent en quelques secondes, l\'historique de 24 heures en moins d\'une minute' : '');
    const open = new Set([...root.querySelectorAll('details.qhelp[open], details.qmore[open]')].map(e => e.closest('.qcard').querySelector('.qh').textContent + e.className));
    top.innerHTML = summary(data);
    const btc = data.options || data.onchain;
    g.innerHTML = sec('Flux d\'ordres') + spotPerpCard(data) + cvdCard(data) + venuesCard(data) +
      sec('Signaux') + regimeCard(data) + signalsCard(data) +
      sec('Liquidité') + bookCard(data) + profileCard(data) +
      sec('Dérivés') + derivsCard(data) + (btc ? optionsCard(data) : '') +
      (data.onchain ? sec('Réseau Bitcoin') + chainCard(data) : '');
    root.querySelectorAll('details.qhelp, details.qmore').forEach(e => { if (open.has(e.closest('.qcard').querySelector('.qh').textContent + e.className)) e.open = true; });
  }

  function show() { if (on) { load(); return; } on = true; render(); load(); timer = setInterval(load, 5000); }
  function hide() { on = false; if (timer) { clearInterval(timer); timer = null; } }
  return {init, show, hide};
})();
