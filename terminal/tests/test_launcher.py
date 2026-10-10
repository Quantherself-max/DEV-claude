"""Lanceur (V17.1) : port deja pris par une autre version du terminal, relance automatique quand une nouvelle version est copiee."""
import contextlib
import io
import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import run
import server as server_mod


def health_server(payload):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def busy(port):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), mock.patch.object(run.webbrowser, "open") as wb:
        code = run.port_busy(port, no_browser=False)
    return code, out.getvalue(), wb


class PortBusyTests(unittest.TestCase):
    def test_old_version_is_named_and_not_opened(self):
        srv = health_server({"ok": True})                                              # V16 : ni version ni dossier
        try:
            code, out, wb = busy(srv.server_address[1])
        finally:
            srv.shutdown(); srv.server_close()
        self.assertEqual(code, run.PORT_BUSY)
        self.assertIn("AUTRE version", out)
        self.assertIn("ancienne version", out)
        wb.assert_not_called()                                                          # ne pas ouvrir la page de l'ancien programme

    def test_other_folder_and_same_version(self):
        srv = health_server({"api": server_mod.API_LEVEL, "version": "17.1", "root": "/ailleurs/terminal"})
        try:
            code, out, wb = busy(srv.server_address[1])
        finally:
            srv.shutdown(); srv.server_close()
        self.assertIn("autre dossier", out)
        wb.assert_not_called()
        srv = health_server({"api": server_mod.API_LEVEL, "version": server_mod.VERSION, "root": str(run.HERE)})
        try:
            code, out, wb = busy(srv.server_address[1])
        finally:
            srv.shutdown(); srv.server_close()
        self.assertIn("tourne deja : ouverture", out)
        wb.assert_called_once()

    def test_port_taken_by_something_else(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                                                                       # personne n'ecoute : pas de reponse
        code, out, wb = busy(port)
        self.assertEqual(code, run.PORT_BUSY)
        self.assertIn("autre programme", out)
        wb.assert_not_called()


class SupervisorTests(unittest.TestCase):
    def test_port_busy_child_is_not_rolled_back(self):
        class P:
            def __init__(self, *a, **k):
                pass

            def wait(self, timeout=None):
                return run.PORT_BUSY
        with mock.patch.object(run.subprocess, "Popen", P), mock.patch("updater.Updater.rollback") as rb:
            self.assertEqual(run.supervise([]), run.PORT_BUSY)
        rb.assert_not_called()


if __name__ == "__main__":
    unittest.main()
