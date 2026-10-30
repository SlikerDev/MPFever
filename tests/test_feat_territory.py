"""Offline test of the 0.6 feature module "territory" (mpfever_feat_territory.lua): starting territories and money handicaps.

The real module and the real companies registry (mpfever_co.lua) run through lupa (Lua 5.2) with the env of the options host
mocked as docs/FEATURES-0.6.md describes it (env.on, env.param, env.state, env.book, env.every, env.send, env.chat, env.write...)
and a mocked game API for the GUI half (zones, towns, owners, game time). Cases:
  - the module loads without the game's API, its options and events follow the contract;
  - both options off: no state, no event, no money, no file, no chat, every build allowed (also with a state left from before);
  - territories: claims (accepted, twice, overlap, the claim year, a later company's own year, the host's company, a computer
    company, an unknown or gone company, a bad position), withdrawal within the year only, the end of a protection (once), "for
    good", a company gone (bankrupt);
  - the refusals of THIS player's builds (M.allow, M.proposal): stations, depots, stops (new, re-created by the stop tool,
    without a model position), signals, tracks, junctions, town buildings, an edit of the company's own station, a proposal
    as userdata, the game's own critical error, mode "shared", option off; M.blockedFor for the computer companies;
  - handicaps: once per player's company, not the savegame's company nor a computer company, per player values, a company whose
    player entity comes later, a new company after a bankruptcy, savegame reload, mode "shared", handicap alone;
  - determinism: two games applying the same events give the same state and the same bookings, whatever the order the
    territories were put in the state;
  - the state is plain data (no function, no userdata, no shared table, no cycle, finite numbers);
  - GUI half on the host's game and on a client's (no event sent by either), the chat news (once, not again after a load, a
    refusal only to its claimer, French), the circles on the ground, the window's file and tab, the window's requests.
Run: python tests/test_feat_territory.py
"""
import os
import sys

try:
    import lupa.lua52 as lua52
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mod", "mpfever_1", "content")
SRC_M = open(os.path.join(HERE, "mpfever_feat_territory.lua"), encoding="utf-8").read()
SRC_CO = open(os.path.join(HERE, "mpfever_co.lua"), encoding="utf-8").read()

failures = []


def check(cond, what):
    print(("  ok    " if cond else "  FAIL  ") + what)
    if not cond:
        failures.append(what)


