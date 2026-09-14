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

/** The middle of the room: an information plaza between the two desk blocks. */
export const PLAZA = { x: 24.4, y: 22.0 };

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
  // centred in the walk aisle between desk blocks 1 and 2: blockRight(0) = 16.5,
  // next block starts at 19.4, so the aisle runs 16.5 .. 19.4
  x: 17.95 - 1.25,
  w: 2.5,
  yBottom: 13.6,
  yTop: PLATFORM.y + PLATFORM.d,
  steps: 7,
};

/**
 * Stairs from the platform up to the CEO's floor.
 *
 * They used to rise at x=29 — which is *inside* the MACRO cabin's footprint, so
 * every walk to the penthouse went through a colleague's cabin. They now stand
 * on the open platform past COMPLIANCE, and the walk to the CEO door runs along
 * a mezzanine behind the cabin row instead of across its roofs.
 */
export const CEO_STAIR = { x: 44.5, w: 2.8, yBottom: 4.4, yTop: 1.2 };

/**
 * The mezzanine behind the cabin row: the deck the penthouse door opens onto.
 * It runs from the top of the console stair (right end) along the back of the
 * cabins to the CEO's own door, and it sits behind `y = 1.5` because that is
 * where the cabins start — the walk never crosses one.
 */
export const CEO_WALK_Y = 0.7;
export const CEO_TERRACE = { x: 21.0, y: -0.7, w: 26.4, d: 2.0, z: CEO.z };

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
  blockX: [3.2, 19.4, 35.6],
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

/** Standing room inside a cabin — where a trader goes when it is being judged. */
export function cabinInterior(cabinKey: string): Pt {
  const cabin = cabinKey === "CEO" ? CEO : CABINS.find((c) => c.key === cabinKey);
  if (!cabin) return [NODES.platform[0], NODES.platform[1], PLATFORM.z];
  return [cabin.x + cabin.w / 2, cabin.y + cabin.d * 0.62, cabin.z];
}

/** The strip of platform in front of the cabin row that people walk along. */
export const PLATFORM_WALK = PLATFORM.y + PLATFORM.d - 0.7;

/**
 * Path from a desk to a cabin: out into the row gap, along the promenade, up
 * the stairs, then across the platform to the cabin door.
 */
/**
 * Path from where a trader is standing to the inside of a cabin.
 *
 * The last leg matters: the trader walks *through the door and stands inside*
 * the cabin, not on the platform outside it. If they are already up on the
 * platform — which is the normal case, because a council runs cabin to cabin —
 * the path starts from the cabin they are standing in and goes straight along
 * the platform, instead of walking back down the stairs and up again.
 */
