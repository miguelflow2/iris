import React, { useEffect, useState } from 'react'
import { CarteReglage, Holo, TopBar } from '../components/ui'
import { IcoPoubelle, IcoRecherche, IcoTelecharger } from '../components/icons'
import { api, messageErreur } from '../lib/api'
import { useStore } from '../lib/store'
import './AccessibiliteScreen.css'

/* =========================================================================
   « Journal de la journée » : ce qu'IRIS a entendu et retenu, retrouvable par
   mots et par dates, effaçable par plage.

   Consulter, exporter et effacer ses données restent permis SANS lunettes (Loi 25).
   Seul l'allumage du journal continu les exige : il ouvre le micro.
   Les entrées sont chiffrées sur cet ordinateur (backend/iris/journal.py) et
   supprimées physiquement au-delà de la durée de conservation.
   ========================================================================= */

interface Entree {
  id: string
  ts: string
  texte: string
  source: string
  score?: number
}

const SOURCES: Record<string, string> = {
  'sous-titres': 'entendu',
  photo: 'description retenue'
}

function quand(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('fr-CA', { dateStyle: 'medium', timeStyle: 'short' })
}

/** « invite », « zone:Clinique » (raisons de MemoryService.suspendre) en mots lisibles. */
function libelleSuspension(raison: string): string {
  const morceaux = raison.split(',').map((r) => r.trim()).filter(Boolean)
  return morceaux
    .map((r) => (r === 'invite' ? 'mode invité' : r.startsWith('zone:') ? `zone sans mémoire : ${r.slice(5)}` : r))
    .join(', ')
}

function libelleRetention(jours: number): string {
  if (!jours) return 'illimitée'
  if (jours === 1) return '24 heures'
  return `${jours} jours`
}