# ------------------------------------------------------------------------------------------------------------------------------
# A game: the module and the registry in a Lua state of their own, the options host's env mocked
MOCK = r'''
YEAR = 1200000                 -- a game year in this test (ms of game time): 6000 steps of 200 ms
GUI_TIME = 0                   -- the game time the GUI half reads (api GAME_TIME)
REAL = 0                       -- the GUI half's real time (env.realTime)
OWNERS = {}                    -- entity -> owner player entity (PLAYER_OWNED)
ZONES, ZCALLS = {}, 0          -- the circles drawn (api.gui.mission)
TOWN_IDS = { 11, 12, 13, 14 }
TOWN_NAME = { [11] = "Aville", [12] = "Bourg", [13] = "Cité", [14] = "Douves" }
TOWN_POS = { [11] = { 1000.4, 1000.6 }, [12] = { 2500, 1000 }, [13] = { 20000, 20000 }, [14] = { 6000, 1000 } }
TOWN_CAPS = { [11] = { 900, 100, 50 }, [12] = { 400, 10, 0 }, [13] = { 200, 0, 0 }, [14] = { 600, 0, 0 } }
api = {
  type = { ComponentType = { PLAYER_OWNED = "po", NAME = "name", GAME_TIME = "gt", TOWN = "town" },
    enum = { LandUseType = { RESIDENTIAL = 0 } },
    Vec2f = { new = function(x, y) return { x = x, y = y } end },
    Vec4f = { new = function(a, b, c, d) return { a, b, c, d } end } },
  util = { getDefaultYearDuration = function() return YEAR end },
  engine = {
    getComponent = function(e, ct)
      if ct == "po" then return OWNERS[e] and { player = OWNERS[e] } or nil end
      if ct == "name" then return { name = TOWN_NAME[e] } end
      if ct == "gt" then return { gameTime = GUI_TIME } end
      return nil
    end,
    util = { getWorld = function() return 1 end,
      town = { getTownDistrictCenter = function(t, use) local p = TOWN_POS[t]; return { x = p[1], y = p[2], z = 0 } end } },
    forEachEntityWithComponent = function(fn, ct) if ct == "town" then for _, t in ipairs(TOWN_IDS) do fn(t) end end end,
    system = { townBuildingSystem = { getTown2personCapacitiesMap = function() return TOWN_CAPS end } },
  },
  gui = { mission = {
    setZoneCircle = function(key, c, r, draw, col, prohibit, anim)
      ZONES[key] = { x = c.x, y = c.y, r = r, draw = draw, a = col[4], prohibit = prohibit, anim = anim }; ZCALLS = ZCALLS + 1
    end,
    removeZone = function(key) ZONES[key] = nil end } },
}

function newGame(mode)
  local g = { st = {}, books = {}, logs = {}, step = 0, time = 0, opts = {}, mode = mode or "separate" }
  g.env = {
    STEP = 200,
    log = function(s) g.logs[#g.logs + 1] = s end,
    gameTime = function() return g.time end,
    on = function(id) return g.opts[id] == true end,
    -- (nil when the host set nothing: the module takes the option's default)
    param = function(id, pid) return g.opts[id .. "." .. pid] end,
    state = function(st) st.feat = st.feat or {}; st.feat.territory = st.feat.territory or {}; return st.feat.territory end,
    every = function(n) return g.step % n == 0 end,
    book = function(ent, amount) g.books[#g.books + 1] = tostring(ent) .. ":" .. tostring(amount) end,
    money = function() return 0 end,
    companies = function() return {} end,
    R = {},
  }
  return g
end
function sync(g)
  g.env.mode = g.mode
  g.env.co = (g.mode == "separate") and g.st.co or nil
end
function steps(g, n) for _ = 1, n do g.step = g.step + 1; g.time = g.time + 200; sync(g); M.tick(g.st, g.env) end; GUI_TIME = g.time end
function jump(g, ms) g.time = g.time + ms; steps(g, 25) end
function ev(g, name, p) sync(g); M.event(g.st, name, p, g.env) end
function claim(g, co, from, x, y, name) ev(g, "f_territory_claim", { x = x, y = y, name = name, mpfCo = co, mpfFrom = from }) end

-- the registry as the bridge makes it: the savegame's company (the host's, entity 100), bob, carl, a computer company, eve
function makeReg(g)
  g.st.co = CO.new("separate", 100, 2000000)
  local h = CO.join(g.st.co, "host", "Host", true, "Host Co", "s1", 1); h.name = "Host Co"
  local b = CO.join(g.st.co, "bob", "Bob", false, "Bob Co", "s2", 2); b.ent = 200
  local c = CO.join(g.st.co, "carl", "Carl", false, "Carl Co", "s3", 3); c.ent = 300
  local a = CO.join(g.st.co, "ai:1", "AI", false, "Regional Transport", nil, 4); a.ent = 400
  local e = CO.join(g.st.co, "eve", "Eve", false, "Eve Co", "s5", 5); e.ent = 500
  OWNERS[3001] = 300                   -- a station of carl's
  OWNERS[2001] = 200                   -- a station of bob's
end
function S(g) return g.st.feat and g.st.feat.territory end
function nNews(g, k) local n = 0 for _, x in ipairs((S(g) or {}).news or {}) do if x.k == k then n = n + 1 end end return n end
function lastNews(g) local s = S(g) or {}; local l = s.news or {}; return l[#l] end

-- builds (the shipped form of a tool's proposal: C.compactProposal, an act's args[1])
function mat(x, y) local m = { __mat = true } for i = 1, 16 do m[i] = 0 end m[1], m[6], m[11], m[16] = 1, 1, 1, 1; m[13], m[14] = x, y; return m end
function act(co, p) return { fn = "makeWorldBuildProposalCmd", co = co, args = { n = 4, [1] = p, [2] = { __player = true }, [3] = false, [4] = true } } end
function conP(file, x, y, toRemove)
  return { toAdd = { { fileName = file, transf = mat(x, y) } }, toRemove = toRemove or {},
    proposal = { addedSegments = {}, addedNodes = {}, edgeObjectsToAdd = {} } }
end
function stopP(x, y, opts)
  opts = opts or {}
  local o = { category = opts.cat or 0, resultEntity = -5, left = true }
  if not opts.noModel then o.modelInstance = { __ud = true, transf = mat(x, y) } end
  return { toAdd = {}, toRemove = {}, proposal = {
    addedNodes = { { entity = -1, comp = { position = { __vec = true, x = x, y = y, z = 0 } } } },
    addedSegments = { { entity = -3, comp = { node0 = -1, node1 = 77 } } },
    edgeObjectsToAdd = { o }, new2oldEdgeObjects = opts.again and { [-5] = { 901 } } or nil } }
end
function trackP(x, y)
  return { toAdd = {}, toRemove = {}, proposal = {
    addedNodes = { { entity = -1, comp = { position = { __vec = true, x = x, y = y, z = 0 } } } },
    addedSegments = { { entity = -3, type = 1, comp = { node0 = -1, node1 = 77 } } }, edgeObjectsToAdd = {} } }
end
-- the same proposal as the game's userdata: an unknown member raises an error, the lists have a length, a matrix is indexed 1..16
function ud(t)
  if type(t) ~= "table" then return t end
  local f = {}
  for k, v in pairs(t) do if k ~= "__mat" and k ~= "__ud" and k ~= "__vec" then f[k] = ud(v) end end
  local n = #t
  return setmetatable({}, { __index = function(_, k)
    local v = f[k]
    if v == nil and type(k) ~= "number" then error("no member '" .. tostring(k) .. "'") end
    return v
  end, __len = function() return n end, __pairs = function() return next, f, nil end })
end

-- the GUI half's env (docs/FEATURES-0.6.md): the host's game or a client's
function guiEnv(g, myCo, isHost, me, T)
  local e = { isHost = isHost, me = me, myCo = myCo, sends = {}, chats = {}, writes = {}, T = T }
  e.log = function() end
  e.on = g.env.on
  e.param = g.env.param
  e.send = function(name, p) e.sends[#e.sends + 1] = { name = name, p = p } end
  e.chat = function(t) e.chats[#e.chats + 1] = t end
  e.write = function(f, lines) e.writes[#e.writes + 1] = { f = f, lines = lines } end
  e.realTime = function() return REAL end
  return e
end
function fileOf(e) local w = e.writes[#e.writes]; return w and table.concat(w.lines, "\n") or nil end

-- what a savegame keeps: plain data only (no function, no userdata, no table met twice, no cycle, finite numbers)
function plain(v, seen)
  seen = seen or {}
  local t = type(v)
  if t == "table" then
    if seen[v] then return false, "a table met twice" end
    seen[v] = true
    for k, x in pairs(v) do
      if type(k) ~= "string" and type(k) ~= "number" then return false, "a key of type " .. type(k) end
      local ok, why = plain(x, seen)
      if not ok then return false, why end
    end
    return true
  elseif t == "number" then return v == v and v > -1e300 and v < 1e300, "a number not finite"
  elseif t == "string" or t == "boolean" then return true end
  return false, "a value of type " .. t
end
-- (a value written the same way whatever the order of its tables' keys)
function canon(v)
  if type(v) ~= "table" then return type(v) .. ":" .. tostring(v) end
  local ks = {}
  for k in pairs(v) do ks[#ks + 1] = k end
  table.sort(ks, function(a, b) return tostring(a) < tostring(b) end)
  local parts = {}
  for _, k in ipairs(ks) do parts[#parts + 1] = tostring(k) .. "=" .. canon(v[k]) end
  return "{" .. table.concat(parts, ",") .. "}"
end
function COPY(t)
  if type(t) ~= "table" then return t end
  local o = {}
  for k, v in pairs(t) do o[k] = COPY(v) end
  return o
end
-- a game loaded from a savegame: the state copied, the module's own (non-saved) tables as a new Lua state has them
function reload(g)
  local g2 = newGame(g.mode)
  g2.st, g2.time, g2.step, g2.opts = COPY(g.st), g.time, g.step, COPY(g.opts)
  M.pending, M.drawn, M.newsSeen, M.townList, M.townsAt = {}, {}, nil, nil, nil
  return g2
end
FR = function(fr, en) return fr end
'''


