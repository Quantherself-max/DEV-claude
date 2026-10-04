#!/bin/bash
# Double-clique sur ce fichier pour lancer le terminal (la premiere fois : clic droit > Ouvrir).
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  python3 run.py
else
  echo "Python 3 n'est pas installe sur ce Mac."
  echo "1) Installe-le depuis la page qui va s'ouvrir.  2) Puis double-clique de nouveau sur ce fichier."
  open "https://www.python.org/downloads/"
fi
read -r -p "Appuie sur Entree pour fermer..."
