/**
 * Static world builders: floor, walls, doors, props, signage, skyline.
 * Everything is driven by the server blueprint (`/api/layout`) so the render and
 * the navigation mesh can never disagree about where the building is.
 */
import * as THREE from 'three'
import type { Layout, PropDef, SignDef, WallDef } from './types'

export const M = {
  floor: new THREE.MeshStandardMaterial({ color: 0xf2f4f8, roughness: 0.5, metalness: 0.06 }),
  floorAlt: new THREE.MeshStandardMaterial({ color: 0xe8ecf2, roughness: 0.55, metalness: 0.05 }),
  wall: new THREE.MeshStandardMaterial({ color: 0xf4f6f9, roughness: 0.92, metalness: 0.02 }),
  wallTrim: new THREE.MeshStandardMaterial({ color: 0xdde3ec, roughness: 0.7, metalness: 0.12 }),
  glass: new THREE.MeshPhysicalMaterial({
    color: 0x9fd8ff, roughness: 0.08, metalness: 0, transmission: 0, transparent: true,
    opacity: 0.17, side: THREE.DoubleSide, envMapIntensity: 1.4
  }),
  desk: new THREE.MeshStandardMaterial({ color: 0x2f3a4b, roughness: 0.45, metalness: 0.3 }),
  deskTop: new THREE.MeshStandardMaterial({ color: 0x46536b, roughness: 0.32, metalness: 0.45 }),
  wood: new THREE.MeshStandardMaterial({ color: 0x4a3a2c, roughness: 0.62, metalness: 0.12 }),
  metal: new THREE.MeshStandardMaterial({ color: 0x8d99ad, roughness: 0.28, metalness: 0.85 }),
  dark: new THREE.MeshStandardMaterial({ color: 0x10141b, roughness: 0.6, metalness: 0.3 }),
  chair: new THREE.MeshStandardMaterial({ color: 0x1f2733, roughness: 0.55, metalness: 0.2 }),
  plant: new THREE.MeshStandardMaterial({ color: 0x1f5c3d, roughness: 0.8 }),
  pot: new THREE.MeshStandardMaterial({ color: 0x2c3441, roughness: 0.7 }),
  glassTable: new THREE.MeshPhysicalMaterial({ color: 0xcfe9ff, roughness: 0.05, metalness: 0.1,
    transparent: true, opacity: 0.35 }),
  screen: new THREE.MeshStandardMaterial({ color: 0x05070c, emissive: 0x1d4ed8,
    emissiveIntensity: 0.9, roughness: 0.3, metalness: 0.2 })
}

