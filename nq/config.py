"""Configuration : variables d'environnement `NQ_*`, completees par un fichier `.env` (voir config.example.env)."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _read_text(path: Path) -> str:
    """Texte d'un fichier de reglages ecrit a la main : UTF-8 avec ou sans BOM (Bloc-notes de Windows), sinon Windows-1252."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _load_env_file(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in _read_text(path).splitlines():
            line = line.strip().lstrip("﻿")
            if line.startswith("export "):
                line = line[7:].lstrip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def env_sources(env_path: Path) -> list:
    """« .env.txt » (Windows cache les extensions : un « .env » cree avec le Bloc-notes devient « .env.txt »), puis « .env », qui l'emporte."""
    p = Path(env_path)
    return [f for f in (p.with_name(p.name + ".txt"), p) if f.is_file()]


@dataclass
class Config:
    source: str = "simulated"        # simulated = prix FICTIFS (essai) | csv = transactions lues dans un fichier (voir README)
    instrument: str = "NQ"           # instrument du graphique : NQ | MNQ | ES | MES
    host: str = "127.0.0.1"          # local uniquement : le terminal n'est pas expose sur le reseau
    port: int = 8766                 # (le terminal crypto est sur 8765 : les deux peuvent tourner en meme temps)
    refresh_seconds: float = 1.0     # frequence de lecture de la source
    display_tz: str = "paris"        # fuseau des heures affichees : paris | et
    big_lot: int = 0                 # taille d'un « gros ordre » (0 = valeur par defaut de l'instrument)
    zone_pts: float = 6.0            # largeur d'une zone de confluence, en points
    sim_days: int = 6                # jours de donnees simulees
    history_days: int = 10           # journees de trading gardees en memoire (profil de la semaine : 5 ; du mois : ~22 -> NQ_HISTORY_DAYS=25)
    sim_start: str = ""              # heure de depart de la simulation (« 2026-10-12T15:40:00Z », UTC) : le temps avance ensuite normalement. Vide = maintenant.
    csv_path: str = ""
    csv_tz: str = "utc"              # fuseau des heures SANS indication du fichier : utc | et | paris
    csv_columns: str = ""            # colonnes si le fichier n'a pas d'en-tete : « time,price,size,side »
    csv_buy_codes: tuple = ()        # valeurs de la colonne « cote » qui veulent dire acheteur agressif (si ce n'est pas B / buy / ask)
    csv_sell_codes: tuple = ()
    data_dir: str = str(ROOT / "data_local")
    auto_source: bool = False        # vrai si le fichier de l'enregistreur NinjaTrader a ete trouve tout seul
    source_explicit: bool = False    # NQ_SOURCE ecrit dans .env ou l'environnement (la detection automatique ne joue pas)
    oi_explicit: bool = False        # NQ_OI_PATH donne
    oi_path: str = ""                # intérêt ouvert écrit par NQTickLogger (par defaut : nq-oi.csv a cote du fichier des transactions)
    gex: str = "NDX"                 # sous-jacent des options pour le GEX : NDX | QQQ | off
    gex_file: str = ""               # fichier JSON d'options a lire au lieu du telechargement
    gex_refresh_min: float = 15.0    # frequence de telechargement des options (minutes)
    # --- Tradovate (API officielle, TES identifiants ; voir README « Brancher Tradovate ») : identifiants lus SEULEMENT dans .env ---
    tv_user: str = ""
    tv_password: str = ""
    tv_cid: str = ""                 # « cid » de ta cle d'API Tradovate (si tu en as une)
    tv_secret: str = ""              # « sec » de ta cle d'API Tradovate
    tv_env: str = "live"             # live | demo
    tv_app_id: str = "NQScalpTerminal"
    tv_debug: bool = False           # journalise les trames recues (pour mettre au point)


def logger_candidates() -> list:
    """Emplacements par defaut du fichier ecrit par NQTickLogger (Documents\\NQ-Terminal\\nq-ticks.csv), OneDrive compris."""
    home = Path.home()
    out = [home / "Documents" / "NQ-Terminal" / "nq-ticks.csv", home / "OneDrive" / "Documents" / "NQ-Terminal" / "nq-ticks.csv"]
    out += sorted(home.glob("OneDrive*/Documents/NQ-Terminal/nq-ticks.csv"))
    return out


def find_logger_file():
    for p in logger_candidates():
        try:
            if p.is_file() and p.stat().st_size > 40:
                return str(p)
        except OSError:
            continue
    return None


def _flag(v) -> bool:
    return str(v).lower() not in ("0", "false", "non", "no", "")