def game_runtime():
    L = lua52.LuaRuntime(unpack_returned_tuples=True)
    L.execute(MOCK)
    L.globals().CO = L.execute(SRC_CO)
    L.globals().M = L.execute(SRC_M)
    return L, L.eval("function(code) local f = assert(load(code)) return f() end")


# ------------------------------------------------------------------------------------------------------------------------------
print("loading (no game API) and the contract")
L0 = lua52.LuaRuntime(unpack_returned_tuples=True)
ok_load = L0.eval("function(src) api = nil local ok, m = pcall(function() return assert(load(src))() end) return ok, m end")
okm, M0 = ok_load(SRC_M)
check(okm and M0 is not None, "the module loads without the game's API")
r0 = L0.eval("function(code) local f = assert(load(code)) return f() end")
L0.globals().M = M0
check(r0('return M.ID') == "territory", "its id is 'territory'")
check(r0('''
  local ids = {}
  for _, o in ipairs(M.OPTIONS) do
    if type(o.title) ~= "table" or #o.title ~= 2 or type(o.desc) ~= "table" or #o.desc ~= 2 or o.modes ~= "separate" then return false end
    ids[#ids + 1] = o.id
    for _, p in ipairs(o.params or {}) do
      local found = false
      for _, v in ipairs(p.values) do
        if v == p.default then found = true end
        local s = p.show and p.show(v, function(fr, en) return en end)
        if p.show and (type(s) ~= "string" or s == "") then return false end
      end
      if not found or type(p.label) ~= "table" or #p.label ~= 2 then return false end
    end
  end
  return table.concat(ids, ",")''') == "territory,handicap",
      "two options (territory, handicap), French and English, separate mode, params with their default and labels")
check(r0('local p = M.OPTIONS[1].params[2]; return p.show(0, function(fr, en) return fr end) .. "|" .. p.show(5, function(fr, en) return en end)')
      == "toujours|5 years", "the protection's label: 'for good' for 0, years otherwise")
check(r0('for k in pairs(M.EVENTS) do if k:sub(1, 12) ~= "f_territory_" then return false end end return M.EVENTS.f_territory_claim == true') is True,
      "its events start with f_territory_")
check(r0('return M.TAB.id == "territory" and #M.TAB.title == 2') is True, "its tab has an id and a French and English title")
check(r0('return M.yearMs()') == 1461000, "without the game's API a year has the fallback length")

# ------------------------------------------------------------------------------------------------------------------------------
print("both options off: nothing at all")
L, run = game_runtime()
run('''
G1 = newGame(); makeReg(G1)
steps(G1, 200)
claim(G1, 2, "Bob#1", 1000, 1000, "Aville")
E1 = guiEnv(G1, 3, true, "Host")
M.gui(G1.st, E1)
OK1, WHY1 = M.allow(act(3, conP("::/stations/rail/modular_station/modular_station.con", 1000, 1000)), G1.st, E1)
REQ1 = M.request("claim", 11, G1.st, E1)
''')
check(run('return G1.st.feat') is None, "no state")
check(run('return #G1.books') == 0, "no money")
check(run('return #E1.sends + #E1.chats + #E1.writes') == 0, "no event, no chat, no file")
check(run('return OK1') is True and run('return REQ1') is False, "every build allowed, no claim possible")
check(run('return ZCALLS') == 0, "no circle drawn")
# the options switched off after a game with them: what the state holds no longer counts
run('''
G1.opts.territory = true; G1.opts.handicap = true
steps(G1, 25); claim(G1, 2, "Bob#1", 1000, 1000, "Aville"); steps(G1, 25)
M.gui(G1.st, guiEnv(G1, 3, false, "Carl#2"))
G1.opts.territory = false; G1.opts.handicap = false
BOOKS1, SNAP1 = #G1.books, canon(G1.st)
steps(G1, 100); claim(G1, 3, "Carl#2", 9000, 9000, "Cité")
E1b = guiEnv(G1, 3, false, "Carl#2")
M.gui(G1.st, E1b)
OK1b = M.allow(act(3, conP("::/stations/rail/modular_station/modular_station.con", 1000, 1000)), G1.st, E1b)
''')
check(run('return canon(G1.st) == SNAP1 and #G1.books == BOOKS1') is True, "switched off again: the state and the money stay as they were")
check(run('return OK1b') is True and run('return (M.blockedFor(G1.st, E1b, 3, 1000, 1000))') is False,
      "switched off again: the old territory refuses nothing")
check(run('return next(ZONES) == nil and #E1b.writes == 0') is True, "switched off again: its circle is taken away, no file")

