import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, messageErreur } from '../lib/api'
import { useStore } from '../lib/store'
import { CarteReglage, Field, Holo, TopBar } from '../components/ui'
import { IcoMicro, IcoRobotDegrade } from '../components/icons'
import { LunettesFace } from '../components/Lunettes'

/* =========================================================================
   Première ouverture d'IRIS (porté de _ancien/views/Onboarding.tsx).
   Six étapes : Bienvenue · Compte · Lunettes · Consentement · Audio · Voix,
   rendues en plein écran dans le style des maquettes (IMG_0709/0710 : robot en
   dégradé, cartes anthracite, grand bouton holographique en bas).
   Avec `seulementCompte`, seule l'étape du compte est réclamée — et elle se
   masque d'elle-même dès que le compte est déjà en place.

   Étape « Lunettes » (règle « lunettes d'abord » du 2026-09-13) : détecter et
   connecter la paire comme l'écran Connecter (l'accueil est une surcouche, la
   pile d'écrans n'y est pas visible), ou dire « Je n'ai pas encore mes
   lunettes » : IRIS explique alors l'aperçu écrit (sa taille réelle vient de
   GET /api/lunettes/presence) et offre le lien d'achat. Jamais de mention d'un
   mode sans lunettes.
   ========================================================================= */

type Props = {
  /** Ne demander que le compte, sans le reste de l'accueil.
   *
   * Sert aux installations déjà configurées avant que l'étape existe : sans cela, elles ne se
   * verraient jamais réclamer de mot de passe, et l'accès depuis le téléphone resterait sans
   * protection sans que personne le sache. */
  seulementCompte?: boolean
}

const WAKE_DEFAUT = 'Dis-moi Iris'
const URL_ACHAT_DEFAUT = 'https://velaglass.ca/lunettes.html'

/** Libellés de la barre de progression (l'étape « Compte » doit y figurer : backend/tests/test_comptes.py). */
const ETAPES = ['Bienvenue', 'Compte', 'Lunettes', 'Consentement', 'Audio', 'Voix']

/** Appareil Bluetooth détecté (POST /api/glasses/scan), comme dans ConnecterScreen. */
interface AppareilBle {
  address: string
  name: string
  rssi: number | null
  likely_glasses: boolean
  paired?: boolean
}

interface CompteInfo {
  configure: boolean
  nom?: string
}

interface Peripheriques {
  devices: string[]
  outputs: string[]
}

/** Avancement réel du téléchargement du modèle (événement `voice.model_progress`). */
interface Avancement {
  done: number
  total: number
}

