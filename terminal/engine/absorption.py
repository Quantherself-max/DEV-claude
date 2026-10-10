"""Absorptions (V21) : beaucoup d'ordres AGRESSIFS d'un cote, et pourtant le prix ne va pas dans leur sens. En face, des ordres passifs
(souvent caches et reapprovisionnes au fur et a mesure) ont tout « absorbe ».

DETECTION sur les bougies. Delta = volume acheteur agressif - volume vendeur agressif, VRAI chez Binance (jamais estime ici) :
  - absorption ACHETEUSE (les vendeurs sont absorbes : signal haussier) : delta tres negatif, au moins Z_MIN ecarts-types de la normale
    des N_NORM bougies precedentes, sur une bougie qui finit pourtant en HAUSSE (cloture au-dessus de l'ouverture) ;
  - absorption VENDEUSE (les acheteurs sont absorbes : signal baissier) : delta tres positif sur une bougie qui finit en BAISSE ;
  - « au plus bas » (« au plus haut ») : la bougie fait le plus bas (plus haut) des EXT bougies precedentes : les vendeurs (acheteurs)
    ont pousse jusqu'a un nouvel extreme et y ont ete absorbes.
Echelle du delta : racine de la moyenne des carres des deltas des N_NORM bougies precedentes (rien du futur).

MESURE (study) : apres chaque absorption, sur les H bougies suivantes,
  - le prix va-t-il dans le sens de l'absorption (hausse apres une absorption acheteuse) ?
  - le plus bas (plus haut) de la bougie d'absorption tient-il ?
face a des bougies SEMBLABLES (meme sens, corps a +/- 30 % en ATR, volume relatif a +/- 30 %) dont le delta est ORDINAIRE (a moins
d'1 ecart-type de zero) : meme mouvement du prix, flux normal. On isole ainsi ce qu'ajoute le delta. Les NCONT plus proches dans le temps.
Moities de la periode pour la stabilite, comme les autres mesures du terminal. Module PUR."""
import math
from collections import deque

VERSION = 1
N_NORM = 96            # bougies precedentes pour l'echelle du delta et le volume habituel
Z_MIN = 2.0            # delta d'au moins 2 ecarts-types contre le sens de la bougie
EXT = 12               # « au plus bas / au plus haut » des 12 bougies precedentes
HORIZONS = (1, 4, 12, 24, 72)
PRIMARY = 4            # horizon de reference des verdicts : les 4 bougies suivantes (fixe avant toute mesure)
NCONT = 20
WIN = 600              # ecart maximal (en bougies) pour chercher des bougies semblables
SIDE_TXT = {"bull": "acheteuse", "bear": "vendeuse"}


def arrays(src):
    """(t, o, h, l, c, v, d) depuis une liste de Candle (delta = 2 x volume acheteur agressif - volume) ou un fine.Bars (colonne d)."""
    if hasattr(src, "step") and hasattr(src, "d"):
        return list(src.t), list(src.o), list(src.h), list(src.l), list(src.c), list(src.v), list(src.d)
    t, o, h, l, c, v, d = [], [], [], [], [], [], []
    for k in src:
        t.append(k.t); o.append(k.o); h.append(k.h); l.append(k.l); c.append(k.c); v.append(k.v); d.append(2.0 * k.tb - k.v)
    return t, o, h, l, c, v, d


def has_real_delta(candles) -> bool:
    """Au moins 80 % des bougies recentes portent un volume acheteur agressif : donnee reelle de la bourse (sinon pas d'absorption)."""
    xs = [k for k in candles[-300:] if k.v > 0]
    return bool(xs) and sum(1 for k in xs if k.tb > 0) >= 0.8 * len(xs)


def features(t, o, h, l, c, v, d, n: int = N_NORM, ext: int = EXT):
    """Par bougie i (les n premieres exclues) : z (delta en ecarts-types), vr (volume / volume moyen), body (corps en ATR), atr,
    lowExt / highExt (plus bas / plus haut des ext bougies precedentes). None ou False quand l'historique ne suffit pas."""
    N = len(c)
    z, vr, body, atr = [None] * N, [None] * N, [None] * N, [None] * N
    lo_ext, hi_ext = [False] * N, [False] * N
    s2 = sv = 0.0
    a = None
    for i in range(N):
        if i >= n and a:
            if i % 2000 == 0:                                   # recalcul exact de temps en temps (erreurs d'arrondi des sommes glissantes)
                s2 = sum(x * x for x in d[i - n:i])
                sv = sum(v[i - n:i])
            rms, mv = math.sqrt(max(s2, 0.0) / n), sv / n
            if rms > 0 and mv > 0:
                z[i], vr[i], body[i], atr[i] = d[i] / rms, v[i] / mv, (c[i] - o[i]) / a, a
                lo_ext[i] = l[i] <= min(l[max(0, i - ext):i])
                hi_ext[i] = h[i] >= max(h[max(0, i - ext):i])
        tr = h[i] - l[i] if i == 0 else max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        a = tr if a is None else (a * 13 + tr) / 14
        s2 += d[i] * d[i]
        sv += v[i]
        if i >= n:
            s2 -= d[i - n] * d[i - n]
            sv -= v[i - n]
    return z, vr, body, atr, lo_ext, hi_ext


