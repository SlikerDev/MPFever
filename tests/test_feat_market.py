"""Offline test of the 0.6 game option "Competition" (mod/mpfever_1/content/mpfever_feat_market.lua): market shares per
town, who serves each industry, competition alerts (release/recherche-0.6/03-parts-de-marche.md, decisions C1 to C6).

The module is loaded through lupa (Lua 5.2) without the game's API, once per simulated game (each its own Lua state, as
each player's game), with the env of the contract (docs/FEATURES-0.6.md: env.on, env.param, env.state, env.mode,
env.companies, env.month, env.money, env.book, ... in the simulation half; env.isHost, env.myCo, env.send, env.chat,
env.write, env.realTime in the GUI half) and its engine readers (M.engine) replaced by a small mocked map. The events the
host's game sends are serialized and applied by every game in the same order, as the lockstep does.

Cases: option off and "shared" mode (nothing at all: no state, no event, no file, no chat, no engine read, no money); the
host's measure (passengers from the rank's average, cargo per line's owner, stations per company, industries' servers) and
the exact event it sends; a client never measures nor sends; the first measure is the reference (no alert); a competitor
arriving in a town, first place lost (with its margin), never told to a computer company; the alerts' parameter off; a
company gone (bankrupt); a measure sent again or older (left out); a malformed event; determinism on two games and after a
savegame reload (plain data, no function, no userdata, no cycle); nothing told again after a reload; the event sent again
when it was lost (and not before); the measure spread over the calls of a big map; the window's file, the tab's content
in French and English and its widgets; the option's declaration.
Run: python tests/test_feat_market.py
"""
import os
import re
import sys

try:
    import lupa.lua52 as lua52
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "..", "mod", "mpfever_1", "content", "mpfever_feat_market.lua"), encoding="utf-8").read()

# one game: its own Lua state with the module, the game script state st, the two envs and the mocked map
HARNESS = r'''
assert(api == nil, "no game API in the test")
M = assert(load(SRC, "mpfever_feat_market.lua"))()

G = { sent = {}, chat = {}, files = {}, writes = 0, log = {}, booked = {}, moneyCalls = 0, clock = 0, month = 24000,
      mode = "separate", isHost = false, myCo = nil, step = 0, calls = 0, listGone = false }

-- a deterministic serializer (sorted keys) that refuses anything but plain data: what a savegame keeps
function ser(v)
  local t = type(v)
  if t == "number" then
    assert(v == v and v ~= math.huge and v ~= -math.huge, "a number that is not finite")
    if v == math.floor(v) and math.abs(v) < 2^53 then return string.format("%d", v) end
    return string.format("%.17g", v)
  elseif t == "string" then return string.format("%q", v)
  elseif t == "boolean" then return tostring(v)
  elseif t == "table" then
    local keys = {}
    for k in pairs(v) do keys[#keys + 1] = k end
    table.sort(keys, function(a, b) if type(a) ~= type(b) then return type(a) < type(b) end return a < b end)
    local parts = {}
    for _, k in ipairs(keys) do parts[#parts + 1] = "[" .. ser(k) .. "]=" .. ser(v[k]) end
    return "{" .. table.concat(parts, ",") .. "}"
  end
  error("not plain data: a " .. t)
end
function deser(s) return assert(load("return " .. s, "data", "t", {}))() end

-- plain data: tables (no metatable, each reached once: no cycle, nothing shared), strings, finite numbers, booleans; keys
-- strings or whole numbers from 1. Returns nil or what is wrong
function plain(v)
  local seen = {}
  local function walk(x, path)
    local t = type(x)
    if t == "string" or t == "boolean" then return nil end
    if t == "number" then if x ~= x or x == math.huge or x == -math.huge then return path .. ": not finite" end return nil end
    if t ~= "table" then return path .. ": a " .. t end
    if getmetatable(x) ~= nil then return path .. ": a metatable" end
    if seen[x] then return path .. ": reached twice (a cycle or a shared table)" end
    seen[x] = true
    for k, y in pairs(x) do
      if not (type(k) == "string" or (type(k) == "number" and k >= 1 and k == math.floor(k))) then return path .. ": key " .. tostring(k) end
      local e = walk(y, path .. "." .. tostring(k))
      if e then return e end
    end
    return nil
  end
  return walk(v, "st")
end

-- the options as st.opts holds them (the same on every game): env.on and env.param read them, the parameters with their
-- default
local function on(id) return (st.opts or {})[id] == 1 end
local function param(id, pid)
  local v = (st.opts or {})[id .. "." .. pid]
  if v ~= nil then return v end
  for _, o in ipairs(M.OPTIONS) do
    if o.id == id then for _, p in ipairs(o.params or {}) do if p.id == pid then return p.default end end end
  end
  return nil
end

-- the simulation half's env (contract): every game, at the same step
simEnv = {
  STEP = 200,
  log = function(s) G.log[#G.log + 1] = s end,
  gameTime = function() return G.step * 200 end,
  on = on, param = param,
  state = function(s) s.feat = s.feat or {}; s.feat.market = s.feat.market or {}; return s.feat.market end,
  companies = function()
    local out = {}
    for _, c in ipairs(st.co and st.co.list or {}) do
      if c.ent and (G.listGone or not c.gone) then
        out[#out + 1] = { id = c.id, ent = c.ent, name = c.name, ai = tostring(c.key):sub(1, 3) == "ai:", members = {}, gone = c.gone }
      end
    end
    table.sort(out, function(a, b) return a.id < b.id end)
    return out
  end,
  money = function(ent) G.moneyCalls = G.moneyCalls + 1; return 0 end,
  book = function(ent, amount) G.booked[#G.booked + 1] = { ent, amount } end,
  R = {},
  every = function(n) return G.step % n == 0 end,
  month = function() return G.month end,
}
setmetatable(simEnv, { __index = function(_, k) if k == "mode" then return G.mode end if k == "co" then return G.mode == "separate" and st.co or nil end end })

-- the GUI half's env (contract): no mode in it (the module reads the registry's)
guiEnv = {
  log = function(s) G.log[#G.log + 1] = s end,
  on = on, param = param,
  send = function(name, p) G.sent[#G.sent + 1] = { name = name, s = ser(p) } end,
  chat = function(text) G.chat[#G.chat + 1] = text end,
  write = function(file, lines)
    local txt = table.concat(lines, "\n")
    if G.files[file] ~= txt then G.files[file] = txt; G.writes = G.writes + 1 end
  end,
  realTime = function() return G.clock end,
}
setmetatable(guiEnv, { __index = function(_, k) if k == "isHost" then return G.isHost end if k == "myCo" then return G.myCo end if k == "me" then return G.me end end })

-- the simulation half must not read a clock, a random number or the engine
function simCall(fn, ...)
  local ot, oc, mr = os.time, os.clock, math.random
  local function no(what) return function() error(what .. " in the simulation half", 0) end end
  os.time, os.clock, math.random = no("os.time"), no("os.clock"), no("math.random")
  local ok, err = pcall(fn, ...)
  os.time, os.clock, math.random = ot, oc, mr
  if not ok then error(err, 0) end
end

-- the mocked map the host's measure reads (M.engine), every read counted
WORLD = { lines = {}, owner = {}, towns = {}, t2s = {}, deliv = {}, sgOf = {}, sgStations = {}, catch = {}, inds = {}, names = {} }
CALLS = { deliveries = 0 }
FOCUSED = nil
local function counted(name, fn)
  return function(...) G.calls = G.calls + 1; CALLS[name] = (CALLS[name] or 0) + 1; return fn(...) end
end
local E = M.engine
E.ownerOf = counted("ownerOf", function(e) return WORLD.owner[e] end)
E.lines = counted("lines", function() local l = {} for k in pairs(WORLD.lines) do l[#l + 1] = k end table.sort(l) return l end)
E.lineGroups = counted("lineGroups", function(l) return WORLD.lines[l] or {} end)
E.towns = counted("towns", function() local out = {} for _, t in ipairs(WORLD.towns) do out[#out + 1] = { town = t[1], pop = t[2] } end return out end)
E.townStations = counted("townStations", function() return WORLD.t2s end)
E.halfYear = counted("halfYear", function() return 365000 end)
E.deliveries = counted("deliveries", function(town) return WORLD.deliv[town] or {} end)
E.stationGroup = counted("stationGroup", function(s) return WORLD.sgOf[s] end)
E.groupStations = counted("groupStations", function(sg) return WORLD.sgStations[sg] or {} end)
E.catchables = counted("catchables", function(s) return WORLD.catch[s] or {} end)
E.industries = counted("industries", function() local out = {} for _, x in ipairs(WORLD.inds) do out[#out + 1] = { ind = x[1], stockList = x[2] } end return out end)
E.name = function(e) return WORLD.names[e] or ("#" .. tostring(e)) end
E.companyName = function(c) return (c.name ~= "" and c.name) or "Host Co" end
E.focusTown = function(t) FOCUSED = t; return true end

-- a station of a company in a town (or none), in a station group, stopped at by a line of that company
function addStop(owner, line, station, sg, town)
  WORLD.owner[station] = owner
  WORLD.owner[line] = owner
  WORLD.sgOf[station] = sg
  WORLD.sgStations[sg] = WORLD.sgStations[sg] or {}
  table.insert(WORLD.sgStations[sg], station)
  WORLD.lines[line] = WORLD.lines[line] or {}
  table.insert(WORLD.lines[line], sg)
  if town then WORLD.t2s[town] = WORLD.t2s[town] or {}; table.insert(WORLD.t2s[town], station) end
end

function gui(n) for i = 1, n or 1 do G.clock = G.clock + 1; M.gui(st, guiEnv) end end
function newMonth(m) G.month = m; simCall(M.month, st, simEnv) end
function deliver(s) simCall(M.event, st, "f_market_snap", deser(s), simEnv) end
function stateSer() return ser(st.feat and st.feat.market or {}) end
function sentCount() return #G.sent end
function sentAt(k) return G.sent[k].name, G.sent[k].s end
'''

