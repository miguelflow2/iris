import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError, EVT_LUNETTES_REQUISES, EVT_VERROUILLEE, type BackendInfo, type IrisEvent } from './api'
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
  | 'accessibilite'
  | 'sous-titres'
  | 'alertes-sonores'
  | 'ecoute-assistee'
  | 'mode-dehors'
  | 'journal'
  | 'bouton-lunettes'
  | 'interprete'
  | 'vision-partagee'
  | 'cours'
  | 'cours-detail'
  | 'recus'
  | 'pas-a-pas'
  | 'entrainement'
  | 'prix'
  | 'resume-journee'
  | 'rappels-contexte'
  | 'verrou-vocal'
  | 'zones'
  | 'mode-invite'
  | 'verrou-distant'

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

/** Présence des lunettes VELA (GET /api/lunettes/presence, événement lunettes.presence). */
export interface PresenceLunettes {
  presentes: boolean
  /** d'où vient la présence : ordinateur, téléphone appairé… (null = absentes) */
  source: string | null
  verrou_actif: boolean
  nom: string | null
  attestation_age_s: number | null
  /** messages écrits restants de l'aperçu sans lunettes */
  apercu_restant: number
  apercu_total: number
  acheter_url: string
  limite?: string
}

/** Refus « cette fonction marche avec les lunettes VELA » à montrer (428 lunettes_requises ou garde d'écran). */
export interface DemandeLunettes {
  fonction?: string
  message?: string
  acheter_url?: string
}

/** Dernière alerte sonore reçue (événement alerte.sonore : « genre », jamais « type »). */
export interface AlerteSonore {
  id: number
  genre: string
  libelle: string
  confiance: number
  ts: number
  test: boolean
}

/** Verrouillage d'IRIS (sur place ou à distance). */
export interface EtatVerrou {
  verrouille: boolean
  depuis: string | null
  /** « local », « distance »… tel que le service le dit */
  raison: string | null
  /** phrase du service quand le verrou a été découvert par un refus 401 */
  message?: string
}

export interface EtatInvite {
  actif: boolean
  depuis: string | null
  jusqua: string | null
}

export interface EtatZone {
  dans_zone: boolean
  zone_nom: string | null
}

/** État de l'écoute locale (GET /api/ecoute/etat, événement ecoute.etat). */
export interface EtatEcoute {
  sous_titres: boolean
  journal: boolean
  enregistrement: { actif: boolean; nom: string | null; secondes: number }
  assistee: { actif: boolean; latence_ms: number | null }
  alertes: boolean
  modele_pret: boolean
  raison: string | null
  memoire_suspendue?: string | null
  transcription_active?: boolean
  demandes?: string[]
  cours?: { id: string; titre: string; secondes: number; lignes: number } | null
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
  /* ---- lunettes d'abord */
  /** null tant que le service n'a pas répondu (ou s'il ne connaît pas encore cette route) */
  presence: PresenceLunettes | null
  rafraichirPresence: () => Promise<void>
  /** refus « lunettes requises » affiché par App.tsx (feuille), null sinon */
  lunettesRequises: DemandeLunettes | null
  demanderLunettes: (demande?: DemandeLunettes) => void
  fermerLunettesRequises: () => void
  /** garde d'écran : vrai si la fonction peut partir ; sinon ouvre la feuille « lunettes requises » et rend faux */
  exigerLunettes: (fonction: string) => boolean
  /* ---- accessibilité et confiance */
  alerte: AlerteSonore | null
  fermerAlerte: () => void
  verrou: EtatVerrou | null
  deverrouiller: (motDePasse: string) => Promise<void>
  rafraichirVerrou: () => Promise<void>
  invite: EtatInvite | null
  zone: EtatZone | null
  ecoute: EtatEcoute | null
  rafraichirEcoute: () => Promise<void>
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
  const [presence, setPresence] = useState<PresenceLunettes | null>(null)
  const [lunettesRequises, setLunettesRequises] = useState<DemandeLunettes | null>(null)
  const [alerte, setAlerte] = useState<AlerteSonore | null>(null)
  const [verrou, setVerrou] = useState<EtatVerrou | null>(null)
  const [invite, setInvite] = useState<EtatInvite | null>(null)
  const [zone, setZone] = useState<EtatZone | null>(null)
  const [ecoute, setEcoute] = useState<EtatEcoute | null>(null)
  const toastId = useRef(1)
  const alerteId = useRef(1)
  const minuterieAlerte = useRef<number | null>(null)
  const minuteriePresence = useRef<number | null>(null)
  // Lu par les écouteurs d'événements sans les réabonner à chaque changement.
  const verrouRef = useRef<EtatVerrou | null>(null)
  verrouRef.current = verrou

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

