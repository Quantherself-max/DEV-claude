// Idees de trade (V27 : page a part entiere du menu Workspace, retiree du panneau de droite du Desk) : cartes (quoi faire / pourquoi /
// probabilites), validation historique, journal.
const Signals = (() => {
  let LT = null, root = null, last = null;
  const open = new Set();
  const xres = {};                                                    // avis d'influenceurs deja lus (cle symbole|sens)
  const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const px = v => v == null ? '-' : LT.fmtP(v);
  const chg = (v, e) => LT.sPct((v / e - 1) * 100);
  const timeFr = ms => new Date(ms).toLocaleString('fr-FR', {timeZone: 'Europe/Paris', weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
  const KIND = {rebond: 'Rebond sur une zone (ordre à cours limité)', reprise: 'Retournement après balayage (entrée immédiate)'};
  const STATUS = {pending: ['Ordre en attente', 'warn'], active: ['Position ouverte', 'ok'], tp1: ['Objectif 1 atteint', 'ok']};
  const RESULT = {stop: ['Stop touché', 'dn'], tp1_be: ['Objectif 1 puis retour à l\'entrée', 'muted'], tp2: ['Objectif 2 atteint', 'up'],
    missed: ['Objectif atteint sans exécution', 'muted'], expired: ['Expirée sans exécution', 'muted'], expired_active: ['Suivi terminé', 'muted'],
    switch: ['Fermée pour changer de sens', 'muted'], switch_cancel: ['Ordre annulé pour changer de sens', 'muted']};
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
      if (b) { LT.setPlan(b.dataset.plan || null); render(last); return; }
      const tg = e.target.closest('button[data-ptog]');                // V26 : idée envoyée, masquer / afficher
      if (tg) { LT.togglePlan(tg.dataset.ptog); render(last); return; }
      const lv = e.target.closest('button[data-plive]');               // configuration du moment : afficher / retirer
      if (lv) { LT.setPlan(lv.dataset.plive || null); render(last); return; }
      const al = e.target.closest('button[data-pall]');
      if (al) { al.dataset.pall === 'reset' ? LT.planReset() : LT.setPlan(al.dataset.pall); render(last); return; }
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

  function dirNote(i) {                                            // tu ne trades que dans un sens : l'autre sens n'est qu'une alerte de prudence
    const d = (last && last.direction) || 'both';
    if (d === 'both' || i.side === d) return '';
    return ` <span class="pill warn" title="Réglages → 4 : sens de tes trades">${d === 'long' ? 'alerte pour tes longs, pas une idée' : 'alerte pour tes shorts, pas une idée'}</span>`;
  }
  // V25.3 : ce qu'il advient de chaque configuration du moment (même logique que l'envoi, calculée par le terminal)
  const BLOCK_SHORT = {quota: 'quota de la semaine atteint', pair: 'maximum par paire cette semaine', last: 'dernière place : qualité insuffisante',
    cooldown: 'une idée par paire toutes les 12 heures', zone: 'même zone qu\'une idée en cours', same: 'déjà envoyée il y a moins de 48 heures',
    full: '2 idées déjà en cours sur la paire', never: 'contredirait l\'idée en cours'};
  const isSent = i => !!(i.send && (i.send.state === 'sent' || i.send.state === 'alert'));
  function sendLine(i) {
    const s = i.send;
    if (!s) return '';
    if (isSent(i)) {
      const st = s.status === 'closed' ? (RESULT[s.result] || [s.result])[0] : (STATUS[s.status] || [s.status])[0];
      const moved = s.moved ? ` Ses niveaux sont <b>figés</b> à l'envoi (entrée ${px(s.entry)}, stop ${px(s.stop)}, objectif 1 ${px(s.tp1)}) ; ceux du tableau ci-dessous sont recalculés en continu.` : ' Ses niveaux sont figés à l\'envoi.';
      return `<div class="sendline ok">✅ ${s.state === 'alert' ? 'Alerte envoyée' : 'Envoyée sur Telegram'} le <b>${LT.parisAt(s.created)}</b>${s.n ? ` (idée ${s.n} de la semaine)` : ''} · ${esc(st)}${s.sent === false ? ' · <span class="dn">envoi Telegram non confirmé</span>' : ''}.${moved}</div>`;
    }
    if (s.state === 'next') return `<div class="sendline ok">⏳ ${esc(s.text)}.</div>`;
    if (s.state === 'blocked' || s.state === 'warming') return `<div class="sendline no">⛔ <b>Pas envoyée</b> : ${esc(s.text)}.</div>`;
    if (s.state === 'filtered') {
      const why = (i.gates || []).length ? shortGate(i.gates[0]) : (i.hold || []).length ? 'annonce majeure imminente ou toute récente' : `qualité sous le seuil (${(last && last.symbols && last.symbols[LT.st.symbol] || {}).minScore || ''}/100)`;
      return `<div class="sendline muted">Pas envoyée : ${esc(why)} (détail dans « Tout comprendre »).</div>`;
    }
    if (s.state === 'alertmode') return `<div class="sendline muted">${esc(s.text)}.</div>`;
    return '';
  }
  function card(i, sg) {
    const buy = i.side === 'long', col = buy ? 'up' : 'dn', d = i.desc, s = i.send || {};
    const sentNow = isSent(i);
    const gate = (i.gates || [])[0];
    const d0 = (last && last.direction) || 'both', bias = last && last.desk && last.desk.bias;
    const op = !sentNow && (d0 === 'both' || i.side === d0) ? LT.oppOf(bias, i.side) : null;
    const hedge = op && !op.blocked ? ` <span class="pill amb" title="Elle partirait en couverture : ${esc(op.names)} reste ouvert, chaque idée garde son stop et ses objectifs">Couverture de ${esc(op.names)}</span>` : '';
    const state = sentNow ? `<span class="pill up" title="Partie sur Telegram : niveaux figés, dessinés sur le graphique à partir de l'heure d'envoi">${s.state === 'alert' ? 'Alerte envoyée' : 'Envoyée'} le ${LT.parisAt(s.created)}</span>`
      : s.state === 'blocked' ? `<span class="pill warn" title="${esc(s.text)}">Pas envoyée : ${esc(BLOCK_SHORT[s.code] || s.code)}</span>`
      : s.state === 'warming' ? '<span class="pill warn" title="Calculs de démarrage en cours">Pas encore : démarrage</span>'
      : s.state === 'next' ? '<span class="pill up">Part dans un instant</span>' + hedge
      : gate ? `<span class="pill warn" title="${esc(i.gates.join(' · '))}">Filtre : ${esc(shortGate(gate))}</span>` : i.hold.length ? `<span class="pill warn" title="${esc(i.hold.join(' · '))}">En attente : annonce</span>`
      : i.eligible ? '<span class="pill up">Au-dessus du seuil</span>' + hedge : `<span class="pill muted">Sous le seuil (${sg.minScore})</span>`;
    const al = i.align, tpill = al == null ? '' : al > 0 ? '<span class="pill up" title="Le cours est du même côté des moyennes de 50 et 200 jours que l\'idée : c\'est la seule catégorie qui a rapporté dans le backtest">Dans le sens de la tendance</span>'
      : al < 0 ? '<span class="pill dn" title="Idée à contre-courant : la catégorie qui a perdu dans le backtest">À contre-courant</span>' : '<span class="pill warn" title="Cours entre les moyennes de 50 et 200 jours : aucun avantage mesuré">Tendance indécise</span>';
    const comps = i.comps.map(c => `<div class="cmp"><span>${esc(c.label)}</span><i><b style="width:${Math.round(100 * c.pts / c.max)}%"></b></i><em>${c.pts.toFixed(0)}/${c.max}</em></div>`).join('');
    const st0 = sentNow && last && last.desk ? (last.desk.trades || []).find(t => t.id === s.id) : null;
    const shown = LT.st.planOn && (sentNow ? !!(st0 && LT.planVisible(st0)) : LT.st.planKey === i.key);
    return `<div class="idea ${col}">
      <div class="ihead"><b class="side ${col}">${buy ? 'ACHAT' : 'VENTE'}</b><span class="muted small">${esc(KIND[i.kind] || i.kind)}</span>${dirNote(i)}
        <span class="score ${tone(i.score)}" title="Qualité de l'idée sur 100">${i.score.toFixed(0)}<small>/100</small></span></div>
      <div class="irow">${state}${tpill}<span class="muted small">${esc(i.grade)} · niveaux : qualité ${String(i.st.S.toFixed(1)).replace('.', ',')}</span></div>
      ${sendLine(i)}
      <table class="plan">
        <tr><td>Entrée</td><td><b>${px(i.entry)}</b></td><td class="muted">${i.entryType === 'marché' ? 'près du prix actuel' : `ordre limite, à ${LT.num(i.distAtr * i.atrPct)} % du prix`}</td></tr>
        <tr><td>Stop</td><td><b class="dn">${px(i.stop)}</b></td><td class="muted">${chg(i.stop, i.entry)} (sortie si l'idée est fausse)</td></tr>
        <tr><td>Objectif 1</td><td><b class="up">${px(i.tp1)}</b></td><td class="muted">${chg(i.tp1, i.entry)}${rr(i.rr1)}</td></tr>
        ${i.tp2 != null ? `<tr><td>Objectif 2</td><td><b class="up">${px(i.tp2)}</b></td><td class="muted">${chg(i.tp2, i.entry)}${rr(i.rr2)}</td></tr>` : ''}
      </table>
      <div class="ibtns">${sentNow ? (st0 ? `<button data-ptog="${esc(st0.id)}">${shown ? 'Masquer l\'idée envoyée du graphique' : 'Afficher l\'idée envoyée sur le graphique'}</button>` : '')
        : shown ? '<button data-plive="">Retirer du graphique</button>' : `<button data-plive="${esc(i.key)}" title="Dessinée en gris au bord droit : pas envoyée, ses niveaux bougent avec le marché">Voir cette configuration sur le graphique</button>`}</div>
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
    const head = `<div class="muted small">Depuis le premier lancement : <b>${s.ideas}</b> idées envoyées, <b>${s.executed}</b> exécutées · stop <b>${s.stop}</b> · objectif 1 puis retour <b>${s.tp1_be}</b> · objectif 2 <b>${s.tp2}</b> · en cours <b>${s.open}</b>${s.executed ? ` · résultat cumulé ≈ <b class="${s.r >= 0 ? 'up' : 'dn'}">${LT.num(s.r, 1)}</b> fois le risque (si la moitié est prise à l'objectif 1)` : ''}. <a href="#/history">Historique complet →</a></div>`;
    if (!desk.trades.length) return head + '<div class="muted small">Aucune idée envoyée pour l\'instant. Le journal est le test le plus honnête : il garde ce qui s\'est réellement passé après chaque idée.</div>';
    return head + `<ul class="jr">${desk.trades.slice(0, 12).map(t => {
      const st = t.status === 'closed' ? RESULT[t.result] || [t.result, 'muted'] : STATUS[t.status] || [t.status, 'muted'];
      const alert = t.mode === 'alerte';
      const tag = alert ? `<b class="amb">ALERTE</b> <span class="muted small">(configuration de ${t.side === 'short' ? 'vente' : 'achat'})</span>` : `<b class="${t.side === 'long' ? 'up' : 'dn'}">${t.side === 'long' ? 'ACHAT' : 'VENTE'}</b>`;
      const vis = !alert && LT.st.planOn && LT.planVisible(t);
      const tgl = alert ? '' : ` <button class="mini" data-ptog="${esc(t.id)}" title="${t.symbol === LT.st.symbol ? '' : 'Visible sur le graphique ' + esc(t.symbol.replace('USDT', '')) + ' · '}niveaux figés à l'envoi">${vis ? 'Masquer du graphique' : 'Afficher sur le graphique'}</button>`;
      return `<li>${tag} ${esc(t.symbol)} · ${px(t.entry)} → ${px(t.tp1)} / stop ${px(t.stop)}
        <span class="pill ${st[1]}">${esc(st[0])}</span>${tgl}<div class="muted small">envoyée ${timeFr(t.created)} · qualité ${Math.round(t.score)}/100 · ${alert ? 'hors quota' : 'idée ' + t.n + ' de la semaine'}${t.hedgeOf ? ' · couverture' : t.flipFrom || t.switchFrom ? ' · changement de sens' : ''}${t.sent ? '' : ' · envoi Telegram non confirmé'}</div></li>`;
    }).join('')}</ul>`;
  }

  // V26 : tout ce qui est dessiné sur le graphique, chaque élément retirable ; idées masquées réaffichables
  function onChart(desk) {
    const sym = LT.st.symbol, ps = (LT.st.plans || []).filter(x => x.symbol === sym);
    const hidden = (desk.trades || []).filter(t => t.symbol === sym && LT.st.planHide.includes(t.id)).length;
    const items = ps.map(x => x.kind === 'live'
      ? `<span class="pchip live">${x.side === 'long' ? 'Achat' : 'Vente'} du moment (pas envoyée) <button data-plive="" title="Retirer du graphique">✕</button></span>`
      : `<span class="pchip ${x.side === 'long' ? 'up' : 'dn'}${x.status === 'closed' ? ' done' : ''}">${x.side === 'long' ? 'Achat' : 'Vente'} du ${LT.parisAt(x.created)}${x.status === 'closed' ? ' (terminée)' : ''} <button data-ptog="${esc(x.key)}" title="Masquer du graphique">✕</button></span>`).join('');
    const off = !LT.st.planOn;
    return `<div class="onchart"><span class="lt">Sur le graphique</span> ${off ? '<span class="muted small">traits des idées masqués</span>' : items || '<span class="muted small">aucune idée dessinée</span>'}
      ${off ? '<button data-pall="on">Réafficher</button>' : ps.length ? '<button data-pall="off" title="Masquer tous les traits (aussi : case « Idées envoyées » du graphique)">Tout masquer</button>' : ''}
      ${hidden ? `<button data-pall="reset" title="Réafficher les idées que tu as masquées une par une">${hidden > 1 ? `Réafficher les ${hidden} idées masquées` : 'Réafficher l\'idée masquée'}</button>` : ''}
      <a href="#/desk" class="small">Ouvrir le graphique →</a></div>`;
  }

  function render(p) {
    if (!root || !p) return;
    last = p;
    if (!p.on) { root.innerHTML = '<section class="card"><div class="muted">Les idées de trade sont désactivées dans les réglages.</div></section>'; return; }
    const sym = LT.st.symbol, sg = (p.symbols || {})[sym], desk = p.desk;
    if (!sg || !sg.ready) { root.innerHTML = '<section class="card"><div class="muted">Calcul en cours… (les idées apparaissent quand les données et l\'historique sont chargés)</div></section>'; return; }
    const w = desk.week, dots = Array.from({length: w.cap}, (_, k) => `<i class="${k < w.sent ? 'on' : ''}"></i>`).join('');
    const ideas = sg.ideas.slice(0, 6);
    const elig = sg.ideas.filter(i => i.eligible).length, sentN = sg.ideas.filter(isSent).length;
    const heldN = sg.ideas.filter(i => i.send && (i.send.state === 'blocked' || i.send.state === 'warming')).length;
    let html = `<div class="sigcol"><section class="card"><h2>Cette semaine <small>lundi 00 h UTC → dimanche · ${esc(sym)}</small></h2>
      <div class="week"><span class="dots">${dots}</span><b>${w.sent}/${w.cap}</b> idées envoyées · seuil de qualité <b>${sg.minScore}/100</b> (la dernière place exige ${sg.minScore + 8})</div>
      <div class="biasline">${LT.biasHtml(desk.bias)}</div>
      ${onChart(desk)}
      ${desk.waiting && desk.waiting.why ? `<div class="muted small">${esc(desk.waiting.why)}</div>` : ''}
      <div class="muted small">Idées d'achat ou de vente fondées sur trois piliers : les <b>liquidités</b> (poches d'ordres d'arrêt), les <b>VWAP et VWAP ancrés</b> (de l'heure à l'année) et le <b>contexte macro</b>. Rien n'est envoyé sous le seuil ni sans liquidité ou avec une macro nettement contraire : mieux vaut aucune idée qu'une idée moyenne.</div></section>`;
    html += `<section class="card"><h2>Configurations du moment <small>${esc(sym)} · recalculées en continu</small></h2>${trendBox(sg)}
      <div class="muted small">Ce que le terminal voit <b>maintenant</b> : ces niveaux bougent avec le marché. Seules les configurations marquées « Envoyée » sont parties sur Telegram, avec des niveaux <b>figés</b> à l'envoi, dessinés sur le graphique à partir de l'heure d'envoi. Pour les autres, la raison est écrite sur la carte.</div>${ideas.length
      ? ideas.map(i => card(i, sg)).join('')
      : '<div class="muted">Aucune configuration ne passe les filtres pour l\'instant. C\'est normal : une bonne idée est rare.</div>'}`;
    if (sg.rejected && sg.rejected.length) {
      html += `<details class="rej"><summary>Zones repérées mais écartées (${sg.rejected.length})</summary><ul>${sg.rejected.map(r =>
        `<li>${r.side === 'long' ? 'Achat' : 'Vente'} vers ${px(r.entry)} : ${esc(r.why)}</li>`).join('')}</ul></details>`;
    }
    html += `<div class="muted small">${elig ? `${elig} configuration(s) au-dessus du seuil : ${sentN} déjà envoyée(s), ${heldN} retenue(s) par les règles d'envoi (quota, une idée par paire toutes les 12 heures, doublons).` : 'Aucune configuration au-dessus du seuil.'} Le détail de chaque score est dans « Tout comprendre ».</div></section>`;
    html += `</div><div class="sigcol"><section class="card"><h2>Idées envoyées sur Telegram <small>niveaux figés à l'envoi</small></h2>${journal(desk)}</section>`;
    html += `<section class="card"><h2>Validation historique <small>${esc(sym)}</small></h2>${validation(sg.validation, sg.minStruct)}</section></div>`;
    root.innerHTML = html;
  }

  return {init, render, last: () => last};
})();
