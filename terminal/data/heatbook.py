"""Heatmap du carnet d'ordres (V28, mémoire longue V29) : où attendent les gros ordres, et depuis combien de temps.

Le terminal photographie les carnets à intervalle régulier et range chaque photo par tranche de prix (montant en dollars, achats et
ventes additionnés), sur ±4 % autour du prix :
  - Binance (perpétuel) : le carnet local déjà tenu à jour en direct pour l'écran (flux des différences), toutes les 10 secondes ;
  - OKX (perpétuel) : le carnet en direct de 400 niveaux toutes les 10 secondes, et un carnet profond de 5 000 niveaux toutes les
    3 minutes (adresse publique « books-full ») pour les prix plus éloignés ;
  - Bybit (perpétuel) : 500 niveaux toutes les 30 secondes (adresse publique) ;
  - Coinbase (comptant BTC-USD) : le carnet complet toutes les 10 minutes (adresse publique, 1 Mo environ).
Sur une même bourse, la photo en direct passe devant la photo profonde là où elle couvre le prix. Les photos des 24 dernières heures
sont gardées en détail et sauvegardées sur le disque (data_local/heatmap/<PAIRE>.pkl). Volume réseau estimé : 350 Mo par jour
(désactivable : TERMINAL_HEATMAP=0 dans .env).

V29 : MÉMOIRE LONGUE, pour que tout le graphique (même en 4 heures) ait sa heatmap. Une colonne par quart d'heure et par source, en
tranches de 0,1 % du prix, gardée 180 jours (TERMINAL_HEATMAP_DAYS), un fichier par jour (data_local/heatmap/<PAIRE>/) :
  - tes propres photos, résumées (moyenne, minute par minute, de ce que chaque bourse montrait) : aussi fines que le carnet ;
  - là où tu n'as pas de photos (avant ton premier lancement, PC éteint) : les archives publiques de Binance (« bookDepth »,
    data.binance.vision, depuis janvier 2023), qui donnent toutes les 30 secondes le montant en attente à 0,2 %, 1 %, 2 %, 3 %, 4 %
    et 5 % du prix, perpétuel Binance seulement. Chaque tranche est répartie à parts égales sur sa largeur : on voit de quel côté
    et à quelle distance le carnet est épais, pas les murs précis. 0,5 Mo par jour d'archive (90 Mo pour 180 jours, une seule fois).
SimHeat fabrique des carnets avec des murs persistants pour le mode « données simulées », sim_depth_rows des archives plausibles."""
from __future__ import annotations
import array
import base64
import bisect
import calendar
import math
import os
import pickle
import random
import threading
import time

from . import listing

RANGE = 0.04
KEEP_MS = 24 * 3_600_000
CTVAL = {"BTC": 0.01, "ETH": 0.1, "SOL": 1.0, "PUMP": 1000.0}             # pièces par contrat OKX
EXCHANGES = ("binance", "okx", "bybit", "coinbase")
EX_NAMES = {"binance": "Binance", "okx": "OKX", "bybit": "Bybit", "coinbase": "Coinbase"}
# série -> (bourse, priorité, âge maximal d'une photo pour qu'elle compte encore)
SERIES = {"binance": ("binance", 0, 45_000), "okx": ("okx", 0, 45_000), "okxDeep": ("okx", 1, 420_000),
          "bybit": ("bybit", 0, 100_000), "coinbase": ("coinbase", 0, 1_300_000)}
EVERY = {"binance": 10.0, "okx": 10.0, "okxDeep": 180.0, "bybit": 30.0, "coinbase": 600.0}
EX_SERIES = {ex: sorted((n for n, (e, _, _) in SERIES.items() if e == ex), key=lambda n: SERIES[n][1]) for ex in EXCHANGES}

# mémoire longue (V29)
DAY_MS = 86_400_000
LT_MS = 900_000                                  # une colonne par quart d'heure
LT_BAND = math.log(1.001)                        # tranches de 0,1 % du prix (échelle logarithmique : la même grille à toutes les époques)
LT_RANGE = 0.05                                  # ±5 % autour du prix : la portée des archives Binance
LT_DAYS = 180
LT_SOURCES = EXCHANGES + ("archive",)            # « archive » : profondeur Binance par tranches de 1 % (archives publiques)
LT_VERSION = 1
DEPTH_URL = "https://data.binance.vision/data/futures/um/daily/bookDepth/{s}/{s}-bookDepth-{d}.zip"


def lt_band(price: float) -> int:
    return math.floor(math.log(price) / LT_BAND)


def lt_price(b: float) -> float:
    return math.exp(b * LT_BAND)


def ymd(t_ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(t_ms / 1000))


def _at_or_after(s, t) -> int:
    """Indice du premier élément (t, ...) d'une liste triée dont le temps est >= t."""
    lo, hi = 0, len(s)                                                 # recherche par moitiés (bisect avec key= demande Python 3.10)
    while lo < hi:
        mid = (lo + hi) // 2
        if s[mid][0] < t:
            lo = mid + 1
        else:
            hi = mid
    return lo


def nice(raw: float) -> float:
    if not raw > 0:
        return 1.0
    e = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if m * e >= raw * 0.999:
            return float(f"{m * e:.6g}")
    return 10 * e


