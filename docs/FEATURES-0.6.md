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
M.EVENTS = { f_stats_cancel = true }  -- the module's game events (names start with "f_" .. M.ID .. "_"; another is left out)

-- SIMULATION half, every game, at the same game step (lockstep): deterministic, no os.clock/os.time/math.random, no file,
-- no GUI. st = the game script state (saved with the game); env = see below.
function M.event(st, name, param, env) end   -- one of M.EVENTS, sent by a game's GUI half with env.send (or by the window
                                             -- with u.send); param.mpfFrom = the sender's name, param.mpfCo = its company
                                             -- (separate mode). Only while one of the module's options is on. State saved.
function M.tick(st, env) return changed end  -- optional, every simulation step: keep it cheap (env.every(n) helps); return
                                             -- true when it changed st (the bridge saves the state only then)
function M.month(st, env) end                -- optional, at the first step of every game month (env.month(): the game
                                             -- month's number, floor(game time / month duration), as mpfever_eco.lua counts)
function M.onAction(st, a, ok, env) end      -- optional: after every player action the games replay (see "onAction" below).
                                             -- For the journal, "built by", budgets.
function M.onGameEvent(st, id, name, param, env, src) return changed end  -- optional: the game's own script events the
                                             -- bridge sees (id: the event's id, e.g. "apply_command"; src: its source), every
                                             -- game; return true when it changed st

-- GUI half of the bridge, every game, about once a second (optional). st is the game script state as the GUI sees it
-- (read only). Decisions that need one decider are taken by the host only (env.isHost) and sent as events, stamped and
-- applied by every game at the same step (as co_month in 0.5).
function M.gui(st, env) end
function M.request(kind, payload, st, env) end   -- optional: a request of the MPFever window (u.request on that side)
function M.allow(a, st, env) return true end     -- optional: THIS player's own action, before it is shipped; return
                                                 -- false, reason to refuse it here (a chat notice tells the reason). For
                                                 -- territories and permissions: no desync, nothing was sent. See "allow".

-- The MPFever window (mpfever_ui.script.lua), every game (optional): a tab of its own while one of the module's options is on.
M.TAB = { id = "stats", title = { "Classement", "Ranking" } }
function M.ui(u) end                          -- builds the tab's content with u's helpers (see "UI" below)
return M
```

A module must load without the game's API (the lobby and the tests require it): no `api.*` call at load time.

## env (given by the options host)

Simulation half (`env` of M.event / M.tick / M.month / M.onAction / M.onGameEvent; made by `F.simEnv` from the bridge's
`SIM.featBridge`):
- `env.log(text)`, `env.gameTime()` (ms), `env.STEP`, `env.on(id)` (option switched on), `env.param(id, pid)` (the value as
  declared in `values`, a number stays a number; the default when unset or unknown), `env.state(st)` (= st.feat[M.ID],
  created empty; st optional), `env.mode` ("separate" / "shared": the mode f_opts came with), `env.co` (the companies
  registry st.co in the separate mode, else nil), `env.CO` (mpfever_co.lua), `env.R` (references), `env.companies()`
  ({ id, ent, name, ai, members = { keys } } sorted by id; the co-op: one, id 1), `env.money(ent)` (a company's balance on
  this game), `env.book(ent, amount)` (money added or taken: a journal entry OTHER; the same on every game when called from an
  event), `env.every(steps)` (true once every that many steps, from the game time: the same step on every game),
  `env.month()` (the game month's number), `env.date()` ({ year, month, day } of the calendar at this game time, or nil:
  decide with env.month(), the calendar follows the game's calendar speed), `env.module(id)` (another feature module loaded
  in this Lua state, e.g. `env.module("tenders").wins`; nil when it is not there).
Every game runs this code; the host never decides alone here.

GUI half (`env` of M.gui / M.request / M.allow; made by `F.guiEnv` from the bridge's `G.featBridge`): `env.log`, `env.on`,
`env.param`, `env.isHost` (the host's game, a dedicated server's too), `env.me` (this player's name, "#n" after it for a
player who joined), `env.myCo` (this player's company id, separate mode), `env.mode`, `env.send(name, param)` (an event of
this module, one of its M.EVENTS, stamped and applied by every game at the same step, as G.coEvent; not sent during a
resynchronisation), `env.chat(text)` (a notice in this game's chat only), `env.write(name, lines)` (the file
`feat_<module>_<name>.txt` of the session folder, name [a-z0-9_]+, lines a list or a text, written only when it changed),
`env.realTime()` (os.clock, the GUI may), `env.gameTime()`, `env.R`, `env.CO`, `env.T` (the game's T(fr, en): texts in the
player's language, e.g. a chat notice), `env.players()` (the names of the other players this game hears from, sorted).
`env.realTime()` (os.clock, the GUI may), `env.gameTime()`, `env.date(t)` (the calendar's { year, month, day } at game time
t, now by default; a date the simulation needs is read by the host here and sent in an event), `env.T(fr, en)` (this game's
language), `env.module(id)`, `env.R`, `env.CO`.

UI (`u` of M.ui, made by `U.featU` in mpfever_ui.script.lua): `u.T(fr, en)`, `u.Tf(fr, en, ...)`, `u.money(n)`, `u.W` (the
text width), `u.isHost`, `u.me`, `u.mode`, `u.on(id)`, `u.param(id, pid)` (the session's options, as MPFever.exe sends them),
`u.read(name)` (the lines of `feat_<module>_<name>.txt` written by env.write; {} when there is none), `u.request(kind,
payload)` (to M.request of the module on this game: ui.log "feat_req"), `u.send(name, param)` (an event of the module, sent as
this player's command: stamped like the player's actions, checked by allow). Widgets, each returns its node: `u.title(t)`,
`u.text(t, cls)` (cls: "warning", "error", "success"...), `u.muted(t)`, `u.gap(h)`, `u.button(label, fn, primary, enabled,
tip)` (the window draws again after fn), `u.row(nodes)`, `u.table(lines, widths, header)` (lines of cells; widths in pixels,
else the width shared; header: the first line as titles). `u.add(node)` puts a node in the tab; M.ui may also return a list of
nodes (they come after those added). The window draws again about once a second.

## The options' journey

1. Lobby (`mpfever_menu.lua`): the host switches an option or picks a parameter in its "Game settings…" panel (both company
   modes) → `request("opt", "<id>=<0|1>")` or `request("opt", "<id>.<param>=<value>")`.
2. MPFever.exe (`launcher/GameOpts.cs`, `MainForm.cs`) keeps the options of the session (string `id=1;id.param=v;...`: the
   options on and the parameters of those only, keys in byte order; an option switched off forgets its parameters), sends them
   to every lobby view (`opts` of menu_state.txt), to the in-game windows (`opts=` of mp_status.txt) and with the session to
   every game (session payload `["opts"]`, both modes), remembers them for the host's next lobby (`gameopts=` of
   mpfever_settings.txt; a dedicated server: `game-options=` of mpfever_server.properties), and reads them back from a
   savegame when a lobby opens on it (`SaveInfo.Opts`: the text `mpfopts:...;` the game keeps, as `mpfrules:` in 0.5.14).
3. The host's game sends the event `f_opts { s = "<canon>", mode }` when the canon of the session's options (`F.canon`: the
   options a module declares, on, allowed in the mode; parameters with a declared value other than the default) differs from
   the game's (st.optsText), at most every 600 frames (about 10 s), never during a resynchronisation; every game applies it at
   the same step (`F.applyOpts`, only from the host: a plain name): st.optsText, st.opts (the parsed map), st.optsMode and
   st.optsCfg = "mpfopts:<canon>;", all kept in the savegame.
4. Every module reads `env.on(id)` / `env.param(id, pid)`, which read st.opts: the same on every game, at every step.
5. The window's "Game" tab lists the options on and their parameters for every player; the host switches them there too
   (`U.featAsk` → MPFever.exe's "opt" request, as in the lobby, then 3.). In the co-op the Game tab shows for the 0.6 options
   only (when one is on, or for the host when one is offered).

## Rules for every feature

- Off by default; nothing at all happens while off (no event, no state, no file).
- Money moves only through `env.book` in the simulation half, from events: the same on every game.
- Figures that the game computes for the LOCAL player (company value, "transported") are measured by the host and sent
  in an event, never read locally to decide (see release/recherche-0.6/00-INDEX.md).
- A refusal of a player's own action happens on that player's game before anything is sent (no desync risk).
- Each feature has an offline test `tests/test_feat_<id>.py` (lupa, Lua 5.2), picked up by tests/run_all.py.
- Texts: French and English (`T(fr, en)`); comments in the style of the surrounding code; English identifiers.
- Each change of existing behaviour has an `MPFEVER_...=0` switch back to the old behaviour.
- `MPFEVER_FEAT=0` (a session setting, read once at load in every Lua state) turns the whole options host off: no hook runs,
  no f_opts is sent, the lobby and the window show nothing of it (0.5.14 exactly).

## onAction: what a module hears

Every game hears the same actions at the same step (`F.simAction`):
- an action the simulation applies (`simApplyDue`): `a` is the queued action (`a.fn` the api.cmd factory, `a.args` with THIS
  game's entity ids, `a.co`, `a.origin`, `a.uid`, `a.at`, `a.tok`), `ok` = the command was given to the engine; MPFever's own
  events come too (`a.fn == "makeScriptingSendEventCmd"`, `a.args[2] == "mpfever"`);
- an action applied in a pause (`runPausedActions`, through the note `f_act` to the simulation): `a = { fn, args (none for a
  build), co, origin, uid, at, paused = true }`, `ok` = the engine's verdict;
- a tool's build (`SIM.featNative`, at the build's step: the builder's own when it is shipped, and every replay of it):
  `a = { fn = "nativeBuild", native = true, at, proposal, data }` (the engine's proposal and its data, userdata, to read during
  the call only), `ok = true`. The simulation does not know who built it: a company's build carries its player entity in the
  proposal (`proposal.toAdd[i].playerEntity`...); in the co-op, the builder's name is not known there.
Entity ids differ between games: keep positions or the references of mpfever_refs.lua in the state, never raw ids.

`M.digest(a)` (optional, plain data out): the bridge translates an action's references to this game's entity ids IN PLACE when
it applies it, so what a reference said (a demolished construction's file and place, a sold vehicle's creation key) is gone in
onAction. A module with `M.digest` gets, instead of the action, the copy it made of it BEFORE (`F.digests`): for the actions the
simulation applies (simApplyDue), the paused ones (f_act `dg`), and the tools' builds WITH their builder (`G.featNativeAct`: the
builder's game when it ships its build, every other game when it replays it, before the replay; f_act with `only`, to the modules
with a digest alone, so the others still hear a tool's build once, as `nativeBuild`). That last path is not stamped (each game
hands it over when it ships or replays the build): such a module keeps a state that ends the same whatever the order (the
journal sorts by the build's own game time).

## allow: what a module may refuse

`G.featRefuse` (interface half, this player's game only), only while a module on has `M.allow`:
- a window's command (an "act_req" of ui.log, before it is stamped, `stampHeld`): `a = { fn, args (as the window marshalled
  them, see mpfever_refs.lua), co, origin }`. Refused: never sent nor applied; the window's command gets a refused result
  (results.log), this game's chat says the reason;
- a tool's build held by the DLL (`pollNativeEvents`): `a = { fn = "nativeBuild", native = true, natId, proposal }` (proposal:
  the compact proposal the tool applied, `C.compactProposal`, when its event came in the last 5 frames, else nil). Refused:
  the DLL drops it (`dropid`, the way of a build made during a resynchronisation), it is never announced.
A module whose allow fails lets the action through (logged).

## Hook points (implemented)

| Where | Name | What |
|---|---|---|
| mpfever_common.lua | `C.feat()` | loads mpfever_feat.lua once per Lua state (nil when it cannot) |
| bridge, top | `K.FEAT` | `MPFEVER_FEAT ~= "0"`, read once |
| bridge, `executeActionOnce` | (inline) | the `f_` events carry `param.mpfFrom` / `param.mpfCo` in both modes |
| bridge, `simApplyDue` | `SIM.featAction`, `SIM.featDigests` (`SIM.featDg`) | onAction of each action the simulation applies (with the modules' copies taken before it) |
| bridge, `update` (top) | `SIM.featOn`, `SIM.featHears`, `SIM.featHearing` | an option on (st.optsText), a module hears game events |
| bridge, `update` (end) | `SIM.featTick` | month and tick |
| bridge, `handleEvent` onPreBuildProposal | `SIM.featSeq`, `SIM.featNative` | onAction of a tool's build |
| bridge, `handleEvent` other ids | `SIM.featGameEvent` | onGameEvent |
| bridge, `handleEvent` "mpfever" chain | `SIM.featEvent` | f_opts, f_act, the modules' events (`F.simEvent`) |
| bridge, `H.session` | `G.featOpts` | the session's options |
| bridge, `guiUpdate` (after coGui) | `G.featGui` | f_opts from the host's game, the modules' gui |
| bridge, `stampHeld` | `G.featRefuse`, `G.featRequest` | allow of a window's command; the window's "feat_req" |
| bridge, `pollNativeEvents` | `G.featRefuse`, `G.featTakeTool` | allow of a tool's build |
| bridge, `guiHandleEvent` | `G.featTool` | the build the tool applies (for allow) |
| bridge, `runPausedActions` | `G.featPausedAct`, `G.featDigests` | the note f_act of a paused action (with the modules' copies taken before it) |
| bridge, `shipNativeBuilds`, `shipTerrain`, `runNativeReplays` | `G.featNativeAct` | a tool's build with its builder, to the modules with `M.digest` (f_act `only`) |
| bridge, helpers | `SIM.featBridge`, `G.featBridge`, `G.featChat` | what the env is made of |
| window | `U.featView`, `U.featTabs`, `U.featGameTab`, `U.featGameRows`, `U.featAsk`, `U.featU`, `U.featTabRows` | Game tab, modules' tabs |
| lobby (`setup`) | `featView`, `featSection`, `featSummary` | the host's panel, the players' line |
| MPFever.exe | `GameOpts` (Parse, Canon, Apply), `GameOptions()`, `LoadSaveOpts`, `SaveInfo.Opts`, `ServerConfig.GameOptions`, request "opt" | the session's options |

The options host (mpfever_feat.lua): `F.MODULES`, `F.loader` (tests), `F.load`, `F.parse`, `F.encode`, `F.canon`, `F.on`,
`F.param`, `F.modOn`, `F.active`, `F.offered`, `F.summary`, `F.text`, `F.showValue`, `F.call` (every call protected; a failing
hook is logged the first 5 times, then every 100th), `F.applyOpts`, `F.simEvent`, `F.simTick`, `F.simAction`,
`F.simGameEvent`, `F.hearsGameEvents`, `F.digests`, `F.gui`, `F.request`, `F.allow`, `F.wantsAllow`, `F.tabs`, `F.simEnv`, `F.guiEnv`.

## How to integrate a module

1. Write `mod/mpfever_1/content/mpfever_feat_<id>.lua` as above (its id is already in `F.MODULES`; a module not in the list
   is never loaded) and add it to the files of `mod/mpfever_1/_content.json` (tests/check_repo.py checks the list). No `api.*`
   call at load time and no state of the game in the file (four Lua states load it).
2. Options: ids [a-z_]+ unique over all modules, `title` and `desc` { French, English }, `modes`, `params` with `values`
   (numbers or [-0-9a-z_.] texts) and a `default` (else the first value). Nothing else is needed for the lobby, the window's
   Game tab, MPFever.exe and the savegame: they list the options from OPTIONS.
3. Events: names `f_<id>_...` in `M.EVENTS`; send them with `env.send` (interface half) or `u.send` (window). Decide on the
   host only (`env.isHost`) what needs one decider, and send it as an event.
4. Simulation code deterministic (no os.clock, os.time, math.random, file, GUI); money only with `env.book`, from an event;
   the module's state only in `env.state()`; values the game computes for the LOCAL player measured by the host and sent in an
   event.
5. Return true from tick / onGameEvent when st changed (else the change is lost at the next step).
6. A tab: `M.TAB` + `M.ui(u)`; data from the interface half with `env.write(name, lines)`, read back with `u.read(name)`.
7. Texts: every T(fr, en) English text gets its translations in launcher/lang.json (`python tests/test_lang.py --add`, then
   fill them in).
8. A test `tests/test_feat_<id>.py` (lupa): load mpfever_feat.lua, give it the module through `F.loader`, mock the bridge's
   helpers (see tests/test_feat_host.py), check that nothing is called with all options off.
9. Run `python tests/run_all.py` (with `--exe launcher/bin/Release/MPFever.exe` after a launcher change).
