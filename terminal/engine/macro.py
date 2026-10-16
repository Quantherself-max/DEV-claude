"""Analyse macro : calendrier economique (consensus), reaction MESUREE des marches aux annonces passees,
tendance des actifs de reference (dollar, taux 10 ans, indices, VIX, or) et lien avec le crypto.

Principe : sans clé payante on ne dispose que du consensus et du chiffre precedent AVANT l'annonce. Le chiffre
publie est donc lu a travers la reaction du marche lui-meme (rendement 10 ans + dollar dans les 15 minutes
suivantes) : c'est la mesure la plus fiable de la « surprise » (restrictive si les taux et le dollar montent,
accommodante s'ils baissent). Les regles ci-dessous sont des a priori de lecture, ensuite corriges par ce
qui a ete reellement mesure sur BTC / la paire affichee."""
import math
import re
from bisect import bisect_right

MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000

# (motif, cle, categorie, poids d'importance, signe attendu sur le risque si le chiffre est SUPERIEUR au consensus, libelle)
RULES = [
    (r"fomc.*(statement|rate)|federal funds rate|interest rate decision", "FOMC", "fed", 1.0, 0, "Décision de la Fed"),
    (r"fomc.*press conference|fed chair.*press", "FOMC_PC", "fed", 0.9, 0, "Conférence de presse de la Fed"),
    (r"fomc.*minutes|meeting minutes", "MINUTES", "fed", 0.6, 0, "Compte rendu de la Fed"),
    (r"fed chair|powell|fomc member|speaks|testifies", "FED_SPEECH", "speech", 0.5, 0, "Discours Fed"),
    (r"core cpi", "CORE_CPI", "inflation", 1.0, -1, "Inflation sous-jacente (CPI core)"),
    (r"\bcpi\b", "CPI", "inflation", 0.9, -1, "Inflation (CPI)"),
    (r"core pce", "CORE_PCE", "inflation", 0.9, -1, "PCE core (inflation préférée de la Fed)"),
    (r"pce price", "PCE", "inflation", 0.7, -1, "PCE"),
    (r"core ppi", "CORE_PPI", "inflation", 0.55, -1, "PPI core"),
    (r"\bppi\b", "PPI", "inflation", 0.5, -1, "PPI"),
    (r"average hourly earnings", "AHE", "inflation", 0.6, -1, "Salaires horaires"),
    (r"non-?farm|nfp", "NFP", "labor", 1.0, -1, "Emplois non agricoles (NFP)"),
    (r"unemployment rate", "UNRATE", "labor", 0.7, 1, "Taux de chômage"),
    (r"unemployment claims|jobless claims", "CLAIMS", "labor", 0.4, 1, "Inscriptions au chômage"),
    (r"adp", "ADP", "labor", 0.4, -1, "Emploi ADP"),
    (r"jolts", "JOLTS", "labor", 0.4, -1, "Offres d'emploi (JOLTS)"),
    (r"retail sales", "RETAIL", "growth", 0.6, -1, "Ventes au détail"),
    (r"\bgdp\b", "GDP", "growth", 0.6, -1, "PIB"),
    (r"ism.*(manufacturing|services)|\bpmi\b", "PMI", "growth", 0.5, -1, "Indice PMI / ISM"),
    (r"consumer (sentiment|confidence)", "SENTIMENT", "sentiment", 0.3, 1, "Confiance des consommateurs"),
    (r"treasury|bond auction|note auction|bill auction", "AUCTION", "auction", 0.3, 0, "Adjudication de dette US"),
    (r"ecb|boe|boj|monetary policy|main refinancing|bank rate|policy rate", "CB_OTHER", "fed", 0.5, 0, "Banque centrale (hors Fed)"),
]
NOISE = re.compile(r"holiday|crude oil|natural gas|api|baker hughes|mortgage|housing|building permits|home sales", re.I)


def classify(title: str, country: str = "USD"):
    t = title.lower()
    if NOISE.search(t):
        return {"key": "OTHER", "cat": "other", "w": 0.1, "sign": 0, "label": title}
    for pat, key, cat, w, sign, label in RULES:
        if re.search(pat, t):
            if country != "USD" and cat in ("inflation", "labor", "growth", "sentiment"):
                w *= 0.4                                    # hors Etats-Unis : effet indirect sur le crypto
            return {"key": key, "cat": cat, "w": w, "sign": sign, "label": label}
    return {"key": "OTHER", "cat": "other", "w": 0.15, "sign": 0, "label": title}


