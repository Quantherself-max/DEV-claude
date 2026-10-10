"""Derives et positionnement multi-bourses (V9), tout en acces public, sans cle ni compte :

  - Deribit : options du BTC / ETH (interet ouvert par strike et echeance -> « max pain », ratio put / call, murs d'options), indice de volatilite implicite DVOL,
    base des futures datees (annualisee) ;
  - Bybit, OKX, Hyperliquid : financement (annualise), interet ouvert en dollars et prix de marque du perpetuel de la paire suivie, pour comparer a Binance.
Pourquoi : un financement tres positif PARTOUT = foule longue (carburant de liquidation) ; une base annualisee elevee = levier en cours ; les strikes d'options chargent
le prix d'aimants (max pain) a l'approche de l'echeance ; le DVOL dit ce que le marche paie pour se couvrir.
Les fonctions de calcul sont PURES (testees sans reseau) ; les classes reseau levent DataError : le hub garde l'erreur et reessaie plus tard.
Format des reponses : documentation publique des bourses ; non verifie ici contre les vrais serveurs (aucun acces) : toute reponse inattendue donne une erreur lisible,
jamais un faux chiffre."""
import json
import math
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .base import DataError

DERIBIT = "https://www.deribit.com"
BYBIT = "https://api.bybit.com"
OKX = "https://www.okx.com"
HYPER = "https://api.hyperliquid.xyz"
MONTHS = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}
HOUR = 3_600_000
DAY = 86_400_000


def post_json(url: str, payload: dict, timeout: float = 15.0):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "User-Agent": "liq-terminal/9.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        e.close()
        raise DataError(f"HTTP {e.code} ({url.split('?')[0]})") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
        raise DataError(f"injoignable : {url.split('?')[0]} ({type(e).__name__})") from e


def coin_of(symbol: str) -> str:
    """SOLUSDT -> SOL."""
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


# =====================================================================================================
#  Calculs purs
# =====================================================================================================
OPT_RE = re.compile(r"^([A-Z]+)-(\d{1,2})([A-Z]{3})(\d{2})-(\d+(?:\.\d+)?)-([CP])$")
FUT_RE = re.compile(r"^([A-Z]+)-(\d{1,2})([A-Z]{3})(\d{2})$")


def parse_expiry(day: str, mon: str, yy: str) -> int | None:
    """Les echeances Deribit expirent a 08:00 UTC."""
    try:
        return int(datetime(2000 + int(yy), MONTHS[mon], int(day), 8, tzinfo=timezone.utc).timestamp() * 1000)
    except (KeyError, ValueError):
        return None


def parse_option(name: str):
    m = OPT_RE.match(name or "")
    if not m:
        return None
    exp = parse_expiry(m.group(2), m.group(3), m.group(4))
    return None if exp is None else {"coin": m.group(1), "expiry": exp, "strike": float(m.group(5)), "kind": m.group(6)}


def max_pain(oi_by_strike: dict[float, tuple[float, float]]) -> float | None:
    """Strike qui minimise le montant total a payer aux detenteurs d'options a l'echeance. {strike: (oi_calls, oi_puts)}."""
    if not oi_by_strike:
        return None
    strikes = sorted(oi_by_strike)
    best, best_k = None, None
    for k in strikes:
        pay = sum(c * max(0.0, k - s) + p * max(0.0, s - k) for s, (c, p) in oi_by_strike.items())
        if best is None or pay < best:
            best, best_k = pay, k
    return best_k