# the companies of every game: the savegame's (the host's), Bob's, a computer company
COMPANIES = r'''
st = { opts = OPTS, co = { mode = MODE, list = {
  { id = 1, key = "", name = "", ent = 100, color = 1 },
  { id = 2, key = "bob", name = "Bob Co", ent = 200, color = 2 },
  { id = 3, key = "ai:1", name = "Robot Co", ent = 300, color = 3 },
} }, prog = { passengers = {
  { company = 1, town = 1001, value = 12.34 }, { company = 1, town = 1002, value = 5.0 },
  { company = 2, town = 1002, value = 5.0 }, { company = 3, town = 1003, value = 2.0 },
} } }
'''

# the map: towns Alpha (1001), Beta (1002), Gamma (1003), Delta (1004, nobody); the host's line L1 in Alpha and Beta, Bob's
# L2 in Beta, the computer's L3 in Gamma and at a mine (industry 701, stock list 801); L1's Beta station also takes the
# goods of a factory (702, stock list 802); a line of a player of no company (999) counts for nobody
WORLD1 = r'''
WORLD.towns = { { 1001, 5000 }, { 1002, 3000 }, { 1003, 800 }, { 1004, 100 } }
WORLD.names = { [1001] = "Alpha", [1002] = "Beta", [1003] = "Gamma", [1004] = "Delta", [701] = "Mine", [702] = "Factory" }
addStop(100, 11, 601, 501, 1001)
addStop(100, 11, 602, 502, 1002)
addStop(200, 12, 603, 503, 1002)
addStop(300, 13, 604, 504, 1003)
addStop(300, 13, 605, 505, nil)
addStop(999, 19, 609, 509, 1004)
WORLD.deliv = { [1001] = { [11] = 50, [19] = 99 }, [1002] = { [11] = 10, [12] = 30 }, [1003] = { [13] = 20 } }
WORLD.inds = { { 701, 801 }, { 702, 802 }, { 703, 803 } }
WORLD.catch = { [605] = { 801 }, [602] = { 802 } }
'''

# a month later: Bob opens a stop in Alpha; the computer company arrives in Beta with much cargo (first place); the host's
# company opens a station in Gamma, where only the computer company was
WORLD2 = r'''
addStop(200, 14, 606, 506, 1001)
addStop(300, 15, 607, 507, 1002)
addStop(100, 16, 608, 508, 1003)
WORLD.deliv[1002][15] = 200
'''

failures = []


def check(cond, what):
    print(("  ok    " if cond else "  FAIL  ") + what)
    if not cond:
        failures.append(what)


class Game:
    def __init__(self, name, is_host=False, my_co=None, opts="{ market = 1 }", mode="separate", world=True):
        self.L = lua52.LuaRuntime(unpack_returned_tuples=True)
        g = self.L.globals()
        g.SRC = SRC
        self.L.execute(HARNESS)
        self.L.execute(f"OPTS = {opts}; MODE = {mode!r}")
        self.L.execute(COMPANIES)
        self.L.execute(f"G.isHost = {'true' if is_host else 'false'}; G.myCo = {my_co if my_co else 'nil'}; G.me = {name!r}; G.mode = MODE")
        if world:
            self.L.execute(WORLD1)
        self.name = name

    def run(self, code):
        return self.L.execute(code)

    def ev(self, expr):
        return self.L.eval(expr)

    def gui(self, n=1):
        self.L.globals().gui(n)

    def month(self, m):
        self.L.globals().newMonth(m)

    def deliver(self, s):
        self.L.globals().deliver(s)

    def state(self):
        return self.L.globals().stateSer()

    def sent(self):
        g = self.L.globals()
        return [g.sentAt(k) for k in range(1, g.sentCount() + 1)]

    def chat(self):
        return list(self.ev("G.chat").values())


def network(sender, games, start):
    """the events `sender` sent since `start`, applied by every game in the same order; returns the new start"""
    out = sender.sent()
    for name, s in out[start:]:
        check(name == "f_market_snap", f"{sender.name} sends f_market_snap ({name})")
        for g in games:
            g.deliver(s)
    return len(out)


def measure(host, games, start, calls=10):
    host.gui(calls)
    return network(host, games, start)


# ---------------------------------------------------------------------------------------------------- the declaration
print("the option's declaration")
d = Game("decl", world=False)
check(d.ev("M.ID") == "market", "module id market")
check(d.ev("#M.OPTIONS") == 1 and d.ev("M.OPTIONS[1].id") == "market", "one option: market")
check(d.ev("M.OPTIONS[1].modes") == "separate", "separate mode only")
check(d.ev("#M.OPTIONS[1].title == 2 and #M.OPTIONS[1].desc == 2"), "title and description in French and English")
check(d.ev("M.OPTIONS[1].params[1].id") == "alerts" and d.ev("M.OPTIONS[1].params[1].default") == 1, "parameter alerts, on by default")
check(d.ev("M.OPTIONS[1].params[1].show(1, function(fr, en) return en end)") == "Yes"
      and d.ev("M.OPTIONS[1].params[1].show(0, function(fr, en) return fr end)") == "Non", "the parameter's labels")
