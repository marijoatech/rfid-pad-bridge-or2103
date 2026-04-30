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
        LoadConfig();

        if (args.Length < 1)
        {
            Out("ERROR=ACTION_REQUIRED");
            return 1;
        }

        string action = args[0].Trim().ToLowerInvariant();

        if (action == "status")
        {
            Out("OK");
            Out("COM=" + ComPort);
            Out("BAUDRATE=" + BaudRate);
            Out("TIMEOUT_MS=" + TimeoutMs);
            return 0;
        }

        if (action == "methods")
        {
            PrintMethods();
            return 0;
        }

        string msg;
        if (!Connect(out msg))
        {
            Out("ERROR=CONNECT_FAILED:" + Clean(msg));
            return 2;
        }

        try
        {
            PrepareReader();

            if (action == "version") return Version();
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
			string m;

			// No forzar StopInventory aqui, porque despues de write puede colgar
			try { readerManager.SetLedBuzzer(0, out m); } catch { }

			TryClose(readerManager);

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

			Thread.Sleep(500);
		}

		return false;
	}

	private static void PrepareReader()
	{
		string msg;

		// Importante: cerrar inventario anterior antes de leer
		try { readerManager.StopInventory(); } catch { }
		Thread.Sleep(300);

		try { readerManager.SetPower(Power, out msg); } catch { }

		// EPC area
		try { readerManager.SetReadArea(0, 0, 0, out msg); } catch { }

		// Buzzer OFF automatico
		try { readerManager.SetLedBuzzer(0, out msg); } catch { }

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
        bool started = readerManager.Inventory(out msg);

        if (!started)
        {
            readerManager.InventoryTag -= ReaderManager_InventoryTag;
            Out("ERROR=INVENTORY_FAILED:" + Clean(msg));
            return 1;
        }

        DateTime end = DateTime.Now.AddMilliseconds(TimeoutMs);

        while (DateTime.Now < end)
        {
            lock (TagsLock)
            {
                if (onlyFirst && Tags.Count > 0) break;
            }

            Thread.Sleep(50);
        }

        try { readerManager.StopInventory(); } catch { }
        readerManager.InventoryTag -= ReaderManager_InventoryTag;

        List<string> copy;
        lock (TagsLock) { copy = new List<string>(Tags); }

        if (copy.Count == 0)
        {
            Out("NO_TAG");
            return 0;
        }

        if (onlyFirst)
		{
			// 🔊 pitido manual SOLO una vez
			//try { readerManager.SendBuzzer(1, out msg); } catch { }
			//try { readerManager.SendBuzzer(); } catch { }
			try { readerManager.SetLedBuzzer(2, out msg); Thread.Sleep(150); readerManager.SetLedBuzzer(0, out msg); } catch { }

			Out("DETECTED=" + copy[0]);
		}
        else
        {
            foreach (string epc in copy)
            {
                Out("DETECTED=" + epc);
            }
        }

        return 0;
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
        try
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string configPath = Path.Combine(Directory.GetParent(baseDir).FullName, "config.json");

            if (!File.Exists(configPath)) configPath = Path.Combine(baseDir, "config.json");
            if (!File.Exists(configPath)) return;

            string json = File.ReadAllText(configPath);

            string com = MatchString(json, "com");
            if (com.Length > 0) ComPort = com;

            int baud = MatchInt(json, "baudrate");
            if (baud > 0) BaudRate = baud;

            int timeout = MatchInt(json, "timeout_ms");
            if (timeout > 0) TimeoutMs = timeout;

            string pwd = NormalizeHex(MatchString(json, "access_pwd"));
            if (pwd.Length == 8) AccessPwd = pwd;

			int power = MatchInt(json, "power");
			if (power >= 5 && power <= 30) Power = power;

        }
        catch { }
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