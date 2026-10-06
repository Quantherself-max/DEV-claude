// Lecture : l'essentiel du marche pour la paire choisie, sur un seul ecran (tendance, idee, ce qui arrive, positionnement, derives, macro).
// Chaque ligne porte son niveau de preuve : « validé » (backtest), « indice » (même signe partout, sans preuve), « contexte » (lecture seule).
const Lecture = (() => {
  'use strict';
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  let LT = null, root = null, last = null, timer = null, busy = false;
  const px = v => v == null ? '-' : LT.fmtP(v);
  const n1 = (v, d = 1) => v == null || isNaN(v) ? '-' : v.toFixed(d).replace('.', ',');
  const sg = (v, d = 1, u = '') => v == null || isNaN(v) ? '-' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d).replace('.', ',') + u;
  const EV = {valide: ['ok', 'validé par le backtest'], indice: ['warn', 'indice, non démontré'], informatif: ['ok', 'informatif'], contexte: ['', 'contexte']};

  function init(lt) { LT = lt; root = document.getElementById('lectureBox'); }
  async function load() {
    if (busy || !root) return;
    busy = true;
    try { last = await LT.api('/api/lecture?symbol=' + encodeURIComponent(LT.st.symbol)); } catch (e) { last = {error: e.message}; }
    busy = false;
    render();
  }
  function show() {
    load();
    clearInterval(timer);
    timer = setInterval(() => { if (LT.st.tab === 'lecture' && LT.st.page === 'desk') load(); }, 20000);
  }
  const cd = ms => { const m = Math.max(0, Math.round(ms / 60000)); return m >= 90 ? Math.floor(m / 60) + ' h ' + String(m % 60).padStart(2, '0') : m + ' min'; };

  function chipHtml(c) {
    const ev = EV[c.evidence] || EV.contexte;
    return `<div class="lchip ${c.tone || ''}"><div class="lhd"><span class="lt">${esc(c.title)}</span><span class="pill ${ev[0]}" title="${esc(ev[1])}">${c.evidence === 'valide' ? 'validé' : c.evidence === 'indice' ? 'indice' : c.evidence === 'informatif' ? 'informatif' : 'contexte'}</span></div>
      <div class="lv">${esc(c.value)}</div>${c.note ? `<div class="ln">${esc(c.note)}</div>` : ''}</div>`;
  }
  function ideaHtml(i) {
    if (!i) return '<div class="muted small">Idées indisponibles.</div>';
    if (!i.side) return '<div class="muted small">Aucune idée retenue pour l\'instant. Le terminal n\'en envoie que lorsque plusieurs niveaux se superposent, dans le sens de la tendance de fond.</div>';
    const cls = i.side === 'long' ? 'up' : 'dn';
    const why = (i.gates || []).concat(i.hold || [])[0];
    const status = i.eligible ? '' : i.align != null && i.align <= 0 ? ' · contre la tendance de fond : non retenue' : i.score < i.minScore ? ' · sous le seuil (' + i.minScore + ')' : ' · pas encore envoyée';
    return `<div class="lidea"><b class="${cls}">${i.side === 'long' ? 'ACHAT' : 'VENTE'}</b> <span class="muted small">qualité ${Math.round(i.score)}/100${status}${why ? ' · ' + esc(why) : ''}</span>
      <div class="small">entrée ${px(i.entry)} · stop ${px(i.stop)} · objectif ${px(i.tp1)}</div></div>`;
  }
  function lv(l, up) { return `<span class="${up ? 'up' : 'dn'}">${up ? '▲' : '▼'}</span> ${px(l.mid)} <span class="muted small">${n1(l.distAtr, 1)} ATR · ${'●'.repeat(Math.min(5, l.score || 0))}${l.reach24 != null ? ' · ' + Math.round(l.reach24 * 100) + ' % en 24 h' : ''}</span>`; }

  function moneyHtml(m) {
    if (!m) return '';
    const pt = v => v == null ? '<td class="r muted">-</td>' : `<td class="r ${v > 0.0005 ? 'up' : v < -0.0005 ? 'dn' : 'muted'}">${sg(v * 100, 1)} pt</td>`;
    const rows = m.rows.map(x => `<tr><td>${esc(x.label)}</td><td class="r"><b>${n1(x.share * 100, 1)} %</b></td>${pt(x.d7)}${pt(x.d30)}</tr>`).join('');
    const rp = v => v == null ? '<span class="muted">-</span>' : `<span class="${v > 0.005 ? 'up' : v < -0.005 ? 'dn' : 'muted'}">${sg(v * 100, 1, ' %')}</span>`;
    const g = m.gold, tr = g.trend == null ? '' : g.trend > 0 ? 'au-dessus de sa moyenne 200 j' : 'sous sa moyenne 200 j';
    return `<section class="card"><h2>Où est l'argent <small>${m.ageDays > 3 ? 'données du ' + new Date(m.date).toLocaleDateString('fr-FR') : 'rotation sur 7 et 30 jours'}</small></h2>
      <div class="lchip"><div class="lhd"><span class="lt">Lecture</span><span class="pill">contexte</span></div><div class="ln" style="font-size:12.5px;color:#d4d8e2">${esc(m.reading)}</div></div>
      <table class="bttab"><thead><tr><th>Part du capital</th><th class="r">Auj.</th><th class="r">7 j</th><th class="r">30 j</th></tr></thead><tbody>${rows}</tbody></table>
      <div class="small" style="margin-top:6px">Contre le BTC (30 j) : ETH ${rp(m.rel.eth30)} · altcoins ${rp(m.rel.alts30)} · SOL ${rp(m.rel.sol30)} · or ${rp(m.rel.gold30)}</div>
      <div class="lchip" style="margin-top:8px"><div class="lhd"><span class="lt">Or (PAXG)</span><span class="pill">contexte</span></div><div class="lv">${n1(g.price, 0)} $ · ${sg((g.d30 || 0) * 100, 1, ' %')} en 30 j${tr ? ' · ' + tr : ''}${g.corr90 != null ? ' · corrélation BTC 90 j ' + sg(g.corr90, 2) : ''}</div><div class="ln">${esc(g.note)}</div></div>
      <div class="muted small" style="margin-top:6px">Panier : BTC, ETH, 10 altcoins. Aucun de ces indicateurs ne prédit le prix de façon prouvée (page Backtest → « où va l'argent »).</div></section>`;
  }

  function render() {
    if (!root) return;
    if (!last) { root.innerHTML = '<section class="card"><div class="muted">Chargement…</div></section>'; return; }
    if (last.error) { root.innerHTML = `<section class="card"><div class="dn">Indisponible : ${esc(last.error)}</div></section>`; return; }
    if (!last.ready) { root.innerHTML = '<section class="card"><div class="muted">Chargement des données du marché…</div></section>'; return; }
    const h = last.head, tr = h.trend, bi = h.bias, w = last.watch;
    const trendHtml = tr ? `<div class="lrow"><span class="lt">Tendance de fond</span><b class="${tr.regime > 0 ? 'up' : tr.regime < 0 ? 'dn' : 'amb'}">${esc(tr.label.toUpperCase())}</b> <span class="pill ok" title="mesuré par le backtest du terminal">validé</span>
      <div class="muted small">cours ${sg(tr.distFast, 1, ' %')} / moyenne 50 j · ${sg(tr.distSlow, 1, ' %')} / moyenne 200 j · ${tr.regime === 0 ? 'aucune idée retenue' : tr.regime > 0 ? 'seuls les achats sont retenus' : 'seules les ventes sont retenues'}</div></div>` : '';
    const biasHtml = !bi ? '' : bi.validated
      ? `<div class="lrow"><span class="lt">Biais statistique</span><b class="${/hauss/i.test(bi.label) ? 'up' : /baiss/i.test(bi.label) ? 'dn' : 'muted'}">${esc(bi.label.toUpperCase())}</b> <span class="pill ok">validé</span><div class="muted small">probabilité de hausse à 24 h : ${n1((bi.pUp24 || 0) * 100, 0)} %</div></div>`
      : `<div class="lrow"><span class="lt">Biais statistique</span><span class="muted small">non validé : il ne bat pas le hasard hors échantillon (${n1((bi.base24 || 0) * 100, 0)} % de hausse en moyenne à 24 h), donc ignoré.</span></div>`;
    const nxt = w.next ? `<div class="lrow"><span class="lt">Prochaine annonce</span><b class="${w.next.minutes != null && w.next.minutes <= 90 ? 'dn' : ''}">${esc(w.next.label)}</b> <span class="muted small">dans ${cd((w.next.t || 0) - Date.now())}</span></div>` : '';
    const lvls = (w.up.length || w.dn.length) ? `<div class="lrow"><span class="lt">Niveaux proches</span>${w.up.slice().reverse().map(l => '<div class="small">' + lv(l, true) + '</div>').join('')}${w.dn.map(l => '<div class="small">' + lv(l, false) + '</div>').join('')}</div>` : '';
    const groups = {};
    last.chips.forEach(c => (groups[c.group] = groups[c.group] || []).push(c));
    const sections = Object.entries(groups).map(([g, cs]) => `<section class="card"><h2>${esc(g)}</h2>${cs.map(chipHtml).join('')}</section>`).join('');
    const money = moneyHtml(last.money);
    root.innerHTML = `<section class="card"><h2>${esc(h.symbol.replace('USDT', ''))} <small>${px(h.price)} · ${sg(h.change24, 2, ' %')} en 24 h</small></h2>${trendHtml}${biasHtml}
        <div class="lrow"><span class="lt">Idée de trade</span>${ideaHtml(last.idea)}</div>${nxt}${lvls}</section>${sections}${money}
      <section class="card"><div class="muted small"><b>Preuve</b> : « validé » = mesuré par le backtest du terminal ; « indice » = même signe sur l'apprentissage et le test, sans dépasser le seuil du hasard ; « contexte » = lecture seule, aucun avantage démontré (le détail est dans la page Backtest, rapport « indicateurs »). Rien de tout cela n'entre dans le score des idées sauf la tendance de fond.${last.optionsOn ? '' : ' Options, volatilité implicite et base : indisponibles (Deribit injoignable ou mode simulé).'}</div></section>`;
  }
  return {init, show, render};
})();
