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

V45.1 : le moteur ne tourne que pendant que la page le demande (voir `touch`) ; il ne suit que les paires demandées.

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
IDLE_S = 300.0                # arret du moteur 5 minutes apres la derniere demande de la page
SEED_PAUSE = 0.4              # secondes entre deux pages de bougies au demarrage (requetes etalees : jamais de rafale vers Binance)
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
                 ws_clients=None, now=time.time, seed_hours: int = 24):
        self.symbols = [s.upper() for s in symbols]
        self.binance, self.bybit, self.okx = binance or Binance(), bybit or Bybit(), okx or Okx()
        for c in self.binance.clients():      # le quota de Binance est partage avec tout le terminal : le moteur s'efface des 50 %
            c.weight_guard = min(getattr(c, "weight_guard", 0.8), 0.5)
        self.deribit, self.onchain = deribit or Deribit(), onchain or OnChain()
        self.books, self.footprint, self.liqs, self.ws_clients = books, footprint, liqs, ws_clients
        self.now = now
        self.seed_hours = seed_hours
        self.seed_pause = SEED_PAUSE
        self.autostart = True                 # faux dans les tests : les taches sont alors lancees a la main
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
        # V45.1 : le moteur ne tourne QUE quand l'onglet Quant est ouvert. Tant que personne ne demande /api/quant, il ne lit rien, ne
        # compte rien et n'envoie aucune requete : le terminal demarre exactement comme avant. Il s'arrete IDLE_S secondes apres la
        # derniere demande. Seules les paires demandees sont suivies.
        self.active = False
        self.last_used = 0.0
        self.wanted: dict = {}                # paire -> heure de la derniere demande
        self.seeded: set = set()
        self.idle_since = None                # heure (ms) du dernier arret : a la reprise, les minutes manquees sont marquees incompletes

    def now_ms(self) -> int:
        return int(self.now() * 1000)

    # =================================================================================================
    #  flux en direct
    # =================================================================================================
    def on_binance_agg(self, x: dict, market: str) -> None:
        """Transaction agrégée Binance ; `m` vrai = acheteur passif = vente agressive. Textes lus en entiers exacts."""
        if not self.active or x["s"].upper() not in self.wanted:
            return
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
        if not self.active or "BTCUSDT" not in self.wanted:
            return
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

    def seed(self, symbols=None) -> None:
        """Bougies officielles d'une minute des dernieres heures, pour les paires demandees : le CVD a un passe exact. Petites pages
        (499 bougies : poids 2 chez Binance au lieu de 10) et une pause entre deux pages : aucune rafale."""
        now = self.now_ms()
        for (s, m), c in self.cvd.items():
            if symbols is not None and s not in symbols:
                continue

            def one(s=s, m=m, c=c):
                rows = self.binance.klines_exact(s, "1m", now - self.seed_hours * HOUR, now, m, page=499, pause=self.seed_pause, wait=self.stop_ev.wait)
                closed = [r for r in rows if r[0] + MIN <= self.now_ms()]
                with self.lock:
                    self.integrity[(s, m)]["seeded"] += c.seed(closed, replace=False)
            self._run(f"bougies {m} {s}", one)
            if self.stop_ev.is_set():
                return
        if symbols:
            self.seeded.update(symbols)

    def reconcile(self, n: int = 12) -> None:
        """Compare les dernières minutes fermées aux bougies officielles, puis les remplace par elles (la bougie officielle est la
        référence des minutes fermées ; les transactions donnent le temps réel de la minute en cours).
        Constat fait sur des journées entières d'archives publiques (tools/check_cvd_archive.py) : sur les perpétuels, une transaction
        agrégée ne porte qu'UNE heure pour toutes ses exécutions ; dans 10 à 25 % des minutes, quelques exécutions sont donc rangées dans
        la minute voisine de celle de la bougie officielle. Ces écarts s'annulent : le total reste exact. Le contrôle compte donc les
        minutes identiques, les minutes décalées, et surtout le RÉSIDU cumulé (transactions comptées - bougies officielles) : il doit
        rester proche de zéro ; un résidu qui grandit veut dire que des transactions manquent ou sont en double."""
        for (s, m), c in self.cvd.items():
            if s not in self.wanted:
                continue

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
        """Carnet de chaque paire demandee. Le desequilibre et la profondeur se calculent en ENTIERS (exacts et rapides : un carnet BTC a
        plus de 10 000 niveaux dans +/- 1 %) ; seuls les niveaux candidats a etre des murs passent en decimal pour le suivi."""
        if self.books is None:
            return
        t = self.now_ms()
        for s in self.symbols:
            if s not in self.wanted:
                continue
            try:
                bids, asks = self.books(s)
                if not bids or not asks:
                    continue
                out = self._book_measures(s, t, bids, asks)
            except ERRS as e:
                self.errors[f"carnet {s}"] = str(e)[:120]
                continue
            if out is not None:
                with self.lock:
                    self.book_last[s] = out
                self.errors.pop(f"carnet {s}", None)

    def _book_measures(self, s: str, t: int, bids, asks):
        bb, ba = max(p for p, _ in bids), min(p for p, _ in asks)
        mid = (bb + ba) / 2.0
        lo, hi = mid * (1 - BOOK_BAND * 1.02), mid * (1 + BOOK_BAND * 1.02)
        # entiers exacts : un prix ou une quantite de bourse a au plus 8 decimales, l'arrondi du produit flottant redonne donc l'entier juste
        bu = sorted(((round(p * UNIT), round(q * UNIT)) for p, q in bids if p >= lo and q > 0), reverse=True)
        au = sorted((round(p * UNIT), round(q * UNIT)) for p, q in asks if p <= hi and q > 0)
        if not bu or not au:
            return None
        mid2 = bu[0][0] + au[0][0]                                       # deux fois le prix milieu (reste entier)
        out = {"t": t, "mid": mid2 / (2 * UNIT), "spreadBps": (au[0][0] - bu[0][0]) * 20000 / mid2, "obi": {}, "depth": {}}
        notion = {"bid": [(p, p * q) for p, q in bu], "ask": [(p, p * q) for p, q in au]}
        for band in BANDS:
            num, den = D(band).as_integer_ratio()
            lim = mid2 * num                                             # distance maximale, a la meme echelle que d ci-dessous
            w, dep = {}, {}
            for side in ("bid", "ask"):
                ws = ds = 0
                for p, n in notion[side]:
                    d = abs(2 * p - mid2) * den
                    if d > lim:
                        break
                    ws += n * (lim - d)                                  # poids lineaire : 1 au prix milieu, 0 au bord de la bande
                    ds += n
                w[side], dep[side] = ws, ds
            tot = w["bid"] + w["ask"]
            out["obi"][band] = (w["bid"] - w["ask"]) / tot if tot else 0.0
            out["depth"][band] = {"bid": qflow.usd(dep["bid"]), "ask": qflow.usd(dep["ask"])}
        # murs : mediane exacte sur tous les niveaux de la bande, puis seuls les candidats (et les murs deja suivis) passent en decimal
        num, den = D(str(BOOK_BAND)).as_integer_ratio()
        lim = mid2 * num
        inband = {side: [(p, n) for p, n in notion[side] if abs(2 * p - mid2) * den <= lim] for side in ("bid", "ask")}
        allv = sorted(n for side in inband.values() for _, n in side if n > 0)
        if not allv:
            return out
        k = len(allv)
        med = from_units(allv[k // 2], 16) if k % 2 else CTX.divide(from_units(allv[k // 2 - 1] + allv[k // 2], 16), Decimal(2))
        thr = int(CTX.multiply(med, Decimal(8)).scaleb(16).to_integral_value()) // 4      # marge : tout ce qui pese au moins 2 medianes
        wt = self.walls[s]
        with self.lock:
            tracked = {(name, int(p.scaleb(8))) for (name, p) in wt.live}
        dec = {}
        for side in ("bid", "ask"):
            rows = inband[side]
            keep = [(p, n) for i, (p, n) in enumerate(rows) if i == 0 or n >= thr or (side, p) in tracked]
            dec[side] = [(from_units(p), CTX.divide(from_units(n, 16), from_units(p))) for p, n in keep]
        w = qbook.walls(dec["bid"], dec["ask"], str(BOOK_BAND), "8", median=med)
        out["walls"] = {k2: [{"price": p, "usd": u, "mult": m, "dist": d} for p, u, m, d in w[k2]] for k2 in ("bid", "ask")}
        with self.lock:
            wt.update(t, dec["bid"], dec["ask"], median=med)
        return out

    def poll_fast(self) -> None:
        """Toutes les 30 secondes : intérêt ouvert à l'instant, prix de marque et taux de financement en cours."""
        for s in self.symbols:
            if s not in self.wanted:
                continue
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
            if s not in self.wanted:
                continue
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
        if "BTCUSDT" not in self.wanted:
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
        if "BTCUSDT" not in self.wanted:
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

    TASKS = (("books", 5.0), ("gaps", 5.0), ("fast", 30.0), ("reconcile", 300.0), ("slow", 300.0), ("options", 300.0), ("onchain", 300.0))

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

    def touch(self, symbol: str, start: bool = True) -> None:
        """La page demande cette paire : le moteur se met en marche (ou reste en marche) pour elle."""
        s = symbol.upper()
        now = self.now()
        self.last_used = now
        fresh = s not in self.wanted
        self.wanted[s] = now
        if not self.active:
            if self.idle_since is not None:                              # reprise : ce qui s'est passe pendant l'arret n'a pas ete compte
                t1 = self.now_ms()
                t0 = max(self.idle_since, t1 - self.seed_hours * HOUR)
                with self.lock:
                    for cv in list(self.cvd.values()) + list(self.venues.venues.values()):
                        if cv.first_tick is not None:
                            cv.gap(t0, t1)
                self.idle_since = None
            self.active = True
            self._due.clear()
        elif fresh:
            for k in ("fast", "slow", "books", "options", "onchain"):
                self._due.pop(k, None)                                   # une nouvelle paire est lue tout de suite
        if start and not (self.thread and self.thread.is_alive()):
            self.stop_ev.clear()
            self.thread = threading.Thread(target=self._loop, name="quant-hub", daemon=True)
            self.thread.start()

    def _loop(self) -> None:
        self._due.setdefault("reconcile", self.now() + 90.0)
        while not self.stop_ev.wait(1.0):
            if self.now() - self.last_used > IDLE_S:                     # plus personne ne regarde : on s'arrete, sans rien garder a jour
                self.active = False
                self.idle_since = self.now_ms()
                self.wanted.clear()
                self.seeded.clear()
                return
            todo = [s for s in list(self.wanted) if s not in self.seeded]
            if todo:
                self.seed(todo)
            self.step()

    def start(self) -> None:
        """Garde par compatibilite : le moteur ne demarre plus avec le terminal, mais a la premiere demande de la page (touch)."""

    def stop(self) -> None:
        self.stop_ev.set()
        self.active = False

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
        self.touch(s, start=self.autostart)
        cached = self._snap.get(s)
        if cached and self.now() - cached[0] <= max_age:
            return cached[1]
        now = self.now_ms()
        out = {"ok": True, "symbol": s, "now": now, "warming": s not in self.seeded}
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