def options_view(summaries: list[dict], now_ms: int, max_expiries: int = 4) -> dict:
    """Resume des options depuis get_book_summary_by_currency(kind=option) : ratio put/call, max pain et murs par echeance, interet ouvert total en dollars."""
    by_exp: dict[int, dict] = {}
    spot = None
    for s in summaries:
        o = parse_option(s.get("instrument_name", ""))
        oi = num(s.get("open_interest"))
        if not o or oi is None or oi <= 0 or o["expiry"] <= now_ms:
            continue
        up = num(s.get("underlying_price"))
        spot = up or spot
        e = by_exp.setdefault(o["expiry"], {"strikes": {}, "calls": 0.0, "puts": 0.0})
        c, p = e["strikes"].get(o["strike"], (0.0, 0.0))
        e["strikes"][o["strike"]] = (c + oi, p) if o["kind"] == "C" else (c, p + oi)
        e["calls" if o["kind"] == "C" else "puts"] += oi
    if not by_exp or not spot:
        raise DataError("options : aucune échéance exploitable")
    exps = []
    for t in sorted(by_exp)[:max_expiries]:
        e = by_exp[t]
        walls = sorted(((c + p, k, c, p) for k, (c, p) in e["strikes"].items()), reverse=True)[:3]
        exps.append({"expiry": t, "daysLeft": (t - now_ms) / DAY, "maxPain": max_pain(e["strikes"]), "calls": e["calls"], "puts": e["puts"],
                     "putCall": e["puts"] / e["calls"] if e["calls"] > 0 else None, "oiUsd": (e["calls"] + e["puts"]) * spot,
                     "walls": [{"strike": k, "oi": tot, "calls": c, "puts": p} for tot, k, c, p in walls]})
    calls = sum(e["calls"] for e in by_exp.values())
    puts = sum(e["puts"] for e in by_exp.values())
    return {"spot": spot, "putCall": puts / calls if calls > 0 else None, "oiUsd": (calls + puts) * spot, "expiries": exps}


def futures_basis(summaries: list[dict], now_ms: int) -> list[dict]:
    """Base annualisee des futures datees : (mark / index - 1) x 365 / jours restants. Le perpetuel est renvoye avec son financement."""
    out = []
    for s in summaries:
        name = s.get("instrument_name", "")
        mark, idx = num(s.get("mark_price")), num(s.get("estimated_delivery_price"))
        if not mark or not idx:
            continue
        if name.endswith("PERPETUAL"):
            out.append({"name": name, "perp": True, "basis": mark / idx - 1.0, "funding8h": num(s.get("funding_8h")), "oi": num(s.get("open_interest"))})
            continue
        m = FUT_RE.match(name)
        exp = parse_expiry(*m.group(2, 3, 4)) if m else None
        if exp is None or exp <= now_ms:
            continue
        days = (exp - now_ms) / DAY
        out.append({"name": name, "perp": False, "expiry": exp, "daysLeft": days, "basis": mark / idx - 1.0, "annualized": (mark / idx - 1.0) * 365.0 / days, "oi": num(s.get("open_interest"))})
    return sorted(out, key=lambda r: (not r["perp"], r.get("expiry", 0)))


def dvol_view(rows: list) -> dict:
    """Derniere valeur de l'indice, variation 24 h et 7 jours, rang percentile sur la fenetre recue. rows = [[t, open, high, low, close], ...]."""
    pts = sorted((int(r[0]), float(r[4])) for r in rows if len(r) >= 5 and num(r[4]) is not None)
    if len(pts) < 10:
        raise DataError("DVOL : trop peu de points")
    t, v = pts[-1]
    at = lambda back: next((c for tt, c in reversed(pts) if tt <= t - back), None)
    vals = sorted(c for _, c in pts)
    d1, d7 = at(DAY), at(7 * DAY)
    return {"t": t, "value": v, "chg24h": (v / d1 - 1.0) if d1 else None, "chg7d": (v / d7 - 1.0) if d7 else None, "rank": sum(1 for x in vals if x <= v) / len(vals), "days": (pts[-1][0] - pts[0][0]) / DAY}


def funding_annualized(rate: float, interval_h: float) -> float:
    return rate * (8760.0 / interval_h)


def compare_view(rows: list[dict]) -> dict:
    """Financement et interet ouvert compares. rows = [{ex, funding (par periode), intervalH, oiUsd, mark}] -> moyenne annualisee, ecart, part de chaque bourse."""
    out = [dict(r) for r in rows]
    for r in out:
        r["annualized"] = funding_annualized(r["funding"], r.get("intervalH") or 8.0) if r.get("funding") is not None else None
    ann = [r["annualized"] for r in out if r["annualized"] is not None]
    tot = sum(r["oiUsd"] for r in out if r.get("oiUsd"))
    for r in out:
        r["oiShare"] = (r["oiUsd"] / tot) if tot and r.get("oiUsd") else None
    flag = None
    if ann:
        m = sum(ann) / len(ann)
        flag = "longs" if m > 0.25 and min(ann) > 0.10 else "shorts" if m < -0.10 and max(ann) < -0.02 else None
    return {"rows": out, "meanAnnualized": (sum(ann) / len(ann)) if ann else None, "spread": (max(ann) - min(ann)) if len(ann) > 1 else None, "oiUsd": tot or None, "crowded": flag}


