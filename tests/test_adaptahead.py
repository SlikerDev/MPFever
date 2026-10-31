"""Offline test of the launcher's "Slow PC mode" (MPFEVER_ADAPTAHEAD, 0.6.2, issue #104).

Its text says it gives builds more room when the PC is very busy; it shortened the stamp distance instead (down to 60 %), and
a host with it on had builds arriving with no step to spare. adaptAhead is taken from the real bridge file and run through
lupa (Lua 5.2). Cases:
  - nothing set: the full distance;
  - MPFEVER_ADAPTAHEAD=1 (Slow PC mode): a third more room, whatever the margins seen;
  - MPFEVER_ADAPTAHEAD=short: shortened from the margins seen, never below 60 %, the full distance once an action came late
    (G.aheadLocked) or before 8 margins are known: as before.
Run: python tests/test_adaptahead.py
"""
import os, re, sys

try:
    import lupa.lua52 as lupa
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

BRIDGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mod", "mpfever_1", "content", "mpfever_bridge.script.lua")
fails = []


def check(name, cond, got=""):
    print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f": {got}" if got != "" and not cond else ""))
    if not cond:
        fails.append(name)


def main():
    src = open(BRIDGE, encoding="utf-8").read()
    m = re.search(r"^local function adaptAhead\(base\)\n.*?^end\n", src, re.S | re.M)
    if not m:
        print("FAIL: adaptAhead not found in the bridge")
        return 1
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute("ENV = {}; os.getenv = function(k) return ENV[k] end; G = { consumed = {} }")
    L.execute(m.group(0) + "\nAA = adaptAhead\n")
    run = L.eval("function(code) return assert(load(code))() end")
    check("nothing set: the full distance", run("return AA(16)") == 16)
    run("G.consumed = { 1, 1, 1, 1, 1, 1, 1, 1 }")
    check("nothing set, small margins seen: still the full distance", run("return AA(16)") == 16)
    run("ENV.MPFEVER_ADAPTAHEAD = '1'")
    check("#104: Slow PC mode gives more room (16 -> 22)", run("return AA(16)") == 22, run("return AA(16)"))
    check("Slow PC mode at x1 (7 -> 10)", run("return AA(7)") == 10, run("return AA(7)"))
    run("ENV.MPFEVER_ADAPTAHEAD = 'short'")
    check("short: shortened from the margins seen, not below 60 %", run("return AA(16)") == 10, run("return AA(16)"))
    run("G.aheadLocked = true")
    check("short: the full distance once an action came late", run("return AA(16)") == 16)
    run("G.aheadLocked = nil; G.consumed = { 1, 1 }")
    check("short: the full distance before 8 margins are known", run("return AA(16)") == 16)
    print(f"\n{len(fails)} failure(s)" if fails else "\nall passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
