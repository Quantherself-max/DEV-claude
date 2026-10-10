"""Bilan macro de la semaine (V18) : ce qui a ete publie, les chiffres, et ce que cela engendre. Module PUR (aucun acces reseau).

Une semaine = du lundi 00 h UTC au lundi suivant. Le bilan rassemble :
  1. les ANNONCES de la semaine (calendrier : consensus et chiffre precedent ; chiffre PUBLIE recalcule a partir de la base officielle FRED pour les
     grandes statistiques americaines ; ecart au consensus ; reaction MESUREE du taux a 10 ans, du dollar et du bitcoin dans les 15 minutes) ;
  2. un TABLEAU DE BORD par theme (inflation, emploi, croissance, Fed et taux, dollar, liquidite, risque et credit, energie) avec la derniere valeur,
     sa variation et une lecture ;
  3. les MARCHES de la semaine (bitcoin, ether, solana, indices americains, or, dollar, taux a 10 ans, volatilite) et la crypto (dominance, sentiment,
     stablecoins, rotation) ;
  4. CE QUE CELA ENGENDRE : une lecture par regles classiques (ce que chaque theme implique pour les actifs a risque), resumee en un « vent macro »,
     puis une MESURE sur l'historique du bitcoin : chacun de ces moteurs a-t-il vraiment fait une difference sur la semaine suivante ?
  5. la SEMAINE PROCHAINE : les annonces a surveiller, avec ce qu'un chiffre au-dessus ou en dessous du consensus impliquerait.

Les regles de lecture ne sont pas validees par le backtest du terminal ; la mesure le dit franchement quand un moteur ne se distingue pas du hasard."""
import math
import re
from bisect import bisect_right
from datetime import datetime, timezone

from . import macro as macro_engine

MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
WEEK = 7 * DAY


# ---------- semaines ----------
def week_start(t_ms: int) -> int:
    """Lundi 00 h UTC de la semaine qui contient t (le 1er janvier 1970 etait un jeudi)."""
    d = t_ms // DAY
    return (d - (d + 3) % 7) * DAY


def week_key(ws: int) -> str:
    return datetime.fromtimestamp(ws / 1000, timezone.utc).strftime("%Y-%m-%d")


