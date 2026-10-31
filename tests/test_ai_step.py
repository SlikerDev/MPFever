"""A computer company's whole look (mpfever_ai.lua: M.tick, the host's step for each company) runs through on a mocked world with
the 0.6 rules on and with each of their switches at 0, without an error (the bridge only logs a failed step: an error there
stops the company for good, unseen). Offline, through lupa (Lua 5.2) with the mocked game of tests/ai_mock.py.

The world: a computer company with two bus lines that earn and 3 million, a farm (raw, level 1 of 5) 3 km from a food factory,
a garage open to all. Its looks must ask for a long-term freight line from the farm (0.6), and none with MPFEVER_AILONGFREIGHT=0
(with 3 million it may still open freight as a rich company of 0.5.14 does).
Needs lupa (pip install lupa). Run: python tests/test_ai_step.py
"""
import sys

try:
    import lupa.lua52  # noqa: F401
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

from ai_mock import load, checker

check, failures = checker()

WORLD = '''
LINES, VEH, CONS, ACTS, LOG, INDCACHE, SENT, BUILDS = {}, {}, {}, {}, {}, {}, {}, {}
G.AI, G.AIS, G.AIT = {}, {}, {}
G.frames = 100000
TIME = 3000000
E.C.ROLE = "host"
G.cmode = "separate"
G.connected = true
G.session = { started = true }
G.myCo = 1
G.coAi = "1:7:2"
CO1 = { id = 2, ent = 700, key = "ai:1", name = "Regional Transport", color = 7 }
G.co = { list = { CO1 } }
E.CO.byKey = function(reg, key) if key == "ai:1" then return CO1 end end
MONEY[700] = 3000000
addLine(501, { 1, 2 }, 2, { bal = 100000, use = 0.7, bought = 0 })
addLine(502, { 3, 4 }, 2, { bal = 80000, use = 0.7, bought = 0 })
addGarage(950, 951, 100, 100)
FARM = addIndustry(1001, { primary = true, outputs = { 2 }, level = 1, maxLevel = 5, pos = { x = 0, y = 0, z = 0 } })
FACT = addIndustry(1101, { outputs = { 5 }, inputs = { [2] = true }, pos = { x = 3000, y = 0, z = 0 } })
PROD[1004], MOST[1004] = 100, 200
'''


def looks(run, n):
    errors = []
    for _ in range(n):
        ok, err = run('G.frames = G.frames + 700; TIME = TIME + 20000; useIndustries(); G.AI.busy = nil; '
                      'local ok, err = pcall(M.tick, E, {}); return ok, tostring(err)')
        if not ok:
            errors.append(str(err))
    return errors


def scenario(name, env, want_lt):
    L, M = load()
    run = L.eval("function(code) local f = assert(load(code)) return f() end")
    run(WORLD)
    for k, v in env.items():
        run('ENV["%s"] = "%s"' % (k, v))
    errors = looks(run, 12)
    check(not errors, "%s: 12 looks without an error%s" % (name, (": " + errors[0][:300]) if errors else ""))
    asked = run('return logHas("long-term line asked")')
    if want_lt is not None:
        check(asked is want_lt, "%s: %s" % (name, "a long-term freight line is asked for" if want_lt else "no long-term freight line"))
    return run


print("whole looks")
run = scenario("0.6 rules", {}, True)
check(run('return acts("makeLineCreateCmd")') >= 1, "its line is sent")
check(run('return logHas("floor ")') is True, "the company's floor is in its report")
scenario("MPFEVER_AILONGFREIGHT=0", {"MPFEVER_AILONGFREIGHT": "0"}, False)
scenario("MPFEVER_AISOLVENT=0", {"MPFEVER_AISOLVENT": "0"}, None)
scenario("MPFEVER_AIFLOOR=0", {"MPFEVER_AIFLOOR": "0"}, None)
scenario("MPFEVER_AILTTREND=0 MPFEVER_AILTTRUCKS=0 MPFEVER_AILTCHAIN=0",
         {"MPFEVER_AILTTREND": "0", "MPFEVER_AILTTRUCKS": "0", "MPFEVER_AILTCHAIN": "0"}, True)
scenario("MPFEVER_AITOWNFREIGHT=0", {"MPFEVER_AITOWNFREIGHT": "0"}, None)
scenario("MPFEVER_AIKEEPBUILDINGS=0", {"MPFEVER_AIKEEPBUILDINGS": "0"}, None)

print("a poor company")
L, M = load()
run = L.eval("function(code) local f = assert(load(code)) return f() end")
run(WORLD)
run('MONEY[700] = 50000; LBAL[501] = -60000')
errors = looks(run, 12)
check(not errors, "12 looks under its floor without an error" + ((": " + errors[0][:300]) if errors else ""))
check(run('return acts("makeVehicleSellCmd")') >= 1, "it sells a vehicle of its losing line")
check(run('return acts("makeVehicleBuyCmd")') == 0 and run('return acts("makeLineCreateCmd")') == 0, "it buys and opens nothing")

if failures:
    print(f"FAIL: {len(failures)} check(s)")
    sys.exit(1)
print("PASS")
