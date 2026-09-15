/** Drosophila brain — single-neuron confocal style, like the multicolour
 * Golgi/FlipOut atlases.
 *
 * Architecture first: the brain is grown as NEURONS, not as glowing wires.
 * Each neuron is a branching arbor (soma → trunk → recursive dendrites) that
 * lives in one region of the brain — left optic lobe (pink/red family), right
 * optic lobe (green family), central brain (red/green/blue mix) — plus a few
 * long tract neurons bridging optic→central. Every neuron keeps ONE dim colour;
 * the veins are rendered thin and wispy with normal blending so they do NOT
 * shine. Soma and tip beads punctuate the arbors; a barely-there dark membrane
 * gives the ghost silhouette on black.
 *
 * Light: exactly ONE line of light runs fast through the veins, continuously,
 * hopping arbor to arbor. When a desk on the floor THINKS or QUESTIONS (cabin
 * hearing, verdict, CEO ruling, chat Q&A, operator ask), that one line takes
 * the thinker's colour and sprints harder, then settles back. No thought, no
 * colour change — the light keeps its own quiet run.
 */
import * as THREE from 'three'
import { onThought, type Thought } from '../state/brainBus'

/* one colour family per brain region, like the stained neuron populations */
const PALETTE_L = ['#ff5d7a', '#e84a6f', '#ff7a9e', '#d94f6c', '#ff8fa8']
const PALETTE_R = ['#4ade80', '#35c96f', '#6ee7a0', '#2fae5f', '#57d98a']
const PALETTE_C = ['#e84a6f', '#4ade80', '#4a7dff', '#35c96f', '#ff5d7a', '#3f6fe0',
  '#6ee7a0', '#ff7a9e']

