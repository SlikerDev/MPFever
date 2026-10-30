"""The players' journal, « built by » and a player's view (mpfever_feat_journal.lua, 0.6 options "journal", "builtby" and
"playerview"), offline: the module is run through lupa (Lua 5.2) on several simulated games, each with its own Lua state, the
mock env of docs/FEATURES-0.6.md (env.on, env.param, env.state, env.book, env.companies... in the simulation half; env.isHost,
env.me, env.send, env.chat, env.write, env.realTime in the GUI half) and a lockstep: the events a game's GUI sends are applied
by every game in the same order.

Cases: every option off (no state, no event, no file, no chat, no money); the journal's entries for builds (station, depot,
road merged, signals, town buildings, demolitions, edits), purchases, sales, lines, terrain, trees; the actions left out
(computer companies, mods, autotests, a company's announcement, an action refused, an action given twice); the chat's only
notice (« X demolished what Y built », once, not again after a load); determinism (the same actions on two games give the same
state, and in another order the same journal); the registry (tolerance of a metre, edits, « changed by », computer companies'
demolitions, the cap); the view (an answer, a refusal kept in the state, the host's time-out and only the host's, the separate
mode's rule of one company, a bankrupt company, a computer company, a load that does not take an old answer again); the
journal's cap; the state as plain data through a save and a load; the window's tab (details, player filter, Show, view buttons).
Run: python tests/test_feat_journal.py
"""
import os
import sys

try:
    import lupa.lua52 as lua52
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_PATH = os.path.join(HERE, "..", "mod", "mpfever_1", "content", "mpfever_feat_journal.lua")
SRC = open(SRC_PATH, encoding="utf-8").read()

STATION = "stations/rail/modular_station/modular_station.con"
DEPOT = "depots/road/road_depot/road_depot.con"
HOUSE = "buildings/a/c1/a_com_l1_1x1_01.con"

HARNESS = r'''
OPTS = {}
MODE = "shared"
COMPANIES = nil
TIME = 100000
RT = 0
LOG, SENT, CHAT, FILES, BOOK, CAMSET, FOCUS = {}, {}, {}, {}, {}, {}, {}
WRITES = 0
CAM = { 1200.5, -340.25, 650, 0.75, 0.5 }
ST = {}
PLAYERS = nil
function T_fr(fr, en) return fr end
function T_en(fr, en) return en end

-- a value as text, the same for the same value (sorted keys); an error for anything but plain data, or a cycle
function ser(v, seen)
  local t = type(v)
  if t == "string" then return string.format("%q", v) end
  if t == "number" then return string.format("%.17g", v) end
  if t == "boolean" or t == "nil" then return tostring(v) end
  if t == "table" then
    seen = seen or {}
    if seen[v] then error("a cycle in the state") end
    seen[v] = true
    local keys = {}
    for k in pairs(v) do
      if type(k) ~= "string" and type(k) ~= "number" then error("a key of type " .. type(k)) end
      keys[#keys + 1] = k
    end
    table.sort(keys, function(a, b) if type(a) ~= type(b) then return type(a) < type(b) end return a < b end)
    local parts = {}
    for _, k in ipairs(keys) do parts[#parts + 1] = "[" .. ser(k, seen) .. "]=" .. ser(v[k], seen) end
    seen[v] = nil
    return "{" .. table.concat(parts, ",") .. "}"
  end
  error("not plain data: " .. t)
end
function deser(s) return assert(load("return " .. s))() end

function defaultParam(id, pid)
  for _, o in ipairs(M.OPTIONS) do
    if o.id == id then for _, p in ipairs(o.params or {}) do if p.id == pid then return p.default end end end
  end
end
function simEnv(from)
  return {
    log = function(s) LOG[#LOG + 1] = s end,
    gameTime = function() return TIME end, STEP = 200,
    on = function(id) return OPTS[id] == true end,
    param = function(id, pid) local v = OPTS[id .. "." .. pid]; if v == nil then v = defaultParam(id, pid) end; return v end,
    state = function(st) st.feat = st.feat or {}; st.feat[M.ID] = st.feat[M.ID] or {}; return st.feat[M.ID] end,
    mode = MODE, co = (MODE == "separate") and ST.co or nil,
    companies = function() return COMPANIES or {} end,
    money = function(ent) return 0 end,
    book = function(ent, amount) BOOK[#BOOK + 1] = { ent, amount } end,
    R = {}, every = function(n) return false end,
    month = function() return 1925 * 12 + 2 end,
    from = from,
  }
end
function guiEnv(me, isHost, myCo, T)
  return {
    log = function(s) LOG[#LOG + 1] = s end,
    on = function(id) return OPTS[id] == true end,
    param = function(id, pid) local v = OPTS[id .. "." .. pid]; if v == nil then v = defaultParam(id, pid) end; return v end,
    isHost = isHost, me = me, myCo = myCo,
    send = function(name, param) SENT[#SENT + 1] = { name = name, param = param } end,
    chat = function(t) CHAT[#CHAT + 1] = t end,
    write = function(file, lines) local c = {} for i, l in ipairs(lines) do c[i] = l end FILES[file] = c; WRITES = WRITES + 1 end,
    realTime = function() return RT end,
    T = T or T_en,
    players = PLAYERS and function() return PLAYERS end or nil,
  }
end
M.camGet = function() return M.camData(CAM) end
M.camSet = function(d) CAMSET[#CAMSET + 1] = d; return true end
M.focus = function(e) FOCUS[#FOCUS + 1] = e end

-- the actions, as the games replay them (references not translated yet, see the bridge's R.translateOut)
function mat(x, y, z)
  local t = { __mat = true }
  for i = 1, 16 do t[i] = 0 end
  t[1], t[6], t[11], t[16] = 1, 1, 1, 1
  t[13], t[14], t[15] = x, y, z or 0
  return t
end
function conRef(f, x, y) return { __ref = true, k = "con", id = 77, f = f, p = { x = x, y = y, z = 10 } } end
function seg(x0, y0, x1, y1, typ)
  return { entity = -1, type = typ or 0, comp = { node0 = -1, node1 = -2,
    position0 = { x = x0, y = y0, z = 0, __vec = true }, position1 = { x = x1, y = y1, z = 0, __vec = true } } }
end
function build(origin, oseq, at, adds, rems, prop, extra)
  local m = { toAdd = {}, toRemove = rems or {}, proposal = prop or { addedNodes = {}, addedSegments = {}, removedNodes = {}, removedSegments = {}, edgeObjectsToAdd = {} } }
  for i, a in ipairs(adds or {}) do m.toAdd[i] = { fileName = a[1], transf = mat(a[2], a[3], 5), params = {} } end
  local a = { fn = "makeWorldBuildProposalCmd", args = { n = 4, [1] = m, [2] = { __player = true }, [3] = false, [4] = true },
    origin = origin, oseq = oseq, uid = origin .. ":" .. oseq, at = at, native = true, co = 1 }
  for k, v in pairs(extra or {}) do a[k] = v end
  return a
end
function road(origin, oseq, at, segs, removed, objs)
  return build(origin, oseq, at, nil, nil, { addedNodes = {}, addedSegments = segs or {}, removedNodes = {}, removedSegments = removed or {}, edgeObjectsToAdd = objs or {} })
end
function act(origin, oseq, at, fn, args, extra)
  local a = { fn = fn, args = args, origin = origin, oseq = oseq, uid = origin .. ":" .. oseq, at = at, co = 1 }
  for k, v in pairs(extra or {}) do a[k] = v end
  return a
end
function busCfg(model) return { vehicles = { { part = { modelId = model, __ud = true }, __ud = true } }, vehicleGroups = { 1 }, __ud = true } end
function depotRef(x, y) return { __ref = true, k = "depot", id = 55, con = { k = "con", f = "depots/road/road_depot/road_depot.con", p = { x = x, y = y, z = 3 } }, i = 1 } end
function sgRef(x, y) return { __ref = true, k = "sg", id = 66, st = { k = "station", con = { k = "con", f = "stations/street/x.con", p = { x = x, y = y, z = 0 } }, i = 1 } } end
function J() return ST.feat and ST.feat[M.ID] end
function kinds()
  local r = {}
  for _, e in ipairs(M.entries(J())) do r[#r + 1] = e.kind end
  return table.concat(r, ",")
end
function entry(kind, nth)
  local n = 0
  for _, e in ipairs(M.entries(J())) do if e.kind == kind then n = n + 1; if n == (nth or 1) then return e end end end
end
'''

