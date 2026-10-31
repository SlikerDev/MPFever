"""The place of the main menu's « Multiplayer » card (mpfever_menu.lua, cardPlace), offline (lupa, Lua 5.2).

Up to 0.6.2 the card sat in the main page's top left corner and covered the game's own lines there (the player's profile, the
edition, the Mod Hub's state). It now sits beside the game's cards, left of their bottom row. The real cardPlace is taken from
the file and its result laid out the way the game's FloatingLayout does (an item at h, v of the room left: x = h * (W - w)),
on the main page as main_page.tl, main_menu.css.lua and main_menu_sizes.lua build it, in the menu's units (a 1920 x 1080
screen scaled to the window by the smaller of width / 1920 and height / 1080). Checked on 1280 x 720 to 2560 x 1440, 16:10,
21:9, 32:9 and 5:4 screens, with the standard and the deluxe logo:
  - the card is on the screen, at least 16 units from its edges;
  - it covers none of the game's cards, nor the top bar (profile, edition lines, Mod Hub state, buttons), nor the version;
  - it keeps to the cards: the gap to them is the one between the game's cards (10), its middle at the bottom row's middle;
  - MPFEVER_MENUCARD=old gives the old place (top left, which covered the top bar's left column);
  - the card's item lets the mouse through (the game's cards under its empty part stay clickable).
Run: python tests/test_menucard.py
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
MENU = os.path.join(HERE, "..", "mod", "mpfever_1", "content", "mpfever_menu.lua")
failures = []


def check(cond, name, got=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f": {got}" if got != "" and not cond else ""))
    if not cond:
        failures.append(name)


src = open(MENU, encoding="utf-8").read()
m = re.search(r"^\tlocal function cardPlace\(how, deluxe\)\n.*?^\tend\n", src, re.S | re.M)
if not m:
    print("FAIL: cardPlace not found in mpfever_menu.lua")
    sys.exit(1)
L = lua52.LuaRuntime(unpack_returned_tuples=True)
L.execute(m.group(0).replace("local function cardPlace", "function cardPlace", 1))
place_lua = L.eval("function(how, deluxe) local p = cardPlace(how, deluxe) return p.h, p.v, p.padding[1], p.padding[2], p.padding[3], p.padding[4] end")

# the game's main page (main_menu.css.lua, main_menu_sizes.lua): card sizes with their margins, the logo, the top bar
MARGIN = 5
HALF_W, HALF_H = 1600 / 2 - 5 - 1, 640 / 2 - 5 - 1          # New Game, Campaign
QUARTER_W = 1600 / 4 - 1.5 * 5 - 1.5 * 1                   # Map Editor, Mod Hub, Continue, Load Game
ROWS_W = HALF_W + 2 * MARGIN + QUARTER_W + 2 * MARGIN       # 1205
ROW_H = HALF_H + 2 * MARGIN                                 # 324
CARD_W, CARD_H = 316, 181                                   # small-rectangle-card


def logo_block(deluxe):
    return -18 + (297.5 if deluxe else 272) + (36 if deluxe else 28)


def rect_overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def layout(sw, sh, deluxe, how=None):
    s = min(sw / 1920, sh / 1080)
    W, H = sw / s, sh / s
    h, v, pt, pr, pb, pl = place_lua(how, deluxe)
    iw, ih = pl + CARD_W + 2 * MARGIN + pr, pt + CARD_H + 2 * MARGIN + pb
    x, y = (h * (W - iw) if h >= 0 else 0), (v * (H - ih) if v >= 0 else 0)
    card = (x + pl + MARGIN, y + pt + MARGIN, x + pl + MARGIN + CARD_W, y + pt + MARGIN + CARD_H)
    bh = logo_block(deluxe) + 2 * ROW_H
    top = (H - bh) / 2
    gx = (W - ROWS_W) / 2
    grid_top = top + logo_block(deluxe)
    grid = (gx + MARGIN, grid_top + MARGIN, gx + ROWS_W - MARGIN, grid_top + 2 * ROW_H - MARGIN)
    row2 = (grid_top + ROW_H, grid_top + 2 * ROW_H)
    bar_l = (W - 1698) / 2
    # (the top bar's left column: profile, edition on two lines, the Mod Hub's state; its right one: the four buttons)
    others = {
        "the top bar's left column": (bar_l, 48, bar_l + 360, 48 + 54 + 2 * 26 + 40),
        "the top bar's buttons": (bar_l + 1698 - 320, 48, bar_l + 1698, 48 + 54),
        "the version line": (W - 260, H - 48, W, H),
        "the logo": ((W - 676) / 2, top - 18, (W + 676) / 2, top - 18 + (297.5 if deluxe else 272)),
        "the game's cards": grid,
    }
    return W, H, card, grid, row2, others


SCREENS = [(1280, 720), (1600, 900), (1920, 1080), (2560, 1440), (1920, 1200), (2560, 1080), (3440, 1440), (5120, 1440),
           (5120, 1334), (1280, 1024)]
print("the card beside the game's cards")
for sw, sh in SCREENS:
    for deluxe in (False, True):
        W, H, card, grid, row2, others = layout(sw, sh, deluxe)
        tag = f"{sw} x {sh}{' deluxe' if deluxe else ''}"
        inside = card[0] >= 16 and card[1] >= 16 and card[2] <= W - 16 and card[3] <= H - 16
        hits = [n for n, r in others.items() if rect_overlap(card, r)]
        gap = grid[0] - card[2]
        mid = (card[1] + card[3]) / 2 - (row2[0] + row2[1]) / 2
        ok = inside and not hits and abs(gap - 10) < 0.01 and abs(mid) < 0.01
        check(ok, f"{tag}: on screen, hides nothing, 10 from the cards, centred on their bottom row",
              f"card {tuple(round(c) for c in card)} screen {round(W)} x {round(H)} hits {hits} gap {gap:.1f} offset {mid:.1f}")

print("MPFEVER_MENUCARD=old")
W, H, card, grid, row2, others = layout(1920, 1080, False, "old")
check(tuple(round(c) for c in card[:2]) == (29, 101), "the top left corner, as up to 0.6.2", card)
check(rect_overlap(card, others["the top bar's left column"]), "(where it covered the top bar's left column)")

print("the menu's code")
check(re.search(r'cardPlace\(os\.getenv\("MPFEVER_MENUCARD"\), ', src) is not None, "the switch MPFEVER_MENUCARD is read")
check(re.search(r"FloatingLayoutChild\{ h = place\.h, v = place\.v, item = builtin\.Component\{ mouseTransparent = true, ", src) is not None,
      "the card's item lets the mouse through to the game's cards")
check(chr(92) not in src, "no backslash in the menu's file (see its top)")

if failures:
    print(f"FAIL {len(failures)} case(s): " + "; ".join(failures))
    sys.exit(1)
print("all passed")
sys.exit(0)
