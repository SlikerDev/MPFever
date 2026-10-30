"""Offline test of the lists of entities in an action (0.5.14): a sale of several vehicles (the computer companies' sales)
travels as references, as a single vehicle does, and the owner guard checks every vehicle of the list.

mpfever_refs.lua is loaded whole through lupa (Lua 5.2) for two games whose vehicles have other ids; the owner guard is taken
from the real bridge file (executeActionOnce's block) with C.OWNER_ARGS from mpfever_common.lua. Cases:
  - R.translateOut: each vehicle of a list becomes a reference (its creation key when an action of the session created it),
    R.translateIn on the other game gives that game's vehicles (before: the builder's raw ids, other vehicles there);
    MPFEVER_REFLISTS=0: the raw list, as before; a single vehicle as before; a table that is not a list of numbers untouched;
    a vehicle missing on the other game is reported missing;
  - the owner guard: a list with another company's vehicle is refused on every game (before: a list was never checked, a
    company could sell another's vehicles); a list of its own vehicles passes; MPFEVER_OWNERLISTS=0: not checked, as before.
Run: python tests/test_reflists.py
"""
import os, re, sys

try:
    import lupa.lua52 as lupa
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(HERE, "..", "mod", "mpfever_1", "content")

MOCK = r'''
ENV = {}
os.getenv = function(k) return ENV[k] end
VEH = {}        -- this game's vehicles
api = {
  type = { ComponentType = setmetatable({}, { __index = function(_, k) return k end }) },
  engine = {
    entityExists = function(e) return VEH[e] ~= nil end,
    getComponent = function(e, ct) if ct == "TRANSPORT_VEHICLE" and VEH[e] then return { line = -1 } end return nil end,
    util = { getPlayer = function() return 1 end },
  },
}
'''

GUARD_MOCK = r'''
OWNER = {}      -- vehicle -> owner player entity
LOGS = {}
function log(s) LOGS[#LOGS + 1] = s end
R = { CO = nil, ownerOf = function(e) return OWNER[e] end }
C = { eco = function() return nil end }
'''


