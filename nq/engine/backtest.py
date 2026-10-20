"""Backtest des setups de scalping, CORRÉLÉ aux règles Lucid. Module PUR.

On rejoue l'historique barre par barre, SANS jamais regarder le futur :
  - à la clôture de la barre i, on calcule le profil, le CVD, les niveaux et les setups À PARTIR DES SEULES BARRES ≤ i (un `BarMarket` qui
    n'expose que le passé) ;
  - si un setup passe le score minimal, qu'aucune position n'est ouverte et que les règles l'autorisent, on ENTRE à l'ouverture de la barre
    suivante (i+1) — la décision ne voit donc jamais la bougie sur laquelle elle s'exécute ;
  - la position est gérée barre par barre : stop, objectif (si les deux sont touchés dans la même barre, on suppose le STOP d'abord, prudent),
    fermeture forcée à 16 h 45 ET, et stop de temps.
On applique de VRAIS frais (table Lucid) et un glissement. Puis on passe les P&L par journée dans les règles Lucid (`engine/risk.py`) :
évaluation validée ? plancher touché ? consistance 50 % respectée ? retrait possible ? part de micro-scalping ? — pour répondre à
« backtest et voir si corrélé avec les règles ».

Ce n'est pas une garantie : un backtest sur-estime toujours un peu (pas de file d'attente réelle, glissement supposé constant). Il sert à
mesurer et comparer des réglages, pas à promettre un résultat."""
import math
from bisect import bisect_left
from dataclasses import dataclass, field

from . import clock, risk, signals, vp
from .bars import TF_MS, atr, resample
from .footprint import Ladder
from .levels import build as levels_build
from .levels import nearest as levels_nearest


class _DayBars:
    """Barres de base d'UNE journée de trading, et les ladders (gx / rth) développées jusqu'à un instant donné (incrémental, monotone)."""
    def __init__(self, tick):
        self.tick = tick
        self.bars = []            # (t_ouverture, Bar) triées
        self.gx = Ladder(tick)
        self.rth = Ladder(tick)
        self._i_gx = 0            # index de la prochaine barre à verser dans gx / rth
        self._i_rth = 0
        self.rth_a = self.rth_b = None

    def feed_gx(self, upto):
        while self._i_gx < len(self.bars) and self.bars[self._i_gx][0] < upto:
            self.gx.add_rows(self.bars[self._i_gx][1].fp)
            self._i_gx += 1

    def feed_rth(self, upto):
        if self.rth_a is None:
            return
        while self._i_rth < len(self.bars):
            t, b = self.bars[self._i_rth]
            if t >= upto:
                break
            if self.rth_a <= t < self.rth_b:
                self.rth.add_rows(b.fp)
            self._i_rth += 1


