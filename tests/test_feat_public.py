"""Offline test of mod/mpfever_1/content/mpfever_feat_public.lua (0.6, the public games' options, note 09): the module loads
without the game's API, declares only its options as docs/FEATURES-0.6.md asks (ids, French and English texts, modes, every
option off by default, each parameter's default among its values, the values' labels through T(fr, en)), and has no game
code (no event, tick, gui, ui...: the public games are MPFever.exe's and the list's work, see launcher/PublicGames.cs, its
self-test, and tests/test_serverlist.py). The option ids MPFever.exe reads are checked against launcher/PublicGames.cs.
Run: python tests/test_feat_public.py
"""
import os
import re
import sys

import lupa.lua52 as lupa

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.join(HERE, "..", "mod", "mpfever_1", "content", "mpfever_feat_public.lua")
CS = os.path.join(HERE, "..", "launcher", "PublicGames.cs")


def main():
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    # (no api, no game: as the lobby and the tests load the modules)
    L.execute("api = nil; game = nil")
    M = L.execute(open(MOD, encoding="utf-8").read())
    fails = []

    def check(name, cond, got=""):
        print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f": {got}" if got != "" else ""))
        if not cond:
            fails.append(name)

    check("loads without the game's API", M is not None)
    check("module id", M["ID"] == "public", M["ID"])
    keys = sorted(str(k) for k in M.keys())
    check("options only (no game code)", keys == ["ID", "OPTIONS"], keys)
    T = L.eval("function(fr, en) return '[' .. en .. ']' end")
    ids = []
    for _, o in sorted(M["OPTIONS"].items()):
        oid = o["id"]
        ids.append(oid)
        check(f"{oid}: id", re.fullmatch(r"[a-z_]+", oid or "") is not None)
        check(f"{oid}: title and description in French and English",
              all(o[k] is not None and o[k][1] and o[k][2] and o[k][1] != o[k][2] for k in ("title", "desc")))
        check(f"{oid}: modes", o["modes"] == "both", o["modes"])
        check(f"{oid}: off by default", o["default"] is None)
        for _, p in sorted((o["params"] or L.table()).items()):
            values = list(p["values"].values())
            check(f"{oid}.{p['id']}: default among the values", p["default"] in values, f"{p['default']} in {values}")
            check(f"{oid}.{p['id']}: label in French and English", p["label"][1] and p["label"][2])
            if p["show"] is not None:
                shown = [p["show"](v, T) for v in values]
                check(f"{oid}.{p['id']}: values shown through T", all(isinstance(s, str) and s.startswith("[") for s in shown), shown)
    check("the four options of note 09", ids == ["public", "join_bans", "join_approve", "join_steamfriends"], ids)
    pub = M["OPTIONS"][1]
    params = {p["id"]: p for _, p in pub["params"].items()}
    check("public: 8 players at most by default (I7)", list(params["max"]["values"].values())[-1] == 8 and params["max"]["default"] == 8)
    check("public: no arrival during the game by default (I2)", params["late"]["default"] == 0)
    check("public: the IP address not shown by default (I3)", params["ip"]["default"] == 0)
    # the ids MPFever.exe reads (PublicGates.On / Param) are the declared ones
    cs = open(CS, encoding="utf-8").read()
    used = set(re.findall(r'(?:On|Param)\("([a-z_]+)"', cs))
    check("MPFever.exe reads the declared options only", used and used <= set(ids), sorted(used))
    used_params = set(re.findall(r'Param\("public", "([a-z_]+)"\)', cs))
    check("MPFever.exe reads the declared parameters only", used_params and used_params <= set(params), sorted(used_params))
    if fails:
        print(f"FAIL {len(fails)} case(s): {', '.join(fails)}")
        return 1
    print("all cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
