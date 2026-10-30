-- MPFever 0.6: the public games' options (release/recherche-0.6/09-trouver-joueurs.md, the owner's decisions I2-I8 in
-- 00-REPONSES.md). They are the work of MPFever.exe and of the public list (launcher/PublicGames.cs, serverlist/ServerList.cs),
-- not of the game: this module only declares them, so that the lobby's "Game settings" show them like the others (see
-- docs/FEATURES-0.6.md). Every one is off by default; with all of them off a game is hosted exactly as in 0.5.14.
--   public              the lobby shows in the public list (found by the host's Steam id, joined through Steam with no port to
--                       open); max: the players at most (8, I7); late: it stays listed while the game runs (I2, off: the lobby
--                       only); ip: the host's IP address shown in the list too (I3, the lobby warns the host). The game's name,
--                       "Partie de <name>" / "<name>'s game", is changed in the lobby (I7).
--   join_bans           the host kicks and bans players from the lobby and from the MPFever window; the banned ones are
--                       refused from then on, in its next games too (a list kept on its PC, I4)
--   join_approve        every arrival waits until the host lets it in or not (I4)
--   join_steamfriends   a private game takes Steam connections from the host's Steam friends only (I6); joining by address
--                       still works, and a public game takes everybody
-- No moderation of the list in v1 (I8). The texts of the values go through T(fr, en) of the options host.
local M = {}
M.ID = "public"
M.OPTIONS = {
	{ id = "public",
		title = { "Partie publique", "Public game" },
		desc = { "Le salon apparaît dans la liste publique des parties : n'importe quel joueur de la même version peut le rejoindre par Steam, sans port à ouvrir.",
			"The lobby shows in the public list of games: any player with the same version can join it through Steam, with no port to open." },
		modes = "both",
		params = {
			{ id = "max", label = { "Joueurs au maximum", "Players at most" }, values = { 2, 3, 4, 5, 6, 7, 8 }, default = 8 },
			{ id = "late", label = { "Arrivées pendant la partie", "Arrivals during the game" }, values = { 0, 1 }, default = 0,
				show = function(v, T) return v == 1 and T("Oui (chacune recharge la partie de tous)", "Yes (each one reloads everybody's game)") or T("Non (salon seulement)", "No (lobby only)") end },
			{ id = "ip", label = { "Montrer mon adresse IP", "Show my IP address" }, values = { 0, 1 }, default = 0,
				show = function(v, T) return v == 1 and T("Oui (visible par tous)", "Yes (shown to everybody)") or T("Non (par Steam seulement)", "No (through Steam only)") end },
		} },
	{ id = "join_bans",
		title = { "Exclure et bannir", "Kick and ban" },
		desc = { "L'hôte peut exclure ou bannir un joueur depuis le salon et la fenêtre MPFever. Les bannis sont refusés, aussi dans ses parties suivantes.",
			"The host can kick or ban a player from the lobby and the MPFever window. Banned players are refused, in its next games too." },
		modes = "both" },
	{ id = "join_approve",
		title = { "Accepter chaque arrivée", "Approve every arrival" },
		desc = { "Chaque joueur qui arrive attend que l'hôte l'accepte ou le refuse (salon ou fenêtre MPFever).",
			"Every player who arrives waits until the host accepts or refuses them (lobby or MPFever window)." },
		modes = "both" },
	{ id = "join_steamfriends",
		title = { "Steam : amis seulement", "Steam: friends only" },
		desc = { "Une partie privée n'accepte par Steam que vos amis Steam. Rejoindre par l'adresse reste possible.",
			"A private game takes only your Steam friends through Steam. Joining by the address still works." },
		modes = "both" },
}
return M
