"""ATR (moyenne de Wilder, comme ta.atr de Pine) et changement d'echelle de temps."""
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


INTERVAL_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
