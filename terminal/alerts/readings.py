"""Historique des lectures du terminal (V13) : une fois par jour et par paire, ce que le terminal « pensait » (tendance de fond, biais, squeeze, climat
macro, idee du moment), puis ce que le prix a fait ensuite (24 h, 3 jours, 7 jours). On peut ainsi suivre ses analyses dans le temps, pas seulement ses idees.

Seule la tendance de fond est validee par le backtest : c'est elle qu'on note (le prix est-il alle dans son sens ?). Le reste est garde pour memoire.
Le terminal n'enregistre que lorsqu'il tourne : un jour ou il est eteint n'a pas de lecture (rien n'est reconstruit apres coup)."""
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

HORIZONS = (24, 72, 168)
HOUR = 3_600_000
KEEP = 600


def day_of(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def snapshot(lec: dict) -> dict:
    """Resume d'une lecture (sortie de Service.lecture)."""
    h = lec.get("head") or {}
    tr, bi, sq, idea = h.get("trend") or {}, h.get("bias") or {}, lec.get("squeeze") or {}, lec.get("idea") or {}
    macro = next((c for c in lec.get("chips") or [] if c.get("key") == "macro"), None)
    return {"price": h.get("price"), "trend": tr.get("regime"), "trendLabel": tr.get("label"), "bias": bi.get("label"), "biasValidated": bool(bi.get("validated")),
            "squeeze": sq.get("label"), "squeezeCode": sq.get("code"), "macro": (macro or {}).get("value"),
            "idea": {"side": idea.get("side"), "score": idea.get("score"), "eligible": idea.get("eligible")} if idea.get("side") else None}


class ReadingLog:
    def __init__(self, cfg, now=time.time):
        self.dir = Path(cfg.data_dir) / ("simulated" if cfg.source == "simulated" else "")
        self.file = self.dir / "readings.json"
        self.now = now
        self.lock = threading.Lock()
        self.rows = self._load()
        self._evaluated = 0.0

    def _load(self) -> list:
        try:
            return list(json.loads(self.file.read_text(encoding="utf-8")))[-KEEP:]
        except (OSError, ValueError):
            return []

    def _save(self):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.rows[-KEEP:], ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.file)
        except OSError:
            pass

    def due(self, sym: str, now_ms: int) -> bool:
        d = day_of(now_ms)
        return not any(r["symbol"] == sym and r["day"] == d for r in self.rows[-50:])

    def record(self, sym: str, now_ms: int, snap: dict) -> dict | None:
        if not snap.get("price"):
            return None
        row = {"day": day_of(now_ms), "t": now_ms, "symbol": sym, **snap, "after": {}}
        with self.lock:
            self.rows.append(row)
            self._save()
        return row

    def evaluate(self, price_at, now_ms: int, every_s: float = 600.0) -> int:
        """Complete le prix apres 24 h / 3 j / 7 j quand il est connu. price_at(symbole, t_ms) -> prix ou None. Renvoie le nombre de cases remplies."""
        if self.now() - self._evaluated < every_s:
            return 0
        self._evaluated = self.now()
        n = 0
        with self.lock:
            for r in self.rows:
                for hh in HORIZONS:
                    k = str(hh)
                    if k in r["after"] or now_ms < r["t"] + hh * HOUR:
                        continue
                    p = price_at(r["symbol"], r["t"] + hh * HOUR)
                    if p and r.get("price"):
                        r["after"][k] = (p / r["price"] - 1.0) * 100.0
                        n += 1
            if n:
                self._save()
        return n

    def public(self, limit: int = 120) -> dict:
        """Lectures (plus recentes d'abord) et, pour la tendance de fond, la part des fois ou le prix est alle dans son sens."""
        rows = list(self.rows[::-1][:limit])
        score = {}
        for hh in HORIZONS:
            k = str(hh)
            judged = [r for r in self.rows if r.get("trend") and k in r["after"]]
            ok = sum(1 for r in judged if (r["after"][k] > 0) == (r["trend"] > 0))
            score[k] = {"n": len(judged), "right": ok, "rate": ok / len(judged) if judged else None,
                        "avg": sum(r["after"][k] * (1 if r["trend"] > 0 else -1) for r in judged) / len(judged) if judged else None}
        return {"rows": rows, "trendScore": score, "horizons": list(HORIZONS)}
