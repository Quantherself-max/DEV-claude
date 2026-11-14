"""Profil de volume exact (V45) : POC, VAH, VAL à partir des transactions réelles.

Le volume de chaque transaction est ajouté à la ligne de son prix (entiers : aucune répartition supposée, aucune erreur de somme).
  POC  : la ligne la plus échangée ; à égalité, la plus proche du milieu de la fourchette, puis la plus basse (règle fixe, annoncée).
  Zone de valeur (70 % par défaut) : méthode classique du Market Profile. On part du POC ; à chaque tour on compare le volume des DEUX
         lignes juste au-dessus à celui des deux lignes juste en dessous, on ajoute la paire la plus lourde (à égalité : celle du haut),
         jusqu'à atteindre le pourcentage voulu. La comparaison au pourcentage se fait en entiers : volume × 100 >= total × pourcentage.
  VAH / VAL : bord haut de la plus haute ligne retenue, bord bas de la plus basse.
Le pas des lignes est un multiple entier du pas de cotation : avec un multiple de 1, chaque prix est exact.
Module PUR."""
from __future__ import annotations
from fractions import Fraction

from .num import UNIT, from_units


class ExactProfile:
    """Volume par ligne de prix. `row_u` : hauteur d'une ligne en unités de prix (10^-8). Ligne k = prix [k × row_u, (k + 1) × row_u[."""

    def __init__(self, row_u: int):
        if row_u <= 0:
            raise ValueError("hauteur de ligne nulle")
        self.row = int(row_u)
        self.buy: dict[int, int] = {}
        self.sell: dict[int, int] = {}
        self.n = 0

    def add(self, px_u: int, qty_u: int, side: int) -> None:
        k = px_u // self.row
        d = self.buy if side > 0 else self.sell
        d[k] = d.get(k, 0) + qty_u
        self.n += 1

    def add_row(self, k: int, buy_u: int, sell_u: int) -> None:
        """Ligne déjà comptée (empreinte des transactions archivées)."""
        if buy_u:
            self.buy[k] = self.buy.get(k, 0) + int(buy_u)
        if sell_u:
            self.sell[k] = self.sell.get(k, 0) + int(sell_u)

    def merge(self, other: "ExactProfile") -> None:
        if other.row != self.row:
            raise ValueError("profils de pas différents")
        for k, v in other.buy.items():
            self.buy[k] = self.buy.get(k, 0) + v
        for k, v in other.sell.items():
            self.sell[k] = self.sell.get(k, 0) + v
        self.n += other.n

    def rows(self, group: int = 1) -> tuple[int, list, list]:
        """(indice de la première ligne, volumes, deltas) en lignes contiguës de `group` lignes de base."""
        keys = set(self.buy) | set(self.sell)
        if not keys:
            return 0, [], []
        lo, hi = min(keys) // group, max(keys) // group
        vol, dlt = [0] * (hi - lo + 1), [0] * (hi - lo + 1)
        for k, v in self.buy.items():
            vol[k // group - lo] += v
            dlt[k // group - lo] += v
        for k, v in self.sell.items():
            vol[k // group - lo] += v
            dlt[k // group - lo] -= v
        return lo, vol, dlt

    def levels(self, va_pct: int = 70, group: int = 1) -> dict | None:
        """POC, VAH, VAL (prix en unités de 10^-8 et en Decimal), volume total, part exacte du volume dans la zone de valeur."""
        lo, vol, dlt = self.rows(group)
        if not vol:
            return None
        return value_area(vol, lo, self.row * group, va_pct, dlt)


def value_area(vol: list, k0: int, row_u: int, va_pct: int = 70, dlt: list | None = None) -> dict:
    """Voir l'en-tête. `vol` : volumes des lignes contiguës à partir de la ligne k0 ; `row_u` : hauteur d'une ligne (unités de prix)."""
    n = len(vol)
    total = sum(vol)
    if total <= 0:
        raise ValueError("profil vide")
    best = max(vol)
    cands = [i for i, v in enumerate(vol) if v == best]
    mid2 = n - 1                                             # deux fois l'indice du milieu (évite les demi-entiers)
    poc = min(cands, key=lambda i: (abs(2 * i - mid2), i))
    acc, up, dn = best, poc, poc
    while acc * 100 < total * va_pct and (up < n - 1 or dn > 0):
        up_v = sum(vol[up + 1:up + 3]) if up < n - 1 else -1
        dn_v = sum(vol[max(0, dn - 2):dn]) if dn > 0 else -1
        if up_v >= dn_v:
            acc += up_v
            up = min(n - 1, up + 2)
        else:
            acc += dn_v
            dn = max(0, dn - 2)
    poc_u = (k0 + poc) * row_u
    vah_u, val_u = (k0 + up + 1) * row_u, (k0 + dn) * row_u
    out = {"poc_u": poc_u, "pocMid_u": poc_u + row_u // 2, "vah_u": vah_u, "val_u": val_u, "row_u": row_u,
           "poc": from_units(poc_u), "vah": from_units(vah_u), "val": from_units(val_u),
           "total": total, "inValue": acc, "share": Fraction(acc, total), "pocVolume": best, "rows": n, "ties": len(cands)}
    if dlt is not None:
        out["delta"] = sum(dlt)
        out["pocDelta"] = dlt[poc]
    return out


def nodes(vol: list, k0: int, row_u: int, span: int = 3, min_pct: int = 30) -> dict:
    """Nœuds de fort volume (HVN) et creux (LVN) : maximum (ou minimum) strict sur `span` lignes de chaque côté. Un HVN doit peser au
    moins min_pct % du POC ; un LVN au plus (100 - min_pct) %. Prix = bord bas de la ligne, en unités."""
    best = max(vol) if vol else 0
    hv, lv = [], []
    for i in range(span, len(vol) - span):
        x = vol[i]
        around = vol[i - span:i] + vol[i + 1:i + span + 1]
        if x * 100 >= best * min_pct and all(x > y for y in around):
            hv.append(((k0 + i) * row_u, x))
        if x * 100 <= best * (100 - min_pct) and all(x < y for y in around):
            lv.append(((k0 + i) * row_u, x))
    return {"hvn": hv, "lvn": lv}


def from_buckets(items, step_f: float, tick_u: int, scale_qty: int = UNIT) -> ExactProfile:
    """Profil à partir d'une empreinte déjà regroupée : `items` = [(indice de pas, achats, ventes)] (engine.footprint), `step_f` le pas de
    l'empreinte en dollars. Les volumes y sont des sommes flottantes de quantités toutes multiples du pas de quantité : arrondies à
    10^-8, elles redonnent la somme exacte (l'erreur d'une somme flottante de quelques milliers de transactions est mille fois plus
    petite). Le pas de l'empreinte doit être un multiple du pas de cotation."""
    row_u = int(round(step_f * UNIT))
    if tick_u > 0 and row_u % tick_u:
        raise ValueError("le pas de l'empreinte n'est pas un multiple du pas de cotation")
    p = ExactProfile(row_u)
    for i, b, s in items:
        p.add_row(int(i), int(round(b * scale_qty)), int(round(s * scale_qty)))
    return p
