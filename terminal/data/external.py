"""Donnees externes (V3), toutes gratuites et sans cle : calendrier economique (consensus), actifs de reference
(dollar, taux US, indices, or, VIX via Yahoo), dominance du Bitcoin (CoinGecko, repli CoinPaprika), indice
Fear & Greed, et paires alt/BTC de Binance spot (historique reel de la force des altcoins face au BTC).
Chaque element peut tomber en panne sans arreter les autres : l'erreur est gardee et affichee."""
import hashlib
import json
import math
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .base import DataError

FF_URL = "https://nfs.faireconomy.media"
YAHOO = "https://query1.finance.yahoo.com"
COINGECKO = "https://api.coingecko.com"
PAPRIKA = "https://api.coinpaprika.com"
ALTERNATIVE = "https://api.alternative.me"
SPOT = "https://api.binance.com"

# nom affiche -> symbole Yahoo (futures / indices : ils cotent presque 24 h, utile autour des annonces)
CROSS = {"DXY": "DX-Y.NYB", "US10Y": "^TNX", "SPX": "ES=F", "NDX": "NQ=F", "VIX": "^VIX", "GOLD": "GC=F"}
ALT_PAIRS = ("ETHBTC", "SOLBTC", "BNBBTC", "XRPBTC", "ADABTC", "DOGEBTC", "AVAXBTC", "LINKBTC")
IMPACT = {"high": 3, "medium": 2, "low": 1}


