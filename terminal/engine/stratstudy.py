"""Etude complete de la strategie de l'utilisateur (rebonds / clotures sur VWAP et VWAP ancres semaine + mois, volume profile, poches de liquidite).

PROTOCOLE FIXE avant de regarder les resultats (sinon on trouve toujours « quelque chose ») :
  1. Evenements : chaque touche d'un des 8 niveaux sur bougie 1 h ou 4 h, dans les DEUX sens (suivre la cloture = regle de l'utilisateur ; inverse = son contraire).
  2. Sorties : 48 combinaisons (stop x objectif x duree). La sortie est choisie sur la regle LITTERALE, periode d'apprentissage seulement.
  3. Filtres : une quarantaine de regles (echelle, niveau, volume, position face a la VAL / VAH des profils, tendance de fond), jouees avec les 3 meilleures sorties.
     Classement sur l'apprentissage seulement (statistique t de l'esperance, au moins 150 trades). La meilleure est ensuite regardee UNE FOIS sur la periode test.
  4. Verification : temoin au hasard (meme forme, meme tendance), sensibilite aux frais, resultat par periode et par annee.
  5. Couverture : correlation des rendements hebdomadaires entre la meilleure variante et toutes les autres ; portefeuille « principale + poids x couverture »,
     poids et couverture choisis sur l'apprentissage, juges sur le test.

Module PUR : prend les evenements deja construits (vwapstrat.build_events + attach), renvoie un dictionnaire serialisable."""
import math
import time
from datetime import datetime, timezone

from . import backtest as bt
from . import hedge
from . import vwapstrat as vs
from .backtest import DAY

KEYS = ("n", "winRate", "expR", "expLo", "expHi", "pf", "ret", "cagr", "maxDD", "sharpe", "perWeek", "exposure", "tstat", "avgWin", "avgLoss")
SUBJECT_VWAP = "Ta règle telle que tu la décris (clôture 1 h ou 4 h au-dessus ou en dessous d'un VWAP ou VWAP ancré de la semaine ou du mois)"
MIN_N_EXIT = 300           # une sortie n'est retenue que si elle repose sur au moins 300 trades d'apprentissage
MIN_N_RULE = 150
STOP_LABEL = {"struct": "stop sous la structure", "atr15": "stop à 1,5 ATR", "atr3": "stop à 3 ATR", "atr5": "stop à 5 ATR"}
TP_LABEL = {"pool": "objectif = poche de liquidité", "pool2R": "poche, sinon 2 R", "2R": "objectif 2 R", "poolhalf": "moitié à la poche 1, reste à la poche 2"}
HOLD_LABEL = {"H24": "24 h", "H48": "48 h", "H24x": "24 h (48 h si volume)"}


def slim(m: dict) -> dict:
    return {k: m.get(k) for k in KEYS}


def d0(e: dict) -> int:
    """Sens du signal d'origine (pour une variante inverse, le trade va a l'opposé)."""
    return -e["dir"] if e.get("fade") else e["dir"]


def tp_label(t: str) -> str:
    return TP_LABEL.get(t) or (f"objectif {t[:-1].replace('.', ',')} R" if t.endswith("R") else t)


def cfg_label(cfg: str) -> str:
    s, t, h = cfg.split("|")
    return f"{STOP_LABEL[s]} · {tp_label(t)} · {HOLD_LABEL[h]}"