def expectation(ev, cls):
    """Ce que le consensus dit par rapport au chiffre precedent, et le scenario type de reaction."""
    f, p = ev.get("fnum"), ev.get("pnum")
    out = {"dir": None, "text": "", "scen_up": "", "scen_dn": ""}
    if f is not None and p is not None:
        d = f - p
        if abs(d) < 1e-9:
            out["dir"] = 0
            out["text"] = f"Consensus {ev['forecast']} : stable par rapport au précédent ({ev['previous']})."
        else:
            out["dir"] = 1 if d > 0 else -1
            out["text"] = (f"Consensus {ev['forecast']} contre {ev['previous']} précédemment : "
                           f"{'hausse' if d > 0 else 'baisse'} attendue.")
    elif f is not None:
        out["text"] = f"Consensus {ev['forecast']}."
    s = cls["sign"]
    if s:
        up_bad = s < 0
        out["scen_up"] = ("Chiffre supérieur au consensus : plutôt restrictif (dollar et taux en hausse), pression sur le crypto."
                          if up_bad else "Chiffre supérieur au consensus : plutôt accommodant (économie plus faible), soutien au crypto.")
        out["scen_dn"] = ("Chiffre inférieur au consensus : plutôt accommodant (dollar et taux en baisse), soutien au crypto."
                          if up_bad else "Chiffre inférieur au consensus : plutôt restrictif, pression sur le crypto.")
    elif cls["cat"] == "fed":
        out["scen_up"] = "Ton plus restrictif que prévu (moins de baisses de taux) : dollar et taux en hausse, pression sur le crypto."
        out["scen_dn"] = "Ton plus accommodant que prévu (plus de baisses de taux) : soutien au crypto."
    return out


# ---------- series ----------
def _series_at(series, ts):
    """Derniere valeur connue a l'instant ts pour une liste triee [(t_ms, valeur)]."""
    if not series:
        return None
    ks = [t for t, _ in series]
    i = bisect_right(ks, ts) - 1
    if i < 0 or ts - series[i][0] > 3 * HOUR:
        return None
    return series[i][1]


def _yield_pct(v):
    return v / 10.0 if v is not None and v > 20 else v         # ^TNX est parfois cote x10


def _px_at(c5, times, ts):
    """Cloture du dernier bar 5 min termine a l'instant ts."""
    i = bisect_right(times, ts - 5 * MIN) - 1
    return c5[i].c if i >= 0 and ts - (c5[i].t + 5 * MIN) < HOUR else None


def crypto_reaction(c5, t_ev):
    if not c5:
        return None
    times = [k.t for k in c5]
    p0 = _px_at(c5, times, t_ev)
    p15, p60 = _px_at(c5, times, t_ev + 15 * MIN), _px_at(c5, times, t_ev + 60 * MIN)
    if not p0 or not p15:
        return None
    i0 = bisect_right(times, t_ev - 5 * MIN)
    after = [k for k in c5[i0:i0 + 12]]
    before = c5[max(0, i0 - 288):i0]
    rng = (max(k.h for k in after) - min(k.l for k in after)) / p0 * 100 if after else None
    v_after = sum(k.v for k in after)
    v_norm = sum(k.v for k in before) / max(1, len(before)) * 12
    return {"r15": (p15 / p0 - 1) * 100, "r60": (p60 / p0 - 1) * 100 if p60 else None, "rng": rng,
            "volx": v_after / v_norm if v_norm > 0 else None}


def cross_reaction(cross5, t_ev):
    out = {}
    for name in ("DXY", "US10Y", "NDX", "SPX"):
        s = cross5.get(name)
        a, b, c = _series_at(s, t_ev), _series_at(s, t_ev + 15 * MIN), _series_at(s, t_ev + 60 * MIN)
        if a is None or b is None:
            continue
        if name == "US10Y":
            a, b = _yield_pct(a), _yield_pct(b)
            out["US10Y"] = (b - a) * 100.0                      # points de base
            if c is not None:
                out["US10Y60"] = (_yield_pct(c) - a) * 100.0
        else:
            out[name] = (b / a - 1) * 100.0
    return out


