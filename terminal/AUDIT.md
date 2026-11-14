# Audit du terminal et plan d'architecture (V45)

Audit fait sur le code de la V44 (60 000 lignes), puis vérifié sur de vraies données : une journée entière de transactions Binance
(1 460 102 transactions BTC, 222 301 transactions SOL, archives publiques du 12 novembre 2026), la chaîne d'options Deribit en direct
(978 options), OKX, Coinbase, Bitstamp et Bybit en direct, mempool.space, CoinMetrics et blockchain.info.

## 1. Ce qui était déjà réel, et ce qui ne l'était pas

Le terminal lisait déjà des sources réelles partout (Binance, OKX, Bybit, Coinbase, Bitstamp, Deribit, Hyperliquid, FRED, Yahoo...).
Les défauts trouvés :

| N° | Constat | Gravité | État en V45 |
|----|---------|---------|-------------|
| 1 | Un mode « données simulées » pouvait être choisi dans les réglages, la ligne de commande et le fichier `.env` : prix, carnet, liquidations, options et macro fabriqués au hasard. | Haute | Retiré du produit. Les générateurs ne s'activent plus que pendant les tests automatiques (variable `LIQ_TEST_DOUBLES`). Ils restent dans les fichiers du code : leur déplacement dans le dossier `tests` est l'étape suivante. |
| 2 | Tous les prix et quantités étaient convertis en flottants binaires dès la lecture (`float("68000.10")`). Sur une journée de BTC, la somme des achats dérive de 3,6 × 10⁻⁷ pièce. Sans effet visible, mais ce n'est pas exact. | Moyenne | Nouveau paquet `quant` : entiers (unités de 10⁻⁸) et décimaux exacts. La dérive est supprimée. |
| 3 | Le CVD venait des bougies (volume acheteur agressif de Binance par bougie) : exact par bougie, mais pas transaction par transaction ; et un delta de remplacement (position de la clôture dans la bougie) quand la bougie n'a pas ce volume. | Moyenne | CVD transaction par transaction, contrôlé contre les bougies officielles. Le delta de remplacement reste utilisé par les backtests sur l'historique Bitstamp (constat 9). |
| 4 | Profil de volume : transactions réelles, mais rangées sur une grille de 0,03 % (environ 20 $ sur le BTC) puis regroupées en 30 à 160 lignes. Mesuré : POC à 5,67 $ du POC exact sur le BTC, 0,01 $ sur le SOL. | Faible | Profil exact au pas de l'empreinte (5 $ sur le BTC, 0,01 $ sur le SOL), zone de valeur en entiers. |
| 5 | Backtest : le financement était compté comme un coût constant de 0,01 % par 8 heures **dans les deux sens**. En réalité un short REÇOIT le financement quand il est positif : biais contre les shorts. | Haute | Financement réel publié, avec son signe (`quant.execution`). L'ancien calcul reste disponible pour relire les anciens rapports. |
| 6 | Backtest : glissement fixe de 0,02 %, quel que soit l'état du marché. Un stop touché dans une cascade s'exécute bien plus mal. | Moyenne | Glissement qui grandit avec l'agitation des 14 minutes précédentes, plus un terme d'impact si la profondeur est connue. C'est une hypothèse annoncée, pas une mesure. |
| 7 | Backtest : pas de Sortino, de Calmar, de durée du drawdown, de statistiques MAE / MFE, ni de Monte Carlo. | Moyenne | Ajoutés (`quant.metrics`), dont 1 000 tirages par permutation et 1 000 avec remise. |
| 8 | Aucun test ne prouvait l'absence de regard vers l'avenir. | Haute | Test ajouté : les décisions prises avant une date sont identiques quand on retire toutes les données qui suivent. Il passe. |
| 9 | Les backtests longs tournent sur l'historique Bitstamp (comptant, depuis 2013), dont les bougies n'ont pas le volume acheteur agressif : le CVD y est un remplacement. | Moyenne | Non corrigé : il faut rejouer les études sur les archives Binance (depuis 2019). À faire à l'étape suivante. |
| 10 | Pas de skew à 25 delta ; la volatilité implicite était celle de Deribit, sans contrôle. | Faible | Modèle de Black complet, volatilité recalculée de la prime, skew, butterfly. Contrôlé contre Deribit (voir 3). |
| 11 | Aucune donnée du réseau Bitcoin. | Faible | mempool.space, CoinMetrics, blockchain.info. |
| 12 | Reconnexion des flux : attente doublée jusqu'à 30 secondes, sans aléa ; les coupures n'étaient pas datées. | Moyenne | Attente exponentielle avec aléa jusqu'à 60 secondes, coupures datées, passage par proxy, port de secours. |
| 13 | Requêtes REST : pas de limite de débit commune ; le compteur de poids de Binance n'était pas lu. | Moyenne | Client commun : seau de jetons, « Retry-After », pause avant la limite de Binance, cache. |
| 14 | blockchain.info publie des frais négatifs (constaté le 14 novembre 2026). | Faible | Ces champs ne sont pas lus ; seules la difficulté et la puissance de calcul servent de second avis. |

## 2. Trois points du cahier des charges corrigés par les faits

