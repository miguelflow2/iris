import React, { useCallback, useEffect, useRef, useState } from 'react'
import { BtnIcone, Field, Holo, Liste, Rangee, TopBar } from '../components/ui'
import { IcoJournal, IcoPoubelle, IcoRecherche } from '../components/icons'
import { api, formatDate, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   Mémoire d'IRIS (porte l'ancienne MemoryView) : compteur et rétention, ajout
   d'un souvenir, recherche en direct, résumé de journée, export, effacement,
   et la liste des souvenirs avec la phrase d'origine sous chaque ligne.
   Rien n'est inventé : tout vient de GET /api/memory et de l'événement memory.updated.

   Effacer une période (DELETE /api/memory/plage) : bornes AAAA-MM-JJ à l'heure de
   l'ordinateur, fin incluse (toute la journée) ; les souvenirs épinglés de la
   période partent aussi. Quand la mémoire est suspendue (mode invité, zone sans
   mémoire), l'écran le dit : rien de nouveau n'est retenu, consulter et effacer
   restent possibles. Tout cet écran reste accessible sans lunettes (Loi 25).
   ========================================================================= */

function messageErreur(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

function libelleSource(source: string | undefined): string {
  if (source === 'user') return 'vous'
  if (source === 'conversation') return 'retenu de vos mots'
  return source || 'inconnue'
}

export function MemoireScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  void params
  const { nav, toast, settings, consent, ecoute, invite, zone } = useStore()
  const [items, setItems] = useState<any[]>([])
  const [count, setCount] = useState(0)
  const [query, setQuery] = useState('')
  const [text, setText] = useState('')
  const [occupe, setOccupe] = useState<'memoriser' | 'resumer' | 'exporter' | 'effacer' | 'plage' | null>(null)
  const [debut, setDebut] = useState('')
  const [fin, setFin] = useState('')
  const monte = useRef(true)
  useEffect(() => {
    monte.current = true
    return () => {
      monte.current = false
    }
  }, [])

  const load = useCallback(async (q?: string) => {
    try {
      const res = await api.get(q ? `/api/memory?q=${encodeURIComponent(q)}` : '/api/memory')
      if (!monte.current) return
      setItems(Array.isArray(res?.items) ? res.items : [])
      if (!q) setCount(Number(res?.count) || 0)
    } catch (err) {
      if (monte.current) toast(messageErreur(err), 'error')
    }
  }, [toast])

  useEffect(() => {
    load(query || undefined)
    return api.on((e: IrisEvent) => {
      if (e.type === 'memory.updated') load(query || undefined)
    })
  }, [load, query])

  const memoriser = async (): Promise<void> => {
    const t = text.trim()
    if (!t || occupe) return
    setOccupe('memoriser')
    try {
      await api.post('/api/memory', { text: t })
      setText('')
      toast('Souvenir mémorisé.', 'success')
      await load(query || undefined)
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const resumerJournee = async (): Promise<void> => {
    if (occupe) return
    setOccupe('resumer')
    try {
      const r = await api.post('/api/memory/summarize-day', {})
      toast(r?.stored ? 'Résumé de la journée enregistré.' : 'Rien à résumer aujourd’hui.', r?.stored ? 'success' : 'info')
      await load(query || undefined)
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const exporter = async (): Promise<void> => {
    if (occupe) return
    setOccupe('exporter')
    try {
      const res = await api.get('/api/memory/export')
      const path = await window.iris.saveFile('iris-memoire.json', typeof res === 'string' ? res : JSON.stringify(res, null, 2))
      if (path) toast(`Mémoire exportée : ${path}`, 'success')
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const toutEffacer = async (): Promise<void> => {
    if (occupe) return
    if (!window.confirm('Effacer toute la mémoire ? Cette action est définitive.')) return
    setOccupe('effacer')
    try {
      await api.delete('/api/memory')
      toast('Mémoire effacée.', 'info')
      await load(query || undefined)
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const effacerPlage = async (): Promise<void> => {
    if (occupe || (!debut && !fin)) return
    if (debut && fin && debut > fin) {
      toast('La date de début doit précéder la date de fin.', 'error')
      return
    }
    const periode = debut && fin ? (debut === fin ? `du ${debut}` : `du ${debut} au ${fin} inclus`) : debut ? `depuis le ${debut}` : `jusqu’au ${fin} inclus`
    if (!window.confirm(`Effacer tous les souvenirs retenus ${periode}, épinglés compris ? Cette action est définitive.`)) return
    setOccupe('plage')
    try {
      const q = new URLSearchParams()
      if (debut) q.set('debut', debut)
      if (fin) q.set('fin', fin)
      const r = await api.delete(`/api/memory/plage?${q.toString()}`)
      const n = Number(r?.supprimes) || 0
      toast(n ? `${n} souvenir${n > 1 ? 's' : ''} effacé${n > 1 ? 's' : ''} ${periode}.` : `Aucun souvenir retenu ${periode}.`, n ? 'success' : 'info')
      await load(query || undefined)
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const supprimer = async (id: string): Promise<void> => {
    try {
      await api.delete(`/api/memory/${id}`)
      await load(query || undefined)
    } catch (err) {
      toast(messageErreur(err), 'error')
    }
  }

  const retention: number = Number(settings?.retention_days) || 0
  const motReveil: string = settings?.wake_word || 'Dis-moi Iris'
  const memoirePartagee = Boolean(consent?.memory?.granted)
  // Mémoire suspendue : la raison exacte du service quand l'écoute la publie, sinon l'état du mode
  // invité ou de la zone tel que le store le connaît.
  const suspendue: string | null =
    ecoute?.memoire_suspendue || (invite?.actif ? 'mode invité' : zone?.dans_zone ? `zone sans mémoire${zone.zone_nom ? ` « ${zone.zone_nom} »` : ''}` : null)
  const aujourdhui = new Date().toLocaleDateString('en-CA')

  return (
    <div className="ecran">
      <TopBar titre="Mémoire" />
      <div className="contenu">
        {suspendue ? (
          <div className="bloc-note attention" role="status">
            Mémoire suspendue ({suspendue}) : IRIS ne retient rien de nouveau pour l’instant, ni souvenir, ni journal, ni cours, ni reçu. Vous pouvez encore
            consulter, exporter et effacer.
          </div>
        ) : null}

        {/* carte d'en-tête : compteur, rétention, consentement */}
        <div className="carte">
          <h3>
            {count} souvenir{count > 1 ? 's' : ''}
          </h3>
          <div className="desc">
            IRIS ne fabrique aucun souvenir : elle retient ce que vous avez réellement dit, et garde la phrase d’origine sous chaque ligne. Si elle n’a pas
            l’information, elle le dit au lieu de l’inventer.
          </div>
          <div className="row wrap" style={{ marginTop: 12, gap: 8 }}>
            <span className="pill">chiffré{count > 1 ? 's' : ''} sur cet ordinateur</span>
            <span className="pill">rétention : {retention ? `${retention} jour${retention > 1 ? 's' : ''}` : 'illimitée'}</span>
            <span className={`pill ${memoirePartagee ? 'ok' : 'warn'}`}>{memoirePartagee ? 'souvenirs ajoutés au contexte de l’IA' : 'non partagés avec l’IA'}</span>
          </div>
          {!memoirePartagee ? (
            <div className="small muted" style={{ marginTop: 8, lineHeight: 1.4 }}>
              Les souvenirs ne sont pas partagés avec l’IA : le consentement « mémoire » n’est pas accordé (Mon profil › Confidentialité).
            </div>
          ) : null}
        </div>

        {/* ajout d'un souvenir */}
        <div className="carte col">
          <textarea
            className="textarea"
            placeholder="Ajouter un souvenir : une préférence, un fait, une décision…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault()
                memoriser()
              }
            }}
          />
          <div className="row between wrap" style={{ gap: 10 }}>
            <span className="small muted" style={{ flex: 1, minWidth: 180, lineHeight: 1.4 }}>
              Ctrl+Entrée pour enregistrer. IRIS peut aussi mémoriser à la voix : « {motReveil}, souviens-toi que… »
            </span>
            <Holo taille="petit" disabled={!text.trim() || occupe === 'memoriser' || Boolean(suspendue)} onClick={memoriser}>
              {occupe === 'memoriser' ? 'Enregistrement…' : 'Mémoriser'}
            </Holo>
          </div>
        </div>

        {/* effacer une période */}
        <div className="carte col" style={{ gap: 12 }}>
          <h3 style={{ margin: 0 }}>Effacer une période</h3>
          <div className="desc">Les souvenirs retenus entre ces deux dates, à l’heure de cet ordinateur. Une seule date suffit (« depuis » ou « jusqu’à »).</div>
          <div className="cartes-2">
            <Field label="Du">
              <input className="input" type="date" max={fin || aujourdhui} value={debut} onChange={(e) => setDebut(e.target.value)} />
            </Field>
            <Field label="Au (inclus)">
              <input className="input" type="date" min={debut || undefined} max={aujourdhui} value={fin} onChange={(e) => setFin(e.target.value)} />
            </Field>
          </div>
          <div className="row between wrap" style={{ gap: 10 }}>
            <span className="small muted" style={{ flex: 1, minWidth: 180, lineHeight: 1.4 }}>Les souvenirs épinglés de la période sont effacés aussi. Le journal d’écoute s’efface à part.</span>
            <button type="button" className="btn sm danger" disabled={occupe !== null || (!debut && !fin)} onClick={effacerPlage}>
              {occupe === 'plage' ? 'Effacement…' : 'Effacer la période'}
            </button>
          </div>
        </div>

        <Liste>
          <Rangee icone={<IcoJournal />} titre="Journal d’écoute" sous="Ce qui a été entendu mot pour mot, si le journal continu est activé : chercher, effacer une plage." onClick={() => nav.ouvrir('journal')} />
        </Liste>

        {/* recherche en direct */}
        <div className="recherche">
          <IcoRecherche />
          <input placeholder="Rechercher dans la mémoire…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Rechercher dans la mémoire" />
        </div>

        {/* actions globales */}
        <div className="row wrap" style={{ gap: 8 }}>
          <button type="button" className="btn sm" disabled={occupe !== null} onClick={resumerJournee}>
            {occupe === 'resumer' ? 'Résumé…' : 'Résumer la journée'}
          </button>
          <button type="button" className="btn sm" disabled={occupe !== null} onClick={exporter}>
            {occupe === 'exporter' ? 'Export…' : 'Exporter (JSON)'}
          </button>
          <button type="button" className="btn sm danger" disabled={occupe !== null} onClick={toutEffacer}>
            {occupe === 'effacer' ? 'Effacement…' : 'Tout effacer'}
          </button>
        </div>

        {/* liste des souvenirs */}
        {items.length === 0 ? (
          <div className="empty">
            {query ? (
              <div style={{ fontSize: 16, color: 'var(--text)' }}>Aucun souvenir ne correspond à « {query} ».</div>
            ) : (
              <>
                <div style={{ fontSize: 16, color: 'var(--text)' }}>Aucun souvenir pour l’instant.</div>
                <div className="small" style={{ marginTop: 8, lineHeight: 1.4 }}>
                  Écrivez-en un ci-dessus, ou laissez IRIS le faire : elle retient ce qui compte au fil de vos conversations, en gardant votre phrase d’origine.
                </div>
              </>
            )}
          </div>
        ) : (
          <div className="col" style={{ gap: 10 }}>
            {items.map((m) => (
              <div className="carte serree" key={m.id}>
                <div className="row" style={{ alignItems: 'flex-start' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{m.text}</div>
                    {m.source_text ? (
                      <div className="origin" title="Phrase exacte dont vient ce souvenir">« {m.source_text} »</div>
                    ) : null}
                    <div className="small muted" style={{ marginTop: 4, lineHeight: 1.4 }}>
                      {formatDate(m.created_at)} · {libelleSource(m.source)}
                      {m.uses ? ` · utilisé ${m.uses} fois` : ''}
                      {m.pinned ? ' · épinglé' : ''}
                      {m.score ? ` · pertinence ${Math.round(Number(m.score) * 100)} %` : ''}
                      {m.retained_until ? ` · expire ${formatDate(m.retained_until)}` : ''}
                    </div>
                  </div>
                  <BtnIcone aria-label="Supprimer ce souvenir" title="Supprimer" onClick={() => supprimer(String(m.id))}>
                    <IcoPoubelle />
                  </BtnIcone>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
