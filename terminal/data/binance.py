"""Source BINANCE (futures USDT-M, endpoints publics, sans cle). Ecrit d'apres la documentation de l'API ;
a verifier sur ton PC avec :  python run.py --selftest
Bougies : /fapi/v1/klines (index 9 = volume acheteur agressif, index 7 = volume en dollars : prix moyen exact, V23) ; OI : /futures/data/openInterestHist
(5 min, limite a 30 jours par Binance)."""
from __future__ import annotations
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from engine.atr import Candle, INTERVAL_MS
from . import listing
from .base import DataError, Source

FAPI = "https://fapi.binance.com"
SPOT = "https://api.binance.com"
COINBASE = "https://api.exchange.coinbase.com"


class BinanceSource(Source):
    name = "binance"

    def __init__(self, base: str = FAPI, timeout: int = 20, pause: float = 0.12, retries: int = 3,
                 spot_base: str = SPOT, coinbase_base: str = COINBASE):
        self.base, self.timeout, self.pause, self.retries = base.rstrip("/"), timeout, pause, retries
        self.spot_base, self.coinbase_base = spot_base.rstrip("/"), coinbase_base.rstrip("/")
        self.cool_until: dict = {}           # V46 : serveur -> heure avant laquelle on ne l'appelle plus (il a repondu « trop de requetes »)

    def _get(self, path: str, params: dict | None = None, host: str | None = None, retries: int | None = None,
             timeout: float | None = None):
        url = (host or self.base) + path + ("?" + urllib.parse.urlencode(params) if params else "")
        last = None
        retries = retries or self.retries
        srv = host or self.base
        left = self.cool_until.get(srv, 0.0) - time.time()
        if left > 0:                                              # V46 : le serveur a demande une pause : on la respecte, sans insister
            raise DataError(f"pause demandée par le serveur (trop de requêtes) : reprise dans {int(left) + 1} s ({srv.split('//')[-1]})")
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "liq-terminal/1.0"})
                with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:200]
                if e.code in (429, 418):
                    # V46 : « trop de requetes » (429) ou adresse bannie (418). Reessayer tout de suite aggrave le blocage (Binance
                    # allonge le bannissement) : on arrete d'appeler ce serveur pendant la duree qu'il annonce (sinon 60 s / 120 s).
                    try:
                        wait = float(e.headers.get("Retry-After")) if e.headers and e.headers.get("Retry-After") else 0.0
                    except (TypeError, ValueError):
                        wait = 0.0
                    wait = min(3600.0, max(wait, 60.0 if e.code == 429 else 120.0))
                    self.cool_until[srv] = time.time() + wait
                    raise DataError(f"HTTP {e.code} : trop de requêtes, pause de {int(wait)} s demandée par le serveur ({url.split('?')[0]})") from e
                if e.code in (500, 502, 503, 504) and attempt < retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                    last = f"HTTP {e.code}"
                    continue
                hint = " (acces refuse depuis ta region ou ton reseau ?)" if e.code in (403, 451) else ""
                raise DataError(f"HTTP {e.code}{hint} ({url.split('?')[0]}) : {body}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = str(e)
                time.sleep(1.0 * (attempt + 1))
        raise DataError(f"injoignable : {url.split('?')[0]} ({last})")

    @staticmethod
    def parse_klines(rows):
        out = []
        for r in rows:
            try:
                q = float(r[7])                                   # volume en dollars : prix moyen exact de la bougie (V23)
            except (TypeError, ValueError, IndexError):
                q = 0.0
            try:
                bq = float(r[10])                                 # V37 : volume acheteur agressif en dollars (delta en dollars exact)
            except (TypeError, ValueError, IndexError):
                bq = 0.0
            out.append(Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]), float(r[9]), q, bq))
        return out

    @staticmethod
    def parse_oi(rows):
        return [(int(r["timestamp"]), float(r["sumOpenInterest"])) for r in rows]

    def candles(self, symbol, interval, start_ms, end_ms):
        step = INTERVAL_MS[interval]
        out, t = [], listing.clamp(symbol, start_ms)                # V42 : jamais avant le premier jour de la paire (data/listing.py)
        while t <= end_ms:
            lim = page_limit(t, end_ms, step, 1500)
            rows = self._get("/fapi/v1/klines", {"symbol": symbol, "interval": interval,
                                                   "startTime": t, "endTime": end_ms, "limit": lim})
            if not rows:
                break
            out += self.parse_klines(rows)
            t = int(rows[-1][0]) + step
            if len(rows) < lim:
                break
            time.sleep(self.pause)
        return out

    def open_interest(self, symbol, period, start_ms, end_ms):
        step = INTERVAL_MS[period]
        out, t = [], listing.clamp(symbol, start_ms)
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

    def open_interest_now(self, symbol):
        """V37 : /fapi/v1/openInterest, l'intérêt ouvert à l'instant (les relevés 5 min de openInterestHist ont plusieurs minutes de retard)."""
        r = self._get("/fapi/v1/openInterest", {"symbol": symbol}, retries=1)
        return int(r.get("time") or self.now_ms()), float(r["openInterest"])

    def spot_candles(self, symbol, interval, start_ms, end_ms):
        """V37 : bougies spot (/api/v3/klines : index 9 et 10 = volume acheteur agressif en coin et en dollars), 1000 par appel."""
        step = INTERVAL_MS[interval]
        out, t = [], listing.clamp(symbol, start_ms, "spot")
        while t <= end_ms:
            lim = page_limit(t, end_ms, step, 1000)
            rows = self._get("/api/v3/klines", {"symbol": symbol, "interval": interval, "startTime": t, "endTime": end_ms, "limit": lim},
                             host=self.spot_base)
            if not rows:
                break
            out += self.parse_klines(rows)
            t = int(rows[-1][0]) + step
            if len(rows) < lim:
                break
            time.sleep(self.pause)
        return out

    # --- contexte derives (V2) ---
    def premium_index(self, symbol):
        """Prix mark, prix index (spot agrege), dernier funding (par 8 h), prochaine echeance."""
        r = self._get("/fapi/v1/premiumIndex", {"symbol": symbol})
        return {"mark": float(r["markPrice"]), "index": float(r["indexPrice"]), "funding": float(r["lastFundingRate"]),
                "next_funding": int(r["nextFundingTime"])}

    def funding_history(self, symbol, start_ms, end_ms):
        out, t = [], listing.clamp(symbol, start_ms)
        while t <= end_ms:
            rows = self._get("/fapi/v1/fundingRate", {"symbol": symbol, "startTime": t, "endTime": end_ms, "limit": 1000})
            if not rows:
                break
            out += [(int(r["fundingTime"]), float(r["fundingRate"])) for r in rows]
            if len(rows) < 1000:
                break
            t = int(rows[-1]["fundingTime"]) + 1
            time.sleep(self.pause)
        return out

    def long_short(self, symbol, period, start_ms, end_ms, kind="global"):
        """Ratio long/short : 'global' = comptes, 'top' = positions des gros traders. [(t, ratio, part long)]"""
        path = "/futures/data/globalLongShortAccountRatio" if kind == "global" else "/futures/data/topLongShortPositionRatio"
        rows = self._get(path, {"symbol": symbol, "period": period, "limit": 500, "startTime": listing.clamp(symbol, start_ms), "endTime": end_ms})
        out = []
        for r in rows:
            lg = r.get("longAccount", r.get("longPosition"))
            out.append((int(r["timestamp"]), float(r["longShortRatio"]), float(lg) if lg is not None else None))
        return out

    def spot_price(self, symbol):
        return float(self._get("/api/v3/ticker/price", {"symbol": symbol}, host=self.spot_base)["price"])

    def coinbase_price(self, product):
        return float(self._get(f"/products/{product}/ticker", None, host=self.coinbase_base)["price"])

    def last_price(self, symbol):
        """Dernier prix (une seule tentative, delai court : appele chaque seconde quand le flux temps reel
        du navigateur est coupe)."""
        try:
            r = self._get("/fapi/v1/ticker/price", {"symbol": symbol}, retries=1, timeout=4)
        except DataError:
            r = self._get("/fapi/v2/ticker/price", {"symbol": symbol}, retries=1, timeout=4)
        return float(r["price"]), int(r.get("time") or self.now_ms())

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
        for name, fn in (("funding / prix mark (fapi)", lambda: self.premium_index(symbol)["funding"]),
                         ("ratio long/short (fapi)", lambda: len(self.long_short(symbol, "1h", now - 6 * 3_600_000, now))),
                         ("prix spot (api.binance.com)", lambda: self.spot_price(symbol)),
                         ("prix Coinbase (api.exchange.coinbase.com)", lambda: self.coinbase_price(coinbase_product(symbol)))):
            try:
                res.append((name, True, str(fn())))
            except (DataError, KeyError, ValueError) as e:
                res.append((name, False, str(e) + " (optionnel : le terminal fonctionne sans)"))
        return res


def page_limit(start_ms: int, end_ms: int, step: int, cap: int) -> int:
    """V46 : nombre de bougies a demander pour couvrir [start, end], au plus `cap`. Binance facture une requete de bougies selon ce
    nombre (perpetuels : 1 point jusqu'a 99 bougies, 2 jusqu'a 499, 5 jusqu'a 1 000, 10 au-dela). Le terminal demandait toujours 1 500
    bougies, meme pour n'en lire que deux a chaque cycle : presque tout le quota de 2 400 points par minute y passait."""
    need = (end_ms - start_ms) // step + 2
    for tier in (99, 499, 1000):
        if need <= tier <= cap:
            return tier
    return cap


def coinbase_product(symbol: str) -> str:
    """BTCUSDT -> BTC-USD (paire Coinbase en dollars)."""
    base = symbol[:-4] if symbol.endswith("USDT") else symbol[:-3]
    return f"{base}-USD"
