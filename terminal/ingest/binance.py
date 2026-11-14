"""Binance : perpétuels USDT-M (fapi.binance.com) et comptant (api.binance.com), adresses publiques sans clé (V45).

Chaque méthode rend des enregistrements normalisés : heures en millisecondes UTC, prix et quantités en Decimal ou en unités entières
de 10^-8 (lus du texte envoyé par Binance), côté de l'agresseur +1 (achat) / -1 (vente).
Poids des appels (limite : 2 400 par minute sur les perpétuels, 6 000 sur le comptant) : passés au limiteur du client.

  agg_trades            /fapi/v1/aggTrades, /api/v3/aggTrades      transactions agrégées ; `m` vrai = acheteur passif = VENTE agressive
  klines_exact          /fapi/v1/klines, /api/v3/klines            bougies avec le volume acheteur agressif : barres exactes du CVD
  depth                 /fapi/v1/depth, /api/v3/depth              photo du carnet
  open_interest         /fapi/v1/openInterest                      intérêt ouvert à l'instant (pièces)
  open_interest_hist    /futures/data/openInterestHist             historique (30 jours au plus chez Binance)
  funding_rate          /fapi/v1/fundingRate                       taux publiés aux échéances, avec le prix de marque
  premium_index         /fapi/v1/premiumIndex                      prix de marque, indice, taux en cours, prochaine échéance
  long_short            /futures/data/globalLongShortAccountRatio  part des comptes longs et shorts
Flux en direct : noms `<paire>@aggTrade`, `<paire>@depth20@100ms` ; `parse_agg_trade` et `parse_depth20` lisent leurs messages."""
from __future__ import annotations
import time

from quant.num import D, to_ms, units
from .core import HttpClient, IngestError, need

FAPI = "https://fapi.binance.com"
SPOT = "https://api.binance.com"
FAPI_WS = "wss://fstream.binance.com"
SPOT_WS = "wss://stream.binance.com:9443"
INTERVAL_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000,
               "4h": 14_400_000, "6h": 21_600_000, "8h": 28_800_000, "12h": 43_200_000, "1d": 86_400_000}


def stream_agg_trade(symbol: str) -> str:
    return f"{symbol.lower()}@aggTrade"


def stream_depth20(symbol: str) -> str:
    return f"{symbol.lower()}@depth20@100ms"


def parse_agg_trade(x: dict) -> tuple:
    """Message aggTrade (flux ou API) -> (heure ms, prix en unités, quantité en unités, côté, numéro). Le texte de Binance est lu sans
    passer par un flottant."""
    return (int(x["T"]), units(x["p"]), units(x["q"]), -1 if x["m"] else 1, int(x["a"]))


def parse_depth20(x: dict) -> tuple:
    """Photo partielle du carnet (20 niveaux, toutes les 100 ms) -> (heure ms, bids, asks) en Decimal, du meilleur au moins bon.
    Perpétuels : champs b / a et T ; comptant : bids / asks, sans heure (None)."""
    bids = x.get("b") if "b" in x else x.get("bids")
    asks = x.get("a") if "a" in x else x.get("asks")
    if bids is None or asks is None:
        raise IngestError("carnet : champs bids / asks absents", "format")
    t = x.get("T") or x.get("E")
    return (int(t) if t else None, [(D(p), D(q)) for p, q in bids if D(q) > 0], [(D(p), D(q)) for p, q in asks if D(q) > 0])


def kline_row(r: list) -> tuple:
    """Bougie Binance -> barre exacte pour quant.flow.TickCvd.seed : (début, ouverture, haut, bas, clôture, achats agressifs, ventes
    agressives, achats en dollars, ventes en dollars, nombre de transactions), en unités entières. Le volume vendeur est le volume
    total moins le volume acheteur (soustraction d'entiers : exacte)."""
    v, tb = units(r[5]), units(r[9])
    q, tbq = units(r[7]), units(r[10])
    unit = 10 ** 8
    return (int(r[0]), units(r[1]), units(r[2]), units(r[3]), units(r[4]), tb, v - tb, tbq * unit, (q - tbq) * unit, int(r[8]))


