"""Flux par taille d'ordre (V39) : delta (achats agressifs moins ventes agressives, en dollars) separe selon la TAILLE de chaque ordre,
comme l'indicateur « Volume By Side (delta) » d'Aggr : 0 a 1 000 $, 1 000 a 10 000 $, 10 000 a 100 000 $, 100 000 $ a 1 million, plus d'un million.

On ne voit pas les portefeuilles : la taille de l'ordre sert d'indice de la taille de celui qui le passe (les petits ordres viennent surtout des
particuliers, les tres gros surtout des institutions et des gros portefeuilles ; un gros acteur peut aussi decouper ses ordres).
Un « ordre » = les transactions consecutives d'un meme sens au meme instant (milliseconde) : un ordre qui balaie plusieurs prix arrive en
plusieurs transactions Binance (aggTrade) au meme instant, elles sont regroupees (comme l'option « aggregate trades » d'Aggr).

Stockage : par jour UTC, un tableau de 1 440 minutes x 10 valeurs (achats puis ventes de chaque classe, en dollars). Couverture : intervalles
de temps ou toutes les transactions sont presentes (meme regle que l'empreinte, engine/footprint.py). Module PUR (un verrou pour le direct)."""
from __future__ import annotations
import threading
from array import array
from bisect import bisect_right

EDGES = (1_000.0, 10_000.0, 100_000.0, 1_000_000.0)            # limites des classes, en dollars
NCLS = len(EDGES) + 1
MIN = 60_000
DAY = 86_400_000
WIDTH = 2 * NCLS                                                 # achats c0..c4 puis ventes c0..c4
NAMES = ["moins de 1 000 $", "1 000 à 10 000 $", "10 000 à 100 000 $", "100 000 $ à 1 million", "plus d'un million"]
# trois groupes lisibles : petits ordres (particuliers), moyens, gros (institutions, gros portefeuilles)
GROUPS = [("petits", "particuliers, moins de 10 000 $", (0, 1)), ("moyens", "10 000 à 100 000 $", (2,)), ("gros", "institutions, plus de 100 000 $", (3, 4))]


def cls_of(usd: float) -> int:
    for i, e in enumerate(EDGES):
        if usd < e:
            return i
    return NCLS - 1


