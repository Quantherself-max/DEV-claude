"""Options : modèle de Black (1976), volatilité implicite, skew à 25 delta, max pain, exposition gamma par strike (V45).

Les options de Deribit portent sur le prix À TERME de leur échéance (F), sans taux d'intérêt, et leur prime est cotée en pièces (BTC).
  d1 = (ln(F / K) + σ² T / 2) / (σ √T)          d2 = d1 - σ √T
  call = F N(d1) - K N(d2)                       put = K N(-d2) - F N(-d1)                  (en dollars ; ÷ F pour la prime en BTC)
  delta = N(d1) (call), N(d1) - 1 (put)          gamma = φ(d1) / (F σ √T)
  vega  = F φ(d1) √T                             thêta = - F φ(d1) σ / (2 √T)               (par an ; ÷ 365 par jour)
T en années de 365 jours (la convention de Deribit, vérifiée contre ses propres volatilités : voir tests/test_v45_live.py).

Ces formules sont exactes (ce sont celles du modèle, pas une approximation numérique) ; elles sont ÉVALUÉES en flottants 64 bits car
elles contiennent logarithme, exponentielle et loi normale (nombres irrationnels : aucun type décimal ne les rend « exacts »). L'erreur
d'évaluation est de l'ordre de 10^-15 en relatif. La loi normale utilise erfc (précise aussi dans les queues).

- implied_vol : volatilité qui redonne un prix (bissection sécurisée + Newton), précision 10^-10 sur σ.
- skew25 : par échéance, volatilité du put 25 delta moins celle du call 25 delta (positif = les puts de protection coûtent plus cher),
  risk reversal (l'opposé) et butterfly ; les volatilités à 25 delta sont lues par interpolation linéaire en delta entre les deux
  options qui encadrent, sans extrapolation.
- max_pain : strike qui minimise la somme payée aux détenteurs à l'échéance ; calcul EXACT en décimal.
- gex_by_strike : gamma × intérêt ouvert × F² × 1 %, en dollars à couvrir pour un mouvement de 1 %, calls +, puts - (convention
  habituelle : les teneurs de marché sont acheteurs des calls et vendeurs des puts du public ; ce n'est pas observable).
Module PUR."""
from __future__ import annotations
import math
from decimal import Decimal

from .num import CTX, D, ZERO

SQRT2 = math.sqrt(2.0)
SQRT2PI = math.sqrt(2.0 * math.pi)
YEAR_MS = 365.0 * 86_400_000.0
MIN_T = 1.0 / (365.0 * 24.0 * 60.0)                 # une minute : en dessous, les grecques n'ont plus de sens


def norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / SQRT2)


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT2PI


def years(expiry_ms: int, now_ms: int) -> float:
    return (expiry_ms - now_ms) / YEAR_MS


def d1d2(f: float, k: float, iv: float, t: float):
    s = iv * math.sqrt(t)
    d1 = (math.log(f / k) + 0.5 * s * s) / s
    return d1, d1 - s


def _check(f, k, iv, t):
    if not (f > 0 and k > 0 and iv > 0 and t > 0):
        raise ValueError("prix à terme, strike, volatilité et durée doivent être positifs")


def price(kind: str, f: float, k: float, iv: float, t: float) -> float:
    """Prime en dollars (non actualisée). kind = 'C' ou 'P'."""
    _check(f, k, iv, t)
    d1, d2 = d1d2(f, k, iv, t)
    if kind == "C":
        return f * norm_cdf(d1) - k * norm_cdf(d2)
    return k * norm_cdf(-d2) - f * norm_cdf(-d1)


def greeks(kind: str, f: float, k: float, iv: float, t: float) -> dict:
    """prix ($ et pièces), delta, gamma (par dollar), vega (par point de volatilité : 1 % = 0,01), thêta (dollars par jour)."""
    _check(f, k, iv, t)
    d1, d2 = d1d2(f, k, iv, t)
    pdf, sq = norm_pdf(d1), math.sqrt(t)
    p = f * norm_cdf(d1) - k * norm_cdf(d2) if kind == "C" else k * norm_cdf(-d2) - f * norm_cdf(-d1)
    return {"price": p, "priceCoin": p / f, "delta": norm_cdf(d1) - (0.0 if kind == "C" else 1.0), "gamma": pdf / (f * iv * sq),
            "vega": f * pdf * sq / 100.0, "theta": -f * pdf * iv / (2.0 * sq) / 365.0, "d1": d1, "d2": d2}