  /* ------------------------------------------------------------ lunettes d'abord, confiance, écoute */
  const rafraichirPresence = useCallback(async () => {
    try {
      const p = await api.get('/api/lunettes/presence')
      if (p && typeof p.presentes === 'boolean') setPresence(p)
    } catch {
      /* service plus ancien ou verrouillé : on garde la dernière valeur connue */
    }
  }, [])
  // Les preuves de présence changent par rafales (état des lunettes, écoute) : une seule relecture.
  const presencePlusTard = useCallback(() => {
    if (minuteriePresence.current) window.clearTimeout(minuteriePresence.current)
    minuteriePresence.current = window.setTimeout(() => {
      minuteriePresence.current = null
      rafraichirPresence().catch(() => undefined)
    }, 800)
  }, [rafraichirPresence])
  const rafraichirEcoute = useCallback(async () => {
    try {
      const e = await api.get('/api/ecoute/etat')
      if (e && typeof e === 'object') setEcoute(e)
    } catch {
      /* module d'écoute absent : pas d'état */
    }
  }, [])
  const chargerConfiance = useCallback(async () => {
    try {
      const i = await api.get('/api/confiance/invite')
      setInvite({ actif: Boolean(i?.actif), depuis: i?.depuis ?? null, jusqua: i?.jusqua ?? null })
    } catch {
      /* module de confiance absent */
    }
    try {
      const z = await api.get('/api/confiance/zones')
      setZone({ dans_zone: Boolean(z?.zone_active), zone_nom: z?.zone_active?.nom ?? null })
    } catch {
      /* module de confiance absent */
    }
  }, [])
  const lireVerrou = useCallback(async (): Promise<EtatVerrou | null> => {
    try {
      const v = await api.get('/api/confiance/verrou/etat')
      return { verrouille: Boolean(v?.verrouille), depuis: v?.depuis ?? null, raison: v?.raison ?? null }
    } catch {
      return null
    }
  }, [])
  const chargerSecondaires = useCallback(() => {
    rafraichirLunettes().catch(() => undefined)
    chargerPersonas().catch(() => undefined)
    rafraichirPresence().catch(() => undefined)
    rafraichirEcoute().catch(() => undefined)
    chargerConfiance().catch(() => undefined)
  }, [rafraichirLunettes, chargerPersonas, rafraichirPresence, rafraichirEcoute, chargerConfiance])

  const bootstrap = useCallback(
    async (backend: BackendInfo) => {
      api.connect(backend)
      setInfo(backend)
      // Le verrou d'abord : c'est l'une des rares routes permises quand IRIS est verrouillée, et
      // toutes les autres répondraient 401 — l'application afficherait une panne au lieu du verrou.
      const v = await lireVerrou()
      if (v?.verrouille) {
        setVerrou(v)
        setBackendState('ready')
        return
      }
      try {
        await Promise.all([refreshStatus(), refreshSettings(), refreshAgents()])
        setVerrou(v)
        setBackendState('ready')
        chargerSecondaires()
      } catch (err) {
        if (err instanceof ApiError && err.status === 401 && /verrouill/i.test(err.message)) {
          setVerrou({ verrouille: true, depuis: null, raison: null, message: err.message })
          setBackendState('ready')
          return
        }
        setBackendState('failed')
        setBackendMessage(String(err))
      }
    },
    [refreshAgents, refreshSettings, refreshStatus, lireVerrou, chargerSecondaires]
  )

