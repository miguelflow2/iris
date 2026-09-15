import React, { useEffect, useRef, useState } from 'react'
import { Holo, Toggle, TopBar } from '../components/ui'
import { IcoAvertissement, IcoCamera, IcoFermer, IcoImage, IcoLien, IcoRecherche } from '../components/icons'
import { CarteLunettesRequises } from '../components/LunettesRequises'
import { ApiError, api, messageErreur } from '../lib/api'
import { useStore } from '../lib/store'
import { BlocRefus, dureeLisible, dureeMesuree, lireRefus, pluriel, useTic, VideCompact, type Refus } from './CoursScreen'
import { formatMontant } from './RecusScreen'
import './AccessibiliteScreen.css'
import './CoursScreen.css'

/* =========================================================================
   « Comparer les prix » : ce produit, combien ailleurs au Canada ?

   Ce que fait le service (backend/iris/prix.py), dit à l'écran :
   - identification par la vision (photo) ou par le nom tapé ; rien n'est
     deviné, un produit non identifié est refusé ;
   - recherche par l'API de recherche web d'IRIS (elle doit être configurée
     sur l'ordinateur) ; les prix sont tirés des EXTRAITS de résultats, en
     dollars canadiens seulement, une offre par marchand ;
   - l'avertissement du service est toujours affiché, en tête des résultats :
     un extrait peut dater, le prix et le stock en magasin peuvent différer ;
   - la requête quitte l'ordinateur (accord « Texte de vos demandes ») ; rien
     n'est conservé.

   Lunettes d'abord : comparer exige les lunettes.
   ========================================================================= */

interface Produit {
  nom: string | null
  marque: string | null
  format: string | null
  code_barres: string | null
  prix_vu: number | null
}

interface Offre {
  marchand: string
  prix: number
  devise: string
  url: string
  extrait: string
  titre?: string
}

interface Comparaison {
  produit: Produit
  offres: Offre[]
  resume: string
  avertissement: string
  local: boolean
  source?: string
  description?: string | null
  ecartees?: number
  recherches?: number
  duree_ms?: number
}

interface ImageChoisie {
  name: string
  media_type: string
  data: string
}