failures = []


def check(cond, what):
    print(("  ok    " if cond else "  FAIL  ") + what)
    if not cond:
        failures.append(what)


class Game:
    """One game: its own Lua state, its module, its state (ST) and its player (me, as the bridge's G.me)."""

    def __init__(self, me, host=False, opts=None, mode="shared", companies=None, myco=None):
        self.L = lua52.LuaRuntime(unpack_returned_tuples=True)
        self.no_api = self.L.globals().api is None
        self.M = self.L.execute(SRC)
        self.L.globals().M = self.M
        self.L.execute(HARNESS)
        self.me, self.host, self.myco = me, host, myco
        self.set_opts(opts or {})
        self.run(f'MODE = "{mode}"')
        if companies:
            self.run("COMPANIES = " + companies)
            if mode == "separate":
                self.run('ST.co = { mode = "separate", list = COMPANIES }')

    def run(self, code):
        return self.L.execute(code)

    def ev(self, expr):
        return self.L.eval(expr)

    def set_opts(self, opts):
        self.run("OPTS = {}")
        for k, v in opts.items():
            self.run(f'OPTS["{k}"] = {"true" if v is True else v}')

    def action(self, expr, ok="true"):
        self.run(f"M.onAction(ST, {expr}, {ok}, simEnv())")

    def gui(self, T="T_en"):
        self.run(f'M.gui(ST, guiEnv("{self.me}", {str(self.host).lower()}, {self.myco or "nil"}, {T}))')

    def request(self, kind, payload):
        self.run(f'M.request("{kind}", "{payload}", ST, guiEnv("{self.me}", {str(self.host).lower()}, {self.myco or "nil"}))')

    def take_sent(self):
        n = int(self.ev("#SENT"))
        out = [(self.ev(f"SENT[{i}].name"), self.ev(f"ser(SENT[{i}].param)")) for i in range(1, n + 1)]
        self.run("SENT = {}")
        return out

    def state(self):
        return self.ev("ser(ST.feat)")


def lockstep(games, senders, with_from=True):
    """The events the GUIs of `senders` sent, applied by every game in the same order (the stamped events of the options host)."""
    events = []
    for g in senders:
        for name, param in g.take_sent():
            events.append((g.me, name, param))
    for g in games:
        for origin, name, param in events:
            frm = f'"{origin}"' if with_from else "nil"
            g.run(f'M.event(ST, "{name}", deser([==[{param}]==]), simEnv({frm}))')
    return events


