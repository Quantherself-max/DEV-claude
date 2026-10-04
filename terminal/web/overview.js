// Page Overview : une carte par paire (prix, biais, niveaux essentiels, contexte) et un bandeau macro / dominance / sentiment.
const Overview = (() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const esc = s => Charts.esc(s);
  const n1 = (v, d = 2) => v == null || isNaN(v) ? '-' : v.toFixed(d).replace('.', ',');
  const sg = (v, d = 2, u = '') => v == null || isNaN(v) ? '-' : (v > 0 ? '+' : '') + v.toFixed(d).replace('.', ',') + u;
  const p0 = v => v == null ? '-' : Math.round(v * 100) + ' %';
  const fmtP = p => p >= 1000 ? Math.round(p).toLocaleString('fr-FR') : p.toFixed(2).replace('.', ',');
  const cd = ms => { const m = Math.round(Math.abs(ms) / 60000); return m >= 1440 ? `${Math.floor(m / 1440)} j ${Math.floor(m % 1440 / 60)} h` : m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}` : `${m} min`; };
  let LT = null, last = null;
  const card = (t, b, cls = '') => `<div class="acard ${cls}"><h3>${t}</h3>${b}</div>`;

  function ideaBlock(s) {
    const i = s.idea;
    if (!i) return '';
    if (!i.n && !i.side) return '<div class="sect">Idée de trade</div><div class="muted small">Aucune configuration ne passe les filtres pour l\'instant.</div>';
    const buy = i.side === 'long', cls = buy ? 'up' : 'dn';
    const state = i.eligible ? `<span class="tag ok">au-dessus du seuil</span>` : i.hold && i.hold.length ? `<span class="tag warn">en attente : annonce</span>` : `<span class="tag warn">sous le seuil (${i.minScore})</span>`;
    return `<div class="sect">Idée de trade</div><div class="hero" style="gap:10px"><div class="big ${cls}" style="font-size:18px">${buy ? 'ACHAT' : 'VENTE'}</div><div class="muted small">qualité <b>${Math.round(i.score)}/100</b> ${state}<br>entrée ${fmtP(i.entry)} · stop ${fmtP(i.stop)} · objectif ${fmtP(i.tp1)}</div></div>`;
  }

  function symCard(s) {
    if (!s.ready) return card(esc(s.symbol), '<div class="muted">Chargement des données…</div>');
    const sy = s.synth, dirCls = sy.direction === 'haussier' ? 'up' : sy.direction === 'baissier' ? 'dn' : 'neu';
    const col = s.change24 > 0 ? '#3ddc97' : '#ff6b6b';
    const lv = sy.levels.filter(l => l.side !== 'in').sort((a, b) => b.mid - a.mid);
    const rows = lv.map(l => `<tr><td class="${l.side === 'above' ? 'up' : 'dn'}">${l.side === 'above' ? '▲' : '▼'} ${'●'.repeat(Math.min(5, l.score))}</td><td class="r">${fmtP(l.mid)}</td><td class="r muted">${n1(l.distAtr, 1)} ATR</td><td class="r">${p0(l.reach24)}</td><td class="r">${l.bounce && l.bounce.n ? p0(l.bounce.p) : '-'}</td></tr>`).join('');
    const sym = s.symbol.replace('USDT', '');
    return card(`${esc(sym)} <small class="muted">perpétuel Binance</small>`,
      `<div class="hero"><div class="big neu" style="font-size:28px">${fmtP(s.price)}</div><div><div class="${s.change24 > 0 ? 'up' : 'dn'}" style="font-weight:600">${sg(s.change24, 2, ' %')} <span class="muted small">24 h</span></div><div class="muted small">ATR 1h ${n1(s.atrPct)} %</div></div><div style="flex:1;min-width:110px">${Charts.spark(s.spark, col, 180, 44)}</div></div>` +
      `<div class="sect">Biais</div><div class="hero" style="gap:10px"><div class="big ${dirCls}" style="font-size:18px">${esc(sy.label.toUpperCase())}</div><div class="muted small">${sg(sy.score, 0)}/100 · confiance <span class="tag ${sy.confidence === 'faible' ? 'warn' : 'ok'}">${sy.confidence}</span><span class="tag ${sy.validated ? 'ok' : 'warn'}">${sy.validated ? 'modèle validé' : 'non validé'}</span></div></div>` +
      `<div class="muted small" style="margin-top:4px">P(hausse 24 h) ${sy.validated ? '<b>' + p0(sy.pUp24) + '</b>' : p0(sy.base24) + ' (taux de base)'}${s.history && s.history.since ? ' · historique depuis ' + new Date(s.history.since).getFullYear() : ''}</div>` +
      ideaBlock(s) +
      (rows ? `<div class="sect">Niveaux essentiels</div><table class="t"><tr><th></th><th class="r">Prix</th><th class="r">Distance</th><th class="r">Atteinte 24 h</th><th class="r">Rebond</th></tr>${rows}</table>` : '<div class="muted small">Aucune zone essentielle.</div>') +
      `<div class="sect">Contexte</div><div class="muted small">${s.regime ? esc(s.regime) + '<br>' : ''}Funding ${s.funding != null ? sg(s.funding, 4, ' %') : '-'} · OI 24 h ${sg(s.oi24, 1, ' %')} · achats agressifs 24 h ${s.buy24 != null ? n1(s.buy24, 1) + ' %' : '-'} · L/S ${s.ls != null ? n1(s.ls) : '-'}</div>` +
      `<div class="line" style="margin-top:8px"><button data-ovgo="${esc(s.symbol)}" class="primary">Ouvrir sur le Desk</button><button data-ovan="${esc(s.symbol)}">Analyse</button></div>`);
  }

  function render(o) {
    last = o;
    const el = $('#overview'); if (!el) return;
    const mac = o.macro, now = o.t;
    let top = '<div class="ag">';
    if (mac) {
      const r = mac.risk, lvl = r ? (r.minutes <= 90 ? 'bad' : r.minutes <= 720 ? 'warn' : '') : '';
      top += card('Macro', `<div class="hero"><div class="big ${mac.label === 'risk-on' ? 'up' : mac.label === 'risk-off' ? 'dn' : 'neu'}" style="font-size:24px">${esc((mac.label || 'n/d').toUpperCase())}</div><div class="muted small">${mac.score != null ? sg(mac.score, 0) + '/100' : ''}</div></div>` +
        (mac.risk ? `<div class="msg ${lvl}"><b>${esc(mac.risk.label)}</b> dans ${cd(mac.risk.t - Date.now())}</div>` : '<div class="msg ok">Aucune annonce majeure imminente.</div>') +
        (mac.upcoming || []).slice(0, 3).map(e => `<div class="muted small">${new Date(e.t).toLocaleString('fr-FR', {weekday: 'short', hour: '2-digit', minute: '2-digit'})} · ${'●'.repeat(e.impact)} ${esc(e.label)}${e.forecast ? ' (' + esc(e.forecast) + ')' : ''}</div>`).join(''));
    }
    if (o.dom && o.dom.btc_d != null) top += card('Dominance BTC', `<div class="hero"><div class="big neu" style="font-size:24px">${n1(o.dom.btc_d, 1)} %</div></div><div class="msg ${o.dom.tone === 'muted' ? '' : o.dom.tone || ''}">${esc(o.dom.regime || '')}</div>`);
    if (o.fng) top += card('Fear & Greed', `<div class="hero"><div class="big neu" style="font-size:24px">${o.fng.value}</div><div class="sub muted">${esc(o.fng.label)}${o.fng.d7 != null ? ' · ' + sg(o.fng.d7, 0) + ' en 7 j' : ''}</div></div>`);
    const feed = o.feed, errs = Object.entries(o.errors || {}), srcErr = Object.entries((o.sources && o.sources.errors) || {});
    if (o.week) {
      const w = o.week, st = o.tradeStats || {};
      top += card('Idées de trade', `<div class="hero"><div class="big neu" style="font-size:24px">${w.sent}/${w.cap}</div><div class="muted small">envoyées cette semaine</div></div>` +
        ((o.openTrades || []).length ? o.openTrades.map(t => `<div class="muted small"><b class="${t.side === 'long' ? 'up' : 'dn'}">${t.side === 'long' ? 'ACHAT' : 'VENTE'}</b> ${esc(t.symbol)} ${fmtP(t.entry)} · ${t.status === 'pending' ? 'ordre en attente' : t.status === 'tp1' ? 'objectif 1 atteint' : 'position ouverte'}</div>`).join('') : '<div class="muted small">Aucune idée ouverte.</div>') +
        (st.ideas ? `<div class="muted small" style="margin-top:4px">Total : ${st.ideas} idées · stop ${st.stop} · objectif 2 ${st.tp2}</div>` : ''));
    }
    top += card('Santé', `<div class="muted small">Flux prix : ${feed && feed.trades && feed.trades.connected ? '<span class="up">connecté</span>' : '<span class="dn">hors ligne</span>'}<br>Flux liquidations : ${feed && feed.liqs && feed.liqs.connected ? '<span class="up">connecté</span>' : '<span class="dn">hors ligne</span>'}<br>Sources externes : ${srcErr.length ? '<span class="dn">' + srcErr.length + ' en erreur</span>' : '<span class="up">OK</span>'}${errs.length ? '<br><span class="dn">' + errs.length + ' erreur(s) serveur</span>' : ''}</div>`);
    top += card('Dernières alertes', (o.alerts || []).length ? o.alerts.map(a => `<div class="alert"><time>${new Date(a.t * 1000).toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit'})}</time>${a.sent ? '✓' : '✗'} ${esc(a.text)}</div>`).join('') : '<div class="muted small">Aucune alerte pour l\'instant.</div>');
    top += '</div>';
    el.className = 'ovwrap';
    el.innerHTML = top + `<div class="ag two" style="margin-top:10px">${o.symbols.map(symCard).join('')}</div>`;
    el.querySelectorAll('[data-ovgo]').forEach(b => b.onclick = () => LT.openSymbol(b.dataset.ovgo, 'desk'));
    el.querySelectorAll('[data-ovan]').forEach(b => b.onclick = () => LT.openSymbol(b.dataset.ovan, 'analysis'));
  }
  function init(lt) { LT = lt; }
  return {init, render};
})();
