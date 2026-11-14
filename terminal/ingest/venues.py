"""Bybit, OKX et Deribit : adresses publiques sans clé (V45). Mêmes règles que ingest.binance (heures en ms UTC, textes lus en Decimal).

Bybit (api.bybit.com, V5)
  open_interest     /v5/market/open-interest      intérêt ouvert (pièces), du plus ancien au plus récent
  funding_history   /v5/market/funding/history    taux publiés aux échéances
  ticker            /v5/market/tickers            prix de marque, indice, taux en cours, intérêt ouvert
  risk_limit        /v5/market/risk-limit         paliers de marge de maintien (publics chez Bybit)
  parse_public_trade : message du flux publicTrade.<paire> ; `S` est le côté de l'AGRESSEUR (Buy = achat agressif).
OKX (www.okx.com, V5)
  open_interest     /api/v5/public/open-interest          en contrats et en pièces
  funding_history   /api/v5/public/funding-rate-history   taux réalisés
  funding_now       /api/v5/public/funding-rate           taux de la période en cours
  trades            /api/v5/market/trades                 dernières transactions ; `side` est le côté de l'agresseur
  position_tiers    /api/v5/public/position-tiers         paliers de marge (par taille de position, en contrats)
Deribit (www.deribit.com/api/v2/public)
  instruments       get_instruments                échéance exacte, strike, type, taille du contrat de chaque option
  book_summary      get_book_summary_by_currency   intérêt ouvert, volatilité implicite de marque, prix à terme, prime de marque
  option_chain      les deux réunis en lignes pour quant.options
  ticker            ticker                         grecques publiées par Deribit (contrôle de nos formules)
  index_price       get_index_price
Chaque réponse qui porte un code d'erreur (retCode, code, error) lève IngestError : jamais de liste vide silencieuse."""
from __future__ import annotations
from decimal import Decimal

from quant.num import D, to_ms, units
from .core import HttpClient, IngestError, need

BYBIT = "https://api.bybit.com"
OKX = "https://www.okx.com"
DERIBIT = "https://www.deribit.com"
OKX_CT = {"BTC-USDT-SWAP": "0.01", "ETH-USDT-SWAP": "0.1", "SOL-USDT-SWAP": "1"}       # taille d'un contrat en pièces (documentation OKX)


def coin_of(symbol: str) -> str:
    return symbol[:-4] if symbol.upper().endswith("USDT") else symbol


# =====================================================================================================
#  Bybit
# =====================================================================================================
def parse_public_trade(msg: dict) -> list:
    """Message publicTrade -> [(heure ms, prix u, quantité u, côté, identifiant)]."""
    out = []
    for x in msg.get("data") or ():
        out.append((int(x["T"]), units(x["p"]), units(x["v"]), 1 if x["S"] == "Buy" else -1, x.get("i")))
    return out


class Bybit:
    def __init__(self, http: HttpClient | None = None):
        self.http = http or HttpClient("Bybit", BYBIT, rate=5.0, burst=10.0)

    def _result(self, r: dict) -> dict:
        if not isinstance(r, dict) or r.get("retCode") != 0:
            raise IngestError(f"Bybit : {r.get('retMsg') if isinstance(r, dict) else 'réponse inattendue'}", "format")
        return need(r, "result")

    def open_interest(self, symbol: str, interval: str = "5min", limit: int = 200, category: str = "linear") -> list:
        res = self._result(self.http.get("/v5/market/open-interest", {"category": category, "symbol": symbol, "intervalTime": interval, "limit": limit}))
        return sorted((to_ms(x["timestamp"]), D(x["openInterest"])) for x in need(res, "list"))

    def funding_history(self, symbol: str, limit: int = 200, start_ms: int | None = None, end_ms: int | None = None, category: str = "linear") -> list:
        res = self._result(self.http.get("/v5/market/funding/history", {"category": category, "symbol": symbol, "limit": limit,
                                                                         "startTime": start_ms, "endTime": end_ms}))
        return sorted((to_ms(x["fundingRateTimestamp"]), D(x["fundingRate"])) for x in need(res, "list"))

    def ticker(self, symbol: str, category: str = "linear") -> dict:
        res = self._result(self.http.get("/v5/market/tickers", {"category": category, "symbol": symbol}, retries=2))
        x = need(res, "list", 0)
        return {"mark": D(x["markPrice"]), "index": D(x["indexPrice"]), "last": D(x["lastPrice"]), "funding": D(x["fundingRate"]),
                "nextFunding": to_ms(x["nextFundingTime"]), "oi": D(x["openInterest"]), "oiUsd": D(x["openInterestValue"])}

    def risk_limit(self, symbol: str, category: str = "linear") -> list:
        """Paliers pour quant.perp.liquidation_price : [(notionnel maximal, taux de marge de maintien, montant de maintien)]."""
        res = self._result(self.http.get("/v5/market/risk-limit", {"category": category, "symbol": symbol}, ttl=3600))
        out = []
        for x in need(res, "list"):
            out.append((D(x["riskLimitValue"]), D(x["maintenanceMargin"]), D(x.get("mmDeduction") or "0")))
        return sorted(out)