  /** Après un déverrouillage (ici, sur le téléphone ou par un redémarrage) : tout recharger. */
  const apresDeverrouillage = useCallback(async () => {
    setVerrou((v) => (v ? { ...v, verrouille: false, message: undefined } : v))
    api.reconnecter()
    try {
      await Promise.all([refreshStatus(), refreshSettings(), refreshAgents()])
      setBackendState('ready')
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 401)) {
        setBackendState('failed')
        setBackendMessage(String(err))
      }
    }
    chargerSecondaires()
  }, [refreshStatus, refreshSettings, refreshAgents, chargerSecondaires])

  const rafraichirVerrou = useCallback(async () => {
    const v = await lireVerrou()
    if (!v) return
    if (v.verrouille) setVerrou(v)
    else if (verrouRef.current?.verrouille) await apresDeverrouillage()
    else setVerrou(v)
  }, [lireVerrou, apresDeverrouillage])

  const deverrouiller = useCallback(
    async (motDePasse: string) => {
      // Les refus (mot de passe incorrect, trop de tentatives) remontent tels quels à l'écran.
      await api.post('/api/confiance/deverrouiller', { mot_de_passe: motDePasse })
      await apresDeverrouillage()
    },
    [apresDeverrouillage]
  )

  // Pendant le verrou, le WebSocket est fermé par le service : on relit l'état toutes les 5 s pour
  // voir un déverrouillage fait ailleurs (téléphone, relais).
  useEffect(() => {
    if (!verrou?.verrouille) return
    const t = window.setInterval(() => {
      rafraichirVerrou().catch(() => undefined)
    }, 5000)
    return () => window.clearInterval(t)
  }, [verrou?.verrouille, rafraichirVerrou])

  const demanderLunettes = useCallback((demande?: DemandeLunettes) => setLunettesRequises(demande || {}), [])
  const fermerLunettesRequises = useCallback(() => setLunettesRequises(null), [])
  const exigerLunettes = useCallback(
    (fonction: string) => {
      // Présence inconnue (service qui ne répond pas encore) : on laisse partir, le service tranchera
      // lui-même par un 428 que la feuille affichera de toute façon.
      if (!presence || presence.presentes) return true
      setLunettesRequises({ fonction, acheter_url: presence.acheter_url })
      return false
    },
    [presence]
  )

  const fermerAlerte = useCallback(() => {
    if (minuterieAlerte.current) window.clearTimeout(minuterieAlerte.current)
    minuterieAlerte.current = null
    setAlerte(null)
  }, [])

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
          // Reconnexion : ce qui a pu changer pendant la coupure (présence, invité, zone, écoute, verrou).
          rafraichirPresence().catch(() => undefined)
          rafraichirEcoute().catch(() => undefined)
          chargerConfiance().catch(() => undefined)
          if (verrouRef.current?.verrouille) rafraichirVerrou().catch(() => undefined)
          break
        case 'ws.close':
          break
        case 'capture.state':
          setCapture({ mic: event.mic, screen: event.screen, camera: event.camera, listening: event.listening })
          break
        case 'voice.state':
          setVoice(event)
          // le micro des lunettes est aussi une preuve de présence (lunettes_presence.py)
          presencePlusTard()
          break
        case 'tts.state':
          setTtsSpeaking(Boolean(event.speaking))
          break
        case 'consent.updated':
          setConsentState(event.consent)
          break
        case 'settings.updated':
          setSettings(event.settings)
          presencePlusTard()
          break
        case 'agent.updated':
          setAgents((list) => list.map((a) => (a.name === event.agent.name ? event.agent : a)))
          refreshStatus().catch(() => undefined)
          break
        case 'glasses.state':
          // l'événement porte le statut complet des lunettes
          setLunettes((prev: any) => ({ ...(prev || {}), ...event, type: undefined }))
          presencePlusTard()
          break
        case 'glasses.connected':
        case 'glasses.disconnected':
        case 'glasses.connecting':
          rafraichirLunettes().catch(() => undefined)
          presencePlusTard()
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
        /* ---------------------------------------------------------------- lunettes d'abord */
        case 'lunettes.presence': {
          const { type: _t, ...etat } = event
          if (typeof etat.presentes === 'boolean') setPresence(etat as PresenceLunettes)
          break
        }
        case EVT_LUNETTES_REQUISES:
          // Un écran a reçu un 428 : la feuille « Cette fonction marche avec les lunettes VELA » s'ouvre
          // d'elle-même (App.tsx), et la présence est relue (elle a peut-être changé depuis).
          setLunettesRequises({ fonction: event.fonction, message: event.message, acheter_url: event.acheter_url })
          rafraichirPresence().catch(() => undefined)
          break
        /* ---------------------------------------------------------------- accessibilité */
        case 'alerte.sonore': {
          const id = alerteId.current++
          setAlerte({
            id,
            genre: String(event.genre || ''),
            libelle: String(event.libelle || 'Alerte sonore'),
            confiance: Number(event.confiance) || 0,
            ts: Number(event.ts) || Date.now() / 1000,
            test: Boolean(event.test)
          })
          // 10 s à l'écran, sauf si une alerte plus récente l'a remplacée entre-temps.
          if (minuterieAlerte.current) window.clearTimeout(minuterieAlerte.current)
          minuterieAlerte.current = window.setTimeout(() => {
            minuterieAlerte.current = null
            setAlerte((a) => (a && a.id === id ? null : a))
          }, 10000)
          break
        }
        case 'ecoute.etat': {
          const { type: _t, ...etat } = event
          setEcoute(etat as EtatEcoute)
          break
        }
        case 'voice.locuteur_refuse':
          toast(`Commande vocale ignorée par le verrou vocal${event.raison ? ` : ${event.raison}` : ''}.`, 'error')
          break
        case 'rappel.contexte':
          toast(`Rappel${event.personne ? ` pour ${event.personne}` : ''} : ${event.texte || ''}`, 'info')
          break
        case 'partage.message':
          toast(`Message de votre proche : ${event.texte || ''}`, 'info')
          break
        /* ---------------------------------------------------------------- confiance */
        case 'verrou.etat':
          if (event.verrouille) {
            setVerrou({ verrouille: true, depuis: event.depuis ?? null, raison: event.raison ?? null })
          } else if (verrouRef.current?.verrouille) {
            apresDeverrouillage().catch(() => undefined)
          }
          break
        case EVT_VERROUILLEE:
          // Refus 401 « IRIS est verrouillée » reçu par n'importe quelle requête.
          setVerrou((v) => (v?.verrouille ? v : { verrouille: true, depuis: null, raison: null, message: event.message }))
          rafraichirVerrou().catch(() => undefined)
          break
        case 'invite.etat':
          setInvite({ actif: Boolean(event.actif), depuis: event.depuis ?? null, jusqua: event.jusqua ?? null })
          break
        case 'zone.etat':
          setZone({ dans_zone: Boolean(event.dans_zone), zone_nom: event.zone_nom ?? null })
          break
        default:
          break
      }
    })
  }, [refreshStatus, toast, rafraichirLunettes, rafraichirPresence, presencePlusTard, rafraichirEcoute, chargerConfiance, rafraichirVerrou, apresDeverrouillage])

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
      setPref,
      presence,
      rafraichirPresence,
      lunettesRequises,
      demanderLunettes,
      fermerLunettesRequises,
      exigerLunettes,
      alerte,
      fermerAlerte,
      verrou,
      deverrouiller,
      rafraichirVerrou,
      invite,
      zone,
      ecoute,
      rafraichirEcoute
    }),
    // `micLevel` fait partie des dépendances : sans lui, le vumètre de la barre vocale reste figé.
    [backendState, backendMessage, info, status, settings, agents, consent, capture, voice, micLevel, ttsSpeaking, lunettes, rafraichirLunettes, personas, nav, setView, toasts, toast, dismissToast, refreshStatus, refreshSettings, refreshAgents, updateSettings, setConsent, confirmRequest, answerConfirm, consentRequest, appInfo, favoris, basculerFavori, estFavori, prefs, setPref, presence, rafraichirPresence, lunettesRequises, demanderLunettes, fermerLunettesRequises, exigerLunettes, alerte, fermerAlerte, verrou, deverrouiller, rafraichirVerrou, invite, zone, ecoute, rafraichirEcoute]
  )

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>
}

export function useStore(): StoreValue {
  const ctx = useContext(StoreContext)
  if (!ctx) throw new Error('useStore hors StoreProvider')
  return ctx
}
