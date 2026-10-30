"""Offline test of the start money of 0.5.14 (one company per player): the host's company at a new game, a new company's own
start money (a player's, a computer company's).

SIM.coStartCanon, coApply and coCreate are taken from the real bridge file and run through lupa (Lua 5.2) with
mpfever_co.lua and a mocked engine. Cases:
  - SIM.coStartCanon: the savegame's company takes the start money of every company (booked as the difference with its
    money), once, only when it has nothing yet: a vehicle, a line or (review fix) a loan of its own and it keeps its money
    (a map prepared with borrowed money lost the money and kept the debt); MPFEVER_SHARESWITCH=0: nothing, as before;
  - coApply: the registry made by the first join calls it with the join's start money; a new company keeps its join's start
    money (c.start: the players' value of the session or a computer company's own), floored, never under 0; a known company
    is not touched; MPFEVER_SHARESWITCH=0: none;
  - coCreate (the interface, once the engine made the company's player entity): the company's own start money booked, else
    the registry's; 0 books nothing.
Run: python tests/test_costart.py
"""
import os, re, sys

try:
    import lupa.lua52 as lupa
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(HERE, "..", "mod", "mpfever_1", "content")
BRIDGE = os.path.join(CONTENT, "mpfever_bridge.script.lua")

MOCK = r'''
ENV = {}
os.getenv = function(k) return ENV[k] end
OWN = {}          -- vehicle -> owner player entity
LINES = {}        -- player entity -> its lines
BAL = {}          -- player entity -> money
LOANS = nil       -- the loan script's state (obtainedLoans)
BOOKED, LOGS, STARTS = {}, {}, {}
api = {
  type = {
    ComponentType = { PLAYER_OWNED = "po", GAME_SCRIPT = "gs", ACCOUNT = "acc" },
    JournalEntry = { new = function() return { category = {} } end, Type = { OTHER = 1 } },
    Vec3f = { new = function(x, y, z) return { x, y, z } end },
  },
  engine = {
    getComponent = function(e, ct)
      if ct == "po" then return OWN[e] and { player = OWN[e] } or nil end
      if ct == "gs" then return e == 900 and { state = LOANS } or nil end
      if ct == "acc" then return BAL[e] and { balance = BAL[e] } or nil end
      return nil
    end,
    util = { getPlayer = function() return 100 end },
    system = {
      lineSystem = { getLinesForPlayer = function(p) if LINES == "error" then error("no line system") end return LINES[p] or {} end },
      gameScriptSystem = { getEntityForGameScript = function(name) return name == "loan.gs" and 900 or -1 end },
    },
  },
  cmd = {
    makeJournalBookAssetCmd = function(ent, e) return { kind = "book", ent = ent, amount = e.amount, type = e.category.type, time = e.time } end,
    sendCommand = function(c) BOOKED[#BOOKED + 1] = c end,
    makeEntitySetColorCmd = function() return { kind = "color" } end,
    makeGameAddPlayerCmd = function(name, col) return { kind = "addplayer", name = name } end,
  },
}
GAME_SCRIPTS = { loan = "loan.gs" }
C = { marshal = function(v) return v end }
R = { entitiesWith = function(k) local r = {} for v in pairs(OWN) do r[#r + 1] = v end table.sort(r) return r end }
SIM = {}
G = { frames = 0 }
function log(s) LOGS[#LOGS + 1] = s end
function shortErr(e) return tostring(e) end
function coIsLoanEvent() return false end
function installSimPlayer() end
function toSim() end
-- (the engine answers a command at once here)
function replaySend(cmd, cb) BOOKED[#BOOKED + 1] = cmd; if cmd.kind == "addplayer" then cb({ resultEntity = 300 }, true) end end
'''


