using System;
using System.Collections.Generic;
using System.Text;

namespace MPFever
{
    // What a savegame says about MPFever's companies, read from the decompressed savegame without loading it.
    //
    // The game keeps the mod's state (its companies' registry among it, see mpfever_co.lua) as serialized Lua tables: each value starts
    // with its type (int32): a string 3, its length (int32) and its bytes; a number 2 and a double; a table 4 and its entries; a table's keys come in
    // alphabetical order. A company is { ..., color = <palette index>, ent, [gone], id = n, key = "<player>", members, name, ... }:
    // its "key" entry comes right after its "id" one, which tells it from a member's { key, sid } (key first).
    static class SaveInfo
    {
        public sealed class Company
        {
            public int Number;     // n of the key "ai:<n>"
            public string Name = "";
            public int Color;      // palette index (1-12), 0 when unknown
        }

        static readonly byte[] KeyEntry = { 3, 0, 0, 0, 3, 0, 0, 0, (byte)'k', (byte)'e', (byte)'y', 3, 0, 0, 0 };
        static readonly byte[] IdEntry = { 3, 0, 0, 0, 2, 0, 0, 0, (byte)'i', (byte)'d', 2, 0, 0, 0 };
        static readonly byte[] ColorEntry = { 3, 0, 0, 0, 5, 0, 0, 0, (byte)'c', (byte)'o', (byte)'l', (byte)'o', (byte)'r', 2, 0, 0, 0 };
        static readonly byte[] GoneEntry = { 3, 0, 0, 0, 4, 0, 0, 0, (byte)'g', (byte)'o', (byte)'n', (byte)'e' };
        static readonly byte[] NameEntry = { 3, 0, 0, 0, 4, 0, 0, 0, (byte)'n', (byte)'a', (byte)'m', (byte)'e', 3, 0, 0, 0 };

        /// <summary>The computer companies of a savegame (keys "ai:n", not gone), by number; empty when none or unreadable.</summary>
        public static List<Company> AiCompanies(string savePath)
        {
            var found = new SortedDictionary<int, Company>();
            byte[] d;
            try { d = Zstd.DecompressFile(savePath); }
            catch (Exception e) { Log.W("savegame companies: " + e.Message); return new List<Company>(); }
            for (int i = IndexOf(d, KeyEntry, 0); i >= 0; i = IndexOf(d, KeyEntry, i + 1))
            {
                int v = i + KeyEntry.Length;
                if (v + 4 > d.Length) break;
                int len = BitConverter.ToInt32(d, v);
                if (len < 4 || len > 12 || v + 4 + len > d.Length) continue;
                string key = Encoding.ASCII.GetString(d, v + 4, len);
                if (!key.StartsWith("ai:", StringComparison.Ordinal) || !int.TryParse(key.Substring(3), out int n) || n < 1 || n > 32) continue;
                // (a company's own key: its "id" entry right before)
                int idAt = i - IdEntry.Length - 8;
                if (idAt < 0 || !Same(d, idAt, IdEntry)) continue;
                if (found.ContainsKey(n)) continue;
                var c = new Company { Number = n };
                // its colour and whether it is gone: in the entries before (chief, color, ent, gone, id)
                int from = Math.Max(0, i - 200);
                int col = LastIndexOf(d, ColorEntry, from, i);
                if (col >= 0 && col + ColorEntry.Length + 8 <= d.Length)
                {
                    double x = BitConverter.ToDouble(d, col + ColorEntry.Length);
                    if (x >= 1 && x <= 12 && x == Math.Floor(x)) c.Color = (int)x;
                }
                if (LastIndexOf(d, GoneEntry, col >= 0 ? col : from, i) >= 0) continue;
                // its name: after its members
                int nm = IndexOf(d, NameEntry, v, Math.Min(d.Length, v + 4000));
                if (nm >= 0)
                {
                    int nv = nm + NameEntry.Length;
                    int nl = nv + 4 <= d.Length ? BitConverter.ToInt32(d, nv) : -1;
                    if (nl >= 0 && nl <= 200 && nv + 4 + nl <= d.Length) c.Name = Encoding.UTF8.GetString(d, nv + 4, nl);
                }
                found[n] = c;
            }
            return new List<Company>(found.Values);
        }

        static bool Same(byte[] d, int at, byte[] p)
        {
            if (at < 0 || at + p.Length > d.Length) return false;
            for (int k = 0; k < p.Length; k++) if (d[at + k] != p[k]) return false;
            return true;
        }

        static int IndexOf(byte[] d, byte[] p, int start, int end = -1)
        {
            if (end < 0) end = d.Length;
            int last = end - p.Length;
            for (int i = Array.IndexOf(d, p[0], start); i >= 0 && i <= last; i = Array.IndexOf(d, p[0], i + 1))
                if (Same(d, i, p)) return i;
            return -1;
        }

        static int LastIndexOf(byte[] d, byte[] p, int start, int end)
        {
            for (int i = end - p.Length; i >= start; i--) if (d[i] == p[0] && Same(d, i, p)) return i;
            return -1;
        }
    }
}
