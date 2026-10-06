"""Idees de trade (V5) : on ne garde que les configurations rares, construites sur TROIS piliers :
  1. la LIQUIDITE : poche de liquidations dans la zone ou juste au-dela, poche deja balayee, grosse poche en face comme objectif ;
  2. les VWAP et VWAP ancres (et, en renfort, profils de volume, ouvertures, plus hauts / plus bas, POC nus) ;
  3. le CONTEXTE MACRO : lecture des actifs de reference, annonces a venir (consensus), reaction aux annonces passees.

Principe
- On part des zones de confluence deja calculees et on donne a chaque source un POIDS selon son echelle de temps :
  heure < jour < semaine < mois < annee. Un VWAP annuel pese quatre fois plus qu'un VWAP du jour. VWAP et VWAP ancres sont
  bonifies (x1,6), les profils de volume (x1,2), les ouvertures et plus hauts / bas pesent un peu moins.
- Une idee est un retournement sur une zone : achat sur un support, vente sur une resistance.
    « rebond »  : ordre a cours limite sur le bord de la zone ;
    « reprise » : la zone (ou une poche de liquidation proche) a ete balayee puis reprise : le piege est joue.
- Chaque idee a un stop (au-dela de la zone, de ses poches et de la meche du balayage), un premier objectif (prochain niveau
  important ou grosse poche, au moins 1,5 fois le risque) et un second objectif.
- Le score sur 100 combine : liquidite (30), VWAP / VWAP ancres et niveaux superposes (30), macro et annonces (20), flux
  d'ordres (8), tendance de fond (7), biais et dominance (5). FILTRES : il faut de la liquidite (6 points au moins) et une macro
  qui ne va pas nettement contre l'idee. Rien n'est envoye sous le seuil, et au plus 5 idees par semaine.

Ce module est PUR : il ne lit ni reseau ni disque. Le rejeu historique (sigtest.py) utilise la meme construction
d'idees pour mesurer ce que la structure des niveaux aurait donne depuis 2019."""
import math
import re

# ---------- constantes ----------
TFW = {1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0}                      # jour, semaine, mois, annee
TF_NAME = {0: "heure", 1: "jour", 2: "semaine", 3: "mois", 4: "année"}
EMPH = {"vwap": 1.6, "avwap": 1.6, "vp": 1.2, "band": 1.1, "hl": 0.9, "open": 0.8, "npoc": 1.0, "round": 0.4}
PER = {"D": 1, "W": 2, "M": 3, "Y": 4}
PERIOD_OF = {}
for _l in "dwmy":
    PERIOD_OF[f"{_l}VWAP"] = (_l.upper(), "vwap", False)
    PERIOD_OF[f"{_l}Open"] = (_l.upper(), "open", False)
    PERIOD_OF[f"{_l}VP"] = (_l.upper(), "vp", False)
    PERIOD_OF[f"p{_l}VP"] = (_l.upper(), "vp", True)
    PERIOD_OF[f"P{_l.upper()}HL"] = (_l.upper(), "hl", True)

CUR = {"D": "du jour", "W": "de la semaine", "M": "du mois", "Y": "de l'année"}
PREV = {"D": "de la veille", "W": "de la semaine dernière", "M": "du mois dernier", "Y": "de l'année dernière"}
VP_WHAT = {"POC": "point de contrôle (prix où il s'est échangé le plus de volume)", "VAH": "bord haut de la zone de valeur (70 % du volume)",
           "VAL": "bord bas de la zone de valeur (70 % du volume)", "HVN": "zone très échangée (nœud de volume)"}

DEFAULTS = {
    "min_struct": 7.0,        # qualite minimale de la zone (somme des poids des sources)
    "min_htf": 2,             # sources d'echelle >= semaine
    "min_sources": 3,         # sources distinctes (hors nombres ronds et poches)
    "max_dist_atr": 4.0,      # prix a moins de 4 amplitudes d'heure de l'entree (ordre limite realiste)
    "min_rr1": 1.5,           # premier objectif >= 1,5 fois le risque
    "risk_min_atr": 1.5,      # stop au moins a 1,5 amplitude d'heure de l'entree (sinon il est balaye par le bruit : on l'elargit)
    "risk_max_atr": 6.0,      # au-dela, le stop est trop loin : le rapport gain / risque devient mauvais
    "target_min_struct": 4.0,
    "valid_hours": 48,
    "sweep_hours": 8,
    "recent_hours": 10,       # fenetre de recherche d'une meche qui perce la zone puis la reprend
    "leverage": 10.0,
    "min_liq_pts": 6.0,       # filtre : points de liquidite minimaux (sur 30)
    "min_macro_pts": 5.0,     # filtre : points de macro minimaux (sur 20) ; en dessous, la macro va nettement contre l'idee
    "trend_gate": True,       # filtre : seulement les idees dans le sens de la tendance de fond (moyennes 50 j et 200 j), seul filtre valide par le backtest
}


# ---------- formats ----------
def fmt_price(p):
    if p is None:
        return "-"
    s = f"{p:,.0f}" if abs(p) >= 1000 else f"{p:,.2f}" if abs(p) >= 1 else f"{p:.4f}"
    return s.replace(",", " ").replace(".", ",") if abs(p) < 1000 else s.replace(",", " ")


def fmt_pct(x, d=2, sign=False):
    if x is None:
        return "-"
    s = f"{x:+.{d}f}" if sign else f"{x:.{d}f}"
    return s.replace(".", ",") + " %"


