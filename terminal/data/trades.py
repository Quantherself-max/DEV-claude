"""Transactions exactes (V23) : CHAQUE transaction des derniers jours, pour que les profils de volume, POC / VAH / VAL, noeuds, profil de
seance, TPO et zones soient calcules sur ce qui s'est reellement echange, au prix pres, au lieu d'etre deduits des bougies.

Trois sources, toutes publiques et sans cle, recollees sans trou par le NUMERO de transaction (aggTrade) :
  - archives quotidiennes aggTrades de Binance Vision (data.binance.vision), telechargees EN MEMOIRE, du jour le plus recent au plus ancien,
    converties en empreinte (engine/footprint.py) et gardees en petits fichiers par jour (quelques dizaines de Ko) : aucun gros fichier sur
    le disque ;
  - l'API publique Binance (/fapi/v1/aggTrades, a partir d'un numero de transaction, 1 requete par seconde au plus) entre la derniere archive
    et maintenant, et apres chaque coupure du flux en direct ;
  - le flux en direct du terminal (aggTrade) : chaque transaction prolonge l'empreinte, numeros consecutifs verifies.
Seules les periodes ou TOUTES les transactions sont presentes comptent comme exactes (couverture) ; ailleurs le terminal garde la repartition
des bougies, et l'affiche."""
from __future__ import annotations
import gzip
import io
import json
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from engine import footprint as fpm
from engine import sizeflow as sfm
from . import listing

VISION = "https://data.binance.vision/data/futures/um/daily/aggTrades"
VISION_SPOT = "https://data.binance.vision/data/spot/daily/aggTrades"      # V39 : marche spot (flux par taille d'ordre)
REST_PATH = {"perp": "/fapi/v1/aggTrades", "spot": "/api/v3/aggTrades"}
DAY = 86_400_000
REST_PAUSE = 1.0             # secondes entre deux pages de l'API (poids 20 : 1 200 sur 2 400 par minute au plus)
SAVE_EVERY = 300.0           # sauvegarde du jour en cours (secondes)
RETRY_404 = 3 * 3600.0       # archive pas encore publiee : nouvel essai 3 h plus tard
QUEUE_MAX = 3_000_000


def day_of(ms: int) -> int:
    return ms - ms % DAY


