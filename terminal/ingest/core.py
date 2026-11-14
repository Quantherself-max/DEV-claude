"""Client HTTP commun de l'ingestion (V45) : limite de débit, reprises, cache, nombres exacts, santé de la source.

- RateLimiter : seau de jetons par serveur. `acquire(poids)` attend qu'il y ait assez de jetons ; `penalize(secondes)` interdit tout
  appel jusqu'à une heure donnée (réponse 429 / 418, ou compteur de poids de Binance presque plein).
- TTLCache : dernière réponse de chaque adresse, avec son âge.
- HttpClient.get(chemin, paramètres, ttl=, weight=) :
    1. réponse en cache plus jeune que `ttl` : rendue sans appel ;
    2. attente du limiteur ;
    3. appel ; 200 : JSON lu avec les nombres en Decimal (aucun flottant binaire) ;
    4. 429 (trop d'appels) : attente « Retry-After » si le serveur la donne, sinon exponentielle ; 418 (adresse bannie par Binance) :
       plus aucun appel pendant la durée annoncée, sans reprise ;
       403 / 451 (accès refusé, souvent par pays) : erreur immédiate, sans reprise (insister ne sert à rien) ;
       5xx, délai dépassé, coupure : reprise après min(max, base × 2^essai) × (0,5 à 1, au hasard) : l'aléa évite que toutes les
       reprises partent au même instant ;
    5. tout échoue : IngestError (kind = 'blocked', 'rate', 'http', 'network', 'format'). Avec `stale_ok`, la dernière réponse connue
       est rendue à la place, et `meta(...)['stale']` le dit : jamais en silence.
- L'en-tête X-MBX-USED-WEIGHT-1M de Binance est lu à chaque réponse : au-delà de 80 % de la limite, le client se met en pause
  jusqu'à la minute suivante.
Le transport (`transport(url, headers, timeout) -> (statut, en-têtes, corps)`) se remplace dans les tests : aucun réseau n'y est utilisé."""
from __future__ import annotations
import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from decimal import Decimal

from data.base import DataError


class IngestError(DataError):
    """Erreur d'ingestion. kind : blocked (refus par pays ou par règle), rate (trop d'appels), http, network, format."""

    def __init__(self, msg: str, kind: str = "http", status: int | None = None, retry_after: float | None = None):
        super().__init__(msg)
        self.kind, self.status, self.retry_after = kind, status, retry_after


def urllib_transport(url: str, headers: dict, timeout: float):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers.items()), r.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        finally:
            e.close()
        return e.code, dict(e.headers.items()) if e.headers else {}, body


class RateLimiter:
    """Seau de jetons : `rate` jetons par seconde, `burst` au plus en réserve."""

    def __init__(self, rate: float, burst: float, now=time.monotonic, sleep=time.sleep):
        self.rate, self.burst = float(rate), float(burst)
        self.now, self.sleep = now, sleep
        self.tokens = float(burst)
        self.t = now()
        self.not_before = 0.0
        self.lock = threading.Lock()
        self.waited = 0.0

    def _refill(self):
        t = self.now()
        self.tokens = min(self.burst, self.tokens + (t - self.t) * self.rate)
        self.t = t

    def acquire(self, weight: float = 1.0) -> float:
        """Attend le temps qu'il faut ; renvoie le temps attendu (secondes)."""
        weight = min(float(weight), self.burst)
        total = 0.0
        while True:
            with self.lock:
                self._refill()
                wait = max(0.0, self.not_before - self.now())
                if wait <= 0:
                    if self.tokens >= weight:
                        self.tokens -= weight
                        self.waited += total
                        return total
                    wait = (weight - self.tokens) / self.rate
            self.sleep(wait)
            total += wait

    def penalize(self, seconds: float) -> None:
        with self.lock:
            self.not_before = max(self.not_before, self.now() + max(0.0, seconds))

    def paused_for(self) -> float:
        return max(0.0, self.not_before - self.now())


class TTLCache:
    def __init__(self, max_items: int = 256, now=time.time):
        self.max, self.now = max_items, now
        self.d: dict = {}
        self.lock = threading.Lock()

    def get(self, key):
        """(valeur, âge en secondes) ou (None, None)."""
        with self.lock:
            e = self.d.get(key)
            return (e[0], self.now() - e[1]) if e else (None, None)

    def put(self, key, value) -> None:
        with self.lock:
            self.d[key] = (value, self.now())
            if len(self.d) > self.max:
                for k in sorted(self.d, key=lambda k: self.d[k][1])[:len(self.d) - self.max]:
                    del self.d[k]


def backoff_delay(attempt: int, base: float, cap: float, rnd=random.random) -> float:
    """Attente avant la reprise numéro `attempt` (0 pour la première) : min(cap, base × 2^attempt) × (0,5 à 1)."""
    return min(cap, base * (2 ** attempt)) * (0.5 + 0.5 * rnd())


