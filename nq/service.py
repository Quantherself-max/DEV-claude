"""Service : relie la source de donnees, le marche, le compte et les vues JSON servies au navigateur."""
import copy
from bisect import bisect_left
import logging
import threading
import time
from dataclasses import replace
from pathlib import Path

from data.base import DataError
from data.filefeed import CsvSource, selftest_file
from data.simulated import SimulatedSource
from engine import backtest as bt
from data.options import OptionsFeed, oi_summary, read_oi
from engine import absorption, clock, context, cvd, events, footprint, gex, levels, montecarlo, profiles, risk, signals, vp, vwap
from engine.account import Account
from engine.bars import TF_MS, resample
from engine.instruments import INSTRUMENTS, front_contract
from engine.market import Market

VERSION = "0.7"
log = logging.getLogger("nq")
SIM_BASE = {"NQ": 25_000.0, "MNQ": 25_000.0, "ES": 6_700.0, "MES": 6_700.0}


def make_source(cfg):
    inst = INSTRUMENTS[cfg.instrument]
    if cfg.source == "tradovate":
        from data.tradovate import TradovateSource
        return TradovateSource(cfg.tv_user, cfg.tv_password, cfg.tv_cid, cfg.tv_secret, cfg.tv_app_id, "1.0",
                               cfg.tv_env, inst.root, debug=cfg.tv_debug)
    if cfg.source == "csv":
        # journees de trading -> jours calendaires du fichier (week-ends compris), avec une marge
        return CsvSource(cfg.csv_path, cfg.csv_tz, cfg.csv_columns or None, cfg.csv_buy_codes, cfg.csv_sell_codes,
                         max_days=cfg.history_days * 7 / 5 + 2)
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
    if side not in ("long", "short") or root not in INSTRUMENTS or not 0 < qty <= 10_000 or not 0 < entry < 1_000_000:
        return None
    return {"side": side, "root": root, "qty": qty, "entry": entry}


