"""Indicateurs sous le graphique (V30) : l'INTÉRÊT OUVERT en bougies (ouverture, plus haut, plus bas, clôture de chaque bougie du
graphique, à partir des relevés toutes les 5 minutes de Binance) et le DELTA de chaque bougie (volume acheteur agressif moins volume
vendeur agressif) avec son cumul, le CVD. Module PUR.
V37 : calculs plus précis et lecture croisée : intérêt ouvert À L'INSTANT pour la bougie en cours, delta EXACT en dollars (volume acheteur
agressif en dollars de Binance), CVD du SPOT à côté de celui du perpétuel, funding pondéré par la durée réellement couverte dans chaque bougie
(et la vraie durée de la période en cours), funding cumulé, et pour chaque bougie QUI OUVRE ou QUI FERME ses positions (prix x intérêt
ouvert x delta), avec le funding en confirmation."""
from __future__ import annotations
from bisect import bisect_left, bisect_right


def oi_candles(times, step_ms: int, pt_t: list, pt_v: list) -> list:
    """times : ouverture de chaque bougie (ms) ; pt_t / pt_v : relevés de l'intérêt ouvert (heure du relevé, valeur), triés.
    Rend [ouverture, plus haut, plus bas, clôture] par bougie (None sans relevé). L'ouverture est le dernier relevé d'avant la bougie
    (comme un graphique en bougies : chaque bougie part de la clôture de la précédente)."""
    out = []
    for j, t in enumerate(times):                          # V36 : une bougie finit à l'ouverture de la suivante (mois de 28 à 31 jours)
        end = min(t + step_ms, times[j + 1]) if j + 1 < len(times) else t + step_ms
        i0, i1 = bisect_right(pt_t, t), bisect_right(pt_t, end)
        if i1 <= i0:                                       # pas encore de relevé dans la bougie (bougie en cours) : la dernière valeur
            p = pt_v[i0 - 1] if i0 > 0 and t - pt_t[i0 - 1] <= 3 * max(step_ms, 300_000) else None
            out.append([p, p, p, p] if p is not None else None)
            continue
        vs = pt_v[i0:i1]
        o = pt_v[i0 - 1] if i0 > 0 and t - pt_t[i0 - 1] <= 3 * max(step_ms, 300_000) else vs[0]
        out.append([o, max(o, max(vs)), min(o, min(vs)), vs[-1]])
    return out


def deltas(candles) -> tuple:
    """(delta par bougie, CVD) ; None là où le volume acheteur agressif est inconnu (le CVD reprend la dernière valeur connue)."""
    d, cvd, run = [], [], 0.0
    for k in candles:
        if k.tb > 0 and k.v > 0:
            x = 2 * k.tb - k.v
            run += x
            d.append(x)
        else:
            d.append(None)
        cvd.append(run)
    return d, cvd


def deltas_usd(candles) -> tuple:
    """V37 : delta de chaque bougie EN DOLLARS. Exact quand Binance donne le volume acheteur agressif en dollars (2 x acheteurs - volume,
    en dollars) ; sinon delta en coin x prix moyen exact de la bougie (volume en dollars / volume). Rend (deltas, part exacte 0..1)."""
    out, exact, known = [], 0, 0
    for k in candles:
        if k.bq > 0 and k.q > 0:
            out.append(2 * k.bq - k.q)
            exact += 1
            known += 1
        elif k.tb > 0 and k.v > 0:
            out.append((2 * k.tb - k.v) * (k.q / k.v if k.q > 0 else k.c))
            known += 1
        else:
            out.append(None)
    return out, (exact / known if known else 0.0)


def align_spot(times, spot) -> tuple:
    """V37 : delta du SPOT (coin, dollars) aligné sur les bougies du graphique (même heure d'ouverture) ; None sans bougie spot."""
    by = {k.t: k for k in spot}
    dc, du = deltas([by[t] for t in times if t in by]), deltas_usd([by[t] for t in times if t in by])
    it_c, it_u = iter(dc[0]), iter(du[0])
    a, b = [], []
    for t in times:
        if t in by:
            a.append(next(it_c))
            b.append(next(it_u))
        else:
            a.append(None)
            b.append(None)
    return a, b


def merge_points(live: dict, archive: dict, now_pt=None, now_ms=None) -> tuple:
    """Relevés de l'adresse Binance (clé : ouverture de la bougie 5 min, valeur à sa fin) et des archives (clé : heure du relevé) ->
    (heures, valeurs) triées ; l'adresse passe devant les archives. V37 : now_pt = (heure, OI) à l'instant, ajouté après le dernier relevé
    s'il est plus récent (et date de moins de 15 minutes) : la bougie en cours n'attend plus le relevé 5 min, publié avec du retard."""
    pts = dict(archive)
    for k, v in live.items():
        pts[k + 300_000] = v
    ts = sorted(pts)
    vs = [pts[t] for t in ts]
    if now_pt and now_pt[1] and (not ts or now_pt[0] > ts[-1]) and (now_ms is None or now_ms - now_pt[0] <= 900_000):
        ts.append(int(now_pt[0]))
        vs.append(float(now_pt[1]))
    return ts, vs


