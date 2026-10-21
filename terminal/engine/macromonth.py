"""Analyse macro du mois (V25) : le mois en chiffres, la Fed (projections de ses membres, communiques et ce qui a change, votes, discours),
les projections a prendre en compte (Fed, Fonds monetaire international, marche, menages), la vision a moyen terme (cycle, inflation,
courbe des taux, liquidite, dollar), et des scenarios avec leurs declencheurs chiffres. Module PUR (aucun acces reseau).

Les rapports des banques (Goldman Sachs, JPMorgan...) ne sont pas publics en donnees : ils sont cherches sur le web par Claude, a la demande
(service + alerts/assistant.py), et ranges a cote de cette analyse."""
from __future__ import annotations
import math
from datetime import datetime, timezone

from . import macroview as mv
from . import macroweek as mw

DAY = mw.DAY
fr, fx = mw.fr, mv.fx


# ---------- mois ----------
def month_start(t: int) -> int:
    d = datetime.fromtimestamp(t / 1000, timezone.utc)
    return int(datetime(d.year, d.month, 1, tzinfo=timezone.utc).timestamp() * 1000)


def next_month(ms: int) -> int:
    d = datetime.fromtimestamp(ms / 1000, timezone.utc)
    return int(datetime(d.year + (d.month == 12), d.month % 12 + 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def month_key(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m")


def parse_month(key: str) -> int:
    return int(datetime.strptime(key + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def month_label(ms: int) -> str:
    d = datetime.fromtimestamp(ms / 1000, timezone.utc)
    return f"{mw.MONTHS[d.month - 1]} {d.year}"


# ---------- 1. le mois en chiffres ----------
def month_events(calendar: dict, fred: dict, a: int, b: int, now: int) -> list:
    """Annonces importantes du mois avec le chiffre publie et l'ecart au consensus (en ecarts habituels)."""
    out = []
    for e in mw.week_events(calendar or {}, fred or {}, a, b, now):
        if not (e["w"] >= 0.5 or e["impact"] == 3) or not e["past"]:
            continue
        z = None
        if e.get("surprise") is not None and e["key"] in mv.SIZE:
            z = round(mv.clip(e["surprise"] / mv.SIZE[e["key"]] * (-1 if e["key"] in ("UNRATE", "CLAIMS") else 1), -3, 3), 2)
        out.append({k: e[k] for k in ("id", "t", "label", "title", "country", "cat", "key", "forecast", "previous", "actual", "surpriseText", "dir", "read",
                                       "reactionText")} | {"z": z})
    return out


def dashboard_changes(fred: dict, a: int, b: int, lagged: bool) -> list:
    """Tableau de bord par theme a la fin du mois, avec la variation depuis le debut du mois (memes lignes que le bilan de la semaine)."""
    end, start = mw.dashboard(fred, b, lagged=lagged), mw.dashboard(fred, a, lagged=True)
    prev = {(th["key"], it["name"]): it["value"] for th in start for it in th["items"]}
    out = []
    for th in end:
        items = []
        for it in th["items"]:
            p = prev.get((th["key"], it["name"]))
            items.append({**it, "monthChange": (it["value"] - p) if it["value"] is not None and p is not None else None})
        out.append({**th, "items": items})
    return out


# ---------- 2. la Fed ----------
SEP_ROWS = [("FEDTARMD", "Taux directeur en fin d'année", "%"), ("PCECTPIMD", "Inflation (prix des dépenses de consommation), sur l'année", "%"),
            ("JCXFEMD", "Inflation sous-jacente (mesure préférée de la Fed), sur l'année", "%"), ("UNRATEMD", "Chômage au quatrième trimestre", "%"),
            ("GDPC1MD", "Croissance du produit intérieur brut, sur l'année", "%")]


def sep_table(fred: dict, t: int) -> dict:
    """Projections medianes des membres de la Fed (derniere reunion avec projections) : annee en cours et deux suivantes, plus le long terme."""
    y = datetime.fromtimestamp(t / 1000, timezone.utc).year
    years = [y, y + 1, y + 2]
    rows = []
    for sid, name, unit in SEP_ROWS:
        vals = {}
        for ts, v in fred.get(sid) or []:
            yr = datetime.fromtimestamp(ts / 1000, timezone.utc).year
            if yr in years:
                vals[str(yr)] = v
        if vals:
            rows.append({"sid": sid, "name": name, "unit": unit, "values": vals})
    lo = {str(datetime.fromtimestamp(ts / 1000, timezone.utc).year): v for ts, v in fred.get("FEDTARRL") or []}
    hi = {str(datetime.fromtimestamp(ts / 1000, timezone.utc).year): v for ts, v in fred.get("FEDTARRH") or []}
    lr = fred.get("FEDTARMDLR") or []
    sd = mv.sep_date(fred)
    return {"years": [str(x) for x in years], "rows": rows, "rangeLow": {k: lo[k] for k in map(str, years) if k in lo},
            "rangeHigh": {k: hi[k] for k in map(str, years) if k in hi}, "longRun": lr[-1][1] if lr else None, "date": sd,
            "stale": bool(sd and t - sd > 120 * DAY)}


def statements(fed: dict, a: int, b: int) -> dict:
    """Dernier communique connu a la fin du mois, ce qui a change face au precedent (mot a mot), le ton de chacun et les votes contre."""
    from data import fed as fed_mod
    st = sorted(((u, x) for u, x in ((fed or {}).get("statements") or {}).items() if x["t"] <= b), key=lambda kv: kv[1]["t"], reverse=True)
    if not st:
        return {}
    (u1, s1), prev = st[0], (st[1] if len(st) > 1 else None)
    out = {"t": s1["t"], "link": u1, "inMonth": a <= s1["t"] < b, "decision": fed_mod.decision(s1["pars"]), "tone": fed_mod.tone(" ".join(s1["pars"])),
           "dissents": fed_mod.dissents(s1["pars"]), "pars": s1["pars"]}
    if prev:
        u0, s0 = prev
        out["prev"] = {"t": s0["t"], "link": u0, "decision": fed_mod.decision(s0["pars"]), "tone": fed_mod.tone(" ".join(s0["pars"]))}
        out["diff"] = fed_mod.diff_statements(s0["pars"], s1["pars"])
        d = out["tone"]["score"] - out["prev"]["tone"]["score"]
        out["toneShift"] = d
        out["toneText"] = ("Le communiqué est plus accommodant que le précédent (plus de phrases sur les risques pour l'emploi ou le ralentissement de l'inflation)."
                           if d > 0 else "Le communiqué est plus restrictif que le précédent (plus de phrases sur l'inflation ou la solidité de l'économie)."
                           if d < 0 else "Ton inchangé par rapport au précédent communiqué : ce sont les changements de mots ci-dessous qui comptent.")
    return out


# ---------- 3. projections a prendre en compte ----------
def consensus_table(fred: dict, imf: dict, D: mv.Data, t: int, fedv: dict) -> list:
    """Une ligne par grandeur : ce que projettent la Fed, le FMI, le marche, les menages, et le dernier chiffre connu."""
    y = datetime.fromtimestamp(t / 1000, timezone.utc).year

    def sep(sid, yr):
        return next((v for ts, v in fred.get(sid) or [] if datetime.fromtimestamp(ts / 1000, timezone.utc).year == yr), None)

    def fmi(ind, area, yr):
        return ((imf or {}).get(ind) or {}).get(area, {}).get(str(yr))
    rows = []
    gn = D.known("GDPNOW", t, last=1)
    gdp = D.known("A191RL1Q225SBEA", t, last=1)
    for yr in (y, y + 1):
        rows.append({"name": f"Croissance des États-Unis en {yr}", "unit": "%",
                     "note": "Fed : fin d'année sur fin d'année ; FMI : moyenne annuelle ; GDPNow et dernier chiffre : rythme annualisé d'un trimestre", "cols": {
            "fed": sep("GDPC1MD", yr), "imf": fmi("NGDP_RPCH", "USA", yr),
            "now": gn[-1][1] if gn and yr == y else None, "last": gdp[-1][1] if gdp and yr == y else None}})
    core = D.known("PCEPILFE", t, last=13)
    core_y = mw.pct(core[-1][1], core[-13][1]) if len(core) >= 13 else None
    for yr in (y, y + 1):
        rows.append({"name": f"Inflation des États-Unis en {yr}", "unit": "%",
                     "note": "Fed : prix des dépenses de consommation, fin d'année sur fin d'année (sous-jacente, puis totale) ; FMI : prix à la consommation, "
                             "moyenne annuelle ; marché : inflation anticipée sur 5 ans ; ménages et Fed de Cleveland : inflation attendue à un an ; "
                             "dernier chiffre : mesure préférée de la Fed (sous-jacente) sur un an", "cols": {
            "fed": sep("JCXFEMD", yr), "fed2": sep("PCECTPIMD", yr), "imf": fmi("PCPIPCH", "USA", yr),
            "market": D.at("T5YIE", t) if yr == y + 1 else None, "households": D.at("MICH", t) if yr == y + 1 else None,
            "model": D.at("EXPINF1YR", t) if yr == y + 1 else None, "last": core_y if yr == y else None}})
    un = D.known("UNRATE", t, last=1)
    for yr in (y, y + 1):
        rows.append({"name": f"Chômage aux États-Unis en {yr}", "unit": "%", "note": "Fed : quatrième trimestre ; FMI : moyenne annuelle", "cols": {
            "fed": sep("UNRATEMD", yr), "imf": fmi("LUR", "USA", yr), "last": un[-1][1] if un and yr == y else None}})
    for d in (fedv.get("dots") or [])[:2]:
        mk = mv.interp([(p["m"], p["r"]) for p in fedv.get("path") or []], d["m"])
        rows.append({"name": f"Taux de la Fed fin {d['year']}", "unit": "%",
                     "note": "marché : chemin lu dans les taux d'État de 3 mois à 2 ans (approximation)", "cols": {"fed": d["median"], "market": mk,
                                                                                     "last": fedv.get("dff") if d["year"] == y else None}})
    for area in ("WEOWORLD", "EURO", "CHN", "JPN"):
        a, b = fmi("NGDP_RPCH", area, y), fmi("NGDP_RPCH", area, y + 1)
        if a is not None or b is not None:
            rows.append({"name": f"Croissance — {mv_area(area)} ({y} / {y + 1})", "unit": "%", "cols": {"imf": a, "imf2": b}})
    return rows


def mv_area(code):
    from data.imf import AREAS
    return AREAS.get(code, code)


CONSENSUS_COLS = [("fed", "Fed (médiane des membres)"), ("fed2", "Fed, inflation totale"), ("imf", "FMI"), ("imf2", "FMI, année suivante"),
                  ("market", "Marché"), ("households", "Ménages (Michigan, 1 an)"), ("model", "Fed de Cleveland (1 an)"),
                  ("now", "Estimation en temps réel (GDPNow)"), ("last", "Dernier chiffre")]


# ---------- 4. moyen terme ----------
def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def recession_prob(spread):
    """Probabilite de recession dans 12 mois selon la pente 10 ans − 3 mois (modele de la Fed de New York, moyenne mensuelle de l'ecart)."""
    return norm_cdf(-0.5333 - 0.6330 * spread) * 100


def recession_path(D: mv.Data, t: int, months: int = 24) -> list:
    s = D.known("T10Y3M", t)
    by = {}
    for ts, v in s[-(months + 2) * 23:]:
        by.setdefault(mw.ym_of(ts), []).append(v)
    out = []
    for ym in sorted(by)[-months:]:
        avg = sum(by[ym]) / len(by[ym])
        out.append({"ym": f"{ym[0]}-{ym[1]:02d}", "spread": round(avg, 3), "prob": round(recession_prob(avg), 1)})
    return out


def curve_move(D: mv.Data, t: int, days: int = 91) -> dict:
    """Mouvement de la courbe sur 3 mois : pentification ou aplatissement, par le haut ou par le bas."""
    a2, a10 = D.at("DGS2", t), D.at("DGS10", t)
    b2, b10 = D.at("DGS2", t - days * DAY), D.at("DGS10", t - days * DAY)
    if None in (a2, a10, b2, b10):
        return {}
    d2, d10 = (a2 - b2) * 100, (a10 - b10) * 100
    ds = d10 - d2
    if abs(ds) < 10:
        kind, txt = "stable", "Pente de la courbe à peu près inchangée sur 3 mois."
    elif ds > 0:
        if d2 < 0 and abs(d2) >= abs(d10):
            kind, txt = "bull_steep", "Pentification par le bas : le taux à 2 ans baisse plus que le 10 ans, le marché anticipe des baisses de la Fed (souvent favorable à la liquidité)."
        else:
            kind, txt = "bear_steep", "Pentification par le haut : le taux à 10 ans monte plus que le 2 ans (prime de risque, inflation ou dette publique) : souvent défavorable aux actifs à risque."
    else:
        if d2 > 0 and d2 >= d10:
            kind, txt = "bear_flat", "Aplatissement par le haut : le taux à 2 ans monte plus que le 10 ans, la Fed est vue plus restrictive."
        else:
            kind, txt = "bull_flat", "Aplatissement par le bas : le taux à 10 ans baisse plus que le 2 ans, le marché anticipe un ralentissement."
    return {"kind": kind, "text": txt, "d2": d2, "d10": d10, "slope": (a10 - a2), "slopeChange": ds}


def medium_term(D: mv.Data, fred: dict, t: int, rstudy=None) -> dict:
    """Vision a 3-12 mois : cycle (recession, regle de Sahm, credit, conditions financieres), inflation (tendance, anticipations),
    taux (courbe, prime de terme, taux reels), liquidite (bilan de la Fed, liquidite nette, masse monetaire), dollar."""
    items, lines, score = [], [], []

    def add(group, name, value, unit, d=2, change=None, cunit="", clabel="", note="", cd=None):
        items.append({"group": group, "name": name, "value": value, "unit": unit, "d": d, "change": change, "changeUnit": cunit, "changeLabel": clabel, "note": note,
                      "cd": cd})
    rp = recession_path(D, t)
    if rp:
        p = rp[-1]["prob"]
        add("Cycle", "Probabilité de récession dans 12 mois (pente 10 ans − 3 mois, modèle de la Fed de New York)", p, "%", 0,
            p - rp[-4]["prob"] if len(rp) >= 4 else None, "point", "en 3 mois", "le modèle a annoncé les récessions passées, avec beaucoup de fausses alertes depuis 2022", cd=0)
    sahm = D.known("SAHMREALTIME", t, last=1)
    if sahm:
        add("Cycle", "Règle de Sahm en temps réel (récession probable à partir de 0,5)", sahm[-1][1], "point", 2)
    un = D.known("UNRATE", t, last=15)
    trig = None
    if len(un) >= 15:
        avg3 = [sum(x[1] for x in un[i - 2:i + 1]) / 3 for i in range(2, len(un))]
        mn = min(avg3[-12:])
        trig = 3 * (mn + 0.5) - un[-1][1] - un[-2][1]
    hy = D.known("BAMLH0A0HYM2", t)
    if hy:
        a, b = D.at("BAMLH0A0HYM2", t), D.at("BAMLH0A0HYM2", t - 91 * DAY)
        add("Cycle", "Écart de taux des obligations à haut rendement", a, "%", 2, (a - b) * 100 if b is not None else None, "pb", "en 3 mois",
            "monte quand les investisseurs craignent les défauts d'entreprises")
    nf_a, nf_b = D.at("NFCI", t), D.at("NFCI", t - 91 * DAY)
    if nf_a is not None:
        add("Cycle", "Conditions financières (Fed de Chicago, au-dessus de 0 = plus tendues que la moyenne)", nf_a, "points", 2,
            nf_a - nf_b if nf_b is not None else None, "point", "en 3 mois")
    core = D.known("CPILFESL", t, last=13)
    a3, a12 = mv._ann(core, 3), mv._ann(core, 12)
    if a3 is not None:
        add("Inflation", "Inflation sous-jacente, rythme annualisé sur 3 mois", a3, "%", 1, note=f"sur un an : {fr(a12)} %")
    for sid, name in (("T5YIFR", "Inflation anticipée dans 5 ans pour 5 ans (ancrage à long terme, cible de la Fed ≈ 2,3 % sur cette mesure)"),
                      ("T5YIE", "Inflation anticipée par le marché sur 5 ans")):
        a, b = D.at(sid, t), D.at(sid, t - 91 * DAY)
        if a is not None:
            add("Inflation", name, a, "%", 2, (a - b) * 100 if b is not None else None, "pb", "en 3 mois")
    for sid, name in (("MICH", "Inflation attendue à un an par les ménages (Michigan)"), ("EXPINF10YR", "Inflation attendue à dix ans (modèle de la Fed de Cleveland)")):
        s = D.known(sid, t, last=4)
        if s:
            add("Inflation", name, s[-1][1], "%", 1 if sid == "MICH" else 2, s[-1][1] - s[0][1] if len(s) >= 4 else None, "point", "en 3 mois")
    cm = curve_move(D, t)
    if cm:
        add("Taux", "Pente de la courbe (10 ans − 2 ans)", cm["slope"], "point", 2, cm["slopeChange"], "pb", "en 3 mois", cm["text"])
    for sid, name, note in (("THREEFYTP10", "Prime de terme du taux à 10 ans (ce que les investisseurs exigent pour prêter longtemps)", "en hausse : dette publique, inflation incertaine ; pèse sur les actifs à risque"),
                            ("DFII10", "Taux réel à 10 ans (après inflation)", "le coût de l'argent pour un actif sans rendement comme le bitcoin")):
        a, b = D.at(sid, t), D.at(sid, t - 91 * DAY)
        if a is not None:
            add("Taux", name, a, "%", 2, (a - b) * 100 if b is not None else None, "pb", "en 3 mois", note)
    net = mw.net_liquidity(D.known("WALCL", t), D.known("WTREGEN", t), D.known("RRPONTSYD", t))
    liq = None
    if net:
        a, b = mw.at(net, t), mw.at(net, t - 91 * DAY)
        liq = (a - b) if a is not None and b is not None else None
        add("Liquidité", "Liquidité nette (bilan de la Fed − compte du Trésor − prises en pension)", a, "Md$", 0, liq, "Md$", "en 3 mois")
    wal_a, wal_b = D.at("WALCL", t), D.at("WALCL", t - 91 * DAY)
    if wal_a is not None and wal_b is not None:
        add("Liquidité", "Bilan de la Fed", wal_a / 1e3, "Md$", 0, (wal_a - wal_b) / 1e3, "Md$", "en 3 mois",
            "en baisse : la Fed retire des liquidités (réduction de son bilan) ; stable ou en hausse : elle a arrêté")
    m2 = D.known("M2SL", t, last=13)
    if len(m2) >= 13:
        add("Liquidité", "Masse monétaire M2 sur un an", mw.pct(m2[-1][1], m2[-13][1]), "%", 1)
    dx_a, dx_b = D.at("DTWEXBGS", t), D.at("DTWEXBGS", t - 91 * DAY)
    dxc = mw.pct(dx_a, dx_b) if dx_a is not None and dx_b is not None else None
    if dx_a is not None:
        add("Dollar", "Dollar face à un large panier de devises", dx_a, "indice", 1, dxc, "%", "en 3 mois")
    # lecture
    if rp:
        p = rp[-1]["prob"]
        lines.append(f"Cycle : probabilité de récession à 12 mois de {fr(p, 0)} % selon la pente des taux"
                     + (f", règle de Sahm à {fr(sahm[-1][1], 2)}" if sahm else "")
                     + (f" (il faudrait un chômage d'environ {fr(trig, 1)} % le mois prochain pour la déclencher)" if trig is not None else "") + ".")
        score.append(-0.5 if p >= 40 else 0.25 if p < 20 else 0.0)
    if a3 is not None and a12 is not None:
        lines.append(f"Inflation : la tendance récente ({fr(a3)} % en rythme annualisé) est {'au-dessous' if a3 < a12 else 'au-dessus'} du chiffre sur un an ({fr(a12)} %)"
                     + (" : la désinflation continue." if a3 < a12 - 0.2 else " : l'inflation repart." if a3 > a12 + 0.2 else " : pas de changement de tendance."))
        score.append(0.5 if a3 < a12 - 0.2 else -0.5 if a3 > a12 + 0.2 else 0.0)
    if cm:
        lines.append("Taux : " + cm["text"])
        score.append({"bull_steep": 0.5, "bear_steep": -0.5, "bear_flat": -0.5, "bull_flat": 0.0}.get(cm["kind"], 0.0))
    if liq is not None:
        lines.append(f"Liquidité : {fr(liq, 0, True)} milliards de dollars de liquidité nette en 3 mois"
                     + (" : plus de dollars disponibles, le décor le plus favorable au bitcoin." if liq > 100 else " : moins de dollars disponibles, vent contraire." if liq < -100 else " : stable."))
        score.append(0.5 if liq > 100 else -0.5 if liq < -100 else 0.0)
    if dxc is not None:
        lines.append(f"Dollar : {fr(dxc, 1, True)} % en 3 mois" + (" : un dollar plus faible soutient la liquidité mondiale." if dxc < -2 else
                                                                    " : un dollar plus fort resserre les conditions financières mondiales." if dxc > 2 else "."))
        score.append(0.5 if dxc < -2 else -0.5 if dxc > 2 else 0.0)
    s = sum(score) if score else None
    return {"items": items, "lines": lines, "score": s, "label": mv.tone_label(s) if s is not None else None, "recession": rp, "sahmTrigger": trig, "curve": cm}


# ---------- 5. scenarios et declencheurs ----------
def scenarios(D: mv.Data, t: int, fedv: dict, mt: dict, calendar: dict, fred: dict) -> list:
    """Trois scenarios avec des declencheurs chiffres et les dates ou ils se verifient (prochaines annonces connues, reunion de la Fed)."""
    nxt = {}
    for e in sorted((calendar or {}).values(), key=lambda x: x["t"]):
        if e["t"] > t and e.get("country") == "USD":
            k = mv.macro_engine.classify(e["title"], "USD")["key"]
            if k in ("CORE_CPI", "NFP", "CORE_PCE", "UNRATE") and k not in nxt:
                nxt[k] = e["t"]

    def when(k, fallback):
        if k in nxt:
            d = datetime.fromtimestamp(nxt[k] / 1000, timezone.utc)
            return f" — prochain chiffre le {d.day} {mw.MONTHS[d.month - 1]}"
        return f" — prochain chiffre {fallback}"
    n = fedv.get("next")
    fed_date = ""
    if n:
        d = datetime.fromtimestamp(n["decision"] / 1000, timezone.utc)
        fed_date = f"réunion de la Fed du {d.day} {mw.MONTHS[d.month - 1]}"
    un = D.known("UNRATE", t, last=1)
    u = un[-1][1] if un else None
    cl = D.known("ICSA", t, last=4)
    c4 = sum(x[1] for x in cl) / len(cl) / 1000 if cl else None
    cuts = fedv.get("cuts")
    trig = mt.get("sahmTrigger")
    cpi_when, job_when = when("CORE_CPI", "vers le milieu du mois (date habituelle)"), when("NFP", "en général le premier vendredi du mois")
    base = {"key": "central", "title": "Scénario central : ce que le marché anticipe",
            "text": (f"Le marché anticipe environ {mv._n_cuts(cuts)} d'ici un an. " if cuts is not None and abs(cuts) >= 0.4 else "Le marché n'anticipe pas de changement net du taux d'ici un an. ")
            + "Tant que les chiffres restent proches du consensus, ce scénario est déjà dans les prix : les cryptos suivent alors surtout leur propre flux (liquidations, ETF, liquidité).",
            "triggers": [f"Inflation sous-jacente mensuelle entre 0,2 et 0,3 %{cpi_when}", f"Créations d'emplois proches du consensus{job_when}"]
            + ([f"Décision conforme aux attentes ({fed_date})"] if fed_date else []), "effect": 0}
    good = {"key": "favorable", "title": "Scénario favorable aux actifs à risque : désinflation sans récession",
            "text": "L'inflation ralentit nettement pendant que l'emploi tient : la Fed peut baisser ses taux plus vite que prévu. Taux et dollar baissent, "
                    "la liquidité augmente : historiquement le meilleur décor pour le bitcoin, et plus encore pour solana.",
            "triggers": [f"Inflation sous-jacente mensuelle ≤ 0,2 % (≈ 2,4 % par an){cpi_when}",
                         "Chômage stable" + (f" (autour de {fr(u, 1)} %)" if u is not None else "") + job_when,
                         "Liquidité nette et masse monétaire en hausse, dollar en baisse"], "effect": 1}
    hot = {"key": "inflation", "title": "Scénario défavorable n° 1 : l'inflation repart",
           "text": "L'inflation sous-jacente remonte : la Fed retarde ou arrête ses baisses, les taux longs et le dollar montent. C'est le scénario le plus "
                   "pénalisant pour les cryptos (actifs sans rendement, sensibles aux taux réels).",
           "triggers": [f"Inflation sous-jacente mensuelle ≥ 0,3 % (≈ 3,7 % par an) deux mois de suite{cpi_when}",
                        "Inflation anticipée à 5 ans en hausse de plus de 0,2 point", "Pétrole en forte hausse (géopolitique)"], "effect": -1}
    scare = {"key": "recession", "title": "Scénario défavorable n° 2 : peur de récession",
             "text": "L'emploi se dégrade vite : la Fed baisse ses taux plus vite, mais d'abord les actifs à risque baissent (ventes forcées, écarts de crédit "
                     "en hausse). Historiquement, le bitcoin baisse avec les actions dans la phase de peur, puis profite des baisses de taux.",
             "triggers": ([f"Chômage ≥ {fr(trig, 1)} % le mois prochain (déclenche la règle de Sahm)"] if trig is not None else ["Règle de Sahm ≥ 0,5"])
             + ([f"Inscriptions au chômage durablement au-dessus de {fr(c4 * 1.15, 0)} milliers par semaine (+15 %)"] if c4 else [])
             + ["Écarts de crédit à haut rendement en hausse de plus de 1 point"], "effect": -1}
    return [base, good, hot, scare]


# ---------- assemblage ----------
def build(ms: int, now: int, fred: dict, calendar: dict, fed: dict, imf: dict, crossD: dict, crypto_daily: dict,
          study=None, rstudy=None, reconstructed: bool | None = None) -> dict:
    a, b = ms, next_month(ms)
    current = a <= now < b
    t = min(now, b)
    lagged = not current
    if reconstructed is None:
        reconstructed = not current and now - b > 3 * DAY
    D = mv.Data(fred)
    fedv = mv.fed_view(D, t, (fed or {}).get("meetings") or [], lagged, change_days=max(1, int((t - a) / DAY)), change_label="Depuis le début du mois")
    reg = mv.regime_at(D, t, lagged=lagged)
    reg["trail"] = mv.regime_trail(D, t, 12, lagged_now=lagged)
    reg["text"] = mv.QUADS[reg["quad"]][1] if reg["quad"] else ""
    mt = medium_term(D, fred, t, rstudy)
    themes = dashboard_changes(fred, a, t, lagged)
    out = {"month": month_key(a), "label": month_label(a), "start": a, "end": b, "current": current, "final": now >= b + 3 * DAY, "built": now,
           "reconstructed": reconstructed, "events": month_events(calendar, fred, a, b, now), "themes": themes,
           "verdict": mw.verdict(themes, []), "markets": mw.markets(crypto_daily or {}, crossD or {}, a, b, now),
           "surprises": mv.surprises(calendar, fred, t, days=max(7, int((t - a) / DAY) + 1)),
           "fed": fedv, "sep": sep_table(fred, t), "statement": statements(fed, a, b), "comms": mv.fed_comms(fed, a, b),
           "consensus": consensus_table(fred, imf, D, t, fedv), "consensusCols": CONSENSUS_COLS, "imfUpdated": (imf or {}).get("t"),
           "regime": reg, "regimeStudy": rstudy, "medium": mt, "study": study, "upcoming": mv.upcoming(calendar, fred, t, t + 21 * DAY, D) if current else [],
           "hasFred": any(fred.get(k) for k in ("CPIAUCSL", "UNRATE", "DGS10"))}
    out["scenarios"] = scenarios(D, t, fedv, mt, calendar, fred)
    out["lines"] = narrative(out)
    out["summary"] = summary_text(out)
    return out


def narrative(r: dict) -> list:
    L = []
    reg = r["regime"]
    if reg.get("quad"):
        L.append({"title": "Le régime", "text": f"{reg['label']} (croissance {mv.momentum_word(reg['g'])}, inflation {mv.momentum_word(reg['i'])}). {reg['text']}"})
    ev = [e for e in r["events"] if e.get("z") is not None]
    if ev:
        hot = [e for e in ev if e["z"] > 0.25]
        cold = [e for e in ev if e["z"] < -0.25]
        biggest = max(ev, key=lambda e: abs(e["z"]))
        L.append({"title": "Le mois face au consensus",
                  "text": f"{len(ev)} chiffre{'s' if len(ev) > 1 else ''} américain{'s' if len(ev) > 1 else ''} comparé{'s' if len(ev) > 1 else ''} au consensus : "
                          f"{len(hot)} au-dessus (plus solides ou plus chauds), {len(cold)} en dessous, {len(ev) - len(hot) - len(cold)} conforme{'s' if len(ev) - len(hot) - len(cold) > 1 else ''}. "
                          f"Plus grosse surprise : {biggest['label']} ({fx(biggest['actual']['text']) if biggest.get('actual') else ''} pour un consensus de {fx(biggest['forecast'])})."})
    f = r["fed"]
    st = r.get("statement") or {}
    fed_txt = " ".join(f.get("text") or [])
    if st.get("decision"):
        d = datetime.fromtimestamp(st["t"] / 1000, timezone.utc)
        fed_txt += (f" Dernier communiqué ({d.day} {mw.MONTHS[d.month - 1]}) : {st['decision']['move']} du taux"
                    + (f" de {st['decision']['by']} point" if st["decision"].get("by") else "") + f", ton {st['tone']['label']}."
                    + (f" {st['toneText']}" if st.get("toneText") else "")
                    + (" Au moins un membre a voté contre : le comité n'est pas unanime (détail plus bas)." if st.get("dissents") else ""))
    sep = r.get("sep") or {}
    if sep.get("rangeLow") and sep.get("rangeHigh"):
        y = sep["years"][1] if len(sep["years"]) > 1 else sep["years"][0]
        lo, hi = sep["rangeLow"].get(y), sep["rangeHigh"].get(y)
        if lo is not None and hi is not None:
            fed_txt += f" Désaccord entre les membres : pour fin {y}, leurs projections de taux vont de {fr(lo, 2)} à {fr(hi, 2)} % ({fr((hi - lo) * 100, 0)} points de base d'écart)."
    if fed_txt:
        L.append({"title": "La Fed", "text": fed_txt.strip()})
    cons = r.get("consensus") or []
    us = next((x for x in cons if x["name"].startswith("Croissance des États-Unis")), None)
    infl = next((x for x in cons if x["name"].startswith("Inflation des États-Unis")), None)
    if us or infl:
        bits = []
        if us and us["cols"].get("fed") is not None:
            bits.append(f"croissance {fr(us['cols']['fed'])} % selon la Fed" + (f", {fr(us['cols']['imf'])} % selon le FMI" if us["cols"].get("imf") is not None else "")
                        + (f", {fr(us['cols']['now'])} % en rythme annualisé pour le trimestre en cours (GDPNow)" if us["cols"].get("now") is not None else ""))
        if infl and infl["cols"].get("fed") is not None:
            bits.append(f"inflation sous-jacente {fr(infl['cols']['fed'])} % selon la Fed" + (f", {fr(infl['cols']['imf'])} % (inflation totale) selon le FMI" if infl["cols"].get("imf") is not None else ""))
        if bits:
            L.append({"title": "Les projections à prendre en compte", "text": "Pour cette année : " + " ; ".join(bits) + ". Le tableau compare la Fed, le FMI, le marché et les ménages."})
    mt = r.get("medium") or {}
    if mt.get("lines"):
        L.append({"title": "Vision à moyen terme (3 à 12 mois)", "text": " ".join(mt["lines"]) + (f" Ensemble : {mt['label']} pour les actifs à risque." if mt.get("label") else "")})
    return L


def summary_text(r: dict) -> str:
    """Version texte (Telegram, contexte de Claude)."""
    L = [f"Analyse macro du mois : {r['label']}" + (" (en cours)" if r["current"] else "")]
    for p in r["lines"]:
        L += ["", f"{p['title']} : {p['text']}"]
    sep = r.get("sep") or {}
    if sep.get("rows"):
        L += ["", "Projections médianes de la Fed (" + ", ".join(sep["years"]) + (", long terme" if sep.get("longRun") is not None else "") + ") :"]
        for row in sep["rows"]:
            L.append(f"• {row['name']} : " + " / ".join(fr(row["values"].get(y), 1 if row["sid"] != "FEDTARMD" else 2) for y in sep["years"])
                     + (f" / {fr(sep['longRun'], 2)}" if row["sid"] == "FEDTARMD" and sep.get("longRun") is not None else ""))
    st = r.get("statement") or {}
    if st.get("diff"):
        d = st["diff"]
        L += ["", "Ce qui a changé dans le communiqué de la Fed :"]
        for ch in d["changed"][:6]:
            L.append("• " + " ".join((f"[-{x}-]" if s == "-" else f"{{+{x}+}}" if s == "+" else x) for s, x in ch))
        L += [f"• ajouté : {x}" for x in d["added"][:4]] + [f"• retiré : {x}" for x in d["removed"][:4]]
    if r.get("scenarios"):
        L += ["", "Scénarios et déclencheurs :"]
        for s in r["scenarios"]:
            L.append(f"• {s['title']} : {s['text']} Déclencheurs : " + " ; ".join(s["triggers"]) + ".")
    if r.get("markets"):
        L += ["", "Marchés sur le mois : " + " ; ".join(f"{m['name']} {fr(m['chg'], 0 if m['unit'] == 'pb' else 1, True)} {'points de base' if m['unit'] == 'pb' else '%'}"
                                                       for m in r["markets"] if m.get("chg") is not None)]
    if r.get("banks", {}).get("rows"):
        L += ["", "Rapports des banques (recherche de Claude) :"]
        L += [f"• {b.get('bank')} ({b.get('date', '')}) : " + "; ".join(f"{k} {v}" for k, v in b.items() if k not in ("bank", "date", "source") and v) for b in r["banks"]["rows"]]
    L += ["", "Lectures par règles classiques reliées aux chiffres, non validées par le backtest du terminal : ce ne sont pas des prévisions."]
    return "\n".join(L)


# ---------- rapports des banques (reponse de Claude) ----------
BANK_KEYS = ("bank", "date", "cuts", "fedEnd", "us10y", "recession", "spx", "dollar", "crypto", "source")
BANK_LABELS = {"cuts": "baisses de la Fed d'ici 12 mois", "fedEnd": "taux de la Fed fin de l'année prochaine", "us10y": "taux à 10 ans en fin d'année",
               "recession": "probabilité de récession", "spx": "objectif S&P 500", "dollar": "dollar", "crypto": "bitcoin et cryptos"}


def parse_banks(text: str):
    """Reponse de Claude -> (texte sans le tableau, lignes du tableau <banques>). Lignes incompletes ou sans nom ignorees ;
    une source qui n'est pas une adresse web est retiree."""
    import re
    m = re.search(r"<banques>(.*?)</banques>", text or "", re.S | re.I)
    if not m:
        return (text or "").strip(), []
    rows = []
    for line in m.group(1).splitlines():
        cells = [c.strip().strip("*").strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not cells[0] or cells[0].lower().startswith(("banque", "---", ":--")) or set(cells[0]) <= set("-: "):
            continue
        row = {k: (cells[i] if i < len(cells) and cells[i] not in ("?", "") else "") for i, k in enumerate(BANK_KEYS)}
        if row["source"] and not re.match(r"https?://", row["source"]):
            row["source"] = ""
        rows.append(row)
    clean = (text[:m.start()] + text[m.end():]).strip()
    return clean, rows[:15]