export function pathToCabin(
  desk: DeskSlot,
  cabinKey: string,
  from?: { x: number; y: number; z: number; cabin?: string },
): Pt[] {
  const cabin = cabinKey === "CEO" ? CEO : CABINS.find((c) => c.key === cabinKey);
  if (!cabin) return pathToDoor(desk, "entry");
  const zf = cabin.z;
  const inside = cabinInterior(cabinKey);
  const ax = nearestAisle(desk.seat[0]);
  const apron = STAIR.yBottom + 0.9;          // on the floor, in front of the stairs

  const onPlatform = !!from && from.z >= PLATFORM.z - 0.05;
  if (onPlatform) {
    const start: Pt = from!.cabin
      ? cabinInterior(from!.cabin)
      : [from!.x, from!.y, from!.z];
    const out: Pt[] = [start];
    // Stepping out of a cabin means stepping out of its doorway. Walking
    // straight out from the standing spot took the trader through the front
    // glass, which is exactly what "no walking through structures" rules out.
    const leaving = from?.cabin
      ? (from.cabin === "CEO" ? CEO : CABINS.find((c) => c.key === from.cabin))
      : null;
    if (leaving) {
      out.push([leaving.doorX, leaving.y + leaving.d * 0.52, leaving.z]);
      out.push(leaving.key === "CEO"
        ? [NODES.ceoFront[0], NODES.ceoFront[1], CEO.z]
        : [leaving.doorX, leaving.y + leaving.d + 0.5, PLATFORM.z]);
    }
    const walkX = leaving ? leaving.doorX : start[0];
    if (!leaving || leaving.key !== "CEO") out.push([walkX, PLATFORM_WALK, PLATFORM.z]);
    if (cabinKey === "CEO" || (from?.cabin === "CEO" && cabinKey !== "CEO")) {
      if (cabinKey === "CEO") {
        // up the stairs at the end of the row, along the mezzanine behind the
        // cabins, then in through the penthouse door
        out.push(
          [NODES.ceoStairBase[0], PLATFORM_WALK, PLATFORM.z],
          [NODES.ceoStairBase[0], NODES.ceoStairBase[1], PLATFORM.z],
          [NODES.ceoStairTop[0], NODES.ceoStairTop[1], CEO.z],
          [NODES.ceoStairTop[0], CEO_WALK_Y, CEO.z],
          [CEO.doorX, CEO_WALK_Y, CEO.z],
          [CEO.doorX, CEO.y + CEO.d * 0.52, CEO.z],
          inside,
        );
        return out;
      }
      // coming down from the penthouse: door, mezzanine, stairs, walkway
      out.push(
        [CEO.doorX, CEO.y + CEO.d * 0.52, CEO.z],
        [CEO.doorX, CEO_WALK_Y, CEO.z],
        [NODES.ceoStairTop[0], CEO_WALK_Y, CEO.z],
        [NODES.ceoStairTop[0], NODES.ceoStairTop[1], CEO.z],
        [NODES.ceoStairBase[0], NODES.ceoStairBase[1], PLATFORM.z],
        [NODES.ceoStairBase[0], PLATFORM_WALK, PLATFORM.z],
      );
    }
    out.push(
      [cabin.doorX, PLATFORM_WALK, PLATFORM.z],
      [cabin.doorX, cabin.y + cabin.d * 0.52, PLATFORM.z],
      inside,
    );
    return out;
  }

  // ground floor: out of the desk, along the row gap, down an aisle, across the
  // front of the stair well, up the stairs, then in through the cabin door
  const out: Pt[] = [
    desk.seat,
    [desk.seat[0], desk.gapY, 0],
    [ax, desk.gapY, 0],
    [ax, apron, 0],
    [PROMENADE.centre, apron, 0],
    NODES.stairBase,
    [NODES.stairTop[0], NODES.stairTop[1], PLATFORM.z],
  ];
  if (cabinKey === "CEO") {
    out.push(
      [NODES.ceoStairBase[0], PLATFORM_WALK, PLATFORM.z],
      [NODES.ceoStairBase[0], NODES.ceoStairBase[1], PLATFORM.z],
      [NODES.ceoStairTop[0], NODES.ceoStairTop[1], CEO.z],
      [NODES.ceoStairTop[0], CEO_WALK_Y, CEO.z],
      [CEO.doorX, CEO_WALK_Y, CEO.z],
      [CEO.doorX, CEO.y + CEO.d * 0.52, CEO.z],
      inside,
    );
  } else {
    out.push(
      [cabin.doorX, PLATFORM_WALK, PLATFORM.z],
      [cabin.doorX, cabin.y + cabin.d * 0.52, PLATFORM.z],
      inside,
    );
  }
  return out;
}

export function pathToDoor(
  desk: DeskSlot,
  door: "entry" | "exit",
  from?: { x: number; y: number; z: number; cabin?: string },
): Pt[] {
  const d = door === "entry" ? DOORS.entry : DOORS.exit;
  const ax = nearestAisle(desk.seat[0]);
  const front: [number, number] = [d.x + d.w / 2, PROMENADE.front];
  const out: Pt[] = [];
  if (from && from.z >= PLATFORM.z - 0.05) {
    // coming down from the cabins: out of the doorway it is standing in, along
    // the platform, down the stairs, then across the floor to the door
    const leaving = from.cabin
      ? (from.cabin === "CEO" ? CEO : CABINS.find((c) => c.key === from.cabin))
      : null;
    if (leaving) {
      out.push(
        cabinInterior(leaving.key),
        [leaving.doorX, leaving.y + leaving.d * 0.52, leaving.z],
      );
      if (leaving.key === "CEO") {
        out.push(
          [CEO.doorX, CEO_WALK_Y, CEO.z],
          [NODES.ceoStairTop[0], CEO_WALK_Y, CEO.z],
          [NODES.ceoStairTop[0], NODES.ceoStairTop[1], CEO.z],
          [NODES.ceoStairBase[0], NODES.ceoStairBase[1], PLATFORM.z],
          [NODES.ceoStairBase[0], PLATFORM_WALK, PLATFORM.z],
          [NODES.stairTop[0], PLATFORM_WALK, PLATFORM.z],
        );
      } else {
        out.push([leaving.doorX, leaving.y + leaving.d + 0.5, PLATFORM.z]);
      }
    } else {
      out.push([from.x, from.y, from.z]);
    }
    out.push(
      [NODES.stairTop[0], NODES.stairTop[1], PLATFORM.z],
      NODES.stairBase,
      [PROMENADE.centre, STAIR.yBottom + 0.9, 0],
    );
  } else {
    out.push(
      desk.seat,
      [desk.seat[0], desk.gapY, 0],
      [ax, desk.gapY, 0],
    );
  }
  out.push([ax, PROMENADE.front, 0], front, [d.x + d.w / 2, FLOOR.d + 0.6, 0]);
  return out;
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