def both(games, expr, ok="true"):
    for g in games:
        g.action(expr, ok)


# ---------------------------------------------------------------------------------------------------------- the module itself
print("module")
g = Game("Alice", host=True)
check(g.no_api, "the module loads without the game's API (the lobby and the tests require it)")
M = g.M
check(M.ID == "journal" and M.TAB.id == "journal", "ID and tab")
opt_ids = [M.OPTIONS[i].id for i in range(1, len(M.OPTIONS) + 1)]
check(opt_ids == ["journal", "builtby", "playerview"], f"three options: {opt_ids}")
shape_ok = True
for i in range(1, len(M.OPTIONS) + 1):
    o = M.OPTIONS[i]
    shape_ok = shape_ok and o.modes == "both" and len(o.title) == 2 and len(o.desc) == 2
    shape_ok = shape_ok and all(isinstance(o.title[k], str) and isinstance(o.desc[k], str) for k in (1, 2))
    if o.params:
        for j in range(1, len(o.params) + 1):
            p = o.params[j]
            shape_ok = shape_ok and p.default in [p["values"][k] for k in range(1, len(p["values"]) + 1)]
check(shape_ok, "options: French and English title and text, modes both, each parameter's default among its values")
check(g.ev('M.OPTIONS[1].params[1].show(1, T_fr)') == "oui" and g.ev('M.OPTIONS[1].params[1].show(0, T_en)') == "no",
      "the details parameter shows yes / no in the game's language")
check(all(k.startswith("f_journal") for k in g.ev("M.EVENTS").keys()), "events named f_journal_*")
check(g.ev('M.allow') is None and g.ev('M.tick') is None, "no refusal of actions, no tick (nothing to do every step)")
check(g.ev('#M.TEXTS.chat_demolish == 2'), "texts in French and English")

# ---------------------------------------------------------------------------------------------------------- everything off
print("options off: nothing at all")
off = Game("Alice", host=True, opts={})
off.run(f'''
for _, a in ipairs({{
  build("Alice", 1, 1000, {{ {{ "{STATION}", 100, 200 }} }}),
  build("Bob#1", 2, 1200, nil, {{ conRef("{STATION}", 100, 200) }}),
  road("Alice", 3, 1300, {{ seg(0, 0, 100, 0) }}),
  act("Bob#1", 4, 1400, "makeVehicleBuyCmd", {{ n = 3, [1] = 0, [2] = depotRef(5, 5), [3] = busCfg(1234) }}),
  act("Bob#1", 5, 1500, "makeLineCreateCmd", {{ n = 4, [1] = "L1", [2] = {{}}, [3] = 0, [4] = {{ stops = {{ {{ stationGroup = sgRef(1, 2) }} }} }} }}),
}}) do M.onAction(ST, a, true, simEnv()) end
for name in pairs(M.EVENTS) do
  M.event(ST, name, {{ to = "bob", from = "Alice", id = 1, d = {{ 1, 2, 3, 4, 5 }}, allow = false }}, simEnv("Alice"))
end
M.gui(ST, guiEnv("Alice", true)); M.gui(ST, guiEnv("Bob#1", false))
RT = 100
M.gui(ST, guiEnv("Alice", true))
M.request("view", "bob", ST, guiEnv("Alice", true)); M.request("share", "0", ST, guiEnv("Alice", true))
''')
check(off.ev("ST.feat") is None, "no state (st.feat untouched)")
check(off.ev("#SENT") == 0 and off.ev("#CHAT") == 0 and off.ev("WRITES") == 0 and off.ev("#BOOK") == 0,
      "no event sent, no chat, no file written, no money")

# only the view on: the actions write no journal and no registry
pv = Game("Alice", host=True, opts={"playerview": True})
pv.action(f'build("Alice", 1, 1000, {{ {{ "{STATION}", 100, 200 }} }})')
check(pv.ev("J().nlog") == 0 and pv.ev("J().nreg") == 0 and pv.ev("J().who.alice") == "Alice",
      "only the view on: no journal, no registry, the player is known for the view's list")

# ---------------------------------------------------------------------------------------------------------- the journal
print("journal: entries")
OPT_J = {"journal": True}
A = Game("Alice", host=True, opts=OPT_J)
B = Game("Bob#1", host=False, opts=OPT_J)
AB = [A, B]
both(AB, f'build("Alice", 1, 1000, {{ {{ "{STATION}", 100, 200 }} }}, nil, nil, {{ cost = 120000 }})')
both(AB, 'road("Alice", 2, 2000, { seg(0, 0, 100, 0) })')
both(AB, 'road("Alice", 3, 5000, { seg(100, 0, 200, 0) })')
both(AB, f'build("Alice", 4, 6000, {{ {{ "{DEPOT}", 300, 300 }} }})')
both(AB, 'act("Bob#1", 3, 7000, "makeVehicleBuyCmd", { n = 3, [1] = { __ref = true, k = "player", co = 1 }, [2] = depotRef(300, 300), [3] = busCfg(1234) })')
both(AB, 'act("Bob#1", 4, 8000, "makeLineCreateCmd", { n = 4, [1] = "Ligne 1", [2] = { x = 1, y = 0, z = 0, __vec = true }, [3] = 0, [4] = { stops = { { stationGroup = sgRef(10, 20) } } } })')
for g_ in AB:
    g_.gui()   # the first look after the load: nothing to tell yet
