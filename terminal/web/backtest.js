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
  let LT = null, list = null, label = null, kind = 'backtest', rep = null, loading = false, error = null, sortKey = null, showAll = false;

  const repKind = r => ({'vwap-strategy': 'strategy', 'avwap-swing': 'avwap', indicators: 'indicators', rotation: 'rotation', squeeze: 'squeeze', pockets: 'pockets'})[r.kind] || 'backtest';

  async function show() {
    if (loading) return;
    if (!list) {
      loading = true; render();
      try { list = (await LT.api('/api/backtest')).reports; } catch (e) { error = e.message; }
      loading = false;
    }
    if (list && list.length && !label) {
      const base = (LT.st.symbol || 'BTCUSDT').replace(/USDT$/, '');
      const pick = list.find(r => r.kind === 'backtest' && r.label === base) || list.find(r => r.kind === 'backtest' && r.label === 'BTC') || list[0];
      label = pick.label; kind = pick.kind;
    }
    if (label && (!rep || rep.label !== label || repKind(rep) !== kind)) {
      loading = true; render();
      try { rep = await LT.api('/api/backtest?label=' + encodeURIComponent(label) + '&kind=' + kind); error = null; } catch (e) { error = e.message; }
      loading = false;
    }
    render();
  }

  function init(lt) {
    LT = lt;
    const root = $('#btBox');
    if (!root) return;
    root.addEventListener('change', e => { if (e.target.id === 'btSel') { [kind, label] = e.target.value.split('|'); rep = null; show(); } });
    root.addEventListener('click', e => {
      const th = e.target.closest('th[data-sort]');
      if (th) { sortKey = sortKey === th.dataset.sort ? null : th.dataset.sort; render(); }
      const rt = e.target.closest('[data-rott]');
      if (rt) { rotT = rt.dataset.rott; render(); }
      const sqb = e.target.closest('[data-sqt]');
      if (sqb) { sqT = sqb.dataset.sqt; render(); }
      const ih = e.target.closest('[data-indh]');
      if (ih) { indH = +ih.dataset.indh; render(); }
      const all = e.target.closest('[data-showall]');
      if (all) { showAll = !showAll; render(); }
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
      <li><b>Exécution des ordres limites</b> : un ordre limite est supposé exécuté dès que le prix le touche (optimiste : la file d'attente peut empêcher l'exécution). Vérifié : en exigeant que le prix dépasse le niveau de 0,1 %, la règle actuelle passe de +0,13 à +0,125 R par trade, donc le résultat n'en dépend pas.</li>
      <li><b>Sélection</b> : une position à la fois, ${5} idées par semaine au maximum, une zone ne revient pas avant 48 h.</li>
      <li><b>Ce qui n'est pas testé</b> : les poches de liquidations estimées par l'Open Interest (29 jours d'historique seulement), le contexte macro et les annonces, le volume acheteur agressif réel (ici estimé), le financement réel et l'écart acheteur/vendeur. Les marchés de 2013 à 2016 étaient moins liquides : les frais réels y étaient plus élevés.</li>
      <li><b>Pour relancer sur tes données</b> (par exemple SOL avec le vrai volume acheteur de Binance) : <code>python tools/fetch_history.py SOLUSDT</code> puis <code>python tools/run_study.py SOLUSDT</code>. Le rapport apparaît ici automatiquement.</li>
      <li>Un résultat passé n'est pas une garantie. Un avantage mesuré de ce genre est modeste et peut disparaître.</li></ul></section>`;
  }

  // ---------- rapport « ta stratégie » ----------
  const sideTxt = s => s === 'inverse' ? 'inverse (le contre de la clôture)' : 'suivre la clôture';
  const cfgTxt = c => { const [a, b, h] = c.split('|'); return ({struct: 'stop sous la structure', atr15: 'stop 1,5 ATR', atr3: 'stop 3 ATR', atr5: 'stop 5 ATR'}[a]) + ' · ' + ({pool: 'objectif poche', pool2R: 'poche sinon 2 R', poolhalf: 'moitié poche 1, reste poche 2'}[b] || 'objectif ' + b.replace('R', ' R')) + ' · ' + ({H24: '24 h', H48: '48 h', H24x: '24 h (48 h si volume)'}[h]); };
  const cfgShort = c => { const [a, b, h] = c.split('|'); return ({struct: 'stop structure', atr15: 'stop 1,5 ATR', atr3: 'stop 3 ATR', atr5: 'stop 5 ATR'}[a]) + ' · ' + ({pool: 'poche', pool2R: 'poche/2R', poolhalf: 'poche ½'}[b] || b.replace('R', ' R')) + ' · ' + ({H24: '24 h', H48: '48 h', H24x: '24→48 h'}[h]); };
  const rcell = (m, big) => !m || m.expR == null ? '<td class="r muted">-</td>' : `<td class="r ${rcol(m.expR)}" title="${m.n} trades">${big ? '<b>' + sgn(m.expR) + '</b>' : sgn(m.expR)}</td>`;

  function stratVerdict(r) {
    const sw = r.kind === 'avwap-swing', b = r.best, lit = r.literal, v = r.verdict, tone = v.level === 'edge' ? 'ok' : v.level === 'weak' ? 'warn' : 'bad';
    const kp = (t, big, sub, cls = '') => `<div class="kpi"><small>${t}</small><b class="${cls}">${big}</b><span>${sub}</span></div>`;
    return `<section class="card btv ${tone}"><div class="bthead"><h2>Verdict : ${sw ? 'VWAP ancrés sur un mouvement de ' + Math.round(r.swing.mainPct * 100) + ' % ou plus' : 'ta stratégie'} <small>${esc(r.label)} · ${dateFr(r.period.start)} → ${dateFr(r.period.end)} · ${r.counts.events.toLocaleString('fr-FR')} ${sw ? 'contacts (dans les deux sens)' : 'signaux'}, ${r.counts.tests} combinaisons testées</small></h2></div>
      <div class="btverdict">${esc(v.text)}</div>
      <ul class="btnotes">${v.notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul>
      <div class="kpis">
        ${kp(sw ? 'Règle littérale (toute clôture)' : 'Ta règle, telle quelle', sgn(lit.all.expR) + ' R', `par trade, après frais · ${lit.all.n} trades`, rcol(lit.all.expR))}
        ${kp('Meilleure variante : apprentissage', sgn(b.is.expR) + ' R', `${yr(r.period.start)}-${yr(r.period.split) - 1} · ${b.is.n} trades`, rcol(b.is.expR))}
        ${kp('… sur le test (jamais vu)', sgn(b.oos.expR) + ' R', `${yr(r.period.split)}-${yr(r.period.end - 1)} · ${b.oos.n} trades`, rcol(b.oos.expR))}
        ${kp('Avant frais', sgn(b.gross) + ' R', `les frais retirent ${num(b.costR)} R par trade`, rcol(b.gross))}
        ${kp('Rythme', num(b.all.perWeek, 1) + ' / sem.', `durée moyenne ${num(b.avgHours, 0)} h`)}
      </div>
      <div class="muted small">« R » = multiple du risque pris : +0,10 R signifie que chaque trade rapporte en moyenne 10 % de la somme risquée, frais compris. L'apprentissage sert à choisir, le test (jamais regardé pour choisir) sert à juger.</div></section>`;
  }

  function stratBest(r) {
    const b = r.best, eras = r.eras || [];
    const head = '<th></th><th class="r">Trades</th><th class="r">Gain moyen (R)</th><th>Intervalle à 90 %</th><th class="r">Réussite</th><th class="r">Facteur de profit</th><th class="r">Baisse max.</th>';
    const row = (lab, m) => `<tr><td>${lab}</td><td class="r">${m.n}</td><td class="r ${rcol(m.expR)}"><b>${sgn(m.expR)}</b></td><td>${ciCell(m)}</td><td class="r">${pc(m.winRate)}</td><td class="r">${num(m.pf)}</td><td class="r">${pc(m.maxDD)}</td></tr>`;
    const rows = row('Tout', b.all) + row('Apprentissage', b.is) + row('Test', b.oos) + (b.eras || []).map(e => row(esc(e.label), e)).join('');
    const yrs = Object.entries(b.years || {}).map(([y, v]) => `<td class="r ${rcol(v.expR)}" title="${v.n} trades">${sgn(v.expR)}</td>`).join('');
    const yh = Object.keys(b.years || {}).map(y => `<th class="r">${y.slice(2)}</th>`).join('');
    const cs = (b.costSens || []).map(x => `<tr><td>${esc(x.name)}</td><td class="r"><b class="${rcol(x.expR)}">${sgn(x.expR)} R</b> par trade</td></tr>`).join('');
    const c = b.control, ctrl = c && c.all && c.all.expMean != null ? `<div class="muted small">Témoin (même nombre de trades, même forme, même tendance, instants tirés au hasard) : <b>${sgn(c.all.expMean)} R</b> en moyenne, 90 % des tirages entre ${sgn(c.all.exp5)} et ${sgn(c.all.exp95)}. La variante fait mieux que ${pc(1 - c.allP)} des tirages${c.oosP != null ? ` (test seul : ${pc(1 - c.oosP)})` : ''}.</div>` : '';
    const sd = b.bySide ? Object.entries(b.bySide).map(([k, v]) => `${k === 'long' ? 'achats' : 'ventes'} : ${sgn(v.expR)} R sur ${v.n}`).join(' · ') : '';
    const eq = b.equity && b.equity.length > 2 ? lineChart([{name: 'Capital (1 % de risque par trade)', pts: b.equity, color: '#4c8dff', end: '×' + num(b.equity[b.equity.length - 1][1], 2), w: 1.8}], {log: false}) : '';
    return `<section class="card"><h2>La variante retenue <small>${esc(b.name)} · ${esc(sideTxt(b.side))}</small></h2>
      <div class="muted small">Sortie : ${esc(cfgTxt(b.cfg))}. Choisie parce que c'est la meilleure statistique t sur l'apprentissage parmi les ${r.counts.tests} combinaisons ; le test n'a servi qu'à la juger.</div>
      <div class="scroll"><table class="bttab vt"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>
      <div class="muted small">Par année (gain moyen par trade) :</div>
      <div class="scroll"><table class="bttab"><thead><tr>${yh}</tr></thead><tbody><tr>${yrs}</tr></tbody></table></div>
      <div class="muted small">${sd}</div>
      <div class="btcharts"><div><div class="muted small">Capital en risquant 1 % par trade <small>(échelle linéaire)</small></div>${eq}</div>
      <div><div class="muted small">Poids des frais</div><table class="bttab"><tbody>${cs}</tbody></table>${ctrl}</div></div></section>`;
  }

  function stratVariants(r) {
    const find = k => r.variants.find(v => v.name === k[0] && v.side === k[1] && v.cfg === k[2]);
    const top = (r.ranking || []).map(find).filter(Boolean);
    const eras = r.eras || [];
    const line = v => `<tr class="${r.best && v.name === r.best.name && v.side === r.best.side && v.cfg === r.best.cfg ? 'cur' : ''}"><td>${esc(v.name)}</td><td class="muted small">${esc(cfgShort(v.cfg))}</td><td>${v.side === 'inverse' ? '<span class="pill warn">inverse</span>' : 'suivre'}</td><td class="r">${v.is.n}</td><td class="r ${rcol(v.is.expR)}"><b>${sgn(v.is.expR)}</b></td><td class="r">${num(v.is.tstat, 1)}</td><td class="r">${v.oos.n}</td><td class="r ${rcol(v.oos.expR)}"><b>${sgn(v.oos.expR)}</b></td><td>${ciCell(v.oos)}</td>${(v.eras || []).map(e => rcell(e)).join('')}</tr>`;
    const th = `<thead><tr><th>Variante</th><th>Sortie</th><th>Sens</th><th class="r">Trades appr.</th><th class="r">Gain appr.</th><th class="r">t</th><th class="r">Trades test</th><th class="r">Gain test</th><th>Test : intervalle 90 %</th>${eras.map(e => `<th class="r">${esc(e.label)}</th>`).join('')}</tr></thead>`;
    const all = showAll ? r.variants.slice().sort((a, b) => (b.is.expR ?? -9) - (a.is.expR ?? -9)) : [];
    return `<section class="card"><h2>Toutes les variantes <small>classées sur l'apprentissage seulement</small></h2>
      <div class="muted small">Chaque ligne est une façon de filtrer tes signaux (échelle, niveau, volume, position face à la zone de valeur du profil de volume, tendance de fond), dans ton sens ou dans le sens contraire. Les 25 meilleures sur l'apprentissage sont ici avec leur résultat sur le test : <b>si le test est loin de l'apprentissage, c'était du hasard</b>.</div>
      <div class="scroll"><table class="bttab vt">${th}<tbody>${top.map(line).join('')}</tbody></table></div>
      <div class="muted small"><a href="#" data-showall="1" onclick="return false">${showAll ? 'Masquer' : 'Voir'} les ${r.variants.length} combinaisons</a></div>
      ${showAll ? `<div class="scroll"><table class="bttab vt">${th}<tbody>${all.map(line).join('')}</tbody></table></div>` : ''}</section>`;
  }

  function stratExits(r) {
    const eras = r.eras || [];
    const ch = new Set(r.chosenExits || []);
    const rows = r.exits.map(x => `<tr class="${ch.has(x.cfg) ? 'cur' : ''}"><td>${esc(cfgTxt(x.cfg))}${ch.has(x.cfg) ? ' <span class="pill ok">retenue</span>' : ''}</td><td class="r">${x.is.n}</td><td class="r ${rcol(x.is.expR)}"><b>${sgn(x.is.expR)}</b></td><td class="r ${rcol(x.oos.expR)}">${sgn(x.oos.expR)}</td><td class="r">${pc(x.is.winRate)}</td><td class="r">${num(x.is.perWeek, 1)}</td></tr>`).join('');
    return `<section class="card"><h2>Les sorties <small>stop, objectif, durée</small></h2>
      <div class="muted small">${r.kind === 'avwap-swing' ? 'La règle littérale (toute clôture sur un VWAP ancré)' : 'Ta règle telle quelle (toute clôture sur un niveau)'}, jouée avec ${r.exits.length} façons de sortir (stop, objectif, durée). Classées sur l'apprentissage ; les meilleures sont gardées pour la suite.</div>
      <div class="scroll"><table class="bttab vt"><thead><tr><th>Sortie</th><th class="r">Trades appr.</th><th class="r">Gain appr. (R)</th><th class="r">Gain test (R)</th><th class="r">Réussite</th><th class="r">Par sem.</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
  }

  function stratHedge(r) {
    const h = r.hedge;
    if (!h || !h.all) return '';
    const w = 0.5, wi = h.weights.indexOf(w) >= 0 ? h.weights.indexOf(w) : 1;
    const base = h.all.main;
    const rows = h.all.rows.slice().sort((a, b) => (a.corr ?? 9) - (b.corr ?? 9)).map(x => {
      const m = x.mix[wi];
      return `<tr><td>${esc(x.name)}</td><td class="r">${x.n}</td><td class="r ${x.corr != null && x.corr < 0 ? 'up' : ''}">${x.corr == null ? '-' : sgn(x.corr)}</td><td class="r ${rcol(x.alone.mean * 20)}">${sgn(x.alone.cagr * 100, 0)} %/an</td><td class="r">${pc(m.maxDD)}</td><td class="r ${m.maxDD < base.maxDD ? 'up' : 'dn'}">${sgn((m.maxDD - base.maxDD) * 100, 0)} pts</td><td class="r">${sgn(m.cagr * 100, 0)} %/an</td></tr>`;
    }).join('');
    const c = h.choice;
    const choice = c ? `<div class="btverdict">Choix sur l'apprentissage : <b>${esc(c.name)}</b> à ${pc(c.w)} du risque de la stratégie principale. Apprentissage : baisse maximale ${pc(c.isMain.maxDD)} → ${pc(c.is.maxDD)}. <b>Test (jamais vu)</b> : ${pc(c.oosMain.maxDD)} → ${pc(c.oos.maxDD)}, rendement annualisé ${sgn(c.oosMain.cagr * 100, 0)} % → ${sgn(c.oos.cagr * 100, 0)} %, corrélation des semaines ${c.corrOos == null ? '-' : sgn(c.corrOos)}.</div>` : '<div class="muted">Aucune couverture ne réduit la baisse maximale sans dégrader fortement le rendement.</div>';
    const cv = r.hedge.curves && r.hedge.curves.main ? lineChart([{name: 'Principale seule', pts: h.curves.main, color: '#9aa0b0', end: '×' + num(h.curves.main[h.curves.main.length - 1][1], 2), w: 1.4}, {name: 'Avec la couverture', pts: h.curves.mix, color: '#4c8dff', end: '×' + num(h.curves.mix[h.curves.mix.length - 1][1], 2), w: 1.8}], {log: true}) : '';
    return `<section class="card"><h2>Couverture <small>quelle variante gagne quand la principale perd ?</small></h2>
      <div class="muted small">Principale : « ${esc(h.main.name)} » (${esc(sideTxt(h.main.side))}). Pour chaque autre variante : corrélation des résultats par semaine (négative = gagne quand la principale perd) et portefeuille « principale + 50 % de la variante », à risque égal de 1 % par trade. Un trade de couverture n'est pas une assurance gratuite : il a ses propres frais et son propre risque.</div>
      ${choice}
      <div class="scroll"><table class="bttab vt"><thead><tr><th>Variante de couverture</th><th class="r">Trades</th><th class="r">Corrélation</th><th class="r">Seule</th><th class="r">Baisse max. du mélange</th><th class="r">Écart</th><th class="r">Rendement du mélange</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="muted small">Principale seule : baisse maximale ${pc(base.maxDD)}, rendement annualisé ${sgn(base.cagr * 100, 0)} %. Chaque ligne est calculée sur toute la période ; le choix retenu ci-dessus est fait sur l'apprentissage puis jugé sur le test.</div>
      ${cv}</section>`;
  }

  function stratMethod(r) {
    return `<section class="card"><h2>Méthode et limites</h2><ul class="btnotes">
      <li><b>Ta stratégie, traduite en règles</b> : sur chaque bougie 1 h ou 4 h qui touche le VWAP ou un VWAP ancré (début de semaine, de mois, plus haut / plus bas de 7 ou 30 jours), on regarde où elle <i>clôture</i> : au-dessus = achat, en dessous = vente. Entrée au marché à l'ouverture de la bougie suivante. Objectif : poche de liquidité visible dans le prix (plus hauts et bas, creux, sommets, niveaux égaux). Durée 24 h, 48 h au plus.</li>
      <li><b>Profil de volume</b> : la clôture est située par rapport à la VAL et à la VAH du profil de la semaine ou du mois (en cours ou précédent). « Réintégration » = la clôture revient dans la zone de valeur depuis l'extérieur, « rejet » = la clôture reste hors de la zone dans le sens du trade.</li>
      <li><b>Pas de fuite du futur</b> : chaque niveau, chaque profil et chaque poche est calculé avec les bougies fermées à l'instant du signal ; les sorties sont jouées sur des bougies de 5 minutes.</li>
      <li><b>Frais</b> : ordre au marché ${num(r.costs.taker * 100, 3)} % + glissement ${num(r.costs.slip * 100, 3)} %, ordre limite ${num(r.costs.maker * 100, 3)} %, financement ${num(r.costs.funding8h * 100, 3)} % par 8 h. Avec 8 à 12 signaux par semaine, les frais deviennent le premier ennemi.</li>
      <li><b>Sélection honnête</b> : sortie choisie sur la règle littérale, filtres classés sur l'apprentissage (${yr(r.period.start)}-${yr(r.period.split) - 1}), jugement unique sur le test (${yr(r.period.split)}-${yr(r.period.end - 1)}). ${r.counts.tests} combinaisons testées : une partie paraît bonne par hasard, d'où le test.</li>
      <li><b>Couverture</b> : calculée par semaine sur des comptes séparés (les positions opposées ne s'annulent pas entre elles, donc les frais sont comptés deux fois : c'est prudent).</li>
      <li><b>Relancer sur ton actif</b> : <code>python tools/run_strategy.py SOLUSDT</code> après <code>python tools/fetch_history.py SOLUSDT</code>.</li>
      <li>Un résultat passé n'est pas une garantie.</li></ul></section>`;
  }

  function reactionCard(r) {
    const sizes = r.swing.sizes, main = sizes.find(x => Math.abs(x.pct - r.swing.mainPct) < 1e-9) || sizes[0];
    const AN = {H: 'sommet de la baisse', L: 'creux de la baisse'}, RE = {tient: 'tient (rejet / rebond)', traverse: 'traverse (cassure)'}, TO = {tous: 'tous', '1er': '1er contact', '2e+': '2e et suivants'};
    const ex = c => !c ? '<td class="r muted">-</td>' : `<td class="r ${Math.abs(c.t) >= 3 ? (c.ex > 0 ? 'up' : 'dn') : 'muted'}" title="${c.n} contacts, t = ${num(c.t, 1)}">${sgn(c.ex * 100)} %</td>`;
    const pr = p => !p ? '<td class="r muted">-</td>' : `<td class="r ${Math.abs(p.sigma) >= 3 ? (p.sigma > 0 ? 'up' : 'dn') : 'muted'}" title="${p.n} cas ; hasard ${pc(p.pBase, 1)}">${pc(p.p, 1)}</td>`;
    const rows = main.reaction.map(x => `<tr><td>${AN[x.anchor]}</td><td>${RE[x.reaction]}</td><td>${TO[x.touch]}</td><td class="r">${x.n}</td>${ex(x.f4)}${ex(x.f24)}${ex(x.f48)}<td class="r ${x.f24 && Math.abs(x.f24.t) >= 3 ? '' : 'muted'}">${x.f24 ? sgn(x.f24.t, 1) : '-'}</td>${ex(x.is24)}${ex(x.oos24)}${pr(x.p)}${pr(x.pOos)}</tr>`).join('');
    const sens = sizes.map(s => {
      const cell = (a, re) => { const x = s.reaction.find(y => y.anchor === a && y.reaction === re && y.touch === 'tous'); return x && x.f24 ? `<td class="r ${Math.abs(x.f24.t) >= 3 ? (x.f24.ex > 0 ? 'up' : 'dn') : 'muted'}" title="${x.n} contacts">${sgn(x.f24.ex * 100)} % <small>t ${sgn(x.f24.t, 1)}</small></td>` : '<td class="r muted">-</td>'; };
      return `<tr><td>≥ ${Math.round(s.pct * 100)} %</td><td class="r">${s.anchorsH + s.anchorsL}</td><td class="r">${s.events.toLocaleString('fr-FR')}</td>${cell('H', 'tient')}${cell('H', 'traverse')}${cell('L', 'tient')}${cell('L', 'traverse')}</tr>`;
    }).join('');
    return `<section class="card"><h2>Comment le prix réagit à ces VWAP ancrés <small>mouvement d'au moins ${Math.round(main.pct * 100)} %</small></h2>
      <div class="muted small">Chaque ligne : après une bougie 1 h qui touche le VWAP ancré, que fait le prix <b>dans le sens de la clôture</b> (au-dessus = achat, en dessous = vente), par rapport à la dérive moyenne du marché ? « Tient » = la clôture reste du même côté qu'avant le contact (rejet sous un sommet, rebond sur un creux) ; « traverse » = elle passe de l'autre côté. Vert / rouge seulement si l'écart est solide (|t| ≥ 3). Dernières colonnes : probabilité d'aller d'abord d'1 ATR dans le sens de la clôture en 24 h (50 % = hasard).</div>
      <div class="scroll"><table class="bttab vt"><thead><tr><th>VWAP ancré sur le</th><th>La clôture</th><th>Contact</th><th class="r">Fois</th><th class="r">4 h</th><th class="r">24 h</th><th class="r">48 h</th><th class="r">t (24 h)</th><th class="r">Appr. 24 h</th><th class="r">Test 24 h</th><th class="r">1 ATR d'abord</th><th class="r">… test</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="muted small">Selon la taille du mouvement (rendement à 24 h dans le sens de la clôture, tous contacts) :</div>
      <div class="scroll"><table class="bttab"><thead><tr><th>Mouvement</th><th class="r">Ancres</th><th class="r">Contacts</th><th class="r">Sommet : tient</th><th class="r">Sommet : traverse</th><th class="r">Creux : tient</th><th class="r">Creux : traverse</th></tr></thead><tbody>${sens}</tbody></table></div></section>`;
  }

  function swingMethod(r) {
    const pct = Math.round(r.swing.mainPct * 100);
    return `<section class="card"><h2>Méthode et limites</h2><ul class="btnotes">
      <li><b>Le mouvement</b> : un zigzag confirmé, sans regarder le futur. Un sommet n'est connu qu'une fois le prix redescendu d'au moins ${pct} % depuis lui ; un creux, une fois remonté d'autant. Le VWAP ancré part de ce sommet (début de la baisse, le prix est dessous : résistance) ou de ce creux (fin de la baisse, le prix est dessus : support), il est suivi ${r.swing.maxAgeDays} jours.</li>
      <li><b>Le contact</b> : une bougie 1 h fermée qui touche le VWAP ancré ; le sens est le côté de la clôture, comme pour tes autres niveaux. Un même VWAP ancré est touché de nombreuses fois (le prix oscille autour) : la ligne « 1er contact » isole le seul moment où ce niveau est « neuf ».</li>
      <li><b>Réaction</b> : rendement après 4 / 24 / 48 h moins la dérive moyenne du marché ; erreur-type regroupée par jour (les contacts d'une même journée ne sont pas indépendants, plusieurs ancres se recouvrent). Probabilité d'aller d'abord d'1 ATR dans le bon sens, comparée à des instants au hasard.</li>
      <li><b>Trades</b> : mêmes règles que pour ta stratégie (entrée au marché à la bougie 5 minutes suivante, frais 0,05 % + glissement 0,02 % + financement), 12 sorties (stop sous la structure, 3 ou 5 ATR ; objectif 1 R ou 2 R ; 24 h ou 48 h), ${r.counts.rules} filtres, deux sens, sortie choisie sur la règle littérale, filtres classés sur l'apprentissage, jugement unique sur le test, témoin au hasard.</li>
      <li><b>Limites</b> : BTC au comptant (Bitstamp), pas SOL ; le zigzag fixe un seuil unique (5, 8 ou 12 %) alors qu'à l'œil on choisit les mouvements ; plusieurs ancres se recouvrent. Un résultat passé n'est pas une garantie.</li>
      <li><b>Relancer sur ton actif</b> : <code>python tools/run_avwap_swing.py SOLUSDT</code> après <code>python tools/fetch_history.py SOLUSDT</code>.</li></ul></section>`;
  }

  // ---------- rapport « indicateurs » ----------
  let indH = 14;
  let sqT = 'RET';
  function indFmt(r, v) {
    if (v == null) return '-';
    if (r.unit === 'pts') return (v >= 0 ? '+' : '−') + num(Math.abs(v) * 100, 1) + ' pt';
    if (r.unit && r.unit.includes('%')) return (v >= 0 ? '+' : '−') + num(Math.abs(v) * 100, Math.abs(v) < 0.01 ? 2 : 1) + ' %';
    return num(v, Math.abs(v) >= 100 ? 0 : 2);
  }
  function indVerdict(r) {
    const c = r.counts, tone = c.informative ? 'ok' : c.hints ? 'warn' : 'bad';
    const kp = (t, big, sub) => `<div class="kpi"><small>${t}</small><b>${big}</b><span>${sub}</span></div>`;
    return `<section class="card btv ${tone}"><div class="bthead"><h2>Indicateurs : que valent-ils vraiment ? <small>${esc(r.label)} · ${dateFr(r.period.start)} → ${dateFr(r.period.end)} · ${c.indicators} indicateurs, ${c.tests} mesures</small></h2></div>
      <div class="btverdict">${esc(r.verdict.text)}</div>
      <ul class="btnotes">${r.verdict.notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul>
      <div class="kpis">${kp('Informatifs', c.informative, 'au-dessus du seuil du hasard, appris puis confirmés sur le test')}${kp('À surveiller', c.hints, 'même signe partout, mais sous le seuil')}${kp('Seuil du hasard', num(r.threshold, 1), '|t| dépassé dans 1 % des cas par un signal sans lien avec le prix')}${kp('Période test', yr(r.period.split) + '-' + yr(r.period.end - 1), 'jamais regardée pour choisir')}</div>
      <div class="muted small">Écart = rendement futur attendu en plus entre le haut et le bas de l'historique de l'indicateur (en points de rendement logarithmique, à l'horizon choisi). « t » mesure la solidité : en dessous du seuil du hasard, on ne peut pas distinguer l'effet du hasard.</div></section>`;
  }
  function hlab(r, h) {
    const hours = (r.stepHours || 24) * h;
    return hours < 48 ? hours + ' h' : (hours / 24) + ' jours';
  }
  function indTable(r, rowsIn, title, sub, opts = {}) {
    const rows0 = rowsIn || r.rows;
    const hs = r.horizons, hk = String(hs.includes(indH) ? indH : hs[Math.floor(hs.length / 2)]);
    const hl = hlab(r, +hk), amp = !!opts.amp, unitSp = r.stepHours ? 'observations' : 'jours';
    const sp = (m) => !m ? '<td class="r muted">-</td>' : `<td class="r ${Math.abs(m.t) >= 2 ? (m.spread > 0 ? 'up' : 'dn') : 'muted'}" title="${m.n} ${unitSp}, t = ${num(m.t, 1)}">${amp ? sgn(m.spread, 2) + ' σ' : sgn(m.spread * 100, 1) + ' %'} <small>t ${sgn(m.t, 1)}</small></td>`;
    const bk = (b, k) => b && b[k] ? (amp ? num(b[k].mean, 2) : `${sgn(b[k].mean * 100, 1)}`) : '-';
    const LV = {informatif: ['ok', 'informatif'], indice: ['warn', 'à surveiller'], rien: ['', 'rien de prouvé']};
    let last = null;
    const GO = ['Prix', 'En chaîne', 'Liquidité', 'Macro'], LO = {informatif: 0, indice: 1, rien: 2};
    const GO2 = r.kind === 'rotation' ? ['Rotation', 'Liquidité', 'Or'] : r.kind === 'squeeze' ? ['Référence', 'Flux (delta, CVD)', 'Divergences', 'Levier (intérêt ouvert)', 'Squeeze'] : GO;
    const sorted = rows0.slice().sort((a, b) => (GO2.indexOf(a.group) - GO2.indexOf(b.group)) || (LO[a.level] - LO[b.level]));
    const rows = sorted.map(x => {
      const d = x.h[hk] || {}, now = x.now;
      const head = x.group !== last ? `<tr class="grp"><td colspan="8">${esc(x.group)}</td></tr>` : ''; last = x.group;
      const lv = LV[x.level];
      const rk = now ? `<span class="rkbar" title="percentile historique ${Math.round(now.rank * 100)} %"><i style="left:${(now.rank * 100).toFixed(0)}%"></i></span>` : '';
      return head + `<tr><td><b>${esc(x.title)}</b><div class="muted small">${esc(x.hypothesis)}</div></td>
        <td class="r">${now ? indFmt(x, now.value) : '-'}<div>${rk}</div></td>${sp(d.is)}${sp(d.oos)}
        <td class="r small">${bk(d.buckets, 'bottom')} / ${bk(d.buckets, 'mid')} / ${bk(d.buckets, 'top')}</td>
        <td>${x.expect ? (x.expectOk ? '<span class="muted small">sens attendu ✓</span>' : '<span class="muted small">sens inverse de l\'attendu</span>') : '<span class="muted small">sens libre</span>'}</td>
        <td><span class="pill ${lv[0]}" ${x.bestH ? `title="jugé sur son meilleur horizon : ${hlab(r, x.bestH)}"` : ''}>${lv[1]}</span></td></tr>`;
    }).join('');
    const btn = hs.map(h => `<button data-indh="${h}" class="seg-like ${String(h) === hk ? 'on' : ''}">${hlab(r, h)}</button>`).join(' ');
    const lagTxt = r.stepHours ? 'une heure de décalage' : 'un jour de décalage';
    return `<section class="card"><h2>${title || 'Les indicateurs'} <small>${sub || 'rendement du bitcoin'} à ${hl}, ${lagTxt}</small></h2>
      <div class="line">Horizon : ${btn}</div>
      <div class="scroll"><table class="bttab vt"><thead><tr><th>${opts.varLabel || 'Indicateur'}</th><th class="r">${opts.nowLabel || "Aujourd'hui"}</th><th class="r">Écart · apprentissage</th><th class="r">Écart · test</th><th class="r">${amp ? 'Ampleur (σ) : bas / milieu / haut' : 'Rendement : bas / milieu / haut (%)'}</th><th>Sens</th><th>Verdict</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="muted small">Bas / milieu / haut = ${amp ? 'ampleur moyenne du mouvement (en écarts-types habituels, 0,8 ≈ normal)' : 'rendement moyen à ' + hl} quand la variable est dans son quintile bas, central ou haut. La barre place la valeur ${opts.nowLabel ? 'de la dernière heure mesurée' : 'actuelle'} dans l'historique de la variable (gauche = bas).</div></section>`;
  }
  function indMethod(r) {
    return `<section class="card"><h2>Méthode et limites</h2><ul class="btnotes">
      <li><b>Données libres</b> : ${esc(r.source || '')}</li>
      <li><b>Pas de futur</b> : chaque indicateur est replacé dans l'historique de ses seules valeurs passées (rang percentile sur fenêtre croissante, un an au moins). Le rendement futur démarre à la clôture du lendemain : la valeur d'un jour n'est connue qu'à la fin du jour.</li>
      <li><b>Mesure</b> : régression du rendement logarithmique futur (7, 14, 30 jours) sur le signal centré ; erreur-type de Newey-West (les fenêtres se chevauchent). Apprentissage jusqu'au ${dateFr(r.period.split)}, test après.</li>
      <li><b>Témoin</b> : le même signal décalé au hasard (≥ 400 jours) garde sa forme mais perd tout lien avec le prix ; son |t| fixe le seuil. ${r.counts.tests} mesures sont faites : quelques-unes paraissent bonnes par hasard, d'où le seuil et le test.</li>
      <li><b>Limites</b> : un seul actif (BTC), des séries journalières, peu de cycles de marché (2013-2026) ; la puissance est limitée. Les indicateurs de dérivés (financement, Open Interest, options, liquidations) n'ont pas d'historique libre : le terminal les enregistre désormais lui-même pour pouvoir les mesurer plus tard.</li>
      <li><b>Relancer</b> : <code>python tools/run_indicators.py</code> (quelques secondes, aucune clé).</li></ul></section>`;
  }

  // ---------- rapport « rotation du capital et or » ----------
  let rotT = 'BTC';
  function rotVerdict(r) {
    const v = r.verdict, tone = v.informative ? 'ok' : v.hints ? 'warn' : 'bad';
    const c90 = (r.gold.corr || {})['90'], semi = (r.gold.semi || {}).all;
    const kp = (t, big, sub) => `<div class="kpi"><small>${t}</small><b>${big}</b><span>${sub}</span></div>`;
    return `<section class="card btv ${tone}"><div class="bthead"><h2>Où est l'argent ? <small>${esc(r.label)} · ${dateFr(r.period.start)} → ${dateFr(r.period.end)} · rotation du capital, or et bitcoin</small></h2></div>
      <div class="btverdict">${esc(v.text)}</div>
      <ul class="btnotes">${v.notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul>
      <div class="kpis">${kp('Liens prouvés', v.informative, 'sur 81 mesures, au-dessus du seuil du hasard')}${kp('À surveiller', v.hints, 'même signe partout, sous le seuil')}
        ${kp('Corrélation bitcoin / or', c90 ? sgn(c90.mean, 2) : '-', 'moyenne, fenêtres de 90 jours')}${kp('Asymétrie or hausse / baisse', semi ? sgn(semi.asym.diff, 2) : '-', semi ? 't = ' + sgn(semi.asym.t, 1) + (Math.abs(semi.asym.t) >= 2 ? ' : significatif' : ' : non démontrée') : '')}</div></section>`;
  }
  function rotMap(r) {
    const m = r.map, s = m.snapshot;
    if (!s) return '';
    const pt = v => v == null ? '<td class="r muted">-</td>' : `<td class="r ${v > 0.0005 ? 'up' : v < -0.0005 ? 'dn' : 'muted'}">${sgn(v * 100, 1)} pt</td>`;
    const rows = s.rows.map(x => `<tr><td>${esc(x.label)}</td><td class="r"><b>${num(x.share * 100, 1)} %</b></td>${pt(x.d7)}${pt(x.d30)}</tr>`).join('');
    const rl = (lab, k7, k30) => `<tr><td>${lab}</td>${rcellp(s.rel[k7])}${rcellp(s.rel[k30])}</tr>`;
    const rcellp = v => v == null ? '<td class="r muted">-</td>' : `<td class="r ${v > 0.005 ? 'up' : v < -0.005 ? 'dn' : 'muted'}">${sgn(v * 100, 1)} %</td>`;
    return `<section class="card"><h2>Carte du capital <small>au ${dateFr(s.date)} · panier suivi : BTC, ETH, 10 altcoins${s.stableUsd ? ' · stablecoins ' + num(s.stableUsd / 1e9, 0) + ' Md$' : ''}</small></h2>
      <div class="muted small">${esc(m.reading.text)}</div>
      <div class="btcharts"><div><table class="bttab"><thead><tr><th>Part du capital</th><th class="r">Aujourd'hui</th><th class="r">7 jours</th><th class="r">30 jours</th></tr></thead><tbody>${rows}</tbody></table>
        <table class="bttab" style="margin-top:8px"><thead><tr><th>Performance relative</th><th class="r">7 jours</th><th class="r">30 jours</th></tr></thead><tbody>${rl('ETH contre BTC', 'eth7', 'eth30')}${rl('Altcoins contre BTC', 'alts7', 'alts30')}${rl('SOL contre BTC', 'sol7', 'sol30')}${rl('Or contre BTC', 'gold7', 'gold30')}</tbody></table></div>
        <div><div class="muted small">Parts du panier (BTC + ETH + 10 altcoins), hebdomadaire</div><div id="rotChart" class="svgbox"></div></div></div>
      <div class="muted small">Le panier n'est pas tout le marché : il mesure des <b>parts</b> et leurs variations, pas des montants. « Stablecoins » = part de l'offre de stablecoins (USDT, USDC, DAI) face au panier plus eux : c'est la poudre sèche.</div></section>`;
  }
  function drawRotation(r) {
    const el = document.getElementById('rotChart');
    if (!el || !r.map.series.length || typeof Charts === 'undefined') return;
    const ser = (i, name, color) => ({name, color, pts: r.map.series.filter(p => p[i] != null).map(p => [p[0], p[i] * 100]), area: false});
    Charts.line(el, {series: [ser(1, 'Bitcoin', '#f7931a'), ser(2, 'ETH', '#7b8cff'), ser(3, 'Altcoins', '#3ddc97'), ser(4, 'Stablecoins (part)', '#9aa0b0')], height: 200, yFmt: v => num(v, 0) + ' %', xFmt: t => new Date(t).getUTCFullYear(), xTicks: 6});
  }
  function rotGold(r) {
    const g = r.gold, sm = g.semi || {};
    const cell = m => !m ? '<td class="r muted">-</td>' : `<td class="r ${Math.abs(m.t) >= 2 ? (m.beta > 0 ? 'up' : 'dn') : 'muted'}">${sgn(m.beta, 2)} <small>t ${sgn(m.t, 1)}</small></td>`;
    const semiRow = (lab, k) => { const x = sm[k]; return x ? `<tr><td>${lab}</td><td class="r">${x.n}</td>${cell({beta: x.up.beta, t: x.up.t})}${cell({beta: x.down.beta, t: x.down.t})}<td class="r ${Math.abs(x.asym.t) >= 2 ? 'up' : 'muted'}">${sgn(x.asym.diff, 2)} <small>t ${sgn(x.asym.t, 1)}</small></td></tr>` : ''; };
    const co = Object.entries(g.corr || {}).filter(([, v]) => v).map(([w, v]) => `<tr><td>${w} jours</td><td class="r">${sgn(v.mean, 2)}</td><td class="r">${sgn(v.min, 2)}</td><td class="r">${sgn(v.max, 2)}</td><td class="r">${num(v.positive * 100, 0)} %</td></tr>`).join('');
    const sh = ((g.shocks || {}).all || []).filter(x => x.same).map(x => `<tr><td>${esc(x.label)}</td><td class="r">${x.n}</td><td class="r ${rcol(x.same.mean * 10)}">${sgn(x.same.mean * 100, 2)} %</td><td class="r ${rcol(x.next.mean * 10)}">${sgn(x.next.mean * 100, 2)} % <small>t ${sgn(x.next.t, 1)}</small></td><td class="r">${sgn(x.next5.mean * 100, 2)} %</td></tr>`).join('');
    const ll = ((g.leadLag || {}).all || []).map(x => `<tr><td>or sur les ${x.k} jour(s) précédent(s)</td><td class="r">${x.beta == null ? '-' : sgn(x.beta, 3)}</td><td class="r ${x.t != null && Math.abs(x.t) >= 2 ? 'up' : 'muted'}">${x.t == null ? '-' : sgn(x.t, 1)}</td></tr>`).join('');
    return `<section class="card"><h2>Bitcoin et or <small>l'asymétrie existe-t-elle ?</small></h2>
      <div class="muted small">Or = jeton PAXG (1 jeton = 1 once, coté 24 h / 24, week-ends compris), rendements quotidiens depuis février 2020. Bêta = de combien le bitcoin bouge pour 1 de l'or.</div>
      <div class="scroll"><table class="bttab vt"><thead><tr><th>Période</th><th class="r">Jours</th><th class="r">Bêta quand l'or monte</th><th class="r">Bêta quand l'or baisse</th><th class="r">Écart (asymétrie)</th></tr></thead><tbody>${semiRow('Tout', 'all')}${semiRow('Apprentissage', 'is')}${semiRow('Test', 'oos')}</tbody></table></div>
      <div class="btcharts"><div><div class="muted small">Corrélation glissante</div><table class="bttab"><thead><tr><th>Fenêtre</th><th class="r">Moyenne</th><th class="r">Min</th><th class="r">Max</th><th class="r">Positive</th></tr></thead><tbody>${co}</tbody></table></div>
        <div><div class="muted small">Jours de choc de l'or (± 1,5 %) : rendement du bitcoin</div><table class="bttab"><thead><tr><th>Choc</th><th class="r">Jours</th><th class="r">Même jour</th><th class="r">Lendemain</th><th class="r">5 jours</th></tr></thead><tbody>${sh}</tbody></table></div></div>
      <div class="muted small">L'or d'hier explique-t-il le bitcoin d'aujourd'hui ? (régression, t ≥ 2 = signal)</div>
      <table class="bttab"><thead><tr><th>Variable</th><th class="r">Pente</th><th class="r">t</th></tr></thead><tbody>${ll}</tbody></table></section>`;
  }
  function rotTargets(r) {
    const t = r.targets.find(x => x.key === rotT) || r.targets[0];
    const btn = r.targets.map(x => `<button data-rott="${esc(x.key)}" class="seg-like ${x.key === t.key ? 'on' : ''}">${esc(x.title)}</button>`).join(' ');
    return `<section class="card"><h2>Que prédit la rotation ? <small>cible choisie : ${esc(t.title)}</small></h2><div class="line">Cible : ${btn}</div><div class="muted small">${esc(t.desc)} Seuil du hasard : |t| ≥ ${num(t.threshold, 1)}.</div></section>` + indTable(r, t.rows, 'Les indicateurs de rotation', t.title.toLowerCase());
  }
  function rotMethod(r) {
    return `<section class="card"><h2>Méthode et limites</h2><ul class="btnotes">
      <li><b>Données libres</b> : ${esc(r.source || '')}</li>
      <li><b>Panier</b> : BTC, ETH, SOL et 10 altcoins présents depuis 2019 (BNB, XRP, ADA, DOGE, TRX, LINK, LTC, BCH, XLM, ATOM), capitalisation estimée quotidienne. Ce n'est pas tout le marché : les parts sont celles du panier.</li>
      <li><b>Mesure</b> : même méthode que les indicateurs (rang percentile sur fenêtre croissante, rendement futur à 7 / 14 / 30 jours avec un jour de décalage, Newey-West, apprentissage jusqu'au ${dateFr(r.period.split)}, test après, témoin par décalage au hasard), appliquée à trois cibles : le bitcoin, les altcoins contre le bitcoin, l'or contre le bitcoin.</li>
      <li><b>Limites</b> : moins de 7 ans de données (depuis juin 2019), donc peu de cycles et un seuil du hasard élevé ; PAXG suit l'or de près mais pas exactement (écart de l'ordre de 1 à 3 % avec les prix mensuels). La situation géopolitique n'est pas mesurable directement : on la voit à travers le pétrole, la volatilité et le dollar (page « indicateurs »).</li>
      <li><b>Relancer</b> : <code>python tools/run_rotation.py</code> (quelques secondes, aucune clé).</li></ul></section>`;
  }

  // ---------- rapport « importance des poches » (V14) ----------
  const VCLS = v => /^effet \+|^indice \+/.test(v) ? 'up' : /^effet −|^indice −/.test(v) ? 'dn' : 'muted';
  function pkVerdict(r) {
    const s = r.summary || {lines: []};
    return `<section class="card btv warn"><div class="bthead"><h2>Poches de liquidité : taille, confluences, âge <small>${esc(r.label)} · ${esc(r.period.text)} · ${r.stats.touches} premiers contacts · ${r.stats.samples} mesures d'attraction</small></h2></div>
      <ul class="btnotes">${s.lines.map(n => `<li>${esc(n)}</li>`).join('')}</ul>
      <div class="muted small">« Écart » = ce qui est arrivé moins ce que la seule position du prix (ou la seule distance) laissait attendre, en points de pourcentage. « effet » = même signe à l'apprentissage et au test, chacun au-delà de 2 erreurs-types ; « indice » = même signe partout, l'ensemble au-delà de 2 ; erreurs-types regroupées par jour.</div></section>`;
  }
  function pkRows(rows, dims) {
    let last = null;
    return rows.map(x => {
      const dim = x.dim, head = dim !== last ? `<tr class="grp"><td colspan="7">${esc(dims[dim] || dim)}</td></tr>` : '';
      last = dim;
      const e = v => v == null ? '-' : sgn(v * 100, 1);
      return head + `<tr><td>${esc(x.name)}</td><td class="r">${x.n}</td><td class="r">${pc(x.p, 1)}</td><td class="r muted">${pc(x.exp, 1)}</td><td class="r ${VCLS(x.verdict)}"><b>${e(x.ex)}</b></td>
        <td class="r small">${e(x.is.ex)} / ${e(x.oos.ex)}</td><td class="${VCLS(x.verdict)}">${esc(x.verdict)}</td></tr>`;
    }).join('');
  }
  function pkTable(r, key) {
    const att = key === 'attraction';
    return `<section class="card"><h2>${att ? 'Attraction : le prix va-t-il chercher la poche ?' : 'Réaction au premier contact : le prix se retourne-t-il ?'} <small>${att ? 'atteinte en 24 h, comparée à la même distance n\'importe où' : 'repart d\'une amplitude moyenne (ATR 1 h) dans l\'autre sens avant d\'en faire une de plus'}</small></h2>
      <div class="scroll"><table class="bttab vt"><thead><tr><th>Groupe</th><th class="r">Cas</th><th class="r">${att ? 'Atteinte' : 'Retournement'}</th><th class="r">Attendu</th><th class="r">Écart</th><th class="r">Apprentissage / test</th><th>Verdict</th></tr></thead>
      <tbody>${pkRows(r[key], r.dims || {})}</tbody></table></div></section>`;
  }
  function pkSweep(r) {
    const pick = (m, d) => r.sweep.filter(x => x.dim === m && x.name.startsWith(d + '|')).map(x => ({...x, dim: m + ':' + d, name: x.name.split('|')[1]}));
    const rows = ['all', 'confw', 'age'].flatMap(d => pick('sweep', d).concat(pick('break', d)));
    const dims = {'sweep:all': 'Mèche à travers puis clôture revenue (balayage)', 'break:all': 'Clôture au-delà de la poche (cassure)', 'sweep:confw': 'Balayage, selon les confluences', 'break:confw': 'Cassure, selon les confluences', 'sweep:age': 'Balayage, selon l\'âge', 'break:age': 'Cassure, selon l\'âge'};
    return `<section class="card"><h2>Balayage ou cassure <small>retournement selon la façon dont la bougie de contact se ferme</small></h2><div class="scroll"><table class="bttab vt"><thead><tr><th>Groupe</th><th class="r">Cas</th><th class="r">Retournement</th><th class="r">Attendu</th><th class="r">Écart</th><th class="r">Apprentissage / test</th><th>Verdict</th></tr></thead><tbody>${pkRows(rows, dims)}</tbody></table></div></section>`;
  }
  function pkMethod(r) {
    return `<section class="card"><h2>Méthode et limites</h2><ul class="btnotes">
      <li><b>Poches mesurées</b> : plus hauts / plus bas de la veille, de la semaine et du mois précédents, creux et sommets confirmés sur 1 h, et extrêmes presque égaux (moins de 0,15 % d'écart). Âge = depuis quand le prix n'est plus revenu à ce niveau. Confluences = niveaux d'autres sources (VWAP, ouvertures, profils de volume, POC nus, nombres ronds, plus hauts / bas d'autres périodes) à moins de 0,3 amplitude moyenne d'une bougie d'une heure, pondérées comme dans le terminal (année 10, mois 9, semaine 7, jour 4).</li>
      <li><b>Attraction</b> : chaque jour à 00 h UTC, chaque poche intacte entre 0,5 et 8 amplitudes ; atteinte dans les 24 h comparée à la fréquence d'atteinte de la même distance sur tout l'historique. Témoin : niveaux tirés au hasard.</li>
      <li><b>Réaction</b> : au premier contact, depuis la clôture de la bougie de contact ; « attendu » = taux d'une marche au hasard depuis la même position (correction de dépassement). Horizon ${r.horizon} h, seuil ${num(r.k, 1)} amplitude.</li>
      <li><b>Limites</b> : un seul actif (BTC au comptant, Bitstamp) ; les poches estimées par l'intérêt ouvert ne sont pas testables (29 jours d'historique chez Binance) ; les effets mesurés sont petits (quelques points de pourcentage), utiles pour classer, pas pour trader seuls.</li>
      <li><b>Relancer sur SOL</b> : <code>python tools/fetch_history.py SOLUSDT</code> puis <code>python tools/run_pocket_study.py SOLUSDT</code>. Le rapport s'ajoute à cette liste.</li></ul></section>`;
  }

  // ---------- rapport « delta, CVD et squeezes » ----------
  function sqVerdict(r) {
    const v = r.verdict, tone = v.informative ? 'ok' : v.hints ? 'warn' : 'bad';
    const real = (r.source || '').startsWith('réel');
    const kp = (t, big, sub) => `<div class="kpi"><small>${t}</small><b>${big}</b><span>${sub}</span></div>`;
    const nT = r.targets.reduce((a, t) => a + t.counts.tests, 0);
    return `<section class="card btv ${tone}"><div class="bthead"><h2>Delta, CVD, volume et squeezes <small>${esc(r.label)} · ${dateFr(r.period.start)} → ${dateFr(r.period.end)} · ${nT} mesures</small></h2></div>
      <div class="btverdict">${esc(v.text)}</div>
      <ul class="btnotes">${v.notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul>
      <div class="kpis">${kp('Liens prouvés', v.informative, 'au-dessus du seuil du hasard, appris puis confirmés sur le test')}${kp('À surveiller', v.hints, 'même signe partout, sous le seuil')}
        ${kp('Delta', real ? 'réel' : 'estimé', real ? 'volume acheteur agressif de la bourse' : 'déduit de la position de la clôture dans la bougie')}${kp('Intérêt ouvert', r.hasOi ? 'réel' : 'absent', r.hasOi ? 'carburants de squeeze mesurés' : 'squeezes non mesurables ici')}</div></section>`;
  }
  function sqEvents(r) {
    const base = r.baseline || {};
    const cell = (x) => !x ? '<td class="r muted" colspan="3">trop peu de cas</td>' : `<td class="r ${x.mean > 0.0005 ? 'up' : x.mean < -0.0005 ? 'dn' : 'muted'}" title="${x.n} observations">${sgn(x.mean * 100, 2)} %<div class="muted small">${num(x.up * 100, 0)} % de hausses</div></td><td class="r">${x.bigUp == null ? '-' : num(x.bigUp * 100, 0) + ' %'}</td><td class="r">${x.bigDn == null ? '-' : num(x.bigDn * 100, 0) + ' %'}</td>`;
    const rows = (r.events || []).map(e => `<tr><td>${esc(e.title)}</td><td>${e.side === 'haut' ? 'décile haut' : 'décile bas'}</td>${cell(e.is)}${cell(e.oos)}</tr>`).join('');
    const baseRow = base.is && base.oos ? `<tr class="grp"><td colspan="2">Toutes les observations (taux de base)</td>${cell(base.is)}${cell(base.oos)}</tr>` : '';
    return `<section class="card"><h2>Quand la configuration se présente <small>ce qui se passe dans les 24 heures suivantes</small></h2>
      <div class="muted small">Décile haut / bas = les 10 % d'heures où la variable est la plus haute / la plus basse de son historique passé. « Gros mouvement » = le prix va d'au moins 1,5 écart-type habituel dans ce sens (plus haut ou plus bas atteint dans les 24 h). Compare toujours avec le taux de base.</div>
      <div class="scroll"><table class="bttab vt"><thead><tr><th>Variable</th><th>Cas</th><th class="r">Rendement 24 h · apprentissage</th><th class="r">Gros mouvement ↑</th><th class="r">Gros mouvement ↓</th><th class="r">Rendement 24 h · test</th><th class="r">Gros mouvement ↑</th><th class="r">Gros mouvement ↓</th></tr></thead><tbody>${baseRow}${rows}</tbody></table></div></section>`;
  }
  function sqTargets(r) {
    const t = r.targets.find(x => x.key === sqT) || r.targets[0];
    const btn = r.targets.map(x => `<button data-sqt="${esc(x.key)}" class="seg-like ${x.key === t.key ? 'on' : ''}">${esc(x.title)}</button>`).join(' ');
    return `<section class="card"><h2>Que prédisent le flux et le levier ? <small>cible choisie : ${esc(t.title)}</small></h2><div class="line">Cible : ${btn}</div><div class="muted small">${esc(t.desc)} Seuil du hasard : |t| ≥ ${num(t.threshold, 1)}.</div></section>`
      + indTable(r, t.rows, 'Les variables de flux et de levier', t.title.toLowerCase(), {amp: t.key === 'AMP', varLabel: 'Variable', nowLabel: 'Dernière heure'});
  }
  function sqMethod(r) {
    const real = (r.source || '').startsWith('réel');
    return `<section class="card"><h2>Méthode et limites</h2><ul class="btnotes">
      <li><b>Données</b> : ${esc(r.source || '')}</li>
      <li><b>Variables</b> : déséquilibre du flux (delta / volume), écart entre le prix et le flux (le prix fait-il mieux que ce que le CVD explique ?), delta récent contre CVD de fond, volume anormal et « effort sans résultat ». Avec l'intérêt ouvert : « carburant » de short squeeze (OI en hausse, flux vendeur, prix qui ne baisse pas) et de long squeeze (miroir), squeeze en cours (le prix s'envole pendant que l'OI chute) et financement. Toutes en écarts-types des 30 derniers jours, sans regarder le futur.</li>
      <li><b>Mesure</b> : une observation toutes les 6 heures, rendement futur à 6, 24 et 72 h après une heure de décalage, Newey-West, apprentissage jusqu'au ${dateFr(r.period.split)} puis test, témoin par décalage au hasard. Deuxième cible : l'ampleur du mouvement (un squeeze est un mouvement plus grand que d'habitude, dont le sens se lit après).</li>
      <li><b>Limites</b> : ${real ? 'les archives publiques de Binance (perpétuel USDT-M) ne remontent qu\'à décembre 2021 pour l\'intérêt ouvert' : 'le delta est une estimation (le vrai volume acheteur agressif n\'existe pas pour cette période) et il n\'y a pas d\'intérêt ouvert : les carburants de squeeze ne sont pas mesurés ici'} ; un seul actif ; peu de squeezes marqués (une centaine d\'épisodes), donc un seuil du hasard élevé. « Rien de prouvé » ne veut pas dire « rien » : l\'effet peut exister sans être assez fort pour être distingué du hasard.</li>
      <li><b>Mesurer avec le vrai delta, l'OI et le financement (≥ 4 ans, Binance)</b> : <code>python tools/fetch_history.py BTCUSDT --since 2021-12 --metrics</code> puis <code>python tools/run_squeeze_study.py BTCUSDT</code> (idem <code>SOLUSDT</code>). Le rapport remplace celui-ci dans la liste.</li></ul></section>`;
  }

  function render() {
    const root = $('#btBox');
    if (!root) return;
    if (error && !rep) { root.innerHTML = `<section class="card"><div class="dn">Rapport indisponible : ${esc(error)}</div></section>`; return; }
    if (loading && !rep) { root.innerHTML = '<section class="card"><div class="muted">Chargement du rapport…</div></section>'; return; }
    if (!list || !list.length) { root.innerHTML = '<section class="card"><h2>Backtest</h2><div class="muted">Aucun rapport trouvé. Lance <code>python tools/run_study.py BTCUSDT</code> après avoir téléchargé l\'historique (<code>python tools/fetch_history.py BTCUSDT</code>).</div></section>'; return; }
    if (!rep) return;
    const kname = k => k === 'strategy' ? 'ta stratégie VWAP / profil de volume' : k === 'avwap' ? 'VWAP ancrés sur un mouvement de 5 % ou plus' : k === 'indicators' ? 'indicateurs (en chaîne, macro, liquidité)' : k === 'rotation' ? 'où va l\'argent (rotation, or)' : k === 'squeeze' ? 'delta, CVD et squeezes' : k === 'pockets' ? 'importance des poches (confluences, âge)' : 'idées du terminal';
    const sel = `<div class="btbar"><label>Rapport <select id="btSel">${list.map(x => `<option value="${esc(x.kind)}|${esc(x.label)}" ${x.label === label && x.kind === kind ? 'selected' : ''}>${esc(x.label)} · ${kname(x.kind)}${x.own ? ' (calculé sur tes données)' : ' (livré avec le terminal)'}</option>`).join('')}</select></label>
      <span class="muted small">Calculé le ${dateFr(rep.computedAt)} en ${rep.seconds < 90 ? rep.seconds + ' s' : Math.round(rep.seconds / 60) + ' min'}</span></div>`;
    if (rep.kind === 'vwap-strategy') { root.innerHTML = sel + '<div class="btgrid">' + stratVerdict(rep) + stratBest(rep) + stratVariants(rep) + stratExits(rep) + stratHedge(rep) + stratMethod(rep) + '</div>'; return; }
    if (rep.kind === 'rotation') { root.innerHTML = sel + '<div class="btgrid">' + rotVerdict(rep) + rotMap(rep) + rotGold(rep) + rotTargets(rep) + rotMethod(rep) + '</div>'; drawRotation(rep); return; }
    if (rep.kind === 'pockets') { root.innerHTML = sel + '<div class="btgrid">' + pkVerdict(rep) + pkTable(rep, 'reaction') + pkTable(rep, 'attraction') + pkSweep(rep) + pkMethod(rep) + '</div>'; return; }
    if (rep.kind === 'squeeze') { root.innerHTML = sel + '<div class="btgrid">' + sqVerdict(rep) + sqEvents(rep) + sqTargets(rep) + sqMethod(rep) + '</div>'; return; }
    if (rep.kind === 'indicators') { root.innerHTML = sel + '<div class="btgrid">' + indVerdict(rep) + indTable(rep) + indMethod(rep) + '</div>'; return; }
    if (rep.kind === 'avwap-swing') { root.innerHTML = sel + '<div class="btgrid">' + stratVerdict(rep) + reactionCard(rep) + stratBest(rep) + stratVariants(rep) + stratExits(rep) + swingMethod(rep) + '</div>'; return; }
    root.innerHTML = sel + '<div class="btgrid">' + verdictCard(rep) + trendCard(rep) + equityCard(rep) + variantsCard(rep) + eventsCard(rep) + touchCard(rep) + regimeCard(rep) + costsCard(rep) + methodCard(rep) + '</div>';
  }

  return {init, show, render};
})();
