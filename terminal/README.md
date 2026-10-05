# Liq Terminal (V6)

Un terminal **local**, qui tourne uniquement sur ton PC. Il rassemble :

- **Un banc d'essai historique honnête** (V6, page **Backtest**) : la stratégie du terminal est rejouée sur 13 ans de BTC (bougies 1 minute), avec frais, contre des entrées au hasard, par période. Résultat : **le seul filtre qui compte est la tendance de fond** (voir « V6 » plus bas).
- **Des idées de trade rares, envoyées sur Telegram** (V5) : achat ou vente sur une zone où plusieurs niveaux importants (VWAP, VWAP ancrés, profils de volume, de l'heure à l'année) et des poches de liquidités se superposent, avec entrée, stop, deux objectifs, probabilités et une explication complète sans abréviation. Cinq idées par semaine au maximum, réglable (voir « V5 » plus bas).
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

## Ce qui est nouveau en V6 : on a mesuré, et on a gardé ce qui tient

### Le résultat, sans détour
La stratégie du terminal (confluences de niveaux, VWAP et VWAP ancrés, profils de volume, poches de liquidité, balayages, flux d'ordres) a été rejouée **minute par minute sur du BTC réel de 2013 à octobre 2026** (données Bitstamp, 67 000 idées simulées), avec frais, glissement et financement, **uniquement avec ce qui était connu à chaque instant**. Ce que ça donne (en « fois le risque pris » par trade, après frais) :

| | par trade | trades |
|---|---|---|
| Idées dans le sens de la tendance de fond (cours au-dessus des moyennes de 50 et 200 jours pour acheter, sous les deux pour vendre) | **+0,15** | 1 302 |
| Idées à contre-courant | **−0,12** | 1 588 |
| Tendance indécise (entre les deux moyennes) | +0,02 | 628 |
| Ancienne règle du terminal (sans filtre de tendance) | −0,04 | 1 787 |
| **Règle actuelle** (score ≥ 60 **et** dans le sens de la tendance) | **+0,13** (intervalle à 90 % : +0,06 à +0,21) | 1 202 |

- **Le filtre de tendance est le seul qui résiste** : même signe sur chaque grande période (2013-2016, qui n'avait pas servi à le choisir, 2017-2021, 2022-2026) et pour sept réglages différents des moyennes. C'est une règle de bon sens (ne pas lutter contre le marché), pas une découverte magique.
- **Mais l'avantage s'est affaibli** : +0,23 sur 2013-2016, +0,21 sur 2017-2021, **−0,01 sur 2022-2026** pour la règle actuelle. Sur la période récente, filtrer la tendance évite surtout les pertes ; il n'y a plus d'avantage démontré. Le marché devient plus mûr.
- **Les niveaux n'ajoutent rien de démontré.** Face à des entrées *au hasard prises dans la même tendance* (+0,11 en moyenne), la règle fait à peine mieux (+0,13) : la tendance explique l'essentiel. Balayages de liquidité, écarts au VWAP, contacts avec un VWAP ancré, divergences du CVD : pris un par un, **aucun ne montre un effet à la fois solide et stable** (la page Backtest donne le tableau complet, 48 signaux testés).
- **Les frais pèsent lourd** : environ 0,09 fois le risque par trade. Avant frais, la règle rapporte +0,22.
- **Ce n'est pas une machine à cash.** Avec 1 % du capital risqué par trade, la règle actuelle fait environ +11 % par an sur 13 ans (baisse maximale 32 %), très loin du bitcoin lui-même (×6 500), mais avec une baisse maximale trois fois plus faible et 39 % du temps en position. Un résultat passé n'est pas une garantie.

### Ce qui change dans le terminal
- **Filtre de tendance de fond** (⚙ section 4, `TERMINAL_SIGNAL_TREND_GATE=1`, activé par défaut) : une idée à contre-courant ou en tendance indécise n'est plus envoyée sur Telegram. Elle reste visible dans l'onglet Idées avec la raison. Les chiffres ci-dessus sont cités dans chaque idée.
- **Page Backtest** (menu de gauche) : verdict, tendance de fond par période, courbes de capital, **comparaison des raisonnements** (21 façons de choisir les idées, avec intervalle de confiance et résultat par période), étude outil par outil, test de réaction des zones, poids des frais, méthode et limites.
- **Poches d'ordres d'arrêt visibles dans le prix** (plus haut / plus bas de la veille, de la semaine, du mois ; creux et sommets récents ; niveaux égaux) : elles existent sur tout l'historique, donc elles se testent. Tracées sur le graphique principal (case « Plus hauts / bas »), listées dans le panneau Niveaux, utilisées comme sources de confluence, comme poches d'objectif et pour détecter les **balayages** (mèche qui perce puis reprise, sur bougies 15 minutes) en plus de l'estimation par l'Open Interest.
- **Flux d'ordres plus fin** : divergence du CVD sur les pivots du prix et absorption (gros volume agressif sans mouvement), calculées sur le **vrai volume acheteur agressif** de Binance, ajoutées à la lecture du flux.
- **Profils de volume plus précis** : le profil du jour, de la semaine et du mois (courants et précédents) est calculé sur des bougies **5 minutes** (70 jours gardés) au lieu de 1 heure. Mesuré sur 21 mois de BTC : le point de contrôle hebdomadaire s'écarte en moyenne de 1,2 amplitude horaire du profil réel (minute par minute) avec des bougies 1 h, de 0,7 avec 5 minutes ; pour le jour, de 0,47 à 0,32. VWAP et VWAP ancrés étaient déjà précis à 1 h (écart moyen de 0,05 amplitude au plus) ; les bandes ±2σ gagnent un peu.
- **Rejeu dans le terminal** (validation de l'onglet Idées) : compare désormais aux entrées au hasard *dans la même tendance* et sépare les idées dans le sens / à contre-courant / en tendance indécise.

### Lancer le banc d'essai sur tes propres données (SOL en priorité)
Les chiffres livrés sont ceux du BTC. Pour SOL (ou toute paire Binance), avec le **vrai** volume acheteur agressif :
```
python tools/fetch_history.py SOLUSDT      # télécharge l'historique 1 minute public de Binance (data.binance.vision, sans clé)
python tools/run_study.py SOLUSDT          # quelques minutes à une demi-heure ; écrit data_local/reports/backtest_SOL.json
```
Le rapport apparaît dans la page Backtest (menu « Rapport »), et le filtre de tendance cite alors les chiffres de ta paire plutôt que ceux du BTC. `--market spot` pour le comptant, `--since 2021-01` pour limiter l'historique, `--workers 4` pour les coeurs utilisés. **Ces deux commandes demandent un accès internet vers Binance** ; elles ont été écrites d'après le format public des archives et testées sur de fausses archives, pas encore contre le vrai site.

### Ce qui n'est pas testé (et donc pas démontré)
Les poches estimées par l'Open Interest (29 jours d'historique seulement), le contexte macro et les annonces, le financement réel, l'écart acheteur / vendeur, et le flux d'ordres réel sur BTC (les archives Bitstamp n'ont pas de volume acheteur agressif : il est estimé par la position de la clôture dans la bougie). Les marchés de 2013 à 2016 étaient peu liquides : les frais réels y étaient plus élevés que ceux supposés.

## Ce qui est nouveau en V5 : des idées de trade, pas du bruit

### Ce que c'est
Une **idée de trade** est un achat ou une vente préparé à l'avance : où entrer, où sortir si l'idée est fausse (le **stop**), où prendre les gains (deux **objectifs**), pourquoi, et avec quelles probabilités. Le terminal t'en envoie sur Telegram **au plus 5 par semaine** (réglable) (du lundi 00 h UTC au dimanche), et seulement si leur qualité dépasse un seuil. Il vaut mieux recevoir zéro idée qu'une idée moyenne.

### Comment une idée est construite : trois piliers
1. **La liquidité.** Poche de liquidations dans la zone ou **juste au-delà** (le stop est alors placé derrière elle), poche **déjà balayée** récemment (les ordres d'arrêt ont été pris : retournement fréquent), zone percée puis reprise, ou grosse poche en face comme objectif. **Sans liquidité liée à la zone (6 points sur 30 au minimum), pas d'idée.**
2. **Les VWAP et VWAP ancrés**, de l'heure à l'année. Chaque source pèse selon son échelle de temps : jour 1, semaine 2, mois 3, année 4. VWAP et VWAP ancrés sont bonifiés (x1,6), les profils de volume (x1,2) ; ouvertures, plus hauts / bas précédents et POC nus renforcent. Un VWAP annuel pèse donc plus de quatre fois un VWAP du jour. Une zone doit réunir au moins 3 sources (qualité 7 minimum), dont 2 d'échelle semaine ou plus et **au moins un VWAP ou VWAP ancré**.
3. **Le contexte macro.** Lecture des actifs de référence (dollar, taux 10 ans, indices, VIX, or) et de leur lien mesuré avec le BTC, annonces à venir avec leur consensus, réaction mesurée aux annonces passées. **Une macro nettement contraire (risk-off pour un achat, par exemple) écarte l'idée** ; une annonce majeure dans moins de 3 h ou juste publiée la met en attente.
4. **VWAP ancrés automatiques.** En plus de ta date d'ancrage : le plus bas et le plus haut de l'année et des 3 derniers mois, le début de l'année et du mois précédents. Ils entrent dans les confluences et le graphique VWAP.
5. **Deux types d'idées.** *Rebond* : ordre à cours limité au bord de la zone. *Retournement après balayage* : la zone (ou une poche proche) vient d'être percée puis reprise ; l'entrée est immédiate et le stop passe sous la mèche.
6. **Stop et objectifs.** Le stop est au-delà de la zone, de ses poches et de la mèche, jamais à moins de 1,5 amplitude d'une bougie d'une heure. L'objectif 1 est juste avant le prochain niveau important ou la prochaine grosse poche, à au moins 1,5 fois le risque ; l'objectif 2 est le suivant. Sans objectif réaliste, pas d'idée.
7. **Score sur 100.** Liquidité (30), VWAP / VWAP ancrés et niveaux (30), macro et annonces (20), flux d'ordres (8), tendance de fond (7), biais et dominance (5).
8. **Filtres.** Seuil de 60/100 (la dernière place de la semaine exige 68) ; au plus 5 idées par semaine (réglable) ; une idée par symbole toutes les 12 h ; au plus 2 idées ouvertes par symbole.

### Ce que tu reçois
- **Par défaut, Telegram ne reçoit QUE les idées de trade** (et leur suivi). Plus de « nouvelle confluence », de poches balayées ni d'alertes d'annonces. Pour les retrouver : ⚙ section 3, « Idées de trade + alertes de zones, de poches et d'annonces » (`TERMINAL_ALERT_MODE=all`). Au démarrage, un seul message court confirme que le terminal tourne.
- Chaque idée est un message en plusieurs parties : **quoi faire**, **pourquoi ici** (liquidités, puis VWAP et VWAP ancrés, puis les autres niveaux, chacun expliqué avec son échelle de temps), **contexte macro**, **annonces économiques** (consensus et réaction passée), **autres contextes**, **probabilités**, **prudence** (calcul de liquidation avec ton levier). Aucune abréviation : VWAP est écrit « prix moyen pondéré par les volumes », POC « point de contrôle », etc.
- Le suivi de l'idée : ordre exécuté, objectif 1 atteint (avec le conseil de remonter le stop à l'entrée), objectif 2, stop touché, ordre jamais exécuté / expiré.
- Dans le terminal : onglet **Idées** du panneau de droite (cartes avec « Tout comprendre », détail du score, zones écartées et pourquoi, validation historique, journal), le **plan tracé sur le graphique principal** (entrée, stop, objectifs ; case « Plan »), une pastille 🎯 dans l'en-tête, la page Overview.

### Honnêteté : ce qui est mesuré et ce qui ne l'est pas
- **Validation historique (rejeu).** Le terminal rejoue la **structure des niveaux** (VWAP jour à année et bandes, ouvertures, plus hauts / bas précédents, profils de volume, POC nus) sur tout l'historique, avec les mêmes règles qu'en direct, et compare à des **entrées au hasard de même forme** (même distance, même stop, même objectif). Il écrit le verdict : « mieux que le hasard », « pas mieux que le hasard » ou « trop peu de cas ». Sur des prix sans mémoire, il ne trouve aucun avantage : c'est le contrôle de sa propre honnêteté. Sur de vrais marchés liquides, « pas mieux que le hasard » est un résultat fréquent : l'idée reste un **scénario**, pas un avantage prouvé.
- **Non rejoué** : les poches de liquidation (29 jours d'historique d'Open Interest seulement), les annonces et le flux d'ordres. Ils pèsent dans le score en direct et filtrent les idées (liquidité, macro), mais leur effet n'est pas mesuré sur 7 ans.
- **Probabilités affichées** : fréquence historique d'exécution de l'ordre limite selon la distance, fréquence d'atteindre l'objectif 1 avant le stop dans les 72 h pour cette forme de trade (n'importe quand), et rebond historique sur les zones de ce type face au hasard.
- **Le journal** garde ce qui s'est réellement passé après chaque idée envoyée (`data_local/trades.json`). C'est le test le plus honnête, il se remplit avec le temps. Résultat cumulé en « fois le risque », en supposant que la moitié est prise à l'objectif 1.
- **Fréquence réelle** : le rejeu donne environ 2 idées par semaine (structure seule). En direct, le score (poches, flux, annonces, tendance) ne laisse passer qu'une partie d'entre elles ; la fréquence réelle ne se connaît qu'à l'usage. Peu d'idées ? Baisse la qualité minimale dans ⚙ (55 par exemple). Trop ? Monte-la.

### Avis d'influenceurs sur X (facultatif, indicatif, hors score)
À la fin de chaque idée, le terminal peut dire si quelques comptes X que **tu** choisis vont **dans ton sens** (✅ d'accord), **à l'opposé** (❌ en désaccord), sans avis net (➖) ou sans post récent sur la paire (…). C'est un message séparé envoyé juste après l'idée, avec un extrait du post le plus parlant de chaque compte pour que tu vérifies toi-même.
- **N'entre jamais dans le score ni dans aucune décision** : l'idée est calculée et envoyée sans lui, il vient seulement après (test automatique : le score, l'entrée, le stop et les objectifs sont identiques avec ou sans cet avis).
- **Lecture automatique par mots-clés** (français et anglais : haussier / baissier, long / short, breakout / breakdown, négations et doutes simples) des posts de moins de 48 h qui parlent de la paire, les plus récents pesant davantage. Elle peut se tromper : lis le post.
- **Réglage** : ⚙ section 5, « Avis d'influenceurs sur X » : coche la case, mets les comptes (10 au maximum, séparés par des virgules) et ton **jeton d'accès X**. Le bouton « Tester le jeton » vérifie le tout.
- **Jeton X** : il faut un compte développeur sur developer.x.com, une application, puis son « Bearer Token » (clé d'accès en lecture), collé dans ⚙ ou dans `TERMINAL_X_BEARER_TOKEN` du `.env`. Il n'est jamais renvoyé à l'interface ni envoyé ailleurs qu'à l'API de X.
- **Coût** : l'API de X facture la lecture, environ **0,005 $ par post lu** selon les tarifs publiés début 2026 (à vérifier sur ton compte développeur ; sans crédits, l'avis est simplement indisponible). Pour limiter le coût, les posts ne sont lus **qu'au moment d'envoyer une idée** (5 par semaine au maximum) ou quand tu cliques sur « Voir l'avis des comptes X » dans une idée, puis gardés 30 minutes. Exemple : 8 comptes x 10 posts = 80 lectures, soit environ 0,40 $ par idée.
- Désactivé tant qu'il n'y a ni jeton ni compte. Une panne de X n'a aucun effet sur les idées.

### Réglages (⚙ sections 3 et 4, ou `.env`)
`TERMINAL_SIGNALS` (1/0), `TERMINAL_ALERT_MODE` (ideas), `TERMINAL_SIGNAL_MIN_SCORE` (60), `TERMINAL_SIGNAL_MAX_WEEK` (5), `TERMINAL_SIGNAL_MIN_STRUCT` (7), `TERMINAL_SIGNAL_LEVERAGE` (10, pour le calcul de liquidation affiché), `TERMINAL_SIGNAL_VALID_HOURS` (48), `TERMINAL_SIGNAL_TREND_GATE` (1 : seulement les idées dans le sens de la tendance de fond). Avis X : `TERMINAL_X_BEARER_TOKEN`, `TERMINAL_X_ACCOUNTS`, `TERMINAL_X_POSTS` (10), `TERMINAL_X_ON` (1).

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

## Faire tourner le terminal 24 h/24 sans ton ordinateur

Le terminal n'envoie des idées que **tant qu'il tourne**. Pour ne pas laisser ton PC allumé, installe-le sur un petit serveur loué en Europe (environ 4 à 7 € par mois, 2 Go de mémoire) ou sur un Raspberry Pi toujours allumé. Un script installe tout comme service permanent (démarrage automatique, redémarrage après panne) : **voir `serveur/GUIDE.md`** (pas à pas, 10 minutes). Le terminal reste accessible depuis ton PC par un tunnel sécurisé, sans rien exposer sur Internet.

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
| Bougies 5 min | Binance futures | 70 jours (profils de volume du jour, de la semaine, du mois) |
| Open Interest 5 min | Binance futures | Environ 29 jours (limite Binance) |
| Historique 1 minute pour le backtest | Binance Vision (archives publiques) ou fichier CSV | Depuis 2019 (futures) ; BTC livré : Bitstamp depuis 2013 |
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
                    dominance, biais validé en avançant, synthèse ; stance.py (lecture des avis X) ; signals.py (idées de trade : poids, zones, stop,
                    objectifs, score, textes), sigtest.py (rejeu historique face au hasard) ; V6 : fine.py (séries 1 min à 1 h avec sommes cumulées),
                    liqsweep.py (poches visibles dans le prix, balayages), cvd.py (déséquilibre, divergences, absorption), trend.py (tendance de fond),
                    backtest.py (génération des idées, exécution 1 min, frais, métriques, témoins), study.py (rapport complet), history.py (archives Binance)
data/               sources : simulée et Binance ; historique en mémoire et contexte (funding, L/S, spot, Coinbase) ; social.py (posts X, facultatif)
alerts/             règles d'alerte, envoi Telegram ; trades.py (quota hebdomadaire, suivi et journal des idées)
service.py          relie les données et les moteurs, fabrique l'état JSON
server.py           serveur local : API, réglages, sécurité
web/                interface : index.html + style.css ; app.js (Desk, état, alertes), panels.js (les trois graphiques),
                    overview.js (vue d'ensemble), signals.js (idées de trade), analysis.js et charts.js (analyse, graphiques SVG) ;
                    TradingView Lightweight Charts (vendor/)
tools/              fetch_history.py (historique 1 min Binance) et run_study.py (rapport de backtest)
reports/            rapports de backtest livrés (BTC) ; les tiens vont dans data_local/reports/
serveur/            installation sur un serveur 24 h/24 (script et guide)
tests/              tests automatiques (plus de deux cent cinquante)
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
- **Volume profiles.** Ceux du jour, de la semaine et du mois (courants et précédents) sont construits à partir des bougies 5 min (volume réparti sur la plage haut-bas de chaque bougie), ceux de l'année et les profils choisis longs à partir des bougies 1 h : la résolution reste inférieure à celle d'un profil TradingView calculé sur des bougies 1 minute (voir V6 pour l'écart mesuré).
- **Backtest.** Voir « V6 » : l'avantage mesuré est modeste, dû surtout à la tendance de fond, et absent de la période 2022-2026 pour la règle complète. Données Bitstamp au comptant, flux d'ordres estimé.
- **Idées de trade.** Ce sont des scénarios construits à partir de niveaux, de liquidité estimée, de flux et de macro, pas des conseils financiers. Le rejeu prouve (ou non) la valeur de la structure seule. Les ordres sont supposés exécutés au prix limite, sans frais ni glissement. Le terminal doit tourner pour envoyer les idées et suivre leurs ordres.
- **À venir.** Flux ETF et on-chain si tu en as besoin.
