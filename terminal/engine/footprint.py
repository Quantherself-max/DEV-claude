"""Empreinte des transactions (V23) : volume echange a CHAQUE prix, acheteurs agressifs et vendeurs agressifs separes, par tranche de 5 minutes,
construite a partir de chaque transaction de Binance (archives quotidiennes aggTrades de Binance Vision, rattrapage par l'API, flux en direct).

Elle remplace, partout ou elle couvre la periode, la repartition SUPPOSEE du volume d'une bougie (uniforme entre son plus bas et son plus haut,
ou le long de son trajet probable) : profils de volume, POC / VAH / VAL / HVN / LVN, profil de seance, volume et delta a chaque prix du TPO,
prix le plus echange des zones, ecart-type du VWAP. Les tranches de 5 minutes qu'elle ne couvre pas entierement gardent l'ancienne methode
(rien n'est jamais melange a l'interieur d'une tranche).

Pas de prix : le pas de cotation de la bourse, ou un multiple « rond » de celui-ci quand il est beaucoup plus fin qu'un demi-point de base
(BTC : 5 $ ; SOL : 0,01 $, le pas de cotation lui-meme). Un prix de l'empreinte est donc exact (SOL) ou connu a un demi-pas pres (BTC : 2,5 $).
Couverture : intervalles de temps ou TOUTES les transactions sont presentes (journees d'archive completes, rattrapage contigu par numero de
transaction, flux en direct sans trou). Module PUR (aucun acces reseau ou disque ; un verrou pour le flux en direct)."""
from __future__ import annotations
import json
import math
import threading
from array import array
from bisect import bisect_right

from .vp import VP_GRID

BUCKET = 300_000          # 5 minutes
DAY = 86_400_000
FORMAT = 1


def nice_up(x: float) -> float:
    """Plus petit pas « rond » (1, 2, 2,5 ou 5 fois une puissance de 10) au moins egal a x."""
    if x <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(x))
    for m in (1, 2, 2.5, 5, 10):
        if m * e >= x * (1 - 1e-12):
            return m * e
    return 10 * e


def tick_of(text: str) -> float:
    """Pas de cotation deduit de l'ecriture d'un prix (« 109.56 » -> 0,01 ; « 81711.0 » -> 0,1)."""
    t = text.strip()
    if "." not in t:
        return 1.0
    return 10.0 ** -len(t.split(".", 1)[1])


def storage_step(price: float, tick: float) -> float:
    """Pas de l'empreinte : le pas de cotation, ou un multiple rond de celui-ci proche d'un demi-point de base du prix."""
    st = max(tick, nice_up(price * 0.00005))
    r = round(st / tick)
    return tick * max(1, r)


