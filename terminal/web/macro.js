// Macro (V27) : une seule page au lieu de trois (« Macro & annonces », « Macro de la semaine », « Macro du mois »).
// En tête l'essentiel (vent de la semaine, moyen terme, Fed, régime, marchés du moment, sentiment) puis les annonces (à venir et publiées :
// consensus, estimation du terminal, réaction type du bitcoin réunis) ; le détail est rangé par thème dans des sections dépliables.
// Données : /api/analysis (macro du moment, fournie par Analysis), /api/macroweek (semaine choisie), /api/macromonth (mois choisi).
const Macro = (() => {
  'use strict';
  let LT = null, root = null, an = null, wk = null, mo = null, week = null, month = null, timer = null, busy = false, visible = false, openUp = null;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const prose = s => Charts.prose(s);
  const num = (v, d = 1) => v == null || isNaN(v) ? '—' : v.toLocaleString('fr-FR', {minimumFractionDigits: d, maximumFractionDigits: d});
  const sg = (v, d = 1) => v == null || isNaN(v) ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toLocaleString('fr-FR', {minimumFractionDigits: d, maximumFractionDigits: d});
  const paris = (t, o) => new Date(t).toLocaleString('fr-FR', {timeZone: 'Europe/Paris', ...o});
  const day = t => paris(t, {weekday: 'short', day: '2-digit', month: '2-digit'});
  const hm = t => paris(t, {hour: '2-digit', minute: '2-digit'});
  const date = t => paris(t, {day: 'numeric', month: 'long'});
  const dateY = t => paris(t, {day: 'numeric', month: 'long', year: 'numeric'});
  const range = (s, e) => `du ${paris(s, {day: 'numeric', month: 'long'})} au ${paris(e - 86400000, {day: 'numeric', month: 'long', year: 'numeric'})}`;
  const cdown = ms => { const m = Math.round(Math.abs(ms) / 60000); return m >= 1440 ? `${Math.floor(m / 1440)} j ${Math.floor(m % 1440 / 60)} h` : m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}` : `${m} min`; };
  const toneW = s => s == null ? '' : s > 0 ? 'up' : s < 0 ? 'dn' : '';                 // lectures de la semaine : le signe suffit
  const toneM = s => s == null ? '' : s >= 0.4 ? 'up' : s <= -0.4 ? 'dn' : '';          // moyen terme : seuil
  const cap = s => s ? s[0].toUpperCase() + s.slice(1) : '';
  const UNIT = {'%': ' %', point: ' point', pb: ' point de base', 'Md$': ' Md$', milliers: ' milliers', millions: ' millions', million: ' million', '$': ' $', indice: '', points: '', personnes: ''};
  const unit = u => UNIT[u] !== undefined ? UNIT[u] : (u ? ' ' + u : '');
  const QL = {goldilocks: 'Croissance qui tient, inflation qui ralentit', reflation: 'Surchauffe', stagflation: 'Stagflation', slowdown: 'Ralentissement'};
  const QS = {goldilocks: 'Boucles d\'or', reflation: 'Surchauffe', stagflation: 'Stagflation', slowdown: 'Ralentissement'};
  const fedUrl = u => /^https:\/\/www\.federalreserve\.gov\//.test(u || '');
  const webUrl = u => /^https?:\/\/[^\s"'<>]+$/.test(u || '');
  const link = (u, txt, ok = fedUrl) => ok(u) ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(txt)}</a>` : esc(txt);
  const card = (title, body, cls = '') => `<div class="acard ${cls}"><h3>${title}</h3>${body}</div>`;
  const pct = v => v == null ? '<span class="muted">—</span>' : `<span class="${v > 0 ? 'up' : v < 0 ? 'dn' : ''}">${sg(v, 2)} %</span>`;
  const gauge = (v, span = 2, title = '') => v == null ? '' :
    `<div class="mwgauge" title="${esc(title)}"><i style="left:${50 + Math.max(-span, Math.min(span, v)) / span * 50}%"></i><u></u></div>`;

  // sections dépliables : ouvertes ou fermées selon ton dernier choix
  const SECTIONS = [
    ['fed', 'La Fed et les taux', 'chemin attendu par le marché, projections des membres, communiqué annoté, publications'],
    ['regime', 'Croissance, inflation et régime', 'où en est l\'économie, chiffres face au consensus'],
    ['board', 'Tableau de bord de la semaine', 'inflation, emploi, croissance, taux, dollar, liquidité, crédit, énergie'],
    ['markets', 'Marchés, crypto et institutionnels', 'actions, taux, dollar, or, pétrole, fonds indiciels cotés, stablecoins'],
    ['medium', 'Moyen terme et scénarios', 'synthèse du mois, projections Fed / FMI / marché, récession, scénarios'],
    ['claude', 'Recherche de Claude', 'commentaire de la semaine, rapports des grandes banques'],
    ['study', 'Mesures sur l\'historique', 'ce qui a vraiment compté pour le bitcoin'],
  ];
  let opened = new Set();
  try { opened = new Set(JSON.parse(localStorage.getItem('liqMacroOpen') || '[]')); } catch (e) { /* stockage indisponible */ }
  const saveOpen = () => { try { localStorage.setItem('liqMacroOpen', JSON.stringify([...opened])); } catch (e) { /* rien */ } };

  function init(lt, host) {
    LT = lt; root = host;
    root.innerHTML = `<div class="mwbar mxbar"><label class="muted small">Semaine <select id="mxWeek"></select></label><label class="muted small">Mois <select id="mxMonth"></select></label>` +
      `<span id="mxInfo" class="muted small"></span><span class="spacer"></span><button id="mxReload" title="Recalculer avec les dernières données">↻ Actualiser</button></div>` +
      `<div id="mxBody" class="muted">Chargement de la macro…</div>`;
    root.querySelector('#mxWeek').onchange = e => { week = e.target.value; load(); };
    root.querySelector('#mxMonth').onchange = e => { month = e.target.value; load(); };
    root.querySelector('#mxReload').onclick = () => load(true);
    root.addEventListener('click', e => {
      if (e.target.closest('#mwAsk')) askWeek();
      if (e.target.closest('#mmAsk')) askMonth();
      const tr = e.target.closest('tr[data-up]');
      if (tr && !e.target.closest('a')) { openUp = openUp === tr.dataset.up ? null : tr.dataset.up; render(); }
    });
    root.addEventListener('toggle', e => {
      const d = e.target;
      if (!d.dataset || !d.dataset.sec) return;
      d.open ? opened.add(d.dataset.sec) : opened.delete(d.dataset.sec);
      saveOpen();
      if (d.open) draw(d);
    }, true);
  }
  async function loadLists() {
    try {
      const [lw, lm] = await Promise.all([LT.api('/api/macroweeks'), LT.api('/api/macromonths')]);
      if (!week) week = lw.current;
      if (!month) month = lm.current;
      root.querySelector('#mxWeek').innerHTML = lw.weeks.map(w => {
        const s = Date.parse(w.week + 'T00:00:00Z');
        return `<option value="${esc(w.week)}" ${w.week === week ? 'selected' : ''}>${esc(range(s, s + 7 * 86400000))}${w.current ? ' (en cours)' : ''}${w.label ? ' · ' + esc(w.label) : ''}${w.comment ? ' · commentée' : ''}</option>`;
      }).join('');
      root.querySelector('#mxMonth').innerHTML = lm.months.map(m => `<option value="${esc(m.month)}" ${m.month === month ? 'selected' : ''}>${esc(cap(m.label))}${m.current ? ' (en cours)' : ''}` +
        `${m.tone ? ' · ' + esc(m.tone) : ''}${m.banks ? ' · banques' : ''}</option>`).join('');
    } catch (e) { /* listes indisponibles : la semaine et le mois en cours restent lisibles */ }
  }
  async function load(force) {
    if (busy) return;
    busy = true;
    try {
      if (force || !root.querySelector('#mxWeek option')) await loadLists();
      const [w, m] = await Promise.allSettled([LT.api('/api/macroweek' + (week ? '?week=' + week : '')), LT.api('/api/macromonth' + (month ? '?month=' + month : ''))]);
      wk = w.status === 'fulfilled' ? w.value : {error: w.reason && w.reason.message};
      mo = m.status === 'fulfilled' ? m.value : {error: m.reason && m.reason.message};
      render();
    } catch (e) { root.querySelector('#mxBody').innerHTML = `<div class="acard">Macro indisponible : ${esc(e.message)}</div>`; }
    busy = false;
  }
  function show() {
    visible = true;
    load(true);
    clearInterval(timer);
    timer = setInterval(() => { if ((wk && wk.current) || (mo && mo.current)) load(); }, 300000);
  }
  function hide() { visible = false; clearInterval(timer); timer = null; }
  function setAnalysis(a) {                                             // appelé par Analysis à chaque analyse (macro du moment)
    an = a;
    if (visible) render();
  }

  // ---------- 1. l'essentiel ----------
  function riskBanner(m) {
    const r = m && m.risk;
    if (!r || r.level === 'info') return '';
    return `<div class="msg ${r.level === 'danger' ? 'bad' : 'warn'}"><b>${esc(r.label)}</b> ${r.minutes >= 0 ? 'dans' : 'il y a'} <b>${cdown(r.minutes * 60000)}</b> (${esc(day(r.t))} ${esc(hm(r.t))}, heure de Paris). ` +
      `${r.level === 'danger' ? 'Fenêtre de danger : écarts de prix élargis, mèches rapides, stops balayés. Réduis le levier ou reste à plat.' : 'Volatilité attendue dans les prochaines heures : évite les entrées de faible conviction juste avant.'}</div>`;
  }
  const tile = (k, v, cls, sub) => `<div class="mxtile ${cls || ''}"><div class="k">${k}</div><div class="v">${v}</div>${sub ? `<div class="s">${sub}</div>` : ''}</div>`;
  function fedLine(f) {
    const c = f.cuts, a = c == null ? null : Math.round(Math.abs(c) * 10) / 10;
    if (a == null) return null;
    return a < 0.4 ? 'pas de changement net' : `≈ ${num(a, 1)} ${c > 0 ? 'baisse' : 'hausse'}${a >= 2 ? 's' : ''} de 0,25 point`;
  }
  function essentials() {
    const v = wk && wk.view, m = an && an.macro, f = (mo && mo.fed) || (v && v.fed) || {}, mt = (mo && mo.medium) || {}, reg = (v && v.regime) || (mo && mo.regime) || {};
    const tiles = [];
    if (v && v.label) tiles.push(tile('Vent de la semaine', esc(cap(v.label)), toneW(v.score),
      gauge(v.score, 2.5, 'somme des composantes : régime, surprises, Fed, annonces') +
      `<ul class="mxparts">${(v.parts || []).map(p => `<li class="${p.score > 0.1 ? 'up' : p.score < -0.1 ? 'dn' : ''}">${p.score > 0.1 ? '▲' : p.score < -0.1 ? '▼' : '•'} ${esc(p.name)}</li>`).join('')}</ul>`));
    if (mt.label) tiles.push(tile('Moyen terme <small>3 à 12 mois</small>', esc(cap(mt.label)), toneM(mt.score), 'pour les actifs à risque'));
    const fl = fedLine(f), n = f.next;
    if (fl || n) tiles.push(tile('Fed <small>attendu d\'ici un an</small>', esc(fl || '—'), '',
      (f.cutsChange != null && Math.abs(f.cutsChange) >= 0.1 ? `<span class="${f.cutsChange > 0 ? 'up' : 'dn'}">${sg(f.cutsChange, 1)}</span> ${esc((f.changeLabel || 'sur la semaine').toLowerCase())}<br>` : '') +
      (n ? `Prochaine décision : <b>${esc(date(n.decision))}</b> (${n.days < 1 ? 'aujourd\'hui ou demain' : `dans ${n.days} jour${n.days > 1 ? 's' : ''}`})` : '')));
    if (reg.label) tiles.push(tile('Régime <small>croissance et inflation</small>', esc(reg.label), '', ''));
    if (m && m.label) tiles.push(tile('Marchés en ce moment', esc(m.label), m.score > 25 ? 'up' : m.score < -25 ? 'dn' : '',
      `score ${sg(m.score, 0)} sur ±100 · actifs de référence, réaction aux annonces, sentiment`));
    if (m && m.fng) tiles.push(tile('Fear &amp; Greed', `${m.fng.value} <small>${esc(m.fng.label)}</small>`, '', m.fng.d7 != null ? `${sg(m.fng.d7, 0)} en 7 jours` : ''));
    // la conclusion d'abord, puis le reste de la vision de la semaine (sans la liste des publications de la Fed : elle est dans « La Fed et les taux »)
    const ls = ((v && v.lines) || []).filter(l => !/^Ce que la Fed a publié/.test(l.title));
    const concl = ls.filter(l => /^Ce que cela veut dire/.test(l.title)), rest = ls.filter(l => !/^Ce que cela veut dire/.test(l.title));
    const para = l => `<p><b>${esc(l.title)}.</b> ${esc(l.text)}</p>`;
    const lines = (concl.length ? `<div class="mxconcl">${concl.map(para).join('')}</div>` : '') +
      (rest.length ? `<details class="mxmore"${opened.has('vision') ? ' open' : ''} data-sec="vision"><summary>Le raisonnement complet de la semaine (${rest.map(l => { const t = l.title.replace(/\s*\(.*\)$/, ''); return esc(t[0].toLowerCase() + t.slice(1)); }).join(', ')})</summary><div class="mxlines">${rest.map(para).join('')}</div></details>` : '');
    return `<section class="mxsec mxess"><h2>L'essentiel <small>${wk && wk.start ? 'semaine ' + esc(range(wk.start, wk.end)) : ''}${mo && mo.label ? ' · ' + esc(mo.label) : ''}</small></h2>` +
      riskBanner(m) + (tiles.length ? `<div class="mxtiles">${tiles.join('')}</div>` : '<div class="muted">Données macro en cours de chargement…</div>') +
      (lines ? `${lines}<div class="note">Lectures classiques reliées aux chiffres, pas des prévisions : la macro donne le décor, le flux et la liquidité du marché crypto décident du moment.</div>` : '') + '</section>';
  }

  // ---------- 2. annonces : à venir et publiées ----------
  function upcoming() {
    const v = wk && wk.view, m = an && an.macro, byId = {};
    ((m && m.upcoming) || []).forEach(e => { byId[e.id] = {m: e}; });
    ((v && wk.current && v.upcoming) || []).forEach(e => { (byId[e.id] = byId[e.id] || {}).v = e; });
    const rows = Object.values(byId).map(x => ({...(x.m || {}), ...(x.v || {}), _m: x.m, _v: x.v})).sort((a, b) => a.t - b.t);
    if (!rows.length) return '<div class="muted small">Aucune annonce importante dans les 7 prochains jours (ou calendrier indisponible).</div>';
    const key = (v && v.key) || [];
    const now = an ? an.t : Date.now();
    return `<div class="mwscroll"><table class="t mwtable"><tr><th>Quand <span class="muted small">(Paris)</span></th><th>Annonce</th><th class="r">Consensus</th><th class="r">Précédent</th>` +
      `<th class="r">Estimation du terminal</th><th>Penchant</th><th class="r">Bitcoin en 1 h, d'habitude</th></tr>` + rows.map(e => {
        const ln = e.lean ? `<span class="${e.cat === 'inflation' ? (e.lean > 0 ? 'dn' : 'up') : 'amb'}" title="${esc(e.leanText)}">${e.lean > 0 ? '▲ au-dessus' : '▼ en dessous'}</span>` :
          (e.estimateText ? '<span class="muted small">pas de signal</span>' : '');
        const t = e._m && e._m.typical, ex = (e._m && e._m.exp) || {}, open = openUp === e.id;
        const imp = e.impact === 3 ? ' <span class="amb small" title="impact élevé">★★★</span>' : '';
        return `<tr data-up="${esc(e.id)}" class="${key.includes(e.id) || e.impact === 3 ? 'hl' : ''}" style="cursor:pointer"><td class="nowrap">${esc(day(e.t))} ${esc(hm(e.t))}<div class="muted small">dans ${cdown(e.t - now)}</div></td>` +
          `<td><b>${esc(e.label)}</b> <span class="pill">${esc(e.country)}</span>${imp}</td><td class="r">${esc(e.forecast || '—')}</td><td class="r">${esc(e.previous || '—')}</td>` +
          `<td class="r">${e.estimateText ? `<b>${esc(e.estimateText)}</b><div class="muted small">${esc(e.errorText)}</div>` : '<span class="muted small">—</span>'}</td><td>${ln}</td>` +
          `<td class="r">${t && t.abs60 != null ? `±${num(t.abs60, 2)} % <span class="muted small">(${t.n} fois)</span>` : '<span class="muted small">pas encore mesuré</span>'}</td></tr>` +
          (open ? `<tr><td></td><td colspan="6" class="small">${ex.text ? `<div><b>Ce que dit le consensus</b> : ${prose(ex.text)}</div>` : ''}` +
            (e.how ? `<div><b>Estimation du terminal</b> : ${esc(e.how)}${e.errorText ? ` ; erreur habituelle de cette méthode sur 5 ans : ${esc(e.errorText)}` : ''}.</div>` : '') +
            (e.leanText ? `<div>${esc(e.leanText)}</div>` : '') +
            `<div class="muted">${esc(e.scenUp || ex.scen_up || '')}<br>${esc(e.scenDn || ex.scen_dn || '')}</div></td></tr>` : '');
      }).join('') + '</table></div>' +
      '<div class="note">Clique une ligne pour les scénarios. Estimation du terminal = tendance des derniers mois (inflation : tendance sous-jacente, alimentation, essence ; croissance : GDPNow de la Fed d\'Atlanta) avec son erreur habituelle ; un « penchant » n\'apparaît que si l\'écart au consensus dépasse la moitié de cette erreur. « Bitcoin en 1 h, d\'habitude » : mouvement moyen mesuré après les annonces du même type.</div>';
  }
  function published() {
    const m = an && an.macro, react = {};
    ((m && m.past) || []).forEach(e => { react[e.id] = e.reaction; });
    let evs = ((wk && wk.events) || []).filter(e => e.past).slice().reverse();
    if (!wk || !wk.events) evs = ((m && m.past) || []).map(e => ({...e, past: true}));
    if (!evs.length) return '<div class="muted small">Aucune annonce importante publiée pour l\'instant cette semaine.</div>';
    return `<div class="mwscroll"><table class="t mwtable"><tr><th>Quand <span class="muted small">(Paris)</span></th><th>Annonce</th><th class="r">Consensus</th><th class="r">Publié</th><th class="r">Écart</th>` +
      `<th>Ce que cela veut dire</th><th class="r">Bitcoin 1 h après</th></tr>` + evs.map(e => {
        const r = react[e.id] || e.reaction || {}, b = r.btc || {};
        const pub = e.actual ? `<b>${esc(e.actual.text)}</b>${e.actual.period ? `<div class="muted small">${esc(e.actual.period)}</div>` : ''}` :
          '<span class="muted small" title="Le flux gratuit ne donne pas le chiffre publié ; FRED ne couvre que les grandes statistiques américaines, parfois avec quelques heures de retard.">non fourni</span>';
        const surp = e.surprise == null ? '' : `<span class="${e.cat === 'inflation' ? (e.surprise > 0 ? 'dn' : e.surprise < 0 ? 'up' : '') : ''}" title="chiffre publié moins consensus">${esc(e.surpriseText || sg(e.surprise, 2))}</span>`;
        const imp = r.impulseLabel && !/inconnu/.test(r.impulseLabel) ? `<div class="muted small">Réaction des taux et du dollar : ${prose(r.impulseLabel)}</div>` : '';
        const read = (e.read ? esc(e.read) : '') + (imp || (e.reactionText ? `<div class="muted small">${esc(e.reactionText)}</div>` : ''));
        return `<tr><td class="nowrap">${esc(day(e.t))} ${esc(hm(e.t))}</td><td><b>${esc(e.label)}</b> <span class="pill">${esc(e.country)}</span>${e.impact === 3 ? ' <span class="amb small">★★★</span>' : ''}</td>` +
          `<td class="r">${esc(e.forecast || '—')}</td><td class="r">${pub}</td><td class="r">${surp}</td><td class="mwread">${read}</td><td class="r">${b.r60 != null ? pct(b.r60) : '<span class="muted small">—</span>'}</td></tr>`;
      }).join('') + '</table></div>' +
      '<div class="note">Chiffre publié recalculé à partir de la base officielle FRED pour les grandes statistiques américaines. Quand il manque, la surprise est lue dans la réaction des taux et du dollar dans les 15 minutes.</div>';
  }
  function nextWeek() {
    const n = (wk && !wk.current && wk.next) || [];
    if (!n.length) return '';
    return `<div class="sect">Semaine suivante : à surveiller</div><ul class="mwnext">` + n.map(e => `<li><b>${esc(day(e.t))} ${esc(hm(e.t))}</b> — ${esc(e.label)} <span class="pill">${esc(e.country)}</span>` +
      (e.forecast ? ` <span class="muted">consensus ${esc(e.forecast)}, précédent ${esc(e.previous || '—')}</span>` : '') + '</li>').join('') + '</ul>';
  }
  function announcements() {
    const cur = !wk || wk.current;
    return `<section class="mxsec"><h2>Annonces <small>${cur ? 'les 7 prochains jours et celles de la semaine' : 'semaine archivée'}</small></h2>` +
      (cur && an && an.macro ? '<div id="mxTl"></div><div class="note">Orange = à venir, gris = passé ; gros points = impact élevé.</div>' : '') +
      (cur ? `<div class="sect">À venir</div>${upcoming()}` : '') + `<div class="sect">Publiées${cur ? ' cette semaine' : ''}</div>${published()}${nextWeek()}</section>`;
  }

  // ---------- 3. la Fed et les taux ----------
  function fedCard() {
    const f = (mo && mo.fed) || (wk && wk.view && wk.view.fed) || {}, fl = fedLine(f), n = f.next;
    return card('Ce que le marché attend de la Fed', (fl ? `<div class="mwbig">${esc(fl)}</div><div class="muted small">attendu par le marché d'ici un an environ` +
        (f.cutsChange != null && Math.abs(f.cutsChange) >= 0.1 ? ` · <span class="${f.cutsChange > 0 ? 'up' : 'dn'}">${sg(f.cutsChange, 1)}</span> ${esc((f.changeLabel || '').toLowerCase())}` : '') + '</div>' : '') +
      (n ? `<div class="small" style="margin:4px 0">Prochaine décision : <b>${esc(dateY(n.decision))}</b> (${n.days < 1 ? 'aujourd\'hui ou demain' : `dans ${n.days} jour${n.days > 1 ? 's' : ''}`})${n.sep ? ', avec de nouvelles projections des membres' : ''}.</div>` : '') +
      '<div id="mxPath" class="mwpath"></div>' + (f.text || []).map(x => `<p class="small">${esc(x)}</p>`).join('') +
      `<div class="note">Chemin du marché déduit des taux d'État à 3 mois, 6 mois, 1 an et 2 ans (approximation : la référence, les contrats à terme sur le taux de la Fed, n'est pas en accès libre). Points orange : projections des membres de la Fed${f.sepDate ? ' publiées le ' + esc(dateY(f.sepDate)) : ''}.</div>`);
  }
  function sepCard() {
    const s = (mo && mo.sep) || {};
    if (!(s.rows || []).length) return card('Projections des membres de la Fed', '<div class="muted">Pas encore de projections (base FRED injoignable ?).</div>');
    const ys = s.years || [];
    const rows = s.rows.map(x => `<tr><td>${esc(x.name)}</td>${ys.map(y => `<td class="r">${x.values[y] == null ? '—' : num(x.values[y], x.sid === 'FEDTARMD' ? 2 : 1) + ' %'}</td>`).join('')}` +
      `<td class="r">${x.sid === 'FEDTARMD' && s.longRun != null ? num(s.longRun, 2) + ' %' : ''}</td></tr>`).join('');
    const rng = ys.filter(y => s.rangeLow && s.rangeLow[y] != null).map(y => `fin ${y} : de ${num(s.rangeLow[y], 2)} à ${num(s.rangeHigh[y], 2)} %`).join(' ; ');
    return card(`Projections des membres de la Fed <small class="muted">médianes${s.date ? ', réunion du ' + esc(dateY(s.date)) : ''}</small>`,
      `<div class="mwscroll"><table class="t mmsep"><tr><th></th>${ys.map(y => `<th class="r">${esc(y)}</th>`).join('')}<th class="r">Long terme</th></tr>${rows}</table></div>` +
      (rng ? `<div class="small" style="margin-top:6px">Désaccord sur le taux directeur (du membre le plus bas au plus haut) : ${esc(rng)}.</div>` : '') +
      (s.stale ? '<div class="note amb">Ces projections ont plus de 4 mois : de nouvelles arrivent à la prochaine réunion avec projections.</div>' : '') +
      '<div class="note">Inflation et croissance : de la fin d\'année à la fin d\'année. Long terme : le taux « neutre » vu par la Fed (ni frein ni soutien).</div>');
  }
  const diffHtml = ch => ch.map(([st, txt]) => st === '-' ? `<del>${esc(txt)}</del>` : st === '+' ? `<ins>${esc(txt)}</ins>` : esc(txt)).join(' ');
  function statementCard() {
    const s = (mo && mo.statement) || {};
    if (!s.t) return card('Communiqué de la Fed', '<div class="muted">Communiqué pas encore lu (site de la Fed injoignable ?).</div>', 'wide');
    const d = s.diff, dec = s.decision || {}, t = s.tone || {};
    const MOVE = {baisse: 'Baisse du taux', hausse: 'Hausse du taux', maintien: 'Taux inchangé'};
    let body = `<div class="small">${link(s.link, 'Communiqué du ' + dateY(s.t))}${s.inMonth ? '' : ' <span class="muted">(dernier connu, avant ce mois)</span>'} : ` +
      `<b>${esc(MOVE[dec.move] || 'décision non lue')}</b>${dec.range ? ` (fourchette « ${esc(dec.range)} percent »)` : ''} · ton <b>${esc(t.label || '—')}</b>` +
      (s.prev ? ` <span class="muted">(précédent, ${esc(dateY(s.prev.t))} : ${esc((s.prev.tone || {}).label || '—')})</span>` : '') + '</div>';
    if (s.toneText) body += `<p class="small">${esc(s.toneText)}</p>`;
    if (d) {
      const items = (d.changed || []).map(ch => `<li>${diffHtml(ch)}</li>`).concat((d.added || []).map(x => `<li><ins>${esc(x)}</ins></li>`), (d.removed || []).map(x => `<li><del>${esc(x)}</del></li>`));
      body += `<div class="sect">Ce qui a changé face au communiqué précédent <span class="muted small">(${d.same} phrase${d.same > 1 ? 's' : ''} inchangée${d.same > 1 ? 's' : ''})</span></div>` +
        (items.length ? `<ul class="mmdiff">${items.join('')}</ul>` : '<div class="muted small">Aucun changement de texte.</div>');
    }
    if ((s.dissents || []).length) body += `<div class="sect">Votes contre la décision</div><ul class="mwnext">${s.dissents.map(x => `<li class="small">${esc(x)}</li>`).join('')}</ul>`;
    if ((t.hawk || []).length || (t.dove || []).length) body += `<div class="note">Ton compté sur des formules typiques : accommodantes (${(t.dove || []).map(esc).join(', ') || 'aucune'}) ; restrictives (${(t.hawk || []).map(esc).join(', ') || 'aucune'}). ` +
      'Indication grossière : le texte change peu d\'une réunion à l\'autre, ce sont les mots ajoutés ou retirés qui comptent.</div>';
    return card('Communiqué de la Fed : ce qui a changé <small class="muted">texte d\'origine en anglais ; <ins>ajouté</ins> / <del>retiré</del></small>', body, 'wide');
  }
  function commsCard() {
    const c = (mo && mo.comms && mo.comms.length ? mo.comms : (wk && wk.view && wk.view.comms)) || [];
    if (!c.length) return '';
    return card('Publications de la Fed ce mois-ci', `<ul class="mwnext">` +
      c.slice(0, 25).map(x => `<li><b>${esc(day(x.t))}</b> — <span class="pill">${esc(x.kindLabel)}</span> ${link(x.link, x.title)}${x.speaker ? ` <span class="muted small">(${esc(x.speaker)})</span>` : ''}</li>`).join('') +
      '</ul><div class="note">Flux publics du site de la Fed (communiqués, comptes rendus, discours), en anglais. La recherche de Claude peut les résumer.</div>');
  }
  const secFed = () => `<div class="mwgrid">${fedCard()}${sepCard()}</div>${statementCard()}<div class="mwgrid" style="margin-top:10px">${commsCard()}</div>`;

  // ---------- 4. croissance, inflation et régime ----------
  function regimeCard() {
    const r = (wk && wk.view && wk.view.regime) || (mo && mo.regime) || {};
    const comp = (list, title) => list.length ? `<div class="sect">${title}</div><table class="t">` + list.map(c =>
      `<tr><td>${esc(c.name)}<div class="muted small">${esc(c.text)}</div></td><td style="width:32%" title="${sg(c.score, 2)} (de −2 à +2)">${Charts.dvBar(c.score, 2, '#9aa0ae', '#9aa0ae')}</td></tr>`).join('') + '</table>' : '';
    return card('Régime : croissance et inflation <small class="muted">élan sur 3 mois face à un an, trajet sur 12 mois</small>',
      (r.label ? `<div class="mwregime">${esc(r.label)}</div><div class="muted small">${esc(r.text || '')}</div>` : '<div class="muted">Pas assez de chiffres officiels pour situer le régime.</div>') +
      '<div id="mxQuad" class="mwq"></div>' + comp(r.growth || [], 'Croissance') + comp(r.inflation || [], 'Inflation'));
  }
  function surpCard() {
    const s = (wk && wk.view && wk.view.surprises) || {};
    const one = (x, name, inflation) => !x ? '' : `<div class="mwsurp"><div><b>${name}</b> : <span class="${inflation && x.value != null ? (x.value >= 0.15 ? 'dn' : x.value <= -0.15 ? 'up' : '') : ''}">${esc(x.label)}</span></div>` +
      (x.value != null ? gauge(x.value, 2, 'moyenne des écarts au consensus, en écarts habituels (de −2 à +2)') : '') +
      `<div class="muted small">${x.n} chiffre${x.n > 1 ? 's' : ''} : ${x.above} au-dessus, ${x.below} en dessous, ${x.inline} conforme${x.inline > 1 ? 's' : ''}</div></div>`;
    const rows = (s.rows || []).slice(0, 10).map(r => `<tr><td class="nowrap">${esc(day(r.t))}</td><td>${esc(r.label)}</td><td class="r">${esc(r.actual)}</td><td class="r muted">${esc(r.forecast || '—')}</td>` +
      `<td style="width:26%" title="${sg(r.z, 1)} écart habituel">${Charts.dvBar(r.z, 3, r.grp === 'inflation' ? '#ff6b6b' : '#9aa0ae', r.grp === 'inflation' ? '#3ddc97' : '#9aa0ae')}</td></tr>`).join('');
    return card(`Les chiffres face au consensus <small class="muted">${s.days || 56} derniers jours</small>`,
      one(s.activity, 'Activité et emploi', false) + one(s.inflation, 'Inflation', true) +
      (rows ? `<div class="mwscroll"><table class="t"><tr><th>Quand</th><th>Chiffre</th><th class="r">Publié</th><th class="r">Consensus</th><th>Écart</th></tr>${rows}</table></div>` :
        '<div class="muted small">Aucun chiffre publié retrouvé sur la période (le calendrier se remplit depuis l\'installation du terminal ; FRED couvre les grandes statistiques américaines).</div>') +
      '<div class="note">Écart = (publié − consensus) rapporté à l\'écart habituel de ce chiffre ; chômage et inscriptions au chômage comptés à l\'envers (plus haut = activité plus faible). Les plus récents pèsent davantage.</div>');
  }
  const secRegime = () => `<div class="mwgrid">${regimeCard()}${surpCard()}</div>`;

  // ---------- 5. tableau de bord de la semaine ----------
  function verdictCard() {
    const v = (wk && wk.verdict) || {}, sc = v.score;
    const parts = (v.parts || []).map(p => `<span class="pill ${toneW(p.score)}" title="${esc(p.read)}">${esc(p.title)} ${p.score > 0 ? '▲' : p.score < 0 ? '▼' : '•'}</span>`).join(' ');
    return `<div class="acard mwhero"><h3>Ce que cela engendre <small class="muted">lecture par thème selon des règles classiques, non validée par l'historique (voir « Mesures sur l'historique »)</small></h3>` +
      (v.label ? `<div class="mwvent ${toneW(sc)}">Vent macro ${esc(v.label)}</div>${sc == null ? '' : `<div class="mwgauge" title="somme des lectures par thème (de −7 à +7)"><i style="left:${50 + Math.max(-7, Math.min(7, sc)) / 7 * 50}%"></i><u></u></div>`}` :
        '<div class="muted">Pas assez de données officielles pour une lecture (FRED injoignable ?).</div>') +
      `<div class="mwparts">${parts}</div>${(v.lines || []).map(l => `<p>${esc(l)}</p>`).join('')}</div>`;
  }
  function themeCard(th) {
    if (!th.items.length) return '';
    const rows = th.items.map(it => `<tr><td>${esc(it.name)}${it.note ? `<div class="muted small">${esc(it.note)}</div>` : ''}</td>` +
      `<td class="r nowrap"><b>${num(it.value, it.d)}</b>${esc(unit(it.unit))}</td>` +
      `<td class="r nowrap small">${it.change == null ? '' : `${sg(it.change, it.cd)}${esc(unit(it.changeUnit))}<div class="muted">${esc(it.changeLabel || '')}</div>`}</td></tr>`).join('');
    return `<div class="acard"><h3>${esc(th.title)}${th.score != null ? ` <span class="pill ${toneW(th.score)}">${th.score > 0 ? 'favorable' : th.score < 0 ? 'défavorable' : 'neutre'}</span>` : ''}</h3>` +
      (th.read ? `<p class="mwthread ${toneW(th.score)}">${esc(th.read)}</p>` : '') + `<table class="t">${rows}</table></div>`;
  }
  const secBoard = () => verdictCard() + `<div class="mwgrid" style="margin-top:10px">${((wk && wk.themes) || []).map(themeCard).join('')}</div>`;

  // ---------- 6. marchés, crypto et institutionnels ----------
  function marketsCard(list, title, sub) {
    const m = list || [];
    if (!m.length) return '';
    const mx = Math.max(1, ...m.filter(x => x.unit === '%').map(x => Math.abs(x.chg || 0)));
    const rows = m.map(x => {
      const pb = x.unit === 'pb', w = pb ? 0 : Math.min(100, Math.abs(x.chg || 0) / mx * 100);
      return `<tr><td>${esc(x.name)}</td><td class="r nowrap ${pb ? '' : (x.chg > 0 ? 'up' : x.chg < 0 ? 'dn' : '')}">${pb ? sg(x.chg, 0) + ' pb' : sg(x.chg, 1) + ' %'}</td>` +
        `<td class="mwbarcell">${pb ? '' : `<i class="${x.chg >= 0 ? 'pos' : 'neg'}" style="width:${w / 2}%"></i>`}</td></tr>`;
    }).join('');
    return card(`${title} <small class="muted">${sub}</small>`, `<table class="t">${rows}</table><div class="note">pb = point de base (0,01 point de taux).</div>`);
  }
  function cryptoCard() {
    const c = (wk && wk.crypto) || {};
    if (!(c.rows || []).length && !c.rotation) return '';
    const rows = (c.rows || []).map(x => `<tr><td>${esc(x.name)}</td><td class="r nowrap"><b>${num(x.value, x.d)}</b>${esc(unit(x.unit))}</td>` +
      `<td class="r nowrap small">${x.change == null ? '' : sg(x.change, x.changeUnit === '%' ? 1 : x.d || 1) + ' ' + esc(x.changeUnit)}</td></tr>`).join('');
    return card('Crypto et institutionnels <small class="muted">variation sur la semaine</small>', `<table class="t">${rows}</table>` + (c.rotation ? `<p class="small">Où va l'argent : ${esc(c.rotation)}</p>` : ''));
  }
  function nowCard() {
    const m = an && an.macro;
    if (!m) return '';
    return card('Lecture des marchés en ce moment <small class="muted">écrite à partir des chiffres mesurés</small>', (m.lines || []).map(l => `<div class="msg ${l.tone === 'muted' ? '' : l.tone}">${prose(l.text)}</div>`).join('') +
      (m.score != null ? Charts.meter(m.score) + '<table class="t">' + (m.components || []).map(c => `<tr><td>${esc(c.label)}</td><td style="width:40%">${Charts.dvBar(c.score)}</td><td class="r ${c.score > 0.1 ? 'up' : c.score < -0.1 ? 'dn' : ''}">${sg(c.score * 100, 0)}</td></tr>`).join('') + '</table>' : ''));
  }
  function refCard() {
    const tr = Object.entries((an && an.macro && an.macro.trends) || {});
    if (!tr.length) return '';
    return card('Actifs de référence <small class="muted">5 jours · lien mesuré avec le bitcoin sur 90 jours et 1 an</small>', '<div class="spark">' + tr.map(([, t]) => {
      const eff = (t.corr != null ? t.corr : 0) * (t.z || 0), col = Math.abs(t.z || 0) < 1 ? '#6a6e7a' : eff >= 0 ? '#3ddc97' : '#ff6b6b';
      return `<div class="sp"><div class="l">${esc(t.label)}</div><b>${LT.fmtP(t.last)}</b> <span class="${t.c5d > 0 ? 'up' : 'dn'}">${sg(t.c5d, t.unit === 'pb' ? 1 : 2)} ${t.unit === 'pb' ? 'pb' : '%'}</span>${Charts.spark(t.spark, col, 170, 34)}` +
        `<div class="l">corrélation avec le bitcoin : 90 j ${t.corr != null ? sg(t.corr, 2) : 'n/d'} · 1 an ${t.corr365 != null ? sg(t.corr365, 2) : 'n/d'}</div></div>`;
    }).join('') + '</div><div class="note">Trait gris = mouvement banal ; vert / rouge = mouvement inhabituel plutôt favorable / défavorable au bitcoin compte tenu de sa corrélation récente. Données Yahoo Finance (contrats à terme, presque 24 h sur 24).</div>', 'wide');
  }
  const secMarkets = () => `<div class="mwgrid">${nowCard()}${marketsCard(wk && wk.markets, 'Marchés sur la semaine', 'depuis la clôture de vendredi dernier')}${cryptoCard()}` +
    `${marketsCard(mo && mo.markets, 'Marchés sur le mois', 'depuis le début du mois')}</div>${refCard()}`;

  // ---------- 7. moyen terme et scénarios ----------
  function monthHero() {
    const mt = (mo && mo.medium) || {};
    if (!(mo && (mo.lines || []).length) && !mt.label) return '';
    return `<div class="acard mwhero mwview"><h3>Synthèse du mois <small class="muted">${mo && mo.label ? esc(mo.label) + ' · ' : ''}chaque phrase vient d'un chiffre</small></h3>` +
      (mt.label ? `<div class="mwvent ${toneM(mt.score)}">Moyen terme ${esc(mt.label)} pour les actifs à risque</div>` : '') +
      ((mo && mo.lines) || []).map(l => `<p><b>${esc(l.title)}.</b> ${esc(l.text)}</p>`).join('') + '</div>';
  }
  function mediumCard() {
    const mt = (mo && mo.medium) || {}, groups = {};
    (mt.items || []).forEach(it => (groups[it.group] = groups[it.group] || []).push(it));
    const tables = Object.entries(groups).map(([g, items]) => `<div class="sect">${esc(g)}</div><table class="t">` + items.map(it =>
      `<tr><td>${esc(it.name)}${it.note ? `<div class="muted small">${esc(it.note)}</div>` : ''}</td><td class="r nowrap"><b>${num(it.value, it.d)}</b>${esc(unit(it.unit))}</td>` +
      `<td class="r nowrap small">${it.change == null ? '' : `${sg(it.change, it.cd != null ? it.cd : it.changeUnit === 'pb' || it.changeUnit === 'Md$' ? 0 : it.changeUnit === '%' ? 1 : 2)}${esc(unit(it.changeUnit))}<div class="muted">${esc(it.changeLabel || '')}</div>`}</td></tr>`).join('') + '</table>').join('');
    if (!tables && !(mt.lines || []).length) return '';
    return card('Vision à moyen terme <small class="muted">3 à 12 mois</small>', (mt.lines || []).map(l => `<p class="small">${esc(l)}</p>`).join('') + '<div id="mxRec" class="mwpath"></div>' + tables);
  }
  function consensusCard() {
    const rows = (mo && mo.consensus) || [];
    if (!rows.length) return '';
    const p = (v, d = 1) => v == null ? null : num(v, d) + ' %';
    const join = (...xs) => xs.filter(Boolean).join(' · ') || '<span class="muted">—</span>';
    const notes = [];
    const note = n => { if (!n) return ''; let k = notes.indexOf(n); if (k < 0) { notes.push(n); k = notes.length - 1; } return `<sup>${k + 1}</sup>`; };
    const body = rows.map(x => { const c = x.cols, d = /^Taux/.test(x.name) ? 2 : 1;
      return `<tr><td>${esc(x.name)}${note(x.note)}</td><td class="r">${join(p(c.fed, d), c.fed2 != null ? 'totale ' + p(c.fed2) : null)}</td>` +
        `<td class="r">${join(p(c.imf), c.imf2 != null ? 'puis ' + p(c.imf2) : null)}</td><td class="r">${join(p(c.market, 2))}</td>` +
        `<td class="r">${join(c.households != null ? 'ménages ' + p(c.households) : null, c.model != null ? 'Cleveland ' + p(c.model, 2) : null)}</td>` +
        `<td class="r">${join(p(c.last, d), c.now != null ? 'GDPNow ' + p(c.now) : null)}</td></tr>`; }).join('');
    return card(`Projections à prendre en compte <small class="muted">Fed, Fonds monétaire international (FMI), marché, ménages${mo.imfUpdated ? ' ; FMI lu le ' + esc(dateY(mo.imfUpdated)) : ''}</small>`,
      `<div class="mwscroll"><table class="t mwtable mmcons"><tr><th></th><th class="r">Fed (médiane des membres)</th><th class="r">FMI</th><th class="r">Marché</th>` +
      `<th class="r">Attentes à un an</th><th class="r">Dernier chiffre</th></tr>${body}</table></div><ol class="mmfoot">${notes.map(n => `<li>${esc(n)}</li>`).join('')}</ol>` +
      '<div class="note">Les mesures diffèrent d\'une source à l\'autre (notes ci-dessus) : compare les sens et les écarts plutôt que les décimales.</div>', 'wide');
  }
  function scenariosCard() {
    const sc = (mo && mo.scenarios) || [];
    if (!sc.length) return '';
    return card('Scénarios et déclencheurs <small class="muted">ce qui ferait basculer d\'un scénario à l\'autre, et quand le vérifier</small>', '<div class="mmscen">' +
      sc.map(s => `<div class="mmsc ${s.effect > 0 ? 'good' : s.effect < 0 ? 'bad' : ''}"><div class="mmsct">${esc(s.title)}</div><p class="small">${esc(s.text)}</p><div class="sect">Déclencheurs</div>` +
        `<ul class="mwnext">${s.triggers.map(t => `<li class="small">${esc(t)}</li>`).join('')}</ul></div>`).join('') + '</div>', 'wide');
  }
  const secMedium = () => monthHero() + `<div class="mwgrid" style="margin-top:10px">${mediumCard()}</div>${consensusCard()}<div style="margin-top:10px">${scenariosCard()}</div>`;

  // ---------- 8. recherche de Claude ----------
  function commentCard() {
    const c = wk && wk.comment;
    return card('Commentaire de la semaine <small class="muted">rapports de la Fed et du reste du monde, géopolitique, fonds indiciels cotés, institutionnels</small>',
      (c ? `<div class="mwcomment">${esc(c.text)}</div><div class="note">Rédigé le ${esc(paris(c.t, {day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit'}))} · coût ${num(c.usd, 3)} $ · ${esc(c.model || '')}</div>` :
        '<div class="muted small">Pas encore de commentaire pour cette semaine.</div>') +
      `<div style="margin-top:8px"><button id="mwAsk" class="primary">${c ? 'Refaire le commentaire' : 'Demander le commentaire de Claude'}</button> <span id="mwAskOut" class="muted small">` +
      'Utilise ta clé API Claude (Réglages → 7), quelques centimes par commentaire.</span></div>', 'wide');
  }
  function banksCard() {
    const b = mo && mo.banks;
    const KEYS = [['cuts', 'Baisses de la Fed (12 mois)'], ['fedEnd', 'Taux Fed fin d\'année proch.'], ['us10y', 'Taux 10 ans fin d\'année'], ['recession', 'Récession (12 mois)'],
                  ['spx', 'Objectif S&P 500'], ['dollar', 'Dollar'], ['crypto', 'Bitcoin et cryptos']];
    let body = '<div class="muted small">Pas encore de recherche pour ce mois.</div>';
    if (b) {
      const rows = (b.rows || []).map(x => `<tr><td><b>${esc(x.bank)}</b><div class="muted small">${esc(x.date || '')}</div></td>${KEYS.map(([k]) => `<td class="small">${esc(x[k] || '—')}</td>`).join('')}` +
        `<td class="small">${x.source ? link(x.source, 'source', webUrl) : ''}</td></tr>`).join('');
      body = (rows ? `<div class="mwscroll"><table class="t mwtable"><tr><th>Banque</th>${KEYS.map(([, n]) => `<th>${esc(n)}</th>`).join('')}<th></th></tr>${rows}</table></div>` :
        '<div class="muted small">Claude n\'a pas trouvé de rapport chiffré exploitable cette fois.</div>') +
        `<div class="mwcomment">${esc(b.text)}</div><div class="note">Recherche du ${esc(paris(b.t, {day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit'}))} · coût ${num(b.usd, 3)} $ · ${esc(b.model || '')}. ` +
        'Les chiffres des banques viennent de leurs publications trouvées sur le web : vérifie la source avant de t\'en servir.</div>';
    }
    return card('Rapports des banques et discussion de la Fed <small class="muted">recherche sur le web, pour le mois choisi</small>', body +
      `<div style="margin-top:8px"><button id="mmAsk" class="primary">${b ? 'Refaire la recherche' : 'Lancer la recherche de Claude'}</button> <span id="mmAskOut" class="muted small">` +
      'Utilise ta clé API Claude (Réglages → 7) : quelques dizaines de centimes par recherche (une dizaine de recherches sur le web).</span></div>', 'wide');
  }
  const secClaude = () => commentCard() + '<div style="margin-top:10px"></div>' + banksCard();

  // ---------- 9. mesures sur l'historique ----------
  function regimeStudy() {
    const st = (wk && wk.view && wk.view.regimeStudy) || (mo && mo.regimeStudy);
    if (!st || !st.rows || !st.rows.length) return '';
    return card(`Le bitcoin le mois suivant, selon le régime <small class="muted">${esc(st.from || '')} → ${esc(st.to || '')}</small>`, '<div class="mwscroll"><table class="t">' +
      '<tr><th>Régime</th><th class="r">Mois</th><th class="r">Moyenne</th><th class="r">En hausse</th><th>Verdict</th></tr>' +
      st.rows.map(x => `<tr><td>${esc(QL[x.quad] || x.label)}</td><td class="r">${x.n}</td><td class="r ${x.mean > 0 ? 'up' : x.mean < 0 ? 'dn' : ''}">${x.mean == null ? '—' : sg(x.mean, 1) + ' %'}</td>` +
        `<td class="r">${x.hit == null ? '—' : num(x.hit, 0) + ' %'}</td><td class="small ${/net/.test(x.verdict) ? 'amb' : 'muted'}">${esc(x.verdict)}</td></tr>`).join('') +
      `</table></div><div class="note">${esc(st.note || '')}</div>`);
  }
  function weekStudy() {
    const s = wk && wk.study;
    if (!s || !s.ready) return card('Ce qui a vraiment compté pour le bitcoin', `<div class="muted">${esc((s && s.note) || 'Mesure pas encore disponible (données officielles ou historique du bitcoin manquants).')}</div>`, 'wide');
    const rows = s.rows.map(x => `<tr><td>${esc(x.label)}</td><td class="r">${x.nFav} / ${x.nUnf}</td>` +
      `<td class="r ${x.fav1 > 0 ? 'up' : 'dn'}">${sg(x.fav1, 2)} %</td><td class="r ${x.unf1 > 0 ? 'up' : 'dn'}">${sg(x.unf1, 2)} %</td>` +
      `<td class="r">${num(x.hitFav, 0)} % / ${num(x.hitUnf, 0)} %</td><td class="r">${x.fav4 == null ? '—' : sg(x.fav4, 1) + ' % / ' + sg(x.unf4, 1) + ' %'}</td>` +
      `<td class="mwverdict ${/net/.test(x.verdict) ? (/inverse/.test(x.verdict) ? 'amb' : 'up') : 'muted'}">${esc(x.verdict)}${x.t1 != null ? ` <span class="muted small">(statistique ${sg(x.t1, 1)})</span>` : ''}</td></tr>`).join('');
    return card(`Ce qui a vraiment compté pour le bitcoin <small class="muted">mesure de ${esc(s.from)} à ${esc(s.to)}</small>`,
      `<div class="mwscroll"><table class="t"><tr><th>Moteur (sens « favorable » selon la théorie)</th><th class="r">Semaines favorables / défavorables</th><th class="r">Bitcoin semaine suivante, si favorable</th>` +
      `<th class="r">… si défavorable</th><th class="r">Semaines en hausse (fav. / défav.)</th><th class="r">4 semaines suivantes (fav. / défav.)</th><th>Verdict</th></tr>${rows}</table></div><div class="note">${esc(s.note)}</div>`, 'wide');
  }
  function fngCard() {
    const f = an && an.macro && an.macro.fng, s = f && f.stats;
    if (!s) return '';
    const p0 = v => v == null ? '-' : Math.round(v * 100) + ' %';
    return card(`Que fait le bitcoin après chaque zone de Fear &amp; Greed ? <small class="muted">${s.days.toLocaleString('fr-FR')} jours depuis le ${new Date(s.since).toLocaleDateString('fr-FR')}</small>`,
      `<div class="hero"><div class="big neu">${f.value}</div><div class="sub">${esc(f.label)}${f.d7 != null ? ` · ${sg(f.d7, 0)} en 7 jours` : ''}</div><div style="flex:1;min-width:120px">${Charts.spark(f.spark, '#c98500', 200, 40)}</div></div>` +
      '<table class="t"><tr><th>Zone</th><th class="r">Hausse à 1 j</th><th class="r">à 7 j</th><th class="r">à 30 j</th><th class="r">Gain moyen 7 j</th></tr>' +
      s.rows.map(r => { const c = h => { const v = r[h], b = s.base[h], e = v.lo != null && v.lo > b ? 'up' : v.hi != null && v.hi < b ? 'dn' : ''; return `<td class="r ${e}">${p0(v.p)}</td>`; };
        return `<tr class="${r.current ? 'hl' : ''}"><td>${r.current ? '▶ ' : ''}${esc(r.zone)} <span class="muted small">n=${r['7'].n}</span></td>${c('1')}${c('7')}${c('30')}<td class="r ${r['7'].mean > 0 ? 'up' : 'dn'}">${sg(r['7'].mean, 1)} %</td></tr>`; }).join('') +
      `<tr><td class="muted">Hasard (tous les jours)</td><td class="r muted">${p0(s.base['1'])}</td><td class="r muted">${p0(s.base['7'])}</td><td class="r muted">${p0(s.base['30'])}</td><td></td></tr></table>` +
      '<div class="note">Vert / rouge : l\'intervalle de confiance à 90 % est entièrement au-dessus / en dessous du hasard (fenêtres qui se chevauchent : effectifs indépendants réduits).</div>');
  }
  const secStudy = () => weekStudy() + `<div class="mwgrid" style="margin-top:10px">${regimeStudy()}${fngCard()}</div>`;

  // ---------- page ----------
  const BUILD = {fed: secFed, regime: secRegime, board: secBoard, markets: secMarkets, medium: secMedium, claude: secClaude, study: secStudy};
  function render() {
    const body = root && root.querySelector('#mxBody');
    if (!body || (!wk && !mo && !an)) return;
    const y = window.scrollY;
    const errs = [];
    [[wk, 'semaine'], [mo, 'mois']].forEach(([r, n]) => {
      if (!r) return;
      if (r.error) errs.push(`${n} : ${r.error}`);
      Object.entries((r.sources || {}).errors || {}).forEach(([k, v]) => errs.push(`${k} : ${v}`));
    });
    Object.entries((an && an.macro && an.macro.errors) || {}).forEach(([k, v]) => errs.push(`${k} : ${v}`));
    const fe = Object.keys(((wk && wk.sources) || {}).fredErrors || {});
    const info = [];
    if (wk && wk.built) info.push(`semaine ${wk.current ? 'en cours, recalculée toutes les 5 minutes' : wk.reconstructed ? 'établie après coup' : 'archivée'}`);
    if (mo && mo.built) info.push(`mois ${mo.current ? 'en cours' : mo.reconstructed ? 'établi après coup' : 'archivé'}`);
    root.querySelector('#mxInfo').textContent = info.join(' · ') + (wk && wk.built ? ` · ${paris(wk.built, {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'})}` : '');
    body.className = '';
    body.innerHTML =
      ((wk && wk.hasFred === false) || (mo && mo.hasFred === false) ? '<div class="acard warnbox">Les chiffres officiels américains (base FRED de la Fed de Saint-Louis) ne sont pas encore arrivés ou sont injoignables : l\'analyse est incomplète. Le terminal réessaie toutes les 3 heures.</div>' : '') +
      essentials() + announcements() +
      SECTIONS.map(([k, t, sub]) => `<details class="mxsec" data-sec="${k}"${opened.has(k) ? ' open' : ''}><summary><b>${t}</b> <small>${sub}</small></summary><div class="mxin">${BUILD[k]()}</div></details>`).join('') +
      (errs.length || fe.length ? `<div class="note">Sources en difficulté : ${esc([...new Set(errs)].concat(fe.length ? [`FRED (${fe.length} série${fe.length > 1 ? 's' : ''} : ${fe.slice(0, 4).join(', ')})`] : []).join(' ; '))}</div>` : '') +
      '<div class="note">Sources : base FRED de la Réserve fédérale de Saint-Louis (chiffres officiels et projections des membres de la Fed), site de la Fed (communiqués, comptes rendus, discours), Fonds monétaire international, ' +
      'calendrier ForexFactory (consensus et chiffre précédent), Yahoo Finance (marchés), Binance (cryptos), CoinGecko et alternative.me (sentiment). Les lectures « favorable / défavorable » sont des règles classiques d\'économistes, pas des prévisions.</div>';
    const tl = body.querySelector('#mxTl'), m = an && an.macro;
    if (tl && m) Charts.timeline(tl, [...(m.past || []), ...(m.upcoming || [])], an.t);
    body.querySelectorAll('details.mxsec[open]').forEach(draw);
    if (Math.abs(window.scrollY - y) > 2) window.scrollTo(0, y);
  }
  // graphiques d'une section : dessinés à l'ouverture (ils mesurent leur largeur)
  function draw(d) {
    const p = d.querySelector('#mxPath'), q = d.querySelector('#mxQuad'), rec = d.querySelector('#mxRec');
    if (p) Charts.ratePath(p, (mo && mo.fed) || (wk && wk.view && wk.view.fed) || {});
    if (q) {
      const vr = wk && wk.view && wk.view.regime, tr = ((vr && vr.trail) || (mo && mo.regime && mo.regime.trail) || []);
      Charts.quadrant(q, tr.map((x, k) => ({...x, label: k === tr.length - 1 ? 'maintenant' : paris(x.t, {month: 'long', year: 'numeric'})})), {quads: QS, long: QL});
    }
    const rp = ((mo && mo.medium) || {}).recession || [];
    if (rec && rp.length > 2) Charts.line(rec, {series: [{name: 'Probabilité de récession dans 12 mois', color: '#d95926', pts: rp.map(x => [Date.parse(x.ym + '-01T00:00:00Z'), x.prob])}], height: 150,
      xFmt: v => new Date(v).toLocaleDateString('fr-FR', {month: 'short', year: '2-digit'}), yFmt: v => Math.round(v) + ' %', xTicks: 4});
  }
  async function askWeek() {
    const b = root.querySelector('#mwAsk'), out = root.querySelector('#mwAskOut');
    b.disabled = true; out.className = 'muted small'; out.textContent = 'Claude lit le bilan et cherche les rapports de la semaine… (30 secondes à 2 minutes)';
    try {
      const r = await LT.api('/api/macroweek/comment', {week: wk.week});
      if (!r.ok) { out.className = 'dn small'; out.textContent = r.answer || 'Échec.'; b.disabled = false; return; }
      await load(true);
    } catch (e) { out.className = 'dn small'; out.textContent = 'Erreur : ' + e.message; b.disabled = false; }
  }
  async function askMonth() {
    const b = root.querySelector('#mmAsk'), out = root.querySelector('#mmAskOut');
    b.disabled = true; out.className = 'muted small'; out.textContent = 'Claude lit l\'analyse et cherche les rapports des banques et la discussion de la Fed… (1 à 3 minutes)';
    try {
      const r = await LT.api('/api/macromonth/research', {month: mo.month});
      if (!r.ok) { out.className = 'dn small'; out.textContent = r.answer || 'Échec.'; b.disabled = false; return; }
      await load(true);
    } catch (e) { out.className = 'dn small'; out.textContent = 'Erreur : ' + e.message; b.disabled = false; }
  }
  return {init, show, hide, load, setAnalysis};
})();
