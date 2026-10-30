-- Computer companies (AI, experimental, 0.5.12): companies the host's game runs by itself, in the companies mode. The host adds
-- them in its lobby (each with its colour); a savegame's computer companies are taken again by the lobby. Every decision is taken
-- on the host only and goes to the other games exactly as a player's builds and actions do (their replays, their stamps): no new
-- determinism risk. The module keeps no knowledge of its own across loads: each step reads the world (what the company owns) and
-- does the next thing missing, one at a time. Several companies take their steps in turn.
local M = {}

-- the company of the step under way (see M.tick): its key in the registry ("ai:<n>"), its name, its colour (a palette index)
local AIKEY, AINAME, AICOLOR, AINUM, AIMONEY = "ai:1", "", 7, 1, nil
-- the names of new computer companies, by number
local NAMES_FR = { "Transports Régionaux", "Cars de la Vallée", "Lignes du Littoral", "Autocars du Plateau", "Réseau des Collines", "Transports du Pays",
	"Bus de la Plaine", "Lignes de l'Estuaire" }
local NAMES_EN = { "Regional Transport", "Valley Coaches", "Coastal Lines", "Plateau Buses", "Hills Network", "Country Transport",
	"Plain Buses", "Estuary Lines" }
-- (two-sided: a bus going either way along the street stops at it; a one-sided stop on a line there and back left the engine
-- searching for a way to turn round, and the simulation stood still on every game)
local STOP_MODEL = "stations/street/small_stops/small_old_twosided.con"
local DEPOT_FILE = "::/depots/road/road_maint_station.con"
local TICK = 60            -- frames between two looks at the world
local RESERVE = 400000     -- money kept back (the lines' first months cost more than they earn): the level's, see LEVELS
local BUS_COST = 180000    -- a bus, until the first purchase measures it

-- The levels (0.5.13), the host's choice for each company in its lobby: how often it looks at the world (frames), the money it
-- keeps back, the vehicles a line may get, when a line gets one more (seats used, cargo waiting), how many of its lines carry
-- freight, how far its freight goes, and whether it competes with the players (Hard: the industries and towns they serve are
-- not left to them).
-- (0.5.14) and how it grows: its first lines (bootstrap) freely, then a new one only once the last one had time to fill
-- (settle, game time) and while its lines earn (their result together) or it holds that much money besides its reserve (freeCash);
-- whether the lines between towns and the freight come before the towns' own lines (profitFirst: a fare grows with the
-- distance flown, so the short town lines earn the least)
local LEVELS = {
	{ name = "easy", tick = 150, reserve = 700000, maxBus = 4, maxTruck = 5, busUse = 0.85, truckUse = 0.6, waiting = 80, freightShare = 1 / 3,
		freightMax = 4000, compete = false, townMin = 600, pause = 1200, bootstrap = 1, settle = 360000, freeCash = 3000000, profitFirst = false, runMonths = 6 },
	{ name = "normal", tick = 60, reserve = 400000, maxBus = 8, maxTruck = 10, busUse = 0.75, truckUse = 0.45, waiting = 40, freightShare = 1 / 2,
		freightMax = 5000, compete = false, townMin = 500, pause = 600, bootstrap = 2, settle = 240000, freeCash = 2000000, profitFirst = true, runMonths = 4 },
	{ name = "hard", tick = 30, reserve = 350000, maxBus = 12, maxTruck = 14, busUse = 0.6, truckUse = 0.35, waiting = 25, freightShare = 2 / 3,
		freightMax = 6500, compete = true, townMin = 300, pause = 300, bootstrap = 3, settle = 120000, freeCash = 1200000, profitFirst = true, runMonths = 3 },
}
local LV = LEVELS[2]

local function L(E, s) E.log("AI" .. (AINUM ~= 1 and tostring(AINUM) or "") .. " " .. s) end

