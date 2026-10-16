#!/usr/bin/env python3
"""Terminal de liquidite : lance le serveur local, l'interface web et les alertes Telegram.

  python run.py                  demarre (les reglages se font ensuite dans le terminal : bouton Reglages) ; le terminal se met a jour et redemarre
                                 tout seul quand une nouvelle version est publiee (Reglages -> Mises a jour), sans fermer cette fenetre
  python run.py --selftest       verifie Binance (et Telegram si configure)
  python run.py --telegram-chatid   affiche ton chat id (apres avoir ecrit un message a ton bot)
  python run.py --telegram-test  envoie un message de test
"""
import argparse
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# les modules du terminal sont importes plus bas, dans le processus qui fait tourner le terminal : le processus de relance (supervise) ne depend que
# d'updater.py, si bien qu'une version cassee ne peut pas l'empecher de remettre la precedente en place


def selftest(cfg) -> int:
    from alerts.notifier import TelegramNotifier
    from data.binance import BinanceSource
    bad = 0
    print("== Binance ==")
    for name, ok, detail in BinanceSource().selftest(cfg.symbols[0]):
        print(("  OK  " if ok else "  KO  ") + f"{name} : {detail}")
        bad += not ok and "optionnel" not in detail
    print("== Telegram ==")
    if cfg.telegram_on:
        ok, detail = TelegramNotifier(cfg.telegram_token, cfg.telegram_chat_id, cfg.telegram_api_base).send("✅ Test du terminal : Telegram fonctionne.")
        print(("  OK  " if ok else "  KO  ") + f"message de test : {detail}")
        bad += not ok
    else:
        print("  --  non configure : bouton Reglages dans le terminal (ou TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID dans .env)")
    return 1 if bad else 0


PORT_BUSY = 4                                                        # code de sortie : le port est deja pris par un autre terminal


def port_busy(port: int, no_browser: bool) -> int:
    """Le port est deja pris. Si c'est une AUTRE version du terminal (plus ancienne, ou lancee depuis un autre dossier), on le dit clairement :
    sinon on ouvrirait la page d'un ancien programme (nouvelles pages, ancien moteur : vues en « HTTP 404 »)."""
    import json
    import urllib.request
    from server import API_LEVEL, VERSION
    url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url + "api/health", timeout=4) as r:
            info = json.loads(r.read())
    except Exception:
        info = None
    other_dir = bool(info and info.get("root")) and os.path.normcase(str(info["root"])) != os.path.normcase(str(HERE))
    print("=" * 64)
    if info is None:
        print(f"  Le port {port} est deja utilise par un autre programme (ou un terminal qui ne repond pas).")
        print("  Ferme l'autre fenetre du terminal (ou change TERMINAL_PORT dans .env), puis relance ce fichier.")
    elif (info.get("api") or 0) < API_LEVEL or other_dir:
        print(f"  Une AUTRE version du terminal tourne deja sur le port {port}"
              f" ({'version ' + str(info['version']) if info.get('version') else 'ancienne version'}"
              f"{', lancee depuis un autre dossier : ' + str(info['root']) if other_dir else ''}) ; celle-ci est la version {VERSION}.")
        print("  1. Ferme la fenetre noire « Liq Terminal » deja ouverte (ou Ctrl+C dedans).")
        print("  2. Relance ce fichier : la page s'ouvrira sur la bonne version.")
    else:
        print(f"  Le terminal tourne deja : ouverture de la page {url}")
        if not no_browser:
            webbrowser.open(url)
    print("=" * 64)
    return PORT_BUSY


