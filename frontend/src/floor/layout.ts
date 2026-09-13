/**
 * Where everything stands.
 *
 * One place for every coordinate on the floor, so the furniture, the walk paths
 * and the camera all agree. World units are ~1 metre; x runs to the lower right
 * of the screen, y to the lower left, z is up.
 *
 *   back / top of screen                          front / bottom of screen
 *   --------------------------------------------  ------------------------
 *   CEO penthouse   (above the cabin row)
 *   cabin row:      QUANT RISK NEWS MACRO COMPLIANCE   (on a raised platform)
 *   staircase down the middle of the promenade
 *   desk blocks     [5 columns]  promenade  [5 columns]   x 6 rows
 *   front promenade
 *   ENTRY door (left)                      EXIT door (right)
 */
export const FLOOR = { w: 50, d: 36 };

export const PLATFORM = { x: 2.5, y: 0.2, w: 45.0, d: 9.4, z: 2.4 };

export interface CabinSlot {
  key: string;
  x: number; // left edge
  y: number;
  w: number;
  d: number;
  z: number;
  doorX: number; // centre of the opening, used by walk paths
}

const CABIN_W = 7.2;
const CABIN_D = 6.4;
const CABIN_Y = 1.5;
const CABIN_Z = PLATFORM.z;

/** The five voting cabins, left to right, plus the CEO's penthouse above them. */
export const CABINS: CabinSlot[] = [
  { key: "QUANT", x: 4.6, y: CABIN_Y, w: CABIN_W, d: CABIN_D, z: CABIN_Z, doorX: 5.4 },
  { key: "RISK", x: 12.7, y: CABIN_Y, w: CABIN_W, d: CABIN_D, z: CABIN_Z, doorX: 12.6 },
  { key: "NEWS", x: 20.8, y: CABIN_Y, w: CABIN_W, d: CABIN_D, z: CABIN_Z, doorX: 19.8 },
  { key: "MACRO", x: 28.9, y: CABIN_Y, w: CABIN_W, d: CABIN_D, z: CABIN_Z, doorX: 27.0 },
  { key: "COMPLIANCE", x: 37.0, y: CABIN_Y, w: CABIN_W, d: CABIN_D, z: CABIN_Z, doorX: 34.2 },
].map((c) => ({ ...c, doorX: c.x + c.w / 2 - 0.8 }));

export const CEO: CabinSlot = {
  key: "CEO",
  x: 18.4,
  y: -6.8,
  w: 16.4,
  d: 5.8,
  z: 5.1,
  doorX: 24.4,
};

/** Staircase from the promenade up to the cabin platform. */
export const STAIR = {
  x: 17.35 - 1.25, // centred in the walk aisle between desk blocks 1 and 2
  w: 2.5,
  yBottom: 13.6,
  yTop: PLATFORM.y + PLATFORM.d,
  steps: 7,
};

/** Two steps from the platform up to the CEO's floor. */
export const CEO_STAIR = { x: 29.0, w: 2.8, yBottom: 4.4, yTop: 1.2 };

export const DOORS = {
  entry: { x: 13.6, w: 4.4, y: FLOOR.d - 0.15, label: "WELCOME" },
  exit: { x: 31.8, w: 4.4, y: FLOOR.d - 0.15, label: "EXIT" },
};

/** Reception desk next to the welcome door — where new trades check in. */
export const RECEPTION = { x: 7.8, y: 31.0, w: 3.8, d: 1.6 };

export const DESKS = {
  colPitch: 2.65,
  rowPitch: 2.8,
  /** Left edge of each column block. The gaps between blocks are walk aisles. */
  blockX: [3.2, 18.6, 34.0],
  colsPerBlock: 5,
  y0: 15.0,
  rows: 5,
  deskW: 1.9,
  deskD: 1.25,
  deskH: 0.76,
  /** where in the cell the chair sits, relative to the desk's left edge */
  seatDX: 2.3,
  seatDY: 0.6,
};

/** Right-hand edge of a column block's footprint (desks plus the chairs). */
export function blockRight(block: number): number {
  return DESKS.blockX[block] + (DESKS.colsPerBlock - 1) * DESKS.colPitch + DESKS.seatDX + 0.4;
}

/** Every vertical walk aisle, left to right. */
export function aisles(): number[] {
  const out: number[] = [DESKS.blockX[0] - 1.7];
  for (let i = 0; i < DESKS.blockX.length - 1; i++) {
    out.push((blockRight(i) + DESKS.blockX[i + 1]) / 2);
  }
  out.push((blockRight(DESKS.blockX.length - 1) + FLOOR.w - 1.2) / 2);
  return out;
}

/** The aisle a trader at this x will actually walk to. */
export function nearestAisle(x: number): number {
  let best = aisles()[0];
  for (const a of aisles()) if (Math.abs(a - x) < Math.abs(best - x)) best = a;
  return best;
}

export const PROMENADE = {
  /** central aisle between the two desk blocks */
  centre: STAIR.x + STAIR.w / 2,
  front: FLOOR.d - 1.8,
  left: 1.9,
  right: FLOOR.w - 1.9,
};

export interface DeskSlot {
  index: number;
  row: number;
  col: number;
  x: number;
  y: number;
  /** centre of the walking gap behind the desks of this row */
  gapY: number;
  seat: [number, number];
}

