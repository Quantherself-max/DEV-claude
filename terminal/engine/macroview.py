"""Analyse macro de la semaine (V25) : la vision d'ensemble, en plus du bilan chiffre (engine/macroweek.py). Module PUR.

  1. REGIME : la croissance et l'inflation americaines accelerent-elles ou ralentissent-elles ? Quatre quadrants, le trajet sur 12 mois,
     et la mesure de ce qu'a fait le bitcoin le mois suivant dans chaque quadrant (chiffres deja publies a chaque date) ;
  2. SURPRISES : les chiffres sortent-ils au-dessus ou en dessous du consensus depuis 8 semaines (activite, inflation), en ecarts habituels ;
  3. FED : ce que le marche anticipe (taux d'Etat a 3 mois, 6 mois, 1 an et 2 ans), ce que les membres de la Fed projettent, la prochaine
     reunion et le changement sur la semaine ;
  4. SEMAINE A VENIR : chaque annonce importante avec le consensus, l'ESTIMATION DU TERMINAL (tendance des derniers mois ; prix de l'essence
     pour l'inflation totale ; GDPNow pour la croissance), l'erreur habituelle de cette estimation mesuree sur 5 ans, et ce qu'un ecart impliquerait ;
  5. VISION GLOBALE : un texte qui relie le tout, et ce que cela veut dire pour le bitcoin et solana.

Rien n'est invente : chaque phrase vient d'un chiffre mesure. Les regles de lecture sont classiques et non validees par le backtest du terminal ;
l'estimation du terminal est volontairement simple (les economistes connaissent aussi ces tendances) : elle sert a reperer un consensus
qui s'ecarte nettement des tendances, pas a battre le consensus."""
import math
from bisect import bisect_right
from datetime import datetime, timezone

from . import macro as macro_engine
from . import macroweek as mw

DAY, WEEK = mw.DAY, mw.WEEK
fr = mw.fr


def clip(x, lo=-2.0, hi=2.0):
    return max(lo, min(hi, x))


class Data:
    """Acces rapide aux series FRED « connues a l'instant t » (recherche par dichotomie, sans recopier les listes)."""

    def __init__(self, fred: dict):
        from data.fred import SERIES
        self.fred, self.lags = fred or {}, {k: v[2] for k, v in SERIES.items()}
        self.ts = {k: [x[0] for x in v] for k, v in self.fred.items()}

    def n(self, sid, t, lagged=False) -> int:
        """Nombre d'observations connues a t (publiees : date d'observation + delai habituel <= t si lagged)."""
        ts = self.ts.get(sid)
        if not ts:
            return 0
        return bisect_right(ts, t - (self.lags.get(sid, 0) * DAY if lagged else 0))

    def known(self, sid, t, lagged=False, last=None):
        k = self.n(sid, t, lagged)
        s = self.fred.get(sid) or []
        return s[max(0, k - last):k] if last else s[:k]

    def at(self, sid, t, lagged=False):
        k = self.n(sid, t, lagged)
        return self.fred[sid][k - 1][1] if k else None

    def month_map(self, sid, t, lagged=False, months=40) -> dict:
        return mw.by_month(self.known(sid, t, lagged, last=months))


def _ann(vals, months):
    """Rythme annualise (%) sur `months` mois d'une serie mensuelle d'indices [(t, v)]."""
    if len(vals) < months + 1 or not vals[-1 - months][1]:
        return None
    return ((vals[-1][1] / vals[-1 - months][1]) ** (12 / months) - 1) * 100


# ---------- 1. regime ----------
QUADS = {
    "goldilocks": ("Croissance qui tient, inflation qui ralentit",
                   "C'est le meilleur cas pour les actifs à risque : la Fed peut baisser ses taux sans que l'économie flanche.", 1.0),
    "reflation": ("Croissance et inflation en hausse (surchauffe)",
                  "Bon pour l'activité, mais la Fed a moins de marge pour baisser ses taux : les taux longs et le dollar peuvent monter.", 0.0),
    "stagflation": ("Croissance en baisse, inflation en hausse (stagflation)",
                    "C'est le cas le plus difficile : la Fed est coincée entre l'emploi et l'inflation, et les actifs à risque souffrent souvent.", -1.0),
    "slowdown": ("Croissance et inflation en baisse (ralentissement)",
                 "La Fed a de la marge pour baisser ses taux : favorable à la liquidité, mais la peur d'une récession peut dominer.", 0.0),
}


def quadrant(g, i):
    if g is None or i is None:
        return None
    return ("goldilocks" if i < 0 else "reflation") if g >= 0 else ("slowdown" if i < 0 else "stagflation")


