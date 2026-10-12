// Panneaux de droite : Lecture, Niveaux, Compte (regles Lucid), Plan (calculateur), Footprint.
// Les formulaires sont construits UNE fois (sinon un rafraichissement effacerait ce que tu es en train de taper) ; seules les zones dynamiques sont redessinees.
const Panels = (() => {
  'use strict';
  const {fmt, sign, usd, susd, pct, esc, cls, $, $$, api, toast, debounce} = U;
  let cb = {};
  let lastField = 'entry';
  let showRounds = false;
  const GROUP_COLOR = {veille: '#f5a97f', nuit: '#b794f6', seance: '#5eead4', rond: '#6b7280'};

  const gauge = (frac, kind = '', marker = null) =>
    `<div class="bar ${kind}"><span style="width:${Math.max(0, Math.min(1, frac)) * 100}%"></span>${marker != null ? `<em style="left:${marker * 100}%"></em>` : ''}</div>`;
  const kv = (k, v, c = '') => `<div class="kv"><span>${k}</span><b class="${c}">${v}</b></div>`;

  // ======================================================= Lecture
  function lecture(c, st) {
    const host = $('#tab-lecture');
    if (!c || !c.ready) { host.innerHTML = `<div class="card muted">${esc(c && c.notes && c.notes[0] ? c.notes[0].text : 'En attente des premières transactions…')}</div>`; return; }
    const v = c.vwap, fl = c.flow, rg = c.range, ib = c.ib;
    let top = '';
    top += kv('Phase', esc(c.phase.label));
    top += kv('ATR 1 min · 5 min', `${fmt(c.atr1, 1)} · ${fmt(c.atr5, 1)} pts`);
    if (v) top += kv(`VWAP ${v.scope}`, `${fmt(v.v, 2)} <small>${sign(v.z, 1)} σ</small>`, v.z > 0.25 ? 'pos' : v.z < -0.25 ? 'neg' : '');
    if (ib) top += kv(`IB${ib.done ? '' : ' (en cours)'}`, `${fmt(ib.lo, 2)} – ${fmt(ib.hi, 2)}`);
    if (c.valueAreaPrev) top += kv('Zone de valeur veille', `${fmt(c.valueAreaPrev.val, 2)} – ${fmt(c.valueAreaPrev.vah, 2)}`);
    let gauges = '';
    if (fl) {
      const b15 = 50 * (1 + fl.imb15);
      gauges += `<div class="small">Achats agressifs, 15 min : <b>${fmt(b15, 0)} %</b> (5 min : ${fmt(50 * (1 + fl.imb5), 0)} %)</div>${gauge(b15 / 100, b15 > 54 ? '' : b15 < 46 ? 'bad' : 'acc', 0.5)}`;
    }
    if (rg) gauges += `<div class="small">Amplitude de la séance : <b>${fmt(rg.today, 0)} pts</b> sur ${fmt(rg.adr, 0)} de moyenne (${rg.n} séances)</div>${gauge(rg.ratio / 1.5, rg.ratio >= 1 ? 'warn' : 'acc', 1 / 1.5)}`;
    const marks = (c.marks || []).map(m => `<div class="kv"><span>${esc(m.label)}</span><b>${m.paris} <small>dans ${m.in} min</small></b></div>`).join('');
    const events = (c.events || []).map(e => `<div class="kv"><span>${esc(e.name)}</span><b>${e.paris} <small>${esc(e.impactLabel)}</small></b></div>`).join('');
    const notes = c.notes.map(n => `<div class="note ${n.tone}"><i></i><div>${esc(n.text)}</div></div>`).join('');
    host.innerHTML = `<div class="card"><h2>Maintenant</h2><div class="grid2" style="grid-template-columns:1fr">${top}</div>${gauges}</div>`
      + `<div class="card"><h2>Lecture</h2>${notes}</div>`
      + (marks || events ? `<div class="card"><h2>Repères et annonces (heure de Paris)</h2>${marks}${events}${events ? '' : '<div class="small">Aucune annonce saisie : voir data_local/events.json</div>'}</div>` : '');
  }

  // ======================================================= Niveaux
  function levels(lv, price) {
    const host = $('#tab-levels');
    if (!lv || !lv.levels || !lv.levels.length) { host.innerHTML = '<div class="card muted">Pas encore de niveaux.</div>'; return; }
    const list = lv.levels.filter(x => showRounds || x.group !== 'rond');
    let rowsHtml = '', placed = false;
    const mk = x => `<tr class="lvl" data-price="${x.price}"><td><span class="dot" style="background:${GROUP_COLOR[x.group]}"></span>${esc(x.name)}</td><td>${fmt(x.price, 2)}</td>`
      + `<td class="${x.dist >= 0 ? 'pos' : 'neg'}">${sign(x.dist, 1)}</td><td class="muted">${fmt(x.usdNQ, 0)} $</td></tr>`;
    for (const x of list) {
      if (!placed && x.price < price) { rowsHtml += `<tr class="cur"><td>▶ Prix</td><td>${fmt(price, 2)}</td><td></td><td></td></tr>`; placed = true; }
      rowsHtml += mk(x);
    }
    if (!placed) rowsHtml += `<tr class="cur"><td>▶ Prix</td><td>${fmt(price, 2)}</td><td></td><td></td></tr>`;
    const zs = [...(lv.zones || [])].sort((a, b) => b.score - a.score).slice(0, 8).map(z =>
      `<tr class="lvl" data-price="${z.mid}"><td>${esc(z.names.slice(0, 3).join(' + '))}${z.names.length > 3 ? ' …' : ''}</td><td>${fmt(z.lo, 2)}${z.hi > z.lo ? '–' + fmt(z.hi, 2) : ''}</td>`
      + `<td class="${z.dist >= 0 ? 'pos' : 'neg'}">${sign(z.dist, 1)}</td><td><b>${z.score}</b></td></tr>`).join('');
    host.innerHTML = `<div class="card"><h2>Zones de confluence <small>plusieurs niveaux proches</small></h2>`
      + (zs ? `<table><tr><th>Niveaux</th><th>Prix</th><th>Dist.</th><th>Score</th></tr>${zs}</table>` : '<div class="muted">Aucune zone pour l\'instant.</div>')
      + `<div class="small" style="margin-top:6px">Ce n'est pas un signal : c'est une carte des endroits où le prix a plusieurs raisons de réagir. Sa valeur réelle sera mesurée avant qu'on s'y fie.</div></div>`
      + `<div class="card"><h2>Niveaux <label style="float:right;font-weight:400;text-transform:none"><input type="checkbox" id="showRounds" ${showRounds ? 'checked' : ''}> nombres ronds</label></h2>`
      + `<table><tr><th>Niveau</th><th>Prix</th><th>Dist. (pts)</th><th>1 NQ</th></tr>${rowsHtml}</table>`
      + `<div class="small" style="margin-top:6px">Clique une ligne pour reprendre son prix dans le calculateur (champ « ${lastField === 'entry' ? 'entrée' : lastField === 'stop' ? 'stop' : lastField === 't1' ? 'objectif 1' : 'objectif 2'} »).</div></div>`;
    const sr = $('#showRounds', host);
    if (sr) sr.onchange = () => { showRounds = sr.checked; levels(lv, price); };
    $$('tr.lvl', host).forEach(tr => tr.onclick = () => {
      const f = $(`#planForm [name=${lastField}]`);
      if (f) { f.value = Number(tr.dataset.price).toFixed(2); f.dispatchEvent(new Event('input', {bubbles: true})); toast(`Prix ${fmt(Number(tr.dataset.price), 2)} copié dans le calculateur`); }
    });
  }

  // ======================================================= Compte
  const STATUS = {ok: ['EN RÈGLE', 'ok'], warn: ['ATTENTION', 'warn'], danger: ['DANGER', 'bad'], breached: ['PLANCHER ATTEINT', 'bad'], passed: ['ÉVALUATION VALIDÉE', 'ok']};
  const RULE_FIELDS = [['profit_target', 'Cible de profit ($)'], ['max_drawdown', 'Perte maximale ($)'], ['lock_offset', 'Verrou du plancher : capital + ($)'],
    ['consistency_pct', 'Consistance : meilleur jour max (%)'], ['min_trading_days', 'Jours de trading minimum'], ['max_minis', 'Minis maximum'],
    ['max_micros', 'Micros maximum'], ['risk_per_trade', 'Risque max par trade ($)'], ['daily_stop', 'Stop quotidien ($)'],
    ['fee_NQ', 'Frais aller-retour NQ ($)'], ['fee_MNQ', 'Frais aller-retour MNQ ($)']];

  function buildAccount() {
    $('#tab-account').innerHTML = `
      <div class="card" id="acctStatus"></div>
      <div class="card"><h2>Position ouverte <small>pour suivre le latent</small></h2><div id="posSummary" class="small"></div>
        <form id="posForm" class="f"><label>Sens<select name="side"><option value="long">Achat</option><option value="short">Vente</option></select></label>
          <label>Instrument<select name="root"><option>NQ</option><option>MNQ</option><option>ES</option><option>MES</option></select></label>
          <label>Quantité<input name="qty" inputmode="numeric" value="1"></label><label>Prix d'entrée<input name="entry" inputmode="decimal"></label>
          <div class="row wide" style="grid-column:1/3"><button type="submit" class="primary">Enregistrer</button><button type="button" id="posClear">Effacer</button>
            <button type="button" id="posClose" title="Préremplit le trade clôturé avec le dernier prix">Clôturer au dernier prix →</button></div></form></div>
      <div class="card"><h2>Trade clôturé</h2>
        <form id="tradeForm" class="f"><label>Sens<select name="side"><option value="long">Achat</option><option value="short">Vente</option></select></label>
          <label>Instrument<select name="inst"><option>NQ</option><option>MNQ</option><option>ES</option><option>MES</option></select></label>
          <label>Quantité<input name="qty" inputmode="numeric" value="1"></label><label>Setup (facultatif)<input name="setup" list="setups" maxlength="60"></label>
          <label>Entrée<input name="entry" inputmode="decimal"></label><label>Sortie<input name="exit" inputmode="decimal"></label>
          <label class="wide">Note<input name="note" maxlength="300"></label><datalist id="setups"></datalist>
          <div class="row" style="grid-column:1/3"><button type="submit" class="primary">Enregistrer le trade</button><button type="button" id="tradeUndo">Annuler la dernière saisie</button></div></form>
        <div class="err" id="tradeErr"></div></div>
      <div class="card"><h2>Aujourd'hui</h2><div id="acctRecords"></div></div>
      <div class="card"><h2>Journées</h2><div id="acctDays"></div></div>
      <div class="card"><h2>Statistiques du journal</h2><div id="acctPerf"></div></div>
      <div class="card"><details id="rules"><summary>Règles Lucid et limites personnelles</summary><form id="rulesForm" class="f"></form>
        <div class="row" style="margin-top:6px"><button id="rulesSave" class="primary" type="button">Enregistrer les règles</button></div><div id="rulesNote" class="small" style="margin-top:6px"></div></details></div>
      <div class="card"><details><summary>Reprendre un compte entamé · remettre à zéro</summary>
        <form id="adjForm" class="f"><label>Journée de trading<input name="day" placeholder="AAAA-MM-JJ"></label><label>P&amp;L net du jour ($)<input name="net" inputmode="decimal"></label>
          <label class="wide">Note<input name="note" placeholder="ex. reprise du compte"></label><div class="row" style="grid-column:1/3"><button class="primary" type="submit">Ajouter</button></div></form>
        <div class="err" id="adjErr"></div>
        <div class="row" style="margin-top:8px"><button id="resetBtn" class="danger" type="button">Effacer tout le journal…</button></div></details></div>`;
    // position
    const pf = $('#posForm'), tf = $('#tradeForm');
    const loadPos = () => {
      const p = (cb.getPos() || '').split(',');
      if (p.length === 4) { pf.side.value = p[0]; pf.root.value = p[1]; pf.qty.value = p[2]; pf.entry.value = p[3]; }
      else { pf.qty.value = '1'; pf.entry.value = ''; }
    };
    loadPos();
    pf.onsubmit = e => {
      e.preventDefault();
      const q = parseInt(pf.qty.value, 10), en = parseFloat(String(pf.entry.value).replace(',', '.'));
      if (!(q > 0) || !(en > 0)) { toast('Quantité et prix d\'entrée requis', true); return; }
      cb.setPos(`${pf.side.value},${pf.root.value},${q},${en}`); cb.refreshAccount(); toast('Position enregistrée');
    };
    $('#posClear').onclick = () => { cb.setPos(''); pf.entry.value = ''; cb.refreshAccount(); };
    $('#posClose').onclick = () => {
      const p = (cb.getPos() || '').split(',');
      if (p.length !== 4) { toast('Aucune position enregistrée', true); return; }
      tf.side.value = p[0]; tf.inst.value = p[1]; tf.qty.value = p[2]; tf.entry.value = p[3]; tf.exit.value = String(cb.getLast() || '');
      tf.setup.focus(); toast('Vérifie la sortie, ajoute le setup, puis « Enregistrer le trade »');
    };
    // trade
    tf.onsubmit = async e => {
      e.preventDefault();
      const f = new FormData(tf), num = k => parseFloat(String(f.get(k)).replace(',', '.'));
      $('#tradeErr').textContent = '';
      try {
        await api('/api/account/trade', {body: {inst: f.get('inst'), side: f.get('side'), qty: num('qty'), entry: num('entry'), exit: num('exit'), setup: f.get('setup'), note: f.get('note')}});
        const p = (cb.getPos() || '').split(',');
        if (p.length === 4 && p[1] === f.get('inst') && p[0] === f.get('side')) {                // meme position : elle diminue de la quantite sortie (ou se referme)
          const left = parseInt(p[2], 10) - num('qty');
          cb.setPos(left > 0 ? `${p[0]},${p[1]},${left},${p[3]}` : '');
          loadPos();
        }
        tf.entry.value = ''; tf.exit.value = ''; tf.note.value = '';
        toast('Trade enregistré'); cb.refreshAccount();
      } catch (err) { $('#tradeErr').textContent = err.message; }
    };
    $('#tradeUndo').onclick = async () => {
      try { const r = await api('/api/account/undo', {body: {}}); toast(r.undone ? 'Dernière saisie annulée' : 'Rien à annuler'); cb.refreshAccount(); } catch (err) { toast(err.message, true); }
    };
    // regles
    $('#rulesForm').innerHTML = RULE_FIELDS.map(([k, l]) => `<label>${l}<input name="${k}" inputmode="decimal"></label>`).join('');
    $('#rulesSave').onclick = async () => {
      const f = $('#rulesForm'), ch = {fee_rt: {}}, val = k => String(f[k].value).trim().replace(',', '.');
      for (const [k] of RULE_FIELDS) {
        if (k.startsWith('fee_')) { if (val(k) !== '') ch.fee_rt[k.slice(4)] = parseFloat(val(k)); continue; }
        ch[k] = val(k) === '' ? null : parseFloat(val(k));
      }
      for (const k of ['profit_target', 'max_drawdown', 'max_minis', 'max_micros', 'risk_per_trade', 'daily_stop']) if (ch[k] == null || isNaN(ch[k])) { delete ch[k]; }
      try { await api('/api/account/profile', {body: {changes: ch}}); toast('Règles enregistrées'); cb.refreshAccount(true); } catch (err) { $('#rulesNote').textContent = err.message; }
    };
    const af = $('#adjForm');
    af.onsubmit = async e => {
      e.preventDefault(); $('#adjErr').textContent = '';
      try { await api('/api/account/adjust', {body: {day: af.day.value.trim(), net: parseFloat(String(af.net.value).replace(',', '.')), note: af.note.value}}); af.net.value = ''; toast('Ajouté'); cb.refreshAccount(); }
      catch (err) { $('#adjErr').textContent = err.message; }
    };
    $('#resetBtn').onclick = async () => {
      if (!confirm('Effacer TOUT le journal du compte ? (une copie est gardée dans data_local)')) return;
      try { const r = await api('/api/account/reset', {body: {confirm: true}}); toast(`${r.erased} saisie(s) effacée(s)`); cb.refreshAccount(); } catch (err) { toast(err.message, true); }
    };
  }

  function account(a, perf) {
    if (!a) return;
    const [label, kind] = STATUS[a.status] || ['—', ''];
    const c = a.consistency, buf = a.bufferFrac;
    let cons = '';
    if (!c.rule) cons = '<div class="small">Pas de règle de consistance dans ce profil.</div>';
    else if (!(c.total > 0)) cons = `<div class="small">Consistance : le meilleur jour ne devra pas dépasser <b>${c.pct} %</b> du profit total. Profit total à atteindre pour valider : <b>${usd(c.needed)}</b> (la cible), en au moins 2 jours.</div>`;
    else {
      const ratio = c.ratio, ok = c.ok;
      cons = `<div class="small">Meilleur jour ${usd(c.best)} sur un total de ${usd(c.total)} : <b class="${ok ? 'pos' : 'neg'}">${ratio == null ? '—' : pct(ratio)}</b> (maximum ${c.pct} %) ${ratio == null ? '' : ok ? '✓' : '✗'}</div>`
        + gauge(ratio == null ? 0 : ratio, ok ? '' : 'bad', c.pct / 100)
        + `<div class="small">Profit total à atteindre pour valider : <b>${usd(c.needed)}</b>${c.needed > a.target ? ' <span class="amb">(plus que la cible, à cause du meilleur jour)</span>' : ''}</div>`
        + `<div class="small">Aujourd'hui : gain maximal pour que la journée reste sous ${c.pct} % du total : <b>${usd(c.todayCap)}</b> ${c.todayCap === 0 ? '(premier jour : la consistance se valide sur l\'ensemble des jours)' : ''}</div>`;
    }
    $('#acctStatus').innerHTML = `<h2>${esc(a.name)} <span class="badge ${kind}">${label}</span></h2>`
      + kv('Solde réalisé', usd(a.balance, 2)) + kv('Equity (avec le latent)', usd(a.equity, 2), cls(a.openPnl))
      + kv('Plancher du compte', usd(a.floor, 2) + (a.locked ? ' <small>verrouillé</small>' : ''))
      + (a.locked ? '' : '<div class="small">Le plancher suit ton meilleur solde de fin de journée (jusqu\'à ' + usd(a.start + a.profile.lock_offset) + ').</div>')
      + `<div style="margin-top:6px"><b>Marge avant le plancher : ${usd(a.buffer, 0)}</b> <small>${pct(buf)} de la perte maximale</small></div>`
      + gauge(buf, a.status === 'danger' || a.status === 'breached' ? 'bad' : a.status === 'warn' ? 'warn' : '')
      + `<div style="margin-top:6px">Objectif : <b>${susd(a.profit)}</b> sur ${usd(a.target)} <small>reste ${usd(a.targetLeft)}</small></div>` + gauge(a.progress, 'acc')
      + `<div style="margin-top:6px">${cons}</div>`
      + `<div style="margin-top:8px">Aujourd'hui : <b class="${cls(a.dayPnl)}">${susd(a.dayPnl)}</b> <small>stop quotidien −${usd(a.dailyStop)}${a.dailyStopHit ? ' — ATTEINT' : ` : reste ${usd(a.dailyStopLeft)}`}</small></div>`
      + gauge(a.dayPnl < 0 ? Math.min(1, -a.dayPnl / a.dailyStop) : 0, a.dailyStopHit ? 'bad' : 'warn');
    $('#posSummary').innerHTML = a.position ? `<b>${a.position.side === 'long' ? 'Achat' : 'Vente'} ${a.position.qty} ${a.position.root}</b> à ${fmt(a.position.entry, 2)} · latent <b class="${cls(a.position.pnl)}">${susd(a.position.pnl, 2)}</b>`
      : 'Aucune. Saisis ta position pour que la marge tienne compte du latent.';
    $('#acctRecords').innerHTML = a.records.length ? `<table><tr><th>Trade</th><th>Pts</th><th>Net</th><th></th></tr>${a.records.slice().reverse().map(r =>
      r.kind === 'trade' ? `<tr><td>${r.side === 'long' ? '▲' : '▼'} ${r.qty} ${r.inst} ${fmt(r.entry, 2)}→${fmt(r.exit, 2)}${r.setup ? ' <small>' + esc(r.setup) + '</small>' : ''}</td><td class="${cls(r.pts)}">${sign(r.pts, 2)}</td><td class="${cls(r.net)}">${susd(r.net, 2)}</td><td><a href="#" data-del="${r.id}" title="Supprimer">✕</a></td></tr>`
        : `<tr><td>Ajustement ${esc(r.note || '')}</td><td></td><td class="${cls(r.net)}">${susd(r.net, 2)}</td><td><a href="#" data-del="${r.id}">✕</a></td></tr>`).join('')}</table>` : '<div class="muted">Aucun trade aujourd\'hui.</div>';
    $$('#acctRecords [data-del]').forEach(el => el.onclick = async e => { e.preventDefault(); try { await api('/api/account/delete', {body: {id: Number(el.dataset.del)}}); cb.refreshAccount(); } catch (err) { toast(err.message, true); } });
    let cum = 0;
    $('#acctDays').innerHTML = a.days.length ? `<table><tr><th>Jour</th><th>P&amp;L net</th><th>Cumul</th></tr>${a.days.map(d => { cum += d.pnl; return `<tr><td>${d.day}${d.pnl === a.bestDay && d.pnl > 0 ? ' ★' : ''}</td><td class="${cls(d.pnl)}">${susd(d.pnl, 2)}</td><td class="${cls(cum)}">${susd(cum, 2)}</td></tr>`; }).join('')}</table>`
      + `<div class="small">★ meilleur jour (celui qui compte pour la consistance)</div>` : '<div class="muted">Pas encore de journée.</div>';
    if (perf) {
      const g = perf.all;
      let html;
      if (!g.n) html = '<div class="muted">Aucun trade saisi.</div>';
      else {
        html = kv('Trades', g.n) + kv('Gagnants', pct(g.winRate)) + kv('Gain moyen · perte moyenne', `${susd(g.avgWin)} · ${susd(g.avgLoss)}`)
          + kv('Espérance par trade', susd(g.expectancy, 2), cls(g.expectancy)) + kv('Facteur de profit', g.profitFactor == null ? '—' : fmt(g.profitFactor, 2))
          + kv('Frais payés', usd(g.fees));
        const setups = Object.entries(perf.bySetup);
        if (setups.some(([k]) => k !== '(sans setup)')) {
          html += `<table style="margin-top:6px"><tr><th>Setup</th><th>N</th><th>Gagn.</th><th>Espérance</th></tr>${setups.map(([k, st]) =>
            `<tr><td>${esc(k)}</td><td>${st.n}</td><td>${pct(st.winRate)}</td><td class="${cls(st.expectancy)}">${susd(st.expectancy, 2)}</td></tr>`).join('')}</table>`;
        }
      }
      $('#acctPerf').innerHTML = html;
      const dl = $('#setups');
      if (dl) dl.innerHTML = Object.keys(perf.bySetup).filter(k => k !== '(sans setup)').map(k => `<option value="${esc(k)}">`).join('');
    }
    const rf = $('#rulesForm'), p = a.profile;
    if (rf && !rf.contains(document.activeElement)) {
      const vals = {profit_target: p.profit_target, max_drawdown: p.max_drawdown, lock_offset: p.lock_offset, consistency_pct: p.consistency_pct, min_trading_days: p.min_trading_days,
        max_minis: p.max_minis, max_micros: p.max_micros, risk_per_trade: p.risk_per_trade, daily_stop: p.daily_stop, fee_NQ: p.fee_rt.NQ, fee_MNQ: p.fee_rt.MNQ};
      for (const k in vals) rf[k].value = vals[k] == null ? '' : vals[k];
      $('#rulesNote').innerHTML = `<b>À vérifier sur le site de Lucid :</b> ${a.toVerify.map(esc).join(' · ')}. Un champ vide = pas de règle. Les valeurs « risque par trade » et « stop quotidien » sont TES limites, pas celles de Lucid.`;
    }
  }

  // ======================================================= Plan
  function buildPlan() {
    $('#tab-plan').innerHTML = `<div class="card"><h2>Calculateur de position</h2>
      <form id="planForm" class="f" autocomplete="off">
        <label>Sens<select name="side"><option value="long">Achat</option><option value="short">Vente</option></select></label>
        <label>Instrument de référence<select name="root"><option>NQ</option><option>ES</option></select></label>
        <label>Entrée<input name="entry" inputmode="decimal"></label><label>Risque ($)<input name="risk" inputmode="decimal"></label>
        <label>Stop (prix)<input name="stop" inputmode="decimal"></label><label>Stop (pts)<input name="sp" inputmode="decimal"></label>
        <label>Objectif 1 (prix)<input name="t1" inputmode="decimal"></label><label>Objectif 1 (pts)<input name="p1" inputmode="decimal"></label>
        <label>Objectif 2 (prix)<input name="t2" inputmode="decimal"></label><label>Objectif 2 (pts)<input name="p2" inputmode="decimal"></label>
        <div class="row" style="grid-column:1/3"><button type="button" id="planLast">Entrée = dernier prix</button><button type="button" id="planClear">Vider</button></div>
      </form>
      <div class="small" style="margin-top:6px">Saisis le stop en prix <i>ou</i> en points (l'autre se remplit). Le risque inclut les frais aller-retour. Tu peux aussi cliquer un niveau dans l'onglet Niveaux.</div></div>
      <div id="planOut"></div>`;
    const f = $('#planForm');
    const num = k => { const v = parseFloat(String(f[k].value).replace(',', '.')); return isNaN(v) ? null : v; };
    const sgn = () => f.side.value === 'long' ? 1 : -1;
    const set = (k, v) => { f[k].value = v == null ? '' : (Math.round(v * 100) / 100).toString(); };
    const pairs = [['stop', 'sp', -1], ['t1', 'p1', 1], ['t2', 'p2', 1]];
    const calc = debounce(async () => {
      const entry = num('entry'), stop = num('stop');
      const out = $('#planOut');
      if (entry == null || stop == null) { out.innerHTML = ''; return; }
      const t = [num('t1'), num('t2')].filter(x => x != null).join(',');
      try {
        const q = new URLSearchParams({side: f.side.value, entry, stop, targets: t, root: f.root.value});
        if (num('risk') != null) q.set('risk', num('risk'));
        const pos = cb.getPos(); if (pos) q.set('pos', pos);
        planResult(await api('/api/plan?' + q), entry);
      } catch (err) { out.innerHTML = `<div class="card"><div class="err">${esc(err.message)}</div></div>`; }
    }, 250);
    // chaque niveau (stop, objectifs) a deux ecritures : en prix ou en points depuis l'entree. On retient celle que tu as saisie en dernier et on recalcule
    // l'autre quand l'entree ou le sens changent (des points restent des points, un prix saisi reste ce prix).
    const src = {stop: 'price', t1: 'price', t2: 'price'};
    f.addEventListener('input', e => {
      const n = e.target.name;
      if (['entry', 'stop', 't1', 't2'].includes(n)) lastField = n;
      for (const [pk, dk] of pairs) { if (n === pk) src[pk] = 'price'; if (n === dk) src[pk] = 'pts'; }
      const entry = num('entry');
      if (entry != null) for (const [pk, dk, d] of pairs) {
        if (src[pk] === 'pts' && num(dk) != null) { if (n !== pk) set(pk, entry + sgn() * d * Math.abs(num(dk))); }
        else if (num(pk) != null && n !== dk) set(dk, Math.abs(num(pk) - entry));
      }
      calc();
    });
    f.addEventListener('focusin', e => { if (['entry', 'stop', 't1', 't2'].includes(e.target.name)) lastField = e.target.name; });
    $('#planLast').onclick = () => { f.entry.value = (cb.getLast() || '').toString(); f.entry.dispatchEvent(new Event('input', {bubbles: true})); };
    $('#planClear').onclick = () => { for (const k of ['entry', 'stop', 'sp', 't1', 'p1', 't2', 'p2']) f[k].value = ''; $('#planOut').innerHTML = ''; };
  }

  function planResult(p, entry) {
    const names = Object.keys(p.sizes);
    const head = `<tr><th></th>${names.map(n => `<th>${n}</th>`).join('')}</tr>`;
    const row = (label, fn) => `<tr><td>${label}</td>${names.map(n => `<td>${fn(p.sizes[n], n)}</td>`).join('')}</tr>`;
    let html = `<div class="card"><h2>${p.side === 'long' ? 'Achat' : 'Vente'} · stop ${fmt(p.stopPts, 2)} pts (${fmt(p.stopTicks, 0)} ticks)</h2><table>${head}`
      + row('Contrats', s => `<b>${s.qty}</b>${s.capped ? ' <small>plafond</small>' : ''}`)
      + row('Risque (frais inclus)', s => usd(s.riskUsd, 0))
      + row('Frais aller-retour', s => `${usd(s.feeUsd, 2)} <small>${fmt(s.feeTicks, 1)} tk</small>`);
    const nT = p.sizes[names[0]].targets.length;
    for (let i = 0; i < nT; i++) {
      html += row(`Objectif ${i + 1} · ${fmt(p.sizes[names[0]].targets[i].pts, 1)} pts`, s => s.targets[i] ? `${susd(s.targets[i].net, 0)} <small>${s.targets[i].r == null ? '' : fmt(s.targets[i].r, 2) + ' R'}</small>` : '—');
    }
    html += '</table>';
    html += (p.warnings || []).map(w => `<div class="warnbox">${esc(w)}</div>`).join('');
    html += `<div class="row" style="margin-top:8px">${names.map(n => p.sizes[n].qty ? `<button data-pos="${n}" data-qty="${p.sizes[n].qty}">Prendre la position : ${p.sizes[n].qty} ${n}</button>` : '').join('')}</div></div>`;
    $('#planOut').innerHTML = html;
    $$('#planOut [data-pos]').forEach(b => b.onclick = () => {
      cb.setPos(`${p.side},${b.dataset.pos},${b.dataset.qty},${entry}`); cb.refreshAccount(); const pf = $('#posForm');
      if (pf) { pf.side.value = p.side; pf.root.value = b.dataset.pos; pf.qty.value = b.dataset.qty; pf.entry.value = entry; }
      toast(`Position enregistrée : ${b.dataset.qty} ${b.dataset.pos} à ${fmt(entry, 2)} (suivi du latent)`);
    });
  }

  // ======================================================= Footprint
  function buildFp() {
    $('#tab-fp').innerHTML = '<div class="card"><h2>Footprint <small id="fpTf"></small></h2><div id="fpOut" class="grid2" style="align-items:start"></div>'
      + '<div class="small" style="margin-top:6px">Vendeurs agressifs (au bid) | prix | acheteurs agressifs (à l\'ask). Fond coloré = déséquilibre diagonal ≥ 3 : l\'acheteur d\'un prix contre le vendeur du prix juste en dessous (et inversement). Ligne claire = POC de la barre.</div></div>'
      + '<div class="card"><h2>Ruban</h2><div id="tape"></div></div>';
  }

  function footprint(fp, tape, tfLabel) {
    $('#fpTf').textContent = tfLabel;
    const out = $('#fpOut');
    if (!fp || !fp.bars.length) { out.innerHTML = '<div class="muted">Pas de barre.</div>'; return; }
    out.innerHTML = fp.bars.map(b => {
      const rows = b.rows.slice(0, 70).map(r => `<tr class="${r[3] & 4 ? 'poc' : ''}"><td class="s ${r[3] & 2 ? 'is' : ''}">${fmt(r[1], 0)}</td><td class="p">${fmt(r[0], 2)}</td><td class="b ${r[3] & 1 ? 'ib' : ''}">${fmt(r[2], 0)}</td></tr>`).join('');
      const more = b.rows.length > 70 ? `<div class="small">… ${b.rows.length - 70} prix de plus</div>` : '';
      return `<div><div class="small"><b>${U.hm(b.t, cb.tz())}</b> · vol ${fmt(b.v, 0)} · Δ <b class="${cls(b.delta)}">${sign(b.delta, 0)}</b></div><table class="fp"><tr><th>Vend.</th><th>Prix</th><th>Ach.</th></tr>${rows}</table>${more}`
        + (b.stacks.length ? `<div class="small">${b.stacks.map(s => `Pile ${s.side > 0 ? 'acheteuse' : 'vendeuse'} ${fmt(s.lo, 2)}–${fmt(s.hi, 2)}`).join('<br>')}</div>` : '') + '</div>';
    }).join('');
    $('#tape').innerHTML = `<table><tr><th>Heure (${cb.tz() === 'et' ? 'NY' : 'Paris'})</th><th>Qté</th><th>Prix</th></tr>${(tape || []).map(t =>
      `<tr><td>${U.hm(t.t / 1000, cb.tz())}</td><td class="${t.s > 0 ? 'pos' : 'neg'}">${t.s > 0 ? '▲' : '▼'} ${t.q}</td><td>${fmt(t.p, 2)}</td></tr>`).join('')}</table>`;
  }

  function init(callbacks) { cb = callbacks; buildAccount(); buildPlan(); buildFp(); }
  return {init, lecture, levels, account, footprint, planResult};
})();
