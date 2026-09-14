import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BtnIcone, Feuille, Holo, Option, Segmente } from '../components/ui'
import { IcoCapture, IcoChevronBas, IcoEnvoyer, IcoImage, IcoListeChat, IcoNouveauChat, IcoRobotDegrade, IcoStop, IcoTraduire } from '../components/icons'
import { api, formatDate, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import { Bulle } from './ia/Bulle'
import { BarreVoix } from './ia/BarreVoix'
import { Favoris } from './ia/Favoris'
import { Minuteur } from './ia/Minuteur'
import { CLE_OUVRIR, OUVRIR_NOUVELLE, OUVRIR_VOIX, SUGGESTIONS, labelMoteurPublic, messageErreur, session, type Conversation, type Message, type PieceJointe } from './ia/commun'
import './IaScreen.css'

/* =========================================================================
   Onglet IA (racine) — le cœur de l'application. Trois segments :
   - Discussion : le fil avec IRIS (port complet de l'ancienne ChatView :
     conversations, envoi, annulation, flux d'événements, pièces jointes,
     fil vocal, barre vocale, remèdes, masque de marque) ;
   - Favoris : les messages étoilés ;
   - Minuteur : les rappels.

   Lunettes d'abord (2026-09-13) : sans lunettes présentes (GET /api/lunettes/presence),
   le chat écrit n'est qu'un APERÇU compté par le service (ChatService._verrou_lunettes_chat).
   Un bandeau dit combien de messages restent, avec « Connecter » et « Acheter » ; à zéro,
   le composeur laisse la place à l'invitation au lieu d'envoyer une demande que le service
   refuserait. La voix, elle, n'a pas d'aperçu (BarreVoix le dit). Le compteur se relit
   après chaque réponse, car le service ne publie pas sa consommation.
   ========================================================================= */

const URL_ACHAT_DEFAUT = 'https://velaglass.ca/lunettes.html'

type Segment = 'discussion' | 'favoris' | 'minuteur'
const CLE_SEGMENT = 'iris.ia.segment'
const SEGMENTS: { id: Segment; label: string }[] = [
  { id: 'discussion', label: 'Discussion' },
  { id: 'favoris', label: 'Favoris' },
  { id: 'minuteur', label: 'Minuteur' }
]

function lireSegment(): Segment {
  try {
    const v = window.localStorage.getItem(CLE_SEGMENT)
    return v === 'favoris' || v === 'minuteur' ? v : 'discussion'
  } catch {
    return 'discussion'
  }
}

export function IaScreen(): JSX.Element {
  const { nav, settings, updateSettings, personas, toast, agents, consent, status, lunettes, presence, rafraichirPresence, exigerLunettes, demanderLunettes } = useStore()
  const [segment, setSegmentEtat] = useState<Segment>(lireSegment)
  const [rolesOuvert, setRolesOuvert] = useState(false)

  /* ---------------------------------------------------------------- état de la discussion */
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<PieceJointe[]>([])
  const [agentChoice, setAgentChoice] = useState('auto')
  const [busy, setBusy] = useState(false)
  const [lastTranscript, setLastTranscript] = useState('')
  const [lastLatency, setLastLatency] = useState<number | null>(null)
  const [showVoiceConv, setShowVoiceConv] = useState(false)
  const [lastVoiceAt, setLastVoiceAt] = useState<string | null>(null)

  const filRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  // L'abonnement WebSocket est monté une seule fois : sans ces références il verrait
  // éternellement les valeurs du premier rendu.
  const activeRef = useRef<string | null>(null)
  activeRef.current = activeId
  const busyRef = useRef(false)
  busyRef.current = busy
  const inputRef = useRef('')
  inputRef.current = input
  const voiceOpenRef = useRef(false)
  voiceOpenRef.current = showVoiceConv

  const setSegment = useCallback((s: Segment) => {
    setSegmentEtat(s)
    try {
      window.localStorage.setItem(CLE_SEGMENT, s)
    } catch {
      /* stockage indisponible : le choix vaut pour cette session seulement */
    }
  }, [])

  const readyAgents = useMemo(() => agents.filter((a) => a.ready), [agents])

  const loadConversations = useCallback(async () => {
    const res = await api.get('/api/conversations')
    const liste: Conversation[] = res.conversations || []
    setConversations(liste)
    return liste
  }, [])

  /** Horodatage du fil vocal, sans charger ses messages (il grossit à vie). */
  const loadVoiceMeta = useCallback(async () => {
    try {
      const res = await api.get('/api/conversations?kind=voice')
      const conv = res.conversations?.[0]
      if (conv) setLastVoiceAt(conv.updated_at)
    } catch {
      /* le fil vocal n'existe pas encore */
    }
  }, [])

  /** On attend la réponse du service AVANT de changer de fil : si la conversation n'existe
   *  plus (favori d'une discussion supprimée, identifiant périmé), l'état reste cohérent au
   *  lieu de pointer sur un identifiant invalide avec les messages du fil précédent. */
  const openConversation = useCallback(async (id: string) => {
    const res = await api.get(`/api/conversations/${id}`)
    // Un favori pris dans le fil vocal pointe sur ce fil : on l'affiche comme tel (en-tête,
    // composeur remplacé), pas comme une conversation écrite où l'on pourrait taper.
    const voix = res.kind === 'voice'
    setActiveId(id)
    activeRef.current = id
    session.lastOpened = id
    session.lastOpenedVoice = voix
    setShowVoiceConv(voix)
    setMessages(res.messages || [])
    setBusy(Boolean(res.busy))
    setAgentChoice(res.agent || 'auto')
  }, [])

  const openVoiceConversation = useCallback(async () => {
    const res = await api.get('/api/conversations/voice')
    setActiveId(res.id)
    activeRef.current = res.id
    session.lastOpened = res.id
    session.lastOpenedVoice = true
    setShowVoiceConv(true)
    setMessages(res.messages || [])
    setBusy(Boolean(res.busy))
    // un fil vocal tout juste créé (ou vidé) n'a pas de « dernier échange » à annoncer
    setLastVoiceAt(res.messages?.length ? res.updated_at || null : null)
  }, [])

  /** Nouvelle conversation = brouillon local. Rien n'est écrit en base tant qu'aucun message
   *  n'est envoyé : trois clics exploratoires n'ajoutent pas trois coquilles vides à la liste. */
  const newConversation = useCallback(() => {
    session.lastOpened = null
    session.lastOpenedVoice = false
    activeRef.current = null
    setActiveId(null)
    setShowVoiceConv(false)
    setMessages([])
    setBusy(false)
    setAgentChoice('auto')
    setSegment('discussion')
    window.setTimeout(() => textareaRef.current?.focus(), 0)
  }, [setSegment])

  /* ---------------------------------------------------------------- montage : quoi ouvrir ? */
  useEffect(() => {
    let demande: string | null = null
    try {
      demande = window.sessionStorage.getItem(CLE_OUVRIR)
      if (demande) window.sessionStorage.removeItem(CLE_OUVRIR)
    } catch {
      demande = null
    }
    loadConversations()
      .then((liste) => {
        if (demande === OUVRIR_VOIX) {
          setSegment('discussion')
          return openVoiceConversation()
        }
        if (demande === OUVRIR_NOUVELLE) {
          newConversation()
          return undefined
        }
        if (demande) {
          setSegment('discussion')
          return openConversation(demande).catch(() => toast('Cette conversation n’existe plus.', 'error'))
        }
        // au lancement : fil neuf. Au retour d'un autre écran : on retrouve son fil.
        if (session.lastOpenedVoice) return openVoiceConversation()
        if (session.lastOpened && liste.some((c) => c.id === session.lastOpened)) return openConversation(session.lastOpened)
        session.lastOpened = null
        return undefined
      })
      .catch(() => undefined)
    loadVoiceMeta().catch(() => undefined)
    // volontairement au montage seulement
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /* ---------------------------------------------------------------- défilement automatique */
  useEffect(() => {
    if (!messages.length) return
    const el = filRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  // Ctrl+F : ouvre la liste des discussions (où vit la recherche).
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
        e.preventDefault()
        nav.ouvrir('discussions')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [nav])

  // la zone d'écriture reprend sa hauteur d'une ligne une fois vidée
  useEffect(() => {
    if (input === '' && textareaRef.current) textareaRef.current.style.height = 'auto'
  }, [input])

  /* ---------------------------------------------------------------- événements du service */
  useEffect(() => {
    return api.on((event: IrisEvent) => {
      if (event.type === 'voice.transcript' && event.text) setLastTranscript(event.text)
      if (event.type === 'voice.heard' && event.text) setLastTranscript(`Entendu : ${event.text}`)
      if (event.type === 'voice.reply') {
        setLastLatency(typeof event.seconds === 'number' ? event.seconds : null)
        setLastVoiceAt(new Date().toISOString())
      }
      // Une panne d'écoute efface la dernière phrase entendue : la garder laisserait croire
      // que le micro fonctionne encore.
      if (event.type === 'voice.state' && event.state === 'off' && event.error) setLastTranscript('')
      // Dès que le mot d'activation est reconnu, on montre le fil vocal : la transcription,
      // l'outil exécuté et la réponse s'affichent en direct, sans clic. On ne vole jamais le fil
      // si une réponse écrite est en cours ou si l'utilisateur est en train de taper.
      if (event.type === 'voice.state' && event.state === 'command' && !voiceOpenRef.current && !busyRef.current && !inputRef.current.trim()) {
        setSegment('discussion')
        openVoiceConversation().catch(() => undefined)
      }
      if (event.type === 'conversation.created' || event.type === 'conversation.updated' || event.type === 'conversation.deleted') {
        loadConversations().catch(() => undefined)
        if (event.type === 'conversation.deleted' && event.conversation_id && event.conversation_id === activeRef.current && !voiceOpenRef.current) {
          // la conversation ouverte a été supprimée ailleurs : on repart sur un brouillon
          session.lastOpened = null
          activeRef.current = null
          setActiveId(null)
          setMessages([])
          setBusy(false)
        }
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
          // Une demande écrite sans lunettes a consommé un message de l'aperçu (ou a été refusée) :
          // le service ne publie pas ce compteur, on le relit.
          rafraichirPresence().catch(() => undefined)
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
  }, [loadConversations, openVoiceConversation, setSegment, toast, rafraichirPresence])

  // Le compteur de l'aperçu est relu à chaque ouverture de l'onglet.
  useEffect(() => {
    rafraichirPresence().catch(() => undefined)
  }, [rafraichirPresence])

  const absentes = presence !== null && !presence.presentes
  const apercuRestant: number = presence?.apercu_restant ?? 0
  const apercuEpuise = absentes && apercuRestant <= 0
  const acheterUrl: string = presence?.acheter_url || URL_ACHAT_DEFAUT

  /* ---------------------------------------------------------------- envoi, annulation, pièces */
  /** `override` permet d'envoyer une phrase d'exemple sans passer par l'état `input`
   *  (qui serait périmé dans la fermeture du gestionnaire de clic). */
  const send = useCallback(
    async (override?: string) => {
      const text = (override ?? input).trim()
      if ((!text && attachments.length === 0) || busy) return
      if (apercuEpuise) {
        // Le service refuserait : on montre l'invitation plutôt que d'écrire un message voué au refus.
        demanderLunettes({ fonction: 'Écrire à IRIS', acheter_url: acheterUrl })
        return
      }
      let convId = activeId
      if (!convId) {
        let conv: { id: string }
        try {
          conv = await api.post('/api/conversations', { agent: agentChoice })
        } catch (err) {
          toast(messageErreur(err), 'error')
          return
        }
        convId = conv.id
        // le filtre d'événements lit cette référence, pas l'état React : sans cette ligne
        // le tout premier flux de réponse serait jeté.
        activeRef.current = conv.id
        session.lastOpened = conv.id
        session.lastOpenedVoice = false
        setActiveId(conv.id)
        await loadConversations().catch(() => undefined)
      }
      setBusy(true)
      const images = attachments.map((a) => ({ media_type: a.media_type, data: a.data }))
      const ok = api.send({ type: 'chat.send', conversation_id: convId, text, images, agent: agentChoice })
      if (!ok) {
        try {
          await api.post(`/api/conversations/${convId}/messages`, { text, images, agent: agentChoice })
        } catch (err) {
          setBusy(false)
          toast(messageErreur(err), 'error')
          return
        }
      }
      setInput('')
      setAttachments([])
    },
    [activeId, agentChoice, attachments, busy, input, loadConversations, toast, apercuEpuise, demanderLunettes, acheterUrl]
  )

  const cancel = useCallback(() => {
    if (activeId) api.send({ type: 'chat.cancel', conversation_id: activeId })
  }, [activeId])

  const attachImage = useCallback(async () => {
    try {
      const img = await window.iris.pickImage()
      if (img) setAttachments((a) => [...a, img])
    } catch (err) {
      toast(messageErreur(err), 'error')
    }
  }, [toast])

  const attachScreenshot = useCallback(async () => {
    // Capturer l'écran, c'est capter : les lunettes sont exigées (règle « lunettes d'abord »).
    if (!exigerLunettes('Joindre une capture d’écran')) return
    try {
      const shot = await api.post('/api/system/screenshot')
      setAttachments((a) => [...a, { name: 'capture.jpg', media_type: shot.media_type, data: shot.data }])
    } catch (err) {
      toast(messageErreur(err), 'error')
    }
  }, [exigerLunettes, toast])

  const viderHistoriqueVocal = useCallback(async () => {
    if (!activeId) return
    if (!window.confirm('Effacer tout l’historique de vos commandes vocales ?')) return
    try {
      await api.delete(`/api/conversations/${activeId}`)
      await openVoiceConversation()
    } catch (err) {
      toast(messageErreur(err), 'error')
    }
  }, [activeId, openVoiceConversation, toast])

  /** Depuis Favoris : ouvrir la conversation d'un message étoilé. */
  const ouvrirDepuisFavori = useCallback(
    (conversationId: string) => {
      setSegment('discussion')
      openConversation(conversationId).catch(() => toast('Cette conversation n’existe plus.', 'error'))
    },
    [openConversation, setSegment, toast]
  )

  /* ---------------------------------------------------------------- dérivés */
  const plan = status?.plan
  const mot = settings?.wake_word || 'Dis-moi Iris'
  const personaId: string = settings?.persona || 'defaut'
  const nomRole = personas.find((p) => p.id === personaId)?.nom || 'Assistante IRIS (défaut)'

  // L'envoi n'est bloqué que si le texte doit partir vers une IA externe : les IA locales
  // sont exemptées par la porte de consentement du service.
  const consentBloque = useMemo(() => {
    if (!Object.keys(consent).length) return false
    if (settings?.local_only || consent.transcript?.granted) return false
    if (agentChoice === 'auto') return readyAgents.some((a) => !a.local)
    return !agents.find((a) => a.name === agentChoice)?.local
  }, [agentChoice, agents, consent, readyAgents, settings])

  const vide = messages.length === 0
  const lunettesConnectees = Boolean(lunettes?.connected)

  /* ---------------------------------------------------------------- rendu */
  return (
    <div className="ecran avec-onglets ia-ecran">
      <div className="ia-tete">
        <BtnIcone title="Liste des discussions (Ctrl+F)" aria-label="Liste des discussions" onClick={() => nav.ouvrir('discussions')}>
          <IcoListeChat />
        </BtnIcone>
        <button type="button" className="role" title="Choisir un rôle" onClick={() => setRolesOuvert(true)}>
          <span>{nomRole}</span>
          <IcoChevronBas />
        </button>
        <BtnIcone title="Paramètres de langue de l’IA" aria-label="Paramètres de langue de l’IA" onClick={() => nav.ouvrir('langue-ia')}>
          <IcoTraduire />
        </BtnIcone>
        <BtnIcone title="Nouvelle conversation" aria-label="Nouvelle conversation" onClick={newConversation}>
          <IcoNouveauChat />
        </BtnIcone>
      </div>

      <Segmente options={SEGMENTS} valeur={segment} onChange={setSegment} />

      {segment === 'favoris' ? (
        <div className="ia-centre sans-composeur">
          <Favoris onOuvrir={ouvrirDepuisFavori} />
        </div>
      ) : null}

      {segment === 'minuteur' ? (
        <div className="ia-centre sans-composeur">
          <Minuteur />
        </div>
      ) : null}

      {segment === 'discussion' ? (
        <>
          {absentes ? (
            <div
              className={`bloc-note ${apercuEpuise ? 'attention' : ''}`}
              role="status"
              aria-live="polite"
              style={{ margin: '0 12px 6px', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', flex: 'none' }}
            >
              <span style={{ flex: 1, minWidth: 200 }}>
                Aperçu : {apercuRestant} message{apercuRestant > 1 ? 's' : ''} restant{apercuRestant > 1 ? 's' : ''} — IRIS s’utilise avec les lunettes VELA
              </span>
              <span className="row" style={{ gap: 6 }}>
                <button type="button" className="btn sm primary" onClick={() => nav.ouvrir('connecter')}>Connecter</button>
                <button type="button" className="btn sm" onClick={() => window.iris.openExternal(acheterUrl)}>Acheter</button>
              </span>
            </div>
          ) : null}
          <div className="ia-centre" ref={filRef}>
            {showVoiceConv ? (
              <div className="ia-fil-entete">
                <span>Échanges vocaux</span>
                <span>·</span>
                <span>{lastVoiceAt ? `dernier échange ${formatDate(lastVoiceAt)}` : `en attente de « ${mot} »`}</span>
                {activeId && !vide ? (
                  <button type="button" className="btn ghost sm" title="Efface toutes vos commandes vocales passées. Sans effet sur vos conversations écrites." onClick={viderHistoriqueVocal}>
                    Vider l’historique
                  </button>
                ) : null}
              </div>
            ) : null}

            {vide ? (
              <div className="intro" style={{ paddingTop: 12 }}>
                <h1 style={{ fontSize: 28 }}>{showVoiceConv ? 'Échanges vocaux' : 'Assistante d’IA'}</h1>
                <IcoRobotDegrade className="robot" style={{ width: 70, height: 84 }} />
                <h2 style={{ fontSize: 30 }}>Questions et réponses</h2>
                <p className="sous" style={{ fontWeight: 700, color: 'var(--text-2)' }}>
                  Permet la saisie vocale dans plusieurs langues, y compris des questions sur la météo, la vie quotidienne et d’autres questions et réponses. Compréhension des situations : « Quel temps fait-il aujourd’hui ? »
                </p>
                {showVoiceConv ? (
                  <div className="exemples bloc" style={{ width: '100%', textAlign: 'left', marginTop: 12 }}>
                    <div className="legende">Dites « {mot} », puis par exemple :</div>
                    {SUGGESTIONS.map((s) => (
                      <div className="exemple" key={s.phrase} style={{ padding: '4px 0 10px' }}>
                        <span className="verbe">{s.verbe}</span>
                        <span className="phrase">« {s.phrase} »</span>
                      </div>
                    ))}
                    <div className="legende" style={{ marginTop: 4 }}>Les trois premiers, IRIS les exécute elle-même, sans passer par une IA.</div>
                  </div>
                ) : absentes || (presence === null && !lunettesConnectees) ? (
                  <>
                    <Holo style={{ marginTop: 18 }} onClick={() => nav.ouvrir('connecter')}>
                      Connectez l’appareil
                    </Holo>
                    <div className="muted" style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.4 }}>
                      {presence
                        ? `IRIS s’utilise avec les lunettes VELA. Sans elles, un aperçu de ${presence.apercu_total} messages écrits.`
                        : 'IRIS s’utilise avec les lunettes VELA.'}
                    </div>
                  </>
                ) : (
                  <div className="exemples bloc" style={{ width: '100%', textAlign: 'left', marginTop: 12 }}>
                    <div className="legende">Dites « {mot} », ou choisissez un exemple.</div>
                    {SUGGESTIONS.map((s) => (
                      <button
                        key={s.phrase}
                        type="button"
                        className="exemple"
                        disabled={busy}
                        title={s.local ? 'Envoyer cette demande maintenant : IRIS l’exécute elle-même, sans passer par une IA' : 'Mettre cette phrase dans la zone d’écriture'}
                        onClick={() => {
                          if (s.local) send(s.phrase).catch(() => undefined)
                          else {
                            setInput(s.phrase)
                            textareaRef.current?.focus()
                          }
                        }}
                      >
                        <span className="verbe">{s.verbe}</span>
                        <span className="phrase">« {s.phrase} »</span>
                      </button>
                    ))}
                    <div className="legende" style={{ marginTop: 4 }}>
                      Les trois premiers, IRIS les exécute elle-même, sans passer par une IA. Les autres remplissent la zone d’écriture : vous validez avant l’envoi.
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="fil">
                <div className="date">{formatDate(messages[0].created_at)}</div>
                {messages.map((m) => (
                  <Bulle key={m.id} m={m} conversationId={activeId} />
                ))}
              </div>
            )}
          </div>

          {/* La voix passe AVANT le clavier : c'est la conduite principale du produit, le composeur
              est le repli. */}
          <BarreVoix transcript={lastTranscript} latence={lastLatency} />

          <div className="composeur">
            {!showVoiceConv && apercuEpuise ? (
              <div className="carte col" style={{ gap: 10 }} role="status">
                <h3 style={{ margin: 0, fontSize: 19 }}>Votre aperçu d’IRIS par écrit est terminé</h3>
                <div className="desc">IRIS s’utilise avec les lunettes VELA : connectez les vôtres, ou découvrez-les.</div>
                <div className="row wrap" style={{ gap: 8 }}>
                  <Holo taille="petit" onClick={() => nav.ouvrir('connecter')}>Connecter mes lunettes</Holo>
                  <Holo taille="petit" variante="contour" onClick={() => window.iris.openExternal(acheterUrl)}>Acheter les lunettes</Holo>
                </div>
              </div>
            ) : !showVoiceConv ? (
              <>
                {attachments.length ? (
                  <div className="pieces">
                    {attachments.map((a, i) => (
                      <div className="att" key={i}>
                        <img src={`data:${a.media_type};base64,${a.data}`} alt={a.name} />
                        <button type="button" aria-label="Retirer cette pièce jointe" onClick={() => setAttachments((list) => list.filter((_, j) => j !== i))}>×</button>
                      </div>
                    ))}
                  </div>
                ) : null}
                <div className="boite">
                  <BtnIcone title="Joindre une image" aria-label="Joindre une image" onClick={attachImage}>
                    <IcoImage />
                  </BtnIcone>
                  <BtnIcone title="Joindre une capture d’écran" aria-label="Joindre une capture d’écran" onClick={attachScreenshot}>
                    <IcoCapture />
                  </BtnIcone>
                  <textarea
                    ref={textareaRef}
                    rows={1}
                    placeholder={busy ? 'IRIS répond…' : 'Écrivez à IRIS…'}
                    value={input}
                    onChange={(e) => {
                      setInput(e.target.value)
                      e.target.style.height = 'auto'
                      e.target.style.height = Math.min(e.target.scrollHeight, 160) + 'px'
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        send().catch(() => undefined)
                      }
                    }}
                  />
                  <button
                    type="button"
                    className={`envoyer ${busy ? 'stop' : ''}`}
                    title={busy ? 'Arrêter la réponse' : 'Envoyer (Entrée)'}
                    aria-label={busy ? 'Arrêter la réponse' : 'Envoyer'}
                    disabled={!busy && !input.trim() && attachments.length === 0}
                    onClick={() => (busy ? cancel() : send().catch(() => undefined))}
                  >
                    {busy ? <IcoStop /> : <IcoEnvoyer />}
                  </button>
                </div>
                <div className="barre">
                  <span>{agentChoice === 'auto' ? 'IRIS choisit l’IA la mieux placée' : `IA : ${labelMoteurPublic(agentChoice)}`}</span>
                  {plan?.label ? <span className="pill" title={`Le modèle est choisi selon votre forfait ${plan.label}.`}>{plan.label}</span> : null}
                  {settings?.local_only ? <span className="pill ok">100 % local</span> : null}
                  {consentBloque ? (
                    <button
                      type="button"
                      className="pill warn lien"
                      title="Sans cette autorisation, IRIS ne peut pas envoyer votre demande à une IA externe. Ouvre Confidentialité."
                      onClick={() => nav.ouvrir('confidentialite')}
                    >
                      Envoi du texte non autorisé — cliquez pour autoriser
                    </button>
                  ) : null}
                </div>
              </>
            ) : (
              <div className="barre">
                <span>Ce fil garde les commandes vocales adressées à IRIS et ses réponses.</span>
                <button type="button" className="btn ghost sm" onClick={newConversation}>Écrire à IRIS</button>
                {plan?.label ? <span className="pill" title={`Le modèle est choisi selon votre forfait ${plan.label}.`}>{plan.label}</span> : null}
              </div>
            )}
          </div>
        </>
      ) : null}

      {rolesOuvert ? (
        <Feuille titre="Choisir un rôle" onClose={() => setRolesOuvert(false)}>
          {personas.map((p) => (
            <Option
              key={p.id}
              titre={p.nom}
              sous={p.description}
              actif={personaId === p.id}
              onClick={() => {
                updateSettings({ persona: p.id }).catch((err) => toast(messageErreur(err), 'error'))
                setRolesOuvert(false)
              }}
            />
          ))}
        </Feuille>
      ) : null}
    </div>
  )
}
