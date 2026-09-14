/** Tiny observable store — no external state library needed. */
import { useEffect, useState } from 'react'

export class Store<T> {
  private listeners = new Set<(v: T) => void>()
  constructor(private value: T) {}

  get(): T {
    return this.value
  }

  set(next: Partial<T> | ((prev: T) => Partial<T>)) {
    const patch = typeof next === 'function' ? (next as any)(this.value) : next
    this.value = { ...this.value, ...patch }
    this.listeners.forEach((l) => l(this.value))
  }

  subscribe(l: (v: T) => void) {
    this.listeners.add(l)
    return () => this.listeners.delete(l)
  }
}

export function useStore<T>(store: Store<T>): T {
  const [v, setV] = useState(store.get())
  useEffect(() => store.subscribe(setV) as any, [store])
  return v
}
