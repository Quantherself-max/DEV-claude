"""Profil de volume de la seance (V15, affine en V19) : volume echange par tranche de prix depuis 00 h UTC (ou la semaine, le mois), avec la part des
acheteurs agressifs, comme le profil colle a l'echelle des prix des terminaux d'order flow. Bougies 5 min (volume acheteur agressif reel de Binance).

V19 : le volume d'une bougie n'est plus etale uniformement entre son plus bas et son plus haut, il suit le TRAJET probable du prix dans la bougie
(haussiere : ouverture -> plus bas -> plus haut -> cloture ; baissiere : ouverture -> plus haut -> plus bas -> cloture). Les prix traverses deux fois
recoivent deux fois plus de volume, ce qui rapproche le profil du temps reellement passe a chaque prix. S'y ajoutent les noeuds de volume fort
(HVN, zones d'acceptation) et faible (LVN, zones de rejet que le prix traverse vite) et le POC / VAH / VAL EVOLUTIFS (leur valeur au fil de la
seance). Module PUR."""
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


def path_of(k):
    """Trajet probable dans la bougie : points successifs (ouverture, extremes, cloture)."""
    if k.c >= k.o:
        return (k.o, k.l, k.h, k.c)
    return (k.o, k.h, k.l, k.c)


def spread(k, k0: int, n: int, step: float, vol, buy, path: bool = True) -> None:
    """Ajoute le volume (et le volume acheteur) de la bougie k aux lignes [k0, k0 + n) d'un pas `step`.
    path=True : le long du trajet probable ; sinon uniforme entre le plus bas et le plus haut (ancienne methode)."""
    v, tb = k.v, k.tb
    if v <= 0:
        return
    segs = []
    if path:
        p = path_of(k)
        segs = [(min(a, b), max(a, b)) for a, b in zip(p, p[1:]) if b != a]
    elif k.h > k.l:
        segs = [(k.l, k.h)]
    total = sum(b - a for a, b in segs)
    if total <= 0:                                           # bougie sans amplitude : tout a la cloture
        j = max(0, min(n - 1, math.floor(k.c / step + 1e-9) - k0))
        vol[j] += v
        buy[j] += tb
        return
    for a, b in segs:
        w = (b - a) / total
        j0, j1 = math.floor(a / step + 1e-9) - k0, math.floor(b / step + 1e-9) - k0
        if j0 == j1:
            j = max(0, min(n - 1, j0))
            vol[j] += v * w
            buy[j] += tb * w
            continue
        span = b - a
        for j in range(max(0, j0), min(n - 1, j1) + 1):
            r0, r1 = (k0 + j) * step, (k0 + j + 1) * step
            f = max(0.0, min(b, r1) - max(a, r0)) / span * w
            vol[j] += v * f
            buy[j] += tb * f


def value_area(vol, poc: int):
    """(haut, bas) de la zone de valeur (70 % du volume) en indices de ligne, en ajoutant a chaque fois le cote le plus fourni."""
    n, tot = len(vol), sum(vol)
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
    return up, dn