class BarMarket:
    """Imite l'interface de lecture de `Market` dont `levels.build` et le reste ont besoin, mais à partir d'une LISTE de barres et en ne révélant
    que le passé (jusqu'à `now`). Avance de façon monotone : `advance(t)` verse les barres ≤ t dans les ladders du jour."""
    class _NullLock:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def __init__(self, inst, base_bars):
        self.inst = inst
        self.lock = self._NullLock()
        self.days = {}                 # jour -> _DayBars
        self._order = []               # jours triés
        for b in base_bars:
            day = clock.trading_day(b.t)
            d = self.days.get(day)
            if d is None:
                d = self.days[day] = _DayBars(inst.tick)
                a, bb = clock.window(day, "rth")
                d.rth_a, d.rth_b = a, bb
            d.bars.append((b.t, b))
        self._order = sorted(self.days)
        for d in self.days.values():
            d.bars.sort(key=lambda x: x[0])
            d.ts = [t for t, _ in d.bars]            # ouvertures, pour borner les fenêtres par dichotomie
        self._now = None
        self._last_price = None
        self._ohlc_cache = {}                        # (jour, fenêtre) -> OHLC d'une fenêtre entièrement passée (constante)

    def advance(self, now_ms, price):
        self._now = now_ms
        self._last_price = price
        day = clock.trading_day(now_ms)
        d = self.days.get(day)
        if d:
            d.feed_gx(now_ms)
            d.feed_rth(now_ms)

    # --- interface lue par levels.build / signals ---
    @property
    def price(self):
        return self._last_price

    def now_ms(self):
        return self._now

    def day(self):
        return clock.trading_day(self._now) if self._now else None

    def prev_day(self, day=None):
        day = day or self.day()
        cand = [d for d in self._order if d < day and self.days[d].rth.volume > 0]
        return max(cand) if cand else None

    def ladder(self, day, kind):
        d = self.days.get(day)
        if d is None:
            return None
        if day == self.day():                     # jour en cours : seulement ce qui est déjà « arrivé »
            return d.rth if kind == "rth" else d.gx
        return d.rth if kind == "rth" else d.gx    # jour passé : complet

    def window_ohlc(self, day, name):
        d = self.days.get(day)
        if d is None:
            return None
        a, b = clock.window(day, name)
        end = b if self._now is None else min(b, self._now)       # on ne révèle que le passé
        if end <= a:
            return None
        past = end >= b                                           # fenêtre entièrement close : son OHLC ne bougera plus
        ck = (day, name)
        if past and ck in self._ohlc_cache:
            return self._ohlc_cache[ck]
        i0 = bisect_left(d.ts, a)
        i1 = bisect_left(d.ts, end)
        if i1 <= i0:
            return None
        sub = [d.bars[k][1] for k in range(i0, i1)]
        o = {"o": sub[0].o, "h": max(x.h for x in sub), "l": min(x.l for x in sub), "c": sub[-1].c, "t0": sub[0].t, "t1": sub[-1].t}
        if past:
            self._ohlc_cache[ck] = o
        return o


@dataclass
class BtParams:
    tf: str = "1m"                   # unité de temps des signaux
    min_score: float = 40.0          # score minimal pour prendre un trade
    slippage_ticks: float = 1.0      # glissement à l'entrée ET à la sortie au marché (ticks)
    max_hold_min: int = 20           # stop de temps : on sort après N minutes
    risk_usd: float = 100.0          # risque visé par trade (sert au dimensionnement)
    one_per_session: bool = False    # au plus un trade par séance régulière (discipline)
    target_index: int = 0            # objectif visé (0 = le premier)
    limit_through_ticks: int = 1     # un objectif (ordre limite) n'est rempli que si le prix le DÉPASSE de N ticks (file d'attente) ; 0 = toucher suffit
    signal_params: signals.Params = field(default_factory=lambda: signals.Params())


def _size(stop_pts, inst, profile, risk_usd):
    per = stop_pts * inst.point_value + profile.fee_rt.get(inst.root, 0.0)
    if per <= 0:
        return 0
    n = int(math.floor(risk_usd / per))
    cap = profile.max_micros if inst.mini_equiv < 1 else profile.max_minis       # MNQ / MES : plafond en micros
    return max(0, min(n, cap))


class Tape:
    """Décisions de setup pré-calculées pour CHAQUE barre de signal (à sa clôture, sans regarder le futur), indépendantes du score minimal, du
    glissement, du stop de temps et du risque. Le coût (profil, niveaux, setups) est payé une fois ; `simulate` rejoue ensuite autant de réglages
    qu'on veut en quelques millisecondes (test de robustesse)."""
    def __init__(self, tf, step, bars, rows):
        self.tf = tf
        self.step = step
        self.bars = bars            # barres de signal
        self.rows = rows            # par barre : (now, jour, fermeture forcée, séance commencée, bloqué, meilleur setup ou None)

    @property
    def days(self):
        return sorted({r[1] for r in self.rows})


