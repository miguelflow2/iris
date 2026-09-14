import React, { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Holo, Modal } from '../components/ui'
import { IcoBatterie, IcoCamera, IcoChevronBas, IcoImageIA, IcoMicro, IcoMusique, IcoPlateforme, IcoStop, IcoVideo, Vague } from '../components/icons'
import { LogoLunettes, LunettesFace } from '../components/Lunettes'
import { CosmosFond } from '../components/Cosmos'
import { api, ApiError, estLunettesRequises, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   Accueil (racine de l'onglet « Accueil »).
   - Sans lunettes connectées : le héros « cosmos » avec le logo, le bouton de connexion,
     « Acheter les lunettes » et un lien discret vers l'Accessibilité (qui reste consultable
     sans lunettes : ses réglages et ses limites s'y lisent).
   - Lunettes connectées : la carte de l'appareil, les fonctions rapides, la reconnaissance
     d'images, les cartes de configuration et les cartes de fonctions.

   Lunettes d'abord : chaque tuile qui capte ou agit passe d'abord par exigerLunettes(). Sans
   lunettes présentes, la feuille « Cette fonction marche avec les lunettes VELA » s'ouvre au
   lieu d'appeler le service ; un refus 428 du service ouvre la même feuille (App.tsx), on ne
   le double donc pas d'un toast.

   Rien n'est simulé : la vidéo est enregistrée par les lunettes elles-mêmes et IRIS ne sait
   pas la récupérer ; la tuile le dit au lieu de faire semblant.
   ========================================================================= */

const URL_ACHAT_DEFAUT = 'https://velaglass.ca/lunettes.html'

/** Nom de fichier à partir d'un chemin local (Windows ou POSIX). */
function nomDeFichier(chemin: string): string {
  const parties = chemin.split(/[\\/]/)
  return parties[parties.length - 1] || chemin
}

/** Blob → base64 sans le préfixe « data:…;base64, ». */
function blobVersBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const lecteur = new FileReader()
    lecteur.onerror = () => reject(lecteur.error || new Error('Lecture de la photo impossible.'))
    lecteur.onload = () => {
      const s = String(lecteur.result || '')
      const i = s.indexOf(',')
      resolve(i >= 0 ? s.slice(i + 1) : s)
    }
    lecteur.readAsDataURL(blob)
  })
}

