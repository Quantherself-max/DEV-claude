// Macro du mois (V25) : synthèse, la Fed (projections de ses membres, chemin attendu par le marché, communiqué annoté mot à mot, votes, discours),
// projections à prendre en compte (Fed, FMI, marché, ménages), vision à moyen terme, scénarios avec déclencheurs, le mois en chiffres,
// et la recherche de Claude (rapports des grandes banques, discussion au sein de la Fed). Une version archivée par mois.
const MacroMonth = (() => {
  'use strict';
  let LT = null, root = null, month = null, data = null, timer = null, busy = false;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const num = (v, d = 1) => v == null || isNaN(v) ? '—' : v.toLocaleString('fr-FR', {minimumFractionDigits: d, maximumFractionDigits: d});
  const sg = (v, d = 1) => v == null || isNaN(v) ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toLocaleString('fr-FR', {minimumFractionDigits: d, maximumFractionDigits: d});
  const paris = (t, o) => new Date(t).toLocaleString('fr-FR', {timeZone: 'Europe/Paris', ...o});
  const day = t => paris(t, {weekday: 'short', day: '2-digit', month: '2-digit'});
  const date = t => paris(t, {day: 'numeric', month: 'long', year: 'numeric'});
  const tone = s => s == null ? '' : s >= 0.4 ? 'up' : s <= -0.4 ? 'dn' : '';
  const cap = s => s ? s[0].toUpperCase() + s.slice(1) : '';
  const UNIT = {'%': ' %', point: ' point', pb: ' pb', 'Md$': ' Md$', milliers: ' milliers', millions: ' millions', million: ' million', '$': ' $', indice: '', points: '', personnes: ''};
  const unit = u => UNIT[u] !== undefined ? UNIT[u] : (u ? ' ' + u : '');
  const QL = {goldilocks: 'Croissance qui tient, inflation qui ralentit', reflation: 'Surchauffe', stagflation: 'Stagflation', slowdown: 'Ralentissement'};
  const QS = {goldilocks: 'Boucles d\'or', reflation: 'Surchauffe', stagflation: 'Stagflation', slowdown: 'Ralentissement'};
  const fedUrl = u => /^https:\/\/www\.federalreserve\.gov\//.test(u || '');
  const webUrl = u => /^https?:\/\/[^\s"'<>]+$/.test(u || '');
  const link = (u, txt, ok = fedUrl) => ok(u) ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(txt)}</a>` : esc(txt);

  function init(lt, host) {
    LT = lt; root = host;
    root.innerHTML = `<div class="mwbar"><label class="muted small">Mois <select id="mmMonth"></select></label><span id="mmInfo" class="muted small"></span>` +
      `<span class="spacer"></span><button id="mmReload" title="Recalculer avec les dernières données">↻ Actualiser</button></div><div id="mmBody" class="muted">Chargement de l'analyse du mois…</div>`;
    root.querySelector('#mmMonth').onchange = e => { month = e.target.value; load(); };
    root.querySelector('#mmReload').onclick = () => load(true);
    root.addEventListener('click', e => { if (e.target.closest('#mmAsk')) ask(); });
  }
  async function loadList() {
    try {
      const l = await LT.api('/api/macromonths'), sel = root.querySelector('#mmMonth');
      if (!month) month = l.current;
      sel.innerHTML = l.months.map(m => `<option value="${esc(m.month)}" ${m.month === month ? 'selected' : ''}>${esc(cap(m.label))}${m.current ? ' (en cours)' : ''}` +
        `${m.tone ? ' · ' + esc(m.tone) : ''}${m.banks ? ' · banques' : ''}</option>`).join('');
    } catch (e) { /* liste indisponible : le mois en cours reste lisible */ }
  }
  async function load(force) {
    if (busy) return;
    busy = true;
    try {
      if (force || !root.querySelector('#mmMonth option')) await loadList();
      data = await LT.api('/api/macromonth' + (month ? '?month=' + month : ''));
      render();
    } catch (e) { root.querySelector('#mmBody').innerHTML = `<div class="acard">Analyse indisponible : ${esc(e.message)}</div>`; }
    busy = false;
  }
  function show() {
    load(true);
    clearInterval(timer);
    timer = setInterval(() => { if (data && data.current) load(); }, 600000);
  }
  function hide() { clearInterval(timer); timer = null; }

  // ---------- sections ----------
  function hero(r) {
    const mt = r.medium || {};
    return `<div class="acard mwhero mwview"><h3>Synthèse du mois <small class="muted">— chaque phrase vient d'un chiffre ; lectures classiques, pas des prévisions</small></h3>` +
      (mt.label ? `<div class="mwvent ${tone(mt.score)}">Moyen terme ${esc(mt.label)} pour les actifs à risque</div>` : '') +
      (r.lines || []).map(l => `<p><b>${esc(l.title)}.</b> ${esc(l.text)}</p>`).join('') + '</div>';
  }
  function fedCard(r) {
    const f = r.fed || {}, c = f.cuts, n = f.next;
    const a = c == null ? 0 : Math.round(Math.abs(c) * 10) / 10;
    const big = c == null ? '' : `<div class="mwbig">${a < 0.4 ? 'pas de changement net' : `≈ ${num(a, 1)} ${c > 0 ? 'baisse' : 'hausse'}${a >= 2 ? 's' : ''} de 0,25 point`}</div>` +
      `<div class="muted small">${a < 0.4 ? 'attendu' : 'attendue' + (a >= 2 ? 's' : '')} par le marché d'ici un an environ` +
      (f.cutsChange != null && Math.abs(f.cutsChange) >= 0.1 ? ` · <span class="${f.cutsChange > 0 ? 'up' : 'dn'}">${sg(f.cutsChange, 1)}</span> ${esc((f.changeLabel || '').toLowerCase())}` : '') + '</div>';
    return `<div class="acard"><h3>La Fed : taux et chemin attendu</h3>${big}` +
      (n ? `<div class="small" style="margin:4px 0">Prochaine décision : <b>${esc(date(n.decision))}</b> (${n.days < 1 ? 'aujourd\'hui ou demain' : `dans ${n.days} jour${n.days > 1 ? 's' : ''}`})${n.sep ? ', avec de nouvelles projections des membres' : ''}.</div>` : '') +
      `<div id="mmPath" class="mwpath"></div>` + (f.text || []).map(x => `<p class="small">${esc(x)}</p>`).join('') +
      `<div class="note">Chemin du marché déduit des taux d'État à 3 mois, 6 mois, 1 an et 2 ans (approximation). Points orange : projections des membres de la Fed${f.sepDate ? ' publiées le ' + esc(date(f.sepDate)) : ''}.</div></div>`;
  }
  function sepCard(r) {
    const s = r.sep || {};
    if (!(s.rows || []).length) return `<div class="acard"><h3>Projections des membres de la Fed</h3><div class="muted">Pas encore de projections (base FRED injoignable ?).</div></div>`;
    const ys = s.years || [];
    const rows = s.rows.map(x => `<tr><td>${esc(x.name)}</td>${ys.map(y => `<td class="r">${x.values[y] == null ? '—' : num(x.values[y], x.sid === 'FEDTARMD' ? 2 : 1) + ' %'}</td>`).join('')}` +
      `<td class="r">${x.sid === 'FEDTARMD' && s.longRun != null ? num(s.longRun, 2) + ' %' : ''}</td></tr>`).join('');
    const rng = ys.filter(y => s.rangeLow && s.rangeLow[y] != null).map(y => `fin ${y} : de ${num(s.rangeLow[y], 2)} à ${num(s.rangeHigh[y], 2)} %`).join(' ; ');
    return `<div class="acard"><h3>Projections des membres de la Fed <small class="muted">— médianes${s.date ? ', réunion du ' + esc(date(s.date)) : ''}</small></h3>` +
      `<div class="mwscroll"><table class="t mmsep"><tr><th></th>${ys.map(y => `<th class="r">${esc(y)}</th>`).join('')}<th class="r">Long terme</th></tr>${rows}</table></div>` +
      (rng ? `<div class="small" style="margin-top:6px">Désaccord sur le taux directeur (du membre le plus bas au plus haut) : ${esc(rng)}.</div>` : '') +
      (s.stale ? '<div class="note amb">Ces projections ont plus de 4 mois : de nouvelles arrivent à la prochaine réunion avec projections.</div>' : '') +
      '<div class="note">Inflation et croissance : de la fin d\'année à la fin d\'année. Long terme : le taux « neutre » vu par la Fed (ni frein ni soutien).</div></div>';
  }
  function diffHtml(ch) {
    return ch.map(([st, txt]) => st === '-' ? `<del>${esc(txt)}</del>` : st === '+' ? `<ins>${esc(txt)}</ins>` : esc(txt)).join(' ');
  }
  function statementCard(r) {
    const s = r.statement || {};
    if (!s.t) return `<div class="acard wide"><h3>Communiqué de la Fed</h3><div class="muted">Communiqué pas encore lu (site de la Fed injoignable ?).</div></div>`;
    const d = s.diff, dec = s.decision || {};
    const MOVE = {baisse: 'Baisse du taux', hausse: 'Hausse du taux', maintien: 'Taux inchangé'};
    let body = `<div class="small">${link(s.link, 'Communiqué du ' + date(s.t))}${s.inMonth ? '' : ' <span class="muted">(dernier connu, avant ce mois)</span>'} : ` +
      `<b>${esc(MOVE[dec.move] || 'décision non lue')}</b>${dec.range ? ` (fourchette « ${esc(dec.range)} percent »)` : ''} · ton <b>${esc((s.tone || {}).label || '—')}</b>` +
      (s.prev ? ` <span class="muted">(précédent, ${esc(date(s.prev.t))} : ${esc((s.prev.tone || {}).label || '—')})</span>` : '') + '</div>';
    if (s.toneText) body += `<p class="small">${esc(s.toneText)}</p>`;
    if (d) {
      const items = (d.changed || []).map(ch => `<li>${diffHtml(ch)}</li>`).concat((d.added || []).map(x => `<li><ins>${esc(x)}</ins></li>`), (d.removed || []).map(x => `<li><del>${esc(x)}</del></li>`));
      body += `<div class="sect">Ce qui a changé face au communiqué précédent <span class="muted small">(${d.same} phrase${d.same > 1 ? 's' : ''} inchangée${d.same > 1 ? 's' : ''})</span></div>` +
        (items.length ? `<ul class="mmdiff">${items.join('')}</ul>` : '<div class="muted small">Aucun changement de texte.</div>');
    }
    if ((s.dissents || []).length) body += `<div class="sect">Votes contre la décision</div><ul class="mwnext">${s.dissents.map(x => `<li class="small">${esc(x)}</li>`).join('')}</ul>`;
    const t = s.tone || {};
    if ((t.hawk || []).length || (t.dove || []).length) body += `<div class="note">Ton mesuré par un lexique simple : formules accommodantes (${(t.dove || []).map(esc).join(', ') || 'aucune'}) ; formules restrictives (${(t.hawk || []).map(esc).join(', ') || 'aucune'}). ` +
      'Indication grossière : le texte change peu d\'une réunion à l\'autre, ce sont les mots ajoutés ou retirés qui comptent.</div>';
    return `<div class="acard wide"><h3>Communiqué de la Fed : ce qui a changé <small class="muted">— texte d'origine en anglais ; <ins>ajouté</ins> / <del>retiré</del></small></h3>${body}</div>`;
  }
  function commsCard(r) {
    const c = r.comms || [];
    if (!c.length) return '';
    return `<div class="acard"><h3>Communication de la Fed ce mois-ci</h3><ul class="mwnext">` +
      c.slice(0, 25).map(x => `<li><b>${esc(day(x.t))}</b> — <span class="pill">${esc(x.kindLabel)}</span> ${link(x.link, x.title)}${x.speaker ? ` <span class="muted small">(${esc(x.speaker)})</span>` : ''}</li>`).join('') +
      '</ul><div class="note">Flux publics du site de la Fed (communiqués, comptes rendus, discours). La recherche de Claude, plus bas, résume la discussion.</div></div>';
  }
  function consensusCard(r) {
    const rows = r.consensus || [];
    if (!rows.length) return '';
    const p = (v, d = 1) => v == null ? null : num(v, d) + ' %';
    const join = (...xs) => xs.filter(Boolean).join(' · ') || '<span class="muted">—</span>';
    const notes = [];
    const note = n => { if (!n) return ''; let k = notes.indexOf(n); if (k < 0) { notes.push(n); k = notes.length - 1; } return `<sup>${k + 1}</sup>`; };
    const rate = x => /^Taux/.test(x.name);
    const body = rows.map(x => { const c = x.cols, d = rate(x) ? 2 : 1;
      return `<tr><td>${esc(x.name)}${note(x.note)}</td><td class="r">${join(p(c.fed, d), c.fed2 != null ? 'totale ' + p(c.fed2) : null)}</td>` +
        `<td class="r">${join(p(c.imf), c.imf2 != null ? 'puis ' + p(c.imf2) : null)}</td><td class="r">${join(p(c.market, 2))}</td>` +
        `<td class="r">${join(c.households != null ? 'ménages ' + p(c.households) : null, c.model != null ? 'Cleveland ' + p(c.model, 2) : null)}</td>` +
        `<td class="r">${join(p(c.last, d), c.now != null ? 'GDPNow ' + p(c.now) : null)}</td></tr>`; }).join('');
    return `<div class="acard wide"><h3>Projections à prendre en compte <small class="muted">— Fed, Fonds monétaire international (FMI), marché, ménages${r.imfUpdated ? ' ; FMI lu le ' + esc(date(r.imfUpdated)) : ''}</small></h3>` +
      `<div class="mwscroll"><table class="t mwtable mmcons"><tr><th></th><th class="r">Fed (médiane des membres)</th><th class="r">FMI</th><th class="r">Marché</th>` +
      `<th class="r">Attentes à un an</th><th class="r">Dernier chiffre</th></tr>${body}</table></div>` +
      `<ol class="mmfoot">${notes.map(n => `<li>${esc(n)}</li>`).join('')}</ol>` +
      '<div class="note">Les mesures diffèrent d\'une source à l\'autre (notes ci-dessus) : compare les sens et les écarts plutôt que les décimales. Le FMI publie ses perspectives en avril et en octobre (mises à jour en janvier et en juillet).</div></div>';
  }
  function mediumCard(r) {
    const mt = r.medium || {};
    const groups = {};
    (mt.items || []).forEach(it => (groups[it.group] = groups[it.group] || []).push(it));
    const tables = Object.entries(groups).map(([g, items]) => `<div class="sect">${esc(g)}</div><table class="t">` + items.map(it =>
      `<tr><td>${esc(it.name)}${it.note ? `<div class="muted small">${esc(it.note)}</div>` : ''}</td><td class="r nowrap"><b>${num(it.value, it.d)}</b>${esc(unit(it.unit))}</td>` +
      `<td class="r nowrap small">${it.change == null ? '' : `${sg(it.change, it.cd != null ? it.cd : it.changeUnit === 'pb' || it.changeUnit === 'Md$' ? 0 : it.changeUnit === '%' ? 1 : 2)}${esc(unit(it.changeUnit))}<div class="muted">${esc(it.changeLabel || '')}</div>`}</td></tr>`).join('') + '</table>').join('');
    return `<div class="acard"><h3>Vision à moyen terme <small class="muted">— 3 à 12 mois</small></h3>` +
      (mt.lines || []).map(l => `<p class="small">${esc(l)}</p>`).join('') + `<div id="mmRec" class="mwpath"></div>` + tables + '</div>';
  }
  function regimeCard(r) {
    const g = r.regime || {}, st = r.regimeStudy;
    const study = st && st.rows && st.rows.length ? `<div class="sect">Le bitcoin le mois suivant, selon le régime <span class="muted small">(${esc(st.from || '')} → ${esc(st.to || '')})</span></div><div class="mwscroll"><table class="t">` +
      `<tr><th>Régime</th><th class="r">Mois</th><th class="r">Moyenne</th><th class="r">En hausse</th><th>Verdict</th></tr>` +
      st.rows.map(x => `<tr><td>${esc(QL[x.quad] || x.label)}</td><td class="r">${x.n}</td><td class="r ${x.mean > 0 ? 'up' : x.mean < 0 ? 'dn' : ''}">${x.mean == null ? '—' : sg(x.mean, 1) + ' %'}</td>` +
        `<td class="r">${x.hit == null ? '—' : num(x.hit, 0) + ' %'}</td><td class="small ${/net/.test(x.verdict) ? 'amb' : 'muted'}">${esc(x.verdict)}</td></tr>`).join('') + `</table></div><div class="note">${esc(st.note || '')}</div>` : '';
    return `<div class="acard"><h3>Régime : croissance et inflation <small class="muted">— trajet sur 12 mois</small></h3>` +
      (g.label ? `<div class="mwregime">${esc(g.label)}</div><div class="muted small">${esc(g.text || '')}</div>` : '<div class="muted">Pas assez de chiffres officiels.</div>') +
      `<div id="mmQuad" class="mwq"></div>${study}</div>`;
  }
  function scenariosCard(r) {
    const sc = r.scenarios || [];
    if (!sc.length) return '';
    return `<div class="acard wide"><h3>Scénarios et déclencheurs <small class="muted">— ce qui ferait basculer d'un scénario à l'autre, et quand le vérifier</small></h3><div class="mmscen">` +
      sc.map(s => `<div class="mmsc ${s.effect > 0 ? 'good' : s.effect < 0 ? 'bad' : ''}"><div class="mmsct">${esc(s.title)}</div><p class="small">${esc(s.text)}</p><div class="sect">Déclencheurs</div>` +
        `<ul class="mwnext">${s.triggers.map(t => `<li class="small">${esc(t)}</li>`).join('')}</ul></div>`).join('') + '</div></div>';
  }
  function eventsCard(r) {
    const ev = r.events || [];
    if (!ev.length) return `<div class="acard wide"><h3>Le mois en chiffres : annonces</h3><div class="muted">Aucune annonce importante enregistrée pour ce mois${r.reconstructed ? ' (le calendrier ne remonte que depuis l\'installation du terminal)' : ''}.</div></div>`;
    const rows = ev.map(e => `<tr><td class="nowrap">${esc(day(e.t))}</td><td><b>${esc(e.label)}</b> <span class="pill">${esc(e.country)}</span></td><td class="r">${esc(e.forecast || '—')}</td>` +
      `<td class="r">${e.actual ? `<b>${esc(e.actual.text)}</b>` : '<span class="muted small">non fourni</span>'}</td>` +
      `<td style="width:18%">${e.z == null ? '' : Charts.dvBar(e.z, 3, e.cat === 'inflation' ? '#ff6b6b' : '#9aa0ae', e.cat === 'inflation' ? '#3ddc97' : '#9aa0ae')}</td><td class="mwread small">${esc(e.read || '')}</td></tr>`).join('');
    return `<div class="acard wide"><h3>Le mois en chiffres : annonces face au consensus</h3><div class="mwscroll"><table class="t mwtable">` +
      `<tr><th>Quand</th><th>Annonce</th><th class="r">Consensus</th><th class="r">Publié</th><th>Écart</th><th>Ce que cela veut dire</th></tr>${rows}</table></div></div>`;
  }
  const chgUnit = (u, v) => ({'%': ' point', indice: ' point', points: ' point', point: ' point', 'Md$': ' Md$', milliers: ' milliers', millions: ' million', '$': ' $'}[u] || '') +
    (Math.abs(v) >= 2 && ['%', 'indice', 'points', 'point'].includes(u) ? 's' : '');
  function themesCard(r) {
    const th = (r.themes || []).filter(t => t.items.length);
    if (!th.length) return '';
    const rows = th.map(t => `<tr><td colspan="3" class="sect">${esc(t.title)}</td></tr>` + t.items.slice(0, 4).map(it => `<tr><td>${esc(it.name)}</td>` +
      `<td class="r nowrap"><b>${num(it.value, it.d)}</b>${esc(unit(it.unit))}</td><td class="r nowrap small">${it.monthChange == null || Math.abs(it.monthChange) < 1e-9 ? '<span class="muted">inchangé</span>' : sg(it.monthChange, it.cd) + esc(chgUnit(it.unit, it.monthChange))}</td></tr>`).join('')).join('');
    return `<div class="acard"><h3>Tableau de bord <small class="muted">— variation depuis le début du mois</small></h3><table class="t">${rows}</table></div>`;
  }
  function marketsCard(r) {
    const m = r.markets || [];
    if (!m.length) return '';
    return `<div class="acard"><h3>Marchés sur le mois</h3><table class="t">` + m.map(x => `<tr><td>${esc(x.name)}</td><td class="r nowrap ${x.unit === 'pb' ? '' : x.chg > 0 ? 'up' : x.chg < 0 ? 'dn' : ''}">` +
      `${x.unit === 'pb' ? sg(x.chg, 0) + ' pb' : sg(x.chg, 1) + ' %'}</td></tr>`).join('') + '</table><div class="note">pb = point de base (0,01 point de taux).</div></div>';
  }
  function banksCard(r) {
    const b = r.banks;
    const KEYS = [['cuts', 'Baisses de la Fed (12 mois)'], ['fedEnd', 'Taux Fed fin d\'année proch.'], ['us10y', 'Taux 10 ans fin d\'année'], ['recession', 'Récession (12 mois)'],
                  ['spx', 'Objectif S&P 500'], ['dollar', 'Dollar'], ['crypto', 'Bitcoin et cryptos']];
    let body = '';
    if (b) {
      const rows = (b.rows || []).map(x => `<tr><td><b>${esc(x.bank)}</b><div class="muted small">${esc(x.date || '')}</div></td>${KEYS.map(([k]) => `<td class="small">${esc(x[k] || '—')}</td>`).join('')}` +
        `<td class="small">${x.source ? link(x.source, 'source', webUrl) : ''}</td></tr>`).join('');
      body = (rows ? `<div class="mwscroll"><table class="t mwtable"><tr><th>Banque</th>${KEYS.map(([, n]) => `<th>${esc(n)}</th>`).join('')}<th></th></tr>${rows}</table></div>` :
        '<div class="muted small">Claude n\'a pas trouvé de rapport chiffré exploitable cette fois.</div>') +
        `<div class="mwcomment">${esc(b.text)}</div><div class="note">Recherche du ${esc(paris(b.t, {day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit'}))} · coût ${num(b.usd, 3)} $ · ${esc(b.model || '')}. ` +
        'Les chiffres des banques viennent de leurs publications trouvées sur le web : vérifie la source avant de t\'en servir.</div>';
    } else body = '<div class="muted small">Pas encore de recherche pour ce mois.</div>';
    return `<div class="acard wide"><h3>Rapports des banques et discussion de la Fed <small class="muted">— recherche sur le web par Claude, à partir de cette analyse</small></h3>${body}` +
      `<div style="margin-top:8px"><button id="mmAsk" class="primary">${b ? 'Refaire la recherche' : 'Lancer la recherche de Claude'}</button> <span id="mmAskOut" class="muted small">` +
      'Utilise ta clé API Claude (Réglages → 7) : quelques dizaines de centimes par recherche (une dizaine de recherches sur le web).</span></div></div>';
  }
  function render() {
    const r = data, body = root.querySelector('#mmBody');
    if (!r) return;
    const src = r.sources || {}, errs = Object.entries(src.errors || {}).map(([k, v]) => `${k} : ${v}`), fe = Object.keys(src.fredErrors || {});
    root.querySelector('#mmInfo').textContent = (r.current ? 'mois en cours, recalculé toutes les 10 minutes' : r.reconstructed ? 'établi après coup' : 'version archivée') +
      ` · ${paris(r.built, {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'})}`;
    body.className = '';
    body.innerHTML =
      (!r.hasFred ? '<div class="acard warnbox">Les chiffres officiels américains (base FRED) ne sont pas encore arrivés ou sont injoignables : l\'analyse est incomplète. Le terminal réessaie toutes les 3 heures.</div>' : '') +
      (errs.length || fe.length ? `<div class="note">Sources en difficulté : ${esc(errs.concat(fe.length ? [`FRED (${fe.length} série${fe.length > 1 ? 's' : ''} : ${fe.slice(0, 4).join(', ')})`] : []).join(' ; '))}</div>` : '') +
      `<h2 class="mwtitle">Analyse macro de ${esc(r.label)}${r.current ? ' <span class="pill">en cours</span>' : ''}</h2>` +
      hero(r) + `<div class="mwgrid">${fedCard(r)}${sepCard(r)}${commsCard(r)}</div>` + statementCard(r) + consensusCard(r) +
      `<div class="mwgrid">${mediumCard(r)}${regimeCard(r)}</div>` + scenariosCard(r) + eventsCard(r) + `<div class="mwgrid">${themesCard(r)}${marketsCard(r)}</div>` + banksCard(r) +
      '<div class="note">Sources : base FRED de la Réserve fédérale de Saint-Louis (chiffres officiels et projections des membres de la Fed), site de la Fed (calendrier des réunions' +
      (src.calendarSource ? ' : ' + esc(src.calendarSource) : '') + ', communiqués, comptes rendus, discours), Fonds monétaire international (perspectives de l\'économie mondiale), ' +
      'calendrier ForexFactory (consensus), Yahoo Finance et Binance (marchés). Probabilité de récession : modèle publié par la Fed de New York, appliqué à la pente 10 ans − 3 mois.</div>';
    const q = root.querySelector('#mmQuad'), p = root.querySelector('#mmPath'), rec = root.querySelector('#mmRec');
    const tr = (r.regime || {}).trail || [];
    if (q) Charts.quadrant(q, tr.map((x, k) => ({...x, label: k === tr.length - 1 ? 'fin de la période' : paris(x.t, {month: 'long', year: 'numeric'})})), {quads: QS, long: QL, nowLabel: r.current ? 'maintenant' : 'fin du mois'});
    if (p) Charts.ratePath(p, r.fed || {});
    const rp = (r.medium || {}).recession || [];
    if (rec && rp.length > 2) Charts.line(rec, {series: [{name: 'Probabilité de récession dans 12 mois', color: '#d95926', pts: rp.map(x => [Date.parse(x.ym + '-01T00:00:00Z'), x.prob])}], height: 150,
      xFmt: v => new Date(v).toLocaleDateString('fr-FR', {month: 'short', year: '2-digit'}), yFmt: v => Math.round(v) + ' %', xTicks: 4});
  }
  async function ask() {
    const b = root.querySelector('#mmAsk'), out = root.querySelector('#mmAskOut');
    b.disabled = true; out.className = 'muted small'; out.textContent = 'Claude lit l\'analyse et cherche les rapports des banques et la discussion de la Fed… (1 à 3 minutes)';
    try {
      const r = await LT.api('/api/macromonth/research', {month: data.month});
      if (!r.ok) { out.className = 'dn small'; out.textContent = r.answer || 'Échec.'; b.disabled = false; return; }
      await load(true);
    } catch (e) { out.className = 'dn small'; out.textContent = 'Erreur : ' + e.message; b.disabled = false; }
  }
  return {init, show, hide, load};
})();
