"""Jeux de donnees LIBRES, gratuits et sans cle, publies sur GitHub (V9) : de quoi mesurer des indicateurs sur 10 a 17 ans.

  - Coin Metrics « community » (github.com/coinmetrics/data, CC BY-NC 4.0) : BTC en chaine depuis 2009, au jour le jour (flux vers / depuis les bourses, offre
    sur les bourses, MVRV, hashrate, adresses actives, frais, volume) et offre de stablecoins (USDT, USDC, DAI) ;
  - github.com/datasets : VIX (quotidien depuis 1990), petrole WTI et Brent (depuis 1986 / 1987), gaz naturel, taux de change quotidiens (dont on reconstruit
    un indice dollar), toutes ces series etant mises a jour par leurs depots.

Telechargement dans data_local/opendata/ (ecriture atomique, repli sur la copie locale si internet manque). Module sans dependance, series en (jour UTC en ms, valeur)."""
import csv
import io
import math
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAW = "https://raw.githubusercontent.com"
DAY = 86_400_000

FILES = {
    "btc": "coinmetrics/data/master/csv/btc.csv",
    "usdt": "coinmetrics/data/master/csv/usdt.csv",
    "usdc": "coinmetrics/data/master/csv/usdc.csv",
    "dai": "coinmetrics/data/master/csv/dai.csv",
    "vix": "datasets/finance-vix/main/data/vix-daily.csv",
    "wti": "datasets/oil-prices/main/data/wti-daily.csv",
    "brent": "datasets/oil-prices/main/data/brent-daily.csv",
    "natgas": "datasets/natural-gas/main/data/daily.csv",
    "fx": "datasets/exchange-rates/main/data/daily.csv",
    # or tokenise (1 PAXG = 1 once d'or, cote 24 h / 24) : prix quotidien de l'or depuis 2020, week-ends compris
    "paxg": "coinmetrics/data/master/csv/paxg.csv",
    "xaut": "coinmetrics/data/master/csv/xaut.csv",
    # capitalisations estimees (CapMrktEstUSD, comparables entre actifs depuis juin 2019) : de quoi suivre ou va l'argent
    "eth": "coinmetrics/data/master/csv/eth.csv",
    **{a: f"coinmetrics/data/master/csv/{a}.csv" for a in ("bnb", "xrp", "ada", "doge", "trx", "link", "ltc", "bch", "xlm", "atom", "sol")},
}
ALT_BASKET = ("bnb", "xrp", "ada", "doge", "trx", "link", "ltc", "bch", "xlm", "atom")      # alts presentes depuis juin 2019 (panier constant, sans ETH ni SOL)
# exposants de l'indice dollar (DXY) : EUR 0,576, JPY 0,136, GBP 0,119, CAD 0,091, SEK 0,042, CHF 0,036 ; les cours du jeu de donnees sont en monnaie locale pour 1 USD,
# donc tous les exposants sont positifs (EURUSD^-0,576 = (EUR pour 1 USD)^0,576)
DXY_WEIGHTS = {"Euro": 0.576, "Japan": 0.136, "United Kingdom": 0.119, "Canada": 0.091, "Sweden": 0.042, "Switzerland": 0.036}
DXY_CONST = 50.14348112


def day_ms(date_str: str) -> int | None:
    """« 2024-03-01 » (ou « 2024-03 ») -> minuit UTC en ms ; None si illisible."""
    try:
        parts = [int(x) for x in date_str.strip()[:10].split("-")]
        while len(parts) < 3:
            parts.append(1)
        return int(datetime(parts[0], parts[1], parts[2], tzinfo=timezone.utc).timestamp() * 1000)
    except (ValueError, IndexError):
        return None


def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def read_csv(path_or_text) -> list[dict]:
    if isinstance(path_or_text, (str, Path)) and "\n" not in str(path_or_text) and Path(str(path_or_text)).exists():
        text = Path(str(path_or_text)).read_text(encoding="utf-8", errors="replace")
    else:
        text = str(path_or_text)
    return list(csv.DictReader(io.StringIO(text)))


def column(rows: list[dict], date_col: str, val_col: str) -> list[tuple[int, float]]:
    """Serie (jour UTC en ms, valeur) triee, sans doublon de jour (la derniere valeur l'emporte), valeurs vides ignorees."""
    out = {}
    for r in rows:
        t, v = day_ms(r.get(date_col, "")), num(r.get(val_col))
        if t is not None and v is not None:
            out[t] = v
    return sorted(out.items())