check(d.ev("(function() for k in pairs(M.EVENTS) do if k:sub(1, 9) ~= 'f_market_' then return false end end return M.EVENTS.f_market_snap == true end)()"),
      "events named f_market_*")
check(d.ev("M.TAB.id") == "market" and d.ev("M.TAB.title[2]") == "Competition", "the window's tab")
check(d.ev("(function() for k, p in pairs(M.TEXT) do if type(p[1]) ~= 'string' or type(p[2]) ~= 'string' then return k end end return true end)()") is True,
      "every text in French and English")

# ---------------------------------------------------------------------------------------------------- off: nothing at all
print("option off, and the shared mode: nothing happens")
for label, opts, mode in (("off", "{}", "separate"), ("off explicitly", "{ market = 0 }", "separate"), ("shared mode", "{ market = 1 }", "shared")):
    h = Game("host", True, 1, opts=opts, mode=mode)
    c = Game("bob", False, 2, opts=opts, mode=mode)
    if mode == "shared":
        for g in (h, c):
            g.run("st.co = nil")
    h.month(24001)
    c.month(24001)
    h.gui(40)
    c.gui(40)
    # (an event that would apply when on)
    for g in (h, c):
        g.deliver('{["month"]=24001,["t"]="1001,5000,1:10:0:1",["i"]=""}')
    check(all(g.ev("st.feat == nil") for g in (h, c)), f"{label}: no state")
    check(not h.sent() and not c.sent(), f"{label}: no event sent")
    check(all(g.ev("next(G.files) == nil and #G.chat == 0") for g in (h, c)), f"{label}: no file, no chat")
    check(all(g.ev("G.calls") == 0 for g in (h, c)), f"{label}: the map is never read")
    check(all(g.ev("#G.booked == 0 and G.moneyCalls == 0") for g in (h, c)), f"{label}: no money")

# ---------------------------------------------------------------------------------------------------- the first measure
print("the host's first measure (the option switched on in the middle of a month)")
host = Game("host", True, 1)
bob = Game("bob", False, 2)
games = [host, bob]
host.gui(1)
check(len(host.sent()) == 0, "the measure is spread: nothing sent after one call")
host.gui(9)
sent = host.sent()
check(len(sent) == 1, f"one event sent ({len(sent)})")
expect = '{["i"]="701:3;702:1",["month"]=-1,["t"]="1001,5000,1:123:50:1;1002,3000,1:50:10:1,2:50:30:1;1003,800,3:20:20:1"}'
check(sent and sent[0][1] == expect, "the measure: passengers from the rank's average (x10), cargo per line's owner, stations, industries' servers"
      + ("" if sent and sent[0][1] == expect else f"\n          got {sent[0][1] if sent else None}"))
bob.gui(40)
check(not bob.sent() and bob.ev("G.calls") == 0, "a client never measures nor sends")
check(host.ev("CALLS.deliveries") == 4, "one read of the deliveries per town")
start = network(host, games, 0)
check(host.state() == bob.state(), "the same state on both games")
check(host.ev("st.feat.market.month") == -1 and host.ev("#st.feat.market.towns") == 3, "three towns where a company is (Delta: nobody)")
check(host.ev("st.feat.market.seq") == 0 and host.ev("#st.feat.market.alerts") == 0, "the first measure is the reference: no alert")
check(host.ev("st.feat.market.towns[1].lead") == 1 and host.ev("st.feat.market.towns[2].lead") == 2 and host.ev("st.feat.market.towns[3].lead") == 3,
      "first place: the host in Alpha, Bob in Beta (cargo 75 %), the computer in Gamma")
check(host.ev("plain(st)") is None, "the game state is plain data")
host.gui(5)
check(len(host.sent()) == 1, "up to date: nothing sent again")
bob.gui(2)
f = bob.ev("G.files[M.FILE]") or ""
check("me\t2" in f and "tot\t2\t" in f and "town\t1002\t3000\t2\tBeta" in f and "ind\t702\t1\tFactory" in f,
      "the client's window file (its company, totals, towns, industries)")
check("tp\t1002\t2\t500\t750\t1" in f, "Bob's shares in Beta: passengers 50 %, cargo 75 %, one station")

# ---------------------------------------------------------------------------------------------------- a month later
print("a month later: competitors arrive, first place lost")
for g in games:
    g.run(WORLD2)
    g.month(24001)
check(host.state() == bob.state(), "the month due on both games")
start = measure(host, games, start)
check(len(host.sent()) == 2, "the measure of the month sent")
check(host.state() == bob.state(), "the same state on both games")
alerts = host.ev("(function() local t = {} for _, a in ipairs(st.feat.market.alerts) do t[#t + 1] = a.n .. ':' .. a.kind .. ':' .. a.co .. ':' .. a.by .. ':' .. a.town end return table.concat(t, ' ') end)()")
check(alerts == "1:arrive:1:2:1001 2:arrive:1:3:1002 3:arrive:2:3:1002 4:lead:2:3:1002",
      f"alerts: Bob arrives in Alpha (to the host), the computer arrives in Beta (to both), Bob loses Beta; none to the computer in Gamma ({alerts})")
check(host.ev("st.feat.market.towns[3].lead") == 3, "Gamma: the computer stays first (the host only has a station)")
host.gui(1)
bob.gui(1)
hc, bc = host.chat(), bob.chat()
check(hc == ["Competition: Bob Co arrives in Alpha, a town where you are.", "Competition: Robot Co arrives in Beta, a town where you are."],
      f"the host's chat: its two alerts ({hc})")
check(bc == ["Competition: Robot Co arrives in Beta, a town where you are.", "Competition: you lose first place in Beta, Robot Co takes the lead."],
      f"Bob's chat: its two alerts ({bc})")
host.gui(5)
check(len(host.chat()) == 2, "an alert is told once")
check(host.ev("plain(st)") is None, "still plain data")

# ---------------------------------------------------------------------------------------------------- reload
print("a savegame reload")
saved = bob.ev("ser(st)")
bob2 = Game("bob", False, 2, world=False)
bob2.run(WORLD1)
bob2.run(WORLD2)
bob2.L.globals().SAVED = saved
bob2.run("st = deser(SAVED)")
check(bob2.state() == bob.state(), "the state reads back as it was")
bob2.gui(3)
check(bob2.chat() == [], "nothing told again after the reload")
f2 = bob2.ev("G.files[M.FILE]") or ""
check("alert\t4\tlead\t3\t1002\tBeta" in f2, "the window's file keeps the company's alerts")
games = [host, bob, bob2]
# (nothing new for a month: no alert, the same state everywhere)
for g in games:
    g.month(24002)
start = measure(host, games, start)
check(host.state() == bob.state() == bob2.state(), "the same state on the three games (one reloaded)")
check(host.ev("st.feat.market.seq") == 4, "nothing new: no alert")

