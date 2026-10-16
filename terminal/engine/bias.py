"""Biais statistique VALIDE hors echantillon (bougies 1h fermees uniquement, aucune donnee du futur).

1) Variables calculees a chaque cloture horaire : momentum 4/24/72 h normalise par la volatilite, CVD reel
   4/24 h (volume acheteur agressif), ecart aux VWAP jour/semaine, regime de volatilite, position dans
   l'amplitude 72 h, funding.
2) Regression logistique (ridge) qui estime la probabilite que le prix soit plus haut dans 4 h / 24 h.
3) Validation « walk-forward » : le modele est entraine sur le passe seulement (avec une marge egale a
   l'horizon pour eviter toute fuite), teste sur les 30 jours suivants, et on recommence en avancant.
   On mesure alors l'AUC, le score de Brier et la precision avec un intervalle de confiance (bootstrap
   par blocs de 24 h, car les echantillons voisins se chevauchent).
4) Calibration de Platt sur ces predictions hors echantillon : la probabilite affichee est celle qui s'est
   reellement realisee. Si le modele ne bat pas le hasard, on l'affiche tel quel (« pas d'avantage prouve »).
5) Tables conditionnelles (tiers de chaque variable) et « first passage » (TP avant SL) pour le plan de trade."""
import json
import math
import os
import random
import time
from bisect import bisect_right
from collections import deque

from .stats import Z90, atr_series, wilson

FEATS = [
    ("mom4", "Momentum 4 h", "Rendement des 4 dernières heures, en unités de volatilité"),
    ("mom24", "Momentum 24 h", "Rendement des 24 dernières heures, en unités de volatilité"),
    ("mom72", "Momentum 72 h", "Rendement des 72 dernières heures, en unités de volatilité"),
    ("cvd4", "CVD 4 h", "(achats agressifs − ventes agressives) / volume sur 4 h"),
    ("cvd24", "CVD 24 h", "(achats agressifs − ventes agressives) / volume sur 24 h"),
    ("dvwap", "Écart VWAP jour", "(prix − VWAP du jour) / ATR"),
    ("wvwap", "Écart VWAP semaine", "(prix − VWAP de la semaine) / ATR"),
    ("volreg", "Régime de volatilité", "ln(ATR actuel / ATR moyen des 100 dernières heures)"),
    ("range72", "Position 72 h", "0 = plus bas des 72 h, 1 = plus haut des 72 h"),
    ("funding", "Funding", "Dernier taux de funding (en % par 8 h)"),
]
NAMES = [f[0] for f in FEATS]
WARMUP = 120                      # heures necessaires avant de pouvoir calculer toutes les variables
LAMBDA = 60.0                     # ridge : on prefere un modele prudent a un modele qui sur-apprend
HORIZONS = (4, 24)
MAX_TRAIN_H = 24 * 365 * 3        # fenetre d'entrainement glissante de 3 ans : le marche change de regime
VERSION = 2