# ------------------------------------------------------------------------------------------------------------------------------
print("territories: claims")
L, run = game_runtime()
run('''
G = newGame(); makeReg(G); G.opts.territory = true
steps(G, 25)
''')
check(run('return S(G).t0') == 5000, "the option's start is noted (the first year to claim)")
check(run('return S(G).seen["1"] ~= nil and S(G).seen["2"] ~= nil and S(G).seen["4"] == nil') is True,
      "the players' companies are seen, not the computer one")
check(run('return S(G).hc') is None, "handicap off: no handicap")
run('claim(G, 2, "Bob#1", 1000.4, 1000.6, "Aville")')
check(run('local t = S(G).terr["2"]; return t and t.x == 1000 and t.y == 1001 and t.r == 2000 and t.untilT == G.time + 5 * YEAR and t.by == "Bob#1"') is True,
      "bob claims Aville: rounded centre, radius 2 km, protected 5 years (the defaults)")
check(run('return lastNews(G).k == "claim" and lastNews(G).co == 2') is True, "a news tells it")
run('claim(G, 2, "Bob#1", 9000, 9000, "Cité")')
check(run('return lastNews(G).k == "refused" and lastNews(G).why == "already" and S(G).terr["2"].name == "Aville"') is True,
      "a second claim of the same company is refused")
run('claim(G, 3, "Carl#2", 2500, 1000, "Bourg")')
check(run('return lastNews(G).why == "overlap" and lastNews(G).other == 2 and S(G).terr["3"] == nil') is True,
      "a circle overlapping bob's is refused (2 km apart, radii 2 + 2 km)")
run('claim(G, 3, "Carl#2", 6000, 1000, "Douves")')
check(run('return S(G).terr["3"] ~= nil and S(G).terr["3"].name == "Douves"') is True, "carl claims Douves (5 km away): accepted")
run('claim(G, 1, "Host", 1000, 9000, "Port")')
check(run('return S(G).terr["1"] ~= nil') is True, "the savegame's company (the host's) may claim too")
run('claim(G, 4, "Host", 30000, 30000, "Ailleurs")')
check(run('return lastNews(G).why == "ai" and S(G).terr["4"] == nil') is True, "a computer company has no territory")
run('N0 = S(G).newsSeq; claim(G, 99, "Nobody#9", 40000, 40000, "X")')
check(run('return S(G).newsSeq == N0') is True, "an unknown company's claim is ignored (no news)")
run('claim(G, 5, "Eve#3", "nan", nil, "Y")')
check(run('return lastNews(G).why == "place" and S(G).terr["5"] == nil') is True, "a claim without a position is refused")
run('claim(G, 5, "Eve#3", 2e6, 0, "Y")')
check(run('return lastNews(G).why == "place"') is True, "a claim off the map is refused")
run('claim(G, 5, "Eve#3", 30000, 30000, "Very long name ' + "é" * 40 + '\\n")')
check(run('''local n = S(G).terr["5"].name
  if #n > 60 or #n < 50 or n:find("%c") then return false end
  -- (valid UTF-8: no character cut at its end)
  local i = 1
  while i <= #n do
    local b = n:byte(i)
    local k = b < 128 and 0 or b >= 240 and 3 or b >= 224 and 2 or b >= 192 and 1 or -1
    if k < 0 or i + k > #n then return false end
    for j = i + 1, i + k do local c = n:byte(j) if c < 128 or c >= 192 then return false end end
    i = i + k + 1
  end
  return true''') is True, "a long name is cut to 60 bytes without a broken character or a control character")
run('ev(G, "f_territory_drop", { mpfCo = 5, mpfFrom = "Eve#3" })')
check(run('return S(G).terr["5"] == nil and lastNews(G).k == "drop"') is True, "eve gives up its territory within its year")
run('claim(G, 5, "Eve#3", 30000, 30000, "Cité")')
check(run('return S(G).terr["5"] ~= nil') is True, "and claims another one")
# the claim year
run('jump(G, YEAR)')
run('ev(G, "f_territory_drop", { mpfCo = 5, mpfFrom = "Eve#3" })')
check(run('return S(G).terr["5"] ~= nil') is True, "after its year a company cannot give its territory up")
run('''local d = CO.join(G.st.co, "dave", "Dave", false, "Dave Co", "s6", 6); d.ent = 600
steps(G, 25)''')
check(run('return S(G).seen["6"] == G.time') is True, "a company that comes later is seen when it comes")
run('''local f = CO.join(G.st.co, "fred", "Fred", false, "Fred Co", "s7", 7); f.ent = 700''')
run('claim(G, 7, "Fred#5", 50000, 50000, "Far")')
check(run('return S(G).terr["7"] ~= nil') is True, "a company claiming before its first look gets its own year too")
run('jump(G, YEAR / 2); claim(G, 6, "Dave#4", 40000, 40000, "Loin")')
check(run('return S(G).terr["6"] ~= nil') is True, "a later company claims within its own first year")
run('''local h = CO.join(G.st.co, "hank", "Hank", false, "Hank Co", "s8", 8); h.ent = 800''')
run('G.time = G.time + 1; claim(G, 8, "Hank#6", 60000, 60000, "Z")')
check(run('return S(G).terr["8"] ~= nil') is True, "(hank, new, claims at once)")
# a company there from the start that never claimed: its year is over
run('local g = CO.join(G.st.co, "gus", "Gus", false, "Gus Co", "s9", 9); g.ent = 900; S(G).seen["9"] = S(G).t0')
run('claim(G, 9, "Gus#7", 70000, 70000, "W")')
check(run('return lastNews(G).why == "late" and S(G).terr["9"] == nil') is True, "a claim after the company's first year is refused")
run('CO.find(G.st.co, 9).gone = "bankrupt"; claim(G, 9, "Gus#7", 70000, 70000, "W")')
check(run('return lastNews(G).why == "company"') is True, "a gone company cannot claim")

