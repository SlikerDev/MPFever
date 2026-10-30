"""Offline test of the 0.6 module "stats" (mod/mpfever_1/content/mpfever_feat_stats.lua): the game goal, the ranking and
graphs, the yearly report in the chat (note release/recherche-0.6/01-objectifs-stats.md, the owner's decisions A1-A6, B7).

The module is run through lupa (Lua 5.2) with the options host's env mocked as docs/FEATURES-0.6.md describes it (simulation
half: env.on, env.param, env.state, env.mode, env.co, env.companies, env.money, env.book, env.month...; GUI half: env.isHost,
env.send, env.chat, env.write, env.realTime...; window: u.T, u.read, u.request and widgets) and a mocked game API for the
host's measure. Two games run the same events in the same order (lockstep), with different player entities.
Cases: the module loads without the game's API; every option off (no state, no event, no file, no chat, no money); the
separate-only options in the shared mode; the host's monthly figures (client sends nothing, a client's event refused, a month
measured once, a month not started refused, the companies settled first); the ring of 24 months and the years; the goal by
value, money and tenders (target, time, ties, computer companies that cannot or can win, a gone company, the tenders option
off); the host's cancel (window request, client refused), the option switched off, a new goal only after a change; the yearly
report of every company in each game's language, told once; the savegame (plain data, reload, same outcome); determinism (the
same state on both games); the window's tab (French and English, chart or table, host and client).
Run: python tests/test_feat_stats.py
"""
import os
import sys

try:
    import lupa.lua52 as lua52
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(HERE, "..", "mod", "mpfever_1", "content")
MODULE = os.path.join(CONTENT, "mpfever_feat_stats.lua")

L = lua52.LuaRuntime(unpack_returned_tuples=True)
failures = []


def check(cond, what):
    print(("  ok    " if cond else "  FAIL  ") + what)
    if not cond:
        failures.append(what)


run = L.eval("function(code) local f = assert(load(code)) return f() end")

# ---------------------------------------------------------------- the module loads without the game's API
L.execute("api = nil; ug_require = nil")
M = L.execute(open(MODULE, encoding="utf-8").read())
L.globals().M = M
print("loading")
check(M is not None and run("return M.ID") == "stats", "the module loads without the game's API, ID 'stats'")
check(run('''
local ids = {}
for _, o in ipairs(M.OPTIONS) do ids[#ids + 1] = o.id .. "/" .. o.modes end
return table.concat(ids, ",")''') == "goal/separate,stats/both,yearly/separate", "options goal (separate), stats (both), yearly (separate)")
check(run('''
for _, o in ipairs(M.OPTIONS) do
  if not (o.id:match("^[a-z_]+$") and type(o.title[1]) == "string" and type(o.title[2]) == "string" and o.desc[1] and o.desc[2]) then return false end
  for _, p in ipairs(o.params or {}) do
    local found = false
    for _, v in ipairs(p.values) do if v == p.default then found = true end end
    if not found or not (p.label[1] and p.label[2]) then return false end
    for _, v in ipairs(p.values) do
      if type(p.show(v, function(fr, en) return fr end)) ~= "string" or type(p.show(v, function(fr, en) return en end)) ~= "string" then return false end
    end
  end
end
return true''') is True, "every option and parameter: French and English, a default among its values, a label for each value")
check(run('''
for k in pairs(M.EVENTS) do if k:sub(1, 8) ~= "f_stats_" then return false end end
return M.EVENTS.f_stats_sample and M.EVENTS.f_stats_cancel and M.TAB.id == "stats" and M.TAB.title[1] == "Classement"''') is True,
      "events named f_stats_*, the tab 'Classement' / 'Ranking'")
# (every text: French and English, the same number of %s)
check(run('''
for k, p in pairs(M.TX) do
  if type(p[1]) ~= "string" or type(p[2]) ~= "string" or p[1] == "" or p[2] == "" then return k end
  local _, a = p[1]:gsub("%%s", "") local _, b = p[2]:gsub("%%s", "")
  if a ~= b then return k end
end
return true''') is True, "every text in French and English with the same placeholders")

