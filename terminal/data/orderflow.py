"""Flux d'ordres en direct (V15), cote serveur : carnet d'ordres, nombre d'ordres par prix, ruban des transactions.

- Carnet Binance futures (profondeur reelle) : flux des differences a 100 ms (route /public de fstream) + photo REST de 1000 niveaux,
  synchronises selon la regle publiee par Binance (lastUpdateId de la photo, puis U / u / pu de chaque evenement) ; au moindre trou,
  nouvelle photo. Taille en pieces (SOL, BTC) par prix.
- Nombre d'ordres par prix : Binance ne publie pas le detail ordre par ordre (« L3 »). Le carnet OKX du meme perpetuel USDT donne, pour
  chaque prix, la taille ET le NOMBRE d'ordres ; continuite controlee par seqId et somme de controle (CRC32 des 25 premiers niveaux).
- Ruban (transactions agregees Binance, recues par LiveFeed) : vitesse (transactions par seconde), part acheteuse, gros ordres executes
  (au-dessus du 99,7e centile des 5 000 dernieres transactions et d'un plancher par paire), volume echange par prix depuis la derniere
  remise a zero, latence (heure de l'evenement chez Binance -> reception ici).
SimFlow fabrique les memes donnees en mode simule (prix fictifs) pour que l'ecran fonctionne hors ligne."""
import json
import math
import random
import threading
import time
import zlib
from bisect import insort
from collections import deque

from .ws import WSClient

MIN_BIG_USD = {"BTC": 250_000.0, "ETH": 100_000.0, "SOL": 50_000.0}
DEFAULT_MIN_BIG = 25_000.0
BIG_PCT = 0.997
OKX_DEPTH_CHECK = 25


def base_of(sym: str) -> str:
    return sym[:-4] if sym.upper().endswith("USDT") else sym


def okx_inst(sym: str) -> str:
    return f"{base_of(sym.upper())}-USDT-SWAP"


def okx_checksum(bids, asks) -> int:
    """bids / asks : [(prix_texte, taille_texte)] du meilleur au moins bon. Entier signe 32 bits comme celui d'OKX."""
    parts = []
    for i in range(OKX_DEPTH_CHECK):
        if i < len(bids):
            parts += [bids[i][0], bids[i][1]]
        if i < len(asks):
            parts += [asks[i][0], asks[i][1]]
    return _signed(zlib.crc32(":".join(parts).encode()))


def _signed(c: int) -> int:
    c &= 0xFFFFFFFF
    return c - (1 << 32) if c >= 1 << 31 else c


