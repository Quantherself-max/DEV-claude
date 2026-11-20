"""Baleines des options et variations de l'intérêt ouvert (V51). Module PUR : aucun réseau.

Baleines : les transactions d'options de Deribit sont regroupées en ORDRES :
  - un bloc négocié (même `block_trade_id`) ou un combo (même `combo_trade_id`) : toutes ses jambes ensemble ;
  - sinon, les exécutions d'un même ordre au carnet : même instrument, même sens, même milliseconde.
Un ordre est une baleine quand son notionnel (contrats × prix de l'indice, 1 contrat = 1 BTC) atteint le seuil (1 million de dollars par
défaut). Le SENS est celui de l'initiateur (le preneur : celui qui traverse le carnet, ou qui demande le bloc). On ne sait pas s'il ouvre
ou ferme une position : la variation de l'intérêt ouvert de l'instrument le dit à l'échelle de la journée.

Pour chaque ordre :
  - la stratégie reconnue d'après ses jambes (achat / vente de call ou de put, spreads, straddle, strangle, risk reversal, calendrier,
    papillon, condor) ;
  - la prime nette payée (positive) ou reçue (négative), en dollars : sens × prix (en BTC) × contrats × indice ;
  - le delta net en BTC (modèle de Black avec la volatilité implicite de chaque exécution et le prix de l'indice comme prix à terme :
    une estimation, le prix à terme exact de l'échéance n'est pas dans la transaction) : positif = l'initiateur gagne à la hausse ;
  - le vega net en dollars par point de volatilité : positif = il achète de la volatilité.

Variations de l'intérêt ouvert : deux photos {instrument: contrats ouverts} ; différence par instrument, sans les instruments arrivés à
échéance entre les deux photos (leur disparition n'est pas une fermeture)."""
from __future__ import annotations
import calendar
import re

from . import options as qopt

MONTHS = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"))}
NAME_RE = re.compile(r"^([A-Z]+)(?:_[A-Z]+)?-(\d{1,2})([A-Z]{3})(\d{2})-(\d+(?:d\d+)?)-([CP])$")
WHALE_USD = 1_000_000.0
DAY = 86_400_000
SINGLE = {("C", 1): ("Achat de call", "pari haussier"),
          ("C", -1): ("Vente de call", "plafond : ne croit pas à une forte hausse, encaisse la prime"),
          ("P", 1): ("Achat de put", "protection ou pari baissier"),
          ("P", -1): ("Vente de put", "prêt à acheter plus bas : haussier ou neutre, encaisse la prime")}


def parse_name(name: str):
    """« BTC-27NOV26-60000-P » -> {coin, expiry (ms, 08 h 00 UTC), strike, kind 'C' / 'P'} ; None si le nom n'est pas une option."""
    m = NAME_RE.match(name or "")
    if not m:
        return None
    coin, d, mon, yy, k, kind = m.groups()
    if mon not in MONTHS:
        return None
    exp = calendar.timegm((2000 + int(yy), MONTHS[mon], int(d), 8, 0, 0)) * 1000
    return {"coin": coin, "expiry": exp, "strike": float(k.replace("d", ".")), "kind": kind}


def leg_of(t: dict):
    """Transaction Deribit -> jambe : {t, name, kind, strike, expiry, dir (+1 achat, -1 vente), amount, price (BTC), index, iv, id}."""
    meta = parse_name(t.get("instrument_name"))
    if meta is None:
        return None
    return {"t": int(t["timestamp"]), "name": t["instrument_name"], "kind": meta["kind"], "strike": meta["strike"], "expiry": meta["expiry"],
            "dir": 1 if t.get("direction") == "buy" else -1, "amount": float(t.get("amount") or 0.0), "price": float(t.get("price") or 0.0),
            "index": float(t.get("index_price") or 0.0), "iv": float(t["iv"]) / 100.0 if t.get("iv") else None,
            "id": str(t.get("trade_id")), "liq": bool(t.get("liquidation")),
            "group": t.get("block_trade_id") or t.get("combo_trade_id") or None}


def group_key(leg: dict) -> str:
    return "B:" + str(leg["group"]) if leg["group"] else f"O:{leg['name']}:{leg['dir']}:{leg['t']}"


