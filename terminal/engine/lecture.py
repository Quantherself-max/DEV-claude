"""« Lecture » : l'essentiel du marche en une page, a partir de tout ce que le terminal sait deja (V9).

Principe d'epuration : on ne garde que ce qui sert a decider ; le detail (stats par niveau, profils, historique d'alertes...) reste disponible en mode expert.
Chaque element porte son NIVEAU DE PREUVE :
  - « valide »  : mesure par le backtest du terminal (la tendance de fond) ;
  - « indice »  : meme signe sur l'apprentissage et le test, sans depasser le seuil du hasard (laboratoire d'indicateurs) ;
  - « contexte »: information de lecture, aucun avantage demontre (financement, options, flux...). Aucun de ces elements n'entre dans le score des idees.
Module PUR : entrees = dictionnaires deja construits par le service ; sortie = dictionnaire serialisable."""
from . import indicators as ind
from data import derivs

DAY = 86_400_000


def fr(v, d=1, sign=False, unit=""):
    """Nombre a la francaise : virgule decimale, espace insecable pour les milliers, vrai signe moins."""
    if v is None:
        return "n/d"
    s = f"{v:+,.{d}f}" if sign else f"{v:,.{d}f}"
    return s.replace(",", "\u202f").replace(".", ",").replace("-", "−") + unit


def usd(v):
    if v is None:
        return "n/d"
    a = abs(v)
    return fr(v / 1e9, 2) + " Md$" if a >= 1e9 else fr(v / 1e6, 1) + " M$" if a >= 1e6 else fr(v / 1e3, 0) + " k$"


def chip(key, group, title, value, note="", tone="", evidence="contexte", detail=None):
    return {"key": key, "group": group, "title": title, "value": value, "note": note, "tone": tone, "evidence": evidence, "detail": detail}


def funding_chip(d: dict):
    ctx, price = d.get("ctx") or {}, d.get("price")
    f = (ctx.get("funding") or {}).get("now")                 # en % par 8 h
    rows = []
    if f is not None:
        oi = (ctx.get("oi") or {}).get("now")
        rows.append({"ex": "Binance", "funding": f / 100.0, "intervalH": 8.0, "oiUsd": oi * price if (oi and price) else None})
    rows += [dict(r) for r in (d.get("perps") or [])]
    if not rows:
        return None
    cmp_ = derivs.compare_view(rows)
    mean = cmp_["meanAnnualized"]
    if mean is None:
        return None
    n = len([r for r in cmp_["rows"] if r.get("annualized") is not None])
    crowd = cmp_["crowded"]
    note = ("Foule acheteuse : tout le monde est long et paie cher. Si le prix recule, les liquidations de longs s'enchaînent." if crowd == "longs" else
            "Foule vendeuse : tout le monde est short. Une hausse peut forcer des rachats (squeeze)." if crowd == "shorts" else
            "Pas de foule marquée." if abs(mean) < 0.25 else "Financement élevé sans accord entre les bourses.")
    val = f"{fr(mean * 100, 0, True)} %/an" + (f" · {n} bourses" if n > 1 else " · Binance")
    return chip("funding", "Positionnement", "Financement (coût de tenir une position)", val, note, "warn" if crowd else "", detail={"rows": cmp_["rows"], "spread": cmp_["spread"]})


def oi_chip(d: dict):
    ctx = d.get("ctx") or {}
    oi24 = (ctx.get("oi") or {}).get("d24h")
    reg = (ctx.get("regime") or {})
    if oi24 is None:
        return None
    others = d.get("perps") or []
    tot = sum(r["oiUsd"] for r in others if r.get("oiUsd"))
    oi, price = (ctx.get("oi") or {}).get("now"), d.get("price")
    if oi and price:
        tot += oi * price
    val = f"{fr(oi24, 1, True)} % en 24 h" + (f" · {usd(tot)} sur les bourses suivies" if tot else "")
    code = reg.get("code")
    return chip("oi", "Positionnement", "Intérêt ouvert (Open Interest)", val, reg.get("label", ""), "warn" if code in ("flat_up", "down_up") else "")