def side_of(zi, oi, ci, z_min: float = Z_MIN):
    if zi is None:
        return None
    if zi <= -z_min and ci > oi:
        return "bull"
    if zi >= z_min and ci < oi:
        return "bear"
    return None


def detect(src, last: int | None = None, n: int = N_NORM, z_min: float = Z_MIN, ext: int = EXT) -> list:
    """Absorptions des bougies donnees (toutes FERMEES : l'appelant retire la bougie en cours), au plus sur les `last` dernieres.
    [{t, side, price (plus bas pour acheteuse, plus haut pour vendeuse), delta, volume, z, vr, body, clv, extreme, grade}]"""
    t, o, h, l, c, v, d = arrays(src)
    z, vr, body, atr, lo_ext, hi_ext = features(t, o, h, l, c, v, d, n, ext)
    out = []
    for i in range(max(n, len(c) - last if last else 0), len(c)):
        side = side_of(z[i], o[i], c[i], z_min)
        if not side:
            continue
        rng = h[i] - l[i]
        ex = lo_ext[i] if side == "bull" else hi_ext[i]
        out.append({"t": int(t[i]), "side": side, "price": l[i] if side == "bull" else h[i], "open": o[i], "close": c[i], "high": h[i], "low": l[i],
                    "delta": d[i], "volume": v[i], "z": round(z[i], 2), "vr": round(vr[i], 2), "body": round(body[i], 3),
                    "clv": round((2 * c[i] - h[i] - l[i]) / rng, 3) if rng > 0 else 0.0, "extreme": bool(ex),
                    "grade": 1 + (abs(z[i]) >= 1.5 * z_min) + bool(ex)})
    return out


# ---------- mesure ----------
def _paired(groups):
    """groups : par evenement, liste de couples (resultat 0/1 ou reel, moyenne des temoins). Taux, ecart et statistique t."""
    xs = [(x, y) for g in groups for x, y in g]
    n = len(xs)
    if n < 30:
        return {"n": n, "rate": None, "control": None, "diff": None, "t": None}
    rx, ry = sum(x for x, _ in xs) / n, sum(y for _, y in xs) / n
    dd = rx - ry
    var = sum((sum(x - y for x, y in g) - dd * len(g)) ** 2 for g in groups if g)
    se = math.sqrt(var) / n
    return {"n": n, "rate": rx, "control": ry, "diff": dd, "t": dd / se if se > 0 else None}


def _future_extremes(h, l, horizons):
    """{h: (plus bas, plus haut) des bougies i+1 .. i+h} (None au-dela de la fin)."""
    N = len(h)
    out = {}
    for hz in horizons:
        lo, hi = [None] * N, [None] * N
        qa, qb = deque(), deque()
        for j in range(N):                                     # fenetre [j - hz + 1, j] = bougies i+1 .. i+hz pour i = j - hz
            while qa and l[qa[-1]] >= l[j]:
                qa.pop()
            qa.append(j)
            while qb and h[qb[-1]] <= h[j]:
                qb.pop()
            qb.append(j)
            if qa[0] <= j - hz:
                qa.popleft()
            if qb[0] <= j - hz:
                qb.popleft()
            i = j - hz
            if i >= 0:
                lo[i], hi[i] = l[qa[0]], h[qb[0]]
        out[hz] = (lo, hi)
    return out


def _verdict(r, r1, r2):
    """Net : |t| >= 2 sur toute la periode ET meme signe sur les deux moities ; contraire : net mais dans l'autre sens ; instable : |t| >= 2
    sans confirmation ; hasard ; insuffisant."""
    t, dd = r.get("t"), r.get("diff")
    if t is None or dd is None:
        return "insuffisant"
    d1, d2 = r1.get("diff"), r2.get("diff")
    stable = d1 is not None and d2 is not None and (d1 > 0) == (d2 > 0) == (dd > 0)
    if abs(t) >= 2 and stable:
        return "net" if dd > 0 else "contraire"
    return "instable" if abs(t) >= 2 else "hasard"