export function makeTextTexture(lines: { text: string; size?: number; color?: string; weight?: string }[],
                                opts: { w?: number; h?: number; bg?: string; align?: 'left' | 'center' } = {}) {
  const w = opts.w ?? 1024
  const h = opts.h ?? 256
  const c = document.createElement('canvas')
  c.width = w
  c.height = h
  const g = c.getContext('2d')!
  if (opts.bg) {
    g.fillStyle = opts.bg
    g.fillRect(0, 0, w, h)
  }
  const total = lines.length
  lines.forEach((ln, i) => {
    g.fillStyle = ln.color || '#dbeafe'
    g.font = `${ln.weight || '700'} ${ln.size || 96}px "Inter", "Segoe UI", system-ui, sans-serif`
    g.textAlign = opts.align === 'center' ? 'center' : 'left'
    g.textBaseline = 'middle'
    const y = ((i + 0.5) / total) * h
    g.fillText(ln.text, opts.align === 'center' ? w / 2 : 24, y, w - 48)
  })
  const tex = new THREE.CanvasTexture(c)
  tex.anisotropy = 4
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

/** Floor: polished white stone with an inlaid pathway grid. */
function makeFloorTexture(size = 2048): THREE.CanvasTexture {
  const c = document.createElement('canvas')
  c.width = size
  c.height = size
  const g = c.getContext('2d')!
  const grd = g.createLinearGradient(0, 0, size, size)
  grd.addColorStop(0, '#f5f7fa')
  grd.addColorStop(0.5, '#eef1f5')
  grd.addColorStop(1, '#e9edf3')
  g.fillStyle = grd
  g.fillRect(0, 0, size, size)
  // fine mineral grain
  for (let i = 0; i < 9000; i++) {
    const x = Math.random() * size
    const y = Math.random() * size
    g.fillStyle = `rgba(160,175,195,${Math.random() * 0.05})`
    g.fillRect(x, y, 2, 2)
  }
  // panel grid
  g.strokeStyle = 'rgba(110,140,180,0.09)'
  g.lineWidth = 2
  const step = size / 32
  for (let i = 0; i <= 32; i++) {
    g.beginPath()
    g.moveTo(i * step, 0)
    g.lineTo(i * step, size)
    g.stroke()
    g.beginPath()
    g.moveTo(0, i * step)
    g.lineTo(size, i * step)
    g.stroke()
  }
  const tex = new THREE.CanvasTexture(c)
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping
  tex.repeat.set(6, 6)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

export function buildFloor(scene: THREE.Scene, layout: Layout) {
  const { x0, z0, x1, z1 } = layout.hall
  const w = x1 - x0 + 40
  const d = z1 - z0 + 60
  const mat = new THREE.MeshStandardMaterial({ map: makeFloorTexture(), roughness: 0.5,
    metalness: 0.06, color: 0xffffff })
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(w, d), mat)
  floor.rotation.x = -Math.PI / 2
  floor.position.set((x0 + x1) / 2, 0, (z0 + z1) / 2 + 8)
  floor.receiveShadow = true
  floor.name = 'floor'
  scene.add(floor)

  // outer apron (plaza) — slightly lighter concrete
  const apron = new THREE.Mesh(new THREE.PlaneGeometry(w + 30, 40),
    new THREE.MeshStandardMaterial({ color: 0xd9dee6, roughness: 0.92, metalness: 0.03 }))
  apron.rotation.x = -Math.PI / 2
  apron.position.set((x0 + x1) / 2, -0.02, layout.hall.south + 22)
  apron.receiveShadow = true
  scene.add(apron)

  // pathway inlays for every floor zone (the "clean paths" the trades follow)
  for (const z of layout.floor_zones) {
    const [a, b, cc, dd] = z.rect
    const zw = cc - a
    const zd = dd - b
    const isRoom = ['exec', 'vault', 'debate', 'cabin'].includes(z.kind)
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(zw, zd),
      isRoom
        ? new THREE.MeshStandardMaterial({ color: 0xe9eef5, roughness: 0.42, metalness: 0.05 })
        : new THREE.MeshStandardMaterial({ color: 0xe2e8f1, roughness: 0.46, metalness: 0.05 }))
    mesh.rotation.x = -Math.PI / 2
    mesh.position.set(a + zw / 2, 0.012, b + zd / 2)
    mesh.receiveShadow = true
    scene.add(mesh)
  }
  return floor
}

export function buildWalls(scene: THREE.Scene, layout: Layout) {
  const group = new THREE.Group()
  group.name = 'walls'
  for (const w of layout.walls) {
    const dx = w.x1 - w.x0
    const dz = w.z1 - w.z0
    const len = Math.hypot(dx, dz)
    if (len < 0.02) continue
    const thick = Math.min(Math.abs(dx) || 0.36, Math.abs(dz) || 0.36)
    const glassy = w.kind === 'glass'
    const h = w.h
    const geo = new THREE.BoxGeometry(len, h, glassy ? thick : thick)
    const mesh = new THREE.Mesh(geo, glassy ? M.glass : w.kind === 'exterior' ? M.wall : M.wall)
    mesh.position.set((w.x0 + w.x1) / 2, w.y + h / 2, (w.z0 + w.z1) / 2)
    mesh.rotation.y = Math.abs(dx) < Math.abs(dz) ? Math.PI / 2 : 0
    mesh.castShadow = !glassy
    mesh.receiveShadow = true
    group.add(mesh)
    if (!glassy && w.kind !== 'low') {
      // trim band
      const trim = new THREE.Mesh(new THREE.BoxGeometry(len + 0.02, 0.12, thick + 0.06), M.wallTrim)
      trim.position.set(mesh.position.x, w.y + 1.02, mesh.position.z)
      trim.rotation.y = mesh.rotation.y
      group.add(trim)
    }
  }
  scene.add(group)
  return group
}

