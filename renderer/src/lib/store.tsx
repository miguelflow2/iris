import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { api, type BackendInfo, type IrisEvent } from './api'

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
  view: View
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
}

const StoreContext = createContext<StoreValue | null>(null)

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
  const [view, setView] = useState<View>('chat')
  const [toasts, setToasts] = useState<Toast[]>([])
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null)
  const [consentRequest, setConsentRequest] = useState<ConsentRequest | null>(null)
  const [appInfo, setAppInfo] = useState<StoreValue['appInfo']>(null)
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

  const bootstrap = useCallback(
    async (backend: BackendInfo) => {
      api.connect(backend)
      setInfo(backend)
      try {
        await Promise.all([refreshStatus(), refreshSettings(), refreshAgents()])
        setBackendState('ready')
      } catch (err) {
        setBackendState('failed')
        setBackendMessage(String(err))
      }
    },
    [refreshAgents, refreshSettings, refreshStatus]
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
        case 'chat.confirm':
          setConfirmRequest({
            confirm_id: event.confirm_id,
            conversation_id: event.conversation_id,
            title: event.title,
            detail: event.detail
          })
          break
        case 'chat.confirm_closed':
          setConfirmRequest((c) => (c && c.confirm_id === event.confirm_id ? null : c))
          break
        case 'chat.consent_required':
          setConsentRequest({
            conversation_id: event.conversation_id,
            data_type: event.data_type,
            label: event.label,
            description: event.description,
            agent: event.agent
          })
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
          // niveau du micro publié pendant l'écoute d'une commande : sert l'indicateur de la barre vocale
          setMicLevel({ peak: event.peak || 0, device: event.device || '', at: Date.now() })
          break
        case 'voice.warning':
          toast(event.text, 'error')
          break
        case 'voice.info':
          toast(event.text, 'info')
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
          toast(event.status === 'logged_in' || event.status === 'already_logged_in' ? `Connecté à ${event.site}.` : `Connexion à ${event.site} non confirmée.`, event.status?.includes('logged_in') ? 'success' : 'error')
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
  }, [refreshStatus, toast])

  const updateSettings = useCallback(
    async (patch: Record<string, unknown>) => {
      const next = await api.patch('/api/settings', patch)
      setSettings(next)
    },
    []
  )
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
      view,
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
      appInfo
    }),
    // `micLevel` fait partie des dépendances : sans lui, la valeur du contexte ne change pas
    // quand `voice.level` arrive et le vumètre de la barre vocale reste figé.
    [backendState, backendMessage, info, status, settings, agents, consent, capture, voice, micLevel, ttsSpeaking, view, toasts, toast, dismissToast, refreshStatus, refreshSettings, refreshAgents, updateSettings, setConsent, confirmRequest, answerConfirm, consentRequest, appInfo]
  )

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>
}

export function useStore(): StoreValue {
  const ctx = useContext(StoreContext)
  if (!ctx) throw new Error('useStore hors StoreProvider')
  return ctx
}
