"""V44 : liquidations du BTC sur trois bourses et gros ordres exécutés sur cinq bourses, pour l'onglet GEX.

LIQUIDATIONS des perpétuels BTC (vraies liquidations, flux publics, sans clé) :
  - Binance : flux forceOrder (déjà lu par data/live.py, contrat BTCUSDT). Binance n'envoie AU PLUS qu'une liquidation par seconde
    (la dernière de la seconde) : pendant une cascade, son total est un MINIMUM ;
  - Bybit : flux allLiquidation (toutes les liquidations, depuis février 2025), contrat BTCUSDT ; « S » = sens de la POSITION
    liquidée (Buy : un long) ;
  - OKX : canal liquidation-orders (perpétuels BTC-USDT et BTC-USD), et l'adresse publique des dernières 24 heures au démarrage puis
    toutes les 3 heures : les trous de l'enregistrement (terminal éteint, coupure) sont comblés.
GROS ORDRES EXÉCUTÉS : les ordres au marché (ceux qui prennent la liquidité : un acheteur qui paie le prix des vendeurs affichés, ou
l'inverse), lus en direct sur Binance (perpétuel et comptant BTCUSDT), Coinbase (BTC-USD), Bitstamp (BTC/USD), OKX (perpétuels
BTC-USDT et BTC-USD, comptant BTC-USDT) et Bybit (perpétuel et comptant BTCUSDT). Un ordre qui traverse plusieurs prix arrive en
plusieurs morceaux : ils sont regroupés par numéro d'ordre (Coinbase, Bitstamp), sinon par sens et par milliseconde (Binance, OKX, Bybit :
deux ordres du même sens dans la même milliseconde comptent pour un). Montants en dollars.
Tout est rangé par tranches de 5 minutes et par taille (moins de 100 000 $, 100 000 à 500 000, 500 000 à 1 million, 1 à 5 millions,
5 millions et plus), gardé 48 heures et sauvegardé toutes les 2 minutes (data_local/cexflow/BTC.json, moins de 1 Mo). Rien n'est
enregistré quand le terminal est éteint : la part de chaque fenêtre réellement couverte est affichée.
SimCex fabrique les mêmes données en mode « données simulées »."""
from __future__ import annotations
import calendar
import json
import math
import os
import random
import threading
import time
from bisect import bisect_right
from collections import deque
from decimal import Decimal
from pathlib import Path

from .ws import WSClient, port_fallbacks

H = 3_600_000
BUCKET = 300_000                        # tranches de 5 minutes
KEEP_MS = 48 * H
WINDOWS = (6, 12, 24, 48)               # heures
CLASSES = (0.0, 100_000.0, 500_000.0, 1_000_000.0, 5_000_000.0)
NC = len(CLASSES)
BIG_MIN = 250_000.0                     # gros ordres gardés un par un (liste des derniers) à partir de ce montant
VENUES = (("binance_perp", "Binance", "perp"), ("binance_spot", "Binance", "spot"), ("coinbase", "Coinbase", "spot"),
          ("bitstamp", "Bitstamp", "spot"), ("okx_perp", "OKX", "perp"), ("okx_spot", "OKX", "spot"),
          ("bybit_perp", "Bybit", "perp"), ("bybit_spot", "Bybit", "spot"))
VENUE_IDS = tuple(v[0] for v in VENUES)
LIQ_EX = (("binance", "Binance"), ("bybit", "Bybit"), ("okx", "OKX"))
LIQ_IDS = tuple(e[0] for e in LIQ_EX)
OKX_CT = {"BTC-USDT-SWAP": ("coin", 0.01), "BTC-USD-SWAP": ("usd", 100.0)}    # taille d'un contrat OKX : 0,01 BTC ; 100 dollars
GAP_MS = 150_000                        # deux points de couverture séparés de plus de 2 min 30 s : trou
HOLD_S = 1.0                            # un ordre est clos s'il ne reçoit plus de morceau pendant 1 seconde
TRADE_SILENCE_S = 180.0                 # un flux de transactions muet depuis 3 minutes ne compte plus comme couvert

BYBIT_LINEAR = "wss://stream.bybit.com/v5/public/linear"
BYBIT_SPOT = "wss://stream.bybit.com/v5/public/spot"
OKX_WS = "wss://ws.okx.com:8443/ws/v5/public"
OKX_REST = "https://www.okx.com"
COINBASE_WS = "wss://ws-feed.exchange.coinbase.com"
BITSTAMP_WS = "wss://ws.bitstamp.net"


def cls_of(usd: float) -> int:
    """Classe de taille d'un ordre (0 : moins de 100 000 $ ... 4 : 5 millions et plus)."""
    return max(0, bisect_right(CLASSES, usd) - 1)


def iso_ms(s: str) -> int:
    """« 2026-11-12T21:49:19.027191Z » -> millisecondes UTC (sans dépendre de la version de Python)."""
    s = s.strip()
    main, frac = s[:19], ""
    if len(s) > 19 and s[19] == ".":
        k = 20
        while k < len(s) and s[k].isdigit():
            k += 1
        frac = s[20:k]
    return calendar.timegm(time.strptime(main, "%Y-%m-%dT%H:%M:%S")) * 1000 + int((frac + "000")[:3])