def fmt_num(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


def week_start(now_ms: int) -> int:
    """Debut (ms) de la semaine en cours : lundi 00:00 UTC."""
    day = now_ms // 86_400_000
    return ((day + 3) // 7 * 7 - 3) * 86_400_000


# ---------- poids des sources ----------
def _days_tf(d):
    return 1 if d <= 3 else 2 if d <= 14 else 3 if d <= 100 else 4


def _vp_label(lbl: str) -> str:
    """« VP 30j » -> « sur 30 jours » ; « VP depuis 01/06/25 » -> « depuis 01/06/25 » ; « VP mois -1 » -> « du mois précédent »."""
    t = lbl[3:] if lbl.startswith("VP ") else lbl
    m = re.fullmatch(r"(\d+)j", t)
    if m:
        return f"sur {m.group(1)} jours"
    if t.startswith("depuis"):
        return t
    m = re.fullmatch(r"(jour|semaine|mois|trimestre|année)(?: -(\d+))?", t)
    if m:
        art = {"jour": "du jour", "semaine": "de la semaine", "mois": "du mois", "trimestre": "du trimestre", "année": "de l'année"}[m.group(1)]
        return art + (f" (il y a {m.group(2)} période(s))" if m.group(2) else " en cours")
    return f"sur {t}"


AV_LABELS = {"année préc.": "ancré au début de l'année précédente", "mois préc.": "ancré au début du mois précédent",
             "bas 1 an": "ancré sur le plus bas de l'année", "haut 1 an": "ancré sur le plus haut de l'année",
             "bas 3 mois": "ancré sur le plus bas des 3 derniers mois", "haut 3 mois": "ancré sur le plus haut des 3 derniers mois"}


def _av_label(name: str) -> str:
    lab = name[6:] if name.startswith("AVWAP ") else name
    return AV_LABELS.get(lab, f"ancré au {lab}")


def classify(lv: dict, now_ms: int = 0) -> dict:
    """Echelle de temps, famille, poids et phrase en clair d'un niveau."""
    g, n, k, p = lv.get("group", ""), lv.get("name", ""), lv.get("kind", ""), lv["price"]
    px = fmt_price(p)
    if k == "round":
        return {"tf": 0, "fam": "round", "w": EMPH["round"], "text": f"nombre rond {px} (des ordres s'y accumulent)"}
    if k == "liq":
        pool = lv.get("pool") or {}
        who = "longues" if pool.get("side") == "long" else "courtes"
        return {"tf": 0, "fam": "liq", "w": 0.0, "text": f"poche de liquidations de positions {who} vers {px}"}
    if g in PERIOD_OF:
        per, fam, prev = PERIOD_OF[g]
        tf = PER[per]
        cur = PREV[per] if prev else CUR[per]
        if fam == "vwap":
            if n.endswith("+2σ"):
                return {"tf": tf, "fam": "band", "w": TFW[tf] * EMPH["band"], "text": f"borne haute (+2 écarts-types) du prix moyen pondéré par les volumes (VWAP) {cur} : {px}, zone où le prix est très étiré"}
            if n.endswith("-2σ"):
                return {"tf": tf, "fam": "band", "w": TFW[tf] * EMPH["band"], "text": f"borne basse (-2 écarts-types) du prix moyen pondéré par les volumes (VWAP) {cur} : {px}, zone où le prix est très étiré"}
            return {"tf": tf, "fam": "vwap", "w": TFW[tf] * EMPH["vwap"], "text": f"prix moyen pondéré par les volumes (VWAP) {cur} : {px}"}
        if fam == "open":
            return {"tf": tf, "fam": "open", "w": TFW[tf] * EMPH["open"], "text": f"ouverture {cur} : {px} (prix de départ de la période, souvent défendu)"}
        if fam == "hl":
            hi = n.endswith("H")
            return {"tf": tf, "fam": "hl", "w": TFW[tf] * EMPH["hl"], "text": f"{'plus haut' if hi else 'plus bas'} {cur} : {px} (des ordres d'arrêt s'y trouvent)"}
        what = VP_WHAT.get(n[-3:], VP_WHAT["POC"]) if n[-3:] in VP_WHAT else VP_WHAT["POC"]
        return {"tf": tf, "fam": "vp", "w": TFW[tf] * EMPH["vp"], "text": f"{what} {cur} : {px}"}
    if g == "nPOC":
        unit_w = "S-" in n
        age = n.rsplit("-", 1)[-1] if "-" in n else "?"
        tf = 2 if unit_w else 1
        return {"tf": tf, "fam": "npoc", "w": TFW[tf] * EMPH["npoc"],
                "text": f"point de contrôle « nu » d'il y a {age} {'semaine(s)' if unit_w else 'jour(s)'} : {px} (jamais retesté depuis)"}
    if g.startswith("aVWAP"):
        anchor = (lv.get("anchor") or 0)
        age = (now_ms - anchor) / 86_400_000 if anchor and now_ms else 365
        tf = 1 if age <= 10 else 2 if age <= 45 else 3 if age <= 150 else 4
        return {"tf": tf, "fam": "avwap", "w": TFW[tf] * EMPH["avwap"],
                "text": f"prix moyen pondéré par les volumes (VWAP) {_av_label(n)} : {px}"}
    if g.startswith("xVP"):
        vid = (lv.get("vpid") or g[4:])
        tf = 3
        if vid.startswith("r") and vid[1:].isdigit():
            tf = _days_tf(int(vid[1:]))
        elif vid.startswith("s") and len(vid) >= 11:
            try:
                from datetime import datetime, timezone
                d0 = datetime.strptime(vid[1:11], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000
                tf = _days_tf(max(1.0, (now_ms - d0) / 86_400_000)) if now_ms else 3
            except ValueError:
                tf = 3
        else:
            for pfx, v in (("day", 1), ("week", 2), ("month", 3), ("quarter", 3), ("year", 4)):
                if vid.startswith(pfx):
                    tf = v
        what = VP_WHAT.get(n[-3:], VP_WHAT["POC"])
        label = _vp_label(n[:-4] if n[-3:] in VP_WHAT else n)
        return {"tf": tf, "fam": "vp", "w": TFW[tf] * EMPH["vp"], "text": f"{what} du profil de volume {label} : {px}"}
    return {"tf": 1, "fam": "hl", "w": 1.0, "text": f"{n} : {px}"}


def zone_structure(members, now_ms: int = 0) -> dict:
    """Qualite d'une zone = somme, par SOURCE distincte (un VWAP et ses bandes comptent une fois), du poids de la source."""
    by_g: dict[str, dict] = {}
    for m in members:
        c = classify(m, now_ms)
        if c["fam"] == "liq":
            continue
        g = m.get("group", m["name"])
        if g not in by_g or c["w"] > by_g[g]["w"]:
            by_g[g] = {**c, "price": m["price"], "name": m["name"], "group": g}
    av = sorted([c for c in by_g.values() if c["fam"] == "avwap"], key=lambda c: c["price"])
    for a, b in zip(av, av[1:]):                          # deux VWAP ancrees a moins de 0,12 % : une seule ligne
        if a["group"] in by_g and b["group"] in by_g and abs(b["price"] - a["price"]) <= 0.0012 * a["price"]:
            del by_g[a["group"] if a["w"] < b["w"] else b["group"]]
    items = sorted(by_g.values(), key=lambda c: -c["w"])
    real = [c for c in items if c["fam"] != "round"]
    return {"S": sum(c["w"] for c in real), "items": items, "n": len(real),
            "htf": sum(1 for c in real if c["tf"] >= 2), "core": sum(1 for c in real if c["fam"] in ("vwap", "band", "avwap")),
            "vp": sum(1 for c in real if c["fam"] == "vp"), "maxTf": max([c["tf"] for c in real] or [0])}


def quality_word(S):
    return "exceptionnelle" if S >= 14 else "très forte" if S >= 11 else "forte" if S >= 8.5 else "correcte" if S >= 7 else "faible"


# ---------- construction des idees (etape 1 : structure, geometrie, liquidite) ----------
def build_ideas(inp: dict) -> tuple[list[dict], list[dict]]:
    """Renvoie (idees, rejets). `inp` : symbol, now, price, atr, levels, zones, pools, candles (bougies 1h fermees recentes),
    sweeps (balayages recents), opts. Une idee = dict sans score contextuel (voir score_idea)."""
    o = {**DEFAULTS, **(inp.get("opts") or {})}
    price, atr, now = inp["price"], inp["atr"], inp["now"]
    if not atr or atr <= 0:
        return [], []
    lv = {l["id"]: l for l in inp["levels"]}
    cs = inp.get("candles") or []
    zi = []
    for z in inp["zones"]:
        members = [lv[i] for i in z["members"] if i in lv]
        pools = [m["pool"] for m in members if m.get("kind") == "liq" and m.get("pool")]
        zi.append({**z, "st": zone_structure(members, now), "members_lv": members, "pools": pools})
    buf = max(0.5 * atr, 0.0015 * price)
    ideas, rejects = [], []

    def targets(side, entry, risk):
        """Prochains niveaux importants dans le sens du trade (zones solides, grosses poches), tries du plus proche au plus loin."""
        out = []
        for z in zi:
            if z["st"]["S"] >= o["target_min_struct"] and z["st"]["htf"] >= 1:
                if side == "long" and z["lo"] > entry:
                    out.append({"price": z["lo"] - 0.1 * atr, "kind": "zone", "ref": z})
                elif side == "short" and z["hi"] < entry:
                    out.append({"price": z["hi"] + 0.1 * atr, "kind": "zone", "ref": z})
        for p in inp.get("pools") or []:
            if p.get("score", 0) >= 60:
                if side == "long" and p["side"] == "short" and p["lo"] > entry:
                    out.append({"price": p["lo"] - 0.1 * atr, "kind": "pool", "ref": p})
                elif side == "short" and p["side"] == "long" and p["hi"] < entry:
                    out.append({"price": p["hi"] + 0.1 * atr, "kind": "pool", "ref": p})
        out.sort(key=lambda t: abs(t["price"] - entry))
        res = []
        for t in out:
            rr = abs(t["price"] - entry) / risk if risk else 0
            if not res or abs(t["price"] - res[-1]["price"]) >= 1.0 * atr:       # pas deux objectifs collés
                res.append({**t, "rr": rr})
        return res

    recent = [c for c in cs if c.t >= now - o["recent_hours"] * 3_600_000] or cs[-1:]       # bougies fermees recentes (toute granularite)
    last_close = cs[-1].c if cs else price
    sweeps = [e for e in (inp.get("sweeps") or []) if now - e["t"] <= o["sweep_hours"] * 3_600_000]
    for z in zi:
        st = z["st"]
        tag = f"{fmt_price(z['mid'])}"
        if st["S"] < o["min_struct"] or st["htf"] < o["min_htf"] or st["core"] < 1 or st["n"] < o["min_sources"]:
            continue
        side = "long" if z["side"] == "below" else "short" if z["side"] == "above" else None
        kind, wick, sweep_evt = "rebond", None, None
        # reprise : la zone a ete percee dans les dernieres heures puis reprise
        if recent:
            if side in ("long", None) and min(c.l for c in recent) < z["lo"] - 0.1 * atr and last_close > z["mid"] and price >= z["lo"]:
                side, kind, wick = "long", "reprise", min(c.l for c in recent)
            elif side in ("short", None) and max(c.h for c in recent) > z["hi"] + 0.1 * atr and last_close < z["mid"] and price <= z["hi"]:
                side, kind, wick = "short", "reprise", max(c.h for c in recent)
        for e in sweeps:                                    # poche de liquidation proche balayee
            near = abs(e["price"] - z["mid"]) <= max(0.8 * atr, z["hi"] - z["lo"])
            if near and ((e["side"] == "long" and side in ("long", None) and price >= z["lo"]) or (e["side"] == "short" and side in ("short", None) and price <= z["hi"])):
                sweep_evt = e
                side = "long" if e["side"] == "long" else "short"
                kind = "reprise"
        if side is None:
            continue
        # poches importantes JUSTE AU-DELA de la zone (cote du stop) : le prix peut aller les chercher avant de repartir
        near = []
        for p in inp.get("pools") or []:
            if p.get("score", 0) < 50 or p in z["pools"]:
                continue
            if side == "long" and p["side"] == "long" and p["price"] < z["lo"] and p["hi"] >= z["lo"] - 2.0 * atr:
                near.append(p)
            elif side == "short" and p["side"] == "short" and p["price"] > z["hi"] and p["lo"] <= z["hi"] + 2.0 * atr:
                near.append(p)
        # entree et stop
        if side == "long":
            base = min([z["lo"]] + [p["lo"] for p in z["pools"] + near if p["side"] == "long"] + ([wick] if wick else []) + ([sweep_evt["to"] or sweep_evt["price"]] if sweep_evt else []))
            stop = base - buf
            entry = z["hi"]
            if kind == "reprise" and (price - z["hi"] <= 0.5 * atr or z["side"] == "in"):
                entry = price
        else:
            base = max([z["hi"]] + [p["hi"] for p in z["pools"] + near if p["side"] == "short"] + ([wick] if wick else []) + ([sweep_evt["to"] or sweep_evt["price"]] if sweep_evt else []))
            stop = base + buf
            entry = z["lo"]
            if kind == "reprise" and (z["lo"] - price <= 0.5 * atr or z["side"] == "in"):
                entry = price
        entry_type = "marché" if abs(entry - price) < 1e-9 else "limite"
        if abs(entry - stop) < o["risk_min_atr"] * atr:                     # stop trop serre : on l'elargit au plancher de bruit
            stop = entry - o["risk_min_atr"] * atr if side == "long" else entry + o["risk_min_atr"] * atr
        risk = abs(entry - stop)
        dist = abs(price - entry) / atr
        if (side == "long" and entry <= stop) or (side == "short" and entry >= stop):
            continue
        why_not = None
        if dist > o["max_dist_atr"]:
            why_not = f"prix trop loin de l'entrée ({fmt_num(dist)} amplitudes d'heure)"
        elif risk > o["risk_max_atr"] * atr:
            why_not = "stop trop éloigné : le rapport gain / risque serait mauvais"
        tg = targets(side, entry, risk) if risk else []
        tg1 = next((t for t in tg if t["rr"] >= o["min_rr1"]), None)
        if why_not is None and tg1 is None:
            why_not = "aucun objectif réaliste (prochain niveau important trop proche ou absent)"
        base_idea = {"zoneId": z["id"], "side": side, "kind": kind, "entry": entry, "entryType": entry_type, "stop": stop,
                     "risk": risk, "distAtr": dist, "zone": {"lo": z["lo"], "hi": z["hi"], "mid": z["mid"], "side": z["side"]},
                     "st": st, "pools": z["pools"], "nearPools": near, "sweep": sweep_evt, "wick": wick, "label": tag, "minStruct": o["min_struct"]}
        if why_not:
            rejects.append({**base_idea, "why": why_not})
            continue
        idx = tg.index(tg1)
        tg2 = next((t for t in tg[idx + 1:] if t["rr"] >= tg1["rr"] + 0.5), None)
        base_idea.update(tp1=tg1["price"], rr1=tg1["rr"], tp1Kind=tg1["kind"], tp1Ref=tg1["ref"],
                         tp2=tg2["price"] if tg2 else None, rr2=tg2["rr"] if tg2 else None, tp2Kind=tg2["kind"] if tg2 else None,
                         tp2Ref=tg2["ref"] if tg2 else None)
        ideas.append(base_idea)
    # une idee par zone et par cote ; au plus 2 par cote, les plus solides d'abord
    ideas.sort(key=lambda i: (-i["st"]["S"], i["distAtr"]))
    kept, per_side = [], {"long": [], "short": []}
    for i in ideas:
        if len(per_side[i["side"]]) >= 2 or any(abs(i["entry"] - j["entry"]) < 1.0 * atr for j in per_side[i["side"]]):
            continue
        per_side[i["side"]].append(i)
        kept.append(i)
    return kept, rejects


# ---------- etape 2 : score contextuel ----------
def _clip(x, lo=-1.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def trend_score(price, vw):
    """-1 (tendance de fond baissiere) .. +1 (haussiere) : position du prix face aux VWAP semaine / mois / annee."""
    parts = []
    for key, w in (("W", 1.0), ("M", 2.0), ("Y", 2.0)):
        v = vw.get(key)
        if v:
            parts.append(((1 if price > v else -1), w))
    return sum(s * w for s, w in parts) / sum(w for _, w in parts) if parts else 0.0


def score_idea(idea: dict, c: dict, o: dict | None = None) -> dict:
    """Ajoute a l'idee : score sur 100 (detail par composante), alertes de prudence, verrous (attente) et filtres (gates).
    c : price, vwap {W,M,Y}, flow (score -1..1 + notes), macro (etat macro), synth, dom, now."""
    o = {**DEFAULTS, **(o or {})}
    sgn = 1 if idea["side"] == "long" else -1
    comps, warn, hold, gates = [], [], [], []
    st = idea["st"]
    # 1) liquidite (30)
    lpts, lnotes = 0.0, []
    same = lambda p: (p["side"] == "long") == (idea["side"] == "long")
    pools = [p for p in idea["pools"] if same(p)]
    if pools:
        best = max(p.get("score", 0) for p in pools)
        lpts += 14.0 if best >= 70 else 9.0 if best >= 50 else 4.0
        lnotes.append("poche de liquidations dans la zone" + (" (la plus importante)" if best >= 70 else ""))
    near = [p for p in idea.get("nearPools", []) if same(p)]
    if near:
        lpts += 8.0 if max(p.get("score", 0) for p in near) >= 70 else 6.0
        lnotes.append("grosse poche juste au-delà de la zone (le stop est placé derrière)")
    if idea["sweep"]:
        lpts += 12.0 if idea["sweep"]["frac"] >= 0.15 else 8.0
        lnotes.append("poche déjà balayée récemment")
    elif idea["kind"] == "reprise":
        lpts += 6.0
        lnotes.append("zone percée puis reprise")
    if idea.get("tp1Kind") == "pool" or idea.get("tp2Kind") == "pool":
        lpts += 6.0
        lnotes.append("grosse poche en face comme objectif")
    lpts = min(30.0, lpts)
    comps.append({"key": "liquidity", "label": "Liquidité", "pts": lpts, "max": 30, "note": "; ".join(lnotes) or "pas de poche notable liée à la zone"})
    if lpts < o["min_liq_pts"]:
        gates.append("pas assez de liquidité liée à la zone (ni poche dans la zone ou juste au-delà, ni balayage récent, ni grosse poche comme objectif)")
    # 2) VWAP, VWAP ancres et niveaux superposes (30)
    s_pts = 30.0 * min(1.0, st["S"] / 14.0)
    tfs = ", ".join(TF_NAME[t] for t in sorted({i["tf"] for i in st["items"] if i["tf"]}, reverse=True))
    comps.append({"key": "structure", "label": "VWAP, VWAP ancrés et niveaux", "pts": s_pts, "max": 30,
                  "note": f"{st['n']} sources dont {st['core']} VWAP ou VWAP ancré, qualité {fmt_num(st['S'])} ({quality_word(st['S'])}), échelles : {tfs}"})
    # 3) macro et annonces (20)
    macro = c.get("macro") or {}
    ms = macro.get("score")
    m_pts = 10.0 + (10.0 * _clip(sgn * ms / 100.0) if ms is not None else 0.0)
    m_note = f"lecture macro {macro.get('label') or 'indisponible'}" + (f" ({ms:+.0f}/100)" if ms is not None else "")
    risk = macro.get("risk")
    ev_h = None
    if macro.get("inWindow"):
        hold.append("une annonce majeure vient d'être publiée ou va l'être dans l'heure : on attend que le marché se stabilise")
    if risk:
        ev_h = risk["minutes"] / 60.0
        if ev_h <= 3:
            hold.append(f"annonce majeure dans {fmt_num(ev_h)} h ({risk['label']}) : on attend la publication")
        elif ev_h <= 24:
            m_pts -= 6.0
            warn.append(f"annonce majeure dans {fmt_num(ev_h, 0)} h ({risk['label']}) : le prix peut balayer la zone avant")
    m_pts = max(0.0, min(20.0, m_pts))
    comps.append({"key": "macro", "label": "Macro et annonces", "pts": m_pts, "max": 20, "note": m_note})
    if ms is not None and m_pts < o["min_macro_pts"]:
        gates.append(f"le contexte macro va nettement contre l'idée ({macro.get('label') or 'macro'} {ms:+.0f}/100)")
    # 4) flux d'ordres (8)
    fs, fnotes = c.get("flow") or (None, [])
    if fs is None:
        comps.append({"key": "flow", "label": "Flux d'ordres", "pts": 4.0, "max": 8, "note": "indisponible : neutre"})
    else:
        comps.append({"key": "flow", "label": "Flux d'ordres", "pts": 4.0 + 4.0 * _clip(sgn * fs), "max": 8,
                      "note": "; ".join(t for s, t in fnotes if s * sgn > 0.15) or "ne soutient ni n'empêche"})
    # levier : shorts / longs qui s'accumulent = carburant de squeeze CONTRE l'idee (lecture seule : non mesure comme predictif, il n'entre pas dans le score)
    sq = ((c.get("squeeze") or {}).get("state") or {}).get("code")
    if (sq == "short_fuel" and sgn < 0) or (sq == "long_fuel" and sgn > 0):
        word = ("des shorts s'accumulent (intérêt ouvert en hausse, flux vendeur, prix qui ne baisse pas) : un squeeze haussier peut balayer une vente" if sgn < 0 else
                "des longs s'accumulent (intérêt ouvert en hausse, flux acheteur, prix qui ne monte pas) : un squeeze baissier peut balayer un achat")
        warn.append(word + " (lecture du levier, non démontrée par le backtest)")
    elif (sq == "squeeze_up" and sgn < 0) or (sq == "squeeze_down" and sgn > 0):
        warn.append("squeeze en cours dans le sens contraire (positions fermées de force, intérêt ouvert en chute) : attendre la fin du mouvement avant d'entrer")
    # 5) tendance de fond (7) : moyennes 50 j / 200 j si disponibles (c'est ce que mesure le backtest), sinon position face aux VWAP
    tr = trend_score(c["price"], c.get("vwap") or {})
    rg = c.get("regime")
    align = (rg["regime"] * sgn) if rg and rg.get("ready") else None
    if align is not None:
        side_word = "au-dessus des" if rg["regime"] > 0 else "sous les" if rg["regime"] < 0 else "entre les"
        t_pts = 7.0 if align > 0 else 3.5 if align == 0 else 0.0
        t_note = (f"dans le sens de la tendance de fond ({fmt_price(rg['price'])} {side_word} moyennes de {rg['fastDays']} et {rg['slowDays']} jours)" if align > 0 else
                  f"tendance de fond indécise (cours entre les moyennes de {rg['fastDays']} et {rg['slowDays']} jours)" if align == 0 else
                  f"CONTRE la tendance de fond (cours {side_word} moyennes de {rg['fastDays']} et {rg['slowDays']} jours)")
        comps.append({"key": "trend", "label": "Tendance de fond", "pts": t_pts, "max": 7, "note": t_note})
        ev = c.get("evidence") or {}
        stat = (f" Mesuré sur {ev['label']} : {fmt_num(ev['aligned'], 2)} fois le risque gagné en moyenne par trade dans le sens de la tendance, "
                f"{fmt_num(ev['counter'], 2)} à contre-courant." if ev.get("aligned") is not None and ev.get("counter") is not None else "")
        if o.get("trend_gate") and align < 0:
            gates.append("l'idée va contre la tendance de fond : le cours est " + side_word + " moyennes de 50 et 200 jours, et c'est la catégorie d'idées qui a perdu de l'argent dans le backtest." + stat)
        elif o.get("trend_gate") and align == 0:
            gates.append("tendance de fond indécise (cours entre les moyennes de 50 et 200 jours) : aucun avantage mesuré dans le backtest pour ces idées." + stat)
    else:
        if sgn * tr < -0.3:
            warn.append("l'idée va contre la tendance de fond (prix " + ("sous" if tr < 0 else "au-dessus de") + " les VWAP de la semaine, du mois et de l'année) : plus risquée")
        comps.append({"key": "trend", "label": "Tendance de fond", "pts": max(0.0, min(7.0, 3.5 + 3.5 * sgn * tr)), "max": 7,
                      "note": ("dans le sens de la tendance de fond" if sgn * tr > 0.3 else "contre la tendance de fond" if sgn * tr < -0.3 else "tendance de fond neutre")})
    # 6) biais et dominance (5)
    sy, dom = c.get("synth") or {}, c.get("dom") or {}
    b_pts, notes = 2.5, []
    if sy.get("direction") in ("haussier", "baissier"):
        b_pts += 1.5 * _clip(sgn * sy["score"] / 50.0)
        notes.append(f"biais global {sy['direction']}")
    d = (dom.get("regime") or {}).get("score") if c.get("is_alt") else None
    if d is not None:
        b_pts += 1.0 * _clip(sgn * d / 0.6)
        notes.append(f"dominance : {dom['regime']['name']}")
    comps.append({"key": "bias", "label": "Biais et dominance", "pts": max(0.0, min(5.0, b_pts)), "max": 5, "note": "; ".join(notes) or "neutre"})
    total = sum(x["pts"] for x in comps)
    mlines = [ln["text"] for ln in (macro.get("lines") or []) if ln.get("text", "").startswith("Lecture macro") or "mouvement inhabituel" in ln.get("text", "")][:3]
    return {**idea, "score": round(total, 1), "comps": comps, "warn": warn, "hold": hold, "gates": gates, "eventHours": ev_h,
            "trend": tr, "align": align, "regime": rg if rg and rg.get("ready") else None, "evidence": c.get("evidence"),
            "news": news_lines(macro, c.get("now") or 0), "macroLines": mlines}


DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def news_lines(macro: dict, now_ms: int) -> list[str]:
    """Annonces economiques en clair : les prochaines annonces majeures (consensus) et la derniere reaction mesuree."""
    out = []
    if not macro or not now_ms:
        return out
    import time as _t
    for e in (macro.get("upcoming") or [])[:8]:
        h = (e["t"] - now_ms) / 3_600_000
        if e.get("impact") == 3 and e.get("w", 0) >= 0.5 and 0 <= h <= 72:
            g = _t.gmtime(e["t"] / 1000)
            ex = (e.get("exp") or {}).get("text") or "pas de consensus publié"
            out.append(f"{e['label']} : {DAYS[g.tm_wday]} à {g.tm_hour:02d} h {g.tm_min:02d} (heure UTC), dans {fmt_num(h, 0) if h >= 10 else fmt_num(h)} h. {ex}")
        if len(out) >= 2:
            break
    for e in (macro.get("past") or [])[:4]:
        r = e.get("reaction")
        if r and r.get("impulse") is not None and now_ms - e["t"] <= 24 * 3_600_000 and e.get("impact") == 3:
            out.append(f"Dernière annonce : {e['label']}, surprise {r['impulseLabel']} lue dans les taux et le dollar.")
            break
    return out


# ---------- etape 3 : textes en clair ----------
def grade(score):
    return "excellente" if score >= 80 else "très bonne" if score >= 72 else "bonne" if score >= 60 else "moyenne" if score >= 50 else "faible"


def leverage_lines(idea, lev, mmr=0.4):
    entry, stop = idea["entry"], idea["stop"]
    sp = abs(entry - stop) / entry * 100.0
    liq_pct = max(0.0, 100.0 / lev - mmr)
    liq = entry * (1 - liq_pct / 100.0) if idea["side"] == "long" else entry * (1 + liq_pct / 100.0)
    lev_max = max(1, int(100.0 / (2.0 * sp + mmr)))
    out = [f"Si le stop est touché, tu perds {fmt_pct(sp)} du prix, soit {fmt_pct(sp * lev)} de ta marge avec ton levier de {fmt_num(lev, 0)}x. "
           f"À ce levier, ta liquidation serait vers {fmt_price(liq)} ({fmt_pct(liq_pct)} de l'entrée)."]
    if liq_pct <= sp * 1.1:
        out.append(f"⚠ À ce levier la liquidation arrive AVANT ton stop : ne dépasse pas {lev_max}x.")
    elif lev > lev_max:
        out.append(f"⚠ Ta liquidation serait à moins de deux fois la distance du stop : pour garder de la marge de sécurité, reste à {lev_max}x au maximum.")
    else:
        out.append(f"Ta liquidation reste bien au-delà du stop. Levier maximum pour qu'elle soit deux fois plus loin que le stop : {lev_max}x.")
    return out, {"lev": lev, "stopPct": sp, "liqPrice": liq, "liqPct": liq_pct, "levMax": lev_max, "marginLoss": sp * lev}


def trend_text(idea: dict) -> list[str]:
    """Tendance de fond et ce que le backtest en dit, en clair (liste vide si la tendance est inconnue)."""
    rg, align = idea.get("regime"), idea.get("align")
    if not rg or align is None:
        return []
    px = lambda v: fmt_price(v)
    pos = (f"Le cours ({px(rg['price'])}) est {'au-dessus de' if rg['regime'] > 0 else 'sous' if rg['regime'] < 0 else 'entre'} "
           f"la moyenne de {rg['fastDays']} jours ({px(rg['fast'])}) et {'de ' if rg['regime'] > 0 else ''}la moyenne de {rg['slowDays']} jours ({px(rg['slow'])}) : tendance de fond {rg['label']}.")
    out = [pos]
    if align > 0:
        out.append("L'idée va DANS LE SENS de cette tendance : c'est la seule catégorie d'idées qui a rapporté de l'argent dans le backtest.")
    elif align < 0:
        out.append("L'idée va À CONTRE-COURANT de cette tendance : c'est la catégorie qui a perdu de l'argent dans le backtest.")
    else:
        out.append("La tendance est indécise : aucun avantage n'a été mesuré dans ce cas.")
    ev = idea.get("evidence")
    if ev and ev.get("aligned") is not None and ev.get("counter") is not None:
        out.append(f"Mesuré sur {ev['label']} ({ev.get('n', '?')} idées dans le sens de la tendance) : en moyenne {fmt_num(ev['aligned'], 2)} fois le risque pris par trade après frais "
                   f"dans le sens de la tendance, {fmt_num(ev['counter'], 2)} à contre-courant. Avantage modeste, venant surtout de la tendance elle-même : pas une garantie.")
    return out


def describe(idea: dict, probs: dict | None, valid: dict | None, lev: float, symbol: str, week_n: int | None = None) -> dict:
    """Texte complet de l'idee, sans abreviation : quoi faire, pourquoi, contexte, probabilites, prudence."""
    side = idea["side"]
    buy = side == "long"
    word = "ACHAT (position longue)" if buy else "VENTE (position courte)"
    e, s, t1, t2 = idea["entry"], idea["stop"], idea["tp1"], idea.get("tp2")
    pct = lambda a: (a / e - 1.0) * 100.0
    head = f"{symbol} : {word}"
    action = []
    if idea["entryType"] == "marché":
        action.append(f"Entrée : près du prix actuel, vers {fmt_price(e)} (le piège vient d'être joué et le prix a repris la zone).")
    else:
        sens = "descend" if buy else "monte"
        action.append(f"Entrée : ordre {'d'+chr(39)+'achat' if buy else 'de vente'} à cours limité à {fmt_price(e)}, exécuté seulement si le prix {sens} jusque-là (le prix actuel est {fmt_price(idea['price'])}, à {fmt_pct(idea['distAtr'] * idea['atrPct'])} de l'entrée).")
    action.append(f"Stop (sortie si l'idée est fausse) : {fmt_price(s)}, soit {fmt_pct(pct(s), 2, True)} par rapport à l'entrée.")
    action.append(f"Objectif 1 : {fmt_price(t1)} ({fmt_pct(pct(t1), 2, True)}), gain d'environ {fmt_num(idea['rr1'])} fois le risque pris. Conseil : en prendre une partie et remonter le stop à l'entrée.")
    if t2:
        action.append(f"Objectif 2 : {fmt_price(t2)} ({fmt_pct(pct(t2), 2, True)}), environ {fmt_num(idea['rr2'])} fois le risque.")
    if idea["entryType"] == "marché":
        action.append(f"Validité : entrée immédiate, l'idée est fausse si le prix atteint {fmt_price(s)}. Si le prix a déjà trop bougé quand tu lis ce message, ne cours pas après : attends la prochaine idée.")
    else:
        action.append(f"Validité : {idea['validHours']} h. L'idée est annulée si le prix atteint {fmt_price(s)} avant que l'ordre soit exécuté, ou si l'objectif 1 est atteint sans que l'ordre l'ait été.")
    st = idea["st"]
    why = [f"Zone {fmt_price(idea['zone']['lo'])} - {fmt_price(idea['zone']['hi'])} : {st['n']} niveaux se superposent "
           f"(qualité {fmt_num(st['S'])} ; minimum demandé {fmt_num(idea.get('minStruct', 7.0))}, 14 et plus est exceptionnel)."]
    # 1) la liquidite : ce vers quoi le prix est attire, et ce que le stop evite
    liq = []
    who = lambda p: "longues" if p["side"] == "long" else "courtes"
    def pool_name(p):
        if p.get("src"):                         # poche visible dans le prix (plus haut / plus bas, creux, sommet)
            return f"ordres d'arrêt {'sous' if p['side'] == 'long' else 'au-dessus de'} le {p['src']}"
        return f"liquidations de positions {who(p)}"
    for p in idea["pools"]:
        if (p["side"] == "long") == buy:
            liq.append(f"  • Poche de {pool_name(p)} entre {fmt_price(p['lo'])} et {fmt_price(p['hi'])} dans la zone (force {p.get('score', 0):.0f}/100) : "
                       "beaucoup d'ordres d'arrêt s'y trouvent ; le prix va souvent les chercher, puis repart.")
    for p in idea.get("nearPools", []):
        if (p["side"] == "long") == buy:
            liq.append(f"  • Grosse poche de {pool_name(p)} juste {'sous' if buy else 'au-dessus de'} la zone, entre {fmt_price(p['lo'])} et {fmt_price(p['hi'])} "
                       f"(force {p.get('score', 0):.0f}/100) : le prix peut aller la chercher avant de repartir, c'est pourquoi le stop est placé derrière elle.")
    if idea["sweep"]:
        e0 = idea["sweep"]
        what = f"Le {e0['src']} (vers {fmt_price(e0['price'])})" if e0.get("src") else f"Une poche de positions {who(e0)} vers {fmt_price(e0['price'])}"
        liq.append(f"  • {what} a été balayé{'' if e0.get('src') else 'e'} il y a {idea.get('sweepAgeH') or 0:.0f} h : les ordres d'arrêt ont été pris, "
                   "ce qui précède souvent un retournement.")
    elif idea["kind"] == "reprise" and idea.get("wick"):
        liq.append(f"  • Le prix a percé la zone jusqu'à {fmt_price(idea['wick'])} puis est revenu {'au-dessus' if buy else 'en dessous'} : la mèche a pris les ordres d'arrêt.")
    if idea.get("tp1Kind") == "pool" or idea.get("tp2Kind") == "pool":
        liq.append("  • Une grosse poche de liquidations se trouve en face : le prix y est attiré, c'est là que l'objectif est placé.")
    if liq:
        why.append("Liquidités (les ordres d'arrêt qui attirent le prix) :")
        why += liq
    # 2) VWAP et VWAP ancres
    vw = [it for it in st["items"] if it["fam"] in ("vwap", "band", "avwap")]
    if vw:
        why.append("Prix moyens (VWAP et VWAP ancrés), où les acheteurs et vendeurs de la période sont à l'équilibre :")
        why += [f"  • [{TF_NAME[it['tf']]}] {it['text']}" for it in vw[:5]]
    # 3) autres niveaux
    oth = [it for it in st["items"] if it["fam"] not in ("vwap", "band", "avwap", "round")]
    if oth:
        why.append("Autres niveaux au même endroit (profils de volume, ouvertures, plus hauts et plus bas) :")
        why += [f"  • [{TF_NAME[it['tf']]}] {it['text']}" for it in oth[:5]]
    why.append(f"Le stop est placé au-delà de {'la zone et de ses poches' if idea['pools'] or idea.get('nearPools') else 'la zone'} : si le prix va jusque-là, l'idée est fausse.")
    tgt1 = ("juste avant une poche de liquidations en face" if idea["tp1Kind"] == "pool" else "juste avant le prochain niveau important")
    why.append(f"L'objectif 1 est placé {tgt1}, car c'est là que le prix risque de se retourner.")
    macro_lines, ctx = [], []
    for cmp in idea["comps"]:
        if cmp["key"] == "macro":
            macro_lines.append(f"Macro et annonces ({cmp['pts']:.0f}/{cmp['max']}) : {cmp['note']}")
        elif cmp["key"] in ("flow", "trend", "bias") and cmp["note"]:
            ctx.append(f"{cmp['label']} ({cmp['pts']:.0f}/{cmp['max']}) : {cmp['note']}")
    macro_lines += list(idea.get("macroLines") or [])
    trend_lines = trend_text(idea)
    prob = []
    if probs:
        f = probs.get("fill")
        if f and f.get("p24") is not None:
            prob.append(f"Chance que l'ordre soit exécuté : environ {f['p24'] * 100:.0f} % en 24 h, {f['p72'] * 100:.0f} % en 72 h (fréquence historique pour cette distance)." if idea["entryType"] == "limite" else "Entrée immédiate.")
        pl = probs.get("plan")
        if pl and pl.get("tp", {}).get("p") is not None:
            prob.append(f"Une fois entré, fréquence historique d'atteindre l'objectif 1 avant le stop dans les 72 h : {pl['tp']['p'] * 100:.0f} % "
                        f"(intervalle {pl['tp']['lo'] * 100:.0f}-{pl['tp']['hi'] * 100:.0f} %, environ {pl['neff']} cas indépendants). "
                        "C'est la fréquence pour cette forme de trade à n'importe quel moment : la qualité des niveaux doit faire mieux pour apporter un avantage.")
        bn = probs.get("bounce")
        if bn and bn.get("n"):
            base = probs.get("baseBounce")
            prob.append(f"Rebond historique sur les zones de ce type : {bn['p'] * 100:.0f} % ({bn['n']} cas)" + (f" contre {base['p'] * 100:.0f} % pour des niveaux tirés au hasard." if base and base.get("p") is not None else "."))
    if valid:
        prob.append(valid["text"])
    levl, levinfo = leverage_lines(idea, lev)
    risks = list(idea["warn"]) + levl
    risks.append("Ce sont des estimations et des statistiques passées, pas une garantie ni un conseil financier. Ne risque que ce que tu acceptes de perdre.")
    return {"headline": head, "action": action, "why": why, "trend": trend_lines, "macro": macro_lines, "context": ctx, "news": list(idea.get("news") or []),
            "probs": prob, "risks": risks, "leverage": levinfo}


def to_text(idea: dict, d: dict, n_week: int, max_week: int) -> str:
    """Message Telegram complet (peut depasser la limite d'un message : voir split_message)."""
    stars = "★" * max(1, round((idea["score"] - 40) / 12)) if idea["score"] >= 52 else "★"
    lines = [f"🎯 Idée de trade {n_week}/{max_week} de la semaine · {d['headline']}",
             f"Qualité : {idea['score']:.0f}/100 ({grade(idea['score'])}) {stars}", "",
             "▶ QUOI FAIRE"] + [f"• {x}" for x in d["action"]]
    if d.get("trend"):
        lines += ["", "▶ TENDANCE DE FOND"] + [f"• {x}" for x in d["trend"]]
    lines += ["", "▶ POURQUOI ICI"] + d["why"]
    if d.get("macro"):
        lines += ["", "▶ CONTEXTE MACRO"] + [f"• {x}" for x in d["macro"]]
    if d.get("news"):
        lines += ["", "▶ ANNONCES ÉCONOMIQUES"] + [f"• {x}" for x in d["news"]]
    if d["context"]:
        lines += ["", "▶ AUTRES CONTEXTES"] + [f"• {x}" for x in d["context"]]
    if d["probs"]:
        lines += ["", "▶ PROBABILITÉS"] + [f"• {x}" for x in d["probs"]]
    lines += ["", "▶ PRUDENCE"] + [f"• {x}" for x in d["risks"]]
    return "\n".join(lines)


def split_message(text: str, limit: int = 3800) -> list[str]:
    """Decoupe un long message en plusieurs, SANS rien perdre, aux frontieres de sections (lignes vides) ; chaque morceau tient dans la limite
    de Telegram (4 096 caracteres, prudence : 3 800). Les morceaux suivants sont annonces par « (suite 2/3) »."""
    if len(text) <= limit:
        return [text]
    blocks, cur, out = text.split("\n\n"), "", []
    for b in blocks:
        while len(b) > limit - 20:                                   # un bloc seul trop long : on coupe aux lignes
            cut = b.rfind("\n", 0, limit - 20)
            cut = cut if cut > 0 else limit - 20
            b, rest = b[:cut], b[cut:].lstrip("\n")
            if cur and len(cur) + 2 + len(b) > limit - 20:
                out.append(cur)
                cur = ""
            cur = (cur + "\n\n" + b) if cur else b
            out.append(cur)
            cur, b = "", rest
        if cur and len(cur) + 2 + len(b) > limit - 20:
            out.append(cur)
            cur = b
        else:
            cur = (cur + "\n\n" + b) if cur else b
    if cur:
        out.append(cur)
    n = len(out)
    return [out[0]] + [f"(suite {k + 1}/{n})\n{x}" for k, x in enumerate(out[1:], 1)] if n > 1 else out
