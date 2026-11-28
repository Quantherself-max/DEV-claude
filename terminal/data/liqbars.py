"""V55 : liquidations par minute et par bourse, pour la fenêtre « Liquidations » sous le graphique (une barre par bougie, quelle que soit
l'unité de temps).

Sources (toutes réelles, lues en direct par le terminal) :
  - Binance, pour chaque symbole suivi : flux forceOrder (data/live.py). Binance n'envoie AU PLUS qu'une liquidation par seconde (la
    dernière de la seconde) : pendant une cascade, son total est un MINIMUM ;
  - Bybit et OKX, pour le BTC : flux du registre des bourses (data/cexflow.py).
Chaque minute garde, par bourse, [dollars des longs liquidés, dollars des shorts liquidés]. Un long liquidé est une vente forcée (barre
rouge, vers le bas) ; un short liquidé est un achat forcé (barre verte, vers le haut).

Au premier démarrage, l'historique est amorcé :
  - Binance : chaque liquidation déjà notée par le terminal (data_local/liqs_SYMBOLE.jsonl), à la seconde près ;
  - Bybit et OKX (BTC) : les tranches de 5 minutes du registre des bourses (48 heures au plus), placées au début de leur tranche.
Rien n'est inventé : avant le premier relevé, la fenêtre n'a pas de barre (et le dit). Gardé 30 jours, sauvegardé toutes les minutes
(data_local/liqbars/SYMBOLE.json). Bibliothèque standard uniquement."""
from __future__ import annotations
import json
import os
import threading
import time
from bisect import bisect_right
from pathlib import Path

MIN = 60_000
DAY = 86_400_000
KEEP_MS = 30 * DAY
SAVE_EVERY_S = 60.0
NAMES = {"binance": "Binance", "bybit": "Bybit", "okx": "OKX"}