def merge_legs(legs: list) -> list:
    """Exécutions d'un même instrument et d'un même sens dans un ordre -> une jambe (contrats additionnés, prix et volatilité moyens
    pondérés par les contrats)."""
    by = {}
    for g in legs:
        k = (g["name"], g["dir"])
        if k not in by:
            by[k] = {**g, "_pv": g["price"] * g["amount"], "_iv": (g["iv"] or 0.0) * g["amount"], "_ivn": g["amount"] if g["iv"] else 0.0}
        else:
            b = by[k]
            b["amount"] += g["amount"]
            b["_pv"] += g["price"] * g["amount"]
            if g["iv"]:
                b["_iv"] += g["iv"] * g["amount"]
                b["_ivn"] += g["amount"]
            b["liq"] = b["liq"] or g["liq"]
    out = []
    for b in by.values():
        a = b["amount"] or 1.0
        out.append({k: v for k, v in b.items() if not k.startswith("_")} | {"price": b["_pv"] / a, "iv": (b["_iv"] / b["_ivn"]) if b["_ivn"] else None})
    return sorted(out, key=lambda g: (g["expiry"], g["kind"], g["strike"]))


def greeks_of(leg: dict, t_ms: int):
    """(delta, vega) d'UN contrat de la jambe, au moment de la transaction ; (None, None) sans volatilité."""
    tt = qopt.years(leg["expiry"], t_ms)
    if not leg["iv"] or leg["index"] <= 0 or tt <= qopt.MIN_T:
        return None, None
    g = qopt.greeks(leg["kind"], leg["index"], leg["strike"], leg["iv"], tt)
    return g["delta"], g["vega"]


