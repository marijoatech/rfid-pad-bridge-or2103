import contextlib
import importlib.util
import io
import itertools
import json
import pathlib
import tempfile
import types
import unittest
from unittest import mock

PATH = pathlib.Path(__file__).resolve().parents[1] / "linux" / "OR2103Bridge.py"
spec = importlib.util.spec_from_file_location("rfid_under_test", PATH)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
EPC = "000000000000000001000027"
ZERO_FRAME = bytes.fromhex("A5 12 55 00 30 00 00 00 00 00 00 00 00 00 00 00 00 00 FD 97 01 2C")
ACK_START = bytes.fromhex("A5 01 53 00 54")
ACK_STOP = bytes.fromhex("A5 01 54 00 55")


def inventory_frame(epc, extra=b""):
    data = bytes.fromhex(epc)
    pc = (len(data) // 2 << 11).to_bytes(2, "big")
    return bytes(bridge.command(0x55, b"\x00" + pc + data + extra + bytes.fromhex("FD 97 01")))


class FakeSerial:
    """Activa respuestas solo cuando se envia su comando, como el pad real."""
    def __init__(self, power=10, replies=None):
        self.power = power
        self.replies = replies or {}
        self.pending = []
        self.writes = []
        self.closed = False
        self.resets_after_start = 0
        self.sound_mode = 3
        self.inventory_sound = []

    def write(self, data):
        data = bytes(data)
        self.writes.append(data)
        cmd = data[2]
        if cmd == 0x21:
            self.power = data[3]
        if cmd == 0x13:
            self.sound_mode = data[3]
        if cmd == 0x53:
            self.inventory_sound.append(self.sound_mode)
        if cmd in self.replies:
            chunks = self.replies[cmd]
            if callable(chunks):
                chunks = chunks()
        elif cmd == 0x22:
            chunks = [bridge.command(0x22, bytes([0, self.power]))]
        elif cmd == 0x14:
            chunks = [bridge.command(0x14, bytes([0, self.sound_mode]))]
        else:
            chunks = [bridge.command(cmd, b"\x00")]
        self.pending.extend(chunks)

    def read(self, size):
        chunk = self.pending.pop(0) if self.pending else b""
        if isinstance(chunk, Exception):
            raise chunk
        # Respeta read(size), incluso cuando se generan muchos datos.
        if len(chunk) > size:
            self.pending.insert(0, chunk[size:])
            chunk = chunk[:size]
        return bytes(chunk)

    def reset_input_buffer(self):
        if any(frame[2] == 0x53 for frame in self.writes):
            self.resets_after_start += 1
        self.pending.clear()

    def close(self):
        self.closed = True


class BridgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.power_config = pathlib.Path(temporary.name) / "antenna-power.json"
        patcher = mock.patch.object(bridge, "POWER_CONFIG_PATH", self.power_config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def invoke(self, args, device=None):
        device = FakeSerial() if device is None else device
        factory = mock.Mock(return_value=device)
        output, diagnostics = io.StringIO(), io.StringIO()
        ticks = itertools.count()
        with mock.patch.object(bridge, "serial", types.SimpleNamespace(Serial=factory)), \
                mock.patch.object(bridge.time, "sleep"), \
                mock.patch.object(bridge.time, "monotonic", side_effect=lambda: next(ticks) * .05), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
            code = bridge.main(args)
        self.last_stderr = diagnostics.getvalue()
        return code, output.getvalue(), factory

    def test_status_requires_power_reply_and_has_no_configuration_commands(self):
        device = FakeSerial(power=9)
        code, output, _ = self.invoke(["status"], device)
        self.assertEqual(code, 0)
        self.assertEqual(output.splitlines(), ["OK", "CONNECTED=1", "PORT=" + bridge.PORT,
                                              "BAUDRATE=" + str(bridge.BAUD),
                                              "TIMEOUT_MS=" + str(bridge.TIMEOUT_MS), "POWER=9"])
        self.assertEqual(device.writes, [bytes.fromhex("A5 00 22 22")])
        self.assertTrue(device.closed)

    def test_power_response_fragmentation_and_noise(self):
        response = bytes.fromhex("A5 02 22 00 0A 2E")
        device = FakeSerial(replies={0x22: [b"noise" + response[:2], response[2:4], response[4:]]})
        self.assertEqual(self.invoke(["get-power"], device)[:2], (0, "POWER=10\nOK\n"))
        self.assertEqual(self.last_stderr, "")

    def test_get_power_accepts_actual_values_outside_setter_limits(self):
        for power in (0, 4, 31, 255):
            with self.subTest(power=power):
                self.assertEqual(self.invoke(["get-power"], FakeSerial(power=power))[:2],
                                 (0, "POWER=" + str(power) + "\nOK\n"))

    def test_control_reply_inside_fragmented_epc_is_never_accepted(self):
        frame = inventory_frame("A50222000A2E000000000000")
        device = FakeSerial(replies={0x22: [frame[:12], frame[12:]]})
        self.assertEqual(self.invoke(["get-power"], device)[:2], (1, "ERROR=READER_NOT_RESPONDING\n"))
        self.assertEqual(self.last_stderr, "RFID_DIAG CMD=22 RX_BYTES=22 TAG_FRAMES=1\n")

    def test_control_rejects_bad_checksum_status_and_length(self):
        for response, error in [("A50222000A2F", "READER_CHECKSUM"),
                                ("A501220326", "READER_STATUS_03"),
                                ("A501220023", "READER_RESPONSE_INVALID")]:
            with self.subTest(response=response):
                device = FakeSerial(replies={0x22: [bytes.fromhex(response)]})
                self.assertEqual(self.invoke(["get-power"], device)[:2], (1, "ERROR=" + error + "\n"))
                self.assertTrue(device.closed)

    def test_control_diagnostics_have_counts_and_never_raw_data(self):
        secret = b"secret-sentinel-epc"
        device = FakeSerial(replies={0x22: [secret * 40]})
        self.assertEqual(self.invoke(["get-power"], device)[:2], (1, "ERROR=READER_NOT_RESPONDING\n"))
        self.assertEqual(self.last_stderr, "RFID_DIAG CMD=22 RX_BYTES=760 TAG_FRAMES=0\n")
        self.assertNotIn(secret.decode(), self.last_stderr)
        self.assertNotIn(secret.hex().upper(), self.last_stderr)
        self.assertLess(len(self.last_stderr), 100)

    def test_status_open_port_without_reply_is_not_connected(self):
        device = FakeSerial(replies={0x22: []})
        self.assertEqual(self.invoke(["status"], device)[:2], (1, "ERROR=READER_NOT_RESPONDING\n"))
        self.assertEqual(self.last_stderr, "RFID_DIAG CMD=22 RX_BYTES=0 TAG_FRAMES=0\n")
        self.assertTrue(device.closed)

    def test_serial_failure_and_permission_error_are_reported(self):
        device = FakeSerial(replies={0x22: [OSError("device removed")]})
        self.assertEqual(self.invoke(["status"], device)[:2], (1, "ERROR=SERIAL_ERROR:device removed\n"))
        self.assertTrue(device.closed)
        output = io.StringIO()
        with mock.patch.object(bridge, "serial", types.SimpleNamespace(Serial=mock.Mock(side_effect=PermissionError("denied")))), \
                contextlib.redirect_stdout(output):
            self.assertEqual(bridge.main(["status"]), 1)
        self.assertEqual(output.getvalue(), "ERROR=SERIAL_ERROR:denied\n")

    def test_set_power_ack_and_readback_golden_bytes(self):
        for power, expected in [(5, "A501210527"), (15, "A501210F31"), (30, "A501211E40")]:
            with self.subTest(power=power):
                device = FakeSerial()
                self.assertEqual(self.invoke(["set-power", str(power)], device)[:2],
                                 (0, "POWER=" + str(power) + "\nOK\n"))
                self.assertEqual(device.writes, [bytes.fromhex(expected), bytes.fromhex("A5002222")])
                self.assertTrue(device.closed)
                self.assertFalse(self.power_config.exists())

    def test_set_power_ack_failure_does_not_confirm(self):
        device = FakeSerial(replies={0x21: [bytes.fromhex("A501210224")]})
        self.assertEqual(self.invoke(["set-power", "15"], device)[:2], (1, "ERROR=READER_STATUS_02\n"))
        self.assertEqual(len(device.writes), 1)
        self.assertIn("CMD=21", self.last_stderr)

    def test_set_power_requires_matching_readback(self):
        device = FakeSerial(replies={0x22: [bytes.fromhex("A50222000A2E")]})
        self.assertEqual(self.invoke(["set-power", "15"], device)[:2], (1, "ERROR=POWER_READBACK_MISMATCH\n"))
        self.assertTrue(device.closed)

    def test_set_power_timeouts_identify_stage(self):
        for failed_cmd in (0x21, 0x22):
            with self.subTest(cmd=failed_cmd):
                self.assertEqual(self.invoke(["set-power", "15"], FakeSerial(replies={failed_cmd: []}))[:2],
                                 (1, "ERROR=READER_NOT_RESPONDING\n"))
                self.assertIn("CMD=" + format(failed_cmd, "02X"), self.last_stderr)

    def test_invalid_actions_parameters_never_open_reader(self):
        for args in [[], ["missing"], ["version"], ["write-epc"], ["write-epc", "----"],
                     ["write-epc", "1000027"], ["write-epc", "A" * 128], ["clear", "32"], ["clear", "0"],
                     ["set-power"], ["set-power", "4"], ["set-power", "31"], ["set-power", "10.5"],
                     ["set-power", " 10"], ["set-power", "10x"]]:
            with self.subTest(args=args):
                code, output, factory = self.invoke(args)
                self.assertEqual(code, 1)
                self.assertTrue(output.startswith("ERROR="))
                factory.assert_not_called()

    def test_real_cleared_tag_frame_has_correct_pc_length_and_checksum(self):
        self.assertEqual(inventory_frame("0" * 24), ZERO_FRAME)
        self.assertEqual(len(ZERO_FRAME), 22)
        self.assertEqual(bridge.parse_epcs(ZERO_FRAME), ["0" * 24])

    def test_incomplete_tag_never_appears_before_checksum(self):
        for end in range(len(ZERO_FRAME)):
            with self.subTest(end=end):
                self.assertEqual(bridge.parse_epcs(ZERO_FRAME[:end]), [])

    def test_tag_bad_checksum_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "READER_CHECKSUM"):
            bridge.parse_epcs(ZERO_FRAME[:-1] + b"\x2D")

    def test_tag_pc_controls_length_instead_of_fixed_24_characters(self):
        for words in (1, 5, 6, 7, 31):
            epc = bytes(range(1, words * 2 + 1)).hex().upper()
            with self.subTest(words=words):
                self.assertEqual(bridge.parse_epcs(inventory_frame(epc)), [epc])

    def test_tag_optional_data_is_not_included_in_epc(self):
        self.assertEqual(bridge.parse_epcs(inventory_frame(EPC, bytes.fromhex("ABCD") * 6)), [EPC])

    def test_tag_invalid_status_or_pc_is_rejected(self):
        for data, error in [(b"\x03", "READER_STATUS_03"), (b"\x03" + ZERO_FRAME[4:-1], "READER_STATUS_03"),
                            (b"\x00\x00\x00" + ZERO_FRAME[6:-1], "READER_RESPONSE_INVALID"),
                            (b"\x00\x38\x00" + ZERO_FRAME[6:-1], "READER_RESPONSE_INVALID")]:
            with self.subTest(error=error):
                with self.assertRaisesRegex(ValueError, error):
                    bridge.parse_epcs(bridge.command(0x55, data))

    def test_inventory_preserves_tags_with_start_ack_in_same_read(self):
        device = FakeSerial(replies={0x53: [ACK_START + inventory_frame(EPC)]})
        self.assertEqual(self.invoke(["read-epc"], device)[:2], (0, "DETECTED=" + EPC + "\n"))
        self.assertEqual(device.resets_after_start, 0)
        self.assertTrue(device.closed)
        self.assertEqual(self.last_stderr, "")

    def test_inventory_preserves_tag_before_start_ack(self):
        device = FakeSerial(replies={0x53: [ZERO_FRAME + ACK_START]})
        self.assertEqual(self.invoke(["read-epc"], device)[:2], (0, "DETECTED=" + "0" * 24 + "\n"))

    def test_inventory_preserves_fragmented_headers_pc_and_checksums(self):
        raw = ACK_START + ZERO_FRAME
        device = FakeSerial(replies={0x53: [bytes([byte]) for byte in raw],
                                     0x54: [ACK_STOP[:2], ACK_STOP[2:]]})
        self.assertEqual(self.invoke(["read-epc"], device)[:2], (0, "DETECTED=" + "0" * 24 + "\n"))
        self.assertTrue(device.closed)

    def test_inventory_deduplicates_cleared_and_nonzero_tags(self):
        device = FakeSerial(replies={0x53: [ACK_START + ZERO_FRAME + inventory_frame(EPC) + ZERO_FRAME]})
        self.assertEqual(self.invoke(["inventory"], device)[:2],
                         (0, "DETECTED=" + "0" * 24 + "\nDETECTED=" + EPC + "\n"))

    def test_stop_wait_preserves_pending_tags_and_coalesced_ack(self):
        device = FakeSerial(replies={0x54: [ZERO_FRAME + inventory_frame(EPC) + ACK_STOP]})
        self.assertEqual(self.invoke(["inventory"], device)[:2],
                         (0, "DETECTED=" + "0" * 24 + "\nDETECTED=" + EPC + "\n"))

    def test_no_tag_requires_both_start_and_stop_acks(self):
        for action in ("read-epc", "inventory"):
            device = FakeSerial()
            self.assertEqual(self.invoke([action], device)[:2], (0, "NO_TAG\n"))
            self.assertIn(bytes.fromhex("A5005353"), device.writes)
            self.assertIn(bytes.fromhex("A5005454"), device.writes)
            self.assertTrue(device.closed)

    def test_start_timeout_despite_tag_still_attempts_stop_and_reports_error(self):
        device = FakeSerial(replies={0x53: [ZERO_FRAME]})
        self.assertEqual(self.invoke(["inventory"], device)[:2], (1, "ERROR=READER_NOT_RESPONDING\n"))
        self.assertIn(bytes.fromhex("A5005454"), device.writes)
        self.assertIn("CMD=53", self.last_stderr)
        self.assertTrue(device.closed)

    def test_rejected_start_still_attempts_stop(self):
        device = FakeSerial(replies={0x53: [bridge.command(0x53, b"\x01")]})
        self.assertEqual(self.invoke(["inventory"], device)[:2], (1, "ERROR=READER_STATUS_01\n"))
        self.assertEqual(device.writes[-1], bytes.fromhex("A5005454"))
        self.assertTrue(device.closed)

    def test_stop_timeout_never_emits_detected_or_no_tag(self):
        for start in ([ACK_START], [ACK_START + ZERO_FRAME]):
            device = FakeSerial(replies={0x53: start, 0x54: []})
            self.assertEqual(self.invoke(["read-epc"], device)[:2], (1, "ERROR=READER_NOT_RESPONDING\n"))
            self.assertIn("CMD=54", self.last_stderr)
            self.assertNotIn(bytes.fromhex("A5001919"), device.writes)
            self.assertTrue(device.closed)

    def test_stop_rejection_and_checksum_failure_never_emit_success(self):
        for ack, error in [(bridge.command(0x54, b"\x01"), "READER_STATUS_01"),
                           (ACK_STOP[:-1] + b"\x56", "READER_CHECKSUM")]:
            device = FakeSerial(replies={0x53: [ACK_START + ZERO_FRAME], 0x54: [ack]})
            self.assertEqual(self.invoke(["read-epc"], device)[:2], (1, "ERROR=" + error + "\n"))
            self.assertIn("CMD=54", self.last_stderr)

    def test_corrupt_tag_or_read_failure_attempts_stop_and_reports_error(self):
        for response, error in [(ZERO_FRAME[:-1] + b"\x2D", "READER_CHECKSUM"),
                                (OSError("read failed"), "SERIAL_ERROR:read failed")]:
            device = FakeSerial(replies={0x53: [ACK_START, response]})
            self.assertEqual(self.invoke(["inventory"], device)[:2], (1, "ERROR=" + error + "\n"))
            self.assertEqual(device.writes[-1], bytes.fromhex("A5005454"))
            self.assertTrue(device.closed)

    def test_control_patterns_inside_epc_do_not_become_inventory_acks(self):
        epc = "A501530054A501540055000000"
        device = FakeSerial(replies={0x53: [inventory_frame(epc)[:11], inventory_frame(epc)[11:]]})
        self.assertEqual(self.invoke(["inventory"], device)[:2], (1, "ERROR=READER_NOT_RESPONDING\n"))
        self.assertIn("CMD=53", self.last_stderr)

    def test_init_does_not_configure_buzzer_or_hid_area(self):
        for args in (["read-epc"], ["inventory"], ["write-epc", EPC], ["clear", "6"]):
            device = FakeSerial(replies={0x53: [ACK_START + ZERO_FRAME]})
            self.assertEqual(self.invoke(args, device)[0], 0)
            self.assertFalse({0x13, 0x43, 0x51}.intersection(frame[2] for frame in device.writes))
            self.assertEqual([frame[2] for frame in device.writes[:3]], [0x32, 0x21, 0x22])

    def test_write_packet_and_output_are_unchanged(self):
        expected = bytes.fromhex("A5 15 57 00000000 01 01 07 3000 " + EPC + "CD")
        self.assertEqual(bridge.build_write_epc(EPC), expected)
        device = FakeSerial()
        self.assertEqual(self.invoke(["write-epc", EPC], device)[:2], (0, "WRITTEN=" + EPC + "\nOK\n"))
        self.assertIn(expected, device.writes)

    def test_failed_write_returns_no_written_marker(self):
        device = FakeSerial(replies={0x57: []})
        code, output, _ = self.invoke(["write-epc", EPC], device)
        self.assertEqual(code, 1)
        self.assertIn("ERROR=WRITE_FAILED", output)
        self.assertNotIn("WRITTEN=", output)
        self.assertTrue(device.closed)

    def test_clear_respects_words(self):
        for words in (6, 10):
            zeros = "0" * (words * 4)
            self.assertEqual(self.invoke(["clear", str(words)])[:2], (0, "WRITTEN=" + zeros + "\nOK\n"))

    def test_saved_power_applies_to_read_and_write(self):
        self.power_config.write_text('{"power":15}', encoding="utf-8")
        for args in (["read-epc"], ["write-epc", EPC]):
            device = FakeSerial()
            self.assertEqual(self.invoke(args, device)[0], 0)
            self.assertIn(bytes.fromhex("A501210F31"), device.writes)
            self.assertEqual(device.power, 15)

    def test_invalid_saved_power_fails_before_open(self):
        for content in ['{"power":4}', '{"power":31}', '{"power":true}', '{"power":"10"}',
                        '{"power":10.5}', '{}', '[]', 'bad json']:
            self.power_config.write_text(content, encoding="utf-8")
            code, output, factory = self.invoke(["read-epc"])
            self.assertEqual((code, output), (1, "ERROR=POWER_CONFIG_INVALID\n"))
            factory.assert_not_called()

    def test_power_apply_failure_stops_before_tag_operation(self):
        device = FakeSerial(replies={0x21: [bridge.command(0x21, b"\x02")]})
        self.assertEqual(self.invoke(["read-epc"], device)[:2], (1, "ERROR=READER_STATUS_02\n"))
        self.assertNotIn(bytes.fromhex("A5005353"), device.writes)
        self.assertTrue(device.closed)

    def test_status_ignores_bad_saved_config_and_cli_set_does_not_persist(self):
        self.power_config.write_text('invalid', encoding="utf-8")
        self.assertEqual(self.invoke(["status"])[0], 0)
        self.assertEqual(self.invoke(["set-power", "15"])[0], 0)
        self.assertEqual(self.power_config.read_text(encoding="utf-8"), 'invalid')

    def test_partial_inventory_tag_is_preserved_across_start_ack_boundary(self):
        device = FakeSerial(replies={0x53: [ACK_START + ZERO_FRAME[:10], ZERO_FRAME[10:]]})
        self.assertEqual(self.invoke(["read-epc"], device)[:2], (0, "DETECTED=" + "0" * 24 + "\n"))
        self.assertTrue(device.closed)

    def test_invalid_saved_utf8_fails_before_open(self):
        self.power_config.write_bytes(b"\xff")
        code, output, factory = self.invoke(["read-epc"])
        self.assertEqual((code, output), (1, "ERROR=POWER_CONFIG_INVALID\n"))
        factory.assert_not_called()

    def test_read_sound_defaults_on_and_can_be_selected_explicitly(self):
        for args, expected_sound in [(["read-epc"], True), (["read-epc", "1"], True), (["read-epc", "0"], False)]:
            with self.subTest(args=args):
                device = FakeSerial(replies={0x53: [ACK_START + ZERO_FRAME]})
                code, output, _ = self.invoke(args, device)
                self.assertEqual((code, output), (0, "DETECTED=" + "0" * 24 + "\n"))
                self.assertEqual(bytes.fromhex("A5 00 19 19") in device.writes, expected_sound)

    def test_read_sound_rejects_invalid_values_before_opening_reader(self):
        for args in (["read-epc", "2"], ["read-epc", "false"], ["read-epc", "0", "1"]):
            with self.subTest(args=args):
                code, output, factory = self.invoke(args)
                self.assertEqual((code, output), (1, "ERROR=SOUND_INVALID\n"))
                factory.assert_not_called()

    def test_silent_read_preserves_light_and_restores_buzzer(self):
        for state in range(4):
            with self.subTest(state=state):
                device = FakeSerial(replies={0x53: [ACK_START + ZERO_FRAME]})
                device.sound_mode = state
                code, output, _ = self.invoke(['read-epc', '0'], device)
                self.assertEqual(code, 0, output)
                self.assertEqual(device.inventory_sound, [state & 1])
                self.assertEqual(device.sound_mode, state)
                self.assertEqual([f[3] for f in device.writes if f[2] == 0x13],
                                 [state & 1, state] if state & 2 else [])
                self.assertEqual(device.writes[0], bytes.fromhex('A5005454'))
                self.assertFalse(any(f[2] == 0x19 for f in device.writes))
                self.assertTrue(device.closed)

    def test_silent_read_requires_valid_sound_state_before_inventory(self):
        for reply in [[], [bytes.fromhex('A50214000318')],
                      [bridge.command(0x14, b'\x01\x03')],
                      [bridge.command(0x14, b'\x00\x04')],
                      [bridge.command(0x14, b'\x00')]]:
            with self.subTest(reply=reply):
                device = FakeSerial(replies={0x14: reply})
                self.assertEqual(self.invoke(['read-epc','0'], device)[0], 1)
                self.assertFalse(any(f[2] in (0x13, 0x53) for f in device.writes))
                self.assertTrue(device.closed)

    def test_silent_read_restores_when_mute_ack_lost(self):
        calls = itertools.count()
        device = FakeSerial(replies={0x13: lambda: [] if next(calls) == 0 else [bridge.command(0x13, b'\x00')]})
        self.assertEqual(self.invoke(['read-epc','0'], device)[0], 1)
        self.assertFalse(any(f[2] == 0x53 for f in device.writes))
        self.assertEqual(device.sound_mode, 3)

    def test_silent_read_does_not_read_if_setting_does_not_match(self):
        device = FakeSerial(replies={0x14: [bridge.command(0x14, b'\x00\x03')]})
        self.assertEqual(self.invoke(['read-epc','0'], device)[:2], (1, 'ERROR=SOUND_VERIFY_FAILED\n'))
        self.assertFalse(any(f[2] == 0x53 for f in device.writes))
        self.assertEqual(device.sound_mode, 3)

    def test_silent_read_restores_after_no_tag_or_failed_inventory(self):
        for reply in [[ACK_START], [], [bridge.command(0x53, b'\x01')]]:
            with self.subTest(reply=reply):
                device = FakeSerial(replies={0x53: reply})
                self.invoke(['read-epc','0'], device)
                self.assertEqual([f[3] for f in device.writes if f[2] == 0x13], [1, 3])
                self.assertTrue(device.closed)

    def test_silent_read_reports_restore_failure_instead_of_epc(self):
        calls = itertools.count()
        device = FakeSerial(replies={0x13: lambda: [bridge.command(0x13,b'\x00')] if next(calls) == 0 else [],
                                     0x53: [ACK_START + ZERO_FRAME]})
        self.assertEqual(self.invoke(['read-epc','0'], device)[:2], (1, 'ERROR=SOUND_RESTORE_FAILED\n'))

    def test_normal_reads_do_not_configure_automatic_buzzer(self):
        for args in [['read-epc'], ['read-epc','1'], ['inventory'], ['status']]:
            device = FakeSerial()
            self.assertEqual(self.invoke(args, device)[0], 0)
            self.assertFalse(any(f[2] in (0x13, 0x14) for f in device.writes))

    def test_saved_power_mismatch_prevents_inventory(self):
        self.power_config.write_text('{"power":15}', encoding="utf-8")
        device = FakeSerial(replies={0x22: [bytes.fromhex("A50222000A2E")]})
        self.assertEqual(self.invoke(["read-epc"], device)[:2], (1, "ERROR=POWER_READBACK_MISMATCH\n"))
        self.assertNotIn(bytes.fromhex("A5005353"), device.writes)
        self.assertTrue(device.closed)

    def test_clear_verified_succeeds_with_one_write_and_independent_read(self):
        calls = itertools.count()
        device = FakeSerial(replies={0x53: lambda: [ACK_START + inventory_frame(EPC if next(calls) == 0 else "0" * 24)]})
        code, output, _ = self.invoke(["clear-verified", EPC], device)
        self.assertEqual((code, output.splitlines()), (0, ["ORIGINAL=" + EPC, "ATTEMPTED=1",
            "WRITTEN=" + "0" * 24, "VERIFIED=" + "0" * 24, "OK"]))
        self.assertEqual(sum(command[2] == 0x57 for command in device.writes), 1)
        self.assertEqual(sum(command[2] == 0x53 for command in device.writes), 2)

    def test_clear_verified_blocks_no_tag_multiple_and_changed_without_write(self):
        cases = [([], "NO_TAG"), ([EPC, "0" * 24], "ERROR=MULTIPLE_TAGS"),
                 (["000000000000000001000028"], "ERROR=TAG_CHANGED"),
                 (["0" * 24], "ERROR=TAG_CHANGED")]
        for epcs, expected in cases:
            with self.subTest(epcs=epcs):
                device = FakeSerial(replies={0x53: [ACK_START + b"".join(inventory_frame(epc) for epc in epcs)]})
                code, output, _ = self.invoke(["clear-verified", EPC], device)
                self.assertEqual((code, output.strip()), (1, expected))
                self.assertFalse(any(command[2] == 0x57 for command in device.writes))

    def test_clear_verified_write_error_is_not_retried(self):
        device = FakeSerial(replies={0x53: [ACK_START + inventory_frame(EPC)],
                                     0x57: [bridge.command(0x57, b"\x03")]})
        code, output, _ = self.invoke(["clear-verified", EPC], device)
        self.assertEqual((code, output.splitlines()), (1, ["ORIGINAL=" + EPC, "ATTEMPTED=1", "ERROR=WRITE_FAILED"]))
        self.assertEqual(sum(command[2] == 0x57 for command in device.writes), 1)

    def test_clear_verified_requires_exact_readback(self):
        for after, failure in [([], "VERIFY_NO_TAG"), ([EPC], "VERIFY_MISMATCH"),
                               (["0" * 24, EPC], "VERIFY_MULTIPLE_TAGS")]:
            with self.subTest(after=after):
                calls = itertools.count()
                device = FakeSerial(replies={0x53: lambda: [ACK_START + b"".join(
                    inventory_frame(epc) for epc in ([EPC] if next(calls) == 0 else after))]})
                code, output, _ = self.invoke(["clear-verified", EPC], device)
                self.assertEqual(code, 1)
                self.assertEqual(output.splitlines()[-1], "ERROR=" + failure)
                self.assertEqual(sum(command[2] == 0x57 for command in device.writes), 1)


if __name__ == "__main__":
    unittest.main()
