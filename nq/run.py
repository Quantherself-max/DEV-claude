#!/usr/bin/env python3
"""Terminal NQ (scalping, prop firm) : lance le serveur local et ouvre l'interface dans le navigateur.

  python run.py                       demarre avec des donnees SIMULEES (prix fictifs) pour essayer
  python run.py --source csv --csv C:\\chemin\\ticks.csv    lit de VRAIES transactions dans un fichier (voir README)
  python run.py --selftest            verifie la configuration et la source, sans ouvrir le navigateur
"""
import argparse
import json
import logging
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def port_busy(port: int, no_browser: bool) -> int:
    """Le port est deja pris : on dit par qui, au lieu d'echouer sans explication."""
    from server import API_LEVEL, VERSION
    url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url + "api/health", timeout=3) as r:
            info = json.loads(r.read())
    except Exception:
        info = None
    print("=" * 66)
    if info is None:
        print(f"  Le port {port} est déjà utilisé par un autre programme.")
        print("  Ferme-le, ou change NQ_PORT dans le fichier .env, puis relance.")
    elif (info.get("api") or 0) != API_LEVEL:
        print(f"  Une AUTRE version du terminal NQ tourne déjà sur le port {port} (version {info.get('version')}, celle-ci est la {VERSION}).")
        print("  Ferme l'ancienne fenêtre noire, puis relance ce fichier.")
    else:
        print(f"  Le terminal NQ tourne déjà : ouverture de la page {url}")
        if not no_browser:
            webbrowser.open(url)
    print("=" * 66)
    return 4


def selftest(cfg) -> int:
    from config import validate
    from service import Service
    bad = validate(cfg)
    for b in bad:
        print("  KO  " + b)
    if bad:
        return 1
    svc = Service(cfg)
    t0 = time.time()
    n = svc.load_sync()
    print(f"  {'OK ' if svc.status['state'] == 'ready' else 'KO '} source {cfg.source} : {svc.status['msg']} ({n} transactions en {time.time() - t0:.1f} s)")
    if svc.status["state"] != "ready":
        return 1
    st = svc.state()
    print(f"  OK  contrat {st['contract']['label']}, dernier prix {st['last']['p']}, delta réel : {st['deltaReal'] * 100:.0f} % des transactions")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):                 # console Windows : pas de plantage sur un accent ou un emoji
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=("simulated", "csv"))
    ap.add_argument("--csv", help="fichier de transactions (avec --source csv)")
    ap.add_argument("--instrument", help="NQ, MNQ, ES ou MES")
    ap.add_argument("--port", type=int)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    from config import load_config, validate
    cfg = load_config()
    if a.source:
        cfg.source = a.source
    if a.csv:
        cfg.csv_path, cfg.source = a.csv, "csv"
    if a.instrument:
        cfg.instrument = a.instrument.upper()
    if a.port:
        cfg.port = a.port
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.selftest:
        return selftest(cfg)
    bad = validate(cfg)
    if bad:
        print("\n".join("  " + b for b in bad))
        return 1

    from server import App, serve
    app = App(cfg)
    try:
        httpd = serve(app)
    except OSError:
        return port_busy(cfg.port, a.no_browser)
    url = f"http://127.0.0.1:{cfg.port}/"
    print("=" * 66)
    print(f"  Terminal NQ ouvert dans ton navigateur : {url}")
    print(f"  Source : {'données SIMULÉES (prix fictifs)' if cfg.source == 'simulated' else 'fichier ' + cfg.csv_path}")
    print(f"  Instrument : {cfg.instrument}   |   compte : {Path(cfg.data_dir) / 'compte.json'}")
    print("  Pour arrêter : ferme cette fenêtre (ou Ctrl+C).")
    print("=" * 66)
    app.start()
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        app.shutdown()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
