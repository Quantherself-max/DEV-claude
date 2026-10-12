"""Footprint : volume echange a chaque prix, acheteurs et vendeurs agressifs separes. Module PUR.

Format d'une ligne : fp[indice de tick] = [vendeur agressif (au bid), acheteur agressif (a l'ask)].
`Ladder` cumule des lignes sur une SEANCE entiere (jour, seance reguliere...) et tient les sommes qui donnent le VWAP et son ecart-type
sans reparcourir les barres. `imbalances` repere les desequilibres « en diagonale » du footprint : l'acheteur du prix P est compare au
vendeur du prix juste en dessous (P - 1 tick), parce que c'est contre celui-la que l'ordre au marche acheteur s'est execute ; l'inverse pour
les vendeurs. Un desequilibre est « empile » quand il se repete sur plusieurs prix consecutifs : zone ou un camp a pousse sans resistance."""
import math


class Ladder:
    __slots__ = ("tick", "rows", "s0", "s1", "s2", "bv", "sv")

    def __init__(self, tick: float):
        self.tick = tick
        self.rows: dict = {}
        self.s0 = self.s1 = self.s2 = 0.0           # somme de q, q x indice, q x indice^2 (en INDICES de tick : petits nombres, precis)
        self.bv = self.sv = 0.0

    def add_trade(self, idx: int, side: int, q: float) -> None:
        r = self.rows.get(idx)
        if r is None:
            r = self.rows[idx] = [0.0, 0.0]
        r[1 if side > 0 else 0] += q
        if side > 0:
            self.bv += q
        else:
            self.sv += q
        self.s0 += q
        self.s1 += q * idx
        self.s2 += q * idx * idx

    def add_rows(self, fp: dict) -> None:
        for idx, (s, b) in fp.items():
            r = self.rows.get(idx)
            if r is None:
                r = self.rows[idx] = [0.0, 0.0]
            r[0] += s
            r[1] += b
            q = s + b
            self.sv += s
            self.bv += b
            self.s0 += q
            self.s1 += q * idx
            self.s2 += q * idx * idx

    def empty(self) -> bool:
        return not self.rows

    @property
    def volume(self) -> float:
        return self.s0

    @property
    def delta(self) -> float:
        return self.bv - self.sv

    @property
    def lo(self):
        return self.tick * min(self.rows) if self.rows else None

    @property
    def hi(self):
        return self.tick * max(self.rows) if self.rows else None

    @property
    def vwap(self):
        return self.s1 / self.s0 * self.tick if self.s0 > 0 else None

    @property
    def sd(self):
        """Ecart-type du prix pondere par le volume (en points)."""
        if self.s0 <= 0:
            return None
        m = self.s1 / self.s0
        return math.sqrt(max(self.s2 / self.s0 - m * m, 0.0)) * self.tick

    def copy(self) -> "Ladder":
        c = Ladder(self.tick)
        c.rows = {k: list(r) for k, r in self.rows.items()}
        c.s0, c.s1, c.s2, c.bv, c.sv = self.s0, self.s1, self.s2, self.bv, self.sv
        return c


def poc_of(fp: dict):
    """Indice de tick du plus gros volume (a egalite : le plus proche du milieu de la plage)."""
    if not fp:
        return None
    mid = (min(fp) + max(fp)) / 2.0
    return max(fp, key=lambda i: (fp[i][0] + fp[i][1], -abs(i - mid)))


def delta_of(fp: dict) -> float:
    return sum(b - s for s, b in fp.values())


def imbalances(fp: dict, ratio: float = 3.0, min_vol: float = 1.0, stack: int = 3) -> dict:
    """Desequilibres diagonaux d'une barre (ou d'une seance).

    Acheteur au prix P : volume a l'ask de P >= ratio x volume au bid de P - 1 tick (et au moins `min_vol`).
    Vendeur au prix P  : volume au bid de P >= ratio x volume a l'ask de P + 1 tick (et au moins `min_vol`).
    Le prix le plus bas n'a pas de voisin du dessous (et le plus haut pas de voisin du dessus) : il n'a rien a comparer, il n'est jamais signale
    (un « desequilibre » contre un voisin absent ne dirait rien). Un prix SANS volume au milieu de la barre compte, lui, pour zero : c'est une vraie absence.
    Renvoie {"buy": [indices], "sell": [indices], "stacks": [(+1|-1, indice bas, indice haut), ...]} ; une pile = `stack` prix consecutifs ou plus."""
    buy, sell = [], []
    if not fp:
        return {"buy": buy, "sell": sell, "stacks": []}
    lo, hi = min(fp), max(fp)
    for idx in sorted(fp):
        s, b = fp[idx]
        below = fp.get(idx - 1)
        above = fp.get(idx + 1)
        if idx > lo and b >= min_vol and b >= ratio * (below[0] if below else 0.0):
            buy.append(idx)
        if idx < hi and s >= min_vol and s >= ratio * (above[1] if above else 0.0):
            sell.append(idx)
    stacks = []
    for side, arr in ((1, buy), (-1, sell)):
        run = []
        for idx in arr + [None]:
            if run and (idx is None or idx != run[-1] + 1):
                if len(run) >= stack:
                    stacks.append((side, run[0], run[-1]))
                run = []
            if idx is not None:
                run.append(idx)
    return {"buy": buy, "sell": sell, "stacks": stacks}
