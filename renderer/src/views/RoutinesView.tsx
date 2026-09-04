import React, { useCallback, useEffect, useState } from 'react'
import { api, formatDate, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

const TOOL_LABEL: Record<string, string> = {
  open_application: 'Ouvrir l’application', open_url: 'Ouvrir l’adresse', play_youtube: 'Lancer sur YouTube', open_path: 'Ouvrir le fichier/dossier',
  run_command: 'Exécuter la commande', type_text: 'Taper le texte', press_keys: 'Touches', click_text: 'Cliquer sur le texte', mouse_click: 'Clic',
  mouse_move: 'Déplacer la souris', mouse_drag: 'Glisser', scroll: 'Défiler', lock_computer: 'Verrouiller', set_reminder: 'Rappel', write_file: 'Écrire le fichier'
}

export function RoutinesView(): JSX.Element {
  const { toast, settings } = useStore()
  const [routines, setRoutines] = useState<any[]>([])
  const [recording, setRecording] = useState<any | null>(null)
  const [name, setName] = useState('')
  const [trigger, setTrigger] = useState('')
  const [reminders, setReminders] = useState<any[]>([])
  const [remText, setRemText] = useState('')
  const [remMinutes, setRemMinutes] = useState('10')

  const load = useCallback(async () => {
    const r = await api.get('/api/routines')
    setRoutines(r.routines)
    setRecording(r.recording)
    setReminders((await api.get('/api/reminders')).reminders)
  }, [])
  useEffect(() => {
    load()
    return api.on((e: IrisEvent) => {
      if (['routine.updated', 'routine.deleted', 'routine.recording', 'routine.ran', 'reminder.updated', 'reminder.deleted', 'reminder.due'].includes(e.type)) load()
    })
  }, [load])

  const startRecording = async () => {
    if (!name.trim()) return toast('Donnez un nom à la routine.', 'error')
    await api.post('/api/routines/record/start', { name: name.trim(), trigger: trigger.trim() || name.trim() })
    toast('Enregistrement démarré : faites vos demandes à IRIS, chaque action sera mémorisée.', 'info')
  }
  const stopRecording = async () => {
    const r = await api.post('/api/routines/record/stop')
    toast(r.routine ? `Routine « ${r.routine.name} » enregistrée (${r.routine.steps.length} étapes).` : 'Aucune action enregistrée.', r.routine ? 'success' : 'error')
    setName(''); setTrigger('')
  }

  return (
    <div className="page">
      <h1>Routines et rappels</h1>
      <p className="lead">Une phrase, une séquence d’actions. Dites « {settings?.wake_word}, mode travail » et IRIS rejoue la routine instantanément, sans passer par l’IA.</p>

      <div className="card col">
        <div className="row"><strong>Nouvelle routine par enregistrement</strong>{recording ? <span className="pill err">● enregistrement : {recording.name} ({recording.steps?.length || 0} actions)</span> : null}</div>
        <div className="grid-2">
          <input className="input" placeholder="Nom (ex. Mode travail)" value={name} onChange={(e) => setName(e.target.value)} disabled={Boolean(recording)} />
          <input className="input" placeholder="Phrase déclencheur (ex. mode travail)" value={trigger} onChange={(e) => setTrigger(e.target.value)} disabled={Boolean(recording)} />
        </div>
        <div className="row">
          {recording ? <button className="btn danger sm" onClick={stopRecording}>Arrêter et enregistrer</button> : <button className="btn primary sm" onClick={startRecording}>Commencer l’enregistrement</button>}
          <span className="small muted">Ou dites simplement : « {settings?.wake_word}, crée une routine "mode travail" qui ouvre VS Code, Spotify et mon dossier projet ».</span>
        </div>
      </div>

      <div className="list" style={{ marginTop: 16 }}>
        {/* État vide : le « lead » explique déjà le concept ; ici on nomme le geste suivant (le bouton d’enregistrement). */}
        {routines.length === 0 ? (
          <div className="empty">
            <div style={{ fontSize: 16, color: 'var(--text)' }}>Aucune routine enregistrée.</div>
            <div className="small" style={{ marginTop: 8 }}>Appuyez sur « Commencer l’enregistrement » : IRIS retient chaque action que vous faites, puis les rejoue à la phrase de votre choix.</div>
          </div>
        ) : null}
        {routines.map((r) => (
          <div className="list-item" key={r.id}>
            <div className="grow">
              <div className="row"><strong>{r.name}</strong><span className="pill">« {r.trigger} »</span><span className="small muted">{r.runs} exécution{r.runs > 1 ? 's' : ''}</span></div>
              <div className="small muted">{r.steps.map((s: any, i: number) => `${i + 1}. ${TOOL_LABEL[s.tool] || s.tool} ${Object.values(s.args || {}).join(' ').slice(0, 40)}`).join(' · ')}</div>
            </div>
            <button className="btn sm" onClick={() => api.post(`/api/routines/${r.id}/run`).then(() => toast(`Routine « ${r.name} » lancée.`, 'success')).catch((e) => toast(e.message, 'error'))}>Lancer</button>
            <button className="btn ghost sm" onClick={() => api.delete(`/api/routines/${r.id}`)}>×</button>
          </div>
        ))}
      </div>

      <h2>Rappels</h2>
      <div className="card col">
        <div className="row">
          <input className="input" placeholder="Rappelle-moi de…" value={remText} onChange={(e) => setRemText(e.target.value)} />
          <input className="input" style={{ width: 90 }} type="number" min={1} value={remMinutes} onChange={(e) => setRemMinutes(e.target.value)} />
          <span className="small muted">min</span>
          <button className="btn primary sm" disabled={!remText.trim()} onClick={() => api.post('/api/reminders', { text: remText.trim(), minutes: Number(remMinutes) || 10 }).then(() => { setRemText(''); toast('Rappel programmé.', 'success') }).catch((e) => toast(e.message, 'error'))}>Programmer</button>
        </div>
        <div className="small muted">À la voix : « {settings?.wake_word}, rappelle-moi d’appeler Paul dans 20 minutes ». IRIS l’annonce à voix haute à l’heure dite.</div>
        {reminders.map((r) => (
          <div className="row between" key={r.id} style={{ borderTop: '1px solid var(--border)', paddingTop: 6 }}>
            <span>{r.text} <span className="small muted">· {formatDate(r.due_at)}</span></span>
            <button className="btn ghost sm" onClick={() => api.delete(`/api/reminders/${r.id}`)}>×</button>
          </div>
        ))}
      </div>
    </div>
  )
}
