/**
 * Person — a lightweight articulated human built from primitives.
 * The walk cycle is driven by the `stride` counter the server advances while a
 * body moves, so limbs, gait and speed always agree with the navigation mesh
 * (nobody moonwalks, nobody glides).
 */
import * as THREE from 'three'

export interface PersonOptions {
  accent: string
  suit?: number
  height?: number
  role?: 'trader' | 'judge' | 'ceo' | 'hunter' | 'npc'
}

const SKIN = new THREE.MeshStandardMaterial({ color: 0xc99a72, roughness: 0.72, metalness: 0.05 })
const HAIR = new THREE.MeshStandardMaterial({ color: 0x1b1c22, roughness: 0.85 })
const SHOE = new THREE.MeshStandardMaterial({ color: 0x14171d, roughness: 0.6, metalness: 0.2 })

export class Person {
  group = new THREE.Group()
  private hips = new THREE.Group()
  private torso = new THREE.Group()
  private head = new THREE.Group()
  private legL = new THREE.Group()
  private legR = new THREE.Group()
  private shinL = new THREE.Group()
  private shinR = new THREE.Group()
  private armL = new THREE.Group()
  private armR = new THREE.Group()
  private foreL = new THREE.Group()
  private foreR = new THREE.Group()
  private card: THREE.Group
  private glow: THREE.Sprite
  private tie: THREE.Mesh | null = null
  private nameplate: THREE.Sprite
  private highlight = 0
  private baseY = 0
  private sitting = 0
  public readonly height: number

