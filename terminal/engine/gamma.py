"""Exposition gamma des options BTC (V26) croisee avec les VWAP et les VWAP ancres ; V38 : choix des echeances et des bourses, strike au plus
fort gamma, max pain, mouvement attendu, flux de couverture estimes et zones de gamma positif / negatif.

Le calcul (data/derivs.py, gex_view) part du carnet public de Deribit, deja lu par le terminal toutes les 5 minutes : interet ouvert,
volatilite implicite et prix a terme de chaque option. Ici : les niveaux qui comptent (mur de calls au-dessus du prix, mur de puts en
dessous, bascule du gamma, plus gros strikes), et pour chacun les VWAP et VWAP ancres tout proches (moins de 0,35 fois l'amplitude d'une
bougie d'une heure, ou 0,25 % du prix) : un strike charge qui tombe sur un VWAP important est un niveau que deux mecanismes differents
surveillent.

Limites, dites partout ou c'est affiche :
  - le sens des positions des teneurs de marche est une HYPOTHESE (acheteurs des calls, vendeurs des puts du public) ; sur BTC, les produits
    de rendement qui vendent des calls peuvent l'inverser en partie ;
  - Deribit porte l'essentiel des options BTC ; depuis la V38, Bybit et OKX sont ajoutes quand ils repondent (CME et Binance n'y sont pas) ;
  - aucun historique gratuit des options par strike : l'effet n'est PAS mesure sur le passe. Le terminal enregistre ces niveaux toutes les
    15 minutes (data_local/history/derivs/BTCUSDT.csv) pour pouvoir le mesurer plus tard. Rien de tout cela n'entre dans le score des idees."""
from __future__ import annotations

VWAP_NAMES = {"dVWAP": "VWAP du jour", "wVWAP": "VWAP de la semaine", "mVWAP": "VWAP du mois", "yVWAP": "VWAP de l'année"}
STALE_MS = 30 * 60_000


def level_name(lv: dict) -> str:
    n = lv.get("name") or ""
    if lv.get("kind") == "vwap":
        return VWAP_NAMES.get(n, n)
    return n.replace("AVWAP", "VWAP ancré", 1)


SCOPE_NAMES = {"all": "toutes les échéances", "week": "échéances des 7 prochains jours", "front": "prochaine échéance"}
SRC_NAMES = {"all": "toutes les bourses lues", "deribit": "Deribit seul"}


def pick(opt: dict, scope: str = "all", src: str = "all") -> tuple[dict | None, str, str]:
    """Vue de gamma choisie (V38 : source et echeances) ; retombe sur Deribit si les autres bourses manquent, sur l'ancienne forme sinon."""
    scope = scope if scope in SCOPE_NAMES else "all"
    src = src if src in SRC_NAMES else "all"
    sets = opt.get("gexSets")
    if not sets:
        return (opt.get("gex"), "all", "deribit")
    g = (sets.get(src) or {}).get(scope)
    if g and src == "all" and len(g.get("sources") or []) < 2:
        src = "deribit"
        g = (sets.get("deribit") or {}).get(scope) or g
    return g, scope, src


def max_pain_level(opt: dict, g: dict, scope: str) -> dict | None:
    """Max pain : de la prochaine echeance si on regarde la prochaine echeance, sinon de la plus grosse des 4 prochaines (en interet ouvert)."""
    exps = [e for e in opt.get("expiries") or [] if e.get("maxPain")]
    if not exps:
        return None
    if scope == "front" and g.get("frontExpiry"):
        e = next((x for x in exps if x["expiry"] == g["frontExpiry"]), None)
    else:
        e = max(exps, key=lambda x: x.get("oiUsd") or 0.0)
    return e and {"price": e["maxPain"], "expiry": e["expiry"], "oiUsd": e.get("oiUsd")}


