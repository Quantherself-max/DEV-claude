"""Assemblage des sources réelles et du moteur exact (V45) : c'est ce module qui répond à /api/quant.

Entrées en direct (aucune connexion en double : le hub se branche sur les flux que le terminal lit déjà) :
  on_binance_agg(x, marché)        chaque transaction agrégée Binance (perpétuels et comptant) de chaque paire suivie ;
  on_venue_trade(bourse, ...)      chaque transaction BTC de Bybit, OKX, Coinbase et Bitstamp (textes exacts) ;
  books(paire)                     le carnet Binance synchronisé du terminal (1 000 niveaux + mises à jour à 100 ms), lu toutes les
                                   2 secondes : plus profond que le flux partiel « depth20 » (20 niveaux, soit environ 2 $ sur le BTC).
Entrées périodiques (ingest.binance / venues / onchain) : bougies d'une minute (48 heures au démarrage, puis contrôle toutes les
5 minutes), intérêt ouvert, financement, ratio long / short, Bybit et OKX, chaîne d'options Deribit, réseau Bitcoin.

Contrôle d'intégrité : toutes les 5 minutes, chaque minute fermée comptée transaction par transaction est comparée à la bougie
officielle de Binance (volume et volume acheteur, à l'unité près), puis remplacée par elle. Voir `reconcile` : le compteur donne les
minutes identiques, les minutes décalées au passage de la minute, les minutes complétées après une coupure, et le résidu cumulé.

Rien n'est fabriqué : une source en panne donne `error` dans sa partie, les autres continuent."""
from __future__ import annotations
import threading
import time
from collections import deque
from decimal import Decimal
from fractions import Fraction

from quant import book as qbook
from quant import flow as qflow
from quant import options as qopt
from quant import profile as qprofile
from quant import regime as qregime
from quant.num import CTX, UNIT, D, from_float, from_units, units
from .binance import Binance
from .core import IngestError
from .onchain import OnChain
from .venues import Bybit, Deribit, Okx, okx_inst

MIN, HOUR, DAY = 60_000, 3_600_000, 86_400_000
WINDOWS = (("5m", 5 * MIN), ("15m", 15 * MIN), ("1h", HOUR), ("4h", 4 * HOUR), ("24h", DAY))
REGIME_WINDOWS = (("15m", 15 * MIN), ("1h", HOUR), ("4h", 4 * HOUR))
BANDS = ("0.001", "0.005", "0.01")
BOOK_BAND = 0.01
VENUE_NAMES = {"binance_perp": "Binance perpétuel", "binance_spot": "Binance comptant", "bybit_perp": "Bybit perpétuel", "bybit_spot": "Bybit comptant",
               "okx_perp": "OKX perpétuel", "okx_spot": "OKX comptant", "coinbase": "Coinbase", "bitstamp": "Bitstamp"}
ERRS = (IngestError, KeyError, IndexError, TypeError, ValueError, ArithmeticError, AttributeError)