check(A.ev("kinds()") == "station,road,depot,buy,line", f"station, road (merged), depot, purchase, line: {A.ev('kinds()')}")
check(A.ev('entry("road").n') == 200 and A.ev('entry("road").at') == 2000, "two roads of one player within 30 s: one entry of 200 m, at the first one's time")
check(A.ev('entry("station").c') == 120000 and A.ev('entry("station").who') == "Alice" and A.ev('entry("station").x') == 100,
      "the station's entry: its cost, its builder (the name without #n), its place")
check(A.ev('entry("buy").a') == "1234" and A.ev('entry("buy").who') == "Bob" and A.ev('entry("buy").x') == 300, "the purchase: its model, its depot's place")
check(A.ev("M.text(entry('buy'), T_en)") == "Bob bought 1 vehicle(s): #1234" and A.ev("M.text({ who = 'Bob', kind = 'buy', n = 1, a = '' }, T_fr)")
      == "Bob a acheté 1 véhicule(s) : un modèle inconnu", "the purchase's text (the model's name from the game, else its id; none: « an unknown model »)")
check(A.ev('entry("line").a') == "Ligne 1" and A.ev('entry("line").y') == 20, "the line: its name, its first stop's place")
check(A.ev('entry("station").ym') == 1925 * 12 + 2, "the game month of the entry (env.month)")

# left out: computer companies, mods, autotests, a company's announcement, an action refused, an action given twice
before = A.ev("ser(J())")
both(AB, 'act("Alice", 20, 8500, "makeVehicleBuyCmd", { n = 3, [1] = 0, [2] = depotRef(300, 300), [3] = busCfg(99) }, { tok = "ai", co = 3 })')
both(AB, 'act("Alice", 21, 8500, "makeLineUpdateCmd", { n = 2, [1] = 5, [2] = {} }, { tok = "mod" })')
both(AB, 'act("Alice", 22, 8500, "makeVehicleSellCmd", { n = 1, [1] = 5 }, { tok = "auto-sell" })')
both(AB, 'act("Alice", 23, 8500, "mpfCoJoin", { key = "alice", mode = "separate" })')
both(AB, 'act("Bob#1", 24, 8600, "makeVehicleSellCmd", { n = 1, [1] = 5 })', ok="false")
both(AB, 'act("Bob#1", 4, 8000, "makeLineCreateCmd", { n = 4, [1] = "Ligne 1", [2] = {}, [3] = 0, [4] = { stops = {} } })')
check(A.ev("ser(J())") == before, "nothing for a computer company's, a mod's, an autotest's action, a company's announcement, a refused action or one given twice")

# the act itself is never changed (the bridge translates its arguments in place after)
A.run(f'TESTACT = build("Bob#1", 9, 9000, nil, {{ conRef("{STATION}", 100.6, 199.6) }}); TESTSER = ser(TESTACT)')
A.run("M.onAction(ST, TESTACT, true, simEnv())")
B.action(f'build("Bob#1", 9, 9000, nil, {{ conRef("{STATION}", 100.6, 199.6) }})')
check(A.ev("ser(TESTACT) == TESTSER"), "the action is read only, never changed")
check(A.ev('entry("demolish").b') == "Alice" and A.ev('entry("demolish").who') == "Bob",
      "Bob demolished the station Alice built (found 0.6 m and 0.4 m away)")
check(A.ev(f'M.regGet(J(), M.conKey("{STATION}", 100, 200))') is None, "the demolished station leaves the registry")

both(AB, 'road("Bob#1", 10, 10000, { seg(0, 50, 30, 50), seg(30, 50, 60, 50) }, { seg(0, 50, 60, 50) }, '
         '{ { category = 2, modelInstance = { transf = mat(30, 50, 0) } } })')
both(AB, 'act("Bob#1", 11, 11000, "makeLineDestroyCmd", { n = 1, [1] = { __ref = true, k = "line", id = 8, key = "LBob#1:4@8000" } })')
both(AB, f'build("Bob#1", 12, 12000, nil, {{ conRef("{HOUSE}", 1, 1), conRef("{HOUSE}", 9, 9) }})')
both(AB, 'act("Alice", 13, 13000, "makeVehicleSellCmd", { n = 1, [1] = { { __ref = true, k = "veh", id = 4, key = "VBob#1:3@7000" } } })')
both(AB, 'act("Alice", 14, 14000, "terrainEdit", { x0 = 1, y0 = 2, w = 3, h = 4 })')
both(AB, 'act("Alice", 15, 15000, "terrainEdit", { x0 = 1, y0 = 2, w = 3, h = 4 })')
both(AB, 'act("Alice", 16, 16000, "assetBuild", { assets = { { models = { { id = "tree", transf = mat(5, 6, 0) }, { id = "tree", transf = mat(7, 6, 0) } } } }, toRemove = {} })')
both(AB, 'road("Alice", 17, 17000, nil, { seg(0, 0, 100, 0, 1) })')
check(A.ev("kinds()") == "station,road,depot,buy,line,demolish,signal,unline,houses,sell,terrain,trees,track_del",
      f"the whole journal: {A.ev('kinds()')}")
