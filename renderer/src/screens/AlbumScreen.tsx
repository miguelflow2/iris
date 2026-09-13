import React, { useCallback, useEffect, useRef, useState } from 'react'
import { BtnIcone, Holo, Modal, Puces, TopBar, Vide } from '../components/ui'
import { IcoAlbumDegrade, IcoEngrenage } from '../components/icons'
import { api, ApiError, formatDate, formatTime, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   Onglet « Album photo » (maquette IMG_0696) : les photos prises par la caméra
   des lunettes et rapatriées sur cet ordinateur (dossier data_dir/captures).
   Le service ne sait ni filmer ni enregistrer l'audio : les filtres « Vidéos »
   et « Enregistrements » existent (même disposition que la maquette) mais
   affichent un état vide honnête.
   ========================================================================= */

type Filtre = 'tout' | 'photos' | 'videos' | 'enregistrements'

interface Capture {
  nom: string
  octets: number
  modifie: string
}

const FILTRES: { id: Filtre; label: string }[] = [
  { id: 'tout', label: 'Tout' },
  { id: 'photos', label: 'Photos' },
  { id: 'videos', label: 'Vidéos' },
  { id: 'enregistrements', label: 'Enregistrements' }
]

function ko(octets: number): number {
  return Math.max(1, Math.round(octets / 1024))
}

/** Identité d'une capture : même nom, même date, même taille = même image (l'aperçu peut être réutilisé). */
function cleDe(c: Capture): string {
  return `${c.nom}|${c.modifie}|${c.octets}`
}

function memeListe(a: Capture[], b: Capture[]): boolean {
  return a.length === b.length && a.every((c, i) => cleDe(c) === cleDe(b[i]))
}

export function AlbumScreen(): JSX.Element {
  const { nav, lunettes, toast } = useStore()
  const [filtre, setFiltre] = useState<Filtre>('tout')
  const [captures, setCaptures] = useState<Capture[]>([])
  const [apercus, setApercus] = useState<Record<string, string>>({})
  const [chargement, setChargement] = useState(true)
  const [prise, setPrise] = useState(false)
  const [ouverte, setOuverte] = useState<Capture | null>(null)
  // URL objet vivantes, par clé de capture : réutilisées d'un rechargement à l'autre pour que la grille
  // ne pointe jamais sur une URL déjà révoquée pendant qu'on relit les blobs.
  const urlsRef = useRef<Record<string, string>>({})

  const connecte = Boolean(lunettes?.connected)

  // Le dossier des captures est construit par le service comme data_dir / "captures"
  // (backend/iris/main.py, glasses_captures). On reprend le séparateur déjà présent.
  const dataDir = api.info?.data_dir || ''
  const dossierCaptures = dataDir ? `${dataDir}${dataDir.includes('\\') ? '\\' : '/'}captures` : ''

  const charger = useCallback(async () => {
    try {
      const r = await api.get('/api/glasses/captures')
      const liste: Capture[] = Array.isArray(r?.captures) ? r.captures : []
      // Même liste qu'avant (glasses.photo puis rechargement après la prise, par exemple) : on garde
      // le même tableau pour ne pas relire tous les aperçus inutilement.
      setCaptures((prev) => (memeListe(prev, liste) ? prev : liste))
    } catch {
      /* dossier absent ou service indisponible : la galerie affiche « aucune photo » */
    } finally {
      setChargement(false)
    }
  }, [])

  useEffect(() => {
    charger()
    // Photo prise depuis la voix (« Dis-moi Iris, prends une photo ») ou depuis l'accueil :
    // le service publie glasses.photo, la galerie se rafraîchit.
    return api.on((e: IrisEvent) => {
      if (e.type === 'glasses.photo') charger()
    })
  }, [charger])

  // Charge l'aperçu de chaque capture via le client authentifié (un <img src> nu ne porterait pas
  // le jeton), puis en fait une URL objet. Les aperçus déjà chargés sont réutilisés ; les anciennes
  // URL ne sont révoquées qu'APRÈS la pose de la nouvelle carte (aucune vignette cassée entre-temps),
  // et tout est libéré au démontage.
  useEffect(() => {
    let annule = false
    const creees: string[] = []
    ;(async () => {
      const vivantes = urlsRef.current
      const suivantes: Record<string, string> = {}
      const map: Record<string, string> = {}
      for (const c of captures) {
        const cle = cleDe(c)
        let url: string | undefined = vivantes[cle]
        if (!url) {
          try {
            const b = await api.blob(`/api/glasses/captures/${encodeURIComponent(c.nom)}`)
            if (annule) return
            url = URL.createObjectURL(b)
            creees.push(url)
          } catch {
            /* aperçu indisponible : la vignette affichera un repli */
            continue
          }
        }
        suivantes[cle] = url
        map[c.nom] = url
      }
      if (annule) return
      const perimees = Object.keys(vivantes)
        .filter((cle) => !suivantes[cle])
        .map((cle) => vivantes[cle])
      urlsRef.current = suivantes
      setApercus(map)
      for (const url of perimees) URL.revokeObjectURL(url)
    })()
    return () => {
      annule = true
      // Les URL créées par cette passe mais jamais posées (passe annulée) ne sont référencées nulle part.
      const conservees = new Set(Object.values(urlsRef.current))
      for (const url of creees) if (!conservees.has(url)) URL.revokeObjectURL(url)
    }
  }, [captures])

  // Démontage de l'onglet : libère toutes les URL objet encore vivantes.
  useEffect(
    () => () => {
      for (const url of Object.values(urlsRef.current)) URL.revokeObjectURL(url)
      urlsRef.current = {}
    },
    []
  )

  const photo = async (): Promise<void> => {
    setPrise(true)
    try {
      const r = await api.post('/api/glasses/photo', { reconnaissance: false })
      if (r?.ok) {
        toast(r.constat || 'Photo enregistrée sur votre ordinateur.', 'success')
        charger()
      } else {
        // Trame envoyée mais image non reconstituée : constat honnête, pas un faux succès.
        toast(r?.constat || 'Aucune image reçue.', 'info')
      }
    } catch (err) {
      // 409 = limite assumée (paire sans caméra, format de trame non confirmé) : note « info ».
      // Tout autre code (500 = vraie panne interne) = erreur.
      const statut = err instanceof ApiError ? err.status : 0
      toast(String((err as Error).message), statut === 409 ? 'info' : 'error')
    } finally {
      setPrise(false)
    }
  }

  const ouvrirDossier = async (): Promise<void> => {
    if (!dossierCaptures) return
    const erreur = await window.iris.openPath(dossierCaptures)
    if (erreur) toast(erreur, 'error')
  }

  const boutonPhoto = connecte ? (
    <Holo disabled={prise} onClick={photo}>{prise ? 'Prise en cours…' : 'Prendre une photo'}</Holo>
  ) : null

  let corps: React.ReactNode
  if (filtre === 'videos') {
    corps = <Vide icone={<IcoAlbumDegrade />} texte="Aucune vidéo pour le moment" petit="L’enregistrement vidéo arrive dans une prochaine version." />
  } else if (filtre === 'enregistrements') {
    corps = <Vide icone={<IcoAlbumDegrade />} texte="Aucun enregistrement pour le moment" petit="L’enregistrement audio arrive dans une prochaine version." />
  } else if (captures.length === 0) {
    corps = (
      <>
        {chargement ? (
          <div className="empty">Chargement…</div>
        ) : (
          <Vide
            icone={<IcoAlbumDegrade />}
            texte="Aucune photo pour le moment"
            petit={connecte ? 'Prenez une photo depuis l’accueil ou avec le bouton avant des lunettes.' : 'Connectez vos lunettes pour prendre des photos.'}
          />
        )}
        {boutonPhoto}
      </>
    )
  } else {
    corps = (
      <>
        <div className="grille-photos">
          {captures.map((c) => (
            <button key={c.nom} type="button" title={c.nom} aria-label={`Photo du ${formatDate(c.modifie)}`} onClick={() => setOuverte(c)}>
              {apercus[c.nom] ? <img src={apercus[c.nom]} alt={c.nom} /> : <span className="small muted">…</span>}
              <span className="legende">{formatTime(c.modifie)} · {ko(c.octets)} Ko</span>
            </button>
          ))}
        </div>
        <div className="small muted" style={{ textAlign: 'center' }}>
          {captures.length} photo{captures.length > 1 ? 's' : ''} · conservée{captures.length > 1 ? 's' : ''} sur cet ordinateur seulement
        </div>
        {boutonPhoto}
      </>
    )
  }

  return (
    <div className="ecran avec-onglets">
      <TopBar
        titre="Album photo"
        retour={false}
        droite={
          <BtnIcone title="Paramètres d’album" aria-label="Paramètres d’album" onClick={() => nav.ouvrir('album-parametres')}>
            <IcoEngrenage />
          </BtnIcone>
        }
      />
      <div className="contenu">
        <Puces options={FILTRES} valeur={filtre} onChange={setFiltre} />
        {corps}
      </div>

      {ouverte ? (
        <Modal
          title={ouverte.nom}
          onClose={() => setOuverte(null)}
          actions={
            <>
              {dossierCaptures ? (
                <button type="button" className="btn" onClick={ouvrirDossier}>Ouvrir le dossier</button>
              ) : null}
              <button type="button" className="btn primary" onClick={() => setOuverte(null)}>Fermer</button>
            </>
          }
        >
          {apercus[ouverte.nom] ? (
            <img
              src={apercus[ouverte.nom]}
              alt={ouverte.nom}
              style={{ display: 'block', width: '100%', maxHeight: '60vh', objectFit: 'contain', borderRadius: 14, background: 'var(--bg)' }}
            />
          ) : (
            <div className="empty">Aperçu indisponible.</div>
          )}
          <p className="small muted" style={{ marginTop: 10 }}>
            {formatDate(ouverte.modifie)} · {ko(ouverte.octets)} Ko · enregistrée sur cet ordinateur, envoyée à personne.
          </p>
        </Modal>
      ) : null}
    </div>
  )
}
