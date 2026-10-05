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