# ---------------------------------------------------------------------------------------------------- the first place's margin
print("first place: a margin before it changes hands")
lead = host.ev("""(function()
  local live = M.companies(st.co.list)
  local t = { cos = { { co = 2, pa = 50, fr = 0, st = 1 }, { co = 3, pa = 51, fr = 0, st = 1 } } }
  local t2 = { cos = { { co = 2, pa = 50, fr = 0, st = 1 }, { co = 3, pa = 54, fr = 0, st = 1 } } }
  local t3 = { cos = { { co = 2, pa = 50, fr = 0, st = 1 }, { co = 3, pa = 50, fr = 0, st = 1 } } }
  local t4 = { cos = { { co = 2, pa = 0, fr = 0, st = 1 } } }
  return table.concat({ tostring(M.leader(t, 2, live)), tostring(M.leader(t2, 2, live)), tostring(M.leader(t3, nil, live)),
    tostring(M.leader(t, 9, live)), tostring(M.leader(t4, 2, live)) }, " ")
end)()""")
check(lead == "2 3 2 3 nil", f"kept within 2 points, lost beyond, a tie to the lowest id, a gone company first before, nobody carrying ({lead})")

# ---------------------------------------------------------------------------------------------------- alerts off
print("the alerts' parameter off")
qh = Game("host", True, 1, opts='{ market = 1, ["market.alerts"] = 0 }')
qb = Game("bob", False, 2, opts='{ market = 1, ["market.alerts"] = "0" }')
qg = [qh, qb]
s0 = measure(qh, qg, 0)
for g in qg:
    g.run(WORLD2)
    g.month(24001)
s0 = measure(qh, qg, s0)
check(qh.state() == qb.state(), "the same state on both games")
check(qh.ev("#st.feat.market.alerts") == 0 and qh.ev("st.feat.market.towns[2].lead") == 3, "no alert, first place still followed")
qh.gui(2)
qb.gui(2)
check(qh.chat() == [] and qb.chat() == [], "nothing in the chat")
check("alerts\t0" in (qb.ev("G.files[M.FILE]") or ""), "the window says the alerts are off")

# ---------------------------------------------------------------------------------------------------- a company gone
print("a company gone (bankrupt)")
for listGone in (False, True):
    gh = Game("host", True, 1)
    gb = Game("carl", False, 2)
    gg = [gh, gb]
    for g in gg:
        g.run(f"G.listGone = {'true' if listGone else 'false'}")
    s0 = measure(gh, gg, 0)
    for g in gg:
        g.run(WORLD2)
        g.run("st.co.list[2].gone = 'bankrupt'")
        g.month(24001)
    s0 = measure(gh, gg, s0)
    p = gh.sent()[-1][1]
    towns_s = re.search(r'\["t"\]="([^"]*)"', p).group(1)
    inds_s = re.search(r'\["i"\]="([^"]*)"', p).group(1)
    named = [f for part in towns_s.split(";") for f in part.split(",")[2:] if f.split(":")[0] == "2"]
    named += [co for part in inds_s.split(";") if ":" in part for co in part.split(":")[1].split(".") if co == "2"]
    check(towns_s != "" and not named, f"the host's measure leaves the gone company out (listed gone: {listGone})")
    # (an event that still names it: the games leave it out too)
    for g in gg:
        g.month(24002)
        g.deliver('{["month"]=24002,["t"]="1001,5000,1:123:50:1,2:9:9:1;1002,3000,2:50:30:1",["i"]="701:2.3"}')
    check(gh.state() == gb.state(), "the same state on both games")
    check(gh.ev("#st.feat.market.towns") == 1 and gh.ev("#st.feat.market.towns[1].cos") == 1 and gh.ev("st.feat.market.ind[1].cos[1]") == 3,
          "an event naming the gone company: its entries left out")
    check(gh.ev("(function() for _, a in ipairs(st.feat.market.alerts) do if a.co == 2 or a.by == 2 then return false end end return true end)()"),
          "no alert to or about the gone company")

# ---------------------------------------------------------------------------------------------------- stale, malformed
print("a measure sent again, an older one, a malformed one")
before = host.state()
for g in games:
    g.deliver('{["month"]=24002,["t"]="1001,1,2:999:999:9",["i"]=""}')
    g.deliver('{["month"]=24000,["t"]="1001,1,2:999:999:9",["i"]=""}')
check(host.state() == before == bob.state(), "a month already applied, or older: left out")
for g in games:
    g.deliver('{["month"]=24003,["t"]="abc;1001,x,1:2:3;1002,10,9:1:1:1,1:a:1:1,1:1:1:1:1,1:1:1:1;;1002,99,2:1:1:1;-5,3,1:1:1:1",["i"]="x:1;703:9;702:1.1.2"}')
    g.deliver('{["month"]="soon",["t"]=""}')
    g.deliver('{["t"]=""}')
check(host.state() == bob.state() == bob2.state(), "the same state on every game")
check(host.ev("#st.feat.market.towns") == 1 and host.ev("st.feat.market.towns[1].town") == 1002 and host.ev("#st.feat.market.towns[1].cos") == 1
      and host.ev("st.feat.market.towns[1].pop") == 10, "only the well-formed entries kept (Beta, the host's company, once)")
check(host.ev("#st.feat.market.ind") == 1 and host.ev("#st.feat.market.ind[1].cos") == 2, "the industries: unknown companies out, each company once")
check(host.ev("st.feat.market.month") == 24003, "a month without a number: left out")
for g in games:
    g.deliver('{["month"]=1000000000,["t"]="1001,1,2:1:1:1",["i"]=""}')
    g.deliver('{["month"]=24004.5,["t"]="1001,1,2:1:1:1",["i"]=""}')
check(host.ev("st.feat.market.month") == 24003 and host.state() == bob.state(), "a wild month or a fraction: left out (later measures still apply)")

# ---------------------------------------------------------------------------------------------------- the map refuses
print("the host's measure fails (the game refuses a read)")
eh = Game("host", True, 1)
eh.run("M.engine.towns = function() error('refused') end")
eh.gui(70)
fails = eh.ev("(function() local n = 0 for _, s in ipairs(G.log) do if s:find('measure failed', 1, true) then n = n + 1 end end return n end)()")
check(fails == 2 and not eh.sent(), f"nothing sent, said once a minute ({fails} times in 70 s)")
check(eh.ev("M.mem.pass == nil or M.mem.pass.phase ~= 'done'"), "the measure starts again")

# ---------------------------------------------------------------------------------------------------- sent again when lost
print("a measure lost (a resynchronisation drops events): sent again")
lh = Game("host", True, 1)
for k in range(20):
    lh.gui(1)
    if lh.sent():
        break
check(len(lh.sent()) == 1, f"sent once (after {k + 1} calls)")
lh.gui(int(lh.ev("M.RESEND_S")) - 1)
check(len(lh.sent()) == 1, "not again before M.RESEND_S")
lh.gui(1)
check(len(lh.sent()) == 2 and lh.sent()[0][1] == lh.sent()[1][1], "the same measure sent again")
lh.deliver(lh.sent()[1][1])
lh.gui(60)
check(len(lh.sent()) == 2, "applied: no more")
check(lh.ev("G.calls") > 0 and lh.ev("CALLS.deliveries") == 4, "the map read once (the measure is not taken again to send it again)")

