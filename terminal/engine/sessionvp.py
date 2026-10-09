"""Profil de volume de la seance (V15) : volume echange par tranche de prix depuis 00 h UTC, avec la part des acheteurs agressifs, comme le
profil colle a l'echelle des prix des terminaux d'order flow. Bougies 5 min (volume acheteur agressif reel de Binance) : le volume d'une
bougie est reparti sur sa fourchette haut - bas. Module PUR."""
import math

VA_PCT = 0.70


def nice_step(raw: float) -> float:
    """Pas « rond » (1, 2, 2,5 ou 5 fois une puissance de 10) au moins egal a raw."""
    if raw <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if m * e >= raw * (1 - 1e-12):
            return m * e
    return 10 * e


def build(bars, target_rows: int = 100, marks: int = 3):
    """bars : bougies (t, o, h, l, c, v, tb) de la seance. Renvoie None s'il n'y a pas de volume."""
    sel = [k for k in bars if k.v > 0]
    if not sel:
        return None
    lo, hi = min(k.l for k in sel), max(k.h for k in sel)
    step = nice_step(max(hi - lo, 1e-9) / max(4, target_rows))
    k0 = math.floor(lo / step)
    n = math.floor(hi / step) - k0 + 1
    vol, buy = [0.0] * n, [0.0] * n
    has_tb = any(k.tb > 0 for k in sel)
    for k in sel:
        a, b = k.l, k.h
        j0, j1 = math.floor(a / step) - k0, math.floor(b / step) - k0
        if b <= a or j0 == j1:
            j = max(0, min(n - 1, math.floor(k.c / step) - k0 if b <= a else j0))
            vol[j] += k.v
            buy[j] += k.tb
            continue
        span = b - a
        for j in range(max(0, j0), min(n - 1, j1) + 1):
            r0, r1 = (k0 + j) * step, (k0 + j + 1) * step
            w = max(0.0, min(b, r1) - max(a, r0)) / span
            vol[j] += k.v * w
            buy[j] += k.tb * w
    tot = sum(vol)
    poc = max(range(n), key=lambda j: vol[j])
    acc, up, dn = vol[poc], poc, poc
    while acc < tot * VA_PCT and (up < n - 1 or dn > 0):
        u = vol[up + 1] if up < n - 1 else -1.0
        d = vol[dn - 1] if dn > 0 else -1.0
        if u >= d:
            up += 1
            acc += vol[up]
        else:
            dn -= 1
            acc += vol[dn]
    rows = [[round((k0 + j) * step, 10), vol[j], buy[j] if has_tb else None] for j in range(n)]
    mx = max(vol)
    cand = [j for j in range(n) if vol[j] >= 0.25 * mx] if has_tb else []
    top = sorted(cand, key=lambda j: -abs(2 * buy[j] - vol[j]))[:marks]
    return {"step": step, "rows": rows, "poc": (k0 + poc + 0.5) * step, "vah": (k0 + up + 1) * step, "val": (k0 + dn) * step,
            "high": hi, "low": lo, "volume": tot, "buyShare": (sum(buy) / tot) if has_tb and tot else None,
            "marks": [[(k0 + j + 0.5) * step, 2 * buy[j] - vol[j]] for j in sorted(top)], "bars": len(sel)}
