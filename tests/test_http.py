"""HTTP real contra PHP CLI; solo entradas rechazadas antes de ejecutar el bridge."""
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

    def test_options_does_not_execute_an_operation(self):
        request = urllib.request.Request(self.url, method="OPTIONS")
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 204)
            self.assertEqual(response.read(), b"")
            self.assertIn("POST", response.headers["Access-Control-Allow-Methods"])


if __name__ == "__main__":
    unittest.main()