# ---------------------------------------------------------------------------------------------------- one company
print("one company only: nothing measured")
oh = Game("host", True, 1)
oh.run("st.co.list[2].gone = 'merged'; st.co.list[3].ent = nil")
oh.gui(20)
check(not oh.sent() and oh.ev("G.calls") == 0, "no competitor: no measure")
check("month" not in (oh.ev("G.files[M.FILE]") or "month"), "the window's file says there is no measure yet")
check("alone\t1" in (oh.ev("G.files[M.FILE]") or "") and oh.ev("(function() local d = M.parseFile({ 'v\t1', 'alone\t1' }) local v = M.view(d, function(fr, en) return en end) "
      "return v[3].text end)()") == "Only one company plays: no competitor, nothing to measure.", "the tab says why: one company only")
check(oh.ev("(function() local n = 0 for _, s in ipairs(G.log) do if s:find('one company plays', 1, true) then n = n + 1 end end return n end)()") == 1,
      "said once in the log")

# ---------------------------------------------------------------------------------------------------- a big map
print("a big map: the measure spread over the calls")
bh = Game("host", True, 1, world=False)
bh.run(r'''
for i = 1, 200 do WORLD.towns[i] = { 5000 + i, 100 * i } end
for i = 1, 300 do
  local town = 5000 + (i % 200) + 1
  addStop(i % 2 == 0 and 100 or 200, 20000 + i, 30000 + i, 40000 + i, town)
  WORLD.deliv[town] = WORLD.deliv[town] or {}
  WORLD.deliv[town][20000 + i] = i
end
''')
calls_per_gui = []
for k in range(200):
    before_d = bh.ev("CALLS.deliveries")
    bh.gui(1)
    calls_per_gui.append(bh.ev("CALLS.deliveries") - before_d)
    if bh.sent():
        break
check(len(bh.sent()) == 1, f"the measure done and sent after {len(calls_per_gui)} calls")
check(max(calls_per_gui) <= bh.ev("M.BUDGET.towns"), f"at most {bh.ev('M.BUDGET.towns')} towns per call")
t = bh.sent()[0][1]
check(t.count(";") == 199, "the 200 towns in the measure")

# ---------------------------------------------------------------------------------------------------- the window's tab
print("the window's tab")
view = bob.ev(r'''(function()
  local d = M.parseFile((function() local l = {} for x in (G.files[M.FILE] .. "\n"):gmatch("([^\n]*)\n") do l[#l + 1] = x end return l end)())
  local out = {}
  for _, b in ipairs(M.view(d, function(fr, en) return en end, false)) do
    if b.kind == "table" then for _, r in ipairs(b.rows) do out[#out + 1] = table.concat(r, "|") end else out[#out + 1] = b.kind .. ":" .. b.text end
  end
  return table.concat(out, "\n")
end)()''')
check("title:Market shares" in view, "English title")
rows = view.split("\n")
# (passengers: Bob 50 of 243 in all the towns; cargo: 30 of 310)
check(len(rows) > 5 and rows[3] == "Bob Co (you)|21 %|10 %|2|0" and rows[4] == "Host Co|71 %|19 %|3|1" and rows[5] == "Robot Co|8 %|71 %|2|1",
      "the totals: this player's company first, marked (you); shares of all the passengers and all the cargo, towns, industries")
check("item:Alpha (5 000 inhabitants), first place: Host Co" in view, "a town where Bob is, with its first place")
check("item:Gamma" not in view and "toggle:All towns" in view, "only Bob's towns, and the filter's button")
check("muted:    Robot Co: passengers 0 %, cargo 83 %, 1 station(s)" in view, "each company's shares in a town (two columns)")
check("item:Competition: you lose first place in Beta, Robot Co takes the lead." in view, "Bob's alerts with a Show button")
view_fr = bob.ev(r'''(function()
  local d = M.parseFile((function() local l = {} for x in (G.files[M.FILE] .. "\n"):gmatch("([^\n]*)\n") do l[#l + 1] = x end return l end)())
  local out = {}
  for _, b in ipairs(M.view(d, function(fr, en) return fr end, true)) do if b.text then out[#out + 1] = b.kind .. ":" .. b.text end end
  return table.concat(out, "\n")
end)()''')
check("title:Parts de marché" in view_fr and "item:Gamma (800 habitants), 1re place : Robot Co" in view_fr and "toggle:Mes villes" in view_fr,
      "French, every town served")
nodes = bob.ev(r'''(function()
  local clicks, nodes = {}, 0
  local u = {
    T = function(fr, en) return en end,
    read = function(file) local l = {} for x in (G.files[file] .. "\n"):gmatch("([^\n]*)\n") do l[#l + 1] = x end return l end,
    text = function(s) nodes = nodes + 1; return { text = s } end,
    row = function(c) nodes = nodes + 1; return { row = c } end,
    button = function(label, fn) clicks[#clicks + 1] = { label = label, fn = fn }; return { button = label } end,
    table = function(lines, widths, header) nodes = nodes + 1; return { table = lines, widths = widths, header = header } end,
    request = function(kind, p) REQ = kind .. ":" .. p end,
  }
  local out = M.ui(u)
  local shown = nil
  for _, c in ipairs(clicks) do if c.label == "Show" then c.fn(); shown = REQ; break end end
  local all0 = M.showAll
  for _, c in ipairs(clicks) do if c.label == "All towns" then c.fn() end end
  return #out .. " " .. tostring(shown) .. " " .. tostring(all0) .. ">" .. tostring(M.showAll) .. " " .. tostring(#M.ui({ T = u.T }) == 0)
end)()''')
check(nodes.split(" ")[1] == "show:1001" and nodes.split(" ")[2] == "nil>true" and nodes.split(" ")[3] == "true" and int(nodes.split(" ")[0]) > 10,
      f"the widgets: nodes, Show asks the bridge to move the camera to the town, the filter flips, no widget no content ({nodes})")
check(bob.ev("(function() M.showAll = nil; FOCUSED = nil; local btn; M.ui({ T = function(f, e) return e end, read = function(file) local l = {} for x in (G.files[file] .. '\\n'):gmatch('([^\\n]*)\\n') do l[#l + 1] = x end return l end, "
             "text = function(s) return { text = s } end, row = function(c) return { row = c } end, button = function(l, fn) if l == 'Show' and not btn then btn = fn end return {} end }); btn(); return FOCUSED end)()") == 1001,
      "without u.request, Show moves the camera from the window itself")
check(bob.ev("M.request('show', '1002', st, guiEnv)") and bob.ev("FOCUSED") == 1002, "the window's request show")

# ---------------------------------------------------------------------------------------------------- money, determinism
print("no money moves, the simulation half reads no clock")
check(all(g.ev("#G.booked == 0 and G.moneyCalls == 0") for g in games + [qh, qb, lh]), "env.book and env.money never called")
check(all(g.ev("plain(st)") is None for g in games + [qh, qb]), "every game's state is plain data")

# ==================================================================================================== integrated
# The module in the real options host (mpfever_feat.lua: F.load, F.canon, F.simEvent, F.simTick, F.gui, F.request, F.tabs, its
# envs) with the bridge's real hooks (SIM.featBridge, SIM.featTick, SIM.featEvent, G.featBridge, G.featChat, G.featGui,
# G.featRequest) and the window's (U.featU, U.featTabRows...), extracted from the files as tests/test_feat_host.py does. Two
# games, each its own Lua state; the events the host's game sends go to both games with the sender the bridge stamps on them
# (executeActionOnce: param.mpfFrom).
print("integrated: the real options host, the bridge's and the window's hooks, two games")
CONTENT = os.path.join(HERE, "..", "mod", "mpfever_1", "content")