export function JournalScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { settings, updateSettings, toast, exigerLunettes, ecoute, rafraichirEcoute, invite, zone } = useStore()
  const [q, setQ] = useState('')
  const [debut, setDebut] = useState('')
  const [fin, setFin] = useState('')
  const [entrees, setEntrees] = useState<Entree[] | null>(null)
  const [chargement, setChargement] = useState(false)
  const [erreur, setErreur] = useState('')
  const [effacement, setEffacement] = useState(false)

  const chercher = async (): Promise<void> => {
    setChargement(true)
    setErreur('')
    const p = new URLSearchParams()
    if (q.trim()) p.set('q', q.trim())
    if (debut) p.set('debut', debut)
    if (fin) p.set('fin', fin)
    p.set('limit', '200')
    try {
      const r = await api.get(`/api/journal?${p.toString()}`)
      setEntrees(Array.isArray(r?.entrees) ? r.entrees : [])
    } catch (err) {
      setErreur(messageErreur(err))
    } finally {
      setChargement(false)
    }
  }

  useEffect(() => {
    chercher()
    rafraichirEcoute().catch(() => undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const basculerJournal = (v: boolean): void => {
    if (v && !exigerLunettes('Journal continu')) return
    updateSettings({ journal_continu: v }).catch((err: unknown) => toast(messageErreur(err), 'error'))
  }

  const effacerPlage = async (tout: boolean): Promise<void> => {
    if (!tout && !debut && !fin) {
      toast('Choisissez au moins une date de début ou de fin pour effacer une plage.', 'info')
      return
    }
    const phrase = tout
      ? 'Effacer TOUT le journal ? Cette suppression est définitive.'
      : `Effacer les entrées ${debut ? `du ${debut}` : 'depuis le début'} ${fin ? `au ${fin} inclus` : 'jusqu’à maintenant'} ? Cette suppression est définitive.`
    if (!window.confirm(phrase)) return
    setEffacement(true)
    const p = new URLSearchParams()
    if (tout) p.set('tout', 'true')
    else {
      if (debut) p.set('debut', debut)
      if (fin) p.set('fin', fin)
    }
    try {
      const r = await api.delete(`/api/journal?${p.toString()}`)
      const n = Number(r?.supprimees) || 0
      toast(`${n} entrée${n > 1 ? 's' : ''} effacée${n > 1 ? 's' : ''}.`, 'success')
      await chercher()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      setEffacement(false)
    }
  }

  const exporter = async (): Promise<void> => {
    if (!entrees?.length) {
      toast('Aucune entrée à exporter.', 'info')
      return
    }
    const contenu = entrees.map((e) => `${quand(e.ts)}\t${SOURCES[e.source] || e.source}\t${e.texte}`).join('\n') + '\n'
    try {
      const chemin = await window.iris.saveFile(`journal-iris-${new Date().toISOString().slice(0, 10)}.txt`, contenu)
      if (chemin) toast('Journal exporté.', 'success')
    } catch (err) {
      toast(messageErreur(err), 'error')
    }
  }

  const retention = Number(settings?.retention_days) || 0
  const suspendue = (ecoute?.memoire_suspendue ? libelleSuspension(ecoute.memoire_suspendue) : null) || (invite?.actif ? 'mode invité' : zone?.dans_zone ? `zone sans mémoire${zone.zone_nom ? ` : ${zone.zone_nom}` : ''}` : null)

  return (
    <div className="ecran">
      <TopBar titre="Journal de la journée" />
      <div className="contenu">
        <CarteReglage
          titre="Journal continu"
          desc="IRIS garde chaque phrase entendue et reconnue sur cet ordinateur, chiffrée. Le son n’est jamais gardé. L’écoute du micro reste active tant que ce réglage l’est. Les descriptions d’images que vous choisissez de retenir s’ajoutent aussi au journal."
          on={Boolean(settings?.journal_continu)}
          onChange={basculerJournal}
        />
        {suspendue ? (
          <div className="bloc-note attention" role="status">Mémorisation suspendue ({suspendue}) : le journal n’écrit rien en ce moment.</div>
        ) : null}
        {settings?.journal_continu && ecoute?.raison ? <div className="bloc-note attention">{ecoute.raison}</div> : null}

        <div className="carte col" style={{ gap: 12 }}>
          <form
            className="recherche"
            onSubmit={(e) => {
              e.preventDefault()
              chercher()
            }}
          >
            <IcoRecherche />
            <input aria-label="Rechercher dans le journal" placeholder="Rechercher un mot, un sujet…" value={q} onChange={(e) => setQ(e.target.value)} />
          </form>
          <div className="plage-dates">
            <label className="field">
              <span>Du</span>
              <input className="input" type="date" value={debut} onChange={(e) => setDebut(e.target.value)} />
            </label>
            <label className="field">
              <span>Au (inclus)</span>
              <input className="input" type="date" value={fin} onChange={(e) => setFin(e.target.value)} />
            </label>
          </div>
          <div className="row wrap" style={{ gap: 8 }}>
            <Holo taille="petit" variante="blanc" disabled={chargement} onClick={chercher}>{chargement ? 'Recherche…' : 'Rechercher'}</Holo>
            <Holo taille="petit" variante="sombre" onClick={exporter}><IcoTelecharger /> Exporter</Holo>
          </div>
          <div className="small muted" style={{ lineHeight: 1.45 }}>
            La recherche compare les mots, sans accents : elle ne comprend pas le sens. Sans mot, les entrées les plus récentes s’affichent.
          </div>
        </div>

        {erreur ? <div className="bloc-note erreur" role="alert">{erreur}</div> : null}

        <div className="carte" aria-live="polite">
          {entrees === null ? (
            <div className="small muted">Chargement…</div>
          ) : entrees.length === 0 ? (
            <div className="small muted">Aucune entrée{q || debut || fin ? ' pour cette recherche' : ''}.</div>
          ) : (
            <>
              <div className="small muted" style={{ marginBottom: 4 }}>{entrees.length} entrée{entrees.length > 1 ? 's' : ''}{entrees.length >= 200 ? ' (les 200 premières)' : ''}</div>
              {entrees.map((e) => (
                <div key={e.id} className="journal-entree">
                  <div className="quand">
                    <span>{quand(e.ts)}</span>
                    <span className="pill">{SOURCES[e.source] || e.source}</span>
                  </div>
                  <div className="texte">{e.texte}</div>
                </div>
              ))}
            </>
          )}
        </div>

        <h2 className="section-sous">Effacer</h2>
        <div className="carte col" style={{ gap: 10 }}>
          <div className="desc">Utilise les dates choisies plus haut. La suppression est définitive.</div>
          <div className="row wrap" style={{ gap: 8 }}>
            <Holo taille="petit" variante="rouge" disabled={effacement} onClick={() => effacerPlage(false)}><IcoPoubelle /> Effacer cette plage</Holo>
            <Holo taille="petit" variante="contour" disabled={effacement} onClick={() => effacerPlage(true)}>Tout effacer</Holo>
          </div>
        </div>

        <div className="carte col" style={{ gap: 10 }}>
          <h3 style={{ margin: 0 }}>Durée de conservation</h3>
          <div className="desc">Actuellement : {libelleRetention(retention)}. Au-delà, les entrées sont supprimées physiquement. Ce réglage vaut aussi pour vos souvenirs et messages.</div>
          <select
            className="select"
            style={{ width: 'auto', minWidth: 200, alignSelf: 'flex-start' }}
            aria-label="Durée de conservation"
            value={retention}
            onChange={(e) => updateSettings({ retention_days: Number(e.target.value) }).catch((err: unknown) => toast(messageErreur(err), 'error'))}
          >
            <option value={0}>Illimitée</option>
            <option value={1}>24 heures</option>
            <option value={7}>7 jours</option>
            <option value={30}>30 jours</option>
            <option value={90}>90 jours</option>
          </select>
        </div>
      </div>
    </div>
  )
}
