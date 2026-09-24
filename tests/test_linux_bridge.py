import contextlib
import importlib.util
import io
import pathlib
import types
import unittest
from unittest import mock

PATH = pathlib.Path(__file__).resolve().parents[1] / "linux" / "OR2103Bridge.py"
spec = importlib.util.spec_from_file_location("rfid_under_test", PATH)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

EPC = "000000000000000001000027"


def inventory_frame(epc):
    # Fixture del formato que el parser actual acepta; no afirma validar el protocolo del fabricante.
    frame = bytearray(21)
    frame[0:3] = bytes([0xA5, 18, 0x55])
    frame[6:18] = bytes.fromhex(epc)
    return bytes(frame)


class FakeSerial:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(bytes(data))

    def read(self, size):
        return self.responses.pop(0) if self.responses else b""

    def reset_input_buffer(self):
        pass

    def close(self):
        self.closed = True


class BridgeTests(unittest.TestCase):
    def invoke(self, args, device=None):
        factory = mock.Mock(return_value=device)
        output = io.StringIO()
        with mock.patch.object(bridge, "serial", types.SimpleNamespace(Serial=factory)), \
                mock.patch.object(bridge.time, "sleep"), contextlib.redirect_stdout(output):
            code = bridge.main(args)
        return code, output.getvalue(), factory

    def test_status_does_not_open_reader(self):
        code, output, factory = self.invoke(["status"])
        self.assertEqual(code, 0)
        self.assertIn("PORT=" + bridge.PORT, output)
        factory.assert_not_called()

    def test_invalid_actions_and_epcs_do_not_open_reader(self):
        for args in [[], ["missing"], ["version"], ["write-epc"], ["write-epc", "----"],
                     ["write-epc", "1000027"], ["write-epc", "A" * 128], ["clear", "32"], ["clear", "0"]]:
            with self.subTest(args=args):
                code, output, factory = self.invoke(args)
                self.assertNotEqual(code, 0)
                self.assertTrue(output.startswith("ERROR="))
                factory.assert_not_called()

    def test_write_command_bytes_unchanged(self):
        # Contrato de escritura previo: password, banco EPC, PC y EPC de 96 bits.
        expected = bytes.fromhex("A5 15 57 00000000 01 01 07 3000 " + EPC + "CD")
        self.assertEqual(bridge.build_write_epc(EPC), expected)

    def test_initial_inventory_response_is_not_lost(self):
        device = FakeSerial([b""] * 5 + [inventory_frame(EPC)])
        code, output, _ = self.invoke(["read-epc"], device)
        self.assertEqual(code, 0)
        self.assertEqual(output, "DETECTED=" + EPC + "\n")
        self.assertIn(bytes.fromhex("A5 00 54 54"), device.writes)
        self.assertTrue(device.closed)

    def test_inventory_deduplicates_multiple_tags(self):
        other = "E28436110000100004210970"
        device = FakeSerial([b""] * 5 + [inventory_frame(EPC), inventory_frame(other) + inventory_frame(EPC)])
        with mock.patch.object(bridge.time, "monotonic", side_effect=[0, 0, 0, 2]):
            code, output, _ = self.invoke(["inventory"], device)
        self.assertEqual(code, 0)
        self.assertEqual(output.splitlines(), ["DETECTED=" + EPC, "DETECTED=" + other])
        self.assertTrue(device.closed)

    def test_fragmented_inventory_frame_is_preserved(self):
        frame = inventory_frame(EPC)
        device = FakeSerial([b""] * 5 + [frame[:10], frame[10:]])
        code, output, _ = self.invoke(["read-epc"], device)
        self.assertEqual((code, output), (0, "DETECTED=" + EPC + "\n"))
        self.assertTrue(device.closed)

    def test_inventory_error_stops_and_closes_reader(self):
        device = FakeSerial()
        with mock.patch.object(device, "read", side_effect=[b""] * 6 + [OSError("read failed"), b""]):
            code, output, _ = self.invoke(["inventory"], device)
        self.assertEqual((code, output), (1, "ERROR=SERIAL_ERROR:read failed\n"))
        self.assertEqual(device.writes[-1], bytes.fromhex("A5 00 54 54"))
        self.assertTrue(device.closed)

    def test_cleared_tag_is_detected_with_24_zeros(self):
        zeros = "0" * 24
        writer = FakeSerial([b""] * 5 + [bytes.fromhex("A5 01 57 00 58")])
        code, output, _ = self.invoke(["clear", "6"], writer)
        self.assertEqual((code, output), (0, "WRITTEN=" + zeros + "\nOK\n"))
        reader = FakeSerial([b""] * 5 + [inventory_frame(zeros)])
        code, output, _ = self.invoke(["read-epc"], reader)
        self.assertEqual((code, output), (0, "DETECTED=" + zeros + "\n"))
        self.assertTrue(writer.closed and reader.closed)

    def test_inventory_includes_cleared_and_written_tags(self):
        zeros = "0" * 24
        device = FakeSerial([b""] * 5 + [inventory_frame(zeros) + inventory_frame(EPC) + inventory_frame(zeros)])
        with mock.patch.object(bridge.time, "monotonic", side_effect=[0, 2]):
            code, output, _ = self.invoke(["inventory"], device)
        self.assertEqual(code, 0)
        self.assertEqual(output.splitlines(), ["DETECTED=" + zeros, "DETECTED=" + EPC])
        self.assertTrue(device.closed)

    def test_no_tag_is_a_normal_result(self):
        for action in ("read-epc", "inventory"):
            for response in (b"", bytes.fromhex("A5 00 53 53"), b"\x00" * 24):
                with self.subTest(action=action, response=response):
                    device = FakeSerial([b""] * 5 + [response])
                    with mock.patch.object(bridge.time, "monotonic", side_effect=[0, 2]):
                        code, output, _ = self.invoke([action], device)
                    self.assertEqual((code, output), (0, "NO_TAG\n"))

    def test_write_ack_returns_ok(self):
        # Se conserva el reconocimiento de ACK existente; validacion binaria completa pendiente.
        device = FakeSerial([b""] * 5 + [bytes.fromhex("A5 01 57 00 58")])
        code, output, _ = self.invoke(["write-epc", EPC], device)
        self.assertEqual((code, output), (0, "WRITTEN=" + EPC + "\nOK\n"))
        self.assertTrue(device.closed)

    def test_failed_write_returns_nonzero(self):
        device = FakeSerial()
        code, output, _ = self.invoke(["write-epc", EPC], device)
        self.assertNotEqual(code, 0)
        self.assertIn("ERROR=WRITE_FAILED", output)
        self.assertNotIn("WRITTEN=", output)
        self.assertTrue(device.closed)

    def test_clear_respects_words(self):
        device = FakeSerial([b""] * 5 + [bytes.fromhex("A5 01 57 00 58")])
        code, output, _ = self.invoke(["clear", "10"], device)
        self.assertEqual((code, output), (0, "WRITTEN=" + "0" * 40 + "\nOK\n"))
        self.assertIn(bridge.build_write_epc("0" * 40), device.writes)

    def test_serial_error_is_reported_without_traceback(self):
        output = io.StringIO()
        with mock.patch.object(bridge, "serial", types.SimpleNamespace(Serial=mock.Mock(side_effect=OSError("missing port")))), \
                contextlib.redirect_stdout(output):
            code = bridge.main(["read-epc"])
        self.assertNotEqual(code, 0)
        self.assertEqual(output.getvalue(), "ERROR=SERIAL_ERROR:missing port\n")


if __name__ == "__main__":
    unittest.main()
