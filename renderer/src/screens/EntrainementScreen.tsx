import React, { useCallback, useEffect, useRef, useState } from 'react'
import { BtnIcone, Field, Holo, Liste, Puces, Rangee, TopBar } from '../components/ui'
import { IcoCoche, IcoLecture, IcoPause, IcoPoubelle } from '../components/icons'
import { CarteLunettesRequises } from '../components/LunettesRequises'
import { ApiError, api, messageErreur, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import { BlocRefus, VideCompact, chrono, dateLisible, dureeLisible, lireRefus, pluriel, useTic, type Refus } from './CoursScreen'
import './AccessibiliteScreen.css'
import './CoursScreen.css'

/* =========================================================================
   « Entraînement » : compter ses séries à la voix et chronométrer le repos,
   téléphone dans le sac, mains sur la barre.

   Ce que fait le service (backend/iris/entrainement.py), dit à l'écran :
   - IRIS ne compte PAS les répétitions : aucun capteur de mouvement des
     lunettes n'est accessible. C'est vous qui dites « série terminée » ;
   - le repos est chronométré sur l'ordinateur et annoncé (« 10 secondes »,
     « Repos terminé ») : une mise en veille retarde l'annonce ;
   - l'historique est chiffré, suit la durée de conservation, et rien n'est
     écrit en mémoire suspendue.

   Le compte à rebours affiché part de la dernière valeur donnée par le
   service et se recale à chaque événement entrainement.etat.

   Lunettes d'abord : démarrer, compter une série et reprendre exigent les
   lunettes ; mettre en pause, terminer et effacer l'historique, jamais.
   ========================================================================= */

interface Seance {
  actif: boolean
  id?: string
  exercice?: string | null
  series?: number
  series_cibles?: number | null
  repos_s?: number
  repos_restant_s?: number
  debut?: string
  etat?: string
  en_pause?: boolean
  duree_s?: number
  fin?: string | null
  limite?: string
  memoire_suspendue?: string | null
  ecoute_active?: boolean
  enregistree?: boolean
}

interface SeancePassee {
  id: string
  exercice: string | null
  series: number
  series_cibles: number | null
  repos_s: number
  debut: string
  fin: string | null
  duree_s: number
  pauses_s?: number
}

const REPOS_RAPIDES = ['30', '60', '90', '120', '180']
const REPOS_MIN = 10
const REPOS_MAX = 900
const LIMITE_DEFAUT =
  'IRIS ne compte pas les répétitions : aucun capteur de mouvement des lunettes n’est accessible. Dites « série terminée » à la fin de chaque série. Le repos est chronométré sur l’ordinateur : une mise en veille retarde l’annonce.'

// Ce qui ne doit jamais attendre les lunettes : s'arrêter.
const SANS_LUNETTES = new Set(['pause', 'terminer', 'etat'])

function Anneau({ restant, total, pause }: { restant: number; total: number; pause: boolean }): JSX.Element {
  const r = 52
  const circonference = 2 * Math.PI * r
  const fraction = total > 0 ? Math.min(1, Math.max(0, restant / total)) : 0
  return (
    <div className={`q-anneau ${pause ? 'pause' : ''}`} role="timer" aria-label={`Repos : ${dureeLisible(Math.ceil(restant))} restantes${pause ? ', en pause' : ''}`}>
      <svg viewBox="0 0 120 120" aria-hidden="true">
        <circle className="fond" cx="60" cy="60" r={r} fill="none" strokeWidth="9" />
        <circle
          className="avance"
          cx="60"
          cy="60"
          r={r}
          fill="none"
          strokeWidth="9"
          strokeLinecap="round"
          strokeDasharray={circonference}
          strokeDashoffset={circonference * (1 - fraction)}
        />
      </svg>
      <div className="centre" aria-hidden="true">
        <span className="temps">{chrono(Math.ceil(restant))}</span>
        <span className="legende">{pause ? 'Repos en pause' : 'Repos'}</span>
      </div>
    </div>
  )
}

export function EntrainementScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { settings, updateSettings, toast, presence, exigerLunettes } = useStore()
  const [seance, setSeance] = useState<Seance | null>(null)
  const [recuA, setRecuA] = useState(() => Date.now())
  const [erreurEtat, setErreurEtat] = useState('')
  const [exercice, setExercice] = useState('')
  const [series, setSeries] = useState('')
  const [repos, setRepos] = useState<string>(() => String(Number(settings?.entrainement_repos_s) || 90))
  const [enCours, setEnCours] = useState<string | null>(null)
  const [refus, setRefus] = useState<(Refus & { reessayer: () => void }) | null>(null)
  const [annonce, setAnnonce] = useState('')
  const [bilan, setBilan] = useState<{ phrase: string; enregistree: boolean; memoire_suspendue: string | null } | null>(null)
  const [historique, setHistorique] = useState<SeancePassee[] | null>(null)
  const [histoInfo, setHistoInfo] = useState<{ memoire_suspendue: string | null; retention_jours: number }>({ memoire_suspendue: null, retention_jours: 0 })
  const vivant = useRef(true)
  const reposTouche = useRef(false)

  const absentes = presence !== null && !presence.presentes
  const actif = Boolean(seance?.actif)
  const tic = useTic(actif, 250)

  // Les réglages arrivent parfois après l'ouverture de l'écran : le repos par défaut suit tant qu'il n'a pas été touché.
  useEffect(() => {
    const defaut = Number(settings?.entrainement_repos_s)
    if (defaut && !reposTouche.current) setRepos(String(defaut))
  }, [settings?.entrainement_repos_s])

  const chargerHistorique = useCallback(async () => {
    try {
      const r = await api.get('/api/entrainement/seances')
      if (!vivant.current) return
      setHistorique(Array.isArray(r?.seances) ? r.seances : [])
      setHistoInfo({ memoire_suspendue: r?.memoire_suspendue || null, retention_jours: Number(r?.retention_jours) || 0 })
    } catch (err) {
      if (vivant.current) toast(messageErreur(err), 'error')
    }
  }, [toast])

  const charger = useCallback(async () => {
    try {
      const r = await api.get('/api/entrainement/etat')
      if (!vivant.current) return
      setSeance(r && typeof r === 'object' ? r : { actif: false })
      setRecuA(Date.now())
      setErreurEtat('')
    } catch (err) {
      if (vivant.current) setErreurEtat(messageErreur(err))
    }
  }, [])

  useEffect(() => {
    vivant.current = true
    charger()
    chargerHistorique()
    // La voix fait avancer la même séance : l'écran suit l'événement (séance imbriquée, jamais « type »).
    const off = api.on((e: IrisEvent) => {
      if (e.type !== 'entrainement.etat') return
      const s: Seance = e.seance && typeof e.seance === 'object' ? e.seance : { actif: false }
      setSeance(s)
      setRecuA(Date.now())
      if (typeof e.annonce === 'string' && e.annonce) setAnnonce(e.annonce)
      if (!s.actif) chargerHistorique()
    })
    return () => {
      vivant.current = false
      off()
    }
  }, [charger, chargerHistorique])

  const demarrer = async (): Promise<void> => {
    if (enCours) return
    const reposS = Math.round(Number(repos))
    if (!Number.isFinite(reposS) || reposS < REPOS_MIN || reposS > REPOS_MAX) {
      setRefus({ message: `Le repos dure de ${REPOS_MIN} secondes à ${REPOS_MAX / 60} minutes.`, consentement: null, reessayer: () => undefined })
      return
    }
    const cibles = series.trim() ? Math.round(Number(series)) : null
    if (cibles !== null && (!Number.isFinite(cibles) || cibles < 1 || cibles > 50)) {
      setRefus({ message: 'Le nombre de séries visé va de 1 à 50.', consentement: null, reessayer: () => undefined })
      return
    }
    if (!exigerLunettes('Entraînement')) return
    setEnCours('demarrer')
    setRefus(null)
    setBilan(null)
    try {
      const r = await api.post('/api/entrainement/demarrer', { exercice: exercice.trim() || null, series_cibles: cibles, repos_s: reposS, parler: true })
      if (!vivant.current) return
      const { phrase, ...etat } = r || {}
      setSeance(etat as Seance)
      setRecuA(Date.now())
      setAnnonce(typeof phrase === 'string' ? phrase : '')
    } catch (err) {
      if (!vivant.current) return
      if (err instanceof ApiError && err.status === 409) charger()
      const x = lireRefus(err)
      if (x) setRefus({ ...x, reessayer: () => demarrer() })
    } finally {
      if (vivant.current) setEnCours(null)
    }
  }

  const commande = async (action: string): Promise<void> => {
    if (enCours) return
    if (!SANS_LUNETTES.has(action) && !exigerLunettes('Entraînement')) return
    setEnCours(action)
    setRefus(null)
    try {
      const r = await api.post('/api/entrainement/commande', { action, parler: true })
      if (!vivant.current) return
      const { phrase, ...etat } = r || {}
      setSeance(etat as Seance)
      setRecuA(Date.now())
      if (typeof phrase === 'string') setAnnonce(phrase)
      if (action === 'terminer') {
        setBilan({ phrase: typeof phrase === 'string' ? phrase : 'Séance terminée.', enregistree: Boolean(r?.enregistree), memoire_suspendue: r?.memoire_suspendue || null })
        chargerHistorique()
      }
    } catch (err) {
      if (!vivant.current) return
      if (err instanceof ApiError && err.status === 409) charger()
      const x = lireRefus(err)
      if (x) setRefus({ ...x, reessayer: () => commande(action) })
    } finally {
      if (vivant.current) setEnCours(null)
    }
  }

  const supprimerSeance = async (s: SeancePassee): Promise<void> => {
    if (!window.confirm(`Effacer la séance du ${dateLisible(s.debut)} de l’historique ? Cette action est définitive.`)) return
    try {
      await api.delete(`/api/entrainement/seances/${encodeURIComponent(s.id)}`)
      toast('Séance effacée.', 'success')
      chargerHistorique()
    } catch (err) {
      toast(messageErreur(err), 'error')
    }
  }

  const retenirRepos = (): void => {
    const reposS = Math.round(Number(repos))
    if (!Number.isFinite(reposS) || reposS < REPOS_MIN || reposS > REPOS_MAX) return
    updateSettings({ entrainement_repos_s: reposS })
      .then(() => toast(`Repos par défaut : ${dureeLisible(reposS)}.`, 'success'))
      .catch((err: unknown) => toast(messageErreur(err), 'error'))
  }

  const ecoule = (tic - recuA) / 1000
  const etat = seance?.etat || 'effort'
  const enPause = etat === 'pause'
  const reposRestant = etat === 'repos' ? Math.max(0, (seance?.repos_restant_s || 0) - Math.max(0, ecoule)) : seance?.repos_restant_s || 0
  const duree = (seance?.duree_s || 0) + (enPause ? 0 : Math.max(0, ecoule))
  const nSeries = seance?.series || 0
  const cibles = seance?.series_cibles || null
  const libelleEtat = enPause ? 'En pause' : etat === 'repos' ? 'Repos' : cibles && nSeries >= cibles ? 'Objectif atteint' : `Série ${nSeries + 1} en cours`
  const reposDefaut = Number(settings?.entrainement_repos_s) || 90

  return (
    <div className="ecran">
      <TopBar titre="Entraînement" />
      <div className="contenu">
        {absentes && !actif ? <CarteLunettesRequises fonction="Entraînement à la voix" /> : null}
        {erreurEtat ? <div className="bloc-note erreur" role="alert">{erreurEtat}</div> : null}
        {seance === null && !erreurEtat ? <div className="empty">Chargement…</div> : null}

        {/* ------------------------------------------------------------ nouvelle séance */}
        {seance !== null && !actif ? (
          <>
            {bilan ? (
              <div className={`bloc-note ${bilan.enregistree ? 'ok' : 'attention'}`} role="status">
                {bilan.phrase}
                {bilan.enregistree ? ' Séance ajoutée à l’historique.' : ''}
              </div>
            ) : null}
            <div className="carte">
              <VideCompact
                glyphe="haltere"
                texte="Vos séries, votre repos"
                petit="Dites « série terminée » après chaque série : IRIS compte les séries et annonce la fin du repos."
              />
            </div>
            <div className="carte q-formulaire">
              <div className="q-grille-2">
                <Field label="Exercice (facultatif)">
                  <input className="input" value={exercice} maxLength={80} placeholder="Ex. : squats" onChange={(e) => setExercice(e.target.value)} />
                </Field>
                <Field label="Séries visées (facultatif)">
                  <input className="input" type="number" min={1} max={50} inputMode="numeric" value={series} placeholder="Ex. : 4" onChange={(e) => setSeries(e.target.value)} />
                </Field>
              </div>
              <div className="col" style={{ gap: 8 }}>
                <div style={{ fontWeight: 700 }}>Repos entre les séries</div>
                <Puces
                  options={REPOS_RAPIDES.map((s) => ({ id: s, label: dureeLisible(Number(s)) }))}
                  valeur={REPOS_RAPIDES.includes(repos) ? repos : ''}
                  onChange={(v) => {
                    reposTouche.current = true
                    setRepos(v)
                  }}
                />
                <div className="row wrap" style={{ gap: 10 }}>
                  <input
                    className="input q-champ-court"
                    type="number"
                    min={REPOS_MIN}
                    max={REPOS_MAX}
                    inputMode="numeric"
                    aria-label="Repos, en secondes"
                    value={repos}
                    onChange={(e) => {
                      reposTouche.current = true
                      setRepos(e.target.value)
                    }}
                  />
                  <span className="muted">secondes</span>
                  {Number(repos) !== reposDefaut ? (
                    <Holo taille="mini" variante="sombre" onClick={retenirRepos}>Retenir par défaut</Holo>
                  ) : null}
                </div>
              </div>
              <Holo disabled={Boolean(enCours)} onClick={demarrer}><IcoLecture /> {enCours === 'demarrer' ? 'Démarrage…' : 'Démarrer la séance'}</Holo>
              {refus ? <BlocRefus refus={refus} onFermer={() => setRefus(null)} onReessayer={refus.reessayer} /> : null}
            </div>
          </>
        ) : null}

        {/* ------------------------------------------------------------ séance en cours */}
        {actif && seance ? (
          <>
            <div className="carte q-seance">
              <div className="exercice">{seance.exercice || 'Séance d’entraînement'}</div>
              <span className={`q-etat-seance ${enPause ? 'pause' : etat === 'repos' ? 'repos' : ''}`} aria-live="polite">{libelleEtat}</span>
              <div className="q-compteur" aria-label={`${pluriel(nSeries, 'série faite', 'séries faites')}${cibles ? ` sur ${cibles}` : ''}`}>{nSeries}</div>
              <div className="q-compteur-sous" aria-hidden="true">
                {nSeries > 1 ? 'séries faites' : 'série faite'}
                {cibles ? ` sur ${cibles}` : ''}
              </div>

              {etat === 'repos' || (enPause && reposRestant > 0) ? (
                <Anneau restant={reposRestant} total={seance.repos_s || 1} pause={enPause} />
              ) : (
                <div className="col" style={{ alignItems: 'center', gap: 2 }}>
                  <span className="q-chrono" style={{ fontSize: 44 }} role="timer" aria-label={`Durée de la séance : ${dureeLisible(duree)}`}>{chrono(duree)}</span>
                  <span className="muted">durée de la séance{enPause ? ' (en pause)' : ''}</span>
                </div>
              )}

              <div className="q-boutons-seance">
                <Holo disabled={Boolean(enCours)} onClick={() => commande('serie')}><IcoCoche /> Série terminée</Holo>
                {enPause ? (
                  <Holo variante="sombre" disabled={Boolean(enCours)} onClick={() => commande('reprendre')}><IcoLecture /> Reprendre</Holo>
                ) : (
                  <Holo variante="sombre" disabled={Boolean(enCours)} onClick={() => commande('pause')}><IcoPause /> Pause</Holo>
                )}
                <Holo variante="rouge" disabled={Boolean(enCours)} onClick={() => commande('terminer')}>Terminer</Holo>
              </div>
              <div className="q-note">Repos réglé : {dureeLisible(seance.repos_s)}.</div>
            </div>

            {refus ? <BlocRefus refus={refus} onFermer={() => setRefus(null)} onReessayer={refus.reessayer} /> : null}
            {seance.memoire_suspendue ? (
              <div className="bloc-note attention">Mémoire suspendue : cette séance ne sera pas ajoutée à l’historique.</div>
            ) : null}
          </>
        ) : null}

        {annonce && !(bilan && !actif && bilan.phrase === annonce) ? (
          <div className="q-dit" role="status"><span className="qui">IRIS a dit</span>{annonce}</div>
        ) : null}

        {/* ------------------------------------------------------------ voix et limites */}
        <div className="carte col" style={{ gap: 10 }}>
          <h3 style={{ margin: 0 }}>À la voix</h3>
          <div className="q-note">Commencez par « {String(settings?.wake_word || 'Dis-moi Iris')} », puis :</div>
          <ul className="q-phrases">
            <li>« commence une séance d’entraînement de squats, quatre séries, repos une minute »</li>
            <li>« série terminée »</li>
            <li>« pause »</li>
            <li>« reprends »</li>
            <li>« on en est où ? »</li>
            <li>« termine l’entraînement »</li>
          </ul>
          <ul className="liste-limites">
            <li>{seance?.limite || LIMITE_DEFAUT}</li>
          </ul>
        </div>

        {/* ------------------------------------------------------------ historique */}
        <h2 className="section-sous">Historique</h2>
        {histoInfo.memoire_suspendue ? (
          <div className="bloc-note attention">Mémoire suspendue (mode invité ou zone sans mémoire) : aucune nouvelle séance n’est enregistrée.</div>
        ) : null}
        {historique === null ? <div className="empty">Chargement…</div> : null}
        {historique !== null && historique.length === 0 ? (
          <div className="carte q-note">Aucune séance enregistrée. Une séance est gardée à la fin si au moins une série a été comptée.</div>
        ) : null}
        {historique !== null && historique.length > 0 ? (
          <Liste>
            {historique.map((s) => (
              <Rangee
                key={s.id}
                compacte
                titre={s.exercice || 'Séance d’entraînement'}
                sous={`${dateLisible(s.debut)} · ${pluriel(s.series, 'série')}${s.series_cibles ? ` (objectif ${s.series_cibles})` : ''} · ${dureeLisible(s.duree_s)} · repos ${dureeLisible(s.repos_s)}`}
                droite={
                  <BtnIcone aria-label="Effacer cette séance" title="Effacer cette séance" onClick={() => supprimerSeance(s)}>
                    <IcoPoubelle />
                  </BtnIcone>
                }
              />
            ))}
          </Liste>
        ) : null}
        <div className="q-note">
          L’historique est chiffré sur cet ordinateur. Conservation : {histoInfo.retention_jours ? `${histoInfo.retention_jours} jours` : 'sans limite de durée'} (réglée dans Confidentialité).
        </div>
      </div>
    </div>
  )
}
