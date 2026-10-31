"""A new multiplayer game without a savegame (0.6.3), offline (lupa, Lua 5.2).

The host's « New game… » button (mpfever_menu.lua, newGame) writes newgame.txt and opens the game's New Game page; the menu
marks the file "started" when that page starts a game; the application script mpfever_auto.lua (newGameTick) starts the loaded
game, saves it as "MPFever <date>", marks the file "saved" and goes back to the main menu, where the main page hosts that
savegame (the lobby opens with it). The menu's real newGame helpers and the real mpfever_auto.lua run here with a mocked game
(app, api) on one real folder. Cases:
  - the menu: « New game » writes the file (state wait, the company mode, the player's name) and opens the game's New Game
    page; app.startGame2 (not a map editor's) and app.loadGame of a saved map mark it started, a savegame's load does not; app's
    functions that cannot be wrapped: "any"; a page that does not open: the file emptied;
  - the main page: a saved new game is taken (the file emptied) and hosted as the tiles' « Host » button does (host_mods.txt,
    the « host » request with the savegame, the player's name and the company mode); any other state, or one older than 2 hours,
    is forgotten;
  - mpfever_auto.lua: nothing without the file, while it says wait, when it is old, with MPFEVER_NEWGAME=0; started or any:
    the loaded game started, saved about 2 s later as "MPFever <date>", then back to the main menu once (not when the player
    went there already); a save that fails: "failed", the game stays;
  - the whole way through the folder: the menu's file read by the script, the script's read by the menu;
  - the switches and hooks in the code: MPFEVER_NEWGAME=0 hides the button, the main page takes the file when it shows.
Run: python tests/test_newgame.py
"""
import os
import re
import shutil
import sys
import tempfile

try:
    import lupa.lua52 as lupa
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(HERE, "..", "mod", "mpfever_1", "content")
fails = []


def check(name, cond, got=""):
    print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f": {got}" if got != "" and not cond else ""))
    if not cond:
        fails.append(name)


menu = open(os.path.join(CONTENT, "mpfever_menu.lua"), encoding="utf-8").read()
auto = open(os.path.join(CONTENT, "mpfever_auto.lua"), encoding="utf-8").read()
m_ng = re.search(r"^\tlocal newGame = \{.*?^\tfunction newGame\.host\(m\)\n.*?^\tend\n", menu, re.S | re.M)
if not m_ng:
    print("FAIL: the menu's newGame helpers not found in mpfever_menu.lua")
    sys.exit(1)

# the menu's state: its files in the session folder, the game's app (startGame2 / loadGame recorded), the requests
MENU_MOCK = r'''
ENV = ENV or {}
os.getenv = function(k) return ENV[k] end
IO = io
BS, NL, TAB = string.char(92), string.char(10), string.char(9)
function readFile(name) local f = io.open(DIR .. BS .. name, "rb") if not f then return nil end local s = f:read("*a") f:close() return s end
function writeFile(name, text) local f = io.open(DIR .. BS .. name, "wb") f:write(text) f:close() return true end
LOGS, REQS, PAGES, CALLS = {}, {}, {}, {}
function log(s) LOGS[#LOGS + 1] = s end
function request(cmd, arg, name, option) REQS[#REQS + 1] = table.concat({ cmd, arg or "", name or "", option or "" }, "|") end
function listSaves() return { { saveName = "Old one", path = "p/o.sav" }, { saveName = SAVED or "?", path = "p/n.sav" } } end
function modsOf(info) return info.mods end
function encodeMods(mods) local o = {} for _, m in ipairs(mods or {}) do o[#o + 1] = m.id end return table.concat(o, ";;") end
api = { type = { SavegameId = { new = function() return {} end } } }
app = {
  SaveGameNamespace = { getSavegame = function() return "save" end, getSavemap = function() return "map" end },
  startGame2 = function(map, seed, date, tod, clouds, editor, mods) CALLS[#CALLS + 1] = "startGame2 " .. tostring(map) .. " " .. tostring(editor) .. " " .. tostring(mods) end,
  loadGame = function(id, editor, info) CALLS[#CALLS + 1] = "loadGame " .. tostring(id.saveGameName) .. " " .. tostring(editor) .. " " .. tostring(info) end,
  getSavegameInfo = function(id) return { get = function() return { info = { mods = { { id = "a_mod" }, { id = "b_mod" } } } } end } end,
}
COMMON = { setPage = function(page, params) PAGES[#PAGES + 1] = page .. " map=" .. tostring(params.map) end }
'''

AUTO_MOCK = r'''
ENV = ENV or {}
os.getenv = function(k) return ENV[k] end
print = function() end
WAITING, PROGRESS, STARTED, SAVES, STOPS, SAVEFAIL = false, 0, 0, {}, 0, false
app = {
  isWaitForStartReadyGame = function() return WAITING end,
  getProgressMonitor = function() return { getProgress = function() return PROGRESS end } end,
  startReadyGame = function() STARTED = STARTED + 1; WAITING = false end,
  saveGame = function(name, cb, editor, skip) if SAVEFAIL then error("disk full") end SAVES[#SAVES + 1] = { name = name, cb = cb, editor = editor } end,
  stopGame = function() STOPS = STOPS + 1 end,
  findAllSavegames = function() return {} end,
  SaveGameNamespace = { getSavegame = function() return "save" end },
}
'''


