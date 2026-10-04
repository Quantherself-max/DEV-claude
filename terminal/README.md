# Liq Terminal (V4)

Un terminal **local**, qui tourne uniquement sur ton PC. Il rassemble :

- **Un espace de travail (menu à gauche)** : **Desk** (les graphiques), **Overview** (une carte par paire : prix, biais, niveaux essentiels, contexte, macro, dominance, Fear & Greed) et **Analyse** (biais, macro, dominance, plan de trade, lexique). Le menu se replie avec la flèche.
- **Trois graphiques synchronisés** (zoom et curseur liés) : **Principal** (bougies + niveaux essentiels), **Liquidité** (uniquement les poches : carte de chaleur, balayages, vraies liquidations) et **VWAP · AVWAP · Volume Profile** (uniquement ces niveaux). Boutons de disposition en haut du Desk : 1 graphique, Liquidité seule, VP seul, 2 ou 3 graphiques ; chaque panneau peut être agrandi.
- **Des volume profiles choisis par toi, selon ta timeframe** (voir « V4 » plus bas).
- **Une analyse sur l'historique le plus long possible** (depuis septembre 2019 quand la paire existait).
- **Le graphique, épuré.** Le mode **Essentiel** (par défaut) ne trace que les 2 zones les plus importantes au-dessus et en dessous du prix, avec leur probabilité d'atteinte. « Confluences » et « Tous » restent disponibles.
- **Le prix en temps réel.** Prix et bougie en cours bougent à chaque transaction Binance. Le prix **Coinbase** (le marché de ton graphique TradingView) s'affiche à côté, avec l'écart.
- **Une vue Liquidité** (second onglet, même graphique) : carte de chaleur de l'historique des poches de liquidation, balayages, **vraies liquidations** Binance en bulles, profil actuel sur le bord droit.
- **Une section Analyse sous le graphique** :
  - **Biais & probabilités** : un biais qui n'est une probabilité que si le modèle a prouvé un avantage hors échantillon ;
  - **Macro & annonces** : calendrier avec consensus, réaction mesurée des marchés aux annonces passées, dollar / taux / indices / VIX / or ;
  - **Dominance BTC / alts** : régime, probabilités historiques, bêta de ta paire face au BTC ;
  - **Plan de trade** : probabilité de toucher le TP avant le stop, liquidation selon ton levier ;
  - **Lexique** qui explique chaque élément du graphique.
- Tout ce qui existait en V2 : niveaux (VWAP et bandes ±2σ, ouvertures, plus hauts/bas, POC/VAH/VAL, POC nus, nombres ronds), poches de liquidation estimées via l'Open Interest, confluences avec probabilités, contexte (OI, CVD, funding, long/short, prime Coinbase), alertes Telegram.

> Estimations et statistiques historiques, à titre informatif : ce n'est pas un conseil financier.
> Les poches de liquidation sont un **proxy** (sauf les bulles « réelles »). La règle « aimant » est une **hypothèse non validée**.

## Démarrage en 3 étapes

1. **Télécharger.** Ouvre ce lien et dézippe le fichier :
   https://github.com/Quantherself-max/DEV-claude/archive/refs/heads/claude/festive-gates-viq9oo.zip
   **Extrais tout le ZIP** (clic droit > « Extraire tout… », ou WinRAR > « Extraire ici ») : le lanceur ne marche pas si tu l'ouvres depuis l'intérieur du ZIP. Ouvre ensuite le dossier extrait, puis le dossier `terminal`.
2. **Lancer.** Double-clique sur le lanceur de ton système :
   - Windows : `Lancer-Terminal-Windows.bat` ;
   - Mac : `Lancer-Terminal-Mac.command`. La première fois, fais clic droit > Ouvrir.

   Si Python n'est pas installé, le lanceur ouvre la page de téléchargement. Installe Python, en cochant **« Add Python to PATH »** sous Windows, puis double-clique de nouveau sur le lanceur.

   Le terminal s'ouvre dans ton navigateur, à l'adresse http://127.0.0.1:8765/ . Une fenêtre noire reste ouverte : c'est le programme. Ferme-la pour arrêter le terminal.
   Le terminal démarre directement sur les **vraies données Binance**. Le premier chargement de l'historique prend 1 à 2 minutes : un bandeau l'indique pendant ce temps.
