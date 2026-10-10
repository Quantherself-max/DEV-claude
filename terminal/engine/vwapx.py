"""Series VWAP (jour / semaine / mois / annee, avec ecart-type) et VWAP ancrees, alignees sur les bougies du graphique.
Calcul sur les bougies 1h (historique complet, bougie en cours incluse) : une valeur par bougie du graphique,
prise a la fin de cette bougie. Une remise a zero de la periode coupe la ligne (valeur nulle sur la 1re bougie)."""
import math
from bisect import bisect_right
from datetime import datetime, timezone

from .periods import period_key

HOUR = 3_600_000
DAY = 86_400_000
KIND_MS = {"D": DAY, "W": 7 * DAY, "M": 28 * DAY, "Y": 365 * DAY}
NAMES = {"D": "VWAP jour", "W": "VWAP semaine", "M": "VWAP mois", "Y": "VWAP année"}


def _start_of(kind, t):
    d = datetime.fromtimestamp(t / 1000.0, timezone.utc)
    if kind == "Y":
        return int(datetime(d.year, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    if kind == "M":
        return int(datetime(d.year, d.month, 1, tzinfo=timezone.utc).timestamp() * 1000)
    return None


def auto_anchors(now_ms):
    """Ancrages automatiques : debut de l'annee et du mois precedents (comme les AVWAP « previous » du script Pine)."""
    d = datetime.fromtimestamp(now_ms / 1000.0, timezone.utc)
    py = int(datetime(d.year - 1, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    m = d.year * 12 + d.month - 2
    pm = int(datetime(m // 12, m % 12 + 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    return [("AVWAP année préc.", py), ("AVWAP mois préc.", pm)]


def swing_anchors(h1, now_ms):
    """Ancrages sur les extremes recents : plus bas / plus haut de l'annee et des 3 derniers mois (la ou les poids se sont
    inverses). Deux extremes a moins de 4 jours l'un de l'autre ne comptent qu'une fois."""
    out = []
    for days, lab in ((365, "1 an"), (90, "3 mois")):
        sub = [k for k in h1 if k.t >= now_ms - days * DAY]
        if len(sub) < 24 * 10:
            continue
        lo, hi = min(sub, key=lambda k: k.l), max(sub, key=lambda k: k.h)
        for name, k in ((f"AVWAP bas {lab}", lo), (f"AVWAP haut {lab}", hi)):
            if all(abs(k.t - a) > 4 * DAY for _, a in out):
                out.append((name, k.t - k.t % HOUR))
    return out


def series(h1, chart_times, tf_ms, anchors, kinds=("D", "W", "M", "Y")):
    """h1 : bougies 1h triees (la derniere peut etre en cours) ; chart_times : ouvertures des bougies du graphique (ms) ;
    anchors : [(libelle, ms)]. Renvoie {vwap:{K:[v|None]}, sd:{K:[...]}, avwap:[{label, anchor, v:[...]}]}."""
    ends = [k.t + HOUR for k in h1]
    out_v = {k: [None] * len(chart_times) for k in kinds if KIND_MS[k] > tf_ms}      # inutile si la periode <= une bougie
    out_s = {k: [None] * len(chart_times) for k in out_v}
    # etat apres chaque bougie 1h : (vwap, sd, cle de periode)
    st = {k: {"key": None, "pv": 0.0, "v": 0.0, "pv2": 0.0} for k in out_v}
    snap = {k: [] for k in out_v}
    av = [{"label": lab, "anchor": a, "pv": 0.0, "v": 0.0, "vals": []} for lab, a in anchors]
    for k in h1:
        tp = (k.h + k.l + k.c) / 3.0
        for kind, s in st.items():
            key = period_key(kind, k.t)
            if key != s["key"]:
                s.update(key=key, pv=0.0, v=0.0, pv2=0.0)
            s["pv"] += tp * k.v; s["v"] += k.v; s["pv2"] += tp * tp * k.v
            if s["v"] > 0:
                vw = s["pv"] / s["v"]
                snap[kind].append((vw, math.sqrt(max(s["pv2"] / s["v"] - vw * vw, 0.0)), key))
            else:
                snap[kind].append((None, None, key))
        for a in av:
            if k.t >= a["anchor"]:
                a["pv"] += tp * k.v; a["v"] += k.v
            a["vals"].append(a["pv"] / a["v"] if a["v"] > 0 else None)
    prev_key = {k: None for k in out_v}
    for i, t in enumerate(chart_times):
        j = bisect_right(ends, t + tf_ms) - 1                  # derniere bougie 1h terminee a la fin de la bougie du graphique
        if j < 0:
            continue
        for kind in out_v:
            vw, sd, key = snap[kind][j]
            if key != prev_key[kind]:
                prev_key[kind] = key                           # remise a zero : on coupe la ligne
                continue
            out_v[kind][i], out_s[kind][i] = vw, sd
    av_out = []
    for a in av:
        vals = [None] * len(chart_times)
        for i, t in enumerate(chart_times):
            j = bisect_right(ends, t + tf_ms) - 1
            if j >= 0 and t + tf_ms > a["anchor"]:
                vals[i] = a["vals"][j]
        if any(v is not None for v in vals):
            av_out.append({"label": a["label"], "anchor": a["anchor"], "v": vals})
    return {"vwap": out_v, "sd": out_s, "avwap": av_out}
