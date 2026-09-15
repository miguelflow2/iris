import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Field, Holo, Segmente, Toggle, TopBar } from '../components/ui'
import { IcoCamera, IcoChevronD, IcoChevronG, IcoHautParleur, IcoHorloge, IcoImage, IcoStop } from '../components/icons'
import { CarteLunettesRequises } from '../components/LunettesRequises'
import { ApiError, api, messageErreur, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import { BlocRefus, chrono, dureeLisible, dureeMesuree, lireRefus, useTic, VideCompact, type Refus } from './CoursScreen'
import './AccessibiliteScreen.css'
import './CoursScreen.css'

/* =========================================================================
   « Pas à pas » : suivre une recette, un montage ou une réparation les mains
   occupées. L'étape courante en très grand texte, trois gros boutons, et la
   voix : « suivant », « répète », « lance le minuteur », « c'est fini ».

   Ce que fait le service (backend/iris/pas_a_pas.py), dit à l'écran :
   - des étapes fournies sont lues telles quelles, rien ne quitte l'ordinateur ;
     des étapes rédigées par le moteur VELA sont annoncées comme telles, avec
     leur avertissement (notice du fabricant, cuisson, professionnel) ;
   - un minuteur n'est jamais inventé : il vient d'une durée DITE dans l'étape,
     ou d'une durée que vous donnez ;
   - « Est-ce que c'est bon ? » décrit UNE photo : un regard, pas une garantie.

   Lunettes d'abord : démarrer et avancer exigent les lunettes ; terminer et
   annuler un minuteur, jamais (on doit toujours pouvoir arrêter).
   ========================================================================= */

interface Etape {
  n: number
  texte: string
  minuteur_s: number | null
}

interface Minuteur {
  etape: number
  duree_s: number
  restant_s: number
}

interface Session {
  actif: boolean
  id?: string
  sujet?: string
  type?: string
  etapes?: Etape[]
  index?: number
  source_etapes?: string
  local?: boolean
  avertissement?: string | null
  minuteurs?: Minuteur[]
  ecoute_active?: boolean
  limite?: string
}

interface Verification {
  phrase: string
  texte: string
  local: boolean
  duree_ms: number | null
}

type TypePas = 'recette' | 'montage' | 'reparation' | 'autre'

const TYPES: { id: TypePas; label: string }[] = [
  { id: 'recette', label: 'Recette' },
  { id: 'montage', label: 'Montage' },
  { id: 'reparation', label: 'Réparation' },
  { id: 'autre', label: 'Autre' }
]
const NOMS_TYPES: Record<string, string> = { recette: 'Recette', montage: 'Montage', reparation: 'Réparation', autre: 'Pas à pas' }

// Actions qui n'exigent jamais les lunettes : on doit toujours pouvoir arrêter.
const SANS_LUNETTES = new Set(['terminer', 'annuler_minuteur'])

export function PasAPasScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { settings, toast, presence, exigerLunettes } = useStore()
  const [session, setSession] = useState<Session | null>(null)
  const [recuA, setRecuA] = useState(() => Date.now())
  const [erreurEtat, setErreurEtat] = useState('')
  const [sujet, setSujet] = useState('')
  const [type, setType] = useState<TypePas>('recette')
  const [avecEtapes, setAvecEtapes] = useState(false)
  const [etapesTexte, setEtapesTexte] = useState('')
  const [enCours, setEnCours] = useState<string | null>(null)
  // Arrêter (terminer, annuler un minuteur) a son propre état : une vérification photo en vol ne doit
  // jamais rendre le bouton rouge inopérant.
  const [enArret, setEnArret] = useState<string | null>(null)
  const [refus, setRefus] = useState<(Refus & { action?: string; reessayer: () => void }) | null>(null)
  const [phrase, setPhrase] = useState('')
  const [verification, setVerification] = useState<Verification | null>(null)
  const [minutesPerso, setMinutesPerso] = useState('')
  const vivant = useRef(true)
  // Incrémenté à chaque arrêt : la réponse tardive d'une commande partie avant l'arrêt (vérification
  // photo de plusieurs secondes) ne doit pas réafficher la session terminée.
  const generation = useRef(0)
  const commandeRef = useRef<(action: string, extra?: Record<string, unknown>) => void>(() => undefined)

  const absentes = presence !== null && !presence.presentes
  const actif = Boolean(session?.actif)
  const minuteurs = session?.minuteurs || []
  const tic = useTic(minuteurs.length > 0, 500)

  const appliquer = (etat: Session | null | undefined): void => {
    setSession(etat && typeof etat === 'object' ? etat : { actif: false })
    setRecuA(Date.now())
  }

  const charger = useCallback(async () => {
    try {
      const r = await api.get('/api/pas-a-pas/etat')
      if (!vivant.current) return
      setSession(r && typeof r === 'object' ? r : { actif: false })
      setRecuA(Date.now())
      setErreurEtat('')
    } catch (err) {
      if (vivant.current) setErreurEtat(messageErreur(err))
    }
  }, [])

  useEffect(() => {
    vivant.current = true
    charger()
    // La voix fait avancer la même session : l'écran suit l'événement (session imbriquée, jamais « type »).
    const off = api.on((e: IrisEvent) => {
      if (e.type !== 'pas_a_pas.etat') return
      setSession(e.session && typeof e.session === 'object' ? e.session : { actif: false })
      setRecuA(Date.now())
      if (typeof e.annonce === 'string' && e.annonce) {
        setPhrase(e.annonce)
        if (e.annonce.startsWith('Minuteur terminé')) toast(e.annonce, 'info')
      }
    })
    return () => {
      vivant.current = false
      off()
    }
  }, [charger, toast])

  const demarrer = async (): Promise<void> => {
    if (enCours) return
    const etapes = avecEtapes
      ? etapesTexte
          .split(/\r?\n/)
          .map((l) => l.replace(/^\s*(\d+[.)-]|[-*•])\s*/, '').trim())
          .filter(Boolean)
      : null
    if (avecEtapes && !etapes?.length) {
      setRefus({ message: 'Écrivez au moins une étape (une par ligne).', consentement: null, reessayer: () => undefined })
      return
    }
    if (!avecEtapes && !sujet.trim()) {
      setRefus({ message: 'Précisez le sujet (par exemple « crêpes » ou « changer un joint de robinet »), ou fournissez les étapes.', consentement: null, reessayer: () => undefined })
      return
    }
    if (!exigerLunettes('Pas à pas')) return
    setEnCours('demarrer')
    setRefus(null)
    setVerification(null)
    try {
      const r = await api.post('/api/pas-a-pas/demarrer', { sujet: sujet.trim(), type, etapes, parler: true })
      if (!vivant.current) return
      const { phrase: p, ...etat } = r || {}
      appliquer(etat as Session)
      setPhrase(typeof p === 'string' ? p : '')
    } catch (err) {
      if (!vivant.current) return
      const x = lireRefus(err)
      if (x) setRefus({ ...x, reessayer: () => demarrer() })
    } finally {
      if (vivant.current) setEnCours(null)
    }
  }

  /** Terminer ou annuler un minuteur : envoyé même si une autre commande est en vol. */
  const arreter = async (action: string): Promise<void> => {
    if (enArret === action) return
    setEnArret(action)
    setRefus(null)
    try {
      const r = await api.post('/api/pas-a-pas/commande', { action, parler: true })
      if (!vivant.current) return
      if (action === 'terminer') generation.current += 1
      const { phrase: p, verification: _v, ...etat } = r || {}
      appliquer(etat as Session)
      if (typeof p === 'string') setPhrase(p)
    } catch (err) {
      if (!vivant.current) return
      if (err instanceof ApiError && err.status === 409 && /Aucun pas à pas/.test(err.message)) {
        charger()
        return
      }
      const x = lireRefus(err)
      if (x) setRefus({ ...x, action, reessayer: () => arreter(action) })
    } finally {
      if (vivant.current) setEnArret(null)
    }
  }

  const commande = async (action: string, extra: Record<string, unknown> = {}): Promise<void> => {
    if (SANS_LUNETTES.has(action)) {
      await arreter(action)
      return
    }
    if (enCours) return
    if (!exigerLunettes('Pas à pas')) return
    setEnCours(action)
    setRefus(null)
    if (action === 'verifier') setVerification(null)
    const partie = generation.current
    try {
      const r = await api.post('/api/pas-a-pas/commande', { action, parler: true, ...extra })
      if (!vivant.current || partie !== generation.current) return
      const { phrase: p, verification: v, ...etat } = r || {}
      appliquer(etat as Session)
      if (typeof p === 'string') setPhrase(p)
      if (v && typeof v === 'object') setVerification(v as Verification)
    } catch (err) {
      if (!vivant.current || partie !== generation.current) return
      if (err instanceof ApiError && err.status === 409 && /Aucun pas à pas/.test(err.message)) {
        charger()
        return
      }
      const x = lireRefus(err)
      if (x) setRefus({ ...x, action, reessayer: () => commande(action, extra) })
    } finally {
      if (vivant.current) setEnCours(null)
    }
  }
  commandeRef.current = (action, extra) => {
    commande(action, extra)
  }

  // Au clavier, sans lâcher ce qu'on a dans les mains trop longtemps : ← précédent, → suivant, R répéter.
  useEffect(() => {
    if (!actif) return
    const touche = (e: KeyboardEvent): void => {
      const cible = e.target as HTMLElement | null
      if (e.altKey || e.ctrlKey || e.metaKey || (cible && /^(INPUT|TEXTAREA|SELECT)$/.test(cible.tagName)) || cible?.isContentEditable) return
      if (e.key === 'ArrowRight') commandeRef.current('suivant')
      else if (e.key === 'ArrowLeft') commandeRef.current('precedent')
      else if (e.key === 'r' || e.key === 'R') commandeRef.current('repeter')
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', touche)
    return () => window.removeEventListener('keydown', touche)
  }, [actif])

  const verifierAvecImage = async (): Promise<void> => {
    if (enCours) return
    if (!exigerLunettes('Pas à pas')) return
    try {
      const img = await window.iris.pickImage()
      if (!img) return
      commande('verifier', { image: { media_type: img.media_type, data: img.data } })
    } catch (err) {
      toast(messageErreur(err), 'error')
    }
  }

  const arreterVoix = (): void => {
    api.post('/api/voice/stop_speaking').catch((err) => toast(messageErreur(err), 'error'))
  }

  const motActivation = String(settings?.wake_word || 'Dis-moi Iris')
  const etapes = session?.etapes || []
  const index = Math.min(Math.max(0, Number(session?.index) || 0), Math.max(0, etapes.length - 1))
  const etape = etapes[index]
  const restant = (m: Minuteur): number => Math.max(0, m.restant_s - (tic - recuA) / 1000)
  const minuteurEtape = etape ? minuteurs.find((m) => m.etape === etape.n) : undefined
  const autresMinuteurs = minuteurs.filter((m) => !etape || m.etape !== etape.n)

  return (
    <div className="ecran">
      <TopBar titre="Pas à pas" />
      <div className="contenu">
        {absentes ? <CarteLunettesRequises fonction="Pas à pas, mains occupées" /> : null}
        {erreurEtat ? <div className="bloc-note erreur" role="alert">{erreurEtat}</div> : null}

        {session === null && !erreurEtat ? <div className="empty">Chargement…</div> : null}

        {/* ------------------------------------------------------------ nouvelle session */}
        {session !== null && !actif ? (
          <>
            <div className="carte">
              <VideCompact
                glyphe="etapes"
                texte="Une étape à la fois, à la voix"
                petit="Recette, montage ou réparation : IRIS lit chaque étape, avance quand vous dites « suivant » et lance les minuteurs indiqués."
              />
            </div>
            <div className="carte q-formulaire">
              <Field label="Sujet">
                <input
                  className="input"
                  value={sujet}
                  maxLength={160}
                  placeholder="Ex. : crêpes, monter une étagère, changer un joint de robinet"
                  onChange={(e) => setSujet(e.target.value)}
                />
              </Field>
              <div className="segmente-souple">
                <Segmente options={TYPES} valeur={type} onChange={setType} />
              </div>
              <div className="row between" style={{ gap: 12 }}>
                <span style={{ fontWeight: 600 }}>J’ai déjà les étapes</span>
                <Toggle on={avecEtapes} onChange={setAvecEtapes} titre="J’ai déjà les étapes" />
              </div>
              {avecEtapes ? (
                <Field label="Étapes (une par ligne)" hint="Lues telles quelles : rien ne quitte l’ordinateur. Une durée écrite dans l’étape (« cuire 10 minutes ») devient un minuteur.">
                  <textarea
                    className="textarea"
                    rows={6}
                    value={etapesTexte}
                    placeholder={'Mélanger la farine et les œufs\nAjouter le lait petit à petit\nLaisser reposer 30 minutes'}
                    onChange={(e) => setEtapesTexte(e.target.value)}
                  />
                </Field>
              ) : (
                <div className="q-note">
                  Sans étapes fournies, IRIS envoie le sujet au moteur VELA pour les rédiger (accord « Texte de vos demandes »). Les étapes
                  rédigées automatiquement sont à vérifier ; pour une réparation, la notice du fabricant a priorité.
                </div>
              )}
              <Holo disabled={Boolean(enCours)} onClick={demarrer}>
                {enCours === 'demarrer' ? (avecEtapes ? 'Démarrage…' : 'IRIS rédige les étapes…') : 'Démarrer'}
              </Holo>
              {refus ? <BlocRefus refus={refus} onFermer={() => setRefus(null)} onReessayer={refus.reessayer} /> : null}
            </div>
            {phrase ? (
              <div className="q-dit" role="status"><span className="qui">IRIS a dit</span>{phrase}</div>
            ) : null}
          </>
        ) : null}

        {/* ------------------------------------------------------------ session en cours */}
        {actif && etape ? (
          <>
            <div className="col" style={{ gap: 4 }}>
              <div className="q-meta">
                <span>{NOMS_TYPES[session?.type || 'autre'] || 'Pas à pas'}</span>
                <span className={`etiquette-locale ${session?.source_etapes === 'moteur' && !session?.local ? 'moteur' : 'local'}`}>
                  {session?.source_etapes === 'fournies' ? 'Vos étapes' : session?.local ? 'Étapes rédigées sur cet ordinateur' : 'Étapes rédigées par le moteur VELA'}
                </span>
              </div>
              <h2 style={{ fontSize: 24, fontWeight: 800, lineHeight: 1.2, wordBreak: 'break-word' }}>{session?.sujet}</h2>
            </div>

            {session?.avertissement ? <div className="bloc-note attention" role="note">{session.avertissement}</div> : null}

            <div className="steps" aria-hidden="true">
              {etapes.map((e, i) => (
                <span key={e.n} className={i <= index ? 'done' : ''} />
              ))}
            </div>

            <div className="q-etape-courante">
              <div className="numero">Étape {etape.n} sur {etapes.length}</div>
              {/* Pas d'annonce au lecteur d'écran : IRIS lit déjà l'étape à voix haute. */}
              <div className="texte" aria-live="off">{etape.texte}</div>
            </div>

            {/* ------------------------------------------------------------ minuteur */}
            {minuteurEtape ? (
              <div className="q-minuteur" role="timer" aria-label={`Minuteur de l’étape ${etape.n}`}>
                <IcoHorloge />
                <span className="temps">{chrono(restant(minuteurEtape))}</span>
                <span className="corps">Minuteur de l’étape {etape.n} ({dureeLisible(minuteurEtape.duree_s)})</span>
                <Holo taille="mini" variante="sombre" disabled={enArret === 'annuler_minuteur'} onClick={() => arreter('annuler_minuteur')}>Annuler</Holo>
              </div>
            ) : etape.minuteur_s ? (
              <div className="q-minuteur">
                <IcoHorloge />
                <span className="corps">Cette étape indique {dureeLisible(etape.minuteur_s)}.</span>
                <Holo taille="mini" variante="blanc" disabled={Boolean(enCours)} onClick={() => commande('minuteur')}>Lancer le minuteur</Holo>
              </div>
            ) : (
              <div className="q-minuteur">
                <IcoHorloge />
                <span className="corps">Pas de durée dans cette étape.</span>
                <input
                  className="input q-champ-court"
                  type="number"
                  min={1}
                  max={1440}
                  inputMode="numeric"
                  aria-label="Durée du minuteur, en minutes"
                  placeholder="min"
                  value={minutesPerso}
                  onChange={(e) => setMinutesPerso(e.target.value)}
                />
                <Holo
                  taille="mini"
                  variante="sombre"
                  disabled={Boolean(enCours) || !(Number(minutesPerso) > 0)}
                  onClick={() => commande('minuteur', { secondes: Math.round(Number(minutesPerso) * 60) })}
                >
                  Lancer
                </Holo>
              </div>
            )}
            {autresMinuteurs.map((m) => (
              <div key={m.etape} className="q-minuteur" role="timer">
                <IcoHorloge />
                <span className="temps" style={{ fontSize: 26 }}>{chrono(restant(m))}</span>
                <span className="corps">Minuteur de l’étape {m.etape}</span>
              </div>
            ))}

            {/* ------------------------------------------------------------ commandes */}
            <div className="q-commandes">
              <button type="button" className="q-gros-bouton" disabled={Boolean(enCours) || index <= 0} onClick={() => commande('precedent')}>
                <IcoChevronG /> Précédent
              </button>
              <button type="button" className="q-gros-bouton" disabled={Boolean(enCours)} onClick={() => commande('repeter')}>
                <IcoHautParleur /> Répéter
              </button>
              <button type="button" className="q-gros-bouton principal" disabled={Boolean(enCours)} onClick={() => commande('suivant')}>
                <IcoChevronD /> Suivant
              </button>
            </div>
            <div className="q-actions">
              <Holo taille="mini" variante="sombre" onClick={arreterVoix}><IcoStop /> Couper la voix</Holo>
              <span className="q-note">Au clavier : ← précédent, → suivant, R répéter.</span>
            </div>

            {refus && refus.action !== 'verifier' ? <BlocRefus refus={refus} onFermer={() => setRefus(null)} onReessayer={refus.reessayer} /> : null}
            {phrase ? (
              <div className="q-dit" role="status"><span className="qui">IRIS a dit</span>{phrase}</div>
            ) : null}

            {/* ------------------------------------------------------------ vérification */}
            <div className="carte col" style={{ gap: 10 }}>
              <h3 style={{ margin: 0 }}>Est-ce que c’est bon ?</h3>
              <div className="q-grille-2">
                <Holo taille="petit" disabled={Boolean(enCours)} onClick={() => commande('verifier')}>
                  <IcoCamera /> {enCours === 'verifier' ? 'IRIS regarde…' : 'Photo des lunettes'}
                </Holo>
                <Holo taille="petit" variante="sombre" disabled={Boolean(enCours)} onClick={verifierAvecImage}>
                  <IcoImage /> Choisir une image
                </Holo>
              </div>
              {refus && refus.action === 'verifier' ? <BlocRefus refus={refus} onFermer={() => setRefus(null)} onReessayer={refus.reessayer} /> : null}
              {verification ? (
                <div className="col" style={{ gap: 6 }} aria-live="polite">
                  <div style={{ fontSize: 19, fontWeight: 700, lineHeight: 1.4 }}>{verification.phrase}</div>
                  <div className="q-meta">
                    <span className={`etiquette-locale ${verification.local ? 'local' : 'moteur'}`}>
                      {verification.local ? 'Décrit sur cet ordinateur' : 'Décrit par le moteur VELA'}
                    </span>
                    {typeof verification.duree_ms === 'number' ? <span>Durée mesurée : {dureeMesuree(verification.duree_ms)}</span> : null}
                  </div>
                </div>
              ) : null}
              <div className="q-note">
                IRIS décrit une seule photo au regard de l’étape : ce n’est pas une garantie de cuisson ni de sécurité. La caméra des lunettes
                n’est pas encore activée dans IRIS (protocole en cours de confirmation) : en attendant, choisissez une photo prise avec votre
                téléphone.
              </div>
            </div>

            {/* ------------------------------------------------------------ étapes */}
            <div className="carte col" style={{ gap: 6 }}>
              <h3 style={{ margin: 0 }}>Toutes les étapes</h3>
              <ol className="q-etapes">
                {etapes.map((e, i) => (
                  <li key={e.n} className={i === index ? 'courante' : i < index ? 'faite' : ''} aria-current={i === index ? 'step' : undefined}>
                    <span className="n">{e.n}</span>
                    <span>
                      {e.texte}
                      {e.minuteur_s ? <span className="muted"> · {dureeLisible(e.minuteur_s)}</span> : null}
                    </span>
                  </li>
                ))}
              </ol>
            </div>

            <Holo variante="rouge" disabled={enArret === 'terminer'} onClick={() => arreter('terminer')}>
              {enArret === 'terminer' ? 'Arrêt…' : 'Terminer le pas à pas'}
            </Holo>
          </>
        ) : null}

        {/* ------------------------------------------------------------ voix et limites */}
        <div className="carte col" style={{ gap: 10 }}>
          <h3 style={{ margin: 0 }}>À la voix</h3>
          <div className="q-note">Commencez par « {motActivation} », puis :</div>
          <ul className="q-phrases">
            <li>« guide-moi pas à pas pour faire des crêpes »</li>
            <li>« suivant »</li>
            <li>« précédent »</li>
            <li>« répète »</li>
            <li>« on en est où ? »</li>
            <li>« lance le minuteur »</li>
            <li>« lance un minuteur de 5 minutes »</li>
            <li>« annule le minuteur »</li>
            <li>« est-ce que c’est bon ? »</li>
            <li>« c’est fini »</li>
          </ul>
          <ul className="liste-limites">
            {session?.limite ? (
              <li>{session.limite}</li>
            ) : (
              <>
                <li>Chaque commande vocale passe par le mot d’activation, sauf pendant la courte fenêtre de conversation qui suit une réponse d’IRIS.</li>
                <li>Les minuteurs tournent sur l’ordinateur : une mise en veille retarde l’annonce. Rien de la session n’est conservé.</li>
              </>
            )}
          </ul>
        </div>
      </div>
    </div>
  )
}