def prepare(base_bars, inst, tf="1m", signal_params: signals.Params = None, max_bars: int = 20000):
    """Calcule la `Tape` d'un historique. None s'il y a trop peu de barres."""
    if tf not in TF_MS:
        raise ValueError(f"unité de temps inconnue : {tf}")
    base = list(base_bars)[-max_bars:]
    if len(base) < 30:
        return None
    step = TF_MS[tf]
    sig_bars = base if tf == "1m" else resample(base, step, with_fp=True)
    mk = BarMarket(inst, base)
    sp = signals.Params(**{**(signal_params or signals.Params()).__dict__, "min_score": 0.0})   # on garde tout : le seuil est appliqué ensuite
    stats_cache = {}                                # partagé : évite de recalculer le profil de la veille à chaque barre
    window = max(sp.look + 20, 140)                 # on ne passe aux signaux que la fin : évite un coût quadratique

    cvd_cache, _acc, _key = [], 0.0, None           # CVD cumulé par journée Globex, construit incrémentalement (O(1) par barre)
    for b in sig_bars:
        k = clock.trading_day(b.t)
        if k != _key:
            _key, _acc = k, 0.0
        _acc += b.bv - b.sv
        cvd_cache.append(_acc)

    rows = []
    for i, bar in enumerate(sig_bars):
        now = bar.t + step                              # décision à la CLÔTURE de la barre i
        mk.advance(now, bar.c)
        day = clock.trading_day(now)
        ff = clock.forced_flat(day)
        rth_started = now >= clock.window(day, "rth")[0]
        top, blocked = None, False
        lv = levels_build(mk, zone_pts=6.0, stats_cache=stats_cache)
        if lv["price"] is not None:
            near = levels_nearest(lv["levels"], lv["price"], 3)
            lad = mk.ladder(day, "rth") if rth_started else mk.ladder(day, "gx")
            prof = vp.stats(lad, min_row_ticks=4, cache=stats_cache) if lad is not None and not lad.empty() else None
            lo = max(0, i - window + 1)
            res = signals.evaluate(sig_bars[lo:i + 1], cvd_cache[lo:i + 1], prof, near, lv["zones"], inst, now, ff, clock.phase(now),
                                   rth_started, acct=None, params=sp)
            blocked = bool(res["blocked"])
            if res["setups"]:
                s = res["setups"][0]
                top = {"side": s["side"], "kind": s["kind"], "score": s["score"], "stop": s["stop"], "targets": list(s["targets"])}
        rows.append((now, day, ff, rth_started, blocked, top))
    return Tape(tf, step, sig_bars, rows)


def _exit_on(bar, pos, tick, through):
    """Sortie éventuelle d'une position sur `bar` : (prix, raison) ou (None, None). Stop d'abord si les deux sont touchés (prudent). Un stop
    sauté par un écart d'ouverture est exécuté à l'ouverture (plus mauvais que le stop). L'objectif doit être dépassé de `through` ticks."""
    if pos["side"] == "long":
        if bar.l <= pos["stop"]:
            return (min(pos["stop"], bar.o), "stop")
        if bar.h >= pos["target"] + through * tick:
            return (pos["target"], "objectif")
    else:
        if bar.h >= pos["stop"]:
            return (max(pos["stop"], bar.o), "stop")
        if bar.l <= pos["target"] - through * tick:
            return (pos["target"], "objectif")
    return (None, None)


