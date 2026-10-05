"""Series FINES (1 min, 5 min, 15 min, 1 h) en tableaux compacts, avec sommes cumulees.

Pourquoi : un VWAP, un VWAP ancre ou un volume profile calcules sur des bougies 1 h repartissent le volume au hasard dans
chaque bougie. Sur des bougies de 1 a 5 minutes (12 a 60 fois plus fines) les niveaux sont bien plus precis. Les sommes
cumulees rendent chaque VWAP (jour, semaine, mois, annee ou ancre n'importe ou) INSTANTANE : VWAP = difference de sommes.

Chaque bougie porte aussi un « delta » (volume acheteur agressif - volume vendeur agressif) :
  - donnees Binance : delta reel = 2 x volume acheteur agressif (taker buy) - volume ;
  - sinon (ex. Bitstamp) : PROXY par minute, volume x (2 x cloture - haut - bas) / (haut - bas), tick rule si haut = bas.
    C'est une approximation (indiquee partout ou elle sert) : seule la source reelle donne le vrai CVD.
Module sans reseau (stdlib uniquement)."""
import csv
import gzip
import math
from array import array
from bisect import bisect_left, bisect_right

from .atr import Candle

MINUTE = 60_000


class Bars:
    """Bougies en colonnes. t = ouverture (ms). d = delta (acheteurs - vendeurs). Sommes cumulees (prefixes, longueur n+1) :
    cv (volume), cpv (prix typique x volume), cpv2 (prix typique^2 x volume), cd (delta)."""
    __slots__ = ("step", "t", "o", "h", "l", "c", "v", "d", "cv", "cpv", "cpv2", "cd", "_cum_n")

    def __init__(self, step_ms: int):
        self.step = step_ms
        self.t, self.o, self.h, self.l, self.c, self.v, self.d = (array("d") for _ in range(7))
        self.cv = self.cpv = self.cpv2 = self.cd = None
        self._cum_n = 0

    def __len__(self):
        return len(self.t)

    def append(self, t, o, h, l, c, v, d):
        self.t.append(t); self.o.append(o); self.h.append(h); self.l.append(l); self.c.append(c); self.v.append(v); self.d.append(d)

    # ---------- sommes cumulees ----------
    def build_cum(self):
        n = len(self.t)
        if self.cv is not None and self._cum_n == n:
            return self
        cv, cpv, cpv2, cd = array("d", [0.0]), array("d", [0.0]), array("d", [0.0]), array("d", [0.0])
        a = b = q = e = 0.0
        h, l, c, v, d = self.h, self.l, self.c, self.v, self.d
        for i in range(n):
            tp = (h[i] + l[i] + c[i]) / 3.0
            vi = v[i]
            a += vi; b += tp * vi; q += tp * tp * vi; e += d[i]
            cv.append(a); cpv.append(b); cpv2.append(q); cd.append(e)
        self.cv, self.cpv, self.cpv2, self.cd, self._cum_n = cv, cpv, cpv2, cd, n
        return self

    def vwap(self, i0: int, i1: int):
        """(VWAP, ecart-type pondere par le volume) des bougies [i0, i1) ; (None, None) sans volume."""
        v = self.cv[i1] - self.cv[i0]
        if v <= 0:
            return None, None
        vw = (self.cpv[i1] - self.cpv[i0]) / v
        var = (self.cpv2[i1] - self.cpv2[i0]) / v - vw * vw
        return vw, math.sqrt(var) if var > 0 else 0.0

    def delta(self, i0: int, i1: int) -> float:
        return self.cd[i1] - self.cd[i0]

    def volume(self, i0: int, i1: int) -> float:
        return self.cv[i1] - self.cv[i0]

    # ---------- recherche ----------
    def idx(self, t_ms: float) -> int:
        """Index de la premiere bougie dont l'ouverture est >= t_ms."""
        return bisect_left(self.t, t_ms)

    def idx_at(self, t_ms: float) -> int:
        """Index de la bougie qui CONTIENT t_ms (-1 si avant la premiere)."""
        return bisect_right(self.t, t_ms) - 1

    def candle(self, i: int) -> Candle:
        v, d = self.v[i], self.d[i]
        return Candle(int(self.t[i]), self.o[i], self.h[i], self.l[i], self.c[i], v, (v + d) / 2.0)

    def candles(self, i0: int, i1: int) -> list:
        return [self.candle(i) for i in range(max(0, i0), min(len(self.t), i1))]

    # ---------- cache binaire (rechargement instantane) ----------
    def save(self, path):
        with open(path, "wb") as f:
            f.write(int(self.step).to_bytes(8, "little") + len(self.t).to_bytes(8, "little"))
            for col in (self.t, self.o, self.h, self.l, self.c, self.v, self.d):
                col.tofile(f)

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            step = int.from_bytes(f.read(8), "little")
            n = int.from_bytes(f.read(8), "little")
            b = cls(step)
            for col in (b.t, b.o, b.h, b.l, b.c, b.v, b.d):
                col.fromfile(f, n)
        return b