def key_levels(g: dict, mp: dict | None = None, em: dict | None = None) -> list[dict]:
    """Niveaux de gamma a surveiller, du plus haut au plus bas (un strike n'apparait qu'une fois)."""
    out, seen = [], set()

    def add(price, kind, label, gex=None, **kw):
        if price is None:
            return
        k = round(float(price), 2)
        if kind in ("callwall", "putwall", "absgamma", "strike") and k in seen:
            if kind == "absgamma":                                       # le strike au plus fort gamma est deja un mur : on le dit sur le mur
                for o in out:
                    if round(o["price"], 2) == k:
                        o["alsoAbs"] = True
            return
        if kind in ("callwall", "putwall", "absgamma", "strike"):
            seen.add(k)
        out.append({"price": float(price), "kind": kind, "label": label, "gex": gex, **kw})
    add(g.get("callWall"), "callwall", "Mur de calls", g.get("callWallGex"))
    add(g.get("putWall"), "putwall", "Mur de puts", g.get("putWallGex"))
    add(g.get("absGamma"), "absgamma", "Plus fort gamma", g.get("absGammaGex"))
    add(g.get("flip"), "flip", "Bascule du gamma")
    if mp:
        add(mp["price"], "maxpain", "Max pain", None, expiry=mp.get("expiry"))
    if em and em.get("day"):
        add(em["day"]["up"], "emup", "Haut du mouvement attendu 24 h", None, pct=em["day"]["pct"])
        add(em["day"]["down"], "emdn", "Bas du mouvement attendu 24 h", None, pct=em["day"]["pct"])
    for t in g.get("top") or []:
        add(t["strike"], "strike", "Strike chargé", t["net"])
    return sorted(out, key=lambda x: -x["price"])


def confluences(keys: list[dict], levels: list[dict], price: float, atr: float | None) -> list[dict]:
    """Pour chaque niveau de gamma : VWAP et VWAP ancres a moins de tol (0,35 ATR 1 h ou 0,25 % du prix, le plus large)."""
    tol = max(0.35 * (atr or 0.0), 0.0025 * price) if price else 0.0
    vw = [l for l in levels or [] if l.get("kind") in ("vwap", "avwap") and l.get("price")]
    for k in keys:
        near = sorted(({"name": level_name(l), "price": l["price"], "distPct": (l["price"] / k["price"] - 1.0) * 100.0} for l in vw
                       if abs(l["price"] - k["price"]) <= tol), key=lambda x: abs(x["distPct"]))
        k["vwap"] = near[:3]
        k["distPct"] = (k["price"] / price - 1.0) * 100.0 if price else None
    return keys


def zones(curve: list, flips: list[float]) -> list[dict]:
    """Bandes de prix ou le gamma total est positif ou negatif (entre deux bascules), pour les colorer sur le graphique."""
    if not curve:
        return []
    cuts = [curve[0][0]] + [f for f in flips if curve[0][0] < f < curve[-1][0]] + [curve[-1][0]]
    out = []
    for lo, hi in zip(cuts, cuts[1:]):
        mid = (lo + hi) / 2.0
        v = min(curve, key=lambda p: abs(p[0] - mid))[1]
        out.append({"lo": lo, "hi": hi, "sign": 1 if v > 0 else -1 if v < 0 else 0})
    return out


def brief(opt: dict | None, levels: list[dict], price: float, atr: float | None, now_ms: int, scope: str = "all", src: str = "all") -> dict | None:
    """Resume pour le graphique et la Lecture (BTC seulement) ; scope : all, week ou front ; src : all ou deribit."""
    if not opt:
        return None
    if not opt.get("gex"):
        return {"error": opt.get("gexError") or "gamma indisponible"}
    g, scope, src = pick(opt, scope, src)
    if not g:
        return {"error": f"aucune option pour : {SCOPE_NAMES[scope]}"}
    em = (opt.get("gexSets") or {}).get("em")
    mp = max_pain_level(opt, g, scope)
    px_ = price or g["spot"]
    keys = confluences(key_levels(g, mp, em), levels, px_, atr)
    t = opt.get("t")
    sign = 1 if g["total"] > 0 else -1 if g["total"] < 0 else 0
    above_flip = None if g.get("flip") is None or not price else price > g["flip"]
    flips = g.get("flips") or ([g["flip"]] if g.get("flip") is not None else [])
    return {"t": t, "stale": bool(t and now_ms - t > STALE_MS), "spot": g["spot"], "price": px_, "total": g["total"], "sign": sign, "flip": g.get("flip"),
            "flips": flips, "aboveFlip": above_flip, "flipDistPct": (px_ / g["flip"] - 1.0) * 100.0 if g.get("flip") else None,
            "callWall": g.get("callWall"), "putWall": g.get("putWall"), "absGamma": g.get("absGamma"), "maxPain": mp, "em": em,
            "flows": g.get("flows") or [], "levels": keys, "zones": zones(g.get("curve") or [], flips),
            "strikes": g.get("strikes") or [], "curve": g.get("curve") or [], "nearShare": g.get("nearShare"), "n": g.get("n"), "expiries": g.get("expiries"),
            "frontExpiry": g.get("frontExpiry"), "sources": g.get("sources") or [{"ex": "Deribit", "share": 1.0}], "scope": scope, "src": src,
            "scopeName": SCOPE_NAMES[scope], "srcName": SRC_NAMES[src], "othersError": opt.get("gexOthersError")}


