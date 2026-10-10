"""Historique fin (bougies 1 minute) depuis les archives publiques de Binance (data.binance.vision) ou un CSV, converti en series fines.

Les archives Binance contiennent le VOLUME ACHETEUR AGRESSIF reel de chaque minute : le CVD est alors reel, pas estime.
Module PUR pour tout ce qui n'est pas le telechargement (analyse des lignes, comblement des trous, construction des dossiers de series)."""
import csv
import io
import json
import zipfile
from datetime import datetime, timezone

from . import fine

MINUTE = 60_000
VISION = "https://data.binance.vision/data"


def vision_url(symbol: str, market: str, y: int, m: int, d: int | None = None, interval: str = "1m") -> str:
    """market : 'spot' ou 'futures' (USDT-M). Archive mensuelle, ou quotidienne si d est donne (mois en cours)."""
    base = "spot" if market == "spot" else "futures/um"
    kind = "daily" if d else "monthly"
    stamp = f"{y:04d}-{m:02d}" + (f"-{d:02d}" if d else "")
    return f"{VISION}/{base}/{kind}/klines/{symbol}/{interval}/{symbol}-{interval}-{stamp}.zip"


def vision_metrics_url(symbol: str, y: int, m: int, d: int) -> str:
    """Interet ouvert, ratios long / short et ratio taker du perpetuel USDT-M, toutes les 5 minutes, un fichier par jour (depuis decembre 2021)."""
    return f"{VISION}/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{y:04d}-{m:02d}-{d:02d}.zip"


def vision_funding_url(symbol: str, y: int, m: int) -> str:
    """Taux de financement reels (un par periode de 8 h), un fichier par mois."""
    return f"{VISION}/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{y:04d}-{m:02d}.zip"


def months(start_ms: int, end_ms: int):
    """[(annee, mois)] de start a end inclus."""
    a, b = datetime.fromtimestamp(start_ms / 1000, timezone.utc), datetime.fromtimestamp(end_ms / 1000, timezone.utc)
    y, m = a.year, a.month
    out = []
    while (y, m) <= (b.year, b.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def parse_rows(rows):
    """Lignes CSV de klines Binance -> (t_ms, o, h, l, c, volume, volume_acheteur_agressif). Tolere l'en-tete et les horodatages en microsecondes
    (archives spot depuis 2025). Les lignes illisibles sont ignorees."""
    for r in rows:
        if len(r) < 10:
            continue
        try:
            t = int(r[0])
            o, h, l, c, v, tb = float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]), float(r[9])
        except ValueError:
            continue                                    # en-tete ou ligne abimee
        if t > 10 ** 14:
            t //= 1000
        yield t, o, h, l, c, v, tb


def read_zip_rows(path_or_bytes):
    """Lignes (listes de champs) du premier CSV d'une archive zip."""
    zf = zipfile.ZipFile(io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, (bytes, bytearray)) else path_or_bytes)
    name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
    with zf.open(name) as f:
        yield from csv.reader(io.TextIOWrapper(f, encoding="utf-8", newline=""))


def append_rows(bars: fine.Bars, parsed, state: dict) -> None:
    """Ajoute des minutes (triees) a `bars`. Les minutes manquantes sont comblees par une bougie plate sans volume ; les doublons sont ignores.
    state = {'last_t': ..., 'last_c': ...} garde la suite entre deux archives."""
    last_t, last_c = state.get("last_t"), state.get("last_c")
    for t, o, h, l, c, v, tb in parsed:
        t -= t % MINUTE
        if last_t is not None:
            if t <= last_t:
                continue
            while last_t + MINUTE < t and t - last_t <= 2 * 86_400_000:           # trou court (maintenance) : bougies plates ; au-dela, on saute
                last_t += MINUTE
                bars.append(last_t, last_c, last_c, last_c, last_c, 0.0, 0.0)
        bars.append(t, o, h, l, c, v, 2.0 * tb - v)
        last_t, last_c = t, c
    state["last_t"], state["last_c"] = last_t, last_c