def http_json(url: str, timeout: float = 15.0, retries: int = 2, headers: dict | None = None):
    last = None
    h = {"User-Agent": "Mozilla/5.0 (liq-terminal/3.0)", "Accept": "application/json", **(headers or {})}
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:120]
            e.close()
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                last = f"HTTP {e.code}"
                continue
            raise DataError(f"HTTP {e.code} ({url.split('?')[0]}) {body}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
            last = f"{type(e).__name__}: {e}"
            if attempt < retries - 1:
                time.sleep(0.8 * (attempt + 1))
    raise DataError(f"injoignable : {url.split('?')[0]} ({last})")


def parse_num(s):
    """'0.3%' -> (0.3, '%') ; '227K' -> (227.0, 'K') ; '<0.1%' -> (0.1, '%') ; '' -> (None, '')."""
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*([%KMBT])?", "" if s is None else str(s))
    return (float(m.group(1)), m.group(2) or "") if m else (None, "")


def normalize_event(raw: dict):
    """Evenement du flux ForexFactory -> dict commun (heure en ms UTC, impact 0-3, valeurs numeriques)."""
    try:
        t = int(datetime.fromisoformat(raw["date"]).timestamp() * 1000)
    except (KeyError, ValueError):
        return None
    title, cur = str(raw.get("title", "")).strip(), str(raw.get("country", "")).strip().upper()
    imp = IMPACT.get(str(raw.get("impact", "")).lower(), 0)
    fnum, unit = parse_num(raw.get("forecast"))
    pnum, unit2 = parse_num(raw.get("previous"))
    return {"id": hashlib.sha1(f"{cur}|{title}|{t}".encode()).hexdigest()[:12], "t": t, "country": cur, "title": title,
            "impact": imp, "forecast": str(raw.get("forecast") or ""), "previous": str(raw.get("previous") or ""),
            "fnum": fnum, "pnum": pnum, "unit": unit or unit2}


class RealProviders:
    def __init__(self, ff=FF_URL, yahoo=YAHOO, coingecko=COINGECKO, paprika=PAPRIKA, alt=ALTERNATIVE, spot=SPOT):
        self.ff, self.yahoo, self.cg, self.pp, self.alt, self.spot = (u.rstrip("/") for u in (ff, yahoo, coingecko, paprika, alt, spot))

    def calendar(self):
        out, err = [], None
        for name in ("thisweek", "nextweek"):
            try:
                rows = http_json(f"{self.ff}/ff_calendar_{name}.json", retries=2)
            except DataError as e:
                if name == "thisweek":
                    raise
                err = e                                    # la semaine prochaine n'est pas toujours publiee
                continue
            out += [e for e in (normalize_event(r) for r in rows) if e]
        return out

    def yahoo_chart(self, symbol, interval, rng):
        from urllib.parse import quote
        d = http_json(f"{self.yahoo}/v8/finance/chart/{quote(symbol)}?interval={interval}&range={rng}&includePrePost=true")
        res = d["chart"]["result"][0]
        ts, cl = res.get("timestamp") or [], res["indicators"]["quote"][0]["close"]
        return [(int(t) * 1000, float(c)) for t, c in zip(ts, cl) if c is not None]

    def coingecko_global(self):
        try:
            d = http_json(f"{self.cg}/api/v3/global")["data"]
            return {"btc_d": float(d["market_cap_percentage"]["btc"]), "eth_d": float(d["market_cap_percentage"].get("eth", 0.0)),
                    "total": float(d["total_market_cap"]["usd"]), "chg24": float(d.get("market_cap_change_percentage_24h_usd", 0.0)),
                    "src": "CoinGecko"}
        except (DataError, KeyError, TypeError, ValueError):
            d = http_json(f"{self.pp}/v1/global")
            return {"btc_d": float(d["bitcoin_dominance_percentage"]), "eth_d": None, "total": float(d["market_cap_usd"]),
                    "chg24": float(d.get("market_cap_change_24h", 0.0)), "src": "CoinPaprika"}

    def fear_greed(self, limit=30):
        d = http_json(f"{self.alt}/fng/?limit={limit}&format=json")["data"]
        return sorted([(int(r["timestamp"]) * 1000, int(r["value"]), r.get("value_classification", "")) for r in d])

    def spot_klines(self, pair, limit=720, interval="1h"):
        rows = http_json(f"{self.spot}/api/v3/klines?symbol={pair}&interval={interval}&limit={limit}", timeout=25)
        return [(int(r[0]), float(r[4])) for r in rows]


class ExternalHub:
    """Rafraichit les sources a leur propre rythme (appele regulierement) et garde un instantane lisible."""
    DUE = {"calendar": 1800, "cross5": 300, "crossD": 3600, "fng": 3600, "cg": 600, "alt": 900, "altD": 21600}

    def __init__(self, providers, now_ms=lambda: int(time.time() * 1000), data_dir: str | None = None):
        self.p, self.now_ms = providers, now_ms
        self.dir = Path(data_dir) if data_dir else None
        self.lock = threading.Lock()
        self.calendar: dict[str, dict] = {}                 # archive des evenements (id -> evenement)
        self.cross5: dict[str, list] = {}
        self.crossD: dict[str, list] = {}
        self.fng: list = []
        self.cg: dict | None = None
        self.cg_hist: list = []                             # [(t_ms, btc_d, total)] : historique construit par le terminal
        self.alt: dict[str, list] = {}
        self.altD: dict[str, list] = {}                     # cloture quotidienne (2,7 ans) des paires alt/BTC + BTCUSDT
        self.errors: dict[str, str] = {}
        self.updated: dict[str, float] = {}
        self._due: dict[str, float] = {}
        self._load()

    # --- persistance (calendrier + dominance) ---
    def _load(self):
        if not self.dir:
            return
        try:
            self.calendar = json.loads((self.dir / "macro_events.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        try:
            self.cg_hist = [tuple(r) for r in json.loads((self.dir / "dominance_hist.json").read_text(encoding="utf-8"))]
        except (OSError, ValueError):
            pass

    def save(self):
        if not self.dir:
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            cut = self.now_ms() - 120 * 86_400_000
            cal = {k: v for k, v in self.calendar.items() if v["t"] >= cut}
            (self.dir / "macro_events.json").write_text(json.dumps(cal), encoding="utf-8")
            (self.dir / "dominance_hist.json").write_text(json.dumps(self.cg_hist[-4000:]), encoding="utf-8")
        except OSError:
            pass

    # --- rafraichissement ---
    def _run(self, name, fn, force):
        wall = time.time()
        if not force and wall < self._due.get(name, 0):
            return
        try:
            fn()
            self.errors.pop(name, None)
            self.updated[name] = wall
            self._due[name] = wall + self.DUE[name]
        except Exception as e:                                  # reseau, format inattendu... : on reessaie plus tard
            self.errors[name] = f"{type(e).__name__}: {str(e)[:160]}"
            self._due[name] = wall + min(300, self.DUE[name])

    def refresh(self, force: bool = False):
        self._run("calendar", self._calendar, force)
        self._run("cg", self._cg, force)
        self._run("fng", self._fng, force)
        self._run("cross5", lambda: self._cross("5m", "5d", self.cross5), force)
        self._run("crossD", lambda: self._cross("1d", "6mo", self.crossD), force)
        self._run("alt", self._alt, force)
        self._run("altD", self._altD, force)
        self.save()

    def _calendar(self):
        evs = self.p.calendar()
        with self.lock:
            for e in evs:
                old = self.calendar.get(e["id"], {})
                self.calendar[e["id"]] = {**old, **e}           # on garde la reaction mesuree deja enregistree

    def _cg(self):
        g = self.p.coingecko_global()
        t = self.now_ms()
        with self.lock:
            self.cg = {**g, "t": t}
            if not self.cg_hist or t - self.cg_hist[-1][0] >= 300_000:
                self.cg_hist.append((t, g["btc_d"], g["total"]))

    def _fng(self):
        v = self.p.fear_greed(30)
        with self.lock:
            self.fng = v

    def _cross(self, interval, rng, target):
        got, bad = {}, []
        for name, sym in CROSS.items():
            if len(bad) >= 2 and not got:
                break                                           # hors ligne : inutile d'insister sur chaque serie
            try:
                got[name] = self.p.yahoo_chart(sym, interval, rng)
            except Exception as e:
                bad.append(f"{name}: {str(e)[:60]}")
        if not got:
            raise DataError("; ".join(bad) or "aucune serie")
        with self.lock:
            target.update(got)
        if bad:
            raise DataError("partiel : " + "; ".join(bad))

    def _alt(self):
        got, bad = {}, []
        for pair in ALT_PAIRS:
            if len(bad) >= 2 and not got:
                break
            try:
                got[pair] = self.p.spot_klines(pair)
            except Exception as e:
                bad.append(f"{pair}: {str(e)[:50]}")
        if len(got) < 3:
            raise DataError("trop peu de paires alt/BTC : " + "; ".join(bad))
        with self.lock:
            self.alt = got
        if bad:
            raise DataError("partiel : " + "; ".join(bad))

    def _altD(self):
        got, bad = {}, []
        for pair in ALT_PAIRS + ("BTCUSDT",):
            if len(bad) >= 2 and not got:
                break
            try:
                got[pair] = self.p.spot_klines(pair, 1000, "1d")
            except Exception as e:
                bad.append(f"{pair}: {str(e)[:50]}")
        if len(got) < 4 or "BTCUSDT" not in got:
            raise DataError("historique quotidien alt/BTC incomplet : " + "; ".join(bad))
        with self.lock:
            self.altD = got
        if bad:
            raise DataError("partiel : " + "; ".join(bad))

    def snapshot(self) -> dict:
        with self.lock:
            return {"calendar": dict(self.calendar), "cross5": dict(self.cross5), "crossD": dict(self.crossD),
                    "fng": list(self.fng), "cg": self.cg, "cg_hist": list(self.cg_hist), "alt": dict(self.alt),
                    "altD": dict(self.altD),
                    "errors": dict(self.errors), "updated": dict(self.updated)}


class SimProviders:
    """Donnees externes fictives mais plausibles (mode simule) : l'interface complete fonctionne hors ligne."""

    def __init__(self, now_ms=lambda: int(time.time() * 1000)):
        self.now_ms = now_ms

    def _walk(self, seed, n, step_ms, end, base, vol):
        import random
        r = random.Random(seed)
        out, px = [], base
        end -= end % step_ms                                  # bougies alignees sur le pas (comme chez Binance)
        t0 = end - n * step_ms
        for i in range(n):
            px *= 1 + r.gauss(0, vol)
            out.append((t0 + i * step_ms, px))
        return out

    def calendar(self):
        now = self.now_ms()
        H = 3_600_000
        spec = [(-30 * H, "CPI m/m", "USD", 3, "0.3%", "0.2%"), (-52 * H, "Unemployment Claims", "USD", 2, "230K", "227K"),
                (-76 * H, "ISM Services PMI", "USD", 2, "52.1", "51.5"), (3 * H, "Core PCE Price Index m/m", "USD", 3, "0.3%", "0.2%"),
                (20 * H, "FOMC Meeting Minutes", "USD", 3, "", ""), (30 * H, "Unemployment Claims", "USD", 2, "225K", "230K"),
                (50 * H, "Non-Farm Employment Change", "USD", 3, "175K", "142K"), (50 * H, "Unemployment Rate", "USD", 3, "4.2%", "4.1%"),
                (74 * H, "Retail Sales m/m", "USD", 2, "0.4%", "0.1%"), (98 * H, "ECB Press Conference", "EUR", 3, "", "")]
        return [normalize_event({"title": t, "country": c, "date": datetime.fromtimestamp((now + dt) / 1000, timezone.utc).isoformat(),
                                 "impact": {3: "High", 2: "Medium", 1: "Low"}[i], "forecast": f, "previous": p})
                for dt, t, c, i, f, p in spec]

    def yahoo_chart(self, symbol, interval, rng):
        now = self.now_ms()
        seed = sum(map(ord, symbol))
        base = {"DX-Y.NYB": 104.0, "^TNX": 4.2, "ES=F": 5800.0, "NQ=F": 20500.0, "^VIX": 16.0, "GC=F": 2650.0}[symbol]
        step = 300_000 if interval == "5m" else 86_400_000
        n = 5 * 288 if interval == "5m" else 130
        vol = {"5m": 0.0006, "1d": 0.008}[interval] * (3 if symbol == "^VIX" else 1)
        return self._walk(seed, n, step, now, base, vol)

    def coingecko_global(self):
        return {"btc_d": 58.2 + 0.4 * math.sin(self.now_ms() / 3e8), "eth_d": 12.1, "total": 3.1e12, "chg24": 0.8, "src": "simule"}

    def fear_greed(self, limit=30):
        now = self.now_ms()
        return [(now - (limit - i) * 86_400_000, int(50 + 20 * math.sin(i / 4)), "Neutral") for i in range(limit)]

    def spot_klines(self, pair, limit=720, interval="1h"):
        step = 3_600_000 if interval == "1h" else 86_400_000
        base = 85000.0 if pair == "BTCUSDT" else 0.02
        return self._walk(sum(map(ord, pair)), limit, step, self.now_ms(), base, 0.003 if interval == "1h" else 0.02)