class Binance:
    def __init__(self, fapi: HttpClient | None = None, spot: HttpClient | None = None):
        self.fapi = fapi or HttpClient("Binance perpétuels", FAPI, rate=20.0, burst=40.0, weight_limit=2400, weight_header="X-MBX-USED-WEIGHT-1M")
        self.spot = spot or HttpClient("Binance comptant", SPOT, rate=40.0, burst=80.0, weight_limit=6000, weight_header="X-MBX-USED-WEIGHT-1M")

    def _c(self, market: str) -> HttpClient:
        return self.spot if market == "spot" else self.fapi

    def clients(self):
        return [self.fapi, self.spot]

    def agg_trades(self, symbol: str, market: str = "perp", from_id: int | None = None, start_ms: int | None = None,
                   end_ms: int | None = None, limit: int = 1000) -> list:
        path = "/api/v3/aggTrades" if market == "spot" else "/fapi/v1/aggTrades"
        rows = self._c(market).get(path, {"symbol": symbol, "fromId": from_id, "startTime": start_ms, "endTime": end_ms, "limit": limit},
                                   weight=4 if market == "spot" else 20)
        if not isinstance(rows, list):
            raise IngestError("aggTrades : réponse inattendue", "format")
        return [parse_agg_trade(x) for x in rows]

    def klines_exact(self, symbol: str, interval: str = "1m", start_ms: int | None = None, end_ms: int | None = None,
                     market: str = "perp", limit: int | None = None, page: int | None = None, pause: float = 0.0, wait=None) -> list:
        """Barres exactes ; `limit` seul = les dernières ; avec start_ms : toutes les barres de l'intervalle (pagination).
        `page` : taille d'une page (499 = poids 2 sur les perpétuels au lieu de 10 pour 1 500) ; `pause` : secondes entre deux pages
        (`wait(secondes)` renvoie vrai s'il faut arrêter)."""
        path, cap = ("/api/v3/klines", 1000) if market == "spot" else ("/fapi/v1/klines", 1500)
        if page:
            cap = min(cap, int(page))
        c = self._c(market)
        if start_ms is None:
            n = min(limit or cap, cap)
            rows = c.get(path, {"symbol": symbol, "interval": interval, "endTime": end_ms, "limit": n},
                         weight=2 if market == "spot" else (1 if n < 100 else 2 if n < 500 else 5 if n <= 1000 else 10))
            return [kline_row(r) for r in rows]
        out, t, step = [], start_ms, INTERVAL_MS[interval]
        while end_ms is None or t <= end_ms:
            rows = c.get(path, {"symbol": symbol, "interval": interval, "startTime": t, "endTime": end_ms, "limit": cap},
                         weight=2 if market == "spot" else (1 if cap < 100 else 2 if cap < 500 else 5 if cap <= 1000 else 10))
            if not rows:
                break
            out += [kline_row(r) for r in rows]
            t = int(rows[-1][0]) + step
            if len(rows) < cap:
                break
            if pause and (wait(pause) if wait else time.sleep(pause)):
                break
        return out

    def depth(self, symbol: str, limit: int = 1000, market: str = "perp") -> dict:
        path = "/api/v3/depth" if market == "spot" else "/fapi/v1/depth"
        r = self._c(market).get(path, {"symbol": symbol, "limit": limit}, weight=20 if limit > 500 else 10 if limit > 100 else 5)
        t, bids, asks = parse_depth20(r)
        return {"lastUpdateId": int(need(r, "lastUpdateId")), "t": t, "bids": bids, "asks": asks}

    def open_interest(self, symbol: str) -> tuple:
        r = self.fapi.get("/fapi/v1/openInterest", {"symbol": symbol}, retries=2)
        return to_ms(need(r, "time")), D(need(r, "openInterest"))

    def open_interest_hist(self, symbol: str, period: str = "5m", limit: int = 500, start_ms: int | None = None,
                           end_ms: int | None = None) -> list:
        """[(heure ms, intérêt ouvert en pièces, en dollars)], du plus ancien au plus récent."""
        rows = self.fapi.get("/futures/data/openInterestHist", {"symbol": symbol, "period": period, "limit": limit, "startTime": start_ms,
                                                                "endTime": end_ms}, weight=1)
        return sorted((to_ms(r["timestamp"]), D(r["sumOpenInterest"]), D(r["sumOpenInterestValue"])) for r in rows)

    def funding_rate(self, symbol: str, start_ms: int | None = None, end_ms: int | None = None, limit: int = 1000) -> list:
        """[(heure de l'échéance ms, taux, prix de marque ou None)], du plus ancien au plus récent."""
        rows = self.fapi.get("/fapi/v1/fundingRate", {"symbol": symbol, "startTime": start_ms, "endTime": end_ms, "limit": limit}, weight=1)
        out = []
        for r in rows:
            mp = r.get("markPrice")
            out.append((to_ms(r["fundingTime"]), D(r["fundingRate"]), D(mp) if mp not in (None, "") else None))
        return sorted(out, key=lambda x: x[0])

    def premium_index(self, symbol: str) -> dict:
        r = self.fapi.get("/fapi/v1/premiumIndex", {"symbol": symbol}, retries=2)
        return {"t": to_ms(need(r, "time")), "mark": D(need(r, "markPrice")), "index": D(need(r, "indexPrice")),
                "funding": D(need(r, "lastFundingRate")), "nextFunding": to_ms(need(r, "nextFundingTime"))}

    def long_short(self, symbol: str, period: str = "5m", limit: int = 30) -> list:
        """[(heure ms, ratio long / short, part des comptes longs, part des comptes shorts)]."""
        rows = self.fapi.get("/futures/data/globalLongShortAccountRatio", {"symbol": symbol, "period": period, "limit": limit}, weight=1)
        return sorted((to_ms(r["timestamp"]), D(r["longShortRatio"]), D(r["longAccount"]), D(r["shortAccount"])) for r in rows)
