"""Flux temps reel Binance futures (WebSocket public) cote serveur :
- dernier prix echange de chaque paire (aggTrade) : prix exact pour les alertes et le secours du navigateur ;
- VRAIES liquidations (forceOrder) : journal en memoire + fichier, resume par fenetre.
Deux connexions separees : le prix ne depend pas du flux de liquidations (best effort)."""
import json
import threading
import time
from collections import deque
from pathlib import Path

from .ws import WSClient

HOUR = 3600.0


class LiveFeed:
    def __init__(self, base_ws: str, symbols, data_dir: str | None = None, ssl_context=None):
        self.base = base_ws.rstrip("/")
        self.symbols = [s.upper() for s in symbols]
        self.price: dict[str, tuple] = {}                       # sym -> (prix, t_transaction_ms, t_reception_s)
        self.liqs: dict[str, deque] = {s: deque(maxlen=5000) for s in self.symbols}
        self.dir = Path(data_dir) if data_dir else None
        self.lock = threading.Lock()
        self.clients: dict[str, WSClient] = {}
        self.ctx = ssl_context
        self.ticks = 0
        self.flow = None                                        # V15 : flux d'ordres (data/orderflow.py), recoit chaque transaction
        self._load_liqs()

    # --- messages ---
    def on_trade(self, text: str):
        m = json.loads(text)
        x = m.get("data", m)
        if x.get("e") != "aggTrade":
            return
        sym = x["s"].upper()
        now = time.time()
        self.price[sym] = (float(x["p"]), int(x["T"]), now)
        self.ticks += 1
        if self.flow is not None:
            self.flow.on_trade(sym, x, now)

    def on_liq(self, text: str):
        m = json.loads(text)
        x = m.get("data", m)
        if x.get("e") != "forceOrder":
            return
        o = x["o"]
        sym = o["s"].upper()
        qty = float(o.get("z") or o.get("q"))
        px = float(o.get("ap") or o.get("p"))
        ev = {"t": int(o.get("T") or x.get("E")), "side": "long" if o["S"] == "SELL" else "short",
              "price": px, "qty": qty, "usd": px * qty}
        self.add_liq(sym, ev, persist=True)

    def add_liq(self, sym: str, ev: dict, persist: bool = False):
        with self.lock:
            q = self.liqs.setdefault(sym, deque(maxlen=5000))
            if q and q[-1]["t"] == ev["t"] and q[-1]["price"] == ev["price"] and q[-1]["qty"] == ev["qty"]:
                return                                          # doublon
            q.append(ev)
        if persist and self.dir:
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                with open(self.dir / f"liqs_{sym}.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(ev) + "\n")
            except OSError:
                pass

    def _load_liqs(self):
        if not self.dir:
            return
        cut = (time.time() - 48 * HOUR) * 1000
        for s in self.symbols:
            try:
                for line in (self.dir / f"liqs_{s}.jsonl").read_text(encoding="utf-8").splitlines()[-5000:]:
                    ev = json.loads(line)
                    if ev["t"] >= cut:
                        self.liqs[s].append(ev)
            except (OSError, ValueError, KeyError):
                continue

    # --- lecture ---
    def last_price(self, sym: str, max_age: float = 15.0):
        """(prix, t_ms) si le flux est frais, sinon None."""
        p = self.price.get(sym.upper())
        if p and time.time() - p[2] <= max_age:
            return p[0], p[1]
        return None

    def recent_liqs(self, sym: str, since_ms: int = 0, limit: int = 600):
        with self.lock:
            return [e for e in self.liqs.get(sym.upper(), ()) if e["t"] >= since_ms][-limit:]

    def liq_summary(self, sym: str, now_ms: int | None = None):
        now_ms = now_ms or int(time.time() * 1000)
        out = {}
        evs = self.recent_liqs(sym, now_ms - 24 * 3_600_000, 5000)
        for lab, h in (("1h", 1), ("4h", 4), ("24h", 24)):
            sel = [e for e in evs if e["t"] >= now_ms - h * 3_600_000]
            out[lab] = {"long": sum(e["usd"] for e in sel if e["side"] == "long"),
                        "short": sum(e["usd"] for e in sel if e["side"] == "short"), "n": len(sel)}
        return out

    def status(self):
        return {k: {"connected": c.connected, "lastMsg": c.last_msg, "error": c.last_error, "connects": c.connects}
                for k, c in self.clients.items()}

    # --- vie ---
    def start(self):
        if self.clients:
            return
        trades = "/".join(f"{s.lower()}@aggTrade" for s in self.symbols)
        liqs = "/".join(f"{s.lower()}@forceOrder" for s in self.symbols)
        self.clients["trades"] = WSClient(f"{self.base}/stream?streams={trades}", self.on_trade, "trades", self.ctx)
        self.clients["liqs"] = WSClient(f"{self.base}/stream?streams={liqs}", self.on_liq, "liqs", self.ctx,
                                        idle_timeout=600.0)        # les liquidations peuvent etre rares
        for c in self.clients.values():
            c.start()

    def stop(self):
        for c in self.clients.values():
            c.stop()
        self.clients = {}