def study(src, horizons=HORIZONS, primary: int = PRIMARY, n: int = N_NORM, z_min: float = Z_MIN, ext: int = EXT,
          ncont: int = NCONT, win: int = WIN) -> dict:
    """Mesure des absorptions sur des bougies au VRAI delta (fermees, continues). Voir l'en-tete du module."""
    t, o, h, l, c, v, d = arrays(src)
    N = len(c)
    if N < n + 300:
        return {"ready": False, "bars": N}
    z, vr, body, atr, lo_ext, hi_ext = features(t, o, h, l, c, v, d, n, ext)
    H = sorted(set(list(horizons) + [primary]))
    fut = _future_extremes(h, l, H)
    half = (n + N) // 2

    def outcome(k, hz, sgn):
        if k + hz >= N:
            return None
        lo, hi = fut[hz][0][k], fut[hz][1][k]
        up = int((c[k + hz] - c[k]) * sgn > 0)
        hold = int(lo > l[k]) if sgn > 0 else int(hi < h[k])
        return up, hold, (c[k + hz] / c[k] - 1.0) * 100.0 * sgn

    def controls(i):
        out, bi, vi = [], body[i], vr[i]
        if not bi or not vi:
            return out
        for dj in range(1, win + 1):
            if i - dj < n and i + dj >= N - 1:
                break
            for j in (i - dj, i + dj):
                if n <= j < N - 1 and z[j] is not None and abs(z[j]) < 1.0 and body[j] and (body[j] > 0) == (bi > 0) \
                        and abs(body[j] / bi - 1) <= 0.3 and abs(vr[j] / vi - 1) <= 0.3:
                    out.append(j)
                    if len(out) >= ncont:
                        return out
        return out

    res = {}
    for side, sgn in (("bull", 1), ("bear", -1)):
        evs = [i for i in range(n, N - 1) if side_of(z[i], o[i], c[i], z_min) == side]
        recs = []                                              # (i, extreme, {h: (resultat, moyenne temoins) x 3})
        for i in evs:
            ctl = controls(i)
            if len(ctl) < 3:
                continue
            per = {}
            for hz in H:
                x = outcome(i, hz, sgn)
                ys = [y for y in (outcome(j, hz, sgn) for j in ctl) if y is not None]
                if x is None or not ys:
                    continue
                per[hz] = tuple((x[q], sum(y[q] for y in ys) / len(ys)) for q in range(3))
            recs.append((i, lo_ext[i] if sgn > 0 else hi_ext[i], per))

        def agg(sel, hz):
            g = [r[2][hz] for r in sel if hz in r[2]]
            ret = [x[2] for x in g]
            n_ = len(ret)
            dif = [x - y for x, y in ret]
            ok = n_ >= 30                                       # comme les taux : rien sous 30 cas
            md = sum(dif) / n_ if ok else None
            sd = math.sqrt(sum((q - md) ** 2 for q in dif) / (n_ - 1)) if ok else None
            return {"up": _paired([[x[0]] for x in g]), "hold": _paired([[x[1]] for x in g]),
                    "ret": {"n": n_, "mean": sum(x for x, _ in ret) / n_ if ok else None, "control": sum(y for _, y in ret) / n_ if ok else None,
                            "diff": md, "t": md / (sd / math.sqrt(n_)) if sd else None}}
        hs = {str(hz): agg(recs, hz) for hz in H}
        first = agg([r for r in recs if r[0] < half], primary)
        second = agg([r for r in recs if r[0] >= half], primary)
        extreme = agg([r for r in recs if r[1]], primary)
        p = hs[str(primary)]
        res[side] = {"n": len(evs), "matched": len(recs), "extreme": sum(1 for r in recs if r[1]), "per1000": round(1000 * len(evs) / max(1, N - n), 2),
                     "h": hs, "first": first, "second": second, "extremeOnly": extreme,
                     "verdict": {"up": _verdict(p["up"], first["up"], second["up"]), "hold": _verdict(p["hold"], first["hold"], second["hold"])}}
    base = {}
    for hz in H:                                              # taux de hausse de toutes les bougies (reference)
        ups = [int(c[k + hz] > c[k]) for k in range(n, N - hz)]
        base[str(hz)] = sum(ups) / len(ups) if ups else None
    step = int(t[1] - t[0]) if N > 1 else 0
    return {"ready": True, "bars": N, "from": int(t[n]), "to": int(t[-1]), "step": step, "zMin": z_min, "norm": n, "ext": ext,
            "horizons": H, "primary": primary, "bull": res["bull"], "bear": res["bear"], "base": base}


# ---------- textes ----------
def _pct(x):
    return "—" if x is None else f"{x * 100:.0f} %"