check(A.ev('entry("signal").det') == 1 and A.ev('entry("signal").n') == 1, "a signal is a detail, the segments it splits are no change of their own")
check(A.ev('entry("unline").a') == "Ligne 1" and A.ev('entry("unline").b') == "Bob", "the line deleted: its name from its creation, its creator")
check(A.ev('entry("houses").n') == 2, "two town buildings taken away: one entry")
check(A.ev('entry("sell").b') == "Bob", "Alice sold a vehicle Bob bought")
check(A.ev('entry("terrain").n') == 2 and A.ev('entry("trees").n') == 2 and A.ev('entry("track_del").n') == 100,
      "terrain twice (merged), two trees, 100 m of track demolished")
check(A.ev("M.text(entry('demolish'), T_en)") == "Bob demolished « modular station », built by Alice", "the demolition's text in English")
check(A.ev("M.text(entry('demolish'), T_fr)") == "Bob a démoli « modular station », construit par Alice", "... and in French")
check(A.ev("M.text(entry('station'), T_en)").startswith("Alice built the station « modular station » ($120000"),
      "the station's text with its cost: " + A.ev("M.text(entry('station'), T_en)"))

print("journal: the chat and the window's file")
for g_ in AB:
    g_.gui()
check(A.ev("#CHAT") == 1 and B.ev("#CHAT") == 1, "the demolition told once in each game's chat")
check(A.ev("CHAT[1]") == "Bob demolished what Alice built: « modular station »", "the chat's text: " + str(A.ev("CHAT[1]")))
for g_ in AB:
    g_.gui()
check(A.ev("#CHAT") == 1, "not told again")
check(A.ev("#CHAT") == 1 and A.ev("CHAT[2]") is None, "no other chat notice (G1: only the demolitions)")
fileA = A.ev(f'FILES["{M.FILE}"]')
check(fileA is not None and A.ev(f'FILES["{M.FILE_BUILTBY}"]') is None, "the tab's file written, not the registry's (builtby off)")
check(A.ev(f'FILES["{M.FILE}"][3]') == "@on\t1\t0\t0" and A.ev(f'#FILES["{M.FILE}"]') == 6 + int(A.ev("J().nlog")),
      "the file: its header, then every entry")
w0 = A.ev("WRITES")
A.gui()
check(A.ev("WRITES") == w0, "nothing written while nothing changed")
check(A.ev("J().nreg") >= 1, "the registry is kept with the journal alone (for « X demolished what Y built »)")

print("journal: determinism")
check(A.state() == B.state(), "two games, the same actions: the same state")
C = Game("Carl", opts=OPT_J)
D = Game("Dave", opts=OPT_J)
seq = [
    'road("Alice", 1, 2000, { seg(0, 0, 50, 0) })',
    'road("Alice", 2, 2600, { seg(50, 0, 80, 0) })',
    f'build("Bob#1", 3, 2400, {{ {{ "{STATION}", 7, 8 }} }})',
    'act("Bob#1", 4, 2400, "makeVehicleSellCmd", { n = 1, [1] = 5 })',
    'road("Alice", 5, 1000, { seg(0, 9, 10, 9) })',
]
for s in seq:
    C.action(s)
for s in reversed(seq):
    D.action(s)
check(C.ev("J().log") == D.ev("J().log") and C.ev("J().reg") == D.ev("J().reg") and C.ev("J().seq") == D.ev("J().seq"),
      "the same actions in another order (a native build handed over later): the same journal and registry")
check(C.ev('entry("road").n') == 90 and C.ev('entry("road").at') == 1000, "three roads in one 30 s: one entry of 90 m at the earliest time")

print("journal: the digest of an action")
# the options host may take M.digest(a) before the action is applied (the bridge then translates its references in place) and
# hand it to M.onAction instead of the action (a native build replayed by the interface: through the simulation's events)
P = Game("Carl", opts=OPT_J)
Q = Game("Dave", opts=OPT_J)
digest_seq = [
    f'build("Alice", 1, 1000, {{ {{ "{STATION}", 100, 200 }} }})',
    f'build("Bob#1", 2, 2000, nil, {{ conRef("{STATION}", 100, 200) }})',
    'act("Bob#1", 3, 3000, "makeVehicleSellCmd", { n = 1, [1] = { { __ref = true, k = "veh", id = 4, key = "VAlice:3@700" } } })',
    'act("Bob#1", 4, 4000, "makeVehicleBuyCmd", { n = 3, [1] = 0, [2] = depotRef(1, 2), [3] = busCfg(77) }, { tok = "ai" })',
]
for s in digest_seq:
    P.action(s)
    Q.run(f"DG = M.digest({s})")
    Q.run("M.onAction(ST, deser(ser(DG)), true, simEnv())")   # (plain data: it travels as an event of the simulation)
check(P.state() == Q.state(), "the digest gives the same state as the action")
R_ = Game("Erin", opts=OPT_J)
R_.run(f'X = build("Alice", 1, 1000, {{ {{ "{STATION}", 100, 200 }} }}); M.onAction(ST, X, true, simEnv())')
R_.run(f'X = build("Bob#1", 2, 2000, nil, {{ conRef("{STATION}", 100, 200) }}); DG = M.digest(X)')
R_.run("X.args[1].toRemove[1] = 4711")   # (what the bridge's R.translateIn leaves: this game's entity id)
R_.run("M.onAction(ST, DG, true, simEnv())")
check(R_.ev('entry("demolish").b') == "Alice", "a digest taken before the translation keeps the demolished station's builder")
R2 = Game("Erin", opts=OPT_J)
R2.run(f'X = build("Alice", 1, 1000, {{ {{ "{STATION}", 100, 200 }} }}); M.onAction(ST, X, true, simEnv())')
R2.run(f'X = build("Bob#1", 2, 2000, nil, {{ 4711 }}); M.onAction(ST, X, true, simEnv())')
check(R2.ev('entry("demolish").b') is None and R2.ev('M.text(entry("demolish"), T_en)') == "Bob demolished a construction",
      "an action already translated: « a construction », its builder unknown (hence the digest)")

