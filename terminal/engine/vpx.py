"""Volume profiles choisis (V4) : profils glissants (N derniers jours), depuis une date, ou sur une periode
calendaire (jour / semaine / mois / trimestre / annee, courante ou precedente). Chaque profil donne POC, VAH,
VAL et HVN : ce sont des niveaux supplementaires pour les confluences, en plus des profils automatiques
(jour, semaine, mois, annee courants et precedents).

« Selon la timeframe » : le choix « auto » prend trois fenetres glissantes adaptees a l'echelle du graphique
(5 min -> 3, 7, 14 jours ; 1 h -> 30, 90, 180 jours ; 1 j -> 1, 2 et 4 ans...)."""
from bisect import bisect_left
from datetime import datetime, timedelta, timezone

from . import vp

DAY = 86_400_000
HOUR = 3_600_000
PERIODS = {"day": "jour", "week": "semaine", "month": "mois", "quarter": "trimestre", "year": "année"}
AUTO_BY_TF = {"5m": (3, 7, 14), "15m": (7, 14, 30), "1h": (30, 90, 180), "4h": (90, 180, 365), "1d": (365, 730, 1460)}
MAX_SPECS = 8
MAX_ANCHORS = 6


def _utc(ms):
    return datetime.fromtimestamp(ms / 1000.0, timezone.utc)


def _ms(dt):
    return int(dt.timestamp() * 1000)


def normalize_specs(raw) -> list[dict]:
    """Valide une liste de specs venant de l'interface. Leve ValueError avec un message lisible."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("liste de volume profiles vide ou invalide")
    if len(raw) > MAX_SPECS:
        raise ValueError(f"{MAX_SPECS} volume profiles au maximum")
    out, seen = [], set()
    for s in raw:
        if not isinstance(s, dict):
            raise ValueError("volume profile invalide")
        kind = s.get("kind")
        if kind == "auto":
            spec = {"kind": "auto"}
        elif kind == "rolling":
            days = int(float(s.get("days", 0)))
            if not 1 <= days <= 2500:
                raise ValueError("durée du profil glissant : entre 1 et 2500 jours")
            spec = {"kind": "rolling", "days": days}
        elif kind == "since":
            try:
                d = datetime.strptime(str(s.get("date", "")), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                raise ValueError("date invalide (AAAA-MM-JJ attendu)")
            if d < datetime(2017, 1, 1, tzinfo=timezone.utc) or d > datetime.now(timezone.utc):
                raise ValueError("date hors limites")
            spec = {"kind": "since", "date": d.strftime("%Y-%m-%d")}
        elif kind == "period":
            per, back = s.get("period"), int(float(s.get("back", 0)))
            if per not in PERIODS or not 0 <= back <= 24:
                raise ValueError("période invalide")
            spec = {"kind": "period", "period": per, "back": back}
        else:
            raise ValueError("type de volume profile inconnu")
        key = tuple(sorted(spec.items()))
        if key not in seen:
            seen.add(key)
            out.append(spec)
    return out


def normalize_anchors(raw) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_ANCHORS:
        raise ValueError(f"{MAX_ANCHORS} dates d'ancrage au maximum")
    out = []
    for a in raw:
        try:
            d = datetime.strptime(str(a), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise ValueError("date d'ancrage invalide (AAAA-MM-JJ attendu)")
        if d < datetime(2017, 1, 1, tzinfo=timezone.utc) or d > datetime.now(timezone.utc):
            raise ValueError("date d'ancrage hors limites")
        s = d.strftime("%Y-%m-%d")
        if s not in out:
            out.append(s)
    return out


def period_bounds(period: str, back: int, now_ms: int):
    """(debut, fin) en ms de la periode calendaire UTC courante (back=0) ou de la back-ieme precedente."""
    t = _utc(now_ms)
    if period == "day":
        s = t.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=back)
        e = s + timedelta(days=1)
    elif period == "week":
        s = t.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=t.weekday() + 7 * back)
        e = s + timedelta(days=7)
    elif period == "month":
        m = t.year * 12 + t.month - 1 - back
        s = datetime(m // 12, m % 12 + 1, 1, tzinfo=timezone.utc)
        n = m + 1
        e = datetime(n // 12, n % 12 + 1, 1, tzinfo=timezone.utc)
    elif period == "quarter":
        q = t.year * 4 + (t.month - 1) // 3 - back
        s = datetime(q // 4, (q % 4) * 3 + 1, 1, tzinfo=timezone.utc)
        n = q + 1
        e = datetime(n // 4, (n % 4) * 3 + 1, 1, tzinfo=timezone.utc)
    else:
        y = t.year - back
        s, e = datetime(y, 1, 1, tzinfo=timezone.utc), datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    return _ms(s), _ms(e)


def _days_label(n):
    return f"{n // 365} an{'s' if n >= 730 else ''}" if n >= 365 and n % 365 == 0 else f"{n}j"


def resolve(specs, tf: str, now_ms: int):
    """Specs -> fenetres [{id, label, kind, start, end}] ; les fenetres glissantes se terminent a l'heure ronde courante."""
    now = now_ms - now_ms % HOUR
    wins, seen = [], set()

    def add(w):
        if w["id"] not in seen:
            seen.add(w["id"])
            wins.append(w)

    for s in specs:
        k = s["kind"]
        if k == "auto":
            for n in AUTO_BY_TF.get(tf, AUTO_BY_TF["1h"]):
                add({"id": f"r{n}", "label": f"VP {_days_label(n)}", "kind": "rolling", "start": now - n * DAY, "end": now + HOUR, "auto": True})
        elif k == "rolling":
            n = s["days"]
            add({"id": f"r{n}", "label": f"VP {_days_label(n)}", "kind": "rolling", "start": now - n * DAY, "end": now + HOUR})
        elif k == "since":
            st = _ms(datetime.strptime(s["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc))
            add({"id": f"s{s['date']}", "label": f"VP depuis {s['date'][8:]}/{s['date'][5:7]}/{s['date'][2:4]}", "kind": "since", "start": st, "end": now + HOUR})
        else:
            st, en = period_bounds(s["period"], s["back"], now_ms)
            nm = PERIODS[s["period"]]
            add({"id": f"{s['period']}{s['back']}", "label": f"VP {nm}" + (f" -{s['back']}" if s["back"] else ""), "kind": "period",
                 "start": st, "end": min(en, now + HOUR)})
    return wins


def build(candles, start: int, end: int, rows_cap: int = 100, hvn_n: int = 2):
    """Profil des bougies dont l'ouverture est dans [start, end). Renvoie None si trop peu de donnees."""
    times = [k.t for k in candles]
    i0, i1 = bisect_left(times, start), bisect_left(times, end)
    sel = [k for k in candles[i0:i1] if k.v > 0]
    if len(sel) < 3:
        return None
    p = vp.Profile()
    for k in sel:
        p.add(k.l, k.h, k.v)
    n = len(sel)
    rows, b0, g = vp.agg_rows(p, min(vp.auto_rows(n), rows_cap))
    poc, vah, val = vp.stats(rows, b0, g)
    hv = vp.hvn(rows, b0, g, hvn_n)
    edges = [[vp.VP_GRID.price(b0 + i * g, 0.0), vp.VP_GRID.price(b0 + (i + 1) * g, 0.0), v] for i, v in enumerate(rows)]
    return {"poc": poc, "vah": vah, "val": val, "hvn": hv, "rows": edges, "bars": n, "volume": sum(rows),
            "t0": sel[0].t, "t1": sel[-1].t + 1}
