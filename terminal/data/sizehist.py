"""Historique profond du flux par taille d'ordre (V40.1), a l'HEURE, pour que les grandes unites de temps (4 heures, jour, semaine, mois)
aient un cumul sur plusieurs mois.

Le flux par taille demande chaque transaction : il n'existe pas de resume public. Le terminal relit donc, en tache de fond et un jour a la
fois, les archives quotidiennes aggTrades de Binance Vision (perpetuel ou spot), les lit EN MEMOIRE, n'en garde que 24 heures x 10 valeurs
(achats et ventes de chaque taille, en dollars) et jette le reste : quelques Ko par jour sur le disque, mais tout le volume de l'archive a
telecharger (estimation : plusieurs dizaines de Mo par jour pour le BTC, beaucoup moins pour le SOL).
Les jours encore presents dans le flux a la minute (data/trades.py) sont additionnes par heure sans rien telecharger. Du plus recent au
plus ancien : le cumul s'allonge vers le passe au fil du chargement."""
from __future__ import annotations
import io
import json
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from engine import sizeflow as sfm
from .trades import DAY, VISION, VISION_SPOT, day_of, http_bytes, vision_url, ymd

HOUR = 3_600_000
PAUSE = 2.0                  # secondes entre deux archives (le reseau et le processeur restent disponibles pour le reste du terminal)
RETRY_404 = 6 * 3600.0
RETRY_ERR = 600.0


def parse_sizes(raw: bytes, flow: sfm.SizeFlow) -> int:
    """Archive aggTrades d'un jour -> flux par taille (le temps en microsecondes des archives spot depuis 2025 est converti). Renvoie le
    nombre de transactions lues."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    n = 0
    add = flow.add_unlocked
    with z.open(z.namelist()[0]) as fh:
        for ln in fh:
            a = ln.split(b",", 7)
            if len(a) < 7 or not a[0][:1].isdigit():
                continue
            t = int(a[5])
            if t > 100_000_000_000_000:
                t //= 1000
            add(float(a[1]), float(a[2]), a[6][:1] in (b"t", b"T"), t)
            n += 1
    flow.flush()
    return n


class SizeHistory:
    """Historique a l'heure d'une paire sur un marche. `minute` : le TradeSync du meme marche (ses jours complets sont additionnes au lieu
    d'etre telecharges) ; `days` : jours d'historique voulus (0 = rien)."""

    def __init__(self, symbol: str, market: str, folder, days: int, minute=None, fetch=http_bytes, now_ms=None, pause: float = PAUSE):
        self.symbol, self.market = symbol.upper(), market
        self.dir = Path(folder) / market / self.symbol
        self.days = max(0, int(days))
        self.minute = minute
        self.fetch = fetch
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.pause = pause
        self.base = VISION_SPOT if market == "spot" else VISION
        self.flow = sfm.SizeFlow(HOUR)
        self.done: set[int] = set()
        self.missing: dict[int, float] = {}
        self.mb = 0.0
        self.state, self.error, self.current = "démarrage", None, None
        self._stop = threading.Event()
        self._thread = None

    # ---------- vie ----------
    def start(self):
        if self._thread is None and self.days > 0:
            self._thread = threading.Thread(target=self.run, name=f"sizehist-{self.market}-{self.symbol}", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()

    def flush(self):
        """Rien a garder en memoire : chaque jour est ecrit des qu'il est fini."""

    def run(self):
        try:
            self.load()
        except Exception as e:
            self.error = f"lecture des fichiers : {type(e).__name__}: {e}"
        while not self._stop.is_set():
            busy = False
            try:
                busy = self.step()
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
                self._stop.wait(30.0)
            self._stop.wait(self.pause if busy else 60.0)

    # ---------- travail ----------
    def wanted_days(self) -> list[int]:
        today = day_of(self.now_ms())
        return [today - k * DAY for k in range(1, self.days + 1)]          # du plus recent au plus ancien

    def step(self) -> bool:
        """Un jour : additionne depuis la minute s'il y est complet, sinon telecharge son archive. True s'il en reste."""
        now_s = time.time()
        for d in self.wanted_days():
            if d in self.done or self.missing.get(d, 0) > now_s:
                continue
            mf = getattr(self.minute, "flow", None)
            if mf is not None and mf.complete(d, d + DAY):
                vals = sfm.hourly_of(mf, d)
                if vals is not None:
                    self._keep(d, vals, "minute")
                    return True
            recent = getattr(self.minute, "flow_days", 0) or 0
            if mf is not None and d >= day_of(self.now_ms()) - recent * DAY:
                continue                                             # jour recent : le flux a la minute le telecharge deja, on l'attend
            self.current = d
            self.state = f"historique : archive du {ymd(d)}"
            try:
                raw = self.fetch(vision_url(self.symbol, d, self.base))
            except Exception as e:
                self.error = f"archive du {ymd(d)} : {type(e).__name__}: {e}"
                self.missing[d] = now_s + RETRY_ERR
                self.current = None
                return False
            if raw is None:
                self.missing[d] = now_s + RETRY_404
                self.current = None
                continue
            self.mb += len(raw) / 1e6
            day = sfm.SizeFlow(HOUR)
            parse_sizes(raw, day)
            vals = day.day_values(d) or [0] * (24 * sfm.WIDTH)
            self._keep(d, vals, "archive")
            self.current = None
            return True
        self.state = "historique à jour"
        self.housekeeping()
        return False

    def _keep(self, d: int, vals, src: str):
        self.flow.put_day(d, vals)
        self.flow.cover(d, d + DAY)
        self.done.add(d)
        self.missing.pop(d, None)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.dir / f"{ymd(d)}.tmp"
            tmp.write_text(json.dumps({"v": 1, "day": d, "src": src, "h": [round(v) for v in vals]}, separators=(",", ":")), encoding="utf-8")
            tmp.replace(self.dir / f"{ymd(d)}.json")
        except OSError as e:
            self.error = f"écriture : {e}"

    def load(self):
        keep = set(self.wanted_days())
        for f in sorted(self.dir.glob("*.json")):
            try:
                d = int(datetime.strptime(f.name[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
            except ValueError:
                continue
            if d not in keep:
                continue                                                 # garde le fichier (la fenetre peut etre agrandie plus tard)
            try:
                blob = json.loads(f.read_text(encoding="utf-8"))
                if blob.get("v") != 1 or len(blob.get("h", [])) != 24 * sfm.WIDTH:
                    continue
            except (OSError, ValueError):
                continue
            self.flow.put_day(d, blob["h"])
            self.flow.cover(d, d + DAY)
            self.done.add(d)
        self.state = "fichiers chargés"

    def housekeeping(self):
        oldest = min(self.wanted_days()) if self.days else day_of(self.now_ms())
        self.flow.drop_before(oldest)
        self.done = {d for d in self.done if d >= oldest}

    def status(self) -> dict:
        return {"symbol": self.symbol, "market": self.market, "kind": "hist", "days": self.days, "complete": len(self.done), "state": self.state,
                "current": ymd(self.current) if self.current else None, "mb": round(self.mb, 1), "error": self.error}
