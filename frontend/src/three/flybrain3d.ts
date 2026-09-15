/** Drosophila connectome visual — the fly brain as it is drawn in the atlases.
 *
 * Rebuilds the silhouette of the reference render: a translucent central body
 * with two large optic lobes, thousands of thin multicolour axon fibres inside,
 * bright somata clusters, and — the point of it — a single line of light that
 * keeps travelling through the wires, hopping fibre to fibre: the brain
 * visibly thinking / reasoning. Its pace and glow follow the live fly state
 * (score, dopamine, strike flash) pushed in via `setActivity`.
 */
import * as THREE from 'three'

/* muted-wire palette lifted from connectome renders + vivid somata accents */
const WIRE_PALETTE = ['#8a7f5c', '#6d8f8a', '#7f6d8f', '#8f6d7a', '#5c7f8a', '#96876a',
  '#5f8a72', '#8a6d5c', '#6d7a8f', '#7a8f5c', '#3fa0a8', '#c98ab8', '#b8a23f', '#7ec46f',
  '#c46f9a', '#6fc4b8', '#a86fc4', '#c4b06f']

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
  private paths: THREE.Vector3[][] = []
  private pathIdx = 0
  private head = 0
  private trail: THREE.Line
  private trailPos: Float32Array
  private trailCol: Float32Array
  private glow: THREE.Sprite
  private energy = 0.4
  private flash = 0
  private t = 0

  private readonly TRAIL = 26

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

    /* pulse trail + glow head */
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
      map: radialTexture('#9ff3ff'), transparent: true, opacity: 0.95,
      blending: THREE.AdditiveBlending, depthWrite: false
    }))
    this.glow.scale.setScalar(0.55)
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
  private ellipsoid(lobe: Lobe, opacity: number, color = 0x9fb2c8) {
    const m = new THREE.Mesh(
      new THREE.SphereGeometry(1, 28, 20),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false }))
    m.position.copy(lobe.c)
    m.scale.copy(lobe.r)
    return m
  }

  private buildMembrane() {
    for (const lobe of [HEMI_L, HEMI_R, LOWER, OPTIC_L, OPTIC_R]) {
      this.group.add(this.ellipsoid(lobe, 0.05))
      const rim = this.ellipsoid(lobe, 0.035, 0xcfe3ff)
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
      const dim = 0.35 + rng() * 0.5
      for (let i = 0; i < pts.length - 1; i++) {
        pos.push(pts[i].x, pts[i].y, pts[i].z, pts[i + 1].x, pts[i + 1].y, pts[i + 1].z)
        const d = dim * (0.85 + rng() * 0.3)
        col.push(c.r * d, c.g * d, c.b * d, c.r * d, c.g * d, c.b * d)
      }
      if (f % 14 === 0) this.paths.push(pts)      /* candidate thought highways */
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
    const lines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.8,
      blending: THREE.AdditiveBlending, depthWrite: false
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
        const b = 0.8 + rng() * 0.9
        col.push(Math.min(1, c.r * b), Math.min(1, c.g * b), Math.min(1, c.b * b))
      }
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
    const pts = new THREE.Points(g, new THREE.PointsMaterial({
      size: 0.075, vertexColors: true, transparent: true, opacity: 0.95,
      map: radialTexture('#ffffff'), blending: THREE.AdditiveBlending,
      depthWrite: false, sizeAttenuation: true
    }))
    this.group.add(pts)
  }

  /* -------------------------------------------------------------- the thought */
  private pickNextPath(rngFree = Math.random) {
    const end = this.paths[this.pathIdx][this.paths[this.pathIdx].length - 1]
    let best = -1, bestD = 0.9
    for (let tries = 0; tries < 12; tries++) {
      const i = Math.floor(rngFree() * this.paths.length)
      if (i === this.pathIdx) continue
      const d = this.paths[i][0].distanceTo(end)
      if (d < bestD) { bestD = d; best = i }
    }
    this.pathIdx = best >= 0 ? best : Math.floor(rngFree() * this.paths.length)
    this.head = 0
  }

  private step() {
    const dt = Math.min(0.05, this.clock.getDelta())
    this.t += dt
    this.group.rotation.y = Math.sin(this.t * 0.14) * 0.55
    this.group.rotation.x = Math.sin(this.t * 0.09) * 0.08
    this.flash = Math.max(0, this.flash - dt * 1.4)

    const path = this.paths[this.pathIdx]
    const speed = (1.1 + this.energy * 1.5 + this.flash * 2.6)   /* segments per second */
    this.head += dt * speed
    if (this.head >= path.length - 1) this.pickNextPath()
    const h = Math.min(this.head, path.length - 1.001)

    /* trail follows the wire behind the head */
    for (let i = 0; i < this.TRAIL; i++) {
      const u = Math.max(0, h - (this.TRAIL - 1 - i) * 0.32)
      const i0 = Math.floor(u), f = u - i0
      const a = path[Math.min(i0, path.length - 1)]
      const b = path[Math.min(i0 + 1, path.length - 1)]
      this.trailPos[i * 3] = a.x + (b.x - a.x) * f
      this.trailPos[i * 3 + 1] = a.y + (b.y - a.y) * f
      this.trailPos[i * 3 + 2] = a.z + (b.z - a.z) * f
      const k = Math.pow(i / (this.TRAIL - 1), 1.8)               /* fade to the tail */
      const boost = 1 + this.flash * 1.6
      this.trailCol[i * 3] = (0.35 + 0.65 * k) * boost
      this.trailCol[i * 3 + 1] = (0.85 + 0.15 * k) * boost
      this.trailCol[i * 3 + 2] = 1.0 * boost
    }
    ;(this.trail.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true
    ;(this.trail.geometry.attributes.color as THREE.BufferAttribute).needsUpdate = true

    const headV = path[Math.min(Math.floor(h) + 1, path.length - 1)]
    this.glow.position.copy(headV)
    this.glow.scale.setScalar(0.4 + 0.25 * this.energy + this.flash * 0.8 +
      Math.sin(this.t * 9) * 0.05)
    ;(this.glow.material as THREE.SpriteMaterial).opacity = 0.75 + this.flash * 0.25
    this.renderer.render(this.scene, this.camera)
  }

  /** live fly-brain activity — the thought speeds up and flares on strikes */
  setActivity(fly: any) {
    const st = fly?.brain?.state || {}
    this.energy = Math.min(1, Math.max(0.12, Math.abs(Number(st.score ?? 0.4))))
    if ((fly?.strike_flash || 0) > 0.25) this.flash = Math.max(this.flash, fly.strike_flash)
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
  grad.addColorStop(0.35, hex + 'aa')
  grad.addColorStop(1, '#00000000')
  g.fillStyle = grad
  g.fillRect(0, 0, 64, 64)
  const tex = new THREE.CanvasTexture(cv)
  return tex
}
