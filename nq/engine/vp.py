"""Volume profile au tick : POC, zone de valeur (VAH / VAL), noeuds de volume fort (HVN) et faible (LVN). Module PUR.

Le profil se lit directement dans une `Ladder` (volume echange a chaque prix, acheteurs et vendeurs separes) : aucune repartition supposee du
volume entre le haut et le bas des barres, contrairement a un profil construit sur des bougies.

Lignes : on regroupe `row_ticks` ticks par ligne (NQ : 4 ticks = 1 point). Les lignes sont alignees sur des multiples de `row_ticks`
(une ligne ne change donc pas de bornes quand le profil s'etend) .
  - POC : le tick le plus echange de la ligne la plus fournie (a egalite, la plus proche du milieu du profil) ;
  - zone de valeur (methode des bourses) : on part de la ligne du POC et on ajoute a chaque pas la paire de lignes la plus fournie, au-dessus
    ou en dessous (les deux lignes suivantes de chaque cote sont comparees), jusqu'a `va_pct` du volume (70 % par defaut) ;
    VAH = haut de la derniere ligne incluse en haut, VAL = bas de la derniere ligne incluse en bas ;
  - HVN : sommets du profil lisse (zones d'acceptation, le prix y reste) ; LVN : creux entre deux sommets (zones de rejet, le prix les traverse vite)."""
import math

ROW_CHOICES = (1, 2, 4, 8, 12, 16, 20, 40, 80, 160, 400)


def auto_row_ticks(span_ticks: int, max_rows: int = 140, minimum: int = 1) -> int:
    """Plus petit regroupement « rond » qui garde le profil sous `max_rows` lignes."""
    need = max(minimum, math.ceil(max(span_ticks, 1) / max_rows))
    for c in ROW_CHOICES:
        if c >= need:
            return c
    return ROW_CHOICES[-1]


