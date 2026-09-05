import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Markdown } from '../components/ui'
import { api, formatTime, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

interface Conversation {
  id: string
  title: string
  agent: string
  kind: string
  updated_at: string
  busy: boolean
  archived?: boolean
}

interface ToolEvent {
  id: string
  name: string
  input: Record<string, unknown>
  status: 'running' | 'done' | 'error'
  result?: string
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
  images: { media_type: string; data: string }[]
  agent?: string | null
  model?: string | null
  meta: any
  created_at: string
  streaming?: boolean
  thinking?: string
  tools?: ToolEvent[]
  infos?: string[]
}

const AGENT_LABEL: Record<string, string> = { openrouter: 'OpenRouter', claude: 'Claude', gpt: 'GPT', gemini: 'Gemini', custom: 'IA perso', auto: 'Auto', system: 'IRIS' }

/** Exemples proposés sur un fil vide : ce que l'on peut demander à IRIS, en une phrase exacte.
 *  `local: true` = commande exécutée par le backend sans réseau ni clé d'API (voir quick_commands.py) :
 *  un clic l'envoie tout de suite. Les autres remplissent seulement la zone d'écriture, pour que
 *  personne n'envoie une demande par inadvertance pendant une démonstration. */
const SUGGESTIONS: { verbe: string; phrase: string; local: boolean }[] = [
  { verbe: 'Répondre tout de suite', phrase: 'Quelle heure est-il ?', local: true },
  { verbe: 'Ouvrir une application', phrase: 'Ouvre la calculatrice', local: true },
  { verbe: 'Lancer de la musique', phrase: 'Mets de la musique jazz', local: true },
  { verbe: 'Prendre une note', phrase: 'Prends une note : rappeler le fournisseur demain', local: false },
  { verbe: 'Lire votre écran', phrase: 'Que vois-tu à l’écran ?', local: false },
  { verbe: 'Écrire du code', phrase: 'Crée un jeu de morpion dans un fichier HTML', local: false }
]

/** Conversation ouverte pendant cette session de l'application. Survit au démontage de ChatView
 *  (quand on passe à Mémoire ou Confidentialité puis qu'on revient), mais pas au lancement :
 *  IRIS s'ouvre toujours sur un fil neuf plutôt que sur la dernière conversation modifiée. */
let lastOpened: string | null = null

/** Nombre de jours civils écoulés (0 = aujourd'hui, 1 = hier). -1 si la date est illisible. */
function joursEcoules(d: Date): number {
  if (Number.isNaN(d.getTime())) return -1
  const jour = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  return Math.round((jour(new Date()) - jour(d)) / 86400000)
}

/** Horodatage d'une conversation dans la liste : l'heure aujourd'hui, « hier », le jour de la
 *  semaine dans les sept derniers jours, la date ensuite. Sans cela, une conversation d'il y a
 *  deux semaines affiche « 14:32 » exactement comme celle d'il y a dix minutes. */
function formatQuand(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const n = joursEcoules(d)
  if (n <= 0) return d.toLocaleTimeString('fr-CA', { hour: '2-digit', minute: '2-digit' })
  if (n === 1) return 'hier'
  if (n < 7) return d.toLocaleDateString('fr-CA', { weekday: 'long' })
  const memeAnnee = d.getFullYear() === new Date().getFullYear()
  return d.toLocaleDateString('fr-CA', memeAnnee ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' })
}

/** Titre de section de la liste de conversations. */
function seauDe(iso: string | null | undefined): string {
  if (!iso) return 'Plus tôt'
  const n = joursEcoules(new Date(iso))
  if (n < 0) return 'Plus tôt'
  if (n === 0) return 'Aujourd’hui'
  if (n === 1) return 'Hier'
  if (n < 7) return '7 derniers jours'
  return 'Plus tôt'
}

// Styles posés ici plutôt que dans styles.css : ce fichier est le seul du périmètre de cette
// correction. Ils reprennent la grammaire visuelle existante (.nav-group, .conv-item, .btn).
const STYLE_GROUPE: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: '0.14em',
  textTransform: 'uppercase',
  color: 'var(--muted)',
  fontWeight: 600,
  padding: '14px 11px 4px'
}
const STYLE_EXEMPLE: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'flex-start',
  gap: 3,
  textAlign: 'left',
  whiteSpace: 'normal',
  height: 'auto',
  padding: '9px 12px',
  lineHeight: 1.45
}