def main():
    src = open(BRIDGE, encoding="utf-8").read()
    m_canon = re.search(r"^SIM\.coStartCanon = function\(st, start\)\n.*?^end\n", src, re.S | re.M)
    m_apply = re.search(r"^local function coApply\(st, a\)\n.*?^end\n", src, re.S | re.M)
    m_create = re.search(r"^local function coCreate\(b, c\)\n.*?^end\n", src, re.S | re.M)
    if not (m_canon and m_apply and m_create):
        print("FAIL: SIM.coStartCanon, coApply or coCreate not found in the bridge")
        return 1
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute(MOCK)
    L.globals().CO = L.execute(open(os.path.join(CONTENT, "mpfever_co.lua"), encoding="utf-8").read())
    L.execute(m_canon.group(0))
    L.execute("REAL_CANON = SIM.coStartCanon")
    L.execute(m_apply.group(0).replace("local function coApply", "function coApply", 1))
    L.execute(m_create.group(0).replace("local function coCreate", "function coCreate", 1))
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

    run(r'''
function canon(start, setup)
  OWN, LINES, BAL, LOANS, BOOKED, ENV = {}, {}, { [100] = 0 }, nil, {}, {}
  if setup then setup() end
  local st = { co = CO.new("separate", 100, 2000000) }
  REAL_CANON(st, start)
  local t = {}
  for _, b in ipairs(BOOKED) do t[#t + 1] = b.ent .. ":" .. b.amount end
  return table.concat(t, ",")
end
''')
    print("SIM.coStartCanon")
    check("a new game, nothing owned: the start money booked", run("return canon(2000000)") == "100:2000000")
    check("booked as the difference with its money", run("return canon(2000000, function() BAL[100] = 500000 end)") == "100:1500000")
    check("more money than the start: the difference taken", run("return canon(2000000, function() BAL[100] = 2600000 end)") == "100:-600000")
    check("already the start money: nothing", run("return canon(2000000, function() BAL[100] = 2000000 end)") == "")
    check("a start money of 0", run("return canon(0, function() BAL[100] = 300000 end)") == "100:-300000")
    check("a vehicle of its own: it keeps its money", run("return canon(2000000, function() OWN[501] = 100 end)") == "")
    check("another company's vehicle only: booked", run("return canon(2000000, function() OWN[501] = 200 end)") == "100:2000000")
    check("a line of its own: it keeps its money", run("return canon(2000000, function() LINES[100] = { 700 } end)") == "")
    check("a loan (review fix): it keeps its money",
          run("return canon(2000000, function() LOANS = { obtainedLoans = { { amount = 5000000 } } } end)") == "")
    check("a loan script with no loan: booked", run("return canon(2000000, function() LOANS = { obtainedLoans = {} } end)") == "100:2000000")
    check("the line system failing: booked all the same", run('return canon(2000000, function() LINES = "error" end)') == "100:2000000")
    check("no start money: nothing", run("return canon(nil)") == "")
    check("a start money under 0: nothing", run("return canon(-1)") == "")
    check("MPFEVER_SHARESWITCH=0: nothing, as before", run('return canon(2000000, function() ENV = { MPFEVER_SHARESWITCH = "0" } end)') == "")
    check("no registry: nothing", run("BOOKED = {}; REAL_CANON({}, 2000000); return #BOOKED") == 0)

    print("coApply")
    run(r'''
SIM.coStartCanon = function(st, start) STARTS[#STARTS + 1] = tostring(start) end
SIM.coRecolor = function() end
ENV = {}
function join(st, key, start, host)
  coApply(st, { fn = "mpfCoJoin", uid = "x", at = 1, args = { mode = "separate", key = key, name = key, host = host == true, cname = key .. " Co", sid = "s-" .. key, start = start } })
  local c = CO.memberOf(st.co, key)
  return c and (c.id .. ":" .. tostring(c.start)) or "none"
end
''')
    got = run('STARTS = {}; ST = {}; local r = join(ST, "host", 5000000, true); return r .. " canon " .. table.concat(STARTS, ",") .. " " .. tostring(ST.co.canon)')
    check("the first join makes the registry and gives the savegame's company the start money", got == "1:nil canon 5000000 100", got)
    check("a new player's company keeps its join's start money", run('return join(ST, "bob", 1000000)') == "2:1000000")
    check("floored", run('return join(ST, "carl", 1500000.9)') == "3:1500000")
    check("never under 0", run('return join(ST, "dan", -10)') == "4:0")
    check("a known company is not touched", run('return join(ST, "bob", 9000000)') == "2:1000000")
    check("no start money in the join: none of its own", run('return join(ST, "eve", nil)') == "5:nil")
    check("MPFEVER_SHARESWITCH=0: none of its own, as before",
          run('ENV = { MPFEVER_SHARESWITCH = "0" }; local r = join(ST, "finn", 3000000); ENV = {}; return r') == "6:nil")
    check("the registry made once", run('STARTS = {}; join(ST, "gus", 1); return #STARTS') == 0)

    print("coCreate")
    run(r'''
function create(cstart, regStart)
  BOOKED = {}
  G.co = { start = regStart }
  coCreate({}, { id = 4, name = "Bob Co", color = 2, start = cstart })
  local t = {}
  for _, b in ipairs(BOOKED) do if b.kind == "book" then t[#t + 1] = b.ent .. ":" .. b.amount end end
  return table.concat(t, ",")
end
''')
    check("the company's own start money booked", run("return create(5000000, 2000000)") == "300:5000000")
    check("none of its own: the registry's", run("return create(nil, 2000000)") == "300:2000000")
    check("0 of its own: nothing booked", run("return create(0, 2000000)") == "")

    if fails:
        print(f"FAIL {len(fails)} case(s): {', '.join(fails)}")
        return 1
    print("all cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