class HttpClient:
    def __init__(self, name: str, base: str, rate: float = 5.0, burst: float = 10.0, timeout: float = 15.0, retries: int = 4,
                 backoff: float = 0.5, backoff_max: float = 20.0, weight_limit: int | None = None, weight_header: str | None = None,
                 transport=urllib_transport, sleep=time.sleep, now=time.time, rnd=random.random, user_agent: str = "liq-terminal/45"):
        self.name, self.base = name, base.rstrip("/")
        self.timeout, self.retries, self.backoff, self.backoff_max = timeout, retries, backoff, backoff_max
        self.weight_limit, self.weight_header = weight_limit, (weight_header or "").lower()
        self.weight_guard = 0.8               # part du quota au-dela de laquelle ce client se met en pause jusqu'a la minute suivante
        self.transport, self.sleep, self.now, self.rnd = transport, sleep, now, rnd
        self.limiter = RateLimiter(rate, burst, sleep=sleep)
        self.cache = TTLCache(now=now)
        self.headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self.lock = threading.Lock()
        self.calls = self.errors = self.retried = self.cache_hits = self.stale_served = 0
        self.last_ok = self.last_err_t = 0.0
        self.last_error = ""
        self.used_weight = None
        self.lat = deque(maxlen=50)
        self._meta: dict = {}

    def url(self, path: str, params: dict | None = None) -> str:
        q = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        return self.base + path + ("?" + q if q else "")

    def meta(self, path: str, params: dict | None = None) -> dict:
        """Origine de la dernière réponse rendue pour cette adresse : {'t': heure, 'cached': bool, 'stale': bool}."""
        return self._meta.get(self.url(path, params), {})

    def _note_headers(self, headers: dict) -> None:
        if not self.weight_header:
            return
        for k, v in headers.items():
            if k.lower() == self.weight_header:
                try:
                    self.used_weight = int(v)
                except (TypeError, ValueError):
                    return
                if self.weight_limit and self.used_weight >= self.weight_guard * self.weight_limit:
                    self.limiter.penalize(60.0 - self.now() % 60.0 + 0.5)        # jusqu'à la minute suivante (le compteur y repart de zéro)

    def get(self, path: str, params: dict | None = None, ttl: float = 0.0, weight: float = 1.0, stale_ok: bool = False,
            timeout: float | None = None, retries: int | None = None):
        url = self.url(path, params)
        if ttl > 0:
            val, age = self.cache.get(url)
            if val is not None and age <= ttl:
                self.cache_hits += 1
                self._meta[url] = {"t": self.now() - age, "cached": True, "stale": False}
                return val
        err = None
        tries = self.retries if retries is None else retries
        for attempt in range(max(1, tries)):
            self.limiter.acquire(weight)
            t0 = self.now()
            self.calls += 1
            try:
                status, headers, body = self.transport(url, self.headers, timeout or self.timeout)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                err = IngestError(f"{self.name} injoignable ({type(e).__name__}: {str(e)[:80]})", "network")
            else:
                self._note_headers(headers)
                if status == 200:
                    try:
                        data = json.loads(body.decode("utf-8"), parse_float=Decimal)
                    except (ValueError, UnicodeDecodeError) as e:
                        err = IngestError(f"{self.name} : réponse illisible ({str(e)[:60]})", "format", 200)
                    else:
                        self.lat.append((self.now() - t0) * 1000.0)
                        self.last_ok, self.last_error = self.now(), ""
                        self.cache.put(url, data)
                        self._meta[url] = {"t": self.now(), "cached": False, "stale": False}
                        return data
                else:
                    text = body.decode("utf-8", "replace")[:160].replace("\n", " ") if body else ""
                    ra = _retry_after(headers)
                    if status in (403, 451):
                        err = IngestError(f"{self.name} : accès refusé (HTTP {status}), sans doute depuis ce pays ou ce réseau. {text}", "blocked", status)
                        break
                    if status == 418:
                        self.limiter.penalize(ra or 120.0)
                        err = IngestError(f"{self.name} : adresse bannie temporairement (HTTP 418), pause de {int(ra or 120)} s", "rate", status, ra)
                        break
                    if status == 429:
                        wait = ra if ra is not None else backoff_delay(attempt, 1.0, 60.0, self.rnd)
                        self.limiter.penalize(wait)
                        err = IngestError(f"{self.name} : trop d'appels (HTTP 429)", "rate", status, wait)
                    elif status >= 500:
                        err = IngestError(f"{self.name} : erreur du serveur (HTTP {status}) {text}", "http", status)
                    else:
                        err = IngestError(f"{self.name} : HTTP {status} {text}", "http", status)
                        break                                                    # 400, 404... : la requête est fausse, inutile d'insister
            if attempt < tries - 1:
                self.retried += 1
                if err.kind != "rate":
                    self.sleep(backoff_delay(attempt, self.backoff, self.backoff_max, self.rnd))
        self.errors += 1
        self.last_error, self.last_err_t = str(err), self.now()
        if stale_ok:
            val, age = self.cache.get(url)
            if val is not None:
                self.stale_served += 1
                self._meta[url] = {"t": self.now() - age, "cached": True, "stale": True, "error": str(err)}
                return val
        raise err

    def status(self) -> dict:
        lat = sorted(self.lat)
        return {"name": self.name, "calls": self.calls, "errors": self.errors, "retried": self.retried, "cacheHits": self.cache_hits,
                "stale": self.stale_served, "lastOk": self.last_ok or None, "error": self.last_error or None,
                "latencyMs": lat[len(lat) // 2] if lat else None, "usedWeight": self.used_weight, "weightLimit": self.weight_limit,
                "pausedFor": round(self.limiter.paused_for(), 1)}


def _retry_after(headers: dict):
    for k, v in headers.items():
        if k.lower() == "retry-after":
            try:
                return max(0.0, float(v))
            except (TypeError, ValueError):
                return None
    return None


def need(d, *keys):
    """Champ obligatoire d'une réponse : d[k1][k2]... ; IngestError('format') s'il manque (jamais de valeur par défaut inventée)."""
    cur = d
    for k in keys:
        try:
            cur = cur[k]
        except (KeyError, IndexError, TypeError):
            raise IngestError(f"réponse inattendue : champ {'.'.join(map(str, keys))} absent", "format") from None
    return cur
