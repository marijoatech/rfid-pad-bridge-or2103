"""Compile the actual Windows bridge against a fake SDK; never open a COM port."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'windows' / 'OR2103Bridge.cs'
if not SOURCE.exists():
    SOURCE = Path(__file__).with_name('OR2103Bridge.cs')
CSC = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if not CSC.exists():
    CSC = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework/v4.0.30319/csc.exe'

FAKE_SDK = r'''
using System;
namespace OR2127LIB {
    public class TagInfo { public string EPC; }
    public class ReaderManager {
        public event Action<TagInfo> InventoryTag;
        private bool wasSet;
        private int requested;
        private static string Value(string name, string fallback) { return Environment.GetEnvironmentVariable(name) ?? fallback; }
        private static void Log(string message) { Console.Error.WriteLine("CALL=" + message); }
        public bool ConSerialPort(string com, int baud, out string msg) { Log("Connect:" + com + ":" + baud); msg="fake"; return Value("FAKE_CONNECT", "1") == "1"; }
        public void DisCon() { Log("DisCon"); }
        public int GetPower(out string msg) {
            Log("GetPower"); msg="";
            return int.Parse(Value(wasSet ? "FAKE_AFTER_POWER" : "FAKE_POWER", wasSet ? requested.ToString() : "17"));
        }
        public bool SetPower(int power, out string msg) { Log("SetPower:" + power); msg="fake"; wasSet=true; requested=power; return Value("FAKE_SET", "1") == "1"; }
        public void StopInventory() { Log("StopInventory"); }
        public bool SetReadArea(int a,int b,int c,out string msg) { Log("SetReadArea"); msg=""; return true; }
        public bool SetLedBuzzer(int mode,out string msg) { Log("SetLedBuzzer:"+mode); msg=""; return true; }
        public bool GetVersion(out string version) { version="V1.2.3"; return true; }
        public bool Inventory(out string msg) { Log("Inventory"); msg=""; if (InventoryTag != null) InventoryTag(new TagInfo { EPC=Value("FAKE_TAG", "000000000000000001000028") }); return true; }
        public bool WriteTag(string pwd,int bank,int start,int words,string data,out string msg) { Log("WriteTag:"+data); msg=""; return true; }
    }
}
'''

@unittest.skipUnless(os.name == 'nt' and CSC.exists(), 'requires Windows .NET Framework C# compiler')
class WindowsBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='rfid-windows-tests-')
        cls.base = Path(cls.temp.name)
        cls.windows = cls.base / 'windows'
        cls.windows.mkdir()
        (cls.base / 'config.json').write_text('{"linux":{"power":6},"windows":{"com":"COM29","baudrate":57600,"timeout_ms":100,"power":12}}')
        cls.exe = cls.windows / 'OR2103Bridge.exe'
        fake = cls.base / 'FakeSdk.cs'
        fake.write_text(FAKE_SDK, encoding='utf-8')
        built = subprocess.run([str(CSC), '/nologo', '/target:exe', '/out:' + str(cls.exe), str(SOURCE), str(fake)], capture_output=True, text=True)
        if built.returncode:
            raise AssertionError(built.stdout + built.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.runtime = self.base / 'runtime'
        self.runtime.mkdir(exist_ok=True)
        self.saved = self.runtime / 'antenna-power.json'
        if self.saved.exists():
            self.saved.unlink()

    def run_bridge(self, *args, **values):
        env = os.environ.copy()
        for name in list(env):
            if name.startswith('FAKE_') or name == 'RFID_POWER':
                del env[name]
        env.update(values)
        return subprocess.run([str(self.exe), *args], capture_output=True, text=True, env=env, timeout=10, cwd=self.base)

    def test_status_requires_reply_without_changing_reader(self):
        r = self.run_bridge('status')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn('CONNECTED=1', r.stdout)
        self.assertIn('POWER=17', r.stdout)
        self.assertIn('CALL=GetPower', r.stderr)
        for forbidden in ['SetPower', 'SetReadArea', 'SetLedBuzzer', 'Inventory']:
            self.assertNotIn(forbidden, r.stderr)
        self.assertIn('CALL=DisCon', r.stderr)

    def test_status_does_not_accept_open_port_without_reader_reply(self):
        r = self.run_bridge('status', FAKE_POWER='-1')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), 'ERROR=READER_NOT_RESPONDING')

    def test_status_port_unavailable(self):
        r = self.run_bridge('status', FAKE_CONNECT='0')
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(r.stdout.startswith('ERROR=CONNECT_FAILED'))
        self.assertNotIn('CALL=GetPower', r.stderr)

    def test_status_can_report_device_power_outside_set_input_range(self):
        for power in ['0', '40', '255']:
            with self.subTest(power=power):
                r = self.run_bridge('status', FAKE_POWER=power)
                self.assertEqual(r.returncode, 0)
                self.assertIn('POWER=' + power, r.stdout)

    def test_get_power_is_actual(self):
        r = self.run_bridge('get-power', FAKE_POWER='23')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.splitlines(), ['POWER=23', 'OK'])
        self.assertNotIn('SetPower', r.stderr)

    def test_set_power_checks_readback(self):
        r = self.run_bridge('set-power', '18')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.splitlines(), ['POWER=18', 'OK'])
        self.assertIn('CALL=SetPower:18', r.stderr)
        self.assertIn('CALL=GetPower', r.stderr)
        self.assertNotIn('SetPower:10', r.stderr)

    def test_set_power_accepts_bridge_range_boundaries(self):
        for power in ['5', '30']:
            with self.subTest(power=power):
                r = self.run_bridge('set-power', power)
                self.assertEqual(r.returncode, 0, r.stdout)
                self.assertEqual(r.stdout.splitlines(), ['POWER=' + power, 'OK'])

    def test_set_power_rejects_missing_reply_and_mismatch(self):
        for value in ['-1', '16']:
            with self.subTest(value=value):
                r = self.run_bridge('set-power', '18', FAKE_AFTER_POWER=value)
                self.assertNotEqual(r.returncode, 0)
                self.assertTrue(r.stdout.startswith('ERROR='))
                self.assertNotIn('OK', r.stdout)
                self.assertNotIn('POWER=', r.stdout)

    def test_set_power_rejects_negative_ack(self):
        r = self.run_bridge('set-power', '18', FAKE_SET='0')
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(r.stdout.startswith('ERROR=POWER_SET_FAILED'))

    def test_invalid_actions_and_power_never_open_port(self):
        for args in [('bogus',), ('set-power',), ('set-power','4'), ('set-power','31'), ('set-power','256'), ('set-power','10.5'), ('set-power','abc'), ('set-power','-1'), ('set-power','10\n')]:
            with self.subTest(args=args):
                r = self.run_bridge(*args)
                self.assertNotEqual(r.returncode, 0)
                self.assertNotIn('CALL=Connect', r.stderr)

    def test_config_from_project_root_uses_only_windows_section(self):
        r = self.run_bridge('status')
        self.assertEqual(r.returncode, 0)
        self.assertIn('COM=COM29', r.stdout)
        self.assertIn('BAUDRATE=57600', r.stdout)
        self.assertIn('TIMEOUT_MS=100', r.stdout)
        self.assertIn('CALL=Connect:COM29:57600', r.stderr)
        r = self.run_bridge('read-epc')
        self.assertIn('CALL=SetPower:12', r.stderr)
        self.assertNotIn('CALL=SetPower:6', r.stderr)

    def test_missing_config_and_runtime_keep_existing_default_power(self):
        config = self.base / 'config.json'
        previous = config.read_text()
        try:
            config.unlink()
            r = self.run_bridge('read-epc')
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn('CALL=SetPower:10', r.stderr)
        finally:
            config.write_text(previous)

    def test_runtime_power_persists_into_next_read_without_changing_status_report(self):
        self.saved.write_text('{"power":19}')
        r = self.run_bridge('read-epc')
        self.assertEqual(r.returncode, 0)
        self.assertIn('CALL=SetPower:19', r.stderr)
        self.assertNotIn('CALL=SetPower:12', r.stderr)
        r = self.run_bridge('status', FAKE_POWER='17')
        self.assertEqual(r.returncode, 0)
        self.assertIn('POWER=17', r.stdout)
        self.assertNotIn('SetPower', r.stderr)

    def test_runtime_invalid_power_fails_before_open_port(self):
        for saved in ['{}', '{"power":4}', '{"power":31}', '{"power":"12"}', '{"power":12.5}', '{"power":05}', '{"power":12,"power":14}', 'broken']:
            with self.subTest(saved=saved):
                self.saved.write_text(saved)
                r = self.run_bridge('read-epc')
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(r.stdout.strip(), 'ERROR=POWER_CONFIG_INVALID')
                self.assertNotIn('CALL=Connect', r.stderr)

    def test_runtime_directory_is_error_instead_of_silent_default(self):
        self.saved.mkdir()
        try:
            r = self.run_bridge('read-epc')
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(r.stdout.strip(), 'ERROR=POWER_CONFIG_READ_FAILED')
            self.assertNotIn('CALL=Connect', r.stderr)
        finally:
            self.saved.rmdir()

    def test_invalid_runtime_does_not_block_diagnosis_or_repair(self):
        self.saved.write_text('{broken')
        for args in [('status',), ('get-power',), ('set-power','18')]:
            with self.subTest(args=args):
                r = self.run_bridge(*args)
                self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.saved.read_text(), '{broken')  # CLI does not persist: PHP owns runtime settings.

    def test_prepare_failure_stops_tag_operations_before_inventory_or_write(self):
        for args in [('read-epc',), ('inventory',), ('write-epc','000000000000000001000028'), ('clear','6')]:
            for env, error in [({'FAKE_SET':'0'}, 'POWER_SET_FAILED'), ({'FAKE_AFTER_POWER':'-1'}, 'POWER_VERIFY_FAILED'), ({'FAKE_AFTER_POWER':'11'}, 'POWER_VERIFY_FAILED')]:
                with self.subTest(args=args, env=env):
                    r = self.run_bridge(*args, **env)
                    self.assertNotEqual(r.returncode, 0)
                    self.assertEqual(r.stdout.strip(), 'ERROR=' + error)
                    self.assertNotIn('CALL=Inventory', r.stderr)
                    self.assertNotIn('CALL=WriteTag', r.stderr)
                    self.assertNotIn('DETECTED=', r.stdout)
                    self.assertNotIn('WRITTEN=', r.stdout)

    def test_zero_epc_and_write_contract_unchanged(self):
        r = self.run_bridge('read-epc', FAKE_TAG='000000000000000000000000')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), 'DETECTED=000000000000000000000000')
        r = self.run_bridge('write-epc', '000000000000000001000028')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), 'WRITTEN=000000000000000001000028')
        r = self.run_bridge('clear', '6')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.splitlines(), ['WRITTEN=000000000000000000000000', 'OK'])

if __name__ == '__main__':
    unittest.main()