def flow_chip(d: dict):
    cvd = (d.get("ctx") or {}).get("cvd") or {}
    b = cvd.get("buy24h")
    if b is None:
        return None
    sd = cvd.get("swingDiv")
    note = ("Divergence haussière : le prix fait un creux plus bas, pas les acheteurs agressifs." if sd == "bull" else "Divergence baissière : le prix fait un sommet plus haut, pas les acheteurs agressifs." if sd == "bear" else
            cvd.get("div") or ("Acheteurs plus agressifs que les vendeurs." if b > 52 else "Vendeurs plus agressifs que les acheteurs." if b < 48 else "Équilibré."))
    return chip("flow", "Positionnement", "Flux d'ordres (acheteurs agressifs, 24 h)", fr(b, 1) + " %", note, "")


def liq_chip(d: dict):
    ctx = d.get("ctx") or {}
    r = (ctx.get("liqReal") or {}).get("24h")
    if r and (r["long"] + r["short"]) > 0:
        tot = r["long"] + r["short"]
        note = ("Surtout des longs liquidés : purge des acheteurs." if r["long"] > 0.65 * tot else "Surtout des shorts liquidés : squeeze vendeur." if r["short"] > 0.65 * tot else "Répartition équilibrée.")
        return chip("liq", "Positionnement", "Liquidations réelles (24 h)", f"longs {usd(r['long'])} · shorts {usd(r['short'])}", note, "")
    return None


def options_chips(d: dict):
    o, coin = d.get("options"), d.get("optionsCoin") or "BTC"
    out = []
    price = (o or {}).get("spot") or d.get("price")
    if o and o.get("expiries"):
        e = o["expiries"][0]
        mp = e.get("maxPain")
        dist = (mp / price - 1.0) * 100.0 if (mp and price) else None
        walls = ", ".join(fr(w["strike"], 0) for w in e["walls"][:2])
        pc = e.get("putCall")
        note = (f"Plus gros strikes : {walls}. " if walls else "") + ("Plus de puts que de calls : couverture ou paris baissiers." if pc and pc > 1.1 else "Plus de calls que de puts : paris haussiers." if pc and pc < 0.7 else "Calls et puts équilibrés.")
        out.append(chip("options", "Dérivés", f"Options {coin} (échéance dans {fr(e['daysLeft'], 1)} j)", f"max pain {fr(mp, 0)} ({fr(dist, 1, True)} %) · put/call {fr(pc, 2)}", note, "", detail={"expiries": o["expiries"][:3], "oiUsd": o.get("oiUsd")}))
    dv = d.get("dvol")
    if dv:
        note = ("Volatilité implicite haute : le marché paie cher sa protection." if dv["rank"] > 0.8 else "Volatilité implicite basse : couverture bon marché, mouvement possible." if dv["rank"] < 0.2 else "Dans la normale des 2 dernières semaines.")
        out.append(chip("dvol", "Dérivés", f"Volatilité implicite {coin} (DVOL)", f"{fr(dv['value'], 1)} · {fr(dv['rank'] * 100, 0)}e centile sur {fr(dv['days'], 0)} j · {fr((dv.get('chg24h') or 0) * 100, 1, True)} % en 24 h", note, ""))
    fut = [r for r in (d.get("futures") or []) if not r.get("perp")]
    if fut:
        q = fut[0]
        a = q["annualized"] * 100
        note = ("Levier très cher : beaucoup d'acheteurs à terme (risque de purge)." if a > 15 else "Base négative : marché en déport, prudence sur les longs." if a < 0 else "Base normale (coût du crédit).")
        out.append(chip("basis", "Dérivés", f"Base des futures {coin}", f"{fr(a, 1, True)} %/an ({fr(q['daysLeft'], 0)} j)", note, "warn" if a > 15 or a < 0 else ""))
    return out


def macro_chip(d: dict):
    m = d.get("macro")
    if not m:
        return None
    risk = m.get("risk")
    lab = (m.get("label") or "n/d").lower()
    note = f"{risk['label']} dans {int(risk['minutes'])} min." if risk and risk.get("minutes") is not None else "Aucune annonce majeure imminente."
    return chip("macro", "Macro et liquidité", "Macro (dollar, taux, actions, volatilité)", lab.upper(), note, "up" if lab == "risk-on" else "dn" if lab == "risk-off" else "", "contexte")


def fng_chip(d: dict):
    f = d.get("fng")
    if not f:
        return None
    v = f["value"]
    return chip("fng", "Macro et liquidité", "Peur et avidité (Fear & Greed)", f"{v} · {f['label']}", "Extrême peur ou extrême avidité = contexte contrarien, non validé." if (v <= 20 or v >= 80) else "", "", "contexte")