class BinanceBook:
    """Carnet local d'une paire. fetch() -> photo REST {"lastUpdateId", "bids", "asks"}. Appeler on_event(dict) pour chaque depthUpdate."""

    def __init__(self, sym: str, fetch, threaded: bool = True, now=time.time):
        self.sym, self.fetch, self.threaded, self.now = sym, fetch, threaded, now
        self.lock = threading.Lock()
        self.bids: dict = {}
        self.asks: dict = {}
        self.buffer: list = []
        self.lid = None                  # lastUpdateId de la photo
        self.last_u = None
        self.need_first = True
        self.synced = False
        self.loading = False
        self.resyncs = 0
        self.error = ""
        self.last_event = 0.0
        self.lat = deque(maxlen=200)

    def on_event(self, ev: dict, recv_s: float | None = None):
        recv_s = recv_s or self.now()
        self.last_event = recv_s
        if ev.get("E"):
            self.lat.append(recv_s * 1000 - float(ev["E"]))
        start = False
        with self.lock:
            if not self.synced:
                self.buffer.append(ev)
                if len(self.buffer) > 2000:
                    self.buffer = self.buffer[-2000:]
                if not self.loading:
                    self.loading = start = True
            else:
                if not self._apply_locked(ev):
                    self._reset_locked()
                    self.buffer = [ev]
                    self.loading = start = True
        if start:
            if self.threaded:
                threading.Thread(target=self._load, name=f"carnet-{self.sym}", daemon=True).start()
            else:
                self._load()

    def _reset_locked(self):
        self.synced, self.need_first, self.lid, self.last_u = False, True, None, None
        self.resyncs += 1

    def _apply_locked(self, ev) -> bool:
        """Applique un evenement synchronise. False = trou dans la sequence : il faut une nouvelle photo."""
        U, u = int(ev["U"]), int(ev["u"])
        if self.need_first:
            if u < self.lid:
                return True                                  # plus ancien que la photo : ignore
            if U > self.lid:
                return False                                 # la photo est trop vieille
            self.need_first = False
        elif int(ev.get("pu", -1)) != self.last_u:
            return False
        for side, book in (("b", self.bids), ("a", self.asks)):
            for p, q in ev.get(side, ()):
                pf, qf = float(p), float(q)
                if qf == 0.0:
                    book.pop(pf, None)
                else:
                    book[pf] = qf
        self.last_u = u
        return True

    def _load(self):
        try:
            snap = self.fetch(self.sym)
            with self.lock:
                self.bids = {float(p): float(q) for p, q in snap["bids"] if float(q) > 0}
                self.asks = {float(p): float(q) for p, q in snap["asks"] if float(q) > 0}
                self.lid, self.need_first, self.last_u = int(snap["lastUpdateId"]), True, None
                buf, self.buffer = self.buffer, []
                ok = True
                for ev in buf:
                    if not self._apply_locked(ev):
                        ok = False
                        break
                self.synced = ok
                self.error = "" if ok else "photo trop ancienne, nouvel essai"
                if not ok:
                    self.need_first, self.lid = True, None
        except Exception as e:                               # reseau, format : on reessaiera au prochain evenement
            with self.lock:
                self.error = f"{type(e).__name__}: {e}"
                self.synced = False
        finally:
            with self.lock:
                self.loading = False

    def levels(self):
        with self.lock:
            if not self.synced:
                return [], []
            return list(self.bids.items()), list(self.asks.items())

    def latency(self):
        return _median(self.lat)


class OkxBook:
    """Carnet OKX « books » d'un perpetuel : prix -> (taille, nombre d'ordres). bad = True quand il faut se reabonner."""

    def __init__(self, inst: str):
        self.inst = inst
        self.lock = threading.Lock()
        self.bids: dict = {}            # prix_texte -> (taille_texte, nb_ordres)
        self.asks: dict = {}
        self.seq = None
        self.synced = False
        self.bad = False
        self.check = True               # somme de controle verifiee (desactivee si elle ne correspond jamais : format change ?)
        self.mismatch = 0
        self.mismatch_fresh = 0
        self.last_event = 0.0
        self.resub_at = 0.0
        self.error = ""

    def on_data(self, action: str, d: dict, recv_s: float):
        with self.lock:
            self.last_event = recv_s
            if action == "snapshot":
                self.bids = {x[0]: (x[1], int(x[3]) if len(x) > 3 else 0) for x in d.get("bids", ())}
                self.asks = {x[0]: (x[1], int(x[3]) if len(x) > 3 else 0) for x in d.get("asks", ())}
                self.synced, self.bad = True, False
                fresh = True
            else:
                if not self.synced or (self.seq is not None and int(d.get("prevSeqId", -1)) != self.seq):
                    self.synced, self.bad, self.error = False, True, "trou dans la sequence"
                    return
                for side, book in (("bids", self.bids), ("asks", self.asks)):
                    for x in d.get(side, ()):
                        if float(x[1]) == 0.0:
                            book.pop(x[0], None)
                        else:
                            book[x[0]] = (x[1], int(x[3]) if len(x) > 3 else 0)
                fresh = False
            self.seq = int(d["seqId"]) if d.get("seqId") is not None else self.seq
            if self.check and d.get("checksum") is not None:
                b = sorted(self.bids.items(), key=lambda kv: -float(kv[0]))[:OKX_DEPTH_CHECK]
                a = sorted(self.asks.items(), key=lambda kv: float(kv[0]))[:OKX_DEPTH_CHECK]
                if okx_checksum([(p, v[0]) for p, v in b], [(p, v[0]) for p, v in a]) != int(d["checksum"]):
                    self.mismatch += 1
                    if fresh:
                        self.mismatch_fresh += 1
                    if self.mismatch_fresh >= 3:                  # meme une photo neuve ne correspond pas : on cesse de verifier
                        self.check, self.error = False, "somme de contrôle OKX non reconnue : vérification désactivée"
                    else:
                        self.synced, self.bad, self.error = False, True, "somme de contrôle différente"

    def levels(self):
        """[(prix, taille, nb_ordres)] de chaque cote."""
        with self.lock:
            if not self.synced:
                return [], []
            return ([(float(p), float(v[0]), v[1]) for p, v in self.bids.items()],
                    [(float(p), float(v[0]), v[1]) for p, v in self.asks.items()])