export function buildDoors(scene: THREE.Scene, layout: Layout, signFont: string) {
  const group = new THREE.Group()
  group.name = 'doors'
  for (const d of layout.doors) {
    const isGate = d.kind === 'entry' || d.kind === 'exit'
    const w = d.width
    const h = isGate ? 4.4 : 3.0
    const alongX = d.axis === 'z'
    const frameMat = isGate
      ? new THREE.MeshStandardMaterial({
          color: d.kind === 'entry' ? 0x0f3d2e : 0x3d1010,
          emissive: d.kind === 'entry' ? 0x10b981 : 0xef4444, emissiveIntensity: 0.5,
          roughness: 0.4, metalness: 0.4 })
      : new THREE.MeshStandardMaterial({ color: 0x2a3442, roughness: 0.5, metalness: 0.4 })

    const post = new THREE.BoxGeometry(0.22, h, 0.22)
    for (const s of [-1, 1]) {
      const m = new THREE.Mesh(post, frameMat)
      m.position.set(d.x + (alongX ? (s * w) / 2 : 0), h / 2, d.z + (alongX ? 0 : (s * w) / 2))
      m.castShadow = true
      group.add(m)
    }
    const lintel = new THREE.Mesh(
      new THREE.BoxGeometry(alongX ? w + 0.3 : 0.22, 0.26, alongX ? 0.22 : w + 0.3), frameMat)
    lintel.position.set(d.x, h, d.z)
    group.add(lintel)

    const labelY = isGate ? 4.9 : 3.25
    const tex = makeTextTexture(
      [
        { text: (d.label || '').toUpperCase(), size: isGate ? 78 : 64, color: '#ffffff' },
        ...(isGate ? [{ text: d.kind === 'entry' ? 'MARKET ENTRY · LIVE' : 'REJECTED · EXIT', size: 44, color: d.kind === 'entry' ? '#6ee7b7' : '#fca5a5' }] : [])
      ],
      { w: 1024, h: isGate ? 256 : 160 })
    const lamp = new THREE.Mesh(new THREE.PlaneGeometry(isGate ? w + 2.4 : w + 0.6, isGate ? 1.1 : 0.5),
      new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false }))
    lamp.position.set(d.x, labelY, d.z + (d.facing === 'south' ? -0.05 : 0.05))
    lamp.rotation.y = d.facing === 'south' ? 0 : Math.PI
    group.add(lamp)
  }
  scene.add(group)
  return group
}

export function buildDesks(scene: THREE.Scene, layout: Layout) {
  const group = new THREE.Group()
  group.name = 'desks'
  const top = new THREE.BoxGeometry(2.3, 0.09, 1.5)
  const apron = new THREE.BoxGeometry(2.3, 0.5, 0.08)
  const leg = new THREE.BoxGeometry(0.09, 0.7, 0.09)
  const monitor = new THREE.BoxGeometry(0.94, 0.56, 0.05)
  const arm = new THREE.BoxGeometry(0.06, 0.34, 0.06)
  const chairSeat = new THREE.BoxGeometry(0.62, 0.1, 0.6)
  const chairBack = new THREE.BoxGeometry(0.62, 0.66, 0.09)
  const chairPost = new THREE.CylinderGeometry(0.05, 0.05, 0.42, 8)

  layout.desks.forEach((d) => {
    const g = new THREE.Group()
    g.position.set(d.x, 0, d.z)
    const t = new THREE.Mesh(top, M.deskTop)
    t.position.y = 0.76
    t.castShadow = true
    t.receiveShadow = true
    g.add(t)
    const a = new THREE.Mesh(apron, M.desk)
    a.position.set(0, 0.55, 0.71)
    g.add(a)
    for (const sx of [-1, 1]) {
      for (const sz of [-1, 1]) {
        const l = new THREE.Mesh(leg, M.metal)
        l.position.set(sx * 1.0, 0.36, sz * 0.64)
        g.add(l)
      }
    }
    // dual monitors
    for (const sx of [-0.55, 0.55]) {
      const m = new THREE.Mesh(monitor, M.screen.clone())
      m.position.set(sx, 1.20, -0.42)
      m.rotation.x = -0.12
      m.name = `screen:${d.id}`
      m.userData.baseColor = new THREE.Color(0x2563eb)
      g.add(m)
      const ar = new THREE.Mesh(arm, M.metal)
      ar.position.set(sx, 0.95, -0.5)
      g.add(ar)
    }
    // keyboard + tablet
    const kb = new THREE.Mesh(new THREE.BoxGeometry(0.78, 0.03, 0.26),
      new THREE.MeshStandardMaterial({ color: 0x11151c, roughness: 0.5 }))
    kb.position.set(0, 0.82, 0.18)
    g.add(kb)
    // chair (behind the desk, in the cross aisle)
    const chair = new THREE.Group()
    chair.position.set(0, 0, -1.05)
    const cs = new THREE.Mesh(chairSeat, M.chair)
    cs.position.y = 0.48
    chair.add(cs)
    const cb = new THREE.Mesh(chairBack, M.chair)
    cb.position.set(0, 0.86, 0.28)
    chair.add(cb)
    const cp = new THREE.Mesh(chairPost, M.metal)
    cp.position.y = 0.24
    chair.add(cp)
    const cf = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.32, 0.06, 10), M.dark)
    cf.position.y = 0.04
    chair.add(cf)
    g.add(chair)
    group.add(g)
  })
  scene.add(group)
  return group
}

