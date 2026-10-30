"""Offline test of the computer companies' money rules of 0.5.14 (mpfever_ai.lua) and of the bridge's loan events.

mpfever_ai.lua is loaded whole through lupa (Lua 5.2); its local functions are reached through a table added before its
last line in the test only (the file is not changed). The bridge's ai_loan and ai_repay events are taken from the real
bridge file. A mocked game gives each line its earnings, seats in use and vehicles' running costs. Cases:
  - a line's fleet fitted to what it earns (MPFEVER_AIFLEET): a vehicle more only while the next one still pays with the
    level's margin (Easy 1.3, Normal 1.15, Hard 1.05 times its running costs), one less when a filled line does not pay its
    vehicles (two looks in a row), the last one when it pays under the level's share (the line is then given up: never
    bought a vehicle again, destroyed once empty), no decision within two game months of the last change; MPFEVER_AIFLEET=0:
    a busy line that does not lose money gets a vehicle, as before;
  - mayExpand, the growth gate: the level's first lines freely, then not while the last new line fills, not while the level's
    number of lines are unproven (young, or measured under the give-up share: one a little short of paying its vehicles no
    longer holds growth for ever), only while the lines earn together; plenty of money besides the reserve and the loans
    overrides it; MPFEVER_AIGOVERN=0: always;
  - bestPair, the pairs of towns spread over the companies: a pair another computer company runs or builds scores as the
    share of passengers left (a third, half on Hard), a pair it failed does not count (review fix), its own pair under way
    keeps its score; MPFEVER_AIPAIRSPREAD=0: as before;
  - in debt: only a line that loses money has a vehicle sold (MPFEVER_AIDEBTSELL=0: the emptiest line's, as before), else a
    loan is asked, one at most, the lowest monthly payment (MPFEVER_AILOANPICK=0: the first offer); money to spare repays
    a loan only when there is one;
  - townsForLines: a town another computer company works on goes after the others (MPFEVER_AISPREAD=0), a station nobody
    owns is no competitor (MPFEVER_AIRETRY=0: counted); bestBus: one-compartment models only (MPFEVER_AIMULTICOMP=1: any);
  - loanBook: count, still owed, monthly payments; M.listOf: a computer company's start money (0 to 10 billion, -1 or none:
    the players');
  - the bridge's ai_loan: at most param.max loans, with param.pick the offer of the lowest monthly payment (the first one
    before, 5 to 70 million over 1 to 24 years); ai_repay: the oldest loan repaid only when the money covers it and the
    amount kept back; neither for a player's company.
Run: python tests/test_ai0514.py
"""
import os, re, sys

try:
    import lupa.lua52 as lupa
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(HERE, "..", "mod", "mpfever_1", "content")
AI = os.path.join(CONTENT, "mpfever_ai.lua")
BRIDGE = os.path.join(CONTENT, "mpfever_bridge.script.lua")

# (the module's locals, for the test only: added before its last line)
EXPOSE = r'''
M.TEST = { mayExpand = mayExpand, manageLines = manageLines, bestPair = bestPair, loanBook = loanBook, townsForLines = townsForLines,
  level = function(i) LV = LEVELS[i]; RESERVE = LV.reserve end,
  buyFor = function(f) buyFor = f end }
return M
'''

