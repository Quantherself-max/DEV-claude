// V45 : onglet Quant. Tout ce qui s'affiche ici vient de /api/quant (ingest/hub.py) : des sources publiques réelles lues en direct, calculées
// par le moteur exact (paquet quant : entiers et décimaux, aucun flottant dans les sommes). Une source qui ne répond pas affiche son erreur ;
// rien n'est jamais remplacé par une valeur fabriquée.
//   Régime de marché   prix + intérêt ouvert + financement + CVD des perpétuels + CVD du comptant, sur 15 minutes, 1 heure et 4 heures
//   CVD exact          transaction par transaction (côté de l'agresseur), contrôlé chaque minute contre la bougie officielle de Binance
// V45.1 : le moteur ne tourne que pendant que cet onglet est ouvert (il s'arrête 5 minutes après) : aucun effet sur le démarrage du terminal.
//   Divergences, absorptions, bourses (BTC), carnet (déséquilibre pondéré, murs, ordres retirés), profil de volume exact, dérivés,
//   options (volatilité, skew 25 delta, max pain, gamma), réseau Bitcoin, état de chaque source.
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
      `<span class="muted small">Données réelles uniquement · calculs exacts (entiers et décimaux)</span></div><div class="qgrid"></div>`;
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

  // ---------- cartes ----------
  function regimeCard(d) {
    const rows = ['15m', '1h', '4h'].map(k => {
      const r = d.regime && d.regime[k];
      if (!r) return '';
      if (r.error) return `<div class="qreg"><span class="qtag">${WLAB[k]}</span><span class="muted small">${esc(r.error)}</span></div>`;
      const i = r.inputs || {};
      const chips = [['prix', i.dp, 2], ['intérêt ouvert', i.doi, 2], ['perpétuels', i.perp, 1], ['comptant', i.spot, 1]]
        .map(([n, v, dec]) => `<span class="qchip ${cls(v)}">${n} ${v == null ? '—' : pct(v, dec)}</span>`).join('');
      const also = (r.tags || []).length > 1 ? `<div class="muted small">aussi : ${esc(r.tags.slice(1).join(', ').replace(/_/g, ' '))}</div>` : '';
      const miss = (r.missing || []).length ? `<div class="muted small">non mesuré : ${esc(r.missing.join(', '))}</div>` : '';
      const low = r.cover && (r.cover.perp < 0.9 || r.cover.spot < 0.9) ? `<div class="muted small">≈ fenêtre incomplète (perpétuels ${nf(r.cover.perp * 100)} %, comptant ${nf(r.cover.spot * 100)} %)</div>` : '';
      return `<div class="qreg"><span class="qtag">${WLAB[k]}</span><b class="${r.bias > 0 ? 'up' : r.bias < 0 ? 'dn' : ''}">${esc(r.label)}</b>` +
        `<span class="muted small"> · force ${nf(r.score * 100)} %</span><div class="qchips">${chips}</div>` +
        `${(r.notes || []).length ? `<div class="small">${esc(r.notes.join(' ; '))}</div>` : ''}${also}${miss}${low}</div>`;
    }).join('');
    return card('Régime de marché · prix + intérêt ouvert + financement + CVD', rows || bad('pas encore de mesure'));
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
    const one = (n, x) => x ? `${n} : ${nf(x.verified)} minutes identiques à la bougie officielle, ${nf(x.shifted)} décalées au passage de la minute, ` +
      `${nf(x.repaired)} complétées après une coupure ; résidu cumulé ${sn(x.residual, 3)} ${coin()} sur ${nf(x.volume)} contrôlées` +
      `${x.mismatch ? ' : <b class="dn">anormal</b>' : ''}${x.live ? '' : ' · flux en direct pas encore reçu'}` : '';
    return card('CVD exact · transaction par transaction', `<table class="qtab">${head}${rows}</table>` + chart(c.series) +
      `<p class="muted small">Delta = achats agressifs − ventes agressives ; le pourcentage est sa part du volume. « ≈ » : fenêtre couverte à moins de 90 %.</p>` +
      `<p class="small">Contrôle d'intégrité (toutes les 5 minutes). ${one('Perpétuels', it.perp)}.<br>${one('Comptant', it.spot)}.</p>` +
      `<p class="muted small">Une transaction agrégée de Binance ne porte qu'une heure pour toutes ses exécutions : quelques-unes sont rangées dans la minute voisine de celle de la bougie officielle. Le total reste exact ; un résidu qui grandit signalerait des transactions manquantes. Les minutes fermées affichées sont celles des bougies officielles.</p>` +
      (it.perp && it.perp.last ? `<p class="small dn">Dernier écart : ${esc(it.perp.last)}</p>` : ''));
  }

  function signalsCard(d) {
    const c = d.cvd || {};
    const dv = (c.divergences || []).map(x => `<li><span class="${x.side === 'bull' ? 'up' : 'dn'}">●</span> ${esc(x.text)}. <span class="muted">` +
      `${x.market === 'perp' ? 'Perpétuels' : 'Comptant'}, pivots ${HM.format(x.t1)} (${px(x.p1)}) et ${HM.format(x.t2)} (${px(x.p2)}), connue à ${HM.format(x.known)}</span></li>`).join('');
    const ab = (c.absorptions || []).map(x => `<li><span class="${x.side === 'bull' ? 'up' : 'dn'}">●</span> ${HM.format(x.t)} · ${esc(x.text)} ` +
      `<span class="muted">(${x.market === 'perp' ? 'perpétuels' : 'comptant'}, delta ${sn(x.delta, 1)} ${coin()} = ${nf(x.imb * 100)} % du volume, ${nf(x.volRatio, 1)} fois le volume habituel, prix ${px(x.price)})</span></li>`).join('');
    return card('Divergences prix / CVD (barres de 5 min) et absorptions (barres d\'1 min)',
      `<div class="qsub">Divergences</div><ul class="qlist">${dv || '<li class="muted">aucune sur les dernières 24 heures</li>'}</ul>` +
      `<div class="qsub">Absorptions</div><ul class="qlist">${ab || '<li class="muted">aucune sur les 6 dernières heures</li>'}</ul>` +
      `<p class="muted small">Une divergence n'apparaît qu'après la confirmation du second pivot (3 barres) : elle n'est jamais dessinée en avance.</p>`);
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
      `<p class="muted small">Ordres au marché de chaque bourse, comptés depuis ${v.since ? DM.format(v.since) : 'le démarrage'} (rien n'est enregistré terminal éteint).</p>`);
  }

  function bookCard(d) {
    const b = d.book;
    if (!b || b.error) return card('Carnet d\'ordres', bad(b ? b.error : 'indisponible'));
    const bar = (k, lab) => { const v = b.obi[k]; const w = Math.min(50, Math.abs(v) * 50);
      return `<div class="qobi"><span>${lab}</span><div class="qobar"><i class="${v >= 0 ? 'up' : 'dn'}" style="width:${w.toFixed(1)}%;${v >= 0 ? 'left:50%' : `left:${(50 - w).toFixed(1)}%`}"></i></div>` +
        `<b class="${cls(v)}">${pct(v, 0)}</b><span class="muted small">${usd(b.depth[k].bid)} / ${usd(b.depth[k].ask)}</span></div>`; };
    const wl = side => (b.walls[side] || []).map(x => `<li><span class="${side === 'bid' ? 'up' : 'dn'}">${side === 'bid' ? 'achat' : 'vente'}</span> ${px(x.price)} · ${usd(x.usd)} · ${nf(x.mult)} fois la médiane · à ${nf(x.dist * 100, 2)} %</li>`).join('');
    const ev = (b.events || []).map(e => `<li>${HM.format(e.t)} · mur ${e.side === 'bid' ? 'acheteur' : 'vendeur'} ${px(e.price)} (${usd(e.peak)}) <b>${esc(e.kind)}</b>` +
      ` <span class="muted">après ${nf(e.lifeMs / 1000)} s, ${usd(e.traded)} échangés dessus</span></li>`).join('');
    return card('Carnet d\'ordres · déséquilibre pondéré par la distance', bar('0.001', '± 0,1 %') + bar('0.005', '± 0,5 %') + bar('0.01', '± 1 %') +
      `<p class="muted small">+100 % = que des acheteurs en attente, −100 % = que des vendeurs. Un ordre proche du prix pèse plus qu'un ordre lointain. À droite : dollars en attente (achat / vente). Écart achat-vente : ${nf(b.spreadBps, 2)} point de base.</p>` +
      `<div class="qsub">Murs (au moins 8 fois la médiane des niveaux, dans ± 1 %)</div><ul class="qlist">${wl('ask') + wl('bid') || '<li class="muted">aucun mur en ce moment</li>'}</ul>` +
      `<div class="qsub">Fin des murs suivis</div><ul class="qlist">${ev || '<li class="muted">aucun événement pour l\'instant</li>'}</ul>` +
      `<p class="muted small">« retiré » : disparu alors que le prix approchait, presque rien échangé dessus (possible ordre d'affichage, ce n'est qu'un indice). « exécuté » : réellement échangé. « absorbe » : toujours là après avoir été échangé plus que sa taille (ordre rechargé).</p>`);
  }

  function profileCard(d) {
    const p = d.profile;
    if (!p || p.error) return card('Profil de volume exact', bad(p ? p.error : 'indisponible'));
    const names = {day: 'Jour (UTC)', '24h': '24 heures', prevDay: 'Veille (UTC)'};
    const rows = Object.keys(names).map(k => { const w = p.windows[k]; if (!w) return '';
      if (w.error) return `<tr><td>${names[k]}</td><td class="muted qwrap" colspan="5">${esc(w.error)}</td></tr>`;
      return `<tr><td>${names[k]}${w.cover < 0.98 ? ' ≈' : ''}</td><td><b>${px(w.poc)}</b></td><td>${px(w.vah)}</td><td>${px(w.val)}</td><td>${nf(w.volume)}</td><td class="${cls(w.delta)}">${sn(w.delta)}</td></tr>`; }).join('');
    return card('Profil de volume exact · transactions réelles', `<table class="qtab"><tr><th></th><th>POC</th><th>VAH</th><th>VAL</th><th>Volume</th><th>Delta</th></tr>${rows}</table>` +
      `<p class="muted small">Volume de chaque transaction à son prix (lignes de ${nf(p.step, p.step < 1 ? 4 : 0)} $, pas de cotation ${p.tick}). Zone de valeur : 70 % du volume, par paires de lignes autour du POC. « ≈ » : période pas entièrement couverte par les transactions archivées.</p>`);
  }

  function derivsCard(d) {
    const x = d.derivs || {};
    const o = x.others || {};
    const line = (n, v) => v ? `<tr><td>${n}</td><td>${nf(v.oi)} ${coin()}</td><td>${usd(v.oiUsd)}</td><td class="${cls(v.funding)}">${pct(v.funding, 4)}</td></tr>` : `<tr><td>${n}</td><td class="muted" colspan="3">pas de données</td></tr>`;
    const bin = x.oi != null ? `<tr><td>Binance</td><td>${nf(x.oi)} ${coin()}</td><td>${x.mark ? usd(x.oi * x.mark) : '—'}</td><td class="${cls(x.funding)}">${pct(x.funding, 4)}</td></tr>` : `<tr><td>Binance</td><td class="muted" colspan="3">pas de données</td></tr>`;
    return card('Dérivés · intérêt ouvert et financement', `<table class="qtab"><tr><th></th><th>Intérêt ouvert</th><th>En dollars</th><th>Financement / 8 h</th></tr>${bin}${line('Bybit', o.bybit)}${line('OKX', o.okx)}</table>` +
      `<p class="small">Binance : intérêt ouvert ${pct(x.oi1h, 2)} sur 1 heure, ${pct(x.oi24h, 2)} sur 24 heures` +
      `${x.longShare != null ? ` · ${nf(x.longShare * 100, 1)} % des comptes sont longs` : ''}${x.nextFunding ? ` · prochaine échéance de financement ${HM.format(x.nextFunding)}` : ''}.</p>`);
  }

  function optionsCard(d) {
    const o = d.options;
    if (!o) return '';
    if (o.error) return card('Options BTC · Deribit', bad(o.error));
    const g = o.gex || {};
    const sm = (o.smile || []).map(s => `<tr><td>${DAYF.format(s.expiry)}</td><td>${nf(s.days, s.days < 3 ? 1 : 0)} j</td><td>${s.atm == null ? '—' : nf(s.atm * 100, 1) + ' %'}</td>` +
      `<td class="${s.skew25 > 0 ? 'dn' : s.skew25 < 0 ? 'up' : ''}">${s.skew25 == null ? '—' : sn(s.skew25 * 100, 1)}</td><td>${s.fly25 == null ? '—' : sn(s.fly25 * 100, 1)}</td></tr>`).join('');
    const mp = (o.maxPain || []).map(m => `<tr><td>${DAYF.format(m.expiry)}</td><td>${nf(m.days, m.days < 3 ? 1 : 0)} j</td><td><b>${px(m.maxPain)}</b></td><td>${nf(m.calls)} / ${nf(m.puts)}</td><td>${m.putCall == null ? '—' : nf(m.putCall, 2)}</td></tr>`).join('');
    return card('Options BTC · Deribit (chaîne complète)', `<p class="small">Exposition gamma totale <b class="${cls(g.total)}">${susd(g.total)}</b> pour 1 % de mouvement` +
      ` · bascule du gamma <b>${px(g.flip)}</b> · mur de calls <b>${px(g.callWall)}</b> · mur de puts <b>${px(g.putWall)}</b> · indice ${px(o.index)}</p>` +
      `<div class="qsub">Volatilité implicite et skew à 25 delta</div><table class="qtab"><tr><th>Échéance</th><th>Dans</th><th>Au prix</th><th>Skew (put − call)</th><th>Butterfly</th></tr>${sm}</table>` +
      `<div class="qsub">Max pain et intérêt ouvert</div><table class="qtab"><tr><th>Échéance</th><th>Dans</th><th>Max pain</th><th>Calls / puts (BTC)</th><th>Put / call</th></tr>${mp}</table>` +
      `<p class="muted small">Skew positif : les puts de protection coûtent plus cher que les calls (crainte de baisse). ${nf(o.n)} options lues, ${nf(o.withOi)} avec de l'intérêt ouvert · ${ago(d.now - o.t)}. Gamma : calls +, puts − (hypothèse habituelle sur les teneurs de marché, non observable).</p>`);
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
      ['Frais conseillés', v(c.fees, f => `${nf(f.fastest)} sat/vB (rapide) · ${nf(f.hour)} sat/vB (1 heure) · ${nf(f.economy)} sat/vB (économique)`)],
      ['Transactions en attente', v(c.mempool, m => `${nf(m.count)} · ${nf(m.blocksToClear, 1)} blocs à vider · ${nf(m.totalFeeSat / 1e8, 3)} BTC de frais`)],
      ['Puissance de calcul', v(c.hashrate, h => `${nf(h.hashrateEH)} EH/s`)],
      ['Difficulté', v(c.difficulty, x => `prochain ajustement ${sn(x.changePct, 2)} % dans ${nf(x.remainingBlocks)} blocs (${nf(x.progressPct, 1)} % de la période)`)],
      ['Dernier bloc', v(typeof c.tip === 'number' ? {h: c.tip} : c.tip, t => nf(t.h))],
      ['Adresses actives (jour)', cm && L.AdrActCnt != null ? nf(L.AdrActCnt) + chg('AdrActCnt') : '<span class="muted">indisponible</span>'],
      ['MVRV', cm && L.CapMVRVCur != null ? `<b>${nf(L.CapMVRVCur, 3)}</b>` + chg('CapMVRVCur') : '<span class="muted">indisponible</span>'],
      ['Entrées sur les bourses (jour)', cm && L.FlowInExNtv != null ? nf(L.FlowInExNtv) + ' BTC' + chg('FlowInExNtv') : '<span class="muted">non fourni par l\'accès gratuit</span>'],
      ['Sorties des bourses (jour)', cm && L.FlowOutExNtv != null ? nf(L.FlowOutExNtv) + ' BTC' + chg('FlowOutExNtv') : '<span class="muted">non fourni par l\'accès gratuit</span>'],
      ['Transactions (jour)', cm && L.TxCnt != null ? nf(L.TxCnt) + chg('TxCnt') : '<span class="muted">indisponible</span>'],
    ].map(([a, b]) => `<tr><td>${a}</td><td>${b}</td></tr>`).join('');
    return card('Réseau Bitcoin · mempool.space et CoinMetrics', `<table class="qtab qkv">${rows}</table>` +
      `<p class="muted small">MVRV : valeur de marché ÷ valeur réalisée (prix moyen d'acquisition des pièces) ; au-dessus de 1, le détenteur moyen est en gain. Mesures CoinMetrics : quotidiennes, publiées avec un à deux jours de retard${cm ? ` (dernier jour : ${DAYF.format(cm.t)})` : ''}.` +
      `${c.crossCheck && c.crossCheck.difficultyGapPct != null ? ` Difficulté recoupée avec blockchain.info : écart ${nf(c.crossCheck.difficultyGapPct, 4)} %.` : ''}</p>`);
  }

  function sourcesCard(d) {
    const s = d.sources || {};
    const http = (s.http || []).map(h => `<tr><td>${esc(h.name)}</td><td class="${h.error ? 'dn' : h.lastOk ? 'up' : 'muted'}">${h.error ? 'en erreur' : h.lastOk ? 'répond' : 'pas encore appelée'}</td>` +
      `<td>${h.latencyMs == null ? '—' : nf(h.latencyMs) + ' ms'}</td><td>${nf(h.calls)} / ${nf(h.errors)}</td><td>${h.usedWeight != null && h.weightLimit ? nf(h.usedWeight / h.weightLimit * 100) + ' %' : '—'}</td></tr>` +
      (h.error ? `<tr><td colspan="5" class="muted small qwrap">${esc(h.error)}</td></tr>` : '')).join('');
    const ws = Object.entries(s.ws || {}).map(([k, c]) => `<tr><td>${esc(k)}</td><td class="${c.connected ? 'up' : 'dn'}">${c.connected ? 'connecté' : 'coupé'}</td>` +
      `<td>${c.lastMsgAge == null ? '—' : nf(c.lastMsgAge, 0) + ' s'}</td><td>${nf(c.connects)}</td><td>${nf(c.gaps)}</td></tr>` +
      (!c.connected && c.error ? `<tr><td colspan="5" class="muted small qwrap">${esc(c.error)} · nouvel essai dans ${nf(c.nextWait, 0)} s</td></tr>` : '')).join('');
    const grp = {};                                                       // une même erreur (une bourse injoignable) n'est écrite qu'une fois
    Object.entries(s.errors || {}).forEach(([k, v]) => { (grp[v] = grp[v] || []).push(k); });
    const er = Object.entries(grp).map(([v, ks]) => `<li><b>${esc(ks.join(', '))}</b> : ${esc(v)}</li>`).join('');
    return card('État des sources', `<div class="qsub">Adresses publiques (REST)</div><table class="qtab"><tr><th>Source</th><th>État</th><th>Latence</th><th>Appels / erreurs</th><th>Quota utilisé</th></tr>${http}</table>` +
      `<div class="qsub">Flux en direct (WebSocket)</div><table class="qtab"><tr><th>Flux</th><th>État</th><th>Dernier message</th><th>Connexions</th><th>Coupures</th></tr>${ws || '<tr><td class="muted" colspan="5">aucun flux</td></tr>'}</table>` +
      (er ? `<div class="qsub">Erreurs en cours</div><ul class="qlist">${er}</ul>` : ''), 'qwide');
  }

  function render() {
    if (!root) return;
    root.querySelector('.qttl').textContent = `Quant · ${coin()}`;
    const g = root.querySelector('.qgrid'), meta = root.querySelector('.qmeta');
    if (!data) { meta.textContent = ''; g.innerHTML = card('Moteur exact', bad(err || 'Chargement…')); return; }
    if (data.symbol !== LT.st.symbol) { g.innerHTML = card('Moteur exact', bad('Chargement…')); return; }
    const last = data.cvd && data.cvd.last && data.cvd.last.perp;
    meta.textContent = `${last ? 'dernier prix ' + px(last) + ' · ' : ''}mis à jour ${HM.format(data.now)}${err ? ' · ' + err : ''}` +
      (data.warming ? ' · démarrage du moteur : les premières mesures arrivent en quelques secondes, l\'historique de 24 heures en moins d\'une minute' : '');
    g.innerHTML = regimeCard(data) + cvdCard(data) + signalsCard(data) + venuesCard(data) + bookCard(data) + profileCard(data) + derivsCard(data) +
      optionsCard(data) + chainCard(data) + sourcesCard(data);
  }

  function show() { if (on) { load(); return; } on = true; render(); load(); timer = setInterval(load, 5000); }
  function hide() { on = false; if (timer) { clearInterval(timer); timer = null; } }
  return {init, show, hide};
})();
