# NQ Scalp Terminal (V0.1 — la base)

Un terminal **local** (il tourne uniquement sur ton PC) pour scalper le **Nasdaq-100 en futures (NQ / MNQ)** avec un compte prop firm **Lucid 25K**. Même esprit que le terminal crypto (VP, CVD, VWAP, niveaux, lecture honnête), refait pour le scalping : horloge de New York, séances du CME, order flow à la transaction près, et un moteur de risque qui connaît les règles du compte.

> **État actuel : une base solide, pas encore une stratégie.** Le terminal te donne la carte (niveaux, flux, profil, VWAP, risque du compte). Les *setups* et leur mesure viennent ensuite, ensemble (voir « Feuille de route »). Les données par défaut sont **simulées** : rien à l'écran ne dit quoi que ce soit du vrai marché tant que tu n'as pas branché de vraies transactions.

## Démarrage

**Si tu as téléchargé le ZIP** (`NQ-Scalp-Terminal-V….zip`) : **extrais tout** (clic droit > « Extraire tout… », ou WinRAR > « Extraire ici »), ouvre le dossier extrait `NQ-Scalp-Terminal`, puis suis les étapes ci-dessous. Les lanceurs ne marchent pas si tu les ouvres depuis l'intérieur du ZIP. Ce dossier est **indépendant** du terminal crypto : il a son propre port (8766), son propre journal de compte et ses propres réglages.

