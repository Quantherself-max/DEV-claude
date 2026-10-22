"""Indicateurs sous le graphique (V30) : l'INTÉRÊT OUVERT en bougies (ouverture, plus haut, plus bas, clôture de chaque bougie du
graphique, à partir des relevés toutes les 5 minutes de Binance) et le DELTA de chaque bougie (volume acheteur agressif moins volume
vendeur agressif) avec son cumul, le CVD. Module PUR."""
from __future__ import annotations
from bisect import bisect_left, bisect_right


def oi_candles(times, step_ms: int, pt_t: list, pt_v: list) -> list:
    """times : ouverture de chaque bougie (ms) ; pt_t / pt_v : relevés de l'intérêt ouvert (heure du relevé, valeur), triés.
    Rend [ouverture, plus haut, plus bas, clôture] par bougie (None sans relevé). L'ouverture est le dernier relevé d'avant la bougie
    (comme un graphique en bougies : chaque bougie part de la clôture de la précédente)."""
    out = []
    for t in times:
        i0, i1 = bisect_right(pt_t, t), bisect_right(pt_t, t + step_ms)
        if i1 <= i0:                                       # pas encore de relevé dans la bougie (bougie en cours) : la dernière valeur
            p = pt_v[i0 - 1] if i0 > 0 and t - pt_t[i0 - 1] <= 3 * max(step_ms, 300_000) else None
            out.append([p, p, p, p] if p is not None else None)
            continue
        vs = pt_v[i0:i1]
        o = pt_v[i0 - 1] if i0 > 0 and t - pt_t[i0 - 1] <= 3 * max(step_ms, 300_000) else vs[0]
        out.append([o, max(o, max(vs)), min(o, min(vs)), vs[-1]])
    return out


def deltas(candles) -> tuple:
    """(delta par bougie, CVD) ; None là où le volume acheteur agressif est inconnu (le CVD reprend la dernière valeur connue)."""
    d, cvd, run = [], [], 0.0
    for k in candles:
        if k.tb > 0 and k.v > 0:
            x = 2 * k.tb - k.v
            run += x
            d.append(x)
        else:
            d.append(None)
        cvd.append(run)
    return d, cvd


def merge_points(live: dict, archive: dict) -> tuple:
    """Relevés de l'adresse Binance (clé : ouverture de la bougie 5 min, valeur à sa fin) et des archives (clé : heure du relevé) ->
    (heures, valeurs) triées ; l'adresse passe devant les archives."""
    pts = dict(archive)
    for k, v in live.items():
        pts[k + 300_000] = v
    ts = sorted(pts)
    return ts, [pts[t] for t in ts]


FUND_LAG_MS = 60_000                                       # un versement arrive quelques millisecondes après l'heure ronde : il clôt la période d'avant


def _per8h(rows) -> list:
    """[(heure du versement, taux de la période)] -> taux ramenés à une période de 8 heures (Binance verse parfois toutes les 4 heures
    ou toutes les heures quand le marché s'emballe : on compare des taux de même durée)."""
    out = []
    for i, (t, r) in enumerate(rows):
        gap = (t - rows[i - 1][0]) if i else (rows[1][0] - t if len(rows) > 1 else 8 * 3_600_000)
        hours = min(8.0, max(1.0, round(gap / 3_600_000)))
        out.append(r * 8.0 / hours)
    return out


def funding_bars(times, step_ms: int, rows, now_rate=None, now_ms=None) -> dict:
    """V35 : le FUNDING (financement payé entre acheteurs et vendeurs à levier) pour chaque bougie du graphique, en % par 8 heures.
    rows : versements [(heure du versement ms, taux de la période)] triés ; now_rate : estimation du taux de la période en cours.
    Une bougie plus courte que la période prend le taux du versement qui clôt sa période ; une bougie plus longue, la moyenne de ses
    versements. Après le dernier versement : l'estimation en cours (« est » = indice de la première bougie estimée)."""
    rows = sorted(rows)
    ks = [t - FUND_LAG_MS for t, _ in rows]
    rs = [r * 100.0 for r in _per8h(rows)]
    nr = None
    if now_rate is not None:
        hours = min(8.0, max(1.0, round((rows[-1][0] - rows[-2][0]) / 3_600_000))) if len(rows) > 1 else 8.0
        nr = now_rate * 100.0 * 8.0 / hours
    last = ks[-1] if ks else None
    vals, est = [], None
    for idx, t in enumerate(times):
        i0, i1 = bisect_left(ks, t), bisect_left(ks, t + step_ms)
        part = rs[i0:i1]
        live = nr is not None and last is not None and t + step_ms > last and (now_ms is None or t <= now_ms)
        if not part and i0 < len(ks):                       # bougie plus courte que la période : le versement qui clôt sa période
            part = [rs[i0]] if ks[i0] - t <= 8 * 3_600_000 + FUND_LAG_MS else []
            live = False
        if live and (not part or i1 >= len(ks)):
            part = part + [nr]
            est = idx if est is None else est
        vals.append(sum(part) / len(part) if part else None)
    week = [r for k, r in zip(ks, rs) if last is not None and k > last - 7 * 86_400_000]
    return {"funding": vals, "fundEst": est, "fundNow": nr, "fundAvg7": sum(week) / len(week) if week else None,
            "fundSince": rows[0][0] if rows else None}