def js(x):
    """Valeur lisible par la page : Decimal et Fraction deviennent des flottants (affichage seulement), le reste est gardé."""
    if isinstance(x, Decimal):
        return float(x)
    if isinstance(x, Fraction):
        return float(x)
    if isinstance(x, dict):
        return {k: js(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [js(v) for v in x]
    return x


class QuantHub:
    def __init__(self, symbols, binance: Binance | None = None, bybit: Bybit | None = None, okx: Okx | None = None,
                 deribit: Deribit | None = None, onchain: OnChain | None = None, books=None, footprint=None, liqs=None,
                 ws_clients=None, now=time.time, seed_hours: int = 48):
        self.symbols = [s.upper() for s in symbols]
        self.binance, self.bybit, self.okx = binance or Binance(), bybit or Bybit(), okx or Okx()
        self.deribit, self.onchain = deribit or Deribit(), onchain or OnChain()
        self.books, self.footprint, self.liqs, self.ws_clients = books, footprint, liqs, ws_clients
        self.now = now
        self.seed_hours = seed_hours
        self.lock = threading.RLock()
        self.cvd = {(s, m): qflow.TickCvd(MIN, keep=seed_hours * 60 + 120) for s in self.symbols for m in ("perp", "spot")}
        self.venues = qflow.VenueFlow(MIN, keep=24 * 60)
        self.walls = {s: qbook.WallTracker(band=str(BOOK_BAND), k="8", near="0.0015") for s in self.symbols}
        self.book_last: dict = {}
        self.oi = {s: deque(maxlen=4000) for s in self.symbols}
        self.premium: dict = {}
        self.ls: dict = {}
        self.others: dict = {}
        self.opt = None
        self.chain = None
        self.oc = None
        self.integrity = {k: {"seeded": 0, "verified": 0, "shifted": 0, "repaired": 0, "mismatch": 0, "residual": 0, "residualBuy": 0,
                              "maxResidual": 0, "volume": 0, "last": None, "lastT": None, "live": 0} for k in self.cvd}
        self.errors: dict = {}
        self.fetched: dict = {}
        self._gaps_seen: dict = {}
        self._due: dict = {}
        self.stop_ev = threading.Event()
        self.thread = None
        self._snap: dict = {}

    def now_ms(self) -> int:
        return int(self.now() * 1000)

    # =================================================================================================
    #  flux en direct
    # =================================================================================================
    def on_binance_agg(self, x: dict, market: str) -> None:
        """Transaction agrégée Binance ; `m` vrai = acheteur passif = vente agressive. Textes lus en entiers exacts."""
        c = self.cvd.get((x["s"].upper(), market))
        if c is None:
            return
        t, px, q, side = int(x["T"]), units(x["p"]), units(x["q"]), (-1 if x["m"] else 1)
        with self.lock:
            c.add(t, px, q, side)
            self.integrity[(x["s"].upper(), market)]["live"] += 1
            if market == "perp":
                w = self.walls.get(x["s"].upper())
                if w is not None and w.live:
                    w.on_trade(from_units(px), from_units(px * q, 16), side)
            if x["s"].upper() == "BTCUSDT":
                self.venues.add("binance_" + market, t, px, q, side)

    def on_venue_trade(self, venue: str, t_ms: int, px_text, qty_text, side: int, quote_text=None) -> None:
        """Transaction BTC d'une autre bourse. Contrat coté en dollars : `quote_text` (notionnel exact), sans quantité."""
        try:
            px = units(px_text)
            if quote_text is not None:
                qu = units(quote_text)
                q = qu * UNIT // px if px > 0 else 0                     # pièces indicatives (le total se fait en dollars)
            else:
                q, qu = units(qty_text), None
        except (ValueError, TypeError) as e:
            self.errors[venue] = f"transaction illisible : {e}"
            return
        with self.lock:
            self.venues.add(venue, int(t_ms), px, q, side, qu)

    def _mark_gaps(self) -> None:
        """Coupures des flux de transactions Binance (datées par le client WebSocket) : les minutes touchées ne sont plus complètes."""
        cl = self.ws_clients() if self.ws_clients else {}
        for market, key in (("perp", "trades"), ("spot", "spot")):
            c = cl.get(key)
            if c is None:
                continue
            last = self._gaps_seen.get(key, 0)
            new = [g for g in list(getattr(c, "gaps", ())) if g[1] > last]
            if new:
                self._gaps_seen[key] = max(g[1] for g in new)
            with self.lock:
                for t0, t1 in new:
                    for (s, m), cv in self.cvd.items():
                        if m == market:
                            cv.gap(t0, t1)

    # =================================================================================================
    #  tâches périodiques
    # =================================================================================================
    def _run(self, name: str, fn) -> bool:
        try:
            fn()
            self.errors.pop(name, None)
            self.fetched[name] = self.now_ms()
            return True
        except ERRS as e:
            self.errors[name] = str(e)[:200] or type(e).__name__
            return False

    def seed(self) -> None:
        """Bougies officielles d'une minute des dernières heures : le CVD a un passé exact dès le démarrage."""
        now = self.now_ms()
        for (s, m), c in self.cvd.items():
            def one(s=s, m=m, c=c):
                rows = self.binance.klines_exact(s, "1m", now - self.seed_hours * HOUR, now, m)
                closed = [r for r in rows if r[0] + MIN <= self.now_ms()]
                with self.lock:
                    self.integrity[(s, m)]["seeded"] += c.seed(closed, replace=False)
            self._run(f"bougies {m} {s}", one)

    def reconcile(self, n: int = 12) -> None:
        """Compare les dernières minutes fermées aux bougies officielles, puis les remplace par elles (la bougie officielle est la
        référence des minutes fermées ; les transactions donnent le temps réel de la minute en cours).
        Constat fait sur des journées entières d'archives publiques (tools/check_cvd_archive.py) : sur les perpétuels, une transaction
        agrégée ne porte qu'UNE heure pour toutes ses exécutions ; dans 10 à 25 % des minutes, quelques exécutions sont donc rangées dans
        la minute voisine de celle de la bougie officielle. Ces écarts s'annulent : le total reste exact. Le contrôle compte donc les
        minutes identiques, les minutes décalées, et surtout le RÉSIDU cumulé (transactions comptées - bougies officielles) : il doit
        rester proche de zéro ; un résidu qui grandit veut dire que des transactions manquent ou sont en double."""
        for (s, m), c in self.cvd.items():
            def one(s=s, m=m, c=c):
                rows = self.binance.klines_exact(s, "1m", market=m, limit=n)
                now = self.now_ms()
                st = self.integrity[(s, m)]
                with self.lock:
                    for r in rows:
                        if r[0] + MIN > now - 2000 or (st["lastT"] is not None and r[0] <= st["lastT"]):
                            continue                                     # minute pas encore fermée, ou déjà contrôlée
                        b = c.bars.get(r[0])
                        if b is not None and b[qflow.OK] and b[qflow.N] > 0:
                            dv, db = qflow.bar_diff(b, r)
                            if (dv, db) == (0, 0):
                                st["verified"] += 1
                            else:
                                st["shifted"] += 1
                            st["residual"] += dv
                            st["residualBuy"] += db
                            st["volume"] += int(r[5]) + int(r[6])
                            st["maxResidual"] = max(st["maxResidual"], abs(st["residual"]))
                        else:
                            st["repaired"] += 1
                        c.seed([r])
                        st["lastT"] = r[0]
                    st["mismatch"] = 1 if st["verified"] + st["shifted"] >= 30 and abs(st["residual"]) * 200 > st["volume"] else 0      # résidu > 0,5 % du volume contrôlé
                    st["last"] = (f"résidu de {st['residual'] / UNIT:+.4f} pièce sur {st['volume'] / UNIT:.1f} contrôlées : des transactions "
                                  f"manquent ou sont en double") if st["mismatch"] else None
            self._run(f"contrôle {m} {s}", one)

    def sample_books(self) -> None:
        if self.books is None:
            return
        t = self.now_ms()
        for s in self.symbols:
            try:
                bids, asks = self.books(s)
            except ERRS as e:
                self.errors[f"carnet {s}"] = str(e)[:120]
                continue
            if not bids or not asks:
                continue
            bb, ba = max(p for p, _ in bids), min(p for p, _ in asks)
            mid = (bb + ba) / 2.0
            lo, hi = mid * (1 - BOOK_BAND * 1.05), mid * (1 + BOOK_BAND * 1.05)
            db = [(from_float(p), from_float(q)) for p, q in sorted(((p, q) for p, q in bids if p >= lo and q > 0), reverse=True)]
            da = [(from_float(p), from_float(q)) for p, q in sorted((p, q) for p, q in asks if p <= hi and q > 0)]
            if not db or not da:
                continue
            out = {"t": t, "mid": qbook.mid_price(db, da), "spreadBps": qbook.spread_bps(db, da), "obi": {}, "depth": {}}
            for band in BANDS:
                o = qbook.obi(db, da, band)
                out["obi"][band] = o["obi"]
                out["depth"][band] = {"bid": qbook.depth_usd(db, o["mid"], band), "ask": qbook.depth_usd(da, o["mid"], band)}
            w = qbook.walls(db, da, str(BOOK_BAND), "8")
            out["walls"] = {k: [{"price": p, "usd": u, "mult": m, "dist": d} for p, u, m, d in w[k]] for k in ("bid", "ask")}
            with self.lock:
                self.walls[s].update(t, db, da)
                self.book_last[s] = out
            self.errors.pop(f"carnet {s}", None)

    def poll_fast(self) -> None:
        """Toutes les 30 secondes : intérêt ouvert à l'instant, prix de marque et taux de financement en cours."""
        for s in self.symbols:
            def oi(s=s):
                t, v = self.binance.open_interest(s)
                with self.lock:
                    if not self.oi[s] or self.oi[s][-1][0] < t:
                        self.oi[s].append((t, v))
            self._run(f"intérêt ouvert {s}", oi)
            self._run(f"financement {s}", lambda s=s: self.premium.__setitem__(s, self.binance.premium_index(s)))

    def poll_slow(self) -> None:
        """Toutes les 5 minutes : historique d'intérêt ouvert (première fois), ratio long / short, Bybit et OKX."""
        for s in self.symbols:
            def hist(s=s):
                rows = self.binance.open_interest_hist(s, "5m", 500)
                with self.lock:
                    have = {t for t, _ in self.oi[s]}
                    merged = sorted(list(self.oi[s]) + [(t, v) for t, v, _ in rows if t not in have])
                    self.oi[s].clear()
                    self.oi[s].extend(merged[-4000:])
            if len(self.oi[s]) < 100:
                self._run(f"historique d'intérêt ouvert {s}", hist)
            self._run(f"ratio long / short {s}", lambda s=s: self.ls.__setitem__(s, self.binance.long_short(s, "5m", 12)))
            ot = self.others.setdefault(s, {})

            def bybit(s=s, ot=ot):
                tk = self.bybit.ticker(s)
                ot["bybit"] = {"t": self.now_ms(), "mark": tk["mark"], "funding": tk["funding"], "oi": tk["oi"], "oiUsd": tk["oiUsd"]}
            self._run(f"Bybit {s}", bybit)

            def okx(s=s, ot=ot):
                inst = okx_inst(s)
                oi, fn = self.okx.open_interest(inst), self.okx.funding_now(inst)
                ot["okx"] = {"t": oi["t"], "funding": fn["funding"], "oi": oi["coins"], "oiUsd": oi["usd"]}
            self._run(f"OKX {s}", okx)

    def poll_options(self) -> None:
        if "BTCUSDT" not in self.symbols:
            return

        def go():
            ch = self.deribit.option_chain("BTC")
            now = ch["t"] or self.now_ms()
            rows = ch["rows"]
            live = [r for r in rows if r["oi"] > 0]
            g = qopt.gex_by_strike(live, now, ch["index"])
            exps = sorted({r["expiry"] for r in live if r["expiry"] - now > 2 * HOUR})
            pains = []
            for e in exps[:6]:
                by = {}
                for r in live:
                    if r["expiry"] == e:
                        c, p = by.get(r["strike"], ("0", "0"))
                        by[r["strike"]] = (r["oiText"], p) if r["kind"] == "C" else (c, r["oiText"])
                k, pay = qopt.max_pain({format(k, ".0f"): v for k, v in by.items()})
                calls = sum(D(c) for c, _ in by.values())
                puts = sum(D(p) for _, p in by.values())
                pains.append({"expiry": e, "days": (e - now) / DAY, "maxPain": k, "calls": calls, "puts": puts,
                              "putCall": CTX.divide(puts, calls) if calls > 0 else None})
            spot = ch["index"] or rows[0]["f"]
            near = sorted(g["byStrike"], key=lambda r: abs(r[0] - spot))[:40]
            self.opt = {"t": now, "index": ch["index"], "n": len(rows), "withOi": len(live), "skipped": ch["skipped"],
                        "smile": qopt.smile(rows, now)[:8], "maxPain": pains,
                        "gex": {"total": g["total"], "flip": g["flip"], "callWall": g["callWall"], "putWall": g["putWall"],
                                "byStrike": sorted(near)}}
        self._run("options Deribit", go)

    def poll_onchain(self) -> None:
        if "BTCUSDT" not in self.symbols:
            return

        def go():
            snap = self.onchain.snapshot()
            snap["t"] = self.now_ms()
            cm = snap.get("coinmetrics")
            if isinstance(cm, dict) and cm.get("rows"):
                last = cm["rows"][-1]
                week = cm["rows"][-8] if len(cm["rows"]) >= 8 else None
                snap["coinmetrics"] = {"t": last["t"], "last": {k: v for k, v in last.items() if k != "t"}, "refused": cm["refused"],
                                       "weekAgo": {k: v for k, v in week.items() if k != "t"} if week else None,
                                       "mvrv": [(r["t"], r["CapMVRVCur"]) for r in cm["rows"] if "CapMVRVCur" in r]}
            bad = [k for k, v in snap.items() if isinstance(v, dict) and v.get("error")]
            if len(bad) >= 6:
                raise IngestError("réseau Bitcoin : aucune source ne répond (" + str(snap[bad[0]]["error"])[:80] + ")", "network")
            self.oc = snap
        self._run("réseau Bitcoin", go)

    TASKS = (("books", 2.0), ("gaps", 5.0), ("fast", 30.0), ("reconcile", 300.0), ("slow", 300.0), ("options", 300.0), ("onchain", 300.0))

    def step(self, force: bool = False) -> None:
        """Un tour des tâches arrivées à échéance (appelé chaque seconde par le fil du hub ; `force` : toutes, pour les tests)."""
        t = self.now()
        fns = {"books": self.sample_books, "gaps": self._mark_gaps, "fast": self.poll_fast, "reconcile": self.reconcile,
               "slow": self.poll_slow, "options": self.poll_options, "onchain": self.poll_onchain}
        for name, every in self.TASKS:
            if force or t >= self._due.get(name, 0.0):
                self._due[name] = t + every
                try:
                    fns[name]()
                except Exception as e:                                   # une tâche ne doit jamais arrêter les autres
                    self.errors[name] = f"{type(e).__name__}: {str(e)[:160]}"

    def _loop(self) -> None:
        self.seed()
        self._due["reconcile"] = self.now() + 90.0
        while not self.stop_ev.wait(1.0):
            self.step()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_ev.clear()
        self.thread = threading.Thread(target=self._loop, name="quant-hub", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_ev.set()

    # =================================================================================================
    #  lecture
    # =================================================================================================
    def _window(self, c: qflow.TickCvd, t0: int, t1: int) -> dict:
        w = c.window(t0, t1)
        tot = w["buy"] + w["sell"]
        return {"buy": qflow.coins(w["buy"]), "sell": qflow.coins(w["sell"]), "delta": qflow.coins(w["delta"]),
                "buyUsd": qflow.usd(w["buyq"]), "sellUsd": qflow.usd(w["sellq"]), "deltaUsd": qflow.usd(w["deltaq"]),
                "imb": (w["delta"] / tot) if tot else None, "n": w["n"], "cover": float(w["cover"])}

    def _oi_at(self, s: str, t: int):
        """Intérêt ouvert le plus proche de t (à 10 minutes près), sinon None."""
        best = None
        for tt, v in self.oi[s]:
            if best is None or abs(tt - t) < abs(best[0] - t):
                best = (tt, v)
        return best[1] if best is not None and abs(best[0] - t) <= 10 * MIN else None

    def _price_at(self, c: qflow.TickCvd, t: int):
        """Clôture de la dernière minute commencée avant t (unités)."""
        k = t - t % MIN - MIN
        for _ in range(30):
            b = c.bars.get(k)
            if b is not None and b[qflow.N] > 0:
                return b[qflow.C]
            k -= MIN
        return None

    def _regimes(self, s: str, now: int) -> dict:
        perp, spot = self.cvd[(s, "perp")], self.cvd[(s, "spot")]
        end = now - now % MIN
        out = {}
        prem = self.premium.get(s)
        for name, span in REGIME_WINDOWS:
            p0, p1 = self._price_at(perp, end - span + MIN), self._price_at(perp, end + MIN)
            if p0 is None or p1 is None:
                out[name] = {"error": "prix des perpétuels absent sur cette fenêtre"}
                continue
            wp, ws = perp.window(end - span, end), spot.window(end - span, end)
            tp, ts = wp["buy"] + wp["sell"], ws["buy"] + ws["sell"]
            oi0, oi1 = self._oi_at(s, end - span), self._oi_at(s, end)
            ll = ls = None
            if self.liqs is not None:
                try:
                    evs = self.liqs(s, end - span)
                    ll = from_float(round(sum(e["usd"] for e in evs if e["side"] == "long"), 2))
                    ls = from_float(round(sum(e["usd"] for e in evs if e["side"] == "short"), 2))
                except ERRS:
                    ll = ls = None
            r = qregime.classify(qregime.change(p0, p1), qregime.change(oi0, oi1),
                                 CTX.divide(D(wp["delta"]), D(tp)) if tp else None, CTX.divide(D(ws["delta"]), D(ts)) if ts else None,
                                 prem["funding"] if prem else None, ll, ls)
            out[name] = {"code": r["code"], "label": r["label"], "bias": r["bias"], "score": r["score"], "tags": r["tags"], "notes": r["notes"],
                         "crowd": r["crowd"], "missing": r["missing"], "inputs": r["inputs"],
                         "cover": {"perp": float(wp["cover"]), "spot": float(ws["cover"])}}
        return out

    def _profiles(self, s: str, now: int) -> dict:
        fp = self.footprint(s) if self.footprint else None
        if fp is None:
            return {"error": "transactions exactes pas encore chargées pour cette paire"}
        day = now - now % DAY
        out = {"step": fp.step, "tick": fp.tick, "windows": {}}
        try:
            tick_u = units(repr(fp.tick))
        except ValueError:
            tick_u = 0
        for name, t0, t1 in (("day", day, now), ("24h", now - DAY, now), ("prevDay", day - DAY, day)):
            try:
                with fp.lock:
                    items = [row for _, rows in fp._items(t0, t1) for row in rows]
                    covered = fp.covered_ms(t0, t1)
                if not items:
                    out["windows"][name] = {"error": "aucune transaction enregistrée sur cette période"}
                    continue
                p = qprofile.from_buckets(items, fp.step, tick_u)
                lv = p.levels(70)
                out["windows"][name] = {"t0": t0, "t1": t1, "poc": lv["poc"], "vah": lv["vah"], "val": lv["val"],
                                        "volume": qflow.coins(lv["total"]), "delta": qflow.coins(lv["delta"]), "share": lv["share"],
                                        "rows": lv["rows"], "cover": covered / max(1, t1 - t0)}
            except ERRS as e:
                out["windows"][name] = {"error": str(e)[:120]}
        return out

    def _venues(self, now: int) -> dict:
        out = {}
        for name, span in (("5m", 5 * MIN), ("1h", HOUR), ("4h", 4 * HOUR)):
            end = now - now % MIN + MIN
            w = self.venues.window(end - span, end)
            rows = []
            for v, x in sorted(w["venues"].items(), key=lambda kv: -(kv[1]["buyq"] + kv[1]["sellq"])):
                tot = x["buyq"] + x["sellq"]
                rows.append({"id": v, "name": VENUE_NAMES.get(v, v), "buyUsd": qflow.usd(x["buyq"]), "sellUsd": qflow.usd(x["sellq"]),
                             "deltaUsd": qflow.usd(x["deltaq"]), "imb": x["deltaq"] / tot if tot else None, "n": x["n"]})
            tot = w["buyq"] + w["sellq"]
            out[name] = {"venues": rows, "buyUsd": qflow.usd(w["buyq"]), "sellUsd": qflow.usd(w["sellq"]), "deltaUsd": qflow.usd(w["deltaq"]),
                         "imb": w["deltaq"] / tot if tot else None}
        first = [v.first_tick for v in self.venues.venues.values() if v.first_tick]
        out["since"] = min(first) if first else None
        return out

    def snapshot(self, symbol: str, max_age: float = 2.0) -> dict:
        s = symbol.upper()
        if s not in self.symbols:
            return {"ok": False, "why": f"paire non suivie : {s}"}
        cached = self._snap.get(s)
        if cached and self.now() - cached[0] <= max_age:
            return cached[1]
        now = self.now_ms()
        out = {"ok": True, "symbol": s, "now": now}
        with self.lock:
            perp, spot = self.cvd[(s, "perp")], self.cvd[(s, "spot")]
            end = now - now % MIN + MIN
            cv = {"windows": {}}
            for name, span in WINDOWS:
                a, b = self._window(perp, end - span, end), self._window(spot, end - span, end)
                cv["windows"][name] = {"perp": a, "spot": b}
            bars5 = {m: qflow.resample(c.closed(now, now - DAY), 5 * MIN) for m, c in (("perp", perp), ("spot", spot))}
            cum = {m: qflow.cumulative(bars5[m]) for m in bars5}
            cv["series"] = {m: [[b[qflow.T], b[qflow.C] / UNIT, c / UNIT, 1 if b[qflow.OK] else 0] for b, c in zip(bars5[m], cum[m])] for m in bars5}
            dv = []
            for m in ("perp", "spot"):
                for d in qflow.divergences(bars5[m], left=3, right=3, max_span=72):
                    dv.append({"market": m, "side": d["side"], "kind": d["kind"], "t1": d["t1"], "t2": d["t2"], "known": d["known"],
                               "p1": d["p1"] / UNIT, "p2": d["p2"] / UNIT, "c1": d["c1"] / UNIT, "c2": d["c2"] / UNIT,
                               "strength": float(d["strength"]), "text": d["text"]})
            cv["divergences"] = sorted(dv, key=lambda d: -d["known"])[:8]
            ab = []
            for m, c in (("perp", perp), ("spot", spot)):
                for a in qflow.absorptions(c.closed(now, now - 6 * HOUR), base=60)[-6:]:
                    ab.append({"market": m, "t": a["t"], "side": a["side"], "delta": a["delta"] / UNIT, "volume": a["volume"] / UNIT,
                               "imb": float(a["imb"]), "volRatio": float(a["volRatio"]), "price": a["price"] / UNIT, "ok": a["ok"], "text": a["text"]})
            cv["absorptions"] = sorted(ab, key=lambda a: -a["t"])[:8]
            cv["last"] = {m: (c.last_px / UNIT if c.last_px else None) for m, c in (("perp", perp), ("spot", spot))}
            cv["liveSince"] = {m: c.first_tick for m, c in (("perp", perp), ("spot", spot))}
            out["cvd"] = cv
            out["integrity"] = {}
            for m in ("perp", "spot"):
                st = dict(self.integrity[(s, m)])
                for k in ("residual", "residualBuy", "maxResidual", "volume"):
                    st[k] = st[k] / UNIT
                out["integrity"][m] = st
            out["regime"] = self._regimes(s, now)
            bk = self.book_last.get(s)
            if bk:
                wt = self.walls[s]
                out["book"] = {**bk, "age": now - bk["t"], "events": [dict(e) for e in wt.events[-12:]][::-1],
                               "tracked": [{"side": w["side"], "price": w["price"], "usd": w["cur"], "peak": w["peak"], "traded": w["traded"],
                                            "ageMs": now - w["first"], "absorbed": w["absorbed"]} for w in wt.active()[:10]]}
            else:
                out["book"] = {"error": self.errors.get(f"carnet {s}") or "carnet pas encore synchronisé"}
            oi = list(self.oi[s])
            prem = self.premium.get(s)
            ls = self.ls.get(s)
            out["derivs"] = {"oi": oi[-1][1] if oi else None, "oiT": oi[-1][0] if oi else None, "oiPoints": len(oi),
                             "oi1h": qregime.change(self._oi_at(s, now - HOUR), oi[-1][1]) if oi else None,
                             "oi24h": qregime.change(self._oi_at(s, now - DAY), oi[-1][1]) if oi else None,
                             "funding": prem["funding"] if prem else None, "mark": prem["mark"] if prem else None,
                             "index": prem["index"] if prem else None, "nextFunding": prem["nextFunding"] if prem else None,
                             "longShare": ls[-1][2] if ls else None, "longShort": ls[-1][1] if ls else None,
                             "others": self.others.get(s) or {}}
            if s == "BTCUSDT":
                out["venues"] = self._venues(now)
        out["profile"] = self._profiles(s, now)
        if s == "BTCUSDT":
            out["options"] = self.opt or {"error": self.errors.get("options Deribit") or "chaîne d'options pas encore lue"}
            out["onchain"] = self.oc or {"error": self.errors.get("réseau Bitcoin") or "réseau Bitcoin pas encore lu"}
        out["sources"] = self.status()
        out = js(out)
        self._snap[s] = (self.now(), out)
        return out

    def status(self) -> dict:
        http = [c.status() for c in (self.binance.fapi, self.binance.spot, self.bybit.http, self.okx.http, self.deribit.http,
                                     *self.onchain.clients())]
        ws = {}
        for k, c in (self.ws_clients() if self.ws_clients else {}).items():
            ws[k] = {"connected": bool(c.connected), "connects": c.connects, "error": (c.last_error or None) if not c.connected else None,
                     "gaps": len(getattr(c, "gaps", ())), "nextWait": round(getattr(c, "next_wait", 0.0), 1), "url": c.url.split("?")[0],
                     "lastMsgAge": round(self.now() - c.last_msg, 1) if c.last_msg else None}
        return {"http": http, "ws": ws, "errors": dict(self.errors), "fetched": dict(self.fetched)}