def simulate(tape: Tape, inst, profile: risk.PropProfile, params: BtParams = None) -> dict:
    """Rejoue la `Tape` avec des réglages donnés. Chaque barre : 1) on gère la position ouverte SUR cette barre (y compris la barre d'entrée :
    l'entrée se fait à son ouverture, son plus haut / plus bas viennent après) ; 2) à la clôture, si à plat, on décide ; entrée à l'ouverture
    de la barre suivante."""
    params = params or BtParams()
    sig_bars, rows, step = tape.bars, tape.rows, tape.step
    sp = params.signal_params
    tick = inst.tick
    trades, pos, traded_this_session = [], None, set()

    def close(bar, exit_p, reason):
        sgn = 1 if pos["side"] == "long" else -1
        # objectif = ordre limite posé au prix : pas de glissement. Stop / 16h45 / temps / fin = sortie au marché, glissement défavorable.
        fill = exit_p if reason == "objectif" else exit_p - sgn * params.slippage_ticks * tick
        gross = (fill - pos["entry"]) * sgn * inst.point_value * pos["qty"]
        fee = profile.fee_rt.get(inst.root, 0.0) * pos["qty"]
        same = bar.t == pos["t_entry"]                  # sortie dans la barre d'entrée : durée inconnue (0 à 1 barre)
        trades.append({**{k: v for k, v in pos.items() if k != "ff"}, "exit": round(fill, 2), "reason": reason, "gross": round(gross, 2), "fee": round(fee, 2),
                       "net": round(gross - fee, 2), "t_exit": bar.t + step,          # connu au plus tard à la clôture de la barre
                       "holdS": round((bar.t - pos["t_entry"]) / 1000.0, 1), "sameBar": same, "day": clock.trading_day(pos["t_entry"])})

    for i, bar in enumerate(sig_bars):
        now, day, ff, rth_started, blocked, top = rows[i]
        if pos and (bar.t >= pos["ff"] or clock.trading_day(bar.t) != pos["day"]):
            # trou de données jusqu'après 16 h 45 (jour férié écourté, enregistreur coupé) : Lucid a fermé la position à 16 h 45 ;
            # on la clôture à la dernière clôture connue de SA journée, jamais sur les prix de la séance suivante
            close(sig_bars[i - 1], sig_bars[i - 1].c, "16h45")
            pos = None
        if pos:
            if bar.t < pos["ff"] < bar.t + step:
                # barre à cheval sur 16 h 45 (unités de 30 min, 1 h) : ce qui suit 16 h 45 n'existe pas pour le compte. Le stop compte
                # (prudent), pas l'objectif ; sinon sortie à l'ouverture de la barre, dernier prix connu avant la fermeture forcée
                ex = _exit_on(bar, dict(pos, target=float("inf") if pos["side"] == "long" else float("-inf")), tick, 0)
                close(bar, *(ex if ex[0] is not None else (bar.o, "16h45")))
                pos = None
                continue
            exit_p, reason = _exit_on(bar, pos, tick, params.limit_through_ticks)
            if exit_p is None and now >= pos["ff"]:                                # fermeture forcée 16 h 45
                exit_p, reason = bar.c, "16h45"
            if exit_p is None and (now - pos["t_entry"]) >= params.max_hold_min * 60_000:
                exit_p, reason = bar.c, "temps"
            if exit_p is not None:
                close(bar, exit_p, reason)
                pos = None
        if pos or i + 1 >= len(sig_bars):
            continue
        # --- décision à la clôture (uniquement si à plat) ---
        if blocked or top is None or top["score"] < params.min_score:
            continue
        if params.one_per_session and rth_started and (day in traded_this_session):
            continue
        nxt = sig_bars[i + 1]
        if nxt.t + step > ff - sp.flat_guard_min * 60_000:     # la barre d'entrée doit finir avant la marge de sécurité de 16 h 45
            continue
        if clock.trading_day(nxt.t) != day or nxt.t - bar.t > 3 * step:     # trou de données / changement de journée : pas d'entrée à l'aveugle
            continue
        sgn = 1 if top["side"] == "long" else -1
        entry = nxt.o + sgn * params.slippage_ticks * tick
        stop = top["stop"]
        if (stop - entry) * sgn >= 0:                   # l'ouverture a déjà franchi le stop : setup invalidé
            continue
        stop_pts = abs(entry - stop)
        if stop_pts < tick:
            continue
        qty = _size(stop_pts, inst, profile, params.risk_usd)
        if qty <= 0:
            continue
        ti = min(params.target_index, len(top["targets"]) - 1)
        target = top["targets"][ti]
        if (target - entry) * sgn <= 0:                 # l'ouverture a déjà dépassé l'objectif : plus rien à gagner
            continue
        pos = {"side": top["side"], "kind": top["kind"], "entry": round(entry, 2), "stop": round(stop, 2),
               "target": target, "qty": qty, "score": top["score"], "t_entry": nxt.t, "ff": ff, "day": day}
        traded_this_session.add(day)

    if pos:                                             # fin de l'historique : on clôture à la dernière clôture connue
        close(sig_bars[-1], sig_bars[-1].c, "fin")
    return _summary(trades, inst, profile, len(tape.days))