def load_config(env_path: Path | None = None) -> Config:
    env = {}
    for f in env_sources(env_path or ROOT / ".env"):
        env.update(_load_env_file(f))
    env.update({k: v for k, v in os.environ.items() if k.startswith("NQ_") and v.strip()})      # variables du systeme : elles l'emportent
    c = Config()
    g = env.get
    c.source = g("NQ_SOURCE", c.source).lower()
    c.instrument = g("NQ_INSTRUMENT", c.instrument).upper()
    c.host = g("NQ_HOST", c.host)
    c.port = int(g("NQ_PORT", c.port))
    c.refresh_seconds = max(0.2, float(g("NQ_REFRESH_SECONDS", c.refresh_seconds)))
    c.display_tz = "et" if g("NQ_DISPLAY_TZ", c.display_tz).lower() in ("et", "ny", "newyork") else "paris"
    c.big_lot = max(0, int(float(g("NQ_BIG_LOT", c.big_lot))))
    c.zone_pts = max(1.0, float(g("NQ_ZONE_PTS", c.zone_pts)))
    c.history_days = max(3, min(40, int(float(g("NQ_HISTORY_DAYS", c.history_days)))))
    c.sim_days = max(2, min(c.history_days, 25, int(float(g("NQ_SIM_DAYS", c.sim_days)))))
    c.sim_start = g("NQ_SIM_START", c.sim_start)
    c.csv_path = g("NQ_CSV_PATH", c.csv_path)
    c.csv_tz = g("NQ_CSV_TZ", c.csv_tz).lower()
    c.csv_columns = g("NQ_CSV_COLUMNS", c.csv_columns)
    c.csv_buy_codes = tuple(x.strip() for x in g("NQ_CSV_BUY_CODES", "").split(",") if x.strip())
    c.csv_sell_codes = tuple(x.strip() for x in g("NQ_CSV_SELL_CODES", "").split(",") if x.strip())
    c.data_dir = g("NQ_DATA_DIR", c.data_dir)
    c.tv_user = g("TRADOVATE_USERNAME", "")
    c.tv_password = g("TRADOVATE_PASSWORD", "")
    c.tv_cid = g("TRADOVATE_CID", "")
    c.tv_secret = g("TRADOVATE_SECRET", "")
    c.tv_env = g("TRADOVATE_ENV", c.tv_env).lower()
    c.tv_app_id = g("TRADOVATE_APP_ID", c.tv_app_id)
    c.tv_debug = _flag(g("NQ_TRADOVATE_DEBUG", ""))
    c.source_explicit = "NQ_SOURCE" in env
    if not c.source_explicit:
        if c.csv_path:                                       # un chemin donne sans NQ_SOURCE : c'est ce fichier qu'on veut
            c.source = "csv"
        else:                                                # rien de choisi : les vraies donnees de NinjaTrader si l'enregistreur tourne
            found = find_logger_file()
            if found:
                c.source, c.csv_path, c.auto_source = "csv", found, True
    c.oi_explicit = bool(g("NQ_OI_PATH", ""))
    c.oi_path = g("NQ_OI_PATH", "") or (str(Path(c.csv_path).with_name("nq-oi.csv")) if c.csv_path and c.source == "csv" else "")
    gx = g("NQ_GEX", c.gex).upper()
    c.gex = gx if gx in ("NDX", "QQQ", "OFF") else "NDX"
    c.gex_file = g("NQ_GEX_FILE", c.gex_file)
    c.gex_refresh_min = max(5.0, float(g("NQ_GEX_REFRESH_MIN", c.gex_refresh_min)))
    return c


def validate(c: Config) -> list:
    """Problemes de configuration, en francais ([] si tout va bien)."""
    from engine.instruments import INSTRUMENTS
    bad = []
    if c.source not in ("simulated", "csv", "tradovate"):
        bad.append(f"NQ_SOURCE « {c.source} » inconnue : simulated, csv ou tradovate.")
    if c.source == "tradovate" and not (c.tv_user and c.tv_password):
        bad.append("NQ_SOURCE=tradovate demande TRADOVATE_USERNAME et TRADOVATE_PASSWORD dans .env.")
    if c.instrument not in INSTRUMENTS:
        bad.append(f"NQ_INSTRUMENT « {c.instrument} » inconnu : {', '.join(INSTRUMENTS)}.")
    if c.source == "csv" and not c.csv_path:
        bad.append("NQ_SOURCE=csv demande NQ_CSV_PATH (le chemin du fichier de transactions).")
    if c.sim_start:
        try:
            from datetime import datetime
            datetime.fromisoformat(c.sim_start.replace("Z", "+00:00"))
        except ValueError:
            bad.append(f"NQ_SIM_START « {c.sim_start} » illisible : écris par exemple 2026-10-12T15:40:00Z (heure UTC).")
    if c.csv_tz not in ("utc", "et", "paris"):
        bad.append(f"NQ_CSV_TZ « {c.csv_tz} » inconnu : utc, et ou paris.")
    return bad