# ---------- V37 : qui ouvre, qui ferme (prix x intérêt ouvert x delta) ----------
POS_NAMES = {0: "intérêt ouvert stable", 1: "acheteurs qui ouvrent", 2: "vendeurs qui ouvrent", 3: "vendeurs qui rachètent", 4: "acheteurs qui sortent"}


def positions(candles, oi, delta, window: int = 24) -> dict:
    """Pour chaque bougie : 1 = le prix monte et l'intérêt ouvert monte (acheteurs à levier qui OUVRENT), 2 = le prix baisse et l'OI monte
    (vendeurs qui ouvrent), 3 = le prix monte et l'OI baisse (vendeurs qui RACHÈTENT, rachats forcés compris), 4 = le prix baisse et l'OI
    baisse (acheteurs qui SORTENT, liquidations comprises), 0 = OI quasi stable (moins du quart de la variation habituelle du graphique).
    Le sens vient du prix, ou du delta quand le corps de la bougie est minuscule (moins de 10 % de son amplitude). « conf » : le delta va
    dans le même sens (achats agressifs pour 1 et 3, ventes pour 2 et 4) ; sinon des ordres passifs ont fait le mouvement (absorption).
    Résumé sur les `window` dernières bougies : OI ajouté ou retiré par chaque camp, en coin."""
    doi = [(c[3] - c[0]) if c and c[0] is not None else None for c in oi]
    mags = sorted(abs(x) for x in doi if x)
    thr = 0.25 * mags[len(mags) // 2] if mags else 0.0
    codes, conf = [], []
    for k, x, d in zip(candles, doi, delta):
        if x is None:
            codes.append(None)
            conf.append(None)
            continue
        mv, rng = k.c - k.o, k.h - k.l
        up = mv > 0 if (mv and abs(mv) >= 0.1 * rng) or not d else d > 0
        code = 0 if abs(x) <= thr else (1 if up else 2) if x > 0 else (3 if up else 4)
        codes.append(code)
        conf.append(None if d is None or code == 0 else (d > 0) == up)
    n = len(codes)
    last = [(codes[i], doi[i]) for i in range(max(0, n - window), n) if codes[i] is not None]
    sums = {c: sum(x for cc, x in last if cc == c) for c in (1, 2, 3, 4)}
    dom = max((1, 2, 3, 4), key=lambda c: abs(sums[c])) if last and any(sums.values()) else None
    first = next((c for c in oi[max(0, n - window):] if c), None)
    lastc = next((c for c in reversed(oi) if c), None)
    return {"pos": codes, "posConf": conf, "posThr": thr,
            "posSum": {"bars": len(last), "longsOpen": sums[1], "shortsOpen": sums[2], "shortsClose": sums[3], "longsClose": sums[4],
                       "dominant": dom, "oiChg": (lastc[3] / first[0] - 1.0) if first and lastc and first[0] else None}}


def crowding(pos_sum: dict, fund8h) -> str | None:
    """V37 : le funding en confirmation de la lecture des positions (fund8h en % par 8 h)."""
    if not pos_sum or fund8h is None:
        return None
    dom = pos_sum.get("dominant")
    if dom == 2 and fund8h < 0:
        return "vendeurs à levier entassés et qui paient : un rachat forcé (squeeze haussier) est possible"
    if dom == 1 and fund8h >= 0.03:
        return "acheteurs à levier entassés et qui paient cher : une purge (squeeze baissier) est possible"
    if dom == 3:
        return "le mouvement vient de rachats de vendeurs plus que de nouveaux acheteurs : souvent moins durable"
    if dom == 4:
        return "le mouvement vient d'acheteurs qui sortent (ou sont liquidés) plus que de nouveaux vendeurs"
    if dom == 1 and fund8h < 0:
        return "de nouveaux acheteurs alors que le funding reste négatif : le marché n'est pas encore surchargé à l'achat"
    if dom == 2 and fund8h >= 0.03:
        return "de nouveaux vendeurs alors que les acheteurs paient cher : pression vendeuse sur des acheteurs entassés"
    return None


FUND_SNAP_MS = 60_000                                      # un versement arrive quelques millisecondes après l'heure ronde : arrondi à la minute
H_MS = 3_600_000


def _hours(gap_ms: float) -> float:
    return min(8.0, max(1.0, round(gap_ms / H_MS)))


def _periods(rows, now_rate=None, next_ms=None) -> list:
    """V37 : versements [(heure, taux de la période)] -> périodes [(début, fin, taux ramené à 8 h, taux brut, estimée)].
    Chaque versement clôt sa période ; la durée vient de l'écart avec le versement d'avant (Binance passe parfois de 8 h à 4 h ou 1 h).
    La période en cours (estimation) va du dernier versement au PROCHAIN versement annoncé par Binance : sa vraie durée."""
    ts = [round(t / FUND_SNAP_MS) * FUND_SNAP_MS for t, _ in rows]
    out = []
    for i, (t, r) in enumerate(zip(ts, [r for _, r in rows])):
        h = _hours(t - ts[i - 1]) if i else (_hours(ts[1] - t) if len(ts) > 1 else 8.0)
        out.append((t - h * H_MS, t, r * 8.0 / h, r, False))
    if now_rate is not None and ts:
        last = ts[-1]
        nxt = round(next_ms / FUND_SNAP_MS) * FUND_SNAP_MS if next_ms and next_ms > last else None
        h = _hours(nxt - last) if nxt else (out[-1][1] - out[-1][0]) / H_MS
        out.append((last, last + h * H_MS, now_rate * 8.0 / h, now_rate, True))
    return out


def funding_bars(times, step_ms: int, rows, now_rate=None, now_ms=None, next_ms=None) -> dict:
    """V35 : le FUNDING (financement payé entre acheteurs et vendeurs à levier) pour chaque bougie du graphique, en % par 8 heures.
    rows : versements [(heure du versement ms, taux de la période)] ; now_rate : estimation du taux de la période en cours ; next_ms : heure
    du prochain versement. V37 : chaque bougie prend la moyenne des taux PONDÉRÉE PAR LA DURÉE de chaque période qu'elle couvre (une bougie
    plus courte que la période : le taux de sa période ; plus longue : chaque période compte pour le temps qu'elle couvre, même quand
    Binance passe à 4 h ou 1 h). « fundCum » : funding cumulé réellement versé depuis le début du graphique (% du montant de la position :
    ce qu'un acheteur a payé, ce qu'un vendeur a reçu). « est » = indice de la première bougie touchée par l'estimation en cours."""
    rows = sorted(rows)
    per = _periods(rows, now_rate, next_ms)
    ends = [p[1] for p in per]
    nr = per[-1][2] * 100.0 if per and per[-1][4] else None
    vals, cum, est = [], [], None
    run, k = 0.0, 0
    t_first = times[0] if times else 0
    pays = [(p[1], p[3]) for p in per if not p[4]]
    for idx, t in enumerate(times):
        end = min(t + step_ms, times[idx + 1]) if idx + 1 < len(times) else t + step_ms
        j = bisect_right(ends, t)
        w = acc = 0.0
        live = False
        while j < len(per) and per[j][0] < end:
            a, b, r8, _, e = per[j]
            ov = min(b, end) - max(a, t)
            if ov > 0 and not (e and now_ms is not None and t > now_ms):
                w += ov
                acc += ov * r8
                live = live or e
            j += 1
        vals.append(acc / w * 100.0 if w > 0 else None)
        if live and est is None:
            est = idx
        while k < len(pays) and pays[k][0] <= end:
            if pays[k][0] > t_first:
                run += pays[k][1] * 100.0
            k += 1
        cum.append(run if pays and pays[0][0] - 8 * H_MS <= end else None)
    week = [p for p in per if not p[4] and per and p[1] > (per[-1][0] if per[-1][4] else per[-1][1]) - 7 * 86_400_000]
    tw = sum(p[1] - p[0] for p in week)
    return {"funding": vals, "fundEst": est, "fundNow": nr, "fundCum": cum,
            "fundAvg7": sum((p[1] - p[0]) * p[2] for p in week) / tw * 100.0 if tw else None,
            "fundSince": rows[0][0] if rows else None,
            "fundHours": ((per[-1][1] - per[-1][0]) / H_MS) if per else None}


def aggregate_funding(rows) -> dict | None:
    """V37 : funding de toutes les bourses, PONDÉRÉ PAR L'INTÉRÊT OUVERT (en dollars) de chacune, ramené à 8 h.
    rows : [{ex, funding (taux de la période), intervalH, oiUsd}] -> {rate8h (%), n, rows: [{ex, rate8h, share}]}."""
    ok = [r for r in rows or [] if r.get("funding") is not None and r.get("oiUsd")]
    tot = sum(r["oiUsd"] for r in ok)
    if not ok or tot <= 0:
        return None
    det = [{"ex": r["ex"], "rate8h": r["funding"] * 8.0 / (r.get("intervalH") or 8.0) * 100.0, "share": r["oiUsd"] / tot} for r in ok]
    return {"rate8h": sum(d["rate8h"] * d["share"] for d in det), "n": len(det), "oiUsd": tot, "rows": det}
