import React, { useEffect, useState } from 'react'
import { Holo, TopBar } from '../components/ui'
import { IcoAvertissement, IcoLecture, IcoStop } from '../components/icons'
import { CarteLunettesRequises } from '../components/LunettesRequises'
import { api, estLunettesRequises, messageErreur, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import './AccessibiliteScreen.css'

/* =========================================================================
   « Écoute assistée » (EXPÉRIMENTAL) : le son ambiant, débruité et amplifié,
   rejoué dans les lunettes, pour entendre un peu plus fort la personne en face.

   Ce n'est pas une aide auditive, et l'écran le dit avant tout. La latence est
   celle que le service MESURE (backend/iris/ecoute_assistee.py), avec ce
   qu'elle compte et ne compte pas ; elle n'est jamais promise.
   ========================================================================= */

interface EtatAssistee {
  actif: boolean
  latence_ms: number | null
  mesure_latence: 'aucune' | 'micro' | 'partielle' | string
  gain_db: number
  reduction: number
  sortie: string | null
  apprentissage: boolean
  en_attente_micro: boolean
  pause_voix: boolean
  blocs_joues: number
  blocs_sautes: number
  raison: string | null
  experimental?: boolean
  local?: boolean
  avertissement?: string
  limites?: string[]
}

const EXPLICATION_MESURE: Record<string, string> = {
  micro: 'De l’arrivée du son du micro à sa sortie. Ne compte ni le retard du Bluetooth, dans les deux sens, ni le quart de seconde de chaque bloc de son.',
  partielle: 'Traitement dans IRIS seulement : l’heure d’arrivée du son du micro n’était pas disponible. Le retard réel est plus grand.',
  aucune: 'Pas encore mesurée : la mesure commence quand le son arrive.'
}

export function EcouteAssisteeScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { settings, updateSettings, toast, presence, exigerLunettes } = useStore()
  const [etat, setEtat] = useState<EtatAssistee | null>(null)
  const [erreur, setErreur] = useState('')
  const [occupe, setOccupe] = useState(false)
  const [gain, setGain] = useState<number>(Number(settings?.ecoute_assistee_gain_db ?? 6))
  const [reduction, setReduction] = useState<number>(Number(settings?.ecoute_assistee_reduction ?? 60))

  const absentes = presence !== null && !presence.presentes

  const charger = async (): Promise<void> => {
    try {
      setEtat(await api.get('/api/ecoute/assistee'))
    } catch (err) {
      setErreur(messageErreur(err))
    }
  }

  useEffect(() => {
    charger()
    return api.on((e: IrisEvent) => {
      if (e.type === 'ecoute_assistee.etat') {
        const { type: _t, ...reste } = e
        setEtat((s) => ({ ...(s || ({} as EtatAssistee)), ...(reste as Partial<EtatAssistee>) }) as EtatAssistee)
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    setGain(Number(settings?.ecoute_assistee_gain_db ?? 6))
    setReduction(Number(settings?.ecoute_assistee_reduction ?? 60))
  }, [settings?.ecoute_assistee_gain_db, settings?.ecoute_assistee_reduction])

  const actif = Boolean(etat?.actif)

  const demarrer = async (): Promise<void> => {
    if (!exigerLunettes('Écoute assistée')) return
    setOccupe(true)
    setErreur('')
    try {
      await api.post('/api/ecoute/assistee/demarrer', { gain_db: gain, reduction })
      await charger()
    } catch (err) {
      // 409 : aucune sortie acceptable (effet Larsen), mode confidentiel… avec la raison exacte.
      if (!estLunettesRequises(err)) setErreur(messageErreur(err))
    } finally {
      setOccupe(false)
    }
  }

  const arreter = async (): Promise<void> => {
    setOccupe(true)
    setErreur('')
    try {
      await api.post('/api/ecoute/assistee/arreter')
      await charger()
    } catch (err) {
      setErreur(messageErreur(err))
    } finally {
      setOccupe(false)
    }
  }

  /** En marche, le réglage s'applique tout de suite (le service règle le traitement en cours). */
  const engager = (): void => {
    const change = gain !== Number(settings?.ecoute_assistee_gain_db) || reduction !== Number(settings?.ecoute_assistee_reduction)
    if (!change) return
    if (actif) {
      api.post('/api/ecoute/assistee/demarrer', { gain_db: gain, reduction }).catch((err) => {
        if (!estLunettesRequises(err)) toast(messageErreur(err), 'error')
      })
    } else {
      updateSettings({ ecoute_assistee_gain_db: gain, ecoute_assistee_reduction: reduction }).catch((err: unknown) => toast(messageErreur(err), 'error'))
    }
  }

  const mesure = etat?.mesure_latence || 'aucune'

  return (
    <div className="ecran">
      <TopBar titre="Écoute assistée" />
      <div className="contenu">
        <span className="bandeau-experimental"><IcoAvertissement width={18} height={18} /> Expérimental</span>
        <div className="bloc-note attention" role="note">
          {etat?.avertissement || 'Écoute assistée expérimentale : elle ne remplace pas une aide auditive et n’est pas un appareil médical.'}
        </div>

        {absentes ? <CarteLunettesRequises /> : null}

        <div className="carte col" style={{ gap: 14 }}>
          <div className="row wrap" style={{ gap: 10 }}>
            {actif ? (
              <Holo taille="petit" variante="rouge" disabled={occupe} onClick={arreter}><IcoStop /> Arrêter</Holo>
            ) : (
              <Holo taille="petit" disabled={occupe} onClick={demarrer}><IcoLecture /> Démarrer</Holo>
            )}
            <span className="pill" aria-live="polite">{actif ? 'En marche' : 'Arrêtée'}</span>
          </div>
          {erreur ? <div className="bloc-note erreur" role="alert">{erreur}</div> : null}
          {etat?.raison ? <div className="bloc-note attention">{etat.raison}</div> : null}
          {actif && etat?.apprentissage ? <div className="bloc-note">Apprentissage du bruit ambiant (1,5 s) : la sortie reste muette pendant ce temps.</div> : null}
          {actif && etat?.en_attente_micro ? <div className="bloc-note attention">En attente du micro : aucun son n’arrive.</div> : null}
          {actif && etat?.pause_voix ? <div className="bloc-note">En pause pendant qu’IRIS parle.</div> : null}
          {etat?.sortie ? <div className="small muted">Sortie audio : {etat.sortie}</div> : null}

          <div className="col" style={{ gap: 4 }} aria-live="polite">
            <div style={{ fontWeight: 700, fontSize: 17 }}>Latence mesurée</div>
            <div style={{ fontSize: 32, fontWeight: 800 }}>{actif && etat?.latence_ms !== null && etat?.latence_ms !== undefined ? `${Math.round(etat.latence_ms)} ms` : '—'}</div>
            <div className="small muted" style={{ lineHeight: 1.45 }}>{EXPLICATION_MESURE[mesure] || EXPLICATION_MESURE.aucune}</div>
            {actif && etat && etat.blocs_joues + etat.blocs_sautes > 0 ? (
              <div className="small muted">
                {etat.blocs_joues} bloc{etat.blocs_joues > 1 ? 's' : ''} joué{etat.blocs_joues > 1 ? 's' : ''}, {etat.blocs_sautes} sauté{etat.blocs_sautes > 1 ? 's' : ''} pour rester en direct.
              </div>
            ) : null}
          </div>
        </div>

        <div className="carte col" style={{ gap: 16 }}>
          <div className="curseur">
            <div className="entete">
              <label htmlFor="gain-assistee">Amplification</label>
              <output htmlFor="gain-assistee">+{gain} dB</output>
            </div>
            <input
              id="gain-assistee"
              type="range"
              min={0}
              max={18}
              step={1}
              value={gain}
              onChange={(e) => setGain(Number(e.target.value))}
              onMouseUp={engager}
              onKeyUp={engager}
              onTouchEnd={engager}
              onBlur={engager}
            />
            <div className="aide">Commencez bas. Le niveau est plafonné dans IRIS, mais le volume réel dépend aussi du volume des lunettes.</div>
          </div>
          <div className="curseur">
            <div className="entete">
              <label htmlFor="reduction-assistee">Réduction du bruit</label>
              <output htmlFor="reduction-assistee">{reduction}</output>
            </div>
            <input
              id="reduction-assistee"
              type="range"
              min={0}
              max={100}
              step={5}
              value={reduction}
              onChange={(e) => setReduction(Number(e.target.value))}
              onMouseUp={engager}
              onKeyUp={engager}
              onTouchEnd={engager}
              onBlur={engager}
            />
            <div className="aide">Plus haut : moins de bruit de fond, mais la voix peut sonner métallique.</div>
          </div>
        </div>

        <div className="carte">
          <h3>Avertissements</h3>
          <ul className="liste-limites">
            <li>Effet Larsen : IRIS refuse de jouer le son dans les haut-parleurs de l’ordinateur. Avec une amplification élevée, un sifflement reste possible ; baissez-la ou arrêtez.</li>
            <li>Volume : un son trop fort peut abîmer l’audition. Commencez au plus bas et montez doucement.</li>
            <li>Ce n’est pas un appareil médical : aucun réglage selon un audiogramme, aucune homologation.</li>
            {(etat?.limites || []).map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
          <div className="small muted" style={{ marginTop: 10 }}>Tout est traité sur cet ordinateur ; rien n’est enregistré.</div>
        </div>
      </div>
    </div>
  )
}
