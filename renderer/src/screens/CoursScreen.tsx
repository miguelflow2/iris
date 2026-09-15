import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { Field, Holo, Liste, Rangee, Segmente, TopBar, Vide } from '../components/ui'
import { IcoDossier, IcoMicro, IcoStop } from '../components/icons'
import { CarteLunettesRequises } from '../components/LunettesRequises'
import { api, ApiError, estLunettesRequises, messageErreur, refusConsentement, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import { CarteConsentement } from './AccessibiliteScreen'
import './AccessibiliteScreen.css'
import './CoursScreen.css'

/* =========================================================================
   « Mode cours » : enregistrer un cours pendant qu'il se donne (ou importer
   un enregistrement WAV), le retrouver rangé par matière, puis réviser.

   Ce qui se passe vraiment (backend/iris/cours.py) :
   - la transcription se fait sur l'ordinateur, avec le modèle hors ligne des
     sous-titres : approximative, sans ponctuation ;
   - le son est gardé en WAV sur l'ordinateur (non chiffré), la transcription
     est chiffrée ;
   - seules les fiches et les questions passent par le moteur VELA, sur
     demande, avec l'accord « Texte de vos demandes » (écran du cours).

   Lunettes d'abord : démarrer ou importer un cours exige des lunettes
   présentes ; consulter, exporter et supprimer ses cours, jamais.

   Ce fichier porte aussi la petite boîte à outils partagée par les écrans du
   quotidien (durées, chrono, refus, icônes en dégradé) : cours, reçus, pas à
   pas, entraînement, prix, résumé de la journée, rappels.
   ========================================================================= */

/* ------------------------------------------------------------------ boîte à outils partagée */

/** Refus d'une route, prêt à afficher : la phrase du service, ou la demande de consentement. */
export interface Refus {
  message: string
  consentement: { data_type: string; label: string; message: string } | null
}

/** null pour un refus « lunettes requises » : la feuille s'ouvre d'elle-même (App.tsx), rien à ajouter. */
export function lireRefus(err: unknown): Refus | null {
  if (estLunettesRequises(err)) return null
  const c = refusConsentement(err)
  return { message: c ? c.message : messageErreur(err), consentement: c }
}

/** Affiche un refus : carte de consentement (accorder puis réessayer) ou phrase d'erreur du service. */
export function BlocRefus({ refus, onFermer, onReessayer }: { refus: Refus; onFermer: () => void; onReessayer: () => void }): JSX.Element {
  const { setConsent, toast } = useStore()
  const c = refus.consentement
  if (c) {
    return (
      <CarteConsentement
        refus={c}
        onFermer={onFermer}
        onAutoriser={async () => {
          try {
            await setConsent(c.data_type, true)
          } catch (err) {
            toast(messageErreur(err), 'error')
            return
          }
          onFermer()
          onReessayer()
        }}
      />
    )
  }
  return <div className="bloc-note erreur" role="alert">{refus.message}</div>
}

/** Rend l'heure courante à chaque intervalle tant que `actif` : chronos et comptes à rebours affichés. */
export function useTic(actif: boolean, intervalleMs = 1000): number {
  const [maintenant, setMaintenant] = useState(() => Date.now())
  useEffect(() => {
    if (!actif) return
    setMaintenant(Date.now())
    const t = window.setInterval(() => setMaintenant(Date.now()), intervalleMs)
    return () => window.clearInterval(t)
  }, [actif, intervalleMs])
  return maintenant
}

/** « 12:34 » ou « 1:02:03 » : un chronomètre. */
export function chrono(secondes: number): string {
  const s = Math.max(0, Math.floor(Number(secondes) || 0))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(r).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

/** « 45 s », « 12 min 30 s », « 1 h 05 min ». */
export function dureeLisible(secondes: number | null | undefined): string {
  const s = Math.max(0, Math.round(Number(secondes) || 0))
  if (s < 60) return `${s} s`
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  if (h > 0) return m ? `${h} h ${String(m).padStart(2, '0')} min` : `${h} h`
  return r ? `${m} min ${r} s` : `${m} min`
}

/** Une durée MESURÉE (service, moteur) : « 0,2 s », « 12,4 s », puis « 1 min 05 s ». Jamais arrondie à « 0 s ». */
export function dureeMesuree(ms: number | null | undefined): string {
  const v = Math.max(0, Number(ms) || 0)
  if (v < 60000) return `${(v / 1000).toFixed(1).replace('.', ',')} s`
  return dureeLisible(v / 1000)
}

export function dateLisible(iso: string | null | undefined, avecHeure = true): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return avecHeure
    ? d.toLocaleString('fr-CA', { dateStyle: 'medium', timeStyle: 'short' })
    : d.toLocaleDateString('fr-CA', { dateStyle: 'long' })
}

/** AAAA-MM-JJ du jour LOCAL (toISOString donnerait le jour UTC, faux le soir au Canada). */
export function jourLocal(d: Date = new Date()): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function pluriel(n: number, un: string, plusieurs?: string): string {
  return `${n} ${n > 1 ? plusieurs || `${un}s` : un}`
}

/** Un nom de fichier acceptable par Windows, tiré d'un titre. */
export function nomDeFichier(texte: string, repli: string): string {
  const propre = (texte || '').replace(/[\\/:*?"<>|]+/g, '-').replace(/\s+/g, ' ').trim().slice(0, 80)
  return propre || repli
}

/** Texte comparable sans accents ni majuscules (recherche dans une transcription). */
export function sansAccents(texte: string): string {
  return (texte || '').normalize('NFD').replace(/\p{M}/gu, '').toLowerCase()
}

export type GlypheDegrade = 'livre' | 'recu' | 'etapes' | 'haltere' | 'etiquette' | 'soleil' | 'personne'

// Glyphes dessinés sur une grille de 24, posés en sombre sur la tuile en dégradé.
const GLYPHES: Record<GlypheDegrade, JSX.Element> = {
  livre: (
    <>
      <path d="M4 5.8c2.6-1.1 5.4-1.1 8 .7 2.6-1.8 5.4-1.8 8-.7v12.6c-2.6-1.1-5.4-1.1-8 .7-2.6-1.8-5.4-1.8-8-.7V5.8Z" />
      <path d="M12 6.5v12.6" />
    </>
  ),
  recu: (
    <>
      <path d="M6 3h12v18l-2-1.4L14 21l-2-1.4L10 21l-2-1.4L6 21V3Z" />
      <path d="M9 8h6M9 11.5h6M9 15h3.5" />
    </>
  ),
  etapes: (
    <>
      <path d="M10 6h10M10 12h10M10 18h10" />
      <path d="m3.5 6 1.5 1.5L7.5 5" />
      <path d="m3.5 12 1.5 1.5L7.5 11" />
      <circle cx="5" cy="18" r="1.4" />
    </>
  ),
  haltere: <path d="M6.5 7.5v9M17.5 7.5v9M3.5 10v4M20.5 10v4M6.5 12h11" />,
  etiquette: (
    <>
      <path d="M3.5 12.5V4.5a1 1 0 0 1 1-1h8l8 8a1.4 1.4 0 0 1 0 2l-7 7a1.4 1.4 0 0 1-2 0l-8-8Z" />
      <circle cx="8" cy="8" r="1.6" />
    </>
  ),
  soleil: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.8v2.2M12 19v2.2M2.8 12H5M19 12h2.2M5.5 5.5 7 7M17 17l1.5 1.5M5.5 18.5 7 17M17 7l1.5-1.5" />
    </>
  ),
  personne: (
    <>
      <circle cx="10" cy="8" r="3.6" />
      <path d="M3.5 20.5a6.5 6.5 0 0 1 13 0" />
      <path d="M19.5 6.5v5.5M19.5 15.2v.3" />
    </>
  )
}

/** Tuile au dégradé holographique des maquettes, pour les états vides. */
export function IcoDegrade({ glyphe, ...props }: React.SVGProps<SVGSVGElement> & { glyphe: GlypheDegrade }): JSX.Element {
  const id = useId()
  return (
    <svg viewBox="0 0 120 120" width={120} height={120} aria-hidden="true" {...props}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#f7bfff" />
          <stop offset="0.5" stopColor="#c8c8ff" />
          <stop offset="1" stopColor="#97f2ff" />
        </linearGradient>
      </defs>
      <rect x="8" y="8" width="104" height="104" rx="32" fill={`url(#${id})`} />
      <g transform="translate(24 24) scale(3)" fill="none" stroke="#1b1b1d" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
        {GLYPHES[glyphe]}
      </g>
    </svg>
  )
}

/** État vide qui tient dans une carte (le composant Vide occupe toute la hauteur d'un écran). */
export function VideCompact({ glyphe, texte, petit }: { glyphe: GlypheDegrade; texte: string; petit?: React.ReactNode }): JSX.Element {
  return (
    <div className="q-vide-compact">
      <IcoDegrade glyphe={glyphe} />
      <div className="texte">{texte}</div>
      {petit ? <div className="petit">{petit}</div> : null}
    </div>
  )
}

/* ------------------------------------------------------------------ cours */

/** Un cours tel que GET /api/cours le rend (cours.py, ServiceCours._resume). */
export interface CoursResume {
  id: string
  titre: string
  matiere: string | null
  debut: string
  fin: string | null
  duree_s: number
  lignes: number
  fiches: boolean
  questions: boolean
  audio: string | null
  actif: boolean
  source: string
  etat: string
  progression: number | null
  erreur: string | null
  /** Rédaction des fiches ou des questions en cours (etat « generation ») : parties faites sur le total. */
  generation?: { quoi: string; fait: number; total: number } | null
  /** Erreur d'une rédaction partie en arrière-plan (réponse 202 de /generer), à afficher telle quelle. */
  erreur_generation?: string | null
}

/** Pastilles d'état d'un cours : en direct, transcription, erreur, fiches, questions. */
export function PastillesCours({ c }: { c: { actif: boolean; etat: string; progression: number | null; fiches: unknown; questions: unknown; source: string; audio: string | null } }): JSX.Element {
  return (
    <span className="q-pastilles">
      {c.actif ? <span className="pill err">En direct</span> : null}
      {c.etat === 'transcription' ? (
        <span className="pill warn">Transcription{typeof c.progression === 'number' ? ` ${Math.round(c.progression * 100)} %` : '…'}</span>
      ) : null}
      {c.etat === 'generation' ? (
        <span className="pill warn">Rédaction{typeof c.progression === 'number' ? ` ${Math.round(c.progression * 100)} %` : '…'}</span>
      ) : null}
      {c.etat === 'erreur' ? <span className="pill err">Erreur</span> : null}
      {c.fiches ? <span className="pill ok">Fiches</span> : null}
      {c.questions ? <span className="pill ok">Questions</span> : null}
      {c.source === 'import' ? <span className="pill">Importé</span> : null}
      {c.audio ? <span className="pill">Audio</span> : null}
    </span>
  )
}

const SANS_MATIERE = 'Sans matière'
// Limites du service (cours.py) : 1 Go par la route en octets bruts ; 150 Mo par l'ancienne route en base64.
const TAILLE_MAX_IMPORT = 1024 * 1024 * 1024
const TAILLE_MAX_IMPORT_ANCIEN = 150 * 1024 * 1024
const FORMAT_REFUSE =
  'Format non pris en charge : seul le fichier WAV (PCM) est accepté. Convertissez l’enregistrement (MP3, M4A…) en WAV, idéalement 16 kHz mono, avant de l’importer.'

type Mode = 'direct' | 'import'

interface LigneDirect {
  ts: number
  texte: string
}

interface SuiviImport {
  phase: 'lecture' | 'envoi' | 'transcription' | 'termine' | 'erreur'
  nom: string
  octets: number
  fraction: number | null
  coursId: string | null
  message: string | null
}

export function CoursScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { nav, presence, exigerLunettes, ecoute, rafraichirEcoute } = useStore()
  const [cours, setCours] = useState<CoursResume[] | null>(null)
  const [recuA, setRecuA] = useState(() => Date.now())
  const [erreurListe, setErreurListe] = useState('')
  const [mode, setMode] = useState<Mode>('direct')
  const [titre, setTitre] = useState('')
  const [matiere, setMatiere] = useState('')
  const [occupe, setOccupe] = useState(false)
  const [erreur, setErreur] = useState('')
  const [avertissement, setAvertissement] = useState<string | null>(null)
  const [termine, setTermine] = useState<{ id: string; titre: string; raison: string | null } | null>(null)
  const [direct, setDirect] = useState<LigneDirect[]>([])
  const [partiel, setPartiel] = useState('')
  const [suivi, setSuivi] = useState<SuiviImport | null>(null)
  const fichierRef = useRef<HTMLInputElement>(null)
  const zoneDirect = useRef<HTMLDivElement>(null)
  const vivant = useRef(true)
  const coursRef = useRef<CoursResume[] | null>(null)
  const actifRef = useRef<string | null>(null)

  const absentes = presence !== null && !presence.presentes
  const actif = useMemo(() => (cours || []).find((c) => c.actif) || null, [cours])
  const actifId = actif?.id || null
  const tic = useTic(Boolean(actif))

  useEffect(() => {
    coursRef.current = cours
  }, [cours])
  useEffect(() => {
    actifRef.current = actifId
  }, [actifId])

  const charger = useCallback(async () => {
    try {
      const r = await api.get('/api/cours')
      if (!vivant.current) return
      setCours(Array.isArray(r?.cours) ? r.cours : [])
      setRecuA(Date.now())
      setErreurListe('')
    } catch (err) {
      if (vivant.current) setErreurListe(messageErreur(err))
    }
  }, [])

  useEffect(() => {
    vivant.current = true
    charger()
    rafraichirEcoute().catch(() => undefined)
    const off = api.on((e: IrisEvent) => {
      if (e.type === 'cours.etat') {
        const id = String(e.id || '')
        const avant = coursRef.current?.find((c) => c.id === id)
        if (!avant) {
          // Un cours démarré ailleurs (voix, téléphone) : la liste est relue.
          charger()
          return
        }
        const actifMaintenant = Boolean(e.actif)
        const etat = typeof e.etat === 'string' ? e.etat : avant.etat
        if (avant.actif && !actifMaintenant) {
          setTermine({ id, titre: avant.titre, raison: typeof e.raison === 'string' && e.raison ? e.raison : null })
          charger()
          return
        }
        if (etat !== avant.etat) {
          charger()
          return
        }
        setCours((liste) =>
          liste
            ? liste.map((c) =>
                c.id === id
                  ? {
                      ...c,
                      actif: actifMaintenant,
                      duree_s: Number(e.secondes ?? c.duree_s) || 0,
                      lignes: Number(e.lignes ?? c.lignes) || 0,
                      progression: typeof e.progression === 'number' ? e.progression : c.progression
                    }
                  : c
              )
            : liste
        )
        if (actifMaintenant) setRecuA(Date.now())
      } else if (e.type === 'ecoute.sous_titre' && actifRef.current) {
        if (typeof e.final === 'string' && e.final) {
          setDirect((l) => [...l, { ts: Number(e.ts) || Date.now() / 1000, texte: e.final }].slice(-200))
          setPartiel('')
        } else if (typeof e.partiel === 'string') {
          setPartiel(e.partiel)
        }
      }
    })
    return () => {
      vivant.current = false
      off()
    }
  }, [charger, rafraichirEcoute])

  // Un cours en direct : les dernières phrases déjà écrites, pour ne pas repartir d'un écran vide.
  useEffect(() => {
    setPartiel('')
    if (!actifId) return
    let courant = true
    api
      .get(`/api/cours/${encodeURIComponent(actifId)}`)
      .then((d) => {
        if (courant && Array.isArray(d?.transcription)) setDirect(d.transcription.slice(-50))
      })
      .catch(() => undefined)
    return () => {
      courant = false
    }
  }, [actifId])

  useEffect(() => {
    const el = zoneDirect.current
    if (el) el.scrollTop = el.scrollHeight
  }, [direct, partiel])

  // L'import suivi avance au rythme de la liste (événements cours.etat, relectures).
  useEffect(() => {
    if (!suivi || suivi.phase !== 'transcription' || !suivi.coursId || !cours) return
    const c = cours.find((x) => x.id === suivi.coursId)
    if (!c) return
    if (c.etat === 'transcription') {
      if (c.progression !== suivi.fraction) setSuivi({ ...suivi, fraction: c.progression })
    } else if (c.etat === 'erreur') {
      setSuivi({ ...suivi, phase: 'erreur', message: c.erreur || 'La transcription a échoué.' })
    } else {
      setSuivi({ ...suivi, phase: 'termine', fraction: 1 })
    }
  }, [cours, suivi])

  const matieres = useMemo(
    () => Array.from(new Set((cours || []).map((c) => (c.matiere || '').trim()).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'fr-CA')),
    [cours]
  )

  const groupes = useMemo(() => {
    const parMatiere = new Map<string, CoursResume[]>()
    for (const c of cours || []) {
      const cle = (c.matiere || '').trim() || SANS_MATIERE
      parMatiere.set(cle, [...(parMatiere.get(cle) || []), c])
    }
    return Array.from(parMatiere.entries()).sort(([a], [b]) => (a === SANS_MATIERE ? 1 : b === SANS_MATIERE ? -1 : a.localeCompare(b, 'fr-CA')))
  }, [cours])

  const demarrer = async (): Promise<void> => {
    if (occupe || actif) return
    if (!exigerLunettes('Mode cours')) return
    setOccupe(true)
    setErreur('')
    setAvertissement(null)
    setTermine(null)
    setDirect([])
    try {
      const r = await api.post('/api/cours/demarrer', { titre: titre.trim(), matiere: matiere.trim() || null })
      if (!vivant.current) return
      setAvertissement(typeof r?.avertissement === 'string' && r.avertissement ? r.avertissement : null)
      setTitre('')
      await charger()
      rafraichirEcoute().catch(() => undefined)
    } catch (err) {
      if (vivant.current && !estLunettesRequises(err)) setErreur(messageErreur(err))
    } finally {
      if (vivant.current) setOccupe(false)
    }
  }

  // Arrêter ne dépend jamais des lunettes : on doit toujours pouvoir couper un enregistrement.
  const arreter = async (): Promise<void> => {
    if (!actif || occupe) return
    setOccupe(true)
    setErreur('')
    try {
      const r = await api.post(`/api/cours/${encodeURIComponent(actif.id)}/arreter`)
      if (!vivant.current) return
      setTermine({ id: actif.id, titre: String(r?.titre || actif.titre), raison: null })
      setAvertissement(null)
      await charger()
      rafraichirEcoute().catch(() => undefined)
    } catch (err) {
      if (vivant.current) setErreur(messageErreur(err))
    } finally {
      if (vivant.current) setOccupe(false)
    }
  }

  const choisirFichier = (): void => {
    setErreur('')
    if (!exigerLunettes('Importer un cours')) return
    fichierRef.current?.click()
  }

  const importer = async (fichier: File): Promise<void> => {
    if (!/\.wav$/i.test(fichier.name)) {
      setErreur(FORMAT_REFUSE)
      return
    }
    if (fichier.size > TAILLE_MAX_IMPORT) {
      setErreur('Fichier trop volumineux (plus de 1 Go) : découpez le fichier ou enregistrez en 16 kHz mono.')
      return
    }
    const nom = fichier.name
    const octets = fichier.size
    const titreImport = titre.trim()
    const matiereImport = matiere.trim() || null
    setErreur('')
    setSuivi({ phase: 'envoi', nom, octets, fraction: 0, coursId: null, message: null })
    const suivre = (r: any): void => {
      if (!vivant.current) return
      setSuivi({ phase: 'transcription', nom, octets, fraction: typeof r?.progression === 'number' ? r.progression : 0, coursId: String(r?.id || ''), message: null })
      setTitre('')
      charger()
    }
    const echouer = (err: unknown): void => {
      if (!vivant.current) return
      if (estLunettesRequises(err)) {
        setSuivi(null)
        return
      }
      setSuivi({ phase: 'erreur', nom, octets, fraction: null, coursId: null, message: messageErreur(err) })
    }
    try {
      // Le fichier part tel quel, lu par morceaux depuis le disque : ni base64, ni copie en mémoire.
      // L'envoi continue même si l'écran est quitté ; la transcription se fait ensuite dans le service.
      const requete = new URLSearchParams({ titre: titreImport, nom_fichier: nom })
      if (matiereImport) requete.set('matiere', matiereImport)
      const r = await api.envoyerFichier(`/api/cours/importer-wav?${requete.toString()}`, fichier, 'audio/wav', (fraction) => {
        if (vivant.current) setSuivi((s) => (s && s.phase === 'envoi' ? { ...s, fraction } : s))
      })
      suivre(r)
    } catch (err) {
      // Service plus ancien, sans la route en octets bruts : l'envoi en base64 reste possible pour un petit fichier.
      if (err instanceof ApiError && err.status === 404 && octets <= TAILLE_MAX_IMPORT_ANCIEN) {
        importerEnBase64(fichier, titreImport, matiereImport, suivre, echouer)
        return
      }
      echouer(err)
    }
  }

  /** Ancien chemin (service sans /api/cours/importer-wav) : le fichier en base64 dans du JSON, 150 Mo au plus. */
  const importerEnBase64 = (fichier: File, titreImport: string, matiereImport: string | null, suivre: (r: any) => void, echouer: (err: unknown) => void): void => {
    const nom = fichier.name
    const octets = fichier.size
    setSuivi({ phase: 'lecture', nom, octets, fraction: 0, coursId: null, message: null })
    const lecteur = new FileReader()
    lecteur.onprogress = (ev) => {
      if (ev.lengthComputable && vivant.current) {
        setSuivi((s) => (s && s.phase === 'lecture' ? { ...s, fraction: ev.loaded / Math.max(1, ev.total) } : s))
      }
    }
    lecteur.onerror = () => {
      if (vivant.current) setSuivi({ phase: 'erreur', nom, octets, fraction: null, coursId: null, message: 'Le fichier n’a pas pu être lu sur cet ordinateur.' })
    }
    lecteur.onload = async () => {
      const brut = String(lecteur.result || '')
      const data = brut.slice(brut.indexOf(',') + 1)
      if (vivant.current) setSuivi({ phase: 'envoi', nom, octets, fraction: null, coursId: null, message: null })
      try {
        suivre(await api.post('/api/cours/importer', { titre: titreImport, matiere: matiereImport, nom_fichier: nom, data }))
      } catch (err) {
        echouer(err)
      }
    }
    lecteur.readAsDataURL(fichier)
  }

  const secondesActif = actif ? actif.duree_s + Math.max(0, (tic - recuA) / 1000) : 0
  const suspendue = ecoute?.memoire_suspendue || null
  const importEnCours = suivi !== null && (suivi.phase === 'lecture' || suivi.phase === 'envoi')

  return (
    <div className="ecran">
      <TopBar titre="Mode cours" />
      <div className="contenu">
        <p className="q-accroche">Fiches de révision et questions d’examen probables, rédigées à partir de votre cours.</p>

        {absentes && !actif ? <CarteLunettesRequises fonction="Enregistrer un cours" /> : null}

        {ecoute && !ecoute.modele_pret ? (
          <div className="bloc-note attention">
            Le modèle de reconnaissance vocale hors ligne n’est pas installé : aucun cours ne peut être transcrit.{' '}
            <button type="button" className="btn sm" onClick={() => nav.ouvrir('reglages-voix')}>Ouvrir Voix et écoute</button>
          </div>
        ) : null}
        {suspendue ? (
          <div className="bloc-note attention">
            Mémorisation suspendue (mode invité ou zone sans mémoire) : aucun cours ne démarre et aucun import n’est enregistré tant que ce mode est actif.
          </div>
        ) : null}

        {/* ------------------------------------------------------------ cours en direct */}
        {actif ? (
          <div className="q-direct">
            <div className="q-rec"><span className="dot rec" aria-hidden="true" /> Cours en cours d’enregistrement</div>
            <div className="q-titre-direct">{actif.titre || 'Cours sans titre'}</div>
            {actif.matiere ? <div className="q-meta">{actif.matiere}</div> : null}
            <div className="q-chrono" role="timer" aria-label={`Durée du cours : ${dureeLisible(secondesActif)}`}>{chrono(secondesActif)}</div>
            <div className="q-meta">{pluriel(actif.lignes, 'phrase transcrite', 'phrases transcrites')}</div>
            {/* aria-live coupé : un lecteur d'écran lirait le cours par-dessus la voix de l'enseignant. */}
            <div ref={zoneDirect} className="q-transcription-direct" role="log" aria-live="off" aria-label="Transcription en direct">
              {direct.length === 0 && !partiel ? <span className="muted">En attente de paroles…</span> : null}
              {direct.map((l, i) => (
                <span key={`${l.ts}-${i}`}>{l.texte}</span>
              ))}
              {partiel ? <span className="partiel" aria-hidden="true">{partiel}</span> : null}
            </div>
            <div className="q-actions">
              <Holo taille="petit" variante="rouge" disabled={occupe} onClick={arreter}><IcoStop /> Arrêter le cours</Holo>
              <Holo taille="petit" variante="contour" onClick={() => nav.ouvrir('cours-detail', { id: actif.id })}>Ouvrir</Holo>
            </div>
          </div>
        ) : null}

        {avertissement ? <div className="bloc-note attention" role="status">{avertissement}</div> : null}
        {erreur ? <div className="bloc-note erreur" role="alert">{erreur}</div> : null}

        {termine && !actif ? (
          <div className={`bloc-note ${termine.raison ? 'attention' : 'ok'}`} role="status">
            {termine.raison || `Cours « ${termine.titre || 'sans titre'} » terminé et gardé sur cet ordinateur.`}{' '}
            <button type="button" className="btn sm" onClick={() => nav.ouvrir('cours-detail', { id: termine.id })}>Ouvrir le cours</button>
          </div>
        ) : null}

        {/* ------------------------------------------------------------ nouveau cours */}
        {!actif ? (
          <div className="carte q-formulaire">
            <h3 style={{ margin: 0 }}>Nouveau cours</h3>
            <div className="segmente-souple">
              <Segmente
                options={[
                  { id: 'direct', label: 'En direct' },
                  { id: 'import', label: 'Importer un WAV' }
                ]}
                valeur={mode}
                onChange={setMode}
              />
            </div>
            <div className="q-grille-2">
              <Field label="Titre (facultatif)">
                <input className="input" value={titre} maxLength={200} placeholder="Ex. : Chapitre 4, les dérivées" onChange={(e) => setTitre(e.target.value)} />
              </Field>
              <Field label="Matière (facultatif)">
                <input className="input" value={matiere} maxLength={120} list="cours-matieres" placeholder="Ex. : Mathématiques" onChange={(e) => setMatiere(e.target.value)} />
              </Field>
            </div>
            <datalist id="cours-matieres">
              {matieres.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>

            {mode === 'direct' ? (
              <>
                <Holo disabled={occupe} onClick={demarrer}><IcoMicro /> {occupe ? 'Démarrage…' : 'Démarrer le cours'}</Holo>
                <div className="q-note">
                  IRIS écoute par le micro qu’elle utilise (celui des lunettes quand elles sont connectées), transcrit sur cet ordinateur et
                  garde l’enregistrement audio. Demandez l’autorisation de l’enseignant ; l’établissement peut interdire l’enregistrement.
                  Le contenu du cours reste protégé par le droit d’auteur : gardez l’enregistrement pour votre usage personnel, et prévenez
                  les autres personnes présentes, dont la voix peut aussi être captée.
                </div>
              </>
            ) : (
              <>
                <input
                  ref={fichierRef}
                  type="file"
                  accept=".wav,audio/wav,audio/x-wav"
                  hidden
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    e.target.value = ''
                    if (f) importer(f)
                  }}
                />
                <Holo disabled={importEnCours} onClick={choisirFichier}><IcoDossier /> Choisir un fichier WAV</Holo>
                <div className="q-note">
                  WAV (PCM) seulement : 1 Go et 4 heures d’enregistrement au plus. Le fichier est transcrit sur cet ordinateur : rien n’est
                  envoyé en ligne. Le titre prend le nom du fichier si vous n’en donnez pas.
                </div>
              </>
            )}
          </div>
        ) : null}

        {suivi ? (
          <div className="carte col" style={{ gap: 10 }} aria-live="polite">
            <div className="row between" style={{ gap: 10 }}>
              <strong style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{suivi.nom}</strong>
              <span className="muted small" style={{ flex: 'none' }}>{(suivi.octets / (1024 * 1024)).toFixed(1).replace('.', ',')} Mo</span>
            </div>
            {suivi.phase === 'lecture' ? (
              <>
                <div>Lecture du fichier sur cet ordinateur : {Math.round((suivi.fraction || 0) * 100)} %</div>
                <div className="progress"><div style={{ width: `${Math.round((suivi.fraction || 0) * 100)}%` }} /></div>
              </>
            ) : null}
            {suivi.phase === 'envoi' ? (
              suivi.fraction !== null && suivi.fraction < 1 ? (
                <>
                  <div>Remise du fichier au service IRIS de cet ordinateur : {Math.round(suivi.fraction * 100)} %</div>
                  <div className="progress"><div style={{ width: `${Math.round(suivi.fraction * 100)}%` }} /></div>
                  <div className="q-note">Le fichier ne quitte pas cet ordinateur : il passe de l’application au service local.</div>
                </>
              ) : (
                <>
                  <div>Vérification du format par le service IRIS de cet ordinateur…</div>
                  <div className="progress indet"><div /></div>
                </>
              )
            ) : null}
            {suivi.phase === 'transcription' ? (
              <>
                <div>Transcription hors ligne : {Math.round((suivi.fraction || 0) * 100)} %</div>
                <div className="progress"><div style={{ width: `${Math.round((suivi.fraction || 0) * 100)}%` }} /></div>
                <div className="q-note">
                  La durée dépend de la longueur de l’enregistrement et de la puissance de l’ordinateur. Vous pouvez quitter cet écran : la
                  transcription continue tant qu’IRIS reste ouverte.
                </div>
              </>
            ) : null}
            {suivi.phase === 'termine' ? <div className="bloc-note ok">Transcription terminée.</div> : null}
            {suivi.phase === 'erreur' ? <div className="bloc-note erreur" role="alert">{suivi.message}</div> : null}
            {suivi.phase === 'termine' || suivi.phase === 'erreur' || suivi.phase === 'transcription' ? (
              <div className="q-actions">
                {suivi.coursId ? (
                  <Holo taille="mini" variante="blanc" onClick={() => nav.ouvrir('cours-detail', { id: suivi.coursId })}>Ouvrir le cours</Holo>
                ) : null}
                {suivi.phase !== 'transcription' ? (
                  <Holo taille="mini" variante="sombre" onClick={() => setSuivi(null)}>Fermer</Holo>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}

        {/* ------------------------------------------------------------ mes cours */}
        <h2 className="section-sous">Mes cours</h2>
        {erreurListe ? <div className="bloc-note erreur" role="alert">{erreurListe}</div> : null}
        {cours === null && !erreurListe ? <div className="empty">Chargement…</div> : null}
        {cours !== null && cours.length === 0 ? (
          <Vide
            icone={<IcoDegrade glyphe="livre" />}
            texte="Aucun cours pour l’instant"
            petit="Démarrez un cours pendant qu’il se donne, ou importez un enregistrement WAV."
          />
        ) : null}
        {groupes.map(([nom, liste]) => (
          <section key={nom} className="col" style={{ gap: 8 }} aria-label={nom}>
            <h3 className="q-titre-groupe">{nom} · {liste.length}</h3>
            <Liste>
              {liste.map((c) => (
                <Rangee
                  key={c.id}
                  compacte
                  titre={c.titre || 'Cours sans titre'}
                  sous={
                    <>
                      {dateLisible(c.debut)} · {dureeLisible(c.duree_s)} · {pluriel(c.lignes, 'phrase')}
                      <PastillesCours c={c} />
                    </>
                  }
                  onClick={() => nav.ouvrir('cours-detail', { id: c.id })}
                />
              ))}
            </Liste>
          </section>
        ))}

        {/* ------------------------------------------------------------ limites */}
        <div className="carte">
          <h3>Ce qu’il faut savoir</h3>
          <ul className="liste-limites">
            <li>La transcription se fait sur cet ordinateur avec un modèle hors ligne : elle est approximative (termes techniques, formules dites à voix haute, noms propres), sans ponctuation, et ne distingue pas l’enseignant de la salle.</li>
            <li>Assis loin ou dans une salle bruyante, le son est moins bien capté et la transcription s’en ressent.</li>
            <li>Les fiches et les questions sont rédigées par le moteur VELA à partir de la transcription, seulement quand vous le demandez et avec votre accord « Texte de vos demandes » : elles peuvent contenir des erreurs, vérifiez-les avec vos notes.</li>
            <li>La transcription, les fiches et les questions sont chiffrées sur cet ordinateur. L’enregistrement audio (WAV) est stocké sur cet ordinateur, sans chiffrement.</li>
            <li>L’import accepte seulement le WAV (PCM), 1 Go et 4 heures au plus : convertissez d’abord un MP3 ou un M4A, et découpez un enregistrement plus long.</li>
            <li>La durée de conservation réglée dans Confidentialité s’applique aux cours : exportez ce que vous voulez garder plus longtemps.</li>
          </ul>
        </div>
      </div>
    </div>
  )
}
