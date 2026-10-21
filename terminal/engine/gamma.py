"""Exposition gamma des options BTC (V26) croisee avec les VWAP et les VWAP ancres.

Le calcul (data/derivs.py, gex_view) part du carnet public de Deribit, deja lu par le terminal toutes les 5 minutes : interet ouvert,
volatilite implicite et prix a terme de chaque option. Ici : les niveaux qui comptent (mur de calls au-dessus du prix, mur de puts en
dessous, bascule du gamma, plus gros strikes), et pour chacun les VWAP et VWAP ancres tout proches (moins de 0,35 fois l'amplitude d'une
bougie d'une heure, ou 0,25 % du prix) : un strike charge qui tombe sur un VWAP important est un niveau que deux mecanismes differents
surveillent.

Limites, dites partout ou c'est affiche :
  - le sens des positions des teneurs de marche est une HYPOTHESE (acheteurs des calls, vendeurs des puts du public) ; sur BTC, les produits
    de rendement qui vendent des calls peuvent l'inverser en partie ;
  - Deribit porte l'essentiel des options BTC mais pas tout (CME, OKX, Bybit, Binance n'y sont pas) ;
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


def key_levels(g: dict) -> list[dict]:
    """Niveaux de gamma a surveiller, du plus haut au plus bas (un strike n'apparait qu'une fois)."""
    out, seen = [], set()

    def add(price, kind, label, gex=None):
        if price is None:
            return
        k = round(float(price), 2)
        if kind != "flip" and k in seen:
            return
        seen.add(k)
        out.append({"price": float(price), "kind": kind, "label": label, "gex": gex})
    add(g.get("callWall"), "callwall", "Mur de calls", g.get("callWallGex"))
    add(g.get("putWall"), "putwall", "Mur de puts", g.get("putWallGex"))
    add(g.get("flip"), "flip", "Bascule du gamma")
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
    return keys


def brief(opt: dict | None, levels: list[dict], price: float, atr: float | None, now_ms: int) -> dict | None:
    """Resume pour le graphique et la Lecture (BTC seulement)."""
    if not opt:
        return None
    g = opt.get("gex")
    if not g:
        return {"error": opt.get("gexError") or "gamma indisponible"}
    keys = confluences(key_levels(g), levels, price or g["spot"], atr)
    t = opt.get("t")
    sign = 1 if g["total"] > 0 else -1 if g["total"] < 0 else 0
    above_flip = None if g.get("flip") is None or not price else price > g["flip"]
    return {"t": t, "stale": bool(t and now_ms - t > STALE_MS), "spot": g["spot"], "total": g["total"], "sign": sign, "flip": g.get("flip"),
            "aboveFlip": above_flip, "callWall": g.get("callWall"), "putWall": g.get("putWall"), "levels": keys,
            "strikes": g.get("strikes") or [], "curve": g.get("curve") or [], "nearShare": g.get("nearShare"), "n": g.get("n"), "expiries": g.get("expiries")}


def musd(v: float | None) -> str:
    if v is None:
        return "-"
    a = abs(v)
    s = f"{a / 1e9:.2f} Md$" if a >= 1e9 else f"{a / 1e6:.1f} M$" if a >= 1e6 else f"{a / 1e3:.0f} k$"
    return ("+" if v > 0 else "−" if v < 0 else "") + s.replace(".", ",")


def px(v: float | None) -> str:
    return "-" if v is None else f"{v:,.0f}".replace(",", " ")


def regime_text(b: dict) -> str:
    if b["sign"] > 0:
        return ("Gamma positif au prix (estimé) : les teneurs de marché vendraient les hausses et achèteraient les baisses : mouvements plutôt "
                "amortis, le prix a tendance à être retenu par les gros strikes.")
    if b["sign"] < 0:
        return ("Gamma négatif au prix (estimé) : les teneurs de marché suivraient le mouvement (achat dans les hausses, vente dans les baisses) : "
                "mouvements plutôt amplifiés.")
    return "Gamma proche de zéro au prix."


def chip_value(b: dict) -> tuple[str, str]:
    """(valeur courte, note) pour la Lecture."""
    val = (f"{'positif' if b['sign'] > 0 else 'négatif' if b['sign'] < 0 else 'neutre'} {musd(b['total'])} par 1 % · bascule {px(b.get('flip'))}"
           f" · calls {px(b.get('callWall'))} · puts {px(b.get('putWall'))}")
    conf = [f"{k['label'].lower()} {px(k['price'])} ≈ {', '.join(v['name'] for v in k['vwap'])}" for k in b["levels"] if k.get("vwap")]
    note = regime_text(b)
    if b.get("aboveFlip") is not None:
        note += f" Le prix est {'au-dessus' if b['aboveFlip'] else 'en dessous'} de la bascule ({px(b['flip'])})."
    if conf:
        note += " Confluences avec les VWAP : " + " ; ".join(conf).rstrip(".") + "."
    note += " Hypothèse sur le sens des teneurs de marché, Deribit seulement, effet non mesuré sur le passé : contexte, hors score."
    if b.get("stale"):
        note += " Données de plus de 30 minutes."
    return val, note
