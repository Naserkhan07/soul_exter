/** Drosophila connectome — full fluorescence-microscopy visual.
 *
 * Built to the reference atlas render, anatomy first:
 *  - two big rounded LATERAL lobes (far left hot-pink/magenta, far right neon
 *    green), each fanned by neurons growing from the optic-tract entry,
 *  - a larger CENTRAL brain: two symmetrical hemispheres with a narrow midline
 *    separation (upper-left red/crimson/magenta/orange/yellow, upper-right
 *    green/cyan/turquoise/electric-blue), a dense top-centre knot,
 *  - the LOWER region and its downward-pointing tract in blue/cyan/green,
 *  - thick primary bundles rendered as double tubes (bright core + halo),
 *    thousands of hair-fine branches around them, and luminous synapse dots
 *    studding every arbor,
 *  - a whisper of translucent tissue for the silhouette, deep black elsewhere.
 *
 * A real UnrealBloom pass gives every fibre the sharp-luminous-core + soft-neon-
 * halo fluorescence look without blurring the detail.
 *
 * Exactly ONE line of light races through the veins, fast, hopping arbor to
 * arbor; when a desk THINKS or QUESTIONS the line takes that desk's colour and
 * sprints, then settles back. No thought — it just keeps its quiet fast run.
 */
import * as THREE from 'three'
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js'
import { onThought } from '../state/brainBus'

/* region palettes — the fluorescence stain of the reference */
const P_OPTIC_L = ['#ff2d6f', '#ff4f9e', '#ff1e5a', '#ff6fb0', '#e8175d', '#ff85c2']
const P_OPTIC_R = ['#39ff6e', '#2fe85c', '#8dffab', '#00e05a', '#6bff92', '#c2ffb0']
const P_HEMI_L = ['#ff2e2e', '#e8143c', '#ff5f2e', '#ffb300', '#ff3d8e', '#d40f4c', '#ff8c1a']
const P_HEMI_R = ['#19e0ff', '#00c8ff', '#2fe8a8', '#39ff6e', '#00b3e8', '#7dffd1', '#00ffd0']
const P_LOWER = ['#2f9bff', '#19e0ff', '#00d0ff', '#2fe8a8', '#39ff6e', '#00b3e8']
const P_TOP_L = ['#ffb300', '#ff8c1a', '#ffd24f']
const P_TOP_R = ['#c2ffb0', '#7dffd1', '#ffe75e']

/* brain regions (x right, y up, z viewer) — proportions from the reference */
const HEMI_L = { c: new THREE.Vector3(-0.44, 0.34, 0), r: new THREE.Vector3(0.74, 0.64, 0.6) }
const HEMI_R = { c: new THREE.Vector3(0.44, 0.34, 0), r: new THREE.Vector3(0.74, 0.64, 0.6) }
const LOWER = { c: new THREE.Vector3(0, -0.42, 0), r: new THREE.Vector3(0.56, 0.46, 0.5) }
const OPTIC_L = { c: new THREE.Vector3(-1.95, 0.05, 0), r: new THREE.Vector3(0.68, 0.74, 0.44) }
const OPTIC_R = { c: new THREE.Vector3(1.95, 0.05, 0), r: new THREE.Vector3(0.68, 0.74, 0.44) }

type Lobe = typeof HEMI_L
const LOBES = [HEMI_L, HEMI_R, LOWER, OPTIC_L, OPTIC_R]

/* where the optic tracts plug into each lateral lobe (the bright knots) */
const ENTRY_L = new THREE.Vector3(-1.5, 0.04, 0)
const ENTRY_R = new THREE.Vector3(1.5, 0.04, 0)

