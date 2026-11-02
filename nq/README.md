# NQ Scalp Terminal (V0.6)

Un terminal **local** (il tourne uniquement sur ton PC) pour scalper le **Nasdaq-100 en futures (NQ / MNQ)** avec un compte prop firm **Lucid 25K**. Même esprit que le terminal crypto (VP, CVD, VWAP, niveaux, lecture honnête), refait pour le scalping : horloge de New York, séances du CME, order flow à la transaction près, et un moteur de risque qui connaît les règles du compte.

> **État actuel : la carte, des setups mesurables, et l'outil pour les mesurer.** Le terminal te donne la carte (niveaux, flux, profil, VWAP, risque du compte), propose des **setups** scorés qui intègrent les règles Lucid, et les **rejoue** sur l'historique (backtest prudent, Monte Carlo de l'évaluation, test de robustesse). Les données par défaut sont **simulées** : rien à l'écran ne dit quoi que ce soit du vrai marché tant que tu n'as pas branché tes vraies transactions (NinjaTrader, voir plus bas). **Aucun setup n'est validé tant qu'il n'a pas été mesuré sur plusieurs semaines de vraies données.**

**Nouveau en V0.6** :
- **vraies données sans réglage** : si l'enregistreur NinjaTrader tourne (fichier `Documents\NQ-Terminal\nq-ticks.csv`, OneDrive compris), le terminal le prend tout seul ; onglet **Outils → Source** pour voir l'état du fichier, en choisir un autre ou revenir au simulé, **sans redémarrer** ;
- **graphique pleine largeur** : le panneau de droite est devenu un tiroir **☰ Outils**, fermé par défaut (Lecture, Setups, Niveaux, GEX / OI, Compte, Plan, Backtest, Footprint, Source) ;
- **vues en onglets** (« Vue 1 · 1m », « Vue 2 · 5m », **＋ Vue**) : chaque onglet garde son unité de temps et ses indicateurs ;
- **menu ▦ Indicateurs** rangé par sections, avec défilement et recherche ;
- **profils superposables** (séance, Globex, veille, semaine, semaine précédente, mois, mois précédent), chacun dans sa couleur ;
- **CVD en ligne ou en bougies**, delta par barre en histogramme, **delta chiffré sous les bougies** ;
- **GEX** des options NDX (ou QQQ) : call wall, put wall, **zéro gamma (HVL)**, strikes majeurs, régime, profil par strike ; **intérêt ouvert** du NQ (OI) écrit par l'enregistreur ;
- **absorptions en marqueurs « ABS »** au-dessus / au-dessous des bougies, triées : seulement **les meilleures** par défaut (fortes, répétées ×2, testées, ou faites sur un niveau clé ★) ; plus de bulles par défaut.

**V0.5** : **absorptions mesurées au prix** dans le footprint (zone tracée jusqu'à sa cassure, tests et recharges comptés), **profils semaine et mois** (et précédents), un **second profil** à gauche du graphique, **VWAP de la semaine et du mois** avec bande ±1σ, **POC vierges** (jour et semaine), **single prints et queues** (lecture TPO, comblés ou non), **graphiques supplémentaires** (« + Graphique », 3 au plus, chacun sa propre unité de temps), historique gardé réglable (`NQ_HISTORY_DAYS`). Correction : les bulles des gros ordres s'affichaient toutes sur la même bougie.

**V0.4** : backtest plus réaliste (la barre d'entrée est vérifiée, un objectif doit être *dépassé* d'un tick pour être rempli, un stop sauté par un écart est exécuté à l'ouverture, plancher touché *en cours* de journée), **probabilité de valider l'évaluation** (Monte Carlo) et coût moyen d'une évaluation validée, **test de robustesse** début / fin d'historique, export CSV des trades, **alertes** (son + notification) et **tracé du setup** (entrée, stop, objectifs) sur le graphique.

## Démarrage

**Si tu as téléchargé le ZIP** (`NQ-Scalp-Terminal-V….zip`) : **extrais tout** (clic droit > « Extraire tout… », ou WinRAR > « Extraire ici »), ouvre le dossier extrait `NQ-Scalp-Terminal`, puis suis les étapes ci-dessous. Les lanceurs ne marchent pas si tu les ouvres depuis l'intérieur du ZIP. Ce dossier est **indépendant** du terminal crypto : il a son propre port (8766), son propre journal de compte et ses propres réglages.

1. **Python 3.10 ou plus** (rien d'autre à installer : aucune bibliothèque externe). Windows : coche « Add Python to PATH » à l'installation.
2. **Lancer** : double-clique sur `Lancer-NQ-Windows.bat` (Windows) ou `Lancer-NQ-Mac.command` (Mac, première fois : clic droit > Ouvrir). Ou, dans un terminal : `python run.py`.
3. Le terminal s'ouvre dans ton navigateur sur **http://127.0.0.1:8766/**. La fenêtre noire reste ouverte : c'est le programme. Ferme-la pour arrêter. (Le terminal crypto est sur le port 8765 : les deux peuvent tourner ensemble.)

Sans réglage, il démarre sur des **données simulées** (badge orange « DONNÉES SIMULÉES », avertissement dans la Lecture). Utile pour prendre en main l'écran et vérifier les calculs.

Pour **voir la séance américaine à n'importe quelle heure** : `NQ_SIM_START=2026-10-12T17:30:00Z python run.py` (heure UTC de départ ; le temps avance ensuite normalement).
`python run.py --selftest` vérifie la configuration et la source sans ouvrir le navigateur.

## Ce que montre l'écran

- **Agencement** : en haut, le prix, l'unité de temps, les horloges, et les puces **OI**, **GEX**, **compte Lucid** et **source** (un clic ouvre le bon onglet des Outils). Dessous, la barre des **vues** (onglets de graphiques : clic pour passer de l'une à l'autre, double-clic pour renommer, ✕ pour fermer, **＋ Vue** pour en ajouter une, copie de la vue active), puis **▦ Indicateurs**, **＋ Graphique** et **☰ Outils**. Le graphique prend toute la largeur ; le tiroir Outils s'ouvre à droite quand tu en as besoin.
- **▦ Indicateurs** (pour la vue active ; recherche en haut, défilement) : *Profils de volume* (superposables), *VWAP* (séance et bandes, Globex, semaine, mois), *Niveaux* (aucun / clés / tous, et par famille : veille, nuit, séance, structure, GEX, ronds ; zones de confluence ; single prints), *Order flow* (absorptions : les meilleures / toutes / aucune ; delta chiffré ; gros ordres), *Panneau du bas* (CVD en ligne ou en bougies, remise à zéro Globex ou séance, delta par barre), *Options* (profil GEX par strike, actualiser), *Affichage* (heures Paris / New York, bougies nuit / classiques).
- **Graphique** : bougies 1 / 2 / 3 / 5 / 15 / 30 min et 1 h, volume, **VWAP de séance** (9 h 30 – 16 h ET) avec bandes ±1σ et ±2σ, VWAP Globex (depuis 18 h ET) en pointillé, **VWAP de la semaine** (violet, ancré le dimanche 18 h ET) et **du mois** (bleu ciel), chacun avec sa bande ±1σ (▦ Indicateurs → VWAP). Les journées d'avant la fenêtre affichée entrent dans ces VWAP par leurs profils : le calcul reste exact quelle que soit l'unité de temps. Axe du temps en **heure de Paris** ou de **New York** (bouton). Le VWAP et l'écart-type sont **exacts** : ils sont calculés sur chaque transaction, pas sur un « prix typique » de bougie.
- **Profils de volume collés à l'échelle des prix**, **superposables** (▦ Indicateurs → Profils : séance, journée Globex, veille, **semaine**, **semaine précédente**, **mois**, **mois précédent**) : volume échangé à chaque prix, acheteurs agressifs (vert) et vendeurs agressifs (rouge), **POC** (tick le plus échangé), **zone de valeur 70 %** (VAH / VAL, méthode des bourses), lignes de 1 point (4 ticks). Avant 9 h 30 ET, « Séance » affiche la journée Globex et l'écrit. Semaine et mois sont des **composites** des journées Globex complètes (24 h). Un seul profil coché : acheteurs (vert) et vendeurs (rouge) séparés. Plusieurs : ils se **superposent**, chacun dans sa couleur (zone de valeur plus marquée, POC en tirets, nom à côté) : tu lis la séance dans la semaine et le mois d'un coup d'œil.
- **CVD et delta** dans un panneau synchronisé sous le prix : CVD en **ligne** ou en **bougies** (ouverture, plus haut, plus bas, clôture du CVD de chaque bougie, lus sur les minutes), remise à zéro à 18 h ET « Globex » ou à 9 h 30 ET « séance », **delta par barre** en histogramme. **Delta chiffré sous les bougies** en option (visible quand on zoome assez). La légende en haut à gauche donne aussi le CVD de la bougie survolée.
- **Absorptions, mesurées au prix** (`engine/absorption.py`, footprint de chaque minute) : dans les 3 ticks du plus bas d'une barre, les vendeurs agressifs ont traité ≥ 1,6 fois le plus gros niveau habituel d'une barre et au moins 30 % de leurs ventes de la barre, et la barre a clôturé loin de son plus bas → des acheteurs passifs ont tout pris (absorption **acheteuse**, haussière) ; symétrique au plus haut. S'y ajoute l'**effort sans résultat** (volume ≥ 2 fois l'habituel, gros delta, mais une petite étendue et une clôture contre le delta). Affichage : un marqueur **« ABS »** sous la bougie (absorption acheteuse, flèche verte) ou au-dessus (vendeuse, flèche rouge). Chaque absorption reçoit une **note d'intérêt** : sa force, + si elle est **répétée** au même prix tant que la première tient (« ABS ×2 » : souvent un ordre caché qui se recharge), + si le prix est revenu la **tester** sans la casser, + si elle s'est faite **sur un niveau clé** (POC, VAH / VAL, VWAP et bandes, veille, nuit, IB, POC vierges, single prints, GEX : « ★ »). Par défaut, seules **les meilleures** sont affichées (gros marqueur) ; « Toutes » ajoute les autres en plus discret. Le suivi (tient / cassée / testée) reste dans Outils → Niveaux. Valeurs de départ, à mesurer.
- **Gros ordres** : bulles vertes (achats) et rouges (ventes) à leur prix et à leur bougie, **désactivées par défaut** (▦ Indicateurs → Order flow).
- **GEX (exposition gamma des options)**, pour NQ et MNQ : chaîne d'options **NDX** (ou QQQ, `NQ_GEX=QQQ`) différée de 15 min, téléchargée depuis ton PC sur le site du CBOE toutes les 15 min (dernière copie gardée pour redémarrer sans réseau). Par strike : GEX = gamma × intérêt ouvert × 100 × S² × 1 %, calls comptés +, puts − (convention usuelle). On en tire le **call wall** (plus gros GEX de calls : résistance fréquente), le **put wall** (support fréquent), le **zéro gamma / HVL** (niveau où le gamma total change de signe, recalculé par Black-Scholes avec la volatilité implicite de chaque option), les **strikes majeurs** et le **régime** : gamma positif = marché qui « colle » (range), négatif = marché qui « accélère ». Tout est ramené au prix du NQ (rapport NQ / NDX au moment des données). Lignes de niveaux (famille GEX), barres par strike à gauche du graphique, détail dans Outils → GEX / OI. **Limites** : intérêt ouvert de la veille, données différées, positions réelles des teneurs inconnues (c'est une convention) ; **le format du flux du CBOE n'a pas pu être vérifié depuis mon environnement** : si l'onglet GEX affiche une erreur de données, envoie-moi le message. Pour essayer sans réseau : `python tools/make_sample_options.py options.json 24900` puis `NQ_GEX_FILE=options.json` (chaîne **fictive**).
- **Intérêt ouvert (OI) du NQ** : écrit par l'enregistreur NinjaTrader dans `nq-oi.csv` (à côté des transactions) quand le flux le donne ; puce « OI » en haut (dernière valeur et variation sur la veille), historique dans Outils → GEX / OI. Publié une fois par jour par la bourse : prix ↑ et OI ↑ = positions nouvelles dans le sens du mouvement ; prix ↑ et OI ↓ = rachats de vendeurs.
- **Niveaux** : high / low / clôture / POC / VAH / VAL de la veille, high / low de la nuit, de l'Asie et de Londres, ouverture 9 h 30, **initial balance** (1re heure), VWAP et bandes, POC / VAH / VAL en formation, nombres ronds. Deux niveaux au même prix dans le même groupe (le plus haut de la nuit *est* le plus haut de Londres) comptent pour **un seul**.
- **Structure** (groupe violet, `engine/profiles.py`) : POC / VAH / VAL de la semaine, de la semaine précédente (et ses plus haut / plus bas) et du mois, VWAP semaine et mois, et les **POC vierges** : POC d'une séance régulière passée (« nPOC 13/10 ») ou d'une semaine passée (« nPOC sem. 41 ») que le prix n'a **jamais retouché** depuis. Le marché y revient souvent « finir le travail » : ce sont des cibles et des aimants de scalping. En mode « Clés », les bords des profils composites (VAH / VAL semaine, mois) sont cachés ; « Tous » les montre.
- **Single prints et queues** (case « Single prints », lecture **TPO** de la séance régulière, périodes de 30 min, lignes de 1 point) : prix traités pendant **une seule** demi-heure, au moins 3 points d'affilée. Au milieu du profil, ce sont des **single prints** (bande jaune : le prix y est passé vite, sans échange) ; aux extrémités, des **queues** (bande violette : rejet net, excès). Pour la séance du jour (« en cours »), la demi-heure en cours n'est pas comptée ; pour les 3 séances précédentes, seuls ceux **non comblés** depuis restent, avec la part déjà retraitée (« comblé 31 % », « vierge »). Les bords des single prints vierges entrent dans les niveaux (« SP 14/10 haut / bas »).
- **Graphiques supplémentaires** (« + Graphique ») : jusqu'à 3 petits graphiques sous le principal, chacun avec son unité de temps (ex. 5 min et 15 min pendant que tu scalpes en 1 min) : bougies, VWAP de séance et de la semaine, niveaux clés (POC, VAH / VAL, POC vierges, veille, IB, nuit, single prints) et absorptions qui tiennent. Gardés d'une ouverture à l'autre ; ✕ pour en retirer un.
- **Zones de confluence** : plusieurs niveaux à moins de 6 points, avec un score. **Ce n'est pas un signal** : c'est une carte des endroits où le prix a plusieurs raisons de réagir. Les poids viennent de valeurs de départ, ils n'ont **pas encore été mesurés**.
- **Lecture** (Outils) : l'essentiel en phrases courtes avec un ton par ligne (vert acheteur, rouge vendeur, bleu info, orange attention) : position face au VWAP en écarts-types, face à la zone de valeur de la veille et à l'initial balance, flux agressif sur 5 et 15 min, divergences et absorptions, amplitude de la séance face à la moyenne des dernières séances, prochains repères horaires **en heure de Paris**, annonces, état du compte.
- **Footprint** : volume au bid et à l'ask à chaque prix pour les 2 dernières barres, avec les **déséquilibres diagonaux** (≥ 3 fois : l'acheteur d'un prix contre le vendeur du prix juste en dessous, et inversement), le POC de la barre et les piles de déséquilibres.
- **Compte Lucid** et **Plan** : voir plus bas.

Heures : l'ouverture de New York (9 h 30 ET) est à **15 h 30 à Paris** la plupart de l'année, mais à **14 h 30** pendant 2 à 3 semaines en mars et fin octobre / début novembre (les changements d'heure américain et européen ne tombent pas le même jour). Le terminal calcule tout, jamais « 15 h 30 en dur », et fonctionne **sans base de fuseaux** (Windows n'en a pas) : les règles d'heure d'été sont dans `engine/clock.py` et testées.

## Brancher de vraies données

Lucid fournit les données de marché par **deux fournisseurs** selon la plateforme : CQG (NinjaTrader, Tradovate, TradingView) ou Rithmic (Sierra Chart, Bookmap, ATAS, Quantower, MotiveWave, R|Trader Pro…). Ces flux ne sont pas des API ouvertes : y accéder depuis un programme tiers demande un accès développeur auprès du fournisseur (accord ou abonnement, **à vérifier**). La liste ci-dessus vient du [centre d'aide de Lucid](https://intercom.help/lucid-trading/en/articles/11404614-lucid-trading-supported-platforms) : vérifie-la aussi. Pour une première version, le terminal lit donc **un fichier de transactions** que ta plateforme (ou un export d'historique) écrit. La plateforme que tu utilises déjà paie les données ; le terminal les lit.

```
python run.py --source csv --csv C:\Trading\export\NQ_ticks.csv
```
(ou `NQ_SOURCE=csv` et `NQ_CSV_PATH=…` dans `.env`, voir `config.example.env`).

**Format** (en-tête reconnu, ordre libre, séparateur `,` `;` ou tabulation) :

| Colonne | Noms reconnus | Remarque |
|---|---|---|
| heure | `time`, `timestamp`, `datetime`, `ts`, `ts_event`… | millisecondes, secondes, µs ou ns depuis 1970 ; ISO 8601 (`2026-10-12T13:30:01.250Z`) ; `2026-10-12 09:30:01` (fuseau = `NQ_CSV_TZ`) |
| prix | `price`, `last`, `px` | |
| quantité | `size`, `volume`, `qty` | |
| côté *(facultatif)* | `side`, `aggressor` | `B`/`S`, `buy`/`sell`, `1`/`-1`, `ask` (exécuté à l'ask = acheteur agressif), `bid` |
| carnet *(facultatif)* | `bid`, `ask` | sans colonne côté : prix ≥ ask = acheteur agressif, ≤ bid = vendeur agressif |

- **Le côté de l'agresseur est ce qui rend le delta et le CVD réels.** Sans lui, le terminal l'estime par la règle du tick (hausse = acheteur, baisse = vendeur) et **te le dit** : badge « delta estimé » en haut, avertissement dans la Lecture. Les lettres `A` / `B` (ask / bid) ont un sens différent selon les sources : elles ne sont **jamais devinées** (`NQ_CSV_BUY_CODES` / `NQ_CSV_SELL_CODES` pour les déclarer). Vérifie sur une séance connue que le delta a le bon signe avant de t'y fier.
- Le fichier est lu **par blocs** (un export de ticks fait vite plusieurs Go) puis **suivi** : les lignes ajoutées arrivent à l'écran ; une ligne encore incomplète est attendue. On ne garde que les 6 derniers jours *du fichier*.
- `python tools/make_sample_csv.py ticks.csv` écrit un fichier d'exemple (avec ou sans côté, `--no-side`, `--iso`) pour essayer la chaîne.

### Et si tu trades sur TradingView ?

**TradingView peut passer tes ordres** (Lucid le range avec NinjaTrader et Tradovate parmi les plateformes du flux CQG, via tes identifiants Tradovate), mais **il ne peut pas alimenter le terminal** : pas d'API de données, et ses conditions limitent les données à un usage « affichage seulement » (ni automatisation, ni collecte). Sur TradingView, à tester sur ton compte de simulation avant de t'y fier : ordres bracket (OCO), stop suiveuse (absente avec l'intégration Tradovate selon un article ancien), DOM plus limité, coupures signalées ; **une seule session TradingView à la fois**.

Pour que le terminal ait ses ticks, quatre voies (recherche d'octobre 2026, la plupart des chiffres viennent d'extraits de pages : revérifie avant d'acheter) :

| Voie | Coût | Remarques |
|---|---|---|
| **A. Tu exécutes dans NinjaTrader 8** (même flux CQG) avec un enregistreur de ticks, TradingView pour les graphiques | ≈ 0 $ | La plus simple. **Windows seulement.** Le côté de l'agresseur est *déduit* (prix ≥ ask = acheteur), pas fourni par le CME. NinjaTrader ne reconstitue pas l'historique des bid / ask : l'enregistrement doit tourner dès le premier jour |
| **B. TradingView pour les ordres + Databento** pour le terminal | 199 $/mois + licences CME (≈ 210 à 240 $ au total, à confirmer) | La plus propre : vrai côté de l'agresseur du CME, indépendant de Lucid et de TradingView. Dans Databento, `side` = « Ask » désigne le vendeur agressif et « Bid » l'acheteur agressif (sens inverse du réflexe) : déclare-le avec `NQ_CSV_SELL_CODES=a` |
| **C. TradingView + NinjaTrader en parallèle** pour les données | ≈ 0 $ | **Non confirmé** : Tradovate limite les sessions simultanées (1 à 2 selon les sources). À tester sur la simulation, et à demander à Lucid |
| **D. Pine Script `request.footprint()` + alertes** | Premium (≈ 70 $/mois) | Par barre seulement (pas de CVD au tick), serveur public sur le port 80 / 443, 3 secondes pour répondre, au plus 15 déclenchements par 3 minutes, et **conditions de TradingView probablement violées** : à éviter |

Écartés : l'API Tradovate (compte réel financé et frais CME, selon une source) et les API de CQG (non fournies aux comptes Lucid). Lucid autorise les systèmes automatiques (le trader reste responsable), mais ne dit rien d'un simple enregistreur de données : demande-lui une confirmation écrite.

**Et une « clé Lucid » ?** Lucid ne fournit pas de clé d'API de données de marché : ses comptes donnent accès aux plateformes (NinjaTrader, Tradovate…), qui reçoivent elles-mêmes le flux CME sous licence. Le terminal n'a donc pas de champ « clé Lucid » et n'en aura pas ; les vraies données CME arrivent par l'enregistreur NinjaTrader ci-dessous, ou par un fournisseur de données qui te vend un accès en ton nom (voie B).

**Voie retenue : A (NinjaTrader 8 + flux CQG de Lucid).** L'enregistreur est fourni : `ninjatrader/NQTickLogger.cs`.

### Brancher NinjaTrader (Windows)

`NQTickLogger` est un indicateur NinjaScript **en lecture seule** : il n'envoie aucun ordre, ne se connecte à rien d'autre que ce que NinjaTrader reçoit déjà. À chaque transaction, il écrit une ligne `time,price,size,side,bid,ask` (heure en millisecondes UTC, côté `B`/`S` déduit du bid / ask du moment, vide si le prix tombe entre les deux).

1. **Copier** `ninjatrader\NQTickLogger.cs` dans `Documents\NinjaTrader 8\bin\Custom\Indicators\` : double-clic sur **`Installer-NinjaTrader.bat`** (dans le dossier du terminal) le fait pour toi.
2. Dans NinjaTrader : **New → NinjaScript Editor**, ouvrir *Indicators → NQTickLogger*, puis **Compile** (F5). Aucune erreur ne doit apparaître en bas.
3. Ouvrir un **graphique du contrat NQ en cours** (ex. `NQ 12-26`), connecté à ton compte Lucid. Clic droit → **Indicators…** → ajouter **NQTickLogger**. Par défaut il écrit dans `Documents\NQ-Terminal\nq-ticks.csv` (réglable : « Chemin du fichier »). La fenêtre *Output* de NinjaTrader affiche « NQTickLogger : écriture dans … ».
4. Lancer `Lancer-NQ-Windows.bat`. **Rien à régler** : si le fichier `Documents\NQ-Terminal\nq-ticks.csv` existe (OneDrive compris), le terminal le prend tout seul. Le badge passe de « DONNÉES SIMULÉES » à « Fichier · NinjaTrader » ; s'il indique « delta estimé », le côté n'arrive pas (vérifie que le graphique reçoit bien le bid / ask). Fichier ailleurs : **Outils → Source** → « Tester et utiliser » (le choix est gardé dans `.env`), ou à la main dans `.env` : `NQ_SOURCE=csv` et `NQ_CSV_PATH=…`. Un `NQ_SOURCE` écrit dans `.env` l'emporte toujours sur la détection.
5. **Test d'une journée** avant de t'y fier : laisse tourner une séance complète, puis compare le volume total et le delta d'une barre de 5 min avec ceux de NinjaTrader (Order Flow + si tu l'as). Un écart de quelques contrats est normal (transactions entre le bid et l'ask), un delta de signe opposé ne l'est pas.

Bon à savoir : l'enregistreur écrit **le temps réel seulement** (option « Inclure l'historique » pour rejouer ce que NinjaTrader a en mémoire) ; il **ajoute** au fichier à chaque démarrage. Le terminal garde les 6 derniers jours du fichier : plus tu enregistres tôt, plus le backtest a de journées. Pour repartir de zéro, ferme NinjaTrader et renomme le fichier. Lucid ne dit rien d'un simple enregistreur de données : demande-lui une confirmation écrite.

## Compte Lucid 25K

Onglet **Compte** : solde, plancher, marge, objectif, consistance, jour en cours, journal des trades, statistiques par *setup*.

Règles retenues par défaut (**LucidFlex 25K, évaluation**), recoupées sur plusieurs sources publiques de 2026 — **confirme-les sur le site de Lucid avant de t'y fier** : [QuantVPS](https://www.quantvps.com/blog/lucid-trading-prop-firm-payout-rules), [Pipback](https://pipback.com/blog/lucid-trading-review), [Prop Trading Vibes](https://proptradingvibes.com/blog/lucid-trading-25k-account-rules), [DamnPropFirms](https://damnpropfirms.com/prop-firms/lucid-trading-rules-payouts/), [centre d'aide Lucid (compte financé)](https://support.lucidtrading.com/en/articles/12945795-lucidflex-funded-account).

| Règle | Valeur | Confiance |
|---|---|---|
| Capital / cible de profit | 25 000 $ / 1 250 $ | sources concordantes |
| Perte maximale | 1 000 $, **trailing sur le solde de fin de journée** : plancher = meilleur solde EOD − 1 000 $, il ne baisse jamais | concordantes |
| Verrou du plancher | s'arrête à capital + 100 $ (25 100 $) | une source précise, les autres confirment « verrouillé » |
| Limite de perte journalière | **optionnelle** : choisie au paiement (moins chère si activée), non modifiable ensuite, « souple » (blocage jusqu'à la séance suivante). Montant à lire sur la page d'achat (600 $ cité pour Pro et Daily ; non confirmé pour Flex 25K). Ce profil la laisse désactivée | centre d'aide Lucid, recoupé |
| Contrats | 2 minis ou 20 micros (un mini = 10 micros, **l'ensemble compte** : hypothèse prudente) | concordantes sur 2 / 20 |
| Consistance (évaluation) | meilleur jour ≤ 50 % du profit total | majorité ; une source isolée dit 20 % (jugée erronée) |
| Jours de trading minimum | aucun minimum officiel trouvé ; **2 jours en pratique** (la consistance de 50 % rend un passage en 1 jour impossible avec une cible de 1 250 $) | moyenne |
| Fermeture forcée | positions **à plat avant 16 h 45 ET** (22 h 45 à Paris), fermées d'office ; pas de position la nuit ni le week-end | centre d'aide Lucid, recoupé |
| Micro-scalping | compte signalé si **plus de 50 % des gains** viennent de trades tenus **5 secondes ou moins** (revue manuelle, avertissement, puis perte de ces gains) | centre d'aide Lucid, recoupé |
| Frais | commissions Lucid : **NQ 3,50 $ et MNQ 1,00 $ l'aller-retour** (1,75 $ et 0,50 $ par côté). Frais de bourse éventuels non inclus ; ES / MES : même valeur par défaut, non vérifiée | table du centre d'aide, à confirmer à l'achat |

Tout est modifiable dans **Compte → « Règles Lucid et limites personnelles »** (un champ vide = pas de règle ; les valeurs inutilisables — nombre non fini, plafond nul, palier vide — sont refusées ; si un ancien fichier en contient une, elle est écartée et signalée, les autres réglages sont gardés et l'original est copié à côté dans `data_local`). Les valeurs **« risque par trade » (100 $) et « stop quotidien » (300 $)** ne sont **pas** des règles de Lucid : ce sont des valeurs de départ pour *ta* discipline, à régler ensemble.

**Ce que calcule le moteur** (`engine/risk.py`, testé sur les cas limites) :
- le **plancher** (il ne se met à jour qu'en fin de journée de trading) et la **marge** avant lui, mesurée sur l'**equity** (solde + latent), prudemment : la limite est considérée touchée dès que l'equity l'atteint ;
- la **consistance** : meilleur jour / profit total, le **profit total à atteindre pour valider** (plus que la cible si le meilleur jour est gros : un meilleur jour de 700 $ à 50 % exige 1 400 $, pas 1 250 $), et le **gain maximal d'aujourd'hui** qui ne casse pas la règle ;
- le **micro-scalping** : part de tes gains issue de trades tenus 5 s ou moins (saisis la durée de chaque trade), avec un avertissement dès 35 % ; la **fermeture forcée** de 16 h 45 ET est annoncée 30 minutes avant ;
- le **dimensionnement** : pour un stop et un risque donnés, combien de NQ **et** de MNQ (frais inclus), plafonnés par le compte, le rapport gain / risque de chaque objectif, et des avertissements (stop trop large, plafond atteint, > 25 % de la marge restante, stop quotidien, frais qui mangent l'objectif).

**Compte financé et retraits** (règles de l'article [LucidFlex Payouts](https://support.lucidtrading.com/en/articles/12945796-lucidflex-payouts), reconstituées à partir d'extraits : le site n'était pas lisible depuis mon environnement) :
- **Évaluation puis compte financé** : quand Lucid valide ton évaluation, bouton **« Évaluation validée → passer en compte financé »** (Compte → Étape). C'est un **nouveau compte** : solde et plancher repartent du départ (25 000 $ / 24 000 $, à confirmer), la consistance disparaît, le palier de taille et les retraits s'appliquent. Annulable avec « Annuler la dernière saisie ».
- **Palier de taille** : 1 mini / 10 micros tant que le profit du compte est sous 1 000 $, puis 2 / 20 ; mesuré en fin de séance (un retrait saisi aujourd'hui ne change la taille autorisée que demain), il peut redescendre après un retrait. Le calculateur le respecte.
- **Retrait** : 5 jours à ≥ 100 $ dans le cycle, profit du cycle positif, minimum 500 $, au plus 50 % du profit et 1 000 $ (le plafond ne monte pas avec les retraits suivants), 90 / 10, 5 retraits au plus puis passage en Live au choix de Lucid. Le premier retrait demande donc **au moins 1 000 $ de profit** : 5 jours à 100 $ ne suffisent pas.
- **À la demande, le plancher saute à 25 100 $ et le solde baisse du montant retiré** : ta marge après retrait = solde − 25 100 $ (profit de 1 000 $, retrait de 500 $ → solde 25 500 $, marge **400 $**). La carte **Retraits** montre les jours qualifiants, l'éligibilité, le montant maximal, et la marge qu'il te resterait. Saisis le retrait dans la carte quand tu l'as demandé : le cycle repart de zéro.
- **Ce que le journal refuse, et ce dont il te prévient** : il reflète ce qui s'est passé chez Lucid, qui contrôle lui-même. Il refuse seulement l'**impossible** : un montant hors minimum / plafond d'une demande (500 $ à 1 000 $), un 6ᵉ retrait (compté sur tout le journal, même antidaté), un retrait daté d'avant le compte financé, un montant qui ferait passer le solde au plancher ou dessous (donc pas de retrait sur un compte neuf). Quand ce que ton journal montre ne remplit pas les conditions de la règle (il manque des jours gagnants, au-dessus de la moitié du profit), le retrait est **enregistré avec un avertissement** : vérifie tes saisies si Lucid n'est pas du même avis. La marge « après retrait » est calculée sur le solde et l'equity **du moment** (une journée déjà négative réduit le retrait possible).
- **Cycle de retrait** : un retrait saisi **après les trades de sa journée** (après 16 h 45 ET ou après le dernier trade du jour) clôt cette journée ; saisi **avant** (ex. à l'ouverture), le même jour ouvre le nouveau cycle. Les saisies datées d'avant le passage en compte financé, rattrapées après coup, restent dans le journal mais n'entrent pas dans le compte financé. Le passage en compte financé ne se supprime pas au milieu du journal.
- **Hypothèses non tranchées par l'article** (retenues prudemment, modifiables dans le code) : un jour compte *net de frais* et *par séance* ; le « 50 % » porte sur le *profit du compte*.
- **Limite de perte journalière** : option choisie à l'achat (moins chère si activée), non modifiable ensuite, **souple** : elle verrouille la séance (« atteinte ») mais ne fait pas échouer le compte. Seul le plancher le fait. Son montant pour Flex 25K n'est pas confirmé (600 $ cité pour Pro et Daily) : lis-le sur la page d'achat et saisis-le dans les règles (un champ vide ou 0 = pas de limite). Une fois touchée, la limite **reste** active toute la séance, même si le latent remonte ensuite (tant que le terminal reste ouvert : le latent d'avant un redémarrage n'est pas conservé), et le calculateur avertit « plus aucun trade ». Enregistrer d'autres règles ne la rouvre pas ; changer la limite, si.

**Le terminal ne se connecte pas à ta plateforme** : le solde vient du **journal** que tu tiens (Compte → « Trade clôturé » : un trade, ou « Clôturer au dernier prix → » depuis la position suivie ; « Reprendre un compte entamé » pour un compte déjà commencé). Le **latent** vient de la **position ouverte** que tu saisis (ou que tu prends depuis le Plan). Il ne comprend pas les frais. Le journal est dans `data_local/compte.json` (écriture atomique ; un fichier illisible est mis de côté, jamais écrasé).

## Plan (calculateur)

Sens, entrée, stop et objectifs **en prix ou en points** (l'autre se remplit), risque en dollars : taille NQ et MNQ, risque frais compris, R par objectif, avertissements. Un clic sur un niveau (onglet Niveaux) copie son prix dans le champ choisi. **Il ne passe aucun ordre.**

## Setups (onglet Setups)

À la clôture de chaque barre, le moteur (`engine/signals.py`) lit des **ingrédients** du flux et du profil, chacun avec un sens et une force entre 0 et 1 :

| Ingrédient | Ce qui est mesuré |
|---|---|
| Divergence CVD | le prix fait un nouvel extrême sur la fenêtre, le CVD non |
| Absorption | gros delta *contre* le sens de la barre, volume au-dessus de la normale |
| Piles de déséquilibres | ≥ 3 déséquilibres diagonaux consécutifs dans le footprint de la barre |
| Bord de zone de valeur | prix à quelques points de la VAH / VAL : rejet possible vers le POC |
| Étirement VWAP | prix au-delà de ±1,6 σ du VWAP de séance (retour vers la moyenne) |
| Zone de confluence | plusieurs niveaux superposés sous / au-dessus du prix |
| Cassure de l'IB | clôture au-delà du high / low de la première heure avec un delta dans le même sens |
| Pente du CVD | le flux agressif récent pousse dans un sens |

Le **score** (0 – 100) est une somme pondérée **transparente** (chaque raison est listée sous le setup), modulée par la phase de séance (× 0,6 au creux de midi et la nuit). Le **stop** se place derrière le dernier extrême + une marge d'ATR (entre 8 et 60 ticks), les **objectifs** sur les niveaux suivants. Un setup n'est **jamais un ordre** : le bouton « Calculer la taille » le copie dans le Plan.

**Règles Lucid intégrées** : aucun setup si le compte est au plancher ou si la limite journalière est atteinte ; plus de nouveau scalp dans les **12 dernières minutes avant 16 h 45 ET** ; en évaluation, rappel du **gain maximal du jour** qui garde la consistance ; avertissement **micro-scalping** si l'objectif est si proche qu'il serait tenu en quelques secondes ; palier de taille en compte financé.

**Alertes** (en haut de l'onglet) : « Tracer le meilleur setup sur le graphique » dessine entrée, stop et objectifs ; « Son + notification » prévient quand un setup atteint le score choisi, **même onglet fermé** (le navigateur demande l'autorisation des notifications la première fois). Une alerte par setup nouveau, au plus une par minute et par sens, jamais pendant un blocage. Si la page du navigateur est en arrière-plan, Chrome peut espacer les vérifications : garde le terminal dans sa propre fenêtre.

## Backtest (onglet Backtest)

On rejoue les setups **barre par barre sans jamais regarder le futur** : à la clôture de la barre *i*, profil, niveaux et setups sont calculés à partir des seules barres ≤ *i* ; l'entrée se fait à l'**ouverture de la barre suivante**, avec glissement. Exécution **prudente** :
- la **barre d'entrée est vérifiée** (un stop touché dans la minute même de l'entrée compte) ; si stop et objectif sont touchés dans la même barre, on suppose **le stop d'abord** ;
- un **objectif** (ordre limite) n'est rempli que si le prix le **dépasse d'un tick** (ta place dans la file d'attente) ; un **stop sauté** par un écart est exécuté à l'ouverture, plus mal que le stop ;
- si l'ouverture a déjà franchi le stop ou l'objectif, le setup est abandonné ; pas d'entrée à travers un trou de données ;
- frais réels de Lucid, sortie forcée à 16 h 45 ET, stop de temps, taille calculée pour le risque choisi et plafonnée par le compte.

Puis le résultat passe **dans les règles Lucid, jour après jour** : plancher suiveur (touché aussi **en cours de journée** si le creux réalisé l'atteint), cible, consistance 50 %, date de validation, part de micro-scalping (un **majorant** : un trade sorti dans sa barre d'entrée est compté comme micro).

- **Probabilité de valider l'évaluation (Monte Carlo)** : un backtest n'est qu'*un* ordre possible des journées. On tire au hasard, avec remise, les journées du backtest (journées sans trade comprises) et on rejoue 2 000 évaluations avec les règles du profil. Résultat : % validées, % au plancher, % ni l'un ni l'autre dans l'horizon, jours nécessaires, part des validations retardées par la consistance. Renseigne le **prix de l'évaluation** : le terminal affiche le **coût moyen d'une évaluation validée** (prix ÷ probabilité). Moins de 15 journées : chiffre signalé comme fragile.
- **Robustesse** : la même stratégie sur une grille score minimal (30 – 70) × glissement (1 – 2 ticks), séparée en **début** (≈ 2/3 des jours) et **fin** d'historique. On choisit le meilleur réglage sur le début seulement et on regarde ce qu'il donne sur la fin, qu'il n'a pas vue. S'il s'effondre, c'était de la sur-optimisation.
- **Exporter CSV** : la liste des trades (heures en UTC) pour ton tableur.

Les calculs lourds (profil, niveaux, setups de chaque barre) sont faits une fois puis gardés tant que l'historique ne change pas : relancer avec d'autres réglages est instantané.

## Annonces

Pas encore de calendrier automatique. Tu peux en tenir un dans `data_local/events.json` (modèle : `events.example.json`) : la Lecture les affiche en heure de Paris et signale une **fenêtre à éviter** de 2 min avant à 3 min après une annonce de niveau 3.

## Méthode

Hérite du terminal crypto : **on mesure avant de croire**. Rien ici n'est présenté comme prédictif :
- les zones, les poids et les seuils (3 fois pour un déséquilibre, 2 σ pour une absorption, 6 points pour une zone…) sont des **valeurs de départ** ;
- chaque setup se **rejoue sur l'historique** avec frais et glissement (le scalping meurt de frais et de slippage), et se juge sur des jours **qu'il n'a pas vus** (Robustesse) ; la comparaison à des entrées au hasard reste à faire ;
- les données simulées ne servent qu'à tester les calculs, jamais à juger une idée.

## Architecture

```
nq/
  run.py  server.py  service.py  config.py         lanceur · API locale (jeton, hôte vérifié) · assemblage · réglages
  engine/                                           moteurs PURS (sans réseau ni disque), testés
    clock.py        ET / Paris sans tzdata · sessions CME · journée de trading · repères horaires
    instruments.py  NQ / MNQ / ES / MES (tick, valeur du point) · contrat trimestriel et roll estimé
    bars.py         transactions · cote de l'agresseur (règle du tick) · barres avec footprint · regroupement
    footprint.py    volume bid / ask à chaque prix · déséquilibres diagonaux · Ladder (VWAP exact)
    vp.py           profil de volume au tick : POC, zone de valeur, HVN / LVN
    vwap.py  cvd.py VWAP et bandes · CVD, divergences, absorptions
    market.py       état du marché : barres, profils par journée, ruban, gros ordres
    levels.py  context.py  events.py     niveaux et zones · lecture de séance · annonces
    risk.py  account.py  règles Lucid et dimensionnement · journal du compte
    absorption.py   absorptions au prix (footprint) : détection, suivi (tient / cassée / testée / répétée), note d'intérêt
    gex.py          GEX d'une chaîne d'options : par strike, call / put walls, zéro gamma (Black-Scholes), conversion vers le NQ
    profiles.py     profils composites semaine / mois, POC vierges, single prints et queues (TPO)
    signals.py      setups de scalping : ingrédients du flux, score, stop / objectifs, règles Lucid
    backtest.py     rejeu sans regard vers le futur (Tape pré-calculée) · exécution prudente · règles jour après jour · robustesse
    montecarlo.py   probabilité de valider l'évaluation (bootstrap des journées)
  ninjatrader/      NQTickLogger.cs : enregistreur de transactions NinjaTrader 8 -> CSV lu par le terminal
  data/             simulated.py (essai) · filefeed.py (CSV, par blocs, suivi) · options.py (options CBOE, intérêt ouvert) · base.py
  web/              interface (lightweight-charts v4.2.3 ; canvas pour les profils, le GEX, les single prints, le delta chiffré ; minis.js : graphiques supplémentaires)
  tools/            make_sample_csv.py · make_sample_options.py (chaîne d'options fictive)
  tests/            tests unitaires de tous les moteurs, de l'API et de la source fichier
```

Tests : `python -m unittest discover -s tests -t .` (depuis le dossier `nq`).

## Limites connues (V0.6)

- Données **simulées** par défaut ; pas de connexion directe à un courtier ni à un flux de données.
- Barres de 1 minute au plus fin : pas encore de graphiques à la seconde, au tick ni au volume (il faut d'abord une vraie source de ticks).
- Jours fériés de bourse non gérés (le terminal ne sait pas qu'un jour est férié) ; la **date de roll** du contrat est une estimation (8 jours avant l'échéance) : au moment du roll, regarde le volume réel de ta plateforme.
- Compte : saisie manuelle ; règles de Lucid à confirmer (voir plus haut) ; le compte financé repart-il vraiment de 25 000 $ avec un plancher à 24 000 $ ? À confirmer. La phase **Live** (après 5 retraits) n'est pas modélisée.
- Backtest sur barres de 1 minute : l'ordre des prix *dans* une minute est inconnu (d'où les hypothèses prudentes) ; pas de file d'attente réelle. Le côté de l'agresseur venant de NinjaTrader est déduit du bid / ask, pas fourni par le CME.
- Le **GEX** (gamma exposure, niveaux HVL…) est reporté : il demande une source d'options payante.
- Le backtest rejoue les niveaux de la journée et de la veille, mais **pas encore** la structure semaine / mois, les POC vierges ni les single prints (en direct, les setups les voient).
- Le terminal ne garde que `NQ_HISTORY_DAYS` journées (10 par défaut) : le profil du mois et les POC vierges anciens demandent `NQ_HISTORY_DAYS=25` et un fichier de transactions qui remonte aussi loin (démarrage plus lent : le fichier est relu en entier).
- Pas d'alertes Telegram, pas de discussion avec Claude, pas de mise à jour automatique : étapes suivantes.

> Estimations et statistiques à titre informatif, ce n'est pas un conseil financier. Le trading de futures comporte un risque élevé de perte.
