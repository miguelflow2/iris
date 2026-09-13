import React, { useCallback, useEffect, useRef, useState } from 'react'
import { BtnIcone, Field, Holo, Liste, Rangee, TopBar } from '../components/ui'
import { IcoHorloge, IcoPoubelle } from '../components/icons'
import { api, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   Routines (porte la partie « routines » de l'ancienne RoutinesView) : enregistrement
   d'une nouvelle routine (nom + phrase déclencheur), liste des routines avec leurs
   étapes, lancement et suppression. Les rappels vivent désormais dans IA › Minuteur :
   une rangée en bas y conduit.
   ========================================================================= */

const TOOL_LABEL: Record<string, string> = {
  open_application: 'Ouvrir l’application',
  open_url: 'Ouvrir l’adresse',
  play_youtube: 'Lancer sur YouTube',
  open_path: 'Ouvrir le fichier/dossier',
  run_command: 'Exécuter la commande',
  type_text: 'Taper le texte',
  press_keys: 'Touches',
  click_text: 'Cliquer sur le texte',
  mouse_click: 'Clic',
  mouse_move: 'Déplacer la souris',
  mouse_drag: 'Glisser',
  scroll: 'Défiler',
  lock_computer: 'Verrouiller',
  set_reminder: 'Rappel',
  write_file: 'Écrire le fichier'
}

function messageErreur(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

function resumeEtapes(steps: any[]): string {
  return steps
    .map((s: any, i: number) => {
      const args = Object.values(s?.args || {})
        .map((v) => (typeof v === 'string' ? v : JSON.stringify(v)))
        .join(' ')
        .slice(0, 40)
      return `${i + 1}. ${TOOL_LABEL[s?.tool] || s?.tool || '?'} ${args}`.trim()
    })
    .join(' · ')
}

export function RoutinesScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  void params
  const { nav, toast, settings } = useStore()
  const [routines, setRoutines] = useState<any[]>([])
  const [recording, setRecording] = useState<any | null>(null)
  const [name, setName] = useState('')
  const [trigger, setTrigger] = useState('')
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
      const r = await api.get('/api/routines')
      if (!monte.current) return
      setRoutines(Array.isArray(r?.routines) ? r.routines : [])
      setRecording(r?.recording || null)
    } catch (err) {
      if (monte.current) toast(messageErreur(err), 'error')
    }
  }, [toast])

  useEffect(() => {
    load()
    return api.on((e: IrisEvent) => {
      if (['routine.updated', 'routine.deleted', 'routine.recording', 'routine.ran'].includes(e.type)) load()
    })
  }, [load])

  const motReveil: string = settings?.wake_word || 'Dis-moi Iris'

  const commencer = async (): Promise<void> => {
    if (!name.trim()) {
      toast('Donnez un nom à la routine.', 'error')
      return
    }
    setOccupe('record')
    try {
      await api.post('/api/routines/record/start', { name: name.trim(), trigger: trigger.trim() || name.trim() })
      toast('Enregistrement démarré : faites vos demandes à IRIS, chaque action sera mémorisée.', 'info')
      await load()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const arreter = async (): Promise<void> => {
    setOccupe('record')
    try {
      const r = await api.post('/api/routines/record/stop')
      const routine = r?.routine
      toast(
        routine ? `Routine « ${routine.name} » enregistrée (${(routine.steps || []).length} étapes).` : 'Aucune action enregistrée.',
        routine ? 'success' : 'error'
      )
      setName('')
      setTrigger('')
      await load()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const lancer = async (r: any): Promise<void> => {
    setOccupe(String(r.id))
    try {
      await api.post(`/api/routines/${r.id}/run`)
      toast(`Routine « ${r.name} » lancée.`, 'success')
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const supprimer = async (r: any): Promise<void> => {
    if (!window.confirm(`Supprimer la routine « ${r.name} » ?`)) return
    try {
      await api.delete(`/api/routines/${r.id}`)
      await load()
    } catch (err) {
      toast(messageErreur(err), 'error')
    }
  }

  const enCours = Boolean(recording)
  const nbActions: number = Array.isArray(recording?.steps) ? recording.steps.length : 0

  return (
    <div className="ecran">
      <TopBar titre="Routines" />
      <div className="contenu">
        <div className="carte">
          <h3>Nouvelle routine par enregistrement</h3>
          <div className="desc">
            Une phrase, une séquence d’actions. Dites « {motReveil}, mode travail » et IRIS rejoue la routine instantanément, sans passer par l’IA.
          </div>
          {enCours ? (
            <div style={{ marginTop: 12 }}>
              <span className="pill err">
                <span className="dot rec" /> enregistrement : {recording?.name} ({nbActions} action{nbActions > 1 ? 's' : ''})
              </span>
            </div>
          ) : null}
          <div className="col" style={{ marginTop: 14, gap: 12 }}>
            <Field label="Nom">
              <input className="input" placeholder="ex. Mode travail" value={name} onChange={(e) => setName(e.target.value)} disabled={enCours} />
            </Field>
            <Field label="Phrase déclencheur" hint="Facultatif : par défaut, c’est le nom de la routine.">
              <input className="input" placeholder="ex. mode travail" value={trigger} onChange={(e) => setTrigger(e.target.value)} disabled={enCours} />
            </Field>
            {enCours ? (
              <Holo variante="rouge" disabled={occupe === 'record'} onClick={arreter}>
                {occupe === 'record' ? 'Arrêt…' : 'Arrêter et enregistrer'}
              </Holo>
            ) : (
              <Holo disabled={occupe === 'record' || !name.trim()} onClick={commencer}>
                {occupe === 'record' ? 'Démarrage…' : 'Commencer l’enregistrement'}
              </Holo>
            )}
            <div className="small muted" style={{ lineHeight: 1.4 }}>
              Ou dites simplement : « {motReveil}, crée une routine "mode travail" qui ouvre VS Code, Spotify et mon dossier projet ».
            </div>
          </div>
        </div>

        {routines.length === 0 ? (
          <div className="empty">
            <div style={{ fontSize: 16, color: 'var(--text)' }}>Aucune routine enregistrée.</div>
            <div className="small" style={{ marginTop: 8, lineHeight: 1.4 }}>
              Appuyez sur « Commencer l’enregistrement » : IRIS retient chaque action que vous faites, puis les rejoue à la phrase de votre choix.
            </div>
          </div>
        ) : (
          <div className="col" style={{ gap: 10 }}>
            {routines.map((r) => {
              const runs: number = Number(r.runs) || 0
              const steps: any[] = Array.isArray(r.steps) ? r.steps : []
              return (
                <div className="carte serree" key={r.id}>
                  <div className="row" style={{ alignItems: 'flex-start' }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 700, fontSize: 17 }}>{r.name}</div>
                      <div className="muted" style={{ marginTop: 2 }}>« {r.trigger} »</div>
                      <div className="small muted" style={{ marginTop: 4 }}>
                        {runs} exécution{runs > 1 ? 's' : ''} · {steps.length} étape{steps.length > 1 ? 's' : ''}
                      </div>
                      {steps.length ? (
                        <div className="small muted" style={{ marginTop: 6, lineHeight: 1.4, wordBreak: 'break-word' }}>{resumeEtapes(steps)}</div>
                      ) : null}
                    </div>
                    <div className="row" style={{ gap: 4, flex: 'none' }}>
                      <button type="button" className="btn sm" disabled={occupe === String(r.id)} onClick={() => lancer(r)}>
                        {occupe === String(r.id) ? '…' : 'Lancer'}
                      </button>
                      <BtnIcone aria-label="Supprimer la routine" title="Supprimer" onClick={() => supprimer(r)}>
                        <IcoPoubelle />
                      </BtnIcone>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        <Liste>
          <Rangee icone={<IcoHorloge />} titre="Rappels" sous="Les rappels sont dans IA › Minuteur" onClick={() => nav.allerOnglet('ia')} />
        </Liste>
      </div>
    </div>
  )
}
