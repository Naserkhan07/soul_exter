/** Drosophila connectome visual — the fly brain as it is drawn in the atlases.
 *
 * At rest the brain is QUIET: no glow, no running light — you simply see the
 * colourful veins (axon fibres) drawn crisply against the dark, with faint
 * somata clusters and a whisper of membrane around them.
 *
 * Every time a desk on the floor THINKS or QUESTIONS — a judge walks into a
 * cabin, a verdict lands, the CEO rules, a chat question/answer is posted —
 * the floor publishes a "thought" and this brain answers it: a light packet
 * runs down the veins for exactly ~3 cm (the render is calibrated: the full
 * brain spans ≈9 cm across the optic lobes), taking the thinker's colour,
 * then fades. Strikes fire a racing burst. Nothing glows unless somebody
 * thought.
 */
import * as THREE from 'three'
import { onThought, type Thought } from '../state/brainBus'

/* vivid vein palette — saturated axon colours so the wires read as veins */
const WIRE_PALETTE = ['#b09a5e', '#6fb3aa', '#9a7fc4', '#c47a8f', '#5fa3c4', '#c0ac6e',
  '#6fc49a', '#c48a6a', '#7f93d6', '#9ac46f', '#45cdd6', '#e09ad2', '#d4bc50', '#94dd82',
  '#dd86b4', '#86ddcd', '#c486dd', '#ddca86']

/* --------------------------------------------------------- physical scale
 * The rendered brain (optic-lobe tip to optic-lobe tip) spans ~4.96 world
 * units and is presented ≈9 cm wide, so 1 unit ≈ 1.815 cm. A thought is a
 * packet of light that runs 3 cm of vein before fading — that distance is
 * exact, not decorative.
 */
const BRAIN_SPAN_UNITS = (1.86 + 0.62) * 2
const BRAIN_SPAN_CM = 9.0
const UNIT_CM = BRAIN_SPAN_CM / BRAIN_SPAN_UNITS
export const THOUGHT_CM = 3.0
const THOUGHT_UNITS = THOUGHT_CM / UNIT_CM
const TRAIL_CM = 2.1
const TRAIL_UNITS = TRAIL_CM / UNIT_CM

