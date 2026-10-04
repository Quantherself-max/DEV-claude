"""Periodes calendaires UTC (Jour, Semaine lundi, Mois, Annee) : VWAP + ecart-type, open, plus haut /
plus bas, profil de volume, et memoire de la periode precedente. Meme logique que les scripts Pine :
le profil n'utilise que les bougies fermees ; VWAP / high / low integrent la bougie en cours."""
import math
from datetime import datetime, timezone

from . import vp
from .atr import Candle

KINDS = ("D", "W", "M", "Y")


def period_key(kind: str, t_ms: int) -> int:
    d = t_ms // 86_400_000
    if kind == "D":
        return d
    if kind == "W":
        return (d + 3) // 7          # semaines commencant le lundi
    dt = datetime.fromtimestamp(t_ms / 1000.0, timezone.utc)
    return dt.year * 12 + dt.month if kind == "M" else dt.year


class _Acc:
    """Cumuls d'une periode : open, high, low, close, sommes pour le VWAP et son ecart-type."""
    __slots__ = ("start", "open", "high", "low", "close", "pv", "v", "pv2", "n")

    def __init__(self):
        self.start = None
        self.open = self.high = self.low = self.close = None
        self.pv = self.v = self.pv2 = 0.0
        self.n = 0

    def add(self, k: Candle) -> None:
        if self.n == 0:
            self.start, self.open, self.high, self.low = k.t, k.o, k.h, k.l
        self.high = max(self.high, k.h)
        self.low = min(self.low, k.l)
        self.close = k.c
        tp = (k.h + k.l + k.c) / 3.0
        self.pv += tp * k.v
        self.v += k.v
        self.pv2 += tp * tp * k.v
        self.n += 1

    def copy(self) -> "_Acc":
        a = _Acc()
        for s in self.__slots__:
            setattr(a, s, getattr(self, s))
        return a

    def vwap(self):
        """(VWAP, ecart-type pondere par le volume) ; None si pas de volume."""
        if self.v <= 0:
            return None, None
        vw = self.pv / self.v
        var = max(self.pv2 / self.v - vw * vw, 0.0)
        return vw, math.sqrt(var)


class PeriodTracker:
    def __init__(self, kind: str):
        self.kind = kind
        self.key = None
        self.acc = _Acc()
        self.profile = vp.Profile()
        self.prev = None          # periode precedente terminee : open/high/low/close + niveaux de profil
        self._cache = (None, None)

    def _final(self):
        a = self.acc
        if a.n == 0:
            return None
        lv = vp.levels(self.profile, a.n)
        vw, _ = a.vwap()
        return {"open": a.open, "high": a.high, "low": a.low, "close": a.close, "vwap": vw, "vp": lv}

    def feed(self, k: Candle) -> None:
        """Bougie FERMEE, dans l'ordre chronologique."""
        key = period_key(self.kind, k.t)
        if key != self.key:
            if self.key is not None:
                self.prev = self._final()
            self.key = key
            self.acc = _Acc()
            self.profile = vp.Profile()
        self.acc.add(k)
        self.profile.add(k.l, k.h, k.v)

    def _cur_vp(self):
        ver = self.profile.version
        if self._cache[0] != ver:
            self._cache = (ver, vp.levels(self.profile, self.acc.n))
        return self._cache[1]

    def snapshot(self, forming: Candle | None = None) -> dict:
        """Etat courant ; `forming` = bougie en cours (comptee dans VWAP / high / low, pas dans le profil)."""
        prev = self.prev
        if forming is not None and self.key is not None and period_key(self.kind, forming.t) != self.key:
            prev = self._final()                    # la bougie en cours ouvre deja la periode suivante
            acc = _Acc()
            acc.add(forming)
            cur_vp = None
        else:
            acc = self.acc.copy()
            if forming is not None:
                acc.add(forming)
            cur_vp = self._cur_vp()
        vw, sd = acc.vwap()
        return {"kind": self.kind, "open": acc.open, "high": acc.high, "low": acc.low, "vwap": vw,
                "sd": sd, "vp": cur_vp, "prev": prev, "start": acc.start, "n": acc.n}


class AnchoredVWAP:
    """VWAP ancree a une date (premiere bougie dont l'ouverture >= ancre)."""

    def __init__(self, anchor_ms: int):
        self.anchor = anchor_ms
        self.acc = _Acc()

    def feed(self, k: Candle) -> None:
        if k.t >= self.anchor:
            self.acc.add(k)

    def snapshot(self, forming: Candle | None = None):
        a = self.acc.copy()
        if forming is not None and forming.t >= self.anchor:
            a.add(forming)
        vw, sd = a.vwap()
        return {"vwap": vw, "sd": sd, "start": a.start, "n": a.n}


class NakedPocs:
    """POC 'nus' (naked) : POC des periodes passees que le prix n'a JAMAIS retraverses depuis. Aimants classiques
    pour les traders de profil de volume. La periode juste terminee est exclue (c'est deja le POC precedent)."""

    def __init__(self, keep: int = 20):
        self.keep = keep
        self.items: list[dict] = []        # {"poc", "t_end", "n"} ; n = numero de la periode (1 = derniere)
        self.pending = None                 # POC de la periode qui vient de se terminer (pas encore "ancien")

    def on_rollover(self, poc, t_end: int) -> None:
        if self.pending is not None:
            self.items.append(self.pending)
            self.items = self.items[-self.keep:]
        self.pending = {"poc": poc, "t_end": t_end} if poc is not None else None

    def feed(self, k: Candle) -> None:
        """Bougie FERMEE : un POC touche n'est plus 'nu' (le POC en attente aussi peut etre touche)."""
        self.items = [x for x in self.items if not (k.l <= x["poc"] <= k.h)]
        if self.pending is not None and k.l <= self.pending["poc"] <= k.h:
            self.pending = None

    def active(self):
        return list(self.items)
