"""Service de marche : relie les donnees, les moteurs (niveaux, poches, confluences, probabilites) et
fabrique l'etat JSON envoye a l'interface et aux alertes."""
import base64
import hashlib
import json
import math
import threading
import time
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path

from config import Config
from data.store import DataStore, H1, M5, DAY, OI_DAYS
from engine.atr import INTERVAL_MS, resample, rma_atr
from engine import bias as bias_engine
from engine import dominance as dominance_engine
from engine import macro as macro_engine
from engine import signals as signals_engine
from engine import sigtest
from engine import synth as synth_engine
from engine import vpx, vwapx
from engine.confluence import Level, find_zones
from engine.liquidity import LiqEngine
from engine.periods import AnchoredVWAP, KINDS, NakedPocs, PeriodTracker
from engine.stats import atr_series, reach_prob, reach_table, reaction_stats, round_step, sweep_outcomes

TFS = ("5m", "15m", "1h", "4h", "1d")
NAMES = {"D": "d", "W": "w", "M": "m", "Y": "y"}
PREV_HL = {"D": ("PDH", "PDL"), "W": ("PWH", "PWL"), "M": ("PMH", "PML"), "Y": ("PYH", "PYL")}
BASELINE = "Hasard (témoin)"
SWEEP_FAMILY = "Poches balayées (OI)"
HOUR_MS = 3_600_000
AUTO_NOTE = {tf: list(v) for tf, v in vpx.AUTO_BY_TF.items()}


def family_of(lv: Level):
    """Famille statistique d'un niveau (None si non mesuree dans l'historique)."""
    n, k = lv.name, lv.kind
    if k == "vwap":
        return "VWAP" if n[0] in "dwm" else None
    if k == "band":
        return "Bandes VWAP 2σ" if n[0] in "dwm" else None
    if k == "open":
        return "Opens" if n[0] in "dwm" else None
    if k == "hl":
        return {"PD": "Haut/bas veille", "PW": "Haut/bas semaine préc.", "PM": "Haut/bas mois préc."}.get(n[:2])
    if k == "vp" and n.startswith("p") and n[1] in "dwm":
        return "POC précédent" if n.endswith("POC") else "VAH/VAL précédent" if n[-3:] in ("VAH", "VAL") else None
    if k == "npoc":
        return "POC nus"
    if k == "round":
        return "Nombres ronds"
    if k == "liq":
        return SWEEP_FAMILY
    return None


def pct(a, b):
    return (a / b - 1.0) * 100.0 if a is not None and b else None


