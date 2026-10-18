// Pages « Analyse » : biais & probabilites, macro (V27 : une seule page, voir macro.js), dominance BTC / alts.
const Analysis = (() => {
  'use strict';
  let LT = null;
  const S = {an: null};
  const $ = s => document.querySelector(s);
  const esc = s => Charts.esc(s);
  const prose = s => Charts.prose(s);                 // prose du serveur : virgule décimale
  const p1 = v => v == null ? '-' : (v * 100).toFixed(1).replace('.', ',') + ' %';
  const p0 = v => v == null ? '-' : Math.round(v * 100) + ' %';
  const n1 = (v, d = 2) => v == null || isNaN(v) ? '-' : v.toFixed(d).replace('.', ',');
  const sg = (v, d = 2, u = '') => v == null || isNaN(v) ? '-' : (v > 0 ? '+' : '') + v.toFixed(d).replace('.', ',') + u;
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
      `<div class="msg ${sy.validated ? 'ok' : 'warn'}" style="margin-top:8px">${prose(sy.statNote)}</div>` +
      `<div class="note">Un biais n'est pas un signal d'entrée : il dit de quel côté le contexte penche, avec quel niveau de preuve. L'entrée, le stop et la taille restent ton plan.</div>`) +
      card('Pourquoi', `<table class="t"><tr><th>Composante</th><th class="r">Poids</th><th style="width:38%">Lecture</th><th class="r">Score</th></tr>` +
        sy.components.map(c => `<tr><td>${esc(c.label)}</td><td class="r">${Math.round(c.weight * 100)} %</td><td>${Charts.dvBar(c.score)}</td><td class="r ${tone(c.score)}">${sg(c.score * 100, 0)}</td></tr>`).join('') + `</table>` +
        (sy.pros.length ? `<div class="sect">Pour</div><ul class="ln">${sy.pros.map(t => `<li class="pro">${prose(t)}</li>`).join('')}</ul>` : '') +
        (sy.cons.length ? `<div class="sect">Contre</div><ul class="ln">${sy.cons.map(t => `<li class="con">${prose(t)}</li>`).join('')}</ul>` : '') +
        (sy.invalidation.length ? `<div class="sect">Ce qui invaliderait</div><ul class="ln">${sy.invalidation.map(t => `<li class="inv">${prose(t)}</li>`).join('')}</ul>` : '')) + `</div>`;
    h += `<div class="ag two" style="margin-top:10px">`;
    // niveaux a surveiller
    h += card('Niveaux essentiels <small class="muted">les seuls tracés en mode Essentiel</small>', sy.levels.length ?
      `<table class="t"><tr><th></th><th class="r">Prix</th><th class="r">Distance</th><th class="r">Atteinte 24 h</th><th class="r">Rebond si touché</th></tr>` +
      sy.levels.map(l => `<tr><td class="${l.side === 'above' ? 'up' : l.side === 'below' ? 'dn' : ''}">${l.side === 'above' ? '▲' : l.side === 'below' ? '▼' : '◆'} ${'●'.repeat(Math.min(5, l.score))}</td><td class="r">${LT.fmtP(l.mid)}</td><td class="r">${n1(l.distAtr, 1)} ATR</td><td class="r">${p0(l.reach24)}</td><td class="r">${l.bounce && l.bounce.n ? p0(l.bounce.p) + ` <span class="muted small">n=${l.bounce.n}</span>` : '-'}</td></tr>`).join('') + `</table>` +
      `<div class="note">« Atteinte » = fréquence historique à laquelle le prix a parcouru cette distance en 24 h. « Rebond » = taux des zones de même type ; compare-le au hasard dans Détails ▾ → Stats.</div>` : '<div class="muted">Aucune zone assez forte pour l\'instant.</div>');
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

  // ---------- Dominance ----------
  function renderDom(an) {
    const el = $('#anDom'), d = an.dom;
    if (!d || !d.ready) { el.innerHTML = `<div class="muted">Données de dominance indisponibles${d && d.errors && Object.keys(d.errors).length ? ' : ' + esc(Object.values(d.errors).join(' ; ')) : ''}.</div>`; return; }
    const sym = an.symbol.replace('USDT', '');
    let h = '';
    if (d.regime) h += `<div class="msg ${d.regime.tone === 'muted' ? '' : d.regime.tone}"><b>${esc(d.regime.name)}</b> — ${prose(d.regime.text)}</div>`;
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
    if (d.lines && d.lines.length) h += `<div style="margin-top:10px">${d.lines.map(l => `<div class="msg">${prose(l)}</div>`).join('')}</div>`;
    el.className = ''; el.innerHTML = h;
    const day = t => new Date(t).toLocaleDateString('fr-FR', {day: 'numeric', month: 'short'});
    const hr = t => new Date(t).toLocaleString('fr-FR', {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
    if (d.cg && $('#cgHist')) $('#cgHist').innerHTML = d.cg.spark && d.cg.spark.length > 3 ? '' : '<div class="muted small">Historique en construction (une mesure toutes les 5 minutes).</div>';
    if (d.cg && d.cg.spark && d.cg.spark.length > 3) Charts.line($('#cgHist'), {series: [{name: 'Dominance BTC', color: '#3987e5', pts: d.cg.spark, area: true}], height: 130, yFmt: v => v.toFixed(2).replace('.', ',') + ' %', xFmt: hr, xTicks: 3});
    if (rel['Panier alts/BTC'] && $('#relHost')) Charts.line($('#relHost'), {series: [{name: 'Panier alts/BTC', color: '#3987e5', pts: rel['Panier alts/BTC'].spark, area: true}], height: 150, yFmt: v => v.toFixed(1).replace('.', ','), xFmt: day, ref: {y: 100, label: 'départ'}, xTicks: 4});
  }

  // ---------- interface ----------
  const TITLES = {synth: 'Biais & probabilités', macro: 'Macro', dom: 'Dominance BTC / alts'};
  function show(name) {                                          // appele par le menu de gauche
    document.querySelectorAll('#anTabs button').forEach(x => x.classList.toggle('on', x.dataset.an === name));
    document.querySelectorAll('.anpane').forEach(p => p.hidden = p.dataset.anpane !== name);
    $('#anTitle').textContent = TITLES[name] || '';
    if (name === 'macro') Macro.show(); else Macro.hide();
    if (S.an) render(S.an);
  }
  function init(lt) {
    LT = lt;
    $('#anTabs').onclick = e => { const b = e.target.closest('button[data-an]'); if (b) show(b.dataset.an); };
    Macro.init(lt, $('#anMacro'));
  }
  function render(an) {
    S.an = an;
    if (!an || !an.ready) return;
    Macro.setAnalysis(an);
    const tab = (document.querySelector('#anTabs button.on') || {}).dataset;
    // on ne redessine que l'onglet visible (les graphiques SVG mesurent leur largeur)
    if (!tab || tab.an === 'synth') renderSynth(an);
    if (tab && tab.an === 'dom') renderDom(an);
    $('#anStatus').textContent = 'analyse de ' + an.symbol + ' · ' + new Date(an.t).toLocaleTimeString('fr-FR');
  }
  return {init, render, show};
})();
