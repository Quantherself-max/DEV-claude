// Idees de trade : cartes (quoi faire / pourquoi / probabilites), validation historique, journal.
const Signals = (() => {
  let LT = null, root = null, last = null;
  const open = new Set();
  const xres = {};                                                    // avis d'influenceurs deja lus (cle symbole|sens)
  const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const px = v => v == null ? '-' : LT.fmtP(v);
  const chg = (v, e) => LT.sPct((v / e - 1) * 100);
  const timeFr = ms => new Date(ms).toLocaleString('fr-FR', {weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
  const KIND = {rebond: 'Rebond sur une zone (ordre à cours limité)', reprise: 'Retournement après balayage (entrée immédiate)'};
  const STATUS = {pending: ['Ordre en attente', 'warn'], active: ['Position ouverte', 'ok'], tp1: ['Objectif 1 atteint', 'ok']};
  const RESULT = {stop: ['Stop touché', 'dn'], tp1_be: ['Objectif 1 puis retour à l\'entrée', 'muted'], tp2: ['Objectif 2 atteint', 'up'],
    missed: ['Objectif atteint sans exécution', 'muted'], expired: ['Expirée sans exécution', 'muted'], expired_active: ['Suivi terminé', 'muted']};
  const VERDICT = {edge: ['Mieux que le hasard', 'up'], none: ['Pas mieux que le hasard', 'muted'], worse: ['Moins bien que le hasard', 'dn'], thin: ['Trop peu de cas', 'muted']};
  const pc = x => x == null ? '-' : Math.round(x * 100) + ' %';
  const tone = s => s >= 75 ? 'up' : s >= 65 ? 'amb' : 'muted';

  function init(lt) {
    LT = lt; root = document.getElementById('sigBox');
    if (!root) return;
    root.addEventListener('click', e => {
      const xb = e.target.closest('button[data-x]');
      if (xb) { loadX(xb.dataset.x, xb.dataset.side); return; }
      const b = e.target.closest('button[data-plan]');
      if (b) { LT.setPlan(b.dataset.plan); render(last); return; }
      if (e.target.closest('[data-plan-off]')) { LT.setPlan('off'); render(last); }
    });
    root.addEventListener('toggle', e => {
      const d = e.target; if (!d.dataset || !d.dataset.key) return;
      d.open ? open.add(d.dataset.key) : open.delete(d.dataset.key);
    }, true);
  }

  const XSTANCE = {bull: 'haussier', bear: 'baissier', mixed: 'mitigé', unclear: 'sans position claire', none: 'aucun post récent'};
  const XREL = {agree: ["✅ d'accord", 'up'], disagree: ['❌ en désaccord', 'dn'], neutral: ['➖ sans avis net', 'muted'], none: ['… aucun post récent', 'muted']};
  async function loadX(sym, side) {
    const k = sym + '|' + side;
    xres[k] = {loading: true}; render(last);
    try { xres[k] = await LT.api(`/api/influencers?symbol=${sym}&side=${side}`); } catch (e) { xres[k] = {error: e.message}; }
    render(last);
  }
  function xBlock(i, sym) {
    const k = sym + '|' + i.side, r = xres[k];
    const head = '<h5>Avis d\'influenceurs sur X <small>(facultatif, indicatif : n\'entre pas dans le score)</small></h5>';
    const btn = `<button data-x="${esc(sym)}" data-side="${i.side}">Voir l'avis des comptes X</button>`;
    if (!r) return head + `<div class="xbox">${btn}<div class="muted small">Lit les derniers posts des comptes configurés dans ⚙ section 5 (coût : environ 0,005 $ par post lu). Facultatif.</div></div>`;
    if (r.loading) return head + '<div class="muted small">Lecture des posts…</div>';
    if (r.error) return head + `<div class="dn small">Indisponible : ${esc(r.error)}</div>${btn}`;
    if (!r.on) return head + '<div class="muted small">Non configuré : ajoute un jeton X et des comptes dans ⚙ section 5.</div>';
    const s = r.summary;
    const rows = r.accounts.map(a => a.error ? `<li class="warnl">@${esc(a.handle)} : indisponible (${esc(a.error)})</li>` : `<li><b class="${XREL[a.relation][1]}">${XREL[a.relation][0]}</b> @${esc(a.handle)}${a.stance !== 'none' ? ` <span class="muted">(${XSTANCE[a.stance]}, ${a.bull} haussier(s), ${a.bear} baissier(s))</span>` : ''}${a.excerpt ? `<div class="muted small">« ${esc(a.excerpt)} »${a.url ? ` <a href="${esc(a.url)}" target="_blank" rel="noopener">voir</a>` : ''}</div>` : ''}</li>`).join('');
    return head + `<div class="small">${s.agree} d'accord · ${s.disagree} en désaccord · ${s.neutral} sans avis net · ${s.none} sans post récent${s.errors ? ` · ${s.errors} indisponible(s)` : ''}</div><ul>${rows}</ul>
      <div class="muted small">Lecture automatique par mots-clés : elle peut se tromper, lis le post. Posts lus : ${r.cost.posts} (≈ ${String(r.cost.usd.toFixed(3)).replace('.', ',')} $). ${btn}</div>`;
  }

  function rr(x) { return x == null ? '' : ` · ${String(x.toFixed(1)).replace('.', ',')} fois le risque`; }

  function lines(arr, cls) {
    return arr.map(x => /^\s{2}•/.test(x) ? `<li class="sub">${esc(x.replace(/^\s*•\s*/, ''))}</li>` : `<li class="${cls || ''}">${esc(x)}</li>`).join('');
  }

  const GATE_SHORT = [[/^l'idée va contre la tendance/, 'contre la tendance de fond'], [/^tendance de fond indécise/, 'tendance de fond indécise'], [/^pas assez de liquidité/, 'pas assez de liquidité'],
    [/^le contexte macro/, 'macro contraire']];
  const shortGate = g => { const m = GATE_SHORT.find(([re]) => re.test(g)); return m ? m[1] : g.length > 42 ? g.slice(0, 40) + '…' : g; };

  function card(i, sg, trade) {
    const buy = i.side === 'long', col = buy ? 'up' : 'dn', d = i.desc;
    const status = trade ? (trade.status === 'closed' ? RESULT[trade.result] : STATUS[trade.status]) : null;
    const sent = trade ? `<span class="pill ${status ? status[1] : ''}">${esc(status ? status[0] : '')}</span>` : '';
    const gate = (i.gates || [])[0];
    const state = trade ? sent : gate ? `<span class="pill warn" title="${esc(i.gates.join(' · '))}">Filtre : ${esc(shortGate(gate))}</span>` : i.hold.length ? `<span class="pill warn" title="${esc(i.hold.join(' · '))}">En attente : annonce</span>`
      : i.eligible ? '<span class="pill up">Au-dessus du seuil</span>' : `<span class="pill muted">Sous le seuil (${sg.minScore})</span>`;
    const al = i.align, tpill = al == null ? '' : al > 0 ? '<span class="pill up" title="Le cours est du même côté des moyennes de 50 et 200 jours que l\'idée : c\'est la seule catégorie qui a rapporté dans le backtest">Dans le sens de la tendance</span>'
      : al < 0 ? '<span class="pill dn" title="Idée à contre-courant : la catégorie qui a perdu dans le backtest">À contre-courant</span>' : '<span class="pill warn" title="Cours entre les moyennes de 50 et 200 jours : aucun avantage mesuré">Tendance indécise</span>';
    const comps = i.comps.map(c => `<div class="cmp"><span>${esc(c.label)}</span><i><b style="width:${Math.round(100 * c.pts / c.max)}%"></b></i><em>${c.pts.toFixed(0)}/${c.max}</em></div>`).join('');
    const best = sg.ideas.find(x => x.eligible);
    const shown = LT.st.planOn && (LT.st.planKey === i.key || (LT.st.planKey == null && best && best.key === i.key));
    return `<div class="idea ${col}">
      <div class="ihead"><b class="side ${col}">${buy ? 'ACHAT' : 'VENTE'}</b><span class="muted small">${esc(KIND[i.kind] || i.kind)}</span>
        <span class="score ${tone(i.score)}" title="Qualité de l'idée sur 100">${i.score.toFixed(0)}<small>/100</small></span></div>
      <div class="irow">${state}${tpill}<span class="muted small">${esc(i.grade)} · niveaux : qualité ${String(i.st.S.toFixed(1)).replace('.', ',')}</span></div>
      <table class="plan">
        <tr><td>Entrée</td><td><b>${px(i.entry)}</b></td><td class="muted">${i.entryType === 'marché' ? 'près du prix actuel' : `ordre limite, à ${LT.num(i.distAtr * i.atrPct)} % du prix`}</td></tr>
        <tr><td>Stop</td><td><b class="dn">${px(i.stop)}</b></td><td class="muted">${chg(i.stop, i.entry)} (sortie si l'idée est fausse)</td></tr>
        <tr><td>Objectif 1</td><td><b class="up">${px(i.tp1)}</b></td><td class="muted">${chg(i.tp1, i.entry)}${rr(i.rr1)}</td></tr>
        ${i.tp2 != null ? `<tr><td>Objectif 2</td><td><b class="up">${px(i.tp2)}</b></td><td class="muted">${chg(i.tp2, i.entry)}${rr(i.rr2)}</td></tr>` : ''}
      </table>
      <div class="ibtns">${shown ? '<button data-plan-off="1">Masquer sur le graphique</button>' : `<button data-plan="${esc(i.key)}">Voir sur le graphique</button>`}</div>
      <details data-key="${esc(i.key)}" ${open.has(i.key) ? 'open' : ''}><summary>Tout comprendre : pourquoi, contexte, probabilités</summary>
        <h5>Quoi faire</h5><ul>${lines(d.action)}</ul>
        ${d.trend && d.trend.length ? `<h5>Tendance de fond</h5><ul>${lines(d.trend)}</ul>` : ''}
        <h5>Pourquoi ici</h5><ul>${lines(d.why)}</ul>
        ${d.macro && d.macro.length ? `<h5>Contexte macro</h5><ul>${lines(d.macro)}</ul>` : ''}
        ${d.news.length ? `<h5>Annonces économiques</h5><ul>${lines(d.news)}</ul>` : ''}
        ${d.context.length ? `<h5>Autres contextes</h5><ul>${lines(d.context)}</ul>` : ''}
        ${d.probs.length ? `<h5>Probabilités</h5><ul>${lines(d.probs)}</ul>` : ''}
        <h5>Détail du score</h5><div class="cmps">${comps}</div>
        <h5>Prudence</h5><ul>${lines(d.risks, 'warnl')}${i.hold.length ? lines(i.hold.map(h => 'En attente : ' + h), 'warnl') : ''}${(i.gates || []).length ? lines(i.gates.map(g => 'Filtre : ' + g), 'warnl') : ''}</ul>
        ${xBlock(i, sg.symbol)}
      </details></div>`;
  }

  function trendBox(sg) {
    const r = sg.regime, ev = sg.evidence;
    if (!r) return '<div class="trendbox muted small">Tendance de fond : pas assez d\'historique (200 jours) pour la calculer.</div>';
    const cls = r.regime > 0 ? 'up' : r.regime < 0 ? 'dn' : 'amb';
    const what = r.regime > 0 ? 'Seuls les <b>achats</b> sont retenus.' : r.regime < 0 ? 'Seules les <b>ventes</b> sont retenues.' : 'Aucune idée n\'est retenue tant que le cours reste entre les deux moyennes.';
    const stat = ev && ev.aligned != null ? ` Mesuré sur ${esc(ev.label)} : <b class="up">${LT.num(ev.aligned, 2)} R</b> par trade dans le sens de la tendance, <b class="dn">${LT.num(ev.counter, 2)} R</b> à contre-courant (voir la page Backtest).` : '';
    return `<div class="trendbox"><b class="${cls}">Tendance de fond : ${esc(r.label)}</b> <span class="muted small">cours ${px(r.price)} · moyenne 50 j ${px(r.fast)} (${LT.sPct(r.distFast)}) · moyenne 200 j ${px(r.slow)} (${LT.sPct(r.distSlow)})</span>
      <div class="small">${sg.trendGate ? what : 'Filtre désactivé dans les réglages : les idées à contre-courant sont aussi proposées.'}${stat}</div></div>`;
  }

  function validation(v, minS) {
    if (!v || !v.ready) return '<div class="muted small">Le rejeu historique est en cours de calcul (quelques dizaines de secondes après le démarrage).</div>';
    const since = new Date(v.from).toLocaleDateString('fr-FR', {month: '2-digit', year: 'numeric'});
    const rows = v.tiers.map(t => {
      const r = t.real, c = t.ctrl, vd = VERDICT[t.verdict];
      return `<tr><td>≥ ${t.minS}</td><td>${r.n}</td><td>${pc(r.fillRate)}</td><td>${pc(r.win.p)}<small class="muted"> (${pc(r.win.lo)}-${pc(r.win.hi)})</small></td>
        <td>${pc(c.win.p)}</td><td>${r.expR == null ? '-' : LT.num(r.expR)}</td><td>${LT.num(t.perWeek.mean, 1)}</td><td class="${vd[1]}">${vd[0]}</td></tr>`;
    }).join('');
    return `<div class="muted small">Ce que la <b>structure des niveaux seule</b> (VWAP jour à année, ouvertures, plus hauts et bas, profils de volume, points de contrôle non retestés ; sans poches, annonces ni flux) aurait donné depuis ${since} : mêmes règles qu'en direct, ordre limite, stop et objectif 1, au plus ${v.cap} idées par semaine.
      Comparé à des entrées au hasard de même forme (même distance, même stop, même objectif).</div>
      <table class="vtab"><thead><tr><th>Qualité</th><th>Idées</th><th>Exécutées</th><th>Objectif 1 avant stop</th><th>Hasard</th><th>Gain moyen (x risque)</th><th>Par semaine</th><th>Verdict</th></tr></thead><tbody>${rows}</tbody></table>
      <div class="muted small">Intervalle de confiance à 90 % entre parenthèses. Hypothèses : exécution au prix limite, sans frais, stop compté avant l'objectif si les deux sont dans la même bougie. « Pas mieux que le hasard » est le résultat le plus fréquent : l'idée reste un scénario, pas un avantage prouvé.</div>`;
  }

  function journal(desk) {
    const s = desk.stats;
    const head = `<div class="muted small">Depuis le premier lancement : <b>${s.ideas}</b> idées envoyées, <b>${s.executed}</b> exécutées · stop <b>${s.stop}</b> · objectif 1 puis retour <b>${s.tp1_be}</b> · objectif 2 <b>${s.tp2}</b> · en cours <b>${s.open}</b>${s.executed ? ` · résultat cumulé ≈ <b class="${s.r >= 0 ? 'up' : 'dn'}">${LT.num(s.r, 1)}</b> fois le risque (si la moitié est prise à l'objectif 1)` : ''}.</div>`;
    if (!desk.trades.length) return head + '<div class="muted small">Aucune idée envoyée pour l\'instant. Le journal est le test le plus honnête : il garde ce qui s\'est réellement passé après chaque idée.</div>';
    return head + `<ul class="jr">${desk.trades.map(t => {
      const st = t.status === 'closed' ? RESULT[t.result] || [t.result, 'muted'] : STATUS[t.status] || [t.status, 'muted'];
      return `<li><b class="${t.side === 'long' ? 'up' : 'dn'}">${t.side === 'long' ? 'ACHAT' : 'VENTE'}</b> ${esc(t.symbol)} · ${px(t.entry)} → ${px(t.tp1)} / stop ${px(t.stop)}
        <span class="pill ${st[1]}">${esc(st[0])}</span><div class="muted small">${timeFr(t.created)} · qualité ${Math.round(t.score)}/100 · idée ${t.n} de la semaine${t.sent ? '' : ' · envoi Telegram non confirmé'}</div></li>`;
    }).join('')}</ul>`;
  }

  function render(p) {
    if (!root || !p) return;
    last = p;
    if (!p.on) { root.innerHTML = '<section class="card"><div class="muted">Les idées de trade sont désactivées dans les réglages.</div></section>'; return; }
    const sym = LT.st.symbol, sg = (p.symbols || {})[sym], desk = p.desk;
    if (!sg || !sg.ready) { root.innerHTML = '<section class="card"><div class="muted">Calcul en cours… (les idées apparaissent quand les données et l\'historique sont chargés)</div></section>'; return; }
    const w = desk.week, dots = Array.from({length: w.cap}, (_, k) => `<i class="${k < w.sent ? 'on' : ''}"></i>`).join('');
    const openTrades = desk.trades.filter(t => t.symbol === sym && ['pending', 'active', 'tp1'].includes(t.status));
    const matchTrade = i => openTrades.find(t => t.side === i.side && Math.abs(t.entry - i.entry) < 1.5 * sg.atr);
    const ideas = sg.ideas.slice(0, 4);
    const elig = sg.ideas.filter(i => i.eligible).length;
    let html = `<section class="card"><h2>Cette semaine <small>lundi 00 h UTC → dimanche</small></h2>
      <div class="week"><span class="dots">${dots}</span><b>${w.sent}/${w.cap}</b> idées envoyées · seuil de qualité <b>${sg.minScore}/100</b> (la dernière place exige ${sg.minScore + 8})</div>
      ${desk.waiting && desk.waiting.why ? `<div class="muted small">${esc(desk.waiting.why)}</div>` : ''}
      <div class="muted small">Idées d'achat ou de vente fondées sur trois piliers : les <b>liquidités</b> (poches d'ordres d'arrêt), les <b>VWAP et VWAP ancrés</b> (de l'heure à l'année) et le <b>contexte macro</b>. Rien n'est envoyé sous le seuil ni sans liquidité ou avec une macro nettement contraire : mieux vaut aucune idée qu'une idée moyenne.</div></section>`;
    html += `<section class="card"><h2>Idées du moment <small>${esc(sym)}</small></h2>${trendBox(sg)}${ideas.length
      ? ideas.map(i => card(i, sg, matchTrade(i))).join('')
      : '<div class="muted">Aucune configuration ne passe les filtres pour l\'instant. C\'est normal : une bonne idée est rare.</div>'}`;
    if (sg.rejected && sg.rejected.length) {
      html += `<details class="rej"><summary>Zones repérées mais écartées (${sg.rejected.length})</summary><ul>${sg.rejected.map(r =>
        `<li>${r.side === 'long' ? 'Achat' : 'Vente'} vers ${px(r.entry)} : ${esc(r.why)}</li>`).join('')}</ul></details>`;
    }
    html += `<div class="muted small">${elig ? `${elig} idée(s) au-dessus du seuil.` : 'Aucune idée au-dessus du seuil.'} Le détail de chaque score est dans « Tout comprendre ».</div></section>`;
    html += `<section class="card"><h2>Validation historique <small>${esc(sym)}</small></h2>${validation(sg.validation, sg.minStruct)}</section>`;
    html += `<section class="card"><h2>Journal des idées</h2>${journal(desk)}</section>`;
    root.innerHTML = html;
  }

  return {init, render, last: () => last};
})();
