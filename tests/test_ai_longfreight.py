"""Long-term freight of the computer companies (0.6, mpfever_ai.lua): a freight line as an investment whose loss is accepted within
a budget and a time and judged on its trend. Offline, through lupa (Lua 5.2) with the mocked game of tests/ai_mock.py.

  - the pure rules: ltBudget (a share of the money to spare, capped, none under its minimum), ltJudge (paid, budget spent, time
    up, no growth after the proof time, a better result, MPFEVER_AILTTREND=0), ltScore (room to grow, chain, town goods);
  - ltProject: the route of a raw producer that can grow (not one at its most level, not a processing industry the company does
    not feed), the line asked for and noted, nothing while one is under way, nothing it cannot afford, nothing with
    MPFEVER_AILONGFREIGHT=0;
  - ltSync: the line taken once there, its samples (its spending, its producer's production, its income against its trucks'
    running costs) and verdicts (budget spent, no growth, paid), the line taken again after a load;
  - manageLines: the line in its investment is neither "empty" nor "does not pay its vehicles"; once ended, the fleet rules
    take it; a truck more for the cargo waiting at its producer (MPFEVER_AILTTRUCKS=0: not).
Needs lupa (pip install lupa). Run: python tests/test_ai_longfreight.py
"""
import sys

try:
    import lupa.lua52  # noqa: F401
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

from ai_mock import load, checker

check, failures = checker()
L, M = load()
run = L.eval("function(code) local f = assert(load(code)) return f() end")
Y = 1461000

print("ltBudget")
check(run('return M.p.ltBudget(1000000)') is None, "1 million to spare: no budget yet (20 % is under 300 000)")
check(run('return M.p.ltBudget(2000000)') == 400000, "2 million: 400 000")
check(run('return M.p.ltBudget(20000000)') == 1500000, "20 million: capped at 1.5 million")

print("ltJudge")
run('P = { horizon = 3 * %d, proof = %d, grow = 1.25 }' % (Y, Y))


def judge(lt, now, trend=True):
    return run('local v, w = M.p.ltJudge(%s, %d, P, %s); return v' % (lt, now, "true" if trend else "false"))


check(judge('{ born = 0, budget = 500000, spent = 100000, prod0 = 100, samples = { { bal = -50000, prod = 100, ratio = 0.3 } } }', 500000) == "keep",
      "young, within its budget: kept")
check(judge('{ born = 0, budget = 500000, spent = 100000, prod0 = 100, samples = { { ratio = 1.1 }, { ratio = 1.2 } } }', 500000) == "paid",
      "its income covered its trucks two samples in a row: paid")
check(judge('{ born = 0, budget = 500000, spent = 100000, prod0 = 100, samples = { { ratio = 0.5 }, { ratio = 1.2 } } }', 500000) == "keep",
      "one sample is not enough")
check(judge('{ born = 0, budget = 500000, spent = 500000, prod0 = 100, samples = {} }', 500000) == "end", "its budget spent: ended")
check(judge('{ born = 0, budget = 500000, spent = 0, prod0 = 100, samples = {} }', 3 * Y) == "end", "three game years: ended")
check(judge('{ born = 0, proofFrom = 0, budget = 900000, spent = 300000, prod0 = 100, samples = { { bal = -50000, prod = 110 } } }', Y + 1) == "end",
      "a year on, its producer grew by 10 % only and its result no better: ended")
check(judge('{ born = 0, proofFrom = 0, budget = 900000, spent = 300000, prod0 = 100, samples = { { bal = -50000, prod = 130 } } }', Y + 1) == "keep",
      "a year on, its producer grew by 30 %: kept")
check(judge('{ born = 0, proofFrom = 0, budget = 900000, spent = 300000, prod0 = 100, samples = { { bal = -60000, prod = 100 }, { bal = -60000, prod = 100 }, '
            '{ bal = -20000, prod = 100 }, { bal = -10000, prod = 100 } } }', Y + 1) == "keep",
      "a year on, its producer flat but its result much better: kept (the trend, not one month)")
check(judge('{ born = 0, proofFrom = 0, budget = 900000, spent = 300000, prod0 = 100, samples = { { bal = -50000, prod = 100 } } }', Y + 1, False) == "keep",
      "MPFEVER_AILTTREND=0: budget and time only, kept")
check(judge('{ born = 0, proofFrom = %d, budget = 900000, spent = 300000, prod0 = 100, samples = { { bal = -50000, prod = 100 } } }' % Y, Y + 1) == "keep",
      "after a load the proof time starts again (proofFrom)")

