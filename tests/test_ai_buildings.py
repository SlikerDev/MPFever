"""A computer company's builds never take a town building down (0.6, mpfever_ai.lua: keepBuildings, buildingsHit; the bridge's
replay of its garages). Offline, through lupa (Lua 5.2) with the mocked game of tests/ai_mock.py.

Found while checking (2026-10-30): its streets to an industry were dry-run and sent with the buildings gathered (Context bit 1,
35): a house in the way was no error and the street would have taken it down; its garages are replayed by every game with the
buildings gathered as a player's depot tool does. Its stops never gathered any (32).
  - buildingsHit: the buildings a dry run gathers or collides with;
  - connectIndustry: dry run and build without the buildings gathered (34), a street with a building in its way refused, its
    price checked against the floor; MPFEVER_AIKEEPBUILDINGS=0: 35 and built, as before;
  - buildGarage: its act carries keepBuildings (the bridge replays it without the buildings gathered), not with the switch at 0;
    not sent under the floor;
  - buildStop: a stop's Context gathers nothing;
  - the bridge: replayNativeConstruction reads keepBuildings, and such a build gets no other form when that replay fails.
Needs lupa (pip install lupa). Run: python tests/test_ai_buildings.py
"""
import os
import re
import sys

try:
    import lupa.lua52  # noqa: F401
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

from ai_mock import load, checker, CONTENT

check, failures = checker()
L, M = load()
run = L.eval("function(code) local f = assert(load(code)) return f() end")

print("buildingsHit")
run('setComp(77, "TOWN_BUILDING", {}); setComp(78, "CONSTRUCTION", { townBuildings = { 1 } }); setComp(79, "CONSTRUCTION", { townBuildings = {} })')
check(run('return M.f.buildingsHit(E, { collisionInfo = { buildingEntities = { 5, 6 }, collisionEntities = {} } })') == 2, "two buildings gathered")
check(run('return M.f.buildingsHit(E, { collisionInfo = { buildingEntities = {}, collisionEntities = { { entity = 77 }, { entity = 78 }, { entity = 79 } } } })') == 2,
      "a town building and a town building's construction it runs into (not another construction)")
check(run('return M.f.buildingsHit(E, {})') == -1, "unreadable: -1")

# an industry cut off from the streets: its own street's free end (node 31 at 0,0), a town street node (41 at 300,0)
WORLD = '''
LINES, VEH, CONS, ACTS, LOG, BUILDS, DRY = {}, {}, {}, {}, {}, {}, {}
G.AI = {}
G.natCtx = {}
MONEY[700] = 3000000
M.p.set(2, 600000, 150000)
NODES = { [31] = { x = 0, y = 0, z = 0 }, [32] = { x = -50, y = 0, z = 0 }, [41] = { x = 300, y = 0, z = 0 }, [42] = { x = 380, y = 0, z = 0 } }
SEGMAP = { [31] = { 30 }, [32] = { 30 }, [41] = { 40, 43 }, [42] = { 40 } }
setComp(20, "CONSTRUCTION", { frozenEdges = { 30 } })
setComp(30, "BASE_EDGE", { node0 = 32, node1 = 31, type = 0 })
setComp(30, "BASE_EDGE_STREET", {})
setComp(40, "BASE_EDGE", { node0 = 41, node1 = 42, type = 0, roadTemplate = "::/infrastructure/street/town/town_old_small.street_template", roadType = 1 })
setComp(40, "BASE_EDGE_STREET", {})
EDGES = { 40 }
IND = { e = 10, con = 20, pos = { x = 0, y = 0, z = 0 } }
'''


def pd(buildings):
    return ('DRYRESULT = function(p, ctx) return { errorState = { messages = {}, critical = false }, costs = 40000, '
            'collisionInfo = { buildingEntities = { %s }, collisionEntities = {} } } end' % buildings)


