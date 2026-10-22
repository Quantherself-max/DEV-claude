"""ATR (moyenne de Wilder, comme ta.atr de Pine) et changement d'echelle de temps."""
from __future__ import annotations
from datetime import datetime, timezone
from dataclasses import dataclass


@dataclass
class Candle:
    t: int          # ouverture, ms epoch UTC
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0  # volume (coin)
    tb: float = 0.0  # volume acheteur agressif (taker buy), 0 si inconnu
    q: float = 0.0   # V23 : volume en dollars (somme prix x quantite de chaque transaction) : q / v = prix moyen EXACT de la bougie ; 0 si inconnu


def rma_atr(candles, n: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    trs = []
    prev_c = candles[0].c
    for k in candles:
        trs.append(max(k.h - k.l, abs(k.h - prev_c), abs(k.l - prev_c)))
        prev_c = k.c
    if len(trs) < n:
        return sum(trs) / len(trs)
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def avg_price(k) -> float:
    """Prix moyen de la bougie : EXACT (volume en dollars / volume) quand la bourse le donne, sinon prix typique (plus haut + plus bas + cloture) / 3."""
    if k.q > 0 and k.v > 0:
        return k.q / k.v
    return (k.h + k.l + k.c) / 3.0


def resample(candles, interval_ms: int):
    """Regroupe des bougies plus fines en bougies de `interval_ms` (la derniere peut etre incomplete)."""
    out = []
    cur = None
    for k in candles:
        bucket = k.t - (k.t % interval_ms)
        if cur is None or cur.t != bucket:
            if cur is not None:
                out.append(cur)
            cur = Candle(bucket, k.o, k.h, k.l, k.c, k.v, k.tb, k.q)
        else:
            cur.h = max(cur.h, k.h)
            cur.l = min(cur.l, k.l)
            cur.c = k.c
            cur.v += k.v
            cur.tb += k.tb
            cur.q += k.q
    if cur is not None:
        out.append(cur)
    return out


INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
               "1w": 604_800_000, "1M": 2_678_400_000}     # V36 : 1 minute, semaine (du lundi) et mois (calendaire ; 31 jours au plus)
CALENDAR = ("1w", "1M")                                    # bougies de calendrier : on ne les regroupe pas par une durée fixe
MONDAY0 = 4 * 86_400_000                                   # lundi 5 janvier 1970 : les semaines commencent le lundi 00 h UTC (comme Binance)


def bar_start(t_ms: int, tf: str) -> int:
    """Ouverture (ms, UTC) de la bougie de l'unité tf qui contient t_ms."""
    if tf == "1w":
        return t_ms - (t_ms - MONDAY0) % INTERVAL_MS["1w"]
    if tf == "1M":
        d = datetime.fromtimestamp(t_ms / 1000, timezone.utc)
        return int(datetime(d.year, d.month, 1, tzinfo=timezone.utc).timestamp() * 1000)
    return t_ms - t_ms % INTERVAL_MS[tf]


def resample_cal(candles, tf: str):
    """V36 : regroupe des bougies plus fines en bougies de semaine (lundi 00 h UTC) ou de mois calendaire."""
    out, cur, nxt = [], None, None
    for k in candles:
        if cur is None or k.t >= nxt:
            if cur is not None:
                out.append(cur)
            b = bar_start(k.t, tf)
            if tf == "1M":
                d = datetime.fromtimestamp(b / 1000, timezone.utc)
                nxt = int(datetime(d.year + (d.month == 12), d.month % 12 + 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
            else:
                nxt = b + INTERVAL_MS["1w"]
            cur = Candle(b, k.o, k.h, k.l, k.c, k.v, k.tb, k.q)
        else:
            cur.h = max(cur.h, k.h)
            cur.l = min(cur.l, k.l)
            cur.c = k.c
            cur.v += k.v
            cur.tb += k.tb
            cur.q += k.q
    if cur is not None:
        out.append(cur)
    return out
