-- Computer companies (AI, experimental, 0.5.12): companies the host's game runs by itself, in the companies mode. The host adds
-- them in its lobby (each with its colour); a savegame's computer companies are taken again by the lobby. Every decision is taken
-- on the host only and goes to the other games exactly as a player's builds and actions do (their replays, their stamps): no new
-- determinism risk. The module keeps no knowledge of its own across loads: each step reads the world (what the company owns) and
-- does the next thing missing, one at a time. Several companies take their steps in turn.
local M = {}

-- the company of the step under way (see M.tick): its key in the registry ("ai:<n>"), its name, its colour (a palette index)
local AIKEY, AINAME, AICOLOR, AINUM = "ai:1", "", 7, 1
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
local RESERVE = 400000     -- money kept back (the lines' first months cost more than they earn)
local BUS_COST = 180000    -- a bus, until the first purchase measures it

local function L(E, s) E.log("AI" .. (AINUM ~= 1 and tostring(AINUM) or "") .. " " .. s) end

-- the computer companies the host chose in its lobby: "n:colour,n:colour" (the session's "ai"), as { { n, color }... }; the
-- developer tests' MPFEVER_AI=1 gives the first one when the session has none
function M.listOf(text)
	local out, seen = {}, {}
	for n, ix in tostring(text or ""):gmatch("(%d+):(%d+)") do
		n, ix = tonumber(n), tonumber(ix)
		if n and n >= 1 and n <= 32 and not seen[n] then seen[n] = true; out[#out + 1] = { n = n, color = ix } end
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
				if ownerOf(E, s) ~= ent then others = others + 1 end
			end
		end)
		t.others = others
		t.score = t.size / (1 + others / 3)
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
local function build(E, coId, cmd, what, ctxBits)
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
	build(E, co.id, cmd, "stop " .. n, CTX_STOP)
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
				local free = okd and pd and not pd.errorState.critical
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
	E.G.AI.busy = { what = "line " .. name, since = E.G.frames, linesBefore = #myLines(E, co.ent) }
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
	E.G.AI.busy = { what = "bus " .. bus.name, since = E.G.frames, vehBefore = #myVehicles(E, co.ent), moneyBefore = balanceOf(E, co.ent) }
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
	for _, l in ipairs(lines) do
		local n, last = 0, nil
		for _, v in ipairs(vehicles) do if v.line == l.e then n = n + 1; last = v.e end end
		local use = meanUse(E, l.e) or lineUse(E, l.e) or 0
		local bal = lineBalance(E, l.e)
		if n > 0 and (not eUse or use < eUse) then emptiest, eUse = { line = l, last = last, n = n }, use end
		-- (empty: few seats used on average, and losing money when its balance is known)
		local empty = n == 0 or (use < 0.08 and (bal == nil or bal <= 0))
		A.emptyRuns[l.e] = empty and ((A.emptyRuns[l.e] or 0) + 1) or 0
		l.use, l.bal = use, bal
		-- (a line that stays empty three looks in a row: its buses sold one by one, the line given up with the last)
		if A.emptyRuns[l.e] >= 3 and n > 0 and period == 7200 then
			L(E, string.format("line %d empty for %d looks: a bus less", l.e, A.emptyRuns[l.e]))
			sellVehicle(E, co, last, "empty line " .. l.e)
			return true
		end
		-- (the line itself goes once its last bus is sold: the engine keeps a line that still has a vehicle)
		if A.emptyRuns[l.e] >= 3 and n == 0 and period == 7200 then
			L(E, "line " .. l.e .. " given up (empty)")
			act(E, co.id, "makeLineDestroyCmd", { n = 1, [1] = l.e })
			A.badPair = A.badPair or {}
			if l.groups[1] and l.groups[2] then A.badPair[math.min(l.groups[1], l.groups[2]) .. "-" .. math.max(l.groups[1], l.groups[2])] = true end
			-- (its stops are demolished afterwards, and a town whose own line it was gets no new one)
			A.deadGroups = A.deadGroups or {}
			for _, g in ipairs(l.groups) do A.deadGroups[g] = true end
			for town, pts in pairs(A.targets or {}) do
				for _, s in ipairs(myStops(E, co.ent)) do
					for _, w in ipairs(pts) do
						if A.deadGroups[s.group] and dist(s.pos, w.p) < 200 then A.skipTown = A.skipTown or {}; A.skipTown[town] = true end
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
	for _, l in ipairs(lines) do
		local n = 0
		for _, v in ipairs(vehicles) do if v.line == l.e then n = n + 1 end end
		local use = l.use
		L(E, string.format("line %d: %d bus(es), %s of the seats used on average, balance of the last 2 months %s%s", l.e, n,
			use and (math.floor(use * 100) .. "%") or "?", l.bal and tostring(math.floor(l.bal)) or "?", probs[l.e] and (", problem " .. tostring(probs[l.e])) or ""))
		if probs[l.e] and n > 0 and (A.problemSeen or {})[l.e] then
			-- (a problem seen twice in a row: the line is given up, its buses go to the company's other lines)
			L(E, "line " .. l.e .. " given up (problem " .. tostring(probs[l.e]) .. ")")
			act(E, co.id, "makeLineDestroyCmd", { n = 1, [1] = l.e })
			-- (its stops are not joined again: keyed by their station groups)
			A.badPair = A.badPair or {}
			if l.groups[1] and l.groups[2] then A.badPair[math.min(l.groups[1], l.groups[2]) .. "-" .. math.max(l.groups[1], l.groups[2])] = true end
			return true
		end
		A.problemSeen = A.problemSeen or {}
		A.problemSeen[l.e] = probs[l.e] and true or nil
		if use and use > 0.75 and n < 8 and money > RESERVE + (A.busCost or BUS_COST) then
			local depot = garagesNear(E, co.ent, l.mid or { x = 0, y = 0 }, 5000)[1]
			if depot then
				A.forLine = l.e
				buyBus(E, co, depot.depot)
				return true
			end
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
	local segs = streetSegmentsNear(E, p, 320, avoid)
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
local function pairProject(E, co, stops, lines, vehicles, money)
	local A = E.G.AI
	local pair = bestPair(E, co, lines, stops)
	if not pair then return false end
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
	L(E, "pair " .. na .. " - " .. nb .. " running (" .. n .. " buses, " .. math.floor(pair.d) .. " m)")
	return true
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
		args = { key = AIKEY, name = AINAME, host = false, mode = "separate", start = G.coStart, color = AICOLOR, cname = AINAME } }
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
		if A.busy.linesBefore and #myLines(E, co.ent) > A.busy.linesBefore then L(E, A.busy.what .. ": done"); A.busy = nil
		elseif A.busy.vehBefore and #myVehicles(E, co.ent) > A.busy.vehBefore then
			-- (what a bus costs: measured on the company's account)
			local paid = (A.busy.moneyBefore or 0) - balanceOf(E, co.ent)
			if paid > 10000 and paid < 5000000 then A.busCost = paid end
			L(E, A.busy.what .. ": done" .. (paid > 0 and (", paid " .. math.floor(paid)) or ""))
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
	if G.frames - (A.reportAt or -100000) > 1800 then
		A.reportAt = G.frames
		L(E, string.format("company %d (entity %d): money %d, %d stop(s), %d depot(s), %d line(s), %d vehicle(s)", co.id, co.ent, money, #stops, #depots, #lines, #vehicles))
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
	for _, t in ipairs(townsForLines(E, co.ent)) do
		local town = t.e
		if (A.skipTown and A.skipTown[town]) or t.size < 500 then goto continue end
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
			if #missing > 0 then
				-- (a town's line is begun only with the money to end it: its stops and two buses; stops left without a line cost
				-- their upkeep for nothing)
				if money < RESERVE + 30000 * #missing + 2 * (A.busCost or BUS_COST) then return end
				local w = missing[1]
				local avoid = {}
				for _, s in ipairs(stops) do avoid[#avoid + 1] = s.pos end
				local segs = streetSegmentsNear(E, w.p, 300, avoid)
				local tries = A.failed and A.failed["stop " .. town .. ":" .. w.use] or 0
				local s = segs[1 + tries]
				if not s or tries > 4 then
					-- (a point of the ring is left out; a district centre without a stop leaves the town)
					if w.use:sub(1, 4) == "RING" then
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
				createLine(E, co, groups, town)
				return
			end
			-- buses: two at first, more as the town is bigger
			local onLine = 0
			for _, v in ipairs(vehicles) do if v.line == line.e then onLine = onLine + 1 end end
			local wantBuses = math.min(5, 2 + math.floor(#groups / 2))
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
			local depot = garagesNear(E, co.ent, l.mid or { x = 0, y = 0 }, 5000)[1]
			if depot then
				A.forLine = l.e
				buyBus(E, co, depot.depot)
				return
			end
		end
	end
	pairProject(E, co, stops, lines, vehicles, money)
end

-- (for the dev probes)
M.f = { aiCompany = aiCompany, myStops = myStops, myDepots = myDepots, myLines = myLines, myVehicles = myVehicles, bestBus = bestBus,
	act = act, build = build, buildStop = buildStop, createLine = createLine, buyBus = buyBus, join = join, context = context,
	findDepotPlace = findDepotPlace, townsBySize = townsBySize, currentYear = currentYear, garagePlaces = garagePlaces,
	buildGarage = buildGarage, garagesNear = garagesNear, garageCapture = garageCapture }

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
	T.nextAt = G.frames + TICK
	-- (not before the session's first minute: the joins and the first checks)
	T.firstAt = T.firstAt or (G.frames + 600)
	if G.frames < T.firstAt then return end
	-- one company per look, in turn
	T.turn = (T.turn or 0) % #list + 1
	local cur = list[T.turn]
	G.AIS = G.AIS or {}
	G.AIS[cur.n] = G.AIS[cur.n] or {}
	G.AI = G.AIS[cur.n]
	AINUM, AIKEY = cur.n, "ai:" .. cur.n
	AICOLOR = (cur.color and cur.color >= 1 and cur.color <= #E.CO.PALETTE) and cur.color or nil
	local known = aiCompany(E)
	AINAME = known and known.name ~= "" and known.name or newName(E, cur.n)
	-- (what a step costs this game's interface: the slowest one of each minute is logged)
	local t0 = os.clock()
	step(E)
	local dt = os.clock() - t0
	T.slowest = math.max(T.slowest or 0, dt)
	if G.frames - (T.costAt or 0) > 3600 then
		T.costAt = G.frames
		L(E, string.format("slowest step of the last minute: %.3f s (%d compan%s)", T.slowest, #list, #list > 1 and "ies" or "y"))
		T.slowest = 0
	end
	-- (a slow step waits longer before the next one)
	if dt > 0.05 then T.nextAt = G.frames + TICK * 3 end
end

return M