def _clip(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def build_features(candles, funding=None):
    """Variables a la cloture de chaque bougie (liste de listes, None avant WARMUP). funding = [(t_ms, taux)]."""
    n = len(candles)
    atr = atr_series(candles)
    out = [None] * n
    ft = [t for t, _ in funding] if funding else []
    fv = [r for _, r in funding] if funding else []
    day_key = week_key = None
    pv_d = v_d = pv_w = v_w = 0.0
    win4, win24 = deque(), deque()
    hi72, lo72 = deque(), deque()
    atr_q, atr_sum = deque(), 0.0
    for i, k in enumerate(candles):
        days = k.t // 86_400_000
        if days != day_key:
            day_key, pv_d, v_d = days, 0.0, 0.0
        wk = (days + 3) // 7                                  # semaines commencant le lundi (jour 0 = jeudi)
        if wk != week_key:
            week_key, pv_w, v_w = wk, 0.0, 0.0
        tp = (k.h + k.l + k.c) / 3.0
        pv_d += tp * k.v; v_d += k.v; pv_w += tp * k.v; v_w += k.v
        for q, size in ((win4, 4), (win24, 24)):
            q.append((k.v, k.tb))
            if len(q) > size:
                q.popleft()
        while hi72 and candles[hi72[-1]].h <= k.h:
            hi72.pop()
        hi72.append(i)
        while hi72[0] <= i - 72:
            hi72.popleft()
        while lo72 and candles[lo72[-1]].l >= k.l:
            lo72.pop()
        lo72.append(i)
        while lo72[0] <= i - 72:
            lo72.popleft()
        atr_q.append(atr[i]); atr_sum += atr[i]
        if len(atr_q) > 100:
            atr_sum -= atr_q.popleft()
        if i < WARMUP or not atr[i] or not k.c:
            continue
        c, a = k.c, atr[i]
        ap = a / c

        def mom(h):
            return _clip(math.log(c / candles[i - h].c) / (ap * math.sqrt(h)), -6, 6)

        def cvd(q):
            vs = [(v, tb) for v, tb in q if v > 0 and tb > 0]
            s = sum(v for v, _ in vs)
            return (2 * sum(tb for _, tb in vs) - s) / s if s > 0 else 0.0

        rng = candles[hi72[0]].h - candles[lo72[0]].l
        f = bisect_right(ft, k.t + 3_600_000) - 1             # dernier funding connu a la cloture de la bougie
        out[i] = [mom(4), mom(24), mom(72), cvd(win4), cvd(win24),
                  _clip((c - pv_d / v_d) / a, -6, 6) if v_d > 0 else 0.0,
                  _clip((c - pv_w / v_w) / a, -8, 8) if v_w > 0 else 0.0,
                  _clip(math.log(a / (atr_sum / len(atr_q))), -1.5, 1.5),
                  (c - candles[lo72[0]].l) / rng - 0.5 if rng > 0 else 0.0,
                  fv[f] * 100.0 if f >= 0 else 0.0]
    return out


# ---------- regression logistique (Newton / IRLS, ridge) ----------
def _sigmoid(z):
    return 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))


def _solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            continue
        M[c], M[piv] = M[piv], M[c]
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                if f:
                    M[r] = [x - f * y for x, y in zip(M[r], M[c])]
    return [M[i][n] / M[i][i] if abs(M[i][i]) > 1e-12 else 0.0 for i in range(n)]


def fit_logistic(X, y, lam=LAMBDA, iters=8):
    """X : lignes deja standardisees (sans colonne constante). Retourne [intercept, b1..bp]."""
    p = len(X[0]) + 1
    w = [0.0] * p
    for _ in range(iters):
        g = [0.0] * p
        H = [[0.0] * p for _ in range(p)]
        for xi, yi in zip(X, y):
            row = [1.0] + xi
            pr = _sigmoid(sum(a * b for a, b in zip(w, row)))
            r, wt = pr - yi, max(pr * (1 - pr), 1e-6)
            for a in range(p):
                g[a] += r * row[a]
                wa, Ha = wt * row[a], H[a]
                for b in range(a, p):
                    Ha[b] += wa * row[b]
        for a in range(p):
            for b in range(a):
                H[a][b] = H[b][a]
            if a:
                g[a] += lam * w[a]
                H[a][a] += lam
        step = _solve(H, g)
        w = [a - b for a, b in zip(w, step)]
        if max(abs(s) for s in step) < 1e-6:
            break
    return w


def _standardize(rows):
    p = len(rows[0])
    mu = [sum(r[j] for r in rows) / len(rows) for j in range(p)]
    sd = [math.sqrt(sum((r[j] - mu[j]) ** 2 for r in rows) / len(rows)) for j in range(p)]
    return mu, [s if s > 1e-9 else 1.0 for s in sd]


def _apply(mu, sd, row):
    return [(a - m) / s for a, m, s in zip(row, mu, sd)]


def _predict(w, z):
    return _sigmoid(w[0] + sum(a * b for a, b in zip(w[1:], z)))


def train(rows, labels, lam=LAMBDA):
    mu, sd = _standardize(rows)
    w = fit_logistic([_apply(mu, sd, r) for r in rows], labels, lam)
    return {"mu": mu, "sd": sd, "w": w}


def predict(model, row):
    return _predict(model["w"], _apply(model["mu"], model["sd"], row))


