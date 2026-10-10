"""Mesure TPO sur l'historique (V19) : les repères du profil de marché tiennent-ils leurs promesses ? Module PUR (aucun accès réseau).

Sur chaque séance (1 jour : tranches de 30 min ; 4 heures et 1 heure : tranches de 5 min), avec exactement le moteur du terminal (engine/tpo.py)
et un pas de prix fixé SANS regarder le futur (médiane des amplitudes des 10 séances précédentes divisée par le nombre de lignes) :
  1. SINGLE PRINTS : sont-ils comblés (le prix retraverse toute la zone) plus souvent qu'une bande TÉMOIN de même largeur placée à la même distance
     de la clôture, de l'autre côté ? Comparaison appariée, erreur-type groupée par séance.
  2. POOR HIGH / POOR LOW : sont-ils dépassés (« réparés ») plus souvent que les extrêmes avec une QUEUE (excess), à distance égale de la clôture
     (comparaison stratifiée par distance) ?
  3. POC : sont-ils revisités plus souvent qu'un prix témoin à la même distance de la clôture ? Et les POC restés vierges la séance suivante ?
  4. PREMIÈRE HEURE (initial balance) : fréquence des cassures, des extensions à 1,5 et 2 fois sa hauteur, et sens de la séance après la
     première cassure.
  5. RÈGLE DES 80 % : après une ouverture hors de la valeur précédente et deux tranches clôturées dedans, l'autre bord est-il atteint dans la
     séance ? Témoin : même ouverture, simple retour dans la valeur (sans la condition des deux tranches).
  6. MIGRATION DE LA VALEUR, POSITION DE L'OUVERTURE, TYPE DE JOURNÉE et FORME : ce qui suit (sens de la séance suivante), face au taux de base.
Les résultats sont donnés pour toute la période et pour ses deux moitiés (stabilité). Plusieurs mesures étant faites, un écart isolé peut être
dû à la chance : seuls les écarts nets ET de même signe dans les deux moitiés méritent d'être retenus."""
import math
from bisect import bisect_left
from datetime import datetime, timezone

from . import tpo
from .sessionvp import nice_step

HORIZONS = {"D": (1, 3, 5, 10, 20), "4h": (1, 3, 6, 18, 42), "1h": (1, 4, 24, 72, 168)}
ROWS = {"D": 60, "4h": 36, "1h": 20}


