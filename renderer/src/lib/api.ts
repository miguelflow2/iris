/** Client HTTP + WebSocket vers le backend local IRIS (jeton de session fourni par le process principal). */
export interface BackendInfo {
  host: string
  port: number
  token: string
  data_dir: string
  baseUrl: string
  wsUrl: string
}

export type IrisEvent = { type: string; [key: string]: any }
type Listener = (event: IrisEvent) => void

export class ApiError extends Error {
  status: number
  retryable: boolean
  constructor(message: string, status: number, retryable = false) {
    super(message)
    this.status = status
    this.retryable = retryable
  }
}

class Api {
  info: BackendInfo | null = null
  private ws: WebSocket | null = null
  private listeners = new Set<Listener>()
  private reconnectTimer: number | null = null
  connected = false

  connect(info: BackendInfo): void {
    this.info = info
    this.openSocket()
  }

  private openSocket(): void {
    if (!this.info) return
    if (this.ws) {
      try {
        this.ws.close()
      } catch {
        /* ignore */
      }
    }
    const ws = new WebSocket(this.info.wsUrl)
    this.ws = ws
    ws.onopen = () => {
      this.connected = true
      this.emit({ type: 'ws.open' })
    }
    ws.onmessage = (msg) => {
      try {
        this.emit(JSON.parse(msg.data))
      } catch {
        /* ignore */
      }
    }
    ws.onclose = () => {
      this.connected = false
      this.emit({ type: 'ws.close' })
      if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = window.setTimeout(() => this.openSocket(), 1500)
    }
    ws.onerror = () => {
      /* onclose suit */
    }
  }

  private emit(event: IrisEvent): void {
    for (const l of Array.from(this.listeners)) {
      try {
        l(event)
      } catch (err) {
        console.error('listener error', err)
      }
    }
  }

  on(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  send(message: Record<string, unknown>): boolean {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message))
      return true
    }
    return false
  }

  async request<T = any>(method: string, path: string, body?: unknown): Promise<T> {
    if (!this.info) throw new ApiError('Backend IRIS non démarré', 0, true)
    const res = await fetch(`${this.info.baseUrl}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${this.info.token}`,
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {})
      },
      body: body !== undefined ? JSON.stringify(body) : undefined
    })
    const isJson = (res.headers.get('content-type') || '').includes('application/json')
    const payload = isJson ? await res.json() : await res.text()
    if (!res.ok) {
      const detail = typeof payload === 'object' && payload ? payload.detail : payload
      throw new ApiError(
        typeof detail === 'string' ? detail : JSON.stringify(detail ?? res.statusText),
        res.status,
        Boolean(typeof payload === 'object' && payload?.retryable)
      )
    }
    return payload as T
  }

  get<T = any>(path: string): Promise<T> {
    return this.request<T>('GET', path)
  }
  post<T = any>(path: string, body?: unknown): Promise<T> {
    return this.request<T>('POST', path, body ?? {})
  }
  put<T = any>(path: string, body?: unknown): Promise<T> {
    return this.request<T>('PUT', path, body ?? {})
  }
  patch<T = any>(path: string, body?: unknown): Promise<T> {
    return this.request<T>('PATCH', path, body ?? {})
  }
  delete<T = any>(path: string): Promise<T> {
    return this.request<T>('DELETE', path)
  }
}

export const api = new Api()

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('fr-CA', { dateStyle: 'medium', timeStyle: 'short' })
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString('fr-CA', { hour: '2-digit', minute: '2-digit' })
}
