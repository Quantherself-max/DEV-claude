"""Liquidite VISIBLE DANS LE PRIX et balayages (sweeps), calculables sur n'importe quel historique OHLC.

Une « poche de liquidite » est un endroit ou les ordres d'arret s'accumulent parce que tout le monde les voit :
  - plus bas / plus haut de la veille, de la semaine, du mois precedents (PDL, PWL, PML ...) et de la periode en cours ;
  - creux / sommets recents (pivots 1 h) ; deux pivots au meme prix (« egaux ») forment la poche la plus nette.
Les stops des acheteurs sont SOUS un creux (cote « long »), ceux des vendeurs AU-DESSUS d'un sommet (cote « short »).

Un balayage est une meche qui perce la poche puis une cloture qui la REPREND (retour de l'autre cote) : les ordres d'arret ont
ete pris, le prix n'a pas tenu au-dela. C'est le declencheur des « reprises » (voir signals.py).

Complement de l'estimation par l'Open Interest (liquidity.py, 29 jours seulement) : ces poches-ci existent sur tout
l'historique, donc elles se TESTENT (backtest.py). Module PUR (aucun reseau)."""
from bisect import bisect_left, bisect_right

from .fine import Bars

EQUAL_PCT = 0.0015            # deux pivots a moins de 0,15 % = niveaux « egaux »
BAND_ATR = 0.25               # epaisseur de la poche : 0,25 ATR au-dela du niveau
SWING_N = 3                   # un pivot = extreme sur 3 bougies de chaque cote
SWING_DAYS = 7
SCORES = {"M": 95, "W": 85, "D": 70, "mH": 80, "wH": 65, "dH": 55}        # mois/semaine/jour precedents ; periode en cours
PREV_TXT = {"D": "de la veille", "W": "de la semaine dernière", "M": "du mois dernier"}
CUR_TXT = {"D": "du jour", "W": "de la semaine", "M": "du mois"}


def swing_points(b: Bars, n: int = SWING_N):
    """Pivots confirmes sur des bougies b (1 h conseille). Renvoie (hauts, bas) : listes triees de (t_confirmation, t_pivot, prix)."""
    hi, lo = [], []
    H, L, T, step = b.h, b.l, b.t, b.step
    for j in range(n, len(T) - n):
        x = H[j]
        if all(x > H[j - q] for q in range(1, n + 1)) and all(x >= H[j + q] for q in range(1, n + 1)):
            hi.append((T[j + n] + step, T[j], x))
        y = L[j]
        if all(y < L[j - q] for q in range(1, n + 1)) and all(y <= L[j + q] for q in range(1, n + 1)):
            lo.append((T[j + n] + step, T[j], y))
    return hi, lo


class PriceLiquidity:
    def __init__(self, b1h: Bars, n: int = SWING_N):
        self.b = b1h
        self.highs, self.lows = swing_points(b1h, n)
        self._hc = [x[0] for x in self.highs]
        self._lc = [x[0] for x in self.lows]
        self._cache = (None, None)

    def recent_swings(self, now_ms: int, days: float = SWING_DAYS):
        """Pivots deja confirmes a now_ms et vieux de moins de `days` jours."""
        t0 = now_ms - days * 86_400_000
        out = {}
        for key, arr, conf in (("high", self.highs, self._hc), ("low", self.lows, self._lc)):
            j1 = bisect_right(conf, now_ms)
            j0 = bisect_left([a[1] for a in arr[max(0, j1 - 400):j1]], t0) + max(0, j1 - 400)
            out[key] = arr[j0:j1]
        return out

    def _swing_candidates(self, now_ms: int):
        """Creux / sommets recents (mis en memoire une heure : ils ne changent qu'a la confirmation d'un nouveau pivot)."""
        hour = now_ms // 3_600_000
        if self._cache[0] == hour:
            return self._cache[1]
        sw = self.recent_swings(now_ms)
        t72 = now_ms - 72 * 3_600_000
        lows72 = [x[2] for x in sw["low"] if x[1] >= t72]
        highs72 = [x[2] for x in sw["high"] if x[1] >= t72]
        lowest, highest = (min(lows72) if lows72 else None), (max(highs72) if highs72 else None)
        out = [(p, "low", 60 if p == lowest else 50, "creux sur 1 h", tp) for _, tp, p in sw["low"]]
        out += [(p, "high", 60 if p == highest else 50, "sommet sur 1 h", tp) for _, tp, p in sw["high"]]
        self._cache = (hour, out)
        return out

    def formed_at(self, level: float, kind: str, now_ms: int, forming=None):
        """Derniere fois que le prix a traite a ce niveau (naissance de la poche : depuis, ses ordres d'arret s'accumulent).
        kind 'low' : derniere bougie dont le plus bas l'atteint ; 'high' : le plus haut. `forming` : bougie 1 h en cours (t, h, l).
        None si ce n'est pas arrive dans l'historique charge (120 jours)."""
        eps = level * 1e-9
        if forming is not None and (forming.l <= level + eps if kind == "low" else forming.h >= level - eps):
            return int(forming.t)
        b = self.b
        j = bisect_right(b.t, now_ms - b.step) - 1
        arr = b.l if kind == "low" else b.h
        while j >= 0:
            if (arr[j] <= level + eps) if kind == "low" else (arr[j] >= level - eps):
                return int(b.t[j])
            j -= 1
        return None

    def pools(self, price: float, atr: float, now_ms: int, ext, max_dist_pct: float = 0.10, forming=None):
        """Poches pres du prix. `ext` : [(nom, prix, 'low'|'high', score, instant_de_naissance_ms)] (extremes de periodes, recalcules
        a chaque appel : le plus bas du jour peut etre balaye 20 minutes apres sa creation).
        Renvoie des dicts compatibles avec les poches OI : side ('long' = stops sous un creux), price, lo, hi, score, src, born."""
        cand = [(p, kind, score, name, self.formed_at(p, kind, now_ms, forming) or born) for name, p, kind, score, born in ext if p]
        cand += self._swing_candidates(now_ms)
        cand = [c for c in cand if abs(c[0] / price - 1) <= max_dist_pct]
        out = []
        w = BAND_ATR * atr
        for kind in ("low", "high"):
            grp = sorted([c for c in cand if c[1] == kind], key=lambda c: c[0])
            cur = []
            for c in grp + [None]:
                if c is not None and (not cur or c[0] <= cur[0][0] * (1 + EQUAL_PCT)):
                    cur.append(c)
                    continue
                if cur:
                    best = max(cur, key=lambda c2: c2[2])
                    px = sum(c2[0] for c2 in cur) / len(cur)
                    score = min(100, best[2] + 12 * (len(cur) - 1))
                    lo, hi = (px - w, px) if kind == "low" else (px, px + w)
                    out.append({"side": "long" if kind == "low" else "short", "price": px, "lo": lo, "hi": hi, "score": score,
                                "src": best[3] + (" (égaux)" if len(cur) > 1 else ""), "born": min(c2[4] for c2 in cur), "size": 0.0, "magnet": False})
                cur = [c] if c is not None else []
        return out