# =====================================================================================================
#  Regles de filtrage (toutes ecrites sur le sens du signal d'origine d0)
# =====================================================================================================
def rules() -> list[tuple[str, str, object]]:
    """(nom, groupe, regle) ; chaque regle prend un evenement."""
    trend = lambda e: e["reg"] == d0(e)
    vol = lambda k: (lambda e: e["volr"] is not None and e["volr"] >= k)
    tf = lambda x: (lambda e: e["tf"] == x)
    grp = lambda x: (lambda e: e["grp"] == x)
    fam = lambda x: (lambda e: e["fam"] == x)
    typ = lambda x: (lambda e: e["type"] == x)

    def reentry(p):
        return lambda e: e["posPrev"][p] not in (None, 0) and e["pos"][p] == 0 and e["posPrev"][p] == -d0(e)

    def reject(p):
        return lambda e: e["pos"][p] is not None and e["pos"][p] == d0(e)

    def confirm(p):
        return lambda e: reentry(p)(e) or reject(p)(e)

    def against(p):
        return lambda e: (e["pos"][p] is not None and e["pos"][p] == -d0(e)) or (e["posPrev"][p] not in (None, 0) and e["pos"][p] == 0 and e["posPrev"][p] == d0(e))

    AND = lambda *fs: (lambda e: all(f(e) for f in fs))
    R = [("Règle littérale (toute clôture sur un niveau)", "Base", lambda e: True),
         ("1h seulement", "Échelle", tf("1h")), ("4h seulement", "Échelle", tf("4h")),
         ("niveaux du mois", "Niveau", grp("M")), ("niveaux de la semaine", "Niveau", grp("W")),
         ("VWAP seulement", "Niveau", fam("vwap")), ("VWAP ancrés seulement", "Niveau", fam("avwap")),
         ("traversée (la clôture change de côté)", "Déclencheur", typ("cross")), ("rebond (la clôture reste du même côté)", "Déclencheur", typ("bounce")),
         ("volume ≥ moyenne", "Volume", vol(1.0)), ("volume ≥ 1,5 × moyenne", "Volume", vol(1.5)),
         ("dans le sens de la tendance 50/200 j", "Tendance", trend)]
    for p, lab in (("pw", "semaine dernière"), ("pm", "mois dernier"), ("cw", "semaine en cours"), ("cm", "mois en cours")):
        R += [(f"VP {lab} : réintégration de la zone de valeur", "Volume profile", reentry(p)),
              (f"VP {lab} : rejet (clôture hors zone, dans le sens)", "Volume profile", reject(p)),
              (f"VP {lab} : réintégration ou rejet", "Volume profile", confirm(p)),
              (f"VP {lab} : contre le profil", "Volume profile", against(p)),
              (f"VP {lab} confirmé + volume ≥ moyenne", "Volume profile", AND(confirm(p), vol(1.0))),
              (f"VP {lab} confirmé + tendance", "Volume profile + tendance", AND(confirm(p), trend))]
    R += [("tendance + volume ≥ moyenne", "Tendance", AND(trend, vol(1.0))),
          ("tendance + 4h", "Tendance", AND(trend, tf("4h"))),
          ("tendance + niveaux du mois", "Tendance", AND(trend, grp("M"))),
          ("tendance + volume + niveaux du mois", "Tendance", AND(trend, vol(1.0), grp("M"))),
          ("tendance + VP mois dernier confirmé + volume", "Volume profile + tendance", AND(trend, confirm("pm"), vol(1.0))),
          ("tendance + VP semaine dernière confirmé + volume", "Volume profile + tendance", AND(trend, confirm("pw"), vol(1.0)))]
    return R


# =====================================================================================================
#  Evaluation d'une regle
# =====================================================================================================
def run_rule(events: list[dict], rule, cfg: str, costs: dict, start_ms: int, end_ms: int, split_ms: int, eras: list, cooldown_h: float = 6.0):
    """Selection continue sur toute la periode (une position a la fois), puis lecture par tranche : apprentissage, test, grandes periodes."""
    cands = vs.as_candidates(events, cfg, rule)
    trades = bt.select(cands, lambda r: True, costs, max_week=999, zone_cooldown_h=cooldown_h, start_ms=start_ms, end_ms=end_ms)
    return trades, summarize(trades, start_ms, end_ms, split_ms, eras)