print("territories: their end")
run('NEND = nNews(G, "end"); jump(G, 4 * YEAR)')
check(run('return S(G).terr["2"].ended == "time" and S(G).terr["3"].ended == "time" and S(G).terr["1"].ended == "time"') is True,
      "after 5 years bob's, carl's and the host's territories end")
check(run('return nNews(G, "end") - NEND') == 4, "one news each (eve's too, claimed at the same time)")
run('NEND = nNews(G, "end"); steps(G, 100)')
check(run('return nNews(G, "end") == NEND') is True, "and no second one")
check(run('return (M.blockedFor(G.st, G.env, 3, 1000, 1000))') is False, "an ended territory refuses nothing")
# for good, and a company gone
L, run = game_runtime()
run('''
G = newGame(); makeReg(G); G.opts.territory = true; G.opts["territory.years"] = 0; G.opts["territory.radius"] = 3
steps(G, 25)
claim(G, 2, "Bob#1", 1000, 1000, "Aville")
claim(G, 3, "Carl#2", 7000, 1000, "Douves")
''')
check(run('local t = S(G).terr["2"]; return t.untilT == nil and t.years == 0 and t.r == 3000') is True, "years 0: protected for good, radius 3 km")
run('jump(G, 30 * YEAR)')
check(run('return S(G).terr["2"].ended == nil') is True, "still protected 30 years later")
run('CO.find(G.st.co, 3).gone = "bankrupt"; steps(G, 25)')
check(run('return S(G).terr["3"].ended == "gone" and lastNews(G).k == "end" and lastNews(G).why == "gone"') is True,
      "a bankrupt company's territory ends")
run('G.opts["territory.radius"] = 7')
check(run('return M.radius(G.env)') == 2000, "a radius the lobby does not offer: the default")

# ------------------------------------------------------------------------------------------------------------------------------
print("refusals of this player's builds (M.allow, M.proposal) and the computer companies' check")
L, run = game_runtime()
run('''
G = newGame(); makeReg(G); G.opts.territory = true
steps(G, 25)
claim(G, 2, "Bob#1", 1000, 1000, "Aville")
EC = guiEnv(G, 3, false, "Carl#2")      -- carl's game
EB = guiEnv(G, 2, false, "Bob#1")       -- bob's game
ST = "::/stations/rail/modular_station/modular_station.con"
function allow(e, co, p) local ok, why = M.allow(act(co, p), G.st, e) return ok, why end
''')
okc, why = run('return allow(EC, 3, conP(ST, 1500, 1500))')
check(okc is False and "Bob Co" in str(why) and "Aville" in str(why), "carl's station in bob's territory is refused, with a reason: " + str(why))
check(run('return (allow(EB, 2, conP(ST, 1500, 1500)))') is True, "bob builds in his own territory")
check(run('return (allow(EC, 3, conP(ST, 3500, 1000)))') is True, "carl builds outside it (2.5 km from its centre)")
check(run('return (allow(EC, 3, conP("::/depots/road/road_depot/road_depot.con", 1200, 900)))') is False, "a depot is refused")
check(run('return (allow(EC, 3, conP("stations/street/small_stops/small_old.con", 1200, 900)))') is False, "a stop construction is refused")
check(run('return (allow(EC, 3, conP("::/stations/air/airport.con", 1200, 900)))') is False, "an airport is refused")
check(run('return (allow(EC, 3, conP("::/street_construction/roundabout.con", 1200, 900)))') is True, "a road junction is not refused")
check(run('return (allow(EC, 3, conP("::/buildings/town/res_1.con", 1200, 900)))') is True, "a town building is not refused")
check(run('return (allow(EC, 3, trackP(1100, 1100)))') is True, "tracks and streets are not refused")
check(run('return (allow(EC, 3, stopP(1100, 1100)))') is False, "a new stop on a street is refused")
check(run('return (allow(EC, 3, stopP(1100, 1100, { again = true })))') is True,
      "a stop the stop tool only re-creates (new2oldEdgeObjects) is not")
check(run('return (allow(EC, 3, stopP(1100, 1100, { cat = 2 })))') is True, "a signal is not refused")
check(run('return (allow(EC, 3, stopP(1100, 1100, { noModel = true })))') is False, "a stop without a model position: its segment's nodes count")
check(run('return (allow(EC, 3, conP(ST, 1500, 1500, { 3001 })))') is True, "carl's own station there (from before the claim) may be edited")
check(run('return (allow(EC, 3, conP(ST, 1500, 1500, { { __ref = true, k = "con", id = 3001 } })))') is True,
      "the same edit in its shipped form (a reference with this game's entity)")
check(run('return (allow(EC, 3, conP(ST, 1500, 1500, { 2001 })))') is False, "rebuilding bob's station is no edit of carl's")
check(run('return (allow(EC, 3, conP(ST, 1500, 1500, { 4242 })))') is False, "a construction of nobody removed (a house) is no edit either")
check(run('return (M.allow({ fn = "makeVehicleBuyCmd", co = 3, args = { 1, 2 } }, G.st, EC))') is True, "other actions are allowed")
check(run('return (allow(EC, nil, conP(ST, 1500, 1500)))') is False, "an act without company: this player's company counts")
check(run('return (allow(EC, 4, conP(ST, 1500, 1500)))') is False, "a computer company's act shipped by the host is held to the territory too")
check(run('return (allow(guiEnv(G, nil, false, "Server"), nil, conP(ST, 1500, 1500)))') is True, "no company (a dedicated server): nothing refused here")
# the tool's own check (builder.proposalCreate: { Proposal, ProposalData } by position), on the game's userdata
check(run('return M.proposal({ ud(conP(ST, 1500, 1500)), ud({ errorState = { critical = false } }) }, G.st, EC) ~= nil') is True,
      "the tool's proposal (userdata) of carl's station there gets an error text")
