"""Carte des liquidations sur plusieurs mois (V29), pour l'AFFICHAGE seulement.

Même moteur que les poches de liquidation (engine/liquidity.py : leviers 10x, 25x, 50x et 100x, répartition longs / shorts par le
volume acheteur agressif, un niveau s'éteint quand le prix le touche, réduction quand l'intérêt ouvert baisse), rejoué sur les bougies
d'une heure avec l'intérêt ouvert de chaque heure : celui des 29 derniers jours (adresse Binance, comme les poches) et, avant, celui
des archives publiques de Binance (« metrics », data.binance.vision, toutes les 5 minutes depuis décembre 2021). Une photo compacte par
heure (tranches de 0,15 % du prix, ±30 % autour du prix de l'heure).

Ce moteur est SÉPARÉ de celui des poches : les poches, les confluences, les idées de trade et leurs scores ne changent pas.
C'est une estimation (on ne connaît ni les leviers réels ni les prix d'entrée), comme les cartes de liquidation des sites spécialisés."""
import array
import base64
import bisect
import math
import threading
import time

from .liquidity import LiqEngine, band_of, band_price

H1 = 3_600_000
DAY = 86_400_000
SPAN = 0.30                                   # tranches gardées à ±30 % du prix de l'heure
GAP = 3 * H1                                  # trou dans l'intérêt ouvert au-delà duquel on repart de zéro (pas de bloc artificiel)


def _at_or_after(s, t) -> int:
    return bisect.bisect_left(s, t, key=lambda x: x[0])


class LiqMap:
    """photos : [(début de l'heure, première tranche longs, tailles longs, première tranche shorts, tailles shorts)], en pièces."""

    def __init__(self, days: int = 180):
        self.days = max(1, int(days))
        self.eng = LiqEngine(max_snaps=2)
        self.snaps: list = []
        self.fed = None                       # ouverture de la dernière bougie rangée
        self.oi_t = None                      # fin de la dernière heure dont l'intérêt ouvert est connu
        self.oi_first = None                  # première heure avec un intérêt ouvert
        self.lock = threading.Lock()

    def _bands(self, price):
        lo_b, hi_b = band_of(price * (1 - SPAN)), band_of(price * (1 + SPAN))
        out = []
        for d in self.eng._bands_now():
            keys = [b for b, v in d.items() if v > 0 and lo_b <= b <= hi_b]
            if not keys:
                out += [0, array.array("f")]
                continue
            b0 = min(keys)
            arr = array.array("f", bytes(4 * (max(keys) - b0 + 1)))
            for b in keys:
                arr[b - b0] = d[b]
            out += [b0, arr]
        return out

    def feed(self, bars, oi_at, now_ms: int | None = None) -> int:
        """bars : bougies d'une heure FERMÉES, dans l'ordre ; oi_at(fin de l'heure) -> intérêt ouvert (pièces) ou None. Rend le nombre rangé."""
        n = 0
        with self.lock:
            for k in bars:
                if self.fed is not None and k.t <= self.fed:
                    continue
                self.snaps.append((k.t, *self._bands(k.o)))          # l'état au début de l'heure
                oi = oi_at(k.t + H1)
                if oi is not None:
                    if self.oi_t is not None and k.t + H1 - self.oi_t > GAP:
                        self.eng.oi_last = None
                    self.oi_t = k.t + H1
                    if self.oi_first is None:
                        self.oi_first = k.t
                self.eng.step(oi, k.h, k.l, k.c, k.v, k.tb if k.tb > 0 else None, None)
                self.fed = k.t
                n += 1
            if now_ms is not None and self.snaps and self.snaps[0][0] < now_ms - self.days * DAY - DAY:
                del self.snaps[:_at_or_after(self.snaps, now_ms - self.days * DAY)]
        return n

    def since(self):
        with self.lock:
            return self.snaps[0][0] if self.snaps else None

    def query(self, t0: int, t1: int, lo: float, hi: float, cols: int = 300, rows: int = 250, price: float | None = None) -> dict:
        """Image temps x prix (lignes de prix régulières) : chaque colonne montre la dernière photo horaire (l'heure en cours : l'état
        actuel), longs et shorts additionnés. Valeurs codées sur 0-255 (puissance 0,85 jusqu'au 98,5e centile ; sous 5 % : rien)."""
        cols = max(10, min(600, int(cols)))
        rows = max(10, min(400, int(rows)))
        if not (t1 > t0 and hi > lo > 0):
            return {"ready": False}
        with self.lock:
            if not self.snaps:
                return {"ready": False, "why": "carte en préparation"}
            snaps = self.snaps[max(0, _at_or_after(self.snaps, t0) - 1):_at_or_after(self.snaps, t1 + 1)]
            live = (self.fed + H1, *self._bands(price)) if (price and self.fed is not None) else None
        if live:
            snaps.append(live)
        rowsz = (hi - lo) / rows
        dt = (t1 - t0) / cols
        mat = [0.0] * (cols * rows)
        alloc: dict = {}

        def rows_of(b):
            r = alloc.get(b)
            if r is None:
                y1, y2 = (band_price(b) - lo) / rowsz, (band_price(b + 1) - lo) / rowsz
                r = []
                for j in range(max(0, math.floor(y1)), min(rows - 1, math.floor(y2)) + 1):
                    ov = min(j + 1, y2) - max(j, y1)
                    if ov > 0:
                        r.append((j, ov / (y2 - y1)))
                alloc[b] = r
            return r

        b_lo, b_hi = band_of(lo) - 1, band_of(hi) + 1
        p = -1
        for ci in range(cols):
            tc = t0 + (ci + 1) * dt
            while p + 1 < len(snaps) and snaps[p + 1][0] <= tc:
                p += 1
            if p < 0 or tc - snaps[p][0] > max(2 * H1, dt):
                continue
            _, b0l, al, b0s, ash = snaps[p]
            for b0, arr in ((b0l, al), (b0s, ash)):
                for i in range(max(0, b_lo - b0), min(len(arr), b_hi - b0 + 1)):
                    v = arr[i]
                    if v > 0:
                        for j, f in rows_of(b0 + i):
                            mat[j * cols + ci] += v * f
        base = {"ready": True, "t0": t0, "t1": t1, "cols": cols, "rows": rows, "lo": lo, "rowsz": rowsz,
                "since": snaps[0][0] if snaps else None, "oiSince": self.oi_first}
        nz = sorted(v for v in mat if v > 0)
        if not nz:
            return {**base, "empty": True, "ref": 0.0, "data": ""}
        ref = nz[min(len(nz) - 1, int(len(nz) * 0.985))] or nz[-1]
        buf = bytearray(cols * rows)
        for i, v in enumerate(mat):
            r = v / ref
            if r >= 0.05:
                buf[i] = max(1, min(255, int(255 * min(1.0, r) ** 0.85)))
        return {**base, "empty": False, "ref": ref, "data": base64.b64encode(bytes(buf)).decode("ascii")}