def _day(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def build_sessions(bars, kind: str, start: int, end: int, rows: int | None = None, progress=None):
    """Profils de toutes les seances completes de [start, end) (bars : fine.Bars en 5 ou 15 min)."""
    spec = tpo.KINDS[kind]
    L, rows = spec["len"], rows or ROWS[kind]
    need = 0.9 * L / bars.step
    t = bars.t
    s = start // L * L
    out, ranges = [], []
    total = max(1, (end - s) // L)
    k = 0
    while s + L <= end:
        i0, i1 = bisect_left(t, s), bisect_left(t, s + L)
        k += 1
        if progress and k % 500 == 0:
            progress(k, total)
        if i1 - i0 < need:
            s += L
            continue
        cs = bars.candles(i0, i1)
        hi, lo = max(bars.h[i0:i1]), min(bars.l[i0:i1])
        last = sorted(ranges[-10:])
        typical = last[len(last) // 2] if last else hi - lo
        step = nice_step(max(typical, 1e-9) / rows)
        p = tpo.profile(cs, s, s + L, spec["bracket"], step, ib_ms=spec["ib"])
        ranges.append(hi - lo)
        if p is not None and p["high"] > p["low"]:
            out.append({"p": p, "start": s, "cs": cs, "typical": typical})
        s += L
    return out


def _future(ss, k, h):
    """(plus bas, plus haut) des seances k+1 .. k+h (None si l'historique s'arrete avant, ou s'il manque des seances)."""
    if k + h >= len(ss):
        return None
    L = ss[k]["p"]["end"] - ss[k]["p"]["start"]
    if ss[k + h]["start"] - ss[k]["start"] != h * L:          # trou dans les donnees : on ne compte pas
        return None
    lo = min(ss[j]["p"]["low"] for j in range(k + 1, k + h + 1))
    hi = max(ss[j]["p"]["high"] for j in range(k + 1, k + h + 1))
    return lo, hi


def paired(groups):
    """groups : par seance, liste de couples (repere 0/1, temoin 0/1). Taux, ecart et statistique t groupee par seance."""
    xs = [(x, y) for g in groups for x, y in g]
    n = len(xs)
    if n < 30:
        return {"n": n, "rate": None, "control": None, "diff": None, "t": None}
    rx, ry = sum(x for x, _ in xs) / n, sum(y for _, y in xs) / n
    d = rx - ry
    var = sum((sum(x - y for x, y in g) - d * len(g)) ** 2 for g in groups if g)
    se = math.sqrt(var) / n
    return {"n": n, "rate": rx, "control": ry, "diff": d, "t": d / se if se > 0 else None}


def _split(ss):
    mid = len(ss) // 2
    return [("all", 0, len(ss)), ("first", 0, mid), ("second", mid, len(ss))]


def measure_singles(ss, horizons):
    out = {}
    for name, a, b in _split(ss):
        res = {}
        for h in horizons:
            groups_fill, groups_touch = [], []
            for k in range(a, b):
                p = ss[k]["p"]
                f = _future(ss, k, h)
                if f is None or not p["singles"]:
                    continue
                lo, hi = f
                c = p["close"]
                gf, gt = [], []
                for z0, z1 in p["singles"]:
                    m0, m1 = 2 * c - z1, 2 * c - z0                 # bande temoin : meme largeur, meme distance, de l'autre cote
                    gf.append((int(lo <= z0 and hi >= z1), int(lo <= m0 and hi >= m1)))
                    gt.append((int(lo <= z1 and hi >= z0), int(lo <= m1 and hi >= m0)))
                groups_fill.append(gf)
                groups_touch.append(gt)
            res[str(h)] = {"fill": paired(groups_fill), "touch": paired(groups_touch)}
        out[name] = res
    return out


def _strat(rows, h):
    """rows : (groupe, distance relative, repare 0/1). Taux bruts et ecart stratifie poor - excess (a distance egale)."""
    bins = [0.0, 0.1, 0.25, 0.5, 0.75, 10.0]
    cell = {}
    for g, dist, ok in rows:
        bi = next(i for i in range(len(bins) - 1) if dist < bins[i + 1])
        c = cell.setdefault((g, bi), [0, 0])
        c[0] += ok
        c[1] += 1
    raw = {}
    for g in ("poor", "excess", "other"):
        n = sum(v[1] for (gg, _), v in cell.items() if gg == g)
        raw[g] = {"n": n, "rate": (sum(v[0] for (gg, _), v in cell.items() if gg == g) / n) if n else None}
    num = den = var = 0.0
    for bi in range(len(bins) - 1):
        p, e = cell.get(("poor", bi)), cell.get(("excess", bi))
        if not p or not e or p[1] < 10 or e[1] < 10:
            continue
        rp, re_ = p[0] / p[1], e[0] / e[1]
        w = p[1]
        num += w * (rp - re_)
        den += w
        var += w * w * (rp * (1 - rp) / p[1] + re_ * (1 - re_) / e[1])
    d = num / den if den else None
    se = math.sqrt(var) / den if den else None
    return {"raw": raw, "diff": d, "t": (d / se) if d is not None and se else None, "n": int(den)}


def measure_extremes(ss, horizons):
    out = {}
    for name, a, b in _split(ss):
        res = {}
        for h in horizons:
            rows = []
            for k in range(a, b):
                p = ss[k]["p"]
                f = _future(ss, k, h)
                if f is None:
                    continue
                lo, hi = f
                r = p["high"] - p["low"]
                c = p["close"]
                gh = "poor" if p["poorHigh"] else "excess" if p["tailHigh"] else "other"
                gl = "poor" if p["poorLow"] else "excess" if p["tailLow"] else "other"
                rows.append((gh, (p["high"] - c) / r, int(hi > p["high"])))
                rows.append((gl, (c - p["low"]) / r, int(lo < p["low"])))
            res[str(h)] = _strat(rows, h)
        out[name] = res
    return out


def measure_poc(ss, horizons):
    out = {}
    for name, a, b in _split(ss):
        res = {}
        for h in horizons:
            g_all, g_virgin = [], []
            for k in range(a, b):
                p = ss[k]["p"]
                f = _future(ss, k, h)
                if f is None:
                    continue
                lo, hi = f
                P, c = p["poc"], p["close"]
                M = 2 * c - P
                g_all.append([(int(lo <= P <= hi), int(lo <= M <= hi))])
                if h > 1:
                    f1 = _future(ss, k, 1)
                    if f1 and not (f1[0] <= P <= f1[1]) and not (f1[0] <= M <= f1[1]):
                        g_virgin.append([(int(lo <= P <= hi), int(lo <= M <= hi))])
            res[str(h)] = {"all": paired(g_all), "virgin": paired(g_virgin) if h > 1 else None}
        out[name] = res
    return out


def measure_ib(ss):
    """Premiere heure : frequence des cassures et des extensions ; puis, A PARTIR DU MOMENT de la premiere cassure (seule question utile pour
    trader : la cassure dit-elle quelque chose de la suite ?), part des seances qui cloturent au-dela du niveau casse (50 % = aucune information)
    et part qui reviennent jusqu'a l'autre bord de la premiere heure (echec)."""
    n = up = dn = both = none = 0
    ext15 = ext2 = broke_side = 0
    cont = {"up": [], "down": []}                              # 1 si cloture au-dela du niveau casse
    fail = {"up": 0, "down": 0}
    for x in ss:
        p = x["p"]
        st = p.get("ibStats")
        if not st or not st["complete"] or st["range"] <= 0:
            continue
        n += 1
        u, d = st["extUp"] > 0, st["extDn"] > 0
        both += u and d
        up += u and not d
        dn += d and not u
        none += not u and not d
        for e in (st["extUp"], st["extDn"]):
            if e > 0:
                broke_side += 1
                ext15 += e >= 0.5
                ext2 += e >= 1.0
        side, t_break = None, None
        for i, h, l, c in p["br"]:
            if i * p["bracketMs"] < p["ibMs"]:                  # tranches de la premiere heure elle-meme
                continue
            if h > st["high"] and l < st["low"]:
                break                                           # les deux cotes dans la meme tranche : ordre inconnu
            if h > st["high"] or l < st["low"]:
                side, t_break = ("up" if h > st["high"] else "down"), p["start"] + i * p["bracketMs"]
                break
        if side:
            lvl = st["high"] if side == "up" else st["low"]
            cont[side].append(int(p["close"] > lvl) if side == "up" else int(p["close"] < lvl))
            after = [k for k in x["cs"] if k.t >= t_break]
            fail[side] += any(k.l <= st["low"] for k in after) if side == "up" else any(k.h >= st["high"] for k in after)
    if not n:
        return None
    r = lambda a, b: a / b if b else None

    def side_stats(sd):
        v = cont[sd]
        m = sum(v) / len(v) if v else None
        return {"n": len(v), "closeBeyond": m, "t": (m - 0.5) / math.sqrt(0.25 / len(v)) if v else None, "failure": r(fail[sd], len(v))}
    return {"n": n, "none": none / n, "upOnly": up / n, "downOnly": dn / n, "both": both / n,
            "ext15": r(ext15, broke_side), "ext2": r(ext2, broke_side), "firstUp": side_stats("up"), "firstDown": side_stats("down")}


def measure_eighty(ss):
    setups = hits = 0
    base_n = base_hits = 0
    for k in range(1, len(ss)):
        cur, prev = ss[k]["p"], ss[k - 1]["p"]
        if ss[k]["start"] - ss[k - 1]["start"] != cur["end"] - cur["start"]:
            continue
        e = tpo.eighty(cur, prev, ss[k]["cs"], cur["step"])
        if not e:
            continue
        val, vah = prev["val"], prev["vah"]
        # temoin : premier retour dans la valeur (une tranche qui la touche), puis l'autre bord atteint ensuite dans la seance ?
        entry = None
        for i, h, l, c in cur["br"]:
            if l <= vah and h >= val:
                entry = cur["start"] + (i + 1) * cur["bracketMs"]
                break
        if entry is not None:
            after = [x for x in ss[k]["cs"] if x.t >= entry]
            target = vah if e["side"] == "up" else val
            base_n += 1
            base_hits += any(x.h >= target for x in after) if e["side"] == "up" else any(x.l <= target for x in after)
        if e["trigger"] is not None:
            setups += 1
            hits += bool(e["reached"])
    return {"n": setups, "rate": hits / setups if setups else None, "controlN": base_n, "control": base_hits / base_n if base_n else None}


def _next_dir(ss, groups_of):
    """Pour chaque groupe : part des seances SUIVANTES haussieres (cloture > ouverture) et rendement moyen, face a toutes les seances."""
    res, allr = {}, []
    for k in range(len(ss) - 1):
        nx = ss[k + 1]["p"]
        if ss[k + 1]["start"] - ss[k]["start"] != nx["end"] - nx["start"]:
            continue
        ret = (nx["close"] / nx["open"] - 1) * 100
        allr.append(ret)
        g = groups_of(k)
        if g:
            res.setdefault(g, []).append(ret)
    base = sum(1 for x in allr if x > 0) / len(allr) if allr else None
    out = {}
    for g, v in res.items():
        m = sum(v) / len(v)
        sd = math.sqrt(sum((x - m) ** 2 for x in v) / max(1, len(v) - 1))
        out[g] = {"n": len(v), "up": sum(1 for x in v if x > 0) / len(v), "mean": m, "t": m / (sd / math.sqrt(len(v))) if sd > 0 and len(v) > 1 else None}
    return {"base": base, "groups": out}


def run(bars, kind: str, start: int, end: int, progress=None) -> dict:
    ss = build_sessions(bars, kind, start, end, progress=progress)
    if len(ss) < 60:
        return {"kind": kind, "ready": False, "n": len(ss)}
    H = HORIZONS[kind]
    prevs = {}
    for k in range(1, len(ss)):
        if ss[k]["start"] - ss[k - 1]["start"] == ss[k]["p"]["end"] - ss[k]["p"]["start"]:
            prevs[k] = ss[k - 1]["p"]

    def va_group(k):
        return tpo.va_relation(ss[k]["p"], prevs[k])[0] if k in prevs else None

    def open_group(k):
        return tpo.open_location(ss[k]["p"], prevs[k])[0] if k in prevs else None

    def type_group(k):
        x = ss[k]
        last = sorted(y["p"]["high"] - y["p"]["low"] for y in ss[max(0, k - 10):k])
        dt = tpo.day_type(x["p"], last[len(last) // 2] if last else None)
        if not dt:
            return None
        up = x["p"]["close"] > x["p"]["open"]
        return f"{dt}_{'up' if up else 'down'}" if dt in ("trend", "normalvar") else dt

    def shape_group(k):
        return ss[k]["p"].get("shape")

    def same_session(groups_of):                             # meme seance : part haussiere (face a toutes les seances) et amplitude typique
        res, n_all, up_all = {}, 0, 0
        for k in range(len(ss)):
            g = groups_of(k)
            if not g:
                continue
            p = ss[k]["p"]
            n_all += 1
            up_all += p["close"] > p["open"]
            r = res.setdefault(g, [0, 0, 0.0])
            r[0] += 1
            r[1] += p["close"] > p["open"]
            r[2] += (p["high"] - p["low"]) / max(ss[k]["typical"], 1e-9)
        base = up_all / n_all if n_all else 0.5
        out = {g: {"n": v[0], "up": v[1] / v[0], "rangeX": v[2] / v[0],
                   "t": (v[1] / v[0] - base) / math.sqrt(base * (1 - base) / v[0]) if v[0] and 0 < base < 1 else None} for g, v in res.items()}
        return {"base": base, "groups": out}

    types = {}
    for k in range(len(ss)):
        g = type_group(k)
        if g:
            types[g] = types.get(g, 0) + 1
    tot = sum(types.values()) or 1
    return {"kind": kind, "ready": True, "n": len(ss), "from": _day(ss[0]["start"]), "to": _day(ss[-1]["p"]["end"] - 1), "rows": ROWS[kind],
            "horizons": list(H), "singles": measure_singles(ss, H), "extremes": measure_extremes(ss, H), "poc": measure_poc(ss, H),
            "ib": measure_ib(ss), "eighty": measure_eighty(ss) if kind == "D" else None,
            "migration": _next_dir(ss, va_group), "openNext": _next_dir(ss, open_group), "openSame": same_session(open_group),
            "dayTypes": {"freq": {g: v / tot for g, v in types.items()}, "next": _next_dir(ss, type_group)},
            "shapes": _next_dir(ss, shape_group)}


# ---------- synthese lisible (vue TPO, README) ----------
KIND_TXT = {"D": "séances d'1 jour", "4h": "séances de 4 heures", "1h": "séances d'1 heure"}


def _pct(x, d=0):
    return "—" if x is None else f"{x * 100:.{d}f}".replace(".", ",") + " %"


def _num(x, d=1):
    return "—" if x is None else f"{x:.{d}f}".replace(".", ",").replace("-", "−")


def _pts(x):
    return "—" if x is None else f"{x * 100:+.1f}".replace(".", ",").replace("-", "−") + " points"


def _verdict(all_t, first_d, second_d, all_d):
    """Net si |t| >= 2 sur toute la periode ET meme signe sur les deux moities ; faible si |t| >= 2 mais instable ; sinon hasard."""
    if all_t is None or all_d is None:
        return "insuffisant"
    stable = first_d is not None and second_d is not None and (first_d > 0) == (second_d > 0) == (all_d > 0)
    if abs(all_t) >= 2 and stable:
        return "net"
    if abs(all_t) >= 2:
        return "instable"
    return "hasard"


def summary(rep: dict) -> list:
    """Constats principaux, du plus solide au plus fragile : [{key, kind, verdict, text}]."""
    out = []
    for kind in ("D", "4h", "1h"):
        r = rep.get(kind)
        if not r or not r.get("ready"):
            continue
        H = [str(h) for h in r["horizons"]]
        hk, hm = H[0], H[2]                                       # seance suivante, et horizon moyen (5 jours, 6 x 4 h, 24 h)
        unit = {"D": ("la séance suivante", "5 séances"), "4h": ("la séance de 4 h suivante", "24 heures"), "1h": ("l'heure suivante", "24 heures")}[kind]
        ex = r["extremes"]
        e, e1, e2 = ex["all"][hk], ex["first"][hk], ex["second"][hk]
        v = _verdict(e["t"], e1["diff"], e2["diff"], e["diff"])
        out.append({"key": "poor", "kind": kind, "verdict": v,
                    "text": f"Poor high / poor low ({KIND_TXT[kind]}) : dépassés dès {unit[0]} {_pct(e['raw']['poor']['rate'])} du temps, contre "
                            f"{_pct(e['raw']['excess']['rate'])} pour un extrême avec queue (excess) ; à distance égale de la clôture, écart "
                            f"{_pts(e['diff'])} (statistique {_num(e['t'])}). " +
                            ("Effet net et stable : la queue marque un vrai rejet, le poor high / low une enchère inachevée qui attire un retour."
                             if v == "net" else "Effet non démontré.")})
        sg, s1, s2 = (r["singles"][p][hm]["fill"] for p in ("all", "first", "second"))
        v = _verdict(sg["t"], s1["diff"], s2["diff"], sg["diff"])
        if v == "net" and sg["diff"] is not None and sg["diff"] < 0:
            v = "contraire"                                       # mesure nette... dans le sens oppose a l'idee recue
        out.append({"key": "singles", "kind": kind, "verdict": v,
                    "text": f"Single prints ({KIND_TXT[kind]}) : comblés en {unit[1]} {_pct(sg['rate'])} du temps ; une bande témoin de même largeur à la "
                            f"même distance de la clôture l'est {_pct(sg['control'])} (écart {_pts(sg['diff'])}, statistique {_num(sg['t'])}). " +
                            ("Pas d'effet aimant : ils sont même un peu MOINS souvent comblés (le prix a quitté vite ces prix, il n'y revient pas plus qu'ailleurs)."
                             if sg["diff"] is not None and sg["diff"] < 0 and v in ("contraire", "instable") else
                             "Aucune différence démontrée avec le hasard." if v == "hasard" else "Effet aimant mesuré.")})
        pc, p1, p2 = (r["poc"][p][hk]["all"] for p in ("all", "first", "second"))
        v = _verdict(pc["t"], p1["diff"], p2["diff"], pc["diff"])
        pv = r["poc"]["all"][H[1]]["virgin"]
        out.append({"key": "poc", "kind": kind, "verdict": v,
                    "text": f"POC ({KIND_TXT[kind]}) : retraversé dès {unit[0]} {_pct(pc['rate'])} du temps, contre {_pct(pc['control'])} pour un prix témoin "
                            f"à la même distance (écart {_pts(pc['diff'])}, statistique {_num(pc['t'])})"
                            + (f" ; POC resté vierge une séance : revisité ensuite {_pct(pv['rate'])} contre {_pct(pv['control'])}" if pv and pv.get("rate") is not None else "")
                            + (". Léger effet aimant, net et stable." if v == "net" else ". Effet faible ou instable." if v == "instable" else ". Pas d'effet démontré.")})
        ib = r.get("ib")
        if ib:
            fu, fd = ib["firstUp"], ib["firstDown"]
            out.append({"key": "ib", "kind": kind, "verdict": "description",
                        "text": f"Première heure ({KIND_TXT[kind]}) : cassée des deux côtés {_pct(ib['both'])} du temps, d'un seul côté {_pct(ib['upOnly'] + ib['downOnly'])} ; "
                                f"après une cassure, l'extension à 1,5 fois sa hauteur est atteinte {_pct(ib['ext15'])} du temps, à 2 fois {_pct(ib['ext2'])}. "
                                f"Depuis le moment de la première cassure, la séance clôture au-delà du niveau cassé {_pct(fu['closeBeyond'])} (vers le haut) et "
                                f"{_pct(fd['closeBeyond'])} (vers le bas) : la cassure ne dit presque rien de la suite."})
        e8 = r.get("eighty")
        if e8 and e8.get("rate") is not None:
            out.append({"key": "eighty", "kind": kind, "verdict": "description",
                        "text": f"Règle des « 80 % » ({KIND_TXT[kind]}) : après une ouverture hors de la valeur de la veille et deux tranches de 30 min clôturées dedans, "
                                f"l'autre bord est atteint dans la journée {_pct(e8['rate'])} du temps (sur {e8['n']} cas), contre {_pct(e8['control'])} après un simple "
                                f"retour dans la valeur. Bien loin de 80 %."})
        osm = r.get("openSame") or {}
        g = osm.get("groups") or {}
        if g.get("belowValue") and g.get("aboveValue"):
            b, a_ = g["belowValue"], g["aboveValue"]
            vv = "net" if (b.get("t") or 0) >= 2 and (a_.get("t") or 0) <= -2 else "faible"
            out.append({"key": "open", "kind": kind, "verdict": vv,
                        "text": f"Ouverture ({KIND_TXT[kind]}) : sous la valeur précédente, la séance finit en hausse {_pct(b['up'])} du temps ; au-dessus, {_pct(a_['up'])} ; "
                                f"en moyenne {_pct(osm['base'])}. Le prix a tendance à revenir vers la valeur précédente, et ces séances sont plus larges "
                                f"(×{_num(b['rangeX'], 2)} l'amplitude habituelle)."})
    order = {"net": 0, "contraire": 1, "instable": 2, "faible": 3, "description": 4, "hasard": 5, "insuffisant": 6}
    return sorted(out, key=lambda x: (order.get(x["verdict"], 9), ["D", "4h", "1h"].index(x["kind"])))


def compact(rep: dict, kind: str):
    """Ce que la vue TPO affiche pour un type de seance : taux mesures a cote des marques et constats."""
    r = (rep or {}).get(kind)
    if not r or not r.get("ready"):
        return None
    H = [str(h) for h in r["horizons"]]
    hk, hm = H[0], H[2]
    sg, e, pc = r["singles"]["all"][hm]["fill"], r["extremes"]["all"][hk], r["poc"]["all"][hk]["all"]
    return {"symbol": rep.get("symbol"), "source": rep.get("source"), "from": r["from"], "to": r["to"], "n": r["n"], "horizons": r["horizons"],
            "singles": {"rate": sg["rate"], "control": sg["control"], "t": sg["t"], "h": int(hm)},
            "poor": {"rate": e["raw"]["poor"]["rate"], "excess": e["raw"]["excess"]["rate"], "diff": e["diff"], "t": e["t"], "h": int(hk)},
            "poc": {"rate": pc["rate"], "control": pc["control"], "t": pc["t"], "h": int(hk),
                    "virgin": r["poc"]["all"][H[1]]["virgin"], "virginH": int(H[1])},
            "ib": r.get("ib"), "eighty": r.get("eighty"), "openSame": r.get("openSame"), "dayTypes": (r.get("dayTypes") or {}).get("freq"),
            "summary": [x for x in rep.get("summary", []) if x["kind"] == kind]}