check(run('return M.proposal({ ud(stopP(1100, 1100)), ud({ errorState = { critical = false } }) }, G.st, EC) ~= nil') is True,
      "the stop tool's proposal (userdata) there too")
check(run('return M.proposal({ ud(stopP(1100, 1100, { again = true })), ud({ errorState = { critical = false } }) }, G.st, EC)') is None,
      "a re-created stop (userdata) is not")
check(run('return M.proposal({ ud(conP(ST, 1500, 1500)), ud({ errorState = { critical = true } }) }, G.st, EC)') is None,
      "a proposal the game already refuses is left alone")
check(run('return M.proposal({ ud(conP(ST, 1500, 1500)), ud({ errorState = { critical = false } }) }, G.st, EB)') is None,
      "bob's own proposal there is not refused")
check(run('return M.proposal({ ud(conP(ST, 9500, 9500)), ud({ errorState = { critical = false } }) }, G.st, EC)') is None,
      "carl's proposal elsewhere is not refused")
check(run('return M.proposal({}, G.st, EC)') is None, "an event without a proposal: nothing")
check(run('local fr = guiEnv(G, 3, false, "Carl#2", FR); local _, w = allow(fr, 3, conP(ST, 1500, 1500)); return w:find("Territoire de Bob Co") ~= nil') is True,
      "the reason in French on a French game")
# the computer companies (host only, F5) and the quick checks
b, owner, town = run('return M.blockedFor(G.st, EC, 4, 1200, 1100)')
check(b is True and owner == 2 and town == "Aville", "a computer company may not build in bob's territory (M.blockedFor)")
check(run('return (M.blockedFor(G.st, EC, 4, 9000, 9000))') is False, "nor is it kept from building elsewhere")
check(run('return (M.blockedFor(G.st, nil, 4, 1200, 1100))') is True, "M.blockedFor without an env: the state's territories count")
check(run('return (M.blockedFor(G.st, EC, 2, 1200, 1100))') is False, "bob's own territory does not block bob")
# the mode "shared" (no registry) and the option off
run('G.opts.territory = false')
check(run('return (allow(EC, 3, conP(ST, 1500, 1500)))') is True and run('return (M.blockedFor(G.st, EC, 4, 1200, 1100))') is False,
      "the option off: nothing refused")
run('G.opts.territory = true; SAVEDCO = G.st.co; G.st.co = { mode = "shared", list = SAVEDCO.list }')
check(run('return (allow(EC, 3, conP(ST, 1500, 1500)))') is True, "mode shared: nothing refused")
run('G.st.co = SAVEDCO; CO.find(G.st.co, 2).gone = "merged"')
check(run('return (allow(EC, 3, conP(ST, 1500, 1500)))') is True, "bob's company gone: its territory refuses nothing, at once")

# ------------------------------------------------------------------------------------------------------------------------------
print("handicaps")
L, run = game_runtime()
run('''
G = newGame(); makeReg(G); G.opts.handicap = true
G.opts["handicap.money.bob"] = 50; G.opts["handicap.money.carl"] = 150; G.opts["handicap.money.host"] = 200
G.opts["handicap.money.ai:1"] = 200
steps(G, 25)
''')
check(run('return table.concat(G.books, " ")') == "200:-1000000 300:1000000",
      "bob 50 % (-1 000 000), carl 150 % (+1 000 000); not the savegame's company, not the computer company; eve 100 %: nothing")
check(run('return S(G).hc["1"] == nil and S(G).hc["4"] == nil and S(G).hc["5"].amount == 0 and S(G).hc["5"].pct == 100') is True,
      "eve's 100 % is noted (nothing booked), company 1 and the computer company have none")
check(run('return S(G).terr == nil and S(G).t0 == nil') is True, "territory off: no territory state")
check(run('return nNews(G, "hc")') == 2, "a news for each handicap booked")
run('steps(G, 200)')
check(run('return #G.books') == 2, "booked once only")
run('G2 = reload(G); steps(G2, 100)')
check(run('return #G2.books') == 0, "after a savegame reload: not booked again")
run('G = G2; G.opts["handicap.money"] = 75')
run('local d = CO.join(G.st.co, "dave", "Dave", false, "Dave Co", "s6", 6); d.start = 3000000; d.ent = 600; steps(G, 25)')
check(run('return table.concat(G.books, " ")') == "600:-750000", "a later company: the players' value (75 %) of its own start money (3 M)")
run('''G.books = {}; G.opts["handicap.money.erin"] = 125
local e = CO.join(G.st.co, "erin", "Erin", false, "Erin Co", "s7", 7)
steps(G, 25)''')
check(run('return #G.books == 0 and S(G).hc["7"].amount == 500000') is True, "a company without its player entity yet: decided, not booked")
run('CO.find(G.st.co, 7).ent = 700; steps(G, 1); steps(G, 50)')
check(run('return table.concat(G.books, " ")') == "700:500000", "booked once its entity is there")
# bankruptcy: a new company, a new start, a new handicap
run('''G.books = {}
CO.find(G.st.co, 2).gone = "bankrupt"; CO.find(G.st.co, 2).members = {}
local b2 = CO.join(G.st.co, "bob", "Bob", false, "Bob Co 2", "s2", 2); b2.ent = 210
steps(G, 25)''')
check(run('return table.concat(G.books, " ")') == "210:-1000000", "bob's new company after a bankruptcy gets his handicap again")
run('G.books = {}; local z = CO.join(G.st.co, "zed", "Zed", false, "Zed Co", "s9", 9); z.ent = 990; z.gone = "empty"; ZID = z.id; steps(G, 25)')
check(run('return #G.books == 0 and S(G).hc[tostring(ZID)] == nil') is True, "a gone company gets none")
# mode shared
run('GS = newGame("shared"); GS.opts.handicap = true; GS.opts.territory = true; steps(GS, 200); claim(GS, 1, "Host", 1, 1, "A")')
check(run('return GS.st.feat == nil and #GS.books == 0') is True, "mode shared: no state, no money")
check(run('return M.moneyPct(G.env, "nobody") == 75 and M.moneyPct({ param = function() return 33 end }, "x") == 100') is True,
      "a player without a value: the players' one; a value the lobby does not offer: 100 %")

