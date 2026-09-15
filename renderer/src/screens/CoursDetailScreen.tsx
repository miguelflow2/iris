import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BtnIcone, Holo, Markdown, Segmente, TopBar, Vide } from '../components/ui'
import { IcoLecture, IcoPoubelle, IcoRecherche, IcoStop, IcoTelecharger } from '../components/icons'
import { ApiError, api, messageErreur, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import {
  BlocRefus,
  IcoDegrade,
  PastillesCours,
  VideCompact,
  chrono,
  dateLisible,
  dureeLisible,
  lireRefus,
  nomDeFichier,
  pluriel,
  sansAccents,
  useTic,
  type CoursResume,
  type Refus
} from './CoursScreen'
import './AccessibiliteScreen.css'
import './CoursScreen.css'

/* =========================================================================
   Un cours : sa transcription, ses fiches de révision, ses questions d'examen
   probables, son enregistrement audio.

   - Transcription : faite sur l'ordinateur (approximative, sans ponctuation).
   - Fiches et questions : rédigées par le moteur VELA à partir de la
     transcription, sur demande seulement (POST /api/cours/{id}/generer), avec
     l'accord « Texte de vos demandes ». Rédiger exige les lunettes (c'est le
     mode cours) ; relire, exporter, écouter et supprimer, jamais (Loi 25).
   - Questions : des cartes à retourner (question, puis réponse), avec leur
     type et leur difficulté telles que le service les rend.
   ========================================================================= */

interface Question {
  question: string
  reponse: string
  type: string
  difficulte: number
}

type CoursDetail = Omit<CoursResume, 'fiches' | 'questions'> & {
  transcription: { ts: number; texte: string }[]
  fiches: string | null
  questions: Question[] | null
}

type Vue = 'transcription' | 'fiches' | 'questions'
type Quoi = 'fiches' | 'questions' | 'tout'

const TYPES_QUESTION: Record<string, string> = {
  definition: 'Définition',
  application: 'Application',
  comprehension: 'Compréhension',
  calcul: 'Calcul',
  vrai_faux: 'Vrai ou faux'
}
const DIFFICULTES = ['', 'Facile', 'Moyenne', 'Difficile']

/** Une phrase qui se termine par un signe de ponctuation, sans le doubler (lecteurs d'écran). */
function finPhrase(texte: string): string {
  const t = (texte || '').trim()
  return /[.!?…]$/.test(t) ? t : `${t}.`
}

function CarteQuestion({ q, n, retournee, onBasculer }: { q: Question; n: number; retournee: boolean; onBasculer: () => void }): JSX.Element {
  const d = Math.min(3, Math.max(1, Math.round(Number(q.difficulte) || 2)))
  const genre = TYPES_QUESTION[q.type] || 'Question'
  const difficulte = (
    <span className="q-difficulte" title={`Difficulté : ${DIFFICULTES[d]}`}>
      {[1, 2, 3].map((i) => (
        <i key={i} className={i <= d ? 'plein' : ''} />
      ))}
      <span className="small" style={{ marginLeft: 4, fontWeight: 700 }}>{DIFFICULTES[d]}</span>
    </span>
  )
  return (
    <button
      type="button"
      className={`q-retourner ${retournee ? 'retournee' : ''}`}
      aria-pressed={retournee}
      aria-label={retournee ? `Question ${n}, réponse : ${finPhrase(q.reponse)} Touchez pour revoir la question.` : `Question ${n} (${genre}, ${DIFFICULTES[d]}) : ${finPhrase(q.question)} Touchez pour voir la réponse.`}
      onClick={onBasculer}
    >
      <span className="q-flip">
        <span className="q-face recto" aria-hidden="true">
          <span className="haut">
            <span className="genre">{n}. {genre}</span>
            {difficulte}
          </span>
          <span className="q-question">{q.question}</span>
          <span className="indice">Touchez pour voir la réponse</span>
        </span>
        <span className="q-face verso" aria-hidden="true">
          <span className="haut">
            <span className="genre">Réponse {n}</span>
            {difficulte}
          </span>
          <span className="q-reponse">{q.reponse}</span>
          <span className="indice">Touchez pour revoir la question</span>
        </span>
      </span>
    </button>
  )
}

export function CoursDetailScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  const id = String(params?.id ?? '')
  const { nav, toast, exigerLunettes } = useStore()
  const [cours, setCours] = useState<CoursDetail | null>(null)
  const [recuA, setRecuA] = useState(() => Date.now())
  const [introuvable, setIntrouvable] = useState('')
  const [vue, setVue] = useState<Vue>('transcription')
  const [generation, setGeneration] = useState<{ quoi: Quoi; depuis: number } | null>(null)
  const [refus, setRefus] = useState<(Refus & { quoi: Quoi }) | null>(null)
  const [retournees, setRetournees] = useState<Set<number>>(() => new Set())
  const [partiel, setPartiel] = useState('')
  const [filtre, setFiltre] = useState('')
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [audioCharge, setAudioCharge] = useState(false)
  const [audioErreur, setAudioErreur] = useState('')
  const [occupe, setOccupe] = useState(false)
  const vivant = useRef(true)
  const premier = useRef(true)
  const coursRef = useRef<CoursDetail | null>(null)
  const rechargement = useRef<number | null>(null)
  const urlAudio = useRef<string | null>(null)

  const tic = useTic(Boolean(generation) || Boolean(cours?.actif))

  useEffect(() => {
    coursRef.current = cours
  }, [cours])

  const charger = useCallback(async () => {
    if (!id) {
      setIntrouvable('Aucun cours n’a été choisi.')
      return
    }
    try {
      const d: CoursDetail = await api.get(`/api/cours/${encodeURIComponent(id)}`)
      if (!vivant.current) return
      setCours(d)
      setRecuA(Date.now())
      setIntrouvable('')
      if (premier.current) {
        premier.current = false
        if (d.fiches) setVue('fiches')
      }
    } catch (err) {
      if (!vivant.current) return
      if (err instanceof ApiError && err.status === 404) {
        setCours(null)
        setIntrouvable('Ce cours n’existe plus : il a peut-être été supprimé, ou effacé par la durée de conservation.')
      } else if (coursRef.current) {
        toast(messageErreur(err), 'error')
      } else {
        setIntrouvable(messageErreur(err))
      }
    }
  }, [id, toast])

  useEffect(() => {
    vivant.current = true
    charger()
    const planifier = (): void => {
      if (rechargement.current !== null) return
      rechargement.current = window.setTimeout(() => {
        rechargement.current = null
        charger()
      }, 1200)
    }
    const off = api.on((e: IrisEvent) => {
      const c = coursRef.current
      if (e.type === 'cours.etat' && String(e.id || '') === id) {
        if (!c) return
        if (typeof e.erreur_generation === 'string' && e.erreur_generation) {
          // Rédaction en arrière-plan en échec : le cours relu porte « erreur_generation », affichée telle quelle.
          planifier()
          return
        }
        const actif = Boolean(e.actif)
        const etat = typeof e.etat === 'string' ? e.etat : c.etat
        if (c.actif !== actif || c.etat !== etat) {
          planifier()
          return
        }
        setCours((x) =>
          x
            ? {
                ...x,
                duree_s: Number(e.secondes ?? x.duree_s) || 0,
                lignes: Number(e.lignes ?? x.lignes) || 0,
                progression: typeof e.progression === 'number' ? e.progression : x.progression,
                generation:
                  typeof e.fait === 'number' && typeof e.total === 'number'
                    ? { quoi: String(e.quoi || ''), fait: e.fait, total: e.total }
                    : x.generation
              }
            : x
        )
        setRecuA(Date.now())
      } else if (e.type === 'ecoute.sous_titre' && c?.actif) {
        // Cours en direct : les phrases finales s'ajoutent sans relire toute la transcription.
        if (typeof e.final === 'string' && e.final) {
          const debut = Date.parse(c.debut) / 1000
          const ts = Number.isFinite(debut) && Number(e.ts) ? Math.max(0, Number(e.ts) - debut) : c.duree_s
          const texte = e.final
          setCours((x) => (x ? { ...x, transcription: [...x.transcription, { ts, texte }] } : x))
          setPartiel('')
        } else if (typeof e.partiel === 'string') {
          setPartiel(e.partiel)
        }
      }
    })
    return () => {
      vivant.current = false
      off()
      if (rechargement.current !== null) window.clearTimeout(rechargement.current)
      if (urlAudio.current) URL.revokeObjectURL(urlAudio.current)
    }
  }, [charger, id])

  const lignesVisibles = useMemo(() => {
    const t = cours?.transcription || []
    const q = sansAccents(filtre.trim())
    return q ? t.filter((l) => sansAccents(l.texte).includes(q)) : t
  }, [cours?.transcription, filtre])

  const generer = async (quoi: Quoi): Promise<void> => {
    if (generation || !cours) return
    if (!exigerLunettes('Fiches et questions de révision')) return
    setGeneration({ quoi, depuis: Date.now() })
    setRefus(null)
    try {
      const d: CoursDetail & { en_arriere_plan?: boolean; phrase?: string } = await api.post(
        `/api/cours/${encodeURIComponent(cours.id)}/generer`,
        { quoi }
      )
      if (!vivant.current) return
      if (d.en_arriere_plan) {
        // 202 : long cours, la rédaction CONTINUE en arrière-plan. Rien n'est encore rédigé : on le dit, et le
        // cours relu (etat « generation », progression par cours.etat) montre l'avancement réel.
        toast(d.phrase || 'La rédaction continue en arrière-plan.', 'info')
        await charger()
        return
      }
      setCours(d)
      setRetournees(new Set())
      setVue(quoi === 'questions' ? 'questions' : 'fiches')
      toast(quoi === 'questions' ? 'Questions rédigées.' : quoi === 'fiches' ? 'Fiches rédigées.' : 'Fiches et questions rédigées.', 'success')
    } catch (err) {
      if (!vivant.current) return
      const r = lireRefus(err)
      if (r) setRefus({ ...r, quoi })
    } finally {
      if (vivant.current) setGeneration(null)
    }
  }

  const arreter = async (): Promise<void> => {
    if (!cours || occupe) return
    setOccupe(true)
    try {
      await api.post(`/api/cours/${encodeURIComponent(cours.id)}/arreter`)
      setPartiel('')
      await charger()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (vivant.current) setOccupe(false)
    }
  }

  const exporter = async (): Promise<void> => {
    if (!cours) return
    try {
      const b = await api.blob(`/api/cours/${encodeURIComponent(cours.id)}/exporter`)
      const texte = await b.text()
      const chemin = await window.iris.saveFile(`${nomDeFichier(cours.titre, 'cours')}.md`, texte)
      if (chemin) toast('Cours exporté en Markdown.', 'success')
    } catch (err) {
      toast(messageErreur(err), 'error')
    }
  }

  const chargerAudio = async (): Promise<void> => {
    if (!cours?.audio || audioCharge) return
    setAudioCharge(true)
    setAudioErreur('')
    try {
      const b = await api.blob(`/api/album/fichier/${encodeURIComponent(cours.audio)}`)
      if (!vivant.current) return
      if (urlAudio.current) URL.revokeObjectURL(urlAudio.current)
      urlAudio.current = URL.createObjectURL(b)
      setAudioUrl(urlAudio.current)
    } catch (err) {
      if (vivant.current) setAudioErreur(messageErreur(err))
    } finally {
      if (vivant.current) setAudioCharge(false)
    }
  }

  const supprimer = async (): Promise<void> => {
    if (!cours || occupe) return
    const ok = window.confirm(
      `Supprimer « ${cours.titre || 'ce cours'} » ? La transcription, les fiches, les questions et l’enregistrement audio seront effacés de cet ordinateur. Cette action est définitive.`
    )
    if (!ok) return
    setOccupe(true)
    try {
      await api.delete(`/api/cours/${encodeURIComponent(cours.id)}`)
      toast('Cours supprimé.', 'success')
      nav.retour()
    } catch (err) {
      toast(messageErreur(err), 'error')
      if (vivant.current) setOccupe(false)
    }
  }

  const basculer = (i: number): void => {
    setRetournees((s) => {
      const n = new Set(s)
      if (n.has(i)) n.delete(i)
      else n.add(i)
      return n
    })
  }

  if (!cours) {
    return (
      <div className="ecran">
        <TopBar titre="Cours" />
        <div className="contenu">
          {introuvable ? (
            <Vide
              icone={<IcoDegrade glyphe="livre" />}
              texte="Cours introuvable"
              petit={introuvable}
              action={<Holo taille="petit" variante="sombre" onClick={nav.retour}>Retour à mes cours</Holo>}
            />
          ) : (
            <div className="empty">Chargement…</div>
          )}
        </div>
      </div>
    )
  }

  const questions = cours.questions || []
  const secondes = cours.actif ? cours.duree_s + Math.max(0, (tic - recuA) / 1000) : cours.duree_s
  const enTranscription = cours.etat === 'transcription'
  const enRedaction = cours.etat === 'generation'
  const empechement = cours.actif
    ? 'Arrêtez d’abord le cours : les fiches et les questions porteront sur tout le cours.'
    : enTranscription
      ? 'La transcription n’est pas terminée : la rédaction sera possible ensuite.'
      : null
  const secondesGeneration = generation ? Math.max(0, Math.round((tic - generation.depuis) / 1000)) : 0

  const zoneGeneration = (quoi: 'fiches' | 'questions', existe: boolean): JSX.Element => (
    <div className="carte col" style={{ gap: 10 }}>
      {generation || enRedaction ? (
        <div className="col" style={{ gap: 8 }} aria-live="polite">
          <div style={{ fontWeight: 700 }}>
            Rédaction par le moteur VELA en cours…{' '}
            {enRedaction && cours.generation ? (
              <span className="muted">partie {Math.min(cours.generation.fait + 1, cours.generation.total)} sur {cours.generation.total}</span>
            ) : (
              <span className="muted">{dureeLisible(secondesGeneration)}</span>
            )}
          </div>
          {enRedaction && typeof cours.progression === 'number' ? (
            <div className="progress"><div style={{ width: `${Math.round(cours.progression * 100)}%` }} /></div>
          ) : (
            <div className="progress indet"><div /></div>
          )}
          <div className="q-note">
            Un long cours est découpé en parties, rédigées l’une après l’autre : comptez parfois plusieurs minutes. Vous pouvez quitter
            cet écran, la rédaction continue.
          </div>
        </div>
      ) : (
        <div className="q-actions">
          <Holo taille="petit" disabled={Boolean(empechement)} onClick={() => generer(quoi)}>
            {existe ? (quoi === 'fiches' ? 'Réécrire les fiches' : 'Réécrire les questions') : quoi === 'fiches' ? 'Rédiger les fiches' : 'Rédiger les questions'}
          </Holo>
          {!cours.fiches && !cours.questions ? (
            <Holo taille="petit" variante="sombre" disabled={Boolean(empechement)} onClick={() => generer('tout')}>Fiches et questions</Holo>
          ) : null}
        </div>
      )}
      {empechement ? <div className="bloc-note attention">{empechement}</div> : null}
      {cours.erreur_generation && !enRedaction ? (
        <div className="bloc-note attention" role="status">La dernière rédaction n’a pas abouti : {cours.erreur_generation}</div>
      ) : null}
      {refus ? <BlocRefus refus={refus} onFermer={() => setRefus(null)} onReessayer={() => generer(refus.quoi)} /> : null}
      <div className="q-note">
        La transcription est envoyée au moteur VELA avec votre accord « Texte de vos demandes », et l’envoi est inscrit au registre de
        confidentialité. {existe ? 'Réécrire remplace la version actuelle.' : ''}
      </div>
    </div>
  )

  return (
    <div className="ecran">
      <TopBar
        titre="Cours"
        droite={
          <BtnIcone aria-label="Exporter en Markdown" title="Exporter en Markdown" onClick={exporter}>
            <IcoTelecharger />
          </BtnIcone>
        }
      />
      <div className="contenu">
        {/* ------------------------------------------------------------ en-tête */}
        <div className="carte col q-entete-cours" style={{ gap: 6 }}>
          <h2>{cours.titre || 'Cours sans titre'}</h2>
          {cours.matiere ? <div className="matiere">{cours.matiere}</div> : null}
          <div className="q-meta">
            <span>{dateLisible(cours.debut)}</span>
            <span>· {dureeLisible(secondes)}</span>
            <span>· {pluriel(cours.lignes, 'phrase transcrite', 'phrases transcrites')}</span>
            <span>· {cours.source === 'import' ? 'importé d’un fichier WAV' : 'enregistré en direct'}</span>
          </div>
          <PastillesCours c={cours} />
        </div>

        {cours.actif ? (
          <div className="q-direct">
            <div className="q-rec"><span className="dot rec" aria-hidden="true" /> Cours en cours d’enregistrement</div>
            <div className="q-chrono" role="timer" aria-label={`Durée du cours : ${dureeLisible(secondes)}`}>{chrono(secondes)}</div>
            <div className="q-actions">
              <Holo taille="petit" variante="rouge" disabled={occupe} onClick={arreter}><IcoStop /> Arrêter le cours</Holo>
            </div>
          </div>
        ) : null}

        {enTranscription ? (
          <div className="carte col" style={{ gap: 8 }} aria-live="polite">
            <div style={{ fontWeight: 700 }}>Transcription hors ligne : {Math.round((cours.progression || 0) * 100)} %</div>
            <div className="progress"><div style={{ width: `${Math.round((cours.progression || 0) * 100)}%` }} /></div>
            <div className="q-note">Elle se fait sur cet ordinateur et continue tant qu’IRIS reste ouverte.</div>
          </div>
        ) : null}

        {cours.erreur ? <div className="bloc-note attention" role="status">{cours.erreur}</div> : null}

        <div className="segmente-souple">
          <Segmente
            options={[
              { id: 'transcription', label: 'Transcription' },
              { id: 'fiches', label: 'Fiches' },
              { id: 'questions', label: questions.length ? `Questions (${questions.length})` : 'Questions' }
            ]}
            valeur={vue}
            onChange={setVue}
          />
        </div>

        {/* ------------------------------------------------------------ transcription */}
        {vue === 'transcription' ? (
          <div className="carte col" style={{ gap: 10 }}>
            {cours.transcription.length > 8 ? (
              <div className="recherche">
                <IcoRecherche />
                <input aria-label="Chercher dans la transcription" placeholder="Chercher un mot…" value={filtre} onChange={(e) => setFiltre(e.target.value)} />
              </div>
            ) : null}
            {lignesVisibles.length === 0 && !partiel ? (
              <div className="muted">
                {enTranscription
                  ? 'Les phrases apparaîtront quand la transcription sera terminée.'
                  : filtre.trim()
                    ? 'Aucune phrase ne contient ce mot.'
                    : cours.actif
                      ? 'En attente de paroles…'
                      : 'Aucune phrase transcrite.'}
              </div>
            ) : (
              <div className="q-transcription">
                {lignesVisibles.map((l, i) => (
                  <div key={`${l.ts}-${i}`} className="q-ligne">
                    <time>{chrono(l.ts)}</time>
                    <span>{l.texte}</span>
                  </div>
                ))}
                {partiel && !filtre.trim() ? (
                  <div className="q-ligne partiel" aria-hidden="true">
                    <time>{chrono(secondes)}</time>
                    <span>{partiel}</span>
                  </div>
                ) : null}
              </div>
            )}
            <div className="q-note">Transcription automatique faite sur cet ordinateur : approximative et sans ponctuation.</div>
          </div>
        ) : null}

        {/* ------------------------------------------------------------ fiches */}
        {vue === 'fiches' ? (
          <>
            {cours.fiches ? (
              <div className="carte sombre">
                <Markdown text={cours.fiches} />
              </div>
            ) : (
              <div className="carte">
                <VideCompact
                  glyphe="livre"
                  texte="Pas encore de fiches"
                  petit="IRIS peut rédiger des fiches de révision à partir de la transcription : notions clés, définitions, formules dites en classe, exemples et résumé par section."
                />
              </div>
            )}
            {zoneGeneration('fiches', Boolean(cours.fiches))}
          </>
        ) : null}

        {/* ------------------------------------------------------------ questions */}
        {vue === 'questions' ? (
          <>
            {questions.length ? (
              <>
                <div className="q-actions">
                  <Holo taille="mini" variante="sombre" onClick={() => setRetournees(new Set(questions.map((_q, i) => i)))}>Tout retourner</Holo>
                  <Holo taille="mini" variante="sombre" onClick={() => setRetournees(new Set())}>Tout cacher</Holo>
                </div>
                <div className="q-questions">
                  {questions.map((q, i) => (
                    <CarteQuestion key={`${i}-${q.question.slice(0, 20)}`} q={q} n={i + 1} retournee={retournees.has(i)} onBasculer={() => basculer(i)} />
                  ))}
                </div>
                <div className="bloc-note">
                  Questions probables, rédigées à partir de la transcription : ce ne sont pas celles de votre examen. Vérifiez les réponses avec vos
                  notes et le matériel du cours.
                </div>
              </>
            ) : (
              <div className="carte">
                <VideCompact
                  glyphe="livre"
                  texte="Pas encore de questions"
                  petit="IRIS peut proposer de 10 à 25 questions d’examen probables avec leurs réponses, selon ce que contient la transcription ; un cours très court en donne moins."
                />
              </div>
            )}
            {zoneGeneration('questions', questions.length > 0)}
          </>
        ) : null}

        {/* ------------------------------------------------------------ audio */}
        {cours.audio ? (
          <div className="carte col" style={{ gap: 10 }}>
            <h3 style={{ margin: 0 }}>Enregistrement audio</h3>
            {audioUrl ? (
              <audio controls src={audioUrl} style={{ width: '100%' }} />
            ) : (
              <Holo taille="petit" variante="sombre" disabled={audioCharge || cours.actif} onClick={chargerAudio} style={{ alignSelf: 'flex-start' }}>
                <IcoLecture /> {audioCharge ? 'Chargement…' : 'Écouter l’enregistrement'}
              </Holo>
            )}
            {cours.actif ? <div className="q-note">L’enregistrement sera disponible à l’arrêt du cours.</div> : null}
            {audioErreur ? <div className="bloc-note erreur" role="alert">{audioErreur}</div> : null}
            <div className="q-note">Fichier WAV stocké sur cet ordinateur, sans chiffrement ({cours.audio}). Il apparaît aussi dans l’Album.</div>
          </div>
        ) : null}

        {/* ------------------------------------------------------------ actions */}
        <div className="q-actions">
          <Holo taille="petit" variante="sombre" onClick={exporter}><IcoTelecharger /> Exporter en Markdown</Holo>
          <Holo taille="petit" variante="contour" disabled={occupe} onClick={supprimer}><IcoPoubelle /> Supprimer</Holo>
        </div>
        <div className="q-note">
          L’export contient la transcription, et les fiches et les questions si elles existent. Supprimer efface aussi l’enregistrement audio.
        </div>
      </div>
    </div>
  )
}
