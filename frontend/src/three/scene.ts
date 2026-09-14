/**
 * FloorScene — the live 3D trading floor.
 *
 * Rendering is decoupled from the simulation: the server streams walker
 * positions at ~12 Hz and this class interpolates them at display refresh, so
 * the floor stays buttery even when the brain is chewing on a hard ticket.
 */
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type { FrameMsg, Layout, MarketRow, StageFrame, TradeFrame, WalkerFrame } from './types'
import { Person, hexA, radialTexture } from './person'
import { buildCity, buildDesks, buildDoors, buildFloor, buildLighting, buildProps,
  buildSigns, buildSky, buildWalls, makeTextTexture } from './world'
import type { LightingRig } from './world'

interface LabelEl {
  el: HTMLDivElement
  subEl: HTMLDivElement
  anchor: THREE.Vector3
  visible: boolean
}

interface WalkerVis {
  person: Person
  target: THREE.Vector3
  yawTarget: number
  last: WalkerFrame
  label: LabelEl | null
  trail: THREE.Line
  trailPts: Float32Array
  trailCount: number
  seated: number
}

export interface SceneOptions {
  onSelect?: (id: string | null) => void
  /** Clicking a judge above a cabin opens that desk's chat on the live ticket. */
  onJudgeClick?: (seatId: string, tradeId: string | null) => void
  quality?: 'high' | 'balanced' | 'performance'
}

const PRESETS: Record<string, { pos: THREE.Vector3; target: THREE.Vector3 }> = {
  overview: { pos: new THREE.Vector3(6, 34, 62), target: new THREE.Vector3(0, 0, 0) },
  pit: { pos: new THREE.Vector3(-12, 13, 20), target: new THREE.Vector3(-16, 0, -3) },
  corridor: { pos: new THREE.Vector3(0, 6.5, -4.5), target: new THREE.Vector3(0, 1.4, -17) },
  cabins: { pos: new THREE.Vector3(0, 10.5, -6.5), target: new THREE.Vector3(0, 0.6, -19) },
  executive: { pos: new THREE.Vector3(24.5, 5.4, 5.5), target: new THREE.Vector3(27.5, 0.5, -6) },
  debate: { pos: new THREE.Vector3(19.5, 6.4, 26.0), target: new THREE.Vector3(25.6, 0.4, 17.2) },
  gates: { pos: new THREE.Vector3(-6, 8.5, 40), target: new THREE.Vector3(-6, 1.2, 24) },
  tape: { pos: new THREE.Vector3(-40, 9, 6), target: new THREE.Vector3(-24, 2.4, -0.4) }
}

export class FloorScene {
  renderer: THREE.WebGLRenderer
  scene = new THREE.Scene()
  camera: THREE.PerspectiveCamera
  controls: OrbitControls
  private clock = new THREE.Clock()
  private walkers = new Map<string, WalkerVis>()
  private seats = new Map<string, Person>()
  private seatLabels = new Map<string, LabelEl>()
  private labelHost: HTMLDivElement
  private labels: LabelEl[] = []
  private pickables: THREE.Object3D[] = []
  private raycaster = new THREE.Raycaster()
  private pointer = new THREE.Vector2()
  private flyGroup = new THREE.Group()
  private flyWings: THREE.Mesh[] = []
  private flyLight: THREE.PointLight
  private flyAnchor = new THREE.Sprite
  private selected: string | null = null
  private follow = true
  private raf = 0
  private fps = 60
  private frames = 0
  private tAcc = 0
  private degraded = false
  private cabinRings: Record<number, THREE.Mesh> = {}
  private cabinSpots: Record<number, THREE.SpotLight> = {}
  private deskScreens = new Map<string, THREE.Mesh[]>()
  private bigScreens: THREE.Mesh[] = []
  private tickerCanvas: HTMLCanvasElement
  private tickerTex: THREE.CanvasTexture
  private tickerDirty = 0
  private markets: MarketRow[] = []
  private lastFly = { x: 0, y: 4.6, z: 10 }
  private flyTarget = new THREE.Vector3(0, 4.6, 10)
  private tmp = new THREE.Vector3()
  private frame: FrameMsg | null = null
  private tradeInfo = new Map<string, TradeFrame>()
  private seatLive = new Map<string, { tradeId: string; text: string }>()
  private seatIdByName = new Map<string, string>()
  private panelEl: HTMLDivElement
  private verdictFlashes: { mesh: THREE.Mesh; life: number; color: THREE.Color }[] = []
  private hubLights: THREE.PointLight[] = []
  private hemi: THREE.HemisphereLight | null = null
  private keyLight: THREE.DirectionalLight | null = null
  private fillLight: THREE.DirectionalLight | null = null
  private rig: LightingRig | null = null
  private lightLevel = 1.0
  private lightingMode: 'bright' | 'moody' = 'bright'
  readonly ready: Promise<void>

