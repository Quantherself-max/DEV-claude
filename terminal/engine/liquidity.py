"""Poches de liquidation ESTIMEES a partir de l'Open Interest. Port du script Pine LiqLevels, ameliore :
chaque hausse d'OI = nouvelles positions au prix de la sous-bougie, reparties longs / shorts selon le
VOLUME ACHETEUR AGRESSIF reel (taker buy) quand il est connu (sinon la direction de la bougie), puis par
levier ; prix de liquidation = formule isolee + marge de maintenance. Un niveau disparait quand le prix le
touche (journal des balayages) ; quand l'OI baisse, les niveaux restants sont reduits d'autant.
C'est une estimation (proxy), pas de vraies liquidations."""
import math
from bisect import insort

from .grid import Grid, rnd

LIQ_GRID = Grid(0.05)
BAND_PCT = 0.15                                   # largeur d'une bande de la carte de chaleur (% du prix)
_BAND = math.log(1.0 + BAND_PCT / 100.0)
SNAP_MS = 3_600_000                               # une photo de l'etat des poches par heure
STEP_MS = 300_000


def band_of(price: float) -> int:
    return math.floor(math.log(max(price, 1e-9)) / _BAND)


def band_price(b: int, off: float = 0.0) -> float:
    return math.exp((b + off) * _BAND)