print("a street to an industry")
run(WORLD)
run(pd("77"))
check(run('return M.f.connectIndustry(E, CO1, IND)') is False, "a town building in its way: no street")
check(run('return #BUILDS') == 0, "nothing sent")
check(run('return DRY[1] and DRY[1].ctx.gatherBuildings') is False, "its dry run gathers no building")
check(run('return logHas("town building(s) in its way")') is True, "the refusal is logged")
run(WORLD)
run(pd(""))
check(run('return M.f.connectIndustry(E, CO1, IND)') is True, "nothing in its way: the street is built")
check(run('return #BUILDS') == 1 and run('return BUILDS[1].ctx.gatherBuildings') is False, "sent without the buildings gathered")
check(run('return G.natCtx[100000 + G.autoBuildSeq]') == 34, "the other games replay it with the same flags (34)")
run(WORLD)
run(pd(""))
run('MONEY[700] = 170000')
check(run('return M.f.connectIndustry(E, CO1, IND)') is False and run('return #BUILDS') == 0, "its price (40 000) would take it under its floor: not built")
run(WORLD)
run(pd("77"))
run('ENV.MPFEVER_AIKEEPBUILDINGS = "0"')
check(run('return M.f.connectIndustry(E, CO1, IND)') is True, "MPFEVER_AIKEEPBUILDINGS=0: built over the building's place, as before")
check(run('return BUILDS[1].ctx.gatherBuildings') is True and run('return G.natCtx[100000 + G.autoBuildSeq]') == 35, "with the buildings gathered (35)")
run('ENV.MPFEVER_AIKEEPBUILDINGS = nil')

print("a garage")
GARAGE = '''
setComp(50, "BASE_EDGE", { node0 = 51, node1 = 52, type = 0, roadTemplate = "::/infrastructure/street/town/town_old_small.street_template", laneConfigs = {} })
PLACE = { seg = 50, c = comp(50, "BASE_EDGE"), a = { x = 0, y = 0, z = 0 }, b = { x = 100, y = 0, z = 0 }, P = { x = 50, y = 0, z = 0 },
  O = { x = 50, y = 42, z = 0 }, n = { x = 0, y = 1 }, side = 1, cost = 300000 }
SENT = {}
'''
run(WORLD)
run(GARAGE)
run('M.f.buildGarage(E, CO1, PLACE)')
check(run('return #SENT') >= 1 and run('return SENT[1].name') == "act", "the garage is sent as an act")
check(run('return SENT[1].a.keepBuildings') is True, "its act keeps the town buildings (the bridge replays it so on every game)")
check(run('return G.nativeQueue[#G.nativeQueue].keepBuildings') is True, "this game's own replay too")
run(WORLD)
run(GARAGE)
run('ENV.MPFEVER_AIKEEPBUILDINGS = "0"; M.f.buildGarage(E, CO1, PLACE)')
check(run('return SENT[1].a.keepBuildings') is None, "MPFEVER_AIKEEPBUILDINGS=0: as before")
run('ENV.MPFEVER_AIKEEPBUILDINGS = nil')
run(WORLD)
run(GARAGE)
run('MONEY[700] = 400000')
check(run('return M.f.buildGarage(E, CO1, PLACE)') is False and run('return #SENT') == 0, "320 000 with 400 000 and a floor of 150 000: not sent")

print("a stop")
run(WORLD)
run('setComp(60, "BASE_EDGE", { node0 = 41, node1 = 42, tangent0 = {}, tangent1 = {}, type = 0, typeIndex = -1, roadTemplate = "t", laneConfigs = {} })')
check(run('return M.f.buildStop(E, CO1, 60, "x")') is True, "the stop is built")
check(run('return BUILDS[1].ctx.gatherBuildings') is False, "a stop gathers no building")

print("the bridge")
src = open(os.path.join(CONTENT, "mpfever_bridge.script.lua"), encoding="utf-8").read()
m = re.search(r"^local function replayNativeConstruction\(a\)\n.*?^end\n", src, re.S | re.M)
check(m is not None and "ctx2.gatherBuildings = a.keepBuildings ~= true" in m.group(0),
      "replayNativeConstruction: no building gathered for a build that keeps them")
check(re.search(r"if replayNativeConstruction\(a\) then return end\n\s*--[^\n]*\n\s*--[^\n]*\n\s*if a\.keepBuildings == true then\n[^\n]*\n\s*replayFailed\(a,", src) is not None,
      "and no other form for it when that replay fails (they all gather the buildings)")

if failures:
    print(f"FAIL: {len(failures)} check(s)")
    sys.exit(1)
print("PASS")