# =====================================================================================================
#  OKX
# =====================================================================================================
def okx_inst(symbol: str) -> str:
    return f"{coin_of(symbol.upper())}-USDT-SWAP"


def parse_okx_trade(x: dict, ct_val=None) -> tuple:
    """Transaction OKX -> (heure ms, prix u, quantité u en pièces, côté, numéro). `sz` est en contrats sur les perpétuels : multiplié par la
    taille du contrat (`ct_val`, texte) ; sur le comptant ct_val est None."""
    px, sz = units(x["px"]), D(x["sz"])
    q = sz * D(ct_val) if ct_val is not None else sz
    return (int(x["ts"]), px, units(format(q, "f")), 1 if x["side"] == "buy" else -1, x.get("tradeId"))


class Okx:
    def __init__(self, http: HttpClient | None = None):
        self.http = http or HttpClient("OKX", OKX, rate=5.0, burst=10.0, user_agent="Mozilla/5.0 (liq-terminal/45)")

    def _data(self, r: dict) -> list:
        if not isinstance(r, dict) or str(r.get("code")) != "0":
            raise IngestError(f"OKX : {r.get('msg') if isinstance(r, dict) else 'réponse inattendue'}", "format")
        return need(r, "data")

    def open_interest(self, inst: str) -> dict:
        x = need(self._data(self.http.get("/api/v5/public/open-interest", {"instType": "SWAP", "instId": inst}, retries=2)), 0)
        return {"t": to_ms(x["ts"]), "contracts": D(x["oi"]), "coins": D(x["oiCcy"]), "usd": D(x["oiUsd"]) if x.get("oiUsd") else None}

    def funding_history(self, inst: str, limit: int = 100, before_ms: int | None = None, after_ms: int | None = None) -> list:
        """[(heure ms, taux réalisé)] du plus ancien au plus récent."""
        rows = self._data(self.http.get("/api/v5/public/funding-rate-history", {"instId": inst, "limit": limit, "before": before_ms, "after": after_ms}))
        return sorted((to_ms(x["fundingTime"]), D(x.get("realizedRate") or x["fundingRate"])) for x in rows)

    def funding_now(self, inst: str) -> dict:
        x = need(self._data(self.http.get("/api/v5/public/funding-rate", {"instId": inst}, retries=2)), 0)
        return {"t": to_ms(x["ts"]), "funding": D(x["fundingRate"]), "fundingTime": to_ms(x["fundingTime"]),
                "nextFunding": to_ms(x["nextFundingTime"]) if x.get("nextFundingTime") else None,
                "premium": D(x["premium"]) if x.get("premium") else None}

    def trades(self, inst: str, limit: int = 100) -> list:
        rows = self._data(self.http.get("/api/v5/market/trades", {"instId": inst, "limit": limit}, retries=2))
        ct = OKX_CT.get(inst) if inst.endswith("-SWAP") else None
        if inst.endswith("-SWAP") and ct is None:
            raise IngestError(f"OKX : taille de contrat inconnue pour {inst}", "format")
        return sorted(parse_okx_trade(x, ct) for x in rows)

    def position_tiers(self, family: str, td_mode: str = "isolated") -> list:
        """[(taille maximale en contrats, taux de marge de maintien, taux de marge initiale, levier maximal)], du plus petit au plus grand."""
        rows = self._data(self.http.get("/api/v5/public/position-tiers", {"instType": "SWAP", "tdMode": td_mode, "instFamily": family}, ttl=3600))
        return sorted((D(x["maxSz"]), D(x["mmr"]), D(x["imr"]), D(x["maxLever"])) for x in rows)


