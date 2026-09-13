import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BtnIcone, Field, Modal, TopBar } from '../components/ui'
import { IcoNouveauChat, IcoRecherche } from '../components/icons'
import { api, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import { MicOrb } from './ia/BarreVoix'
import { CLE_OUVRIR, OUVRIR_NOUVELLE, OUVRIR_VOIX, formatQuand, labelMoteurPublic, messageErreur, seauDe, session, type Conversation } from './ia/commun'

/* =========================================================================
   Liste des discussions (maquette IMG_0717) : recherche, fil « Échanges
   vocaux » épinglé, conversations groupées par date, actions (renommer,
   archiver / restaurer, supprimer), bascule vers les archives. Ouvrir une
   conversation = poser son identifiant en sessionStorage et revenir à
   l'onglet IA, qui l'ouvre au montage.
   ========================================================================= */

function demanderOuverture(valeur: string): void {
  try {
    window.sessionStorage.setItem(CLE_OUVRIR, valeur)
  } catch {
    /* sans sessionStorage, l'onglet IA rouvrira son dernier fil */
  }
}

export function DiscussionsScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  void params
  const { nav, toast, voice, ttsSpeaking, settings } = useStore()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [archivedCount, setArchivedCount] = useState(0)
  const [showArchives, setShowArchives] = useState(false)
  const [filtre, setFiltre] = useState('')
  const [charge, setCharge] = useState(false)
  const [lastVoiceAt, setLastVoiceAt] = useState<string | null>(null)
  // Renommage : un petit modal maison (Electron refuse window.prompt()).
  const [renommage, setRenommage] = useState<Conversation | null>(null)
  const [nouveauTitre, setNouveauTitre] = useState('')
  const [renommageEnCours, setRenommageEnCours] = useState(false)
  const rechercheRef = useRef<HTMLInputElement>(null)
  const archivesRef = useRef(false)

  const loadConversations = useCallback(async () => {
    try {
      const res = await api.get(`/api/conversations${archivesRef.current ? '?archived=true' : ''}`)
      setConversations(res.conversations || [])
      setArchivedCount(res.archived_count ?? 0)
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      setCharge(true)
    }
  }, [toast])

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

  useEffect(() => {
    loadConversations().catch(() => undefined)
    loadVoiceMeta().catch(() => undefined)
    return api.on((e: IrisEvent) => {
      if (e.type === 'conversation.created' || e.type === 'conversation.updated' || e.type === 'conversation.deleted') loadConversations().catch(() => undefined)
      if (e.type === 'voice.reply') setLastVoiceAt(new Date().toISOString())
    })
  }, [loadConversations, loadVoiceMeta])

  // Ctrl+F met le curseur dans la recherche.
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
        e.preventDefault()
        rechercheRef.current?.focus()
        rechercheRef.current?.select()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const ouvrir = useCallback(
    (id: string) => {
      demanderOuverture(id)
      nav.retour()
    },
    [nav]
  )

  const ouvrirVoix = useCallback(() => {
    demanderOuverture(OUVRIR_VOIX)
    nav.retour()
  }, [nav])

  /** Nouvelle conversation : un brouillon dans l'onglet IA (rien n'est écrit en base avant
   *  le premier message, pour ne pas semer de coquilles vides dans cette liste). */
  const nouvelle = useCallback(() => {
    demanderOuverture(OUVRIR_NOUVELLE)
    nav.retour()
  }, [nav])

  const toggleArchives = useCallback(async () => {
    archivesRef.current = !archivesRef.current
    setShowArchives(archivesRef.current)
    setFiltre('')
    await loadConversations()
  }, [loadConversations])

  const ouvrirRenommage = useCallback((conv: Conversation) => {
    setRenommage(conv)
    setNouveauTitre(conv.title || '')
  }, [])

  const fermerRenommage = useCallback(() => {
    setRenommage(null)
    setNouveauTitre('')
  }, [])

  const enregistrerRenommage = useCallback(async () => {
    if (!renommage || renommageEnCours) return
    const title = nouveauTitre.trim()
    if (!title) {
      toast('Le titre ne peut pas être vide.', 'error')
      return
    }
    if (title === (renommage.title || '')) {
      fermerRenommage()
      return
    }
    setRenommageEnCours(true)
    try {
      await api.patch(`/api/conversations/${renommage.id}`, { title })
      await loadConversations()
      fermerRenommage()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      setRenommageEnCours(false)
    }
  }, [fermerRenommage, loadConversations, nouveauTitre, renommage, renommageEnCours, toast])

  /** Ranger plutôt que détruire : rien n'est effacé, la conversation reste consultable. */
  const setArchived = useCallback(
    async (conv: Conversation, archived: boolean) => {
      try {
        await api.patch(`/api/conversations/${conv.id}`, { archived })
        if (session.lastOpened === conv.id) {
          session.lastOpened = null
          session.lastOpenedVoice = false
        }
        await loadConversations()
        toast(archived ? `« ${conv.title} » archivée.` : `« ${conv.title} » restaurée.`, 'success')
      } catch (err) {
        toast(messageErreur(err), 'error')
      }
    },
    [loadConversations, toast]
  )

  const supprimer = useCallback(
    async (conv: Conversation) => {
      const ok = window.confirm(`Supprimer définitivement « ${conv.title} » ?\nCette conversation et ses messages seront effacés. Pour simplement la ranger, utilisez Archiver.`)
      if (!ok) return
      try {
        await api.delete(`/api/conversations/${conv.id}`)
        if (session.lastOpened === conv.id) {
          session.lastOpened = null
          session.lastOpenedVoice = false
        }
        await loadConversations()
      } catch (err) {
        toast(messageErreur(err), 'error')
      }
    },
    [loadConversations, toast]
  )

  // Conversations visibles : filtre de recherche appliqué sur les titres déjà chargés
  // (aucun message n'est déchiffré côté interface).
  const visibles = useMemo(() => {
    const q = filtre.trim().toLowerCase()
    if (!q) return conversations
    return conversations.filter((c) => (c.title || '').toLowerCase().includes(q))
  }, [conversations, filtre])

  // Le service renvoie déjà les conversations triées (updated_at DESC) : il suffit de partitionner.
  const groupes = useMemo(() => {
    const out: { seau: string; items: Conversation[] }[] = []
    for (const c of visibles) {
      const seau = seauDe(c.updated_at)
      if (!out.length || out[out.length - 1].seau !== seau) out.push({ seau, items: [] })
      out[out.length - 1].items.push(c)
    }
    return out
  }, [visibles])

  const mot = settings?.wake_word || 'Dis-moi Iris'
  const voiceState: string = voice?.state || 'off'

  return (
    <div className="ecran">
      <TopBar
        titre="Liste des discussions"
        droite={
          <BtnIcone title="Nouvelle conversation" aria-label="Nouvelle conversation" onClick={nouvelle}>
            <IcoNouveauChat />
          </BtnIcone>
        }
      />
      <div className="contenu serre">
        <div className="recherche">
          <IcoRecherche />
          <input
            ref={rechercheRef}
            placeholder="Rechercher une discussion"
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
          <button
            type="button"
            className="carte"
            style={{ border: 'none', textAlign: 'left', color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 14, width: '100%' }}
            title="Tout ce que vous dites à IRIS arrive ici, dans un seul fil continu"
            onClick={ouvrirVoix}
          >
            <MicOrb state={voiceState} muted={Boolean(voice?.muted)} speaking={Boolean(ttsSpeaking)} />
            <span style={{ flex: 1, minWidth: 0 }}>
              <span style={{ display: 'block', fontSize: 20, fontWeight: 600 }}>Échanges vocaux</span>
              <span className="muted" style={{ display: 'block', fontSize: 15, marginTop: 2 }}>
                {lastVoiceAt ? `dernier échange ${formatQuand(lastVoiceAt)}` : `en attente de « ${mot} »`}
              </span>
            </span>
          </button>
        ) : null}

        <div className="row between wrap">
          <span className="muted" style={{ fontWeight: 600 }}>{showArchives ? 'Conversations archivées' : 'Conversations écrites'}</span>
          <button type="button" className="btn sm" onClick={() => toggleArchives().catch(() => undefined)}>
            {showArchives ? '← Conversations' : `Archives${archivedCount ? ` (${archivedCount})` : ''}`}
          </button>
        </div>

        {charge && conversations.length === 0 ? (
          <div className="empty">
            {showArchives ? (
              'Aucune conversation archivée. Rien n’est supprimé sans que vous le demandiez.'
            ) : (
              <>
                Aucune conversation écrite.
                <br />
                Vos commandes dites à voix haute sont dans « Échanges vocaux », ci-dessus.
              </>
            )}
          </div>
        ) : null}
        {conversations.length > 0 && visibles.length === 0 ? <div className="empty">Aucun résultat pour «&nbsp;{filtre.trim()}&nbsp;».</div> : null}

        {groupes.map((g) => (
          <React.Fragment key={g.seau}>
            <div className="muted" style={{ fontWeight: 600, fontSize: 16, marginTop: 6 }}>{g.seau}</div>
            {g.items.map((c) => (
              <div key={c.id}>
                <div
                  className="carte serree"
                  role="button"
                  tabIndex={0}
                  style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 12 }}
                  onClick={() => ouvrir(c.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      ouvrir(c.id)
                    }
                  }}
                >
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ display: 'block', fontSize: 20, fontWeight: 600, lineHeight: 1.25, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.title || 'Sans titre'}</span>
                    <span className="muted" style={{ display: 'block', fontSize: 14.5, marginTop: 2 }}>
                      {formatQuand(c.updated_at)}
                      {c.agent && c.agent !== 'auto' ? ` · ${labelMoteurPublic(c.agent)}` : ''}
                      {c.busy ? ' · réponse en cours…' : ''}
                    </span>
                  </span>
                </div>
                <div className="row wrap" style={{ padding: '2px 6px 0', gap: 4 }}>
                  <button type="button" className="btn sm ghost" onClick={() => ouvrirRenommage(c)}>Renommer</button>
                  {showArchives ? (
                    <button type="button" className="btn sm ghost" title="Remettre dans les conversations" onClick={() => setArchived(c, false)}>Restaurer</button>
                  ) : (
                    <button type="button" className="btn sm ghost" title="Ranger cette conversation — rien n’est effacé" onClick={() => setArchived(c, true)}>Archiver</button>
                  )}
                  <button type="button" className="btn sm ghost" style={{ color: '#ff8a80' }} title={`Supprimer définitivement « ${c.title} »`} aria-label={`Supprimer la conversation ${c.title}`} onClick={() => supprimer(c)}>
                    Supprimer
                  </button>
                </div>
              </div>
            ))}
          </React.Fragment>
        ))}
      </div>

      {renommage ? (
        <Modal
          title="Renommer la discussion"
          onClose={fermerRenommage}
          actions={
            <>
              <button type="button" className="btn ghost" onClick={fermerRenommage} disabled={renommageEnCours}>
                Annuler
              </button>
              <button type="button" className="btn primary" onClick={() => enregistrerRenommage().catch(() => undefined)} disabled={renommageEnCours || !nouveauTitre.trim()}>
                Enregistrer
              </button>
            </>
          }
        >
          <Field label="Titre">
            <input
              className="input"
              autoFocus
              value={nouveauTitre}
              maxLength={120}
              placeholder="Titre de la discussion"
              onChange={(e) => setNouveauTitre(e.target.value)}
              onFocus={(e) => e.currentTarget.select()}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  enregistrerRenommage().catch(() => undefined)
                } else if (e.key === 'Escape') {
                  e.preventDefault()
                  fermerRenommage()
                }
              }}
            />
          </Field>
        </Modal>
      ) : null}
    </div>
  )
}