def _nice(raw: float) -> float:
    if raw <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if m * e >= raw * 0.999:
            return round(m * e, 12)
    return 10 * e


class AbsorbWatch:
    """Absorptions en direct (V21), au prix pres : sur les WINDOW dernieres secondes, beaucoup de volume agressif d'un seul cote a une meme
    tranche de prix (au moins deux fois plus que l'autre cote), sans que le prix passe au travers (jamais plus d'une tranche au-dela depuis
    le premier echange a ce prix). Ensuite : CONFIRMEE (le prix s'eloigne de 6 tranches dans le sens de l'absorption), CASSEE (il traverse
    de 2 tranches) ou TENUE (ni l'un ni l'autre en CONFIRM secondes). Une seule absorption signalee par episode a un prix. « Reapprovisionnee » : il s'est execute a ce prix au moins deux fois
    la taille encore affichee dans le carnet Binance : un gros ordre passif se recharge (souvent un ordre cache, « iceberg »).
    Seuil : 95e centile des plus gros volumes d'un cote par tranche (releve toutes les 5 s sur la derniere heure), avec un plancher en
    dollars par paire. Tranche : environ 0,02 % du prix. Rien n'est mesure sur l'historique (il faudrait chaque transaction et le carnet)."""
    WINDOW = 60.0
    CONFIRM = 300.0
    SAMPLE = 5.0
    MIN_SAMPLES = 60
    AWAY = 6                                             # confirmee : le prix s'eloigne de 6 tranches (environ 0,12 %)
    FLOOR = {"BTC": 1_500_000.0, "ETH": 600_000.0, "SOL": 300_000.0}
    DEFAULT_FLOOR = 150_000.0

    def __init__(self, sym: str, book_size=None):
        self.sym = sym
        self.floor = self.FLOOR.get(base_of(sym.upper()), self.DEFAULT_FLOOR)
        self.book_size = book_size                       # (bas, haut, "bid" | "ask") -> taille affichee, ou None
        self.step = None
        self.trades: deque = deque()                     # (t_s, tranche, quantite, cote)
        self.agg: dict = {}                              # tranche -> [achat, vente agressifs, debut vendeurs dominants, debut acheteurs dominants, deja signale (vendeurs, acheteurs)]
        self.kmin: deque = deque()                       # minimum / maximum glissants des tranches echangees : (t_s, tranche)
        self.kmax: deque = deque()
        self.samples: deque = deque(maxlen=720)
        self.thr = None
        self.next_sample = 0.0
        self.events: deque = deque(maxlen=400)
        self.open: dict = {}
        self.seq = 0

    def _since(self, dq, t0):
        """Minimum (ou maximum) des tranches echangees depuis t0 : premier element de la file monotone a partir de t0."""
        for t, k in dq:
            if t >= t0:
                return k
        return None

    def on_trade(self, t_s: float, price: float, qty: float, side: str):
        if self.step is None:
            self.step = _nice(price * 0.0002)
        k = math.floor(price / self.step + 1e-9)
        self.trades.append((t_s, k, qty, side))
        a = self.agg.get(k)
        if a is None:
            a = self.agg[k] = [0.0, 0.0, None, None, False, False]
        a[0 if side == "buy" else 1] += qty
        self._mark(a, t_s, price)
        while self.kmin and self.kmin[-1][1] >= k:
            self.kmin.pop()
        self.kmin.append((t_s, k))
        while self.kmax and self.kmax[-1][1] <= k:
            self.kmax.pop()
        self.kmax.append((t_s, k))
        cut = t_s - self.WINDOW
        while self.trades and self.trades[0][0] < cut:
            _t, k0, q0, s0 = self.trades.popleft()
            b = self.agg.get(k0)
            if b is not None:
                b[0 if s0 == "buy" else 1] -= q0
                if b[0] <= 1e-12 and b[1] <= 1e-12:
                    del self.agg[k0]
                else:
                    self._mark(b, t_s, price)
        while self.kmin and self.kmin[0][0] < cut:
            self.kmin.popleft()
        while self.kmax and self.kmax[0][0] < cut:
            self.kmax.popleft()
        if t_s >= self.next_sample:
            self.next_sample = t_s + self.SAMPLE
            if self.agg:
                self.samples.append(max(max(b[0], b[1]) for b in self.agg.values()) * price)
                if len(self.samples) >= self.MIN_SAMPLES:
                    srt = sorted(self.samples)
                    self.thr = max(self.floor, srt[int(0.95 * (len(srt) - 1))])
        self._resolve(k, t_s)
        self._check(k, t_s, price)

    def _mark(self, b, t_s, price):
        """Debut de la domination d'un cote a une tranche (au moins 30 % du seuil et deux fois l'autre cote) ; oublie sous 20 % ou 1,5 fois."""
        if self.thr is None:
            return
        for i, (mine, other) in ((2, (b[1], b[0])), (3, (b[0], b[1]))):
            usd = mine * price
            if b[i] is None:
                if usd >= 0.3 * self.thr and mine >= 2 * other:
                    b[i] = t_s
            elif usd < 0.2 * self.thr or mine < 1.5 * other:
                b[i], b[i + 2] = None, False                     # fin de l'episode : une nouvelle absorption pourra etre signalee ici

    def _resolve(self, k, t_s):
        for key, ev in list(self.open.items()):
            k0, side = key
            if side == "bull":
                st = "cassée" if k <= k0 - 2 else "confirmée" if k >= k0 + self.AWAY else None
            else:
                st = "cassée" if k >= k0 + 2 else "confirmée" if k <= k0 - self.AWAY else None
            if st is None and t_s - ev["t"] / 1000.0 > self.CONFIRM:
                st = "tenue"
            if st:
                ev["status"], ev["end"] = st, int(t_s * 1000)
                del self.open[key]
            else:
                b = self.agg.get(k0)
                if b:                                            # le volume absorbe continue de grossir tant que l'absorption dure
                    ev["buy"], ev["sell"] = max(ev["buy"], b[0]), max(ev["sell"], b[1])
                    ev["delta"] = ev["buy"] - ev["sell"]

    def _check(self, k, t_s, price):
        if self.thr is None:
            return
        b = self.agg.get(k)
        if not b:
            return
        buy, sell, t_bull, t_bear, done_bull, done_bear = b
        if t_bull is not None and not done_bull and sell * price >= self.thr and sell >= 2 * buy:
            lo = self._since(self.kmin, t_bull)                  # depuis que les vendeurs dominent ici, le prix n'est pas passe au travers
            if lo is not None and lo >= k - 1 and self._open(k, "bull", t_s, price, buy, sell):
                b[4] = True                                      # une seule absorption par episode a ce prix
        if t_bear is not None and not done_bear and buy * price >= self.thr and buy >= 2 * sell:
            hi = self._since(self.kmax, t_bear)
            if hi is not None and hi <= k + 1 and self._open(k, "bear", t_s, price, buy, sell):
                b[5] = True

    def _open(self, k, side, t_s, price, buy, sell):
        for kk in (k, k - 1, k + 1):                             # une seule absorption en cours par prix (et par tranche voisine)
            if (kk, side) in self.open:
                return False
        size = None
        if self.book_size:
            try:
                size = self.book_size(k * self.step, (k + 1) * self.step, "bid" if side == "bull" else "ask")
            except Exception:
                size = None
        done = sell if side == "bull" else buy
        self.seq += 1
        ev = {"id": self.seq, "t": int(t_s * 1000), "price": round(k * self.step, 10), "step": self.step, "side": side,
              "buy": buy, "sell": sell, "delta": buy - sell, "usd": round(done * price), "status": "en cours", "end": None,
              "shown": size, "refill": (bool(size) and done >= 2 * size) if size is not None else None}
        self.open[(k, side)] = ev
        self.events.append(ev)
        return True

    def recent(self, since_ms: int = 0, limit: int = 200):
        return [dict(e) for e in self.events if e["t"] >= since_ms][-limit:]


