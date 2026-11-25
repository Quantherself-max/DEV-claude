"""Baleines des options BTC et photos de l'intérêt ouvert (V51), lues en continu chez Deribit et gardées sur le disque.

Contrairement au reste du moteur exact, ce lecteur tourne même onglet Quant fermé : une variation sur 24 heures demande une photo prise
il y a 24 heures. Il est léger : toutes les 5 minutes, les transactions d'options depuis la dernière lecture (une page, environ 50 Ko) ;
toutes les heures, une photo de l'intérêt ouvert de chaque option (une requête). Au premier lancement, il lit les 24 dernières heures de
transactions (environ 13 pages, 4 Mo), page par page avec une pause.

V54.1 : à chaque photo horaire, l'exposition delta (DEX) et l'exposition gamma (GEX) de toutes les options ouvertes sont calculées
(quant.options.exposures) et gardées 120 jours : c'est l'historique DEX et GEX de l'onglet Quant. Deribit ne publie pas l'historique de
l'intérêt ouvert par option : cet historique commence au premier relevé de ton terminal et ne contient que des relevés réels.

Fichiers (dossier de données, sous-dossier « options ») :
  oi_BTC.json       photos horaires {instrument: contrats ouverts}, 3 jours au plus ;
  expo_BTC.json     relevés horaires [heure, indice, DEX, GEX, DEX des calls, DEX des puts] (dollars), 120 jours au plus ;
  whales_BTC.json   baleines (ordres d'au moins 1 million de dollars), 3 jours au plus, et l'heure de la dernière transaction lue.

Rien n'est inventé : sans photo assez ancienne, la page dit l'écart réel entre les deux photos comparées."""
from __future__ import annotations
import json
import os
import threading
import time
from pathlib import Path

from quant import options as qopt
from quant import whales as qw
from .core import IngestError
from .venues import Deribit

HOUR, DAY = 3_600_000, 86_400_000
KEEP_MS = 3 * DAY
EXPO_KEEP = 120 * DAY                                                    # V54.1 : historique DEX / GEX
ERRS = (IngestError, KeyError, IndexError, TypeError, ValueError, ArithmeticError, AttributeError, OSError)


