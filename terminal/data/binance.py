"""Source BINANCE (futures USDT-M, endpoints publics, sans cle). Ecrit d'apres la documentation de l'API ;
a verifier sur ton PC avec :  python run.py --selftest
Bougies : /fapi/v1/klines (index 9 = volume acheteur agressif) ; OI : /futures/data/openInterestHist
(5 min, limite a 30 jours par Binance)."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from engine.atr import Candle, INTERVAL_MS
from .base import DataError, Source

FAPI = "https://fapi.binance.com"


class BinanceSource(Source):
    name = "binance"

    def __init__(self, base: str = FAPI, timeout: int = 20, pause: float = 0.12, retries: int = 3):
        self.base, self.timeout, self.pause, self.retries = base.rstrip("/"), timeout, pause, retries

    def _get(self, path: str, params: dict | None = None):
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        last = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "liq-terminal/1.0"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:200]
                if e.code in (429, 418, 500, 502, 503, 504) and attempt < self.retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                    last = f"HTTP {e.code}"
                    continue
                hint = " (acces refuse depuis ta region ou ton reseau ?)" if e.code in (403, 451) else ""
                raise DataError(f"Binance HTTP {e.code}{hint} : {body}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = str(e)
                time.sleep(1.0 * (attempt + 1))
        raise DataError(f"Binance injoignable ({last})")

    @staticmethod
    def parse_klines(rows):
        out = []
        for r in rows:
            out.append(Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]), float(r[9])))
        return out

    @staticmethod
    def parse_oi(rows):
        return [(int(r["timestamp"]), float(r["sumOpenInterest"])) for r in rows]

    def candles(self, symbol, interval, start_ms, end_ms):
        step = INTERVAL_MS[interval]
        out, t = [], start_ms
        while t <= end_ms:
            rows = self._get("/fapi/v1/klines", {"symbol": symbol, "interval": interval,
                                                   "startTime": t, "endTime": end_ms, "limit": 1500})
            if not rows:
                break
            out += self.parse_klines(rows)
            t = int(rows[-1][0]) + step
            if len(rows) < 1500:
                break
            time.sleep(self.pause)
        return out

    def open_interest(self, symbol, period, start_ms, end_ms):
        step = INTERVAL_MS[period]
        out, t = [], start_ms
        while t <= end_ms:
            rows = self._get("/futures/data/openInterestHist",
                             {"symbol": symbol, "period": period, "limit": 500,
                              "startTime": t, "endTime": min(end_ms, t + 500 * step)})
            if rows:
                out += self.parse_oi(rows)
                t = max(t + step, int(rows[-1]["timestamp"]) + step)
            else:
                t += 500 * step
            time.sleep(self.pause)
        return out

    def selftest(self, symbol="BTCUSDT"):
        """Verifications rapides : renvoie une liste de (nom, ok, detail)."""
        res = []
        try:
            self._get("/fapi/v1/ping")
            res.append(("ping fapi.binance.com", True, "ok"))
        except DataError as e:
            return [("ping fapi.binance.com", False, str(e))]
        try:
            now = self.now_ms()
            ks = self.candles(symbol, "1h", now - 6 * 3_600_000, now)
            ok = len(ks) >= 3 and all(k.h >= k.l for k in ks)
            res.append((f"bougies 1h {symbol}", ok, f"{len(ks)} bougies, derniere cloture {ks[-1].c if ks else '-'}"))
            res.append(("volume acheteur (taker) present", any(k.tb > 0 for k in ks), "ok" if any(k.tb > 0 for k in ks) else "absent"))
        except DataError as e:
            res.append((f"bougies 1h {symbol}", False, str(e)))
        try:
            oi = self.open_interest(symbol, "5m", now - 2 * 3_600_000, now)
            res.append((f"Open Interest 5m {symbol}", len(oi) >= 5, f"{len(oi)} points, dernier {oi[-1][1] if oi else '-'}"))
        except DataError as e:
            res.append((f"Open Interest 5m {symbol}", False, str(e)))
        return res
