"""Offline test of the 0.6.1 fixes for the reloads of issues #101 and #102 (players in different game languages, and builds in
a pause).

C.buildSig is taken from mpfever_common.lua, valueHash and the capture's "engine applies it again" block from the real bridge
file, and run through lupa (Lua 5.2). Cases:
  - C.buildSig: two constructions of the same pause (same game time, one construction each) have different signatures when
    their file or place differ (before: "0/0/0/0/0/0/0/0/1/0" for both, the second was not shipped, #102); the same
    construction gives the same signature, from the shipped arguments as from the capture; MPFEVER_SIGCON=0: counts only;
  - the capture's block: a build that matches an action just applied is not shipped, and only once (a second one alike at
    that time is the player's own and is shipped); another construction at that time is shipped;
  - valueHash: the subsidies' state hashes the same with the title in English and in German, and still differs when
    something else differs; other scripts still hash their "name" texts; MPFEVER_SUBNAMES=1: hashed as before;
  - the launcher: "names" is a part the games correct from the host (no reload), MPFEVER_NAMESCHECK=1 keeps it a reason.
Run: python tests/test_langdesync.py
"""
import os, re, sys

try:
    import lupa.lua52 as lupa
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
CONTENT = os.path.join(ROOT, "mod", "mpfever_1", "content")

MOCK = r'''
ENV = {}
os.getenv = function(k) return ENV[k] end
LOGS = {}
function log(s) LOGS[#LOGS + 1] = s end
C = {}
-- (the hash of the real mpfever_common.lua is not needed: any string hash that differs on different texts)
function C.hashStr(seed, s)
  local h = seed % 4294967296
  s = tostring(s)
  for i = 1, #s do h = (h * 31 + s:byte(i)) % 4294967296 end
  return h
end
function C.int(v) return string.format("%d", v) end
state = { set = function() end }
function con(file, x, y)
  return { proposal = { addedNodes = {}, addedSegments = {} }, toAdd = { { fileName = file, params = {},
    transf = { 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, 10, 1 } } }, toRemove = {} }
end
'''

fails = []


def check(name, cond, got=""):
    print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f": {got}" if got != "" and not cond else ""))
    if not cond:
        fails.append(name)


