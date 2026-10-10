"""Confluences : zones ou plusieurs niveaux de SOURCES DIFFERENTES se regroupent (meme regle que le
tableau Pine : tri par prix, fenetre gloutonne <= tolerance, au moins 2 groupes distincts)."""
from dataclasses import dataclass, field


@dataclass
class Level:
    id: str
    name: str
    price: float
    group: str          # source : un profil / une periode = un seul groupe
    kind: str           # vwap | avwap | open | vp | hl | liq
    extra: dict = field(default_factory=dict)


def find_zones(levels, tol: float):
    """Renvoie des zones : {mid, lo, hi, members:[Level], groups:[...]}, triees par prix croissant."""
    lv = sorted(levels, key=lambda x: x.price)
    zones = []
    i = 0
    n = len(lv)
    while i < n:
        base = lv[i].price
        j = i
        while j + 1 < n and lv[j + 1].price - base <= tol:
            j += 1
        if j > i:
            members = lv[i:j + 1]
            groups = sorted({m.group for m in members})
            if len(groups) >= 2:
                zones.append({"mid": sum(m.price for m in members) / len(members),
                              "lo": members[0].price, "hi": members[-1].price,
                              "members": members, "groups": groups})
        i = j + 1
    return zones