class Market:
    def __init__(self, source, symbol: str, cfg: Config):
        self.symbol, self.cfg, self.source = symbol, cfg, source
        self.store = DataStore(source, symbol, cfg.anchor_ms, cfg.history_years,
                               cfg.data_dir if getattr(source, 'name', '') == 'binance' else None)
        self.trackers = {k: PeriodTracker(k) for k in KINDS}
        self.avwap = AnchoredVWAP(cfg.anchor_ms)
        self.naked = {"D": NakedPocs(30), "W": NakedPocs(12)}
        self.liq = LiqEngine()
        self._fed_h1 = -1
        self._fed_m5 = -1
        self.ready = False
        self.feed = None             # flux temps reel (prix exact, vraies liquidations), optionnel
        self.stats = None            # probabilites mesurees (calculees en tache de fond)
        self.reach = None
        self.stats_at = 0.0
        self.vp_cfg = {"specs": [{"kind": "auto"}], "anchors": []}      # volume profiles choisis + ancrages VWAP (partages)
        self._vp_cache: dict = {}
        self._ser_cache: dict = {}
        self.bias = None             # biais statistique valide hors echantillon (calcule en tache de fond)
        self.bias_fund: list = []
        self._atr_cache = (0, [])
        self.sigval = None            # rejeu historique des idees (structure seule), calcule en tache de fond
        self._avs: dict[int, AnchoredVWAP] = {}      # VWAP ancrees supplementaires (dates choisies + extremes automatiques)
        self._sw_cache = (None, [])

    def update(self) -> None:
        self.store.refresh()
        now = self.source.now_ms()
        for k in self.store.h1:
            if k.t > self._fed_h1 and k.t + H1 <= now:       # bougies FERMEES uniquement, dans l'ordre
                prev = {kd: self.trackers[kd].prev for kd in ("D", "W")}
                for tr in self.trackers.values():
                    tr.feed(k)
                self.avwap.feed(k)
                for av in self._avs.values():
                    av.feed(k)
                for kd, nk in self.naked.items():
                    p = self.trackers[kd].prev
                    if p is not prev[kd] and p:
                        nk.on_rollover(p["vp"]["poc"] if p["vp"] else None, k.t)
                    nk.feed(k)
                self._fed_h1 = k.t
        for k in self.store.m5:
            if k.t > self._fed_m5 and k.t + M5 <= now:
                self.liq.step(self.store.oi.get(k.t), k.h, k.l, k.c, k.v, k.tb if k.tb > 0 else None, k.t + M5)
                self._fed_m5 = k.t
        self.ready = bool(self.store.h1)
        self.store.refresh_context()

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
        lp = self.feed.last_price(self.symbol) if self.feed else None
        if lp:
            return lp[0]                      # dernier prix echange (flux temps reel) plutot que la cloture 5 min
        s = self.store
        return s.m5[-1].c if s.m5 else s.h1[-1].c

    def h1_atrs(self):
        h1 = self.store.closed_h1()
        if self._atr_cache[0] != len(h1):
            self._atr_cache = (len(h1), atr_series(h1))
        return h1, self._atr_cache[1]

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
            if kind != "Y" and s["vwap"] is not None and s["sd"]:
                add(f"{p}VWAP+2σ", s["vwap"] + 2 * s["sd"], f"{p}VWAP", "band")
                add(f"{p}VWAP-2σ", s["vwap"] - 2 * s["sd"], f"{p}VWAP", "band")
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
        now = self.source.now_ms()
        for kd, nk in self.naked.items():
            unit, span = ("J", DAY) if kd == "D" else ("S", 7 * DAY)
            for x in nk.active():
                if abs(x["poc"] / self.price() - 1.0) > 0.15:      # trop loin pour compter
                    continue
                age = max(2, math.ceil((now - x["t_end"]) / span) + 1)
                add(f"nPOC {unit}-{age}", x["poc"], "nPOC", "npoc")
        a = self.avwap.snapshot(forming)
        add(f"AVWAP {self.cfg.anchor_date}", a["vwap"], "aVWAP", "avwap", sd=a["sd"], anchor=self.cfg.anchor_ms)
        keep = set()
        for lab, ms in self.anchors():
            if ms == self.cfg.anchor_ms:
                continue
            keep.add(ms)
            av = self._avs.get(ms)
            if av is None:
                av = self._avs[ms] = AnchoredVWAP(ms)
                for k in self.store.h1:
                    if k.t <= self._fed_h1:
                        av.feed(k)
            sn = av.snapshot(forming)
            add(lab, sn["vwap"], f"aVWAP:{ms}", "avwap", sd=sn["sd"], anchor=ms)
        for ms in [m for m in self._avs if m not in keep]:
            del self._avs[ms]
        return out

    # ---------- contexte (OI, prix, CVD, funding, base, ratios, Coinbase) ----------
    def _oi_at(self, t):
        s = self.store
        q = bisect_right(s.oi_t, t) - 1
        return s.oi_v[q] if q >= 0 else None

    def _price_at(self, t):
        m5 = self.store.m5
        lo, hi = 0, len(m5)
        while lo < hi:
            mid = (lo + hi) // 2
            if m5[mid].t <= t:
                lo = mid + 1
            else:
                hi = mid
        return m5[lo - 1].c if lo > 0 else None

    def context(self) -> dict:
        s, now, price = self.store, self.source.now_ms(), self.price()
        oi_now = s.oi_v[-1] if s.oi_v else None
        t_last = s.oi_t[-1] if s.oi_t else now
        ctx = {"oi": {"now": oi_now}, "price": {}, "errors": dict(s.ctx["errors"])}
        for lab, dt in (("1h", H1), ("4h", 4 * H1), ("24h", DAY)):
            ctx["oi"]["d" + lab] = pct(oi_now, self._oi_at(t_last - dt)) if oi_now else None
            ctx["price"]["d" + lab] = pct(price, self._price_at(now - dt))
        dp, doi = ctx["price"]["d4h"], ctx["oi"]["d4h"]
        if dp is not None and doi is not None:
            up, dn = dp > 0.3, dp < -0.3
            oiu, oid = doi > 0.5, doi < -0.5
            if up and oiu:
                code, lab = "up_up", "Hausse alimentée par de nouvelles positions (acheteurs agressifs)"
            elif up and oid:
                code, lab = "up_down", "Hausse par rachat de shorts : moins solide"
            elif dn and oiu:
                code, lab = "down_up", "Baisse avec nouvelles positions (vendeurs agressifs)"
            elif dn and oid:
                code, lab = "down_down", "Baisse par fermeture / liquidation de longs (purge)"
            elif oiu:
                code, lab = "flat_up", "Prix stable, OI en hausse : des positions s'accumulent (risque de mouvement brusque)"
            elif oid:
                code, lab = "flat_down", "Prix stable, OI en baisse : désengagement"
            else:
                code, lab = "flat_flat", "Calme : prix et OI stables"
            ctx["regime"] = {"code": code, "label": lab}
        # CVD reel (volume acheteur agressif - vendeur) sur les bougies 5 min
        m5 = s.m5
        for lab, dt in (("4h", 4 * H1), ("24h", DAY)):
            sub = [k for k in m5[-int(dt / M5) - 1:] if k.t >= now - dt and k.v > 0]
            buy = sum(k.tb for k in sub)
            vol = sum(k.v for k in sub)
            ctx.setdefault("cvd", {})["d" + lab] = (2 * buy - vol) if vol else None
            ctx["cvd"]["buy" + lab] = buy / vol * 100.0 if vol else None
        cvd4, p4 = ctx["cvd"].get("d4h"), ctx["price"].get("d4h")
        if cvd4 is not None and p4 is not None:
            if p4 > 0.3 and cvd4 < 0:
                ctx["cvd"]["div"] = "baissière : le prix monte sans acheteurs agressifs"
            elif p4 < -0.3 and cvd4 > 0:
                ctx["cvd"]["div"] = "haussière : le prix baisse malgré des acheteurs agressifs (absorption)"
        pr = s.ctx["premium"]
        if pr:
            f = pr["funding"] * 100
            hist = [r for _, r in s.ctx["funding"]]
            avg = sum(hist) / len(hist) * 100 if hist else None
            lab = ("élevé : les longs paient cher (foule acheteuse)" if f > 0.03 else
                   "négatif : les shorts paient (foule vendeuse)" if f < -0.005 else "neutre")
            ctx["funding"] = {"now": f, "avg7d": avg, "label": lab, "next": pr["next_funding"]}
            ctx["basis"] = pct(pr["mark"], pr["index"])
        for key in ("ls_global", "ls_top"):
            ser = s.ctx[key]
            if ser:
                r_now = ser[-1][1]
                r_24 = next((r for t, r, _ in reversed(ser) if t <= ser[-1][0] - DAY), None)
                ctx.setdefault("ls", {})[key[3:]] = {"now": r_now, "d24h": (r_now - r_24) if r_24 else None,
                                                    "long": ser[-1][2]}
        if s.ctx["coinbase"] and s.ctx["spot"]:
            prem = pct(s.ctx["coinbase"], s.ctx["spot"])
            ctx["coinbase"] = {"premium": prem,
                               "label": ("demande US plus forte" if prem > 0.05 else
                                         "demande US plus faible" if prem < -0.05 else "neutre")}
        if self.feed:
            ctx["liqReal"] = self.feed.liq_summary(self.symbol)           # vraies liquidations vues par le terminal
        tl, ts = self.liq.totals()
        if tl + ts > 0:
            ctx["liq"] = {"long": tl / (tl + ts) * 100.0, "short": ts / (tl + ts) * 100.0,
                          "taker": self.liq.taker_steps / max(1, self.liq.steps) * 100.0}
        return ctx

    # ---------- probabilites ----------
    def _prob_for(self, side, dist_price, n_groups):
        st, tab = self.stats, self.reach
        if not st or not tab:
            return None
        h1, atrs = self.h1_atrs()
        a = atrs[-1] if atrs else None
        if not a:
            return None
        d = abs(dist_price) / a
        sd = {"above": "resistance", "below": "support"}.get(side)
        direction = "up" if side == "above" else "down"
        reach = {str(H): (1.0 if side == "in" else reach_prob(tab, d, direction, H)) for H in (4, 24, 72)}
        bucket = "3+" if n_groups >= 3 else str(max(1, n_groups))
        sc = st["score"].get(bucket, {}).get(sd or "all")
        base = st["family"].get(BASELINE, {}).get(sd or "all")
        return {"reach": reach, "distAtrH1": d, "bounce": sc, "base": base, "bucket": bucket, "side": sd}

    def sweeps(self):
        h1, atrs = self.h1_atrs()
        summ, res = sweep_outcomes(self.liq.events, h1, atrs, self.cfg.stats_horizon, self.cfg.stats_k)
        return {"stats": summ, "recent": list(reversed(res[-10:]))}

    # ---------- etat complet pour un timeframe ----------
    def state(self, tf: str) -> dict:
        cfg = self.cfg
        cs = self.chart_candles(tf)
        price = self.price()
        atr = rma_atr(cs[-300:], 14) or price * 0.005
        win = max(cfg.dist_atr * atr, cfg.min_dist_pct / 100.0 * price)
        liq = self.liq.pools(price, win, cfg.clust_pct, cfg.keep_pct, cfg.per_side, cfg.magnet_pct)
        levels = self.base_levels()
        step = round_step(price)
        for m in range(math.floor((price - win) / step), math.ceil((price + win) / step) + 1):
            v = m * step
            if v > 0 and abs(v - price) <= win:
                levels.append(Level(f"ROUND|{v:g}", f"Rond {v:,.0f}".replace(",", " ") if v >= 1000 else f"Rond {v:g}",
                                    float(v), "ROUND", "round"))
        vps = self.vp_profiles(tf)
        for pf in vps:                                           # volume profiles supplementaires = sources de confluence
            gp = f"xVP:{pf['id']}"
            for nm, val in (("POC", pf["poc"]), ("VAH", pf["vah"]), ("VAL", pf["val"])) + tuple(("HVN", h) for h in pf["hvn"][:1]):
                if val and abs(val - price) <= win * 1.5:
                    levels.append(Level(f"{gp}|{nm}", f"{pf['label']} {nm}", float(val), gp, "xvp", {"vp": pf["id"]}))
        for i, p in enumerate(liq["pools"]):
            pr = self._prob_for("above" if p["price"] > price else "below", p["price"] - price, 1)
            p["reach"] = pr["reach"] if pr else None
            nm = f"Liq {'longs' if p['side'] == 'long' else 'shorts'}"
            levels.append(Level(f"LIQ|{p['side']}{i}", nm, p["price"], "LIQ", "liq", {"pool": p}))
        tol = max(cfg.conf_atr * atr, cfg.conf_min_pct / 100.0 * price)
        sweeps = self.sweeps()
        zones = []
        for k, z in enumerate(find_zones(levels, tol)):
            inside = z["lo"] <= price <= z["hi"]
            edge = 0.0 if inside else (z["lo"] - price if z["lo"] > price else z["hi"] - price)
            has_mag = any(m.kind == "liq" and m.extra["pool"]["magnet"] for m in z["members"])
            side = "in" if inside else ("above" if z["mid"] > price else "below")
            zones.append({
                "id": f"z{k}", "mid": z["mid"], "lo": z["lo"], "hi": z["hi"], "side": side,
                "distPct": edge / price * 100.0, "distAtr": abs(edge) / atr, "groups": z["groups"],
                "score": len(z["groups"]) + (1 if has_mag else 0), "hasMagnet": has_mag,
                "members": [m.id for m in z["members"]],
                "prob": self._prob_for(side, edge, len(z["groups"])),
            })
        in_zone = {mid: z["id"] for z in zones for mid in z["members"]}
        fam_stats = self.stats["family"] if self.stats else {}
        lv_out = []
        for lv in levels:
            fam = family_of(lv)
            sd = "support" if lv.price < price else "resistance"
            if fam == SWEEP_FAMILY:
                fst = sweeps["stats"]
            else:
                fst = fam_stats.get(fam, {}).get(sd) if fam else None
            lv_out.append({"id": lv.id, "name": lv.name, "price": lv.price, "group": lv.group, "kind": lv.kind,
                           "distPct": (lv.price / price - 1.0) * 100.0, "distAtr": abs(lv.price - price) / atr,
                           "inWindow": abs(lv.price - price) <= win, "zone": in_zone.get(lv.id),
                           "pool": lv.extra.get("pool"), "sd": lv.extra.get("sd"), "family": fam, "famStat": fst,
                           "anchor": lv.extra.get("anchor"), "vpid": lv.extra.get("vp")})
        # importance : sources distinctes, aimant, type de niveau meilleur que le hasard, proximite
        base = fam_stats.get(BASELINE, {}).get("all") if fam_stats else None
        lvd = {l["id"]: l for l in lv_out}
        for z in zones:
            edge = 0
            for i in z["members"]:
                f = (lvd.get(i) or {}).get("famStat")
                if f and f.get("n", 0) >= 30 and base and base.get("n"):
                    edge += 1 if f["lo"] > base["hi"] else -1 if f["hi"] < base["lo"] else 0
            z["edge"] = max(-2, min(2, edge))
            z["imp"] = round(z["score"] * 2 + (1.5 if z["hasMagnet"] else 0) + 0.7 * z["edge"] - 0.35 * min(z["distAtr"], 12)
                             - (2.0 if z["score"] < 3 else 0.0), 2)
        essential = []
        for sd in ("above", "below"):
            cand = sorted([z for z in zones if z["side"] == sd], key=lambda z: -z["imp"])
            good = [z for z in cand if z["score"] >= 3][:2] or [z for z in cand if z["score"] >= 2][:1]
            essential += [z["id"] for z in good]
        essential += [z["id"] for z in zones if z["side"] == "in" and z["score"] >= 2]
        ess_set = set(essential)
        above = sorted([z for z in zones if z["side"] == "above"], key=lambda z: z["lo"])
        below = sorted([z for z in zones if z["side"] == "below"], key=lambda z: -z["hi"])
        above = [z for k, z in enumerate(above) if k < 3 or z["id"] in ess_set]         # les zones essentielles sont toujours listees
        below = [z for k, z in enumerate(below) if k < 3 or z["id"] in ess_set]
        inside = [z for z in zones if z["side"] == "in"]
        t = self.store
        return {
            "symbol": self.symbol, "tf": tf, "source": self.source.name, "now": self.source.now_ms(),
            "price": price, "atr": atr, "atrPct": atr / price * 100.0, "window": win, "tol": tol,
            "candles": [[k.t // 1000, k.o, k.h, k.l, k.c, k.v] for k in cs[-400:]],
            "levels": lv_out, "zones": zones,
            "ladder": {"above": [z["id"] for z in reversed(above)], "inside": [z["id"] for z in inside],
                       "below": [z["id"] for z in below], "essential": essential},
            "liquidity": {"pools": liq["pools"], "total": liq["total"], "sumLong": liq["sum_long"],
                          "sumShort": liq["sum_short"], "steps": self.liq.steps, "oiPoints": len(t.oi)},
            "sweeps": sweeps, "context": self.context(),
            "vp": [{k: pf[k] for k in ("id", "label", "kind", "start", "end", "poc", "vah", "val", "hvn", "bars")} for pf in vps],
            "stats": self.stats_summary(),
        }

    # ---------- volume profiles choisis et series VWAP ----------
    def vp_profiles(self, tf: str):
        now = self.source.now_ms()
        wins = vpx.resolve(self.vp_cfg["specs"], tf, now)
        h1, m5 = self.store.closed_h1(), self.store.m5
        out = []
        for w in wins:
            use_m5 = bool(m5) and (w["end"] - w["start"]) <= 5 * DAY and w["start"] >= m5[0].t
            key = (w["id"], w["start"], w["end"], len(h1), len(m5) // 12 if use_m5 else 0)
            if key not in self._vp_cache:
                if len(self._vp_cache) > 120:
                    self._vp_cache.clear()
                self._vp_cache[key] = vpx.build(m5 if use_m5 else h1, w["start"], w["end"])
            res = self._vp_cache[key]
            if res:
                out.append({**w, **res})
        return out

    def swing_anchors(self):
        h1 = self.store.h1
        key = (len(h1), self.source.now_ms() // DAY)
        if self._sw_cache[0] != key:
            self._sw_cache = (key, vwapx.swing_anchors(self.store.closed_h1(), self.source.now_ms()))
        return self._sw_cache[1]

    def anchors(self):
        now = self.source.now_ms()
        seen, out = set(), []
        for lab, ms in [(f"AVWAP {self.cfg.anchor_date}", self.cfg.anchor_ms)] + \
                [(f"AVWAP {d}", int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)) for d in self.vp_cfg["anchors"]] + \
                vwapx.auto_anchors(now) + self.swing_anchors():
            if ms not in seen and ms < now:
                seen.add(ms)
                out.append((lab, ms))
        return out

    def vwap_series(self, tf: str):
        cs = self.chart_candles(tf)[-400:]
        if not cs:
            return {"ready": False}
        h1 = self.store.h1
        anchors = self.anchors()
        key = (tf, len(h1), cs[-1].t, tuple(anchors), int(time.time() // 10))
        if key in self._ser_cache:
            return self._ser_cache[key]
        t0 = min([a for _, a in anchors] + [vwapx._start_of("Y", cs[0].t)])
        sub = [k for k in h1 if k.t >= t0 - HOUR_MS]
        res = vwapx.series(sub, [k.t for k in cs], INTERVAL_MS[tf], anchors)
        res.update(ready=True, symbol=self.symbol, tf=tf, times=[k.t // 1000 for k in cs])
        if len(self._ser_cache) > 6:
            self._ser_cache.clear()
        self._ser_cache[key] = res
        return res

    def heat(self, hours: float | None = None) -> dict:
        """Carte de chaleur des poches de liquidation estimees (une colonne par heure, bandes de 0,15 %)."""
        now, price = self.source.now_ms(), self.price()
        since = now - int((hours or OI_DAYS * 24) * H1)
        sub = [k for k in self.store.m5 if k.t >= since] or self.store.m5[-12:]
        p_lo = max(min(k.l for k in sub) * 0.985, price * 0.6)
        p_hi = min(max(k.h for k in sub) * 1.015, price * 1.4)
        h = self.liq.heat(p_lo, p_hi, since, now)
        if not h:
            return {"ready": False}
        n, m, b0 = h["n"], h["m"], h["b0"]
        vals = sorted(v for _, a, b in h["cols"] for d in (a, b) for bb, v in d.items() if 0 <= bb - b0 < m)
        if not vals:
            return {"ready": False}
        ref = vals[min(len(vals) - 1, int(len(vals) * 0.985))] or vals[-1]
        out = []
        for side in (1, 2):
            buf = bytearray(n * m)
            for ci, col in enumerate(h["cols"]):
                for bb, v in col[side].items():
                    j = bb - b0
                    if 0 <= j < m:
                        r = v / ref
                        if r >= 0.05:                              # seules les poches notables s'allument
                            buf[j * n + ci] = min(255, int(255 * min(1.0, r) ** 0.85))
            out.append(base64.b64encode(bytes(buf)).decode("ascii"))
        evs = [{"t": e["t"], "side": e["side"], "price": e["price"], "frac": e["frac"]}
               for e in self.liq.events if e["t"] >= since]
        return {"ready": True, "symbol": self.symbol, "t0": h["t0"], "dt": h["dt"], "n": n, "m": m, "b0": b0,
                "step": h["step"], "ref": ref, "long": out[0], "short": out[1], "price": price, "now": now,
                "sweeps": evs}

    def stats_summary(self):
        if not self.stats:
            return {"ready": False}
        st = self.stats
        return {"ready": True, "meta": st["meta"], "family": st["family"], "score": st["score"], "flow": st["flow"],
                "computedAt": self.stats_at, "k": self.cfg.stats_k, "horizon": self.cfg.stats_horizon}


class Service:
    """Un Market par symbole, rafraichis en tache de fond ; get_state() est protege par un verrou."""

    def __init__(self, source, cfg: Config):
        self.cfg, self.source = cfg, source
        self.markets = {s: Market(source, s, cfg) for s in cfg.symbols}
        self.lock = threading.Lock()
        self.errors: dict[str, str] = {}
        self.last_update = 0.0
        self.listeners = []            # fonctions appelees apres chaque rafraichissement : f(service)
        self._stats_running: set[str] = set()
        self.feed = None
        self.ext = None                # donnees externes : calendrier, actifs de reference, dominance (V3)
        self._ext_running = False
        self.vp_state = {"specs": [{"kind": "auto"}], "anchors": []}
        self._an_cache: dict = {}
        self._an_state: dict = {}
        self._sig_cache: dict = {}
        self._fp_cache: dict = {}
        self._plan_cache: dict = {}
        self.load_vp()

    def attach_ext(self, hub) -> None:
        self.ext = hub

    # ---------- volume profiles choisis (sauvegardes sur le disque) ----------
    @property
    def vp_file(self) -> Path:
        return Path(self.cfg.data_dir) / "vps.json"

    def load_vp(self) -> None:
        try:
            d = json.loads(self.vp_file.read_text(encoding="utf-8"))
            cfg = {"specs": vpx.normalize_specs(d.get("specs")), "anchors": vpx.normalize_anchors(d.get("anchors"))}
        except Exception:
            cfg = {"specs": [{"kind": "auto"}], "anchors": []}
        self._apply_vp(cfg)

    def _apply_vp(self, cfg) -> None:
        for m in self.markets.values():
            m.vp_cfg = cfg
            m._vp_cache.clear()
            m._ser_cache.clear()
        self.vp_state = cfg
        self._an_cache.clear()

    def set_vp(self, specs, anchors) -> dict:
        cfg = {"specs": vpx.normalize_specs(specs), "anchors": vpx.normalize_anchors(anchors)}
        try:
            self.vp_file.parent.mkdir(parents=True, exist_ok=True)
            self.vp_file.write_text(json.dumps(cfg), encoding="utf-8")
        except OSError:
            pass
        with self.lock:
            self._apply_vp(cfg)
        return cfg

    def get_vp(self, symbol: str, tf: str) -> dict:
        m = self.markets.get(symbol)
        if m is None:
            raise KeyError(f"symbole inconnu : {symbol}")
        if tf not in TFS:
            raise KeyError(f"timeframe inconnu : {tf}")
        if not m.ready:
            return {"ready": False}
        with self.lock:
            profs = m.vp_profiles(tf)
        return {"ready": True, "symbol": symbol, "tf": tf, "specs": self.vp_state["specs"], "anchors": self.vp_state["anchors"],
                "auto": AUTO_NOTE, "profiles": profs}

    def get_series(self, symbol: str, tf: str) -> dict:
        m = self.markets.get(symbol)
        if m is None:
            raise KeyError(f"symbole inconnu : {symbol}")
        if tf not in TFS:
            raise KeyError(f"timeframe inconnu : {tf}")
        if not m.ready:
            return {"ready": False}
        with self.lock:
            return m.vwap_series(tf)

    def schedule_external(self, wait: bool = False) -> None:
        if not self.ext or self._ext_running:
            return
        self._ext_running = True

        def run():
            try:
                self.ext.refresh()
            except Exception as e:
                self.errors["externe"] = f"{type(e).__name__}: {e}"
            finally:
                self._ext_running = False
        if wait:
            run()
        else:
            threading.Thread(target=run, daemon=True).start()

    def attach_feed(self, feed) -> None:
        self.feed = feed
        for m in self.markets.values():
            m.feed = feed

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
        self.schedule_stats()
        self.schedule_external()

    # ---------- probabilites : recalcul en tache de fond (quelques secondes) ----------
    def compute_stats(self, sym: str) -> None:
        m = self.markets[sym]
        try:
            with self.lock:
                candles = list(m.store.closed_h1())
            atrs = atr_series(candles)
            st = reaction_stats(candles, horizon=self.cfg.stats_horizon, kb=self.cfg.stats_k, kx=self.cfg.stats_k,
                                atrs=atrs)
            tab = reach_table(candles, atrs)
            with self.lock:
                m.stats, m.reach, m.stats_at = st, tab, time.time()
            self.errors.pop(f"stats {sym}", None)
            try:                                                # biais statistique : un echec ici n'efface pas les probabilites
                try:
                    fund = self.source.funding_history(sym, candles[0].t, self.source.now_ms())
                except Exception:
                    fund = m.bias_fund
                path = Path(self.cfg.data_dir) / f"bias_{sym}.json" if getattr(self.source, "name", "") == "binance" else None
                b = bias_engine.load(path) if path else None
                fresh = b and b["since"] == candles[0].t and b["bars"] >= len(candles) - 72 \
                    and time.time() * 1000 - b["computedAt"] < 24 * 3_600_000
                if not fresh:                                    # le modele valide est recalcule au plus une fois par jour
                    b = bias_engine.analyse(candles, fund)
                    if path and b.get("ready"):
                        path.parent.mkdir(parents=True, exist_ok=True)
                        bias_engine.save(b, path)
                with self.lock:
                    m.bias, m.bias_fund = b, fund
                self.errors.pop(f"biais {sym}", None)
            except Exception as e:
                self.errors[f"biais {sym}"] = f"{type(e).__name__}: {e}"
            if self.cfg.signal_on:
                try:                                                # rejeu des idees de trade (structure seule) depuis le debut de l'historique
                    self.compute_sigval(sym, candles, atrs)
                    self.errors.pop(f"rejeu {sym}", None)
                except Exception as e:
                    self.errors[f"rejeu {sym}"] = f"{type(e).__name__}: {e}"
        except Exception as e:
            self.errors[f"stats {sym}"] = f"{type(e).__name__}: {e}"
        finally:
            self._stats_running.discard(sym)

    def compute_sigval(self, sym, candles, atrs) -> None:
        m = self.markets[sym]
        path = Path(self.cfg.data_dir) / f"signals_{sym}.json" if getattr(self.source, "name", "") == "binance" else None
        params = {"min_struct": self.cfg.signal_min_struct, "valid_hours": self.cfg.signal_valid_hours}
        v = None
        if path and path.exists():
            try:
                v = json.loads(path.read_text(encoding="utf-8"))
                if not (v.get("version") == sigtest.VERSION and v.get("ready") and v["bars"] >= len(candles) - 96
                        and time.time() * 1000 - v["computedAt"] < 24 * 3_600_000
                        and v["params"]["minStruct"] == params["min_struct"] and v["params"]["validHours"] == params["valid_hours"]
                        and v.get("cap") == self.cfg.signal_max_week):
                    v = None
            except (OSError, ValueError, KeyError):
                v = None
        if v is None:
            v = sigtest.replay(candles, atrs, params, max_week=self.cfg.signal_max_week)
            if path and v.get("ready"):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(v), encoding="utf-8")
        with self.lock:
            m.sigval = v

    def schedule_stats(self, wait: bool = False) -> None:
        for sym, m in self.markets.items():
            due = time.time() - m.stats_at > self.cfg.stats_refresh_hours * 3600
            if m.ready and due and sym not in self._stats_running and len(m.store.h1) > 24 * 40:
                self._stats_running.add(sym)
                if wait:
                    self.compute_stats(sym)
                else:
                    threading.Thread(target=self.compute_stats, args=(sym,), daemon=True).start()

    # ---------- analyse complete (biais, macro, dominance) ----------
    @staticmethod
    def _daily(candles):
        """Cloture quotidienne UTC a partir de bougies 1h : [(debut du jour en ms, derniere cloture du jour)]."""
        out = {}
        for k in candles:
            out[k.t // DAY * DAY] = k.c
        return sorted(out.items())

    def analysis(self, symbol: str) -> dict:
        m = self.markets.get(symbol)
        if m is None:
            raise KeyError(f"symbole inconnu : {symbol}")
        if not m.ready:
            return {"ready": False}
        hit = self._an_cache.get(symbol)
        if hit and time.time() - hit[0] < 4.0:
            return hit[1]
        now = self.source.now_ms()
        btc = self.markets.get("BTCUSDT")
        with self.lock:
            state = m.state("1h")
            self._an_state[symbol] = (time.time(), state)
            h1 = list(m.store.closed_h1())
            c5 = list(m.store.m5[-288 * 29:])
            c5b = list(btc.store.m5[-288 * 29:]) if btc else []
            h1b = list(btc.store.closed_h1()) if btc else []
            bias_res, fund = m.bias, m.bias_fund
        if bias_res and bias_res.get("ready") and h1 and bias_res["t"] != h1[-1].t:
            try:
                bias_res = bias_engine.repredict(bias_res, h1, fund)
                with self.lock:
                    m.bias = bias_res
            except Exception as e:
                self.errors[f"biais {symbol}"] = f"{type(e).__name__}: {e}"
        snap = self.ext.snapshot() if self.ext else {"calendar": {}, "cross5": {}, "crossD": {}, "fng": [], "cg": None,
                                                     "cg_hist": [], "alt": {}, "altD": {}, "errors": {}, "updated": {}}
        macro_state, new = macro_engine.analyse(now, snap, c5, c5b, symbol, self._daily(h1b))
        if new and self.ext:
            with self.ext.lock:
                for k, v in new.items():
                    if k in self.ext.calendar:
                        self.ext.calendar[k]["reaction"] = v
            self.ext.save()
        dom = dominance_engine.analyse(snap, (h1b or h1)[-24 * 400:], h1[-24 * 400:], symbol)
        bpub = bias_engine.public(bias_res)
        syn = synth_engine.synthesize(symbol, state["price"], bpub, macro_state, dom, state["context"], state["zones"],
                                      set(state["ladder"]["essential"]))
        c24 = next((k.c for k in reversed(h1) if k.t <= now - DAY), None)
        out = {"ready": True, "symbol": symbol, "t": now, "price": state["price"], "synth": syn, "bias": bpub,
               "context": state["context"], "atrPct": state["atrPct"], "change24": pct(state["price"], c24),
               "spark": [round(k.c, 6) for k in h1[-72:]],
               "macro": macro_state, "dom": dom, "sources": {"errors": snap["errors"], "updated": snap.get("updated", {})},
               "statsReady": bool(m.stats), "biasPending": bias_res is None}
        self._an_cache[symbol] = (time.time(), out)
        return out

    # ---------- idees de trade ----------
    def recent_m5(self, symbol: str, since_ms: int) -> list:
        """Bougies 5 min [(t, haut, bas, cloture)] depuis since_ms (suivi des idees ouvertes)."""
        m = self.markets.get(symbol)
        if m is None or not m.ready:
            return []
        out = []
        with self.lock:
            for k in reversed(m.store.m5):
                if k.t < since_ms - 300_000:
                    break
                out.append((k.t, k.h, k.l, k.c))
        return out[::-1]

    def _idea_probs(self, symbol, idea, zp, h1, atrs, tab):
        out = {}
        if tab and idea["entryType"] == "limite":
            d, direction = idea["distAtr"], "down" if idea["side"] == "long" else "up"
            out["fill"] = {"p24": reach_prob(tab, d, direction, 24), "p72": reach_prob(tab, d, direction, 72)}
        a, e = idea["atr"], idea["entry"]
        tp_a, sl_a = max(0.1, round(abs(idea["tp1"] - e) / a, 1)), max(0.1, round(abs(e - idea["stop"]) / a, 1))
        key = (symbol, idea["side"], tp_a, sl_a)
        hit = self._fp_cache.get(key)
        if hit is None or time.time() - hit[0] > 6 * 3600:
            a_pct = a / idea["price"] * 100.0
            res = bias_engine.plan(h1, atrs, idea["side"], tp_a * a_pct, sl_a * a_pct, 72, idea["price"], a)
            if len(self._fp_cache) > 200:
                self._fp_cache.clear()
            hit = self._fp_cache[key] = (time.time(), res)
        out["plan"] = hit[1]
        if zp:
            out["bounce"], out["baseBounce"] = zp.get("bounce"), zp.get("base")
        return out

    def signals(self, symbol: str) -> dict:
        """Idees de trade du moment pour ce symbole : candidates classees par score, rejets et validation historique."""
        m = self.markets.get(symbol)
        if m is None:
            raise KeyError(f"symbole inconnu : {symbol}")
        if not m.ready or not self.cfg.signal_on:
            return {"ready": False, "symbol": symbol, "on": self.cfg.signal_on}
        hit = self._sig_cache.get(symbol)
        if hit and time.time() - hit[0] < 4.0:
            return hit[1]
        cfg = self.cfg
        an = self.analysis(symbol)
        st = self._an_state.get(symbol)
        if not an.get("ready") or not st:
            return {"ready": False, "symbol": symbol, "on": True}
        state, now = st[1], self.source.now_ms()
        with self.lock:
            cs = list(m.store.closed_h1()[-14:])
            events = [dict(e) for e in m.liq.events[-30:]]
            h1, atrs = m.h1_atrs()
            tab, sigval = m.reach, m.sigval
        opts = {"min_struct": cfg.signal_min_struct, "valid_hours": cfg.signal_valid_hours, "leverage": cfg.signal_leverage}
        vw = {l["name"][0].upper(): l["price"] for l in state["levels"] if l["kind"] == "vwap" and l["name"] in ("wVWAP", "mVWAP", "yVWAP")}
        inp = {"symbol": symbol, "now": now, "price": state["price"], "atr": state["atr"], "levels": state["levels"], "zones": state["zones"],
               "pools": state["liquidity"]["pools"], "candles": cs, "sweeps": events, "opts": opts}
        raw, rejects = signals_engine.build_ideas(inp)
        ctx = {"price": state["price"], "vwap": vw, "flow": synth_engine.flow_score(state["context"]), "macro": an["macro"],
               "synth": an["synth"], "dom": an["dom"], "is_alt": symbol != "BTCUSDT", "now": now}
        zprob = {z["id"]: z.get("prob") for z in state["zones"]}
        ideas = []
        for idea in raw:
            sc = signals_engine.score_idea(idea, ctx, opts)
            sc.update(symbol=symbol, price=state["price"], atr=state["atr"], atrPct=state["atrPct"], validHours=cfg.signal_valid_hours,
                      sweepAgeH=(now - sc["sweep"]["t"]) / 3_600_000 if sc["sweep"] else None)
            sc["key"] = hashlib.md5((symbol + sc["side"] + "+".join(sorted(i["group"] for i in sc["st"]["items"]))).encode()).hexdigest()[:10]
            sc["grade"] = signals_engine.grade(sc["score"])
            probs = None
            if sc["score"] >= cfg.signal_min_score - 12:
                try:
                    probs = self._idea_probs(symbol, sc, zprob.get(sc["zoneId"]), h1, atrs, tab)
                except Exception as e:
                    self.errors[f"probas idee {symbol}"] = f"{type(e).__name__}: {e}"
            vt = sigtest.tier_for(sigval, sc["st"]["S"])
            valid = {"text": sigtest.validation_text(sigval, sc["st"]["S"]), "verdict": vt["verdict"] if vt else None} if vt else None
            if valid and not valid["text"]:
                valid = None
            sc["probs"], sc["valid"] = probs, valid
            sc["desc"] = signals_engine.describe(sc, probs, valid, cfg.signal_leverage, symbol)
            sc["eligible"] = sc["score"] >= cfg.signal_min_score and not sc["hold"]
            pub = {k: v for k, v in sc.items() if k not in ("tp1Ref", "tp2Ref")}
            pub["st"] = {**sc["st"], "items": [{k: it[k] for k in ("tf", "fam", "w", "text", "price", "name")} for it in sc["st"]["items"]]}
            ideas.append(pub)
        ideas.sort(key=lambda i: -i["score"])
        rej = [{"side": r["side"], "S": r["st"]["S"], "label": r["label"], "why": r["why"], "entry": r["entry"]}
               for r in sorted([r for r in rejects if r["distAtr"] <= 12], key=lambda r: -r["st"]["S"])[:4]]
        out = {"ready": True, "on": True, "symbol": symbol, "t": now, "price": state["price"], "atr": state["atr"], "ideas": ideas,
               "rejected": rej, "minScore": cfg.signal_min_score, "maxWeek": cfg.signal_max_week, "minStruct": cfg.signal_min_struct,
               "validation": sigval, "leverage": cfg.signal_leverage, "warm": m.stats is not None and sigval is not None}
        self._sig_cache[symbol] = (time.time(), out)
        return out

    def _idea_brief(self, sym):
        """Meilleure idee du moment (resume pour la vue d'ensemble)."""
        try:
            sg = self.signals(sym)
        except Exception:
            return None
        if not sg.get("ready") or not sg["ideas"]:
            return {"n": 0} if sg.get("ready") else None
        best = sg["ideas"][0]
        return {"n": sum(1 for i in sg["ideas"] if i["eligible"]), "side": best["side"], "score": best["score"], "entry": best["entry"],
                "stop": best["stop"], "tp1": best["tp1"], "eligible": best["eligible"], "hold": best["hold"][:1], "minScore": sg["minScore"]}

    def overview(self) -> dict:
        """Vue d'ensemble : une carte par paire (prix, biais, niveaux essentiels, contexte) + macro, dominance, sentiment."""
        syms, first = [], None
        for sym, m in self.markets.items():
            if not m.ready:
                syms.append({"symbol": sym, "ready": False})
                continue
            an = self.analysis(sym)
            first = first or an
            ctx = an["context"]
            sy = an["synth"]
            syms.append({"symbol": sym, "ready": True, "price": an["price"], "change24": an["change24"], "atrPct": an["atrPct"],
                         "spark": an["spark"], "synth": {k: sy[k] for k in ("direction", "label", "score", "confidence", "validated", "pUp24", "pUp4", "base24", "levels", "invalidation")},
                         "regime": (ctx.get("regime") or {}).get("label"), "funding": (ctx.get("funding") or {}).get("now"),
                         "oi24": (ctx.get("oi") or {}).get("d24h"), "buy24": (ctx.get("cvd") or {}).get("buy24h"),
                         "ls": ((ctx.get("ls") or {}).get("global") or {}).get("now"),
                         "history": {"bars": (an["bias"] or {}).get("bars"), "since": (an["bias"] or {}).get("since")},
                         "idea": self._idea_brief(sym)})
        g = {}
        if first:
            m = first["macro"]
            g = {"macro": {"score": m["score"], "label": m["label"], "risk": m["risk"], "lines": [l for l in m["lines"][:3]],
                           "upcoming": [{k: e[k] for k in ("id", "t", "label", "impact", "forecast", "previous")} for e in m["upcoming"][:4]]},
                 "fng": m.get("fng") and {k: m["fng"][k] for k in ("value", "label", "d7")},
                 "dom": {"btc_d": ((first["dom"].get("cg") or {}).get("btc_d")), "regime": (first["dom"].get("regime") or {}).get("name"),
                         "tone": (first["dom"].get("regime") or {}).get("tone")},
                 "sources": first["sources"]}
        return {"ready": True, "t": self.source.now_ms(), "symbols": syms, **g}

    def plan(self, symbol: str, side: str, tp_pct: float, sl_pct: float, lev: float, horizon: int) -> dict:
        m = self.markets.get(symbol)
        if m is None:
            raise KeyError(f"symbole inconnu : {symbol}")
        if not m.ready:
            return {"ready": False}
        if side not in ("long", "short") or not (0.05 <= tp_pct <= 50 and 0.05 <= sl_pct <= 50) or horizon not in (4, 24, 72):
            raise ValueError("parametres invalides (sens long/short, TP et SL entre 0,05 et 50 %, horizon 4, 24 ou 72 h)")
        lev = max(1.0, min(125.0, lev))
        with self.lock:
            h1, atrs = m.h1_atrs()
            h1, atrs = list(h1), list(atrs)
            price, tab = m.price(), m.reach
        key = (symbol, len(h1), side, round(tp_pct, 2), round(sl_pct, 2), horizon)
        res = self._plan_cache.get(key)
        if res is None:
            res = bias_engine.plan(h1, atrs, side, tp_pct, sl_pct, horizon, price, atrs[-1])
            if len(self._plan_cache) > 80:
                self._plan_cache.clear()
            self._plan_cache[key] = res
        mmr = 0.4
        liq_pct = max(0.0, 100.0 / lev - mmr)
        a_pct = atrs[-1] / price * 100.0
        d = liq_pct / a_pct if a_pct else None
        direction = "down" if side == "long" else "up"
        touch = {str(H): (reach_prob(tab, d, direction, H) if tab and d is not None else None) for H in (4, 24, 72)}
        liq_px = price * (1 - liq_pct / 100.0) if side == "long" else price * (1 + liq_pct / 100.0)
        return {"ready": True, "symbol": symbol, "side": side, "price": price, "atrPct": a_pct, "plan": res,
                "lev": lev, "liqPct": liq_pct, "liqPrice": liq_px, "liqAtr": d, "liqTouch": touch,
                "slBeyondLiq": sl_pct >= liq_pct, "entry": price,
                "tpPrice": price * (1 + tp_pct / 100) if side == "long" else price * (1 - tp_pct / 100),
                "slPrice": price * (1 - sl_pct / 100) if side == "long" else price * (1 + sl_pct / 100),
                "riskOnMargin": sl_pct * lev, "gainOnMargin": tp_pct * lev}

    def get_heat(self, symbol: str, hours: float | None = None) -> dict:
        m = self.markets.get(symbol)
        if m is None:
            raise KeyError(f"symbole inconnu : {symbol}")
        if not m.ready:
            return {"ready": False}
        with self.lock:
            return m.heat(hours)

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