def extremes_from_trackers(tr, now_ms: int):
    """Extremes de periodes depuis des PeriodTracker (D, W, M) : precedents et en cours. Retourne la liste `ext` de pools()."""
    out = []
    for kind in ("D", "W", "M"):
        t = tr[kind]
        prev = t.prev
        if prev:
            out.append((f"plus bas {PREV_TXT[kind]}", prev["low"], "low", SCORES[kind], now_ms))
            out.append((f"plus haut {PREV_TXT[kind]}", prev["high"], "high", SCORES[kind], now_ms))
        a = t.acc
        if a.n:
            sc = SCORES[kind.lower() + "H"]
            out.append((f"plus bas {CUR_TXT[kind]}", a.low, "low", sc, a.start))
            out.append((f"plus haut {CUR_TXT[kind]}", a.high, "high", sc, a.start))
    return out


def detect_sweeps(pools, b: Bars, i: int, now_ms: int, hours: float = 8.0, reclaim_bars: int = 6, eps: float = 0.0002):
    """Balayages recents (bougies fines `b`, derniere bougie FERMEE d'index i).
    Une poche « long » (creux) est balayee si une bougie descend sous le creux (de plus de eps) puis qu'une cloture repasse
    au-dessus dans les `reclaim_bars` bougies suivantes ; symetrique pour les sommets. Renvoie des evenements
    {t, side, price, to, frac, src} comme ceux du moteur OI (to = pointe extreme de la meche)."""
    n_bars = int(hours * 3_600_000 / b.step)
    j0 = max(0, i - n_bars + 1)
    if i < 1:
        return []
    H, L, C, T = b.h, b.l, b.c, b.t
    lo_w = min(L[j0:i + 1])
    hi_w = max(H[j0:i + 1])
    out = []
    for p in pools:
        lvl = p["price"]
        if p["side"] == "long":
            if lo_w >= lvl * (1 - eps):
                continue
            jp = next((j for j in range(j0, i + 1) if L[j] < lvl * (1 - eps)), None)
            if jp is None:
                continue
            jr = next((j for j in range(jp, min(i, jp + reclaim_bars) + 1) if C[j] > lvl), None)
            if jr is None or C[i] <= lvl:
                continue
            out.append({"t": int(T[jr] + b.step), "side": "long", "price": lvl, "to": min(L[jp:jr + 1]), "frac": p["score"] / 200.0, "src": p["src"]})
        else:
            if hi_w <= lvl * (1 + eps):
                continue
            jp = next((j for j in range(j0, i + 1) if H[j] > lvl * (1 + eps)), None)
            if jp is None:
                continue
            jr = next((j for j in range(jp, min(i, jp + reclaim_bars) + 1) if C[j] < lvl), None)
            if jr is None or C[i] >= lvl:
                continue
            out.append({"t": int(T[jr] + b.step), "side": "short", "price": lvl, "to": max(H[jp:jr + 1]), "frac": p["score"] / 200.0, "src": p["src"]})
    return out