function messageErreur(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

/** Durée d'enregistrement lisible sur une tuile : « 0:42 », « 12:05 », « 1:02:33 ». */
function chrono(secondes: number): string {
  const s = Math.max(0, Math.floor(secondes))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = String(s % 60).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${r}` : `${m}:${r}`
}

/** Durée dite en toutes lettres dans un message : « 42 s », « 3 min 05 s ». */
function dureeLisible(secondes: number): string {
  const s = Math.max(0, Math.round(secondes))
  if (s < 60) return `${s} s`
  const m = Math.floor(s / 60)
  return `${m} min ${String(s % 60).padStart(2, '0')} s`
}

function taille(octets: number): string {
  if (octets >= 1024 * 1024) return `${(octets / (1024 * 1024)).toFixed(1).replace('.', ',')} Mo`
  return `${Math.max(1, Math.round(octets / 1024))} Ko`
}

type Glyphe = 'oeil' | 'bulles' | 'livre' | 'partage'

/** Même plateforme isométrique que IcoPlateforme (cartes de l'accueil), avec le glyphe des nouvelles
 *  fonctions. IcoPlateforme n'offre que trois glyphes (orbe, nuage, baguette) : le socle est repris
 *  à l'identique ici pour que les sept cartes se ressemblent. */
function PlateformeFonction({ glyphe, className }: { glyphe: Glyphe; className?: string }): JSX.Element {
  const id = useId()
  const lumiere = `url(#${id}c)`
  return (
    <svg viewBox="0 0 130 110" width={130} height={110} aria-hidden="true" className={className}>
      <defs>
        <linearGradient id={`${id}a`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#5b7cff" />
          <stop offset="1" stopColor="#2a45b8" />
        </linearGradient>
        <linearGradient id={`${id}b`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#3b56d6" />
          <stop offset="1" stopColor="#1e2f80" />
        </linearGradient>
        <radialGradient id={`${id}c`} cx="0.4" cy="0.35" r="0.7">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="0.5" stopColor="#bfd4ff" />
          <stop offset="1" stopColor="#6f8cff" />
        </radialGradient>
      </defs>
      <path d="M65 58 118 80 65 102 12 80Z" fill={`url(#${id}a)`} />
      <path d="M12 80v8l53 22v-8Z" fill={`url(#${id}b)`} />
      <path d="M118 80v8l-53 22v-8Z" fill="#1a2a70" />
      <path d="M65 66 98 80 65 94 32 80Z" fill="#1c2f8a" opacity="0.8" />
      {glyphe === 'oeil' ? (
        <>
          <path d="M34 48s12-20 31-20 31 20 31 20-12 20-31 20-31-20-31-20Z" fill={lumiere} />
          <circle cx="65" cy="48" r="10" fill="#2a3a90" />
          <circle cx="61" cy="44" r="3" fill="#fff" opacity="0.9" />
          <circle cx="98" cy="20" r="2" fill="#fff" />
        </>
      ) : null}
      {glyphe === 'bulles' ? (
        <>
          <path d="M30 22h32a7 7 0 0 1 7 7v14a7 7 0 0 1-7 7H47l-9 8v-8h-8a7 7 0 0 1-7-7V29a7 7 0 0 1 7-7Z" fill={lumiere} />
          <path d="M68 38h30a7 7 0 0 1 7 7v13a7 7 0 0 1-7 7h-6v8l-9-8H68a7 7 0 0 1-7-7V45a7 7 0 0 1 7-7Z" fill="#8fb0ff" />
          <path d="M36 33h20M36 40h13M74 49h18M74 56h11" stroke="#2a3a90" strokeWidth="3" strokeLinecap="round" />
        </>
      ) : null}
      {glyphe === 'livre' ? (
        <>
          <path d="M65 34c-10-7-23-8-33-5v34c10-3 23-2 33 5Z" fill={lumiere} />
          <path d="M65 34c10-7 23-8 33-5v34c-10-3-23-2-33 5Z" fill="#8fb0ff" />
          <path d="M65 34v34" stroke="#2a3a90" strokeWidth="2.5" />
          <path d="M84 16v10M79 21h10" stroke="#fff" strokeWidth="3" strokeLinecap="round" />
        </>
      ) : null}
      {glyphe === 'partage' ? (
        <>
          <rect x="53" y="20" width="24" height="44" rx="6" fill={lumiere} />
          <circle cx="65" cy="36" r="6" fill="#2a3a90" />
          <path d="M84 30a14 14 0 0 1 0 20M91 24a24 24 0 0 1 0 32" stroke="#fff" strokeWidth="3" strokeLinecap="round" fill="none" />
          <path d="M46 30a14 14 0 0 0 0 20M39 24a24 24 0 0 0 0 32" stroke="#8fb0ff" strokeWidth="3" strokeLinecap="round" fill="none" />
        </>
      ) : null}
    </svg>
  )
}

export function AccueilScreen(): JSX.Element {
  const { nav, settings, lunettes, rafraichirLunettes, toast, presence, exigerLunettes, ecoute, rafraichirEcoute } = useStore()
  const [reconnexion, setReconnexion] = useState(false)
  const [prise, setPrise] = useState(false)
  const [analyse, setAnalyse] = useState(false)
  const [mesure, setMesure] = useState(false)
  const [enregOccupe, setEnregOccupe] = useState(false)
  const [videoExpliquee, setVideoExpliquee] = useState(false)
  // Tentative de connexion en cours (le service réessaie jusqu'à 3 × 30 s) : affichée sur le bouton.
  const [tentative, setTentative] = useState<{ attempt: number; attempts: number } | null>(null)
  // Vrai pendant qu'une photo est déclenchée depuis cet écran : l'événement glasses.photo qui
  // suit ne doit pas produire un second toast (celui du bouton suffit).
  const photoLocale = useRef(false)
  const monte = useRef(true)

  useEffect(() => {
    monte.current = true
    rafraichirLunettes().catch(() => undefined)
    const off = api.on((e: IrisEvent) => {
      if (!e.type.startsWith('glasses.')) return
      if (e.type === 'glasses.photo') {
        // Photo prise depuis la voix (« Dis-moi Iris, prends une photo ») ou depuis un autre écran.
        if (!photoLocale.current) toast('Photo enregistrée dans l’album.', 'success')
        return
      }
      if (e.type === 'glasses.connecting') setTentative({ attempt: Number(e.attempt) || 1, attempts: Number(e.attempts) || 3 })
      else if (e.type === 'glasses.connected' || e.type === 'glasses.disconnected') setTentative(null)
      // Échec après toutes les tentatives : le service ne publie que glasses.state (connecting: false).
      else if (e.type === 'glasses.state' && !e.connecting) setTentative(null)
      // glasses.state / connected / disconnected / connecting / packet : on relit l'état complet.
      if (e.type !== 'glasses.packet') rafraichirLunettes().catch(() => undefined)
    })
    return () => {
      monte.current = false
      off()
    }
  }, [rafraichirLunettes, toast])

  const connected = Boolean(lunettes?.connected)
  const connecting = Boolean(lunettes?.connecting)
  const remembered = lunettes?.remembered
  const device = lunettes?.device
  const battery: number | null = typeof lunettes?.battery === 'number' ? lunettes.battery : null
  const wake: string = settings?.wake_word || 'Dis-moi Iris'
  const nomAppareil: string = device?.name || device?.address || remembered?.name || 'Lunettes VELA'
  const acheterUrl: string = presence?.acheter_url || URL_ACHAT_DEFAUT

  /* ---------------------------------------------------------------- enregistrement audio : état et chrono */
  // La vérité vient du service (ecoute.etat) : un enregistrement lancé à la voix, arrêté par la durée
  // maximale ou par le mode confidentiel se voit ici aussi. `debutLocal` couvre les quelques
  // millisecondes entre la réponse du démarrage et l'arrivée de l'événement.
  const enregService = ecoute?.enregistrement
  const [debutLocal, setDebutLocal] = useState<number | null>(null)
  const [baseService, setBaseService] = useState<number | null>(null)
  const [, setTic] = useState(0)
  const actifService = Boolean(enregService?.actif)
  const secondesService = Number(enregService?.secondes) || 0
  useEffect(() => {
    if (actifService) {
      setBaseService(Date.now() - secondesService * 1000)
      setDebutLocal(null)
    } else {
      setBaseService(null)
    }
  }, [actifService, secondesService, enregService?.nom])
  const enregistre = actifService || debutLocal !== null
  useEffect(() => {
    if (!enregistre) return
    const t = window.setInterval(() => setTic((x) => x + 1), 1000)
    return () => window.clearInterval(t)
  }, [enregistre])
  const baseChrono = baseService ?? debutLocal
  const secondesEcoulees = baseChrono !== null ? (Date.now() - baseChrono) / 1000 : 0

  const basculerEnregistrement = useCallback(async () => {
    if (enregOccupe) return
    if (!enregistre && !exigerLunettes('Enregistrer l’audio')) return
    setEnregOccupe(true)
    try {
      if (!enregistre) {
        await api.post('/api/ecoute/enregistrement/demarrer')
        if (monte.current) setDebutLocal(Date.now())
        toast('Enregistrement en cours : le son est gardé sur cet ordinateur jusqu’à l’arrêt.', 'info')
      } else {
        const r = await api.post('/api/ecoute/enregistrement/arreter')
        if (monte.current) setDebutLocal(null)
        const duree = typeof r?.secondes === 'number' ? dureeLisible(r.secondes) : ''
        const poids = typeof r?.octets === 'number' ? taille(r.octets) : ''
        toast(`Enregistrement gardé dans l’album${duree ? ` : ${duree}` : ''}${poids ? `, ${poids}` : ''}. Stocké sur cet ordinateur.`, 'success')
      }
    } catch (err) {
      if (!estLunettesRequises(err)) {
        // 409 = empêchement expliqué par le service (micro coupé, mémoire suspendue, disque plein…).
        const statut = err instanceof ApiError ? err.status : 0
        toast(messageErreur(err), statut === 409 ? 'info' : 'error')
      }
      // « Aucun enregistrement en cours » : l'état local était périmé, on le réaligne.
      if (enregistre && monte.current) setDebutLocal(null)
    } finally {
      rafraichirEcoute().catch(() => undefined)
      if (monte.current) setEnregOccupe(false)
    }
  }, [enregOccupe, enregistre, exigerLunettes, rafraichirEcoute, toast])

  /* ---------------------------------------------------------------- reconnexion aux lunettes mémorisées */
  const reconnecter = useCallback(async () => {
    if (!remembered?.address) return
    setReconnexion(true)
    setTentative(null)
    try {
      // Le service tente jusqu'à 3 fois 30 s : l'appel peut durer jusqu'à 90 s.
      const r = await api.post('/api/glasses/connect', { address: remembered.address, name: remembered.name })
      await rafraichirLunettes()
      // Échec après les tentatives : le service répond 200 avec { connected: false, error } (pas d'exception).
      if (r && !r.connected && r.error) toast(String(r.error), 'error')
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) {
        setReconnexion(false)
        setTentative(null)
      }
    }
  }, [remembered?.address, remembered?.name, rafraichirLunettes, toast])

  /* ---------------------------------------------------------------- batterie (quand les lunettes ne l'ont pas encore annoncée) */
  const mesurerBatterie = useCallback(async () => {
    setMesure(true)
    try {
      const r = await api.post('/api/glasses/battery')
      await rafraichirLunettes()
      if (typeof r?.battery !== 'number') toast('Niveau de batterie non communiqué par les lunettes.', 'info')
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setMesure(false)
    }
  }, [rafraichirLunettes, toast])

  /* ---------------------------------------------------------------- photo simple */
  const prendrePhoto = useCallback(async () => {
    if (!exigerLunettes('Prendre une photo')) return
    setPrise(true)
    photoLocale.current = true
    try {
      const r = await api.post('/api/glasses/photo', { reconnaissance: false })
      if (r.ok) toast('Photo enregistrée dans l’album.', 'success')
      // Trame envoyée mais image non reconstituée : constat honnête, pas un faux succès.
      else toast(r.constat || 'Aucune image reçue.', 'info')
    } catch (err) {
      if (!estLunettesRequises(err)) {
        // 409 = limite assumée (paire sans caméra, format de trame non confirmé) : note « info ».
        const statut = err instanceof ApiError ? err.status : 0
        toast(messageErreur(err), statut === 409 ? 'info' : 'error')
      }
    } finally {
      photoLocale.current = false
      if (monte.current) setPrise(false)
    }
  }, [exigerLunettes, toast])

  /* ---------------------------------------------------------------- reconnaissance d'images : photo → conversation IA */
  const reconnaitre = useCallback(async () => {
    if (!exigerLunettes('Reconnaissance d’images')) return
    setAnalyse(true)
    photoLocale.current = true
    try {
      const r = await api.post('/api/glasses/photo', { reconnaissance: true })
      if (!r.ok || !r.chemin) {
        toast(r.constat || 'Aucune image reçue.', 'info')
        return
      }
      const nom = nomDeFichier(String(r.chemin))
      const blob = await api.blob('/api/glasses/captures/' + encodeURIComponent(nom))
      const data = await blobVersBase64(blob)
      const conv = await api.post('/api/conversations', { agent: 'auto', title: "Reconnaissance d'images avec l'IA" })
      await api.post(`/api/conversations/${conv.id}/messages`, {
        text: 'Décris ce que tu vois sur cette photo.',
        images: [{ media_type: 'image/jpeg', data }],
        agent: 'auto'
      })
      try {
        window.sessionStorage.setItem('iris.ouvrirConversation', String(conv.id))
      } catch {
        /* stockage de session indisponible : l'onglet IA s'ouvrira sur sa dernière discussion */
      }
      nav.allerOnglet('ia')
    } catch (err) {
      if (!estLunettesRequises(err)) {
        const statut = err instanceof ApiError ? err.status : 0
        toast(messageErreur(err), statut === 409 ? 'info' : 'error')
      }
    } finally {
      photoLocale.current = false
      if (monte.current) setAnalyse(false)
    }
  }, [exigerLunettes, nav, toast])

  /* ================================================================ non connecté : héros cosmos */
  if (!connected) {
    const enCours = reconnexion || connecting
    const libelleConnexion = tentative ? `Connexion… tentative ${tentative.attempt}/${tentative.attempts}` : 'Connexion…'
    // Présence attestée par le téléphone appairé : les lunettes sont là, mais pas sur cet ordinateur.
    const parTelephone = presence?.presentes && presence.source === 'telephone'
    return (
      <div className="ecran avec-onglets">
        <div className="hero-cosmos">
          <CosmosFond className="fond" />
          <div className="marque">
            <LogoLunettes />
            <div className="nom">IRIS</div>
            <div className="par">par VELA</div>
          </div>
          <div className="bas">
            {parTelephone ? (
              <p className="small" style={{ textAlign: 'center', color: 'var(--text-2)', fontWeight: 600, margin: '0 0 12px', lineHeight: 1.4 }}>
                Vos lunettes{presence?.nom ? ` (${presence.nom})` : ''} sont connectées à votre téléphone : les fonctions qui les exigent sont permises.
              </p>
            ) : null}
            {remembered?.address ? (
              <div className="col" style={{ gap: 12 }}>
                <Holo disabled={enCours} onClick={reconnecter}>
                  {enCours ? libelleConnexion : `Reconnecter ${remembered.name || remembered.address}`}
                </Holo>
                <Holo variante="contour" disabled={enCours} onClick={() => nav.ouvrir('connecter')}>
                  Autre appareil
                </Holo>
              </div>
            ) : (
              <div className="col" style={{ gap: 12 }}>
                <Holo disabled={enCours} onClick={() => nav.ouvrir('connecter')}>
                  {enCours ? libelleConnexion : 'Connectez l’appareil'}
                </Holo>
                <Holo variante="contour" onClick={() => window.iris.openExternal(acheterUrl)}>
                  Acheter les lunettes
                </Holo>
              </div>
            )}
            <div className="row" style={{ justifyContent: 'center', gap: 4, marginTop: 10, flexWrap: 'wrap' }}>
              <button type="button" className="btn ghost sm" onClick={() => nav.ouvrir('accessibilite')}>
                Accessibilité
              </button>
              {remembered?.address ? (
                <button type="button" className="btn ghost sm" onClick={() => window.iris.openExternal(acheterUrl)}>
                  Acheter les lunettes
                </button>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    )
  }

  /* ================================================================ connecté */
  return (
    <div className="ecran avec-onglets">
      <div className="contenu">
        {/* 1) carte de l'appareil.
            Pourcentage connu : un simple <button>. Pourcentage inconnu : la carte devient un <div role="button">
            pour pouvoir contenir un vrai bouton « Mesurer » (un <button> ne peut pas en imbriquer un autre). */}
        {battery !== null ? (
          <button type="button" className="carte-appareil" onClick={() => nav.ouvrir('lunettes')}>
            <div>
              <div className="nom">{nomAppareil}</div>
              <div className="etat">
                <span className="point">Connecté</span>
                <span className="batterie">
                  <IcoBatterie niveau={battery} />
                  <span>{battery} %</span>
                </span>
              </div>
            </div>
            <LunettesFace className="photo" />
            <div className="deplier"><IcoChevronBas /></div>
          </button>
        ) : (
          <div
            className="carte-appareil"
            role="button"
            tabIndex={0}
            style={{ cursor: 'pointer' }}
            onClick={() => nav.ouvrir('lunettes')}
            onKeyDown={(e) => {
              // Seulement quand la carte elle-même a le focus : Entrée/Espace sur le bouton « Mesurer »
              // remontent ici aussi et ne doivent pas ouvrir l'écran.
              if (e.target !== e.currentTarget) return
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                nav.ouvrir('lunettes')
              }
            }}
          >
            <div>
              <div className="nom">{nomAppareil}</div>
              <div className="etat">
                <span className="point">Connecté</span>
                <span className="batterie">
                  <IcoBatterie niveau={null} />
                  <button
                    type="button"
                    className="btn sm"
                    disabled={mesure}
                    onClick={(e) => {
                      e.stopPropagation()
                      mesurerBatterie()
                    }}
                  >
                    {mesure ? 'Mesure…' : 'Mesurer'}
                  </button>
                </span>
              </div>
            </div>
            <LunettesFace className="photo" />
            <div className="deplier"><IcoChevronBas /></div>
          </div>
        )}

        {/* 2) fonctions rapides */}
        <h2 className="section-titre">Fonctions rapides</h2>
        <div className="tuiles-3">
          <button type="button" className="tuile" disabled={prise} onClick={prendrePhoto}>
            <IcoCamera />
            <span>{prise ? <>Prise<br />en cours…</> : <>Prendre<br />une photo</>}</span>
          </button>
          <button type="button" className="tuile" onClick={() => setVideoExpliquee(true)}>
            <IcoVideo />
            <span>Enregistrer<br />une vidéo</span>
          </button>
          <button
            type="button"
            className="tuile"
            disabled={enregOccupe}
            aria-pressed={enregistre}
            aria-label={enregistre ? `Arrêter l’enregistrement audio, en cours depuis ${dureeLisible(secondesEcoulees)}` : 'Enregistrer l’audio'}
            style={enregistre ? { boxShadow: 'inset 0 0 0 2px var(--red)' } : undefined}
            onClick={basculerEnregistrement}
          >
            {enregistre ? <IcoStop style={{ color: 'var(--red)' }} /> : <IcoMicro />}
            <span>
              {enregOccupe ? (
                enregistre ? <>Arrêt…</> : <>Démarrage…</>
              ) : enregistre ? (
                <>
                  <span className="mono" style={{ fontSize: 20 }}>{chrono(secondesEcoulees)}</span>
                  <br />Arrêter
                </>
              ) : (
                <>Enregistrer<br />l’audio</>
              )}
            </span>
          </button>
        </div>

        {/* 3) reconnaissance d'images */}
        <button type="button" className="tuile-large" disabled={analyse} onClick={reconnaitre}>
          <IcoImageIA />
          <span>{analyse ? 'Analyse…' : 'Reconnaissance d’images avec l’IA'}</span>
        </button>

        {/* 4) configuration des lunettes */}
        <h2 className="section-titre">Configuration des lunettes</h2>
        <div className="cartes-2">
          <button type="button" className="carte-config camera" onClick={() => nav.ouvrir('tuto-camera')}>
            <IcoCamera className="ico" />
            <Vague className="vague" />
            <h3>Apprenez à utiliser l’appareil photo</h3>
            <p>Conseils pour prendre des photos et enregistrer des vidéos</p>
          </button>
          <button type="button" className="carte-config touche" onClick={() => nav.ouvrir('tuto-touchpad')}>
            <IcoMusique className="ico" />
            <Vague className="vague" />
            <h3>Gestes de pavé tactile</h3>
            <p>Play/Pause, changer de chanson, régler le volume.</p>
          </button>
        </div>

        {/* 5) assistant vocal */}
        <button type="button" className="carte-fonction" onClick={() => nav.ouvrir('assistant-intro')}>
          <h3>Assistant vocal</h3>
          <p className="citation">{`« ${wake},\nrappelle-moi d’appeler Marc à 15 h »`}</p>
          <p>Dites le mot d’activation, puis votre demande. Le temps de chaque réponse est mesuré et affiché dans l’onglet IA.</p>
          <IcoPlateforme glyphe="orbe" className="illustration" />
        </button>

        {/* 6) traduction */}
        <button type="button" className="carte-fonction" onClick={() => nav.ouvrir('traduction')}>
          <h3>Traduction avec IA</h3>
          <p className="citation">{'Bonjour, quel est ton nom ?\nTraduction en cours…\nHello, what is your name?'}</p>
          <p>Traduire le texte de l’écran, interpréter une conversation phrase par phrase ou résumer une réunion.</p>
          <IcoPlateforme glyphe="nuage" className="illustration" />
        </button>

        {/* 7) lumière BD : calculée sur cet ordinateur (backend/iris/album.py) */}
        <button type="button" className="carte-fonction" onClick={() => nav.ouvrir('lumiere-bd')}>
          <h3>Lumière BD</h3>
          <p className="citation">Traits de BD doux pour les moments du quotidien</p>
          <p>Transforme une photo de l’album en image aux traits de BD, sur cet ordinateur. Le rendu dépend de la netteté de la photo.</p>
          <IcoPlateforme glyphe="baguette" className="illustration" />
        </button>

        {/* 8) les fonctions du chantier de lancement */}
        <h2 className="section-titre">Plus de fonctions</h2>
        <button type="button" className="carte-fonction" onClick={() => nav.ouvrir('accessibilite')}>
          <h3>Accessibilité</h3>
          <p className="citation">{'« Qu’est-ce qu’il y a devant moi ? »\n« Lis-moi ça »'}</p>
          <p>Décrire une scène, lire un texte, compter des billets ; sous-titres et alertes sonores. Une photo prend quelques secondes : ce n’est pas une alerte d’obstacle.</p>
          <PlateformeFonction glyphe="oeil" className="illustration" />
        </button>

        <button type="button" className="carte-fonction" onClick={() => nav.ouvrir('interprete')}>
          <h3>Mode interprète</h3>
          <p className="citation">{'Vous : « Où est la gare ? »\nL’autre : « Two blocks away. »'}</p>
          <p>Chacun parle sa langue ; IRIS traduit après chaque phrase, avec quelques secondes de délai, mesurées et affichées à chaque tour.</p>
          <PlateformeFonction glyphe="bulles" className="illustration" />
        </button>

        <button type="button" className="carte-fonction" onClick={() => nav.ouvrir('cours')}>
          <h3>Mode cours</h3>
          <p className="citation">{'Enregistrer · transcrire · réviser'}</p>
          <p>Transcription approximative faite sur cet ordinateur, puis fiches et questions de révision à vérifier avec vos notes.</p>
          <PlateformeFonction glyphe="livre" className="illustration" />
        </button>

        <button type="button" className="carte-fonction" onClick={() => nav.ouvrir('vision-partagee')}>
          <h3>Vision partagée</h3>
          <p className="citation">{'« Regarde ce que je vois »'}</p>
          <p>Un proche voit l’écran de l’ordinateur ou la caméra du téléphone par un lien temporaire, et vous écrit. Rien n’est conservé.</p>
          <PlateformeFonction glyphe="partage" className="illustration" />
        </button>
      </div>

      {videoExpliquee ? (
        <Modal
          title="Enregistrer une vidéo"
          onClose={() => setVideoExpliquee(false)}
          actions={<button type="button" className="btn primary" onClick={() => setVideoExpliquee(false)}>Compris</button>}
        >
          <p className="desc" style={{ lineHeight: 1.45 }}>
            La vidéo s’enregistre dans les lunettes elles-mêmes : deux clics sur le bouton avant pour démarrer, un clic pour terminer (voir « Apprenez à
            utiliser l’appareil photo »).
          </p>
          <p className="small muted" style={{ lineHeight: 1.45 }}>
            IRIS ne sait pas récupérer ces vidéos sur cet ordinateur : le fabricant ne documente pas ce transfert. Elles ne figurent donc pas dans l’album
            d’IRIS.
          </p>
        </Modal>
      ) : null}
    </div>
  )
}
