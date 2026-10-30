# MPFever 0.6 game options: the contract between the options host and the feature modules

Every 0.6 idea (release/recherche-0.6/01..09, decisions in release/recherche-0.6/00-REPONSES.md) is a **game option the
host switches on or off in the lobby's "Game settings"**. An option with extra parameters shows them in the lobby **only
while the option is on**. Every option is **off by default**: with all options off, a game plays exactly as 0.5.14 did
(no new event sent, no state written, no file written, no change in a check). That is the no-regression rule.

## Where things live

- `mod/mpfever_1/content/mpfever_feat.lua`: the options host (loads the feature modules, parses and encodes the options,
  dispatches events, ticks, GUI and UI calls). Written once, generic: no feature code in it.
- `mod/mpfever_1/content/mpfever_feat_<id>.lua`: one module per feature group (`journal`, `stats`, `market`, `territory`,
  `tenders`, `perms`, `trade`, `stock`). Listed once in `mpfever_feat.lua`'s `MODULES` list (one line each).
- The public games options (`public`, note 09) are launcher and server-list work (C#): they declare their options in
  `mpfever_feat_public.lua` (OPTIONS only) so the lobby shows them like the others.
- The bridge (`mpfever_bridge.script.lua`), the window (`mpfever_ui.script.lua`), the lobby (`mpfever_menu.lua`) and
  MPFever.exe (`launcher/MainForm.cs`) only call the options host at a few hook points. **The bridge is at Lua's limit of
  200 locals in its main chunk: never add a `local` at its top level** (use fields of G, SIM, H or K).

## A feature module

```lua
local M = {}
M.ID = "stats"                       -- [a-z]+, unique; the state is st.feat[M.ID], the events start with "f_" .. M.ID
M.OPTIONS = {                         -- the lobby's "Game settings", section "Game options (0.6)"
  { id = "goal",                      -- option id, unique over all modules ([a-z_]+)
    title = { "Objectif de partie", "Game goal" },          -- { French, English }
    desc  = { "...", "..." },                               -- one or two short sentences, shown under the switch
    modes = "separate",               -- "separate" (one company per player only), "shared" (co-op only) or "both"
    params = {                        -- shown in the lobby only while the option is on
      { id = "years", label = { "Durée", "Length" }, values = { 10, 20, 30, 50 }, default = 20,
        show = function(v, T) return T("%s ans", "%s years"):gsub("%%s", v) end },   -- optional label of a value
    } },
}
M.EVENTS = { f_stats_cancel = true }  -- the module's game events (names start with "f_" .. M.ID)

-- SIMULATION half, every game, at the same game step (lockstep): deterministic, no os.clock/os.time/math.random, no file,
-- no GUI. st = the game script state (saved with the game); env = see below.
function M.event(st, name, param, env) end   -- one of M.EVENTS, sent by a game's GUI half with env.send
function M.tick(st, env) end                 -- optional, every simulation step: keep it cheap (env.every(n) helps)

-- GUI half of the bridge, every game, about once a second (optional). st is the game script state as the GUI sees it
-- (read only). Decisions that need one decider are taken by the host only (env.isHost) and sent as events, stamped and
-- applied by every game at the same step (as co_month in 0.5).
function M.gui(st, env) end
function M.request(kind, payload, st, env) end   -- optional: a request of the MPFever window (env.uiRequest on that side)

-- The MPFever window (mpfever_ui.script.lua), every game (optional): a tab of its own while one of the module's options is on.
M.TAB = { id = "stats", title = { "Classement", "Ranking" } }
function M.ui(u) end                          -- builds the tab's content with u's helpers (see mpfever_feat.lua)
return M
```

A module must load without the game's API (the lobby and the tests require it): no `api.*` call at load time.

## env (given by the options host)

Simulation half (`env` of M.event / M.tick):
- `env.log(text)`, `env.gameTime()` (ms), `env.STEP`, `env.on(id)` (option switched on), `env.param(id, pid)` (with the
  default), `env.state(st)` (= st.feat[M.ID], created empty), `env.mode` ("separate" / "shared"), `env.co` (the companies
  registry st.co in the separate mode, else nil), `env.companies()` ({ id, ent, name, ai, members } sorted by id),
  `env.money(ent)`, `env.book(ent, amount)` (money added or taken, the same on every game), `env.R` (references),
  `env.every(steps)` (true once every that many steps, the same step on every game).
Every game runs this code; the host never decides alone here.

GUI half (`env` of M.gui / M.request): `env.log`, `env.on`, `env.param`, `env.isHost`, `env.me` (this player's name),
`env.myCo` (this player's company id, separate mode), `env.send(name, param)` (an event of the module, applied by every
game at the same step, as G.coEvent), `env.chat(text)` (a notice in this game's chat), `env.write(file, lines)` (a text
file in the session folder for the window, written only when it changed), `env.realTime()` (os.clock, the GUI may).

UI (`u` of M.ui): `u.T(fr, en)`, `u.read(file)` (lines of a file written by env.write), `u.request(kind, payload)` (to
M.request of the module on this game), and the window's widgets (text, button, row, table) as `mpfever_feat.lua` exposes them.

## The options' journey

1. Lobby (`mpfever_menu.lua`): the host switches an option or picks a parameter → `request("opt", "<id>=<value>")`.
2. MPFever.exe keeps the options of the session (string `id=1;id.param=v;...`), sends them to every lobby view
   (`st.opts`) and with the session to every game (session payload `["opts"]`), remembers them for the host's next lobby,
   and reads them back from a savegame (text `mpfopts:...;` the game keeps, as `mpfrules:` in 0.5.14).
3. The host's game sends the event `f_opts { s = "<string>" }` when the session's options differ from the game's
   (st.opts); every game applies it at the same step: st.opts and st.optsText (kept in the savegame).
4. Every module reads `env.on(id)` / `env.param(id, pid)`, which read st.opts: the same on every game, at every step.
5. The window's "Game" tab lists the options on and their parameters for every player; the host can change them there too.

## Rules for every feature

- Off by default; nothing at all happens while off (no event, no state, no file).
- Money moves only through `env.book` in the simulation half, from events: the same on every game.
- Figures that the game computes for the LOCAL player (company value, "transported") are measured by the host and sent
  in an event, never read locally to decide (see release/recherche-0.6/00-INDEX.md).
- A refusal of a player's own action happens on that player's game before anything is sent (no desync risk).
- Each feature has an offline test `tests/test_feat_<id>.py` (lupa, Lua 5.2), picked up by tests/run_all.py.
- Texts: French and English (`T(fr, en)`); comments in the style of the surrounding code; English identifiers.
- Each change of existing behaviour has an `MPFEVER_...=0` switch back to the old behaviour.