def nodes(vol, k0: int, step: float, poc: int):
    """Noeuds de volume : HVN (pics du profil lisse, zones d'acceptation) et LVN (creux marques entre deux pics, zones de rejet que le prix
    traverse vite). Renvoie (hvn, lvn) : listes de [prix bas, prix haut, part du volume], sans chevauchement."""
    n = len(vol)
    tot = sum(vol)
    if n < 9 or tot <= 0:
        return [], []
    r = max(1, n // 25)                                      # lissage sur ~4 % de la hauteur du profil
    sm = [sum(vol[max(0, i - r):i + r + 1]) / (min(n, i + r + 1) - max(0, i - r)) for i in range(n)]
    mx = max(sm)
    w = max(2, n // 12)                                      # un pic doit dominer ses voisins sur ~8 % du profil
    peaks = []
    for i in range(n):
        if sm[i] >= 0.45 * mx and all(sm[i] >= sm[j] for j in range(max(0, i - w), min(n, i + w + 1))):
            if peaks and i - peaks[-1] <= w:                 # plateau : un seul pic
                if sm[i] > sm[peaks[-1]]:
                    peaks[-1] = i
            else:
                peaks.append(i)
    troughs = []
    for a, b in zip(peaks, peaks[1:]):                      # creux : milieu du plateau le plus bas entre deux pics
        lowest = min(sm[a + 1:b]) if b - a > 1 else sm[a]
        flat = [j for j in range(a + 1, b) if sm[j] <= lowest * 1.02 + 1e-12] or [a]
        troughs.append(flat[len(flat) // 2])
    hvn = []
    for k, i in enumerate(peaks):
        lim_lo = troughs[k - 1] + 1 if 0 < k <= len(troughs) else 0
        lim_hi = troughs[k] - 1 if k < len(troughs) else n - 1
        lo = hi = i
        while lo - 1 >= max(lim_lo, i - 2 * w) and sm[lo - 1] >= 0.7 * sm[i]:
            lo -= 1
        while hi + 1 <= min(lim_hi, i + 2 * w) and sm[hi + 1] >= 0.7 * sm[i]:
            hi += 1
        hvn.append([(k0 + lo) * step, (k0 + hi + 1) * step, sum(vol[lo:hi + 1]) / tot])
    lvn = []
    for (a, b), m in zip(zip(peaks, peaks[1:]), troughs):
        top = min(sm[a], sm[b])
        if sm[m] > 0.5 * top:
            continue                                         # creux trop peu marque : pas un noeud de rejet
        thr = sm[m] + 0.2 * (top - sm[m])                    # tout le creux, jusqu'a 20 % de la remontee vers les pics
        lo = hi = m
        while lo - 1 > a and sm[lo - 1] <= thr:
            lo -= 1
        while hi + 1 < b and sm[hi + 1] <= thr:
            hi += 1
        lvn.append([(k0 + lo) * step, (k0 + hi + 1) * step, sum(vol[lo:hi + 1]) / tot])
    return hvn, lvn


def shape(vol, poc: int):
    """Forme du profil : « P » (volume en haut : rachats / achats tardifs), « b » (volume en bas : liquidation), « D » (equilibre)."""
    n, tot = len(vol), sum(vol)
    if n < 6 or tot <= 0:
        return None
    upper = sum(vol[int(n * 0.6):]) / tot
    lower = sum(vol[:int(n * 0.4) + 1]) / tot
    pos = (poc + 0.5) / n
    if pos >= 0.6 and upper >= 0.5:
        return "P"
    if pos <= 0.4 and lower >= 0.5:
        return "b"
    return "D"


def build(bars, target_rows: int = 100, marks: int = 3, path: bool = True, developing: bool = True):
    """bars : bougies (t, o, h, l, c, v, tb) de la seance. Renvoie None s'il n'y a pas de volume."""
    sel = [k for k in bars if k.v > 0]
    if not sel:
        return None
    lo, hi = min(k.l for k in sel), max(k.h for k in sel)
    step = nice_step(max(hi - lo, 1e-9) / max(4, target_rows))
    k0 = math.floor(lo / step + 1e-9)
    n = math.floor(hi / step + 1e-9) - k0 + 1
    vol, buy = [0.0] * n, [0.0] * n
    has_tb = any(k.tb > 0 for k in sel)
    dev = []
    every = max(1, len(sel) // 96)                           # POC / VAH / VAL evolutifs : au plus ~100 points par seance
    for i, k in enumerate(sel):
        spread(k, k0, n, step, vol, buy, path)
        if developing and (i % every == every - 1 or i == len(sel) - 1):
            pj = max(range(n), key=lambda j: vol[j])
            up, dn = value_area(vol, pj)
            dev.append([k.t, (k0 + pj + 0.5) * step, (k0 + up + 1) * step, (k0 + dn) * step])
    tot = sum(vol)
    poc = max(range(n), key=lambda j: vol[j])
    up, dn = value_area(vol, poc)
    rows = [[round((k0 + j) * step, 10), vol[j], buy[j] if has_tb else None] for j in range(n)]
    mx = max(vol)
    cand = [j for j in range(n) if vol[j] >= 0.25 * mx] if has_tb else []
    top = sorted(cand, key=lambda j: -abs(2 * buy[j] - vol[j]))[:marks]
    hvn, lvn = nodes(vol, k0, step, poc)
    return {"step": step, "rows": rows, "poc": (k0 + poc + 0.5) * step, "vah": (k0 + up + 1) * step, "val": (k0 + dn) * step,
            "high": hi, "low": lo, "volume": tot, "buyShare": (sum(buy) / tot) if has_tb and tot else None,
            "delta": (2 * sum(buy) - tot) if has_tb else None,
            "marks": [[(k0 + j + 0.5) * step, 2 * buy[j] - vol[j]] for j in sorted(top)], "bars": len(sel),
            "hvn": hvn, "lvn": lvn, "shape": shape(vol, poc), "developing": dev, "method": "trajet" if path else "uniforme"}