STEP = {"BTC": 20.0, "ETH": 1.0, "SOL": 0.05}               # tranches fixes : l'historique sauvegardé reste lisible


def bucket_step(price: float) -> float:
    """Tranche de prix de stockage : environ 0,025 % du prix (20 $ pour le BTC à 80 000 $, 0,05 $ pour SOL à 190 $)."""
    return nice(price * 0.00025)


def to_buckets(bids, asks, step: float, mid: float, rng: float = RANGE):
    """[(prix, quantité en pièces)] -> (k0, array('f')) : dollars par tranche [k·step, (k+1)·step), achats et ventes additionnés."""
    lo, hi = mid * (1 - rng), mid * (1 + rng)
    acc: dict = {}
    for side in (bids, asks):
        for p, q in side:
            if q > 0 and lo <= p <= hi:
                k = int(math.floor(p / step + 1e-9))
                acc[k] = acc.get(k, 0.0) + p * q
    if not acc:
        return None
    k0, k1 = min(acc), max(acc)
    arr = array.array("f", bytes(4 * (k1 - k0 + 1)))
    for k, v in acc.items():
        arr[k - k0] = v
    return k0, arr


def _mid(bids, asks):
    bb = max((p for p, _ in bids), default=None)
    ba = min((p for p, _ in asks), default=None)
    if bb and ba:
        return (bb + ba) / 2
    return bb or ba


