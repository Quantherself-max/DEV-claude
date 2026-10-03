#!/usr/bin/env python3
"""Terminal de liquidite : lance le serveur local, l'interface web et les alertes Telegram.

  python run.py                  demarre (donnees simulees tant que TERMINAL_SOURCE n'est pas "binance")
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

from alerts.notifier import ConsoleNotifier, TelegramNotifier   # noqa: E402
from alerts.rules import AlertEngine                            # noqa: E402
from config import load_config                                  # noqa: E402
from data.binance import BinanceSource                          # noqa: E402
from data.simulated import SimulatedSource                      # noqa: E402
from server import App, serve                                   # noqa: E402
from service import Service                                     # noqa: E402


def build(cfg):
    source = BinanceSource() if cfg.source == "binance" else SimulatedSource()
    notifier = TelegramNotifier(cfg.telegram_token, cfg.telegram_chat_id, cfg.telegram_api_base) \
        if cfg.telegram_on else ConsoleNotifier()
    service = Service(source, cfg)
    alerts = AlertEngine(cfg, notifier)
    return App(cfg, service, alerts, notifier)


def selftest(cfg) -> int:
    bad = 0
    print("== Binance ==")
    for name, ok, detail in BinanceSource().selftest(cfg.symbols[0]):
        print(("  OK  " if ok else "  KO  ") + f"{name} : {detail}")
        bad += not ok
    print("== Telegram ==")
    if cfg.telegram_on:
        ok, detail = TelegramNotifier(cfg.telegram_token, cfg.telegram_chat_id, cfg.telegram_api_base).send("✅ Test du terminal : Telegram fonctionne.")
        print(("  OK  " if ok else "  KO  ") + f"message de test : {detail}")
        bad += not ok
    else:
        print("  --  non configure (TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID dans .env) : les alertes s'affichent seulement ici")
    return 1 if bad else 0


def main() -> int:
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
            print("TELEGRAM_BOT_TOKEN manquant dans .env")
            return 1
        tn = TelegramNotifier(cfg.telegram_token, cfg.telegram_chat_id, cfg.telegram_api_base)
        if a.telegram_chatid:
            ids = tn.find_chat_ids()
            print("Conversations vues par ton bot :", ids or "aucune : ecris d'abord un message a ton bot dans Telegram, puis relance")
            return 0
        print(tn.send("✅ Test du terminal : Telegram fonctionne."))
        return 0

    app = build(cfg)
    httpd = serve(app)
    url = f"http://{cfg.host}:{cfg.port}/"
    print(f"Terminal : {url}   (source : {cfg.source}, alertes : {'Telegram' if cfg.telegram_on else 'console seulement'})")
    if cfg.source == "simulated":
        print("ATTENTION : donnees SIMULEES (prix fictifs). Mets TERMINAL_SOURCE=binance dans .env pour le reel.")
    threading.Thread(target=app.refresh_loop, daemon=True).start()
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nArret.")
    finally:
        app.stop.set()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
