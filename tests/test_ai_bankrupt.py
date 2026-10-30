"""A computer company never goes bankrupt (0.6, mpfever_eco.lua: E.AI_NO_BANKRUPT, E.isAi), offline: the registry and the host's
monthly look (co_month) through lupa (Lua 5.2) with a mocked game API, as tests/test_companies.py does.

Cases: a player's company in debt for the host's months goes bankrupt, a computer company in debt as long does not (no months
counted, no "in debt" notice); a computer company known by a member's key only, or by a key made unique ("ai:1@..."); a debt count
of an earlier version is dropped; MPFEVER_AINOBANKRUPT=0 brings the old rule back (the computer company goes bankrupt too).
Needs lupa (pip install lupa). Run: python tests/test_ai_bankrupt.py
"""
import os
import sys

try:
    import lupa.lua52 as lua52
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mod", "mpfever_1", "content")

MOCK = r'''
ENVOVR = {}
do
  local og = os.getenv
  os.getenv = function(k) local v = ENVOVR[k] if v ~= nil then return v end return og(k) end
end
TIME = 0
BAL = {}
OWN = {}
api = {
  type = { JournalEntry = { new = function() return { category = {} } end, Type = { OTHER = 1 } }, Vec3f = { new = function() return {} end },
    ComponentType = { PLAYER_OWNED = "po", NAME = "name" } },
  util = { getDefaultMonthDuration = function() return 1000 end },
  cmd = { sendCommand = function() end, makeJournalBookAssetCmd = function(ent, e) BAL[ent] = (BAL[ent] or 0) + e.amount return {} end,
    makeEntitySetPlayerCmd = function(e, p) OWN[e] = p return {} end },
  engine = { getComponent = function() return nil end, entityExists = function() return false end,
    forEachEntityWithComponent = function() end,
    util = { finance = { getPlayersBalance = function(p) return BAL[p] or 0 end } }, system = {} },
}
R = { allEdges = function() return {} end, entitiesWith = function() return {} end, ownerOf = function(e) return OWN[e] end, sgKey = function(s) return "sg" .. s end,
  withoutAssets = function(l) return l end }
LOG = {}
ENV = { log = function(s) LOG[#LOG + 1] = s end, R = R, STEP = 200, gameTime = function() return TIME end, journalCarrier = function() return 1 end }
'''

failures = []


def check(cond, what):
    print(("  ok    " if cond else "  FAIL  ") + what)
    if not cond:
        failures.append(what)


def world(no_bankrupt_env=None):
    L = lua52.LuaRuntime(unpack_returned_tuples=True)
    L.execute(MOCK)
    if no_bankrupt_env is not None:
        L.execute('ENVOVR["MPFEVER_AINOBANKRUPT"] = "%s"' % no_bankrupt_env)
    CO = L.execute(open(os.path.join(here, "mpfever_co.lua"), encoding="utf-8").read())
    L.globals().CO = CO
    L.execute("ENV.CO = CO")
    E = L.execute(open(os.path.join(here, "mpfever_eco.lua"), encoding="utf-8").read())
    L.globals().E = E
    run = L.eval("function(code) local f = assert(load(code)) return f() end")
    # the savegame's company (the host's), a player, two computer companies (one joined under a name taken: "ai:2@3"), all with
    # their player entity; the host's rule: bankrupt after 3 months in debt
    run('''
st = { co = CO.new("separate", 100, 2000000) }
CO.join(st.co, "host", "Host", true, "Host Co", "s1", 1)
local b = CO.join(st.co, "bob", "Bob", false, "Bob Co", "s2", 2); b.ent = 200
local a1 = CO.join(st.co, "ai:1", "Regional Transport", false, "Regional Transport", nil, 3); a1.ent = 300
local a2 = CO.join(st.co, "ai:2", "Valley Coaches", false, "Valley Coaches", nil, 4); a2.ent = 400
a2.key = "ai:2@3"
st.co.rules = { bankrupt = 3 }
TIME = 0; E.tick(st, ENV)
''')
    return L, run


def months(run, n, debt):
    for m in range(1, n + 1):
        run('TIME = TIME + 1000; E.tick(st, ENV); E.event(st, "co_month", { month = st.co.month, debt = { %s }, mpfFrom = "Host" }, ENV)' % debt)


print("a computer company never goes bankrupt")
L, run = world()
check(run('return E.AI_NO_BANKRUPT') is True, "the rule is on by default")
check(run('return E.isAi(CO.find(st.co, 3))') is True, "company 3 (key ai:1) is a computer company")
check(run('return E.isAi(CO.find(st.co, 4))') is True, "company 4 (key ai:2@3, a name taken) is a computer company")
check(run('return E.isAi(CO.find(st.co, 2))') is False, "bob's company is a player's")
check(run('return E.isAi({ key = "", members = { { key = "carl" }, { key = "ai:7" } } })') is True, "a member's key ai:7 is enough")
check(run('return E.isAi(nil)') is False, "nothing is no computer company")
months(run, 2, "2, 3, 4")
check(run('return CO.find(st.co, 2).debt') == 2, "bob's company counts 2 months in debt")
check(run('return CO.find(st.co, 3).debt') is None, "the computer company counts none")
check(run('local n = 0 for _, x in ipairs(st.co.news or {}) do if x.kind == "debt" and (x.co == 3 or x.co == 4) then n = n + 1 end end return n') == 0,
      "no 'in debt' notice for a computer company")
months(run, 1, "2, 3, 4")
check(run('return CO.find(st.co, 2).gone') == "bankrupt", "bob's company is bankrupt after 3 months")
run('E.finishAuction(st, ENV)')
months(run, 12, "3, 4")
check(run('return CO.find(st.co, 3).gone') is None, "computer company 3 is still there after 15 months in debt")
check(run('return CO.find(st.co, 4).gone') is None, "computer company 4 is still there after 15 months in debt")
# (a debt count kept by an earlier version is dropped at the next month, the bankruptcy check never takes it)
run('CO.find(st.co, 3).debt = 7')
months(run, 1, "3")
check(run('return CO.find(st.co, 3).debt') is None and run('return CO.find(st.co, 3).gone') is None,
      "an old debt count of a computer company is dropped, no bankruptcy")

print("MPFEVER_AINOBANKRUPT=0: as before")
L, run = world("0")
check(run('return E.AI_NO_BANKRUPT') is False, "the rule is off")
months(run, 3, "3")
check(run('return CO.find(st.co, 3).gone') == "bankrupt", "the computer company goes bankrupt after 3 months, as before")

if failures:
    print(f"FAIL: {len(failures)} check(s)")
    sys.exit(1)
print("PASS")
