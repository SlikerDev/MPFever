"""Offline test of the owner of an upgraded street in a replay (0.6.2, issue #104).

One company per player: a player upgraded another company's street. replaceSegment, which the replays start from, keeps the old
segment's owner, while the tool's segment has an owner of its own or none (then the engine makes it nobody's): the builder's game
and the others disagreed on who owns it (owners out of sync, a reload). The replay now gives the engine's segment the tool's
owner, or none. In game: the autotest upgowner (n31kit u1) went out of sync on owners before, in sync after.

G.stepOwner and upgradePlan's owner line are taken from the real bridge file and run through lupa (Lua 5.2) with mocks. Cases:
  - the tool's owner differs: the replay's segment gets it;
  - the tool's segment has no owner: the replay's segment has none (a new segment with the rest of the fields);
  - the same owner, or nobody's on both: the segment is left as it is;
  - MPFEVER_UPGOWNER=0, or no owner known (step.owner nil): replaceSegment's owner, as before;
  - upgradePlan notes the tool's owner, false for none.
Run: python tests/test_upgowner.py
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
LOGS = {}
function log(s) LOGS[#LOGS + 1] = s end
G = {}
C = { newOf = function(kind) return { __kind = kind } end }
function seg(owner) return { entity = -1, type = 0, comp = { node0 = 1, node1 = 2 }, streetEdge = { p = 2 },
  playerOwned = owner and { player = owner } or nil } end
'''

fails = []


def check(name, cond, got=""):
    print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f": {got}" if got != "" and not cond else ""))
    if not cond:
        fails.append(name)


def main():
    src = open(BRIDGE, encoding="utf-8").read()
    m = re.search(r"^G\.stepOwner = function\(a, step, seg\)\n.*?^end\n", src, re.S | re.M)
    m_plan = re.search(r"^\t\tlocal owner = type\(ad\.playerOwned\) == \"table\".*\n", src, re.M)
    if not (m and m_plan):
        print("FAIL: G.stepOwner or upgradePlan's owner line not found in the bridge")
        return 1
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute(MOCK)
    L.execute(m.group(0))
    run = L.eval("function(code) return assert(load(code))() end")
    A = "local a = { uid = 'Kev#2:10' } "

    got = run(A + "local s = G.stepOwner(a, { edge = 61461, owner = 200 }, seg(100)); return s.playerOwned.player")
    check("#104: the tool's owner (another company) given to the replay's segment", got == 200, got)
    got = run(A + "local s = G.stepOwner(a, { edge = 47348, owner = false }, seg(100)); return tostring(s.playerOwned) .. ' ' .. s.__kind .. ' ' .. s.comp.node1 .. ' ' .. s.streetEdge.p")
    check("#104: the tool's segment has no owner: none on the replay's (the other fields kept)", got == "nil SegmentAndEntity 2 2", got)
    got = run(A + "local s0 = seg(100); local s = G.stepOwner(a, { edge = 1, owner = 100 }, s0); return s == s0 and #LOGS")
    check("the same owner: left as it is (nothing logged)", got == 2, got)
    got = run(A + "local s0 = seg(nil); local s = G.stepOwner(a, { edge = 1, owner = false }, s0); return s == s0")
    check("nobody's on both: left as it is", got is True, got)
    got = run(A + "local s = G.stepOwner(a, { edge = 1 }, seg(100)); return s.playerOwned.player")
    check("no owner known (step.owner nil): replaceSegment's owner", got == 100, got)
    run("ENV.MPFEVER_UPGOWNER = '0'")
    got = run(A + "local s = G.stepOwner(a, { edge = 1, owner = 200 }, seg(100)); return s.playerOwned.player")
    check("MPFEVER_UPGOWNER=0: replaceSegment's owner, as before", got == 100, got)
    run("ENV.MPFEVER_UPGOWNER = nil")
    check("the change is logged", any("owner 100 -> 200 (the tool's)" in str(x) for x in L.eval("LOGS").values()))

    line = m_plan.group(0).strip()
    f = L.eval("function(line) return assert(load('return function(ad) ' .. line .. ' return owner end'))() end")(line)
    check("upgradePlan: the tool's owner noted", L.eval("function(f) return f({ playerOwned = { player = 25898 } }) end")(f) == 25898)
    check("upgradePlan: false for a segment without an owner", L.eval("function(f) return f({}) end")(f) is False)

    print(f"\n{len(fails)} failure(s)" if fails else "\nall passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
