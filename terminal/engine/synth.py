"""Synthese du biais : combine les briques d'analyse en un biais lisible, avec sa confiance, ses arguments pour /
contre et ce qui l'invaliderait.

Regle d'or d'honnetete : seule la composante STATISTIQUE est une probabilite validee hors echantillon. Flux,
macro, niveaux et dominance sont des lectures de contexte ponderees a priori : elles orientent le biais mais ne
sont pas presentees comme des probabilites mesurees. La confiance reste « faible » tant que le modele
statistique n'a pas prouve un avantage et qu'une annonce majeure est proche."""


def _clip(x, lo=-1.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def flow_score(ctx):
    """Lecture du positionnement : (score -1..1, [(sens, texte)])."""
    if not ctx:
        return None, []
    notes, parts = [], []
    cvd = ctx.get("cvd") or {}
    if cvd.get("buy4h") is not None and cvd.get("buy24h") is not None:
        s = _clip(((cvd["buy4h"] - 50) + (cvd["buy24h"] - 50)) / 8.0)
        parts.append(s)
        notes.append((s, f"Flux agressif : {cvd['buy4h']:.1f} % d'achats sur 4 h, {cvd['buy24h']:.1f} % sur 24 h"))
        if cvd.get("div"):
            notes.append((-0.4 if "baissière" in cvd["div"] else 0.4, f"Divergence CVD {cvd['div']}"))
            parts.append(notes[-1][0])
    f = (ctx.get("funding") or {}).get("now")
    if f is not None:
        s = _clip(-(f - 0.01) / 0.05) * 0.6
        parts.append(s)
        notes.append((s, f"Funding {f:+.4f} % : {'foule acheteuse, risque de purge des longs' if s < -0.1 else 'foule vendeuse, risque de squeeze' if s > 0.1 else 'neutre'}"))
    g = ((ctx.get("ls") or {}).get("global") or {}).get("now")
    if g is not None:
        s = _clip(-(g - 1.2) / 1.0) * 0.5
        parts.append(s)
        notes.append((s, f"Ratio long/short des comptes {g:.2f} : {'foule très longue (contrarien baissier)' if s < -0.15 else 'foule courte (contrarien haussier)' if s > 0.15 else 'équilibré'}"))
    code = (ctx.get("regime") or {}).get("code")
    s = {"up_up": 0.3, "up_down": -0.2, "down_up": -0.3, "down_down": 0.1}.get(code)
    if s is not None:
        parts.append(s)
        notes.append((s, (ctx["regime"]["label"])))
    cb = (ctx.get("coinbase") or {}).get("premium")
    if cb is not None and abs(cb) > 0.05:
        s = 0.25 if cb > 0 else -0.25
        parts.append(s)
        notes.append((s, f"Prime Coinbase {cb:+.3f} % : {'demande US plus forte' if cb > 0 else 'demande US plus faible'}"))
    lr = ctx.get("liqReal")
    if lr and lr.get("1h") and lr["1h"]["long"] + lr["1h"]["short"] > 0:
        L, S = lr["1h"]["long"], lr["1h"]["short"]
        if max(L, S) > 3 * max(1.0, min(L, S)) and max(L, S) > 200_000:
            s = 0.3 if L > S else -0.3                         # purge de longs = pression vendeuse passee, souvent epuisee
            notes.append((0.0, f"Liquidations réelles 1 h : {L / 1e6:.2f} M$ de longs, {S / 1e6:.2f} M$ de shorts"))
    return (sum(parts) / len(parts) if parts else None), notes


def structure_score(zones, price):
    """Asymetrie des niveaux essentiels : le prix a-t-il plus de chances de toucher la zone du dessus ou celle du dessous ?"""
    up = [z for z in zones if z["side"] == "above" and z.get("prob")]
    dn = [z for z in zones if z["side"] == "below" and z.get("prob")]
    if not up or not dn:
        return None, None
    zu, zd = min(up, key=lambda z: z["distAtr"]), min(dn, key=lambda z: z["distAtr"])
    pu, pd = zu["prob"]["reach"].get("24"), zd["prob"]["reach"].get("24")
    if pu is None or pd is None:
        return None, None
    return _clip((pu - pd) * 1.5), (zu, zd, pu, pd)


def synthesize(sym, price, bias, macro, dom, ctx, zones, ess_ids):
    ess = [z for z in zones if z["id"] in ess_ids]
    comps = []                                                   # (clef, libelle, score, poids, notes)
    stat_note = "Pas encore calculé (historique en cours d'analyse)."
    stat_validated = False
    p24 = p4 = None
    if bias and bias.get("ready"):
        h24, h4 = bias["horizons"]["24"], bias["horizons"]["4"]
        p24, p4 = h24, h4
        stat_validated = h24["validated"] or h4["validated"]
        if stat_validated:
            s = _clip(((h24["pUp"] - 0.5) / 0.08) * 0.6 + ((h4["pUp"] - 0.5) / 0.08) * 0.4 if h4["validated"] and h24["validated"] else
                      (h24["pUp"] - 0.5) / 0.08 if h24["validated"] else (h4["pUp"] - 0.5) / 0.08)
            comps.append(("stat", "Modèle statistique (validé hors échantillon)", s, 0.35,
                          [(s, f"P(hausse 24 h) = {h24['pUp'] * 100:.1f} %, P(hausse 4 h) = {h4['pUp'] * 100:.1f} %")]))
            stat_note = "Le modèle a prouvé un avantage hors échantillon : sa probabilité est la seule composante mesurée."
        else:
            stat_note = ("Le modèle statistique ne bat pas le hasard hors échantillon sur cette paire : "
                         f"la probabilité de hausse reste au taux de base ({h24['base'] * 100:.1f} % à 24 h). On n'en tire aucun biais.")
    fs, fnotes = flow_score(ctx)
    if fs is not None:
        comps.append(("flow", "Flux et positionnement", fs, 0.25, fnotes))
    if macro and macro.get("score") is not None:
        ms = _clip(macro["score"] / 100.0)
        comps.append(("macro", "Macro et actifs de référence", ms, 0.2, [(ms, f"Lecture macro {macro['label']} ({macro['score']:+.0f}/100)")]))
    ss, ctxz = structure_score(ess or zones, price)
    if ss is not None:
        zu, zd, pu, pd = ctxz
        comps.append(("structure", "Asymétrie des niveaux", ss, 0.1,
                      [(ss, f"Zone du dessus {pu * 100:.0f} % d'être touchée en 24 h, zone du dessous {pd * 100:.0f} %")]))
    if dom and dom.get("regime") and sym != "BTCUSDT":
        comps.append(("dom", "Dominance BTC / alts", dom["regime"]["score"], 0.1, [(dom["regime"]["score"], f"{dom['regime']['name']}")]))
    tw = sum(c[3] for c in comps)
    total = sum(c[2] * c[3] for c in comps) / tw if tw else 0.0
    score = round(total * 100)
    direction = "neutre" if abs(score) < 15 else "haussier" if score > 0 else "baissier"
    strength = "Léger" if abs(score) < 35 else "Net" if abs(score) < 60 else "Fort"
    label = "Neutre" if direction == "neutre" else f"{strength} biais {direction}"
    sign = 1 if score > 0 else -1
    agree = [c for c in comps if c[2] * sign > 0.1]
    pts = (2 if stat_validated and any(c[0] == "stat" for c in agree) else 0) + (1 if any(c[0] == "macro" for c in agree) else 0) \
        + (1 if any(c[0] == "flow" for c in agree) else 0) + (1 if len(agree) >= 3 else 0)
    risk = (macro or {}).get("risk")
    danger = bool(risk and risk["level"] == "danger")
    conf = "faible" if direction == "neutre" or pts < 3 or danger else "moyenne" if pts < 5 else "élevée"
    if not stat_validated:                                      # sans modele valide, la confiance reste faible
        conf = "faible"
    pros = [t for c in comps for s, t in c[4] if s * sign > 0.15 and direction != "neutre"]
    cons = [t for c in comps for s, t in c[4] if s * sign < -0.15 and direction != "neutre"]
    inval = []
    if ess:
        dn = sorted([z for z in ess if z["side"] == "below"], key=lambda z: z["distAtr"])
        up = sorted([z for z in ess if z["side"] == "above"], key=lambda z: z["distAtr"])
        if direction == "haussier" and dn:
            z = dn[0]
            b = (z.get("prob") or {}).get("bounce")
            inval.append(f"Cassure franche de la zone {z['mid']:,.0f}".replace(",", " ") + (f" (rebond historique {b['p'] * 100:.0f} % sur {b['n']} tests)" if b and b.get("n") else ""))
        if direction == "baissier" and up:
            z = up[0]
            inval.append(f"Reprise et tenue au-dessus de la zone {z['mid']:,.0f}".replace(",", " "))
    if danger:
        inval.append(f"Annonce majeure ({risk['label']}) dans {int(risk['minutes'])} min : tout biais peut être balayé en quelques secondes")
    return {
        "score": score, "direction": direction, "label": label, "confidence": conf, "validated": stat_validated, "statNote": stat_note,
        "components": [{"key": k, "label": lab, "score": s, "weight": w / tw if tw else 0} for k, lab, s, w, _ in comps],
        "pros": pros, "cons": cons, "invalidation": inval,
        "pUp24": p24["pUp"] if p24 else None, "pUp4": p4["pUp"] if p4 else None,
        "base24": p24["base"] if p24 else None,
        "levels": [{"id": z["id"], "side": z["side"], "mid": z["mid"], "score": z["score"], "distAtr": z["distAtr"],
                    "reach24": (z.get("prob") or {}).get("reach", {}).get("24"),
                    "bounce": (z.get("prob") or {}).get("bounce")} for z in sorted(ess, key=lambda z: -z["mid"])],
    }