def main():
    common = open(os.path.join(CONTENT, "mpfever_common.lua"), encoding="utf-8").read()
    bridge = open(os.path.join(CONTENT, "mpfever_bridge.script.lua"), encoding="utf-8").read()
    mainform = open(os.path.join(ROOT, "launcher", "MainForm.cs"), encoding="utf-8").read()
    m_sig = re.search(r"^function C\.buildSig\(m\)\n.*?^end\n", common, re.S | re.M)
    m_vh = re.search(r"^local function valueHash\(v, d, noName\)\n.*?^end\n", bridge, re.S | re.M)
    m_blk = re.search(r"^\tdo\n\t\tlocal okg, sig = pcall\(C\.buildSig, compact\)\n.*?^\tend\n", bridge, re.S | re.M)
    m_call = re.search(r"valueHash\(c\.state, 0, (.*?)\)\)\n", bridge)
    if not (m_sig and m_vh and m_blk and m_call):
        print("FAIL: C.buildSig, valueHash, the capture's block or the scripts' hash call not found")
        return 1
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute(MOCK)
    L.execute(m_sig.group(0))
    L.execute(m_vh.group(0) + "\nVH = valueHash\n")
    # the capture's block, as a function: "kept" when it returned (not shipped), "shipped" when it went on
    L.execute("function CAPTURE(st, compact, now)\n" + m_blk.group(0) + "\treturn 'shipped'\nend\n")
    # the call of extendedParts, with the script's name
    L.execute("function SCRIPTHASH(name, state) return tostring(VH(state, 0, " + m_call.group(1) + ")) end")
    run = L.eval("function(code) return assert(load(code))() end")

    # --- C.buildSig
    a = run("return C.buildSig(con('station/street/bus_stop.con', 762, -136))")
    b = run("return C.buildSig(con('depot/road_depot.con', 936, -152))")
    a2 = run("return C.buildSig(con('station/street/bus_stop.con', 762, -136))")
    c = run("return C.buildSig(con('station/street/bus_stop.con', 500, 20))")
    check("two constructions of a pause: different signatures", a != b, f"{a} / {b}")
    check("the same construction at another place: different", a != c, f"{a} / {c}")
    check("the same construction: the same signature", a == a2, f"{a} / {a2}")
    check("the signature names the file and place", "bus_stop.con@762,-136" in str(a), a)
    st = run("return C.buildSig({ proposal = { addedNodes = { 1, 2 }, addedSegments = { 3 } }, toAdd = {}, toRemove = {} })")
    check("a street build: counts only (no construction)", st == "2/0/1/0/0/0/0/0/0/0", st)
    run("ENV.MPFEVER_SIGCON = '0'")
    a0 = run("return C.buildSig(con('station/street/bus_stop.con', 762, -136))")
    b0 = run("return C.buildSig(con('depot/road_depot.con', 936, -152))")
    check("MPFEVER_SIGCON=0: counts only, as before", a0 == b0 == "0/0/0/0/0/0/0/0/1/0", f"{a0} / {b0}")
    run("ENV.MPFEVER_SIGCON = nil")

    # --- the capture's block
    r = run("""
      local st = { replaySigs = { at = 433000, list = { C.buildSig(con('station/street/bus_stop.con', 762, -136)) } } }
      local first = CAPTURE(st, con('depot/road_depot.con', 936, -152), 433000)
      return first""")
    check("#102: another player's station at the same paused time, then this player's depot: shipped", r == "shipped", r)
    r = run("""
      local st = { replaySigs = { at = 433000, list = { C.buildSig(con('station/street/bus_stop.con', 762, -136)) } } }
      local first = CAPTURE(st, con('station/street/bus_stop.con', 762, -136), 433000)
      local second = CAPTURE(st, con('station/street/bus_stop.con', 762, -136), 433000)
      return tostring(first) .. "," .. tostring(second)""")
    check("the engine's second application: not shipped, once only", r == "nil,shipped", r)
    r = run("""
      local st = { replaySigs = { at = 433000, list = { C.buildSig(con('station/street/bus_stop.con', 762, -136)) } } }
      local got = CAPTURE(st, con("station/street/bus_stop.con", 762, -136), 433200)
      return tostring(got)""")
    check("another game time: shipped", r == "shipped", r)
    run("ENV.MPFEVER_SIGCON = '0'")
    r = run("""
      local st = { replaySigs = { at = 433000, list = { C.buildSig(con('station/street/bus_stop.con', 762, -136)) } } }
      local got = CAPTURE(st, con('depot/road_depot.con', 936, -152), 433000)
      return tostring(got)""")
    check("MPFEVER_SIGCON=0: the depot taken for the station, as before (the bug)", r == "nil", r)
    run("ENV.MPFEVER_SIGCON = nil")

    # --- the subsidies' hash
    sub = """
      local function s(title, amount) return { version = 2, activeSubventions = { { id = '::/x/deliver_workers.res', uid = 92070,
        data = { name = title, upfront = { { type = 'Money', params = { amount = amount } } } } } } } end
      return SCRIPTHASH('subventions', s(%s, %s))"""
    en = run(sub % ("'Transport Workers'", "4990000"))
    de = run(sub % ("'Arbeiter transportieren'", "4990000"))
    other = run(sub % ("'Transport Workers'", "5000000"))
    check("#102: a subsidy titled in English and in German: the same hash", en == de, f"{en} / {de}")
    check("a subsidy with another amount: another hash", en != other, f"{en} / {other}")
    tw = "return SCRIPTHASH('towns', { townStates = { { name = %s, score = 1 } } })"
    check("another script: its 'name' texts still counted", run(tw % "'A'") != run(tw % "'B'"))
    run("ENV.MPFEVER_SUBNAMES = '1'")
    en1 = run(sub % ("'Transport Workers'", "4990000"))
    de1 = run(sub % ("'Arbeiter transportieren'", "4990000"))
    check("MPFEVER_SUBNAMES=1: the titles hashed, as before", en1 != de1, f"{en1} / {de1}")
    run("ENV.MPFEVER_SUBNAMES = nil")

    # --- the launcher: "names" corrected from the host, not a reason to reload
    m_cp = re.search(r"static readonly HashSet<string> CorrectedParts = (.*?);\n", mainform, re.S)
    cp = m_cp.group(1) if m_cp else ""
    check("#101: \"names\" among the parts corrected from the host", re.search(r'\{ "money", "names" \}', cp) is not None, cp)
    check("MPFEVER_NAMESCHECK=1: money only, as before",
          'GetEnvironmentVariable("MPFEVER_NAMESCHECK") == "1"' in cp and re.search(r'\? new HashSet<string> \{ "money" \}', cp) is not None, cp)

    print(f"\n{len(fails)} failure(s)" if fails else "\nall passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
