// Macro de la semaine : V25 vision d'ensemble en tête (régime, surprises, Fed, estimation du terminal) ; V18 bilan : annonces avec chiffres publiés, tableau de bord par thème, marchés, crypto, ce que cela engendre,
// mesure sur l'historique du bitcoin, semaine prochaine et commentaire facultatif de Claude. Une version archivée par semaine.
const MacroWeek = (() => {
  'use strict';
  let LT = null, root = null, week = null, data = null, timer = null, busy = false;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const num = (v, d = 1) => v == null || isNaN(v) ? '—' : v.toLocaleString('fr-FR', {minimumFractionDigits: d, maximumFractionDigits: d});
  const sg = (v, d = 1) => v == null || isNaN(v) ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toLocaleString('fr-FR', {minimumFractionDigits: d, maximumFractionDigits: d});
  const paris = (t, o) => new Date(t).toLocaleString('fr-FR', {timeZone: 'Europe/Paris', ...o});
  const day = t => paris(t, {weekday: 'short', day: '2-digit', month: '2-digit'});
  const hm = t => paris(t, {hour: '2-digit', minute: '2-digit'});
  const range = (s, e) => `du ${paris(s, {day: 'numeric', month: 'long'})} au ${paris(e - 86400000, {day: 'numeric', month: 'long', year: 'numeric'})}`;
  const tone = s => s == null ? '' : s >= 0.75 ? 'up' : s <= -0.75 ? 'dn' : s > 0 ? 'up' : s < 0 ? 'dn' : '';
  const UNIT = {'%': ' %', point: ' point', pb: ' point de base', 'Md$': ' Md$', milliers: ' milliers', millions: ' millions', million: ' million', '$': ' $', indice: '', points: '', personnes: ''};
  const unit = u => UNIT[u] !== undefined ? UNIT[u] : (u ? ' ' + u : '');

  function init(lt, host) {
    LT = lt; root = host;
    root.innerHTML = `<div class="mwbar"><label class="muted small">Semaine <select id="mwWeek"></select></label><span id="mwInfo" class="muted small"></span>` +
      `<span class="spacer"></span><button id="mwReload" title="Recalculer avec les dernières données">↻ Actualiser</button></div><div id="mwBody" class="muted">Chargement du bilan…</div>`;
    root.querySelector('#mwWeek').onchange = e => { week = e.target.value; load(); };
    root.querySelector('#mwReload').onclick = () => load(true);
    root.addEventListener('click', e => {
      if (e.target.closest('#mwAsk')) ask();
      const tr = e.target.closest('tr[data-up]');
      if (tr && !e.target.closest('a')) { openUp = openUp === tr.dataset.up ? null : tr.dataset.up; render(); }
    });
  }
  async function loadList() {
    try {
      const l = await LT.api('/api/macroweeks'), sel = root.querySelector('#mwWeek');
      if (!week) week = l.current;
      sel.innerHTML = l.weeks.map(w => {
        const s = Date.parse(w.week + 'T00:00:00Z');
        return `<option value="${w.week}" ${w.week === week ? 'selected' : ''}>${esc(range(s, s + 7 * 86400000))}${w.current ? ' (en cours)' : ''}${w.label ? ' · ' + esc(w.label) : ''}${w.comment ? ' · commentée' : ''}</option>`;
      }).join('');
    } catch (e) { /* liste indisponible : la semaine en cours reste lisible */ }
  }
  async function load(force) {
    if (busy) return;
    busy = true;
    try {
      if (force || !root.querySelector('#mwWeek option')) await loadList();
      data = await LT.api('/api/macroweek' + (week ? '?week=' + week : ''));
      render();
    } catch (e) { root.querySelector('#mwBody').innerHTML = `<div class="acard">Bilan indisponible : ${esc(e.message)}</div>`; }
    busy = false;
  }
  function show() {
    load(true);
    clearInterval(timer);
    timer = setInterval(() => { if (data && data.current) load(); }, 300000);
  }
  function hide() { clearInterval(timer); timer = null; }

  // ---------- V25 : vision de la semaine (en tête) ----------
  const QL = {goldilocks: 'Croissance qui tient, inflation qui ralentit', reflation: 'Surchauffe', stagflation: 'Stagflation', slowdown: 'Ralentissement'};
  const QS = {goldilocks: 'Boucles d\'or', reflation: 'Surchauffe', stagflation: 'Stagflation', slowdown: 'Ralentissement'};    // coins du quadrant (courts)
  const cap = s => s ? s[0].toUpperCase() + s.slice(1) : '';
  const fedUrl = u => /^https:\/\/www\.federalreserve\.gov\//.test(u || '');
  const link = (u, txt) => fedUrl(u) ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(txt)}</a>` : esc(txt);
  const date = t => paris(t, {day: 'numeric', month: 'long'});
  function gauge2(v, span = 2, title = '') {
    if (v == null) return '';
    return `<div class="mwgauge" title="${esc(title)}"><i style="left:${50 + Math.max(-span, Math.min(span, v)) / span * 50}%"></i><u></u></div>`;
  }
  function viewHero(v) {
    const parts = (v.parts || []).map(p => `<span class="pill ${tone(p.score)}">${esc(p.name)} ${p.score > 0.1 ? '▲' : p.score < -0.1 ? '▼' : '•'}</span>`).join(' ');
    return `<div class="acard mwhero mwview"><h3>Vision de la semaine <small class="muted">— régime, surprises, Fed et annonces à venir, reliés à partir des chiffres ; lecture classique, pas une prévision</small></h3>` +
      (v.label ? `<div class="mwvent ${tone(v.score)}">${esc(cap(v.label))} pour les actifs à risque</div>${gauge2(v.score, 2.5, 'somme des composantes ci-dessous')}` : '') +
      `<div class="mwparts">${parts}</div>` + (v.lines || []).map(l => `<p><b>${esc(l.title)}.</b> ${esc(l.text)}</p>`).join('') + '</div>';
  }
  function studyRows(st) {
    if (!st || !st.rows || !st.rows.length) return '';
    return `<div class="sect">Le bitcoin le mois suivant, selon le régime <span class="muted small">(${esc(st.from || '')} → ${esc(st.to || '')})</span></div><div class="mwscroll"><table class="t">` +
      `<tr><th>Régime</th><th class="r">Mois</th><th class="r">Moyenne</th><th class="r">En hausse</th><th>Verdict</th></tr>` +
      st.rows.map(x => `<tr><td>${esc(QL[x.quad] || x.label)}</td><td class="r">${x.n}</td><td class="r ${x.mean > 0 ? 'up' : x.mean < 0 ? 'dn' : ''}">${x.mean == null ? '—' : sg(x.mean, 1) + ' %'}</td>` +
        `<td class="r">${x.hit == null ? '—' : num(x.hit, 0) + ' %'}</td><td class="small ${/net/.test(x.verdict) ? 'amb' : 'muted'}">${esc(x.verdict)}</td></tr>`).join('') +
      `</table></div><div class="note">${esc(st.note || '')}</div>`;
  }
  function regimeCard(v) {
    const r = v.regime || {};
    const comp = (list, title) => list.length ? `<div class="sect">${title}</div><table class="t">` + list.map(c =>
      `<tr><td>${esc(c.name)}<div class="muted small">${esc(c.text)}</div></td><td style="width:32%" title="${sg(c.score, 2)} (de −2 à +2)">${Charts.dvBar(c.score, 2, '#9aa0ae', '#9aa0ae')}</td></tr>`).join('') + '</table>' : '';
    return `<div class="acard"><h3>Régime : croissance et inflation <small class="muted">— élan sur 3 mois face à un an, trajet sur 12 mois</small></h3>` +
      (r.label ? `<div class="mwregime">${esc(r.label)}</div><div class="muted small">${esc(r.text || '')}</div>` : '<div class="muted">Pas assez de chiffres officiels pour situer le régime.</div>') +
      `<div id="mwQuad" class="mwq"></div>` + comp(r.growth || [], 'Croissance') + comp(r.inflation || [], 'Inflation') + studyRows(v.regimeStudy) + '</div>';
  }
  function fedCard(v) {
    const f = v.fed || {}, c = f.cuts;
    const a = c == null ? 0 : Math.round(Math.abs(c) * 10) / 10;
    const big = c == null ? '' : `<div class="mwbig">${a < 0.4 ? 'pas de changement net' : `≈ ${num(a, 1)} ${c > 0 ? 'baisse' : 'hausse'}${a >= 2 ? 's' : ''} de 0,25 point`}</div>` +
      `<div class="muted small">${a < 0.4 ? 'attendu' : 'attendue' + (a >= 2 ? 's' : '')} par le marché d'ici un an environ` +
      (f.cutsChange != null && Math.abs(f.cutsChange) >= 0.1 ? ` · <span class="${f.cutsChange > 0 ? 'up' : 'dn'}">${sg(f.cutsChange, 1)}</span> ${esc((f.changeLabel || 'sur la semaine').toLowerCase())}` : '') + '</div>';
    return `<div class="acard"><h3>Ce que le marché attend de la Fed</h3>${big}<div id="mwPath" class="mwpath"></div>` +
      (f.text || []).map(x => `<p class="small">${esc(x)}</p>`).join('') +
      `<div class="note">Chemin du marché déduit des taux d'État à 3 mois, 6 mois, 1 an et 2 ans : une approximation (la référence, les contrats à terme sur le taux de la Fed, n'est pas en accès libre). ` +
      `Points orange : projections des membres de la Fed${f.sepDate ? ' publiées le ' + esc(date(f.sepDate)) : ''}.</div></div>`;
  }
  function surpCard(v) {
    const s = v.surprises || {};
    const one = (x, name, inflation) => !x ? '' : `<div class="mwsurp"><div><b>${name}</b> : <span class="${inflation && x.value != null ? (x.value >= 0.15 ? 'dn' : x.value <= -0.15 ? 'up' : '') : ''}">${esc(x.label)}</span></div>` +
      (x.value != null ? gauge2(x.value, 2, 'moyenne des écarts au consensus, en écarts habituels (de −2 à +2)') : '') +
      `<div class="muted small">${x.n} chiffre${x.n > 1 ? 's' : ''} : ${x.above} au-dessus, ${x.below} en dessous, ${x.inline} conforme${x.inline > 1 ? 's' : ''}</div></div>`;
    const rows = (s.rows || []).slice(0, 10).map(r => `<tr><td class="nowrap">${esc(day(r.t))}</td><td>${esc(r.label)}</td><td class="r">${esc(r.actual)}</td><td class="r muted">${esc(r.forecast || '—')}</td>` +
      `<td style="width:26%" title="${sg(r.z, 1)} écart habituel">${Charts.dvBar(r.z, 3, r.grp === 'inflation' ? '#ff6b6b' : '#9aa0ae', r.grp === 'inflation' ? '#3ddc97' : '#9aa0ae')}</td></tr>`).join('');
    return `<div class="acard"><h3>Les chiffres face au consensus <small class="muted">— ${s.days || 56} derniers jours</small></h3>` +
      one(s.activity, 'Activité et emploi', false) + one(s.inflation, 'Inflation', true) +
      (rows ? `<div class="mwscroll"><table class="t"><tr><th>Quand</th><th>Chiffre</th><th class="r">Publié</th><th class="r">Consensus</th><th>Écart</th></tr>${rows}</table></div>` :
        '<div class="muted small">Aucun chiffre publié retrouvé sur la période (le calendrier se remplit depuis l\'installation du terminal ; FRED couvre les grandes statistiques américaines).</div>') +
      `<div class="note">Écart = (publié − consensus) rapporté à l'écart habituel de ce chiffre ; chômage et inscriptions au chômage comptés à l'envers (plus haut = activité plus faible). Les plus récents pèsent davantage (demi-vie de 3 semaines).</div></div>`;
  }
  let openUp = null;
  function upcomingCard(v) {
    const ups = v.upcoming || [];
    if (!ups.length) return '';
    const rows = ups.map(e => {
      const ln = e.lean ? `<span class="${e.cat === 'inflation' ? (e.lean > 0 ? 'dn' : 'up') : 'amb'}" title="${esc(e.leanText)}">${e.lean > 0 ? '▲ au-dessus' : '▼ en dessous'}</span>` :
        (e.estimateText ? '<span class="muted small">pas de signal</span>' : '');
      const open = openUp === e.id;
      return `<tr data-up="${esc(e.id)}" class="${(v.key || []).includes(e.id) ? 'hl' : ''}" style="cursor:pointer"><td class="nowrap">${esc(day(e.t))}<div class="muted small">${esc(hm(e.t))} Paris</div></td>` +
        `<td><b>${esc(e.label)}</b> <span class="pill">${esc(e.country)}</span></td><td class="r">${esc(e.forecast || '—')}</td><td class="r">${esc(e.previous || '—')}</td>` +
        `<td class="r">${e.estimateText ? `<b>${esc(e.estimateText)}</b><div class="muted small">${esc(e.errorText)}</div>` : '<span class="muted small">—</span>'}</td><td>${ln}</td></tr>` +
        (open ? `<tr><td></td><td colspan="5" class="small">${e.how ? `<div><b>Estimation du terminal</b> : ${esc(e.how)}${e.errorText ? ` ; erreur habituelle de cette méthode sur 5 ans : ${esc(e.errorText)}` : ''}.</div>` : ''}` +
          (e.leanText ? `<div>${esc(e.leanText)}</div>` : '') + (e.scenUp ? `<div class="muted">${esc(e.scenUp)}<br>${esc(e.scenDn)}</div>` : '') + '</td></tr>' : '');
    }).join('');
    return `<div class="acard wide"><h3>Annonces à venir : consensus et estimation du terminal <small class="muted">— 7 prochains jours ; clique une ligne pour le détail</small></h3>` +
      `<div class="mwscroll"><table class="t mwtable"><tr><th>Quand</th><th>Annonce</th><th class="r">Consensus</th><th class="r">Précédent</th><th class="r">Estimation du terminal</th><th>Penchant</th></tr>${rows}</table></div>` +
      `<div class="note">Estimation du terminal = tendance des derniers mois (inflation totale : tendance sous-jacente, alimentation et prix de l'essence ; croissance : GDPNow de la Fed d'Atlanta), avec son erreur habituelle mesurée sur 5 ans. ` +
      `Un « penchant » n'apparaît que si l'écart avec le consensus dépasse la moitié de cette erreur. Les économistes connaissent aussi ces tendances : c'est un repère, pas une prévision.</div></div>`;
  }
  function commsCard(v) {
    const c = v.comms || [];
    if (!c.length) return '';
    return `<div class="acard wide"><h3>Ce que la Fed a publié cette semaine</h3><ul class="mwnext">` +
      c.map(x => `<li><b>${esc(day(x.t))}</b> — <span class="pill">${esc(x.kindLabel)}</span> ${link(x.link, x.title)}${x.speaker ? ` <span class="muted small">(${esc(x.speaker)})</span>` : ''}</li>`).join('') +
      '</ul><div class="note">Textes en anglais sur le site de la Fed. Le commentaire de Claude (plus bas) peut les résumer.</div></div>';
  }
  function view(r) {
    const v = r.view;
    if (!v) return '';
    return viewHero(v) + `<div class="mwgrid">${regimeCard(v)}${fedCard(v)}${surpCard(v)}</div>` + upcomingCard(v) + commsCard(v) +
      '<h2 class="mwtitle mwsub">Bilan de la semaine</h2>';
  }
  function drawView(r) {
    const v = r.view;
    if (!v) return;
    const q = root.querySelector('#mwQuad'), p = root.querySelector('#mwPath');
    if (q) Charts.quadrant(q, (v.regime.trail || []).map(x => ({...x, label: x.t === v.regime.trail[v.regime.trail.length - 1].t ? 'maintenant' : paris(x.t, {month: 'long', year: 'numeric'})})), {quads: QS, long: QL});
    if (p) Charts.ratePath(p, v.fed || {});
  }

  // ---------- sections ----------
  function hero(r) {
    const v = r.verdict || {}, sc = v.score;
    const gauge = sc == null ? '' : `<div class="mwgauge" title="somme des lectures par thème (de −7 à +7)"><i style="left:${50 + Math.max(-7, Math.min(7, sc)) / 7 * 50}%"></i><u></u></div>`;
    const parts = (v.parts || []).map(p => `<span class="pill ${tone(p.score)}" title="${esc(p.read)}">${esc(p.title)} ${p.score > 0 ? '▲' : p.score < 0 ? '▼' : '•'}</span>`).join(' ');
    return `<div class="acard mwhero"><h3>Ce que cela engendre <small class="muted">— lecture par règles classiques, non validée par le backtest (voir la mesure plus bas)</small></h3>` +
      (v.label ? `<div class="mwvent ${tone(sc)}">Vent macro ${esc(v.label)}</div>${gauge}` : '<div class="muted">Pas assez de données officielles pour une lecture (FRED injoignable ?).</div>') +
      `<div class="mwparts">${parts}</div>${(v.lines || []).map(l => `<p>${esc(l)}</p>`).join('')}</div>`;
  }
  function eventsCard(r) {
    const evs = r.events || [];
    if (!evs.length) return `<div class="acard"><h3>Annonces de la semaine</h3><div class="muted">Aucune annonce importante enregistrée pour cette semaine${r.reconstructed ? ' (le calendrier ne remonte que depuis l\'installation du terminal)' : ''}.</div></div>`;
    const rows = evs.map(e => {
      const pub = e.actual ? `<b>${esc(e.actual.text)}</b><div class="muted small">${esc(e.actual.period || '')}</div>` :
        e.past ? '<span class="muted small" title="Le flux gratuit ne donne pas le chiffre publié ; FRED ne couvre que les grandes statistiques américaines, parfois avec quelques heures de retard.">non fourni</span>' : '<span class="muted small">à venir</span>';
      const surp = e.surprise == null ? '' : `<span class="${e.cat === 'inflation' ? (e.surprise > 0 ? 'dn' : e.surprise < 0 ? 'up' : '') : ''}" title="chiffre publié moins consensus">${esc(e.surpriseText || sg(e.surprise, 2))}</span>`;
      const read = e.read ? esc(e.read) : (!e.past && e.scenUp ? `<span class="muted">Si au-dessus du consensus : ${esc(e.scenUp.replace(/^Chiffre supérieur au consensus : /, ''))}</span>` : '');
      const stars = '★'.repeat(Math.min(3, e.impact || 0));
      return `<tr class="${e.past ? '' : 'mwfut'}"><td class="nowrap">${esc(day(e.t))}<div class="muted small">${esc(hm(e.t))} Paris</div></td>` +
        `<td><b>${esc(e.label)}</b> <span class="pill">${esc(e.country)}</span>${stars ? ` <span class="amb small" title="importance">${stars}</span>` : ''}<div class="muted small">${esc(e.title)}</div></td>` +
        `<td class="r">${esc(e.forecast || '—')}</td><td class="r">${esc(e.previous || '—')}</td><td class="r">${pub}</td><td class="r">${surp}</td>` +
        `<td class="mwread">${read}${e.reactionText ? `<div class="muted small">${esc(e.reactionText)}</div>` : ''}</td></tr>`;
    }).join('');
    return `<div class="acard wide"><h3>Annonces de la semaine <small class="muted">— heures de Paris ; chiffre publié recalculé à partir de la base officielle FRED pour les grandes statistiques américaines</small></h3>` +
      `<div class="mwscroll"><table class="t mwtable"><tr><th>Quand</th><th>Annonce</th><th class="r">Consensus</th><th class="r">Précédent</th><th class="r">Publié</th><th class="r">Écart</th><th>Ce que cela veut dire</th></tr>${rows}</table></div></div>`;
  }
  function themeCard(th) {
    if (!th.items.length) return '';
    const rows = th.items.map(it => `<tr><td>${esc(it.name)}${it.note ? `<div class="muted small">${esc(it.note)}</div>` : ''}</td>` +
      `<td class="r nowrap"><b>${num(it.value, it.d)}</b>${esc(unit(it.unit))}</td>` +
      `<td class="r nowrap small">${it.change == null ? '' : `${sg(it.change, it.cd)}${esc(unit(it.changeUnit))}<div class="muted">${esc(it.changeLabel || '')}</div>`}</td></tr>`).join('');
    return `<div class="acard"><h3>${esc(th.title)}${th.score != null ? ` <span class="pill ${tone(th.score)}">${th.score > 0 ? 'favorable' : th.score < 0 ? 'défavorable' : 'neutre'}</span>` : ''}</h3>` +
      (th.read ? `<p class="mwthread ${tone(th.score)}">${esc(th.read)}</p>` : '') + `<table class="t">${rows}</table></div>`;
  }
  function marketsCard(r) {
    const m = r.markets || [];
    if (!m.length) return '';
    const mx = Math.max(1, ...m.filter(x => x.unit === '%').map(x => Math.abs(x.chg || 0)));
    const rows = m.map(x => {
      const pb = x.unit === 'pb', w = pb ? 0 : Math.min(100, Math.abs(x.chg || 0) / mx * 100);
      return `<tr><td>${esc(x.name)}</td><td class="r nowrap ${pb ? '' : (x.chg > 0 ? 'up' : x.chg < 0 ? 'dn' : '')}">${pb ? sg(x.chg, 0) + ' pb' : sg(x.chg, 1) + ' %'}</td>` +
        `<td class="mwbarcell">${pb ? '' : `<i class="${x.chg >= 0 ? 'pos' : 'neg'}" style="width:${w / 2}%"></i>`}</td></tr>`;
    }).join('');
    return `<div class="acard"><h3>Marchés sur la semaine <small class="muted">— depuis la clôture de vendredi dernier</small></h3><table class="t">${rows}</table>` +
      `<div class="note">pb = point de base (0,01 point de taux).</div></div>`;
  }
  function cryptoCard(r) {
    const c = r.crypto || {};
    if (!(c.rows || []).length && !c.rotation) return '';
    const rows = (c.rows || []).map(x => `<tr><td>${esc(x.name)}</td><td class="r nowrap"><b>${num(x.value, x.d)}</b>${esc(unit(x.unit))}</td>` +
      `<td class="r nowrap small">${x.change == null ? '' : sg(x.change, x.changeUnit === '%' ? 1 : x.d || 1) + ' ' + esc(x.changeUnit)}</td></tr>`).join('');
    return `<div class="acard"><h3>Crypto et institutionnels <small class="muted">— variation sur la semaine</small></h3><table class="t">${rows}</table>` +
      (c.rotation ? `<p class="small">Où va l'argent : ${esc(c.rotation)}</p>` : '') + '</div>';
  }
  function studyCard(r) {
    const s = r.study;
    if (!s || !s.ready) return `<div class="acard wide"><h3>Ce qui a vraiment compté pour le bitcoin</h3><div class="muted">${esc((s && s.note) || 'Mesure pas encore disponible (données officielles ou historique du bitcoin manquants).')}</div></div>`;
    const rows = s.rows.map(x => `<tr><td>${esc(x.label)}</td><td class="r">${x.nFav} / ${x.nUnf}</td>` +
      `<td class="r ${x.fav1 > 0 ? 'up' : 'dn'}">${sg(x.fav1, 2)} %</td><td class="r ${x.unf1 > 0 ? 'up' : 'dn'}">${sg(x.unf1, 2)} %</td>` +
      `<td class="r">${num(x.hitFav, 0)} % / ${num(x.hitUnf, 0)} %</td><td class="r">${x.fav4 == null ? '—' : sg(x.fav4, 1) + ' % / ' + sg(x.unf4, 1) + ' %'}</td>` +
      `<td class="mwverdict ${/net/.test(x.verdict) ? (/inverse/.test(x.verdict) ? 'amb' : 'up') : 'muted'}">${esc(x.verdict)}${x.t1 != null ? ` <span class="muted small">(statistique ${sg(x.t1, 1)})</span>` : ''}</td></tr>`).join('');
    return `<div class="acard wide"><h3>Ce qui a vraiment compté pour le bitcoin <small class="muted">— mesure de ${esc(s.from)} à ${esc(s.to)}</small></h3>` +
      `<div class="mwscroll"><table class="t"><tr><th>Moteur (sens « favorable » selon la théorie)</th><th class="r">Semaines favorables / défavorables</th><th class="r">Bitcoin semaine suivante, si favorable</th>` +
      `<th class="r">… si défavorable</th><th class="r">Semaines en hausse (fav. / défav.)</th><th class="r">4 semaines suivantes (fav. / défav.)</th><th>Verdict</th></tr>${rows}</table></div>` +
      `<div class="note">${esc(s.note)}</div></div>`;
  }
  function nextCard(r) {
    const n = r.next || [];
    if (!n.length) return '';
    const rows = n.map(e => `<li><b>${esc(day(e.t))} ${esc(hm(e.t))}</b> — ${esc(e.label)} <span class="pill">${esc(e.country)}</span>` +
      (e.forecast ? ` <span class="muted">consensus ${esc(e.forecast)}, précédent ${esc(e.previous || '—')}</span>` : '') +
      (e.scenUp ? `<div class="small muted">${esc(e.scenUp)}<br>${esc(e.scenDn)}</div>` : '') + '</li>').join('');
    return `<div class="acard wide"><h3>Semaine prochaine : à surveiller</h3><ul class="mwnext">${rows}</ul></div>`;
  }
  function commentCard(r) {
    const c = r.comment;
    return `<div class="acard wide"><h3>Commentaire de Claude <small class="muted">— rapports de la Fed et du reste du monde, géopolitique, fonds indiciels cotés (ETF), institutionnels ; recherche sur le web à partir de ce bilan</small></h3>` +
      (c ? `<div class="mwcomment">${esc(c.text)}</div><div class="note">Rédigé le ${esc(paris(c.t, {day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit'}))} · coût ${num(c.usd, 3)} $ · ${esc(c.model || '')}</div>` :
        '<div class="muted small">Pas encore de commentaire pour cette semaine.</div>') +
      `<div style="margin-top:8px"><button id="mwAsk" class="primary">${c ? 'Refaire le commentaire' : 'Demander le commentaire de Claude'}</button> <span id="mwAskOut" class="muted small">` +
      `Utilise ta clé API Claude (Réglages → 7), quelques centimes par commentaire.</span></div></div>`;
  }
  function render() {
    const r = data, body = root.querySelector('#mwBody');
    if (!r) return;
    const errs = Object.entries((r.sources || {}).errors || {}).map(([k, v]) => `${k} : ${v}`);
    const fe = Object.keys((r.sources || {}).fredErrors || {});
    root.querySelector('#mwInfo').textContent = (r.current ? 'semaine en cours, recalculée toutes les 5 minutes' : r.reconstructed ? 'établi après coup (chiffres déjà publiés en fin de semaine)' : 'version archivée') +
      ` · ${paris(r.built, {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'})}`;
    body.className = '';
    body.innerHTML =
      (!r.hasFred ? '<div class="acard warnbox">Les chiffres officiels américains (base FRED de la Fed de Saint-Louis) ne sont pas encore arrivés ou sont injoignables : le tableau de bord est incomplet. Le terminal réessaie toutes les 3 heures.</div>' : '') +
      (errs.length || fe.length ? `<div class="note">Sources en difficulté : ${esc(errs.concat(fe.length ? [`FRED (${fe.length} série${fe.length > 1 ? 's' : ''} : ${fe.slice(0, 4).join(', ')})`] : []).join(' ; '))}</div>` : '') +
      `<h2 class="mwtitle">Semaine ${esc(range(r.start, r.end))}${r.current ? ' <span class="pill">en cours</span>' : ''}</h2>` +
      view(r) + hero(r) + eventsCard(r) +
      `<div class="mwgrid">${(r.themes || []).map(themeCard).join('')}${marketsCard(r)}${cryptoCard(r)}</div>` +
      studyCard(r) + nextCard(r) + commentCard(r) +
      '<div class="note">Sources : base FRED de la Réserve fédérale de Saint-Louis (chiffres officiels, parfois révisés après coup), calendrier ForexFactory (consensus et chiffre précédent), Yahoo Finance (marchés), Binance (cryptos), CoinGecko et alternative.me (dominance, sentiment). ' +
      'Les lectures « favorable / défavorable » sont des règles classiques d\'économistes, pas des prévisions : la mesure ci-dessus dit lesquelles ont réellement fait une différence pour le bitcoin.</div>';
    drawView(r);
  }
  async function ask() {
    const b = root.querySelector('#mwAsk'), out = root.querySelector('#mwAskOut');
    b.disabled = true; out.className = 'muted small'; out.textContent = 'Claude lit le bilan et cherche les rapports de la semaine… (30 secondes à 2 minutes)';
    try {
      const r = await LT.api('/api/macroweek/comment', {week: data.week});
      if (!r.ok) { out.className = 'dn small'; out.textContent = r.answer || 'Échec.'; b.disabled = false; return; }
      await load(true);
    } catch (e) { out.className = 'dn small'; out.textContent = 'Erreur : ' + e.message; b.disabled = false; }
  }
  return {init, show, hide, load};
})();
