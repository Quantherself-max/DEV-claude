"""Intérêt ouvert archivé (V29), pour la carte des liquidations sur plusieurs mois : archives publiques quotidiennes de Binance
(« metrics », data.binance.vision, une valeur toutes les 5 minutes depuis décembre 2021), gardées dans data_local/history/<PAIRE>/raw_metrics
(le même dossier que tools/fetch_history.py : ce qui y est déjà n'est pas retéléchargé). 11 Ko par jour, 2 Mo pour 180 jours.
SimOiArchive fabrique un intérêt ouvert plausible pour le mode « données simulées » (rien n'est écrit sur le disque)."""
import json
import math
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from engine import history

DAY = 86_400_000
M5 = 300_000


def _ymd(t_ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(t_ms / 1000))


class OiArchive:
    """points() -> {horodatage (ms) : intérêt ouvert en pièces} pour les `days` derniers jours ; fetch() télécharge les jours manquants."""

    def __init__(self, symbol: str, folder: str, days: int = 180, now=time.time, http_bytes=None, workers: int = 4):
        self.symbol, self.folder, self.days, self.now, self.workers = symbol.upper(), folder, max(1, int(days)), now, workers
        self.http_bytes = http_bytes
        self.lock = threading.Lock()
        self._pts: dict = {}
        self._parsed: set = set()
        self._tried_path = os.path.join(folder, "_essais.json")

    def _file(self, day: int) -> str:
        return os.path.join(self.folder, f"{self.symbol}-metrics-{_ymd(day)}.zip")

    def _wanted(self):
        today = int(self.now() * 1000) // DAY * DAY
        return [today - k * DAY for k in range(1, self.days + 1)]

    def days_count(self) -> int:
        return sum(1 for d in self._wanted() if os.path.exists(self._file(d)))

    def points(self) -> dict:
        """Lit les archives présentes (une seule fois chacune)."""
        with self.lock:
            for d in self._wanted():
                f = self._file(d)
                if f in self._parsed or not os.path.exists(f):
                    continue
                self._parsed.add(f)
                try:
                    for t, oi, _, _ in history.parse_metrics(history.read_zip_rows(f)):
                        self._pts[t] = oi
                except Exception:                                  # archive abîmée : supprimée, elle sera retéléchargée
                    try:
                        os.remove(f)
                    except OSError:
                        pass
                    self._parsed.discard(f)
            return dict(self._pts)

    def fetch(self, stop_ev=None) -> int:
        """Télécharge les jours manquants, du plus récent au plus ancien. Une archive absente (404) n'est redemandée qu'une fois par jour
        pendant 3 jours (publication du lendemain), puis une fois par semaine. Rend le nombre de jours ajoutés."""
        if self.http_bytes is None:
            from .trades import http_bytes
            self.http_bytes = http_bytes
        os.makedirs(self.folder, exist_ok=True)
        try:
            with open(self._tried_path, encoding="utf-8") as f:
                tried = json.load(f)
        except (OSError, ValueError):
            tried = {}
        now = int(self.now() * 1000)
        todo = []
        for d in self._wanted():
            if os.path.exists(self._file(d)):
                continue
            age = (now - d) // DAY
            if now - int(tried.get(_ymd(d), 0)) < (DAY if age <= 3 else 7 * DAY):
                continue
            todo.append(d)

        def one(day):
            if stop_ev is not None and stop_ev.is_set():
                return None
            y, m, dd = (int(x) for x in _ymd(day).split("-"))
            raw = self.http_bytes(history.vision_metrics_url(self.symbol, y, m, dd), timeout=60)
            if raw is None:
                return False
            tmp = self._file(day) + ".part"
            with open(tmp, "wb") as f:
                f.write(raw)
            os.replace(tmp, self._file(day))
            return True

        got, err = 0, None
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futs = [(d, ex.submit(one, d)) for d in todo]
            for d, fu in futs:
                try:
                    ok = fu.result()
                except Exception as e:                             # réseau : ce jour sera redemandé au prochain tour
                    err = e
                    continue
                if ok:
                    got += 1
                elif ok is False:
                    tried[_ymd(d)] = now
        try:
            with open(self._tried_path, "w", encoding="utf-8") as f:
                json.dump(tried, f)
        except OSError:
            pass
        if err is not None and not got:
            raise err
        return got


