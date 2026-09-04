import React, { useCallback, useEffect, useState } from 'react'
import { Markdown, Modal } from '../components/ui'
import { api, formatDate, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

const STATUS: Record<string, { label: string; cls: string }> = {
  pending: { label: 'en attente', cls: '' },
  running: { label: 'en cours', cls: 'warn' },
  done: { label: 'terminée', cls: 'ok' },
  failed: { label: 'échouée', cls: 'err' },
  cancelled: { label: 'annulée', cls: '' }
}

export function TasksView(): JSX.Element {
  const { agents, toast } = useStore()
  const [tasks, setTasks] = useState<any[]>([])
  const [title, setTitle] = useState('')
  const [instructions, setInstructions] = useState('')
  const [agent, setAgent] = useState('auto')
  const [open, setOpen] = useState<any | null>(null)

  const load = useCallback(async () => setTasks((await api.get('/api/tasks')).tasks), [])
  useEffect(() => {
    load()
    return api.on((e: IrisEvent) => {
      if (e.type === 'task.updated' || e.type === 'task.deleted') load()
    })
  }, [load])

  const create = async () => {
    try {
      await api.post('/api/tasks', { title: title.trim() || 'Tâche', instructions: instructions.trim(), agent })
      setTitle('')
      setInstructions('')
      toast('Tâche lancée en arrière-plan. IRIS vous préviendra à la fin.', 'success')
    } catch (err) {
      toast(String((err as Error).message), 'error')
    }
  }

  const show = async (id: string) => setOpen(await api.get(`/api/tasks/${id}`))

  return (
    <div className="page">
      <h1>Tâches</h1>
      <p className="lead">Confiez un travail long (recherche, rédaction, développement) à une IA : il tourne en arrière-plan et IRIS vous prévient par la voix et une notification quand c’est prêt.</p>
      <div className="card col">
        <input className="input" placeholder="Titre" value={title} onChange={(e) => setTitle(e.target.value)} />
        <textarea className="textarea" placeholder="Instructions complètes pour l’IA…" value={instructions} onChange={(e) => setInstructions(e.target.value)} />
        <div className="row between">
          <select className="select" style={{ width: 220 }} value={agent} onChange={(e) => setAgent(e.target.value)}>
            <option value="auto">IRIS choisit l’IA (recommandé)</option>
            {agents.filter((a) => a.ready).map((a) => (
              <option key={a.name} value={a.name}>{a.label}</option>
            ))}
          </select>
          <button className="btn primary sm" disabled={!instructions.trim()} onClick={create}>Lancer la tâche</button>
        </div>
      </div>
      <div className="list" style={{ marginTop: 16 }}>
        {/* État vide : ne pas redire le « lead » ci-dessus, mais révéler le fait neuf (ça continue en arrière-plan). */}
        {tasks.length === 0 ? (
          <div className="empty">
            <div style={{ fontSize: 16, color: 'var(--text)' }}>Aucune tâche en cours.</div>
            <div className="small" style={{ marginTop: 8 }}>Écrivez les instructions ci-dessus et lancez : vous pouvez changer d’écran, parler à IRIS ou fermer la fenêtre, le travail se poursuit.</div>
          </div>
        ) : null}
        {tasks.map((t) => (
          <div className="list-item" key={t.id} style={{ cursor: 'pointer' }} onClick={() => show(t.id)}>
            <div className="grow">
              <div className="row">
                <strong>{t.title}</strong>
                <span className={`pill ${STATUS[t.status]?.cls || ''}`}>{STATUS[t.status]?.label || t.status}</span>
                <span className="small muted">{t.agent}</span>
              </div>
              <div className="small muted">{formatDate(t.created_at)}{t.completed_at ? ` → ${formatDate(t.completed_at)}` : ''}{t.error ? ` · ${t.error}` : ''}</div>
            </div>
            {t.status === 'running' || t.status === 'pending' ? (
              <button className="btn sm" onClick={(e) => { e.stopPropagation(); api.post(`/api/tasks/${t.id}/cancel`) }}>Annuler</button>
            ) : (
              <button className="btn ghost sm" onClick={(e) => { e.stopPropagation(); api.delete(`/api/tasks/${t.id}`) }}>×</button>
            )}
          </div>
        ))}
      </div>
      {open ? (
        <Modal title={open.title} onClose={() => setOpen(null)} actions={<button className="btn" onClick={() => setOpen(null)}>Fermer</button>}>
          <p className="small muted">{open.instructions}</p>
          {open.result ? <Markdown text={open.result} /> : <p className="muted">{open.status === 'running' ? 'En cours…' : open.error || 'Cette tâche s’est terminée sans produire de résultat.'}</p>}
        </Modal>
      ) : null}
    </div>
  )
}
