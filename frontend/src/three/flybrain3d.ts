/** Drosophila connectome visual — the fly brain as drawn in the atlases.
 *
 * Silhouette of the reference render: translucent central body + two optic
 * lobes, thin multicolour axon fibres (the veins) that stay dark and clearly
 * coloured on black, bright somata clusters.
 *
 * The thinking light: NO constant glow. A short pulse (~3 cm on screen) is
 * launched only when the floor actually thinks — a chatroom message, a cabin
 * verdict, a debate turn, a strike — runs once along a vein and dies. The
 * pace/flair scale with the live fly state via `setActivity`, and each
 * thinking event calls `launchThought()`.
 */
import * as THREE from 'three'

/* atlas palette — distinct hues that stay readable on black */
const WIRE_PALETTE = ['#c9a24a', '#3fa0a8', '#c96fb4', '#8a6fc9', '#6fc98a', '#c9806f',
  '#5f8ac9', '#a8c95f', '#c95f7a', '#5fc9c0', '#b8a23f', '#7e6db0', '#4aa06d', '#c46f9a',
  '#6d9ac4', '#9ac46d', '#c4786d', '#6dc4ae']

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
type Vein = { pts: THREE.Vector3[]; len: number }

const PULSE_LEN = 1.7        /* ~3 cm of light on screen */

export class FlyBrainViz {
  private renderer: THREE.WebGLRenderer
  private scene = new THREE.Scene()
  private camera = new THREE.PerspectiveCamera(38, 1, 0.1, 60)
  private group = new THREE.Group()
  private raf = 0
  private ro?: ResizeObserver
  private clock = new THREE.Clock()
  private disposed = false

  /* the travelling thought */
  private veins: Vein[] = []
  private veinIdx = 0
  private head = -1                     /* distance along the vein; -1 = idle */
  private speed = 1.6
  private trail: THREE.Line
  private trailPos: Float32Array
  private trailCol: Float32Array
  private glow: THREE.Sprite
  private glowFade = 0
  private energy = 0.4
  private lastStrikeLaunch = 0
  private t = 0

  private readonly TRAIL = 30

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
    this.buildVeins(rng)
    this.buildSomata(rng)