MOCK = r'''
ENV = {}
os.getenv = function(k) return ENV[k] end
NOW = 10000000           -- game time (ms)
BAL, USE, RUN = {}, {}, {}
ACTS, BOUGHT, LOGS = {}, {}, {}
TOWNS, CAPS, CENTRES = {}, {}, {}
api = {
  type = { ComponentType = setmetatable({}, { __index = function(_, k) return k end }), enum = { LandUseType = { RESIDENTIAL = 1 } } },
  util = { getDefaultYearDuration = function() return 1440000 end, getDefaultMonthDuration = function() return 100000 end },
  engine = {
    getComponent = function(e, ct)
      if ct == "VEHICLE_DEPOT" then return { outNodes = { 1 } } end
      if ct == "NAME" then return { name = "E" .. e } end
      return nil
    end,
    util = {
      line = {
        getLineCapacityUsages = function(l) return USE[l] and { { used = USE[l] * 100, capacity = 100 } } or {} end,
        getLineProblems = function() return {} end,
      },
      finance = { calculateBalance = function(list, from, to) return BAL[list[1]] end },
      vehicle = { getRunningCost = function(v) return RUN[v] or 120000 end },
      town = { getTownDistrictCenter = function(t) return CENTRES[t] end },
    },
    system = {
      streetConnectorSystem = { getConstructionEntityForDepot = function(d) return d - 1 end },
      townBuildingSystem = { getTown2personCapacitiesMap = function() return CAPS end },
    },
  },
}
E = {
  api = api,
  G = { frames = 100000, AI = {}, AIS = {}, AIT = {} },
  R = { translateOut = function() end, entitiesWith = function(k) if k == "TOWN" then return TOWNS end return {} end, ownerOf = function() return nil end },
  C = { DIR = "dir", line = function(kind, p) return p end, appendFile = function(path, p) ACTS[#ACTS + 1] = p end },
  BS = "\\",
  log = function(s) LOGS[#LOGS + 1] = s end,
  send = function() end,
  gameTime = function() return NOW end,
}
CO = { id = 3, ent = 300 }
'''

BRIDGE_MOCK = r'''
SIM = {}
LOANEV, BLOG = {}, {}
function log(s) BLOG[#BLOG + 1] = s end
function gameTime() return 5000 end
function loanMods() return { lu = { getDurationInMonths = function(d) return d end,
  getFullLoanAndInterestPayBack = function(l) return l.amount * (1 + l.percentage) end } } end
function coLoanTable(st, id) st.co.loan = st.co.loan or {} return st.co.loan[id] end
function coLoanEvent(st, id, name, loans) LOANEV[#LOANEV + 1] = name .. " " .. id .. " " .. tostring(loans[1].amount) end
BALANCE = {}
api2 = { engine = { util = { finance = { getPlayersBalance = function(e) return BALANCE[e] end } } } }
'''


