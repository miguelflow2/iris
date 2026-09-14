import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useStore } from '../lib/store'
import { Holo, TopBar, Vide } from '../components/ui'
import { IcoPlateforme } from '../components/icons'
import { CarteLunettesRequises } from '../components/LunettesRequises'
import { api, estLunettesRequises, formatDate, messageErreur } from '../lib/api'

/* =========================================================================
   « Lumière BD » : transformer une photo de l'album en image aux traits de
   bande dessinée (POST /api/album/bd, backend/iris/album.py).

   Ce que le service fait vraiment, et que l'écran dit : un effet graphique
   calculé SUR CET ORDINATEUR (lissage, aplats de 12 couleurs, contours encrés),
   sans modèle ni envoi, en quelques secondes. Ce n'est pas un dessin : sur une
   photo floue, sombre ou très texturée, des traits manquent ou débordent.

   Créer une image agit : le bouton exige les lunettes. Choisir une photo,
   regarder le résultat et l'exporter restent permis sans elles (ce sont les
   données de l'utilisateur).
   ========================================================================= */

interface Element {
  nom: string
  type: string
  octets: number
  modifie: string
}

interface Resultat {
  nom: string
  source: string
  duree_ms: number | null
}

export function LumiereBDScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  const { nav, presence, exigerLunettes, toast } = useStore()
  const [photos, setPhotos] = useState<Element[]>([])
  const [chargement, setChargement] = useState(true)
  const [choisie, setChoisie] = useState<string | null>(typeof params?.nom === 'string' ? params.nom : null)
  const [vignettes, setVignettes] = useState<Record<string, string>>({})
  const [resultat, setResultat] = useState<Resultat | null>(null)
  const [apresUrl, setApresUrl] = useState<string | null>(null)
  const [occupe, setOccupe] = useState<'creer' | 'exporter' | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [exporte, setExporte] = useState<{ chemin: string; filigrane: boolean } | null>(null)
  const urls = useRef<string[]>([])
  const monte = useRef(true)

  const absentes = presence !== null && !presence.presentes

  useEffect(() => {
    monte.current = true
    return () => {
      monte.current = false
      for (const u of urls.current) URL.revokeObjectURL(u)
      urls.current = []
    }
  }, [])

  const garderUrl = (blob: Blob): string => {
    const u = URL.createObjectURL(blob)
    urls.current.push(u)
    return u
  }

  const charger = useCallback(async () => {
    try {
      const r = await api.get('/api/album?type=photo')
      const liste: Element[] = Array.isArray(r?.elements) ? r.elements : []
      if (!monte.current) return
      setPhotos(liste)
      setChoisie((c) => c ?? liste[0]?.nom ?? null)
      setErreur(null)
      // La liste s'affiche tout de suite ; les vignettes arrivent ensuite.
      setChargement(false)
      // Vignettes chargées une à une, par le client authentifié : les 24 plus récentes suffisent au choix.
      for (const p of liste.slice(0, 24)) {
        try {
          const b = await api.blob(`/api/album/fichier/${encodeURIComponent(p.nom)}`)
          if (!monte.current) return
          const u = garderUrl(b)
          setVignettes((v) => ({ ...v, [p.nom]: u }))
        } catch {
          /* vignette indisponible : repli textuel */
        }
      }
    } catch (err) {
      if (monte.current) setErreur(messageErreur(err))
    } finally {
      if (monte.current) setChargement(false)
    }
  }, [])

  useEffect(() => {
    charger()
  }, [charger])

  // Photo choisie hors des 24 premières (ouverte depuis l'album) : sa vignette est chargée à part, une fois.
  const demandees = useRef(new Set<string>())
  useEffect(() => {
    if (chargement || !choisie || vignettes[choisie] || demandees.current.has(choisie)) return
    if (photos.slice(0, 24).some((p) => p.nom === choisie)) return
    demandees.current.add(choisie)
    api
      .blob(`/api/album/fichier/${encodeURIComponent(choisie)}`)
      .then((b) => {
        if (monte.current) setVignettes((v) => ({ ...v, [choisie]: garderUrl(b) }))
      })
      .catch(() => undefined)
  }, [chargement, choisie, photos, vignettes])

  const choisir = (nom: string): void => {
    setChoisie(nom)
    setResultat(null)
    setApresUrl(null)
    setExporte(null)
    setErreur(null)
  }

  const creer = async (): Promise<void> => {
    if (!choisie || occupe) return
    if (!exigerLunettes('Lumière BD')) return
    setOccupe('creer')
    setErreur(null)
    setExporte(null)
    try {
      const r = await api.post('/api/album/bd', { nom: choisie })
      const b = await api.blob(`/api/album/fichier/${encodeURIComponent(String(r?.nom || ''))}`)
      if (!monte.current) return
      setResultat({ nom: String(r.nom), source: String(r.source || choisie), duree_ms: typeof r?.duree_ms === 'number' ? r.duree_ms : null })
      setApresUrl(garderUrl(b))
    } catch (err) {
      if (!estLunettesRequises(err) && monte.current) setErreur(messageErreur(err))
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const exporter = async (): Promise<void> => {
    if (!resultat || occupe) return
    setOccupe('exporter')
    setErreur(null)
    try {
      // filigrane: null = le réglage « Filigrane » des paramètres d'album s'applique.
      const r = await api.post('/api/album/exporter', { nom: resultat.nom, filigrane: null })
      if (monte.current) setExporte({ chemin: String(r?.chemin || ''), filigrane: Boolean(r?.filigrane) })
    } catch (err) {
      if (monte.current) setErreur(messageErreur(err))
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const ouvrirDossier = async (chemin: string): Promise<void> => {
    const dossier = chemin.replace(/[\\/][^\\/]*$/, '')
    if (!dossier) return
    const e = await window.iris.openPath(dossier)
    if (e) toast(e, 'error')
  }

  const avantUrl = choisie ? vignettes[choisie] : undefined
  const styleImage: React.CSSProperties = { display: 'block', width: '100%', aspectRatio: '1', objectFit: 'cover', borderRadius: 14, background: 'var(--bg)' }

  return (
    <div className="ecran">
      <TopBar titre="Lumière BD" />
      <div className="contenu">
        <div className="carte" style={{ textAlign: 'center' }}>
          <IcoPlateforme glyphe="baguette" style={{ width: 150, height: 125 }} />
          <h3>Lumière BD</h3>
          <p className="desc" style={{ marginTop: 6 }}>
            Crée une copie d’une photo avec des aplats de couleur et des contours encrés, calculée sur cet ordinateur : rien n’est envoyé en ligne.
          </p>
          <p className="small muted" style={{ marginTop: 10, lineHeight: 1.45 }}>
            C’est un effet graphique, pas un dessin : sur une photo floue, sombre ou très texturée, des traits peuvent manquer ou déborder. Comptez quelques
            secondes par image. L’original n’est pas modifié.
          </p>
        </div>

        {absentes ? <CarteLunettesRequises fonction="Lumière BD" /> : null}

        {chargement ? (
          <div className="empty">Chargement des photos…</div>
        ) : photos.length === 0 ? (
          <Vide
            texte="Aucune photo dans l’album"
            petit="Lumière BD transforme les photos prises avec vos lunettes. Prenez une photo depuis l’accueil, puis revenez ici."
            action={
              <Holo variante="sombre" taille="petit" onClick={() => nav.allerOnglet('album')}>
                Ouvrir l’album
              </Holo>
            }
          />
        ) : (
          <>
            <h3 className="section-sous">1. Choisissez une photo</h3>
            <div className="grille-photos" role="listbox" aria-label="Photos de l’album">
              {photos.slice(0, 24).map((p) => (
                <button
                  key={p.nom}
                  type="button"
                  role="option"
                  aria-selected={p.nom === choisie}
                  aria-label={`Photo du ${formatDate(p.modifie)}`}
                  onClick={() => choisir(p.nom)}
                  style={p.nom === choisie ? { outline: '3px solid var(--blue)', outlineOffset: -3 } : undefined}
                >
                  {vignettes[p.nom] ? <img src={vignettes[p.nom]} alt="" /> : <span className="small muted">…</span>}
                </button>
              ))}
            </div>
            {photos.length > 24 ? (
              <div className="small muted">Les 24 photos les plus récentes sont proposées ; les autres s’ouvrent depuis l’album.</div>
            ) : null}

            <h3 className="section-sous">2. Avant, après</h3>
            <div className="cartes-2">
              <figure style={{ margin: 0 }}>
                {avantUrl ? <img src={avantUrl} alt="Photo d’origine" style={styleImage} /> : <div className="empty">Aucune photo choisie</div>}
                <figcaption className="small muted" style={{ textAlign: 'center', marginTop: 6 }}>Avant</figcaption>
              </figure>
              <figure style={{ margin: 0 }}>
                {apresUrl ? (
                  <img src={apresUrl} alt="Image aux traits de BD" style={styleImage} />
                ) : (
                  <div className="carte douce" style={{ ...styleImage, display: 'grid', placeItems: 'center', padding: 12 }}>
                    <span className="small muted" style={{ textAlign: 'center' }}>{occupe === 'creer' ? 'Transformation en cours…' : 'Le résultat s’affichera ici'}</span>
                  </div>
                )}
                <figcaption className="small muted" style={{ textAlign: 'center', marginTop: 6 }}>
                  Après{resultat?.duree_ms ? ` · calculée en ${(resultat.duree_ms / 1000).toFixed(1).replace('.', ',')} s` : ''}
                </figcaption>
              </figure>
            </div>

            {erreur ? <div className="bloc-note erreur" role="alert">{erreur}</div> : null}

            {!resultat ? (
              <Holo disabled={!choisie || occupe !== null} onClick={creer}>
                {occupe === 'creer' ? 'Transformation…' : 'Créer l’image BD'}
              </Holo>
            ) : (
              <div className="col" style={{ gap: 10 }}>
                <div className="bloc-note ok" role="status">
                  Image enregistrée dans l’album sous « {resultat.nom} », sur cet ordinateur (non chiffrée).
                </div>
                <Holo disabled={occupe !== null} onClick={exporter}>
                  {occupe === 'exporter' ? 'Exportation…' : 'Exporter'}
                </Holo>
                {exporte ? (
                  <div className="bloc-note ok" role="status">
                    Copiée dans <span className="mono" style={{ wordBreak: 'break-all' }}>{exporte.chemin}</span>
                    {exporte.filigrane ? ' (avec filigrane, sans métadonnées)' : ''}.
                    <div style={{ marginTop: 8 }}>
                      <button type="button" className="btn sm" onClick={() => ouvrirDossier(exporte.chemin)}>Ouvrir le dossier</button>
                    </div>
                  </div>
                ) : null}
                <Holo variante="sombre" disabled={occupe !== null} onClick={() => choisir(resultat.source)}>
                  Transformer une autre photo
                </Holo>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
