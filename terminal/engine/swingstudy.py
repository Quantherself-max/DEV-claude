"""Etude des VWAP ancres sur un mouvement precedent d'au moins X % (swingavwap.py) :
  1. REACTION : que fait le prix apres un contact ? Rendement dans le sens de la cloture moins la derive moyenne du marche (par evenement, erreur-type
     regroupee par jour), et probabilite d'aller d'abord de 1 ATR dans ce sens (0,5 = hasard) ; par type d'ancre (sommet / creux), par reaction
     (la cloture « tient » du meme cote qu'avant ou « traverse »), par numero de contact, sur apprentissage et test, pour trois tailles de mouvement.
  2. TRADES : les memes contacts joues avec stop, objectif et duree (12 sorties), une vingtaine de filtres, dans les deux sens, protocole de stratstudy.run
     (sortie choisie sur la regle litterale, filtres classes sur l'apprentissage, jugement unique sur le test, temoin au hasard).
Module PUR."""
import math
import random
import time

from . import backtest as bt
from . import stratstudy as ss
from . import study
from .backtest import DAY, HOUR

CONFIGS = [f"{s}|{t}|{h}" for s in ("struct", "atr3", "atr5") for t in ("1R", "2R") for h in ("H24", "H48")]
SUBJECT = "Suivre la clôture 1 h face à un VWAP ancré sur un mouvement d'au moins {pct} % (sommet de la baisse ou creux)"


def _d0(e: dict) -> int:
    return -e["dir"] if e.get("fade") else e["dir"]


def rules() -> list[tuple[str, str, object]]:
    """(nom, groupe, regle) ; toutes ecrites sur le sens du signal d'origine (d0) pour que la variante inverse recoive les memes filtres."""
    holds = lambda e: _d0(e) == e["sideBefore"]                         # la cloture reste du meme cote qu'avant le contact
    trend = lambda e: e["reg"] == _d0(e)
    vol = lambda k: (lambda e: e["volr"] is not None and e["volr"] >= k)
    AND = lambda *fs: (lambda e: all(f(e) for f in fs))
    anc = lambda k: (lambda e: e["anchor"] == k)
    return [("Toute clôture sur un VWAP ancré (règle littérale)", "Base", lambda e: True),
            ("ancré sur le sommet de la baisse", "Ancre", anc("H")), ("ancré sur le creux de la baisse", "Ancre", anc("L")),
            ("la clôture tient (rejet / rebond)", "Réaction", holds), ("la clôture traverse (cassure)", "Réaction", lambda e: not holds(e)),
            ("sommet : rejet par en dessous (vente)", "Sens naturel", AND(anc("H"), holds)),
            ("creux : rebond par au-dessus (achat)", "Sens naturel", AND(anc("L"), holds)),
            ("sommet : cassure vers le haut (achat)", "Sens naturel", AND(anc("H"), lambda e: not holds(e))),
            ("creux : cassure vers le bas (vente)", "Sens naturel", AND(anc("L"), lambda e: not holds(e))),
            ("premier contact", "Contact", lambda e: e["touchNo"] == 1), ("deuxième contact ou plus", "Contact", lambda e: e["touchNo"] >= 2),
            ("premier contact + la clôture tient", "Contact", AND(lambda e: e["touchNo"] == 1, holds)),
            ("premier contact + traverse", "Contact", AND(lambda e: e["touchNo"] == 1, lambda e: not holds(e))),
            ("ancre de moins de 3 jours", "Âge", lambda e: e["ageD"] < 3), ("ancre de 3 à 10 jours", "Âge", lambda e: 3 <= e["ageD"] < 10), ("ancre de plus de 10 jours", "Âge", lambda e: e["ageD"] >= 10),
            ("baisse d'au moins 8 %", "Profondeur", lambda e: (e["depth"] or 0) >= 0.08), ("baisse d'au moins 12 %", "Profondeur", lambda e: (e["depth"] or 0) >= 0.12),
            ("dans le sens de la tendance 50/200 j", "Tendance", trend),
            ("tendance + la clôture tient", "Tendance", AND(trend, holds)), ("tendance + traverse", "Tendance", AND(trend, lambda e: not holds(e))),
            ("volume ≥ moyenne", "Volume", vol(1.0)), ("volume ≥ 1,5 × moyenne", "Volume", vol(1.5)),
            ("volume ≥ 1,5 × + la clôture tient", "Volume", AND(vol(1.5), holds)), ("volume ≥ 1,5 × + traverse", "Volume", AND(vol(1.5), lambda e: not holds(e))),
            ("premier contact + tendance + tient", "Contact", AND(lambda e: e["touchNo"] == 1, trend, holds))]


