/** The thought bus — every "a desk is thinking / questioning" moment on the floor
 * is published here, and the fly-brain connectome subscribes so a light packet
 * runs down the veins for each one. Decoupled on purpose: panels and sockets
 * publish, the 3D brain listens, nobody imports anybody.
 */
export interface Thought {
  /** desk accent colour — the light takes the thinker's colour */
  color?: string
  /** 0..~1.5 — scales the packet's brightness/length (a verdict hits harder than a remark) */
  strength?: number
  /** short label, only used for debugging */
  kind?: string
}

type Listener = (t: Thought) => void
const listeners = new Set<Listener>()

export function emitThought(t: Thought): void {
  for (const l of listeners) {
    try { l(t) } catch { /* a broken listener never breaks the floor */ }
  }
}

export function onThought(l: Listener): () => void {
  listeners.add(l)
  return () => { listeners.delete(l) }
}
