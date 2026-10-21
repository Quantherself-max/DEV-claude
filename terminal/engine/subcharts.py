"""Indicateurs sous le graphique (V30) : l'INTÉRÊT OUVERT en bougies (ouverture, plus haut, plus bas, clôture de chaque bougie du
graphique, à partir des relevés toutes les 5 minutes de Binance) et le DELTA de chaque bougie (volume acheteur agressif moins volume
vendeur agressif) avec son cumul, le CVD. Module PUR."""
from __future__ import annotations
from bisect import bisect_right


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