1. **Python 3.10 ou plus** (rien d'autre à installer : aucune bibliothèque externe). Windows : coche « Add Python to PATH » à l'installation.
2. **Lancer** : double-clique sur `Lancer-NQ-Windows.bat` (Windows) ou `Lancer-NQ-Mac.command` (Mac, première fois : clic droit > Ouvrir). Ou, dans un terminal : `python run.py`.
3. Le terminal s'ouvre dans ton navigateur sur **http://127.0.0.1:8766/**. La fenêtre noire reste ouverte : c'est le programme. Ferme-la pour arrêter. (Le terminal crypto est sur le port 8765 : les deux peuvent tourner ensemble.)

Sans réglage, il démarre sur des **données simulées** (badge orange « DONNÉES SIMULÉES », avertissement dans la Lecture). Utile pour prendre en main l'écran et vérifier les calculs.

Pour **voir la séance américaine à n'importe quelle heure** : `NQ_SIM_START=2026-10-12T17:30:00Z python run.py` (heure UTC de départ ; le temps avance ensuite normalement).
`python run.py --selftest` vérifie la configuration et la source sans ouvrir le navigateur.

## Ce que montre l'écran

- **Graphique** : bougies 1 / 2 / 3 / 5 / 15 / 30 min et 1 h, volume, **VWAP de séance** (9 h 30 – 16 h ET) avec bandes ±1σ et ±2σ, VWAP Globex (depuis 18 h ET) en pointillé. Axe du temps en **heure de Paris** ou de **New York** (bouton). Le VWAP et l'écart-type sont **exacts** : ils sont calculés sur chaque transaction, pas sur un « prix typique » de bougie.
- **Profil de volume collé à l'échelle des prix** (séance, journée Globex ou veille) : volume échangé à chaque prix, acheteurs agressifs (vert) et vendeurs agressifs (rouge), **POC** (tick le plus échangé), **zone de valeur 70 %** (VAH / VAL, méthode des bourses), lignes de 1 point (4 ticks). Avant 9 h 30 ET, « Séance » affiche la journée Globex et l'écrit.
- **CVD et delta** dans un panneau synchronisé sous le prix (remise à zéro à 18 h ET « Globex » ou à 9 h 30 ET « séance »).
- **Absorptions** (flèches ABS) : delta très fort *contre* le sens de la barre, avec un volume au-dessus de la normale. **Gros ordres** : bulles vertes (achats) et rouges (ventes) à leur prix.
- **Niveaux** : high / low / clôture / POC / VAH / VAL de la veille, high / low de la nuit, de l'Asie et de Londres, ouverture 9 h 30, **initial balance** (1re heure), VWAP et bandes, POC / VAH / VAL en formation, nombres ronds. Deux niveaux au même prix dans le même groupe (le plus haut de la nuit *est* le plus haut de Londres) comptent pour **un seul**.
- **Zones de confluence** : plusieurs niveaux à moins de 6 points, avec un score. **Ce n'est pas un signal** : c'est une carte des endroits où le prix a plusieurs raisons de réagir. Les poids viennent de valeurs de départ, ils n'ont **pas encore été mesurés**.
- **Lecture** (panneau de droite) : l'essentiel en phrases courtes avec un ton par ligne (vert acheteur, rouge vendeur, bleu info, orange attention) : position face au VWAP en écarts-types, face à la zone de valeur de la veille et à l'initial balance, flux agressif sur 5 et 15 min, divergences et absorptions, amplitude de la séance face à la moyenne des dernières séances, prochains repères horaires **en heure de Paris**, annonces, état du compte.
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

**À décider ensemble** : quelle plateforme alimente ce fichier, et comment (export natif, petit script / indicateur à écrire pour NinjaTrader, Sierra Chart, ATAS…), ou un fournisseur de données par API (payant). Voir la feuille de route.

## Compte Lucid 25K

Onglet **Compte** : solde, plancher, marge, objectif, consistance, jour en cours, journal des trades, statistiques par *setup*.

Règles retenues par défaut (**LucidFlex 25K, évaluation**), recoupées sur plusieurs sources publiques de 2026 — **confirme-les sur le site de Lucid avant de t'y fier** : [QuantVPS](https://www.quantvps.com/blog/lucid-trading-prop-firm-payout-rules), [Pipback](https://pipback.com/blog/lucid-trading-review), [Prop Trading Vibes](https://proptradingvibes.com/blog/lucid-trading-25k-account-rules), [DamnPropFirms](https://damnpropfirms.com/prop-firms/lucid-trading-rules-payouts/), [centre d'aide Lucid (compte financé)](https://support.lucidtrading.com/en/articles/12945795-lucidflex-funded-account).

| Règle | Valeur | Confiance |
|---|---|---|
| Capital / cible de profit | 25 000 $ / 1 250 $ | sources concordantes |
| Perte maximale | 1 000 $, **trailing sur le solde de fin de journée** : plancher = meilleur solde EOD − 1 000 $, il ne baisse jamais | concordantes |
| Verrou du plancher | s'arrête à capital + 100 $ (25 100 $) | une source précise, les autres confirment « verrouillé » |
| Limite de perte journalière imposée par Lucid | aucune | concordantes |
| Contrats | 2 minis ou 20 micros (un mini = 10 micros, **l'ensemble compte** : hypothèse prudente) | concordantes sur 2 / 20 |
| Consistance (évaluation) | meilleur jour ≤ 50 % du profit total | majorité ; une source isolée dit 20 % (jugée erronée) |
| Jours de trading minimum | **sources contradictoires (0 ou 2)** | **à vérifier** |
| Frais aller-retour | **estimations** (NQ 4,50 $, MNQ 1,50 $) | **à remplacer par tes frais réels** |

Tout est modifiable dans **Compte → « Règles Lucid et limites personnelles »** (un champ vide = pas de règle). Les valeurs **« risque par trade » (100 $) et « stop quotidien » (300 $)** ne sont **pas** des règles de Lucid : ce sont des valeurs de départ pour *ta* discipline, à régler ensemble.

**Ce que calcule le moteur** (`engine/risk.py`, testé sur les cas limites) :
- le **plancher** (il ne se met à jour qu'en fin de journée de trading) et la **marge** avant lui, mesurée sur l'**equity** (solde + latent), prudemment : la limite est considérée touchée dès que l'equity l'atteint ;
- la **consistance** : meilleur jour / profit total, le **profit total à atteindre pour valider** (plus que la cible si le meilleur jour est gros : un meilleur jour de 700 $ à 50 % exige 1 400 $, pas 1 250 $), et le **gain maximal d'aujourd'hui** qui ne casse pas la règle ;
- le **dimensionnement** : pour un stop et un risque donnés, combien de NQ **et** de MNQ (frais inclus), plafonnés par le compte, le rapport gain / risque de chaque objectif, et des avertissements (stop trop large, plafond atteint, > 25 % de la marge restante, stop quotidien, frais qui mangent l'objectif).

**Le terminal ne se connecte pas à ta plateforme** : le solde vient du **journal** que tu tiens (Compte → « Trade clôturé » : un trade, ou « Clôturer au dernier prix → » depuis la position suivie ; « Reprendre un compte entamé » pour un compte déjà commencé). Le **latent** vient de la **position ouverte** que tu saisis (ou que tu prends depuis le Plan). Il ne comprend pas les frais. Le journal est dans `data_local/compte.json` (écriture atomique ; un fichier illisible est mis de côté, jamais écrasé).

## Plan (calculateur)

Sens, entrée, stop et objectifs **en prix ou en points** (l'autre se remplit), risque en dollars : taille NQ et MNQ, risque frais compris, R par objectif, avertissements. Un clic sur un niveau (onglet Niveaux) copie son prix dans le champ choisi. **Il ne passe aucun ordre.**

## Annonces

Pas encore de calendrier automatique. Tu peux en tenir un dans `data_local/events.json` (modèle : `events.example.json`) : la Lecture les affiche en heure de Paris et signale une **fenêtre à éviter** de 2 min avant à 3 min après une annonce de niveau 3.

## Méthode

Hérite du terminal crypto : **on mesure avant de croire**. Rien ici n'est présenté comme prédictif :
- les zones, les poids et les seuils (3 fois pour un déséquilibre, 2 σ pour une absorption, 6 points pour une zone…) sont des **valeurs de départ** ;
- avant qu'un setup soit proposé, il sera **rejoué sur l'historique** et comparé à des entrées au hasard, avec les frais (le scalping meurt de frais et de slippage) ;
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
  data/             simulated.py (essai) · filefeed.py (CSV, par blocs, suivi) · base.py
  web/              interface (lightweight-charts v4.2.3, canvas pour le profil et les bulles)
  tools/            make_sample_csv.py
  tests/            tests unitaires de tous les moteurs, de l'API et de la source fichier
```

Tests : `python -m unittest discover -s tests -t .` (depuis le dossier `nq`).

## Limites connues (V0.1)

- Données **simulées** par défaut ; pas de connexion directe à un courtier ni à un flux de données.
- Barres de 1 minute au plus fin : pas encore de graphiques à la seconde, au tick ni au volume (il faut d'abord une vraie source de ticks).
- Jours fériés de bourse non gérés (le terminal ne sait pas qu'un jour est férié) ; la **date de roll** du contrat est une estimation (8 jours avant l'échéance) : au moment du roll, regarde le volume réel de ta plateforme.
- Compte : saisie manuelle ; règles de Lucid à confirmer (voir plus haut) ; règles du **compte financé** non incluses.
- Pas d'alertes (Telegram), pas de discussion avec Claude, pas de mise à jour automatique : ce sont des étapes suivantes.

> Estimations et statistiques à titre informatif, ce n'est pas un conseil financier. Le trading de futures comporte un risque élevé de perte.
