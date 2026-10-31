"""Offline test of the companies' ranks (mpfever_progression.lua, one company per player), 0.6.3.

A player reported that the host's company rose fast (supervisor) while the others barely moved (near junior). The savegame's
company (number 1, the host's) followed the game's own experience while that one was higher (issue #63's fix), and the game's
own experience is the world's population: it grows with what every company carries. Company 1 now keeps where it began and
adds its own score only.

PG.tally is run through lupa (Lua 5.2) with a mocked game (levels, the game's own experience) and towns. Cases:
  - two companies, only company 2 carries, the world's population grows: company 1's experience stays where it began,
    company 2's grows with its score;
  - company 1 carries: its experience grows from where it began by its own score (its bar moves: #63 stays fixed);
  - a savegame of 0.6.2, company 1's record already far up (no base yet): never lowered, then its own score only;
  - its rank never goes down when its score falls;
  - MPFEVER_RANK1BASE=0: follows the game's own experience (0.6.2); MPFEVER_RANK1OWN=0: its score only (before #63).
Run: python tests/test_ranks.py
"""
import os, sys

try:
    import lupa.lua52 as lupa
except ImportError:
    print("lupa is not installed (pip install lupa): test skipped")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "..", "mod", "mpfever_1", "content", "mpfever_progression.lua")

MOCK = r'''
ENV = {}
os.getenv = function(k) return ENV[k] end
OWN = 9000       -- the game's own experience (the world's population)
GAME = {
  levelFor = function(x) return math.floor(x / 1000) + 1 end,
  own = function(entity) return { experience = OWN, level = 1, potentialLevel = 1 } end,
  sensitivity = function() return 0 end,
}
REG = { mode = "separate", list = { { id = 1, ent = 101 }, { id = 2, ent = 102 } } }
-- one town of `pop` residents; carried[id] = cargo delivered by that company
function TOWNS(pop, c1, c2)
  local carried = {}
  if c1 > 0 then carried[1] = { cargo = c1, late = 0, passengers = 0, unhappy = 0 } end
  if c2 > 0 then carried[2] = { cargo = c2, late = 0, passengers = 0, unhappy = 0 } end
  return { { town = 7, population = pop, state = { cachedRatings = { urban_care = { value = 1 } } }, carried = carried } }
end
function EXP(prog, id) for _, r in ipairs(prog.records) do if r.company == id then return r.experience end end end
'''

fails = []


def check(name, cond, got=""):
    print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f": {got}" if got != "" and not cond else ""))
    if not cond:
        fails.append(name)


def main():
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute(MOCK)
    L.execute("PG = (function() " + open(FILE, encoding="utf-8").read() + " end)()")
    run = L.eval("function(code) return assert(load(code))() end")

    # --- only company 2 carries, the world grows
    got = run("""
      local prog = PG.ensure({})
      local out = {}
      for i, pop in ipairs({ 1000, 2000, 4000, 8000 }) do
        OWN = 9000 + pop
        PG.tally(prog, REG, TOWNS(pop, 0, 100), GAME)
        out[#out + 1] = EXP(prog, 1) .. "/" .. EXP(prog, 2)
      end
      return table.concat(out, " ")""")
    check("only company 2 carries: company 1 stays where it began, company 2 grows",
          got == "10000/1000 10000/2000 10000/4000 10000/8000", got)

    # --- company 1 carries: its bar moves from where it began (#63)
    got = run("""
      OWN = 9000
      local prog = PG.ensure({})
      local out = {}
      for i, pop in ipairs({ 0, 500, 1500 }) do
        PG.tally(prog, REG, TOWNS(pop, 100, 0), GAME)
        out[#out + 1] = EXP(prog, 1)
      end
      return table.concat(out, " ")""")
    check("#63: company 1 carries: its experience grows from where it began by its own score", got == "9000 9500 10500", got)

    # --- a savegame of 0.6.2: company 1 already far up, no base
    got = run("""
      OWN = 30000
      local prog = PG.ensure({ records = { { company = 1, experience = 25000, potential = 26, level = 20 } } })
      PG.tally(prog, REG, TOWNS(1000, 100, 100), GAME)    -- both carry half: score 500 each
      local a = EXP(prog, 1)
      OWN = 60000
      PG.tally(prog, REG, TOWNS(3000, 100, 100), GAME)    -- score 1500
      local b = EXP(prog, 1)
      PG.tally(prog, REG, TOWNS(200, 100, 100), GAME)     -- score 100: not lowered
      return a .. " " .. b .. " " .. EXP(prog, 1)""")
    check("a 0.6.2 savegame: not lowered, then its own score only (not the world's 60000)", got == "25000 26000 26000", got)

    # --- the old ways
    run("ENV.MPFEVER_RANK1BASE = '0'")
    got = run("""
      OWN = 9000
      local prog = PG.ensure({})
      PG.tally(prog, REG, TOWNS(1000, 0, 100), GAME)
      OWN = 20000
      PG.tally(prog, REG, TOWNS(2000, 0, 100), GAME)
      return tostring(EXP(prog, 1))""")
    check("MPFEVER_RANK1BASE=0: follows the game's own experience, as 0.6.2", got == "20000", got)
    run("ENV.MPFEVER_RANK1BASE = nil; ENV.MPFEVER_RANK1OWN = '0'")
    got = run("""
      OWN = 9000
      local prog = PG.ensure({})
      PG.tally(prog, REG, TOWNS(1000, 100, 0), GAME)
      PG.tally(prog, REG, TOWNS(2000, 100, 0), GAME)
      return tostring(EXP(prog, 1))""")
    check("MPFEVER_RANK1OWN=0: stays at the game's start, as before #63", got == "9000", got)
    run("ENV.MPFEVER_RANK1OWN = nil")

    print(f"\n{len(fails)} failure(s)" if fails else "\nall passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
