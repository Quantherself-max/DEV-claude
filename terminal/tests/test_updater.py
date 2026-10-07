import io
import json
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from updater import LAUNCHERS, Updater, UpdateError

TOKEN = "github_pat_TEST123"
BASE_FILES = {"run.py": "print('v')\n", "server.py": "X = 1\n", "service.py": "Y = 1\n", "config.py": "Z = 1\n", "updater.py": "U = 1\n",
              "web/index.html": "<html>v1</html>\n", "engine/a.py": "A = 1\n", "Lancer-Terminal-Windows.bat": "@echo v1\n"}


def zip_of(sha, files, top_extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        top = f"o-r-{sha[:7]}"
        z.writestr(f"{top}/README.md", "racine du depot\n")
        for rel, txt in files.items():
            z.writestr(f"{top}/terminal/{rel}", txt)
        for name, txt in (top_extra or {}).items():
            z.writestr(name, txt)
    return buf.getvalue()


class FakeGitHub:
    """Imite l'API GitHub : branches, commits, contenu, archive (redirection vers un autre hote, sans jeton)."""

    def __init__(self):
        self.branches = {}          # nom -> sha
        self.commits = {}           # sha -> (date, message, fichiers ou None si la branche n'a pas le terminal)
        self.extra = {}             # sha -> entrees supplementaires dans l'archive
        self.codeload_auth = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=b"", ctype="application/json", headers=None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urlparse(self.path)
                q = parse_qs(u.query)
                if u.path.startswith("/codeload/"):
                    fake.codeload_auth.append(self.headers.get("Authorization"))
                    sha = u.path.split("/")[-1].replace(".zip", "")
                    return self._send(200, zip_of(sha, fake.commits[sha][2], fake.extra.get(sha)), "application/zip")
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    return self._send(404, b'{"message":"Not Found"}')
                parts = u.path.split("/")
                if u.path == "/repos/o/r/branches":
                    return self._send(200, json.dumps([{"name": n, "commit": {"sha": s}} for n, s in fake.branches.items()]).encode())
                if u.path.startswith("/repos/o/r/commits/"):
                    ref = unquote(parts[-1])
                    sha = fake.branches.get(ref, ref)
                    if sha not in fake.commits:
                        return self._send(404, b"{}")
                    d, m, _ = fake.commits[sha]
                    return self._send(200, json.dumps({"sha": sha, "commit": {"committer": {"date": d}, "message": m + "\n\ndetail"}}).encode())
                if u.path == "/repos/o/r/contents/terminal/run.py":
                    sha = fake.branches.get((q.get("ref") or [""])[0])
                    ok = sha and fake.commits[sha][2] is not None
                    return self._send(200 if ok else 404, b"{}")
                if u.path.startswith("/repos/o/r/zipball/"):
                    sha = parts[-1]
                    return self._send(302, b"", headers={"Location": f"http://127.0.0.1:{self.server.server_address[1]}/codeload/{sha}.zip"})
                return self._send(404, b"{}")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def publish(self, branch, sha, date, message, files):
        self.commits[sha] = (date, message, files)
        self.branches[branch] = sha

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def install_v1(root: Path):
    for rel, txt in BASE_FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    (root / "data_local").mkdir()
    (root / "data_local" / "journal.json").write_text("mes donnees", encoding="utf-8")
    (root / ".env").write_text("TELEGRAM_BOT_TOKEN=secret\n", encoding="utf-8")


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGitHub()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "terminal"
        self.root.mkdir()
        install_v1(self.root)
        v2 = dict(BASE_FILES, **{"web/index.html": "<html>v2</html>\n", "engine/b.py": "B = 2\n", "Lancer-Terminal-Windows.bat": "@echo v2\n"})
        self.gh.publish("main", "a" * 40, "2026-09-01T10:00:00Z", "ancienne branche", None)
        self.gh.publish("claude/x", "b" * 40, "2026-10-06T10:00:00Z", "V10 : nouveautes", v2)

    def tearDown(self):
        self.gh.close()
        self.tmp.cleanup()

    def up(self, **kw):
        return Updater(self.root, "o/r", kw.pop("branch", "auto"), kw.pop("token", TOKEN), api=self.gh.url, smoke=kw.pop("smoke", False), timeout=10)

    def test_auto_picks_most_recent_branch_with_the_terminal(self):
        r = self.up().check()
        self.assertTrue(r["newer"])
        self.assertEqual(r["latest"]["branch"], "claude/x")
        self.assertEqual(r["latest"]["message"], "V10 : nouveautes")
        self.gh.publish("vide", "c" * 40, "2026-10-07T10:00:00Z", "autre projet sans terminal", None)
        self.assertEqual(self.up().latest()["branch"], "claude/x")         # la branche la plus recente n'a pas le terminal : ignoree
        self.assertEqual(self.up(branch="main").latest()["sha"], "a" * 40)

    def test_private_repo_without_token_is_explained(self):
        with self.assertRaises(UpdateError) as e:
            self.up(token="").check()
        self.assertIn("jeton", str(e.exception))

    def test_apply_replaces_code_keeps_data_settings_and_running_launcher(self):
        u = self.up()
        res = u.apply()
        self.assertTrue(res["restart"])
        self.assertIn("web/index.html", res["changed"])
        self.assertIn("engine/b.py", res["changed"])
        self.assertEqual((self.root / "web/index.html").read_text(), "<html>v2</html>\n")
        self.assertEqual((self.root / "data_local" / "journal.json").read_text(), "mes donnees")
        self.assertEqual((self.root / ".env").read_text(), "TELEGRAM_BOT_TOKEN=secret\n")
        self.assertEqual((self.root / "Lancer-Terminal-Windows.bat").read_text(), "@echo v1\n")           # lanceur en cours d'utilisation : pas touche
        self.assertEqual((self.root / ".update" / "lanceurs" / "Lancer-Terminal-Windows.bat").read_text(), "@echo v2\n")
        self.assertEqual(res["launchers"], ["Lancer-Terminal-Windows.bat"])
        st = u.state()
        self.assertEqual(st["sha"], "b" * 40)
        self.assertTrue(st["pendingVerify"])
        self.assertEqual(self.gh.codeload_auth, [None])                                               # le jeton ne part pas vers l'hote de telechargement
        self.assertFalse(u.check()["newer"])
        again = u.apply(u.latest())
        self.assertFalse(again["restart"])                                                            # rien de neuf : pas de redemarrage
        u.mark_healthy()
        self.assertFalse(u.state()["pendingVerify"])
        self.assertTrue(set(LAUNCHERS) >= {"Lancer-Terminal-Windows.bat"})

    def test_removed_files_are_deleted_and_rollback_restores(self):
        u = self.up()
        u.apply()
        v3 = {k: v for k, v in BASE_FILES.items() if k != "engine/a.py"}
        v3["service.py"] = "Y = 3\n"
        self.gh.publish("claude/x", "d" * 40, "2026-10-07T09:00:00Z", "V11", v3)
        res = u.apply()
        self.assertIn("engine/a.py", res["removed"])
        self.assertIn("engine/b.py", res["removed"])
        self.assertFalse((self.root / "engine/a.py").exists())
        self.assertEqual(u.state()["previous"]["sha"], "b" * 40)
        self.assertTrue(u.rollback())
        self.assertTrue((self.root / "engine/a.py").exists())
        self.assertEqual((self.root / "service.py").read_text(), "Y = 1\n")
        self.assertEqual((self.root / "web/index.html").read_text(), "<html>v2</html>\n")
        st = u.state()
        self.assertEqual(st["sha"], "b" * 40)
        self.assertEqual(st["rolledBack"]["sha"], "d" * 40)
        self.assertFalse(st["pendingVerify"])
        self.assertEqual((self.root / "data_local" / "journal.json").read_text(), "mes donnees")

    def test_broken_version_is_refused_and_nothing_changes(self):
        bad = dict(BASE_FILES, **{"service.py": "def oups(:\n"})
        self.gh.publish("claude/x", "e" * 40, "2026-10-07T11:00:00Z", "cassee", bad)
        with self.assertRaises(UpdateError) as e:
            self.up().apply()
        self.assertIn("compile", str(e.exception))
        self.assertEqual((self.root / "service.py").read_text(), "Y = 1\n")
        self.assertFalse(self.up().state())
        incomplete = {k: v for k, v in BASE_FILES.items() if k != "server.py"}
        self.gh.publish("claude/x", "f" * 40, "2026-10-07T12:00:00Z", "incomplete", incomplete)
        with self.assertRaises(UpdateError) as e:
            self.up().apply()
        self.assertIn("incomplète", str(e.exception))

    def test_version_that_fails_to_import_is_refused(self):
        bad = dict(BASE_FILES, **{"server.py": "import module_qui_n_existe_pas\n"})
        self.gh.publish("claude/x", "9" * 40, "2026-10-07T11:00:00Z", "import casse", bad)
        with self.assertRaises(UpdateError) as e:
            self.up(smoke=True).apply()
        self.assertIn("ne démarre pas", str(e.exception))
        ok = self.up(smoke=True).apply(self.up().latest() | {"sha": "b" * 40})
        self.assertTrue(ok["restart"])

    def test_archive_paths_outside_the_folder_are_refused(self):
        self.gh.extra["b" * 40] = {"o-r-bbbbbbb/terminal/../../evil.py": "x = 1\n"}
        with self.assertRaises(UpdateError):
            self.up().apply()
        self.assertFalse((Path(self.tmp.name) / "evil.py").exists())

    def test_git_checkout_is_left_alone(self):
        (self.root / ".git").mkdir()
        with self.assertRaises(UpdateError) as e:
            self.up().apply()
        self.assertIn("git", str(e.exception))


class AppUpdateTests(unittest.TestCase):
    """Le serveur : statut sans jeton en clair, installation, demande de relance, reglages, en-tete de demarrage."""

    def setUp(self):
        from config import Config
        from data.simulated import SimulatedSource
        from server import App
        from tests.test_data_server import NOW
        self.gh = FakeGitHub()
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name) / "terminal"
        self.root.mkdir()
        install_v1(self.root)
        self.gh.publish("claude/x", "b" * 40, "2026-10-06T10:00:00Z", "V10", dict(BASE_FILES, **{"web/index.html": "<html>v2</html>\n"}))
        cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=str(Path(self.tmp.name) / "data"), port=0, update_token=TOKEN)
        mk = lambda c: Updater(self.root, "o/r", c.update_branch, c.update_token, api=self.gh.url, smoke=False, timeout=10)
        self.app = App(cfg, env_path=Path(self.tmp.name) / ".env", make_source=lambda c: SimulatedSource(now_ms=NOW), make_hub=lambda c, s: None, make_updater=mk)

    def tearDown(self):
        self.gh.close()
        self.tmp.cleanup()

    def test_status_check_and_install_without_supervisor(self):
        s = self.app.update_status()
        self.assertNotIn(TOKEN, json.dumps(s))
        self.assertTrue(s["configured"])
        self.assertTrue(s["tokenHint"].endswith("T123"))
        c = self.app.update_check(install=False)
        self.assertTrue(c["newer"])
        self.assertEqual((self.root / "web/index.html").read_text(), "<html>v1</html>\n")
        r = self.app.update_check(install=True)
        self.assertEqual((self.root / "web/index.html").read_text(), "<html>v2</html>\n")
        self.assertFalse(self.app.restart_requested)                       # lance sans run.py : pas de relance, la version s'appliquera au prochain demarrage
        self.assertIn("relance", r["state"])

    def test_install_under_supervisor_requests_a_restart(self):
        self.app.updates_on = True
        r = self.app.update_check()                                          # mise a jour automatique active par defaut
        self.assertTrue(self.app.restart_requested)
        self.assertIn("redémarrage", r["state"])

    def test_auto_off_only_reports(self):
        self.app.cfg.update_auto = False
        r = self.app.update_check()
        self.assertTrue(r["newer"])
        self.assertEqual((self.root / "web/index.html").read_text(), "<html>v1</html>\n")

    def test_errors_are_readable(self):
        self.app.cfg.update_token = ""
        r = self.app.update_check()
        self.assertEqual(r["state"], "erreur")
        self.assertIn("jeton", r["error"])

    def test_settings_store_token_in_env_only(self):
        out = self.app.save_settings({"updateToken": "github_pat_ABCD9999", "updateAuto": False, "updateBranch": "claude/x"})
        env = (Path(self.tmp.name) / ".env").read_text()
        self.assertIn("TERMINAL_GITHUB_TOKEN=github_pat_ABCD9999", env)
        self.assertIn("TERMINAL_UPDATE_AUTO=0", env)
        self.assertNotIn("github_pat_ABCD9999", json.dumps(out))
        self.assertEqual(out["update"]["branch"], "claude/x")
        self.assertFalse(out["update"]["auto"])
        with self.assertRaises(ValueError):
            self.app.save_settings({"updateToken": "jeton avec espaces"})
        with self.assertRaises(ValueError):
            self.app.save_settings({"updateBranch": "../../etc"})

    def test_every_json_answer_carries_the_boot_id(self):
        import urllib.request
        from server import serve
        httpd = serve(self.app)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            port = httpd.server_address[1]
            with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/update", headers={"Host": f"127.0.0.1:{port}"}), timeout=10) as r:
                self.assertEqual(r.headers.get("X-Terminal-Boot"), self.app.boot)
                self.assertIn("installed", json.loads(r.read()))
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