# ------------------------------------------------------------------------------------------------------------------------------
print("determinism: two games, the same events")
SCRIPT = r'''
G = newGame(); makeReg(G); G.opts.territory = true; G.opts.handicap = true; G.opts["handicap.money.bob"] = 50
steps(G, 30)
claim(G, 2, "Bob#1", 1000, 1000, "Aville")
claim(G, 3, "Carl#2", 2500, 1000, "Bourg")
steps(G, 7)
claim(G, 3, "Carl#2", 6000, 1000, "Douves")
claim(G, 1, "Host", 1000, 12000, "Port")
local d = CO.join(G.st.co, "dave", "Dave", false, "Dave Co", "s6", 6); d.ent = 600
steps(G, 60)
if REVERSE then
  -- (the same territories put into the state in another order: the pairs() order differs)
  local t, ks = S(G).terr, {}
  for k in pairs(t) do ks[#ks + 1] = k end
  table.sort(ks, function(a, b) return a > b end)
  local n = {}
  for _, k in ipairs(ks) do n[k] = t[k] end
  S(G).terr = n
end
jump(G, 6 * YEAR)
claim(G, 6, "Dave#4", 30000, 30000, "Cité")
steps(G, 30)
return canon(G.st.feat), table.concat(G.books, " ")
'''
La, runa = game_runtime()
Lb, runb = game_runtime()
Lb.execute("REVERSE = true")
sa, ba = runa(SCRIPT)
sb, bb = runb(SCRIPT)
check(sa == sb, "the same state on both games")
check(ba == bb and ba != "", "the same bookings on both games: " + ba)
check(runa('return nNews(G, "end")') == 3 and runa('return S(G).terr["6"] == nil') is True,
      "(the three territories ended at one step, told in one order; dave's year was over)")
ok_plain, why_plain = runa('local ok, why = plain(G.st) return ok, tostring(why)')
check(ok_plain is True, "the state is plain data" + ("" if ok_plain else ": " + str(why_plain)))
check(runa('return (plain(COPY(G.st)))') is True, "(and a copy of it)")

# ------------------------------------------------------------------------------------------------------------------------------
print("GUI half: host and client")
L, run = game_runtime()
run('''
G = newGame(); makeReg(G); G.opts.territory = true; G.opts.handicap = true; G.opts["handicap.money.bob"] = 50
steps(G, 25)
EH = guiEnv(G, 1, true, "Host")
EC = guiEnv(G, 3, false, "Carl#2")
M.gui(G.st, EH)            -- (the first look of each game)
''')
check(run('return #EH.chats') == 1, "a handicap booked at the start is told (younger than 30 s of game time)")
run('''
M2 = M
claim(G, 2, "Bob#1", 1000, 1000, "Aville")
claim(G, 3, "Carl#2", 2500, 1000, "Bourg")       -- refused: too close to bob's
M.gui(G.st, EH)
''')
check(run('return #EH.sends') == 0, "the host's game sends no event")
check(run('return #EH.chats == 2 and EH.chats[2]:find("Bob Co claimed Aville") ~= nil') is True,
      "the host's chat tells bob's claim: " + str(run('return EH.chats[2]')))
check(run('local z = ZONES["mpfever_terr_2"]; return z and z.x == 1000 and z.r == 2000 and z.draw == true and z.prohibit == false and z.a == M.ALPHA') is True,
      "bob's circle on the ground: its centre, 2 km, drawn, building not prohibited by the zone")
check(run('return fileOf(EH):find("terr\\t2\\tBob Co\\tAville\\t2\\ton\\t60\\t0", 1, true) ~= nil') is True,
      "the window's file lists bob's territory (60 months left)")
check(run('return fileOf(EH):find("hc\\t2\\tBob Co\\t50\\t-1000000", 1, true) ~= nil') is True, "and bob's handicap")
check(run('return fileOf(EH):find("me\\tclaim\\t12\\t0", 1, true) ~= nil') is True, "the host may still claim (12 months)")
check(run('return fileOf(EH):find("town\\t13\\tCité\\t1", 1, true) ~= nil and fileOf(EH):find("town\\t12\\tBourg\\t0", 1, true) ~= nil') is True,
      "the claim list: Cité free, Bourg too close to bob's")
# the client's game: the same news, its own refusal, nothing sent
run('ZC0 = ZCALLS; M.newsSeen = nil; M.gui(G.st, EC)')
check(run('return #EC.sends') == 0, "the client's game sends no event either")
check(run('local n = 0 for _, c in ipairs(EC.chats) do if c:find("Claim of Bourg refused", 1, true) then n = n + 1 end end return n') == 1,
      "carl's game tells carl's refused claim")
check(run('for _, c in ipairs(EH.chats) do if c:find("refused", 1, true) then return false end end return true') is True,
      "the host's game does not tell carl's refusal")