class LiqBars:
    def __init__(self, data_dir: str | None = None, keep_ms: int = KEEP_MS, now=time.time):
        self.dir = Path(data_dir) / "liqbars" if data_dir else None
        self.keep, self.now = keep_ms, now
        self.lock = threading.Lock()
        self.m: dict = {}            # symbole -> {minute (ms): {bourse: [longs $, shorts $]}}
        self.first: dict = {}        # symbole -> {bourse: première minute enregistrée}
        self.upto: dict = {}         # symbole -> heure (ms) de la dernière sauvegarde : tout ce qui précède est sur le disque
        self.rev: dict = {}          # symbole -> compteur de changements (cache des réponses)
        self.dirty: set = set()
        self.saved_at = 0.0

    # ---------- écriture ----------
    def add(self, sym: str, ex: str, t_ms: int, side: str, usd: float) -> None:
        if not usd or usd <= 0 or side not in ("long", "short"):
            return
        sym, t = sym.upper(), int(t_ms)
        mn = t - t % MIN
        with self.lock:
            row = self.m.setdefault(sym, {}).setdefault(mn, {}).setdefault(ex, [0.0, 0.0])
            row[0 if side == "long" else 1] += float(usd)
            f = self.first.setdefault(sym, {})
            if ex not in f or mn < f[ex]:
                f[ex] = mn
            self.rev[sym] = self.rev.get(sym, 0) + 1
            self.dirty.add(sym)
        self.maybe_save()

    def seed_events(self, sym: str, ex: str, events) -> int:
        """Amorce avec des liquidations notées une par une ({t, side, usd}) qui ne sont pas encore dans le registre : avant la première
        minute de cette bourse, ou après la dernière sauvegarde (terminal arrêté avant d'avoir sauvegardé). Rend le nombre ajouté."""
        sym = sym.upper()
        with self.lock:
            first = self.first.get(sym, {}).get(ex)
            upto = self.upto.get(sym)
        cut = self.now() * 1000 - self.keep
        n = 0
        for e in events:
            try:
                t, side, usd = int(e["t"]), e["side"], float(e["usd"])
            except (KeyError, TypeError, ValueError):
                continue
            if t < cut or (first is not None and first <= t < (upto if upto is not None else float("inf"))):
                continue
            self.add(sym, ex, t, side, usd)
            n += 1
        return n

    def seed_buckets(self, sym: str, ex: str, buckets: dict) -> int:
        """Amorce avec des tranches {début (ms): (longs $, shorts $)} (registre des bourses, 5 minutes), seulement AVANT la première minute
        de cette bourse : jamais deux fois la même liquidation."""
        sym = sym.upper()
        with self.lock:
            first = self.first.get(sym, {}).get(ex)
        cut = self.now() * 1000 - self.keep
        n = 0
        for b, (lo, sh) in sorted(buckets.items()):
            b = int(b)
            if b < cut or (first is not None and b >= first):
                continue
            if lo:
                self.add(sym, ex, b, "long", lo)
            if sh:
                self.add(sym, ex, b, "short", sh)
            n += 1
        return n

    # ---------- lecture ----------
    def bars(self, sym: str, times_ms: list, now_ms: int | None = None) -> dict:
        """Pour les bougies qui commencent à times_ms (croissant) : liqLong / liqShort (dollars par bougie ; None avant le premier relevé),
        liqSince (première minute enregistrée), liqEx (bourses vues), liqRev (compteur de changements)."""
        sym = sym.upper()
        n = len(times_ms)
        out = {"liqLong": [None] * n, "liqShort": [None] * n, "liqSince": None, "liqEx": [], "liqRev": 0}
        with self.lock:
            m = self.m.get(sym) or {}
            first = dict(self.first.get(sym) or {})
            out["liqRev"] = self.rev.get(sym, 0)
            items = sorted(m.items()) if n else []
        if not first or not n:
            return out
        since = min(first.values())
        out["liqSince"] = since
        out["liqEx"] = [NAMES.get(e, e) for e in sorted(first, key=lambda e: list(NAMES).index(e) if e in NAMES else 9)]
        end = (now_ms or int(self.now() * 1000)) + MIN
        lo, sh = out["liqLong"], out["liqShort"]
        for i, t in enumerate(times_ms):                                   # bougies couvertes : zéro plutôt que rien
            nxt = times_ms[i + 1] if i + 1 < n else end
            if nxt > since:
                lo[i] = sh[i] = 0.0
        for mn, row in items:
            i = bisect_right(times_ms, mn) - 1
            if i < 0 or (i + 1 >= n and mn >= end):
                continue
            for v in row.values():
                lo[i] += v[0]
                sh[i] += v[1]
        return out

    def revision(self, sym: str) -> int:
        with self.lock:
            return self.rev.get(sym.upper(), 0)

    # ---------- disque ----------
    def prune(self) -> None:
        cut = self.now() * 1000 - self.keep
        with self.lock:
            for sym, m in self.m.items():
                old = [k for k in m if k < cut]
                for k in old:
                    del m[k]
                if old:
                    self.dirty.add(sym)
                    self.first[sym] = {}
                    for mn in sorted(m):
                        for ex in m[mn]:
                            self.first[sym].setdefault(ex, mn)

    def maybe_save(self, force: bool = False) -> None:
        if self.dir is None or not self.dirty or (not force and time.time() - self.saved_at < SAVE_EVERY_S):
            return
        self.saved_at = time.time()
        self.prune()
        with self.lock:
            todo = list(self.dirty)
            self.dirty.clear()
            now = int(self.now() * 1000)
            docs = {s: {"upto": now, "m": {str(k): {e: [round(v[0], 2), round(v[1], 2)] for e, v in r.items()} for k, r in self.m.get(s, {}).items()}}
                    for s in todo}
            for s in todo:
                self.upto[s] = now
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            for s, doc in docs.items():
                p = self.dir / f"{s}.json"
                tmp = p.with_suffix(".tmp")
                tmp.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
                os.replace(tmp, p)
        except OSError:
            with self.lock:
                self.dirty.update(todo)

    def load(self, symbols) -> int:
        if self.dir is None:
            return 0
        n = 0
        cut = self.now() * 1000 - self.keep
        for s in symbols:
            s = s.upper()
            try:
                doc = json.loads((self.dir / f"{s}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            m, first = {}, {}
            for k, r in (doc.get("m") or {}).items():
                try:
                    mn = int(k)
                except ValueError:
                    continue
                if mn < cut or not isinstance(r, dict):
                    continue
                row = {}
                for e, v in r.items():
                    if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
                        row[e] = [float(v[0]), float(v[1])]
                        if e not in first or mn < first[e]:
                            first[e] = mn
                if row:
                    m[mn] = row
            with self.lock:
                self.m[s], self.first[s] = m, first
                if isinstance(doc.get("upto"), int):
                    self.upto[s] = doc["upto"]
                self.rev[s] = self.rev.get(s, 0) + 1
            n += len(m)
        return n


def read_jsonl(path: Path, cut_ms: float) -> list:
    """Liquidations notées une par une par data/live.py (une par ligne), à partir de cut_ms."""
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and isinstance(e.get("t"), (int, float)) and e["t"] >= cut_ms:
                    out.append(e)
    except OSError:
        pass
    return out
