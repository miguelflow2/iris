/**
 * Liaison WebSocket du process principal vers le backend : indépendante de la fenêtre,
 * elle alimente l'indicateur de capture, le tray et les notifications même fenêtre fermée.
 */
import { EventEmitter } from 'events'
import WebSocket from 'ws'
import type { BackendInfo } from './backend'

export class BackendLink extends EventEmitter {
  private ws: WebSocket | null = null
  private info: BackendInfo | null = null
  private timer: NodeJS.Timeout | null = null
  private closed = false

  connect(info: BackendInfo): void {
    this.info = info
    this.closed = false
    this.open()
  }

  private open(): void {
    if (!this.info || this.closed) return
    const ws = new WebSocket(this.info.wsUrl)
    this.ws = ws
    ws.on('open', () => this.emit('open'))
    ws.on('message', (data) => {
      try {
        const event = JSON.parse(data.toString())
        this.emit('event', event)
        if (event.type === 'capture.state') this.emit('capture', event)
      } catch {
        /* message illisible */
      }
    })
    ws.on('close', () => this.scheduleReconnect())
    ws.on('error', () => {
      /* close suivra */
    })
  }

  private scheduleReconnect(): void {
    this.ws = null
    if (this.closed) return
    if (this.timer) clearTimeout(this.timer)
    this.timer = setTimeout(() => this.open(), 1500)
  }

  send(message: Record<string, unknown>): boolean {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message))
      return true
    }
    return false
  }

  close(): void {
    this.closed = true
    if (this.timer) clearTimeout(this.timer)
    // On détache les écouteurs avant de fermer : l'événement `close` de l'ancienne socket
    // arrive de façon asynchrone et, lors d'une relance du service, il remettrait `this.ws`
    // à null puis planifierait une reconnexion — soit deux sockets et des événements en double.
    this.ws?.removeAllListeners()
    this.ws?.close()
    this.ws = null
  }
}
