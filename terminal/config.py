"""Configuration : variables d'environnement, completees par un fichier .env (voir config.example.env)."""
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_env_file(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


@dataclass
class Config:
    source: str = "binance"              # binance = vraies donnees (par defaut) | simulated = prix fictifs (essai hors ligne)
    symbols: tuple = ("BTCUSDT", "SOLUSDT")
    host: str = "127.0.0.1"              # local uniquement : le terminal n'est pas expose sur le reseau
    port: int = 8765
    refresh_seconds: int = 30
    anchor_date: str = "2024-01-01"      # VWAP ancree
    # fenetre autour du prix et confluences (en ATR du timeframe affiche)
    dist_atr: float = 8.0
    min_dist_pct: float = 1.5
    conf_atr: float = 0.30
    conf_min_pct: float = 0.15
    # poches de liquidite
    keep_pct: float = 35.0
    per_side: int = 3
    clust_pct: float = 0.25
    magnet_pct: float = 70.0
    # probabilites (mesurees sur l'historique 1h) : rebond = +k ATR avant -k ATR dans l'horizon
    stats_horizon: int = 24
    stats_k: float = 1.5
    stats_refresh_hours: float = 6.0
    # alertes
    alert_sweep: bool = True              # alerte quand une grosse poche de liquidation est balayee
    alert_sweep_frac: float = 0.15        # ... si elle represente >= 15 % des liquidations de ce cote
    alert_tf: str = "1h"
    alert_min_score: int = 3             # nb de sources distinctes (+1 si une poche AIMANT en fait partie)
    alert_max_dist_atr: float = 6.0
    alert_approach_atr: float = 0.5
    alert_cooldown_hours: float = 6.0
    alert_max_per_hour: int = 6
    telegram_token: str = ""
    telegram_chat_id: str = ""
    telegram_api_base: str = "https://api.telegram.org"
    data_dir: str = str(ROOT / "data_local")

    @property
    def anchor_ms(self) -> int:
        return int(datetime.strptime(self.anchor_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)

    @property
    def telegram_on(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)


def load_config(env_path: Path | None = None) -> Config:
    env = _load_env_file(env_path or ROOT / ".env")
    env.update({k: v for k, v in os.environ.items() if k.startswith(("TERMINAL_", "TELEGRAM_"))})
    c = Config()
    g = env.get
    c.source = g("TERMINAL_SOURCE", c.source).lower()
    c.symbols = tuple(s.strip().upper() for s in g("TERMINAL_SYMBOLS", ",".join(c.symbols)).split(",") if s.strip())
    c.host = g("TERMINAL_HOST", c.host)
    c.port = int(g("TERMINAL_PORT", c.port))
    c.refresh_seconds = int(g("TERMINAL_REFRESH_SECONDS", c.refresh_seconds))
    c.anchor_date = g("TERMINAL_ANCHOR_DATE", c.anchor_date)
    c.alert_tf = g("TERMINAL_ALERT_TF", c.alert_tf)
    c.alert_min_score = int(g("TERMINAL_ALERT_MIN_SCORE", c.alert_min_score))
    c.alert_cooldown_hours = float(g("TERMINAL_ALERT_COOLDOWN_HOURS", c.alert_cooldown_hours))
    c.alert_sweep = g("TERMINAL_ALERT_SWEEP", "1").lower() not in ("0", "false", "non", "no")
    c.stats_horizon = int(g("TERMINAL_STATS_HORIZON", c.stats_horizon))
    c.stats_k = float(g("TERMINAL_STATS_K", c.stats_k))
    c.telegram_token = g("TELEGRAM_BOT_TOKEN", "")
    c.telegram_chat_id = g("TELEGRAM_CHAT_ID", "")
    c.telegram_api_base = g("TELEGRAM_API_BASE", c.telegram_api_base)
    c.data_dir = g("TERMINAL_DATA_DIR", c.data_dir)
    return c


def write_env(path: Path, updates: dict) -> None:
    """Met a jour (ou cree) le fichier .env en gardant les autres lignes et les commentaires."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    done = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in updates:
            out.append(f"{key}={updates[key]}")
            done.add(key)
        else:
            out.append(line)
    for k, v in updates.items():
        if k not in done:
            out.append(f"{k}={v}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)            # le token Telegram n'est lisible que par toi
    except OSError:
        pass