def implied_vol(kind: str, f: float, k: float, t: float, premium: float, lo: float = 1e-4, hi: float = 20.0, tol: float = 1e-10):
    """Volatilité (fraction : 0,5 = 50 %) qui donne `premium` (dollars). None si le prix est hors des bornes possibles (sous la valeur
    intrinsèque, ou au-dessus de la prime maximale)."""
    if not (f > 0 and k > 0 and t > 0 and premium > 0):
        return None
    intrinsic = max(0.0, f - k) if kind == "C" else max(0.0, k - f)
    cap = f if kind == "C" else k
    if premium <= intrinsic or premium >= cap:
        return None
    a, b = lo, hi
    if price(kind, f, k, a, t) > premium or price(kind, f, k, b, t) < premium:
        return None
    x = min(b, max(a, math.sqrt(2.0 * abs(math.log(f / k)) / t) or 0.5))        # point d'inflexion : Newton y converge (Manaster-Koehler)
    for _ in range(200):
        d1, _d2 = d1d2(f, k, x, t)
        diff = price(kind, f, k, x, t) - premium
        if diff > 0:
            b = x
        else:
            a = x
        if b - a < tol:
            break
        vega = f * norm_pdf(d1) * math.sqrt(t)
        nx = x - diff / vega if vega > 1e-300 else None
        x = nx if nx is not None and a < nx < b else 0.5 * (a + b)
    return 0.5 * (a + b)


# ---------- lecture d'une chaîne d'options ----------
# une ligne = {"strike", "kind" ('C' / 'P'), "oi" (pièces), "iv" (fraction), "f" (prix à terme de l'échéance), "expiry" (ms)}
def _interp(pts: list, x: float):
    """Valeur en x par interpolation linéaire entre les deux points (abscisse, valeur) qui encadrent ; None hors de la plage."""
    pts = sorted(pts)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return None


def smile(rows: list, now_ms: int) -> list:
    """Par échéance : volatilité au prix (interpolée en strike autour du prix à terme), volatilités à 25 delta, skew, risk reversal,
    butterfly. Les échéances à moins d'une heure sont ignorées."""
    by: dict[int, list] = {}
    for r in rows:
        if r.get("iv") and r["iv"] > 0 and r.get("f") and r["f"] > 0 and r["expiry"] - now_ms > 3_600_000:
            by.setdefault(r["expiry"], []).append(r)
    out = []
    for e in sorted(by):
        rs = by[e]
        t = years(e, now_ms)
        f = rs[0]["f"]
        calls, puts, atm = [], [], {}
        for r in rs:
            d1, _ = d1d2(r["f"], r["strike"], r["iv"], t)
            delta = norm_cdf(d1) - (0.0 if r["kind"] == "C" else 1.0)
            (calls if r["kind"] == "C" else puts).append((delta, r["iv"], r["strike"]))
            atm.setdefault(r["strike"], []).append(r["iv"])
        ks = sorted((k, sum(v) / len(v)) for k, v in atm.items())
        iv_atm = _interp(ks, f)
        if iv_atm is None and ks:
            iv_atm = min(ks, key=lambda p: abs(p[0] - f))[1]
        c25 = _interp([(d, iv) for d, iv, _ in calls], 0.25)
        p25 = _interp([(d, iv) for d, iv, _ in puts], -0.25)
        kc = _interp([(d, k) for d, _, k in calls], 0.25)
        kp = _interp([(d, k) for d, _, k in puts], -0.25)
        row = {"expiry": e, "days": t * 365.0, "f": f, "atm": iv_atm, "call25": c25, "put25": p25, "strikeCall25": kc, "strikePut25": kp,
               "skew25": None, "rr25": None, "fly25": None, "n": len(rs)}
        if c25 is not None and p25 is not None:
            row["skew25"], row["rr25"] = p25 - c25, c25 - p25
            if iv_atm is not None:
                row["fly25"] = 0.5 * (c25 + p25) - iv_atm
        out.append(row)
    return out


