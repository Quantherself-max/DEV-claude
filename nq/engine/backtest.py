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
    slippage_ticks: float = 1.0      # glissement à l'entrée ET à la sortie (ticks)
    max_hold_min: int = 20           # stop de temps : on sort après N minutes
    risk_usd: float = 100.0          # risque visé par trade (sert au dimensionnement)
    one_per_session: bool = False    # au plus un trade par séance régulière (discipline)
    target_index: int = 0            # objectif visé (0 = le premier)
    signal_params: signals.Params = field(default_factory=lambda: signals.Params())


def _size(stop_pts, inst, profile, risk_usd):
    per = stop_pts * inst.point_value + profile.fee_rt.get(inst.root, 0.0)
    if per <= 0:
        return 0
    n = int(math.floor(risk_usd / per))
    return max(0, min(n, profile.max_minis))


def run(base_bars, inst, profile: risk.PropProfile, params: BtParams = None, max_bars: int = 20000) -> dict:
    """Rejoue `base_bars` (barres de base, footprint inclus) et renvoie trades, P&L par jour, statistiques et la conformité aux règles Lucid."""
    params = params or BtParams()
    if params.tf not in TF_MS:
        raise ValueError(f"unité de temps inconnue : {params.tf}")
    base = list(base_bars)[-max_bars:]
    if len(base) < 30:
        return {"ok": False, "msg": "pas assez de barres pour un backtest", "trades": [], "days": []}
    step = TF_MS[params.tf]
    sig_bars = base if step == TF_MS["1m"] and params.tf == "1m" else resample(base, step, with_fp=True)
    mk = BarMarket(inst, base)
    sp = params.signal_params
    sp = signals.Params(**{**sp.__dict__, "min_score": params.min_score})
    stats_cache = {}                                # partagé : évite de recalculer le profil de la veille à chaque barre

    trades = []
    pos = None                      # position ouverte : dict
    traded_this_session = set()
    tick = inst.tick
    window = max(sp.look + 20, 140)                 # on ne passe aux signaux que la fin : évite un coût quadratique

    cvd_cache, _acc, _key = [], 0.0, None           # CVD cumulé par journée Globex, construit incrémentalement (O(1) par barre)
    for b in sig_bars:
        k = clock.trading_day(b.t)
        if k != _key:
            _key, _acc = k, 0.0
        _acc += b.bv - b.sv
        cvd_cache.append(_acc)

    for i in range(len(sig_bars) - 1):
        bar = sig_bars[i]
        nxt = sig_bars[i + 1]
        now = bar.t + step                              # décision à la CLÔTURE de la barre i
        mk.advance(now, bar.c)
        day = clock.trading_day(now)
        ff = clock.forced_flat(day)
        ph = clock.phase(now)
        rth_a = clock.window(day, "rth")[0]
        rth_started = now >= rth_a

        # --- gérer une position ouverte sur la barre i+1 (déjà connue : on la vit tick-max/tick-min) ---
        if pos:
            exit_p, reason = None, None
            if pos["side"] == "long":
                if nxt.l <= pos["stop"]:
                    exit_p, reason = pos["stop"], "stop"
                elif nxt.h >= pos["target"]:
                    exit_p, reason = pos["target"], "objectif"
            else:
                if nxt.h >= pos["stop"]:
                    exit_p, reason = pos["stop"], "stop"
                elif nxt.l <= pos["target"]:
                    exit_p, reason = pos["target"], "objectif"
            if exit_p is None and nxt.t + step >= ff > pos["t_entry"]:      # fermeture forcée 16 h 45
                exit_p, reason = nxt.c, "16h45"
            if exit_p is None and (nxt.t - pos["t_entry"]) >= params.max_hold_min * 60_000:
                exit_p, reason = nxt.c, "temps"
            if exit_p is not None:
                sgn = 1 if pos["side"] == "long" else -1
                # objectif = ordre limite posé au prix : pas de glissement. Stop / 16h45 / temps = sortie au marché, glissement défavorable.
                fill = exit_p if reason == "objectif" else exit_p - sgn * params.slippage_ticks * tick
                gross = (fill - pos["entry"]) * sgn * inst.point_value * pos["qty"]
                fee = profile.fee_rt.get(inst.root, 0.0) * pos["qty"]
                hold_s = (nxt.t - pos["t_entry"]) / 1000.0
                trades.append({**pos, "exit": round(fill, 2), "reason": reason, "gross": round(gross, 2), "fee": round(fee, 2),
                               "net": round(gross - fee, 2), "t_exit": nxt.t, "holdS": round(hold_s, 1),
                               "day": clock.trading_day(pos["t_entry"])})
                pos = None

        if pos:                                         # toujours en position : pas de nouvelle entrée
            continue

        # --- chercher un setup (uniquement si à plat) ---
        lv = levels_build(mk, zone_pts=6.0, stats_cache=stats_cache)
        if lv["price"] is None:
            continue
        near = levels_nearest(lv["levels"], lv["price"], 3)
        lad = mk.ladder(day, "rth") if rth_started else mk.ladder(day, "gx")
        prof = vp.stats(lad, min_row_ticks=4, cache=stats_cache) if lad is not None and not lad.empty() else None
        lo = max(0, i - window + 1)
        res = signals.evaluate(sig_bars[lo:i + 1], cvd_cache[lo:i + 1], prof, near, lv["zones"], inst, now, ff, ph, rth_started, acct=None, params=sp)
        if res["blocked"] or not res["setups"]:
            continue
        if params.one_per_session and rth_started and (day in traded_this_session):
            continue
        s = res["setups"][0]
        if 0 <= (ff - now) / 60_000 <= sp.flat_guard_min:
            continue
        # entrée à l'ouverture de i+1, avec glissement défavorable
        sgn = 1 if s["side"] == "long" else -1
        entry = nxt.o + sgn * params.slippage_ticks * tick
        stop = s["stop"]
        stop_pts = abs(entry - stop)
        if stop_pts < tick:
            continue
        qty = _size(stop_pts, inst, profile, params.risk_usd)
        if qty <= 0:
            continue
        ti = min(params.target_index, len(s["targets"]) - 1)
        pos = {"side": s["side"], "kind": s["kind"], "entry": round(entry, 2), "stop": round(stop, 2),
               "target": s["targets"][ti], "qty": qty, "score": s["score"], "t_entry": nxt.t}
        traded_this_session.add(day)

    return _summary(trades, inst, profile)