# ---------------------------------------------------------------- the mocked game, two games in lockstep
HARNESS = r'''
-- the game's API as the host's GUI half reads it (the host's own entities)
BAL, LOAN, VAL, OWNER, EXISTS = {}, {}, {}, {}, {}
api = {
  type = { ComponentType = { ACCOUNT = "acc", PLAYER_OWNED = "po", TRANSPORT_VEHICLE = "tv" } },
  engine = {
    entityExists = function(e) return EXISTS[e] ~= false end,
    getComponent = function(e, ct)
      if ct == "acc" then return BAL[e] and { balance = BAL[e], loan = LOAN[e] or 0 } or nil end
      if ct == "po" then return OWNER[e] and { player = OWNER[e] } or nil end
      return nil
    end,
    forEachEntityWithComponent = function(fn, ct)
      if ct ~= "tv" then return end
      local ks = {} for v in pairs(OWNER) do ks[#ks + 1] = v end table.sort(ks)
      for _, v in ipairs(ks) do fn(v) end
    end,
    util = {
      finance = { getPlayersBalance = function(p) return BAL[p] end },
      vehicle = { getDepreciatedValue = function(v) return VAL[v] or 0 end },
      getPlayer = function() return 100 end,
    },
  },
}
-- (mpfever_co.lua's palette through the game's loader)
ug_require = function(name)
  local f = assert(io.open(CONTENT .. "/" .. name:gsub("^mpfever_1::/", ""), "rb"))
  local s = f:read("*a") f:close()
  return assert(load(s, name))()
end

local function default(opt, pid)
  for _, o in ipairs(M.OPTIONS) do
    if o.id == opt then for _, p in ipairs(o.params or {}) do if p.id == pid then return p.default end end end
  end
  return nil
end

-- the module as one game loads it: each game runs its own copy (its own GUI memory, as each PC's Lua state)
function loadModule() return assert(load(SRC, "mpfever_feat_stats.lua"))() end

-- a game: its own module, state, player entities (base + 100 * company), language, role
function newGame(name, base, lang, host)
  local g = { M = loadModule(), name = name, base = base, lang = lang, isHost = host, mode = "separate", month = 0, now = 0,
    st = {}, sent = {}, chats = {}, files = {}, books = {}, logs = {}, writes = 0 }
  g.st.co = { mode = "separate", list = {} }
  g.st.opts = {}
  return g
end

-- the companies: { id, name, key, gone } on every game, each with its own entity
function setCompanies(g, list)
  g.st.co.list = {}
  for _, c in ipairs(list) do
    g.st.co.list[#g.st.co.list + 1] = { id = c.id, name = c.name, key = c.key, gone = c.gone, color = c.id, ent = g.base + 100 * c.id }
  end
end

function opts(g, t) g.st.opts = t end

function simEnv(g)
  local env = {}
  env.log = function(s) g.logs[#g.logs + 1] = s end
  env.gameTime = function() return g.month * 1000 end
  env.STEP = 200
  env.on = function(id) return g.st.opts[id] == true end
  env.param = function(id, pid)
    local v = g.st.opts[id .. "." .. pid]
    if v == nil then return default(id, pid) end
    return v
  end
  env.state = function(st) st.feat = st.feat or {}; st.feat.stats = st.feat.stats or {}; return st.feat.stats end
  env.mode = g.mode
  env.co = g.mode == "separate" and g.st.co or nil
  env.companies = function()
    local out = {}
    if g.mode ~= "separate" then return { { id = 1, ent = g.base + 100, name = "", ai = false, members = {} } } end
    for _, c in ipairs(g.st.co.list) do
      out[#out + 1] = { id = c.id, ent = c.ent, name = c.name, ai = (c.key or ""):sub(1, 3) == "ai:", members = { { key = c.key } } }
    end
    table.sort(out, function(a, b) return a.id < b.id end)
    return out
  end
  env.money = function(ent) return BAL[ent] end
  env.book = function(ent, amount) g.books[#g.books + 1] = { ent, amount } end
  env.R = {}
  env.every = function(n) return false end
  env.month = function() return g.month end
  return env
end

function guiEnv(g)
  local env = {}
  env.log = function(s) g.logs[#g.logs + 1] = s end
  env.on = function(id) return g.st.opts[id] == true end
  env.param = function(id, pid)
    local v = g.st.opts[id .. "." .. pid]
    if v == nil then return default(id, pid) end
    return v
  end
  env.isHost = g.isHost
  env.me = g.name
  env.myCo = g.myCo
  env.send = function(name, param) g.sent[#g.sent + 1] = { name = name, param = param } end
  env.chat = function(t) g.chats[#g.chats + 1] = t end
  env.write = function(file, lines)
    local s = table.concat(lines, "\n")
    if g.files[file] ~= s then g.files[file] = s; g.writes = g.writes + 1 end
  end
  env.realTime = function() return g.now end
  env.T = function(fr, en) if g.lang == "fr" then return fr end return en end
  return env
end

GAMES = {}

-- a new game month on every game
function newMonth(mi)
  for _, g in ipairs(GAMES) do g.month = mi; g.M.month(g.st, simEnv(g)) end
end

-- an event sent by game `from`, applied by every game at the same step (lockstep): the sender's name stamped as mpfFrom
function apply(name, param, origin)
  for _, g in ipairs(GAMES) do
    local p = {}
    for k, v in pairs(param or {}) do p[k] = v end
    p.mpfFrom = origin
    g.M.event(g.st, name, p, simEnv(g))
  end
end

-- the GUI half of every game, `dt` seconds later; the events they sent are then applied everywhere
function guiAll(dt)
  local out = {}
  for _, g in ipairs(GAMES) do
    g.now = g.now + (dt or 1)
    g.M.gui(g.st, guiEnv(g))
    for _, e in ipairs(g.sent) do out[#out + 1] = { e = e, origin = g.isHost and g.name or (g.name .. "#1") } end
    g.sent = {}
  end
  for _, x in ipairs(out) do apply(x.e.name, x.e.param, x.origin) end
  return #out
end

-- a game month as a session plays it: its start, then the GUI halves a second and 5 seconds later (the host's companies are
-- read once known for 5 s: the first month of a scenario is measured at the second look)
function month(mi)
  newMonth(mi)
  return guiAll(1) + guiAll(5)
end

-- a plain-data serializer (sorted keys): fails on a function, a userdata, a cycle, a key that is not a string or a number
function ser(v, seen)
  seen = seen or {}
  local t = type(v)
  if t == "string" then return string.format("%q", v) end
  if t == "number" then
    if v ~= v or v == math.huge or v == -math.huge then error("not a plain number") end
    return string.format("%.17g", v)
  end
  if t == "boolean" or t == "nil" then return tostring(v) end
  if t ~= "table" then error("not plain data: " .. t) end
  if seen[v] then error("a cycle") end
  seen[v] = true
  local keys = {}
  for k in pairs(v) do
    if type(k) ~= "string" and type(k) ~= "number" then error("a key " .. type(k)) end
    keys[#keys + 1] = k
  end
  table.sort(keys, function(a, b) if type(a) ~= type(b) then return type(a) == "number" end return a < b end)
  local parts = {}
  for _, k in ipairs(keys) do parts[#parts + 1] = "[" .. ser(k, seen) .. "]=" .. ser(v[k], seen) end
  seen[v] = nil
  return "{" .. table.concat(parts, ",") .. "}"
end

function feat(g) return g.st.feat and ser(g.st.feat) or "nil" end

-- what the host's game reads of its companies: money, loans, vehicles (owned by the host's own entities)
function hostFigures(g, id, bal, loan, vehicles)
  local ent = g.base + 100 * id
  BAL[ent], LOAN[ent] = bal, loan or 0
  for v, o in pairs(OWNER) do if o == ent then OWNER[v], VAL[v] = nil, nil end end
  for i, val in ipairs(vehicles or {}) do
    local v = ent * 1000 + i
    OWNER[v], VAL[v] = ent, val
  end
end

-- the whole session reset: two games, A the host (French), B a client (English)
function reset(mode)
  BAL, LOAN, VAL, OWNER, EXISTS = {}, {}, {}, {}, {}
  A = newGame("host", 0, "fr", true)
  B = newGame("bob", 5000, "en", false)
  A.myCo, B.myCo = 1, 2
  GAMES = { A, B }
  for _, g in ipairs(GAMES) do
    g.mode = mode or "separate"
    if g.mode ~= "separate" then g.st.co = nil end
  end
end
'''
L.globals().CONTENT = CONTENT.replace("\\", "/")
L.globals().SRC = open(MODULE, encoding="utf-8").read()
L.execute(HARNESS)

