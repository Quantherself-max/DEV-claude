# Liq Terminal (V21)

Un terminal **local**, qui tourne uniquement sur ton PC. Il rassemble :

- **Un banc d'essai historique honnête** (V6, page **Backtest**) : la stratégie du terminal est rejouée sur 13 ans de BTC (bougies 1 minute), avec frais, contre des entrées au hasard, par période. Résultat : **le seul filtre qui compte est la tendance de fond** (voir « V6 » plus bas).
- **Ta stratégie, mesurée** (V7, onglet **Stratégie** et rapport « ta stratégie » dans la page **Backtest**) : rebonds / clôtures sur VWAP et VWAP ancrés de la semaine et du mois, position face à la VAL / VAH du volume profile, poches de liquidité en objectif, 1 à 2 jours. Testée en 252 variantes sur 13 ans de BTC, avec recherche de couverture (voir « V7 » plus bas).
- **Absorptions avec le delta** (V21) : sur le graphique principal, chaque bougie dont le delta (volume acheteur agressif − vendeur agressif, donnée réelle de Binance) va fortement CONTRE son sens est marquée (vendeurs absorbés : triangle vert ; acheteurs absorbés : triangle rouge), et en direct le terminal repère au prix près les gros volumes agressifs absorbés sans que le prix passe au travers (cercles, et repère dans le carnet). Le terminal **mesure lui-même** sur ton historique Binance si ces absorptions annoncent la suite (voir « V21 » plus bas).
- **TPO de la semaine et du mois** (V20) : la vue **▥ TPO** affiche maintenant les profils de marché **du mois** (une lettre par jour) et **de la semaine** (lundi 00 h UTC, une lettre par tranche de 4 heures, « première heure » = le lundi), et leurs **single prints** sont tracées en priorité sur les graphiques et dans les confluences ; mesure sur **14 ans de bitcoin** de ce qu'elles valent vraiment (voir « V20 » plus bas).
- **TPO complet et mesuré, profils de volume et zones plus précis** (V19) : vue **▥ TPO** refaite (zoom, séances plus anciennes, volume et delta à chaque prix, première heure et objectifs, type de journée, profil composite et ses zones fortes et faibles, POC vierges) avec ce que **10 ans de bitcoin** disent de chaque repère ; profils de volume répartis selon le trajet des bougies, nœuds de volume, POC évolutif ; zones de confluence avec **prix clé**, cœur et prix le plus échangé ; carnet d'ordres presque transparent (voir « V19 » plus bas).
- **Bilan macro de la semaine** (V18) : menu **Analyse → Bilan macro de la semaine**. Chaque semaine : les annonces avec consensus, chiffre précédent et **chiffre publié** (base officielle de la Fed de Saint-Louis), la réaction mesurée des marchés, un tableau de bord par thème (inflation, emploi, croissance, Fed et taux, dollar, liquidité, crédit, énergie), les marchés et la crypto de la semaine, **ce que cela engendre**, une **mesure** de ce qui a vraiment compté pour le bitcoin, la semaine prochaine, et un commentaire facultatif de Claude (voir « V18 » plus bas).
- **TPO et profils jour / semaine / mois** (V17) : bouton **▥ TPO** du Desk (profils de marché des séances d'1 jour, de 4 heures et d'1 heure, avec **single prints** et **poor high / poor low**), ces mêmes marques sur les graphiques et dans les confluences, et les **profils de volume de la semaine et du mois** à côté de celui du jour (voir « V17 » plus bas).
- **Plusieurs unités de temps à la fois** (V16) : bouton **⊞ Multi-unités** du Desk, 2 à 5 graphiques du même actif côte à côte (5 min, 15 min, 1 h, 4 h, 1 jour au choix pour chacun), bougie en direct, VWAP, profil de la séance, niveaux clés, **réticule synchronisé** et ligne d'**alignement** des unités (voir « V16 » plus bas).
- **Écran d'order flow** (V15) : style « nuit » (fond noir, bougies bleues et blanches, prix en bleu avec le décompte dessous), **profil de volume de la séance collé à l'échelle des prix** (part des acheteurs et des vendeurs, POC / VAH / VAL, plus haut et bas de séance, clôture de la veille), VWAP du jour à ±1 écart-type, **carnet d'ordres en direct aligné sur les prix** (taille en attente, nombre d'ordres, volume échangé à chaque prix), **gros ordres exécutés en losanges**, vitesse du ruban et latence (voir « V15 » plus bas).
- **Poches de liquidité classées par importance** (V14) : chaque poche (estimée par l'intérêt ouvert ou visible dans le prix) affiche son **âge** (formée il y a…), un **score d'importance sur 100** (taille + confluences autour + fraîcheur) et son **rang** de son côté (N°1, N°2…), le même en 15 minutes, 1 heure ou 4 heures. Les poids viennent d'une **mesure sur 12 ans de BTC** (rapport « poches » dans la page **Backtest**, voir « V14 » plus bas).
- **Historique et sens de tes trades** (V13) : page **Historique** (chaque idée et alerte envoyée avec son résultat, la lecture du terminal jour après jour et ce que le prix a fait ensuite), **jamais deux biais opposés à moins de 24 heures**, toutes paires confondues, et le **biais du terminal** affiché partout (voir « V13.1 » et « V13 » plus bas).
- **Discuter avec Claude** (V12) : pose tes questions sur Telegram (au même bot) ou dans l'onglet **Discussion** (« pourquoi le BTC a perdu 2 % ? ») ; Claude répond avec toutes les données du terminal à cet instant et l'actualité du web (voir « V12 » plus bas).
- **Mise à jour automatique** (V11) : une nouvelle version publiée sur GitHub est vérifiée, sauvegardée et installée toute seule ; le terminal redémarre dans la même fenêtre et la page se recharge. Rien à configurer : le dépôt est public (Réglages → 6 pour suivre l'état, voir « V11 » plus bas).
- **Où est l'argent, l'or, et les squeezes** (V10) : carte du capital (bitcoin, ETH, altcoins, stablecoins, or) et rotation, asymétrie bitcoin / or, **delta, divergences flux / prix / volume et short / long squeezes** (lecture en direct à la Velo dans la Lecture, mesure sur 12 ans), décompte de bougie sous le prix comme sur TradingView (voir « V10 » plus bas).
- **Un écran de lecture épuré et de nouvelles données** (V9) : onglet **Lecture** (l'essentiel en une page, chaque ligne avec son niveau de preuve), dérivés multi-bourses (options, volatilité implicite, base, financement, Open Interest), données en chaîne et macro libres, et un **laboratoire d'indicateurs** qui mesure ce que vaut chaque indicateur (voir « V9 » plus bas).
- **Les VWAP ancrés sur un mouvement d'au moins 5 %** (V8, onglet **Stratégie** et rapport « VWAP ancrés sur un mouvement » dans la page **Backtest**) : VWAP ancré sur le sommet de la baisse (résistance) et sur le creux (support), réaction du prix mesurée sur 13 ans de BTC (voir « V8 » plus bas).
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

## Ce qui est nouveau en V21 : les absorptions, avec le delta

Une **absorption**, c'est beaucoup d'ordres **agressifs** d'un côté (des ventes au marché, par exemple), et pourtant le prix ne va pas dans leur sens : en face, des ordres **passifs** (souvent cachés et rechargés au fur et à mesure) ont tout encaissé. Le terminal les repère de deux façons.

### Sur les bougies (case **Absorptions** du graphique principal, cochée par défaut)
- **Absorption acheteuse** (les vendeurs sont absorbés) : delta d'au moins **2 écarts-types** de la normale des 96 bougies précédentes, très **vendeur**, sur une bougie qui finit pourtant en **hausse** → triangle **vert** sous la bougie.
- **Absorption vendeuse** (les acheteurs sont absorbés) : delta très **acheteur** sur une bougie qui finit en **baisse** → triangle **rouge** au-dessus.
- Triangle **plein** et chiffre du delta : absorption forte (3 écarts-types ou plus) ou **au plus bas / au plus haut** des 12 dernières bougies (là où une absorption a le plus de sens). **Anneau orange** : elle s'est produite sur une **zone de confluence**.
- **Survole** un triangle : delta en pièces (BTC, SOL), écarts-types, volume par rapport à la normale, et **ce que la mesure dit** sur ce marché.
- Toutes les unités de temps (5 minutes à 1 jour). Le delta est **réel** (volume acheteur agressif de Binance) : sans cette donnée, rien n'est affiché.

### En direct, au prix près (ruban et carnet)
- Sur les 60 dernières secondes, un gros volume agressif d'un seul côté à **un même prix** (au moins deux fois l'autre côté, au-dessus d'un seuil qui s'adapte au marché), sans que le prix passe au travers → **cercle** à ce prix sur le graphique, avec le montant absorbé, et **repère vert ou rouge dans le carnet**.
- Ensuite : **confirmée** (cercle plein : le prix s'éloigne d'environ 0,12 % dans son sens), **cassée** (cercle barré : le prix passe au travers) ou **tenue** (ni l'un ni l'autre en 5 minutes). **Losange** au centre : il s'est exécuté à ce prix au moins **deux fois la taille encore affichée** dans le carnet Binance → l'ordre passif se recharge (ordre caché probable, « iceberg »).
- Ces absorptions en direct ne sont **pas mesurables** sur l'historique (il faudrait l'archive de chaque transaction et du carnet) : la bulle le dit.

### Ce que dit la mesure (calculée chez toi, sur tes données)
L'historique Binance n'a pas pu être téléchargé pendant le développement (accès bloqué), et l'historique Bitstamp disponible n'a qu'un delta **estimé** : impossible d'y voir une absorption. Le terminal fait donc la mesure **lui-même**, en tâche de fond, sur son historique Binance (bougies 1 heure depuis 2019 pour le BTC, 2020 pour SOL, avec le vrai volume acheteur agressif, et regroupées en 4 heures) :
- pour chaque absorption : le prix va-t-il dans son sens dans les **4 bougies suivantes** ? le plus bas (plus haut) de la bougie **tient-il** ?
- face aux 20 bougies les plus proches dans le temps qui ont **le même sens, le même corps et le même volume**, mais un **delta ordinaire** : on isole exactement ce qu'ajoute le delta ;
- verdict « mesuré » seulement si l'écart dépasse 2 erreurs-types **et** garde le même sens sur les deux moitiés de la période.

Le résultat apparaît dans la bulle des triangles, dans la ligne **Absorption** de la Lecture (avec le niveau de preuve) et dans la page **Backtest** (rapport « absorptions »). Pour les petites unités de temps (5 et 15 minutes) et plus d'historique : `python tools/fetch_history.py SOLUSDT` puis `python tools/run_absorption_study.py SOLUSDT` (une à quelques minutes) ; ce rapport remplace alors la mesure du terminal.

### Honnêteté
- La détection et la mesure n'ont pas pu être vérifiées sur de vraies données Binance pendant le développement : seulement sur des données simulées et des tests (l'outil retrouve un effet quand on en met un, et n'en invente pas quand il n'y en a pas). Les premiers chiffres réels s'afficheront chez toi quelques minutes après le démarrage.
- Les absorptions ne changent **ni les idées de trade ni Telegram** tant qu'elles ne sont pas mesurées.
- En mode « données simulées », des absorptions sont fabriquées de temps en temps pour que l'écran serve d'exemple.