def dom_chip(d: dict):
    dm = d.get("dom")
    if not dm or d.get("symbol") == "BTCUSDT" or not dm.get("regime"):
        return None
    return chip("dom", "Macro et liquidité", "Dominance du bitcoin", f"{fr(dm.get('btc_d'), 1)} % · {dm['regime']}", "", "", "contexte")


def indicator_chips(d: dict):
    """Indicateurs en chaine / liquidite : seulement ceux que le laboratoire classe « indice » ou « informatif » (le reste est du bruit mesure)."""
    reads = (d.get("indicators") or {}).get("readings") or {}
    levels = d.get("indicatorLevels") or {}
    out = []
    for key in ("stable_30d", "puell"):
        r, lv = reads.get(key), levels.get(key)
        if not r or lv not in ("indice", "informatif"):
            continue
        grp, title, expect, hyp, unit = ind.CATALOG[key]
        v = r["value"]
        val = (fr(v * 100, 1, True) + " %" if "%" in unit else fr(v, 2)) + f" · {fr(r['rank'] * 100, 0)}e centile"
        age = (d.get("now_ms", 0) - r["date"]) / DAY
        note = hyp + (f" (donnée de {fr(age, 0)} j)" if age > 3 else "")
        out.append(chip(key, "Macro et liquidité", title, val, note, "", lv))
    return out


def money_block(d: dict):
    """Ou est l'argent : parts du panier (BTC, ETH, alts, stablecoins) et variations, performance relative, or (PAXG). Lecture seule : aucun lien prouve avec le prix futur."""
    snap = ((d.get("indicators") or {}).get("rotation"))
    if not snap:
        return None
    from . import rotation
    g = snap["gold"]
    rep = d.get("rotationReport") or {}
    semi = ((rep.get("gold") or {}).get("semi") or {}).get("all")
    c90 = ((rep.get("gold") or {}).get("corr") or {}).get("90")
    note = ("Lien avec le bitcoin : simultané, pas prédictif" + (f" (corrélation moyenne {fr(c90['mean'], 2, True)} sur 90 jours" + (f", asymétrie {'démontrée' if abs(semi['asym']['t']) >= 2 else 'non démontrée'}" if semi else "") + ")" if c90 else ""))
    age = (d.get("now_ms", 0) - snap["date"]) / DAY
    return {"date": snap["date"], "ageDays": age, "rows": snap["rows"], "rel": snap["rel"], "reading": rotation.reading(snap)["text"], "stableUsd": snap.get("stableUsd"),
            "gold": {"price": g["price"], "d30": g["d30"], "trend": g["trend"], "corr90": g["corr90"], "note": note}}


def build(d: dict) -> dict:
    """Entrees : voir engine/lecture.py (en-tete) et Service.lecture."""
    chips = [c for c in (funding_chip(d), oi_chip(d), flow_chip(d), liq_chip(d)) if c]
    chips += options_chips(d)
    chips += [c for c in (macro_chip(d), fng_chip(d), dom_chip(d)) if c]
    chips += indicator_chips(d)
    tr = d.get("trend")
    head = {"symbol": d.get("symbol"), "price": d.get("price"), "change24": d.get("change24")}
    if tr:
        head["trend"] = {"regime": tr["regime"], "label": tr["label"], "distFast": tr["distFast"], "distSlow": tr["distSlow"], "evidence": "valide"}
    sy = d.get("synth")
    if sy:
        head["bias"] = {"label": sy["label"], "score": sy["score"], "validated": sy["validated"], "pUp24": sy.get("pUp24"), "base24": sy.get("base24")}
    levels = [l for l in ((sy or {}).get("levels") or []) if l.get("side") in ("above", "below")]
    up = sorted([l for l in levels if l["side"] == "above"], key=lambda l: l["mid"])[:2]
    dn = sorted([l for l in levels if l["side"] == "below"], key=lambda l: -l["mid"])[:2]
    m = d.get("macro") or {}
    nxt = None
    if m.get("risk"):
        nxt = {"label": m["risk"]["label"], "t": m["risk"]["t"], "minutes": m["risk"].get("minutes")}
    elif m.get("upcoming"):
        e = m["upcoming"][0]
        nxt = {"label": e["label"], "t": e["t"], "minutes": (e["t"] - d.get("now_ms", e["t"])) / 60000.0}
    money = money_block(d)
    return {"ready": True, "t": d.get("now_ms"), "money": money, "head": head, "idea": d.get("idea"), "watch": {"next": nxt, "up": up, "dn": dn}, "chips": chips,
            "optionsOn": d.get("options") is not None, "sources": d.get("sources") or {}}
