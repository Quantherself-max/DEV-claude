"""Delta, divergences et squeezes : que valent-ils vraiment sur le prix futur ? (V10)

Meme methode que le laboratoire d'indicateurs (engine/indstudy.py) mais en HEURES :
  - variables de engine/squeeze.py calculees heure par heure sans regarder le futur ; signal = rang percentile parmi les valeurs PASSEES ;
  - observations toutes les 6 heures (les fenetres de 6 a 72 h se recouvrent de toute facon : en garder une sur six accelere le calcul sans perdre d'information utile) ;
  - deux cibles : (1) le rendement du prix a 6, 24 et 72 h (une heure de decalage) ; (2) l'AMPLEUR du mouvement a venir, |rendement| rapporte a la volatilite habituelle des 30 jours
    precedents (« le mouvement sera-t-il plus grand que d'habitude ? » : c'est la vraie question d'un squeeze, dont le sens n'est connu qu'apres) ;
  - regression robuste (Newey-West), apprentissage puis test, seuil fixe par un temoin (le meme signal decale au hasard) ;
  - tableau d'EVENEMENTS : quand la variable est dans son decile haut ou bas, part de hausses, part de mouvements d'au moins 1,5 ecart-type dans chaque sens sur 24 h,
    comparees a toutes les heures de la meme periode.
Source : delta REEL (volume acheteur agressif, Binance) + interet ouvert + financement si disponibles ; sinon delta ESTIME depuis la position de la cloture dans chaque bougie 1 minute
(Bitstamp, depuis 2013) : le rapport l'indique en toutes lettres. Module PUR."""
import math
import time

from . import indstudy as ist
from . import squeeze as sq

HOUR = sq.HOUR
HOURS = (6, 24, 72)
OBS = 6                   # une observation toutes les 6 heures
LAG = 1                   # heure(s) de decalage entre le signal et l'entree
EVENT_KEYS = ("sfuel24", "lfuel24", "squp6", "sqdn6", "divp24", "divp72", "divd", "imb24", "effort24")
EVENT_TITLES = {k: (sq.CATALOG[k][1]) for k in EVENT_KEYS}
THETA = 1.5               # un « gros » mouvement = 1,5 ecart-type de la duree


def hourly_series(b1h):
    """(temps, cloture, plus haut, plus bas, volume, delta) en listes, depuis des bougies fines 1 h (engine.fine.Bars)."""
    return ([int(x) for x in b1h.t], list(b1h.c), list(b1h.h), list(b1h.l), list(b1h.v), list(b1h.d))


def to_hourly(pairs, t0: int, n: int, how: str = "last"):
    """Serie irreguliere [(t_ms, valeur)] -> liste horaire alignee sur t0 + k h (derniere valeur de l'heure) ; None si aucune valeur dans l'heure."""
    out = [None] * n
    for t, x in pairs:
        k = (t - t0) // HOUR
        if 0 <= k < n and x is not None:
            out[k] = x
    return out


def trailing_sigma(c, win: int = 720, minobs: int = 240):
    """Ecart-type des rendements horaires sur les `win` dernieres heures (cloture d'aujourd'hui comprise)."""
    r = [None] + [math.log(b / a) if (a and b and a > 0 and b > 0) else None for a, b in zip(c, c[1:])]
    out, s, q, k = [None] * len(c), 0.0, 0.0, 0
    for i, v in enumerate(r):
        if v is not None:
            s += v
            q += v * v
            k += 1
        if i >= win and r[i - win] is not None:
            u = r[i - win]
            s -= u
            q -= u * u
            k -= 1
        if k >= minobs:
            m = s / k
            var = q / k - m * m
            out[i] = math.sqrt(var) if var > 0 else None
    return out