  constructor(private opts: PersonOptions) {
    const suitColor = opts.suit ?? 0x1f2937
    const suit = new THREE.MeshStandardMaterial({ color: suitColor, roughness: 0.62, metalness: 0.12 })
    const accentMat = new THREE.MeshStandardMaterial({
      color: new THREE.Color(opts.accent), emissive: new THREE.Color(opts.accent),
      emissiveIntensity: 0.35, roughness: 0.5
    })
    const h = opts.height ?? (opts.role === 'ceo' ? 1.86 : 1.74)
    this.height = h
    const s = h / 1.76

    // hips / legs
    this.group.add(this.hips)
    this.hips.position.y = 0.94 * s
    const thigh = new THREE.BoxGeometry(0.15, 0.46 * s, 0.17)
    const shin = new THREE.BoxGeometry(0.13, 0.46 * s, 0.15)
    for (const [leg, shinG, x] of [[this.legL, this.shinL, -0.11], [this.legR, this.shinR, 0.11]] as const) {
      const t = new THREE.Mesh(thigh, suit)
      t.position.y = -0.23 * s
      t.castShadow = true
      leg.add(t)
      shinG.position.y = -0.46 * s
      const sh = new THREE.Mesh(shin, suit)
      sh.position.y = -0.23 * s
      sh.castShadow = true
      shinG.add(sh)
      const shoe = new THREE.Mesh(new THREE.BoxGeometry(0.15, 0.09, 0.27), SHOE)
      shoe.position.set(0, -0.46 * s, 0.05)
      shinG.add(shoe)
      leg.add(shinG)
      leg.position.x = x
      this.hips.add(leg)
    }

    // torso
    this.hips.add(this.torso)
    const chest = new THREE.Mesh(new THREE.BoxGeometry(0.44 * s, 0.6 * s, 0.24 * s), suit)
    chest.position.y = 0.32 * s
    chest.castShadow = true
    this.torso.add(chest)
    const shoulder = new THREE.Mesh(new THREE.BoxGeometry(0.5 * s, 0.16 * s, 0.25 * s), suit)
    shoulder.position.y = 0.58 * s
    this.torso.add(shoulder)
    // shirt collar + accent
    const collar = new THREE.Mesh(new THREE.BoxGeometry(0.2 * s, 0.12 * s, 0.2 * s),
      new THREE.MeshStandardMaterial({ color: 0xe5e7eb, roughness: 0.6 }))
    collar.position.set(0, 0.62 * s, 0.03)
    this.torso.add(collar)
    if (opts.role === 'ceo' || opts.role === 'judge') {
      this.tie = new THREE.Mesh(new THREE.BoxGeometry(0.07 * s, 0.34 * s, 0.02), accentMat)
      this.tie.position.set(0, 0.44 * s, 0.13 * s)
      this.torso.add(this.tie)
    }
    // arms
    for (const [arm, fore, x] of [[this.armL, this.foreL, -0.29], [this.armR, this.foreR, 0.29]] as const) {
      const upper = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.3 * s, 0.13), suit)
      upper.position.y = -0.15 * s
      upper.castShadow = true
      arm.add(upper)
      const lower = new THREE.Mesh(new THREE.BoxGeometry(0.11, 0.3 * s, 0.12), suit)
      lower.position.y = -0.15 * s
      fore.add(lower)
      const hand = new THREE.Mesh(new THREE.SphereGeometry(0.062 * s, 8, 6), SKIN)
      hand.position.y = -0.3 * s
      fore.add(hand)
      fore.position.y = -0.3 * s
      arm.add(fore)
      arm.position.set(x * s, 0.54 * s, 0)
      this.torso.add(arm)
    }

    // head
    this.torso.add(this.head)
    const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.055 * s, 0.06 * s, 0.09 * s, 8), SKIN)
    neck.position.y = 0.68 * s
    this.head.add(neck)
    const skull = new THREE.Mesh(new THREE.BoxGeometry(0.2 * s, 0.24 * s, 0.21 * s), SKIN)
    skull.position.y = 0.82 * s
    skull.castShadow = true
    this.head.add(skull)
    const hair = new THREE.Mesh(new THREE.BoxGeometry(0.215 * s, 0.1 * s, 0.225 * s), HAIR)
    hair.position.y = 0.92 * s
    this.head.add(hair)
    if (opts.role === 'hunter') {
      const headset = new THREE.Mesh(new THREE.TorusGeometry(0.12 * s, 0.018 * s, 6, 14), accentMat)
      headset.rotation.y = Math.PI / 2
      headset.position.y = 0.84 * s
      this.head.add(headset)
    }

    // floating trade token (holo card) carried at chest height
    this.card = new THREE.Group()
    const cardGeo = new THREE.PlaneGeometry(0.44, 0.3)
    const cardTex = this.makeCardTexture('—')
    const cardMat = new THREE.MeshBasicMaterial({ map: cardTex, transparent: true,
      side: THREE.DoubleSide, depthWrite: false })
    const cardMesh = new THREE.Mesh(cardGeo, cardMat)
    this.card.add(cardMesh)
    const frame = new THREE.Mesh(new THREE.EdgesGeometry(cardGeo),
      new THREE.LineBasicMaterial({ color: new THREE.Color(opts.accent) }))
    this.card.add(frame)
    this.card.position.set(0, 1.12 * s, 0.34)
    this.card.visible = false
    this.group.add(this.card)

    // soft glow sprite + selection ring
    const glowTex = radialTexture(opts.accent)
    this.glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color: 0xffffff,
      transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false }))
    this.glow.scale.set(2.4, 2.4, 1)
    this.glow.position.y = 1.0
    this.group.add(this.glow)

    const plateTex = makePlateTexture(opts.accent)
    this.nameplate = new THREE.Sprite(new THREE.SpriteMaterial({ map: plateTex, transparent: true,
      depthWrite: false, depthTest: false, opacity: 0.0 }))
    this.nameplate.scale.set(0.9, 0.225, 1)
    this.nameplate.position.y = h + 0.34
    this.group.add(this.nameplate)
  }

  private makeCardTexture(symbol: string): THREE.CanvasTexture {
    const c = document.createElement('canvas')
    c.width = 256
    c.height = 176
    const g = c.getContext('2d')!
    g.clearRect(0, 0, 256, 176)
    const grd = g.createLinearGradient(0, 0, 256, 176)
    grd.addColorStop(0, 'rgba(8,20,34,0.92)')
    grd.addColorStop(1, 'rgba(6,12,22,0.72)')
    g.fillStyle = grd
    g.fillRect(0, 0, 256, 176)
    g.strokeStyle = this.opts.accent
    g.lineWidth = 4
    g.strokeRect(3, 3, 250, 170)
    g.fillStyle = this.opts.accent
    g.font = '700 30px system-ui, sans-serif'
    g.fillText('TRADE TICKET', 18, 38)
    g.fillStyle = '#ffffff'
    g.font = '800 46px system-ui, sans-serif'
    g.fillText((symbol || '—').slice(0, 12), 18, 96)
    g.fillStyle = 'rgba(255,255,255,0.65)'
    g.font = '600 24px system-ui, sans-serif'
    g.fillText(new Date().toISOString().slice(11, 16) + ' UTC', 18, 138)
    const tex = new THREE.CanvasTexture(c)
    tex.colorSpace = THREE.SRGBColorSpace
    return tex
  }

  setCard(symbol: string, direction: string, visible: boolean) {
    if (!visible) {
      this.card.visible = false
      this.glow.visible = true
      return
    }
    const mesh = this.card.children[0] as THREE.Mesh
    const mat = mesh.material as THREE.MeshBasicMaterial
    const key = `${symbol}|${direction}`
    if ((mat as any)._key !== key) {
      ;(mat as any)._key = key
      mat.map?.dispose()
      mat.map = this.makeCardTexture(symbol)
      mat.needsUpdate = true
    }
    this.card.visible = true
  }

  setHighlight(v: number) {
    this.highlight = v
    const m = this.nameplate.material as THREE.SpriteMaterial
    m.opacity = Math.min(1, 0.55 + v * 0.45)
  }

  setSitting(v: number) {
    this.sitting = v
  }

  /** Advance the animated pose. `stride` comes from the server walker. */
  update(dt: number, stride: number, seated: boolean, moving: boolean) {
    const sit = seated ? 1 : 0
    const walk = moving ? 1 : 0
    const swing = Math.sin(stride) * 0.72 * walk
    const swingB = Math.sin(stride + Math.PI) * 0.72 * walk
    this.legL.rotation.x = sit * -1.35 + swing
    this.legR.rotation.x = sit * -1.35 + swingB
    this.shinL.rotation.x = Math.max(0, -swing) * 0.8 + sit * 1.25
    this.shinR.rotation.x = Math.max(0, -swingB) * 0.8 + sit * 1.25
    this.armL.rotation.x = sit * -0.5 - swing * 0.7
    this.armR.rotation.x = sit * -0.5 - swingB * 0.7
    this.foreL.rotation.x = sit * -0.9 + Math.abs(swing) * 0.25
    this.foreR.rotation.x = sit * -0.9 + Math.abs(swingB) * 0.25
    const bob = moving ? Math.abs(Math.sin(stride)) * 0.035 : 0
    this.hips.position.y = 0.94 * (this.height / 1.76) - sit * 0.42 + bob
    this.torso.rotation.y = moving ? Math.sin(stride) * 0.09 : 0
    this.head.rotation.y = moving ? -Math.sin(stride) * 0.12 : Math.sin(performance.now() * 0.0004) * 0.18
    // carried card floats and slowly turns
    if (this.card.visible) {
      this.card.position.y = (sit > 0.5 ? 0.86 : 1.12) * (this.height / 1.76) +
        Math.sin(performance.now() * 0.003) * 0.02
      this.card.rotation.y = Math.sin(performance.now() * 0.0008) * 0.5 + (sit > 0.5 ? 0.5 : 0)
    }
    const pulse = 0.35 + this.highlight * 0.5
    ;(this.glow.material as THREE.SpriteMaterial).opacity = pulse
    this.glow.scale.setScalar(1.6 + this.highlight * 1.6)
  }

  dispose() {
    this.group.traverse((o) => {
      const m = o as THREE.Mesh
      if (m.geometry) m.geometry.dispose()
      const mat = (m as any).material
      if (Array.isArray(mat)) mat.forEach((x: any) => x.dispose?.())
      else mat?.dispose?.()
    })
  }
}

