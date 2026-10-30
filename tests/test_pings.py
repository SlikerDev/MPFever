"""Offline test of the signals on the map (0.5.14, idea G3 of 0.6): a kind picked in the MPFever window arms the next click on
the map; every game draws the signal for 12 s.

G.pingArm, G.pingClick, H.ping and G.pingTick are taken from the real bridge file and run through lupa (Lua 5.2) with a
mocked interface (os.clock, frames, zones). Cases:
  - an armed signal lasts 15 s of real time (review fix: it was 900 frames, 15 s at 60 frames a second only: a fast game
    lost it in a few seconds, a slow one kept it for minutes), at any frame rate; G.pingTick disarms it after 15 s;
  - arming: MPFEVER_PINGS=0 and an unknown kind arm nothing; a click without an arm places nothing; one click per arm;
  - one signal every 2 s (120 frames) at most;
  - H.ping: drawn with the kind's colour and the player's in its middle, three per player at most (the oldest goes), numbers
    of the map only (no NaN, nothing beyond 1e6), the own echo not drawn twice, none on a dedicated server; G.pingTick
    takes a signal away after 720 frames.
Run: python tests/test_pings.py
"""
import os, re, sys

try:
    import lupa.lua52 as lupa
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(HERE, "..", "mod", "mpfever_1", "content", "mpfever_bridge.script.lua")

MOCK = r'''
ENV = {}
CLOCK = 100
os.getenv = function(k) return ENV[k] end
os.clock = function() return CLOCK end
NL, BS = "\n", "\\"
ZONES, SENT, LOGS, JOURNAL = {}, {}, {}, {}
api = {
  gui = { mission = {
    setZoneCircle = function(key, pos, r, a, col) ZONES[key] = { x = pos.x, y = pos.y, r = r, col = col } end,
    removeZone = function(key) ZONES[key] = nil end,
  }, mouse = nil },
  type = { Vec2f = { new = function(x, y) return { x = x, y = y } end }, Vec4f = { new = function(r, g, b, a) return { r, g, b, a } end } },
}
C = { DIR = "dir", appendFile = function(p, s) JOURNAL[#JOURNAL + 1] = s end }
CO = { rgb = function(i) return 0.1 * i, 0.2, 0.3 end }
G = { frames = 0, me = "Host", coMyColor = function() return 3 end }
H = {}
function log(s) LOGS[#LOGS + 1] = s end
function send(kind, p) SENT[#SENT + 1] = p end
function zones() local n = 0 for _ in pairs(ZONES) do n = n + 1 end return n end
'''