def forward_targets(c, h, l, sig, hours=HOURS, lag: int = LAG):
    """{heures: (rendement, ampleur, hausse maximale, baisse maximale)} en listes horaires ; tout est exprime a partir de la cloture de l'heure t + lag.
    ampleur = |rendement| / (sigma_horaire x racine(duree)) ; hausse / baisse maximale = plus grand ecart du plus haut / plus bas pendant la duree, en ecarts-types."""
    n = len(c)
    out = {}
    for H in hours:
        ret, amp, up, dn = [None] * n, [None] * n, [None] * n, [None] * n
        for t in range(n):
            a, b = t + lag, t + lag + H
            if b >= n or not c[a] or not c[b] or c[a] <= 0 or c[b] <= 0 or not sig[t]:
                continue
            sd = sig[t] * math.sqrt(H)
            r = math.log(c[b] / c[a])
            ret[t], amp[t] = r, abs(r) / sd
            hi = max(h[a + 1:b + 1])
            lo = min(l[a + 1:b + 1])
            up[t] = math.log(hi / c[a]) / sd if hi > 0 else None
            dn[t] = -math.log(lo / c[a]) / sd if lo > 0 else None
        out[H] = (ret, amp, up, dn)
    return out


def _counts(rows, horizons):
    return {"indicators": len(rows), "tests": len(rows) * len(horizons), "informative": sum(1 for r in rows if r["level"] == "informatif"), "hints": sum(1 for r in rows if r["level"] == "indice")}


def _stats(vals):
    return {"n": len(vals), "mean": sum(vals) / len(vals)} if vals else None