def impulse(cr):
    """Surprise lue dans le marche : > 0 restrictive (taux et dollar montent), < 0 accommodante."""
    parts = []
    if "US10Y" in cr:
        parts.append(cr["US10Y"] / 3.0)                         # ~3 pb = mouvement notable en 15 min
    if "DXY" in cr:
        parts.append(cr["DXY"] / 0.12)
    return sum(parts) / len(parts) if parts else None


def impulse_label(x):
    if x is None:
        return "inconnue"
    if abs(x) < 0.6:
        return "neutre (déjà dans les prix)"
    return ("restrictive" if x > 0 else "accommodante") + (" forte" if abs(x) > 1.6 else "")


# ---------- tendance des actifs de reference ----------
def _pct(a, b):
    return (a / b - 1) * 100.0 if a is not None and b else None


def _log_returns(series):
    out = {}
    for (t0, a), (t1, b) in zip(series, series[1:]):
        if a > 0 and b > 0:
            out[t1 // DAY] = math.log(b / a)
    return out


def correlation(a: dict, b: dict, last=30):
    ks = sorted(set(a) & set(b))[-last:]
    if len(ks) < min(12, last):
        return None
    xa, xb = [a[k] for k in ks], [b[k] for k in ks]
    ma, mb = sum(xa) / len(xa), sum(xb) / len(xb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(xa, xb))
    va, vb = sum((x - ma) ** 2 for x in xa), sum((y - mb) ** 2 for y in xb)
    return cov / math.sqrt(va * vb) if va > 0 and vb > 0 else None


PRIOR = {"DXY": -0.3, "US10Y": -0.2, "SPX": 0.4, "NDX": 0.45, "VIX": -0.3, "GOLD": 0.1}
LABEL = {"DXY": "Dollar (DXY)", "US10Y": "Taux US 10 ans", "SPX": "S&P 500 (futures)", "NDX": "Nasdaq (futures)",
         "VIX": "VIX (volatilité actions)", "GOLD": "Or"}


def asset_trends(cross5, crossD, btc_daily):
    btc_ret = _log_returns(btc_daily) if btc_daily else {}
    out = {}
    for name in LABEL:
        d, f = crossD.get(name) or [], cross5.get(name) or []
        if len(d) < 30:
            continue
        last = f[-1][1] if f else d[-1][1]
        t_last = f[-1][0] if f else d[-1][0]
        px = _yield_pct if name == "US10Y" else (lambda v: v)
        last, d_vals = px(last), [(t, px(c)) for t, c in d]
        day_ago = _series_at(f, t_last - DAY) if f else None
        c1 = (last - px(day_ago)) * 100 if name == "US10Y" and day_ago is not None else _pct(last, px(day_ago) if day_ago else None)
        ref5 = d_vals[-6][1] if len(d_vals) >= 6 else None
        c5 = (last - ref5) * 100 if name == "US10Y" and ref5 is not None else _pct(last, ref5)
        # ecart-type des variations sur 5 jours (3 dernieres annees) pour juger si le mouvement est inhabituel
        chg = []
        for i in range(max(5, len(d_vals) - 760), len(d_vals)):
            chg.append((d_vals[i][1] - d_vals[i - 5][1]) * 100 if name == "US10Y" else _pct(d_vals[i][1], d_vals[i - 5][1]))
        chg = [x for x in chg if x is not None]
        sd = math.sqrt(sum(x * x for x in chg) / len(chg)) if chg else None
        z = c5 / sd if (c5 is not None and sd) else None
        rets = _log_returns(d_vals) if btc_ret else {}
        cors = {w: (correlation(rets, btc_ret, w) if rets else None) for w in (30, 90, 365)}
        out[name] = {"label": LABEL[name], "last": last, "c1d": c1, "c5d": c5, "unit": "pb" if name == "US10Y" else "%",
                     "z": z, "corr": cors[90] if cors[90] is not None else cors[30], "corr30": cors[30], "corr365": cors[365],
                     "t": t_last, "spark": [round(v, 4) for _, v in d_vals[-30:]], "years": round(len(d_vals) / 365.0, 1)}
    return out


def risk_score(trends):
    """Score risk-on (+) / risk-off (-) en [-100, 100] : mouvement inhabituel de chaque actif x son lien avec le BTC
    (correlation mesuree sur 90 j, melangee a l'a priori usuel pour eviter les valeurs extremes)."""
    parts, total, wsum = [], 0.0, 0.0
    for name, t in trends.items():
        if t["z"] is None:
            continue
        corr = t["corr"] if t["corr"] is not None else PRIOR[name]
        eff = 0.5 * corr + 0.5 * PRIOR[name]
        c = max(-2.0, min(2.0, t["z"])) * eff
        parts.append({"name": name, "label": t["label"], "z": t["z"], "corr": t["corr"], "eff": eff, "contrib": c})
        total += c
        wsum += abs(eff)
    score = max(-100.0, min(100.0, total / max(wsum, 0.5) * 100.0 / 2.0 * 1.6)) if parts else None
    return score, sorted(parts, key=lambda d: -abs(d["contrib"]))


def fng_stats(fng, btc_daily):
    """Que fait le BTC apres chaque zone du Fear & Greed ? Frequence de hausse a 1 / 7 / 30 jours, sur tout l'historique
    commun (depuis 2018). Les fenetres se chevauchent : les intervalles de confiance utilisent des effectifs reduits."""
    if not fng or len(btc_daily) < 400:
        return None
    from .stats import wilson
    px = {t // DAY: c for t, c in btc_daily}
    days = sorted(px)
    pos = {d: i for i, d in enumerate(days)}
    zones = [("Peur extrême (≤ 25)", 0, 25), ("Peur (26-45)", 26, 45), ("Neutre (46-55)", 46, 55), ("Avidité (56-75)", 56, 75), ("Avidité extrême (> 75)", 76, 100)]
    hs = (1, 7, 30)
    acc = {z[0]: {h: [0, 0, 0.0] for h in hs} for z in zones}
    base = {h: [0, 0] for h in hs}
    cur = fng[-1][1]
    for t, v, _ in fng:
        d = t // DAY
        i = pos.get(d)
        if i is None:
            continue
        zname = next(z[0] for z in zones if z[1] <= v <= z[2])
        for h in hs:
            if i + h >= len(days) or days[i + h] - d > h + 3:
                continue
            up = px[days[i + h]] > px[d]
            a = acc[zname][h]
            a[0] += 1; a[1] += up; a[2] += px[days[i + h]] / px[d] - 1
            base[h][0] += 1; base[h][1] += up
    out = []
    for name, lo, hi in zones:
        row = {"zone": name, "current": lo <= cur <= hi}
        for h in hs:
            n, k, r = acc[name][h]
            neff = max(1, n // h)
            p, a, b = wilson(round(k / n * neff), neff) if n else (None, None, None)
            row[str(h)] = {"n": n, "neff": neff, "p": k / n if n else None, "lo": a, "hi": b, "mean": r / n * 100 if n else None}
        out.append(row)
    return {"rows": out, "base": {str(h): base[h][1] / base[h][0] if base[h][0] else None for h in hs},
            "since": fng[0][0], "days": len(fng)}


# ---------- analyse complete ----------
def analyse(now_ms, snap, c5_sym, c5_btc, sym, btc_daily):
    cal = snap["calendar"]
    cross5, crossD = snap["cross5"], snap["crossD"]
    events, new_react = [], {}
    for e in sorted(cal.values(), key=lambda e: e["t"]):
        cls = classify(e["title"], e["country"])
        usd_ok = e["country"] == "USD" and e["impact"] >= 2
        if not (usd_ok or e["impact"] == 3):
            continue
        if cls["key"] == "OTHER" and e["impact"] < 3:
            continue
        item = {**e, "key": cls["key"], "cat": cls["cat"], "w": cls["w"], "label": cls["label"], "past": e["t"] <= now_ms}
        if item["past"]:
            r = e.get("reaction")
            if r is None and now_ms - e["t"] >= 75 * MIN:
                r = {"btc": crypto_reaction(c5_btc, e["t"]), "sym": crypto_reaction(c5_sym, e["t"]) if sym != "BTCUSDT" else None,
                     "cross": cross_reaction(cross5, e["t"])}
                if r["btc"] or r["cross"]:
                    new_react[e["id"]] = r
                else:
                    r = None
            if r is not None:
                imp = impulse(r.get("cross") or {})
                r = {**r, "impulse": imp, "impulseLabel": impulse_label(imp)}
            item["reaction"] = r
        else:
            item["exp"] = expectation(e, cls)
        events.append(item)
    upcoming = [e for e in events if not e["past"] and e["t"] - now_ms <= 7 * DAY]
    past = [e for e in events if e["past"] and now_ms - e["t"] <= 7 * DAY][::-1]
    # reaction typique par type d'evenement (archive complete, y compris les reactions mesurees plus tot)
    typical = {}
    for e in cal.values():
        r = e.get("reaction") or new_react.get(e["id"])
        if not r or not r.get("btc"):
            continue
        k = classify(e["title"], e["country"])["key"]
        typical.setdefault(k, []).append(r)
    typ = {}
    for k, rs in typical.items():
        a60 = [abs(x["btc"]["r60"]) for x in rs if x["btc"].get("r60") is not None]
        rg = [x["btc"]["rng"] for x in rs if x["btc"].get("rng")]
        typ[k] = {"n": len(rs), "abs60": sum(a60) / len(a60) if a60 else None, "rng": sum(rg) / len(rg) if rg else None}
    for e in upcoming:
        e["typical"] = typ.get(e["key"])
    # risque evenementiel
    nxt = next((e for e in upcoming if e["impact"] == 3 and e["w"] >= 0.5), None)
    risk = None
    if nxt:
        mins = (nxt["t"] - now_ms) / MIN
        risk = {"id": nxt["id"], "label": nxt["label"], "title": nxt["title"], "minutes": mins, "t": nxt["t"],
                "level": "danger" if mins <= 90 else "attention" if mins <= 12 * 60 else "info"}
    in_window = [e for e in events if e["impact"] == 3 and e["w"] >= 0.5 and -60 * MIN <= e["t"] - now_ms <= 30 * MIN]
    trends = asset_trends(cross5, crossD, btc_daily)
    rs, parts = risk_score(trends)
    # impulsions recentes (72 h, demi-vie 24 h) : accommodante = favorable au crypto
    imp_sum, imp_n = 0.0, 0
    for e in past:
        r = e.get("reaction")
        if r and r.get("impulse") is not None and now_ms - e["t"] <= 72 * HOUR:
            wgt = e["w"] * 0.5 ** ((now_ms - e["t"]) / (24 * HOUR))
            imp_sum += -max(-2.5, min(2.5, r["impulse"])) * wgt
            imp_n += 1
    imp_score = max(-1.0, min(1.0, imp_sum / 1.5)) if imp_n else None
    fng = snap.get("fng") or []
    fg = None
    if fng:
        v = fng[-1][1]
        fg = {"value": v, "label": fng[-1][2], "d7": v - fng[-8][1] if len(fng) >= 8 else None,
              "stats": fng_stats(fng, btc_daily),
              "contrarian": 0.4 if v <= 20 else 0.2 if v <= 30 else -0.4 if v >= 80 else -0.2 if v >= 70 else 0.0,
              "spark": [x[1] for x in fng[-30:]]}
    comps = []
    if rs is not None:
        comps.append(("Actifs de référence", rs / 100.0, 0.6))
    if imp_score is not None:
        comps.append(("Réaction aux annonces récentes", imp_score, 0.3))
    if fg:
        comps.append(("Sentiment (Fear & Greed, contrarien)", fg["contrarian"], 0.1))
    tw = sum(w for _, _, w in comps)
    score = sum(s * w for _, s, w in comps) / tw * 100.0 if tw else None
    discount = 0.5 if risk and risk["level"] == "danger" else 0.8 if risk and risk["level"] == "attention" else 1.0
    state = {
        "score": score, "label": ("risk-on" if score > 25 else "risk-off" if score < -25 else "neutre") if score is not None else None,
        "discount": discount, "risk": risk, "inWindow": [e["id"] for e in in_window],
        "upcoming": upcoming[:14], "past": past[:12], "typical": typ, "trends": trends, "parts": parts[:6], "fng": fg,
        "impulse": {"score": imp_score, "n": imp_n},
        "components": [{"label": n, "score": s, "w": w} for n, s, w in comps],
        "errors": snap.get("errors", {}), "hasCalendar": bool(cal),
    }
    state["lines"] = narrative(state, now_ms, sym)
    return state, new_react


def _fmt_min(m):
    m = int(abs(m))
    return f"{m // 60} h {m % 60:02d}" if m >= 60 else f"{m} min"


def narrative(s, now_ms, sym):
    """Lecture macro en francais, construite uniquement a partir des chiffres mesures (rien d'invente)."""
    L = []
    r = s["risk"]
    if r:
        tone = {"danger": "bad", "attention": "warn", "info": "muted"}[r["level"]]
        extra = " Évite de garder un levier élevé à travers l'annonce : les mèches de 30 s balaient les stops." if r["level"] == "danger" else ""
        L.append({"tone": tone, "text": f"Prochaine annonce majeure : {r['label']} dans {_fmt_min(r['minutes'])}.{extra}"})
    elif s["hasCalendar"]:
        L.append({"tone": "ok", "text": "Aucune annonce majeure (impact élevé) dans les prochains jours : le marché est piloté par le flux et les niveaux."})
    else:
        L.append({"tone": "muted", "text": "Calendrier indisponible pour l'instant (voir l'état des sources)."})
    up = [e for e in s["upcoming"] if e["impact"] == 3 and e["w"] >= 0.5][:1]
    for e in up:
        ex = e.get("exp") or {}
        if ex.get("text"):
            L.append({"tone": "muted", "text": f"{e['label']} : {ex['text']}"})
        t = e.get("typical")
        if t and t.get("abs60") is not None:
            L.append({"tone": "muted", "text": f"Mesuré sur {t['n']} annonce(s) de ce type : mouvement moyen du BTC {t['abs60']:.2f} % dans l'heure qui suit (amplitude {t['rng']:.2f} %)." if t.get("rng") else f"Mesuré sur {t['n']} annonce(s) : mouvement moyen du BTC {t['abs60']:.2f} % dans l'heure."})
    tr = s["trends"]
    for name in ("DXY", "US10Y", "NDX", "VIX"):
        t = tr.get(name)
        if not t or t["c5d"] is None:
            continue
        unusual = t["z"] is not None and abs(t["z"]) >= 1.0
        c = f"{t['c5d']:+.1f} pb" if t["unit"] == "pb" else f"{t['c5d']:+.2f} %"
        corr = f" (lien mesuré avec le BTC sur 90 j : {t['corr']:+.2f})" if t["corr"] is not None else ""
        eff = (t["corr"] if t["corr"] is not None else PRIOR[name]) * (t["z"] or 0)
        if unusual:
            L.append({"tone": "ok" if eff > 0 else "bad", "text": f"{t['label']} {c} sur 5 jours, mouvement inhabituel : {'plutôt favorable' if eff > 0 else 'plutôt défavorable'} au crypto{corr}."})
    ev = [e for e in s["past"] if e.get("reaction") and e["reaction"].get("impulse") is not None and now_ms - e["t"] <= 72 * HOUR][:2]
    for e in ev:
        rr = e["reaction"]
        b = (rr.get("btc") or {})
        btxt = f" ; le BTC a fait {b['r15']:+.2f} % en 15 min" if b.get("r15") is not None else ""
        L.append({"tone": "muted", "text": f"{e['label']} ({e['forecast'] or 'sans consensus'}) : surprise {rr['impulseLabel']} lue dans les taux et le dollar{btxt}."})
    fg = s.get("fng")
    if fg:
        L.append({"tone": "muted", "text": f"Sentiment Fear & Greed : {fg['value']} ({fg['label']}). Les extrêmes (≤ 20 ou ≥ 80) sont des signaux contrariens, pas des signaux d'entrée."})
    if s["score"] is not None:
        L.append({"tone": "ok" if s["score"] > 25 else "bad" if s["score"] < -25 else "muted",
                  "text": f"Lecture macro : {s['label']} ({s['score']:+.0f}/100). C'est un contexte, pas un signal : il pèse sur la probabilité, il ne la remplace pas."})
    return L
