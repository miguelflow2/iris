import React, { useEffect, useRef, useState } from 'react'
import { Field, Holo, TopBar } from '../components/ui'
import { CarteLunettesRequises } from '../components/LunettesRequises'
import { api, estLunettesRequises, messageErreur, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import './AccessibiliteScreen.css'

/* =========================================================================
   « Bouton des lunettes » : un appui sur un bouton physique déclenche
   « décris ce qu'il y a devant moi », sans sortir le téléphone.

   Le fabricant ne documente pas ce qu'émettent les boutons : IRIS APPREND le
   bouton en observant les paquets Bluetooth (backend/iris/bouton_lunettes.py) —
   2 s sans toucher, puis quelques secondes d'appuis. L'échec est un résultat
   possible et normal (beaucoup de boutons ne sortent pas des lunettes) : il est
   dit tel quel, sans promesse.
   ========================================================================= */

interface EtatBouton {
  signature: string | null
  mode: string
  apprentissage: boolean
  phase: string | null
  lunettes_connectees: boolean
  description_disponible: boolean
  derniere_action: { action: string; raison: string | null; ts: number } | null
  limites?: string[]
}

interface ModeVision {
  id: string
  nom: string
}

type Phase = { etat: 'reference' | 'appuyez'; fin: number; total: number } | null

const DUREE_APPUI_S = 6

const ACTIONS: Record<string, string> = {
  decrire: 'description lancée',
  refuse: 'refusé',
  indisponible: 'description indisponible',
  erreur: 'erreur'
}

export function BoutonLunettesScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { nav, updateSettings, toast, presence, exigerLunettes } = useStore()
  const [etat, setEtat] = useState<EtatBouton | null>(null)
  const [modes, setModes] = useState<ModeVision[]>([])
  const [phase, setPhase] = useState<Phase>(null)
  const [restant, setRestant] = useState(0)
  const [enCours, setEnCours] = useState(false)
  const [resultat, setResultat] = useState<{ etat: string; signature: string | null; raison: string | null } | null>(null)
  const [erreur, setErreur] = useState('')
  const minuterie = useRef<number | null>(null)

  const absentes = presence !== null && !presence.presentes

  const charger = async (): Promise<void> => {
    try {
      setEtat(await api.get('/api/lunettes/bouton'))
    } catch (err) {
      setErreur(messageErreur(err))
    }
  }

  useEffect(() => {
    charger()
    api
      .get('/api/accessibilite/modes')
      .then((r) => setModes(Array.isArray(r?.modes) ? r.modes : []))
      .catch(() => undefined)
    const off = api.on((e: IrisEvent) => {
      if (e.type === 'bouton.apprentissage') {
        if (e.etat === 'reference' || e.etat === 'appuyez') {
          const total = Number(e.secondes) || (e.etat === 'reference' ? 2 : DUREE_APPUI_S)
          setPhase({ etat: e.etat, fin: Date.now() + total * 1000, total })
        } else {
          setPhase(null)
          if (e.etat === 'appris' || e.etat === 'echec') setResultat({ etat: e.etat, signature: e.signature ?? null, raison: e.raison ?? null })
          charger()
        }
      } else if (e.type === 'bouton.lunettes') {
        setEtat((s) => (s ? { ...s, derniere_action: { action: String(e.action), raison: e.raison ?? null, ts: Date.now() / 1000 } } : s))
      } else if (e.type === 'glasses.connected' || e.type === 'glasses.disconnected') {
        charger()
      }
    })
    return () => {
      off()
      if (minuterie.current) window.clearInterval(minuterie.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Compte à rebours affiché, recalculé depuis l'heure de fin (pas de dérive si l'onglet est lent).
  useEffect(() => {
    if (minuterie.current) window.clearInterval(minuterie.current)
    if (!phase) {
      setRestant(0)
      return
    }
    const maj = (): void => setRestant(Math.max(0, Math.ceil((phase.fin - Date.now()) / 1000)))
    maj()
    minuterie.current = window.setInterval(maj, 200)
    return () => {
      if (minuterie.current) window.clearInterval(minuterie.current)
    }
  }, [phase])

  const apprendre = async (): Promise<void> => {
    if (!exigerLunettes('Apprendre le bouton des lunettes')) return
    setEnCours(true)
    setErreur('')
    setResultat(null)
    try {
      // La requête dure tout l'apprentissage (environ 8 s) ; les phases arrivent par événements.
      const r = await api.post('/api/lunettes/bouton/apprendre', { secondes: DUREE_APPUI_S })
      setResultat({ etat: String(r?.etat), signature: r?.signature ?? null, raison: r?.raison ?? null })
      await charger()
    } catch (err) {
      if (!estLunettesRequises(err)) setErreur(messageErreur(err))
    } finally {
      setEnCours(false)
      setPhase(null)
    }
  }

  const oublier = async (): Promise<void> => {
    if (!window.confirm('Oublier le bouton appris ? Un appui ne déclenchera plus rien.')) return
    try {
      await api.delete('/api/lunettes/bouton')
      setResultat(null)
      await charger()
      toast('Bouton oublié.', 'success')
    } catch (err) {
      toast(messageErreur(err), 'error')
    }
  }

  const connectees = Boolean(etat?.lunettes_connectees)
  const derniere = etat?.derniere_action

  return (
    <div className="ecran">
      <TopBar titre="Bouton des lunettes" />
      <div className="contenu">
        {absentes ? <CarteLunettesRequises /> : null}

        <div className="carte col" style={{ gap: 8 }}>
          <h3 style={{ margin: 0 }}>Décrire d’un appui</h3>
          <div className="desc">
            Si votre bouton envoie un signal à l’ordinateur, IRIS peut l’apprendre : un appui prendra alors une photo avec les lunettes et la décrira à voix haute,
            quelques secondes plus tard.
          </div>
        </div>

        {etat && !connectees && !absentes ? (
          <div className="bloc-note attention">
            L’apprentissage exige les lunettes connectées à CET ordinateur en Bluetooth basse énergie (une connexion au téléphone ne suffit pas).{' '}
            <button type="button" className="btn sm" onClick={() => nav.ouvrir('connecter')}>Connecter les lunettes</button>
          </div>
        ) : null}

        {/* ------------------------------------------------------------ apprentissage */}
        <div className="carte col" style={{ gap: 12 }}>
          {phase ? (
            <div className={`compte-rebours ${phase.etat}`} role="status" aria-live="assertive">
              <div className="chiffre" aria-hidden="true">{restant}</div>
              <div className="consigne">
                {phase.etat === 'reference' ? 'Ne touchez à rien…' : 'Appuyez maintenant sur le bouton, deux ou trois fois'}
              </div>
              <div className="small muted">
                {phase.etat === 'reference' ? 'IRIS observe ce que les lunettes envoient sans appui.' : `Encore ${restant} seconde${restant > 1 ? 's' : ''}.`}
              </div>
            </div>
          ) : (
            <Holo disabled={enCours || (etat !== null && !connectees)} onClick={apprendre}>
              {enCours ? 'Préparation…' : etat?.signature ? 'Réapprendre le bouton' : 'Apprendre le bouton'}
            </Holo>
          )}
          {erreur ? <div className="bloc-note erreur" role="alert">{erreur}</div> : null}
          {resultat?.etat === 'appris' ? (
            <div className="bloc-note ok" role="status">Bouton appris. Appuyez-y pour essayer : une description devrait suivre en quelques secondes.</div>
          ) : resultat?.etat === 'echec' ? (
            <div className="bloc-note erreur" role="alert">Échec de l’apprentissage : {resultat.raison || 'aucun signal utilisable reçu.'}</div>
          ) : null}
        </div>

        {/* ------------------------------------------------------------ bouton appris */}
        <div className="carte col" style={{ gap: 12 }}>
          <h3 style={{ margin: 0 }}>Bouton enregistré</h3>
          {etat?.signature ? (
            <>
              <div className="small muted">Signal appris :</div>
              <div className="signature">{etat.signature}</div>
            </>
          ) : (
            <div className="desc">Aucun bouton appris pour le moment.</div>
          )}
          <Field label="Ce que déclenche l’appui" hint="Le mode « Décris l’écran » capture l’écran de l’ordinateur au lieu de prendre une photo.">
            <select
              className="select"
              value={etat?.mode || 'scene'}
              onChange={(e) => updateSettings({ bouton_description_mode: e.target.value }).then(charger).catch((err: unknown) => toast(messageErreur(err), 'error'))}
            >
              {(modes.length ? modes : [{ id: 'scene', nom: 'Qu’est-ce qu’il y a devant moi ?' }]).map((m) => (
                <option key={m.id} value={m.id}>{m.nom}</option>
              ))}
            </select>
          </Field>
          {derniere ? (
            <div className="small" aria-live="polite">
              Dernier appui reçu à {new Date(derniere.ts * 1000).toLocaleTimeString('fr-CA', { hour: '2-digit', minute: '2-digit' })} : {ACTIONS[derniere.action] || derniere.action}
              {derniere.raison ? ` — ${derniere.raison}` : ''}
            </div>
          ) : null}
          {etat?.signature ? (
            <Holo taille="petit" variante="contour" style={{ alignSelf: 'flex-start' }} onClick={oublier}>Oublier ce bouton</Holo>
          ) : null}
        </div>

        <div className="carte">
          <h3>Limites</h3>
          <ul className="liste-limites">
            {(etat?.limites || []).map((l) => (
              <li key={l}>{l}</li>
            ))}
            <li>Beaucoup de lunettes gèrent leurs boutons en interne (volume, lecture) sans rien envoyer : dans ce cas, aucune application ne peut les utiliser, et l’apprentissage échoue.</li>
          </ul>
        </div>
      </div>
    </div>
  )
}