class Tape:
    """Ruban d'une paire (transactions agregees Binance)."""

    def __init__(self, sym: str, now=time.time, book_size=None):
        self.sym, self.now = sym, now
        self.absorb = AbsorbWatch(sym, book_size)
        self.lock = threading.Lock()
        self.recent: deque = deque()                     # (t_reception_s, cote) des 60 dernieres secondes
        self.notional: deque = deque(maxlen=5000)
        self.sorted_n: list = []
        self.n_seen = 0
        self.thr = MIN_BIG_USD.get(base_of(sym), DEFAULT_MIN_BIG)
        self.floor = self.thr
        self.big: deque = deque(maxlen=3000)
        self.foot: dict = {}                             # prix -> [achat agressif, vente agressive] depuis la remise a zero
        self.since = int(self.now() * 1000)
        self.lat = deque(maxlen=200)
        self.last = None

    def on_trade(self, price: float, qty: float, buyer_maker: bool, t_ms: int, e_ms: int | None = None, recv_s: float | None = None):
        recv_s = recv_s or self.now()
        side = "sell" if buyer_maker else "buy"             # acheteur « maker » = c'est le vendeur qui a frappe le carnet
        usd = price * qty
        with self.lock:
            self.last = (price, t_ms)
            self.recent.append((recv_s, side))
            while self.recent and self.recent[0][0] < recv_s - 60:
                self.recent.popleft()
            if e_ms:
                self.lat.append(recv_s * 1000 - e_ms)
            f = self.foot.setdefault(price, [0.0, 0.0])
            f[0 if side == "buy" else 1] += qty
            self.absorb.on_trade(t_ms / 1000.0, price, qty, side)
            self.notional.append(usd)
            self.n_seen += 1
            if self.n_seen % 250 == 0:
                srt = sorted(self.notional)
                q = srt[min(len(srt) - 1, int(BIG_PCT * len(srt)))]
                self.thr = max(self.floor if self.n_seen < 1000 else self.floor / 2, q)
            if usd >= self.thr:
                self.big.append({"t": int(t_ms), "price": price, "qty": qty, "usd": round(usd), "side": side})

    def speed(self, window: float = 5.0):
        now = self.now()
        with self.lock:
            sel = [s for t, s in self.recent if t >= now - window]
        n = len(sel)
        return {"perSec": round(n / window, 1), "buyShare": (sum(1 for s in sel if s == "buy") / n) if n else None, "n60": len(self.recent)}

    def reset(self):
        with self.lock:
            self.foot, self.since = {}, int(self.now() * 1000)

    def absorptions(self, since_ms: int = 0):
        with self.lock:
            return self.absorb.recent(since_ms)

    def latency(self):
        return _median(self.lat)


