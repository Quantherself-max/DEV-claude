"""Heatmap du carnet d'ordres (V28) : où attendent les gros ordres, et depuis combien de temps.

Le terminal photographie les carnets à intervalle régulier et range chaque photo par tranche de prix (montant en dollars, achats et
ventes additionnés), sur ±4 % autour du prix :
  - Binance (perpétuel) : le carnet local déjà tenu à jour en direct pour l'écran (flux des différences), toutes les 10 secondes ;
  - OKX (perpétuel) : le carnet en direct de 400 niveaux toutes les 10 secondes, et un carnet profond de 5 000 niveaux toutes les
    3 minutes (adresse publique « books-full ») pour les prix plus éloignés ;
  - Bybit (perpétuel) : 500 niveaux toutes les 30 secondes (adresse publique) ;
  - Coinbase (comptant BTC-USD) : le carnet complet toutes les 10 minutes (adresse publique, 1 Mo environ).
Sur une même bourse, la photo en direct passe devant la photo profonde là où elle couvre le prix. 24 heures sont gardées et
sauvegardées sur le disque (data_local/heatmap). Aucune source gratuite ne donne le carnet passé : la heatmap commence au premier
lancement. Volume réseau estimé : 350 Mo par jour (désactivable : TERMINAL_HEATMAP=0 dans .env).
SimHeat fabrique des carnets avec des murs persistants pour le mode « données simulées »."""
import array
import base64
import bisect
import math
import os
import pickle
import random
import threading
import time

RANGE = 0.04
KEEP_MS = 24 * 3_600_000
CTVAL = {"BTC": 0.01, "ETH": 0.1, "SOL": 1.0}               # pièces par contrat OKX
EXCHANGES = ("binance", "okx", "bybit", "coinbase")
EX_NAMES = {"binance": "Binance", "okx": "OKX", "bybit": "Bybit", "coinbase": "Coinbase"}
# série -> (bourse, priorité, âge maximal d'une photo pour qu'elle compte encore)
SERIES = {"binance": ("binance", 0, 45_000), "okx": ("okx", 0, 45_000), "okxDeep": ("okx", 1, 420_000),
          "bybit": ("bybit", 0, 100_000), "coinbase": ("coinbase", 0, 1_300_000)}
EVERY = {"binance": 10.0, "okx": 10.0, "okxDeep": 180.0, "bybit": 30.0, "coinbase": 600.0}


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
    """Photos rangées par tranche de prix, par série ; query() rend une image temps x prix prête à dessiner."""

    def __init__(self, symbol: str, step: float | None = None, keep_ms: int = KEEP_MS):
        self.symbol, self.keep = symbol, keep_ms
        self.step = step or STEP.get(symbol.upper()[:-4] if symbol.upper().endswith("USDT") else symbol.upper())   # sinon : au premier prix
        self.lock = threading.Lock()
        self.series = {name: [] for name in SERIES}          # [(t_ms, k0, array('f'))] par ordre chronologique

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

    def query(self, t0: int, t1: int, lo: float, hi: float, cols: int = 300, rows: int = 250, exchanges=EXCHANGES) -> dict:
        """Image temps x prix : chaque colonne montre la dernière photo de chaque bourse (au plus vieille de son âge maximal), chaque
        ligne le montant en dollars de sa tranche de prix. Valeurs codées sur 0-255 (échelle en racine, 255 = 99e centile)."""
        cols = max(10, min(600, int(cols)))
        rows = max(10, min(400, int(rows)))
        if not (t1 > t0 and hi > lo > 0) or self.step is None:
            return {"ready": False}
        step = self.step
        rowsz = step * max(1, math.ceil((hi - lo) / rows / step))
        r0 = math.floor(lo / rowsz)
        m = max(1, math.ceil(hi / rowsz) - r0)
        dt = (t1 - t0) / cols
        mat = [0.0] * (cols * m)
        k_lo, k_hi = math.floor(lo / step), math.floor(hi / step)
        with self.lock:
            snaps = {k: list(v) for k, v in self.series.items()}
        for ex in exchanges:
            names = sorted((n for n, (e, _, _) in SERIES.items() if e == ex), key=lambda n: SERIES[n][1])
            ptr = {n: -1 for n in names}
            for ci in range(cols):
                tc = t0 + (ci + 1) * dt
                covered = None                                  # lignes déjà couvertes par une photo plus fraîche de la même bourse
                for n in names:
                    s = snaps.get(n) or []
                    p = ptr[n]
                    while p + 1 < len(s) and s[p + 1][0] <= tc:
                        p += 1
                    ptr[n] = p
                    if p < 0 or tc - s[p][0] > SERIES[n][2]:
                        continue
                    _, k0, arr = s[p]
                    a, b = max(k0, k_lo), min(k0 + len(arr) - 1, k_hi)
                    j_a, j_b = int(math.floor(k0 * step / rowsz)) - r0, int(math.floor((k0 + len(arr) - 1) * step / rowsz)) - r0
                    for k in range(a, b + 1):
                        v = arr[k - k0]
                        if v <= 0:
                            continue
                        j = int(math.floor(k * step / rowsz + 1e-9)) - r0
                        if 0 <= j < m and not (covered and covered[0] <= j <= covered[1]):
                            mat[j * cols + ci] += v
                    covered = (j_a, j_b) if covered is None else (min(covered[0], j_a), max(covered[1], j_b))
        nz = sorted(v for v in mat if v > 0)
        if not nz:
            return {"ready": True, "empty": True, "t0": t0, "t1": t1, "cols": cols, "rows": m, "lo": r0 * rowsz, "rowsz": rowsz, "ref": 0.0, "data": ""}
        ref = nz[min(len(nz) - 1, int(len(nz) * 0.99))] or nz[-1]
        buf = bytearray(cols * m)
        for i, v in enumerate(mat):
            if v > 0:
                buf[i] = max(1, min(255, int(255 * math.sqrt(min(1.0, v / ref)))))
        return {"ready": True, "empty": False, "t0": t0, "t1": t1, "cols": cols, "rows": m, "lo": r0 * rowsz, "rowsz": rowsz,
                "ref": ref, "data": base64.b64encode(bytes(buf)).decode("ascii")}

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


class HeatRecorder:
    """Une boucle par source : photo, rangement, sauvegarde toutes les 5 minutes. sources : {nom: fonction -> (achats, ventes) ou None}."""

    def __init__(self, book: HeatBook, sources: dict, path: str | None = None, now=time.time, every: dict | None = None, prefill=None):
        self.book, self.sources, self.path, self.now, self.prefill = book, sources, path, now, prefill
        self.every = {**EVERY, **(every or {})}
        self.stop_ev = threading.Event()
        self.threads: list = []
        self.state = {n: {"ok": None, "error": "", "n": 0} for n in sources}
        self._saved = 0.0

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
        if self.path:
            self.book.load(self.path, int(self.now() * 1000))
        if self.prefill:
            t = threading.Thread(target=self._boot, name=f"heatmap-{self.book.symbol}-reprise", daemon=True)
            t.start()
            self.threads.append(t)
        else:
            self._start_sources()

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
