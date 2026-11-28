// V54.3 : ce fichier s'appelait quant.js ; renommé qtab.js parce que la liste anti-pistage EasyPrivacy (uBlock Origin, Brave, AdGuard…) bloque
// toute adresse en « /quant.js » (le script de Quantcast porte ce nom) : l'onglet Quant restait vide chez qui utilise un bloqueur.
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
// V54.1 : DEX (exposition delta des options BTC) sous « L'essentiel » : valeur, rang sur 7, 30 ou 90 jours, lecture, jauge, et
//   l'historique DEX ou GEX (relevé chaque heure par le terminal lui-même, ingest/optflow.py) avec l'infobulle de chaque point.
// V56 : page refaite : en haut, quatre verdicts cliquables (qui domine entre comptant et perpétuels, levier, stops des perpétuels, options) ;
//   dessous, six sous-onglets : comptant ou perpétuels, levier et stops, DEX et teneurs de marché, baleines et échéances, flux et carnet, réseau.
var QUANTV = (() => {                                                  // V54.2 : « var » : le fichier peut être rechargé s'il n'est pas arrivé
  'use strict';
  let LT = null, root = null, on = false, timer = null, data = null, err = null, busy = false, wsort = 'big';
  const ls = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* rien */ } };
  let wmin = [1e6, 5e6, 1e7].includes(ls('qWhaleMin', 5e6)) ? ls('qWhaleMin', 5e6) : 5e6;
  let xwin = [7, 30, 90].includes(ls('qDexWin', 90)) ? ls('qDexWin', 90) : 90, xwhat = ls('qDexWhat', 'dex') === 'gex' ? 'gex' : 'dex', dexPts = [], dexW = 1000;
  let tab = ['sp', 'lev', 'dex', 'wh', 'flux', 'net'].includes(ls('qTab56', 'sp')) ? ls('qTab56', 'sp') : 'sp';      // V56 : sous-onglet choisi
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
    root.addEventListener('mousemove', dexTip);
    root.addEventListener('mouseleave', () => { const t = root.querySelector('.qdextip'); if (t) t.hidden = true; });
    root.addEventListener('click', e => {
      const ws = e.target.closest('[data-qws]'); if (ws) { wsort = ws.dataset.qws; render(); return; }
      const wm = e.target.closest('[data-qwm]'); if (wm) { wmin = +wm.dataset.qwm; lsSet('qWhaleMin', wmin); load(); return; }
      const xw = e.target.closest('[data-qxw]'); if (xw) { xwin = +xw.dataset.qxw; lsSet('qDexWin', xwin); render(); return; }
      const xk = e.target.closest('[data-qxk]'); if (xk) { xwhat = xk.dataset.qxk; lsSet('qDexWhat', xwhat); render(); return; }
      const tb = e.target.closest('[data-qtab]'); if (tb) { tab = tb.dataset.qtab; lsSet('qTab56', tab); render(); }
    });
  }

  // V54.1 : infobulle de l'historique DEX / GEX : le point le plus proche du pointeur
  function dexTip(e) {
    const sv = e.target.closest && e.target.closest('.qdexsvg'), w = sv && sv.closest('.qdexw'), tip = w && w.querySelector('.qdextip'), ln = sv && sv.querySelector('.qdexcur');
    if (!sv || !tip || !dexPts.length) return;
    const r = sv.getBoundingClientRect(), vx = (e.clientX - r.left) / r.width * dexW;
    const p = dexPts.reduce((a, b) => Math.abs(b.x - vx) < Math.abs(a.x - vx) ? b : a);
    tip.innerHTML = `<b>${xwhat === 'dex' ? 'DEX · exposition delta' : 'GEX · exposition gamma'}</b><span>${(xwin === 7 ? DM : DAYF).format(p.t)}</span><b class="${cls(p.v)}">${short$(p.v)}</b>`;
    tip.hidden = false;
    const px0 = p.x / dexW * r.width, left = px0 + 14 + 170 > r.width ? px0 - 184 : px0 + 14;
    tip.style.left = left + 'px'; tip.style.top = Math.max(0, p.y / 240 * r.height - 30) + 'px';
    if (ln) { ln.setAttribute('x1', p.x); ln.setAttribute('x2', p.x); ln.style.display = ''; }
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
  // ---------- V54.1 : DEX, exposition delta des options BTC ----------
  const pctWord = p => p == null ? null : p <= 5 ? 'extrême bas' : p <= 20 ? 'bas' : p >= 95 ? 'extrême haut' : p >= 80 ? 'haut' : 'milieu';
  const short$ = v => { const a = Math.abs(v), f = (x, dd) => x.toFixed(dd).replace('.', ',');
    return (v < 0 ? '−' : '') + (a >= 1e9 ? f(a / 1e9, a >= 1e10 ? 0 : 1) + ' Md $' : a >= 1e6 ? f(a / 1e6, a >= 1e8 ? 0 : 1) + ' M $' : a >= 1e3 ? f(a / 1e3, 0) + ' k $' : f(a, 0) + ' $'); };
  function dexChart(E) {
    dexPts = [];
    const k = xwhat === 'dex' ? 1 : 2, src = xwin === 7 ? (E.hourly || []) : (E.daily || []), t1 = E.last.t;
    const pts = src.filter(r => r[0] >= t1 - xwin * 86400000 && r[k] != null).map(r => ({t: r[0], v: r[k]}));
    if (pts.length < 2) return `<p class="muted small">Le graphique apparaît dès le deuxième relevé (un par heure).</p>`;
    const W = dexW = Math.max(320, Math.round(((root.querySelector('.qgrid') || root).clientWidth || 1034) - 34)), H = 240, L = 78, B = 26, T = 10, vs = pts.map(p => p.v);   // une unité = un pixel : textes et points non déformés
    let lo = Math.min(...vs), hi = Math.max(...vs); const pad = (hi - lo || Math.abs(hi) || 1) * 0.08; lo -= pad; hi += pad;
    const t0 = pts[0].t, tx = t => L + (t - t0) / ((t1 - t0) || 1) * (W - L - 10), ty = v => T + (hi - v) / (hi - lo) * (H - T - B);
    dexPts = pts.map(p => ({x: tx(p.t), y: ty(p.v), t: p.t, v: p.v}));
    let g = '';
    for (let i = 0; i <= 3; i++) { const v = hi - (hi - lo) * (i / 3) - (i === 0 ? pad * 0 : 0), y = ty(v);
      g += `<line x1="${L}" x2="${W}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" class="qdexgrid"/><text x="${L - 8}" y="${(y + 4).toFixed(1)}" text-anchor="end" class="qdexax">${short$(v)}</text>`; }
    if (lo < 0 && hi > 0) g += `<line x1="${L}" x2="${W}" y1="${ty(0).toFixed(1)}" y2="${ty(0).toFixed(1)}" class="qdexzero"/>`;
    const nx = 6;
    for (let i = 0; i < nx; i++) { const t = t0 + (t1 - t0) * i / (nx - 1);
      g += `<text x="${tx(t).toFixed(1)}" y="${H - 6}" text-anchor="${i === 0 ? 'start' : i === nx - 1 ? 'end' : 'middle'}" class="qdexax">${(xwin === 7 ? DM : DAYF).format(t)}</text>`; }
    const line = dexPts.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
    const dots = dexPts.length <= 200 ? dexPts.map((p, i) => `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${i === dexPts.length - 1 ? 4.5 : 2.6}" class="${i === dexPts.length - 1 ? 'qdexlast' : ''}"/>`).join('') : '';
    return `<div class="qdexw"><svg class="qdexsvg ${xwhat}" viewBox="0 0 ${W} ${H}">${g}` +
      `<line class="qdexcur" x1="0" x2="0" y1="${T}" y2="${H - B}" style="display:none"/><polyline points="${line}"/>${dots}</svg><div class="qdextip" hidden></div></div>`;
  }
  function dexCard(d) {
    const E = d.optFlow && d.optFlow.expo, live = d.options && !d.options.error && d.options.dex, coinNote = d.symbol === 'BTCUSDT' ? '' : ' <span class="muted small">· options BTC, référence du marché</span>';
    if (!E && !live) return `<section class="qdex"><div class="qkl">DEX · Exposition delta${coinNote}</div><p class="muted small">${d.optFlow ? 'Premier relevé dans moins d\'une heure (un relevé par heure, même onglet fermé).' : 'Lecteur des options coupé dans les réglages (TERMINAL_OPTION_WHALES=0).'}</p></section>`;
    const v = live ? live.total : E.last.dex, calls = live ? live.calls : E.last.dexCalls, puts = live ? live.puts : E.last.dexPuts;
    const R = E && E.ranks && E.ranks[String(xwin)], p = R && R.dex, span = R ? R.span : 0, full = span >= xwin - 0.5;
    const badge = p == null ? '' : `<span class="qkc ${p <= 5 || p >= 95 ? 'amb' : ''}" title="Rang du dernier relevé parmi les relevés horaires de la période (P0 = le plus bas, P100 = le plus haut)">P${p} · ${pctWord(p)} ${full ? xwin + ' j' : `sur ${nf(span, span < 2 ? 1 : 0)} j d'historique`}</span>`;
    const src = E && E.hourly ? E.hourly.filter(r => r[0] >= E.last.t - xwin * 86400000).map(r => r[1]) : [];
    const mx = Math.max(Math.abs(v), ...src.map(Math.abs)) || 1, wd = Math.min(50, Math.abs(v) / mx * 50);
    const read = v < 0 ? 'Flux mécanique vendeur : couverture en vendant comptant et perpétuels' : 'Flux mécanique acheteur : couverture en achetant comptant et perpétuels';
    const more = v < 0 ? `Les options ouvertes penchent à la baisse : ${short$(puts)} de delta en puts contre ${short$(calls)} en calls. En face, les teneurs de marché portent le delta inverse et le couvrent en vendant.`
      : `Les options ouvertes penchent à la hausse : ${short$(calls)} de delta en calls contre ${short$(puts)} en puts. En face, les teneurs de marché portent le delta inverse et le couvrent en achetant.`;
    const ext = p != null && (p <= 5 || p >= 95) ? ' Niveau rarement atteint sur la période : une telle couverture se défait souvent aux échéances (vendredi 9 h, heure de Paris).' : '';
    const age = live ? 'en direct' : `relevé ${ago(d.now - E.last.t)}`;
    const tabs = `<div class="qseg">${[['dex', 'DEX'], ['gex', 'GEX']].map(([k, n]) => `<button data-qxk="${k}" class="${k === xwhat ? 'on' : ''}">${n}</button>`).join('')}</div>` +
      `<div class="qseg">${[7, 30, 90].map(k => `<button data-qxw="${k}" class="${k === xwin ? 'on' : ''}">${k} j</button>`).join('')}</div>`;
    const hist = E ? `<div class="qdexh"><span class="qkl">Historique DEX &amp; GEX · BTC</span><span class="spacer"></span>${tabs}</div>` +
      `<div class="qdexsub muted small">${xwhat === 'dex' ? 'DEX · exposition delta ($)' : 'GEX · exposition gamma ($ à couvrir pour 1 % de mouvement ; positif = mouvements amortis, négatif = amplifiés)'}</div>` + dexChart(E) +
      `<p class="muted small">Relevé par ton terminal chaque heure, même onglet fermé, depuis le ${DAYF.format(E.first)} (${nf(E.n)} relevé${E.n > 1 ? 's' : ''}) ; ${xwin === 7 ? 'un point par heure' : 'un point par jour (le dernier relevé du jour)'}.` +
      `${full ? '' : ` Deribit ne publie pas l'historique de l'intérêt ouvert par option : la période de ${xwin} jours se remplit au fil des jours.`}</p>` : '';
    return `<section class="qdex"><div class="qdexhd"><span class="qkl">DEX · Exposition delta${coinNote}</span><b class="qdexv ${cls(v)}">${short$(v)}</b>${badge}<span class="spacer"></span><span class="muted small">${age}</span></div>` +
      `<p class="small muted">Position delta agrégée du portefeuille d'options. Une exposition structurelle, pas un signal de prix.</p>` +
      `<div class="qdexr">${read}</div><div class="qdexg" title="Le plus grand DEX de la période (en valeur absolue) remplit la moitié ; à gauche négatif, à droite positif"><i class="${v >= 0 ? 'up' : 'dn'}" style="width:${wd.toFixed(1)}%;left:${(v >= 0 ? 50 : 50 - wd).toFixed(1)}%"></i></div>` +
      `<p class="small qdexm">${more}${ext}</p>${hist}</section>`;
  }

  // ---------- flux d'ordres ----------
  function spotPerpCard(d) {
    const s = d.spotPerp;
    const title = 'Comptant contre perpétuels · heure par heure sur 48 heures';
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
    const title = 'Les plus gros ordres des baleines · 24 heures';
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
    return card(title, seg + (rows ? `<div class="qwlist">${head}${rows}</div>` : bad(`aucun ordre d'au moins ${usd(W.minUsd || wmin)} sur les dernières 24 heures`)) + help(
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

  const row = (...cards) => { const c = cards.filter(Boolean); return c.length ? `<div class="qrow${c.length === 1 ? ' q1' : ''}">${c.join('')}</div>` : ''; };
  // ---------- V56 : page refaite : quatre verdicts en haut (cliquables), puis six sous-onglets ----------
  const TABS = [['sp', 'Comptant / perpétuels'], ['lev', 'Levier et stops'], ['dex', 'DEX et teneurs'], ['wh', 'Baleines et échéances'],
    ['flux', 'Flux et carnet'], ['net', 'Réseau']];
  const PERP_C = '#a78bfa', SPOT_C = '#f59e0b';                         // violet : perpétuels (levier) ; ambre : comptant (argent réel)
  const banner = (txt, sub, c = '') => `<div class="qbanner ${c}">${txt}${sub ? `<small>${sub}</small>` : ''}</div>`;
  const sumTile = (k, lab, val, sub, chip, chipCl, bias) => `<button type="button" class="qsumc ${bias > 0 ? 'b-up' : bias < 0 ? 'b-dn' : bias === 'amb' ? 'b-amb' : 'b-nt'}${tab === k ? ' on' : ''}" data-qtab="${k}">` +
    `<span class="qkh"><span class="qkl">${lab}</span>${chip ? `<span class="qkc ${chipCl || ''}">${chip}</span>` : ''}</span><span class="qsv">${val}</span>${sub ? `<span class="qss">${sub}</span>` : ''}</button>`;
  const split = (a, b, ca, cb) => { const t = (a || 0) + (b || 0), pa = t ? a / t * 100 : 50;
    return `<span class="qsplit"><i style="width:${pa.toFixed(1)}%;background:${ca}"></i><i style="width:${(100 - pa).toFixed(1)}%;background:${cb}"></i></span>`; };
  const hbar = (v, mx, c) => `<span class="qhb"><i style="width:${Math.min(100, mx ? Math.abs(v) / mx * 100 : 0).toFixed(1)}%;background:${c}"></i></span>`;
  const dbar = (v, mx, cu = '#22c55e', cd = '#ef4444') => { const w = Math.min(50, mx ? Math.abs(v || 0) / mx * 50 : 0);   // barre centrée : négatif à gauche, positif à droite
    return `<span class="qdb"><i style="width:${w.toFixed(1)}%;left:${(v >= 0 ? 50 : 50 - w).toFixed(1)}%;background:${v >= 0 ? cu : cd}"></i></span>`; };
  const when = t => `${EXP.format(t)} <span class="muted">· ${inDays(t, data.now)}</span>`;

  // ----- comptant ou perpétuels : qui pèse le plus dans le volume, et qui achète -----
  function domData(d) {
    const w = (d.spotPerp && d.spotPerp.windows) || {}, a = w['24h'], b = w['48h'];
    if (!a || !a.spot || !a.perp || a.spot.error || a.perp.error || !(a.spot.volUsd > 0) || !(a.perp.volUsd > 0)) return null;
    const sv = a.spot.volUsd, pv = a.perp.volUsd;
    let prev = null;                                                       // part du comptant sur les 24 heures d'avant (48 h moins 24 h)
    if (b && b.spot && b.perp && !b.spot.error && !b.perp.error) { const s2 = b.spot.volUsd - sv, p2 = b.perp.volUsd - pv; if (s2 > 0 && p2 > 0) prev = s2 / (s2 + p2); }
    return {sv, pv, share: sv / (sv + pv), ratio: pv / sv, prev, read: a.read, a};
  }
  function venueSplit(d, k) {
    const V = d.venues && d.venues[k];
    if (!V || !(V.venues || []).length) return null;
    let s = 0, p = 0;
    V.venues.forEach(v => { const x = (v.buyUsd || 0) + (v.sellUsd || 0); if (/_perp$/.test(v.id)) p += x; else s += x; });
    return s + p > 0 ? {s, p, share: s / (s + p), rows: V.venues} : null;
  }
  const sideRead = (p, q) => p > 0 && q > 0 ? ['Les deux achètent', 'up'] : p < 0 && q < 0 ? ['Les deux vendent', 'dn'] : p > 0 && q < 0 ? ['Le levier achète, le comptant vend', 'amb'] :
    p < 0 && q > 0 ? ['Le comptant achète, le levier vend', 'amb'] : p ? [p > 0 ? 'Seuls les perpétuels achètent' : 'Seuls les perpétuels vendent', p > 0 ? 'up' : 'dn'] :
    q ? [q > 0 ? 'Seul le comptant achète' : 'Seul le comptant vend', q > 0 ? 'up' : 'dn'] : ['Équilibré', ''];
  function domCard(d) {
    const D = domData(d), title = 'Qui pèse le plus : comptant ou perpétuels';
    if (!D) return card(title, bad((d.spotPerp && d.spotPerp.error) || 'bougies d\'une heure pas encore lues'));
    const trend = D.prev == null ? '' : Math.abs(D.share - D.prev) < 0.003 ? 'stable par rapport aux 24 heures d\'avant' :
      `${D.share > D.prev ? 'en hausse' : 'en baisse'} : ${nf(D.prev * 100, 1)} % les 24 heures d'avant`;
    const big = `<div class="qdom"><div class="qdoml"><span style="color:${PERP_C}">■</span> Perpétuels <b>${nf((1 - D.share) * 100, 1)} %</b><small>${usd(D.pv)} échangés</small></div>` +
      `<div class="qdomr"><span style="color:${SPOT_C}">■</span> Comptant <b>${nf(D.share * 100, 1)} %</b><small>${usd(D.sv)} échangés</small></div></div>` + split(D.pv, D.sv, PERP_C, SPOT_C);
    const read = D.ratio >= 8 ? 'Le marché est piloté par le levier : un mouvement porté par les perpétuels seuls se retourne plus facilement.' :
      D.ratio <= 3 ? 'Le comptant pèse lourd : les mouvements reposent sur de l\'argent réel, ils tiennent mieux.' : 'Poids habituel du levier par rapport au comptant.';
    let ven = '';
    for (const k of ['1h', '4h']) {
      const V = venueSplit(d, k); if (!V) continue;
      const mx = Math.max(...V.rows.map(v => (v.buyUsd || 0) + (v.sellUsd || 0))) || 1;
      ven += `<div class="qsub">Toutes les bourses suivies · ${WLAB[k]} · comptant ${nf(V.share * 100, 1)} % du volume</div>${split(V.p, V.s, PERP_C, SPOT_C)}<table class="qtab qven">` +
        V.rows.map(v => { const vol = (v.buyUsd || 0) + (v.sellUsd || 0), perp = /_perp$/.test(v.id);
          return `<tr><td><span style="color:${perp ? PERP_C : SPOT_C}">■</span> ${esc(v.name)}</td><td>${hbar(vol, mx, perp ? PERP_C : SPOT_C)}</td><td>${usd(vol)}</td>` +
            `<td class="${cls(v.deltaUsd)}">${susd(v.deltaUsd)}</td><td class="${cls(v.imb)} small">${pct(v.imb)}</td></tr>`; }).join('') + '</table>';
      break;
    }
    return card(title, big + `<p class="small"><b>Les perpétuels échangent ${nf(D.ratio, 1)} fois plus que le comptant</b> (Binance, 24 heures${trend ? ' ; part du comptant ' + trend : ''}).</p>` +
      `<p class="small muted">${read}</p>${ven}` + help(`<p class="small">Volume au marché des bougies officielles d'une heure de Binance, comptant et perpétuel de la même paire, sur 24 heures (l'heure en cours comprise). Pour le BTC, le tableau reprend toutes les bourses lues en direct par le terminal (Binance, Coinbase, OKX, Bybit, Bitstamp) : net = achats au marché moins ventes au marché.</p>`), '', 'Binance');
  }
  function whoBuysCard(d) {
    const c = d.cvd && d.cvd.windows, w = (d.spotPerp && d.spotPerp.windows) || {}, rows = [];
    ['15m', '1h', '4h'].forEach(k => { const x = c && c[k]; if (x && x.perp && x.perp.n) rows.push([WLAB[k], x.spot, x.perp, 'CVD exact']); });
    ['24h', '48h'].forEach(k => { const x = w[k]; if (x && x.spot && x.perp && !x.spot.error && !x.perp.error) rows.push([k === '24h' ? '24 h' : '48 h', x.spot, x.perp, 'bougies officielles']); });
    if (!rows.length) return card('Qui achète, qui vend', bad('pas encore de transactions'));
    const sg = x => !x || x.imb == null ? 0 : x.imb >= 0.01 ? 1 : x.imb <= -0.01 ? -1 : 0;
    const mx = Math.max(0.05, ...rows.flatMap(r => [Math.abs((r[1] || {}).imb || 0), Math.abs((r[2] || {}).imb || 0)]));
    const cell = x => !x || x.imb == null ? '<td class="muted" colspan="2">—</td>' : `<td>${dbar(x.imb, mx)}</td><td><b class="${cls(x.deltaUsd)}">${susd(x.deltaUsd)}</b> <small class="${cls(x.imb)}">${pct(x.imb)}</small></td>`;
    const body = rows.map(([lab, s, p, src]) => { const r = sideRead(sg(p), sg(s));
      return `<tr title="${src}"><td><b>${lab}</b></td>${cell(s)}${cell(p)}<td><span class="qkc ${r[1]}">${r[0]}</span></td></tr>`; }).join('');
    return card('Qui achète, qui vend', `<table class="qtab qwho"><tr><th></th><th colspan="2" style="color:${SPOT_C}">Comptant</th><th colspan="2" style="color:${PERP_C}">Perpétuels</th><th>Lecture</th></tr>${body}</table>` +
      help(`<p class="small">Net = achats agressifs moins ventes agressives, en dollars ; le pourcentage est sa part dans le volume de ce marché (c'est lui qui compare les deux marchés, car les perpétuels échangent bien plus). Un marché achète au-dessus de + 1 %, vend sous − 1 %. 15 min, 1 h et 4 h : CVD exact, transaction par transaction ; 24 et 48 h : bougies officielles d'une heure.</p>` +
        `<p class="small">Les deux achètent : conviction forte. Le levier achète et le comptant vend : hausse fragile (risque de liquidation des longs). Le comptant achète et le levier vend : accumulation face à des vendeurs à découvert, qui peut finir en rachat forcé des shorts.</p>`));
  }
  function regimeCard(d) {
    const R = d.regime || {}, ks = ['15m', '1h', '4h'].filter(k => R[k] && !R[k].error);
    if (!ks.length) return '';
    return card('Régime du marché', `<div class="qreg">${ks.map(k => { const r = R[k], v = VERD(r.bias);
      return `<div class="qregc ${bcls(r.bias)}"><span class="qkl">${WLAB[k]}</span><b class="${bcls(r.bias)}">${esc(r.label)}</b><span class="qkc ${v[1]}">${v[0]}</span>` +
        `<div class="qmeter"><i class="${bcls(r.bias)}" style="width:${Math.min(100, r.score * 100).toFixed(0)}%"></i></div><small class="muted">${READ_REG[r.code] || ''}</small></div>`; }).join('')}</div>`);
  }

  // ----- levier et stops des perpétuels -----
  function leverRead(L) {
    const r = L.oi && L.oi.rank30, f = L.funding && L.funding.binance, s = L.longShare;
    if (r == null && f == null) return null;
    let sc = 0;
    if (r != null) sc += r >= 80 ? 1 : r <= 20 ? -1 : 0;
    if (f != null) sc += f >= 0.0003 ? 1 : f < 0 ? -0.5 : 0;
    const lvl = sc >= 1 ? 'élevé' : sc <= -1 ? 'bas' : 'normal';
    const crowd = f != null && f > 0.0001 && (s == null || s > 0.55) ? 'longs' : (f != null && f < 0) || (s != null && s < 0.42) ? 'shorts' : null;
    return {lvl, crowd, cl: lvl === 'élevé' ? 'amb' : lvl === 'bas' ? 'up' : ''};
  }
  const bigStop = (L, side) => ((L.stops && L.stops[side] && L.stops[side].top) || [])[0];
  function leverBanner(L) {
    const R = leverRead(L);
    if (!R) return banner('Levier : pas encore mesuré', 'l\'intérêt ouvert et le financement arrivent avec les premiers relevés (toutes les 5 minutes)');
    const up = bigStop(L, 'shorts'), dn = bigStop(L, 'longs');
    const crowd = R.crowd === 'longs' ? ' · les acheteurs à levier sont nombreux' : R.crowd === 'shorts' ? ' · les vendeurs à levier sont nombreux' : '';
    const risk = R.crowd === 'longs' && dn ? `Risque principal : une purge des longs vers ${px(dn.price)} (${pct(dn.dist)}), où se trouve le plus gros paquet de stops de longs.` :
      R.crowd === 'shorts' && up ? `Risque principal : un rachat forcé des shorts vers ${px(up.price)} (${pct(up.dist)}), où se trouve le plus gros paquet de stops de shorts.` :
      up && dn ? `Plus gros paquets de stops : shorts à ${px(up.price)} (${pct(up.dist)}), longs à ${px(dn.price)} (${pct(dn.dist)}). Le prix est souvent attiré vers le plus gros.` : '';
    return banner(`Levier ${R.lvl}${crowd}`, risk, R.cl);
  }
  function leverTiles(L) {
    const o = L.oi, f = L.funding || {}, s = L.longShare, q = L.liq24, q1 = L.liq1;
    const t1 = o ? tile('Intérêt ouvert', `${nf(o.coins)} ${esc(o.unit)}`, `${usd(o.usd)} · 24 h <span class="${cls(o.chg24h)}">${pct(o.chg24h, 1)}</span> · 7 j <span class="${cls(o.chg7d)}">${pct(o.chg7d, 1)}</span>` +
      (o.rank30 != null ? `<div class="qrank" title="Rang parmi les relevés des 30 derniers jours"><i style="left:${o.rank30}%"></i></div>plus haut que ${o.rank30} % des 30 derniers jours` : `<br>${nf(o.days, 0)} jours d'historique`)) :
      tile('Intérêt ouvert', '—', 'pas encore de relevé');
    const t2 = tile('Financement (Binance)', f.binance == null ? '—' : `${pct(f.binance, 4)}`, f.binance == null ? '' : `par 8 h · ${pct(f.annual, 1)} par an${f.okx != null ? ` · OKX ${pct(f.okx, 4)}` : ''}<br>` +
      (f.binance >= 0.0003 ? 'élevé : les acheteurs à levier paient cher' : f.binance > 0.0001 ? 'positif : les acheteurs paient' : f.binance < 0 ? 'négatif : les vendeurs paient' : 'proche du taux de base'), cls(f.binance));
    const t3 = tile('Comptes longs (Binance)', s == null ? '—' : `${nf(s * 100)} %`, s == null ? 'pas encore lu' : `${split(s, 1 - s, '#22c55e', '#ef4444')}${nf(s * 100)} % des comptes sont acheteurs, ${nf((1 - s) * 100)} % vendeurs`);
    const t4 = q && q.since ? tile('Liquidations · 24 h', usd(q.long + q.short), `${split(q.long, q.short, '#ef4444', '#22c55e')}<span class="dn">longs ${usd(q.long)}</span> · <span class="up">shorts ${usd(q.short)}</span>` +
      (q1 ? `<br>dernière heure : longs ${usd(q1.long)} · shorts ${usd(q1.short)}` : '')) : tile('Liquidations · 24 h', '—', 'notées par le terminal à partir de maintenant');
    const t5 = tile('Intérêt ouvert / volume comptant', L.oiToSpot == null ? '—' : `${nf(L.oiToSpot, 1)} ×`, L.oiToSpot == null ? '' : `pour 1 $ échangé au comptant en 24 h, ${nf(L.oiToSpot, 1)} $ de positions à levier ouvertes`);
    return `<div class="qtiles q5">${t1}${t2}${t3}${t4}${t5}</div>`;
  }
  function stopsCard(L) {
    const S = L.stops, title = 'Stops des perpétuels · où sont les liquidations estimées';
    if (!S) return card(title, bad(L.error || 'indisponible'));
    const lb = S.longs.bands, sb = S.shorts.bands, mx = Math.max(...lb.map(b => b.usd), ...sb.map(b => b.usd)) || 1;
    const rng = b => `${nf(b.from * 100)} à ${nf(b.to * 100)} %`;
    const row = (b, up) => `<span class="ql">${up ? '+' : '−'}${rng(b)}</span><span class="qlb">${hbar(b.usd, mx, up ? '#22c55e' : '#ef4444')}</span><span class="qlv ${b.usd ? (up ? 'up' : 'dn') : 'muted'}">${b.usd ? usd(b.usd) : '—'}</span>`;
    const lad = `<div class="qlad"><span class="qlh up">Stops de shorts au-dessus · achats forcés si le prix monte</span>${sb.slice().reverse().map(b => row(b, true)).join('')}` +
      `<span class="qlp">prix ${px(S.price)}</span>${lb.map(b => row(b, false)).join('')}<span class="qlh dn">Stops de longs en dessous · ventes forcées si le prix baisse</span></div>`;
    const tops = (side, up) => (S[side].top || []).map(p => `<li><b class="${up ? 'up' : 'dn'}">${px(p.price)}</b> <span class="muted">(${pct(p.dist)})</span> · ${usd(p.usd)}${p.born ? ` <span class="muted small">· formé ${ago(data.now - p.born)}</span>` : ''}</li>`).join('') || '<li class="muted">aucun</li>';
    const tot = `${split(S.shorts.usd, S.longs.usd, '#22c55e', '#ef4444')}<p class="small"><span class="up">Stops de shorts : ${usd(S.shorts.usd)}</span> · <span class="dn">stops de longs : ${usd(S.longs.usd)}</span> (à ± ${nf(S.span * 100)} % du prix)</p>`;
    const tiers = `<div class="qtiers">${S.tiers.map(t => `<span><b>${t.lev}x</b> ± ${nf(t.dist * 100, 1)} %</span>`).join('')}</div>`;
    return card(title, tot + `<div class="qstops">${lad}<div><div class="qsub up">Plus gros paquets de stops de shorts</div><ul class="qlist">${tops('shorts', true)}</ul>` +
      `<div class="qsub dn">Plus gros paquets de stops de longs</div><ul class="qlist">${tops('longs', false)}</ul>` +
      `<div class="qsub">Distance de liquidation selon le levier</div>${tiers}<p class="small muted">Une position ouverte à 100x est liquidée après 0,6 % contre elle, à 10x après 9,6 %.</p></div></div>` +
      help(`<p class="small">Estimation, comme les cartes de liquidation des sites spécialisés : chaque hausse de l'intérêt ouvert est comptée comme de nouvelles positions au prix du moment, réparties entre acheteurs et vendeurs selon le volume agressif réel, puis entre les leviers 100x, 50x, 25x et 10x (${S.tiers.map(t => `${t.lev}x ${nf(t.weight * 100)} %`).join(', ')}) ; un niveau disparaît quand le prix le touche, et tout se réduit quand l'intérêt ouvert baisse. Ni les leviers réels ni les prix d'entrée ne sont publics : ce sont des zones probables, pas des ordres visibles.</p>`), '', 'estimation · Binance');
  }

  // ----- DEX et teneurs de marché -----
  function hedgeCard(d) {
    const o = d.options;
    if (!o || o.error) return '';
    const g = o.gex || {}, neg = g.total < 0, a = Math.abs(g.total || 0);
    const txt = neg ? `<p class="qbig">Si le BTC <b class="dn">baisse de 1 %</b>, les teneurs de marché doivent <b class="dn">vendre ≈ ${usd(a)}</b> ; s'il <b class="up">monte de 1 %</b>, <b class="up">acheter ≈ ${usd(a)}</b>.</p><p class="small">Ils suivent le mouvement : <b>les mouvements sont amplifiés</b> (gamma négatif).</p>` :
      `<p class="qbig">Si le BTC <b class="dn">baisse de 1 %</b>, les teneurs de marché doivent <b class="up">acheter ≈ ${usd(a)}</b> ; s'il <b class="up">monte de 1 %</b>, <b class="dn">vendre ≈ ${usd(a)}</b>.</p><p class="small">Ils vont contre le mouvement : <b>les mouvements sont freinés</b> (gamma positif).</p>`;
    const above = o.index != null && g.flip != null ? o.index >= g.flip : null;
    return card('Ce que les teneurs de marché doivent faire', txt +
      `<div class="qkvg"><div><span class="muted">Bascule du gamma</span><b>${px(g.flip)}</b><small class="muted">${above == null ? '' : `prix ${above ? 'au-dessus : calme' : 'en dessous : agité'}`}</small></div>` +
      `<div><span class="muted">Mur de calls</span><b>${px(g.callWall)}</b><small class="muted">résistance des options</small></div>` +
      `<div><span class="muted">Mur de puts</span><b>${px(g.putWall)}</b><small class="muted">support des options</small></div>` +
      `<div><span class="muted">Exposition gamma</span><b class="${cls(g.total)}">${susd(g.total)}</b><small class="muted">à couvrir pour 1 %</small></div></div>` +
      help(`<p class="small">Hypothèse habituelle, non observable : les teneurs de marché ont acheté les calls et vendu les puts du public. Ils se couvrent en achetant ou en vendant du BTC (comptant et perpétuels) quand le prix bouge. Sous la bascule du gamma, leur couverture suit le mouvement et l'amplifie ; au-dessus, elle le freine.</p>`), '', `Deribit · ${ago(d.now - o.t)}`);
  }
  function dexMoves(d) {
    const E = d.optFlow && d.optFlow.expo, h = (E && E.hourly) || [];
    if (!E || h.length < 2) return null;
    const last = h[h.length - 1], at = t => { let best = null; for (const r of h) { if (r[0] <= t) best = r; else break; } return best; };
    const a = at(last[0] - 86400000), b = h[0][0] <= last[0] - 6.5 * 86400000 ? h[0] : null;
    return {d24: a && a !== last ? last[1] - a[1] : null, d7: b ? last[1] - b[1] : null};
  }
  function dexExpiryCard(d) {
    const X = d.options && d.options.dex, rows = (X && X.byExpiry) || [];
    if (!rows.length) return '';
    const show = rows.slice(0, 10), mx = Math.max(...show.map(r => Math.abs(r.dex))) || 1, M = dexMoves(d);
    const mv = M ? `<p class="small">DEX : 24 h <b class="${cls(M.d24)}">${M.d24 == null ? '—' : (M.d24 >= 0 ? '+' : '') + short$(M.d24)}</b> · 7 j <b class="${cls(M.d7)}">${M.d7 == null ? '— (moins de 7 jours d\'historique)' : (M.d7 >= 0 ? '+' : '') + short$(M.d7)}</b></p>` : '';
    return card('DEX par échéance', mv + `<table class="qtab qdexe"><tr><th>Échéance</th><th></th><th>DEX</th><th>calls</th><th>puts</th><th>GEX (1 %)</th><th>Ouvert (BTC)</th></tr>` +
      show.map(r => `<tr><td>${when(r.expiry)}</td><td>${dbar(r.dex, mx)}</td><td class="${cls(r.dex)}"><b>${short$(r.dex)}</b></td><td class="up small">${short$(r.dexCalls)}</td><td class="dn small">${short$(r.dexPuts)}</td>` +
        `<td class="${cls(r.gex)} small">${short$(r.gex)}</td><td class="small">${nf(r.oiCalls)} c / ${nf(r.oiPuts)} p</td></tr>`).join('') + '</table>' +
      help(`<p class="small">DEX de chaque échéance : la position delta de toutes ses options ouvertes (calls positifs, puts négatifs), en dollars. Une échéance au DEX très négatif est un poids vendeur : quand elle expire (vendredi 9 h, heure de Paris), la couverture correspondante se défait, ce qui peut libérer le prix.</p>`), '', 'Deribit');
  }
  function dexStrikeCard(d) {
    const X = d.options && d.options.dex, ks = (X && X.byStrike) || [], idx = d.options && d.options.index;
    if (ks.length < 3) return '';
    const mx = Math.max(...ks.map(k => Math.max(Math.abs(k[1]), Math.abs(k[2])))) || 1;
    let placed = false;
    const rows = ks.slice().reverse().map(k => {
      let mark = '';
      if (!placed && idx != null && k[0] < idx) { placed = true; mark = `<div class="qstk qstkp"><span>prix ${px(idx)}</span></div>`; }
      return mark + `<div class="qstk"><span class="qstkb l">${k[2] ? hbar(k[2], mx, '#ef4444') : ''}</span><b>${nf(k[0])}</b><span class="qstkb">${k[1] ? hbar(k[1], mx, '#22c55e') : ''}</span>` +
        `<small class="muted">${k[2] ? short$(k[2]) : ''}${k[1] && k[2] ? ' / ' : ''}${k[1] ? short$(k[1]) : ''}</small></div>`;
    }).join('');
    return card('DEX par strike autour du prix', `<div class="qstkh small"><span class="dn">◀ puts (delta négatif)</span><span>strike</span><span class="up">calls (delta positif) ▶</span></div><div class="qstks">${rows}</div>` +
      help(`<p class="small">Pour chaque strike proche du prix, le delta en dollars des calls (à droite) et des puts (à gauche) encore ouverts, toutes échéances. Les gros paquets montrent où les teneurs de marché ont le plus à couvrir : le prix est souvent attiré ou freiné près d'eux.</p>`), '', 'Deribit');
  }

  // ----- baleines : qui achète, qui vend, quoi, pour quelle échéance -----
  const FAM = {calls_buy: 'achètent surtout des calls : pari sur la hausse', calls_sell: 'vendent surtout des calls : ne croient pas à une forte hausse, encaissent la prime',
    puts_buy: 'achètent surtout des puts : protection ou pari sur la baisse', puts_sell: 'vendent surtout des puts : prêtes à acheter plus bas, encaissent la prime'};
  function whaleBanner(d) {
    const F = d.optFlow && d.optFlow.whales && d.optFlow.whales.flows, W = d.optFlow && d.optFlow.whales, idx = d.options && d.options.index;
    if (!F || !F.orders) return banner('Baleines : aucun ordre sur 24 heures au-dessus du seuil choisi', W && W.minUsd ? `seuil ${usd(W.minUsd)}` : '');
    const v = F.verdict, dl = v.delta, dir = dl > 0 ? 'orientées à la hausse' : dl < 0 ? 'orientées à la baisse' : 'neutres';
    const S = (W && W.sum) || {}, prem = (S.premiumCalls || 0) + (S.premiumPuts || 0);
    return banner(`Les baleines ${FAM[v.code] || esc(v.label)}`, `Au total ${dir} : delta net ${sn(dl)} BTC${idx ? ` (${susd(dl * idx)})` : ''} · prime nette ${prem >= 0 ? 'payée' : 'reçue'} ${usd(Math.abs(prem))}` +
      ` · volatilité ${S.vega > 0 ? 'achetée' : S.vega < 0 ? 'vendue' : '—'} · ${nf(F.orders)} ordres sur 24 h`, dl > 0 ? 'up' : dl < 0 ? 'dn' : '');
  }
  function flowsCard(d) {
    const F = d.optFlow && d.optFlow.whales && d.optFlow.whales.flows;
    if (!F || !F.orders) return '';
    const q = [['calls', 'buy', 'Calls achetés', 'up', 'pari haussier'], ['calls', 'sell', 'Calls vendus', 'dn', 'plafond, prime encaissée'],
      ['puts', 'buy', 'Puts achetés', 'dn', 'protection, pari baissier'], ['puts', 'sell', 'Puts vendus', 'up', 'soutien, prime encaissée']];
    const mx = Math.max(...q.map(([k, s]) => F[k][s].contracts)) || 1;
    return card('Ce que les baleines ont fait · 24 heures', `<div class="qquad">${q.map(([k, s, lab, c, sub]) => { const x = F[k][s];
      return `<div class="qq qq-${c}"><span class="qkl">${lab}</span><b class="qqn">${nf(x.contracts)} <small>BTC</small></b>${hbar(x.contracts, mx, c === 'up' ? '#22c55e' : '#ef4444')}` +
        `<span class="small">${usd(x.notional)} de notionnel</span><span class="small muted">prime ${s === 'buy' ? 'payée' : 'reçue'} ${usd(x.premium)} · ${nf(x.n)} ordre${x.n > 1 ? 's' : ''}</span><span class="small muted">${sub}</span></div>`; }).join('')}</div>` +
      help(`<p class="small">Toutes les jambes des ordres de baleines des dernières 24 heures, rangées en quatre familles. Le sens est celui de l'initiateur (celui qui traverse le carnet ou demande le bloc négocié). 1 contrat = 1 BTC ; notionnel = contrats × prix du BTC. On ne sait pas si l'ordre ouvre ou ferme une position : la carte « Positions ouvertes » le dit pour la journée.</p>`), '', 'Deribit');
  }
  function expiryCard(d) {
    const o = d.options, F = d.optFlow && d.optFlow.whales && d.optFlow.whales.flows, idx = o && o.index;
    const mp = new Map(((o && !o.error && o.maxPain) || []).map(m => [m.expiry, m])), wh = new Map(((F && F.byExpiry) || []).map(r => [r.expiry, r]));
    const keys = [...new Set([...mp.keys(), ...wh.keys()])].filter(t => t > d.now).sort((a, b) => a - b).slice(0, 12);
    if (!keys.length) return card('Échéances et max pain', bad((o && o.error) || 'chaîne d\'options pas encore lue'));
    const c = (v, cl) => v ? `<td class="${cl}">${nf(v)}</td>` : '<td class="muted">·</td>';
    const body = keys.map(t => { const m = mp.get(t), w = wh.get(t), gap = m && idx ? m.maxPain / idx - 1 : null;
      return `<tr><td>${when(t)}</td>${w ? c(w.callsBuy, 'up') + c(w.callsSell, 'dn') + c(w.putsBuy, 'dn') + c(w.putsSell, 'up') + `<td class="${cls(w.delta)}"><b>${sn(w.delta)}</b></td>` : '<td class="muted" colspan="5">aucune baleine</td>'}` +
        `<td><b>${m ? px(m.maxPain) : '—'}</b></td><td class="${gap == null ? '' : cls(gap)} small">${gap == null ? '' : pct(gap)}</td><td class="small">${m && m.putCall != null ? nf(m.putCall, 2) : '—'}</td></tr>`; }).join('');
    return card('Échéances : baleines et max pain', `<table class="qtab qexp"><tr><th>Échéance</th><th class="up">Calls achetés</th><th class="dn">Calls vendus</th><th class="dn">Puts achetés</th><th class="up">Puts vendus</th><th>Delta net (BTC)</th><th>Max pain</th><th>vs prix</th><th>Put / call</th></tr>${body}</table>` +
      help(`<p class="small">Une ligne par échéance. À gauche, ce que les baleines y ont fait sur 24 heures (contrats, 1 contrat = 1 BTC) et leur delta net : positif = elles gagnent à la hausse. À droite, le max pain de l'échéance (prix où les détenteurs d'options perdraient le plus à l'expiration ; le prix s'en rapproche souvent dans les derniers jours), son écart au prix actuel, et le rapport put / call de l'intérêt ouvert (au-dessus de 1 : plus de puts que de calls ouverts).</p>`), '', 'Deribit');
  }

  // ----- les quatre verdicts du haut -----
  function summary(d) {
    const D = domData(d), L = d.lever || {}, R = leverRead(L), up = bigStop(L, 'shorts'), dn = bigStop(L, 'longs');
    const t1 = D ? sumTile('sp', 'Qui domine · 24 h', `<span class="qsvt"><span style="color:${PERP_C}">Perpétuels ${nf((1 - D.share) * 100)} %</span> · <span style="color:${SPOT_C}">comptant ${nf(D.share * 100)} %</span></span>${split(D.pv, D.sv, PERP_C, SPOT_C)}`,
      `les perpétuels échangent ${nf(D.ratio, 1)} × plus${D.read ? ` · ${esc(CONV[D.read.code] || D.read.label)}` : ''}`, D.read ? VERD(D.read.bias)[0] : '', D.read ? VERD(D.read.bias)[1] : '', D.read ? D.read.bias : 0) :
      sumTile('sp', 'Qui domine · 24 h', '—', 'bougies d\'une heure pas encore lues');
    const f = L.funding && L.funding.binance, o = L.oi;
    const t2 = R ? sumTile('lev', 'Levier', `Levier ${R.lvl}`, [o && o.rank30 != null ? `intérêt ouvert plus haut que ${o.rank30} % des 30 j` : '', f != null ? `financement ${pct(f, 4)}` : '',
      L.longShare != null ? `${nf(L.longShare * 100)} % des comptes longs` : ''].filter(Boolean).join(' · '), R.crowd ? (R.crowd === 'longs' ? 'longs nombreux' : 'shorts nombreux') : '', 'amb', R.lvl === 'élevé' ? 'amb' : 0) :
      sumTile('lev', 'Levier', '—', 'premiers relevés en cours');
    const t3 = up || dn ? sumTile('lev', 'Stops des perpétuels', `${up ? `<span class="up">▲ ${px(up.price)} <small>${pct(up.dist)}</small></span>` : ''}${up && dn ? '<br>' : ''}${dn ? `<span class="dn">▼ ${px(dn.price)} <small>${pct(dn.dist)}</small></span>` : ''}`,
      `plus gros paquets : shorts ${up ? usd(up.usd) : '—'} au-dessus, longs ${dn ? usd(dn.usd) : '—'} en dessous (estimation)`) : sumTile('lev', 'Stops des perpétuels', '—', esc(L.error || 'estimation pas encore prête'));
    const X = d.options && !d.options.error && d.options.dex, F = d.optFlow && d.optFlow.whales && d.optFlow.whales.flows;
    const t4 = sumTile('wh', 'Options BTC', X ? `<span class="${cls(X.total)}">DEX ${short$(X.total)}</span>` : '—',
      (X ? (X.total < 0 ? 'teneurs de marché couverts en vendant' : 'teneurs de marché couverts en achetant') : '') + (F && F.orders ? ` · baleines : ${esc((F.verdict.label || '').toLowerCase())}, delta ${sn(F.verdict.delta)} BTC` : ''),
      F && F.orders ? (F.verdict.delta < 0 ? 'baleines baissières' : F.verdict.delta > 0 ? 'baleines haussières' : '') : '', F && F.orders ? (F.verdict.delta < 0 ? 'dn' : 'up') : '', F && F.orders ? Math.sign(F.verdict.delta) : 0);
    return `<div class="qsum">${t1}${t2}${t3}${t4}</div>`;
  }
  function tabBody(d) {
    const L = d.lever || {}, btc = d.symbol === 'BTCUSDT', ref = btc ? '' : banner('Options BTC : la référence du marché', 'les options de cette paire ne sont pas assez liquides ; le BTC donne le ton', '');
    if (tab === 'sp') return row(domCard(d), whoBuysCard(d)) + row(spotPerpCard(d)) + row(regimeCard(d));
    if (tab === 'lev') return leverBanner(L) + leverTiles(L) + row(stopsCard(L));
    if (tab === 'dex') return ref + dexCard(d) + row(hedgeCard(d), volCard(d)) + row(dexExpiryCard(d)) + row(dexStrikeCard(d));
    if (tab === 'wh') return ref + whaleBanner(d) + row(flowsCard(d)) + row(expiryCard(d)) + row(whalesCard(d)) + row(oiChangeCard(d));
    if (tab === 'flux') return lastSignals(d) + row(cvdCard(d)) + row(signalsCard(d), d.book && !d.book.error ? bookCard(d) : '');
    if (tab === 'net') return d.onchain ? row(chainCard(d)) : banner('Réseau Bitcoin', 'affiché sur la paire BTC');
    return '';
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
    if (tab === 'net' && !data.onchain) tab = 'sp';
    const tabs = `<nav class="qtabs">${TABS.filter(([k]) => k !== 'net' || data.onchain).map(([k, n]) => `<button type="button" data-qtab="${k}" class="${k === tab ? 'on' : ''}">${n}</button>`).join('')}</nav>`;
    g.innerHTML = summary(data) + tabs + `<div class="qpane">${tabBody(data)}</div>`;
    root.querySelectorAll('details.qhelp, details.qmore').forEach(e => { if (open.has(keyOf(e))) e.open = true; });
  }

  function show() { if (on) { load(); return; } on = true; render(); load(); timer = setInterval(load, 5000); }
  function hide() { on = false; if (timer) { clearInterval(timer); timer = null; } }
  return {init, show, hide};
})();
