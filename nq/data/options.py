"""Données d'options pour le GEX, et intérêt ouvert (open interest) du future.

GEX : chaîne d'options DIFFÉRÉE (15 min) publiée gratuitement par le CBOE pour l'indice NDX ou l'ETF QQQ :
    https://cdn.cboe.com/api/global/delayed_quotes/options/_NDX.json   (ou QQQ.json)
Le terminal la télécharge lui-même (depuis ton PC), au plus toutes les `refresh_min` minutes, et garde la dernière copie dans `data_local`
pour redémarrer sans réseau. Tu peux aussi pointer `NQ_GEX_FILE` sur un fichier JSON du même format (téléchargé à la main).
Usage personnel : ce sont les cotations différées affichées sur le site du CBOE.

Intérêt ouvert du NQ : l'indicateur NinjaTrader (NQTickLogger) l'écrit dans un petit fichier `nq-oi.csv` (heure UTC en ms, valeur) à côté
du fichier des transactions. La bourse le publie une fois par jour : on montre la dernière valeur et sa variation sur la journée précédente."""
import csv
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from engine import clock

CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
SYMBOLS = {"NDX": "_NDX", "QQQ": "QQQ"}


class OptionsFeed:
    """Télécharge (ou relit) la chaîne d'options. `fetch_fn` remplaçable pour les tests."""
    def __init__(self, underlying: str, cache_dir, file_path: str = "", refresh_min: float = 15.0, fetch_fn=None):
        self.underlying = underlying.upper()
        self.cache = Path(cache_dir) / f"options-{self.underlying}.json"
        self.file_path = file_path
        self.refresh_s = max(1.0, refresh_min) * 60
        self.fetch_fn = fetch_fn or self._http
        self.last_try = 0.0
        self.error = None

    def _http(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (NQ Scalp Terminal, usage personnel)", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read()

    def due(self, now: float | None = None) -> bool:
        return (now or time.time()) - self.last_try >= self.refresh_s

    def load(self, force: bool = False):
        """(json, provenance) ou (None, None). Ordre : fichier choisi > téléchargement (si dû ou forcé) > copie locale."""
        if self.file_path:
            try:
                return json.loads(Path(self.file_path).read_text(encoding="utf-8")), "fichier " + Path(self.file_path).name
            except (OSError, ValueError) as e:
                self.error = f"fichier d'options illisible : {e}"
                return None, None
        if force or self.due():
            self.last_try = time.time()
            sym = SYMBOLS.get(self.underlying, self.underlying)
            try:
                raw = self.fetch_fn(CBOE_URL.format(sym=sym))
                js = json.loads(raw)
                try:
                    self.cache.parent.mkdir(parents=True, exist_ok=True)
                    tmp = self.cache.with_suffix(".tmp")
                    tmp.write_bytes(raw)
                    tmp.replace(self.cache)
                except OSError:
                    pass
                self.error = None
                return js, "CBOE (différé 15 min)"
            except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
                self.error = f"téléchargement des options impossible ({e}) : dernière copie utilisée si elle existe"
        if self.cache.exists():
            try:
                return json.loads(self.cache.read_text(encoding="utf-8")), "copie locale"
            except (OSError, ValueError):
                return None, None
        return None, None


def read_oi(path) -> list:
    """[(t ms, intérêt ouvert)] du fichier `nq-oi.csv` (en-tête time,oi), dans l'ordre. [] si absent ou illisible."""
    p = Path(path) if path else None
    if not p or not p.exists():
        return []
    out = []
    try:
        with p.open(encoding="utf-8", newline="") as f:
            for row in csv.reader(f):
                if len(row) < 2:
                    continue
                try:
                    t, v = int(float(row[0])), float(row[1])
                except ValueError:
                    continue                                   # en-tête ou ligne incomplète
                if v > 0:
                    out.append((t, v))
    except OSError:
        return []
    out.sort()
    return out


def oi_summary(rows: list) -> dict | None:
    """Dernière valeur, celle de la journée de trading précédente, variation. None sans données."""
    if not rows:
        return None
    t, v = rows[-1]
    day = clock.trading_day(t)
    prev = next((x for tt, x in reversed(rows) if clock.trading_day(tt) < day), None)
    by_day = {}
    for tt, x in rows:
        by_day[clock.trading_day(tt)] = x
    hist = sorted(by_day.items())[-10:]
    return {"t": t, "oi": v, "day": day, "prev": prev, "change": None if prev is None else v - prev,
            "history": [{"day": d, "oi": x} for d, x in hist]}
