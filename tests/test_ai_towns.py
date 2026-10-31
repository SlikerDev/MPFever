"""Deliveries of the computer companies to the towns (0.6, mpfever_ai.lua; on by default again in 0.6.2, MPFEVER_AITOWNFREIGHT=0: off; off by default since
0.5.14): the town buildings that take the cargo (stockTakes, the town building's stock list), the place where they stand thickest
(densest, townDropPoint), and the check that a stop reaches some of them before its line is made (stopReaches, the engine's
catchment of the station; townFreightProject). Offline, through lupa (Lua 5.2) with the mocked game of tests/ai_mock.py.
Also MPFEVER_AITOWNCATCH=0 (the district's centre and no check, as before).
Needs lupa (pip install lupa). Run: python tests/test_ai_towns.py
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

print("densest")
check(run('return (M.p.densest({}, 160))') is None, "no building: no place")
p = run('local p, n = M.p.densest({ { x = 0, y = 0 }, { x = 100, y = 0 }, { x = 50, y = 50 }, { x = 2000, y = 0 } }, 160); return p.x .. "," .. n')
check(p in ("0,3", "50,3", "100,3"), "three together and one alone: a place of the three (%s)" % p)

print("stockTakes")
run('''
setComp(81, "STOCK_LIST", { stocks = { { type = 0, cargoType = 5 } } })
setComp(82, "STOCK_LIST", { stocks = { { type = 1, cargoType = 5 } } })
setComp(83, "STOCK_LIST", { stocks = { { type = 0, cargoType = -1, cargoTypes = { [5] = true } } } })
setComp(84, "STOCK_LIST", { stocks = { { type = 0, cargoType = 3 } } })
''')
check(run('return M.f.stockTakes(E, 81, 5)') is True, "an input stock of that cargo")
check(run('return M.f.stockTakes(E, 82, 5)') is False, "an output stock is no demand")
check(run('return M.f.stockTakes(E, 83, 5)') is True, "an input stock of a set with that cargo")
check(run('return M.f.stockTakes(E, 84, 5)') is False, "another cargo")
check(run('return M.f.stockTakes(E, 99, 5)') is False, "no stock list")

print("stopReaches")
run('CATCH = { [70] = { 81, 82, 83, 84 } }')
check(run('return M.f.stopReaches(E, 70, 5)') == 2, "two stock lists in reach take it")
check(run('return M.f.stopReaches(E, 71, 5)') == 0, "a stop that reaches nothing")
run('CATCHFAIL = true')
check(run('return M.f.stopReaches(E, 70, 5)') == -1, "unreadable: -1 (not taken for none)")
run('CATCHFAIL = nil')

print("townDropPoint")
run('''
G.AI = {}
local function b(e, sl, x, y)
  setComp(e, "TOWN_BUILDING", { stockList = sl, construction = e + 1000 })
  setComp(e + 1000, "CONSTRUCTION", { transf = { 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, 0, 1 } })
end
b(201, 81, 1000, 1000); b(202, 83, 1080, 1000); b(203, 81, 1000, 1090); b(204, 81, 3000, 3000); b(205, 84, 1010, 1010)
TOWNBUILDINGS = { [9] = { 201, 202, 203, 204, 205 } }
''')
pt = run('local p, n = M.f.townDropPoint(E, 9, 5); return p and (p.x .. "," .. p.y .. "," .. n) or "none"')
check(pt.endswith(",3") and not pt.startswith("3000"), "the place of the three that take it together (%s), not the one alone, not the one of another cargo" % pt)
check(run('local p = M.f.townDropPoint(E, 9, 4); return p') is None, "a cargo no building takes: none")

# a town delivery (opt-in): a farm's vegetables (cargo 5) to town 9, whose shops want 50 more; the company's stop 70 near its
# buildings that take them; a garage near the farm
WORLD = '''
LINES, VEH, CONS, ACTS, LOG, INDCACHE = {}, {}, {}, {}, {}, {}
G.AI = {}
G.frames = 400000
MONEY[700] = 3000000
M.p.set(2, 600000, 150000)
ENV.MPFEVER_AITOWNFREIGHT = "1"
TOWNLIST = { 9 }
TOWNCAP = { [9] = { 400, 100, 100 } }
CENTRE = { [9] = { x = 1500, y = 1500, z = 0 } }
SUPPLY = { [9] = { [1] = { [5] = { 10, 60 } } } }
addGarage(950, 951, 100, 100)
FARM = addIndustry(1001, { primary = true, outputs = { 5 }, level = 1, maxLevel = 5, pos = { x = -1000, y = 1000, z = 0 } })
PROD[1004] = 100
useIndustries()
setComp(71, "STATION_GROUP", { stations = { 70 } })
setComp(70, "STATION", { terminals = { { vehicleNodeId = 1 }, { vehicleNodeId = 2 } } })
MYSTOPS = { { station = 70, group = 71, pos = { x = 1020, y = 1020, z = 0 } } }
'''

print("townFreightProject: the stop must reach buildings that take the cargo")
run(WORLD)
run('CATCH = { [70] = { 84 } }')
check(run('return M.f.bestTownFreight(E, CO1, linesList()) ~= nil') is True, "a delivery is found")
run('G.AI.freightTried = {}')
r = run('return M.f.townFreightProject(E, CO1, MYSTOPS, linesList(), vehiclesList(), MONEY[700])')
check(r is False, "the stop reaches no building that takes vegetables: no line")
check(run('return acts("makeLineCreateCmd")') == 0, "nothing sent")
check(run('return G.AI.freightTried["1001>town9:5"]') is False, "that delivery is left")
run(WORLD)
run('CATCH = { [70] = { 81, 83 } }')
r = run('return M.f.townFreightProject(E, CO1, MYSTOPS, linesList(), vehiclesList(), MONEY[700])')
check(r is True and run('return acts("makeLineCreateCmd")') == 1, "it reaches two: the line is made")
check(run('return logHas("2 building(s) in reach")') is True, "logged")

print("MPFEVER_AITOWNCATCH=0: as before")
run(WORLD)
run('CATCH = { [70] = { 84 } }; ENV.MPFEVER_AITOWNCATCH = "0"')
run('MYSTOPS[1].pos = { x = 1500, y = 1500, z = 0 }')
r = run('return M.f.townFreightProject(E, CO1, MYSTOPS, linesList(), vehiclesList(), MONEY[700])')
check(r is True and run('return acts("makeLineCreateCmd")') == 1, "the district's centre, no check: the line is made")
run('ENV.MPFEVER_AITOWNCATCH = nil; ENV.MPFEVER_AITOWNFREIGHT = nil')

# (0.6.2) the deliveries to towns on by default (a company without freight lines starts with one), off with MPFEVER_AITOWNFREIGHT=0
print("MPFEVER_AITOWNFREIGHT: on by default")
run(WORLD)
run('ENV.MPFEVER_AITOWNFREIGHT = nil; CATCH = { [70] = { 81, 83 } }')
run('M.f.freightProject(E, CO1, MYSTOPS, linesList(), vehiclesList(), MONEY[700])')
check(run('return logHas("town delivery")') is True, "nothing set: a delivery to a town is looked for")
run(WORLD)
run('ENV.MPFEVER_AITOWNFREIGHT = "0"; CATCH = { [70] = { 81, 83 } }')
run('M.f.freightProject(E, CO1, MYSTOPS, linesList(), vehiclesList(), MONEY[700])')
check(run('return logHas("town delivery")') is False, "MPFEVER_AITOWNFREIGHT=0: none")
run('ENV.MPFEVER_AITOWNFREIGHT = nil')

if failures:
    print(f"FAIL: {len(failures)} check(s)")
    sys.exit(1)
print("PASS")