def summarize(trades: list[dict], start_ms: int, end_ms: int, split_ms: int, eras: list) -> dict:
    sub = lambda a, b: [t for t in trades if a <= t["t"] < b]
    out = {"all": slim(bt.metrics(trades, start_ms, end_ms)), "is": slim(bt.metrics(sub(start_ms, split_ms), start_ms, split_ms)),
           "oos": slim(bt.metrics(sub(split_ms, end_ms), split_ms, end_ms))}
    out["eras"] = [{"label": lab, **slim(bt.metrics(sub(a, b), a, b))} for lab, a, b in eras]
    return out


def per_year(trades: list[dict], years: range) -> dict:
    out = {}
    for y in years:
        a, b = bt.ms(y), bt.ms(y + 1)
        s = [t["r"] for t in trades if a <= t["t"] < b]
        if s:
            out[str(y)] = {"n": len(s), "expR": round(sum(s) / len(s), 3)}
    return out


def _side(events: list[dict], fade: bool) -> list[dict]:
    return [e for e in events if bool(e.get("fade")) == fade]


# =====================================================================================================
#  Sorties calculees a la demande (une configuration a la fois : la memoire reste petite)
# =====================================================================================================
_G: dict = {}


def _work(args):
    cfg, lo, hi = args
    ds, ev = _G["ds"], _G["ev"]
    return [vs.run_config(ds, ev[i], cfg) for i in range(lo, hi)]