def classify(legs: list) -> dict:
    """Nom de la stratégie et ce qu'elle dit, d'après les jambes (triées par échéance, type, strike)."""
    n = len(legs)
    K = {"C": "call", "P": "put"}
    if n == 1:
        g = legs[0]
        name, reading = SINGLE[(g["kind"], g["dir"])]
        return {"name": name, "reading": reading}
    same_exp = len({g["expiry"] for g in legs}) == 1
    kinds = {g["kind"] for g in legs}
    eq = len({round(g["amount"], 6) for g in legs}) == 1
    if n == 2:
        a, b = legs
        if same_exp and a["kind"] == b["kind"] and a["dir"] != b["dir"] and a["strike"] != b["strike"]:
            lo, hi = (a, b) if a["strike"] < b["strike"] else (b, a)
            r = " 1x2" if not eq else ""
            if a["kind"] == "C":
                return {"name": "Call spread acheteur" + r, "reading": "haussier, gain plafonné"} if lo["dir"] > 0 else \
                    {"name": "Call spread vendeur" + r, "reading": "ne croit pas à une hausse au-delà du strike vendu"}
            return {"name": "Put spread acheteur" + r, "reading": "baissier ou protection, gain plafonné"} if hi["dir"] > 0 else \
                {"name": "Put spread vendeur" + r, "reading": "ne croit pas à une baisse sous le strike vendu"}
        if same_exp and kinds == {"C", "P"}:
            c = a if a["kind"] == "C" else b
            p = b if c is a else a
            if c["dir"] == p["dir"]:
                nm = "straddle" if c["strike"] == p["strike"] else "strangle"
                return {"name": ("Achat de " if c["dir"] > 0 else "Vente de ") + nm,
                        "reading": "pari sur un gros mouvement, dans un sens ou l'autre" if c["dir"] > 0 else "pari sur un marché calme, dans une fourchette"}
            return {"name": "Risk reversal haussier", "reading": "achète la hausse, financée en vendant la baisse"} if c["dir"] > 0 else \
                {"name": "Risk reversal baissier", "reading": "achète la protection, financée en vendant la hausse (collar s'il détient des BTC)"}
        if not same_exp and a["kind"] == b["kind"] and a["strike"] == b["strike"] and a["dir"] != b["dir"]:
            near, far = (a, b) if a["expiry"] < b["expiry"] else (b, a)
            return {"name": f"Calendrier de {K[a['kind']]}s" + (" (report)" if far["dir"] > 0 else ""),
                    "reading": "repousse sa position sur une échéance plus lointaine" if far["dir"] > 0 else "rapproche sa position sur l'échéance proche"}
        if not same_exp and a["kind"] == b["kind"] and a["dir"] != b["dir"]:
            return {"name": f"Diagonale de {K[a['kind']]}s", "reading": "change d'échéance et de strike"}
    if n == 3 and same_exp and len(kinds) == 1 and eq:
        a, b, c = sorted(legs, key=lambda g: g["strike"])
        if a["kind"] == "P" and (a["dir"], b["dir"], c["dir"]) == (-1, -1, 1):
            return {"name": "Échelle de puts (put ladder)", "reading": "baissier jusqu'au strike du milieu, mais exposé si la baisse va sous le plus bas strike"}
        if a["kind"] == "C" and (a["dir"], b["dir"], c["dir"]) == (1, -1, -1):
            return {"name": "Échelle de calls (call ladder)", "reading": "haussier jusqu'au strike du milieu, mais exposé si la hausse dépasse le plus haut strike"}
    if n == 3 and same_exp and len(kinds) == 1:
        a, b, c = legs
        if a["dir"] == c["dir"] != b["dir"] and abs(b["amount"] - 2 * a["amount"]) < 1e-6 and abs(a["amount"] - c["amount"]) < 1e-6:
            return {"name": f"Papillon de {K[a['kind']]}s " + ("acheteur" if a["dir"] > 0 else "vendeur"),
                    "reading": f"vise une clôture vers {b['strike']:,.0f} à l'échéance".replace(",", " ") if a["dir"] > 0 else "parie que le prix s'éloignera du strike central"}
    if n == 4 and same_exp and kinds == {"C", "P"}:
        ps, cs = [g for g in legs if g["kind"] == "P"], [g for g in legs if g["kind"] == "C"]
        if len(ps) == 2 and len(cs) == 2:
            pin, pout = max(ps, key=lambda g: g["strike"]), min(ps, key=lambda g: g["strike"])
            cin, cout = min(cs, key=lambda g: g["strike"]), max(cs, key=lambda g: g["strike"])
            if pin["dir"] == cin["dir"] == -pout["dir"] == -cout["dir"]:
                return {"name": "Iron condor " + ("vendeur" if pin["dir"] < 0 else "acheteur"),
                        "reading": "pari sur un marché calme entre les strikes vendus" if pin["dir"] < 0 else "pari sur une sortie de la fourchette"}
    what = "calls" if kinds == {"C"} else "puts" if kinds == {"P"} else "calls et puts"
    return {"name": f"Stratégie à {n} jambes ({what})", "reading": "lire le delta et le vega nets", "generic": True}


def build_order(legs: list, block: bool) -> dict:
    """Ordre (une ou plusieurs jambes) -> ligne de baleine."""
    t = min(g["t"] for g in legs)
    lg = merge_legs(legs)
    idx = next((g["index"] for g in lg if g["index"] > 0), 0.0)
    notional = sum(g["amount"] * (g["index"] or idx) for g in lg)
    premium = sum(g["dir"] * g["price"] * g["amount"] * (g["index"] or idx) for g in lg)
    nd = nv = 0.0
    known = True
    for g in lg:
        d, v = greeks_of(g, t)
        if d is None:
            known = False
            continue
        nd += g["dir"] * g["amount"] * d
        nv += g["dir"] * g["amount"] * v
    c = classify(lg)
    if c.get("generic") and known:                                   # structure sans nom usuel : on dit ce qu'elle fait
        size = sum(g["amount"] for g in lg) or 1.0
        sens = "neutre sur le sens" if abs(nd) / size < 0.1 else ("haussière" if nd > 0 else "baissière")
        vol = "achète de la volatilité" if nv > 0 else "vend de la volatilité" if nv < 0 else ""
        c = {"name": c["name"].replace("Stratégie", "Structure"), "reading": sens + (", " + vol if vol else "")}
    return {"t": t, "block": block, "legs": [{"name": g["name"], "kind": g["kind"], "strike": g["strike"], "expiry": g["expiry"], "dir": g["dir"],
                                               "amount": round(g["amount"], 4), "price": g["price"], "iv": g["iv"], "liq": g["liq"]} for g in lg],
            "index": idx, "contracts": round(sum(g["amount"] for g in lg), 4), "notional": notional, "premium": premium,
            "delta": nd, "vega": nv, "greeksComplete": known, "name": c["name"], "reading": c["reading"],
            "liq": any(g["liq"] for g in lg)}


