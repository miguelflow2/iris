import React, { useCallback, useEffect, useRef, useState } from 'react'
import { BtnIcone, Field, Holo, Markdown, Modal, TopBar } from '../components/ui'
import { IcoPoubelle } from '../components/icons'
import { api, formatDate, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import { labelMoteurPublic } from './ia/commun'

/* =========================================================================
   Tâches de fond (porte l'ancienne TasksView) : formulaire titre / instructions /
   moteur, liste des tâches avec leur état, annulation ou suppression, et une
   modale de détail (instructions + résultat en Markdown).
   ========================================================================= */

const STATUS: Record<string, { label: string; cls: string }> = {
  pending: { label: 'en attente', cls: '' },
  running: { label: 'en cours', cls: 'warn' },
  done: { label: 'terminée', cls: 'ok' },
  failed: { label: 'échouée', cls: 'err' },
  cancelled: { label: 'annulée', cls: '' }
}

/** Moteurs proposés sur cet écran (masque de marque) : même liste que MoteursIaScreen.MOTEURS_DE_BASE.
 *  Les moteurs tiers ne se choisissent que depuis l'écran avancé « Moteurs IA ». */
const MOTEURS_PUBLICS = ['vela', 'custom']

function messageErreur(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

export function TachesScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  void params
  const { agents, toast } = useStore()
  const [tasks, setTasks] = useState<any[]>([])
  const [title, setTitle] = useState('')
  const [instructions, setInstructions] = useState('')
  const [agent, setAgent] = useState('auto')
  const [open, setOpen] = useState<any | null>(null)
  const [occupe, setOccupe] = useState<string | null>(null)
  const monte = useRef(true)
  useEffect(() => {
    monte.current = true
    return () => {
      monte.current = false
    }
  }, [])

  const load = useCallback(async () => {
    try {
      const r = await api.get('/api/tasks')
      if (monte.current) setTasks(Array.isArray(r?.tasks) ? r.tasks : [])
    } catch (err) {
      if (monte.current) toast(messageErreur(err), 'error')
    }
  }, [toast])

  useEffect(() => {
    load()
    return api.on((e: IrisEvent) => {
      if (e.type === 'task.updated' || e.type === 'task.deleted') {
        load()
        // si la modale de détail est ouverte sur cette tâche, on la rafraîchit
        if (e.type === 'task.updated' && e.task?.id) {
          setOpen((o: any) => (o && o.id === e.task.id ? { ...o, ...e.task } : o))
        }
      }
    })
  }, [load])

  const creer = async (): Promise<void> => {
    if (!instructions.trim() || occupe === 'creer') return
    setOccupe('creer')
    try {
      await api.post('/api/tasks', { title: title.trim() || 'Tâche', instructions: instructions.trim(), agent })
      setTitle('')
      setInstructions('')
      toast('Tâche lancée en arrière-plan. IRIS vous préviendra à la fin.', 'success')
      await load()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const detail = async (id: string): Promise<void> => {
    try {
      setOpen(await api.get(`/api/tasks/${id}`))
    } catch (err) {
      toast(messageErreur(err), 'error')
    }
  }

  const annuler = async (id: string): Promise<void> => {
    setOccupe(id)
    try {
      await api.post(`/api/tasks/${id}/cancel`)
      await load()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const supprimer = async (id: string): Promise<void> => {
    setOccupe(id)
    try {
      await api.delete(`/api/tasks/${id}`)
      await load()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const moteursPrets = agents.filter((a) => a?.ready && MOTEURS_PUBLICS.includes(a.name))

  return (
    <div className="ecran">
      <TopBar titre="Tâches" />
      <div className="contenu">
        <div className="carte">
          <h3>Nouvelle tâche</h3>
          <div className="desc">
            Confiez un travail long (recherche, rédaction, développement) à une IA : il tourne en arrière-plan et IRIS vous prévient par la voix et une notification quand
            c’est prêt.
          </div>
          <div className="col" style={{ marginTop: 14, gap: 12 }}>
            <Field label="Titre">
              <input className="input" placeholder="ex. Étude de marché lunettes connectées" value={title} onChange={(e) => setTitle(e.target.value)} />
            </Field>
            <Field label="Instructions">
              <textarea className="textarea" placeholder="Instructions complètes pour l’IA…" value={instructions} onChange={(e) => setInstructions(e.target.value)} />
            </Field>
            <Field label="Moteur" hint={moteursPrets.length ? undefined : 'Aucun moteur prêt pour l’instant : IRIS choisira parmi ceux disponibles (Mon profil › Réglages › Moteurs IA).'}>
              <select className="select" value={agent} onChange={(e) => setAgent(e.target.value)}>
                <option value="auto">IRIS choisit l’IA (recommandé)</option>
                {moteursPrets.map((a) => (
                  <option key={a.name} value={a.name}>{labelMoteurPublic(a.name)}</option>
                ))}
              </select>
            </Field>
            <Holo disabled={!instructions.trim() || occupe === 'creer'} onClick={creer}>
              {occupe === 'creer' ? 'Lancement…' : 'Lancer la tâche'}
            </Holo>
          </div>
        </div>

        {tasks.length === 0 ? (
          <div className="empty">
            <div style={{ fontSize: 16, color: 'var(--text)' }}>Aucune tâche en cours.</div>
            <div className="small" style={{ marginTop: 8, lineHeight: 1.4 }}>
              Écrivez les instructions ci-dessus et lancez : vous pouvez changer d’écran, parler à IRIS ou fermer la fenêtre, le travail se poursuit.
            </div>
          </div>
        ) : (
          <div className="col" style={{ gap: 10 }}>
            {tasks.map((t) => {
              const etat = STATUS[t.status] || { label: String(t.status || ''), cls: '' }
              const active = t.status === 'running' || t.status === 'pending'
              return (
                <div className="carte serree" key={t.id}>
                  <div className="row" style={{ alignItems: 'flex-start' }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="row wrap" style={{ gap: 8 }}>
                        <span style={{ fontWeight: 700, fontSize: 17, wordBreak: 'break-word' }}>{t.title}</span>
                        <span className={`pill ${etat.cls}`}>{etat.label}</span>
                        {t.agent ? <span className="small muted">{labelMoteurPublic(t.agent)}</span> : null}
                      </div>
                      <div className="small muted" style={{ marginTop: 4 }}>
                        {formatDate(t.created_at)}
                        {t.completed_at ? ` → ${formatDate(t.completed_at)}` : ''}
                      </div>
                      {t.error ? (
                        <div style={{ marginTop: 6 }}>
                          <span className="pill err" style={{ whiteSpace: 'normal', wordBreak: 'break-word' }}>{String(t.error)}</span>
                        </div>
                      ) : null}
                    </div>
                    <div className="row" style={{ gap: 6, flexShrink: 0 }}>
                      <button type="button" className="btn sm" onClick={() => detail(String(t.id))}>
                        Détails
                      </button>
                      {active ? (
                        <button type="button" className="btn sm" disabled={occupe === String(t.id)} onClick={() => annuler(String(t.id))}>
                          {occupe === String(t.id) ? '…' : 'Annuler'}
                        </button>
                      ) : (
                        <BtnIcone aria-label="Supprimer la tâche" title="Supprimer" disabled={occupe === String(t.id)} onClick={() => supprimer(String(t.id))}>
                          <IcoPoubelle />
                        </BtnIcone>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {open ? (
        <Modal
          title={String(open.title || 'Tâche')}
          onClose={() => setOpen(null)}
          actions={
            <button type="button" className="btn" onClick={() => setOpen(null)}>
              Fermer
            </button>
          }
        >
          <div className="row wrap" style={{ gap: 8, marginBottom: 10 }}>
            <span className={`pill ${(STATUS[open.status] || { cls: '' }).cls}`}>{(STATUS[open.status] || { label: String(open.status || '') }).label}</span>
            {open.agent ? <span className="small muted">{labelMoteurPublic(open.agent)}</span> : null}
            {open.created_at ? <span className="small muted">{formatDate(open.created_at)}</span> : null}
          </div>
          {open.instructions ? (
            <p className="small muted" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{open.instructions}</p>
          ) : null}
          {open.result ? (
            <div className="sombre">
              <Markdown text={String(open.result)} />
            </div>
          ) : (
            <p className="muted">
              {open.status === 'running' || open.status === 'pending' ? 'En cours…' : open.error || 'Cette tâche s’est terminée sans produire de résultat.'}
            </p>
          )}
        </Modal>
      ) : null}
    </div>
  )
}
