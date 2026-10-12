"""Transactions (ticks), barres et regroupement. Module PUR.

Une barre porte, en plus de l'OHLC :
  - v  : volume total (contrats) ; bv : volume ACHETEUR agressif (ordre au marche qui frappe l'ask) ; sv : volume VENDEUR agressif (frappe le bid) ;
  - n  : nombre de transactions ; pv, pv2 : somme prix x quantite et prix^2 x quantite (VWAP et ecart-type EXACTS, sans approximation par barre) ;
  - fp : « footprint » {indice de tick: [vendeur, acheteur]} = volume echange a CHAQUE prix, avec les deux cotes separes.
Le delta d'une barre = bv - sv. Il n'est REEL que si la source donne le cote de l'agresseur (Rithmic, CQG, Databento...). Sinon, la regle du
tick (hausse = acheteur, baisse = vendeur, prix inchange = comme la derniere fois) en donne une estimation : `SideClassifier`."""
from bisect import bisect_left
from dataclasses import dataclass


@dataclass(slots=True)
class Tick:
    t: int                  # ms epoch UTC
    p: float                # prix
    q: float                # quantite (contrats)
    side: int = 0           # +1 acheteur agressif (frappe l'ask), -1 vendeur agressif (frappe le bid), 0 inconnu


class SideClassifier:
    """Donne un cote aux transactions qui n'en ont pas (regle du tick). Les cotes fournis par la bourse sont gardes tels quels."""
    def __init__(self):
        self.last_p = None
        self.last_side = 1
        self.estimated = 0          # transactions dont le cote a ete deduit
        self.total = 0

    def __call__(self, tk: Tick) -> int:
        self.total += 1
        if tk.side:
            side = 1 if tk.side > 0 else -1
        else:
            self.estimated += 1
            if self.last_p is None or tk.p == self.last_p:
                side = self.last_side
            else:
                side = 1 if tk.p > self.last_p else -1
        self.last_p, self.last_side = tk.p, side
        return side

    @property
    def real_share(self) -> float:
        """Part des transactions dont le cote vient de la bourse (1.0 = delta reel)."""
        return 1.0 - self.estimated / self.total if self.total else 1.0


class Bar:
    __slots__ = ("t", "o", "h", "l", "c", "v", "bv", "sv", "n", "pv", "pv2", "fp")

    def __init__(self, t: int, p: float):
        self.t = t
        self.o = self.h = self.l = self.c = p
        self.v = self.bv = self.sv = 0.0
        self.n = 0
        self.pv = self.pv2 = 0.0
        self.fp = {}

    @property
    def delta(self) -> float:
        return self.bv - self.sv

    def add(self, p: float, q: float, side: int, idx: int) -> None:
        if p > self.h:
            self.h = p
        if p < self.l:
            self.l = p
        self.c = p
        self.v += q
        if side > 0:
            self.bv += q
        else:
            self.sv += q
        self.n += 1
        self.pv += p * q
        self.pv2 += p * p * q
        r = self.fp.get(idx)
        if r is None:
            r = self.fp[idx] = [0.0, 0.0]
        r[1 if side > 0 else 0] += q

    def copy(self, with_fp: bool = True) -> "Bar":
        b = Bar(self.t, self.o)
        b.h, b.l, b.c, b.v, b.bv, b.sv, b.n, b.pv, b.pv2 = self.h, self.l, self.c, self.v, self.bv, self.sv, self.n, self.pv, self.pv2
        if with_fp:
            b.fp = {k: list(r) for k, r in self.fp.items()}
        return b

    def to_dict(self) -> dict:
        return {"t": self.t, "o": self.o, "h": self.h, "l": self.l, "c": self.c, "v": self.v, "bv": self.bv, "sv": self.sv, "n": self.n}


class BarSeries:
    """Barres de `step` ms construites au fil des transactions (une barre par tranche de temps qui a eu au moins une transaction)."""
    def __init__(self, step_ms: int, tick: float):
        self.step = step_ms
        self.tick = tick
        self.bars: list[Bar] = []
        self._ts: list[int] = []            # ouvertures, pour la recherche d'une barre par dichotomie

    def add(self, tk: Tick, side: int) -> Bar | None:
        """Ajoute la transaction. Renvoie la barre touchee (None si une transaction tres en retard n'a plus de barre)."""
        b0 = tk.t - tk.t % self.step
        idx = int(round(tk.p / self.tick))
        if not self.bars or b0 > self.bars[-1].t:
            b = Bar(b0, tk.p)
            self.bars.append(b)
            self._ts.append(b0)
        elif b0 == self.bars[-1].t:
            b = self.bars[-1]
        else:                                # transaction en retard : on la range dans sa barre si elle existe encore
            i = bisect_left(self._ts, b0)
            if i >= len(self._ts) or self._ts[i] != b0:
                return None
            b = self.bars[i]
            c = b.c
            b.add(tk.p, tk.q, side, idx)
            b.c = c                           # l'ouverture et la cloture ne bougent pas pour une transaction en retard
            return b
        b.add(tk.p, tk.q, side, idx)
        return b

    def prune(self, before_ms: int) -> int:
        """Retire les barres ouvertes avant `before_ms`. Renvoie le nombre retire."""
        i = bisect_left(self._ts, before_ms)
        if i:
            del self.bars[:i]
            del self._ts[:i]
        return i


def resample(bars, step_ms: int, with_fp: bool = False) -> list:
    """Regroupe des barres plus fines en barres de `step_ms` (alignees sur l'UTC, donc sur les heures pleines de New York et de Paris)."""
    out = []
    cur = None
    for b in bars:
        k = b.t - b.t % step_ms
        if cur is None or cur.t != k:
            cur = b.copy(with_fp)
            cur.t = k
            out.append(cur)
            continue
        if b.h > cur.h:
            cur.h = b.h
        if b.l < cur.l:
            cur.l = b.l
        cur.c = b.c
        cur.v += b.v
        cur.bv += b.bv
        cur.sv += b.sv
        cur.n += b.n
        cur.pv += b.pv
        cur.pv2 += b.pv2
        if with_fp:
            for idx, r in b.fp.items():
                d = cur.fp.get(idx)
                if d is None:
                    cur.fp[idx] = list(r)
                else:
                    d[0] += r[0]
                    d[1] += r[1]
    return out


TF_MS = {"1m": 60_000, "2m": 120_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000}


def atr(bars, n: int = 14) -> float:
    """ATR de Wilder, en points, sur des barres (0.0 s'il y en a moins de 2)."""
    if len(bars) < 2:
        return 0.0
    trs, prev = [], bars[0].c
    for b in bars:
        trs.append(max(b.h - b.l, abs(b.h - prev), abs(b.l - prev)))
        prev = b.c
    if len(trs) < n:
        return sum(trs) / len(trs)
    a = sum(trs[:n]) / n
    for x in trs[n:]:
        a = (a * (n - 1) + x) / n
    return a