COS = '''
for _, g in ipairs(GAMES) do
  setCompanies(g, { { id = 1, name = "Host Rail", key = "host" }, { id = 2, name = "Bob Trans", key = "bob" },
    { id = 3, name = "Robot", key = "ai:1" } })
end
'''


def nothing_happened():
    return run('''
for _, g in ipairs(GAMES) do
  if g.st.feat ~= nil or #g.sent > 0 or g.writes > 0 or #g.chats > 0 or #g.books > 0 then return false end
end
return true''') is True


# ---------------------------------------------------------------- every option off
print("options off")
run("reset()" + COS + '''
hostFigures(A, 1, 5000000, 0, { 100000 })
hostFigures(A, 2, 2000000, 0, {})
for mi = 24001, 24030 do month(mi) end
apply("f_stats_sample", { mi = 24030, rows = "1:5000000,0,100000" }, "host")
apply("f_stats_cancel", { seq = 1 }, "host")
A.M.request("cancel", "", A.st, guiEnv(A))
''')
check(nothing_happened(), "every option off: no state, no event sent, no file, no chat, no money, even after events and requests")
check(run('return M.ui({ T = function(fr, en) return en end, read = function() return nil end, text = function(t) return t end })') is not None,
      "the window's tab without a file draws (no data)")

# the separate-only options in the shared mode (one company for everybody): nothing either
print("shared mode")
run('''reset("shared")
for _, g in ipairs(GAMES) do opts(g, { goal = true, yearly = true }) end
for mi = 24001, 24005 do month(mi) end''')
check(nothing_happened(), "shared mode: goal and yearly (separate only) do nothing")
run('''
for _, g in ipairs(GAMES) do opts(g, { stats = true }) end
BAL[100], LOAN[100] = 3000000, 1000000
OWNER[777], VAL[777] = 100, 400000
for mi = 24006, 24008 do month(mi) end''')
check(run('return A.st.feat.stats.m[#A.st.feat.stats.m]') == "24008|2000|8|1:3000000,1000000,400000",
      "shared mode with stats: the one company (the game's player) measured: money, loan, vehicles")
check(run('return feat(A) == feat(B) and B.st.feat.stats.goal == nil') is True, "shared mode: both games agree, no goal")
check(run('return A.files["feat_stats.txt"]:find("mode\tshared", 1, true) ~= nil and A.files["feat_stats.txt"]:find("opts\t0\t1\t0", 1, true) ~= nil') is True,
      "shared mode: the window's file says shared, stats only")

# ---------------------------------------------------------------- the host's monthly figures
print("monthly figures")
run("reset()" + COS + '''
for _, g in ipairs(GAMES) do opts(g, { stats = true }) end
hostFigures(A, 1, 5000000, 1000000, { 300000, 200000 })
hostFigures(A, 2, 2500000, 0, { 100000 })
hostFigures(A, 3, 8000000, 0, {})
newMonth(24001)
N1 = guiAll(1)''')
check(run("return N1") == 0, "the companies are not read before they are known for 5 seconds (the engine asserts otherwise)")
check(run("return A.st.feat.stats.due == 24001 and A.st.feat.stats.last == nil") is True, "the month is due, not measured yet")
run("N2 = guiAll(5)")
check(run("return N2") == 1, "5 seconds later the host sends the month's figures, once")
check(run('return A.st.feat.stats.m[1]') == "24001|2000|1|1:5000000,1000000,500000;2:2500000,0,100000;3:8000000,0,0",
      "figures: money, loans, the vehicles' resale value of every company (ids, not entities)")