run('N = #EC.chats; M.gui(G.st, EC); M.gui(G.st, EC)')
check(run('return #EC.chats == N and ZCALLS == ZC0') is True, "nothing told twice, the circles not drawn again while unchanged")
# a load: the old news are not told again
run('jump(G, 120000); G2 = reload(G); EC2 = guiEnv(G2, 3, false, "Carl#2"); M.gui(G2.st, EC2)')
check(run('return #EC2.chats') == 0, "after a load the old news are not told again")
check(run('return ZONES["mpfever_terr_2"] ~= nil') is True, "and the circles are drawn again")
# French
run('EF = guiEnv(G2, 3, false, "Carl#2", FR); claim(G2, 1, "Host", 1000, 12000, "Port"); M.gui(G2.st, EF)')
check(run('return EF.chats[#EF.chats]:find("Host Co a revendiqué Port comme territoire (rayon 2 km, protégé pendant 5 ans)", 1, true) ~= nil') is True,
      "the news in French: " + str(run('return EF.chats[#EF.chats]')))
# the end of a protection takes the circle away
run('jump(G2, 5 * YEAR - 60000); M.gui(G2.st, EF)')
check(run('return ZONES["mpfever_terr_2"] == nil and ZONES["mpfever_terr_1"] ~= nil') is True,
      "bob's circle goes when its protection ends (the host's, claimed later, stays)")
check(run('return fileOf(EF):find("terr\\t2\\tBob Co\\tAville\\t2\\tended", 1, true) ~= nil') is True, "the file says it ended")
# the option off: the circles go, no file
run('G2.opts.territory = false; G2.opts.handicap = false; NW = #EF.writes; M.gui(G2.st, EF)')
check(run('return next(ZONES) == nil and #EF.writes == NW') is True, "options off: the circles go, no file written")

print("GUI half: the window's requests and tab")
L, run = game_runtime()
run('''
G = newGame(); makeReg(G); G.opts.territory = true; G.opts.handicap = true
steps(G, 25)
claim(G, 2, "Bob#1", 1000, 1000, "Aville")
EC = guiEnv(G, 3, false, "Carl#2")
M.gui(G.st, EC)
R1 = M.request("claim", "13", G.st, EC)
R2 = M.request("claim", 12, G.st, EC)
R3 = M.request("claim", 99, G.st, EC)
''')
check(run('return R1 == true and #EC.sends == 1 and EC.sends[1].name == "f_territory_claim"') is True, "a claim of Cité is sent")
check(run('local p = EC.sends[1].p; return p.x == 20000 and p.y == 20000 and p.name == "Cité" and p.mpfCo == nil') is True,
      "with the town's centre and name (the bridge adds the sender's company)")
check(run('return R2 == false and #EC.sends == 1 and EC.chats[#EC.chats - 1]:find("Too close to the territory of Bob Co", 1, true) ~= nil') is True,
      "a claim of Bourg is refused here, with the reason in the chat")
check(run('return R3 == false and EC.chats[#EC.chats] == "Town not found."') is True, "an unknown town: nothing sent")
run('ev(G, EC.sends[1].name, { x = 20000, y = 20000, name = "Cité", mpfCo = 3, mpfFrom = "Carl#2" }); M.gui(G.st, EC)')
check(run('return M.request("drop", "", G.st, EC) == true and EC.sends[2].name == "f_territory_drop"') is True, "carl may give it up")
check(run('return M.request("drop", "", G.st, guiEnv(G, 5, false, "Eve#3")) == false') is True, "eve, without a territory, sends nothing")
items = run('''
local items = M.uiModel(EC.writes[#EC.writes].lines, nil)
local out = {}
for _, it in ipairs(items) do out[#out + 1] = it.kind .. "|" .. tostring(it.text) .. "|" .. tostring(it.req) .. "|" .. tostring(it.payload) end
return table.concat(out, "\\n")''')
check("title|Territories" in items and "Your territory: Cité (radius 2 km), protected for 60 more month(s)." in items,
      "the tab shows carl's territory")
check("button|You may still change your mind" in items and "|drop|" in items, "and the button to give it up within the year")
check("Bob Co: Aville, radius 2 km, 60 more month(s)" in items, "and bob's territory")
check("title|Money handicaps" in items and "Carl Co: 100 % of the start money (+0)" in items, "and the handicaps")
run('''
EE = guiEnv(G, 5, false, "Eve#3"); M.gui(G.st, EE)
MADE, REQS = {}, {}
U = { T = function(fr, en) return en end, read = function(f) return f == M.FILE and EE.writes[#EE.writes].lines or nil end,
  request = function(k, p) REQS[#REQS + 1] = k .. ":" .. tostring(p) end,
  text = function(s) MADE[#MADE + 1] = "text:" .. s; return { s = s } end,
  button = function(label, fn) MADE[#MADE + 1] = "button:" .. label; return { label = label, fn = fn } end,
  row = function(list) return { row = list } end }
W = M.ui(U)
local claimBtn = nil
for _, w in ipairs(W) do if w.row and w.row[2].label == "Claim" then claimBtn = claimBtn or w.row[2] end end
claimBtn.fn()
''')
check(run('return #W > 0 and REQS[1] == "claim:14"') is True,
      "eve's tab offers the biggest free town first (Douves: Aville and Cité are taken, Bourg too close); its button asks the window's request")
check(run('for _, m in ipairs(MADE) do if m == "text:Bourg (too close to another territory)" then return true end end return false') is True,
      "a town too close to a territory is shown without a button")
run('S(G).seen["5"] = S(G).t0; jump(G, YEAR + 1000); EE2 = guiEnv(G, 5, false, "Eve#3"); M.gui(G.st, EE2)')
check(run('return fileOf(EE2):find("me\\tlate", 1, true) ~= nil and M.request("claim", 13, G.st, EE2) == false') is True,
      "after the year: no claim list, a claim is refused here")
check(run('return #M.uiModel({ "garbage", "rule\\t2" }, nil) > 0') is True, "the tab survives a damaged file")

# ------------------------------------------------------------------------------------------------------------------------------
if failures:
    print(f"FAIL {len(failures)} case(s): " + "; ".join(failures))
    sys.exit(1)
print("all passed")
sys.exit(0)