# ---------- metriques ----------
def auc(preds, ys):
    pairs = sorted(zip(preds, ys))
    ranks, i, n = [0.0] * len(pairs), 0, len(pairs)
    while i < n:
        j = i
        while j + 1 < n and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j) / 2.0 + 1.0
        i = j + 1
    n1 = sum(y for _, y in pairs)
    n0 = n - n1
    if n1 == 0 or n0 == 0:
        return 0.5
    return (sum(r for r, (_, y) in zip(ranks, pairs) if y) - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def brier(preds, ys):
    return sum((p - y) ** 2 for p, y in zip(preds, ys)) / len(ys)


def _metrics(preds, ys, base_p):
    b0 = brier([base_p] * len(ys), ys)
    pred_up = base_p >= 0.5
    acc = sum(1 for p, y in zip(preds, ys) if (p >= 0.5) == bool(y)) / len(ys)
    acc0 = sum(1 for y in ys if bool(y) == pred_up) / len(ys)
    return {"auc": auc(preds, ys), "skill": 1 - brier(preds, ys) / b0 if b0 > 0 else 0.0, "acc": acc, "edge": acc - acc0}


def _boot_ci(preds, ys, base_p, block, reps=200, seed=11):
    r = random.Random(seed)
    n = len(ys)
    nb = max(1, n // block)
    acc = {k: [] for k in ("auc", "skill", "edge")}
    for _ in range(reps):
        idx = []
        for _ in range(nb):
            s = r.randrange(0, max(1, n - block))
            idx += range(s, min(n, s + block))
        m = _metrics([preds[i] for i in idx], [ys[i] for i in idx], base_p)
        for k in acc:
            acc[k].append(m[k])
    out = {}
    for k, v in acc.items():
        v.sort()
        out[k] = (v[int(0.05 * len(v))], v[int(0.95 * len(v)) - 1])
    return out


def _platt(preds, ys):
    """p_cal = sigmoid(a + b * logit(p)) ajuste sur les predictions hors echantillon."""
    xs = [math.log(_clip(p, 1e-4, 1 - 1e-4) / (1 - _clip(p, 1e-4, 1 - 1e-4))) for p in preds]
    w = fit_logistic([[x] for x in xs], ys, lam=1e-3)
    return w[0], w[1]


# ---------- validation walk-forward ----------
def walk_forward(X, ys, idx, h, stride=2, min_train_h=24 * 100, fold_h=None, max_train_h=MAX_TRAIN_H):
    """idx : position horaire de chaque echantillon. Retourne les predictions hors echantillon.
    Entrainement sur les `max_train_h` heures qui precedent (marge h pour eviter toute fuite), test sur le pli suivant."""
    pos = list(range(len(idx)))
    span = idx[-1] - idx[0]
    fold_h = fold_h or (24 * 30 if span < 24 * 900 else 24 * 90)      # plis plus longs quand l'historique est tres long
    first_test = idx[0] + max(min_train_h, int(span * 0.4))
    preds, labs, ts, folds = [], [], [], 0
    start = first_test
    while start <= idx[-1]:
        tr = [q for q in pos if start - h - max_train_h < idx[q] <= start - h and (idx[q] % stride == 0)]
        te = [q for q in pos if start <= idx[q] < start + fold_h and (idx[q] % stride == 0)]
        if len(tr) > 400 and te:
            ytr = [ys[q] for q in tr]
            if 0 < sum(ytr) < len(ytr):
                m = train([X[q] for q in tr], ytr)
                for q in te:
                    preds.append(predict(m, X[q]))
                    labs.append(ys[q])
                    ts.append(idx[q])
                folds += 1
        start += fold_h
    return preds, labs, ts, folds


def _calibration(preds, ys, bins=5):
    if not preds:
        return []
    order = sorted(range(len(preds)), key=lambda i: preds[i])
    out, size = [], max(1, len(order) // bins)
    for b in range(bins):
        sel = order[b * size:(b + 1) * size if b < bins - 1 else len(order)]
        if sel:
            out.append({"p": sum(preds[i] for i in sel) / len(sel), "freq": sum(ys[i] for i in sel) / len(sel), "n": len(sel)})
    return out


def tercile_tables(X, ys, cur, stride_h=24):
    """P(hausse a l'horizon | tiers actuel de chaque variable) : descriptif, sur tout l'historique."""
    n = len(ys)
    out = []
    base_k = sum(ys)
    for j, (key, label, _) in enumerate(FEATS):
        col = sorted(r[j] for r in X)
        if col[0] == col[-1]:
            continue
        t1, t2 = col[n // 3], col[2 * n // 3]
        tier = lambda v: 0 if v <= t1 else 1 if v <= t2 else 2
        ct = tier(cur[j])
        k = sum(1 for r, y in zip(X, ys) if y and tier(r[j]) == ct)
        m = sum(1 for r in X if tier(r[j]) == ct)
        neff = max(1, int(m / stride_h))                       # les echantillons voisins se chevauchent
        p, lo, hi = wilson(round(k / m * neff), neff) if m else (None, None, None)
        out.append({"key": key, "label": label, "tier": ("bas", "milieu", "haut")[ct], "p": k / m if m else None,
                    "lo": lo, "hi": hi, "n": m, "neff": neff, "base": base_k / n})
    return out


def analyse(candles, funding=None, now_ms=None):
    """Entraine, valide et predit pour chaque horizon. candles : bougies 1h FERMEES. Peut prendre quelques secondes."""
    n = len(candles)
    if n < WARMUP + 24 * 160:
        return {"ready": False, "reason": f"historique trop court ({n} h ; il faut au moins {WARMUP + 24 * 160} h)"}
    feats = build_features(candles, funding)
    cur = feats[-1]
    if cur is None:
        return {"ready": False, "reason": "variables indisponibles"}
    res = {"ready": True, "version": VERSION, "bars": n, "t": candles[-1].t, "since": candles[0].t,
           "computedAt": int(time.time() * 1000), "features": [], "horizons": {}}
    stride = 2 if n < 30000 else 3
    for h in HORIZONS:
        idx = [i for i in range(WARMUP, n - h)]
        X = [feats[i] for i in idx]
        ys = [1 if candles[i + h].c > candles[i].c else 0 for i in idx]
        preds, labs, ts, folds = walk_forward(X, ys, idx, h, stride=stride)
        base = sum(ys) / len(ys)
        train_idx = [q for q in range(len(idx)) if idx[q] % stride == 0 and idx[q] > idx[-1] - MAX_TRAIN_H]
        model = train([X[q] for q in train_idx], [ys[q] for q in train_idx])
        z = _apply(model["mu"], model["sd"], cur)
        p_raw = _predict(model["w"], z)
        info = {"h": h, "base": base, "pRaw": p_raw, "folds": folds, "n": len(labs), "validated": False,
                "pUp": base, "pCal": base}
        if len(labs) >= 300:
            base_oos = sum(labs) / len(labs)
            met = _metrics(preds, labs, sum(ys) / len(ys))
            ci = _boot_ci(preds, labs, sum(ys) / len(ys), block=max(1, 24 // 2))
            a, b = _platt(preds, labs)
            p_cal = _sigmoid(a + b * math.log(_clip(p_raw, 1e-4, 1 - 1e-4) / (1 - _clip(p_raw, 1e-4, 1 - 1e-4))))
            validated = ci["auc"][0] > 0.5 and met["skill"] > 0 and b > 0.1
            neff = max(1, int(len(labs) / (24 / 2)))
            info.update({"auc": met["auc"], "aucCI": ci["auc"], "skill": met["skill"], "skillCI": ci["skill"], "acc": met["acc"],
                         "edge": met["edge"], "edgeCI": ci["edge"], "neff": neff, "baseOos": base_oos,
                         "platt": (a, b), "validated": validated, "pCal": p_cal,
                         "pUp": p_cal if validated else base,
                         "calibration": _calibration([_sigmoid(a + b * math.log(_clip(p, 1e-4, 1 - 1e-4) / (1 - _clip(p, 1e-4, 1 - 1e-4)))) for p in preds], labs)})
        info["contrib"] = sorted([{"key": k, "label": lab, "raw": cur[j], "z": z[j], "w": model["w"][j + 1],
                                   "c": model["w"][j + 1] * z[j]} for j, (k, lab, _) in enumerate(FEATS)],
                                 key=lambda d: -abs(d["c"]))
        info["tables"] = tercile_tables(X, ys, cur, stride_h=h)
        info["_model"], info["_X"], info["_ys"] = model, X, ys             # gardes pour mettre a jour la prediction chaque heure
        res["horizons"][str(h)] = info
    res["features"] = [{"key": k, "label": lab, "raw": cur[j], "help": hp} for j, (k, lab, hp) in enumerate(FEATS)]
    return res


def repredict(res, candles, funding=None):
    """Met a jour la prediction avec la derniere bougie fermee SANS re-entrainer (le modele valide reste le meme)."""
    feats = build_features(candles, funding)
    cur = feats[-1]
    if cur is None or not res.get("ready"):
        return res
    new = {**res, "t": candles[-1].t, "bars": len(candles), "horizons": {}}
    for h, info in res["horizons"].items():
        model = info["_model"]
        if "_X" not in info:                                    # resultat relu du disque : jeux d'apprentissage reconstruits
            idx = [i for i in range(WARMUP, len(candles) - int(h))]
            info = {**info, "_X": [feats[i] for i in idx], "_ys": [1 if candles[i + int(h)].c > candles[i].c else 0 for i in idx]}
        z = _apply(model["mu"], model["sd"], cur)
        p_raw = _predict(model["w"], z)
        out = {**info, "pRaw": p_raw}
        if info.get("platt"):
            a, b = info["platt"]
            lg = math.log(_clip(p_raw, 1e-4, 1 - 1e-4) / (1 - _clip(p_raw, 1e-4, 1 - 1e-4)))
            out["pCal"] = _sigmoid(a + b * lg)
            out["pUp"] = out["pCal"] if info["validated"] else info["base"]
        out["contrib"] = sorted([{"key": k, "label": lab, "raw": cur[j], "z": z[j], "w": model["w"][j + 1],
                                  "c": model["w"][j + 1] * z[j]} for j, (k, lab, _) in enumerate(FEATS)], key=lambda d: -abs(d["c"]))
        out["tables"] = tercile_tables(info["_X"], info["_ys"], cur, stride_h=int(h))
        new["horizons"][h] = out
    new["features"] = [{"key": k, "label": lab, "raw": cur[j], "help": hp} for j, (k, lab, hp) in enumerate(FEATS)]
    return new


def save(res, path):
    """Ecrit le resultat valide (sans les jeux d'apprentissage, reconstruits au besoin) : le redemarrage est instantane."""
    out = {**res, "horizons": {h: {k: v for k, v in info.items() if k not in ("_X", "_ys")} for h, info in res["horizons"].items()}}
    try:
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f)
        os.replace(tmp, path)
    except OSError:
        pass


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if d.get("version") == VERSION and d.get("ready") else None
    except (OSError, ValueError):
        return None


def public(res):
    """Version JSON : sans les donnees d'entrainement (cles commencant par _)."""
    if not res:
        return res
    return {**{k: v for k, v in res.items() if k != "horizons"},
            "horizons": {h: {k: v for k, v in info.items() if not k.startswith("_")} for h, info in res.get("horizons", {}).items()}}


# ---------- plan de trade : TP avant SL (first passage) ----------
def first_passage(candles, atrs, up_atr, dn_atr, horizon, warmup=24 * 14):
    """Pour chaque heure de depart : le prix touche d'abord +up_atr ou -dn_atr (en ATR de l'heure de depart) ?
    Si les deux sont touches dans la meme bougie on compte le STOP en premier (hypothese prudente).
    Renvoie les comptes (up_first, dn_first, aucun)."""
    n = len(candles)
    u = d = z = 0
    for i in range(warmup, n - 1):
        a = atrs[i]
        if not a:
            continue
        c = candles[i].c
        up, dn = c + up_atr * a, c - dn_atr * a
        res = 0
        for j in range(i + 1, min(n, i + 1 + horizon)):
            hit_up, hit_dn = candles[j].h >= up, candles[j].l <= dn
            if hit_dn:
                res = -1
                break
            if hit_up:
                res = 1
                break
        if i + horizon >= n and res == 0:
            continue                                            # horizon pas encore ecoule
        if res > 0:
            u += 1
        elif res < 0:
            d += 1
        else:
            z += 1
    return u, d, z


def plan(candles, atrs, side, tp_pct, sl_pct, horizon, price, atr_now):
    """Probabilites empiriques pour un trade (long ou short) : TP avant SL, SL avant TP, ni l'un ni l'autre."""
    a_pct = atr_now / price * 100.0
    tp_a, sl_a = tp_pct / a_pct, sl_pct / a_pct
    up_a, dn_a = (tp_a, sl_a) if side == "long" else (sl_a, tp_a)
    u, d, z = first_passage(candles, atrs, up_a, dn_a, horizon)
    n = u + d + z
    win, loss = (u, d) if side == "long" else (d, u)
    neff = max(1, n // max(1, horizon // 2))
    out = {"n": n, "neff": neff, "tpAtr": tp_a, "slAtr": sl_a, "horizon": horizon}
    for key, k in (("tp", win), ("sl", loss), ("none", z)):
        p, lo, hi = wilson(round(k / n * neff), neff) if n else (None, None, None)
        out[key] = {"p": k / n if n else None, "lo": lo, "hi": hi}
    if n and tp_pct > 0 and sl_pct > 0:
        out["rr"] = tp_pct / sl_pct
        out["ev"] = (win * tp_pct - loss * sl_pct) / n          # esperance en % du prix, par trade (avant frais), sans levier
    return out
