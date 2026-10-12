"""Source FICHIER : lit des transactions (ticks) dans un fichier CSV, puis suit les lignes ajoutees au fil de l'eau.

C'est la porte d'entree des VRAIES donnees sans API payante cote terminal : la plateforme que tu utilises deja pour trader (NinjaTrader,
Sierra Chart, Bookmap, ATAS, Tradovate...) ecrit les transactions dans un fichier, le terminal les lit. Le fichier peut aussi etre un export
d'historique tick (Databento, Rithmic, Sierra Chart...).

Colonnes reconnues (nom insensible a la casse, ordre libre, separateur , ; ou tabulation, avec ou sans en-tete) :
  heure    : time, timestamp, datetime, date_time, ts, ts_event, ts_recv  (ms, s, µs ou ns depuis 1970 ; ISO 8601 ; « 2026-10-12 09:30:01.123 »)
  prix     : price, last, px, trade_price
  quantite : size, volume, qty, quantity, vol, trade_size
  cote     : side, aggressor, initiator -- facultatif. Compris sans ambiguite : buy / sell, B / S, 1 / -1, « ask » (execute a l'ask =
             acheteur agressif), « bid » (execute au bid = vendeur agressif). Les lettres A / B (ask / bid) different selon les sources : elles
             ne sont PAS devinees. Si ton fichier les utilise, dis ce qu'elles veulent dire avec `buy_codes` et `sell_codes`.
  carnet   : bid, ask (prix) -- facultatif : sans colonne de cote, un prix >= ask = acheteur agressif, <= bid = vendeur agressif
Sans cote ni carnet, le terminal estime le cote par la regle du tick (le delta est alors une ESTIMATION, signalee dans l'interface).

Heures sans fuseau (« 2026-10-12 09:30:01 ») : fuseau donne par `tz` (utc, et ou paris). Fichier sans en-tete : precise `columns`."""
import csv
import io
import re
import time
from datetime import datetime
from pathlib import Path

from engine import clock
from engine.bars import Tick

from .base import DataError, Source

ALIASES = {
    "t": ("time", "timestamp", "datetime", "date_time", "ts", "ts_event", "ts_recv", "date"),
    "p": ("price", "last", "px", "trade_price", "last_price"),
    "q": ("size", "volume", "qty", "quantity", "vol", "trade_size", "last_size"),
    "s": ("side", "aggressor", "initiator", "aggressor_side"),
    "bid": ("bid", "bid_price", "bidprice"),
    "ask": ("ask", "ask_price", "askprice"),
}
BUY_WORDS = {"b", "buy", "buyer", "1", "+1", "ask", "up"}
SELL_WORDS = {"s", "sell", "seller", "-1", "bid", "down"}


def parse_time(raw: str, tz: str = "utc") -> int:
    """Texte -> ms UTC. Nombre : ms / s / µs / ns selon sa taille ; sinon date ISO ou « AAAA-MM-JJ HH:MM:SS[.fff] » (avec Z ou decalage +HH:MM
    eventuel ; sans indication, c'est l'heure murale du fuseau `tz`)."""
    s = raw.strip().strip('"')
    if re.fullmatch(r"\d+(\.\d+)?", s):
        x = float(s)
        if x >= 1e17:
            return int(x / 1e6)               # nanosecondes
        if x >= 1e14:
            return int(x / 1e3)               # microsecondes
        if x >= 1e11:
            return int(x)                     # millisecondes
        return int(x * 1000)                  # secondes
    s = s.replace("T", " ").replace("/", "-")
    off = None                                # decalage explicite, en ms (None = heure murale du fuseau `tz`)
    m = re.search(r"(\d\d:\d\d(?::\d\d(?:\.\d+)?)?)\s*(Z|[+-]\d\d:?\d\d)$", s)
    if m:
        z = m.group(2)
        off = 0 if z == "Z" else (1 if z[0] == "+" else -1) * (int(z[1:3]) * 60 + int(z[-2:])) * 60_000
        s = s[:m.start(2)].strip()
    w = None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            w = datetime.strptime(s[:26], fmt)
            break
        except ValueError:
            continue
    if w is None:
        raise DataError(f"heure illisible : « {raw} »")
    return clock.wall_to_utc(w, tz) if off is None else clock.wall_to_utc(w, "utc") - off