# =====================================================================================================
#  Reseau
# =====================================================================================================
class DerivMixin:
    """Methodes ajoutees aux fournisseurs (RealProviders) ; _get(url) = http_json ; adresses de base : self.deribit, self.bybit, self.okx, self.hyper."""

    def deribit_summary(self, currency: str, kind: str) -> list:
        d = self._get(f"{self.deribit}/api/v2/public/get_book_summary_by_currency?currency={currency}&kind={kind}")
        res = d.get("result") if isinstance(d, dict) else None
        if not isinstance(res, list) or not res:
            raise DataError(f"Deribit {kind} {currency} : réponse inattendue")
        return res

    def deribit_options(self, currency: str, now_ms: int) -> dict:
        return options_view(self.deribit_summary(currency, "option"), now_ms)

    def deribit_futures(self, currency: str, now_ms: int) -> list:
        return futures_basis(self.deribit_summary(currency, "future"), now_ms)

    def deribit_dvol(self, currency: str, now_ms: int) -> dict:
        d = self._get(f"{self.deribit}/api/v2/public/get_volatility_index_data?currency={currency}&start_timestamp={now_ms - 14 * DAY}&end_timestamp={now_ms}&resolution=3600")
        data = ((d or {}).get("result") or {}).get("data") if isinstance(d, dict) else None
        if not isinstance(data, list):
            raise DataError("Deribit DVOL : réponse inattendue")
        return dvol_view(data)

    def perp_bybit(self, coin: str) -> dict:
        d = self._get(f"{self.bybit}/v5/market/tickers?category=linear&symbol={coin}USDT")
        rows = (((d or {}).get("result") or {}).get("list")) if isinstance(d, dict) else None
        if not rows:
            raise DataError("Bybit : paire absente")
        r = rows[0]
        mark = num(r.get("markPrice"))
        oi_val = num(r.get("openInterestValue"))
        if oi_val is None and num(r.get("openInterest")) and mark:
            oi_val = num(r["openInterest"]) * mark
        return {"ex": "Bybit", "funding": num(r.get("fundingRate")), "intervalH": num(r.get("fundingIntervalHour")) or 8.0, "oiUsd": oi_val, "mark": mark}

    def perp_okx(self, coin: str) -> dict:
        inst = f"{coin}-USDT-SWAP"
        f = self._get(f"{self.okx}/api/v5/public/funding-rate?instId={inst}")
        o = self._get(f"{self.okx}/api/v5/public/open-interest?instType=SWAP&instId={inst}")
        m = self._get(f"{self.okx}/api/v5/public/mark-price?instType=SWAP&instId={inst}")
        fr = ((f or {}).get("data") or [None])[0]
        oi = ((o or {}).get("data") or [None])[0]
        mk = ((m or {}).get("data") or [None])[0]
        if not fr:
            raise DataError("OKX : paire absente")
        mark = num((mk or {}).get("markPx"))
        oi_usd = num((oi or {}).get("oiUsd")) or ((num((oi or {}).get("oiCcy")) or 0.0) * mark if mark and (oi or {}).get("oiCcy") else None)
        t0, t1 = num(fr.get("fundingTime")), num(fr.get("nextFundingTime"))
        interval = (t1 - t0) / HOUR if t0 and t1 and t1 > t0 else 8.0
        return {"ex": "OKX", "funding": num(fr.get("fundingRate")), "intervalH": interval, "oiUsd": oi_usd, "mark": mark}

    def perp_hyperliquid(self, coin: str) -> dict:
        d = post_json(f"{self.hyper}/info", {"type": "metaAndAssetCtxs"})
        if not (isinstance(d, list) and len(d) == 2 and isinstance(d[0], dict) and isinstance(d[1], list)):
            raise DataError("Hyperliquid : réponse inattendue")
        names = [u.get("name") for u in d[0].get("universe", [])]
        if coin not in names:
            raise DataError(f"Hyperliquid : {coin} absent")
        c = d[1][names.index(coin)]
        mark = num(c.get("markPx"))
        oi = num(c.get("openInterest"))
        return {"ex": "Hyperliquid", "funding": num(c.get("funding")), "intervalH": 1.0, "oiUsd": oi * mark if (oi is not None and mark) else None, "mark": mark}

    def perp_others(self, symbol: str) -> list[dict]:
        """Bybit, OKX, Hyperliquid pour la paire ; une bourse en panne n'empeche pas les autres. Leve DataError si aucune ne repond."""
        coin, got, bad = coin_of(symbol), [], []
        for fn in (self.perp_bybit, self.perp_okx, self.perp_hyperliquid):
            try:
                got.append(fn(coin))
            except (DataError, KeyError, TypeError, ValueError, IndexError) as e:
                bad.append(f"{fn.__name__[5:]}: {str(e)[:60]}")
        if not got:
            raise DataError("; ".join(bad) or "aucune bourse")
        return got