def main():
    tmp = tempfile.mkdtemp(prefix="mpf_newgame_")
    try:
        def path(n):
            return os.path.join(tmp, n)

        def read(n):
            return open(path(n), encoding="utf-8").read() if os.path.exists(path(n)) else None

        def write(n, s):
            with open(path(n), "w", encoding="utf-8", newline="") as f:
                f.write(s)

        def clear():
            for n in os.listdir(tmp):
                os.remove(path(n))

        def fresh_menu(env=""):
            L = lupa.LuaRuntime(unpack_returned_tuples=True)
            L.execute("ENV = { " + env + " }\nDIR = [[" + tmp + "]]")
            L.execute(MENU_MOCK)
            L.execute(m_ng.group(0) + "\nNG = newGame\n")
            return L

        def fresh_auto(env=""):
            L = lupa.LuaRuntime(unpack_returned_tuples=True)
            L.execute("ENV = { MPFEVER_DIR = [[" + tmp + "]], " + env + " }")
            L.execute(AUTO_MOCK)
            L.execute(auto)
            L.execute("H = data()\nfunction ticks(n) for i = 1, n * 30 do H.update() end end")
            return L

        def state():
            s = read("newgame.txt") or ""
            return s.rstrip("\n").split("\t")

        # --- the menu
        print("the menu")
        clear()
        M = fresh_menu()
        ok = M.eval('NG.ask("separate", "Bob", COMMON)')
        st = state()
        check("« New game »: the file says wait, the mode, the player", ok is True and st[0] == "wait" and st[2:4] == ["separate", "Bob"], st)
        check("« New game »: the game's New Game page opens", list(M.eval("PAGES").values()) == ["NewGame map=false"], list(M.eval("PAGES").values()))
        M.execute('app.startGame2("m", "s", "d", 1, 0.5, true, "mods")')
        check("a map editor's start: not ours", state()[0] == "wait", state())
        M.execute('app.loadGame({ saveGameName = "Old one", saveGameNamespace = "save" }, false, "info")')
        check("a savegame loaded: not ours", state()[0] == "wait", state())
        M.execute('app.startGame2("m", "s", "d", 1, 0.5, false, "mods")')
        check("the New Game page starts a game: started", state()[0] == "started", state())
        calls = list(M.eval("CALLS").values())
        check("the game's functions still run, with all their arguments",
              calls == ["startGame2 m true mods", "loadGame Old one false info", "startGame2 m false mods"], calls)
        clear()
        M = fresh_menu()
        M.eval('NG.ask("shared", "Al", COMMON)')
        M.execute('app.loadGame({ saveGameName = "Alps", saveGameNamespace = "map" }, false, "info")')
        check("a saved map loaded by the New Game page: started", state()[0] == "started", state())
        clear()
        M = fresh_menu()
        M.execute('local real = app; app = setmetatable({}, { __index = real, __newindex = function() error("read only") end })')
        M.eval('NG.ask("shared", "Al", COMMON)')
        check("app's functions cannot be wrapped: any (the next game loaded counts)", state()[0] == "any", state())
        clear()
        M = fresh_menu()
        ok = M.eval('NG.ask("shared", "Al", { setPage = function() error("no page") end })')
        check("the New Game page does not open: the file emptied", ok is False and (read("newgame.txt") or "") == "", read("newgame.txt"))

        print("the main page")
        clear()
        M = fresh_menu()
        write("newgame.txt", "saved\t" + str(int(M.eval("os.time()"))) + "\tseparate\tBob\tMPFever 2026-10-31 14h05\n")
        M.execute('SAVED = "MPFever 2026-10-31 14h05"; T0 = NG.take(); if T0 then NG.host(T0) end')
        check("a saved new game taken, the file emptied", M.eval("T0 and T0.save") == "MPFever 2026-10-31 14h05" and read("newgame.txt") == "", read("newgame.txt"))
        check("hosted: its mods for the lobby", read("host_mods.txt") == "a_mod;;b_mod", read("host_mods.txt"))
        reqs = list(M.eval("REQS").values())
        check("hosted: the « host » request (savegame, player, company mode)", reqs == ["host|MPFever 2026-10-31 14h05|Bob|separate"], reqs)
        for st0 in ("wait", "started", "saving", "failed", "any"):
            write("newgame.txt", st0 + "\t" + str(int(M.eval("os.time()"))) + "\tshared\tBob\t\n")
            got = M.eval("NG.take()")
            check(f"'{st0}' when the main page shows: forgotten", got is None and read("newgame.txt") == "", read("newgame.txt"))
        write("newgame.txt", "saved\t" + str(int(M.eval("os.time()")) - 8000) + "\tshared\tBob\tMPFever x\n")
        check("a saved one older than 2 hours: forgotten", M.eval("NG.take()") is None)
        check("no file: nothing", M.eval("NG.take()") is None)

        # --- the application script
        print("mpfever_auto.lua")
        now = int(lupa.LuaRuntime().eval("os.time()"))

        def scenario(first, env="", fail=False, stamp=None):
            clear()
            write("newgame.txt", f"{first}\t{stamp or now}\tseparate\tBob\t\n")
            A = fresh_auto(env)
            A.execute("SAVEFAIL = " + ("true" if fail else "false"))
            A.execute("WAITING, PROGRESS = true, 0.5")
            A.eval("ticks(3)")
            pre = A.eval("STARTED")
            A.execute("PROGRESS = 1")
            A.eval("ticks(1)")
            return A, pre

        A, pre = scenario("started")
        check("the game still loading: not started", pre == 0)
        check("loaded: started (no « press a key »)", A.eval("STARTED") == 1)
        A.eval("ticks(2)")
        check("not saved at once", A.eval("#SAVES") == 0)
        A.eval("ticks(3)")
        name = A.eval("SAVES[1] and SAVES[1].name")
        check("about 2 s later: saved as « MPFever <date> »", A.eval("#SAVES") == 1 and re.match(r"^MPFever \d{4}-\d\d-\d\d \d\dh\d\d$", name or "") is not None, name)
        check("the file says saving with that name", state()[0] == "saving" and state()[4] == name, state())
        A.eval("ticks(3)")
        check("not back to the menu before the save's end", A.eval("STOPS") == 0)
        A.execute("SAVES[1].cb()")
        check("the save done: the file says saved", state()[0] == "saved" and state()[2:5] == ["separate", "Bob", name], state())
        A.eval("ticks(1)")
        check("then back to the main menu, once", A.eval("STOPS") == 1)
        A.eval("ticks(5)")
        check("nothing more", A.eval("STOPS") == 1 and A.eval("#SAVES") == 1 and A.eval("STARTED") == 1)

        A, _ = scenario("any")
        A.eval("ticks(5)")
        check("any: the same", A.eval("STARTED") == 1 and A.eval("#SAVES") == 1)
        A, _ = scenario("started")
        A.eval("ticks(5)")
        A.execute("SAVES[1].cb()")
        write("newgame.txt", "")
        A.eval("ticks(2)")
        check("the player went to the menu already (the file taken): not stopped", A.eval("STOPS") == 0)
        for first, env, stamp, what in (("wait", "", None, "while it says wait (no game started from the page)"),
                                         ("started", "", now - 8000, "a file older than 2 hours"),
                                         ("started", "MPFEVER_NEWGAME = '0'", None, "MPFEVER_NEWGAME=0"),
                                         ("saved", "", None, "already saved")):
            A, _ = scenario(first, env, stamp=stamp)
            A.eval("ticks(8)")
            check(f"{what}: nothing", A.eval("STARTED") == 0 and A.eval("#SAVES") == 0 and A.eval("STOPS") == 0,
                  (A.eval("STARTED"), A.eval("#SAVES"), A.eval("STOPS")))
        clear()
        A = fresh_auto()
        A.execute("WAITING, PROGRESS = true, 1")
        A.eval("ticks(8)")
        check("no file: a game loaded is left alone", A.eval("STARTED") == 0 and A.eval("#SAVES") == 0)
        A, _ = scenario("started", fail=True)
        A.eval("ticks(6)")
        check("a save that fails: « failed », the game stays", state()[0] == "failed" and A.eval("STOPS") == 0, state())

        print("the whole way")
        clear()
        M = fresh_menu()
        M.eval('NG.ask("separate", "Zoe", COMMON)')
        M.execute('app.startGame2("m", "s", "d", 1, 0.5, false, "mods")')
        A = fresh_auto()
        A.execute("WAITING, PROGRESS = true, 1")
        A.eval("ticks(8)")
        A.execute("SAVES[1].cb()")
        A.eval("ticks(1)")
        name = A.eval("SAVES[1].name")
        M2 = fresh_menu()
        M2.execute(f'SAVED = "{name}"; T0 = NG.take(); if T0 then NG.host(T0) end')
        reqs = list(M2.eval("REQS").values())
        check("menu -> script -> menu: the new game hosted", A.eval("STOPS") == 1 and reqs == [f"host|{name}|Zoe|separate"], reqs)

        print("the code")
        check("MPFEVER_NEWGAME=0 hides the button",
              'local newGame = { on = os.getenv("MPFEVER_NEWGAME") ~= "0"' in menu and "newGame.on and button(T(\"Nouvelle partie…\", \"New game…\")" in menu)
        check("the main page takes the file when it shows",
              re.search(r"react\.onMount\(function\(\)\n(?:.*\n){0,6}?\t\t\tlocal ng = newGame\.on and newGame\.take\(\) or nil\n", menu) is not None)
        check("the script's tick in update", "local okN, errN = pcall(newGameTick)" in auto)
        check("no backslash in the menu's and the script's files", chr(92) not in menu and chr(92) not in auto)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{len(fails)} failure(s)" if fails else "\nall passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
