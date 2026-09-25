using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Threading;
using OR2127LIB;

public class OR2103Bridge
{
    private static string ComPort = "COM5";
    private static int BaudRate = 115200;
    private static int TimeoutMs = 15000;
    private static string AccessPwd = "00000000";
	
	private static int Power = 10;

    private static ReaderManager readerManager;
    private static readonly object TagsLock = new object();
    private static readonly List<string> Tags = new List<string>();

    public static int Main(string[] args)
    {
        try { LoadConfig(); }
        catch (Exception ex)
        {
            Out("ERROR=" + Clean(ex.Message));
            return 1;
        }

        if (args.Length < 1)
        {
            Out("ERROR=ACTION_REQUIRED");
            return 1;
        }

        string action = args[0].Trim().ToLowerInvariant();

        if (action == "methods")
        {
            PrintMethods();
            return 0;
        }

        int requestedPower = 0;
        if (action == "set-power")
        {
            if (args.Length < 2)
            {
                Out("ERROR=POWER_REQUIRED");
                return 1;
            }
            if (!Regex.IsMatch(args[1], @"\A[0-9]{1,2}\z") ||
                !int.TryParse(args[1], out requestedPower) || requestedPower < 5 || requestedPower > 30)
            {
                Out("ERROR=POWER_INVALID");
                return 1;
            }
        }
        if (action != "status" && action != "get-power" && action != "set-power" &&
            action != "version" && action != "inventory" && action != "read-epc" &&
            action != "write-epc" && action != "clear")
        {
            Out("ERROR=UNKNOWN_ACTION");
            return 1;
        }

        if (action == "inventory" || action == "read-epc" || action == "write-epc" || action == "clear")
        {
            try { LoadRuntimePower(); }
            catch (Exception ex)
            {
                Out("ERROR=" + Clean(ex.Message));
                return 1;
            }
        }

        string msg;
        if (!Connect(out msg))
        {
            Out("ERROR=CONNECT_FAILED:" + Clean(msg));
            return 2;
        }

        try
        {
            // Consultas diagnosticas exigen una respuesta del lector y no cambian su potencia.
            if (action == "status") return Status();
            if (action == "get-power") return GetPower();
            if (action == "set-power") return SetPower(requestedPower);
            if (action == "version") return Version();

            PrepareReader();
            if (action == "inventory") return Inventory(false);
            if (action == "read-epc") return Inventory(true);

            if (action == "write-epc")
            {
                if (args.Length < 2)
                {
                    Out("ERROR=EPC_REQUIRED");
                    return 1;
                }

                return WriteEpc(args[1]);
            }

            if (action == "clear")
            {
                int palabras = 6;
                if (args.Length >= 2) int.TryParse(args[1], out palabras);
                return Clear(palabras);
            }

            Out("ERROR=UNKNOWN_ACTION");
            return 1;
        }
        catch (Exception ex)
        {
            Out("ERROR=" + Clean(ex.Message));
            return 1;
        }
		finally
		{
            // No configurar LED/buzzer (0x13): el OR2103 probado deja de aceptar comandos.
            // Cerrar el puerto sin enviar configuraciones adicionales al lector.
            TryClose(readerManager);
            if (action == "inventory" || action == "read-epc" || action == "write-epc" || action == "clear")
                Thread.Sleep(800);
		}
    }

	private static bool Connect(out string msg)
	{
		msg = "";

		for (int i = 0; i < 3; i++)
		{
			try
			{
				readerManager = new ReaderManager();
				if (readerManager.ConSerialPort(ComPort, BaudRate, out msg))
				{
					return true;
				}
			}
			catch (Exception ex)
			{
				msg = ex.Message;
			}

            TryClose(readerManager);
            Thread.Sleep(500);
        }

        return false;
	}

