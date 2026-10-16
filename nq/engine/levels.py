"""Niveaux cles du jour et zones de confluence. Module PUR (lit un `Market`, ne modifie rien).

Niveaux (chacun avec un poids : plus il est eleve, plus le niveau « compte » dans une zone) :
  - veille (seance reguliere) : plus haut, plus bas, cloture, POC, VAH, VAL ;
  - nuit (Globex avant 9 h 30 ET) : plus haut / plus bas ; Asie ; Londres ;
  - seance du jour : ouverture 9 h 30, initial balance (plus haut / plus bas de la premiere heure), VWAP et bandes ±1 / ±2 ecarts-types,
    POC / VAH / VAL en formation (avant 9 h 30 : ceux de la journee Globex) ;
  - nombres ronds (centaines et cinquantaines de points) autour du prix.
Zone de confluence : plusieurs niveaux a moins de `zone_pts` points les uns des autres. Son score est la somme des poids. Ce n'est PAS un signal :
c'est une carte des endroits ou le prix a plusieurs raisons de reagir. Sa valeur reelle sera MESUREE (comme pour les zones du terminal crypto)
avant qu'on s'appuie dessus."""
from . import clock, vp
from .instruments import MNQ, NQ

GROUPS = {"veille": "Veille", "nuit": "Nuit", "seance": "Séance", "rond": "Ronds"}

W = {                                        # poids de depart (a mesurer et ajuster)
    "pdh": 3.0, "pdl": 3.0, "pdc": 2.0, "ppoc": 3.0, "pvah": 2.5, "pval": 2.5,
    "onh": 2.5, "onl": 2.5, "asih": 1.5, "asil": 1.5, "lonh": 1.5, "lonl": 1.5,
    "open": 2.0, "ibh": 2.5, "ibl": 2.5, "vwap": 3.0, "vp1": 1.5, "vm1": 1.5, "vp2": 1.0, "vm2": 1.0,
    "poc": 2.5, "vah": 2.0, "val": 2.0, "r100": 1.5, "r50": 1.0,
}


