# Faire tourner le terminal 24 h/24 sans ton ordinateur

Le terminal est un programme : il surveille le marché, calcule les idées de trade et les envoie sur Telegram **tant qu'il tourne**. Éteins ton PC et plus rien n'est envoyé ni suivi. La solution : l'installer sur un petit **serveur loué** (ou un mini-ordinateur toujours allumé). Il ne dépend plus de ton PC.

## Ce qu'il te faut
- **Un serveur Linux** : Ubuntu 22.04 ou 24.04 (ou Debian 12), **2 Go de mémoire** (j'ai mesuré 350 Mo avec 2,5 ans d'historique simulé ; compte environ 1 Go avec 7 ans d'historique réel, donc 1 Go serait trop juste), 10 Go de disque.
- **Hébergé en Europe** (Allemagne, France, Finlande...). Binance bloque certains pays, dont les États-Unis : un serveur là-bas ne recevrait aucune donnée. Prix indicatif : environ 4 à 7 € par mois chez Hetzner, OVHcloud, Scaleway, Contabo... (à vérifier chez le fournisseur).
- Alternative à la maison : un **Raspberry Pi 4 ou 5** (système 64 bits) ou un vieux PC sous Linux, toujours allumé et branché à Internet.
- Le **ZIP du terminal** (le même que d'habitude), et ton **token Telegram** et ton **chat id** (dans ⚙ du terminal, ou dans ton fichier `.env`).

## Installation (10 minutes)
1. **Loue le serveur.** Choisis Ubuntu 24.04, un emplacement en Europe. Le fournisseur te donne une adresse IP et un mot de passe (ou te fait créer une clé SSH).
2. **Envoie le ZIP sur le serveur.** Sous Windows 10/11, ouvre **PowerShell** et tape (en adaptant le nom du fichier et l'adresse IP) :
   ```
   scp "$HOME\Downloads\DEV-claude-claude-festive-gates-viq9oo.zip" root@ADRESSE_IP:/root/liq.zip
   ```
   (Sans ligne de commande : le logiciel gratuit WinSCP fait la même chose en glisser-déposer.)
3. **Connecte-toi au serveur** : `ssh root@ADRESSE_IP`
4. **Installe** (copie ces trois lignes) :
   ```
   apt-get update && apt-get install -y unzip
   rm -rf /root/liq && unzip -q /root/liq.zip -d /root/liq
   bash /root/liq/*/terminal/serveur/installer-serveur.sh
   ```
   Le script te demande ton **token Telegram** (rien ne s'affiche quand tu le colles, c'est normal) puis ton **chat id**. Il installe Python, copie le terminal dans `/opt/liq-terminal` et le configure comme **service permanent** : il démarre tout seul, et redémarre après une panne ou un redémarrage du serveur.
5. **Vérifie.** Dans la minute, tu reçois sur Telegram : « Terminal démarré. Tu ne recevras que les idées de trade… ». Pour vérifier que Binance est joignable depuis ce serveur :
   ```
   sudo -u liq python3 /opt/liq-terminal/terminal/run.py --selftest
   ```
   Si tu vois « KO » avec une erreur de zone ou « 451 », ce serveur est dans un pays bloqué : choisis un autre emplacement.
6. **Arrête le terminal de ton PC** (ou mets `TERMINAL_SIGNALS=0` dans son `.env`), sinon tu recevras chaque idée en double.

Au premier lancement, le terminal télécharge l'historique (depuis 2019) : compte quelques minutes avant les premières idées.

## Voir l'interface depuis ton PC (facultatif)
Le terminal ne s'ouvre à personne d'autre que le serveur lui-même : rien n'est exposé sur Internet. Pour voir l'interface (graphiques, onglet Idées, réglages) depuis ton PC, ouvre un tunnel sécurisé dans PowerShell et laisse la fenêtre ouverte :
```
ssh -L 8765:127.0.0.1:8765 root@ADRESSE_IP
```
Puis ouvre **http://127.0.0.1:8765/** dans ton navigateur. Les réglages (⚙) y fonctionnent comme d'habitude. Sans tunnel, modifie le fichier de réglages sur le serveur (`nano /opt/liq-terminal/terminal/.env`) puis `systemctl restart liq-terminal`.

## Commandes utiles (sur le serveur)
| Pour... | Commande |
|---|---|
| voir ce que fait le terminal | `journalctl -u liq-terminal -f` (Ctrl+C pour quitter) |
| connaître son état | `systemctl status liq-terminal` |
| le redémarrer | `systemctl restart liq-terminal` |
| l'arrêter | `systemctl stop liq-terminal` |

## Mettre à jour
Télécharge le nouveau ZIP sur ton PC, renvoie-le avec `scp` (étape 2), puis refais l'étape 4. Ton `.env` et l'historique déjà téléchargé sont conservés.

## Gagner du temps (facultatif)
Pour éviter le téléchargement initial de l'historique, copie le dossier `data_local` de ton PC dans `/opt/liq-terminal/terminal/` avant l'étape 4, puis `chown -R liq:liq /opt/liq-terminal`. Sinon le serveur le retélécharge lui-même.

## Sécurité
- Le serveur contient ton token Telegram (et ton jeton X si tu l'utilises) dans `/opt/liq-terminal/terminal/.env`, lisible seulement par root et par le service. Protège l'accès au serveur : mot de passe long, de préférence une **clé SSH**, mises à jour régulières (`apt-get update && apt-get upgrade -y`).
- Le terminal n'a besoin d'aucune clé d'exchange : il lit des données publiques. N'en mets jamais, surtout avec un droit de trading.

## Limites
- Je n'ai pas pu tester l'installation sur un vrai serveur depuis mon environnement : le script a été testé en simulation (copie, réglages, mise à jour qui garde `.env` et historique, démarrage du terminal sans navigateur). Si une étape échoue, copie-moi le message d'erreur.
- Si le serveur tombe en panne ou si le fournisseur coupe le service, rien n'est envoyé ni suivi pendant ce temps.
- Les idées dépendent de la connexion de ce serveur à Binance, Yahoo Finance, CoinGecko et Telegram.
