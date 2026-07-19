"""Generate the OmniCast pixel office layout (ChatDev-style zones).

Agents that work in the same pipeline stage sit CLUSTERED in one zone, each at a
fixed desk whose chair uid = "seat-<agent_id>" so the UI can pin every agent to
its zone via agentCreated{seatId}. 29x25 grid fills the iframe at the fixed 2x zoom.

Zones (signpost-style WHITEBOARD marker + distinct floor colour per zone):
  Discovery (wood)  : research, scorer, scanner
  Script (wood)     : writer, critic
  Visual (green)    : visual, media
  QA (violet)       : compliance, quality
  Publish (blue)    : upload, abtest, analytics
Center = reception (CHATDEV-style desk area, decor only).
"""
import json, time, sys

COLS, ROWS = 29, 25
WALL, EMPTY = 0, 255
WOOD, BLUE, GREEN, VIOLET = 7, 1, 3, 2

tiles = [[WALL] * COLS for _ in range(ROWS)]
furniture = []
_uid = 0
def auto_uid():
    global _uid; _uid += 1
    return f"f-gen-{_uid}"
def add(t, c, r, uid=None):
    furniture.append({"uid": uid or auto_uid(), "type": t, "col": c, "row": r})
def carve(x0, y0, x1, y1, floor):
    for r in range(y0, y1 + 1):
        for c in range(x0, x1 + 1):
            tiles[r][c] = floor
def door(c, r, floor): tiles[r][c] = floor

# ── 6 rooms (2 cols × 3 bands) ────────────────────────────────────────────────
rooms = {
    'discovery': (1, 1, 13, 7, WOOD),
    'reception': (15, 1, 27, 7, BLUE),
    'script':    (1, 9, 13, 15, WOOD),
    'visual':    (15, 9, 27, 15, GREEN),
    'qa':        (1, 17, 13, 23, VIOLET),
    'publish':   (15, 17, 27, 23, WOOD),
}
for (x0, y0, x1, y1, fl) in rooms.values():
    carve(x0, y0, x1, y1, fl)
# doors (keep walkable/connected)
door(14, 4, WOOD); door(14, 5, WOOD)
door(14, 12, WOOD); door(14, 13, GREEN)
door(14, 20, WOOD); door(14, 21, WOOD)
for c in (6, 7):
    door(c, 8, WOOD); door(c + 14, 8, WOOD); door(c, 16, WOOD); door(c + 14, 16, WOOD)

# ── workstation: desk(3x2)+PC on top + chair below (faces UP → seat). ──────────
# chair uid is fixed per agent so the UI can pin agents to their zone seat.
def ws(c, r, seat_uid):
    add("DESK_FRONT", c, r)
    add("PC_FRONT_OFF", c + 1, r)
    add("CUSHIONED_CHAIR_BACK", c + 1, r + 2, uid=seat_uid)

# agent → zone, clustered. Each gets one workstation inside its room.
ZONE_AGENTS = {
    'discovery': ['research', 'scorer', 'scanner'],
    'script':    ['writer', 'critic'],
    'visual':    ['visual', 'media'],
    'qa':        ['compliance', 'quality'],
    'publish':   ['upload', 'abtest', 'analytics'],
}
# desk anchor offsets within a 13x7 room (cluster 2-3 desks)
SLOTS = [(1, 1), (6, 1), (1, 4)]  # up to 3 workstations per room
for zone, agents in ZONE_AGENTS.items():
    x0, y0, x1, y1, fl = rooms[zone]
    for i, agent in enumerate(agents):
        sx, sy = SLOTS[i]
        ws(x0 + sx, y0 + sy, seat_uid=f"seat-{agent}")

# ── reception (center room): CHATDEV-style desk + sofas + plants (decor only) ─
rx0, ry0, rx1, ry1, _ = rooms['reception']
add("COFFEE_TABLE", 20, 3); add("SOFA_FRONT", 20, 1); add("SOFA_SIDE", 18, 3)
add("SOFA_SIDE:left", 23, 3); add("COFFEE", 20, 4)
add("LARGE_PAINTING", 16, 1); add("PLANT", 26, 2); add("HANGING_PLANT", 21, 1)

# ── zone signposts (WHITEBOARD marker) + decor per room top wall ──────────────
def decor(zone):
    x0, y0, x1, y1, fl = rooms[zone]
    add("WHITEBOARD", x0 + 4, y0)          # zone "signpost"
    add("DOUBLE_BOOKSHELF", x0 + 1, y0)
    add("HANGING_PLANT", x0, y0); add("HANGING_PLANT", x1, y0)
    add("PLANT", x1 - 1, y1 - 1)
for zone in ZONE_AGENTS:
    decor(zone)
add("BIN", 13, 23); add("PLANT_2", 27, 23); add("CLOCK", 7, 1)

# ── tile colours (every tile needs one) ───────────────────────────────────────
TILE_COLOR = {
    0: {"h": 214, "s": 30, "b": -100, "c": -55},
    1: {"h": 209, "s": 39, "b": -25, "c": -80},
    2: {"h": 280, "s": 22, "b": -32, "c": -74},
    3: {"h": 140, "s": 28, "b": -34, "c": -76},
    7: {"h": 25, "s": 48, "b": -43, "c": -88},
    9: {"h": 209, "s": 0, "b": -16, "c": -8},
}
flat, colors = [], []
for r in range(ROWS):
    for c in range(COLS):
        t = tiles[r][c]; flat.append(t); colors.append(TILE_COLOR.get(t))

layout = {"version": 1, "cols": COLS, "rows": ROWS, "layoutRevision": int(time.time()),
          "tiles": flat, "tileColors": colors, "furniture": furniture}
out = sys.argv[1] if len(sys.argv) > 1 else "office-layout.json"
with open(out, "w", encoding="utf-8") as f:
    json.dump(layout, f)
seats = [x["uid"] for x in furniture if x["uid"].startswith("seat-")]
print(f"wrote {out}: {COLS}x{ROWS}, {len(furniture)} furniture, {len(seats)} zone seats: {seats}")