def parse_side(raw, buy_codes=(), sell_codes=()) -> int:
    """Cote lu dans un fichier -> +1 (acheteur agressif) / -1 (vendeur agressif) / 0 (inconnu). `buy_codes` / `sell_codes` : valeurs propres a
    la source, prioritaires (ex. si « A » veut dire execute a l'ask : buy_codes=('a',))."""
    s = str(raw).strip().lower()
    if s in buy_codes:
        return 1
    if s in sell_codes:
        return -1
    if s in BUY_WORDS:
        return 1
    if s in SELL_WORDS:
        return -1
    return 0


def _map_header(cells: list) -> dict:
    low = [c.strip().strip('"').lower() for c in cells]
    out = {}
    for key, names in ALIASES.items():
        for n in names:
            if n in low:
                out[key] = low.index(n)
                break
    return out


def _delim(sample: str) -> str:
    return max((";", "\t", ","), key=lambda d: sample.count(d))


class RowParser:
    def __init__(self, tz: str = "utc", columns: str | None = None, buy_codes=(), sell_codes=()):
        self.tz = tz
        self.buy_codes = tuple(str(c).lower() for c in buy_codes)
        self.sell_codes = tuple(str(c).lower() for c in sell_codes)
        self.cols = _map_header(columns.split(",")) if columns else None
        self.delim = ","
        self.bad = 0

    def feed_header(self, line: str) -> bool:
        """True si la ligne est un en-tete (elle est alors consommee)."""
        if self.cols is not None:
            return False
        self.delim = _delim(line)
        cells = next(csv.reader([line], delimiter=self.delim))
        cols = _map_header(cells)
        if {"t", "p", "q"} <= set(cols):
            self.cols = cols
            return True
        raise DataError("en-tête CSV non reconnu : il faut au moins une colonne heure, prix et quantité "
                        f"(vu : {', '.join(c.strip() for c in cells)[:120]}). Sans en-tête, précise les colonnes (réglage « columns »).")

    def parse(self, line: str):
        line = line.strip()
        if not line:
            return None
        try:
            cells = next(csv.reader([line], delimiter=self.delim))
            c = self.cols
            t = parse_time(cells[c["t"]], self.tz)
            p = float(cells[c["p"]])
            q = float(cells[c["q"]])
            if q <= 0 or p <= 0:
                return None
            side = parse_side(cells[c["s"]], self.buy_codes, self.sell_codes) if "s" in c and c["s"] < len(cells) else 0
            if not side and "bid" in c and "ask" in c and max(c["bid"], c["ask"]) < len(cells):
                bid, ask = float(cells[c["bid"]] or 0), float(cells[c["ask"]] or 0)
                if ask > 0 and p >= ask:
                    side = 1
                elif bid > 0 and p <= bid:
                    side = -1
            return Tick(t, p, q, side)
        except (ValueError, IndexError, KeyError, DataError):
            self.bad += 1
            return None