def run(base_bars, inst, profile: risk.PropProfile, params: BtParams = None, max_bars: int = 20000) -> dict:
    """Rejoue `base_bars` (barres de base, footprint inclus) et renvoie trades, P&L par jour, statistiques et la conformité aux règles Lucid."""
    params = params or BtParams()
    tape = prepare(base_bars, inst, params.tf, params.signal_params, max_bars)
    if tape is None:
        return {"ok": False, "msg": "pas assez de barres pour un backtest", "trades": [], "days": []}
    return simulate(tape, inst, profile, params)


def sweep(tape: Tape, inst, profile: risk.PropProfile, base: BtParams = None, scores=(30, 40, 50, 60, 70), slippages=(1, 2)) -> dict:
    """Test de robustesse : rejoue la même `Tape` sur une grille score minimal × glissement, et sépare chaque résultat en DÉBUT d'historique
    (« in-sample », ~2/3 des jours) et FIN (« out-of-sample », le reste). On choisit le meilleur réglage sur le début seulement, puis on regarde
    ce qu'il donne sur la fin : s'il s'effondre, le « meilleur » réglage n'était que de la chance (sur-optimisation)."""
    base = base or BtParams()
    days = tape.days
    if len(days) < 3:
        return {"ok": False, "msg": "il faut au moins 3 journées pour séparer début et fin d'historique"}
    cut = days[max(1, (2 * len(days)) // 3) - 1]         # dernier jour de la partie « début »
    grid = []
    for sl in slippages:
        for sc in scores:
            p = BtParams(**{**base.__dict__, "min_score": float(sc), "slippage_ticks": float(sl)})
            r = simulate(tape, inst, profile, p)
            ins = [t for t in r["trades"] if t["day"] <= cut]
            oos = [t for t in r["trades"] if t["day"] > cut]
            grid.append({"minScore": sc, "slippage": sl, "nTrades": r["nTrades"], "net": r["net"], "profitFactor": r["profitFactor"],
                         "winRate": r["winRate"], "evalPassed": r["rules"]["evalPassed"], "floorBreach": bool(r["rules"]["floorBreach"]),
                         "inNet": round(sum(t["net"] for t in ins), 2), "inN": len(ins),
                         "outNet": round(sum(t["net"] for t in oos), 2), "outN": len(oos)})
    ref = [g for g in grid if g["slippage"] == min(slippages)]
    best = max(ref, key=lambda g: (g["inNet"], -g["minScore"]))
    pos_out = sum(1 for g in grid if g["outNet"] > 0)
    return {"ok": True, "grid": grid, "cut": cut, "inDays": len([d for d in days if d <= cut]), "outDays": len([d for d in days if d > cut]),
            "best": best, "robust": best["inNet"] > 0 and best["outNet"] > 0, "positiveOut": pos_out, "total": len(grid)}


def _summary(trades, inst, profile, n_days: int | None = None) -> dict:
    by_day, low_day, run_day = {}, {}, {}
    for t in sorted(trades, key=lambda x: x["t_exit"]):
        d = t["day"]
        by_day[d] = round(by_day.get(d, 0.0) + t["net"], 2)
        run_day[d] = run_day.get(d, 0.0) + t["net"]
        low_day[d] = round(min(low_day.get(d, 0.0), run_day[d]), 2)        # creux réalisé de la journée (≤ 0)
    days = sorted(by_day.items())
    day_pnls = [v for _, v in days]

    # conformité aux règles d'évaluation, jour après jour (comme le vit le compte) : plancher touché en cours de journée si le creux réalisé
    # l'atteint ; évaluation validée le premier jour où cible ET consistance sont réunies, avant toute violation
    floor_breach, passed_on = None, None
    bal = profile.start_balance
    led_floor = profile.start_balance - profile.max_drawdown
    peak = profile.start_balance
    lock = risk.locked_level(profile)
    seen = []
    for d, v in days:
        if passed_on is not None:                       # l'évaluation s'arrête le jour où elle est validée : la suite n'est plus jugée
            break
        if floor_breach is None and bal + low_day.get(d, 0.0) <= led_floor + 1e-9:
            floor_breach = {"day": d, "balance": round(bal + low_day[d], 2), "floor": led_floor, "intraday": True}
        bal = round(bal + v, 2)
        seen.append(v)
        if bal <= led_floor + 1e-9 and floor_breach is None:
            floor_breach = {"day": d, "balance": bal, "floor": led_floor, "intraday": False}
        if floor_breach is None and passed_on is None and bal - profile.start_balance >= profile.profit_target - 1e-6 \
                and risk.consistency(seen, profile)["ok"]:
            passed_on = d
        if profile.dd_mode == "eod_trailing":
            peak = max(peak, bal)
            nf = peak - profile.max_drawdown
            if lock is not None:
                nf = min(nf, lock)
            led_floor = max(led_floor, nf)
    cons = risk.consistency(seen if passed_on else day_pnls, profile)      # jugée sur les jours de l'évaluation
    profit = round(bal - profile.start_balance, 2)
    eval_passed = passed_on is not None

    wins = [t for t in trades if t["net"] > 0]
    losses = [t for t in trades if t["net"] <= 0]
    gw = sum(t["net"] for t in wins)
    gl = -sum(t["net"] for t in losses)
    short_wins = sum(t["net"] for t in wins if t["holdS"] <= risk.MICRO_HOLD_SECONDS)

    by_kind = {}
    for t in trades:
        k = t["kind"]
        a = by_kind.setdefault(k, {"n": 0, "net": 0.0, "wins": 0})
        a["n"] += 1
        a["net"] = round(a["net"] + t["net"], 2)
        a["wins"] += 1 if t["net"] > 0 else 0
    for a in by_kind.values():
        a["winRate"] = round(a["wins"] / a["n"], 3) if a["n"] else 0.0

    equity, run = [], profile.start_balance
    for d, v in days:
        run = round(run + v, 2)
        equity.append({"day": d, "balance": run})

    return {
        "ok": True, "trades": trades, "nTrades": len(trades),
        "days": [{"day": d, "pnl": v, "low": low_day.get(d, 0.0)} for d, v in days], "equity": equity,
        "nDays": n_days if n_days is not None else len(days),
        "net": round(sum(t["net"] for t in trades), 2), "fees": round(sum(t["fee"] for t in trades), 2),
        "winRate": round(len(wins) / len(trades), 3) if trades else 0.0,
        "avgWin": round(gw / len(wins), 2) if wins else 0.0, "avgLoss": round(-gl / len(losses), 2) if losses else 0.0,
        "expectancy": round(sum(t["net"] for t in trades) / len(trades), 2) if trades else 0.0,
        "profitFactor": round(gw / gl, 2) if gl > 0 else None,
        "byKind": by_kind, "byReason": _by_reason(trades),
        # barres d'1 min : un trade sorti DANS sa barre d'entrée a duré entre 0 et 60 s, on le compte comme micro -> c'est un MAJORANT
        "microShare": round(short_wins / gw, 3) if gw > 0 else None, "microLimit": risk.MICRO_PROFIT_SHARE, "microUpperBound": True,
        "rules": {
            "profit": profit, "target": profile.profit_target, "evalPassed": eval_passed, "passedOn": passed_on,
            "floorBreach": floor_breach, "consistency": {"ok": cons["ok"], "best": cons["best"], "ratio": cons["ratio"], "needed": cons["needed"]},
            "daysTraded": len([v for v in day_pnls if v != 0]), "finalBalance": round(bal, 2),
        },
    }


def _by_reason(trades) -> dict:
    out = {}
    for t in trades:
        out[t["reason"]] = out.get(t["reason"], 0) + 1
    return out
