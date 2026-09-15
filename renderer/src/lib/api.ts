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

/**
 * Événements fabriqués ICI, jamais par le service (préfixe « ui. ») : ils portent jusqu'au magasin
 * les refus que TOUS les écrans peuvent recevoir, pour que l'application y réponde d'une seule façon
 * au lieu que chaque écran réinvente la sienne.
 * - ui.lunettes_requises : une route a répondu 428 { code: "lunettes_requises", fonction, message, acheter_url } ;
 * - ui.verrouillee : une route a répondu 401 parce qu'IRIS est verrouillée (message du service).
 */
export const EVT_LUNETTES_REQUISES = 'ui.lunettes_requises'
export const EVT_VERROUILLEE = 'ui.verrouillee'

export class ApiError extends Error {
  status: number
  retryable: boolean
  /** Le champ « detail » de la réponse, tel quel (texte ou objet : { code, message, … }). */
  detail: any
  constructor(message: string, status: number, retryable = false, detail: any = undefined) {
    super(message)
    this.status = status
    this.retryable = retryable
    this.detail = detail === undefined ? message : detail
  }

  /** Code machine du refus quand le service en donne un (« lunettes_requises », « consentement »…). */
  get code(): string | null {
    return this.detail && typeof this.detail === 'object' && typeof this.detail.code === 'string' ? this.detail.code : null
  }
}

/** Vrai si l'erreur est le refus « cette fonction marche avec les lunettes VELA ». */
export function estLunettesRequises(err: unknown): err is ApiError {
  return err instanceof ApiError && err.status === 428 && err.code === 'lunettes_requises'
}

/** Détail d'un refus de consentement (403 { code: "consentement", data_type, label, message }), sinon null. */
export function refusConsentement(err: unknown): { data_type: string; label: string; message: string } | null {
  if (!(err instanceof ApiError) || err.status !== 403 || err.code !== 'consentement') return null
  const d = err.detail
  return { data_type: String(d.data_type || ''), label: String(d.label || d.data_type || ''), message: String(d.message || err.message) }
}

/** Le texte à montrer pour une erreur quelconque : la phrase du service quand il en donne une. */
export function messageErreur(err: unknown): string {
  if (err instanceof Error) return err.message
  return String(err)
}

/**
 * Refus de la caméra des lunettes, dit au client. Le module caméra du service (lunettes_camera.py) refuse
 * la photo pour TOUTES les paires tant que l'en-tête de sa trame n'est pas confirmé sur le vrai matériel ;
 * son message technique (charge utile en hexadécimal, chemin d'un document interne, nom d'un réglage
 * d'exploration qui écrirait des octets non prouvés dans la puce) ne doit jamais atteindre un client. Tant
 * que le service ne renvoie pas lui-même { code: "camera_non_confirmee", message }, la phrase est remplacée ici.
 */
export const CAMERA_NON_CONFIRMEE =
  'La caméra des lunettes n’est pas encore activée dans IRIS (son protocole est en cours de confirmation) : aucune photo n’a été prise. En attendant, utilisez une photo prise avec votre téléphone, ou l’écran de l’ordinateur.'
const CAMERA_ABSENTE = 'Ces lunettes n’exposent pas de caméra utilisable par IRIS : aucune photo n’a été prise.'

/** Remplace le jargon interne connu du service par une phrase client ; laisse tout le reste intact. */
export function phraseClient(texte: string): string {
  if (/lunettes_exploration|LUNETTES-CAMERA-PROTOCOLE|en-tête exact de la trame/i.test(texte)) return CAMERA_NON_CONFIRMEE
  if (/service ae00|caractéristiques ae01/i.test(texte)) return CAMERA_ABSENTE
  return texte
}

/** Vrai si l'erreur est le refus « caméra des lunettes pas encore activée » (code du service ou phrase reconnue). */
export function estCameraNonConfirmee(err: unknown): boolean {
  return err instanceof ApiError && (err.code === 'camera_non_confirmee' || err.message === CAMERA_NON_CONFIRMEE)
}

/** Phrase lisible depuis le « detail » d'une réponse : la phrase du service, jamais du JSON brut quand on peut l'éviter. */
function texteDetail(detail: unknown, repli: string): string {
  if (typeof detail === 'string' && detail) return phraseClient(detail)
  if (detail && typeof detail === 'object') {
    const d = detail as Record<string, unknown>
    if (typeof d.message === 'string' && d.message) return phraseClient(d.message)
    // Erreurs de validation de FastAPI : une liste de { msg, loc }.
    if (Array.isArray(detail) && detail.length && typeof (detail[0] as any)?.msg === 'string') {
      return (detail as any[]).map((e) => e.msg).join(' ; ')
    }
    return JSON.stringify(detail)
  }
  return repli
}

// Reconnexion du WebSocket : 1,5 s au premier essai, puis de plus en plus espacée tant que la
// connexion n'aboutit pas. Une IRIS verrouillée ferme le WebSocket (code 4401) et refuse les
// suivants : sans cet espacement, l'application réessaierait en rafale toute la durée du verrou.
const RECONNEXION_MIN_MS = 1500
const RECONNEXION_MAX_MS = 15000

class Api {
  info: BackendInfo | null = null
  private ws: WebSocket | null = null
  private listeners = new Set<Listener>()
  private reconnectTimer: number | null = null
  private echecsConsecutifs = 0
  connected = false

