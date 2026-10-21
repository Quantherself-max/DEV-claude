#!/bin/bash
# Double-clique sur ce fichier pour lancer le terminal.
# La premiere fois, si le Mac refuse de l'ouvrir : Reglages Systeme > Confidentialite et securite > « Ouvrir quand meme »
# (ou clic droit > Ouvrir sur les macOS plus anciens).
cd "$(dirname "$0")" || exit 1
if [ ! -f run.py ]; then
  echo "Le terminal a ete lance sans le reste du programme (fichier ZIP pas extrait ?)."
  echo "Double-clique d'abord sur le ZIP pour l'extraire, puis ouvre le dossier terminal et relance ce fichier."
  read -r -p "Appuie sur Entree pour fermer..."
  exit 1
fi
# V34.2 : le Python le plus recent du Mac (python.org, Homebrew, puis celui d'Apple), au moins 3.9. Le « python3 » d'Apple sans les outils
# de developpement n'est qu'un raccourci qui propose de les installer : il echoue au test et on passe au suivant.
PY=""
for c in python3.14 python3.13 python3.12 python3.11 python3.10 \
         /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    PY="$c"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Aucun Python 3 utilisable sur ce Mac (il faut la version 3.9 ou plus recente)."
  echo "1) Installe-le depuis la page qui va s'ouvrir (bouton « Download Python »)."
  echo "2) Puis double-clique de nouveau sur ce fichier."
  open "https://www.python.org/downloads/macos/"
  read -r -p "Appuie sur Entree pour fermer..."
  exit 1
fi
echo "Python utilise : $("$PY" --version 2>&1) ($(command -v "$PY"))"
"$PY" run.py
echo
echo "Le terminal s'est arrete. Si un message d'erreur est affiche au-dessus, fais-en une capture d'ecran."
read -r -p "Appuie sur Entree pour fermer..."
