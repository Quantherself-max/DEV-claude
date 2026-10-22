"""Derives et positionnement multi-bourses (V9), tout en acces public, sans cle ni compte :

  - Deribit : options du BTC / ETH (interet ouvert par strike et echeance -> « max pain », ratio put / call, murs d'options), indice de volatilite implicite DVOL,
    base des futures datees (annualisee) ;
  - Bybit, OKX, Hyperliquid : financement (annualise), interet ouvert en dollars et prix de marque du perpetuel de la paire suivie, pour comparer a Binance.
Pourquoi : un financement tres positif PARTOUT = foule longue (carburant de liquidation) ; une base annualisee elevee = levier en cours ; les strikes d'options chargent
le prix d'aimants (max pain) a l'approche de l'echeance ; le DVOL dit ce que le marche paie pour se couvrir.
Les fonctions de calcul sont PURES (testees sans reseau) ; les classes reseau levent DataError : le hub garde l'erreur et reessaie plus tard.
Format des reponses : documentation publique des bourses ; non verifie ici contre les vrais serveurs (aucun acces) : toute reponse inattendue donne une erreur lisible,
jamais un faux chiffre."""
from __future__ import annotations
import json
import math
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .base import DataError

DERIBIT = "https://www.deribit.com"
BYBIT = "https://api.bybit.com"
OKX = "https://www.okx.com"
HYPER = "https://api.hyperliquid.xyz"
MONTHS = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}
HOUR = 3_600_000
DAY = 86_400_000


def post_json(url: str, payload: dict, timeout: float = 15.0):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "User-Agent": "liq-terminal/9.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        e.close()
        raise DataError(f"HTTP {e.code} ({url.split('?')[0]})") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
        raise DataError(f"injoignable : {url.split('?')[0]} ({type(e).__name__})") from e


def coin_of(symbol: str) -> str:
    """SOLUSDT -> SOL."""
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


# =====================================================================================================
#  Calculs purs
# =====================================================================================================
OPT_RE = re.compile(r"^([A-Z]+)-(\d{1,2})([A-Z]{3})(\d{2})-(\d+(?:\.\d+)?)-([CP])$")
FUT_RE = re.compile(r"^([A-Z]+)-(\d{1,2})([A-Z]{3})(\d{2})$")


def parse_expiry(day: str, mon: str, yy: str) -> int | None:
    """Les echeances Deribit expirent a 08:00 UTC."""
    try:
        return int(datetime(2000 + int(yy), MONTHS[mon], int(day), 8, tzinfo=timezone.utc).timestamp() * 1000)
    except (KeyError, ValueError):
        return None


def parse_option(name: str):
    m = OPT_RE.match(name or "")
    if not m:
        return None
    exp = parse_expiry(m.group(2), m.group(3), m.group(4))
    return None if exp is None else {"coin": m.group(1), "expiry": exp, "strike": float(m.group(5)), "kind": m.group(6)}


def max_pain(oi_by_strike: dict[float, tuple[float, float]]) -> float | None:
    """Strike qui minimise le montant total a payer aux detenteurs d'options a l'echeance. {strike: (oi_calls, oi_puts)}."""
    if not oi_by_strike:
        return None
    strikes = sorted(oi_by_strike)
    best, best_k = None, None
    for k in strikes:
        pay = sum(c * max(0.0, k - s) + p * max(0.0, s - k) for s, (c, p) in oi_by_strike.items())
        if best is None or pay < best:
            best, best_k = pay, k
    return best_k


def options_view(summaries: list[dict], now_ms: int, max_expiries: int = 4) -> dict:
    """Resume des options depuis get_book_summary_by_currency(kind=option) : ratio put/call, max pain et murs par echeance, interet ouvert total en dollars."""
    by_exp: dict[int, dict] = {}
    spot = None
    for s in summaries:
        o = parse_option(s.get("instrument_name", ""))
        oi = num(s.get("open_interest"))
        if not o or oi is None or oi <= 0 or o["expiry"] <= now_ms:
            continue
        up = num(s.get("underlying_price"))
        spot = up or spot
        e = by_exp.setdefault(o["expiry"], {"strikes": {}, "calls": 0.0, "puts": 0.0})
        c, p = e["strikes"].get(o["strike"], (0.0, 0.0))
        e["strikes"][o["strike"]] = (c + oi, p) if o["kind"] == "C" else (c, p + oi)
        e["calls" if o["kind"] == "C" else "puts"] += oi
    if not by_exp or not spot:
        raise DataError("options : aucune échéance exploitable")
    exps = []
    for t in sorted(by_exp)[:max_expiries]:
        e = by_exp[t]
        walls = sorted(((c + p, k, c, p) for k, (c, p) in e["strikes"].items()), reverse=True)[:3]
        exps.append({"expiry": t, "daysLeft": (t - now_ms) / DAY, "maxPain": max_pain(e["strikes"]), "calls": e["calls"], "puts": e["puts"],
                     "putCall": e["puts"] / e["calls"] if e["calls"] > 0 else None, "oiUsd": (e["calls"] + e["puts"]) * spot,
                     "walls": [{"strike": k, "oi": tot, "calls": c, "puts": p} for tot, k, c, p in walls]})
    calls = sum(e["calls"] for e in by_exp.values())
    puts = sum(e["puts"] for e in by_exp.values())
    return {"spot": spot, "putCall": puts / calls if calls > 0 else None, "oiUsd": (calls + puts) * spot, "expiries": exps}