- **« @aggTrade pour le vrai CVD tick par tick ».** Oui pour le total, non à la minute près. Une transaction agrégée des perpétuels
  ne porte qu'une heure pour toutes ses exécutions. Mesuré sur le BTC du 12 novembre : 1 275 minutes identiques à la bougie
  officielle, 165 décalées de quelques exécutions vers une minute voisine ; le total du jour est identique. Sur le comptant :
  1 440 minutes identiques sur 1 440. Le terminal remplace donc chaque minute fermée par la bougie officielle et surveille le
  résidu cumulé.
- **« @depth20@100ms ».** Ce flux ne donne que 20 niveaux, soit environ 2 $ de chaque côté sur le BTC : trop peu pour un déséquilibre
  pondéré par la distance ou des murs. Le terminal garde son carnet complet synchronisé (1 000 niveaux et mises à jour à 100 ms).
  La lecture de `depth20` existe (`ingest.binance.parse_depth20`) mais n'est pas utilisée.
- **« Interdiction des flottants pour les calculs critiques ».** Appliqué à l'argent, aux tailles, aux prix de bourse et aux
  volumes. Deux exceptions, annoncées dans le code : le modèle de Black (logarithme, exponentielle, loi normale : des nombres
  irrationnels, qu'aucun type décimal ne rend exacts ; erreur de 10⁻¹⁵) et les statistiques de performance (Sharpe, Sortino : des
  racines carrées de moyennes). Côté navigateur, aucun calcul financier n'est fait : `decimal.js` n'apporterait rien.

## 3. Ce qui a été vérifié sur de vraies données

| Preuve | Résultat |
|--------|----------|
| CVD exact, BTC perpétuel, 12/11/2026 | 1 460 102 transactions ; total du jour identique aux bougies officielles ; résidu au pire 0,036 % du volume pendant le jour |
| CVD exact, BTC comptant | 886 881 transactions ; 1 440 minutes identiques sur 1 440 |
| CVD exact, SOL perpétuel et comptant | totaux identiques ; comptant : 1 440 sur 1 440 |
| Volatilité implicite recalculée contre Deribit | 180 options hors de la monnaie ; écart médian de 0,002 à 0,02 point de volatilité selon l'instant, 0,2 au pire |
| Delta, vega, thêta contre le « ticker » de Deribit | écarts de 0,000 %, 0,000 % et 0,005 % ; gamma à 4,6 × 10⁻⁶ près (Deribit l'arrondit à 0,00001) |
| Difficulté du réseau : mempool.space contre blockchain.info | identique |
| Flux en direct Bybit, OKX, Coinbase, Bitstamp | messages réels reçus et lus (formats confirmés, ce que la V44 n'avait pas pu faire) |
| Pas de regard vers l'avenir | décisions identiques avec ou sans les données futures |

Non vérifié depuis la machine de développement : l'API et les flux en direct de Binance (refus par pays, HTTP 451) et l'API REST de
Bybit (refus par pays, HTTP 403). `python tools/check_sources.py` fait ces contrôles sur ton ordinateur.

## 4. Architecture

```
ingest/      COUCHE D'INGESTION (réseau)
  core.py        client HTTP : limite de débit, reprises exponentielles avec aléa, Retry-After, cache, nombres décimaux, erreurs typées
  binance.py     transactions agrégées, bougies exactes, carnet, intérêt ouvert, financement, ratio long / short
  venues.py      Bybit, OKX, Deribit
  onchain.py     mempool.space, CoinMetrics, blockchain.info
  hub.py         assemble les flux en direct et les sources périodiques, nourrit le moteur exact, répond à /api/quant
data/ws.py   client WebSocket : attente exponentielle avec aléa, coupures datées, proxy, port de secours
quant/       MOTEUR DE CALCUL EXACT (pur : ni réseau ni disque)
  num.py         décimal exact, unités entières, arrondi au pas, heures en millisecondes UTC
  perp.py        résultat, frais, financement, prix de liquidation, taille de position, seuil de rentabilité
  flow.py        CVD transaction par transaction, divergences, absorptions, plusieurs bourses, contrôle contre les bougies
  profile.py     profil de volume exact : POC, VAH, VAL, nœuds
  book.py        déséquilibre pondéré par la distance, murs, ordres retirés / exécutés / rechargés
  regime.py      régime de marché (prix + intérêt ouvert + financement + CVD perpétuels + CVD comptant)
  options.py     modèle de Black, volatilité implicite, skew 25 delta, max pain, gamma par strike
  metrics.py     Sharpe, Sortino, Calmar, facteur de profit, espérance, drawdown (profondeur et durée), MAE / MFE, Monte Carlo
  execution.py   frais, glissement dynamique, financement réel
engine/backtest.py   MOTEUR DE BACKTEST : utilise quant.execution et quant.metrics
web/quant.js         INTERFACE : onglet « Quant »
tools/check_sources.py        contrôle de chaque source et des formules sur ton ordinateur
tools/check_cvd_archive.py    preuve du CVD exact sur une journée entière d'archives
```

## 5. Étapes suivantes proposées

1. Déplacer physiquement les générateurs de données de test dans le dossier `tests`.
2. Rejouer les études de backtest sur les archives Binance (vrai CVD, financement réel) et afficher les nouvelles mesures dans
   l'onglet Backtest.
3. Brancher le CVD exact, les divergences et le régime de marché sur le graphique principal et sur les idées de trade.
4. Estimation des grappes de liquidation avec les paliers de marge réels (OKX et Bybit les publient).