  constructor(private container: HTMLElement, private layout: Layout, private opts: SceneOptions = {}) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance',
      alpha: false, stencil: false })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75))
    this.renderer.setSize(container.clientWidth, container.clientHeight)
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping
    this.renderer.toneMappingExposure = 1.06
    this.renderer.outputColorSpace = THREE.SRGBColorSpace
    this.renderer.shadowMap.enabled = true
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap
    container.appendChild(this.renderer.domElement)

    this.labelHost = document.createElement('div')
    this.labelHost.className = 'label-host'
    container.appendChild(this.labelHost)

    this.camera = new THREE.PerspectiveCamera(48, container.clientWidth / container.clientHeight, 0.2, 900)
    this.camera.position.copy(PRESETS.overview.pos)
    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.target.copy(PRESETS.overview.target)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.06
    this.controls.maxPolarAngle = Math.PI * 0.495
    this.controls.minDistance = 3
    this.controls.maxDistance = 190
    this.controls.zoomSpeed = 0.9
    this.controls.panSpeed = 0.8
    this.controls.screenSpacePanning = true

    this.scene.background = new THREE.Color(0x05070d)
    this.scene.fog = new THREE.Fog(0x0a0f18, 90, 340)

    this.setupLights()
    buildSky(this.scene)
    buildCity(this.scene)
    buildFloor(this.scene, layout)
    buildWalls(this.scene, layout)
    buildDoors(this.scene, layout, '')
    const desks = buildDesks(this.scene, layout)
    buildProps(this.scene, layout)
    buildSigns(this.scene, layout)

    // cabin lighting + hearing rings + exec spotlight
    for (let i = 1; i <= 5; i++) {
      const cx = this.layout.nodes[`cabin_${i}_hear`]?.[0] ?? 0
      const ring = new THREE.Mesh(new THREE.RingGeometry(1.5, 1.9, 48),
        new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.0,
          side: THREE.DoubleSide }))
      ring.rotation.x = -Math.PI / 2
      ring.position.set(cx, 0.03, -18.2)
      this.scene.add(ring)
      this.cabinRings[i] = ring
      const spot = new THREE.SpotLight(0x9fd8ff, 24, 16, Math.PI / 5, 0.5, 1.6)
      spot.position.set(cx, 4.6, -21)
      spot.target.position.set(cx, 0, -18.8)
      this.scene.add(spot)
      this.scene.add(spot.target)
      this.cabinSpots[i] = spot
    }

    // desk screen registry
    desks.traverse((o) => {
      if (o.name?.startsWith('screen:')) {
        const id = o.name.split(':')[1]
        if (!this.deskScreens.has(id)) this.deskScreens.set(id, [])
        this.deskScreens.get(id)!.push(o as THREE.Mesh)
        this.pickables.push(o)
      }
    })
    this.scene.traverse((o) => {
      if (o.name?.startsWith('bigscreen:')) this.bigScreens.push(o as THREE.Mesh)
    })

    // welcome sign
    const gate = layout.nodes['entry_gate']
    this.buildGateEffects(gate?.[0] ?? -14, gate?.[1] ?? 26)
    const exitGate = layout.nodes['exit_gate']
    this.buildGateEffects(exitGate?.[0] ?? 7, exitGate?.[1] ?? 26, true)

    // seated LLM avatars (judges + CEO) — filled by setSeats()
    this.buildFly()
    this.tickerCanvas = document.createElement('canvas')
    this.tickerCanvas.width = 1024
    this.tickerCanvas.height = 256
    this.tickerTex = new THREE.CanvasTexture(this.tickerCanvas)
    this.tickerTex.colorSpace = THREE.SRGBColorSpace
    for (const s of this.bigScreens) {
      const mat = s.material as THREE.MeshBasicMaterial
      mat.map = this.tickerTex
      mat.needsUpdate = true
    }

    this.panelEl = document.createElement('div')
    this.panelEl.className = 'scene-hidden'
    container.appendChild(this.panelEl)

    window.addEventListener('resize', this.onResize)
    this.renderer.domElement.addEventListener('pointerdown', this.onPointer)
    this.ready = Promise.resolve()
    this.loop()
  }

  // ------------------------------------------------------------------ lights
  private roomLights: THREE.PointLight[] = []

  private setupLights() {
    const hemi = new THREE.HemisphereLight(0xbcd7ff, 0x243040, 1.15)
    this.hemi = hemi
    this.scene.add(hemi)
    const key = new THREE.DirectionalLight(0xdfeaff, 1.35)
    this.keyLight = key
    key.position.set(38, 46, 26)
    key.castShadow = true
    key.shadow.mapSize.set(2048, 2048)
    const d = 60
    key.shadow.camera.left = -d
    key.shadow.camera.right = d
    key.shadow.camera.top = d
    key.shadow.camera.bottom = -d
    key.shadow.camera.far = 160
    key.shadow.bias = -0.0006
    this.scene.add(key)
    const fill = new THREE.DirectionalLight(0x7aa7ff, 0.4)
    fill.position.set(-30, 22, -20)
    this.fillLight = fill
    this.scene.add(fill)
    // ceiling rig (fixtures, pendants, LED strips, floor light pools)
    this.rig = buildLighting(this.layout)
    this.scene.add(this.rig.group)
    // warm wash for the cabin corridor and each room interior
    const corridor = new THREE.PointLight(0xdcecff, 30, 60, 2)
    corridor.userData.base = 30
    corridor.position.set(0, 7.4, -13.0)
    this.scene.add(corridor)
    this.roomLights.push(corridor)
    for (const room of this.layout.rooms) {
      if (room.kind === 'hall' || room.kind === 'cabin') continue
      const [x0, z0, x1, z1] = room.rect
      const light = new THREE.PointLight(room.kind === 'debate' ? 0xcfc6ff : 0xffe9c9,
        18, 26, 2)
      light.position.set((x0 + x1) / 2, 6.4, (z0 + z1) / 2)
      light.userData.base = 18
      this.scene.add(light)
      this.roomLights.push(light)
    }
    // one lamp per cabin, right over the hearing table
    for (const room of this.layout.rooms) {
      if (room.kind !== 'cabin') continue
      const [x0, z0, x1, z1] = room.rect
      const light = new THREE.PointLight(0xfff0cf, 14, 18, 2)
      light.position.set((x0 + x1) / 2, 5.6, (z0 + z1) / 2 + 1.2)
      light.userData.base = 14
      this.scene.add(light)
      this.roomLights.push(light)
    }
    // ceiling strip lights over the pit
    for (let i = 0; i < 7; i++) {
      const l = new THREE.PointLight(i % 2 ? 0xcfe4ff : 0xffe9c7, 22, 34, 2)
      l.position.set(-30 + i * 10, 8.2, i % 2 ? -1.5 : 5.5)
      this.scene.add(l)
      this.hubLights.push(l)
    }
  }

  /** Bright (working floor) vs moody (cinematic) lighting. */
  setLighting(mode: 'bright' | 'moody') {
    this.lightingMode = mode
    const bright = mode === 'bright'
    this.lightLevel = bright ? 1.0 : 0.62
    if (this.hemi) this.hemi.intensity = bright ? 1.15 : 0.62
    if (this.keyLight) this.keyLight.intensity = bright ? 1.35 : 0.85
    if (this.fillLight) this.fillLight.intensity = bright ? 0.4 : 0.22
    this.renderer.toneMappingExposure = bright ? 1.16 : 1.0
    for (const l of this.hubLights) l.intensity = (bright ? 26 : 17)
    for (const l of this.roomLights) l.intensity = bright ? l.userData.base ?? l.intensity : 0.6 * (l.userData.base ?? l.intensity)
    if (this.rig) {
      const poolOpacity = bright ? 1.0 : 0.6
      for (const m of this.rig.pools) {
        const mat = m.material as THREE.MeshBasicMaterial
        mat.opacity = (mat.map === null ? 0.16 : 0.2) * poolOpacity
      }
      for (const halo of this.rig.halos) {
        (halo.material as THREE.SpriteMaterial).opacity = bright ? 0.5 : 0.34
      }
      for (const p of this.rig.panels) {
        const mat = p.material as THREE.MeshBasicMaterial
        mat.color.setStyle(bright ? '#fff6e2' : '#c9bda6')
      }
      for (const st of this.rig.strips) {
        const mat = st.material as THREE.MeshBasicMaterial
        mat.color.setStyle(bright ? '#8fd8ff' : '#4b8ab5')
      }
    }
  }

  get lighting(): 'bright' | 'moody' {
    return this.lightingMode
  }

  private buildGateEffects(x: number, z: number, isExit = false) {
    const color = isExit ? 0xef4444 : 0x10b981
    const beam = new THREE.Mesh(new THREE.PlaneGeometry(3.0, 8),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.08,
        blending: THREE.AdditiveBlending, side: THREE.DoubleSide, depthWrite: false }))
    beam.position.set(x, 4, z)
    this.scene.add(beam)
    const glow = new THREE.PointLight(color, isExit ? 12 : 16, 18, 2)
    glow.position.set(x, 3.2, z - 1.5)
    this.scene.add(glow)
    const tex = makeTextTexture([{ text: isExit ? 'EXIT' : 'WELCOME', size: 120, color: '#ffffff' }],
      { w: 512, h: 256 })
    const label = new THREE.Mesh(new THREE.PlaneGeometry(3.4, 1.7),
      new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false }))
    label.position.set(x, 5.6, z + (isExit ? 0.1 : 0.1))
    this.scene.add(label)
  }

  private buildFly() {
    const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.06, 0.16, 4, 8),
      new THREE.MeshStandardMaterial({ color: 0x0f172a, emissive: 0x34d399, emissiveIntensity: 1.4,
        roughness: 0.4 }))
    body.rotation.z = Math.PI / 2
    this.flyGroup.add(body)
    for (const s of [-1, 1]) {
      const wing = new THREE.Mesh(new THREE.PlaneGeometry(0.26, 0.12),
        new THREE.MeshBasicMaterial({ color: 0xa7f3d0, transparent: true, opacity: 0.55,
          side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false }))
      wing.position.set(0, 0.02, s * 0.07)
      this.flyGroup.add(wing)
      this.flyWings.push(wing)
    }
    this.flyLight = new THREE.PointLight(0x34d399, 6, 8, 2)
    this.flyGroup.add(this.flyLight)
    this.flyAnchor = new THREE.Sprite(new THREE.SpriteMaterial({ map: radialTexture('#34d399'),
      color: 0xffffff, transparent: true, opacity: 0.75, blending: THREE.AdditiveBlending,
      depthWrite: false }))
    this.flyAnchor.scale.set(1.6, 1.6, 1)
    this.flyGroup.add(this.flyAnchor)
    this.flyGroup.position.set(0, 4.6, 10)
    this.scene.add(this.flyGroup)
  }

  // ------------------------------------------------------------ LLM avatars
  setSeats(seats: any[]) {
    for (const seat of seats) {
      if (seat?.name && seat?.id) this.seatIdByName.set(seat.name, seat.id)
      if (seat.cabin == null) {
        if (seat.id !== 'ceo') continue
      }
      if (seat.id === 'ceo') {
        if (this.seats.has('ceo')) continue
        const p = new Person({ accent: seat.accent || '#c084fc', suit: 0x121722, role: 'ceo',
          height: 1.88 })
        const node = this.layout.nodes['exec_ceo'] || [25.8, -6.5]
        p.group.position.set(node[0] + 1.6, 0, node[1])
        p.group.rotation.y = Math.PI
        p.setSitting(1)
        p.setHighlight(0.25)
        this.scene.add(p.group)
        this.seats.set('ceo', p)
        const ceoLabel = this.addLabel(`CEO · ${seat.name}`,
          seat.open_source_family || seat.model, seat.accent,
          p.group.position.clone().setY(2.4), 'judge')
        this.seatLabels.set(seat.id, ceoLabel)
        this.bindSeatClick(ceoLabel, seat.id)
        continue
      }
      if (seat.cabin == null) continue
      const node = this.layout.nodes[`cabin_${seat.cabin}_judge`] || [0, -22.5]
      const p = new Person({ accent: seat.accent || '#38bdf8', suit: 0x1b2230, role: 'judge' })
      p.group.position.set(node[0] + 0.34, 0, node[1] + 0.2)
      p.group.rotation.y = Math.PI
      p.setSitting(1)
      p.setHighlight(0.2)
      this.scene.add(p.group)
      this.seats.set(seat.id, p)
      const label = this.addLabel(`${seat.name} · CABIN ${String(seat.cabin).padStart(2, '0')}`,
        `${seat.specialty} · ${seat.open_source_family || seat.model}`, seat.accent,
        p.group.position.clone().setY(2.3), 'judge')
      this.seatLabels.set(seat.id, label)
      this.bindSeatClick(label, seat.id)
    }
  }

  // ------------------------------------------------------------------ labels
  /** Judge plates are interactive: they carry the live verdict and open the chat. */
  private bindSeatClick(label: LabelEl, seatId: string) {
    if (!this.opts.onJudgeClick) return
    label.el.classList.add('plate-clickable')
    label.el.style.pointerEvents = 'auto'
    label.el.addEventListener('click', (ev) => {
      ev.stopPropagation()
      this.opts.onJudgeClick?.(seatId, this.seatTradeId(seatId))
    })
  }

  /** Which ticket is in front of this desk right now (by stage history). */
  private seatTradeId(seatId: string): string | null {
    const info = this.seatLive.get(seatId)
    return info?.tradeId ?? null
  }

  /** Update judge plates with the ticket under hearing and its verdict. */
  private updateSeatPlates() {
    const f = this.frame
    if (!f) return
    const live = new Map<string, { tradeId: string; text: string }>()
    for (const t of f.trades) {
      if (t.state === 'exited' || t.outcome !== 'pending') continue
      const stages = (t.stages || []) as StageFrame[]
      for (const st of stages) {
        const seatId = this.seatIdByName.get(st.judge_name) || ''
        if (!seatId) continue
        if (st.verdict) {
          live.set(seatId, {
            tradeId: t.id,
            text: `${t.symbol} ${t.direction} → ${String(st.verdict).toUpperCase()} ` +
                  `${Math.round((st.confidence || 0) * 100)}%`,
          })
        } else if (st.state === 'hearing' && !live.has(seatId)) {
          live.set(seatId, { tradeId: t.id, text: `${t.symbol} ${t.direction} — hearing…` })
        } else if (!live.has(seatId)) {
          live.set(seatId, { tradeId: t.id, text: `${t.symbol} ${t.direction} — queued` })
        }
      }
    }
    this.seatLive = live
    for (const [seatId, label] of this.seatLabels) {
      if (label.el.dataset.base === undefined) label.el.dataset.base = label.subEl.textContent || ''
      const info = live.get(seatId)
      label.subEl.textContent = info ? info.text : (label.el.dataset.base || '')
      label.el.classList.toggle('plate-live', !!info)
    }
  }

  private addLabel(text: string, sub: string, accent: string, anchor: THREE.Vector3,
                   kind: 'walker' | 'judge' | 'fly' = 'walker', id?: string): LabelEl {
    const el = document.createElement('div')
    el.className = `plate plate-${kind}`
    el.style.setProperty('--accent', accent)
    el.innerHTML = `<span class="plate-title">${text}</span>` +
      (sub ? `<span class="plate-sub">${sub}</span>` : '')
    if (id) {
      el.style.pointerEvents = 'auto'
      el.addEventListener('click', (ev) => {
        ev.stopPropagation()
        this.opts.onSelect?.(id)
      })
    }
    this.labelHost.appendChild(el)
    const subEl = el.querySelector('.plate-sub') as HTMLDivElement
    const item: LabelEl = { el, subEl: subEl || document.createElement('div'),
                            anchor: anchor.clone(), visible: true }
    this.labels.push(item)
    return item
  }

  // ------------------------------------------------------------- frame data
  setFrame(frame: FrameMsg) {
    this.frame = frame
    this.markets = frame.markets || []
    this.tickerDirty = 1
    for (const t of frame.trades) this.tradeInfo.set(t.id, t)
    this.syncWalkers(frame)
    // fly
    if (frame.fly) {
      const p = frame.fly.pos
      this.flyTarget.set(p.x, Math.max(1.4, p.y), p.z)
      this.lastFly = p
      const flash = frame.fly.strike_flash || 0
      this.flyLight.intensity = 4 + flash * 22
      this.flyAnchor.scale.setScalar(1.2 + flash * 1.4)
      ;(this.flyAnchor.material as THREE.SpriteMaterial).opacity = 0.4 + flash * 0.5
    }
    this.updateCabinState(frame)
  }

  private syncWalkers(frame: FrameMsg) {
    const seen = new Set<string>()
    for (const w of frame.walkers) {
      seen.add(w.id)
      let vis = this.walkers.get(w.id)
      if (!vis) {
        const isTrade = w.kind === 'trade'
        const person = new Person({
          accent: w.accent || '#facc15',
          suit: isTrade ? 0x2a2f3d : 0x232b38,
          role: isTrade ? 'trader' : 'npc',
          height: isTrade ? 1.76 : 1.72
        })
        person.group.position.set(w.x, 0, w.z)
        this.scene.add(person.group)
        const trailGeo = new THREE.BufferGeometry()
        const arr = new Float32Array(28 * 3)
        trailGeo.setAttribute('position', new THREE.BufferAttribute(arr, 3))
        trailGeo.setDrawRange(0, 0)
        const trail = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({
          color: new THREE.Color(w.accent || '#facc15'), transparent: true, opacity: 0.32 }))
        this.scene.add(trail)
        const label = this.addLabel(w.label, w.sub, w.accent, person.group.position.clone().setY(2.2),
          'walker', w.trade_id || undefined)
        vis = { person, target: new THREE.Vector3(w.x, 0, w.z), yawTarget: w.yaw, last: w,
          label, trail, trailPts: arr, trailCount: 0, seated: w.seated ? 1 : 0 }
        this.walkers.set(w.id, vis)
      }
      vis.last = w
      vis.target.set(w.x, w.seated ? 0.0 : 0, w.z)
      vis.yawTarget = w.yaw
      if (vis.label) {
        vis.label.anchor.set(w.x, (vis.person.height ?? 1.76) + 0.42, w.z)
        vis.label.el.classList.toggle('plate-selected', w.trade_id === this.selected)
        const titleEl = vis.label.el.querySelector('.plate-title')!
        if (titleEl.textContent !== w.label) titleEl.textContent = w.label
        const subEl = vis.label.el.querySelector('.plate-sub')
        if (subEl && subEl.textContent !== w.sub) subEl.textContent = w.sub
      }
      // trail
      const trail = w.trail || []
      const count = Math.min(trail.length, 28)
      for (let i = 0; i < count; i++) {
        this.trailPoints(vis, i, trail[trail.length - count + i])
      }
      ;(vis.trail.geometry as THREE.BufferGeometry).setDrawRange(0, count)
      ;(vis.trail.geometry as THREE.BufferGeometry).attributes.position.needsUpdate = true
    }
    for (const [id, vis] of this.walkers) {
      if (!seen.has(id)) {
        this.scene.remove(vis.person.group)
        this.scene.remove(vis.trail)
        vis.person.dispose()
        if (vis.label) {
          vis.label.el.remove()
          this.labels = this.labels.filter((l) => l !== vis.label)
        }
        this.walkers.delete(id)
      }
    }
  }

  private trailPoints(vis: WalkerVis, i: number, p: [number, number]) {
    vis.trailPts[i * 3] = p[0]
    vis.trailPts[i * 3 + 1] = 0.06
    vis.trailPts[i * 3 + 2] = p[1]
  }

  private updateCabinState(frame: FrameMsg) {
    const active: Record<number, { state: string; verdict?: string | null }> = {}
    for (const t of frame.trades) {
      if (t.state === 'in_cabin' || t.state === 'walking_to_cabin') {
        const stage = [...t.stages].reverse().find((s) => s.kind === 'cabin' && s.state !== 'voted')
        if (stage?.cabin_index) active[stage.cabin_index] = { state: t.state, verdict: stage.verdict }
      }
      if (t.state === 'in_executive' || t.state === 'to_executive') {
        active[0] = { state: t.state }
      }
    }
    for (let i = 1; i <= 5; i++) {
      const ring = this.cabinRings[i]
      const spot = this.cabinSpots[i]
      const a = active[i]
      const targetOpacity = a ? (a.state === 'in_cabin' ? 0.75 : 0.3) : 0.0
      const mat = ring.material as THREE.MeshBasicMaterial
      mat.opacity += (targetOpacity - mat.opacity) * 0.12
      mat.color.set(a?.state === 'in_cabin' ? 0x38bdf8 : 0xfacc15)
      spot.intensity = a ? (a.state === 'in_cabin' ? 46 : 26) : 12
    }
  }

  private flashVerdict(cabin: number, verdict: string) {
    const color = verdict === 'approve' ? 0x22c55e : verdict === 'reject' ? 0xef4444 : 0xf59e0b
    const cx = this.layout.nodes[`cabin_${cabin}_hear`]?.[0] ?? 0
    const mesh = new THREE.Mesh(new THREE.RingGeometry(1.0, 3.2, 40),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.65,
        side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false }))
    mesh.rotation.x = -Math.PI / 2
    mesh.position.set(cx, 0.05, -18.2)
    this.scene.add(mesh)
    this.verdictFlashes.push({ mesh, life: 1.0, color: new THREE.Color(color) })
  }

  handleEvent(ev: any) {
    if (ev.kind === 'verdict' && ev.cabin) this.flashVerdict(ev.cabin, ev.verdict || 'abstain')
    if (ev.kind === 'exec_ruling') this.flashVerdict(3, ev.verdict || 'reject')
  }

  // ------------------------------------------------------------------ camera
  setPreset(name: string) {
    const p = PRESETS[name] || PRESETS.overview
    this.camera.position.copy(p.pos)
    this.controls.target.copy(p.target)
    this.follow = false
    this.controls.update()
  }

  select(id: string | null, flyTo = false) {
    this.selected = id
    for (const vis of this.walkers.values()) {
      const isSel = !!id && vis.last.trade_id === id
      vis.person.setHighlight(isSel ? 1 : 0)
    }
    if (id && flyTo) {
      const vis = [...this.walkers.values()].find((v) => v.last.trade_id === id)
      if (vis) {
        const p = vis.person.group.position
        this.controls.target.lerp(new THREE.Vector3(p.x, 1.2, p.z), 0.9)
        const dir = new THREE.Vector3().subVectors(this.camera.position, this.controls.target)
          .setLength(11)
        dir.y = 6.5
        this.camera.position.copy(this.controls.target.clone().add(dir))
        this.follow = true
      }
    }
  }

  setFollow(v: boolean) {
    this.follow = v
  }

  // ------------------------------------------------------------------ events
  private onResize = () => {
    const w = this.container.clientWidth
    const h = this.container.clientHeight
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
    this.renderer.setSize(w, h)
  }

  private onPointer = (ev: PointerEvent) => {
    const rect = this.renderer.domElement.getBoundingClientRect()
    this.pointer.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1
    this.pointer.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1
    this.raycaster.setFromCamera(this.pointer, this.camera)
    const bodies: THREE.Object3D[] = []
    for (const vis of this.walkers.values()) bodies.push(vis.person.group)
    const hits = this.raycaster.intersectObjects(bodies, true)
    if (hits.length) {
      let obj: THREE.Object3D | null = hits[0].object
      while (obj && !obj.userData.walkerId) {
        const entry = [...this.walkers.entries()].find(([, v]) => v.person.group === obj)
        if (entry) {
          obj.userData.walkerId = entry[1].last.trade_id
          break
        }
        obj = obj.parent
      }
      const found = [...this.walkers.entries()].find(([, v]) => v.person.group === hits[0].object.parent ||
        v.person.group === hits[0].object)
      const tradeId = found?.[1].last.trade_id
      if (tradeId) {
        this.opts.onSelect?.(tradeId)
        return
      }
    }
    this.opts.onSelect?.(null)
  }

  // ------------------------------------------------------------------- ticker
  private drawTicker() {
    if (!this.tickerDirty) return
    this.tickerDirty = 0
    const g = this.tickerCanvas.getContext('2d')!
    const { width: W, height: H } = this.tickerCanvas
    g.fillStyle = 'rgba(5,9,16,0.94)'
    g.fillRect(0, 0, W, H)
    g.fillStyle = 'rgba(56,189,248,0.12)'
    g.fillRect(0, 0, W, 34)
    g.fillStyle = '#7dd3fc'
    g.font = '700 22px system-ui, sans-serif'
    g.fillText('SOUL EXTER · LIVE MARKET TAPE', 14, 24)
    const rows = this.markets.slice(0, 8)
    rows.forEach((m, i) => {
      const y = 58 + i * 24
      const up = m.change_pct >= 0
      g.fillStyle = '#e2e8f0'
      g.font = '600 20px ui-monospace, monospace'
      g.fillText(`${m.symbol.padEnd(11, ' ')}`, 14, y)
      g.fillText(`${m.price.toFixed(m.price > 100 ? 1 : 4)}`, 190, y)
      g.fillStyle = up ? '#34d399' : '#f87171'
      g.fillText(`${up ? '▲' : '▼'} ${m.change_pct.toFixed(2)}%`, 320, y)
      g.fillStyle = 'rgba(148,163,184,0.85)'
      g.font = '500 16px system-ui, sans-serif'
      g.fillText(m.asset_class.toUpperCase(), 470, y)
      // sparkline
      const spark = m.spark?.slice(-32) || []
      if (spark.length > 2) {
        const min = Math.min(...spark)
        const max = Math.max(...spark)
        g.strokeStyle = up ? 'rgba(52,211,153,0.9)' : 'rgba(248,113,113,0.9)'
        g.lineWidth = 2
        g.beginPath()
        spark.forEach((v, k) => {
          const x = 560 + (k / (spark.length - 1)) * 200
          const yy = y + 6 - ((v - min) / Math.max(1e-9, max - min)) * 22
          k === 0 ? g.moveTo(x, yy) : g.lineTo(x, yy)
        })
        g.stroke()
      }
      g.fillStyle = 'rgba(148,163,184,0.6)'
      g.font = '500 15px system-ui, sans-serif'
      g.fillText(`tick ${m.tick_rate?.toFixed?.(1) ?? '-'}/s`, 780, y)
    })
    g.fillStyle = 'rgba(148,163,184,0.5)'
    g.font = '600 15px system-ui, sans-serif'
    g.fillText(new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC', 780, 24)
    this.tickerTex.needsUpdate = true
  }

  // -------------------------------------------------------------------- loop
  private loop = () => {
    this.raf = requestAnimationFrame(this.loop)
    const dt = Math.min(0.05, this.clock.getDelta())
    this.frames++
    this.tAcc += dt
    if (this.tAcc > 1) {
      this.fps = this.frames / this.tAcc
      this.frames = 0
      this.tAcc = 0
      this.autoQuality()
    }

    // walkers: interpolate toward the latest authoritative pose
    for (const vis of this.walkers.values()) {
      const p = vis.person.group.position
      const k = 1 - Math.pow(0.0015, dt)          // frame-rate independent smoothing
      p.x += (vis.target.x - p.x) * k
      p.z += (vis.target.z - p.z) * k
      let diff = (vis.yawTarget - vis.person.group.rotation.y + Math.PI) % (Math.PI * 2) - Math.PI
      vis.person.group.rotation.y += diff * k
      const moving = Math.hypot(vis.target.x - p.x, vis.target.z - p.z) > 0.035
      const seatTarget = vis.last.seated ? 1 : 0
      vis.seated += (seatTarget - vis.seated) * Math.min(1, dt * 6)
      vis.person.setSitting(vis.seated)
      vis.person.setCard(tradeSymbol(this.tradeInfo, vis.last.trade_id),
        tradeDirection(this.tradeInfo, vis.last.trade_id), !!vis.last.trade_id && vis.last.carrying)
      vis.person.update(dt, vis.last.stride, vis.seated > 0.5, moving)
    }

    // fly
    this.flyGroup.position.lerp(this.flyTarget, Math.min(1, dt * 3.4))
    this.flyGroup.rotation.y += dt * 0.6
    const flap = performance.now() * 0.05
    this.flyWings.forEach((w, i) => {
      w.rotation.z = Math.sin(flap + i * Math.PI) * 0.9
      w.rotation.x = Math.sin(flap * 0.7 + i * Math.PI) * 0.3
    })

    // verdict flashes
    for (let i = this.verdictFlashes.length - 1; i >= 0; i--) {
      const f = this.verdictFlashes[i]
      f.life -= dt * 0.6
      const mat = f.mesh.material as THREE.MeshBasicMaterial
      mat.opacity = Math.max(0, f.life * 0.7)
      f.mesh.scale.setScalar(1 + (1 - f.life) * 1.4)
      if (f.life <= 0) {
        this.scene.remove(f.mesh)
        f.mesh.geometry.dispose()
        mat.dispose()
        this.verdictFlashes.splice(i, 1)
      }
    }

    // desk screens react to the market + seated trades
    if (this.markets.length) {
      const pulse = 0.6 + Math.sin(performance.now() * 0.002) * 0.15
      this.deskScreens.forEach((meshes, deskId) => {
        const trade = [...this.tradeInfo.values()].find((t) => t.desk_id === deskId &&
          t.state !== 'exited')
        const row = trade ? this.markets.find((m) => m.symbol === trade.symbol) : undefined
        meshes.forEach((m) => {
          const mat = m.material as THREE.MeshStandardMaterial
          if (row) {
            const c = new THREE.Color(row.change_pct >= 0 ? 0x22c55e : 0xef4444)
            mat.emissive.copy(c)
            mat.emissiveIntensity = 1.5 * pulse
          } else {
            mat.emissive.setHex(0x1d4ed8)
            mat.emissiveIntensity = 0.55 * pulse
          }
        })
      })
    }

    // ceiling lights gently breathe
    const t = performance.now() * 0.0005
    this.hubLights.forEach((l, i) => { l.intensity = 18 + Math.sin(t + i) * 3 })

    // follow camera
    if (this.follow && this.selected) {
      const vis = [...this.walkers.values()].find((v) => v.last.trade_id === this.selected)
      if (vis) {
        const p = vis.person.group.position
        this.tmp.set(p.x, 1.1, p.z)
        this.controls.target.lerp(this.tmp, Math.min(1, dt * 1.8))
      }
    }

    this.controls.update()
    this.drawTicker()
    this.updateSeatPlates()
    this.updateLabels()
    this.renderer.render(this.scene, this.camera)
  }

  private updateLabels() {
    const w = this.container.clientWidth
    const h = this.container.clientHeight
    const camPos = this.camera.position
    for (const l of this.labels) {
      const v = l.anchor.clone().project(this.camera)
      const dist = camPos.distanceTo(l.anchor)
      const visible = v.z < 1 && dist < 78
      const x = (v.x * 0.5 + 0.5) * w
      const y = (-v.y * 0.5 + 0.5) * h
      const el = l.el
      if (!visible) {
        if (el.style.display !== 'none') el.style.display = 'none'
        continue
      }
      if (el.style.display !== 'block') el.style.display = 'block'
      const scale = Math.max(0.72, Math.min(1.12, 26 / Math.max(6, dist)))
      el.style.transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, -100%) scale(${scale})`
      el.style.opacity = String(Math.max(0.15, Math.min(1, 1.25 - dist / 78)))
      el.style.zIndex = String(Math.max(1, 1000 - Math.round(dist)))
    }
  }

  private autoQuality() {
    if (this.degraded) return
    if (this.fps < 38) {
      this.degraded = true
      this.renderer.setPixelRatio(1)
      this.renderer.shadowMap.enabled = false
      this.scene.traverse((o) => { (o as any).castShadow = false })
      this.scene.fog = new THREE.Fog(0x0a0f18, 70, 220)
      // trim the dynamic-light bill: emissive panels and floor pools still carry
      // the look, so the hall stays lit without paying for 16 real lamps
      this.hubLights.forEach((l, i) => { l.visible = i % 2 === 0 })
      for (const l of this.roomLights) l.visible = false
      for (const key of Object.keys(this.cabinSpots)) {
        const spot = this.cabinSpots[Number(key)]
        if (spot) spot.visible = false
      }
      console.info('[soul-exter] quality auto-degraded for smoothness', this.fps.toFixed(1), 'fps')
    }
  }

  get fpsValue() {
    return this.fps
  }

  dispose() {
    cancelAnimationFrame(this.raf)
    window.removeEventListener('resize', this.onResize)
    this.renderer.domElement.removeEventListener('pointerdown', this.onPointer)
    this.labelHost.remove()
    this.controls.dispose()
    this.renderer.dispose()
    this.walkers.forEach((v) => v.person.dispose())
    this.walkers.clear()
  }
}

function tradeSymbol(map: Map<string, TradeFrame>, id: string | null): string {
  if (!id) return '—'
  return map.get(id)?.symbol || '—'
}
function tradeDirection(map: Map<string, TradeFrame>, id: string | null): string {
  if (!id) return ''
  return (map.get(id)?.direction || '').toUpperCase()
}

export { hexA }
