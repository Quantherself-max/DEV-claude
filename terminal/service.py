"""Service de marche : relie les donnees, les moteurs (niveaux, poches, confluences) et fabrique l'etat
JSON envoye a l'interface et aux alertes."""
import threading
import time

from config import Config
from data.store import DataStore, H1, M5
from engine import vp  # noqa: F401  (documentation : les niveaux de profil viennent d'engine.vp)
from engine.atr import INTERVAL_MS, resample, rma_atr
from engine.confluence import Level, find_zones
from engine.liquidity import LiqEngine
from engine.periods import AnchoredVWAP, KINDS, PeriodTracker

TFS = ("5m", "15m", "1h", "4h", "1d")
NAMES = {"D": "d", "W": "w", "M": "m", "Y": "y"}
PREV_HL = {"D": ("PDH", "PDL"), "W": ("PWH", "PWL"), "M": ("PMH", "PML"), "Y": ("PYH", "PYL")}


class Market:
    def __init__(self, source, symbol: str, cfg: Config):
        self.symbol, self.cfg, self.source = symbol, cfg, source
        self.store = DataStore(source, symbol, cfg.anchor_ms)
        self.trackers = {k: PeriodTracker(k) for k in KINDS}
        self.avwap = AnchoredVWAP(cfg.anchor_ms)
        self.liq = LiqEngine()
        self._fed_h1 = -1
        self._fed_m5 = -1
        self.ready = False

    def update(self) -> None:
        self.store.refresh()
        now = self.source.now_ms()
        for k in self.store.h1:
            if k.t > self._fed_h1 and k.t + H1 <= now:       # bougies FERMEES uniquement, dans l'ordre
                for tr in self.trackers.values():
                    tr.feed(k)
                self.avwap.feed(k)
                self._fed_h1 = k.t
        for k in self.store.m5:
            if k.t > self._fed_m5 and k.t + M5 <= now:
                self.liq.step(self.store.oi.get(k.t), k.h, k.l, k.c, k.v)
                self._fed_m5 = k.t
        self.ready = bool(self.store.h1)

    # ---------- donnees pour un timeframe ----------
    def chart_candles(self, tf: str):
        s = self.store
        if tf == "5m":
            return s.m5
        if tf == "15m":
            return resample(s.m5, INTERVAL_MS["15m"])
        if tf == "1h":
            return s.h1
        return resample(s.h1, INTERVAL_MS[tf])

    def price(self) -> float:
        s = self.store
        return s.m5[-1].c if s.m5 else s.h1[-1].c

    # ---------- niveaux ----------
    def base_levels(self) -> list[Level]:
        forming = self.store.forming_h1()
        out: list[Level] = []
        seen: dict[str, int] = {}

        def add(name, price, group, kind, **extra):
            if price is None:
                return
            n = seen.get(group + name, 0)
            seen[group + name] = n + 1
            out.append(Level(f"{group}|{name}{'' if n == 0 else n}", name, float(price), group, kind, extra))

        for kind in KINDS:
            p = NAMES[kind]
            s = self.trackers[kind].snapshot(forming)
            add(f"{p}VWAP", s["vwap"], f"{p}VWAP", "vwap", sd=s["sd"])
            add(f"{p}Open", s["open"], f"{p}Open", "open")
            if s["vp"]:
                add(f"{p}POC", s["vp"]["poc"], f"{p}VP", "vp")
                for h in s["vp"]["hvn"]:
                    add(f"{p}HVN", h, f"{p}VP", "vp")
            prev = s["prev"]
            if prev:
                hi, lo = PREV_HL[kind]
                add(hi, prev["high"], f"{hi[:2]}HL", "hl")
                add(lo, prev["low"], f"{hi[:2]}HL", "hl")
                if prev["vp"]:
                    g = f"p{p}VP"
                    add(f"p{p}POC", prev["vp"]["poc"], g, "vp")
                    add(f"p{p}VAH", prev["vp"]["vah"], g, "vp")
                    add(f"p{p}VAL", prev["vp"]["val"], g, "vp")
                    for h in prev["vp"]["hvn"]:
                        add(f"p{p}HVN", h, g, "vp")
        a = self.avwap.snapshot(forming)
        add(f"AVWAP {self.cfg.anchor_date}", a["vwap"], "aVWAP", "avwap", sd=a["sd"])
        return out

    # ---------- etat complet pour un timeframe ----------
    def state(self, tf: str) -> dict:
        cfg = self.cfg
        cs = self.chart_candles(tf)
        price = self.price()
        atr = rma_atr(cs[-300:], 14) or price * 0.005
        win = max(cfg.dist_atr * atr, cfg.min_dist_pct / 100.0 * price)
        liq = self.liq.pools(price, win, cfg.clust_pct, cfg.keep_pct, cfg.per_side, cfg.magnet_pct)
        levels = self.base_levels()
        pool_levels = []
        for i, p in enumerate(liq["pools"]):
            nm = f"Liq {'longs' if p['side'] == 'long' else 'shorts'}"
            pool_levels.append(Level(f"LIQ|{p['side']}{i}", nm, p["price"], "LIQ", "liq", {"pool": p}))
        levels += pool_levels
        tol = max(cfg.conf_atr * atr, cfg.conf_min_pct / 100.0 * price)
        zones = []
        for k, z in enumerate(find_zones(levels, tol)):
            inside = z["lo"] <= price <= z["hi"]
            edge = 0.0 if inside else (z["lo"] - price if z["lo"] > price else z["hi"] - price)
            has_mag = any(m.kind == "liq" and m.extra["pool"]["magnet"] for m in z["members"])
            zones.append({
                "id": f"z{k}", "mid": z["mid"], "lo": z["lo"], "hi": z["hi"], "side": "in" if inside else ("above" if z["mid"] > price else "below"),
                "distPct": edge / price * 100.0, "distAtr": abs(edge) / atr, "groups": z["groups"],
                "score": len(z["groups"]) + (1 if has_mag else 0), "hasMagnet": has_mag,
                "members": [m.id for m in z["members"]],
            })
        in_zone = {mid: z["id"] for z in zones for mid in z["members"]}
        lv_out = []
        for lv in levels:
            lv_out.append({"id": lv.id, "name": lv.name, "price": lv.price, "group": lv.group, "kind": lv.kind,
                           "distPct": (lv.price / price - 1.0) * 100.0, "distAtr": abs(lv.price - price) / atr,
                           "inWindow": abs(lv.price - price) <= win, "zone": in_zone.get(lv.id),
                           "pool": lv.extra.get("pool"), "sd": lv.extra.get("sd")})
        above = sorted([z for z in zones if z["side"] == "above"], key=lambda z: z["lo"])[:3]
        below = sorted([z for z in zones if z["side"] == "below"], key=lambda z: -z["hi"])[:3]
        inside = [z for z in zones if z["side"] == "in"]
        t = self.store
        return {
            "symbol": self.symbol, "tf": tf, "source": self.source.name, "now": self.source.now_ms(),
            "price": price, "atr": atr, "atrPct": atr / price * 100.0, "window": win, "tol": tol,
            "candles": [[k.t // 1000, k.o, k.h, k.l, k.c, k.v] for k in cs[-400:]],
            "levels": lv_out, "zones": zones,
            "ladder": {"above": [z["id"] for z in reversed(above)], "inside": [z["id"] for z in inside],
                       "below": [z["id"] for z in below]},
            "liquidity": {"pools": liq["pools"], "total": liq["total"], "sumLong": liq["sum_long"],
                          "sumShort": liq["sum_short"], "steps": self.liq.steps, "oiPoints": len(t.oi)},
        }


class Service:
    """Un Market par symbole, rafraichis en tache de fond ; get_state() est protege par un verrou."""

    def __init__(self, source, cfg: Config):
        self.cfg, self.source = cfg, source
        self.markets = {s: Market(source, s, cfg) for s in cfg.symbols}
        self.lock = threading.Lock()
        self.errors: dict[str, str] = {}
        self.last_update = 0.0
        self.listeners = []            # fonctions appelees apres chaque rafraichissement : f(service)

    def refresh_all(self) -> None:
        for sym, m in self.markets.items():
            try:
                with self.lock:
                    m.update()
                self.errors.pop(sym, None)
            except Exception as e:                     # une panne reseau ne doit pas arreter le terminal
                self.errors[sym] = f"{type(e).__name__}: {e}"
        self.last_update = time.time()
        for f in self.listeners:
            try:
                f(self)
            except Exception as e:
                self.errors["listener"] = f"{type(e).__name__}: {e}"

    def get_state(self, symbol: str, tf: str) -> dict:
        m = self.markets.get(symbol)
        if m is None:
            raise KeyError(f"symbole inconnu : {symbol}")
        if tf not in TFS:
            raise KeyError(f"timeframe inconnu : {tf}")
        if not m.ready:
            return {"symbol": symbol, "tf": tf, "ready": False, "error": self.errors.get(symbol, "chargement des donnees...")}
        with self.lock:
            st = m.state(tf)
        st["ready"] = True
        st["error"] = self.errors.get(symbol)
        st["lastUpdate"] = self.last_update
        return st
