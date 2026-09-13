import React, { useCallback, useEffect, useState } from 'react'
import { BtnIcone, Field, Holo, Vide } from '../../components/ui'
import { IcoHorlogeDegrade, IcoPoubelle } from '../../components/icons'
import { api, formatDate, type IrisEvent } from '../../lib/api'
import { useStore } from '../../lib/store'
import { messageErreur } from './commun'

/* =========================================================================
   Onglet IA › Minuteur = les rappels (partie « Rappels » de l'ancienne
   RoutinesView). État vide selon la maquette IMG_0715, puis le formulaire.
   GET /api/reminders, POST /api/reminders {text, minutes} ou {text, at:'HH:MM'},
   DELETE /api/reminders/{id} ; événements reminder.updated/deleted/due.
   ========================================================================= */

interface Rappel {
  id: string
  text: string
  due_at: string
  created_at: string
  done: boolean
}

const RE_HEURE = /^([01]?\d|2[0-3]):([0-5]\d)$/

export function Minuteur(): JSX.Element {
  const { toast, settings } = useStore()
  const [rappels, setRappels] = useState<Rappel[]>([])
  const [charge, setCharge] = useState(false)
  const [texte, setTexte] = useState('')
  const [minutes, setMinutes] = useState('')
  const [heure, setHeure] = useState('')
  const [envoi, setEnvoi] = useState(false)

  const charger = useCallback(async () => {
    try {
      const r = await api.get('/api/reminders')
      setRappels(Array.isArray(r?.reminders) ? r.reminders : [])
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      setCharge(true)
    }
  }, [toast])

  useEffect(() => {
    charger().catch(() => undefined)
    return api.on((e: IrisEvent) => {
      if (e.type === 'reminder.updated' || e.type === 'reminder.deleted' || e.type === 'reminder.due') charger().catch(() => undefined)
    })
  }, [charger])

  const programmer = async (): Promise<void> => {
    const t = texte.trim()
    const m = Number(minutes)
    const h = heure.trim()
    if (!t) return toast('Écrivez d’abord le rappel.', 'error')
    const parMinutes = minutes.trim() !== '' && Number.isFinite(m) && m > 0
    const parHeure = RE_HEURE.test(h)
    if (h && !parHeure && !parMinutes) return toast('Heure invalide : utilisez le format HH:MM (ex. 15:30).', 'error')
    if (!parMinutes && !parHeure) return toast('Indiquez un délai en minutes (plus grand que 0) ou une heure au format HH:MM.', 'error')
    setEnvoi(true)
    try {
      const corps: Record<string, unknown> = parMinutes ? { text: t, minutes: m } : { text: t, at: h }
      const cree = await api.post('/api/reminders', corps)
      setTexte('')
      setMinutes('')
      setHeure('')
      // le service publie reminder.updated ; on insère tout de suite pour ne pas attendre l'événement
      if (cree && cree.id) setRappels((liste) => (liste.some((r) => r.id === cree.id) ? liste : [...liste, cree].sort((a, b) => a.due_at.localeCompare(b.due_at))))
      toast('Rappel programmé.', 'success')
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      setEnvoi(false)
    }
  }

  const supprimer = async (id: string): Promise<void> => {
    try {
      await api.delete(`/api/reminders/${id}`)
      setRappels((liste) => liste.filter((r) => r.id !== id))
    } catch (err) {
      toast(messageErreur(err), 'error')
    }
  }

  const actifs = rappels.filter((r) => !r.done)
  const mot = settings?.wake_word || 'Dis-moi Iris'

  return (
    <div className="contenu" style={{ paddingTop: 4 }}>
      {charge && actifs.length === 0 ? <Vide icone={<IcoHorlogeDegrade />} texte="Aucun horaire prévu pour le moment" /> : null}

      {actifs.map((r) => (
        <div className="carte" key={r.id} style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 18, fontWeight: 600, lineHeight: 1.3, wordBreak: 'break-word' }}>{r.text}</div>
            <div className="muted" style={{ marginTop: 4, fontSize: 15 }}>{formatDate(r.due_at)}</div>
          </div>
          <BtnIcone title="Supprimer ce rappel" aria-label={`Supprimer le rappel ${r.text}`} onClick={() => supprimer(r.id)}>
            <IcoPoubelle />
          </BtnIcone>
        </div>
      ))}

      <div className="carte" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Field label="Rappel">
          <input
            className="input"
            placeholder="Rappelle-moi de…"
            value={texte}
            onChange={(e) => setTexte(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                programmer().catch(() => undefined)
              }
            }}
          />
        </Field>
        <div className="grid-2">
          <Field label="Dans (minutes)">
            <input className="input" type="number" min={1} inputMode="numeric" placeholder="ex. 20" value={minutes} onChange={(e) => setMinutes(e.target.value)} />
          </Field>
          <Field label="Ou à (HH:MM)">
            <input className="input" placeholder="ex. 15:30" value={heure} onChange={(e) => setHeure(e.target.value)} />
          </Field>
        </div>
        <Holo disabled={envoi} onClick={() => programmer().catch(() => undefined)}>
          Programmer
        </Holo>
        <div className="small muted" style={{ lineHeight: 1.5 }}>
          À la voix : « {mot}, rappelle-moi d’appeler Paul dans 20 minutes ». IRIS l’annonce à voix haute à l’heure dite.
        </div>
      </div>
    </div>
  )
}