def regime_at(D: Data, t: int, lagged=True) -> dict:
    """Elan de la croissance (g) et de l'inflation (i), chacun entre −2 et +2 : moyenne de composantes normalisees (rythme recent
    face au rythme sur un an). Seuls les chiffres publies a l'instant t comptent si lagged."""
    G, I = [], []
    pay = D.known("PAYEMS", t, lagged, last=13)
    if len(pay) >= 13:
        d = [pay[j][1] - pay[j - 1][1] for j in range(1, 13)]
        a3, a12 = sum(d[-3:]) / 3, sum(d) / 12
        G.append(("emplois", "Créations d'emplois", clip((a3 - a12) / 50), f"{fr(a3, 0)} milliers par mois sur 3 mois, contre {fr(a12, 0)} sur 12 mois"))
    un = D.known("UNRATE", t, lagged, last=4)
    if len(un) >= 4:
        ch = un[-1][1] - un[-4][1]
        G.append(("chomage", "Chômage", clip(-ch / 0.2), f"{fr(un[-1][1])} %, {fr(ch, 1, True)} point en 3 mois"))
    cl = D.known("ICSA", t, lagged, last=17)
    if len(cl) >= 17:
        a4, b4 = sum(x[1] for x in cl[-4:]) / 4, sum(x[1] for x in cl[:4]) / 4
        r = (a4 / b4 - 1) * 100 if b4 else 0.0
        G.append(("inscriptions", "Inscriptions au chômage", clip(-r / 8), f"{fr(a4 / 1000, 0)} milliers par semaine, {fr(r, 0, True)} % en 3 mois"))
    for sid, key, name, div in (("RSAFS", "ventes", "Ventes au détail", 4.0), ("INDPRO", "industrie", "Production industrielle", 4.0)):
        s = D.known(sid, t, lagged, last=13)
        a3, a12 = _ann(s, 3), _ann(s, 12)
        if a3 is not None and a12 is not None:
            G.append((key, name, clip((a3 - a12) / div), f"rythme annualisé {fr(a3)} % sur 3 mois, contre {fr(a12)} % sur un an"))
    gn = D.known("GDPNOW", t, lagged, last=1)
    if gn:
        G.append(("gdpnow", "Croissance du trimestre estimée (GDPNow)", clip((gn[-1][1] - 1.8) / 1.5), f"{fr(gn[-1][1])} % en rythme annualisé"))
    for sid, key, name, div in (("CPILFESL", "sousjacente", "Inflation sous-jacente", 0.8), ("PCEPILFE", "pce", "Inflation préférée de la Fed (sous-jacente)", 0.8),
                                ("CPIAUCSL", "totale", "Inflation totale", 1.5), ("PPIFIS", "production", "Prix à la production", 3.0)):
        s = D.known(sid, t, lagged, last=13)
        a3, a12 = _ann(s, 3), _ann(s, 12)
        if a3 is not None and a12 is not None:
            I.append((key, name, clip((a3 - a12) / div), f"rythme annualisé {fr(a3)} % sur 3 mois, contre {fr(a12)} % sur un an"))
    a, b = D.at("T5YIE", t, lagged), D.at("T5YIE", t - 91 * DAY, lagged)
    if a is not None and b is not None:
        I.append(("anticipee", "Inflation anticipée par le marché (5 ans)", clip((a - b) / 0.25), f"{fr(a, 2)} %, {fr((a - b) * 100, 0, True)} points de base en 3 mois"))
    g = sum(x[2] for x in G) / len(G) if len(G) >= 2 else None
    i = sum(x[2] for x in I) / len(I) if len(I) >= 2 else None
    q = quadrant(g, i)
    return {"t": t, "g": g, "i": i, "quad": q, "label": QUADS[q][0] if q else None,
            "growth": [{"key": k, "name": n, "score": round(s, 2), "text": x} for k, n, s, x in G],
            "inflation": [{"key": k, "name": n, "score": round(s, 2), "text": x} for k, n, s, x in I]}


def momentum_word(x, up="accélère", down="ralentit"):
    return None if x is None else up if x > 0.35 else down if x < -0.35 else "stable"


