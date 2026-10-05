"""Couverture (hedge) entre variantes : quelle variante gagne quand la principale perd ?

On transforme chaque liste de trades (backtest.select) en rendements par periode (jour ou semaine) a risque fixe (par defaut 1 % du capital par trade,
levier plafonne), puis on mesure :
  - la correlation des rendements entre la strategie principale et chaque candidate de couverture ;
  - le portefeuille « principale + w x couverture » : rendement annualise, baisse maximale, Sharpe, pire periode ;
  - quelle couverture, a quel poids, reduit le plus la baisse maximale SANS faire passer l'esperance sous zero.
Module PUR."""
import math

DAY = 86_400_000
WEEK = 7 * DAY


def series(trades: list[dict], start_ms: int, end_ms: int, bucket: int = WEEK, risk_pct: float = 0.01, max_lev: float = 10.0) -> list[float]:
    """Rendement de chaque periode (somme des rendements des trades sortis dans la periode ; risque fixe en % du capital initial)."""
    n = max(1, int((end_ms - start_ms) // bucket) + 1)
    out = [0.0] * n
    for t in trades:
        k = int((t["exit_t"] - start_ms) // bucket)
        if 0 <= k < n:
            eff = min(risk_pct, max_lev * t["stop_pct"])
            out[k] += eff * t["r"]
    return out


def corr(a: list[float], b: list[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 10:
        return None
    ma, mb = sum(a[:n]) / n, sum(b[:n]) / n
    va = sum((x - ma) ** 2 for x in a[:n])
    vb = sum((x - mb) ** 2 for x in b[:n])
    if va <= 0 or vb <= 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a[:n], b[:n])) / math.sqrt(va * vb)


def stats(rets: list[float], per_year: float = 52.0) -> dict:
    """Rendement compose, annualise, baisse maximale, Sharpe, pire periode."""
    eq, peak, dd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= max(0.0, 1.0 + r)
        peak = max(peak, eq)
        dd = max(dd, 1.0 - eq / peak)
    n = len(rets)
    mu = sum(rets) / n if n else 0.0
    sd = math.sqrt(sum((x - mu) ** 2 for x in rets) / (n - 1)) if n > 1 else 0.0
    years = n / per_year if n else 1.0
    return {"ret": eq - 1.0, "cagr": eq ** (1.0 / years) - 1.0 if eq > 0 and years > 0 else -1.0, "maxDD": dd,
            "sharpe": mu / sd * math.sqrt(per_year) if sd > 0 else None, "worst": min(rets) if rets else 0.0, "mean": mu}


def combine(main: list[float], hedge: list[float], w: float) -> list[float]:
    n = min(len(main), len(hedge))
    return [main[i] + w * hedge[i] for i in range(n)]


def evaluate(main_tr: list[dict], cands: dict[str, list[dict]], start_ms: int, end_ms: int, weights=(0.25, 0.5, 1.0), bucket: int = WEEK) -> dict:
    """Pour chaque candidate : correlation et portefeuille principale + w x candidate."""
    per_year = 365.0 * DAY / bucket
    m = series(main_tr, start_ms, end_ms, bucket)
    base = stats(m, per_year)
    rows = []
    for name, tr in cands.items():
        h = series(tr, start_ms, end_ms, bucket)
        row = {"name": name, "n": len(tr), "corr": corr(m, h), "alone": stats(h, per_year), "mix": []}
        for w in weights:
            row["mix"].append({"w": w, **stats(combine(m, h, w), per_year)})
        rows.append(row)
    return {"main": base, "rows": rows}


def best_hedge(ev: dict, weights=(0.25, 0.5, 1.0)):
    """Meilleure (candidate, poids) : plus forte baisse de la baisse maximale, sans abaisser le rendement annualise de la principale de plus de moitie."""
    base = ev["main"]
    best = None
    for row in ev["rows"]:
        for mix in row["mix"]:
            if mix["cagr"] < 0.5 * base["cagr"] if base["cagr"] > 0 else mix["cagr"] < base["cagr"]:
                continue
            gain = base["maxDD"] - mix["maxDD"]
            if best is None or gain > best[0]:
                best = (gain, row["name"], mix["w"], mix)
    return best