# ---------------------------------------------------------------------------------------------------------- built by
print("built by")
OPT_B = {"builtby": True}
E = Game("Alice", host=True, opts=OPT_B)
E.action(f'build("Alice", 1, 1000, {{ {{ "{STATION}", 100.4, 200 }} }})')
check(E.ev("J().nlog") == 0 and E.ev("J().nreg") == 1, "built by alone: the registry, no journal")
E.action(f'build("Bob#1", 2, 2000, {{ {{ "{STATION}", 100.4, 200 }} }}, {{ conRef("{STATION}", 100.5, 200.2) }})')
E.action(f'build("Bob#1", 3, 3000, {{ {{ "{DEPOT}", 50, 50 }} }}, {{ conRef("{DEPOT}", 50, 50) }})')
E.action(f'build("Carl", 4, 4000, {{ {{ "{STATION}", 900, 900 }} }})')
E.gui()
check(E.ev(f'FILES["{M.FILE_BUILTBY}"] ~= nil'), "the registry's file written for the windows")
E.run(f'IDX = M.builtByIndex(FILES["{M.FILE_BUILTBY}"])')
check(E.ev(f'M.builtByText(IDX, M.keyOfSg("c:{STATION}@100,200#1"), T_en)') == "Built by Alice, changed by Bob",
      "a station's window (its R.sgKey): built by Alice, changed by Bob")
check(E.ev(f'M.builtByText(IDX, M.conKey("::/{STATION}", 101.2, 199), T_fr)') == "Construit par Alice, modifié par Bob",
      "the construction's key (with ::/ and a metre away), in French")
check(E.ev(f'M.builtByText(IDX, M.conKey("{DEPOT}", 50, 50), T_en)') == "Changed by Bob",
      "a construction from before the option: « changed by » only")
check(E.ev(f'M.builtByText(IDX, M.conKey("{STATION}", 900, 900), T_en)') == "Built by Carl", "built by Carl")
check(E.ev(f'M.builtByText(IDX, M.conKey("{STATION}", 905, 900), T_en)') is None, "5 m away: another construction")
check(E.ev('M.creatorText("VBob#1:3@7000", T_en)') == "Bought by Bob" and E.ev('M.creatorText("LAlice:2@100", T_fr)') == "Créée par Alice",
      "vehicles and lines: from their creation keys")
# a computer company's build that takes a construction away (separate mode): out of the registry, not in the journal
E.run('COMPANIES = { { id = 1, members = { { key = "alice" } } }, { id = 4, ai = true, members = { { key = "ai:1" } } } }')
E.action(f'build("Alice", 5, 5000, nil, {{ conRef("{STATION}", 900, 900) }}, nil, {{ co = 4 }})')
check(E.ev(f'M.regGet(J(), M.conKey("{STATION}", 900, 900))') is None and E.ev("J().nlog") == 0,
      "a computer company's demolition: out of the registry, nothing in the journal")
# the registry's cap
F = Game("Alice", opts=OPT_B)
F.run("M.MAX_REG = 50")
for i in range(60):
    F.action(f'build("Alice", {i + 1}, {1000 + i}, {{ {{ "{STATION}", {i * 100}, 0 }} }})')
check(F.ev("J().nreg") == 50 and F.ev(f'M.regGet(J(), M.conKey("{STATION}", 0, 0))') is None
      and F.ev(f'M.regGet(J(), M.conKey("{STATION}", 5900, 0))') is not None, "the registry keeps its 50 latest (cap)")
# the journal's cap
G = Game("Alice", opts=OPT_J)
for i in range(350):
    G.action(f'build("Alice", {i + 1}, {1000 + i * 40000}, {{ {{ "{STATION}", {i}, 0 }} }})')
check(G.ev("J().nlog") == 300 and G.ev("J().seq") == 350 and G.ev("M.entries(J())[1].x") == 50, "the journal keeps its 300 latest entries")

# ---------------------------------------------------------------------------------------------------------- savegame
print("savegame")
for name, g_ in (("journal", A), ("built by", E), ("cap", G)):
    try:
        s = g_.ev("ser(ST.feat)")
        okp = True
    except Exception as ex:   # noqa: BLE001
        s, okp = str(ex), False
    check(okp, f"the {name} state is plain data (no function, userdata or cycle)")
saved = A.state()
A2 = Game("Alice", host=True, opts=OPT_J)
A2.run(f"ST.feat = deser([==[{saved}]==])")
A2.request("share", "1")   # (a click in the window before the first look: the load's entries are still not told)
A2.gui()
check(A2.ev("#CHAT") == 0, "after a load: the demolition already in the journal is not told again")
check(A2.ev(f'FILES["{M.FILE}"] ~= nil') and A2.state() == saved, "after a load: the tab's file written again, the state unchanged")
A2.action('act("Bob#1", 30, 30000, "makeVehicleSellCmd", { n = 1, [1] = 5 })')
A.action('act("Bob#1", 30, 30000, "makeVehicleSellCmd", { n = 1, [1] = 5 })')
check(A2.state() == A.state(), "the loaded game goes on as the one that saved")