print("ltScore")
low = run('return M.p.ltScore(200, 1, 5, 3000, false, false)')
check(run('return M.p.ltScore(200, 4, 4, 3000, false, false)') == 0, "a producer at its most level scores nothing")
check(run('return M.p.ltScore(200, 4, 4, 3000, true, false)') > 0, "unless the company feeds it (a chain)")
check(low > run('return M.p.ltScore(200, 4, 5, 3000, false, false)'), "more room to grow, more score")
check(abs(run('return M.p.ltScore(200, 1, 5, 3000, false, true)') - low * 1.2) < 1e-6, "a product the towns take: 1.2 times")

# a world: two bus lines that earn (the level's first lines), a farm (raw, level 1 of 5) 3 km from a food factory that takes
# its grain, a quarry at its most level, a brick works that makes bricks without the company's cargo, a garage open to all
WORLD = '''
LINES, VEH, CONS, ACTS, LOG, INDCACHE = {}, {}, {}, {}, {}, {}
G.AI = {}
G.frames = 300000
TIME = 2000000
MONEY[700] = 3000000
addLine(501, { 1, 2 }, 2, { bal = 100000, use = 0.7 })
addLine(502, { 3, 4 }, 2, { bal = 80000, use = 0.7 })
addGarage(950, 951, 100, 100)
FARM = addIndustry(1001, { primary = true, outputs = { 2 }, level = 1, maxLevel = 5, pos = { x = 0, y = 0, z = 0 } })
FACT = addIndustry(1101, { outputs = { 5 }, inputs = { [2] = true }, pos = { x = 3000, y = 0, z = 0 } })
QUARRY = addIndustry(1201, { primary = true, outputs = { 2 }, level = 4, maxLevel = 4, pos = { x = 0, y = 400, z = 0 } })
BRICKS = addIndustry(1301, { outputs = { 3 }, pos = { x = 0, y = -400, z = 0 } })
TOWNS = addIndustry(1401, { inputs = { [3] = true }, pos = { x = 2500, y = -400, z = 0 } })
PROD[1004], MOST[1004] = 100, 200
PROD[1204], MOST[1204] = 300, 300
PROD[1304], MOST[1304] = 500, 500
useIndustries()
M.p.set(2, 600000, 150000)
'''

print("ltProject")
run(WORLD)
r = run('return M.f.ltProject(E, CO1, {}, linesList(), vehiclesList(), MONEY[700])')
check(r is True, "it acts")
check(run('return acts("makeLineCreateCmd")') == 1, "a freight line is asked for")
check(run('return G.AI.ltPending and G.AI.ltPending.key') == "1001>1101:2", "the farm's grain to the food factory (not the quarry at its most, nor the bricks it does not feed)")
check(run('return G.AI.ltPending.budget') == 600000, "its budget: 20 % of its 3 million to spare (no loan)")
run('ACTS = {}')
check(run('return M.f.ltProject(E, CO1, {}, linesList(), vehiclesList(), MONEY[700])') is False and run('return acts("makeLineCreateCmd")') == 0,
      "nothing more while the one asked for is not there")

