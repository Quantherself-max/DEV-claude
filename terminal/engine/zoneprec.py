"""Precision des zones de confluence (V19). Une zone regroupe des niveaux de sources differentes ; sa largeur brute va du plus bas au plus haut
de ses niveaux. Pour savoir OU agir dans la zone, on calcule :
  - le PRIX CLE : mediane des prix de ses niveaux, chaque niveau pese selon son echelle de temps et sa famille (meme baremes que les idees :
    jour 1, semaine 2, mois 3, annee 4 ; VWAP et VWAP ancres x1,6 ; profils de volume x1,2...) ;
  - le COEUR : la partie de la zone qui porte la moitie centrale de ce poids (du 25e au 75e centile pondere) ;
  - le PRIX LE PLUS ECHANGE dans la zone (et un peu autour) sur les 14 derniers jours, en bougies de 5 minutes reparties selon leur trajet :
    le prix ou le marche a reellement fait affaire ;
  - la LARGEUR en ATR et un libelle de precision.
Les membres des zones ne changent pas : les idees de trade restent calculees exactement comme avant. Module PUR."""
import math

from .sessionvp import spread


def wquantile(pts, q):
    """Quantile pondere de [(prix, poids)] tries par prix : chaque niveau occupe une part du poids total centree sur son prix, interpolation
    lineaire entre deux niveaux voisins."""
    tot = sum(w for _, w in pts)
    if not pts or tot <= 0:
        return None
    acc, mids = 0.0, []
    for _, w in pts:
        mids.append((acc + w / 2) / tot)
        acc += w
    if q <= mids[0]:
        return pts[0][0]
    if q >= mids[-1]:
        return pts[-1][0]
    for i in range(1, len(pts)):
        if q <= mids[i]:
            f = (q - mids[i - 1]) / (mids[i] - mids[i - 1])
            return pts[i - 1][0] + f * (pts[i][0] - pts[i - 1][0])
    return pts[-1][0]


class FineProfile:
    """Profil de volume fin des derniers jours, autour du prix (pas ~0,02 % du prix), recalcule quand une bougie 5 min se ferme."""

    def __init__(self, bars, price: float, span_pct: float = 0.12, step_pct: float = 0.0002):
        self.step = max(price * step_pct, 1e-12)
        lo, hi = price * (1 - span_pct), price * (1 + span_pct)
        self.k0 = math.floor(lo / self.step)
        self.n = max(1, math.floor(hi / self.step) - self.k0 + 1)
        self.vol, self.buy = [0.0] * self.n, [0.0] * self.n
        for k in bars:
            if k.h < lo or k.l > hi:
                continue
            spread(k, self.k0, self.n, self.step, self.vol, self.buy)

    def peak(self, a: float, b: float):
        """(prix le plus echange, part du volume de [a, b] a ce prix) entre a et b ; None sans volume."""
        j0 = max(0, math.floor(a / self.step) - self.k0)
        j1 = min(self.n - 1, math.floor(b / self.step) - self.k0)
        if j1 < j0:
            return None
        seg = self.vol[j0:j1 + 1]
        tot = sum(seg)
        if tot <= 0:
            return None
        # leger lissage (3 lignes) pour ne pas tomber sur une ligne isolee
        sm = [sum(seg[max(0, i - 1):i + 2]) for i in range(len(seg))]
        i = max(range(len(seg)), key=lambda j: sm[j])
        return (self.k0 + j0 + i + 0.5) * self.step, seg[i] / tot


def refine(zone: dict, members: list, weights: list, atr: float, fine: FineProfile | None = None) -> dict:
    """Champs de precision d'une zone : key, core [bas, haut], vpoc, vpocShare, widthAtr, coreAtr, precision."""
    pts = sorted(zip((m["price"] for m in members), (max(0.25, w) for w in weights)))
    key = wquantile(pts, 0.5)
    if len(pts) <= 2:
        core = [pts[0][0], pts[-1][0]]
    else:
        core = [wquantile(pts, 0.25), wquantile(pts, 0.75)]
    out = {"key": key, "core": core, "widthAtr": (zone["hi"] - zone["lo"]) / atr if atr else None,
           "coreAtr": (core[1] - core[0]) / atr if atr else None}
    if fine is not None:                                     # dans la zone, elargie a au moins +/- 0,08 ATR autour du prix cle
        a, b = min(zone["lo"], key - 0.08 * atr), max(zone["hi"], key + 0.08 * atr)
        pk = fine.peak(a, b)
        if pk:
            out["vpoc"], out["vpocShare"] = pk
    w = out["coreAtr"]
    out["precision"] = None if w is None else "fine" if w <= 0.25 else "moyenne" if w <= 0.6 else "large"
    return out