# ---------- V26 : exposition gamma (GEX) des options, BTC ; V38 : plusieurs bourses, choix des echeances, nouveaux niveaux ----------
YEAR_MS = 365.0 * DAY
SQRT2PI = math.sqrt(2.0 * math.pi)
BYBIT_OPT_RE = re.compile(r"^([A-Z]+)-(\d{1,2})([A-Z]{3})(\d{2})-(\d+(?:\.\d+)?)-([CP])(?:-[A-Z]+)?$")     # Bybit : suffixe -USDT possible
OKX_OPT_RE = re.compile(r"^([A-Z]+)-USD-(\d{2})(\d{2})(\d{2})-(\d+(?:\.\d+)?)-([CP])$")                     # OKX : BTC-USD-261030-100000-C
GEX_SRCS = ("all", "deribit")                      # toutes les bourses lues / Deribit seul
GEX_SCOPES = ("all", "week", "front")              # toutes les echeances / 7 prochains jours / prochaine echeance
FRONT_MIN_MS = 2 * HOUR                            # une echeance a moins de 2 heures de sa fin ne compte plus comme « prochaine » : son gamma n'a plus de sens
FLOW_PCTS = (1.0, 2.0, 5.0)


def bs_gamma(f: float, k: float, iv: float, t: float) -> float:
    """Gamma de Black (option sur un sous-jacent a terme, taux nul, comme Deribit) : variation du delta pour 1 unite du prix."""
    if f <= 0 or k <= 0 or iv <= 0 or t <= 0:
        return 0.0
    s = iv * math.sqrt(t)
    d1 = (math.log(f / k) + 0.5 * s * s) / s
    return math.exp(-0.5 * d1 * d1) / (SQRT2PI * f * s)


def _opt_row(ex, strike, kind, oi, iv, f, expiry, now_ms, index=None):
    """Ligne commune a toutes les bourses (iv en fraction : 0,5 = 50 %) ; None si inexploitable."""
    if not oi or oi <= 0 or not iv or iv <= 0 or not f or f <= 0 or not strike or strike <= 0 or expiry is None or expiry <= now_ms:
        return None
    return {"ex": ex, "strike": float(strike), "kind": kind, "oi": float(oi), "iv": float(iv), "f": float(f), "expiry": int(expiry), "index": index}


def norm_deribit(summaries: list[dict], now_ms: int) -> list[dict]:
    """get_book_summary_by_currency(kind=option) : open_interest en BTC, mark_iv en %, underlying_price = prix a terme de l'echeance,
    estimated_delivery_price = indice (le prix du moment)."""
    out = []
    for s in summaries:
        o = parse_option(s.get("instrument_name", ""))
        iv = num(s.get("mark_iv"))
        r = o and _opt_row("Deribit", o["strike"], o["kind"], num(s.get("open_interest")), iv / 100.0 if iv else None, num(s.get("underlying_price")),
                           o["expiry"], now_ms, num(s.get("estimated_delivery_price")))
        if r:
            out.append(r)
    return out


def norm_bybit(items: list[dict], now_ms: int) -> list[dict]:
    """/v5/market/tickers?category=option : symbol BTC-30OCT26-100000-C(-USDT), openInterest en BTC, markIv en fraction, underlyingPrice, indexPrice."""
    out = []
    for it in items or []:
        m = BYBIT_OPT_RE.match(str(it.get("symbol") or ""))
        if not m:
            continue
        iv = num(it.get("markIv"))
        if iv and iv > 5:                                           # au cas ou la volatilite arriverait en %
            iv /= 100.0
        r = _opt_row("Bybit", float(m.group(5)), m.group(6), num(it.get("openInterest")), iv, num(it.get("underlyingPrice")) or num(it.get("indexPrice")),
                     parse_expiry(m.group(2), m.group(3), m.group(4)), now_ms, num(it.get("indexPrice")))
        if r:
            out.append(r)
    return out


