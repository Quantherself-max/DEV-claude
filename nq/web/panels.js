// Panneaux de droite : Lecture, Niveaux, Compte (regles Lucid), Plan (calculateur), Footprint.
// Les formulaires sont construits UNE fois (sinon un rafraichissement effacerait ce que tu es en train de taper) ; seules les zones dynamiques sont redessinees.
const Panels = (() => {
  'use strict';
  const {fmt, sign, usd, susd, pct, esc, cls, $, $$, api, toast, debounce, parseNum, store} = U;
  let cb = {};
  let lastField = 'entry';
  let showRounds = false;
  let lastProfile = null;       // profil du dernier état reçu (pour les textes qui dépendent des règles)
  const lockableNow = () => !!lastProfile && lastProfile.dd_mode === 'eod_trailing' && lastProfile.lock_offset != null;
  let replan = null;            // recalcule le plan affiché (posé par buildPlan) sans toucher aux champs
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
    ['daily_loss_limit', 'Limite de perte journalière (option d\'achat, $)'], ['consistency_pct', 'Consistance : meilleur jour max (%)'], ['min_trading_days', 'Jours de trading minimum'], ['max_minis', 'Minis maximum'],
    ['max_micros', 'Micros maximum'], ['risk_per_trade', 'Risque max par trade ($)'], ['daily_stop', 'Stop quotidien ($)'],
    ['fee_NQ', 'Frais aller-retour NQ ($)'], ['fee_MNQ', 'Frais aller-retour MNQ ($)']];

  function buildAccount() {
    $('#tab-account').innerHTML = `
      <div class="card" id="acctStatus"></div>
      <div class="card" id="stageCard"><h2>Étape du compte</h2><div id="stageBox" class="small"></div>
        <div class="row" style="margin-top:6px"><button id="fundedBtn" type="button" title="L'évaluation est validée : le compte financé est un nouveau compte, il repart du capital de départ">Évaluation validée → passer en compte financé</button></div></div>
      <div class="card" id="payoutCard" hidden><h2>Retraits <small>compte financé</small></h2><div id="payoutBox"></div>
        <form id="payoutForm" class="f" style="margin-top:8px"><label>Montant demandé ($, avant partage)<input name="amount" inputmode="decimal"></label><label>Note<input name="note" maxlength="300"></label>
          <div class="row" style="grid-column:1/3"><button type="submit" class="primary">Enregistrer le retrait demandé</button></div></form><div class="err" id="payoutErr"></div></div>
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
          <label>Durée du trade (s)<input name="hold" inputmode="decimal" placeholder="facultatif" title="Lucid signale un compte dont plus de 50 % des gains viennent de trades tenus 5 secondes ou moins"></label>
          <label>Note<input name="note" maxlength="300"></label><datalist id="setups"></datalist>
          <div class="row" style="grid-column:1/3"><button type="submit" class="primary">Enregistrer le trade</button><button type="button" id="tradeUndo">Annuler la dernière saisie</button></div></form>
        <div class="err" id="tradeErr"></div></div>
      <div class="card"><h2>Aujourd'hui</h2><div id="acctRecords"></div></div>
      <div class="card"><h2>Journées</h2><div id="acctDays"></div></div>
      <div class="card"><h2>Statistiques du journal</h2><div id="acctPerf"></div></div>
      <div class="card"><details id="rules"><summary>Règles Lucid et limites personnelles</summary><form id="rulesForm" class="f"></form>
        <div class="row" style="margin-top:6px"><button id="rulesSave" class="primary" type="button">Enregistrer les règles</button></div><div id="rulesErr" class="err"></div><div id="rulesNote" class="small" style="margin-top:6px"></div></details></div>
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
      const q = parseInt(pf.qty.value, 10), en = parseNum(pf.entry.value);
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
      const f = new FormData(tf), num = k => parseNum(f.get(k));
      $('#tradeErr').textContent = '';
      try {
        const hold = String(f.get('hold')).trim() === '' ? null : num('hold');
        if (hold !== null && isNaN(hold)) throw new Error('durée du trade invalide : un nombre de secondes est attendu');
        await api('/api/account/trade', {body: {inst: f.get('inst'), side: f.get('side'), qty: num('qty'), entry: num('entry'), exit: num('exit'), setup: f.get('setup'), note: f.get('note'), hold_s: hold}});
        const p = (cb.getPos() || '').split(',');
        if (p.length === 4 && p[1] === f.get('inst') && p[0] === f.get('side')) {                // meme position : elle diminue de la quantite sortie (ou se referme)
          const left = parseInt(p[2], 10) - num('qty');
          cb.setPos(left > 0 ? `${p[0]},${p[1]},${left},${p[3]}` : '');
          loadPos();
        }
        tf.entry.value = ''; tf.exit.value = ''; tf.note.value = ''; tf.hold.value = '';
        toast('Trade enregistré'); cb.refreshAccount();
      } catch (err) { $('#tradeErr').textContent = err.message; }
    };
    $('#tradeUndo').onclick = async () => {
      try { const r = await api('/api/account/undo', {body: {}}); toast(r.undone ? 'Dernière saisie annulée' : 'Rien à annuler'); cb.refreshAccount(); } catch (err) { toast(err.message, true); }
    };
    // regles
    $('#rulesForm').innerHTML = RULE_FIELDS.map(([k, l]) => `<label>${l}<input name="${k}" inputmode="decimal"></label>`).join('');
    $('#rulesForm').addEventListener('input', () => { $('#rulesForm').dataset.dirty = '1'; });          // saisie en cours : le rafraîchissement ne l'écrase pas
    $('#rulesSave').onclick = async () => {
      const f = $('#rulesForm'), ch = {fee_rt: {}}, kept = [];
      $('#rulesErr').textContent = '';
      for (const [k] of RULE_FIELDS) {
        const raw = String(f[k].value).trim(), fee = k.startsWith('fee_');
        if (raw === '') { if (!fee) ch[k] = null; continue; }
        const n = parseNum(raw);
        if (isNaN(n)) { $('#rulesErr').textContent = `${k} : « ${raw} » n'est pas un nombre`; return; }
        if (fee) ch.fee_rt[k.slice(4)] = n; else ch[k] = n;
      }
      for (const k of ['profit_target', 'max_drawdown', 'max_minis', 'max_micros', 'risk_per_trade', 'daily_stop']) if (ch[k] == null || isNaN(ch[k])) { delete ch[k]; kept.push(k); }
      try {
        await api('/api/account/profile', {body: {changes: ch}});
        delete f.dataset.dirty;
        toast(kept.length ? `Règles enregistrées ; champ vide ignoré, valeur actuelle conservée : ${kept.join(', ')}` : 'Règles enregistrées', kept.length > 0);
        cb.refreshAccount(true);
      } catch (err) { $('#rulesErr').textContent = err.message; }
    };
    const af = $('#adjForm');
    af.onsubmit = async e => {
      e.preventDefault(); $('#adjErr').textContent = '';
      try { await api('/api/account/adjust', {body: {day: af.day.value.trim(), net: parseNum(af.net.value), note: af.note.value}}); af.net.value = ''; toast('Ajouté'); cb.refreshAccount(); }
      catch (err) { $('#adjErr').textContent = err.message; }
    };
    $('#fundedBtn').onclick = async () => {
      if (!confirm('Passer en compte financé ?\n\nC\'est un NOUVEAU compte : le solde repart du capital de départ, la consistance disparaît, le palier de taille et les retraits s\'appliquent. (Annulable avec « Annuler la dernière saisie ».)')) return;
      try { await api('/api/account/funded', {body: {}}); toast('Compte financé : nouveau compte, solde de départ'); cb.refreshAccount(); } catch (err) { toast(err.message, true); }
    };
    const payf = $('#payoutForm');
    payf.onsubmit = async e => {
      e.preventDefault(); $('#payoutErr').textContent = '';
      try {
        const r = await api('/api/account/payout', {body: {amount: parseNum(payf.amount.value), note: payf.note.value}});
        payf.amount.value = ''; payf.note.value = ''; toast(lockableNow() ? 'Retrait enregistré : le plancher passe au niveau verrouillé' : 'Retrait enregistré'); cb.refreshAccount();
        if (r && r.warnings && r.warnings.length) $('#payoutErr').textContent = 'Enregistré, mais d\'après ton journal : ' + r.warnings.join(' ; ') + '. Vérifie tes saisies si Lucid n\'est pas du même avis.';
      } catch (err) { $('#payoutErr').textContent = err.message; }
    };
    $('#resetBtn').onclick = async () => {
      if (!confirm('Effacer TOUT le journal du compte ? (une copie est gardée dans data_local)')) return;
      try { const r = await api('/api/account/reset', {body: {confirm: true}}); toast(`${r.erased} saisie(s) effacée(s)`); cb.refreshAccount(); } catch (err) { toast(err.message, true); }
    };
  }

  function account(a, perf) {
    if (!a) return;
    lastProfile = a.profile;
    const capKey = a.stage + ':' + a.caps.minis + '/' + a.caps.micros;         // le palier ou l'étape change : le calcul du plan affiché (taille, bouton « Prendre la position ») doit suivre
    if (capKey !== account.capKey) {
      const first = account.capKey === undefined; account.capKey = capKey;
      const pf = $('#planForm');
      if (!first && pf && pf.entry.value && pf.stop.value && replan) replan();
    }
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
    const funded = a.stage === 'funded';
    const cap = a.caps || {};
    $('#acctStatus').innerHTML = `<h2>${esc(a.name)} <span class="badge ${kind}">${label}</span></h2>`
      + kv('Solde réalisé', usd(a.balance, 2)) + kv('Equity (avec le latent)', usd(a.equity, 2), cls(a.openPnl))
      + kv('Plancher du compte', usd(a.floor, 2) + (a.locked ? ' <small>verrouillé</small>' : ''))
      + (a.locked ? '' : a.profile.dd_mode === 'static' ? '<div class="small">Plancher fixe : il ne suit pas ton solde.</div>'
         : '<div class="small">Le plancher suit ton meilleur solde de fin de journée' + (a.profile.lock_offset == null ? ' (aucun verrou dans ce profil).' : ' (jusqu\'à ' + usd(a.start + a.profile.lock_offset) + ').') + '</div>')
      + `<div style="margin-top:6px"><b>Marge avant le plancher : ${usd(a.buffer, 0)}</b> <small>${pct(buf)} de la perte maximale</small></div>`
      + gauge(buf, a.status === 'danger' || a.status === 'breached' ? 'bad' : a.status === 'warn' ? 'warn' : '')
      + (funded ? `<div style="margin-top:6px">Profit sur le compte : <b class="${cls(a.profit)}">${susd(a.profit)}</b> <small>retraits déjà pris : ${usd(a.paid)}</small></div>`
                : `<div style="margin-top:6px">Objectif : <b>${susd(a.profit)}</b> sur ${usd(a.target)} <small>reste ${usd(a.targetLeft)}</small></div>` + gauge(a.progress, 'acc')
                  + `<div style="margin-top:6px">${cons}</div>`)
      + `<div class="small" style="margin-top:6px">Taille maximale : <b>${cap.minis} mini / ${cap.micros} micros</b>${cap.next ? ` jusqu'à ${usd(cap.next)} de profit (palier mis à jour en fin de séance)` : ''}</div>`
      + `<div style="margin-top:8px">Aujourd'hui : <b class="${cls(a.dayPnl)}">${susd(a.dayPnl)}</b> <small>stop quotidien −${usd(a.dailyStop)}${a.dailyStopHit ? ' — ATTEINT' : ` : reste ${usd(a.dailyStopLeft)}`}</small></div>`
      + gauge(a.dayPnl < 0 ? Math.min(1, -a.dayPnl / a.dailyStop) : 0, a.dailyStopHit ? 'bad' : 'warn')
      + (a.dll != null ? `<div class="small ${a.dllHit ? 'neg' : ''}">Limite journalière (option d'achat) : −${usd(a.dll)}${a.dllHit ? ' — ATTEINTE : verrouillé jusqu\'à la séance suivante, le compte survit' : ' (souple : bloque la séance, pas le compte)'}</div>` : '');
    // ----- etape et retraits -----
    $('#stageBox').innerHTML = funded
      ? `<b>Compte financé</b> depuis le ${esc(a.stageSince || '')}. Ses règles : pas de consistance, palier de taille, retraits.`
      : `<b>Évaluation</b>. ${a.passed ? '<span class="pos">Les conditions de validation sont remplies : quand Lucid a ouvert ton compte financé, passe à l\'étape suivante.</span>' : 'Quand Lucid valide ton évaluation, passe en compte financé.'}`;
    $('#fundedBtn').hidden = funded;
    $('#payoutCard').hidden = !funded;
    if (funded && a.payout) {
      const po = a.payout, chips = Array.from({length: Math.min(po.daysNeeded, 60)}, (_, i) => `<span class="dot" style="background:${i < po.daysOk.length ? 'var(--up)' : '#3a4052'}" title="${po.daysOk[i] || 'à gagner'}"></span>`).join('');
      const pr = a.profile, pc = x => String(+(x * 100).toFixed(2)).replace('.', ','), split = pc(pr.payout_split), capPct = pc(pr.payout_cap_pct);
      const lockable = pr.dd_mode === 'eod_trailing' && pr.lock_offset != null;
      let h = (po.left > 0 ? `<div class="small">Retrait n° <b>${po.done + 1}</b> · il en reste ${po.left} sur ${po.done + po.left} avant le Live</div>`
                           : `<div class="small"><b>${po.done} retraits faits</b> : le compte passe en Live au choix de Lucid (non modélisé ici).</div>`)
        + `<div style="margin-top:6px">Jours à ≥ ${usd(po.dayProfit)} dans ce cycle : ${chips} <b>${Math.min(po.daysOk.length, po.daysNeeded)} / ${po.daysNeeded}</b>${po.daysOk.length > po.daysNeeded ? ` <small>(${po.daysOk.length} jours qualifiants)</small>` : ''}</div>`
        + kv('Profit du cycle', susd(po.cycleProfit), cls(po.cycleProfit)) + kv('Profit sur le compte', usd(po.profitBasis))
        + kv('Plafond actuel', `${usd(Math.floor(po.cap + 1e-9))} <small>${capPct} % du profit, ${usd(pr.payout_cap)} maximum</small>`);
      if (po.eligible) {
        h += `<div style="margin-top:6px"><span class="badge ok">RETRAIT POSSIBLE</span> jusqu'à <b>${usd(po.max.amount)}</b> <small>soit ${usd(po.max.net)} pour toi (${split} %)</small></div>`
          + `<div class="small">Après ce retrait : solde ${usd(po.max.balance)}, plancher ${usd(po.max.floor)} ${lockable ? '<small>(il saute au niveau verrouillé dès la demande)</small>' : ''}, <b>marge ${usd(po.max.cushion)}</b>.</div>`
          + (po.min ? `<div class="small">Au minimum (${usd(po.minRequest)}) : marge ${usd(po.min.cushion)}.</div>` : '');
      } else {
        h += `<div style="margin-top:6px"><span class="badge warn">PAS ENCORE</span></div>` + po.why.map(w => `<div class="small">• ${esc(w)}</div>`).join('')
          + (po.profitForMin && po.done === 0 ? `<div class="small">Le premier retrait demande au moins ${usd(po.profitForMin)} de profit sur le compte : ${po.daysNeeded} jours à ${usd(po.dayProfit)} ne suffisent pas.</div>` : '');
      }
      h += `<div class="small" style="margin-top:6px">Hypothèses (non tranchées par l'article) : un jour compte net de frais et par séance ; le « ${capPct} % » porte sur le profit du compte.</div>`;
      $('#payoutBox').innerHTML = h;
    }
    $('#posSummary').innerHTML = a.position ? `<b>${a.position.side === 'long' ? 'Achat' : 'Vente'} ${a.position.qty} ${a.position.root}</b> à ${fmt(a.position.entry, 2)} · latent <b class="${cls(a.position.pnl)}">${susd(a.position.pnl, 2)}</b>`
      : 'Aucune. Saisis ta position pour que la marge tienne compte du latent.';
    $('#acctRecords').innerHTML = a.records.length ? `<table><tr><th>Trade</th><th>Pts</th><th>Net</th><th></th></tr>${a.records.slice().reverse().map(r =>
      r.kind === 'trade' ? `<tr><td>${r.side === 'long' ? '▲' : '▼'} ${r.qty} ${r.inst} ${fmt(r.entry, 2)}→${fmt(r.exit, 2)}${r.setup ? ' <small>' + esc(r.setup) + '</small>' : ''}</td><td class="${cls(r.pts)}">${sign(r.pts, 2)}</td><td class="${cls(r.net)}">${susd(r.net, 2)}</td><td><a href="#" data-del="${r.id}" title="Supprimer">✕</a></td></tr>`
        : r.kind === 'payout' ? `<tr><td>Retrait demandé ${esc(r.note || '')}</td><td></td><td class="neg">${susd(-r.amount, 2)}</td><td><a href="#" data-del="${r.id}" title="Supprimer">✕</a></td></tr>`
        : `<tr><td>Ajustement ${esc(r.note || '')}</td><td></td><td class="${cls(r.net)}">${susd(r.net, 2)}</td><td><a href="#" data-del="${r.id}">✕</a></td></tr>`).join('')}</table>` : '<div class="muted">Aucune saisie aujourd\'hui.</div>';
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
      const mi = a.micro;
      if (mi && mi.trades) {
        const sh = mi.shareMin;
        html += `<div class="small" style="margin-top:8px">Gains issus de trades tenus ${mi.seconds} s ou moins : <b class="${sh != null && sh >= 0.4 ? 'neg' : ''}">${sh == null ? '—' : pct(sh)}</b> `
          + `<small>(Lucid signale un compte au-delà de ${pct(mi.limit)})</small></div>` + gauge(sh || 0, sh >= 0.4 ? 'bad' : sh >= 0.3 ? 'warn' : 'acc', mi.limit)
          + (mi.unknown ? `<div class="small amb">${mi.unknown} trade(s) sans durée saisie : cette part est un minimum.</div>` : '');
      }
      $('#acctPerf').innerHTML = html;
      const dl = $('#setups');
      if (dl) dl.innerHTML = Object.keys(perf.bySetup).filter(k => k !== '(sans setup)').map(k => `<option value="${esc(k)}">`).join('');
    }
    const rf = $('#rulesForm'), p = a.profile;
    if (rf && !rf.contains(document.activeElement) && !rf.dataset.dirty) {
      const vals = {profit_target: p.profit_target, max_drawdown: p.max_drawdown, lock_offset: p.lock_offset, daily_loss_limit: p.daily_loss_limit, consistency_pct: p.consistency_pct, min_trading_days: p.min_trading_days,
        max_minis: p.max_minis, max_micros: p.max_micros, risk_per_trade: p.risk_per_trade, daily_stop: p.daily_stop, fee_NQ: p.fee_rt.NQ, fee_MNQ: p.fee_rt.MNQ};
      for (const k in vals) rf[k].value = vals[k] == null ? '' : vals[k];
      $('#rulesNote').innerHTML = `<b>À vérifier sur le site de Lucid :</b> ${a.toVerify.map(esc).join(' · ')}. Un champ vide = pas de règle (sauf cible, perte maximale, tailles, risque et stop : ils gardent leur valeur). Les valeurs « risque par trade » et « stop quotidien » sont TES limites, pas celles de Lucid.`
        + ((a.profileDropped || []).length ? ` <span class="neg">Réglages du fichier inutilisables, remis aux valeurs par défaut : ${a.profileDropped.map(esc).join(', ')} (l'original est gardé à côté, dans data_local).</span>` : '');
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
    const num = k => { const v = parseNum(f[k].value); return isNaN(v) ? null : v; };
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
    replan = calc;
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

  // ======================================================= Setups (signaux de scalping)
  const TAG_FR = {divergence: 'Divergence CVD', absorption: 'Absorption', stack: 'Pile de déséquilibres', va_edge: 'Bord de zone de valeur',
    vwap_band: 'Bande VWAP', zone: 'Zone de confluence', ib_break: 'Cassure IB', cvd_trend: 'Flux cumulé', phase: 'Phase'};

  function buildSetups() {
    const on = k => store.get(k, k === 'setupLines');
    $('#tab-setups').innerHTML = `<div class="card"><h2>Alertes <small>même quand l'onglet est fermé</small></h2>
      <label class="small" style="display:flex;gap:6px;align-items:center"><input type="checkbox" id="optSetupLines" style="width:auto"${on('setupLines') ? ' checked' : ''}> Tracer le meilleur setup sur le graphique (entrée, stop, objectifs)</label>
      <label class="small" style="display:flex;gap:6px;align-items:center;margin-top:4px"><input type="checkbox" id="optAlerts" style="width:auto"${on('alerts') ? ' checked' : ''}> Son + notification quand un setup atteint le score
        <input id="alertMin" inputmode="decimal" style="width:52px" value="${esc(String(store.get('alertMin', 55)))}"></label>
      <div class="small muted" style="margin-top:4px">Une alerte par setup nouveau (sens, type, entrée), au plus une par minute et par sens. Jamais pendant un blocage (plancher, 16 h 45).</div></div>
      <div id="setupOut"></div>`;
    const push = () => { if (cb.onSetupOpts) cb.onSetupOpts(); };
    $('#optSetupLines').onchange = e => { store.set('setupLines', e.target.checked); push(); };
    $('#optAlerts').onchange = e => {
      store.set('alerts', e.target.checked);
      if (e.target.checked && 'Notification' in window && Notification.permission === 'default') Notification.requestPermission().catch(() => {});
      push();
    };
    $('#alertMin').onchange = e => { const v = parseNum(e.target.value); store.set('alertMin', isNaN(v) ? 55 : Math.max(0, Math.min(100, v))); e.target.value = store.get('alertMin', 55); push(); };
  }

  function setups(d) {
    const host = $('#setupOut');
    if (!d || !d.ready) {
      host.innerHTML = `<div class="card muted">${esc(d && d.blocked && d.blocked[0] ? d.blocked[0] : 'En attente de barres suffisantes…')}</div>`;
      return;
    }
    let html = `<div class="card"><h2>Setups <small>${esc(d.tf || '')} · ${esc(d.phase || '')}</small></h2>`
      + kv('Prix', fmt(d.price, 2)) + kv('ATR (barre)', `${fmt(d.atr, 1)} pts`)
      + (d.phaseFactor != null && d.phaseFactor < 1 ? `<div class="small">Phase peu active : convictions réduites (× ${fmt(d.phaseFactor, 2)}).</div>` : '');
    if (d.blocked && d.blocked.length) html += d.blocked.map(b => `<div class="note warn"><i></i><div>${esc(b)}</div></div>`).join('');
    html += '</div>';

    if (!d.setups || !d.setups.length) {
      html += '<div class="card muted">Aucun setup au-dessus du score minimal pour l\'instant. Les ingrédients lus sont en bas.</div>';
    } else {
      for (const s of d.setups) {
        const longS = s.side === 'long';
        const dim = s.suppressed ? ' style="opacity:.55"' : '';
        html += `<div class="card"${dim}><h2><span class="badge ${longS ? 'ok' : 'bad'}">${longS ? 'ACHAT' : 'VENTE'}</span> ${s.kind === 'momentum' ? 'Momentum' : 'Retournement'}`
          + ` <small>score ${fmt(s.score, 0)}/100</small>${s.conflict ? ' <small class="amb">(signal inverse aussi présent)</small>' : ''}</h2>`
          + gauge(s.score / 100, s.score >= 60 ? '' : s.score >= 45 ? 'acc' : 'warn')
          + kv('Entrée', fmt(s.entry, 2)) + kv('Stop', `${fmt(s.stop, 2)} <small>${fmt(s.stopPts, 1)} pts</small>`, 'neg')
          + kv('Objectifs', s.targets.map(t => fmt(t, 2)).join(' · '))
          + kv('Gain / risque (1er objectif)', `${fmt(s.rr, 2)} R`, s.rr >= 1.5 ? 'pos' : s.rr >= 1 ? '' : 'neg');
        html += '<div class="small" style="margin-top:6px"><b>Pourquoi :</b></div>'
          + s.reasons.map(r => `<div class="note ${r.dir > 0 ? 'bull' : 'bear'}"><i></i><div>${esc(r.text)} <small>(${TAG_FR[r.tag] || r.tag}, force ${fmt(r.strength, 2)})</small></div></div>`).join('');
        if (s.against && s.against.length) html += `<div class="small amb">Contre : ${s.against.map(a => esc(a.text)).join(' ; ')}.</div>`;
        if (s.ruleNotes && s.ruleNotes.length) html += s.ruleNotes.map(n => `<div class="note info"><i></i><div>${esc(n)}</div></div>`).join('');
        html += `<div class="row" style="margin-top:8px"><button data-setup='${esc(JSON.stringify({side: s.side, entry: s.entry, stop: s.stop, targets: s.targets}))}'${s.suppressed ? ' disabled' : ''}>→ Calculer la taille (Plan)</button></div>`;
        html += `<div class="small" style="margin-top:4px">Ce n'est pas un ordre : un setup est une configuration mesurée. Vérifie-la, dimensionne-la, décide.</div></div>`;
      }
    }
    html += `<div class="card"><h2>Ingrédients lus <small>le flux brut, avant score</small></h2>`
      + ((d.ingredients && d.ingredients.length) ? d.ingredients.map(i =>
          `<div class="kv"><span>${i.dir > 0 ? '▲' : '▼'} ${esc(TAG_FR[i.tag] || i.tag)}</span><b class="${i.dir > 0 ? 'pos' : 'neg'}">${fmt(i.strength, 2)}</b></div>`).join('')
        : '<div class="muted">Rien de notable.</div>')
      + (d.ruleNotes && d.ruleNotes.length ? d.ruleNotes.map(n => `<div class="small">${esc(n)}</div>`).join('') : '') + '</div>';
    host.innerHTML = html;
    $$('#setupOut [data-setup]').forEach(b => b.onclick = () => {
      try { const s = JSON.parse(b.dataset.setup); fillPlan(s.side, s.entry, s.stop, s.targets); } catch (e) { /* ignore */ }
    });
  }

  function fillPlan(side, entry, stop, targets) {
    const f = $('#planForm');
    if (!f) return;
    f.side.value = side;
    f.root.value = 'NQ';
    f.entry.value = Number(entry).toFixed(2);
    f.stop.value = Number(stop).toFixed(2);
    f.sp.value = '';
    if (targets && targets[0] != null) f.t1.value = Number(targets[0]).toFixed(2);
    if (targets && targets[1] != null) f.t2.value = Number(targets[1]).toFixed(2); else f.t2.value = '';
    f.entry.dispatchEvent(new Event('input', {bubbles: true}));
    if (cb.showTab) cb.showTab('plan');
    toast('Setup copié dans le calculateur : vérifie la taille et le risque');
  }

  // ======================================================= Backtest
  function buildBacktest() {
    $('#tab-backtest').innerHTML = `<div class="card"><h2>Backtest <small>sur l'historique chargé</small></h2>
      <form id="btForm" class="f" autocomplete="off">
        <label>Unité de temps<select name="tf"></select></label>
        <label>Score minimal<input name="minScore" inputmode="decimal" value="40"></label>
        <label>Glissement (ticks)<input name="slippage" inputmode="decimal" value="1"></label>
        <label>Stop de temps (min)<input name="maxHold" inputmode="decimal" value="20"></label>
        <label>Risque par trade ($)<input name="risk" inputmode="decimal" value="100"></label>
        <label>Jours (vide = tous)<input name="days" inputmode="decimal" placeholder="tous"></label>
        <label>Prix de l'éval. ($, option)<input name="evalFee" inputmode="decimal" placeholder="ex. 100"></label>
        <label>Horizon Monte Carlo (jours)<input name="horizon" inputmode="decimal" value="60"></label>
        <label class="wide" style="flex-direction:row;align-items:center;gap:6px"><input type="checkbox" name="one" style="width:auto"> Au plus 1 trade par séance régulière</label>
        <div class="row" style="grid-column:1/3"><button type="button" id="btRun" class="primary">Lancer le backtest</button>
          <button type="button" id="btSweep" title="Rejoue une grille de réglages et compare début / fin d'historique">Robustesse</button>
          <button type="button" id="btCsv" disabled title="Télécharger la liste des trades">Exporter CSV</button></div>
      </form>
      <div class="small" style="margin-top:6px">On rejoue les setups barre par barre, sans regarder le futur (décision à la clôture, entrée à l'ouverture suivante), avec frais et glissement. Puis le résultat passe dans les règles Lucid.</div>
      <div id="btErr" class="err"></div></div>
      <div id="btOut"></div>`;
    const f = $('#btForm');
    f.tf.innerHTML = (cb.tfs() || ['1m']).map(t => `<option${t === '1m' ? ' selected' : ''}>${t}</option>`).join('');
    const num = (v, d) => { const x = parseNum(v); return isNaN(x) ? d : x; };
    const query = () => {
      const q = new URLSearchParams({tf: f.tf.value, minScore: num(f.minScore.value, 40), slippage: Math.max(0, num(f.slippage.value, 1)),
        maxHold: Math.max(1, Math.round(num(f.maxHold.value, 20))), risk: Math.max(1, num(f.risk.value, 100)), onePerSession: f.one.checked ? '1' : '0',
        horizon: Math.max(5, Math.min(250, Math.round(num(f.horizon.value, 60))))});
      const dv = parseNum(f.days.value); if (!isNaN(dv) && dv > 0) q.set('days', Math.round(dv));
      const fee = parseNum(f.evalFee.value); if (!isNaN(fee) && fee > 0) q.set('evalFee', fee);
      return q;
    };
    const busy = on => { $('#btRun').disabled = on; $('#btSweep').disabled = on; };
    $('#btRun').onclick = async () => {
      $('#btErr').textContent = '';
      $('#btOut').innerHTML = '<div class="card muted">Backtest en cours… (quelques secondes la première fois, instantané ensuite tant que l\'historique ne change pas)</div>';
      busy(true);
      try { backtestResult(await api('/api/backtest?' + query())); }
      catch (err) { $('#btErr').textContent = err.message; $('#btOut').innerHTML = ''; }
      finally { busy(false); }
    };
    $('#btSweep').onclick = async () => {
      $('#btErr').textContent = '';
      $('#btOut').innerHTML = '<div class="card muted">Test de robustesse en cours…</div>';
      busy(true);
      try { sweepResult(await api('/api/backtest/sweep?' + query())); }
      catch (err) { $('#btErr').textContent = err.message; $('#btOut').innerHTML = ''; }
      finally { busy(false); }
    };
    $('#btCsv').onclick = () => {
      if (!lastBt || !lastBt.trades || !lastBt.trades.length) return;
      const cols = ['day', 'side', 'kind', 'score', 't_entry', 'entry', 'stop', 'target', 'qty', 't_exit', 'exit', 'reason', 'gross', 'fee', 'net', 'holdS', 'sameBar'];
      const iso = ms => new Date(ms).toISOString();
      const lines = [cols.join(',')].concat(lastBt.trades.map(t => cols.map(c => (c === 't_entry' || c === 't_exit') ? iso(t[c]) : (t[c] == null ? '' : String(t[c]))).join(',')));
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([lines.join('\n') + '\n'], {type: 'text/csv'}));
      a.download = `backtest-nq-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    };
  }

  let lastBt = null;

  function sweepResult(r) {
    if (!r || !r.ok) { $('#btOut').innerHTML = `<div class="card muted">${esc(r && r.msg ? r.msg : 'Pas de résultat.')}</div>`; return; }
    const b = r.best;
    let html = `<div class="card"><h2>Robustesse <span class="badge ${r.robust ? 'ok' : 'bad'}">${r.robust ? 'TIENT HORS ÉCHANTILLON' : 'NE TIENT PAS'}</span></h2>`
      + `<div class="small">Début d'historique : ${r.inDays} j (jusqu'au ${esc(r.cut)}) · fin : ${r.outDays} j. On choisit le meilleur score minimal sur le DÉBUT seulement, puis on regarde la FIN, jamais vue au moment du choix.</div>`
      + kv('Meilleur score sur le début', `${b.minScore} <small>${susd(b.inNet)} sur ${b.inN} trade(s)</small>`, cls(b.inNet))
      + kv('… le même sur la fin', `${susd(b.outNet)} <small>sur ${b.outN} trade(s)</small>`, cls(b.outNet))
      + kv('Réglages positifs sur la fin', `${r.positiveOut} / ${r.total}`, r.positiveOut * 2 >= r.total ? 'pos' : 'neg')
      + `<div class="small" style="margin-top:6px">${r.robust ? 'Le réglage choisi reste gagnant sur des jours qu\'il n\'a pas vus : bon signe (pas une preuve).' : 'Le « meilleur » réglage ne se confirme pas sur la fin : c\'était sans doute de la chance. Ne pas sur-optimiser ; il faut plus de journées.'}</div></div>`;
    html += `<div class="card"><h2>Grille <small>score minimal × glissement</small></h2><table><tr><th>Score</th><th>Gliss.</th><th>N</th><th>Début</th><th>Fin</th><th>PF</th><th>Éval.</th></tr>`
      + r.grid.map(g => `<tr${g === b || (g.minScore === b.minScore && g.slippage === b.slippage) ? ' style="outline:1px solid var(--acc)"' : ''}><td>${g.minScore}</td><td>${g.slippage}</td><td>${g.nTrades}</td>`
        + `<td class="${cls(g.inNet)}">${susd(g.inNet)}</td><td class="${cls(g.outNet)}">${susd(g.outNet)}</td><td>${g.profitFactor == null ? '—' : fmt(g.profitFactor, 2)}</td>`
        + `<td>${g.floorBreach ? '<b class="neg">plancher</b>' : g.evalPassed ? '<b class="pos">✓</b>' : '—'}</td></tr>`).join('') + '</table>'
      + '<div class="small" style="margin-top:6px">Glissement 2 ticks = scénario pessimiste. Une stratégie qui ne survit qu\'à 1 tick est fragile en temps réel.</div></div>';
    $('#btOut').innerHTML = html;
  }

  function monteCarlo(mc) {
    if (!mc || !mc.ok) return '';
    const d = mc.daysToPass;
    const bar = (p, c) => `<span style="display:inline-block;height:8px;width:${Math.round(p * 100)}%;background:var(--${c})"></span>`;
    return `<div class="card"><h2>Probabilité de valider l'éval. <small>Monte Carlo · ${mc.paths} évaluations simulées</small></h2>`
      + `<div style="display:flex;width:100%;border-radius:4px;overflow:hidden;margin:4px 0 8px">${bar(mc.pPass, 'up')}${bar(mc.pTimeout, 'mut')}${bar(mc.pBreach, 'dn')}</div>`
      + kv('Validée', pct(mc.pPass), 'pos') + kv('Plancher touché', pct(mc.pBreach), 'neg') + kv(`Ni l'un ni l'autre en ${mc.horizon} j`, pct(mc.pTimeout))
      + (d.median != null ? kv('Jours pour valider', `${d.median} <small>(25 % : ${d.p25} j · 75 % : ${d.p75} j)</small>`) : '')
      + (mc.consistencyDelayed ? kv('Validations retardées par la consistance', pct(mc.consistencyDelayed), 'amb') : '')
      + (mc.attemptsPerPass != null ? kv('Tentatives par validation (moyenne)', fmt(mc.attemptsPerPass, 2)) : '')
      + (mc.costPerPass != null ? kv('Coût moyen d\'une éval. validée', usd(mc.costPerPass), mc.costPerPass > 3 * mc.evalFee ? 'neg' : '') : '')
      + kv('Pire creux d\'une journée (historique)', susd(mc.dayWorstLow), 'neg')
      + `<div class="small" style="margin-top:6px">On tire au hasard, avec remise, les ${mc.sampleDays} journées du backtest (journées sans trade comprises) et on rejoue l'évaluation avec les règles du profil : plancher suiveur touché en cours de journée, cible, consistance.`
      + (mc.fragile ? ` <b class="amb">Échantillon court (${mc.sampleDays} j) : chiffre très fragile, à refaire avec plus de jours enregistrés.</b>` : '') + '</div></div>';
  }

  function backtestResult(r) {
    lastBt = r && r.ok ? r : null;
    if ($('#btCsv')) $('#btCsv').disabled = !(lastBt && lastBt.trades.length);
    if (!r || !r.ok) { $('#btOut').innerHTML = `<div class="card muted">${esc(r && r.msg ? r.msg : 'Pas de résultat.')}</div>`; return; }
    const ru = r.rules, cons = ru.consistency;
    const pass = ru.evalPassed;
    let html = `<div class="card"><h2>Conformité aux règles Lucid <span class="badge ${pass ? 'ok' : 'bad'}">ÉVAL. ${pass ? 'VALIDÉE' : 'NON VALIDÉE'}</span></h2>`
      + kv('Profit simulé', `${susd(ru.profit)} <small>sur ${usd(ru.target)}</small>`, cls(ru.profit))
      + kv('Solde final', usd(ru.finalBalance, 0))
      + kv('Plancher touché', ru.floorBreach ? `<b class="neg">OUI le ${esc(ru.floorBreach.day)}${ru.floorBreach.intraday ? ' en séance' : ''} (${usd(ru.floorBreach.balance, 0)})</b>` : '<b class="pos">non</b>')
      + (ru.passedOn ? kv('Validée le', esc(ru.passedOn), 'pos') : '')
      + kv('Consistance (meilleur jour ≤ 50 %)', cons.ratio == null ? '—' : `${pct(cons.ratio)} ${cons.ok ? '✓' : '✗ il faudrait ' + usd(cons.needed) + ' de profit'}`, cons.ok ? 'pos' : 'neg')
      + kv('Jours tradés', ru.daysTraded)
      + `<div class="small" style="margin-top:6px">${pass ? 'Sur cet historique et avec ces réglages, la stratégie aurait passé l\'évaluation.' : 'Ces réglages ne passent pas encore : ajuste le score minimal, le stop de temps ou le risque, et relance.'}</div></div>`;

    html += `<div class="card"><h2>Résultats <small>${r.nTrades} trade(s)</small></h2>`
      + kv('Résultat net (frais déduits)', susd(r.net), cls(r.net))
      + kv('Frais payés', usd(r.fees))
      + kv('Taux de réussite', pct(r.winRate))
      + kv('Gain moyen · perte moyenne', `${susd(r.avgWin)} · ${susd(r.avgLoss)}`)
      + kv('Espérance par trade', susd(r.expectancy), cls(r.expectancy))
      + kv('Facteur de profit', r.profitFactor == null ? '—' : fmt(r.profitFactor, 2))
      + (r.microShare != null ? kv('Part micro-scalping (≤ 5 s)', `au plus ${pct(r.microShare)} <small>limite ${pct(r.microLimit)}</small>`, r.microShare >= r.microLimit ? 'neg' : '') : '')
      + (r.microShare != null ? '<div class="small">« Au plus » : un trade sorti dans sa barre d\'entrée a duré entre 0 et 1 barre, on le compte comme micro par prudence.</div>' : '')
      + '</div>';
    html += monteCarlo(r.monteCarlo);

    const kinds = Object.entries(r.byKind || {});
    if (kinds.length) html += `<div class="card"><h2>Par type de setup</h2><table><tr><th>Type</th><th>N</th><th>Réussite</th><th>Net</th></tr>`
      + kinds.map(([k, a]) => `<tr><td>${k === 'momentum' ? 'Momentum' : 'Retournement'}</td><td>${a.n}</td><td>${pct(a.winRate)}</td><td class="${cls(a.net)}">${susd(a.net)}</td></tr>`).join('')
      + `</table>` + (r.byReason ? `<div class="small" style="margin-top:6px">Sorties : ${Object.entries(r.byReason).map(([k, v]) => `${k} ${v}`).join(' · ')}</div>` : '') + '</div>';

    if (r.equity && r.equity.length) {
      const bals = r.equity.map(e => e.balance), lo = Math.min(...bals, r.rules.finalBalance), hi = Math.max(...bals);
      const w = 260, h = 48, n = bals.length;
      const pts = bals.map((b, i) => `${(n < 2 ? 0 : i / (n - 1)) * w},${h - (hi === lo ? h / 2 : (b - lo) / (hi - lo) * (h - 4) + 2)}`).join(' ');
      html += `<div class="card"><h2>Courbe de solde (fin de journée)</h2><svg viewBox="0 0 ${w} ${h}" style="width:100%;height:60px"><polyline points="${pts}" fill="none" stroke="var(--acc)" stroke-width="1.5"/></svg>`
        + `<table style="margin-top:6px"><tr><th>Jour</th><th>P&amp;L</th><th>Solde</th></tr>`
        + r.days.map((d, i) => `<tr><td>${esc(d.day)}</td><td class="${cls(d.pnl)}">${susd(d.pnl)}</td><td>${usd(r.equity[i].balance, 0)}</td></tr>`).join('') + '</table></div>';
    }
    if (r.profile && r.profile.name && r.profile.name.toLowerCase().indexOf('simul') < 0) { /* reserved */ }
    html += `<div class="card small muted">Un backtest sur-estime toujours un peu, même prudent : ici un objectif n'est rempli que si le prix le dépasse d'un tick (file d'attente), un stop sauté par un écart est exécuté à l'ouverture, et la barre d'entrée est vérifiée. Il sert à comparer des réglages, pas à promettre un résultat. Sur données simulées, les prix sont fictifs : seuls comptent la mécanique et la conformité aux règles.</div>`;
    $('#btOut').innerHTML = html;
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

  function init(callbacks) { cb = callbacks; buildSetups(); buildAccount(); buildPlan(); buildBacktest(); buildFp(); }
  return {init, lecture, levels, account, footprint, planResult, setups, backtestResult};
})();
