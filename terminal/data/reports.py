"""Rapports de backtest (JSON) : ceux livres avec le terminal (dossier reports/) et ceux que tu as relances sur tes donnees (data_local/reports/).
Nom des fichiers : backtest_<ACTIF>.json (BTC, SOL, ETH...)."""
import json
import re
from pathlib import Path

_LABEL = re.compile(r"^(backtest|strategy|avwap|indicators|rotation|squeeze|pockets)_([A-Za-z0-9]+)\.json$")
KINDS = ("backtest", "strategy", "avwap", "indicators", "rotation", "squeeze", "pockets")           # backtest : idees du terminal ; strategy : ta strategie (VWAP / profil de volume) ; avwap : VWAP ancres sur un mouvement d'au moins 5 % ; indicators : valeur des indicateurs (en chaine, macro) sur le prix futur ; rotation : ou va le capital, or ; squeeze : delta, CVD, volume, squeezes ; pockets : importance des poches (confluences, maturite)


def base_of(symbol: str) -> str:
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def _files(dirs, kind: str = "backtest"):
    seen = {}
    for d in dirs:                                   # les dossiers suivants l'emportent (tes propres rapports avant ceux livres)
        d = Path(d)
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            m = _LABEL.match(f.name)
            if m and m.group(1) == kind:
                seen[m.group(2).upper()] = f
    return seen


def load(dirs, label: str, kind: str = "backtest"):
    f = _files(dirs, kind).get(label.upper())
    if not f:
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def summaries(dirs):
    out = []
    for kind in KINDS:
        for lab, f in _files(dirs, kind).items():
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            out.append({"kind": kind, "label": lab, "computedAt": r.get("computedAt"), "period": r.get("period"), "verdict": (r.get("verdict") or {}).get("text"),
                        "source": r.get("source"), "own": "data_local" in str(f)})
    return sorted(out, key=lambda x: (KINDS.index(x["kind"]), x["label"]))


def strategy_summary(dirs, symbol: str, kind: str = "strategy"):
    """Resume du rapport « ta strategie » (kind « strategy ») ou « VWAP ancres sur un mouvement » (kind « avwap ») pour ce symbole (a defaut celui du BTC, indique comme tel)."""
    base = base_of(symbol).upper()
    rep, proxy = load(dirs, base, kind), False
    if rep is None:
        rep, proxy = load(dirs, "BTC", kind), True
    if not rep:
        return None
    b = rep.get("best") or {}
    return {"label": rep.get("label"), "proxy": proxy, "verdict": (rep.get("verdict") or {}).get("text"), "bestName": b.get("name"), "bestCfg": b.get("cfg"),
            "all": b.get("all"), "oos": b.get("oos"), "period": rep.get("period")}


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