def bar_delta(o, h, l, c, v, prev_close):
    """Delta PROXY d'une bougie : volume x position de la cloture dans la bougie (-1 en bas, +1 en haut)."""
    if h > l:
        return v * (2.0 * c - h - l) / (h - l)
    if prev_close is None or c == prev_close:
        return 0.0
    return v if c > prev_close else -v          # tick rule


def from_candles(candles, step_ms: int) -> Bars:
    """Bars a partir de Candle (tb > 0 : delta reel 2 tb - v ; sinon proxy)."""
    b = Bars(step_ms)
    prev = None
    for k in candles:
        d = (2.0 * k.tb - k.v) if k.tb > 0 else bar_delta(k.o, k.h, k.l, k.c, k.v, prev)
        b.append(k.t, k.o, k.h, k.l, k.c, k.v, d)
        prev = k.c
    return b.build_cum()


def load_bitstamp(paths, start_ms: int = 0, end_ms: int = 2 ** 62) -> Bars:
    """CSV « timestamp,open,high,low,close,volume » (secondes, ouverture), eventuellement .gz ; plusieurs fichiers a la suite.
    Les minutes sans echange sont gardees (bougie plate, volume nul) pour que l'indexation reste reguliere."""
    b = Bars(MINUTE)
    prev = None
    last_t = None
    for p in paths:
        opener = gzip.open if str(p).endswith(".gz") else open
        with opener(p, "rt", newline="") as f:
            r = csv.reader(f)
            next(r, None)
            for row in r:
                t = int(row[0]) * 1000
                if t < start_ms:
                    continue
                if t >= end_ms:
                    break
                if last_t is not None and t <= last_t:
                    continue                                  # recouvrement entre fichiers
                o, h, l, c, v = float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
                b.append(t, o, h, l, c, v, bar_delta(o, h, l, c, v, prev))
                prev = c
                last_t = t
    return b.build_cum()


def resample(src: Bars, step_ms: int) -> Bars:
    """Regroupe des bougies fines en bougies de step_ms (alignees sur l'epoque UTC)."""
    out = Bars(step_ms)
    n = len(src.t)
    i = 0
    t, o, h, l, c, v, d = src.t, src.o, src.h, src.l, src.c, src.v, src.d
    while i < n:
        bucket = int(t[i] // step_ms) * step_ms
        j = i
        hi, lo, vol, dl = h[i], l[i], 0.0, 0.0
        while j < n and t[j] < bucket + step_ms:
            if h[j] > hi:
                hi = h[j]
            if l[j] < lo:
                lo = l[j]
            vol += v[j]
            dl += d[j]
            j += 1
        out.append(bucket, o[i], hi, lo, c[j - 1], vol, dl)
        i = j
    return out.build_cum()


def atr(bars: Bars, i: int, n: int = 14) -> float:
    """ATR simple (moyenne des vraies amplitudes) des n bougies finissant a l'index i inclus."""
    i0 = max(1, i - n + 1)
    tot, cnt = 0.0, 0
    for j in range(i0, i + 1):
        pc = bars.c[j - 1]
        tot += max(bars.h[j] - bars.l[j], abs(bars.h[j] - pc), abs(bars.l[j] - pc))
        cnt += 1
    return tot / cnt if cnt else 0.0