export function ChatView(): JSX.Element {
  const { agents, settings, status, toast, voice, ttsSpeaking, consent, setView, micLevel, updateSettings } = useStore()
  const plan = status?.plan
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<{ name: string; media_type: string; data: string }[]>([])
  const [agentChoice, setAgentChoice] = useState('auto')
  const [busy, setBusy] = useState(false)
  const [lastTranscript, setLastTranscript] = useState('')
  const [lastLatency, setLastLatency] = useState<number | null>(null)
  const [showVoiceConv, setShowVoiceConv] = useState(false)
  const [lastVoiceAt, setLastVoiceAt] = useState<string | null>(null)
  const [filtre, setFiltre] = useState('')
  const [showArchives, setShowArchives] = useState(false)
  const [archivedCount, setArchivedCount] = useState(0)
  const [dlModel, setDlModel] = useState(false)
  // repli de la colonne des conversations : en démonstration, le fil doit prendre toute la largeur
  const [listOpen, setListOpen] = useState(() => {
    try {
      return localStorage.getItem('iris.convlist') !== '0'
    } catch {
      return true
    }
  })
  const listRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const rechercheRef = useRef<HTMLInputElement>(null)
  const activeRef = useRef<string | null>(null)
  activeRef.current = activeId
  // L'abonnement WebSocket est monté une seule fois : sans ces références il verrait
  // éternellement les valeurs du premier rendu.
  const busyRef = useRef(false)
  busyRef.current = busy
  const inputRef = useRef('')
  inputRef.current = input
  const voiceOpenRef = useRef(false)
  voiceOpenRef.current = showVoiceConv
  const archivesRef = useRef(false)

  const readyAgents = useMemo(() => agents.filter((a) => a.ready), [agents])

  const loadConversations = useCallback(async () => {
    const res = await api.get(`/api/conversations${archivesRef.current ? '?archived=true' : ''}`)
    setConversations(res.conversations)
    setArchivedCount(res.archived_count ?? 0)
    return res.conversations as Conversation[]
  }, [])

  /** Horodatage du fil vocal, sans charger ses messages (il grossit à vie). */
  const loadVoiceMeta = useCallback(async () => {
    try {
      const res = await api.get('/api/conversations?kind=voice')
      const conv = res.conversations?.[0]
      if (conv) setLastVoiceAt(conv.updated_at)
    } catch {
      /* le fil vocal n'existe pas encore : la ligne épinglée reste en état d'attente */
    }
  }, [])

  const openConversation = useCallback(async (id: string) => {
    setActiveId(id)
    activeRef.current = id
    lastOpened = id
    setShowVoiceConv(false)
    const res = await api.get(`/api/conversations/${id}`)
    setMessages(res.messages)
    setBusy(Boolean(res.busy))
    setAgentChoice(res.agent || 'auto')
  }, [])

  const openVoiceConversation = useCallback(async () => {
    const res = await api.get('/api/conversations/voice')
    setActiveId(res.id)
    activeRef.current = res.id
    lastOpened = res.id
    setShowVoiceConv(true)
    setMessages(res.messages)
    setBusy(Boolean(res.busy))
    // un fil vocal tout juste créé (ou vidé) n'a pas de « dernier échange » à annoncer
    setLastVoiceAt(res.messages?.length ? res.updated_at || null : null)
  }, [])

  /** Nouvelle conversation = brouillon local. Rien n'est écrit en base tant qu'aucun message
   *  n'est envoyé : trois clics exploratoires n'ajoutent plus trois coquilles vides à la liste. */
  const newConversation = useCallback(() => {
    lastOpened = null
    activeRef.current = null
    setActiveId(null)
    setShowVoiceConv(false)
    setMessages([])
    setBusy(false)
    setAgentChoice('auto')
    if (archivesRef.current) {
      // on revient à la liste courante, sinon le brouillon apparaîtrait au milieu des archives
      archivesRef.current = false
      setShowArchives(false)
      loadConversations().catch(() => undefined)
    }
    textareaRef.current?.focus()
  }, [loadConversations])

  const toggleList = useCallback(() => {
    setListOpen((v) => {
      const next = !v
      try {
        localStorage.setItem('iris.convlist', next ? '1' : '0')
      } catch {
        /* stockage indisponible : le choix vaut pour cette session seulement */
      }
      return next
    })
  }, [])

  const toggleArchives = useCallback(async () => {
    archivesRef.current = !archivesRef.current
    setShowArchives(archivesRef.current)
    setFiltre('')
    await loadConversations().catch(() => undefined)
  }, [loadConversations])

  useEffect(() => {
    loadConversations()
      .then((list) => {
        // au lancement : fil neuf. Au retour d'une autre vue : on retrouve son fil.
        if (lastOpened && list.some((c) => c.id === lastOpened)) openConversation(lastOpened)
      })
      .catch(() => undefined)
    loadVoiceMeta()
  }, [loadConversations, loadVoiceMeta, openConversation])

  useEffect(() => {
    // Fil vide : on ne descend pas. Sinon l'écran d'accueil (« Dites « Dis-moi Iris »… »
    // et les exemples) s'ouvre déjà défilé, titre coupé en haut.
    if (!messages.length) return
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  // Ctrl+F met le curseur dans la recherche : ChatView n'est monté que sur la vue Conversations.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
        e.preventDefault()
        if (!listOpen) toggleList()
        rechercheRef.current?.focus()
        rechercheRef.current?.select()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [listOpen, toggleList])

  useEffect(() => {
    return api.on((event: IrisEvent) => {
      if (event.type === 'voice.transcript' && event.text) setLastTranscript(event.text)
      if (event.type === 'voice.heard' && event.text) setLastTranscript(`Entendu : ${event.text}`)
      if (event.type === 'voice.reply') {
        setLastLatency(event.seconds)
        setLastVoiceAt(new Date().toISOString())
      }
      // Une panne d'écoute efface la dernière phrase entendue : la garder laisserait croire
      // que le micro fonctionne encore.
      if (event.type === 'voice.state' && event.state === 'off' && event.error) setLastTranscript('')
      // Dès que le mot d'activation est reconnu, on montre le fil vocal : la transcription,
      // l'outil exécuté et la réponse s'affichent en direct, sans clic. On ne vole jamais le fil
      // si une réponse écrite est en cours ou si l'utilisateur est en train de taper.
      if (event.type === 'voice.state' && event.state === 'command' && !voiceOpenRef.current && !busyRef.current && !inputRef.current.trim()) {
        openVoiceConversation().catch(() => undefined)
      }
      if (event.type === 'conversation.created' || event.type === 'conversation.updated' || event.type === 'conversation.deleted') {
        loadConversations().catch(() => undefined)
      }
      if (!event.conversation_id || event.conversation_id !== activeRef.current) return
      switch (event.type) {
        case 'chat.user_message':
          setMessages((m) => (m.some((x) => x.id === event.message.id) ? m : [...m, event.message]))
          break
        case 'chat.started':
          setBusy(true)
          setMessages((m) => [
            ...m,
            { id: event.message_id, role: 'assistant', text: '', images: [], agent: event.agent, model: event.model, meta: { reason: event.reason }, created_at: new Date().toISOString(), streaming: true, thinking: '', tools: [], infos: [] }
          ])
          break
        case 'chat.delta':
          setMessages((m) => m.map((x) => (x.id === event.message_id ? { ...x, text: x.text + event.text } : x)))
          break
        case 'chat.thinking':
          setMessages((m) => m.map((x) => (x.id === event.message_id ? { ...x, thinking: (x.thinking || '') + event.text } : x)))
          break
        case 'chat.info':
          setMessages((m) => m.map((x) => (x.id === event.message_id ? { ...x, infos: [...(x.infos || []), event.text] } : x)))
          break
        case 'chat.tool':
          setMessages((m) =>
            m.map((x) => {
              if (x.id !== event.message_id) return x
              const tools = [...(x.tools || [])]
              const idx = tools.findIndex((t) => t.id === event.tool.id)
              if (idx >= 0) tools[idx] = event.tool
              else tools.push(event.tool)
              return { ...x, tools }
            })
          )
          break
        case 'chat.done':
          setBusy(false)
          setMessages((m) => {
            const exists = m.some((x) => x.id === event.message.id)
            const merged = { ...event.message, tools: event.message.meta?.tools, thinking: event.message.meta?.thinking }
            return exists ? m.map((x) => (x.id === event.message.id ? { ...x, ...merged, streaming: false } : x)) : [...m, merged]
          })
          break
        case 'chat.error':
          setBusy(false)
          setMessages((m) => m.map((x) => (x.streaming ? { ...x, streaming: false, meta: { ...x.meta, error: event.message } } : x)))
          if (!event.code) toast(event.message, 'error')
          break
        case 'chat.consent_required':
          setBusy(false)
          break
        default:
          break
      }
    })
  }, [loadConversations, openVoiceConversation, toast])

  /** `override` permet d'envoyer une phrase d'exemple sans passer par l'état `input`
   *  (qui serait périmé dans la fermeture du gestionnaire de clic). */
  const send = useCallback(
    async (override?: string) => {
      const text = (override ?? input).trim()
      if ((!text && attachments.length === 0) || busy) return
      let convId = activeId
      if (!convId) {
        const conv = await api.post('/api/conversations', { agent: agentChoice })
        convId = conv.id
        // le filtre d'événements lit cette référence, pas l'état React : sans cette ligne
        // le tout premier flux de réponse serait jeté.
        activeRef.current = conv.id
        lastOpened = conv.id
        setActiveId(conv.id)
        await loadConversations()
      }
      if (!consent.transcript?.granted && !settings?.local_only) {
        const target = agentChoice === 'auto' ? readyAgents[0]?.name : agentChoice
        const cfg = agents.find((a) => a.name === target)
        if (!cfg?.local) {
          // le backend renverra chat.consent_required ; on laisse la porte de consentement décider
        }
      }
      setBusy(true)
      const ok = api.send({ type: 'chat.send', conversation_id: convId, text, images: attachments.map((a) => ({ media_type: a.media_type, data: a.data })), agent: agentChoice })
      if (!ok) {
        try {
          await api.post(`/api/conversations/${convId}/messages`, { text, images: attachments.map((a) => ({ media_type: a.media_type, data: a.data })), agent: agentChoice })
        } catch (err) {
          setBusy(false)
          toast(String((err as Error).message), 'error')
          return
        }
      }
      setInput('')
      setAttachments([])
    },
    [activeId, agentChoice, agents, attachments, busy, consent, input, loadConversations, readyAgents, settings, toast]
  )

  const cancel = useCallback(() => {
    if (activeId) api.send({ type: 'chat.cancel', conversation_id: activeId })
  }, [activeId])

  const attachImage = useCallback(async () => {
    try {
      const img = await window.iris.pickImage()
      if (img) setAttachments((a) => [...a, img])
    } catch (err) {
      toast(String((err as Error).message), 'error')
    }
  }, [toast])

  const attachScreenshot = useCallback(async () => {
    try {
      const shot = await api.post('/api/system/screenshot')
      setAttachments((a) => [...a, { name: 'capture.jpg', media_type: shot.media_type, data: shot.data }])
    } catch (err) {
      toast(String((err as Error).message), 'error')
    }
  }, [toast])

  /** Ranger plutôt que détruire : rien n'est effacé, la conversation reste consultable. */
  const setArchived = useCallback(
    async (id: string, archived: boolean) => {
      await api.patch(`/api/conversations/${id}`, { archived })
      const list = await loadConversations()
      if (activeRef.current === id) {
        lastOpened = null
        activeRef.current = null
        setActiveId(null)
        setMessages([])
        setBusy(false)
      }
      return list
    },
    [loadConversations]
  )

  const deleteConversation = useCallback(
    async (conv: Conversation) => {
      const ok = window.confirm(
        `Supprimer définitivement « ${conv.title} » ?\nCette conversation et ses messages seront effacés. Pour simplement la ranger, utilisez Archiver.`
      )
      if (!ok) return
      await api.delete(`/api/conversations/${conv.id}`)
      await loadConversations()
      if (activeRef.current === conv.id) {
        lastOpened = null
        activeRef.current = null
        setActiveId(null)
        setMessages([])
        setBusy(false)
      }
    },
    [loadConversations]
  )

  const renameConversation = useCallback(
    async (conv: Conversation) => {
      const title = window.prompt('Nouveau titre', conv.title)
      if (title && title.trim()) {
        await api.patch(`/api/conversations/${conv.id}`, { title: title.trim() })
        loadConversations()
      }
    },
    [loadConversations]
  )

  const active = conversations.find((c) => c.id === activeId)
  const voiceState: string = voice?.state || 'off'
  const mot = settings?.wake_word || 'Dis-moi Iris'
  const voiceLabel: Record<string, string> = {
    off: voice?.muted ? 'Micro coupé (muet)' : voice?.paused_until ? 'Écoute en pause (reprise automatique)' : 'Écoute arrêtée',
    wake: settings?.wake_word ? `Prête — dites « ${settings.wake_word} »` : 'Prête à vous écouter',
    armed: 'Mot d’activation détecté…',
    command: 'Je vous écoute',
    processing: 'IRIS réfléchit…',
    speaking: 'IRIS parle'
  }

  // Conversations visibles : filtre de recherche appliqué sur les titres déjà chargés
  // (aucun message n'est déchiffré côté interface).
  const visibles = useMemo(() => {
    const q = filtre.trim().toLowerCase()
    if (!q) return conversations
    return conversations.filter((c) => c.title.toLowerCase().includes(q))
  }, [conversations, filtre])

  // Le backend renvoie déjà les conversations triées (updated_at DESC) : il suffit de partitionner.
  const groupes = useMemo(() => {
    const out: { seau: string; items: Conversation[] }[] = []
    for (const c of visibles) {
      const seau = seauDe(c.updated_at)
      if (!out.length || out[out.length - 1].seau !== seau) out.push({ seau, items: [] })
      out[out.length - 1].items.push(c)
    }
    return out
  }, [visibles])

  // L'envoi n'est bloqué que si le texte doit partir vers une IA externe : les IA locales
  // sont exemptées par ConsentGate.check.
  const consentBloque = useMemo(() => {
    if (!Object.keys(consent).length) return false
    if (settings?.local_only || consent.transcript?.granted) return false
    if (agentChoice === 'auto') return readyAgents.some((a) => !a.local)
    return !agents.find((a) => a.name === agentChoice)?.local
  }, [agentChoice, agents, consent, readyAgents, settings])

  // Une panne d'écoute doit se lire, et se réparer, sans quitter l'écran. On n'affiche l'erreur
  // que si l'écoute est réellement arrêtée et qu'il ne s'agit pas d'une pause volontaire.
  const voiceError: string = voiceState === 'off' && !voice?.paused_until ? voice?.error || '' : ''
  const remede = !voiceError
    ? null
    : settings?.privacy_mode
      ? {
          label: 'Quitter le mode confidentiel',
          run: async () => {
            await updateSettings({ privacy_mode: false })
            api.send({ type: 'voice.start' })
          }
        }
      : voice?.muted
        ? { label: 'Réactiver le micro', run: async () => void api.send({ type: 'voice.toggle_mute' }) }
        : voice?.model_ready === false
          ? {
              label: dlModel ? 'Téléchargement…' : 'Télécharger le modèle',
              run: async () => {
                setDlModel(true)
                try {
                  await api.post('/api/voice/model/download', {})
                } catch (err) {
                  toast(String((err as Error).message), 'error')
                } finally {
                  setDlModel(false)
                }
              }
            }
          : { label: 'Ouvrir les réglages voix', run: async () => setView('settings') }

  return (
    <div className={`chat ${listOpen ? '' : 'solo'}`} style={listOpen ? undefined : { gridTemplateColumns: '1fr' }}>
      {listOpen ? (
        <div className="conv-list">
          <div className="head">
            <button className="btn primary sm" onClick={newConversation}>+ Nouvelle conversation</button>
          </div>
          <div className="search" style={{ padding: '0 14px 10px' }}>
            <input
              ref={rechercheRef}
              className="input"
              type="text"
              style={{ padding: '6px 10px', fontSize: 12.5 }}
              placeholder="Rechercher une conversation (Ctrl+F)"
              value={filtre}
              onChange={(e) => setFiltre(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  e.preventDefault()
                  setFiltre('')
                  e.currentTarget.blur()
                }
              }}
            />
          </div>

          {!showArchives ? (
            <div className="conv-pinned" style={{ padding: '0 8px 10px', marginBottom: 6, borderBottom: '1px solid var(--border)' }}>
              <div
                className={`conv-item pinned ${showVoiceConv ? 'active' : ''}`}
                style={{ background: 'var(--panel)', border: '1px solid var(--border)' }}
                title="Tout ce que vous dites à IRIS arrive ici, dans un seul fil continu"
                onClick={openVoiceConversation}
              >
                <div className="t" style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600 }}>
                  <MicOrb state={voiceState} muted={!!voice?.muted} speaking={!!ttsSpeaking} />
                  <span>Échanges vocaux</span>
                </div>
                <div className="m">
                  <span>{lastVoiceAt ? `dernier échange ${formatQuand(lastVoiceAt)}` : `en attente de « ${mot} »`}</span>
                </div>
              </div>
            </div>
          ) : null}

          <div className="items">
            {!showArchives ? <div className="conv-group" style={STYLE_GROUPE}>Conversations écrites</div> : null}

            {!showArchives && activeId === null && !showVoiceConv ? (
              <div className="conv-item active">
                <div className="t">Nouvelle conversation</div>
                <div className="m">
                  <span>brouillon · enregistrée au premier message</span>
                </div>
              </div>
            ) : null}

            {conversations.length === 0 ? (
              <div className="empty small">
                {showArchives ? 'Aucune conversation archivée. Rien n’est supprimé sans que vous le demandiez.' : <>Aucune conversation écrite.<br />Vos commandes dites à voix haute sont dans « Échanges vocaux », ci-dessus.</>}
              </div>
            ) : null}
            {conversations.length > 0 && visibles.length === 0 ? (
              <div className="empty small">Aucun résultat pour «&nbsp;{filtre.trim()}&nbsp;».</div>
            ) : null}

            {groupes.map((g) => (
              <React.Fragment key={g.seau}>
                <div className="conv-group" style={STYLE_GROUPE}>{g.seau}</div>
                {g.items.map((c) => (
                  <div
                    key={c.id}
                    className={`conv-item ${c.id === activeId && !showVoiceConv ? 'active' : ''}`}
                    onClick={() => openConversation(c.id)}
                    onDoubleClick={() => renameConversation(c)}
                  >
                    <div className="t">{c.title}</div>
                    <div className="m">
                      {c.agent && c.agent !== 'auto' ? <span>{AGENT_LABEL[c.agent] || c.agent}</span> : null}
                      <span>{formatQuand(c.updated_at)}</span>
                      {c.busy ? <span style={{ color: 'var(--accent-2)' }}>…</span> : null}
                      <span className="row-actions" style={{ marginLeft: 'auto', display: 'flex', gap: 2 }}>
                        {showArchives ? (
                          <button
                            className="btn ghost sm"
                            style={{ padding: '0 6px' }}
                            title="Remettre dans les conversations"
                            onClick={(e) => { e.stopPropagation(); setArchived(c.id, false) }}
                          >Restaurer</button>
                        ) : (
                          <button
                            className="btn ghost sm"
                            style={{ padding: '0 6px' }}
                            title="Ranger cette conversation — rien n’est effacé"
                            onClick={(e) => { e.stopPropagation(); setArchived(c.id, true) }}
                          >Archiver</button>
                        )}
                        <button
                          className="btn ghost sm del"
                          style={{ padding: '0 6px' }}
                          title={`Supprimer définitivement « ${c.title} »`}
                          aria-label={`Supprimer la conversation ${c.title}`}
                          onClick={(e) => { e.stopPropagation(); deleteConversation(c) }}
                        >×</button>
                      </span>
                    </div>
                  </div>
                ))}
              </React.Fragment>
            ))}
          </div>

          <div className="conv-foot" style={{ padding: '8px 12px 12px', borderTop: '1px solid var(--border)' }}>
            <button className="btn ghost sm" onClick={toggleArchives}>
              {showArchives ? '← Conversations' : `Archives${archivedCount ? ` (${archivedCount})` : ''}`}
            </button>
          </div>
        </div>
      ) : null}

      <div className="thread">
        <div className="topbar">
          <button
            className="btn ghost sm"
            aria-expanded={listOpen}
            title={listOpen ? 'Masquer la liste des conversations' : 'Afficher la liste des conversations'}
            onClick={toggleList}
          >{listOpen ? '‹ Masquer la liste' : '☰ Conversations'}</button>
          {!listOpen ? (
            <>
              <button className="btn primary sm" onClick={newConversation}>+ Nouvelle</button>
              <button className={`btn sm ${showVoiceConv ? 'primary' : ''}`} title="Tout ce que vous dites à IRIS arrive ici" onClick={openVoiceConversation}>🎙 Échanges vocaux</button>
            </>
          ) : null}
          <div className="title">{showVoiceConv ? 'Échanges vocaux' : active?.title || 'Nouvelle conversation'}</div>
          {/* Aucun sélecteur de modèle : le forfait décide quelle IA répond, et le relais VELA
              l'applique. Choisir entre des noms de modèles n'a jamais aidé personne à formuler
              sa demande. On affiche seulement ce à quoi le forfait donne droit. */}
          {plan ? <span className="pill" title={`Le modèle est choisi selon votre forfait ${plan.label}.`}>{plan.label}</span> : null}
          {showVoiceConv && activeId ? <button className="btn ghost sm" title="Efface toutes vos commandes vocales passées. Sans effet sur vos conversations écrites." onClick={async () => { if (window.confirm('Effacer tout l’historique de vos commandes vocales ?')) { await api.delete(`/api/conversations/${activeId}`); openVoiceConversation() } }}>Vider l’historique</button> : null}
        </div>

        <div className="messages" ref={listRef}>
          {messages.length === 0 ? (
            <div className="empty">
              <div style={{ display: 'inline-block', textAlign: 'left', maxWidth: 480 }}>
                <div style={{ fontSize: 17, color: 'var(--text)', fontWeight: 600 }}>Dites « {mot} », ou choisissez un exemple.</div>
                <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {SUGGESTIONS.map((s) =>
                    showVoiceConv ? (
                      <div className="small" key={s.phrase} style={{ lineHeight: 1.7 }}>« {s.phrase} »</div>
                    ) : (
                      <button
                        key={s.phrase}
                        className="btn sm"
                        style={STYLE_EXEMPLE}
                        disabled={busy}
                        title={s.local ? 'Envoyer cette demande maintenant : IRIS l’exécute elle-même, sans passer par une IA' : 'Mettre cette phrase dans la zone d’écriture'}
                        onClick={() => {
                          if (s.local) send(s.phrase)
                          else {
                            setInput(s.phrase)
                            textareaRef.current?.focus()
                          }
                        }}
                      >
                        <span style={{ fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--muted)' }}>{s.verbe}</span>
                        <span style={{ color: 'var(--text-2)' }}>« {s.phrase} »</span>
                      </button>
                    )
                  )}
                </div>
                <div className="small muted" style={{ marginTop: 12, lineHeight: 1.55 }}>
                  {showVoiceConv
                    ? 'Les trois premiers, IRIS les exécute elle-même, sans passer par une IA.'
                    : 'Les trois premiers, IRIS les exécute elle-même, sans passer par une IA. Les autres remplissent la zone d’écriture : vous validez avant l’envoi.'}
                </div>
              </div>
            </div>
          ) : null}
          {messages.map((m) => (
            <MessageBubble key={m.id} m={m} />
          ))}
        </div>

        {/* La voix passe AVANT le clavier : c'est la conduite principale du produit, le composeur
            est le repli. */}
        <div
          className={`voice-bar vb-${voiceState}`}
          data-state={voice?.muted ? 'muted' : ttsSpeaking || voiceState === 'speaking' ? 'speaking' : voiceState}
          style={{ flexWrap: 'wrap', rowGap: 8 }}
        >
          <div className="state">
            <MicOrb state={voiceState} muted={!!voice?.muted} speaking={!!ttsSpeaking} />
            <span className="label" aria-live="polite">{voiceLabel[voiceState] || voiceState}</span>
          </div>
          <LevelMeter peak={micLevel && Date.now() - micLevel.at < 2500 ? micLevel.peak : 0} active={voiceState === 'command'} />
          <div className="transcript" style={voiceError ? { color: 'var(--danger)' } : undefined}>
            {voiceError ? `⚠ ${voiceError}` : lastTranscript ? `« ${lastTranscript} »` : ''}
          </div>
          {remede ? (
            <button
              className="btn primary sm"
              disabled={dlModel}
              onClick={() => { remede.run().catch((err) => toast(String((err as Error).message), 'error')) }}
            >{remede.label}</button>
          ) : null}
          {lastLatency !== null && !voiceError ? <span className="pill">{lastLatency}s</span> : null}
          <div className="ctrls" style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 'none' }}>
            {ttsSpeaking ? <button className="btn danger sm" title="Ou dites « stop »" onClick={() => api.send({ type: 'tts.stop' })}>■ Stop</button> : null}
            <button
              className={`btn sm ${voice?.muted ? 'danger' : 'ghost'}`}
              title="Couper ou réactiver le micro (Ctrl+Maj+M, ou dites « muet »)"
              onClick={() => api.send({ type: 'voice.toggle_mute' })}
            >{voice?.muted ? '🔴 Réactiver le micro' : '🔇 Couper le micro'}</button>
            <button
              className={`btn sm ${voiceState === 'off' ? '' : 'ghost'}`}
              title={voiceState === 'off' ? 'Reprendre l’écoute du mot d’activation' : 'Pause de 10 minutes, puis l’écoute reprend seule (pour couper le micro : Couper le micro)'}
              onClick={() => api.send({ type: voiceState === 'off' ? 'voice.start' : 'voice.pause', minutes: 10 })}
            >
              {voiceState === 'off' ? (voice?.paused_until ? '▶ Reprendre l’écoute' : '▶ Démarrer l’écoute') : '⏸ Pause 10 min'}
            </button>
            {/* Le geste de secours de la démonstration : il fonctionne même micro coupé ou écoute en pause. */}
            <button
              className="btn primary"
              title="Parler tout de suite, sans le mot d’activation (Ctrl+Maj+Espace) — fonctionne même micro coupé ou écoute en pause"
              onClick={() => api.send({ type: 'voice.push_to_talk' })}
            >
              🎙 Parler maintenant <kbd style={{ color: 'inherit', background: 'rgba(27,20,14,0.22)', borderColor: 'rgba(27,20,14,0.34)' }}>Ctrl+Maj+Espace</kbd>
            </button>
          </div>
        </div>

        {!showVoiceConv ? (
          <div className="composer">
            {attachments.length ? (
              <div className="attachments">
                {attachments.map((a, i) => (
                  <div className="att" key={i}>
                    <img src={`data:${a.media_type};base64,${a.data}`} alt={a.name} />
                    <button onClick={() => setAttachments((list) => list.filter((_, j) => j !== i))}>×</button>
                  </div>
                ))}
              </div>
            ) : null}
            <div className="box">
              <button className="btn ghost icon" title="Joindre une image" onClick={attachImage}>🖼</button>
              <button className="btn ghost icon" title="Joindre une capture d’écran" onClick={attachScreenshot}>⌗</button>
              <textarea
                ref={textareaRef}
                rows={1}
                placeholder={busy ? 'IRIS répond…' : 'Écrivez à IRIS… (Entrée pour envoyer, Maj+Entrée pour une nouvelle ligne)'}
                value={input}
                onChange={(e) => { setInput(e.target.value); e.target.style.height = 'auto'; e.target.style.height = Math.min(e.target.scrollHeight, 200) + 'px' }}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
              />
              {busy ? (
                <button className="btn danger sm" onClick={cancel}>Stop</button>
              ) : (
                <button className="btn primary sm" onClick={() => send()} disabled={!input.trim() && attachments.length === 0}>Envoyer</button>
              )}
            </div>
            <div className="bar">
              <span>{agentChoice === 'auto' ? 'IRIS choisit l’IA la mieux placée' : `IA : ${AGENT_LABEL[agentChoice] || agentChoice}`}</span>
              {settings?.local_only ? <span className="pill ok">100 % local</span> : null}
              {consentBloque ? (
                <button
                  type="button"
                  className="pill warn"
                  style={{ cursor: 'pointer' }}
                  title="Sans cette autorisation, IRIS ne peut pas envoyer votre demande à une IA externe. Ouvre Confidentialité."
                  onClick={() => setView('privacy')}
                >Envoi du texte non autorisé — cliquez pour autoriser</button>
              ) : null}
            </div>
          </div>
        ) : (
          <div className="composer">
            <div className="bar">
              <span>Ce fil enregistre tout ce que vous dites à IRIS.</span>
              <button className="btn ghost sm" onClick={newConversation}>Écrire à IRIS</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function MessageBubble({ m }: { m: Message }): JSX.Element {
  const isUser = m.role === 'user'
  const error = m.meta?.error
  const reason = m.meta?.reason
  return (
    <div className={`msg ${isUser ? 'user' : ''}`}>
      <div className="who">
        <span>{isUser ? 'Vous' : AGENT_LABEL[m.agent || ''] || m.agent || 'IRIS'}</span>
        {m.model ? <span className="mono">{m.model}</span> : null}
        <span>{formatTime(m.created_at)}</span>
        {m.meta?.source === 'voice' ? <span className="pill">voix</span> : null}
        {reason && !isUser ? <span title="Pourquoi cette IA">· {reason}</span> : null}
        {m.meta?.cancelled ? <span className="pill warn">interrompu</span> : null}
      </div>
      {m.images?.length ? (
        <div className="images">
          {m.images.map((img, i) => (img.data ? <img key={i} src={`data:${img.media_type};base64,${img.data}`} alt="" /> : null))}
        </div>
      ) : null}
      {m.thinking ? (
        <details className="thinking">
          <summary>Raisonnement</summary>
          {m.thinking}
        </details>
      ) : null}
      {m.tools?.map((t) => (
        <div className="tool" key={t.id}>
          <div className="h">
            <span className={`dot ${t.status === 'running' ? 'rec' : t.status === 'done' ? 'on' : ''}`} style={t.status === 'error' ? { background: 'var(--danger)' } : {}} />
            <span className="name">{t.name}</span>
            <span className="muted small">{summarizeInput(t.input)}</span>
          </div>
          {t.result ? <pre>{t.result}</pre> : null}
        </div>
      ))}
      {m.infos?.map((line, i) => (
        <div className="info-line" key={i}>{line}</div>
      ))}
      {m.text || (!m.streaming && !error) ? (
        <div className="bubble">{isUser ? <div style={{ whiteSpace: 'pre-wrap' }}>{m.text}</div> : <Markdown text={m.text || (m.streaming ? '' : 'IRIS n’a rien répondu. Reformulez votre demande.')} />}</div>
      ) : null}
      {m.streaming && !m.text ? <div className="info-line">IRIS réfléchit…</div> : null}
      {error ? <div className="bubble err">{error}</div> : null}
    </div>
  )
}

function summarizeInput(input: Record<string, unknown>): string {
  if (!input) return ''
  const entries = Object.entries(input)
  if (!entries.length) return ''
  return entries
    .map(([k, v]) => {
      const s = typeof v === 'string' ? v : JSON.stringify(v)
      return `${k}: ${s.length > 80 ? s.slice(0, 80) + '…' : s}`
    })
    .join(' · ')
}


/** Pastille d'écoute. L'état vocal est l'information la plus importante de l'application : il doit
 *  se lire d'un coup d'œil. Les classes historiques (`listening`, `talking`, `muted`) sont
 *  conservées pour que l'apparence actuelle tienne, et une classe fine s'y ajoute
 *  (`wake`, `hearing`, `thinking`) pour distinguer les quatre états à la caméra. */
function MicOrb({ state, muted, speaking }: { state: string; muted: boolean; speaking: boolean }): JSX.Element {
  const cls = muted
    ? 'muted'
    : speaking || state === 'speaking'
      ? 'talking'
      : state === 'off'
        ? 'idle'
        : state === 'processing'
          ? 'listening thinking'
          : state === 'command' || state === 'armed'
            ? 'listening hearing'
            : 'listening wake'
  const titre = muted
    ? 'Micro coupé'
    : speaking || state === 'speaking'
      ? 'IRIS parle'
      : state === 'off'
        ? 'Écoute arrêtée'
        : state === 'processing'
          ? 'IRIS réfléchit'
          : state === 'command' || state === 'armed'
            ? 'IRIS vous écoute'
            : 'IRIS est prête, dites le mot d’activation'
  return (
    <span className={`mic-orb ${cls}`} title={titre} aria-label={titre} role="img">
      <i />
      <b />
    </span>
  )
}

/** Niveau du micro en direct : permet de voir immédiatement si le micro capte trop faiblement,
 *  la première cause de commandes mal comprises. */
function LevelMeter({ peak, active }: { peak: number; active: boolean }): JSX.Element | null {
  if (!active && !peak) return null
  const barres = 5
  const ratio = Math.min(1, peak / 9000)
  const allumees = Math.round(ratio * barres)
  return (
    <span className="level" title={`Niveau du micro : ${peak} sur 32767`}>
      {Array.from({ length: barres }, (_, i) => (
        <span
          key={i}
          className={i < allumees ? (peak > 22000 ? 'hot' : 'lit') : ''}
          style={{ height: 3 + (i + 1) * 3 }}
        />
      ))}
    </span>
  )
}
