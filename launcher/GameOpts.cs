using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace MPFever
{
    /// <summary>The 0.6 game options of a session (docs/FEATURES-0.6.md): one string "id=1;id.param=v;..." the host chooses in its
    /// lobby's "Game settings" (or in its game's MPFever window), off by default. MPFever.exe keeps the session's (gameopts= in
    /// mpfever_settings.txt, game-options= for a dedicated server), sends it to every lobby view and with the session to every game,
    /// whose options host (mpfever_feat.lua) reads it. Here only its syntax: which options exist, their modes and values are the
    /// Lua modules' (the game's canon drops what they do not declare).</summary>
    static class GameOpts
    {
        /// <summary>The string at most (characters, entries), as mpfever_feat.lua caps it.</summary>
        public const int MaxText = 1000, MaxEntries = 64;

        static readonly Regex KeyRx = new Regex("^[a-z_]+(\\.[a-z_]+)?$", RegexOptions.CultureInvariant);
        static readonly Regex ValueRx = new Regex("^[-0-9a-z_.]+$", RegexOptions.CultureInvariant);

        /// <summary>The entries of a string, keys in byte order (as the Lua side sorts them); entries of another syntax are left out.</summary>
        public static SortedDictionary<string, string> Parse(string s)
        {
            var map = new SortedDictionary<string, string>(StringComparer.Ordinal);
            if (string.IsNullOrEmpty(s) || s.Length > MaxText) return map;
            foreach (var entry in s.Split(';'))
            {
                int eq = entry.IndexOf('=');
                if (eq <= 0) continue;
                string k = entry.Substring(0, eq).Trim(), v = entry.Substring(eq + 1).Trim();
                if (!KeyRx.IsMatch(k) || !ValueRx.IsMatch(v)) continue;
                if (!map.ContainsKey(k) && map.Count >= MaxEntries) continue;
                map[k] = v;
            }
            return map;
        }

        /// <summary>The options on ("id=1") and the parameters of those only, keys sorted: the form MPFever.exe keeps and sends.</summary>
        public static string Canon(string s)
        {
            var map = Parse(s);
            var keep = map.Where(kv =>
            {
                int dot = kv.Key.IndexOf('.');
                string id = dot < 0 ? kv.Key : kv.Key.Substring(0, dot);
                return map.TryGetValue(id, out var on) && on == "1" && (dot >= 0 || kv.Value == "1");
            });
            return string.Join(";", keep.Select(kv => kv.Key + "=" + kv.Value));
        }

        /// <summary>A request of the host ("id=0", "id=1" or "id.param=value") applied to the current string: the new string, or null
        /// with the reason when the request is not of that syntax or the string would grow too long. Switching an option off forgets
        /// its parameters (off, it has none: the lobby shows them only while it is on).</summary>
        public static string Apply(string current, string request, out string error)
        {
            error = null;
            request = (request ?? "").Trim();
            int eq = request.IndexOf('=');
            if (request.Length == 0 || request.Length > 80 || eq <= 0) { error = "syntax"; return null; }
            string k = request.Substring(0, eq), v = request.Substring(eq + 1);
            if (!KeyRx.IsMatch(k) || !ValueRx.IsMatch(v)) { error = "syntax"; return null; }
            var map = Parse(Canon(current));
            int dot = k.IndexOf('.');
            if (dot < 0)
            {
                if (v != "0" && v != "1") { error = "value"; return null; }
                if (v == "1") map[k] = "1";
                else foreach (var key in map.Keys.Where(x => x == k || x.StartsWith(k + ".", StringComparison.Ordinal)).ToList()) map.Remove(key);
            }
            else
            {
                if (!map.TryGetValue(k.Substring(0, dot), out var on) || on != "1") { error = "option off"; return null; }
                map[k] = v;
            }
            var s = string.Join(";", map.Select(kv => kv.Key + "=" + kv.Value));
            if (s.Length > MaxText || map.Count > MaxEntries) { error = "too long"; return null; }
            return s;
        }
    }
}