class SizeFlow:
    def __init__(self):
        self.days: dict[int, array] = {}
        self.cov: list[list[int]] = []
        self.lock = threading.RLock()
        self.version = 0
        self._pend = None                                        # ordre en cours de regroupement : [t, vente, dollars]

    # ---------- ecriture ----------
    def _arr(self, day: int) -> array:
        a = self.days.get(day)
        if a is None:
            a = self.days[day] = array("d", bytes(8 * 1440 * WIDTH))
        return a

    def _put(self, t: int, sell: bool, usd: float) -> None:
        day = t - t % DAY
        k = ((t - day) // MIN) * WIDTH + (NCLS if sell else 0) + cls_of(usd)
        self._arr(day)[k] += usd

    def add_unlocked(self, price: float, qty: float, buyer_maker: bool, t_ms: int) -> None:
        """Une transaction, dans l'ordre des numeros. buyer_maker = l'acheteur etait passif : VENTE agressive."""
        p = self._pend
        usd = price * qty
        if p is not None and p[0] == t_ms and p[1] == buyer_maker:
            p[2] += usd
            return
        if p is not None:
            self._put(p[0], p[1], p[2])
        self._pend = [t_ms, buyer_maker, usd]

    def add(self, price: float, qty: float, buyer_maker: bool, t_ms: int) -> None:
        with self.lock:
            self.add_unlocked(price, qty, buyer_maker, t_ms)
            self.version += 1

    def flush(self) -> None:
        """Range l'ordre en cours de regroupement (fin d'une archive, avant une lecture)."""
        with self.lock:
            if self._pend is not None:
                self._put(*self._pend)
                self._pend = None

    def put_day(self, day: int, values) -> None:
        with self.lock:
            a = array("d", bytes(8 * 1440 * WIDTH))
            for i, v in enumerate(values[:len(a)]):
                a[i] = float(v)
            self.days[day] = a
            self.version += 1

    def clear(self, a: int, b: int) -> None:
        """Remet a zero [a, b[ (minutes entieres) et retire sa couverture, avant de le remplacer par une archive complete."""
        with self.lock:
            if self._pend is not None and a <= self._pend[0] < b:
                self._pend = None
            t = a - a % MIN
            while t < b:
                day = t - t % DAY
                arr = self.days.get(day)
                if arr is not None:
                    if t == day and t + DAY <= b:
                        del self.days[day]
                        t += DAY
                        continue
                    k = ((t - day) // MIN) * WIDTH
                    for j in range(WIDTH):
                        arr[k + j] = 0.0
                t += MIN
            self.uncover(a, b)
            self.version += 1

    def cover(self, a: int, b: int) -> None:
        if b <= a:
            return
        with self.lock:
            out = []
            for x, y in self.cov:
                if y < a or x > b:
                    out.append([x, y])
                else:
                    a, b = min(a, x), max(b, y)
            out.append([a, b])
            out.sort()
            self.cov = out

    def uncover(self, a: int, b: int) -> None:
        with self.lock:
            out = []
            for x, y in self.cov:
                if y <= a or x >= b:
                    out.append([x, y])
                    continue
                if x < a:
                    out.append([x, a])
                if y > b:
                    out.append([b, y])
            self.cov = out

    def drop_before(self, t_ms: int) -> None:
        with self.lock:
            for d in [d for d in self.days if d + DAY <= t_ms]:
                del self.days[d]
            self.uncover(-1, t_ms)

    # ---------- lecture ----------
    def complete(self, a: int, b: int) -> bool:
        with self.lock:
            j = bisect_right(self.cov, [a, float("inf")]) - 1
            return j >= 0 and self.cov[j][0] <= a and self.cov[j][1] >= b

    def covered_ms(self, a: int, b: int) -> int:
        with self.lock:
            return sum(max(0, min(y, b) - max(x, a)) for x, y in self.cov)

    def day_array(self, day: int) -> array | None:
        """Copie exacte d'un jour (pour le recopier dans un autre flux sans arrondi)."""
        with self.lock:
            a = self.days.get(day)
            return None if a is None else array("d", a)

    def day_values(self, day: int) -> list | None:
        """Les 14 400 valeurs d'un jour, arrondies au dollar (sauvegarde)."""
        with self.lock:
            a = self.days.get(day)
            return None if a is None else [round(v) for v in a]

    def totals(self, t0: int, t1: int) -> tuple[list, list]:
        """(achats, ventes) en dollars par classe sur [t0, t1[ (minutes entieres)."""
        buy, sell = [0.0] * NCLS, [0.0] * NCLS
        with self.lock:
            t = t0 - t0 % MIN
            while t < t1:
                day = t - t % DAY
                arr = self.days.get(day)
                end = min(t1, day + DAY)
                if arr is not None:
                    k0, k1 = ((t - day) // MIN) * WIDTH, ((end - day + MIN - 1) // MIN) * WIDTH
                    for c in range(NCLS):
                        buy[c] += sum(arr[k0 + c:k1:WIDTH])
                        sell[c] += sum(arr[k0 + NCLS + c:k1:WIDTH])
                t = end
        return buy, sell

    def series(self, times: list[int], step_ms: int, min_cov: float = 0.98) -> dict:
        """Pour chaque bougie [t, t + step[ : delta en dollars de chaque classe (None si moins de 98 % de la bougie est couverte, ou si la
        bougie n'est pas terminee et que sa partie ecoulee n'est pas couverte), et la part couverte."""
        self.flush()
        deltas = [[None] * len(times) for _ in range(NCLS)]
        vols = [[None] * len(times) for _ in range(NCLS)]
        cov = []
        last_end = None
        with self.lock:
            last_end = self.cov[-1][1] if self.cov else None
        for i, t in enumerate(times):
            end = t + step_ms
            if last_end is not None and t < last_end < end:
                end = last_end                                   # bougie en cours : jusqu'a la derniere transaction integree
            span = max(1, end - t)
            c = self.covered_ms(t, end) / span
            cov.append(round(c, 4))
            if c < min_cov:
                continue
            b, s = self.totals(t, end)
            for k in range(NCLS):
                deltas[k][i] = b[k] - s[k]
                vols[k][i] = b[k] + s[k]
        return {"delta": deltas, "volume": vols, "cov": cov}


def simulated(candles, seed: int = 7) -> dict:
    """Mode simule : delta de chaque bougie (volume acheteur agressif connu) reparti entre les classes, avec des comportements differents
    (les gros suivent la tendance de fond, les petits la contrent un peu) : seulement pour decouvrir l'affichage."""
    import random
    r = random.Random(seed)
    n = len(candles)
    share = (0.16, 0.24, 0.27, 0.21, 0.12)
    deltas = [[None] * n for _ in range(NCLS)]
    vols = [[None] * n for _ in range(NCLS)]
    drift = [0.0] * NCLS                                         # chaque taille a aussi son propre courant, lent et persistant
    for i, k in enumerate(candles):
        q = k.q or k.v * k.c
        if not q:
            continue
        d = (2 * k.tb - k.v) * (q / k.v) if k.v else 0.0
        for c in range(NCLS):
            drift[c] = 0.985 * drift[c] + r.gauss(0, 0.012)
            deltas[c][i] = d * share[c] * (0.4 + 0.8 * r.random()) * (1.3 if c >= 3 else 0.7) + drift[c] * q * share[c]
            vols[c][i] = q * share[c]
    return {"delta": deltas, "volume": vols, "cov": [1.0] * n}