function mulberry(seed: number) {
  let a = seed >>> 0
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/* brain lobes — central brain + two big optic lobes + the lower stalk */
const HEMI_L = { c: new THREE.Vector3(-0.5, 0.3, 0), r: new THREE.Vector3(0.82, 0.7, 0.62) }
const HEMI_R = { c: new THREE.Vector3(0.5, 0.3, 0), r: new THREE.Vector3(0.82, 0.7, 0.62) }
const LOWER = { c: new THREE.Vector3(0, -0.44, 0), r: new THREE.Vector3(0.6, 0.5, 0.55) }
const OPTIC_L = { c: new THREE.Vector3(-1.86, 0.04, 0), r: new THREE.Vector3(0.62, 0.76, 0.44) }
const OPTIC_R = { c: new THREE.Vector3(1.86, 0.04, 0), r: new THREE.Vector3(0.62, 0.76, 0.44) }

type Lobe = typeof HEMI_L
const LOBES = [HEMI_L, HEMI_R, LOWER, OPTIC_L, OPTIC_R]
const CENTRAL = [HEMI_L, HEMI_L, HEMI_R, HEMI_R, LOWER]

/* one road = a root→tip arbor path the light line can run along */
interface Road {
  pts: THREE.Vector3[]
  cum: number[]
  total: number
}

interface Arbor {
  segs: number[]
  cols: number[]
  beads: number[]
  beadCols: number[]
  roads: Road[]
}

export class FlyBrainViz {
  private renderer: THREE.WebGLRenderer
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

  /* beam state — the ONE line of light */
  private roadIdx = 0
  private forward = true
  private s = 0
  private baseSpeed = 4.2
  private speed = this.baseSpeed
  private targetSpeed = this.baseSpeed
  private beamColor = new THREE.Color('#bfe9ff')
  private targetColor = new THREE.Color('#bfe9ff')
  private flare = 0

  private energy = 0.4
  private t = 0
  private thoughtCount = 0

  private readonly TRAIL = 30
  private readonly STEP = 0.05            /* arclength spacing of trail samples */

  constructor(private host: HTMLElement) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    this.renderer.setClearColor(0x000000, 0)
    host.appendChild(this.renderer.domElement)
    this.camera.position.set(0, 0.35, 6.4)
    this.camera.lookAt(0, 0, 0)
    this.scene.add(this.group)

    const rng = mulberry(20250914)
    this.buildMembrane()
    this.buildNeurons(rng)
    this.buildCortexBeads(rng)
    this.buildBeam()

    /* every thought published on the floor steers the one light */
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
  private ellipsoid(lobe: Lobe, opacity: number, color = 0x1c2230) {
    const m = new THREE.Mesh(
      new THREE.SphereGeometry(1, 30, 22),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false }))
    m.position.copy(lobe.c)
    m.scale.copy(lobe.r)
    return m
  }

  /* the ghost silhouette — barely lighter than the void, never a surface */
  private buildMembrane() {
    for (const lobe of LOBES) {
      const fill = this.ellipsoid(lobe, 0.32, 0x141a26)
      fill.renderOrder = -2
      this.group.add(fill)
      const rim = this.ellipsoid(lobe, 0.1, 0x27303f)
      rim.scale.multiplyScalar(1.015)
      rim.renderOrder = -1
      this.group.add(rim)
    }
  }

  private inLobe(rng: () => number, lobe: Lobe, lo = 0.15, hi = 0.8): THREE.Vector3 {
    const v = new THREE.Vector3(rng() * 2 - 1, rng() * 2 - 1, rng() * 2 - 1)
    if (v.length() > 1) v.normalize()
    const k = lo + rng() * (hi - lo)
    return new THREE.Vector3(lobe.c.x + v.x * lobe.r.x * k,
      lobe.c.y + v.y * lobe.r.y * k, lobe.c.z + v.z * lobe.r.z * k)
  }

  /* grow one neuron: soma → trunk → recursive dendrites, clamped inside its
   * region. Roads record every root→tip chain so the light can run the arbor. */
  private growNeuron(soma: THREE.Vector3, color: THREE.Color, region: Lobe, rng: () => number,
                     clampRegion: boolean): Arbor {
    const segs: number[] = []
    const cols: number[] = []
    const beads: number[] = [soma.x, soma.y, soma.z]
    const beadCols: number[] = [color.r, color.g, color.b]
    const roads: Road[] = []
    const maxDepth = 3
    const len0 = ((region.r.x + region.r.y) * 0.5) * (0.62 + rng() * 0.5)

    const reflect = (p: THREE.Vector3, d: THREE.Vector3) => {
      if (!clampRegion) return
      const lx = p.x - region.c.x, ly = p.y - region.c.y, lz = p.z - region.c.z
      const bx = region.r.x * 0.96, by = region.r.y * 0.96, bz = region.r.z * 0.96
      if (Math.abs(lx) > bx) { p.x = region.c.x + Math.sign(lx) * bx; d.x *= -0.6 }
      if (Math.abs(ly) > by) { p.y = region.c.y + Math.sign(ly) * by; d.y *= -0.6 }
      if (Math.abs(lz) > bz) { p.z = region.c.z + Math.sign(lz) * bz; d.z *= -0.6 }
    }

    const pushSeg = (a: THREE.Vector3, b: THREE.Vector3) => {
      segs.push(a.x, a.y, a.z, b.x, b.y, b.z)
      cols.push(color.r, color.g, color.b, color.r, color.g, color.b)
    }

    const grow = (from: THREE.Vector3, dir: THREE.Vector3, len: number, depth: number,
                  chain: THREE.Vector3[]) => {
      const steps = 6 + Math.floor(rng() * 6)
      const pts: THREE.Vector3[] = []
      const d = dir.clone().normalize()
      const p = from.clone()
      for (let i = 0; i < steps; i++) {
        d.x += (rng() - 0.5) * 0.36; d.y += (rng() - 0.5) * 0.36; d.z += (rng() - 0.5) * 0.36
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
      const childChain = chain.concat(pts)
      if (depth >= maxDepth || len < 0.16) {
        roads.push(this.makeRoad(childChain))
        if (rng() < 0.4) {
          beads.push(prev.x, prev.y, prev.z)
          beadCols.push(color.r, color.g, color.b)
        }
        return
      }
      const kids = rng() < 0.18 ? 3 : 2
      for (let k = 0; k < kids; k++) {
        const axis = new THREE.Vector3(rng() - 0.5, rng() - 0.5, rng() - 0.5).normalize()
        const nd = d.clone().applyAxisAngle(axis, 0.45 + rng() * 0.65)
        grow(prev, nd, len * (0.58 + rng() * 0.24), depth + 1, childChain)
      }
    }

    const init = new THREE.Vector3(rng() - 0.5, rng() - 0.5, rng() - 0.5).normalize()
    grow(soma, init, len0, 0, [soma])
    return { segs, cols, beads, beadCols, roads }
  }

  private makeRoad(pts: THREE.Vector3[]): Road {
    const cum = [0]
    for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + pts[i].distanceTo(pts[i - 1]))
    return { pts, cum, total: cum[cum.length - 1] }
  }

  /* the brain, neuron by neuron — region palettes like the stained preparation */
  private buildNeurons(rng: () => number) {
    const segs: number[] = []
    const cols: number[] = []
    const beads: number[] = []
    const beadCols: number[] = []
    const c = new THREE.Color()

    const plant = (soma: THREE.Vector3, palette: string[], region: Lobe,
                   clampRegion: boolean, shade: number) => {
      c.set(palette[Math.floor(rng() * palette.length)])
      c.multiplyScalar(shade)
      const arbor = this.growNeuron(soma, c, region, rng, clampRegion)
      segs.push(...arbor.segs)
      cols.push(...arbor.cols)
      beads.push(...arbor.beads)
      beadCols.push(...arbor.beadCols)
      for (const r of arbor.roads) if (r.total > 0.55) this.roads.push(r)
    }

    /* left optic lobe — the pink/red population */
    for (let i = 0; i < 15; i++) plant(this.inLobe(rng, OPTIC_L, 0.2, 0.85), PALETTE_L,
      OPTIC_L, true, 0.32 + rng() * 0.22)
    /* right optic lobe — the green population */
    for (let i = 0; i < 15; i++) plant(this.inLobe(rng, OPTIC_R, 0.2, 0.85), PALETTE_R,
      OPTIC_R, true, 0.32 + rng() * 0.22)
    /* central brain — the red/green/blue mix */
    for (let i = 0; i < 30; i++) {
      const region = CENTRAL[Math.floor(rng() * CENTRAL.length)]
      plant(this.inLobe(rng, region, 0.15, 0.8), PALETTE_C, region, true,
        0.3 + rng() * 0.22)
    }
    /* tract neurons bridging optic → central (long smooth axons) */
    for (let i = 0; i < 7; i++) {
      const side = rng() < 0.5
      const optic = side ? OPTIC_L : OPTIC_R
      const hemi = side ? HEMI_L : HEMI_R
      const soma = this.inLobe(rng, optic, 0.3, 0.7)
      const dir = new THREE.Vector3().subVectors(hemi.c, soma).normalize()
      const pal = side ? PALETTE_L : PALETTE_R
      c.set(pal[Math.floor(rng() * pal.length)]).multiplyScalar(0.38)
      const arbor = this.growTract(soma, dir, c, 1.5 + rng() * 0.7, rng)
      segs.push(...arbor.segs)
      cols.push(...arbor.cols)
      beads.push(...arbor.beads)
      beadCols.push(...arbor.beadCols)
      for (const r of arbor.roads) if (r.total > 0.55) this.roads.push(r)
    }

    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(segs, 3))
    g.setAttribute('color', new THREE.Float32BufferAttribute(cols, 3))
    /* wispy veins: normal blending, thin, dim — they never shine */
    const lines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.66, depthWrite: false
    }))
    lines.renderOrder = 1
    this.group.add(lines)

    const bg = new THREE.BufferGeometry()
    bg.setAttribute('position', new THREE.Float32BufferAttribute(beads, 3))
    bg.setAttribute('color', new THREE.Float32BufferAttribute(beadCols, 3))
    const points = new THREE.Points(bg, new THREE.PointsMaterial({
      size: 0.042, vertexColors: true, transparent: true, opacity: 0.6,
      depthWrite: false, sizeAttenuation: true
    }))
    points.renderOrder = 2
    this.group.add(points)
  }


  /* long smooth tract axon — few branches, far reach */
  private growTract(soma: THREE.Vector3, dir: THREE.Vector3, color: THREE.Color,
                    len: number, rng: () => number): Arbor {
    const segs: number[] = []
    const cols: number[] = []
    const beads: number[] = []
    const beadCols: number[] = []
    const roads: Road[] = []
    const d = dir.clone()
    const p = soma.clone()
    const steps = 10 + Math.floor(rng() * 5)
    const chain = [soma.clone()]
    for (let i = 0; i < steps; i++) {
      d.x += (rng() - 0.5) * 0.16; d.y += (rng() - 0.5) * 0.16; d.z += (rng() - 0.5) * 0.12
      d.normalize()
      const q = p.clone().addScaledVector(d, len / steps)
      segs.push(p.x, p.y, p.z, q.x, q.y, q.z)
      cols.push(color.r, color.g, color.b, color.r, color.g, color.b)
      chain.push(q)
      p.copy(q)
    }
    if (rng() < 0.7) {
      beads.push(p.x, p.y, p.z)
      beadCols.push(color.r, color.g, color.b)
    }
    roads.push(this.makeRoad(chain))
    /* one small distal twig */
    const t0 = p.clone()
    const td = d.clone().applyAxisAngle(new THREE.Vector3(0, 0, 1), (rng() - 0.5) * 2)
    const chain2 = [t0.clone()]
    const q0 = t0.clone()
    for (let i = 0; i < 4; i++) {
      td.y += (rng() - 0.5) * 0.3; td.normalize()
      const q = q0.clone().addScaledVector(td, 0.09)
      segs.push(q0.x, q0.y, q0.z, q.x, q.y, q.z)
      cols.push(color.r, color.g, color.b, color.r, color.g, color.b)
      chain2.push(q)
      q0.copy(q)
    }
    roads.push(this.makeRoad(chain2))
    return { segs, cols, beads, beadCols, roads }
  }

  /* the beaded cortex rings visible around each optic lobe in the preparation */
  private buildCortexBeads(rng: () => number) {
    const pos: number[] = []
    const col: number[] = []
    const c = new THREE.Color()
    for (const [lobe, pal] of [[OPTIC_L, PALETTE_L], [OPTIC_R, PALETTE_R]] as
        [typeof OPTIC_L, string[]][]) {
      c.set(pal[Math.floor(rng() * pal.length)])
      for (let i = 0; i < 150; i++) {
        const v = new THREE.Vector3(rng() * 2 - 1, rng() * 2 - 1, rng() * 2 - 1)
          .normalize().multiplyScalar(0.86 + rng() * 0.14)
        pos.push(lobe.c.x + v.x * lobe.r.x * 1.02,
                 lobe.c.y + v.y * lobe.r.y * 1.02,
                 lobe.c.z + v.z * lobe.r.z * 1.02)
        const b = 0.22 + rng() * 0.2
        col.push(c.r * b, c.g * b, c.b * b)
      }
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
    const pts = new THREE.Points(g, new THREE.PointsMaterial({
      size: 0.05, vertexColors: true, transparent: true, opacity: 0.5,
      depthWrite: false, sizeAttenuation: true
    }))
    pts.renderOrder = 2
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
      vertexColors: true, transparent: true, opacity: 0.95,
      blending: THREE.AdditiveBlending, depthWrite: false
    }))
    this.beamLine.frustumCulled = false
    this.beamLine.renderOrder = 5
    this.group.add(this.beamLine)
    this.headTex = radialTexture('#ffffff')
    this.beamHead = new THREE.Sprite(new THREE.SpriteMaterial({
      map: this.headTex, transparent: true, opacity: 0.95,
      blending: THREE.AdditiveBlending, depthWrite: false
    }))
    this.beamHead.scale.setScalar(0.34)
    this.beamHead.renderOrder = 6
    this.group.add(this.beamHead)

    /* start on a decent long road */
    if (this.roads.length) {
      let best = 0
      for (let i = 1; i < this.roads.length; i++) {
        if (this.roads[i].total > this.roads[best].total) best = i
      }
      this.roadIdx = best
    }
  }

  /** arclength lookup along a road, forward or reversed */
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

  private endOf(road: Road, reversed: boolean, out: THREE.Vector3) {
    const p = reversed ? road.pts[0] : road.pts[road.pts.length - 1]
    return out.copy(p)
  }

  private hop() {
    const road = this.roads[this.roadIdx]
    const end = this.endOf(road, !this.forward, this.tmpA)
    let best = -1, bestD = 0.42
    for (let tries = 0; tries < 24; tries++) {
      const i = Math.floor(Math.random() * this.roads.length)
      if (i === this.roadIdx) continue
      const cand = this.roads[i]
      /* the light flows arbor→arbor: enter where the last one left */
      const dInStart = end.distanceTo(cand.pts[0])
      const dInEnd = end.distanceTo(cand.pts[cand.pts.length - 1])
      if (dInStart < bestD) { bestD = dInStart; best = i; this.forward = true }
      if (dInEnd < bestD) { bestD = dInEnd; best = i; this.forward = false }
    }
    if (best < 0) {
      best = Math.floor(Math.random() * this.roads.length)
      this.forward = Math.random() < 0.5
    }
    this.roadIdx = best
    this.s = 0
  }

  /** a thinking / questioning event: the ONE line takes the thinker's colour
   * and sprints, then quietly settles back */
  think(colorHex?: string, strength = 1) {
    if (this.disposed) return
    const st = Math.max(0.6, Math.min(1.5, strength))
    this.targetColor.set(colorHex || '#dff6ff')
    this.flare = Math.min(1.4, this.flare + 0.55 * st)
    this.targetSpeed = this.baseSpeed * (1.7 + 0.5 * st) + this.energy * 2
    this.thoughtCount++
  }

  private tmpA = new THREE.Vector3()
  private tmpB = new THREE.Vector3()

  private step() {
    const dt = Math.min(0.05, this.clock.getDelta())
    this.t += dt
    this.group.rotation.y = Math.sin(this.t * 0.1) * 0.42
    this.group.rotation.x = Math.sin(this.t * 0.065) * 0.05

    /* colour + speed relax back to the resting run */
    this.flare = Math.max(0, this.flare - dt * 0.9)
    if (this.flare < 0.02) this.targetColor.set('#bfe9ff')
    this.targetSpeed += (this.baseSpeed + this.energy * 1.5 - this.targetSpeed) * dt * 1.4
    this.speed = this.targetSpeed * (1 + this.flare * 0.35)
    this.beamColor.lerp(this.targetColor, Math.min(1, dt * 5))

    const road = this.roads[this.roadIdx]
    if (road) {
      this.s += dt * this.speed
      if (this.s >= road.total) { this.hop() }
      /* trail behind the head along the wire */
      const boost = 1 + this.flare * 0.7
      for (let i = 0; i < this.TRAIL; i++) {
        const back = (this.TRAIL - 1 - i) * this.STEP
        this.pointAt(this.roads[this.roadIdx], this.s - back, !this.forward, this.tmpA)
        this.beamPos[i * 3] = this.tmpA.x
        this.beamPos[i * 3 + 1] = this.tmpA.y
        this.beamPos[i * 3 + 2] = this.tmpA.z
        const k = Math.pow(i / (this.TRAIL - 1), 1.7)
        const r = this.beamColor.r, g = this.beamColor.g, b = this.beamColor.b
        /* white-hot head, tinted tail */
        this.beamCol[i * 3] = (r * (0.35 + 0.65 * k) + 0.75 * k * k) * boost
        this.beamCol[i * 3 + 1] = (g * (0.35 + 0.65 * k) + 0.75 * k * k) * boost
        this.beamCol[i * 3 + 2] = (b * (0.35 + 0.65 * k) + 0.85 * k * k) * boost
      }
      ;(this.beamLine.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true
      ;(this.beamLine.geometry.attributes.color as THREE.BufferAttribute).needsUpdate = true
      ;(this.beamLine.material as THREE.LineBasicMaterial).opacity = 0.92 + this.flare * 0.08
      this.pointAt(this.roads[this.roadIdx], this.s, !this.forward, this.tmpB)
      this.beamHead.position.copy(this.tmpB)
      this.beamHead.scale.setScalar(0.3 + 0.1 * Math.min(1, this.speed / 8) +
        this.flare * 0.22 + Math.sin(this.t * 10) * 0.02)
      ;(this.beamHead.material as THREE.SpriteMaterial).opacity = 0.85 + this.flare * 0.15
    }
    this.renderer.render(this.scene, this.camera)
  }

  /** live fly-brain activity — a strike makes the one light flash and race */
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
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
  }

  dispose() {
    this.disposed = true
    this.offBus()
    cancelAnimationFrame(this.raf)
    this.ro?.disconnect()
    this.headTex?.dispose()
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