class HeatBook:
    """Photos rangées par tranche de prix, par série ; query() rend une image temps x prix prête à dessiner. long : mémoire longue (V29),
    qui prend le relais là où il n'y a pas de photo détaillée."""

    def __init__(self, symbol: str, step: float | None = None, keep_ms: int = KEEP_MS):
        self.symbol, self.keep = symbol, keep_ms
        self.step = step or STEP.get(symbol.upper()[:-4] if symbol.upper().endswith("USDT") else symbol.upper())   # sinon : au premier prix
        self.lock = threading.Lock()
        self.series = {name: [] for name in SERIES}          # [(t_ms, k0, array('f'))] par ordre chronologique
        self.long: HeatLong | None = None

    def add(self, name: str, t_ms: int, bids, asks, mid: float | None = None) -> bool:
        mid = mid or _mid(bids, asks)
        if not mid or name not in self.series:
            return False
        if self.step is None:
            self.step = bucket_step(mid)
        b = to_buckets(bids, asks, self.step, mid)
        if b is None:
            return False
        with self.lock:
            s = self.series[name]
            if s and s[-1][0] >= t_ms:                         # photo plus ancienne que la dernière (reprise d'historique) : rangée à sa place
                i = bisect.bisect_left([x[0] for x in s], t_ms)
                if i < len(s) and s[i][0] == t_ms:
                    return False
                s.insert(i, (int(t_ms), b[0], b[1]))
                return True
            s.append((int(t_ms), b[0], b[1]))
            if len(s) > 64 and s[0][0] < t_ms - self.keep - 600_000:      # coupe par paquets : pas de copie à chaque photo
                cut = next((i for i, x in enumerate(s) if x[0] >= t_ms - self.keep), len(s))
                del s[:cut]
        return True

    def since(self):
        with self.lock:
            ts = [s[0][0] for s in self.series.values() if s]
        return min(ts) if ts else None

    def last(self, name):
        with self.lock:
            s = self.series.get(name) or []
            return s[-1][0] if s else None

    @staticmethod
    def _exchange_at(snaps, ex, ptr, tc, k_lo, k_hi) -> dict:
        """{tranche: dollars} d'une bourse à l'instant tc : la dernière photo de chaque série (au plus vieille de son âge maximal), la photo
        en direct passant devant la photo profonde là où elle couvre le prix. ptr : position de lecture par série (tc croissant)."""
        out, covered = {}, None
        for n in EX_SERIES[ex]:
            s = snaps.get(n) or []
            p = ptr[n]
            while p + 1 < len(s) and s[p + 1][0] <= tc:
                p += 1
            ptr[n] = p
            if p < 0 or tc - s[p][0] > SERIES[n][2]:
                continue
            _, k0, arr = s[p]
            k1 = k0 + len(arr) - 1
            for k in range(max(k0, k_lo), min(k1, k_hi) + 1):
                v = arr[k - k0]
                if v > 0 and not (covered and covered[0] <= k <= covered[1]):
                    out[k] = out.get(k, 0.0) + v
            covered = (k0, k1) if covered is None else (min(covered[0], k0), max(covered[1], k1))
        return out

    def long_column(self, w: int, ex: str):
        """Résumé d'un quart d'heure [w, w + 15 min) pour la mémoire longue : moyenne, minute par minute, de ce que la bourse montrait
        (mêmes règles que l'image), rangée en tranches de 0,1 % du prix. None si la bourse a montré moins de 3 minutes."""
        if self.step is None:
            return None
        with self.lock:
            snaps = {}
            for n in EX_SERIES[ex]:
                s = self.series[n]
                i = max(0, _at_or_after(s, w - SERIES[n][2]) - 1)
                snaps[n] = s[i:_at_or_after(s, w + LT_MS + 1)]
        ptr = {n: -1 for n in snaps}
        acc, got, step = {}, 0, self.step
        for mi in range(15):
            vals = self._exchange_at(snaps, ex, ptr, w + (mi + 1) * 60_000, -2 ** 62, 2 ** 62)
            if vals:
                got += 1
                for k, v in vals.items():
                    b = lt_band((k + 0.5) * step)
                    acc[b] = acc.get(b, 0.0) + v
        if got < 3 or not acc:
            return None
        b0, b1 = min(acc), max(acc)
        arr = array.array("f", bytes(4 * (b1 - b0 + 1)))
        for b, v in acc.items():
            arr[b - b0] = v / got
        return b0, arr

    def query(self, t0: int, t1: int, lo: float, hi: float, cols: int = 300, rows: int = 250, exchanges=EXCHANGES) -> dict:
        """Image temps x prix : chaque colonne montre la dernière photo de chaque bourse (au plus vieille de son âge maximal), chaque
        ligne le montant en dollars de sa tranche de prix. Là où une bourse n'a pas de photo, la mémoire longue prend le relais
        (moyenne des quarts d'heure de la colonne ; pour Binance, les archives publiques quand il n'y a pas de photo à soi).
        Valeurs codées sur 0-255 (échelle en racine, 255 = 99e centile)."""
        cols = max(10, min(600, int(cols)))
        rows = max(10, min(400, int(rows)))
        exchanges = tuple(exchanges)
        lng = self.long
        if not (t1 > t0 and hi > lo > 0) or (self.step is None and not (lng and lng.count())):
            return {"ready": False}
        step = self.step or bucket_step((lo + hi) / 2)
        rowsz = step * max(1, math.ceil((hi - lo) / rows / step))
        r0 = math.floor(lo / rowsz)
        m = max(1, math.ceil(hi / rowsz) - r0)
        dt = (t1 - t0) / cols
        mat = [0.0] * (cols * m)
        k_lo, k_hi = math.floor(lo / step), math.floor(hi / step)
        with self.lock:
            snaps = {k: list(v) for k, v in self.series.items()}
        spans, used = {}, set()
        if lng is not None:
            for src in exchanges + (("archive",) if "binance" in exchanges else ()):
                spans[src] = lng.span(src, int(t0 - dt - LT_MS), int(t1) + 1)
        b_lo, b_hi = lt_band(lo) - 1, lt_band(hi) + 1
        alloc: dict = {}

        def rows_of(b):                                   # lignes couvertes par une tranche de 0,1 % (part de la tranche dans chacune)
            r = alloc.get(b)
            if r is None:
                y1, y2 = lt_price(b) / rowsz - r0, lt_price(b + 1) / rowsz - r0
                r = []
                for j in range(math.floor(y1), math.floor(y2) + 1):
                    ov = min(j + 1, y2) - max(j, y1)
                    if ov > 0 and 0 <= j < m:
                        r.append((j, ov / (y2 - y1)))
                alloc[b] = r
            return r

        for ex in exchanges:
            ptr = {n: -1 for n in EX_SERIES[ex]}
            for ci in range(cols):
                tc = t0 + (ci + 1) * dt
                vals = self._exchange_at(snaps, ex, ptr, tc, k_lo, k_hi)
                if vals:
                    for k, v in vals.items():
                        j = int(math.floor(k * step / rowsz + 1e-9)) - r0
                        if 0 <= j < m:
                            mat[j * cols + ci] += v
                    continue
                got, src = (), None
                for cand in ((ex, "archive") if ex == "binance" else (ex,)):
                    lst = spans.get(cand)
                    if lst:
                        i, k = _at_or_after(lst, tc - dt - LT_MS + 1), _at_or_after(lst, tc)
                        if k > i:
                            got, src = lst[i:k], cand
                            break
                if not got:
                    continue
                used.add(src)
                if len(got) > 4:                                  # colonne large (graphique 4 heures) : 4 quarts d'heure répartis suffisent
                    got = got[::math.ceil(len(got) / 4)]
                inv = 1.0 / len(got)
                for _, b0, arr in got:
                    for i in range(max(0, b_lo - b0), min(len(arr), b_hi - b0 + 1)):
                        v = arr[i]
                        if v > 0:
                            for j, f in rows_of(b0 + i):
                                mat[j * cols + ci] += v * f * inv
        nz = sorted(v for v in mat if v > 0)
        base = {"ready": True, "t0": t0, "t1": t1, "cols": cols, "rows": m, "lo": r0 * rowsz, "rowsz": rowsz, "longUsed": sorted(used)}
        if not nz:
            return {**base, "empty": True, "ref": 0.0, "data": ""}
        ref = nz[min(len(nz) - 1, int(len(nz) * 0.99))] or nz[-1]
        buf = bytearray(cols * m)
        for i, v in enumerate(mat):
            if v > 0:
                buf[i] = max(1, min(255, int(255 * math.sqrt(min(1.0, v / ref)))))
        return {**base, "empty": False, "ref": ref, "data": base64.b64encode(bytes(buf)).decode("ascii")}

    # --- disque ---
    def save(self, path: str):
        with self.lock:
            dump = {"v": 1, "symbol": self.symbol, "step": self.step,
                    "series": {k: [(t, k0, a.tobytes()) for t, k0, a in v] for k, v in self.series.items()}}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump(dump, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)

    def load(self, path: str, now_ms: int) -> int:
        """Recharge les photos de moins de 24 h si la tranche de prix n'a pas changé. Rend le nombre de photos reprises."""
        try:
            with open(path, "rb") as f:
                d = pickle.load(f)
        except (OSError, EOFError, pickle.UnpicklingError, ValueError, AttributeError):
            return 0
        if d.get("v") != 1 or not d.get("step"):
            return 0
        if self.step is None:
            self.step = float(d["step"])
        if abs(float(d["step"]) - self.step) > 1e-12:
            return 0
        n = 0
        with self.lock:
            for k, v in (d.get("series") or {}).items():
                if k not in self.series:
                    continue
                keep = []
                for t, k0, raw in v:
                    if t >= now_ms - self.keep:
                        a = array.array("f")
                        a.frombytes(raw)
                        keep.append((int(t), int(k0), a))
                self.series[k] = keep + [x for x in self.series[k] if not keep or x[0] > keep[-1][0]]
                n += len(keep)
        return n