  connect(info: BackendInfo): void {
    this.info = info
    this.echecsConsecutifs = 0
    this.openSocket()
  }

  /** Rouvre la liaison en direct tout de suite (après un déverrouillage, par exemple). */
  reconnecter(): void {
    this.echecsConsecutifs = 0
    if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    if (!this.connected) this.openSocket()
  }

  private openSocket(): void {
    if (!this.info) return
    if (this.ws) {
      // On détache l'ancienne socket avant de la fermer : son `onclose` asynchrone planifierait
      // sinon une reconnexion de plus (deux sockets, événements en double).
      const ancienne = this.ws
      ancienne.onopen = ancienne.onmessage = ancienne.onclose = ancienne.onerror = null
      try {
        ancienne.close()
      } catch {
        /* ignore */
      }
    }
    const ws = new WebSocket(this.info.wsUrl)
    this.ws = ws
    ws.onopen = () => {
      this.connected = true
      this.echecsConsecutifs = 0
      this.emit({ type: 'ws.open' })
    }
    ws.onmessage = (msg) => {
      try {
        this.emit(JSON.parse(msg.data))
      } catch {
        /* ignore */
      }
    }
    ws.onclose = (evt) => {
      const etaitOuverte = this.connected
      this.connected = false
      this.emit({ type: 'ws.close', code: evt.code })
      if (this.ws !== ws) return
      // 4401 = refus du service (verrou) ; une socket jamais ouverte = service injoignable ou refus.
      if (evt.code === 4401 || !etaitOuverte) this.echecsConsecutifs += 1
      else this.echecsConsecutifs = 0
      const delai = Math.min(RECONNEXION_MAX_MS, RECONNEXION_MIN_MS * 2 ** Math.max(0, this.echecsConsecutifs - 1))
      if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = window.setTimeout(() => this.openSocket(), delai)
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

  /** Construit l'erreur d'une réponse refusée et prévient le magasin des refus communs (lunettes, verrou). */
  private erreur(status: number, statusText: string, payload: unknown): ApiError {
    const objet = typeof payload === 'object' && payload ? (payload as Record<string, any>) : null
    const detail = objet ? objet.detail : payload
    const err = new ApiError(texteDetail(detail, statusText), status, Boolean(objet?.retryable), detail ?? statusText)
    if (status === 428 && err.code === 'lunettes_requises') {
      this.emit({ type: EVT_LUNETTES_REQUISES, ...(err.detail as Record<string, unknown>) })
    } else if (status === 401 && /verrouill/i.test(err.message)) {
      this.emit({ type: EVT_VERROUILLEE, message: err.message })
    }
    return err
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
    if (!res.ok) throw this.erreur(res.status, res.statusText, payload)
    return payload as T
  }

  /** Récupère un binaire (image, etc.) en portant le jeton de session : un <img src> nu ne
   *  transporte pas l'en-tête Authorization, donc les fichiers servis sous /api passent par ici,
   *  puis par URL.createObjectURL côté vue. Rien ne quitte la machine : tout est local. */
  async blob(path: string): Promise<Blob> {
    if (!this.info) throw new ApiError('Backend IRIS non démarré', 0, true)
    const res = await fetch(`${this.info.baseUrl}${path}`, {
      headers: { Authorization: `Bearer ${this.info.token}` }
    })
    if (!res.ok) {
      let payload: unknown = null
      try {
        payload = (res.headers.get('content-type') || '').includes('application/json') ? await res.json() : null
      } catch {
        payload = null
      }
      throw this.erreur(res.status, res.statusText, payload)
    }
    return res.blob()
  }

  /**
   * Envoie un fichier tel quel (octets bruts, sans base64 ni JSON) et suit la progression de l'envoi.
   * Chromium lit le fichier par morceaux depuis le disque : un enregistrement de plusieurs centaines de
   * mégaoctets ne devient jamais une chaîne JavaScript (une chaîne V8 plafonne vers 536 millions de
   * caractères, et un encodage base64 de 400 Mo la dépasse). XMLHttpRequest plutôt que fetch : seul lui
   * rapporte la progression d'un envoi.
   */
  envoyerFichier<T = any>(path: string, fichier: Blob, contentType: string, onProgres?: (fraction: number) => void): Promise<T> {
    const info = this.info
    if (!info) return Promise.reject(new ApiError('Backend IRIS non démarré', 0, true))
    return new Promise<T>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${info.baseUrl}${path}`)
      xhr.setRequestHeader('Authorization', `Bearer ${info.token}`)
      xhr.setRequestHeader('Content-Type', contentType)
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable && onProgres) onProgres(ev.loaded / Math.max(1, ev.total))
      }
      xhr.onerror = () => reject(new ApiError('Le service IRIS de cet ordinateur est injoignable.', 0, true))
      xhr.onabort = () => reject(new ApiError('Envoi interrompu.', 0, true))
      xhr.onload = () => {
        let payload: unknown = xhr.responseText
        if ((xhr.getResponseHeader('content-type') || '').includes('application/json')) {
          try {
            payload = JSON.parse(xhr.responseText)
          } catch {
            payload = xhr.responseText
          }
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(payload as T)
        else reject(this.erreur(xhr.status, xhr.statusText, payload))
      }
      xhr.send(fichier)
    })
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
