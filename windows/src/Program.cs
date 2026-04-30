using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Threading;
using OR2127LIB;

namespace OR2103Bridge
{
    internal class Program
    {
        private static readonly object LockObj = new object();
        private static readonly List<string> DetectedEpcs = new List<string>();

        private static string Com = "COM5";
        private static int Baudrate = 115200;
        private static int TimeoutMs = 4000;

        private static int Main(string[] args)
        {
            if (args.Length < 1)
            {
                Out("ERROR=ACTION_REQUIRED");
                return 1;
            }

            LoadConfig();
            string action = args[0].Trim().ToLowerInvariant();

            try
            {
                switch (action)
                {
                    case "inventory":
                        return Inventory();

                    case "read-epc":
                        return ReadEpc();

                    case "write-epc":
                        if (args.Length < 2)
                        {
                            Out("ERROR=EPC_REQUIRED");
                            return 1;
                        }
                        return WriteEpc(args[1]);

                    case "clear":
                        if (args.Length < 2)
                        {
                            Out("ERROR=PALABRAS_REQUIRED");
                            return 1;
                        }
                        return Clear(args[1]);

                    case "version":
                        return Version();

                    case "status":
                        Out("STATUS=OK");
                        return 0;

                    case "methods":
                        return Methods();

                    default:
                        Out("ERROR=UNKNOWN_ACTION");
                        return 1;
                }
            }
            catch (Exception ex)
            {
                Out("ERROR=" + Clean(ex.Message));
                return 1;
            }
        }

        private static int Inventory()
        {
            using (var session = OpenReader())
            {
                ReaderManager reader = session.Reader;
                DetectedEpcs.Clear();
                reader.InventoryTag += ReaderInventoryTag;

                string msg;
                bool started = reader.Inventory(out msg);
                if (!started)
                {
                    Out("ERROR=INVENTORY_FAILED_" + Clean(msg));
                    return 1;
                }

                Thread.Sleep(TimeoutMs);
                reader.StopInventory();

                lock (LockObj)
                {
                    if (DetectedEpcs.Count == 0)
                    {
                        Out("NO_TAG");
                        return 0;
                    }

                    foreach (string epc in DetectedEpcs)
                    {
                        Out("DETECTED=" + epc);
                    }
                }

                return 0;
            }
        }

        private static int ReadEpc()
        {
            using (var session = OpenReader())
            {
                ReaderManager reader = session.Reader;
                DetectedEpcs.Clear();
                reader.InventoryTag += ReaderInventoryTag;

                string msg;
                bool started = reader.Inventory(out msg);
                if (!started)
                {
                    Out("ERROR=READ_FAILED_" + Clean(msg));
                    return 1;
                }

                long start = Environment.TickCount;
                while (Environment.TickCount - start < TimeoutMs)
                {
                    lock (LockObj)
                    {
                        if (DetectedEpcs.Count > 0)
                        {
                            reader.StopInventory();
                            Out("DETECTED=" + DetectedEpcs[0]);
                            return 0;
                        }
                    }
                    Thread.Sleep(50);
                }

                reader.StopInventory();
                Out("NO_TAG");
                return 0;
            }
        }

        private static int WriteEpc(string epc)
        {
            epc = NormalizeHex(epc);
            if (string.IsNullOrWhiteSpace(epc))
            {
                Out("ERROR=INVALID_EPC");
                return 1;
            }

            // El SDK recibido confirma lectura por InventoryTag.
            // Para escritura necesitamos ver el demo C# exacto o ejecutar 'methods'
            // y revisar la firma de WriteTag/ReadTag.
            Out("ERROR=WRITE_NOT_IMPLEMENTED_PENDING_WRITE_METHOD_SIGNATURE");
            return 1;
        }

        private static int Clear(string palabras)
        {
            int words;
            if (!int.TryParse(palabras, out words) || words <= 0)
            {
                Out("ERROR=PALABRAS_INVALIDAS");
                return 1;
            }

            string zeros = new string('0', words * 4);
            return WriteEpc(zeros);
        }

        private static int Version()
        {
            using (var session = OpenReader())
            {
                string version;
                bool ok = session.Reader.GetVersion(out version);
                if (!ok)
                {
                    Out("ERROR=VERSION_FAILED");
                    return 1;
                }

                Out("VERSION=" + Clean(version));
                return 0;
            }
        }

        private static int Methods()
        {
            Type type = typeof(ReaderManager);
            foreach (MethodInfo method in type.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly))
            {
                string pars = string.Join(", ", method.GetParameters().Select(p => p.ParameterType.Name + " " + p.Name));
                Out("METHOD=" + method.ReturnType.Name + " " + method.Name + "(" + pars + ")");
            }
            return 0;
        }

        private static ReaderSession OpenReader()
        {
            var reader = new ReaderManager();
            string msg;
            bool ok = reader.ConSerialPort(Com, Baudrate, out msg);

            if (!ok)
            {
                throw new Exception("CONNECT_FAILED_" + Clean(msg));
            }

            return new ReaderSession(reader);
        }

        private static void ReaderInventoryTag(TagInfo tag)
        {
            if (tag == null || string.IsNullOrWhiteSpace(tag.EPC)) return;

            string epc = NormalizeHex(tag.EPC);
            if (string.IsNullOrWhiteSpace(epc)) return;

            lock (LockObj)
            {
                if (!DetectedEpcs.Contains(epc))
                {
                    DetectedEpcs.Add(epc);
                }
            }
        }

        private static void LoadConfig()
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            DirectoryInfo dir = Directory.GetParent(baseDir);
            string configPath = dir != null ? Path.Combine(dir.FullName, "config.json") : Path.Combine(baseDir, "config.json");

            if (!File.Exists(configPath)) return;

            string json = File.ReadAllText(configPath);

            string com = MatchJsonString(json, "com");
            if (!string.IsNullOrWhiteSpace(com)) Com = com;

            int baud;
            if (MatchJsonInt(json, "baudrate", out baud)) Baudrate = baud;

            int timeout;
            if (MatchJsonInt(json, "timeout_ms", out timeout)) TimeoutMs = timeout;
        }

        private static string MatchJsonString(string json, string key)
        {
            Match m = Regex.Match(json, "\"" + key + "\"\\s*:\\s*\"([^\"]+)\"", RegexOptions.IgnoreCase);
            return m.Success ? m.Groups[1].Value.Trim() : null;
        }

        private static bool MatchJsonInt(string json, string key, out int value)
        {
            value = 0;
            Match m = Regex.Match(json, "\"" + key + "\"\\s*:\\s*(\\d+)", RegexOptions.IgnoreCase);
            return m.Success && int.TryParse(m.Groups[1].Value, out value);
        }

        private static string NormalizeHex(string value)
        {
            return Regex.Replace(value ?? "", "[^0-9A-Fa-f]", "").ToUpperInvariant();
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
    }

    internal sealed class ReaderSession : IDisposable
    {
        public ReaderManager Reader { get; private set; }

        public ReaderSession(ReaderManager reader)
        {
            Reader = reader;
        }

        public void Dispose()
        {
            try { Reader.StopInventory(); } catch { }
            try { Reader.CloseCon(); } catch { }
        }
    }
}