	private static void PrepareReader()
	{
		string msg;

        // El SDK detiene en una tarea: esperar su ACK antes de configurar o cerrar el puerto.
        StopInventoryConfirmed();

        // Cada operacion debe conservar la potencia elegida, no continuar si el lector la rechaza.
        bool powerSet;
        try { powerSet = readerManager.SetPower(Power, out msg); }
        catch { throw new InvalidOperationException("POWER_SET_FAILED"); }
        if (!powerSet) throw new InvalidOperationException("POWER_SET_FAILED");
        int actualPower;
        try { actualPower = readerManager.GetPower(out msg); }
        catch { throw new InvalidOperationException("POWER_VERIFY_FAILED"); }
        if (actualPower != Power) throw new InvalidOperationException("POWER_VERIFY_FAILED");

        // Conservar la configuracion de areas del lector; 0x43 corresponde a auto/trigger.

		Thread.Sleep(200);
	}

    private static void TryClearFilters()
    {
        TryCall("SetTagFilter", new object[] { "", 0, 0, "" });
        TryCall("SetTagFilter", new object[] { 0, 0, 0, "", "" });
        TryCall("SetTagFilter", new object[] { 1, 0, 0, "", "" });
        TryCall("SetTagFilter", new object[] { false, 0, 0, "", "" });
    }

    private static bool TryCall(string methodName, object[] args)
    {
        try
        {
            Type t = readerManager.GetType();

            foreach (MethodInfo mi in t.GetMethods())
            {
                if (mi.Name != methodName) continue;

                ParameterInfo[] ps = mi.GetParameters();
                if (ps.Length != args.Length) continue;

                object[] values = new object[args.Length];

                for (int i = 0; i < ps.Length; i++)
                {
                    Type pt = ps[i].ParameterType;
                    object arg = args[i];

                    if (pt.IsByRef)
                    {
                        Type et = pt.GetElementType();
                        if (et == typeof(string)) values[i] = arg == null ? "" : arg.ToString();
                        else if (et == typeof(int)) values[i] = Convert.ToInt32(arg);
                        else if (et == typeof(bool)) values[i] = Convert.ToBoolean(arg);
                        else values[i] = arg;
                    }
                    else if (pt == typeof(string))
                    {
                        values[i] = arg == null ? "" : arg.ToString();
                    }
                    else if (pt == typeof(int))
                    {
                        values[i] = Convert.ToInt32(arg);
                    }
                    else if (pt == typeof(bool))
                    {
                        values[i] = Convert.ToBoolean(arg);
                    }
                    else if (pt == typeof(byte))
                    {
                        values[i] = Convert.ToByte(arg);
                    }
                    else
                    {
                        values[i] = arg;
                    }
                }

                mi.Invoke(readerManager, values);
                return true;
            }
        }
        catch { }

        return false;
    }

    private static void TrySetReadArea(object manager)
    {
        Type t = manager.GetType();

        foreach (MethodInfo mi in t.GetMethods())
        {
            if (mi.Name != "SetReadArea") continue;

            ParameterInfo[] ps = mi.GetParameters();
            object[] values = new object[ps.Length];

            for (int i = 0; i < ps.Length; i++)
            {
                Type pt = ps[i].ParameterType;

                if (pt == typeof(int)) values[i] = 0;
                else if (pt == typeof(string)) values[i] = "EPC";
                else if (pt == typeof(bool)) values[i] = false;
                else if (pt == typeof(byte)) values[i] = (byte)0;
                else if (pt.IsByRef)
                {
                    Type et = pt.GetElementType();
                    if (et == typeof(string)) values[i] = "";
                    else if (et == typeof(int)) values[i] = 0;
                    else if (et == typeof(bool)) values[i] = false;
                    else values[i] = null;
                }
                else values[i] = null;
            }

            try
            {
                mi.Invoke(manager, values);
                return;
            }
            catch { }
        }
    }

    private static int ReadPower(out int actualPower)
    {
        string msg;
        actualPower = readerManager.GetPower(out msg);
        // El SDK valida cabecera, checksum y estado de la respuesta 0x22; -1 significa fallo.
        if (actualPower < 0 || actualPower > 255)
        {
            Out("ERROR=READER_NOT_RESPONDING" + (string.IsNullOrEmpty(msg) ? "" : ":" + Clean(msg)));
            return 1;
        }
        return 0;
    }