def _median(xs):
    if not xs:
        return None
    s = sorted(xs)
    return round(s[len(s) // 2])


def ladder_rows(step: float, center: float, rows: int, bids, asks, okx_bids=(), okx_asks=(), foot=None):
    """Regroupe le carnet par tranche de prix `step` autour de `center`. Ligne : [prix_bas, taille_achat, taille_vente, ordres_achat,
    ordres_vente, echange_achat, echange_vente], du plus haut prix au plus bas."""
    k0 = math.floor(center / step)
    half = rows // 2
    lo_k, hi_k = k0 - half, k0 + half
    acc = {k: [0.0, 0.0, 0, 0, 0.0, 0.0] for k in range(lo_k, hi_k + 1)}

    def put(price, idx, val):
        k = math.floor(price / step + 1e-9)
        r = acc.get(k)
        if r is not None:
            r[idx] += val

    for p, q in bids:
        put(p, 0, q)
    for p, q in asks:
        put(p, 1, q)
    for p, _sz, n in okx_bids:
        put(p, 2, n)
    for p, _sz, n in okx_asks:
        put(p, 3, n)
    for p, (b, s) in (foot or {}).items():
        put(p, 4, b)
        put(p, 5, s)
    return [[round(k * step, 10), *v] for k, v in sorted(acc.items(), reverse=True)]


class OrderFlow:
    """Coordonne les carnets et le ruban de toutes les paires. LiveFeed lui transmet les transactions (on_trade)."""

    def __init__(self, symbols, ws_public: str, okx_ws: str, fetch_snapshot, ssl_context=None, now=time.time, threaded: bool = True):
        self.symbols = [s.upper() for s in symbols]
        self.ws_public, self.okx_ws, self.ctx, self.now = ws_public.rstrip("/"), okx_ws, ssl_context, now
        self.books = {s: BinanceBook(s, fetch_snapshot, threaded, now) for s in self.symbols}
        self.okx = {okx_inst(s): OkxBook(okx_inst(s)) for s in self.symbols}
        self.tapes = {s: Tape(s, now, self._book_size(s)) for s in self.symbols}
        self.clients: dict = {}
        self._ping = 0.0
        self.okx_error = ""

    def _book_size(self, sym):
        """Taille affichee dans le carnet Binance entre deux prix, cote acheteur (bid) ou vendeur (ask) ; None si le carnet n'est pas synchronise."""
        def size(lo, hi, side):
            bk = self.books[sym]
            if not bk.synced:
                return None
            bids, asks = bk.levels()
            return sum(q for p, q in (bids if side == "bid" else asks) if lo <= p < hi)
        return size

    # --- messages ---
    def on_depth(self, text: str):
        m = json.loads(text)
        x = m.get("data", m)
        if x.get("e") != "depthUpdate":
            return
        b = self.books.get(x["s"].upper())
        if b:
            b.on_event(x, self.now())

    def on_okx(self, text: str):
        now = self.now()
        if now - self._ping > 20:                                 # OKX coupe une connexion muette : petit « ping » regulier
            self._ping = now
            c = self.clients.get("okx")
            if c:
                c.send_text("ping")
        if text == "pong":
            return
        m = json.loads(text)
        if m.get("event") == "error":
            self.okx_error = f"{m.get('code')}: {m.get('msg')}"
            return
        arg = m.get("arg") or {}
        bk = self.okx.get(arg.get("instId"))
        if not bk or arg.get("channel") != "books" or not m.get("data"):
            return
        bk.on_data(m.get("action", "update"), m["data"][0], now)
        if bk.bad and now - bk.resub_at >= 2.0:                      # pas plus d'un reabonnement toutes les 2 s par paire
            bk.resub_at = now
            self._resubscribe(bk.inst)

    def _subscribe_all(self, client):
        client.send_text(json.dumps({"op": "subscribe", "args": [{"channel": "books", "instId": i} for i in self.okx]}))

    def _resubscribe(self, inst):
        c = self.clients.get("okx")
        bk = self.okx[inst]
        bk.bad = False
        if c:
            arg = [{"channel": "books", "instId": inst}]
            c.send_text(json.dumps({"op": "unsubscribe", "args": arg}))
            c.send_text(json.dumps({"op": "subscribe", "args": arg}))

    def on_trade(self, sym: str, x: dict, recv_s: float | None = None):
        tp = self.tapes.get(sym.upper())
        if tp:
            tp.on_trade(float(x["p"]), float(x["q"]), bool(x.get("m")), int(x["T"]), int(x["E"]) if x.get("E") else None, recv_s)

    # --- lecture ---
    def ladder(self, sym: str, step: float, rows: int = 60, center: float | None = None, big_since: int = 0) -> dict:
        sym = sym.upper()
        bk, ok, tp = self.books[sym], self.okx[okx_inst(sym)], self.tapes[sym]
        bids, asks = bk.levels()
        obids, oasks = ok.levels()
        bb = max((p for p, _ in bids), default=None)
        ba = min((p for p, _ in asks), default=None)
        mid = center or ((bb + ba) / 2 if bb and ba else (tp.last[0] if tp.last else None))
        out = {"symbol": sym, "ready": mid is not None, "step": step, "mid": mid, "bestBid": bb, "bestAsk": ba, "since": tp.since,
               "book": {"source": "Binance", "synced": bk.synced, "error": bk.error, "resyncs": bk.resyncs},
               "orders": {"source": "OKX", "synced": ok.synced, "check": ok.check, "error": ok.error or self.okx_error},
               "tape": tp.speed(), "latency": {"trades": tp.latency(), "book": bk.latency()}, "threshold": round(tp.thr),
               "big": [b for b in list(tp.big) if b["t"] >= big_since][-500:], "absorb": tp.absorptions(big_since),
               "absorbThr": tp.absorb.thr}
        if mid is None or step <= 0:
            out["rows"] = []
            return out
        with tp.lock:
            foot = dict(tp.foot)
        out["rows"] = ladder_rows(step, mid, max(4, min(int(rows), 400)), bids, asks, obids, oasks, foot)
        return out

    def reset(self, sym: str):
        t = self.tapes.get(sym.upper())
        if t:
            t.reset()

    def status(self):
        return {k: {"connected": c.connected, "lastMsg": c.last_msg, "error": c.last_error, "connects": c.connects} for k, c in self.clients.items()}

    # --- vie ---
    def start(self):
        if self.clients:
            return
        streams = "/".join(f"{s.lower()}@depth@100ms" for s in self.symbols)
        self.clients["depth"] = WSClient(f"{self.ws_public}/stream?streams={streams}", self.on_depth, "carnet", self.ctx)
        self.clients["okx"] = WSClient(self.okx_ws, self.on_okx, "okx", self.ctx, idle_timeout=45.0, on_open=self._on_okx_open)
        for c in self.clients.values():
            c.start()

    def _on_okx_open(self, client):
        for bk in self.okx.values():
            bk.synced, bk.seq = False, None
        self._subscribe_all(client)

    def stop(self):
        for c in self.clients.values():
            c.stop()
        self.clients = {}


class SimFlow:
    """Meme interface qu'OrderFlow, donnees fabriquees autour du prix simule (mode « donnees simulees »)."""

    def __init__(self, symbols, price_of, now=time.time, seed: int = 3):
        self.symbols = [s.upper() for s in symbols]
        self.price_of, self.now = price_of, now
        self.rnd = random.Random(seed)
        self.tapes = {s: Tape(s, now) for s in self.symbols}
        self.lock = threading.Lock()
        self._last = {s: now() for s in self.symbols}
        self._episode = {s: (now() + 330.0, None) for s in self.symbols}  # V21 : episodes d'absorption fabriques (debut, (fin, cote, prix)) ; le premier apres la mise en route du seuil

    def _pump(self, sym):
        """Ajoute les transactions fictives ecoulees depuis le dernier appel (environ 20 par seconde)."""
        now = self.now()
        last = self._last.get(sym, now - 1)
        n = min(400, int((now - last) * 20))
        if n <= 0:
            return
        self._last[sym] = now
        px = self.price_of(sym)
        if not px:
            return
        tp = self.tapes[sym]
        nxt, ep = self._episode[sym]
        for i in range(n):
            t = last + (i + 1) * (now - last) / n
            if ep is None and t >= nxt:                     # de temps en temps, un gros ordre passif absorbe les agressifs pendant 25 s
                side = "bull" if self.rnd.random() < 0.5 else "bear"
                ep = (t + 25.0, side, round(px * (1 - 0.0003 if side == "bull" else 1 + 0.0003), 2))
            if ep is not None and t > ep[0]:
                nxt, ep = t + self.rnd.uniform(600, 1500), None
            p = round(px * (1 + self.rnd.gauss(0, 0.0004)), 2)
            usd = math.exp(self.rnd.gauss(8.0, 1.6))
            maker = self.rnd.random() < 0.5
            if ep is not None:
                lvl = ep[2]
                p = max(p, lvl) if ep[1] == "bull" else min(p, lvl)          # le prix ne passe pas au travers
                if self.rnd.random() < 0.5:
                    p, usd, maker = lvl, math.exp(self.rnd.gauss(11.2, 0.5)), ep[1] == "bull"   # vendeurs (acheteurs) agressifs absorbes
            tp.on_trade(p, usd / p, maker, int(t * 1000), int(t * 1000) - 40, t)
        self._episode[sym] = (nxt, ep)

    def ladder(self, sym: str, step: float, rows: int = 60, center: float | None = None, big_since: int = 0) -> dict:
        sym = sym.upper()
        with self.lock:
            self._pump(sym)
        px = self.price_of(sym)
        tp = self.tapes[sym]
        out = {"symbol": sym, "ready": bool(px), "simulated": True, "step": step, "mid": px, "since": tp.since,
               "book": {"source": "simulé", "synced": True, "error": "", "resyncs": 0},
               "orders": {"source": "simulé", "synced": True, "check": True, "error": ""},
               "tape": tp.speed(), "latency": {"trades": 40, "book": 60}, "threshold": round(tp.thr),
               "big": [b for b in list(tp.big) if b["t"] >= big_since][-500:], "absorb": tp.absorptions(big_since), "absorbThr": tp.absorb.thr}
        if not px or step <= 0:
            out["rows"] = []
            return out
        rnd = random.Random(int(self.now() * 2))                      # le carnet bouge deux fois par seconde
        tick = max(step / 5, px * 1e-5)
        bids, asks, ob, oa = [], [], [], []
        for i in range(1, int(rows * step / tick / 2) + 2):
            for book, okx, p in ((bids, ob, px - i * tick), (asks, oa, px + i * tick)):
                q = rnd.expovariate(1.0) * 40000 / px * (3 if rnd.random() < 0.04 else 1)
                book.append((p, q))
                okx.append((p, q, max(1, int(q * px / 4000) + rnd.randint(0, 3))))
        with tp.lock:
            foot = dict(tp.foot)
        out["rows"] = ladder_rows(step, center or px, max(4, min(int(rows), 400)), bids, asks, ob, oa, foot)
        out["bestBid"], out["bestAsk"] = px - tick, px + tick
        return out

    def reset(self, sym: str):
        t = self.tapes.get(sym.upper())
        if t:
            t.reset()

    def status(self):
        return {"simulé": {"connected": True, "lastMsg": self.now(), "error": "", "connects": 1}}

    def start(self):
        pass

    def stop(self):
        pass
