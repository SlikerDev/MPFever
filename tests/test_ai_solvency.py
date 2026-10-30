"""A computer company keeps itself solvent (0.6, mpfever_ai.lua): its floor (floorOf, spendOk: no purchase or build takes it
under), and what it does under its reserve and under its floor (manageLines: the vehicles of its losing lines first, the one
that loses the most per vehicle first, never its long-term freight line before the others; then the cheapest loan; then its
long-term line's investment ends), and no new project under its reserve (mayExpand). Offline, through lupa (Lua 5.2) with the
mocked game of tests/ai_mock.py.

Also: MPFEVER_AISOLVENT=0 (the old rules: nothing done until it is in debt, then the emptiest losing line's vehicle) and
MPFEVER_AIFLOOR=0 (no floor).
Needs lupa (pip install lupa). Run: python tests/test_ai_solvency.py
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

print("the floor")
check(run('return M.p.floorOf(0, 0, 600000)') == 100000, "at least 100 000")
check(run('return M.p.floorOf(1200000, 0, 600000)') == 200000, "two months of a fleet's running costs (1.2 million a year)")
check(run('return M.p.floorOf(1200000, 50000, 1000000)') == 300000, "and two months of its loans' payments")
check(run('return M.p.floorOf(6000000, 0, 600000)') == 600000, "never above its reserve")

print("spendOk and the purchases")
run('''
M.p.set(2, 600000, 150000)
MONEY[700] = 400000
G.AI = {}
''')
check(run('return M.f.spendOk(E, CO1, 200000, "x")') is True, "400 000 less 200 000 stays above a floor of 150 000")
check(run('return M.f.spendOk(E, CO1, 300000, "y")') is False, "400 000 less 300 000 would go under the floor: refused")
check(run('return logHas("y not bought")') is True, "the refusal is logged")
run('MONEY[700] = 200000')
check(run('return M.f.buyBus(E, CO1, 900)') is False and run('return acts("makeVehicleBuyCmd")') == 0,
      "a bus of 180 000 with 200 000 and a floor of 150 000: not bought, nothing sent")
run('ENV.MPFEVER_AIFLOOR = "0"')
check(run('return M.f.buyBus(E, CO1, 900)') is True and run('return acts("makeVehicleBuyCmd")') == 1, "MPFEVER_AIFLOOR=0: bought, as before")
run('ENV.MPFEVER_AIFLOOR = nil; G.AI.busy = nil')
run('MONEY[700] = 300000; G.AI.busCost = nil; ACTS = {}')
check(run('return M.f.buyBus(E, CO1, 900)') is False, "with 300 000: refused, the price is the measured one when higher (180 000), not the model's 120 000")
run('MONEY[700] = 400000')
check(run('return M.f.buyBus(E, CO1, 900)') is True and run('return acts("makeVehicleBuyCmd")') == 1, "with 400 000: bought")

# the company's lines: 501 earns, 502 loses 25 000 per bus, 503 loses 30 000 per bus, 504 is its long-term freight line (loses
# 120 000 with one truck, planned)
WORLD = '''
LINES, VEH, ACTS, LOG = {}, {}, {}, {}
G.AI = {}
G.frames = 200000
addLine(501, { 1, 2 }, 2, { bal = 100000, use = 0.6 })
addLine(502, { 3, 4 }, 2, { bal = -50000, use = 0.3 })
addLine(503, { 5, 6 }, 3, { bal = -90000, use = 0.5 })
addLine(504, { 7, 8 }, 1, { bal = -120000, use = 0.2 })
G.AI.lt = { [504] = { state = "invest", key = "k504", budget = 500000, spent = 100000, samples = {}, born = TIME } }
M.p.set(2, 600000, 150000)
'''


def look(money):
    return run('G.frames = G.frames + 7300; MONEY[700] = %d; return M.f.manageLines(E, CO1, linesList(), vehiclesList(), %d)' % (money, money))


def sold():
    return run('local a = lastAct("makeVehicleSellCmd"); return a and a.args[1][1] or nil')


print("under its floor: the vehicles of its losing lines, the most losing per vehicle first")
run(WORLD)
check(look(50000) is True, "it acts")
check(sold() == 5033, "a bus of line 503 (30 000 lost per bus) goes before 502's (25 000 per bus) and the long-term line's truck")
run('ACTS = {}')
check(look(50000) is True and sold() in (5033, 5032, 5031), "again 503's at the next look (20 s later in game: every look under the floor)")

print("under its floor with no other losing line: the cheapest loan, then its long-term line's investment ends")
run(WORLD)
run('LBAL[502] = 20000; LBAL[503] = 30000')
check(look(50000) is True, "it acts")
ev = run('local a = lastAct("makeScriptingSendEventCmd"); return a and a.args[3] or nil')
check(ev == "ai_loan", "a loan is asked (ai_loan)")
check(run('return lastAct("makeScriptingSendEventCmd").args[4].pick') == 1, "the offer of the lowest monthly payment (pick 1)")
check(sold() is None, "nothing sold: the long-term line's truck is kept while a loan can come")
run('G.AI.busy = nil; G.AI.loanCount = 1; ACTS = {}')
check(look(50000) is True and run('return G.AI.lt[504].state') == "ended", "with a loan already: the long-term line's investment ends")
check(run('return G.AI.ltFailed.k504') is True and run('return G.AI.ltNextAt ~= nil') is True, "its route is not tried again soon")
check(sold() is None, "nothing sold at that look")
run('ACTS = {}')
check(look(50000) is True and sold() == 5041, "the next look sells its truck: a losing line like the others now")

print("under its reserve, above its floor")
run(WORLD)
check(look(400000) is True and sold() == 5033, "one vehicle of the line losing the most per vehicle at a regular look")
run('ACTS = {}')
check(look(2000000) is not True or sold() is None, "with money to spare: no sale for want of money")
check(run('return M.f.mayExpand(E, CO1, linesList(), 400000)') is False, "nothing new under its reserve")
check(run('return logHas("under its reserve")') is True, "the reason is logged")

print("MPFEVER_AISOLVENT=0: as before")
run(WORLD)
run('ENV.MPFEVER_AISOLVENT = "0"')
check(look(50000) is not True or sold() is None, "between zero and its floor: nothing sold")
run('ACTS = {}')
check(look(-50000) is True and sold() == 5022, "in debt: the emptiest losing line's vehicle (502, 30 % used), as before")
run('ENV.MPFEVER_AISOLVENT = nil')

if failures:
    print(f"FAIL: {len(failures)} check(s)")
    sys.exit(1)
print("PASS")
