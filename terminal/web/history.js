// Historique (V13, refait en V24) : chaque idée et alerte envoyée avec son récit complet (pourquoi, plan, déroulé, résultat expliqué,
// ce qu'on peut en retenir), un graphique du trajet du prix autour de l'idée, les statistiques par catégorie, ce que le terminal annonçait
// face à ce qui est arrivé, et la lecture quotidienne du terminal avec ce que le prix a fait ensuite.
const History = (() => {
  'use strict';
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const NS = 'http://www.w3.org/2000/svg';
  let LT = null, data = null, err = null;
  const filt = {type: 'all', pair: 'all', res: 'all'};
  let group = 'pair';
  const openIds = new Set(), details = {};
  const RISK_KEY = 'lt.histRiskUsd';
  let riskUsd = 0;
  try { riskUsd = Math.max(0, parseFloat(localStorage.getItem(RISK_KEY)) || 0); } catch (e) { riskUsd = 0; }

  const num = (v, d = 1) => v == null || isNaN(v) ? '-' : Number(v).toFixed(d).replace('.', ',');
  const sg = (v, d = 2, u = '') => v == null || isNaN(v) ? '-' : (Math.abs(v) < 0.5 * Math.pow(10, -d) ? '0' : (v > 0 ? '+' : '−') + Math.abs(v).toFixed(d).replace('.', ',')) + u;
  const pct = v => v == null ? '-' : Math.round(v * 100) + ' %';
  const px = v => v == null ? '-' : LT.fmtP(v);
  const PARIS = new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
  const PDAY = new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', day: '2-digit', month: '2-digit'});
  const PHOUR = new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', hour: '2-digit', minute: '2-digit'});
  const when = ms => ms ? PARIS.format(new Date(ms)).replace(',', '').replace(':', 'h') : '-';
  const SIDE = {long: 'Achat', short: 'Vente'};
  const KIND = {rebond: 'rebond sur une zone', reprise: 'reprise après une mèche'};
  const sym = s => String(s || '').replace('USDT', '');
  const cls = v => v > 0 ? 'up' : v < 0 ? 'dn' : '';
  const money = r => riskUsd > 0 && r != null ? (r > 0 ? '+' : r < 0 ? '−' : '') + Math.round(Math.abs(r * riskUsd)).toLocaleString('fr-FR') + ' $' : '';
  function dur(ms) {
    if (ms == null) return '-';
    const m = Math.max(0, Math.round(ms / 60000));
    if (m < 60) return m + ' minute' + (m > 1 ? 's' : '');
    const h = Math.floor(m / 60), mm = m % 60;
    if (h < 24) return h + ' heure' + (h > 1 ? 's' : '') + (mm ? ' et ' + mm + ' minute' + (mm > 1 ? 's' : '') : '');
    const d = Math.floor(h / 24), hh = h % 24;
    return d + ' jour' + (d > 1 ? 's' : '') + (hh ? ' et ' + hh + ' heure' + (hh > 1 ? 's' : '') : '');
  }

  function init(lt) {
    LT = lt;
    const root = document.getElementById('histBox');
    if (!root) return;
    root.addEventListener('click', e => {
      const b = e.target.closest('[data-hf],[data-hp],[data-hr],[data-hg]');
      if (b) {
        if (b.dataset.hf) filt.type = b.dataset.hf;
        if (b.dataset.hp) filt.pair = b.dataset.hp;
        if (b.dataset.hr) filt.res = b.dataset.hr;
        if (b.dataset.hg) group = b.dataset.hg;
        if (b.dataset.hg) renderGroups(); else renderTable();
        return;
      }
      if (e.target.closest('details, a, input, button')) return;
      const row = e.target.closest('tr[data-tid]');
      if (row) toggle(row.dataset.tid);
    });
    let rz = null;
    window.addEventListener('resize', () => {
      clearTimeout(rz);
      rz = setTimeout(() => { if (!openIds.size || !document.getElementById('histTable')) return; fitFiches(); openIds.forEach(id => { if (details[id] && details[id].bars) drawTrade(id); }); }, 200);
    });
    root.addEventListener('change', e => {
      if (e.target.id !== 'histRisk') return;
      riskUsd = Math.max(0, parseFloat(String(e.target.value).replace(',', '.')) || 0);
      try { localStorage.setItem(RISK_KEY, String(riskUsd)); } catch (x) { /* navigateur sans stockage : reglage oublie a la fermeture */ }
      refreshMoney();                                    // jamais tout redessiner ici : le champ de saisie doit rester en place
    });
  }
  async function show() {
    try { data = await LT.api('/api/history'); err = null; } catch (e) { err = e.message; }
    render();
  }

  // ---------- synthese ----------
  function refreshMoney() {
    if (!data || !data.summary) return;
    const k = document.getElementById('histKpis'), n = document.getElementById('histCurveNote');
    if (k) k.innerHTML = kpis(data);
    if (n) n.innerHTML = curveNote(data);
    renderTable();
    renderGroups();
  }
  function head(d) {
    return `<section class="card"><h2>Historique du terminal <small>${d.source === 'simulated' ? 'données simulées' : 'Binance'} · heure de Paris</small></h2>
      <div class="biasline">${LT.biasHtml(d.bias)}</div>
      <div class="hverdict ${d.summary.decided >= 30 && d.summary.avgLo > 0 ? 'ok' : d.summary.decided >= 30 && d.summary.avgHi < 0 ? 'bad' : ''}">${esc(d.summary.verdict || '')}</div>
      <div class="kpis" id="histKpis">${kpis(d)}</div>
      <div class="hrisk"><label>Traduire en dollars : je risque <input id="histRisk" type="number" min="0" step="5" value="${riskUsd || ''}" placeholder="montant"> $ par idée</label>
        <span class="muted small">la somme perdue si le stop est touché. Exemple : avec 50 $, une idée à +1,5 fois le risque rapporte 75 $. Réglage gardé dans ce navigateur seulement.</span></div></section>`;
  }
  function kpis(d) {
    const s = d.summary || {}, al = s.alerts || {n: 0, right: 0, wrong: 0};
    const ts = (d.readings.trendScore || {})['72'] || {};
    const kp = (t, big, sub, c = '') => `<div class="kpi"><small>${t}</small><b class="${c}">${big}</b><span>${sub}</span></div>`;
    const m = money(s.r);
    const pend = d.trades.filter(t => t.mode !== 'alerte' && t.status === 'pending').length;
    return `${kp('Idées envoyées', s.n || 0, `${s.filled || 0} exécutées${s.n ? ' (' + pct(s.fillRate) + ')' : ''} · ${s.open || 0} en cours${pend ? ' dont ' + pend + ' en attente' : ''}`)}
        ${kp('Idées gagnantes', s.decided ? pct(s.winRate) : '-', s.decided ? `${s.wins} sur ${s.decided} terminées (objectif 1 atteint avant le stop)` : 'aucune idée terminée')}
        ${kp('Résultat total', s.decided ? sg(s.r) : '-', s.decided ? `fois le risque pris${m ? ' = <b class="' + cls(s.r) + '">' + m + '</b>' : ''} · ${sg(s.avg)} en moyenne par idée` : 'en fois le risque pris', cls(s.r))}
        ${kp('Pire passage', s.decided ? (s.maxDrawdown > 0 ? '−' + num(s.maxDrawdown, 2) : '0') : '-', s.decided ? `fois le risque perdu du plus haut au plus bas de la courbe${riskUsd > 0 && s.maxDrawdown > 0 ? ' (' + money(-s.maxDrawdown) + ')' : ''} · plus longue série de pertes : ${s.lossStreak}` : 'du plus haut au plus bas de la courbe', s.maxDrawdown > 0 ? 'dn' : '')}
        ${kp('Durée moyenne', s.avgHold != null ? dur(s.avgHold) : '-', `en position (de l'entrée à la sortie)${s.avgFill != null ? ' · ordre exécuté ' + dur(s.avgFill) + ' après l\'envoi en moyenne' : ''}`)}
        ${kp(d.direction === 'short' ? 'Alertes pour tes shorts' : 'Alertes pour tes longs', al.n, al.right + al.wrong ? `${al.right} justes, ${al.wrong} fausses` : 'pas encore tranchées')}
        ${kp('Tendance de fond', ts.n ? pct(ts.rate) : '-', ts.n ? `le prix est allé dans son sens à 3 jours (${ts.right} fois sur ${ts.n})` : 'pas encore assez de lectures')}`;
  }

  // ---------- courbe ----------
  function curve(d) {
    const c = (d.summary || {}).curve || [];
    return c.length >= 2 && typeof Charts !== 'undefined' ? `<section class="card"><h2>Résultat cumulé des idées <small>en fois le risque, idée après idée (sorties dans l'ordre)</small></h2>
      <div id="histCurve" class="svgbox"></div><div class="muted small" id="histCurveNote">${curveNote(d)}</div></section>` : '';
  }
  const curveNote = d => 'Chaque point est une idée terminée. Les idées non exécutées et les positions encore ouvertes n\'y sont pas.' +
    (riskUsd > 0 ? ` Avec ${riskUsd.toLocaleString('fr-FR')} $ risqués par idée : ${money(d.summary.r)} au total.` : '');
  function drawCurve(d) {
    const el = document.getElementById('histCurve');
    if (!el) return;
    const c = d.summary.curve, ideas = Object.fromEntries(d.trades.map(t => [t.id, t]));
    const first = ideas[c[0].id];
    const pts = [[Math.min(c[0].t, first ? first.created : c[0].t) - 1, 0]].concat(c.map(p => [p.t, p.cum]));
    const fmtX = t => PDAY.format(new Date(t));
    Charts.line(el, {series: [{name: 'Résultat cumulé', color: '#3987e5', pts, area: true}], height: 190, yFmt: v => sg(v, 1),
      xFmt: fmtX, xTicks: Math.min(5, pts.length - 1), ref: {y: 0, label: '0'}});
  }

  // ---------- tableau des idees ----------
  function outcomeOf(t) {
    if (t.mode === 'alerte') return 'alert';
    return t.outcome;
  }
  function filtered(d) {
    return d.trades.filter(t => {
      if (filt.type === 'ideas' && t.mode === 'alerte') return false;
      if (filt.type === 'alerts' && t.mode !== 'alerte') return false;
      if (filt.pair !== 'all' && sym(t.symbol) !== filt.pair) return false;
      const o = outcomeOf(t);
      if (filt.res === 'win') return o === 'win' || (o === 'alert' && t.verdict === true);
      if (filt.res === 'loss') return o === 'loss' || (o === 'alert' && t.verdict === false);
      if (filt.res === 'none') return o === 'unfilled' || o === 'uncounted';
      if (filt.res === 'open') return o === 'open' || (o === 'alert' && t.verdict == null);
      return true;
    });
  }
  function ladder(t) {
    if (t.mode === 'alerte') return '';
    if (!t.filledAt) {
      if (t.status === 'pending') return '<span class="muted small">ordre en attente</span>';
      if (t.near) {
        const gap = Math.abs((t.near.p / t.entry - 1) * 100);
        const touched = t.side === 'long' ? t.near.p <= t.entry : t.near.p >= t.entry;
        return `<span class="muted small">non exécutée${touched ? '' : ' · au plus près à ' + num(gap, 2) + ' % de l\'entrée'}</span>`;
      }
      return '<span class="muted small">non exécutée</span>';
    }
    const rr1 = t.rr1, rr2 = t.rr2 || null, rb = t.rBest, rw = t.rWorst;
    const rres = t.r != null ? t.r : t.rNow;
    let lo = Math.min(-1.15, rw != null ? rw - 0.1 : -1.15), hi = Math.max((rr2 || rr1) + 0.25, rb != null ? rb + 0.1 : 0);
    lo = Math.max(lo, -3); hi = Math.min(hi, 10);
    const X = v => (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo) * 100;
    let h = '<div class="ladder">';
    if (rw != null && rw < 0) h += `<i class="lz dn" style="left:${X(rw)}%;width:${X(0) - X(rw)}%"></i>`;
    if (rb != null && rb > 0) h += `<i class="lz up" style="left:${X(0)}%;width:${X(rb) - X(0)}%"></i>`;
    h += `<b class="lk stop" style="left:${X(-1)}%"></b><b class="lk entry" style="left:${X(0)}%"></b><b class="lk tp" style="left:${X(rr1)}%"></b>`;
    if (rr2) h += `<b class="lk tp" style="left:${X(rr2)}%"></b>`;
    if (rres != null) h += `<em class="${t.r == null ? 'live' : cls(rres) || 'zero'}" style="left:${X(rres)}%"></em>`;
    const tip = `stop −1 · entrée 0 · objectif 1 ${sg(rr1)}${rr2 ? ' · objectif 2 ' + sg(rr2) : ''}${rb != null ? ' · au mieux ' + sg(rb) : ''}${rw != null ? ' · au pire ' + sg(rw) : ''}${rres != null ? ' · résultat ' + sg(rres) : ''} (en fois le risque)`;
    return h + `</div><div class="ladcap" title="${esc(tip)}">${rb != null ? `au mieux <span class="up">${sg(rb, 1)}</span> · au pire <span class="dn">${sg(rw, 1)}</span>` : '<span class="muted">trajet non enregistré</span>'}</div>`;
  }
  function resultCell(t) {
    if (t.mode === 'alerte') {
      const v = t.verdict === true ? ['ok', 'juste'] : t.verdict === false ? ['dn', 'fausse'] : ['', 'en cours'];
      return `<span class="pill ${v[0]}">alerte ${v[1]}</span>`;
    }
    const o = t.outcome;
    if (o === 'open') {
      const lr = t.rNow;
      return `<span class="pill warn">${esc(t.resultText)}</span>${lr != null ? `<div class="small">au prix actuel <b class="${cls(lr)}">${sg(lr)}</b> <span class="muted">(pas encore compté)</span></div>` : ''}`;
    }
    if (o === 'uncounted') return `<span class="pill">${esc(t.resultText)}</span>${t.rNow != null ? `<div class="small muted">valait ${sg(t.rNow)} à ce moment · non compté</div>` : ''}`;
    if (o === 'unfilled') return `<span class="pill">${esc(t.resultText)}</span><div class="small muted">0 · aucune position</div>`;
    const m = money(t.r);
    return `<span class="pill ${o === 'win' ? 'ok' : 'dn'}">${esc(t.resultText)}</span><div class="small"><b class="${cls(t.r)}">${sg(t.r)}</b> fois le risque${m ? ` <b class="${cls(t.r)}">(${m})</b>` : ''}</div>`;
  }
  function timeCell(t) {
    if (t.status === 'pending') return `<span class="muted">valable jusqu'au ${when(t.validUntil)}</span>`;
    if (!t.filledAt) return '<span class="muted">-</span>';
    return `${t.status === 'closed' ? '' : 'depuis '}${dur(t.held)}`;
  }
  function rowHtml(t) {
    const on = openIds.has(t.id);
    const what = t.mode === 'alerte' ? `<b class="amb">Alerte</b><small class="muted">configuration ${t.side === 'short' ? 'de vente' : 'd\'achat'}</small>`
      : `<b class="${t.side === 'long' ? 'up' : 'dn'}">${SIDE[t.side]}</b><small class="muted">${esc(KIND[t.kind] || t.kind || '')}${t.entryType === 'marché' ? ' · au marché' : ''}</small>`;
    const flip = (t.hedgeOf || []).length ? '<small class="amb">couverture</small>' : t.flipFrom || (t.switchFrom || []).length ? '<small class="amb">changement de sens</small>'
      : t.result === 'switch' || t.result === 'switch_cancel' ? '<small class="amb">remplacée par une idée plus forte</small>' : '';
    return `<tr class="hrow${on ? ' on' : ''}" data-tid="${esc(t.id)}"><td><span class="chev">${on ? '▾' : '▸'}</span> ${when(t.created)}</td><td><b>${esc(sym(t.symbol))}</b></td><td>${what}${flip}</td>
      <td class="r">${num(t.score, 0)}</td><td class="small">entrée ${px(t.entry)}<div class="muted">stop ${px(t.stop)} · objectifs ${px(t.tp1)}${t.tp2 ? ' / ' + px(t.tp2) : ''}</div></td>
      <td class="ladcell">${ladder(t)}</td><td>${resultCell(t)}</td><td class="small">${timeCell(t)}</td></tr>`
      + (on ? `<tr class="hdet" data-det="${esc(t.id)}"><td colspan="8">${fiche(t)}</td></tr>` : '');
  }
  function seg(attr, cur, opts) {
    return `<span class="hseg">${opts.map(([k, l]) => `<button data-${attr}="${k}" class="seg-like ${cur === k ? 'on' : ''}">${l}</button>`).join('')}</span>`;
  }
  function tableCard(d) {
    return `<section class="card" id="histTable">${tableInner(d)}</section>`;
  }
  function tableInner(d) {
    const rows = filtered(d);
    const pairs = [...new Set(d.trades.map(t => sym(t.symbol)))].sort();
    const bar = `<div class="hfilters">${seg('hf', filt.type, [['all', 'Tout'], ['ideas', 'Idées'], ['alerts', 'Alertes']])}
      ${pairs.length > 1 ? seg('hp', filt.pair, [['all', 'Toutes les paires']].concat(pairs.map(p => [p, p]))) : ''}
      ${seg('hr', filt.res, [['all', 'Tous les résultats'], ['win', 'Gagnantes'], ['loss', 'Perdantes'], ['none', 'Sans résultat'], ['open', 'En cours']])}</div>`;
    const body = rows.map(rowHtml).join('');
    return `<h2>Idées et alertes envoyées <small>${rows.length} affichée${rows.length > 1 ? 's' : ''} sur ${d.trades.length} · clique sur une ligne pour voir son graphique et son récit</small></h2>${bar}
      ${rows.length ? `<div class="scroll"><table class="bttab vt htab"><thead><tr><th>Envoi</th><th>Paire</th><th>Idée</th><th class="r" title="qualité sur 100 au moment de l'envoi">Qualité</th><th>Plan</th>
        <th title="jusqu'où le prix est allé contre toi (rouge) et pour toi (vert) pendant la position, en fois le risque ; traits : stop, entrée, objectifs ; point : résultat">Trajet</th><th>Résultat</th><th>Durée en position</th></tr></thead><tbody>${body}</tbody></table></div>`
        : `<div class="muted small">${d.trades.length ? 'Aucune idée pour ces filtres.' : 'Rien pour l\'instant : les idées sont rares (5 par semaine au plus) et n\'apparaissent ici qu\'une fois envoyées.'}</div>`}`;
  }
  function renderTable() {
    const el = document.getElementById('histTable');
    if (!el || !data) return;
    el.innerHTML = tableInner(data);
    fitFiches();
    openIds.forEach(id => { if (details[id] && details[id].bars) drawTrade(id); });
  }
  // la fiche reste dans la partie visible du tableau, meme quand celui-ci defile en largeur (petits ecrans)
  function fitFiches() {
    document.querySelectorAll('#histTable .hdet .fiche').forEach(f => {
      const sc = f.closest('.scroll');
      if (sc) f.style.width = Math.max(260, sc.clientWidth - 22) + 'px';
    });
  }
  function toggle(id) {
    if (openIds.has(id)) openIds.delete(id); else openIds.add(id);
    renderTable();
    if (openIds.has(id) && !details[id]) load(id);
  }
  async function load(id) {
    details[id] = {loading: true};
    try { details[id] = await LT.api('/api/history/trade?id=' + encodeURIComponent(id)); } catch (e) { details[id] = {error: e.message}; }
    const host = document.querySelector(`[data-det="${CSS.escape(id)}"] .fchart`);
    if (host) { host.outerHTML = chartBlock(id); fitFiches(); if (details[id].bars) drawTrade(id); }
  }

  // ---------- fiche d'une idee ----------
  function chartBlock(id) {
    const det = details[id];
    if (!det || det.loading) return '<div class="fchart"><div class="muted small">Chargement du trajet du prix…</div></div>';
    if (det.error) return `<div class="fchart"><div class="dn small">Trajet indisponible : ${esc(det.error)}</div></div>`;
    const legend = [['entry', 'entrée'], ['stop', 'stop'], ['tp', 'objectifs'], ['zone', 'zone de l\'idée'], ['pos', 'période en position']]
      .map(([k, l]) => `<span class="lg ${k}"><i></i>${l}</span>`).join('') +
      '<span class="lg mk"><b class="up">▲</b> meilleur moment <b class="dn">▼</b> pire moment <b>●</b> envoi, exécution, objectif 1, fin (survole les marques)</span>';
    return `<div class="fchart"><div class="fhead">Trajet du prix <small>bougies de ${esc(det.barWord)} · heure de Paris${det.source && det.source.indexOf('1 heure') === 0 ? ' · bougies 5 minutes plus conservées pour cette période' : ''}</small></div>
      <div class="tchart" id="tc-${esc(id)}"></div><div class="flegend">${legend}</div>
      ${(det.after || []).length ? `<div class="fafter"><span class="lt">Et ensuite ?</span> ${det.after.map(esc).join(' ')}</div>` : ''}</div>`;
  }
  function fiche(t) {
    const s = t.story || {};
    const li = arr => (arr || []).filter(Boolean).map(x => `<li>${esc(x)}</li>`).join('');
    const ev = (s.events || []).map(e => `<li class="ev ${e.kind}"><span class="evt">${e.t ? when(e.t) : e.kind === 'now' ? 'maintenant' : 'heure non enregistrée'}</span><span>${esc(e.text)}</span></li>`).join('');
    const comps = (t.comps || []).map(c => `<div class="cmp"><span>${esc(c.label)}</span><i><b style="width:${Math.max(0, Math.min(100, c.pts / (c.max || 1) * 100))}%"></b></i><em>${num(c.pts, 0)}/${c.max}</em></div>
      ${c.note ? `<div class="cmpnote">${esc(c.note)}</div>` : ''}`).join('');
    return `<div class="fiche"><div class="fleft">${chartBlock(t.id)}<div class="ftext">
      <h5>Pourquoi le terminal l'a proposée</h5><ul>${li(s.why)}</ul>${comps ? `<div class="cmps">${comps}</div>` : ''}</div></div>
      <div class="ftext"><h5>Ce qui s'est passé</h5><ol class="tl">${ev}</ol>
      <h5>Résultat</h5><ul>${li(s.result)}</ul>${(s.facts || []).length ? `<ul class="facts">${li(s.facts)}</ul>` : ''}
      ${(s.lesson || []).length ? `<h5>À retenir</h5><ul>${li(s.lesson)}</ul>` : ''}
      <h5>Le plan envoyé</h5><ul>${li(s.plan)}</ul>
      ${t.text ? `<details><summary>Message envoyé sur Telegram</summary><pre class="histmsg">${esc(t.text)}</pre></details>` : ''}</div></div>`;
  }
  const svg = (name, attrs, parent) => {
    const n = document.createElementNS(NS, name);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  };
  let tipEl = null;
  function tip(html, x, y) {
    if (!tipEl) { tipEl = document.createElement('div'); tipEl.className = 'ctip'; document.body.appendChild(tipEl); }
    tipEl.innerHTML = html; tipEl.style.display = 'block';
    const w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    tipEl.style.left = Math.min(window.innerWidth - w - 8, x + 14) + 'px';
    tipEl.style.top = Math.max(4, Math.min(window.innerHeight - h - 8, y - h - 10)) + 'px';
  }
  const hideTip = () => { if (tipEl) tipEl.style.display = 'none'; };
  const EV_COLOR = {sent: '#9aa3b5', fill: '#4c8dff', tp1: '#3ddc97', end: '#d1d4dc', best: '#3ddc97', worst: '#ff6b6b', near: '#ffb300'};
  function drawTrade(id) {
    const host = document.getElementById('tc-' + id), d = details[id], t = data && data.trades.find(x => x.id === id);
    if (!host || !d || !t) return;
    host.innerHTML = '';
    const bars = d.bars || [];
    if (!bars.length) { host.innerHTML = '<div class="muted small">Pas de bougies pour cette période (terminal éteint ou données pas encore chargées).</div>'; return; }
    const W = Math.max(320, host.clientWidth || 640), H = 300, m = {l: 6, r: 112, t: 12, b: 22};
    const L = d.levels;
    let lo = Infinity, hi = -Infinity;
    bars.forEach(b => { lo = Math.min(lo, b[3]); hi = Math.max(hi, b[2]); });
    [L.entry, L.stop, L.tp1, L.tp2].forEach(v => { if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
    const pad = (hi - lo) * 0.05 || hi * 0.002; lo -= pad; hi += pad;
    const x0 = d.from, x1 = Math.max(d.to, bars[bars.length - 1][0]) + d.bar;
    const X = ms => m.l + (ms - x0) / (x1 - x0) * (W - m.l - m.r), Y = p => m.t + (hi - p) / (hi - lo) * (H - m.t - m.b);
    const g = svg('svg', {class: 'ch tch', viewBox: `0 0 ${W} ${H}`, height: H}, host);
    Charts.ticks(lo, hi, 5).forEach(v => {
      svg('line', {x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), class: 'grid'}, g);
      svg('text', {x: m.l + 2, y: Y(v) - 3, class: 'tick'}, g).textContent = px(v);
    });
    const end = t.status === 'closed' ? (t.endAt || t.closedAt) : d.to;
    if (t.filledAt) svg('rect', {x: X(t.filledAt), y: m.t, width: Math.max(1, X(end) - X(t.filledAt)), height: H - m.t - m.b, class: 'tpos'}, g);
    if (L.zone && L.zone.lo != null && L.zone.hi != null) {
      const zlo = Math.max(lo, Math.min(hi, L.zone.lo)), zhi = Math.max(lo, Math.min(hi, L.zone.hi));
      svg('rect', {x: X(t.created), y: Y(zhi), width: Math.max(1, W - m.r - X(t.created)), height: Math.max(1.5, Y(zlo) - Y(zhi)), class: 'tzone'}, g);
    }
    // bougies
    const cw = Math.max(1, Math.min(9, (W - m.l - m.r) / Math.max(1, (x1 - x0) / d.bar) * 0.7));
    bars.forEach(b => {
      const x = X(b[0] + d.bar / 2), up = b[4] >= b[1];
      svg('line', {x1: x, x2: x, y1: Y(b[2]), y2: Y(b[3]), class: up ? 'cw up' : 'cw dn'}, g);
      svg('rect', {x: x - cw / 2, y: Y(Math.max(b[1], b[4])), width: cw, height: Math.max(1, Math.abs(Y(b[1]) - Y(b[4]))), class: up ? 'cb up' : 'cb dn'}, g);
    });
    // niveaux : trait plein pendant la vie de l'idee, pointille avant et apres
    const lv = [['entry', L.entry, 'Entrée'], ['stop', L.stop, 'Stop'], ['tp', L.tp1, 'Objectif 1'], ['tp', L.tp2, 'Objectif 2']].filter(x => x[1] != null);
    lv.forEach(([k, v]) => {
      svg('line', {x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), class: 'tl ' + k + ' faint'}, g);
      svg('line', {x1: X(t.created), x2: X(end), y1: Y(v), y2: Y(v), class: 'tl ' + k}, g);
    });
    // etiquettes a droite, sans chevauchement
    const labs = lv.map(([k, v, name]) => ({k, y: Y(v), text: `${name} ${px(v)}`})).sort((a, b) => a.y - b.y);
    for (let i = 1; i < labs.length; i++) if (labs[i].y - labs[i - 1].y < 13) labs[i].y = labs[i - 1].y + 13;
    const over = labs.length ? labs[labs.length - 1].y - (H - m.b - 2) : 0;
    if (over > 0) labs.forEach(l => { l.y -= over; });
    labs.forEach(l => { svg('text', {x: W - m.r + 6, y: l.y + 3, class: 'tlab ' + l.k}, g).textContent = l.text; });
    // axe du temps (heure de Paris)
    const span = x1 - x0, nt = Math.max(2, Math.min(6, Math.floor((W - m.l - m.r) / 110)));
    for (let i = 0; i <= nt; i++) {
      const tt = x0 + span * i / nt, lab = span > 3 * 86400000 ? PDAY.format(new Date(tt)) : PDAY.format(new Date(tt)) + ' ' + PHOUR.format(new Date(tt)).replace(':', 'h');
      svg('text', {x: X(tt), y: H - 6, 'text-anchor': i === 0 ? 'start' : i === nt ? 'end' : 'middle'}, g).textContent = lab;
    }
    // moments cles
    (d.events || []).forEach(e => {
      if (e.t == null || e.t < x0 || e.t > x1) return;
      const c = e.kind === 'end' ? (t.r > 0 ? '#3ddc97' : t.r < 0 ? '#ff6b6b' : '#d1d4dc') : EV_COLOR[e.kind] || '#d1d4dc';
      if (['sent', 'fill', 'end'].includes(e.kind)) svg('line', {x1: X(e.t), x2: X(e.t), y1: m.t, y2: H - m.b, stroke: c, 'stroke-width': 1, 'stroke-dasharray': '2 3', opacity: 0.7}, g);
      if (e.p == null) return;
      const cx = X(e.t + (e.kind === 'sent' ? 0 : d.bar / 2)), cy = Y(e.p);
      const shape = e.kind === 'best' || e.kind === 'worst' ? svg('path', {d: e.kind === 'best' ? `M${cx} ${cy - 7}l5 8h-10z` : `M${cx} ${cy + 7}l5 -8h-10z`, fill: c, stroke: '#131722', 'stroke-width': 1.5}, g)
        : svg('circle', {cx, cy, r: 5, fill: c, stroke: '#131722', 'stroke-width': 2}, g);
      shape.style.cursor = 'help';
      shape.addEventListener('mousemove', ev => tip(`<b>${esc(e.label)}</b><br>${when(e.t)} · ${px(e.p)}`, ev.clientX, ev.clientY));
      shape.addEventListener('mouseleave', hideTip);
    });
    // reticule et infobulle des bougies
    const cross = svg('line', {y1: m.t, y2: H - m.b, stroke: '#6a6e7a', 'stroke-width': 1, visibility: 'hidden'}, g);
    const hit = svg('rect', {x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent'}, g);
    g.insertBefore(hit, g.querySelector('circle, path'));
    hit.addEventListener('mousemove', ev => {
      const r = g.getBoundingClientRect(), xv = x0 + ((ev.clientX - r.left) * W / r.width - m.l) / (W - m.l - m.r) * (x1 - x0);
      let best = bars[0];
      for (const b of bars) if (Math.abs(b[0] + d.bar / 2 - xv) < Math.abs(best[0] + d.bar / 2 - xv)) best = b;
      const cx = X(best[0] + d.bar / 2);
      cross.setAttribute('x1', cx); cross.setAttribute('x2', cx); cross.setAttribute('visibility', 'visible');
      const rk = Math.abs(t.entry - t.stop), rOf = p => rk ? ((t.side === 'long' ? p - t.entry : t.entry - p) / rk) : null;
      tip(`<div class="muted">${when(best[0])}</div>ouverture ${px(best[1])} · haut ${px(best[2])}<br>bas ${px(best[3])} · clôture <b>${px(best[4])}</b>` +
        (t.filledAt ? `<br><span class="muted">clôture à ${sg(rOf(best[4]))} fois le risque de l'entrée</span>` : ''), ev.clientX, ev.clientY);
    });
    hit.addEventListener('mouseleave', () => { cross.setAttribute('visibility', 'hidden'); hideTip(); });
  }

  // ---------- par categorie ----------
  function groupsCard(d) {
    return `<section class="card" id="histGroups">${groupsInner(d)}</section>`;
  }
  function groupsInner(d) {
    const gs = (d.summary || {}).groups || [];
    const g = gs.find(x => x.key === group) || gs[0];
    if (!g || !(d.summary.n > 0)) return '<h2>Ce qui marche, ce qui ne marche pas</h2><div class="muted small">Pas encore d\'idée envoyée.</div>';
    const rows = g.rows.map(r => `<tr><td>${esc(r.label)}</td><td class="r">${r.n}</td><td class="r">${r.filled}${r.n ? ' <span class="muted">(' + pct(r.fillRate) + ')</span>' : ''}</td>
      <td class="r">${r.decided}${r.open ? ' <span class="muted">+' + r.open + ' en cours</span>' : ''}</td><td class="r">${r.decided ? r.wins + ' <span class="muted">(' + pct(r.winRate) + ')</span>' : '-'}</td>
      <td class="r ${cls(r.r)}">${r.decided ? sg(r.r) : '-'}${r.decided && riskUsd > 0 ? '<div class="small">' + money(r.r) + '</div>' : ''}</td><td class="r ${cls(r.avg)}">${r.decided ? sg(r.avg) : '-'}</td></tr>`).join('');
    const small = g.rows.some(r => r.decided > 0 && r.decided < 10);
    return `<h2>Ce qui marche, ce qui ne marche pas <small>résultats par catégorie, en fois le risque</small></h2>
      <div class="hfilters">${seg('hg', g.key, gs.map(x => [x.key, x.title]))}</div>
      <div class="scroll"><table class="bttab vt"><thead><tr><th>${esc(g.title)}</th><th class="r">Idées</th><th class="r">Exécutées</th><th class="r">Terminées</th><th class="r">Gagnantes</th><th class="r">Résultat total</th><th class="r">Moyenne par idée terminée</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="muted small">${small ? 'Moins de 10 idées terminées dans une catégorie : c\'est une anecdote, pas une preuve. ' : ''}Une idée « terminée » a été exécutée puis s'est conclue (stop, objectif 1 puis équilibre, objectif 2). Les frais ne sont pas comptés.</div>`;
  }
  function renderGroups() {
    const el = document.getElementById('histGroups');
    if (el && data) el.innerHTML = groupsInner(data);
  }

  // ---------- annonce contre realise ----------
  function compare(d) {
    const s = d.summary || {}, ex = s.expect || {}, cal = s.calibration || {};
    const pairRows = ((s.groups || []).find(g => g.key === 'pair') || {rows: []}).rows;
    const syms = Object.keys(ex).filter(k => ex[k]);
    const rows = syms.map(k => {
      const e = ex[k], live = pairRows.find(r => r.label === sym(k));
      return `<tr><td><b>${esc(sym(k))}</b>${e.proxy ? ' <span class="muted small">(rapport du bitcoin : pas de rapport pour cette paire)</span>' : ''}</td>
        <td class="r">${pct(e.winRate)} <span class="muted small">sur ${e.n}</span></td><td class="r ${cls(e.expR)}">${sg(e.expR)}</td>
        <td class="r">${e.recent ? `${pct(e.recent.winRate)} · <span class="${cls(e.recent.expR)}">${sg(e.recent.expR)}</span> <span class="muted small">(${esc(e.recent.label)}, ${e.recent.n} idées)</span>` : '-'}</td>
        <td class="r">${live && live.decided ? `${pct(live.winRate)} <span class="muted small">sur ${live.decided}</span>` : '<span class="muted">aucune</span>'}</td><td class="r ${live ? cls(live.avg) : ''}">${live && live.decided ? sg(live.avg) : '-'}</td></tr>`;
    }).join('');
    const calLine = (c, what, unit) => c ? `<li>${what} : <b>${pct(c.announced)}</b> annoncé en moyenne à l'envoi ; en réel <b>${pct(c.real)}</b> (${Math.round(c.real * c.n)} ${unit} sur ${c.n}).${c.n < 20 ? ' <span class="muted">Encore trop peu de cas pour juger.</span>' : ''}</li>` : '';
    const cl = calLine(cal.tp1, 'Chance d\'atteindre l\'objectif 1 avant le stop', 'fois') + calLine(cal.fill, 'Chance que l\'ordre à cours limité soit exécuté en 24 heures', 'fois');
    if (!rows && !cl) return '';
    return `<section class="card"><h2>Ce que le terminal attendait, et ce qui est arrivé</h2>
      ${rows ? `<div class="scroll"><table class="bttab vt"><thead><tr><th>Paire</th><th class="r">Backtest : idées gagnantes</th><th class="r">Backtest : moyenne par idée</th><th class="r">Backtest, période récente</th><th class="r">En réel : gagnantes</th><th class="r">En réel : moyenne par idée</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="muted small">Backtest : mêmes règles rejouées sur l'historique de la paire (${syms.map(k => esc(ex[k].label)).join(', ')}), frais comptés et sortie forcée après 72 heures. En réel : idées vraiment envoyées par ce terminal, sans frais, suivies 7 jours. Si le réel reste loin du backtest après une trentaine d'idées, c'est un signal à prendre au sérieux.</div>` : ''}
      ${cl ? `<ul class="btnotes">${cl}</ul>` : '<div class="muted small">Les chances annoncées à l\'envoi sont enregistrées depuis le journal détaillé (V24) : la comparaison apparaîtra avec les prochaines idées.</div>'}</section>`;
  }

  // ---------- lectures quotidiennes ----------
  function readings(d) {
    const R = d.readings, rows = R.rows;
    const cell = (r, k) => {
      const v = r.after[k];
      if (v == null) return '<td class="r muted">…</td>';
      const ok = r.trend ? (v > 0) === (r.trend > 0) : null;
      return `<td class="r ${v > 0 ? 'up' : v < 0 ? 'dn' : ''}">${sg(v, 1, ' %')}${ok == null ? '' : ok ? ' <span title="dans le sens de la tendance">✓</span>' : ' <span class="muted" title="contre la tendance">✗</span>'}</td>`;
    };
    const body = rows.map(r => `<tr><td>${esc(r.day.slice(8, 10) + '/' + r.day.slice(5, 7))}</td><td><b>${esc(sym(r.symbol))}</b></td><td class="r">${px(r.price)}</td>
      <td class="${r.trend > 0 ? 'up' : r.trend < 0 ? 'dn' : 'muted'}">${esc(r.trendLabel || '-')}</td><td class="small">${esc(r.squeeze || '-')}</td><td class="small">${esc(r.macro || '-')}</td>
      <td class="small">${r.idea ? `${SIDE[r.idea.side]} ${num(r.idea.score, 0)}/100${r.idea.eligible ? '' : ' (non envoyée)'}` : '-'}</td>${cell(r, '24')}${cell(r, '72')}${cell(r, '168')}</tr>`).join('');
    return `<section class="card"><h2>Lectures du terminal, jour après jour <small>une par jour et par paire, puis ce que le prix a fait</small></h2>
      <div class="muted small">✓ = le prix est allé dans le sens de la tendance de fond (le seul élément validé par le backtest). Squeeze, macro et idée sont gardés pour mémoire.</div>
      ${rows.length ? `<div class="scroll"><table class="bttab vt"><thead><tr><th>Jour</th><th>Paire</th><th class="r">Prix</th><th>Tendance de fond</th><th>Squeeze</th><th>Macro</th><th>Idée du moment</th><th class="r">24 heures après</th><th class="r">3 jours après</th><th class="r">7 jours après</th></tr></thead><tbody>${body}</tbody></table></div>`
        : '<div class="muted small">La première lecture s\'enregistre dans les minutes qui suivent le démarrage, puis une par jour.</div>'}</section>`;
  }

  // ---------- mode d'emploi ----------
  function guide(d) {
    const dir = d.direction === 'long' ? 'Achat seulement : les configurations de vente arrivent comme « alertes pour tes longs », hors quota.' :
      d.direction === 'short' ? 'Vente seulement : les configurations d\'achat arrivent comme « alertes pour tes shorts », hors quota.' : 'Achats et ventes (réglage recommandé).';
    return `<section class="card"><h2>Comment lire cette page</h2><ul class="btnotes">
      <li><b>« Fois le risque »</b> : l'unité de tous les résultats. Le risque, c'est la distance entre l'entrée et le stop. Un stop touché coûte 1 fois le risque ; +2 fois le risque veut dire que tu gagnes deux fois ce que tu aurais perdu au stop. Indique en haut la somme que tu risques par idée pour lire les résultats en dollars.</li>
      <li><b>Gestion suivie par le terminal</b> : la moitié de la position est encaissée à l'objectif 1 et le stop remonte à l'entrée ; l'autre moitié sort à l'objectif 2, ou à l'entrée si le prix revient. D'où « objectif 1 atteint puis sortie à l'équilibre » = la moitié de l'objectif 1 (gagnante, sans perte possible sur le reste).</li>
      <li><b>Sans résultat</b> : « objectif atteint sans exécution » (l'ordre n'a jamais été touché, le terminal ne court pas après le prix) et « expirée » valent 0. « Suivi arrêté après 7 jours » n'est pas compté : la gestion te revient.</li>
      <li><b>Trajet</b> : la barre montre jusqu'où le prix est allé contre toi (rouge) et pour toi (vert) pendant la position, en fois le risque. Traits : stop (−1), entrée (0), objectifs. Point : le résultat (bleu si la position est encore ouverte).</li>
      <li><b>Meilleur et pire moment</b> : le prix le plus favorable et le plus défavorable pendant la position, lus sur les bougies de 5 minutes. Dans une bougie qui touche le stop, l'ordre des mouvements est inconnu : on retient le pire, comme pour le résultat.</li>
      <li><b>Le terminal n'analyse que lorsqu'il tourne</b> (allumé depuis le ${when(d.since)}). Éteint, il n'envoie rien ; au redémarrage, il vérifie ce qui est arrivé aux idées ouvertes pendant son absence (stop, objectifs), sans fabriquer d'idées pour le passé. Pour qu'il tourne 24 heures sur 24 sans ton ordinateur : dossier <code>serveur/</code>.</li>
      <li><b>Sens de tes trades</b> : ${dir} (Réglages → 4). ${d.opposite === 'never'
        ? 'Une seule direction à la fois, toutes paires confondues : tant qu\'une idée est en cours (ordre en attente, position, objectif 1 atteint), aucune idée dans l\'autre sens.'
        : 'Une idée dans l\'autre sens peut arriver pendant une idée en cours : elle la <b>couvre</b> sans l\'annuler (marquée « couverture »), chaque idée garde son stop et ses objectifs et compte ici avec son propre résultat. Le tableau « Couverture » des résultats par catégorie dit si elles paient.'}</li></ul></section>`;
  }

  function render() {
    const root = document.getElementById('histBox');
    if (!root) return;
    hideTip();
    if (err) { root.innerHTML = `<section class="card"><div class="dn">Historique indisponible : ${esc(err)}</div></section>`; return; }
    if (!data) { root.innerHTML = '<section class="card"><div class="muted">Chargement…</div></section>'; return; }
    if (!data.summary) { root.innerHTML = '<section class="card"><div class="dn">Le programme qui tourne est plus ancien que cette page : redémarre le terminal pour voir l\'historique détaillé.</div></section>'; return; }
    root.innerHTML = '<div class="btgrid hist">' + head(data) + curve(data) + tableCard(data) + groupsCard(data) + compare(data) + readings(data) + guide(data) + '</div>';
    if (document.getElementById('histCurve')) drawCurve(data);
    fitFiches();
    openIds.forEach(id => { if (details[id] && details[id].bars) drawTrade(id); });
  }
  return {init, show, render};
})();