check(run('return feat(A) == feat(B)') is True, "both games hold the same figures")
check(run("return guiAll(1)") == 0, "nothing sent again once applied")
# a client sends nothing, and a client's event is refused
run('''
for _, g in ipairs(GAMES) do g.isHost = false end
newMonth(24002)
CLIENT_SENT = guiAll(30)
for _, g in ipairs(GAMES) do g.isHost = (g == A) end''')
check(run("return CLIENT_SENT") == 0, "no game but the host's sends figures (isHost false everywhere: nothing)")
run('''apply("f_stats_sample", { mi = 24002, rows = "1:1,0,0" }, "bob#1")''')
check(run("return A.st.feat.stats.last == 24001 and B.st.feat.stats.last == 24001") is True, "figures from a client are refused")
run('''apply("f_stats_sample", { mi = 24003, rows = "1:1,0,0" }, "host")''')
check(run("return A.st.feat.stats.last") == 24001, "figures of a month not started yet are refused")
run('''apply("f_stats_sample", { mi = 24002, rows = "1:1,0,0;1:2,0,0" }, "host")
apply("f_stats_sample", { mi = 24002, rows = "1:x,0,0" }, "host")''')
check(run("return A.st.feat.stats.last") == 24001, "malformed figures (a company twice, not a number) are refused")
run("guiAll(1)")
check(run("return A.st.feat.stats.last") == 24002, "the host's own figures of the month are taken")
run('''apply("f_stats_sample", { mi = 24002, rows = "1:9,0,0" }, "host")''')
check(run('return A.st.feat.stats.m[#A.st.feat.stats.m]:sub(1, 7)') == "24002|2" and run('return #A.st.feat.stats.m') == 2,
      "a month already measured is not taken again")
# the host's event lost (a resynchronisation): sent again after 10 s
run('''
newMonth(24003)
LOST = 0
for _, g in ipairs(GAMES) do g.now = g.now + 1; g.M.gui(g.st, guiEnv(g)); LOST = LOST + #g.sent; g.sent = {} end''')
check(run("return LOST") == 1 and run("return guiAll(3)") == 0, "a month sent is not sent again before 10 s")
check(run("return guiAll(10)") == 1 and run("return A.st.feat.stats.last") == 24003, "a lost month is sent again after 10 s")
# a company of the host not settled: waited for up to 20 s, then the others go without it
run('''
for _, g in ipairs(GAMES) do setCompanies(g, { { id = 1, name = "Host Rail", key = "host" }, { id = 2, name = "Bob Trans", key = "bob" },
  { id = 3, name = "Robot", key = "ai:1" }, { id = 4, name = "Late", key = "late" } }) end
hostFigures(A, 4, 2000000, 0, {})
EXISTS[400] = false     -- (its player entity not there yet on the host's game)
newMonth(24004)
W1 = guiAll(1)
W2 = guiAll(10)
W3 = guiAll(15)''')
check(run("return W1") == 0 and run("return W2") == 0 and run("return W3") == 1,
      "a company not readable yet is waited for up to 20 s, then the month goes without it")
check(run('return A.st.feat.stats.m[#A.st.feat.stats.m]:find(";4:", 1, true) == nil and A.st.feat.stats.last == 24004') is True,
      "the month without the company not settled")
run('''EXISTS[400] = nil
month(24005)''')
check(run('return A.st.feat.stats.m[#A.st.feat.stats.m]:find(";4:2000000,0,0", 1, true) ~= nil') is True,
      "the next month, readable and known for 5 s: measured")
# a gone company is not measured
run('''A.st.co.list[4].gone = "bankrupt"; B.st.co.list[4].gone = "bankrupt"
month(24006)''')
check(run('return A.st.feat.stats.m[#A.st.feat.stats.m]:find(";4:", 1, true) == nil and A.st.feat.stats.last == 24006') is True,
      "a gone (bankrupt) company is not measured")
# infinite money (the game's balance nil, the account's far beyond any goal): the figures still go, kept in bounds
run('''local real = api.engine.util.finance.getPlayersBalance
api.engine.util.finance.getPlayersBalance = function(p) if p == 100 then return nil end return real(p) end
BAL[100] = 4e18
newMonth(24007); guiAll(1)
api.engine.util.finance.getPlayersBalance = real
BAL[100] = 5000000''')
check(run('return A.st.feat.stats.last') == 24007 and run('return A.st.feat.stats.m[#A.st.feat.stats.m]:find("|1:100000000000000,", 1, true) ~= nil') is True,
      "infinite money: the account's balance, bounded, and the month is taken")
# the ring and the years
run('''for mi = 24007, 24040 do month(mi) end''')
check(run("return #A.st.feat.stats.m") == 24, "24 months kept for the graph")
check(run('''local t = {} for _, e in ipairs(A.st.feat.stats.y) do t[#t + 1] = e:match("^(%d+)|(%d+)") end return table.concat(t, ",")''')
      == "2000,2001,2002,2003", "one entry per game year: the start, then each 1st of January")
check(run('return A.st.feat.stats.y[2]:match("^2001|(%d+)|")') == "24013", "the year's entry is January's figures (month 24013 = 2001/1)")
check(run("return feat(A) == feat(B) and #A.books + #B.books == 0") is True, "both games agree; no money moved")
check(run(r'''local fa = A.files["feat_stats.txt"] local fb = B.files["feat_stats.txt"]
local function strip(s) return (s:gsub("host\t%d\n", ""):gsub("me\t%d+\n", "")) end
return strip(fa) == strip(fb)''') is True, "the window's file is the same on both games but 'host' and 'me'")

# ---------------------------------------------------------------- the goal by value, with a target
print("goal: value with a target")
run("reset()" + COS + '''
for _, g in ipairs(GAMES) do opts(g, { goal = true, ["goal.criterion"] = "value", ["goal.target"] = 10, ["goal.years"] = 5 }) end
hostFigures(A, 1, 5000000, 0, {})
hostFigures(A, 2, 4000000, 0, {})
hostFigures(A, 3, 50000000, 0, {})      -- the computer company far ahead
month(24001)''')
check(run("return A.st.feat.stats.goal.state") == "run" and run("return A.st.feat.stats.goal.endM") == 24001 + 60,
      "the goal starts at the month's start, 5 game years long")