class LiqMapKeeper:
    """Tient la carte d'une paire à jour, en tâche de fond : la construit dès que l'historique est chargé, ajoute chaque heure fermée, la
    reconstruit quand des archives d'intérêt ouvert arrivent (de nouvelles heures anciennes deviennent connues).
    market() -> Market (store.h1, store.oi) ou None ; archive.points() -> {fin de période 5 min (ms): intérêt ouvert} ; archive.fetch()
    télécharge les jours manquants (rend le nombre de jours nouveaux)."""

    def __init__(self, symbol: str, market, archive=None, days: int = 180, now=time.time, deep=None):
        self.symbol, self.market, self.archive, self.days, self.now = symbol, market, archive, days, now
        self.deep = deep                                      # V33 : intérêt ouvert sur plusieurs années (bougies sous le graphique seulement)
        self.map: LiqMap | None = None
        self.stop_ev = threading.Event()
        self.thread = None
        self.state = {"state": "en attente de l'historique", "error": "", "builtAt": None, "archiveDays": 0}
        self._rebuild = True

    def _oi_at(self):
        m = self.market()
        live = dict(m.store.oi) if m is not None else {}
        arch = self.archive.points() if self.archive is not None else {}

        def at(t_end):
            v = live.get(t_end - 300_000)                    # OI de l'adresse Binance : clé = ouverture de la bougie 5 min
            if v is None:
                v = arch.get(t_end)
                if v is None:
                    v = arch.get(t_end - 300_000)
            return v
        return at

    def _bars(self, after=None):
        m = self.market()
        if m is None or not m.ready or not m.store.h1:
            return None
        now = int(self.now() * 1000)
        t0 = now - self.days * DAY
        return [k for k in list(m.store.h1) if k.t >= t0 and k.t + H1 <= now and (after is None or k.t > after)]

    def step(self) -> bool:
        """Un passage : construit, reconstruit ou complète la carte. Rend True si elle a changé."""
        if self._rebuild or self.map is None:
            bars = self._bars()
            if not bars:
                return False
            mp = LiqMap(self.days)
            mp.feed(bars, self._oi_at(), int(self.now() * 1000))
            self.map, self._rebuild = mp, False
            self.state.update(state="à jour", builtAt=int(self.now() * 1000))
            return True
        bars = self._bars(self.map.fed)
        if bars:
            self.map.feed(bars, self._oi_at(), int(self.now() * 1000))
            return True
        return False

    def fetch_archives(self) -> int:
        if self.archive is None:
            return 0
        try:
            n = self.archive.fetch(self.stop_ev)
            self.state["error"] = ""
        except Exception as e:                                # réseau : on réessaie plus tard
            self.state["error"] = f"{type(e).__name__}: {e}"[:160]
            return 0
        self.state["archiveDays"] = self.archive.days_count()
        if n:
            self._rebuild = True
        return n

    def _loop(self):
        nxt_arch = 0.0
        while not self.stop_ev.wait(3.0 if self.map is None else 30.0):
            try:
                self.step()
                if time.monotonic() >= nxt_arch and self.map is not None:
                    self.fetch_archives()
                    nxt_arch = time.monotonic() + (600 if self.state["error"] else 3 * 3600)
                    self.step()
                    if self.deep is not None:                 # après la carte : l'intérêt ouvert des années précédentes, au calme
                        try:
                            self.deep.fetch(self.stop_ev)
                            self.state["deepDays"] = self.deep.days_count()
                        except Exception as e:
                            self.state["deepError"] = f"{type(e).__name__}: {e}"[:160]
            except Exception as e:                            # une erreur ici ne doit jamais arrêter le terminal
                self.state["error"] = f"{type(e).__name__}: {e}"[:160]

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name=f"carte-liquidations-{self.symbol}", daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_ev.set()

    def status(self) -> dict:
        mp = self.map
        return {**self.state, "since": mp.since() if mp else None, "oiSince": mp.oi_first if mp else None, "days": self.days}
