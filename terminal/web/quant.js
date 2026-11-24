// V45 : onglet Quant. Tout ce qui s'affiche ici vient de /api/quant (ingest/hub.py) : des sources publiques réelles lues en direct, calculées
// par le moteur exact (paquet quant : entiers et décimaux, aucun flottant dans les sommes). Une source qui ne répond pas affiche son erreur ;
// rien n'est jamais remplacé par une valeur fabriquée.
//   Régime de marché   prix + intérêt ouvert + financement + CVD des perpétuels + CVD du comptant, sur 15 minutes, 1 heure et 4 heures
//   CVD exact          transaction par transaction (côté de l'agresseur), contrôlé chaque minute contre la bougie officielle de Binance
// V45.1 : le moteur ne tourne que pendant que cet onglet est ouvert (il s'arrête 5 minutes après) : aucun effet sur le démarrage du terminal.
//   Divergences, absorptions, bourses (BTC), carnet (déséquilibre pondéré, murs, ordres retirés), profil de volume exact, dérivés,
//   options (volatilité, skew 25 delta, max pain, gamma), réseau Bitcoin.
// V48 : page réorganisée (synthèse en tête, puis cinq rubriques ; les explications sont repliées sous « Comment lire »), nouvelle carte
//   « Comptant contre perpétuels » (24 et 48 heures, bougies officielles d'une heure) et plus d'état des sources.
// V51 : page rangée en rubriques fixes (navigation en haut, chaque rubrique repliable, cartes par paires de même hauteur) ; rubrique
//   Options : baleines (ordres d'options d'au moins 1, 5 ou 10 millions de dollars, avec leur stratégie, leur prime et leur delta) et
//   positions ouvertes (variations de l'intérêt ouvert de chaque option sur 24 heures), lues en continu chez Deribit (ingest/optflow.py).
// V54 : page allégée. En haut, « L'essentiel » : six chiffres en grand (qui mène sur 24 heures, régime, CVD, carnet, levier, options),
//   chacun avec un verdict et une phrase qui dit comment le lire, puis les derniers signaux. Le détail est rangé dessous, dans des
//   rubriques fermées par défaut. Retirés : CVD par bourse, profil de volume exact (déjà sur les graphiques), tableau des dérivés par
//   bourse (résumé dans « Levier »), listes trop longues (baleines, échéances, réseau Bitcoin raccourcis).
const QUANTV = (() => {
  'use strict';
  let LT = null, root = null, on = false, timer = null, data = null, err = null, busy = false, wsort = 'big';
  const ls = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* rien */ } };
  let wmin = [1e6, 5e6, 1e7].includes(ls('qWhaleMin', 5e6)) ? ls('qWhaleMin', 5e6) : 5e6;
  const opened = new Set(ls('qOpen54', []));                            // V54 : rubriques de détail ouvertes (fermées par défaut)
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const sgn = v => v > 0 ? '+' : v < 0 ? '−' : '';
  const nf = (v, d = 0) => v == null || !isFinite(v) ? '—' : Math.abs(v).toLocaleString('fr-FR', {minimumFractionDigits: d, maximumFractionDigits: d}).replace(/ | /g, ' ');
  const sn = (v, d = 0) => v == null || !isFinite(v) ? '—' : sgn(v) + nf(v, d);
  const pct = (v, d = 1) => v == null || !isFinite(v) ? '—' : sgn(v) + nf(v * 100, d) + ' %';
  const usd = v => { if (v == null || !isFinite(v)) return '—'; const a = Math.abs(v);
    return a >= 1e9 ? nf(a / 1e9, 2) + ' Md$' : a >= 1e6 ? nf(a / 1e6, a >= 1e8 || a % 1e6 === 0 ? 0 : 1) + ' M$' : a >= 1e3 ? nf(a / 1e3, 0) + ' k$' : nf(a, 0) + ' $'; };
  const susd = v => v == null ? '—' : sgn(v) + usd(v);
  const px = v => v == null ? '—' : LT.fmtP ? LT.fmtP(v) : nf(v, 2);
  const HM = new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', hour: '2-digit', minute: '2-digit'});
  const DM = new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
  const DAYF = new Intl.DateTimeFormat('fr-FR', {timeZone: 'UTC', day: '2-digit', month: '2-digit'});
  const ago = ms => { if (ms == null) return '—'; const s = Math.max(0, Math.round(ms / 1000));
    return s < 90 ? `il y a ${s} s` : s < 5400 ? `il y a ${Math.round(s / 60)} min` : s < 172800 ? `il y a ${Math.round(s / 3600)} h` : `il y a ${Math.round(s / 86400)} j`; };
  const cls = v => v > 0 ? 'up' : v < 0 ? 'dn' : '';
  const WLAB = {'5m': '5 min', '15m': '15 min', '1h': '1 h', '4h': '4 h', '24h': '24 h'};
  const card = (title, body, extra = '', meta = '') => `<section class="qcard ${extra}"><div class="qh"><span class="qht">${title}</span>${meta ? `<span class="qhm">${meta}</span>` : ''}</div>${body}</section>`;
  const bad = t => `<p class="muted small">${esc(t)}</p>`;
  const coin = () => (LT.st.symbol || '').replace(/USDT$/, '');

  function init(lt, host) {
    LT = lt; root = host;
    root.innerHTML = `<div class="qbar"><b class="qttl"></b><span class="qmeta muted small"></span><span class="spacer"></span>` +
      `<span class="muted small">Données réelles uniquement · calculs exacts</span></div><div class="qgrid"></div>`;
    root.addEventListener('click', e => {
      const ws = e.target.closest('[data-qws]'); if (ws) { wsort = ws.dataset.qws; render(); return; }
      const wm = e.target.closest('[data-qwm]'); if (wm) { wmin = +wm.dataset.qwm; lsSet('qWhaleMin', wmin); load(); return; }
      const f = e.target.closest('[data-qfold]');
      if (f) { const k = f.dataset.qfold; if (opened.has(k)) opened.delete(k); else opened.add(k); lsSet('qOpen54', [...opened]); render(); }
    });
  }

  async function load() {
    if (busy || !on) return;
    busy = true;
    try {
      const r = await fetch(`/api/quant?symbol=${encodeURIComponent(LT.st.symbol)}&whale=${wmin}`);
      if (!r.ok) throw new Error(r.status === 404 ? 'cette page demande la version 45 du terminal : ferme la fenêtre noire et relance-le' : 'HTTP ' + r.status);
      const d = await r.json();
      if (d.ok === false) { err = d.why || 'indisponible'; data = null; } else { data = d; err = null; }
    } catch (e) { err = String(e.message || e); }
    busy = false;
    render();
  }

  // ---------- outils de présentation ----------
  const help = html => `<details class="qhelp"><summary>Comment lire</summary>${html}</details>`;
  const sec = t => `<div class="qsec">${t}</div>`;
  const tile = (lab, val, sub, c = '') => `<div class="qtile"><div class="qtl">${lab}</div><div class="qtv ${c}">${val}</div><div class="qts muted">${sub || ''}</div></div>`;
  const CONV = {both_buy: 'Acheteuse forte', spot_vs_shorts: 'Comptant acheteur', spot_buy: 'Comptant acheteur', lev_buy_spot_sell: 'Levier seul · fragile',
    lev_buy: 'Levier acheteur', both_sell: 'Vendeuse forte', spot_sell: 'Comptant vendeur', lev_sell: 'Levier vendeur', flat: 'Neutre', missing: '—'};
  const bcls = b => b > 0 ? 'up' : b < 0 ? 'dn' : '';

  // ---------- V54 : « L'essentiel » : un chiffre en grand, un verdict, une phrase de lecture ----------
  const VERD = b => b > 0 ? ['Acheteur', 'up'] : b < 0 ? ['Vendeur', 'dn'] : ['Neutre', ''];
  const kpi = o => `<div class="qk ${o.bias > 0 ? 'b-up' : o.bias < 0 ? 'b-dn' : 'b-nt'}${o.wide ? ' wide' : ''}">` +
    `<div class="qkh"><span class="qkl">${o.lab}</span>${o.chip ? `<span class="qkc ${o.chipCl || ''}">${o.chip}</span>` : ''}</div>` +
    `<div class="qkn ${o.cl || ''}${o.txt ? ' txt' : ''}">${o.val}</div>${o.sub ? `<div class="qks">${o.sub}</div>` : ''}` +
    `${o.read ? `<div class="qkr">${o.read}</div>` : ''}</div>`;
  const bar = (v, scale) => { const w = v == null ? 0 : Math.min(50, Math.abs(v) / scale * 50);
    return `<div class="qobar"><i class="${v >= 0 ? 'up' : 'dn'}" style="width:${w.toFixed(1)}%;${v >= 0 ? 'left:50%' : `left:${(50 - w).toFixed(1)}%`}"></i></div>`; };
  const READ_SP = {
    both_buy: 'Argent réel et levier achètent ensemble : la hausse est solide.',
    spot_vs_shorts: 'Le comptant achète contre des vendeurs à levier : accumulation ; si le prix monte, les shorts devront racheter.',
    spot_buy: 'De l\'argent réel achète, sans levier : hausse saine, sans excès.',
    lev_buy_spot_sell: 'Le levier achète mais le comptant vend : hausse fragile, risque de liquidation des longs.',
    lev_buy: 'Seul le levier achète : attendre que le comptant confirme avant de suivre.',
    both_sell: 'Argent réel et levier vendent ensemble : la baisse est solide.',
    spot_sell: 'Le comptant vend, sans levier : distribution d\'argent réel, pression vendeuse de fond.',
    lev_sell: 'Seul le levier vend : baisse fragile, risque de rachat des shorts.',
    flat: 'Aucun des deux marchés ne domine : attendre qu\'un déséquilibre apparaisse.',
    missing: 'Une des deux sources manque : pas de lecture.'};
  const READ_REG = {
    cascade_longs: 'Des longs sont liquidés en chaîne : la baisse s\'accélère, attendre la fin de la purge avant d\'acheter.',
    short_squeeze: 'Des shorts rachètent de force : hausse rapide, souvent courte.',
    shorts_agressifs: 'Des vendeurs ouvrent à levier : pression baissière, mais carburant pour un rachat si le prix tient.',
    longs_agressifs: 'Des acheteurs ouvrent à levier : pression haussière, mais carburant pour une purge si le prix casse.',
    accumulation_spot: 'Le comptant achète nettement : accumulation de fond.',
    distribution_spot: 'Le comptant vend nettement : distribution de fond.',
    compression: 'Des positions se construisent sans mouvement : un déplacement fort se prépare.',
    neutre: 'Rien de marqué sur l\'heure : pas de signal de régime.'};

  function whoLeads(d) {
    const S = d.spotPerp, sp = S && S.windows && S.windows['24h'], w48 = S && S.windows && S.windows['48h'];
    if (!sp) return kpi({lab: 'Qui mène · 24 h', val: '—', txt: true, read: esc(S && S.error ? S.error : 'chargement'), bias: 0});
    const b = sp.read.bias, scale = Math.max(0.05, Math.abs((sp.spot || {}).imb || 0), Math.abs((sp.perp || {}).imb || 0));
    const ln = (n, x) => !x || x.error ? `<div class="qkb"><span>${n}</span><span class="muted">—</span></div>` :
      `<div class="qkb"><span>${n}</span>${bar(x.imb, scale)}<b class="${cls(x.deltaUsd)}">${susd(x.deltaUsd)}</b><span class="${cls(x.imb)}">${pct(x.imb)}</span></div>`;
    const v = sp.read.code === 'lev_buy_spot_sell' ? ['Fragile', 'amb'] : VERD(b);
    return kpi({lab: 'Qui mène · 24 h', val: esc(CONV[sp.read.code] || '—'), txt: true, cl: bcls(b), chip: v[0], chipCl: v[1], bias: b,
      sub: ln('Comptant', sp.spot) + ln('Perpétuels', sp.perp) + (w48 && w48.read ? `<div class="muted">48 h : <span class="${bcls(w48.read.bias)}">${esc(CONV[w48.read.code] || '—')}</span></div>` : ''),
      read: READ_SP[sp.read.code] || esc(sp.read.label)});
  }
  function regimeKpi(d) {
    const R = d.regime || {}, r = R['1h'];
    if (!r || r.error) return kpi({lab: 'Régime · 1 h', val: '—', txt: true, read: esc(r ? r.error : 'pas encore mesuré'), bias: 0});
    const v = VERD(r.bias), other = ['15m', '4h'].map(k => { const x = R[k]; return x && !x.error ? `${WLAB[k]} : <span class="${bcls(x.bias)}">${esc(x.label)}</span>` : ''; }).filter(Boolean).join(' · ');
    return kpi({lab: 'Régime · 1 h', val: esc(r.label), txt: true, cl: bcls(r.bias), chip: v[0], chipCl: v[1], bias: r.bias,
      sub: `<div class="qmeter" title="force ${nf(r.score * 100)} %"><i class="${bcls(r.bias)}" style="width:${Math.min(100, r.score * 100).toFixed(0)}%"></i></div>` +
        `${(r.notes || []).length ? `<div class="muted">${esc(r.notes.slice(0, 2).join(' · '))}</div>` : ''}${other ? `<div>${other}</div>` : ''}`,
      read: READ_REG[r.code] || ''});
  }
  function cvdKpi(d) {
    const c = d.cvd && d.cvd.windows && d.cvd.windows['1h'], P = c && c.perp, S = c && c.spot;
    if (!P || !P.n) return kpi({lab: 'CVD · 1 h', val: '—', read: 'pas encore de transactions', bias: 0});
    const sg = x => !x || !x.n ? 0 : x.imb >= 0.01 ? 1 : x.imb <= -0.01 ? -1 : 0, p = sg(P), q = sg(S);
    const read = p > 0 && q > 0 ? 'Perpétuels et comptant achètent : pression acheteuse saine.' : p < 0 && q < 0 ? 'Perpétuels et comptant vendent : pression vendeuse nette.' :
      p > 0 && q < 0 ? 'Le levier achète, le comptant vend : hausse fragile.' : p < 0 && q > 0 ? 'Le comptant achète, le levier vend : absorption, les shorts s\'exposent.' :
      p || q ? `${p ? 'Seuls les perpétuels' : 'Seul le comptant'} ${(p || q) > 0 ? 'achète' + (p ? 'nt' : '') : 'vend' + (p ? 'ent' : '')} : signal faible tant que l'autre ne suit pas.` : 'Flux équilibré sur l\'heure : personne ne force.';
    const b = p + q, cell = (n, x) => `<div><span class="muted">${n}</span><b class="${cls(x && x.deltaUsd)}">${x && x.n ? susd(x.deltaUsd) : '—'}</b><small class="${cls(x && x.imb)}">${x && x.n ? pct(x.imb) + ' du volume' : ''}</small></div>`;
    const v = p > 0 && q < 0 ? ['Fragile', 'amb'] : p < 0 && q > 0 ? ['Absorption', 'amb'] : VERD(b);
    return kpi({lab: 'CVD · 1 h', val: `<div class="qk2">${cell('Perpétuels', P)}${cell('Comptant', S)}</div>`, chip: v[0], chipCl: v[1], bias: b, read});
  }
  function bookKpi(d) {
    const b = d.book;
    if (!b || b.error) return kpi({lab: 'Carnet · ± 0,5 %', val: '—', read: esc(b ? b.error : 'indisponible') + ' (il se remplit en quelques secondes une fois l\'onglet ouvert)', bias: 0});
    const v = b.obi['0.005'], near = side => (b.walls[side] || []).slice().sort((a, c) => a.dist - c.dist)[0];
    const wa = near('ask'), wb = near('bid'), pulled = (b.events || []).find(e => /retir/.test(e.kind));
    const bias = v >= 0.2 ? 1 : v <= -0.2 ? -1 : 0, ch = VERD(bias);
    return kpi({lab: 'Carnet · ± 0,5 %', val: pct(v, 0), cl: cls(v), chip: ch[0], chipCl: ch[1], bias,
      sub: `<div class="muted">en attente : achat ${usd(b.depth['0.005'].bid)} · vente ${usd(b.depth['0.005'].ask)}</div>` +
        [wa ? `<span class="dn">mur vendeur ${px(wa.price)}</span> <span class="muted">(${usd(wa.usd)}, à ${nf(wa.dist * 100, 2)} %)</span>` : '',
         wb ? `<span class="up">mur acheteur ${px(wb.price)}</span> <span class="muted">(${usd(wb.usd)}, à ${nf(wb.dist * 100, 2)} %)</span>` : ''].filter(Boolean).map(x => `<div>${x}</div>`).join('') +
        (pulled ? `<div class="muted">dernier mur retiré : ${pulled.side === 'bid' ? 'acheteur' : 'vendeur'} ${px(pulled.price)}, ${ago(d.now - pulled.t)}</div>` : ''),
      read: v >= 0.2 ? 'Plus d\'acheteurs en attente près du prix : soutien juste en dessous.' : v <= -0.2 ? 'Plus de vendeurs en attente près du prix : résistance juste au-dessus.' :
        'Carnet équilibré près du prix : pas de mur décisif. Un mur retiré juste avant d\'être touché est souvent de l\'affichage.'});
  }
  function leverKpi(d) {
    const x = d.derivs || {}, o = x.others || {}, sp = d.spotPerp && d.spotPerp.windows && d.spotPerp.windows['24h'];
    const mv = sp && sp.perp ? sp.perp.move : null, oi = x.oi24h, fu = x.funding != null ? x.funding : (o.okx || o.bybit || {}).funding;
    const fsrc = x.funding != null ? 'Binance' : o.okx ? 'OKX' : o.bybit ? 'Bybit' : '';
    let read = oi == null || mv == null ? 'Variation de l\'intérêt ouvert pas encore connue (relevé toutes les 5 minutes).' :
      oi > 0.01 && mv > 0.003 ? 'Des acheteurs à levier ouvrent : hausse alimentée par le levier.' : oi > 0.01 && mv < -0.003 ? 'Des vendeurs à levier ouvrent : baisse alimentée par les shorts.' :
      oi < -0.01 && mv > 0.003 ? 'Des shorts rachètent : hausse par fermeture de positions, souvent courte.' : oi < -0.01 && mv < -0.003 ? 'Des longs sortent ou sont liquidés : purge du levier.' :
      oi > 0.01 ? 'Le levier s\'accumule sans que le prix bouge : un mouvement fort se prépare.' : 'Levier stable : pas de signal.';
    if (fu != null && fu >= 0.0003) read += ' Financement élevé : acheteurs à levier nombreux, risque de purge.';
    else if (fu != null && fu <= -0.0001) read += ' Financement négatif : vendeurs nombreux, risque de rachat.';
    const bias = oi == null || mv == null ? 0 : (oi > 0.01 ? Math.sign(mv) : 0);
    return kpi({lab: 'Levier · 24 h', val: oi == null ? '—' : pct(oi, 2), cl: cls(oi), chip: oi == null ? '' : oi > 0.01 ? 'Levier qui monte' : oi < -0.01 ? 'Levier qui sort' : 'Stable', chipCl: oi > 0.01 ? 'amb' : '', bias,
      sub: `<div class="muted">intérêt ouvert sur 24 h${x.oi1h != null ? ` · 1 h <span class="${cls(x.oi1h)}">${pct(x.oi1h, 2)}</span>` : ''}</div>` +
        `<div>financement ${fu == null ? '—' : `<b class="${cls(fu)}">${pct(fu, 4)}</b> / 8 h`}${fsrc ? ` <span class="muted">(${fsrc})</span>` : ''}${x.longShare != null ? ` · <span class="muted">${nf(x.longShare * 100)} % des comptes longs</span>` : ''}</div>`,
      read});
  }
  function optionsKpi(d) {
    const o = d.options, f = d.optFlow, ws = f && f.whales && f.whales.sum, lab = 'Options BTC' + (d.symbol === 'BTCUSDT' ? '' : ' · référence');
    if (!o || o.error) return kpi({lab, val: '—', read: esc(o ? o.error : 'indisponible'), bias: 0});
    const g = o.gex || {}, pos = g.total > 0, above = o.index != null && g.flip != null ? o.index >= g.flip : null, mp = (o.maxPain || [])[0];
    const read = pos ? `Gamma positif : les teneurs de marché freinent les mouvements${g.flip ? ` tant que le prix reste au-dessus de ${px(g.flip)}` : ''}.` :
      `Gamma négatif : les teneurs de marché amplifient les mouvements (accélérations)${g.flip ? ` ; au-dessus de ${px(g.flip)}, ça se calme` : ''}.`;
    const wd = ws && ws.n ? `baleines 24 h : delta net <b class="${cls(ws.delta)}">${sn(ws.delta)} BTC</b> <span class="muted">(${nf(ws.n)} ordres)</span>` : '';
    return kpi({lab, val: susd(g.total), cl: cls(g.total), chip: pos ? 'Amorti' : 'Amplifié', chipCl: pos ? 'up' : 'dn', bias: 0,
      sub: `<div class="muted">gamma pour 1 % de mouvement${above != null ? ` · prix ${above ? 'au-dessus' : 'en dessous'} de la bascule` : ''}</div>` +
        `<div>bascule <b>${px(g.flip)}</b> · calls <b>${px(g.callWall)}</b> · puts <b>${px(g.putWall)}</b>${mp ? ` · max pain <b>${px(mp.maxPain)}</b>` : ''}</div>${wd ? `<div>${wd}</div>` : ''}`,
      read});
  }
  function lastSignals(d) {
    const c = d.cvd || {}, short = t => String(t || '').split(' : ')[0];
    const items = [...(c.divergences || []).map(x => ({t: x.known || x.t2, side: x.side, txt: short(x.text), where: `${x.market === 'perp' ? 'perpétuels' : 'comptant'} · ${px(x.p2)}`})),
      ...(c.absorptions || []).map(x => ({t: x.t, side: x.side, txt: short(x.text), where: `${x.market === 'perp' ? 'perpétuels' : 'comptant'} · ${px(x.price)} · ${nf(x.volRatio, 1)} × le volume habituel`}))]
      .sort((a, b) => b.t - a.t).slice(0, 4);
    if (!items.length) return '';
    return `<div class="qsig"><span class="qkl">Derniers signaux</span>${items.map(x => `<span class="qsi"><b class="${x.side === 'bull' ? 'up' : 'dn'}">${x.side === 'bull' ? '▲' : '▼'} ${esc(x.txt)}</b>` +
      ` <span class="muted">${HM.format(x.t)} · ${esc(x.where)}</span></span>`).join('')}` +
      `<span class="qsih muted">▲ = favorable à la hausse, ▼ = à la baisse · divergence : le CVD contredit le prix ; absorption : gros volume sans mouvement</span></div>`;
  }
  function summary(d) {
    return `<div class="qdash">${whoLeads(d)}${regimeKpi(d)}${cvdKpi(d)}${leverKpi(d)}${bookKpi(d)}${optionsKpi(d)}</div>${lastSignals(d)}`;
  }

  // ---------- flux d'ordres ----------
  function spotPerpCard(d) {
    const s = d.spotPerp;
    const title = 'Comptant contre perpétuels · conviction sur 24 et 48 heures';
    if (!s || s.error) return card(title, bad(s ? s.error : 'indisponible'));
    const W = s.windows || {};
    const imbs = [];
    ['24h', '48h'].forEach(k => ['spot', 'perp'].forEach(m => { const v = W[k] && W[k][m] && W[k][m].imb; if (v != null) imbs.push(Math.abs(v)); }));
    const scale = Math.max(0.05, ...imbs);                               // la barre la plus longue remplit la moitié ; au moins ± 5 %
    const bar = v => { const w = v == null ? 0 : Math.min(50, Math.abs(v) / scale * 50);
      return `<div class="qobar"><i class="${v >= 0 ? 'up' : 'dn'}" style="width:${w.toFixed(1)}%;${v >= 0 ? 'left:50%' : `left:${(50 - w).toFixed(1)}%`}"></i></div>`; };
    const line = (lab, x) => !x || x.error ? `<div class="qspr"><span>${lab}</span><span class="muted small qspe">${esc(x ? x.error : 'pas de données')}</span></div>` :
      `<div class="qspr"><span>${lab}</span>${bar(x.imb)}<b class="${cls(x.deltaUsd)}">${susd(x.deltaUsd)}</b><span class="${cls(x.imb)} small">${pct(x.imb)}</span></div>`;
    const block = k => { const w = W[k]; if (!w) return '';
      const mv = w.perp && w.perp.move != null ? ` · prix <span class="${cls(w.perp.move)}">${pct(w.perp.move, 2)}</span>` : '';
      const share = w.spotShareVol != null ? `<div class="muted small">Le comptant fait ${nf(w.spotShareVol * 100)} % du volume au marché et ${nf(w.spotShareBuy * 100)} % des achats.</div>` : '';
      return `<div class="qsp"><div class="qsph"><b>${k === '24h' ? '24 heures' : '48 heures'}</b><span class="muted small">${mv}</span></div>` +
        `<div class="qverdict ${bcls(w.read.bias)}">${esc(w.read.label)}</div>${line('Comptant', w.spot)}${line('Perpétuels', w.perp)}${share}</div>`; };
    return card(title, `<div class="qsps">${block('24h')}${block('48h')}</div>${hourly(s.series || [])}` + help(
      `<p class="small">Chaque bougie officielle d'une heure de Binance donne le volume acheté au marché (l'acheteur traverse l'écart) ; le reste est vendu au marché. Net = achats − ventes, en dollars. Le pourcentage est la part nette dans le volume de ce marché : c'est lui qui compare les deux marchés, car les perpétuels échangent bien plus que le comptant.</p>` +
      `<p class="small">Un marché « achète » quand sa part nette dépasse + 1 %, « vend » sous − 1 %. Le comptant, c'est de l'argent réel qui achète la pièce ; les perpétuels, c'est du levier. Comptant et perpétuels acheteurs : conviction forte. Perpétuels acheteurs et comptant vendeur : hausse portée par le levier, fragile (risque de liquidation des longs). Comptant acheteur et perpétuels vendeurs : accumulation face à des vendeurs à découvert, qui peut finir en rachat forcé des shorts.</p>` +
      `<p class="muted small">Barres d'une heure de 48 heures, l'heure en cours comprise (elle se complète au fil de l'heure). Relu chaque minute.</p>`), '');
  }

  function hourly(rows) {
    if (rows.length < 3) return '';
    const W = 600, lab = 14, lane = 56, gap = 8, H = 2 * (lab + lane) + gap, n = rows.length, bw = W / n;
    const draw = (idx, y0) => {
      const v = rows.map(r => r[idx]);
      const mx = Math.max(...v.map(x => Math.abs(x || 0))) || 1;
      const mid = y0 + lane / 2;
      let out = `<line x1="0" x2="${W}" y1="${mid}" y2="${mid}" stroke="rgba(148,163,184,.35)" stroke-width="0.6"/>`;
      v.forEach((x, i) => { if (x == null) return; const h = Math.abs(x) / mx * (lane / 2 - 1);
        out += `<rect x="${(i * bw + bw * 0.12).toFixed(1)}" width="${(bw * 0.76).toFixed(1)}" y="${(x >= 0 ? mid - h : mid).toFixed(1)}" height="${Math.max(0.6, h).toFixed(1)}" fill="${x >= 0 ? '#22c55e' : '#ef4444'}" opacity="0.85"/>`; });
      let c = 0; const cum = v.map(x => (c += x || 0));
      const lo = Math.min(0, ...cum), hi = Math.max(0, ...cum), sp = hi - lo || 1;
      out += `<polyline fill="none" stroke="#e5e7eb" stroke-width="1.2" points="${cum.map((y, i) => `${((i + 0.5) * bw).toFixed(1)},${(y0 + lane - 2 - (y - lo) / sp * (lane - 4)).toFixed(1)}`).join(' ')}"/>`;
      return out;
    };
    const cut = Math.max(0, n - 24) * bw;
    const y2 = 2 * lab + lane + gap;
    const pc = v => (v / H * 100).toFixed(1) + '%';
    const t0 = rows[0][0], tm = rows[Math.max(0, n - 24)][0];
    return `<div class="qhw"><svg class="qhourly" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${draw(1, lab)}${draw(2, y2)}` +
      `<line x1="${cut}" x2="${cut}" y1="0" y2="${H}" stroke="#38bdf8" stroke-width="1" stroke-dasharray="3 3"/></svg>` +
      `<span class="qhl" style="top:1px">Comptant · net par heure</span><span class="qhl" style="top:${pc(lab + lane + gap)}">Perpétuels · net par heure</span></div>` +
      `<div class="qhaxis small muted"><span>${DM.format(t0)}</span><span style="left:${(cut / W * 100).toFixed(1)}%">${DM.format(tm)} · début des 24 h</span><span>maintenant</span></div>` +
      `<div class="qlegend small muted">Barres : achats − ventes au marché de chaque heure · trait clair : cumul · chaque rangée à sa propre échelle</div>`;
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
    const rows = ['15m', '1h', '4h', '24h'].map(k => {                 // V54 : sans la ligne 5 min
      const w = c.windows[k]; if (!w) return '';
      const cell = x => x.n ? `<td class="${cls(x.delta)}">${sn(x.delta, Math.abs(x.delta) < 100 ? 2 : 0)} ${coin()}${x.cover < 0.9 ? ' ≈' : ''}</td><td class="${cls(x.imb)}">${pct(x.imb)}</td>` : '<td class="muted" colspan="2">pas de données</td>';
      return `<tr><td>${WLAB[k]}</td>${cell(w.perp)}${cell(w.spot)}</tr>`;
    }).join('');
    const it = d.integrity || {};
    const okLine = ['perp', 'spot'].map(m => { const x = it[m]; if (!x) return '';
      const n = (x.verified || 0) + (x.shifted || 0);
      return `<span class="${x.mismatch ? 'dn' : n ? 'up' : 'muted'}">${m === 'perp' ? 'perpétuels' : 'comptant'} ${x.mismatch ? 'anormal' : n ? 'conforme' : 'en attente'}</span>`; }).join(' · ');
    const one = (n, x) => x ? `${n} : ${nf(x.verified)} minutes identiques à la bougie officielle, ${nf(x.shifted)} décalées au passage de la minute, ` +
      `${nf(x.repaired)} complétées après une coupure ; résidu cumulé ${sn(x.residual, 3)} ${coin()} sur ${nf(x.volume)} contrôlées` +
      `${x.mismatch ? ' : <b class="dn">anormal</b>' : ''}${x.live ? '' : ' · flux en direct pas encore reçu'}` : '';
    return card('CVD exact · transaction par transaction', `<table class="qtab">${head}${rows}</table>` + chart(c.series) +
      `<p class="small">Contrôle contre les bougies officielles : ${okLine}</p>` +
      (it.perp && it.perp.last ? `<p class="small dn">Dernier écart : ${esc(it.perp.last)}</p>` : '') + help(
      `<p class="small">Delta = achats agressifs − ventes agressives ; le pourcentage est sa part du volume. « ≈ » : fenêtre couverte à moins de 90 %.</p>` +
      `<p class="small">Contrôle d'intégrité (toutes les 5 minutes). ${one('Perpétuels', it.perp)}.<br>${one('Comptant', it.spot)}.</p>` +
      `<p class="muted small">Une transaction agrégée de Binance ne porte qu'une heure pour toutes ses exécutions : quelques-unes sont rangées dans la minute voisine de celle de la bougie officielle. Le total reste exact ; un résidu qui grandit signalerait des transactions manquantes. Les minutes fermées affichées sont celles des bougies officielles.</p>`));
  }

  // ---------- signaux ----------
  function signalsCard(d) {
    const c = d.cvd || {};
    const dv = (c.divergences || []).map(x => `<li><span class="${x.side === 'bull' ? 'up' : 'dn'}">●</span> ${esc(x.text)}. <span class="muted">` +
      `${x.market === 'perp' ? 'Perpétuels' : 'Comptant'}, pivots ${HM.format(x.t1)} (${px(x.p1)}) et ${HM.format(x.t2)} (${px(x.p2)}), connue à ${HM.format(x.known)}</span></li>`);
    const ab = (c.absorptions || []).map(x => `<li><span class="${x.side === 'bull' ? 'up' : 'dn'}">●</span> ${HM.format(x.t)} · ${esc(x.text)} ` +
      `<span class="muted">(${x.market === 'perp' ? 'perpétuels' : 'comptant'}, delta ${sn(x.delta, 1)} ${coin()} = ${nf(x.imb * 100)} % du volume, ${nf(x.volRatio, 1)} fois le volume habituel, prix ${px(x.price)})</span></li>`);
    const fold = (items, none) => { if (!items.length) return `<ul class="qlist"><li class="muted">${none}</li></ul>`;
      const more = items.length > 4 ? `<details class="qmore"><summary>${items.length - 4} plus ancienne${items.length > 5 ? 's' : ''}</summary><ul class="qlist">${items.slice(4).join('')}</ul></details>` : '';
      return `<ul class="qlist">${items.slice(0, 4).join('')}</ul>${more}`; };
    return card('Divergences et absorptions',
      `<div class="qsub">Divergences prix / CVD · barres de 5 min, 24 h</div>${fold(dv, 'aucune')}` +
      `<div class="qsub">Absorptions · barres d'1 min, 6 h</div>${fold(ab, 'aucune')}` +
      help(`<p class="muted small">Une divergence n'apparaît qu'après la confirmation du second pivot (3 barres) : elle n'est jamais dessinée en avance. Une absorption est une minute de gros volume très déséquilibrée où le prix ne suit pas.</p>`));
  }

  // ---------- liquidité ----------
  function bookCard(d) {
    const b = d.book;
    if (!b || b.error) return card('Carnet d\'ordres', bad(b ? b.error : 'indisponible'));
    const bar = (k, lab) => { const v = b.obi[k]; const w = Math.min(50, Math.abs(v) * 50);
      return `<div class="qobi"><span>${lab}</span><div class="qobar"><i class="${v >= 0 ? 'up' : 'dn'}" style="width:${w.toFixed(1)}%;${v >= 0 ? 'left:50%' : `left:${(50 - w).toFixed(1)}%`}"></i></div>` +
        `<b class="${cls(v)}">${pct(v, 0)}</b><span class="muted small">${usd(b.depth[k].bid)} / ${usd(b.depth[k].ask)}</span></div>`; };
    const wl = side => (b.walls[side] || []).map(x => `<li><span class="${side === 'bid' ? 'up' : 'dn'}">${side === 'bid' ? 'achat' : 'vente'}</span> <b>${px(x.price)}</b> · ${usd(x.usd)} · ${nf(x.mult)} fois la médiane · à ${nf(x.dist * 100, 2)} %</li>`).join('');
    const ev = (b.events || []).slice(0, 6).map(e => `<li>${HM.format(e.t)} · mur ${e.side === 'bid' ? 'acheteur' : 'vendeur'} ${px(e.price)} (${usd(e.peak)}) <b>${esc(e.kind)}</b>` +
      ` <span class="muted">après ${nf(e.lifeMs / 1000)} s, ${usd(e.traded)} échangés dessus</span></li>`).join('');
    return card('Carnet d\'ordres · déséquilibre et murs', bar('0.001', '± 0,1 %') + bar('0.005', '± 0,5 %') + bar('0.01', '± 1 %') +
      `<div class="qsub">Murs dans ± 1 %</div><ul class="qlist">${wl('ask') + wl('bid') || '<li class="muted">aucun mur en ce moment</li>'}</ul>` +
      `<div class="qsub">Fin des murs suivis</div><ul class="qlist">${ev || '<li class="muted">aucun événement pour l\'instant</li>'}</ul>` +
      help(`<p class="small">+100 % = que des acheteurs en attente, −100 % = que des vendeurs ; un ordre proche du prix pèse plus qu'un ordre lointain. À droite : dollars en attente (achat / vente). Écart achat-vente : ${nf(b.spreadBps, 2)} point de base. Un mur fait au moins 8 fois la médiane des niveaux.</p>` +
      `<p class="muted small">« retiré » : disparu alors que le prix approchait, presque rien échangé dessus (possible ordre d'affichage, ce n'est qu'un indice). « exécuté » : réellement échangé. « absorbe » : toujours là après avoir été échangé plus que sa taille (ordre rechargé).</p>`));
  }

  // ---------- options BTC (Deribit) ----------
  // sens d'une position d'après son delta net rapporté à sa taille (contrats) : sous 10 %, elle est surtout un pari sur la volatilité
  function deltaWord(delta, contracts, thr = 0.1) {
    if (delta == null || !isFinite(delta)) return 'delta inconnu';
    const r = contracts > 0 ? Math.abs(delta) / contracts : 1;
    return r < thr ? 'quasi neutre' : delta > 0 ? 'haussier' : 'baissier';
  }
  const KIND = {C: 'Call', P: 'Put'}, KIND_FR = {C: 'option d\'achat', P: 'option de vente'};
  const EXP = new Intl.DateTimeFormat('fr-FR', {timeZone: 'UTC', day: '2-digit', month: '2-digit', year: '2-digit'});
  const inDays = (t, now) => { const dd = (t - now) / 86400000; return dd < 1 ? `dans ${nf(dd * 24)} h` : `dans ${nf(dd)} j`; };
  const legTxt = g => `${g.dir > 0 ? 'achat' : 'vente'} ${nf(g.amount, g.amount < 10 ? 1 : 0)} ${KIND[g.kind].toLowerCase()} ${nf(g.strike)} ${DAYF.format(g.expiry)}`;

  function whalesCard(d) {
    const f = d.optFlow;
    const title = 'Baleines des options BTC · 24 heures';
    if (!f) return card(title, bad('lecteur des baleines coupé dans les réglages (TERMINAL_OPTION_WHALES=0)'));
    const W = f.whales || {}, S = W.sum || {};
    const meta = `Deribit${W.last ? ' · lu ' + ago(d.now - W.last) : ''}`;
    const seg = `<div class="qctl"><div class="qseg">${[['big', 'Plus gros'], ['new', 'Plus récents']].map(([k, n]) => `<button data-qws="${k}" class="${k === wsort ? 'on' : ''}">${n}</button>`).join('')}</div>` +
      `<div class="qseg">${[[1e6, '≥ 1 M$'], [5e6, '≥ 5 M$'], [1e7, '≥ 10 M$']].map(([v, n]) => `<button data-qwm="${v}" class="${v === wmin ? 'on' : ''}" title="Notionnel minimal d'un ordre (contrats × prix du BTC)">${n}</button>`).join('')}</div></div>`;
    if (f.error && !(W.biggest || []).length) return card(title, seg + bad(f.error), '', meta);
    const idx = (d.options && d.options.index) || null;
    const stats = S.n ? `<div class="qstats">` +
      `<div><span class="muted">Ordres</span><b>${nf(S.n)}</b><small class="muted">dont ${nf(S.blocks)} blocs négociés</small></div>` +
      `<div><span class="muted">Notionnel</span><b>${usd(S.notional)}</b><small class="muted">${nf(S.bull)} haussiers · ${nf(S.bear)} baissiers</small></div>` +
      `<div><span class="muted">Delta net</span><b class="${cls(S.delta)}">${sn(S.delta)} BTC</b><small class="muted">${idx ? susd(S.delta * idx) + ' d\'exposition' : ''}</small></div>` +
      `<div><span class="muted">Volatilité</span><b class="${S.vega > 0 ? 'up' : S.vega < 0 ? 'dn' : ''}">${S.vega > 0 ? 'achetée' : S.vega < 0 ? 'vendue' : '—'}</b><small class="muted">${susd(S.vega)} par point</small></div>` +
      `<div><span class="muted">Primes nettes</span><b class="small">calls ${S.premiumCalls >= 0 ? 'payées' : 'reçues'} ${usd(Math.abs(S.premiumCalls))}</b><small class="muted">puts ${S.premiumPuts >= 0 ? 'payées' : 'reçues'} ${usd(Math.abs(S.premiumPuts))}</small></div></div>` : '';
    const all = (wsort === 'new' ? W.latest : W.biggest) || [];
    const one = o => {
      const word = deltaWord(o.delta, o.contracts);
      return `<div class="qwr"><div class="qwt">${DM.format(o.t)}${o.block ? '<span class="qbadge">bloc</span>' : ''}${o.liq ? '<span class="qbadge dn">liquidation</span>' : ''}</div>` +
        `<div class="qwp"><b class="${word === 'quasi neutre' ? '' : cls(o.delta)}">${esc(o.name)}</b> <span class="muted small">· ${esc(o.reading)}</span>` +
        `<div class="small qwl">${o.legs.map(legTxt).join(' · ')}</div></div>` +
        `<div class="qwn"><b>${usd(o.notional)}</b><small class="muted">${nf(o.contracts)} BTC</small></div>` +
        `<div class="qwn"><b class="${o.premium >= 0 ? '' : 'muted'}">${usd(Math.abs(o.premium))}</b><small class="muted">prime ${o.premium >= 0 ? 'payée' : 'reçue'}</small></div>` +
        `<div class="qwn"><b class="${cls(o.delta)}">${sn(o.delta, Math.abs(o.delta) < 10 ? 1 : 0)} BTC</b><small class="muted">${word}${o.vega ? ' · vol. ' + (o.vega > 0 ? 'achetée' : 'vendue') : ''}</small></div></div>`;
    };
    const rows = all.slice(0, 6).map(one).join('') + (all.length > 6 ? `<details class="qmore"><summary>${all.length - 6} autres ordres</summary>${all.slice(6).map(one).join('')}</details>` : '');   // V54 : 6 affichés
    const head = `<div class="qwr qwh muted"><div>Heure</div><div>Position</div><div>Taille</div><div>Prime</div><div>Delta net</div></div>`;
    return card(title, seg + stats + (rows ? `<div class="qwlist">${head}${rows}</div>` : bad(`aucun ordre d'au moins ${usd(W.minUsd || wmin)} sur les dernières 24 heures`)) + help(
      `<p class="small">Une baleine est un ordre d'options dont le notionnel (contrats × prix du BTC, 1 contrat = 1 BTC) atteint le seuil choisi. Les jambes d'un même bloc négocié (ou d'un combo) sont regroupées : c'est la position complète. Le sens est celui de l'initiateur : celui qui traverse le carnet ou demande le bloc. On ne sait pas s'il ouvre ou ferme une position : la carte « Positions ouvertes » le dit pour la journée.</p>` +
      `<p class="small">Delta net : l'exposition de la position en BTC équivalents. +100 BTC se comporte comme 100 BTC achetés (gagne à la hausse), −100 BTC comme 100 BTC vendus à découvert (gagne à la baisse) ; proche de zéro (moins de 10 % de la taille) : un pari sur la volatilité plutôt que sur le sens. Il est calculé avec le modèle de Black, la volatilité de chaque exécution et le prix de l'indice : une estimation. Volatilité achetée (vega positif) : il gagne si les mouvements s'amplifient ; vendue : il parie sur le calme.</p>` +
      `<p class="muted small">Lu toutes les 5 minutes, même onglet fermé, et gardé 3 jours sur le disque${f.whales && f.whales.since ? ` ; données depuis le ${DM.format(f.whales.since)}` : ''}.</p>`), '', meta);
  }

  function oiChangeCard(d) {
    const f = d.optFlow;
    const title = 'Positions ouvertes des options BTC · variations 24 heures';
    if (!f) return '';
    const o = f.oi;
    if (!o) {
      const first = f.firstSnap ? `Première photo de l'intérêt ouvert prise ${ago(d.now - f.firstSnap)} : la comparaison apparaît après une heure et couvre 24 heures dès le ${DM.format(f.firstSnap + 86400000)}.` : 'Pas encore de photo de l\'intérêt ouvert (prise toutes les heures).';
      return card(title, bad(f.error || first), '', 'Deribit');
    }
    const row = (r, up) => `<div class="qoi"><div><b>${KIND_FR[r.kind][0].toUpperCase() + KIND_FR[r.kind].slice(1)} ${nf(r.strike)} $</b>` +
      `<small class="muted">${EXP.format(r.expiry)} · ${inDays(r.expiry, d.now)} · ouvert ${nf(r.oi)} BTC</small></div>` +
      `<div class="qoin"><b class="${up ? 'up' : 'dn'}">${sn(r.change, Math.abs(r.change) < 10 ? 1 : 0)}</b><small class="muted">${r.usd != null ? susd(r.usd) : ''}</small></div></div>`;
    const tot = (n, v) => `<span class="qchip ${cls(v)}">${n} ${sn(v)} BTC</span>`;
    const read = o.calls > 0 && o.puts > 0 ? (o.puts > o.calls * 1.3 ? 'les puts s\'accumulent davantage : demande de protection à la baisse' : o.calls > o.puts * 1.3 ? 'les calls s\'accumulent davantage : appétit pour la hausse' : 'calls et puts s\'accumulent ensemble : on prend position des deux côtés')
      : o.calls < 0 && o.puts < 0 ? 'les positions se ferment des deux côtés : le marché se désengage' : o.calls > 0 ? 'des calls s\'ouvrent pendant que des puts se ferment : biais haussier' : o.puts > 0 ? 'des puts s\'ouvrent pendant que des calls se ferment : biais baissier' : '';
    const gap = o.gapH;
    const note = gap < 20 ? `Photos espacées de ${nf(gap, 1)} h seulement : le terminal photographie l'intérêt ouvert chaque heure, la comparaison couvrira 24 heures dès le ${DM.format(o.ref + 86400000)}.` : `Photos espacées de ${nf(gap, 1)} h.`;
    return card(title, `<p class="small muted">Intérêt ouvert = contrats encore ouverts (1 contrat = 1 BTC). ${note}</p>` +
      `<div class="qchips">${tot('Calls', o.calls)}${tot('Puts', o.puts)}${read ? `<span class="small">${read}</span>` : ''}</div>` +
      `<div class="qoic"><div><div class="qoih up">Principales accumulations</div>${o.up.slice(0, 4).map(r => row(r, true)).join('') || '<p class="muted small">aucune</p>'}</div>` +
      `<div><div class="qoih dn">Principales réductions</div>${o.down.slice(0, 4).map(r => row(r, false)).join('') || '<p class="muted small">aucune</p>'}</div></div>` +
      help(`<p class="small">Différence, option par option, entre la photo la plus récente de l'intérêt ouvert et celle d'il y a environ 24 heures. Une accumulation = des positions s'ouvrent sur cette option (acheteurs et vendeurs ensemble : le sens se lit avec les baleines) ; une réduction = des positions se ferment. Les options arrivées à échéance entre les deux photos sont écartées. En dollars : contrats × prix du BTC.</p>`), '', `Deribit · photo ${ago(d.now - o.t)}`);
  }

  function gammaCard(d) {
    const o = d.options;
    if (!o) return '';
    if (o.error) return card('Gamma et max pain', bad(o.error), '', 'Deribit');
    const g = o.gex || {};
    const mp = (o.maxPain || []).slice(0, 4).map(m => `<tr><td>${DAYF.format(m.expiry)}</td><td>${nf(m.days, m.days < 3 ? 1 : 0)} j</td><td><b>${px(m.maxPain)}</b></td><td>${nf(m.calls)} / ${nf(m.puts)}</td><td>${m.putCall == null ? '—' : nf(m.putCall, 2)}</td></tr>`).join('');
    return card('Gamma et max pain', `<div class="qkvg">` +
      `<div><span class="muted">Exposition gamma</span><b class="${cls(g.total)}">${susd(g.total)}</b><small class="muted">pour 1 % de mouvement</small></div>` +
      `<div><span class="muted">Bascule du gamma</span><b>${px(g.flip)}</b><small class="muted">indice ${px(o.index)}</small></div>` +
      `<div><span class="muted">Mur de calls</span><b>${px(g.callWall)}</b><small class="muted">résistance des options</small></div>` +
      `<div><span class="muted">Mur de puts</span><b>${px(g.putWall)}</b><small class="muted">support des options</small></div></div>` +
      `<div class="qsub">Max pain et intérêt ouvert par échéance</div><table class="qtab"><tr><th>Échéance</th><th>Dans</th><th>Max pain</th><th>Calls / puts (BTC)</th><th>Put / call</th></tr>${mp}</table>` +
      help(`<p class="muted small">Gamma : calls +, puts − (hypothèse habituelle sur les teneurs de marché, non observable). Sous la bascule du gamma, les teneurs de marché amplifient les mouvements ; au-dessus, ils les freinent. Max pain : prix où les détenteurs d'options perdraient le plus à l'échéance. ${nf(o.n)} options lues, ${nf(o.withOi)} avec de l'intérêt ouvert.</p>`), '', `Deribit · ${ago(d.now - o.t)}`);
  }

  function volCard(d) {
    const o = d.options;
    if (!o || o.error) return '';
    const sm = (o.smile || []).slice(0, 4).map(s => `<tr><td>${DAYF.format(s.expiry)}</td><td>${nf(s.days, s.days < 3 ? 1 : 0)} j</td><td>${s.atm == null ? '—' : nf(s.atm * 100, 1) + ' %'}</td>` +
      `<td class="${s.skew25 > 0 ? 'dn' : s.skew25 < 0 ? 'up' : ''}">${s.skew25 == null ? '—' : sn(s.skew25 * 100, 1)}</td><td>${s.fly25 == null ? '—' : sn(s.fly25 * 100, 1)}</td></tr>`).join('');
    const near = (o.smile || [])[0];
    const lede = near && near.skew25 != null ? `<p class="small">Échéance la plus proche : skew ${sn(near.skew25 * 100, 1)} point${near.skew25 > 0 ? ' : les puts coûtent plus cher, le marché se protège de la baisse' : ' : les calls coûtent plus cher, le marché paie pour la hausse'}.</p>` : '';
    return card('Volatilité implicite et skew', lede + `<table class="qtab"><tr><th>Échéance</th><th>Dans</th><th>Au prix</th><th>Skew 25 delta</th><th>Butterfly</th></tr>${sm}</table>` +
      help(`<p class="muted small">Au prix : volatilité implicite des options au prix actuel. Skew (put − call à 25 delta) positif : les puts de protection coûtent plus cher que les calls (crainte de baisse). Butterfly positif : les ailes (grands mouvements) sont chères.</p>`), '', 'Deribit');
  }

  function chainCard(d) {
    const c = d.onchain;
    if (!c) return '';
    if (c.error) return card('Réseau Bitcoin', bad(c.error));
    const v = (x, f) => x && !x.error ? f(x) : `<span class="muted">${esc(x && x.error ? 'indisponible' : '—')}</span>`;
    const cm = c.coinmetrics && !c.coinmetrics.error ? c.coinmetrics : null;
    const L = cm ? cm.last : {}, Wk = cm && cm.weekAgo ? cm.weekAgo : {};
    const chg = k => L[k] != null && Wk[k] ? ` <span class="${cls(L[k] / Wk[k] - 1)} small">(${pct(L[k] / Wk[k] - 1)} en 7 j)</span>` : '';
    const rows = [                                                      // V54 : l'essentiel seulement (frais, attente, difficulté, blocs retirés)
      ['MVRV', cm && L.CapMVRVCur != null ? `<b>${nf(L.CapMVRVCur, 3)}</b>` + chg('CapMVRVCur') : '<span class="muted">indisponible</span>'],
      ['Entrées sur les bourses (jour)', cm && L.FlowInExNtv != null ? nf(L.FlowInExNtv) + ' BTC' + chg('FlowInExNtv') : '<span class="muted">non fourni par l\'accès gratuit</span>'],
      ['Sorties des bourses (jour)', cm && L.FlowOutExNtv != null ? nf(L.FlowOutExNtv) + ' BTC' + chg('FlowOutExNtv') : '<span class="muted">non fourni par l\'accès gratuit</span>'],
      ['Adresses actives (jour)', cm && L.AdrActCnt != null ? nf(L.AdrActCnt) + chg('AdrActCnt') : '<span class="muted">indisponible</span>'],
      ['Puissance de calcul', v(c.hashrate, h => `${nf(h.hashrateEH)} EH/s`)],
    ].map(([a, b]) => `<tr><td>${a}</td><td>${b}</td></tr>`).join('');
    return card('Réseau Bitcoin', `<table class="qtab qkv">${rows}</table>` +
      help(`<p class="muted small">MVRV : valeur de marché ÷ valeur réalisée (prix moyen d'acquisition des pièces) ; au-dessus de 1, le détenteur moyen est en gain. Sources : mempool.space et CoinMetrics (mesures quotidiennes, publiées avec un à deux jours de retard${cm ? ` ; dernier jour : ${DAYF.format(cm.t)}` : ''}).` +
      `${c.crossCheck && c.crossCheck.difficultyGapPct != null ? ` Difficulté recoupée avec blockchain.info : écart ${nf(c.crossCheck.difficultyGapPct, 4)} %.` : ''}</p>`));
  }

  // ---------- V54 : mise en page : « L'essentiel » en haut, le détail dessous dans des rubriques fermées par défaut ----------
  const row = (...cards) => { const c = cards.filter(Boolean); return c.length ? `<div class="qrow${c.length === 1 ? ' q1' : ''}">${c.join('')}</div>` : ''; };
  function section(id, title, lede, body) {
    const o = opened.has(id);
    return `<section class="qsect${o ? '' : ' folded'}" id="qs-${id}"><header class="qsh" data-qfold="${id}" title="${o ? 'Fermer' : 'Ouvrir'} le détail">` +
      `<span class="qfold">${o ? '▾' : '▸'}</span><h3>${title}</h3>${lede ? `<span class="qlede">${lede}</span>` : ''}</header>${o ? `<div class="qbody">${body}</div>` : ''}</section>`;
  }

  function render() {
    if (!root) return;
    root.querySelector('.qttl').textContent = `Quant · ${coin()}`;
    const g = root.querySelector('.qgrid'), meta = root.querySelector('.qmeta');
    if (!data || data.symbol !== LT.st.symbol) { meta.textContent = ''; g.innerHTML = card('Moteur exact', bad(!data && err || 'Chargement…')); return; }
    const sp = data.spotPerp && data.spotPerp.windows && data.spotPerp.windows['24h'], last = data.cvd && data.cvd.last && data.cvd.last.perp;
    meta.innerHTML = `<b class="qpx">${px(last || (sp && sp.perp && sp.perp.close))}</b>${sp && sp.perp && sp.perp.move != null ? ` <span class="${cls(sp.perp.move)}">${pct(sp.perp.move, 2)} sur 24 h</span>` : ''}` +
      ` · mis à jour ${HM.format(data.now)}${err ? ' · ' + esc(err) : ''}` +
      (data.warming ? ' · démarrage du moteur : l\'historique de 24 heures arrive en moins d\'une minute' : '');
    const keyOf = e => ((e.closest('.qcard') || {}).querySelector ? (e.closest('.qcard').querySelector('.qht') || {}).textContent : '') + e.className;
    const open = new Set([...root.querySelectorAll('details.qhelp[open], details.qmore[open]')].map(keyOf));
    const btc = data.symbol === 'BTCUSDT', b = data.book, ws = data.optFlow && data.optFlow.whales && data.optFlow.whales.sum;
    const nSig = ((data.cvd && data.cvd.divergences) || []).length + ((data.cvd && data.cvd.absorptions) || []).length;
    g.innerHTML = `<div class="qhead"><h3>L'essentiel</h3><span class="muted small">un chiffre, un verdict, une phrase pour le lire · le détail est plus bas</span></div>` + summary(data) +
      `<div class="qhead"><h3>Détail</h3><span class="muted small">touche une rubrique pour l'ouvrir</span></div>` +
      section('flux', 'Flux d\'ordres', 'comptant contre perpétuels heure par heure, CVD exact', row(spotPerpCard(data)) + row(cvdCard(data))) +
      section('sig', 'Signaux', nSig ? `${nSig} sur 24 h` : 'aucun sur 24 h', row(signalsCard(data))) +
      (b && !b.error ? section('liq', 'Carnet d\'ordres', 'déséquilibre à 3 distances, murs, murs retirés', row(bookCard(data))) : '') +
      section('opt', 'Options BTC' + (btc ? '' : ' <small class="muted">· référence du marché</small>'), ws && ws.n ? `baleines, positions ouvertes, gamma, volatilité` : 'positions ouvertes, gamma, volatilité',
        row(whalesCard(data)) + row(oiChangeCard(data)) + row(gammaCard(data), volCard(data))) +
      (data.onchain ? section('net', 'Réseau Bitcoin', 'MVRV, flux des bourses, adresses, puissance de calcul', row(chainCard(data))) : '');
    root.querySelectorAll('details.qhelp, details.qmore').forEach(e => { if (open.has(keyOf(e))) e.open = true; });
  }

  function show() { if (on) { load(); return; } on = true; render(); load(); timer = setInterval(load, 5000); }
  function hide() { on = false; if (timer) { clearInterval(timer); timer = null; } }
  return {init, show, hide};
})();
