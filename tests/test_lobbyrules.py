"""Offline test of the lobby's game rules of 0.5.14 (mpfever_menu.lua): what MPFever.exe sends the lobby is read the way it
writes it.

The lobby page is one React component: the two pieces that read MPFever.exe's texts are taken from the real file (the loop
over the computer companies, the rules' line and its summary) and run through lupa (Lua 5.2). Cases:
  - the computer companies, "n:colour:level:money:name;..." (0.5.14, LobbyAiView: its start money, -1 the players'), and
    "n:colour:level:name;..." of an MPFever.exe of 0.5.13 (the players' money); their colours taken;
  - the rules, "start|share|months" (LobbyRulesView): the start money, the sharing rules on or off, the months before a
    bankruptcy; none yet (an older MPFever.exe): 2 million, on, the session's bankruptcy months; the line every player sees.
Run: python tests/test_lobbyrules.py
"""
import os, re, sys

try:
    import lupa.lua52 as lupa
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
MENU = os.path.join(HERE, "..", "mod", "mpfever_1", "content", "mpfever_menu.lua")


def main():
    src = open(MENU, encoding="utf-8").read()
    m_ai = re.search(r"^(\t+)for entry in \(st\.ai or \"\"\):gmatch\(\"\[\^;\]\+\"\) do\n.*?^\1end\n", src, re.S | re.M)
    m_rules = re.search(r"^\t+local rStart, rShare, rMonths = \(st\.rules or \"\"\).*?\"Bankruptcy: %s months\"\)[^\n]*\n", src, re.S | re.M)
    if not (m_ai and m_rules):
        print("FAIL: the lobby's reading of the computer companies or of the rules not found in mpfever_menu.lua")
        return 1
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute("SIDE_W, PIC_W = 600, 300\nfunction T(fr, en) return en end")
    L.execute("function readAis(st)\n  local ais, taken = {}, {}\n" + m_ai.group(0) + "  return ais, taken\nend\n")
    L.execute("function readRules(st)\n" + m_rules.group(0) + "  return rStart, shareOn, rMonths, summary\nend\n")
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
function ais(text)
  local list, taken = readAis({ ai = text })
  local t = {}
  for _, a in ipairs(list) do t[#t + 1] = a.n .. "/" .. a.ix .. "/" .. a.lv .. "/" .. a.money .. "/" .. a.name end
  local k = {}
  for ix in pairs(taken) do k[#k + 1] = ix end
  table.sort(k)
  return table.concat(t, " ; ") .. " | taken " .. table.concat(k, ",")
end
function rules(text, bankrupt)
  local s, on, mo, summary = readRules({ rules = text, bankrupt = bankrupt })
  return s .. " " .. tostring(on) .. " " .. mo .. " | " .. summary
end
''')
    print("the computer companies")
    got = run('return ais("1:7:3:1000000:Regional Transport;2:3:1:-1:Valley Coaches")')
    check("with their start money (0.5.14)", got == "1/7/3/1000000/Regional Transport ; 2/3/1/-1/Valley Coaches | taken 3,7", got)
    got = run('return ais("3:5:2:Plain Buses")')
    check("an MPFever.exe of 0.5.13: no money, the players'", got == "3/5/2/-1/Plain Buses | taken 5", got)
    got = run('return ais("4:2:2:20000000:")')
    check("no name yet", got == "4/2/2/20000000/ | taken 2", got)
    got = run('return ais("")')
    check("none", got == " | taken ", got)
    got = run('return ais("x;5:1:2:0:Estuary Lines;bad")')
    check("what is not a company is left out", got == "5/1/2/0/Estuary Lines | taken 1", got)

    print("the rules")
    got = run('return rules("5000000|0|6")')
    check("start money, sharing off, months", got == "5000000 false 6 | Start: 5 M  ·  Sharing off  ·  Bankruptcy: 6 months", got)
    got = run('return rules("500000|1|0")')
    check("500 k, sharing on, no bankruptcy", got == "500000 true 0 | Start: 500 k  ·  Sharing on  ·  No bankruptcy", got)
    got = run('return rules("0|1|24")')
    check("no start money", got == "0 true 24 | Start: 0  ·  Sharing on  ·  Bankruptcy: 24 months", got)
    got = run('return rules(nil, 3)')
    check("none yet (an older MPFever.exe): 2 million, on, the session's months", got == "2000000 true 3 | Start: 2 M  ·  Sharing on  ·  Bankruptcy: 3 months", got)
    got = run('return rules("abc", nil)')
    check("not the rules' form: the defaults", got == "2000000 true 12 | Start: 2 M  ·  Sharing on  ·  Bankruptcy: 12 months", got)

    if fails:
        print(f"FAIL {len(fails)} case(s): {', '.join(fails)}")
        return 1
    print("all cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