## Ce qui est nouveau en V20 : TPO de haute unité de temps (semaine et mois)

Sur les séances courtes (1 heure, 4 heures), les single prints sont innombrables (plus de 10 000 zones sur les séances d'1 heure depuis 2021) et la plupart ne veulent rien dire. Sur la semaine et le mois, une single print est un prix qu'**une seule tranche de 4 heures (ou une seule journée) a touché de toute la semaine (du mois)** : des zones rares (en moyenne 0,4 par semaine sur les profils de la semaine, 0,6 par mois sur ceux du mois) et larges.

### Dans le terminal
- **Vue ▥ TPO** : deux nouvelles colonnes, **1 mois** (tranches d'1 jour, profil composite des 3 derniers mois) et **1 semaine** (tranches de 4 heures, composite des 4 dernières semaines), cochées par défaut avec la séance d'1 jour (4 heures et 1 heure restent disponibles). La « première heure » devient **le lundi** pour la semaine et **la première semaine** pour le mois (barre verte, objectifs ×1,5 et ×2) ; type de séance, forme, migration de la valeur, ouverture, règle des « 80 % », rotation, POC vierges : tout fonctionne comme pour le jour. Quand les profils sont trop larges pour tenir à trois, ils passent en **histogramme compact** à l'échelle commune.
- **Graphiques** (principal et multi-unités) : cases **TPO mois** et **semaine** (cochées), single prints de haute unité de temps en **trait épais** et fond plus marqué, tracées en premier ; 4 heures et 1 heure décochées par défaut pour ne pas noyer le graphique (tout reste réglable).
- **Confluences** : single prints et poor high / low **de la semaine et du mois** entrent dans les zones, avec le poids de leur échelle de temps (semaine ×2, mois ×3) pour le **prix clé** de la zone. Les idées de trade, elles, n'utilisent toujours pas le TPO.
- Calcul sur les **bougies d'1 heure** (la bougie en cours comprise), donc sur plusieurs années d'historique ; marques TPO gardées en mémoire tant que les bougies ne changent pas.

### Ce que disent 14 ans de bitcoin (rapport « TPO » de la page Backtest)
Mesure refaite avec un **témoin plus juste** : pour chaque zone de single prints, la **même bande** (même position par rapport à la clôture, en amplitudes habituelles) dans les 20 séances les plus proches **qui ont le même sens, la même amplitude et une clôture au même endroit de leur fourchette**, et où ces prix ont été échangés par au moins deux tranches. On compare donc, à mouvement égal, des prix « passés vite » à des prix « échangés ». L'ancien témoin (bande miroir de l'autre côté de la clôture) était faussé par la hausse de fond du bitcoin, car les single prints sont surtout **sous** la clôture (laissées par les hausses). Semaine et mois : 768 semaines et 176 mois de 2012 à 2026 (bougies 1 h).

| Single prints | Comblées dès la séance suivante (témoin) | Au retour du prix, la zone tient (témoin) | Verdict |
|---|---|---|---|
| **Mois** (102 zones) | **18 %** (34 %) ; en 3 mois 38 % (50 %) | 33 % (39 %) | **moins comblées qu'ailleurs** (2019-2026 : 13 % contre 38 %) |
| **Semaine** (309 zones) | **32 %** (39 %) ; en 4 semaines 50 % (60 %) | 39 % (44 %) | même sens à tous les horizons, mais **seulement sur 2019-2026** (26 % contre 41 % ; 2012-2019 : aucun écart) : à confirmer |
| **Jour** (1 383 zones) | 35 % (41 %) ; en 5 jours 64 % (67 %) | 42 % (43 %) | **moins comblées qu'ailleurs**, stable |
| 4 heures (3 254 zones) | 37 % (38 %) | 37 % (41 %) | aucun écart pour le comblement |
| 1 heure (10 634 zones) | 35 % (40 %) | 40 % (40 %) | moins comblées qu'ailleurs |

**Ce que ça veut dire pour trader** :
- Une single print n'est **pas un aimant**, quelle que soit l'unité de temps : le prix y revient plutôt **moins** souvent qu'à un prix comparable, et l'écart **grandit avec l'unité de temps** (mois : −16 points). Elle marque un mouvement **convaincu** : le marché a accepté les nouveaux prix et ne revient pas vite. Ne pas viser son comblement comme objectif.
- **Au retour du prix**, une single print ne tient **ni mieux ni moins bien** qu'un autre prix (rebond d'au moins sa hauteur avant d'être traversée : même fréquence que les témoins) : ce n'est pas un support ou une résistance en soi. Ce sont les autres repères (VWAP, profils de volume, poches) qui doivent décider d'une entrée.
- **Élan** : après un mois qui laisse des single prints, le mois suivant va dans le même sens 67 % du temps contre 47 % après un mois semblable sans single print (seulement 42 cas : à confirmer) ; sur le jour, 48 % contre 44 % (mesuré et stable) ; rien sur la semaine.
- Les autres repères de la semaine et du mois : **poor high / low** sans effet (contrairement au jour et à l'heure), **POC** sans effet aimant, **fourchette du lundi** cassée des deux côtés 39 % des semaines (cassure par le haut : la semaine clôture au-dessus 57 % du temps, par le bas : en dessous 48 %, l'écart reflète surtout la hausse de fond du bitcoin), règle des « 80 % » : 47 % sur la semaine (129 cas), 29 % sur le mois (35 cas).

Variantes regardées pour choisir les réglages (même conclusion) : tranches d'1 jour ou de 12 heures pour la semaine, 40 ou 100 lignes au lieu de 60. Pour refaire la mesure : `python tools/run_tpo_study.py --folder dossier_bitstamp --fine dossier_5min --label BTC` (1 minute) ; sur SOL : `python tools/fetch_history.py SOLUSDT` puis `python tools/run_tpo_study.py SOLUSDT`.

### Honnêteté
- Un seul actif (bitcoin au comptant, Bitstamp). Peu de mois (176) et de semaines (768) : les écarts sur ces séances sont moins sûrs que sur le jour ; la partie « stabilité » de chaque tableau de la page Backtest montre d'où ils viennent (première et seconde moitié de la période).
- Le tableau V19 « single prints comblés en 5 jours 60 % contre 65 % » utilisait la bande miroir ; avec le témoin apparié l'écart est de 64 % contre 67 % en 5 jours et de 35 % contre 41 % dès le lendemain : même conclusion, mieux mesurée.

## Ce qui est nouveau en V19 : TPO complet et mesuré, profils de volume et zones plus précis

### La vue TPO (bouton **▥ TPO** du Desk), refaite
- **Navigation** : molette = zoom sur les prix, glisser = déplacer, **Maj + molette** (ou glisser à l'horizontale) = séances plus anciennes (jusqu'à 30 jours, 42 séances de 4 h, 48 heures), double-clic = recadrer.
- **Sur chaque séance** : zone de valeur en fond bleuté (et barre bleue), POC surligné, **première heure** (« initial balance », barre verte, lettres A et B en vert) avec ses objectifs **×1,5** et **×2** sur la séance en cours, **ouverture ▶** et **clôture ◀**, **volume et delta à chaque prix** (barres fines : bleu = acheteurs agressifs dominants, blanc = vendeurs), single prints (rectangle gris), poor high / low (trait orange), queues (lettres sombres), dernière lettre de la séance en cours en orange, **POC vierges** prolongés en pointillés.
- **Profil composite** à droite (5 jours, 6 séances de 4 h ou 12 heures) avec ses **zones fortes (HVN, bleu)** et **faibles (LVN, orange)**, reportées en bandes légères sur tout le graphique.
- **Contexte de la séance en cours** (pastilles sous le titre, détail au survol) : type de journée (classement de J. Dalton, avec sa fréquence sur l'historique), forme du profil (P, b, D, I, B), migration de la zone de valeur, position de l'ouverture face à la valeur précédente (avec ce qui a été mesuré), règle des « 80 % », cassure de la première heure, facteur de rotation, répartition des lettres autour du POC.
- **Bulle au survol** : lettres, volume et delta du prix, taux mesuré des single prints et des POC vierges. Cases : affichage (lettres ou blocs), lignes fines, volume, composite, POC vierges, première heure.
- Pour coller à la mesure, la séance d'1 jour compte maintenant **60 lignes** pour son amplitude habituelle (40 avant) : les repères sont plus fins.

### Ce que disent 10 ans de bitcoin (rapport « TPO » de la page Backtest, et panneau « Ce que dit l'historique » de la vue TPO)
Mesure faite avec exactement le moteur du terminal (Bitstamp : bougies de 15 min depuis 2016 pour 3 930 jours, de 5 min depuis 2021 pour 12 600 séances de 4 h et 50 400 heures). Chaque repère est comparé à un **témoin placé à la même distance du prix** :

| Repère | Ce qui se passe | Verdict |
|---|---|---|
| **Poor high / poor low** | dépassés dès la séance suivante 48 % du temps (1 jour), 50 % (4 h), 51 % (1 h), contre 42 %, 41 %, 40 % pour un extrême avec queue | **effet réel et stable** : la queue est un vrai rejet, le poor high / low une enchère inachevée |
| **POC** | retraversé dès la séance suivante 68 % du temps contre 65 % pour un prix témoin ; POC resté vierge une heure : revisité 51 % contre 45 % | **léger effet aimant**, net mais faible (2 à 6 points) |
| **Ouverture sous la valeur précédente** | la séance finit en hausse 60 % du temps (1 jour), 59 % (4 h), 56 % (1 h), contre 52 % en moyenne ; au-dessus : 48 %, 45 %, 45 % | **retour vers la valeur** mesuré, séances plus larges (×1,2) |
| **Single prints** | comblés en 5 jours 60 % du temps, mais une zone témoin l'est 65 % ; en 4 h et en 1 h : comme le hasard | **pas d'effet aimant** (sur 1 jour, même un peu l'inverse) |
| **Règle des « 80 % »** | autre bord atteint **43 %** du temps (1 026 cas), contre 38 % après un simple retour dans la valeur | utile, mais **très loin de 80 %** |
| **Première heure** | cassée des deux côtés 70 % des jours ; depuis la première cassure, la journée clôture au-delà du niveau cassé 53 % (haut) / 46 % (bas) | la cassure **ne dit presque rien** de la suite |

Pour mesurer SOL : `python tools/fetch_history.py SOLUSDT` puis `python tools/run_tpo_study.py SOLUSDT` (le rapport remplace celui du bitcoin pour cette paire).

### Profils de volume
- **Plus précis** : le volume de chaque bougie suit son **trajet probable** (haussière : ouverture → plus bas → plus haut → clôture ; baissière : l'inverse), au lieu d'être étalé uniformément ; les prix traversés deux fois reçoivent deux fois plus de volume.
- **Nœuds de volume** (case « Nœuds ») : **HVN** (bleu, zones d'acceptation) et **LVN** (violet, zones de rejet que le prix traverse vite), sur le bord de chaque profil et en bandes légères sur le graphique.
- **POC évolutif** (case « POC évolutif ») : le POC (trait clair) et la zone de valeur (pointillés bleus) du jour tels qu'ils ont bougé au fil de la séance.
- **POC vierges** (case « POC vierges ») : les POC des jours (J-n) et des semaines (S-n) passés jamais retraversés, les 6 plus proches du prix, prolongés en pointillés avec leur prix.
- Titre de chaque profil avec sa **forme** (P, b, D).

### Zones de confluence plus précises
Les membres des zones ne changent pas (les idées de trade restent calculées exactement comme avant), mais chaque zone indique maintenant **où agir** :
- **Prix clé** (trait orange, et prix affiché dans les listes) : médiane de ses niveaux, chacun pesé selon son échelle de temps (jour 1, semaine 2, mois 3, année 4) et sa famille (VWAP ×1,6, profils de volume ×1,2…) ;
- **Cœur** (bande orange plus marquée) : la partie de la zone qui porte la moitié centrale de ce poids ;
- **Prix le plus échangé** dans la zone sur les 14 derniers jours (petit losange blanc au bord droit) ;
- **Largeur** en ATR et précision (précise, moyenne, large) dans la fiche de la zone (« Où agir dans la zone »).

### Carnet d'ordres
Fond encore plus transparent (12 % au lieu de 34 %), barres de taille plus légères, chiffres lisibles grâce à un léger halo : les bougies se voient à travers.

### Honnêteté
- La mesure porte sur le bitcoin au comptant (Bitstamp), pas sur le contrat perpétuel de Binance ni sur SOL (outil fourni). Plusieurs mesures étant faites à la fois, seuls les écarts nets ET de même sens sur les deux moitiés de la période sont marqués « mesuré ».
- Les repères TPO et les nœuds de volume **ne sont pas utilisés par les idées de trade**.
- La première heure classique (1 h à partir de 00 h UTC) est petite sur un marché ouvert 24 h sur 24 : elle est cassée des deux côtés 70 % des jours, d'où beaucoup de journées « neutres » ; la fréquence de chaque type de journée est affichée.

## Ce qui est nouveau en V18 : le bilan macro de chaque semaine

Menu **Analyse → Bilan macro de la semaine** (aussi dans les onglets de la page Analyse). Un menu en haut choisit la semaine : celle en cours (recalculée toutes les 5 minutes) et les précédentes. Une version est **archivée chaque semaine** (deux ans gardés) ; les 8 dernières semaines peuvent aussi être établies après coup, avec seulement les chiffres déjà publiés en fin de semaine.

### Ce que contient le bilan
- **Ce que cela engendre** : le « vent macro » pour les actifs à risque et les cryptos (de défavorable à favorable), avec ce qui soutient et ce qui freine, le bilan des surprises de la semaine et la lecture du marché au moment des annonces (taux et dollar).
- **Annonces de la semaine** (heures de Paris) : consensus, chiffre précédent, **chiffre publié**, écart au consensus, ce que cela veut dire, et la réaction mesurée dans les 15 minutes (taux à 10 ans, dollar, bitcoin). Les annonces à venir affichent ce qu'un chiffre au-dessus du consensus impliquerait.
- **Tableau de bord par thème**, chaque thème avec sa lecture (favorable, neutre, défavorable) :
  - *Inflation* : sur un an, sous-jacente (hors alimentation et énergie), rythme des 3 derniers mois, indice préféré de la Fed, inflation anticipée par le marché ;
  - *Emploi* : chômage, règle de Sahm (signal de récession), créations d'emplois, inscriptions au chômage, salaires, offres d'emploi ;
  - *Croissance* : produit intérieur brut, ventes au détail ;
  - *Fed et taux* : taux directeur, taux à 2 et 10 ans, ce que le marché anticipe, pente de la courbe, taux réel ;
  - *Dollar* ; *Liquidité* : bilan de la Fed, compte du Trésor, prises en pension, **liquidité nette**, masse monétaire ;
  - *Risque et crédit* : écarts de taux des entreprises à haut rendement, volatilité, conditions financières ; *Énergie* : pétrole.
- **Marchés sur la semaine** (bitcoin, ether, solana, indices américains, or, dollar, taux à 10 ans, volatilité) et **crypto** (dominance du bitcoin, capitalisation, sentiment, stablecoins, où va l'argent).
- **Ce qui a vraiment compté pour le bitcoin** : pour chaque moteur (liquidité, dollar, taux réel, crédit, taux à 10 ans), le rendement moyen du bitcoin la semaine suivante (et les 4 semaines suivantes) selon que le moteur était favorable ou non, avec un verdict honnête (« écart net » ou « ≈ hasard »). Calculé sur ton PC avec les vraies données.
- **Semaine prochaine** : les annonces à surveiller et les deux scénarios.
- **Commentaire de Claude** (bouton, facultatif, avec ta clé API de la V12) : rapports de la Fed et du reste du monde, géopolitique, fonds indiciels cotés (ETF), institutionnels, avec ses sources. Quelques centimes par commentaire, gardé avec la semaine.
- Une ligne **« Bilan macro de la semaine »** apparaît aussi dans le panneau Lecture du Desk.
- **Telegram** : Réglages → 3, case « Bilan macro de la semaine, le samedi matin ». **Désactivé par défaut** (Telegram reste réservé aux idées de trade tant que tu ne la coches pas).

### D'où viennent les chiffres, et les limites
- **Chiffres officiels américains** : base FRED de la Réserve fédérale de Saint-Louis, téléchargement public sans clé (30 séries, tout l'historique depuis 2016 au premier lancement, puis toutes les 3 heures et peu après chaque annonce américaine). FRED donne la dernière valeur connue : les emplois et le produit intérieur brut sont parfois **révisés** après coup. Le chiffre publié d'une annonce est figé dans l'archive dès qu'il est trouvé.
- **Garde-fou** : le chiffre publié n'est affiché que si FRED est déjà à jour (vérifié avec le « chiffre précédent » du calendrier). Juste après une annonce, il peut rester « non fourni » une à quelques heures. Les statistiques hors États-Unis et les indices privés (ISM, confiance des consommateurs) ne sont pas dans FRED : « non fourni », mais la réaction des marchés est mesurée.
- Les lectures « favorable / défavorable » sont des **règles classiques d'économistes, pas des prévisions**, et **les idées de trade n'en tiennent pas compte**. La mesure du bilan dit lesquelles ont réellement fait une différence pour le bitcoin ; plusieurs moteurs étant testés à la fois, un écart isolé peut être dû à la chance.
- Je n'ai pas pu tester les vrais téléchargements FRED depuis mon environnement (accès bloqué) : tout est vérifié sur des données simulées et des tests automatiques. Si un problème apparaît, la page affiche « Sources en difficulté » avec le détail.

## V17.1 : « HTTP 404 » dans la vue TPO (ancien programme encore lancé)

Ce message voulait dire que les **nouvelles pages** étaient arrivées dans le dossier, mais que le **programme** qui tournait sur le PC était encore l'ancien : il ne connaissait pas l'adresse du TPO. Pour corriger tout de suite : **ferme la fenêtre noire « Liq Terminal »** (ou Ctrl+C dedans), puis relance **Lancer-Terminal-Windows.bat** (Mac : Lancer-Terminal-Mac.command). Ensuite, plus besoin d'y penser :
- **Redémarrage automatique** : le terminal surveille ses propres fichiers. Si une nouvelle version est copiée dans son dossier pendant qu'il tourne (ZIP extrait par-dessus, mise à jour, git pull), il redémarre tout seul environ 30 secondes plus tard, et la page se recharge. Lancé sans le lanceur, il affiche un bandeau « relance le terminal ».
- **Bandeau rouge** en haut de la page si le programme qui tourne est plus ancien que les pages, avec ce qu'il faut faire. La vue TPO l'explique aussi dans chaque colonne au lieu de rester noire.
- **Lanceur** : si une autre version du terminal occupe déjà le port (une ancienne fenêtre restée ouverte, ou un autre dossier), il le dit clairement au lieu d'ouvrir la page de l'ancien programme.

## Ce qui est nouveau en V17 : TPO, single prints, poor high / low, profils semaine et mois

### La vue TPO (bouton **▥ TPO** du Desk)
- Trois colonnes, une par type de séance : **1 jour** (00 h – 24 h UTC, une lettre par tranche de **30 minutes** : A = 02 h – 02 h 30 heure de Paris l'été…), **4 heures** et **1 heure** (une lettre par tranche de **5 minutes**). Cases en haut pour n'en garder qu'une ou deux (choix gardé). Les séances les plus récentes sont à droite, près de l'échelle des prix ; la séance en cours est marquée « en cours ».
- Chaque lettre est posée sur tous les prix que sa tranche a touchés. Les lettres claires sont les plus récentes ; quand la colonne est trop étroite, les lettres deviennent de petits blocs (le survol affiche toujours le prix, le nombre de tranches et les lettres de la ligne).
- **POC** : la ligne la plus longue (prix le plus souvent visité dans le temps), surlignée. **Zone de valeur** (70 % des lettres autour du POC) : barre **bleue** à gauche de la séance. **Première heure** de la séance d'1 jour (tranches A et B, l'« initial balance ») : barre **verte**.
- **Single prints** : **rectangle gris peu opaque**. Ce sont des prix touchés par **une seule tranche** au milieu du profil (au moins deux lignes de suite) : le prix y est passé vite, sans s'y arrêter. Tant qu'il n'a pas retraversé toute la zone depuis, le rectangle est **prolongé vers la droite** ; une fois comblé, il reste pâle dans sa séance.
- **Queues** (lettres plus sombres tout en haut ou tout en bas) : single prints au bord du profil, rejet net, enchère terminée.
- **Poor high / poor low** : trait **orange**. Le plus haut (ou le plus bas) de la séance a été touché par **au moins deux tranches**, sans queue : l'enchère s'est mal terminée et le niveau attire souvent un retour. Prolongé en pointillés tant que le prix ne l'a pas dépassé (« réparé »).

### Sur les graphiques (principal et multi-unités)
- Cases **TPO 1 j**, **4 h**, **1 h** de la barre d'outils : les single prints **non comblés** en rectangle gris (de leur séance jusqu'au bord droit) et les poor high / low **non réparés** en pointillés orange, avec leur nom (« single prints 4 h », « poor low 1 j »). Par défaut 1 j et 4 h (les séances d'1 h font beaucoup de marques : à garder pour le 5 ou 15 minutes).
- **Dans les confluences** : les single prints non comblés et les poor high / low actifs des séances **d'1 jour et de 4 heures** proches du prix entrent dans la liste des niveaux (groupe **TPO**, gris pour les single prints, orange pour les poor) et peuvent former une zone avec d'autres niveaux.
- **Profils de volume** : cases **Profil J**, **S** et **M**. En plus du profil du jour, le profil de la **semaine en cours** (depuis lundi 00 h UTC, bleu ardoise) et du **mois en cours** (depuis le 1er, brun), côte à côte à droite, chacun avec son POC (« POC semaine », « POC mois ») et sa zone de valeur en pointillés. Bougies 5 minutes quand elles couvrent la période, sinon 1 heure (le mois, après ~29 jours).
- **Carnet d'ordres** plus transparent : on voit les bougies à travers.

### Honnêteté
- Les TPO sont calculés sur les **bougies de 5 minutes** de Binance (le plus haut et le plus bas de chaque tranche) : c'est la méthode habituelle, mais un aller-retour à l'intérieur d'une bougie de 5 minutes ne compte qu'une fois.
- **Rien du TPO n'est mesuré** par le backtest du terminal, et les **idées de trade n'en tiennent pas compte** (elles restent calculées exactement comme avant, sans ces niveaux) : ce sont des repères de lecture, pas un signal validé.

## Ce qui est nouveau en V16 : analyser plusieurs unités de temps en même temps

- **Bouton ⊞ Multi-unités** (barre du Desk) : une grille de **2, 3, 4 ou 5 graphiques** du même actif (boutons en haut de la grille). Chaque graphique a son **unité de temps** (menu en haut à gauche : 5 min, 15 min, 1 heure, 4 heures, 1 jour) ; par défaut 5 min, 15 min, 1 h, 4 h, puis 1 jour. Le choix est gardé.
- **Sur chaque graphique** : les bougies (celle en cours bouge à chaque transaction, avec le décompte « clôture dans 03:12 »), la **VWAP du jour** et ses bandes à ±1 écart-type, la **VWAP de la semaine** (trait plus fin), le **profil de la séance** collé à l'échelle des prix avec POC, VAH, VAL, et les **plus hauts / plus bas de la veille, de la semaine et du mois précédents** (nommés au bord gauche).
- **Réticule synchronisé** : en survolant un graphique, les autres placent leur réticule **au même instant** (sur la bougie de leur unité qui le contient) et **au même prix**. Pratique pour voir où se situe un creux du 5 minutes dans la bougie 1 heure ou 4 heures.
- **En-tête de chaque graphique** : variation de la bougie en cours, position du cours face aux **moyennes 20 et 50 bougies** de cette unité et face à la **VWAP du jour** (de la semaine sur le graphique 1 jour, où la VWAP du jour n'a pas de sens). Le texte complet s'affiche au survol.
- **Ligne d'alignement** au-dessus de la grille : combien d'unités sont au-dessus de leurs moyennes 20 et 50, de la VWAP du jour, du POC de la séance (« toutes au-dessus », « 3 sur 4 au-dessus »…), en bleu quand tout est au-dessus, en blanc quand tout est en dessous. Ce sont des **faits, pas un signal** : aucun de ces alignements n'a été validé par le backtest du terminal (le seul filtre validé reste la tendance de fond, onglet Lecture).
- **⤢** sur un graphique : ouvre cette unité dans le graphique principal (carnet d'ordres, poches, zones, plan de trade).
- Les bougies fermées et les VWAP sont relues toutes les 15 secondes ; la bougie en cours suit le flux en direct.

## Ce qui est nouveau en V15 : un écran d'order flow

Inspiré d'un terminal d'order flow pour les contrats à terme américains (vidéo envoyée le 9 octobre 2026) et adapté à la crypto.

### Le style « nuit » (par défaut)
- Fond noir, bougies **bleues** (hausse) et **blanches** (baisse), chiffres à chasse fixe, étiquette du prix en **bleu** avec le décompte de la bougie juste dessous.
- Bouton **☾ nuit / ☀ classique** en haut à droite pour revenir à l'ancien style (vert / rouge). Le choix est gardé.

### Sur le graphique principal (cases de la barre d'outils)
- **Profil** : profil de volume de la **séance** (depuis 00 h UTC ; juste après minuit, il garde aussi la veille), collé à l'échelle des prix. Barre grise = volume échangé à ce prix (plus claire dans la zone de valeur, blanche au POC) ; bout **bleu** = les acheteurs agressifs ont dominé à ce prix, bout **blanc** = les vendeurs ; le **delta chiffré** (+1,2k, −850) est écrit aux trois prix où il est le plus marqué. Lignes et étiquettes : **POC, VAH, VAL, HAUT SÉANCE, BAS SÉANCE, CLÔTURE VEILLE**. Calculé sur les bougies de 5 minutes avec le vrai volume acheteur agressif de Binance.
- **VWAP** : VWAP du jour et ses bandes à **±1 écart-type**, avec leur étiquette au bout de la ligne.
- **Carnet** : le carnet d'ordres **en direct, aligné sur les prix du graphique** (une ligne ≈ 15 pixels, le pas s'adapte au zoom). Colonnes : **ACHAT** (taille en attente côté acheteurs, et à gauche le **nombre d'ordres** avec une barre par ordre, six au plus) · **VOL** (vendu agressivement à ce prix) · **PRIX** (la ligne du prix actuel est en bleu) · **VOL** (acheté agressivement) · **VENTE** (taille en attente côté vendeurs et nombre d'ordres). En tête : la vitesse du **ruban** (transactions par seconde). Le bouton **↺ volumes** remet à zéro le volume échangé affiché.
- **Gros ordres** : chaque transaction au-dessus du seuil est un **losange** à son prix et à son heure, avec son montant (« 120k », « 1,2M ») ; **bleu** = acheteur agressif, **blanc** = vendeur agressif. Seuil adaptatif : 99,7e centile des 5 000 dernières transactions, et au moins 250 000 $ sur BTC, 100 000 $ sur ETH, 50 000 $ sur SOL.
- En bas à gauche : **latence** du flux des transactions et du carnet (de l'heure de l'événement chez Binance à sa réception), transactions par seconde, seuil des gros ordres.
- Quand le profil et le carnet sont affichés, le graphique laisse automatiquement assez de place à droite des bougies pour ne pas les cacher.

### D'où viennent les données, et les limites
- **Taille en attente** : carnet de Binance futures, synchronisé selon la règle publiée par Binance (photo de 1 000 niveaux puis flux des différences toutes les 100 ms, nouvelle photo au moindre trou).
- **Nombre d'ordres par prix** : Binance ne publie pas le détail ordre par ordre (ce que la vidéo appelle « L3 »). Le carnet d'**OKX** sur le même perpétuel (SOL-USDT, BTC-USDT) donne, pour chaque prix, la taille **et le nombre d'ordres** : c'est lui qui alimente les barres. C'est donc le nombre d'ordres d'une autre bourse, pas celui de Binance.
- **Transactions** : flux des transactions agrégées de Binance, déjà utilisé pour le prix. Le volume échangé par prix est compté **depuis le démarrage du terminal** (ou la dernière remise à zéro), pas depuis le début de la journée.
- **Vitesse d'affichage** : les données arrivent toutes les 100 ms côté serveur ; l'écran se rafraîchit toutes les 0,4 seconde. La vidéo montre des contrats à terme CME via Rithmic, qui fournit le vrai ordre par ordre mais est payant et ne couvre pas la crypto.
- **Non vérifié contre les vrais serveurs** depuis l'environnement de développement (Binance et OKX y sont inaccessibles) : la synchronisation est écrite d'après la documentation publique et testée avec de faux serveurs. La somme de contrôle d'OKX est vérifiée ; si elle ne correspond jamais, elle est désactivée au lieu de couper le flux en boucle. Tout problème s'affiche en jaune dans l'en-tête du carnet.
- Pour couper le flux d'ordres : `TERMINAL_ORDERFLOW=0` dans `.env`. En mode « données simulées », carnet et transactions sont fabriqués pour découvrir l'écran.

## Ce qui est nouveau en V14 : quelle poche de liquidité compte le plus

### Ce que tu vois
- **Âge de chaque poche** : « formée il y a 5 h », « 3 j »… Pour une poche estimée par l'intérêt ouvert, c'est le moment où elle a commencé à peser ; pour un plus haut / plus bas, la dernière fois que le prix a traité à ce niveau (avant, l'âge des plus hauts et plus bas de la veille, de la semaine et du mois était faux : il valait « maintenant »).
- **Score d'importance sur 100**, en trois parts (barre tricolore dans les listes, détail au clic) :
  - **taille** (50 points au plus) : montant estimé face à la plus grosse poche de la fenêtre d'une heure ; pour un plus haut / plus bas, sa force (mois > semaine > jour > creux ou sommet sur 1 h, deux extrêmes au même prix comptent plus) ;
  - **confluences** (30 points au plus) : niveaux d'**autres sources** à moins de 0,3 amplitude moyenne d'une bougie d'une heure, pondérés par la période (année 10, mois 9, semaine 7, jour 4, VWAP ancré 7, POC nu 6, nombre rond 3) ; une poche estimée posée sur des ordres d'arrêt visibles (ou l'inverse) compte 10. Le détail liste chaque confluence avec son prix ;
  - **fraîcheur** (20 points au plus) : tout pour une poche de moins de 24 heures, puis de moins en moins ; plus rien après 60 jours.
- **Rang N°1, N°2…** de son côté (au-dessus / en dessous du prix). Le classement se fait toujours sur la **fenêtre d'une heure** : une poche garde **le même score et le même rang en 15 minutes, 1 heure ou 4 heures** (fini l'« aimant » qui changeait de côté avec l'unité de temps). Les N°1 et N°2 de chaque côté sont toujours affichées, même quand l'unité de temps n'en montre que trois.
- Sur les graphiques : « N°1 85 857 +1,01 % · 90/100 · 13 j ». Les listes de l'onglet **Niveaux** et de **Liquidité** sont classées par importance ; les plus hauts / plus bas sont maintenant cliquables (détail, confluences, chances d'être atteints).
- L'étiquette **AIMANT** disparaît de l'affichage : elle désignait seulement la plus grosse poche de la vue, et la mesure montre qu'aucune poche n'attire le prix (voir plus bas). Elle reste « la plus grosse poche » dans les zones de confluence.

### Ce que dit la mesure (rapport « poches », page Backtest)
BTC au comptant 2014 → octobre 2026, bougies 1 heure, uniquement avec ce qui était connu à chaque instant ; apprentissage jusqu'à fin 2021, test ensuite ; erreurs-types regroupées par jour. Poches mesurables sur 12 ans : plus hauts / plus bas de la veille, de la semaine, du mois, creux et sommets sur 1 h, extrêmes égaux (26 552 premiers contacts, 48 156 mesures d'attraction). Les poches estimées par l'intérêt ouvert ne sont **pas** testables (29 jours d'historique chez Binance) : on leur applique les mêmes règles par prudence.
- **Pas d'aimant.** Une poche est atteinte en 24 heures **moins** souvent que la même distance n'importe où (26,8 % contre 29,3 %), et **plus elle a de confluences, moins le prix va jusqu'à elle** (−5,5 points pour les fortes) : les niveaux autour l'arrêtent avant. Conséquence pratique : une poche très entourée est un **mauvais objectif** et un **bon endroit derrière lequel cacher un stop**.
- **Un petit retournement au contact.** Au premier contact, le prix se retourne 51,5 % du temps pour 48,7 % attendus (+2,8 points, confirmé sur l'apprentissage et le test ; témoin au hasard +0,6). C'est plus net pour les poches de **moins de 24 heures** (+3,3 à +3,6) et cela disparaît après 10 jours : d'où la **fraîcheur** dans le score, pas l'ancienneté.
- **Les confluences n'ajoutent presque rien au retournement** (+2,9 faibles, +2,7 moyennes, +3,4 fortes, sans écart prouvé) : d'où un poids modéré (30 points).
- **Les plus hauts / bas de la semaine et du mois ne se retournent pas plus** que ceux de la veille ou qu'un creux sur 1 h : ce sont les stops que tout le monde voit, et une fois pris, le mouvement continue aussi souvent.
- Les effets sont **petits** (quelques points de pourcentage) : le score sert à **classer** les poches entre elles, pas à prendre un trade seul.
- Relancer la mesure, par exemple sur SOL : `python tools/fetch_history.py SOLUSDT` puis `python tools/run_pocket_study.py SOLUSDT` (quelques secondes).

## Ce qui est nouveau en V13.1 : un seul biais à la fois

- **Retour aux achats et aux ventes par défaut.** Le mode « achat seulement » de la V13 n'est plus le réglage par défaut (il reste disponible dans Réglages → 4). Si la V13 l'avait écrit dans ton `.env` en enregistrant les réglages, le terminal le remet **une seule fois** sur « achats et ventes » au démarrage ; si tu le choisis de nouveau ensuite, ton choix est respecté.
- **Jamais deux biais opposés à moins de 24 heures, toutes paires confondues.** BTC et SOL bougent ensemble : une vente SOL juste après un achat BTC, c'est la même contradiction qu'une vente BTC. Tant qu'une idée est **en cours** (ordre en attente, en position, objectif 1 atteint) ou qu'elle a **moins de 24 heures**, aucune idée dans l'autre sens n'est envoyée, sur aucune paire. Dans le même sens, rien ne change (un achat BTC puis un achat SOL, c'est cohérent).
- **Entre 24 et 72 heures**, une idée dans l'autre sens n'est possible que si la précédente est terminée, avec **10 points de qualité en plus**, et son message commence par **« ⚠️ CHANGEMENT DE SENS »** : la paire, la date et le résultat de l'idée précédente, et le fait qu'elle la **remplace**.
- **Le biais du terminal est affiché** (onglet Idées, Lecture, Vue d'ensemble, Historique) : « ACHAT depuis l'idée BTC du 07/10 14:00 · aucune idée de vente, sur aucune paire, tant que l'idée BTC est en cours, et pas avant le 08/10 14:00 », ou « AUCUN » quand la prochaine idée peut aller dans les deux sens. Une configuration qui le contredit reste visible, marquée **« bloquée »** : tu sais qu'elle existe, mais ce n'est pas une idée à prendre.

## Ce qui est nouveau en V13 : l'historique, et plus de va-et-vient

### Page « Historique » (menu de gauche)
- **Chaque idée et chaque alerte envoyées**, avec la date (heure de Paris), la paire, le sens, la qualité, l'entrée, le stop, les objectifs, le **résultat** (ordre en attente, en position, objectif 1 puis sortie à l'équilibre, objectif 2, stop, expirée…) en fois le risque (R), et le message complet tel qu'il est parti sur Telegram.
- En haut : idées envoyées, part des idées gagnantes, résultat total en R, justesse des alertes, et la **courbe du résultat cumulé**.
- **La lecture du terminal jour après jour** : une fois par jour et par paire, ce que le terminal pensait (tendance de fond, squeeze, climat macro, idée du moment), puis ce que le prix a fait **24 heures, 3 jours et 7 jours après**. La tendance de fond (le seul élément validé par le backtest) est notée : ✓ si le prix est allé dans son sens.

### Sens de tes trades (Réglages → 4)
- **Achats et ventes** : réglage par défaut depuis la V13.1 (voir plus haut).
- **Achat seulement** : une configuration de **vente** n'est plus envoyée comme une idée de vente. Elle arrive comme **« 🛡 Alerte pour tes longs »** : où elle serait fausse, jusqu'où le prix peut aller, que faire si tu es long (alléger, remonter le stop, attendre avant de renforcer), et le rappel de ton idée d'achat encore ouverte avec son stop. Hors quota (les 5 idées par semaine restent des achats), une par paire et par 24 heures au plus. Son résultat est suivi : l'historique dit si elle avait raison.
- **Vente seulement** : le miroir.

### Plus de va-et-vient
- Règle renforcée en V13.1 (voir plus haut) : elle vaut désormais **toutes paires confondues**, avec un blocage strict de 24 heures. Les alertes de prudence du mode « achat seulement » ne sont pas des idées : elles ne sont pas bloquées.

### Le terminal analyse-t-il quand il est éteint ?
- **Non.** Tout tourne sur ton ordinateur, **seulement quand le terminal est ouvert** : récupération des données, calculs, idées, alertes, lecture quotidienne, mises à jour. Éteint, rien n'est calculé ni envoyé.
- Au redémarrage, il recharge l'historique des prix et **vérifie ce qui est arrivé aux idées ouvertes pendant son absence** (stop, objectifs, jusqu'à 29 jours en arrière) : les résultats de l'historique restent justes. En revanche, il **ne fabrique pas d'idées pour le passé** et une journée éteinte n'a pas de lecture.
- Pour qu'il tourne 24 h / 24 sans ton ordinateur : dossier `serveur/` (installation sur un petit serveur loué, quelques euros par mois).

### Correction
- Le graphique des parts du capital (page Backtest → « où va l'argent ») ne s'affichait pas : corrigé.

## Ce qui est nouveau en V12 : discuter avec Claude, comme sur Telegram

### Ce que ça fait
- Tu écris au **bot Telegram** (le même que pour les idées de trade) ou dans l'onglet **Discussion** du terminal : « pourquoi le BTC a perdu 2 % cet après-midi ? », « les shorts s'accumulent sur SOL ? », « qu'est-ce qui arrive cette semaine en macro ? ».
- Le terminal rassemble **tout ce qu'il sait à cet instant** : prix et variations (1 h, 4 h, 24 h, 7 jours), tendance de fond, niveaux proches, idée en cours, financement, intérêt ouvert, flux d'ordres, liquidations réelles, configuration de squeeze, options, macro (annonces passées et à venir, climat), dollar, taux, actions, or, volatilité, peur et avidité, où est l'argent.
- Il repère les **mouvements marquants des dernières 24 heures** (plus forte baisse, plus forte hausse) et ce qui s'est passé **pendant** chacun : intérêt ouvert, part d'acheteurs agressifs, volume par rapport à la normale, liquidations longs / shorts, mouvement des autres marchés sur la même fenêtre, annonces macro proches. Heures en heure de Paris.
- **Claude** (Claude Opus 5.5 par défaut) répond en français, d'abord en quelques phrases puis le détail, en séparant ce qui est mesuré de ce qui est une hypothèse, et cherche l'actualité sur le web quand les données ne suffisent pas (sources citées). Il garde le fil des 6 derniers échanges ; `/reset` repart de zéro.
- Telegram : **seuls tes messages** (ton chat id) reçoivent une réponse ; commandes `/aide`, `/reset`, `/cout`.

### À faire une seule fois
1. Crée une **clé API** sur **console.anthropic.com** → **API Keys** → **Create Key**, et ajoute du crédit (**Billing**). C'est payant à l'usage et séparé de l'abonnement Claude : environ 5 à 15 centimes par question avec Claude Opus 5.5 (moins avec Claude Sonnet 5.5 ou Claude Haiku 4.5), plus environ 1 centime par recherche web.
2. Dans le terminal : **Réglages → 7. Discussion avec Claude** → colle la clé → **Installer le module Claude** (le module officiel `anthropic`, installé une fois avec `pip`) → **Enregistrer**.
3. Pose ta question dans l'onglet **Discussion** ou envoie-la à ton bot Telegram.

### Garde-fous
- **Budget mensuel** (20 $ par défaut, réglable ; 0 = sans limite) : au-delà, le terminal ne pose plus de question à Claude jusqu'au mois suivant. La dépense du mois s'affiche dans l'onglet et avec `/cout`.
- La clé reste dans `.env`. Les données du terminal ne partent vers l'API de Claude qu'au moment d'une question.
- Les réponses sont des lectures du marché, pas des conseils ; seule la tendance de fond est validée par le backtest, et Claude a pour consigne de le rappeler plutôt que de présenter un indicateur comme prédictif.
- **Vérifié** : la forme des requêtes avec le module officiel `anthropic` (1.11) contre un faux serveur (modèle, recherche web, reprise d'une réponse mise en pause, repli en cas de refus, erreurs : clé refusée, crédit épuisé, surcharge), et le contexte construit sur les données simulées. **Pas vérifié ici** : une vraie réponse de Claude (aucune clé dans l'environnement de développement) et l'écoute Telegram contre les vrais serveurs.

## Ce qui est nouveau en V11 : le terminal se met à jour tout seul

### À faire une seule fois
- **Installe cette version à la main**, une dernière fois (ZIP habituel, en gardant ton dossier `data_local` et ton fichier `.env`), puis lance-la comme d'habitude. C'est tout : le dépôt est public, **aucun jeton n'est nécessaire**.
- Pour voir où en est le terminal : **Réglages → 6. Mises à jour automatiques** → **Vérifier maintenant**.
- Jeton GitHub **facultatif**, seulement si le dépôt redevient privé un jour : GitHub → **Settings** → **Developer settings** → **Fine-grained tokens** → **Generate new token**, dépôt `DEV-claude`, **Contents : Read-only** ; à coller dans le Réglage 6. Sans jeton, GitHub accepte 60 requêtes par heure : le terminal en utilise une à deux par vérification (les versions déjà vues sont gardées en mémoire).

### Ensuite, plus rien à faire
- Toutes les 30 minutes, le terminal regarde la dernière version publiée (« auto » = la branche du dépôt la plus récemment mise à jour qui contient le terminal : chaque session de travail publie sur sa propre branche).
- S'il y en a une nouvelle : il la télécharge, **vérifie** qu'elle est complète, que tout le code se compile et que les modules principaux se chargent, **sauvegarde** la version actuelle (`.update/backup`), remplace les fichiers, puis **redémarre tout seul dans la même fenêtre**. La page du navigateur se recharge et un message indique la version installée.
- Si la nouvelle version s'arrête en erreur au démarrage, **l'ancienne revient automatiquement** et le terminal repart avec elle.
- **Jamais touchés** : `data_local/` (données, journaux, tes rapports) et `.env` (réglages, jetons). Pas de message Telegram à chaque relance (Telegram reste réservé aux idées de trade).
- Le lanceur (`.bat` / `.command`) en cours d'utilisation n'est pas remplacé pendant que le terminal tourne : s'il change, la nouvelle copie attend dans `.update/lanceurs/` (le Réglage 6 le signale).
- Tu préfères garder la main : décoche « Installer automatiquement » ; le terminal te dit alors qu'une version est disponible et tu cliques **Installer maintenant**.
- Lancé avec `python run.py --no-supervisor`, ou depuis un dossier git (utilise alors `git pull`), le terminal ne se met pas à jour tout seul.
- **Vérifié** : contre le vrai GitHub (dépôt public, sans jeton) : vérification, téléchargement, contrôles, remplacement d'un fichier modifié, sauvegarde ; et, contre un faux serveur GitHub, la relance complète, le rechargement de la page et le retour automatique à l'ancienne version. Si ça bloque sur ton PC, le Réglage 6 affiche l'erreur en clair.

## Ce qui est nouveau en V10 : où est l'argent, l'or, et les squeezes

### Où est l'argent (carte du capital et rotation)
- **Carte du capital** (carte « Où est l'argent » dans **Lecture**) : parts du bitcoin, de l'ETH, d'un panier de 10 altcoins (BNB, XRP, ADA, DOGE, TRX, LINK, LTC, BCH, XLM, ATOM) et des stablecoins (USDT + USDC + DAI, la « poudre sèche »), variations à 7 et 30 jours en points, performance relative face au bitcoin (ETH, altcoins, SOL, or) et une phrase de lecture. Données libres Coin Metrics (capitalisations estimées comparables depuis juin 2019). Le panier n'est pas tout le marché : il mesure des **parts**, pas des montants.
- **Or** : jeton **PAXG** (1 jeton = 1 once d'or, coté 24 h / 24, week-ends compris) depuis février 2020 : prix, variation à 30 jours, position face à sa moyenne 200 jours, corrélation avec le bitcoin sur 90 jours.
- **Ce que la mesure dit** (page **Backtest → Rapport → où va l'argent**, 9 indicateurs de rotation × 3 cibles × 3 horizons = 81 mesures, apprentissage jusqu'en 2022, test depuis 2023) : **aucun lien ne dépasse le seuil du hasard** : savoir où va le capital ne dit pas, de façon prouvée, où ira le prix du bitcoin, ni si les altcoins feront mieux, ni si l'or battra le bitcoin. Seul indice (sous le seuil) : or contre bitcoin sur 30 jours → altcoins contre bitcoin.
- **Bitcoin et or : l'asymétrie n'est pas démontrée.** Quand l'or monte, le bitcoin bouge de +0,48 pour 1 de l'or ; quand l'or baisse, de +0,64 (l'écart de −0,16 n'est pas significatif, t = −0,6). La corrélation moyenne sur 90 jours est de +0,15 (de −0,38 à +0,51) : le lien existe, il est faible et change de signe. Les jours de choc de l'or (± 1,5 %), le bitcoin suit **le même jour** (+1,2 % / −1,6 %) mais pas le lendemain : le lien est simultané, pas prédictif. La situation géopolitique n'est pas mesurable en direct : on la voit à travers l'or, le pétrole, la volatilité et le dollar (rapport « indicateurs »).
- **Relancer** : `python tools/run_rotation.py` (télécharge les jeux libres, quelques secondes, aucune clé).

### Delta, CVD, volume et squeezes
- **Lecture en direct** (carte **Flux et squeeze** dans **Lecture**, et pastille en haut du Desk) : trois mini-graphiques alignés sur 72 heures (prix, intérêt ouvert, CVD) avec leur étiquette, comme sur Velo (« baisse lente », « levier en hausse », « vendeurs agressifs »), et la configuration du moment : **des shorts s'accumulent** (intérêt ouvert en hausse, flux vendeur, prix qui ne baisse pas assez : un rebond les forcerait à racheter), **des longs s'accumulent** (le miroir), **squeeze en cours** (le prix s'envole ou s'effondre pendant que l'intérêt ouvert chute), divergence prix / flux, « effort sans résultat » (beaucoup de volume, peu de mouvement). Delta réel (volume acheteur agressif de Binance) ; les écarts sont mesurés en écarts-types des 30 derniers jours.
- **Dans les idées de trade** : si les shorts s'accumulent et que l'idée est une vente (ou l'inverse pour les longs), un avertissement est ajouté. **Jamais dans le score** : rien ici n'est prouvé.
- **La mesure** (page **Backtest → Rapport → delta, CVD et squeezes**) : variables horaires sans regard sur le futur (déséquilibre du flux, prix contre flux, delta récent contre CVD de fond, volume anormal, effort sans résultat, et avec l'intérêt ouvert : carburants de short et de long squeeze, squeeze en cours, financement), **deux cibles** : le rendement à 6, 24 et 72 h et l'**ampleur** du mouvement suivant (un squeeze est un mouvement plus grand que d'habitude), référence « prix seul », tableau d'événements (décile haut / bas, part de gros mouvements dans chaque sens), témoin au hasard, apprentissage / test.
- **Résultat livré (BTC, 2014-2026, delta ESTIMÉ, test sur 4,8 ans)** : aucune variable de flux ne prédit le **sens** du prix (0 sur 27 mesures). Le **volume anormal** prédit l'**ampleur** du mouvement suivant, et fait mieux que le mouvement des 24 dernières heures à lui seul : c'est le seul lien solide, il dit « ça va bouger », pas « dans quel sens ». Les carburants de squeeze **ne sont pas mesurables avec ce jeu de données** (pas d'intérêt ouvert avant décembre 2021 et pas d'historique libre accessible d'ici).
- **Pour mesurer les squeezes avec le vrai delta, l'intérêt ouvert et le financement (≥ 4 ans, depuis décembre 2021)** : `python tools/fetch_history.py BTCUSDT --since 2021-12 --metrics` puis `python tools/run_squeeze_study.py BTCUSDT` (idem `SOLUSDT`). Le rapport écrit dans `data_local/reports/` remplace celui livré. **Non vérifié contre les vrais serveurs depuis l'environnement de développement** (aucun accès à Binance Vision) : les formats sont écrits d'après la documentation publique et testés sur des fichiers imités ; une erreur lisible s'affiche si un format diffère.

### Décompte de bougie et affichage
- **Décompte sous le prix** sur chacun des trois graphiques (échelle de droite) : temps restant avant la clôture de la bougie en cours, `mm:ss` sous une heure, `h:mm:ss` au-dessus, de la même couleur que l'étiquette du prix (vert / rouge selon la bougie), comme sur TradingView.
- **Étiquettes qui ne se recouvrent plus** : zones, plus hauts / plus bas et noms de niveaux se décalent les uns derrière les autres au lieu de se superposer.
- La ligne de prix prend la couleur de la bougie (comme sur TradingView) ; le lexique explique le delta, le CVD, l'intérêt ouvert et les squeezes.

## Ce qui est nouveau en V9 : plus de données, moins de bruit

### L'écran de lecture (onglet **Lecture**, par défaut)
Une page, dans l'ordre où l'on décide : **tendance de fond** (le seul filtre validé par le backtest), **idée de trade** en cours (ou « aucune »), **prochaine annonce**, **niveaux proches**, puis trois blocs : *Positionnement* (financement comparé entre bourses, Open Interest, flux d'ordres, liquidations réelles), *Dérivés* (options du bitcoin : max pain, put/call, volatilité implicite DVOL, base des futures), *Macro et liquidité* (macro, Fear & Greed, dominance pour les alts, offre de stablecoins). **Chaque ligne porte son niveau de preuve** : « validé » (mesuré par le backtest du terminal), « indice » (même signe sur l'apprentissage et le test, sans preuve), « contexte » (lecture seule, aucun avantage démontré). Le biais statistique non validé n'occupe plus qu'une ligne.
- **Épuration** : le panneau de droite ne montre plus que Lecture · Idées · Niveaux · Stratégie. Contexte, Stats, Liquidité, VP, Alertes, ainsi que les pages « Biais & probabilités » et « Dominance », sont derrière **Détails ▾** (ou « Mode détaillé » dans le menu de gauche). La vue d'ensemble garde l'essentiel (biais non validé réduit à une ligne, niveaux proches, plus de carte d'alertes).

### Les nouvelles données (gratuites, sans clé)
- **Jeux libres sur GitHub** (téléchargés dans `data_local/opendata/`) : **Coin Metrics** (`coinmetrics/data`, CC BY-NC 4.0) pour le BTC en chaîne depuis 2009 (flux vers et depuis les bourses, offre sur les bourses, MVRV, hashrate, adresses actives, transactions, frais, volume) et l'offre de USDT, USDC et DAI ; **`datasets/*`** pour le VIX (depuis 1990), le pétrole WTI et Brent, le gaz naturel et les taux de change, dont on reconstruit un **indice dollar** (formule du DXY ; vérifié contre des niveaux connus : environ 80,6 en juin 2014, 97 en juin 2017, 103 en juin 2022).
- **Dérivés en direct** (`data/derivs.py`) : Deribit (options BTC / ETH : intérêt ouvert par strike et échéance → max pain, put/call, murs d'options ; DVOL ; base annualisée des futures), Bybit, OKX et Hyperliquid (financement, Open Interest, prix de marque de la paire suivie). **Ces API n'ont pas pu être appelées depuis mon environnement** (seuls les dépôts GitHub y sont joignables) : le code suit leur documentation publique et il est testé sur de faux serveurs, mais **pas encore sur les vrais**. Une réponse inattendue donne une erreur lisible dans l'état de santé, jamais un faux chiffre. Désactivable : `TERMINAL_DERIVS=0`.
- **Le terminal enregistre ces séries** toutes les 15 minutes (`data_local/history/derivs/<PAIRE>.csv`) : il n'existe pas d'historique libre du financement multi-bourses ni des options, donc c'est le seul moyen de les backtester un jour.

### Ce que la mesure dit des indicateurs (BTC, 2013-2026, 25 indicateurs × 3 horizons)
Méthode : chaque indicateur est replacé dans l'historique de ses seules valeurs passées, puis relié au rendement du bitcoin à 7, 14 et 30 jours (un jour de décalage), avec une erreur-type robuste, un apprentissage jusqu'en 2021 et un test depuis 2022. Un **témoin** (le même signal décalé au hasard) donne le seuil du hasard : |t| ≥ 3,1 dans 5 % des cas, ≥ 4,0 dans 1 %.
- **Aucun indicateur ne dépasse le seuil à la fois sur l'apprentissage et sur le test.**
- **À surveiller** (même signe partout, sous le seuil) : momentum 30 et 90 jours et écart à la moyenne 200 jours (c'est la tendance de fond, déjà dans le terminal), **multiple de Puell** (revenu des mineurs ; le signe est l'inverse de l'intuition : un Puell haut précède plutôt des rendements plus hauts) et **la variation sur 30 jours de l'offre de stablecoins** : écart de +9,4 % à 14 jours à l'apprentissage (t = 2,2) et +8,3 % sur le test (t = 2,2), +21,5 % puis +16,1 % à 30 jours : le seul qui garde la même ampleur hors échantillon. Ce n'est **pas** une preuve (75 mesures, un seuil à 4,0), c'est un indice : il apparaît donc dans la Lecture avec l'étiquette « indice ».
- **Rien de prouvé** : MVRV (fort à l'apprentissage, nul sur le test), flux nets vers les bourses, offre sur les bourses, hashrate, adresses actives, frais, volume, **VIX, pétrole Brent, gaz naturel, dollar**. La part de l'offre détenue sur les bourses (−25 % à 14 jours à l'apprentissage, t = −3,2) disparaît sur le test (−4,7 %, t = −0,7).
- **Limite de puissance** : l'écart à la moyenne 200 jours, effet connu, reste lui-même sous le seuil (t = 2,5 puis 1,4) : avec une dizaine d'années de données journalières, ce test ne détecte que des effets forts. « Pas de preuve » ne veut pas dire « pas d'effet ».
- Page **Backtest → Rapport → indicateurs** : tableau complet (valeur du jour et position dans l'historique, écart et t à l'apprentissage et au test, rendement par quintile, sens attendu ou non, verdict), horizon au choix.

### Corrections et précisions
- La barre d'onglets du panneau de droite ne coupe plus « Alertes » ; l'onglet **Stratégie** est mémorisé au rechargement.
- Décimales à la française partout (le texte de l'analyse macro, du biais et de la dominance, les consensus d'annonces, les axes des graphiques affichaient « 0.3 » ou « 58.59 % »).
- Le téléchargement des jeux libres tourne dans un fil à part (une connexion lente ne bloque plus le rafraîchissement) ; les adresses des bourses sont injectables, les tests restent hermétiques.
- Un test a attrapé une erreur de signe dans mon calcul de l'indice dollar (les taux de change du jeu de données sont en monnaie locale pour 1 USD : tous les exposants du DXY sont positifs) ; corrigé avant publication du rapport.

### Relancer / backtester plus tard
```
python tools/run_indicators.py                 # quelques secondes ; télécharge les jeux libres puis écrit data_local/reports/indicators_BTC.json
python tools/run_derivs_study.py SOLUSDT       # après 3 à 4 semaines d'enregistrement : financement, OI, options, base contre le prix futur
```

## Ce qui est nouveau en V8 : les VWAP ancrés sur un mouvement d'au moins −5 %

### Ce qui est testé
Un mouvement est détecté **sans regarder le futur** (zigzag confirmé) : un sommet n'est connu qu'une fois le prix redescendu d'au moins 5 % depuis lui, un creux une fois remonté d'au moins 5 % depuis lui. Deux VWAP ancrés en sortent : **sur le sommet de la baisse** (le prix est dessous, résistance) et **sur le creux** (le prix est dessus, support). Ils sont suivis 30 jours. Un « contact » est une bougie 1 h fermée qui touche le VWAP ancré, le sens étant le côté de la clôture (même convention que tes autres niveaux). Même chose avec des mouvements d'au moins 8 % et 12 %.

### Le résultat, sans détour : le prix ne réagit pas à ces niveaux
- **Réaction** (BTC 2013-2026, 98 078 contacts de 1 530 sommets et 1 521 creux) : après un contact, le rendement à 4 / 24 / 48 h dans le sens de la clôture, moins la dérive moyenne du marché, ne montre **aucun écart solide à 24 h** (|t| ≥ 3) sur les 12 lignes (sommet ou creux × la clôture tient ou traverse × premier contact ou suivants). Même résultat à 8 % et à 12 %. Le plus marqué, un rejet sous le sommet, donne l'inverse de l'attendu (−0,22 % à 24 h dans le sens de la vente : le prix monte un peu plus que la dérive) et reste insignifiant (t = −1,5).
- **Probabilité d'aller d'abord d'1 ATR dans le sens de la clôture** (50 % = hasard) : de 43 % à 54 % selon les cas, contre 47 % à 53 % pour des instants au hasard. Pas de différence nette.
- **Seule trace** : à 4 h, après une clôture qui traverse le VWAP ancré, le prix revient en moyenne de 0,12 % (t ≈ −3,5, pour le sommet comme pour le creux). Moins que les frais d'un aller-retour au marché (0,14 %) : pas exploitable.
- **Trades** (mêmes règles que pour ta stratégie, 12 sorties, 26 filtres, deux sens, 156 combinaisons) : la règle littérale fait **−0,01 R par trade** (1 939 trades ; +0,01 sur 2013-2021, −0,05 sur 2022-2026). La meilleure variante sur l'apprentissage (« volume ≥ 1,5 × la moyenne et la clôture traverse », stop 5 ATR, objectif 2 R, 48 h) fait +0,05 R puis **+0,02 R** sur le test (intervalle à 90 % de −0,05 à +0,08). Sa statistique t sur l'apprentissage (1,7) est **en dessous** de ce que le hasard donne en essayant 156 combinaisons (≈ 3,2) : aucune variante n'atteint t = 3. Stop serré (sous la structure) : −0,10 R par trade en moyenne ; stop à 5 ATR : le moins mauvais, comme pour tes autres niveaux.

### Ce que ça veut dire
Sur BTC, un VWAP ancré sur le sommet ou le creux d'un mouvement de 5 % ou plus **n'est pas un niveau où le prix réagit de façon mesurable** (ni rejet, ni rebond, ni cassure), ni plus ni moins que n'importe quelle autre ligne autour de laquelle le prix oscille. Cela ne dit rien de ton tri à l'œil (mouvement que tu juges important, contexte, moment), ni de SOL.

### Dans le terminal
- **Onglet Stratégie** : tableau des VWAP ancrés sur mouvement ≥ 5 % encore suivis (sommet ou creux, prix de l'ancre, VWAP ancré, distance en ATR, âge, ampleur de la baisse, ▲ / ▼ de la dernière bougie 1 h fermée), plus le verdict du backtest. Aucune alerte Telegram.
- **Page Backtest, menu « Rapport » → « VWAP ancrés sur un mouvement de 5 % ou plus »** : verdict, tableau de réaction (par ancre, par réaction, par contact, apprentissage / test, probabilité d'1 ATR d'abord, selon la taille du mouvement), variante retenue, classement, sorties, méthode.

### Relancer sur SOL
```
python tools/fetch_history.py SOLUSDT
python tools/run_avwap_swing.py SOLUSDT      # 5 à 20 minutes ; écrit data_local/reports/avwap_SOL.json ; --pct 5 règle la taille du mouvement
```

## Ce qui est nouveau en V7 : ta stratégie, traduite en règles et mesurée

### La stratégie testée
Sur chaque bougie **1 h ou 4 h** qui touche un **VWAP ou un VWAP ancré** de la semaine ou du mois (VWAP de la semaine / du mois, ancré au début de la semaine dernière / du mois dernier, sur le plus haut / plus bas de 7 jours, sur le plus haut / plus bas de 30 jours), on regarde où la bougie **clôture** : au-dessus = achat, en dessous = vente. Entrée au marché à l'ouverture de la bougie suivante. Le **volume profile** sert à situer la clôture face à la **VAL / VAH** (zone de valeur de la semaine ou du mois, en cours ou précédent) : *réintégration* (la clôture revient dans la zone) ou *rejet* (la clôture reste hors de la zone, dans le sens du trade). Objectif sur les **poches de liquidité** visibles dans le prix, position gardée **24 h, 48 h au plus** (et la variante « 24 h prolongées à 48 h s'il y a du volume »).

### Protocole (fixé avant de regarder les résultats)
1. 178 858 signaux de 2013 à octobre 2026 (BTC réel, bougies d'une minute), **dans les deux sens** : suivre la clôture (ta règle) et prendre le contre (variante inverse, pour la couverture).
2. **48 sorties** : stop sous la structure ou à 1,5 / 3 / 5 ATR (amplitude horaire), objectif sur la poche, la poche sinon 2 R, 2 R, ou moitié à chaque poche, durée 24 h / 48 h / 24 h prolongées. Choisies sur la règle littérale, **apprentissage 2013-2021 seulement**.
3. **42 filtres** (échelle, niveau, volume, VAL / VAH de quatre profils, tendance de fond) × 3 meilleures sorties × 2 sens = **252 combinaisons**, classées sur l'apprentissage.
4. La meilleure est jugée **une seule fois** sur 2022-2026 (jamais vu), comparée à des trades au hasard de même forme dans la même tendance, avec sensibilité aux frais et résultat par période et par année.
5. **Couverture** : corrélation hebdomadaire de toutes les variantes avec la principale, portefeuille « principale + 25 / 50 / 100 % de la variante », choix sur l'apprentissage, jugement sur le test.

### Le résultat, sans détour
- **Ta règle telle que tu la décris n'a pas d'avantage** : +0,00 fois le risque par trade après frais (3 673 trades ; +0,05 sur 2013-2021, **−0,07 sur 2022-2026**). Avec des stops serrés (sous la structure ou 1,5 ATR) elle perd 8 % du risque par trade en moyenne.
- **Les sorties qui comptent** : les stops larges (3 à 5 ATR) ramènent la règle à zéro ; l'objectif sur la poche de liquidité fait moins bien qu'un objectif fixe de 2 fois le risque (−0,09 contre −0,01) ; garder 48 h vaut mieux que 24 h, et **prolonger seulement s'il y a du volume ne fait pas mieux que garder 48 h**.
- **Une condition ressort : le rejet de la zone de valeur du volume profile.** Quand la clôture qui touche le niveau se fait **hors de la VAL / VAH de la semaine en cours, dans le sens du trade**, avec stop à 5 ATR, objectif 2 R et 48 h : **+0,15 R par trade sur 2013-2021, +0,03 R sur 2022-2026** (702 trades, intervalle à 90 % de −0,03 à +0,09). Positive dans les trois périodes, dans les achats (+0,13) comme dans les ventes (+0,08), et meilleure que 98 % des trades tirés au hasard dans la même tendance sur le test (le hasard fait −0,05).
- **Mais c'est un avantage faible qui s'érode, pas démontré** : positive chaque année de 2013 à 2022, puis +0,20 (2024) entre trois années à −0,04 / −0,06 / −0,05. La statistique t passe de 5,7 à 0,9. Parmi les 62 combinaisons qui avaient un t ≥ 3 à l'apprentissage, 27 seulement restent positives sur le test.
- **Frais** : 0,16 R avant frais, 0,11 R après sur toute la période (2,8 trades par semaine en moyenne, 39 h de détention).
- **Couverture : aucune variante ne protège.** Sur 16 variantes candidates et 48 dosages, **aucune** ne réduit la baisse maximale du test d'au moins 1 point. Le miroir (même signal, sens inverse) est bien anti-corrélé (−0,6) mais perd 15 % par an seul : c'est une prime d'assurance sans indemnité. Choisi sur l'apprentissage, il fait passer la baisse maximale du test de 20 % à 23 % et le rendement annualisé de +4 % à +0,3 %.

### Ce que ça veut dire, honnêtement
Le seul élément de ta lecture qui survit est **le rejet hors de la zone de valeur** (le prix qui continue hors du volume profile plutôt que de le réintégrer), avec des **stops larges et 48 h**. Le gain moyen est faible et il a fondu depuis 2022. Les rebonds sur VWAP et VWAP ancrés seuls, les poches de liquidité comme objectif et la prolongation selon le volume n'ont pas montré d'avantage. Cette étude mesure **la version mécanique** (tous les signaux, sans le tri que tu fais à l'œil : contexte macro, qualité du rebond, moment) sur **BTC au comptant** ; elle ne dit pas ce que vaut ton tri, ni ce que donne SOL avec du levier.

### Dans le terminal
- **Onglet Stratégie** (panneau de droite) : lecture **en direct** de tes règles. Dernières bougies 1 h et 4 h fermées (touchent-elles un niveau, de quel côté clôturent-elles, volume), tableau des 8 niveaux avec ▲ / ▼, VAL / POC / VAH des quatre profils avec *réintégration* / *rejet*, poches de liquidité au-dessus et en dessous. **Aucune alerte Telegram** : la stratégie n'a pas d'avantage démontré, c'est un tableau de lecture, comme les autres alertes restent réservées aux idées du terminal (tendance de fond).
- **Page Backtest, menu « Rapport » → « ta stratégie VWAP / profil de volume »** : verdict, variante retenue (par période, par année, frais, témoin), classement des 25 meilleures variantes (et des 252), les 48 sorties, la couverture avec courbes, méthode et limites.

### Relancer sur SOL
```
python tools/fetch_history.py SOLUSDT
python tools/run_strategy.py SOLUSDT      # 15 à 40 minutes, 3 à 6 Go de mémoire pour 13 ans ; moins pour SOL
```
Le rapport (`data_local/reports/strategy_SOL.json`) apparaît dans la page Backtest et l'onglet Stratégie le cite pour SOL. `--start 2021-01-01 --split 2024-01-01` pour choisir la période d'apprentissage.

### Limites
Ordres au marché, frais 0,05 % + glissement 0,02 % + financement 0,01 % par 8 h. BTC Bitstamp (volume acheteur agressif estimé). Les poches estimées par l'Open Interest et le contexte macro ne sont pas testés. 252 combinaisons sont fortement liées entre elles (même famille « rejet du profil ») : la statistique t de la meilleure à l'apprentissage est gonflée par le choix, d'où le test. La couverture est calculée sur comptes séparés (une position opposée ne compense pas l'autre : les frais sont comptés deux fois, c'est prudent). Un résultat passé n'est pas une garantie.

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

### Vérifications de robustesse faites
- **Biais de calcul** : niveaux, tendance, ATR et poches n'utilisent que des bougies fermées ; un pivot n'est connu que trois bougies après (test automatique). Un test sur marche aléatoire ne trouve aucun avantage (la machine à tester ne fabrique pas de faux signaux).
- **Exécution des ordres limites** : supposés exécutés dès que le prix les touche (optimiste). En exigeant que le prix les dépasse de 0,1 %, la règle actuelle passe de +0,134 à +0,125 par trade : le résultat n'en dépend pas.
- **Erreur corrigée en route** : une première version de l'étude d'événements moyennait par jour au lieu de par événement et faisait apparaître un faux retour à la moyenne vers le VWAP du jour ; la correction (moyenne par événement, erreur-type robuste par jour) le fait disparaître.

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
`TERMINAL_SIGNALS` (1/0), `TERMINAL_ALERT_MODE` (ideas), `TERMINAL_SIGNAL_MIN_SCORE` (60), `TERMINAL_SIGNAL_MAX_WEEK` (5), `TERMINAL_SIGNAL_MAX_PER_SYMBOL` (3 : au plus 3 des 5 idées pour une même paire quand tu en suis plusieurs, pour que SOL ne soit pas privée de places par BTC), `TERMINAL_SIGNAL_MIN_STRUCT` (7), `TERMINAL_SIGNAL_LEVERAGE` (10, pour le calcul de liquidation affiché), `TERMINAL_SIGNAL_VALID_HOURS` (48), `TERMINAL_SIGNAL_TREND_GATE` (1 : seulement les idées dans le sens de la tendance de fond). Avis X : `TERMINAL_X_BEARER_TOKEN`, `TERMINAL_X_ACCOUNTS`, `TERMINAL_X_POSTS` (10), `TERMINAL_X_ON` (1).

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
run.py              point d'entrée (relance le terminal après une mise à jour)
updater.py          mise à jour automatique depuis GitHub : vérification, contrôles, sauvegarde, remplacement, retour arrière (V11)
Lancer-Terminal-*   lanceurs à double-cliquer
config.py           configuration (.env) et écriture des réglages
engine/             calculs : profils de volume (auto et choisis), séries VWAP / AVWAP, périodes, POC nus, poches de
                    liquidation, confluences, ATR, statistiques (rebond / cassure, atteinte, balayages, Wilson), macro,
                    dominance, biais validé en avançant, synthèse ; stance.py (lecture des avis X) ; signals.py (idées de trade : poids, zones, stop,
                    objectifs, score, textes), sigtest.py (rejeu historique face au hasard) ; V6 : fine.py (séries 1 min à 1 h avec sommes cumulées),
                    liqsweep.py (poches visibles dans le prix, balayages), cvd.py (déséquilibre, divergences, absorption), trend.py (tendance de fond),
                    backtest.py (génération des idées, exécution 1 min, frais, métriques, témoins), study.py (rapport complet), history.py (archives Binance) ;
                    V7 : vwapstrat.py (signaux de ta stratégie, 48 sorties, simulation 5 min), hedge.py (corrélation et portefeuille de couverture), stratstudy.py (protocole, variantes, verdict) ;
                    V8 : swingavwap.py (zigzag confirmé, VWAP ancrés sur sommet / creux, contacts), swingstudy.py (réaction du prix et trades) ;
                    V9 : indicators.py (25 indicateurs journaliers), indstudy.py (mesure avec témoin), derivstudy.py (mesure des dérivés enregistrés), lecture.py (écran de lecture) ;
                    V12 : explain.py (mouvements récents et faits qui les accompagnent) ;
                    V10 : rotation.py et rotationstudy.py (carte du capital, rotation, or), goldbtc.py (asymétrie bitcoin / or), squeeze.py (delta, divergences, squeezes), squeezestudy.py (mesure) ;
                    V14 : pocketrank.py (importance d'une poche : taille, confluences, fraîcheur), pocketstudy.py (mesure sur l'historique) ;
                    V15 : sessionvp.py (profil de volume de la séance avec part acheteuse)
data/               sources : simulée et Binance ; V15 : orderflow.py (carnet Binance synchronisé, nombre d'ordres OKX, ruban, gros ordres) ; historique en mémoire et contexte (funding, L/S, spot, Coinbase) ; social.py (posts X, facultatif) ; V9 : derivs.py (options, DVOL, base, financement multi-bourses), opendata.py (jeux libres GitHub)
alerts/             règles d'alerte, envoi Telegram ; trades.py (quota hebdomadaire, suivi et journal des idées) ; assistant.py (discussion avec Claude, V12) ; readings.py (lecture quotidienne et ce que le prix a fait ensuite, V13)
service.py          relie les données et les moteurs, fabrique l'état JSON
server.py           serveur local : API, réglages, sécurité
web/                interface : index.html + style.css ; app.js (Desk, état, alertes), panels.js (les trois graphiques),
                    overview.js (vue d'ensemble), signals.js (idées de trade), analysis.js et charts.js (analyse, graphiques SVG) ;
                    TradingView Lightweight Charts (vendor/)
tools/              run_pocket_study.py (V14), run_rotation.py, run_squeeze_study.py (V10), run_indicators.py, run_derivs_study.py (V9), fetch_history.py (historique 1 min Binance), run_study.py (rapport de backtest des idées du terminal), run_strategy.py (rapport de ta stratégie VWAP / profil de volume) et run_avwap_swing.py (VWAP ancrés sur un mouvement de 5 % ou plus)
reports/            rapports livrés (BTC) : backtest_BTC.json (idées du terminal), strategy_BTC.json (ta stratégie) et avwap_BTC.json (VWAP ancrés sur un mouvement) indicators_BTC.json (indicateurs en chaîne et macro), rotation_BTC.json (où va l'argent, or) et squeeze_BTC.json (delta, CVD, squeezes) ; les tiens vont dans data_local/reports/
serveur/            installation sur un serveur 24 h/24 (script et guide)
tests/              tests automatiques (plus de quatre cents)
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