    private static int Status()
    {
        int actualPower;
        if (ReadPower(out actualPower) != 0) return 1;
        Out("OK");
        Out("CONNECTED=1");
        Out("COM=" + ComPort);
        Out("BAUDRATE=" + BaudRate);
        Out("TIMEOUT_MS=" + TimeoutMs);
        Out("POWER=" + actualPower);
        return 0;
    }

    private static int GetPower()
    {
        int actualPower;
        if (ReadPower(out actualPower) != 0) return 1;
        Out("POWER=" + actualPower);
        Out("OK");
        return 0;
    }

    private static int SetPower(int requestedPower)
    {
        string msg;
        if (!readerManager.SetPower(requestedPower, out msg))
        {
            Out("ERROR=POWER_SET_FAILED" + (string.IsNullOrEmpty(msg) ? "" : ":" + Clean(msg)));
            return 1;
        }
        int actualPower;
        if (ReadPower(out actualPower) != 0) return 1;
        if (actualPower != requestedPower)
        {
            Out("ERROR=POWER_VERIFY_FAILED");
            return 1;
        }
        Out("POWER=" + actualPower);
        Out("OK");
        return 0;
    }

    private static int Version()
    {
        string version;
        if (readerManager.GetVersion(out version))
        {
            Out("VERSION=" + Clean(version));
            return 0;
        }

        Out("ERROR=VERSION_FAILED");
        return 1;
    }

    private static int Inventory(bool onlyFirst)
    {
        lock (TagsLock) { Tags.Clear(); }
        readerManager.InventoryTag += ReaderManager_InventoryTag;
        string msg;
        bool started;
        try
        {
            started = readerManager.Inventory(out msg);
            if (started)
            {
                DateTime end = DateTime.Now.AddMilliseconds(TimeoutMs);
                while (DateTime.Now < end)
                {
                    lock (TagsLock)
                    {
                        if (onlyFirst && Tags.Count > 0) break;
                    }
                    Thread.Sleep(50);
                }
            }
        }
        finally
        {
            try { StopInventoryConfirmed(); }
            finally { readerManager.InventoryTag -= ReaderManager_InventoryTag; }
        }

        if (!started)
        {
            Out("ERROR=INVENTORY_FAILED:" + Clean(msg));
            return 1;
        }
        List<string> copy;
        lock (TagsLock) { copy = new List<string>(Tags); }
        if (copy.Count == 0)
        {
            Out("NO_TAG");
            return 0;
        }
        if (onlyFirst)
        {
            // Aviso puntual con respuesta consumida antes de cerrar COM.
            TryBeepConfirmed();
            Out("DETECTED=" + copy[0]);
        }
        else
        {
            foreach (string epc in copy) Out("DETECTED=" + epc);
        }
        return 0;
    }

    private static bool TryBeepConfirmed()
    {
        try
        {
            // SendBuzzer usa Send y purga TX inmediatamente. La API sincronica espera el ACK.
            byte[] reply = ReaderUtil.GetInstance().SendGetData(new byte[] { 0xA5, 0x00, 0x19, 0x19 });
            return reply != null && reply.Length == 5 && reply[0] == 0xA5 && reply[1] == 1 &&
                reply[2] == 0x19 && reply[3] == 0 && reply[4] == 0x1A;
        }
        catch { return false; }
    }

    private static void StopInventoryConfirmed()
    {
        using (StopAcknowledgement acknowledgement = new StopAcknowledgement())
        {
            readerManager.DataTransmission += acknowledgement.OnData;
            try
            {
                try { readerManager.StopInventory(); }
                catch { throw new InvalidOperationException("READER_NOT_RESPONDING:STOP"); }
                // El SDK espera 50 ms antes de transmitir y hasta 600 ms por respuesta.
                if (!acknowledgement.Wait(1500))
                    throw new InvalidOperationException("READER_NOT_RESPONDING:STOP");
                string error = acknowledgement.Error;
                if (error.Length > 0) throw new InvalidOperationException(error);
            }
            finally { readerManager.DataTransmission -= acknowledgement.OnData; }
        }
    }

