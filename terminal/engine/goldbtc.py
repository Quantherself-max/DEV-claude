"""Le bitcoin et l'or sont-ils asymetriques ? Mesures sur des rendements quotidiens (engine/rotation.py fournit l'or tokenise PAXG, cote 24 h / 24).

  - correlation glissante (30 / 90 / 180 jours) : le lien change de signe selon les periodes ;
  - « semi-betas » : de combien le BTC bouge quand l'or monte (beta+) et quand l'or baisse (beta-), regression a deux pentes, erreur-type de Newey-West ;
    asymetrie = beta+ - beta- (test : ajouter un terme « or positif » a la regression) ;
  - jours de choc de l'or (± 1,5 %) : que fait le BTC le meme jour, le lendemain, dans les 5 jours qui suivent ;
  - avance / retard : le rendement de l'or sur les k jours precedents explique-t-il le rendement du BTC du jour ?
Module PUR (stdlib)."""
import math


def solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Resout a x = b (elimination de Gauss avec pivot) ; a est carree et petite."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-18:
            raise ZeroDivisionError("matrice singuliere")
        m[c], m[p] = m[p], m[c]
        for r in range(c + 1, n):
            f = m[r][c] / m[c][c]
            for k in range(c, n + 1):
                m[r][k] -= f * m[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][k] * x[k] for k in range(r + 1, n))) / m[r][r]
    return x


def inv(a: list[list[float]]) -> list[list[float]]:
    n = len(a)
    cols = [solve(a, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)]
    return [[cols[j][i] for j in range(n)] for i in range(n)]


def ols_hac(xs: list[list[float]], y: list[float], lags: int = 5):
    """Regression y ~ constante + xs (k regresseurs) avec erreurs-types de Newey-West. xs = liste de colonnes. Renvoie (coefficients, t) hors constante, ou None."""
    n, k = len(y), len(xs)
    if n < 60 or any(len(c) != n for c in xs):
        return None
    X = [[1.0] + [xs[j][i] for j in range(k)] for i in range(n)]
    p = k + 1
    xtx = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(p)] for a in range(p)]
    xty = [sum(X[i][a] * y[i] for i in range(n)) for a in range(p)]
    try:
        beta = solve(xtx, xty)
        xtxi = inv(xtx)
    except ZeroDivisionError:
        return None
    e = [y[i] - sum(X[i][a] * beta[a] for a in range(p)) for i in range(n)]
    z = [[X[i][a] * e[i] for a in range(p)] for i in range(n)]
    s = [[sum(z[i][a] * z[i][b] for i in range(n)) for b in range(p)] for a in range(p)]
    for l in range(1, lags + 1):
        w = 1.0 - l / (lags + 1.0)
        for a in range(p):
            for b in range(p):
                g = sum(z[i][a] * z[i - l][b] for i in range(l, n))
                g2 = sum(z[i][b] * z[i - l][a] for i in range(l, n))
                s[a][b] += w * (g + g2)
    v = [[sum(xtxi[a][c] * s[c][d] * xtxi[d][b] for c in range(p) for d in range(p)) for b in range(p)] for a in range(p)]
    se = [math.sqrt(max(v[a][a], 1e-30)) for a in range(p)]
    return beta[1:], [beta[a] / se[a] for a in range(1, p)]


def log_returns(prices: list) -> list:
    return [None] + [math.log(b / a) if (a and b and a > 0 and b > 0) else None for a, b in zip(prices, prices[1:])]


def pair(rg: list, rb: list):
    idx = [i for i in range(len(rg)) if rg[i] is not None and rb[i] is not None]
    return idx, [rg[i] for i in idx], [rb[i] for i in idx]


def semi_betas(rg: list, rb: list, lo: int = 0, hi: int | None = None) -> dict | None:
    hi = len(rg) if hi is None else hi
    idx, g, b = pair(rg[lo:hi], rb[lo:hi])
    if len(g) < 80:
        return None
    up = [max(x, 0.0) for x in g]
    dn = [min(x, 0.0) for x in g]
    two = ols_hac([up, dn], b, 5)
    asym = ols_hac([g, up], b, 5)
    if not two or not asym:
        return None
    return {"n": len(g), "up": {"beta": two[0][0], "t": two[1][0]}, "down": {"beta": two[0][1], "t": two[1][1]},
            "asym": {"diff": asym[0][1], "t": asym[1][1]}, "corr": _corr(g, b)}


