"""GEX (exposition gamma des teneurs de marché) à partir d'une chaîne d'options. Module PUR.

Idée : les teneurs de marché couvrent les options qu'ils portent. Convention usuelle des sites de GEX : gamma des calls compté +, gamma des
puts compté −. Gamma total positif : les couvertures achètent les baisses et vendent les hausses (marché qui « colle », amplitude réduite) ;
négatif : elles vendent les baisses et achètent les hausses (marché qui « accélère »).

Par option : GEX ($ par mouvement de 1 %) = gamma × intérêt ouvert × multiplicateur (100) × S² × 1 %.
On en tire, par prix d'exercice (strike) :
  - CALL WALL : le strike au plus gros GEX des calls (résistance fréquente) ; PUT WALL : le plus gros GEX des puts (support fréquent) ;
  - ZÉRO GAMMA (« gamma flip », souvent appelé HVL) : le niveau du sous-jacent où le gamma total change de signe. On le trouve en recalculant
    le gamma de chaque option (Black-Scholes, avec SA volatilité implicite et SON échéance) sur une grille de niveaux autour du prix ;
  - les strikes au plus gros GEX net (positif ou négatif) : les « niveaux GEX ».
Les niveaux sont ensuite ramenés au prix du future NQ par le rapport NQ / sous-jacent (NDX ou QQQ) au moment des données.

Limites : intérêt ouvert publié une fois par jour (celui de la veille) ; données d'options différées ; le sens réel des positions des teneurs
n'est pas connu (c'est une convention). À lire comme une carte, pas comme une certitude."""
import math
import re
from datetime import date, datetime, timezone

from . import clock

SYM = re.compile(r"^([A-Z]+?)(\d{6})([CP])(\d{8})$")
YEAR = 365.0 * 24 * 3600 * 1000


def parse_symbol(sym: str):
    """« QQQ261120C00500000 » -> (racine, échéance AAAA-MM-JJ, 'C'|'P', strike). None si le format n'est pas reconnu."""
    m = SYM.match(str(sym).strip().upper())
    if not m:
        return None
    root, ymd, cp, k = m.groups()
    try:
        exp = date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6])).isoformat()
    except ValueError:
        return None
    return root, exp, cp, int(k) / 1000.0


def bs_gamma(s: float, k: float, t: float, iv: float, r: float = 0.0, q: float = 0.0) -> float:
    if s <= 0 or k <= 0 or t <= 0 or iv <= 0:
        return 0.0
    v = iv * math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * iv * iv) * t) / v
    return math.exp(-q * t) * math.exp(-0.5 * d1 * d1) / (math.sqrt(2 * math.pi) * s * v)


