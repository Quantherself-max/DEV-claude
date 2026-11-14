"""Moteur de calcul exact (V45).

Règle du paquet : tout ce qui est de l'argent, une taille, un prix de bourse ou un volume se calcule en décimal exact (`decimal.Decimal`)
ou en entiers (unités de 10^-8), jamais en nombre flottant binaire. Les textes envoyés par les bourses (« 68224.47 », « 0.001 ») sont lus
tels quels, sans passer par un flottant. Les flottants ne servent qu'à deux endroits, annoncés dans chaque module :
  - les fonctions transcendantes de la valorisation d'options (logarithme, exponentielle, loi normale) : leur erreur (10^-15 en relatif)
    est des milliards de fois plus petite que l'erreur du modèle lui-même ;
  - les statistiques de performance (Sharpe, Sortino...) : ce sont des racines carrées et des moyennes de rendements, pas des montants.
Modules PURS : aucun accès au réseau ni au disque (la lecture des données est dans le paquet `ingest`)."""
from __future__ import annotations
