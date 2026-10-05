"""Rapports de backtest (JSON) : ceux livres avec le terminal (dossier reports/) et ceux que tu as relances sur tes donnees (data_local/reports/).
Nom des fichiers : backtest_<ACTIF>.json (BTC, SOL, ETH...)."""
import json
import re
from pathlib import Path

_LABEL = re.compile(r"^backtest_([A-Za-z0-9]+)\.json$")


def base_of(symbol: str) -> str:
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def _files(dirs):
    seen = {}
    for d in dirs:                                   # les dossiers suivants l'emportent (tes propres rapports avant ceux livres)
        d = Path(d)
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            m = _LABEL.match(f.name)
            if m:
                seen[m.group(1).upper()] = f
    return seen


def load(dirs, label: str):
    f = _files(dirs).get(label.upper())
    if not f:
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def summaries(dirs):
    out = []
    for lab, f in _files(dirs).items():
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"label": lab, "computedAt": r.get("computedAt"), "period": r.get("period"), "verdict": (r.get("verdict") or {}).get("text"),
                    "source": r.get("source"), "own": "data_local" in str(f)})
    return sorted(out, key=lambda x: x["label"])


def evidence(dirs, symbol: str):
    """Chiffres qui appuient le filtre de tendance pour ce symbole : son propre rapport sinon celui de BTC (indique comme tel)."""
    base = base_of(symbol).upper()
    rep, proxy = load(dirs, base), False
    if rep is None:
        rep, proxy = load(dirs, "BTC"), True
    if not rep or "trend" not in rep:
        return None
    try:
        a, c = rep["trend"]["aligned"], rep["trend"]["counter"]
        y0 = __import__("time").gmtime(rep["period"]["start"] / 1000).tm_year
        y1 = __import__("time").gmtime(rep["period"]["end"] / 1000).tm_year
        lab = f"{rep['label']} {y0}-{y1}" + (" (rapport BTC : pas encore de rapport pour ce symbole)" if proxy else "")
        return {"label": lab, "aligned": a["expR"], "counter": c["expR"], "n": a["n"], "proxy": proxy}
    except (KeyError, TypeError):
        return None
