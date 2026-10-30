"""The 0.6 game options host (mpfever_feat.lua) and its hooks in the bridge and the MPFever window, offline (lupa, Lua 5.2).

A test module (not shipped: given to the host by its loader here) declares three options (one per company mode), parameters,
an event, and every hook of the contract (docs/FEATURES-0.6.md); a second one fails in its tick. Checked:
  - the options string: parsing, encoding (keys sorted), the canon (declared options only, on, in the mode, parameters only of an
    option on and only when not their default), defaults off, typed parameters;
  - f_opts: the host's applied by every game (st.optsText, st.opts, st.optsCfg "mpfopts:...;"), another player's refused;
  - dispatch: a module's event while its options are on (ignored while off, or unknown), tick, month, onAction, f_act,
    onGameEvent, gui (once a second, its events and files), request, allow; a failing hook is caught and its log rate-limited;
  - nothing called while no option is on;
  - the bridge's G.featGui (the host sends f_opts when the game's differ, at most every 600 frames, never during a
    resynchronisation, never from a player; nothing at all while none is on or asked), G.featRefuse (a refusal: the chat says
    why, the window's command gets a refused result; a failing module lets it through) and SIM.featNative (only the builds
    every game hears: a replay, or this game's own build shipped);
  - the window: a module's tab while its option is on (its rows, u.read, u.request), the Game tab's section for the host
    (On / Off, parameters, the request to MPFever.exe) and for the players (the options on).
Run: python tests/test_feat_host.py
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
CONTENT = os.path.join(HERE, "..", "mod", "mpfever_1", "content")


def read(name):
    with open(os.path.join(CONTENT, name), encoding="utf-8") as f:
        return f.read()


def extract(src, pattern, what):
    m = re.search(pattern, src, re.S | re.M)
    if not m:
        print(f"FAIL: {what} not found")
        sys.exit(1)
    return m.group(0)


L = lua52.LuaRuntime(unpack_returned_tuples=True)
L.execute(r'''
RESULTS = {}
function check(name, cond, got)
  RESULTS[#RESULTS + 1] = { name = name, ok = cond and true or false, got = tostring(got) }
end
LOGS = {}
function log(s) LOGS[#LOGS + 1] = tostring(s) end
function countLogs(pat) local n = 0 for _, l in ipairs(LOGS) do if l:find(pat, 1, true) then n = n + 1 end end return n end
CALLS = {}
function called(pat) for _, c in ipairs(CALLS) do if c:find(pat, 1, true) then return true end end return false end
function T(fr, en) return en end

-- the test module (not shipped): every hook of the contract
TESTMOD = [==[
local M = {}
M.ID = "stats"
M.OPTIONS = {
  { id = "goal", title = { "Objectif", "Game goal" }, desc = { "Une description.", "A description." }, modes = "separate",
    params = {
      { id = "years", label = { "Durée", "Length" }, values = { 10, 20, 30 }, default = 20,
        show = function(v, T) return T("%s ans", "%s years"):gsub("%%s", v) end },
      { id = "kind", label = { "Valeur", "Value" }, values = { "value", "money" } },
    } },
  { id = "summary", title = { "Bilan annuel", "Yearly summary" }, modes = "both" },
  { id = "coop", title = { "Coop", "Co-op" }, modes = "shared" },
}
M.EVENTS = { f_stats_cancel = true, f_other_x = true }
function M.event(st, name, param, env) CALLS[#CALLS + 1] = "event " .. name; local s = env.state(); s.n = (s.n or 0) + 1 end
function M.tick(st, env) CALLS[#CALLS + 1] = "tick"; return env.every(5) end
function M.month(st, env) CALLS[#CALLS + 1] = "month " .. tostring(env.month()) end
function M.onAction(st, a, ok, env) CALLS[#CALLS + 1] = "action " .. tostring(a.fn) .. " " .. tostring(ok) end
function M.onGameEvent(st, id, name, param, env, src) CALLS[#CALLS + 1] = "game " .. tostring(id) .. " " .. tostring(name); return true end
function M.gui(st, env)
  CALLS[#CALLS + 1] = "gui " .. tostring(env.isHost)
  if env.isHost then env.send("f_stats_cancel", { x = 1 }); env.send("f_journal_x", {}) end
  env.write("board", { "first", "second" })
end
function M.request(kind, payload, st, env) CALLS[#CALLS + 1] = "request " .. tostring(kind) end
function M.allow(a, st, env) if a.fn == "makeVehicleBuyCmd" then return false, "No buying here." end return true end
M.TAB = { id = "stats", title = { "Classement", "Ranking" } }
function M.ui(u)
  u.add(u.text("hello " .. tostring(u.param("goal", "years"))))
  for _, l in ipairs(u.read("board")) do u.add(u.muted(l)) end
  u.add(u.table({ { "a", "b" }, { "1", "2" } }, nil, true))
  u.request("refresh", { n = 1 })
  return { u.button("Go", function() CALLS[#CALLS + 1] = "clicked" end, true) }
end
return M
]==]
-- a second module whose tick fails, and whose allow fails
BADMOD = [==[
local M = { ID = "journal", OPTIONS = { { id = "journal", title = { "Journal", "Journal" } } } }
function M.tick(st, env) error("boom") end
function M.allow(a, st, env) error("allow boom") end
return M
]==]
''')

F = L.execute(read("mpfever_feat.lua"))
L.globals().F = F
L.execute(r'''
F.loader = function(id)
  if id == "stats" then return load(TESTMOD, "=stats")() end
  if id == "journal" then return load(BADMOD, "=journal")() end
  return nil   -- the other modules of the list do not exist yet: skipped
end
F.load(log)

-- the bridge's helpers, as SIM.featBridge / G.featBridge give them
NOW, MONTH, SENT, CHAT, FILES, BOOKED = 0, 100, {}, {}, {}, {}
B = { log = log, STEP = 200, gameTime = function() return NOW end, month = function() return MONTH end, date = function() return nil end,
  money = function() return 0 end, book = function(ent, amount) BOOKED[#BOOKED + 1] = amount return true end,
  companies = function() return {} end, isHost = true, me = "host", myCo = 1, mode = "separate",
  send = function(name, param) SENT[#SENT + 1] = name return true end, chat = function(t) CHAT[#CHAT + 1] = t return true end,
  write = function(file, text) FILES[file] = text return true end }

-- ---- the list
check("modules: the two that exist loaded, the others skipped", #F.mods == 2 and F.byId.stats ~= nil and F.byId.journal ~= nil, #F.mods)
check("events: a wrongly named one left out", F.eventOwner.f_stats_cancel == F.byId.stats and F.eventOwner.f_other_x == nil)

-- ---- the string
local p = F.parse("goal=1;goal.years=30;BAD=1;x=;y.z.w=1;q=A;ok_1=1")
check("parse: valid entries only", p.goal == "1" and p["goal.years"] == "30" and p.BAD == nil and p.x == nil and p["y.z.w"] == nil and p.q == nil, F.encode(p))
check("encode: keys sorted", F.encode({ b = "1", a = "1", ["a.x"] = "2" }) == "a=1;a.x=2;b=1", F.encode({ b = "1", a = "1", ["a.x"] = "2" }))
check("parse: too long", next(F.parse(string.rep("a", F.MAX_TEXT + 1) .. "=1")) == nil)
local c = F.canon("summary=1;goal.kind=value;goal=1;goal.years=30;coop=1;zzz=1;goal.bogus=3", "separate")
check("canon: declared, on, in the mode, parameters not default", c == "goal=1;goal.years=30;summary=1", c)
c = F.canon("summary=1;goal=1;goal.years=30;coop=1", "shared")
check("canon: the co-op's", c == "coop=1;summary=1", c)
check("canon: no parameter of an option off", F.canon("goal.years=30;summary=1", "separate") == "summary=1")
check("canon: a value not declared dropped", F.canon("goal=1;goal.years=25", "separate") == "goal=1")
check("canon: the default dropped", F.canon("goal=1;goal.years=20", "separate") == "goal=1")
check("canon: any mode", F.canon("goal=1;coop=1") == "coop=1;goal=1")

-- ---- defaults
check("defaults: off", not F.on({}, "goal") and not F.on(F.parse(""), "summary"))
check("defaults: a parameter's default, typed", F.param({}, "goal", "years") == 20 and F.param({}, "goal", "kind") == "value")
check("parameter: typed as declared", F.param(F.parse("goal=1;goal.years=30"), "goal", "years") == 30)
check("parameter: unknown value -> default", F.param(F.parse("goal=1;goal.years=31"), "goal", "years") == 20)
local off = F.offered("shared")
check("offered: the co-op's options, in the list's order", #off == 3 and off[1].opt.id == "journal" and off[2].opt.id == "summary" and off[3].opt.id == "coop", #off)
local sum = F.summary(F.parse("goal=1;goal.years=30"), "separate", T)
check("summary: titles and parameters shown", #sum == 1 and sum[1].title == "Game goal" and sum[1].params[1] == "Length: 30 years" and sum[1].params[2] == "Value: value", sum[1] and sum[1].params[1])

-- ---- nothing while all off
CALLS = {}
local st0 = {}
check("all off: no module active", #F.active(nil) == 0 and #F.active("") == 0)
check("all off: tick calls nothing", F.simTick(st0, B) == false and #CALLS == 0 and st0.featMonth == nil, #CALLS)
check("all off: onAction calls nothing", F.simAction(st0, { fn = "x" }, true, B) == false and #CALLS == 0)
check("all off: no game event heard", not F.hearsGameEvents("") and not F.wantsAllow(""))
F.gui(st0, B, 100)
check("all off: gui calls nothing", #CALLS == 0 and next(FILES) == nil)
check("all off: no tab", #F.tabs({}) == 0)

-- ---- f_opts
st = {}   -- (global: the bridge's and the window's checks below use it)
F.simEvent(st, "f_opts", { s = "goal=1;coop=1;goal.years=30", mode = "separate", mpfFrom = "bob#2" }, B)
check("f_opts: a player's refused", st.optsText == nil and countLogs("refused: not the host") == 1)
F.simEvent(st, "f_opts", { s = "goal=1;coop=1;goal.years=30", mode = "separate", mpfFrom = "host" }, B)
check("f_opts: the host's applied", st.optsText == "goal=1;goal.years=30" and st.opts.goal == "1" and st.optsMode == "separate"
  and st.optsCfg == "mpfopts:goal=1;goal.years=30;", st.optsCfg)

-- ---- dispatch
CALLS = {}
F.simEvent(st, "f_stats_cancel", { mpfFrom = "bob#2" }, B)
check("event: to its module, its state created", called("event f_stats_cancel") and st.feat.stats.n == 1)
F.simEvent(st, "f_nobody_x", {}, B)
check("event: unknown ignored", countLogs("has no module here") == 1)
CALLS = {}
NOW, MONTH = 1000, 100
local ch = F.simTick(st, B)
check("tick: called, first month noted (not counted)", called("tick") and not called("month") and st.featMonth == 100 and ch == true)
MONTH = 101
CALLS = {}
F.simTick(st, B)
check("month: at a new game month", called("month 101") and st.featMonth == 101)
CALLS = {}
F.simAction(st, { fn = "makeVehicleBuyCmd" }, true, B)
F.simEvent(st, "f_act", { a = { fn = "makeLineCreateCmd", paused = true }, ok = false }, B)
check("onAction: an action and an f_act note", called("action makeVehicleBuyCmd true") and called("action makeLineCreateCmd false"))
check("onGameEvent: heard, state changed", F.hearsGameEvents(st.optsText) and F.simGameEvent(st, "Subvention", "onAccept", {}, B, "src") == true and called("game Subvention onAccept"))

-- ---- a failing module, and every hook protected
st2 = {}
F.simEvent(st2, "f_opts", { s = "journal=1;summary=1", mode = "shared", mpfFrom = "host" }, B)
LOGS = {}
for i = 1, 20 do F.simTick(st2, B) end
check("protection: a failing tick caught, logged 5 times of 20", countLogs("journal.tick failed") == 5, countLogs("journal.tick failed"))
check("protection: the other module still ticks", called("tick"))
CALLS = {}
F.simEvent(st2, "f_stats_cancel", {}, B)
check("event: still dispatched in the co-op", called("event f_stats_cancel"))
F.simEvent(st2, "f_opts", { s = "journal=1", mode = "shared", mpfFrom = "host" }, B)
CALLS = {}
F.simEvent(st2, "f_stats_cancel", {}, B)
check("event: ignored while its module's options are off", not called("event") and countLogs("are off") >= 1)

-- ---- interface half
CALLS, SENT, FILES = {}, {}, {}
F.gui(st, B, 110)
F.gui(st, B, 110.5)
F.gui(st, B, 111.2)
local n = 0 for _, c in ipairs(CALLS) do if c == "gui true" then n = n + 1 end end
check("gui: about once a second", n == 2, n)
check("gui: its own event sent, another module's refused", #SENT == 2 and SENT[1] == "f_stats_cancel" and countLogs("not one of this module's EVENTS") >= 1, #SENT)
check("gui: its file", FILES["feat_stats_board.txt"] == "first\nsecond")
CALLS = {}
check("request: to its module", F.request("stats", "refresh", {}, st, B) == true and called("request refresh"))
check("request: none to a module off", F.request("journal", "x", {}, st, B) == false)
local ok1, why1, m1 = F.allow({ fn = "makeVehicleBuyCmd" }, st, B)
local ok2 = F.allow({ fn = "makeLineCreateCmd" }, st, B)
check("allow: refused with its reason", ok1 == false and why1 == "No buying here." and m1 == F.byId.stats and ok2 == true)
check("allow: a failing module lets it through", F.allow({ fn = "x" }, st2, B) == true and F.wantsAllow(st2.optsText))
local tabs = F.tabs(st.opts)
check("tabs: the module's while its option is on", #tabs == 1 and tabs[1].key == "f_stats" and #F.tabs(F.parse("journal=1")) == 0)
''')

# ---------------------------------------------------------------- the bridge's hooks (the real functions)
bridge = read("mpfever_bridge.script.lua")
gui_src = extract(bridge, r"^G\.featGui = function\(st\)\n.*?^end\n", "G.featGui")
refuse_src = extract(bridge, r"^G\.featRefuse = function\(p\)\n.*?^end\n", "G.featRefuse")
native_src = extract(bridge, r"^SIM\.featNative = function\(state, param, seq0\)\n.*?^end\n", "SIM.featNative")
L.execute(r'''
FEATCALLS = 0
G = { frames = 1000, session = { started = true, resync = false }, connected = true, cmode = "separate" }
C = { ROLE = "host", T = function(fr, en) return en end, DIR = "D", line = function(kind, r) return kind .. " " .. tostring(r.success) .. " " .. tostring(r.err) end }
C.feat = function() FEATCALLS = FEATCALLS + 1 return F end
APPENDED = {}
C.appendFile = function(path, text) APPENDED[#APPENDED + 1] = path .. "|" .. text return true end
BS = "/"
EVENTS = {}
G.coEvent = function(name, param) EVENTS[#EVENTS + 1] = { name = name, s = param.s, mode = param.mode } end
G.featBridge = function() return B end
G.featChat = function(t) CHAT[#CHAT + 1] = t return true end
SIM = { featBridge = function() return B end }
function gameTime() return NOW end
''')
L.execute(gui_src)
L.execute(refuse_src)
L.execute(native_src)
L.execute(r'''
-- G.featGui: nothing at all while none is on or asked
FEATCALLS, EVENTS = 0, {}
G.featOpts = nil
G.featGui({})
G.featOpts = ""
G.featGui({ optsText = "" })
check("bridge: nothing while none is on or asked (the host not even loaded)", FEATCALLS == 0 and #EVENTS == 0 and G.featOn == false)
-- the host's game sends the session's options when the game's differ, at most every 600 frames
G.featOpts = "goal=1;coop=1;goal.years=30"
G.featGui({})
check("bridge: f_opts sent by the host", #EVENTS == 1 and EVENTS[1].name == "f_opts" and EVENTS[1].s == "goal=1;goal.years=30" and EVENTS[1].mode == "separate", EVENTS[1] and EVENTS[1].s)
G.frames = 1300
G.featGui({})
check("bridge: not again within 600 frames", #EVENTS == 1)
G.frames = 1700
G.featGui({})
check("bridge: again after 600 frames while they still differ", #EVENTS == 2)
G.frames = 3000
G.featGui({ optsText = "goal=1;goal.years=30", opts = F.parse("goal=1;goal.years=30") })
check("bridge: not sent once the game has them", #EVENTS == 2 and G.featOn == true and G.featAllow == true)
G.session.resync = true
G.frames = 5000
G.featGui({ optsText = "" })
check("bridge: never during a resynchronisation", #EVENTS == 2)
G.session.resync = false
C.ROLE = "client"
G.frames = 7000
G.featGui({ optsText = "" })
check("bridge: never from a player's game", #EVENTS == 2)
C.ROLE = "host"
G.featOpts = ""
G.frames = 9000
G.featGui({ optsText = "goal=1", opts = F.parse("goal=1") })
check("bridge: all switched off -> f_opts with nothing", #EVENTS == 3 and EVENTS[3].s == "")
-- (the same options, a savegame played in the other company mode: sent again with this lobby's mode)
G.featOpts = "goal=1"
G.frames = 11000
G.featGui({ optsText = "goal=1", opts = F.parse("goal=1"), optsMode = "shared" })
check("bridge: the same options in another company mode -> f_opts again", #EVENTS == 4 and EVENTS[4].s == "goal=1" and EVENTS[4].mode == "separate")
G.frames = 13000
G.featGui({ optsText = "goal=1", opts = F.parse("goal=1"), optsMode = "separate" })
check("bridge: not again once the mode is the game's", #EVENTS == 4)

-- G.featRefuse
G.featSt = st
G.me, G.myCo = "bob#2", 2
CHAT, APPENDED = {}, {}
local r1 = G.featRefuse({ fn = "makeVehicleBuyCmd", tok = "tk", id = 7 })
check("bridge: refused, the chat says why, the window gets a refusal", r1 == true and CHAT[1] == "No buying here."
  and #APPENDED == 1 and APPENDED[1]:find("^D/results.log|result false game option: No buying here.") ~= nil, APPENDED[1])
CHAT, APPENDED = {}, {}
check("bridge: allowed, nothing said", G.featRefuse({ fn = "makeLineCreateCmd", tok = "tk", id = 8 }) == false and #CHAT == 0 and #APPENDED == 0)
check("bridge: a native build checked too (no result line)", G.featRefuse({ fn = "makeVehicleBuyCmd", native = true, natId = 3 }) == true and #APPENDED == 0)
G.featSt = st2
check("bridge: a failing module lets it through", G.featRefuse({ fn = "makeVehicleBuyCmd", tok = "tk", id = 9 }) == false)
local allowFn = F.allow
F.allow = nil   -- (a broken options host: G.featRefuse never throws into the stamping)
check("bridge: an error inside lets it through", G.featRefuse({ fn = "x" }) == false and countLogs("allow failed") >= 1)
F.allow = allowFn
''')
L.execute(r'''
-- SIM.featNative: only what every game hears (a replay here, or this game's build shipped)
local function state(t) return { get = function() return t end, set = function() SETS = (SETS or 0) + 1 end } end
local stN = { optsText = st.optsText, opts = st.opts, outSeq = 4 }
NOW = 5000
CALLS = {}
SIM.replayBuildAt = nil
SIM.featNative(state(stN), { "proposal", "data" }, 4)
check("native: not shipped, not a replay -> not heard", not called("action"))
SIM.replayBuildAt = 5000
SIM.featNative(state(stN), { "proposal", "data" }, 4)
check("native: a replay heard", called("action nativeBuild true"))
CALLS = {}
SIM.replayBuildAt = nil
stN.outSeq = 5
SIM.featNative(state(stN), { "proposal", "data" }, 4)
check("native: this game's build, shipped, heard", called("action nativeBuild true"))
CALLS = {}
stN.solo = true
SIM.featNative(state(stN), { "proposal", "data" }, 4)
check("native: nothing without a lobby", not called("action"))
''')

# ---------------------------------------------------------------- the window (the real functions)
ui = read("mpfever_ui.script.lua")
win_src = extract(ui, r"^U\.featOff = .*?^U\.featTabRows = function\(K, st, key\)\n.*?^end\n", "the window's game options")
L.execute(r'''
U = { isHost = function(st) return st and st.host == true end, winChanged = function() end }
REQS, LINES = {}, {}
U.menuRequest = function(cmd, arg) REQS[#REQS + 1] = cmd .. " " .. tostring(arg) return true end
function sendLine(kind, p) LINES[#LINES + 1] = kind .. " " .. tostring(p.m) .. " " .. tostring(p.kind) end
function money(n) return tostring(n) end
FILEDATA = { ["D/feat_stats_board.txt"] = "first\r\nsecond\n" }
C = { feat = function() return F end, DIR = "D", BS = "/", NL = "\n", CR = "\r", Tf = function(fr, en) return en end,
  IO = { open = function(path) local s = FILEDATA[path] if not s then return nil end
    return { read = function() return s end, close = function() end } end } }
os.getenv = function() return nil end
api = { cmd = { sendCommand = function() end, makeScriptingSendEventCmd = function() return {} end } }
-- the window's drawing kit, as nodes that say what they are
K = { TEXT_W = 556, ICON_SETTINGS = "i" }
function K.text(t, class, cls, w) return { kind = "text", t = tostring(t), class = class } end
function K.muted(t, w) return { kind = "muted", t = tostring(t) } end
function K.section(icon, t) return { kind = "section", t = t } end
function K.gap() return { kind = "gap" } end
function K.row(c) return { kind = "row", c = c } end
function K.col(c) return { kind = "col", c = c } end
function K.btn(label, tip, fn, primary, enabled) return { kind = "btn", t = label, fn = fn, primary = primary } end
''')
L.execute(win_src)
L.execute(r'''
local stS = { mode = "separate", opts = "goal=1;goal.years=30", host = true }
local tabs = U.featTabs(stS)
check("window: the module's tab while its option is on", #tabs == 1 and tabs[1].key == "f_stats")
check("window: no tab while off", #U.featTabs({ mode = "separate", opts = "" }) == 0)
check("window: a separate-only option is off in the co-op", #U.featTabs({ mode = "shared", opts = "goal=1" }) == 0)
LINES, CALLS = {}, {}
local rows = U.featTabRows(K, stS, "f_stats")
check("window: the tab's rows (u.add, u.read, u.table, returned ones)", #rows == 5 and rows[1].t == "hello 30" and rows[2].t == "first" and rows[3].t == "second"
  and rows[4].kind == "col" and rows[5].kind == "btn", #rows)
check("window: u.request to the bridge", LINES[1] == "feat_req stats refresh")
rows[5].fn()
check("window: a button's function runs", called("clicked"))
check("window: a tab not on any more", U.featTabRows(K, { mode = "separate", opts = "" }, "f_stats")[1].kind == "muted")
-- the Game tab's section, the host
local g = {}
U.featGameRows(K, { mode = "shared", opts = "summary=1", host = true }, g)
local texts, onBtn, offBtn, after = {}, nil, nil, nil
for _, r in ipairs(g) do
  if r.kind == "text" then texts[#texts + 1] = r.t; after = r.t end
  if r.kind == "row" and r.c[1] and r.c[1].kind == "btn" and r.c[1].t == "On" and after == "Yearly summary" then onBtn = r.c[1]; offBtn = r.c[3] end
end
check("window, host: every option of the mode", #texts == 3 and texts[1] == "Journal" and texts[2] == "Yearly summary" and texts[3] == "Co-op", table.concat(texts, ","))
check("window, host: On / Off of the first one shows it on", onBtn ~= nil and onBtn.primary == true and offBtn.primary == false)
REQS = {}
offBtn.fn()
check("window, host: switched off through MPFever.exe", REQS[1] == "opt summary=0", REQS[1])
local g2 = {}
U.featGameRows(K, { mode = "shared", opts = "summary=1", host = true }, g2)
local still, after2 = false, nil
for _, r in ipairs(g2) do
  if r.kind == "text" then after2 = r.t end
  if r.kind == "row" and r.c[1] and r.c[1].t == "On" and r.c[1].primary and after2 == "Yearly summary" then still = true end
end
check("window, host: the choice shows at once (asked)", not still)
local g3 = {}
U.featGameRows(K, { mode = "separate", opts = "goal=1", host = true }, g3)
local yearsRow = nil
for _, r in ipairs(g3) do if r.kind == "row" and r.c[1] and r.c[1].t == "10 years" then yearsRow = r end end
check("window, host: the parameters of an option on", yearsRow ~= nil and yearsRow.c[3].primary == true)
REQS = {}
yearsRow.c[5].fn()
check("window, host: a parameter asked", REQS[1] == "opt goal.years=30", REQS[1])
-- the players
local g4 = {}
U.featGameRows(K, { mode = "separate", opts = "goal=1;goal.years=30" }, g4)
local t4 = {}
for _, r in ipairs(g4) do if r.kind == "text" or r.kind == "muted" then t4[#t4 + 1] = r.t end end
check("window, player: the options on and their parameters", t4[1] == "Game goal" and t4[2] == "   Length: 30 years", table.concat(t4, "|"))
U.featAsked = nil
check("window: the co-op's Game tab for the host only while nothing is on", U.featGameTab({ mode = "shared", opts = "", host = true }) == true
  and U.featGameTab({ mode = "shared", opts = "" }) == false and U.featGameTab({ mode = "shared", opts = "summary=1" }) == true)
''')

failed = 0
for r in L.globals().RESULTS.values():
    print(f"{'ok  ' if r.ok else 'FAIL'} {r.name}" + ("" if r.ok else f" (got {r.got})"))
    failed += 0 if r.ok else 1
if failed:
    print(f"FAIL {failed} case(s)")
    sys.exit(1)
print("all cases passed")
sys.exit(0)