    /* pulse trail + glow head (additive — it is the only bright thing) */
    this.trailPos = new Float32Array(this.TRAIL * 3)
    this.trailCol = new Float32Array(this.TRAIL * 3)
    const tg = new THREE.BufferGeometry()
    tg.setAttribute('position', new THREE.BufferAttribute(this.trailPos, 3))
    tg.setAttribute('color', new THREE.BufferAttribute(this.trailCol, 3))
    this.trail = new THREE.Line(tg, new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false
    }))
    this.trail.frustumCulled = false
    this.group.add(this.trail)
    this.glow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: radialTexture('#9ff3ff'), transparent: true, opacity: 0,
      blending: THREE.AdditiveBlending, depthWrite: false
    }))
    this.glow.scale.setScalar(0.4)
    this.group.add(this.glow)

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
  private ellipsoid(lobe: Lobe, opacity: number, color = 0x8fa3bd) {
    const m = new THREE.Mesh(
      new THREE.SphereGeometry(1, 26, 18),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false }))
    m.position.copy(lobe.c)
    m.scale.copy(lobe.r)
    return m
  }

  private buildMembrane() {
    /* whisper-thin ghost shells — the veins must own the picture */
    for (const lobe of [HEMI_L, HEMI_R, LOWER, OPTIC_L, OPTIC_R]) {
      this.group.add(this.ellipsoid(lobe, 0.045))
    }
  }

  private inLobe(rng: () => number, lobe: Lobe, squash = 0.92): THREE.Vector3 {
    const v = new THREE.Vector3(rng() * 2 - 1, rng() * 2 - 1, rng() * 2 - 1)
    if (v.length() > 1) v.normalize().multiplyScalar(rng() * 0.6 + 0.4)
    return new THREE.Vector3(lobe.c.x + v.x * lobe.r.x * squash,
      lobe.c.y + v.y * lobe.r.y * squash, lobe.c.z + v.z * lobe.r.z * squash)
  }

  private veinCurve(rng: () => number): THREE.CatmullRomCurve3 {
    const roll = rng()
    let anchors: THREE.Vector3[]
    if (roll < 0.42) {
      const lobe = rng() < 0.5 ? HEMI_L : HEMI_R
      anchors = [0, 1, 2, 3].map(() => this.inLobe(rng, lobe))
    } else if (roll < 0.66) {                        /* commissure across the midline */
      anchors = [this.inLobe(rng, HEMI_L), this.inLobe(rng, LOWER, 0.5),
        this.inLobe(rng, HEMI_R), this.inLobe(rng, rng() < 0.5 ? HEMI_R : LOWER)]
    } else if (roll < 0.88) {                        /* optic tracts into the lobes */
      const side = rng() < 0.5
      const optic = side ? OPTIC_L : OPTIC_R
      const hemi = side ? HEMI_L : HEMI_R
      anchors = [this.inLobe(rng, optic), this.inLobe(rng, optic),
        this.inLobe(rng, hemi), this.inLobe(rng, hemi)]
    } else {                                         /* ventral stalk */
      anchors = [this.inLobe(rng, LOWER), this.inLobe(rng, LOWER),
        this.inLobe(rng, HEMI_L, 0.6), this.inLobe(rng, HEMI_R, 0.6)]
    }
    return new THREE.CatmullRomCurve3(anchors, false, 'catmullrom', 0.6)
  }

  private buildVeins(rng: () => number) {
    const pos: number[] = []
    const col: number[] = []
    const c = new THREE.Color()
    const FIBRES = 1400
    for (let f = 0; f < FIBRES; f++) {
      const curve = this.veinCurve(rng)
      const pts = curve.getPoints(10)
      if (f % 12 === 0) {
        const spaced = curve.getSpacedPoints(44)
        this.veins.push({ pts: spaced, len: curve.getLength() })
      }
      c.set(WIRE_PALETTE[Math.floor(rng() * WIRE_PALETTE.length)])
      const dim = 0.5 + rng() * 0.5
      for (let i = 0; i < pts.length - 1; i++) {
        pos.push(pts[i].x, pts[i].y, pts[i].z, pts[i + 1].x, pts[i + 1].y, pts[i + 1].z)
        const d = dim * (0.8 + rng() * 0.4)
        col.push(c.r * d, c.g * d, c.b * d, c.r * d, c.g * d, c.b * d)
      }
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
    /* NORMAL blending: veins keep their own colour instead of summing to white */
    const lines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.85,
      blending: THREE.NormalBlending, depthWrite: false
    }))
    this.group.add(lines)
  }

  private buildSomata(rng: () => number) {
    const pos: number[] = []
    const col: number[] = []
    const c = new THREE.Color()
    const lobes = [HEMI_L, HEMI_R, LOWER, OPTIC_L, OPTIC_R]
    for (let cluster = 0; cluster < 30; cluster++) {
      const lobe = lobes[Math.floor(rng() * lobes.length)]
      const centre = this.inLobe(rng, lobe, 0.8)
      c.set(WIRE_PALETTE[2 + Math.floor(rng() * (WIRE_PALETTE.length - 2))])
      const n = 4 + Math.floor(rng() * 6)
      for (let i = 0; i < n; i++) {
        const j = centre.clone().add(new THREE.Vector3(
          (rng() - 0.5) * 0.15, (rng() - 0.5) * 0.15, (rng() - 0.5) * 0.15))
        pos.push(j.x, j.y, j.z)
        const b = 0.7 + rng() * 0.6
        col.push(Math.min(1, c.r * b), Math.min(1, c.g * b), Math.min(1, c.b * b))
      }
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
    const pts = new THREE.Points(g, new THREE.PointsMaterial({
      size: 0.055, vertexColors: true, transparent: true, opacity: 0.85,
      map: radialTexture('#ffffff'), blending: THREE.AdditiveBlending,
      depthWrite: false, sizeAttenuation: true
    }))
    this.group.add(pts)
  }

  /* ---------------------------------------------------------- the thought */
  /** A thinking event on the floor sends one short pulse through a vein. */
  launchThought(intensity = 1) {
    if (!this.veins.length) return
    const end = this.head >= 0 ? this.veins[this.veinIdx].pts[this.veins[this.veinIdx].pts.length - 1] : null
    let best = -1, bestD = 0.8
    for (let tries = 0; tries < 10; tries++) {
      const i = Math.floor(Math.random() * this.veins.length)
      if (i === this.veinIdx) continue
      if (end && this.veins[i].pts[0].distanceTo(end) < bestD) { bestD = this.veins[i].pts[0].distanceTo(end); best = i }
      else if (best < 0) best = i
    }
    this.veinIdx = best >= 0 ? best : Math.floor(Math.random() * this.veins.length)
    this.head = 0
    this.speed = 1.5 + intensity * 0.9 + this.energy * 0.6
    this.glowFade = 1
  }

  private pointAt(vein: Vein, d: number): THREE.Vector3 {
    const pts = vein.pts
    const u = Math.max(0, Math.min(vein.len, d)) / vein.len * (pts.length - 1)
    const i0 = Math.floor(u), f = u - i0
    const a = pts[Math.min(i0, pts.length - 1)]
    const b = pts[Math.min(i0 + 1, pts.length - 1)]
    return new THREE.Vector3(a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f, a.z + (b.z - a.z) * f)
  }

  private step() {
    const dt = Math.min(0.05, this.clock.getDelta())
    this.t += dt
    this.group.rotation.y = Math.sin(this.t * 0.14) * 0.55
    this.group.rotation.x = Math.sin(this.t * 0.09) * 0.08

    const vein = this.veins[this.veinIdx]
    if (this.head >= 0) {
      this.head += dt * this.speed
      if (this.head > vein.len + PULSE_LEN) this.head = -1    /* thought done */
    }
    const spacing = PULSE_LEN / (this.TRAIL - 1)
    for (let i = 0; i < this.TRAIL; i++) {
      const d = this.head - (this.TRAIL - 1 - i) * spacing
      const p = d <= 0 ? vein.pts[0] : this.pointAt(vein, d)
      this.trailPos[i * 3] = p.x
      this.trailPos[i * 3 + 1] = p.y
      this.trailPos[i * 3 + 2] = p.z
      const k = this.head < 0 ? 0 : Math.pow(i / (this.TRAIL - 1), 1.7)
      this.trailCol[i * 3] = 0.45 * k
      this.trailCol[i * 3 + 1] = 0.95 * k
      this.trailCol[i * 3 + 2] = 1.0 * k
    }
    ;(this.trail.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true
    ;(this.trail.geometry.attributes.color as THREE.BufferAttribute).needsUpdate = true

    if (this.head >= 0) {
      this.glow.position.copy(this.pointAt(vein, this.head))
      this.glow.scale.setScalar(0.32 + 0.14 * this.energy)
      this.glowFade = 1
    } else {
      this.glowFade = Math.max(0, this.glowFade - dt * 2.2)
    }
    ;(this.glow.material as THREE.SpriteMaterial).opacity = this.glowFade * 0.9
    this.renderer.render(this.scene, this.camera)
  }

  /** live fly-brain activity — strikes flare a thought through the veins */
  setActivity(fly: any) {
    const st = fly?.brain?.state || {}
    this.energy = Math.min(1, Math.max(0.12, Math.abs(Number(st.score ?? 0.4))))
    const flash = Number(fly?.strike_flash || 0)
    if (flash > 0.25 && this.t - this.lastStrikeLaunch > 1.6) {
      this.lastStrikeLaunch = this.t
      this.launchThought(1.4 + flash)
    }
  }

  private resize() {
    const w = this.host.clientWidth || 320
    const h = this.host.clientHeight || 240
    this.renderer.setSize(w, h)
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
  }

  dispose() {
    this.disposed = true
    cancelAnimationFrame(this.raf)
    this.ro?.disconnect()
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
  grad.addColorStop(0.35, hex + '88')
  grad.addColorStop(1, '#00000000')
  g.fillStyle = grad
  g.fillRect(0, 0, 64, 64)
  return new THREE.CanvasTexture(cv)
}
