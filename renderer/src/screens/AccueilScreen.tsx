import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Holo } from '../components/ui'
import { IcoBatterie, IcoCamera, IcoChevronBas, IcoImageIA, IcoMicro, IcoMusique, IcoPlateforme, IcoVideo, Vague } from '../components/icons'
import { LogoLunettes, LunettesFace } from '../components/Lunettes'
import { CosmosFond } from '../components/Cosmos'
import { api, ApiError, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   Accueil (racine de l'onglet « Accueil »).
   - Sans lunettes connectées : le héros « cosmos » avec le logo et le bouton de connexion.
   - Lunettes connectées : la carte de l'appareil, les fonctions rapides, la reconnaissance
     d'images, les cartes de configuration et les trois cartes de fonctions.
   Tout ce qui n'a pas encore de support côté service le dit franchement (toast « Pas encore
   disponible »), rien n'est simulé.
   ========================================================================= */

const PAS_DISPONIBLE = 'Pas encore disponible dans cette version.'

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

export function AccueilScreen(): JSX.Element {
  const { nav, settings, lunettes, rafraichirLunettes, toast } = useStore()
  const [reconnexion, setReconnexion] = useState(false)
  const [prise, setPrise] = useState(false)
  const [analyse, setAnalyse] = useState(false)
  const [mesure, setMesure] = useState(false)
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
    setPrise(true)
    photoLocale.current = true
    try {
      const r = await api.post('/api/glasses/photo', { reconnaissance: false })
      if (r.ok) toast('Photo enregistrée dans l’album.', 'success')
      // Trame envoyée mais image non reconstituée : constat honnête, pas un faux succès.
      else toast(r.constat || 'Aucune image reçue.', 'info')
    } catch (err) {
      // 409 = limite assumée (paire sans caméra, format de trame non confirmé) : note « info ».
      const statut = err instanceof ApiError ? err.status : 0
      toast(messageErreur(err), statut === 409 ? 'info' : 'error')
    } finally {
      photoLocale.current = false
      if (monte.current) setPrise(false)
    }
  }, [toast])

  /* ---------------------------------------------------------------- reconnaissance d'images : photo → conversation IA */
  const reconnaitre = useCallback(async () => {
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
      const statut = err instanceof ApiError ? err.status : 0
      toast(messageErreur(err), statut === 409 ? 'info' : 'error')
    } finally {
      photoLocale.current = false
      if (monte.current) setAnalyse(false)
    }
  }, [nav, toast])

  /* ================================================================ non connecté : héros cosmos */
  if (!connected) {
    const enCours = reconnexion || connecting
    const libelleConnexion = tentative ? `Connexion… tentative ${tentative.attempt}/${tentative.attempts}` : 'Connexion…'
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
              <Holo disabled={enCours} onClick={() => nav.ouvrir('connecter')}>
                {enCours ? libelleConnexion : 'Connectez l’appareil'}
              </Holo>
            )}
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
          <button type="button" className="tuile" onClick={() => toast(PAS_DISPONIBLE, 'info')}>
            <IcoVideo />
            <span>Enregistrer<br />une vidéo</span>
          </button>
          <button type="button" className="tuile" onClick={() => toast(PAS_DISPONIBLE, 'info')}>
            <IcoMicro />
            <span>Enregistrer<br />l’audio</span>
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
          <p className="citation">{`« ${wake},\nQuelle sorte de fleur est-ce devant moi ? »`}</p>
          <p>Activez l’assistant vocal et posez-lui votre question ou passez votre demande.</p>
          <IcoPlateforme glyphe="orbe" className="illustration" />
        </button>

        {/* 6) traduction */}
        <button type="button" className="carte-fonction" onClick={() => nav.ouvrir('traduction')}>
          <h3>Traduction avec IA</h3>
          <p className="citation">{'Bonjour, quel est ton nom ?\nTraduction en cours…\nHello, what is your name?'}</p>
          <p>Différentes langues, même compréhension : la traduction assistée par IA vous rapproche du monde.</p>
          <IcoPlateforme glyphe="nuage" className="illustration" />
        </button>

        {/* 7) lumière BD (pas encore de support côté service) */}
        <button type="button" className="carte-fonction" onClick={() => nav.ouvrir('lumiere-bd')}>
          <span className="a-venir">À venir</span>
          <h3>Lumière BD</h3>
          <p className="citation">Traits de BD doux pour les moments du quotidien</p>
          <p>Prend en charge portraits, paysages et plus. Transforme le réel en BD.</p>
          <IcoPlateforme glyphe="baguette" className="illustration" />
        </button>
      </div>
    </div>
  )
}
