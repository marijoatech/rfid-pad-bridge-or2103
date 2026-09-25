"""Compile the actual Windows bridge against a fake SDK; never open a COM port."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(__file__).with_name('OR2103Bridge.cs')
if not SOURCE.exists():
    SOURCE = ROOT / 'windows' / 'OR2103Bridge.cs'
CSC = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if not CSC.exists():
    CSC = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework/v4.0.30319/csc.exe'

FAKE_SDK = r'''
using System;
using System.Threading;
namespace OR2127LIB {
    public class TagInfo { public string EPC; }
    public class ReaderUtil {
        private static readonly ReaderUtil instance = new ReaderUtil();
        public static ReaderUtil GetInstance() { return instance; }
        public byte[] SendGetData(byte[] command) { return ReaderManager.Current.SafeRequest(command); }
    }
    public class ReaderManager {
        public static ReaderManager Current;
        public ReaderManager() { Current = this; }
        public byte[] SafeRequest(byte[] command) {
            if (command == null || command.Length != 4 || command[0] != 0xA5 || command[1] != 0 || command[2] != 0x19 || command[3] != 0x19)
                throw new InvalidOperationException("FORBIDDEN_RAW_REQUEST");
            if (closed || stopRequests != stopReplies) { Log("UnsafeBeepBeforeStop"); throw new InvalidOperationException("STOP_NOT_CONFIRMED"); }
            Log("SafeBeep");
            Thread.Sleep(50); // Synchronous request does not return until the reply is consumed.
            Log("SafeBeepReply");
            string mode=Value("FAKE_BEEP_REPLY", "normal");
            if(mode == "throw") throw new InvalidOperationException("FAKE_BEEP_FAILED");
            if(mode == "null") return null;
            if(mode == "empty") return new byte[0];
            if(mode == "status") return Frame(0x19,1);
            if(mode == "wrong-command") return Frame(0x54,0);
            if(mode == "wrong-length") return Frame(0x19,0,0);
            byte[] reply=Frame(0x19,0);
            if(mode == "checksum") reply[4]++;
            return reply;
        }
        private Action<TagInfo> inventoryTag;
        private Action<byte[], bool> dataTransmission;
        public event Action<TagInfo> InventoryTag {
            add { inventoryTag += value; Log("SubscribeTag"); }
            remove { inventoryTag -= value; Log("UnsubscribeTag"); }
        }
        public event Action<byte[], bool> DataTransmission {
            add { dataTransmission += value; Log("SubscribeData"); }
            remove { dataTransmission -= value; Log("UnsubscribeData"); }
        }
        private volatile bool closed;
        private int stopRequests;
        private int stopReplies;
        private bool wasSet;
        private int requested;
        private static string Value(string name, string fallback) { return Environment.GetEnvironmentVariable(name) ?? fallback; }
        private static void Log(string message) { Console.Error.WriteLine("CALL=" + message); }
        public bool ConSerialPort(string com, int baud, out string msg) { Log("Connect:" + com + ":" + baud); msg="fake"; return Value("FAKE_CONNECT", "1") == "1"; }
        public void DisCon() {
            closed = true;
            Log("DisCon:requests=" + stopRequests + ":replies=" + stopReplies + ":data=" + (dataTransmission == null ? 0 : dataTransmission.GetInvocationList().Length) + ":tags=" + (inventoryTag == null ? 0 : inventoryTag.GetInvocationList().Length));
            Log("DisCon");
        }
        public int GetPower(out string msg) {
            Log("GetPower"); msg="";
            return int.Parse(Value(wasSet ? "FAKE_AFTER_POWER" : "FAKE_POWER", wasSet ? requested.ToString() : "17"));
        }
        public bool SetPower(int power, out string msg) { Log("SetPower:" + power); msg="fake"; wasSet=true; requested=power; return Value("FAKE_SET", "1") == "1"; }
        private void Emit(byte[] bytes, bool isSend) { Action<byte[], bool> callback = dataTransmission; if (callback != null) callback(bytes, isSend); }
        private static byte[] Frame(byte command, params byte[] payload) {
            byte[] result = new byte[payload.Length + 4]; result[0]=0xA5; result[1]=(byte)payload.Length; result[2]=command;
            Array.Copy(payload, 0, result, 3, payload.Length);
            int checksum=0; for(int i=1; i<result.Length-1; i++) checksum+=result[i]; result[result.Length-1]=(byte)checksum; return result;
        }
        private static byte[] Join(byte[] first, byte[] second) { byte[] result=new byte[first.Length+second.Length]; Array.Copy(first,result,first.Length); Array.Copy(second,0,result,first.Length,second.Length); return result; }
        private static byte[] Slice(byte[] source, int offset, int length) { byte[] result=new byte[length]; Array.Copy(source,offset,result,0,length); return result; }
        public void StopInventory() {
            int call=Interlocked.Increment(ref stopRequests); Log("StopInventory:" + call);
            string mode=Value(call == 1 ? "FAKE_PREPARE_STOP" : "FAKE_FINAL_STOP", "normal");
            if(mode == "throw") throw new InvalidOperationException("FAKE_STOP_THROW");
            ThreadPool.QueueUserWorkItem(delegate {
                try {
                    Thread.Sleep(50); // Same delayed send as the real SDK: closing early cancels STOP.
                    if(closed) { Log("StopCancelled:" + call); return; }
                    byte[] ack=Frame(0x54,0);
                    if(mode == "stale") Emit(ack,false); // Old traffic before this attempt transmits cannot confirm it.
                    Emit(Frame(0x54),true); Log("StopSent:" + call);
                    if(mode == "noack" || mode == "stale") return;
                    if(mode == "embedded") { Emit(Frame(0x55,0,0x30,0xA5,1,0x54,0,0x55,0,0),false); return; }
                    if(mode == "incomplete-embedded") { Emit(new byte[] {0xA5,18,0x55,0,0x30,0xA5,1,0x54,0,0x55},false); return; }
                    if(mode == "checksum") ack[4]++;
                    if(mode == "status") ack=Frame(0x54,1);
                    if(mode == "length") ack=Frame(0x54,0,0);
                    if(mode == "empty") ack=Frame(0x54);
                    Interlocked.Increment(ref stopReplies); Log("StopReply:" + call);
                    Action<byte[],bool> lateCallback = dataTransmission;
                    if(mode == "fragmented") { Emit(new byte[] {0,0x7E},false); Emit(Slice(ack,0,2),false); Thread.Sleep(5); Emit(Slice(ack,2,3),false); }
                    else if(mode == "coalesced") Emit(Join(Frame(0x55,0,0x30,0,0,0,0),ack),false);
                    else if(mode == "embedded-then-ack") { byte[] tag=Frame(0x55,0,0x30,0xA5,1,0x54,0,0x55,0,0); Emit(Slice(tag,0,10),false); Thread.Sleep(5); Emit(Join(Slice(tag,10,tag.Length-10),ack),false); }
                    else Emit(ack,false);
                    if(mode == "late") { Thread.Sleep(100); if(lateCallback != null) lateCallback(ack,false); }
                } catch(Exception ex) { Log("WorkerFailure:" + ex.GetType().Name); }
            });
        }
        public bool SetReadArea(int a,int b,int c,out string msg) { Log("SetReadArea"); msg=""; throw new InvalidOperationException("FORBIDDEN_AUTO_READ_AREA_CONFIGURATION"); }
        public bool SetLedBuzzer(int mode,out string msg) { Log("SetLedBuzzer:"+mode); msg=""; throw new InvalidOperationException("FORBIDDEN_LED_CONFIGURATION"); }
        public void SendBuzzer(out string msg) { Log("SendBuzzer"); msg=""; throw new InvalidOperationException("FORBIDDEN_UNSAFE_BUZZER_SEND"); }
        public bool GetVersion(out string version) { version="V1.2.3"; return true; }
        public bool Inventory(out string msg) {
            Log("Inventory"); msg="";
            if (Value("FAKE_INVENTORY", "1") == "throw") throw new InvalidOperationException("FAKE_INVENTORY_THROW");
            if (Value("FAKE_INVENTORY", "1") != "1") return false;
            if (inventoryTag != null && Value("FAKE_NO_TAG", "0") != "1") inventoryTag(new TagInfo { EPC=Value("FAKE_TAG", "000000000000000001000028") });
            return true;
        }
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
        # Exercise exact ACK recognition independently of the best-effort read result.
        harness = cls.base / 'BeepAckHarness.cs'
        harness.write_text('''using System;
using System.Reflection;
using OR2127LIB;
public class BeepAckHarness {
    public static int Main() {
        new ReaderManager();
        MethodInfo method = typeof(OR2103Bridge).GetMethod("TryBeepConfirmed", BindingFlags.NonPublic | BindingFlags.Static);
        bool confirmed = (bool)method.Invoke(null, null);
        Console.WriteLine(confirmed ? "BEEP_CONFIRMED" : "BEEP_UNCONFIRMED");
        return 0;
    }
}
''', encoding='utf-8')
        cls.beep_exe = cls.windows / 'BeepAckHarness.exe'
        built = subprocess.run([str(CSC), '/nologo', '/target:exe', '/main:BeepAckHarness', '/out:' + str(cls.beep_exe), str(SOURCE), str(fake), str(harness)], capture_output=True, text=True)
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
        result = subprocess.run([str(self.exe), *args], capture_output=True, text=True, env=env, timeout=10, cwd=self.base)
        # Includes cleanup after failures: command 0x13 must never be sent automatically.
        self.assertNotIn('CALL=SetLedBuzzer:', result.stderr, 'LED configuration can leave this pad unresponsive')
        self.assertNotIn('CALL=SetReadArea', result.stderr, 'Tag operations must preserve the auto/trigger read area')
        self.assertNotIn('CALL=SendBuzzer', result.stderr, 'SDK SendBuzzer discards pending TX and can leave the pad unresponsive')
        self.assertNotIn('CALL=UnsafeBeepBeforeStop', result.stderr)
        self.assertNotIn('CALL=WorkerFailure:', result.stderr)
        self.assertNotIn('CALL=StopCancelled:', result.stderr, 'SDK STOP must finish before COM is closed')
        return result

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

    def test_all_supported_actions_avoid_led_and_auto_area_configuration(self):
        for args in [('status',), ('get-power',), ('set-power','18'), ('version',), ('read-epc',), ('inventory',), ('write-epc','000000000000000001000028'), ('clear','6')]:
            with self.subTest(args=args):
                r = self.run_bridge(*args)
                self.assertEqual(r.returncode, 0, r.stdout)
                self.assertNotIn('CALL=SetLedBuzzer:', r.stderr)
                self.assertIn('CALL=DisCon', r.stderr)

    def test_successful_read_waits_for_safe_beep_after_confirmed_stop(self):
        r = self.run_bridge('read-epc')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(r.stdout.strip(), 'DETECTED=000000000000000001000028')
        self.assertNotIn('CALL=SendBuzzer', r.stderr)
        self.assertEqual(r.stderr.splitlines().count('CALL=SafeBeep'), 1)
        self.assertLess(r.stderr.index('CALL=StopReply:2'), r.stderr.index('CALL=SafeBeep'))
        self.assertLess(r.stderr.index('CALL=SafeBeepReply'), r.stderr.index('CALL=DisCon:'))

    def test_no_beep_for_diagnostics_no_tag_or_failed_read(self):
        for args, values in [
            (('status',), {}), (('get-power',), {}), (('set-power','18'), {}),
            (('read-epc',), {'FAKE_NO_TAG':'1'}),
            (('read-epc',), {'FAKE_SET':'0'}),
            (('read-epc',), {'FAKE_INVENTORY':'0'}),
            (('inventory',), {}),
        ]:
            with self.subTest(args=args, values=values):
                r = self.run_bridge(*args, **values)
                self.assertNotIn('CALL=SendBuzzer', r.stderr)
                self.assertNotIn('CALL=SafeBeep', r.stderr)
        r = self.run_bridge('read-epc', FAKE_NO_TAG='1')
        self.assertEqual(r.stdout.strip(), 'NO_TAG')

    def test_sdk_buzzer_failure_is_not_triggered_by_confirmed_read(self):
        r = self.run_bridge('read-epc', FAKE_BEEP_FAIL='1')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(r.stdout.strip(), 'DETECTED=000000000000000001000028')
        self.assertNotIn('CALL=SendBuzzer', r.stderr)
        self.assertNotIn('ERROR=', r.stdout)

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


    def assert_closed_without_subscriptions(self, result, requests, replies):
        marker = f'CALL=DisCon:requests={requests}:replies={replies}:data=0:tags=0'
        self.assertIn(marker, result.stderr)
        if replies:
            self.assertLess(result.stderr.index('CALL=StopReply:' + str(replies)), result.stderr.index(marker))

    def test_async_stop_finishes_before_close_with_and_without_tags(self):
        for action in ['read-epc', 'inventory']:
            for no_tag in ['0', '1']:
                with self.subTest(action=action, no_tag=no_tag):
                    r = self.run_bridge(action, FAKE_NO_TAG=no_tag)
                    self.assertEqual(r.returncode, 0, r.stdout)
                    self.assertEqual(r.stdout.strip(), 'NO_TAG' if no_tag == '1' else 'DETECTED=000000000000000001000028')
                    self.assert_closed_without_subscriptions(r, 2, 2)

    def test_inventory_failure_or_exception_still_waits_for_stop(self):
        for result, error in [('0', 'ERROR=INVENTORY_FAILED:'), ('throw', 'ERROR=FAKE_INVENTORY_THROW')]:
            with self.subTest(result=result):
                r = self.run_bridge('read-epc', FAKE_INVENTORY=result)
                self.assertNotEqual(r.returncode, 0)
                self.assertTrue(r.stdout.strip().startswith(error), r.stdout)
                self.assert_closed_without_subscriptions(r, 2, 2)
                self.assertNotIn('CALL=SendBuzzer', r.stderr)

    def test_missing_stop_ack_never_reports_success(self):
        for action in ['read-epc', 'inventory']:
            for no_tag in ['0', '1']:
                with self.subTest(action=action, no_tag=no_tag):
                    r = self.run_bridge(action, FAKE_FINAL_STOP='noack', FAKE_NO_TAG=no_tag)
                    self.assertNotEqual(r.returncode, 0)
                    self.assertEqual(r.stdout.strip(), 'ERROR=READER_NOT_RESPONDING:STOP')
                    self.assert_closed_without_subscriptions(r, 2, 1)
                    self.assertNotIn('CALL=SendBuzzer', r.stderr)

    def test_missing_prepare_stop_ack_blocks_tag_operations(self):
        for args in [('read-epc',), ('inventory',), ('write-epc','000000000000000001000028'), ('clear','6')]:
            with self.subTest(args=args):
                r = self.run_bridge(*args, FAKE_PREPARE_STOP='noack')
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(r.stdout.strip(), 'ERROR=READER_NOT_RESPONDING:STOP')
                self.assertNotIn('CALL=SetPower:', r.stderr)
                self.assertNotIn('CALL=Inventory', r.stderr)
                self.assertNotIn('CALL=WriteTag:', r.stderr)
                self.assert_closed_without_subscriptions(r, 1, 0)

    def test_stop_accepts_complete_frames_across_fragments_and_noise(self):
        for mode in ['fragmented', 'coalesced', 'embedded-then-ack', 'late']:
            with self.subTest(mode=mode):
                r = self.run_bridge('read-epc', FAKE_FINAL_STOP=mode)
                self.assertEqual(r.returncode, 0, r.stdout)
                self.assertEqual(r.stdout.strip(), 'DETECTED=000000000000000001000028')
                self.assert_closed_without_subscriptions(r, 2, 2)

    def test_stop_rejects_stale_ack_and_ack_bytes_inside_tag(self):
        for mode in ['stale', 'embedded', 'incomplete-embedded']:
            with self.subTest(mode=mode):
                r = self.run_bridge('read-epc', FAKE_FINAL_STOP=mode)
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(r.stdout.strip(), 'ERROR=READER_NOT_RESPONDING:STOP')
                self.assert_closed_without_subscriptions(r, 2, 1)

    def test_stop_requires_valid_checksum_payload_length_and_status(self):
        for mode, error in [('checksum','READER_CHECKSUM:STOP'), ('length','READER_RESPONSE_INVALID:STOP'), ('empty','READER_RESPONSE_INVALID:STOP'), ('status','READER_STATUS_01:STOP')]:
            with self.subTest(mode=mode):
                r = self.run_bridge('read-epc', FAKE_FINAL_STOP=mode)
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(r.stdout.strip(), 'ERROR=' + error)
                self.assert_closed_without_subscriptions(r, 2, 2)

    def test_stop_exception_removes_all_event_subscriptions(self):
        r = self.run_bridge('read-epc', FAKE_FINAL_STOP='throw')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), 'ERROR=READER_NOT_RESPONDING:STOP')
        self.assert_closed_without_subscriptions(r, 2, 1)


    def test_safe_beep_failure_never_invalidates_confirmed_epc(self):
        for mode in ['throw', 'null', 'empty', 'status', 'wrong-command', 'wrong-length', 'checksum']:
            with self.subTest(mode=mode):
                r = self.run_bridge('read-epc', FAKE_BEEP_REPLY=mode)
                self.assertEqual(r.returncode, 0, r.stdout)
                self.assertEqual(r.stdout.strip(), 'DETECTED=000000000000000001000028')
                self.assertEqual(r.stderr.splitlines().count('CALL=SafeBeep'), 1)
                self.assertLess(r.stderr.index('CALL=SafeBeepReply'), r.stderr.index('CALL=DisCon:'))
                self.assert_closed_without_subscriptions(r, 2, 2)


    def test_safe_beep_confirms_only_exact_success_ack(self):
        for mode in ['normal', 'throw', 'null', 'empty', 'status', 'wrong-command', 'wrong-length', 'checksum']:
            with self.subTest(mode=mode):
                env = os.environ.copy()
                for key in list(env):
                    if key.startswith('FAKE_'):
                        del env[key]
                env['FAKE_BEEP_REPLY'] = mode
                r = subprocess.run([str(self.beep_exe)], capture_output=True, text=True, env=env, timeout=5)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout.strip(), 'BEEP_CONFIRMED' if mode == 'normal' else 'BEEP_UNCONFIRMED')

if __name__ == '__main__':
    unittest.main()
