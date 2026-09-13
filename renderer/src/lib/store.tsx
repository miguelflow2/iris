import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { api, type BackendInfo, type IrisEvent } from './api'
import { PERSONAS_DEFAUT, type Persona } from './roles'

/* =========================================================================
   État global de l'application : connexion au service local, réglages, voix,
   lunettes, navigation par onglets + pile d'écrans, favoris et préférences
   locales. Tout écran lit ici ; rien n'est dupliqué dans les écrans.
   ========================================================================= */

/** Les quatre onglets de la barre du bas. */
export type Onglet = 'accueil' | 'ia' | 'album' | 'profil'

/** Les écrans qui s'ouvrent par-dessus un onglet (avec flèche de retour). */
export type Ecran =
  | 'connecter'
  | 'lunettes'
  | 'lunettes-audio'
  | 'lunettes-technique'
  | 'tuto-camera'
  | 'tuto-touchpad'
  | 'assistant-intro'
  | 'traduction'
  | 'lumiere-bd'
  | 'album-parametres'
  | 'discussions'
  | 'langue-ia'
  | 'profil-modifier'
  | 'compte-securite'
  | 'commentaire'
  | 'faq'
  | 'a-propos'
  | 'memoire'
  | 'routines'
  | 'taches'
  | 'surveillances'
  | 'abonnement'
  | 'reglages'
  | 'reglages-voix'
  | 'reglages-pc'
  | 'communications'
  | 'comptes-web'
  | 'moteurs-ia'
  | 'confidentialite'

export interface Page {
  ecran: Ecran
  params?: Record<string, any>
}

/** Anciens identifiants de vue : encore acceptés par `setView` pour le code porté. */
export type View = 'chat' | 'agents' | 'glasses' | 'routines' | 'watches' | 'memory' | 'tasks' | 'privacy' | 'plan' | 'settings'

export interface Toast {
  id: number
  kind: 'info' | 'error' | 'success'
  text: string
}

export interface ConfirmRequest {
  confirm_id: string
  conversation_id: string
  title: string
  detail: string
}

export interface ConsentRequest {
  conversation_id: string
  data_type: string
  label: string
  description: string
  agent?: string
}

/** Un message mis en favori (onglet IA › Favoris). Conservé sur cet ordinateur seulement. */
export interface Favori {
  id: string
  conversation_id: string
  texte: string
  role: string
  date: string
}

/** Préférences purement locales (pas de réglage serveur) : album. */
export interface PrefsLocales {
  album_filigrane: boolean
  album_stabilisation: boolean
  album_enregistrement_auto: boolean
  assistant_intro_vue: boolean
}

export interface Nav {
  onglet: Onglet
  pile: Page[]
  /** ouvre un écran par-dessus l'onglet courant */
  ouvrir: (ecran: Ecran, params?: Record<string, any>) => void
  /** revient à l'écran précédent (ou à l'onglet si la pile est vide) */
  retour: () => void
  /** change d'onglet et vide la pile */
  allerOnglet: (onglet: Onglet) => void
  /** remplace toute la pile par un écran (ex. après une action) */
  remplacer: (ecran: Ecran, params?: Record<string, any>) => void
  viderPile: () => void
}