def max_pain(oi_by_strike: dict):
    """{strike: (intérêt ouvert des calls, des puts)} -> (strike de max pain, somme payée à ce strike), en Decimal. À égalité : le strike
    le plus bas. La somme payée si le prix finit à S : Σ calls × max(0, S - K) + Σ puts × max(0, K - S)."""
    items = [(D(k), D(c), D(p)) for k, (c, p) in oi_by_strike.items()]
    if not items:
        return None, None
    best_k, best = None, None
    for s, _, _ in sorted(items):
        pay = ZERO
        for k, c, p in items:
            if s > k:
                pay = CTX.add(pay, CTX.multiply(c, CTX.subtract(s, k)))
            elif k > s:
                pay = CTX.add(pay, CTX.multiply(p, CTX.subtract(k, s)))
        if best is None or pay < best:
            best, best_k = pay, s
    return best_k, best


def gex_by_strike(rows: list, now_ms: int, spot: float | None = None) -> dict:
    """Exposition gamma par strike, au prix du moment : dollars à couvrir pour 1 % de mouvement (calls +, puts -). Renvoie byStrike
    [(strike, gex, gex calls, gex puts)], total, mur de calls (strike au gamma positif le plus fort), mur de puts, et `flip` : le prix
    où le gamma total change de signe (recherche sur ± 25 % par pas de 0,25 %, interpolation linéaire entre deux pas)."""
    good = []
    for r in rows:
        t = years(r["expiry"], now_ms)
        if t > MIN_T and r.get("oi") and r["oi"] > 0 and r.get("iv") and r["iv"] > 0 and r.get("f") and r["f"] > 0:
            good.append((r, t))
    if not good:
        return {"byStrike": [], "total": 0.0, "callWall": None, "putWall": None, "flip": None, "n": 0}
    by: dict[float, list] = {}
    tot = 0.0
    for r, t in good:
        g = norm_pdf(d1d2(r["f"], r["strike"], r["iv"], t)[0]) / (r["f"] * r["iv"] * math.sqrt(t)) * r["oi"] * r["f"] * r["f"] * 0.01
        e = by.setdefault(r["strike"], [0.0, 0.0])
        e[0 if r["kind"] == "C" else 1] += g
        tot += g if r["kind"] == "C" else -g
    rows_out = sorted((k, c - p, c, -p) for k, (c, p) in by.items())
    call_wall = max(rows_out, key=lambda x: x[1])
    put_wall = min(rows_out, key=lambda x: x[1])

    def total_at(scale: float) -> float:
        s = 0.0
        for r, t in good:
            f = r["f"] * scale
            g = norm_pdf(d1d2(f, r["strike"], r["iv"], t)[0]) / (f * r["iv"] * math.sqrt(t)) * r["oi"] * f * f * 0.01
            s += g if r["kind"] == "C" else -g
        return s

    flip = None
    ref = spot if spot else good[0][0]["f"]
    steps = [1.0 + j * 0.0025 for j in range(-100, 101)]
    vals = [total_at(sc) for sc in steps]
    cross = [(steps[i], steps[i + 1], vals[i], vals[i + 1]) for i in range(len(steps) - 1) if (vals[i] < 0) != (vals[i + 1] < 0)]
    if cross:
        s0, s1, v0, v1 = min(cross, key=lambda c: abs(0.5 * (c[0] + c[1]) - 1.0))
        flip = ref * (s0 + (s1 - s0) * (0.0 - v0) / (v1 - v0))
    return {"byStrike": rows_out, "total": tot, "callWall": call_wall[0] if call_wall[1] > 0 else None,
            "putWall": put_wall[0] if put_wall[1] < 0 else None, "flip": flip, "n": len(good)}


def put_call(rows: list) -> dict:
    """Intérêt ouvert des calls et des puts (pièces, Decimal exact si les quantités sont des textes) et leur rapport."""
    c = p = ZERO
    for r in rows:
        v = r["oi"] if isinstance(r["oi"], Decimal) else Decimal(repr(r["oi"]))
        if r["kind"] == "C":
            c = CTX.add(c, v)
        else:
            p = CTX.add(p, v)
    return {"calls": c, "puts": p, "ratio": CTX.divide(p, c) if c > 0 else None}