def ymd(day_ms: int) -> str:
    return datetime.fromtimestamp(day_ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def vision_url(symbol: str, day_ms: int, base: str = VISION) -> str:
    d = ymd(day_ms)
    return f"{base}/{symbol}/{symbol}-aggTrades-{d}.zip"


def http_bytes(url: str, timeout: float = 120.0) -> bytes | None:
    """Contenu d'une adresse ; None si elle n'existe pas (404). Autre erreur : exception."""
    req = urllib.request.Request(url, headers={"User-Agent": "liq-terminal/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def parse_day(raw: bytes, step: float | None = None, tick: float | None = None, flow=None):
    """Archive aggTrades d'un jour -> (empreinte fermee, premier numero, dernier numero, temps du dernier, nombre). Lecture en flux (memoire
    faible meme pour les jours les plus charges du BTC). Le pas de cotation est deduit de l'ecriture des prix si `tick` est None.
    V39 : `flow` (engine/sizeflow.SizeFlow) recoit aussi chaque transaction ; les archives spot donnent le temps en microsecondes depuis 2025."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    name = z.namelist()[0]
    fp = None
    fadd = flow.add_unlocked if flow is not None else None
    first = last = last_t = None
    n = 0
    with z.open(name) as fh:
        for ln in fh:
            a = ln.split(b",")
            if len(a) < 7 or not a[0][:1].isdigit():
                continue                                             # en-tete (archives recentes) ou ligne vide
            if fp is None:
                tk = tick or fpm.tick_of(a[1].decode("ascii"))
                fp = fpm.Footprint(step or fpm.storage_step(float(a[1]), tk), tk)
                add = fp.add_unlocked
            i = int(a[0])
            t = int(a[5])
            if t > 100_000_000_000_000:                              # microsecondes (archives spot depuis 2025)
                t //= 1000
            p, q, m = float(a[1]), float(a[2]), a[6][:1] in (b"t", b"T")
            add(p, q, m, t)
            if fadd is not None:
                fadd(p, q, m, t)
            if first is None:
                first = i
            last, last_t = i, t
            n += 1
    if fp is None:
        return None
    fp.seal(2 ** 62)
    if flow is not None:
        flow.flush()
    return fp, first, last, last_t, n


class TradeSync:
    """Empreinte exacte d'une paire, tenue a jour en tache de fond. `get(path, params)` : appel de l'API publique Binance (la source du
    terminal) ; `fetch(url)` : telechargement d'une archive (None si absente)."""

    def __init__(self, symbol: str, folder, days: int, get, fetch=http_bytes, now_ms=None, vision_base: str | None = None,
                 rest_pause: float = REST_PAUSE, market: str = "perp", flow_days: int | None = None):
        self.symbol = symbol.upper()
        self.market = market if market in REST_PATH else "perp"
        self.dir = Path(folder) / self.symbol
        self.days = max(1, int(days))
        self.get, self.fetch = get, fetch
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.vision_base = vision_base or (VISION_SPOT if self.market == "spot" else VISION)
        self.rest_path = REST_PATH[self.market]
        self.flow = sfm.SizeFlow()                                   # V39 : delta par taille d'ordre, nourri en meme temps que l'empreinte
        self.flow_days = self.days if flow_days is None else max(0, min(self.days, int(flow_days)))   # jours recents ou il doit exister
        self.rest_pause = rest_pause
        self.fp: fpm.Footprint | None = None
        self.q: deque = deque()                                      # transactions en direct pas encore integrees : (numero, prix, qte, vente, t)
        self.head_id = None                                          # toutes les transactions jusqu'a ce numero sont dans l'empreinte (queue)
        self.head_t = None
        self.tail_start = None                                       # debut de la couverture de la queue (fin de la derniere archive chargee)
        self.done: set[int] = set()                                  # jours complets (archive ou couverture totale)
        self.missing: dict[int, float] = {}                          # jour -> instant du prochain essai (archive absente)
        self.dirty: set[int] = set()                                 # jours modifies depuis la derniere sauvegarde
        self.day_last: dict[int, tuple] = {}                         # jour -> (dernier numero, son temps) integre par la queue
        self.catching_up = True                                      # la queue n'a pas encore rejoint le present
        self.rest_at = 0.0                                           # prochaine page de rattrapage (trou, retard)
        self.poll_at = 0.0                                           # prochaine page « au present » quand le flux en direct manque
        self.rest_errors = 0
        self.live_at = 0.0                                           # derniere transaction recue en direct (secondes)
        self.saved_at = 0.0
        self.mb = 0.0
        self.state = "démarrage"
        self.current = None                                          # jour en cours de telechargement
        self.error = None
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    # ---------- flux en direct (fil du WebSocket) ----------
    def on_live(self, x: dict) -> None:
        """Message aggTrade du flux en direct : mis en file, integre par le fil de synchronisation (numeros verifies)."""
        if len(self.q) < QUEUE_MAX:
            self.q.append((int(x["a"]), float(x["p"]), float(x["q"]), bool(x.get("m")), int(x["T"])))
        self.live_at = time.time()

    # ---------- vie ----------
    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self.run, name=f"trades-{self.symbol}", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            self.load()
        except Exception as e:                                       # fichiers illisibles : on repart de zero, sans bloquer le terminal
            self.error = f"lecture des fichiers : {type(e).__name__}: {e}"
        while not self._stop.is_set():
            busy = False
            try:
                busy = self.step()
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
                self._stop.wait(5.0)
            self._stop.wait(0.05 if busy else 0.5)

    def step(self) -> bool:
        """Un pas de travail. Priorites : 1) une archive plus recente que la queue (ou la premiere, qui l'ancre) ; 2) la queue (rattrapage
        par l'API puis flux en direct) jusqu'au present ; 3) les archives plus anciennes, une par pas. Renvoie True s'il reste du travail."""
        if self._newer_archive_possible():
            busy = self.history_step()
        else:
            busy = self.tail_step()
            if not self.catching_up or self.rest_errors > 0:          # a jour, ou API indisponible : les archives plus anciennes avancent
                busy = self.history_step() or busy
        self.housekeeping()
        return busy

    def _newer_archive_possible(self) -> bool:
        """Vrai s'il faut d'abord une archive : aucune queue, ou une archive plus recente que la queue peut exister."""
        if self.head_t is None:
            return True
        hd, now_s = day_of(self.head_t), time.time()
        for d in self.wanted_days():                                 # du plus recent au plus ancien
            if d <= hd:
                return False
            if d not in self.done and self.missing.get(d, 0) <= now_s:
                return True
        return False

    # ---------- queue : rattrapage par l'API et flux en direct ----------
    def tail_step(self) -> bool:
        if self.head_id is None:
            return False
        n = self._drain()
        gap = bool(self.q) and self.q[0][0] > self.head_id + 1
        quiet = time.time() - self.live_at > 15.0                    # pas de flux en direct : l'API tient l'empreinte a jour
        if gap:
            self.catching_up = True
        elif not quiet:
            self.catching_up = False                                 # le flux en direct est integre sans trou
        now_s = time.time()
        if (gap and now_s >= self.rest_at) or (not gap and not self.q and quiet and now_s >= max(self.rest_at, self.poll_at)):
            return self._rest_page() or n > 0
        return n > 0

    def _drain(self) -> int:
        n = 0
        fp = self.fp
        d0 = day_of(self.head_t) if self.head_t is not None else None
        while self.q and self.q[0][0] <= self.head_id + 1:
            a, p, qty, m, t = self.q.popleft()
            if a == self.head_id + 1:
                fp.add(p, qty, m, t)
                self.flow.add(p, qty, m, t)
                self.head_id, self.head_t = a, t
                self.day_last[t - t % DAY] = (a, t)
                n += 1
        if n:
            self._cover_tail(d0)
        return n

    def _cover_tail(self, d0=None):
        """Couverture de la queue jusqu'a la derniere transaction integree ; jours touches depuis `d0` marques a sauvegarder."""
        if self.tail_start is not None and self.head_t is not None and self.head_t > self.tail_start:
            self.fp.cover(self.tail_start, self.head_t)
            self.flow.cover(self.tail_start, self.head_t)
        if self.head_t is not None:
            d = day_of(self.head_t) if d0 is None else min(d0, day_of(self.head_t))
            while d <= self.head_t:
                self.dirty.add(d)
                d += DAY

    def _rest_page(self) -> bool:
        self.rest_at = time.time() + self.rest_pause
        d0 = day_of(self.head_t) if self.head_t is not None else None
        try:
            rows = self.get(self.rest_path, {"symbol": self.symbol, "fromId": self.head_id + 1, "limit": 1000})
        except Exception as e:
            self.rest_errors += 1
            self.error = f"API aggTrades : {e}"
            self.state = "API indisponible : archives seulement (nouvel essai)"
            self.rest_at = time.time() + min(300.0, 5.0 * 2 ** min(self.rest_errors, 6))
            return False
        self.error = None if self.error and self.error.startswith("API aggTrades") else self.error
        self.rest_errors = 0
        stop = self.q[0][0] if self.q else None
        n = 0
        for r in rows or []:
            a = int(r["a"])
            if a <= self.head_id:
                continue
            if a != self.head_id + 1 or (stop is not None and a >= stop):
                break
            t = int(r["T"])
            if t > 100_000_000_000_000:                              # microsecondes (API spot si demande)
                t //= 1000
            self.fp.add(float(r["p"]), float(r["q"]), bool(r["m"]), t)
            self.flow.add(float(r["p"]), float(r["q"]), bool(r["m"]), t)
            self.head_id, self.head_t = a, t
            self.day_last[t - t % DAY] = (a, t)
            n += 1
        if n:
            self._cover_tail(d0)
        full = len(rows or []) >= 1000
        self.catching_up = full or (bool(self.q) and self.q[0][0] > self.head_id + 1)
        self.state = "rattrapage" if self.catching_up else "à jour"
        if not full:
            self.poll_at = time.time() + 5.0                         # au present : une page toutes les 5 s si le flux en direct manque
        return full

    # ---------- archives quotidiennes ----------
    def wanted_days(self):
        today = day_of(self.now_ms())
        first = listing.first_ms(self.symbol, self.market)          # V42 : rien avant le premier jour de la paire (data/listing.py)
        return [d for d in (today - k * DAY for k in range(1, self.days + 1)) if d >= first]   # du plus recent au plus ancien, aujourd'hui exclu

    def history_step(self) -> bool:
        now_s = time.time()
        for d in self.wanted_days():
            if d in self.done:
                continue
            if self.fp is not None and self._day_ok(d):
                self.done.add(d)
                continue
            if self.missing.get(d, 0) > now_s:
                continue
            self.current = d
            self.state = f"archive du {ymd(d)}"
            try:
                raw = self.fetch(vision_url(self.symbol, d, self.vision_base))
            except Exception as e:
                self.error = f"archive du {ymd(d)} : {type(e).__name__}: {e}"
                self.missing[d] = now_s + 600.0
                self.current = None
                return False
            if raw is None:                                          # pas encore publiee (ou jour sans contrat)
                self.missing[d] = now_s + RETRY_404
                self.current = None
                continue
            self.mb += len(raw) / 1e6
            self._load_day(d, raw)
            self.current = None
            self.state = f"archive du {ymd(d)} chargée"
            return True
        self.state = "archives à jour" if self.head_id is not None else self.state
        if self.head_id is None:
            self._anchor_rest(self.wanted_days()[0])                 # aucune archive utilisable : la queue part d'hier minuit (API)
        return False

    def _day_ok(self, d: int) -> bool:
        """Jour complet : toutes ses transactions dans l'empreinte et, pour les `flow_days` jours les plus recents, dans le flux par taille
        (un jour enregistre avant la V39 n'a pas ce flux : son archive est relue une fois)."""
        if not self.fp.complete(d, d + DAY):
            return False
        return d < day_of(self.now_ms()) - self.flow_days * DAY or self.flow.complete(d, d + DAY)

    def _load_day(self, d: int, raw: bytes):
        dflow = sfm.SizeFlow()
        res = parse_day(raw, self.fp.step if self.fp else None, self.fp.tick if self.fp else None, dflow)
        if res is None:
            self.missing[d] = time.time() + RETRY_404
            return
        dfp, first, last, last_t, n = res
        if self.fp is None:
            self.fp = fpm.Footprint(dfp.step, dfp.tick)
            self._save_meta()
        fp = self.fp
        fp.clear(d, d + DAY)                                         # remplace ce qui existait (queue partielle) : jamais de double compte
        for t5, (i0, b, s) in dfp.closed.items():
            fp.put(t5, i0, b, s)
        fp.cover(d, d + DAY)
        self.flow.clear(d, d + DAY)
        vals = dflow.day_array(d)
        if vals is not None:
            self.flow.put_day(d, vals)
        self.flow.cover(d, d + DAY)
        self.done.add(d)
        self.missing.pop(d, None)
        self.dirty.discard(d)
        self._save_day(d, {"lastId": last, "lastT": last_t, "firstId": first, "trades": n, "source": "archive"})
        self.day_last[d] = (last, last_t)
        if self.head_t is None or self.head_t < d + DAY:             # la queue repart de la fin de cette archive
            self.head_id, self.head_t, self.tail_start = last, last_t, d + DAY
            self.catching_up = True
            for x in [x for x in self.day_last if x > d]:
                del self.day_last[x]
            while self.q and self.q[0][0] <= last:
                self.q.popleft()

    def _anchor_rest(self, day: int):
        """Pas d'archive utilisable : la queue commence a minuit UTC du jour `day` (premier numero de transaction donne par l'API)."""
        if self.head_id is not None or time.time() < self.rest_at:
            return
        self.rest_at = time.time() + self.rest_pause
        try:
            rows = self.get(self.rest_path, {"symbol": self.symbol, "startTime": day, "endTime": day + 3_599_999, "limit": 1})
        except Exception as e:
            self.error = f"API aggTrades : {e}"
            return
        if not rows:
            return
        r = rows[0]
        if self.fp is None:
            tk = fpm.tick_of(str(r["p"]))
            self.fp = fpm.Footprint(fpm.storage_step(float(r["p"]), tk), tk)
            self._save_meta()
        self.head_id, self.head_t, self.tail_start = int(r["a"]) - 1, day, day
        self.catching_up = True

    # ---------- disque ----------
    def _path(self, d: int) -> Path:
        return self.dir / f"{ymd(d)}.json.gz"

    def _save_meta(self):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / "meta.json").write_text(json.dumps({"step": self.fp.step, "tick": self.fp.tick, "symbol": self.symbol}), encoding="utf-8")
        except OSError as e:
            self.error = f"écriture : {e}"

    def _save_day(self, d: int, extra: dict):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self._path(d).with_suffix(".tmp")
            fl = self.flow.day_values(d)
            if fl is not None and self.flow.covered_ms(d, d + DAY) >= self.fp.covered_ms(d, d + DAY):
                extra = {**extra, "flow": fl}                        # V39 : flux par taille, couvert comme l'empreinte de ce jour
            tmp.write_bytes(gzip.compress(self.fp.day_blob(d, extra), compresslevel=5))
            tmp.replace(self._path(d))
        except OSError as e:
            self.error = f"écriture : {e}"

    def load(self):
        """Fichiers deja enregistres (jours de la fenetre), la queue reprend apres la derniere transaction sauvegardee."""
        try:
            meta = json.loads((self.dir / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.fp = fpm.Footprint(float(meta["step"]), float(meta["tick"]))
        keep = set(self.wanted_days()) | {day_of(self.now_ms())}
        best = None
        for f in sorted(self.dir.glob("*.json.gz")):
            try:
                d = int(datetime.strptime(f.name[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
            except ValueError:
                continue
            if d not in keep:
                try:
                    f.unlink()                                       # hors de la fenetre : supprime
                except OSError:
                    pass
                continue
            try:
                head = self.fp.load_blob(gzip.decompress(f.read_bytes()))
            except (OSError, ValueError, EOFError, KeyError):
                continue
            if isinstance(head.get("flow"), list):                   # V39 : flux par taille de ce jour, meme couverture que l'empreinte
                self.flow.put_day(d, head["flow"])
                for a, b in head.get("cov", []):
                    self.flow.cover(int(a), int(b))
            if self._day_ok(d):
                self.done.add(d)
            if head.get("lastId") is not None:
                self.day_last[d] = (int(head["lastId"]), int(head["lastT"]))
                if best is None or d > best[0]:
                    best = (d, int(head["lastId"]), int(head["lastT"]))
        if best:
            self.head_id, self.head_t = best[1], best[2]
            self.tail_start = best[2]
        self.state = "fichiers chargés"

    def housekeeping(self):
        if self.fp is None:
            return
        now = self.now_ms()
        self.fp.seal(now - now % fpm.BUCKET - fpm.BUCKET)             # tranches terminees depuis plus de 5 min : format compact
        if self.dirty and time.time() - self.saved_at >= SAVE_EVERY:
            self.flush()
        oldest = min(self.wanted_days())
        if self.fp.first_covered() is not None and self.fp.first_covered() < oldest - DAY:
            self.fp.drop_before(oldest)
            self.flow.drop_before(oldest)
            for d in [x for x in self.done if x < oldest]:
                self.done.discard(d)
            for d in [x for x in self.day_last if x < oldest]:
                del self.day_last[d]
            for f in self.dir.glob("*.json.gz"):                     # fichiers des jours sortis de la fenetre
                if f.name[:10] < ymd(oldest):
                    try:
                        f.unlink()
                    except OSError:
                        pass

    def flush(self):
        """Sauvegarde des jours modifies par la queue, du plus ancien au plus recent (chacun avec sa derniere transaction)."""
        if self.fp is None:
            return
        for d in sorted(self.dirty):                                 # du plus ancien au plus recent : le dernier ecrit porte la queue
            if self.head_t is not None and d > day_of(self.head_t):
                continue
            last = self.day_last.get(d)
            self._save_day(d, {"lastId": last[0], "lastT": last[1], "source": "direct"} if last else {"source": "direct"})
        self.dirty.clear()
        self.saved_at = time.time()

    # ---------- lecture ----------
    def status(self) -> dict:
        wanted = self.wanted_days()
        today = day_of(self.now_ms())
        now = self.now_ms()
        fp = self.fp
        cov_today = (fp.covered_ms(today, now) / max(1, now - today)) if fp else 0.0
        return {"symbol": self.symbol, "market": self.market, "days": self.days, "complete": sum(1 for d in wanted if d in self.done),
                "today": round(min(1.0, cov_today), 4), "state": self.state, "current": ymd(self.current) if self.current else None,
                "behindSec": round((now - self.head_t) / 1000) if self.head_t else None, "queue": len(self.q),
                "mb": round(self.mb, 1), "error": self.error, "step": fp.step if fp else None, "exactPrices": fp.exact if fp else None}