function buildProp(p: PropDef): THREE.Object3D | null {
  const g = new THREE.Group()
  g.position.set(p.x, p.y, p.z)
  g.rotation.y = p.rot
  const w = Math.max(0.05, p.w)
  const d = Math.max(0.05, p.d)
  const h = Math.max(0.05, p.h)
  switch (p.kind) {
    case 'pillar': {
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), M.wallTrim)
      m.position.y = h / 2
      m.castShadow = true
      g.add(m)
      const cap = new THREE.Mesh(new THREE.BoxGeometry(w + 0.22, 0.16, d + 0.22), M.metal)
      cap.position.y = h - 0.1
      g.add(cap)
      const base = new THREE.Mesh(new THREE.BoxGeometry(w + 0.26, 0.14, d + 0.26), M.metal)
      base.position.y = 0.07
      g.add(base)
      break
    }
    case 'plant':
    case 'plaza_tree': {
      const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.12, h * 0.45, 6), M.wood)
      trunk.position.y = h * 0.22
      g.add(trunk)
      for (let i = 0; i < 4; i++) {
        const s = 0.36 + Math.random() * 0.22
        const leaf = new THREE.Mesh(new THREE.IcosahedronGeometry(s * h * 0.55, 0), M.plant)
        leaf.position.set((Math.random() - 0.5) * 0.5, h * 0.55 + i * 0.18, (Math.random() - 0.5) * 0.5)
        leaf.castShadow = true
        g.add(leaf)
      }
      const pot = new THREE.Mesh(new THREE.CylinderGeometry(w * 0.32, w * 0.26, 0.34, 10), M.pot)
      pot.position.y = 0.17
      g.add(pot)
      break
    }
    case 'sofa': {
      const base = new THREE.Mesh(new THREE.BoxGeometry(w, 0.4, d), M.chair)
      base.position.y = 0.22
      base.castShadow = true
      g.add(base)
      const back = new THREE.Mesh(new THREE.BoxGeometry(w, 0.5, 0.18), M.chair)
      back.position.set(0, 0.6, -d / 2 + 0.09)
      g.add(back)
      for (const s of [-1, 1]) {
        const armrest = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.26, d), M.chair)
        armrest.position.set(s * (w / 2 - 0.08), 0.5, 0)
        g.add(armrest)
      }
      break
    }
    case 'coffee_table':
    case 'hearing_table':
    case 'side_table':
    case 'round_table':
    case 'exec_table':
    case 'judge_desk':
    case 'security_desk':
    case 'reception':
    case 'witness_stand': {
      const isRound = p.kind === 'round_table'
      const geo = isRound
        ? new THREE.CylinderGeometry(w / 2, w / 2, 0.09, 28)
        : new THREE.BoxGeometry(w, 0.09, d)
      const top = new THREE.Mesh(geo, p.kind === 'exec_table' || p.kind === 'judge_desk' ? M.wood : M.deskTop)
      top.position.y = h
      top.castShadow = true
      top.receiveShadow = true
      g.add(top)
      const skirtGeo = isRound
        ? new THREE.CylinderGeometry(w / 2 - 0.24, w / 2 - 0.3, h, 20)
        : new THREE.BoxGeometry(w - 0.3, h, d - 0.2)
      const skirt = new THREE.Mesh(skirtGeo, M.desk)
      skirt.position.y = h / 2
      g.add(skirt)
      break
    }
    case 'chair': {
      const seat = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.1, 0.58), M.chair)
      seat.position.y = 0.47
      g.add(seat)
      const back = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.62, 0.09), M.chair)
      back.position.set(0, 0.83, 0.26)
      g.add(back)
      const post = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.42, 8), M.metal)
      post.position.y = 0.23
      g.add(post)
      break
    }
    case 'cabinet': {
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), M.dark)
      m.position.y = h / 2
      m.castShadow = true
      g.add(m)
      break
    }
    case 'rack': {
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), M.dark)
      m.position.y = h / 2
      m.castShadow = true
      g.add(m)
      for (let i = 0; i < 7; i++) {
        const led = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 0.03),
          new THREE.MeshBasicMaterial({ color: i % 3 === 0 ? 0x22d3ee : 0x34d399 }))
        led.position.set(0, 0.3 + i * 0.26, d / 2 + 0.01)
        g.add(led)
      }
      break
    }
    case 'water_cooler': {
      const body = new THREE.Mesh(new THREE.CylinderGeometry(0.24, 0.26, 1.05, 12),
        new THREE.MeshStandardMaterial({ color: 0x93c5fd, transparent: true, opacity: 0.6 }))
      body.position.y = 0.52
      g.add(body)
      const base = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.5, 0.5), M.dark)
      base.position.y = 0.25
      g.add(base)
      break
    }
    case 'screen':
    case 'video_wall': {
      const isTicker = !!p.meta?.band || p.meta?.content === 'tape' || p.meta?.content === 'brand'
      const mesh = new THREE.Mesh(
        new THREE.BoxGeometry(w, h, d),
        isTicker
          ? new THREE.MeshBasicMaterial({ color: 0x0b1220 })
          : M.screen.clone())
      mesh.name = `bigscreen:${p.meta?.content || p.kind}:${p.x.toFixed(1)}_${p.z.toFixed(1)}`
      mesh.position.y = d < w ? h / 2 : 0
      mesh.userData.role = p.meta?.content || (p.meta?.wall ? 'wall-screen' : 'screen')
      mesh.userData.size = [w, h, d]
      g.add(mesh)
      break
    }
    case 'light_panel': {
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d),
        new THREE.MeshBasicMaterial({ color: 0xdff3ff, transparent: true, opacity: 0.55 }))
      m.position.y = 0
      g.add(m)
      break
    }
    case 'monitor':
    case 'keyboard':
    case 'mug':
    case 'desk_lamp':
    case 'holo_chart':
      break
    case 'turnstile': {
      const body = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), M.metal)
      body.position.y = h / 2
      body.castShadow = true
      g.add(body)
      const glass = new THREE.Mesh(new THREE.BoxGeometry(w + 0.24, 0.9, d + 0.24), M.glass)
      glass.position.y = h + 0.45
      g.add(glass)
      break
    }
    case 'rope_post': {
      const post = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.05, 1.0, 8), M.metal)
      post.position.y = 0.5
      g.add(post)
      const ball = new THREE.Mesh(new THREE.SphereGeometry(0.06, 10, 8), M.metal)
      ball.position.y = 1.02
      g.add(ball)
      break
    }
    case 'curb': {
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d),
        new THREE.MeshStandardMaterial({ color: 0x39414f, roughness: 0.9 }))
      m.position.y = h / 2
      g.add(m)
      break
    }
    case 'street_lamp': {
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.08, h, 8), M.metal)
      pole.position.y = h / 2
      g.add(pole)
      const head = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.14, 0.3),
        new THREE.MeshBasicMaterial({ color: 0xfef3c7 }))
      head.position.set(0.22, h, 0)
      g.add(head)
      break
    }
    case 'fountain': {
      const basin = new THREE.Mesh(new THREE.CylinderGeometry(w / 2, w / 2 + 0.2, 0.5, 22),
        new THREE.MeshStandardMaterial({ color: 0x2b3444, roughness: 0.85 }))
      basin.position.y = 0.25
      g.add(basin)
      const water = new THREE.Mesh(new THREE.CylinderGeometry(w / 2 - 0.3, w / 2 - 0.3, 0.52, 22),
        new THREE.MeshPhysicalMaterial({ color: 0x38bdf8, roughness: 0.05, transparent: true,
          opacity: 0.55 }))
      water.position.y = 0.3
      g.add(water)
      break
    }
    case 'taxi': {
      const body = new THREE.Mesh(new THREE.BoxGeometry(w, h * 0.7, d), 
        new THREE.MeshStandardMaterial({ color: 0xfbbf24, roughness: 0.4, metalness: 0.5 }))
      body.position.y = h * 0.35 + 0.15
      body.castShadow = true
      g.add(body)
      const cabin = new THREE.Mesh(new THREE.BoxGeometry(w * 0.5, h * 0.42, d * 0.86),
        new THREE.MeshStandardMaterial({ color: 0x111827, roughness: 0.2, metalness: 0.6 }))
      cabin.position.y = h * 0.78
      g.add(cabin)
      for (const sx of [-1, 1]) {
        for (const sz of [-1, 1]) {
          const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.32, 0.32, 0.2, 12), M.dark)
          wheel.rotation.z = Math.PI / 2
          wheel.position.set(sx * w * 0.32, 0.32, sz * d * 0.32)
          g.add(wheel)
        }
      }
      break
    }
    case 'security_desk':
    default:
      break
  }
  return g.children.length ? g : null
}

