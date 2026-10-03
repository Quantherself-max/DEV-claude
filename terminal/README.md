# Liq Terminal (V1)

Un terminal **local** (sur ton PC uniquement) qui relie sur une seule page :

- les **niveaux** de ta stratégie : VWAP jour/semaine/mois/année, VWAP ancrée, opens, plus hauts/bas précédents, profils de volume (POC, VAH/VAL, HVN) ;
- les **poches de liquidation estimées** (proxy à partir de l'Open Interest Binance) ;
- les **confluences** : zones où plusieurs niveaux de sources différentes se regroupent ;
- un **clic** sur un niveau, une zone ou une poche affiche son détail (composition, distance, explication) ;
- des **alertes Telegram** quand une confluence se forme ou que le prix s'en approche.

> Estimations à titre informatif, pas un conseil financier. Les poches de liquidité sont un **proxy** (pas de vraies
> liquidations). La règle « aimant » (une zone attire le prix) est une **hypothèse non validée**.

## 1. Installer (une seule fois)

1. Installe **Python 3.10 ou plus** (https://www.python.org/downloads/ ; sous Windows, coche « Add Python to PATH »).
2. Récupère le dossier `terminal` (sur GitHub : branche `claude/festive-gates-viq9oo` → Code → Download ZIP, puis ouvre le dossier `terminal`).
3. Aucune autre installation : le terminal n'utilise que la bibliothèque standard de Python.

## 2. Essayer tout de suite (données simulées)

```
python run.py
```

(Windows : `py run.py`.) Le navigateur s'ouvre sur http://127.0.0.1:8765/ . Le badge **DONNÉES SIMULÉES** rappelle que les prix
sont fictifs : c'est juste pour voir comment ça marche.

## 3. Passer aux données réelles

1. Copie `config.example.env` en `.env` (même dossier) et mets `TERMINAL_SOURCE=binance`.
2. Vérifie ton accès : `python run.py --selftest` (teste Binance : bougies, volume acheteur, Open Interest). Si un test affiche `KO`,
   envoie-moi le message affiché.
3. Relance `python run.py`. Au premier lancement, le chargement de l'historique prend environ une minute.

Données utilisées (Binance futures USDT-M, endpoints publics, sans clé) : bougies 1h depuis le 1er janvier de l'an dernier (profils annuels,
VWAP ancrée), bougies 5 min et Open Interest 5 min sur ~29 jours (limite imposée par Binance).

## 4. Alertes Telegram

1. Dans Telegram, parle à **@BotFather** → `/newbot` → il te donne un **token**. Mets-le dans `.env` : `TELEGRAM_BOT_TOKEN=...`
2. Écris un message quelconque à ton nouveau bot, puis lance `python run.py --telegram-chatid` : il affiche ton **chat id**.
   Mets-le dans `.env` : `TELEGRAM_CHAT_ID=...`
3. Teste : `python run.py --telegram-test`.

Le terminal doit tourner (PC allumé) pour envoyer des alertes. Sans Telegram configuré, les alertes s'affichent dans la console.

**Règles d'alerte** (réglables dans `.env`, voir `config.example.env`) :

- une confluence est « qualifiante » si elle a au moins `TERMINAL_ALERT_MIN_SCORE` sources (3 par défaut ; une poche AIMANT compte +1)
  et qu'elle est à moins de 6 ATR du prix (timeframe `TERMINAL_ALERT_TF`, 1h par défaut) ;
- **nouvelle confluence** : une alerte, puis aucune autre pour la même zone pendant `TERMINAL_ALERT_COOLDOWN_HOURS` (6 h) ;
- **approche** : une alerte quand le prix arrive à 0,5 ATR d'une zone qualifiante ;
- au démarrage : un seul message de résumé (pas de rafale) ; 6 alertes par heure au maximum.

## 5. Utiliser

- Choisis le symbole (BTCUSDT, SOLUSDT...) et le timeframe en haut. Les niveaux sont les mêmes à tous les timeframes ; la fenêtre
  autour du prix et la tolérance des confluences s'adaptent à l'ATR du timeframe affiché.
- **Confluences** (par défaut) : seules les zones de la liste sont tracées. **Tous les niveaux** : tous ceux de la fenêtre, avec leurs noms.
- Clique une ligne de la liste, une bande, une barre de poche ou un niveau : le détail s'affiche à droite et les noms des niveaux
  concernés apparaissent sur le graphique.
- Poches : barre en dégradé ancrée sur la dernière bougie ; plus elle est longue et opaque, plus la poche est grosse. `AIMANT` = la plus
  forte de son côté (si ≥ 70 % de la plus grosse).

## 6. Lignes de conduite

- Le serveur n'écoute que sur ta machine (`127.0.0.1`) : il n'est pas accessible depuis le réseau.
- `.env` contient ton token Telegram : ne le partage jamais (il est exclu de git par `.gitignore`).
- Les données/alertes enregistrées sont dans `data_local/` (état des alertes, journal).

## 7. Tests et structure

```
python -m unittest discover -s tests -t .
```

```
run.py            point d'entrée (serveur, --selftest, --telegram-*)
config.py         configuration (.env)
engine/           calculs : profils de volume, VWAP/périodes, poches de liquidité, confluences, ATR
data/             sources : simulée, Binance ; historique en mémoire
alerts/           règles d'alerte, envoi Telegram
service.py        relie données + moteurs, fabrique l'état JSON
server.py         serveur local (API + fichiers de web/)
web/              interface (HTML/CSS/JS + TradingView Lightweight Charts)
tests/            tests automatiques
```

## 8. Limites connues de la V1

- L'adaptateur Binance a été écrit d'après la documentation et testé contre un **faux serveur Binance** ; son premier vrai essai
  est ton `--selftest`.
- Les poches reposent sur des hypothèses (répartition longs/shorts selon la direction de la bougie, poids de levier 10/20/30/40 % pour
  100x/50x/25x/10x, marge 0,4 %). Elles ne sont pas calibrées sur de vraies liquidations.
- Pas encore : statistiques de réaction du prix par type de niveau (V4), CVD/funding/prime Coinbase (V2), flux ETF et macro (V4).