# ---------------------------------------------------------------------------------------------------------- the view
print("the view: shared mode")
OPT_V = {"playerview": True}
VA = Game("Alice", host=True, opts=OPT_V)
VB = Game("Bob#1", opts=OPT_V)
VC = Game("Carl#2", opts=OPT_V)
V = [VA, VB, VC]
for g_ in V:
    g_.action('act("Alice", 1, 1000, "makeVehicleSellCmd", { n = 1, [1] = 5 })')
    g_.action('act("Bob#1", 1, 1000, "makeVehicleSellCmd", { n = 1, [1] = 5 })')
    g_.action('act("Carl#2", 1, 1000, "makeVehicleSellCmd", { n = 1, [1] = 5 })')
    g_.gui()
VB.request("view", "alice")
ev = lockstep(V, V)
check([e[1] for e in ev] == ["f_journal_camreq"] and VA.ev("#J().cam") == 1, "Bob asks for Alice's view: one request on every game")
for g_ in V:
    g_.gui()
ev = lockstep(V, V)
check([(e[0], e[1]) for e in ev] == [("Alice", "f_journal_cam")], "Alice's game alone answers, with its camera")
for g_ in V:
    g_.gui()
check(VB.ev("#CAMSET") == 1 and VB.ev("CAMSET[1][1]") == 1200.5 and VB.ev("CAMSET[1][3]") == 650, "Bob's camera takes Alice's view")
check(VA.ev("#CAMSET") == 0 and VC.ev("#CAMSET") == 0, "no other camera moves")
check(VB.ev(f'FILES["{M.FILE}"][#FILES["{M.FILE}"]]') == "@status\tview\tAlice", "Bob's tab: « Alice's view »")
check(VA.state() == VB.state() == VC.state(), "the three games: the same state")
# Alice keeps her view to herself
VA.request("share", "0")
lockstep(V, V)
check(VB.ev("J().noview.alice") is True, "Alice's refusal kept in the state (G4)")
VB.request("view", "alice")
check(VB.ev("#SENT") == 0, "Bob's game does not ask (its tab shows the refusal)")
VB.run('SENT[1] = { name = "f_journal_camreq", param = { to = "alice", from = "Bob#1" } }')   # (a request sent before the refusal arrived)
lockstep(V, V)
for g_ in V:
    g_.gui()
check(VA.ev("#SENT") == 0 and VB.ev("#CAMSET") == 1, "the request is answered « no » at once, Alice's game sends nothing")
check(VB.ev(f'FILES["{M.FILE}"][#FILES["{M.FILE}"]]') == "@status\tnoshare\tAlice", "Bob's tab: « Alice does not share their view »")
VA.request("share", "1")
lockstep(V, V)
check(VB.ev("J().noview.alice") is None, "Alice shares her view again")
# nobody answers: the host's game alone ends the request
VB.request("view", "dave")
lockstep(V, V)
for t in (0, 5):
    for g_ in V:
        g_.run(f"RT = {t}")
        g_.gui()
check(sum(int(g_.ev("#SENT")) for g_ in V) == 0, "within 8 s: nothing")
for g_ in (VB, VC):
    g_.run("RT = 100")
    g_.gui()
check(VB.ev("#SENT") == 0 and VC.ev("#SENT") == 0, "the other games never end a request (not the host)")
VA.run("RT = 9")
VA.gui()
ev = lockstep(V, V)
check([(e[0], e[1]) for e in ev] == [("Alice", "f_journal_camend")], "the host's game ends it after 8 s")
for g_ in V:
    g_.gui()
check(VB.ev(f'FILES["{M.FILE}"][#FILES["{M.FILE}"]]') == "@status\ttimeout\tdave", "Bob's tab: « dave does not answer »")
check(VA.state() == VB.state() == VC.state(), "the same state after the time-out")
VB.run("RT = 131")
VB.gui()
check(not any(str(VB.ev(f'FILES["{M.FILE}"][{i}]')).startswith("@status") for i in range(1, int(VB.ev(f'#FILES["{M.FILE}"]')) + 1)),
      "the tab's status line goes after 30 s")
# a load does not take an answer again
saved = VB.state()
VB2 = Game("Bob#1", opts=OPT_V)
VB2.run(f"ST.feat = deser([==[{saved}]==])")
VB2.gui()
check(VB2.ev("#CAMSET") == 0 and VB2.ev("#SENT") == 0, "after a load: no old answer taken again, nothing sent")
# what is never asked
VB.request("view", "bob")
VB.request("view", "ai:1")
check(VB.ev("#SENT") == 0, "no request for oneself or a computer company")
# the sender read from the event when the options host gives none (env.from nil)
VC.request("view", "alice")
lockstep(V, V, with_from=False)
check(VA.ev("J().cam[1].from") == "carl" and VA.state() == VC.state(), "the sender from the event itself when env.from is nil")

print("the view: separate mode")
COMP = ('{ { id = 1, members = { { key = "alice" } } }, { id = 2, members = { { key = "bob" }, { key = "dave" } } }, '
        '{ id = 3, gone = "bankrupt", members = { { key = "carl" } } }, { id = 4, key = "ai:1", ai = true, members = { { key = "ai:1" } } } }')