def _corr(a: list, b: list) -> float | None:
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    sa, sb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(sa * sb) if sa > 0 and sb > 0 else None


def shocks(rg: list, rb: list, thr: float = 0.015, lo: int = 0, hi: int | None = None) -> list[dict]:
    """Rendement moyen du BTC (meme jour, lendemain, 5 jours suivants) apres un fort jour de l'or. Les 5 jours se recouvrent entre chocs proches : l'erreur-type est indicative."""
    hi = len(rg) if hi is None else hi
    out = []
    for lab, test in ((f"or ≥ +{thr * 100:.1f} %".replace(".", ","), lambda x: x >= thr), (f"or ≤ −{thr * 100:.1f} %".replace(".", ","), lambda x: x <= -thr)):
        ev = [i for i in range(max(lo, 1), min(hi, len(rg)) - 6) if rg[i] is not None and rb[i] is not None and test(rg[i])]
        if len(ev) < 15:
            out.append({"label": lab, "n": len(ev)})
            continue
        row = {"label": lab, "n": len(ev)}
        for key, f in (("same", lambda i: rb[i]), ("next", lambda i: rb[i + 1]), ("next5", lambda i: sum(x for x in rb[i + 1:i + 6] if x is not None))):
            xs = [f(i) for i in ev if f(i) is not None]
            m = sum(xs) / len(xs)
            sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
            row[key] = {"mean": m, "t": m / (sd / math.sqrt(len(xs))) if sd > 0 else 0.0}
        out.append(row)
    return out


def lead_lag(rg: list, rb: list, ks=(1, 5, 20), lo: int = 0, hi: int | None = None) -> list[dict]:
    """Le rendement cumule de l'or sur les k jours PRECEDENTS explique-t-il le rendement du BTC du jour ?"""
    hi = len(rg) if hi is None else hi
    out = []
    for k in ks:
        xs, ys = [], []
        for i in range(max(lo, k + 1), min(hi, len(rg))):
            w = rg[i - k:i]
            if rb[i] is not None and all(x is not None for x in w):
                xs.append(sum(w))
                ys.append(rb[i])
        r = ols_hac([xs], ys, k + 2) if len(xs) > 80 else None
        out.append({"k": k, "beta": r[0][0] if r else None, "t": r[1][0] if r else None, "n": len(xs)})
    return out


def analyse(gold: list, btc: list, grid: list, split_ms: int) -> dict:
    """Toutes les mesures sur deux series de prix alignees (None = jour manquant)."""
    rg, rb = log_returns(gold), log_returns(btc)
    sp = next((i for i, t in enumerate(grid) if t >= split_ms), len(grid))
    roll = {}
    for w in (30, 90, 180):
        cs = []
        for i in range(w, len(rg), max(1, w // 3)):
            _, a, b = pair(rg[i - w:i], rb[i - w:i])
            if len(a) >= int(w * 0.8):
                c = _corr(a, b)
                if c is not None:
                    cs.append(c)
        roll[str(w)] = {"mean": sum(cs) / len(cs), "min": min(cs), "max": max(cs), "positive": sum(1 for c in cs if c > 0) / len(cs), "n": len(cs)} if cs else None
    return {"corr": roll, "semi": {"all": semi_betas(rg, rb), "is": semi_betas(rg, rb, 0, sp), "oos": semi_betas(rg, rb, sp)},
            "shocks": {"all": shocks(rg, rb), "is": shocks(rg, rb, 0.015, 0, sp), "oos": shocks(rg, rb, 0.015, sp)}, "leadLag": {"all": lead_lag(rg, rb), "is": lead_lag(rg, rb, lo=0, hi=sp), "oos": lead_lag(rg, rb, lo=sp)}}
