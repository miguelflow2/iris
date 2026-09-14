import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useStore } from '../lib/store'
import { api, estLunettesRequises, messageErreur, refusConsentement, type IrisEvent } from '../lib/api'
import { Field, Holo, Liste, Rangee, Segmente, TopBar, Vide } from '../components/ui'
import { IcoOreille, IcoReunion, IcoTelephoneEcran, IcoTraduire } from '../components/icons'
import { CarteLunettesRequises } from '../components/LunettesRequises'
import { CarteConsentement } from './AccessibiliteScreen'

/* =========================================================================
   « Traduction avec IA » (maquette IMG_0711) : trois grandes cartes, toutes
   réelles.
   - Traduction par écran : POST /api/traduction/ecran (backend/iris/album.py).
     L'écran PRINCIPAL de cet ordinateur est capturé et lu sur place ; seul le
     TEXTE part au moteur VELA, après les consentements « Captures d'écran » et
     « Texte de vos demandes ». L'image n'est ni envoyée ni gardée. Un délai
     avant la capture laisse le temps d'afficher la fenêtre à traduire : sans
     lui, IRIS traduirait sa propre fenêtre.
   - Interprétation : ouvre le mode interprète (deux sens, phrase par phrase).
     Ce n'est PAS de la simultanée : la traduction arrive quelques secondes
     après chaque phrase ; la carte le dit.
   - Procès-verbal de la réunion : ouvre les sous-titres locaux, qui portent le
     résumé (procès-verbal) sur demande.
   La traduction à sens unique à la voix (l'ancien mode, /api/traduction/*)
   reste accessible sous les cartes.
   Lunettes d'abord : traduire l'écran et la traduction à la voix agissent,
   elles exigent les lunettes.
   ========================================================================= */

const LANGUES_DEFAUT: { code: string; nom: string }[] = [
  { code: 'en', nom: 'Anglais' },
  { code: 'es', nom: 'Espagnol' },
  { code: 'pt', nom: 'Portugais' },
  { code: 'it', nom: 'Italien' },
  { code: 'de', nom: 'Allemand' },
  { code: 'fr', nom: 'Français' }
]

/** Langues cibles acceptées par la traduction d'écran (album.py, LANGUES_CIBLES). */
const LANGUES_ECRAN: { code: string; nom: string }[] = [
  { code: 'fr', nom: 'Français' },
  { code: 'en', nom: 'Anglais' },
  { code: 'es', nom: 'Espagnol' },
  { code: 'pt', nom: 'Portugais' },
  { code: 'it', nom: 'Italien' },
  { code: 'de', nom: 'Allemand' },
  { code: 'nl', nom: 'Néerlandais' },
  { code: 'pl', nom: 'Polonais' },
  { code: 'ro', nom: 'Roumain' },
  { code: 'el', nom: 'Grec' },
  { code: 'ru', nom: 'Russe' },
  { code: 'uk', nom: 'Ukrainien' },
  { code: 'tr', nom: 'Turc' },
  { code: 'ar', nom: 'Arabe' },
  { code: 'fa', nom: 'Persan' },
  { code: 'hi', nom: 'Hindi' },
  { code: 'pa', nom: 'Pendjabi' },
  { code: 'ur', nom: 'Ourdou' },
  { code: 'zh', nom: 'Chinois' },
  { code: 'ja', nom: 'Japonais' },
  { code: 'ko', nom: 'Coréen' },
  { code: 'vi', nom: 'Vietnamien' },
  { code: 'tl', nom: 'Tagalog' },
  { code: 'ht', nom: 'Créole haïtien' }
]

const DELAIS: { id: '0' | '5' | '10'; label: string }[] = [
  { id: '0', label: 'Tout de suite' },
  { id: '5', label: '5 s' },
  { id: '10', label: '10 s' }
]

const RAISONS: Record<string, string> = {
  demande: 'à votre demande',
  silence: 'après un long silence',
  erreur: 'après plusieurs échecs',
  traduction: 'relancée'
}

