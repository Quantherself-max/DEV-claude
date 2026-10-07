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
    refresh_seconds: int = 5             # recalcul des niveaux / alertes ; le prix, lui, arrive en temps reel
    binance_ws: str = "wss://fstream.binance.com/market"   # flux temps reel Binance futures (route /market depuis 2026)
    coinbase_ws: str = "wss://ws-feed.exchange.coinbase.com"   # prix Coinbase en direct (meme marche que ton TradingView)
    live_ws: bool = True                 # flux temps reel cote serveur (prix exact pour les alertes, liquidations reelles)
    anchor_date: str = "2024-01-01"      # VWAP ancree
    history_years: int = 0                # historique d'analyse (bougies 1h) : 0 = le plus long possible (depuis septembre 2019)
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
    alert_mode: str = "ideas"             # "ideas" = SEULEMENT les idees de trade sur Telegram | "all" = + alertes de zones, de poches et d'annonces
    alert_zones: bool = True              # (mode all) alertes « nouvelle confluence » / « le prix approche »
    alert_sweep: bool = True              # alerte quand une grosse poche de liquidation est balayee
    alert_sweep_frac: float = 0.15        # ... si elle represente >= 15 % des liquidations de ce cote
    alert_macro: bool = True              # alerte ~1 h avant une annonce majeure + bilan de la reaction du marche
    alert_tf: str = "1h"
    alert_min_score: int = 3             # nb de sources distinctes (+1 si une poche AIMANT en fait partie)
    alert_max_dist_atr: float = 6.0
    alert_approach_atr: float = 0.5
    alert_cooldown_hours: float = 6.0
    alert_max_per_hour: int = 6
    # idees de trade (V5) : quelques idees rares, de haute qualite, avec stop et objectifs
    signal_on: bool = True
    signal_min_score: float = 60.0        # score minimal sur 100 (la derniere place de la semaine exige +8)
    signal_max_week: int = 5              # idees par semaine au maximum (lundi 00:00 UTC)
    signal_max_per_symbol: int = 3        # dont au plus N pour une meme paire (plusieurs paires suivies) : evite qu'une paire prenne toutes les places
    signal_min_struct: float = 7.0        # qualite minimale des niveaux superposes
    signal_leverage: float = 10.0         # levier utilise pour les calculs de liquidation affiches
    signal_valid_hours: int = 48          # duree de validite d'un ordre limite
    derivs_on: bool = True                # derives multi-bourses (Deribit, Bybit, OKX, Hyperliquid) et jeux libres en chaine : lecture seule, aucune cle
    signal_direction: str = "both"        # both = achats et ventes (jamais deux biais opposes a moins de 24 h) | long = achat seulement : les ventes deviennent des « alertes pour tes longs » | short
    signal_trend_gate: bool = True        # n'envoyer que les idees dans le sens de la tendance de fond (moyennes 50 j / 200 j) : seul filtre valide par le backtest
    # avis d'influenceurs sur X (facultatif, indicatif, hors score) : jeton X (API officielle) + comptes a suivre
    x_on: bool = True
    x_token: str = ""
    x_accounts: tuple = ()
    x_posts: int = 10                     # posts lus par compte (5 a 20)
    x_max_age_h: float = 48.0
    x_api_base: str = "https://api.x.com"
    # mise a jour automatique (V11) : nouvelle version publiee sur GitHub -> installee et terminal relance, sans fermer la fenetre
    update_auto: bool = True
    update_repo: str = "Quantherself-max/DEV-claude"
    update_branch: str = "auto"           # « auto » = la branche la plus recemment mise a jour qui contient le terminal
    update_token: str = ""                # jeton GitHub en LECTURE SEULE (depot prive)
    update_minutes: int = 30
    update_api: str = "https://api.github.com"
    # discussion avec Claude (V12) : questions sur Telegram ou dans l'onglet Discussion ; cle API Anthropic payante a l'usage
    chat_key: str = ""
    chat_model: str = "claude-opus-5-5"
    chat_web: bool = True                 # recherche d'actualites sur le web quand les donnees du terminal ne suffisent pas
    chat_telegram: bool = True            # repondre aux messages envoyes au bot Telegram (seulement depuis ton chat id)
    chat_budget: float = 20.0             # plafond de depense mensuelle en dollars (0 = sans plafond)
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
    c.refresh_seconds = max(3, int(g("TERMINAL_REFRESH_SECONDS", c.refresh_seconds)))
    c.binance_ws = g("TERMINAL_BINANCE_WS", c.binance_ws).rstrip("/")
    c.coinbase_ws = g("TERMINAL_COINBASE_WS", c.coinbase_ws).rstrip("/")
    c.live_ws = g("TERMINAL_LIVE_WS", "1").lower() not in ("0", "false", "non", "no")
    c.anchor_date = g("TERMINAL_ANCHOR_DATE", c.anchor_date)
    c.history_years = max(0, min(10, int(float(g("TERMINAL_HISTORY_YEARS", c.history_years)))))
    c.alert_tf = g("TERMINAL_ALERT_TF", c.alert_tf)
    c.alert_min_score = int(g("TERMINAL_ALERT_MIN_SCORE", c.alert_min_score))
    c.alert_cooldown_hours = float(g("TERMINAL_ALERT_COOLDOWN_HOURS", c.alert_cooldown_hours))
    c.alert_mode = "all" if g("TERMINAL_ALERT_MODE", c.alert_mode).lower() == "all" else "ideas"
    c.alert_zones = g("TERMINAL_ALERT_ZONES", "1").lower() not in ("0", "false", "non", "no")
    c.alert_sweep = g("TERMINAL_ALERT_SWEEP", "1").lower() not in ("0", "false", "non", "no")
    c.alert_macro = g("TERMINAL_ALERT_MACRO", "1").lower() not in ("0", "false", "non", "no")
    c.signal_on = g("TERMINAL_SIGNALS", "1").lower() not in ("0", "false", "non", "no")
    c.signal_min_score = max(40.0, min(95.0, float(g("TERMINAL_SIGNAL_MIN_SCORE", c.signal_min_score))))
    c.signal_max_week = max(1, min(10, int(float(g("TERMINAL_SIGNAL_MAX_WEEK", c.signal_max_week)))))
    c.signal_max_per_symbol = max(1, min(10, int(float(g("TERMINAL_SIGNAL_MAX_PER_SYMBOL", c.signal_max_per_symbol)))))
    c.signal_min_struct = max(4.0, min(20.0, float(g("TERMINAL_SIGNAL_MIN_STRUCT", c.signal_min_struct))))
    c.signal_leverage = max(1.0, min(125.0, float(g("TERMINAL_SIGNAL_LEVERAGE", c.signal_leverage))))
    c.signal_valid_hours = max(4, min(168, int(float(g("TERMINAL_SIGNAL_VALID_HOURS", c.signal_valid_hours)))))
    c.signal_direction = {"long": "long", "short": "short", "both": "both"}.get(g("TERMINAL_SIGNAL_DIRECTION", c.signal_direction).strip().lower(), "both")
    c.signal_trend_gate = g("TERMINAL_SIGNAL_TREND_GATE", "1").lower() not in ("0", "false", "non", "no")
    c.derivs_on = g("TERMINAL_DERIVS", "1").lower() not in ("0", "false", "non", "no")
    c.x_on = g("TERMINAL_X_ON", "1").lower() not in ("0", "false", "non", "no")
    c.x_token = g("TERMINAL_X_BEARER_TOKEN", "").strip()
    from data.social import clean_handles
    c.x_accounts = tuple(clean_handles(g("TERMINAL_X_ACCOUNTS", "")))
    c.x_posts = max(5, min(20, int(float(g("TERMINAL_X_POSTS", c.x_posts)))))
    c.x_api_base = g("TERMINAL_X_API_BASE", c.x_api_base).rstrip("/")
    c.stats_horizon = int(g("TERMINAL_STATS_HORIZON", c.stats_horizon))
    c.stats_k = float(g("TERMINAL_STATS_K", c.stats_k))
    c.update_auto = g("TERMINAL_UPDATE_AUTO", "1").lower() not in ("0", "false", "non", "no")
    c.update_repo = g("TERMINAL_UPDATE_REPO", c.update_repo).strip().strip("/") or "Quantherself-max/DEV-claude"
    c.update_branch = g("TERMINAL_UPDATE_BRANCH", c.update_branch).strip() or "auto"
    c.update_token = g("TERMINAL_GITHUB_TOKEN", "").strip()
    c.update_minutes = max(10, min(1440, int(float(g("TERMINAL_UPDATE_MINUTES", c.update_minutes)))))
    c.update_api = g("TERMINAL_UPDATE_API", c.update_api).rstrip("/")
    c.chat_key = g("TERMINAL_ANTHROPIC_API_KEY", "").strip()
    c.chat_model = g("TERMINAL_CHAT_MODEL", c.chat_model).strip() or "claude-opus-5-5"
    c.chat_web = g("TERMINAL_CHAT_WEB", "1").lower() not in ("0", "false", "non", "no")
    c.chat_telegram = g("TERMINAL_CHAT_TELEGRAM", "1").lower() not in ("0", "false", "non", "no")
    c.chat_budget = max(0.0, min(1000.0, float(g("TERMINAL_CHAT_BUDGET", c.chat_budget))))
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


def migrate_env(path: Path, data_dir) -> bool:
    """Migration unique (V13.1) : la V13 mettait « achat seulement » par defaut et l'ecrivait dans .env a chaque enregistrement des reglages.
    Retour a « achats et ventes » une seule fois ; un choix fait ensuite (reglages ou .env) est respecte. True si .env a change."""
    mark = Path(data_dir) / ".migrated-direction"
    if mark.exists():
        return False
    changed = False
    try:
        if path.exists() and _load_env_file(path).get("TERMINAL_SIGNAL_DIRECTION", "").strip().lower() == "long":
            write_env(path, {"TERMINAL_SIGNAL_DIRECTION": "both"})
            changed = True
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text("V13.1 : TERMINAL_SIGNAL_DIRECTION remis a both une seule fois\n", encoding="utf-8")
    except OSError:
        pass
    return changed