class LiqEngine:
    def __init__(self, levs=(100, 50, 25, 10), wts=(10, 20, 30, 40), mmr=0.004, split="auto", shrink=True,
                 sweep_min_frac=0.05, max_events=300, max_snaps=800):
        self.levs, self.wts, self.mmr, self.split, self.shrink = levs, wts, mmr, split, shrink
        self.wsum = max(sum(wts), 1e-4)
        self.lsz: dict[int, float] = {}
        self.ssz: dict[int, float] = {}
        self.lact: list[int] = []     # bins actifs tries par prix croissant
        self.sact: list[int] = []
        self.raw_long = 0.0           # somme des tailles brutes actives (taille reelle = brute x g)
        self.raw_short = 0.0
        self.g = 1.0                  # echelle globale (reduction quand l'OI baisse)
        self.oi_last = None
        self.steps = 0
        self.taker_steps = 0          # pas ou la repartition vient du vrai volume acheteur
        self.sweep_min_frac = sweep_min_frac
        self.max_events = max_events
        self.events: list[dict] = []  # balayages significatifs (journal)
        self.snaps: list = []         # (t_ms, {bande: taille longs}, {bande: taille shorts}) : une par heure
        self.max_snaps = max_snaps
        self._slot = None
        self._bandc: dict[int, int] = {}

    # --- niveaux ---
    def _add(self, side, price, amt):
        sz, act = (self.lsz, self.lact) if side == "long" else (self.ssz, self.sact)
        i = LIQ_GRID.idx(price)
        if sz.get(i, 0.0) <= 0.0:
            insort(act, i)
        raw = amt / self.g
        sz[i] = sz.get(i, 0.0) + raw
        if side == "long":
            self.raw_long += raw
        else:
            self.raw_short += raw

    def _sweep_long(self, low):
        hit, raw, hi_p, lo_p = 0, 0.0, None, None
        while self.lact and LIQ_GRID.price(self.lact[-1]) >= low:
            i = self.lact.pop()
            p = LIQ_GRID.price(i)
            hi_p = p if hi_p is None else hi_p
            lo_p = p
            raw += self.lsz[i]
            self.lsz[i] = 0.0
            hit += 1
        return hit, raw, hi_p, lo_p

    def _sweep_short(self, high):
        hit, raw, lo_p, hi_p = 0, 0.0, None, None
        while self.sact and LIQ_GRID.price(self.sact[0]) <= high:
            i = self.sact.pop(0)
            p = LIQ_GRID.price(i)
            lo_p = p if lo_p is None else lo_p
            hi_p = p
            raw += self.ssz[i]
            self.ssz[i] = 0.0
            hit += 1
        return hit, raw, lo_p, hi_p

    def _scale_down(self, f):
        g = self.g * f
        if g < 1e-6:
            for i in self.lact:
                self.lsz[i] *= g
            for i in self.sact:
                self.ssz[i] *= g
            self.raw_long = sum(self.lsz[i] for i in self.lact)
            self.raw_short = sum(self.ssz[i] for i in self.sact)
            g = 1.0
        self.g = g

    def _record(self, t, side, raw, total_raw, first_p, last_p):
        if t is None or raw <= 0 or total_raw <= 0:
            return
        frac = raw / total_raw
        if frac >= self.sweep_min_frac:
            self.events.append({"t": t, "side": side, "price": first_p, "to": last_p, "frac": frac,
                                "size": raw * self.g})
            if len(self.events) > self.max_events:
                del self.events[0]

    # --- photos horaires (carte de chaleur et age des poches) ---
    def _bands_now(self):
        bc, g = self._bandc, self.g
        out = []
        for sz, act in ((self.lsz, self.lact), (self.ssz, self.sact)):
            d: dict[int, float] = {}
            for i in act:
                b = bc.get(i)
                if b is None:
                    b = bc[i] = band_of(LIQ_GRID.price(i))
                d[b] = d.get(b, 0.0) + sz[i] * g
            out.append(d)
        return out

    def _snap(self, ts):
        lo, sh = self._bands_now()
        self.snaps.append((ts, lo, sh))
        if len(self.snaps) > self.max_snaps:
            del self.snaps[0]

    def _tick_snap(self, t):
        slot = (t - STEP_MS) // SNAP_MS            # t = fin de bougie 5 min ; la photo est prise a l'ouverture de l'heure
        if self._slot is None or slot > self._slot:
            self._snap(slot * SNAP_MS)
            self._slot = slot

    def birth_of(self, lo, hi, side, share=0.25):
        """Debut (ms) de la poche situee entre lo et hi : remonte les photos tant qu'elle pesait au moins `share`
        de sa taille actuelle (un balayage la remet a zero). None si l'historique est vide."""
        if not self.snaps:
            return None
        b0, b1 = band_of(lo), band_of(hi)
        k = 1 if side == "long" else 2
        now_d = self._bands_now()[0 if side == "long" else 1]
        cur = sum(v for b, v in now_d.items() if b0 <= b <= b1)
        if cur <= 0:
            return None
        born = None
        for snap in reversed(self.snaps):
            tot = sum(v for b, v in snap[k].items() if b0 <= b <= b1)
            if tot >= share * cur:
                born = snap[0]
            else:
                break
        return born

    def heat(self, p_lo, p_hi, since_ms, now_ms):
        """Carte de chaleur : colonnes horaires [since, now], bandes de prix [p_lo, p_hi]. Tailles reelles."""
        b0, b1 = band_of(p_lo), band_of(p_hi)
        m = b1 - b0 + 1
        cols = [s for s in self.snaps if s[0] >= since_ms - SNAP_MS]
        slot_now = now_ms // SNAP_MS * SNAP_MS
        live = self._bands_now()
        if cols and cols[-1][0] == slot_now:
            cols[-1] = (slot_now, live[0], live[1])         # la colonne de l'heure en cours montre l'etat actuel
        elif cols:
            cols.append((slot_now, live[0], live[1]))
        if not cols or m <= 0:
            return None
        return {"t0": cols[0][0], "dt": SNAP_MS, "n": len(cols), "b0": b0, "m": m,
                "cols": cols, "lo": band_price(b0), "step": _BAND}

    def step(self, oi_now, h, l, c, vol=0.0, tb=None, t=None):
        """Un pas de temps (bougie 5 min). oi_now peut etre None (alors seule la touche est traitee).
        tb = volume acheteur agressif de la bougie (None si inconnu) ; t = horodatage (journal des balayages)."""
        if t is not None:
            self._tick_snap(t)
        tot_l, tot_s = self.raw_long, self.raw_short
        hl, raw_l, p1l, p2l = self._sweep_long(l)
        hs, raw_s, p1s, p2s = self._sweep_short(h)
        self.raw_long = max(0.0, self.raw_long - raw_l)
        self.raw_short = max(0.0, self.raw_short - raw_s)
        self._record(t, "long", raw_l, tot_l, p1l, p2l)
        self._record(t, "short", raw_s, tot_s, p1s, p2s)
        hits = hl + hs
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
        if self.split in ("auto", "taker") and tb is not None and vol > 0 and tb > 0:
            l_sh = max(0.2, min(0.8, tb / vol))          # part des acheteurs agressifs = nouveaux longs
            self.taker_steps += 1
        elif self.split == "50":
            l_sh = 0.5
        else:
            rng = h - l
            clv = ((c - l) - (h - c)) / rng if rng > 0 else 0.0
            l_sh = max(0.2, min(0.8, 0.5 + 0.5 * clv))
        for lev, w in zip(self.levs, self.wts):
            wq = w / self.wsum
            if lev <= 1 or wq <= 0:
                continue
            pl = px * (1.0 - 1.0 / lev + self.mmr)
            ps = px * (1.0 + 1.0 / lev - self.mmr)
            if pl < l:
                self._add("long", pl, amt * l_sh * wq)
            if ps > h:
                self._add("short", ps, amt * (1.0 - l_sh) * wq)

    def totals(self):
        """Taille reelle totale des niveaux actifs (longs sous le prix, shorts au-dessus)."""
        return self.raw_long * self.g, self.raw_short * self.g

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
                             "magnet": cnt[p["side"]] == 1 and rel >= magnet_pct / 100.0,
                             "born": self.birth_of(p["lo"], p["hi"], p["side"])})
        return {"pools": kept, "total": len(allp),
                "sum_long": sum(p["size"] for p in allp if p["side"] == "long"),
                "sum_short": sum(p["size"] for p in allp if p["side"] == "short")}
