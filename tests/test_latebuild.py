"""Offline test of G.lateSkip (issue #96): another game's build that comes too late is left unbuilt only when this game
already built something at a later step (its own build or another replay), and the host's game is then reloaded.

The function is taken from the real bridge file and run through lupa (Lua 5.2) with a mocked G, log, replayFailed and
os.getenv. Cases: a build on time, a late one with nothing built since, a late one after an own build (shipped, or
released and not shipped yet), two late builds of one step (both built), a company join, MPFEVER_LATERESYNC=0, and the
chat notice when the host's game is the one that leaves a build out.
Run: python MPFever/tests/test_latebuild.py
"""
import os, re, sys
import lupa.lua52 as lupa

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(HERE, "..", "mod", "mpfever_1", "content", "mpfever_bridge.script.lua")


def main():
    src = open(BRIDGE, encoding="utf-8").read()
    m = re.search(r"^function G\.lateSkip\(a, now\)\n.*?^end\n", src, re.S | re.M)
    if not m:
        print("FAIL: G.lateSkip not found in the bridge")
        return 1
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute(r'''
ENV = {}
os = { getenv = function(k) return ENV[k] end }
G = {}
C = { ROLE = "client", Tf = function(fr, en, ...) return string.format(en, ...) end }
LOGS, FAILED, SAID = {}, {}, {}
function G.coSay(t) SAID[#SAID + 1] = t end
function log(s) LOGS[#LOGS + 1] = s end
function replayFailed(a, why) FAILED[#FAILED + 1] = tostring(a.uid) .. ": " .. why end
''')
    L.execute(m.group(0))
    L.execute(r'''
function case(builtAt, ship, at, now, fn, env, role)
  G.builtAt, G.natShipIds = builtAt, ship or {}
  ENV = env or {}
  C.ROLE = role or "client"
  FAILED, SAID = {}, {}
  local r = G.lateSkip({ uid = "harry:1", origin = "harry", at = at, fn = fn or "makeBuildCmd" }, now)
  return r, #FAILED, #SAID
end
''')
    case = L.globals().case
    fails = []

    def check(name, got, want):
        ok = got == want
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {got}")
        if not ok:
            fails.append(name)

    # on time: never left out, whatever was built here
    check("on time", case(9600, None, 9600, 9600), (False, 0, 0))
    check("ahead of this game", case(9800, None, 9800, 9600), (False, 0, 0))
    # late, nothing built here since its step: built as before
    check("late, nothing since", case(9400, None, 9560, 9634), (False, 0, 0))
    check("late, nothing ever", case(None, None, 9560, 9634), (False, 0, 0))
    # late after an own build of a later step (issue #96: nathan#1:22 at 9620 before harry:111 of 9604): left out, resync asked
    check("late after a shipped build", case(9620, None, 9604, 9634), (True, 1, 0))
    # an own build released and not shipped yet, at a later step that this game reached
    lt = L.eval("function(t) local r = {} for i, x in ipairs(t) do r[i] = { at = x } end return r end")
    check("late after a released build", case(None, lt(L.table(9610)), 9604, 9634), (True, 1, 0))
    check("released one not reached yet", case(None, lt(L.table(9700)), 9604, 9634), (False, 0, 0))
    check("released one of an earlier step", case(None, lt(L.table(9500)), 9604, 9634), (False, 0, 0))
    # two late builds of one step: the first built here sets builtAt to its own step, the second of that step is built too
    check("second build of the same step", case(9604, None, 9604, 9634), (False, 0, 0))
    # a company join is never left out here (it has its own hold)
    check("company join", case(9620, None, 9604, 9634, "mpfCoJoin"), (False, 0, 0))
    # the switch back to the old behaviour
    check("MPFEVER_LATERESYNC=0", case(9620, None, 9604, 9634, None, L.table_from({"MPFEVER_LATERESYNC": "0"})), (False, 0, 0))
    # the host's game that leaves a build out says so in the chat (the build is gone on every game after the reload)
    check("host leaves it out, says so", case(9620, None, 9604, 9634, None, None, "host"), (True, 1, 1))
    check("host, nothing since", case(9400, None, 9560, 9634, None, None, "host"), (False, 0, 0))
    if fails:
        print(f"FAIL {len(fails)} case(s): {', '.join(fails)}")
        return 1
    print("all cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