check(run("return A.st.feat.stats.goal.target") == 10000000, "target $10 M")
check(run("return A.st.feat.stats.goal.state") == "run", "a computer company above the target does not win (A2)")
run('''hostFigures(A, 1, 6000000, 0, { 4000000 })   -- 10 M exactly with its vehicles
hostFigures(A, 2, 12000000, 3000000, {})        -- 12 M of money but 3 M of loans: 9 M
month(24002)''')
check(run("return A.st.feat.stats.goal.state") == "won" and run("return A.st.feat.stats.goal.winner") == 1,
      "company 1 reaches $10 M (money - loans + vehicles) and wins; company 2's loans count")
check(run("return A.st.feat.stats.goal.how") == "target", "won by the target")
check(run("return A.st.feat.stats.goal.final") == "3:50000000:ai;1:10000000;2:9000000", "the final ranking: everybody, the computer company too")
check(run('return A.st.feat.stats.goal.names') == "3=Robot|1=Host Rail|2=Bob Trans", "the final names frozen")
check(run("return feat(A) == feat(B)") is True, "both games: the same winner")
run("for _, g in ipairs(GAMES) do g.chats = {} end; month(24003)")
check(run("return A.st.feat.stats.goal.state") == "won", "the game goes on, the goal stays won")
check(run("return A.st.feat.stats.goal.seq") == 1, "no new goal while the rules are the same")
# the notice of the end: told on both games in their language, once
run("reset()" + COS + '''
for _, g in ipairs(GAMES) do opts(g, { goal = true, ["goal.target"] = 10, ["goal.years"] = 5 }) end
hostFigures(A, 1, 5000000, 0, {}); hostFigures(A, 2, 4000000, 0, {}); hostFigures(A, 3, 1000000, 0, {})
month(24001); guiAll(1)
CH1A, CH1B = #A.chats, #B.chats
hostFigures(A, 2, 11000000, 0, {})
month(24002); guiAll(1); guiAll(1)''')
check(run("return CH1A") == 0 and run("return CH1B") == 0, "the goal there at the first look is not told")
check(run('return A.chats[1]') == "Objectif atteint ! Bob Trans remporte la partie. La partie continue."
      and run('return B.chats[1]') == "Goal reached! Bob Trans wins the game. The game goes on.",
      "the end told in each game's language (French on the host, English on the client)")
check(run("return #A.chats") == 1 and run("return #B.chats") == 1, "told once")

# ties, and the time
print("goal: the best at the end, ties")
run("reset()" + COS + '''
for _, g in ipairs(GAMES) do opts(g, { goal = true, ["goal.criterion"] = "money", ["goal.target"] = 0, ["goal.years"] = 5 }) end
hostFigures(A, 1, 7000000, 0, { 9000000 })
hostFigures(A, 2, 9000000, 2000000, {})
hostFigures(A, 3, 90000000, 0, {})
for mi = 24001, 24060 do month(mi) end''')
check(run("return A.st.feat.stats.goal.state") == "run", "no target: the goal runs until its length is over")
run("month(24061)")
check(run("return A.st.feat.stats.goal.state") == "won" and run("return A.st.feat.stats.goal.how") == "time",
      "5 years later the best one wins")
check(run("return A.st.feat.stats.goal.winner") == 1, "money criterion: money - loans (7 M and 7 M: a tie), the smaller number wins; vehicles do not count")
check(run("return feat(A) == feat(B)") is True, "both games agree")

# computer companies allowed to win
print("goal: computer companies can win")
run("reset()" + COS + '''
for _, g in ipairs(GAMES) do opts(g, { goal = true, ["goal.target"] = 10, ["goal.ai_can_win"] = 1 }) end
hostFigures(A, 1, 1000000, 0, {}); hostFigures(A, 2, 1000000, 0, {}); hostFigures(A, 3, 12000000, 0, {})
month(24001)''')
check(run("return A.st.feat.stats.goal.winner") == 3, "the host's box lets a computer company win")

# a gone company, and the time with nobody allowed to win
print("goal: a gone company, nobody to win")
run("reset()" + COS + '''
for _, g in ipairs(GAMES) do opts(g, { goal = true, ["goal.target"] = 10, ["goal.years"] = 5 }) end
hostFigures(A, 1, 1000000, 0, {}); hostFigures(A, 2, 20000000, 0, {}); hostFigures(A, 3, 1000000, 0, {})
newMonth(24001)
for _, g in ipairs(GAMES) do g.st.co.list[2].gone = "bankrupt" end
-- (the host's figures measured just before the bankruptcy: company 2 above the target)
apply("f_stats_sample", { mi = 24001, rows = "1:1000000,0,0;2:20000000,0,0;3:1000000,0,0" }, "host")''')
check(run("return A.st.feat.stats.last") == 24001 and run("return A.st.feat.stats.goal.state") == "run",
      "a gone (bankrupt) company does not win, even with figures above the target")
run('''for _, g in ipairs(GAMES) do g.st.co.list[1].gone = "merged" end
for mi = 24002, 24061 do month(mi) end''')
check(run("return A.st.feat.stats.goal.state") == "ended" and run("return A.st.feat.stats.goal.winner") is None,
      "the time is over with only a computer company left: no winner")
check(run("return A.st.feat.stats.goal.final") == "3:1000000:ai", "the final ranking: the live companies only")

# tenders
print("goal: tenders")
run("reset()" + COS + '''
for _, g in ipairs(GAMES) do
  opts(g, { goal = true, tenders = true, ["goal.criterion"] = "tenders", ["goal.wins"] = 3 })
  g.st.feat = { tenders = { wins = { ["1"] = 1, ["2"] = 2, ["3"] = 9 } } }
end
hostFigures(A, 1, 1000000, 0, {}); hostFigures(A, 2, 1000000, 0, {}); hostFigures(A, 3, 1000000, 0, {})
month(24001)''')
check(run("return A.st.feat.stats.goal.crit") == "tenders" and run("return A.st.feat.stats.goal.target") == 3,
      "the tenders criterion while the tenders option is on (B7): 3 tenders")
