"""Couche d'ingestion des données réelles (V45).

Tout ce qui entre dans le terminal depuis une bourse ou un service public passe par ici :
  core      client HTTP commun : limite de débit par serveur (seau de jetons), reprises avec attente exponentielle et aléa, respect de
            « Retry-After », cache à durée de vie, nombres décimaux exacts, erreurs typées, état de santé de chaque source ;
  binance   perpétuels et comptant : transactions agrégées, bougies exactes, carnet, intérêt ouvert, financement, ratio long/short ;
  bybit     intérêt ouvert, financement, transactions publiques ;
  okx       intérêt ouvert, financement, transactions, paliers de marge ;
  deribit   chaîne d'options complète (résumé du carnet + instruments) ;
  onchain   réseau Bitcoin : mempool.space, CoinMetrics (API communautaire), blockchain.info ;
  hub       assemble ces sources et les flux en direct, nourrit le moteur exact (paquet quant) et répond à /api/quant.
Règles : aucune donnée fabriquée (une source en panne donne une erreur lisible, jamais un chiffre de remplacement) ; heures en
millisecondes UTC (quant.num.to_ms) ; prix et quantités lus du TEXTE de la bourse (jamais par un flottant)."""
from __future__ import annotations