function mulberry(seed: number) {
  let a = seed >>> 0
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/* brain lobes, matching the reference silhouette (x right, y up, z viewer) */
const HEMI_L = { c: new THREE.Vector3(-0.52, 0.28, 0), r: new THREE.Vector3(0.85, 0.72, 0.68) }
const HEMI_R = { c: new THREE.Vector3(0.52, 0.28, 0), r: new THREE.Vector3(0.85, 0.72, 0.68) }
const LOWER = { c: new THREE.Vector3(0, -0.42, 0), r: new THREE.Vector3(0.78, 0.52, 0.62) }
const OPTIC_L = { c: new THREE.Vector3(-1.86, 0.02, 0), r: new THREE.Vector3(0.62, 0.78, 0.46) }
const OPTIC_R = { c: new THREE.Vector3(1.86, 0.02, 0), r: new THREE.Vector3(0.62, 0.78, 0.46) }

type Lobe = typeof HEMI_L

interface Pulse {
  line: THREE.Line
  head: THREE.Sprite
  pos: Float32Array
  col: Float32Array
  path: THREE.Vector3[] | null
  cum: number[]            /* cumulative arc length of the path */
  dist: number             /* how far the packet runs (≈3 cm in units) */
  travelled: number
  trailLen: number
  speed: number
  color: THREE.Color
  strength: number
  phase: 'run' | 'fade'
  fade: number
  active: boolean
}

const TRAIL_PTS = 16
const MAX_PULSES = 8

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

  /* the thought packets — one per thinking/questioning event */
  private paths: THREE.Vector3[][] = []
  private pathLens: number[][] = []
  private pulses: Pulse[] = []
  private headTex: THREE.Texture

  private energy = 0.4
  private flash = 0
  private t = 0
  private thoughtCount = 0

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
    this.buildFibres(rng)
    this.buildSomata(rng)

    /* pooled thought packets — built once, reused per event */
    this.headTex = radialTexture('#ffffff')
    for (let i = 0; i < MAX_PULSES; i++) this.pulses.push(this.buildPulse())

    /* every thought published on the floor lights a vein */
    this.offBus = onThought((t) => this.pulse(t.color, t.strength))

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
  private ellipsoid(lobe: Lobe, opacity: number, color = 0x9fb2c8) {
    const m = new THREE.Mesh(
      new THREE.SphereGeometry(1, 28, 20),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false }))
    m.position.copy(lobe.c)
    m.scale.copy(lobe.r)
    return m
  }

  /* the membrane stays a whisper — the VEINS are the show, not a glowing blob */
  private buildMembrane() {
    for (const lobe of [HEMI_L, HEMI_R, LOWER, OPTIC_L, OPTIC_R]) {
      this.group.add(this.ellipsoid(lobe, 0.022))
      const rim = this.ellipsoid(lobe, 0.016, 0xcfe3ff)
      rim.scale.multiplyScalar(1.02)
      this.group.add(rim)
    }
  }

  private inLobe(rng: () => number, lobe: Lobe, squash = 0.92): THREE.Vector3 {
    const v = new THREE.Vector3(rng() * 2 - 1, rng() * 2 - 1, rng() * 2 - 1)
    if (v.length() > 1) v.normalize().multiplyScalar(rng() * 0.6 + 0.4)
    return new THREE.Vector3(lobe.c.x + v.x * lobe.r.x * squash,
      lobe.c.y + v.y * lobe.r.y * squash, lobe.c.z + v.z * lobe.r.z * squash)
  }

  private fibreCurve(rng: () => number): THREE.CatmullRomCurve3 {
    const roll = rng()
    let anchors: THREE.Vector3[]
    if (roll < 0.42) {
      const lobe = rng() < 0.5 ? HEMI_L : HEMI_R
      anchors = [0, 1, 2, 3].map(() => this.inLobe(rng, lobe))
    } else if (roll < 0.66) {                                   /* commissure: cross the midline */
      anchors = [this.inLobe(rng, HEMI_L), this.inLobe(rng, LOWER, 0.5),
        this.inLobe(rng, HEMI_R), this.inLobe(rng, rng() < 0.5 ? HEMI_R : LOWER)]
    } else if (roll < 0.88) {                                  /* optic tracts */
      const side = rng() < 0.5
      const optic = side ? OPTIC_L : OPTIC_R
      const hemi = side ? HEMI_L : HEMI_R
      anchors = [this.inLobe(rng, optic), this.inLobe(rng, optic),
        this.inLobe(rng, hemi), this.inLobe(rng, hemi)]
    } else {                                                   /* vertical stalk */
      anchors = [this.inLobe(rng, LOWER), this.inLobe(rng, LOWER),
        this.inLobe(rng, HEMI_L, 0.6), this.inLobe(rng, HEMI_R, 0.6)]
    }
    return new THREE.CatmullRomCurve3(anchors, false, 'catmullrom', 0.6)
  }

  private buildFibres(rng: () => number) {
    const pos: number[] = []
    const col: number[] = []
    const c = new THREE.Color()
    const FIBRES = 1500
    for (let f = 0; f < FIBRES; f++) {
      const curve = this.fibreCurve(rng)
      const pts = curve.getPoints(12)
      c.set(WIRE_PALETTE[Math.floor(rng() * WIRE_PALETTE.length)])
      const shade = 0.72 + rng() * 0.42
      for (let i = 0; i < pts.length - 1; i++) {
        pos.push(pts[i].x, pts[i].y, pts[i].z, pts[i + 1].x, pts[i + 1].y, pts[i + 1].z)
        col.push(c.r * shade, c.g * shade, c.b * shade,
          c.r * shade, c.g * shade, c.b * shade)
      }
      if (f % 14 === 0) {
        this.paths.push(pts)
        this.pathLens.push(cumLengths(pts))
      }
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
    /* plain colour blending — crisp veins, not an additive fog */
    const lines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.95, depthWrite: false
    }))
    this.group.add(lines)
  }

  private buildSomata(rng: () => number) {
    const pos: number[] = []
    const col: number[] = []
    const c = new THREE.Color()
    const lobes = [HEMI_L, HEMI_R, LOWER, OPTIC_L, OPTIC_R]
    for (let cluster = 0; cluster < 34; cluster++) {
      const lobe = lobes[Math.floor(rng() * lobes.length)]
      const centre = this.inLobe(rng, lobe, 0.8)
      c.set(WIRE_PALETTE[8 + Math.floor(rng() * (WIRE_PALETTE.length - 8))])
      const n = 4 + Math.floor(rng() * 7)
      for (let i = 0; i < n; i++) {
        const j = centre.clone().add(new THREE.Vector3(
          (rng() - 0.5) * 0.16, (rng() - 0.5) * 0.16, (rng() - 0.5) * 0.16))
        pos.push(j.x, j.y, j.z)
        const b = 0.55 + rng() * 0.6
        col.push(Math.min(1, c.r * b), Math.min(1, c.g * b), Math.min(1, c.b * b))
      }
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
    const pts = new THREE.Points(g, new THREE.PointsMaterial({
      size: 0.06, vertexColors: true, transparent: true, opacity: 0.8,
      map: radialTexture('#ffffff'), blending: THREE.AdditiveBlending,
      depthWrite: false, sizeAttenuation: true
    }))
    this.group.add(pts)
  }

  /* ------------------------------------------------------- thought packets */
  private buildPulse(): Pulse {
    const pos = new Float32Array(TRAIL_PTS * 3)
    const col = new Float32Array(TRAIL_PTS * 3)
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    g.setAttribute('color', new THREE.BufferAttribute(col, 3))
    const line = new THREE.Line(g, new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0,
      blending: THREE.AdditiveBlending, depthWrite: false
    }))
    line.frustumCulled = false
    line.visible = false
    this.group.add(line)
    const head = new THREE.Sprite(new THREE.SpriteMaterial({
      map: this.headTex, transparent: true, opacity: 0,
      blending: THREE.AdditiveBlending, depthWrite: false
    }))
    head.scale.setScalar(0.4)
    head.visible = false
    this.group.add(head)
    return { line, head, pos, col, path: null, cum: [], dist: THOUGHT_UNITS,
      travelled: 0, trailLen: TRAIL_UNITS, speed: 2.3, color: new THREE.Color('#9ff3ff'),
      strength: 1, phase: 'run', fade: 0, active: false }
  }

  /** one thinking / questioning event → one light packet runs ~3 cm of vein */
  pulse(colorHex?: string, strength = 1) {
    if (this.disposed) return
    let p = this.pulses.find((x) => !x.active)
    if (!p) {                                        /* recycle the oldest */
      p = this.pulses.reduce((a, b) => (a.travelled > b.travelled ? a : b))
    }
    const idx = Math.floor(Math.random() * this.paths.length)
    p.path = this.paths[idx]
    p.cum = this.pathLens[idx]
    p.strength = Math.max(0.55, Math.min(1.5, strength))
    p.dist = THOUGHT_UNITS * (0.85 + 0.3 * (p.strength - 1))
    p.travelled = 0
    p.trailLen = TRAIL_UNITS * Math.min(1, p.strength)
    p.speed = (2.1 + this.energy * 1.1 + this.flash * 1.6) * (0.9 + 0.2 * p.strength)
    p.color.set(colorHex || '#9ff3ff')
    p.phase = 'run'
    p.fade = 0
    p.active = true
    ;(p.line.material as THREE.LineBasicMaterial).opacity = 0
    ;(p.head.material as THREE.SpriteMaterial).opacity = 0
    p.line.visible = true
    p.head.visible = true
    p.head.material.color.copy(p.color)
    this.thoughtCount++
  }

  /* a strike is the loudest thought the fly has — the veins race */
  private burst(n = 3) {
    for (let i = 0; i < n; i++) setTimeout(() => {
      if (!this.disposed) this.pulse('#ffd166', 1.15 + i * 0.1)
    }, i * 90)
  }

  /* arc-length position lookup along the active path */
  private pointAt(p: Pulse, s: number, out: THREE.Vector3) {
    const path = p.path!
    const cum = p.cum
    const total = cum[cum.length - 1]
    const u = Math.max(0, Math.min(total, s))
    let lo = 0, hi = cum.length - 1
    while (lo < hi - 1) { const mid = (lo + hi) >> 1; if (cum[mid] <= u) lo = mid; else hi = mid }
    const seg = cum[hi] - cum[lo] || 1e-6
    const f = (u - cum[lo]) / seg
    const a = path[lo], b = path[hi]
    out.set(a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f, a.z + (b.z - a.z) * f)
    return out
  }

  private tmpA = new THREE.Vector3()

  private step() {
    const dt = Math.min(0.05, this.clock.getDelta())
    this.t += dt
    this.group.rotation.y = Math.sin(this.t * 0.14) * 0.55
    this.group.rotation.x = Math.sin(this.t * 0.09) * 0.08
    this.flash = Math.max(0, this.flash - dt * 1.1)

    for (const p of this.pulses) {
      if (!p.active) continue
      if (p.phase === 'run') {
        p.travelled += dt * p.speed
        if (p.travelled >= p.dist) { p.travelled = p.dist; p.phase = 'fade'; p.fade = 0 }
        /* trail samples the vein behind the head */
        const headS = p.travelled
        const tailS = Math.max(0, headS - p.trailLen)
        for (let i = 0; i < TRAIL_PTS; i++) {
          const s = tailS + (headS - tailS) * (i / (TRAIL_PTS - 1))
          this.pointAt(p, s, this.tmpA)
          p.pos[i * 3] = this.tmpA.x; p.pos[i * 3 + 1] = this.tmpA.y; p.pos[i * 3 + 2] = this.tmpA.z
          const k = Math.pow(i / (TRAIL_PTS - 1), 1.7)        /* dim toward the tail */
          const boost = (0.9 + this.flash * 0.9) * p.strength
          p.col[i * 3] = p.color.r * (0.25 + 0.75 * k) * boost + 0.25 * k * boost
          p.col[i * 3 + 1] = p.color.g * (0.25 + 0.75 * k) * boost + 0.25 * k * boost
          p.col[i * 3 + 2] = p.color.b * (0.25 + 0.75 * k) * boost + 0.45 * k * boost
        }
        ;(p.line.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true
        ;(p.line.geometry.attributes.color as THREE.BufferAttribute).needsUpdate = true
        ;(p.line.material as THREE.LineBasicMaterial).opacity = 0.95
        this.pointAt(p, headS, this.tmpA)
        p.head.position.copy(this.tmpA)
        const hm = p.head.material as THREE.SpriteMaterial
        hm.opacity = 0.95
        p.head.scale.setScalar(0.34 + 0.2 * p.strength + this.flash * 0.3 +
          Math.sin(this.t * 11) * 0.03)
      } else {
        p.fade += dt
        const k = Math.max(0, 1 - p.fade / 0.45)
        ;(p.line.material as THREE.LineBasicMaterial).opacity = 0.95 * k
        ;(p.head.material as THREE.SpriteMaterial).opacity = 0.95 * k
        if (k <= 0) {
          p.active = false
          p.line.visible = false
          p.head.visible = false
        }
      }
    }
    this.renderer.render(this.scene, this.camera)
  }

  /** live fly-brain activity — a strike fires a racing burst of thoughts */
  setActivity(fly: any) {
    const st = fly?.brain?.state || {}
    this.energy = Math.min(1, Math.max(0.12, Math.abs(Number(st.score ?? 0.4))))
    if ((fly?.strike_flash || 0) > 0.25 && this.flash < 0.1) {
      this.flash = Math.max(this.flash, fly.strike_flash)
      this.burst(3)
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
    this.headTex.dispose()
    for (const p of this.pulses) {
      p.line.geometry.dispose()
      ;(p.line.material as THREE.Material).dispose()
      ;(p.head.material as THREE.Material).dispose()
    }
    this.renderer.dispose()
    this.renderer.domElement.remove()
  }
}

function cumLengths(pts: THREE.Vector3[]): number[] {
  const cum = [0]
  for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + pts[i].distanceTo(pts[i - 1]))
  return cum
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
