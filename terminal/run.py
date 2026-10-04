#!/usr/bin/env python3
"""Terminal de liquidite : lance le serveur local, l'interface web et les alertes Telegram.

  python run.py                  demarre (les reglages se font ensuite dans le terminal : bouton Reglages)
  python run.py --selftest       verifie Binance (et Telegram si configure)
  python run.py --telegram-chatid   affiche ton chat id (apres avoir ecrit un message a ton bot)
  python run.py --telegram-test  envoie un message de test
"""
import argparse
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alerts.notifier import TelegramNotifier   # noqa: E402
from config import load_config                 # noqa: E402
from data.binance import BinanceSource         # noqa: E402
from server import App, serve                  # noqa: E402


def selftest(cfg) -> int:
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
    a = ap.parse_args()
    cfg = load_config()
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

    app = App(cfg)
    try:
        httpd = serve(app)
    except OSError:
        print(f"Le port {cfg.port} est deja utilise : le terminal tourne peut-etre deja. Ouvre http://127.0.0.1:{cfg.port}/")
        if not a.no_browser:
            webbrowser.open(f"http://127.0.0.1:{cfg.port}/")
        return 1
    url = f"http://127.0.0.1:{cfg.port}/"
    print("=" * 64)
    print(f"  Terminal ouvert dans ton navigateur : {url}")
    print(f"  Source : {'donnees SIMULEES (prix fictifs)' if cfg.source == 'simulated' else 'Binance (reel)'}"
          f" | alertes : {'Telegram' if cfg.telegram_on else 'console seulement'}")
    print("  Reglages (donnees reelles, Telegram) : bouton  Reglages  en haut a droite du terminal.")
    print("  Pour arreter : ferme cette fenetre (ou Ctrl+C).")
    print("=" * 64)
    threading.Thread(target=app.refresh_loop, daemon=True).start()
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nArret.")
    finally:
        app.stop.set()
        app.wake.set()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