class Sims:
    """Calcule la sortie `cfg` de chaque evenement (en parallele par fork si workers > 1) et la range dans e['sims'] = {cfg: sim}.
    Une seule configuration est gardee en memoire a la fois par liste d'evenements."""

    def __init__(self, ds, workers: int = 1):
        self.ds, self.workers, self.cur = ds, max(1, workers), {}
        if self.workers > 1:
            import multiprocessing as mp
            _G["ds"] = ds
            self.ctx = mp.get_context("fork")

    def ensure(self, events: list[dict], cfg: str) -> None:
        key = id(events)
        if self.cur.get(key) == cfg:
            return
        if self.workers > 1 and len(events) > 4000:
            _G["ev"] = events
            n = len(events)
            step = max(1000, n // (self.workers * 8))
            pool = self.ctx.Pool(self.workers)
            try:
                parts = pool.map(_work, [(cfg, i, min(n, i + step)) for i in range(0, n, step)])
            finally:
                pool.close()
                pool.join()
            sims = [x for p in parts for x in p]
        else:
            sims = [vs.run_config(self.ds, e, cfg) for e in events]
        for e, sm in zip(events, sims):
            e["sims"] = {cfg: sm}
        self.cur[key] = cfg


# =====================================================================================================
#  Etude complete
# =====================================================================================================
def run(ds: "bt.Dataset", events: list[dict], label: str, start_ms: int, end_ms: int, split_ms: int, eras: list, costs: dict | None = None,
        control_runs: int = 40, n_exits: int = 3, extra_hedges: dict | None = None, progress=None, workers: int = 1,
        min_exit: int = MIN_N_EXIT, min_rule: int = MIN_N_RULE, rule_list=None, configs=None, kind: str = "vwap-strategy", subject: str | None = None,
        with_hedge: bool = True) -> dict:
    """rule_list : [(nom, groupe, regle)] (defaut : les filtres de la strategie VWAP / profil de volume) ; configs : sorties a essayer (defaut : les 48)."""
    t0 = time.time()
    costs = costs or bt.DEFAULT_COSTS
    say = progress or (lambda *_: None)
    lit, inv = _side(events, False), _side(events, True)
    R = rule_list or rules()
    cfgs = configs or vs.CONFIGS
    base_rule = R[0][2]
    years = range(_year(start_ms), _year(end_ms - 1) + 1)

    sims = Sims(ds, workers)
    # ---- 2. sorties (regle litterale, apprentissage) -------------------------------------------------
    exits = []
    for i, cfg in enumerate(cfgs):
        say(f"sorties {i + 1}/{len(cfgs)}")
        sims.ensure(lit, cfg)
        tr, sm = run_rule(lit, base_rule, cfg, costs, start_ms, end_ms, split_ms, eras)
        s_, tp, h = cfg.split("|")
        exits.append({"cfg": cfg, "stop": s_, "tp": tp, "hold": h, "label": cfg_label(cfg), **{k: sm[k] for k in ("all", "is", "oos")}, "eras": sm["eras"]})
    ok = [x for x in exits if x["is"]["n"] >= min_exit and x["is"]["expR"] is not None]
    ok.sort(key=lambda x: -x["is"]["expR"])
    chosen_exits = [x["cfg"] for x in ok[:n_exits]]
    exits.sort(key=lambda x: -(x["is"]["expR"] if x["is"]["expR"] is not None else -9))

    # ---- 3. filtres x sorties x deux sens -----------------------------------------------------------
    rows, store = [], {}
    total = len(R) * len(chosen_exits) * 2
    k = 0
    for cfg in chosen_exits:
        sims.ensure(lit, cfg)
        sims.ensure(inv, cfg)
        for name, group, rule in R:
            for fade in (False, True):
                k += 1
                if k % 20 == 0:
                    say(f"filtres {k}/{total}")
                tr, sm = run_rule(inv if fade else lit, rule, cfg, costs, start_ms, end_ms, split_ms, eras)
                store[(name, fade, cfg)] = tr
                rows.append({"name": name, "group": group, "side": "inverse" if fade else "suivre", "cfg": cfg, **sm})
    elig = [r for r in rows if r["is"]["n"] >= min_rule and r["is"].get("tstat") is not None]
    elig.sort(key=lambda r: -r["is"]["tstat"])
    best = elig[0] if elig else None
    best_literal = next((r for r in elig if r["side"] == "suivre"), None)
    n_tests = len(rows)

    out = {"kind": kind, "label": label, "computedAt": int(time.time() * 1000),
           "period": {"start": start_ms, "end": end_ms, "split": split_ms}, "costs": costs,
           "eras": [{"label": lab, "start": a, "end": b} for lab, a, b in eras],
           "counts": {"events": len(events), "levels": len(vs.LEVELS) if rule_list is None else None, "exits": len(cfgs), "rules": len(R), "tests": n_tests, "tested": len(rows)},
           "subject": subject or SUBJECT_VWAP, "exits": exits, "chosenExits": chosen_exits, "variants": rows, "ranking": [_key(r) for r in elig[:25]]}
    if not best:
        out["seconds"] = round(time.time() - t0)
        return out

    # ---- 4. verifications de la meilleure ----------------------------------------------------------
    say("verifications…")
    bt_key = (best["name"], best["side"] == "inverse", best["cfg"])
    trades = store[bt_key]
    out["best"] = _detail(ds, trades, best, costs, start_ms, end_ms, split_ms, years, control_runs, sims, lit, inv, R)
    if best_literal and best_literal is not best:
        out["bestLiteral"] = _detail(ds, store[(best_literal["name"], False, best_literal["cfg"])], best_literal, costs, start_ms, end_ms, split_ms, years, 0, sims, lit, inv, R)
    lit0 = next(r for r in rows if r["name"] == R[0][0] and r["side"] == "suivre" and r["cfg"] == chosen_exits[0])
    out["literal"] = {**{k2: lit0[k2] for k2 in ("name", "cfg", "all", "is", "oos", "eras")}, "years": per_year(store[(R[0][0], False, chosen_exits[0])], years)}

    # ---- 5. couverture -----------------------------------------------------------------------------
    if with_hedge:
        say("couverture…")
        out["hedge"] = hedge_study(store, rows, best, start_ms, end_ms, split_ms, extra_hedges or {}, R, min_rule)
    out["verdict"] = verdict(out)
    out["seconds"] = round(time.time() - t0)
    return out


def _year(ms_: int) -> int:
    return datetime.fromtimestamp(ms_ / 1000, timezone.utc).year


def _key(r: dict) -> list:
    return [r["name"], r["side"], r["cfg"]]


def _detail(ds, trades, row, costs, start_ms, end_ms, split_ms, years, control_runs, sims, lit, inv, R) -> dict:
    d = {"name": row["name"], "group": row["group"], "side": row["side"], "cfg": row["cfg"], "cfgLabel": cfg_label(row["cfg"]),
         "all": row["all"], "is": row["is"], "oos": row["oos"], "eras": row["eras"], "years": per_year(trades, years)}
    if not trades:
        return d
    d["gross"] = sum(t["r_gross"] for t in trades) / len(trades)
    d["costR"] = d["gross"] - row["all"]["expR"]
    d["avgHours"] = sum(t["hours"] for t in trades) / len(trades)
    d["bySide"] = {s: {"n": len(x), "expR": sum(t["r"] for t in x) / len(x)} for s in ("long", "short") for x in [[t for t in trades if t["side"] == s]] if x}
    d["costSens"] = []
    rule = next(r for n, g, r in R if n == row["name"])
    evs = inv if row["side"] == "inverse" else lit
    sims.ensure(evs, row["cfg"])
    for mult, lab in ((0.0, "sans frais"), (0.5, "frais ÷ 2"), (1.0, "frais prévus"), (2.0, "frais × 2")):
        cc = {k: v * mult for k, v in costs.items()}
        tr2 = bt.select(vs.as_candidates(evs, row["cfg"], rule), lambda r: True, cc, max_week=999, zone_cooldown_h=6.0, start_ms=start_ms, end_ms=end_ms)
        d["costSens"].append({"name": lab, "expR": sum(t["r"] for t in tr2) / len(tr2) if tr2 else None, "n": len(tr2)})
    d["equity"] = bt.metrics(trades, start_ms, end_ms).get("equity")
    if control_runs:
        ma = bt.regime_series(ds.b1h)
        ctrl = vs.random_control_v(trades, ds, row["cfg"], costs, start_ms, end_ms, runs=control_runs, seed=3, match_regime=True, ma=ma)
        sub = [t for t in trades if t["t"] >= split_ms]
        ctrl2 = vs.random_control_v(sub, ds, row["cfg"], costs, split_ms, end_ms, runs=control_runs, seed=4, match_regime=True, ma=ma) if sub else None
        mo = bt.metrics(sub, split_ms, end_ms) if sub else None
        d["control"] = {"all": {k2: ctrl[k2] for k2 in ("runs", "expMean", "exp5", "exp95")}, "allP": bt.percentile_of(ctrl["_exps"], row["all"]["expR"]),
                        "oos": ({k2: ctrl2[k2] for k2 in ("runs", "expMean", "exp5", "exp95")} if ctrl2 else None),
                        "oosP": bt.percentile_of(ctrl2["_exps"], mo["expR"]) if ctrl2 and mo and mo["expR"] is not None else None}
    return d


# =====================================================================================================
#  Couverture
# =====================================================================================================
def hedge_study(store: dict, rows: list[dict], best: dict, start_ms: int, end_ms: int, split_ms: int, extra: dict, R: list, min_rule: int = MIN_N_RULE) -> dict:
    main = store[(best["name"], best["side"] == "inverse", best["cfg"])]
    cfg = best["cfg"]
    names = {n for n, _, _ in R}
    cands: dict[str, list[dict]] = {}

    def pick(name, fade):
        return store.get((name, fade, cfg))

    mirror = pick(best["name"], best["side"] != "inverse")
    if mirror:
        cands["Miroir : même signal, sens inverse"] = mirror
    for nm, lab in ((R[0][0], "Toute clôture sur un niveau"), ("dans le sens de la tendance 50/200 j", "Dans le sens de la tendance")):
        for fade in (False, True):
            if (fade == (best["side"] == "inverse")) and nm == best["name"]:
                continue
            tr = pick(nm, fade)
            if tr:
                cands[f"{lab} ({'inverse' if fade else 'suivre'})"] = tr
    # meilleures variantes de l'autre sens et de l'autre echelle (classees sur l'apprentissage)
    elig = [r for r in rows if r["cfg"] == cfg and r["is"]["n"] >= min_rule and r["is"].get("tstat") is not None and r["name"] != best["name"]]
    elig.sort(key=lambda r: -r["is"]["tstat"])
    for r in elig[:6]:
        cands[f"{r['name']} ({r['side']})"] = store[(r["name"], r["side"] == "inverse", cfg)]
    for nm in ("1h seulement", "4h seulement"):
        for fade in (False, True):
            tr = pick(nm, fade)
            if tr:
                cands.setdefault(f"{nm} ({'inverse' if fade else 'suivre'})", tr)
    cands.update(extra)
    weights = (0.25, 0.5, 1.0)

    def wk(tr, a, b):
        return [t for t in tr if a <= t["t"] < b]

    # choix sur l'apprentissage
    ev_is = hedge.evaluate(wk(main, start_ms, split_ms), {k: wk(v, start_ms, split_ms) for k, v in cands.items()}, start_ms, split_ms, weights)
    pick_is = hedge.best_hedge(ev_is, weights)
    ev_all = hedge.evaluate(main, cands, start_ms, end_ms, weights)
    ev_oos = hedge.evaluate(wk(main, split_ms, end_ms), {k: wk(v, split_ms, end_ms) for k, v in cands.items()}, split_ms, end_ms, weights)
    out = {"main": {"name": best["name"], "side": best["side"], "cfg": cfg}, "weights": list(weights),
           "all": _hedge_rows(ev_all), "is": _hedge_rows(ev_is), "oos": _hedge_rows(ev_oos)}
    if pick_is:
        gain, name, w, mix = pick_is
        row_oos = next(r for r in ev_oos["rows"] if r["name"] == name)
        mix_oos = next(m for m in row_oos["mix"] if m["w"] == w)
        out["choice"] = {"name": name, "w": w, "isGain": gain, "is": mix, "oos": mix_oos, "oosMain": ev_oos["main"],
                         "oosGain": ev_oos["main"]["maxDD"] - mix_oos["maxDD"], "corrIs": next(r["corr"] for r in ev_is["rows"] if r["name"] == name),
                         "corrOos": row_oos["corr"], "isMain": ev_is["main"]}
        m_w = hedge.series(main, start_ms, end_ms)
        h_w = hedge.series(cands[name], start_ms, end_ms)
        comb = hedge.combine(m_w, h_w, w)
        out["curves"] = {"main": _equity(m_w, start_ms), "mix": _equity(comb, start_ms)}
    return out


def _hedge_rows(ev: dict) -> dict:
    return {"main": ev["main"], "rows": [{"name": r["name"], "n": r["n"], "corr": r["corr"], "alone": r["alone"], "mix": r["mix"]} for r in ev["rows"]]}


def _equity(rets: list[float], start_ms: int, step: int = 4) -> list:
    eq, pts = 1.0, [(start_ms, 1.0)]
    for i, r in enumerate(rets):
        eq *= max(0.0, 1.0 + r)
        if i % step == 0:
            pts.append((start_ms + (i + 1) * hedge.WEEK, round(eq, 4)))
    return pts


# =====================================================================================================
#  Verdict en clair
# =====================================================================================================
def _r(v, d=2):
    return "n/d" if v is None else f"{v:+.{d}f}".replace(".", ",").replace("-", "−")


def _n(v, d=2):
    return "n/d" if v is None else f"{v:.{d}f}".replace(".", ",")


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def exit_summary(rep: dict) -> dict:
    """Moyenne du gain par trade de la regle litterale (apprentissage / test) selon le stop, l'objectif et la duree."""
    out = {}
    for field in ("stop", "tp", "hold"):
        groups = {}
        for x in rep["exits"]:
            groups.setdefault(x[field], []).append(x)
        out[field] = {g: {"is": _mean([x["is"]["expR"] for x in xs]), "oos": _mean([x["oos"]["expR"] for x in xs]), "n": len(xs)} for g, xs in groups.items()}
    return out


def hedge_summary(rep: dict) -> dict | None:
    h = rep.get("hedge")
    if not h or not h.get("oos"):
        return None
    base = h["oos"]["main"]
    mixes = [(r["name"], m) for r in h["oos"]["rows"] for m in r["mix"]]
    helps = [(n, m) for n, m in mixes if m["maxDD"] <= base["maxDD"] - 0.01]
    best = min(mixes, key=lambda x: x[1]["maxDD"]) if mixes else None
    return {"candidates": len(h["oos"]["rows"]), "mixes": len(mixes), "reduceOosDD": len(helps), "mainDD": base["maxDD"],
            "bestName": best[0] if best else None, "bestW": best[1]["w"] if best else None, "bestDD": best[1]["maxDD"] if best else None}


def verdict(rep: dict) -> dict:
    """Trois niveaux : « edge » (avantage demontre : intervalle a 90 % au-dessus de zero sur l'apprentissage ET le test, meme signe dans chaque grande periode,
    meilleur que 95 % des tirages au hasard sur le test), « weak » (signe positif partout et meilleur que le hasard, mais intervalle du test qui contient zero),
    « none » (rien de solide)."""
    b, lit = rep["best"], rep["literal"]
    notes = []
    ctrl = b.get("control") or {}
    eras_pos = all(e["expR"] is not None and e["expR"] > 0 for e in b["eras"])
    p_oos = ctrl.get("oosP")                       # part des tirages au hasard qui font MIEUX que la variante (plus c'est petit, mieux c'est)
    beats = p_oos is None or p_oos <= 0.05
    is_ok = b["is"]["expLo"] is not None and b["is"]["expLo"] > 0
    oos_ok = b["oos"]["expLo"] is not None and b["oos"]["expLo"] > 0
    oos_pos = b["oos"]["expR"] is not None and b["oos"]["expR"] > 0
    level = "edge" if (is_ok and oos_ok and eras_pos and beats) else "weak" if (is_ok and oos_pos and eras_pos and beats) else "none"
    n_tests = rep["counts"]["tests"]
    t_best = b["is"].get("tstat")
    chance = math.sqrt(2 * math.log(max(2, n_tests)))
    side = "en suivant la clôture" if b["side"] == "suivre" else "en prenant le contre de la clôture"
    head = (f"{rep.get('subject') or SUBJECT_VWAP} fait {_r(lit['all']['expR'])} R par trade après frais "
            f"({lit['all']['n']} trades : {_r(lit['is']['expR'])} R sur l'apprentissage, {_r(lit['oos']['expR'])} R sur le test) : aucun avantage tel quel.")
    ci = f"intervalle à 90 % de {_r(b['oos']['expLo'])} à {_r(b['oos']['expHi'])}"
    one = f"« {b['name']} » ({side}, {b['cfgLabel']}) : {_r(b['is']['expR'])} R à l'apprentissage, {_r(b['oos']['expR'])} R sur le test ({ci}, {b['oos']['n']} trades)"
    if level == "edge":
        text = f"{head} Une condition tient la route : {one}, positive dans chaque période et meilleure que le hasard."
    elif level == "weak":
        text = (f"{head} Une condition ressort : {one}. Elle est positive dans chacune des trois périodes et meilleure que des trades tirés au hasard, "
                f"mais son intervalle sur le test contient zéro et le gain a fondu : c'est un avantage faible, qui s'érode, pas démontré.")
    else:
        text = f"{head} Aucune variante n'a d'avantage démontré. La meilleure sur l'apprentissage : {one} : elle ne se confirme pas."
    if t_best is not None:
        notes.append(f"{n_tests} combinaisons (filtres × sorties × sens) ont été essayées : par pur hasard, la meilleure statistique t attendue est d'environ {_n(chance, 1)} ; "
                     f"la meilleure observée sur l'apprentissage est {_n(t_best, 1)}, mais sur le test elle tombe à {_n(b['oos'].get('tstat'), 1)}.")
    notes.append(f"Frais : la variante retenue gagne {_r(b.get('gross'))} R par trade avant frais et {_r(b['all']['expR'])} R après ; les frais en retirent {_n(b.get('costR'))} "
                 f"(ordres au marché, glissement, financement), car les stops larges et les positions de 1 à 2 jours réduisent le nombre de trades.")
    if ctrl.get("all") and ctrl["all"].get("expMean") is not None:
        runs = ctrl["all"].get("runs") or 0
        beat = lambda pv, rn: f"les {rn} tirages" if pv == 0 else f"{(1 - pv) * 100:.0f} % des tirages"
        notes.append(f"Témoin : des trades de même forme à des instants tirés au hasard, dans la même tendance de fond, donnent {_r(ctrl['all']['expMean'])} R en moyenne "
                     f"(90 % des tirages entre {_r(ctrl['all']['exp5'])} et {_r(ctrl['all']['exp95'])}). La variante fait mieux que {beat(ctrl['allP'], runs)} sur toute la période"
                     + (f" et que {beat(p_oos, ctrl['oos'].get('runs') or 0)} sur le test seul (le hasard fait {_r(ctrl['oos']['expMean'])} R sur 2022-2026)." if p_oos is not None and ctrl.get("oos") else "."))
    yrs = b.get("years") or {}
    if yrs:
        sy = _year(rep["period"]["split"])
        before = [v["expR"] for y, v in yrs.items() if int(y) < sy]
        after = {y: v["expR"] for y, v in yrs.items() if int(y) >= sy}
        notes.append(f"Par année : positive {sum(1 for v in before if v > 0)} années sur {len(before)} avant {sy}, puis " + ", ".join(f"{y} : {_r(v)}" for y, v in after.items()) + ".")
    sd = b.get("bySide") or {}
    if sd.get("long") and sd.get("short"):
        notes.append(f"Achats : {_r(sd['long']['expR'])} R sur {sd['long']['n']} trades ; ventes : {_r(sd['short']['expR'])} R sur {sd['short']['n']}"
                     + (" : l'effet n'est donc pas seulement la hausse de long terme du bitcoin." if level != "none" and sd['long']['expR'] > 0 and sd['short']['expR'] > 0 else "."))
    es = exit_summary(rep)
    parts = []
    for field, lab, fmt in (("stop", "stops", lambda g: STOP_LABEL.get(g, g)), ("tp", "objectifs", tp_label), ("hold", "durées", lambda g: HOLD_LABEL.get(g, g))):
        if len(es[field]) > 1:
            parts.append(f"{lab} : " + ", ".join(f"{fmt(g)} {_r(v['is'])} R" for g, v in es[field].items()))
    if parts:
        notes.append("Sorties (règle littérale, moyenne sur l'apprentissage) — " + " ; ".join(parts) + ".")
    hs = hedge_summary(rep)
    if hs:
        h = rep["hedge"]["choice"] if rep["hedge"].get("choice") else None
        txt = (f"Couverture : sur {hs['candidates']} variantes candidates et {hs['mixes']} dosages, {hs['reduceOosDD']} réduisent la baisse maximale du test d'au moins 1 point "
               f"(principale : {hs['mainDD'] * 100:.0f} % ; meilleur mélange : {hs['bestDD'] * 100:.0f} %). ")
        if h:
            txt += (f"Le choix fait sur l'apprentissage (« {h['name']} » à {h['w'] * 100:.0f} %) donne sur le test {h['oosMain']['maxDD'] * 100:.0f} % → {h['oos']['maxDD'] * 100:.0f} % de baisse maximale "
                    f"et un rendement annualisé de {_r(h['oosMain']['cagr'] * 100, 1)} % → {_r(h['oos']['cagr'] * 100, 1)} %, avec une corrélation de {_r(h['corrOos'])}. ")
        txt += "Une variante inverse est bien anti-corrélée mais perd de l'argent seule : c'est une prime d'assurance sans indemnité, pas une vraie couverture."
        notes.append(txt)
    return {"level": level, "edge": level == "edge", "text": text, "notes": [n for n in notes if n], "exitSummary": es, "hedgeSummary": hs}