def month_starts(t0: int, t1: int):
    d = datetime.fromtimestamp(t0 / 1000, timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while d.timestamp() * 1000 <= t1:
        yield int(d.timestamp() * 1000)
        d = d.replace(year=d.year + (d.month == 12), month=d.month % 12 + 1)


def regime_trail(D: Data, t: int, months: int = 12, lagged_now: bool = False) -> list:
    """Trajet du regime : debut de chacun des `months` derniers mois (chiffres publies a ce moment), puis t."""
    pts = []
    for m in list(month_starts(t - months * 31 * DAY, t))[-months:]:
        r = regime_at(D, m, lagged=True)
        if r["g"] is not None and r["i"] is not None:
            pts.append({"t": m, "g": round(r["g"], 3), "i": round(r["i"], 3), "quad": r["quad"]})
    r = regime_at(D, t, lagged=lagged_now)
    if r["g"] is not None and r["i"] is not None:
        pts.append({"t": t, "g": round(r["g"], 3), "i": round(r["i"], 3), "quad": r["quad"]})
    return pts


def _welch(a, b):
    na, nb = len(a), len(b)
    if na < 6 or nb < 6:
        return None
    ma, mb = sum(a) / na, sum(b) / nb
    va, vb = sum((x - ma) ** 2 for x in a) / (na - 1), sum((x - mb) ** 2 for x in b) / (nb - 1)
    se = math.sqrt(va / na + vb / nb)
    return (ma - mb) / se if se > 0 else None


def regime_study(D: Data, px: list, now: int) -> dict:
    """Ce qu'a fait le bitcoin le mois suivant selon le quadrant du debut du mois (chiffres deja publies), depuis le debut des donnees.
    px : clotures quotidiennes [(t, prix)]. Mois sans chevauchement ; comparaison de chaque quadrant aux autres mois (statistique de Welch)."""
    if not px or len(px) < 400:
        return {"ready": False, "rows": [], "note": "historique du bitcoin insuffisant"}
    ts = [x[0] for x in px]

    def price(t):
        k = bisect_right(ts, t) - 1
        return px[k][1] if k >= 0 and t - px[k][0] <= 4 * DAY else None
    by = {q: [] for q in QUADS}
    allr = []
    for m in month_starts(px[0][0] + 31 * DAY, now - 31 * DAY):
        nxt = next(month_starts(m + 32 * DAY, m + 32 * DAY))
        if nxt > now:
            break
        r = regime_at(D, m, lagged=True)
        p0, p1 = price(m), price(nxt)
        if r["quad"] and p0 and p1:
            ret = (p1 / p0 - 1) * 100
            by[r["quad"]].append(ret)
            allr.append((r["quad"], ret))
    rows = []
    for q, rets in by.items():
        others = [x for k, x in allr if k != q]
        tt = _welch(rets, others)
        rows.append({"quad": q, "label": QUADS[q][0], "n": len(rets), "mean": sum(rets) / len(rets) if rets else None,
                     "median": sorted(rets)[len(rets) // 2] if rets else None, "hit": sum(1 for x in rets if x > 0) / len(rets) * 100 if rets else None,
                     "t": tt, "verdict": ("pas assez de mois" if len(rets) < 6 else "écart net" if tt is not None and abs(tt) >= 2 else "≈ hasard")})
    span = (datetime.fromtimestamp(px[0][0] / 1000, timezone.utc).strftime("%m/%Y"), datetime.fromtimestamp(now / 1000, timezone.utc).strftime("%m/%Y"))
    return {"ready": len(allr) >= 24, "rows": rows, "n": len(allr), "from": span[0], "to": span[1],
            "note": "Rendement du bitcoin le mois suivant, selon le quadrant du début du mois (chiffres déjà publiés à ce moment-là). « Écart net » : "
                    "différent des autres mois au seuil statistique habituel (Welch, 2) ; « ≈ hasard » : pas distinguable des autres mois. Peu de mois "
                    "par quadrant : un écart isolé peut être dû à la chance."}


# ---------- 2. surprises face au consensus ----------
# ecart habituel entre chiffre publie et consensus (ordre de grandeur historique, unites du calendrier) : sert a comparer des chiffres differents
SIZE = {"CPI": 0.1, "CORE_CPI": 0.1, "PCE": 0.1, "CORE_PCE": 0.1, "PPI": 0.25, "CORE_PPI": 0.2, "AHE": 0.1, "NFP": 70.0, "UNRATE": 0.1,
        "CLAIMS": 15.0, "JOLTS": 0.35, "RETAIL": 0.5, "GDP": 0.5}


def surprises(calendar: dict, fred: dict, t: int, days: int = 56) -> dict:
    """Indices de surprise sur `days` jours : moyenne ponderee (importance, demi-vie de 3 semaines) des ecarts au consensus en ecarts habituels.
    Activite : positif = plus solide que prevu (chomage et inscriptions au chomage inverses). Inflation : positif = plus chaude que prevu."""
    rows, seen = [], set()
    evs = sorted((e for e in (calendar or {}).values() if t - days * DAY <= e["t"] <= t and e.get("country") == "USD" and e.get("fnum") is not None),
                 key=lambda e: (e["t"], "m/m" not in e["title"].lower()))
    for e in evs:
        cls = macro_engine.classify(e["title"], "USD")
        key = cls["key"]
        if key not in SIZE or (key, e["t"]) in seen:
            continue
        pub = e.get("actual") or mw.published(e, fred or {})
        if not pub:
            continue
        seen.add((key, e["t"]))
        raw = (pub["value"] - e["fnum"]) / SIZE[key]
        z = clip(raw * (-1 if key in ("UNRATE", "CLAIMS") else 1), -3.0, 3.0)
        rows.append({"t": e["t"], "label": mw.event_label(e, cls), "key": key, "grp": "inflation" if cls["cat"] == "inflation" else "activity",
                     "forecast": e.get("forecast"), "actual": pub["text"], "z": round(z, 2), "w": cls["w"] * 0.5 ** ((t - e["t"]) / DAY / 21)})

    def index(grp):
        rs = [r for r in rows if r["grp"] == grp]
        if len(rs) < 2:
            return {"value": None, "n": len(rs), "above": 0, "below": 0, "inline": 0, "label": "pas assez de chiffres publiés"}
        v = sum(r["w"] * r["z"] for r in rs) / sum(r["w"] for r in rs)
        hot = ("plus chaude", "plus froide") if grp == "inflation" else ("plus solide", "plus faible")
        lab = (f"nettement {hot[0]} que prévu" if v >= 0.5 else f"plutôt {hot[0]} que prévu" if v >= 0.15 else
               f"nettement {hot[1]} que prévu" if v <= -0.5 else f"plutôt {hot[1]} que prévu" if v <= -0.15 else "conforme au consensus")
        return {"value": round(v, 2), "n": len(rs), "above": sum(1 for r in rs if r["z"] > 0.25), "below": sum(1 for r in rs if r["z"] < -0.25),
                "inline": sum(1 for r in rs if abs(r["z"]) <= 0.25), "label": lab}
    for r in rows:
        r["w"] = round(r["w"], 3)
    return {"days": days, "activity": index("activity"), "inflation": index("inflation"), "rows": rows[::-1]}


# ---------- 3. ce que le marche anticipe pour la Fed ----------
def _pricing_at(D: Data, t: int, lagged: bool):
    lo, hi, dff = D.at("DFEDTARL", t, lagged), D.at("DFEDTARU", t, lagged), D.at("DFF", t, lagged)
    if dff is None and lo is not None and hi is not None:
        dff = (lo + hi) / 2
    y3, y6, y1, y2 = (D.at(s, t, lagged) for s in ("DGS3MO", "DGS6MO", "DGS1", "DGS2"))
    path = []
    if dff is not None:
        path.append({"m": 0.0, "r": dff, "label": "aujourd'hui (taux effectif)"})
    if y3 is not None:
        path.append({"m": 1.5, "r": y3, "label": "moyenne attendue sur 3 mois"})
    if y3 is not None and y6 is not None:
        path.append({"m": 4.5, "r": 2 * y6 - y3, "label": "dans 3 à 6 mois"})
    if y6 is not None and y1 is not None:
        path.append({"m": 9.0, "r": 2 * y1 - y6, "label": "dans 6 à 12 mois"})
    if y1 is not None and y2 is not None:
        path.append({"m": 18.0, "r": 2 * y2 - y1, "label": "dans 1 à 2 ans"})
    f12 = next((p["r"] for p in path if p["m"] == 9.0), None)
    cuts = (dff - f12) / 0.25 if dff is not None and f12 is not None else None
    return {"lo": lo, "hi": hi, "dff": dff, "path": path, "in12": f12, "cuts": cuts}


def interp(pts, x):
    """Interpolation lineaire sur des points (x, y) tries ; None hors de la plage."""
    pts = sorted(p for p in pts if p[1] is not None)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y0
    return None


def sep_date(fred: dict):
    """Date de la derniere reunion avec projections connue (observation de la projection a long terme). None si la serie manque
    ou n'est datee que par l'annee (1er janvier) : les projections restent affichees, sans date."""
    s = fred.get("FEDTARMDLR") or []
    if not s:
        return None
    d = datetime.fromtimestamp(s[-1][0] / 1000, timezone.utc)
    return None if (d.month, d.day) == (1, 1) else s[-1][0]


def fed_view(D: Data, t: int, meetings: list, lagged: bool = False, change_days: int = 7, change_label: str = "Sur la semaine") -> dict:
    """change_days / change_label : periode de comparaison des anticipations (la semaine, ou depuis le debut du mois)."""
    from data import fed as fed_mod
    cur = _pricing_at(D, t, lagged)
    prev = _pricing_at(D, t - change_days * DAY, True)
    out = {**cur, "cutsBefore": prev["cuts"], "changeLabel": change_label,
           "cutsChange": (cur["cuts"] - prev["cuts"]) if cur["cuts"] is not None and prev["cuts"] is not None else None}
    y = datetime.fromtimestamp(t / 1000, timezone.utc).year
    sd = sep_date(D.fred)
    dots = []
    if sd is None or sd <= t + DAY:                     # projections publiees apres t : pas d'anachronisme (bilan reconstruit)
        for sid, key in (("FEDTARMD", "median"), ("FEDTARRH", "high"), ("FEDTARRL", "low")):
            for ts_, v in D.fred.get(sid) or []:
                yr = datetime.fromtimestamp(ts_ / 1000, timezone.utc).year
                if y <= yr <= y + 2:
                    end = int(datetime(yr, 12, 31, tzinfo=timezone.utc).timestamp() * 1000)
                    row = next((d for d in dots if d["year"] == yr), None)
                    if row is None:
                        row = {"year": yr, "m": round((end - t) / (30.44 * DAY), 1)}
                        dots.append(row)
                    row[key] = v
    dots.sort(key=lambda d: d["year"])
    out["dots"] = [d for d in dots if "median" in d]
    out["fedIn12"] = interp([(0.0, out["dff"])] + [(d["m"], d["median"]) for d in out["dots"]], 9.0) if out["dots"] and out["dff"] is not None else None
    lr = D.fred.get("FEDTARMDLR") or []
    out["longRun"] = lr[-1][1] if lr else None
    out["sepDate"] = sd
    nm = fed_mod.next_meeting(meetings or fed_mod.fallback_meetings(), t)
    out["next"] = {"decision": nm["decision"], "days": max(0, int((nm["decision"] - t) // DAY)), "sep": nm["sep"]} if nm else None
    out["text"] = fed_text(out)
    return out


def _n_cuts(x):
    a = round(abs(x), 1)
    n = fr(a, 1).replace(",0", "")
    return f"{n} {'baisse' if x > 0 else 'hausse'}{'s' if a >= 2 else ''} de 0,25 point"


def fx(s) -> str:
    """Chiffre du calendrier (« 0.3% ») ecrit a la francaise (« 0,3 % »)."""
    import re
    s = re.sub(r"(\d)\.(\d)", r"\1,\2", str(s or ""))
    return re.sub(r"(\d)%", r"\1 %", s)


def low1(s: str) -> str:
    """Premiere lettre en minuscule (les sigles et noms propres restent intacts)."""
    return s[:1].lower() + s[1:] if s and not s[:2].isupper() else s


def fed_text(f: dict) -> list:
    L = []
    if f.get("lo") is not None and f.get("hi") is not None:
        L.append(f"Taux directeur de la Fed : {fr(f['lo'], 2)} – {fr(f['hi'], 2)} %" + (f" (taux effectif {fr(f['dff'], 2)} %)." if f.get("dff") is not None else "."))
    c = f.get("cuts")
    if c is not None:
        if abs(c) < 0.4:
            L.append(f"Le marché n'anticipe pas de changement net du taux d'ici un an environ (taux attendu ≈ {fr(f['in12'], 2)} %).")
        else:
            L.append(f"Le marché anticipe environ {_n_cuts(c)} d'ici un an environ (taux attendu ≈ {fr(f['in12'], 2)} % dans 6 à 12 mois, "
                     f"contre {fr(f['dff'], 2)} % aujourd'hui).")
        ch = f.get("cutsChange")
        if ch is not None and abs(ch) >= 0.2:
            L.append(f"{f.get('changeLabel') or 'Sur la semaine'}, le marché a {'ajouté' if ch > 0 else 'retiré'} l'équivalent de {fr(abs(ch), 1)} baisse{'s' if abs(ch) >= 2 else ''} : "
                     + ("anticipations plus accommodantes, plutôt favorable aux actifs à risque." if ch > 0 else "anticipations plus restrictives, plutôt défavorable aux actifs à risque."))
    d = f.get("dots") or []
    if d:
        d0 = d[0]
        rng = f" (de {fr(d0['low'], 2)} à {fr(d0['high'], 2)} % selon les membres)" if d0.get("low") is not None and d0.get("high") is not None else ""
        L.append(f"Les membres de la Fed projettent un taux médian de {fr(d0['median'], 2)} % fin {d0['year']}{rng}"
                 + (f" et de {fr(d[1]['median'], 2)} % fin {d[1]['year']}" if len(d) > 1 else "") + ".")
        fed9 = f.get("fedIn12")
        if f.get("in12") is not None and fed9 is not None:
            gap = f["in12"] - fed9
            L.append(f"Dans 6 à 12 mois : le marché attend ≈ {fr(f['in12'], 2)} %, la Fed (médiane de ses projections) ≈ {fr(fed9, 2)} %"
                     + (" : les deux sont alignés." if abs(gap) < 0.2 else
                        f" : le marché attend un taux plus bas de {fr(abs(gap) * 100, 0)} points de base, il parie sur davantage de baisses que ce que la Fed "
                        "annonce ; si la Fed tient sa ligne, ce pari peut se défaire (taux en hausse)." if gap < 0 else
                        f" : le marché attend un taux plus haut de {fr(gap * 100, 0)} points de base, il doute des baisses annoncées par la Fed."))
    n = f.get("next")
    if n:
        when = datetime.fromtimestamp(n["decision"] / 1000, timezone.utc)
        L.append(f"Prochaine décision de la Fed le {when.day} {mw.MONTHS[when.month - 1]} {when.year} "
                 + ("(aujourd'hui ou demain)" if n["days"] < 1 else f"(dans {n['days']} jour{'s' if n['days'] > 1 else ''})")
                 + (", avec de nouvelles projections de ses membres." if n["sep"] else "."))
    return L


# ---------- 4. estimation du terminal pour les annonces a venir ----------
W_CPI = {"core": 0.79, "food": 0.135, "gas": 0.035, "energy_services": 0.04}       # poids approximatifs dans l'indice des prix a la consommation
ENERGY_SERVICES_TREND = 0.3                                                      # electricite et gaz : hausse mensuelle typique (%)
MOM_BASE = {"CPIAUCNS": "CPIAUCSL", "CPILFENS": "CPILFESL"}                       # glissement annuel : estime a partir de la serie corrigee


def _mom(m, ym):
    a, b = m.get(ym), m.get(mw.month_shift(ym, -1))
    return (a / b - 1) * 100 if a and b else None


def _trend(m, ref, k=3, back=6):
    vals, ym = [], mw.month_shift(ref, -1)
    for _ in range(back):
        v = _mom(m, ym)
        if v is not None:
            vals.append(v)
        if len(vals) >= k:
            break
        ym = mw.month_shift(ym, -1)
    return sum(vals) / len(vals) if len(vals) >= 2 else None


def _gas_seasonal(gas: list) -> dict:
    """Variation moyenne du prix de l'essence par mois de l'annee (saisonnalite brute, sur tout l'historique)."""
    avg = {}
    for t, v in gas:
        d = datetime.fromtimestamp(t / 1000, timezone.utc)
        avg.setdefault((d.year, d.month), []).append(v)
    mm = {k: sum(v) / len(v) for k, v in avg.items()}
    by = {}
    for (y, m), v in mm.items():
        p = mm.get(mw.month_shift((y, m), -1))
        if p:
            by.setdefault(m, []).append((v / p - 1) * 100)
    return {m: sum(v) / len(v) for m, v in by.items() if len(v) >= 3}, mm


def _gas_effect(gas, ref, sm=None):
    """Variation du prix de l'essence (moyenne du mois de reference face au mois d'avant), corrigee de la saisonnalite moyenne.
    sm : (saisonnalite, moyennes mensuelles) deja calculees."""
    seas, mm = sm or _gas_seasonal(gas)
    a, b = mm.get(ref), mm.get(mw.month_shift(ref, -1))
    if not a or not b:
        return None
    return (a / b - 1) * 100 - seas.get(ref[1], 0.0)


def _cpi_headline(D, ref, t, sm=None):
    core = _trend(D.month_map("CPILFESL", t, months=80), ref)
    food = _trend(D.month_map("CPIUFDSL", t, months=80), ref)
    gas = _gas_effect(D.known("GASREGW", t), ref, sm)
    if core is None:
        return None, ""
    v = W_CPI["core"] * core + W_CPI["food"] * (food if food is not None else 0.25) + W_CPI["gas"] * (gas or 0.0) + W_CPI["energy_services"] * ENERGY_SERVICES_TREND
    how = f"tendance sous-jacente {fr(core, 2)} % par mois" + (f", alimentation {fr(food, 2)} %" if food is not None else "") + \
          (f", essence {fr(gas, 1, True)} % sur le mois (corrigé des saisons)" if gas is not None else ", prix de l'essence indisponible")
    return v, how


def _pce_from_cpi(D, sid, ref, t):
    """Inflation PCE : moitie tendance du PCE, moitie inflation CPI du meme mois (si deja publiee) moins l'ecart moyen CPI − PCE sur 2 ans."""
    pm = D.month_map(sid, t, months=80)
    trend = _trend(pm, ref)
    csid = "CPILFESL" if sid == "PCEPILFE" else "CPIAUCSL"
    cm = D.month_map(csid, t, months=80)
    c = _mom(cm, ref)
    gaps = [(_mom(cm, ym), _mom(pm, ym)) for ym in (mw.month_shift(ref, -k) for k in range(1, 25))]
    gaps = [a - b for a, b in gaps if a is not None and b is not None]
    if c is not None and len(gaps) >= 6 and trend is not None:
        bias = sum(gaps) / len(gaps)
        return 0.5 * (c - bias) + 0.5 * trend, f"moitié tendance du PCE ({fr(trend, 2)} %), moitié CPI du même mois ({fr(c, 2)} %) moins l'écart moyen ({fr(bias, 2)})"
    return trend, (f"tendance des 3 derniers mois ({fr(trend, 2)} % par mois)" if trend is not None else "")


def estimate(ev: dict, fred: dict, t: int, D: Data | None = None) -> dict | None:
    """Estimation du terminal pour une annonce americaine couverte par FRED, dans les unites du calendrier : {value, how, kind}."""
    import re
    if ev.get("country") != "USD":
        return None
    title = ev.get("title", "").lower().strip()
    hit = next(((sid, kind, gap) for pat, sid, kind, gap in mw.EVENT_MAP if re.search(pat, title)), None)
    if not hit:
        return None
    sid, kind, gap = hit
    D = D or Data(fred)
    if kind == "claims":
        cl = D.known("ICSA", t, last=4)
        if len(cl) < 4:
            return None
        return {"value": sum(x[1] for x in cl) / 4 / 1000, "how": "moyenne des 4 dernières semaines", "kind": kind, "sid": sid}
    if kind == "rate":
        return None
    if kind == "quarter":
        d = datetime.fromtimestamp(ev["t"] / 1000, timezone.utc)
        q0 = (d.year, (d.month - 1) // 3 * 3 + 1)
        ref = mw.month_shift(q0, -3)
        v = D.month_map("GDPNOW", t, months=12).get(ref)
        return {"value": v, "how": "estimation GDPNow de la Fed d'Atlanta pour ce trimestre", "kind": kind, "sid": "GDPNOW"} if v is not None else None
    ref = mw.ym_of(ev["t"] - gap * DAY)
    base = MOM_BASE.get(sid, sid)
    if kind in ("mom", "yoy"):
        if base == "CPIAUCSL":
            v, how = _cpi_headline(D, ref, t)
        elif base in ("PCEPI", "PCEPILFE"):
            v, how = _pce_from_cpi(D, base, ref, t)
        else:
            v = _trend(D.month_map(base, t), ref)
            how = f"tendance des 3 derniers mois ({fr(v, 2)} % par mois)" if v is not None else ""
        if v is None:
            return None
        if kind == "yoy":
            m = D.month_map(base, t)
            prev, old = m.get(mw.month_shift(ref, -1)), m.get(mw.month_shift(ref, -12))
            if not prev or not old:
                return None
            return {"value": (prev * (1 + v / 100) / old - 1) * 100, "how": how + ", ramené sur un an", "kind": kind, "sid": base}
        return {"value": v, "how": how, "kind": kind, "sid": base}
    m = D.month_map(sid, t)
    last = _last_before(m, ref)                       # dernier mois publie avant le mois de reference (publication retardee : on remonte)
    if last is None:
        return None
    if kind == "diffK":
        ds = [m.get(mw.month_shift(last, -k)) for k in range(0, 4)]
        if None in ds:
            return None
        return {"value": (ds[0] - ds[3]) / 3, "how": "moyenne des 3 derniers mois publiés", "kind": kind, "sid": sid}
    if kind == "level":
        a, b = m.get(last), m.get(mw.month_shift(last, -3))
        if b is None:
            return None
        return {"value": a + (a - b) / 3, "how": "dernier chiffre prolongé de sa tendance sur 3 mois", "kind": kind, "sid": sid}
    if kind == "levelM":
        return {"value": m[last] / 1000.0, "how": "dernier chiffre", "kind": kind, "sid": sid}
    return None


def _last_before(m: dict, ref, back: int = 6):
    ym = mw.month_shift(ref, -1)
    for _ in range(back):
        if ym in m:
            return ym
        ym = mw.month_shift(ym, -1)
    return None


def estimate_error(fred: dict, sid: str, kind: str, t: int, D: Data | None = None) -> dict | None:
    """Erreur moyenne de la meme methode d'estimation sur les 5 dernieres annees (chiffres revises de FRED : approximatif)."""
    D = D or Data(fred)
    errs = []
    if kind == "claims":
        cl = D.known("ICSA", t, last=110)
        for j in range(4, len(cl)):
            errs.append(abs(cl[j][1] - sum(x[1] for x in cl[j - 4:j]) / 4) / 1000)
    elif kind == "quarter":
        gn, gdp = D.month_map("GDPNOW", t, months=80), D.month_map("A191RL1Q225SBEA", t, months=80)
        errs = [abs(gn[k] - gdp[k]) for k in gn if k in gdp][-20:]
    else:
        base = MOM_BASE.get(sid, sid)
        sm = _gas_seasonal(D.known("GASREGW", t)) if base == "CPIAUCSL" else None
        m = D.month_map(base, t, months=80)
        last = mw.last_ym(D.known(base, t, last=1))
        if not last:
            return None
        for k in range(1, 61):
            ref = mw.month_shift(last, -k + 1)
            if kind in ("mom", "yoy"):
                if base == "CPIAUCSL":
                    est, _ = _cpi_headline(D, ref, t, sm)
                elif base in ("PCEPI", "PCEPILFE"):
                    est, _ = _pce_from_cpi(D, base, ref, t)
                else:
                    est = _trend(m, ref)
                act = _mom(m, ref)
            elif kind == "diffK":
                ds = [m.get(mw.month_shift(ref, -j)) for j in range(0, 5)]
                est = (ds[1] - ds[4]) / 3 if None not in ds else None
                act = ds[0] - ds[1] if None not in ds[:2] else None
            elif kind == "level":
                a, b, c = m.get(ref), m.get(mw.month_shift(ref, -1)), m.get(mw.month_shift(ref, -4))
                est = b + (b - c) / 3 if b is not None and c is not None else None
                act = a
            elif kind == "levelM":
                a, b = m.get(ref), m.get(mw.month_shift(ref, -1))
                est, act = (b / 1000 if b is not None else None), (a / 1000 if a is not None else None)
            else:
                return None
            if est is not None and act is not None:
                errs.append(abs(act - est))
    errs = [e for e in errs if math.isfinite(e)]
    if len(errs) < 8:
        return None
    errs_sorted = sorted(errs)
    return {"mae": sum(errs) / len(errs), "median": errs_sorted[len(errs) // 2], "n": len(errs)}


def lean(ev, est, err, cls) -> dict:
    """Ecart estimation − consensus rapporte a l'erreur habituelle de l'estimation : en dessous de la moitie, pas de signal."""
    f = ev.get("fnum")
    if est is None or f is None or not err or not err.get("mae"):
        return {"z": None, "dir": 0, "text": ""}
    d = est["value"] - f
    z = d / err["mae"]
    if abs(z) < 0.5:
        return {"z": round(z, 2), "dir": 0, "text": "Pas de signal : l'écart entre l'estimation et le consensus est plus petit que l'erreur habituelle de l'estimation."}
    up = d > 0
    key = cls["key"]
    if cls["cat"] == "inflation":
        txt = ("risque d'un chiffre plus CHAUD que le consensus, défavorable aux actifs à risque s'il se confirme" if up else
               "risque d'un chiffre plus FROID que le consensus, favorable aux actifs à risque s'il se confirme")
    elif key in ("UNRATE", "CLAIMS"):
        txt = ("risque d'un emploi plus FAIBLE que prévu (chiffre au-dessus du consensus) : plus de baisses de taux, mais attention à la peur de la récession" if up else
               "risque d'un emploi plus SOLIDE que prévu : moins de raisons pour la Fed de baisser ses taux")
    else:
        txt = ("risque d'un chiffre plus SOLIDE que le consensus : bon pour l'économie, moins de baisses de taux à attendre" if up else
               "risque d'un chiffre plus FAIBLE que le consensus : plus de baisses de taux à attendre, avec la peur d'un ralentissement en toile de fond")
    return {"z": round(z, 2), "dir": 1 if up else -1, "text": txt[0].upper() + txt[1:] + f" (écart de {fr(abs(z), 1)} fois l'erreur habituelle)."}


def _dec(ev):
    return mw._decimals(ev.get("forecast"), ev.get("previous"))


def upcoming(calendar: dict, fred: dict, t: int, until: int, D: Data | None = None) -> list:
    """Annonces importantes entre t et until, avec l'estimation du terminal quand elle existe."""
    D = D or Data(fred)
    out, errs = [], {}
    for e in sorted((calendar or {}).values(), key=lambda x: x["t"]):
        if not (t < e["t"] <= until):
            continue
        cls = macro_engine.classify(e["title"], e["country"])
        if not ((e["country"] == "USD" and cls["w"] >= 0.4 and cls["key"] != "OTHER") or e.get("impact", 0) == 3):
            continue
        est = estimate(e, fred, t, D)
        err = None
        if est:
            k = (est["sid"], est["kind"])
            if k not in errs:
                errs[k] = estimate_error(fred, est["sid"], est["kind"], t, D)
            err = errs[k]
        ln = lean(e, est, err, cls)
        exp = macro_engine.expectation(e, cls)
        unit = "K" if est and est["kind"] in ("diffK", "claims") else "M" if est and est["kind"] == "levelM" else "%"
        dec = _dec(e) + (0 if unit == "K" else 1)
        out.append({"id": e["id"], "t": e["t"], "country": e["country"], "title": e["title"], "label": mw.event_label(e, cls), "cat": cls["cat"], "key": cls["key"],
                    "w": cls["w"], "impact": e.get("impact", 0), "forecast": e.get("forecast") or "", "previous": e.get("previous") or "",
                    "estimate": round(est["value"], dec) if est else None, "estimateText": (f"{fr(est['value'], dec)}{' ' if unit == '%' else ''}{unit}" if est else ""),
                    "how": est["how"] if est else "", "error": round(err["mae"], dec) if err else None,
                    "errorText": (f"± {fr(err['mae'], dec)}{' ' if unit == '%' else ''}{unit}" if err else ""), "lean": ln["dir"], "leanZ": ln["z"], "leanText": ln["text"],
                    "scenUp": exp.get("scen_up", ""), "scenDn": exp.get("scen_dn", "")})
    return out


# ---------- 5. annonces de la Fed et des banques centrales ----------
def fed_comms(fed: dict, t0: int, t1: int) -> list:
    """Communication de la Fed entre t0 et t1 (communiques, comptes rendus, discours), la plus recente d'abord."""
    from data import fed as fed_mod
    KIND = {"statement": "Communiqué", "minutes": "Compte rendu", "speech": "Discours", "projections": "Projections", "note": "Note", "release": "Communiqué"}
    out = []
    for it in (fed or {}).get("items") or []:
        if t0 <= it["t"] <= t1:
            out.append({"t": it["t"], "kind": it["kind"], "kindLabel": KIND.get(it["kind"], "Publication"), "title": it["title"], "link": it["link"],
                        "speaker": fed_mod.speaker(it) if it["kind"] == "speech" else ""})
    return sorted(out, key=lambda x: x["t"], reverse=True)


def sol_beta(crypto_daily: dict, t: int, days: int = 90):
    """Amplification de solana face au bitcoin (beta des rendements quotidiens sur 90 jours)."""
    b, s = dict(crypto_daily.get("BTC") or []), dict(crypto_daily.get("SOL") or [])
    keys = sorted(k for k in b if k in s and t - (days + 1) * DAY <= k <= t)
    rb, rs = [], []
    for a, c in zip(keys, keys[1:]):
        if c - a == DAY and b[a] and s[a]:
            rb.append(b[c] / b[a] - 1)
            rs.append(s[c] / s[a] - 1)
    if len(rb) < 40:
        return None
    mb, ms = sum(rb) / len(rb), sum(rs) / len(rs)
    var = sum((x - mb) ** 2 for x in rb)
    if var <= 0:
        return None
    beta = sum((x - mb) * (y - ms) for x, y in zip(rb, rs)) / var
    corr = beta * math.sqrt(var / sum((y - ms) ** 2 for y in rs)) if any(y != ms for y in rs) else None
    return {"beta": round(beta, 2), "corr": round(corr, 2) if corr is not None else None, "n": len(rb)}


# ---------- assemblage ----------
def tone_label(x):
    return "favorable" if x >= 1.2 else "plutôt favorable" if x >= 0.4 else "neutre" if x > -0.4 else "plutôt défavorable" if x > -1.2 else "défavorable"


def build(t: int, fred: dict, calendar: dict, fed: dict, crypto_daily: dict, verdict: dict | None = None, study: dict | None = None,
          rstudy: dict | None = None, lagged: bool = False, horizon_days: int = 7) -> dict:
    """Vision de la semaine a l'instant t (lagged : vision reconstruite apres coup, seuls les chiffres deja publies a t comptent)."""
    D = Data(fred)
    reg = regime_at(D, t, lagged=lagged)
    trail = regime_trail(D, t, 12, lagged_now=lagged)
    sur = surprises(calendar, fred, t)
    fv = fed_view(D, t, (fed or {}).get("meetings") or [], lagged)
    up = upcoming(calendar, fred, t, t + horizon_days * DAY, D)
    comms = fed_comms(fed, t - 7 * DAY, t)
    beta = sol_beta(crypto_daily or {}, t)
    # ton d'ensemble : composantes affichees
    parts = []
    if verdict and verdict.get("score") is not None:
        parts.append(("Vent macro du bilan (thèmes)", clip(verdict["score"] / 3, -1, 1)))
    if reg["quad"]:
        parts.append(("Régime " + QUADS[reg["quad"]][0].lower(), QUADS[reg["quad"]][2] * 0.8))
    iv = sur["inflation"]["value"]
    if iv is not None:
        parts.append(("Surprises sur l'inflation", clip(-iv, -1, 1) * 0.6))
    ch = fv.get("cutsChange")
    if ch is not None and abs(ch) >= 0.2:
        parts.append(("Anticipations sur la Fed cette semaine", clip(ch, -1, 1) * 0.6))
    score = sum(p[1] for p in parts) if parts else None
    label = tone_label(score) if score is not None else None
    key = sorted(up, key=lambda e: -(e["w"] * (e["impact"] or 1)))[:3]
    view = {"t": t, "score": round(score, 2) if score is not None else None, "label": label,
            "parts": [{"name": n, "score": round(s, 2)} for n, s in parts], "regime": {**reg, "trail": trail, "text": QUADS[reg["quad"]][1] if reg["quad"] else ""},
            "regimeStudy": rstudy, "surprises": sur, "fed": fv, "upcoming": up, "key": [e["id"] for e in key], "comms": comms, "solBeta": beta}
    view["lines"] = narrative(view, study)
    return view


def narrative(v: dict, study: dict | None = None) -> list:
    """Vision globale en quelques paragraphes, chacun ecrit a partir des chiffres du dessus. [{title, text}]"""
    L = []
    r = v["regime"]
    if r["quad"]:
        gw, iw = momentum_word(r["g"]), momentum_word(r["i"])
        top_g = max(r["growth"], key=lambda x: abs(x["score"]))
        top_i = max(r["inflation"], key=lambda x: abs(x["score"]))
        L.append({"title": "Où en est l'économie américaine",
                  "text": f"{r['label']}. La croissance {gw} (le plus parlant : {low1(top_g['name'])}, {top_g['text']}) et l'inflation {iw} "
                          f"({low1(top_i['name'])}, {top_i['text']}). {r['text']}"})
    f = v["fed"]
    if f.get("text"):
        L.append({"title": "Ce que le marché attend de la Fed", "text": " ".join(f["text"])})
    s = v["surprises"]
    a, i = s["activity"], s["inflation"]
    if a["value"] is not None or i["value"] is not None:
        txt = []
        def counts(x):
            return f"{x['n']} chiffres : {x['above']} au-dessus, {x['below']} en dessous, {x['inline']} conforme{'s' if x['inline'] > 1 else ''}"
        if a["value"] is not None:
            txt.append(f"activité {a['label']} ({counts(a)})")
        if i["value"] is not None:
            txt.append(f"inflation {i['label']} ({counts(i)})")
        hint = ""
        if i["value"] is not None and i["value"] >= 0.15:
            hint = " Une inflation qui surprend à la hausse retarde les baisses de taux : c'est le principal risque pour les cryptos."
        elif i["value"] is not None and i["value"] <= -0.15:
            hint = " Une inflation qui surprend à la baisse donne de la marge à la Fed : soutien pour les actifs à risque."
        if a["value"] is not None and a["value"] <= -0.5:
            hint += " Les chiffres d'activité déçoivent nettement : les baisses de taux se rapprochent, mais la peur d'un ralentissement peut peser d'abord."
        L.append({"title": "Les chiffres face au consensus (8 dernières semaines)", "text": "Face aux prévisions des économistes : " + " ; ".join(txt) + "." + hint})
    ups = v["upcoming"]
    if ups:
        key = [e for e in ups if e["id"] in v["key"]]
        def when(e):
            d = datetime.fromtimestamp(e["t"] / 1000, timezone.utc)
            return f"{['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche'][d.weekday()]} {d.day}"
        txt = "À surveiller : " + " ; ".join(f"{e['label']} ({when(e)}" + (f", consensus {fx(e['forecast'])}" if e["forecast"] else "") +
                                             (f", estimation du terminal {e['estimateText']}" if e.get("estimateText") else "") + ")" for e in key) + "."
        sig = [e for e in ups if e.get("lean")]
        if sig:
            txt += " " + " ".join(f"{e['label']} : {e['leanText']}" for e in sig[:3])
        else:
            txt += " Aucune estimation du terminal ne s'écarte nettement du consensus : pas de surprise annoncée par les tendances."
        L.append({"title": "Les annonces qui comptent", "text": txt})
    if v.get("comms"):
        c = v["comms"]
        st = [x for x in c if x["kind"] in ("statement", "minutes")]
        sp = [x for x in c if x["kind"] == "speech"]
        bits = []
        if st:
            bits.append(" ; ".join(x["kindLabel"].lower() + " du " + datetime.fromtimestamp(x["t"] / 1000, timezone.utc).strftime("%d/%m") for x in st))
        if sp:
            who = sorted({x["speaker"] for x in sp if x["speaker"]})
            bits.append(f"{len(sp)} discours" + (f" ({', '.join(who[:5])})" if who else ""))
        L.append({"title": "Ce que la Fed a publié cette semaine", "text": "La Fed a publié : " + " ; ".join(bits) + ". Le détail et les liens sont plus bas ; "
                 "le commentaire de Claude peut les résumer."})
    tone = v.get("label")
    if tone:
        txt = f"Lecture d'ensemble {tone} pour les actifs à risque et les cryptos"
        comps = [p for p in v["parts"] if abs(p["score"]) >= 0.2]
        if comps:
            txt += " (" + ", ".join(f"{p['name'].lower()} {'▲' if p['score'] > 0 else '▼'}" for p in comps) + ")"
        txt += "."
        b = v.get("solBeta")
        if b and b.get("beta") and b["beta"] >= 0.5 and (b.get("corr") or 0) >= 0.4:
            txt += (f" Solana amplifie les mouvements du bitcoin : sur 90 jours, quand le bitcoin bouge de 1 %, solana bouge en moyenne de {fr(b['beta'], 1)} %"
                    + (f" (corrélation {fr(b['corr'], 2)})." if b.get("corr") is not None else "."))
        if study and study.get("ready"):
            net = [x for x in study["rows"] if "net" in x["verdict"] and "inverse" not in x["verdict"]]
            txt += (" Sur l'historique du bitcoin, les moteurs qui ont vraiment compté la semaine suivante : " + ", ".join(x["label"].lower() for x in net) + "."
                    if net else " Sur l'historique du bitcoin, aucun moteur macro pris seul n'a fait de différence nette la semaine suivante : la macro donne le décor, "
                                "le flux et la liquidité du marché crypto décident du timing.")
        rs = v.get("regimeStudy")
        if rs and rs.get("ready") and v["regime"]["quad"]:
            row = next((x for x in rs["rows"] if x["quad"] == v["regime"]["quad"]), None)
            if row and row["n"] >= 6:
                txt += (f" Dans ce quadrant (depuis {rs['from']}), le bitcoin a fait en moyenne {fr(row['mean'], 1, True)} % le mois suivant ({row['n']} mois, en hausse {fr(row['hit'], 0)} % du temps) : "
                        + ("un écart net avec les autres mois." if row["verdict"] == "écart net" else "pas distinguable des autres mois (≈ hasard)."))
        txt += " Rien de cela n'est une prévision : ce sont des lectures classiques reliées aux chiffres, à confronter au graphique (volume profile, CVD, VWAP)."
        L.append({"title": "Ce que cela veut dire pour le bitcoin et solana", "text": txt})
    return L


def summary_lines(v: dict) -> list:
    """Version texte (Telegram, contexte de Claude)."""
    if not v:
        return []
    L = ["Vision de la semaine" + (f" : {v['label']} pour les actifs à risque" if v.get("label") else "")]
    for p in v.get("lines") or []:
        L.append(f"• {p['title']} : {p['text']}")
    ups = v.get("upcoming") or []
    if ups:
        L.append("Annonces à venir (consensus / estimation du terminal) :")
        for e in ups[:10]:
            d = datetime.fromtimestamp(e["t"] / 1000, timezone.utc).strftime("%a %d/%m %H:%M UTC")
            L.append(f"   – {d} {e['label']}" + (f" : consensus {fx(e['forecast'])}" if e["forecast"] else "") +
                     (f", terminal {e['estimateText']} {e['errorText']}" if e.get("estimateText") else "") + (f" → {e['leanText']}" if e.get("lean") else ""))
    return L