check(run("return A.st.feat.stats.goal.state") == "run", "the computer company's 9 tenders do not win")
run('''for _, g in ipairs(GAMES) do g.st.feat.tenders.wins["2"] = 3 end
month(24002)''')
check(run("return A.st.feat.stats.goal.winner") == 2, "company 2 wins its 3rd tender: it wins the goal")
check(run('return A.files["feat_stats.txt"]:find("tw\t1:1;2:3;3:9", 1, true) ~= nil') is True, "the tenders won in the window's file")
run('''for _, g in ipairs(GAMES) do g.st.feat.tenders = { done = { { status = "won", winner = 1 }, { status = "expired" }, { status = "won", winner = 1 } } } end''')
check(run("return M.tenderWins(A.st, 1)") == 2 and run("return M.tenderWins(A.st, 2)") == 0, "the tenders won read from a 'done' list too")
check(run("return M.tenderWins({ feat = { tenders = 'x' } }, 1)") == 0 and run("return M.tenderWins({}, 1)") == 0,
      "no tenders state, or a strange one: 0")
run("reset()" + COS + '''
for _, g in ipairs(GAMES) do opts(g, { goal = true, ["goal.criterion"] = "tenders", ["goal.target"] = 25 }) end
newMonth(24001)''')
check(run("return A.st.feat.stats.goal.crit") == "value" and run("return A.st.feat.stats.goal.want") == "tenders"
      and run("return A.st.feat.stats.goal.target") == 25000000, "tenders option off: the goal counts the value (with the money target)")

# the host's cancel, the option off, a new goal
print("goal: cancel, off, a new goal")
run("reset()" + COS + '''
for _, g in ipairs(GAMES) do opts(g, { goal = true, stats = true, ["goal.target"] = 500 }) end
hostFigures(A, 1, 1000000, 0, {}); hostFigures(A, 2, 1000000, 0, {}); hostFigures(A, 3, 1000000, 0, {})
month(24001)
CLIENT_REQ = B.M.request("cancel", "", B.st, guiEnv(B))
CLIENT_SENT = #B.sent
apply("f_stats_cancel", { seq = 1 }, "bob#1")''')
check(run("return CLIENT_REQ") is False and run("return CLIENT_SENT") == 0, "a client's window cannot cancel the goal (nothing sent)")
check(run("return A.st.feat.stats.goal.state") == "run", "a client's cancel event is refused")
run('''apply("f_stats_cancel", { seq = 7 }, "host")''')
check(run("return A.st.feat.stats.goal.state") == "run", "a cancel of another goal is refused")
run('''HOST_REQ = A.M.request("cancel", "", A.st, guiEnv(A)); guiAll(1)''')
check(run("return HOST_REQ") is True and run("return A.st.feat.stats.goal.state") == "cancelled"
      and run("return B.st.feat.stats.goal.how") == "host", "the host cancels from its window: cancelled on every game (A5)")
run("month(24002)")
check(run("return A.st.feat.stats.goal.seq") == 1, "a cancelled goal does not start again with the same rules")
run('''for _, g in ipairs(GAMES) do g.st.opts["goal.years"] = 30 end
month(24003)''')
check(run("return A.st.feat.stats.goal.seq") == 2 and run("return A.st.feat.stats.goal.years") == 30
      and run("return A.st.feat.stats.goal.state") == "run", "new rules after the end: a new goal")
run('''for _, g in ipairs(GAMES) do g.st.opts["goal.years"] = 50 end
month(24004)''')
check(run("return A.st.feat.stats.goal.seq") == 2 and run("return A.st.feat.stats.goal.years") == 30,
      "the rules of a running goal no longer change (A5)")
run('''for _, g in ipairs(GAMES) do g.st.opts.goal = nil end
month(24005)''')
check(run("return A.st.feat.stats.goal.state") == "cancelled" and run("return A.st.feat.stats.goal.how") == "off",
      "the goal option switched off: the running goal is cancelled")
run('''for _, g in ipairs(GAMES) do g.st.opts.goal = true end
month(24006)''')
check(run("return A.st.feat.stats.goal.seq") == 3 and run("return A.st.feat.stats.goal.state") == "run",
      "switched on again: a new goal")
check(run("return feat(A) == feat(B)") is True, "both games agree through all of it")
check(run('return table.concat(B.chats, "/")') == "The host cancelled the goal./Game goal: Company value, target $500.0 M, 30 years."
      "/The host switched the goal off./Game goal: Company value, target $500.0 M, 50 years.",
      "each change of the goal told in the chat (the client's, in English)")
check(run('return A.chats[2]') == "Objectif de partie : Valeur de l'entreprise, cible $500.0 M, 30 ans.", "and in French on the host")
# every option off with a goal running in the state: cancelled, and nothing else
run('''for _, g in ipairs(GAMES) do g.st.opts = {} end
SENT0, WR0 = #A.sent, A.writes
month(24007)''')
check(run("return A.st.feat.stats.goal.state") == "cancelled" and run("return A.writes == WR0 and #A.sent == SENT0") is True,
      "every option off later: the running goal is cancelled, no file written, nothing sent")

