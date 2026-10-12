"""Etat du marche : tout ce que le terminal sait d'un contrat, construit transaction par transaction. Sans reseau ni disque.

Contenu :
  - les barres de base (1 minute par defaut) avec leur footprint (`BarSeries`) ; les autres unites de temps sont des regroupements ;
  - pour chaque journee de trading, deux « echelles de prix » (`Ladder`) : la journee Globex entiere (18 h ET -> 17 h ET) et la seance reguliere
    americaine (9 h 30 -> 16 h ET) : profil de volume, VWAP et ecart-type, delta ;
  - le ruban (dernieres transactions) et les gros ordres.
Un verrou protege tout : le thread qui lit la source ecrit, les requetes du navigateur lisent."""
import threading
from bisect import bisect_left
from collections import deque

from . import clock
from .bars import BarSeries, SideClassifier, Tick, resample
from .footprint import Ladder
from .instruments import NQ, Instrument


class Market:
    def __init__(self, inst: Instrument = NQ, base_ms: int = 60_000, keep_days: int = 8):
        self.inst = inst
        self.base_ms = base_ms
        self.keep_days = keep_days
        self.series = BarSeries(base_ms, inst.tick)
        self.cls = SideClassifier()
        self.gx: dict = {}              # jour de trading -> Ladder (journee Globex entiere)
        self.rth: dict = {}             # jour de trading -> Ladder (seance reguliere)
        self.last: Tick | None = None
        self.tape = deque(maxlen=300)   # (t, prix, quantite, cote)
        self.bigs = deque(maxlen=60)    # les gros ordres
        self.count = 0
        self.version = 0                # change a chaque transaction : permet aux vues de savoir si elles doivent se recalculer
        self.lock = threading.RLock()
        self._w = None                  # fenetre de la journee de trading en cours : (debut, fin, jour, debut RTH, fin RTH)
        self._cache: dict = {}

    # ---------- entree ----------
    def _day(self, t: int) -> tuple:
        """(jour de trading, dans la seance reguliere ?) de l'instant t. La fenetre de la journee en cours est gardee : un calcul par jour, pas par tick."""
        w = self._w
        if w is None or not (w[0] <= t < w[1]):
            day = clock.trading_day(t)
            y, m, d = (int(x) for x in day.split("-"))
            ra, rb = clock.window(day, "rth")
            w = self._w = (clock.window(day, "globex")[0], clock.et_to_utc(y, m, d, 18, 0), day, ra, rb)
        return w[2], w[3] <= t < w[4]

    def ingest(self, tk: Tick) -> None:
        if tk.p <= 0 or tk.q <= 0:
            return
        with self.lock:
            side = self.cls(tk)
            if self.series.add(tk, side) is None:
                return
            idx = self.inst.idx(tk.p)
            day, in_rth = self._day(tk.t)
            lad = self.gx.get(day)
            if lad is None:
                lad = self.gx[day] = Ladder(self.inst.tick)
            lad.add_trade(idx, side, tk.q)
            if in_rth:
                lr = self.rth.get(day)
                if lr is None:
                    lr = self.rth[day] = Ladder(self.inst.tick)
                lr.add_trade(idx, side, tk.q)
            if self.last is None or tk.t >= self.last.t:
                self.last = tk
            self.tape.append((tk.t, tk.p, tk.q, side))
            if tk.q >= self.inst.big_lot:
                self.bigs.append((tk.t, tk.p, tk.q, side))
            self.count += 1
            self.version += 1

    def ingest_many(self, ticks) -> int:
        n = 0
        for tk in ticks:
            self.ingest(tk)
            n += 1
        if n:
            self.prune()
        return n

    def prune(self) -> None:
        """Oublie les journees plus vieilles que `keep_days` (barres, profils)."""
        with self.lock:
            if self.last is None:
                return
            day = clock.trading_day(self.last.t)
            for _ in range(self.keep_days):
                day = clock.prev_day(day)
            for d in (self.gx, self.rth):
                for k in [k for k in d if k <= day]:
                    del d[k]
            self.series.prune(clock.window(day, "globex")[1])

    # ---------- lecture ----------
    @property
    def price(self):
        return self.last.p if self.last else None

    def now_ms(self) -> int | None:
        return self.last.t if self.last else None

    def day(self):
        """Journee de trading en cours (celle de la derniere transaction)."""
        return clock.trading_day(self.last.t) if self.last else None

    def days(self) -> list:
        with self.lock:
            return sorted(self.gx)

    def prev_day(self, day: str | None = None):
        """Derniere journee AVANT `day` qui a eu une seance reguliere (jours feries : on saute les jours sans donnees)."""
        with self.lock:
            day = day or self.day()
            cand = [d for d in self.rth if d < day and self.rth[d].volume > 0]
            return max(cand) if cand else None

    def ladder(self, day: str, kind: str):
        return (self.rth if kind == "rth" else self.gx).get(day)

    def slice(self, a: int, b: int) -> list:
        """Barres de base ouvertes dans [a, b)."""
        with self.lock:
            ts = self.series._ts
            return self.series.bars[bisect_left(ts, a):bisect_left(ts, b)]

    def ohlc(self, a: int, b: int):
        """{o, h, l, c} des barres de [a, b), ou None."""
        bars = self.slice(a, b)
        if not bars:
            return None
        return {"o": bars[0].o, "h": max(x.h for x in bars), "l": min(x.l for x in bars), "c": bars[-1].c, "t0": bars[0].t, "t1": bars[-1].t}

    def window_ohlc(self, day: str, name: str):
        a, b = clock.window(day, name)
        return self.ohlc(a, b)

    def chart_bars(self, tf_ms: int, limit: int = 600) -> list:
        """Barres de `tf_ms` (regroupement des barres de base), les `limit` dernieres (0 = toutes). Calcul garde tant qu'aucune transaction n'arrive.
        Les barres de base sont les objets vivants : lis-les en tenant `self.lock`."""
        with self.lock:
            hit = self._cache.get(tf_ms)
            if hit and hit[0] == self.version:
                bars = hit[1]
            else:
                bars = self.series.bars if tf_ms == self.base_ms else resample(self.series.bars, tf_ms)
                self._cache[tf_ms] = (self.version, bars)
            return bars[-limit:] if limit else list(bars)