# =====================================================================================================
#  Donnees fictives (mode simule) : meme forme
# =====================================================================================================
class SimDerivMixin:
    def _sim(self, seed: int, lo: float, hi: float) -> float:
        import random
        return random.Random(seed + int(self.now_ms() // 600_000)).uniform(lo, hi)

    def deribit_options(self, currency: str, now_ms: int) -> dict:
        spot = 85000.0 if currency == "BTC" else 3200.0
        step = 1000.0 if currency == "BTC" else 50.0
        summ = []
        for k, days in enumerate((3, 10, 24, 52)):
            exp = datetime.fromtimestamp((now_ms + days * DAY) / 1000, timezone.utc)
            tag = f"{exp.day}{list(MONTHS)[exp.month - 1]}{exp.year % 100}"
            for j in range(-8, 9):
                strike = round(spot / step) * step + j * step * (k + 1)
                for kind, w in (("C", 1.0 if j >= 0 else 0.4), ("P", 1.0 if j <= 0 else 0.4)):
                    summ.append({"instrument_name": f"{currency}-{tag}-{int(strike)}-{kind}", "open_interest": w * (300 - 25 * abs(j)) * (1 + 0.1 * k), "underlying_price": spot})
        return options_view(summ, now_ms)

    def deribit_futures(self, currency: str, now_ms: int) -> list:
        spot = 85000.0
        out = [{"instrument_name": f"{currency}-PERPETUAL", "mark_price": spot * 1.0002, "estimated_delivery_price": spot, "funding_8h": 0.00012, "open_interest": 1.2e9}]
        for days in (30, 90):
            exp = datetime.fromtimestamp((now_ms + days * DAY) / 1000, timezone.utc)
            out.append({"instrument_name": f"{currency}-{exp.day}{list(MONTHS)[exp.month - 1]}{exp.year % 100}", "mark_price": spot * (1 + 0.0035 * days / 30), "estimated_delivery_price": spot, "open_interest": 4e8})
        return futures_basis(out, now_ms)

    def deribit_dvol(self, currency: str, now_ms: int) -> dict:
        rows = [[now_ms - (240 - i) * HOUR, 0, 0, 0, 52 + 6 * math.sin(i / 20.0)] for i in range(241)]
        return dvol_view(rows)

    def perp_others(self, symbol: str) -> list[dict]:
        base = 0.00008 + self._sim(sum(map(ord, symbol)), -0.00003, 0.00004)
        return [{"ex": "Bybit", "funding": base * 1.1, "intervalH": 8.0, "oiUsd": 6.1e8, "mark": 190.0},
                {"ex": "OKX", "funding": base * 0.9, "intervalH": 8.0, "oiUsd": 4.0e8, "mark": 190.0},
                {"ex": "Hyperliquid", "funding": base / 8.0 * 1.3, "intervalH": 1.0, "oiUsd": 2.2e8, "mark": 190.0}]