interface StoreValue {
  backendState: 'starting' | 'ready' | 'down' | 'failed'
  backendMessage: string
  info: BackendInfo | null
  status: any
  settings: any
  agents: any[]
  consent: Record<string, any>
  capture: { mic: boolean; screen: boolean; camera: boolean; listening: boolean }
  voice: any
  micLevel: { peak: number; device: string; at: number } | null
  ttsSpeaking: boolean
  /** état complet des lunettes (GET /api/glasses/status, tenu à jour par les événements) */
  lunettes: any
  rafraichirLunettes: () => Promise<void>
  personas: Persona[]
  nav: Nav
  /** compatibilité : les anciens identifiants de vue ouvrent le bon onglet ou écran */
  setView: (v: View) => void
  toasts: Toast[]
  toast: (text: string, kind?: Toast['kind']) => void
  dismissToast: (id: number) => void
  refreshStatus: () => Promise<void>
  refreshSettings: () => Promise<void>
  refreshAgents: () => Promise<void>
  updateSettings: (patch: Record<string, unknown>) => Promise<void>
  setConsent: (dataType: string, granted: boolean) => Promise<void>
  confirmRequest: ConfirmRequest | null
  answerConfirm: (approved: boolean) => void
  consentRequest: ConsentRequest | null
  closeConsentRequest: () => void
  appInfo: { version: string; platform: string; userData: string; logPath: string } | null
  favoris: Favori[]
  basculerFavori: (f: Favori) => void
  estFavori: (id: string) => boolean
  prefs: PrefsLocales
  setPref: <K extends keyof PrefsLocales>(cle: K, valeur: PrefsLocales[K]) => void
}

const StoreContext = createContext<StoreValue | null>(null)

const PREFS_DEFAUT: PrefsLocales = { album_filigrane: false, album_stabilisation: false, album_enregistrement_auto: false, assistant_intro_vue: false }

function lireLocal<T>(cle: string, defaut: T): T {
  try {
    const brut = window.localStorage.getItem(cle)
    return brut ? { ...defaut, ...JSON.parse(brut) } : defaut
  } catch {
    return defaut
  }
}
function lireListe<T>(cle: string): T[] {
  try {
    const brut = window.localStorage.getItem(cle)
    const v = brut ? JSON.parse(brut) : []
    return Array.isArray(v) ? v : []
  } catch {
    return []
  }
}
function ecrireLocal(cle: string, valeur: unknown): void {
  try {
    window.localStorage.setItem(cle, JSON.stringify(valeur))
  } catch {
    /* stockage indisponible : on continue sans persistance */
  }
}

/** Correspondance des anciennes vues vers la nouvelle navigation. */
const VUE_VERS_NAV: Record<View, { onglet: Onglet; ecran?: Ecran }> = {
  chat: { onglet: 'ia' },
  glasses: { onglet: 'accueil', ecran: 'lunettes' },
  memory: { onglet: 'profil', ecran: 'memoire' },
  routines: { onglet: 'profil', ecran: 'routines' },
  tasks: { onglet: 'profil', ecran: 'taches' },
  watches: { onglet: 'profil', ecran: 'surveillances' },
  privacy: { onglet: 'profil', ecran: 'confidentialite' },
  plan: { onglet: 'profil', ecran: 'abonnement' },
  agents: { onglet: 'profil', ecran: 'moteurs-ia' },
  settings: { onglet: 'profil', ecran: 'reglages' }
}