def dxy_series(fx_rows: list[dict]) -> list[tuple[int, float]]:
    """Indice dollar reconstruit depuis les taux de change quotidiens (formule officielle du DXY) ; seuls les jours ou les six monnaies sont cotees."""
    by_day: dict[int, dict] = {}
    for r in fx_rows:
        c = r.get("Country")
        if c not in DXY_WEIGHTS:
            continue
        t, v = day_ms(r.get("Date", "")), num(r.get("Exchange rate"))
        if t is not None and v and v > 0:
            by_day.setdefault(t, {})[c] = v
    out = []
    for t in sorted(by_day):
        d = by_day[t]
        if len(d) == len(DXY_WEIGHTS):
            out.append((t, DXY_CONST * math.prod(d[c] ** w for c, w in DXY_WEIGHTS.items())))
    return out


def ffill(series: list[tuple[int, float]], start: int, end: int) -> dict[int, float]:
    """Serie quotidienne continue de start a end (jours sans valeur : derniere valeur connue)."""
    d = dict(series)
    out, last = {}, None
    for t in range(start, end + 1, DAY):
        if t in d:
            last = d[t]
        if last is not None:
            out[t] = last
    return out


class OpenData:
    """Telecharge (si la copie a plus de `ttl_hours`) puis lit les jeux libres."""

    def __init__(self, folder, base: str = RAW, ttl_hours: float = 12.0, files: dict | None = None):
        self.dir = Path(folder)
        self.base = base.rstrip("/")
        self.ttl = ttl_hours * 3600.0
        self.files = dict(files or FILES)
        self._cache: dict[str, list[dict]] = {}

    def path(self, name: str) -> Path:
        return self.dir / f"{name}.csv"

    def age_hours(self, name: str) -> float | None:
        p = self.path(name)
        return (time.time() - p.stat().st_mtime) / 3600.0 if p.exists() else None

    def refresh(self, names=None, force: bool = False, timeout: float = 60.0) -> dict:
        """{nom: 'ok' | 'a jour' | 'copie locale (erreur)' | 'indisponible'} ; ne leve jamais."""
        self.dir.mkdir(parents=True, exist_ok=True)
        res = {}
        for name in (names or list(self.files)):
            p = self.path(name)
            if p.exists() and not force and time.time() - p.stat().st_mtime < self.ttl:
                res[name] = "à jour"
                continue
            try:
                req = urllib.request.Request(f"{self.base}/{self.files[name]}", headers={"User-Agent": "liq-terminal/9.0"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = r.read()
                if len(data) < 50 or b"\n" not in data:
                    raise ValueError("fichier vide")
                tmp = p.with_suffix(".tmp")
                tmp.write_bytes(data)
                os.replace(tmp, p)
                self._cache.pop(name, None)
                res[name] = "ok"
            except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, OSError) as e:
                res[name] = "copie locale (erreur : " + type(e).__name__ + ")" if p.exists() else "indisponible (" + type(e).__name__ + ")"
        return res

    def rows(self, name: str) -> list[dict]:
        if name not in self._cache:
            p = self.path(name)
            self._cache[name] = read_csv(p) if p.exists() else []
        return self._cache[name]

    def available(self) -> list[str]:
        return [n for n in self.files if self.path(n).exists()]

    # ---------- series nommees ----------
    def cm(self, name: str, col: str) -> list[tuple[int, float]]:
        return column(self.rows(name), "time", col)

    def macro(self, name: str) -> list[tuple[int, float]]:
        rows = self.rows(name)
        if name == "vix":
            return column(rows, "DATE", "CLOSE")
        if name in ("wti", "brent", "natgas"):
            return column(rows, "Date", "Price")
        if name == "fx":
            return dxy_series(rows)
        raise KeyError(name)

    def stablecoin_supply(self) -> list[tuple[int, float]]:
        """Offre totale USDT + USDC + DAI (en dollars), jour par jour ; chaque stablecoin compte a partir de sa premiere valeur."""
        parts = [dict(self.cm(n, "SplyCur")) for n in ("usdt", "usdc", "dai") if self.rows(n)]
        if not parts:
            return []
        days = sorted(set().union(*[set(p) for p in parts]))
        out, last = [], [None] * len(parts)
        for t in days:
            for i, p in enumerate(parts):
                if t in p:
                    last[i] = p[t]
            out.append((t, sum(v for v in last if v is not None)))
        return out
