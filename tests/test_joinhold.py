"""Offline test of the company join's hold (0.5.14, one company per player): a company join that is due holds the game until
it is applied (released before, a batch of steps could run first and the host created the joining company 4 or 5 steps late,
with other entity ids than the other games: drifts later; night tests x2 and x4 of 0.5.13).

nativeHoldAt is taken from the real bridge file with the line that reads its switch, and run through lupa (Lua 5.2) with a
mocked state. Cases: a due join (gathered, its turn) holds at the game's time; a join still gathering holds (as before); a
join not due yet is only a stop point ahead; MPFEVER_JOINHOLD=0 (read at the start): a due join no longer holds, as before;
nothing queued: no hold.
Run: python tests/test_joinhold.py
"""
import os, re, sys

try:
    import lupa.lua52 as lupa
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(HERE, "..", "mod", "mpfever_1", "content", "mpfever_bridge.script.lua")

MOCK = r'''
ENV = {}
os.getenv = function(k) return ENV[k] end
STEP = 200
NOW = 100000
LOGS = {}
function gameTime() return NOW end
function overshootReserve() return 2 end
function log(s) LOGS[#LOGS + 1] = s end
O = { steps = true }
K = { JOIN_GATHER = 60 }
G = { frames = 5000, natRelease = {}, natWait = {}, simStill = function() return true end, joinTurn = function(a) return true end }
'''


def main():
    src = open(BRIDGE, encoding="utf-8").read()
    m_sw = re.search(r"^G\.joinHoldDue = .*\n", src, re.M)
    m_fn = re.search(r"^local function nativeHoldAt\(\)\n.*?^end\n", src, re.S | re.M)
    if not m_fn:
        print("FAIL: nativeHoldAt not found in the bridge")
        return 1
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute(MOCK)
    L.execute(m_fn.group(0).replace("local function nativeHoldAt", "function nativeHoldAt", 1))
    sw = m_sw.group(0) if m_sw else "G.joinHoldDue = nil\n"
    lua_run = L.eval("function(code) local f = assert(load(code)) return f() end")

    def run(code):
        # (a Lua error is a result too: the case that gets it fails, the others still run)
        try:
            return lua_run(code)
        except lupa.LuaError as e:
            return "LUA ERROR " + str(e).splitlines()[0]

    fails = []

    def check(name, cond, got=""):
        print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f": {got}" if got != "" else ""))
        if not cond:
            fails.append(name)

    # (the switch is read once, when the bridge starts: as every game reads it)
    run("ENV = {}\n" + sw)
    run(r'''
function hold(queue)
  G.nativeQueue = queue
  return tostring(nativeHoldAt())
end
''')
    check("nothing queued: no hold", run("return hold({})") == "nil")
    got = run("return hold({ { fn = 'mpfCoJoin', uid = 'x:1', at = NOW - 200, recvFrame = 100 } })")
    check("a due join, gathered and its turn: holds at the game's time", got == "100000", got)
    check("and says so once", sum("holds the game" in str(s) for s in L.globals().LOGS.values()) == 1)
    got = run("return hold({ { fn = 'mpfCoJoin', uid = 'x:2', at = NOW - 200, recvFrame = G.frames - 10 } })")
    check("a join still gathering the others: holds, as before", got == "100000", got)
    got = run("return hold({ { fn = 'mpfCoJoin', uid = 'x:3', at = NOW + 2000, recvFrame = 100 } })")
    check("a join not due yet: a stop point at its time", got == "102000", got)
    got = run("return hold({ { fn = 'makeVehicleBuyCmd', uid = 'x:4', at = NOW - 200 } })")
    check("another due action: no hold here", got == "nil", got)
    run('ENV = { MPFEVER_JOINHOLD = "0" }\n' + sw + "ENV = {}")
    got = run("return hold({ { fn = 'mpfCoJoin', uid = 'x:5', at = NOW - 200, recvFrame = 100 } })")
    check("MPFEVER_JOINHOLD=0: a due join no longer holds, as before", got == "nil", got)

    if fails:
        print(f"FAIL {len(fails)} case(s): {', '.join(fails)}")
        return 1
    print("all cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