class Grouper:
    """Regroupe des transactions arrivant page par page (triées par heure croissante) en ordres. Un ordre n'est rendu qu'une fois
    complet : quand une transaction plus récente que sa dernière jambe est vue (les jambes d'un bloc ont la même heure)."""

    def __init__(self, min_usd: float = WHALE_USD):
        self.min_usd = min_usd
        self.open: dict = {}
        self.seen: set = set()

    def feed(self, trades: list) -> list:
        """Ajoute des transactions brutes ; renvoie les baleines devenues complètes."""
        last_t = None
        for raw in trades:
            tid = str(raw.get("trade_id"))
            if tid in self.seen:
                continue
            self.seen.add(tid)
            g = leg_of(raw)
            if g is None or g["amount"] <= 0:
                continue
            self.open.setdefault(group_key(g), []).append(g)
            last_t = g["t"] if last_t is None else max(last_t, g["t"])
        if last_t is None:
            return []
        return self._flush(lambda legs: max(x["t"] for x in legs) < last_t)

    def finish(self) -> list:
        return self._flush(lambda legs: True)

    def _flush(self, done) -> list:
        out = []
        for k in [k for k, legs in self.open.items() if done(legs)]:
            legs = self.open.pop(k)
            idx = next((g["index"] for g in legs if g["index"] > 0), 0.0)
            if sum(g["amount"] for g in legs) * idx >= self.min_usd:
                out.append(build_order(legs, k.startswith("B:")))
        if len(self.seen) > 200_000:                                       # mémoire bornée : seuls les identifiants récents servent
            self.seen = set(list(self.seen)[-50_000:])
        return out


def oi_changes(cur: dict, old: dict, now_ms: int, index: float | None = None, top: int = 6) -> dict:
    """Variations de l'intérêt ouvert (contrats) entre deux photos {instrument: contrats}. Les instruments échus sont écartés."""
    rows = []
    for name in set(cur) | set(old):
        meta = parse_name(name)
        if meta is None or meta["expiry"] <= now_ms:
            continue
        d = float(cur.get(name, 0.0)) - float(old.get(name, 0.0))
        if abs(d) < 1e-9:
            continue
        rows.append({"name": name, "kind": meta["kind"], "strike": meta["strike"], "expiry": meta["expiry"], "change": d,
                     "oi": float(cur.get(name, 0.0)), "usd": d * index if index else None})
    calls = sum(r["change"] for r in rows if r["kind"] == "C")
    puts = sum(r["change"] for r in rows if r["kind"] == "P")
    up = sorted([r for r in rows if r["change"] > 0], key=lambda r: -r["change"])[:top]
    dn = sorted([r for r in rows if r["change"] < 0], key=lambda r: r["change"])[:top]
    return {"up": up, "down": dn, "calls": calls, "puts": puts, "n": len(rows)}


def summarize(orders: list, now_ms: int, hours: int = 24) -> dict:
    """Totaux des baleines sur les dernières `hours` heures : nombre, notionnel, delta net, vega net, primes payées en calls et en puts."""
    sel = [o for o in orders if o["t"] >= now_ms - hours * 3_600_000]
    paid_c = sum(g["dir"] * g["price"] * g["amount"] * o["index"] for o in sel for g in o["legs"] if g["kind"] == "C")
    paid_p = sum(g["dir"] * g["price"] * g["amount"] * o["index"] for o in sel for g in o["legs"] if g["kind"] == "P")
    return {"n": len(sel), "blocks": sum(1 for o in sel if o["block"]), "notional": sum(o["notional"] for o in sel),
            "delta": sum(o["delta"] for o in sel), "vega": sum(o["vega"] for o in sel), "premiumCalls": paid_c, "premiumPuts": paid_p,
            "bull": sum(1 for o in sel if o["delta"] > 0), "bear": sum(1 for o in sel if o["delta"] < 0)}
