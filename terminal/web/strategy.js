// Ta stratégie en direct : VWAP et VWAP ancrés de la semaine et du mois (bougies 1 h et 4 h fermées), zone de valeur des profils, poches de liquidité en objectif.
const Strategy = (() => {
  'use strict';
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  let LT = null, root = null, last = null, timer = null, busy = false;
  const px = v => v == null ? '-' : LT.fmtP(v);
  const n1 = (v, d = 1) => v == null || isNaN(v) ? '-' : v.toFixed(d).replace('.', ',');
  const POS = {'-1': ['sous la VAL', 'dn'], '0': ['dans la zone de valeur', 'muted'], '1': ['au-dessus de la VAH', 'up']};
  const VPN = {cw: 'Semaine en cours', pw: 'Semaine dernière', cm: 'Mois en cours', pm: 'Mois dernier'};

  function init(lt) { LT = lt; root = document.getElementById('mineBox'); }
  async function load() {
    if (busy || !root) return;
    busy = true;
    try { last = await LT.api('/api/strategy?symbol=' + encodeURIComponent(LT.st.symbol)); } catch (e) { last = {error: e.message}; }
    busy = false;
    render();
  }
  function show() {
    load();
    clearInterval(timer);
    timer = setInterval(() => { if (LT.st.tab === 'mine' && LT.st.page === 'desk') load(); }, 30000);
  }

  function flag(b, name) {
    const t = (b.triggers || []).filter(x => x.name === name);
    if (!t.length) return '<span class="muted">·</span>';
    return t.map(x => `<span class="pill ${x.dir > 0 ? 'up' : 'dn'}" title="La bougie touche ce niveau et clôture ${x.dir > 0 ? 'au-dessus' : 'en dessous'} (${x.type === 'cross' ? 'elle change de côté' : 'elle reste du même côté : rebond'})">${x.dir > 0 ? '▲ achat' : '▼ vente'}${x.type === 'cross' ? ' ↔' : ''}</span>`).join(' ');
  }
  function vpRow(k, v, bars) {
    if (!v) return `<tr><td>${VPN[k]}</td><td colspan="5" class="muted">pas assez de données</td></tr>`;
    const cell = tf => {
      const b = bars[tf]; if (!b) return '-';
      const p = b.pos[k], q = b.posPrev[k];
      if (p == null) return '-';
      const [txt, cls] = POS[String(p)];
      let ev = '';
      if (q != null && q !== 0 && p === 0) ev = ` <span class="pill warn" title="La bougie précédente était hors de la zone de valeur, celle-ci clôture dedans : le prix réintègre le profil">réintégration</span>`;
      else if (q != null && q === p && p !== 0) ev = ` <span class="pill ${p > 0 ? 'up' : 'dn'}" title="Deux clôtures de suite hors de la zone de valeur du même côté : le prix rejette le profil">rejet</span>`;
      return `<span class="${cls}">${txt}</span>${ev}`;
    };
    return `<tr><td>${VPN[k]}</td><td class="r">${px(v.val)}</td><td class="r">${px(v.poc)}</td><td class="r">${px(v.vah)}</td><td>${cell('1h')}</td><td>${cell('4h')}</td></tr>`;
  }
  function pools(list, up) {
    if (!list.length) return '<div class="muted small">Aucune poche notable dans la fenêtre.</div>';
    return `<table class="bttab">${list.map(p => `<tr><td>${esc(p.src)}</td><td class="r">${px(p.price)}</td><td class="r muted">${up ? '+' : '−'}${n1(p.distAtr)} ATR · ${n1(Math.abs(p.price / last.price - 1) * 100, 2)} %</td><td class="r muted">force ${p.score}</td></tr>`).join('')}</table>`;
  }
  function reading(v) {
    const out = [];
    for (const tf of ['4h', '1h']) {
      const b = v.bars[tf]; if (!b) continue;
      const t = (b.triggers || []);
      const when = new Date((b.t + (tf === '1h' ? 3600000 : 14400000))).toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit'});
      if (!t.length) { out.push(`Bougie ${tf} fermée à ${when} (clôture ${px(b.c)}) : ne touche aucun de tes niveaux.`); continue; }
      const buys = t.filter(x => x.dir > 0), sells = t.filter(x => x.dir < 0);
      const names = l => l.map(x => x.name.replace('VWAP ancré ', 'VWAP ancré ')).join(', ');
      if (buys.length) out.push(`Bougie ${tf} fermée à ${when} : touche ${names(buys)} et clôture AU-DESSUS (${px(b.c)}) → déclencheur d'achat.`);
      if (sells.length) out.push(`Bougie ${tf} fermée à ${when} : touche ${names(sells)} et clôture EN DESSOUS (${px(b.c)}) → déclencheur de vente.`);
      if (b.volr != null) out.push(`Volume de cette bougie ${tf} : ${n1(b.volr, 2)} × la moyenne des 24 précédentes${b.volr >= 1 ? ' (il y a du volume)' : ' (volume faible)'}.`);
    }
    return out;
  }
  function reportBox(v) {
    const r = v.report;
    if (!r) return '<div class="trendbox muted small">Aucun rapport de backtest de cette stratégie dans <code>reports/</code>.</div>';
    const a = r.all, o = r.oos;
    const f = m => m && m.expR != null ? `${m.expR >= 0 ? '+' : '−'}${n1(Math.abs(m.expR), 2)} R (${m.n} trades)` : '-';
    return `<div class="trendbox"><b>Ce que dit le backtest</b> <span class="muted small">${esc(r.label)}${r.proxy ? ' (rapport BTC : pas encore de rapport pour ce symbole)' : ''}</span>
      <div class="small">${esc(r.verdict || '')}</div>
      <div class="small muted">Meilleure variante : ${esc(r.bestName || '-')} · tout l'historique ${f(a)} · depuis 2022 ${f(o)}. Détail : page Backtest, rapport « ta stratégie ».</div></div>`;
  }

  function render() {
    if (!root) return;
    if (!last) { root.innerHTML = '<section class="card"><div class="muted">Chargement…</div></section>'; return; }
    if (last.error) { root.innerHTML = `<section class="card"><div class="dn">Indisponible : ${esc(last.error)}</div></section>`; return; }
    if (!last.ready) { root.innerHTML = '<section class="card"><div class="muted">Pas encore assez d\'historique (40 jours de bougies 1 h).</div></section>'; return; }
    const v = last, b1 = v.bars['1h'] || {}, b4 = v.bars['4h'] || {};
    const rg = v.regime && v.regime.ready ? `<span class="${v.regime.regime > 0 ? 'up' : v.regime.regime < 0 ? 'dn' : 'amb'}">${esc(v.regime.label)}</span>` : '-';
    const lv = v.levels.map(l => `<tr><td>${esc(l.name.replace('VWAP ancré', 'AVWAP').replace('sur le plus ', 'plus '))}${l.grp === 'M' ? '' : ''}</td><td class="r">${px(l.value)}</td>
      <td class="r muted">${l.distAtr >= 0 ? '+' : '−'}${n1(Math.abs(l.distAtr))} ATR</td><td>${flag(b1, l.name)}</td><td>${flag(b4, l.name)}</td></tr>`).join('');
    root.innerHTML = `<section class="card"><h2>Ta stratégie <small>${esc(v.symbol)} · prix ${px(v.price)} · tendance de fond ${rg}</small></h2>
        <div class="muted small">Le prix touche un VWAP ou un VWAP ancré de la semaine ou du mois puis clôture au-dessus (achat) ou en dessous (vente) sur une bougie 1 h ou 4 h ; objectifs sur les poches de liquidité ; zone de valeur du profil pour juger réintégration ou rejet. Aucune alerte n'est envoyée : c'est un tableau de lecture.</div>
        ${reportBox(v)}</section>
      <section class="card"><h2>Lecture des dernières bougies fermées</h2><ul class="mine">${reading(v).map(x => `<li>${esc(x)}</li>`).join('') || '<li class="muted">Rien à signaler.</li>'}</ul></section>
      <section class="card"><h2>Niveaux <small>VWAP et VWAP ancrés</small></h2>
        <table class="bttab"><thead><tr><th>Niveau</th><th class="r">Prix</th><th class="r">Distance</th><th>Bougie 1 h</th><th>Bougie 4 h</th></tr></thead><tbody>${lv}</tbody></table>
        <div class="muted small">▲ / ▼ : la dernière bougie fermée touche le niveau et clôture au-dessus / en dessous. ↔ : elle a changé de côté.</div></section>
      <section class="card"><h2>Volume profile <small>zone de valeur (70 % du volume)</small></h2>
        <table class="bttab"><thead><tr><th>Profil</th><th class="r">VAL</th><th class="r">POC</th><th class="r">VAH</th><th>Clôture 1 h</th><th>Clôture 4 h</th></tr></thead><tbody>${['cw', 'pw', 'cm', 'pm'].map(k => vpRow(k, v.vp[k], v.bars)).join('')}</tbody></table>
        <div class="muted small">Réintégration : la clôture précédente était hors de la zone de valeur et celle-ci est dedans. Rejet : deux clôtures de suite hors de la zone, du même côté.</div></section>
      <section class="card"><h2>Poches de liquidité <small>tes objectifs</small></h2>
        <div class="sect">Au-dessus (objectifs d'achat)</div>${pools(v.pools.up, true)}
        <div class="sect">En dessous (objectifs de vente)</div>${pools(v.pools.dn, false)}
        <div class="muted small">Ordres d'arrêt visibles dans le prix (plus hauts / plus bas, creux, sommets, niveaux égaux). Les poches de liquidations estimées par l'Open Interest sont dans l'onglet Niveaux.</div></section>`;
  }
  return {init, show, render};
})();
