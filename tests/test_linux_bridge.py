import contextlib
import importlib.util
import io
import json
import tempfile
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


def init_responses(power=10):
    # Get mode, ACK de potencia, lectura de confirmacion, area EPC, buzzer.
    return [b"", bytes.fromhex("A5 01 21 00 22"), bridge.command(0x22, bytes([0, power])), b"", b""]


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

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.power_config = pathlib.Path(temporary.name) / "antenna-power.json"
        patcher = mock.patch.object(bridge, "POWER_CONFIG_PATH", self.power_config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_status_requires_valid_reader_response(self):
        # Respuesta real capturada en Windows/COM5: A5 02 22 00 0A 2E.
        device = FakeSerial([bytes.fromhex("A5 02 22 00 0A 2E")])
        code, output, factory = self.invoke(["status"], device)
        self.assertEqual(code, 0)
        self.assertEqual(output.splitlines(), ["OK", "CONNECTED=1", "PORT=" + bridge.PORT,
                                              "BAUDRATE=" + str(bridge.BAUD),
                                              "TIMEOUT_MS=" + str(bridge.TIMEOUT_MS), "POWER=10"])
        self.assertEqual(device.writes, [bytes.fromhex("A5 00 22 22")])
        factory.assert_called_once()
        self.assertTrue(device.closed)

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
        device = FakeSerial(init_responses() + [inventory_frame(EPC)])
        code, output, _ = self.invoke(["read-epc"], device)
        self.assertEqual(code, 0)
        self.assertEqual(output, "DETECTED=" + EPC + "\n")
        self.assertIn(bytes.fromhex("A5 00 54 54"), device.writes)
        self.assertTrue(device.closed)

    def test_inventory_deduplicates_multiple_tags(self):
        other = "E28436110000100004210970"
        device = FakeSerial(init_responses() + [inventory_frame(EPC), inventory_frame(other) + inventory_frame(EPC)])
        with mock.patch.object(bridge.time, "monotonic", side_effect=[0] * 4 + [0, 0, 0, 2]):
            code, output, _ = self.invoke(["inventory"], device)
        self.assertEqual(code, 0)
        self.assertEqual(output.splitlines(), ["DETECTED=" + EPC, "DETECTED=" + other])
        self.assertTrue(device.closed)

    def test_fragmented_inventory_frame_is_preserved(self):
        frame = inventory_frame(EPC)
        device = FakeSerial(init_responses() + [frame[:10], frame[10:]])
        code, output, _ = self.invoke(["read-epc"], device)
        self.assertEqual((code, output), (0, "DETECTED=" + EPC + "\n"))
        self.assertTrue(device.closed)

    def test_inventory_error_stops_and_closes_reader(self):
        device = FakeSerial()
        with mock.patch.object(device, "read", side_effect=init_responses() + [b""] + [OSError("read failed"), b""]):
            code, output, _ = self.invoke(["inventory"], device)
        self.assertEqual((code, output), (1, "ERROR=SERIAL_ERROR:read failed\n"))
        self.assertEqual(device.writes[-1], bytes.fromhex("A5 00 54 54"))
        self.assertTrue(device.closed)

    def test_cleared_tag_is_detected_with_24_zeros(self):
        zeros = "0" * 24
        writer = FakeSerial(init_responses() + [bytes.fromhex("A5 01 57 00 58")])
        code, output, _ = self.invoke(["clear", "6"], writer)
        self.assertEqual((code, output), (0, "WRITTEN=" + zeros + "\nOK\n"))
        reader = FakeSerial(init_responses() + [inventory_frame(zeros)])
        code, output, _ = self.invoke(["read-epc"], reader)
        self.assertEqual((code, output), (0, "DETECTED=" + zeros + "\n"))
        self.assertTrue(writer.closed and reader.closed)

    def test_inventory_includes_cleared_and_written_tags(self):
        zeros = "0" * 24
        device = FakeSerial(init_responses() + [inventory_frame(zeros) + inventory_frame(EPC) + inventory_frame(zeros)])
        with mock.patch.object(bridge.time, "monotonic", side_effect=[0] * 4 + [0, 2]):
            code, output, _ = self.invoke(["inventory"], device)
        self.assertEqual(code, 0)
        self.assertEqual(output.splitlines(), ["DETECTED=" + zeros, "DETECTED=" + EPC])
        self.assertTrue(device.closed)

    def test_no_tag_is_a_normal_result(self):
        for action in ("read-epc", "inventory"):
            for response in (b"", bytes.fromhex("A5 00 53 53"), b"\x00" * 24):
                with self.subTest(action=action, response=response):
                    device = FakeSerial(init_responses() + [response])
                    with mock.patch.object(bridge.time, "monotonic", side_effect=[0] * 4 + [0, 2]):
                        code, output, _ = self.invoke([action], device)
                    self.assertEqual((code, output), (0, "NO_TAG\n"))

    def test_write_ack_returns_ok(self):
        # Se conserva el reconocimiento de ACK existente; validacion binaria completa pendiente.
        device = FakeSerial(init_responses() + [bytes.fromhex("A5 01 57 00 58")])
        code, output, _ = self.invoke(["write-epc", EPC], device)
        self.assertEqual((code, output), (0, "WRITTEN=" + EPC + "\nOK\n"))
        self.assertTrue(device.closed)

    def test_failed_write_returns_nonzero(self):
        device = FakeSerial(init_responses())
        code, output, _ = self.invoke(["write-epc", EPC], device)
        self.assertNotEqual(code, 0)
        self.assertIn("ERROR=WRITE_FAILED", output)
        self.assertNotIn("WRITTEN=", output)
        self.assertTrue(device.closed)

    def test_clear_respects_words(self):
        device = FakeSerial(init_responses() + [bytes.fromhex("A5 01 57 00 58")])
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

    def test_get_power_ignores_noise_other_commands_and_fragmentation(self):
        device = FakeSerial([b"noise" + bytes.fromhex("A5 01 21 00 22 A5 02"),
                             bytes.fromhex("22 00 0F 33")])
        code, output, _ = self.invoke(["get-power"], device)
        self.assertEqual((code, output), (0, "POWER=15\nOK\n"))
        self.assertEqual(device.writes, [bytes.fromhex("A5 00 22 22")])
        self.assertTrue(device.closed)

    def test_status_and_get_power_reject_invalid_responses(self):
        cases = [
            ("A5 02 22 00 0A 2F", "READER_CHECKSUM"),
            ("A5 01 22 03 26", "READER_STATUS_03"),
            ("A5 01 22 00 23", "READER_RESPONSE_INVALID"),
            ("A5 03 22 00 0A 00 2F", "READER_RESPONSE_INVALID"),
        ]
        for action in ("status", "get-power"):
            for raw, error in cases:
                with self.subTest(action=action, raw=raw):
                    device = FakeSerial([bytes.fromhex(raw)])
                    code, output, _ = self.invoke([action], device)
                    self.assertEqual((code, output), (1, "ERROR=" + error + "\n"))
                    self.assertNotIn("CONNECTED=1", output)
                    self.assertTrue(device.closed)

    def test_status_open_port_without_reply_is_not_connected(self):
        for response in (b"", b"noise", bytes.fromhex("A5 02 22"), bytes.fromhex("A5 01 21 00 22")):
            with self.subTest(response=response):
                device = FakeSerial([response])
                with mock.patch.object(bridge.time, "monotonic", side_effect=[0, 0, 2]):
                    code, output, _ = self.invoke(["status"], device)
                self.assertEqual((code, output), (1, "ERROR=READER_NOT_RESPONDING\n"))
                self.assertTrue(device.closed)

    def test_set_power_validates_ack_and_readback_without_initialization(self):
        # ACK real capturado al cambiar temporalmente COM5 de 10 a 9 y restaurar 10.
        device = FakeSerial([bytes.fromhex("A5 01 21 00 22"), bytes.fromhex("A5 02 22 00 0F 33")])
        code, output, _ = self.invoke(["set-power", "15"], device)
        self.assertEqual((code, output), (0, "POWER=15\nOK\n"))
        self.assertEqual(device.writes, [bytes.fromhex("A5 01 21 0F 31"), bytes.fromhex("A5 00 22 22")])
        self.assertTrue(device.closed)
        self.assertFalse(self.power_config.exists(), "CLI no debe persistir el ajuste")

    def test_set_power_limits_and_command_bytes(self):
        for value, command in [(5, "A5 01 21 05 27"), (30, "A5 01 21 1E 40")]:
            with self.subTest(value=value):
                device = FakeSerial([bytes.fromhex("A5 01 21 00 22"), bridge.command(0x22, bytes([0, value]))])
                code, output, _ = self.invoke(["set-power", str(value)], device)
                self.assertEqual((code, output), (0, "POWER=" + str(value) + "\nOK\n"))
                self.assertEqual(device.writes[0], bytes.fromhex(command))

    def test_invalid_power_never_opens_device(self):
        for args in [["set-power"], ["set-power", "4"], ["set-power", "31"], ["set-power", "-1"],
                     ["set-power", "5.5"], ["set-power", " 10"], ["set-power", "10x"], ["set-power", ""]]:
            with self.subTest(args=args):
                code, output, factory = self.invoke(args)
                self.assertEqual(code, 1)
                self.assertIn("ERROR=POWER_", output)
                factory.assert_not_called()

    def test_set_power_rejects_ack_errors(self):
        for raw, error in [("A5 01 21 02 24", "READER_STATUS_02"),
                           ("A5 01 21 00 23", "READER_CHECKSUM"),
                           ("A5 02 21 00 0A 2D", "READER_RESPONSE_INVALID")]:
            with self.subTest(raw=raw):
                device = FakeSerial([bytes.fromhex(raw)])
                code, output, _ = self.invoke(["set-power", "15"], device)
                self.assertEqual((code, output), (1, "ERROR=" + error + "\n"))
                self.assertEqual(len(device.writes), 1)
                self.assertTrue(device.closed)

    def test_set_power_rejects_readback_mismatch(self):
        device = FakeSerial([bytes.fromhex("A5 01 21 00 22"), bytes.fromhex("A5 02 22 00 0A 2E")])
        code, output, _ = self.invoke(["set-power", "15"], device)
        self.assertEqual((code, output), (1, "ERROR=POWER_READBACK_MISMATCH\n"))
        self.assertTrue(device.closed)

    def test_set_power_requires_reply_for_both_steps(self):
        for responses, times in [([], [0, 0, 2]),
                                 ([bytes.fromhex("A5 01 21 00 22")], [0, 0, 0, 0, 2])]:
            with self.subTest(responses=responses):
                device = FakeSerial(responses)
                with mock.patch.object(bridge.time, "monotonic", side_effect=times):
                    code, output, _ = self.invoke(["set-power", "15"], device)
                self.assertEqual((code, output), (1, "ERROR=READER_NOT_RESPONDING\n"))
                self.assertTrue(device.closed)

    def test_serial_read_error_closes_status_device(self):
        device = FakeSerial()
        with mock.patch.object(device, "read", side_effect=OSError("device removed")):
            code, output, _ = self.invoke(["status"], device)
        self.assertEqual((code, output), (1, "ERROR=SERIAL_ERROR:device removed\n"))
        self.assertTrue(device.closed)

    def test_disconnected_or_denied_port_fails_status(self):
        for error in (FileNotFoundError("missing port"), PermissionError("permission denied")):
            with self.subTest(error=error):
                output = io.StringIO()
                with mock.patch.object(bridge, "serial", types.SimpleNamespace(Serial=mock.Mock(side_effect=error))), \
                        contextlib.redirect_stdout(output):
                    code = bridge.main(["status"])
                self.assertEqual(code, 1)
                self.assertTrue(output.getvalue().startswith("ERROR=SERIAL_ERROR:"))
                self.assertNotIn("CONNECTED=1", output.getvalue())

    def test_saved_power_is_used_on_subsequent_read_and_write(self):
        self.power_config.write_text(json.dumps({"power": 15}), encoding="utf-8")
        for args, response in [(["read-epc"], inventory_frame(EPC)),
                               (["write-epc", EPC], bytes.fromhex("A5 01 57 00 58"))]:
            with self.subTest(args=args):
                device = FakeSerial(init_responses(15) + [response])
                code, output, _ = self.invoke(args, device)
                self.assertEqual(code, 0)
                self.assertEqual(device.writes[1], bytes.fromhex("A5 01 21 0F 31"))
                self.assertNotIn(bytes.fromhex("A5 01 21 0A 2C"), device.writes)

    def test_absent_power_override_keeps_existing_default(self):
        self.assertEqual(bridge.configured_power(), int(bridge.POWER_HEX, 16))
        device = FakeSerial(init_responses() + [inventory_frame(EPC)])
        self.invoke(["read-epc"], device)
        self.assertEqual(device.writes[1], bytes.fromhex("A5 01 21 0A 2C"))

    def test_invalid_saved_power_fails_before_opening_reader(self):
        for content in ['{"power":4}', '{"power":31}', '{"power":true}', '{"power":"10"}',
                        '{"power":10.5}', '{}', '[]', 'bad json']:
            with self.subTest(content=content):
                self.power_config.write_text(content, encoding="utf-8")
                code, output, factory = self.invoke(["read-epc"])
                self.assertEqual((code, output), (1, "ERROR=POWER_CONFIG_INVALID\n"))
                factory.assert_not_called()
        self.power_config.write_bytes(b"\xff")
        code, output, factory = self.invoke(["read-epc"])
        self.assertEqual((code, output), (1, "ERROR=POWER_CONFIG_INVALID\n"))
        factory.assert_not_called()

    def test_status_reports_actual_power_even_if_saved_config_is_invalid(self):
        self.power_config.write_text('invalid', encoding="utf-8")
        device = FakeSerial([bytes.fromhex("A5 02 22 00 0A 2E")])
        code, output, _ = self.invoke(["status"], device)
        self.assertEqual(code, 0)
        self.assertIn("POWER=10\n", output)

    def test_cli_set_power_does_not_overwrite_saved_config(self):
        self.power_config.write_text('{"power":15}', encoding="utf-8")
        device = FakeSerial([bytes.fromhex("A5 01 21 00 22"), bytes.fromhex("A5 02 22 00 0A 2E")])
        code, output, _ = self.invoke(["set-power", "10"], device)
        self.assertEqual(code, 0)
        self.assertEqual(self.power_config.read_text(encoding="utf-8"), '{"power":15}')

    def test_read_and_write_fail_when_saved_power_cannot_be_applied(self):
        self.power_config.write_text('{"power":15}', encoding="utf-8")
        for args in (["read-epc"], ["write-epc", EPC]):
            for responses, error in [([b"", bytes.fromhex("A5 01 21 02 24")], "READER_STATUS_02"),
                                     (init_responses(10), "POWER_READBACK_MISMATCH")]:
                with self.subTest(args=args, error=error):
                    device = FakeSerial(responses)
                    code, output, _ = self.invoke(args, device)
                    self.assertEqual((code, output), (1, "ERROR=" + error + "\n"))
                    self.assertNotIn(bytes.fromhex("A5 00 53 53"), device.writes)
                    self.assertNotIn(bridge.build_write_epc(EPC), device.writes)
                    self.assertTrue(device.closed)

    def test_read_power_accepts_actual_byte_outside_setter_range(self):
        for action in ("status", "get-power"):
            for power in (0, 4, 31, 255):
                with self.subTest(action=action, power=power):
                    device = FakeSerial([bridge.command(0x22, bytes([0, power]))])
                    code, output, _ = self.invoke([action], device)
                    self.assertEqual(code, 0)
                    self.assertIn("POWER=" + str(power) + "\n", output)
                    if action == "status":
                        self.assertIn("CONNECTED=1\n", output)
                    self.assertTrue(device.closed)


if __name__ == "__main__":
    unittest.main()
