// Section « Analyse » sous le graphique : biais & probabilites, macro & annonces, dominance BTC / alts, plan de trade, lexique.
const Analysis = (() => {
  'use strict';
  let LT = null;
  const S = {an: null, planTimer: null, planSeq: 0, side: 'long', openEv: null};
  const $ = s => document.querySelector(s);
  const esc = s => Charts.esc(s);
  const p1 = v => v == null ? '-' : (v * 100).toFixed(1).replace('.', ',') + ' %';
  const p0 = v => v == null ? '-' : Math.round(v * 100) + ' %';
  const n1 = (v, d = 2) => v == null || isNaN(v) ? '-' : v.toFixed(d).replace('.', ',');
  const sg = (v, d = 2, u = '') => v == null || isNaN(v) ? '-' : (v > 0 ? '+' : '') + v.toFixed(d).replace('.', ',') + u;
  const when = t => new Date(t).toLocaleString('fr-FR', {weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
  const cdown = ms => { const m = Math.round(Math.abs(ms) / 60000); return m >= 1440 ? `${Math.floor(m / 1440)} j ${Math.floor(m % 1440 / 60)} h` : m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}` : `${m} min`; };
  const tone = x => x > 0.1 ? 'up' : x < -0.1 ? 'dn' : '';
  const card = (title, body, cls = '') => `<div class="acard ${cls}"><h3>${title}</h3>${body}</div>`;
  const FMT = {
    mom4: v => sg(v, 1, ' σ'), mom24: v => sg(v, 1, ' σ'), mom72: v => sg(v, 1, ' σ'),
    cvd4: v => sg(v * 100, 1, ' %'), cvd24: v => sg(v * 100, 1, ' %'), dvwap: v => sg(v, 1, ' ATR'), wvwap: v => sg(v, 1, ' ATR'),
    volreg: v => sg(v, 2), range72: v => Math.round((v + 0.5) * 100) + ' %', funding: v => sg(v, 4, ' %'),
  };

  // ---------- Biais & probabilites ----------
  function aucScale(a, ci) {                                     // echelle 0,45 -> 0,65, repere a 0,5
    const x = v => Math.max(0, Math.min(100, (v - 0.45) / 0.2 * 100));
    return `<div class="ci ${ci[0] > 0.5 ? 'pos' : ''}" title="AUC ${n1(a, 3)} · intervalle 90 % ${n1(ci[0], 3)} – ${n1(ci[1], 3)}"><i style="left:${x(ci[0])}%;width:${Math.max(1, x(ci[1]) - x(ci[0]))}%"></i><u style="left:${x(0.5)}%"></u><b style="left:${x(a)}%"></b></div>`;
  }
  function renderSynth(an) {
    const el = $('#anSynth'), sy = an.synth, b = an.bias;
    if (!sy) { el.textContent = 'Analyse en cours…'; return; }
    const dirCls = sy.direction === 'haussier' ? 'up' : sy.direction === 'baissier' ? 'dn' : 'neu';
    const confCls = sy.confidence === 'faible' ? 'warn' : 'ok';
    const sym = an.symbol.replace('USDT', '');
    const h24 = b && b.ready ? b.horizons['24'] : null, h4 = b && b.ready ? b.horizons['4'] : null;
    const probTile = (h, label) => !h ? '' : `<div class="sp"><div class="l">${label}</div><b>${h.validated ? p1(h.pUp) : p1(h.base)}</b> <span class="muted small">${h.validated ? `(taux de base ${p1(h.base)})` : '= taux de base, aucun avantage prouvé'}</span></div>`;
    let h = `<div class="ag two">` + card(`Biais ${esc(sym)} <small class="muted">${new Date(an.t).toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit'})}</small>`,
      `<div class="hero"><div class="big ${dirCls}" style="font-size:26px">${esc(sy.label.toUpperCase())}</div><div><div style="font-size:18px;font-weight:600">${sg(sy.score, 0)} / 100</div>` +
      `<div class="sub">confiance <span class="tag ${confCls}">${sy.confidence}</span><span class="tag ${sy.validated ? 'ok' : 'warn'}">${sy.validated ? 'modèle validé' : 'modèle non validé'}</span></div></div></div>` +
      Charts.meter(sy.score) +
      `<div class="spark" style="margin-top:8px">${probTile(h4, 'Probabilité de hausse dans 4 h')}${probTile(h24, 'Probabilité de hausse dans 24 h')}</div>` +
      `<div class="msg ${sy.validated ? 'ok' : 'warn'}" style="margin-top:8px">${esc(sy.statNote)}</div>` +
      `<div class="note">Un biais n'est pas un signal d'entrée : il dit de quel côté le contexte penche, avec quel niveau de preuve. L'entrée, le stop et la taille restent ton plan.</div>`) +
      card('Pourquoi', `<table class="t"><tr><th>Composante</th><th class="r">Poids</th><th style="width:38%">Lecture</th><th class="r">Score</th></tr>` +
        sy.components.map(c => `<tr><td>${esc(c.label)}</td><td class="r">${Math.round(c.weight * 100)} %</td><td>${Charts.dvBar(c.score)}</td><td class="r ${tone(c.score)}">${sg(c.score * 100, 0)}</td></tr>`).join('') + `</table>` +
        (sy.pros.length ? `<div class="sect">Pour</div><ul class="ln">${sy.pros.map(t => `<li class="pro">${esc(t)}</li>`).join('')}</ul>` : '') +
        (sy.cons.length ? `<div class="sect">Contre</div><ul class="ln">${sy.cons.map(t => `<li class="con">${esc(t)}</li>`).join('')}</ul>` : '') +
        (sy.invalidation.length ? `<div class="sect">Ce qui invaliderait</div><ul class="ln">${sy.invalidation.map(t => `<li class="inv">${esc(t)}</li>`).join('')}</ul>` : '')) + `</div>`;
    h += `<div class="ag two" style="margin-top:10px">`;
    // niveaux a surveiller
    h += card('Niveaux essentiels <small class="muted">les seuls tracés en mode Essentiel</small>', sy.levels.length ?
      `<table class="t"><tr><th></th><th class="r">Prix</th><th class="r">Distance</th><th class="r">Atteinte 24 h</th><th class="r">Rebond si touché</th></tr>` +
      sy.levels.map(l => `<tr><td class="${l.side === 'above' ? 'up' : l.side === 'below' ? 'dn' : ''}">${l.side === 'above' ? '▲' : l.side === 'below' ? '▼' : '◆'} ${'●'.repeat(Math.min(5, l.score))}</td><td class="r">${LT.fmtP(l.mid)}</td><td class="r">${n1(l.distAtr, 1)} ATR</td><td class="r">${p0(l.reach24)}</td><td class="r">${l.bounce && l.bounce.n ? p0(l.bounce.p) + ` <span class="muted small">n=${l.bounce.n}</span>` : '-'}</td></tr>`).join('') + `</table>` +
      `<div class="note">« Atteinte » = fréquence historique à laquelle le prix a parcouru cette distance en 24 h. « Rebond » = taux des zones de même type ; compare-le au hasard dans l'onglet Stats.</div>` : '<div class="muted">Aucune zone assez forte pour l\'instant.</div>');
    // modele
    if (!b || !b.ready) {
      h += card('Modèle statistique', `<div class="muted">${an.biasPending ? 'Calcul de l\'historique en cours (1 à 2 minutes après le chargement des données)…' : esc((b && b.reason) || 'indisponible')}</div>`);
    } else {
      const m = h24;
      h += card(`Modèle statistique <small class="muted">${b.bars.toLocaleString('fr-FR')} h d'historique${b.since ? ' depuis le ' + new Date(b.since).toLocaleDateString('fr-FR') + ' (' + n1((b.t - b.since) / 31557600000, 1) + ' ans)' : ''} · ${m.folds} périodes de test</small>`,
        `<table class="t"><tr><th></th><th>AUC (0,5 = hasard)</th><th style="width:30%"></th><th class="r">Gain de précision</th><th class="r">Score de Brier</th></tr>` +
        [['24 h', h24], ['4 h', h4]].map(([l, r]) => `<tr><td style="white-space:nowrap">${l}</td><td style="white-space:nowrap">${n1(r.auc, 3)} <span class="muted small">[${n1(r.aucCI[0], 3)} – ${n1(r.aucCI[1], 3)}]</span></td><td>${aucScale(r.auc, r.aucCI)}</td><td class="r">${sg(r.edge * 100, 1, ' pt')}</td><td class="r ${r.skill > 0 ? 'up' : 'dn'}">${sg(r.skill * 100, 2, ' %')}</td></tr>`).join('') + `</table>` +
        `<div class="note">Chaque ligne est mesurée <b>hors échantillon</b> : le modèle apprend sur le passé, est testé sur les 30 jours suivants, puis on avance (${m.n.toLocaleString('fr-FR')} prévisions testées, environ ${m.neff} indépendantes). ` +
        `Validé = l'intervalle de confiance de l'AUC est entièrement au-dessus de 0,5 <u>et</u> le score de Brier bat le taux de base. Sinon, le terminal ne tire aucun biais du modèle. Entraînement sur une fenêtre glissante de 3 ans ; les statistiques descriptives utilisent tout l'historique.</div>` +
        `<div class="sect">Calibration (24 h) : quand il annonce X %, que se passe-t-il vraiment ?</div><div id="calibHost"></div>`);
      h += card('Ce qui pèse aujourd\'hui <small class="muted">horizon 24 h</small>',
        `<table class="t"><tr><th>Variable</th><th class="r">Valeur</th><th style="width:34%">Poussée (haussière →)</th></tr>` +
        m.contrib.slice(0, 6).map(c => `<tr><td title="${esc((b.features.find(f => f.key === c.key) || {}).help || '')}">${esc(c.label)}</td><td class="r">${(FMT[c.key] || (v => n1(v)))(c.raw)}</td><td>${Charts.dvBar(c.c, Math.max(0.3, Math.abs(m.contrib[0].c)))}</td></tr>`).join('') + `</table>` +
        `<div class="note">${m.validated ? '' : 'Ces poussées décrivent ce que le modèle voit, mais il n\'a pas prouvé de pouvoir prédictif : ne les lis pas comme un signal. '}Poussée = coefficient × valeur standardisée, en log-cotes.</div>`);
      h += card('Situations comparables <small class="muted">chaque variable seule, tout l\'historique</small>',
        `<table class="t"><tr><th>Variable</th><th>Tiers actuel</th><th class="r">Hausse à 24 h</th><th class="r">Base</th><th></th><th class="r">n indép.</th></tr>` +
        m.tables.map(t => { const e = t.lo > t.base ? ['pos', 'au-dessus du hasard'] : t.hi < t.base ? ['neg', 'en dessous'] : ['neu', '≈ hasard']; return `<tr><td>${esc(t.label)}</td><td>${t.tier}</td><td class="r">${p1(t.p)} <span class="muted small">[${p0(t.lo)}–${p0(t.hi)}]</span></td><td class="r">${p1(t.base)}</td><td><span class="edge ${e[0]}">${e[1]}</span></td><td class="r">${t.neff}</td></tr>`; }).join('') + `</table>` +
        `<div class="note">Descriptif (non testé hors échantillon) : un tiers « au-dessus du hasard » sur une seule variable peut être un accident. Seul le bloc « Modèle statistique » ci-contre fait foi.</div>`);
    }
    h += `</div>`;
    el.className = ''; el.innerHTML = h;
    if (b && b.ready) { const ch = $('#calibHost'); if (ch) Charts.calib(ch, b.horizons['24'].calibration || []); }
  }

  function fngTable(s) {
    if (!s) return '';
    return `<div class="sect">Que fait le BTC après chaque zone ? <small class="muted">${s.days.toLocaleString('fr-FR')} jours depuis le ${new Date(s.since).toLocaleDateString('fr-FR')}</small></div>` +
      `<table class="t"><tr><th>Zone</th><th class="r">Hausse à 1 j</th><th class="r">à 7 j</th><th class="r">à 30 j</th><th class="r">Gain moyen 7 j</th></tr>` +
      s.rows.map(r => { const c = h => { const v = r[h], b = s.base[h], e = v.lo != null && v.lo > b ? 'up' : v.hi != null && v.hi < b ? 'dn' : ''; return `<td class="r ${e}">${p0(v.p)}</td>`; };
        return `<tr class="${r.current ? 'hl' : ''}"><td>${r.current ? '▶ ' : ''}${esc(r.zone)} <span class="muted small">n=${r['7'].n}</span></td>${c('1')}${c('7')}${c('30')}<td class="r ${r['7'].mean > 0 ? 'up' : 'dn'}">${sg(r['7'].mean, 1, ' %')}</td></tr>`; }).join('') +
      `<tr><td class="muted">Hasard (tous les jours)</td><td class="r muted">${p0(s.base['1'])}</td><td class="r muted">${p0(s.base['7'])}</td><td class="r muted">${p0(s.base['30'])}</td><td></td></tr></table>` +
      `<div class="note">Vert / rouge : l'intervalle de confiance à 90 % est entièrement au-dessus / en dessous du hasard (fenêtres qui se chevauchent : effectifs indépendants réduits).</div>`;
  }

  // ---------- Macro & annonces ----------
  const impDots = n => `<span class="dots">${'●'.repeat(n)}</span>`;
  const rcell = (v, d = 2, u = ' %') => v == null ? '<span class="muted">-</span>' : `<span class="${v > 0 ? 'up' : v < 0 ? 'dn' : ''}">${sg(v, d, u)}</span>`;
  function renderMacro(an) {
    const el = $('#anMacro'), m = an.macro;
    if (!m) { el.textContent = 'Analyse en cours…'; return; }
    const now = an.t;
    let h = '';
    if (m.risk) {
      const r = m.risk;
      h += `<div class="msg ${r.level === 'danger' ? 'bad' : r.level === 'attention' ? 'warn' : ''}"><b>${esc(r.label)}</b> ${r.minutes >= 0 ? 'dans' : 'il y a'} <b>${cdown(r.minutes * 60000)}</b> (${when(r.t)}). ` +
        `${r.level === 'danger' ? 'Fenêtre de danger : spreads élargis, mèches rapides, stops balayés. Réduis le levier ou reste à plat.' : r.level === 'attention' ? 'Volatilité attendue dans les prochaines heures : évite les entrées de faible conviction juste avant.' : ''}</div>`;
    }
    h += `<div class="ag two">`;
    h += card('Lecture macro <small class="muted">écrite à partir des chiffres mesurés</small>', m.lines.map(l => `<div class="msg ${l.tone === 'muted' ? '' : l.tone}">${esc(l.text)}</div>`).join('') +
      (m.score != null ? Charts.meter(m.score) + `<table class="t">` + m.components.map(c => `<tr><td>${esc(c.label)}</td><td style="width:40%">${Charts.dvBar(c.score)}</td><td class="r ${tone(c.score)}">${sg(c.score * 100, 0)}</td></tr>`).join('') + `</table>` : ''));
    h += card('Calendrier : 3 jours passés, 5 jours à venir', `<div id="tlHost"></div><div class="note">Orange = à venir, gris = passé. Gros points = impact élevé. Heures affichées dans ton fuseau.</div>` +
      (m.fng ? `<div class="sect">Fear &amp; Greed</div><div class="hero"><div class="big neu">${m.fng.value}</div><div class="sub">${esc(m.fng.label)}${m.fng.d7 != null ? ` · ${sg(m.fng.d7, 0)} en 7 j` : ''}</div><div style="flex:1;min-width:120px">${Charts.spark(m.fng.spark, '#c98500', 200, 40)}</div></div>` + fngTable(m.fng.stats) : ''));
    h += `</div><div class="ag" style="margin-top:10px">`;
    // a venir
    h += card('Annonces à venir <small class="muted">consensus = prévision moyenne des analystes</small>', m.upcoming.length ? `<table class="t"><tr><th>Quand</th><th>Annonce</th><th class="r">Consensus</th><th class="r">Précédent</th><th>Ce que dit le consensus</th><th>Réaction type du BTC</th></tr>` +
      m.upcoming.map(e => {
        const ex = e.exp || {}, t = e.typical, open = S.openEv === e.id;
        return `<tr class="${e.impact === 3 ? 'hl' : ''}" data-ev="${e.id}" style="cursor:pointer"><td>${when(e.t)}<div class="muted small">dans ${cdown(e.t - now)}</div></td><td>${impDots(e.impact)} ${esc(e.label)}<div class="muted small">${esc(e.title)} · ${esc(e.country)}</div></td>` +
          `<td class="r">${esc(e.forecast || '-')}</td><td class="r">${esc(e.previous || '-')}</td><td>${esc(ex.text || '-')}</td><td>${t && t.abs60 != null ? `±${n1(t.abs60)} % en 1 h <span class="muted small">(n=${t.n})</span>` : '<span class="muted small">pas encore mesuré</span>'}</td></tr>` +
          (open ? `<tr><td></td><td colspan="5"><div class="msg">${esc(ex.scen_up || '')}</div><div class="msg">${esc(ex.scen_dn || '')}</div><div class="muted small">Scénarios types (a priori). Le chiffre publié n'est pas connu à l'avance : le terminal lit ensuite la vraie réaction des taux et du dollar.</div></td></tr>` : '');
      }).join('') + `</table><div class="note">Clique une ligne pour voir les scénarios.</div>` : '<div class="muted">Aucune annonce majeure à venir (ou calendrier indisponible).</div>', 'wide');
    // passees
    h += card('Annonces passées : ce que le marché en a fait', m.past.length ? `<table class="t"><tr><th>Quand</th><th>Annonce</th><th class="r">Consensus</th><th class="r">BTC 15 min</th><th class="r">BTC 1 h</th><th class="r">Taux 10 ans</th><th class="r">Dollar</th><th>Surprise lue</th></tr>` +
      m.past.map(e => { const r = e.reaction || {}, b = r.btc || {}, c = r.cross || {}; return `<tr><td>${when(e.t)}</td><td>${impDots(e.impact)} ${esc(e.label)}</td><td class="r">${esc(e.forecast || '-')}</td><td class="r">${rcell(b.r15)}</td><td class="r">${rcell(b.r60)}</td><td class="r">${rcell(c.US10Y, 1, ' pb')}</td><td class="r">${rcell(c.DXY)}</td><td>${r.impulseLabel ? esc(r.impulseLabel) : '<span class="muted small">en cours de mesure</span>'}</td></tr>`; }).join('') + `</table>` +
      `<div class="note">Le flux gratuit ne fournit pas le chiffre publié : la « surprise » est lue dans la réaction du marché (restrictive si les taux et le dollar montent dans les 15 min, accommodante s'ils baissent). Les mesures sont archivées et s'accumulent avec le temps.</div>` : '<div class="muted">Pas encore d\'annonce passée mesurée.</div>', 'wide');
    // actifs de reference
    const tr = Object.entries(m.trends || {});
    h += card('Actifs de référence <small class="muted">5 jours · lien mesuré avec le BTC sur 90 jours et 1 an</small>', tr.length ? `<div class="spark">` + tr.map(([k, t]) => {
      const eff = (t.corr != null ? t.corr : 0) * (t.z || 0), col = Math.abs(t.z || 0) < 1 ? '#6a6e7a' : eff >= 0 ? '#3ddc97' : '#ff6b6b';
      return `<div class="sp"><div class="l">${esc(t.label)}</div><b>${LT.fmtP(t.last)}</b> <span class="${t.c5d > 0 ? 'up' : 'dn'}">${sg(t.c5d, t.unit === 'pb' ? 1 : 2, ' ' + (t.unit === 'pb' ? 'pb' : '%'))}</span>${Charts.spark(t.spark, col, 170, 34)}<div class="l" title="Corrélation des rendements quotidiens avec le BTC : 30 j ${t.corr30 != null ? sg(t.corr30, 2) : 'n/d'} · 90 j ${t.corr != null ? sg(t.corr, 2) : 'n/d'} · 1 an ${t.corr365 != null ? sg(t.corr365, 2) : 'n/d'}">corrélation BTC 90 j ${t.corr != null ? sg(t.corr, 2) : 'n/d'} (1 an ${t.corr365 != null ? sg(t.corr365, 2) : 'n/d'}) · écart ${t.z != null ? sg(t.z, 1) + ' σ' : 'n/d'}</div></div>`;
    }).join('') + `</div><div class="note">Trait gris = mouvement banal ; vert / rouge = mouvement inhabituel plutôt favorable / défavorable au BTC compte tenu de sa corrélation récente. Données Yahoo Finance (futures, presque 24 h).</div>` : '<div class="muted">Données de marché indisponibles (Yahoo Finance injoignable ?).</div>', 'wide');
    const errs = Object.entries(m.errors || {});
    if (errs.length) h += card('État des sources', `<div class="muted small">${errs.map(([k, v]) => `<b>${esc(k)}</b> : ${esc(v)}`).join('<br>')}</div>`, 'wide');
    h += `</div>`;
    el.className = ''; el.innerHTML = h;
    const th = $('#tlHost'); if (th) Charts.timeline(th, [...m.past, ...m.upcoming], now);
    el.querySelectorAll('tr[data-ev]').forEach(r => r.onclick = () => { S.openEv = S.openEv === r.dataset.ev ? null : r.dataset.ev; renderMacro(S.an); });
  }

  // ---------- Dominance ----------
  function renderDom(an) {
    const el = $('#anDom'), d = an.dom;
    if (!d || !d.ready) { el.innerHTML = `<div class="muted">Données de dominance indisponibles${d && d.errors && Object.keys(d.errors).length ? ' : ' + esc(Object.values(d.errors).join(' ; ')) : ''}.</div>`; return; }
    const sym = an.symbol.replace('USDT', '');
    let h = '';
    if (d.regime) h += `<div class="msg ${d.regime.tone === 'muted' ? '' : d.regime.tone}"><b>${esc(d.regime.name)}</b> — ${esc(d.regime.text)}</div>`;
    h += `<div class="ag">`;
    if (d.cg) h += card('Dominance du Bitcoin', `<div class="hero"><div class="big neu">${n1(d.cg.btc_d, 1)} %</div><div class="sub">24 h ${d.cg.d24 != null ? sg(d.cg.d24, 2, ' pt') : 'en cours de mesure'} · 7 j ${d.cg.d7 != null ? sg(d.cg.d7, 2, ' pt') : 'en cours de mesure'}<br>ETH ${d.cg.eth_d != null ? n1(d.cg.eth_d, 1) + ' %' : 'n/d'} · capitalisation ${n1(d.cg.total / 1e12)} T$ (${sg(d.cg.chg24, 1, ' %')} 24 h)</div></div>` +
      `<div id="cgHist" style="margin-top:8px"></div><div class="note">Source ${esc(d.cg.src)}. L'historique se construit tant que le terminal tourne${d.cg.histSince ? ' (depuis le ' + new Date(d.cg.histSince).toLocaleDateString('fr-FR') + ')' : ''}.</div>`);
    const rel = d.rel || {};
    if (rel['Panier alts/BTC']) h += card('Force des altcoins face au BTC <small class="muted">historique réel Binance, 30 jours</small>',
      `<div class="spark">${Object.entries(rel).map(([k, r]) => `<div class="sp"><div class="l">${esc(k)}</div><b>${sg(r.c24, 2, ' %')}</b> <span class="muted small">24 h</span> · <b>${sg(r.c7, 2, ' %')}</b> <span class="muted small">7 j</span></div>`).join('')}</div><div id="relHost" style="margin-top:8px"></div>` +
      `<div class="note">Panier = ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK cotés en BTC, équipondérés (100 au départ). Il monte = les alts battent le BTC (la dominance baisse).</div>`);
    if (d.beta) h += card(`${esc(sym)} face au BTC`, `<div class="hero"><div class="big neu">${n1(d.beta.beta)}×</div><div class="sub">bêta ${esc(d.beta.window)} (corrélation ${n1(d.beta.corr)}, R² ${n1(d.beta.r2)})</div></div>` +
      `<div class="spark" style="margin-top:6px">${Object.entries(d.betas || {}).map(([w, b]) => `<div class="sp"><div class="l">${esc(w)}</div><b>${n1(b.beta)}×</b> <span class="muted small">corr. ${n1(b.corr)}</span></div>`).join('')}</div>` +
      `<div class="msg">${esc(sym)} bouge de <b>${n1(d.beta.beta)} %</b> quand le BTC bouge de 1 %. Un levier 10× sur ${esc(sym)} équivaut à ~${Math.round(10 * d.beta.beta)}× sur le BTC.</div>` +
      (d.symRel ? `<div class="muted small">${esc(d.symRel.name)} spot : ${sg(d.symRel.c24, 2, ' %')} sur 24 h, ${sg(d.symRel.c7, 2, ' %')} sur 7 j.</div>` : ''));
    h += `</div>`;
    if (d.stats) {
      const rows = Object.entries(d.stats.table).filter(([, v]) => v.n >= 30).sort((a, b) => b[1].n - a[1].n);
      const names = {up: 'BTC ↑', dn: 'BTC ↓', flat: 'BTC ='};
      const an2 = {up: 'alts ↑', dn: 'alts ↓', flat: 'alts ='};
      h += `<div class="ag" style="margin-top:10px">` + card(`Probabilités : que fait le panier d'alts après chaque régime ? <small class="muted">${d.stats.days} jours d'historique réel</small>`,
        `<table class="t"><tr><th>Régime (5 j)</th><th class="r">Jours</th><th class="r">Alts ↑ le lendemain</th><th class="r">Alts ↑ à 3 jours</th></tr>` +
        rows.map(([k, v]) => { const [a, b] = k.split('|'); const cur = k === d.stats.cur; const e1 = v.lo1 > d.stats.base1 ? 'up' : v.hi1 < d.stats.base1 ? 'dn' : ''; return `<tr class="${cur ? 'hl' : ''}"><td>${cur ? '▶ ' : ''}${names[a]} · ${an2[b]}</td><td class="r">${v.n}</td><td class="r ${e1}">${p0(v.p1)} <span class="muted small">[${p0(v.lo1)}–${p0(v.hi1)}]</span></td><td class="r">${p0(v.p3)}</td></tr>`; }).join('') +
        `<tr><td class="muted">Hasard (tous les jours)</td><td class="r muted"></td><td class="r muted">${p0(d.stats.base1)}</td><td class="r muted">${p0(d.stats.base3)}</td></tr></table>` +
        `<div class="note">Lecture : « alts ↑ le lendemain » = le panier alts/BTC finit plus haut dans 24 h. Vert / rouge = l'intervalle de confiance à 90 % est entièrement au-dessus / en dessous du hasard. Les fenêtres de 5 jours se chevauchent : le nombre de cas réellement indépendants est environ 3 fois plus petit que « Jours ».</div>`, 'wide') + `</div>`;
    }
    if (d.lines && d.lines.length) h += `<div style="margin-top:10px">${d.lines.map(l => `<div class="msg">${esc(l)}</div>`).join('')}</div>`;
    el.className = ''; el.innerHTML = h;
    const day = t => new Date(t).toLocaleDateString('fr-FR', {day: 'numeric', month: 'short'});
    const hr = t => new Date(t).toLocaleString('fr-FR', {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
    if (d.cg && $('#cgHist')) $('#cgHist').innerHTML = d.cg.spark && d.cg.spark.length > 3 ? '' : '<div class="muted small">Historique en construction (une mesure toutes les 5 minutes).</div>';
    if (d.cg && d.cg.spark && d.cg.spark.length > 3) Charts.line($('#cgHist'), {series: [{name: 'Dominance BTC', color: '#3987e5', pts: d.cg.spark, area: true}], height: 130, yFmt: v => v.toFixed(2) + ' %', xFmt: hr, xTicks: 3});
    if (rel['Panier alts/BTC'] && $('#relHost')) Charts.line($('#relHost'), {series: [{name: 'Panier alts/BTC', color: '#3987e5', pts: rel['Panier alts/BTC'].spark, area: true}], height: 150, yFmt: v => v.toFixed(1), xFmt: day, ref: {y: 100, label: 'départ'}, xTicks: 4});
  }

  // ---------- Plan de trade ----------
  function renderPlanForm() {
    $('#anPlan').innerHTML = `<div class="ag two"><div class="acard"><h3>Ton trade</h3>
      <div class="frm">
        <label>Sens<select id="plSide"><option value="long">Long</option><option value="short">Short</option></select></label>
        <label>Objectif TP (%)<input id="plTp" type="number" step="0.1" min="0.1" value="2"></label>
        <label>Stop SL (%)<input id="plSl" type="number" step="0.1" min="0.1" value="1"></label>
        <label>Levier (×)<input id="plLev" type="number" step="1" min="1" max="125" value="10"></label>
        <label>Horizon<select id="plH"><option value="4">4 h</option><option value="24" selected>24 h</option><option value="72">72 h</option></select></label>
      </div>
      <div class="line"><button id="plFill" title="Place le TP sur la prochaine zone essentielle et le SL juste derrière la zone opposée">Pré-remplir avec mes niveaux</button><span class="muted small">distances comptées depuis le prix actuel</span></div>
      <div class="note">Les probabilités viennent de ce qu'a réellement fait cette paire depuis le début de l'historique : à chaque heure passée, le prix a-t-il touché d'abord le TP ou le stop (distances converties en ATR de l'époque) ? Si les deux sont touchés dans la même bougie, le stop compte en premier.</div></div>
      <div class="acard"><h3>Résultat <small id="plWait" class="muted"></small></h3><div id="plOut" class="muted">Saisis un trade ci-contre.</div></div></div>`;
    ['plSide', 'plTp', 'plSl', 'plLev', 'plH'].forEach(id => $('#' + id).addEventListener('input', schedulePlan));
    $('#plFill').onclick = () => {
      const lv = (S.an && S.an.synth && S.an.synth.levels) || [], px = S.an && S.an.price, side = $('#plSide').value;
      if (!px || !lv.length) return;
      const up = lv.filter(l => l.side === 'above').sort((a, b) => a.mid - b.mid)[0], dn = lv.filter(l => l.side === 'below').sort((a, b) => b.mid - a.mid)[0];
      const t = side === 'long' ? up : dn, s = side === 'long' ? dn : up;
      if (t) $('#plTp').value = Math.max(0.2, Math.abs(t.mid / px - 1) * 100).toFixed(2);
      if (s) $('#plSl').value = Math.max(0.2, Math.abs(s.mid / px - 1) * 100 + 0.25).toFixed(2);
      schedulePlan();
    };
  }
  function schedulePlan() { clearTimeout(S.planTimer); S.planTimer = setTimeout(runPlan, 350); }
  async function runPlan() {
    if (!$('#plSide')) return;
    const seq = ++S.planSeq, q = new URLSearchParams({symbol: LT.st.symbol, side: $('#plSide').value, tp: $('#plTp').value, sl: $('#plSl').value, lev: $('#plLev').value, h: $('#plH').value});
    $('#plWait').textContent = 'calcul…';
    let r;
    try { r = await LT.api('/api/plan?' + q); } catch (e) { if (seq === S.planSeq) { $('#plOut').className = 'dn'; $('#plOut').textContent = e.message; $('#plWait').textContent = ''; } return; }
    if (seq !== S.planSeq) return;
    $('#plWait').textContent = '';
    const o = $('#plOut');
    if (!r.ready) { o.textContent = 'Données en cours de chargement…'; return; }
    const pl = r.plan, tp = pl.tp, sl = pl.sl, no = pl.none, long = r.side === 'long';
    const ev = pl.ev, evMargin = ev != null ? ev * r.lev : null;
    const risk = S.an && S.an.macro && S.an.macro.risk, sy = S.an && S.an.synth;
    let w = '';
    if (r.slBeyondLiq) w += `<div class="msg bad">Ton stop (${n1(+$('#plSl').value)} %) est <b>au-delà de ta liquidation</b> (${n1(r.liqPct)} %) : à ${r.lev}× la plateforme te liquide avant que ton stop ne serve.</div>`;
    if (ev != null && ev < 0) w += `<div class="msg warn">Sur l'historique de ${esc(LT.st.symbol.replace('USDT', ''))}, ce couple TP/SL a une espérance <b>négative</b> avant frais (${sg(ev, 3, ' %')} par trade). Le hasard ne paie pas : il faut un avantage (niveau, flux) pour justifier l'entrée.</div>`;
    if (risk && risk.level !== 'info') w += `<div class="msg ${risk.level === 'danger' ? 'bad' : 'warn'}">Annonce majeure (${esc(risk.label)}) dans ${cdown(risk.minutes * 60000)} : les probabilités ci-dessous ignorent l'événement.</div>`;
    if (sy && sy.direction !== 'neutre' && sy.confidence !== 'faible' && ((sy.direction === 'haussier') !== long)) w += `<div class="msg warn">Ce trade va <b>contre</b> le biais ${sy.direction} (confiance ${sy.confidence}).</div>`;
    const seg = (p, col, lab) => p > 0.02 ? `<i style="left:LEFT%;width:${p * 100}%;background:${col}"></i>` : '';
    let left = 0; const bar = [[tp.p, '#3ddc97'], [sl.p, '#ff6b6b'], [no.p, '#4a4e5a']].map(([p, c]) => { const s = `<i style="left:${left * 100}%;width:${p * 100}%;background:${c}"></i>`; left += p; return s; }).join('');
    o.className = '';
    o.innerHTML = w + `<div class="pbar">${bar}</div>` +
      `<table class="t"><tr><td><span class="chip" style="background:#3ddc97"></span>TP touché en premier</td><td class="r"><b>${p1(tp.p)}</b> <span class="muted small">[${p0(tp.lo)}–${p0(tp.hi)}]</span></td></tr>` +
      `<tr><td><span class="chip" style="background:#ff6b6b"></span>Stop touché en premier</td><td class="r"><b>${p1(sl.p)}</b> <span class="muted small">[${p0(sl.lo)}–${p0(sl.hi)}]</span></td></tr>` +
      `<tr><td><span class="chip" style="background:#4a4e5a"></span>Ni l'un ni l'autre dans l'horizon</td><td class="r"><b>${p1(no.p)}</b></td></tr>` +
      `<tr><td>Ratio gain / risque</td><td class="r">${n1(pl.rr, 2)} : 1 <span class="muted small">(seuil de rentabilité ${p0(1 / (1 + pl.rr))} de réussite)</span></td></tr>` +
      `<tr><td>Espérance par trade, avant frais</td><td class="r ${ev > 0 ? 'up' : 'dn'}">${sg(ev, 3, ' %')} du prix · ${sg(evMargin, 1, ' %')} de la marge</td></tr>` +
      `<tr><td>Si TP / si stop (sur la marge à ${r.lev}×)</td><td class="r"><span class="up">${sg(r.gainOnMargin, 0, ' %')}</span> / <span class="dn">−${n1(r.riskOnMargin, 0)} %</span></td></tr></table>` +
      `<div class="sect">Liquidation à ${r.lev}× (marge isolée, 0,4 % de maintenance)</div>` +
      `<table class="t"><tr><td>Prix de liquidation</td><td class="r"><b>${LT.fmtP(r.liqPrice)}</b> (${n1(r.liqPct)} % du prix, ${n1(r.liqAtr, 1)} ATR 1h)</td></tr>` +
      `<tr><td>Probabilité de toucher ce prix en 4 h / 24 h / 72 h</td><td class="r">${['4', '24', '72'].map(h => p1(r.liqTouch[h])).join(' / ')}</td></tr></table>` +
      `<div class="note">Basé sur ${pl.n.toLocaleString('fr-FR')} départs horaires (≈ ${pl.neff} indépendants). Prix d'entrée supposé = prix actuel ${LT.fmtP(r.price)} ; TP ${LT.fmtP(r.tpPrice)}, stop ${LT.fmtP(r.slPrice)}. Frais et funding non inclus.</div>`;
  }

  // ---------- Lexique ----------
  function renderLex() {
    const sw = c => `<span class="sw" style="background:${c}"></span>`;
    $('#anLex').innerHTML = `<dl class="lex">
      <div class="acard"><h3>Sur le graphique</h3>
      <dt>${sw('rgba(255,179,0,.35)')}Zone de confluence</dt><dd>Bande où au moins deux niveaux de <b>sources différentes</b> se regroupent (VWAP, ouvertures, plus hauts/bas, POC, VAH/VAL, nPOC, bandes ±2σ, nombres ronds, poches de liquidation). Plus il y a de sources distinctes, plus la zone compte. Le nombre de points ● est le score ; une poche AIMANT ajoute 1.</dd>
      <dt>Mode « Essentiel »</dt><dd>Ne garde que les 2 zones les plus importantes au-dessus et en dessous du prix (score, aimant, type de niveau qui bat le hasard dans l'historique, proximité). « Confluences » montre toutes les zones proches, « Tous » tous les niveaux. Clique une zone pour voir ses membres.</dd>
      <dt>${sw('#ff6b6b')}${sw('#3ddc97')}Poches de liquidation estimées</dt><dd>Barre qui part de l'<b>instant où la poche s'est formée</b> et s'étend jusqu'à maintenant. Rouge au-dessus du prix = liquidations de shorts, vert en dessous = liquidations de longs. Plus la barre est opaque et épaisse, plus la poche est grosse. <b>AIMANT</b> = la plus forte de son côté. Ce sont des <u>estimations</u> à partir de l'Open Interest, pas de vraies liquidations.</dd>
      <dt>Vue « Liquidité »</dt><dd>Même graphique, centré sur la liquidité : carte de chaleur de l'historique des poches (une colonne par heure), balayages (▼▲), liquidations <b>réelles</b> (bulles, depuis que le terminal tourne) et profil actuel sur le bord droit.</dd>
      <dt>Pastille de prix</dt><dd>Prix de la poche et distance au prix actuel. Les chiffres bougent en temps réel avec le flux Binance.</dd></div>
      <div class="acard" style="margin-top:10px"><h3>Probabilités</h3>
      <dt>« x % d'y aller en 24 h »</dt><dd>Fréquence historique avec laquelle cette paire a parcouru <b>cette distance (en ATR 1h)</b> dans les 24 heures. Ce n'est pas une prévision directionnelle : c'est la probabilité qu'un prix à cette distance soit touché, dans un sens ou dans l'autre.</dd>
      <dt>« si touchée : rebond y % »</dt><dd>Parmi les zones de même type et même nombre de sources, part de celles où le prix s'est éloigné de 1,5 ATR du bon côté avant de casser de 1,5 ATR. Comparé à des niveaux tirés au hasard : « ≈ hasard » veut dire que la zone n'a pas prouvé qu'elle compte.</dd>
      <dt>Intervalle de confiance [a–b]</dt><dd>Fourchette à 90 % (méthode de Wilson). Plus l'échantillon est petit, plus elle est large. On ne conclut qu'avec une fourchette entièrement d'un côté du hasard.</dd>
      <dt>Biais statistique « validé »</dt><dd>Régression logistique sur 10 variables (momentum, CVD réel, VWAP, volatilité, funding...), entraînée sur le passé et testée sur les 30 jours suivants, en avançant. Elle n'est affichée comme probabilité que si elle bat le hasard hors échantillon ; sinon le terminal le dit et s'en tient au taux de base.</dd></div>
      <div class="acard" style="margin-top:10px"><h3>Macro &amp; contexte</h3>
      <dt>Consensus et surprise</dt><dd>Le consensus (prévision moyenne) est connu avant l'annonce. Le flux gratuit ne donne pas le chiffre publié : la surprise est lue dans la réaction du <b>rendement 10 ans</b> et du <b>dollar</b> dans les 15 minutes (restrictive si ils montent, accommodante s'ils baissent), puis comparée à la réaction du BTC.</dd>
      <dt>Fenêtre de danger</dt><dd>Moins de 90 minutes avant une annonce majeure (CPI, NFP, Fed...). Les mèches de 30 secondes y balayent les stops : réduis le levier ou reste à plat.</dd>
      <dt>Dominance BTC &amp; panier d'alts</dt><dd>Part du BTC dans la capitalisation crypto. Le panier alts/BTC (8 alts cotées en BTC) monte quand les alts battent le BTC. Le régime croise ce panier et la direction du BTC : saison BTC, alt season, risk-off...</dd>
      <dt>CVD, funding, long/short, prime Coinbase</dt><dd>Voir l'onglet Contexte du panneau de droite : flux agressif réel, coût du levier, positionnement de la foule et des gros comptes, demande US.</dd></div>
      <div class="acard" style="margin-top:10px"><h3>Idées de trade</h3>
      <dt>Idée de trade</dt><dd>Un achat ou une vente sur une zone où plusieurs niveaux importants se superposent, avec une <b>entrée</b>, un <b>stop</b> (où l'idée est fausse) et deux <b>objectifs</b>. Il n'y en a que 3 par semaine au maximum (lundi 00 h UTC), et seulement si la qualité dépasse le seuil : mieux vaut aucune idée qu'une idée moyenne.</dd>
      <dt>Poids des niveaux</dt><dd>Chaque source pèse selon son échelle de temps : jour 1, semaine 2, mois 3, année 4. Le VWAP (prix moyen pondéré par les volumes), les VWAP ancrés et les profils de volume sont bonifiés (x1,3). Un VWAP annuel pèse donc plus de quatre fois un VWAP du jour. La <b>qualité des niveaux</b> est la somme des poids des sources distinctes de la zone (7 minimum).</dd>
      <dt>Score sur 100</dt><dd>Niveaux superposés (40), liquidité (20 : poche dans la zone, poche déjà balayée, poche en face comme objectif), flux d'ordres (12), macro et annonces (12), tendance de fond (10), biais et dominance (6). Le détail de chaque idée est dans « Tout comprendre ».</dd>
      <dt>Rebond et retournement après balayage</dt><dd>Rebond : ordre à cours limité posé au bord de la zone. Retournement après balayage : la zone ou une poche de liquidations proche vient d'être percée puis reprise ; les ordres d'arrêt ont été pris, l'entrée est immédiate et le stop passe sous la mèche.</dd>
      <dt>Stop, objectif 1 et 2, rapport gain / risque</dt><dd>Le stop est au-delà de la zone (et de ses poches), jamais à moins de 1,5 amplitude d'une bougie d'une heure. L'objectif 1 est juste avant le prochain niveau important ou la prochaine grosse poche, à au moins 1,5 fois le risque. Conseil : y prendre une partie des gains et remonter le stop à l'entrée.</dd>
      <dt>Annonce en attente</dt><dd>Une annonce majeure dans moins de 3 heures (ou juste publiée) met l'idée en attente : elle n'est pas envoyée tant que le marché n'a pas digéré l'annonce.</dd>
      <dt>Validation historique et journal</dt><dd>Le rejeu rejoue la structure des niveaux sur tout l'historique et la compare à des entrées au hasard de même forme : il dit si cette qualité de niveau a fait mieux que le hasard. Le journal garde ce qui s'est réellement passé après chaque idée envoyée.</dd></div>
      <div class="acard" style="margin-top:10px"><h3>Honnêteté</h3><dd>Les probabilités décrivent le passé de la paire. Elles ne garantissent rien, ignorent les annonces imprévues et ne tiennent pas compte de tes frais. Un biais « neutre » ou « faible confiance » est une information : il vaut mieux ne pas trader que forcer un avantage qui n'existe pas.</dd></div>
    </dl>`;
  }

  // ---------- interface ----------
  const TITLES = {synth: 'Biais & probabilités', macro: 'Macro & annonces', dom: 'Dominance BTC / alts', plan: 'Plan de trade', lex: 'Lexique du graphique'};
  function show(name) {                                          // appele par le menu de gauche
    document.querySelectorAll('#anTabs button').forEach(x => x.classList.toggle('on', x.dataset.an === name));
    document.querySelectorAll('.anpane').forEach(p => p.hidden = p.dataset.anpane !== name);
    $('#anTitle').textContent = TITLES[name] || '';
    if (name === 'plan') runPlan();
    if (S.an) render(S.an);
  }
  function init(lt) {
    LT = lt;
    $('#anTabs').onclick = e => { const b = e.target.closest('button[data-an]'); if (b) show(b.dataset.an); };
    renderPlanForm(); renderLex();
  }
  function render(an) {
    S.an = an;
    if (!an || !an.ready) return;
    const tab = (document.querySelector('#anTabs button.on') || {}).dataset;
    // on ne redessine que l'onglet visible (les graphiques SVG mesurent leur largeur)
    if (!tab || tab.an === 'synth') renderSynth(an);
    if (tab && tab.an === 'macro') renderMacro(an);
    if (tab && tab.an === 'dom') renderDom(an);
    $('#anStatus').textContent = 'analyse de ' + an.symbol + ' · ' + new Date(an.t).toLocaleTimeString('fr-FR');
  }
  return {init, render, runPlan, show};
})();