def supervise(argv: list) -> int:
    """Lance le terminal dans un processus enfant et le relance quand il le demande (mise a jour installee). Si une version tout juste installee
    s'arrete en erreur, la version precedente est remise en place puis relancee."""
    from updater import RESTART_CODE, Updater
    env = dict(os.environ)
    while True:
        t0 = time.time()
        p = subprocess.Popen([sys.executable, str(HERE / "run.py"), "--child", *argv], env=env)
        try:
            code = p.wait()
        except KeyboardInterrupt:
            try:
                p.wait(timeout=20)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                p.kill()
            return 0
        env["LIQ_NO_BROWSER"] = "1"                                  # la page deja ouverte se recharge toute seule
        env["LIQ_RESTART"] = "1"                                     # pas de message « Terminal demarre » sur Telegram a chaque relance
        if code == RESTART_CODE:
            print("\n== Nouvelle version installée : redémarrage du terminal (la page du navigateur se recharge toute seule) ==\n", flush=True)
            continue
        if code == PORT_BUSY:                                        # un autre terminal occupe deja le port : rien a remettre en place
            return code
        u = Updater(HERE)
        if code != 0 and u.state().get("pendingVerify") and u.rollback():
            print(f"\n== La nouvelle version s'est arrêtée en erreur après {time.time() - t0:.0f} s : retour automatique à la version précédente ==\n", flush=True)
            continue
        return code


def main() -> int:
    for stream in (sys.stdout, sys.stderr):          # console Windows : pas de plantage sur un emoji
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--telegram-chatid", action="store_true")
    ap.add_argument("--telegram-test", action="store_true")
    ap.add_argument("--source", choices=("simulated", "binance"))
    ap.add_argument("--port", type=int)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-supervisor", action="store_true", help="sans relance automatique (ni mise a jour automatique)")
    a = ap.parse_args()
    if not (a.child or a.no_supervisor or a.selftest or a.telegram_chatid or a.telegram_test):
        return supervise([x for x in sys.argv[1:] if x != "--child"])
    if os.environ.get("LIQ_NO_BROWSER"):
        a.no_browser = True
    from alerts.notifier import TelegramNotifier
    from config import ROOT, load_config, migrate_env
    from server import App, serve
    cfg = load_config()
    if migrate_env(ROOT / ".env", cfg.data_dir):
        cfg = load_config()                                         # V13.1 : retour une seule fois a « achats et ventes »
    if a.source:
        cfg.source = a.source
    if a.port:
        cfg.port = a.port
    if a.selftest:
        return selftest(cfg)
    if a.telegram_chatid or a.telegram_test:
        if not cfg.telegram_token:
            print("TELEGRAM_BOT_TOKEN manquant (bouton Reglages dans le terminal, ou fichier .env)")
            return 1
        tn = TelegramNotifier(cfg.telegram_token, cfg.telegram_chat_id, cfg.telegram_api_base)
        if a.telegram_chatid:
            ids = tn.find_chat_ids()
            print("Conversations vues par ton bot :", ids or "aucune : ecris d'abord un message a ton bot dans Telegram, puis relance")
            return 0
        print(tn.send("✅ Test du terminal : Telegram fonctionne."))
        return 0

    app = App(cfg, updates=a.child)
    try:
        httpd = serve(app)
    except OSError:
        return port_busy(cfg.port, a.no_browser)
    url = f"http://127.0.0.1:{cfg.port}/"
    print("=" * 64)
    print(f"  Terminal ouvert dans ton navigateur : {url}")
    print(f"  Source : {'donnees SIMULEES (prix fictifs)' if cfg.source == 'simulated' else 'Binance (reel)'}"
          f" | alertes : {'Telegram' if cfg.telegram_on else 'console seulement'}")
    print("  Reglages (donnees reelles, Telegram) : bouton  Reglages  en haut a droite du terminal.")
    print("  Pour arreter : ferme cette fenetre (ou Ctrl+C).")
    print("=" * 64)
    app.httpd = httpd
    app.start_background()
    app.start_code_watch()                                           # nouvelle version copiee dans le dossier : redemarrage (ou bandeau)
    threading.Thread(target=app.refresh_loop, daemon=True).start()
    if a.child:
        app.start_updates()                                          # verification des nouvelles versions (Reglages -> Mises a jour)
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nArret.")
    finally:
        app.shutdown()
        httpd.server_close()
    if app.restart_requested:
        from updater import RESTART_CODE
        return RESTART_CODE
    return 0


if __name__ == "__main__":
    sys.exit(main())