def _summary(trades, inst, profile) -> dict:
    by_day = {}
    for t in trades:
        by_day[t["day"]] = round(by_day.get(t["day"], 0.0) + t["net"], 2)
    days = sorted(by_day.items())
    day_pnls = [v for _, v in days]

    # conformité aux règles d'évaluation
    closed = [(d, v) for d, v in days]
    floor_breach = None
    bal = profile.start_balance
    led_floor = profile.start_balance - profile.max_drawdown
    peak = profile.start_balance
    for d, v in days:
        bal = round(bal + v, 2)
        if bal <= led_floor + 1e-9 and floor_breach is None:
            floor_breach = {"day": d, "balance": bal, "floor": led_floor}
        peak = max(peak, bal)
        nf = peak - profile.max_drawdown
        lock = risk.locked_level(profile)
        if lock is not None:
            nf = min(nf, lock)
        led_floor = max(led_floor, nf)
    cons = risk.consistency(day_pnls, profile)
    profit = round(bal - profile.start_balance, 2)
    eval_passed = floor_breach is None and profit >= profile.profit_target - 1e-6 and cons["ok"]

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
        "days": [{"day": d, "pnl": v} for d, v in days], "equity": equity,
        "net": round(sum(t["net"] for t in trades), 2), "fees": round(sum(t["fee"] for t in trades), 2),
        "winRate": round(len(wins) / len(trades), 3) if trades else 0.0,
        "avgWin": round(gw / len(wins), 2) if wins else 0.0, "avgLoss": round(-gl / len(losses), 2) if losses else 0.0,
        "expectancy": round(sum(t["net"] for t in trades) / len(trades), 2) if trades else 0.0,
        "profitFactor": round(gw / gl, 2) if gl > 0 else None,
        "byKind": by_kind, "byReason": _by_reason(trades),
        "microShare": round(short_wins / gw, 3) if gw > 0 else None, "microLimit": risk.MICRO_PROFIT_SHARE,
        "rules": {
            "profit": profit, "target": profile.profit_target, "evalPassed": eval_passed,
            "floorBreach": floor_breach, "consistency": {"ok": cons["ok"], "best": cons["best"], "ratio": cons["ratio"], "needed": cons["needed"]},
            "daysTraded": len([v for v in day_pnls if v != 0]), "finalBalance": round(bal, 2),
        },
    }


def _by_reason(trades) -> dict:
    out = {}
    for t in trades:
        out[t["reason"]] = out.get(t["reason"], 0) + 1
    return out