/** Build the desk grid: two blocks of five columns either side of the promenade. */
export function buildDesks(limit = 80): DeskSlot[] {
  const out: DeskSlot[] = [];
  let index = 0;
  for (let row = 0; row < DESKS.rows; row++) {
    const y = DESKS.y0 + row * DESKS.rowPitch;
    const gapY = y + DESKS.rowPitch - 0.35;
    for (let block = 0; block < DESKS.blockX.length; block++) {
      for (let col = 0; col < DESKS.colsPerBlock; col++) {
        const x = DESKS.blockX[block] + col * DESKS.colPitch;
        out.push({
          index,
          row,
          col: block * DESKS.colsPerBlock + col,
          x,
          y,
          gapY,
          seat: [x + DESKS.seatDX, y + DESKS.seatDY],
        });
        index++;
        if (index >= limit) return out;
      }
    }
  }
  return out;
}

export const DESK_SLOTS = buildDesks(80);

/** Waypoints every walk is routed through, so nobody walks through a desk. */
export const NODES = {
  promenadeTop: [PROMENADE.centre, STAIR.yBottom - 0.6] as [number, number],
  stairBase: [PROMENADE.centre, STAIR.yBottom] as [number, number],
  stairTop: [PROMENADE.centre, STAIR.yTop - 0.4] as [number, number],
  platform: [PROMENADE.centre, PLATFORM.y + PLATFORM.d + 0.35] as [number, number],
  ceoStairBase: [CEO_STAIR.x + CEO_STAIR.w / 2, CEO_STAIR.yBottom] as [number, number],
  ceoStairTop: [CEO_STAIR.x + CEO_STAIR.w / 2, CEO_STAIR.yTop] as [number, number],
  ceoFront: [CEO.doorX + 0.8, CEO.y + CEO.d - 0.4] as [number, number],
  frontLeft: [DOORS.entry.x + DOORS.entry.w / 2, PROMENADE.front] as [number, number],
  frontRight: [DOORS.exit.x + DOORS.exit.w / 2, PROMENADE.front] as [number, number],
  entryDoor: [DOORS.entry.x + DOORS.entry.w / 2, FLOOR.d + 0.4] as [number, number],
  exitDoor: [DOORS.exit.x + DOORS.exit.w / 2, FLOOR.d + 0.4] as [number, number],
  reception: [RECEPTION.x + RECEPTION.w / 2, RECEPTION.y + RECEPTION.d + 0.9] as [number, number],
};

export type Pt = [number, number, number?];

/**
 * Path from a desk to a cabin: out into the row gap, along the promenade, up
 * the stairs, then across the platform to the cabin door.
 */
export function pathToCabin(desk: DeskSlot, cabinKey: string): Pt[] {
  const cabin = cabinKey === "CEO" ? CEO : CABINS.find((c) => c.key === cabinKey);
  if (!cabin) return pathToDoor(desk, "entry");
  const zf = cabin.z;
  const ax = nearestAisle(desk.seat[0]);
  const apron = STAIR.yBottom - 1.3;          // clear strip in front of the deck
  const out: Pt[] = [
    desk.seat,
    [desk.seat[0], desk.gapY, 0],
    [ax, desk.gapY, 0],
    [ax, apron, 0],
    [PROMENADE.centre, apron, 0],
    NODES.stairBase,
  ];
  if (cabinKey === "CEO") {
    out.push(
      [NODES.stairTop[0], NODES.stairTop[1], PLATFORM.z],
      [NODES.ceoStairBase[0], NODES.ceoStairBase[1], PLATFORM.z],
      [NODES.ceoStairTop[0], NODES.ceoStairTop[1], CEO.z],
      NODES.ceoFront,
      [cabin.doorX, cabin.y + cabin.d - 0.2, CEO.z],
    );
  } else {
    out.push(
      [NODES.stairTop[0], NODES.stairTop[1], PLATFORM.z],
      [cabin.doorX, PLATFORM.y + PLATFORM.d + 0.45, zf],
      [cabin.doorX, cabin.y + cabin.d - 0.15, zf],
    );
  }
  return out;
}

export function pathToDoor(desk: DeskSlot, door: "entry" | "exit"): Pt[] {
  const d = door === "entry" ? DOORS.entry : DOORS.exit;
  const ax = nearestAisle(desk.seat[0]);
  const front: [number, number] = [d.x + d.w / 2, PROMENADE.front];
  return [
    desk.seat,
    [desk.seat[0], desk.gapY, 0],
    [ax, desk.gapY, 0],
    [ax, PROMENADE.front, 0],
    front,
    [d.x + d.w / 2, FLOOR.d + 0.6, 0],
  ];
}

export function pathFromEntry(desk: DeskSlot): Pt[] {
  const centre: [number, number] = [
    DOORS.entry.x + DOORS.entry.w / 2,
    PROMENADE.front,
  ];
  return [
    [DOORS.entry.x + DOORS.entry.w / 2, FLOOR.d + 1.6, 0],
    centre,
    [PROMENADE.centre, PROMENADE.front, 0],
    [PROMENADE.centre, desk.gapY, 0],
    [desk.seat[0], desk.gapY, 0],
    desk.seat,
  ];
}

/** Bounds of everything drawn, for the camera fit. */
export function sceneBounds() {
  return {
    x0: -1.8,
    y0: CEO.y - 2.6,
    x1: FLOOR.w + 1.8,
    y1: FLOOR.d + 2.6,
    zTop: CEO.z + 3.9,
  };
}

/** The part of the room worth filling the frame with. */
export function busyBounds() {
  return { x0: 1.5, y0: CEO.y - 0.5, x1: FLOOR.w - 1.0, y1: FLOOR.d + 0.5, zTop: 8.6 };
}
