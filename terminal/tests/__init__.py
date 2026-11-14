from __future__ import annotations
import os

# V45 : les donnees fabriquees (source « simulated », carnets, flux et series d'essai) n'existent plus que pour les tests automatiques.
# Cette variable les autorise ici ; le terminal lance normalement ne la pose jamais.
os.environ.setdefault("LIQ_TEST_DOUBLES", "1")