class Service:
    def __init__(self, cfg, source=None, account: Account | None = None, env_path: Path | None = None):
        self.cfg = cfg
        inst = INSTRUMENTS[cfg.instrument]
        if cfg.big_lot:
            inst = replace(inst, big_lot=cfg.big_lot)
        self.inst = inst
        self.market = Market(inst, keep_days=cfg.history_days + 1)
        self.source = source or make_source(cfg)
        self.account = account or Account(Path(cfg.data_dir) / "compte.json", now_ms=self.now_ms)
        self.events_path = Path(cfg.data_dir) / "events.json"
        self._bt_lock = threading.Lock()
        self._bt_cache = None                                # (clé, Tape) du dernier backtest
        self.composer = profiles.Composer()                  # profils composites semaine / mois (journées passées gardées)
        self._abs_known = {}                                 # absorptions déjà évaluées, par barre close (une barre close ne change plus)
        self._lv_cache = (0.0, None)                         # niveaux (recalculés au plus toutes les 3 s pour classer les absorptions)
        self._oi = (None, None)                              # (date de modification du fichier, résumé de l'intérêt ouvert)
        gex_ok = cfg.gex != "OFF" and inst.root in ("NQ", "MNQ")          # options NDX / QQQ : seulement pour le Nasdaq
        self.options = OptionsFeed(cfg.gex, Path(cfg.data_dir), cfg.gex_file, cfg.gex_refresh_min) if gex_ok else None
        self.gex_state = {"state": "off" if self.options is None else "waiting", "res": None, "asof": None, "src": None,
                          "msg": "" if gex_ok or cfg.gex == "OFF" else "GEX : options du Nasdaq, seulement pour NQ / MNQ."}
        self._gex_lock = threading.Lock()
        self._gex_force = threading.Event()
        self._swap = threading.Lock()                        # changement de source pendant que le fil de lecture tourne
        from config import ROOT
        self.env_path = Path(env_path) if env_path else ROOT / ".env"
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
            self.market = Market(self.inst, keep_days=self.cfg.history_days + 1)                      # lecture interrompue a mi-chemin : on repart d'un marche vide (sinon la reprise doublerait les volumes deja lus)
            self.status = {"state": "error", "msg": str(e)}
            return 0
        self.loaded = True
        self.status = {"state": "ready", "msg": f"{n} transactions chargées"} if n else {"state": "empty", "msg": "Aucune transaction pour l'instant."}
        return n

    def pump_once(self) -> int:
        with self._swap:
            return self._pump()

    def _pump(self) -> int:
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
        if self.options is not None:
            threading.Thread(target=self._gex_loop, daemon=True, name="nq-gex").start()

    # ---------- GEX (options, téléchargement en arrière-plan) ----------
    def gex_refresh(self, force: bool = False) -> dict:
        """Lit la chaîne d'options (fichier, téléchargement ou copie locale) et calcule le GEX. Appelé par le fil GEX ou à la demande."""
        if self.options is None:
            return self.gex_state
        js, src = self.options.load(force=force)
        if js is None:
            with self._gex_lock:
                self.gex_state = dict(self.gex_state, state="error" if self.gex_state.get("res") is None else self.gex_state["state"],
                                      msg=self.options.error or "Pas encore de données d'options.")
            return self.gex_state
        now = self.now_ms()
        try:
            chain = gex.chain_from_json(js, now)
            res = gex.compute(chain)
        except (ValueError, KeyError, TypeError, ZeroDivisionError) as e:
            with self._gex_lock:                                 # on garde le dernier bon calcul s'il existe
                self.gex_state = dict(self.gex_state, state="ready" if self.gex_state.get("res") else "error",
                                      msg=f"Données d'options inattendues : {e}")
            return self.gex_state
        # prix du NQ qui correspond au prix du sous-jacent des données : cotations différées de 15 min -> NQ d'il y a 15 min pour un
        # téléchargement ; pour un fichier / une copie, NQ à l'heure écrite dans les données si on l'a, sinon le dernier prix
        ref_t = now - 15 * 60_000 if src and src.startswith("CBOE") else chain["asof"]
        with self.market.lock:
            bars = self.market.slice(ref_t - 3 * 60_000, ref_t + 60_000) if ref_t else []
            ref = bars[-1].c if bars else self.market.price
        with self._gex_lock:
            self.gex_state = {"state": "ready", "msg": self.options.error or "", "res": res, "asof": ref_t, "src": src, "ref": ref,
                              "underlying": chain["underlying"] or self.cfg.gex}
        return self.gex_state

    def _gex_loop(self):
        try:
            self.gex_refresh()
        except Exception:
            log.exception("GEX")
        while not self.stop_ev.is_set():
            forced = self._gex_force.wait(30)
            self._gex_force.clear()
            try:
                if forced or self.options.due():
                    self.gex_refresh(force=forced)
            except Exception:
                log.exception("GEX")

    def gex_view(self) -> dict:
        """Niveaux GEX ramenés au prix du NQ (rapport NQ / sous-jacent à l'heure des données d'options)."""
        with self._gex_lock:
            st = dict(self.gex_state)
        out = {"state": st["state"], "msg": st.get("msg", ""), "underlying": st.get("underlying") or self.cfg.gex, "src": st.get("src")}
        res = st.get("res")
        if not res:
            return out
        ref = st.get("ref") or self.market.price
        if not ref or not res["spot"]:
            return dict(out, state="error", msg="Pas de prix NQ pour convertir les niveaux d'options.")
        ratio = ref / res["spot"]
        conv = gex.to_nq(res, ratio)
        out.update({"asof": st["asof"], "spot": res["spot"], "ratio": round(ratio, 6), "total": res["total"], "regime": res["regime"],
                    "dte0Share": round(res["dte0Share"], 3), "nOptions": res["nOptions"], "levels": conv["levels"], "strikes": conv["strikes"],
                    "zeroGammaSrc": res["zeroGamma"], "callWallSrc": res["callWall"], "putWallSrc": res["putWall"]})
        return out

    def oi(self):
        """Intérêt ouvert du NQ (fichier de NQTickLogger), relu seulement quand le fichier change."""
        p = Path(self.cfg.oi_path) if self.cfg.oi_path else None
        try:
            mt = p.stat().st_mtime_ns if p and p.exists() else None
        except OSError:
            mt = None
        if mt is None:
            return None
        if self._oi[0] != mt:
            self._oi = (mt, oi_summary(read_oi(p)))
        return self._oi[1]

    def shutdown(self):
        self.stop_ev.set()
        if hasattr(self.source, "shutdown"):
            try:
                self.source.shutdown()
            except Exception:
                pass

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
            out = {"ok": True, "version": VERSION, "status": self.status, "source": dict(self.source.info(), auto=self.cfg.auto_source),
                   "ticks": mk.count,
                   "deltaReal": mk.cls.real_share if mk.count else None,
                   "last": {"t": last.t, "p": last.p, "q": last.q, "side": last.side} if last else None,
                   "day": mk.day(), "prevDay": mk.prev_day(),
                   "tape": [{"t": t, "p": p, "q": q, "s": s} for t, p, q, s in list(mk.tape)[-25:]][::-1],
                   "bigs": [{"t": t, "p": p, "q": q, "s": s} for t, p, q, s in list(mk.bigs)[-8:]][::-1]}
        out["oi"] = self.oi()
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
            d0 = clock.trading_day(win[0].t)
            a0 = clock.window(d0, "globex")[0]
            base = mk.slice(a0, win[-1].t + step)
            v_rth = vwap.bands(vwap.sample(base, vwap.cumulative(base, vwap.key_rth), win, step))
            v_gx = vwap.bands(vwap.sample(base, vwap.cumulative(base, vwap.key_globex), win, step))
            # VWAP de la semaine et du mois : les journées d'avant la fenêtre lue viennent de leurs profils (sommes), sans relire leurs barres
            tick = self.inst.tick
            wk, mo = profiles.week_key(d0), d0[:7]
            off_w = {wk: vwap.ladder_sums([mk.gx[d] for d in mk.gx if d < d0 and profiles.week_key(d) == wk], tick)}
            off_m = {mo: vwap.ladder_sums([mk.gx[d] for d in mk.gx if d < d0 and d[:7] == mo], tick)}
            month_ok = profiles.covers(mk, profiles.period_start(mk.day(), "month"))        # mois tronqué par l'historique : pas de VWAP faux
            v_wk = vwap.bands(vwap.sample(base, vwap.cumulative(base, vwap.key_week, offsets=off_w), win, step), ks=(1.0,))
            v_mo = vwap.bands(vwap.sample(base, vwap.cumulative(base, vwap.key_month, offsets=off_m), win, step) if month_ok
                              else [None] * len(win), ks=(1.0,))
            cum_rth, cum_gx = cvd.cumulative(base, vwap.key_rth), cvd.cumulative(base, vwap.key_globex)
            c_rth = vwap.sample(base, cum_rth, win, step)
            c_gx = vwap.sample(base, cum_gx, win, step)
            o_rth = cvd.ohlc_sample(base, cum_rth, win, step)                # bougies de CVD (ouverture, plus haut, plus bas, clôture)
            o_gx = cvd.ohlc_sample(base, cum_gx, win, step)
            # absorptions au prix (barres de 1 min, footprint), suivies jusqu'à maintenant ; 70 barres d'avance pour les échelles habituelles
            j0 = bisect_left(mk.series._ts, a0)                          # les 65 barres d'avant, quelle que soit la pause de 17 h ou le week-end
            warm = mk.series.bars[max(0, j0 - absorption.PARAMS.base - 5):j0]
            ab_bars = warm + base
            if len(self._abs_known) > 60_000:
                self._abs_known.clear()
            zs = absorption.track(absorption.scan(ab_bars, tick, known=self._abs_known), ab_bars, tick)
            t_first = win[0].t
            marks = [{"t": z["t"] // 1000, "side": z["side"], "price": z["price"], "lo": z["lo"], "hi": z["hi"], "qty": z["qty"],
                      "strength": z["strength"], "kind": z["kind"], "status": z["status"], "tests": z["tests"], "count": z["count"],
                      "end": z["end"] // 1000 if z["end"] else None} for z in zs if z["t"] >= t_first or z["status"] == "active"]
            absorption.rank(marks, self._key_levels(), tick)        # note d'intérêt : force, répétition, tests, niveau clé
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
            v_wk = {key: v[sl] for key, v in v_wk.items()}
            v_mo = {key: v[sl] for key, v in v_mo.items()}
            c_rth, c_gx = c_rth[sl], c_gx[sl]
            o_rth, o_gx = o_rth[sl], o_gx[sl]
        rnd = lambda xs: [None if x is None else round(x, 2) for x in xs]
        return {"tf": tf, "step": step, "full": full, "bars": rows, "vwapRth": v_rth, "vwapGx": v_gx, "vwapWeek": v_wk, "vwapMonth": v_mo,
                "cvdRth": rnd(c_rth), "cvdGx": rnd(c_gx), "cvdOhlcRth": o_rth, "cvdOhlcGx": o_gx,
                "absorptions": marks, "bigs": bigs}

    def profile(self, which: str = "rth", row_ticks: int | None = None) -> dict:
        """Profil de volume : `rth` (seance du jour), `gx` (journee Globex), `prev` (seance reguliere de la veille), `week` / `pweek`
        (semaine en cours / precedente, composite Globex), `month` / `pmonth` (mois en cours / precedent)."""
        mk = self.market
        if which in ("week", "pweek", "month", "pmonth"):
            with mk.lock:
                if mk.last is None:
                    return {"which": which, "empty": True}
                lad, label, days = self.composer.composite(mk, which)
                st = vp.stats(lad, row_ticks, min_row_ticks=4) if lad is not None else None
                price = mk.price
            if st is None:
                return {"which": which, "empty": True, "label": label}
            st.update({"which": which, "day": days[-1] if days else None, "days": days, "empty": False, "tick": self.inst.tick,
                       "price": price, "label": label})
            return st
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
        extra, singles = self._structure()
        g = self.gex_view()
        for x in g.get("levels") or []:                      # niveaux GEX (options) : groupe à part, poids fort pour les murs et le zéro gamma
            w = {"gcall": 3.0, "gput": 3.0, "gzero": 3.0}.get(x["kind"], 2.0)
            extra.append({"name": x["name"], "price": x["price"], "kind": x["kind"], "group": "gex", "w": w})
        lv = levels.build(self.market, self.cfg.zone_pts, extra=extra)
        lv["near"] = levels.nearest(lv["levels"], lv["price"], 3) if lv["price"] else {"above": [], "below": []}
        lv["singles"] = singles
        return lv

    def _key_levels(self) -> list:
        """Niveaux (hors nombres ronds), recalculés au plus toutes les 3 s : servent à repérer les absorptions qui se font SUR un niveau."""
        t, lv = self._lv_cache
        if lv is None or time.time() - t > 3.0:
            try:
                lv = [x for x in self.levels()["levels"] if x["group"] != "rond"]
            except Exception:                                   # jamais bloquant pour le graphique
                log.exception("niveaux")
                lv = lv or []
            self._lv_cache = (time.time(), lv)
        return lv

    def _structure(self):
        """Niveaux de structure au-delà de la journée : profils semaine / mois, semaine précédente, VWAP semaine / mois, POC vierges, et les
        single prints (séance du jour + 3 séances passées non comblées). Renvoie (niveaux en plus, single prints)."""
        mk = self.market
        out, singles = [], []

        def add(name, p, kind, w):
            if p is not None:
                out.append({"name": name, "price": round(float(p), 4), "kind": kind, "group": "profil", "w": w})

        with mk.lock:
            if mk.last is None:
                return out, singles
            day, price = mk.day(), mk.price
            after = profiles._After(mk.series.bars)
            for which, pre, w in (("week", "sem.", 2.5), ("pweek", "sem. préc.", 2.0), ("month", "mois", 2.5)):
                lad, _, days = self.composer.composite(mk, which)
                st = vp.stats(lad, min_row_ticks=4) if lad is not None else None
                if not st or not days or not profiles.covers(mk, profiles.period_start(days[0], "week" if which != "month" else "month")):
                    continue                                              # période tronquée par l'historique gardé : niveaux faux, on s'abstient
                if which == "week" and days == [day]:
                    continue                                              # lundi : la semaine EST la journée (doublon des niveaux du jour)
                if which == "month" and len(days) < 6:                    # un « mois » de quelques jours n'apporte rien de plus que la semaine
                    continue
                k = {"week": "w", "pweek": "pw", "month": "m"}[which]
                add(f"POC {pre}", st["poc"], k + "poc", w + 0.5)
                add(f"VAH {pre}", st["vah"], k + "vah", w - 0.5)
                add(f"VAL {pre}", st["val"], k + "val", w - 0.5)
                if which == "pweek":
                    add("High sem. préc.", st["hi"], "pwh", 2.5)
                    add("Low sem. préc.", st["lo"], "pwl", 2.5)
                if which in ("week", "month"):
                    add("VWAP " + pre, lad.vwap, "vwapw" if which == "week" else "vwapm", 2.5 if which == "week" else 2.0)
            for n in profiles.naked_pocs(mk, max_days=self.cfg.history_days, after=after):
                add(n["label"], n["price"], "npoc" if n["kind"] == "jour" else "nwpoc", 3.0 if n["kind"] == "jour" else 3.5)
            past = [d for d in sorted(mk.rth) if d < day][-3:]
            for d in past + [day]:
                for sp_ in profiles.single_prints(mk, d, after=after):
                    if sp_["filled"] < 1.0 and abs((sp_["lo"] + sp_["hi"]) / 2 - price) <= 250:
                        singles.append(sp_)
        for z in singles:
            if z["current"] or z["kind"] != "single":
                continue
            lab = f"SP {z['day'][8:10]}/{z['day'][5:7]}"
            if z["hi"] - z["lo"] > self.cfg.zone_pts:                     # assez large : ses deux bords sont deux niveaux
                add(lab + " haut", z["hi"], "sph", 2.0)
                add(lab + " bas", z["lo"], "spl", 2.0)
            else:                                                         # étroit : un seul niveau (sinon il ferait une « zone » à lui seul)
                add(lab, (z["lo"] + z["hi"]) / 2, "sph", 2.0)
        return out, singles

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

    def signals(self, tf: str = "1m", pos_text=None) -> dict:
        """Setups de scalping sur la dernière barre : mêmes ingrédients que le backtest, avec les règles Lucid attachées (compte courant)."""
        if tf not in TF_MS:
            raise ValueError(f"unité de temps inconnue : {tf}")
        step, mk = TF_MS[tf], self.market
        sp = signals.PARAMS
        win = max(sp.look + 20, 140)
        with mk.lock:
            if mk.last is None:
                return {"ready": False, "setups": [], "blocked": ["en attente des premières transactions"], "ruleNotes": [], "tf": tf}
            now = mk.last.t
            base = mk.slice(mk.last.t - (win + 6) * step, mk.last.t + step)
            sig = base if (tf == "1m") else resample(base, step, with_fp=True)
            if len(sig) < 5:
                return {"ready": False, "setups": [], "blocked": ["pas assez de barres"], "ruleNotes": [], "tf": tf}
            cvd_vals, acc, key = [], 0.0, None
            for b in sig:
                k = clock.trading_day(b.t)
                if k != key:
                    key, acc = k, 0.0
                acc += b.bv - b.sv
                cvd_vals.append(acc)
            day = clock.trading_day(now)
            rth_started = now >= clock.window(day, "rth")[0]
            lad = mk.ladder(day, "rth") if rth_started else mk.ladder(day, "gx")
            prof = vp.stats(lad, min_row_ticks=4) if lad is not None and not lad.empty() else None
            ph = clock.phase(now)
            ff = clock.forced_flat(day)
        lv = self.levels()
        near = lv.get("near") or {"above": [], "below": []}
        acct = self.account_view(pos_text)
        res = signals.evaluate(sig, cvd_vals, prof, near, lv.get("zones", []), self.inst, now, ff, ph, rth_started, acct=acct)
        res["tf"] = tf
        return res

    def _tape(self, tf: str, days: int | None):
        """`Tape` de backtest de l'historique chargé, mise en cache tant que l'historique (dernière barre) et les réglages ne changent pas."""
        mk = self.market
        with mk.lock:
            bars = list(mk.series.bars)
            if bars:                                         # la dernière barre se forme encore : on en fige une copie (lue hors du verrou)
                last = copy.copy(bars[-1])
                last.fp = {k: list(v) if isinstance(v, list) else v for k, v in bars[-1].fp.items()}
                bars[-1] = last
        if days and days > 0:                                # limite éventuelle au N dernières journées de trading
            keep = set(sorted({clock.trading_day(b.t) for b in bars})[-int(days):])
            bars = [b for b in bars if clock.trading_day(b.t) in keep]
        tf = tf if tf in TF_MS else "1m"
        # clé : barres CLOSES seulement. La barre en cours change à chaque transaction ; tant qu'aucune nouvelle barre ne s'ouvre, on réutilise
        # le calcul (Backtest puis Robustesse instantanés), au prix d'une dernière minute un peu en retard.
        key = (tf, int(days or 0) if days and days > 0 else 0, len(bars), bars[-1].t if bars else None)
        with self._bt_lock:
            if self._bt_cache and self._bt_cache[0] == key:
                return self._bt_cache[1], tf
        tape = bt.prepare(bars, self.inst, tf)
        with self._bt_lock:
            self._bt_cache = (key, tape)
        return tape, tf

    def backtest(self, tf: str = "1m", min_score: float = 40.0, slippage_ticks: float = 1.0, max_hold_min: int = 20,
                 risk_usd: float = 100.0, one_per_session: bool = False, days: int | None = None, eval_fee: float | None = None,
                 horizon: int = 60) -> dict:
        """Rejoue les setups sur l'historique chargé (barres de base) et confronte le résultat aux règles Lucid du profil courant, puis estime
        par Monte Carlo la probabilité de valider l'évaluation."""
        tape, tf = self._tape(tf, days)
        if tape is None:
            return {"ok": False, "msg": "pas assez de barres pour un backtest", "trades": [], "days": []}
        params = bt.BtParams(tf=tf, min_score=float(min_score), slippage_ticks=max(0.0, float(slippage_ticks)),
                             max_hold_min=max(1, int(max_hold_min)), risk_usd=max(1.0, float(risk_usd)), one_per_session=bool(one_per_session))
        prof = self.account.profile
        res = bt.simulate(tape, self.inst, prof, params)
        res["params"] = {"tf": params.tf, "minScore": params.min_score, "slippageTicks": params.slippage_ticks,
                         "maxHoldMin": params.max_hold_min, "riskUsd": params.risk_usd, "onePerSession": params.one_per_session,
                         "limitThroughTicks": params.limit_through_ticks}
        res["profile"] = {"name": prof.name, "start": prof.start_balance, "target": prof.profit_target, "maxDd": prof.max_drawdown}
        samples = [(d["pnl"], d["low"]) for d in res["days"]] + [(0.0, 0.0)] * max(0, res["nDays"] - len(res["days"]))
        fee = float(eval_fee) if eval_fee and eval_fee > 0 else None
        res["monteCarlo"] = montecarlo.simulate_eval(samples, prof, horizon=max(5, min(250, int(horizon))), eval_fee=fee) if res["trades"] else None
        return res

    def backtest_sweep(self, tf: str = "1m", max_hold_min: int = 20, risk_usd: float = 100.0, one_per_session: bool = False,
                       days: int | None = None) -> dict:
        """Test de robustesse : grille score minimal × glissement, avec séparation début / fin d'historique (voir engine/backtest.sweep)."""
        tape, tf = self._tape(tf, days)
        if tape is None:
            return {"ok": False, "msg": "pas assez de barres pour un backtest"}
        base = bt.BtParams(tf=tf, max_hold_min=max(1, int(max_hold_min)), risk_usd=max(1.0, float(risk_usd)), one_per_session=bool(one_per_session))
        return bt.sweep(tape, self.inst, self.account.profile, base)

    def test_file(self, path: str) -> dict:
        ok, msg = selftest_file(path)
        return {"ok": ok, "message": msg}

    def config_view(self) -> dict:
        c = self.cfg
        return {"source": c.source, "instrument": c.instrument, "displayTz": c.display_tz, "zonePts": c.zone_pts, "csvPath": c.csv_path,
                "tfs": list(TF_MS), "version": VERSION, "days": self.market_days(), "gex": c.gex, "historyDays": c.history_days}

    def source_view(self) -> dict:
        """Où le terminal prend ses données, et où il cherche le fichier de l'enregistreur NinjaTrader."""
        from config import logger_candidates
        c = self.cfg
        out = {"source": c.source, "auto": c.auto_source, "explicit": c.source_explicit, "csvPath": c.csv_path, "oiPath": c.oi_path,
               "status": self.status, "candidates": []}
        for p in logger_candidates():
            try:
                st = p.stat() if p.is_file() else None
            except OSError:
                st = None
            out["candidates"].append({"path": str(p), "exists": st is not None, "size": st.st_size if st else 0,
                                      "mtime": int(st.st_mtime * 1000) if st else None})
        if c.csv_path:
            try:
                st = Path(c.csv_path).stat()
                out["file"] = {"size": st.st_size, "mtime": int(st.st_mtime * 1000), "ageS": round(time.time() - st.st_mtime, 1)}
            except OSError:
                out["file"] = None
        with self.market.lock:
            last = self.market.last
            out["lastTick"] = last.t if last else None
        if c.source == "tradovate":
            info = self.source.info()
            out["tvUser"] = c.tv_user                        # l'identifiant seulement, jamais le mot de passe
            out["tradovate"] = {"status": info.get("status"), "error": info.get("error"), "env": info.get("env"),
                                "symbol": info.get("symbol"), "mode": info.get("mode"), "label": info.get("label")}
        return out

    def use_source(self, path: str | None) -> dict:
        """Passe sur le fichier de transactions `path` (vérifié d'abord), ou sur les données simulées si `path` est vide, sans redémarrer.
        Le choix est écrit dans .env (NQ_SOURCE, NQ_CSV_PATH) pour les prochains démarrages."""
        c0 = self.cfg
        if path:
            ok, msg = selftest_file(path, c0.csv_tz, c0.csv_columns or None, c0.csv_buy_codes, c0.csv_sell_codes,
                                    max_days=c0.history_days * 7 / 5 + 2)
            if not ok:
                raise ValueError(msg)
        self._write_env({"NQ_SOURCE": "csv" if path else "simulated", "NQ_CSV_PATH": str(path) if path else ""})   # avant de changer : une erreur ne laisse rien à moitié
        c = self.cfg
        with self._swap:
            c.source, c.csv_path, c.auto_source, c.source_explicit = ("csv", str(path), False, True) if path else ("simulated", "", False, True)
            c.oi_path = str(Path(path).with_name("nq-oi.csv")) if path else ""          # pas d'OI réel sur des prix simulés
            self._install(make_source(c))
        return {"ok": True, "message": msg if path else "Données simulées.", "source": c.source}

    def _install(self, source):
        """Remplace la source et repart d'un marché vide. À appeler en tenant `self._swap`."""
        old = self.source
        if hasattr(old, "shutdown"):                         # arrête le fil de fond de l'ancienne source (Tradovate)
            try:
                old.shutdown()
            except Exception:
                pass
        self.source = source
        self.market = Market(self.inst, keep_days=self.cfg.history_days + 1)
        self.composer = profiles.Composer()
        self._abs_known, self._lv_cache, self._oi, self._bt_cache = {}, (0.0, None), (None, None), None
        self.loaded = False
        self.status = {"state": "loading", "msg": "Chargement de la nouvelle source…"}

    def tradovate_login(self, username, password, cid="", sec="", env="live", remember=False) -> dict:
        """Formulaire de connexion : se connecte à l'API officielle de Tradovate avec les identifiants saisis (ceux du compte de l'utilisateur),
        vérifie tout de suite qu'ils sont acceptés, puis passe le terminal sur ce flux, sans redémarrer. Le mot de passe n'est jamais renvoyé
        ni journalisé ; il n'est écrit dans .env que si `remember` est coché (en clair, sur ce PC)."""
        from data.tradovate import TradovateSource, _AuthDenied
        username, cid, sec = str(username or "").strip(), str(cid or "").strip(), str(sec or "").strip()
        password = str(password or "")
        env = "demo" if str(env).lower() == "demo" else "live"
        if not username or not password:
            raise ValueError("Identifiant et mot de passe requis.")
        c = self.cfg
        src = TradovateSource(username, password, cid, sec, c.tv_app_id, "1.0", env, self.inst.root, debug=c.tv_debug)
        try:
            label = src.preauth()
        except _AuthDenied as e:
            raise ValueError(f"Connexion refusée par Tradovate : {e}") from None
        except DataError as e:
            raise ValueError(str(e)) from None
        remembered = False
        note = ""
        if remember:
            if password != password.strip().strip('"').strip("'") or "\n" in password or "\r" in password:
                note = " Mot de passe non mémorisé (il commence ou finit par un espace ou un guillemet : .env ne peut pas le garder tel quel)."
            else:
                self._write_env({"NQ_SOURCE": "tradovate", "NQ_CSV_PATH": "", "TRADOVATE_USERNAME": username, "TRADOVATE_PASSWORD": password,
                                 "TRADOVATE_CID": cid, "TRADOVATE_SECRET": sec, "TRADOVATE_ENV": env})
                remembered = True
        with self._swap:
            c.source, c.csv_path, c.auto_source, c.source_explicit, c.oi_path = "tradovate", "", False, True, ""
            c.tv_user, c.tv_password, c.tv_cid, c.tv_secret, c.tv_env = username, password, cid, sec, env
            self._install(src)
        return {"ok": True, "remembered": remembered, "message": f"Connecté : {label}." + (" Identifiants mémorisés dans .env." if remembered else
                " Identifiants gardés en mémoire seulement (à ressaisir au prochain démarrage).") + note}

    def tradovate_logout(self) -> dict:
        """Se déconnecte de Tradovate : efface les identifiants de la mémoire et de .env, puis revient au fichier NinjaTrader s'il existe,
        sinon aux données simulées."""
        from config import find_logger_file
        self._write_env({"NQ_SOURCE": "", "TRADOVATE_USERNAME": "", "TRADOVATE_PASSWORD": "", "TRADOVATE_CID": "", "TRADOVATE_SECRET": "",
                         "TRADOVATE_ENV": ""})
        c = self.cfg
        found = find_logger_file()
        with self._swap:
            c.tv_user = c.tv_password = c.tv_cid = c.tv_secret = ""
            c.source, c.csv_path, c.auto_source, c.source_explicit = ("csv", found, True, False) if found else ("simulated", "", False, False)
            c.oi_path = str(Path(found).with_name("nq-oi.csv")) if found else ""
            self._install(make_source(c))
        return {"ok": True, "source": c.source, "message": "Déconnecté de Tradovate. Identifiants effacés."}

    def _write_env(self, values: dict):
        """Remplace (ou ajoute) ces réglages dans .env, en gardant le reste du fichier tel quel."""
        from config import _read_text
        p = self.env_path
        try:
            lines = _read_text(p).splitlines() if p.exists() else []          # .env écrit au Bloc-notes : UTF-8 ou Windows-1252
        except OSError as e:
            raise ValueError(f"impossible de lire {p} : {e}") from None
        keep = [ln for ln in lines if ln.split("=", 1)[0].strip() not in values]
        keep += [f"{k}={v}" for k, v in values.items() if v != ""]
        try:
            tmp = p.with_suffix(".tmp")
            tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
            tmp.replace(p)
        except OSError as e:
            raise ValueError(f"impossible d'écrire {p} : {e}") from None

    def market_days(self) -> int:
        with self.market.lock:
            return len({clock.trading_day(b.t) for b in self.market.series.bars}) if self.market.series.bars else 0