export function Onboarding({ seulementCompte = false }: Props = {}): JSX.Element | null {
  const { settings, updateSettings, consent, setConsent, toast, voice, lunettes, rafraichirLunettes, presence, rafraichirPresence } = useStore()
  const [step, setStep] = useState(seulementCompte ? 1 : 0)
  const [comptePose, setComptePose] = useState(false)
  const [name, setName] = useState<string>(settings?.user_name || '')
  const [wake, setWake] = useState<string>(settings?.wake_word || WAKE_DEFAUT)
  const [downloading, setDownloading] = useState(false)
  const [avancement, setAvancement] = useState<Avancement | null>(null)

  // Le compte du propriétaire. IRIS exécute des commandes sur cet ordinateur : on ne laisse pas
  // cet accès ouvert au premier appareil qui connaît l'adresse. Voir backend/iris/comptes.py.
  const [compte, setCompte] = useState<CompteInfo | null>(null)
  const [email, setEmail] = useState('')
  const [mdp, setMdp] = useState('')
  const [mdp2, setMdp2] = useState('')
  const [compteErreur, setCompteErreur] = useState<string | null>(null)
  const [compteOccupe, setCompteOccupe] = useState(false)

  const [devices, setDevices] = useState<Peripheriques>({ devices: [], outputs: [] })

  // Étape « Lunettes » : détection Bluetooth, connexion (jusqu'à 3 × 30 s côté service), ou aperçu sans lunettes.
  const [appareils, setAppareils] = useState<AppareilBle[]>([])
  const [detection, setDetection] = useState(false)
  const [detectionFaite, setDetectionFaite] = useState(false)
  const [connexionA, setConnexionA] = useState<string | null>(null)
  const [tentative, setTentative] = useState<{ attempt: number; attempts: number } | null>(null)
  const [pasEncore, setPasEncore] = useState(false)
  const monte = useRef(true)
  useEffect(() => {
    monte.current = true
    return () => {
      monte.current = false
    }
  }, [])

  useEffect(() => {
    api.get<Peripheriques>('/api/voice/devices').then(setDevices).catch(() => undefined)
    api.get<CompteInfo>('/api/compte').then(setCompte).catch(() => setCompte({ configure: false }))
  }, [])

  // Avancement du modèle de reconnaissance : uniquement ce que le service annonce, jamais inventé.
  useEffect(() => {
    return api.on((event) => {
      if (event.type === 'voice.model_progress') {
        setDownloading(true)
        setAvancement({ done: Number(event.done) || 0, total: Number(event.total) || 0 })
      } else if (event.type === 'voice.model_ready') {
        setDownloading(false)
        setAvancement(null)
      } else if (event.type === 'glasses.connecting') {
        setTentative({ attempt: Number(event.attempt) || 1, attempts: Number(event.attempts) || 3 })
      } else if (event.type === 'glasses.connected' || event.type === 'glasses.disconnected') {
        setTentative(null)
      }
    })
  }, [])

  const detecter = useCallback(async () => {
    setDetection(true)
    try {
      const r = await api.post('/api/glasses/scan', { seconds: 6 })
      if (!monte.current) return
      setAppareils(Array.isArray(r?.devices) ? r.devices : [])
      if (r?.error) toast(String(r.error), 'error')
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) {
        setDetection(false)
        setDetectionFaite(true)
      }
    }
  }, [toast])

  const connecter = useCallback(
    async (a: AppareilBle) => {
      setConnexionA(a.address)
      setTentative(null)
      try {
        await api.post('/api/glasses/connect', { address: a.address, name: a.name })
        await rafraichirLunettes()
        await rafraichirPresence()
      } catch (err) {
        toast(messageErreur(err), 'error')
      } finally {
        if (monte.current) {
          setConnexionA(null)
          setTentative(null)
        }
      }
    },
    [rafraichirLunettes, rafraichirPresence, toast]
  )

  // En arrivant sur l'étape « Lunettes » sans paire connectée : une détection part d'elle-même,
  // comme à l'ouverture de l'écran Connecter. Une seule fois : l'utilisateur relance à la main.
  const lunettesConnectees = Boolean(lunettes?.connected)
  useEffect(() => {
    if (step !== 2 || lunettesConnectees || detectionFaite || detection) return
    rafraichirPresence().catch(() => undefined)
    detecter()
  }, [step, lunettesConnectees, detectionFaite, detection, detecter, rafraichirPresence])

  const isHandsFree = (n: string): boolean => /hands-free|mains libres/i.test(n)
  const wakeAffiche = wake.trim() || WAKE_DEFAUT

  const validerCompte = async (): Promise<void> => {
    setCompteErreur(null)
    setCompteOccupe(true)
    try {
      if (compte?.configure) {
        await api.post('/api/compte/connexion', { mot_de_passe: mdp })
      } else {
        if (mdp.trim().length < 8) throw new Error('Le mot de passe doit faire au moins 8 caractères.')
        if (mdp !== mdp2) throw new Error('Les deux mots de passe ne sont pas identiques.')
        await api.post('/api/compte', { nouveau: mdp, nom: name })
        // Le courriel d'achat suffit à activer l'abonnement : aucune clé à recopier.
        if (email.trim()) await updateSettings({ licence_email: email.trim(), licence_auto: true })
      }
      setMdp('')
      setMdp2('')
      if (seulementCompte) {
        setComptePose(true)
        toast('Votre compte est en place.', 'success')
        return
      }
      setStep(2)
    } catch (err) {
      setCompteErreur(String((err as Error).message))
    } finally {
      setCompteOccupe(false)
    }
  }

  const finish = async (): Promise<void> => {
    try {
      await updateSettings({ onboarded: true, user_name: name, wake_word: wake })
      toast(`IRIS est prête. Dites « ${wake} » pour commencer.`, 'success')
    } catch (err) {
      // Sans ce filet, un backend momentanément indisponible laissait l'accueil ouvert, sans
      // message : l'utilisateur recliquait sans comprendre. onboarded reste false -> re-clic possible.
      toast((err as Error).message, 'error')
    }
  }

  const telechargerModele = (): void => {
    setDownloading(true)
    api.post('/api/voice/model/download', {}).catch((err: unknown) => {
      // 409 : un téléchargement est déjà en route — ce n'est pas une erreur, on le laisse finir.
      if (err instanceof ApiError && err.status === 409) {
        toast('Le téléchargement est déjà en cours.', 'info')
        return
      }
      setDownloading(false)
      toast(String((err as Error).message), 'error')
    })
  }

  const changerPeripherique = (patch: Record<string, string>): void => {
    api.patch('/api/glasses/prefs', patch).catch((err: Error) => toast(err.message, 'error'))
  }

  if (seulementCompte && (comptePose || compte === null || compte.configure)) return null

  const titres = ['Bienvenue', compte?.configure ? 'Connectez-vous' : 'Votre compte', 'Vos lunettes', 'Consentement', 'Audio', 'Mot d’activation']
  const acheterUrl: string = presence?.acheter_url || URL_ACHAT_DEFAUT
  const apercuTotal: number = presence?.apercu_total ?? 10
  const parTelephone = Boolean(presence?.presentes && presence.source === 'telephone')
  const lunettesPretes = lunettesConnectees || parTelephone
  const nomLunettes: string = lunettes?.device?.name || lunettes?.remembered?.name || presence?.nom || 'Lunettes VELA'
  const modeleTaille: number | undefined = typeof voice?.model_info?.size_mb === 'number' ? voice.model_info.size_mb : undefined
  const pourcentage = avancement && avancement.total > 0 ? Math.min(100, Math.round((avancement.done / avancement.total) * 100)) : null

  /* ------------------------------------------------------------ pied : Précédent / Continuer */
  const pied = (precedent: (() => void) | null, principal: React.ReactNode): JSX.Element => (
    <div style={{ padding: '8px 16px 24px', marginTop: 'auto' }}>
      <div className="row" style={{ gap: 8 }}>
        {precedent ? (
          <button type="button" className="btn ghost" style={{ flex: 'none', height: 54, padding: '0 20px', fontSize: 16 }} onClick={precedent}>Précédent</button>
        ) : null}
        {principal}
      </div>
    </div>
  )

  return (
    <div className="overlay" style={{ padding: 0, alignItems: 'stretch', backdropFilter: 'none', background: 'var(--bg)' }}>
      <div className="ecran">
        <TopBar titre={titres[step]} retour={false} />
        <div className="contenu">
          {!seulementCompte ? (
            <div
              className="steps"
              role="progressbar"
              aria-valuemin={1}
              aria-valuemax={ETAPES.length}
              aria-valuenow={step + 1}
              aria-valuetext={`Étape ${step + 1} sur ${ETAPES.length} : ${ETAPES[step]}`}
            >
              {ETAPES.map((s, i) => <span key={s} className={i <= step ? 'done' : ''} title={s} />)}
            </div>
          ) : null}

          {/* ---------------------------------------------------------- 0 · Bienvenue */}
          {step === 0 ? (
            <>
              <div className="intro">
                <IcoRobotDegrade className="robot" />
                <h1>Bienvenue dans IRIS</h1>
                <p className="sous">La technologie de vos lunettes VELA, qui travaille sur votre ordinateur.</p>
                <p className="consigne">Dites « {wakeAffiche} » pour la réveiller et posez directement votre demande.</p>
              </div>
              <div className="carte">
                {/* Première phrase du produit : bénéfice concret, aucun jargon, promesse vérifiable (cf. docs/DIFFERENCIATION.md §3.A). */}
                <p className="desc" style={{ marginBottom: 10 }}>
                  IRIS agit sur votre ordinateur quand vous le lui demandez, retient ce que vous avez réellement dit, et vous laisse <strong style={{ color: 'var(--text)' }}>vérifier vous-même</strong> ce qu’elle a capté et ce qu’elle a envoyé. Rien ne sort de cet ordinateur sans votre accord.
                </p>
                {/* Triade de marque conservée, dans sa forme en français clair du README. */}
                <p className="small muted" style={{ marginBottom: 16 }}><strong>Vois. Souviens-toi. Fais.</strong></p>
                <Field label="Comment devons-nous vous appeler ?">
                  <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Votre prénom" autoFocus />
                </Field>
              </div>
            </>
          ) : null}

          {/* ---------------------------------------------------------- 1 · Compte */}
          {/* Tant que GET /api/compte n'a pas répondu, on ne sait pas s'il faut créer ou déverrouiller :
              on attend plutôt que d'afficher un formulaire de création qui disparaîtrait sous les doigts. */}
          {step === 1 && compte === null ? (
            <div className="carte">
              <p className="desc">Vérification du compte…</p>
            </div>
          ) : null}
          {step === 1 && compte !== null ? (
            <div className="carte">
              <h3>{compte?.configure ? 'Connectez-vous' : 'Votre compte'}</h3>
              {compte?.configure ? (
                <p className="desc" style={{ marginBottom: 14 }}>
                  Un compte existe déjà sur cet ordinateur{compte.nom ? ` — ${compte.nom}` : ''}. Entrez son mot de passe pour reprendre la main.
                </p>
              ) : (
                <p className="desc" style={{ marginBottom: 14 }}>
                  IRIS ouvre vos applications, tape à votre place et lit votre écran. Ce mot de passe est ce qui protège cet accès quand vous la joignez depuis votre téléphone : sans lui, connaître l’adresse suffirait. Il ne quitte jamais cet ordinateur et n’y est jamais écrit en clair.
                </p>
              )}
              {!compte?.configure ? (
                <Field label="Courriel (facultatif)" hint="Celui de votre achat VELA. Votre abonnement s’activera tout seul, sans clé à recopier.">
                  <input className="input" type="email" autoComplete="email" placeholder="vous@exemple.com" value={email} onChange={(e) => setEmail(e.target.value)} />
                </Field>
              ) : null}
              <div style={{ marginTop: compte?.configure ? 0 : 12 }}>
                <Field label="Mot de passe">
                  <input
                    className="input"
                    type="password"
                    autoComplete={compte?.configure ? 'current-password' : 'new-password'}
                    placeholder={compte?.configure ? '' : '8 caractères au minimum'}
                    value={mdp}
                    autoFocus
                    onChange={(e) => setMdp(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && compte?.configure) void validerCompte()
                    }}
                  />
                </Field>
              </div>
              {!compte?.configure ? (
                <div style={{ marginTop: 12 }}>
                  <Field label="Répétez-le">
                    <input
                      className="input"
                      type="password"
                      autoComplete="new-password"
                      value={mdp2}
                      onChange={(e) => setMdp2(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') void validerCompte()
                      }}
                    />
                  </Field>
                </div>
              ) : null}
              {compteErreur ? <p className="small" style={{ color: 'var(--red)', marginTop: 10 }}>{compteErreur}</p> : null}
              {compte?.configure ? (
                <p className="small muted" style={{ marginTop: 14 }}>
                  Oublié ? Il n’est stocké nulle part, donc introuvable. Supprimez <span className="mono">compte.json</span> dans le dossier de données d’IRIS pour repartir de zéro : cela déconnecte aussi tous vos téléphones.
                </p>
              ) : null}
            </div>
          ) : null}

          {/* ---------------------------------------------------------- 2 · Lunettes */}
          {step === 2 ? (
            <>
              <div className="intro" style={{ padding: '0 0 4px' }}>
                <LunettesFace style={{ width: 240, maxWidth: '70%', marginTop: 20 }} />
                <h1 style={{ fontSize: 28 }}>Vos lunettes VELA</h1>
                <p className="sous">
                  IRIS est la technologie de vos lunettes : la voix, la vision, l’écoute et les fonctions qui agissent demandent qu’elles soient présentes.
                </p>
              </div>

              {lunettesConnectees ? (
                <div className="carte" role="status">
                  <h3>Lunettes connectées</h3>
                  <p className="desc">{nomLunettes} · vous les retrouverez dans Mon profil › Mes lunettes.</p>
                </div>
              ) : parTelephone ? (
                <div className="carte" role="status">
                  <h3>Lunettes signalées par votre téléphone</h3>
                  <p className="desc">{nomLunettes} : l’app IRIS de votre téléphone indique qu’elles lui sont connectées.</p>
                </div>
              ) : (
                <div className="carte col" style={{ gap: 12 }}>
                  <h3 style={{ margin: 0 }}>Connecter vos lunettes</h3>
                  <p className="desc">
                    Allumez-les et gardez-les près de l’ordinateur. Les appareils déjà appairés dans Windows apparaissent même s’ils n’émettent pas.
                  </p>
                  <Holo variante="sombre" disabled={detection || connexionA !== null} onClick={() => void detecter()}>
                    {detection ? 'Recherche… (6 s)' : 'Détecter les lunettes'}
                  </Holo>
                  {lunettes?.error ? <span className="pill err" style={{ alignSelf: 'flex-start', whiteSpace: 'normal' }}>{String(lunettes.error)}</span> : null}
                  {appareils.map((a) => (
                    <div className="row" key={a.address} style={{ alignItems: 'center', gap: 12, padding: '8px 0', borderTop: '1px solid var(--line)' }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="row wrap" style={{ gap: 8 }}>
                          <span style={{ fontWeight: 700, fontSize: 17 }}>{a.name}</span>
                          {a.likely_glasses ? <span className="pill ok">lunettes ?</span> : null}
                          {a.paired ? <span className="pill">appairé Windows</span> : null}
                        </div>
                        <div className="small muted mono" style={{ marginTop: 3 }}>{a.address}</div>
                      </div>
                      <button type="button" className="btn primary sm" disabled={connexionA !== null || detection} onClick={() => void connecter(a)}>
                        {connexionA === a.address
                          ? tentative
                            ? `Connexion… tentative ${tentative.attempt}/${tentative.attempts}`
                            : 'Connexion… (jusqu’à 90 s)'
                          : 'Connecter'}
                      </button>
                    </div>
                  ))}
                  {detectionFaite && !detection && appareils.length === 0 ? (
                    <p className="small muted" style={{ lineHeight: 1.45 }}>
                      Aucun appareil détecté. Allumez les lunettes, rapprochez-les de l’ordinateur, puis relancez la détection.
                    </p>
                  ) : null}
                </div>
              )}

              {pasEncore && !lunettesPretes ? (
                <div className="carte douce col" style={{ gap: 10 }} role="status">
                  <h3 style={{ margin: 0 }}>Sans lunettes pour l’instant</h3>
                  <p className="desc">
                    Vous pouvez découvrir IRIS par écrit : un aperçu de {apercuTotal} messages dans l’onglet IA. La voix, la vision, l’écoute et les
                    enregistrements attendront vos lunettes.
                  </p>
                  <p className="small muted" style={{ lineHeight: 1.45 }}>
                    Vos données, vos réglages, la confidentialité et le verrouillage à distance restent accessibles sans lunettes. Vous pourrez les connecter à tout
                    moment depuis l’accueil.
                  </p>
                  <Holo variante="contour" taille="petit" onClick={() => window.iris.openExternal(acheterUrl)}>
                    Découvrir les lunettes VELA
                  </Holo>
                </div>
              ) : null}
            </>
          ) : null}

          {/* ---------------------------------------------------------- 3 · Consentement */}
          {step === 3 ? (
            <>
              <div className="carte douce">
                <h3>Ce qui peut quitter votre ordinateur</h3>
                <p className="desc">
                  Par défaut, rien n’est envoyé. Pour qu’une IA externe réponde, elle doit recevoir le texte de vos demandes. Vous décidez, type par type, et pouvez changer d’avis à tout moment.
                </p>
              </div>
              {Object.entries(consent).map(([k, c]) => (
                <CarteReglage
                  key={k}
                  titre={String(c?.label || k)}
                  desc={c?.description ? String(c.description) : undefined}
                  on={Boolean(c?.granted)}
                  onChange={(v) => setConsent(k, v).catch((err: Error) => toast(err.message, 'error'))}
                />
              ))}
              {Object.keys(consent).length === 0 ? <p className="small muted">Aucun type de donnée à autoriser pour l’instant.</p> : null}
            </>
          ) : null}

          {/* ---------------------------------------------------------- 4 · Audio */}
          {step === 4 ? (
            <div className="carte">
              <h3>Micro et sortie audio</h3>
              <p className="desc" style={{ marginBottom: 14 }}>
                Choisissez comment IRIS vous entend et où elle parle. Le micro « Hands-Free » d’un casque ou de lunettes Bluetooth est en qualité téléphone (8 kHz) : la reconnaissance y est bien moins fiable que sur le micro de l’ordinateur.
              </p>
              <Field label="Micro">
                <select className="select" value={settings?.audio_input_device || ''} onChange={(e) => changerPeripherique({ audio_input_device: e.target.value })}>
                  <option value="">Micro par défaut de l’ordinateur (recommandé)</option>
                  {devices.devices.map((d) => (
                    <option key={d} value={d}>{d}{isHandsFree(d) ? ' — qualité téléphone' : ''}</option>
                  ))}
                </select>
              </Field>
              <div style={{ marginTop: 12 }}>
                <Field label="Sortie audio (voix d’IRIS)">
                  <select className="select" value={settings?.audio_output_device || ''} onChange={(e) => changerPeripherique({ audio_output_device: e.target.value })}>
                    <option value="">Sortie par défaut du système</option>
                    {devices.outputs.map((d) => <option key={d} value={d}>{d}</option>)}
                  </select>
                </Field>
              </div>
              <p className="small muted" style={{ marginTop: 12 }}>
                Conseil lunettes VELA : gardez le micro du PC et choisissez la sortie « Stereo » des lunettes pour entendre IRIS dedans. Modifiable à tout moment dans « Mes lunettes ».
              </p>
            </div>
          ) : null}

          {/* ---------------------------------------------------------- 5 · Voix */}
          {step === 5 ? (
            <>
              {/* IMG_0710 : robot, « Essayez de dire : » et la phrase d'exemple en grand, alignées à gauche. */}
              <div className="intro" style={{ padding: '0 0 8px' }}>
                <IcoRobotDegrade className="robot" />
                <div className="bloc">
                  <p style={{ fontSize: 22, fontWeight: 600, margin: '0 0 14px' }}>Essayez de dire :</p>
                  <h2 style={{ fontSize: 26, fontWeight: 600, lineHeight: 1.3 }}>« {wakeAffiche}, quel temps fait-il aujourd’hui ? »</h2>
                </div>
              </div>
              <div className="reveil">
                <div className="rond"><IcoMicro /></div>
                <div className="corps">
                  <h3>Réveil vocal</h3>
                  <p>Dites « {wakeAffiche} » pour réveiller l’assistante</p>
                  <div style={{ marginTop: 14 }}>
                    <Field
                      label="Votre mot d’activation"
                      hint={`Autre exemple : « ${wakeAffiche}, ouvre mon navigateur et mets de la musique ». Le temps de chaque réponse est mesuré et affiché dans l’onglet IA ; il dépend de la demande et du réseau. IRIS vous pose une question si elle a besoin d’une précision.`}
                    >
                      <input className="input" value={wake} onChange={(e) => setWake(e.target.value)} placeholder={WAKE_DEFAUT} />
                    </Field>
                  </div>
                </div>
              </div>
              <div className="carte reglage">
                <div className="corps">
                  <h3>Reconnaissance vocale hors-ligne</h3>
                  <div className="desc">
                    {voice?.model_ready
                      ? 'Installée : la reconnaissance vocale peut se faire sur l’appareil, sans envoi.'
                      : `IRIS l’installe elle-même${modeleTaille ? ` (${modeleTaille} Mo)` : ''}. Vous pouvez continuer, elle vous préviendra.`}
                  </div>
                  {!voice?.model_ready && downloading ? (
                    <div style={{ marginTop: 10 }}>
                      <div className={`progress ${pourcentage === null ? 'indet' : ''}`}>
                        <div style={pourcentage !== null ? { width: `${pourcentage}%` } : undefined} />
                      </div>
                      <div className="small muted" style={{ marginTop: 6 }}>{pourcentage !== null ? `${pourcentage} %` : 'Téléchargement en cours…'}</div>
                    </div>
                  ) : null}
                </div>
                {voice?.model_ready ? (
                  <span className="pill ok">installé</span>
                ) : (
                  <button type="button" className="btn sm" disabled={downloading} onClick={telechargerModele}>
                    {downloading ? 'En cours…' : 'Relancer'}
                  </button>
                )}
              </div>
            </>
          ) : null}
        </div>

        {/* ------------------------------------------------------------ pied de page */}
        {step === 0 ? pied(null, <Holo style={{ flex: 1 }} onClick={() => setStep(1)}>Continuer</Holo>) : null}
        {step === 1
          ? pied(
              seulementCompte ? null : () => setStep(0),
              <Holo style={{ flex: 1 }} disabled={compte === null || compteOccupe || !mdp.trim()} onClick={() => void validerCompte()}>
                {compteOccupe ? 'Un instant…' : compte?.configure ? 'Se connecter' : 'Créer mon compte'}
              </Holo>
            )
          : null}
        {step === 2 ? pied(
              () => setStep(1),
              lunettesPretes ? (
                <Holo style={{ flex: 1 }} onClick={() => setStep(3)}>Continuer</Holo>
              ) : pasEncore ? (
                <Holo style={{ flex: 1 }} disabled={connexionA !== null} onClick={() => setStep(3)}>Continuer avec l’aperçu</Holo>
              ) : (
                <Holo variante="contour" style={{ flex: 1 }} disabled={connexionA !== null} onClick={() => setPasEncore(true)}>Je n’ai pas encore mes lunettes</Holo>
              )
            ) : null}
        {step === 3 ? pied(() => setStep(2), <Holo style={{ flex: 1 }} onClick={() => setStep(4)}>Continuer</Holo>) : null}
        {step === 4 ? pied(() => setStep(3), <Holo style={{ flex: 1 }} onClick={() => setStep(5)}>Continuer</Holo>) : null}
        {step === 5 ? pied(() => setStep(4), <Holo variante="blanc" style={{ flex: 1 }} onClick={() => void finish()}>Terminer</Holo>) : null}
      </div>
    </div>
  )
}
