import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'
import { setUnauthorizedHandler } from '@/api/client'

// jsdom has no EventSource; the live-updates hook only needs construct/close.
class FakeEventSource {
  static instances: FakeEventSource[] = []
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  readonly url: string
  closed = false

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  emit(data: unknown) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) }))
  }

  close() {
    this.closed = true
  }
}
vi.stubGlobal('EventSource', FakeEventSource)

// jsdom can't navigate; record 401 redirects instead.
export const unauthorized = vi.fn()
setUnauthorizedHandler(unauthorized)

// Node 25 ships its own (file-backed, experimental) `localStorage` global that shadows jsdom's
// and has no methods unless started with --localstorage-file. Use a plain in-memory Storage so
// tests behave the same on every Node version.
class MemoryStorage implements Storage {
  #items = new Map<string, string>()
  get length() {
    return this.#items.size
  }
  clear() {
    this.#items.clear()
  }
  getItem(key: string) {
    return this.#items.get(key) ?? null
  }
  key(index: number) {
    return [...this.#items.keys()][index] ?? null
  }
  removeItem(key: string) {
    this.#items.delete(key)
  }
  setItem(key: string, value: string) {
    this.#items.set(key, String(value))
  }
}
vi.stubGlobal('localStorage', new MemoryStorage())
vi.stubGlobal('sessionStorage', new MemoryStorage())

// Vitest globals are off, so Testing Library can't register its own auto-cleanup.
afterEach(() => {
  cleanup()
  FakeEventSource.instances = []
  localStorage.clear()
  unauthorized.mockClear()
})

export { FakeEventSource }