# ---------------------------------------------------------------- the yearly report
print("yearly report")
run("reset()" + COS + '''
for _, g in ipairs(GAMES) do opts(g, { yearly = true }) end
hostFigures(A, 1, 5000000, 0, { 1000000 }); hostFigures(A, 2, 2000000, 500000, {}); hostFigures(A, 3, 3000000, 0, {})
for mi = 24010, 24012 do month(mi) end
hostFigures(A, 1, 7000000, 0, { 1000000 }); hostFigures(A, 2, 1000000, 0, {}); hostFigures(A, 3, 4000000, 0, {})
month(24013); guiAll(1)''')
check(run('return A.chats[1]') == "Bilan 2000 :" and run('return B.chats[1]') == "2000 in review:", "at a new game year: the year in review, in each game's language")
check(run('return B.chats[2]') == "1. Host Rail: value $8.0 M (+$2.0 M), money $7.0 M, vehicles $1.0 M"
      and run('return B.chats[3]') == "2. Robot (AI): value $4.0 M (+$1.0 M), money $4.0 M, vehicles $0"
      and run('return B.chats[4]') == "3. Bob Trans: value $1.0 M (-$500 k), money $1.0 M, vehicles $0",
      "every company (A6), best value first, the computer company too, with the year's change")
check(run('return A.chats[2]') == "1. Host Rail : valeur $8.0 M (+$2.0 M), argent $7.0 M, véhicules $1.0 M", "the French lines")
check(run("return #A.chats") == 4 and run("return #B.chats") == 4, "told once (one header, one line a company)")
run("for mi = 24014, 24024 do month(mi) end")
check(run("return #B.chats") == 4, "nothing more during the year")
# a reload of the GUI (a resynchronisation): a year already there is not told again
run("for _, g in ipairs(GAMES) do g.M = loadModule() end; guiAll(1); guiAll(1)")
check(run("return #B.chats") == 4, "after a reload, the last year is not told again")
run("month(24025); guiAll(1)")
check(run("return #B.chats") == 8 and run("return B.chats[5]") == "2001 in review:", "the next year is told")
run('''for _, g in ipairs(GAMES) do g.st.co.list[2].gone = "bankrupt" end
for mi = 24026, 24037 do month(mi) end''')
check(run("return B.chats[#B.chats - 2]") == "2002 in review:" and run("return #B.chats") == 11,
      "a bankrupt company is no longer in the next year's review")

# ---------------------------------------------------------------- the savegame: plain data, a reload, the same outcome
print("savegame")
run("reset()" + COS + '''
for _, g in ipairs(GAMES) do opts(g, { goal = true, stats = true, yearly = true, ["goal.target"] = 50, ["goal.years"] = 5 }) end
hostFigures(A, 1, 5000000, 0, { 1000000 }); hostFigures(A, 2, 2000000, 500000, {}); hostFigures(A, 3, 3000000, 0, {})
for mi = 24001, 24020 do month(mi) end
SAVED = ser(A.st)''')
check(run("return type(SAVED)") == "string", "the state is plain data (no function, no userdata, no cycle)")
run('''
-- game C: the same savegame loaded (by a new client, other entities), then the same events on all three games
C = newGame("carl", 9000, "en", false)
C.st = assert(load("return " .. SAVED))()
for _, c in ipairs(C.st.co.list) do c.ent = 9000 + 100 * c.id end
GAMES = { A, B, C }
guiAll(1)
NB = #B.chats
hostFigures(A, 2, 60000000, 0, {})
for mi = 24021, 24030 do month(mi) end
guiAll(1)''')
check(run("return feat(A) == feat(C) and feat(A) == feat(B)") is True, "a game loaded from the savegame keeps going like the others")
check(run("return C.st.feat.stats.goal.winner") == 2, "the reloaded game finds the same winner")
check(run('''local t = {} for i = NB + 1, #B.chats do t[#t + 1] = B.chats[i] end return table.concat(t, "/") == table.concat(C.chats, "/") and #C.chats > 0''') is True,
      "the reloaded game tells what happened after its load, as the others do")
run('''
-- game D: the savegame of after the end loaded: the end is not told again
D = newGame("dan", 12000, "en", false)
D.st = assert(load("return " .. ser(A.st)))()
GAMES = { A, B, C, D }
guiAll(1); guiAll(1); month(24031); guiAll(1)''')
check(run("return #D.chats") == 0 and run("return D.st.feat.stats.goal.state") == "won", "a savegame loaded after the end: nothing told again")

# determinism: the same events in the same order, other entities, other languages: the same state
print("determinism")
DET = COS + '''
for _, g in ipairs(GAMES) do opts(g, { goal = true, stats = true, yearly = true, ["goal.target"] = 25, ["goal.years"] = 10 }) end
for mi = 24001, 24050 do
  hostFigures(A, 1, 1000000 * (mi % 7), (mi % 3) * 100000, { 50000 * (mi % 5) })
  hostFigures(A, 2, 1000000 * (mi % 11), 0, { 100000 })
  hostFigures(A, 3, 500000 * (mi % 13), 0, {})
  newMonth(mi); guiAll(6)
end
'''
run("reset()" + DET + "RUN1 = feat(A)")
run("reset()" + DET + "RUN2 = feat(B)")
check(run("return RUN1 == RUN2") is True, "two runs, two games: the same state")
check(run("return RUN1 == feat(A)") is True, "the host's and the client's states equal")