class CsvSource(Source):
    """Lit le fichier PAR BLOCS (un export de ticks fait vite plusieurs Go : jamais tout en memoire), puis suit les lignes ajoutees.

    `max_days` : on ne garde que les N derniers jours DU FICHIER (la date de la derniere transaction, pas celle de l'horloge : on peut ainsi
    rejouer un vieux fichier). `history()` est un GENERATEUR : le marche consomme les transactions au fur et a mesure."""
    name = "csv"
    CHUNK = 8 * 1024 * 1024                                      # octets lus a chaque tour

    def __init__(self, path, tz: str = "utc", columns: str | None = None, buy_codes=(), sell_codes=(), max_days: float = 6.0, follow: bool = True,
                 chunk_bytes: int | None = None):
        self.path = Path(path)
        self.parser = RowParser(tz, columns, buy_codes, sell_codes)
        self.max_days = max_days
        self.follow = follow
        self.chunk = chunk_bytes or self.CHUNK
        self.label = f"Fichier : {self.path.name}"
        self._pos = 0
        self._rest = b""
        self.rows = 0
        self.last_t = None

    def _check(self):
        if not self.path.is_file():
            raise DataError(f"fichier introuvable : {self.path}")

    def _ensure_header(self) -> None:
        """Lit la 1re ligne pour reconnaitre les colonnes (sauf si `columns` est donne)."""
        if self.parser.cols is not None:
            return
        with open(self.path, "rb") as f:
            first = f.readline().decode("utf-8-sig", "replace")
        if first.strip():
            self.parser.feed_header(first)

    def _read_chunk(self, limit) -> list:
        """Transactions des lignes COMPLETES lues a partir de la position courante (au plus `limit` octets ; None = tout ce qui est disponible)."""
        self._check()
        size = self.path.stat().st_size
        if size < self._pos:                                      # fichier remplace ou tronque : on repart du debut
            self._pos, self._rest = 0, b""
        with open(self.path, "rb") as f:
            f.seek(self._pos)
            data = f.read(limit) if limit else f.read()
        self._pos += len(data)
        buf = self._rest + data
        cut = buf.rfind(b"\n")
        if cut < 0:                                               # ligne encore incomplete : on attend la suite
            self._rest = buf
            return []
        self._rest = buf[cut + 1:]
        out = []
        for line in io.StringIO(buf[:cut + 1].decode("utf-8-sig", "replace")):
            if self.parser.cols is None:
                if self.parser.feed_header(line):
                    continue
            elif self._looks_like_header(line):
                continue
            tk = self.parser.parse(line)
            if tk is not None:
                out.append(tk)
        self.rows += len(out)
        if out:
            self.last_t = max(self.last_t or 0, max(t.t for t in out))
        return out

    @staticmethod
    def _looks_like_header(line: str) -> bool:
        return bool(re.match(r"\s*\"?[A-Za-z_]", line))

    def _tail_time(self):
        """Heure de la transaction la plus recente parmi les dernieres lignes du fichier (None si illisible) : sert de repere a `max_days`."""
        size = self.path.stat().st_size
        with open(self.path, "rb") as f:
            f.seek(max(0, size - 65536))
            lines = f.read().decode("utf-8-sig", "replace").splitlines()
        best, bad = None, self.parser.bad
        for line in lines[1:] if size > 65536 else lines:         # la 1re ligne d'un bout de fichier est probablement coupee
            if self._looks_like_header(line):
                continue
            tk = self.parser.parse(line)
            if tk is not None and (best is None or tk.t > best):
                best = tk.t
        self.parser.bad = bad                                     # ce repérage ne compte pas dans les lignes refusées : elles seront relues (et comptées) par le flux
        return best

    def history(self, now_ms: int):
        self._check()
        self._pos, self._rest, self.rows, self.last_t = 0, b"", 0, None
        self._ensure_header()
        self.parser.bad = 0
        ref = self._tail_time() or now_ms
        horizon = ref - int(self.max_days * clock.DAY)
        return self._stream(horizon)

    def _stream(self, horizon: int):
        while True:
            before = self._pos
            chunk = self._read_chunk(self.chunk)
            if self._pos == before:                               # plus rien a lire
                return
            chunk.sort(key=lambda t: t.t)                         # les exports sont rarement tries a la milliseconde pres
            for tk in chunk:
                if tk.t >= horizon:
                    yield tk

    def poll(self, now_ms: int) -> list:
        return self._read_chunk(None) if self.follow else []

    def info(self) -> dict:
        d = super().info()
        d.update({"path": str(self.path), "rows": self.rows, "badRows": self.parser.bad, "lastT": self.last_t})
        return d


def selftest_file(path) -> tuple:
    """(ok, message) : le fichier existe-t-il et ses premieres lignes sont-elles lisibles ? Pour le bouton « Tester » des reglages."""
    p = Path(path)
    if not p.is_file():
        return False, f"fichier introuvable : {p}"
    src = CsvSource(p, follow=False, max_days=36_500)             # test de lecture : aucun filtre d'age
    try:
        ticks = list(src.history(int(time.time() * 1000)))
    except DataError as e:
        return False, str(e)
    if not ticks:
        return False, f"aucune transaction lisible ({src.parser.bad} ligne(s) refusée(s))"
    sides = sum(1 for t in ticks if t.side)
    return True, (f"{len(ticks)} transactions lues, de {clock.fmt_hms(ticks[0].t, 'paris')} à {clock.fmt_hms(ticks[-1].t, 'paris')} (Paris) ; "
                  f"côté de l'agresseur fourni pour {sides / len(ticks) * 100:.0f} % d'entre elles"
                  + ("" if sides else " : le delta sera ESTIMÉ par la règle du tick"))


__all__ = ["CsvSource", "RowParser", "parse_time", "parse_side", "selftest_file"]
