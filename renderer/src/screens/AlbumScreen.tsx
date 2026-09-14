import React, { useCallback, useEffect, useRef, useState } from 'react'
import { BtnIcone, Holo, Liste, Modal, Puces, Rangee, TopBar, Vide } from '../components/ui'
import { IcoAlbumDegrade, IcoEngrenage, IcoMicro } from '../components/icons'
import { api, ApiError, estLunettesRequises, formatDate, formatTime, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   Onglet « Album photo » (maquette IMG_0696) : ce que l'album local d'IRIS
   contient vraiment (GET /api/album, backend/iris/album.py) — les photos des
   lunettes, les images « Lumière BD » et les enregistrements audio (WAV de
   l'enregistreur et du mode cours), tous rangés dans data_dir/captures, sur
   cet ordinateur.

   - Consulter, exporter et supprimer sont TOUJOURS permis, lunettes ou non :
     ce sont les données de l'utilisateur (Loi 25). Créer une image BD ou
     prendre une photo agit : ces deux gestes exigent les lunettes.
   - Les vidéos restent dans les lunettes : le fabricant ne documente pas leur
     transfert. Le filtre « Vidéos » le dit au lieu d'afficher un vide muet.
   - Photos, BD et WAV ne sont PAS chiffrés sur le disque : l'écran dit
     « stockés sur cet ordinateur », jamais « chiffrés ».
   ========================================================================= */

type Filtre = 'tout' | 'photos' | 'videos' | 'enregistrements'
type Genre = 'photo' | 'audio' | 'bd'

interface Element {
  nom: string
  /** champ « type » de la réponse HTTP (les événements, eux, portent « genre ») */
  type: Genre
  octets: number
  modifie: string
  duree_s: number | null
}

interface Exportation {
  nom: string
  chemin: string
  filigrane: boolean
}

const FILTRES: { id: Filtre; label: string }[] = [
  { id: 'tout', label: 'Tout' },
  { id: 'photos', label: 'Photos' },
  { id: 'videos', label: 'Vidéos' },
  { id: 'enregistrements', label: 'Enregistrements' }
]

/** Au-delà, le WAV n'est pas chargé tout seul à l'ouverture : il pèse lourd en mémoire vive. */
const AUDIO_AUTO_MAX_OCTETS = 100 * 1024 * 1024

function messageErreur(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

function taille(octets: number): string {
  if (octets >= 1024 * 1024) return `${(octets / (1024 * 1024)).toFixed(1).replace('.', ',')} Mo`
  return `${Math.max(1, Math.round(octets / 1024))} Ko`
}

function duree(secondes: number | null): string {
  if (secondes === null || !Number.isFinite(secondes)) return ''
  const s = Math.max(0, Math.round(secondes))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = String(s % 60).padStart(2, '0')
  return h > 0 ? `${h} h ${String(m).padStart(2, '0')} min` : m > 0 ? `${m} min ${r} s` : `${s} s`
}

/** Libellé d'un enregistrement d'après le nom que lui donne le service. */
function libelleAudio(nom: string): string {
  if (nom.startsWith('cours-import-')) return 'Cours importé'
  if (nom.startsWith('cours-')) return 'Cours'
  return 'Enregistrement'
}

function estImage(e: Element): boolean {
  return e.type === 'photo' || e.type === 'bd'
}

/** Identité d'un élément : même nom, même date, même taille = même fichier (l'aperçu peut être réutilisé). */
function cleDe(e: Element): string {
  return `${e.nom}|${e.modifie}|${e.octets}`
}

function memeListe(a: Element[], b: Element[]): boolean {
  return a.length === b.length && a.every((e, i) => cleDe(e) === cleDe(b[i]))
}

/** Dossier parent d'un chemin local (Windows ou POSIX). */
function dossierDe(chemin: string): string {
  return chemin.replace(/[\\/][^\\/]*$/, '')
}

export function AlbumScreen(): JSX.Element {
  const { nav, lunettes, toast, exigerLunettes } = useStore()
  const [filtre, setFiltre] = useState<Filtre>('tout')
  const [elements, setElements] = useState<Element[]>([])
  const [apercus, setApercus] = useState<Record<string, string>>({})
  const [chargement, setChargement] = useState(true)
  const [erreur, setErreur] = useState<string | null>(null)
  const [suspendue, setSuspendue] = useState<string | null>(null)
  const [prise, setPrise] = useState(false)
  const [ouvert, setOuvert] = useState<Element | null>(null)
  const [action, setAction] = useState<'bd' | 'exporter' | 'supprimer' | null>(null)
  const [exporte, setExporte] = useState<Exportation | null>(null)
  const [erreurModale, setErreurModale] = useState<string | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [audioChargement, setAudioChargement] = useState(false)
  // URL objet vivantes, par clé d'élément : réutilisées d'un rechargement à l'autre pour que la grille
  // ne pointe jamais sur une URL déjà révoquée pendant qu'on relit les blobs.
  const urlsRef = useRef<Record<string, string>>({})
  // Numéro de la dernière lecture demandée : une réponse lente d'un ancien filtre ne doit pas écraser la liste.
  const demandeRef = useRef(0)
  const monte = useRef(true)
  const filtreRef = useRef<Filtre>(filtre)
  filtreRef.current = filtre

  const connecte = Boolean(lunettes?.connected)

  // Le dossier de l'album est construit par le service comme data_dir / "captures" (album.py).
  const dataDir = api.info?.data_dir || ''
  const dossierAlbum = dataDir ? `${dataDir}${dataDir.includes('\\') ? '\\' : '/'}captures` : ''

  useEffect(() => {
    monte.current = true
    return () => {
      monte.current = false
    }
  }, [])

  const charger = useCallback(async (): Promise<Element[]> => {
    const f = filtreRef.current
    const numero = ++demandeRef.current
    if (f === 'videos') {
      setChargement(false)
      return []
    }
    try {
      let liste: Element[]
      let infos: any
      if (f === 'photos') {
        // « Photos » = les photos ET leurs versions BD ; le service les range sous deux types.
        const [p, b] = await Promise.all([api.get('/api/album?type=photo'), api.get('/api/album?type=bd')])
        liste = [...(Array.isArray(p?.elements) ? p.elements : []), ...(Array.isArray(b?.elements) ? b.elements : [])]
        liste.sort((x, y) => String(y.modifie).localeCompare(String(x.modifie)))
        infos = p
      } else {
        infos = await api.get(`/api/album?type=${f === 'enregistrements' ? 'audio' : 'tout'}`)
        liste = Array.isArray(infos?.elements) ? infos.elements : []
      }
      if (!monte.current || numero !== demandeRef.current) return liste
      setElements((prev) => (memeListe(prev, liste) ? prev : liste))
      setSuspendue(infos?.memoire_suspendue ?? null)
      setErreur(null)
      return liste
    } catch (err) {
      if (monte.current && numero === demandeRef.current) setErreur(messageErreur(err))
      return []
    } finally {
      if (monte.current && numero === demandeRef.current) setChargement(false)
    }
  }, [])

  useEffect(() => {
    setChargement(true)
    setElements([])
    charger()
  }, [filtre, charger])

  // Nouvelle photo (voix, accueil, bouton des lunettes), nouvelle BD, enregistrement terminé,
  // suppression ou purge de rétention : la liste se relit.
  const enregistrait = useRef(false)
  useEffect(() => {
    return api.on((e: IrisEvent) => {
      if (e.type === 'glasses.photo' || e.type === 'album.nouveau' || e.type === 'album.supprime' || e.type === 'album.purge') {
        charger()
      } else if (e.type === 'album.auto_ignore' && e.raison) {
        // Enregistrement automatique demandé mais refusé (mode invité, zone, dossier inaccessible) : on le dit.
        toast(`Copie automatique non faite : ${e.raison}`, 'info')
      } else if (e.type === 'ecoute.etat') {
        // Début ou fin d'un enregistrement (ou d'un cours) : le WAV apparaît, puis change de taille
        // jusqu'à l'arrêt. On relit seulement à ces bascules, pas à chaque état publié.
        const actif = Boolean(e.enregistrement?.actif) || Boolean(e.cours)
        if (actif !== enregistrait.current) {
          enregistrait.current = actif
          if (filtreRef.current === 'tout' || filtreRef.current === 'enregistrements') charger()
        }
      }
    })
  }, [charger, toast])

  // Aperçus des images via le client authentifié (un <img src> nu ne porterait pas le jeton), en URL
  // objet. Les aperçus déjà chargés sont réutilisés ; les anciennes URL ne sont révoquées qu'APRÈS la
  // pose de la nouvelle carte (aucune vignette cassée entre-temps), et tout est libéré au démontage.
  useEffect(() => {
    let annule = false
    const creees: string[] = []
    ;(async () => {
      const vivantes = urlsRef.current
      const suivantes: Record<string, string> = { ...vivantes }
      const map: Record<string, string> = {}
      for (const e of elements) {
        if (!estImage(e)) continue
        const cle = cleDe(e)
        let url: string | undefined = vivantes[cle]
        if (!url) {
          try {
            const b = await api.blob(`/api/album/fichier/${encodeURIComponent(e.nom)}`)
            if (annule) return
            url = URL.createObjectURL(b)
            creees.push(url)
          } catch {
            /* aperçu indisponible : la vignette affichera un repli */
            continue
          }
        }
        suivantes[cle] = url
        map[e.nom] = url
      }
      if (annule) return
      // On ne révoque que les aperçus des éléments qui n'existent plus du tout, et seulement quand la
      // liste complète est connue (filtre « Tout », liste non vide : une liste vidée le temps d'un
      // changement de filtre ne doit pas jeter les aperçus qu'on va réafficher).
      const presents = new Set(elements.map(cleDe))
      const perimees: string[] = []
      if (filtreRef.current === 'tout' && elements.length > 0) {
        for (const cle of Object.keys(suivantes)) {
          if (!presents.has(cle)) {
            perimees.push(suivantes[cle])
            delete suivantes[cle]
          }
        }
      }
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
  }, [elements])

  // Démontage de l'onglet : libère toutes les URL objet encore vivantes.
  useEffect(
    () => () => {
      for (const url of Object.values(urlsRef.current)) URL.revokeObjectURL(url)
      urlsRef.current = {}
    },
    []
  )

  /* ---------------------------------------------------------------- lecture audio de l'élément ouvert */
  const chargerAudio = useCallback(async (e: Element) => {
    setAudioChargement(true)
    try {
      const b = await api.blob(`/api/album/fichier/${encodeURIComponent(e.nom)}`)
      if (!monte.current) return
      setAudioUrl((ancienne) => {
        if (ancienne) URL.revokeObjectURL(ancienne)
        return URL.createObjectURL(b)
      })
    } catch (err) {
      if (monte.current) setErreurModale(messageErreur(err))
    } finally {
      if (monte.current) setAudioChargement(false)
    }
  }, [])

  useEffect(() => {
    if (ouvert?.type === 'audio' && ouvert.octets <= AUDIO_AUTO_MAX_OCTETS) chargerAudio(ouvert)
    return () => {
      setAudioUrl((ancienne) => {
        if (ancienne) URL.revokeObjectURL(ancienne)
        return null
      })
    }
  }, [ouvert, chargerAudio])

  const ouvrir = (e: Element): void => {
    setExporte(null)
    setErreurModale(null)
    setAction(null)
    setOuvert(e)
  }
  const fermer = (): void => {
    if (action) return
    setOuvert(null)
  }

  /* ---------------------------------------------------------------- actions */
  const photo = async (): Promise<void> => {
    if (!exigerLunettes('Prendre une photo')) return
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
      if (!estLunettesRequises(err)) {
        // 409 = limite assumée (paire sans caméra, format de trame non confirmé) : note « info ».
        const statut = err instanceof ApiError ? err.status : 0
        toast(messageErreur(err), statut === 409 ? 'info' : 'error')
      }
    } finally {
      if (monte.current) setPrise(false)
    }
  }

  const creerBd = async (e: Element): Promise<void> => {
    if (!exigerLunettes('Lumière BD')) return
    setAction('bd')
    setErreurModale(null)
    try {
      const r = await api.post('/api/album/bd', { nom: e.nom })
      const secondes = typeof r?.duree_ms === 'number' ? ` en ${(r.duree_ms / 1000).toFixed(1).replace('.', ',')} s` : ''
      toast(`Image BD créée${secondes}, sur cet ordinateur.`, 'success')
      const liste = await charger()
      const nouvelle = liste.find((x) => x.nom === r?.nom)
      if (monte.current && nouvelle) {
        setExporte(null)
        setOuvert(nouvelle)
      }
    } catch (err) {
      if (!estLunettesRequises(err) && monte.current) setErreurModale(messageErreur(err))
    } finally {
      if (monte.current) setAction(null)
    }
  }

  const exporter = async (e: Element): Promise<void> => {
    setAction('exporter')
    setErreurModale(null)
    try {
      // filigrane: null = le service applique le réglage « Filigrane » des paramètres d'album.
      const r = await api.post('/api/album/exporter', { nom: e.nom, filigrane: null })
      if (monte.current) setExporte({ nom: e.nom, chemin: String(r?.chemin || ''), filigrane: Boolean(r?.filigrane) })
    } catch (err) {
      if (monte.current) setErreurModale(messageErreur(err))
    } finally {
      if (monte.current) setAction(null)
    }
  }

  const supprimer = async (e: Element): Promise<void> => {
    if (!window.confirm(`Supprimer « ${e.nom} » de cet ordinateur ? Cette action est définitive.`)) return
    setAction('supprimer')
    setErreurModale(null)
    try {
      await api.delete(`/api/album/${encodeURIComponent(e.nom)}`)
      toast('Élément supprimé de l’album.', 'info')
      if (monte.current) setOuvert(null)
      charger()
    } catch (err) {
      if (monte.current) setErreurModale(messageErreur(err))
    } finally {
      if (monte.current) setAction(null)
    }
  }

  const ouvrirDossier = async (chemin: string): Promise<void> => {
    if (!chemin) return
    const erreurOuverture = await window.iris.openPath(chemin)
    if (erreurOuverture) toast(erreurOuverture, 'error')
  }

  /* ---------------------------------------------------------------- rendu */
  const boutonPhoto =
    connecte && filtre !== 'enregistrements' ? (
      <Holo disabled={prise} onClick={photo}>{prise ? 'Prise en cours…' : 'Prendre une photo'}</Holo>
    ) : null

  const images = elements.filter(estImage)
  const audios = elements.filter((e) => e.type === 'audio')

  const grille =
    images.length > 0 ? (
      <div className="grille-photos">
        {images.map((e) => (
          <button
            key={e.nom}
            type="button"
            title={e.nom}
            aria-label={`${e.type === 'bd' ? 'Image BD' : 'Photo'} du ${formatDate(e.modifie)}`}
            onClick={() => ouvrir(e)}
          >
            {apercus[e.nom] ? <img src={apercus[e.nom]} alt="" /> : <span className="small muted">…</span>}
            {e.type === 'bd' ? (
              <span className="pill" style={{ position: 'absolute', top: 6, left: 6, background: 'rgba(0, 0, 0, 0.6)', color: '#fff', border: 'none', fontWeight: 800 }}>
                BD
              </span>
            ) : null}
            <span className="legende">{formatTime(e.modifie)} · {taille(e.octets)}</span>
          </button>
        ))}
      </div>
    ) : null

  const listeAudio =
    audios.length > 0 ? (
      <Liste>
        {audios.map((e) => (
          <Rangee
            key={e.nom}
            icone={<IcoMicro />}
            titre={`${libelleAudio(e.nom)} · ${formatDate(e.modifie)}`}
            sous={[duree(e.duree_s), taille(e.octets)].filter(Boolean).join(' · ')}
            onClick={() => ouvrir(e)}
          />
        ))}
      </Liste>
    ) : null

  let corps: React.ReactNode
  if (filtre === 'videos') {
    corps = (
      <Vide
        icone={<IcoAlbumDegrade />}
        texte="Les vidéos restent dans les lunettes"
        petit="Les lunettes enregistrent la vidéo elles-mêmes (deux clics sur le bouton avant). Le fabricant ne documente pas leur transfert : IRIS ne peut pas les récupérer ni les afficher ici."
      />
    )
  } else if (chargement && elements.length === 0) {
    corps = <div className="empty">Chargement…</div>
  } else if (elements.length === 0) {
    corps = (
      <>
        {filtre === 'enregistrements' ? (
          <Vide
            icone={<IcoAlbumDegrade />}
            texte="Aucun enregistrement pour le moment"
            petit="Lancez « Enregistrer l’audio » depuis l’accueil, ou enregistrez un cours. Les enregistrements sont des fichiers WAV stockés sur cet ordinateur, non chiffrés."
          />
        ) : (
          <Vide
            icone={<IcoAlbumDegrade />}
            texte={filtre === 'photos' ? 'Aucune photo pour le moment' : 'L’album est vide'}
            petit={connecte ? 'Prenez une photo depuis l’accueil ou avec le bouton avant des lunettes.' : 'Connectez vos lunettes pour prendre des photos.'}
          />
        )}
        {boutonPhoto}
      </>
    )
  } else {
    corps = (
      <>
        {grille}
        {filtre === 'tout' && audios.length > 0 && images.length > 0 ? <h3 className="section-sous">Enregistrements</h3> : null}
        {listeAudio}
        <div className="small muted" style={{ textAlign: 'center', lineHeight: 1.45 }}>
          {elements.length} élément{elements.length > 1 ? 's' : ''} · stocké{elements.length > 1 ? 's' : ''} sur cet ordinateur seulement, non chiffré
          {elements.length > 1 ? 's' : ''}
        </div>
        {boutonPhoto}
      </>
    )
  }

  const titreModale = ouvert
    ? ouvert.type === 'audio'
      ? libelleAudio(ouvert.nom)
      : ouvert.type === 'bd'
        ? 'Image Lumière BD'
        : 'Photo'
    : ''

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
        {suspendue ? (
          <div className="bloc-note attention" role="status">
            Mémoire suspendue ({suspendue}) : aucune nouvelle photo, image BD ni enregistrement n’est gardé pour l’instant. Consulter, exporter et supprimer
            restent possibles.
          </div>
        ) : null}
        {erreur ? <div className="bloc-note erreur" role="alert">{erreur}</div> : null}
        {corps}
      </div>

      {ouvert ? (
        <Modal
          title={titreModale}
          onClose={fermer}
          actions={
            <>
              {ouvert.type === 'photo' ? (
                <button type="button" className="btn" disabled={action !== null} onClick={() => creerBd(ouvert)}>
                  {action === 'bd' ? 'Transformation…' : 'Lumière BD'}
                </button>
              ) : null}
              <button type="button" className="btn" disabled={action !== null} onClick={() => exporter(ouvert)}>
                {action === 'exporter' ? 'Exportation…' : 'Exporter'}
              </button>
              <button type="button" className="btn danger" disabled={action !== null} onClick={() => supprimer(ouvert)}>
                {action === 'supprimer' ? 'Suppression…' : 'Supprimer'}
              </button>
              <button type="button" className="btn primary" disabled={action !== null} onClick={fermer}>Fermer</button>
            </>
          }
        >
          {estImage(ouvert) ? (
            apercus[ouvert.nom] ? (
              <img
                src={apercus[ouvert.nom]}
                alt={ouvert.type === 'bd' ? 'Image aux traits de BD' : 'Photo des lunettes'}
                style={{ display: 'block', width: '100%', maxHeight: '55vh', objectFit: 'contain', borderRadius: 14, background: 'var(--bg)' }}
              />
            ) : (
              <div className="empty">Aperçu indisponible.</div>
            )
          ) : audioUrl ? (
            <audio controls src={audioUrl} style={{ width: '100%' }} aria-label={`${libelleAudio(ouvert.nom)} du ${formatDate(ouvert.modifie)}`} />
          ) : (
            <div className="col" style={{ gap: 10, alignItems: 'flex-start' }}>
              {audioChargement ? (
                <div className="small muted">Chargement du son…</div>
              ) : (
                <>
                  <div className="small muted" style={{ lineHeight: 1.45 }}>
                    Fichier volumineux ({taille(ouvert.octets)}) : il est chargé en mémoire pour être écouté, ce qui peut prendre un moment.
                  </div>
                  <button type="button" className="btn sm" onClick={() => chargerAudio(ouvert)}>Charger pour écouter</button>
                </>
              )}
            </div>
          )}
          <p className="small muted" style={{ marginTop: 10, lineHeight: 1.45 }}>
            {formatDate(ouvert.modifie)}
            {ouvert.type === 'audio' && ouvert.duree_s !== null ? ` · ${duree(ouvert.duree_s)}` : ''} · {taille(ouvert.octets)} · stocké sur cet ordinateur, non
            chiffré, envoyé à personne.
          </p>
          {ouvert.type === 'photo' ? (
            <p className="small muted" style={{ lineHeight: 1.45 }}>
              « Lumière BD » crée une copie aux traits de BD, calculée sur cet ordinateur en quelques secondes. C’est un effet graphique : sur une photo floue,
              sombre ou très texturée, des traits peuvent manquer ou déborder.
            </p>
          ) : null}
          {exporte && exporte.nom === ouvert.nom ? (
            <div className="bloc-note ok" role="status" style={{ marginTop: 8 }}>
              Copié dans <span className="mono" style={{ wordBreak: 'break-all' }}>{exporte.chemin}</span>
              {exporte.filigrane ? ' (avec filigrane, sans métadonnées)' : ''}.
              <div style={{ marginTop: 8 }}>
                <button type="button" className="btn sm" onClick={() => ouvrirDossier(dossierDe(exporte.chemin))}>Ouvrir le dossier d’exportation</button>
              </div>
            </div>
          ) : null}
          {erreurModale ? <div className="bloc-note erreur" role="alert" style={{ marginTop: 8 }}>{erreurModale}</div> : null}
          {dossierAlbum && !exporte ? (
            <div style={{ marginTop: 8 }}>
              <button type="button" className="btn ghost sm" onClick={() => ouvrirDossier(ouvert.type === 'audio' ? `${dossierAlbum}${dossierAlbum.includes('\\') ? '\\' : '/'}audio` : dossierAlbum)}>
                Ouvrir le dossier de l’album
              </button>
            </div>
          ) : null}
        </Modal>
      ) : null}
    </div>
  )
}