def main():
    src = open(AI, encoding="utf-8").read()
    m_ret = re.search(r"\nreturn M\s*$", src)
    bridge = open(BRIDGE, encoding="utf-8").read()
    m_loan = re.search(r"^(\t+)elseif name == \"ai_loan\" then\n.*?(?=^\1elseif name == \"recolor\" then\n)", bridge, re.S | re.M)
    if not (m_ret and m_loan):
        print("FAIL: the AI module's end or the bridge's ai_loan/ai_repay events not found")
        return 1
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute(MOCK)
    M = L.execute(src[:m_ret.start()] + "\n" + EXPOSE)
    L.globals().M = M
    L.execute("T = M.TEST; T.buyFor(function(E, co, l, depot) BOUGHT[#BOUGHT + 1] = l.e end)")
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

    # one bus line (700) of the company; a vehicle costs 120 000 a year to run: 20 000 over two months (the year is 1 440 000 ms)
    run(r'''
function fresh(level)
  T.level(level or 2)
  E.G.AI = { loanCount = 0, seenAt = { [700] = NOW - 2000000 } }
  E.G.AIS = { [1] = E.G.AI }
  E.G.AIT = { garages = { { con = 40, depot = 41, pos = { x = 0, y = 0, z = 0 }, owner = 300 } } }
  ENV = { MPFEVER_AIFREIGHT = "0" }
end
-- one regular look at the lines (every 2 minutes): n vehicles, the line's result over two months, its seats in use
function look(n, bal, use, money)
  E.G.frames = E.G.frames + 7201
  E.G.AIT.garagesAt = E.G.frames
  local veh = {}
  for i = 1, n do veh[i] = { e = 800 + i, line = 700 } end
  BAL[700], USE[700] = bal, use
  ACTS, BOUGHT = {}, {}
  T.manageLines(E, CO, { { e = 700, groups = { 1, 2 } } }, veh, money or 3000000)
  local t = {}
  for _, a in ipairs(ACTS) do
    local more = ""
    if a.fn == "makeVehicleSellCmd" then more = " " .. tostring(a.args[1][1]) end
    if a.fn == "makeScriptingSendEventCmd" then more = " " .. tostring(a.args[3]) .. (a.args[4].pick == 1 and a.args[4].max == 1 and " pick" or "") end
    t[#t + 1] = a.fn .. more
  end
  for _, l in ipairs(BOUGHT) do t[#t + 1] = "buy " .. l end
  return table.concat(t, ",")
end
''')
    print("a fleet fitted to each line (manageLines)")
    check("Normal: the next bus still pays with the margin (income 50 000 for two, 25 000 >= 1.15 x 20 000): bought",
          run("fresh(2); return look(1, 30000, 0.9)") == "buy 700")
    check("Normal: it would not (20 000 < 23 000): none, though the line earns", run("fresh(2); return look(1, 20000, 0.9)") == "")
    check("Easy (margin 1.3): 25 000 < 26 000: none", run("fresh(1); return look(1, 30000, 0.9)") == "")
    check("Hard (margin 1.05): bought", run("fresh(3); return look(1, 30000, 0.9)") == "buy 700")
    check("a line not full: none", run("fresh(3); return look(1, 30000, 0.5)") == "")
    got = run("fresh(2); return look(3, -15000, 0.5) .. '|' .. look(3, -15000, 0.5)")
    check("three buses paying 75 % of their costs: one less at the second look in a row", got == "|makeVehicleSellCmd 803", got)
    got = run("fresh(2); return look(1, -12000, 0.5) .. '|' .. look(1, -12000, 0.5) .. '|' .. tostring(E.G.AI.dropLine and E.G.AI.dropLine[700])")
    check("one bus paying 40 % (under Normal's 50 %): sold, the line given up", got == "|makeVehicleSellCmd 801|true", got)
    got = run("NOW = NOW + 300000; local r = look(0, 0, 0.95); NOW = NOW - 300000; return r")
    check("a line given up gets no vehicle back, and goes once empty", got == "makeLineDestroyCmd", got)
    got = run("fresh(2); return look(1, -8000, 0.5) .. '|' .. look(1, -8000, 0.5)")
    check("one bus paying 60 % (over the give-up share): kept", got == "|", got)
    got = run("fresh(2); E.G.AI.changedAt = { [700] = NOW - 100000 }; return look(3, -15000, 0.9) .. '|' .. look(3, -15000, 0.9) .. '|' .. look(1, 30000, 0.9)")
    check("within two game months of its last change: no decision", got == "||", got)
    got = run("fresh(2); ENV.MPFEVER_AIFLEET = '0'; return look(1, 20000, 0.9)")
    check("MPFEVER_AIFLEET=0: a busy line that earns gets a bus, as before", got == "buy 700", got)

    print("in debt (manageLines)")
    got = run("fresh(2); return look(2, -5000, 0.5, -100000)")
    check("a line that loses money: its vehicle sold", got == "makeVehicleSellCmd 802", got)
    got = run("fresh(2); return look(2, 30000, 0.5, -100000)")
    check("only lines that earn: none sold, a loan asked (the lowest monthly payment, one at most)", got == "makeScriptingSendEventCmd ai_loan pick", got)
    got = run("fresh(2); E.G.AI.loanCount = 1; return look(2, 30000, 0.5, -100000)")
    # (0.6: no loan any more and nothing losing: the last way out, a vehicle of the line earning the least; it stayed in debt for good)
    check("a loan already: no other one, a vehicle of the line earning the least sold (0.6)", got == "makeVehicleSellCmd 802", got)
    got = run("fresh(2); E.G.AI.loanCount = 1; ENV.MPFEVER_AISTUCK = '0'; local r = look(2, 30000, 0.5, -100000); ENV.MPFEVER_AISTUCK = nil; return r")
    check("a loan already, MPFEVER_AISTUCK=0: nothing, as before", got == "", got)
    got = run("fresh(2); ENV.MPFEVER_AILOANPICK = '0'; return look(2, 30000, 0.5, -100000)")
    check("MPFEVER_AILOANPICK=0: the first offer asked, as before", got == "makeScriptingSendEventCmd ai_loan", got)
    got = run("fresh(2); ENV.MPFEVER_AIDEBTSELL = '0'; return look(2, 30000, 0.5, -100000)")
    check("MPFEVER_AIDEBTSELL=0: the emptiest line's vehicle sold whatever it earns, as before", got == "makeVehicleSellCmd 802", got)
    got = run("fresh(2); E.G.AI.loanCount = 1; return look(1, 50000, 0.5, 2000000)")
    check("money to spare with a loan: its oldest loan repaid", got == "makeScriptingSendEventCmd ai_repay", got)
    got = run("fresh(2); return look(1, 50000, 0.5, 2000000)")
    check("money to spare without a loan: no repayment asked", got == "", got)

    print("the growth gate (mayExpand)")
    run(r'''
function may(lines, money, setup)
  fresh(2)
  E.G.frames = E.G.frames + 1000
  E.G.AI.opAt = nil
  local list = {}
  for i, b in ipairs(lines) do list[i] = { e = 700 + i }; BAL[700 + i] = b or nil end
  if setup then setup(E.G.AI) end
  return T.mayExpand(E, CO, list, money)
end
''')
    check("its first lines (Normal: 2) freely", run("return may({ -50000 }, 500000)") is True)
    check("lines that earn together: yes", run("return may({ 40000, -10000 }, 500000)") is True)
    check("lines that lose together: no", run("return may({ 10000, -30000 }, 500000)") is False)
    check("no result yet: no", run("return may({ false, false }, 500000)") is False)
    check("its last new line still fills (settle): no",
          run("return may({ 40000, 40000 }, 500000, function(A) A.lastNewAt = NOW - 100000 end)") is False)
    check("a young line (Normal: one unproven at most): no",
          run("return may({ 40000, 40000 }, 500000, function(A) A.born = { [701] = NOW - 100000 } end)") is False)
    check("a measured line under the give-up share: no",
          run("return may({ 40000, 40000 }, 500000, function(A) A.ratio = { [701] = 0.3 } end)") is False)
    check("a line a little short of paying its vehicles (80 %): no longer holds growth",
          run("return may({ 40000, 40000 }, 500000, function(A) A.ratio = { [701] = 0.8 } end)") is True)
    check("MPFEVER_AIFLEET=0: the measures not counted", run("return may({ 40000, 40000 }, 500000, function(A) A.ratio = { [701] = 0.3 }; ENV.MPFEVER_AIFLEET = '0' end)") is True)
    check("plenty of money (2 million besides the reserve): yes, whatever its lines do",
          run("return may({ -40000, -40000 }, 2500000, function(A) A.born = { [701] = NOW - 100000 } end)") is True)
    check("a loan's money is no money to spare",
          run("return may({ -40000, -40000 }, 2500000, function(A) A.loanCash = 2000000 end)") is False)
    check("MPFEVER_AIGOVERN=0: always", run("return may({ -40000, -40000 }, 0, function(A) ENV.MPFEVER_AIGOVERN = '0' end)") is True)

    print("the pairs of towns spread over the companies (bestPair)")
    run(r'''
TOWNS = { 1, 2, 3 }
CAPS = { [1] = { 1000, 0, 0 }, [2] = { 900, 0, 0 }, [3] = { 400, 0, 0 } }
CENTRES = { [1] = { x = 0, y = 0, z = 0 }, [2] = { x = 3000, y = 0, z = 0 }, [3] = { x = 0, y = 3000, z = 0 } }
function pair(level, other, setup)
  fresh(level)
  if other then E.G.AIS[2] = other end
  if setup then setup(E.G.AI) end
  local p = T.bestPair(E, CO, {}, {})
  return p and (p.key .. " " .. math.floor(p.score)) or "none"
end
''')
    check("alone: the biggest pair (1/2, score 300)", run("return pair(2)") == "1/2 300")
    check("another company runs it: a third of its score on Normal (100), the next pair first",
          run("return pair(2, { pairDone = { ['1/2'] = true } })") == "1/3 133")
    check("on Hard, which competes: half of it (150), still first", run("return pair(3, { pairDone = { ['1/2'] = true } })") == "1/2 150")
    check("another one builds it (under way): counted", run("return pair(2, { pairUnderWay = '1/2' })") == "1/3 133")
    check("a pair the other one failed is not under way (review fix)",
          run("return pair(2, { pairUnderWay = '1/2', pairFailed = { ['1/2'] = true } })") == "1/2 300")
    check("its own pair under way keeps its score",
          run("return pair(2, { pairDone = { ['1/2'] = true } }, function(A) A.pairUnderWay = '1/2' end)") == "1/2 300")
    check("MPFEVER_AIPAIRSPREAD=0: as before",
          run("return pair(2, { pairDone = { ['1/2'] = true } }, function(A) ENV.MPFEVER_AIPAIRSPREAD = '0' end)") == "1/2 300")

    print("the towns spread over the companies (townsForLines) and the one-compartment buses (bestBus)")
    run(r'''
STATIONS = {}
api.engine.system.stationSystem = { getStations = function(t) return STATIONS[t] or {} end }
E.R.ownerOf = function(e) return OWNERS and OWNERS[e] end
function towns(setup)
  fresh(2)
  STATIONS, OWNERS = {}, {}
  if setup then setup() end
  local t = {}
  for _, x in ipairs(T.townsForLines(E, CO.ent)) do t[#t + 1] = x.e end
  return table.concat(t, ",")
end
''')
    check("alone: the biggest town first", run("return towns()") == "1,2,3")
    check("a town another computer company works on goes after the others",
          run("return towns(function() E.G.AIS[2] = { targets = { [1] = {} } } end)") == "2,3,1")
    check("MPFEVER_AISPREAD=0: as before",
          run("return towns(function() E.G.AIS[2] = { targets = { [1] = {} } }; ENV.MPFEVER_AISPREAD = '0' end)") == "1,2,3")
    check("a station nobody owns (an industry's) is no competitor",
          run("return towns(function() STATIONS[1] = { 51, 52, 53, 54 } end)") == "1,2,3")
    check("MPFEVER_AIRETRY=0: counted, as before",
          run("return towns(function() STATIONS[1] = { 51, 52, 53, 54 }; ENV.MPFEVER_AIRETRY = '0' end)") == "2,1,3")
    run(r'''
local function model(seats, comps)
  local c = {}
  for i = 1, comps do c[i] = { loadConfigs = { { cargoEntry = { capacity = seats } } } } end
  return { metadata = { availability = { yearFrom = 1930, yearTo = 0 }, transportVehicle = { compartments = c } } }
end
MODELS = { [11] = model(40, 1), [12] = model(45, 2) }
api.res = { modelRep = { getAll = function() return { [11] = "model/vehicle/bus/a.mdl", [12] = "model/vehicle/bus/b.mdl", [13] = "model/vehicle/truck/c.mdl" } end, get = function(id) return MODELS[id] end } }
function bus() local b = M.f.bestBus(E) return b and (b.id .. ":" .. b.seats) or "none" end
''')
    got = run("ENV = {}; return bus()")
    check("a model of one compartment only (the shape of the purchase)", got == "11:40", got)
    check("MPFEVER_AIMULTICOMP=1: any model, as before", run("ENV = { MPFEVER_AIMULTICOMP = '1' }; local r = bus(); ENV = {}; return r") == "12:45")

    print("loanBook and M.listOf")
    got = run(r'''
E.G.co = { loan = { [3] = { obtainedLoans = { { amount = 6000000, duration = 1200000, timesPaid = 2, percentage = 0.05 } } } } }
local n, owe, monthly = T.loanBook(E, CO)
E.G.co = nil
return n .. " " .. math.floor(owe) .. " " .. math.floor(monthly)
''')
    check("one loan of 6 million over 12 months, 2 paid: 5 million owed, 525 000 a month", got == "1 5000000 525000", got)
    check("no loan: 0", run("return table.concat({ T.loanBook(E, CO) }, ' ')") == "0 0 0")
    got = run(r'''
local t = {}
for _, c in ipairs(M.listOf("1:7:3:1000000,2:3:1:-1,3:5,4:2:2:20000000000,5:1:9:0")) do
  t[#t + 1] = c.n .. "/" .. tostring(c.color) .. "/" .. c.level .. "/" .. tostring(c.money)
end
return table.concat(t, " ")
''')
    check("the computer companies' start money read (none, -1 or beyond 10 billion: the players')",
          got == "1/7/3/1000000 2/3/1/nil 3/5/2/nil 4/2/2/nil 5/1/2/0", got)

    print("the bridge's ai_loan and ai_repay")
    L.execute(BRIDGE_MOCK)
    L.globals().CO = L.execute(open(os.path.join(CONTENT, "mpfever_co.lua"), encoding="utf-8").read())
    L.execute("function aiEvent(st, name, param)\n  local api = api2\n  if false then\n" + m_loan.group(0) + "  end\nend\n")
    run(r'''
function loanCase(param, setup, key)
  local st = { co = CO.new("separate", 100, 2000000) }
  st.co.list[2] = { id = 2, key = key or "ai:1", name = "AI", color = 3, ent = 200 }
  st.co.loan = { [2] = { availableLoans = {
    { amount = 5000000, duration = 12, percentage = 0.05 },
    { amount = 70000000, duration = 288, percentage = 0.2 },
    { amount = 10000000, duration = 60, percentage = 0.1 },
    { amount = 1000000, duration = 60, percentage = 0, cooldownUntil = 9000 },
  }, obtainedLoans = {} } }
  if setup then setup(st) end
  LOANEV = {}
  param.mpfCo = 2
  aiEvent(st, param.ev or "ai_loan", param)
  return table.concat(LOANEV, ",")
end
''')
    check("the offer of the lowest monthly payment (10 million over 60 months)", run("return loanCase({ pick = 1, max = 1 })") == "Obtain 2 10000000")
    check("without pick: the first offer, as before", run("return loanCase({})") == "Obtain 2 5000000")
    check("an offer cooling down is not taken", run("return loanCase({ pick = 1 }, function(st) st.co.loan[2].availableLoans[3] = nil end)") == "Obtain 2 70000000")
    check("one loan at most (max = 1)", run("return loanCase({ pick = 1, max = 1 }, function(st) st.co.loan[2].obtainedLoans = { { amount = 5000000 } } end)") == "")
    check("a player's company: refused", run('return loanCase({ pick = 1 }, nil, "bob")') == "")
    run(r'''
function repayCase(bal, keep, key, loans)
  BALANCE[200] = bal
  return loanCase({ ev = "ai_repay", keep = keep }, function(st) st.co.loan[2].obtainedLoans = loans or { { amount = 5000000, percentage = 0.1 }, { amount = 9000000, percentage = 0 } } end, key)
end
''')
    check("money for the loan, its interest and what it keeps back: its oldest loan repaid", run("return repayCase(6000000, 400000)") == "Repay 2 5000000")
    check("not enough: kept", run("return repayCase(5800000, 400000)") == "")
    check("no loan: nothing", run("return repayCase(9000000, 0, nil, {})") == "")
    check("a player's company: refused", run('return repayCase(9000000, 0, "bob")') == "")

    if fails:
        print(f"FAIL {len(fails)} case(s): {', '.join(fails)}")
        return 1
    print("all cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