def build_folder(bars: fine.Bars, folder, meta: dict | None = None) -> dict:
    """Ecrit b1m / b5m / b15m / b1h dans `folder` (format lu par backtest.Dataset.load) et un meta.json."""
    from pathlib import Path
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    bars.build_cum()
    bars.save(out / "b1m.bin")
    n = {"b1m": len(bars)}
    for name, step in (("b5m", 300_000), ("b15m", 900_000), ("b1h", 3_600_000)):
        x = fine.resample(bars, step)
        x.save(out / f"{name}.bin")
        n[name] = len(x)
    info = {"bars": n, "from": int(bars.t[0]) if len(bars) else None, "to": int(bars.t[-1]) if len(bars) else None, **(meta or {})}
    (out / "meta.json").write_text(json.dumps(info), encoding="utf-8")
    return info


def load_csv(paths, start_ms: int = 0, end_ms: int = 2 ** 62) -> fine.Bars:
    """CSV « timestamp(s),open,high,low,close,volume » (format Bitstamp) : delta estime."""
    return fine.load_bitstamp(paths, start_ms, end_ms)


# ---------------------------------------------------------------- interet ouvert et financement (V10)
def parse_time(x):
    """Horodatage en ms depuis un entier (ms ou microsecondes) ou un texte « 2022-01-01 00:05:00 » (UTC) ; None si illisible."""
    try:
        v = int(float(x))
        return v // 1000 if v > 10 ** 14 else v
    except (TypeError, ValueError):
        pass
    try:
        return int(datetime.strptime(str(x).strip()[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)
    except ValueError:
        return None


def _num(x):
    try:
        v = float(x)
        return v if v == v and abs(v) != float("inf") else None
    except (TypeError, ValueError):
        return None


def parse_metrics(rows):
    """Lignes de metrics Binance -> [(t_ms, oi_contrats, oi_dollars, ratio_taker)]. Les colonnes sont reperees par leur nom dans l'en-tete (create_time, sum_open_interest,
    sum_open_interest_value, sum_taker_long_short_vol_ratio) ; sans en-tete, ordre documente : temps, symbole, OI, OI en dollars, ..., ratio taker en derniere colonne."""
    col = {"t": 0, "oi": 2, "usd": 3, "tk": 7}
    out = []
    for i, r in enumerate(rows):
        if not r:
            continue
        if i == 0 and not str(r[0]).strip()[:1].isdigit():
            names = [str(x).strip().lower() for x in r]
            for key, nm in (("t", "create_time"), ("oi", "sum_open_interest"), ("usd", "sum_open_interest_value"), ("tk", "sum_taker_long_short_vol_ratio")):
                if nm in names:
                    col[key] = names.index(nm)
            continue
        if len(r) <= max(col["oi"], col["usd"]):
            continue
        t, oi, usd = parse_time(r[col["t"]]), _num(r[col["oi"]]), _num(r[col["usd"]])
        tk = _num(r[col["tk"]]) if len(r) > col["tk"] else None
        if t is None or oi is None or oi <= 0:
            continue
        out.append((t, oi, usd, tk))
    return out


def parse_funding(rows):
    """Lignes de fundingRate -> [(t_ms, taux)] : colonne 0 = heure du calcul, derniere colonne = taux de la periode."""
    out = []
    for i, r in enumerate(rows):
        if len(r) < 2:
            continue
        if i == 0 and not str(r[0]).strip()[:1].isdigit():
            continue
        t, x = parse_time(r[0]), _num(r[-1])
        if t is not None and x is not None:
            out.append((t, x))
    return out


def hourly(pairs, which: int = 1):
    """[(t_ms, a, b, ...)] a 5 minutes -> [(heure_ms, valeur)] : derniere valeur connue de chaque heure (champ `which`), triee, sans doublon."""
    last = {}
    for r in sorted(pairs, key=lambda x: x[0]):
        v = r[which]
        if v is not None:
            last[r[0] - r[0] % 3_600_000] = v
    return sorted(last.items())


def save_pairs(path, pairs, header: str):
    from pathlib import Path
    p = Path(path)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(header + "\n" + "\n".join(f"{t},{v!r}" for t, v in pairs) + "\n", encoding="utf-8")
    tmp.replace(p)


def load_pairs(path):
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines()[1:]:
        a, _, b = line.partition(",")
        try:
            out.append((int(a), float(b)))
        except ValueError:
            continue
    return out
