import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Holo, Segmente, TopBar } from '../components/ui'
import { IcoActualiser, IcoCamera, IcoCapture, IcoCopier, IcoLecture, IcoLien, IcoStop } from '../components/icons'
import { CarteLunettesRequises } from '../components/LunettesRequises'
import { api, ApiError, estLunettesRequises, messageErreur, refusConsentement, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import { CarteConsentement } from './AccessibiliteScreen'
import './AccessibiliteScreen.css'
import './VisionPartageeScreen.css'

/* =========================================================================
   « Vision partagée » : un proche voit ce que vous voyez, par un lien.

   L'écran montre ce que le service fait (backend/iris/partage.py) : IRIS crée
   une session sur le relais VELA, envoie des images JPEG, et la personne qui a
   le lien les regarde dans son navigateur. Les chiffres affichés (spectateurs,
   images envoyées, cadence) sont ceux que le service MESURE ; la note, les
   limites et la raison d'arrêt sont les siennes, affichées telles quelles.

   Les lunettes n'ont pas de flux vidéo : une photo par Bluetooth, puis une
   autre. L'écran le dit AVANT le bouton Démarrer, pas après une déception.
   Le partage ne démarre jamais à la voix (choix du service) : seul ce bouton,
   ou IRIS sur le téléphone, peut diffuser une caméra ou un écran.
   ========================================================================= */

interface MessageProche {
  texte: string
  ts: string
}

interface EtatPartage {
  actif: boolean
  code: string | null
  url_spectateur: string | null
  source: string | null
  spectateurs: number
  images_envoyees: number
  fps_reel: number
  expire_a: string | null
  expire_dans_s: number | null
  intervalle_s: number | null
  emetteur_connecte: boolean
  images_refusees: number
  octets_envoyes: number | null
  derniere_image_il_y_a_s: number | null
  cadence_texte: string | null
  messages: MessageProche[]
  raison: string | null
  note: string | null
  limites: string[]
  local: boolean
}

type Source = 'lunettes' | 'ecran'
type Cadence = 'fluide' | 'econome' | 'tres_econome'

const SPECTATEURS_MAX = 3
const CLE_SOURCE = 'iris.partage.source'

/** Intervalle demandé entre deux captures d'écran (le service le borne de 0,2 à 5 s). C'est une VISÉE :
 *  la cadence réelle dépend de la machine et du réseau, et elle est mesurée plus bas. */
const CADENCES: { id: Cadence; label: string; intervalle: number; sous: string }[] = [
  { id: 'fluide', label: 'Fluide', intervalle: 0.33, sous: 'vise environ 3 images par seconde' },
  { id: 'econome', label: 'Économe', intervalle: 1, sous: 'vise 1 image par seconde' },
  { id: 'tres_econome', label: 'Très économe', intervalle: 3, sous: 'vise 1 image toutes les 3 secondes' }
]

const SOURCES: { id: Source; nom: string; sous: string }[] = [
  {
    id: 'ecran',
    nom: 'Écran de l’ordinateur',
    sous: 'L’écran principal, tel qu’il s’affiche, quelques images par seconde. Tout ce qui y apparaît est visible, notifications comprises.'
  },
  {
    id: 'lunettes',
    nom: 'Lunettes',
    sous: 'La caméra des lunettes n’est pas encore activée dans IRIS (protocole en cours de confirmation) : ce partage est refusé pour l’instant. Même activée, pas de vidéo : une photo par Bluetooth, envoyée, puis une autre, toutes les quelques secondes.'
  }
]

// Par défaut, l'écran : la caméra des lunettes n'est pas encore activée par le service (protocole non confirmé).
// Un choix explicite des lunettes, gardé sur cet ordinateur, est respecté.
function lireSource(): Source {
  try {
    return window.localStorage.getItem(CLE_SOURCE) === 'lunettes' ? 'lunettes' : 'ecran'
  } catch {
    return 'ecran'
  }
}

function ecrireSource(source: Source): void {
  try {
    window.localStorage.setItem(CLE_SOURCE, source)
  } catch {
    /* stockage indisponible : le choix vaut pour cette visite seulement */
  }
}

/** « ABCD EFGH » : un code de 8 caractères se lit et se dicte mieux en deux groupes. */
function codeLisible(code: string | null): string {
  if (!code) return ''
  return code.length === 8 ? `${code.slice(0, 4)} ${code.slice(4)}` : code
}

function duree(s: number): string {
  const total = Math.max(0, Math.round(s))
  const m = Math.floor(total / 60)
  const r = total % 60
  return m > 0 ? `${m} min ${String(r).padStart(2, '0')} s` : `${r} s`
}

function nombre(n: number, decimales = 1): string {
  return n.toLocaleString('fr-CA', { minimumFractionDigits: decimales, maximumFractionDigits: decimales })
}

function tailleDonnees(octets: number): string {
  if (octets >= 1_000_000) return `${nombre(octets / 1_000_000)} Mo`
  return `${Math.max(0, Math.round(octets / 1000))} Ko`
}

function heureMessage(ts: string): string {
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('fr-CA', { hour: '2-digit', minute: '2-digit' })
}

function libelleSource(source: string | null): string {
  if (source === 'lunettes') return 'la caméra des lunettes'
  if (source === 'ecran') return 'l’écran de l’ordinateur'
  if (source === 'telephone') return 'la caméra du téléphone'
  return 'une source inconnue'
}

export function VisionPartageeScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { settings, toast, presence, exigerLunettes, setConsent } = useStore()
  const [etat, setEtat] = useState<EtatPartage | null>(null)
  const [recuA, setRecuA] = useState(() => Date.now())
  const [maintenant, setMaintenant] = useState(() => Date.now())
  const [erreurEtat, setErreurEtat] = useState('')
  const [source, setSource] = useState<Source>(lireSource)
  const [cadence, setCadence] = useState<Cadence>('fluide')
  const [occupe, setOccupe] = useState<'demarrer' | 'arreter' | 'prolonger' | null>(null)
  const [erreur, setErreur] = useState<{ texte: string; source: Source | null; statut: number } | null>(null)
  const [refus, setRefus] = useState<{ data_type: string; label: string; message: string } | null>(null)
  const [messages, setMessages] = useState<MessageProche[]>([])
  const zoneCode = useRef<HTMLDivElement>(null)

  const absentes = presence !== null && !presence.presentes
  const actif = Boolean(etat?.actif)

  const appliquer = useCallback((e: EtatPartage): void => {
    setEtat(e)
    setRecuA(Date.now())
    // Les messages vivent en mémoire vive du service et disparaissent à l'arrêt : on suit sa liste.
    setMessages(Array.isArray(e.messages) ? e.messages : [])
  }, [])

  const charger = useCallback(async (): Promise<void> => {
    try {
      appliquer(await api.get<EtatPartage>('/api/partage/etat'))
      setErreurEtat('')
    } catch (err) {
      setErreurEtat(messageErreur(err))
    }
  }, [appliquer])

  useEffect(() => {
    charger().catch(() => undefined)
    return api.on((e: IrisEvent) => {
      if (e.type === 'partage.etat') {
        const { type: _t, ...reste } = e
        if (typeof reste.actif === 'boolean') appliquer(reste as EtatPartage)
      } else if (e.type === 'partage.message' && typeof e.texte === 'string') {
        const m: MessageProche = { texte: e.texte, ts: String(e.ts || new Date().toISOString()) }
        setMessages((prec) => (prec.some((x) => x.texte === m.texte && x.ts === m.ts) ? prec : [...prec, m].slice(-20)))
      } else if (e.type === 'ws.open') {
        // Liaison rétablie : ce qui a changé pendant la coupure (fin du partage, spectateurs).
        charger().catch(() => undefined)
      }
    })
  }, [charger, appliquer])

  // Le service publie son état toutes les 5 s pendant un partage ; la relecture couvre une liaison coupée,
  // et l'horloge locale fait défiler le temps restant entre deux mesures.
  useEffect(() => {
    if (!actif) return
    const relire = window.setInterval(() => charger().catch(() => undefined), 5000)
    const horloge = window.setInterval(() => setMaintenant(Date.now()), 1000)
    return () => {
      window.clearInterval(relire)
      window.clearInterval(horloge)
    }
  }, [actif, charger])

  const choisirSource = (s: Source): void => {
    if (actif) return
    setSource(s)
    ecrireSource(s)
    setErreur(null)
  }

  const demarrer = async (): Promise<void> => {
    if (!exigerLunettes('Vision partagée')) return
    setOccupe('demarrer')
    setErreur(null)
    setRefus(null)
    try {
      const intervalle = source === 'ecran' ? CADENCES.find((c) => c.id === cadence)?.intervalle ?? null : null
      await api.post('/api/partage/demarrer', { source, intervalle_s: intervalle })
      await charger()
      window.setTimeout(() => zoneCode.current?.focus(), 50)
    } catch (err) {
      if (estLunettesRequises(err)) return
      const c = refusConsentement(err)
      if (c) setRefus(c)
      else setErreur({ texte: messageErreur(err), source, statut: err instanceof ApiError ? err.status : 0 })
    } finally {
      setOccupe(null)
    }
  }

  const arreter = async (): Promise<void> => {
    setOccupe('arreter')
    setErreur(null)
    try {
      appliquer(await api.post<EtatPartage>('/api/partage/arreter'))
    } catch (err) {
      setErreur({ texte: messageErreur(err), source: null, statut: err instanceof ApiError ? err.status : 0 })
    } finally {
      setOccupe(null)
    }
  }

  const prolonger = async (): Promise<void> => {
    setOccupe('prolonger')
    setErreur(null)
    try {
      appliquer(await api.post<EtatPartage>('/api/partage/prolonger'))
      toast('Partage prolongé.', 'success')
    } catch (err) {
      setErreur({ texte: messageErreur(err), source: null, statut: err instanceof ApiError ? err.status : 0 })
    } finally {
      setOccupe(null)
    }
  }

  const copier = (texte: string, quoi: string): void => {
    navigator.clipboard
      .writeText(texte)
      .then(() => toast(`${quoi} copié.`, 'success'))
      .catch(() => toast('Impossible de copier : sélectionnez le texte à la main.', 'error'))
  }

  const restantS = etat?.expire_dans_s !== null && etat?.expire_dans_s !== undefined ? Math.max(0, etat.expire_dans_s - (maintenant - recuA) / 1000) : null
  const bientotExpire = restantS !== null && restantS <= 120
  const limites = etat?.limites?.length ? etat.limites : []
  const mot: string = settings?.wake_word || 'Dis-moi Iris'
  const sourceChoisie = SOURCES.find((s) => s.id === source) || SOURCES[0]

  return (
    <div className="ecran">
      <TopBar titre="Vision partagée" />
      <div className="contenu">
        {absentes && !actif ? <CarteLunettesRequises fonction="Vision partagée" /> : null}

        <div className="vp-hero">
          <h2>Montrez à un proche ce que vous avez devant vous</h2>
          <p>
            IRIS envoie des images au relais VELA ; la personne à qui vous donnez le lien les regarde dans son navigateur et peut vous écrire. Ses messages
            vous sont lus à voix haute.
          </p>
        </div>

        {erreurEtat ? <div className="bloc-note erreur" role="alert">{erreurEtat}</div> : null}

        {actif && etat ? (
          <>
            {/* ------------------------------------------------------------ partage en cours */}
            <div className="carte col vp-actif" style={{ gap: 14 }}>
              <div className="row between wrap" style={{ gap: 8 }}>
                <div className="vp-direct" aria-live="polite">
                  <span className="dot rec" aria-hidden="true" /> Partage en cours depuis {libelleSource(etat.source)}
                </div>
                {etat.source !== 'telephone' && !etat.emetteur_connecte ? <span className="pill warn">liaison au relais en reprise</span> : null}
              </div>

              <div className="vp-code" ref={zoneCode} tabIndex={-1} aria-label={`Code du partage : ${(etat.code || '').split('').join(' ')}`}>
                <span className="etiquette">Code</span>
                <span className="valeur">{codeLisible(etat.code)}</span>
              </div>

              {etat.url_spectateur ? (
                <div className="vp-lien">
                  <span className="etiquette">Lien à donner à votre proche</span>
                  <span className="url" lang="en">{etat.url_spectateur}</span>
                  <div className="row wrap" style={{ gap: 8 }}>
                    <Holo taille="petit" variante="blanc" onClick={() => copier(etat.url_spectateur || '', 'Lien')}>
                      <IcoCopier /> Copier le lien
                    </Holo>
                    <Holo taille="petit" variante="contour" onClick={() => copier(etat.code || '', 'Code')}>
                      Copier le code
                    </Holo>
                  </div>
                  <div className="small muted" style={{ lineHeight: 1.45 }}>
                    Le code est la fin du lien. Au téléphone, dictez l’adresse complète : la page ne demande pas de code seul.
                  </div>
                </div>
              ) : null}

              <div className="vp-mesures" role="group" aria-label="Mesures du partage">
                <div className="mesure">
                  <span className="chiffre">
                    {etat.spectateurs}
                    <small> / {SPECTATEURS_MAX}</small>
                  </span>
                  <span className="libelle">{etat.spectateurs === 0 ? 'personne ne regarde encore' : etat.spectateurs === 1 ? 'personne regarde' : 'personnes regardent'}</span>
                </div>
                <div className="mesure">
                  <span className="chiffre">{etat.images_envoyees}</span>
                  <span className="libelle">images envoyées</span>
                </div>
                <div className="mesure large">
                  <span className="chiffre petit">{etat.cadence_texte || (etat.images_envoyees < 2 ? 'mesure en cours…' : 'aucune image récente')}</span>
                  <span className="libelle">cadence réelle, sur les 30 dernières secondes</span>
                </div>
              </div>

              <div className="vp-details small muted">
                {typeof etat.derniere_image_il_y_a_s === 'number' ? <span>Dernière image : il y a {nombre(etat.derniere_image_il_y_a_s)} s</span> : null}
                {typeof etat.octets_envoyes === 'number' ? <span>Données envoyées : {tailleDonnees(etat.octets_envoyes)}</span> : null}
                {etat.images_refusees > 0 ? <span>Images refusées par le relais : {etat.images_refusees}</span> : null}
                {restantS !== null ? <span className={bientotExpire ? 'vp-alerte' : ''}>Le lien expire dans {duree(restantS)}</span> : null}
              </div>

              {etat.raison ? <div className="bloc-note attention">{etat.raison}</div> : null}
              {etat.note ? <div className="bloc-note">{etat.note}</div> : null}

              <div className="col" style={{ gap: 10 }}>
                <Holo variante="rouge" disabled={occupe !== null} onClick={arreter}>
                  <IcoStop /> {occupe === 'arreter' ? 'Arrêt…' : 'Arrêter le partage'}
                </Holo>
                <Holo variante={bientotExpire ? 'blanc' : 'contour'} taille="petit" disabled={occupe !== null} onClick={prolonger}>
                  <IcoActualiser /> {occupe === 'prolonger' ? 'Prolongation…' : 'Prolonger de 30 minutes'}
                </Holo>
              </div>
              <div className="small muted" style={{ lineHeight: 1.45 }}>
                À la voix : « {mot}, arrête le partage », « {mot}, prolonge le partage » ou « {mot}, qui regarde ? ».
              </div>
            </div>

            {/* ------------------------------------------------------------ messages du proche */}
            <div className="carte col" style={{ gap: 10 }}>
              <h3 style={{ margin: 0 }}>Messages de votre proche</h3>
              {messages.length === 0 ? (
                <div className="muted" style={{ fontWeight: 600, lineHeight: 1.45 }}>Aucun message pour l’instant.</div>
              ) : (
                <ul className="vp-messages" role="log" aria-live="polite" aria-label="Messages de votre proche">
                  {messages.map((m) => (
                    <li key={`${m.ts}|${m.texte}`}>
                      <span className="heure">{heureMessage(m.ts)}</span>
                      <span className="texte">{m.texte}</span>
                    </li>
                  ))}
                </ul>
              )}
              <div className="small muted" style={{ lineHeight: 1.45 }}>
                {etat.source === 'telephone'
                  ? 'Ce partage vient du téléphone : c’est lui qui lit les messages à voix haute.'
                  : 'Chaque message est lu à voix haute par IRIS. Ils ne sont pas conservés : la liste s’efface à l’arrêt du partage.'}
              </div>
            </div>
          </>
        ) : (
          <>
            {/* ------------------------------------------------------------ préparer un partage */}
            <div className="carte col" style={{ gap: 12 }}>
              <h3 style={{ margin: 0 }}>Ce que votre proche verra</h3>
              <div className="vp-sources" role="radiogroup" aria-label="Source des images">
                {SOURCES.map((s) => (
                  <button key={s.id} type="button" role="radio" aria-checked={s.id === source} className="vp-source" onClick={() => choisirSource(s.id)}>
                    <span className="icone">{s.id === 'lunettes' ? <IcoCamera /> : <IcoCapture />}</span>
                    <span className="corps">
                      <span className="nom">{s.nom}</span>
                      <span className="sous">{s.sous}</span>
                    </span>
                  </button>
                ))}
              </div>
              <div className="small muted" style={{ lineHeight: 1.45 }}>
                La caméra du téléphone se partage depuis IRIS sur le téléphone ; ses images sont plus fluides que celles des lunettes.
              </div>

              {source === 'ecran' ? (
                <div className="col" style={{ gap: 8 }}>
                  <span className="vp-etiquette">Cadence de l’écran</span>
                  <Segmente<Cadence> options={CADENCES.map((c) => ({ id: c.id, label: c.label }))} valeur={cadence} onChange={setCadence} />
                  <div className="small muted" style={{ lineHeight: 1.45 }}>
                    {CADENCES.find((c) => c.id === cadence)?.sous} ; la cadence réelle dépend de l’ordinateur et du réseau, et elle est mesurée pendant le partage.
                    Moins d’images, c’est moins de données envoyées.
                  </div>
                </div>
              ) : null}
            </div>

            {etat && !etat.actif && etat.raison ? <div className="bloc-note" aria-live="polite">{etat.raison}</div> : null}

            <div className="col" style={{ gap: 10 }}>
              <Holo disabled={occupe !== null || !etat} onClick={demarrer}>
                <IcoLecture /> {occupe === 'demarrer' ? 'Démarrage…' : `Démarrer le partage (${sourceChoisie.nom.toLowerCase()})`}
              </Holo>
              {occupe === 'demarrer' && source === 'lunettes' ? (
                <div className="small muted" aria-live="polite">
                  IRIS prend d’abord une photo avec les lunettes : le lien n’est créé qu’une fois cette photo reçue, ce qui peut prendre plusieurs secondes.
                </div>
              ) : null}
              <div className="small muted" style={{ lineHeight: 1.45 }}>
                Le partage ne se démarre pas à la voix : une phrase mal comprise ne doit pas diffuser votre caméra ou votre écran.
              </div>
            </div>
          </>
        )}

        {erreur ? (
          <div className="bloc-note erreur" role="alert">
            {erreur.texte}
            {erreur.source === 'lunettes' && erreur.statut === 409 ? (
              <div style={{ marginTop: 8, fontWeight: 500 }}>En attendant, vous pouvez partager l’écran de cet ordinateur, ou la caméra du téléphone depuis IRIS sur le téléphone.</div>
            ) : null}
          </div>
        ) : null}
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

        {/* ------------------------------------------------------------ confidentialité */}
        <div className="carte">
          <h3>Qui voit quoi</h3>
          <ul className="liste-limites">
            <li>
              <strong>Qui voit : les personnes à qui vous donnez le lien</strong>, trois au plus, tant que le partage est actif.
            </li>
            <li>Vous arrêtez quand vous voulez, par le bouton rouge ou à la voix ; le lien cesse alors de fonctionner.</li>
            {settings?.annonce_capture ? <li>IRIS dit à voix haute quand une personne se met à regarder votre partage.</li> : null}
            <li>Le témoin de capture d’IRIS (caméra ou écran) reste allumé pendant tout le partage.</li>
          </ul>
        </div>

        <div className="carte">
          <h3>Ce qu’il faut savoir</h3>
          <ul className="liste-limites">
            {limites.length ? (
              limites.map((l, i) => <li key={i}>{l}</li>)
            ) : (
              <>
                <li>Ce n’est pas une vidéo en direct : chaque image arrive avec du retard, parfois plusieurs secondes.</li>
                <li>Le partage exige Internet, sur cet ordinateur comme chez la personne qui regarde.</li>
              </>
            )}
            <li>Depuis les lunettes, la cadence dépend du Bluetooth : elle est mesurée et affichée, pas promise.</li>
            <li>Le partage ne fonctionne pas en mode confidentiel ni en mode 100 % local, et s’arrête si IRIS est verrouillée.</li>
          </ul>
          <div className="row" style={{ gap: 8, marginTop: 12 }}>
            <IcoLien width={16} height={16} aria-hidden="true" />
            <span className="small muted">IRIS vous prévient à voix haute deux minutes avant l’expiration du lien.</span>
          </div>
        </div>
      </div>
    </div>
  )
}
