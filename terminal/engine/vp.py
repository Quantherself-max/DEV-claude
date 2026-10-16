"""Volume Profile : POC, Value Area (VAH/VAL), HVN. Port fidele du moteur Pine (grille fine 0.03 %,
regroupement en lignes d'affichage, Value Area par paires de lignes, HVN sur profil lisse)."""
import math
from .grid import Grid, rnd

VP_GRID = Grid(0.03)
BIN_PCT = 0.03


class Profile:
    """Volume reparti uniformement entre le low et le high de chaque bougie, sur la grille fine."""
    __slots__ = ("bins", "lo", "hi", "version")

    def __init__(self):
        self.bins: dict[int, float] = {}
        self.lo = None
        self.hi = None
        self.version = 0

    def add(self, low: float, high: float, vol: float) -> None:
        a, b = VP_GRID.idx(low), VP_GRID.idx(high)
        share = vol / (b - a + 1)
        bins = self.bins
        for i in range(a, b + 1):
            bins[i] = bins.get(i, 0.0) + share
        self.lo = a if self.lo is None else min(self.lo, a)
        self.hi = b if self.hi is None else max(self.hi, b)
        self.version += 1

    def empty(self) -> bool:
        return self.lo is None


def auto_rows(n_bars: int) -> int:
    """Nombre de lignes selon la densite de donnees : 6 x racine(barres), entre 30 et 160."""
    return int(max(30, min(160, rnd(6.0 * math.sqrt(max(n_bars, 1))))))


def agg_rows(p: Profile, target: int):
    """Regroupe les bins fins en au plus `target` lignes. Renvoie (lignes, bin de depart, bins par ligne)."""
    if p.empty():
        return [], 0, 1
    n = p.hi - p.lo + 1
    g = max(1, math.ceil(n / float(target)))
    nr = math.ceil(n / g)
    rows = [0.0] * nr
    for i, v in p.bins.items():
        rows[(i - p.lo) // g] += v
    return rows, p.lo, g


def stats(rows, b0, g, va_pct=70.0):
    """(POC, VAH, VAL) : la Value Area grandit en ajoutant la paire de lignes la plus fournie."""
    nr = len(rows)
    if nr < 1:
        return None, None, None
    hi = nr - 1
    tot = sum(rows)
    best, poc_i = -1.0, 0
    for i, v in enumerate(rows):
        if v > best:
            best, poc_i = v, i
    acc, target, up, dn = best, tot * va_pct / 100.0, poc_i, poc_i
    while acc < target and (up < hi or dn > 0):
        up_v = dn_v = 0.0
        if up < hi:
            up_v = rows[up + 1] + (rows[up + 2] if up + 1 < hi else 0.0)
        if dn > 0:
            dn_v = rows[dn - 1] + (rows[dn - 2] if dn - 1 > 0 else 0.0)
        if up < hi and (dn <= 0 or up_v >= dn_v):
            acc += up_v
            up = min(hi, up + 2)
        else:
            acc += dn_v
            dn = max(0, dn - 2)
    return (VP_GRID.price(b0 + poc_i * g, 0.5 * g), VP_GRID.price(b0 + up * g, 1.0 * g),
            VP_GRID.price(b0 + dn * g, 0.0))


def hvn(rows, b0, g, hvn_n=1, win_pct=1.0, min_pct=50.0):
    """HVN : pics du profil lisse, hors zone du POC (au plus hvn_n). Renvoie [prix, ...]."""
    nb = len(rows)
    out = []
    w = max(2, min(rnd(win_pct / (BIN_PCT * g)), rnd(nb / 5.0)))
    s = max(1, rnd(w / 3.0))
    if hvn_n <= 0 or nb - 1 < 2 * w:
        return out
    sm = []
    for i in range(nb):
        a = max(0, i - s)
        b = min(nb - 1, i + s)
        sm.append(sum(rows[a:b + 1]) / (b - a + 1))
    mx, pk = 0.0, 0
    for q, v in enumerate(sm):
        if v > mx:
            mx, pk = v, q
    poc_i = max(range(nb), key=lambda i: rows[i])       # le POC brut est exclu aussi (pas seulement le pic lisse)
    b1 = b2 = 0.0
    i1 = i2 = -1
    for q in range(nb):
        v = sm[q]
        if v >= min_pct / 100.0 * mx and abs(q - pk) > w and abs(q - poc_i) > w:
            ok = True
            for r in range(max(0, q - w), min(nb - 1, q + w) + 1):
                if (r < q and sm[r] >= v) or (r > q and sm[r] > v):
                    ok = False
            if ok:
                if v > b1:
                    b2, i2, b1, i1 = b1, i1, v, q
                elif v > b2:
                    b2, i2 = v, q
    if i1 >= 0:
        out.append(VP_GRID.price(b0 + i1 * g, 0.5 * g))
    if i2 >= 0 and hvn_n >= 2:
        out.append(VP_GRID.price(b0 + i2 * g, 0.5 * g))
    return out


def levels(p: Profile, n_bars: int, hvn_n=1):
    """Niveaux d'un profil : {poc, vah, val, hvn:[...]} (ou None si vide)."""
    if p.empty():
        return None
    rows, b0, g = agg_rows(p, auto_rows(n_bars))
    poc, vah, val = stats(rows, b0, g)
    return {"poc": poc, "vah": vah, "val": val, "hvn": hvn(rows, b0, g, hvn_n)}