def okx_mmr(contracts, tiers: list) -> Decimal:
    """Taux de marge de maintien d'une position de `contracts` contrats (premier palier dont la taille maximale suffit)."""
    n = D(contracts)
    for max_sz, mmr, _imr, _lev in tiers:
        if n <= max_sz:
            return mmr
    raise IngestError("OKX : position au-delà du dernier palier", "format")


# =====================================================================================================
#  Deribit
# =====================================================================================================
class Deribit:
    def __init__(self, http: HttpClient | None = None):
        self.http = http or HttpClient("Deribit", DERIBIT, rate=5.0, burst=10.0)

    def _call(self, method: str, params: dict, ttl: float = 0.0, retries: int | None = None):
        r = self.http.get(f"/api/v2/public/{method}", params, ttl=ttl, retries=retries)
        if not isinstance(r, dict) or "result" not in r:
            err = r.get("error") if isinstance(r, dict) else None
            raise IngestError(f"Deribit {method} : {err or 'réponse inattendue'}", "format")
        return r["result"], r.get("usOut")

    def instruments(self, currency: str = "BTC", kind: str = "option") -> dict:
        """{nom: {expiry ms, strike, type 'C' / 'P', contract_size}} des instruments ouverts."""
        res, _ = self._call("get_instruments", {"currency": currency, "kind": kind, "expired": "false"}, ttl=1800)
        out = {}
        for x in res:
            out[x["instrument_name"]] = {"expiry": to_ms(x["expiration_timestamp"]), "strike": D(x["strike"]) if x.get("strike") is not None else None,
                                         "kind": {"call": "C", "put": "P"}.get(x.get("option_type")), "size": D(x.get("contract_size", 1))}
        return out

    def book_summary(self, currency: str = "BTC", kind: str = "option") -> tuple:
        """(lignes brutes, heure du serveur en ms)."""
        res, us = self._call("get_book_summary_by_currency", {"currency": currency, "kind": kind})
        if not isinstance(res, list) or not res:
            raise IngestError(f"Deribit {kind} {currency} : aucune ligne", "format")
        return res, (to_ms(us) if us else None)

    def option_chain(self, currency: str = "BTC") -> dict:
        """Chaîne complète : {"t": heure serveur, "index": prix de l'indice, "rows": [...]}. Chaque ligne : name, strike, kind, expiry,
        oi (pièces), iv (fraction), f (prix à terme de l'échéance), mark (prime en pièces), size ; en FLOTTANTS pour le modèle de Black
        (voir quant.options), sauf oiText (texte exact de l'intérêt ouvert). Les options sans intérêt ouvert sont gardées (le sourire de
        volatilité en a besoin) ; celles sans volatilité ou sans prix à terme sont écartées et comptées dans `skipped`."""
        inst = self.instruments(currency, "option")
        res, t = self.book_summary(currency, "option")
        rows, skipped, index = [], 0, None
        for s in res:
            i = inst.get(s.get("instrument_name"))
            iv, f = s.get("mark_iv"), s.get("underlying_price")
            if i is None or i["kind"] is None or iv is None or f is None or iv <= 0 or f <= 0:
                skipped += 1
                continue
            if s.get("estimated_delivery_price"):
                index = s["estimated_delivery_price"]
            oi = s.get("open_interest") or 0
            rows.append({"name": s["instrument_name"], "strike": float(i["strike"]), "kind": i["kind"], "expiry": i["expiry"],
                         "oi": float(oi) * float(i["size"]), "oiText": format((D(oi) * i["size"]).normalize(), "f"),
                         "iv": float(D(iv) / 100), "f": float(f),
                         "mark": float(s["mark_price"]) if s.get("mark_price") is not None else None, "size": float(i["size"])})
        if not rows:
            raise IngestError(f"Deribit {currency} : aucune option exploitable", "format")
        return {"t": t, "index": float(index) if index is not None else None, "rows": rows, "skipped": skipped}

    def ticker(self, name: str) -> dict:
        res, us = self._call("ticker", {"instrument_name": name}, retries=2)
        return {"t": to_ms(res.get("timestamp") or us), "raw": res}

    def index_price(self, index: str = "btc_usd") -> Decimal:
        res, _ = self._call("get_index_price", {"index_name": index}, retries=2)
        return D(need(res, "index_price"))