export function StoreProvider({ children }: { children: React.ReactNode }): JSX.Element {
  const [backendState, setBackendState] = useState<StoreValue['backendState']>('starting')
  const [backendMessage, setBackendMessage] = useState('')
  const [info, setInfo] = useState<BackendInfo | null>(null)
  const [status, setStatus] = useState<any>(null)
  const [settings, setSettings] = useState<any>(null)
  const [agents, setAgents] = useState<any[]>([])
  const [consent, setConsentState] = useState<Record<string, any>>({})
  const [capture, setCapture] = useState({ mic: false, screen: false, camera: false, listening: false })
  const [voice, setVoice] = useState<any>(null)
  const [micLevel, setMicLevel] = useState<{ peak: number; device: string; at: number } | null>(null)
  const [ttsSpeaking, setTtsSpeaking] = useState(false)
  const [lunettes, setLunettes] = useState<any>(null)
  const [personas, setPersonas] = useState<Persona[]>(PERSONAS_DEFAUT)
  const [onglet, setOnglet] = useState<Onglet>('accueil')
  const [pile, setPile] = useState<Page[]>([])
  const [toasts, setToasts] = useState<Toast[]>([])
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null)
  const [consentRequest, setConsentRequest] = useState<ConsentRequest | null>(null)
  const [appInfo, setAppInfo] = useState<StoreValue['appInfo']>(null)
  const [favoris, setFavoris] = useState<Favori[]>(() => lireListe<Favori>('iris.favoris'))
  const [prefs, setPrefs] = useState<PrefsLocales>(() => lireLocal('iris.prefs', PREFS_DEFAUT))
  const toastId = useRef(1)

  const toast = useCallback((text: string, kind: Toast['kind'] = 'info') => {
    const id = toastId.current++
    setToasts((t) => [...t, { id, kind, text }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === 'error' ? 8000 : 4000)
  }, [])
  const dismissToast = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), [])

  const refreshStatus = useCallback(async () => {
    const s = await api.get('/api/status')
    setStatus(s)
    setConsentState(s.consent || {})
    setCapture(s.capture)
    setVoice(s.voice)
  }, [])
  const refreshSettings = useCallback(async () => setSettings(await api.get('/api/settings')), [])
  const refreshAgents = useCallback(async () => setAgents((await api.get('/api/agents')).agents), [])
  const rafraichirLunettes = useCallback(async () => {
    try {
      setLunettes(await api.get('/api/glasses/status'))
    } catch {
      /* le service répondra plus tard */
    }
  }, [])
  const chargerPersonas = useCallback(async () => {
    try {
      const r = await api.get('/api/personas')
      if (Array.isArray(r?.personas) && r.personas.length) setPersonas(r.personas)
    } catch {
      /* service sans rôles : liste par défaut */
    }
  }, [])

  const bootstrap = useCallback(
    async (backend: BackendInfo) => {
      api.connect(backend)
      setInfo(backend)
      try {
        await Promise.all([refreshStatus(), refreshSettings(), refreshAgents()])
        setBackendState('ready')
        rafraichirLunettes().catch(() => undefined)
        chargerPersonas().catch(() => undefined)
      } catch (err) {
        setBackendState('failed')
        setBackendMessage(String(err))
      }
    },
    [refreshAgents, refreshSettings, refreshStatus, rafraichirLunettes, chargerPersonas]
  )

  useEffect(() => {
    window.iris.appInfo().then(setAppInfo).catch(() => undefined)
    window.iris.getBackend().then((backend) => {
      if (backend) bootstrap(backend)
    })
    const offBackend = window.iris.onBackend((backend) => bootstrap(backend))
    const offStatus = window.iris.onBackendStatus((s) => {
      if (s.state === 'down') setBackendState('down')
      if (s.state === 'failed') {
        setBackendState('failed')
        setBackendMessage(s.message || '')
      }
    })
    return () => {
      offBackend()
      offStatus()
    }
  }, [bootstrap])

  useEffect(() => {
    return api.on((event: IrisEvent) => {
      switch (event.type) {
        case 'hello':
          setStatus(event.status)
          setConsentState(event.status.consent || {})
          setCapture(event.status.capture)
          setVoice(event.status.voice)
          setBackendState('ready')
          rafraichirLunettes().catch(() => undefined)
          break
        case 'ws.close':
          break
        case 'capture.state':
          setCapture({ mic: event.mic, screen: event.screen, camera: event.camera, listening: event.listening })
          break
        case 'voice.state':
          setVoice(event)
          break
        case 'tts.state':
          setTtsSpeaking(Boolean(event.speaking))
          break
        case 'consent.updated':
          setConsentState(event.consent)
          break
        case 'settings.updated':
          setSettings(event.settings)
          break
        case 'agent.updated':
          setAgents((list) => list.map((a) => (a.name === event.agent.name ? event.agent : a)))
          refreshStatus().catch(() => undefined)
          break
        case 'glasses.state':
          // l'événement porte le statut complet des lunettes
          setLunettes((prev: any) => ({ ...(prev || {}), ...event, type: undefined }))
          break
        case 'glasses.connected':
        case 'glasses.disconnected':
        case 'glasses.connecting':
          rafraichirLunettes().catch(() => undefined)
          if (event.type === 'glasses.connected') toast('Lunettes connectées.', 'success')
          if (event.type === 'glasses.disconnected') toast('Lunettes déconnectées.', 'info')
          break
        case 'chat.confirm':
          setConfirmRequest({ confirm_id: event.confirm_id, conversation_id: event.conversation_id, title: event.title, detail: event.detail })
          break
        case 'chat.confirm_closed':
          setConfirmRequest((c) => (c && c.confirm_id === event.confirm_id ? null : c))
          break
        case 'chat.consent_required':
          setConsentRequest({ conversation_id: event.conversation_id, data_type: event.data_type, label: event.label, description: event.description, agent: event.agent })
          break
        case 'chat.error':
          if (event.code === 'no_agent' || event.code === 'local_only' || event.code === 'quota') toast(event.message, 'error')
          break
        case 'task.updated':
          if (event.task?.status === 'done') toast(`Tâche terminée : ${event.task.title}`, 'success')
          if (event.task?.status === 'failed') toast(`Tâche échouée : ${event.task.title}`, 'error')
          break
        case 'tts.quota':
          toast(event.message, event.level === 'error' ? 'error' : 'info')
          break
        case 'tts.fallback':
          toast(event.reason, 'error')
          break
        case 'privacy.mode':
          toast(event.enabled ? 'Mode confidentiel activé : micro coupé.' : 'Mode confidentiel désactivé.', 'info')
          break
        case 'reminder.due':
          toast(`⏰ Rappel : ${event.reminder?.text}`, 'info')
          break
        case 'voice.calibration':
          if (event.added) toast(`Variante apprise : « ${event.added} »`, 'success')
          else if (event.heard) toast(`Entendu : « ${event.heard} » (déjà reconnu)`, 'info')
          break
        case 'routine.ran':
          toast(`Routine « ${event.name} » exécutée.`, 'success')
          break
        case 'voice.level':
          setMicLevel({ peak: event.peak || 0, device: event.device || '', at: Date.now() })
          break
        case 'voice.warning':
          toast(event.text, 'error')
          break
        case 'voice.info':
          toast(event.text, 'info')
          break
        case 'voice.glasses_required':
          toast(event.message || event.text || 'Les lunettes VELA doivent être connectées pour parler à IRIS.', 'error')
          break
        case 'watch.alert':
          toast(event.message, event.needs_confirmation || event.verdict === 'attention' ? 'error' : 'success')
          break
        case 'plan.synced':
          toast(event.message, 'success')
          break
        case 'plan.expiring':
          toast(event.message, 'error')
          break
        case 'voice.paused':
          toast(`Écoute en pause ${event.minutes} min. Elle reprend ensuite toute seule.`, 'info')
          break
        case 'voice.muted':
          toast(event.muted ? 'Micro coupé. Ctrl+Maj+M pour le réactiver.' : 'Micro réactivé.', 'info')
          break
        case 'voice.interrupted':
          break
        case 'web.captcha':
          toast('Le site affiche un contrôle de sécurité : résolvez-le dans la fenêtre du navigateur, IRIS attend.', 'error')
          break
        case 'web.login':
          toast(
            event.status === 'logged_in' || event.status === 'already_logged_in' ? `Connecté à ${event.site}.` : `Connexion à ${event.site} non confirmée.`,
            event.status?.includes('logged_in') ? 'success' : 'error'
          )
          break
        case 'plan.quota':
          toast(event.message, 'info')
          break
        case 'plan.changed':
          refreshStatus().catch(() => undefined)
          break
        case 'voice.model_ready':
          toast(event.ready ? 'Modèle de reconnaissance vocale prêt.' : `Téléchargement échoué : ${event.error}`, event.ready ? 'success' : 'error')
          break
        default:
          break
      }
    })
  }, [refreshStatus, toast, rafraichirLunettes])

  const updateSettings = useCallback(async (patch: Record<string, unknown>) => {
    const next = await api.patch('/api/settings', patch)
    setSettings(next)
  }, [])
  const setConsent = useCallback(async (dataType: string, granted: boolean) => {
    const res = await api.put(`/api/consent/${dataType}`, { granted })
    setConsentState(res.consent)
  }, [])
  const answerConfirm = useCallback(
    (approved: boolean) => {
      if (!confirmRequest) return
      api.send({ type: 'chat.confirm_reply', confirm_id: confirmRequest.confirm_id, approved })
      setConfirmRequest(null)
    },
    [confirmRequest]
  )

  /* ------------------------------------------------------------ navigation */
  const ouvrir = useCallback((ecran: Ecran, params?: Record<string, any>) => setPile((p) => [...p, { ecran, params }]), [])
  const retour = useCallback(() => setPile((p) => p.slice(0, -1)), [])
  const allerOnglet = useCallback((o: Onglet) => {
    setOnglet(o)
    setPile([])
  }, [])
  const remplacer = useCallback((ecran: Ecran, params?: Record<string, any>) => setPile([{ ecran, params }]), [])
  const viderPile = useCallback(() => setPile([]), [])
  const nav = useMemo<Nav>(() => ({ onglet, pile, ouvrir, retour, allerOnglet, remplacer, viderPile }), [onglet, pile, ouvrir, retour, allerOnglet, remplacer, viderPile])
  const setView = useCallback(
    (v: View) => {
      const cible = VUE_VERS_NAV[v]
      if (!cible) return
      setOnglet(cible.onglet)
      setPile(cible.ecran ? [{ ecran: cible.ecran }] : [])
    },
    []
  )

  /* ------------------------------------------------------------ favoris et préférences locales */
  const basculerFavori = useCallback((f: Favori) => {
    setFavoris((liste) => {
      const suivant = liste.some((x) => x.id === f.id) ? liste.filter((x) => x.id !== f.id) : [f, ...liste]
      ecrireLocal('iris.favoris', suivant)
      return suivant
    })
  }, [])
  const estFavori = useCallback((id: string) => favoris.some((x) => x.id === id), [favoris])
  const setPref = useCallback(<K extends keyof PrefsLocales>(cle: K, valeur: PrefsLocales[K]) => {
    setPrefs((p) => {
      const suivant = { ...p, [cle]: valeur }
      ecrireLocal('iris.prefs', suivant)
      return suivant
    })
  }, [])

  const value = useMemo<StoreValue>(
    () => ({
      backendState,
      backendMessage,
      info,
      status,
      settings,
      agents,
      consent,
      capture,
      voice,
      micLevel,
      ttsSpeaking,
      lunettes,
      rafraichirLunettes,
      personas,
      nav,
      setView,
      toasts,
      toast,
      dismissToast,
      refreshStatus,
      refreshSettings,
      refreshAgents,
      updateSettings,
      setConsent,
      confirmRequest,
      answerConfirm,
      consentRequest,
      closeConsentRequest: () => setConsentRequest(null),
      appInfo,
      favoris,
      basculerFavori,
      estFavori,
      prefs,
      setPref
    }),
    // `micLevel` fait partie des dépendances : sans lui, le vumètre de la barre vocale reste figé.
    [backendState, backendMessage, info, status, settings, agents, consent, capture, voice, micLevel, ttsSpeaking, lunettes, rafraichirLunettes, personas, nav, setView, toasts, toast, dismissToast, refreshStatus, refreshSettings, refreshAgents, updateSettings, setConsent, confirmRequest, answerConfirm, consentRequest, appInfo, favoris, basculerFavori, estFavori, prefs, setPref]
  )

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>
}

export function useStore(): StoreValue {
  const ctx = useContext(StoreContext)
  if (!ctx) throw new Error('useStore hors StoreProvider')
  return ctx
}
