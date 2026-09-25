"""HTTP real contra PHP CLI: ayuda y errores; sin ejecutar operaciones del lector."""
import json
import pathlib
import shutil
import socket
import subprocess
import time
import unittest
import urllib.parse
import urllib.request


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        php = shutil.which("php")
        if not php:
            raise RuntimeError("PHP CLI debe estar disponible en PATH")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        root = pathlib.Path(__file__).resolve().parents[1]
        cls.url = f"http://127.0.0.1:{port}/PADBridge.php"
        cls.server = subprocess.Popen(
            [php, "-n", "-S", f"127.0.0.1:{port}", "-t", str(root)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cls.addClassCleanup(cls.stop_server)
        for _ in range(50):
            if cls.server.poll() is not None:
                raise RuntimeError("El servidor PHP termino antes de iniciar las pruebas")
            try:
                with urllib.request.urlopen(cls.url, timeout=1):
                    return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("No se pudo iniciar el servidor PHP")

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    def test_get_and_form_post_keep_json_error_contract(self):
        for method in ("GET", "POST"):
            for params, code in [({}, "ACTION_REQUIRED"),
                                 ({"action": "write-epc", "epc": "XYZ"}, "EPC_INVALID_HEX"),
                                 ({"action[]": "read-epc"}, "ACTION_INVALID")]:
                with self.subTest(method=method, params=params):
                    encoded = urllib.parse.urlencode(params)
                    url = self.url + ("?" + encoded if method == "GET" else "")
                    req = urllib.request.Request(url, data=encoded.encode() if method == "POST" else None,
                                                 method=method)
                    with urllib.request.urlopen(req, timeout=3) as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
                        self.assertIn("application/json", response.headers["Content-Type"])
                        data = json.load(response)
                    self.assertIs(data["ok"], False)
                    self.assertEqual(data["resultado"], "ERROR=" + code)
                    self.assertNotEqual(data["exit_code"], 0)
                    self.assertIn("stderr", data)

    def test_browser_without_action_gets_visual_help(self):
        request = urllib.request.Request(self.url, headers={"Accept": "text/html,application/xhtml+xml"})
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers["Content-Type"])
            self.assertIn("Accept", response.headers["Vary"])
            html = response.read().decode("utf-8")
        for action in ("read-epc", "inventory", "status", "write-epc", "clear", "version", "get-power", "set-power"):
            self.assertIn("<code>" + action + "</code>", html)
        self.assertIn("000000000000000000130527", html)
        self.assertIn('lang="es"', html)
        self.assertIn("Comprobar la conexión", html)
        self.assertNotIn("No comprueba que el pad responda", html)
        self.assertIn('name="power" type="number" min="5" max="30" step="1"', html)
        self.assertIn('data-result="get-power-result"', html)
        self.assertIn('data-result="set-power-result"', html)
        self.assertIn('name="palabras" value="6"', html)
        self.assertNotIn('href="PADBridge.php?action=write-epc', html)
        self.assertNotIn('href="PADBridge.php?action=clear', html)
        with urllib.request.urlopen(self.url.replace("PADBridge.php", "assets/help.css"), timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"@media", response.read())

    def test_explicit_help_does_not_require_browser_accept(self):
        request = urllib.request.Request(self.url + "?help=1", headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertIn("text/html", response.headers["Content-Type"])

    def test_json_clients_and_explicit_actions_keep_json(self):
        cases = [
            ("GET", "", "application/json", "ACTION_REQUIRED"),
            ("GET", "", "*/*", "ACTION_REQUIRED"),
            ("GET", "", "text/html;q=0, application/json", "ACTION_REQUIRED"),
            ("GET", "format=json", "text/html", "ACTION_REQUIRED"),
            ("POST", "", "text/html", "ACTION_REQUIRED"),
            ("POST", "help=1", "text/html", "ACTION_REQUIRED"),
            ("GET", "action=&help=1", "text/html", "ACTION_REQUIRED"),
            ("GET", "action[]=read-epc&help=1", "text/html", "ACTION_INVALID"),
            ("GET", "action=invalid&help=1", "text/html", "UNKNOWN_ACTION"),
            ("GET", "action=write-epc&epc=XYZ", "text/html", "EPC_INVALID_HEX"),
            ("GET", "help[]=1", "application/json", "ACTION_REQUIRED"),
        ]
        for method, query, accept, code in cases:
            with self.subTest(method=method, query=query, accept=accept):
                request = urllib.request.Request(self.url + "?" + query, headers={"Accept": accept}, method=method)
                with urllib.request.urlopen(request, timeout=3) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn("application/json", response.headers["Content-Type"])
                    data = json.load(response)
                self.assertIs(data["ok"], False)
                self.assertEqual(data["resultado"], "ERROR=" + code)

    def test_options_does_not_execute_an_operation(self):
        request = urllib.request.Request(self.url + "?help=1", headers={"Accept": "text/html"}, method="OPTIONS")
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 204)
            self.assertEqual(response.read(), b"")
            self.assertIn("POST", response.headers["Access-Control-Allow-Methods"])


if __name__ == "__main__":
    unittest.main()
