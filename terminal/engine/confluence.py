"""Confluences : zones ou plusieurs niveaux de SOURCES DIFFERENTES se regroupent (meme regle que le
tableau Pine : tri par prix, fenetre gloutonne <= tolerance, au moins 2 groupes distincts)."""
from __future__ import annotations
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


# ---------- V28 : note de confluence sur 14 ----------
# Sept piliers, chacun noté 0, 1 ou 2 : un niveau de la journée vaut 1 point, un niveau de la semaine, du mois ou de l'année en vaut 2 ;
# deux niveaux différents dans le même pilier valent aussi 2. Les nombres ronds ne comptent pas. 9/14 demande donc plusieurs piliers
# de grande unité de temps au même prix : c'est le seuil d'affichage par défaut du graphique (réglable).
PILLARS = (("vwap", "VWAP"), ("avwap", "VWAP ancrés"), ("vp", "Profils de volume"), ("virgin", "POC vierges et TPO"),
           ("hl", "Plus hauts / plus bas"), ("open", "Ouvertures"), ("liq", "Liquidité"))
GRADE_MAX = 2 * len(PILLARS)


def _member_points(lv) -> tuple[str, float] | None:
    """(pilier, poids 1 ou 2) d'un niveau membre d'une zone ; None s'il ne compte pas (nombre rond)."""
    g, k, ex = lv.group, lv.kind, lv.extra or {}
    if k == "vwap":
        return "vwap", 2 if g in ("mVWAP", "yVWAP") else 1
    if k == "band":
        return "vwap", 1
    if k == "avwap":
        return "avwap", 1
    if k in ("vp", "xvp"):
        return "vp", 1 if g in ("dVP", "pdVP") else 2
    if k == "npoc":
        return "virgin", 2 if " S-" in f" {lv.name}" else 1
    if k == "tpo":
        return "virgin", 2 if (ex.get("tpo") or {}).get("kind") in ("W", "M") else 1
    if k == "hl":
        return "hl", 1 if g == "PDHL" else 2
    if k == "open":
        return "open", 1 if g == "dOpen" else 2
    if k == "liq":
        p = ex.get("pool") or {}
        strong = bool(p.get("magnet")) or ((p.get("imp") or {}).get("score") or 0) >= 70
        return "liq", 2 if strong else 1
    return None


def grade(members) -> dict:
    """Note sur 14 d'une zone : {"grade", "max", "parts": [{"key", "name", "pts", "what": [noms]}]} (piliers présents seulement)."""
    acc: dict = {}
    for lv in members:
        mp = _member_points(lv)
        if mp is None:
            continue
        key, w = mp
        a = acc.setdefault(key, {"w": 0.0, "groups": set(), "what": []})
        a["w"] = max(a["w"], w)
        a["groups"].add(lv.group)
        if lv.name not in a["what"]:
            a["what"].append(lv.name)
    parts = []
    for key, name in PILLARS:
        a = acc.get(key)
        if not a:
            continue
        pts = int(min(2, a["w"] + (1 if len(a["groups"]) >= 2 else 0)))
        parts.append({"key": key, "name": name, "pts": pts, "what": a["what"][:4]})
    return {"grade": sum(p["pts"] for p in parts), "max": GRADE_MAX, "parts": parts}