def _num(d, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            try:
                x = float(d[k])
                if math.isfinite(x):
                    return x
            except (TypeError, ValueError):
                pass
    return None


def expiry_ms(exp: str) -> int:
    """Échéance : 16 h ET du jour d'expiration (règlement de fin de séance ; les mensuelles NDX se règlent à l'ouverture, écart négligeable ici)."""
    y, m, d = (int(x) for x in exp.split("-"))
    return clock.et_to_utc(y, m, d, 16, 0)


def chain_from_json(js: dict, now_ms: int) -> dict:
    """Chaîne d'options depuis le JSON des cotations différées (format CBOE : data.options[] avec « option », « open_interest », « iv »,
    « gamma » ; data.current_price). Tolérant : clés alternatives acceptées, lignes illisibles ignorées. Lève ValueError si rien n'est lisible."""
    data = js.get("data", js) if isinstance(js, dict) else {}
    opts = data.get("options") or data.get("option_chain") or []
    spot = _num(data, "current_price", "last", "close", "price")
    asof = now_ms
    ts = (js.get("timestamp") if isinstance(js, dict) else None) or data.get("timestamp") or data.get("last_trade_time")
    if ts:
        try:
            d = datetime.fromisoformat(str(ts).replace("Z", "+00:00").replace(" ", "T"))
            asof = int((d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp() * 1000)
        except ValueError:
            pass
    out, root0 = [], None
    for o in opts if isinstance(opts, list) else []:
        if not isinstance(o, dict):
            continue
        ps = parse_symbol(o.get("option") or o.get("symbol") or "")
        if not ps:
            continue
        root, exp, cp, k = ps
        root0 = root0 or root
        oi = _num(o, "open_interest", "openInterest", "oi") or 0.0
        t = (expiry_ms(exp) - now_ms) / YEAR
        if t <= -1 / 365.0:                                   # échue
            continue
        out.append({"strike": k, "type": cp, "exp": exp, "t": max(t, 1.0 / (365 * 24)), "oi": oi,
                    "iv": _num(o, "iv", "implied_volatility", "impliedVolatility") or 0.0,
                    "gamma": _num(o, "gamma") or 0.0, "volume": _num(o, "volume") or 0.0})
    if not out:
        raise ValueError("aucune option lisible dans les données")
    if spot is None:
        raise ValueError("prix du sous-jacent absent des données")
    return {"underlying": (data.get("symbol") or root0 or "").lstrip("_"), "spot": spot, "asof": asof, "options": out}


def _gamma_at(o, s):
    return bs_gamma(s, o["strike"], o["t"], o["iv"]) if o["iv"] > 0 else 0.0


def compute(chain: dict, mult: float = 100.0, band: float = 0.10, grid: int = 61, max_days: float = 90.0, top: int = 5) -> dict:
    """Profil GEX par strike, murs, zéro gamma, profil du gamma total selon le niveau du sous-jacent."""
    s0 = chain["spot"]
    opts = [o for o in chain["options"] if o["oi"] > 0 and o["t"] * 365 <= max_days and abs(o["strike"] / s0 - 1) <= 0.25]
    by = {}
    for o in opts:
        g = o["gamma"] if o["gamma"] > 0 else _gamma_at(o, s0)       # gamma fourni par la source si présent, sinon recalculé
        gex = g * o["oi"] * mult * s0 * s0 * 0.01 * (1 if o["type"] == "C" else -1)
        a = by.setdefault(o["strike"], {"strike": o["strike"], "call": 0.0, "put": 0.0, "callOi": 0.0, "putOi": 0.0, "dte0": 0.0})
        if o["type"] == "C":
            a["call"] += gex
            a["callOi"] += o["oi"]
        else:
            a["put"] += gex
            a["putOi"] += o["oi"]
        if o["t"] * 365 < 1.0:
            a["dte0"] += gex
    rows = sorted(by.values(), key=lambda a: a["strike"])
    for a in rows:
        a["net"] = a["call"] + a["put"]
    near = [a for a in rows if abs(a["strike"] / s0 - 1) <= band]
    total = sum(a["net"] for a in rows)
    call_wall = max(near, key=lambda a: a["call"])["strike"] if near and max(a["call"] for a in near) > 0 else None
    put_wall = min(near, key=lambda a: a["put"])["strike"] if near and min(a["put"] for a in near) < 0 else None
    # profil du gamma total en fonction du niveau du sous-jacent (Black-Scholes, vol. implicite de chaque option)
    lv = [s0 * (1 - band + 2 * band * i / (grid - 1)) for i in range(grid)]
    curve = []
    with_iv = [o for o in opts if o["iv"] > 0]
    for s in lv:
        tot = 0.0
        for o in with_iv:
            tot += _gamma_at(o, s) * o["oi"] * mult * s * s * 0.01 * (1 if o["type"] == "C" else -1)
        curve.append((s, tot))
    zero = None
    best = None
    for (s1, g1), (s2, g2) in zip(curve, curve[1:]):
        if g1 == 0 or (g1 < 0) != (g2 < 0):
            x = s1 if g1 == 0 else s1 + (s2 - s1) * (-g1) / (g2 - g1)
            if best is None or abs(x - s0) < best:
                zero, best = x, abs(x - s0)
    majors = sorted(near, key=lambda a: -abs(a["net"]))[:top]
    return {"spot": s0, "total": total, "callWall": call_wall, "putWall": put_wall, "zeroGamma": zero,
            "regime": "positif" if total > 0 else "négatif", "dte0Share": (sum(abs(a["dte0"]) for a in rows) / sum(abs(a["net"]) for a in rows))
            if rows and sum(abs(a["net"]) for a in rows) > 0 else 0.0,
            "majors": [a["strike"] for a in majors], "strikes": near, "curve": curve, "nOptions": len(opts)}


def to_nq(res: dict, ratio: float) -> dict:
    """Ramène les niveaux d'un résultat `compute` au prix du NQ (× rapport NQ / sous-jacent)."""
    f = lambda x: None if x is None else round(round(x * ratio * 4) / 4, 2)
    lv = []
    for name, key, kind in (("Call wall", "callWall", "gcall"), ("Put wall", "putWall", "gput"), ("Zéro gamma (HVL)", "zeroGamma", "gzero")):
        if res.get(key) is not None:
            lv.append({"name": name, "price": f(res[key]), "kind": kind, "src": round(res[key], 2)})
    for k in res.get("majors", []):
        if k not in (res.get("callWall"), res.get("putWall")):
            a = next(x for x in res["strikes"] if x["strike"] == k)
            lv.append({"name": f"GEX {'+' if a['net'] > 0 else '−'} {k:g}", "price": f(k), "kind": "gpos" if a["net"] > 0 else "gneg", "src": k})
    return {"levels": lv, "strikes": [{"price": f(a["strike"]), "strike": a["strike"], "call": a["call"], "put": a["put"], "net": a["net"],
                                       "callOi": a["callOi"], "putOi": a["putOi"]} for a in res["strikes"]]}