# =====================================================================================================
#  1. Reaction du prix
# =====================================================================================================
def _forward(ds, events: list[dict], hours=(4, 24, 48)):
    """[(evenement, {h: rendement dans le sens de la cloture moins la derive moyenne})] ; derive = moyenne de toutes les bougies 1 h (rendement a h heures)."""
    b = ds.b1h
    c = b.c
    n = len(c)
    base = {}
    for h in hours:
        xs = [c[i + h] / c[i] - 1.0 for i in range(0, n - h)]
        base[h] = sum(xs) / len(xs)
    out = []
    for e in events:
        j = b.idx_at(e["t"] - 1)
        r = {h: e["dir"] * ((c[j + h] / c[j] - 1.0) - base[h]) for h in hours if j >= 0 and j + h < n}
        out.append((e, r))
    return out, base


def _stat(rows, h, lo, hi):
    xs = [(e["t"], f[h]) for e, f in rows if h in f and lo <= e["t"] < hi]
    if len(xs) < 40:
        return None
    m = sum(x for _, x in xs) / len(xs)
    cl = {}
    for t, x in xs:
        cl[int(t // DAY)] = cl.get(int(t // DAY), 0.0) + (x - m)
    se = math.sqrt(sum(v * v for v in cl.values())) / len(xs)
    return {"n": len(xs), "ex": m, "t": (m / se) if se > 0 else 0.0}


def _prob(ds, sel, lo, hi, rnd, k=1.0, hours=24, max_n=2000):
    sel = [e for e in sel if lo <= e["t"] < hi]
    if len(sel) > max_n:
        sel = rnd.sample(sel, max_n)
    w = l = wb = lb = 0
    t_lo, t_hi = max(lo, bt.ms(2013, 6)), min(hi, bt.ms(2026, 8))
    for e in sel:
        v = study._barrier(ds.b5, e["t"], e["dir"], e["price"], e["atr"], k, hours)
        w, l = w + (v > 0), l + (v < 0)
        t = rnd.randrange(t_lo, max(t_lo + 1, t_hi))
        j = ds.b5.idx_at(t)
        a = ds.atr_at(t)
        if j < 0 or a <= 0:
            continue
        u = study._barrier(ds.b5, t, e["dir"], ds.b5.c[j], a, k, hours)
        wb, lb = wb + (u > 0), lb + (u < 0)
    if w + l < 40 or wb + lb < 40:
        return None
    p, pb = w / (w + l), wb / (wb + lb)
    se = math.sqrt(0.25 / (w + l) + 0.25 / (wb + lb))
    return {"n": w + l, "p": p, "pBase": pb, "sigma": (p - pb) / se}


def reaction_table(ds, events: list[dict], split_ms: int, with_prob: bool = True, seed: int = 5) -> list[dict]:
    """Une ligne par (ancre, reaction, contact) : rendement excedentaire a 4 / 24 / 48 h (+ apprentissage / test a 24 h) et probabilite d'aller d'abord de 1 ATR."""
    rnd = random.Random(seed)
    rows, _ = _forward(ds, events)
    big = 2 ** 62
    out = []
    for anchor in ("H", "L"):
        for react in ("tient", "traverse"):
            for touch in ("tous", "1er", "2e+"):
                sel = [(e, f) for e, f in rows if e["anchor"] == anchor and (e["dir"] == e["sideBefore"]) == (react == "tient")
                       and (touch == "tous" or (touch == "1er") == (e["touchNo"] == 1))]
                row = {"anchor": anchor, "reaction": react, "touch": touch, "n": len(sel)}
                if len(sel) >= 40:
                    for h in (4, 24, 48):
                        row[f"f{h}"] = _stat(sel, h, 0, big)
                    row["is24"], row["oos24"] = _stat(sel, 24, 0, split_ms), _stat(sel, 24, split_ms, big)
                    if with_prob and touch != "2e+":
                        evs = [e for e, _ in sel]
                        row["p"], row["pIs"], row["pOos"] = _prob(ds, evs, 0, big, rnd), _prob(ds, evs, 0, split_ms, rnd), _prob(ds, evs, split_ms, big, rnd)
                out.append(row)
    return out


def reaction_summary(rows: list[dict]) -> dict:
    """Combien de lignes montrent un ecart solide (|t| >= 3 a 24 h) et de meme signe sur l'apprentissage et le test ?"""
    n = solid = stable = 0
    for r in rows:
        f = r.get("f24")
        if not f:
            continue
        n += 1
        if abs(f["t"]) >= 3:
            solid += 1
            a, b = r.get("is24"), r.get("oos24")
            if a and b and a["ex"] * b["ex"] > 0 and abs(b["t"]) >= 1:
                stable += 1
    return {"rows": n, "solid": solid, "stable": stable}


# =====================================================================================================
#  2. Etude complete
# =====================================================================================================
def run(ds, events_by_pct: dict, label: str, start_ms: int, end_ms: int, split_ms: int, eras: list, main_pct: float = 0.05, costs: dict | None = None,
        control_runs: int = 40, progress=None, workers: int = 1, min_exit: int = 300, min_rule: int = 150) -> dict:
    t0 = time.time()
    say = progress or (lambda *_: None)
    say("réaction du prix…")
    sizes = []
    for pct in sorted(events_by_pct):
        ev = events_by_pct[pct]
        rows = reaction_table(ds, ev, split_ms, with_prob=(pct == main_pct))
        sizes.append({"pct": pct, "events": len(ev), "anchorsH": len({e["anchorT"] for e in ev if e["anchor"] == "H"}), "anchorsL": len({e["anchorT"] for e in ev if e["anchor"] == "L"}),
                      "reaction": rows, "summary": reaction_summary(rows)})
    main = events_by_pct[main_pct]
    events = []
    for e in main:
        events.append({**e, "fade": False})
        events.append({**e, "dir": -e["dir"], "fade": True})
    events.sort(key=lambda e: (e["t"], e["fade"], e["rank"]))
    say("trades…")
    rep = ss.run(ds, events, label, start_ms, end_ms, split_ms, eras, costs=costs, control_runs=control_runs, progress=progress, workers=workers, min_exit=min_exit, min_rule=min_rule,
                 rule_list=rules(), configs=CONFIGS, kind="avwap-swing", subject=SUBJECT.format(pct=int(round(main_pct * 100))), with_hedge=False)
    rep["swing"] = {"mainPct": main_pct, "maxAgeDays": 30, "sizes": sizes}
    rep["seconds"] = round(time.time() - t0)
    if rep.get("best"):
        rep["verdict"] = verdict(rep)
    return rep


def _pct_txt(v: float, d: int = 2) -> str:
    return f"{v * 100:+.{d}f}".replace(".", ",").replace("-", "−") + " %"


def _num(v: float, d: int = 1) -> str:
    return f"{v:.{d}f}".replace(".", ",").replace("-", "−")


def _thousands(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def verdict(rep: dict) -> dict:
    """Verdict des trades (stratstudy.verdict) precede d'un constat sur la reaction du prix."""
    v = ss.verdict(rep)
    main = next(s for s in rep["swing"]["sizes"] if abs(s["pct"] - rep["swing"]["mainPct"]) < 1e-9)
    sm = main["summary"]
    pct = int(round(main["pct"] * 100))
    rows = [r for r in main["reaction"] if r["touch"] == "tous" and r.get("f24")]
    worst = max(rows, key=lambda r: abs(r["f24"]["t"])) if rows else None
    anc = lambda r: "sommet" if r["anchor"] == "H" else "creux"
    solid = (f"{sm['solid']} montrent un écart solide à 24 h (|t| ≥ 3), dont {sm['stable']} avec le même signe sur le test" if sm["solid"] else "aucune ne montre d'écart solide à 24 h (|t| ≥ 3)")
    note = (f"Réaction du prix (mouvement d'au moins {pct} %, {_thousands(main['events'])} contacts de {_thousands(main['anchorsH'])} sommets et {_thousands(main['anchorsL'])} creux) : "
            f"sur {sm['rows']} lignes (ancre × tient / traverse × contact), {solid}.")
    if worst:
        note += (f" Le plus marqué : ancre sur le {anc(worst)}, la clôture {worst['reaction']} : {_pct_txt(worst['f24']['ex'])} à 24 h dans le sens de la clôture (écart t = {_num(worst['f24']['t'])}).")
    cross4 = [r for r in rows if r.get("f4") and r["f4"]["t"] <= -3]
    if cross4:
        rt = 2 * (rep["costs"]["taker"] + rep["costs"]["slip"])
        ex4 = sum(r["f4"]["ex"] for r in cross4) / len(cross4)
        names = ", ".join(anc(r) + " : " + r["reaction"] for r in cross4)
        note += (f" À 4 h seulement, {len(cross4)} lignes ont |t| ≥ 3 ({names}) : après la clôture, le prix revient en moyenne de {_num(abs(ex4) * 100, 2)} % "
                 f"contre le sens de la clôture, soit {'moins' if abs(ex4) < rt else 'plus'} que les frais d'un aller-retour au marché ({_num(rt * 100, 2)} %).")
    v["notes"].insert(0, note)
    return v
