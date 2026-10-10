#!/bin/bash
# Installe le Liq Terminal comme SERVICE PERMANENT sur un serveur Linux (Ubuntu 22.04 / 24.04, Debian 12, Raspberry Pi OS).
# Il tourne alors 24 h/24 sans ton ordinateur et t'envoie les idees de trade sur Telegram.
#
# Utilisation (voir GUIDE.md) : depuis le dossier extrait du ZIP, sur le serveur, en root :
#     bash terminal/serveur/installer-serveur.sh
# Relancer le meme script avec un ZIP plus recent = mise a jour (le .env et l'historique data_local sont gardes).
set -euo pipefail

DIR="${LIQ_DIR:-/opt/liq-terminal}"          # ou le terminal est installe
SVC_USER="liq"                               # utilisateur dedie, sans mot de passe ni acces distant
TEST="${LIQ_TEST:-0}"                        # 1 = essai sans apt / utilisateur / systemd (tests automatiques)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$(cd "$HERE/.." && pwd)"                # le dossier « terminal » de ce ZIP

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { printf '\033[31mERREUR : %s\033[0m\n' "$*" >&2; exit 1; }

[ -f "$SRC/run.py" ] || die "run.py introuvable : lance ce script depuis le dossier extrait du ZIP (terminal/serveur/installer-serveur.sh)."
if [ "$TEST" != "1" ]; then
  [ "$(id -u)" -eq 0 ] || die "lance ce script en root (ou avec sudo)."
  command -v apt-get >/dev/null 2>&1 || die "ce script prevoit Ubuntu / Debian / Raspberry Pi OS (apt)."
  command -v systemctl >/dev/null 2>&1 || die "systemd est necessaire."
fi

say "1/5  Programmes necessaires (Python 3)"
if [ "$TEST" != "1" ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3 ca-certificates >/dev/null
fi
PY="$(command -v python3)" || die "python3 introuvable."
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "Python 3.10 ou plus recent est necessaire ($("$PY" -V)). Choisis Ubuntu 22.04 / 24.04 ou Debian 12."
echo "  OK : $("$PY" -V)"

say "2/5  Copie du programme dans $DIR"
mkdir -p "$DIR/terminal"
for item in "$SRC"/*; do
  name="$(basename "$item")"
  [ "$name" = "data_local" ] && continue          # l'historique deja telecharge est garde
  [ "$name" = "serveur" ] && { rm -rf "$DIR/terminal/serveur"; cp -a "$item" "$DIR/terminal/serveur"; continue; }
  rm -rf "$DIR/terminal/$name"
  cp -a "$item" "$DIR/terminal/$name"
done
find "$DIR/terminal" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
echo "  OK"

say "3/5  Reglages Telegram (.env)"
ENVF="$DIR/terminal/.env"
if [ -f "$ENVF" ]; then
  echo "  Le fichier .env existe deja : il est conserve tel quel."
else
  tty_in=/dev/null; [ -r /dev/tty ] && tty_in=/dev/tty
  TOKEN="${TELEGRAM_BOT_TOKEN:-}"; CHAT="${TELEGRAM_CHAT_ID:-}"
  if [ -z "$TOKEN" ] && [ "$tty_in" != /dev/null ]; then
    printf "  Colle le token de ton bot Telegram (rien ne s'affiche en tapant), puis Entree : "
    IFS= read -r -s TOKEN < "$tty_in" || TOKEN=""; echo
  fi
  if [ -z "$CHAT" ] && [ "$tty_in" != /dev/null ]; then
    printf "  Colle ton chat id Telegram (un nombre), puis Entree : "
    IFS= read -r CHAT < "$tty_in" || CHAT=""
  fi
  case "$TOKEN" in *:*) ;; *) echo "  (!) Le token ne ressemble pas a 123456:ABC... : tu pourras le corriger dans $ENVF" ;; esac
  case "$CHAT" in ''|*[!0-9-]*) echo "  (!) Le chat id doit etre un nombre : tu pourras le corriger dans $ENVF" ;; esac
  umask 077
  {
    echo "# Cree par installer-serveur.sh. Ne partage jamais ce fichier : il contient ton token Telegram."
    echo "TERMINAL_SOURCE=binance"
    echo "TELEGRAM_BOT_TOKEN=$TOKEN"
    echo "TELEGRAM_CHAT_ID=$CHAT"
    echo "TERMINAL_ALERT_MODE=ideas"
  } > "$ENVF"
  echo "  OK : $ENVF cree (lisible par root et par l'utilisateur du service seulement)."
fi
chmod 600 "$ENVF"

if [ "$TEST" = "1" ]; then
  say "Mode essai : utilisateur et service systemd non crees."
  echo "Installation copiee dans $DIR/terminal"
  exit 0
fi

say "4/5  Utilisateur dedie et droits"
id "$SVC_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DIR" --shell /usr/sbin/nologin "$SVC_USER"
chown -R "$SVC_USER":"$SVC_USER" "$DIR"
echo "  OK"

say "5/5  Service permanent (demarre tout seul, redemarre apres une panne ou un redemarrage du serveur)"
cat > /etc/systemd/system/liq-terminal.service <<UNIT
[Unit]
Description=Liq Terminal (idees de trade sur Telegram)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SVC_USER
WorkingDirectory=$DIR/terminal
ExecStart=$PY $DIR/terminal/run.py --no-browser
Restart=always
RestartSec=15
Environment=PYTHONUNBUFFERED=1
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable liq-terminal >/dev/null 2>&1
systemctl restart liq-terminal
sleep 6
if systemctl is-active --quiet liq-terminal; then
  echo "  OK : le terminal tourne."
else
  echo "  Le service n'a pas demarre. Regarde : journalctl -u liq-terminal -n 50 --no-pager"
fi

cat <<'FIN'

========================================================================
  Termine. Le terminal tourne maintenant sur ce serveur, 24 h/24.
  Dans quelques secondes, tu dois recevoir sur Telegram le message :
  « Terminal demarre. Tu ne recevras que les idees de trade ... »

  Premier lancement : le telechargement de l'historique (depuis 2019)
  prend quelques minutes ; les idees n'arrivent qu'ensuite.

  Commandes utiles :
    journalctl -u liq-terminal -f        voir ce que fait le terminal
    systemctl status liq-terminal        etat
    systemctl restart liq-terminal       redemarrer
    systemctl stop liq-terminal          arreter

  IMPORTANT : arrete le terminal de ton ordinateur (ou mets
  TERMINAL_SIGNALS=0 dans son .env), sinon tu recevras chaque idee en double.
========================================================================
FIN