# ---------------------------------------------------------------- the window's tab
print("window")
UI = r'''
NODES, REQS = {}, {}
function makeU(g, lang, withChart)
  local u = { T = function(fr, en) if lang == "fr" then return fr end return en end }
  u.read = function(file)
    local s = g.files[file]
    if not s then return nil end
    local t = {} for l in (s .. "\n"):gmatch("([^\n]*)\n") do t[#t + 1] = l end
    return t
  end
  u.request = function(kind, payload) REQS[#REQS + 1] = kind .. ":" .. tostring(payload) end
  u.text = function(t, kind) return { k = "text", t = t, kind = kind } end
  u.button = function(label, fn, on) return { k = "button", t = label, fn = fn, on = on } end
  u.row = function(nodes) return { k = "row", nodes = nodes } end
  u.table = function(head, rows) return { k = "table", head = head, rows = rows } end
  if withChart then u.chart = function(spec) return { k = "chart", spec = spec } end end
  return u
end
function flat(nodes)
  local out = {}
  local function walk(n)
    if n.k == "row" then for _, x in ipairs(n.nodes) do walk(x) end return end
    if n.k == "table" then out[#out + 1] = "[" .. table.concat(n.head, "|") .. "]" for _, r in ipairs(n.rows) do out[#out + 1] = table.concat(r, "|") end return end
    if n.k == "chart" then out[#out + 1] = "<chart " .. #n.spec.series .. ">" return end
    out[#out + 1] = n.t
  end
  for _, n in ipairs(nodes) do walk(n) end
  return table.concat(out, "\n")
end
function press(nodes, label)
  local function walk(n)
    if n.k == "row" then for _, x in ipairs(n.nodes) do if walk(x) then return true end end end
    if n.k == "button" and n.t == label then n.fn() return true end
    return false
  end
  for _, n in ipairs(nodes) do if walk(n) then return true end end
  return false
end
'''
L.execute(UI)
run("reset()" + COS + '''
for _, g in ipairs(GAMES) do opts(g, { goal = true, stats = true, ["goal.target"] = 50, ["goal.years"] = 5 }) end
hostFigures(A, 1, 5000000, 0, { 1000000 }); hostFigures(A, 2, 2000000, 500000, {}); hostFigures(A, 3, 30000000, 0, {})
for mi = 24001, 24014 do month(mi) end
TAB_EN = flat(B.M.ui(makeU(B, "en", true)))
TAB_FR = flat(A.M.ui(makeU(A, "fr", false)))''')
tab_en = run("return TAB_EN")
tab_fr = run("return TAB_FR")
check("Game goal" in tab_en and "Criterion: Company value. Target: $50.0 M. Length: 5 years." in tab_en, "the goal's rules (English)")
check("Computer companies are ranked but cannot win." in tab_en, "the computer companies' rule told")
check("Time left: 3 year(s) and 11 month(s)." in tab_en, "the time left")
check("Leading: Host Rail (dollars)".replace(" (dollars)", "") in tab_en and "Leading: Host Rail ($6.0 M of $50.0 M)." in tab_en,
      "the leader among the companies that may win, with the target")
check("1|Robot (AI)|$30.0 M|$30.0 M|$0" in tab_en and "2|Host Rail|$6.0 M|$5.0 M|$1.0 M" in tab_en
      and "3|Bob Trans (you)|$1.5 M|$1.5 M|$0" in tab_en, "the ranking: every company, value, money, vehicles, (AI) and (you)")
check("Value = money - loans + resale value of the vehicles" in tab_en, "the value explained (A3)")
check("<chart 3>" in tab_en, "the graph: one series per company (with a chart)")
check("Cancel the goal" not in tab_en, "no cancel button on a client")
check("Objectif de partie" in tab_fr and "Annuler l'objectif" in tab_fr and "[Entreprise|Maintenant|Il y a 6 mois|Il y a 12 mois]" in tab_fr,
      "French: the goal, the host's cancel button, the graph's figures as a table without a chart")
# the host cancels from the tab: two clicks, then the request goes to its game's module
run('''
local u = makeU(A, "fr", true)
local nodes = A.M.ui(u)
P1 = press(nodes, "Annuler l'objectif")
nodes = A.M.ui(u)
P2 = press(nodes, "Confirmer l'annulation")''')
check(run("return P1 and P2") is True and run("return REQS[1]") == "cancel:1", "the host's cancel asks to confirm, then requests 'cancel'")
# graph choices
run('''
local u = makeU(B, "en", false)
press(B.M.ui(u), "Money"); press(B.M.ui(u), "Whole game (yearly)")
TAB_Y = flat(B.M.ui(u))''')
check("[Company|Now|2001|2000]" in run("return TAB_Y") and "Robot (AI)|$30.0 M|$30.0 M|$30.0 M" in run("return TAB_Y")
      and "Host Rail|$5.0 M|" in run("return TAB_Y"),
      "the graph by money over the whole game (one figure a year)")
# the end of the goal in the tab
run('''hostFigures(A, 1, 60000000, 0, {})
month(24015)
TAB_END = flat(B.M.ui(makeU(B, "en", true)))''')
tab_end = run("return TAB_END")
check("Goal reached! Host Rail wins the game." in tab_end and "Final ranking" in tab_end and "1|Host Rail|$60.0 M" in tab_end
      and "2|Robot (AI)|$30.0 M" in tab_end, "the end: the winner and the final ranking")
check("The game goes on." in tab_end, "the game goes on")
# only the yearly option on: the tab has the ranking but no graph
run("reset()" + COS + '''
for _, g in ipairs(GAMES) do opts(g, { yearly = true }) end
hostFigures(A, 1, 5000000, 0, {}); hostFigures(A, 2, 2000000, 0, {}); hostFigures(A, 3, 3000000, 0, {})
month(24001); guiAll(1)
TAB_Y2 = flat(B.M.ui(makeU(B, "en", true)))''')
check("History" not in run("return TAB_Y2") and "Ranking" in run("return TAB_Y2") and "1|Host Rail|$5.0 M|$5.0 M|$0" in run("return TAB_Y2"),
      "only the yearly option: the ranking, no graph (graphs with the stats option, A4)")
# a window without some helpers still draws
check(run('''local r = B.M.ui({ T = function(fr, en) return en end, read = makeU(B, "en").read, text = function(t) return t end })
return table.concat(r, "\\n")''').find("1   Host Rail   $5.0 M   $5.0 M   $0") >= 0, "a window with text only: the table's rows as texts")

if failures:
    print(f"FAIL {len(failures)} case(s):")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("PASS all cases")
sys.exit(0)