print("ltSync")
run('addLine(601, { 1002, 1102 }, 0); OWN[601] = 700')
run('M.f.ltSync(E, CO1, linesList(), vehiclesList(), MONEY[700])')
check(run('return G.AI.lt[601] and G.AI.lt[601].state') == "invest", "the line asked for is taken as the long-term line once there")
check(run('return G.AI.ltPending') is None, "nothing pending any more")
check(run('return M.f.ltProject(E, CO1, {}, linesList(), vehiclesList(), MONEY[700])') is False, "no second one while it is in its investment")
# its truck, two months: lost 60 000, the farm makes 100
run('local v = 6011; VEH[#VEH + 1] = v; OWN[v] = 700; VLINE[v] = 601; RUN[v] = 150000; LBAL[601] = -60000')
run('TIME = TIME + 240000; M.f.ltSync(E, CO1, linesList(), vehiclesList(), MONEY[700])')
check(run('return #G.AI.lt[601].samples') == 1 and run('return G.AI.lt[601].spent') == 60000, "a sample after two months: 60 000 spent")
check(run('return G.AI.lt[601].state') == "invest", "kept")
check(run('return logHas("long-term line 601: -60000")') is True, "the sample is logged")
run('LBAL[601] = -700000; TIME = TIME + 240000; M.f.ltSync(E, CO1, linesList(), vehiclesList(), MONEY[700])')
check(run('return G.AI.lt[601].state') == "ended", "its budget spent: ended")
check(run('return G.AI.ltFailed["1001>1101:2"]') is True, "its route is not tried again as a long-term line")
check(run('return G.AI.ltNextAt') == run('return TIME') + Y // 2, "the next one waits half a game year")
check(run('return M.f.ltProject(E, CO1, {}, linesList(), vehiclesList(), MONEY[700])') is False, "nothing during that wait")
run('addLine(602, { 1002, 1102 }, 1, { bal = -900000 }); G.AI.lt[602] = { state = "invest", key = "k2", from = 1001, stockList = 1004, cargo = 2, '
    'born = TIME, budget = 300000, spent = 0, prod0 = 100, proofFrom = TIME, at = TIME - 240000, samples = {} }')
run('M.f.ltSync(E, CO1, linesList(), vehiclesList(), MONEY[700])')
check(run('return G.AI.lt[602].state') == "ended" and run('return G.AI.ltNextAt') == run('return TIME') + Y,
      "a second one given up: the next one waits twice as long (a game year)")

print("ltSync: a producer that does not grow, one that pays")
run(WORLD)
run('addLine(601, { 1002, 1102 }, 1, { bal = -30000, run = 150000 }); G.AI.lt = {}')
run('G.AI.ltPending = { key = "1001>1101:2", groups = { 1002, 1102 }, from = 1001, stockList = 1004, cargo = 2, budget = 1000000, prod0 = 100, frame = G.frames }')
run('M.f.ltSync(E, CO1, linesList(), vehiclesList(), MONEY[700])')
for k in range(7):
    run('TIME = TIME + 240000; M.f.ltSync(E, CO1, linesList(), vehiclesList(), MONEY[700])')
check(run('return G.AI.lt[601].state') == "ended" and str(run('return G.AI.lt[601].why')).startswith("its producer does not grow"),
      "a year on, the farm still makes 100 and the line loses as much: ended")
run(WORLD)
run('addLine(601, { 1002, 1102 }, 1, { bal = -30000, run = 150000 }); G.AI.lt = {}')
run('G.AI.ltPending = { key = "1001>1101:2", groups = { 1002, 1102 }, from = 1001, stockList = 1004, cargo = 2, budget = 1000000, prod0 = 100, frame = G.frames }')
run('M.f.ltSync(E, CO1, linesList(), vehiclesList(), MONEY[700])')
run('PROD[1004] = 260')
for k in range(7):
    run('TIME = TIME + 240000; M.f.ltSync(E, CO1, linesList(), vehiclesList(), MONEY[700])')
check(run('return G.AI.lt[601].state') == "invest", "a year on, the farm makes 260 (it grew): kept despite its loss")
run('LBAL[601] = 60000')
for k in range(2):
    run('TIME = TIME + 240000; M.f.ltSync(E, CO1, linesList(), vehiclesList(), MONEY[700])')
check(run('return G.AI.lt[601].state') == "paid", "it pays its truck two samples in a row: a line like the others")

print("ltSync after a load")
run(WORLD)
run('addLine(601, { 1002, 1102 }, 1, { bal = -40000, run = 150000, bought = TIME - 480000 }); G.AI = {}; useIndustries()')
run('M.f.ltSync(E, CO1, linesList(), vehiclesList(), MONEY[700])')
check(run('return G.AI.lt[601] and G.AI.lt[601].state') == "invest", "its freight line from the farm is taken again")
check(run('return G.AI.lt[601].born') == run('return TIME') - 480000, "its age from its truck's purchase")
check(run('return G.AI.lt[601].spent') == 80000, "what it spent from the line's accounts since then (4 months of 40 000 a 2 months)")
# (what ltEnd remembers is not in the savegame: a line given up before the load is not taken again with a fresh budget)
run(WORLD)
run('addLine(601, { 1002, 1102 }, 1, { bal = -400000, run = 150000, bought = TIME - 480000 }); G.AI = {}; useIndustries()')
run('M.f.ltSync(E, CO1, linesList(), vehiclesList(), MONEY[700])')
check(run('return G.AI.lt[601] and G.AI.lt[601].state') == "ended", "its loss (800 000) already past the budget it would get (600 000): not taken again")
check(run('return G.AI.ltFailed and G.AI.ltFailed["1001>1101:2"]') is True and run('return G.AI.ltNextAt') == run('return TIME') + Y // 2,
      "counted as given up: its route is left, the next one waits half a game year")
check(run('return M.f.ltProject(E, CO1, {}, linesList(), vehiclesList(), MONEY[700])') is False, "no new long-term line right after the load")
run(WORLD)
run('TIME = 9000000; addLine(601, { 1002, 1102 }, 1, { bal = -40000, run = 150000, bought = TIME - 3 * %d - 1000 }); G.AI = {}; useIndustries()' % Y)
run('M.f.ltSync(E, CO1, linesList(), vehiclesList(), MONEY[700])')
check(run('return G.AI.lt[601]') is None and run('return G.AI.ltNextAt') == run('return TIME') + Y // 2,
      "none to take again but a freight line that lost money since its first truck: the next one waits from the load")
run(WORLD)
run('ENV.MPFEVER_AILTLOAD = "0"')
run('addLine(601, { 1002, 1102 }, 1, { bal = -400000, run = 150000, bought = TIME - 480000 }); G.AI = {}; useIndustries()')
run('M.f.ltSync(E, CO1, linesList(), vehiclesList(), MONEY[700])')
check(run('return G.AI.lt[601] and G.AI.lt[601].state') == "invest" and run('return G.AI.ltNextAt') is None, "MPFEVER_AILTLOAD=0: taken again, as before")
run('ENV.MPFEVER_AILTLOAD = nil')

print("manageLines with a long-term line")
run(WORLD)
run('addLine(601, { 1002, 1102 }, 1, { bal = -50000, run = 150000, use = 0.01, wait = 200 })')
run('G.AI.lt = { [601] = { state = "invest", key = "1001>1101:2", budget = 1000000, spent = 100000, samples = {}, born = TIME } }')
run('G.AI.seenAt = { [601] = TIME - 2000000 }; G.AI.born = { [501] = 0, [502] = 0, [601] = 0 }; G.AI.bornInit = true; G.AI.loanCount = 0')
sold = []
for k in range(4):
    run('ACTS = {}; G.frames = G.frames + 7300; useIndustries(); M.f.manageLines(E, CO1, linesList(), vehiclesList(), MONEY[700])')
    sold.append(run('local a = lastAct("makeVehicleSellCmd"); return a and a.args[1][1] or nil'))
check(all(x is None for x in sold), "in its investment: its truck is never sold (not empty, its loss planned)")
check(run('return logHas("long-term line 601 gets a truck more")') is True, "a truck more for the 200 tons waiting at the farm")
run('ENV.MPFEVER_AILTTRUCKS = "0"; LOG = {}; G.AI.changedAt = {}')
for k in range(2):
    run('ACTS = {}; G.frames = G.frames + 7300; useIndustries(); M.f.manageLines(E, CO1, linesList(), vehiclesList(), MONEY[700])')
check(run('return logHas("long-term line 601 gets a truck more")') is False, "MPFEVER_AILTTRUCKS=0: not for the cargo waiting")
run('ENV.MPFEVER_AILTTRUCKS = nil')
run('G.AI.lt[601].state = "ended"; WAIT[601] = 0')
sold = []
for k in range(3):
    run('ACTS = {}; G.frames = G.frames + 7300; useIndustries(); M.f.manageLines(E, CO1, linesList(), vehiclesList(), MONEY[700])')
    sold.append(run('local a = lastAct("makeVehicleSellCmd"); return a and a.args[1][1] or nil'))
check(6011 in sold, "once ended: its truck is sold as a line that does not pay its vehicles")

print("MPFEVER_AILONGFREIGHT=0")
run(WORLD)
run('ENV.MPFEVER_AILONGFREIGHT = "0"')
check(run('return M.f.ltProject(E, CO1, {}, linesList(), vehiclesList(), MONEY[700])') is False and run('return acts("makeLineCreateCmd")') == 0,
      "no long-term line")
run('addLine(601, { 1002, 1102 }, 1, { bal = -40000, bought = TIME - 480000 }); G.AI.lt = nil')
run('M.f.ltSync(E, CO1, linesList(), vehiclesList(), MONEY[700])')
check(run('return G.AI.lt') is None, "nothing taken after a load")
run('ENV.MPFEVER_AILONGFREIGHT = nil')

print("not affordable")
run(WORLD)
run('MONEY[700] = 1200000')
check(run('return M.f.ltProject(E, CO1, {}, linesList(), vehiclesList(), MONEY[700])') is False and run('return acts("makeLineCreateCmd")') == 0,
      "1.2 million: no budget yet")
check(run('return logHas("long-term freight waits")') is True, "the reason is logged")

if failures:
    print(f"FAIL: {len(failures)} check(s)")
    sys.exit(1)
print("PASS")