def okx_liq_events(item: dict) -> list:
    """Un élément du canal liquidation-orders (ou de l'adresse publique) -> [(t, 'long'/'short', dollars, prix)] pour les perpétuels BTC."""
    ct = OKX_CT.get(item.get("instId") or "")
    if ct is None:
        return []
    out = []
    for d in item.get("details") or ():
        try:
            px, sz, t = float(d.get("bkPx") or 0), float(d.get("sz") or 0), int(d.get("ts") or d.get("time"))
        except (TypeError, ValueError):
            continue
        if px <= 0 or sz <= 0:
            continue
        usd = sz * ct[1] * px if ct[0] == "coin" else sz * ct[1]
        ps = d.get("posSide")
        side = ps if ps in ("long", "short") else ("long" if d.get("side") == "sell" else "short")
        out.append((t, side, usd, px))
    return out


def _merge(iv: list) -> list:
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1] + GAP_MS:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


class CexFlow:
    """Le registre : tranches de 5 minutes, listes des gros ordres et des grosses liquidations, couverture de chaque flux."""

    def __init__(self, path: str | None = None, now=time.time, keep_ms: int = KEEP_MS):
        self.path = Path(path) if path else None
        self.now, self.keep = now, keep_ms
        self.lock = threading.RLock()
        self.liq: dict = {}          # tranche (ms) -> {bourse: [longs $, shorts $, nombre de longs, nombre de shorts]}
        self.ords: dict = {}         # tranche -> {lieu: [achats $, ventes $, nb d'achats, nb de ventes] pour chaque classe, à plat}
        self.big = deque(maxlen=3000)        # derniers gros ordres : [t, lieu, sens (+1 achat, -1 vente), dollars, prix moyen, morceaux]
        self.otop: dict = {}         # tranche -> les 3 plus gros ordres de la tranche (même forme)
        self.ltop: dict = {}         # tranche -> les 3 plus grosses liquidations : [t, bourse, 'long'/'short', dollars, prix]
        self.cover: dict = {}        # source -> [[début, fin], ...] (ms) : moments où le flux était lu
        self.pending: dict = {}      # flux -> [clé, t, sens, dollars, pièces, morceaux, heure locale de réception, lieu]
        self.seen: dict = {}         # source -> heure locale du dernier message reconnu
        self.msgs: dict = {}         # source -> messages reconnus depuis le démarrage
        self.dirty = False
        self.loaded = 0

    def now_ms(self) -> int:
        return int(self.now() * 1000)

    # --- entrées ---
    def fill(self, venue: str, t_ms: int, side: int, qty: float, px: float, key=None, stream: str | None = None) -> None:
        """Un morceau d'ordre au marché : side +1 = acheteur au marché, -1 = vendeur. Les morceaux de même clé sont additionnés."""
        if not (qty > 0 and px > 0) or side not in (1, -1):
            return
        k = key if key is not None else (t_ms, side)
        sk = stream or venue
        wall = self.now()
        with self.lock:
            p = self.pending.get(sk)
            if p is not None and p[0] == k:
                p[3] += qty * px
                p[4] += qty
                p[5] += 1
                p[6] = wall
            else:
                if p is not None:
                    self._close(p)
                self.pending[sk] = [k, int(t_ms), side, qty * px, qty, 1, wall, venue]
            self.seen[venue] = wall
            self.msgs[venue] = self.msgs.get(venue, 0) + 1

    def _close(self, p) -> None:
        _, t, side, usd, qty, n, _, venue = p
        row = self.ords.setdefault(t - t % BUCKET, {}).setdefault(venue, [0.0] * (4 * NC))
        c = cls_of(usd) * 4
        if side > 0:
            row[c] += usd
            row[c + 2] += 1
        else:
            row[c + 1] += usd
            row[c + 3] += 1
        self.record_big(t, venue, side, usd, usd / qty if qty else 0.0, n)
        self.dirty = True

    @staticmethod
    def _top(d: dict, t: int, item: list, k: int = 3) -> None:
        lst = d.setdefault(t - t % BUCKET, [])
        if len(lst) < k:
            lst.append(item)
        else:
            j = min(range(k), key=lambda i: lst[i][3])
            if item[3] > lst[j][3]:
                lst[j] = item

    def record_big(self, t: int, venue: str, side: int, usd: float, px: float, n: int = 1) -> None:
        item = [int(t), venue, side, round(usd), round(px, 2), n]
        if usd >= BIG_MIN:
            self.big.append(item)
        self._top(self.otop, int(t), item)

    def flush(self, hold: float = HOLD_S) -> None:
        """Ferme les ordres qui ne reçoivent plus de morceau."""
        wall = self.now()
        with self.lock:
            for sk, p in list(self.pending.items()):
                if wall - p[6] >= hold:
                    self._close(p)
                    del self.pending[sk]

    def liquidation(self, ex: str, t_ms: int, side: str, usd: float, px: float) -> None:
        if not usd > 0 or side not in ("long", "short"):
            return
        with self.lock:
            row = self.liq.setdefault(int(t_ms) - int(t_ms) % BUCKET, {}).setdefault(ex, [0.0, 0.0, 0, 0])
            i = 0 if side == "long" else 1
            row[i] += usd
            row[i + 2] += 1
            self._top(self.ltop, int(t_ms), [int(t_ms), ex, side, round(usd), px])
            src = "liq:" + ex
            self.seen[src] = self.now()
            self.msgs[src] = self.msgs.get(src, 0) + 1
            self.dirty = True

    # --- couverture ---
    def mark(self, src: str, t_ms: int | None = None) -> None:
        """Le flux « src » est lu à cet instant."""
        t = int(t_ms if t_ms is not None else self.now_ms())
        with self.lock:
            iv = self.cover.setdefault(src, [])
            if iv and iv[-1][0] <= t and t - iv[-1][1] <= GAP_MS:
                iv[-1][1] = max(iv[-1][1], t)
            elif not iv or t > iv[-1][1]:
                iv.append([t, t])
            else:
                self.cover[src] = _merge(iv + [[t, t]])

    def add_cover(self, src: str, a: int, b: int) -> None:
        with self.lock:
            self.cover[src] = _merge(self.cover.get(src, []) + [[int(a), int(b)]])
            self.dirty = True

    def in_cover(self, src: str, t: int) -> bool:
        with self.lock:
            return any(a <= t <= b for a, b in self.cover.get(src, ()))

    def covered(self, src: str, a: int, b: int) -> float:
        """Part de [a, b] couverte par le flux (0 à 1)."""
        if b <= a:
            return 0.0
        with self.lock:
            s = sum(max(0, min(b, y) - max(a, x)) for x, y in self.cover.get(src, ()))
        return min(1.0, s / (b - a))

    def prune(self, now_ms: int | None = None) -> None:
        cut = (now_ms or self.now_ms()) - self.keep - BUCKET
        with self.lock:
            for d in (self.liq, self.ords, self.otop, self.ltop):
                for b in [b for b in d if b < cut]:
                    del d[b]
            while self.big and self.big[0][0] < cut:
                self.big.popleft()
            for src, iv in list(self.cover.items()):
                self.cover[src] = [[max(a, cut), b] for a, b in iv if b >= cut]

    # --- lecture ---
    def summary(self, now_ms: int | None = None, recent: int = 120) -> dict:
        now = int(now_ms or self.now_ms())
        self.flush()
        with self.lock:
            liq_b = sorted(self.liq.items())
            ord_b = sorted(self.ords.items())
            big = list(self.big)
            otop = [x for lst in self.otop.values() for x in lst]
            ltop = [x for lst in self.ltop.values() for x in lst]
        nw = len(WINDOWS)
        starts = [now - h * H for h in WINDOWS]

        def slot(b):                                      # plus petite fenêtre qui contient la tranche (None : trop ancienne)
            if b > now:
                return None
            for i, a in enumerate(starts):
                if b + BUCKET / 2 >= a:
                    return i
            return None
        lq = [{e: [0.0, 0.0, 0, 0] for e in LIQ_IDS} for _ in range(nw)]
        for b, d in liq_b:
            i = slot(b)
            if i is not None:
                for e, r in d.items():
                    acc = lq[i].get(e)
                    if acc is not None:
                        for j in range(4):
                            acc[j] += r[j]
        od = [{v: [0.0] * (4 * NC) for v in VENUE_IDS} for _ in range(nw)]
        for b, d in ord_b:
            i = slot(b)
            if i is not None:
                for v, r in d.items():
                    acc = od[i].get(v)
                    if acc is not None:
                        for j, x in enumerate(r):
                            acc[j] += x
        for i in range(1, nw):                            # fenêtres emboîtées : 12 h = 6 h + les 6 heures d'avant, etc.
            for e in LIQ_IDS:
                lq[i][e] = [x + y for x, y in zip(lq[i][e], lq[i - 1][e])]
            for v in VENUE_IDS:
                od[i][v] = [x + y for x, y in zip(od[i][v], od[i - 1][v])]
        liq, ords = {}, {}
        for i, h in enumerate(WINDOWS):
            a = starts[i]
            rows = {e: {"long": round(r[0]), "short": round(r[1]), "nl": r[2], "ns": r[3], "cover": round(self.covered("liq:" + e, a, now), 3)}
                    for e, r in lq[i].items()}
            top = sorted((x for x in ltop if x[0] >= a), key=lambda x: -x[3])[:5]
            liq[str(h)] = {"ex": rows, "long": sum(r["long"] for r in rows.values()), "short": sum(r["short"] for r in rows.values()),
                           "nl": sum(r["nl"] for r in rows.values()), "ns": sum(r["ns"] for r in rows.values()),
                           "top": [{"t": x[0], "ex": x[1], "side": x[2], "usd": x[3], "px": x[4]} for x in top]}
            ords[str(h)] = {"venues": {v: {"c": [[round(r[4 * c]), round(r[4 * c + 1]), int(r[4 * c + 2]), int(r[4 * c + 3])] for c in range(NC)],
                                           "cover": round(self.covered(v, a, now), 3)} for v, r in od[i].items()},
                            "top": [{"t": x[0], "v": x[1], "s": x[2], "usd": x[3], "px": x[4]}
                                    for x in sorted((x for x in otop if x[0] >= a), key=lambda x: -x[3])[:5]]}
        rec = [{"t": x[0], "v": x[1], "s": x[2], "usd": x[3], "px": x[4], "n": x[5]} for x in big[-recent:][::-1]]
        rec1m = [{"t": x[0], "v": x[1], "s": x[2], "usd": x[3], "px": x[4], "n": x[5]} for x in [y for y in big if y[3] >= 1_000_000][-recent:][::-1]]
        return {"ok": True, "now": now, "windows": list(WINDOWS), "classes": list(CLASSES), "bigMin": BIG_MIN,
                "venues": [{"id": v, "name": n, "market": m} for v, n, m in VENUES], "liqEx": [{"id": e, "name": n} for e, n in LIQ_EX],
                "liq": liq, "orders": ords, "recent": rec, "recent1m": rec1m}

    # --- sauvegarde ---
    def save(self) -> bool:
        if not self.path or not self.dirty:
            return False
        with self.lock:
            st = {"v": 1, "saved": self.now_ms(),
                  "liq": {str(b): {e: [round(r[0]), round(r[1]), r[2], r[3]] for e, r in d.items()} for b, d in self.liq.items()},
                  "ords": {str(b): {v: [round(x) for x in r] for v, r in d.items()} for b, d in self.ords.items()},
                  "big": list(self.big), "otop": {str(b): v for b, v in self.otop.items()}, "ltop": {str(b): v for b, v in self.ltop.items()},
                  "cover": self.cover}
            self.dirty = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(st, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except OSError:
            self.dirty = True
            return False

    def load(self) -> int:
        if not self.path:
            return 0
        try:
            st = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        if not isinstance(st, dict) or st.get("v") != 1:
            return 0
        with self.lock:
            try:
                self.liq = {int(b): {e: [float(r[0]), float(r[1]), int(r[2]), int(r[3])] for e, r in d.items()} for b, d in st.get("liq", {}).items()}
                self.ords = {int(b): {v: [float(x) for x in r] for v, r in d.items() if len(r) == 4 * NC} for b, d in st.get("ords", {}).items()}
                self.big.extend(x for x in st.get("big", []) if len(x) == 6)
                self.otop = {int(b): [x for x in v if len(x) == 6] for b, v in (st.get("otop") or {}).items()}
                self.ltop = {int(b): [x for x in v if len(x) == 5] for b, v in (st.get("ltop") or {}).items()}
                self.cover = {s: [[int(a), int(b)] for a, b in iv] for s, iv in (st.get("cover") or {}).items()}
            except (TypeError, ValueError, AttributeError):
                self.liq, self.ords, self.cover, self.otop, self.ltop = {}, {}, {}, {}, {}
                self.big.clear()
                return 0
        self.prune()
        self.loaded = len(self.liq) + len(self.ords)
        return self.loaded


class CexFeeds:
    """Les connexions aux bourses (flux publics, sans clé). Binance arrive par LiveFeed (data/live.py), qui appelle on_binance_trade et
    on_binance_liq ; le comptant Binance a sa propre connexion seulement si LiveFeed ne le lit pas déjà."""

    def __init__(self, flow: CexFlow, ssl_context=None, http_json=None, binance_spot_ws: str | None = None, okx_ws: str = OKX_WS,
                 urls: dict | None = None):
        self.flow, self.ctx, self.http_json = flow, ssl_context, http_json
        self.binance_spot_ws = binance_spot_ws.rstrip("/") if binance_spot_ws else None
        self.urls = {"bybit_linear": BYBIT_LINEAR, "bybit_spot": BYBIT_SPOT, "okx": okx_ws, "coinbase": COINBASE_WS, "bitstamp": BITSTAMP_WS,
                     **(urls or {})}
        self.clients: dict = {}
        self.live = None                          # LiveFeed : Binance perpétuel, ses liquidations, et peut-être le comptant
        self.errors: dict = {}
        self.tap = None                                         # V45 : tap(bourse, heure ms, prix texte, quantité texte, côté, dollars texte) pour le moteur exact
        self.backfill = {"t": None, "added": 0, "error": None}
        self.stop_ev = threading.Event()
        self.thread = None

    # --- messages ---
    def on_binance_trade(self, x: dict, market: str) -> None:
        """Transaction agrégée Binance (aggTrade) : « m » vrai = l'acheteur était affiché, donc le vendeur est au marché."""
        self.flow.fill("binance_" + market, int(x["T"]), -1 if x.get("m") else 1, float(x["q"]), float(x["p"]))

    def on_binance_liq(self, ev: dict) -> None:
        self.flow.liquidation("binance", int(ev["t"]), ev["side"], float(ev["usd"]), float(ev["price"]))

    def on_binance_spot(self, text: str) -> None:
        m = json.loads(text)
        x = m.get("data", m)
        if x.get("e") == "aggTrade":
            self.on_binance_trade(x, "spot")
            if self.tap is not None:                               # V45 : la connexion comptant propre a ce module nourrit aussi le moteur exact
                self.tap("binance_spot", int(x["T"]), x["p"], x["q"], -1 if x.get("m") else 1, None)

    def on_bybit(self, text: str, market: str) -> None:
        m = json.loads(text)
        topic = m.get("topic") or ""
        if topic.startswith("publicTrade."):
            for d in m.get("data") or ():
                self.flow.fill("bybit_" + market, int(d["T"]), 1 if d.get("S") == "Buy" else -1, float(d["v"]), float(d["p"]))
                if self.tap is not None:
                    self.tap("bybit_" + market, int(d["T"]), d["p"], d["v"], 1 if d.get("S") == "Buy" else -1, None)
        elif topic.startswith("allLiquidation."):
            for d in m.get("data") or ():
                px = float(d["p"])
                self.flow.liquidation("bybit", int(d["T"]), "long" if d.get("S") == "Buy" else "short", float(d["v"]) * px, px)
        elif m.get("op") == "subscribe" and m.get("success") is False:
            self.errors["bybit_" + market] = str(m.get("ret_msg") or "abonnement refusé")

    def on_okx(self, text: str) -> None:
        if text == "pong":
            return
        m = json.loads(text)
        if m.get("event") == "error":
            self.errors["okx"] = f"{m.get('code')}: {m.get('msg')}"
            return
        ch = (m.get("arg") or {}).get("channel")
        if ch == "trades":
            for d in m.get("data") or ():
                inst, px, sz = d.get("instId") or "", float(d["px"]), float(d["sz"])
                ct = OKX_CT.get(inst)
                if ct is not None:
                    qty, venue = (sz * ct[1] if ct[0] == "coin" else sz * ct[1] / px), "okx_perp"
                elif inst == "BTC-USDT":
                    qty, venue = sz, "okx_spot"
                else:
                    continue
                self.flow.fill(venue, int(d["ts"]), 1 if d.get("side") == "buy" else -1, qty, px, stream="okx:" + inst)
                if self.tap is not None:                           # V45 : textes exacts ; contrat en dollars -> notionnel exact, pas de quantite
                    sd = 1 if d.get("side") == "buy" else -1
                    if ct is None:
                        self.tap(venue, int(d["ts"]), d["px"], d["sz"], sd, None)
                    elif ct[0] == "coin":
                        self.tap(venue, int(d["ts"]), d["px"], format(Decimal(d["sz"]) * Decimal(str(ct[1])), "f"), sd, None)
                    else:
                        self.tap(venue, int(d["ts"]), d["px"], None, sd, format(Decimal(d["sz"]) * Decimal(str(ct[1])), "f"))
        elif ch == "liquidation-orders":
            for item in m.get("data") or ():
                for t, side, usd, px in okx_liq_events(item):
                    self.flow.liquidation("okx", t, side, usd, px)

    def on_coinbase(self, text: str) -> None:
        """Canal « matches » : « side » est le sens de l'ordre AFFICHÉ ; un vendeur affiché touché = un acheteur au marché."""
        m = json.loads(text)
        ty = m.get("type")
        if ty == "error":
            self.errors["coinbase"] = str(m.get("message") or m.get("reason") or "erreur")
            return
        if ty != "match":                                      # « last_match » (la dernière avant l'abonnement) : déjà passée
            return
        self.flow.fill("coinbase", iso_ms(m["time"]), -1 if m.get("side") == "buy" else 1, float(m["size"]), float(m["price"]),
                       key=("o", m.get("taker_order_id")) if m.get("taker_order_id") else None)
        if self.tap is not None:
            self.tap("coinbase", iso_ms(m["time"]), m["price"], m["size"], -1 if m.get("side") == "buy" else 1, None)

    def on_bitstamp(self, text: str) -> None:
        """Canal live_trades : « type » 0 = acheteur au marché, 1 = vendeur ; l'ordre au marché est l'ordre d'achat ou de vente selon le cas."""
        m = json.loads(text)
        ev = m.get("event")
        if ev == "bts:request_reconnect":
            c = self.clients.get("bitstamp")
            if c:
                c.reconnect()
            return
        if ev != "trade":
            return
        d = m.get("data") or {}
        side = 1 if int(d.get("type", 0)) == 0 else -1
        oid = d.get("buy_order_id") if side > 0 else d.get("sell_order_id")
        t = int(d["microtimestamp"]) // 1000 if d.get("microtimestamp") else int(d["timestamp"]) * 1000
        self.flow.fill("bitstamp", t, side, float(d["amount"]), float(d["price"]), key=("o", oid) if oid else None)
        if self.tap is not None:                                   # Bitstamp envoie aussi le texte exact (amount_str, price_str)
            self.tap("bitstamp", t, d.get("price_str") or repr(float(d["price"])), d.get("amount_str") or repr(float(d["amount"])), side, None)

    # --- abonnements ---
    def _open_bybit(self, c, market):
        args = ["publicTrade.BTCUSDT"] + (["allLiquidation.BTCUSDT"] if market == "perp" else [])
        c.send_text(json.dumps({"op": "subscribe", "args": args}))

    def _open_okx(self, c):
        args = [{"channel": "trades", "instId": i} for i in ("BTC-USDT-SWAP", "BTC-USD-SWAP", "BTC-USDT")]
        c.send_text(json.dumps({"op": "subscribe", "args": args + [{"channel": "liquidation-orders", "instType": "SWAP"}]}))

    def _open_coinbase(self, c):
        c.send_text(json.dumps({"type": "subscribe", "product_ids": ["BTC-USD"], "channels": ["matches"]}))

    def _open_bitstamp(self, c):
        c.send_text(json.dumps({"event": "bts:subscribe", "data": {"channel": "live_trades_btcusd"}}))

    def own_spot(self) -> bool:
        lv = self.live
        return not (lv is not None and getattr(lv, "spot_base", None) and "BTCUSDT" in (getattr(lv, "spot_trades", None) or {}))

    def make_clients(self) -> dict:
        u, ctx = self.urls, self.ctx
        cl = {"bybit_linear": WSClient(u["bybit_linear"], lambda t: self.on_bybit(t, "perp"), "bybit-perp", ctx, idle_timeout=120.0,
                                       on_open=lambda c: self._open_bybit(c, "perp")),
              "bybit_spot": WSClient(u["bybit_spot"], lambda t: self.on_bybit(t, "spot"), "bybit-spot", ctx, idle_timeout=120.0,
                                     on_open=lambda c: self._open_bybit(c, "spot")),
              "okx": WSClient(u["okx"], self.on_okx, "okx-ordres", ctx, idle_timeout=45.0, on_open=self._open_okx,
                              fallbacks=port_fallbacks(u["okx"])),
              "coinbase": WSClient(u["coinbase"], self.on_coinbase, "coinbase", ctx, idle_timeout=120.0, on_open=self._open_coinbase),
              "bitstamp": WSClient(u["bitstamp"], self.on_bitstamp, "bitstamp", ctx, idle_timeout=300.0, on_open=self._open_bitstamp)}
        if self.binance_spot_ws and self.own_spot():
            cl["binance_spot"] = WSClient(f"{self.binance_spot_ws}/ws/btcusdt@aggTrade", self.on_binance_spot, "binance-comptant", ctx)
        return cl

    # --- couverture et état ---
    def _client_of(self, src: str):
        lv = getattr(self.live, "clients", None) or {}
        return {"binance_perp": lv.get("trades"), "liq:binance": lv.get("liqs"),
                "binance_spot": self.clients.get("binance_spot") or lv.get("spot"),
                "bybit_perp": self.clients.get("bybit_linear"), "liq:bybit": self.clients.get("bybit_linear"),
                "bybit_spot": self.clients.get("bybit_spot"), "okx_perp": self.clients.get("okx"), "okx_spot": self.clients.get("okx"),
                "liq:okx": self.clients.get("okx"), "coinbase": self.clients.get("coinbase"), "bitstamp": self.clients.get("bitstamp")}.get(src)

    def alive(self, src: str) -> bool:
        """Le flux est lu : connexion ouverte et, pour les transactions (jamais muettes longtemps sur le BTC), un message récent."""
        c = self._client_of(src)
        if c is None or not c.connected:
            return False
        if src.startswith("liq:"):
            return True
        return self.flow.now() - self.flow.seen.get(src, 0.0) <= TRADE_SILENCE_S

    def mark_all(self) -> None:
        for src in VENUE_IDS + tuple("liq:" + e for e in LIQ_IDS):
            if self.alive(src):
                self.flow.mark(src)

    def status(self) -> dict:
        out = {}
        for src in VENUE_IDS + tuple("liq:" + e for e in LIQ_IDS):
            c = self._client_of(src)
            key = {"liq:bybit": "bybit_perp", "okx_spot": "okx", "okx_perp": "okx", "liq:okx": "okx"}.get(src, src)
            out[src] = {"connected": bool(c and c.connected), "alive": self.alive(src), "msgs": self.flow.msgs.get(src, 0),
                        "error": (self.errors.get(key) or self.errors.get(src) or (c.last_error if c else "pas de connexion")) or ""}
        return {"sources": out, "backfill": dict(self.backfill), "simulated": False}

    # --- historique OKX (24 heures) ---
    def okx_backfill(self, pages: int = 40, pause: float = 0.2) -> int:
        """Comble les trous des liquidations OKX avec l'adresse publique (environ 24 heures). Ne double rien : un moment déjà couvert par
        l'enregistrement est ignoré ; les liquidations arrivées pendant la lecture sont celles du flux en direct."""
        if self.http_json is None:
            return 0
        f = self.flow
        if self.alive("liq:okx"):
            f.mark("liq:okx")
        t0 = f.now_ms()
        added, lows, cut = 0, [], []
        for fam in ("BTC-USDT", "BTC-USD"):
            after, low = None, None
            for _ in range(pages):
                url = f"{OKX_REST}/api/v5/public/liquidation-orders?instType=SWAP&instFamily={fam}&state=filled&limit=100" + (f"&after={after}" if after else "")
                d = self.http_json(url, timeout=15)
                evs = [e for item in (d.get("data") or []) for e in okx_liq_events(item)]
                if not evs:
                    break
                for t, side, usd, px in evs:
                    if t <= t0 and t >= t0 - f.keep and not f.in_cover("liq:okx", t):
                        f.liquidation("okx", t, side, usd, px)
                        added += 1
                low = min(e[0] for e in evs) if low is None else min(low, min(e[0] for e in evs))
                if after is not None and low >= after:
                    break
                after = low
                if low < t0 - f.keep:
                    break
                if pause:
                    self.stop_ev.wait(pause)
            else:                                                # arrêté par le nombre de pages : l'historique va plus loin
                if low is not None:
                    cut.append(low)
            if low is not None:
                lows.append(low)
        # début de la période reprise : la famille la plus profonde (l'adresse garde environ 24 heures), sauf si une lecture a été
        # arrêtée par le nombre de pages : alors pas avant l'endroit où elle s'est arrêtée
        oldest = max(cut) if cut else (min(lows) if lows else None)
        if oldest is not None:
            f.add_cover("liq:okx", max(oldest, t0 - f.keep), t0)
        self.backfill = {"t": t0, "added": added, "error": None}
        return added

    def import_binance(self, events: list) -> int:
        """Premier lancement de la V44 : les liquidations Binance déjà enregistrées par le terminal (48 dernières heures) sont reprises.
        Couverture estimée : 20 minutes autour de chaque liquidation (sur le BTC, il y en a presque toutes les minutes quand le flux tourne)."""
        if not events or self.flow.cover.get("liq:binance"):
            return 0
        iv = []
        for ev in events:
            self.on_binance_liq(ev)
            iv.append([int(ev["t"]) - 600_000, int(ev["t"]) + 600_000])
        now = self.flow.now_ms()
        for a, b in _merge(iv):
            self.flow.add_cover("liq:binance", a, min(b, now))
        return len(events)

    # --- vie ---
    def _loop(self):
        f = self.flow
        last_ping = last_mark = last_save = 0.0
        next_fill = time.time() + 15.0
        while not self.stop_ev.wait(1.0):
            now = time.time()
            try:
                f.flush()
                if now - last_ping >= 20:
                    last_ping = now
                    for k, c in self.clients.items():
                        if k.startswith("bybit"):
                            c.send_text('{"op":"ping"}')
                        elif k == "okx":
                            c.send_text("ping")
                        elif k == "bitstamp":
                            c.send_text('{"event":"bts:heartbeat"}')
                if now - last_mark >= 30:
                    last_mark = now
                    self.mark_all()
                    f.prune()
                if now - last_save >= 120:
                    last_save = now
                    f.save()
                if now >= next_fill:
                    next_fill = now + 3 * 3600
                    try:
                        self.okx_backfill()
                    except Exception as e:                       # sans internet ou adresse refusée : on réessaie dans 3 heures
                        self.backfill = {"t": f.now_ms(), "added": 0, "error": f"{type(e).__name__}: {e}"}
            except Exception as e:                               # le registre ne doit jamais s'arrêter
                self.errors["registre"] = f"{type(e).__name__}: {e}"
        f.flush(0)
        f.save()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        if not self.flow.loaded:
            self.flow.load()
        if self.live is not None:
            try:
                self.import_binance(self.live.recent_liqs("BTCUSDT", self.flow.now_ms() - self.flow.keep, 5000))
            except Exception:
                pass
        self.stop_ev.clear()
        self.clients = self.make_clients()
        for c in self.clients.values():
            c.start()
        self.thread = threading.Thread(target=self._loop, name="gros-ordres", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_ev.set()
        for c in self.clients.values():
            c.stop()
        if self.thread:
            self.thread.join(timeout=3)
        self.clients = {}


# ---------- version simulée ----------
SIM_VOL = {"binance_perp": 90e6, "binance_spot": 14e6, "coinbase": 10e6, "bitstamp": 1.2e6, "okx_perp": 22e6, "okx_spot": 3e6,
           "bybit_perp": 30e6, "bybit_spot": 4e6}                     # dollars échangés au marché par tranche de 5 minutes (ordre d'idée)
SIM_SHARE = (0.52, 0.24, 0.10, 0.10, 0.04)                             # part de chaque classe de taille
SIM_TYPICAL = (8_000.0, 200_000.0, 700_000.0, 2_000_000.0, 7_000_000.0)
SIM_LIQ = {"binance": 0.14e6, "bybit": 0.12e6, "okx": 0.06e6}         # liquidations par tranche de 5 minutes, marché calme


class SimCex:
    """Même interface que CexFeeds, données fabriquées (mode « données simulées ») : 48 heures d'historique au démarrage puis des ordres
    et des liquidations au fil du temps, plus nombreux quand le prix simulé bouge."""

    def __init__(self, flow: CexFlow, prices=None, last=None, seed: int = 44):
        self.flow = flow
        self.prices = prices or (lambda: None)          # -> fonction prix(t) sur l'historique simulé, ou None tant qu'il n'est pas prêt
        self.last = last or (lambda: None)              # -> dernier prix simulé
        self.rnd = random.Random(seed)
        self.stop_ev = threading.Event()
        self.thread = None
        self.filled = False
        self.live = None
        self._last = None

    def _poisson(self, lam: float) -> int:
        if lam <= 0:
            return 0
        if lam > 30:
            return max(0, round(self.rnd.gauss(lam, math.sqrt(lam))))
        k, p, lim = 0, 1.0, math.exp(-lam)
        while True:
            p *= self.rnd.random()
            if p <= lim:
                return k
            k += 1

    def backfill(self) -> bool:
        """48 heures fabriquées, tranche par tranche, à partir du prix simulé (une baisse liquide des longs, une hausse des shorts)."""
        f, r = self.flow, self.rnd
        at = self.prices()
        if at is None:
            return False
        now = f.now_ms()
        start = now - f.keep
        b = start - start % BUCKET
        prev = at(b - BUCKET)
        if prev is None:
            return False
        while b + BUCKET <= now:
            px = at(b + BUCKET) or prev
            ret = px / prev - 1 if prev else 0.0
            stress = 1.0 + min(12.0, abs(ret) / 0.0015) ** 1.4
            for v, vol in SIM_VOL.items():
                tilt = max(-0.35, min(0.35, ret / 0.004)) * (1.0 if v.endswith("perp") else 0.7)
                row = [0.0] * (4 * NC)
                for c in range(NC):
                    n = self._poisson(vol * SIM_SHARE[c] / SIM_TYPICAL[c] * stress ** 0.5)
                    buy = min(0.95, max(0.05, 0.5 + tilt + r.gauss(0, 0.12 if c >= 2 else 0.04)))
                    for _ in range(min(n, 60) if c else 0):
                        side, usd = (1 if r.random() < buy else -1), SIM_TYPICAL[c] * r.uniform(0.75, 1.6)
                        row[4 * c + (0 if side > 0 else 1)] += usd
                        row[4 * c + (2 if side > 0 else 3)] += 1
                        if usd >= BIG_MIN:
                            f.record_big(b + r.randrange(BUCKET), v, side, usd, px * (1 + r.gauss(0, 0.0005)), r.randint(1, 30))
                    if c == 0:                                    # les petits ordres : en bloc
                        usd = n * SIM_TYPICAL[0]
                        row[0], row[1] = usd * buy, usd * (1 - buy)
                        row[2], row[3] = round(n * buy), n - round(n * buy)
                f.ords.setdefault(b, {})[v] = row
            for e, base in SIM_LIQ.items():
                usd = base * stress * r.uniform(0.3, 1.7)
                longs = min(0.97, max(0.03, 0.5 - ret / 0.003 + r.gauss(0, 0.1)))
                row = [usd * longs, usd * (1 - longs), max(1, round(usd * longs / 9_000)), max(1, round(usd * (1 - longs) / 9_000))]
                f.liq.setdefault(b, {})[e] = row
                side = "long" if longs > 0.5 else "short"
                f._top(f.ltop, b, [b + r.randrange(BUCKET), e, side, round(r.uniform(0.02e6, 0.3e6) * stress ** 0.7), round(px, 1)])
            prev = px
            b += BUCKET
        f.big = deque(sorted(f.big, key=lambda x: x[0]), maxlen=f.big.maxlen)
        for src in VENUE_IDS + tuple("liq:" + e for e in LIQ_IDS):
            f.add_cover(src, start, now)
        self.filled, self._last = True, now
        return True

    def step(self) -> None:
        """Les ordres et liquidations fabriqués depuis le dernier appel."""
        f, r = self.flow, self.rnd
        now = f.now_ms()
        if not self.filled:
            if not self.backfill():
                return
        last = self._last or now
        dt = (now - last) / BUCKET
        if dt <= 0:
            return
        self._last = now
        px = self.last()
        if not px:
            return
        for v, vol in SIM_VOL.items():
            n = min(400, int(dt * 60 + r.random()))
            for i in range(n):
                usd = math.exp(r.gauss(9.3, 1.9)) * vol / 90e6 * 3
                side = 1 if r.random() < 0.5 else -1
                t = last + int((i + 1) * (now - last) / max(1, n))
                f.fill(v, t, side, usd / px, px * (1 + r.gauss(0, 0.0002)), key=("sim", v, t, i))
        for e, base in SIM_LIQ.items():
            if r.random() < min(1.0, dt * 20):
                f.liquidation(e, now, "long" if r.random() < 0.5 else "short", base / 20 * r.uniform(0.2, 3.0), px)
        for src in VENUE_IDS + tuple("liq:" + e for e in LIQ_IDS):
            f.mark(src, now)

    def _loop(self):
        while not self.stop_ev.wait(2.0):
            try:
                self.step()
                self.flow.flush()
                self.flow.prune()
            except Exception:
                pass

    def status(self) -> dict:
        src = {s: {"connected": True, "alive": True, "msgs": self.flow.msgs.get(s, 0), "error": ""} for s in VENUE_IDS + tuple("liq:" + e for e in LIQ_IDS)}
        return {"sources": src, "backfill": {"t": None, "added": 0, "error": None}, "simulated": True}

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_ev.clear()
        self.thread = threading.Thread(target=self._loop, name="gros-ordres-simules", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_ev.set()
        if self.thread:
            self.thread.join(timeout=3)