    private sealed class StopAcknowledgement : IDisposable
    {
        private readonly object gate = new object();
        private readonly List<byte> buffer = new List<byte>();
        private readonly ManualResetEventSlim completed = new ManualResetEventSlim(false);
        private bool waitingForReply;
        private bool finished;
        private bool disposed;
        private string error = "";

        public string Error { get { lock (gate) { return error; } } }
        public bool Wait(int milliseconds) { return completed.Wait(milliseconds); }

        public void OnData(byte[] data, bool isSend)
        {
            lock (gate)
            {
                if (disposed || finished || data == null) return;
                if (isSend)
                {
                    // Solo correlacionar respuestas recibidas despues del comando de esta parada.
                    if (data.Length == 4 && data[0] == 0xA5 && data[1] == 0 && data[2] == 0x54 && data[3] == 0x54)
                    {
                        waitingForReply = true;
                        buffer.Clear();
                    }
                    return;
                }
                if (!waitingForReply) return;
                buffer.AddRange(data);
                while (buffer.Count >= 4)
                {
                    int start = buffer.IndexOf(0xA5);
                    if (start < 0) { buffer.Clear(); return; }
                    if (start > 0) buffer.RemoveRange(0, start);
                    if (buffer.Count < 4) return;
                    int length = buffer[1] + 4;
                    // No buscar un ACK dentro del EPC de una trama 0x55 incompleta.
                    if (buffer.Count < length) return;
                    byte[] frame = buffer.GetRange(0, length).ToArray();
                    buffer.RemoveRange(0, length);
                    if (frame[2] != 0x54) continue;
                    int checksum = 0;
                    for (int i = 1; i < frame.Length - 1; i++) checksum += frame[i];
                    if ((checksum & 0xFF) != frame[frame.Length - 1])
                        Finish("READER_CHECKSUM:STOP");
                    else if (frame.Length != 5 || frame[1] != 1)
                        Finish("READER_RESPONSE_INVALID:STOP");
                    else if (frame[3] != 0)
                        Finish("READER_STATUS_" + frame[3].ToString("X2") + ":STOP");
                    else
                        Finish("");
                    return;
                }
            }
        }

        private void Finish(string failure)
        {
            error = failure;
            finished = true;
            completed.Set();
        }

        public void Dispose()
        {
            lock (gate)
            {
                disposed = true;
                completed.Dispose();
            }
        }
    }

    private static void ReaderManager_InventoryTag(TagInfo tagInfo)
    {
        if (tagInfo == null) return;

        string epc = NormalizeHex(tagInfo.EPC);
        if (epc.Length == 0) return;

        lock (TagsLock)
        {
            if (!Tags.Contains(epc)) Tags.Add(epc);
        }
    }

    private static int WriteEpc(string epc)
    {
        epc = NormalizeHex(epc);

        if (epc.Length == 0)
        {
            Out("ERROR=EPC_EMPTY");
            return 1;
        }

        if (epc.Length % 4 != 0)
        {
            Out("ERROR=EPC_LENGTH_MUST_BE_WORD_ALIGNED");
            return 1;
        }

        string msg;

        int byteLen = epc.Length / 2;
        int wordLen = byteLen / 2;

        UInt16 pc = (UInt16)(((UInt16)wordLen & 0x1F) << 11);
        string pcHex = pc.ToString("X4");
        string data = pcHex + epc;

        bool ok = readerManager.WriteTag(AccessPwd, 1, 1, wordLen + 1, data, out msg);

        if (!ok)
        {
            Thread.Sleep(500);
            ok = readerManager.WriteTag(AccessPwd, 1, 1, wordLen + 1, data, out msg);
        }

        if (ok)
        {
            Out("WRITTEN=" + epc);
            return 0;
        }

        Out("ERROR=WRITE_FAILED:" + Clean(msg));
        return 1;
    }

    private static int Clear(int palabras)
    {
        if (palabras <= 0) palabras = 6;

        string zeros = new string('0', palabras * 4);
        int result = WriteEpc(zeros);

        if (result == 0) Out("OK");

        return result;
    }

