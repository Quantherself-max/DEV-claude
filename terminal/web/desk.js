// Desk (V28) : un espace par instrument (onglets BTC, SOL, et « BTC + SOL » pour les setups qui vont ensemble), et un graphique à
// ÉLÉMENTS : rien n'est dessiné sans avoir été choisi dans « ＋ Éléments » ; chaque élément choisi apparaît dans la légende en haut à
// gauche du graphique (œil : masquer, croix : retirer). Trois vues par instrument, chacune avec ses propres éléments : Graphique (épuré
// par défaut), Vierge (vide, à construire) et Heatmap (carnet d'ordres, BTC). Les confluences ne sont dessinées qu'à partir d'une note
// sur 14 (9 par défaut). La heatmap du carnet (/api/heatmap) et la carte des liquidations (/api/liqmap, V29) sont dessinées sous les
// bougies, sur tout le graphique : V29, mémoire longue (archives Binance avant le premier lancement) et 6 mois de liquidations estimées.
const Desk = (() => {
  'use strict';
  let LT = null, chooser = null, chooserBtn = null, heatTimer = null, legendMin = null;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const EX = [['binance', 'Binance'], ['okx', 'OKX'], ['bybit', 'Bybit'], ['coinbase', 'Coinbase']];
  // catalogue : clé -> [nom, explication, famille, réservé au BTC]
  const EL = {
    zones: ['Confluences', 'zones où des niveaux de sources différentes se superposent, notées sur 14', 'Niveaux'],
    pools: ['Poches de liquidation', 'estimées par l\'intérêt ouvert', 'Niveaux'],
    liqmap: ['Carte des liquidations', 'estimée sur 6 mois : où des positions à levier seraient liquidées ; une ligne s\'éteint quand le prix la touche', 'Niveaux'],
    ppools: ['Plus hauts / plus bas', 'ordres d\'arrêt visibles dans le prix : veille, semaine, mois', 'Niveaux'],
    npoc: ['POC vierges', 'des jours et semaines passés, jamais retraversés', 'Niveaux'],
    sess: ['Profil du jour', 'volume par prix depuis 00 h UTC, POC, VAH, VAL', 'Profils de volume'],
    sessW: ['Profil de la semaine', 'depuis lundi 00 h UTC', 'Profils de volume'],
    sessM: ['Profil du mois', 'depuis le 1er à 00 h UTC', 'Profils de volume'],
    nodes: ['Nœuds de volume', 'acceptation (HVN, bleu) et rejet (LVN, violet) du jour', 'Profils de volume'],
    dpoc: ['POC, VAH et VAL évolutifs', 'du jour, tels qu\'ils ont évolué pendant la séance', 'Profils de volume'],
    tpoM: ['TPO du mois', 'single prints et poor highs / lows non réparés', 'TPO'],
    tpoW: ['TPO de la semaine', 'tranches de 4 heures', 'TPO'],
    tpoD: ['TPO du jour', 'tranches de 30 minutes', 'TPO'],
    tpo4: ['TPO des séances de 4 heures', '', 'TPO'],
    tpo1: ['TPO des séances d\'1 heure', 'beaucoup de marques : en 5 ou 15 minutes', 'TPO'],
    vwap: ['VWAP du jour', 'et bandes à ±1 écart-type', 'VWAP'],
    vwapW: ['VWAP de la semaine', '', 'VWAP'],
    vwapM: ['VWAP du mois', '', 'VWAP'],
    vwapY: ['VWAP de l\'année', '', 'VWAP'],
    avwap: ['VWAP ancrés', 'début d\'année, mois précédent et tes ancres', 'VWAP'],
    vol: ['Volume', 'barres de volume sous les bougies', 'Flux d\'ordres'],
    oi: ['Intérêt ouvert', 'en bougies, dans une fenêtre sous le graphique (Binance, relevé toutes les 5 minutes)', 'Flux d\'ordres'],
    delta: ['Delta', 'en barres sous le graphique : acheteurs moins vendeurs agressifs de chaque bougie ; CVD (le cumul) en option', 'Flux d\'ordres'],
    heat: ['Heatmap du carnet', 'ordres en attente dans le temps (Binance, OKX, Bybit, Coinbase) ; avant tes propres photos : archives Binance, par tranches de 1 %', 'Flux d\'ordres', true],
    dom: ['Carnet d\'ordres', 'taille en attente et nombre d\'ordres à chaque prix, à droite', 'Flux d\'ordres'],
    big: ['Gros ordres agressifs', 'bulles : vert = acheteurs, rouge = vendeurs', 'Flux d\'ordres'],
    absorb: ['Absorptions', 'delta fort contre la bougie ; murs en direct', 'Flux d\'ordres'],
    gex: ['Gamma des options', 'murs de calls et de puts, bascule (Deribit)', 'Options', true],
    plan: ['Idées envoyées', 'entrée, stop et objectifs figés à l\'envoi', 'Idées'],
  };
  const CATS = ['Niveaux', 'Profils de volume', 'TPO', 'VWAP', 'Flux d\'ordres', 'Options', 'Idées'];
  const VIEWS = {main: 'Graphique', blank: 'Vierge', heat: 'Heatmap'};
  const PRESET = {main: {zones: true, sess: true, vwap: true, vol: true, plan: true}, blank: {}, heat: {heat: true, liqmap: false, big: true, vol: true, plan: true}};
  const VIEW_TF = {heat: '5m'};                                   // unité de temps de départ d'une vue (ensuite : la dernière choisie dans cette vue)
  const MO_KEYS = ['sess', 'sessW', 'sessM', 'nodes', 'dpoc', 'npoc', 'tpoM', 'tpoW', 'tpoD', 'tpo4', 'tpo1', 'vwap', 'vwapW', 'vwapM', 'vwapY', 'avwap',
    'vol', 'heat', 'liqmap', 'oi', 'delta', 'dom', 'big', 'absorb', 'gex', 'zones'];
  const freshSet = view => ({els: {...PRESET[view]}, minGrade: 9, bigMin: 2, absorbMode: 'fortes', bigLabels: 'top', heatEx: EX.map(e => e[0]), tf: VIEW_TF[view] || null});

  // ---------- espaces par instrument ----------
  const st = () => LT.st;
  function wsOf(sym) {
    const S = st();
    S.ws = S.ws || {};
    if (!S.ws[sym]) S.ws[sym] = {layout: 'main', sets: {}};
    const w = S.ws[sym];
    Object.keys(VIEWS).forEach(v => { if (!w.sets[v] || typeof w.sets[v].els !== 'object') w.sets[v] = freshSet(v); });
    if (!w.v29) {                                     // V29 : la carte des liquidations apparaît (masquée) dans la légende de la vue Heatmap
      if (!('liqmap' in w.sets.heat.els)) w.sets.heat.els.liqmap = false;
      w.v29 = 1;
    }
    return w;
  }
  const heatSyms = () => (st().cfg && st().cfg.heatmapSymbols) || ['BTCUSDT'];
  const isBtc = sym => /^BTC/.test(sym || '');
  const viewOf = layout => VIEWS[layout] ? layout : 'main';
  function curSet() { const S = st(); return wsOf(S.symbol || (S.cfg && S.cfg.symbols[0]) || 'BTCUSDT').sets[viewOf(S.layout)]; }
  const allowed = k => !(EL[k] && EL[k][3]) || (k === 'heat' ? heatSyms().includes(st().symbol) : isBtc(st().symbol));
  // éléments du jeu courant -> anciens réglages lus par le dessin (panels.js)
  function apply() {
    const S = st(), s = curSet(), on = k => s.els[k] === true && allowed(k);
    S.pools = on('pools'); S.ppools = on('ppools'); S.planOn = on('plan'); S.mode = 'ess';
    MO_KEYS.forEach(k => { S.mainOpts[k] = on(k); });
    Object.assign(S.mainOpts, {bigMin: s.bigMin, absorbMode: s.absorbMode, bigLabels: s.bigLabels, deltaCvd: s.deltaCvd !== false});
    S.minGrade = s.minGrade; S.heatEx = s.heatEx;
  }
  function changed(reset) {
    apply(); LT.savePrefs(); LT.syncAllTools(); LT.refreshAll(); LT.updatePlan();
    if (typeof MTF !== 'undefined') MTF.redraw();
    LT.pollFlow();
    if (reset) LT.panels().forEach(p => p.kind === 'main' && p.resetView());
    renderLegend(); if (chooser && !chooser.hidden) fillChooser();
    pollHeat(true);
  }
  function setEl(k, val) {                            // true : visible ; false : masqué (gardé dans la légende) ; null : retiré
    const s = curSet();
    if (val == null) delete s.els[k]; else s.els[k] = !!val;
    changed(['sess', 'sessW', 'sessM', 'dom'].includes(k));
  }
  function preset(name) {
    const s = curSet();
    s.els = {...PRESET[name]};
    changed(true);
  }

  // ---------- légende dans le graphique ----------
  const EYE = '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true"><path d="M1 8s2.6-4.5 7-4.5S15 8 15 8s-2.6 4.5-7 4.5S1 8 1 8z" fill="none" stroke="currentColor" stroke-width="1.3"/><circle cx="8" cy="8" r="2" fill="currentColor"/></svg>';
  const EYE_OFF = '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true"><path d="M1 8s2.6-4.5 7-4.5S15 8 15 8s-2.6 4.5-7 4.5S1 8 1 8z" fill="none" stroke="currentColor" stroke-width="1.3" opacity=".5"/><path d="M2.5 13.5l11-11" stroke="currentColor" stroke-width="1.4"/></svg>';
  function zoneStatus() {
    const d = st().data, s = curSet();
    if (!d || !d.zones) return '';
    const g = z => z.grade || 0, shown = d.zones.filter(z => g(z) >= s.minGrade).length, best = Math.max(0, ...d.zones.map(g));
    return shown ? `${shown} zone${shown > 1 ? 's' : ''}` : `aucune en ce moment · meilleure ${best}/14`;
  }
  const dayFmt = t => new Date(t).toLocaleDateString('fr-FR', {timeZone: 'Europe/Paris', day: '2-digit', month: '2-digit', year: '2-digit'});
  const minFmt = t => new Date(t).toLocaleString('fr-FR', {timeZone: 'Europe/Paris', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
  function heatStatus() {
    const H = st().bookHeat;
    if (!heatSyms().includes(st().symbol)) return 'BTC seulement';
    if (!H) return 'chargement…';
    if (H.off) return esc(H.why || 'désactivée');
    const lg = H.long || {}, a = lg.archive || {}, own = [H.since, lg.since].filter(Boolean);
    const out = [own.length ? `photos depuis le ${minFmt(Math.min(...own))}` : 'premières photos en cours'];
    if (lg.archiveSince) out.push(`<span title="Avant tes propres photos : archives publiques de Binance depuis le ${dayFmt(lg.archiveSince)}, montant en attente par tranches de 1 % du prix (perpétuel Binance seulement)">avant : archives Binance (1 %)</span>`);
    else if (a.running) out.push('archives Binance : téléchargement…');
    else if (a.error) out.push('archives Binance injoignables pour l\'instant');
    return out.join(' · ');
  }
  function liqStatus() {
    const H = st().liqMap;
    if (!H) return 'chargement…';
    if (H.off || !H.ready) return esc(H.why || 'en préparation');
    const s = H.status || {}, out = ['estimée'];
    if (s.oiSince) out.push(`depuis le ${dayFmt(s.oiSince)}`);
    if (s.error) out.push('archives injoignables pour l\'instant');
    return out.join(' · ');
  }
  function legendItem(k, vis, s) {
    const [name] = EL[k], ok = allowed(k);
    let extra = '';
    if (k === 'zones') extra = ` <label class="lg-sel" title="Note minimale pour qu'une zone soit dessinée">≥ <select data-lgrade>${[5, 6, 7, 8, 9, 10, 11, 12].map(v => `<option value="${v}"${v === s.minGrade ? ' selected' : ''}>${v}</option>`).join('')}</select>/14</label> <span class="lg-st">${zoneStatus()}</span>`;
    else if (k === 'heat') extra = ok ? ` ${EX.map(([e, n]) => `<button class="lg-ex${s.heatEx.includes(e) ? ' on' : ''}" data-lex="${e}" title="Afficher ou retirer ${n}">${n}</button>`).join('')}${vis ? ` <span class="lg-st">${heatStatus()}</span>` : ''}` : ' <span class="lg-st">BTC seulement</span>';
    else if (k === 'liqmap') extra = vis ? ` <span class="lg-st">${liqStatus()}</span>` : '';
    else if (!ok) extra = ' <span class="lg-st">BTC seulement</span>';
    return `<div class="lg-item${vis ? '' : ' off'}${ok ? '' : ' na'}" data-lk="${k}"><button class="lg-eye" data-leye="${k}" title="${vis ? 'Masquer' : 'Afficher'}">${vis ? EYE : EYE_OFF}</button>` +
      `<span class="lg-name">${esc(name)}</span>${extra}<button class="lg-x" data-lx="${k}" title="Retirer du graphique">✕</button></div>`;
  }
  function renderLegend() {
    if (!LT) return;
    const p = LT.panels().find(x => x.kind === 'main'); if (!p) return;
    const el = p.host.querySelector('.legend'); if (!el) return;
    const s = curSet(), keys = Object.keys(EL).filter(k => k in s.els), view = viewOf(st().layout);
    if (legendMin === null) legendMin = window.innerWidth < 700;           // replié d'office sur un petit écran
    const head = `<div class="lg-head"><button class="lg-fold" data-lfold title="${legendMin ? 'Déplier la légende' : 'Replier la légende'}">${legendMin ? '▸' : '▾'}</button>` +
      `<b>${esc((st().symbol || '').replace('USDT', ''))}</b> <span>${esc(st().tf)}</span> <span class="lg-view">${VIEWS[view]}</span>${legendMin ? ` <span class="lg-st">${keys.length} élément${keys.length > 1 ? 's' : ''}</span>` : ''}</div>`;
    el.innerHTML = head + (legendMin ? '' : keys.length ? keys.map(k => legendItem(k, s.els[k] === true, s)).join('') :
      `<div class="lg-empty">${view === 'blank' ? 'Graphique vierge : ajoute ce que tu veux avec « ＋ Éléments ».' : 'Aucun élément : « ＋ Éléments » pour en ajouter.'}</div>`);
    el.hidden = false;
    if (!el.dataset.wired) {
      el.dataset.wired = '1';
      el.addEventListener('click', e => {
        const eye = e.target.closest('[data-leye]'), x = e.target.closest('[data-lx]'), ex = e.target.closest('[data-lex]');
        if (e.target.closest('[data-lfold]')) { legendMin = !legendMin; renderLegend(); }
        else if (eye) { const k = eye.dataset.leye; setEl(k, !(curSet().els[k] === true)); }
        else if (x) setEl(x.dataset.lx, null);
        else if (ex) { const s = curSet(), e2 = ex.dataset.lex; s.heatEx = s.heatEx.includes(e2) ? s.heatEx.filter(v => v !== e2) : [...s.heatEx, e2]; changed(false); }
      });
      el.addEventListener('change', e => { if (e.target.matches('[data-lgrade]')) { curSet().minGrade = +e.target.value; changed(false); } });
    }
    const vn = p.host.querySelector('.viewname'); if (vn) vn.textContent = VIEWS[view];
  }

  // ---------- menu « ＋ Éléments » ----------
  function optsHtml(k, s) {
    if (k === 'zones') return `<select class="mini" data-copt="minGrade" title="Note minimale (sur 14) pour qu'une zone soit dessinée">${[5, 6, 7, 8, 9, 10, 11, 12].map(v => `<option value="${v}"${v === s.minGrade ? ' selected' : ''}>≥ ${v}/14</option>`).join('')}</select>`;
    if (k === 'big') return `<select class="mini" data-copt="bigMin" title="Taille minimale d'une bulle">${Panel.bigSteps(st().symbol).map((v, i) => `<option value="${i}"${i === s.bigMin ? ' selected' : ''}>≥ ${LT.fmtUsdShort(v)} $</option>`).join('')}</select>`;
    if (k === 'delta') return `<select class="mini" data-copt="deltaCvd" title="Ajouter le CVD (cumul du delta) en ligne"><option value="1"${s.deltaCvd !== false ? ' selected' : ''}>barres + CVD</option><option value="0"${s.deltaCvd === false ? ' selected' : ''}>barres seules</option></select>`;
    if (k === 'absorb') return `<select class="mini" data-copt="absorbMode"><option value="fortes"${s.absorbMode === 'fortes' ? ' selected' : ''}>fortes</option><option value="toutes"${s.absorbMode === 'toutes' ? ' selected' : ''}>toutes</option></select>`;
    return '';
  }
  function planList() {
    const S = st(), sym = S.symbol;
    const trades = ((S.sig && S.sig.desk && S.sig.desk.trades) || []).filter(t => t.symbol === sym && t.mode !== 'alerte').slice(0, 8);
    if (!trades.length) return `<div class="ddnote">Aucune idée envoyée sur ${esc(String(sym || '').replace('USDT', ''))} pour l'instant.</div>`;
    const OPEN = ['pending', 'active', 'tp1'];
    const hidden = trades.filter(t => S.planHide.includes(t.id)).length;
    return trades.map(t => `<label class="sub"><input type="checkbox" data-ptog="${esc(t.id)}"${LT.planVisible(t) ? ' checked' : ''}><span class="${t.side === 'long' ? 'up' : 'dn'}">${t.side === 'long' ? 'Achat' : 'Vente'} du ${esc(LT.parisAt(t.created))}` +
      `<small>${OPEN.includes(t.status) ? 'en cours' : 'terminée'} · entrée ${esc(LT.fmtP(t.entry))}, stop ${esc(LT.fmtP(t.stop))}${t.hedgeOf ? ' · couverture' : ''}</small></span></label>`).join('') +
      (hidden ? `<button class="mini" data-pall="reset">Réafficher ${hidden > 1 ? `les ${hidden} idées masquées` : 'l\'idée masquée'}</button>` : '');
  }
  function fillChooser() {
    const s = curSet(), view = viewOf(st().layout);
    chooser.innerHTML = `<div class="chhead"><b>Éléments · ${VIEWS[view]} ${esc((st().symbol || '').replace('USDT', ''))}</b><span class="spacer"></span>` +
      `<button class="mini" data-preset="${view === 'heat' ? 'heat' : 'main'}" title="Le réglage conseillé, sans bruit">Conseillé</button><button class="mini" data-preset="blank" title="Tout retirer : graphique vierge">Tout retirer</button></div>` +
      CATS.map(c => {
        const ks = Object.keys(EL).filter(k => EL[k][2] === c);
        return `<div class="ddh">${esc(c)}</div>` + ks.map(k => {
          const ok = allowed(k), [name, sub] = EL[k], present = k in s.els;
          return `<div class="ddrow"><label class="${ok ? '' : 'off'}"><input type="checkbox" data-chel="${k}"${present ? ' checked' : ''}${ok ? '' : ' disabled'}><span>${esc(name)}${!ok ? ' <em>(BTC seulement)</em>' : ''}${sub ? `<small>${esc(sub)}</small>` : ''}</span></label>${present && ok ? optsHtml(k, s) : ''}</div>` +
            (k === 'plan' && present ? `<div class="ddplans">${planList()}</div>` : '');
        }).join('');
      }).join('') +
      '<div class="ddnote">Chaque instrument et chaque vue (Graphique, Vierge, Heatmap) gardent leurs éléments. Dans le graphique, l\'œil masque un élément sans le retirer, la croix le retire.</div>' +
      '<a class="ddlink" href="#/signals">Page Idées de trade →</a>';
  }
  function placeChooser() {
    if (!chooserBtn || chooser.hidden) return;
    const r = chooserBtn.getBoundingClientRect(), vw = window.innerWidth, vh = window.innerHeight;
    chooser.style.maxHeight = Math.max(200, vh - r.bottom - 12) + 'px';
    chooser.style.top = (r.bottom + 4) + 'px';
    chooser.style.left = Math.max(6, Math.min(r.left, vw - chooser.offsetWidth - 6)) + 'px';
  }
  function closeChooser() { if (chooser) chooser.hidden = true; if (chooserBtn) chooserBtn.classList.remove('open'); }
  function toggleChooser(btn) {
    if (!chooser.hidden && chooserBtn === btn) { closeChooser(); return; }
    chooserBtn = btn; chooser.hidden = false; btn.classList.add('open'); fillChooser(); placeChooser();
  }
  function wireChooser() {
    chooser = document.createElement('div');
    chooser.className = 'ddp chooser'; chooser.hidden = true; chooser.setAttribute('role', 'dialog'); chooser.setAttribute('aria-label', 'Éléments du graphique');
    document.body.appendChild(chooser);
    chooser.addEventListener('change', e => {
      const t = e.target, s = curSet();
      if (t.dataset.chel) { if (t.checked) s.els[t.dataset.chel] = true; else delete s.els[t.dataset.chel]; changed(['sess', 'sessW', 'sessM', 'dom'].includes(t.dataset.chel)); }
      else if (t.dataset.copt) { s[t.dataset.copt] = t.dataset.copt === 'absorbMode' ? t.value : t.dataset.copt === 'deltaCvd' ? t.value === '1' : +t.value; changed(false); }
      else if (t.dataset.ptog != null) { LT.togglePlan(t.dataset.ptog); fillChooser(); }
    });
    chooser.addEventListener('click', e => {
      const pr = e.target.closest('[data-preset]'), all = e.target.closest('[data-pall]');
      if (pr) preset(pr.dataset.preset);
      else if (all) { LT.planReset(); fillChooser(); }
      else if (e.target.closest('.ddlink')) closeChooser();
    });
    document.addEventListener('mousedown', e => { if (!chooser.hidden && !chooser.contains(e.target) && !e.target.closest('[data-elbtn]')) closeChooser(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeChooser(); });
    window.addEventListener('resize', closeChooser);
  }

  // ---------- onglets d'instrument ----------
  const base = s => s.replace('USDT', '');
  function renderTabs() {
    const S = st(), box = document.getElementById('instTabs');
    if (!box || !S.cfg) return;
    const syms = S.cfg.symbols, pair = syms.length >= 2;
    box.innerHTML = syms.map(s => `<button data-inst="${esc(s)}" class="${S.instTab === s ? 'on' : ''}" title="${esc(base(s))} : son graphique, ses idées, sa lecture">${esc(base(s))}</button>`).join('') +
      (pair ? `<button data-inst="PAIR" class="pair${S.instTab === 'PAIR' ? ' on' : ''}" title="Les deux instruments côte à côte, avec les setups qui vont ensemble (couvertures)">${esc(base(syms[0]))} + ${esc(base(syms[1]))}</button>` : '');
  }
  function setTab(tab) {
    const S = st();
    if (tab === 'PAIR') {
      rememberTf(S.tf);
      S.instTab = 'PAIR'; S.layout = 'pair';
      if (S.page !== 'desk') location.hash = '#/desk';
      renderTabs(); LT.applyLayout(); return;
    }
    if (S.instTab !== 'PAIR') rememberTf(S.tf);
    S.instTab = tab;
    const w = wsOf(tab);
    S.layout = w.layout || 'main';
    if (tab !== S.symbol) LT.switchSymbol(tab); else { apply(); LT.applyLayout(); }
    const tf = curSet().tf;
    if (tf && tf !== S.tf) LT.setTf(tf);
    renderTabs();
  }
  function onLayout(layout) {                         // une vue choisie dans la barre du Desk : retenue pour l'instrument, avec son unité de temps
    const S = st();
    if (S.instTab && S.instTab !== 'PAIR' && layout !== 'pair') wsOf(S.instTab).layout = layout;
    apply();
    const tf = curSet().tf;
    if (tf && tf !== S.tf) LT.setTf(tf);
  }
  function rememberTf(tf) { if (VIEWS[st().layout]) curSet().tf = tf; }

  // ---------- couches sous les bougies : heatmap du carnet et carte des liquidations ----------
  // une palette par couche : carnet = bleu nuit, bleu, cyan, jaune, orange, rouge (comme les écrans de carnet) ; liquidations = violet,
  // bleu, vert d'eau, vert, jaune (comme les cartes de liquidation des sites spécialisés)
  const cmapOf = stops => {
    const out = new Uint8ClampedArray(256 * 4);
    for (let q = 0; q < 256; q++) {
      let a = stops[0], b = stops[stops.length - 1];
      for (let i = 0; i < stops.length - 1; i++) if (q >= stops[i][0] && q <= stops[i + 1][0]) { a = stops[i]; b = stops[i + 1]; break; }
      const f = b[0] === a[0] ? 0 : (q - a[0]) / (b[0] - a[0]);
      for (let c = 0; c < 3; c++) out[q * 4 + c] = Math.round(a[1][c] + (b[1][c] - a[1][c]) * f);
      out[q * 4 + 3] = q === 0 ? 0 : Math.round(255 * (a[1][3] + (b[1][3] - a[1][3]) * f));
    }
    return out;
  };
  const CMAP = cmapOf([[0, [8, 18, 48, 0]], [18, [16, 40, 110, 0.35]], [70, [25, 90, 190, 0.6]], [130, [40, 170, 220, 0.75]], [180, [240, 205, 80, 0.88]], [225, [245, 140, 45, 0.95]], [255, [235, 70, 60, 1]]]);
  const CMAP_LIQ = cmapOf([[0, [68, 1, 84, 0]], [13, [72, 20, 110, 0.4]], [70, [59, 82, 139, 0.6]], [130, [33, 145, 140, 0.75]], [190, [94, 201, 98, 0.88]], [255, [253, 231, 37, 0.97]]]);
  function heatImage(h, cmap) {
    const bytes = Uint8Array.from(atob(h.data), c => c.charCodeAt(0)), n = h.cols, m = h.rows;
    const cv = document.createElement('canvas'); cv.width = n; cv.height = m;
    const cx = cv.getContext('2d'), img = cx.createImageData(n, m);
    for (let j = 0; j < m; j++) for (let i = 0; i < n; i++) {
      const q = bytes[j * n + i], o = ((m - 1 - j) * n + i) * 4;
      img.data[o] = cmap[q * 4]; img.data[o + 1] = cmap[q * 4 + 1]; img.data[o + 2] = cmap[q * 4 + 2]; img.data[o + 3] = cmap[q * 4 + 3];
    }
    cx.putImageData(img, 0, 0);
    h.bytes = bytes; h.img = cv;
    return h;
  }
  // une couche : sa clé d'élément, où elle est rangée, son adresse, sa palette, son rythme de rafraîchissement (selon l'unité de temps)
  const LAYERS = [
    {el: 'heat', slot: 'bookHeat', cmap: CMAP, url: (sym, q) => `/api/heatmap?symbol=${sym}&${q}&ex=${encodeURIComponent((st().heatEx || []).join(','))}`,
      every: tf => ({'5m': 8000, '15m': 15000, '1h': 30000}[tf] || 60000), extra: () => (st().heatEx || []).join(',')},
    {el: 'liqmap', slot: 'liqMap', cmap: CMAP_LIQ, url: (sym, q) => `/api/liqmap?symbol=${sym}&${q}`, every: () => 60000, extra: () => ''},
  ];
  const layerState = {heat: {key: '', busy: false}, liqmap: {key: '', busy: false}};
  function mainVisible() {
    const S = st();
    return S.page === 'desk' && LT.panels().some(p => p.kind === 'main' && p.visible());
  }
  function heatWanted() { return mainVisible() && LAYERS.some(l => st().mainOpts[l.el]); }
  function heatQuery() {
    try { return heatQuery0(); } catch (e) { return null; }
  }
  function heatQuery0() {
    const S = st(), p = LT.panels().find(x => x.kind === 'main'), d = S.data;
    if (!p || !d || !d.candles || !d.candles.length) return null;
    const ts = p.chart.timeScale(), r = ts.getVisibleLogicalRange(), cs = d.candles, n = cs.length, per = LT.TF_SEC[S.tf] || 3600;
    if (!r) return null;
    const i0 = Math.max(0, Math.min(n - 1, Math.floor(r.from)));
    const t0 = (cs[i0][0] + (r.from < 0 ? r.from * per : 0)) * 1000;
    const t1 = Math.min(LT.serverNow(), (r.to >= n - 1 ? cs[n - 1][0] + (r.to - (n - 1) + 1) * per : cs[Math.max(0, Math.ceil(r.to))][0]) * 1000);
    const h = p.body.clientHeight, w = ts.width() || p.body.clientWidth;
    const hi = p.series.coordinateToPrice(0), lo = p.series.coordinateToPrice(Math.max(20, p.candleBottom ? p.candleBottom(h) : h - 28));
    if (hi == null || lo == null || !(t1 > t0)) return null;
    return {t0: Math.round(t0), t1: Math.round(t1), lo, hi, cols: Math.max(60, Math.min(400, Math.round(w / 3))), rows: Math.max(60, Math.min(300, Math.round(h / 3)))};
  }
  async function pollLayer(L, q, force) {
    const S = st(), ls = layerState[L.el], sym = S.symbol;
    if (!S.mainOpts[L.el] || ls.busy) return;
    const key = [sym, L.extra(), Math.round(q.t0 / 5000), Math.round(q.t1 / 5000), q.lo.toPrecision(6), q.hi.toPrecision(6), q.cols, q.rows].join('|');
    const cur = S[L.slot];
    if (!force && key === ls.key && cur && Date.now() - (cur.at || 0) < L.every(S.tf) - 500) return;
    ls.busy = true;
    try {
      const h = await LT.api(L.url(sym, `t0=${q.t0}&t1=${q.t1}&lo=${q.lo}&hi=${q.hi}&cols=${q.cols}&rows=${q.rows}`));
      if (sym !== S.symbol) return;
      ls.key = key;
      h.at = Date.now();
      S[L.slot] = h.ready && !h.empty && h.data ? heatImage(h, L.cmap) : h;
      S.version++;
      renderLegend();
    } catch (e) { /* le prochain passage reessaiera */ } finally { ls.busy = false; }
  }
  // V30 : intérêt ouvert en bougies, delta et CVD (sous-fenêtres) : relus à chaque nouvelle bougie, et toutes les 30 secondes
  const indState = {key: '', busy: false};
  async function pollInd(force) {
    const S = st(), d = S.data;
    if (!mainVisible() || !(S.mainOpts.oi || S.mainOpts.delta) || !d || !d.candles || !d.candles.length || indState.busy) return;
    const key = [S.symbol, S.tf, d.candles[d.candles.length - 1][0]].join('|');
    if (!force && key === indState.key && S.ind && Date.now() - (S.ind.at || 0) < 30000) return;
    indState.busy = true;
    try {
      const r = await LT.api(`/api/indicators?symbol=${S.symbol}&tf=${S.tf}`);
      if (r.symbol !== S.symbol || r.tf !== S.tf) return;
      r.at = Date.now(); indState.key = key; S.ind = r; S.version++;
    } catch (e) { /* le prochain passage reessaiera */ } finally { indState.busy = false; }
  }
  async function pollHeat(force) {
    clearTimeout(heatTimer);
    heatTimer = setTimeout(() => pollHeat(false), 8000);
    pollInd(force);
    if (!heatWanted()) return;
    const q = heatQuery();
    if (!q) return;
    LAYERS.forEach(L => pollLayer(L, q, force));
  }
  // appelé à chaque image : si la vue a bougé (défilement, zoom), nouvelle image une demi-seconde après
  let viewSig = '', viewT = 0;
  function tick() {
    try {                                             // jamais d'erreur ici : la boucle d'affichage du terminal s'arrêterait
      pollInd(false);
      if (!heatWanted()) return;
      const q = heatQuery(); if (!q) return;
      const s = [Math.round(q.t0 / 60000), Math.round(q.t1 / 60000), q.lo.toPrecision(4), q.hi.toPrecision(4), q.cols, q.rows].join();
      if (s !== viewSig) { viewSig = s; viewT = Date.now(); }
      else if (viewT && Date.now() - viewT > 500) { viewT = 0; pollHeat(true); }
    } catch (e) { /* vue pas encore prête */ }
  }
  // bulle : montant en attente (carnet) et positions estimées à liquider (carte) sous le pointeur
  function cellAt(H, panel, x, y) {
    if (!H || !H.img || !H.bytes) return null;
    const price = panel.series.coordinateToPrice(y), tt = panel.chart.timeScale().coordinateToTime(x);
    if (price == null) return null;
    const j = Math.floor((price - H.lo) / H.rowsz), L = panel._L;
    let tms = tt != null ? tt * 1000 : null;
    if (tms == null && L) { const x1 = L.xr; tms = H.t1 - Math.max(0, x1 - x) / Math.max(1, x1) * (H.t1 - H.t0); }
    if (tms == null) return null;
    const i = Math.floor((tms - H.t0) / ((H.t1 - H.t0) / H.cols));
    if (j < 0 || j >= H.rows || i < 0 || i >= H.cols) return null;
    const q = H.bytes[j * H.cols + i];
    return q ? {q, lo: H.lo + j * H.rowsz, hi: H.lo + (j + 1) * H.rowsz} : null;
  }
  function heatTip(panel, x, y) {
    const S = st(), out = [];
    if (S.mainOpts.heat) {
      const c = cellAt(S.bookHeat, panel, x, y);
      if (c) out.push(`<b>${LT.usdFmt(S.bookHeat.ref * Math.pow(c.q / 255, 2))}</b> en attente entre ${LT.fmtP(c.lo)} et ${LT.fmtP(c.hi)}<div class="muted small">${c.q >= 255 ? 'au plus fort de l\'image (99e centile ou plus) · ' : ''}carnet : achats et ventes additionnés, bourses choisies</div>`);
    }
    if (S.mainOpts.liqmap) {
      const c = cellAt(S.liqMap, panel, x, y);
      if (c) {
        const H = S.liqMap, coins = H.ref * Math.pow(c.q / 255, 1 / 0.85), px = (c.lo + c.hi) / 2;
        out.push(`≈ <b>${LT.fmtQty(coins)} ${esc(H.unit || '')}</b> (${LT.usdFmt(coins * px)}) de positions à liquider entre ${LT.fmtP(c.lo)} et ${LT.fmtP(c.hi)}<div class="muted small">${c.q >= 255 ? 'au plus fort de l\'image · ' : ''}carte des liquidations : estimation (intérêt ouvert Binance, leviers 10× à 100×)</div>`);
      }
    }
    return out.length ? out.join('<div style="height:6px"></div>') : null;
  }

  function init(lt) {
    LT = lt;
    wireChooser();
    document.addEventListener('click', e => {
      const b = e.target.closest('#instTabs [data-inst]');
      if (b) setTab(b.dataset.inst);
    });
  }
  return {init, apply, curSet, wsOf, rememberTf, renderLegend, toggleChooser, closeChooser, renderTabs, setTab, onLayout, pollHeat, tick, heatTip, viewOf, VIEWS, EL, PRESET, freshSet};
})();