def read_content(name):
    with open(os.path.join(CONTENT, name), encoding="utf-8") as fh:
        return fh.read()


def extract(src, pattern, what):
    m = re.search(pattern, src, re.S | re.M)
    if not m:
        check(False, f"{what} found in the source")
        return ""
    return m.group(0)


FEAT_SRC = read_content("mpfever_feat.lua")
BRIDGE = read_content("mpfever_bridge.script.lua")
UI = read_content("mpfever_ui.script.lua")
HOOKS = "\n".join(extract(BRIDGE, p, w) for p, w in (
    (r"^SIM\.featBridge = function\(\)\n.*?^end\n", "SIM.featBridge"),
    (r"^SIM\.featTick = function\(state\)\n.*?^end\n", "SIM.featTick"),
    (r"^SIM\.featEvent = function\(st, name, param\)\n.*?^end\n", "SIM.featEvent"),
    (r"^G\.featBridge = function\(\)\n.*?^end\n", "G.featBridge"),
    (r"^G\.featChat = function\(text\)\n.*?^end\n", "G.featChat"),
    (r"^G\.featGui = function\(st\)\n.*?^end\n", "G.featGui"),
    (r"^G\.featRequest = function\(p\)\n.*?^end\n", "G.featRequest"),
))
WINDOW = extract(UI, r"^U\.featOff = .*?^U\.featTabRows = function\(K, st, key\)\n.*?^end\n", "the window's game options")
TABREQ = extract(UI, r"^\s*local tab, seq = s:match\(.*?\n", "the window's tab request pattern")
check('"^([%w_]+)"' in TABREQ, "the window's tab request takes a game option's tab (f_market)")
check(re.search(r"^H\.markettest = function\(from, p\)\n", BRIDGE, re.M) is not None, "the bridge has the markettest scenario")

INTEG = r'''
RESULTS_LOG = {}
function log(s) RESULTS_LOG[#RESULTS_LOG + 1] = tostring(s) end
function logged(pat) for _, l in ipairs(RESULTS_LOG) do if l:find(pat, 1, true) then return true end end return false end
function countLogged(pat) local n = 0 for _, l in ipairs(RESULTS_LOG) do if l:find(pat, 1, true) then n = n + 1 end end return n end
function T(fr, en) return en end
function money(n) return tostring(n) end
CLOCK = 0
os.clock = function() return CLOCK end
NOW, MD = 1000, 60000
function gameTime() return NOW end
STEP, BS, TAB, NL = 200, "/", "\t", "\n"
R, CO = {}, { members = function() return {} end }
function coBook() BOOKED = (BOOKED or 0) + 1 end
api = { util = { getDefaultMonthDuration = function() return MD end },
  engine = { util = { getCalendarDate = function() return { year = 1900, month = 1, day = 1 } end, getPlayer = function() return 100 end,
    finance = { getPlayersBalance = function() MONEYREADS = (MONEYREADS or 0) + 1 return 0 end } } },
  cmd = { sendCommand = function() end, makeScriptingSendEventCmd = function() return {} end } }
FILEDATA = {}
FEATLOADS = 0
C = { ROLE = ROLE, DIR = "D", BS = "/", NL = "\n", CR = "\r", TAB = "\t", NAME = ME,
  T = function(fr, en) return en end, Tf = function(fr, en) return en end,
  appendFile = function(path, text) FILEDATA[path] = (FILEDATA[path] or "") .. text return true end,
  IO = { open = function(path, mode)
    if mode and mode:find("w", 1, true) then return { write = function(_, s) FILEDATA[path] = s end, close = function() end } end
    local s = FILEDATA[path]
    if not s then return nil end
    return { read = function() return s end, close = function() end }
  end } }
F = assert(load(FEAT_SRC, "mpfever_feat.lua"))()
F.loader = function(id) if id == "market" then return assert(load(SRC, "mpfever_feat_market.lua"))() end return nil end
C.feat = function() FEATLOADS = FEATLOADS + 1 return F end
SIM = {}
G = { frames = 1000, session = { started = true, resync = false }, connected = true, cmode = "separate", me = ME, myCo = MYCO }
SENT = {}
G.coEvent = function(name, param)
  if G.session.resync then return false end
  SENT[#SENT + 1] = { name = name, s = ser(param or {}) }
end
-- (the window: U and its helpers)
U = { isHost = function(st) return st and st.host == true end, winChanged = function() end }
U.menuRequest = function(cmd, arg) MENUREQ = cmd .. " " .. tostring(arg) return true end
-- (the window's line to the bridge, as stampHeld reads ui.log: a feat_req goes to G.featRequest)
function sendLine(kind, p) if kind == "feat_req" then G.featRequest(p) end end
K = { TEXT_W = 556, ICON_SETTINGS = "i" }
function K.text(t, class, cls, w) return { kind = "text", t = tostring(t), w = w, class = class } end
function K.muted(t, w) return { kind = "muted", t = tostring(t) } end
function K.section(icon, t) return { kind = "section", t = t } end
function K.gap() return { kind = "gap" } end
function K.row(c) return { kind = "row", c = c } end
function K.col(c) return { kind = "col", c = c } end
function K.btn(label, tip, fn, primary, enabled) return { kind = "btn", t = label, fn = fn } end

function ser(v)
  local t = type(v)
  if t == "number" then if v == math.floor(v) then return string.format("%d", v) end return string.format("%.17g", v)
  elseif t == "string" then return string.format("%q", v)
  elseif t == "boolean" then return tostring(v)
  elseif t == "table" then
    local keys = {}
    for k in pairs(v) do keys[#keys + 1] = k end
    table.sort(keys, function(a, b) if type(a) ~= type(b) then return type(a) < type(b) end return a < b end)
    local parts = {}
    for _, k in ipairs(keys) do parts[#parts + 1] = "[" .. ser(k) .. "]=" .. ser(v[k]) end
    return "{" .. table.concat(parts, ",") .. "}"
  end
  error("not plain data: a " .. t)
end
function deser(s) return assert(load("return " .. s, "data", "t", {}))() end

st = { co = { mode = "separate", list = {
  { id = 1, key = "", name = "", ent = 100 },
  { id = 2, key = "bob", name = "Bob Co", ent = 200 },
  { id = 3, key = "ai:1", name = "Robot Co", ent = 300 },
} }, prog = { passengers = {
  { company = 1, town = 1001, value = 12.34 }, { company = 1, town = 1002, value = 5.0 },
  { company = 2, town = 1002, value = 5.0 }, { company = 3, town = 1003, value = 2.0 },
} } }
STATE = { get = function() return st end, set = function() end }

-- the frames of the interface half (guiUpdate): about one second each here
function frames(n)
  for i = 1, n or 1 do
    CLOCK = CLOCK + 1
    G.frames = G.frames + 60
    G.featGui(st)
  end
end
-- a simulation step (update's end): month and tick, only while an option is on, as the bridge gates it (SIM.featOn)
function simStep()
  if type(st.optsText) == "string" and st.optsText ~= "" then SIM.featTick(STATE) end
end
-- an event of the network, as the bridge's handleEvent gives it (the sender stamped by executeActionOnce)
function apply(name, s, from, co)
  local p = deser(s)
  p.mpfFrom, p.mpfCo = from, co
  SIM.featEvent(st, name, p)
end
function sentCount() return #SENT end
function sentAt(k) return SENT[k].name, SENT[k].s end
function marketState() return ser(st.feat and st.feat.market or {}) end
'''