def musd(v: float | None) -> str:
    if v is None:
        return "-"
    a = abs(v)
    s = f"{a / 1e9:.2f} Md$" if a >= 1e9 else f"{a / 1e6:.1f} M$" if a >= 1e6 else f"{a / 1e3:.0f} k$"
    return ("+" if v > 0 else "−" if v < 0 else "") + s.replace(".", ",")


def px(v: float | None) -> str:
    return "-" if v is None else f"{v:,.0f}".replace(",", " ")


def flow_at(b: dict, pct: float) -> dict | None:
    return next((f for f in b.get("flows") or [] if abs(f["pct"] - pct) < 1e-9), None)


def flow_text(v: float) -> str:
    """Achat (+) ou vente (-) des teneurs de marche, en clair."""
    return f"{'achat' if v > 0 else 'vente'} d'environ {musd(abs(v))[1:] if v else '0 $'}"


def regime_text(b: dict) -> str:
    if b["sign"] > 0:
        txt = ("Gamma positif au prix (estimé) : les teneurs de marché vendraient les hausses et achèteraient les baisses : mouvements plutôt "
               "amortis, le prix a tendance à être retenu par les gros strikes.")
    elif b["sign"] < 0:
        txt = ("Gamma négatif au prix (estimé) : les teneurs de marché suivraient le mouvement (achat dans les hausses, vente dans les baisses) : "
               "mouvements plutôt amplifiés.")
    else:
        txt = "Gamma proche de zéro au prix."
    f2 = flow_at(b, 2.0)
    if f2:
        txt += (f" Couverture estimée si le prix monte de 2 % : {flow_text(f2['up'])} ; s'il baisse de 2 % : {flow_text(f2['down'])}.")
    return txt


def chip_value(b: dict) -> tuple[str, str]:
    """(valeur courte, note) pour la Lecture."""
    val = (f"{'positif' if b['sign'] > 0 else 'négatif' if b['sign'] < 0 else 'neutre'} {musd(b['total'])} par 1 % · bascule {px(b.get('flip'))}"
           f" · calls {px(b.get('callWall'))} · puts {px(b.get('putWall'))}")
    conf = [f"{k['label'].lower()} {px(k['price'])} ≈ {', '.join(v['name'] for v in k['vwap'])}" for k in b["levels"]
            if k.get("vwap") and k["kind"] in ("callwall", "putwall", "flip", "absgamma", "maxpain", "strike")]
    note = regime_text(b)
    if b.get("aboveFlip") is not None:
        note += f" Le prix est {'au-dessus' if b['aboveFlip'] else 'en dessous'} de la bascule ({px(b['flip'])}, écart {pct(b.get('flipDistPct'))})."
    if b.get("absGamma"):
        note += f" Strike au plus fort gamma : {px(b['absGamma'])}."
    if b.get("maxPain"):
        note += f" Max pain de la plus grosse échéance proche : {px(b['maxPain']['price'])}."
    em = (b.get("em") or {}).get("day")
    if em:
        note += f" Mouvement attendu par les options sur 24 heures : ±{pct(em['pct'], sign=False)} ({px(em['down'])} à {px(em['up'])})."
    if conf:
        note += " Confluences avec les VWAP : " + " ; ".join(conf).rstrip(".") + "."
    srcs = ", ".join(f"{s['ex']} {pct((s.get('share') or 0) * 100, sign=False, dec=0)}" for s in b.get("sources") or [])
    note += f" Calcul : {b.get('scopeName', 'toutes les échéances')}, {srcs or 'Deribit'}."
    note += " Hypothèse sur le sens des teneurs de marché, effet non mesuré sur le passé : contexte, hors score."
    if b.get("stale"):
        note += " Données de plus de 30 minutes."
    return val, note


def pct(v: float | None, sign: bool = True, dec: int = 1) -> str:
    if v is None:
        return "-"
    s = f"{abs(v):.{dec}f}".replace(".", ",") + " %"
    return (("+" if v > 0 else "−" if v < 0 else "") + s) if sign else s