def main():
    src = open(BRIDGE, encoding="utf-8").read()
    m = re.search(r"^G\.pings = \{\}\n.*?^G\.pingTick = function\(\)\n.*?^end\n", src, re.S | re.M)
    if not m:
        print("FAIL: the map signals (G.pings .. G.pingTick) not found in the bridge")
        return 1
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute(MOCK)
    L.execute(m.group(0))
    lua_run = L.eval("function(code) local f = assert(load(code)) return f() end")

    def run(code):
        # (a Lua error is a result too: the case that gets it fails, the others still run)
        try:
            return lua_run(code)
        except lupa.LuaError as e:
            return "LUA ERROR " + str(e).splitlines()[0]

    fails = []

    def check(name, cond, got=""):
        print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f": {got}" if got != "" else ""))
        if not cond:
            fails.append(name)

    run(r'''
-- a click on the map at (x, y) after dt seconds and df frames: how many signals were sent
function click(dt, df, x, y)
  CLOCK = CLOCK + dt
  G.frames = G.frames + df
  SENT = {}
  G.pingClick("select-world", { pos = { x = x or 100, y = y or 200, z = 5 } })
  return #SENT
end
function arm(k) G.pingArm({ k = k or "warn" }) return G.pingArmed ~= nil end
''')
    print("arming and the 15 s of real time")
    check("armed", run("return arm('warn')") is True)
    check("a click 10 s later at 200 frames a second (2000 frames): placed", run("return click(10, 2000)") == 1)
    check("the signal sent with its kind, place and the player's colour",
          run("local p = SENT[1] return p.k .. ' ' .. p.x .. ',' .. p.y .. ',' .. p.z .. ' c' .. tostring(p.c)") == "warn 100,200,5 c3")
    check("one click per arm", run("return click(0, 200)") == 0)
    check("armed again", run("return arm('build')") is True)
    check("a click 16 s later at 6 frames a second (100 frames): too late", run("return click(16, 100)") == 0)
    run("arm('here')")
    run("CLOCK = CLOCK + 14; G.frames = G.frames + 5000; G.pingTick()")
    check("G.pingTick keeps it within 15 s, whatever the frames", run("return G.pingArmed ~= nil") is True)
    run("CLOCK = CLOCK + 2; G.frames = G.frames + 10; G.pingTick()")
    check("G.pingTick disarms it after 15 s", run("return G.pingArmed == nil") is True)
    check("and says so", any("no click within 15 s" in str(s) for s in L.globals().LOGS.values()))
    check("MPFEVER_PINGS=0: nothing armed", run('ENV = { MPFEVER_PINGS = "0" }; local r = arm("warn"); ENV = {}; return r') is False)
    check("an unknown kind: nothing armed", run('return arm("boom")') is False)
    check("a click without an arm: nothing", run("return click(1, 200)") == 0)

    print("one signal every 2 s")
    check("a signal", run("arm(); return click(1, 200)") == 1)
    check("another one 100 frames later: not sent", run("arm(); return click(1, 100)") == 0)
    check("130 frames later: sent", run("arm(); return click(1, 130)") == 1)

    print("H.ping")
    run("ZONES, G.pings = {}, {}")
    got = run(r'''
H.ping("Bob#1", { x = 10, y = 20, z = 0, k = "here", c = 2, r = 60 })
local key = "mpfever_ping_" .. G.pingN
local a, b = ZONES[key], ZONES[key .. "_c"]
return zones() .. " " .. tostring(a and a.x) .. "," .. tostring(a and a.y) .. " r" .. tostring(a and a.r) .. " middle r" .. tostring(b and b.r)
''')
    check("drawn: the kind's circle and the player's colour in its middle", got == "2 10,20 r60 middle r20", got)
    run('for i = 1, 3 do H.ping("Bob#1", { x = 10 * i, y = 20, z = 0, k = "warn" }) end')
    check("three per player at most: the oldest goes", run('local n = 0 for _, s in pairs(G.pings) do if s.who == "Bob#1" then n = n + 1 end end return n') == 3)
    run('H.ping("Ann#2", { x = 1, y = 2, k = "build" })')
    check("another player's own three", run('local n = 0 for _, s in pairs(G.pings) do if s.who == "Ann#2" then n = n + 1 end end return n') == 1)
    before = run("return G.pingN")
    run('H.ping("Bob#1", { x = 0/0, y = 1, k = "warn" }); H.ping("Bob#1", { x = 1e7, y = 1, k = "warn" }); H.ping("Bob#1", { x = 1, y = 1, k = "nuke" })')
    check("NaN, beyond the map, an unknown kind: not drawn", run("return G.pingN") == before)
    run('H.ping("Host", { x = 1, y = 1, k = "warn" })')
    check("its own echo from the launcher: not drawn twice", run("return G.pingN") == before)
    run('C.SERVER = true; H.ping("Bob#1", { x = 1, y = 1, k = "warn" }); C.SERVER = nil')
    check("a dedicated server: none", run("return G.pingN") == before)
    run('ENV = { MPFEVER_PINGS = "0" }; H.ping("Bob#1", { x = 1, y = 1, k = "warn" }); ENV = {}')
    check("MPFEVER_PINGS=0: none", run("return G.pingN") == before)
    run("G.frames = G.frames + 721; G.pingTick()")
    check("G.pingTick takes them away after 720 frames (12 s)", run("local n = 0 for _ in pairs(G.pings) do n = n + 1 end return n .. ' ' .. zones()") == "0 0")

    if fails:
        print(f"FAIL {len(fails)} case(s): {', '.join(fails)}")
        return 1
    print("all cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