MOCKMAP = r'''
F.load(log)
MK = F.byId.market
WORLD = { lines = {}, owner = {}, towns = {}, t2s = {}, deliv = {}, sgOf = {}, sgStations = {}, catch = {}, inds = {}, names = {} }
ENGINE_READS = 0
local function counted(fn) return function(...) ENGINE_READS = ENGINE_READS + 1 return fn(...) end end
local E = MK.engine
E.ownerOf = counted(function(e) return WORLD.owner[e] end)
E.lines = counted(function() local l = {} for k in pairs(WORLD.lines) do l[#l + 1] = k end table.sort(l) return l end)
E.lineGroups = counted(function(l) return WORLD.lines[l] or {} end)
E.towns = counted(function() local out = {} for _, t in ipairs(WORLD.towns) do out[#out + 1] = { town = t[1], pop = t[2] } end return out end)
E.townStations = counted(function() return WORLD.t2s end)
E.halfYear = counted(function() return 365000 end)
E.deliveries = counted(function(town)
  local out = {}
  -- (as the game gives them: line -> { [-1] = { late, total } }, read through M.delivered)
  for line, n in pairs(WORLD.deliv[town] or {}) do out[line] = MK.delivered({ [-1] = { 0, n } }) end
  return out
end)
E.stationGroup = counted(function(s) return WORLD.sgOf[s] end)
E.groupStations = counted(function(sg) return WORLD.sgStations[sg] or {} end)
E.catchables = counted(function(s) return WORLD.catch[s] or {} end)
E.industries = counted(function() local out = {} for _, x in ipairs(WORLD.inds) do out[#out + 1] = { ind = x[1], stockList = x[2] } end return out end)
E.name = function(e) return WORLD.names[e] or ("#" .. tostring(e)) end
E.companyName = function(c) return (c.name ~= "" and c.name) or "Host Co" end
E.focusTown = function(t) FOCUSED = t return true end
function addStop(owner, line, station, sg, town)
  WORLD.owner[station] = owner
  WORLD.owner[line] = owner
  WORLD.sgOf[station] = sg
  WORLD.sgStations[sg] = WORLD.sgStations[sg] or {}
  table.insert(WORLD.sgStations[sg], station)
  WORLD.lines[line] = WORLD.lines[line] or {}
  table.insert(WORLD.lines[line], sg)
  if town then WORLD.t2s[town] = WORLD.t2s[town] or {}; table.insert(WORLD.t2s[town], station) end
end
'''


class Integ:
    def __init__(self, name, role, my_co):
        self.L = lua52.LuaRuntime(unpack_returned_tuples=True)
        g = self.L.globals()
        g.SRC, g.FEAT_SRC, g.ROLE, g.ME, g.MYCO = SRC, FEAT_SRC, role, name, my_co
        self.L.execute(INTEG)
        self.L.execute(HOOKS)
        self.L.execute(WINDOW)
        self.name = name

    def run(self, code):
        return self.L.execute(code)

    def ev(self, expr):
        return self.L.eval(expr)

    def sent(self):
        g = self.L.globals()
        return [g.sentAt(k) for k in range(1, g.sentCount() + 1)]

    def frames(self, n=1):
        self.L.globals().frames(n)

    def step(self):
        self.L.globals().simStep()


def ship(sender, games, start, origin, co):
    """the events `sender` sent since `start`, applied by every game in the same order (stamped with their sender)"""
    out = sender.sent()
    for name, s in out[start:]:
        for g in games:
            g.L.globals().apply(name, s, origin, co)
    return len(out)


ih = Integ("host", "host", 1)
ib = Integ("bob#2", "client", 2)
ig = [ih, ib]

# ---- all off: nothing (the options host not even loaded)
for g in ig:
    g.run('G.featOpts = ""')
    g.frames(30)
    for _ in range(5):
        g.step()
check(all(g.ev("FEATLOADS") == 0 for g in ig), "integrated, all off: the options host is never loaded")
check(not ih.sent() and not ib.sent() and all(g.ev("next(FILEDATA) == nil and st.feat == nil and st.featMonth == nil") for g in ig),
      "integrated, all off: no event, no file, no state")

# ---- the lobby's view of the option (F.offered, F.canon, F.summary: the lobby, MPFever.exe's canon and the Game tab use them)
ih.run("F.load(log)")
check(ih.ev("(function() for _, e in ipairs(F.offered('separate')) do if e.opt.id == 'market' then return #e.params == 1 and e.params[1].id == 'alerts' end end return false end)()"),
      "integrated: the lobby offers 'Competition' with its parameter in the separate mode")
check(ih.ev("(function() for _, e in ipairs(F.offered('shared')) do if e.opt.id == 'market' then return false end end return true end)()"),
      "integrated: not offered in the co-op")
check(ih.ev("F.canon('market=1;market.alerts=1', 'separate')") == "market=1" and ih.ev("F.canon('market=1;market.alerts=0', 'separate')") == "market=1;market.alerts=0"
      and ih.ev("F.canon('market=1', 'shared')") == "", "integrated: the canon (the default parameter dropped, the co-op drops the option)")
check(ih.ev("F.summary(F.parse('market=1;market.alerts=0'), 'separate', T)[1].params[1]") == "Alerts in the chat: No",
      "integrated: the players' summary of the option")
check(ih.ev("F.param(F.parse('market=1'), 'market', 'alerts')") == 1 and ih.ev("F.param(F.parse('market=1;market.alerts=0'), 'market', 'alerts')") == 0,
      "integrated: env.param gives the declared numbers")

# ---- the map (as in the module's own cases)
for g in ig:
    g.run(MOCKMAP)
    g.run(WORLD1)

# ---- the host switches it on: f_opts from the host's game, applied by both
ih.run('G.featOpts = "market=1"')
ih.frames(1)
check([n for n, _ in ih.sent()] == ["f_opts"], f"integrated: the host's game sends f_opts ({[n for n, _ in ih.sent()]})")
s_at = ship(ih, ig, 0, "host", 1)
check(all(g.ev("st.optsText") == "market=1" and g.ev("st.optsMode") == "separate" for g in ig), "integrated: both games have the option on")
for g in ig:
    g.step()
check(all(g.ev("st.featMonth") == g.ev("math.floor(NOW / MD)") for g in ig), "integrated: the month the options start in noted")

# ---- the host's game measures over its frames, sends f_market_snap; both apply it
ih.frames(12)
ib.frames(12)
names = [n for n, _ in ih.sent()[s_at:]]
check(names == ["f_market_snap"], f"integrated: the host's measure sent once ({names})")
check(not ib.sent(), "integrated: a player's game sends nothing")
check(ib.ev("ENGINE_READS") == 0, "integrated: a player's game never reads the map for it")
s_at = ship(ih, ig, s_at, "host", 1)
check(ih.ev("marketState()") == ib.ev("marketState()") and ih.ev("st.feat.market.month") == -1 and ih.ev("#st.feat.market.towns") == 3,
      "integrated: the same measure applied on both games")
check(ih.ev("logged('feat market: measure of month -1 sent: 3 town(s), 2 industry(ies)')"), "integrated: the host logs its measure")
check(ih.ev("logged('feat market: first measure: 3 line(s) of the companies, 4 town(s) (3 with a company') and logged('deliveries per line 5 with the total (-1), 0 per cargo')"),
      "integrated: the host's first measure says what the game gave")