def parse_week(key: str) -> int:
    t = int(datetime.strptime(key, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    return week_start(t)


# ---------- series (date d'observation, valeur) ----------
def upto(series, t_ms, lag_days: float = 0.0):
    """Observations connues a l'instant t (date d'observation + delai de publication <= t)."""
    if not series:
        return []
    ts = [x[0] for x in series]
    return series[:bisect_right(ts, t_ms - lag_days * DAY)]


def at(series, t_ms):
    """Derniere valeur dont la date est <= t."""
    s = upto(series, t_ms)
    return s[-1][1] if s else None


def by_month(series) -> dict:
    out = {}
    for t, v in series or []:
        d = datetime.fromtimestamp(t / 1000, timezone.utc)
        out[(d.year, d.month)] = v
    return out


def month_shift(ym, k):
    y, m = ym
    m += k
    while m <= 0:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return (y, m)


def ym_of(t_ms):
    d = datetime.fromtimestamp(t_ms / 1000, timezone.utc)
    return (d.year, d.month)


def pct(a, b):
    return (a / b - 1.0) * 100.0 if a is not None and b else None


def mom(series, ym):
    m = by_month(series)
    return pct(m.get(ym), m.get(month_shift(ym, -1)))


def yoy(series, ym):
    m = by_month(series)
    return pct(m.get(ym), m.get(month_shift(ym, -12)))


def last_ym(series):
    return ym_of(series[-1][0]) if series else None


def change_over(series, t_ms, days):
    """(valeur a t, valeur days jours plus tot) sur les observations connues."""
    a, b = at(series, t_ms), at(series, t_ms - days * DAY)
    return a, b


MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def month_name(ym):
    return f"{MONTHS[ym[1] - 1]} {ym[0]}" if ym else ""


def fr(x, d=1, sign=False):
    if x is None:
        return "—"
    s = f"{x:+,.{d}f}" if sign else f"{x:,.{d}f}"
    return s.replace(",", " ").replace(".", ",")


# ---------- 1. annonces : chiffre publie retrouve dans FRED ----------
# (motif sur le titre du calendrier, serie FRED, calcul, ecart minimal en jours entre le debut de la periode mesuree et la publication)
EVENT_MAP = [
    (r"^core cpi m/m", "CPILFESL", "mom", 35), (r"^core cpi y/y", "CPILFENS", "yoy", 35),
    (r"^cpi m/m", "CPIAUCSL", "mom", 35), (r"^cpi y/y", "CPIAUCNS", "yoy", 35),
    (r"^core pce price index m/m", "PCEPILFE", "mom", 35), (r"^core pce price index y/y", "PCEPILFE", "yoy", 35),
    (r"^pce price index m/m", "PCEPI", "mom", 35), (r"^pce price index y/y", "PCEPI", "yoy", 35),
    (r"^ppi m/m", "PPIFIS", "mom", 35),
    (r"^non-?farm employment change", "PAYEMS", "diffK", 28), (r"^unemployment rate", "UNRATE", "level", 28),
    (r"^average hourly earnings m/m", "CES0500000003", "mom", 28),
    (r"^retail sales m/m", "RSAFS", "mom", 35), (r"^core retail sales m/m", "RSFSXMV", "mom", 35),
    (r"^jolts job openings", "JTSJOL", "levelM", 55),
    (r"^(advance |prelim |final )?gdp q/q", "A191RL1Q225SBEA", "quarter", 100),
    (r"^unemployment claims", "ICSA", "claims", 4),
    (r"^federal funds rate", "DFEDTARU", "rate", 0),
]


def _decimals(*strs):
    for s in strs:
        m = re.search(r"-?\d+(?:\.(\d+))?", s or "")
        if m:
            return len(m.group(1) or "")
    return 1


def _value_for(series, kind, ym):
    m = by_month(series)
    if kind == "mom":
        return pct(m.get(ym), m.get(month_shift(ym, -1)))
    if kind == "yoy":
        return pct(m.get(ym), m.get(month_shift(ym, -12)))
    if kind == "diffK":
        a, b = m.get(ym), m.get(month_shift(ym, -1))
        return a - b if a is not None and b is not None else None
    if kind == "level":
        return m.get(ym)
    if kind == "levelM":
        return m[ym] / 1000.0 if ym in m else None
    return None


def published(ev: dict, fred: dict):
    """Chiffre publie d'une annonce americaine, recalcule a partir de FRED : {value, text, period, sid, check} ou None (pas de correspondance,
    ou FRED pas encore a jour). La periode attendue se deduit de la date de l'annonce ; si le chiffre « precedent » du calendrier correspond
    mieux a la periode d'avant (publication retardee), on decale d'un cran."""
    if ev.get("country") != "USD":
        return None
    title = ev.get("title", "").lower().strip()
    for pat, sid, kind, gap in EVENT_MAP:
        if re.search(pat, title):
            break
    else:
        return None
    s = fred.get(sid)
    if not s:
        return None
    t = ev["t"]
    dec = _decimals(ev.get("forecast"), ev.get("previous"))
    if kind == "claims":
        obs = [x for x in s if t - 10 * DAY <= x[0] <= t - gap * DAY]
        if not obs:
            return None
        v = float(round(obs[-1][1] / 1000.0))
        return {"value": v, "text": f"{v:.0f}K", "period": "semaine au " + datetime.fromtimestamp(obs[-1][0] / 1000, timezone.utc).strftime("%d/%m"), "sid": sid}
    if kind == "rate":
        after = [x for x in s if t + DAY <= x[0] <= t + 6 * DAY]                     # nouvelle fourchette effective le lendemain
        if not after:
            return None
        v = after[0][1]
        return {"value": v, "text": f"{v:.2f}%", "period": "décision du jour", "sid": sid}
    if kind == "quarter":
        d = datetime.fromtimestamp(t / 1000, timezone.utc)
        q0 = (d.year, (d.month - 1) // 3 * 3 + 1)
        ref = month_shift(q0, -3)                                                     # trimestre precedent celui de l'annonce
        v = by_month(s).get(ref)
        if v is None:
            return None
        return {"value": v, "text": f"{v:.{dec}f}%", "period": f"{(ref[1] - 1) // 3 + 1}e trimestre {ref[0]}", "sid": sid}
    ref = ym_of(t - gap * DAY)
    pnum = ev.get("pnum")
    # Garde-fou : la periode retenue doit avoir, juste avant elle, le chiffre « precedent » annonce par le calendrier (aux revisions pres).
    # Sinon FRED n'est pas encore a jour (on afficherait l'ancien chiffre comme s'il venait d'etre publie) : on n'affiche rien.
    tol = {"diffK": 75.0, "levelM": 0.35}.get(kind, 0.15)
    best = None
    for c in [ref]:                    # pas de repli sur la periode d'avant : les chiffres mensuels se ressemblent trop pour les distinguer surement
        v = _value_for(s, kind, c)
        if v is None:
            continue
        prev = _value_for(s, kind, month_shift(c, -1))
        if pnum is not None and (prev is None or abs(prev - pnum) > tol):
            continue
        dist = abs(prev - pnum) if pnum is not None else 0.0
        if best is None or dist < best[2]:
            best = (c, v, dist)
    if best is None:
        return None
    c, v, _ = best
    if kind == "diffK":
        text = f"{v:.0f}K"
    elif kind == "levelM":
        text = f"{v:.2f}M"
    else:
        text = f"{v:.{dec}f}%"
    return {"value": round(v, dec) if kind not in ("diffK",) else round(v), "text": text, "period": month_name(c), "sid": sid,
            "late": c != ref}


PERIOD = [(r"m/m", "sur un mois"), (r"y/y", "sur un an"), (r"q/q", "sur un trimestre, rythme annualisé")]


def event_label(ev, cls):
    lab = cls["label"] if cls["key"] != "OTHER" else ev["title"]
    for pat, txt in PERIOD:
        if re.search(pat, ev["title"].lower()):
            return f"{lab} {txt}"
    return lab


READ = {
    "inflation": ("Inflation plus forte que prévu : la Fed a moins de marge pour baisser ses taux. En général le taux à 10 ans et le dollar montent, ce qui pèse sur les actifs à risque comme les cryptos.",
                  "Inflation plus faible que prévu : la Fed garde de la marge pour baisser ses taux. En général le taux à 10 ans et le dollar baissent, ce qui soutient les actifs à risque."),
    "labor_jobs": ("Emploi plus solide que prévu : l'économie tient, mais la Fed a moins de raisons de baisser ses taux (taux et dollar plutôt en hausse).",
                   "Emploi plus faible que prévu : la Fed a plus de raisons de baisser ses taux (soutien à la liquidité) ; un ralentissement trop marqué ferait toutefois craindre une récession."),
    "labor_unemp": ("Chômage plus élevé que prévu : le marché du travail se refroidit, la Fed a plus de raisons de baisser ses taux ; au-delà d'un certain point, c'est la peur de la récession qui domine.",
                    "Chômage plus bas que prévu : marché du travail solide, moins de raisons pour la Fed de baisser ses taux."),
    "labor_claims": ("Plus d'inscriptions au chômage que prévu : signe de refroidissement du marché du travail, la Fed a plus de raisons de baisser ses taux.",
                     "Moins d'inscriptions au chômage que prévu : marché du travail solide, moins de raisons pour la Fed de baisser ses taux."),
    "growth": ("Activité plus solide que prévu : bon pour les bénéfices des entreprises, mais moins de baisses de taux à attendre.",
               "Activité plus faible que prévu : l'économie ralentit ; les baisses de taux deviennent plus probables, avec un risque de récession en toile de fond."),
}


def read_event(cls, pub, ev):
    """Ce que le chiffre veut dire (lecture classique), selon son ecart au consensus."""
    if cls["cat"] == "fed" and pub and ev.get("pnum") is not None and cls["key"] == "FOMC":
        d = pub["value"] - ev["pnum"]
        if d < -1e-9:
            return -1, "Baisse des taux de la Fed : l'argent devient moins cher, ce qui soutient la liquidité et les actifs à risque à terme. L'effet du jour dépend de ce qui était attendu et du ton de la conférence de presse."
        if d > 1e-9:
            return 1, "Hausse des taux de la Fed : l'argent devient plus cher, ce qui pèse sur la liquidité et les actifs à risque."
        return 0, "Taux inchangés : ce sont le communiqué et la conférence de presse (baisses à venir ou non) qui donnent le ton."
    if not pub or ev.get("fnum") is None:
        return None, ""
    dec = _decimals(ev.get("forecast"), ev.get("previous"))
    tol = 0.5 * 10 ** -dec if pub["sid"] not in ("PAYEMS", "ICSA", "JTSJOL") else (5.0 if pub["sid"] != "JTSJOL" else 0.05)
    diff = pub["value"] - ev["fnum"]
    if abs(diff) <= tol:
        return 0, "Conforme au consensus : peu de surprise, le marché l'avait déjà intégré."
    up = diff > 0
    key = cls["key"]
    if cls["cat"] == "inflation":
        txt = READ["inflation"][0 if up else 1]
    elif key == "CLAIMS":
        txt = READ["labor_claims"][0 if up else 1]
    elif key == "UNRATE":
        txt = READ["labor_unemp"][0 if up else 1]
    elif cls["cat"] == "labor":
        txt = READ["labor_jobs"][0 if up else 1]
    elif cls["cat"] == "growth":
        txt = READ["growth"][0 if up else 1]
    else:
        return (1 if up else -1), ("Au-dessus" if up else "En dessous") + " du consensus."
    return (1 if up else -1), txt


def reaction_text(r):
    if not r:
        return ""
    cr, b = r.get("cross") or {}, r.get("btc") or {}
    parts = []
    if "US10Y" in cr:
        parts.append(f"taux à 10 ans {fr(cr['US10Y'], 1, True)} point{'s' if abs(cr['US10Y']) >= 2 else ''} de base")
    if "DXY" in cr:
        parts.append(f"dollar {fr(cr['DXY'], 2, True)} %")
    if b.get("r15") is not None:
        parts.append(f"bitcoin {fr(b['r15'], 2, True)} %")
    if not parts:
        return ""
    lab = r.get("impulseLabel")
    return "Réaction mesurée dans les 15 minutes : " + ", ".join(parts) + (f" (surprise lue par le marché : {lab})." if lab and lab != "inconnue" else ".")


def week_events(calendar: dict, fred: dict, ws: int, we: int, now: int):
    out = []
    for e in sorted(calendar.values(), key=lambda x: x["t"]):
        if not (ws <= e["t"] < we):
            continue
        cls = macro_engine.classify(e["title"], e["country"])
        if not ((e["country"] == "USD" and e.get("impact", 0) >= 2 and cls["key"] != "OTHER") or e.get("impact", 0) == 3):
            continue
        past = e["t"] <= now
        pub = e.get("actual") or (published(e, fred) if past else None)
        dirn, txt = read_event(cls, pub, e) if past else (None, "")
        surprise, stext = None, ""
        if pub and e.get("fnum") is not None and cls["cat"] != "fed":
            dec = _decimals(e.get("forecast"), e.get("previous"))
            surprise = round(pub["value"] - e["fnum"], dec)
            stext = (f"{surprise:+.{dec}f}" + (e.get("unit") or "")).replace("-", "−")
        r = e.get("reaction")
        if r is not None and r.get("cross") is not None:
            imp = macro_engine.impulse(r.get("cross") or {})
            r = {**r, "impulse": imp, "impulseLabel": macro_engine.impulse_label(imp)}
        exp = macro_engine.expectation(e, cls) if not past else None
        out.append({"id": e["id"], "t": e["t"], "country": e["country"], "title": e["title"], "label": event_label(e, cls), "cat": cls["cat"],
                    "key": cls["key"], "impact": e.get("impact", 0), "w": cls["w"], "forecast": e.get("forecast") or "", "previous": e.get("previous") or "",
                    "actual": pub, "surprise": surprise, "surpriseText": stext, "dir": dirn, "read": txt, "reaction": r, "reactionText": reaction_text(r), "past": past,
                    "scenUp": exp["scen_up"] if exp else "", "scenDn": exp["scen_dn"] if exp else ""})
    return out


# ---------- 2. tableau de bord ----------
def _item(name, value, unit, d=1, change=None, change_unit="", change_label="", note="", date=None, cd=None):
    return {"name": name, "value": value, "unit": unit, "d": d, "change": change, "changeUnit": change_unit, "changeLabel": change_label,
            "note": note, "date": date, "cd": d if cd is None else cd}


def _date(series):
    return series[-1][0] if series else None


def dashboard(fred: dict, t: int, lagged: bool = False):
    """Themes du tableau de bord a l'instant t. lagged : bilan reconstruit apres coup, on n'utilise que les chiffres deja publies a t."""
    from data.fred import SERIES
    S = {k: upto(v, t, SERIES.get(k, ("", "D", 0))[2] if lagged else 0) for k, v in fred.items()}
    themes = []

    # inflation
    items, score, read = [], None, ""
    cpi, core, coreSA, pce = S.get("CPIAUCNS"), S.get("CPILFENS"), S.get("CPILFESL"), S.get("PCEPILFE")
    ym = last_ym(cpi)
    if ym:
        v, p = yoy(cpi, ym), yoy(cpi, month_shift(ym, -1))
        items.append(_item("Inflation sur un an (prix à la consommation)", v, "%", 1, (v - p) if v is not None and p is not None else None, "point", "vs mois précédent",
                           f"mois de {month_name(ym)}", _date(cpi)))
    core_y = None
    if core:
        ymc = last_ym(core)
        core_y, p = yoy(core, ymc), yoy(core, month_shift(ymc, -1))
        items.append(_item("Inflation sous-jacente sur un an (hors alimentation et énergie)", core_y, "%", 1,
                           (core_y - p) if core_y is not None and p is not None else None, "point", "vs mois précédent", f"mois de {month_name(ymc)}", _date(core)))
    ann3 = None
    if coreSA and len(coreSA) >= 4:
        a, b = coreSA[-1][1], coreSA[-4][1]
        ann3 = ((a / b) ** 4 - 1) * 100 if b else None
        items.append(_item("Inflation sous-jacente sur 3 mois, rythme annualisé", ann3, "%", 1, note="tendance récente : à comparer au chiffre sur un an", date=_date(coreSA)))
    if pce:
        ymp = last_ym(pce)
        items.append(_item("Prix des dépenses de consommation sous-jacents sur un an (mesure préférée de la Fed, cible 2 %)", yoy(pce, ymp), "%", 1,
                           note=f"mois de {month_name(ymp)}", date=_date(pce)))
    be = S.get("T10YIE")
    if be:
        a, b = change_over(be, t, 28)
        items.append(_item("Inflation anticipée par le marché sur 10 ans", a, "%", 2, (a - b) * 100 if a is not None and b is not None else None, "pb", "en 4 semaines",
                           date=_date(be)))
    if ann3 is not None and core_y is not None:
        gap = ann3 - core_y
        if gap > 0.3:
            score, read = -1.0, f"L'inflation sous-jacente RÉACCÉLÈRE (rythme récent {fr(ann3)} % contre {fr(core_y)} % sur un an) : la Fed a moins de marge pour baisser ses taux, défavorable aux actifs à risque."
        elif gap < -0.3:
            score, read = 1.0, f"L'inflation sous-jacente RALENTIT (rythme récent {fr(ann3)} % contre {fr(core_y)} % sur un an) : la Fed garde de la marge pour baisser ses taux, favorable aux actifs à risque."
        else:
            score = -0.5 if core_y > 3.0 else 0.0
            read = f"Inflation sous-jacente stable autour de {fr(core_y)} % sur un an" + (" : encore loin de la cible de 2 %, la Fed reste prudente." if core_y > 3.0 else " : pas de changement de cap pour la Fed.")
    themes.append({"key": "inflation", "title": "Inflation", "items": items, "score": score, "read": read})

    # emploi
    items, score, read = [], None, ""
    un, pay, cl, ahe, jo = S.get("UNRATE"), S.get("PAYEMS"), S.get("ICSA"), S.get("CES0500000003"), S.get("JTSJOL")
    sahm, un3 = None, None
    if un and len(un) >= 4:
        un3 = un[-1][1] - un[-4][1]
        items.append(_item("Taux de chômage", un[-1][1], "%", 1, un3, "point", "en 3 mois", f"mois de {month_name(last_ym(un))}", _date(un)))
        if len(un) >= 15:
            avg3 = [sum(x[1] for x in un[i - 2:i + 1]) / 3 for i in range(2, len(un))]
            sahm = avg3[-1] - min(avg3[-13:-1])
            items.append(_item("Règle de Sahm (signal de récession à partir de 0,5)", sahm, "point", 2,
                               note="moyenne du chômage sur 3 mois moins son plus bas des 12 mois précédents"))
    pay3 = None
    if pay and len(pay) >= 4:
        pay3 = (pay[-1][1] - pay[-4][1]) / 3
        items.append(_item("Créations d'emplois, moyenne sur 3 mois", pay3, "milliers", 0, pay[-1][1] - pay[-2][1], "milliers", "dernier mois",
                           f"mois de {month_name(last_ym(pay))}", _date(pay)))
    clr = None
    if cl and len(cl) >= 17:
        a4, b4 = sum(x[1] for x in cl[-4:]) / 4, sum(x[1] for x in cl[-17:-13]) / 4
        clr = pct(a4, b4)
        items.append(_item("Inscriptions hebdomadaires au chômage, moyenne sur 4 semaines", a4 / 1000, "milliers", 0, clr, "%", "vs 3 mois plus tôt", date=_date(cl)))
    if ahe:
        y = last_ym(ahe)
        items.append(_item("Salaire horaire moyen sur un an", yoy(ahe, y), "%", 1, note=f"mois de {month_name(y)}", date=_date(ahe)))
    if jo:
        items.append(_item("Offres d'emploi (enquête JOLTS)", jo[-1][1] / 1000, "millions", 2, (jo[-1][1] - jo[-2][1]) / 1000 if len(jo) >= 2 else None, "million",
                           "vs mois précédent", f"mois de {month_name(last_ym(jo))}", _date(jo), cd=2))
    if sahm is not None and sahm >= 0.5:
        score, read = -1.0, f"La règle de Sahm est déclenchée ({fr(sahm, 2)}) : historiquement, une récession américaine était en cours ou proche. Les baisses de taux arrivent, mais la peur de la récession pèse d'abord sur les actifs à risque."
    elif (un3 is not None and un3 >= 0.2) or (clr is not None and clr > 10):
        score, read = 0.5, "Le marché du travail se refroidit (chômage ou inscriptions au chômage en hausse) : la Fed a plus de raisons de baisser ses taux, plutôt favorable à la liquidité tant que cela reste modéré."
    elif pay3 is not None:
        score = 0.0
        read = f"Marché du travail solide ({fr(pay3, 0)} milliers d'emplois créés par mois en moyenne sur 3 mois) : pas d'urgence pour la Fed à baisser ses taux." if pay3 >= 120 else \
            f"Créations d'emplois modestes ({fr(pay3, 0)} milliers par mois sur 3 mois) : l'emploi ralentit doucement, sans signal de récession."
    themes.append({"key": "emploi", "title": "Emploi", "items": items, "score": score, "read": read})

    # croissance
    items, read = [], ""
    gdp, rs = S.get("A191RL1Q225SBEA"), S.get("RSAFS")
    if gdp:
        ref = ym_of(gdp[-1][0])
        items.append(_item("Croissance du produit intérieur brut réel (rythme annualisé)", gdp[-1][1], "%", 1, gdp[-1][1] - gdp[-2][1] if len(gdp) >= 2 else None,
                           "point", "vs trimestre précédent", f"{(ref[1] - 1) // 3 + 1}e trimestre {ref[0]}", _date(gdp)))
        g = gdp[-1][1]
        read = ("L'économie américaine se contracte : risque de récession." if g < 0 else "Croissance faible : l'économie ralentit." if g < 1
                else "Croissance solide : l'économie tient." if g < 3.5 else "Croissance forte : peu de raisons pour la Fed d'assouplir.")
    if rs and len(rs) >= 4:
        items.append(_item("Ventes au détail sur 3 mois", pct(rs[-1][1], rs[-4][1]), "%", 1, mom(rs, last_ym(rs)), "%", "dernier mois", f"mois de {month_name(last_ym(rs))}", _date(rs)))
    themes.append({"key": "croissance", "title": "Croissance", "items": items, "score": None, "read": read})

    # Fed et taux
    items, score, read = [], None, ""
    lo, hi, d2, d10, real = S.get("DFEDTARL"), S.get("DFEDTARU"), S.get("DGS2"), S.get("DGS10"), S.get("DFII10")
    mid = None
    if lo and hi:
        mid = (lo[-1][1] + hi[-1][1]) / 2
        b = at(hi, t - 84 * DAY)
        items.append(_item(f"Taux directeur de la Fed : {fr(lo[-1][1], 2)} – {fr(hi[-1][1], 2)} %", hi[-1][1], "%", 2, (hi[-1][1] - b) * 100 if b is not None else None,
                           "pb", "en 12 semaines", date=_date(hi)))
    if d2:
        a, b = change_over(d2, t, 7)
        items.append(_item("Taux d'État à 2 ans (suit les anticipations sur la Fed)", a, "%", 2, (a - b) * 100 if a is not None and b is not None else None, "pb", "sur la semaine",
                           date=_date(d2)))
        if mid is not None and a is not None:
            sp = a - mid
            items.append(_item("Écart taux à 2 ans − taux de la Fed", sp, "point", 2,
                               note="nettement négatif : le marché anticipe des baisses de taux ; positif : des hausses"))
    if d10:
        a, b = change_over(d10, t, 7)
        items.append(_item("Taux d'État à 10 ans", a, "%", 2, (a - b) * 100 if a is not None and b is not None else None, "pb", "sur la semaine", date=_date(d10)))
        if d2:
            items.append(_item("Pente 10 ans − 2 ans", a - at(d2, t) if a is not None and at(d2, t) is not None else None, "point", 2,
                               note="négative (courbe inversée) : signal classique de ralentissement à venir"))
    if real:
        a, b = change_over(real, t, 28)
        ch = (a - b) * 100 if a is not None and b is not None else None
        items.append(_item("Taux réel à 10 ans (après inflation)", a, "%", 2, ch, "pb", "en 4 semaines", date=_date(real)))
        if ch is not None:
            if ch > 15:
                score, read = -1.0, f"Le taux réel à 10 ans monte ({fr(ch, 0, True)} points de base en 4 semaines) : détenir un actif sans rendement (bitcoin, or) coûte plus cher, défavorable."
            elif ch < -15:
                score, read = 1.0, f"Le taux réel à 10 ans baisse ({fr(ch, 0, True)} points de base en 4 semaines) : l'argent redevient moins cher, favorable aux actifs à risque et sans rendement."
            else:
                score, read = 0.0, "Taux réels à peu près stables sur 4 semaines : pas de pression particulière de ce côté."
    if mid is not None and d2 and at(d2, t) is not None:
        sp = at(d2, t) - mid
        read += (" Le taux à 2 ans est nettement sous le taux de la Fed : le marché anticipe des baisses de taux." if sp < -0.25
                 else " Le taux à 2 ans est au-dessus du taux de la Fed : le marché n'exclut pas des hausses." if sp > 0.25 else "")
    themes.append({"key": "taux", "title": "Fed et taux", "items": items, "score": score, "read": read.strip()})

    # dollar
    items, score, read = [], None, ""
    dx = S.get("DTWEXBGS")
    if dx:
        a, b = change_over(dx, t, 28)
        ch = pct(a, b)
        items.append(_item("Dollar face à un large panier de devises", a, "indice", 1, ch, "%", "en 4 semaines", date=_date(dx)))
        if ch is not None:
            if ch > 1.0:
                score, read = -1.0, f"Le dollar se renforce ({fr(ch, 1, True)} % en 4 semaines) : conditions financières plus serrées dans le monde, défavorable aux cryptos."
            elif ch < -1.0:
                score, read = 1.0, f"Le dollar s'affaiblit ({fr(ch, 1, True)} % en 4 semaines) : plus de liquidité mondiale, favorable aux cryptos."
            else:
                score, read = 0.0, "Dollar stable sur 4 semaines."
    themes.append({"key": "dollar", "title": "Dollar", "items": items, "score": score, "read": read})

    # liquidite
    items, score, read = [], None, ""
    wal, tga, rrp, m2 = S.get("WALCL"), S.get("WTREGEN"), S.get("RRPONTSYD"), S.get("M2SL")
    net = net_liquidity(wal, tga, rrp)
    if wal:
        a, b = change_over(wal, t, 28)
        items.append(_item("Bilan de la Fed", a / 1e3 if a else None, "Md$", 0, (a - b) / 1e3 if a is not None and b is not None else None, "Md$", "en 4 semaines", date=_date(wal)))
    if tga:
        a, b = change_over(tga, t, 28)
        items.append(_item("Compte du Trésor à la Fed (argent retiré du système quand il monte)", a / 1e3 if a else None, "Md$", 0,
                           (a - b) / 1e3 if a is not None and b is not None else None, "Md$", "en 4 semaines", date=_date(tga)))
    if rrp:
        a, b = change_over(rrp, t, 28)
        items.append(_item("Prises en pension inversées (argent parqué à la Fed)", a, "Md$", 0, (a - b) if a is not None and b is not None else None, "Md$", "en 4 semaines",
                           date=_date(rrp)))
    if net:
        a, b1, b4 = at(net, t), at(net, t - 7 * DAY), at(net, t - 28 * DAY)
        c4 = a - b4 if a is not None and b4 is not None else None
        items.append(_item("Liquidité nette (bilan de la Fed − compte du Trésor − prises en pension)", a, "Md$", 0, c4, "Md$", "en 4 semaines",
                           note=f"sur la semaine : {fr(a - b1, 0, True)} Md$" if a is not None and b1 is not None else "", date=net[-1][0]))
        if c4 is not None:
            if c4 > 75:
                score, read = 1.0, f"La liquidité nette augmente ({fr(c4, 0, True)} milliards de dollars en 4 semaines) : plus de dollars disponibles dans le système financier, ce qui porte habituellement les actifs à risque et le bitcoin."
            elif c4 < -75:
                score, read = -1.0, f"La liquidité nette diminue ({fr(c4, 0, True)} milliards de dollars en 4 semaines) : moins de dollars disponibles, vent contraire pour les actifs à risque."
            else:
                score, read = 0.0, "Liquidité nette à peu près stable sur 4 semaines."
    if m2:
        y = last_ym(m2)
        items.append(_item("Masse monétaire M2 sur un an", yoy(m2, y), "%", 1, note=f"mois de {month_name(y)}", date=_date(m2)))
    themes.append({"key": "liquidite", "title": "Liquidité", "items": items, "score": score, "read": read})

    # risque et credit
    items, score, read = [], None, ""
    hy, vix, nf = S.get("BAMLH0A0HYM2"), S.get("VIXCLS"), S.get("NFCI")
    hch, vv = None, None
    if hy:
        a, b = change_over(hy, t, 28)
        hch = (a - b) * 100 if a is not None and b is not None else None
        items.append(_item("Écart de taux des obligations d'entreprises à haut rendement", a, "%", 2, hch, "pb", "en 4 semaines",
                           note="monte quand les investisseurs craignent les défauts", date=_date(hy)))
    if vix:
        a, b = change_over(vix, t, 7)
        vv = a
        items.append(_item("Volatilité attendue sur les actions (VIX)", a, "points", 1, (a - b) if a is not None and b is not None else None, "point", "sur la semaine", date=_date(vix)))
    if nf:
        items.append(_item("Conditions financières (Fed de Chicago)", nf[-1][1], "points", 2, nf[-1][1] - nf[-5][1] if len(nf) >= 5 else None, "point", "en 4 semaines",
                           note="au-dessus de 0 : plus tendues que la moyenne", date=_date(nf)))
    if hch is not None or vv is not None:
        if (hch is not None and hch > 40) or (vv is not None and vv > 25):
            score, read = -1.0, "Stress sur les marchés (écarts de crédit en hausse ou volatilité élevée) : les investisseurs réduisent le risque, les cryptos en pâtissent d'habitude."
        elif (hch is None or hch < -20) and (vv is None or vv < 18):
            score, read = 0.5, "Appétit pour le risque : écarts de crédit en baisse et volatilité basse."
        else:
            score, read = 0.0, "Pas de stress particulier sur le crédit ni sur la volatilité."
    themes.append({"key": "risque", "title": "Risque et crédit", "items": items, "score": score, "read": read})

    # energie
    items, score, read = [], None, ""
    wti = S.get("DCOILWTICO")
    if wti:
        a, b = change_over(wti, t, 28)
        ch = pct(a, b)
        items.append(_item("Pétrole WTI (dollars le baril)", a, "$", 1, ch, "%", "en 4 semaines", date=_date(wti)))
        if ch is not None:
            if ch > 15:
                score, read = -0.5, f"Flambée du pétrole ({fr(ch, 0, True)} % en 4 semaines), souvent liée à la géopolitique : risque d'inflation importée, la Fed peut rester prudente."
            elif ch < -15:
                score, read = 0.25, f"Chute du pétrole ({fr(ch, 0, True)} % en 4 semaines) : moins de pression sur l'inflation, mais parfois signe de demande mondiale faible."
            else:
                score, read = 0.0, "Pétrole sans mouvement extrême."
    themes.append({"key": "energie", "title": "Énergie", "items": items, "score": score, "read": read})
    return themes


def net_liquidity(wal, tga, rrp):
    """Liquidite nette hebdomadaire (milliards de dollars) : bilan de la Fed − compte du Tresor − prises en pension inversees, au mercredi."""
    if not wal or not tga:
        return []
    out = []
    for t, v in wal:
        g = at(tga, t + DAY)
        r = at(rrp, t + DAY) if rrp else 0.0
        if g is None:
            continue
        out.append((t, v / 1e3 - g / 1e3 - (r or 0.0)))
    return out


def verdict(themes, events):
    """Vent macro pour les actifs a risque et la crypto : somme des lectures par theme (regles classiques, non validees par le backtest)."""
    parts = [(th["title"], th["score"], th["read"]) for th in themes if th.get("score") is not None]
    total = sum(s for _, s, _ in parts)
    label = ("favorable" if total >= 2 else "plutôt favorable" if total >= 0.75 else "neutre" if total > -0.75 else "plutôt défavorable" if total > -2 else "défavorable") if parts else None
    pos = [f"{n.lower()}" for n, s, _ in parts if s > 0]
    neg = [f"{n.lower()}" for n, s, _ in parts if s < 0]
    lines = []
    if label:
        lines.append(f"Vent macro {label} pour les actifs à risque et les cryptos" + (f" : soutiens — {', '.join(pos)}" if pos else "") +
                     (f" ; freins — {', '.join(neg)}" if neg else "") + ".")
    past = [e for e in events if e["past"] and e["dir"] is not None and e["cat"] in ("inflation", "labor", "growth")]
    if past:
        hot = sum(1 for e in past if (e["dir"] > 0 and e["key"] not in ("UNRATE", "CLAIMS")) or (e["dir"] < 0 and e["key"] in ("UNRATE", "CLAIMS")))
        cool = sum(1 for e in past if e["dir"] != 0) - hot
        lines.append(f"Annonces de la semaine : {hot} plus solide{'s' if hot > 1 else ''} ou plus chaude{'s' if hot > 1 else ''} que prévu, {cool} plus faible{'s' if cool > 1 else ''}, "
                     f"{sum(1 for e in past if e['dir'] == 0)} conforme{'s' if sum(1 for e in past if e['dir'] == 0) > 1 else ''} au consensus.")
    imps = [e["reaction"]["impulse"] for e in events if e["past"] and e.get("reaction") and e["reaction"].get("impulse") is not None and e["w"] >= 0.5]
    if imps:
        m = sum(imps) / len(imps)
        lines.append("Lecture du marché au moment des annonces (taux et dollar) : " + macro_engine.impulse_label(m) +
                     (" — les surprises ont plutôt poussé les taux et le dollar à la hausse, défavorable aux cryptos." if m > 0.6 else
                      " — les surprises ont plutôt fait baisser les taux et le dollar, favorable aux cryptos." if m < -0.6 else "."))
    return {"score": total if parts else None, "label": label, "lines": lines,
            "parts": [{"title": n, "score": s, "read": r} for n, s, r in parts]}


# ---------- 3. marches de la semaine ----------
def weekly_change(series, ws, we, now, log_yield=False):
    """Variation entre la derniere valeur avant le lundi et la derniere valeur de la semaine (ou maintenant)."""
    if not series:
        return None
    a = at(series, ws - 1)
    b = at(series, min(we, now))
    if a is None or b is None:
        return None
    if log_yield:
        f = lambda v: v / 10.0 if v > 20 else v
        return {"last": f(b), "chg": (f(b) - f(a)) * 100.0, "unit": "pb"}
    return {"last": b, "chg": pct(b, a), "unit": "%"}


CROSS_NAMES = [("SPX", "S&P 500 (contrats à terme)"), ("NDX", "Nasdaq 100 (contrats à terme)"), ("GOLD", "Or"), ("DXY", "Dollar (indice DXY)"),
               ("US10Y", "Taux à 10 ans"), ("VIX", "Volatilité (VIX)")]


def markets(crypto_daily: dict, crossD: dict, ws, we, now):
    rows = []
    for k, name in (("BTC", "Bitcoin"), ("ETH", "Ether"), ("SOL", "Solana")):
        w = weekly_change(crypto_daily.get(k), ws, we, now)
        if w:
            rows.append({"key": k, "name": name, **w})
    for k, name in CROSS_NAMES:
        w = weekly_change(crossD.get(k), ws, we, now, log_yield=(k == "US10Y"))
        if w:
            rows.append({"key": k, "name": name, **w})
    return rows


def crypto_block(cg_hist, fng, rotation_snap, rotation_text, ws, we, now):
    out = []
    end = min(we, now)
    if cg_hist:
        dom = [(t, d) for t, d, _ in cg_hist]
        tot = [(t, v) for t, _, v in cg_hist]
        a, b = at(dom, ws), at(dom, end)
        if a is not None and b is not None and ws - 3 * DAY <= upto(dom, ws)[-1][0]:
            out.append({"name": "Dominance du bitcoin (part dans la capitalisation crypto)", "value": b, "unit": "%", "d": 1, "change": b - a, "changeUnit": "point"})
        a, b = at(tot, ws), at(tot, end)
        if a and b and ws - 3 * DAY <= upto(tot, ws)[-1][0]:
            out.append({"name": "Capitalisation totale des cryptos", "value": b / 1e12, "unit": "milliers de Md$", "d": 2, "change": pct(b, a), "changeUnit": "%"})
    if fng:
        f = [(t, v) for t, v, *_ in fng]
        a, b = at(f, ws), at(f, end)
        if b is not None:
            out.append({"name": "Sentiment des investisseurs crypto (Fear & Greed, 0 = peur extrême, 100 = euphorie)", "value": b, "unit": "", "d": 0,
                        "change": (b - a) if a is not None else None, "changeUnit": "point"})
    if rotation_snap:
        st = next((r for r in rotation_snap.get("rows", []) if r["key"] == "stable"), None)
        if rotation_snap.get("stableUsd"):
            out.append({"name": "Stablecoins en circulation (USDT, USDC, DAI) — « poudre sèche »", "value": rotation_snap["stableUsd"] / 1e9, "unit": "Md$", "d": 0,
                        "change": st["d7"] * 100 if st and st.get("d7") is not None else None, "changeUnit": "point de part en 7 jours"})
    return {"rows": out, "rotation": rotation_text or ""}


# ---------- 4. mesure : ces moteurs ont-ils compte pour le bitcoin ? ----------
DRIVERS = [
    ("liquidite", "Liquidité nette en hausse sur 4 semaines", 1),
    ("dollar", "Dollar en baisse sur 4 semaines", -1),
    ("reel", "Taux réel à 10 ans en baisse sur 4 semaines", -1),
    ("credit", "Écarts de crédit en baisse sur 4 semaines", -1),
    ("taux10", "Taux à 10 ans en baisse sur 4 semaines", -1),
]


def _welch(a, b):
    na, nb = len(a), len(b)
    if na < 8 or nb < 8:
        return None
    ma, mb = sum(a) / na, sum(b) / nb
    va = sum((x - ma) ** 2 for x in a) / (na - 1)
    vb = sum((x - mb) ** 2 for x in b) / (nb - 1)
    se = math.sqrt(va / na + vb / nb)
    return (ma - mb) / se if se > 0 else None


def drivers_study(fred: dict, btc_daily: list, now: int):
    """Pour chaque lundi depuis le debut des donnees : sens du moteur sur les 4 semaines precedentes (chiffres deja publies a ce moment),
    puis rendement du bitcoin la semaine suivante (echantillons hebdomadaires sans chevauchement) et les 4 semaines suivantes (un lundi sur quatre)."""
    from data.fred import SERIES
    if not btc_daily or len(btc_daily) < 200:
        return {"ready": False, "rows": [], "note": "historique du bitcoin insuffisant"}
    lag = lambda k: SERIES[k][2]
    known = lambda k: fred.get(k) or []
    net = net_liquidity(known("WALCL"), known("WTREGEN"), known("RRPONTSYD"))
    src = {"liquidite": (net, 2, "diff"), "dollar": (known("DTWEXBGS"), lag("DTWEXBGS"), "pct"), "reel": (known("DFII10"), 1, "diff"),
           "credit": (known("BAMLH0A0HYM2"), 1, "diff"), "taux10": (known("DGS10"), 1, "diff")}
    px = btc_daily
    first = max(px[0][0] + 35 * DAY, min((s[0][0] for s, _, _ in src.values() if s), default=now) + 35 * DAY)
    m = week_start(first) + WEEK
    rows = []
    for key, label, fav in DRIVERS:
        s, lg, how = src[key]
        if not s:
            continue
        r1 = {True: [], False: []}
        r4 = {True: [], False: []}
        k = 0
        mm = m
        while mm + WEEK <= now:
            a, b = at(s, mm - lg * DAY), at(s, mm - lg * DAY - 28 * DAY)
            p0, p1 = at(px, mm - 1), at(px, mm + WEEK - 1)
            if a is not None and b is not None and p0 and p1:
                ch = (a - b) if how == "diff" else pct(a, b)
                if ch is not None and ch != 0:
                    good = (ch > 0) == (fav > 0)
                    r1[good].append((p1 / p0 - 1) * 100)
                    if k % 4 == 0 and mm + 4 * WEEK <= now:
                        p4 = at(px, mm + 4 * WEEK - 1)
                        if p4:
                            r4[good].append((p4 / p0 - 1) * 100)
            mm += WEEK
            k += 1
        if len(r1[True]) < 8 or len(r1[False]) < 8:
            continue
        mean = lambda v: sum(v) / len(v) if v else None
        hit = lambda v: sum(1 for x in v if x > 0) / len(v) * 100 if v else None
        t1, t4 = _welch(r1[True], r1[False]), _welch(r4[True], r4[False])
        sig = t1 is not None and abs(t1) >= 2.0
        rows.append({"key": key, "label": label, "nFav": len(r1[True]), "nUnf": len(r1[False]),
                     "fav1": mean(r1[True]), "unf1": mean(r1[False]), "hitFav": hit(r1[True]), "hitUnf": hit(r1[False]), "t1": t1,
                     "fav4": mean(r4[True]), "unf4": mean(r4[False]), "n4": len(r4[True]) + len(r4[False]), "t4": t4,
                     "verdict": ("écart net (au seuil statistique habituel)" + ("" if (mean(r1[True]) or 0) > (mean(r1[False]) or 0) else ", mais dans le sens inverse de la théorie"))
                     if sig else "≈ hasard : écart pas distinguable du bruit"})
    span = (datetime.fromtimestamp(m / 1000, timezone.utc).strftime("%m/%Y"), datetime.fromtimestamp(now / 1000, timezone.utc).strftime("%m/%Y"))
    return {"ready": bool(rows), "rows": rows, "from": span[0], "to": span[1],
            "note": "Rendement moyen du bitcoin la semaine suivante selon le sens du moteur sur les 4 semaines précédentes (chiffres déjà publiés à ce moment-là). "
                    "Écart « net » si la statistique de Welch dépasse 2 en valeur absolue ; plusieurs moteurs testés à la fois : un écart isolé peut être dû à la chance."}


# ---------- 5. semaine prochaine ----------
def next_week(calendar: dict, ws_next: int):
    evs = week_events(calendar, {}, ws_next, ws_next + WEEK, ws_next - 1)
    return [e for e in evs if (e["country"] == "USD" and e["w"] >= 0.5) or e["impact"] == 3][:14]


# ---------- assemblage ----------
def build(ws: int, now: int, fred: dict, calendar: dict, crossD: dict, crypto_daily: dict, cg_hist=None, fng=None,
          rotation_snap=None, rotation_text="", study=None, reconstructed: bool | None = None) -> dict:
    """reconstructed : bilan etabli apres coup, sans version archivee pendant la semaine (par defaut : semaine terminee depuis plus de 2 jours)."""
    we = ws + WEEK
    current = ws <= now < we
    t = min(now, we)
    if reconstructed is None:
        reconstructed = not current and now - we > 2 * DAY
    evs = week_events(calendar, fred, ws, we, now)
    themes = dashboard(fred, t, lagged=not current)                  # semaine passee : seulement les chiffres deja publies a la fin de la semaine
    out = {"week": week_key(ws), "start": ws, "end": we, "current": current, "final": now >= we + 2 * DAY, "built": now, "reconstructed": reconstructed,
           "events": evs, "themes": themes, "verdict": verdict(themes, evs), "markets": markets(crypto_daily, crossD, ws, we, now),
           "crypto": crypto_block(cg_hist or [], fng or [], rotation_snap, rotation_text, ws, we, now),
           "next": next_week(calendar, we) if now < we + 3 * DAY else [], "study": study,
           "hasFred": any(fred.get(k) for k in ("CPIAUCSL", "UNRATE", "DGS10"))}
    out["summary"] = summary_text(out)
    return out


def _evline(e):
    when = datetime.fromtimestamp(e["t"] / 1000, timezone.utc).strftime("%d/%m %H:%M UTC")
    pub = f"publié {e['actual']['text']}" if e.get("actual") else "chiffre publié non fourni par la source gratuite"
    s = f"• {when} — {e['label']} : {pub}"
    if e["forecast"]:
        s += f" (consensus {e['forecast']}, précédent {e['previous'] or '—'})"
    if e.get("read"):
        s += f". {e['read']}"
    if e.get("reactionText"):
        s += f" {e['reactionText']}"
    return s


def summary_text(r: dict, max_events: int = 12) -> str:
    """Version texte (Telegram, contexte du commentaire de Claude)."""
    d0 = datetime.fromtimestamp(r["start"] / 1000, timezone.utc).strftime("%d/%m")
    d1 = datetime.fromtimestamp((r["end"] - DAY) / 1000, timezone.utc).strftime("%d/%m/%Y")
    L = [f"Bilan macro de la semaine du {d0} au {d1}" + (" (en cours)" if r["current"] else "")]
    v = r["verdict"]
    if v.get("lines"):
        L.append("")
        L += v["lines"]
    past = [e for e in r["events"] if e["past"] and (e["w"] >= 0.5 or e["impact"] == 3)]
    if past:
        L.append("")
        L.append("Annonces :")
        L += [_evline(e) for e in past[:max_events]]
    L.append("")
    L.append("Par thème :")
    for th in r["themes"]:
        if th["read"]:
            L.append(f"• {th['title']} : {th['read']}")
        for it in th["items"][:3]:
            if it["value"] is not None:
                ch = f" ({fr(it['change'], it['cd'], True)} {it['changeUnit']} {it['changeLabel']})" if it.get("change") is not None and it.get("changeLabel") else ""
                L.append(f"   – {it['name']} : {fr(it['value'], it['d'])} {it['unit']}{ch}")
    if r["markets"]:
        L.append("")
        L.append("Marchés sur la semaine : " + " ; ".join(f"{m['name']} {fr(m['chg'], 0 if m['unit'] == 'pb' else 1, True)} {'points de base' if m['unit'] == 'pb' else '%'}"
                                                     for m in r["markets"] if m.get("chg") is not None))
    if r["crypto"]["rotation"]:
        L.append("Où va l'argent en crypto : " + r["crypto"]["rotation"])
    if r.get("next"):
        L.append("")
        L.append("Semaine prochaine :")
        for e in r["next"][:8]:
            when = datetime.fromtimestamp(e["t"] / 1000, timezone.utc).strftime("%a %d/%m %H:%M UTC")
            L.append(f"• {when} — {e['label']}" + (f" (consensus {e['forecast']}, précédent {e['previous'] or '—'})" if e["forecast"] else ""))
    L.append("")
    L.append("Lecture par règles classiques, non validée par le backtest du terminal (voir la mesure dans la page).")
    return "\n".join(L)
