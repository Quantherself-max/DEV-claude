"""Poches de liquidation ESTIMEES a partir de l'Open Interest. Port du script Pine LiqLevels :
chaque hausse d'OI = nouvelles positions au prix de la sous-bougie, reparties longs / shorts (direction
de la bougie), puis par levier ; prix de liquidation = formule isolee + marge de maintenance. Un niveau
disparait quand le prix le touche ; quand l'OI baisse, les niveaux restants sont reduits d'autant.
C'est une estimation (proxy), pas de vraies liquidations."""
from bisect import insort

from .grid import Grid, rnd

LIQ_GRID = Grid(0.05)


class LiqEngine:
    def __init__(self, levs=(100, 50, 25, 10), wts=(10, 20, 30, 40), mmr=0.004, split="dir", shrink=True):
        self.levs, self.wts, self.mmr, self.split, self.shrink = levs, wts, mmr, split, shrink
        self.wsum = max(sum(wts), 1e-4)
        self.lsz: dict[int, float] = {}
        self.ssz: dict[int, float] = {}
        self.lact: list[int] = []     # bins actifs tries par prix croissant
        self.sact: list[int] = []
        self.g = 1.0                  # echelle globale (reduction quand l'OI baisse)
        self.oi_last = None
        self.steps = 0

    # --- niveaux ---
    def _add(self, sz, act, price, amt):
        i = LIQ_GRID.idx(price)
        if sz.get(i, 0.0) <= 0.0:
            insort(act, i)
        sz[i] = sz.get(i, 0.0) + amt / self.g

    def _sweep_long(self, low):
        hit = 0
        while self.lact and LIQ_GRID.price(self.lact[-1]) >= low:
            self.lsz[self.lact.pop()] = 0.0
            hit += 1
        return hit

    def _sweep_short(self, high):
        hit = 0
        while self.sact and LIQ_GRID.price(self.sact[0]) <= high:
            self.ssz[self.sact.pop(0)] = 0.0
            hit += 1
        return hit

    def _scale_down(self, f):
        g = self.g * f
        if g < 1e-6:
            for i in self.lact:
                self.lsz[i] *= g
            for i in self.sact:
                self.ssz[i] *= g
            g = 1.0
        self.g = g

    def step(self, oi_now, h, l, c, vol=0.0):   # vol : inutilise (conserve pour compatibilite)
        """Un pas de temps (bougie 5 min). oi_now peut etre None (alors seule la touche est traitee)."""
        hits = self._sweep_long(l) + self._sweep_short(h)
        oi_last = self.oi_last
        d = 0.0 if (oi_now is None or oi_last is None) else oi_now - oi_last
        if oi_now is not None:
            self.oi_last = oi_now
        if self.shrink and hits == 0 and d < 0 and oi_last and oi_last > 0:
            self._scale_down(oi_now / oi_last)
        # OI manquant (publie avec un leger retard) : on ne cree rien. Surtout pas de repli sur le volume,
        # qui n'a pas la meme echelle que la variation d'OI.
        amt = max(d, 0.0) if oi_now is not None else 0.0
        self.steps += 1
        if amt <= 0:
            return
        px = (h + l + c) / 3.0
        rng = h - l
        clv = ((c - l) - (h - c)) / rng if rng > 0 else 0.0
        l_sh = 0.5 if self.split == "50" else max(0.2, min(0.8, 0.5 + 0.5 * clv))
        for lev, w in zip(self.levs, self.wts):
            wq = w / self.wsum
            if lev <= 1 or wq <= 0:
                continue
            pl = px * (1.0 - 1.0 / lev + self.mmr)
            ps = px * (1.0 + 1.0 / lev - self.mmr)
            if pl < l:
                self._add(self.lsz, self.lact, pl, amt * l_sh * wq)
            if ps > h:
                self._add(self.ssz, self.sact, ps, amt * (1.0 - l_sh) * wq)

    # --- poches ---
    def _pools_side(self, sz, act, side, close, win_abs, clust_pct):
        tol = clust_pct / 100.0
        out = []
        cs = cw = base = lo = hi = 0.0
        n = len(act)
        for k in range(n + 1):
            elig, p, s, i = False, 0.0, 0.0, 0
            if k < n:
                i = act[k]
                p = LIQ_GRID.price(i)
                s = sz[i] * self.g
                elig = abs(p - close) <= win_abs
            fin = k == n
            if cs > 0 and (fin or (elig and p > base * (1.0 + tol))):
                out.append({"price": cw / cs, "size": cs, "lo": lo, "hi": hi, "side": side})
                cs = cw = 0.0
            if elig:
                if cs == 0.0:
                    base = p
                    lo = LIQ_GRID.price(i, 0.0)
                hi = LIQ_GRID.price(i, 1.0)
                cs += s
                cw += s * p
        return out

    def pools(self, close, win_abs, clust_pct=0.25, keep_pct=35.0, per_side=3, magnet_pct=70.0):
        """Poches dans la fenetre autour du prix, filtrees : >= keep_pct de la plus grosse, per_side max par
        cote ; 'magnet' = la plus forte de chaque cote si >= magnet_pct. Renvoie un dict."""
        allp = (self._pools_side(self.lsz, self.lact, "long", close, win_abs, clust_pct) +
                self._pools_side(self.ssz, self.sact, "short", close, win_abs, clust_pct))
        if not allp:
            return {"pools": [], "total": 0, "sum_long": 0.0, "sum_short": 0.0}
        mx = max(p["size"] for p in allp)
        kept, cnt = [], {"long": 0, "short": 0}
        for p in sorted(allp, key=lambda p: -p["size"]):
            rel = p["size"] / mx
            if rel >= keep_pct / 100.0 and cnt[p["side"]] < per_side:
                cnt[p["side"]] += 1
                kept.append({**p, "rel": rel, "score": rnd(rel * 100.0),
                             "magnet": cnt[p["side"]] == 1 and rel >= magnet_pct / 100.0})
        return {"pools": kept, "total": len(allp),
                "sum_long": sum(p["size"] for p in allp if p["side"] == "long"),
                "sum_short": sum(p["size"] for p in allp if p["side"] == "short")}