check(all(g.ev("logged('feat market: measure of month -1 applied: 3 town(s), 2 industry(ies), 0 alert(s)')") for g in ig),
      "integrated: both games log the measure applied")
ih.frames(2)
ib.frames(2)
fh, fb = ih.ev("FILEDATA['D/feat_market_shares.txt']") or "", ib.ev("FILEDATA['D/feat_market_shares.txt']") or ""
check("me\t1" in fh and "me\t2" in fb and "town\t1002\t3000\t2\tBeta" in fb, "integrated: each game writes its window file (feat_market_shares.txt)")

# ---- a player's forged measure is left out on every game
before = ih.ev("marketState()")
for g in ig:
    g.L.globals().apply("f_market_snap", '{["month"]=99999,["t"]="1001,1,2:999:999:9",["i"]=""}', "bob#2", 2)
check(ih.ev("marketState()") == before == ib.ev("marketState()") and ih.ev("logged('feat market: a measure from bob#2 left out')"),
      "integrated: a measure sent by a player who joined is left out")

# ---- a game month later: competitors arrive, first place lost; the chat of each game
for g in ig:
    g.run(WORLD2)
    g.run("NOW = NOW + MD")
    g.step()
check(all(g.ev("st.feat.market.due") == g.ev("math.floor(NOW / MD)") for g in ig), "integrated: the new month makes a measure due (M.month through F.simTick)")
ih.frames(12)
s_at = ship(ih, ig, s_at, "host", 1)
check(ih.ev("marketState()") == ib.ev("marketState()") and ih.ev("st.feat.market.seq") == 4, "integrated: the month's measure and its 4 alerts on both games")
ih.frames(2)
ib.frames(2)
ch, cb = ih.ev("FILEDATA['D/chat.txt']") or "", ib.ev("FILEDATA['D/chat.txt']") or ""
check("MPFever\tCompetition: Bob Co arrives in Alpha, a town where you are." in ch and "lose first place" not in ch,
      "integrated: the host's chat (G.featChat) tells its alerts")
check("MPFever\tCompetition: you lose first place in Beta, Robot Co takes the lead." in cb and "Bob Co arrives" not in cb,
      "integrated: the player's chat tells its own alerts only")

# ---- the window: the Competition tab while the option is on, drawn by the real U.featU
for g in ig:
    g.run(r'''
    WST = { mode = "separate", opts = "market=1", me = ME, host = C.ROLE == "host" }
    TABS = U.featTabs(WST)
    ROWS = U.featTabRows(K, WST, "f_market")
    function flat(n, out)
      out = out or {}
      if type(n) ~= "table" then return out end
      if n.kind == "text" or n.kind == "muted" or n.kind == "section" or n.kind == "btn" then out[#out + 1] = n.kind .. ":" .. tostring(n.t) end
      for _, c in ipairs(n.c or {}) do flat(c, out) end
      return out
    end
    FLAT = {}
    for _, r in ipairs(ROWS) do flat(r, FLAT) end
    FLATS = table.concat(FLAT, "\n")
    ''')
check(ib.ev("#TABS == 1 and TABS[1].key == 'f_market' and TABS[1].title[2] == 'Competition'"), "integrated: the window has the Competition tab")
flat_b = ib.ev("FLATS")
check("section:Market shares" in flat_b and "text:Bob Co (you)" in flat_b and "text:Passengers" in flat_b, "integrated: the tab's title and the totals' table")
check("text:Alpha (5 000 inhabitants), first place: Host Co" in flat_b and "btn:Show" in flat_b, "integrated: a town line with its Show button")
check(ib.ev("(function() for _, r in ipairs(ROWS) do if r.kind == 'row' and r.c[2] and r.c[2].kind == 'btn' then local w = r.c[1].c[1].c[1].w return w == 556 - MK.SHOW_W end end end)()"),
      "integrated: a line keeps the room of its button (no row wider than the window)")
check("muted:    Robot Co: passengers 0 %, cargo 83 %, 1 station(s)" in flat_b and "text:Competition: you lose first place in Beta, Robot Co takes the lead." in flat_b,
      "integrated: the shares per company and the player's alerts")
ib.run("FOCUSED = nil; RESULTS_LOG = {}")
ib.run("(function() for _, r in ipairs(ROWS) do if r.kind == 'row' and r.c[2] and r.c[2].kind == 'btn' and r.c[2].t == 'Show' then r.c[2].fn() return end end end)()")
check(ib.ev("FOCUSED") == 1001 and ib.ev("logged('feat market: camera to town 1001')"),
      "integrated: Show goes to the bridge (u.request -> G.featRequest -> M.request) and moves the camera")
ib.run("(function() for _, r in ipairs(ROWS) do if r.kind == 'btn' and r.t == 'All towns' then r.fn() return end end end)()")
ib.run("ROWS = U.featTabRows(K, WST, 'f_market'); FLAT = {}; for _, r in ipairs(ROWS) do flat(r, FLAT) end; FLATS = table.concat(FLAT, '\\n')")
check("text:Gamma (800 inhabitants), first place: Robot Co" in ib.ev("FLATS") and "btn:My towns" in ib.ev("FLATS"), "integrated: the filter shows every town")

# ---- the alerts' parameter off: the host's choice reaches every game
ih.run('G.featOpts = "market=1;market.alerts=0"; G.frames = G.frames + 1000')
ih.frames(1)
s_at = ship(ih, ig, s_at, "host", 1)
check(all(g.ev("st.optsText") == "market=1;market.alerts=0" for g in ig), "integrated: the parameter in the game on both")
for g in ig:
    g.run(WORLD2.replace("addStop(200, 14, 606, 506, 1001)", "addStop(200, 17, 610, 510, 1003)").replace("addStop(300, 15, 607, 507, 1002)", "").replace("addStop(100, 16, 608, 508, 1003)", "").replace("WORLD.deliv[1002][15] = 200", ""))
    g.run("NOW = NOW + MD")
    g.step()
ih.frames(12)
s_at = ship(ih, ig, s_at, "host", 1)
check(ih.ev("marketState()") == ib.ev("marketState()") and ih.ev("st.feat.market.seq") == 4, "integrated: alerts off -> no new alert (Bob in Gamma)")
ib.frames(2)
check("alerts\t0" in (ib.ev("FILEDATA['D/feat_market_shares.txt']") or ""), "integrated: the window file says the alerts are off")

# ---- switched off: nothing more
ih.run('G.featOpts = ""; G.frames = G.frames + 1000')
ih.frames(1)
s_at = ship(ih, ig, s_at, "host", 1)
check(all(g.ev("st.optsText") == "" for g in ig), "integrated: switched off on both")
reads0 = ih.ev("ENGINE_READS")
for g in ig:
    g.run("NOW = NOW + MD")
    g.step()
    g.frames(40)
check(len(ih.sent()) == s_at and ih.ev("ENGINE_READS") == reads0, "integrated: off again -> no measure, no event")
check(all(g.ev("#U.featTabs({ mode = 'separate', opts = '', me = ME })") == 0 for g in ig), "integrated: off again -> no tab")
check(all(g.ev("(BOOKED or 0) == 0 and (MONEYREADS or 0) == 0") for g in ig), "integrated: no money booked or read")

if failures:
    print(f"FAIL {len(failures)} case(s):")
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("all cases passed")
sys.exit(0)
