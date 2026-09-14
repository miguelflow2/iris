import React, { useCallback, useEffect, useRef, useState } from 'react'
import { BtnIcone, CarteReglage, Holo, TopBar } from '../components/ui'
import { IcoActualiser, IcoChevronD, IcoChevronG, IcoHautParleur, IcoStop } from '../components/icons'
import { api, estLunettesRequises, messageErreur, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import { dateLisible, dureeLisible, dureeMesuree, jourLocal, VideCompact } from './CoursScreen'
import './AccessibiliteScreen.css'
import './CoursScreen.css'

/* =========================================================================
   « Résumé de la journée » : ce qu'IRIS a VRAIMENT noté de la journée, en
   quatre listes (fait, reste, rappels, à retenir) et un texte à écouter.

   Ce que fait le service (backend/iris/quotidien.py), dit à l'écran :
   - le résumé est construit seulement à partir de ce qui est noté sur
     l'ordinateur (tâches, routines, conversations, souvenirs, journal
     d'écoute s'il est activé, cours, reçus, rappels) ; ce qui s'est passé
     sans IRIS n'y figure pas (champ « limite ») ;
   - avec l'accord « Texte de vos demandes », le moteur VELA rédige le texte à
     partir de ces faits ; sinon, une version rédigée sur l'ordinateur, et la
     réponse le dit (« local », « note ») ;
   - lu à voix haute : jamais en mode confidentiel ni en mode invité (409).

   Lunettes d'abord : ÉCOUTER le résumé exige les lunettes ; le consulter et
   régler le résumé automatique, jamais.
   ========================================================================= */

interface Resume {
  date: string
  texte: string
  sections: { fait: string[]; reste: string[]; rappels: string[]; a_retenir: string[] }
  local: boolean
  note?: string | null
  limite?: string
  duree_ms?: number
  contenu?: boolean
  memorise?: boolean
  parle?: boolean
}

const SECTIONS: { cle: keyof Resume['sections']; titre: string; vide: string }[] = [
  { cle: 'fait', titre: 'Fait', vide: 'Rien de noté comme fait ce jour-là.' },
  { cle: 'reste', titre: 'Reste à faire', vide: 'Rien de noté comme restant à faire.' },
  { cle: 'rappels', titre: 'Rappels', vide: 'Aucun rappel ce jour-là ni le lendemain.' },
  { cle: 'a_retenir', titre: 'À retenir', vide: 'Aucun souvenir retenu ce jour-là.' }
]

function decaler(jour: string, jours: number): string {
  const [a, m, j] = jour.split('-').map(Number)
  const d = new Date(a, (m || 1) - 1, j || 1)
  d.setDate(d.getDate() + jours)
  return jourLocal(d)
}

function titreJour(jour: string): string {
  const aujourdhui = jourLocal()
  if (jour === aujourdhui) return 'Aujourd’hui'
  if (jour === decaler(aujourdhui, -1)) return 'Hier'
  const texte = dateLisible(`${jour}T12:00:00`, false)
  return texte.charAt(0).toUpperCase() + texte.slice(1)
}

export function ResumeJourneeScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  const { settings, updateSettings, toast, exigerLunettes } = useStore()
  const [jour, setJour] = useState<string>(() => (typeof params?.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(params.date) ? params.date : jourLocal()))
  const [resume, setResume] = useState<Resume | null>(null)
  const [chargement, setChargement] = useState(false)
  const [erreur, setErreur] = useState('')
  const [lecture, setLecture] = useState(false)
  const [erreurLecture, setErreurLecture] = useState('')
  const [infoLecture, setInfoLecture] = useState<{ memorise: boolean; parle: boolean } | null>(null)
  const [heure, setHeure] = useState<string>(() => String(settings?.daily_summary_time || '21:00'))
  const vivant = useRef(true)
  const jourRef = useRef(jour)
  const aujourdhui = jourLocal()

  useEffect(() => {
    jourRef.current = jour
  }, [jour])

  useEffect(() => {
    setHeure(String(settings?.daily_summary_time || '21:00'))
  }, [settings?.daily_summary_time])

  const charger = useCallback(async (date: string) => {
    setChargement(true)
    setErreur('')
    try {
      const r: Resume = await api.get(`/api/resume/jour?date=${encodeURIComponent(date)}`)
      if (!vivant.current || jourRef.current !== date) return
      setResume(r)
    } catch (err) {
      if (vivant.current && jourRef.current === date) setErreur(messageErreur(err))
    } finally {
      if (vivant.current && jourRef.current === date) setChargement(false)
    }
  }, [])

  useEffect(() => {
    vivant.current = true
    return () => {
      vivant.current = false
    }
  }, [])

  useEffect(() => {
    setResume(null)
    setInfoLecture(null)
    setErreurLecture('')
    charger(jour)
  }, [jour, charger])

  // Le résumé du soir (boucle quotidienne) ou « résume ma journée » dit à la voix : l'écran reprend le
  // texte de l'événement. Pas de relecture complète : elle redemanderait une rédaction au moteur.
  useEffect(
    () =>
      api.on((e: IrisEvent) => {
        if (e.type !== 'resume.jour' || e.date !== jourRef.current || typeof e.texte !== 'string' || !e.texte) return
        setResume((r) => (r ? { ...r, texte: e.texte, local: Boolean(e.local), note: r.texte === e.texte ? r.note : null } : r))
      }),
    []
  )

  const ecouter = async (): Promise<void> => {
    if (lecture) return
    if (!exigerLunettes('Résumé de la journée lu à voix haute')) return
    setLecture(true)
    setErreurLecture('')
    setInfoLecture(null)
    try {
      const r: Resume = await api.post('/api/resume/jour/parler', { date: jour })
      if (!vivant.current) return
      setResume(r)
      setInfoLecture({ memorise: Boolean(r.memorise), parle: Boolean(r.parle) })
    } catch (err) {
      if (vivant.current && !estLunettesRequises(err)) setErreurLecture(messageErreur(err))
    } finally {
      if (vivant.current) setLecture(false)
    }
  }

  const arreterVoix = (): void => {
    api.post('/api/voice/stop_speaking').catch((err) => toast(messageErreur(err), 'error'))
  }

  const reglage = (patch: Record<string, unknown>): void => {
    updateSettings(patch).catch((err: unknown) => toast(messageErreur(err), 'error'))
  }

  const enregistrerHeure = (): void => {
    if (/^\d{2}:\d{2}$/.test(heure) && heure !== settings?.daily_summary_time) reglage({ daily_summary_time: heure })
  }

  const automatique = settings?.daily_summary_enabled !== false

  return (
    <div className="ecran">
      <TopBar
        titre="Résumé de la journée"
        droite={
          <BtnIcone aria-label="Actualiser le résumé" title="Actualiser" disabled={chargement} onClick={() => charger(jour)}>
            <IcoActualiser />
          </BtnIcone>
        }
      />
      <div className="contenu">
        {/* ------------------------------------------------------------ date */}
        <div className="q-navigation-date">
          <BtnIcone plein aria-label="Jour précédent" onClick={() => setJour((j) => decaler(j, -1))}><IcoChevronG /></BtnIcone>
          <div className="col" style={{ alignItems: 'center', gap: 4 }}>
            <strong style={{ fontSize: 20 }}>{titreJour(jour)}</strong>
            <input
              className="input"
              type="date"
              aria-label="Choisir le jour"
              value={jour}
              max={aujourdhui}
              style={{ maxWidth: 190 }}
              onChange={(e) => {
                if (/^\d{4}-\d{2}-\d{2}$/.test(e.target.value)) setJour(e.target.value)
              }}
            />
          </div>
          <BtnIcone plein aria-label="Jour suivant" disabled={jour >= aujourdhui} onClick={() => setJour((j) => decaler(j, 1))}><IcoChevronD /></BtnIcone>
        </div>

        {/* ------------------------------------------------------------ écouter */}
        <div className="q-actions">
          <Holo disabled={lecture || chargement} onClick={ecouter} style={{ flex: 1 }}>
            <IcoHautParleur /> {lecture ? 'Préparation…' : 'Écouter le résumé'}
          </Holo>
          <Holo taille="petit" variante="sombre" onClick={arreterVoix}><IcoStop /> Couper la voix</Holo>
        </div>
        {erreurLecture ? <div className="bloc-note erreur" role="alert">{erreurLecture}</div> : null}
        {infoLecture ? (
          <div className={`bloc-note ${infoLecture.parle ? 'ok' : 'attention'}`} role="status">
            {infoLecture.parle ? 'Résumé envoyé à la voix d’IRIS.' : 'La voix d’IRIS n’a pas pu lire le résumé : il reste affiché ci-dessous.'}{' '}
            {infoLecture.memorise ? 'Il est retenu dans votre mémoire (un résumé par jour, remplacé à chaque nouvelle écoute).' : 'Il n’a pas été retenu dans la mémoire (journée vide, ou mémoire suspendue).'}
          </div>
        ) : null}

        {erreur ? <div className="bloc-note erreur" role="alert">{erreur}</div> : null}
        {chargement && !resume ? (
          <div className="carte col" style={{ gap: 8 }} aria-live="polite">
            <div style={{ fontWeight: 700 }}>IRIS rassemble ce qu’elle a noté…</div>
            <div className="progress indet"><div /></div>
          </div>
        ) : null}

        {/* ------------------------------------------------------------ résumé */}
        {resume ? (
          <>
            <div className="carte col" style={{ gap: 10 }} aria-live="polite">
              {resume.contenu === false ? (
                <VideCompact glyphe="soleil" texte="Rien de noté ce jour-là" petit={resume.texte || undefined} />
              ) : (
                <div className="q-resume-texte">{resume.texte}</div>
              )}
              <div className="q-meta">
                <span className={`etiquette-locale ${resume.local ? 'local' : 'moteur'}`}>
                  {resume.local ? 'Rédigé sur cet ordinateur' : 'Rédigé par le moteur VELA à partir de vos données'}
                </span>
                {typeof resume.duree_ms === 'number' ? <span>Préparé en {dureeMesuree(resume.duree_ms)}</span> : null}
              </div>
              {resume.note ? <div className="bloc-note attention">{resume.note}</div> : null}
            </div>

            {SECTIONS.map(({ cle, titre, vide }) => {
              const elements = resume.sections?.[cle] || []
              return (
                <section key={cle} className="carte col" style={{ gap: 8 }} aria-label={titre}>
                  <h3 style={{ margin: 0 }}>
                    {titre} <span className="muted" style={{ fontSize: 16 }}>· {elements.length}</span>
                  </h3>
                  {elements.length ? (
                    <ul className="q-liste-points">
                      {elements.map((t, i) => (
                        <li key={`${cle}-${i}`}>{t}</li>
                      ))}
                    </ul>
                  ) : (
                    <div className="q-note">{vide}</div>
                  )}
                </section>
              )
            })}

            {resume.limite ? <div className="bloc-note">{resume.limite}</div> : null}
          </>
        ) : null}

        {/* ------------------------------------------------------------ résumé automatique */}
        <h2 className="section-sous">Chaque soir</h2>
        <CarteReglage
          titre="Résumé automatique"
          desc="À l’heure choisie, si IRIS est ouverte sur cet ordinateur : le résumé du jour est préparé, retenu dans la mémoire, puis lu à voix haute si la voix d’IRIS peut parler. Jamais lu en mode confidentiel ni en mode invité."
          on={automatique}
          onChange={(v) => reglage({ daily_summary_enabled: v })}
        />
        <div className="carte col" style={{ gap: 8 }}>
          <label className="field" htmlFor="heure-resume">
            <span>Heure du résumé</span>
          </label>
          <div className="row wrap" style={{ gap: 10 }}>
            <input
              id="heure-resume"
              className="input"
              type="time"
              value={heure}
              disabled={!automatique}
              style={{ maxWidth: 160 }}
              onChange={(e) => setHeure(e.target.value)}
              onBlur={enregistrerHeure}
            />
            {heure !== settings?.daily_summary_time && /^\d{2}:\d{2}$/.test(heure) ? (
              <Holo taille="mini" variante="sombre" onClick={enregistrerHeure}>Enregistrer</Holo>
            ) : null}
          </div>
          <div className="q-note">
            IRIS vérifie l’heure une fois par minute : le résumé part au plus tard une minute après l’heure choisie, ou peu après l’ouverture
            d’IRIS si l’heure est déjà passée. Il part une fois par jour ; relancer IRIS après l’heure peut le faire repartir. Ordinateur éteint ou
            en veille, rien ne part. Vous pouvez aussi dire « {String(settings?.wake_word || 'Dis-moi Iris')}, résume ma journée ».
          </div>
        </div>
      </div>
    </div>
  )
}