interface Echange {
  id: number
  genre: 'info' | 'entendu' | 'traduit'
  texte?: string
  langue?: string
  original?: string
  traduction?: string
  reponse_suggeree?: string
  reponse_traduite?: string
  latence?: number
}

interface ResultatEcran {
  texte_original: string
  traduction: string
  langue_cible: string
  local: boolean
  tronque: boolean
  duree_ms: number | null
}

const STYLE_CARTE: React.CSSProperties = {
  minHeight: 250,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 18,
  textAlign: 'center',
  border: 'none',
  color: 'var(--text)',
  width: '100%'
}
const STYLE_ICONE: React.CSSProperties = { width: 56, height: 56 }

function nomLangue(code: string, langues: { code: string; nom: string }[]): string {
  return langues.find((l) => l.code === code)?.nom || code
}

export function TraductionScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  const { nav, toast, settings, voice, presence, exigerLunettes, setConsent } = useStore()
  const [mode, setMode] = useState<'menu' | 'live' | 'ecran'>(params?.mode === 'live' ? 'live' : params?.mode === 'ecran' ? 'ecran' : 'menu')
  const [etat, setEtat] = useState<any>(null)
  const [langue, setLangue] = useState<string>('en')
  const [occupe, setOccupe] = useState(false)
  const [ecoute, setEcoute] = useState(false)
  const [fil, setFil] = useState<Echange[]>([])
  const compteur = useRef(1)
  const finFil = useRef<HTMLDivElement | null>(null)
  const wake: string = settings?.wake_word || 'Dis-moi Iris'
  const absentes = presence !== null && !presence.presentes

  /* ---------------------------------------------------------------- traduction par écran */
  const [langueEcran, setLangueEcran] = useState<string>('fr')
  const [delai, setDelai] = useState<'0' | '5' | '10'>('5')
  const [compteARebours, setCompteARebours] = useState<number | null>(null)
  const [traductionEnCours, setTraductionEnCours] = useState(false)
  const [resultatEcran, setResultatEcran] = useState<ResultatEcran | null>(null)
  const [voirOriginal, setVoirOriginal] = useState(false)
  const [erreurEcran, setErreurEcran] = useState<string | null>(null)
  const [refusEcran, setRefusEcran] = useState<{ data_type: string; label: string; message: string } | null>(null)
  const minuterie = useRef<number | null>(null)
  const monte = useRef(true)
  const zoneResultat = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    monte.current = true
    return () => {
      monte.current = false
      if (minuterie.current) window.clearInterval(minuterie.current)
    }
  }, [])

  const traduireEcranMaintenant = useCallback(async () => {
    setTraductionEnCours(true)
    setErreurEcran(null)
    setRefusEcran(null)
    try {
      const r = await api.post('/api/traduction/ecran', { langue_cible: langueEcran })
      if (!monte.current) return
      setResultatEcran({
        texte_original: String(r?.texte_original || ''),
        traduction: String(r?.traduction || ''),
        langue_cible: String(r?.langue_cible || langueEcran),
        local: Boolean(r?.local),
        tronque: Boolean(r?.tronque),
        duree_ms: typeof r?.duree_ms === 'number' ? r.duree_ms : null
      })
      setVoirOriginal(false)
      window.setTimeout(() => zoneResultat.current?.focus(), 0)
    } catch (err) {
      if (!monte.current || estLunettesRequises(err)) return
      const refus = refusConsentement(err)
      if (refus) setRefusEcran(refus)
      else setErreurEcran(messageErreur(err))
    } finally {
      if (monte.current) setTraductionEnCours(false)
    }
  }, [langueEcran])

  const lancerTraductionEcran = (): void => {
    if (traductionEnCours || compteARebours !== null) return
    if (!exigerLunettes('Traduction par écran')) return
    const secondes = Number(delai)
    if (!secondes) {
      traduireEcranMaintenant()
      return
    }
    setCompteARebours(secondes)
    let restant = secondes
    minuterie.current = window.setInterval(() => {
      restant -= 1
      if (restant <= 0) {
        if (minuterie.current) window.clearInterval(minuterie.current)
        minuterie.current = null
        setCompteARebours(null)
        traduireEcranMaintenant()
      } else {
        setCompteARebours(restant)
      }
    }, 1000)
  }

  const annulerCompteARebours = (): void => {
    if (minuterie.current) window.clearInterval(minuterie.current)
    minuterie.current = null
    setCompteARebours(null)
  }

  const autoriserEtReessayer = async (): Promise<void> => {
    if (!refusEcran) return
    try {
      await setConsent(refusEcran.data_type, true)
      setRefusEcran(null)
      traduireEcranMaintenant()
    } catch (err) {
      setErreurEcran(messageErreur(err))
    }
  }

  /* ---------------------------------------------------------------- traduction à sens unique (voix) */
  const langues: { code: string; nom: string }[] = Array.isArray(etat?.langues) && etat.langues.length ? etat.langues : LANGUES_DEFAUT

  const ajouter = useCallback((e: Omit<Echange, 'id'>) => {
    setFil((f) => [...f, { ...e, id: compteur.current++ }])
  }, [])

  const chargerEtat = useCallback(async () => {
    try {
      const r = await api.get('/api/traduction/etat')
      setEtat(r)
      if (r?.actif && r?.langue_entendue) setLangue(String(r.langue_entendue))
      if (r?.actif) setMode((m) => (m === 'menu' ? 'live' : m))
    } catch {
      /* le service ne connaît pas encore cet état : on garde les langues par défaut */
    }
  }, [])

  // Au montage, puis chaque fois que l'écoute vocale démarre ou s'arrête : `ecoute` (GET
  // /api/traduction/etat) dit si quelqu'un entend vraiment l'interlocuteur.
  const ecouteVocaleEnDirect: boolean | undefined = typeof voice?.running === 'boolean' ? voice.running : undefined
  useEffect(() => {
    chargerEtat()
  }, [chargerEtat, ecouteVocaleEnDirect])

  // Fil des échanges : événements « voice.traduction » du service (local à l'écran).
  useEffect(() => {
    return api.on((e: IrisEvent) => {
      if (e.type !== 'voice.traduction') return
      switch (e.etat) {
        case 'ouvert':
          setEtat((p: any) => ({ ...(p || {}), actif: true, langue_entendue: e.langue, langue_entendue_nom: e.langue_nom, empechement: '' }))
          setMode('live')
          ajouter({ genre: 'info', texte: `Traduction ouverte · ${e.langue_nom || e.langue || ''}`.trim() })
          break
        case 'ecoute':
          setEcoute(true)
          break
        case 'entendu':
          setEcoute(false)
          ajouter({ genre: 'entendu', texte: String(e.texte || ''), langue: e.langue })
          break
        case 'traduit':
          if (e.ok === false) {
            ajouter({ genre: 'info', texte: String(e.raison || e.a_dire || 'Phrase non traduite.') })
          } else {
            ajouter({
              genre: 'traduit',
              original: e.original,
              traduction: String(e.traduction || e.a_dire || ''),
              reponse_suggeree: e.reponse_suggeree,
              reponse_traduite: e.reponse_traduite,
              latence: typeof e.latence === 'number' ? e.latence : undefined
            })
          }
          break
        case 'ferme':
          setEcoute(false)
          setEtat((p: any) => ({ ...(p || {}), actif: false }))
          ajouter({ genre: 'info', texte: `Traduction terminée${e.raison && RAISONS[e.raison] ? ` (${RAISONS[e.raison]})` : ''}` })
          break
        default:
          break
      }
    })
  }, [ajouter])

  useEffect(() => {
    finFil.current?.scrollIntoView({ block: 'end' })
  }, [fil.length])

  const demarrer = async (): Promise<void> => {
    if (occupe) return
    if (!exigerLunettes('Traduction à la voix')) return
    setOccupe(true)
    try {
      const r = await api.post('/api/traduction/demarrer', { langue })
      const actif = Boolean(r?.actif ?? r?.ouvert)
      if (!actif) {
        toast(r?.phrase || r?.empechement || 'La traduction n’a pas pu démarrer.', 'error')
      } else if (r?.ecoute === false) {
        // Armé mais sourd : le service le dit dans sa phrase ; on ne le fête pas en vert.
        toast(r?.phrase || 'Traduction armée, mais l’écoute vocale est arrêtée : démarrez-la pour qu’IRIS entende votre interlocuteur.', 'info')
        setEtat((p: any) => ({ ...(p || {}), ...r, actif: true }))
      } else {
        toast(r?.phrase || 'Traduction démarrée.', 'success')
        setEtat((p: any) => ({ ...(p || {}), ...r, actif: true }))
      }
      await chargerEtat()
    } catch (err) {
      if (!estLunettesRequises(err)) toast(messageErreur(err), 'error')
    } finally {
      setOccupe(false)
    }
  }

  const arreter = async (): Promise<void> => {
    if (occupe) return
    setOccupe(true)
    try {
      const r = await api.post('/api/traduction/arreter')
      toast(r?.phrase || 'Traduction arrêtée.', 'info')
      setEtat((p: any) => ({ ...(p || {}), actif: false }))
      setEcoute(false)
      await chargerEtat()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      setOccupe(false)
    }
  }

  const actif = Boolean(etat?.actif)
  const live = mode === 'live' || actif
  const empechement: string = String(etat?.empechement || '')
  // Écoute vocale : le signal vivant du store (voice.state) d'abord, sinon l'instantané de l'état.
  const ecouteVocale: boolean | undefined = ecouteVocaleEnDirect ?? (typeof etat?.ecoute === 'boolean' ? etat.ecoute : undefined)
  const sourd = actif && ecouteVocale === false

  return (
    <div className="ecran">
      <TopBar titre="Traduction avec IA" />
      <div className="contenu">
        <div className="cartes-2">
          <button
            type="button"
            className="carte"
            style={{ ...STYLE_CARTE, outline: mode === 'ecran' ? '2px solid var(--blue)' : undefined }}
            aria-expanded={mode === 'ecran'}
            onClick={() => setMode(mode === 'ecran' ? 'menu' : 'ecran')}
          >
            <h3 style={{ fontSize: 26, margin: 0 }}>Traduction par écran</h3>
            <IcoTelephoneEcran style={STYLE_ICONE} />
            <span className="small muted" style={{ fontWeight: 600 }}>Le texte affiché sur cet ordinateur</span>
          </button>
          <button type="button" className="carte" style={STYLE_CARTE} onClick={() => nav.ouvrir('interprete')}>
            <h3 style={{ fontSize: 26, margin: 0 }}>Interprétation</h3>
            <IcoOreille style={STYLE_ICONE} />
            <span className="small muted" style={{ fontWeight: 600 }}>Dans les deux sens, phrase par phrase</span>
          </button>
          <button type="button" className="carte" style={STYLE_CARTE} onClick={() => nav.ouvrir('sous-titres')}>
            <h3 style={{ fontSize: 26, margin: 0 }}>Procès-verbal de la réunion</h3>
            <IcoReunion style={STYLE_ICONE} />
            <span className="small muted" style={{ fontWeight: 600 }}>Sous-titres sur cet ordinateur, résumé sur demande</span>
          </button>
        </div>

        <Liste>
          <Rangee
            icone={<IcoTraduire />}
            titre="Traduction à sens unique, à la voix"
            sous="Votre interlocuteur parle, IRIS vous traduit ce qu’il a dit et vous suggère une réponse."
            valeur={actif ? 'En cours' : undefined}
            onClick={() => setMode(live && !actif ? 'menu' : 'live')}
          />
        </Liste>

        {/* ------------------------------------------------------------ traduction par écran */}
        {mode === 'ecran' ? (
          <>
            {absentes ? <CarteLunettesRequises fonction="Traduction par écran" /> : null}
            <div className="carte col" style={{ gap: 14 }}>
              <h3 style={{ margin: 0 }}>Traduction par écran</h3>
              <p className="desc">
                IRIS capture l’écran principal de cet ordinateur et en lit le texte sur place. Seul ce texte part au moteur VELA pour être traduit, avec votre
                accord ; l’image n’est ni envoyée ni conservée.
              </p>
              <Field label="Traduire vers">
                <select className="select" value={langueEcran} disabled={traductionEnCours || compteARebours !== null} onChange={(e) => setLangueEcran(e.target.value)}>
                  {LANGUES_ECRAN.map((l) => (
                    <option key={l.code} value={l.code}>{l.nom}</option>
                  ))}
                </select>
              </Field>
              <div>
                <div className="small muted" style={{ fontWeight: 600, marginBottom: 6 }}>Délai avant la capture (le temps d’afficher la fenêtre à traduire)</div>
                <Segmente options={DELAIS} valeur={delai} onChange={setDelai} />
              </div>
              {compteARebours !== null ? (
                <div className="col" style={{ gap: 8 }}>
                  <div aria-live="assertive" style={{ fontSize: 22, fontWeight: 800, textAlign: 'center' }}>
                    Capture dans {compteARebours} s : affichez la fenêtre à traduire.
                  </div>
                  <Holo variante="contour" onClick={annulerCompteARebours}>Annuler</Holo>
                </div>
              ) : (
                <Holo disabled={traductionEnCours} onClick={lancerTraductionEcran}>
                  {traductionEnCours ? 'Lecture et traduction…' : 'Traduire l’écran'}
                </Holo>
              )}
              <p className="small muted" style={{ lineHeight: 1.45, margin: 0 }}>
                Au plus 8 000 caractères : au-delà, la fin est coupée et IRIS le signale. Impossible en mode confidentiel, et en mode 100 % local sans IA locale.
                Un texte en image très petite ou stylisée peut être mal lu.
              </p>
            </div>

            {refusEcran ? <CarteConsentement refus={refusEcran} onAutoriser={autoriserEtReessayer} onFermer={() => setRefusEcran(null)} /> : null}
            {erreurEcran ? <div className="bloc-note erreur" role="alert">{erreurEcran}</div> : null}

            {resultatEcran ? (
              <div className="carte col" style={{ gap: 12 }} ref={zoneResultat} tabIndex={-1} aria-live="polite">
                <div className="row between wrap" style={{ gap: 8 }}>
                  <h3 style={{ margin: 0 }}>Traduction · {nomLangue(resultatEcran.langue_cible, LANGUES_ECRAN)}</h3>
                  <div className="row wrap" style={{ gap: 6 }}>
                    <span className="pill">{resultatEcran.local ? 'IA locale' : 'moteur VELA'}</span>
                    {resultatEcran.duree_ms !== null ? <span className="pill">{(resultatEcran.duree_ms / 1000).toFixed(1).replace('.', ',')} s mesurées</span> : null}
                  </div>
                </div>
                {resultatEcran.tronque ? (
                  <div className="bloc-note attention">Le texte de l’écran dépassait 8 000 caractères : seule la première partie a été traduite.</div>
                ) : null}
                <div style={{ whiteSpace: 'pre-wrap', fontSize: 18, lineHeight: 1.5, userSelect: 'text' }}>{resultatEcran.traduction}</div>
                <div className="row wrap" style={{ gap: 8 }}>
                  <button type="button" className="btn sm" onClick={() => setVoirOriginal((v) => !v)}>
                    {voirOriginal ? 'Masquer le texte lu' : 'Voir le texte lu à l’écran'}
                  </button>
                  <button
                    type="button"
                    className="btn sm"
                    onClick={() => {
                      navigator.clipboard?.writeText(resultatEcran.traduction).then(
                        () => toast('Traduction copiée.', 'success'),
                        () => toast('Copie impossible : sélectionnez le texte à la main.', 'error')
                      )
                    }}
                  >
                    Copier la traduction
                  </button>
                </div>
                {voirOriginal ? (
                  <div className="bloc-note" style={{ whiteSpace: 'pre-wrap', userSelect: 'text' }}>{resultatEcran.texte_original}</div>
                ) : null}
                <div className="small muted" style={{ lineHeight: 1.45 }}>
                  Traduction automatique : vérifiez-la avant de vous en servir pour une décision importante. Rien n’est gardé après la fermeture de cet écran.
                </div>
              </div>
            ) : null}
          </>
        ) : null}

        {/* ------------------------------------------------------------ traduction à sens unique */}
        {live ? (
          <>
            {absentes && !actif ? <CarteLunettesRequises fonction="Traduction à la voix" /> : null}
            <div className="carte">
              <div className="row between wrap" style={{ marginBottom: 12 }}>
                <h3 style={{ margin: 0 }}>Traduction à sens unique</h3>
                {actif ? <span className="pill ok">En cours · {etat?.langue_entendue_nom || nomLangue(String(etat?.langue_entendue || langue), langues)}</span> : null}
                {sourd ? <span className="pill warn" title="Le mode est armé, mais aucun micro n’écoute votre interlocuteur.">Écoute vocale arrêtée</span> : null}
                {actif && !sourd && ecoute ? <span className="pill">À l’écoute</span> : null}
              </div>
              <Field label="Langue de votre interlocuteur">
                <select className="select" value={langue} disabled={actif || occupe} onChange={(e) => setLangue(e.target.value)}>
                  {langues.map((l) => (
                    <option key={l.code} value={l.code}>{l.nom}</option>
                  ))}
                </select>
              </Field>
              <div style={{ marginTop: 14 }}>
                {!actif ? (
                  <Holo onClick={demarrer} disabled={occupe}>Démarrer</Holo>
                ) : (
                  <Holo variante="rouge" onClick={arreter} disabled={occupe}>Arrêter</Holo>
                )}
              </div>
              <p className="muted small" style={{ marginTop: 12, lineHeight: 1.4 }}>
                La traduction arrive quelques secondes après la fin de chaque phrase, pas pendant. Elle exige les lunettes VELA et le moteur VELA (indisponible en
                mode 100 % local) ; la voix de votre interlocuteur est transcrite en ligne, et il n’a rien consenti : prévenez-le.
              </p>
              {empechement ? (
                <div style={{ marginTop: 8 }}>
                  <span className="pill warn" style={{ whiteSpace: 'normal', lineHeight: 1.35 }}>{empechement}</span>
                </div>
              ) : null}
              <p className="muted small" style={{ marginTop: 8, lineHeight: 1.4 }}>
                Vous pouvez aussi dire : « {wake}, traduis ce qu’il dit en {nomLangue(langue, langues).toLowerCase()} ».
              </p>
            </div>

            {fil.length === 0 ? (
              <Vide icone={<IcoOreille style={{ color: 'var(--text-2)' }} />} texte="Aucun échange pour le moment" />
            ) : (
              <div className="fil">
                {fil.map((e) => {
                  if (e.genre === 'info') return <div key={e.id} className="date">{e.texte}</div>
                  if (e.genre === 'entendu') {
                    return (
                      <div key={e.id} className="message">
                        <div className="colonne-msg">
                          <div className="bulle" style={{ background: 'var(--surface)', color: 'var(--text)' }}>{e.texte}</div>
                          {e.langue ? <div className="meta"><span className="etiquette">{nomLangue(e.langue, langues)}</span></div> : null}
                        </div>
                      </div>
                    )
                  }
                  return (
                    <div key={e.id} className="message">
                      <div className="colonne-msg">
                        <div className="bulle ia">{e.traduction}</div>
                        {e.reponse_suggeree ? (
                          <div className="muted small" style={{ padding: '0 4px', lineHeight: 1.4 }}>
                            Réponse suggérée : {e.reponse_suggeree}
                            {e.reponse_traduite ? <> → {e.reponse_traduite}</> : null}
                          </div>
                        ) : null}
                        {typeof e.latence === 'number' ? <div className="meta">{e.latence.toFixed(1)} s mesurées</div> : null}
                      </div>
                    </div>
                  )
                })}
                <div ref={finFil} />
              </div>
            )}
          </>
        ) : null}
      </div>
    </div>
  )
}
