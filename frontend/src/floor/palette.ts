/**
 * Materials and light for the floor.
 *
 * A trading floor at night: dark travertine, warm wood, brushed metal, cold
 * glass, and a lot of small emissive screens. Every colour here is used through
 * the shading helpers in geom.ts, so changing one value changes the whole room.
 */
export const palette = {
  // ---- room ---------------------------------------------------------------
  void: "#05070c",
  ceiling: "#0b1018",
  ceilingBeam: "#141a24",
  wallBack: "#0e131c",
  wallFront: "#080c13",
  wallTrim: "#1b2330",

  floorBase: "#151a22",
  floorTileA: "#1d232d",
  floorTileB: "#191e27",
  floorGrout: "#0d1116",
  floorSheen: "#2b3444",

  travertineA: "#2a2f39",
  travertineB: "#232833",
  carpet: "#141a24",
  aisle: "#1a2029",

  // ---- desks --------------------------------------------------------------
  deskTop: "#6b4a2f",
  deskTopDark: "#5a3d26",
  deskEdge: "#3b2717",
  deskLeg: "#2b313c",
  deskLegDark: "#1e232c",
  chairSeat: "#232a36",
  chairBack: "#2b3240",
  chairPost: "#3a4250",

  monitorBody: "#0e1117",
  monitorBezel: "#1b212a",
  screenOff: "#101822",
  screenGlow: "#3fd0ff",

  // ---- cabins (the LLM stages) -------------------------------------------
  cabinFrame: "#39424f",
  cabinFrameDark: "#232a35",
  cabinGlass: "#8fd4ff",
  cabinFloor: "#2a3140",
  cabinInterior: "#e9b46a",
  cabinScreen: "#1b2a3a",
  cabinRoof: "#1a2029",
  cabinAccent: "#57b6ff",

  ceoAccent: "#ffd479",
  ceoInterior: "#ffe3a6",

  // ---- doors --------------------------------------------------------------
  entryDoor: "#41d69a",
  exitDoor: "#ff6b6b",
  doorFrame: "#2c3441",
  doorGlass: "#0f1720",

  // ---- avatars ------------------------------------------------------------
  skin: ["#f0c9a4", "#d9a273", "#a9703f", "#7a4a26", "#f6d9bd"],
  hair: ["#1b1b21", "#2e2018", "#4a3423", "#6b5236", "#101014", "#8d8d96"],
  shirt: ["#4f7bd9", "#48b09a", "#c95f5f", "#c8a04a", "#8a6fd0", "#5d6b7d", "#d97aa6", "#63a7e0"],
  trousers: ["#2b3240", "#333a48", "#242b36", "#3b3f4d"],
  longColor: "#3ee08a",
  shortColor: "#ff6b6b",
  abstainColor: "#c8b45c",

  // ---- light --------------------------------------------------------------
  sun: "#ffe9c8",
  lampWarm: "#ffcf94",
  lampCool: "#bfe4ff",
  text: "#e9eef6",
  textDim: "#93a0b3",
  plate: "#0b0f16",
} as const;

export type Palette = typeof palette;

/** Direction the room is lit from, in screen space. -1 = from the left. */
export const LIGHT = { fromLeft: true, topBoost: 1.16, sideBoost: 0.86, farBoost: 0.62 };

// ---------------------------------------------------------------------------
// colour maths
// ---------------------------------------------------------------------------
const hexCache = new Map<string, [number, number, number]>();

export function toRgb(hex: string): [number, number, number] {
  const cached = hexCache.get(hex);
  if (cached) return cached;
  let h = hex.trim();
  if (h.startsWith("#")) h = h.slice(1);
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const n = parseInt(h, 16);
  const rgb: [number, number, number] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  hexCache.set(hex, rgb);
  return rgb;
}

export function toHex(rgb: [number, number, number]): string {
  const c = (v: number) => Math.max(0, Math.min(255, Math.round(v)));
  return `#${((1 << 24) | (c(rgb[0]) << 16) | (c(rgb[1]) << 8) | c(rgb[2])).toString(16).slice(1)}`;
}

/** Multiply a colour's brightness — the whole shading model in one function. */
export function shade(hex: string, factor: number): string {
  if (factor === 1) return hex;
  const [r, g, b] = toRgb(hex);
  return toHex([r * factor, g * factor, b * factor]);
}

/** Warm or cool a colour, e.g. interiors under a tungsten lamp. */
export function tint(hex: string, toward: string, amount: number): string {
  const a = toRgb(hex);
  const b = toRgb(toward);
  return toHex([
    a[0] + (b[0] - a[0]) * amount,
    a[1] + (b[1] - a[1]) * amount,
    a[2] + (b[2] - a[2]) * amount,
  ]);
}

export function rgba(hex: string, alpha: number): string {
  const [r, g, b] = toRgb(hex);
  return `rgba(${Math.round(r)},${Math.round(g)},${Math.round(b)},${alpha})`;
}

/** Deterministic value noise — used for marble, wood grain and dust. */
export function hash01(seed: number): number {
  let x = Math.imul(seed ^ 0x9e3779b9, 0x85ebca6b);
  x ^= x >>> 13;
  x = Math.imul(x, 0xc2b2ae35);
  x ^= x >>> 16;
  return (x >>> 0) / 4294967296;
}
