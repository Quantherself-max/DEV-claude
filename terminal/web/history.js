// Historique : toutes les idees et alertes envoyees avec leur resultat, et la lecture quotidienne du terminal avec ce que le prix a fait ensuite (V13).
const History = (() => {
  'use strict';
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  let LT = null, data = null, err = null, filt = 'all';
  const num = (v, d = 1) => v == null || isNaN(v) ? '-' : Number(v).toFixed(d).replace('.', ',');
  const sg = (v, d = 1, u = '') => v == null || isNaN(v) ? '-' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d).replace('.', ',') + u;
  const px = v => v == null ? '-' : LT.fmtP(v);
  const PARIS = new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
  const when = ms => ms ? PARIS.format(new Date(ms)).replace(',', '') : '-';
  const SIDE = {long: 'Achat', short: 'Vente'};

  function init(lt) {
    LT = lt;
    const root = document.getElementById('histBox');
    if (!root) return;
    root.addEventListener('click', e => {
      const f = e.target.closest('[data-hf]');
      if (f) { filt = f.dataset.hf; render(); }
    });
  }
  async function show() {
    try { data = await LT.api('/api/history'); err = null; } catch (e) { err = e.message; }
    render();
  }

  function kpis(d) {
    const s = d.stats || {}, al = s.alerts || {n: 0, right: 0, wrong: 0};
    const ideas = d.trades.filter(t => t.mode !== 'alerte'), done = ideas.filter(t => t.r != null && t.result && !['expired', 'missed'].includes(t.result));
    const wins = done.filter(t => t.r > 0).length, rtot = done.reduce((a, t) => a + t.r, 0);
    const ts = d.readings.trendScore['72'] || {};
    const kp = (t, big, sub, cls = '') => `<div class="kpi"><small>${t}</small><b class="${cls}">${big}</b><span>${sub}</span></div>`;
    return `<div class="kpis">${kp('Idées envoyées', ideas.length, `${s.executed || 0} exécutées · ${s.open || 0} en cours`)}
      ${kp('Idées gagnantes', done.length ? Math.round(wins / done.length * 100) + ' %' : '-', `${wins} sur ${done.length} terminées (objectif atteint avant le stop)`)}
      ${kp('Résultat total', done.length ? sg(rtot, 1) + ' R' : '-', 'R = fois le risque pris ; moitié prise à l\'objectif 1, le reste à l\'objectif 2 ou à l\'entrée', rtot > 0 ? 'up' : rtot < 0 ? 'dn' : '')}
      ${kp(d.direction === 'short' ? 'Alertes pour tes shorts' : 'Alertes pour tes longs', al.n, al.right + al.wrong ? `${al.right} justes, ${al.wrong} fausses` : 'pas encore tranchées')}
      ${kp('Tendance de fond', ts.n ? Math.round(ts.rate * 100) + ' %' : '-', ts.n ? `le prix est allé dans son sens à 3 jours (${ts.right} fois sur ${ts.n})` : 'pas encore assez de lectures')}</div>`;
  }
  function curve(d) {
    const n = d.trades.filter(t => t.mode !== 'alerte' && t.r != null && t.closedAt && !['expired', 'missed'].includes(t.result)).length;
    return n >= 2 && typeof Charts !== 'undefined' ? '<section class="card"><h2>Résultat cumulé des idées <small>en fois le risque (R)</small></h2><div id="histCurve" class="svgbox"></div></section>' : '';
  }
  function drawCurve(d) {
    const el = document.getElementById('histCurve');
    if (!el) return;
    const done = d.trades.filter(t => t.mode !== 'alerte' && t.r != null && t.closedAt && !['expired', 'missed'].includes(t.result)).sort((a, b) => a.closedAt - b.closedAt);
    let c = 0;
    const pts = [[done[0].created, 0]].concat(done.map(t => [t.closedAt, (c += t.r)]));
    Charts.line(el, {series: [{name: 'Résultat cumulé (R)', color: '#3987e5', pts, area: true}], height: 180, yFmt: v => sg(v, 1) + ' R', xFmt: t => new Date(t).toLocaleDateString('fr-FR', {day: '2-digit', month: '2-digit'}), xTicks: 5, ref: {y: 0, label: '0'}});
  }
  function badge(t) {
    if (t.mode === 'alerte') {
      const v = t.verdict === true ? ['ok', 'juste'] : t.verdict === false ? ['bad', 'fausse'] : ['', 'en cours'];
      return `<span class="pill ${v[0]}">${v[1]}</span>`;
    }
    if (t.r == null) return `<span class="pill">${esc(t.resultText)}</span>`;
    const cls = t.r > 0 ? 'ok' : t.r < 0 ? 'bad' : '';
    return `<span class="pill ${cls}">${esc(t.resultText)}${t.result && !['expired', 'missed'].includes(t.result) ? ' · ' + sg(t.r, 1) + ' R' : ''}</span>`;
  }
  function trades(d) {
    let rows = d.trades;
    if (filt === 'ideas') rows = rows.filter(t => t.mode !== 'alerte');
    if (filt === 'alerts') rows = rows.filter(t => t.mode === 'alerte');
    const seg = [['all', 'Tout'], ['ideas', 'Idées'], ['alerts', 'Alertes']].map(([k, l]) => `<button data-hf="${k}" class="seg-like ${filt === k ? 'on' : ''}">${l}</button>`).join(' ');
    const body = rows.map(t => {
      const what = t.mode === 'alerte' ? `<b class="amb">Alerte</b> <span class="muted small">(configuration de ${t.side === 'short' ? 'vente' : 'achat'})</span>` : `<b class="${t.side === 'long' ? 'up' : 'dn'}">${SIDE[t.side]}</b>`;
      const flip = t.flipFrom ? `<div class="small amb">changement de sens : remplace l'${t.flipFrom.side === 'long' ? 'achat' : 'idée de vente'} du ${when(t.flipFrom.created)}</div>` : '';
      return `<tr><td>${when(t.created)}</td><td><b>${esc(t.symbol.replace('USDT', ''))}</b></td><td>${what}${flip}</td><td class="r">${num(t.score, 0)}</td>
        <td class="r small">${px(t.entry)}<div class="muted">stop ${px(t.stop)}</div></td><td class="r small">${px(t.tp1)}${t.tp2 ? `<div class="muted">${px(t.tp2)}</div>` : ''}</td>
        <td>${badge(t)}${t.closedAt ? `<div class="muted small">${when(t.closedAt)}</div>` : ''}</td>
        <td>${t.text ? `<details><summary class="small">message</summary><pre class="histmsg">${esc(t.text)}</pre></details>` : ''}</td></tr>`;
    }).join('');
    return `<section class="card"><h2>Idées et alertes envoyées <small>${d.trades.length} au total · heure de Paris</small></h2>
      <div class="line">${seg}</div>
      ${rows.length ? `<div class="scroll"><table class="bttab vt"><thead><tr><th>Date</th><th>Paire</th><th>Quoi</th><th class="r">Qualité</th><th class="r">Entrée</th><th class="r">Objectifs</th><th>Résultat</th><th></th></tr></thead><tbody>${body}</tbody></table></div>`
        : '<div class="muted small">Rien pour l\'instant : les idées sont rares (5 par semaine au plus) et n\'apparaissent ici qu\'une fois envoyées.</div>'}</section>`;
  }
  function readings(d) {
    const R = d.readings, rows = R.rows;
    const cell = (r, k) => {
      const v = r.after[k];
      if (v == null) return '<td class="r muted">…</td>';
      const ok = r.trend ? (v > 0) === (r.trend > 0) : null;
      return `<td class="r ${v > 0 ? 'up' : v < 0 ? 'dn' : ''}">${sg(v, 1, ' %')}${ok == null ? '' : ok ? ' <span title="dans le sens de la tendance">✓</span>' : ' <span class="muted" title="contre la tendance">✗</span>'}</td>`;
    };
    const body = rows.map(r => `<tr><td>${esc(r.day.slice(8, 10) + '/' + r.day.slice(5, 7))}</td><td><b>${esc(r.symbol.replace('USDT', ''))}</b></td><td class="r">${px(r.price)}</td>
      <td class="${r.trend > 0 ? 'up' : r.trend < 0 ? 'dn' : 'muted'}">${esc(r.trendLabel || '-')}</td><td class="small">${esc(r.squeeze || '-')}</td><td class="small">${esc(r.macro || '-')}</td>
      <td class="small">${r.idea ? `${SIDE[r.idea.side]} ${num(r.idea.score, 0)}/100${r.idea.eligible ? '' : ' (non envoyée)'}` : '-'}</td>${cell(r, '24')}${cell(r, '72')}${cell(r, '168')}</tr>`).join('');
    return `<section class="card"><h2>Lectures du terminal, jour après jour <small>une par jour et par paire, puis ce que le prix a fait</small></h2>
      <div class="muted small">✓ = le prix est allé dans le sens de la tendance de fond (le seul élément validé par le backtest). Squeeze, macro et idée sont gardés pour mémoire.</div>
      ${rows.length ? `<div class="scroll"><table class="bttab vt"><thead><tr><th>Jour</th><th>Paire</th><th class="r">Prix</th><th>Tendance de fond</th><th>Squeeze</th><th>Macro</th><th>Idée du moment</th><th class="r">24 h après</th><th class="r">3 jours après</th><th class="r">7 jours après</th></tr></thead><tbody>${body}</tbody></table></div>`
        : '<div class="muted small">La première lecture s\'enregistre dans les minutes qui suivent le démarrage, puis une par jour.</div>'}</section>`;
  }
  function info(d) {
    const dir = d.direction === 'long' ? 'Achat seulement : les configurations de vente arrivent comme « alertes pour tes longs », hors quota.' :
      d.direction === 'short' ? 'Vente seulement : les configurations d\'achat arrivent comme « alertes pour tes shorts », hors quota.' : 'Achats et ventes.';
    return `<section class="card"><h2>Comment ça marche</h2><ul class="btnotes">
      <li><b>Le terminal n'analyse que lorsqu'il tourne</b> (allumé depuis le ${when(d.since)}). Éteint, il ne calcule rien et n'envoie rien ; au redémarrage, il recharge l'historique des prix et vérifie ce qui est arrivé aux idées ouvertes pendant son absence (stop, objectifs), mais il ne fabrique pas d'idées pour le passé. Pour qu'il tourne 24 h / 24 sans ton ordinateur : dossier <code>serveur/</code> (un petit serveur loué, quelques euros par mois).</li>
      <li><b>Sens de tes trades</b> : ${dir} (Réglages → 4).</li>
      <li><b>Pas de va-et-vient</b> : une idée dans l'autre sens qu'une idée de moins de 72 heures sur la même paire n'est envoyée que si la précédente est terminée, avec 10 points de qualité en plus, et le message commence par « CHANGEMENT DE SENS » en disant qu'elle remplace la précédente. Une idée achat sur BTC et une alerte sur SOL ne se contredisent pas : ce sont deux paires différentes.</li></ul></section>`;
  }
  function render() {
    const root = document.getElementById('histBox');
    if (!root) return;
    if (err) { root.innerHTML = `<section class="card"><div class="dn">Historique indisponible : ${esc(err)}</div></section>`; return; }
    if (!data) { root.innerHTML = '<section class="card"><div class="muted">Chargement…</div></section>'; return; }
    root.innerHTML = `<div class="btgrid"><section class="card"><h2>Historique du terminal <small>${data.source === 'simulated' ? 'données simulées' : 'Binance'}</small></h2>${kpis(data)}</section>`
      + curve(data) + trades(data) + readings(data) + info(data) + '</div>';
    if (document.getElementById('histCurve')) drawCurve(data);
  }
  return {init, show, render};
})();