let radialCache: Record<string, THREE.Texture> = {}
export function radialTexture(color: string): THREE.Texture {
  if (radialCache[color]) return radialCache[color]
  const c = document.createElement('canvas')
  c.width = c.height = 128
  const g = c.getContext('2d')!
  const grd = g.createRadialGradient(64, 64, 2, 64, 64, 62)
  grd.addColorStop(0, hexA(color, 0.55))
  grd.addColorStop(0.45, hexA(color, 0.18))
  grd.addColorStop(1, 'rgba(0,0,0,0)')
  g.fillStyle = grd
  g.fillRect(0, 0, 128, 128)
  const tex = new THREE.CanvasTexture(c)
  radialCache[color] = tex
  return tex
}

function makePlateTexture(color: string): THREE.Texture {
  const c = document.createElement('canvas')
  c.width = 512
  c.height = 128
  const g = c.getContext('2d')!
  g.clearRect(0, 0, 512, 128)
  g.fillStyle = 'rgba(6,12,20,0.0)'
  g.fillRect(0, 0, 512, 128)
  // little tick mark so the sprite has visible geometry
  g.strokeStyle = hexA(color, 0.9)
  g.lineWidth = 6
  g.beginPath()
  g.moveTo(256, 96)
  g.lineTo(256, 126)
  g.stroke()
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

export function hexA(hex: string, alpha: number): string {
  const h = hex.replace('#', '')
  const v = h.length === 3 ? h.split('').map((x) => x + x).join('') : h
  const r = parseInt(v.slice(0, 2), 16)
  const g = parseInt(v.slice(2, 4), 16)
  const b = parseInt(v.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${alpha})`
}
