"""Service : relie la source de donnees, le marche, le compte et les vues JSON servies au navigateur."""
import logging
import threading
import time
from dataclasses import replace
from pathlib import Path

from data.base import DataError
from data.filefeed import CsvSource, selftest_file
from data.simulated import SimulatedSource
from engine import clock, context, cvd, events, footprint, levels, risk, vp, vwap
from engine.account import Account
from engine.bars import TF_MS, resample
from engine.instruments import INSTRUMENTS, front_contract
from engine.market import Market

VERSION = "0.2"
log = logging.getLogger("nq")
SIM_BASE = {"NQ": 25_000.0, "MNQ": 25_000.0, "ES": 6_700.0, "MES": 6_700.0}


def make_source(cfg):
    inst = INSTRUMENTS[cfg.instrument]
    if cfg.source == "csv":
        return CsvSource(cfg.csv_path, cfg.csv_tz, cfg.csv_columns or None, cfg.csv_buy_codes, cfg.csv_sell_codes)
    now_fn = None
    if cfg.sim_start:                                        # rejoue une seance simulee : l'horloge part de l'heure demandee puis avance normalement
        from datetime import datetime, timezone
        d = datetime.fromisoformat(cfg.sim_start.replace("Z", "+00:00"))
        start = int((d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp() * 1000)
        offset = start - int(time.time() * 1000)
        now_fn = lambda: int(time.time() * 1000) + offset
    return SimulatedSource(inst, days=cfg.sim_days, base=SIM_BASE[inst.root], now_fn=now_fn)


def parse_position(text) -> dict | None:
    """« long,NQ,2,25012.25 » -> position ouverte saisie dans le terminal (le terminal ne lit pas ta plateforme). None si vide ou invalide."""
    try:
        side, root, qty, entry = (x.strip() for x in str(text).split(","))
        side, root = side.lower(), root.upper()
        qty, entry = int(float(qty)), float(entry)
    except (ValueError, AttributeError, OverflowError):
        return None
    if side not in ("long", "short") or root not in INSTRUMENTS or qty <= 0 or entry <= 0:
        return None
    return {"side": side, "root": root, "qty": qty, "entry": entry}


class Service:
    def __init__(self, cfg, source=None, account: Account | None = None):
        self.cfg = cfg
        inst = INSTRUMENTS[cfg.instrument]
        if cfg.big_lot:
            inst = replace(inst, big_lot=cfg.big_lot)
        self.inst = inst
        self.market = Market(inst)
        self.source = source or make_source(cfg)
        self.account = account or Account(Path(cfg.data_dir) / "compte.json", now_ms=self.now_ms)
        self.events_path = Path(cfg.data_dir) / "events.json"
        self._events = (None, [])
        self.status = {"state": "loading", "msg": "Chargement de l'historique…"}
        self.loaded = False
        self.started = time.time()
        self.stop_ev = threading.Event()
        self.thread = None

    def now_ms(self) -> int:
        return self.source.now_ms()

    # ---------- alimentation ----------
    def load_sync(self) -> int:
        """Charge l'historique de la source. Renvoie le nombre de transactions. En cas d'erreur de donnees : etat « error », on reessaiera."""
        try:
            n = self.market.ingest_many(self.source.history(self.now_ms()))
        except DataError as e:
            self.market = Market(self.inst)                      # lecture interrompue a mi-chemin : on repart d'un marche vide (sinon la reprise doublerait les volumes deja lus)
            self.status = {"state": "error", "msg": str(e)}
            return 0
        self.loaded = True
        self.status = {"state": "ready", "msg": f"{n} transactions chargées"} if n else {"state": "empty", "msg": "Aucune transaction pour l'instant."}
        return n

    def pump_once(self) -> int:
        if not self.loaded:
            return self.load_sync()
        try:
            n = self.market.ingest_many(self.source.poll(self.now_ms()))
        except DataError as e:
            self.status = {"state": "error", "msg": str(e)}
            return 0
        if self.status["state"] in ("error", "empty") and self.market.count:
            self.status = {"state": "ready", "msg": f"{self.market.count} transactions"}
        return n

    def _run(self):
        while not self.stop_ev.is_set():
            try:
                self.pump_once()
            except Exception:                                    # un probleme de donnees ne doit jamais arreter le terminal
                log.exception("lecture de la source")
                self.status = {"state": "error", "msg": "Erreur inattendue dans la lecture des données (voir la fenêtre noire)."}
            self.stop_ev.wait(self.cfg.refresh_seconds)

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name="nq-pump")
        self.thread.start()

    def shutdown(self):
        self.stop_ev.set()

    # ---------- vues ----------
    def events(self) -> list:
        try:
            mt = self.events_path.stat().st_mtime_ns
        except OSError:
            return []
        if self._events[0] != mt:
            self._events = (mt, events.load(self.events_path))
        return self._events[1]

    def state(self) -> dict:
        mk, now = self.market, self.now_ms()
        c = front_contract(now, self.inst.root)
        nxt = front_contract(c.roll_ms + 1, self.inst.root)
        days_to_roll = (c.roll_ms - now) / clock.DAY
        with mk.lock:
            last = mk.last
            out = {"ok": True, "version": VERSION, "status": self.status, "source": self.source.info(), "ticks": mk.count,
                   "deltaReal": mk.cls.real_share if mk.count else None,
                   "last": {"t": last.t, "p": last.p, "q": last.q, "side": last.side} if last else None,
                   "day": mk.day(), "prevDay": mk.prev_day(),
                   "tape": [{"t": t, "p": p, "q": q, "s": s} for t, p, q, s in list(mk.tape)[-25:]][::-1],
                   "bigs": [{"t": t, "p": p, "q": q, "s": s} for t, p, q, s in list(mk.bigs)[-8:]][::-1]}
        out["inst"] = {"root": self.inst.root, "name": self.inst.name, "tick": self.inst.tick, "pointValue": self.inst.point_value,
                       "tickValue": self.inst.tick_value, "bigLot": self.inst.big_lot}
        out["contract"] = {"code": c.code, "label": c.label, "rollInDays": round(days_to_roll, 1), "next": nxt.code,
                           "rollSoon": days_to_roll <= 3}
        out["clock"] = {"now": now, "paris": clock.fmt_hms(now, "paris"), "et": clock.fmt_hms(now, "et"), "tz": self.cfg.display_tz,
                        "phase": clock.phase(now), "marks": [{"label": lab, "t": t, "paris": clock.fmt_hm(t, "paris"), "et": clock.fmt_hm(t, "et"),
                                                              "in": round((t - now) / 60_000)} for lab, t in clock.next_marks(now, 3)]}
        return out

    def bars(self, tf: str = "1m", limit: int = 500, since: int | None = None) -> dict:
        """Barres du graphique + VWAP (seance et Globex) + CVD (seance et Globex) + absorptions + gros ordres. `since` (ms) : seulement la fin."""
        if tf not in TF_MS:
            raise ValueError(f"unité de temps inconnue : {tf} ({', '.join(TF_MS)})")
        limit = max(1, min(3000, int(limit)))
        step = TF_MS[tf]
        mk = self.market
        with mk.lock:
            chart = mk.chart_bars(step, limit + 80)
            if not chart:
                return {"tf": tf, "step": step, "bars": [], "full": True}
            win = chart[-limit:]
            a0 = clock.window(clock.trading_day(win[0].t), "globex")[0]
            base = mk.slice(a0, win[-1].t + step)
            v_rth = vwap.bands(vwap.sample(base, vwap.cumulative(base, vwap.key_rth), win, step))
            v_gx = vwap.bands(vwap.sample(base, vwap.cumulative(base, vwap.key_globex), win, step))
            c_rth = vwap.sample(base, cvd.cumulative(base, vwap.key_rth), win, step)
            c_gx = vwap.sample(base, cvd.cumulative(base, vwap.key_globex), win, step)
            off = len(chart) - len(win)
            marks = [{"t": chart[i].t // 1000, "side": s, "h": chart[i].h, "l": chart[i].l} for i, s in cvd.marks(chart) if i >= off]
            rows = [{"t": b.t // 1000, "o": b.o, "h": b.h, "l": b.l, "c": b.c, "v": b.v, "d": b.bv - b.sv} for b in win]
            t0 = win[0].t
            bigs = [{"t": t // 1000, "p": p, "q": q, "s": s} for t, p, q, s in mk.bigs if t >= t0]
        full = since is None
        if not full:
            k = 0
            while k < len(rows) - 1 and rows[k]["t"] * 1000 < since:        # depuis la barre `since` (la derniere connue du client : elle a pu changer)
                k += 1
            rows = rows[k:]
            sl = slice(k, None)
            v_rth = {key: v[sl] for key, v in v_rth.items()}
            v_gx = {key: v[sl] for key, v in v_gx.items()}
            c_rth, c_gx = c_rth[sl], c_gx[sl]
        rnd = lambda xs: [None if x is None else round(x, 2) for x in xs]
        return {"tf": tf, "step": step, "full": full, "bars": rows, "vwapRth": v_rth, "vwapGx": v_gx, "cvdRth": rnd(c_rth), "cvdGx": rnd(c_gx),
                "absorptions": marks, "bigs": bigs}

    def profile(self, which: str = "rth", row_ticks: int | None = None) -> dict:
        """Profil de volume : `rth` (seance du jour), `gx` (journee Globex), `prev` (seance reguliere de la veille)."""
        mk = self.market
        with mk.lock:
            if mk.last is None:
                return {"which": which, "empty": True}
            day = mk.day()
            label = {"rth": "Séance", "gx": "Globex", "prev": "Veille"}.get(which, "Séance")
            if which == "prev":
                day, kind = mk.prev_day(day), "rth"
            else:
                kind = "gx" if which == "gx" else "rth"
            lad = mk.ladder(day, kind) if day else None
            if which == "rth" and (lad is None or lad.empty()):          # la seance reguliere n'a pas encore commence : on montre la journee Globex, en le disant
                lad, label = mk.ladder(day, "gx"), "Globex (séance pas encore ouverte)"
            st = vp.stats(lad, row_ticks, min_row_ticks=4) if lad is not None and not lad.empty() else None
        if st is None:
            return {"which": which, "day": day, "empty": True}
        st.update({"which": which, "day": day, "empty": False, "tick": self.inst.tick, "price": mk.price, "label": label})
        return st

    def footprint(self, tf: str = "5m", n: int = 2, ratio: float = 3.0, min_vol: float = 5.0) -> dict:
        """Footprint des n dernieres barres : [{t, rows: [[prix, vendeur, acheteur, drapeaux]], poc, delta, stacks}], du haut vers le bas."""
        if tf not in TF_MS:
            raise ValueError(f"unité de temps inconnue : {tf}")
        step, mk = TF_MS[tf], self.market
        n = max(1, min(6, int(n)))
        with mk.lock:
            if mk.last is None:
                return {"tf": tf, "bars": []}
            last_open = mk.last.t - mk.last.t % step
            bars = resample(mk.slice(last_open - (n - 1) * step, last_open + step), step, with_fp=True)[-n:]
            out = []
            for b in bars:
                im = footprint.imbalances(b.fp, ratio, min_vol)
                poc = footprint.poc_of(b.fp)
                buy, sell = set(im["buy"]), set(im["sell"])
                rows = [[self.inst.price(i), r[0], r[1], (1 if i in buy else 0) | (2 if i in sell else 0) | (4 if i == poc else 0)]
                        for i, r in sorted(b.fp.items(), reverse=True)]
                out.append({"t": b.t // 1000, "o": b.o, "h": b.h, "l": b.l, "c": b.c, "v": b.v, "delta": b.bv - b.sv, "rows": rows,
                            "stacks": [{"side": s, "lo": self.inst.price(a), "hi": self.inst.price(z)} for s, a, z in im["stacks"]]})
        return {"tf": tf, "ratio": ratio, "minVol": min_vol, "bars": out}

    def levels(self) -> dict:
        lv = levels.build(self.market, self.cfg.zone_pts)
        lv["near"] = levels.nearest(lv["levels"], lv["price"], 3) if lv["price"] else {"above": [], "below": []}
        return lv

    def account_view(self, pos_text=None) -> dict:
        """Etat du compte pour la journee de trading en cours. `pos_text` : position ouverte saisie (« long,NQ,1,25000.25 ») pour le latent."""
        pos = parse_position(pos_text)
        price = self.market.price
        open_pnl = 0.0
        if pos and price:
            sgn = 1 if pos["side"] == "long" else -1
            open_pnl = (price - pos["entry"]) * sgn * INSTRUMENTS[pos["root"]].point_value * pos["qty"]
        snap = self.account.snapshot(clock.trading_day(self.now_ms()), open_pnl)
        snap["position"] = dict(pos, pnl=round(open_pnl, 2), price=price) if pos else None
        return snap

    def context(self, pos_text=None) -> dict:
        lv = self.levels()
        return context.build(self.market, lv, self.events(), self.account_view(pos_text), self.source.info(), now_ms=self.now_ms())

    def plan(self, side, entry, stop, targets, root=None, risk_usd=None, pos_text=None) -> dict:
        pos = parse_position(pos_text)
        held = {pos["root"]: pos["qty"]} if pos else None
        return risk.plan(side, float(entry), float(stop), [float(x) for x in targets], (root or self.inst.root).upper(), self.account.profile,
                         self.account_view(pos_text), None if risk_usd in (None, "") else float(risk_usd), held)

    def test_file(self, path: str) -> dict:
        ok, msg = selftest_file(path)
        return {"ok": ok, "message": msg}

    def config_view(self) -> dict:
        c = self.cfg
        return {"source": c.source, "instrument": c.instrument, "displayTz": c.display_tz, "zonePts": c.zone_pts, "csvPath": c.csv_path,
                "tfs": list(TF_MS), "version": VERSION}
