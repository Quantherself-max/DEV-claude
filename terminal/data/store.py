"""Historique d'un symbole en memoire : bougies 1h (depuis l'ancre / l'annee precedente), bougies 5 min +
Open Interest sur 30 jours. refresh() ne telecharge que ce qui manque."""
from datetime import datetime, timezone

from engine.atr import Candle

H1 = 3_600_000
M5 = 300_000
DAY = 86_400_000
OI_DAYS = 29       # Binance ne donne l'OI 5 min que sur ~30 jours


def merge(lst: list, new: list) -> None:
    for k in new:
        if lst and k.t == lst[-1].t:
            lst[-1] = k                      # la bougie qui se formait est remplacee par sa version a jour
        elif not lst or k.t > lst[-1].t:
            lst.append(k)


class DataStore:
    def __init__(self, source, symbol: str, anchor_ms: int):
        self.source, self.symbol = source, symbol
        now = source.now_ms()
        y = datetime.fromtimestamp(now / 1000, timezone.utc).year
        prev_year = int(datetime(y - 1, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        self.history_start = min(anchor_ms, prev_year)       # le profil de l'annee precedente est necessaire
        self.h1: list[Candle] = []
        self.m5: list[Candle] = []
        self.oi: dict[int, float] = {}                       # ouverture de la bougie 5 min -> OI a sa fin
        self.last_error = None
        self.last_refresh = 0

    def refresh(self) -> None:
        now = self.source.now_ms()
        s1 = self.h1[-1].t if self.h1 else self.history_start - self.history_start % H1
        merge(self.h1, self.source.candles(self.symbol, "1h", s1, now))
        s5 = self.m5[-1].t if self.m5 else now - OI_DAYS * DAY
        s5 -= s5 % M5
        merge(self.m5, self.source.candles(self.symbol, "5m", s5, now))
        so = (max(self.oi) + M5) if self.oi else now - OI_DAYS * DAY
        for ts, v in self.source.open_interest(self.symbol, "5m", so, now):
            self.oi[ts - M5] = v
        self.last_refresh = now
        self.last_error = None

    def forming_h1(self):
        k = self.h1[-1] if self.h1 else None
        return k if k and k.t + H1 > self.source.now_ms() else None