export function buildProps(scene: THREE.Scene, layout: Layout) {
  const group = new THREE.Group()
  group.name = 'props'
  for (const p of layout.props) {
    const obj = buildProp(p)
    if (obj) group.add(obj)
  }
  scene.add(group)
  return group
}

export function buildSigns(scene: THREE.Scene, layout: Layout) {
  const group = new THREE.Group()
  group.name = 'signs'
  for (const s of layout.signs as SignDef[]) {
    const wide = s.kind === 'wall' || s.kind === 'screen'
    const w = Math.max(1.6, s.width)
    const h = wide ? w * 0.34 : w * 0.26
    const tex = makeTextTexture(
      [
        { text: s.text, size: wide ? 92 : 82, color: '#ffffff' },
        ...(s.sub ? [{ text: s.sub, size: wide ? 52 : 46, color: s.accent }] : [])
      ],
      { w: 1024, h: s.sub ? 300 : 180 })
    const panel = new THREE.Mesh(new THREE.PlaneGeometry(w, h),
      new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false }))
    panel.position.set(s.x, s.y, s.z)
    panel.rotation.y = s.rot || 0
    group.add(panel)
  }
  scene.add(group)
  return group
}

/** Distant skyline so the plaza reads as a real financial district. */
export function buildCity(scene: THREE.Scene) {
  const group = new THREE.Group()
  group.name = 'city'
  const rng = (() => {
    let s = 12345
    return () => (s = (s * 1103515245 + 12345) % 2147483648) / 2147483648
  })()
  const towerMat = new THREE.MeshStandardMaterial({ color: 0x121a26, roughness: 0.75, metalness: 0.3 })
  const winMat = new THREE.MeshBasicMaterial({ color: 0x7dd3fc, transparent: true, opacity: 0.85 })
  for (let i = 0; i < 46; i++) {
    const w = 8 + rng() * 16
    const d = 8 + rng() * 16
    const h = 24 + rng() * 120
    const angle = rng() * Math.PI * 2
    const radius = 120 + rng() * 190
    const x = Math.cos(angle) * radius
    const z = Math.sin(angle) * radius + 30
    const tower = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), towerMat)
    tower.position.set(x, h / 2, z)
    group.add(tower)
    // window bands
    const bandCount = Math.min(16, Math.floor(h / 7))
    for (let b = 0; b < bandCount; b++) {
      const band = new THREE.Mesh(new THREE.BoxGeometry(w * 1.005, 1.1, d * 1.005), winMat)
      band.position.set(x, 6 + b * (h / bandCount), z)
      group.add(band)
    }
  }
  // towers directly behind the north wing (visible over the cabins)
  for (let i = 0; i < 8; i++) {
    const h = 60 + rng() * 110
    const tower = new THREE.Mesh(new THREE.BoxGeometry(14, h, 14), towerMat)
    tower.position.set(-90 + i * 26, h / 2, -120 - rng() * 60)
    group.add(tower)
  }
  scene.add(group)
  return group
}