function hote(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

export function PrixScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { nav, toast, presence, exigerLunettes } = useStore()
  const [requete, setRequete] = useState('')
  const [image, setImage] = useState<ImageChoisie | null>(null)
  const [parler, setParler] = useState(false)
  const [enCours, setEnCours] = useState<{ quoi: 'nom' | 'lunettes' | 'image'; depuis: number } | null>(null)
  const [resultat, setResultat] = useState<Comparaison | null>(null)
  // « configurer » : refus 409 du service faute de clé de recherche web, qui se règle dans Contrôle de l’ordinateur › Moteur avancé (écran reglages-pc).
  const [refus, setRefus] = useState<(Refus & { description: string | null; reessayer: () => void; configurer?: boolean }) | null>(null)
  const vivant = useRef(true)
  const tic = useTic(Boolean(enCours))

  const absentes = presence !== null && !presence.presentes

  useEffect(() => {
    vivant.current = true
    return () => {
      vivant.current = false
    }
  }, [])

  const comparer = async (quoi: 'nom' | 'lunettes' | 'image', img: ImageChoisie | null = image): Promise<void> => {
    if (enCours) return
    const texte = requete.trim()
    if (quoi === 'nom' && !texte) {
      setRefus({ message: 'Tapez le nom du produit (marque et format si possible).', consentement: null, description: null, reessayer: () => undefined })
      return
    }
    if (quoi === 'image' && !img) return
    if (!exigerLunettes('Comparer les prix')) return
    // Photo des lunettes : pas de texte joint, sinon le service chercherait le nom tapé au lieu de regarder.
    const corps =
      quoi === 'nom'
        ? { source: 'image', image: null, requete: texte, parler }
        : quoi === 'lunettes'
          ? { source: 'lunettes', image: null, requete: null, parler }
          : { source: 'image', image: img ? { media_type: img.media_type, data: img.data } : null, requete: texte || null, parler }
    setEnCours({ quoi, depuis: Date.now() })
    setRefus(null)
    setResultat(null)
    try {
      const r: Comparaison = await api.post('/api/achats/comparer', corps)
      if (vivant.current) setResultat(r)
    } catch (err) {
      if (!vivant.current) return
      const x = lireRefus(err)
      if (!x) return
      const description = err instanceof ApiError && err.detail && typeof err.detail === 'object' && typeof err.detail.description === 'string' ? err.detail.description : null
      const configurer = err instanceof ApiError && err.status === 409 && /pas configurée/i.test(err.message)
      setRefus({ ...x, description, reessayer: () => comparer(quoi, img), configurer })
    } finally {
      if (vivant.current) setEnCours(null)
    }
  }

  const choisirImage = async (): Promise<void> => {
    if (enCours) return
    if (!exigerLunettes('Comparer les prix')) return
    try {
      const img = await window.iris.pickImage()
      if (!img) return
      setImage(img)
      comparer('image', img)
    } catch (err) {
      toast(messageErreur(err), 'error')
    }
  }

  const offres = resultat ? [...resultat.offres].sort((a, b) => a.prix - b.prix) : []
  const prixVu = resultat?.produit?.prix_vu ?? null
  const secondes = enCours ? Math.max(0, Math.round((tic - enCours.depuis) / 1000)) : 0

  return (
    <div className="ecran">
      <TopBar titre="Comparer les prix" />
      <div className="contenu">
        {absentes ? <CarteLunettesRequises fonction="Comparer les prix" /> : null}

        {/* ------------------------------------------------------------ demande */}
        <div className="carte col" style={{ gap: 12 }}>
          <form
            className="recherche"
            onSubmit={(e) => {
              e.preventDefault()
              comparer('nom')
            }}
          >
            <IcoRecherche />
            <input aria-label="Nom du produit" placeholder="Ex. : grille-pain Breville 4 tranches" value={requete} maxLength={200} onChange={(e) => setRequete(e.target.value)} />
          </form>
          <Holo disabled={Boolean(enCours)} onClick={() => comparer('nom')}>
            <IcoRecherche /> {enCours?.quoi === 'nom' ? 'Recherche…' : 'Chercher les prix'}
          </Holo>
          <div className="q-grille-2">
            <Holo taille="petit" variante="sombre" disabled={Boolean(enCours)} onClick={choisirImage}>
              <IcoImage /> {enCours?.quoi === 'image' ? 'Identification…' : 'Choisir une image'}
            </Holo>
            <Holo taille="petit" variante="sombre" disabled={Boolean(enCours)} onClick={() => comparer('lunettes')}>
              <IcoCamera /> {enCours?.quoi === 'lunettes' ? 'Photo en cours…' : 'Photo des lunettes'}
            </Holo>
          </div>
          {image ? (
            <div className="row wrap" style={{ gap: 8 }}>
              <span className="small" style={{ fontWeight: 700 }}>Image : {image.name}</span>
              <button type="button" className="btn sm ghost" onClick={() => setImage(null)} aria-label="Oublier l’image choisie">
                <IcoFermer width={16} height={16} /> Oublier
              </button>
            </div>
          ) : null}
          <div className="row between" style={{ gap: 12 }}>
            <span style={{ fontWeight: 600 }}>Lire le résumé à voix haute</span>
            <Toggle on={parler} onChange={setParler} titre="Lire le résumé à voix haute" />
          </div>
          <div className="q-note">
            Avec une photo, IRIS lit le nom, la marque, le format, le code-barres et le prix affiché s’ils sont lisibles ; le texte tapé sert
            alors de précision. La caméra des lunettes n’est pas encore activée dans IRIS (protocole en cours de confirmation) : en attendant,
            choisissez une photo prise avec votre téléphone.
          </div>
          {enCours ? (
            <div className="col" style={{ gap: 6 }} aria-live="polite">
              <div style={{ fontWeight: 700 }}>
                {enCours.quoi === 'nom' ? 'Recherche en ligne…' : 'Identification du produit, puis recherche en ligne…'}{' '}
                <span className="muted">{dureeLisible(secondes)}</span>
              </div>
              <div className="progress indet"><div /></div>
            </div>
          ) : null}
          {refus ? (
            <>
              <BlocRefus refus={refus} onFermer={() => setRefus(null)} onReessayer={refus.reessayer} />
              {refus.configurer ? (
                <Holo taille="petit" variante="blanc" style={{ alignSelf: 'flex-start' }} onClick={() => nav.ouvrir('reglages-pc')}>
                  Configurer la recherche web
                </Holo>
              ) : null}
              {refus.description ? (
                <div className="q-note">Ce que la photo montre selon IRIS : {refus.description}</div>
              ) : null}
            </>
          ) : null}
        </div>

        {/* ------------------------------------------------------------ résultats */}
        {resultat ? (
          <div className="col" style={{ gap: 14 }} aria-live="polite">
            <div className="q-avertissement-fort" role="note">
              <IcoAvertissement />
              <span>{resultat.avertissement}</span>
            </div>

            <div className="carte col q-produit" style={{ gap: 8 }}>
              <div className="nom">{resultat.produit.nom || 'Produit'}</div>
              <div className="q-meta">
                {resultat.produit.marque ? <span>Marque : {resultat.produit.marque}</span> : null}
                {resultat.produit.format ? <span>Format : {resultat.produit.format}</span> : null}
                {resultat.produit.code_barres ? <span>Code-barres lu : {resultat.produit.code_barres}</span> : null}
                {prixVu !== null ? <span>Prix vu sur place : {formatMontant(prixVu, 'CAD')}</span> : null}
              </div>
              {resultat.description ? (
                <details>
                  <summary className="small muted" style={{ cursor: 'pointer' }}>Ce que la photo montre selon IRIS</summary>
                  <div className="q-note" style={{ marginTop: 6 }}>{resultat.description}</div>
                </details>
              ) : null}
              <div style={{ fontSize: 17, fontWeight: 600, lineHeight: 1.45 }}>{resultat.resume}</div>
            </div>

            <div className="carte col" style={{ gap: 4 }}>
              <h3 style={{ margin: 0 }}>{offres.length ? `${pluriel(offres.length, 'prix trouvé', 'prix trouvés')} en ligne` : 'Aucun prix trouvé'}</h3>
              {offres.length === 0 ? (
                <VideCompact
                  glyphe="etiquette"
                  texte="Rien de comparable au Canada"
                  petit="Aucun extrait de résultat ne donnait un prix en dollars canadiens pour ce produit. Essayez un nom plus précis (marque, format)."
                />
              ) : (
                <div className="q-offres">
                  {offres.map((o, i) => {
                    const ecart = prixVu !== null ? Math.round((o.prix - prixVu) * 100) / 100 : null
                    return (
                      <div key={`${o.url}-${i}`} className={`q-offre ${i === 0 && offres.length > 1 ? 'plus-bas' : ''}`}>
                        <div className="haut">
                          <span className="marchand">
                            {o.marchand}
                            {i === 0 && offres.length > 1 ? <span className="pill ok" style={{ marginLeft: 8 }}>Le plus bas trouvé</span> : null}
                          </span>
                          <span className="prix">{formatMontant(o.prix, o.devise || 'CAD')}</span>
                        </div>
                        {ecart !== null && ecart !== 0 ? (
                          <div className="q-note">
                            {ecart < 0 ? `${formatMontant(-ecart, 'CAD')} de moins` : `${formatMontant(ecart, 'CAD')} de plus`} que le prix vu sur place
                          </div>
                        ) : null}
                        {o.extrait ? <div className="extrait">« {o.extrait} »</div> : null}
                        <div className="row between" style={{ gap: 10 }}>
                          <span className="hote">{hote(o.url)}</span>
                          <Holo taille="mini" variante="sombre" onClick={() => window.iris.openExternal(o.url)}>
                            <IcoLien /> Voir la page
                          </Holo>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
              <div className="q-meta" style={{ marginTop: 8 }}>
                <span className="etiquette-locale moteur">Recherche en ligne</span>
                {typeof resultat.recherches === 'number' ? <span>{pluriel(resultat.recherches, 'recherche faite', 'recherches faites')}</span> : null}
                {resultat.ecartees ? <span>{pluriel(resultat.ecartees, 'résultat écarté', 'résultats écartés')} (montant incohérent, doublon d’un même marchand ou au-delà de 8 offres)</span> : null}
                {typeof resultat.duree_ms === 'number' ? <span>Durée mesurée : {dureeMesuree(resultat.duree_ms)}</span> : null}
              </div>
            </div>
          </div>
        ) : null}

        {/* ------------------------------------------------------------ limites */}
        <div className="carte">
          <h3>Ce qu’il faut savoir</h3>
          <ul className="liste-limites">
            <li>Les prix viennent d’extraits de résultats de recherche : ils peuvent dater de quelques jours, et le prix comme le stock en magasin peuvent différer. Vérifiez sur la page du marchand.</li>
            <li>Seuls les prix en dollars canadiens sont gardés (marchand canadien connu, site en .ca ou mention CAD) ; les rabais, prix barrés, frais de livraison et prix au kilo sont ignorés.</li>
            <li>La recherche quitte l’ordinateur, avec votre accord « Texte de vos demandes » ; une photo passe d’abord par la vision d’IRIS, qui demande l’accord « Images jointes » avant d’envoyer l’image au moteur VELA. Rien n’est conservé.</li>
            <li>
              La comparaison exige que la recherche web soit configurée sur cet ordinateur (
              <button type="button" className="btn sm ghost" style={{ display: 'inline', padding: '0 4px' }} onClick={() => nav.ouvrir('reglages-pc')}>
                Contrôle de l’ordinateur › Moteur avancé › Clé de recherche web
              </button>
              ) ; elle ne marche ni en mode 100 % local, ni en mode confidentiel.
            </li>
          </ul>
        </div>
      </div>
    </div>
  )
}