class Footprint:
    """Empreinte d'une paire. Tranche fermee : (indice du premier pas, achats agressifs, ventes agressives) en tableaux contigus ;
    tranche ouverte (jour en cours, rattrapage) : {indice du pas: [achat, vente]}."""

    def __init__(self, step: float, tick: float | None = None):
        self.step = float(step)
        self.tick = float(tick or step)
        self.exact = abs(self.step - self.tick) <= 1e-12 * max(1.0, self.step)     # pas = pas de cotation : chaque prix est exact
        self.closed: dict[int, tuple] = {}
        self.open: dict[int, dict] = {}
        self.cov: list[list[int]] = []                                  # [[debut, fin[, ...] tries, disjoints
        self.lock = threading.RLock()
        self.version = 0
        self._gi: dict[int, int] = {}                                   # indice du pas -> indice de la grille des profils (0,03 %)
        self._gcache: dict[int, tuple] = {}                             # tranche fermee -> son volume par case de la grille (cache)

    # ---------- ecriture ----------
    def idx(self, price: float) -> int:
        return math.floor(price / self.step + 1e-9)

    def price_of(self, i: int) -> float:
        """Prix representatif d'un pas : le prix exact (pas = pas de cotation) ou le milieu du pas."""
        return i * self.step if self.exact else (i + 0.5) * self.step

    def add(self, price: float, qty: float, buyer_maker: bool, t_ms: int) -> None:
        """Une transaction. buyer_maker = l'acheteur etait passif : c'est une VENTE agressive."""
        t5 = t_ms - t_ms % BUCKET
        with self.lock:
            d = self.open.get(t5)
            if d is None:
                d = self._unseal(t5)
            i = math.floor(price / self.step + 1e-9)
            e = d.get(i)
            if e is None:
                d[i] = e = [0.0, 0.0]
            e[1 if buyer_maker else 0] += qty
            self.version += 1

    def add_unlocked(self, price: float, qty: float, buyer_maker: bool, t_ms: int) -> None:
        """Comme add, sans verrou : chargement en bloc d'une empreinte privee (archive du jour)."""
        t5 = t_ms - t_ms % BUCKET
        d = self.open.get(t5)
        if d is None:
            d = self.open[t5] = {}
        i = math.floor(price / self.step + 1e-9)
        e = d.get(i)
        if e is None:
            d[i] = e = [0.0, 0.0]
        e[1 if buyer_maker else 0] += qty

    def clear(self, a: int, b: int) -> None:
        """Retire les tranches qui commencent dans [a, b[ et leur couverture (avant de les remplacer par une archive complete)."""
        with self.lock:
            for t5 in [t for t in self.closed if a <= t < b]:
                del self.closed[t5]
            for t5 in [t for t in self.open if a <= t < b]:
                del self.open[t5]
            self.uncover(a, b)

    def _unseal(self, t5: int) -> dict:
        d = {}
        c = self.closed.pop(t5, None)
        if c is not None:
            i0, b, s = c
            for k in range(len(b)):
                if b[k] or s[k]:
                    d[i0 + k] = [b[k], s[k]]
        self.open[t5] = d
        return d

    def put(self, t5: int, i0: int, buy, sell) -> None:
        """Tranche complete (archive ou fichier) : remplace ce qui existait."""
        with self.lock:
            self.open.pop(t5, None)
            self.closed[t5] = (int(i0), array("d", buy), array("d", sell))
            self.version += 1

    def seal(self, before_ms: int) -> int:
        """Ferme (tableaux compacts) les tranches ouvertes qui commencent avant `before_ms`. Renvoie leur nombre."""
        n = 0
        with self.lock:
            for t5 in [t for t in self.open if t < before_ms]:
                d = self.open.pop(t5)
                if not d:
                    continue
                lo, hi = min(d), max(d)
                b, s = array("d", bytes(8 * (hi - lo + 1))), array("d", bytes(8 * (hi - lo + 1)))
                for i, (x, y) in d.items():
                    b[i - lo], s[i - lo] = x, y
                self.closed[t5] = (lo, b, s)
                n += 1
        return n

    def cover(self, a: int, b: int) -> None:
        """Toutes les transactions de [a, b[ sont presentes."""
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
            self.version += 1

    def uncover(self, a: int, b: int) -> None:
        """[a, b[ n'est plus couvert (trou detecte apres coup)."""
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
            self.version += 1

    def drop_before(self, t_ms: int) -> None:
        with self.lock:
            for t5 in [t for t in self.closed if t < t_ms]:
                del self.closed[t5]
            for t5 in [t for t in self.open if t < t_ms]:
                del self.open[t5]
            self.uncover(-1, t_ms)

    # ---------- lecture ----------
    def complete(self, a: int, b: int) -> bool:
        """Vrai si toutes les transactions de [a, b[ sont presentes."""
        with self.lock:
            cov = self.cov
            j = bisect_right(cov, [a, float("inf")]) - 1
            return j >= 0 and cov[j][0] <= a and cov[j][1] >= b

    def covered_ms(self, a: int, b: int) -> int:
        with self.lock:
            return sum(max(0, min(y, b) - max(x, a)) for x, y in self.cov)

    def first_covered(self):
        with self.lock:
            return self.cov[0][0] if self.cov else None

    def _items(self, t0: int, t1: int):
        """(t5, [(indice, achat, vente), ...]) des tranches qui commencent dans [t0, t1[, dans l'ordre (copie, sous verrou)."""
        out = []
        t = t0 - t0 % BUCKET
        if t < t0:
            t += BUCKET
        with self.lock:
            closed, opened = self.closed, self.open
            while t < t1:
                c = closed.get(t)
                if c is not None:
                    i0, b, s = c
                    out.append((t, [(i0 + k, b[k], s[k]) for k in range(len(b)) if b[k] or s[k]]))
                else:
                    d = opened.get(t)
                    if d:
                        out.append((t, [(i, x, y) for i, (x, y) in d.items()]))
                t += BUCKET
        return out

    def volume(self, t0: int, t1: int):
        """(volume, volume acheteur agressif) de [t0, t1[."""
        v = bv = 0.0
        for _, rows in self._items(t0, t1):
            for _, x, y in rows:
                v += x + y
                bv += x
        return v, bv

    def add_rows(self, t0: int, t1: int, k0: int, n: int, rstep: float, vol, buy) -> float:
        """Ajoute le volume (et le volume acheteur) de [t0, t1[ aux lignes [k0, k0 + n[ d'un pas `rstep` (ligne j = prix [(k0 + j) * rstep,
        (k0 + j + 1) * rstep[). Un pas de l'empreinte tient en entier dans une ligne quand le pas des lignes en est un multiple (exact) ;
        sinon il est partage au prorata de la longueur couverte. Les prix hors des lignes vont a la premiere / derniere. Renvoie le volume."""
        tot, fs = 0.0, self.step
        ratio = rstep / fs
        whole = abs(ratio - round(ratio)) < 1e-6 and round(ratio) >= 1
        last = n - 1
        if whole:                                                       # chemin rapide : chaque ligne = R pas entiers, sommes par blocs
            R = int(round(ratio))
            t = t0 - t0 % BUCKET
            if t < t0:
                t += BUCKET
            with self.lock:
                while t < t1:
                    c = self.closed.get(t)
                    if c is not None:
                        i0, b, s = c
                        L, k = len(b), 0
                        while k < L:
                            j = (i0 + k) // R
                            z = (j + 1) * R - i0
                            if z > L:
                                z = L
                            sb, ss = sum(b[k:z]), sum(s[k:z])
                            if sb or ss:
                                jj = j - k0
                                jj = 0 if jj < 0 else last if jj > last else jj
                                vol[jj] += sb + ss
                                buy[jj] += sb
                                tot += sb + ss
                            k = z
                    else:
                        d = self.open.get(t)
                        if d:
                            for i, (x, y) in d.items():
                                jj = i // R - k0
                                jj = 0 if jj < 0 else last if jj > last else jj
                                vol[jj] += x + y
                                buy[jj] += x
                                tot += x + y
                    t += BUCKET
            return tot
        for _, rows in self._items(t0, t1):
            for i, x, y in rows:
                v = x + y
                tot += v
                if whole or self.exact:
                    p = i * fs if self.exact else (i + 0.5) * fs
                    j = math.floor(p / rstep + 1e-9) - k0
                    j = 0 if j < 0 else last if j > last else j
                    vol[j] += v
                    buy[j] += x
                    continue
                a, b = i * fs, (i + 1) * fs
                j0, j1 = math.floor(a / rstep + 1e-9) - k0, math.floor(b / rstep - 1e-9) - k0
                if j1 <= j0:
                    j = 0 if j0 < 0 else last if j0 > last else j0
                    vol[j] += v
                    buy[j] += x
                    continue
                for j in range(j0, j1 + 1):
                    r0, r1 = (k0 + j) * rstep, (k0 + j + 1) * rstep
                    f = max(0.0, min(b, r1) - max(a, r0)) / fs
                    jj = 0 if j < 0 else last if j > last else j
                    vol[jj] += v * f
                    buy[jj] += x * f
        return tot

    def _grid_of(self, t5: int, c):
        """Volume d'une tranche fermee par case de la grille des profils (0,03 %), garde en memoire (une tranche fermee ne change plus)."""
        hit = self._gcache.get(t5)
        if hit is not None and hit[0] is c:
            return hit[1]
        i0, b, s = c
        gi, agg = self._gi, {}
        for k in range(len(b)):
            v = b[k] + s[k]
            if v:
                i = i0 + k
                g = gi.get(i)
                if g is None:
                    g = gi[i] = VP_GRID.idx(self.price_of(i))
                agg[g] = agg.get(g, 0.0) + v
        out = tuple(agg.items())
        if len(self._gcache) > 50_000:
            self._gcache.clear()
        self._gcache[t5] = (c, out)
        return out

    def add_profile(self, t0: int, t1: int, prof) -> float:
        """Ajoute le volume de [t0, t1[ a un engine.vp.Profile (grille logarithmique de 0,03 %), chaque pas a son prix representatif."""
        tot = 0.0
        gi = self._gi
        bins = prof.bins
        lo, hi = prof.lo, prof.hi
        t = t0 - t0 % BUCKET
        if t < t0:
            t += BUCKET
        with self.lock:
            while t < t1:
                c = self.closed.get(t)
                if c is not None:
                    items = self._grid_of(t, c)
                else:
                    d = self.open.get(t) or {}
                    items = []
                    for i, (x, y) in d.items():
                        g = gi.get(i)
                        if g is None:
                            g = gi[i] = VP_GRID.idx(self.price_of(i))
                        items.append((g, x + y))
                for g, v in items:
                    bins[g] = bins.get(g, 0.0) + v
                    tot += v
                    lo = g if lo is None or g < lo else lo
                    hi = g if hi is None or g > hi else hi
                t += BUCKET
        prof.lo, prof.hi = lo, hi
        prof.version += 1
        return tot

    def moments(self, t0: int, t1: int):
        """(somme des volumes, somme prix x volume, somme prix^2 x volume) de [t0, t1[ : VWAP et ecart-type exacts au pas pres."""
        v = pv = p2v = 0.0
        for _, rows in self._items(t0, t1):
            for i, x, y in rows:
                p, q = self.price_of(i), x + y
                v += q
                pv += p * q
                p2v += p * p * q
        return v, pv, p2v

    # ---------- sauvegarde par jour ----------
    def day_blob(self, day_ms: int, extra: dict | None = None) -> bytes:
        """Les tranches et la couverture d'un jour UTC, en JSON (compresse par l'appelant) ; `extra` : champs ajoutes a l'en-tete."""
        a, b = day_ms, day_ms + DAY
        with self.lock:
            cov = [[max(x, a), min(y, b)] for x, y in self.cov if y > a and x < b]
        items = self._items(a, b)
        rows = []
        for t5, r in items:
            if not r:
                continue
            lo, hi = min(i for i, _, _ in r), max(i for i, _, _ in r)
            bb, ss = [0.0] * (hi - lo + 1), [0.0] * (hi - lo + 1)
            for i, x, y in r:
                bb[i - lo], ss[i - lo] = round(x, 8), round(y, 8)
            rows.append([t5, lo, bb, ss])
        head = {"v": FORMAT, "step": self.step, "tick": self.tick, "day": day_ms, "cov": cov}
        head.update(extra or {})
        head["b"] = rows
        return json.dumps(head, separators=(",", ":")).encode("utf-8")

    def load_blob(self, raw: bytes) -> dict:
        """Charge un jour sauvegarde (meme pas uniquement). Renvoie son en-tete ; ValueError si incompatible."""
        d = json.loads(raw.decode("utf-8"))
        if d.get("v") != FORMAT or abs(float(d.get("step", 0)) - self.step) > 1e-12 * max(1.0, self.step):
            raise ValueError("empreinte d'un autre format ou d'un autre pas")
        for t5, i0, bb, ss in d.get("b", []):
            self.put(int(t5), int(i0), bb, ss)
        for a, b in d.get("cov", []):
            self.cover(int(a), int(b))
        d.pop("b", None)
        return d


def from_trades(rows, step: float, tick: float) -> Footprint:
    """Empreinte d'une liste de transactions (prix, quantite, acheteur passif, t_ms) ; tranches fermees, sans couverture."""
    fp = Footprint(step, tick)
    for p, q, m, t in rows:
        fp.add(p, q, m, t)
    fp.seal(2 ** 62)
    return fp
