import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Holo, Segmente, TopBar } from '../components/ui'
import { IcoFermer, IcoHautParleur, IcoLecture, IcoStop, IcoTraduire } from '../components/icons'
import { CarteLunettesRequises } from '../components/LunettesRequises'
import { api, estLunettesRequises, messageErreur, refusConsentement, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import { CarteConsentement } from './AccessibiliteScreen'
import './AccessibiliteScreen.css'
import './InterpreteScreen.css'

/* =========================================================================
   « Mode interprète » : deux personnes, deux langues, IRIS au milieu.

   Ce que l'écran montre est ce que le service fait (backend/iris/traduction.py,
   ServiceInterprete) : la langue de l'autre, où l'autre entend, le fil des tours
   avec la latence MESURÉE de chaque tour (jamais promise), et ce qui empêche ou
   limite le mode (empechement, avertissements) tel que le service le dit.

   La voix de l'autre personne part en ligne pour être reconnue : elle n'a rien
   consenti, donc l'écran le dit avant le bouton Démarrer. Les tours vivent en
   mémoire vive du service et sont effacés à l'arrêt : l'écran les relit après
   chaque changement d'état au lieu d'en garder sa propre copie.
   ========================================================================= */

interface Tour {
  ts: number
  qui: string
  original: string
  traduction: string
  langue_source?: string
  langue_cible?: string
  latence_ms: number | null
  sortie?: string
  origine?: string
}

interface Langue {
  code: string
  nom: string
  voix?: boolean
}

interface Doute {
  ts: number
  raison: string
  a_dire?: string
  qui_suppose?: string | null
}

interface EtatInterprete {
  actif: boolean
  langue_moi: string
  langue_autre: string
  langue_autre_nom?: string
  sortie_autre: string
  tours: Tour[]
  langues: Langue[]
  empechement: string | null
  empechement_bloquant?: boolean
  avertissements?: string[]
  voix_autre?: { disponible: boolean; nom: string | null }
  ecoute?: boolean
  latence_moyenne_ms?: number | null
  latence_visee_ms?: number
  traduction_simple_active?: boolean
  dernier_doute?: Doute | null
  phrase?: string
}

type Sortie = 'pc' | 'lunettes' | 'telephone'
type Auteur = 'moi' | 'autre'

const NOMS_LANGUES: Record<string, string> = { fr: 'français', en: 'anglais', es: 'espagnol', pt: 'portugais', it: 'italien', de: 'allemand' }

const SORTIES: { id: Sortie; nom: string; sous: string }[] = [
  { id: 'pc', nom: 'Ordinateur', sous: 'Haut-parleur par défaut de Windows.' },
  { id: 'lunettes', nom: 'Lunettes', sous: 'Haut-parleur des lunettes ; l’ordinateur prend le relais s’il est introuvable.' },
  { id: 'telephone', nom: 'Téléphone', sous: 'La page IRIS du téléphone lit la traduction : elle doit être ouverte et connectée.' }
]

/** Ce que la traduction est devenue pour ce tour, dit sans l'embellir (champ « sortie » du service). */
const SORTIES_TOUR: Record<string, string> = {
  voix_iris: 'lue pour vous par IRIS',
  pc: 'lue sur l’ordinateur',
  lunettes: 'lue par les lunettes',
  telephone: 'envoyée au téléphone',
  ecran: 'affichée seulement (aucune voix)',
  appelant: 'écrite au clavier'
}

/** Pourquoi l'interprète s'est refermé (champ « raison » de interprete.etat). */
const RAISONS_FERMETURE: Record<string, string> = {
  demande: 'Interprète arrêté.',
  silence: 'Personne n’a parlé depuis trois minutes : l’interprète s’est refermé.',
  erreur: 'Les traductions échouaient à répétition : l’interprète s’est refermé.',
  lunettes: 'Les lunettes ne sont plus là : l’interprète s’est refermé.',
  arret: 'L’interprète s’est arrêté (mode confidentiel, mode local ou arrêt d’IRIS).',
  verrouillage: 'IRIS a été verrouillée : l’interprète est arrêté.'
}

function nomLangue(code: string | undefined, langues?: Langue[]): string {
  if (!code) return 'cette langue'
  return langues?.find((l) => l.code === code)?.nom || NOMS_LANGUES[code] || code
}

function majuscule(texte: string): string {
  return texte ? texte.charAt(0).toUpperCase() + texte.slice(1) : texte
}

function secondes(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return '—'
  return `${(ms / 1000).toLocaleString('fr-CA', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s`
}

function heure(ts: number): string {
  const d = new Date(ts * 1000)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('fr-CA', { hour: '2-digit', minute: '2-digit' })
}

function cleTour(t: Tour): string {
  return `${t.ts}|${t.qui}|${t.original}`
}

/* ------------------------------------------------------------ voix locale du navigateur
   Pour le texte écrit au clavier, c'est l'appelant qui fait entendre la traduction
   (le service ne joue rien). On n'utilise QUE les voix installées sur l'ordinateur
   (localService) : aucune phrase ne part en ligne pour être lue. Sans voix locale de
   la langue, le bouton n'apparaît pas — l'écran n'offre pas ce qu'il ne peut pas faire. */
function voixLocale(langue: string): SpeechSynthesisVoice | null {
  try {
    if (!('speechSynthesis' in window)) return null
    const candidates = window.speechSynthesis.getVoices().filter((v) => v.localService && v.lang.toLowerCase().startsWith(langue.toLowerCase()))
    return candidates.find((v) => /-ca$/i.test(v.lang)) || candidates[0] || null
  } catch {
    return null
  }
}

function useVoixLocales(): Set<string> {
  const [langues, setLangues] = useState<Set<string>>(new Set())
  useEffect(() => {
    if (!('speechSynthesis' in window)) return
    const lire = (): void => {
      try {
        setLangues(new Set(window.speechSynthesis.getVoices().filter((v) => v.localService).map((v) => v.lang.slice(0, 2).toLowerCase())))
      } catch {
        setLangues(new Set())
      }
    }
    lire()
    window.speechSynthesis.addEventListener('voiceschanged', lire)
    return () => {
      window.speechSynthesis.removeEventListener('voiceschanged', lire)
      try {
        window.speechSynthesis.cancel()
      } catch {
        /* rien à couper */
      }
    }
  }, [])
  return langues
}

function lireAVoixHaute(texte: string, langue: string): boolean {
  const voix = voixLocale(langue)
  if (!voix) return false
  try {
    window.speechSynthesis.cancel()
    const enonce = new SpeechSynthesisUtterance(texte)
    enonce.voice = voix
    enonce.lang = voix.lang
    window.speechSynthesis.speak(enonce)
    return true
  } catch {
    return false
  }
}

export function InterpreteScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { settings, updateSettings, toast, presence, exigerLunettes, setConsent } = useStore()
  const [etat, setEtat] = useState<EtatInterprete | null>(null)
  const [erreurEtat, setErreurEtat] = useState('')
  const [erreur, setErreur] = useState('')
  const [occupe, setOccupe] = useState(false)
  const [refus, setRefus] = useState<{ data_type: string; label: string; message: string } | null>(null)
  const [phrase, setPhrase] = useState('')
  const [fermeture, setFermeture] = useState('')
  const [doute, setDoute] = useState<Doute | null>(null)
  const [voixAutre, setVoixAutre] = useState<{ etat: string; raison?: string } | null>(null)
  const [auteur, setAuteur] = useState<Auteur>('moi')
  const [texte, setTexte] = useState('')
  const [envoi, setEnvoi] = useState(false)
  const [erreurTexte, setErreurTexte] = useState('')
  const [refusTexte, setRefusTexte] = useState<{ data_type: string; label: string; message: string } | null>(null)
  const [enGrand, setEnGrand] = useState<{ texte: string; langue: string } | null>(null)
  const voixLocales = useVoixLocales()
  const finFil = useRef<HTMLDivElement>(null)

  const absentes = presence !== null && !presence.presentes
  const actif = Boolean(etat?.actif)
  const langueMoi = etat?.langue_moi || 'fr'
  // Hors session, la langue et la sortie choisies sont celles des réglages (le service les relit aussi).
  const langueAutre = etat?.langue_autre || String(settings?.interprete_langue || 'en')
  const sortie = (etat?.sortie_autre || settings?.interprete_sortie_autre || 'pc') as Sortie

  const charger = useCallback(async (): Promise<void> => {
    try {
      const e = await api.get<EtatInterprete>('/api/interprete/etat')
      setEtat(e)
      setErreurEtat('')
    } catch (err) {
      setErreurEtat(messageErreur(err))
    }
  }, [])

  useEffect(() => {
    charger().catch(() => undefined)
    return api.on((e: IrisEvent) => {
      switch (e.type) {
        case 'interprete.tour': {
          const tour: Tour = {
            ts: Number(e.ts) || Date.now() / 1000,
            qui: String(e.qui || ''),
            original: String(e.original || ''),
            traduction: String(e.traduction || ''),
            langue_source: e.langue_source,
            langue_cible: e.langue_cible,
            latence_ms: typeof e.latence_ms === 'number' ? e.latence_ms : null,
            sortie: e.sortie,
            origine: e.origine
          }
          setEtat((prec) => {
            if (!prec) return prec
            if (prec.tours.some((t) => cleTour(t) === cleTour(tour))) return prec
            return { ...prec, tours: [...prec.tours, tour].slice(-50) }
          })
          setDoute(null)
          break
        }
        case 'interprete.etat':
          if (e.actif === false && typeof e.raison === 'string') setFermeture(RAISONS_FERMETURE[e.raison] || RAISONS_FERMETURE.demande)
          if (e.actif === true) setFermeture('')
          setVoixAutre(null)
          charger().catch(() => undefined)
          break
        case 'interprete.doute':
          setDoute({ ts: Number(e.ts) || Date.now() / 1000, raison: String(e.raison || ''), a_dire: e.a_dire, qui_suppose: e.qui_suppose ?? null })
          break
        case 'interprete.voix':
          setVoixAutre({ etat: String(e.etat || ''), raison: typeof e.raison === 'string' ? e.raison : undefined })
          break
        case 'settings.updated':
          // La langue ou la sortie ont pu changer ailleurs (voix, téléphone) : l'état en dépend.
          charger().catch(() => undefined)
          break
        default:
          break
      }
    })
  }, [charger])

  // Le fil suit la conversation : le dernier tour reste visible.
  useEffect(() => {
    finFil.current?.scrollIntoView({ block: 'nearest' })
  }, [etat?.tours.length])

  const choisirLangue = (code: string): void => {
    if (actif || code === langueAutre) return
    updateSettings({ interprete_langue: code })
      .then(() => charger())
      .catch((err: unknown) => toast(messageErreur(err), 'error'))
  }

  const choisirSortie = (id: Sortie): void => {
    if (actif || id === sortie) return
    updateSettings({ interprete_sortie_autre: id })
      .then(() => charger())
      .catch((err: unknown) => toast(messageErreur(err), 'error'))
  }

  const demarrer = async (): Promise<void> => {
    if (!exigerLunettes('Mode interprète')) return
    setOccupe(true)
    setErreur('')
    setRefus(null)
    setFermeture('')
    setPhrase('')
    try {
      const r = await api.post<EtatInterprete>('/api/interprete/demarrer', { langue_autre: langueAutre, sortie_autre: sortie })
      setEtat(r)
      if (r.phrase) setPhrase(r.phrase)
    } catch (err) {
      if (estLunettesRequises(err)) return
      const c = refusConsentement(err)
      if (c) setRefus(c)
      else setErreur(messageErreur(err))
    } finally {
      setOccupe(false)
    }
  }

  const arreter = async (): Promise<void> => {
    setOccupe(true)
    setErreur('')
    try {
      const r = await api.post<EtatInterprete>('/api/interprete/arreter')
      setEtat(r)
      setPhrase('')
      setDoute(null)
    } catch (err) {
      setErreur(messageErreur(err))
    } finally {
      setOccupe(false)
    }
  }

  const envoyerTexte = async (): Promise<void> => {
    const propre = texte.trim()
    if (!propre) return
    if (!exigerLunettes('Mode interprète')) return
    setEnvoi(true)
    setErreurTexte('')
    setRefusTexte(null)
    try {
      // « langue » est TOUJOURS la langue de l'autre personne, quel que soit l'auteur (contrat du service).
      const r = await api.post<{ traduction: string; langue_source: string; langue_cible: string; latence_ms: number }>('/api/interprete/texte', {
        qui: auteur,
        texte: propre,
        langue: langueAutre
      })
      setTexte('')
      if (auteur === 'moi') setEnGrand({ texte: r.traduction, langue: r.langue_cible })
      // Le tour arrive aussi par l'événement interprete.tour ; relire l'état couvre une liaison coupée.
      charger().catch(() => undefined)
    } catch (err) {
      if (estLunettesRequises(err)) return
      const c = refusConsentement(err)
      if (c) setRefusTexte(c)
      else setErreurTexte(messageErreur(err))
    } finally {
      setEnvoi(false)
    }
  }

  const lire = (texteALire: string, langue: string): void => {
    if (!lireAVoixHaute(texteALire, langue)) toast(`Aucune voix en ${nomLangue(langue, etat?.langues)} n’est installée sur cet ordinateur.`, 'error')
  }

  const langues = etat?.langues || []
  const nomMoi = nomLangue(langueMoi, langues)
  const nomAutre = etat?.langue_autre_nom || nomLangue(langueAutre, langues)
  const bloquant = Boolean(etat?.empechement_bloquant)
  const avertissements = useMemo(() => {
    if (!etat || bloquant) return []
    if (Array.isArray(etat.avertissements)) return etat.avertissements
    return etat.empechement ? [etat.empechement] : []
  }, [etat, bloquant])
  const tours = etat?.tours || []

  return (
    <div className="ecran">
      <TopBar titre="Mode interprète" />
      <div className="contenu">
        {absentes ? <CarteLunettesRequises fonction="Mode interprète" /> : null}

        <div className="interp-hero">
          <h2>Parlez {nomMoi}, votre interlocuteur entend sa langue</h2>
          <p>
            IRIS reconnaît chaque phrase, la traduit, puis la fait entendre à l’autre personne dans sa langue ; sa réponse vous revient en {nomMoi}. Chaque
            traduction arrive quelques secondes après la fin de la phrase : le délai de chaque tour est mesuré et affiché ci-dessous.
          </p>
        </div>

        {erreurEtat ? <div className="bloc-note erreur" role="alert">{erreurEtat}</div> : null}

        {/* ------------------------------------------------------------ langue de l'autre personne */}
        <div className="carte col" style={{ gap: 12 }}>
          <h3 style={{ margin: 0 }}>Langue de l’autre personne</h3>
          <div className="interp-langues" role="radiogroup" aria-label="Langue de l’autre personne">
            {langues.length === 0 && !erreurEtat ? <span className="muted">Chargement des langues…</span> : null}
            {langues.map((l) => (
              <button
                key={l.code}
                type="button"
                role="radio"
                aria-checked={l.code === langueAutre}
                className={`puce ${l.code === langueAutre ? 'actif' : ''}`}
                disabled={actif}
                onClick={() => choisirLangue(l.code)}
              >
                <span>{majuscule(l.nom)}</span>
                {sortie !== 'telephone' ? <span className="voix">{l.voix ? 'voix installée' : 'affichage seulement'}</span> : null}
              </button>
            ))}
          </div>
          {sortie !== 'telephone' ? (
            <div className="small muted" style={{ lineHeight: 1.45 }}>
              « Voix installée » : une voix de cette langue existe dans Windows, la traduction peut être lue à l’autre personne. Sinon, elle est seulement
              affichée.{etat?.voix_autre?.nom && etat.voix_autre.disponible ? ` Voix utilisée : ${etat.voix_autre.nom}.` : ''}
            </div>
          ) : null}
          {actif ? <div className="small muted">Arrêtez l’interprète pour changer de langue.</div> : null}
        </div>

        {/* ------------------------------------------------------------ où l'autre entend */}
        <div className="carte col" style={{ gap: 12 }}>
          <h3 style={{ margin: 0 }}>Où l’autre personne entend</h3>
          <div className="interp-sorties" role="radiogroup" aria-label="Où l’autre personne entend la traduction">
            {SORTIES.map((s) => (
              <button key={s.id} type="button" role="radio" aria-checked={s.id === sortie} className="interp-sortie" disabled={actif} onClick={() => choisirSortie(s.id)}>
                <span className="nom">{s.nom}</span>
                <span className="sous">{s.sous}</span>
              </button>
            ))}
          </div>
          <div className="small muted" style={{ lineHeight: 1.45 }}>Vous, vous entendez la traduction de l’autre par la voix habituelle d’IRIS.</div>
        </div>

        {/* ------------------------------------------------------------ empêchements et limites dites par le service */}
        {etat && bloquant && etat.empechement ? (
          <div className="bloc-note erreur" role="alert">
            <strong>L’interprète ne peut pas démarrer : </strong>
            {etat.empechement}
          </div>
        ) : null}
        {avertissements.map((a, i) => (
          <div key={i} className="bloc-note attention">{a}</div>
        ))}
        {etat?.traduction_simple_active ? (
          <div className="bloc-note attention">Le mode traduction simple est ouvert : démarrer l’interprète le remplace.</div>
        ) : null}

        {/* ------------------------------------------------------------ démarrer / arrêter */}
        <div className="col" style={{ gap: 10 }}>
          {/* Démarrer reste actif même quand le service dit « bloquant » : un refus de consentement revient alors en
              403 et la carte d'accord permet d'autoriser en un clic, au lieu d'un bouton mort. */}
          {actif ? (
            <Holo variante="rouge" disabled={occupe} onClick={arreter}>
              <IcoStop /> {occupe ? 'Arrêt…' : 'Arrêter l’interprète'}
            </Holo>
          ) : (
            <Holo disabled={occupe || !etat} onClick={demarrer}>
              <IcoLecture /> {occupe ? 'Démarrage…' : `Démarrer (${nomMoi} ⇄ ${nomAutre})`}
            </Holo>
          )}
          <div className="interp-etat" aria-live="polite">
            <span className={`dot ${actif ? 'on' : ''}`} aria-hidden="true" />
            <span>{actif ? `Interprète actif : ${nomMoi} ⇄ ${nomAutre}` : 'Interprète arrêté'}</span>
            {actif && etat?.ecoute === false ? <span className="pill warn">écoute arrêtée</span> : null}
            {typeof etat?.latence_moyenne_ms === 'number' ? (
              <span className="pill">latence moyenne mesurée : {secondes(etat.latence_moyenne_ms)}</span>
            ) : null}
          </div>
          {actif ? (
            <div className="small muted" style={{ lineHeight: 1.45 }}>
              À la voix : « Dis-moi Iris, fin de l’interprète ». Pour ouvrir sans écran : « Dis-moi Iris, mode interprète {nomAutre} ».
            </div>
          ) : null}
        </div>

        {erreur ? <div className="bloc-note erreur" role="alert">{erreur}</div> : null}
        {refus ? (
          <CarteConsentement
            refus={refus}
            onFermer={() => setRefus(null)}
            onAutoriser={async () => {
              try {
                await setConsent(refus.data_type, true)
              } catch (err) {
                toast(messageErreur(err), 'error')
                return
              }
              setRefus(null)
              demarrer()
            }}
          />
        ) : null}
        {phrase ? <div className="bloc-note ok" aria-live="polite">{phrase}</div> : null}
        {fermeture && !actif ? <div className="bloc-note" aria-live="polite">{fermeture}</div> : null}
        {actif && voixAutre && (voixAutre.etat === 'erreur' || voixAutre.etat === 'repli') && voixAutre.raison ? (
          <div className="bloc-note attention" aria-live="polite">{voixAutre.raison}</div>
        ) : null}
        {actif && doute ? (
          <div className="bloc-note attention" aria-live="polite">
            Phrase non traduite{doute.a_dire ? ` : ${doute.a_dire}` : doute.raison ? ` (${doute.raison})` : '.'}
          </div>
        ) : null}

        {/* ------------------------------------------------------------ fil des tours */}
        <div className="carte col" style={{ gap: 12 }}>
          <div className="row between">
            <h3 style={{ margin: 0 }}>Conversation</h3>
            {actif && voixAutre?.etat === 'debut' ? (
              <span className="pill ok">
                <IcoHautParleur width={14} height={14} /> lecture pour l’autre
              </span>
            ) : null}
          </div>
          {tours.length === 0 ? (
            <div className="muted" style={{ fontWeight: 600, lineHeight: 1.45 }}>
              {actif ? 'En attente d’une première phrase…' : 'Les tours de la conversation s’afficheront ici.'}
            </div>
          ) : (
            <div className="interp-fil" role="log" aria-live="polite" aria-label="Tours de la conversation">
              <div className="interp-entetes" aria-hidden="true">
                <span>L’autre personne</span>
                <span>Vous</span>
              </div>
              {tours.map((t) => {
                const moi = t.qui === 'moi'
                return (
                  <div key={cleTour(t)} className={`interp-tour ${moi ? 'moi' : 'autre'}`}>
                    <div className="interp-bulle">
                      <span className="qui">
                        {moi ? 'Vous' : 'L’autre personne'} · {heure(t.ts)}
                      </span>
                      <span className="traduction" lang={t.langue_cible}>{t.traduction}</span>
                      <span className="original" lang={t.langue_source}>
                        Original ({nomLangue(t.langue_source, langues)}) : {t.original}
                      </span>
                      <span className="meta">
                        <span>
                          {t.origine === 'texte' ? 'traduction' : 'de la fin de la phrase à la voix'} : {secondes(t.latence_ms)}
                        </span>
                        {t.sortie && SORTIES_TOUR[t.sortie] ? <span>{SORTIES_TOUR[t.sortie]}</span> : null}
                        {moi ? (
                          <button type="button" onClick={() => setEnGrand({ texte: t.traduction, langue: t.langue_cible || langueAutre })}>
                            Montrer en grand
                          </button>
                        ) : null}
                      </span>
                    </div>
                  </div>
                )
              })}
              <div ref={finFil} />
            </div>
          )}
          <div className="small muted" style={{ lineHeight: 1.45 }}>
            Le fil reste en mémoire vive, jamais sur le disque : il est effacé à l’arrêt de l’interprète, et après dix minutes sans activité.
          </div>
        </div>

        {/* ------------------------------------------------------------ écrire pour l'autre */}
        <div className="carte col interp-ecrire" style={{ gap: 12 }}>
          <h3 style={{ margin: 0 }}>Écrire pour l’autre</h3>
          <div className="desc">
            Pour un mot difficile à prononcer, un nom, une adresse, ou quand la voix ne passe pas. Fonctionne aussi sans démarrer l’interprète.
          </div>
          <Segmente<Auteur>
            options={[
              { id: 'moi', label: `J’écris (${nomMoi})` },
              { id: 'autre', label: `L’autre écrit (${nomAutre})` }
            ]}
            valeur={auteur}
            onChange={setAuteur}
          />
          <textarea
            className="textarea"
            value={texte}
            maxLength={2000}
            lang={auteur === 'moi' ? langueMoi : langueAutre}
            aria-label={auteur === 'moi' ? `Votre phrase en ${nomMoi}` : `Phrase de l’autre personne en ${nomAutre}`}
            placeholder={auteur === 'moi' ? `Votre phrase en ${nomMoi}…` : `La phrase de l’autre personne, en ${nomAutre}…`}
            onChange={(e) => setTexte(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault()
                envoyerTexte()
              }
            }}
          />
          <div className="row wrap" style={{ gap: 10 }}>
            {/* Pas désactivé par un empêchement de la voix : écrire n'a besoin ni du micro ni de l'accord audio. */}
            <Holo taille="petit" disabled={envoi || !texte.trim()} onClick={envoyerTexte}>
              <IcoTraduire /> {envoi ? 'Traduction…' : `Traduire en ${auteur === 'moi' ? nomAutre : nomMoi}`}
            </Holo>
            <span className="small muted">Ctrl+Entrée</span>
          </div>
          {erreurTexte ? <div className="bloc-note erreur" role="alert">{erreurTexte}</div> : null}
          {refusTexte ? (
            <CarteConsentement
              refus={refusTexte}
              onFermer={() => setRefusTexte(null)}
              onAutoriser={async () => {
                try {
                  await setConsent(refusTexte.data_type, true)
                } catch (err) {
                  toast(messageErreur(err), 'error')
                  return
                }
                setRefusTexte(null)
                envoyerTexte()
              }}
            />
          ) : null}
          <div className="small muted" style={{ lineHeight: 1.45 }}>
            Le texte est envoyé au moteur VELA pour être traduit (accord « Texte de vos demandes »). La traduction de ce que vous écrivez s’affiche en grand
            pour la montrer ; elle peut être lue à voix haute seulement si une voix de la langue est installée sur cet ordinateur.
          </div>
        </div>

        {/* ------------------------------------------------------------ ce qu'il faut savoir */}
        <div className="carte">
          <h3>Ce qu’il faut savoir</h3>
          <ul className="liste-limites">
            <li>
              <strong>Prévenez l’autre personne avant de commencer.</strong> Pour reconnaître ce qu’elle dit, sa voix est envoyée à un service de reconnaissance
              en ligne (la reconnaissance hors ligne ne connaît que votre langue). Elle n’a rien accepté : c’est à vous de lui demander.
            </li>
            <li>Chaque phrase est traduite en ligne par le moteur VELA : l’interprète exige Internet et ne marche pas en mode 100 % local ni en mode confidentiel.</li>
            <li>Le délai dépend du réseau, de la longueur de la phrase et de l’ordinateur. Il est mesuré à chaque tour, jamais garanti.</li>
            <li>Parlez chacun votre tour : quand deux personnes parlent en même temps, IRIS peut attribuer la phrase à la mauvaise personne ou ne rien traduire.</li>
            <li>Une traduction peut être fausse, surtout pour les noms propres, les chiffres et les expressions. Pour une décision médicale, juridique ou financière, faites appel à un interprète professionnel.</li>
            <li>L’interprète écoute le micro qu’IRIS utilise (celui des lunettes quand elles sont connectées à cet ordinateur). Il se referme seul après trois minutes sans parole.</li>
            <li>Dehors, avec le téléphone, utilisez l’interprète de l’app IRIS du téléphone : il n’ouvre pas le micro de l’ordinateur resté à la maison.</li>
          </ul>
        </div>
      </div>

      {enGrand ? (
        <div className="interp-grand" role="dialog" aria-modal="true" aria-label="Traduction à montrer">
          <div className="row between">
            <span className="langue">{majuscule(nomLangue(enGrand.langue, langues))}</span>
            <button type="button" className="btn-icone" aria-label="Fermer" onClick={() => setEnGrand(null)}>
              <IcoFermer />
            </button>
          </div>
          <div className="texte" lang={enGrand.langue}>{enGrand.texte}</div>
          <div className="actions">
            {voixLocales.has(enGrand.langue.slice(0, 2).toLowerCase()) ? (
              <Holo taille="petit" variante="blanc" onClick={() => lire(enGrand.texte, enGrand.langue)}>
                <IcoHautParleur /> Lire à voix haute
              </Holo>
            ) : null}
            <Holo taille="petit" variante="contour" onClick={() => setEnGrand(null)}>Fermer</Holo>
          </div>
        </div>
      ) : null}
    </div>
  )
}