    private static void TryClose(object manager)
    {
        if (manager == null) return;

        string[] names = new string[] {
            "DisCon",
            "CloseCon",
            "CloseConnect",
            "CloseConnection",
            "Close",
            "CloseCom",
            "CloseSerialPort",
            "DisConnect",
            "Disconnect"
        };

        Type t = manager.GetType();

        foreach (string name in names)
        {
            try
            {
                MethodInfo mi = t.GetMethod(name, Type.EmptyTypes);
                if (mi != null)
                {
                    mi.Invoke(manager, null);
                    return;
                }
            }
            catch { }
        }
    }

    private static void LoadConfig()
    {
        // BaseDirectory termina en separador: quitarlo antes de buscar la raiz del proyecto.
        string baseDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        string projectDir = Directory.GetParent(baseDir).FullName;
        try
        {
            string configPath = Path.Combine(projectDir, "config.json");
            if (!File.Exists(configPath)) configPath = Path.Combine(baseDir, "config.json");
            if (File.Exists(configPath))
            {
                string json = File.ReadAllText(configPath);
                // Las secciones actuales son objetos planos. No tomar valores de la seccion Linux.
                Match section = Regex.Match(json, "\\\"windows\\\"\\s*:\\s*\\{([^{}]*)\\}", RegexOptions.IgnoreCase);
                if (section.Success)
                {
                    string config = section.Groups[1].Value;
                    string com = MatchString(config, "com");
                    if (com.Length > 0) ComPort = com;
                    int baud = MatchInt(config, "baudrate");
                    if (baud > 0) BaudRate = baud;
                    int timeout = MatchInt(config, "timeout_ms");
                    if (timeout > 0) TimeoutMs = timeout;
                    string pwd = NormalizeHex(MatchString(config, "access_pwd"));
                    if (pwd.Length == 8) AccessPwd = pwd;
                    int power = MatchInt(config, "power");
                    if (power >= 5 && power <= 30) Power = power;
                }
            }
        }
        catch { }

    }

    private static void LoadRuntimePower()
    {
        string baseDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        string projectDir = Directory.GetParent(baseDir).FullName;
        string powerPath = Path.Combine(projectDir, "runtime", "antenna-power.json");
        string saved;
        try { saved = File.ReadAllText(powerPath); }
        catch (FileNotFoundException) { return; }
        catch (DirectoryNotFoundException) { return; }
        catch { throw new InvalidOperationException("POWER_CONFIG_READ_FAILED"); }
        // PHP guarda un objeto de una sola propiedad; no admitir valores parciales o ambiguos.
        Match setting = Regex.Match(saved, @"\A\s*\{\s*""power""\s*:\s*([1-9][0-9]?)\s*\}\s*\z");
        int savedPower;
        if (!setting.Success || !int.TryParse(setting.Groups[1].Value, out savedPower) || savedPower < 5 || savedPower > 30)
            throw new InvalidOperationException("POWER_CONFIG_INVALID");
        Power = savedPower;
    }

    private static string MatchString(string json, string key)
    {
        Match m = Regex.Match(json, "\\\"" + Regex.Escape(key) + "\\\"\\s*:\\s*\\\"([^\\\"]*)\\\"", RegexOptions.IgnoreCase);
        return m.Success ? m.Groups[1].Value.Trim() : "";
    }

    private static int MatchInt(string json, string key)
    {
        Match m = Regex.Match(json, "\\\"" + Regex.Escape(key) + "\\\"\\s*:\\s*(\\d+)", RegexOptions.IgnoreCase);
        if (!m.Success) return 0;
        int value;
        return int.TryParse(m.Groups[1].Value, out value) ? value : 0;
    }

    private static string NormalizeHex(string value)
    {
        if (value == null) return "";
        return Regex.Replace(value, "[^0-9A-Fa-f]", "").ToUpperInvariant();
    }

    private static string Clean(string value)
    {
        if (value == null) return "";
        return value.Replace("\r", " ").Replace("\n", " ").Trim();
    }

    private static void Out(string value)
    {
        Console.WriteLine(value);
    }

    private static void PrintMethods()
    {
        Type t = typeof(ReaderManager);

        foreach (var m in t.GetMethods())
        {
            if (m.DeclaringType == typeof(object)) continue;
            Console.WriteLine("METHOD=" + m.Name);
        }
    }
}