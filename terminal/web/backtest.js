// Page Backtest : ce que 10 à 14 ans d'historique disent de la stratégie du terminal (rapport calculé par engine/study.py).
const Backtest = (() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const num = (v, d = 2) => v == null || isNaN(v) ? '-' : v.toFixed(d).replace('.', ',');
  const sgn = (v, d = 2) => v == null || isNaN(v) ? '-' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d).replace('.', ',');
  const pc = (v, d = 0) => v == null || isNaN(v) ? '-' : (v * 100).toFixed(d).replace('.', ',') + ' %';
  const yr = ms => new Date(ms).getUTCFullYear();
  const dateFr = ms => new Date(ms).toLocaleDateString('fr-FR', {day: '2-digit', month: '2-digit', year: 'numeric'});
  let LT = null, list = null, label = null, rep = null, loading = false, error = null, sortKey = null;

  async function show() {
    if (loading) return;
    if (!list) {
      loading = true; render();
      try { list = (await LT.api('/api/backtest')).reports; } catch (e) { error = e.message; }
      loading = false;
    }
    if (list && list.length && !label) {
      const base = (LT.st.symbol || 'BTCUSDT').replace(/USDT$/, '');
      label = (list.find(r => r.label === base) || list.find(r => r.label === 'BTC') || list[0]).label;
    }
    if (label && (!rep || rep.label !== label)) {
      loading = true; render();
      try { rep = await LT.api('/api/backtest?label=' + encodeURIComponent(label)); error = null; } catch (e) { error = e.message; }
      loading = false;
    }
    render();
  }

  function init(lt) {
    LT = lt;
    const root = $('#btBox');
    if (!root) return;
    root.addEventListener('change', e => { if (e.target.id === 'btSel') { label = e.target.value; rep = null; show(); } });
    root.addEventListener('click', e => {
      const th = e.target.closest('th[data-sort]');
      if (th) { sortKey = sortKey === th.dataset.sort ? null : th.dataset.sort; render(); }
    });
  }

  // ---------- petits graphiques ----------
  function lineChart(series, opts = {}) {
    const w = 640, h = 220, log = opts.log !== false;
    const all = series.flatMap(s => s.pts.filter(p => p[1] > 0));
    if (!all.length) return '';
    const t0 = Math.min(...all.map(p => p[0])), t1 = Math.max(...all.map(p => p[0]));
    const f = log ? Math.log : (v => v), fi = log ? Math.exp : (v => v);
    const ly = all.map(p => f(p[1]));
    let y0 = Math.min(...ly), y1 = Math.max(...ly);
    if (!log) { y0 = Math.min(y0, 1); const pad = (y1 - y0) * 0.05; y1 += pad; }
    const L = 46, R = 12, T = 10, B = 22, X = t => L + (t - t0) / (t1 - t0 || 1) * (w - L - R), Y = v => T + (1 - (f(v) - y0) / ((y1 - y0) || 1)) * (h - T - B);
    const fmt = v => log ? (v >= 10 ? '×' + Math.round(v) : '×' + num(v, 1)) : '×' + num(v, 2);
    let g = '';
    for (let k = 0; k <= 4; k++) {
      const lv = y0 + (y1 - y0) * k / 4, yy = T + (1 - k / 4) * (h - T - B);
      g += `<line class="grid" x1="${L}" x2="${w - R}" y1="${yy}" y2="${yy}"/><text x="${L - 4}" y="${yy + 3}" text-anchor="end">${fmt(fi(lv))}</text>`;
    }
    const span = yr(t1) - yr(t0), stepY = Math.max(1, Math.ceil(span / 6));
    for (let y = yr(t0) + 1; y <= yr(t1); y += stepY) {
      const x = X(Date.UTC(y, 0, 1)); g += `<line class="grid" x1="${x}" x2="${x}" y1="${T}" y2="${h - B}"/><text x="${x}" y="${h - 6}" text-anchor="middle">${y}</text>`;
    }
    if (!log) g += `<line class="ax" x1="${L}" x2="${w - R}" y1="${Y(1)}" y2="${Y(1)}" stroke-dasharray="3 3"/>`;
    const lines = series.map(s => `<polyline fill="none" stroke="${s.color}" stroke-width="${s.w || 1.6}" vector-effect="non-scaling-stroke" points="${s.pts.filter(p => p[1] > 0).map(p => X(p[0]).toFixed(1) + ',' + Y(p[1]).toFixed(1)).join(' ')}"/>`).join('');
    const leg = series.map(s => `<span class="lg"><i style="background:${s.color}"></i>${esc(s.name)} <b>${esc(s.end)}</b></span>`).join('');
    return `<svg class="ch btsvg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${g}${lines}</svg><div class="btleg">${leg}</div>`;
  }

  // barre signée centrée sur zéro : valeur en multiples du risque
  function bar(v, ci, scale = 0.5) {
    if (v == null) return '<span class="muted">-</span>';
    const a = Math.min(1, Math.abs(v) / scale) * 50, cls = v >= 0 ? 'pos' : 'neg';
    return `<span class="sbar ${cls}"><i style="${v >= 0 ? 'left:50%' : 'right:50%'};width:${a}%"></i><em></em></span>`;
  }
  function ciCell(m, scale = 0.45) {
    if (!m || m.expR == null) return '<span class="muted">-</span>';
    const c = x => Math.max(0, Math.min(100, 50 + 50 * x / scale));
    const lo = m.expLo == null ? m.expR : m.expLo, hi = m.expHi == null ? m.expR : m.expHi;
    const cls = lo > 0 ? 'pos' : hi < 0 ? 'neg' : '';
    return `<div class="ci ${cls}" title="Moyenne ${sgn(m.expR)} fois le risque, intervalle à 90 % de ${sgn(lo)} à ${sgn(hi)}"><i style="left:${c(lo)}%;width:${Math.max(1, c(hi) - c(lo))}%"></i><b style="left:${c(m.expR)}%"></b><u style="left:50%"></u></div>`;
  }
  const rcol = v => v == null ? 'muted' : v > 0.03 ? 'up' : v < -0.03 ? 'dn' : 'muted';

  // ---------- blocs ----------
  function verdictCard(r) {
    const T = r.terminal, A = T.all, L = T.legacy.all, bh = T.buyHold || {}, v = r.verdict;
    const tone = v.edge ? (v.levelsAdd ? 'ok' : 'warn') : 'bad';
    const kp = (t, big, sub, cls = '') => `<div class="kpi"><small>${t}</small><b class="${cls}">${big}</b><span>${sub}</span></div>`;
    return `<section class="card btv ${tone}"><div class="bthead"><h2>Verdict <small>${esc(r.label)} · ${dateFr(r.period.start)} → ${dateFr(r.period.end)} · ${r.candidates.toLocaleString('fr-FR')} idées simulées</small></h2></div>
      <div class="btverdict">${esc(v.text)}</div>
      <ul class="btnotes">${v.notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul>
      <div class="kpis">
        ${kp('Règle actuelle du terminal', sgn(A.expR) + ' R', `par trade, après frais · ${A.n} trades`, rcol(A.expR))}
        ${kp('Sans le filtre de tendance', sgn(L.expR) + ' R', `ancienne règle · ${L.n} trades`, rcol(L.expR))}
        ${kp('Réussite (règle actuelle)', pc(A.winRate), `gain moyen ${sgn(A.avgWin, 1)} R · perte moyenne ${sgn(A.avgLoss, 1)} R`)}
        ${kp('Plus forte baisse', pc(A.maxDD), `achat-conservation : ${pc(bh.maxDD)}`, A.maxDD < (bh.maxDD || 1) ? 'up' : '')}
        ${kp('Idées par semaine', num(A.perWeek, 1), `en position ${pc(A.exposure)} du temps`)}
      </div>
      <div class="muted small">« R » = multiple du risque pris sur le trade : +0,15 R signifie que, en moyenne, chaque trade rapporte 15 % de la somme risquée (un trade où l'on risque 100 € rapporte en moyenne 15 €), frais compris. Intervalle de confiance à 90 %.</div></section>`;
  }

  function trendCard(r) {
    const t = r.trend, eras = r.eras || [];
    const rows = [['Dans le sens de la tendance de fond', 'aligned', 'alignedEras'], ['À contre-courant', 'counter', 'counterEras']];
    const th = '<th></th><th>Tout</th>' + eras.map(e => `<th>${esc(e.label)}</th>`).join('');
    const body = rows.map(([name, k, ke]) => {
      const cells = [t[k]].concat((t[ke] || []));
      return `<tr><td><b>${name}</b></td>${cells.map(m => `<td><div class="btc"><b class="${rcol(m && m.expR)}">${sgn(m && m.expR)}</b> R${bar(m && m.expR, null, 0.4)}<small>${m ? m.n : 0} trades</small></div></td>`).join('')}</tr>`;
    }).join('');
    const ne = t.neutral;
    return `<section class="card"><h2>Le seul filtre qui compte : la tendance de fond</h2>
      <div class="muted small">Tendance de fond : le cours est au-dessus des moyennes de 50 et de 200 jours (haussière) ou sous les deux (baissière). Une idée est « dans le sens » si elle achète en tendance haussière ou vend en tendance baissière.</div>
      <table class="bttab"><thead><tr>${th}</tr></thead><tbody>${body}
      <tr><td class="muted">Tendance indécise (entre les deux moyennes)</td><td colspan="${eras.length + 1}"><span class="${rcol(ne.expR)}">${sgn(ne.expR)} R</span> <small>${ne.n} trades : aucun avantage mesuré</small></td></tr></tbody></table>
      <div class="muted small">Même sens de l'effet sur chaque grande période, y compris 2013-2016 qui n'avait pas servi à le choisir. Il s'affaiblit avec le temps (le marché devient plus mûr) : prudence.</div></section>`;
  }

  function equityCard(r) {
    const T = r.terminal;
    if (!T.equity || T.equity.length < 3) return '';
    const e = T.equity, last = e[e.length - 1][1], b = T.equityBuyHold, bl = b.length ? b[b.length - 1][1] : 1;
    const ctrl = T.controlTrend && T.controlTrend.expMean != null ? T.controlTrend : null;
    return `<section class="card"><h2>Courbes de capital</h2>
      <div class="btcharts">
        <div><div class="muted small">Règle actuelle, en risquant 1 % du capital par trade <small>(échelle linéaire)</small></div>${lineChart([{name: 'Capital', pts: e, color: '#4c8dff', end: '×' + num(last, 2), w: 1.8}], {log: false})}</div>
        <div><div class="muted small">Achat-conservation <small>(échelle logarithmique)</small></div>${lineChart([{name: 'Prix', pts: b, color: '#9aa0b0', end: '×' + (bl >= 10 ? Math.round(bl) : num(bl, 1)), w: 1.4}], {log: true})}</div>
      </div>
      <div class="muted small">Le cours a été multiplié par ${bl >= 10 ? Math.round(bl) : num(bl, 1)} sur la période : aucune règle à 1 % de risque par trade ne suit cette hausse. L'intérêt de la règle est ailleurs : une baisse maximale de ${pc(T.all.maxDD)} contre ${pc((T.buyHold || {}).maxDD)} pour l'achat-conservation, avec ${pc(T.all.exposure)} du temps en position.
      ${ctrl ? `Témoin : des entrées au hasard dans la même tendance donnent ${sgn(ctrl.expMean)} R en moyenne par trade ; la règle fait ${sgn(T.all.expR)} R.` : ''}</div></section>`;
  }

  function variantsCard(r) {
    let vs = r.variants.slice();
    const key = sortKey;
    if (key === 'expR') vs.sort((a, b) => (b.all.expR ?? -9) - (a.all.expR ?? -9));
    if (key === 'n') vs.sort((a, b) => b.all.n - a.all.n);
    const eras = r.eras || [];
    const rows = vs.map(v => {
      const A = v.all, cur = v.name === r.terminal.name;
      const ec = (v.eras || []).map(e => `<td class="r ${rcol(e.expR)}" title="${e.n} trades">${e.expR == null ? '-' : sgn(e.expR)}</td>`).join('');
      return `<tr class="${cur ? 'cur' : ''}"><td>${esc(v.name)}${cur ? ' <span class="pill ok">utilisée</span>' : ''}</td><td class="r">${A.n}</td><td class="r ${rcol(A.expR)}"><b>${sgn(A.expR)}</b></td><td>${ciCell(A)}</td>${ec}<td class="r">${pc(A.winRate)}</td><td class="r">${num(A.pf)}</td><td class="r">${pc(A.maxDD)}</td></tr>`;
    }).join('');
    return `<section class="card"><h2>Comparer les raisonnements <small>lequel est le plus probable ?</small></h2>
      <div class="muted small">Chaque ligne est une façon de choisir les idées à prendre, jouée sur tout l'historique avec les mêmes frais. Une règle n'a un avantage que si <b>tout son intervalle de confiance est au-dessus de zéro</b> (barre verte) <b>et</b> que le signe est le même dans chaque période.</div>
      <div class="scroll"><table class="bttab vt"><thead><tr><th>Raisonnement</th><th class="r" data-sort="n" title="trier">Trades</th><th class="r" data-sort="expR" title="trier">Gain moyen (R)</th><th>Intervalle à 90 %</th>${eras.map(e => `<th class="r">${esc(e.label)}</th>`).join('')}<th class="r">Réussite</th><th class="r">Facteur de profit</th><th class="r">Baisse max.</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="muted small">Clique sur « Trades » ou « Gain moyen » pour trier. Facteur de profit = gains cumulés / pertes cumulées (au-dessus de 1 : gagnant).</div></section>`;
  }

  function eventsCard(r) {
    const ev = (r.events || []).filter(e => e.all24);
    if (!ev.length) return '';
    const sp = yr(r.period.split);
    const groups = {};
    ev.forEach(e => (groups[e.group] = groups[e.group] || []).push(e));
    const cell = s => !s ? '<td class="r muted">-</td>' : `<td class="r ${rcol(s.ex * 10)}" title="${s.n} événements">${sgn(s.ex * 100)} %</td>`;
    const body = Object.entries(groups).map(([g, es]) => `<tr class="grp"><td colspan="8">${esc(g)}</td></tr>` + es.map(e => {
      const a = e.all24, t = Math.abs(a.t), strong = t >= 3;
      const p = e.p_all;
      return `<tr class="${e.consistent ? 'cur' : ''}"><td>${esc(e.name)}${e.consistent ? ' <span class="pill ok">stable</span>' : ''}</td><td class="r">${e.n}</td>${cell(e.all4)}${cell(e.all24)}<td class="r ${strong ? (a.t > 0 ? 'up' : 'dn') : 'muted'}">${sgn(a.t, 1)}</td>${cell(e.is24)}${cell(e.oos24)}<td class="r">${p ? pc(p.p, 1) : '-'}</td></tr>`;
    }).join('')).join('');
    return `<section class="card"><h2>Étude outil par outil <small>que fait le prix après chaque signal ?</small></h2>
      <div class="muted small">Pour chaque signal (balayage de liquidité, écart au VWAP, contact d'un VWAP ancré, CVD, tendance), le rendement du prix <b>par rapport au rendement moyen du marché</b> dans le même sens, 4 h et 24 h après. « Écart » = |t| : au-dessus de 3, l'effet est solide ; en dessous de 2, c'est du bruit. Parmi ${ev.length} signaux testés, quelques-uns paraissent forts par pur hasard : seuls comptent ceux qui gardent le même signe avant et après ${sp} (« stable »).</div>
      <div class="scroll"><table class="bttab vt"><thead><tr><th>Signal</th><th class="r">Fois</th><th class="r">Après 4 h</th><th class="r">Après 24 h</th><th class="r">Écart (t)</th><th class="r">Avant ${sp}</th><th class="r">Depuis ${sp}</th><th class="r">Va d'abord 1 ATR dans le bon sens</th></tr></thead><tbody>${body}</tbody></table></div>
      <div class="muted small">Dernière colonne : 50 % = hasard. Les effets en pourcentage sont des excédents de rendement, avant frais.</div></section>`;
  }

  function touchCard(r) {
    const ts = r.touch || [];
    if (!ts.length) return '';
    const by = {};
    ts.forEach(t => (by[`${t.k}|${t.hours}`] = by[`${t.k}|${t.hours}`] || []).push(t));
    const body = Object.entries(by).map(([k, arr]) => {
      const [kk, hh] = k.split('|');
      return `<tr class="grp"><td colspan="5">Le prix va d'abord de ${num(+kk, 1)} ATR dans le sens du trade (plutôt que contre) dans les ${hh} h</td></tr>` +
        arr.map(t => `<tr><td>${esc(t.name)}</td><td class="r">${t.n}</td><td class="r">${pc(t.p, 1)}</td><td class="r muted">${pc(t.pBase, 1)}</td><td class="r ${Math.abs(t.sigma) >= 3 ? (t.sigma > 0 ? 'up' : 'dn') : 'muted'}">${sgn(t.sigma, 1)}</td></tr>`).join('');
    }).join('');
    return `<section class="card"><h2>Les zones retiennent-elles le prix ? <small>test de réaction</small></h2>
      <div class="muted small">Après l'exécution d'un ordre limite posé sur une zone, avec quelle fréquence le prix repart-il dans le sens du trade avant de le contredire ? Comparé à des instants tirés au hasard (50 % attendu sans effet). Écart en nombre d'écarts-types.</div>
      <div class="scroll"><table class="bttab vt"><thead><tr><th>Zones</th><th class="r">Cas</th><th class="r">Zone</th><th class="r">Hasard</th><th class="r">Écart (σ)</th></tr></thead><tbody>${body}</tbody></table></div></section>`;
  }

  function regimeCard(r) {
    const rg = r.regime || [];
    if (!rg.length) return '';
    const labs = rg[0].periods.map(p => p.label);
    const body = rg.map(g => `<tr><td>${esc(g.name)}</td>${g.periods.map(p => p.cagr == null ? '<td class="r muted">-</td>' : `<td class="r"><b class="${p.cagr >= 0 ? 'up' : 'dn'}">${sgn(p.cagr * 100, 0)} %/an</b><small>baisse ${pc(p.maxDD)} · Sharpe ${num(p.sharpe, 1)}</small></td>`).join('')}</tr>`).join('');
    return `<section class="card"><h2>La tendance seule, sans niveaux <small>moyennes mobiles, un levier</small></h2>
      <div class="muted small">Pour mémoire : être investi seulement quand le cours est au-dessus de ses moyennes mobiles, sans aucun niveau ni VWAP. Frais 0,07 % par changement de position.</div>
      <div class="scroll"><table class="bttab"><thead><tr><th></th>${labs.map(l => `<th class="r">${esc(l)}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table></div></section>`;
  }

  function costsCard(r) {
    const s = r.costSens || [];
    if (!s.length) return '';
    return `<section class="card"><h2>Poids des frais</h2><table class="bttab"><tbody>${s.map(x => `<tr><td>${esc(x.name)}</td><td class="r"><b class="${rcol(x.expR)}">${sgn(x.expR)} R</b> par trade</td></tr>`).join('')}</tbody></table>
      <div class="muted small">Frais prévus : ordre limite ${num(r.costs.maker * 100, 3)} %, ordre au marché ${num(r.costs.taker * 100, 3)} % + glissement ${num(r.costs.slip * 100, 3)} %, financement ${num(r.costs.funding8h * 100, 3)} % par 8 h. Le résultat avant frais est proche de zéro pour presque toutes les règles : c'est le sens de la tendance qui fait la différence.</div></section>`;
  }

  function methodCard(r) {
    return `<section class="card"><h2>Méthode et limites</h2><ul class="btnotes">
      <li><b>Données</b> : ${esc(r.source || '')} Le calcul est refait toutes les 15 minutes avec uniquement ce qui était connu à cet instant (aucune donnée du futur).</li>
      <li><b>Idées</b> : exactement le code du terminal (niveaux VWAP jour → année, VWAP ancrés, profils de volume, poches de liquidité visibles dans le prix, balayages, CVD estimé), puis chaque idée est jouée sur les bougies d'une minute : ordre limite ou au marché, stop, objectif 1 avec prise de la moitié puis stop à l'entrée, objectif 2, sortie au bout de 72 h. Si le stop et l'objectif sont dans la même minute, le stop est compté en premier.</li>
      <li><b>Sélection</b> : une position à la fois, ${5} idées par semaine au maximum, une zone ne revient pas avant 48 h.</li>
      <li><b>Ce qui n'est pas testé</b> : les poches de liquidations estimées par l'Open Interest (29 jours d'historique seulement), le contexte macro et les annonces, le volume acheteur agressif réel (ici estimé), le financement réel et l'écart acheteur/vendeur. Les marchés de 2013 à 2016 étaient moins liquides : les frais réels y étaient plus élevés.</li>
      <li><b>Pour relancer sur tes données</b> (par exemple SOL avec le vrai volume acheteur de Binance) : <code>python tools/fetch_history.py SOLUSDT</code> puis <code>python tools/run_study.py SOLUSDT</code>. Le rapport apparaît ici automatiquement.</li>
      <li>Un résultat passé n'est pas une garantie. Un avantage mesuré de ce genre est modeste et peut disparaître.</li></ul></section>`;
  }

  function render() {
    const root = $('#btBox');
    if (!root) return;
    if (error && !rep) { root.innerHTML = `<section class="card"><div class="dn">Rapport indisponible : ${esc(error)}</div></section>`; return; }
    if (loading && !rep) { root.innerHTML = '<section class="card"><div class="muted">Chargement du rapport…</div></section>'; return; }
    if (!list || !list.length) { root.innerHTML = '<section class="card"><h2>Backtest</h2><div class="muted">Aucun rapport trouvé. Lance <code>python tools/run_study.py BTCUSDT</code> après avoir téléchargé l\'historique (<code>python tools/fetch_history.py BTCUSDT</code>).</div></section>'; return; }
    if (!rep) return;
    const sel = `<div class="btbar"><label>Rapport <select id="btSel">${list.map(x => `<option value="${esc(x.label)}" ${x.label === label ? 'selected' : ''}>${esc(x.label)}${x.own ? ' (calculé sur tes données)' : ' (livré avec le terminal)'}</option>`).join('')}</select></label>
      <span class="muted small">Calculé le ${dateFr(rep.computedAt)} en ${Math.round(rep.seconds / 60)} min</span></div>`;
    root.innerHTML = sel + '<div class="btgrid">' + verdictCard(rep) + trendCard(rep) + equityCard(rep) + variantsCard(rep) + eventsCard(rep) + touchCard(rep) + regimeCard(rep) + costsCard(rep) + methodCard(rep) + '</div>';
  }

  return {init, show, render};
})();
