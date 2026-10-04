"""Source SIMULEE : marche synthetique deterministe (meme historique a chaque lancement), pour tester le
terminal sans reseau. Les prix ne sont PAS reels."""
import math
import random

from engine.atr import Candle, INTERVAL_MS, resample
from .base import Source

M5 = 300_000
SIM_START = 1_704_067_200_000          # 2024-01-01 00:00 UTC
TARGET = {"BTCUSDT": 85000.0, "SOLUSDT": 190.0, "ETHUSDT": 3300.0}
OI_BASE = {"BTCUSDT": 80_000.0, "SOLUSDT": 35_000_000.0, "ETHUSDT": 2_500_000.0}


class SimulatedSource(Source):
    name = "simulated"

    def __init__(self, now_ms: int | None = None):
        self._now = now_ms
        self._m5: dict[str, list[Candle]] = {}
        self._oi: dict[str, list[tuple[int, float]]] = {}
        self._rs: dict[tuple[str, str], list[Candle]] = {}

    def now_ms(self) -> int:
        return self._now if self._now is not None else super().now_ms()

    def set_now(self, now_ms: int) -> None:
        self._now = now_ms

    # --- generation deterministe : le chemin de prix est un prefixe fixe, quelle que soit l'heure ---
    def _gen(self, symbol: str):
        if symbol in self._m5:
            return
        rnd = random.Random(sum(map(ord, symbol)) * 7919)
        end_bucket = self.now_ms() - self.now_ms() % M5
        n = (end_bucket - SIM_START) // M5 + 1
        px, vol_regime = 1.0, 1.0
        raw, closes = [], []
        for k in range(n):
            if k % 600 == 0:
                vol_regime = rnd.choice((0.7, 0.9, 1.0, 1.3, 1.8))
            r = rnd.gauss(0.000004, 0.0011 * vol_regime)
            o, c = px, px * math.exp(r)
            h = max(o, c) * (1 + abs(rnd.gauss(0, 0.0004 * vol_regime)))
            l = min(o, c) * (1 - abs(rnd.gauss(0, 0.0004 * vol_regime)))
            hour = ((SIM_START + k * M5) // 3_600_000) % 24
            v = (1 + abs(r) / 0.0011) * (0.6 + 0.8 * math.sin(math.pi * hour / 24) ** 2) * rnd.uniform(0.6, 1.4)
            tb = v * min(0.9, max(0.1, 0.5 + 0.35 * math.tanh(r / 0.0011) + rnd.gauss(0, 0.05)))
            raw.append((o, h, l, c, v, tb))
            px = c
        scale = TARGET.get(symbol, 100.0) / raw[-1][3]
        qty = 85000.0 / TARGET.get(symbol, 85000.0)        # volumes en coin : plus nombreux quand le prix est bas
        out = []
        for k, (o, h, l, c, v, tb) in enumerate(raw):
            out.append(Candle(SIM_START + k * M5, o * scale, h * scale, l * scale, c * scale, v * 40 * qty, tb * 40 * qty))
        self._m5[symbol] = out
        # Open Interest sur 30 jours (comme l'API Binance) : tendance + rafales de nouvelles positions + purges
        base = OI_BASE.get(symbol, 1e5)
        oi, series = base, []
        first = max(0, len(out) - 30 * 288)
        for k in range(first, len(out)):
            d = rnd.gauss(0.00002, 0.0004) * base
            if rnd.random() < 0.02:
                d += rnd.uniform(0.002, 0.009) * base
            if rnd.random() < 0.012:
                d -= 0.004 * oi
            oi = max(base * 0.3, oi + d)
            series.append((out[k].t + M5, oi))       # horodatage = fin de la bougie 5 min
        self._oi[symbol] = series

    def candles(self, symbol, interval, start_ms, end_ms):
        self._gen(symbol)
        if interval == "5m":
            data = self._m5[symbol]
        else:
            key = (symbol, interval)
            if key not in self._rs:
                self._rs[key] = resample(self._m5[symbol], INTERVAL_MS[interval])
            data = self._rs[key]
        return [k for k in data if start_ms <= k.t <= end_ms]

    def open_interest(self, symbol, period, start_ms, end_ms):
        self._gen(symbol)
        return [(t, v) for t, v in self._oi[symbol] if start_ms <= t <= end_ms]

    # --- contexte derives (V2), deterministes et plausibles ---
    def _last_close(self, symbol):
        self._gen(symbol)
        return self._m5[symbol][-1].c

    def premium_index(self, symbol):
        now = self.now_ms()
        c = self._last_close(symbol)
        basis = 0.0004 * math.sin(now / 3.6e7) + 0.0001
        return {"mark": c * (1 + basis), "index": c, "funding": 0.0001 + 0.00015 * math.sin(now / 9e7),
                "next_funding": now - now % 28_800_000 + 28_800_000}

    def funding_history(self, symbol, start_ms, end_ms):
        t = start_ms - start_ms % 28_800_000 + 28_800_000
        out = []
        while t <= end_ms:
            out.append((t, 0.0001 + 0.00015 * math.sin(t / 9e7)))
            t += 28_800_000
        return out

    def long_short(self, symbol, period, start_ms, end_ms, kind="global"):
        step = INTERVAL_MS[period]
        t = start_ms - start_ms % step + step
        out = []
        while t <= end_ms:
            r = (1.6 if kind == "global" else 1.1) + 0.35 * math.sin(t / 5e7 + (0 if kind == "global" else 1.3))
            out.append((t, r, r / (1 + r)))
            t += step
        return out

    def spot_price(self, symbol):
        return self._last_close(symbol) * (1 - 0.0002)

    def coinbase_price(self, product):
        sym = product.replace("-USD", "USDT")
        return self.spot_price(sym) * (1 + 0.0005 * math.sin(self.now_ms() / 4e7))