export function buildSky(scene: THREE.Scene) {
  const geo = new THREE.SphereGeometry(600, 32, 16)
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    uniforms: {
      top: { value: new THREE.Color(0x05070d) },
      bottom: { value: new THREE.Color(0x12202f) },
      glow: { value: new THREE.Color(0x1b3b57) }
    },
    vertexShader: `varying vec3 vP; void main(){ vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0);}`,
    fragmentShader: `uniform vec3 top; uniform vec3 bottom; uniform vec3 glow; varying vec3 vP;
      void main(){
        float h = normalize(vP).y * 0.5 + 0.5;
        vec3 c = mix(bottom, top, smoothstep(0.35, 0.9, h));
        c += glow * pow(max(0.0, 1.0 - abs(h - 0.5) * 2.2), 2.0) * 0.35;
        gl_FragColor = vec4(c, 1.0);
      }`
  })
  const sky = new THREE.Mesh(geo, mat)
  sky.userData.mat = mat
  scene.add(sky)
  return sky
}

/* --------------------------------------------------------------- lighting -- */
/**
 * Ceiling rig for the hall: suspended linear fixtures, pendant spotlights over
 * the pit, LED strips along the aisles and cabin interiors, plus additive
 * "light pool" decals on the floor. The pools and emissive panels are free
 * (no extra dynamic lights), so the hall reads as properly lit without paying
 * the per-light shading cost of a dozen real lamps.
 */