def rows_of(rows: dict, row_ticks: int) -> tuple:
    """Regroupe les lignes d'une Ladder. Renvoie (indice de la 1re ligne, [[vendeur, acheteur], ...] du bas vers le haut). Vide : (0, [])."""
    if not rows:
        return 0, []
    r0 = min(rows) // row_ticks
    r1 = max(rows) // row_ticks
    out = [[0.0, 0.0] for _ in range(r1 - r0 + 1)]
    for idx, (s, b) in rows.items():
        a = out[idx // row_ticks - r0]
        a[0] += s
        a[1] += b
    return r0, out


def value_area(tot: list, poc: int, va_pct: float = 0.70) -> tuple:
    """(ligne haute, ligne basse) de la zone de valeur ; `tot` = volume total de chaque ligne."""
    n = len(tot)
    target = sum(tot) * va_pct
    acc, up, dn = tot[poc], poc, poc
    while acc < target and (up < n - 1 or dn > 0):
        u = (tot[up + 1] + (tot[up + 2] if up + 2 < n else 0.0)) if up < n - 1 else -1.0
        d = (tot[dn - 1] + (tot[dn - 2] if dn - 2 >= 0 else 0.0)) if dn > 0 else -1.0
        if u >= d:
            step = 2 if up + 2 < n else 1
            acc += tot[up + 1] + (tot[up + 2] if step == 2 else 0.0)
            up += step
        else:
            step = 2 if dn - 2 >= 0 else 1
            acc += tot[dn - 1] + (tot[dn - 2] if step == 2 else 0.0)
            dn -= step
    return up, dn


def nodes(tot: list, min_share: float = 0.45) -> tuple:
    """(HVN, LVN) : listes d'indices de ligne. Sommets du profil lisse qui dominent leurs voisins, et creux entre deux sommets consecutifs."""
    n = len(tot)
    if n < 9 or sum(tot) <= 0:
        return [], []
    r = max(1, n // 25)
    sm = [sum(tot[max(0, i - r):i + r + 1]) / (min(n, i + r + 1) - max(0, i - r)) for i in range(n)]
    mx = max(sm)
    w = max(2, n // 12)
    peaks = []
    for i in range(n):
        if sm[i] >= min_share * mx and all(sm[i] >= sm[j] for j in range(max(0, i - w), min(n, i + w + 1))):
            if peaks and i - peaks[-1] <= w:                  # plateau : un seul sommet
                if sm[i] > sm[peaks[-1]]:
                    peaks[-1] = i
            else:
                peaks.append(i)
    lvn = []
    for a, b in zip(peaks, peaks[1:]):
        seg = sm[a + 1:b] or [sm[a]]
        low = min(seg)
        flat = [j for j in range(a + 1, b) if sm[j] <= low * 1.02 + 1e-12] or [a]
        j = flat[len(flat) // 2]
        if sm[j] <= 0.6 * min(sm[a], sm[b]):                   # un vrai creux, pas un simple replat
            lvn.append(j)
    return peaks, lvn


def stats(ladder, row_ticks: int | None = None, va_pct: float = 0.70, max_rows: int = 140, min_row_ticks: int = 1, cache: dict | None = None) -> dict | None:
    """Profil complet d'une Ladder, pret pour l'affichage : niveaux cles + lignes. None si vide.

    prix des lignes : `lo` / `hi` = bornes de la ligne (bas = premier tick, haut = dernier tick de la ligne).
    `cache` (optionnel) : memorise le resultat par (identite de la ladder, volume) -- utile au backtest, ou le meme profil (veille) est relu a chaque
    barre. Tant que le volume ne change pas, la ladder n'a pas change : on renvoie le resultat garde. (Le terminal en direct ne passe pas de cache.)"""
    if ladder.empty():
        return None
    if cache is not None:
        ck = (id(ladder), round(ladder.volume, 3), row_ticks, va_pct, max_rows, min_row_ticks)
        hit = cache.get(ck)
        if hit is not None:
            return hit
    tick = ladder.tick
    span = max(ladder.rows) - min(ladder.rows) + 1
    rt = row_ticks or auto_row_ticks(span, max_rows, min_row_ticks)
    r0, rows = rows_of(ladder.rows, rt)
    tot = [s + b for s, b in rows]
    mid = (len(tot) - 1) / 2.0
    pi = max(range(len(tot)), key=lambda i: (tot[i], -abs(i - mid)))
    up, dn = value_area(tot, pi, va_pct)
    # POC exact : le tick le plus echange de la ligne du POC
    lo_idx = (r0 + pi) * rt
    cand = [(ladder.rows[i][0] + ladder.rows[i][1], i) for i in range(lo_idx, lo_idx + rt) if i in ladder.rows]
    poc_idx = max(cand, key=lambda x: (x[0], -abs(x[1] - (lo_idx + (rt - 1) / 2.0))))[1]
    hvn, lvn = nodes(tot)

    def lo_p(i): return round((r0 + i) * rt * tick, 10)
    def hi_p(i): return round(((r0 + i + 1) * rt - 1) * tick, 10)

    out = {
        "rowTicks": rt, "rowPts": round(rt * tick, 10), "total": sum(tot), "delta": ladder.delta,
        "poc": round(poc_idx * tick, 10), "vah": hi_p(up), "val": lo_p(dn),
        "hi": ladder.hi, "lo": ladder.lo, "vwap": ladder.vwap, "sd": ladder.sd,
        "hvn": [round((lo_p(i) + hi_p(i)) / 2.0, 10) for i in hvn],
        "lvn": [round((lo_p(i) + hi_p(i)) / 2.0, 10) for i in lvn],
        "rows": [{"lo": lo_p(i), "hi": hi_p(i), "s": rows[i][0], "b": rows[i][1], "va": dn <= i <= up, "poc": i == pi} for i in range(len(rows))],
    }
    if cache is not None:
        if len(cache) > 4000:
            cache.clear()
        cache[ck] = out
    return out


def levels(ladder, row_ticks: int | None = None) -> dict | None:
    """Seulement {poc, vah, val, hi, lo, vwap} d'une Ladder (sans les lignes), None si vide."""
    st = stats(ladder, row_ticks)
    if st is None:
        return None
    return {k: st[k] for k in ("poc", "vah", "val", "hi", "lo", "vwap", "total", "delta")}