def _pts(x):
    return "—" if x is None else f"{x * 100:+.1f}".replace(".", ",").replace("-", "−") + " points"


def _num(x, dgt=1):
    return "—" if x is None else f"{x:.{dgt}f}".replace(".", ",").replace("-", "−")


def unit_label(step_ms: int) -> str:
    return {300_000: "5 minutes", 900_000: "15 minutes", 3_600_000: "1 heure", 14_400_000: "4 heures", 86_400_000: "1 jour"}.get(step_ms, "bougies")


VERDICT_TXT = {"net": "effet net et stable", "contraire": "effet CONTRAIRE, net et stable", "instable": "écart non confirmé sur les deux moitiés",
               "hasard": "pas d'écart démontré", "insuffisant": "trop peu de cas"}


def summary(st: dict, label: str = "") -> list:
    """Constats lisibles : [{side, verdict, text}] (verdict du sens pris sur l'horizon de reference)."""
    if not st or not st.get("ready"):
        return []
    out = []
    u = unit_label(st.get("step") or 0)
    hz = str(st["primary"])
    for side in ("bull", "bear"):
        s = st[side]
        p = s["h"][hz]
        up, hold = p["up"], p["hold"]
        mv = "monte" if side == "bull" else "baisse"
        ext = "plus bas" if side == "bull" else "plus haut"
        txt = (f"Absorption {SIDE_TXT[side]} ({label + ', ' if label else ''}bougies de {u}, {s['n']} cas) : dans les {st['primary']} bougies suivantes, le prix "
               f"{mv} {_pct(up['rate'])} du temps, contre {_pct(up['control'])} après une bougie semblable au flux ordinaire (écart {_pts(up['diff'])}, "
               f"statistique {_num(up['t'])}) : {VERDICT_TXT[s['verdict']['up']]}. Le {ext} de la bougie tient {_pct(hold['rate'])} du temps, contre "
               f"{_pct(hold['control'])} : {VERDICT_TXT[s['verdict']['hold']]}.")
        out.append({"side": side, "verdict": s["verdict"]["up"], "holdVerdict": s["verdict"]["hold"], "text": txt})
    return out


def compact(st: dict):
    """Ce que le graphique et la Lecture affichent : par cote, taux a l'horizon de reference et verdicts."""
    if not st or not st.get("ready"):
        return None
    hz = str(st["primary"])
    out = {"step": st["step"], "unit": unit_label(st["step"]), "from": st["from"], "to": st["to"], "bars": st["bars"], "primary": st["primary"]}
    for side in ("bull", "bear"):
        s = st[side]
        p = s["h"][hz]
        out[side] = {"n": s["n"], "up": p["up"]["rate"], "upCtl": p["up"]["control"], "hold": p["hold"]["rate"], "holdCtl": p["hold"]["control"],
                     "verdict": s["verdict"]["up"], "holdVerdict": s["verdict"]["hold"]}
    return out


def _day(ms):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


TF_ORDER = ("5m", "15m", "1h", "4h", "1d")


def report(label: str, tfs: dict, source: str, origin: str, computed_at: int, seconds: float | None = None) -> dict:
    """Rapport « absorption » (page Backtest) : une mesure par unite de temps. origin : « terminal » (calcule en tache de fond sur
    l'historique 1 h du terminal) ou « outil » (tools/run_absorption_study.py sur l'historique 1 minute de Binance Vision)."""
    ok = {tf: st for tf, st in tfs.items() if st and st.get("ready")}
    sums = []
    for tf in sorted(ok, key=lambda x: TF_ORDER.index(x) if x in TF_ORDER else 9):
        sums += [{**x, "tf": tf} for x in summary(ok[tf], label)]
    order = {"net": 0, "contraire": 1, "instable": 2, "hasard": 3, "insuffisant": 4}
    sums.sort(key=lambda x: (order.get(x["verdict"], 9), TF_ORDER.index(x["tf"]) if x["tf"] in TF_ORDER else 9))
    first = sums[0]["text"] if sums else "pas assez d'historique au vrai delta."
    f0 = min((st["from"] for st in ok.values()), default=None)
    f1 = max((st["to"] for st in ok.values()), default=None)
    return {"symbol": label, "kind": "absorption", "label": label, "version": VERSION, "origin": origin, "source": source,
            "computedAt": computed_at, "seconds": seconds, "period": {"from": f0, "to": f1, "text": f"{_day(f0)} → {_day(f1)}" if f0 else "—"},
            "verdict": {"text": "Absorptions (delta fort contre le sens de la bougie). " + first}, "tfs": tfs, "summary": sums}