3. **Régler.** Clique sur **⚙** (réglages), en haut à droite, ou sur « Réglages » en bas du menu de gauche :
   - **Source** : « Tester la connexion Binance » vérifie que ton PC accède bien aux données. Le mode **Simulées** (prix fictifs) ne sert qu'à essayer sans internet.
   - **Telegram** : suis les 4 petites étapes affichées dans la fenêtre.
     - Crée un bot avec @BotFather et colle son token.
     - Envoie « bonjour » à ton bot, puis clique « Trouver mon chat id ».
     - Clique « Envoyer un message de test ».
   - Clique **Enregistrer**. Le terminal applique les changements tout de suite, sans redémarrage.

Si Binance est injoignable depuis ton PC, un bandeau rouge l'affiche avec un bouton « Tester la connexion ». Si tu choisis un jour le mode simulé, un bandeau orange te rappelle que les prix sont fictifs.

**Tout est réel en mode Binance.** Les bougies, le volume acheteur, l'Open Interest, le funding et les ratios viennent de Binance. L'historique utilisé pour les probabilités, ce sont les vraies bougies passées de la paire. Le **prix et la bougie en cours arrivent en temps réel** : le navigateur se branche directement sur le flux des transactions Binance (badge **● TEMPS RÉEL**). Les niveaux, les poches, les probabilités et les alertes sont recalculés toutes les 10 secondes (réglable avec `TERMINAL_REFRESH_SECONDS` dans `.env`). Si le flux ne passe pas, le badge affiche **● PRIX ~1 s** : le prix est alors redemandé chaque seconde et le flux se reconnecte tout seul.

**Comparer avec TradingView.** Le terminal affiche le **perpétuel Binance** (BTCUSDT, SOLUSDT). Un graphique « Bitcoin / Dollar · Coinbase » est un autre marché, le spot américain : l'écart de quelques dizaines de dollars est normal, même sans aucun retard. L'onglet Contexte l'affiche (« Prime Coinbase »). Pour comparer les mêmes prix, ouvre `BINANCE:BTCUSDT.P` ou `BINANCE:SOLUSDT.P` sur TradingView.

## Lire le terminal

**Onglet Niveaux.** Les zones de confluence sont classées autour du prix : ▲ au-dessus, ▼ en dessous. Chaque ligne affiche :
- la distance au prix, en % et en ATR ;
- le score : ● = une source ;
- `x % d'y aller en 24 h` : la fréquence à laquelle le prix a parcouru cette distance en 24 h dans l'historique de la paire ;
- `si touchée : rebond y %` : le taux de rebond des zones qui ont le même nombre de sources ;
- une étiquette qui compare ce taux au hasard :
  - **mieux que le hasard** : l'intervalle de confiance est entièrement au-dessus des niveaux tirés au sort ;
  - **≈ hasard** : on ne peut pas dire que le niveau compte ;
  - **moins bien** : l'intervalle de confiance est entièrement en dessous.

Clique une zone, une poche ou un niveau pour ouvrir le **Détail**. Il affiche :
- la composition de la zone ;
- les chances d'atteinte à 4 h, 24 h et 72 h ;
- le rebond avec son intervalle de confiance et le nombre de tests ;
- les statistiques de chaque source.

**Définition du rebond.** Le prix touche le niveau. Dans les 24 h qui suivent, il s'en éloigne de 1,5 ATR (1h) du bon côté avant de le casser de 1,5 ATR. Sur un marché sans mémoire, ce taux vaut environ 50 %. C'est pourquoi on le compare toujours au « Hasard (témoin) » : des niveaux tirés au sort et mesurés exactement de la même façon.

**Onglet Contexte.**
- **Régime 4 h** : il croise la variation du prix et celle de l'OI. Par exemple :
  - hausse + OI en hausse = nouvelles positions ;
  - hausse + OI en baisse = rachat de shorts.
- **CVD** : volume acheteur agressif moins volume vendeur, avec les divergences entre prix et CVD.
- **Funding** : la valeur actuelle comparée à la moyenne sur 7 jours.
- **Basis** : l'écart entre le perp et l'index.
- **Ratios long/short** : ceux de la foule et ceux des gros comptes.
- **Prime Coinbase** : l'écart de prix entre Coinbase et Binance spot.
- **Liquidations estimées** : la part de longs et de shorts encore ouvertes.

**Onglet Stats.** Il montre le taux de rebond :
- par type de niveau, en support ou en résistance ;
- par nombre de sources ;
- selon le flux de la bougie de contact.

Pour le flux, on compare le taux observé au taux « attendu » si le flux n'avait aucun effet.

En bas de l'onglet, le **journal des poches balayées** indique, pour chaque poche balayée, si le prix a rebondi ou a continué.

**Onglet Alertes.** Il affiche le journal des messages envoyés.

