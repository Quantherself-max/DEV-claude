"""Historique d'un symbole en memoire : bougies 1h (depuis l'ancre / l'annee precedente), bougies 5 min +
Open Interest sur ~29 jours, et contexte derives (funding, base, ratio long/short, prix spot / Coinbase).
refresh() ne telecharge que ce qui manque ; le contexte est optionnel (ses erreurs n'arretent rien)."""
import gzip
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from engine.atr import Candle

H1 = 3_600_000
M5 = 300_000
DAY = 86_400_000
OI_DAYS = 29       # Binance ne donne l'OI 5 min que sur ~30 jours
EARLIEST = 1_567_296_000_000      # 2019-09-01 : debut des futures perpetuels Binance (BTC)
CACHE_VERSION = 1


def merge(lst: list, new: list) -> None:
    for k in new:
        if lst and k.t == lst[-1].t:
            lst[-1] = k                      # la bougie qui se formait est remplacee par sa version a jour
        elif not lst or k.t > lst[-1].t:
            lst.append(k)


class DataStore:
    def __init__(self, source, symbol: str, anchor_ms: int, history_years: int = 0, cache_dir: str | None = None):
        self.source, self.symbol = source, symbol
        now = source.now_ms()
        y = datetime.fromtimestamp(now / 1000, timezone.utc).year
        prev_year = int(datetime(y - 1, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        # le profil de l'annee precedente est necessaire ; au-dela, l'historique le plus long possible (ou N annees)
        wanted = EARLIEST if history_years <= 0 else now - int(history_years * 365.25 * DAY)
        self.history_start = min(anchor_ms, prev_year, wanted)
        self.cache = Path(cache_dir) / f"h1_{symbol}.json.gz" if cache_dir else None
        self._saved_at = 0.0
        self._saved_n = 0
        self.h1: list[Candle] = []
        self.m5: list[Candle] = []
        self.oi: dict[int, float] = {}                       # ouverture de la bougie 5 min -> OI a sa fin
        self.oi_t: list[int] = []                            # memes donnees, triees (recherche par date)
        self.oi_v: list[float] = []
        self.ctx = {"premium": None, "funding": [], "ls_global": [], "ls_top": [], "spot": None,
                    "coinbase": None, "errors": {}}
        self._ctx_due = {"funding": 0.0, "ls": 0.0, "px": 0.0}
        self.last_error = None
        self.last_refresh = 0

    # --- cache disque des bougies 1h fermees : le redemarrage ne retelecharge que ce qui manque ---
    def _load_cache(self) -> None:
        if not self.cache or self.h1:
            return
        try:
            with gzip.open(self.cache, "rt", encoding="utf-8") as f:
                d = json.load(f)
            if d.get("v") != CACHE_VERSION or d.get("symbol") != self.symbol or not d["rows"] \
                    or d.get("start", 0) > self.history_start + 2 * DAY:
                return                                       # autre version / paire, ou cache demande avec moins d'historique
            self.h1 = [Candle(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[6]) for r in d["rows"]]
            self._saved_n = len(self.h1)
        except (OSError, ValueError, KeyError, IndexError, EOFError):
            self.h1 = []

    def _save_cache(self) -> None:
        closed = self.closed_h1()
        if not self.cache or len(closed) < 100 or len(closed) == self._saved_n:
            return
        if self._saved_n and time.time() - self._saved_at < 1800:      # au plus une ecriture toutes les 30 min
            return
        try:
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache.with_suffix(".tmp")
            rows = [[k.t, k.o, k.h, k.l, k.c, k.v, k.tb] for k in closed]
            with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=3) as f:
                json.dump({"v": CACHE_VERSION, "symbol": self.symbol, "start": self.history_start, "rows": rows}, f)
            os.replace(tmp, self.cache)
            self._saved_n, self._saved_at = len(closed), time.time()
        except OSError:
            pass

    def refresh(self) -> None:
        now = self.source.now_ms()
        self._load_cache()
        s1 = self.h1[-1].t if self.h1 else self.history_start - self.history_start % H1
        merge(self.h1, self.source.candles(self.symbol, "1h", s1, now))
        s5 = self.m5[-1].t if self.m5 else now - OI_DAYS * DAY
        s5 -= s5 % M5
        merge(self.m5, self.source.candles(self.symbol, "5m", s5, now))
        so = (self.oi_t[-1] + M5 + M5) if self.oi_t else now - OI_DAYS * DAY
        for ts, v in self.source.open_interest(self.symbol, "5m", so, now):
            k = ts - M5
            if k not in self.oi:
                self.oi[k] = v
                if not self.oi_t or k > self.oi_t[-1]:
                    self.oi_t.append(k)
                    self.oi_v.append(v)
        self.last_refresh = now
        self.last_error = None
        self._save_cache()

    def refresh_context(self) -> None:
        """Donnees de contexte (V2). Chacune peut echouer sans bloquer le reste."""
        now = self.source.now_ms()
        errs = self.ctx["errors"]

        def safe(name, fn):
            try:
                v = fn()
                errs.pop(name, None)
                return v
            except Exception as e:                      # reseau, endpoint absent, format inattendu...
                errs[name] = f"{type(e).__name__}: {str(e)[:150]}"
                return None

        self.ctx["premium"] = safe("premium", lambda: self.source.premium_index(self.symbol)) or self.ctx["premium"]
        wall = time.time()
        if wall >= self._ctx_due["px"]:                         # prix spot / Coinbase : inutile de les demander a chaque cycle
            self.ctx["spot"] = safe("spot", lambda: self.source.spot_price(self.symbol))
            from data.binance import coinbase_product
            self.ctx["coinbase"] = safe("coinbase", lambda: self.source.coinbase_price(coinbase_product(self.symbol)))
            self._ctx_due["px"] = wall + 15
        if wall >= self._ctx_due["funding"]:
            f = safe("funding", lambda: self.source.funding_history(self.symbol, now - 7 * DAY, now))
            if f is not None:
                self.ctx["funding"] = f
                self._ctx_due["funding"] = wall + 3600
        if wall >= self._ctx_due["ls"]:
            g = safe("ls_global", lambda: self.source.long_short(self.symbol, "1h", now - 2 * DAY, now, "global"))
            tp = safe("ls_top", lambda: self.source.long_short(self.symbol, "1h", now - 2 * DAY, now, "top"))
            if g is not None:
                self.ctx["ls_global"] = g
            if tp is not None:
                self.ctx["ls_top"] = tp
            self._ctx_due["ls"] = wall + 900

    def forming_h1(self):
        k = self.h1[-1] if self.h1 else None
        return k if k and k.t + H1 > self.source.now_ms() else None

    def closed_h1(self):
        now = self.source.now_ms()
        return self.h1 if not self.h1 or self.h1[-1].t + H1 <= now else self.h1[:-1]
