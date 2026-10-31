"""Offline test of the main menu's own load of the host's game (0.6.1, issue #103).

A player changed the game's language in its settings while MPFever waited for the host's game: the game starts its interface
again, and the application script mpfever_auto.lua (started with --script) runs no more. The host's game came in, nobody loaded
it, the player stayed on the main menu "loading" for good. The main page (mpfever_menu.lua) now runs the same loader when the
script has not taken the request within 6 s.

mpfever_auto.lua is run through lupa (Lua 5.2) with a mocked game (app, api) and a real folder for its files; the main page's
timer is taken from the real mpfever_menu.lua. Cases:
  - mpfever_auto.lua run as the game runs it: data() gives the handlers, the chunk returns nothing (as before);
  - required by the menu (package.loaded.mpfever_auto_embed): the handlers returned, no global data() defined;
  - menuTick: the host's game named in menu_state.txt is loaded once (menu_loaded.txt written), not again at the next call;
    a request already taken (menu_loaded.txt) is not loaded again; a state cut in the middle (no "end=1") is not read;
  - the main page's timer: nothing for 6 s (12 calls), then nothing when the application script took the request, else the
    loader's menuTick at every call; another request starts the wait again; not "loading": nothing; MPFEVER_MENULOAD=0:
    never.
Run: python tests/test_menuload.py
"""
import os, re, shutil, sys, tempfile

try:
    import lupa.lua52 as lupa
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(HERE, "..", "mod", "mpfever_1", "content")

MOCK = r'''
ENV = ENV or {}
os.getenv = function(k) return ENV[k] end
LOADS = {}
print = function() end
local function ud(t) return t end
api = { type = {
  SavegameId = { new = function() return {} end },
  SaveGameDetails = { new = function(info) return { info = info } end },
  ModId = { new = function() return {} end },
} }
app = {
  SaveGameNamespace = { getSavegame = function() return "ns" end },
  findAllSavegames = function() return { { saveName = "MPFever resync Balle", path = "p/a.sav", timestamp = 2 },
                                         { saveName = "Other", path = "p/b.sav", timestamp = 1 } } end,
  getSavegameInfo = function(id) return { isCompleted = function() return true end,
    get = function() return { info = { mods = { { name = "mpfever_1" } }, metadata = { gameModDescs = {} } } } end } end,
  loadGame = function(id, editor, details) LOADS[#LOADS + 1] = id.saveGameName end,
  getUserProfile = function() return { getModRep = function() return { exists = function() return true end } end } end,
  isWaitForStartReadyGame = function() return false end,
}
'''

fails = []


def check(name, cond, got=""):
    print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f": {got}" if got != "" and not cond else ""))
    if not cond:
        fails.append(name)