## Alertes Telegram

- **Nouvelle confluence.** Elle est envoyée si la zone a au moins *score minimum* sources (3 par défaut ; une poche AIMANT compte +1) et si elle est à moins de 6 ATR du prix. Ensuite, la même zone reste silencieuse pendant la pause choisie (6 h par défaut).
- **Approche.** Elle est envoyée quand le prix arrive à 0,5 ATR d'une zone qualifiante.
- **Poche balayée.** Elle est envoyée quand une poche qui représente au moins 15 % des liquidations estimées de son côté est touchée.
- **Contenu du message.** Chaque message contient les probabilités : chance d'atteinte en 24 h et rebond comparé au hasard.
- **Démarrage.** Au démarrage, le terminal envoie un seul résumé, sans rafale. Il envoie au maximum 6 alertes par heure.
- **Condition.** Le terminal doit tourner, donc le PC doit être allumé.

## Ce qui est nouveau en V4

### Workspace et graphiques séparés
- Le menu de gauche range les écrans : **Desk**, **Overview**, **Analyse** (Biais, Macro, Dominance, Plan de trade, Lexique). L'adresse du navigateur suit l'écran (`#/desk`, `#/overview`, `#/analysis/macro`…) : tu peux mettre un écran en favori.
- Sur le Desk, trois panneaux : **Principal**, **Liquidité** (uniquement les poches : carte de chaleur ou barres, balayages, vraies liquidations) et **VWAP · AVWAP · VP** (uniquement VWAP jour / semaine / mois / année avec bandes ±2σ, VWAP ancrées, profils de volume). Zoom et curseur sont synchronisés entre les panneaux. Tes choix (disposition, panneau latéral, options) sont mémorisés dans le navigateur.
- Chaque panneau a ses propres options (cases à cocher dans son en-tête).

### Volume profiles selon la timeframe
- Onglet **VP** (panneau de droite). Le choix **Auto** prend trois fenêtres adaptées à ta timeframe : 5 min → 3, 7, 14 jours ; 15 min → 7, 14, 30 jours ; 1 h → 30, 90, 180 jours ; 4 h → 90, 180, 365 jours ; 1 j → 1, 2, 4 ans. Chacune donne **POC, VAH, VAL et HVN**.
- Tu peux **ajouter tes propres profils** (8 au maximum) : *glissant* (N derniers jours), *depuis une date*, ou *période calendaire* (jour, semaine, mois, trimestre, année, courante ou précédente). Ils sont enregistrés dans `data_local/vps.json`.
- Tous ces profils deviennent des **niveaux supplémentaires dans les confluences** (type `xVP`), avec les mêmes probabilités et la même comparaison au hasard que les autres niveaux. Les niveaux trop éloignés du prix sont ignorés pour ne pas faire de bruit.
- **VWAP ancrées** : ajoute une date (6 au maximum) : la VWAP part de cette date. Deux ancrages automatiques existent aussi : début de l'année précédente et du mois précédent.