function mulberry(seed: number) {
  let a = seed >>> 0
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/* one road = a root→tip chain (or a tract centreline) the light can run along */
interface Road {
  pts: THREE.Vector3[]
  cum: number[]
  total: number
}

export class FlyBrainViz {
  private renderer: THREE.WebGLRenderer
  private composer!: EffectComposer
  private bloom!: UnrealBloomPass
  private scene = new THREE.Scene()
  private camera = new THREE.PerspectiveCamera(38, 1, 0.1, 60)
  private group = new THREE.Group()
  private raf = 0
  private ro?: ResizeObserver
  private clock = new THREE.Clock()
  private disposed = false
  private offBus: () => void

  private roads: Road[] = []
  private beamLine!: THREE.Line
  private beamPos!: Float32Array
  private beamCol!: Float32Array
  private beamHead!: THREE.Sprite
  private headTex!: THREE.Texture

  /* the ONE line of light */
  private roadIdx = 0
  private forward = true
  private s = 0
  private baseSpeed = 5.2
  private speed = this.baseSpeed
  private targetSpeed = this.baseSpeed
  private beamColor = new THREE.Color('#c9f2ff')
  private targetColor = new THREE.Color('#c9f2ff')
  private flare = 0

  private energy = 0.4
  private t = 0
  private thoughtCount = 0

  private readonly TRAIL = 28
  private readonly STEP = 0.05

  constructor(private host: HTMLElement) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    this.renderer.setClearColor(0x000000, 1)
    host.appendChild(this.renderer.domElement)
    this.camera.position.set(0, 0.2, 7.0)
    this.camera.lookAt(0, 0, 0)
    this.scene.add(this.group)

    const rng = mulberry(20250914)
    this.buildTissue()
    this.buildNeurons(rng)
    this.buildTracts(rng)
    this.buildBeam()

    /* fluorescence: sharp cores + soft neon halos, detail retained */
    this.composer = new EffectComposer(this.renderer)
    this.composer.addPass(new RenderPass(this.scene, this.camera))
    this.bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.35, 0.42, 0.32)
    this.composer.addPass(this.bloom)
    this.composer.addPass(new OutputPass())

    this.offBus = onThought((t) => this.think(t.color, t.strength))

    this.resize()
    this.ro = new ResizeObserver(() => this.resize())
    this.ro.observe(host)
    const loop = () => {
      if (this.disposed) return
      this.raf = requestAnimationFrame(loop)
      this.step()
    }
    loop()
  }

  /* ------------------------------------------------------------- geometry */
  private ellipsoid(lobe: Lobe, opacity: number, color: number) {
    const m = new THREE.Mesh(
      new THREE.SphereGeometry(1, 30, 22),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false }))
    m.position.copy(lobe.c)
    m.scale.copy(lobe.r)
    return m
  }

  /* faint translucent tissue — the silhouette only, never opaque */
  private buildTissue() {
    for (const lobe of LOBES) {
      const fill = this.ellipsoid(lobe, 0.16, 0x1a2233)
      fill.renderOrder = -2
      this.group.add(fill)
      const rim = this.ellipsoid(lobe, 0.07, 0x32405c)
      rim.scale.multiplyScalar(1.02)
      rim.renderOrder = -1
      this.group.add(rim)
    }
  }

  private inLobe(rng: () => number, lobe: Lobe, lo = 0.15, hi = 0.85): THREE.Vector3 {
    const v = new THREE.Vector3(rng() * 2 - 1, rng() * 2 - 1, rng() * 2 - 1)
    if (v.length() > 1) v.normalize()
    const k = lo + rng() * (hi - lo)
    return new THREE.Vector3(lobe.c.x + v.x * lobe.r.x * k,
      lobe.c.y + v.y * lobe.r.y * k, lobe.c.z + v.z * lobe.r.z * k)
  }

  private makeRoad(pts: THREE.Vector3[]): Road {
    const cum = [0]
    for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + pts[i].distanceTo(pts[i - 1]))
    return { pts, cum, total: cum[cum.length - 1] }
  }

  /* -------------------------------------------------------- neuron growth */
  /** Grow one fluorescent neuron: soma → trunk → recursive dendrites, clamped
   * inside its region. Terminals get luminous beads and hair-fine twigs. */
  private growNeuron(soma: THREE.Vector3, dir0: THREE.Vector3, color: THREE.Color,
                     region: Lobe, rng: () => number, len0: number,
                     beadProb: number, spread: number) {
    const segs: number[] = []
    const cols: number[] = []
    const beads: number[] = []
    const beadCols: number[] = []

    const reflect = (p: THREE.Vector3, d: THREE.Vector3) => {
      const lx = p.x - region.c.x, ly = p.y - region.c.y, lz = p.z - region.c.z
      const bx = region.r.x * 0.97, by = region.r.y * 0.97, bz = region.r.z * 0.97
      if (Math.abs(lx) > bx) { p.x = region.c.x + Math.sign(lx) * bx; d.x *= -0.6 }
      if (Math.abs(ly) > by) { p.y = region.c.y + Math.sign(ly) * by; d.y *= -0.6 }
      if (Math.abs(lz) > bz) { p.z = region.c.z + Math.sign(lz) * bz; d.z *= -0.6 }
    }

    const emitBead = (p: THREE.Vector3, boost: number) => {
      beads.push(p.x, p.y, p.z)
      beadCols.push(Math.min(1.1, color.r * boost), Math.min(1.1, color.g * boost),
        Math.min(1.1, color.b * boost))
    }

    const pushSeg = (a: THREE.Vector3, b: THREE.Vector3) => {
      segs.push(a.x, a.y, a.z, b.x, b.y, b.z)
      cols.push(color.r, color.g, color.b, color.r, color.g, color.b)
    }

    /* hair-fine terminal twig — the individually visible micro detail */
    const twig = (from: THREE.Vector3, dir: THREE.Vector3) => {
      const d = dir.clone().normalize()
      const p = from.clone()
      const n = 2 + Math.floor(rng() * 2)
      for (let i = 0; i < n; i++) {
        d.x += (rng() - 0.5) * 0.7; d.y += (rng() - 0.5) * 0.7; d.z += (rng() - 0.5) * 0.7
        d.normalize()
        const q = p.clone().addScaledVector(d, 0.05 + rng() * 0.05)
        pushSeg(p, q)
        p.copy(q)
      }
      if (rng() < 0.6) emitBead(p, 1.0)
    }

    const roads: Road[] = []
    const grow = (from: THREE.Vector3, dir: THREE.Vector3, len: number,
                  depth: number, chain: THREE.Vector3[]) => {
      const steps = 5 + Math.floor(rng() * 4)
      const pts: THREE.Vector3[] = []
      const d = dir.clone().normalize()
      const p = from.clone()
      for (let i = 0; i < steps; i++) {
        d.x += (rng() - 0.5) * spread; d.y += (rng() - 0.5) * spread; d.z += (rng() - 0.5) * spread
        d.normalize()
        p.addScaledVector(d, len / steps)
        reflect(p, d)
        pts.push(p.clone())
      }
      let prev = from
      for (const q of pts) {
        pushSeg(prev, q)
        prev = q
      }
      if (rng() < beadProb) emitBead(prev, 0.9)
      const childChain = chain.concat(pts)
      if (depth >= 3 || len < 0.17) {
        roads.push(this.makeRoad(childChain))
        twig(prev, d)
        if (rng() < 0.5) twig(prev, d)
        return
      }
      const kids = rng() < 0.2 ? 3 : 2
      for (let k = 0; k < kids; k++) {
        const axis = new THREE.Vector3(rng() - 0.5, rng() - 0.5, rng() - 0.5).normalize()
        const nd = d.clone().applyAxisAngle(axis, 0.4 + rng() * 0.7)
        grow(prev, nd, len * (0.58 + rng() * 0.24), depth + 1, childChain)
      }
    }

    /* the soma itself is a bright knot */
    emitBead(soma, 1.15)
    grow(soma, dir0, len0, 0, [soma])
    return { segs, cols, beads, beadCols, roads }
  }

  /** all neurons, region by region — the stain layout of the reference */
  private buildNeurons(rng: () => number) {
    const segs: number[] = []
    const cols: number[] = []
    const beads: number[] = []
    const beadCols: number[] = []
    const c = new THREE.Color()

    const plant = (soma: THREE.Vector3, dir: THREE.Vector3, palette: string[],
                   region: Lobe, len0: number, beadProb: number, spread = 0.36) => {
      c.set(palette[Math.floor(rng() * palette.length)])
      const r = this.growNeuron(soma, dir, c, region, rng, len0, beadProb, spread)
      segs.push(...r.segs); cols.push(...r.cols)
      beads.push(...r.beads); beadCols.push(...r.beadCols)
      for (const road of r.roads) if (road.total > 0.5) this.roads.push(road)
    }

    /* left lateral lobe — hot pink fans bursting from the tract entry */
    for (let i = 0; i < 15; i++) {
      const soma = ENTRY_L.clone().add(new THREE.Vector3(
        -0.12 - rng() * 0.18, (rng() - 0.5) * 0.16, (rng() - 0.5) * 0.14))
      const dir = new THREE.Vector3(-(0.6 + rng() * 0.5), (rng() - 0.5) * 0.9,
        (rng() - 0.5) * 0.6).normalize()
      plant(soma, dir, P_OPTIC_L, OPTIC_L, 1.05 + rng() * 0.5, 0.55, 0.4)
    }
    /* right lateral lobe — neon green fans */
    for (let i = 0; i < 15; i++) {
      const soma = ENTRY_R.clone().add(new THREE.Vector3(
        0.12 + rng() * 0.18, (rng() - 0.5) * 0.16, (rng() - 0.5) * 0.14))
      const dir = new THREE.Vector3(0.6 + rng() * 0.5, (rng() - 0.5) * 0.9,
        (rng() - 0.5) * 0.6).normalize()
      plant(soma, dir, P_OPTIC_R, OPTIC_R, 1.05 + rng() * 0.5, 0.55, 0.4)
    }
    /* upper-left hemisphere — red, crimson, magenta, orange, yellow */
    for (let i = 0; i < 14; i++) {
      const soma = this.inLobe(rng, HEMI_L, 0.2, 0.8)
      const dir = new THREE.Vector3(rng() - 0.5, rng() - 0.2, rng() - 0.5).normalize()
      plant(soma, dir, P_HEMI_L, HEMI_L, 0.8 + rng() * 0.5, 0.3)
    }
    /* upper-right hemisphere — green, cyan, turquoise, electric blue */
    for (let i = 0; i < 14; i++) {
      const soma = this.inLobe(rng, HEMI_R, 0.2, 0.8)
      const dir = new THREE.Vector3(rng() - 0.5, rng() - 0.2, rng() - 0.5).normalize()
      plant(soma, dir, P_HEMI_R, HEMI_R, 0.8 + rng() * 0.5, 0.3)
    }
    /* top-centre dense knot where the hemispheres approach */
    for (let i = 0; i < 7; i++) {
      const left = i < 4
      const soma = new THREE.Vector3((rng() - 0.5) * 0.2,
        0.78 + rng() * 0.16, (rng() - 0.5) * 0.2)
      plant(soma, new THREE.Vector3((rng() - 0.5) * 0.6, 0.4 + rng() * 0.5,
        (rng() - 0.5) * 0.4).normalize(), left ? P_TOP_L : P_TOP_R,
        left ? HEMI_L : HEMI_R, 0.34 + rng() * 0.2, 0.7, 0.5)
    }
    /* lower region + the downward-pointing tract — blue/cyan/green */
    for (let i = 0; i < 9; i++) {
      const soma = this.inLobe(rng, LOWER, 0.2, 0.8)
      const down = new THREE.Vector3((rng() - 0.5) * 0.7, -0.3 - rng() * 0.6,
        (rng() - 0.5) * 0.4).normalize()
      plant(soma, down, P_LOWER, LOWER, 0.6 + rng() * 0.4, 0.4)
    }

    /* fibres: additive thin lines — sharp cores, the bloom adds the halo */
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(segs, 3))
    g.setAttribute('color', new THREE.Float32BufferAttribute(cols, 3))
    const lines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.72,
      blending: THREE.AdditiveBlending, depthWrite: false
    }))
    lines.renderOrder = 1
    this.group.add(lines)

    /* luminous synapse dots along every arbor */
    const bg = new THREE.BufferGeometry()
    bg.setAttribute('position', new THREE.Float32BufferAttribute(beads, 3))
    bg.setAttribute('color', new THREE.Float32BufferAttribute(beadCols, 3))
    const points = new THREE.Points(bg, new THREE.PointsMaterial({
      size: 0.05, vertexColors: true, transparent: true, opacity: 0.95,
      map: radialTexture('#ffffff'), blending: THREE.AdditiveBlending,
      depthWrite: false, sizeAttenuation: true
    }))
    points.renderOrder = 2
    this.group.add(points)
  }

  /* ------------------------------------------------- major bundle tracts */
  /** A thick primary pathway: outer halo tube + bright inner core tube; its
   * centreline becomes a road the light can race down. */
  private addTract(pts: THREE.Vector3[], hex: string, radius: number) {
    const curve = new THREE.CatmullRomCurve3(pts, false, 'catmullrom', 0.5)
    const halo = new THREE.Mesh(
      new THREE.TubeGeometry(curve, 36, radius, 6, false),
      new THREE.MeshBasicMaterial({ color: new THREE.Color(hex), transparent: true,
        opacity: 0.2, blending: THREE.AdditiveBlending, depthWrite: false }))
    halo.renderOrder = 1
    this.group.add(halo)
    const coreCol = new THREE.Color(hex).lerp(new THREE.Color('#ffffff'), 0.35)
    const core = new THREE.Mesh(
      new THREE.TubeGeometry(curve, 36, radius * 0.45, 6, false),
      new THREE.MeshBasicMaterial({ color: coreCol, transparent: true,
        opacity: 0.78, blending: THREE.AdditiveBlending, depthWrite: false }))
    core.renderOrder = 2
    this.group.add(core)
    this.roads.push(this.makeRoad(curve.getPoints(40)))
  }

  private buildTracts(rng: () => number) {
    /* the horizontal electric-blue bow across the whole brain */
    this.addTract([
      new THREE.Vector3(-0.85, 0.02, 0.05), new THREE.Vector3(-0.4, -0.28, 0.08),
      new THREE.Vector3(0, -0.4, 0.1), new THREE.Vector3(0.4, -0.28, 0.08),
      new THREE.Vector3(0.85, 0.02, 0.05)], '#2f8fff', 0.05)
    /* optic tracts: lateral lobes into the hemispheres (with the bright knots) */
    this.addTract([new THREE.Vector3(-1.52, 0.04, 0), new THREE.Vector3(-1.1, 0.14, 0),
      new THREE.Vector3(-0.72, 0.26, 0)], '#ff4f9e', 0.05)
    this.addTract([new THREE.Vector3(1.52, 0.04, 0), new THREE.Vector3(1.1, 0.14, 0),
      new THREE.Vector3(0.72, 0.26, 0)], '#39ff6e', 0.05)
    /* descending central tract to the downward point */
    this.addTract([new THREE.Vector3(0, -0.12, 0), new THREE.Vector3(0.05, -0.55, 0.04),
      new THREE.Vector3(-0.02, -1.02, 0.02)], '#00d0ff', 0.04)
    /* upper arcs over each hemisphere */
    this.addTract([new THREE.Vector3(-0.75, 0.2, 0), new THREE.Vector3(-0.5, 0.78, 0),
      new THREE.Vector3(-0.08, 0.9, 0)], '#ff3d3d', 0.032)
    this.addTract([new THREE.Vector3(0.75, 0.2, 0), new THREE.Vector3(0.5, 0.78, 0),
      new THREE.Vector3(0.08, 0.9, 0)], '#00c8ff', 0.032)
    /* the green loop in the right hemisphere (as in the reference) */
    const loop: THREE.Vector3[] = []
    for (let i = 0; i <= 14; i++) {
      const a = (i / 14) * Math.PI * 1.65 + 0.5
      loop.push(new THREE.Vector3(0.42 + Math.cos(a) * 0.34, 0.3 + Math.sin(a) * 0.3, 0.05))
    }
    this.addTract(loop, '#2fe85c', 0.028)
    /* red loop lower-left of the hemispheres */
    const loop2: THREE.Vector3[] = []
    for (let i = 0; i <= 12; i++) {
      const a = Math.PI * 0.9 + (i / 12) * Math.PI * 1.4
      loop2.push(new THREE.Vector3(-0.4 + Math.cos(a) * 0.3, -0.05 + Math.sin(a) * 0.26, 0.08))
    }
    this.addTract(loop2, '#e8143c', 0.026)

    /* bright soma knots at the optic entries (the glowing junction clusters) */
    const pos: number[] = []
    const col: number[] = []
    const rngCols = ['#ff5fa8', '#ff85c2', '#5fff9e', '#8dffab']
    for (const entry of [ENTRY_L, ENTRY_R]) {
      for (let i = 0; i < 26; i++) {
        const v = new THREE.Vector3(rng() - 0.5, rng() - 0.5, rng() - 0.5)
          .multiplyScalar(0.14)
        pos.push(entry.x + v.x, entry.y + v.y * 0.8, entry.z + v.z)
        const c = new THREE.Color(rngCols[Math.floor(rng() * rngCols.length)])
        col.push(c.r * 0.95, c.g * 0.95, c.b * 0.95)
      }
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
    const pts = new THREE.Points(g, new THREE.PointsMaterial({
      size: 0.07, vertexColors: true, transparent: true, opacity: 1,
      map: radialTexture('#ffffff'), blending: THREE.AdditiveBlending,
      depthWrite: false, sizeAttenuation: true
    }))
    pts.renderOrder = 3
    this.group.add(pts)
  }

  /* --------------------------------------------------- the ONE light line */
  private buildBeam() {
    this.beamPos = new Float32Array(this.TRAIL * 3)
    this.beamCol = new Float32Array(this.TRAIL * 3)
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(this.beamPos, 3))
    g.setAttribute('color', new THREE.BufferAttribute(this.beamCol, 3))
    this.beamLine = new THREE.Line(g, new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 1,
      blending: THREE.AdditiveBlending, depthWrite: false
    }))
    this.beamLine.frustumCulled = false
    this.beamLine.renderOrder = 5
    this.group.add(this.beamLine)
    this.headTex = radialTexture('#ffffff')
    this.beamHead = new THREE.Sprite(new THREE.SpriteMaterial({
      map: this.headTex, transparent: true, opacity: 0.55,
      blending: THREE.AdditiveBlending, depthWrite: false
    }))
    this.beamHead.scale.setScalar(0.22)
    this.beamHead.renderOrder = 6
    this.group.add(this.beamHead)

    if (this.roads.length) {
      let best = 0
      for (let i = 1; i < this.roads.length; i++) {
        if (this.roads[i].total > this.roads[best].total) best = i
      }
      this.roadIdx = best
    }
  }

  private pointAt(road: Road, s: number, reversed: boolean, out: THREE.Vector3) {
    const { pts, cum, total } = road
    const u = Math.max(0, Math.min(total, s))
    let lo = 0, hi = cum.length - 1
    while (lo < hi - 1) {
      const mid = (lo + hi) >> 1
      if (cum[mid] <= u) lo = mid; else hi = mid
    }
    const seg = cum[hi] - cum[lo] || 1e-6
    const f = (u - cum[lo]) / seg
    const a = pts[lo], b = pts[hi]
    if (!reversed) out.set(a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f, a.z + (b.z - a.z) * f)
    else out.set(b.x + (a.x - b.x) * f, b.y + (a.y - b.y) * f, b.z + (a.z - b.z) * f)
    return out
  }

  private hop() {
    const road = this.roads[this.roadIdx]
    const end = road.pts[this.forward ? road.pts.length - 1 : 0]
    let best = -1, bestD = 0.45
    for (let tries = 0; tries < 24; tries++) {
      const i = Math.floor(Math.random() * this.roads.length)
      if (i === this.roadIdx) continue
      const cand = this.roads[i]
      const d0 = end.distanceTo(cand.pts[0])
      const d1 = end.distanceTo(cand.pts[cand.pts.length - 1])
      if (d0 < bestD) { bestD = d0; best = i; this.forward = true }
      if (d1 < bestD) { bestD = d1; best = i; this.forward = false }
    }
    if (best < 0) {
      best = Math.floor(Math.random() * this.roads.length)
      this.forward = Math.random() < 0.5
    }
    this.roadIdx = best
    this.s = 0
  }

  /** a thinking / questioning event: the ONE line takes the desk's colour and
   * sprints, then settles back to its fast quiet run */
  think(colorHex?: string, strength = 1) {
    if (this.disposed) return
    const st = Math.max(0.6, Math.min(1.5, strength))
    this.targetColor.set(colorHex || '#dff6ff')
    this.flare = Math.min(1.4, this.flare + 0.55 * st)
    this.targetSpeed = this.baseSpeed * (2.0 + 0.5 * st) + this.energy * 2
    this.thoughtCount++
  }

  private tmpA = new THREE.Vector3()
  private tmpB = new THREE.Vector3()

  private step() {
    const dt = Math.min(0.05, this.clock.getDelta())
    this.t += dt
    this.group.rotation.y = Math.sin(this.t * 0.1) * 0.38
    this.group.rotation.x = Math.sin(this.t * 0.065) * 0.05

    this.flare = Math.max(0, this.flare - dt * 0.9)
    if (this.flare < 0.02) this.targetColor.set('#c9f2ff')
    this.targetSpeed += (this.baseSpeed + this.energy * 1.5 - this.targetSpeed) * dt * 1.4
    this.speed = this.targetSpeed * (1 + this.flare * 0.3)
    this.beamColor.lerp(this.targetColor, Math.min(1, dt * 5))

    const road = this.roads[this.roadIdx]
    if (road) {
      this.s += dt * this.speed
      if (this.s >= road.total) this.hop()
      const boost = 1 + this.flare * 0.3
      for (let i = 0; i < this.TRAIL; i++) {
        const back = (this.TRAIL - 1 - i) * this.STEP
        this.pointAt(this.roads[this.roadIdx], this.s - back, !this.forward, this.tmpA)
        this.beamPos[i * 3] = this.tmpA.x
        this.beamPos[i * 3 + 1] = this.tmpA.y
        this.beamPos[i * 3 + 2] = this.tmpA.z
        const k = Math.pow(i / (this.TRAIL - 1), 1.7)
        const r = this.beamColor.r, g = this.beamColor.g, b = this.beamColor.b
        /* light line: tinted head, softly fading tail — visible, never blinding */
        this.beamCol[i * 3] = (r * (0.4 + 0.6 * k) + 0.3 * k * k) * boost
        this.beamCol[i * 3 + 1] = (g * (0.4 + 0.6 * k) + 0.3 * k * k) * boost
        this.beamCol[i * 3 + 2] = (b * (0.4 + 0.6 * k) + 0.34 * k * k) * boost
      }
      ;(this.beamLine.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true
      ;(this.beamLine.geometry.attributes.color as THREE.BufferAttribute).needsUpdate = true
      this.pointAt(this.roads[this.roadIdx], this.s, !this.forward, this.tmpB)
      this.beamHead.position.copy(this.tmpB)
      this.beamHead.scale.setScalar(0.2 + 0.05 * Math.min(1, this.speed / 10) +
        this.flare * 0.1 + Math.sin(this.t * 10) * 0.015)
      ;(this.beamHead.material as THREE.SpriteMaterial).opacity = 0.45 + this.flare * 0.2
    }
    this.composer.render()
  }

  /** live fly-brain activity — a strike flashes the light amber at triple speed */
  setActivity(fly: any) {
    const st = fly?.brain?.state || {}
    this.energy = Math.min(1, Math.max(0.12, Math.abs(Number(st.score ?? 0.4))))
    if ((fly?.strike_flash || 0) > 0.25) {
      this.flare = Math.max(this.flare, 1.1)
      this.targetColor.set('#ffd166')
      this.targetSpeed = this.baseSpeed * 3.2
    }
  }

  get thoughts() { return this.thoughtCount }

  private resize() {
    const w = this.host.clientWidth || 320
    const h = this.host.clientHeight || 240
    this.renderer.setSize(w, h)
    this.composer.setSize(w, h)
    this.bloom.setSize(w, h)
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
  }

  dispose() {
    this.disposed = true
    this.offBus()
    cancelAnimationFrame(this.raf)
    this.ro?.disconnect()
    this.headTex?.dispose()
    this.composer?.dispose()
    this.renderer.dispose()
    this.renderer.domElement.remove()
  }
}

function radialTexture(hex: string): THREE.Texture {
  const cv = document.createElement('canvas')
  cv.width = cv.height = 64
  const g = cv.getContext('2d')!
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32)
  grad.addColorStop(0, hex)
  grad.addColorStop(0.35, hex + 'aa')
  grad.addColorStop(1, '#00000000')
  g.fillStyle = grad
  g.fillRect(0, 0, 64, 64)
  const tex = new THREE.CanvasTexture(cv)
  return tex
}