class SimOiArchive:
    """Mode simulé : un intérêt ouvert plausible (tendance, rafales de nouvelles positions, purges) avant les 30 jours fournis par la source
    simulée, raccordé à sa première valeur. first() -> (horodatage, valeur) de la première valeur de la source, ou None."""

    def __init__(self, symbol: str, first, days: int = 180, now=time.time):
        self.symbol, self.first, self.days, self.now = symbol, first, max(1, int(days)), now
        self._pts = None

    def days_count(self) -> int:
        return self.days if self._pts else 0

    def points(self) -> dict:
        if self._pts is None:
            f = self.first()
            if not f:
                return {}
            t_end, v_end = f
            t0 = (int(self.now() * 1000) - self.days * DAY) // M5 * M5
            rnd = random.Random(f"oi-{self.symbol}")
            oi, walk = 1.0, []
            for t in range(t0, t_end, M5):
                d = rnd.gauss(0.00002, 0.0004)
                if rnd.random() < 0.02:
                    d += rnd.uniform(0.002, 0.009)
                if rnd.random() < 0.012:
                    d -= 0.004 * oi
                oi = max(0.3, oi + d)
                walk.append((t, oi))
            k = v_end / walk[-1][1] if walk else 1.0
            self._pts = {t: v * k for t, v in walk}
        return self._pts

    def fetch(self, stop_ev=None) -> int:
        return 0


class DeepOi:
    """V33 : intérêt ouvert sur plusieurs années (depuis décembre 2021, début des archives « metrics » de Binance), une valeur par heure, pour
    les bougies d'intérêt ouvert sous le graphique en journalier et en 4 heures. Mêmes fichiers que OiArchive (dossier raw_metrics : rien n'est
    téléchargé deux fois) ; seule la dernière valeur de chaque heure est gardée en mémoire (40 000 valeurs pour 4 ans et demi au lieu de 500 000).
    Les heures déjà lues sont gardées dans oi_deep_1h.csv : au redémarrage, seules les nouvelles archives sont relues."""

    START = 1_638_316_800_000          # 2021-12-01

    def __init__(self, symbol: str, folder: str, now=time.time, http_bytes=None):
        days = max(1, int((now() * 1000 - self.START) // DAY))
        self.arch = OiArchive(symbol, folder, days, now=now, http_bytes=http_bytes)
        self.folder = folder
        self.cache = os.path.join(folder, "oi_deep_1h.csv")
        self.lock = threading.Lock()
        self._pts: dict = {}
        self._done: set = set()
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            with open(self.cache, encoding="utf-8") as f:
                head = f.readline().strip()
                self._done = set(head.split(",")[1:]) if head.startswith("#done") else set()
                for line in f:
                    a, _, b = line.partition(",")
                    try:
                        self._pts[int(a)] = float(b)
                    except ValueError:
                        continue
        except OSError:
            pass

    def refresh(self) -> int:
        """Lit les archives présentes pas encore lues (à appeler en tâche de fond, la lecture se fait hors du verrou) ; rend le nombre de jours ajoutés."""
        with self.lock:
            self._load()
            todo = [f for f in (self.arch._file(d) for d in self.arch._wanted())
                    if os.path.basename(f) not in self._done and os.path.exists(f)]
        last, names = {}, []
        for f in todo:
            try:
                rows = history.parse_metrics(history.read_zip_rows(f))
            except Exception:
                continue
            for t, oi, _, _ in rows:
                if oi:
                    last[(t + 3_599_999) // 3_600_000 * 3_600_000] = oi              # clé : fin de l'heure ; le dernier relevé de l'heure l'emporte
            names.append(os.path.basename(f))
        if not names:
            return 0
        with self.lock:
            self._pts.update(last)
            self._done.update(names)
            try:
                tmp = self.cache + ".part"
                with open(tmp, "w", encoding="utf-8") as fo:
                    fo.write("#done," + ",".join(sorted(self._done)) + "\n")
                    for t in sorted(self._pts):
                        fo.write(f"{t},{self._pts[t]}\n")
                os.replace(tmp, self.cache)
            except OSError:
                pass
        return len(names)

    def fetch(self, stop_ev=None) -> int:
        n = self.arch.fetch(stop_ev)
        self.refresh()
        return n

    def points(self) -> dict:
        with self.lock:
            self._load()
            return dict(self._pts)

    def days_count(self) -> int:
        return len(self._done)