### Historique le plus long possible
- Bougies 1h chargées **depuis le 1er septembre 2019** (ou la date de cotation de la paire), mises en cache dans `data_local/` (`h1_*.json.gz`) : seul le manque est redemandé aux lancements suivants. Le **premier lancement télécharge tout** : compte quelques minutes, un bandeau l'indique.
- Réglage : `TERMINAL_HISTORY_YEARS` dans `.env` (0 = le plus long possible ; 2 ou 3 pour un démarrage plus léger).
- Les probabilités (atteinte, rebond), le biais (fenêtre d'entraînement glissante de 3 ans, validation en avançant), les corrélations macro (30 j, 90 j, 1 an), les bêtas face au BTC et les statistiques Fear & Greed utilisent cet historique. Le biais calculé est enregistré (`bias_*.json`) et réutilisé s'il a moins de 24 h.
- Limite de Binance : l'Open Interest 5 min et les bougies 5 min ne remontent qu'à **~29 jours** : la carte de chaleur des poches de liquidation ne peut pas remonter plus loin (le terminal accumule ensuite ses propres instantanés).

## Ce qui est nouveau en V3

### Niveaux essentiels
Chaque zone reçoit une **importance** : nombre de sources distinctes, poche AIMANT, type de niveau qui bat le hasard dans l'historique de la paire, proximité du prix. Le mode Essentiel garde les 2 meilleures de chaque côté (score ≥ 3). Une ★ dans la liste de droite indique les zones tracées. Chaque zone du graphique porte une étiquette : sens, prix, score, probabilité d'atteinte en 24 h.

### Liquidité améliorée
- Les barres de poches partent maintenant de **l'instant où la poche s'est formée** (un trait vertical marque la naissance) et non plus d'une longueur arbitraire. Un balayage remet l'âge à zéro.
- La vue **Liquidité** affiche la carte de chaleur (une colonne par heure, bandes de 0,15 % du prix), avec 24 h, 3 j, 7 j ou 29 j d'historique. Survole une case pour lire la bande, l'heure et la taille estimée en dollars.
- Les **vraies liquidations** viennent du flux public Binance `forceOrder`. Binance n'envoie que la plus grosse par seconde et seulement depuis l'ouverture du terminal ; elles sont gardées dans `data_local/`.

### Macro
- **Calendrier** : le flux gratuit de ForexFactory donne le consensus et le chiffre précédent. Il ne donne **pas** le chiffre publié. La « surprise » est donc lue dans la réaction du **rendement 10 ans** et du **dollar** dans les 15 minutes suivantes, comparée à celle du BTC. Ces mesures sont archivées (`data_local/macro_events.json`) : la « réaction type du BTC » par type d'annonce se construit avec le temps.
- **Actifs de référence** (Yahoo Finance, futures presque 24 h) : dollar, taux 10 ans, S&P 500, Nasdaq, VIX, or. Le lien avec le BTC est mesuré sur 30 jours.
- **Lecture macro** : phrases construites uniquement à partir de ces chiffres. Ce n'est pas une IA qui improvise : tout est vérifiable.
- **Alertes Telegram** : une alerte environ 1 h avant une annonce majeure (consensus et scénarios), puis un bilan de la réaction du marché.

### Dominance BTC / alts
Dominance officielle (CoinGecko, repli CoinPaprika) et **panier alts/BTC** construit avec l'historique réel Binance spot (ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK cotés en BTC). Le régime croise ce panier et la direction du BTC. Les probabilités viennent de ~2,7 ans de bougies quotidiennes.

### Biais statistique « validé »
Régression logistique sur 10 variables calculées à chaque clôture horaire (momentum, CVD réel, VWAP jour/semaine, volatilité, position 72 h, funding). Elle est **validée hors échantillon** (entraînée sur le passé, testée sur les 30 jours suivants, en avançant), avec intervalle de confiance et calibration. Si elle ne bat pas le hasard sur ta paire, le terminal l'écrit et n'en tire **aucun** biais : c'est le résultat le plus fréquent sur des marchés liquides, et c'est une information utile.

### Latence
- Prix et bougie : flux WebSocket direct dans le navigateur (badge ● TEMPS RÉEL). Secours automatique si le flux ne passe pas : le serveur redonne le prix chaque seconde (badge ● PRIX ~1 s).
- Le serveur écoute aussi le flux : ses alertes d'approche utilisent le dernier prix échangé.
- Niveaux, poches et alertes recalculés toutes les 5 secondes (`TERMINAL_REFRESH_SECONDS`).
- **Pourquoi ton prix TradingView diffère** : ton graphique « Bitcoin / Dollar · Coinbase » est le marché spot américain, le terminal affiche le **perpétuel Binance**. L'écart de quelques dizaines de dollars est normal. Le prix Coinbase est affiché à côté pour comparer.

## Sécurité

- Le serveur n'écoute que sur ta machine (`127.0.0.1`). Il refuse les requêtes qui viennent d'un autre site : vérification de l'en-tête Host et jeton de session.
- Les réglages sont enregistrés dans le fichier `.env` du dossier `terminal`. Ce fichier n'est lisible que par toi et il est exclu de git. Ne le partage jamais : il contient ton token Telegram.
- Une fois enregistré, le token Telegram n'est plus jamais renvoyé à l'interface. Seuls ses 4 derniers caractères sont affichés.

## Commandes facultatives

```
python run.py --selftest          teste Binance (et Telegram s'il est configuré)
python run.py --source binance    force la source pour ce lancement
python run.py --port 8800         change le port
python run.py --no-browser        n'ouvre pas le navigateur
python -m unittest discover -s tests     tests automatiques
```

Sous Windows, remplace `python` par `py`. Tous les réglages peuvent aussi s'écrire à la main dans `.env` (voir `config.example.env`).

## Données

Tout est gratuit et sans compte ni clé. Si une source tombe en panne, les autres continuent et l'erreur s'affiche (état des sources, onglet Macro).

| Donnée | Source | Profondeur |
|---|---|---|
| Bougies 1h, volume acheteur agressif | Binance futures | Depuis septembre 2019 (ou la cotation de la paire), en cache disque |
| Bougies 5 min, Open Interest 5 min | Binance futures | Environ 29 jours (limite Binance) |
| Funding, premium index, ratios long/short | Binance futures | Funding : tout l'historique ; ratios : récent |
| Transactions et liquidations en direct | WebSocket Binance futures | Temps réel |
| Prix Coinbase | WebSocket Coinbase | Temps réel |
| Calendrier économique (consensus) | ForexFactory (flux public) | Semaine en cours et suivante, archivé ensuite |
| Dollar, taux 10 ans, indices, VIX, or | Yahoo Finance | 5 jours en 5 min, 10 ans en quotidien |
| Dominance BTC | CoinGecko (repli CoinPaprika) | Historique construit par le terminal |
| Paires alts/BTC | Binance spot | 30 jours en 1h, plusieurs années en quotidien |
| Fear & Greed | alternative.me | Depuis 2018 |

Les probabilités et le biais statistique sont recalculés toutes les 6 heures, en tâche de fond (de 30 secondes à 2 minutes selon la machine).

## Structure

```
run.py              point d'entrée
Lancer-Terminal-*   lanceurs à double-cliquer
config.py           configuration (.env) et écriture des réglages
engine/             calculs : profils de volume (auto et choisis), séries VWAP / AVWAP, périodes, POC nus, poches de
                    liquidation, confluences, ATR, statistiques (rebond / cassure, atteinte, balayages, Wilson), macro,
                    dominance, biais validé en avançant, synthèse
data/               sources : simulée et Binance ; historique en mémoire et contexte (funding, L/S, spot, Coinbase)
alerts/             règles d'alerte, envoi Telegram
service.py          relie les données et les moteurs, fabrique l'état JSON
server.py           serveur local : API, réglages, sécurité
web/                interface : index.html + style.css ; app.js (Desk, état, alertes), panels.js (les trois graphiques),
                    overview.js (vue d'ensemble), analysis.js et charts.js (analyse, graphiques SVG) ;
                    TradingView Lightweight Charts (vendor/)
tests/              tests automatiques (plus de cent)
```

## Limites connues

- **Binance et Telegram.** L'adaptateur Binance et l'envoi Telegram ont été écrits d'après la documentation. Ils ont été testés contre des **faux serveurs** qui imitent Binance et Telegram. Leur premier essai réel se fait sur ton PC, avec les boutons de test des Réglages.
- **Poches de liquidation.** Elles reposent sur des hypothèses :
  - poids de levier : 10 % à 100x, 20 % à 50x, 30 % à 25x, 40 % à 10x ;
  - marge de maintenance : 0,4 % ;
  - répartition entre longs et shorts selon le volume acheteur agressif.

  Elles ne sont pas calibrées sur de vraies liquidations.
- **Probabilités.** Ce sont des fréquences passées sur la même paire. Elles ne garantissent rien pour l'avenir. Le nombre de tests (`n`) et l'intervalle de confiance indiquent leur fiabilité. Sur les données simulées, tout est proche du hasard : c'est normal, le marché simulé n'a pas de mémoire.
- **Calendrier et macro.** Le flux gratuit ne contient pas le chiffre publié (seulement consensus et précédent) : la surprise est lue dans les taux et le dollar, ce qui est plus fiable mais ne remplace pas le chiffre. Yahoo Finance peut limiter les requêtes ; le terminal le signale et réessaie.
- **Biais.** Un biais « neutre » ou de « faible confiance » est un résultat, pas un défaut. Sur BTC et SOL en 1h, les variables classiques n'offrent le plus souvent qu'un avantage minuscule ou nul.
- **Flux temps réel.** Les adresses WebSocket de Binance (`/market`) et de Coinbase ont été vérifiées dans leur documentation mais pas testées en conditions réelles depuis cet environnement. Si le badge reste sur ● PRIX ~1 s, le terminal reste utilisable.
- **Historique long.** Il est téléchargé au premier lancement (quelques minutes) puis mis en cache. L'Open Interest et les bougies 5 min restent limités à ~29 jours par Binance : les poches de liquidation et la carte de chaleur ne peuvent pas être calculées plus loin. Les profils de volume, les VWAP et les statistiques, eux, utilisent tout l'historique 1h.
- **Volume profiles.** Ils sont construits à partir des bougies 1h (volume réparti sur la plage haut-bas de chaque bougie), pas des transactions : la résolution est inférieure à celle d'un profil TradingView calculé sur des bougies 1 minute.
- **À venir.** Flux ETF et on-chain si tu en as besoin.