-- the computer companies the host chose in its lobby: "n:colour:level,..." (the session's "ai"; 0.5.12 sent "n:colour"), as
-- { { n, color, level }... }; the developer tests' MPFEVER_AI=1 gives the first one when the session has none
function M.listOf(text)
	local out, seen = {}, {}
	for part in tostring(text or ""):gmatch("[^,;]+") do
		-- ("n:colour:level:money", 0.5.14: its start money, -1 or none = the players')
		local n, ix, lv, mo = part:match("^%s*(%d+):(%d+):?(%d*):?(%-?%d*)%s*$")
		n, ix, lv, mo = tonumber(n), tonumber(ix), tonumber(lv), tonumber(mo)
		if n and n >= 1 and n <= 32 and not seen[n] then
			seen[n] = true
			out[#out + 1] = { n = n, color = ix, level = (lv and lv >= 1 and lv <= 3) and lv or 2, money = (mo and mo >= 0 and mo <= 1e10) and mo or nil }
		end
	end
	return out
end

local function newName(E, n)
	local list = (E.C.LANGCODE == "fr") and NAMES_FR or NAMES_EN
	return list[(n - 1) % #list + 1] .. (n > #list and (" " .. tostring(n)) or "")
end

-- ------------------------------------------------------------------ reading the world

local function aiCompany(E)
	local reg = E.G.co
	if not reg then return nil end
	return E.CO.byKey(reg, AIKEY)
end

local function balanceOf(E, ent)
	local ok, acc = pcall(function() return E.api.engine.getComponent(ent, E.api.type.ComponentType.ACCOUNT) end)
	return ok and acc and acc.balance or 0
end

local function ownerOf(E, e)
	local ok, o = pcall(function() return E.R.ownerOf(e) end)
	return ok and o or nil
end

local function townName(E, t)
	local n = tostring(t)
	pcall(function() n = E.api.engine.getComponent(t, E.api.type.ComponentType.NAME).name end)
	return n
end

local function centre(E, t, use)
	local api = E.api
	local ok, p = pcall(function() return api.engine.util.town.getTownDistrictCenter(t, use) end)
	if ok and p then return { x = p.x, y = p.y, z = p.z } end
	return nil
end

local function dist(a, b) return math.sqrt((a.x - b.x) ^ 2 + (a.y - b.y) ^ 2) end

local function currentYear(E)
	local api = E.api
	local y = 1940
	pcall(function()
		local gt = api.engine.getComponent(api.engine.util.getWorld(), api.type.ComponentType.GAME_TIME)
		local now, best = gt.gameTime, -1
		for _, d in ipairs(gt.dates) do
			if d[1] <= now and d[1] > best then best = d[1]; y = d[2].year end
		end
	end)
	return y
end

-- towns by inhabitants (residential capacity), the biggest first
local function townsBySize(E)
	local api, R = E.api, E.R
	local caps = {}
	pcall(function() caps = api.engine.system.townBuildingSystem.getTown2personCapacitiesMap() end)
	local list = {}
	for _, t in ipairs(R.entitiesWith("TOWN")) do
		local c = caps[t]
		list[#list + 1] = { e = t, size = c and ((c[1] or 0) + (c[2] or 0) + (c[3] or 0)) or 0 }
	end
	table.sort(list, function(a, b) if a.size ~= b.size then return a.size > b.size end return a.e < b.e end)
	return list
end

-- towns for the company's own lines: the biggest first, the ones the other companies already serve put back (a town crossed by a
-- player's line of 15 stops left the company's new line a few passengers only; and the players keep their towns, PvE)
local function townsForLines(E, ent)
	local api = E.api
	local list = townsBySize(E)
	for _, t in ipairs(list) do
		local others = 0
		pcall(function()
			for _, s in ipairs(api.engine.system.stationSystem.getStations(t.e)) do
				-- (0.5.14: another company's station; a station nobody owns, an industry's own, is none. MPFEVER_AIRETRY=0: counted)
				local o = ownerOf(E, s)
				if o ~= ent and (o ~= nil or os.getenv("MPFEVER_AIRETRY") == "0") then others = others + 1 end
			end
		end)
		t.others = others
		t.score = t.size / (1 + others / (LV.compete and 12 or 3))
	end
	table.sort(list, function(a, b) if a.score ~= b.score then return a.score > b.score end return a.e < b.e end)
	return list
end

-- the company's street stations: station group -> { station entity, edge, position }
-- (every street segment is read: kept 10 s, or until the company's next build)
local function myStops(E, ent)
	local api, R = E.api, E.R
	local A = E.G.AI or {}
	local cache = A.stopsCache
	if cache and cache.ent == ent and E.G.frames - cache.frame < 600 then return cache.list end
	local out = {}
	A.stopsCache = { ent = ent, frame = E.G.frames, list = out }
	for _, e in ipairs(R.allEdges()) do
		local c = api.engine.getComponent(e, api.type.ComponentType.BASE_EDGE)
		if c and #c.objects > 0 then
			for k = 1, #c.objects do
				local eo = c.objects[k][1]
				if ownerOf(E, eo) == ent and api.engine.getComponent(eo, api.type.ComponentType.STATION) then
					local okg, sg = pcall(function() return api.engine.system.stationGroupSystem.getStationGroup(eo) end)
					local a, b = E.nodePosition(c.node0), E.nodePosition(c.node1)
					if okg and sg and a and b then
						out[#out + 1] = { station = eo, group = sg, edge = e, pos = { x = (a.x + b.x) / 2, y = (a.y + b.y) / 2, z = (a.z + b.z) / 2 } }
					end
				end
			end
		end
	end
	return out
end

local function myDepots(E, ent)
	local api, R = E.api, E.R
	local out = {}
	for _, e in ipairs(R.entitiesWith("CONSTRUCTION")) do
		local c = api.engine.getComponent(e, api.type.ComponentType.CONSTRUCTION)
		if c and #c.depots > 0 and ownerOf(E, e) == ent and tostring(c.fileName):find("road", 1, true) then
			local m = E.C.marshal(c.transf)
			out[#out + 1] = { con = e, depot = c.depots[1], pos = { x = m[13], y = m[14], z = m[15] } }
		end
	end
	return out
end

-- Road garages (road_depot.con, not the maintenance stations: they have no exit) whose entrance is joined to the streets: the
-- company's own first, else any other company's (open to the others by default, for a fee), the nearest to a point
local function garagesNear(E, ent, p, maxD)
	local api, R = E.api, E.R
	local segmap = api.engine.system.streetSystem.getNode2SegmentMap()
	local list = {}
	for _, e in ipairs(R.entitiesWith("CONSTRUCTION")) do
		local c = api.engine.getComponent(e, api.type.ComponentType.CONSTRUCTION)
		if c and #c.depots > 0 and tostring(c.fileName):find("road_depot", 1, true) and #c.frozenEdges > 0 then
			local vd = api.engine.getComponent(c.depots[1], api.type.ComponentType.VEHICLE_DEPOT)
			local be = api.engine.getComponent(c.frozenEdges[1], api.type.ComponentType.BASE_EDGE)
			local joined = be and (#(segmap[be.node0] or {}) > 1 or #(segmap[be.node1] or {}) > 1)
			if vd and #vd.outNodes > 0 and joined then
				local m = E.C.marshal(c.transf)
				local pos = { x = m[13], y = m[14], z = m[15] }
				local d = dist(pos, p)
				local own = ownerOf(E, e) == ent
				if d < maxD then list[#list + 1] = { con = e, depot = c.depots[1], pos = pos, d = d, own = own, rank = d - (own and 100000 or 0) } end
			end
		end
	end
	table.sort(list, function(a, b) if a.rank ~= b.rank then return a.rank < b.rank end return a.con < b.con end)
	return list
end

-- a depot whose lanes reach the streets (an exit node): a vehicle of a depot without one, sent to a line, stopped the simulation
local function depotLinked(E, depot)
	local ok, n = pcall(function() return #E.api.engine.getComponent(depot, E.api.type.ComponentType.VEHICLE_DEPOT).outNodes end)
	return ok and n and n > 0
end

local function myLines(E, ent)
	local api, R = E.api, E.R
	local out = {}
	for _, l in ipairs(R.entitiesWith("LINE")) do
		if ownerOf(E, l) == ent then
			local lc = api.engine.getComponent(l, api.type.ComponentType.LINE)
			local groups = {}
			for k = 1, #lc.stops do groups[#groups + 1] = lc.stops[k].stationGroup end
			out[#out + 1] = { e = l, groups = groups }
		end
	end
	return out
end

local function myVehicles(E, ent)
	local api, R = E.api, E.R
	local out = {}
	for _, v in ipairs(R.entitiesWith("TRANSPORT_VEHICLE")) do
		if ownerOf(E, v) == ent then
			local tv = api.engine.getComponent(v, api.type.ComponentType.TRANSPORT_VEHICLE)
			out[#out + 1] = { e = v, line = tv and tv.line or -1 }
		end
	end
	return out
end

-- the best bus on sale this year: most seats, then the newest
local function bestBus(E)
	local api = E.api
	local year = currentYear(E)
	local best
	for id, name in pairs(api.res.modelRep.getAll()) do
		if tostring(name):find("/vehicle/bus/", 1, true) then
			local m = api.res.modelRep.get(id)
			local md = m and m.metadata
			local av = md and md.availability
			local from, to = av and av.yearFrom or 0, av and av.yearTo or 0
			if from <= year and (to == 0 or to > year) then
				local seats = 0
				pcall(function()
					for _, comp in ipairs(md.transportVehicle.compartments) do
						for _, lc in ipairs(comp.loadConfigs) do seats = math.max(seats, lc.cargoEntry.capacity or 0) end
					end
				end)
				if seats > 0 and (not best or seats > best.seats or (seats == best.seats and from > best.from)) then
					best = { id = id, name = name, seats = seats, from = from }
				end
			end
		end
	end
	return best, year
end

-- ------------------------------------------------------------------ acting (as a player would, for the company)

-- a command as the interface sends it: stamped, shipped and applied by every game for the company
local function act(E, coId, fn, margs)
	local A = E.G.AI
	E.R.translateOut(fn, margs, E.G.rev)
	A.reqId = (A.reqId or 0) + 1
	E.C.appendFile(E.C.DIR .. E.BS .. "ui.log", E.C.line("act_req", { tok = "ai", id = A.reqId, fn = fn, args = margs, co = coId }))
end

-- An entry of the companies' journal, on every game (the MPFever window's AI tab and the chat, see the bridge's H.aijournal):
-- what (kind), where (pos, for its "Show" button), and up to two words (a name, a model). MPFEVER_AIJOURNAL=0: none.
local function journal(E, coId, kind, pos, a, b)
	if os.getenv("MPFEVER_AIJOURNAL") == "0" then return end
	local p = { t = E.gameTime(), co = coId, kind = kind, a = a, b = b }
	if pos then p.x, p.y, p.z = math.floor(pos.x + 0.5), math.floor(pos.y + 0.5), math.floor((pos.z or 0) + 0.5) end
	pcall(E.send, "aijournal", p)
	if E.H and E.H.aijournal then pcall(E.H.aijournal, E.G.me, p) end
end

-- where a depot stands (its construction's place), nil if unknown
local function depotPos(E, depot)
	local api, R = E.api, E.R
	for _, e in ipairs(R.entitiesWith("CONSTRUCTION")) do
		local c = api.engine.getComponent(e, api.type.ComponentType.CONSTRUCTION)
		if c and #c.depots > 0 then
			for k = 1, #c.depots do
				if c.depots[k] == depot then local m = E.C.marshal(c.transf); return { x = m[13], y = m[14], z = m[15] } end
			end
		end
	end
	return nil
end

-- bits as the native module reports a tool's Context (see the replays): 1 buildings gathered, 2 terrain aligned, 4 street graph
-- cleaned up, 32 known. The depot tool builds with 39: without the clean-up the maintenance station's lanes were never linked
-- to the street (no exit node), and a bus of it sent to a line stopped the simulation of every game.
local CTX_STOP, CTX_DEPOT = 32, 39
local function context(E, ent, bits)
	local api = E.api
	local ctx = api.type.Context.new()
	bits = bits or CTX_STOP
	ctx.gatherBuildings = bits % 2 == 1
	ctx.checkTerrainAlignment = math.floor(bits / 2) % 2 == 1
	ctx.cleanupStreetGraph = math.floor(bits / 4) % 2 == 1
	ctx.gatherFields = true
	ctx.player = ent
	return ctx
end

-- a build as a tool's, for the company: held at its time, shipped with the company's number (the others build it for it)
local function build(E, coId, cmd, what, ctxBits, jr)
	local G = E.G
	local A = G.AI
	A.busy = { what = what, since = G.frames }
	E.deferredSend(cmd, function(res, success)
		local why = ""
		if not success then pcall(function() why = " " .. E.C.ser(E.C.marshal(res.resultProposalData.errorState.messages)) end) end
		L(E, what .. ": " .. (success and "built" or ("refused" .. why)))
		A.busy = nil
		A.stopsCache = nil
		A.lastResult = { what = what, ok = success, frame = G.frames }
		if success and jr then journal(E, coId, jr.kind, jr.pos, jr.a, jr.b) end
		if not success then A.failed = A.failed or {}; A.failed[what] = (A.failed[what] or 0) + 1 end
	end)
	local id = 100000 + G.autoBuildSeq
	G.aiNatCo = G.aiNatCo or {}
	G.aiNatCo[id] = coId
	if ctxBits then G.natCtx = G.natCtx or {}; G.natCtx[id] = ctxBits end
end

-- a stop on a town street segment, as the stop tool builds it (see H.dstop): the segment replaced by a copy carrying the stop
local function buildStop(E, co, seg, n)
	local api, C, G = E.api, E.C, E.G
	local c = api.engine.getComponent(seg, api.type.ComponentType.BASE_EDGE)
	local sp = api.type.SimpleProposal.new()
	local ssp = sp.streetProposal
	local e = api.type.SegmentAndEntity.new()
	e.entity = -1
	e.type = 0
	local cc = e.comp
	cc.node0 = c.node0; cc.node1 = c.node1
	cc.tangent0 = E.vec(c.tangent0); cc.tangent1 = E.vec(c.tangent1)
	if G.autoSegEnds then cc.position0, cc.position1 = G.autoSegEnds(c) end
	cc.type = c.type; cc.typeIndex = c.typeIndex
	cc.roadTemplate = c.roadTemplate; cc.roadStyle = c.roadStyle; cc.roadType = c.roadType
	cc.laneConfigs = c.laneConfigs
	cc.objects = { { -400000000, 1 } }
	e.comp = cc
	local owner = ownerOf(E, seg)
	if type(owner) == "number" and owner >= 0 then
		pcall(function() local po = C.newOf("PlayerOwned"); po.player = owner; e.playerOwned = po end)
	end
	local se = e.streetEdge; se.precedenceNode0 = 2; se.precedenceNode1 = 2; e.streetEdge = se
	local eo = api.type.SimpleStreetProposal.EdgeObject.new()
	eo.edgeEntity = -1
	eo.param = 0.5
	eo.oneWay = false
	eo.left = false
	eo.model = STOP_MODEL
	eo.playerEntity = co.ent
	eo.name = ""
	ssp.edgesToRemove = { seg }
	ssp.edgesToAdd = { e }
	ssp.edgeObjectsToAdd = { eo }
	local ncr = {}
	for _, nd in ipairs({ c.node0, c.node1 }) do
		local okn, nc = pcall(function() return api.engine.getComponent(nd, api.type.ComponentType.BASE_NODE_CONFIG) end)
		if okn and nc then ncr[#ncr + 1] = nd end
	end
	if #ncr > 0 then ssp.nodeConfigsToRemove = ncr end
	sp.streetProposal = ssp
	local cmd = api.cmd.makeWorldBuildProposalCmd(sp, context(E, co.ent, CTX_STOP), false, true, true)
	local pa, pb = E.nodePosition(c.node0), E.nodePosition(c.node1)
	build(E, co.id, cmd, "stop " .. n, CTX_STOP, { kind = "stop", pos = pa and pb and { x = (pa.x + pb.x) / 2, y = (pa.y + pb.y) / 2, z = (pa.z + pb.z) / 2 } or nil })
end

-- free town street segments near a point, the nearest first
local function streetSegmentsNear(E, p, radius, avoid)
	local api, R = E.api, E.R
	local list = {}
	for _, e in ipairs(R.allEdges()) do
		local c = api.engine.getComponent(e, api.type.ComponentType.BASE_EDGE)
		if c and c.type == 0 and #c.objects == 0 and api.engine.getComponent(e, api.type.ComponentType.BASE_EDGE_STREET)
			and tostring(c.roadTemplate):find("/town/", 1, true) then
			local okC, con = pcall(function() return api.engine.system.streetConnectorSystem.getConstructionEntityForEdge(e) end)
			if not (okC and type(con) == "number" and con >= 0) then
				local a, b = E.nodePosition(c.node0), E.nodePosition(c.node1)
				if a and b then
					local len = math.sqrt((a.x - b.x) ^ 2 + (a.y - b.y) ^ 2)
					local m = { x = (a.x + b.x) / 2, y = (a.y + b.y) / 2, z = (a.z + b.z) / 2 }
					local d = dist(m, p)
					local ok = len > 40 and len < 160 and d < radius
					for _, q in ipairs(avoid or {}) do if dist(m, q) < 120 then ok = false end end
					if ok then list[#list + 1] = { e = e, d = d, a = a, b = b, m = m } end
				end
			end
		end
	end
	table.sort(list, function(x, y) if x.d ~= y.d then return x.d < y.d end return x.e < y.e end)
	return list
end

-- a maintenance station against a street near a point: the first place the engine finds free (dry runs)
local function findDepotPlace(E, co, p)
	local api = E.api
	local V = api.type.Vec4f.new
	local tried = 0
	for _, s in ipairs(streetSegmentsNear(E, p, 700, {})) do
		if tried > 400 then break end
		local dx, dy = s.b.x - s.a.x, s.b.y - s.a.y
		local len = math.sqrt(dx * dx + dy * dy)
		dx, dy = dx / len, dy / len
		for _, side in ipairs({ 1, -1 }) do
			tried = tried + 1
			local nx, ny = -dy * side, dx * side
			local off = 23
			local m = { x = s.m.x + nx * off, y = s.m.y + ny * off }
			m.z = E.groundZ(m.x, m.y, s.m.z)
			local sp = api.type.SimpleProposal.new()
			local ce = api.type.SimpleProposal.ConstructionEntity.new()
			ce.fileName = DEPOT_FILE
			ce.params = { seed = 1, year = currentYear(E), modules = {} }
			ce.transf = api.type.Mat4f.new(V(ny, -nx, 0, 0), V(nx, ny, 0, 0), V(0, 0, 1, 0), V(m.x, m.y, m.z, 1))
			ce.playerEntity = co.ent
			pcall(function() ce.name = "" end)
			sp.constructionsToAdd = { ce }
			local okd, pd = pcall(function() return api.engine.util.proposal.makeProposalData(sp, context(E, co.ent, CTX_DEPOT)) end)
			if okd and pd and #pd.errorState.messages == 0 and not pd.errorState.critical then
				return sp, s, pd.costs
			end
		end
	end
	return nil
end

-- ------------------------------------------------------------------ a garage, as the depot tool builds it

-- The depot tool's build of a road garage (road_depot.con), as MPFever captures it from a player (and every game replays it,
-- see replayNativeConstruction in the bridge): the town street split at the junction, the garage's entrance stretched from the
-- street's axis to the garage (42 m in front of the construction's origin, its own entrance ends at 35), the entrance's inner
-- node frozen to the construction. A script's proposal of the garage alone was never joined to the streets ("Construction
-- impossible" at a street node; no exit when left apart). Sent as a native act that every game, this one too, replays at its
-- time, as a player's garage is replayed.
local GARAGE_FILE = "::/depots/road/road_depot/road_depot.con"
local ENTRANCE_TPL = "::/infrastructure/street/constructions/entrance_new.street_template"

local function v3(p) return { x = p.x, y = p.y, z = p.z, __vec = true } end

-- straight town street segments near a point where a garage stands free (a dry run of the garage alone, its footprint)
local function garagePlaces(E, co, p, maxD)
	local api, C, R = E.api, E.C, E.R
	local V = api.type.Vec4f.new
	local out = {}
	local tried = 0
	for _, s in ipairs(streetSegmentsNear(E, p, maxD, {})) do
		if tried > 60 or #out >= 1 then break end
		local c = api.engine.getComponent(s.e, api.type.ComponentType.BASE_EDGE)
		local len = math.sqrt((s.b.x - s.a.x) ^ 2 + (s.b.y - s.a.y) ^ 2)
		local t0 = c.tangent0
		local tl = math.sqrt(t0.x ^ 2 + t0.y ^ 2)
		local straight = tl > 0 and math.abs((t0.x * (s.b.x - s.a.x) + t0.y * (s.b.y - s.a.y)) / (tl * len)) > 0.995
		if straight and len > 50 then
			local dx, dy = (s.b.x - s.a.x) / len, (s.b.y - s.a.y) / len
			for _, side in ipairs({ 1, -1 }) do
				tried = tried + 1
				local nx, ny = -dy * side, dx * side
				local P = { x = (s.a.x + s.b.x) / 2, y = (s.a.y + s.b.y) / 2, z = (s.a.z + s.b.z) / 2 }
				local O = { x = P.x + nx * 42, y = P.y + ny * 42, z = P.z }
				-- (only on level ground: the garage, its entrance and the street end within 3 m of height, see freight's garages)
				local lo, hi = P.z, P.z
				for _, q in ipairs({ { 42, 0 }, { 21, 0 }, { 60, 0 }, { 42, 15 }, { 42, -15 }, { 60, 15 }, { 60, -15 } }) do
					local x, y = P.x + nx * q[1] + dx * q[2], P.y + ny * q[1] + dy * q[2]
					local z = E.groundZ(x, y, P.z)
					if z < lo then lo = z end
					if z > hi then hi = z end
				end
				local level = hi - lo <= 3
				local sp = api.type.SimpleProposal.new()
				local ce = api.type.SimpleProposal.ConstructionEntity.new()
				ce.fileName = GARAGE_FILE
				ce.params = { seed = 0, year = currentYear(E), modules = {} }
				ce.transf = api.type.Mat4f.new(V(ny, -nx, 0, 0), V(nx, ny, 0, 0), V(0, 0, 1, 0), V(O.x, O.y, O.z, 1))
				ce.playerEntity = co.ent
				pcall(function() ce.name = "" end)
				sp.constructionsToAdd = { ce }
				local okd, pd = pcall(function() return api.engine.util.proposal.makeProposalData(sp, context(E, co.ent, CTX_STOP)) end)
				-- (its entrance touches the street it joins: a collision with that segment only is no obstacle, the tool's build
				-- replaces that segment)
				local free = level and okd and pd and not pd.errorState.critical
				if free and #pd.errorState.messages > 0 then
					local only = true
					pcall(function()
						for _, x in ipairs(pd.collisionInfo.collisionEntities) do
							if x.entity ~= s.e and x.entity ~= c.node0 and x.entity ~= c.node1 then only = false end
						end
						for _, msg in ipairs(pd.errorState.messages) do if msg ~= "Collision" then only = false end end
					end)
					free = only
				end
				if free then
					out[#out + 1] = { seg = s.e, c = c, a = s.a, b = s.b, P = P, O = O, n = { x = nx, y = ny }, side = side }
					break
				end
			end
		end
	end
	return out
end

local function marshalSeg(E, entity, comp, n0, n1, p0, p1, tpl, lanes, owner, locked)
	local t = { x = p1.x - p0.x, y = p1.y - p0.y, z = p1.z - p0.z, __vec = true }
	return {
		entity = entity, type = 0,
		params = { precedenceNode0 = 2, precedenceNode1 = 2, __ud = true },
		streetEdge = { precedenceNode0 = 2, precedenceNode1 = 2, __ud = true },
		playerOwned = owner and { player = owner, __ud = true } or nil,
		comp = { type = 0, typeIndex = -1, node0 = n0, node1 = n1, position0 = v3(p0), position1 = v3(p1), tangent0 = t, tangent1 = t,
			roadTemplate = tpl, roadStyle = comp and comp.roadStyle or nil, roadType = comp and comp.roadType or 1, laneConfigs = lanes,
			edgeDecorations = {}, distance = 0, objects = {}, roadDevelopmentLocked = locked or false, __ud = true },
		__ud = true,
	}
end

local function garageCapture(E, co, place)
	local api, C, G = E.api, E.C, E.G
	local c = place.c
	local P, O, n = place.P, place.O, place.n
	local M = { x = P.x + n.x * 21.74, y = P.y + n.y * 21.74, z = P.z }
	local cm = C.marshal(c)
	local townLanes = cm.laneConfigs
	local entLanes = C.marshal(C.templateLanes(ENTRANCE_TPL)) or townLanes
	local addedSegments = {
		-- (the entrance takes the street's style, as in the tool's build: without one the engine threw on the command)
		marshalSeg(E, -3, { roadStyle = cm.roadStyle, roadType = cm.roadType }, -1, -2, P, M, ENTRANCE_TPL, entLanes, co.ent, true),
		marshalSeg(E, -4, cm, c.node0, -1, place.a, P, c.roadTemplate, townLanes, nil, false),
		marshalSeg(E, -5, cm, -1, c.node1, P, place.b, c.roadTemplate, townLanes, nil, false),
	}
	local ncr = {}
	for _, nd in ipairs({ c.node0, c.node1 }) do
		local okn, nc = pcall(function() return api.engine.getComponent(nd, api.type.ComponentType.BASE_NODE_CONFIG) end)
		if okn and nc then ncr[#ncr + 1] = nd end
	end
	local m = {
		toAdd = { { name = "", params = { seed = 0, year = currentYear(E), modules = {} }, fileName = GARAGE_FILE, segmentsBefore = 0,
			transf = { n.y, -n.x, 0, 0, n.x, n.y, 0, 0, 0, 0, 1, 0, O.x, O.y, O.z, 1, __mat = true }, playerEntity = co.ent, frozenNodes = { 1 } } },
		toRemove = {}, old2new = {}, old2newByRank = {},
		proposal = {
			addedNodes = { { entity = -1, comp = { position = v3(P), __ud = true }, __ud = true }, { entity = -2, comp = { position = v3(M), __ud = true }, __ud = true } },
			addedSegments = addedSegments,
			removedSegments = { { entity = place.seg, type = 0, comp = cm, params = { precedenceNode0 = 2, precedenceNode1 = 2, __ud = true },
				streetEdge = { precedenceNode0 = 2, precedenceNode1 = 2, __ud = true }, __ud = true } },
			removedNodes = {}, nodeConfigsToAdd = {}, nodeConfigsToRemove = ncr, edgeObjectsToAdd = {}, edgeObjectsToRemove = {},
		},
	}
	local margs = { n = 4, [1] = m, [2] = { __player = true }, [3] = false, [4] = true }
	E.R.translateOut("makeWorldBuildProposalCmd", margs, G.rev)
	return margs
end

local function buildGarage(E, co, place)
	local G = E.G
	local A = G.AI
	local margs = garageCapture(E, co, place)
	local now = E.gameTime()
	G.oseq = G.oseq + 1
	local a = { fn = "makeWorldBuildProposalCmd", args = margs, origin = G.me, oseq = G.oseq, uid = G.me .. ":" .. G.oseq,
		at = E.stampFor(now) + E.STEP, native = true, co = co.id, ctx = CTX_DEPOT }
	E.send("act", a)
	a.recvFrame = G.frames
	G.nativeQueue[#G.nativeQueue + 1] = a
	A.busy = { what = "garage on segment " .. place.seg, since = G.frames, until_ = G.frames + 600 }
	L(E, "garage requested on segment " .. place.seg .. " (" .. a.uid .. ", for t=" .. a.at .. ")")
	journal(E, co.id, "garage", place.O)
end

-- ------------------------------------------------------------------ the plan

-- the stops a town project wants: near its residential, commercial and industrial centres
local USES = { "RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL" }

-- Where a town's line stops: its residential, commercial and industrial centres, at least 300 m apart; when they are fewer than
-- two, the farthest point of the town's streets from the first (a company stop already there first, so that the choice stays the
-- same once built)
local function townTargets(E, town, stops, rich)
	local api = E.api
	local pts = {}
	for _, u in ipairs(USES) do
		local p = centre(E, town, api.type.enum.LandUseType[u])
		if p then
			local dup = false
			for _, q in ipairs(pts) do if dist(p, q.p) < 300 then dup = true end end
			if not dup then pts[#pts + 1] = { use = u, p = p } end
		end
	end
	-- (a town's own line: also a ring of points 450 m around its residential centre where the town has streets, so that the line
	-- crosses the town as the players' well filled lines do; then the points chained, each to the nearest one left)
	if rich and pts[1] then
		local c = pts[1].p
		for k = 0, 5 do
			local a = k * math.pi / 3
			local q = { x = c.x + math.cos(a) * 450, y = c.y + math.sin(a) * 450, z = c.z }
			local near = streetSegmentsNear(E, q, 150, {})[1]
			if near then
				local dup = false
				for _, o in ipairs(pts) do if dist(near.m, o.p) < 300 then dup = true end end
				if not dup then pts[#pts + 1] = { use = "RING" .. k, p = near.m } end
			end
		end
		-- (chained from the point farthest from the centre)
		local start, sd = 1, -1
		for i, o in ipairs(pts) do local d = dist(o.p, c); if d > sd then start, sd = i, d end end
		local chain, left = { table.remove(pts, start) }, pts
		while #left > 0 do
			local last = chain[#chain].p
			local bi, bd = 1, nil
			for i, o in ipairs(left) do local d = dist(o.p, last); if not bd or d < bd then bi, bd = i, d end end
			chain[#chain + 1] = table.remove(left, bi)
		end
		return chain
	end
	if #pts == 1 then
		local first = pts[1].p
		local far
		for _, s in ipairs(stops) do
			local d = dist(s.pos, first)
			if d > 350 and d < 800 and (not far or d > far.d) then far = { p = s.pos, d = d } end
		end
		if not far then
			for _, s in ipairs(streetSegmentsNear(E, first, 750, {})) do
				if s.d > 400 and (not far or s.d > far.d) then far = { p = s.m, d = s.d } end
			end
		end
		if far then pts[#pts + 1] = { use = "EDGE", p = far.p } end
	end
	return pts
end

local function townProject(E, co, town, stops)
	local want = {}
	local A = E.G.AI
	local drop = A.dropPoint or {}
	-- (computed once: a point moves once a stop takes its street segment, and the line would follow a moving target)
	A.targets = A.targets or {}
	A.targets[town] = A.targets[town] or townTargets(E, town, stops, true)
	for _, w in ipairs(A.targets[town]) do if not drop[town .. ":" .. w.use] then want[#want + 1] = w end end
	-- a wanted stop is there when one of the company's stops stands within 200 m of its point; one stop serves one point only
	local have, missing, used = {}, {}, {}
	for _, w in ipairs(want) do
		local found, fd
		for _, s in ipairs(stops) do
			local d = dist(s.pos, w.p)
			if d < 200 and not used[s.group] and (not fd or d < fd) then found, fd = s, d end
		end
		if found then used[found.group] = true; have[#have + 1] = { want = w, stop = found } else missing[#missing + 1] = w end
	end
	return have, missing, want
end

local function lineFor(E, lines, groups)
	for _, l in ipairs(lines) do
		local all = true
		for _, g in ipairs(groups) do
			local f = false
			for _, x in ipairs(l.groups) do if x == g then f = true end end
			if not f then all = false end
		end
		if all then return l end
	end
	return nil
end

local function createLine(E, co, groups, town, name)
	local api, C, R = E.api, E.C, E.R
	-- (a bus line of the savegame as the template of the line's fields, its stops replaced)
	local template
	for _, l in ipairs(R.entitiesWith("LINE")) do
		local m = C.marshal(api.engine.getComponent(l, api.type.ComponentType.LINE))
		if m and m.vehicleInfo and m.vehicleInfo.transportModes and m.vehicleInfo.transportModes[3] == true then template = m break end
	end
	if not template then
		local ln = api.type.Line.new()
		template = C.marshal(ln)
	end
	local stop0 = template.stops and template.stops[1]
	local stops = {}
	-- there and back: A B C B
	local order = {}
	for i = 1, #groups do order[#order + 1] = groups[i] end
	for i = #groups - 1, 2, -1 do order[#order + 1] = groups[i] end
	for i, g in ipairs(order) do
		local s = {}
		if stop0 then for k, v in pairs(stop0) do s[k] = v end end
		s.stationGroup = g
		s.station = 0
		s.terminal = 0
		-- (the group's other stations and terminals as alternatives: the engine takes the one on the bus's side of the street)
		local alt = {}
		pcall(function()
			local sg = api.engine.getComponent(g, api.type.ComponentType.STATION_GROUP)
			for k = 1, #sg.stations do
				local sc = api.engine.getComponent(sg.stations[k], api.type.ComponentType.STATION)
				for t = 1, #sc.terminals do
					if not (k == 1 and t == 1) then alt[#alt + 1] = { station = k - 1, terminal = t - 1, __ud = true } end
				end
			end
		end)
		s.alternativeTerminals = alt
		s.waypoints = {}
		s.__ud = true
		stops[i] = s
	end
	template.stops = stops
	name = name or (AINAME .. " " .. townName(E, town))
	act(E, co.id, "makeLineCreateCmd", { n = 4, [1] = name, [2] = C.marshal(api.type.Vec3f.new(0.2, 0.5, 0.9)), [3] = co.ent, [4] = template })
	-- (its growth waits until this line had time to fill, see mayExpand)
	E.G.AI.lastNewAt = E.gameTime()
	local jpos = centre(E, town, E.api.type.enum.LandUseType.RESIDENTIAL)
	E.G.AI.busy = { what = "line " .. name, since = E.G.frames, linesBefore = #myLines(E, co.ent), jr = { kind = "line", pos = jpos, a = name } }
	L(E, "line requested: " .. name .. " with " .. #order .. " stops")
end

local function buyBus(E, co, depot)
	local bus, year = bestBus(E)
	if not bus then L(E, "no bus on sale in " .. year); return false end
	local cfg = {
		vehicles = { { part = { modelId = bus.id, reversed = false, compartment2loadConfig = { { loadConfigIndex = 0, cargoTypeId = 0, __ud = true } },
			color = { x = -1, y = -1, z = -1, __vec = true }, __ud = true }, purchaseTime = 0, maintenanceChange = 0, maintenanceState = 1,
			autoLoadConfig = { true }, __ud = true } },
		vehicleGroups = { 1 }, muFileNames = {}, __ud = true }
	act(E, co.id, "makeVehicleBuyCmd", { n = 3, [1] = co.ent, [2] = depot, [3] = cfg })
	E.G.AI.busy = { what = "bus " .. bus.name, since = E.G.frames, vehBefore = #myVehicles(E, co.ent), moneyBefore = balanceOf(E, co.ent),
		jr = { kind = "bus", pos = depotPos(E, depot), a = tostring(bus.name):match("([^/]+)%.mdl$") or bus.name } }
	L(E, "bus requested: " .. bus.name .. " (" .. bus.seats .. " seats, " .. year .. ") at depot " .. depot)
	return true
end

-- ------------------------------------------------------------------ running the lines

-- passengers' share of the line's seats in use (nil if unknown)
local function lineUse(E, line)
	local ok, u = pcall(function() return E.api.engine.util.line.getLineCapacityUsages(line, false) end)
	if not ok or type(u) ~= "table" then return nil end
	local used, total = 0, 0
	for _, x in pairs(u) do used = used + (x.used or 0); total = total + (x.capacity or x.total or 0) end
	if total <= 0 then return nil end
	return used / total
end

-- a line's earnings less its upkeep over the last two game months (4000 ms of game time a day), nil if unknown
local function lineBalance(E, line)
	local now = E.gameTime()
	local ok, b = pcall(function() return E.api.engine.util.finance.calculateBalance({ line }, now - 240000, now, true) end)
	return ok and type(b) == "number" and b or nil
end

-- The result of the company's lines together over the last two months (earnings less upkeep), read at most every 10 s; nil
-- when no line has one yet
local function companyResult(E, lines)
	local A = E.G.AI
	if A.opAt and E.G.frames - A.opAt < 600 then return A.opResult end
	A.opAt = E.G.frames
	local sum, known = 0, 0
	for _, l in ipairs(lines) do
		local b = lineBalance(E, l.e)
		if b then sum = sum + b; known = known + 1 end
	end
	A.opResult = known > 0 and sum or nil
	return A.opResult
end

-- (0.5.14) Whether the company may open something new (stops, a line, a garage for a new line): its first lines freely (the
-- level's bootstrap); then not before its last new line had time to fill (settle, game time), and only while its lines earn
-- together or it holds plenty of money besides its reserve (freeCash). The tests of 2026-10-29: three companies opened 6 to 10
-- lines in minutes with their 2 million, ran into debt, sold every vehicle and ended at -1.6 million. Vehicles for its lines
-- that are full are not held back. MPFEVER_AIGOVERN=0: as before.
local function mayExpand(E, co, lines, money)
	if os.getenv("MPFEVER_AIGOVERN") == "0" then return true end
	local A = E.G.AI
	local now = E.gameTime()
	local why
	if A.lastNewAt and A.lastNewAt <= now and now - A.lastNewAt < (LV.settle or 0) then
		why = "its last new line fills (" .. math.floor((LV.settle - (now - A.lastNewAt)) / 4000) .. " day(s) left)"
	elseif #lines >= (LV.bootstrap or 0) and money < RESERVE + (LV.freeCash or 0) then
		local r = companyResult(E, lines)
		if r == nil or r < 0 then why = "its lines do not earn yet (" .. tostring(r and math.floor(r)) .. " over 2 months)" end
	end
	if why then
		if E.G.frames - (A.waitSaid or -100000) > 3600 then A.waitSaid = E.G.frames; L(E, "growth waits: " .. why) end
		return false
	end
	return true
end

-- the seats in use, sampled every 20 s: the mean of the last 6 samples (one look at a bus in a terminus said 2 %, the next 33 %)
local function sampleUse(E, lines)
	local G = E.G
	local A = G.AI
	if G.frames - (A.sampleAt or -100000) < 1200 then return end
	A.sampleAt = G.frames
	A.useHist = A.useHist or {}
	for _, l in ipairs(lines) do
		local h = A.useHist[l.e] or {}
		local u = lineUse(E, l.e)
		if u then h[#h + 1] = u; while #h > 6 do table.remove(h, 1) end end
		A.useHist[l.e] = h
	end
end

local function meanUse(E, line)
	local h = (E.G.AI.useHist or {})[line]
	if not h or #h == 0 then return nil end
	local s = 0
	for _, u in ipairs(h) do s = s + u end
	return s / #h
end

-- the company's lines the engine reports a problem for (a stop no vehicle reaches...)
local function problemLines(E, ent)
	local out = {}
	pcall(function()
		for _, p in ipairs(E.api.engine.util.line.getLineProblems()) do
			if ownerOf(E, p[1]) == ent then out[p[1]] = p[2] end
		end
	end)
	return out
end

-- one look at the lines every 2 minutes: a bus more on a full line, a line with a problem given up
local function sellVehicle(E, co, v, why)
	act(E, co.id, "makeVehicleSellCmd", { n = 1, [1] = { v } })
	E.G.AI.busy = { what = "sale of vehicle " .. v, since = E.G.frames, until_ = E.G.frames + 120 }
	L(E, "vehicle " .. v .. " sold (" .. why .. ")")
	journal(E, co.id, "sold", nil)
end

-- (freight, see below: a line's trucks and cargo)
local buyFor, freightOf

local function cargoName(E, id)
	local n = tostring(id)
	pcall(function() n = E.api.res.cargoTypeRep.getName(id) end)
	return n
end

local function manageLines(E, co, lines, vehicles, money)
	local G = E.G
	local A = G.AI
	-- (in debt: a bus of the emptiest line sold every 20 s until the account is back above zero)
	local period = money < 0 and 1200 or 7200
	if G.frames - (A.manageAt or -100000) < period then return false end
	A.manageAt = G.frames
	local probs = problemLines(E, co.ent)
	A.emptyRuns = A.emptyRuns or {}
	local emptiest, eUse
	-- (in debt, only the vehicles of a line that loses money are sold: selling the buses of the lines that earned left the companies
	-- of a test of 2026-10-29 at -1.6 million with lines and no vehicle, earning nothing any more. MPFEVER_AIDEBTSELL=0: as before,
	-- the emptiest line's whatever it earns)
	local losingOnly = os.getenv("MPFEVER_AIDEBTSELL") ~= "0"
	for _, l in ipairs(lines) do
		local n, last = 0, nil
		for _, v in ipairs(vehicles) do if v.line == l.e then n = n + 1; last = v.e end end
		local use = meanUse(E, l.e) or lineUse(E, l.e) or 0
		local bal = lineBalance(E, l.e)
		if n > 0 and (not losingOnly or (bal ~= nil and bal < 0)) and (not eUse or use < eUse) then emptiest, eUse = { line = l, last = last, n = n }, use end
		-- (a freight line: its trucks come back empty, and a producer starts slowly once served: emptier, and given more time)
		l.freight = os.getenv("MPFEVER_AIFREIGHT") ~= "0" and freightOf(E, l) or nil
		local emptyUse, emptyLooks = l.freight and 0.04 or 0.08, l.freight and 6 or 3
		-- (empty: few seats used on average, and losing money when its balance is known)
		-- (a freight line that never had its first trucks yet is not empty: it waits for them, see the first trucks in step)
		local waitsTrucks = l.freight and n == 0 and ((A.trucksFor or {})[l.e] or 0) == 0
		local empty = not waitsTrucks and (n == 0 or (use < emptyUse and (bal == nil or bal <= 0)))
		A.emptyRuns[l.e] = empty and ((A.emptyRuns[l.e] or 0) + 1) or 0
		l.use, l.bal = use, bal
		-- (a line that stays empty three looks in a row: its buses sold one by one, the line given up with the last)
		if A.emptyRuns[l.e] >= emptyLooks and n > 0 and period == 7200 then
			L(E, string.format("line %d empty for %d looks: a bus less", l.e, A.emptyRuns[l.e]))
			sellVehicle(E, co, last, "empty line " .. l.e)
			return true
		end
		-- (the line itself goes once its last bus is sold: the engine keeps a line that still has a vehicle)
		if A.emptyRuns[l.e] >= emptyLooks and n == 0 and period == 7200 then
			L(E, "line " .. l.e .. " given up (empty)")
			local ln = tostring(l.e)
			pcall(function() ln = E.api.engine.getComponent(l.e, E.api.type.ComponentType.NAME).name end)
			journal(E, co.id, "giveup", nil, ln)
			act(E, co.id, "makeLineDestroyCmd", { n = 1, [1] = l.e })
			A.badPair = A.badPair or {}
			if l.groups[1] and l.groups[2] then A.badPair[math.min(l.groups[1], l.groups[2]) .. "-" .. math.max(l.groups[1], l.groups[2])] = true end
			-- (a round: its two ends too, the route it served is not made again)
			local g1, gN = l.groups[1], l.groups[#l.groups]
			if g1 and gN and g1 ~= gN then A.badPair[math.min(g1, gN) .. "-" .. math.max(g1, gN)] = true end
			-- (its stops are demolished afterwards, and a town whose own line it was gets no new one; not for a freight line, whose
			-- town stop may be a stop of the town's bus line)
			A.deadGroups = A.deadGroups or {}
			if not l.freight then for _, g in ipairs(l.groups) do A.deadGroups[g] = true end end
			-- (0.5.14: only for a line of one town; a line between two towns that failed says nothing of either town's own line,
			-- and both towns were left for the whole session. MPFEVER_AIRETRY=0: as before)
			local mine = {}
			for _, g in ipairs(l.groups) do mine[g] = true end
			local touched, nTouched = {}, 0
			for town, pts in pairs(A.targets or {}) do
				for _, s in ipairs(myStops(E, co.ent)) do
					for _, w in ipairs(pts) do
						if mine[s.group] and dist(s.pos, w.p) < 200 and not touched[town] then touched[town] = true; nTouched = nTouched + 1 end
					end
				end
			end
			if nTouched <= 1 or os.getenv("MPFEVER_AIRETRY") == "0" then
				for town, pts in pairs(A.targets or {}) do
					for _, s in ipairs(myStops(E, co.ent)) do
						for _, w in ipairs(pts) do
							if A.deadGroups[s.group] and dist(s.pos, w.p) < 200 then A.skipTown = A.skipTown or {}; A.skipTown[town] = true end
						end
					end
				end
			end
			A.busy = { what = "line " .. l.e .. " destroyed", since = G.frames, until_ = G.frames + 120 }
			return true
		end
	end
	-- the stops of a given up line that no other line of the company uses: demolished one by one (their upkeep for nothing). OFF
	-- (MPFEVER_AIDEMOLISH=1: on): a stop demolished frees its entity, MPFever's free-id order (the smallest first) gives that id
	-- to a new octree node a step later, and the interface's copy of the world, which still had the stop's log book under that
	-- id, stopped both games ("LogBookSystem::EntityAdded isSupported", test rel052 of 2026-10-28)
	if A.deadGroups and period == 7200 and os.getenv("MPFEVER_AIDEMOLISH") == "1" then
		local used = {}
		for _, l in ipairs(lines) do for _, g in ipairs(l.groups) do used[g] = true end end
		for _, s in ipairs(myStops(E, co.ent)) do
			if A.deadGroups[s.group] and not used[s.group] then
				local api = E.api
				local sp = api.type.SimpleProposal.new()
				local ssp = sp.streetProposal
				ssp.edgeObjectsToRemove = { s.station }
				sp.streetProposal = ssp
				L(E, "stop " .. s.station .. " of a given up line demolished")
				build(E, co.id, api.cmd.makeWorldBuildProposalCmd(sp, context(E, co.ent, CTX_STOP), false, true), "demolition of stop " .. s.station, CTX_STOP)
				return true
			end
		end
	end
	if money < 0 and emptiest and #vehicles > 0 then
		sellVehicle(E, co, emptiest.last, "in debt, emptiest line " .. emptiest.line.e)
		return true
	end
	-- (in debt with no line losing money: a loan, as a player would take, rather than waiting in debt; one ask every 2 minutes at
	-- most, the game refuses more than its loans' maximum. MPFEVER_AILOAN=0: none)
	if money < 0 and losingOnly and os.getenv("MPFEVER_AILOAN") ~= "0" and G.frames - (A.loanAsked or -100000) > 7200 then
		A.loanAsked = G.frames
		act(E, co.id, "makeScriptingSendEventCmd", { n = 4, [1] = "mpfever", [2] = "mpfever", [3] = "ai_loan", [4] = {} })
		A.busy = { what = "loan", since = G.frames, until_ = G.frames + 120 }
		L(E, "in debt (" .. math.floor(money) .. "): a loan asked")
		return true
	end
	-- (0.5.14) money to spare: its oldest loan repaid, if it has one (the simulation decides on its own balance, the same on every
	-- game, see the bridge's ai_repay), at most every 6 game months. Before, a loan was never repaid and its money was spent as
	-- profit. MPFEVER_AIREPAY=0: never
	local nowT = E.gameTime()
	if os.getenv("MPFEVER_AIREPAY") ~= "0" and money > 2 * RESERVE + 1000000 and (not A.repayAt or A.repayAt > nowT or nowT - A.repayAt > 720000) then
		A.repayAt = nowT
		act(E, co.id, "makeScriptingSendEventCmd", { n = 4, [1] = "mpfever", [2] = "mpfever", [3] = "ai_repay", [4] = { keep = math.floor(RESERVE) } })
		A.busy = { what = "loan repaid", since = G.frames, until_ = G.frames + 120 }
		L(E, "money to spare (" .. math.floor(money) .. "): its oldest loan repaid if it has one")
		return true
	end
	local reinvest = os.getenv("MPFEVER_AIREINVEST") ~= "0"
	local bestBuy = nil
	for _, l in ipairs(lines) do
		local n, last = 0, nil
		for _, v in ipairs(vehicles) do if v.line == l.e then n = n + 1; last = v.e end end
		local use = l.use
		L(E, string.format("line %d: %d bus(es), %s of the seats used on average, balance of the last 2 months %s%s", l.e, n,
			use and (math.floor(use * 100) .. "%") or "?", l.bal and tostring(math.floor(l.bal)) or "?", probs[l.e] and (", problem " .. tostring(probs[l.e])) or ""))
		if probs[l.e] and n > 0 and (A.problemSeen or {})[l.e] then
			-- (a problem seen twice in a row: the line is given up, its buses go to the company's other lines)
			L(E, "line " .. l.e .. " given up (problem " .. tostring(probs[l.e]) .. ")")
			local ln = tostring(l.e)
			pcall(function() ln = E.api.engine.getComponent(l.e, E.api.type.ComponentType.NAME).name end)
			journal(E, co.id, "giveup", nil, ln)
			act(E, co.id, "makeLineDestroyCmd", { n = 1, [1] = l.e })
			-- (its stops are not joined again: keyed by their station groups)
			A.badPair = A.badPair or {}
			if l.groups[1] and l.groups[2] then A.badPair[math.min(l.groups[1], l.groups[2]) .. "-" .. math.max(l.groups[1], l.groups[2])] = true end
			local g1, gN = l.groups[1], l.groups[#l.groups]
			if g1 and gN and g1 ~= gN then A.badPair[math.min(g1, gN) .. "-" .. math.max(g1, gN)] = true end
			return true
		end
		A.problemSeen = A.problemSeen or {}
		A.problemSeen[l.e] = probs[l.e] and true or nil
		-- (0.5.14, Normal and Hard) a line that has run six months and still loses money with more than two vehicles: one vehicle
		-- less after two looks in a row (three on Normal), so that its fleet fits what it carries; before, a losing line kept every
		-- vehicle until the company was in debt, then everything was sold at once. MPFEVER_AIPRUNE=0: as before
		if os.getenv("MPFEVER_AIPRUNE") ~= "0" and LV.name ~= "easy" and period == 7200 then
			A.seenAt = A.seenAt or {}
			local now = E.gameTime()
			if not A.seenAt[l.e] or A.seenAt[l.e] > now then A.seenAt[l.e] = now end
			A.losing = A.losing or {}
			if n > 2 and l.bal and l.bal < 0 and now - A.seenAt[l.e] > 720000 then
				A.losing[l.e] = (A.losing[l.e] or 0) + 1
				if A.losing[l.e] >= (LV.name == "hard" and 2 or 3) then
					A.losing[l.e] = 0
					L(E, string.format("line %d loses money (%d over 2 months) with %d vehicles: one less", l.e, math.floor(l.bal), n))
					sellVehicle(E, co, last, "losing line " .. l.e)
					return true
				end
			else
				A.losing[l.e] = 0
			end
		end
		-- (a freight line: a truck more when the cargo waiting at the producer fills one, or the trucks are full one way)
		local busy = use and use > LV.busUse and n < LV.maxBus
		if l.freight then
			local waiting = 0
			pcall(function() waiting = E.api.engine.system.simEntityAtTerminalSystem.getLineStopSimEntitiesCount(l.e, 0, l.freight.cargo) end)
			busy = n < LV.maxTruck and (waiting >= LV.waiting or (use and use > LV.truckUse))
			if busy then L(E, string.format("line %d: %d %s waiting at the producer", l.e, waiting, cargoName(E, l.freight.cargo))) end
		end
		if busy and money > RESERVE + ((l.freight and A.truckCost or A.busCost) or BUS_COST) then
			if reinvest then
				-- (0.5.14) the busy line that earns the most per vehicle gets the next one; a full line that loses money gets none on
				-- Normal and Hard (each more of its vehicles loses more). MPFEVER_AIREINVEST=0: the first busy line, as before
				local per = (l.bal or 0) / math.max(1, n)
				if (LV.name == "easy" or l.bal == nil or l.bal >= 0) and (not bestBuy or per > bestBuy.per) then bestBuy = { l = l, per = per } end
			else
				local depot = garagesNear(E, co.ent, l.mid or (l.freight and l.freight.from.pos) or { x = 0, y = 0 }, 5000)[1]
				if depot then
					A.forLine = l.e
					buyFor(E, co, l, depot.depot)
					return true
				end
			end
		end
	end
	if bestBuy then
		local l = bestBuy.l
		local depot = garagesNear(E, co.ent, l.mid or (l.freight and l.freight.from.pos) or { x = 0, y = 0 }, 5000)[1]
		if depot then
			L(E, string.format("line %d gets a vehicle more (it earns %d per vehicle over 2 months)", l.e, math.floor(bestBuy.per)))
			A.forLine = l.e
			buyFor(E, co, l, depot.depot)
			return true
		end
	end
	return false
end

-- lines between neighbour towns: the company's stops nearest their residential centres, joined when both towns have one and
-- no line of the company joins them yet (a pair whose line was given up is not tried again)
local function interTown(E, co, stops, lines, money)
	local api = E.api
	local A = E.G.AI
	if money < RESERVE + 200000 then return false end
	local main = {}
	for _, t in ipairs(townsBySize(E)) do
		local c = centre(E, t.e, api.type.enum.LandUseType.RESIDENTIAL)
		if c then
			local best, bd
			for _, s in ipairs(stops) do local d = dist(s.pos, c); if d < 300 and (not bd or d < bd) then best, bd = s, d end end
			if best then main[#main + 1] = { town = t.e, stop = best, c = c } end
		end
	end
	for i = 1, #main do
		for j = i + 1, #main do
			local a, b = main[i], main[j]
			local key = math.min(a.stop.group, b.stop.group) .. "-" .. math.max(a.stop.group, b.stop.group)
			if dist(a.c, b.c) < 4500 and not (A.badPair or {})[key] and not (A.pairTried or {})[key] and not lineFor(E, lines, { a.stop.group, b.stop.group }) then
				A.pairTried = A.pairTried or {}; A.pairTried[key] = true
				A.pairOf = A.pairOf or {}
				A.nextPair = key
				createLine(E, co, { a.stop.group, b.stop.group }, a.town, AINAME .. " " .. townName(E, a.town) .. " - " .. townName(E, b.town))
				return true
			end
		end
	end
	return false
end

-- The best pair of towns to join next: both big, 1.2 to 6 km apart (fares grow with the distance), not joined by a line of the
-- company yet, not given up. Score: the product of their sizes over their distance.
local function bestPair(E, co, lines, stops)
	local api = E.api
	local A = E.G.AI
	local towns = {}
	for _, t in ipairs(townsBySize(E)) do
		local c = centre(E, t.e, api.type.enum.LandUseType.RESIDENTIAL)
		if c and t.size > 150 then towns[#towns + 1] = { e = t.e, size = t.size, c = c } end
	end
	local best
	for i = 1, #towns do
		for j = i + 1, #towns do
			local a, b = towns[i], towns[j]
			local d = dist(a.c, b.c)
			local key = math.min(a.e, b.e) .. "/" .. math.max(a.e, b.e)
			if d > 1200 and d < 6000 and not (A.pairDone or {})[key] and not (A.pairFailed or {})[key] then
				local score = a.size * b.size / d
				if not best or score > best.score then best = { a = a, b = b, d = d, key = key, score = score } end
			end
		end
	end
	return best
end

-- the company's stop serving a point (within 200 m), if any
local function stopAt(stops, p)
	local best, bd
	for _, s in ipairs(stops) do local d = dist(s.pos, p); if d < 200 and (not bd or d < bd) then best, bd = s, d end end
	return best
end

-- a stop near a point: the nearest free town street segment, the next one after each refusal; false when none is left
local function stopNear(E, co, stops, p, key)
	local A = E.G.AI
	local avoid = {}
	for _, s in ipairs(stops) do avoid[#avoid + 1] = s.pos end
	-- (within the 200 m stopAt takes: a stop built farther was never found again, and another one was built, and another)
	local segs = streetSegmentsNear(E, p, 200, avoid)
	local tries = (A.failed and A.failed["stop " .. key]) or 0
	local s = segs[1 + tries]
	if not s or tries > 4 then return false end
	L(E, "stop " .. key .. " (" .. math.floor(s.d) .. " m from its point)")
	buildStop(E, co, s.e, key)
	return true
end

-- the garage for a place: the company's own within 5 km, else one built near it (money allowing), else another company's
-- within 5 km; returns the garage, or "building", or nil
local function garageFor(E, co, p, money, key)
	local A = E.G.AI
	local list = garagesNear(E, co.ent, p, 5000)
	if list[1] and list[1].own then return list[1] end
	A.garageTried = A.garageTried or {}
	if not A.garageTried[key] and money >= RESERVE + 650000 then
		A.garageTried[key] = true
		local pl = garagePlaces(E, co, p, 900)[1]
		if pl then
			L(E, "garage near " .. key .. " on segment " .. pl.seg)
			buildGarage(E, co, pl)
			return "building"
		end
		L(E, "no free place for a garage near " .. key)
	end
	return list[1]
end

-- one step of the best pair's project: garage, a stop in each town, the line, its first buses. True when it acted (or waits)
local function pairProject(E, co, stops, lines, vehicles, money, grow)
	local A = E.G.AI
	local pair = bestPair(E, co, lines, stops)
	if not pair then return false end
	-- (a new pair only when the company may grow, see mayExpand; the pair under way gets its line and first buses)
	if grow == false and A.pairUnderWay ~= pair.key then return false end
	A.pairUnderWay = pair.key
	local na, nb = townName(E, pair.a.e), townName(E, pair.b.e)
	local g = garageFor(E, co, pair.a.c, money, na)
	if g == "building" then return true end
	if not g then g = garageFor(E, co, pair.b.c, money, nb) end
	if g == "building" then return true end
	if not g then
		L(E, "no garage for " .. na .. " - " .. nb .. ": pair left")
		A.pairFailed = A.pairFailed or {}; A.pairFailed[pair.key] = true
		return false
	end
	-- the line's points: in each town its residential centre and, when another district stands 300 m away, the one nearer to
	-- the other town (people ride from their homes to the other town's shops and works): A home, A work, B work, B home
	local function points(t, other)
		local tg = townTargets(E, t.e, stops)
		local list = { tg[1] }
		local best, bd
		for k = 2, #tg do local d = dist(tg[k].p, other.c); if not bd or d < bd then best, bd = tg[k], d end end
		if best then list[2] = best end
		return list
	end
	local pa, pb = points(pair.a, pair.b), points(pair.b, pair.a)
	local wanted = {}
	for _, p in ipairs(pa) do wanted[#wanted + 1] = { town = pair.a.e, p = p } end
	for k = #pb, 1, -1 do wanted[#wanted + 1] = { town = pair.b.e, p = pb[k] } end
	local groups = {}
	for _, w in ipairs(wanted) do
		local s = stopAt(stops, w.p.p)
		if not s then
			if money < RESERVE + 60000 then return true end
			if stopNear(E, co, stops, w.p.p, w.town .. ":" .. w.p.use) then return true end
			if w.p.use == "RESIDENTIAL" then
				L(E, "no street for a stop in " .. townName(E, w.town) .. ": pair left")
				A.pairFailed = A.pairFailed or {}; A.pairFailed[pair.key] = true
				return false
			end
		else
			groups[#groups + 1] = s.group
		end
	end
	if #groups < 2 then return true end
	local sa, sb = { group = groups[1] }, { group = groups[#groups] }
	local line = lineFor(E, lines, groups)
	local gkey = math.min(sa.group, sb.group) .. "-" .. math.max(sa.group, sb.group)
	if not line and (A.badPair or {})[gkey] then
		-- (a line given up there before: the pair is left)
		A.pairFailed = A.pairFailed or {}; A.pairFailed[pair.key] = true
		return false
	end
	if line and (A.emptyRuns or {})[line.e] and A.emptyRuns[line.e] > 0 then
		A.pairDone = A.pairDone or {}; A.pairDone[pair.key] = true
		return false
	end
	if not line then
		-- (a line only with the money for its first buses)
		if money < RESERVE + 2 * (A.busCost or BUS_COST) then return true end
		createLine(E, co, groups, pair.a.e, AINAME .. " " .. na .. " - " .. nb)
		return true
	end
	local n = 0
	for _, v in ipairs(vehicles) do if v.line == line.e then n = n + 1 end end
	if n < 3 then
		if money < RESERVE + (A.busCost or BUS_COST) then return true end
		A.forLine = line.e
		buyBus(E, co, g.depot)
		return true
	end
	A.pairDone = A.pairDone or {}; A.pairDone[pair.key] = true
	A.pairUnderWay = nil
	L(E, "pair " .. na .. " - " .. nb .. " running (" .. n .. " buses, " .. math.floor(pair.d) .. " m)")
	return true
end

-- ------------------------------------------------------------------ freight (trucks, 0.5.13)

-- Every industry has its own street station (the trucks of the players stop at the industry itself): a freight line is a line
-- from a producer's station to the station of an industry that takes that cargo, with trucks that carry it. Nothing to build
-- but the garage. MPFEVER_AIFREIGHT=0: buses only, as in 0.5.12.
-- (0.5.14) A route left for want of a garage near its producer waits six game months, then is tried again (a garage may stand
-- there by then: the company's own for a town, or another company's), instead of being left for the whole session: freight
-- comes first, before the company has any garage, and the best routes were all left in the first minutes. Returns true when
-- held. MPFEVER_AIRETRY=0: left for good, as before.
local function G_HOLD(E, key)
	if os.getenv("MPFEVER_AIRETRY") == "0" then return false end
	local A = E.G.AI
	A.freightHold = A.freightHold or {}
	A.freightHold[key] = E.gameTime() + 720000
	return true
end

local FREIGHT_MIN = 900      -- the shortest distance between the two industries (m); the longest is the level's (LEVELS)

-- the road terminals of a construction's stations: { group, list = { { station, terminal, node } } } (station and terminal
-- 0-based, as a line's stop takes them), nil when it has none
local function roadTerminals(E, con)
	local api = E.api
	local truck = api.type.enum.TransportMode.TRUCK
	local out
	for k = 1, #con.stations do
		local st = con.stations[k]
		local okg, group = pcall(function() return api.engine.system.stationGroupSystem.getStationGroup(st) end)
		local sg = okg and group and api.engine.getComponent(group, api.type.ComponentType.STATION_GROUP)
		local sc = api.engine.getComponent(st, api.type.ComponentType.STATION)
		if sg and sc then
			local si
			for i = 1, #sg.stations do if sg.stations[i] == st then si = i - 1 end end
			for t = 1, #sc.terminals do
				-- (a terminal trucks use: the carriers the engine reports for it; kept when it cannot tell)
				local road = true
				pcall(function()
					local cr = api.engine.system.stationGroupSystem.getCarriers(group, si, t - 1)
					local modes = cr and cr[2]
					if modes and #modes > 0 then
						road = false
						for _, m in ipairs(modes) do if m == truck then road = true end end
					end
				end)
				if road and si then
					out = out or { group = group, list = {} }
					if out.group == group then
						out.list[#out.list + 1] = { station = si, terminal = t - 1, node = sc.terminals[t].vehicleNodeId }
					end
				end
			end
		end
	end
	return out
end

-- the map's industries: what each makes and takes, where it stands, its road terminals (read once a minute)
local function industries(E)
	local api, R = E.api, E.R
	local A = E.G.AI
	if A.indCache and E.G.frames - A.indCache.frame < 3600 then return A.indCache.list end
	local OUT, IN = api.type.enum.StockListType.OutputStock, api.type.enum.StockListType.InputStock
	local list = {}
	for _, e in ipairs(R.entitiesWith("INDUSTRY")) do
		pcall(function()
			local ind = api.engine.getComponent(e, api.type.ComponentType.INDUSTRY)
			local con = ind and api.engine.getComponent(ind.construction, api.type.ComponentType.CONSTRUCTION)
			local sl = ind and api.engine.getComponent(ind.stockList, api.type.ComponentType.STOCK_LIST)
			if not (con and sl) then return end
			local m = E.C.marshal(con.transf)
			local it = { e = e, con = ind.construction, stockList = ind.stockList, pos = { x = m[13], y = m[14], z = m[15] },
				file = tostring(con.fileName), outputs = {}, inputs = {}, inputSets = {} }
			for k = 1, #sl.stocks do
				local s = sl.stocks[k]
				if s.type == OUT and s.cargoType >= 0 then it.outputs[#it.outputs + 1] = s.cargoType end
				if s.type == IN then
					if s.cargoType >= 0 then it.inputs[s.cargoType] = true else it.inputSets[#it.inputSets + 1] = s.cargoTypes end
				end
			end
			-- (primary: a rule of it, not a booster, makes cargo from nothing, as a mine or a farm; the others need their inputs)
			it.primary = false
			pcall(function()
				for k = 1, #sl.rules do
					local r = sl.rules[k]
					if not r.booster then
						local need = 0
						local alt = r.input and r.input[1]
						if alt then for j = 1, #alt do need = need + (alt[j] or 0) end end
						if need == 0 then it.primary = true end
					end
				end
			end)
			it.road = roadTerminals(E, con)
			-- (else a station of one of its parts, as the game's own path finding of the missions looks for it)
			for k = 1, #con.subconstructions do
				if it.road then break end
				local sub = api.engine.getComponent(con.subconstructions[k], api.type.ComponentType.CONSTRUCTION)
				if sub then it.road = roadTerminals(E, sub) end
			end
			if it.road then list[#list + 1] = it end
		end)
	end
	table.sort(list, function(a, b) return a.e < b.e end)
	A.indCache = { frame = E.G.frames, list = list }
	return list
end

-- How much of a cargo a producer makes now (a year's worth, for the routes' score), nil when it makes none: an industry that needs
-- inputs makes nothing without them (the first test of 0.5.13: a brick works, a refinery and a food factory with no raw material,
-- lines that ran empty and were given up); a primary one starts once a line serves it (half its most). MPFEVER_AIANYPRODUCER=1:
-- every producer, as before.
local function producedOf(E, ind, c)
	local api = E.api
	local made = 0
	pcall(function() made = api.engine.util.stock.getCargoProducedPerYear(ind.stockList, c) or 0 end)
	if made > 0 then return made end
	if ind.primary or os.getenv("MPFEVER_AIANYPRODUCER") == "1" then
		local most = 0
		pcall(function() most = api.engine.util.stock.getCargoMaxProductionPerYear(ind.stockList, c) or 0 end)
		return most * 0.5
	end
	return nil
end

local function takes(E, ind, cargo)
	if ind.inputs[cargo] then return true end
	for _, set in ipairs(ind.inputSets) do
		local ok, yes = pcall(function() return E.api.res.cargoTypeRep.hasCargoType(set, cargo) end)
		if ok and yes then return true end
	end
	return false
end

-- the station groups other companies' lines stop at (the industries they serve are theirs: PvE; not on the Hard level, which
-- competes with them)
local function servedByOthers(E, ent)
	local api, R = E.api, E.R
	local out = {}
	if LV.compete then return out end
	for _, l in ipairs(R.entitiesWith("LINE")) do
		if ownerOf(E, l) ~= ent then
			local lc = api.engine.getComponent(l, api.type.ComponentType.LINE)
			for k = 1, #lc.stops do out[lc.stops[k].stationGroup] = true end
		end
	end
	return out
end

-- a truck can drive from one industry's road terminals to the other's (the engine's path finding)
local function roadPath(E, a, b)
	local api = E.api
	local na, nb = {}, {}
	for _, t in ipairs(a.road.list) do na[#na + 1] = t.node end
	for _, t in ipairs(b.road.list) do nb[#nb + 1] = t.node end
	local ok, p = pcall(function() return api.engine.util.pathfinding.findPathNodeToNode(na, nb, { api.type.enum.TransportMode.TRUCK }) end)
	return ok and type(p) == "table" and #p > 0
end

-- the best truck on sale this year for a cargo: most capacity for it, then the newest
local function bestTruck(E, cargo)
	local api = E.api
	local year = currentYear(E)
	local best
	for id, name in pairs(api.res.modelRep.getAll()) do
		if tostring(name):find("/vehicle/truck/", 1, true) then
			local m = api.res.modelRep.get(id)
			local md = m and m.metadata
			local av = md and md.availability
			local from, to = av and av.yearFrom or 0, av and av.yearTo or 0
			if from <= year and (to == 0 or to > year) then
				local cap = 0
				pcall(function()
					for _, comp in ipairs(md.transportVehicle.compartments) do
						for _, lc in ipairs(comp.loadConfigs) do
							if api.res.cargoTypeRep.hasCargoType(lc.cargoEntry.cargoTypeSet, cargo) then cap = math.max(cap, lc.cargoEntry.capacity or 0) end
						end
					end
				end)
				if cap > 0 and (not best or cap > best.seats or (cap == best.seats and from > best.from)) then
					best = { id = id, name = name, seats = cap, from = from }
				end
			end
		end
	end
	return best, year
end

-- the road terminals of a station group (a street stop: its two sides), as roadTerminals gives them
local function groupRoad(E, group)
	local api = E.api
	local sg = api.engine.getComponent(group, api.type.ComponentType.STATION_GROUP)
	if not sg then return nil end
	local out = { group = group, list = {} }
	for k = 1, #sg.stations do
		local sc = api.engine.getComponent(sg.stations[k], api.type.ComponentType.STATION)
		if sc then
			for t = 1, #sc.terminals do out.list[#out.list + 1] = { station = k - 1, terminal = t - 1, node = sc.terminals[t].vehicleNodeId } end
		end
	end
	return #out.list > 0 and out or nil
end

-- a freight line of the company: { from = industry, to = industry or town stop, cargo } when its first stop is an industry's
-- station and its second one an industry that takes a cargo of the first, or a street stop (a town's delivery: the producer's
-- first cargo). Read from the world: nothing kept across loads.
freightOf = function(E, line)
	local inds = industries(E)
	local byGroup = {}
	for _, it in ipairs(inds) do byGroup[it.road.group] = it end
	-- (a round: the producers first, the industry that takes their cargo last)
	local a, b = byGroup[line.groups[1]], byGroup[line.groups[#line.groups]]
	if not a or not line.groups[2] then return nil end
	if b then
		for _, c in ipairs(a.outputs) do if takes(E, b, c) then return { from = a, to = b, cargo = c } end end
		return nil
	end
	if a.outputs[1] and #line.groups == 2 then
		local road = groupRoad(E, line.groups[2])
		if road then return { from = a, to = { road = road }, cargo = a.outputs[1], town = true } end
	end
	return nil
end

-- a vehicle more for a line: a truck for its cargo on a freight line, else a bus
local function buyTruck(E, co, depot, cargo)
	local truck, year = bestTruck(E, cargo)
	if not truck then L(E, "no truck for " .. cargoName(E, cargo) .. " on sale in " .. year); return false end
	local cfg = {
		vehicles = { { part = { modelId = truck.id, reversed = false, compartment2loadConfig = { { loadConfigIndex = 0, cargoTypeId = 0, __ud = true } },
			color = { x = -1, y = -1, z = -1, __vec = true }, __ud = true }, purchaseTime = 0, maintenanceChange = 0, maintenanceState = 1,
			autoLoadConfig = { true }, __ud = true } },
		vehicleGroups = { 1 }, muFileNames = {}, __ud = true }
	act(E, co.id, "makeVehicleBuyCmd", { n = 3, [1] = co.ent, [2] = depot, [3] = cfg })
	E.G.AI.busy = { what = "truck " .. truck.name, since = E.G.frames, vehBefore = #myVehicles(E, co.ent), moneyBefore = balanceOf(E, co.ent),
		jr = { kind = "truck", pos = depotPos(E, depot), a = tostring(truck.name):match("([^/]+)%.mdl$") or truck.name, b = cargo } }
	L(E, "truck requested: " .. truck.name .. " (" .. truck.seats .. " " .. cargoName(E, cargo) .. ", " .. year .. ") at depot " .. depot)
	return true
end

buyFor = function(E, co, line, depot)
	local f = os.getenv("MPFEVER_AIFREIGHT") ~= "0" and freightOf(E, line)
	if f then return buyTruck(E, co, depot, f.cargo) end
	return buyBus(E, co, depot)
end

-- A stop of a freight line; loadCargo: the cargo its trucks load there (a producer's stop). The stop's configuration lists, per
-- cargo type (its id + 1), whether to load it and up to which share: a new stop's lists are empty, and its trucks loaded nothing
-- (the lines of 0.5.13's first test ran empty and were given up). As the game's line window sets it: that cargo loaded, full.
local function freightStop(E, road, stop0, loadCargo)
	local s = {}
	if stop0 then for k, v in pairs(stop0) do s[k] = v end end
	if loadCargo then
		local n = 0
		pcall(function() for id in pairs(E.api.res.cargoTypeRep.getAll(true)) do if id + 1 > n then n = id + 1 end end end)
		if n > loadCargo then
			local cfg = {}
			if type(s.stopConfig) == "table" then for k, v in pairs(s.stopConfig) do cfg[k] = v end end
			local load, maxLoad = {}, {}
			for k = 1, n do load[k] = (k == loadCargo + 1); maxLoad[k] = 1 end
			cfg.load, cfg.maxLoad = load, maxLoad
			if cfg.destroyForConfigChange == nil then cfg.destroyForConfigChange = true end
			if cfg.destroyForRefresh == nil then cfg.destroyForRefresh = true end
			if cfg.forceUnload == nil then cfg.forceUnload = false end
			cfg.__ud = true
			s.stopConfig = cfg
		else
			L(E, "freight stop: the cargo types could not be read, " .. tostring(loadCargo) .. " not set to load")
		end
	end
	local first = road.list[1]
	s.stationGroup = road.group
	s.station = first.station
	s.terminal = first.terminal
	-- (the station's other road terminals as alternatives: the engine takes a free one)
	local alt = {}
	for k = 2, #road.list do alt[#alt + 1] = { station = road.list[k].station, terminal = road.list[k].terminal, __ud = true } end
	s.alternativeTerminals = alt
	s.waypoints = {}
	s.__ud = true
	return s
end

local function createFreightLine(E, co, f, extra)
	local api, C, R = E.api, E.C, E.R
	-- (a truck line of the savegame as the template of the line's fields, else a new line's)
	local template
	for _, l in ipairs(R.entitiesWith("LINE")) do
		local m = C.marshal(api.engine.getComponent(l, api.type.ComponentType.LINE))
		if m and m.vehicleInfo and m.vehicleInfo.transportModes and m.vehicleInfo.transportModes[4] == true then template = m break end
	end
	if not template then template = C.marshal(api.type.Line.new()) end
	-- (a stop's fields without the template's own cargo settings: every cargo loaded and unloaded, the engine's defaults)
	local stop0
	pcall(function() stop0 = C.marshal(api.type.Line.Stop.new()) end)
	if not stop0 and template.stops and template.stops[1] then
		stop0 = {}
		for k, v in pairs(template.stops[1]) do if k ~= "stopConfig" then stop0[k] = v end end
	end
	template.stops = { freightStop(E, f.from.road, stop0, f.cargo), freightStop(E, f.to.road, stop0) }
	-- (a round: a second producer of the same cargo on the way, see collectFrom)
	if extra then table.insert(template.stops, 2, freightStop(E, extra.road, stop0, f.cargo)) end
	local name = AINAME .. " " .. cargoName(E, f.cargo) .. " " .. math.floor(dist(f.from.pos, f.to.pos) / 100) / 10 .. " km"
	act(E, co.id, "makeLineCreateCmd", { n = 4, [1] = name, [2] = C.marshal(api.type.Vec3f.new(0.8, 0.5, 0.1)), [3] = co.ent, [4] = template })
	-- (its growth waits until this line had time to fill, see mayExpand)
	E.G.AI.lastNewAt = E.gameTime()
	E.G.AI.busy = { what = "line " .. name, since = E.G.frames, linesBefore = #myLines(E, co.ent), jr = { kind = "freight", pos = f.from.pos, a = name, b = f.cargo } }
	L(E, "freight line requested: " .. name .. " (industry " .. f.from.e .. " -> " .. tostring(f.to.e or ("town stop " .. tostring(f.to.road.group))) .. ")")
end

-- The best freight route not served yet: a producer, an industry that takes its cargo 0.9 to 5 km away, no other company's line
-- at either, a road between them (looked for once per route, one route per step: the path finding costs). Score: the most the
-- producer can make of that cargo, times the distance (the fare grows with it), less for long routes.
local function bestFreight(E, co, lines)
	local api = E.api
	local A = E.G.AI
	A.freightTried = A.freightTried or {}
	-- (a street built to an industry since: the routes that had no road there are looked for again, see roadProject)
	if A.retryInd and E.G.frames >= (A.retryAt or 0) then
		for k, v in pairs(A.freightTried) do
			if v == false and (k:find("^" .. A.retryInd .. ">") or k:find(">" .. A.retryInd .. ":")) then A.freightTried[k] = nil end
		end
		A.retryInd = nil
	end
	local others = servedByOthers(E, co.ent)
	local inds = industries(E)
	local cut = A.roadChecked or {}
	local cands = {}
	for _, p in ipairs(inds) do
		if not others[p.road.group] then
			for _, c in ipairs(p.outputs) do
				-- (only a producer that makes that cargo now, or a primary one, see producedOf)
				local prod = producedOf(E, p, c)
				for _, q in ipairs(prod and inds or {}) do
					-- (an industry found cut off from the streets is left out until a street reaches it, see roadProject)
					if q.e ~= p.e and not others[q.road.group] and cut[p.e] ~= false and cut[q.e] ~= false and takes(E, q, c) then
						local d = dist(p.pos, q.pos)
						local key = p.e .. ">" .. q.e .. ":" .. c
						if d > FREIGHT_MIN and d < LV.freightMax and A.freightTried[key] ~= false and not (A.freightDone or {})[key] then
							cands[#cands + 1] = { from = p, to = q, cargo = c, d = d, key = key, score = (prod + 50) * d / (1 + (d / 3000) ^ 2) }
						end
					end
				end
			end
		end
	end
	table.sort(cands, function(a, b) if a.score ~= b.score then return a.score > b.score end return a.key < b.key end)
	for _, f in ipairs(cands) do
		-- (a line of the company there already: that route is running)
		if lineFor(E, lines, { f.from.road.group, f.to.road.group }) then
			A.freightDone = A.freightDone or {}; A.freightDone[f.key] = true
		elseif A.freightTried[f.key] == true then
			return f
		else
			-- (one path search per step)
			local ok = roadPath(E, f.from, f.to)
			A.freightTried[f.key] = ok
			if ok then L(E, "freight route found: " .. cargoName(E, f.cargo) .. ", industry " .. f.from.e .. " -> " .. f.to.e .. " (" .. math.floor(f.d) .. " m)") end
			-- (no road between them: one of the two may be cut off from the streets, see roadProject)
			if not ok then
				A.pathFails = A.pathFails or {}
				if #A.pathFails < 40 then A.pathFails[#A.pathFails + 1] = { from = f.from, to = f.to, score = f.score } end
			end
			return ok and f or "searching"
		end
	end
	return nil
end

-- ---- deliveries to the towns: a producer's cargo to a stop near the town district that wants more of it (its shops or its
-- works). A street stop unloads any cargo of the universal class there; a stop of the company already near that point is taken.
local TOWN_USES = { "COMMERCIAL", "INDUSTRIAL" }

-- what a town's districts want more of: { { cargo, miss, use } } (the district's limit less what it gets)
local function townWants(E, town)
	local api = E.api
	local out = {}
	for _, u in ipairs(TOWN_USES) do
		pcall(function()
			for c, sl in pairs(api.engine.system.townBuildingSystem.getCargoSupplyAndLimit(town, api.type.enum.LandUseType[u])) do
				local miss = math.floor((sl[2] or 0) - (sl[1] or 0))
				if miss > 0 then out[#out + 1] = { cargo = c, miss = miss, use = u } end
			end
		end)
	end
	table.sort(out, function(a, b) if a.miss ~= b.miss then return a.miss > b.miss end return a.cargo < b.cargo end)
	return out
end

-- a truck can drive from an industry's road terminals to the streets around a point
local function roadPathTo(E, a, p)
	local api = E.api
	local na = {}
	for _, t in ipairs(a.road.list) do na[#na + 1] = t.node end
	local ok, path = pcall(function()
		local nb = api.engine.util.octree.findTransportNetworkNodesInCircle(api.type.Vec2f.new(p.x, p.y), 250)
		return api.engine.util.pathfinding.findPathNodeToNode(na, nb, { api.type.enum.TransportMode.TRUCK })
	end)
	return ok and type(path) == "table" and #path > 0
end

-- The best delivery to a town not made yet: a town of 300 people or more, a cargo one of its districts wants, a producer of it
-- 0.9 to 5 km from that district's centre, nobody else's line at the producer, a road between them (one search per step).
-- Score as the routes between industries, times how much the district misses (up to 100).
local function bestTownFreight(E, co, lines)
	local api = E.api
	local A = E.G.AI
	A.freightTried = A.freightTried or {}
	local others = servedByOthers(E, co.ent)
	local inds = industries(E)
	local cands = {}
	for _, t in ipairs(townsBySize(E)) do
		if t.size >= 300 then
			for _, w in ipairs(townWants(E, t.e)) do
				local p = centre(E, t.e, api.type.enum.LandUseType[w.use])
				if p then
					for _, ind in ipairs(inds) do
						if not others[ind.road.group] and (A.roadChecked or {})[ind.e] ~= false then
							for _, c in ipairs(ind.outputs) do
								if c == w.cargo and producedOf(E, ind, c) then
									local d = dist(ind.pos, p)
									local key = ind.e .. ">town" .. t.e .. ":" .. c
									if d > FREIGHT_MIN and d < LV.freightMax and A.freightTried[key] ~= false and not (A.freightDone or {})[key] then
										local prod = producedOf(E, ind, c) or 0
										cands[#cands + 1] = { from = ind, town = t.e, use = w.use, p = p, cargo = c, d = d, key = key,
											score = (prod + 50) * d / (1 + (d / 3000) ^ 2) * math.min(w.miss, 100) / 100 }
									end
								end
							end
						end
					end
				end
			end
		end
	end
	table.sort(cands, function(a, b) if a.score ~= b.score then return a.score > b.score end return a.key < b.key end)
	for _, f in ipairs(cands) do
		if A.freightTried[f.key] == true then return f end
		local ok = roadPathTo(E, f.from, f.p)
		A.freightTried[f.key] = ok
		if ok then L(E, "town delivery found: " .. cargoName(E, f.cargo) .. ", industry " .. f.from.e .. " -> " .. townName(E, f.town) .. " " .. f.use .. " (" .. math.floor(f.d) .. " m)") end
		return ok and f or "searching"
	end
	return nil
end

-- one step of the best town delivery: the garage, the stop in town, the line, its first two trucks. True when it acted (or waits)
local function townFreightProject(E, co, stops, lines, vehicles, money)
	local A = E.G.AI
	local f = bestTownFreight(E, co, lines)
	if f == "searching" then return "searching" end
	if not f then return false end
	-- (a garage that is there already, the company's own first: none is built near an industry, whose ground is often uneven: a
	-- garage built on a slope there stopped both games for good, the engine never ending its build. MPFEVER_AIFREIGHTGARAGE=1: built)
	local g
	if os.getenv("MPFEVER_AIFREIGHTGARAGE") == "1" then g = garageFor(E, co, f.from.pos, money, "industry " .. f.from.e) else g = garagesNear(E, co.ent, f.from.pos, 5000)[1] end
	if g == "building" then return true end
	if not g then
		L(E, "no garage for the town delivery " .. f.key .. ": left" .. (G_HOLD(E, f.key) and " for now" or ""))
		A.freightTried[f.key] = false
		return false
	end
	local s = stopAt(stops, f.p)
	if not s then
		if money < RESERVE + 60000 then return true end
		if stopNear(E, co, stops, f.p, f.town .. ":" .. f.use) then return true end
		L(E, "no street for a stop near the " .. f.use .. " centre of " .. townName(E, f.town) .. ": delivery left")
		A.freightTried[f.key] = false
		return false
	end
	local road = groupRoad(E, s.group)
	if not road then A.freightTried[f.key] = false; return false end
	local line = lineFor(E, lines, { f.from.road.group, s.group })
	if line and #line.groups ~= 2 then line = nil end
	-- (a line given up there before: that delivery is left)
	if not line and (A.badPair or {})[math.min(f.from.road.group, s.group) .. "-" .. math.max(f.from.road.group, s.group)] then A.freightTried[f.key] = false; return false end
	if not line then
		if money < RESERVE + 2 * (A.truckCost or BUS_COST) then return true end
		createFreightLine(E, co, { from = f.from, to = { road = road, pos = s.pos }, cargo = f.cargo })
		return true
	end
	local n = 0
	for _, v in ipairs(vehicles) do if v.line == line.e then n = n + 1 end end
	if n < 2 then
		if money < RESERVE + (A.truckCost or BUS_COST) then return true end
		A.forLine = line.e
		buyTruck(E, co, g.depot, f.cargo)
		return true
	end
	A.freightDone = A.freightDone or {}; A.freightDone[f.key] = true
	return false
end

-- A round (0.5.13): another producer of the route's cargo within 1.5 km of the first, no line at it yet (nobody's, the company's
-- neither), a road from it to the industry that takes the cargo: its stop goes between the two (one path search per step, kept).
-- Returns that industry, nil, or "searching" (a search was made this step). MPFEVER_AIROUND=0: no rounds.
local function collectFrom(E, co, f, lines)
	if os.getenv("MPFEVER_AIROUND") == "0" then return nil end
	local A = E.G.AI
	A.roundTried = A.roundTried or {}
	local others = servedByOthers(E, co.ent)
	local mine = {}
	for _, l in ipairs(lines) do for _, g in ipairs(l.groups) do mine[g] = true end end
	local best, bd
	for _, p in ipairs(industries(E)) do
		if p.e ~= f.from.e and p.e ~= f.to.e and not others[p.road.group] and not mine[p.road.group] then
			local makes = false
			for _, c in ipairs(p.outputs) do if c == f.cargo and producedOf(E, p, c) then makes = true end end
			local d = dist(p.pos, f.from.pos)
			if makes and d < 1500 and dist(p.pos, f.to.pos) < LV.freightMax and A.roundTried[f.key .. "+" .. p.e] ~= false and (not bd or d < bd) then
				best, bd = p, d
			end
		end
	end
	if not best then return nil end
	local key = f.key .. "+" .. best.e
	if A.roundTried[key] == true then return best end
	local ok = roadPath(E, best, f.to)
	A.roundTried[key] = ok
	if ok then L(E, "round: industry " .. best.e .. " joins the route " .. f.key .. " (" .. math.floor(bd) .. " m from the first)") end
	return ok and best or "searching"
end

-- one step of the best freight route between two industries: its garage, its line, its first two trucks. True when it acted
local function industryProject(E, co, lines, vehicles, money)
	local A = E.G.AI
	local f = bestFreight(E, co, lines)
	if f == "searching" then return "searching" end
	if not f then return false end
	-- (a garage that is there already, the company's own first: none is built near an industry, whose ground is often uneven: a
	-- garage built on a slope there stopped both games for good, the engine never ending its build. MPFEVER_AIFREIGHTGARAGE=1: built)
	local g
	if os.getenv("MPFEVER_AIFREIGHTGARAGE") == "1" then g = garageFor(E, co, f.from.pos, money, "industry " .. f.from.e) else g = garagesNear(E, co.ent, f.from.pos, 5000)[1] end
	if g == "building" then return true end
	if not g then
		L(E, "no garage for the freight route " .. f.key .. ": route left" .. (G_HOLD(E, f.key) and " for now" or ""))
		A.freightTried[f.key] = false
		return false
	end
	local line = lineFor(E, lines, { f.from.road.group, f.to.road.group })
	-- (a line given up there before: that route is left)
	if not line and (A.badPair or {})[math.min(f.from.road.group, f.to.road.group) .. "-" .. math.max(f.from.road.group, f.to.road.group)] then A.freightTried[f.key] = false; return false end
	if not line then
		if money < RESERVE + 2 * (A.truckCost or BUS_COST) then return true end
		-- (a second producer of that cargo near the first: one round for both)
		local extra = collectFrom(E, co, f, lines)
		if extra == "searching" then return "searching" end
		createFreightLine(E, co, f, extra)
		return true
	end
	local n = 0
	for _, v in ipairs(vehicles) do if v.line == line.e then n = n + 1 end end
	if n < 2 then
		if money < RESERVE + (A.truckCost or BUS_COST) then return true end
		A.forLine = line.e
		buyTruck(E, co, g.depot, f.cargo)
		return true
	end
	A.freightDone = A.freightDone or {}; A.freightDone[f.key] = true
	return false
end

-- ---- roads (0.5.13): an industry no truck reaches (a route of it found no road) gets a street from the free end of its own
-- streets to the nearest town street node within 900 m: straight, in pieces of 80 m at most, the town street's template, owned
-- by the company, a dry run first; built as the street tool builds (the same fields as the autotest's roads, see the bridge's
-- buildMatrixProposal), for the company. The routes of that industry are looked for again a little later. MPFEVER_AIROADS=0: none.
local CTX_ROAD = 35

local function nearestTownCentre(E, p)
	local best, bd
	for _, t in ipairs(townsBySize(E)) do
		local c = centre(E, t.e, E.api.type.enum.LandUseType.RESIDENTIAL)
		if c then local d = dist(c, p); if not bd or d < bd then best, bd = c, d end end
	end
	return best
end

-- the street proposal from node n0 (at p0) to the town node n1 (at p1), with the town segment tc's template; nil if no lanes
local function roadProposal(E, co, n0, p0, n1, p1, tc)
	local api, C = E.api, E.C
	local lanes = C.templateLanes(tc.roadTemplate)
	if not lanes then return nil end
	local len = dist(p0, p1)
	local k = math.max(1, math.ceil(len / 80))
	local pts = { p0 }
	for i = 1, k - 1 do
		local x, y = p0.x + (p1.x - p0.x) * i / k, p0.y + (p1.y - p0.y) * i / k
		pts[#pts + 1] = { x = x, y = y, z = E.groundZ(x, y, p0.z + (p1.z - p0.z) * i / k) }
	end
	pts[#pts + 1] = p1
	local sp = api.type.SimpleProposal.new()
	local ssp = sp.streetProposal
	local nodes, edges = {}, {}
	local ids = { n0 }
	for i = 2, k do
		local ne = api.type.NodeAndEntity.new()
		ne.entity = -i
		local bn = ne.comp
		bn.position = api.type.Vec3f.new(pts[i].x, pts[i].y, pts[i].z)
		ne.comp = bn
		nodes[#nodes + 1] = ne
		ids[i] = -i
	end
	ids[k + 1] = n1
	for i = 1, k do
		local a, b = pts[i], pts[i + 1]
		local e = api.type.SegmentAndEntity.new()
		e.entity = -100 - i
		e.type = 0
		local c = e.comp
		c.laneConfigs = lanes
		c.node0, c.node1 = ids[i], ids[i + 1]
		local t = api.type.Vec3f.new(b.x - a.x, b.y - a.y, b.z - a.z)
		c.tangent0, c.tangent1 = t, t
		c.type, c.typeIndex = 0, -1
		c.position0 = api.type.Vec3f.new(a.x, a.y, a.z)
		c.position1 = api.type.Vec3f.new(b.x, b.y, b.z)
		c.roadTemplate, c.roadStyle, c.roadType = tc.roadTemplate, tc.roadStyle, tc.roadType
		e.comp = c
		local se = e.streetEdge
		se.precedenceNode0, se.precedenceNode1 = 2, 2
		e.streetEdge = se
		local po = e.playerOwned
		if po == nil then po = C.newOf("PlayerOwned") end
		po.player = co.ent
		e.playerOwned = po
		edges[#edges + 1] = e
	end
	if #nodes > 0 then ssp.nodesToAdd = nodes end
	ssp.edgesToAdd = edges
	sp.streetProposal = ssp
	return sp
end

-- one street to an industry cut off from the streets: true when it was asked for
local function connectIndustry(E, co, ind)
	local api, R = E.api, E.R
	local A = E.G.AI
	local con = api.engine.getComponent(ind.con, api.type.ComponentType.CONSTRUCTION)
	local segmap = api.engine.system.streetSystem.getNode2SegmentMap()
	-- the free ends of its own streets
	local ends, seen = {}, {}
	for k = 1, #con.frozenEdges do
		local e = con.frozenEdges[k]
		local be = api.engine.getComponent(e, api.type.ComponentType.BASE_EDGE)
		if be and api.engine.getComponent(e, api.type.ComponentType.BASE_EDGE_STREET) then
			for _, nd in ipairs({ be.node0, be.node1 }) do
				local p = not seen[nd] and #(segmap[nd] or {}) == 1 and E.nodePosition(nd)
				seen[nd] = true
				if p then ends[#ends + 1] = { node = nd, p = p } end
			end
		end
	end
	if #ends == 0 then L(E, "road: industry " .. ind.e .. " has no free street end"); return false end
	-- the town street nodes near them, the nearest pairs first
	local pairsList = {}
	for _, e in ipairs(R.allEdges()) do
		local c = api.engine.getComponent(e, api.type.ComponentType.BASE_EDGE)
		if c and c.type == 0 and api.engine.getComponent(e, api.type.ComponentType.BASE_EDGE_STREET) and tostring(c.roadTemplate):find("/town/", 1, true) then
			local okC, cn = pcall(function() return api.engine.system.streetConnectorSystem.getConstructionEntityForEdge(e) end)
			if not (okC and type(cn) == "number" and cn >= 0) then
				for _, nd in ipairs({ c.node0, c.node1 }) do
					local q = #(segmap[nd] or {}) <= 3 and E.nodePosition(nd)
					if q then
						for _, en in ipairs(ends) do
							local d = dist(en.p, q)
							if d > 30 and d < 900 then pairsList[#pairsList + 1] = { en = en, node = nd, q = q, c = c, d = d } end
						end
					end
				end
			end
		end
	end
	table.sort(pairsList, function(a, b) if a.d ~= b.d then return a.d < b.d end return a.node < b.node end)
	local ctx = context(E, co.ent, CTX_ROAD)
	for i = 1, math.min(4, #pairsList) do
		local pr = pairsList[i]
		local okp, sp = pcall(roadProposal, E, co, pr.en.node, pr.en.p, pr.node, pr.q, pr.c)
		if okp and sp then
			local okd, pd = pcall(function() return api.engine.util.proposal.makeProposalData(sp, ctx) end)
			local why = ""
			if okd and pd then pcall(function() why = E.C.ser(E.C.marshal(pd.errorState.messages)) end) end
			if okd and pd and #pd.errorState.messages == 0 and not pd.errorState.critical then
				local mid = { x = (pr.en.p.x + pr.q.x) / 2, y = (pr.en.p.y + pr.q.y) / 2, z = (pr.en.p.z + pr.q.z) / 2 }
				L(E, string.format("road to industry %d: %.0f m from node %d to the town node %d", ind.e, pr.d, pr.en.node, pr.node))
				build(E, co.id, api.cmd.makeWorldBuildProposalCmd(sp, ctx, false, true, true), "road to industry " .. ind.e, CTX_ROAD,
					{ kind = "road", pos = mid })
				return true
			end
			L(E, "road to industry " .. ind.e .. " (" .. math.floor(pr.d) .. " m): dry run refused " .. why:sub(1, 200))
		elseif not okp then
			L(E, "road to industry " .. ind.e .. ": " .. tostring(sp):sub(1, 200))
		end
	end
	return false
end

-- one step of the roads: the industries of the routes that found no road, the best route first; is each one cut off from the
-- streets (one path search per step)? A street to the first one that is. True when it acted (or searched)
local function roadProject(E, co, money)
	if os.getenv("MPFEVER_AIROADS") == "0" then return false end
	local A = E.G.AI
	if not A.pathFails or #A.pathFails == 0 or money < RESERVE + 400000 then return false end
	A.roadChecked = A.roadChecked or {}
	A.roadDone = A.roadDone or {}
	table.sort(A.pathFails, function(a, b) return a.score > b.score end)
	for _, pf in ipairs(A.pathFails) do
		for _, ind in ipairs({ pf.from, pf.to }) do
			if not A.roadDone[ind.e] then
				if A.roadChecked[ind.e] == nil then
					local c = nearestTownCentre(E, ind.pos)
					A.roadChecked[ind.e] = c == nil or roadPathTo(E, ind, c)
					if not A.roadChecked[ind.e] then L(E, "industry " .. ind.e .. " is cut off from the streets") end
					return "searching"
				end
				if A.roadChecked[ind.e] == false then
					A.roadDone[ind.e] = true
					if connectIndustry(E, co, ind) then
						A.retryInd, A.retryAt = ind.e, E.G.frames + 1800
						A.roadChecked[ind.e] = nil
						return true
					end
				end
			end
		end
	end
	A.pathFails = {}
	return false
end

-- the next freight step: deliveries to towns and routes between industries in turn (the kind the company has fewer lines of
-- first, the other one when it has nothing to do). MPFEVER_AITOWNFREIGHT=0: between industries only.
local function freightProject(E, co, stops, lines, vehicles, money)
	-- (the routes left for want of a garage are tried again once their wait is over, see G_HOLD)
	local A = E.G.AI
	if A.freightHold and os.getenv("MPFEVER_AIRETRY") ~= "0" then
		local now = E.gameTime()
		for k, t in pairs(A.freightHold) do
			if now >= t or t - now > 2 * 720000 then A.freightHold[k] = nil; if A.freightTried and A.freightTried[k] == false then A.freightTried[k] = nil end end
		end
	end
	local nTown, nInd = 0, 0
	for _, l in ipairs(lines) do
		local f = freightOf(E, l)
		if f and f.town then nTown = nTown + 1 elseif f then nInd = nInd + 1 end
	end
	local towns = os.getenv("MPFEVER_AITOWNFREIGHT") ~= "0"
	if towns and nTown <= nInd then
		return townFreightProject(E, co, stops, lines, vehicles, money) or industryProject(E, co, lines, vehicles, money) or roadProject(E, co, money)
	end
	return industryProject(E, co, lines, vehicles, money) or (towns and townFreightProject(E, co, stops, lines, vehicles, money)) or roadProject(E, co, money)
end

-- ------------------------------------------------------------------ the step

local function join(E)
	local G = E.G
	local A = G.AI
	if A.joinSent and G.frames - A.joinSent < 1800 then return end
	A.joinSent = G.frames
	local now = E.gameTime()
	G.oseq = G.oseq + 1
	local paused = G.session.pauseAt ~= nil and now >= G.session.pauseAt and E.gameSpeed() == 0
	-- (a running session: stamped 60 steps ahead. A player's builds are held by the native module up to their time, a company's
	-- arrival is not: stamped a few steps ahead as they are, the host's simulation, which runs ahead of its interface, had passed
	-- that time when its hold came, and created the company 4 steps after the other game (ser050 of 2026-10-28: another entity,
	-- everything drifted). That far ahead every game holds at its time, the gathering of the joins included)
	local a = { fn = "mpfCoJoin", origin = G.me, oseq = G.oseq, uid = G.me .. ":" .. G.oseq,
		at = paused and E.pausedStamp(now) or (E.stampFor(now) + 60 * E.STEP), paused = paused or nil, native = true,
		args = { key = AIKEY, name = AINAME, host = false, mode = "separate", start = AIMONEY or G.coStart, color = AICOLOR, cname = AINAME } }
	E.send("act", a)
	a.recvFrame = G.frames
	G.nativeQueue[#G.nativeQueue + 1] = a
	if paused and G.joinTurns then G.ptIssue(G.me, G.joinTurnId(a)) end
	L(E, "company announced: " .. AINAME)
end

local function step(E)
	local G = E.G
	local A = G.AI
	local co = aiCompany(E)
	if not co then return join(E) end
	if not co.ent then return end
	-- the colour the host gave it in the lobby (a savegame's company keeps its own until then): asked once, as a player would
	if AICOLOR and co.color ~= AICOLOR and not A.recolorAsked and E.CO.colorFree(G.co, AICOLOR, co.id) then
		A.recolorAsked = true
		act(E, co.id, "makeScriptingSendEventCmd", { n = 4, [1] = "mpfever", [2] = "mpfever", [3] = "recolor", [4] = { color = AICOLOR } })
		L(E, "colour " .. tostring(AICOLOR) .. " asked")
		return
	end
	if A.busy then
		local age = G.frames - A.busy.since
		-- (a command's result shows in the world: the line or the vehicle appears)
		if A.busy.linesBefore and #myLines(E, co.ent) > A.busy.linesBefore then
			L(E, A.busy.what .. ": done")
			if A.busy.jr then journal(E, co.id, A.busy.jr.kind, A.busy.jr.pos, A.busy.jr.a, A.busy.jr.b) end
			A.busy = nil
		elseif A.busy.vehBefore and #myVehicles(E, co.ent) > A.busy.vehBefore then
			-- (what a bus costs: measured on the company's account)
			local paid = (A.busy.moneyBefore or 0) - balanceOf(E, co.ent)
			-- (a truck's price kept apart: taken for a bus's, it held the bus lines back until the company had a million)
			if paid > 10000 and paid < 5000000 then
				-- (never under the price of a bus of 1940: the account's difference also holds what the company earned meanwhile, and a
				-- price measured at 2 720 let a company buy at every look)
				paid = math.max(paid, BUS_COST)
				if A.busy.jr and A.busy.jr.kind == "truck" then A.truckCost = paid else A.busCost = paid end
			end
			L(E, A.busy.what .. ": done" .. (paid > 0 and (", paid " .. math.floor(paid)) or ""))
			if A.busy.jr then journal(E, co.id, A.busy.jr.kind, A.busy.jr.pos, A.busy.jr.a, A.busy.jr.b) end
			A.busy = nil
		elseif A.busy.until_ and G.frames >= A.busy.until_ then A.busy = nil
		elseif age > 1200 then L(E, A.busy.what .. ": no answer, given up"); A.busy = nil end
		if A.busy then return end
	end
	local money = balanceOf(E, co.ent)
	local stops = myStops(E, co.ent)
	local depots = myDepots(E, co.ent)
	local lines = myLines(E, co.ent)
	local vehicles = myVehicles(E, co.ent)
	-- (0.5.14) the money kept back: the level's, and at least a few months of what its vehicles cost to run (a fixed reserve let a
	-- grown fleet fall into debt at its first bad months). Read at most every 10 s. MPFEVER_AIRESERVE=0: the level's only
	if os.getenv("MPFEVER_AIRESERVE") ~= "0" then
		if not A.runAt or G.frames - A.runAt > 600 then
			A.runAt = G.frames
			local run = 0
			for _, v in ipairs(vehicles) do
				local ok, c = pcall(function() return E.api.engine.util.vehicle.getRunningCost(v.e) end)
				if ok and type(c) == "number" then run = run + c end
			end
			A.runCost = run
		end
		RESERVE = math.max(LV.reserve, LV.reserve / 2 + (A.runCost or 0) * (LV.runMonths or 4) / 12)
	end
	if G.frames - (A.reportAt or -100000) > 1800 then
		A.reportAt = G.frames
		-- (0.5.14: what it keeps back, its lines' result together over the last two months and its fleet's running costs a year)
		local res = companyResult(E, lines)
		L(E, string.format("company %d (entity %d): money %d, %d stop(s), %d depot(s), %d line(s), %d vehicle(s), kept back %d, lines' 2-month result %s, running costs %d a year",
			co.id, co.ent, money, #stops, #depots, #lines, #vehicles, math.floor(RESERVE), res and tostring(math.floor(res)) or "?", math.floor(A.runCost or 0)))
	end
	-- where each line runs: the middle of its stops (the garage of its new buses is looked for from there)
	local groupPos = {}
	for _, s in ipairs(stops) do groupPos[s.group] = s.pos end
	for _, l in ipairs(lines) do
		local n, mx, my = 0, 0, 0
		for _, g in ipairs(l.groups) do if groupPos[g] then n = n + 1; mx = mx + groupPos[g].x; my = my + groupPos[g].y end end
		if n > 0 then l.mid = { x = mx / n, y = my / n } end
	end
	-- vehicles without a line go to the line they were bought for, else the company's last line (once a minute at most each)
	A.lineSent = A.lineSent or {}
	for _, v in ipairs(vehicles) do
		local okD, vdepot = pcall(function() return E.api.engine.getComponent(v.e, E.api.type.ComponentType.TRANSPORT_VEHICLE).depot end)
		local linked = okD and type(vdepot) == "number" and vdepot >= 0 and depotLinked(E, vdepot)
		if (v.line == nil or v.line < 0) and #lines > 0 and not A.noAssign and linked then
			if G.frames - (A.lineSent[v.e] or -100000) > 3600 then
				A.lineSent[v.e] = G.frames
				local target = lines[#lines].e
				for _, l in ipairs(lines) do if l.e == A.forLine then target = l.e end end
				act(E, co.id, "makeVehicleSetLineCmd", { n = 3, [1] = v.e, [2] = target, [3] = 0 })
				A.busy = { what = "vehicle " .. v.e .. " to line " .. target, since = G.frames, until_ = G.frames + 120 }
				L(E, "vehicle " .. v.e .. " sent to line " .. target)
				return
			elseif G.frames - A.lineSent[v.e] == 600 or G.frames - A.lineSent[v.e] == 601 or (G.frames - A.lineSent[v.e]) % 1800 < TICK then
				pcall(function()
					local tv = E.api.engine.getComponent(v.e, E.api.type.ComponentType.TRANSPORT_VEHICLE)
					L(E, "vehicle " .. v.e .. " still without a line: " .. E.C.ser(E.C.marshal(tv)):sub(1, 600))
				end)
			end
		end
	end
	-- the lines first (a bus more where full, a broken line given up), then the best pair of towns, then the big towns' own lines
	-- (the towns' own lines across their streets first, as the players' best filled lines; then the lines between towns)
	sampleUse(E, lines)
	if manageLines(E, co, lines, vehicles, money) then return end
	-- every freight line its first two trucks as soon as it is there (whatever the turn of the projects below: a line left without a
	-- truck was given up as empty after a few looks)
	if os.getenv("MPFEVER_AIFREIGHT") ~= "0" then
		A.trucksFor = A.trucksFor or {}
		for _, l in ipairs(lines) do
			local f = freightOf(E, l)
			-- (0.5.14: the trucks it has, not the ones asked for: two refused purchases left a line with no truck, given up as empty
			-- soon after; at most 5 asks. MPFEVER_AIRETRY=0: two asks as before)
			local asks = os.getenv("MPFEVER_AIRETRY") == "0" and 2 or 5
			if f and (A.trucksFor[l.e] or 0) < asks then
				local n = 0
				for _, v in ipairs(vehicles) do if v.line == l.e then n = n + 1 end end
				if n >= 2 then A.trucksFor[l.e] = asks
				elseif money > RESERVE + (A.truckCost or BUS_COST) then
					local depot = garagesNear(E, co.ent, f.from.pos, 5000)[1]
					if depot then
						A.trucksFor[l.e] = (A.trucksFor[l.e] or 0) + 1
						A.forLine = l.e
						buyTruck(E, co, depot.depot, f.cargo)
						return
					end
				end
			end
		end
	end
	-- (0.5.14: whether it may open something new now, see mayExpand)
	local grow = mayExpand(E, co, lines, money)
	-- freight: a route of trucks while the company has fewer freight lines than half its lines (one at first), then the buses
	if os.getenv("MPFEVER_AIFREIGHT") ~= "0" and grow then
		local nf = 0
		for _, l in ipairs(lines) do if freightOf(E, l) then nf = nf + 1 end end
		-- (a path search alone builds nothing: the buses' work goes on in the same look)
		if nf < math.max(1, math.ceil(#lines * LV.freightShare)) and freightProject(E, co, stops, lines, vehicles, money) == true then return end
	end
	-- (Normal and Hard, 0.5.14: the lines between towns before the towns' own lines, a fare grows with the distance flown and the
	-- short town lines earn the least. MPFEVER_AIORDER=0: the towns first, as before)
	local pairsFirst = LV.profitFirst and os.getenv("MPFEVER_AIORDER") ~= "0"
	if pairsFirst and pairProject(E, co, stops, lines, vehicles, money, grow) then return end
	for _, t in ipairs(townsForLines(E, co.ent)) do
		local town = t.e
		if (A.skipTown and A.skipTown[town]) or t.size < LV.townMin then goto continue end
		do
			-- the garage of the town's buses (see garageFor)
			local tc = centre(E, town, E.api.type.enum.LandUseType.RESIDENTIAL)
			if not tc then goto continue end
			local g = garageFor(E, co, tc, money, townName(E, town))
			if g == "building" then return end
			if not g then
				if not (A.noGarage and A.noGarage[town]) then
					A.noGarage = A.noGarage or {}; A.noGarage[town] = true
					L(E, "no road garage joined to the streets within 4 km of " .. townName(E, town) .. ": town skipped for now")
				end
				goto continue
			end
			local have, missing = townProject(E, co, town, stops)
			-- (a town's line not begun yet: only when the company may grow, see mayExpand)
			if not grow and #missing > 0 and not lineFor(E, lines, (function() local g = {} for _, h in ipairs(have) do g[#g + 1] = h.stop.group end return g end)()) then goto continue end
			if #missing > 0 then
				-- (a town's line is begun only with the money to end it: its stops and two buses; stops left without a line cost
				-- their upkeep for nothing)
				if money < RESERVE + 30000 * #missing + 2 * (A.busCost or BUS_COST) then return end
				local w = missing[1]
				local avoid = {}
				for _, s in ipairs(stops) do avoid[#avoid + 1] = s.pos end
				-- (within the 200 m townProject takes, 0.5.14: a stop built 200 to 300 m away was never found again and another one
				-- was built, and another, until the town ran out of streets. MPFEVER_AIRETRY=0: 300 m as before)
				local segs = streetSegmentsNear(E, w.p, os.getenv("MPFEVER_AIRETRY") == "0" and 300 or 200, avoid)
				local tries = A.failed and A.failed["stop " .. town .. ":" .. w.use] or 0
				local s = segs[1 + tries]
				if not s or tries > 4 then
					-- (a point of the ring is left out; a district centre without a stop leaves the town)
					-- (0.5.14: a district centre too when the town has two stops already: the line is made with those, its stops were
					-- left without a line before. MPFEVER_AIRETRY=0: the town skipped)
					if w.use:sub(1, 4) == "RING" or (#have >= 2 and os.getenv("MPFEVER_AIRETRY") ~= "0") then
						L(E, "no street for the stop " .. w.use .. " of " .. townName(E, town) .. ": point left out")
						A.dropPoint = A.dropPoint or {}; A.dropPoint[town .. ":" .. w.use] = true
						return
					end
					L(E, "no street for a stop near the " .. w.use .. " centre of " .. townName(E, town) .. ": town skipped")
					A.skipTown = A.skipTown or {}; A.skipTown[town] = true
					goto continue
				end
				L(E, "stop near the " .. w.use .. " centre of " .. townName(E, town) .. " (" .. math.floor(s.d) .. " m from it)")
				buildStop(E, co, s.e, town .. ":" .. w.use)
				-- (a refused stop counts against that centre: the next try takes the next segment)
				A.busy.what = "stop " .. town .. ":" .. w.use
				return
			end
			-- a depot of the company within 400 m of the stops
			local groups, mid = {}, { x = 0, y = 0 }
			for _, h in ipairs(have) do groups[#groups + 1] = h.stop.group; mid.x = mid.x + h.stop.pos.x / #have; mid.y = mid.y + h.stop.pos.y / #have end
			if #groups < 2 then
				if not (A.oneStop and A.oneStop[town]) then
					A.oneStop = A.oneStop or {}; A.oneStop[town] = true
					L(E, townName(E, town) .. " has room for one stop only: no line there")
				end
				goto continue
			end
			-- a garage joined to the streets within 4 km (its own first): the buses are bought there
			local depot = garagesNear(E, co.ent, mid, 5000)[1]
			if not depot then
				if not (A.noGarage and A.noGarage[town]) then
					A.noGarage = A.noGarage or {}; A.noGarage[town] = true
					L(E, "no road garage joined to the streets within 4 km of " .. townName(E, town) .. ": town skipped for now")
				end
				goto continue
			end
			local line = lineFor(E, lines, groups)
			if not line then
				-- (a line only with the money for its first two buses, as the lines between towns: a line left without one is given up
				-- as empty after a few looks, its stops kept for nothing)
				if money < RESERVE + 2 * (A.busCost or BUS_COST) then return end
				if not grow then goto continue end
				createLine(E, co, groups, town)
				return
			end
			-- buses: two at first, more as the town is bigger
			local onLine = 0
			for _, v in ipairs(vehicles) do if v.line == line.e then onLine = onLine + 1 end end
			local wantBuses = math.min(5, LV.maxBus, 2 + math.floor(#groups / 2))
			if onLine < wantBuses and not A.noBuses then
				if money < RESERVE + (A.busCost or BUS_COST) then return end
				A.forLine = line.e
				buyBus(E, co, depot.depot)
				return
			end
		end
		::continue::
	end
	-- every line two buses at least (the lines between towns too)
	for _, l in ipairs(lines) do
		local n = 0
		for _, v in ipairs(vehicles) do if v.line == l.e then n = n + 1 end end
		if n < 2 and not A.noBuses and money > RESERVE + (A.busCost or BUS_COST) and ((A.emptyRuns or {})[l.e] or 0) == 0 then
			local f = os.getenv("MPFEVER_AIFREIGHT") ~= "0" and freightOf(E, l)
			local depot = garagesNear(E, co.ent, l.mid or (f and f.from.pos) or { x = 0, y = 0 }, 5000)[1]
			if depot then
				A.forLine = l.e
				buyFor(E, co, l, depot.depot)
				return
			end
		end
	end
	if not pairsFirst then pairProject(E, co, stops, lines, vehicles, money, grow) end
end

-- (for the dev probes)
M.f = { aiCompany = aiCompany, myStops = myStops, myDepots = myDepots, myLines = myLines, myVehicles = myVehicles, bestBus = bestBus,
	act = act, build = build, buildStop = buildStop, createLine = createLine, buyBus = buyBus, join = join, context = context,
	findDepotPlace = findDepotPlace, townsBySize = townsBySize, currentYear = currentYear, garagePlaces = garagePlaces,
	buildGarage = buildGarage, garagesNear = garagesNear, garageCapture = garageCapture, industries = industries, roadTerminals = roadTerminals,
	bestTruck = bestTruck, bestFreight = bestFreight, freightOf = freightOf, roadPath = roadPath, cargoName = cargoName,
	bestTownFreight = bestTownFreight, townWants = townWants, townName = townName }

function M.tick(E, st)
	local G, C = E.G, E.C
	if C.ROLE ~= "host" or G.cmode ~= "separate" then return end
	if not (G.connected and G.session and G.session.started) or G.session.resync or not G.myCo then return end
	-- (nothing while the session is paused: its actions would wait for their turns)
	if G.session.pauseAt ~= nil then return end
	local list = M.listOf(G.coAi)
	if #list == 0 and os.getenv("MPFEVER_AI") == "1" then list = { { n = 1, color = 7 } } end
	if #list == 0 then return end
	-- (the module's own clock, for all its companies)
	G.AIT = G.AIT or {}
	local T = G.AIT
	-- (dev: the companies act only while ai_enable.txt stands in the module's folder)
	local dev = os.getenv("MPFEVER_AIDEV")
	if dev and G.frames % 120 == 0 then
		local f = C.IO.open(dev .. E.BS .. "ai_enable.txt", "rb")
		T.enabled = f ~= nil
		if f then f:close() end
	end
	if dev and not T.enabled then return end
	if G.frames < (T.nextAt or 0) then return end
	-- (a look every half second at most; each company has its own pace, its level's)
	T.nextAt = G.frames + 30
	-- (not before the session's first minute: the joins and the first checks)
	T.firstAt = T.firstAt or (G.frames + 600)
	if G.frames < T.firstAt then return end
	-- one company per look, in turn: the next one whose own look is due
	G.AIS = G.AIS or {}
	local cur
	for _ = 1, #list do
		T.turn = (T.turn or 0) % #list + 1
		local c = list[T.turn]
		G.AIS[c.n] = G.AIS[c.n] or {}
		if G.frames >= (G.AIS[c.n].lookAt or 0) then cur = c; break end
	end
	if not cur then return end
	G.AI = G.AIS[cur.n]
	LV = LEVELS[cur.level or 2] or LEVELS[2]
	RESERVE = LV.reserve
	G.AI.lookAt = G.frames + LV.tick
	if G.AI.levelSaid ~= LV.name then G.AI.levelSaid = LV.name; E.log("AI" .. cur.n .. " level " .. LV.name) end
	AINUM, AIKEY = cur.n, "ai:" .. cur.n
	AICOLOR = (cur.color and cur.color >= 1 and cur.color <= #E.CO.PALETTE) and cur.color or nil
	-- (its start money, the host's choice for it; else the players')
	AIMONEY = cur.money
	local known = aiCompany(E)
	AINAME = known and known.name ~= "" and known.name or newName(E, cur.n)
	-- (what a step costs this game's interface: the slowest one of each minute is logged)
	local t0 = os.clock()
	local busyBefore = G.AI.busy
	step(E)
	-- (after a purchase, a build or a new line, the level's pause: a Hard company that acted at every look spent its 2 million in
	-- 90 s on a map of 1972, then sold everything in debt)
	if G.AI.busy and G.AI.busy ~= busyBefore then G.AI.lookAt = math.max(G.AI.lookAt or 0, G.frames + (LV.pause or 600)) end
	local dt = os.clock() - t0
	T.slowest = math.max(T.slowest or 0, dt)
	if G.frames - (T.costAt or 0) > 3600 then
		T.costAt = G.frames
		L(E, string.format("slowest step of the last minute: %.3f s (%d compan%s)", T.slowest, #list, #list > 1 and "ies" or "y"))
		T.slowest = 0
	end
	-- (a slow step waits longer before the next one)
	if dt > 0.05 then T.nextAt = G.frames + TICK * 3; G.AI.lookAt = math.max(G.AI.lookAt, G.frames + TICK * 3) end
end

return M