def main():
    refs = open(os.path.join(CONTENT, "mpfever_refs.lua"), encoding="utf-8").read()
    bridge = open(os.path.join(CONTENT, "mpfever_bridge.script.lua"), encoding="utf-8").read()
    common = open(os.path.join(CONTENT, "mpfever_common.lua"), encoding="utf-8").read()
    m_guard = re.search(r"^(\t)if a\.co and R\.CO and R\.CO\.mode == \"separate\" and type\(a\.args\) == \"table\" and C\.OWNER_ARGS\[a\.fn\].*?\n\1end\n", bridge, re.S | re.M)
    m_args = re.search(r"^C\.OWNER_ARGS = \{\n.*?^\}\n", common, re.S | re.M)
    if not (m_guard and m_args):
        print("FAIL: the owner guard (bridge) or C.OWNER_ARGS (mpfever_common.lua) not found")
        return 1
    # two games: A sends, B applies (their vehicles of the session have other ids)
    A = lupa.LuaRuntime(unpack_returned_tuples=True)
    B = lupa.LuaRuntime(unpack_returned_tuples=True)
    for g in (A, B):
        g.execute(MOCK)
        g.globals().R = g.execute(refs)
    A.execute("VEH = { [801] = true, [802] = true, [50] = true }")
    B.execute("VEH = { [905] = true, [906] = true, [50] = true }")
    serA = A.eval("function(code) return assert(load(code))() end")
    runB = B.eval("function(code) return assert(load(code))() end")
    fails = []

    def check(name, cond, got=""):
        print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f": {got}" if got != "" else ""))
        if not cond:
            fails.append(name)

    def ship(code, env=""):
        # (game A translates the arguments out, as the interface does when it sends an action; the text is what travels)
        try:
            text = serA(r'''
ENV = {''' + env + r'''}
local rev = { [801] = "harry:3@100", [802] = "harry:4@100" }
local margs = ''' + code + r'''
R.translateOut("makeVehicleSellCmd", margs, rev)
ENV = {}
local function ser(v)
  if type(v) ~= "table" then return type(v) == "string" and string.format("%q", v) or tostring(v) end
  local t = {}
  for k, x in pairs(v) do t[#t + 1] = "[" .. ser(k) .. "]=" .. ser(x) end
  table.sort(t)
  return "{" .. table.concat(t, ",") .. "}"
end
return ser(margs)
''')
            return runB(r'''
local margs = ''' + text + r'''
local missing = R.translateIn(margs, { ["harry:3@100"] = 905, ["harry:4@100"] = 906 })
local a = margs[1]
local s = type(a) == "table" and ("{" .. table.concat((function() local t = {} for i, x in ipairs(a) do t[i] = tostring(x) end return t end)(), ",") .. "}") or tostring(a)
return s .. " missing " .. #missing
''')
        except lupa.LuaError as e:
            return "LUA ERROR " + str(e).splitlines()[0]

    print("R.translateOut / R.translateIn: a list of vehicles")
    got = ship("{ n = 1, [1] = { 801, 802, 50 } }")
    check("each vehicle of the list found on the other game (the session's by their key, the savegame's by id)", got == "{905,906,50} missing 0", got)
    got = ship("{ n = 1, [1] = { 801, 802, 50 } }", 'MPFEVER_REFLISTS = "0"')
    check("MPFEVER_REFLISTS=0: the raw ids, as before", got == "{801,802,50} missing 0", got)
    got = ship("{ n = 1, [1] = 801 }")
    check("a single vehicle, as before", got == "905 missing 0", got)
    got = ship("{ n = 1, [1] = { 801, 'x' } }")
    check("a list that is not only numbers: untouched", got == "{801,x} missing 0", got)
    got = ship("{ n = 1, [1] = {} }")
    check("an empty list: untouched", got == "{} missing 0", got)
    B.execute("VEH[906] = nil")
    got = ship("{ n = 1, [1] = { 801, 802 } }")
    check("a vehicle missing on the other game: reported", got.endswith("missing 1"), got)
    B.execute("VEH[906] = true")

    print("the owner guard")
    G = lupa.LuaRuntime(unpack_returned_tuples=True)
    G.execute(MOCK)
    G.execute(GUARD_MOCK)
    G.globals().CO = G.execute(open(os.path.join(CONTENT, "mpfever_co.lua"), encoding="utf-8").read())
    G.execute("C = C or {}\n" + m_args.group(0))
    G.execute("function guard(a)\n  local result = { success = false }\n" + m_guard.group(0) + "  return nil\nend\n")
    runG = G.eval("function(code) return assert(load(code))() end")

    def guard(code):
        try:
            return runG(code)
        except lupa.LuaError as e:
            return "LUA ERROR " + str(e).splitlines()[0]

    G.execute(r'''
R.CO = CO.new("separate", 100, 2000000)
R.CO.list[2] = { id = 2, key = "bob", name = "Bob Co", color = 2, ent = 200 }
R.CO.list[3] = { id = 3, key = "ai:1", name = "AI", color = 3, ent = 300 }
OWNER = { [801] = 300, [802] = 300, [803] = 200 }
function sell(co, list, env)
  ENV = env or {}
  local r = guard({ co = co, fn = "makeVehicleSellCmd", uid = "x", args = { n = 1, [1] = list } })
  ENV = {}
  return r and ("refused: " .. tostring(r.err)) or "passes"
end
''')
    got = guard("return sell(3, { 801, 802 })")
    check("a list of its own vehicles passes", got == "passes", got)
    got = guard("return sell(3, { 801, 803 })")
    check("a list with another company's vehicle: refused on every game", got.startswith("refused: it belongs to company 2"), got)
    got = guard('return sell(3, { 801, 803 }, { MPFEVER_OWNERLISTS = "0" })')
    check("MPFEVER_OWNERLISTS=0: not checked, as before", got == "passes", got)
    got = guard("return sell(3, 803)")
    check("a single vehicle of another company: refused, as before", got.startswith("refused: it belongs to company 2"), got)
    got = guard('return sell(3, { 801, 803 }, { MPFEVER_NOOWNERGUARD = "1" })')
    check("MPFEVER_NOOWNERGUARD=1: no guard at all", got == "passes", got)

    if fails:
        print(f"FAIL {len(fails)} case(s): {', '.join(fails)}")
        return 1
    print("all cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
