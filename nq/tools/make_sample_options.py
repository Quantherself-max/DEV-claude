"""Écrit une chaîne d'options FICTIVE au format des cotations différées du CBOE (pour essayer le GEX sans réseau) :
    python tools/make_sample_options.py options.json [prix du sous-jacent] [AAAA-MM-JJ]
puis NQ_GEX_FILE=options.json. Les intérêts ouverts sont inventés : rien ici ne dit quoi que ce soit du vrai marché."""
import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.gex import bs_gamma  # noqa: E402


def make(spot: float, today: date, seed: int = 3) -> dict:
    rnd = random.Random(seed)
    exps = [today + timedelta(days=d) for d in (0, 1, 2, 7, 14, 30, 60)]
    exps = [e for e in exps if e.weekday() < 5]
    opts = []
    for e in exps:
        t = max((e - today).days, 0.3) / 365.0
        for k in range(int(spot * 0.85) // 50 * 50, int(spot * 1.15), 50):
            for cp in "CP":
                iv = 0.18 + 0.25 * ((k / spot - 1) ** 2) * 10 + (0.03 if cp == "P" and k < spot else 0.0)
                dist = abs(k - spot) / spot
                oi = int(rnd.expovariate(1 / 600) * math.exp(-dist * 18) * (3 if k % 500 == 0 else 1))
                if cp == "C" and k == int(spot * 1.03) // 250 * 250:
                    oi *= 6                                    # un gros mur de calls
                if cp == "P" and k == int(spot * 0.97) // 250 * 250:
                    oi *= 6                                    # un gros mur de puts
                sym = f"NDX{e.strftime('%y%m%d')}{cp}{int(k * 1000):08d}"
                opts.append({"option": sym, "open_interest": oi, "iv": round(iv, 4), "gamma": bs_gamma(spot, k, t, iv), "volume": oi // 3})
    return {"timestamp": f"{today.isoformat()} 15:00:00", "data": {"symbol": "_NDX", "current_price": spot, "options": opts}}


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "options.json"
    spot = float(sys.argv[2]) if len(sys.argv) > 2 else 24_900.0
    day = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else date.today()
    Path(out).write_text(json.dumps(make(spot, day)), encoding="utf-8")
    print(f"chaîne fictive écrite dans {out}")
