"""
Soul Exter — Trading Floor Blueprint
====================================

Single source of truth for the geometry of the trading floor.  The *same*
blueprint drives:

  * the 3D scene that the browser renders (served as JSON over /api/layout), and
  * the navigation mesh used by the A* walker on the server, so an avatar can
    never clip through a wall, a desk or a cabin: every trade physically walks a
    clean pathway, enters a cabin through its door, stands at the hearing table,
    walks back out and continues to the next cabin.

Coordinate system (plan view, matches the browser 1:1):

    +x  ->  east  (right)
    +z  ->  south (down / towards the camera)
    +y  ->  up

    z = -23  ┌──────────────────────────────────────────────────────────┐
             │  CABIN 01 │ CABIN 02 │  CABIN 03  │ CABIN 04 │ CABIN 05 │   NORTH WING
    z = -15  ├───────────┴──────────┴─── THE CORRIDOR ───┴──────────┴──────────┤
             │  corner desks ...        MAIN AVENUE        ... corner desks   │   TRADING FLOOR
    z =  -9  ├───────────────────────────────────────────────┬──────────────┤
             │ desks │ avenue │ desks │ east concourse │ CEO CHAMBER (exec)│
    z =   8  ├───────────────────────────────────────────────┼──────────────┤
             │            ARRIVAL HALL / SECURITY            │ DEBATE CHAMBER  │
    z =  26  └──── WELCOME GATE ──────────────── EXIT GATE ──┴──────────────────┘
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------- constants --
HALL = dict(x0=-46.0, z0=-28.6, x1=46.0, z1=32.6, h=11.5)

WALL_T = 0.36          # wall thickness (m)
CELL = 0.26            # nav-grid cell size (m)
WALK_SPEED = 1.55      # m/s — relaxed, human, unhurried floor walk
AVATAR_R = 0.34        # avatar radius used to inflate blockers
CLEARANCE = 0.18       # conservative half-cell slack when painting blockers

CABIN_PITCH = 15.2
CABIN_CENTERS = [-30.4, -15.2, 0.0, 15.2, 30.4]
CABIN_W = 14.2          # interior width
CABIN_Z0, CABIN_Z1 = -27.8, -19.4   # interior depth band
CORRIDOR_Z0, CORRIDOR_Z1 = -19.4, -12.0

DESK_ROWS_Z = [-8.8, -3.0, 2.8, 8.6]
DESK_W, DESK_D = 2.4, 1.6
POD_GAP = 0.40           # desks inside a pod sit this close (staff squeeze through)
AISLE = 3.30             # walking aisle between pods — wide boulevards, no congestion
POD_PITCH = 2 * DESK_W + POD_GAP + AISLE


def _desk_columns() -> list:
    cols = []
    for block_start in (-43.2, -13.8):
        for pod in range(3):
            base = block_start + pod * POD_PITCH
            cols.append(base + DESK_W / 2)
            cols.append(base + DESK_W + POD_GAP + DESK_W / 2)
    return cols


BLOCK_A_X = _desk_columns()[:6]
BLOCK_B_X = _desk_columns()[6:]

CONCOURSE_X = (13.6, 17.8)          # east spine: corridor -> exec -> lobby
EXEC = dict(x0=19.0, z0=-12.0, x1=42.2, z1=0.4)     # CEO chamber interior
VAULT = dict(x0=19.0, z0=2.6, x1=42.2, z1=10.6)     # data vault (glass, decorative)
DEBATE = dict(x0=18.6, z0=12.8, x1=42.2, z1=30.4)  # debate chamber interior

ENTRY_GATE_X = -17.5
EXIT_GATE_X = 9.5
GATE_W = 3.4
SOUTH_WALL_Z = 31.6


# ------------------------------------------------------------------- shapes --
@dataclass
class Rect:
    x0: float
    z0: float
    x1: float
    z1: float

    @property
    def w(self) -> float:
        return abs(self.x1 - self.x0)

    @property
    def d(self) -> float:
        return abs(self.z1 - self.z0)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cz(self) -> float:
        return (self.z0 + self.z1) / 2.0

    def contains(self, x: float, z: float, pad: float = 0.0) -> bool:
        return (self.x0 - pad <= x <= self.x1 + pad) and (self.z0 - pad <= z <= self.z1 + pad)

    def inflate(self, r: float) -> "Rect":
        return Rect(self.x0 - r, self.z0 - r, self.x1 + r, self.z1 + r)

    def as_list(self) -> List[float]:
        return [round(self.x0, 3), round(self.z0, 3), round(self.x1, 3), round(self.z1, 3)]

    def dict(self) -> dict:
        return dict(x0=self.x0, z0=self.z0, x1=self.x1, z1=self.z1, w=self.w, d=self.d, cx=self.cx, cz=self.cz)


@dataclass
class Wall:
    x0: float
    z0: float
    x1: float
    z1: float
    h: float = 3.2
    kind: str = "partition"      # partition | exterior | glass | low
    y: float = 0.0

    def dict(self) -> dict:
        return dict(x0=self.x0, z0=self.z0, x1=self.x1, z1=self.z1, h=self.h, kind=self.kind, y=self.y)

    def as_rect(self) -> Rect:
        return Rect(min(self.x0, self.x1), min(self.z0, self.z1), max(self.x0, self.x1), max(self.z0, self.z1))


@dataclass
class Door:
    id: str
    label: str
    x: float
    z: float
    width: float
    axis: str                 # 'z' wall (opening travels along x) | 'x' wall (opening travels along z)
    kind: str = "interior"    # interior | cabin | exec | debate | entry | exit | vault
    room: Optional[str] = None
    facing: str = "south"

    def dict(self) -> dict:
        return dict(id=self.id, label=self.label, x=self.x, z=self.z, width=self.width,
                    axis=self.axis, kind=self.kind, room=self.room, facing=self.facing)


@dataclass
class Room:
    id: str
    label: str
    subtitle: str
    kind: str                 # cabin | exec | debate | vault | hall | plaza
    rect: Rect
    accent: str = "#7dd3fc"

    def dict(self) -> dict:
        return dict(id=self.id, label=self.label, subtitle=self.subtitle, kind=self.kind,
                    rect=self.rect.as_list(), accent=self.accent)


@dataclass
class Prop:
    kind: str                 # desk | chair | monitor | planter | pillar | table | sofa | rack | screen ...
    x: float
    z: float
    rot: float = 0.0
    w: float = 1.0
    d: float = 1.0
    h: float = 1.0
    y: float = 0.0
    meta: dict = field(default_factory=dict)

    @property
    def blocks(self) -> bool:
        return bool(self.meta.get("blocks", True))

    def dict(self) -> dict:
        return dict(kind=self.kind, x=self.x, z=self.z, rot=self.rot, w=self.w, d=self.d,
                    h=self.h, y=self.y, meta=self.meta)


@dataclass
class Sign:
    text: str
    x: float
    z: float
    y: float = 2.6
    kind: str = "plate"       # plate | gate | cabin | wall | screen
    sub: str = ""
    accent: str = "#38bdf8"
    width: float = 3.2
    rot: float = 0.0

    def dict(self) -> dict:
        return dict(text=self.text, x=self.x, z=self.z, y=self.y, kind=self.kind, sub=self.sub,
                    accent=self.accent, width=self.width, rot=self.rot)


@dataclass
class Desk:
    id: str
    index: int
    x: float
    z: float
    block: str
    row: int
    col: int

    @property
    def seat(self) -> Tuple[float, float]:
        """Where the trader sits: north side of the desk, facing south."""
        return (self.x, self.z - DESK_D / 2 - 1.05)

    @property
    def stand(self) -> Tuple[float, float]:
        """Where a standing trader waits: south cross-aisle of the same row."""
        return (self.x, self.z + DESK_D / 2 + 1.25)

    def dict(self) -> dict:
        return dict(id=self.id, index=self.index, x=self.x, z=self.z, block=self.block,
                    row=self.row, col=self.col, rot=0.0,
                    seat=[round(self.seat[0], 3), round(self.seat[1], 3)])


# ------------------------------------------------------------ wall builder --
def _ring(rect: Rect, doors: Sequence[dict]) -> List[Wall]:
    """Build the four walls of an interior rect, leaving gaps for its doors."""
    x0, z0, x1, z1 = rect.x0, rect.z0, rect.x1, rect.z1
    t = WALL_T
    walls: List[Wall] = []

    def openings(side: str) -> List[Tuple[float, float]]:
        out = []
        for d in doors:
            if d.get("side") != side:
                continue
            half = d["width"] / 2.0
            if side in ("n", "s"):
                out.append((d["x"] - half, d["x"] + half))
            else:
                out.append((d["z"] - half, d["z"] + half))
        return sorted(out)

    def segment(a: float, b: float, side: str) -> None:
        """Emit wall pieces along `side` between a..b minus openings."""
        if b - a <= 0.02:
            return
        pieces = [(a, b)]
        for (oa, ob) in openings(side):
            nxt = []
            for (pa, pb) in pieces:
                if ob <= pa or oa >= pb:
                    nxt.append((pa, pb))
                    continue
                if oa > pa:
                    nxt.append((pa, max(pa, oa)))
                if ob < pb:
                    nxt.append((min(pb, ob), pb))
            pieces = nxt
        for (pa, pb) in pieces:
            if pb - pa <= 0.04:
                continue
            if side in ("n", "s"):
                z = z0 if side == "n" else z1
                walls.append(Wall(pa, z - t / 2 if side == "n" else z - t / 2, pb,
                                  z + t / 2 if side == "n" else z + t / 2))
                walls[-1].z0 = z - t / 2
                walls[-1].z1 = z + t / 2
            else:
                x = x0 if side == "w" else x1
                walls.append(Wall(x - t / 2, pa, x + t / 2, pb))

    segment(x0 - t / 2, x1 + t / 2, "n")
    segment(x0 - t / 2, x1 + t / 2, "s")
    segment(z0 - t / 2, z1 + t / 2, "w")
    segment(z0 - t / 2, z1 + t / 2, "e")
    return walls


# ---------------------------------------------------------------- the plan --
class FloorPlan:
    def __init__(self) -> None:
        self.rooms: List[Room] = []
        self.walls: List[Wall] = []
        self.doors: List[Door] = []
        self.props: List[Prop] = []
        self.desks: List[Desk] = []
        self.signs: List[Sign] = []
        self.nodes: Dict[str, Tuple[float, float]] = {}
        self.floor_zones: List[dict] = []

    # -- authoring helpers -------------------------------------------------
    def room(self, rid: str, label: str, subtitle: str, kind: str, rect: Rect,
             accent: str = "#7dd3fc") -> Room:
        r = Room(rid, label, subtitle, kind, rect, accent)
        self.rooms.append(r)
        return r

    def door(self, did: str, label: str, x: float, z: float, width: float, axis: str,
             kind: str = "interior", room: Optional[str] = None, facing: str = "south") -> Door:
        d = Door(did, label, x, z, width, axis, kind, room, facing)
        self.doors.append(d)
        return d

    def sign(self, text: str, x: float, z: float, y: float = 2.6, kind: str = "plate",
             sub: str = "", accent: str = "#38bdf8", width: float = 3.2, rot: float = 0.0) -> Sign:
        s = Sign(text, x, z, y, kind, sub, accent, width, rot)
        self.signs.append(s)
        return s

    def prop(self, kind: str, x: float, z: float, rot: float = 0.0, w: float = 1.0, d: float = 1.0,
             h: float = 1.0, y: float = 0.0, blocks: bool = True, **meta) -> Prop:
        meta["blocks"] = blocks
        p = Prop(kind, x, z, rot, w, d, h, y, meta)
        self.props.append(p)
        return p

    def add_room_with_walls(self, rid: str, label: str, subtitle: str, kind: str, rect: Rect,
                            door_specs: Sequence[dict], accent: str = "#7dd3fc",
                            wall_kind: str = "glass") -> Room:
        r = self.room(rid, label, subtitle, kind, rect, accent)
        for w in _ring(rect, door_specs):
            w.kind = wall_kind
            self.walls.append(w)
        for ds in door_specs:
            axis = "z" if ds["side"] in ("n", "s") else "x"
            facing = {"n": "north", "s": "south", "e": "east", "w": "west"}[ds["side"]]
            self.door(ds["id"], ds.get("label", label), ds["x"] if axis == "z" else ds["x"],
                      ds["z"] if axis == "x" else ds["z"], ds["width"], axis,
                      ds.get("kind", "interior"), rid, facing)
        return r


def build_floor_plan() -> FloorPlan:
    p = FloorPlan()

    # ============================================================ exterior ===
    p.room("hall", "SOUL EXTER", "Autonomous Trading Council", "hall",
           Rect(HALL["x0"], HALL["z0"], HALL["x1"], HALL["z1"]))

    def zone(kind: str, rect: Rect, grow: float = 0.0) -> dict:
        r = rect.inflate(grow) if grow else rect
        return dict(kind=kind, rect=r.as_list())

    p.floor_zones = [
        zone("floor_main", Rect(-44.6, -12.0, 12.6, 11.6)),        # trading pit
        zone("corridor", Rect(HALL["x0"] + 1.4, CORRIDOR_Z0, HALL["x1"] - 1.4, CORRIDOR_Z1)),
        zone("concourse", Rect(13.6, CORRIDOR_Z0, 17.8, 10.4)),
        zone("lobby", Rect(HALL["x0"] + 1.4, 10.4, HALL["x1"] - 1.4, SOUTH_WALL_Z)),
        zone("plaza", Rect(HALL["x0"] + 1.4, SOUTH_WALL_Z, HALL["x1"] - 1.4, 49.0)),
        # rooms: grown so the floor runs right up to (and through) their doorways
        zone("exec", Rect(EXEC["x0"], EXEC["z0"], EXEC["x1"], EXEC["z1"]), 1.4),
        zone("vault", Rect(VAULT["x0"], VAULT["z0"], VAULT["x1"], VAULT["z1"]), 1.4),
        zone("debate", Rect(DEBATE["x0"], DEBATE["z0"], DEBATE["x1"], DEBATE["z1"]), 1.4),
    ]
    for _cx in CABIN_CENTERS:
        p.floor_zones.append(zone("cabin", Rect(_cx - CABIN_W / 2, CABIN_Z0,
                                                _cx + CABIN_W / 2, CABIN_Z1), 1.4))

    # exterior shell -------------------------------------------------------
    t = WALL_T
    X0, X1 = HALL["x0"], HALL["x1"]
    Z0, Z1 = HALL["z0"], SOUTH_WALL_Z
    # north / west / east solid, south wall carries the two gates
    H = HALL["h"]
    p.walls.append(Wall(X0, Z0 - t, X1, Z0, h=H, kind="exterior"))
    p.walls.append(Wall(X0 - t, Z0 - t, X0, Z1 + t, h=H, kind="exterior"))
    p.walls.append(Wall(X1, Z0 - t, X1 + t, Z1 + t, h=H, kind="exterior"))
    for gate_x, did, label, kind, accent in (
        (ENTRY_GATE_X, "gate_entry", "WELCOME · MARKET GATE", "entry", "#34d399"),
        (EXIT_GATE_X, "gate_exit", "EXIT · REJECTED TRADES", "exit", "#f87171"),
    ):
        half = GATE_W / 2
        p.door(did, label, gate_x, Z1, GATE_W, "z", kind, None)
        p.sign(label.split(" · ")[0], gate_x, Z1 - 0.35, 4.5, "gate",
               sub="SECURITY CLEARANCE", accent=accent, width=5.2)
    # south wall = three segments, leaving both gates open
    gate_a = ENTRY_GATE_X - GATE_W / 2
    gate_b = ENTRY_GATE_X + GATE_W / 2
    gate_c = EXIT_GATE_X - GATE_W / 2
    gate_d = EXIT_GATE_X + GATE_W / 2
    for xa, xb in ((X0, gate_a), (gate_b, gate_c), (gate_d, X1)):
        p.walls.append(Wall(xa, Z1 - t / 2, xb, Z1 + t / 2, h=H, kind="exterior"))

    # ================================================== north wing: cabins ===
    for i, cx in enumerate(CABIN_CENTERS, start=1):
        rect = Rect(cx - CABIN_W / 2, CABIN_Z0, cx + CABIN_W / 2, CABIN_Z1)
        p.add_room_with_walls(
            f"cabin_{i}", f"CABIN {i:02d}", f"Review Chamber {i}", "cabin", rect,
            [dict(id=f"cabin_{i}_door", label=f"Cabin {i} door", x=cx, z=CABIN_Z1,
                  width=2.4, side="s", kind="cabin")],
            wall_kind="glass",
        )
        # judge station at the far (north) end, facing south toward the door
        p.prop("judge_desk", cx, -24.8, w=4.8, d=1.3, h=0.78)
        p.prop("chair", cx, -26.5, rot=math.pi, w=0.62, d=0.62, h=1.0, blocks=False)
        p.prop("witness_stand", cx, -22.2, w=2.2, d=0.55, h=0.95, blocks=True)
        p.prop("side_table", cx + 4.6, -20.6, w=1.0, d=3.4, h=0.78)
        p.prop("side_table", cx - 4.6, -20.6, w=1.0, d=3.4, h=0.78)
        p.prop("chair", cx + 3.8, -20.6, rot=-math.pi / 2, w=0.6, d=0.6, h=1.0, blocks=False)
        p.prop("chair", cx - 3.8, -20.6, rot=math.pi / 2, w=0.6, d=0.6, h=1.0, blocks=False)
        p.prop("cabinet", cx - 6.55, -23.4, w=0.5, d=3.4, h=2.1)
        p.prop("cabinet", cx + 6.55, -23.4, w=0.5, d=3.4, h=2.1)
        p.prop("plant", cx - 5.9, -20.3, w=0.8, d=0.8, h=1.5)
        p.prop("plant", cx + 5.9, -20.3, w=0.8, d=0.8, h=1.5)
        p.prop("screen", cx, CABIN_Z0 + 0.42, w=5.0, d=0.2, h=2.6, y=1.1, rot=0, blocks=False,
               wall="n")
        for side in (-1, 1):
            p.prop("screen", cx + side * (CABIN_W / 2 - 0.4), -23.6, w=0.2, d=3.2, h=1.8,
                   y=1.4, blocks=False, wall="side")
        # lamps
        for dx in (-4.2, 0.0, 4.2):
            p.prop("light_panel", cx + dx, -22.6, w=2.6, d=1.3, h=0.08, y=4.2, blocks=False)

        p.sign(f"CABIN {i:02d}", cx, CABIN_Z1 - 0.30, 3.35, "cabin",
               sub="COUNCIL REVIEW", accent="#38bdf8", width=3.6)

    # corridor dressing
    for x in (-38.0, -12.0, 12.0, 38.0):
        p.prop("pillar", x, CORRIDOR_Z1 - 1.6, w=1.1, d=1.1, h=HALL["h"])
    p.sign("COUNCIL WING", -38.4, CORRIDOR_Z0 + 0.2, 3.6, "wall", sub="5 REVIEW CHAMBERS",
           accent="#38bdf8", width=7.0, rot=0.0)
    p.sign("THE CORRIDOR", 0.0, CORRIDOR_Z1 - 0.25, 3.5, "wall", sub="ARBITRATION PATHWAY",
           accent="#a78bfa", width=6.0)
    p.prop("water_cooler", -43.0, -15.7, w=0.6, d=0.6, h=1.3)
    p.prop("water_cooler", 43.0, -15.7, w=0.6, d=0.6, h=1.3)
    for x in (-21.0, 21.0):
        p.prop("planter", x, CORRIDOR_Z1 - 1.4, w=1.5, d=1.5, h=0.9)
    # corridor ticker band — quotes running the whole wing
    p.prop("ticker_band", 0.0, CORRIDOR_Z1 - 0.25, w=52.0, d=0.3, h=0.8, y=5.6,
           blocks=False, band=True)

    # ==================================================== trading floor =====
    idx = 0
    for r_i, z in enumerate(DESK_ROWS_Z):
        for c_i, x in enumerate(BLOCK_A_X + BLOCK_B_X):
            block = "A" if c_i < len(BLOCK_A_X) else "B"
            idx += 1
            d = Desk(f"desk_{idx}", idx, x, z, block, r_i, c_i)
            p.desks.append(d)
            p.prop("desk", x, z, w=DESK_W, d=DESK_D, h=0.76)
            p.prop("monitor", x - 0.55, z + 0.30, w=0.72, d=0.16, h=0.48, y=0.76, blocks=False,
                   screen_id=d.id)
            p.prop("monitor", x + 0.55, z + 0.30, w=0.72, d=0.16, h=0.48, y=0.76, blocks=False,
                   screen_id=d.id)
            p.prop("keyboard", x, z + 0.18, w=0.7, d=0.24, h=0.03, y=0.77, blocks=False)
            p.prop("chair", x, z - DESK_D / 2 - 1.05, w=0.62, d=0.62, h=1.0, rot=math.pi,
                   blocks=False)
            p.prop("holo_chart", x, z - 0.15, w=1.5, d=0.02, h=0.95, y=1.95, blocks=False,
                   desk=d.id)
            p.prop("mug", x + 0.8, z - 0.35, w=0.14, d=0.14, h=0.16, y=0.8, blocks=False)
            if c_i % 2 == 0 and r_i == 0:
                p.prop("desk_lamp", x - 0.95, z - 0.35, w=0.3, d=0.3, h=0.5, y=1.36, blocks=False)

    # pillars through the pit
    for z in (-10.6, -1.0, 8.6):
        p.prop("pillar", -17.3, z, w=0.9, d=0.9, h=HALL["h"])

    p.sign("TRADING PIT", -27.0, -10.6, 4.2, "wall", sub="DISCOVERED CANDIDATES", accent="#fbbf24",
           width=9.0)
    p.sign("MOMENTUM · PRICE ACTION", 0.3, 9.2, 3.6, "wall", sub="DESK TIER", accent="#f472b6",
           width=8.0)
    # hanging ticker over the heart of the pit
    p.prop("ticker_band", -6.0, -1.0, w=40.0, d=0.3, h=0.9, y=6.6, blocks=False, band=True)

    # ========================================================= east side ====
    # -- east concourse (spine) --
    p.sign("EXECUTIVE ACCESS", 15.7, -10.6, 3.9, "wall", sub="AUTHORISED ONLY", accent="#a78bfa",
           width=5.0)
    p.prop("rope_post", 14.2, -10.4, w=0.3, d=0.3, h=1.0, blocks=False)
    p.prop("rope_post", 17.2, -10.4, w=0.3, d=0.3, h=1.0, blocks=False)

    exec_rect = Rect(EXEC["x0"], EXEC["z0"], EXEC["x1"], EXEC["z1"])
    p.add_room_with_walls("exec", "EXECUTIVE CHAMBER", "Chief Investment Office", "exec",
                          exec_rect,
                          [dict(id="exec_door", label="Executive door", x=EXEC["x0"], z=-5.8,
                                width=3.0, side="w", kind="exec")],
                          accent="#c084fc", wall_kind="glass")
    ceo_x = exec_rect.cx
    p.prop("exec_table", ceo_x, -6.0, w=8.2, d=2.2, h=0.78)
    p.prop("chair", ceo_x, -8.0, w=0.68, d=0.68, h=1.05, blocks=False)
    p.prop("chair", ceo_x, -4.0, rot=math.pi, w=0.68, d=0.68, h=1.05, blocks=False)
    p.prop("screen", ceo_x, EXEC["z0"] + 0.5, w=7.2, d=0.2, h=2.8, y=1.2, blocks=False, wall="n")
    p.prop("screen", EXEC["x1"] - 0.5, -5.8, w=0.2, d=5.6, h=2.4, y=1.2, blocks=False, wall="e")
    p.prop("plant", EXEC["x1"] - 1.2, -0.8, w=0.9, d=0.9, h=1.6)
    for dx in (-3.4, 0.0, 3.4):
        p.prop("light_panel", ceo_x + dx, -5.8, w=2.6, d=1.4, h=0.08, y=4.4, blocks=False)
    p.sign("EXECUTIVE CHAMBER", EXEC["x0"] - 0.3, -3.6, 3.5, "cabin",
           sub="HEAD OF COUNCIL", accent="#c084fc", width=4.6)
    p.sign("HEAD OF COUNCIL · NAVEED", ceo_x, EXEC["z0"] + 0.28, 4.6, "cabin",
           sub="CHIEF INVESTMENT OFFICE", accent="#c084fc", width=7.6)

    vault_rect = Rect(VAULT["x0"], VAULT["z0"], VAULT["x1"], VAULT["z1"])
    p.add_room_with_walls("vault", "MARKET DATA VAULT", "Feed + tick archive", "vault", vault_rect,
                          [dict(id="vault_door", label="Vault door", x=VAULT["x0"], z=6.6,
                                width=2.6, side="w", kind="vault")],
                          accent="#22d3ee", wall_kind="glass")
    for i in range(9):
        p.prop("rack", VAULT["x0"] + 3.6 + (i % 3) * 1.5, VAULT["z0"] + 1.4 + (i // 3) * 1.9,
               w=1.2, d=1.3, h=2.3)
    p.sign("DATA VAULT", vault_rect.cx, VAULT["z0"] + 0.28, 3.5, "cabin", sub="LIVE MARKET FEEDS",
           accent="#22d3ee", width=4.6)

    debate_rect = Rect(DEBATE["x0"], DEBATE["z0"], DEBATE["x1"], DEBATE["z1"])
    p.add_room_with_walls("debate", "DEBATE CHAMBER", "Council floor · self-training", "debate",
                          debate_rect,
                          [dict(id="debate_door", label="Debate door", x=DEBATE["x0"], z=21.5,
                                width=3.4, side="w", kind="debate")],
                          accent="#34d399", wall_kind="glass")
    round_cx, round_cz = debate_rect.cx, debate_rect.cz - 0.4
    p.prop("round_table", round_cx, round_cz, w=3.9, d=3.9, h=0.76)
    for a in range(6):
        ang = a * (2 * math.pi / 6) - math.pi / 2
        p.prop("chair", round_cx + math.cos(ang) * 3.0, round_cz + math.sin(ang) * 3.0,
               rot=-ang + math.pi, w=0.62, d=0.62, h=1.0, blocks=False, debate_seat=a)
    p.prop("screen", round_cx, DEBATE["z0"] + 0.5, w=7.0, d=0.2, h=3.0, y=1.2, blocks=False,
           wall="n", video_wall=True)
    p.prop("screen", DEBATE["x1"] - 0.5, round_cz, w=0.2, d=5.0, h=2.4, y=1.2, blocks=False,
           wall="e")
    for dx, dz in ((-5.4, -5.6), (5.4, 5.6), (-5.4, 5.6), (5.4, -5.6)):
        p.prop("plant", round_cx + dx, round_cz + dz, w=1.0, d=1.0, h=1.7)
    for a in range(4):
        ang = a * math.pi / 2
        p.prop("light_panel", round_cx + math.cos(ang) * 4.0, round_cz + math.sin(ang) * 4.0,
               w=2.2, d=2.2, h=0.08, y=4.2, blocks=False)
    p.sign("DEBATE CHAMBER", DEBATE["x0"] - 0.3, 21.5, 3.5, "cabin", sub="6 LLM COUNCIL",
           accent="#34d399", width=5.0)
    p.sign("DEBATE CHAMBER", round_cx, DEBATE["z0"] + 0.28, 4.6, "cabin",
           sub="PEER REVIEW · CONTINUOUS TRAINING", accent="#34d399", width=9.0)

    # ============================================== arrival hall / gates ====
    p.prop("security_desk", -17.5, 24.8, w=5.6, d=1.5, h=1.05)
    p.prop("turnstile", -19.2, 27.2, w=0.5, d=0.5, h=1.05)
    p.prop("turnstile", -15.8, 27.2, w=0.5, d=0.5, h=1.05)
    p.prop("turnstile", 7.8, 27.2, w=0.5, d=0.5, h=1.05)
    p.prop("turnstile", 11.2, 27.2, w=0.5, d=0.5, h=1.05)
    p.prop("sofa", -38.0, 19.6, w=2.6, d=1.0, h=0.8)
    p.prop("sofa", -38.0, 16.4, rot=math.pi, w=2.6, d=1.0, h=0.8)
    p.prop("coffee_table", -38.0, 18.0, w=1.4, d=1.0, h=0.42)
    p.prop("planter", -27.0, 29.2, w=1.6, d=1.6, h=1.0)
    p.prop("planter", 0.0, 29.2, w=1.6, d=1.6, h=1.0)
    p.prop("planter", 19.0, 29.2, w=1.6, d=1.6, h=1.0)
    p.prop("ticker_band", 0.0, 14.2, w=26.0, d=0.3, h=0.8, y=3.8, blocks=False, band=True)
    p.sign("ARRIVAL HALL", -30.0, 13.8, 4.2, "wall", sub="TRADE INTAKE", accent="#34d399",
           width=8.0)
    p.sign("SECURITY", -17.5, 25.6, 2.9, "wall", sub="CLEARANCE DESK", accent="#38bdf8",
           width=3.4)

    # west market wall of the pit + lobby video wall on the south wall
    p.prop("video_wall", X0 + 0.55, -1.4, w=0.24, d=19.0, h=6.0, y=2.8, blocks=False,
           wall="w", content="markets")
    p.sign("GLOBAL MARKETS", X0 + 0.9, -1.4, 6.0, "screen", sub="LIVE TAPE", accent="#38bdf8",
           width=7.0)
    p.prop("video_wall", -30.0, SOUTH_WALL_Z - 0.55, w=13.0, d=0.24, h=3.8, y=3.0, blocks=False,
           wall="s", content="tape")
    p.prop("video_wall", 28.0, SOUTH_WALL_Z - 0.55, w=11.0, d=0.24, h=2.8, y=3.4, blocks=False,
           wall="s", content="brand")
    p.sign("SOUL EXTER", 28.0, SOUTH_WALL_Z - 0.95, 6.4, "wall",
           sub="AUTONOMOUS TRADING COUNCIL", accent="#7dd3fc", width=12.0, rot=math.pi)

    # ---- outside plaza ---------------------------------------------------
    p.prop("curb", 0.0, 33.6, w=88.0, d=1.6, h=0.16, y=0.0, blocks=False)
    for x in (-38.0, -27.0, -11.0, 0.0, 13.0, 27.0, 38.0):
        p.prop("street_lamp", x, 37.2, w=0.4, d=0.4, h=7.0, blocks=False)
    p.prop("fountain", 30.0, 42.5, w=6.0, d=6.0, h=0.6)
    p.prop("taxi", -40.0, 41.0, w=4.6, d=1.9, h=1.5, rot=0.1)
    p.prop("taxi", 40.0, 46.5, w=4.6, d=1.9, h=1.5, rot=math.pi - 0.15)
    p.prop("plaza_tree", -25.0, 41.0, w=2.2, d=2.2, h=5.0, blocks=False)
    p.prop("plaza_tree", 8.0, 44.0, w=2.2, d=2.2, h=5.0, blocks=False)

    # --------------------------------------------- navigation waypoints ----
    n = p.nodes
    n["entry_outside"] = (ENTRY_GATE_X, SOUTH_WALL_Z + 5.2)
    n["entry_inside"] = (ENTRY_GATE_X, SOUTH_WALL_Z - 3.0)
    n["entry_gate"] = (ENTRY_GATE_X, SOUTH_WALL_Z)
    n["exit_inside"] = (EXIT_GATE_X, SOUTH_WALL_Z - 3.0)
    n["exit_gate"] = (EXIT_GATE_X, SOUTH_WALL_Z)
    n["exit_outside"] = (EXIT_GATE_X + 6.5, SOUTH_WALL_Z + 6.5)
    n["lobby_center"] = (0.0, 19.0)
    n["concourse_entry"] = (15.7, -7.2)
    n["concourse_lobby"] = (15.7, 6.0)
    n["pit_north_gate"] = (-10.0, -10.6)
    for i, d in enumerate(p.desks, start=1):
        n[f"desk_{i}_seat"] = (round(d.seat[0], 3), round(d.seat[1], 3))
        n[f"desk_{i}_stand"] = (round(d.stand[0], 3), round(d.stand[1], 3))
    for i, cx in enumerate(CABIN_CENTERS, start=1):
        n[f"cabin_{i}_outside"] = (cx, CABIN_Z1 + 2.0)
        n[f"cabin_{i}_door"] = (cx, CABIN_Z1)
        n[f"cabin_{i}_hear"] = (cx, -20.6)
        n[f"cabin_{i}_judge"] = (cx, -26.5)
    n["exec_outside"] = (EXEC["x0"] - 2.0, -5.8)
    n["exec_door"] = (EXEC["x0"], -5.8)
    n["exec_stand"] = (exec_rect.cx, -3.6)
    n["exec_ceo"] = (exec_rect.cx, -8.0)
    n["debate_outside"] = (DEBATE["x0"] - 2.0, 21.5)
    n["debate_door"] = (DEBATE["x0"], 21.5)
    n["debate_stand"] = (round_cx - 3.8, round_cz)
    for a in range(6):
        ang = a * (2 * math.pi / 6) - math.pi / 2
        n[f"debate_seat_{a}"] = (round(round_cx + math.cos(ang) * 4.4, 3),
                                 round(round_cz + math.sin(ang) * 4.4, 3))
    n["vault_door"] = (VAULT["x0"], 6.6)
    n["vault_inside"] = (VAULT["x0"] + 2.0, 6.6)
    n["fly_home"] = (0.0, 12.0)

    # the fly's patrol loop (figure-of-eight over the desks, dipping into the wing)
    fly_loop = []
    for t in range(48):
        a = t / 48.0 * math.tau
        fly_loop.append((round(24.0 * math.sin(a), 2),
                         round(-1.0 + 12.5 * math.sin(2 * a), 2),
                         round(5.4 + 1.6 * math.sin(3 * a), 2)))
    setattr(p, "fly_loop", fly_loop)
    return p


# -------------------------------------------------------------- navigation --
class NavGrid:
    """Rasterised walkable grid + A* with string-pulled, wall-hugging-free paths.

    Painting strategy (fast + conservative):
      1. every cell starts blocked,
      2. each open floor zone paints its cells open,
      3. every solid wall / prop paints its (inflated) cells blocked again.
    """

    def __init__(self, plan: FloorPlan, cell: float = CELL, radius: float = AVATAR_R) -> None:
        self.plan = plan
        self.cell = cell
        self.radius = radius
        self.x0 = HALL["x0"]
        self.z0 = HALL["z0"] - 1.0
        self.x1 = HALL["x1"]
        self.z1 = SOUTH_WALL_Z + 22.0
        self.cols = int(math.ceil((self.x1 - self.x0) / cell))
        self.rows = int(math.ceil((self.z1 - self.z0) / cell))
        self.n = self.cols * self.rows
        self.walk = bytearray(self.n)
        self.cost = [1.0] * self.n
        self._build()

    # -- cell helpers ------------------------------------------------------
    def cell_bounds(self, r: Rect) -> Tuple[int, int, int, int]:
        c0 = max(0, int(math.floor((r.x0 - self.x0) / self.cell)))
        c1 = min(self.cols - 1, int(math.ceil((r.x1 - self.x0) / self.cell)))
        r0 = max(0, int(math.floor((r.z0 - self.z0) / self.cell)))
        r1 = min(self.rows - 1, int(math.ceil((r.z1 - self.z0) / self.cell)))
        return c0, r0, c1, r1

    def _paint(self, r: Rect, value: int, pad: float = 0.0) -> None:
        rr = r.inflate(pad) if pad else r
        c0, r0, c1, r1 = self.cell_bounds(rr)
        for row in range(r0, r1 + 1):
            base = row * self.cols
            for col in range(c0, c1 + 1):
                self.walk[base + col] = value

    def _build(self) -> None:
        pad = 0.06
        for z in self.plan.floor_zones:
            self._paint(Rect(*z["rect"]), 1, pad)
        for w in self.plan.walls:
            self._paint(w.as_rect(), 0, self.radius + CLEARANCE)
        for pr in self.plan.props:
            if not pr.blocks:
                continue
            half_w, half_d = pr.w / 2.0, pr.d / 2.0
            if abs(pr.rot) > 0.01:
                c, sn = abs(math.cos(pr.rot)), abs(math.sin(pr.rot))
                half_w, half_d = (pr.w * c + pr.d * sn) / 2.0, (pr.w * sn + pr.d * c) / 2.0
            self._paint(Rect(pr.x - half_w, pr.z - half_d, pr.x + half_w, pr.z + half_d), 0,
                        self.radius + CLEARANCE)
        # prefer the middle of an aisle: cells touching a blocker cost more
        walk = self.walk
        for row in range(1, self.rows - 1):
            base = row * self.cols
            for col in range(1, self.cols - 1):
                i = base + col
                if not walk[i]:
                    continue
                if not (walk[i - 1] and walk[i + 1] and walk[i - self.cols] and walk[i + self.cols]):
                    self.cost[i] = 1.6

    # -- queries -----------------------------------------------------------
    def idx(self, x: float, z: float) -> Tuple[int, int]:
        col = int((x - self.x0) / self.cell)
        row = int((z - self.z0) / self.cell)
        return max(0, min(self.cols - 1, col)), max(0, min(self.rows - 1, row))

    def walkable(self, x: float, z: float) -> bool:
        col, row = self.idx(x, z)
        return bool(self.walk[row * self.cols + col])

    def free_at(self, x: float, z: float, radius_cells: int = 16):
        """Snap a point to the nearest walkable cell (authoring / endpoint safety)."""
        if self.walkable(x, z):
            return (x, z)
        col, row = self.idx(x, z)
        best, best_d = (x, z), 1e9
        for r in range(max(0, row - radius_cells), min(self.rows, row + radius_cells + 1)):
            base = r * self.cols
            for c in range(max(0, col - radius_cells), min(self.cols, col + radius_cells + 1)):
                if self.walk[base + c]:
                    px = self.x0 + (c + 0.5) * self.cell
                    pz = self.z0 + (r + 0.5) * self.cell
                    d = (px - x) ** 2 + (pz - z) ** 2
                    if d < best_d:
                        best_d, best = d, (px, pz)
        return best

    def _los(self, a, b) -> bool:
        dx, dz = b[0] - a[0], b[1] - a[1]
        dist = math.hypot(dx, dz)
        steps = max(2, int(dist / (self.cell * 0.6)))
        for s in range(steps + 1):
            t = s / steps
            if not self.walkable(a[0] + dx * t, a[1] + dz * t):
                return False
        return True

    def find_path(self, start, goal, smooth: bool = True):
        s = self.free_at(*start)
        g = self.free_at(*goal)
        sc, sr = self.idx(*s)
        gc, gr = self.idx(*g)
        start_i = sr * self.cols + sc
        goal_i = gr * self.cols + gc
        if start_i == goal_i:
            return [(round(s[0], 3), round(s[1], 3)), (round(g[0], 3), round(g[1], 3))]

        open_heap = [(0.0, start_i)]
        came = {}
        gscore = {start_i: 0.0}
        closed = bytearray(self.n)
        diag = math.sqrt(2.0)
        found = False

        def h(i):
            r, c = divmod(i, self.cols)
            dc, dr = abs(c - gc), abs(r - gr)
            return (dc + dr) + (diag - 2.0) * min(dc, dr)

        while open_heap:
            _, cur = heapq.heappop(open_heap)
            if cur == goal_i:
                found = True
                break
            if closed[cur]:
                continue
            closed[cur] = 1
            cr, cc = divmod(cur, self.cols)
            for dr in (-1, 0, 1):
                nr = cr + dr
                if nr < 0 or nr >= self.rows:
                    continue
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nc = cc + dc
                    if nc < 0 or nc >= self.cols:
                        continue
                    ni = nr * self.cols + nc
                    if not self.walk[ni]:
                        continue
                    if dr and dc:
                        if not (self.walk[cr * self.cols + nc] and self.walk[nr * self.cols + cc]):
                            continue
                        step = diag
                    else:
                        step = 1.0
                    ng = gscore[cur] + step * self.cost[ni]
                    if ng < gscore.get(ni, 1e18):
                        gscore[ni] = ng
                        came[ni] = cur
                        heapq.heappush(open_heap, (ng + h(ni) * 1.05, ni))
        if not found:
            return [s, g]

        node = goal_i
        chain = [goal_i]
        while node != start_i and node in came:
            node = came[node]
            chain.append(node)
        chain.reverse()
        pts = [(self.x0 + (i % self.cols + 0.5) * self.cell,
                self.z0 + (i // self.cols + 0.5) * self.cell) for i in chain]
        pts[0] = s
        pts[-1] = g
        if smooth:
            pts = self._smooth(pts)
        return [(round(x, 3), round(z, 3)) for x, z in pts]

    def _smooth(self, pts):
        if len(pts) < 3:
            return pts
        out = [pts[0]]
        i = 0
        while i < len(pts) - 1:
            j = len(pts) - 1
            while j > i + 1:
                if self._los(pts[i], pts[j]):
                    break
                j -= 1
            out.append(pts[j])
            i = j
        cleaned = [out[0]]
        for pt in out[1:]:
            if math.dist(cleaned[-1], pt) > 0.06:
                cleaned.append(pt)
        return cleaned

    def path_length(self, path) -> float:
        return sum(math.dist(path[i], path[i + 1]) for i in range(len(path) - 1))

    def to_dict(self) -> dict:
        return dict(cell=self.cell, x0=self.x0, z0=self.z0, cols=self.cols, rows=self.rows)

    def ascii_preview(self, step: int = 6) -> str:  # pragma: no cover
        rows = []
        for r in range(0, self.rows, step):
            line = ["." if self.walk[r * self.cols + c] else "#" for c in range(0, self.cols, max(1, step // 2))]
            rows.append("".join(line))
        return "\n".join(rows)


# ---------------------------------------------------------------- factories --
_PLAN: Optional[FloorPlan] = None
_NAV: Optional[NavGrid] = None


def get_plan() -> FloorPlan:
    global _PLAN
    if _PLAN is None:
        _PLAN = build_floor_plan()
    return _PLAN


def get_nav() -> NavGrid:
    global _NAV
    if _NAV is None:
        _NAV = NavGrid(get_plan())
    return _NAV


def layout_payload() -> dict:
    p = get_plan()
    nav = get_nav()
    return dict(
        hall=dict(x0=HALL["x0"], z0=HALL["z0"], x1=HALL["x1"], z1=HALL["z1"], h=HALL["h"],
                  south=SOUTH_WALL_Z),
        walk_speed=WALK_SPEED,
        rooms=[r.dict() for r in p.rooms],
        walls=[w.dict() for w in p.walls],
        doors=[d.dict() for d in p.doors],
        props=[pr.dict() for pr in p.props],
        desks=[d.dict() for d in p.desks],
        signs=[s.dict() for s in p.signs],
        nodes={k: [round(v[0], 3), round(v[1], 3)] for k, v in p.nodes.items()},
        floor_zones=[dict(kind=z["kind"], rect=z["rect"]) for z in p.floor_zones],
        fly_loop=getattr(p, "fly_loop", []),
        nav=nav.to_dict(),
    )


if __name__ == "__main__":  # pragma: no cover
    nav = get_nav()
    print(nav.ascii_preview())