def main():
    auto = open(os.path.join(CONTENT, "mpfever_auto.lua"), encoding="utf-8").read()
    menu = open(os.path.join(CONTENT, "mpfever_menu.lua"), encoding="utf-8").read()
    m_timer = re.search(r"^\t\tlocal autoWait = react\.useRef\(nil\)\n(\t\treact\.onStepTimer\(function\(\)\n.*?^\t\tend, 0\.5\)\n)", menu, re.S | re.M)
    if not m_timer:
        print("FAIL: the main page's load timer not found in mpfever_menu.lua")
        return 1
    tmp = tempfile.mkdtemp(prefix="mpf_menuload_")
    try:
        def fresh(env_dir=True):
            L = lupa.LuaRuntime(unpack_returned_tuples=True)
            L.execute("ENV = { MPFEVER_DIR = " + ("[[" + tmp + "]]" if env_dir else "nil") + " }")
            L.execute(MOCK)
            return L

        def write(name, text):
            with open(os.path.join(tmp, name), "w", encoding="utf-8", newline="") as f:
                f.write(text)

        def read(name):
            p = os.path.join(tmp, name)
            return open(p, encoding="utf-8").read() if os.path.exists(p) else None

        def clear():
            for n in os.listdir(tmp):
                os.remove(os.path.join(tmp, n))

        # --- run as the game runs it
        L = fresh()
        ret = L.execute(auto)
        check("as the application script: the chunk returns nothing", ret is None, ret)
        check("as the application script: data() gives the handlers with menuTick",
              L.eval("type(data) == 'function' and type(data().update) == 'function' and type(data().menuTick) == 'function'"))
        # --- required by the menu
        L = fresh()
        L.execute("package.loaded.mpfever_auto_embed = true")
        A = L.execute(auto)
        check("required by the menu: the handlers returned", A is not None and L.eval("function(a) return type(a.menuTick) end")(A) == "function")
        check("required by the menu: no global data()", L.eval("data") is None)

        # --- menuTick
        clear()
        write("menu_state.txt", "phase=loading\nload=MPFever resync Balle\nloadSeq=r1-639\nend=1\n")
        tick = L.eval("function(a) return a.menuTick() end")
        tick(A)
        tick(A)
        tick(A)
        loads = list(L.eval("LOADS").values())
        check("#103: the host's game loaded by the menu", loads == ["MPFever resync Balle"], loads)
        check("menu_loaded.txt names the request", read("menu_loaded.txt") == "r1-639", read("menu_loaded.txt"))
        tick(A)
        check("not loaded twice", len(list(L.eval("LOADS").values())) == 1, list(L.eval("LOADS").values()))

        L = fresh(); L.execute("package.loaded.mpfever_auto_embed = true"); A = L.execute(auto)
        clear()
        write("menu_state.txt", "phase=loading\nload=MPFever resync Balle\nloadSeq=r1-639\nend=1\n")
        write("menu_loaded.txt", "r1-639")
        tick = L.eval("function(a) return a.menuTick() end")
        tick(A); tick(A)
        check("a request the application script took: not loaded again", len(list(L.eval("LOADS").values())) == 0)

        L = fresh(); L.execute("package.loaded.mpfever_auto_embed = true"); A = L.execute(auto)
        clear()
        L.eval("function(a) return a.menuTick() end")(A)      # (a whole state read once)
        write("menu_state.txt", "phase=idle\nend=1\n")
        L.eval("function(a) return a.menuTick() end")(A)
        write("menu_state.txt", "phase=loading\nload=MPFever resync Ba")
        L.eval("function(a) return a.menuTick() end")(A)
        check("a state cut in the middle: not read", len(list(L.eval("LOADS").values())) == 0, list(L.eval("LOADS").values()))

        # --- the main page's timer
        T = lupa.LuaRuntime(unpack_returned_tuples=True)
        T.execute(r'''
          ENV = {}
          os.getenv = function(k) return ENV[k] end
          DIR, IO = "dir", {}
          STATE, FILES, LOGS, TICKS, REQS = {}, {}, {}, 0, 0
          function readState() local c = {} for k, v in pairs(STATE) do c[k] = v end return c end
          function readFile(n) return FILES[n] end
          function log(s) LOGS[#LOGS + 1] = s end
          LOADER = { menuTick = function() TICKS = TICKS + 1 end }
          require = function(name) REQS = REQS + 1; assert(package.loaded.mpfever_auto_embed == true); return LOADER end
          react = { useRef = function(v) local r = { v = v } return { get = function() return r.v end, set = function(_, x) r.v = x end } end,
                    onStepTimer = function(fn) TIMER = fn end }
        ''')
        T.execute("local autoWait = react.useRef(nil)\n" + m_timer.group(1).replace("\t\t", "", 1))
        step = T.eval("function(n) for i = 1, n do TIMER() end return TICKS end")

        T.execute("STATE = { phase = 'loading', load = 'MPFever resync Balle', loadSeq = 'r1' }")
        got = step(12)
        check("the main page waits 6 s", got == 0, got)
        got = step(3)
        check("#103: then the loader at every call", got == 3, got)
        check("the flag of the menu's require put back", T.eval("package.loaded.mpfever_auto_embed") is None)
        check("no global created by the main page (the game forbids it)", not any("creating globals" in str(x) for x in T.eval("LOGS").values()))
        check("one line in the log", sum(1 for s in T.eval("LOGS").values() if "within 6 s" in s) == 1, list(T.eval("LOGS").values()))

        T.execute("STATE.loadSeq = 'r2'; TICKS = 0; FILES['menu_loaded.txt'] = 'r2'")
        got = step(20)
        check("the application script took it: the main page does nothing", got == 0, got)

        T.execute("STATE.loadSeq = 'r3'; TICKS = 0")
        got = step(11)
        check("another request: the wait starts again", got == 0, got)
        T.execute("STATE.phase = 'idle'")
        got = step(20)
        check("not loading: nothing", got == 0, got)

        T.execute("STATE = { phase = 'loading', load = 'X', loadSeq = 'r4' }; TICKS = 0; ENV.MPFEVER_MENULOAD = '0'")
        got = step(30)
        check("MPFEVER_MENULOAD=0: never", got == 0, got)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{len(fails)} failure(s)" if fails else "\nall passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