class OptionsFlow:
    def __init__(self, folder, deribit: Deribit | None = None, currency: str = "BTC", min_usd: float = qw.WHALE_USD,
                 now=time.time, trade_every: float = 300.0, oi_every: float = 3600.0, page_pause: float = 0.5):
        self.folder = Path(folder) / "options"
        self.deribit = deribit or Deribit()
        self.cur, self.min_usd, self.now = currency, float(min_usd), now
        self.trade_every, self.oi_every, self.page_pause = trade_every, oi_every, page_pause
        self.lock = threading.Lock()
        self.stop_ev = threading.Event()
        self.thread = None
        self.snaps: list = []                 # [[heure ms, indice, {instrument: contrats}]]
        self.orders: list = []                # baleines, de la plus ancienne à la plus récente
        self.expo: list = []                  # V54.1 : [[heure ms, indice, DEX, GEX, DEX calls, DEX puts]]
        self.last_t = None                    # heure de la dernière transaction lue
        self.grouper = qw.Grouper(self.min_usd)
        self.error = None
        self.state = "pas encore lu"
        self._next_trades = 0.0
        self._next_oi = 0.0
        self._load()

    def now_ms(self) -> int:
        return int(self.now() * 1000)

    # ---------- disque ----------
    def _path(self, what: str) -> Path:
        return self.folder / f"{what}_{self.cur}.json"

    def _load(self) -> None:
        try:
            d = json.loads(self._path("oi").read_text(encoding="utf-8"))
            self.snaps = [s for s in d.get("snaps", []) if isinstance(s, list) and len(s) == 3]
        except (OSError, ValueError):
            self.snaps = []
        try:
            d = json.loads(self._path("expo").read_text(encoding="utf-8"))
            self.expo = [e for e in d.get("expo", []) if isinstance(e, list) and len(e) == 6 and all(isinstance(x, (int, float)) or x is None for x in e)]
        except (OSError, ValueError):
            self.expo = []
        try:
            d = json.loads(self._path("whales").read_text(encoding="utf-8"))
            self.orders = [o for o in d.get("orders", []) if isinstance(o, dict) and "t" in o]
            self.last_t = d.get("last")
        except (OSError, ValueError):
            self.orders, self.last_t = [], None

    def _save(self, what: str, doc: dict) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            p = self._path(what)
            tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(doc), encoding="utf-8")
            os.replace(tmp, p)
        except OSError as e:
            self.error = f"enregistrement impossible : {e}"

    # ---------- lectures ----------
    def snap_oi(self) -> None:
        """Photo de l'intérêt ouvert de chaque option (1 contrat = 1 BTC chez Deribit)."""
        rows, t = self.deribit.book_summary(self.cur, "option")
        t = t or self.now_ms()
        oi, index, chain = {}, None, []
        for r in rows:
            n = r.get("instrument_name")
            m = qw.parse_name(n)
            if m is None:
                continue
            oi[n] = float(r.get("open_interest") or 0.0)
            if r.get("estimated_delivery_price"):
                index = float(r["estimated_delivery_price"])
            iv, f = r.get("mark_iv"), r.get("underlying_price")             # V54.1 : de quoi calculer le DEX et le GEX
            if oi[n] > 0 and iv and f and iv > 0 and f > 0:
                chain.append({"strike": m["strike"], "kind": m["kind"], "expiry": m["expiry"], "oi": oi[n], "iv": float(iv) / 100.0, "f": float(f)})
        if not oi:
            raise IngestError("Deribit : aucune option dans le résumé du carnet", "format")
        with self.lock:
            self.snaps.append([t, index, oi])
            self.snaps = [s for s in self.snaps if s[0] >= t - KEEP_MS]
            doc = {"snaps": self.snaps}
        self._save("oi", doc)
        if chain:
            x = qopt.exposures(chain, t)
            if x["n"]:
                with self.lock:
                    if not self.expo or t > self.expo[-1][0]:
                        self.expo.append([t, index, round(x["dex"], 2), round(x["gex"], 2), round(x["dexCalls"], 2), round(x["dexPuts"], 2)])
                    self.expo = [e for e in self.expo if e[0] >= t - EXPO_KEEP]
                    edoc = {"expo": self.expo}
                self._save("expo", edoc)

    def poll_trades(self) -> int:
        """Transactions depuis la dernière lecture (24 heures au plus) ; renvoie le nombre de nouvelles baleines."""
        end = self.now_ms()
        start = max(self.last_t or 0, end - DAY)
        found, pages = [], 0
        while not self.stop_ev.is_set():
            trades, more = self.deribit.option_trades(self.cur, start, end)
            pages += 1
            found += self.grouper.feed(trades)
            if trades:
                last = int(trades[-1]["timestamp"])
                self.last_t = max(self.last_t or 0, last)
                start = last if last > start else start + 1
            if not more or not trades or pages >= 60:
                break
            if self.stop_ev.wait(self.page_pause):
                break
        found += self.grouper.finish() if not self.stop_ev.is_set() else []
        with self.lock:
            have = {(o["t"], o["legs"][0]["name"], o["contracts"]) for o in self.orders}
            for o in found:
                if (o["t"], o["legs"][0]["name"], o["contracts"]) not in have:
                    self.orders.append(o)
            self.orders.sort(key=lambda o: o["t"])
            self.orders = [o for o in self.orders if o["t"] >= end - KEEP_MS]
            doc = {"last": self.last_t, "orders": self.orders}
        self._save("whales", doc)
        return len(found)

    def step(self, force: bool = False) -> None:
        t = self.now()
        if force or t >= self._next_oi:
            self._next_oi = t + self.oi_every
            try:
                self.snap_oi()
                self.error = None
            except ERRS as e:
                self.error = f"intérêt ouvert : {str(e)[:160]}"
                self._next_oi = t + 300.0                                  # nouvel essai dans 5 minutes
        if force or t >= self._next_trades:
            self._next_trades = t + self.trade_every
            try:
                self.poll_trades()
                self.state = "à jour"
                if self.error and self.error.startswith("transactions"):
                    self.error = None
            except ERRS as e:
                self.error = f"transactions : {str(e)[:160]}"

    def _loop(self) -> None:
        if self.stop_ev.wait(20.0):                                         # laisse le terminal démarrer d'abord
            return
        while not self.stop_ev.is_set():
            self.step()
            if self.stop_ev.wait(5.0):
                return

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_ev.clear()
        self.thread = threading.Thread(target=self._loop, name="options-baleines", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_ev.set()

    # ---------- pour la page ----------
    def reference(self, now_ms: int, hours: float = 24.0):
        """(photo actuelle, photo de comparaison) : la plus proche de `hours` heures avant la dernière ; à défaut, la plus ancienne (au
        moins une heure d'écart). None si une seule photo."""
        with self.lock:
            snaps = list(self.snaps)
        if len(snaps) < 2:
            return (snaps[-1] if snaps else None), None
        cur = snaps[-1]
        target = cur[0] - hours * HOUR
        old = min(snaps[:-1], key=lambda s: abs(s[0] - target))
        if abs(old[0] - target) > 3 * HOUR:
            old = snaps[0]
        if cur[0] - old[0] < HOUR:
            return cur, None
        return cur, old

    def expo_summary(self, now_ms: int) -> dict | None:
        """V54.1 : pour la page : le dernier relevé, les relevés horaires des 7 derniers jours, un relevé par jour (le dernier de chaque jour
        UTC) sur 120 jours, et le rang du dernier DEX et du dernier GEX parmi les relevés horaires de 7, 30 et 90 jours (percentile, 0 à 100)."""
        with self.lock:
            ex = list(self.expo)
        if not ex:
            return None
        last = ex[-1]
        daily, seen = [], {}
        for e in ex:
            seen[e[0] // DAY] = e
        daily = [[e[0], e[2], e[3]] for _, e in sorted(seen.items())]
        hourly = [[e[0], e[2], e[3]] for e in ex if e[0] >= last[0] - 7 * DAY]
        ranks = {}
        for days in (7, 30, 90):
            win = [e for e in ex if e[0] >= last[0] - days * DAY]
            span = (last[0] - win[0][0]) / DAY
            r = {"span": span, "n": len(win)}
            for i, key in ((2, "dex"), (3, "gex")):
                vals = [e[i] for e in win if e[i] is not None]
                r[key] = round(100.0 * sum(1 for v in vals if v < last[i]) / len(vals)) if len(vals) >= 2 else None
            ranks[str(days)] = r
        return {"last": {"t": last[0], "index": last[1], "dex": last[2], "gex": last[3], "dexCalls": last[4], "dexPuts": last[5]},
                "first": ex[0][0], "n": len(ex), "hourly": hourly, "daily": daily, "ranks": ranks}

    def summary(self, now_ms: int | None = None, hours: int = 24, top: int = 12, min_usd: float | None = None) -> dict:
        """`min_usd` : seuil d'affichage (au moins celui de l'enregistrement)."""
        now = now_ms or self.now_ms()
        floor = max(self.min_usd, float(min_usd or self.min_usd))
        cur, old = self.reference(now)
        oi = None
        if cur is not None and old is not None:
            oi = qw.oi_changes(cur[2], old[2], now, cur[1], top=6)
            oi.update(t=cur[0], ref=old[0], gapH=(cur[0] - old[0]) / HOUR, index=cur[1])
        with self.lock:
            sel = [o for o in self.orders if o["t"] >= now - hours * HOUR and o["notional"] >= floor]
        biggest = sorted(sel, key=lambda o: -o["notional"])[:top]
        latest = sorted(sel, key=lambda o: -o["t"])[:top]
        return {"whales": {"sum": qw.summarize(sel, now, hours), "biggest": biggest, "latest": latest, "minUsd": floor, "recordUsd": self.min_usd,
                           "since": max(now - hours * HOUR, min((o["t"] for o in self.orders), default=now)), "last": self.last_t},
                "oi": oi, "snaps": len(self.snaps), "firstSnap": self.snaps[0][0] if self.snaps else None, "expo": self.expo_summary(now),
                "error": self.error, "state": self.state, "hours": hours}