def norm_okx(summary: list[dict], oi_rows: list[dict], now_ms: int) -> list[dict]:
    """/api/v5/public/opt-summary (markVol en fraction, fwdPx) + /api/v5/public/open-interest?instType=OPTION (oiCcy : interet ouvert en BTC)."""
    oi_by = {str(r.get("instId")): num(r.get("oiCcy")) for r in oi_rows or []}
    out = []
    for s in summary or []:
        inst = str(s.get("instId") or "")
        m = OKX_OPT_RE.match(inst)
        if not m:
            continue
        try:
            exp = int(datetime(2000 + int(m.group(2)), int(m.group(3)), int(m.group(4)), 8, tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
        r = _opt_row("OKX", float(m.group(5)), m.group(6), oi_by.get(inst), num(s.get("markVol")), num(s.get("fwdPx")), exp, now_ms)
        if r:
            out.append(r)
    return out


def ref_spot(rows: list[dict]) -> float:
    """Prix du moment : mediane des indices recus (Deribit, Bybit), sinon prix a terme de la plus proche echeance."""
    idx = sorted(r["index"] for r in rows if r.get("index"))
    if idx:
        return idx[len(idx) // 2]
    return min(rows, key=lambda r: r["expiry"])["f"]


def atm_iv(rows: list[dict], now_ms: int) -> list[tuple[float, float]]:
    """Volatilite implicite au prix (strike le plus proche du prix a terme, moyenne call / put) pour chaque echeance : [(annees restantes, iv)]."""
    by: dict[int, list] = {}
    for r in rows:
        by.setdefault(r["expiry"], []).append(r)
    out = []
    for e, rs in sorted(by.items()):
        f = rs[0]["f"]
        k = min({r["strike"] for r in rs}, key=lambda x: abs(x - f))
        ivs = [r["iv"] for r in rs if r["strike"] == k]
        out.append(((e - now_ms) / YEAR_MS, sum(ivs) / len(ivs)))
    return out


def expected_moves(rows: list[dict], now_ms: int, spot: float) -> dict | None:
    """Mouvement attendu par les options a 1 jour et 7 jours (un ecart-type) : prix x iv x racine(duree). La volatilite d'une duree est lue
    entre les deux echeances qui l'encadrent (interpolation de la variance totale iv^2 x t, la methode habituelle)."""
    pts = [(t, iv) for t, iv in atm_iv(rows, now_ms) if t * YEAR_MS >= FRONT_MIN_MS]
    if not pts:
        return None
    out = {}
    for key, days in (("day", 1.0), ("week", 7.0)):
        h = days / 365.0
        if h <= pts[0][0]:
            iv = pts[0][1]
        elif h >= pts[-1][0]:
            iv = pts[-1][1]
        else:
            (t0, v0), (t1, v1) = next((a, b) for a, b in zip(pts, pts[1:]) if a[0] <= h <= b[0])
            w = v0 * v0 * t0 + (v1 * v1 * t1 - v0 * v0 * t0) * (h - t0) / (t1 - t0)
            iv = math.sqrt(max(w, 0.0) / h)
        mv = spot * iv * math.sqrt(h)
        out[key] = {"iv": iv, "move": mv, "pct": mv / spot * 100.0, "up": spot + mv, "down": spot - mv}
    return out


def _scales(band: float, grid: int) -> list[float]:
    """Prix testes (en multiple du prix du moment) : grille reguliere sur +/- band, plus fine (0,25 %) sur +/- 6 %, et les pas des flux."""
    s = {round(1 - band + 2 * band * i / (grid - 1), 6) for i in range(grid)}
    s |= {round(1 + j * 0.0025, 6) for j in range(-24, 25)}
    s |= {round(1 + sg * p / 100.0, 6) for p in FLOW_PCTS for sg in (-1, 1)}
    return sorted(s)


def _hedge(curve: list, spot: float, target: float) -> float:
    """Dollars que les teneurs de marche devraient acheter (+) ou vendre (-) pour rester couverts si le prix va de spot a target.
    Le gamma en dollars par 1 % G(p) donne la variation de leur delta en dollars : d(delta$) = G(p) x (dp / p) / 1 % ; ils font l'inverse."""
    lo, hi = min(spot, target), max(spot, target)
    pts = [(p, v) for p, v in curve if lo - 1e-9 <= p <= hi + 1e-9]
    d = sum((v0 + v1) / 2.0 * ((p1 - p0) / ((p0 + p1) / 2.0)) / 0.01 for (p0, v0), (p1, v1) in zip(pts, pts[1:]))
    return -d if target > spot else d


def _flips(curve: list) -> list[float]:
    """Prix ou le gamma total change de signe (les points exactement nuls, loin de tout strike, sont ignores)."""
    pts = [(p, v) for p, v in curve if v != 0]
    return [round(p0 + (p1 - p0) * (0 - v0) / (v1 - v0), 2) for (p0, v0), (p1, v1) in zip(pts, pts[1:]) if (v0 < 0) != (v1 < 0)]


def gex_sets(rows: list[dict], now_ms: int, band: float = 0.25, grid: int = 101) -> dict:
    """Exposition gamma des options pour chaque source (toutes les bourses lues, Deribit seul) et chaque choix d'echeances (toutes, 7 prochains
    jours, prochaine echeance), en une seule passe. Pour chaque option : gamma de Black x interet ouvert x prix^2 x 1 %, soit les dollars que les
    teneurs de marche devraient acheter ou vendre pour rester neutres si le prix bouge de 1 %.
    Convention habituelle (non verifiable) : les teneurs de marche sont ACHETEURS des calls et VENDEURS des puts que le public detient,
    donc calls +, puts -. Gamma total positif au prix : ils vendent les hausses et achetent les baisses (marche amorti, aimante par les gros
    strikes) ; negatif : ils suivent le mouvement (marche amplifie). La bascule (« zero gamma ») est le prix ou le total change de signe.
    Quand le prix « bouge », chaque prix a terme bouge dans la meme proportion et la volatilite de chaque strike reste la meme."""
    good = []
    for r in rows:
        if r["expiry"] <= now_ms:
            continue
        t = max((r["expiry"] - now_ms) / YEAR_MS, 1.0 / (365.0 * 24.0))         # au moins une heure : gamma fini a l'echeance
        good.append((r, r["iv"] * math.sqrt(t)))
    if not good:
        raise DataError("gamma : aucune option exploitable (volatilité implicite ou intérêt ouvert absents)")
    spot = ref_spot([r for r, _ in good])
    def front_of(rs):
        exps = sorted({r["expiry"] for r in rs})
        return next((e for e in exps if e - now_ms >= FRONT_MIN_MS), exps[0]) if exps else None
    fronts = {"all": front_of([r for r, _ in good]), "deribit": front_of([r for r, _ in good if r["ex"] == "Deribit"])}
    scales = _scales(band, grid)
    i1 = scales.index(1.0)
    lg = [math.log(sc) for sc in scales]
    span = max(abs(lg[0]), abs(lg[-1]))
    keys = [(s, c) for s in GEX_SRCS for c in GEX_SCOPES]
    acc = {k: {"curve": [0.0] * len(scales), "by_k": {}, "abs": 0.0, "near": 0.0, "n": 0, "oi": {}, "exps": set()} for k in keys}
    for r, s in good:
        srcs = ("all", "deribit") if r["ex"] == "Deribit" else ("all",)
        week = r["expiry"] - now_ms <= 7 * DAY
        base = math.log(r["f"] / r["strike"]) + 0.5 * s * s
        if abs(base) / s - span / s > 9.0:                               # strike trop loin du prix, meme apres un mouvement de 25 % : gamma nul
            vals = None
        else:
            amp = r["oi"] * r["f"] * 0.01 / (SQRT2PI * s) * (1.0 if r["kind"] == "C" else -1.0)
            vals = [amp * sc * math.exp(-0.5 * ((base + l) / s) ** 2) for sc, l in zip(scales, lg)]
        v0 = vals[i1] if vals else 0.0
        for k in [(a, b) for a in srcs for b in ["all"] + (["week"] if week else []) + (["front"] if r["expiry"] == fronts[a] else [])]:
            a = acc[k]
            if vals:
                c = a["curve"]
                for i, v in enumerate(vals):
                    c[i] += v
            cell = a["by_k"].setdefault(r["strike"], [0.0, 0.0])
            cell[0 if r["kind"] == "C" else 1] += v0
            a["abs"] += abs(v0)
            if r["expiry"] - now_ms <= 7 * DAY:
                a["near"] += abs(v0)
            a["n"] += 1
            a["oi"][r["ex"]] = a["oi"].get(r["ex"], 0.0) + r["oi"]
            a["exps"].add(r["expiry"])
    lo, hi = spot * (1 - band), spot * (1 + band)
    out: dict = {"spot": spot, "front": fronts["all"]}
    for src in GEX_SRCS:
        out[src] = {}
        for sc in GEX_SCOPES:
            a = acc[(src, sc)]
            if not a["n"]:
                out[src][sc] = None
                continue
            curve = [(spot * x, v) for x, v in zip(scales, a["curve"])]
            strikes = [{"strike": k, "calls": c, "puts": p, "net": c + p, "gross": c - p} for k, (c, p) in sorted(a["by_k"].items()) if lo <= k <= hi]
            flips = _flips(curve)
            flip = min(flips, key=lambda x: abs(x - spot)) if flips else None
            # mur de calls : plus forte gamma des calls AU-DESSUS du prix (resistance) ; mur de puts : plus forte gamma des puts EN DESSOUS (support)
            cw = max((x for x in strikes if x["calls"] > 0 and x["strike"] >= spot), key=lambda x: x["calls"], default=None)
            pw = min((x for x in strikes if x["puts"] < 0 and x["strike"] <= spot), key=lambda x: x["puts"], default=None)
            ag = max(strikes, key=lambda x: x["gross"], default=None)          # strike ou se concentre le plus de gamma, calls et puts additionnes
            top = sorted(strikes, key=lambda x: -abs(x["net"]))[:6]
            tot_oi = sum(a["oi"].values())
            out[src][sc] = {
                "spot": spot, "total": a["curve"][i1], "calls": sum(x["calls"] for x in strikes), "puts": sum(x["puts"] for x in strikes),
                "flip": flip, "flips": flips,
                "callWall": cw["strike"] if cw else None, "callWallGex": cw["calls"] if cw else None,
                "putWall": pw["strike"] if pw else None, "putWallGex": pw["puts"] if pw else None,
                "absGamma": ag["strike"] if ag and ag["gross"] > 0 else None, "absGammaGex": ag["gross"] if ag else None,
                "top": [{"strike": x["strike"], "net": x["net"]} for x in sorted(top, key=lambda x: x["strike"])],
                "flows": [{"pct": p, "up": _hedge(curve, spot, spot * (1 + p / 100.0)), "down": _hedge(curve, spot, spot * (1 - p / 100.0))} for p in FLOW_PCTS],
                "strikes": strikes, "curve": [[round(p, 2), v] for p, v in curve], "nearShare": a["near"] / a["abs"] if a["abs"] else None,
                "n": a["n"], "expiries": len(a["exps"]), "frontExpiry": fronts[src] if sc == "front" else None,
                "sources": [{"ex": ex, "oi": v, "share": v / tot_oi if tot_oi else None} for ex, v in sorted(a["oi"].items(), key=lambda x: -x[1])]}
    deri = [r for r, _ in good if r["ex"] == "Deribit"]
    out["em"] = expected_moves(deri or [r for r, _ in good], now_ms, spot)
    return out


def gex_view(summaries: list[dict], now_ms: int, band: float = 0.25, grid: int = 101) -> dict:
    """Gamma de Deribit seul, toutes echeances (forme de la V26, gardee pour les anciens appels et l'enregistreur)."""
    g = gex_sets(norm_deribit(summaries, now_ms), now_ms, band, grid)
    return g["deribit"]["all"]


def futures_basis(summaries: list[dict], now_ms: int) -> list[dict]:
    """Base annualisee des futures datees : (mark / index - 1) x 365 / jours restants. Le perpetuel est renvoye avec son financement."""
    out = []
    for s in summaries:
        name = s.get("instrument_name", "")
        mark, idx = num(s.get("mark_price")), num(s.get("estimated_delivery_price"))
        if not mark or not idx:
            continue
        if name.endswith("PERPETUAL"):
            out.append({"name": name, "perp": True, "basis": mark / idx - 1.0, "funding8h": num(s.get("funding_8h")), "oi": num(s.get("open_interest"))})
            continue
        m = FUT_RE.match(name)
        exp = parse_expiry(*m.group(2, 3, 4)) if m else None
        if exp is None or exp <= now_ms:
            continue
        days = (exp - now_ms) / DAY
        out.append({"name": name, "perp": False, "expiry": exp, "daysLeft": days, "basis": mark / idx - 1.0, "annualized": (mark / idx - 1.0) * 365.0 / days, "oi": num(s.get("open_interest"))})
    return sorted(out, key=lambda r: (not r["perp"], r.get("expiry", 0)))


def dvol_view(rows: list) -> dict:
    """Derniere valeur de l'indice, variation 24 h et 7 jours, rang percentile sur la fenetre recue. rows = [[t, open, high, low, close], ...]."""
    pts = sorted((int(r[0]), float(r[4])) for r in rows if len(r) >= 5 and num(r[4]) is not None)
    if len(pts) < 10:
        raise DataError("DVOL : trop peu de points")
    t, v = pts[-1]
    at = lambda back: next((c for tt, c in reversed(pts) if tt <= t - back), None)
    vals = sorted(c for _, c in pts)
    d1, d7 = at(DAY), at(7 * DAY)
    return {"t": t, "value": v, "chg24h": (v / d1 - 1.0) if d1 else None, "chg7d": (v / d7 - 1.0) if d7 else None, "rank": sum(1 for x in vals if x <= v) / len(vals), "days": (pts[-1][0] - pts[0][0]) / DAY}


def funding_annualized(rate: float, interval_h: float) -> float:
    return rate * (8760.0 / interval_h)


def compare_view(rows: list[dict]) -> dict:
    """Financement et interet ouvert compares. rows = [{ex, funding (par periode), intervalH, oiUsd, mark}] -> moyenne annualisee, ecart, part de chaque bourse."""
    out = [dict(r) for r in rows]
    for r in out:
        r["annualized"] = funding_annualized(r["funding"], r.get("intervalH") or 8.0) if r.get("funding") is not None else None
    ann = [r["annualized"] for r in out if r["annualized"] is not None]
    tot = sum(r["oiUsd"] for r in out if r.get("oiUsd"))
    for r in out:
        r["oiShare"] = (r["oiUsd"] / tot) if tot and r.get("oiUsd") else None
    flag = None
    if ann:
        m = sum(ann) / len(ann)
        flag = "longs" if m > 0.25 and min(ann) > 0.10 else "shorts" if m < -0.10 and max(ann) < -0.02 else None
    return {"rows": out, "meanAnnualized": (sum(ann) / len(ann)) if ann else None, "spread": (max(ann) - min(ann)) if len(ann) > 1 else None, "oiUsd": tot or None, "crowded": flag}


# =====================================================================================================
#  Reseau
# =====================================================================================================
def with_gex(view: dict, rows: list, now_ms: int, others: list | None = None, others_error: str | None = None) -> dict:
    """Ajoute l'exposition gamma au resume des options ; un echec du calcul ne fait jamais perdre le resume.
    others : options deja normalisees des autres bourses (Bybit, OKX : V38) ; gex = Deribit, toutes echeances (forme V26) ;
    gexSets = chaque source et chaque choix d'echeances, plus le mouvement attendu (em)."""
    try:
        sets = gex_sets(norm_deribit(rows, now_ms) + list(others or []), now_ms)
        if sets["deribit"]["all"] is None:
            raise DataError("gamma : aucune option Deribit exploitable")
        view["gex"] = sets["deribit"]["all"]
        view["gexSets"] = sets
    except (DataError, ValueError, ZeroDivisionError, OverflowError) as e:
        view["gexError"] = str(e)
    if others_error:
        view["gexOthersError"] = others_error
    return view


class DerivMixin:
    """Methodes ajoutees aux fournisseurs (RealProviders) ; _get(url) = http_json ; adresses de base : self.deribit, self.bybit, self.okx, self.hyper."""

    def deribit_summary(self, currency: str, kind: str) -> list:
        d = self._get(f"{self.deribit}/api/v2/public/get_book_summary_by_currency?currency={currency}&kind={kind}")
        res = d.get("result") if isinstance(d, dict) else None
        if not isinstance(res, list) or not res:
            raise DataError(f"Deribit {kind} {currency} : réponse inattendue")
        return res

    def deribit_options(self, currency: str, now_ms: int) -> dict:
        rows = self.deribit_summary(currency, "option")
        others, bad = [], []
        if currency == "BTC":                                       # V38 : Bybit et OKX ajoutes au gamma du BTC ; une bourse en panne n'empeche rien
            for fn in (self.options_bybit, self.options_okx):
                try:
                    others += fn(currency, now_ms)
                except (DataError, KeyError, TypeError, ValueError, IndexError, AttributeError) as e:
                    bad.append(f"{fn.__name__[8:]}: {str(e)[:60]}")
        return with_gex(options_view(rows, now_ms), rows, now_ms, others, "; ".join(bad) or None)

    def options_bybit(self, coin: str, now_ms: int) -> list[dict]:
        d = self._get(f"{self.bybit}/v5/market/tickers?category=option&baseCoin={coin}")
        items = (((d or {}).get("result") or {}).get("list")) if isinstance(d, dict) else None
        rows = norm_bybit(items or [], now_ms)
        if not rows:
            raise DataError("Bybit options : réponse inattendue")
        return rows

    def options_okx(self, coin: str, now_ms: int) -> list[dict]:
        s = self._get(f"{self.okx}/api/v5/public/opt-summary?instFamily={coin}-USD")
        o = self._get(f"{self.okx}/api/v5/public/open-interest?instType=OPTION&instFamily={coin}-USD")
        rows = norm_okx((s or {}).get("data") or [], (o or {}).get("data") or [], now_ms)
        if not rows:
            raise DataError("OKX options : réponse inattendue")
        return rows

    def deribit_futures(self, currency: str, now_ms: int) -> list:
        return futures_basis(self.deribit_summary(currency, "future"), now_ms)

    def deribit_dvol(self, currency: str, now_ms: int) -> dict:
        d = self._get(f"{self.deribit}/api/v2/public/get_volatility_index_data?currency={currency}&start_timestamp={now_ms - 14 * DAY}&end_timestamp={now_ms}&resolution=3600")
        data = ((d or {}).get("result") or {}).get("data") if isinstance(d, dict) else None
        if not isinstance(data, list):
            raise DataError("Deribit DVOL : réponse inattendue")
        return dvol_view(data)

    def perp_bybit(self, coin: str) -> dict:
        d = self._get(f"{self.bybit}/v5/market/tickers?category=linear&symbol={coin}USDT")
        rows = (((d or {}).get("result") or {}).get("list")) if isinstance(d, dict) else None
        if not rows:
            raise DataError("Bybit : paire absente")
        r = rows[0]
        mark = num(r.get("markPrice"))
        oi_val = num(r.get("openInterestValue"))
        if oi_val is None and num(r.get("openInterest")) and mark:
            oi_val = num(r["openInterest"]) * mark
        return {"ex": "Bybit", "funding": num(r.get("fundingRate")), "intervalH": num(r.get("fundingIntervalHour")) or 8.0, "oiUsd": oi_val, "mark": mark}

    def perp_okx(self, coin: str) -> dict:
        inst = f"{coin}-USDT-SWAP"
        f = self._get(f"{self.okx}/api/v5/public/funding-rate?instId={inst}")
        o = self._get(f"{self.okx}/api/v5/public/open-interest?instType=SWAP&instId={inst}")
        m = self._get(f"{self.okx}/api/v5/public/mark-price?instType=SWAP&instId={inst}")
        fr = ((f or {}).get("data") or [None])[0]
        oi = ((o or {}).get("data") or [None])[0]
        mk = ((m or {}).get("data") or [None])[0]
        if not fr:
            raise DataError("OKX : paire absente")
        mark = num((mk or {}).get("markPx"))
        oi_usd = num((oi or {}).get("oiUsd")) or ((num((oi or {}).get("oiCcy")) or 0.0) * mark if mark and (oi or {}).get("oiCcy") else None)
        t0, t1 = num(fr.get("fundingTime")), num(fr.get("nextFundingTime"))
        interval = (t1 - t0) / HOUR if t0 and t1 and t1 > t0 else 8.0
        return {"ex": "OKX", "funding": num(fr.get("fundingRate")), "intervalH": interval, "oiUsd": oi_usd, "mark": mark}

    def perp_hyperliquid(self, coin: str) -> dict:
        d = post_json(f"{self.hyper}/info", {"type": "metaAndAssetCtxs"})
        if not (isinstance(d, list) and len(d) == 2 and isinstance(d[0], dict) and isinstance(d[1], list)):
            raise DataError("Hyperliquid : réponse inattendue")
        names = [u.get("name") for u in d[0].get("universe", [])]
        if coin not in names:
            raise DataError(f"Hyperliquid : {coin} absent")
        c = d[1][names.index(coin)]
        mark = num(c.get("markPx"))
        oi = num(c.get("openInterest"))
        return {"ex": "Hyperliquid", "funding": num(c.get("funding")), "intervalH": 1.0, "oiUsd": oi * mark if (oi is not None and mark) else None, "mark": mark}

    def perp_others(self, symbol: str) -> list[dict]:
        """Bybit, OKX, Hyperliquid pour la paire ; une bourse en panne n'empeche pas les autres. Leve DataError si aucune ne repond."""
        coin, got, bad = coin_of(symbol), [], []
        for fn in (self.perp_bybit, self.perp_okx, self.perp_hyperliquid):
            try:
                got.append(fn(coin))
            except (DataError, KeyError, TypeError, ValueError, IndexError) as e:
                bad.append(f"{fn.__name__[5:]}: {str(e)[:60]}")
        if not got:
            raise DataError("; ".join(bad) or "aucune bourse")
        return got


# =====================================================================================================
#  Donnees fictives (mode simule) : meme forme
# =====================================================================================================
class SimDerivMixin:
    def _sim(self, seed: int, lo: float, hi: float) -> float:
        import random
        return random.Random(seed + int(self.now_ms() // 600_000)).uniform(lo, hi)

    def deribit_options(self, currency: str, now_ms: int) -> dict:
        spot = 85000.0 if currency == "BTC" else 3200.0
        step = 1000.0 if currency == "BTC" else 50.0
        summ = []
        for k, days in enumerate((3, 10, 24, 52)):
            exp = datetime.fromtimestamp((now_ms + days * DAY) / 1000, timezone.utc)
            tag = f"{exp.day}{list(MONTHS)[exp.month - 1]}{exp.year % 100}"
            for j in range(-8, 9):
                strike = round(spot / step) * step + j * step * (k + 1)
                for kind, w in (("C", 1.0 if j >= 0 else 0.4), ("P", 1.0 if j <= 0 else 0.4)):
                    bump = 1.0
                    if currency == "BTC":                                # V38 : murs nets pour que le dessin simule ressemble a un vrai marche
                        bump = {(90000.0, "C"): 2.5, (88000.0, "C"): 4.0, (80000.0, "P"): 2.5, (82000.0, "P"): 4.0}.get((strike, kind), 1.0)
                    summ.append({"instrument_name": f"{currency}-{tag}-{int(strike)}-{kind}", "open_interest": bump * w * (300 - 25 * abs(j)) * (1 + 0.1 * k),
                                 "underlying_price": spot * (1 + 0.0004 * days), "mark_iv": 48.0 + 1.2 * abs(j) + (3.0 if kind == "P" and j < 0 else 0.0),
                                 "estimated_delivery_price": spot})
        others = []
        if currency == "BTC":                                       # V38 : Bybit et OKX simules (environ 12 % et 9 % de l'interet ouvert de Deribit)
            for r in norm_deribit(summ, now_ms):
                for ex, share, dv in (("Bybit", 0.12, 0.01), ("OKX", 0.09, -0.005)):
                    others.append({**r, "ex": ex, "oi": r["oi"] * share * (1.3 if r["kind"] == "P" and ex == "OKX" else 1.0), "iv": r["iv"] + dv, "index": None})
        return with_gex(options_view(summ, now_ms), summ, now_ms, others)

    def deribit_futures(self, currency: str, now_ms: int) -> list:
        spot = 85000.0
        out = [{"instrument_name": f"{currency}-PERPETUAL", "mark_price": spot * 1.0002, "estimated_delivery_price": spot, "funding_8h": 0.00012, "open_interest": 1.2e9}]
        for days in (30, 90):
            exp = datetime.fromtimestamp((now_ms + days * DAY) / 1000, timezone.utc)
            out.append({"instrument_name": f"{currency}-{exp.day}{list(MONTHS)[exp.month - 1]}{exp.year % 100}", "mark_price": spot * (1 + 0.0035 * days / 30), "estimated_delivery_price": spot, "open_interest": 4e8})
        return futures_basis(out, now_ms)

    def deribit_dvol(self, currency: str, now_ms: int) -> dict:
        rows = [[now_ms - (240 - i) * HOUR, 0, 0, 0, 52 + 6 * math.sin(i / 20.0)] for i in range(241)]
        return dvol_view(rows)

    def perp_others(self, symbol: str) -> list[dict]:
        base = 0.00008 + self._sim(sum(map(ord, symbol)), -0.00003, 0.00004)
        return [{"ex": "Bybit", "funding": base * 1.1, "intervalH": 8.0, "oiUsd": 6.1e8, "mark": 190.0},
                {"ex": "OKX", "funding": base * 0.9, "intervalH": 8.0, "oiUsd": 4.0e8, "mark": 190.0},
                {"ex": "Hyperliquid", "funding": base / 8.0 * 1.3, "intervalH": 1.0, "oiUsd": 2.2e8, "mark": 190.0}]