def events(ranks: dict, fw, lo: int, sp: int, n: int, keys=EVENT_KEYS, hour_key: int = 24) -> list:
    """Pour chaque variable : decile haut puis decile bas, sur l'apprentissage et sur le test : nombre, rendement moyen, part de hausses, part de gros mouvements dans chaque sens (sur `hour_key` heures)."""
    ret, _, up, dn = fw[hour_key]

    def agg(idx):
        r = [ret[i] for i in idx if ret[i] is not None]
        u = [up[i] for i in idx if up[i] is not None]
        d = [dn[i] for i in idx if dn[i] is not None]
        if len(r) < 30:
            return None
        return {"n": len(r), "mean": sum(r) / len(r), "up": sum(1 for x in r if x > 0) / len(r), "bigUp": sum(1 for x in u if x >= THETA) / len(u) if u else None,
                "bigDn": sum(1 for x in d if x >= THETA) / len(d) if d else None}
    purge = -(-hour_key // OBS) + LAG + 1                                      # aucune fenetre d'apprentissage ne deborde sur le test
    span = {"is": range(lo, max(lo, sp - purge)), "oos": range(sp, n)}
    base = {p: agg(list(rg)) for p, rg in span.items()}
    rows = []
    for k in keys:
        rk = ranks.get(k)
        if rk is None:
            continue
        for side, test in (("haut", lambda x: x >= 0.9), ("bas", lambda x: x <= 0.1)):
            ent = {"key": k, "title": EVENT_TITLES.get(k, k), "side": side}
            for p, rg in span.items():
                ent[p] = agg([i for i in rg if rk[i] is not None and test(rk[i])])
            rows.append(ent)
    return rows, base


def run(bars1h, label: str, start_ms: int, end_ms: int, split_ms: int, oi=None, fund=None, source: str = "estimé", shifts: int = 30, hours=HOURS, progress=None) -> dict:
    """bars1h : engine.fine.Bars horaires (delta reel ou estime) ; oi = [(t_ms, contrats)], fund = [(t_ms, taux)] optionnels. Renvoie le rapport (kind « squeeze »)."""
    t0 = time.time()
    say = progress or (lambda *_: None)
    say("séries horaires…")
    t, c, h, l, v, d = hourly_series(bars1h)
    n = len(t)
    oi_h = to_hourly(oi, t[0], n) if oi else None
    fd_h = to_hourly(fund, t[0], n) if fund else None
    say("variables de flux et de levier…")
    feats = sq.features(c, v, d, oi_h, fd_h)
    sig = trailing_sigma(c)
    fw = forward_targets(c, h, l, sig, hours)
    lo_h = next((i for i, x in enumerate(t) if x >= start_ms), 0)
    sp_h = next((i for i, x in enumerate(t) if x >= split_ms), n)
    end_h = next((i for i, x in enumerate(t) if x >= end_ms), n)
    first = lo_h
    while first < end_h and (t[first] // HOUR) % OBS != 0:                     # observations calees sur 00h, 06h, 12h, 18h UTC
        first += 1
    idx = list(range(first, end_h, OBS))
    sub = lambda x: [x[i] for i in idx]
    grid = [t[i] for i in idx]
    lo, sp = 0, next((k for k, i in enumerate(idx) if i >= sp_h), len(idx))
    keys = [k // OBS for k in hours]
    fwd_ret = {k: sub(fw[H][0]) for k, H in zip(keys, hours)}
    fwd_amp = {k: sub(fw[H][1]) for k, H in zip(keys, hours)}
    price = sub(c)
    min_hist = 4 * 180
    targets = []
    spec = (("RET", "Rendement du prix", "Le prix monte-t-il ou baisse-t-il après la configuration ? (6, 24 et 72 heures)", sq.CATALOG, fwd_ret),
            ("AMP", "Ampleur du mouvement", "Le mouvement à venir est-il plus grand que d'habitude (|rendement| divisé par la volatilité des 30 derniers jours) ? C'est la question d'un squeeze.", sq.AMP_CATALOG, fwd_amp))
    ranks_ret = {}
    for key, title, desc, cat, fwd in spec:
        say(f"mesure : {title}…")
        use = {k: v_ for k, v_ in cat.items() if k in feats}
        series = {k: sub(feats[k]) for k in use}
        catalog = {k: tuple(x[:5]) for k, x in use.items()}
        rows, null, thr, last = ist.evaluate(series, price, catalog, grid, lo, sp, keys, 1, min_hist, shifts, None, fwd)
        if key == "RET":
            ranks_ret = {k: ist.expanding_rank(series[k], min_hist) for k in series}
        targets.append({"key": key, "title": title, "desc": desc, "rows": rows, "null": null, "threshold": thr, "counts": _counts(rows, keys)})
    say("événements…")
    ev, base = events(ranks_ret, {H: tuple(sub(a) for a in fw[H]) for H in hours}, lo, sp, len(idx), hour_key=24)
    ev_keys = [k // OBS for k in hours]
    rep = {"kind": "squeeze", "label": label, "computedAt": int(time.time() * 1000), "source": source, "hasOi": oi_h is not None, "hasFunding": fd_h is not None,
           "period": {"start": grid[0], "end": grid[-1] + HOUR, "split": split_ms}, "stepHours": OBS, "hours": list(hours), "horizons": ev_keys,
           "targets": targets, "events": ev, "baseline": base, "seconds": round(time.time() - t0)}
    rep["verdict"] = verdict(rep)
    return rep


def _fr(x, d=1):
    return "n/d" if x is None else f"{x:.{d}f}".replace(".", ",").replace("-", "−")


def _pct(x, d=1, sign=True):
    return "n/d" if x is None else (f"{x * 100:+.{d}f}" if sign else f"{x * 100:.{d}f}").replace(".", ",").replace("-", "−") + " %"


def verdict(rep: dict) -> dict:
    tg = {t["key"]: t for t in rep["targets"]}
    inf = [(t, r) for t in rep["targets"] for r in t["rows"] if r["level"] == "informatif"]
    hint = [(t, r) for t in rep["targets"] for r in t["rows"] if r["level"] == "indice"]
    n_tests = sum(t["counts"]["tests"] for t in rep["targets"])
    p = rep["period"]
    years = (p["end"] - p["split"]) / (365.25 * 86_400_000)
    notes = []
    real = rep["source"].startswith("réel")
    notes.append(("Données : " + rep["source"] + ". ") + (
        "Le delta est le volume acheteur agressif réel de la bourse." if real else
        "Le delta est ESTIMÉ (position de la clôture dans chaque bougie d'une minute), pas mesuré : le vrai volume acheteur agressif n'existe pas pour cette période sur ce marché. "
        "Pour la mesure avec le vrai delta, l'intérêt ouvert et le financement : python tools/fetch_history.py BTCUSDT --metrics puis python tools/run_squeeze_study.py BTCUSDT."))
    if not rep["hasOi"]:
        notes.append("Sans intérêt ouvert, les « carburants de squeeze » (shorts / longs qui s'accumulent) et le squeeze en cours ne sont pas mesurables : seules les divergences de flux et de volume le sont ici.")
    notes.append(f"Test : {_fr(years, 1)} ans (de {_d(p['split'])} à {_d(p['end'])}), sans qu'aucun choix de variable ni de seuil ne s'appuie dessus ; apprentissage avant. {n_tests} mesures au total : quelques-unes paraissent bonnes par hasard, d'où le seuil du témoin.")
    for t in rep["targets"]:
        nul = t["null"]
        notes.append(f"Cible « {t['title']} » : seuil du hasard |t| ≥ {_fr(t['threshold'])} (témoin : 95 % à {_fr(nul['p95'])}) ; {t['counts']['informative']} informatif(s), {t['counts']['hints']} indice(s).")
    ref = next((r for r in tg["RET"]["rows"] if r["key"] == "ret24"), None)
    if ref:
        hk = str(rep["horizons"][1])
        a, b = ref["h"][hk]["is"], ref["h"][hk]["oos"]
        if a and b:
            notes.append(f"Référence : le rendement des 24 dernières heures à lui seul donne {_pct(a['spread'], 2)} à 24 h sur l'apprentissage (t = {_fr(a['t'])}) et {_pct(b['spread'], 2)} sur le test (t = {_fr(b['t'])}) : toute variable de flux doit faire mieux que cela pour valoir quelque chose.")
    amp = tg.get("AMP")
    aref = next((r for r in amp["rows"] if r["key"] == "a_ret24"), None) if amp else None
    if aref and aref["bestH"]:
        def best_t(r):
            m = (r["h"].get(str(r["bestH"])) or {}).get("is")
            return abs(m["t"]) if m else 0.0
        tref = best_t(aref)
        beat = [r["title"] for r in amp["rows"] if r["key"] != "a_ret24" and r["level"] == "informatif" and best_t(r) > tref]
        notes.append(f"Ampleur, référence : le mouvement des 24 dernières heures à lui seul prédit l'ampleur du suivant (t = {_fr(tref)} à l'apprentissage : la volatilité s'agglutine). "
                     + ("Font mieux que cette référence : " + " ; ".join(beat) + "." if beat else "Aucune variable de flux ou de levier ne fait mieux : elles ne disent rien de plus que la volatilité d'hier."))
    base = rep.get("baseline") or {}
    bo = base.get("oos")
    if bo:
        notes.append(f"Taux de base (toutes les heures du test) : {_pct(bo['up'], 0, False)} de hausses à 24 h, {_pct(bo['bigUp'], 0, False)} de gros mouvements haussiers (≥ 1,5 écart-type) et {_pct(bo['bigDn'], 0, False)} de gros mouvements baissiers.")
    if inf:
        text = f"{len(inf)} mesure(s) sur {n_tests} dépassent le seuil du hasard, apprises puis confirmées sur le test : " + " ; ".join(f"{r['title']} → {t['title'].lower()}" for t, r in inf) + "."
    else:
        text = f"Aucune des {n_tests} mesures ne dépasse le seuil du hasard à la fois à l'apprentissage et au test : les divergences de flux, de volume " + ("et les squeezes " if rep["hasOi"] else "") + "ne donnent pas, de façon prouvée, le sens ni l'ampleur du mouvement suivant."
    if hint:
        text += " À surveiller (indice sans preuve) : " + " ; ".join(f"{r['title']} → {t['title'].lower()}" for t, r in hint) + "."
    return {"text": text, "notes": notes, "informative": len(inf), "hints": len(hint)}


def _d(ms):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%d/%m/%Y")