def _round_levels(price: float, span: float = 200.0) -> list:
    out = []
    lo, hi = price - span, price + span
    k = int(lo // 50) * 50
    while k <= hi:
        if k >= lo:
            out.append((f"Rond {k:g}", float(k), "r100" if k % 100 == 0 else "r50"))
        k += 50
    return out


def build(mk, zone_pts: float = 6.0, min_zone_score: float = 4.0, round_span: float = 200.0, stats_cache: dict | None = None) -> dict:
    """Niveaux et zones autour du prix. `mk` : Market. Renvoie {"price", "levels": [...], "zones": [...]} (niveaux tries du haut vers le bas).
    `stats_cache` : passe au calcul de profil (vp.stats) pour eviter de recalculer le profil de la veille a chaque appel (backtest)."""
    with mk.lock:
        price = mk.price
        if price is None:
            return {"price": None, "levels": [], "zones": []}
        now = mk.now_ms()                                          # heure de la derniere transaction : le samedi, la journee est celle du vendredi
        day = clock.trading_day(now)
        tick = mk.inst.tick
        lv: list = []

        def add(name, p, kind, group):
            if p is not None:
                lv.append({"name": name, "price": round(float(p), 4), "kind": kind, "group": group, "w": W[kind]})

        prev = mk.prev_day(day)
        if prev:
            o = mk.window_ohlc(prev, "rth")
            if o:
                add("High veille", o["h"], "pdh", "veille")
                add("Low veille", o["l"], "pdl", "veille")
                add("Clôture veille", o["c"], "pdc", "veille")
            lad = mk.ladder(prev, "rth")
            st = vp.stats(lad, min_row_ticks=4, cache=stats_cache) if lad else None
            if st:
                add("POC veille", st["poc"], "ppoc", "veille")
                add("VAH veille", st["vah"], "pvah", "veille")
                add("VAL veille", st["val"], "pval", "veille")
        for name, key_hi, key_lo, hn, ln, grp in (("on", "onh", "onl", "High nuit", "Low nuit", "nuit"), ("asia", "asih", "asil", "High Asie", "Low Asie", "nuit"),
                                                    ("london", "lonh", "lonl", "High Londres", "Low Londres", "nuit")):
            o = mk.window_ohlc(day, name)
            if o:
                add(hn, o["h"], key_hi, grp)
                add(ln, o["l"], key_lo, grp)
        rth_open = clock.window(day, "rth")[0]
        in_rth_or_after = now >= rth_open
        o = mk.window_ohlc(day, "rth")
        if o:
            add("Ouverture 9h30", o["o"], "open", "seance")
        ib = mk.window_ohlc(day, "ib")
        if ib:
            add("IB High", ib["h"], "ibh", "seance")
            add("IB Low", ib["l"], "ibl", "seance")
        lad = mk.ladder(day, "rth") if in_rth_or_after else mk.ladder(day, "gx")
        if lad is None and not in_rth_or_after:
            lad = mk.ladder(day, "gx")
        if lad is not None and not lad.empty():
            m, sd = lad.vwap, lad.sd
            label = "VWAP" if in_rth_or_after else "VWAP Globex"
            add(label, m, "vwap", "seance")
            if sd:
                add("VWAP +1σ", m + sd, "vp1", "seance")
                add("VWAP −1σ", m - sd, "vm1", "seance")
                add("VWAP +2σ", m + 2 * sd, "vp2", "seance")
                add("VWAP −2σ", m - 2 * sd, "vm2", "seance")
            st = vp.stats(lad, min_row_ticks=4, cache=stats_cache)
            if st:
                suffix = "séance" if in_rth_or_after else "Globex"
                add(f"POC {suffix}", st["poc"], "poc", "seance")
                add(f"VAH {suffix}", st["vah"], "vah", "seance")
                add(f"VAL {suffix}", st["val"], "val", "seance")
        for name, p, kind in _round_levels(price, round_span):
            add(name, p, kind, "rond")
        lv = merge_same(lv, tick)
        lv.sort(key=lambda x: -x["price"])
        for x in lv:
            x["dist"] = round(x["price"] - price, 4)
            x["usdNQ"] = round(abs(x["dist"]) * NQ.point_value, 2)
            x["usdMNQ"] = round(abs(x["dist"]) * MNQ.point_value, 2)
        return {"price": price, "day": day, "prevDay": prev, "levels": lv, "zones": zones(lv, price, zone_pts, min_zone_score)}


def merge_same(levels: list, tick: float) -> list:
    """Fusionne les niveaux du MEME groupe au meme prix (a un demi-tick pres) : le plus haut de la nuit EST souvent le plus haut de Londres, ce
    n'est pas deux raisons de reagir mais une seule. Le niveau garde le plus fort poids et les deux noms (« High nuit = High Londres »)."""
    out: list = []
    for x in sorted(levels, key=lambda x: (x["group"], x["price"])):
        prev = out[-1] if out else None
        if prev and prev["group"] == x["group"] and abs(prev["price"] - x["price"]) < tick / 2:
            if x["w"] > prev["w"]:
                prev["w"], prev["kind"] = x["w"], x["kind"]
            prev["name"] = f"{prev['name']} = {x['name']}"
            continue
        out.append(dict(x))
    return out


def zones(levels: list, price: float, zone_pts: float = 6.0, min_score: float = 4.0) -> list:
    """Groupes de niveaux a moins de `zone_pts` points (du premier au dernier du groupe). Garde ceux qui ont au moins 2 niveaux ET un score
    d'au moins `min_score`. Tries du plus haut au plus bas ; `rank` = rang par score."""
    asc = sorted(levels, key=lambda x: x["price"])
    groups: list = []
    for x in asc:
        if groups and x["price"] - groups[-1][0]["price"] <= zone_pts:
            groups[-1].append(x)
        else:
            groups.append([x])
    out = []
    for g in groups:
        if len(g) < 2:
            continue
        score = sum(x["w"] for x in g)
        if score < min_score:
            continue
        wsum = sum(x["w"] * x["price"] for x in g) / score
        out.append({"lo": g[0]["price"], "hi": g[-1]["price"], "mid": round(wsum, 4), "score": round(score, 2), "n": len(g),
                    "names": [x["name"] for x in reversed(g)], "dist": round(wsum - price, 4), "groups": sorted({x["group"] for x in g})})
    for r, z in enumerate(sorted(out, key=lambda z: -z["score"]), 1):
        z["rank"] = r
    out.sort(key=lambda z: -z["mid"])
    return out


def nearest(levels: list, price: float, n: int = 3) -> dict:
    """Les n niveaux les plus proches au-dessus et en dessous du prix (hors nombres ronds, qui ne sont pas de vrais niveaux de marche)."""
    real = [x for x in levels if x["group"] != "rond"]
    up = sorted([x for x in real if x["price"] > price], key=lambda x: x["price"])[:n]
    dn = sorted([x for x in real if x["price"] < price], key=lambda x: -x["price"])[:n]
    return {"above": up, "below": dn}