class HeatLong:
    """Mémoire longue (V29) : par source (bourse, ou « archive » pour les archives Binance), des colonnes (début du quart d'heure, première
    tranche de 0,1 %, montants en dollars) triées dans le temps. Un fichier par jour ; seuls les jours modifiés sont réécrits."""

    def __init__(self, symbol: str, days: int = LT_DAYS, folder: str | None = None):
        self.symbol, self.days, self.folder = symbol, max(1, int(days)), folder
        self.lock = threading.Lock()
        self.cols = {src: [] for src in LT_SOURCES}
        self.dirty: set = set()
        self.tried: dict = {}                            # archives : jour -> dernier essai (ms), pour ne pas redemander sans cesse

    def add(self, src: str, t: int, b0: int, arr) -> None:
        t = int(t) // LT_MS * LT_MS
        with self.lock:
            s = self.cols[src]
            if not s or s[-1][0] < t:
                s.append((t, int(b0), arr))
            else:
                i = _at_or_after(s, t)
                if i < len(s) and s[i][0] == t:
                    s[i] = (t, int(b0), arr)
                else:
                    s.insert(i, (t, int(b0), arr))
            self.dirty.add(t // DAY_MS * DAY_MS)

    def has(self, src: str, t: int) -> bool:
        t = int(t) // LT_MS * LT_MS
        with self.lock:
            s = self.cols[src]
            i = _at_or_after(s, t)
            return i < len(s) and s[i][0] == t

    def count_day(self, src: str, day: int) -> int:
        with self.lock:
            s = self.cols[src]
            return _at_or_after(s, day + DAY_MS) - _at_or_after(s, day)

    def span(self, src: str, ta: int, tb: int) -> list:
        """Colonnes de la source qui commencent dans [ta, tb[ (copie)."""
        with self.lock:
            s = self.cols.get(src) or []
            return s[_at_or_after(s, ta):_at_or_after(s, tb)]

    def since(self, srcs=None):
        with self.lock:
            ts = [s[0][0] for k, s in self.cols.items() if s and (srcs is None or k in srcs)]
        return min(ts) if ts else None

    def last(self, src: str):
        with self.lock:
            s = self.cols[src]
            return s[-1][0] if s else None

    def count(self, src: str | None = None) -> int:
        with self.lock:
            return sum(len(s) for k, s in self.cols.items() if src is None or k == src)

    def prune(self, now_ms: int) -> None:
        cut = (now_ms - self.days * DAY_MS) // DAY_MS * DAY_MS
        with self.lock:
            for s in self.cols.values():
                i = _at_or_after(s, cut)
                if i:
                    del s[:i]
        if self.folder and os.path.isdir(self.folder):
            for fn in os.listdir(self.folder):
                if fn.startswith("long-") and fn.endswith(".pkl") and fn[5:15] < ymd(cut):
                    try:
                        os.remove(os.path.join(self.folder, fn))
                    except OSError:
                        pass

    def save(self) -> int:
        """Réécrit les jours modifiés (et la liste des archives déjà demandées). Rend le nombre de jours écrits."""
        if not self.folder:
            return 0
        with self.lock:
            days, self.dirty = sorted(self.dirty), set()
            dumps = []
            for d in days:
                cols = {}
                for k, s in self.cols.items():
                    part = s[_at_or_after(s, d):_at_or_after(s, d + DAY_MS)]
                    if part:
                        cols[k] = [(t, b0, a.tobytes()) for t, b0, a in part]
                dumps.append((d, cols))
            tried = dict(self.tried)
        os.makedirs(self.folder, exist_ok=True)
        for d, cols in dumps:
            path = os.path.join(self.folder, f"long-{ymd(d)}.pkl")
            with open(path + ".tmp", "wb") as f:
                pickle.dump({"v": LT_VERSION, "symbol": self.symbol, "day": d, "cols": cols}, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(path + ".tmp", path)
        with open(os.path.join(self.folder, "archives.pkl.tmp"), "wb") as f:
            pickle.dump({"v": LT_VERSION, "tried": tried}, f)
        os.replace(os.path.join(self.folder, "archives.pkl.tmp"), os.path.join(self.folder, "archives.pkl"))
        return len(dumps)

    def load(self, now_ms: int) -> int:
        """Recharge les jours gardés (moins de `days` jours). Rend le nombre de colonnes reprises."""
        if not self.folder or not os.path.isdir(self.folder):
            return 0
        cut = (now_ms - self.days * DAY_MS) // DAY_MS * DAY_MS
        n = 0
        for fn in sorted(os.listdir(self.folder)):
            path = os.path.join(self.folder, fn)
            try:
                if fn == "archives.pkl":
                    with open(path, "rb") as f:
                        d = pickle.load(f)
                    if d.get("v") == LT_VERSION:
                        self.tried.update(d.get("tried") or {})
                    continue
                if not (fn.startswith("long-") and fn.endswith(".pkl")):
                    continue
                with open(path, "rb") as f:
                    d = pickle.load(f)
            except (OSError, EOFError, pickle.UnpicklingError, ValueError, AttributeError, TypeError):
                continue
            if d.get("v") != LT_VERSION or d.get("day", 0) < cut:
                continue
            with self.lock:
                for k, lst in (d.get("cols") or {}).items():
                    if k not in self.cols:
                        continue
                    for t, b0, raw in lst:
                        arr = array.array("f")
                        arr.frombytes(raw)
                        self.cols[k].append((int(t), int(b0), arr))
                        n += 1
        with self.lock:
            for s in self.cols.values():
                s.sort(key=lambda x: x[0])
        return n


# ---------- archives publiques de Binance (bookDepth) ----------
def _stamp(x: str, cache: dict):
    """« 2026-10-15 00:00:01 » (UTC) ou un nombre (ms, microsecondes) -> ms ; None si illisible (en-tête)."""
    v = cache.get(x)
    if v is None:
        try:
            if x.isdigit():
                v = int(x) // 1000 if int(x) > 10 ** 14 else int(x)
            else:
                v = calendar.timegm((int(x[0:4]), int(x[5:7]), int(x[8:10]), int(x[11:13]), int(x[14:16]), int(x[17:19]), 0, 0, 0)) * 1000
        except (ValueError, IndexError):
            return None
        cache[x] = v
    return v


def depth_columns(rows, price_at) -> list:
    """Lignes d'une archive « bookDepth » de Binance (horodatage, pourcentage, quantité, dollars en attente CUMULÉS depuis le prix jusqu'à
    ce pourcentage) -> [(début du quart d'heure, première tranche de 0,1 %, dollars)] : par quart d'heure, la moyenne des photos ; chaque
    tranche (0-0,2 %, 0,2-1 %, 1-2 %... 4-5 %, de chaque côté) répartie à parts égales sur sa largeur. price_at(t_ms) -> prix, ou None."""
    cache, acc = {}, {}
    for r in rows:
        if len(r) < 4:
            continue
        t = _stamp(str(r[0]).strip(), cache)
        if t is None:
            continue
        try:
            pct, usd = float(r[1]), float(r[3])
        except ValueError:
            continue
        if not (usd >= 0 and 0 < abs(pct) <= 100):
            continue
        w = t // LT_MS * LT_MS
        lv = acc.setdefault(w, {}).setdefault(pct, [0.0, 0])
        lv[0] += usd
        lv[1] += 1
    out = []
    for w in sorted(acc):
        px = price_at(w + LT_MS // 2)
        if not px or px <= 0:
            continue
        lv = {p: v[0] / v[1] for p, v in acc[w].items()}
        bands = {}
        for sgn in (-1.0, 1.0):
            prev_p, prev_v = 0.0, 0.0
            for p in sorted((p for p in lv if p * sgn > 0), key=abs):
                a_, b_ = abs(prev_p) / 100.0, abs(p) / 100.0
                if b_ > LT_RANGE + 1e-9:
                    break
                usd = lv[p] - prev_v
                p1, p2 = (px * (1 - b_), px * (1 - a_)) if sgn < 0 else (px * (1 + a_), px * (1 + b_))
                k1, k2 = math.log(p1) / LT_BAND, math.log(p2) / LT_BAND
                if usd > 0 and k2 > k1:
                    for k in range(math.floor(k1), math.ceil(k2)):
                        ov = min(k + 1, k2) - max(k, k1)
                        if ov > 0:
                            bands[k] = bands.get(k, 0.0) + usd * ov / (k2 - k1)
                prev_p, prev_v = p, max(prev_v, lv[p])
        if bands:
            b0, b1 = min(bands), max(bands)
            arr = array.array("f", bytes(4 * (b1 - b0 + 1)))
            for k, v in bands.items():
                arr[k - b0] = v
            out.append((w, b0, arr))
    return out


def fetch_depth(sym: str, day_ms: int, http_bytes=None):
    """Archive bookDepth d'un jour (lignes du CSV), None si Binance ne l'a pas (404 : pas encore publiée, ou jour manquant)."""
    import csv
    import io
    import zipfile
    if http_bytes is None:
        from .trades import http_bytes
    raw = http_bytes(DEPTH_URL.format(s=sym.upper(), d=ymd(day_ms)), timeout=90)
    if raw is None:
        return None
    zf = zipfile.ZipFile(io.BytesIO(raw))
    name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
    with zf.open(name) as f:
        return list(csv.reader(io.TextIOWrapper(f, encoding="utf-8", newline="")))


class HeatRecorder:
    """Une boucle par source : photo, rangement, sauvegarde toutes les 5 minutes. sources : {nom: fonction -> (achats, ventes) ou None}.
    V29 : une boucle résume chaque quart d'heure dans la mémoire longue ; une autre y range les archives Binance des jours sans photos
    (archive(jour) -> lignes ou None ; prices() -> fonction t_ms -> prix, ou None tant que l'historique des bougies n'est pas chargé)."""

    def __init__(self, book: HeatBook, sources: dict, path: str | None = None, now=time.time, every: dict | None = None, prefill=None,
                 archive=None, prices=None, archive_today: bool = False):
        self.book, self.sources, self.path, self.now, self.prefill = book, sources, path, now, prefill
        self.archive, self.prices, self.archive_today = archive, prices, archive_today
        self.every = {**EVERY, **(every or {})}
        self.stop_ev = threading.Event()
        self.threads: list = []
        self.state = {n: {"ok": None, "error": "", "n": 0} for n in sources}
        self.arch = {"state": "en attente" if archive else "désactivées", "days": 0, "missing": 0, "error": "", "running": False}
        self._saved = 0.0
        self._lt_saved = 0.0
        self._lt_next = None

    def sample(self, name: str) -> bool:
        st = self.state[name]
        try:
            got = self.sources[name]()
            if not got:
                st["error"] = "carnet pas encore prêt"
                return False
            bids, asks = got
            ok = self.book.add(name, int(self.now() * 1000), bids, asks)
            if ok:
                st["ok"], st["error"], st["n"] = int(self.now() * 1000), "", st["n"] + 1
            return ok
        except Exception as e:                                  # réseau, format : la série attend la prochaine photo
            st["error"] = f"{type(e).__name__}: {e}"[:160]
            return False

    # --- mémoire longue ---
    def summarize(self) -> int:
        """Range dans la mémoire longue les quarts d'heure terminés qui ont des photos et n'y sont pas encore. Rend le nombre ajouté."""
        lng = self.book.long
        first = self.book.since()
        if lng is None or first is None:
            return 0
        now = int(self.now() * 1000)
        w = max(first // LT_MS * LT_MS, self._lt_next or 0)
        added = 0
        exs = [ex for ex in EXCHANGES if any(SERIES[n][0] == ex for n in self.book.series if self.book.series[n])]
        while w + LT_MS <= now - 30_000:
            for ex in exs:
                if not lng.has(ex, w):
                    col = self.book.long_column(w, ex)
                    if col:
                        lng.add(ex, w, col[0], col[1])
                        added += 1
            w += LT_MS
        self._lt_next = w
        return added

    def fetch_archives(self, limit: int | None = None) -> int:
        """Archives Binance des jours de la mémoire longue où il manque des photos, du plus récent au plus ancien. Une archive absente
        (404) est redemandée toutes les 3 heures pendant 3 jours (publication du lendemain), puis une fois par semaine. Rend le nombre de
        jours rangés."""
        lng = self.book.long
        if lng is None or self.archive is None or self.prices is None:
            return 0
        price_at = self.prices()
        if price_at is None:
            self.arch["state"] = "en attente de l'historique des prix"
            return 0
        now = int(self.now() * 1000)
        today = now // DAY_MS * DAY_MS
        got = 0
        self.arch.update(running=True, state="téléchargement")
        try:
            for k in range(0 if self.archive_today else 1, lng.days + 1):
                if self.stop_ev.is_set() or (limit is not None and got >= limit):
                    break
                day = today - k * DAY_MS
                if day < listing.first_ms(lng.symbol):
                    break                                           # V42 : rien avant le premier jour de la paire
                have = lng.count_day("archive", day) + lng.count_day("binance", day)
                if have >= (min(now - day, DAY_MS) // LT_MS) * 0.85:
                    continue                                        # jour déjà couvert (85 % des quarts d'heure)
                key = ymd(day)
                if now - lng.tried.get(key, 0) < (3 * 3_600_000 if k <= 3 else 7 * DAY_MS):
                    continue
                lng.tried[key] = now
                try:
                    rows = self.archive(day)
                except Exception as e:                              # réseau coupé : on réessaie au prochain tour
                    self.arch["error"] = f"{type(e).__name__}: {e}"[:160]
                    lng.tried.pop(key, None)
                    break
                if rows is None:
                    self.arch["missing"] += 1
                    continue
                for w, b0, arr in depth_columns(rows, price_at):
                    if not lng.has("binance", w):
                        lng.add("archive", w, b0, arr)
                got += 1
                self.arch["error"] = ""
                if got % 15 == 0:
                    self._save_long()
        finally:
            self.arch.update(running=False, state="à jour" if not self.arch["error"] else "interrompues")
            self.arch["days"] = len({t // DAY_MS for t, _, _ in lng.span("archive", 0, 2 ** 62)})
            self._save_long()
        return got

    def _save_long(self):
        try:
            if self.book.long is not None:
                self.book.long.save()
        except OSError:
            pass

    def _long_loop(self):
        nxt_arch, nxt_prune = time.monotonic() + (0 if self.prefill else 20), 0.0
        while not self.stop_ev.wait(5.0 if self._lt_next is None else 30.0):
            self.summarize()
            if time.monotonic() >= nxt_prune:
                nxt_prune = time.monotonic() + 3600
                if self.book.long is not None:
                    self.book.long.prune(int(self.now() * 1000))
            if self.archive is not None and time.monotonic() >= nxt_arch:
                self.fetch_archives()
                waiting = self.arch["state"].startswith("en attente")
                nxt_arch = time.monotonic() + (30 if waiting else 600 if self.arch["error"] else 3 * 3600)
            if self.book.long is not None and self.book.long.dirty and self.now() - self._lt_saved > 900:
                self._lt_saved = self.now()
                self._save_long()

    def _boot(self):
        """Mode simulé : attend le premier prix, range quelques heures de photos d'un coup, puis lance les photos régulières."""
        for _ in range(90):
            if self.stop_ev.wait(2.0) or self.prefill():
                break
        if not self.stop_ev.is_set():
            self._start_sources()

    def _loop(self, name):
        wait = 2.0
        while not self.stop_ev.wait(wait):
            self.sample(name)
            wait = self.every.get(name, 10.0)
            if self.path and name == next(iter(self.sources)) and self.now() - self._saved > 300:
                self._saved = self.now()
                try:
                    self.book.save(self.path)
                except OSError:
                    pass

    def start(self):
        if self.threads:
            return
        now = int(self.now() * 1000)
        if self.path:
            self.book.load(self.path, now)
        if self.book.long is not None:
            self.book.long.load(now)
        if self.prefill:
            t = threading.Thread(target=self._boot, name=f"heatmap-{self.book.symbol}-reprise", daemon=True)
            t.start()
            self.threads.append(t)
        else:
            self._start_sources()
        if self.book.long is not None:
            t = threading.Thread(target=self._long_loop, name=f"heatmap-{self.book.symbol}-memoire", daemon=True)
            t.start()
            self.threads.append(t)

    def _start_sources(self):
        for name in self.sources:
            t = threading.Thread(target=self._loop, args=(name,), name=f"heatmap-{self.book.symbol}-{name}", daemon=True)
            t.start()
            self.threads.append(t)

    def stop(self):
        self.stop_ev.set()
        if self.path:
            try:
                self.book.save(self.path)
            except OSError:
                pass
        self._save_long()

    def status(self) -> dict:
        out = {}
        for ex in EXCHANGES:
            names = [n for n in self.sources if SERIES[n][0] == ex]
            if not names:
                continue
            last = max((self.state[n]["ok"] or 0 for n in names), default=0) or None
            err = "; ".join(self.state[n]["error"] for n in names if self.state[n]["error"] and not self.state[n]["ok"])
            out[ex] = {"name": EX_NAMES[ex], "last": last, "error": err, "photos": sum(self.state[n]["n"] for n in names)}
        return out

    def long_status(self) -> dict:
        lng = self.book.long
        if lng is None:
            return {"on": False}
        return {"on": True, "days": lng.days, "since": lng.since(EXCHANGES), "archiveSince": lng.since(("archive",)),
                "archive": dict(self.arch)}


# ---------- sources réelles ----------
def real_sources(sym: str, flow, http_json) -> dict:
    """Carnets en direct déjà suivis (Binance, OKX) + adresses publiques profondes (OKX, Bybit, Coinbase). Quantités en pièces."""
    from .orderflow import base_of, okx_inst
    base = base_of(sym.upper())
    ct = CTVAL.get(base, 1.0)
    inst = okx_inst(sym)
    src = {}
    if flow is not None and sym in getattr(flow, "books", {}):
        def binance():
            b, a = flow.books[sym].levels()
            return (b, a) if b and a else None

        def okx():
            ok = flow.okx.get(inst)
            if ok is None:
                return None
            b, a = ok.levels()
            return ([(p, s * ct) for p, s, _ in b], [(p, s * ct) for p, s, _ in a]) if b and a else None
        src["binance"], src["okx"] = binance, okx

    def okx_deep():
        d = http_json(f"https://www.okx.com/api/v5/market/books-full?instId={inst}&sz=5000", timeout=20)
        x = (d.get("data") or [{}])[0]
        return ([(float(p), float(s) * ct) for p, s, *_ in x.get("bids", ())], [(float(p), float(s) * ct) for p, s, *_ in x.get("asks", ())])

    def bybit():
        d = http_json(f"https://api.bybit.com/v5/market/orderbook?category=linear&symbol={sym.upper()}&limit=500", timeout=15)
        r = d.get("result") or {}
        return ([(float(p), float(s)) for p, s in r.get("b", ())], [(float(p), float(s)) for p, s in r.get("a", ())])

    def coinbase():
        d = http_json(f"https://api.exchange.coinbase.com/products/{base}-USD/book?level=2", timeout=30)
        return ([(float(x[0]), float(x[1])) for x in d.get("bids", ())], [(float(x[0]), float(x[1])) for x in d.get("asks", ())])
    src["okxDeep"], src["bybit"], src["coinbase"] = okx_deep, bybit, coinbase
    return src


# ---------- version simulée ----------
class SimHeat:
    """Carnets fabriqués autour du prix simulé : un fond qui décroît avec la distance, et des murs qui naissent, durent de 20 minutes
    à quelques heures et disparaissent (plus nombreux sur les prix ronds). Une graine par bourse pour que chacune ait ses murs."""

    def __init__(self, price_at, seed: int = 11):
        self.price_at, self.seed = price_at, seed
        self._pc: dict = {}                                     # prix à la naissance de chaque mur

    def _walls(self, ex, t_ms, px):
        """Murs vivants à l'instant t : chaque tranche de 20 minutes en fait naître trois, au prix du moment, qui vivent 20 minutes
        à 4 heures (le même mur se retrouve donc d'une photo à l'autre)."""
        P, out = 1_200_000, []
        for k in range(t_ms // P - 12, t_ms // P + 1):
            for i in range(3):
                r2 = random.Random(f"{self.seed}-{ex}-{k}-{i}")
                born, life = k * P + r2.randint(0, P - 1), r2.choice((1_200_000, 2_400_000, 3_600_000, 7_200_000, 14_400_000))
                if not born <= t_ms < born + life:
                    continue
                ref = self._pc.get(born)
                if ref is None:
                    if len(self._pc) > 5000:
                        self._pc.clear()
                    ref = self._pc[born] = self.price_at(born) or px
                p = ref * (1 + r2.uniform(-0.025, 0.025))
                if r2.random() < 0.4:
                    unit = nice(px * 0.005)
                    p = round(p / unit) * unit
                out.append((p, r2.uniform(0.6, 4.0) * 1_000_000))
        return out

    def book(self, ex: str, t_ms: int):
        px = self.price_at(t_ms)
        if not px:
            return None
        rnd = random.Random(f"{ex}-{t_ms // 10_000}")
        tick = px * 0.0002
        bids, asks = [], []
        reach = {"binance": 0.012, "okx": 0.004, "okxDeep": 0.02, "bybit": 0.003, "coinbase": 0.04}.get(ex, 0.01)
        n = int(px * reach / tick)
        for i in range(1, n + 1):
            d = i * tick
            base = 90_000 * math.exp(-d / (px * 0.004)) + 9_000
            for side, p in ((bids, px - d), (asks, px + d)):
                side.append((p, base * rnd.expovariate(1.0) / p))
        for p, usd in self._walls(SERIES.get(ex, (ex,))[0], t_ms, px):
            if abs(p / px - 1) <= reach:
                (bids if p < px else asks).append((p, usd / p))
        return bids, asks


def sim_sources(sim: SimHeat, now=time.time) -> dict:
    return {n: (lambda n=n: sim.book(n, int(now() * 1000))) for n in SERIES}


def sim_backfill(book: HeatBook, sim: SimHeat, now_ms: int, hours: float = 6.0) -> bool:
    """Mode simulé : quelques heures de photos d'emblée, pour que l'écran ne soit pas vide. False tant qu'il n'y a pas de prix."""
    if not sim.price_at(now_ms):
        return False
    for n in SERIES:
        step = int(EVERY[n] * 1000)
        t = now_ms - int(hours * 3_600_000)
        t -= t % step
        while t <= now_ms:
            got = sim.book(n, t)
            if got:
                book.add(n, t, *got)
            t += step
    return True


def sim_depth_rows(sym: str, day_ms: int, price_at, now_ms: int | None = None) -> list:
    """Mode simulé : une archive « bookDepth » plausible pour un jour (une photo par quart d'heure, déjà passée) : montants cumulés à
    0,2 / 1 / 2 / 3 / 4 / 5 % de chaque côté, avec une dérive lente et, certains jours, une tranche bien plus épaisse (un gros mur)."""
    rnd = random.Random(f"depth-{sym}-{day_ms // DAY_MS}")
    scale = (1.0 if sym.upper().startswith("BTC") else 0.12) / 60      # à l'échelle des carnets simulés (SimHeat), pas des vrais
    base_b = [45, 230, 480, 600, 680, 760]
    base_a = [45, 180, 360, 430, 480, 520]
    tilt = rnd.uniform(-0.25, 0.25)                         # un côté plus épais que l'autre ce jour-là
    wall = (rnd.choice((-1, 1)), rnd.randrange(1, 6), rnd.uniform(1.3, 1.9), rnd.randrange(0, 80)) if rnd.random() < 0.6 else None
    rows = [["timestamp", "percentage", "depth", "notional"]]
    for q in range(96):
        t = day_ms + q * LT_MS + 60_000
        if now_ms is not None and t > now_ms:
            break
        px = price_at(t)
        if not px:
            continue
        drift = 1 + 0.25 * math.sin((t / DAY_MS) * 0.9 + rnd.random() * 0.3)
        for side, base, sgn in ((base_b, base_b, -1), (base_a, base_a, 1)):
            cum = 0.0
            for i, pct in enumerate((0.2, 1, 2, 3, 4, 5)):
                inc = (base[i] - (base[i - 1] if i else 0)) * 1e6 * scale * drift * (1 + sgn * tilt) * rnd.uniform(0.85, 1.15)
                if wall and wall[0] == sgn and wall[1] == i and wall[3] <= q < wall[3] + 16:
                    inc *= wall[2]
                cum += inc
                rows.append([time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t / 1000)), f"{sgn * pct:.2f}", f"{cum / px:.3f}", f"{cum:.2f}"])
    return rows