let _glowTex: THREE.Texture | null = null
/** Soft radial gradient used for light pools, halos and lamp glows. */
function radialGlow(color = '#ffffff'): THREE.Texture {
  if (_glowTex) return _glowTex
  const size = 256
  const c = document.createElement('canvas')
  c.width = c.height = size
  const ctx = c.getContext('2d')!
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2)
  g.addColorStop(0, color)
  g.addColorStop(0.35, color)
  g.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = g
  ctx.fillRect(0, 0, size, size)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  _glowTex = tex
  return tex
}

export interface LightingRig {
  group: THREE.Group
  panels: THREE.Mesh[]
  strips: THREE.Mesh[]
  pools: THREE.Mesh[]
  pendants: THREE.Mesh[]
  halos: THREE.Sprite[]
}

export function buildLighting(layout: Layout): LightingRig {
  const group = new THREE.Group()
  group.name = 'lighting'
  const hall = layout.hall
  const panels: THREE.Mesh[] = []
  const strips: THREE.Mesh[] = []
  const pools: THREE.Mesh[] = []
  const pendants: THREE.Mesh[] = []
  const halos: THREE.Sprite[] = []

  const panelMat = new THREE.MeshBasicMaterial({ color: 0xfff6e2 })
  const housingMat = new THREE.MeshStandardMaterial({ color: 0x1a2230, roughness: 0.6,
    metalness: 0.5 })
  const stripMat = new THREE.MeshBasicMaterial({ color: 0x8fd8ff })
  const poolTex = radialGlow('rgba(255,233,194,1)')
  const poolMat = new THREE.MeshBasicMaterial({ map: poolTex, transparent: true, opacity: 0.20,
    blending: THREE.AdditiveBlending, depthWrite: false })
  const coolPoolMat = new THREE.MeshBasicMaterial({ map: poolTex, transparent: true, opacity: 0.16,
    color: 0xbfe4ff, blending: THREE.AdditiveBlending, depthWrite: false })

  // --- suspended linear fixtures over the pit and concourse -----------------
  const rowsZ = [-16.5, -10.0, -3.5, 3.0, 9.5, 16.0, 22.5]
  for (let r = 0; r < rowsZ.length; r++) {
    const z = rowsZ[r]
    const count = 6
    for (let i = 0; i < count; i++) {
      const x = hall.x0 + 6.5 + i * ((hall.x1 - hall.x0 - 13) / (count - 1))
      const y = hall.h - 0.55
      const panel = new THREE.Mesh(new THREE.BoxGeometry(6.2, 0.16, 0.9), panelMat)
      panel.position.set(x, y, z)
      group.add(panel)
      panels.push(panel)
      const housing = new THREE.Mesh(new THREE.BoxGeometry(6.5, 0.26, 1.1), housingMat)
      housing.position.set(x, y + 0.2, z)
      group.add(housing)
      const rod = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.55, 6), housingMat)
      rod.position.set(x, y + 0.5, z)
      group.add(rod)
      // light pool on the floor beneath the fixture
      const pool = new THREE.Mesh(new THREE.PlaneGeometry(9.5, 5.2),
        r % 2 ? poolMat : coolPoolMat)
      pool.rotation.x = -Math.PI / 2
      pool.position.set(x, 0.05, z)
      group.add(pool)
      pools.push(pool)
    }
  }

  // --- LED strips marking every aisle so the pathways read clearly ----------
  const aislesX = [-18.05, -5.35, 7.35]
  for (const x of aislesX) {
    for (const [z0, z1] of [[-8.6, 5.6], [-15.2, -8.9], [6.1, 9.4]]) {
      const strip = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.05, z1 - z0), stripMat)
      strip.position.set(x, 0.035, (z0 + z1) / 2)
      group.add(strip)
      strips.push(strip)
    }
  }
  // cross aisle lines
  for (const z of [-8.75, 5.95]) {
    const strip = new THREE.Mesh(new THREE.BoxGeometry(46, 0.05, 0.14), stripMat)
    strip.position.set(-11, 0.035, z)
    group.add(strip)
    strips.push(strip)
  }

  // --- pendant spotlights over the pit -------------------------------------
  for (let i = 0; i < 5; i++) {
    for (let j = 0; j < 2; j++) {
      const x = -30 + i * 10.5
      const z = j ? 2.6 : -5.4
      const cone = new THREE.Mesh(new THREE.ConeGeometry(0.42, 0.5, 14, 1, true),
        new THREE.MeshStandardMaterial({ color: 0x222c3a, metalness: 0.65, roughness: 0.35,
          side: THREE.DoubleSide }))
      cone.position.set(x, hall.h - 1.5, z)
      cone.rotation.x = Math.PI
      group.add(cone)
      const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.16, 12, 10),
        new THREE.MeshBasicMaterial({ color: 0xfff2d6 }))
      bulb.position.set(x, hall.h - 1.72, z)
      group.add(bulb)
      pendants.push(bulb)
      const halo = new THREE.Sprite(new THREE.SpriteMaterial({
        map: radialGlow('rgba(255,230,184,1)'), transparent: true, opacity: 0.5,
        blending: THREE.AdditiveBlending, depthWrite: false }))
      halo.scale.set(2.6, 2.6, 1)
      halo.position.set(x, hall.h - 1.8, z)
      group.add(halo)
      halos.push(halo)
      const cone_glow = new THREE.Mesh(new THREE.ConeGeometry(2.5, 4.2, 18, 1, true),
        new THREE.MeshBasicMaterial({ color: 0xffe9c7, transparent: true, opacity: 0.05,
          blending: THREE.AdditiveBlending, side: THREE.DoubleSide, depthWrite: false }))
      cone_glow.position.set(x, hall.h - 3.7, z)
      cone_glow.rotation.x = Math.PI
      group.add(cone_glow)
    }
  }

  // --- cabin, executive, vault and debate interiors -------------------------
  for (const room of layout.rooms) {
    if (room.kind === 'hall') continue
    const [x0, z0, x1, z1] = room.rect
    const cx = (x0 + x1) / 2
    const cz = (z0 + z1) / 2
    const warm = room.kind === 'cabin' ? 0xfff0d0 : room.kind === 'debate' ? 0xdcd7ff : 0xfff4e0
    const panel = new THREE.Mesh(new THREE.BoxGeometry(Math.min(6.4, x1 - x0 - 2.2), 0.14,
      Math.min(3.4, z1 - z0 - 2.0)), new THREE.MeshBasicMaterial({ color: warm }))
    panel.position.set(cx, hall.h - 0.8, cz)
    group.add(panel)
    panels.push(panel)
    const pool = new THREE.Mesh(new THREE.PlaneGeometry(Math.min(12, x1 - x0 + 3),
      Math.min(10, z1 - z0 + 4)),
      new THREE.MeshBasicMaterial({ map: radialGlow('rgba(255,233,194,1)'), transparent: true,
        opacity: room.kind === 'cabin' ? 0.16 : 0.13, blending: THREE.AdditiveBlending,
        depthWrite: false }))
    pool.rotation.x = -Math.PI / 2
    pool.position.set(cx, 0.05, cz)
    group.add(pool)
    pools.push(pool)
  }

  // --- corridor wash: even light down the cabin corridor --------------------
  for (let i = 0; i < 7; i++) {
    const x = hall.x0 + 5.5 + i * ((hall.x1 - hall.x0 - 11) / 6)
    const pool = new THREE.Mesh(new THREE.PlaneGeometry(11, 6.4), coolPoolMat)
    pool.rotation.x = -Math.PI / 2
    pool.position.set(x, 0.045, -12.6)
    group.add(pool)
    pools.push(pool)
  }

  return { group, panels, strips, pools, pendants, halos }
}