SA = Game("Alice", host=True, opts={"playerview": True, "journal": True}, mode="separate", companies=COMP, myco=1)
SB = Game("Bob#1", opts={"playerview": True, "journal": True}, mode="separate", companies=COMP, myco=2)
S = [SA, SB]
for g_ in S:
    g_.action('act("Bob#1", 1, 1000, "makeVehicleSellCmd", { n = 1, [1] = 5 }, { co = 2 })')
    g_.action('act("Dave#3", 1, 1000, "makeVehicleSellCmd", { n = 1, [1] = 5 }, { co = 2 })')
    g_.action(f'build("Alice", 1, 1100, {{ {{ "{STATION}", 1, 1 }} }}, nil, nil, {{ co = 1 }})')
    g_.action('act("Alice", 2, 1200, "makeVehicleBuyCmd", { n = 3, [1] = 0, [2] = depotRef(1, 1), [3] = busCfg(7) }, { co = 4 })')
    g_.gui()
check(SB.ev("kinds()") == "sell,sell,station", "the journal shows the rivals too (G2), not the computer company")
fileB = [SB.ev(f'FILES["{M.FILE}"][{i}]') for i in range(1, 9)]
check("@peer\tdave\tDave\tok" in fileB and not any(l and l.startswith("@peer\talice") for l in fileB),
      "Bob's view list: Dave (his company) only")
SB.request("view", "alice")
check(SB.ev("#SENT") == 0 and SB.ev("M._g.status[1]") == "company", "Alice's view: refused on Bob's game (another company)")
SB.request("view", "carl")
check(SB.ev("#SENT") == 0, "a member of a bankrupt company: refused")
SB.request("view", "dave")
check(SB.ev("#SENT") == 1, "Dave's view: asked (one company)")
SB.run('SENT[2] = { name = "f_journal_camreq", param = { to = "alice", from = "Bob#1" } }')
lockstep(S, S)
check(SA.ev("#J().cam") == 1 and SA.ev("J().cam[1].to") == "dave" and SA.ev("J().ans[1].no") == "company",
      "every game: Dave asked, Alice refused (another company) whatever a game sent")
check(SA.state() == SB.state(), "the same state on both games")
check(SA.ev("#BOOK") == 0 and SB.ev("#BOOK") == 0 and A.ev("#BOOK") == 0 and E.ev("#BOOK") == 0, "no money moved anywhere")

# ---------------------------------------------------------------------------------------------------------- the window
print("the window's tab")
UI = '''
UIW = {}
U = { T = T_en, read = function(f) return FILES[f] or {} end, request = function(k, p) REQ[#REQ + 1] = k .. "=" .. p end,
  text = function(s) return { t = "text", s = s } end, muted = function(s) return { t = "muted", s = s } end,
  button = function(s, fn) local b = { t = "button", s = s, fn = fn }; UIW[s] = b; return b end,
  row = function(l) return { t = "row", l = l } end }
REQ = {}
function texts(rows)
  local out = {}
  local function walk(w) if w.t == "row" then for _, x in ipairs(w.l) do walk(x) end else out[#out + 1] = w.s end end
  for _, w in ipairs(rows) do walk(w) end
  return table.concat(out, "|")
end
'''
B.run(UI)
B.run("ROWS = M.ui(U)")
t1 = B.ev("texts(ROWS)")
check(t1.startswith("What the players do, the latest first.") and "Details: hidden" in t1 and "Player: all" in t1, "intro, details and player switches")
check("Alice placed 2 tree(s) or rock(s)" not in t1 and "Alice demolished 100 m of track" in t1, "details hidden by default")
check(t1.index("Alice demolished 100 m of track") < t1.index("Alice built the station"), "the latest first")
B.run('UIW["Details: hidden"].fn(); ROWS = M.ui(U)')
check("Alice placed 2 tree(s) or rock(s)" in B.ev("texts(ROWS)"), "details shown after the switch")
B.run('UIW["Player: all"].fn(); ROWS = M.ui(U)')
t3 = B.ev("texts(ROWS)")
check("Player: Alice" in t3 and "Bob demolished" not in t3 and "Alice built the station" in t3, "only Alice's entries")
B.run('UIW["Show"].fn()')
check(B.ev("#FOCUS") == 1 and B.ev("FOCUS[1].x") is not None, "Show takes the camera to the entry")
VB.run(UI)
VB.run('ROWS = M.ui(U)')
t4 = VB.ev("texts(ROWS)")
check("See a player's view" in t4 and "Alice" in t4 and "Carl" in t4 and "The others may see my view: yes" in t4, "the view's part: players, my switch")
VB.run('UIW["See their view"].fn(); UIW["The others may see my view: yes"].fn()')
check(VB.ev("REQ[1]") == "view=carl" and VB.ev("REQ[2]") == "share=0", "its buttons ask the game (view, share)")
H = Game("Alice", host=True, opts={"journal": True, "journal.details": 1})
H.action('act("Alice", 1, 1000, "terrainEdit", {})')
H.gui()
H.run(UI)
check("Alice changed the terrain (×1)" in H.ev("texts(M.ui(U))") and "Details: shown" in H.ev("texts(M.ui(U))"),
      "the option's parameter: details shown by default")

if failures:
    print(f"FAIL {len(failures)} case(s): " + "; ".join(failures))
    sys.exit(1)
print("all cases passed")
sys.exit(0)
