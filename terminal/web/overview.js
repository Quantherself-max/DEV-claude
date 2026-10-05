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

  function trendBlock(s) {
    const t = s.trend;
    if (!t) return '';
    const cls = t.regime > 0 ? 'up' : t.regime < 0 ? 'dn' : 'neu';
    return `<div class="sect">Tendance de fond</div><div class="muted small"><b class="${cls}">${esc(t.label)}</b> · cours ${sg(t.distFast, 1, ' %')} / moyenne 50 j, ${sg(t.distSlow, 1, ' %')} / moyenne 200 j${t.regime === 0 ? ' · aucune idée retenue' : t.regime > 0 ? ' · seuls les achats sont retenus' : ' · seules les ventes sont retenues'}</div>`;
  }

  function symCard(s) {
    if (!s.ready) return card(esc(s.symbol), '<div class="muted">Chargement des données…</div>');
    const sy = s.synth, dirCls = sy.direction === 'haussier' ? 'up' : sy.direction === 'baissier' ? 'dn' : 'neu';
    const col = s.change24 > 0 ? '#3ddc97' : '#ff6b6b';
    const lv = sy.levels.filter(l => l.side !== 'in').sort((a, b) => b.mid - a.mid);
    const below = lv.filter(l => l.side === 'below'), above = lv.filter(l => l.side === 'above');
    const nl = (l, up) => `<span class="${up ? 'up' : 'dn'}">${up ? '▲' : '▼'}</span> ${fmtP(l.mid)} <span class="muted">(${n1(l.distAtr, 1)} ATR · ${p0(l.reach24)} en 24 h)</span>`;
    const near = [above.length ? nl(above[above.length - 1], true) : null, below.length ? nl(below[0], false) : null].filter(Boolean);
    const sym = s.symbol.replace('USDT', '');
    return card(`${esc(sym)} <small class="muted">perpétuel Binance</small>`,
      `<div class="hero"><div class="big neu" style="font-size:28px">${fmtP(s.price)}</div><div><div class="${s.change24 > 0 ? 'up' : 'dn'}" style="font-weight:600">${sg(s.change24, 2, ' %')} <span class="muted small">24 h</span></div><div class="muted small">ATR 1h ${n1(s.atrPct)} %</div></div><div style="flex:1;min-width:110px">${Charts.spark(s.spark, col, 180, 44)}</div></div>` +
      (sy.validated
        ? `<div class="sect">Biais</div><div class="hero" style="gap:10px"><div class="big ${dirCls}" style="font-size:18px">${esc(sy.label.toUpperCase())}</div><div class="muted small">${sg(sy.score, 0)}/100 · confiance <span class="tag ${sy.confidence === 'faible' ? 'warn' : 'ok'}">${sy.confidence}</span> <span class="tag ok">modèle validé</span></div></div><div class="muted small" style="margin-top:4px">P(hausse 24 h) <b>${p0(sy.pUp24)}</b></div>`
        : `<div class="muted small" style="margin-top:6px">Biais statistique non validé (ne bat pas le hasard) : ignoré.</div>`) +
      trendBlock(s) + ideaBlock(s) +
      (near.length ? `<div class="sect">Niveaux proches</div><div class="small">${near.join(' · ')}</div>` : '') +
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
    top += '</div>';
    el.className = 'ovwrap';
    el.innerHTML = top + `<div class="ag two" style="margin-top:10px">${o.symbols.map(symCard).join('')}</div>`;
    el.querySelectorAll('[data-ovgo]').forEach(b => b.onclick = () => LT.openSymbol(b.dataset.ovgo, 'desk'));
    el.querySelectorAll('[data-ovan]').forEach(b => b.onclick = () => LT.openSymbol(b.dataset.ovan, 'analysis'));
  }
  function init(lt) { LT = lt; }
  return {init, render};
})();
