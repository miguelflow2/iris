import React, { useEffect, useRef, useState } from 'react'
import { CarteReglage, Holo, Liste, Rangee, Segmente, Toggle, TopBar } from '../components/ui'
import { IcoAvertissement, IcoHautParleur, IcoJournal, IcoLunettes, IcoOreille, IcoRecherche, IcoStop, IcoTelephone, IcoTraduire } from '../components/icons'
import { CarteLunettesRequises } from '../components/LunettesRequises'
import { api, estCameraNonConfirmee, estLunettesRequises, messageErreur, refusConsentement } from '../lib/api'
import { useStore } from '../lib/store'
import './AccessibiliteScreen.css'

/* =========================================================================
   « Accessibilité » : le carrefour pour les personnes aveugles, malvoyantes,
   sourdes ou malentendantes.

   - Les huit modes de description (GET /api/accessibilite/modes), chacun avec
     sa limite en une phrase, telle que le service la donne ;
   - la source de l'image : caméra des lunettes, écran du PC, ou photo importée ;
   - le résultat en très grand texte, annoncé aux lecteurs d'écran, avec
     « Répéter » et « Arrêter » ;
   - « Où ai-je posé… ? », qui ne cherche que dans les souvenirs réels ;
   - les réglages rapides (débit, longueur, grand texte, annonce de capture) ;
   - les liens vers les autres fonctions, et la liste honnête de ce qui n'est
     PAS livré.

   Lunettes d'abord : décrire, c'est capter. Sans lunettes présentes, l'écran
   le dit avant tout appel ; consulter ses souvenirs reste permis.
   ========================================================================= */

interface ModeVision {
  id: string
  nom: string
  description: string
  local: boolean
  limite?: string
  phrases?: string[]
}

interface ResultatVision {
  ok: boolean
  mode: string
  source: string
  texte: string
  chemin: string | null
  duree_ms: number
  local: boolean
  note?: string | null
}

interface ImageChoisie {
  name: string
  media_type: string
  data: string
}

type Source = 'lunettes' | 'ecran' | 'image'

interface Refus {
  message: string
  consentement: { data_type: string; label: string; message: string } | null
  mode: ModeVision
  /** refus « caméra des lunettes pas encore activée » : on propose les deux sources qui marchent */
  camera: boolean
}

const CLE_SOURCE = 'iris.accessibilite.source'
// Lu aussi par le process principal (electron/main/index.ts, lireChoixRetenir) : Ctrl+Maj+D suit ce choix quand
// la caméra des lunettes est activée par le service (sinon le raccourci ne prend aucune photo : electron/main/decrire.ts).
const CLE_RETENIR = 'iris.accessibilite.retenir'
const TTS_NORMAL = 185
const TTS_MIN = 90
const TTS_MAX = 555

const SOURCES: { id: Source; label: string }[] = [
  { id: 'lunettes', label: 'Lunettes' },
  { id: 'ecran', label: 'Écran du PC' },
  { id: 'image', label: 'Image importée' }
]

const NOTE_SOURCE: Record<Source, string> = {
  lunettes:
    'La caméra des lunettes n’est pas encore activée dans IRIS (protocole en cours de confirmation) : pour l’instant, une description demandée avec cette source est refusée. En attendant, importez une photo prise avec votre téléphone (Image importée) ou décrivez l’écran du PC. Même activée, la caméra prendra une photo en quelques secondes, jamais de vidéo en direct.',
  ecran: 'Capture de l’écran de cet ordinateur au moment où vous choisissez un mode.',
  image: 'Une photo choisie sur cet ordinateur, par exemple prise avec votre téléphone.'
}

/** Ce qui n'est pas livré, dit tel quel (contrat de lancement du 2026-09-13). */
export const LIMITES_ACCESSIBILITE: string[] = [
  'Chaque description vient d’une photo prise il y a quelques secondes : ce n’est ni une surveillance en direct, ni une garantie de sécurité.',
  'Pas d’alerte d’obstacle en temps réel depuis les lunettes : elles n’envoient pas de flux vidéo par Bluetooth, et il faudrait un traitement embarqué dans les lunettes.',
  'Pas de reconnaissance des personnes par leur nom : ce sont des données biométriques, qui exigeraient un consentement exprès et une déclaration préalable à la Commission d’accès à l’information du Québec. IRIS décrit les personnes sans les identifier.',
  'Pas de langue des signes.',
  'Pas d’enregistrement vidéo, de mise à jour du micrologiciel ni d’effacement de la mémoire interne des lunettes : le fabricant ne documente pas ce protocole.',
  'L’empreinte vocale (verrou vocal) n’est pas encore offerte : au Québec, la vérification d’identité par la voix et la banque d’empreintes doivent être déclarées à la Commission d’accès à l’information au moins 60 jours avant leur mise en service, et VELA ne l’a pas encore fait. Elle exigera ensuite votre consentement exprès.'
]

// Par défaut, une photo importée : la caméra des lunettes n'est pas encore activée par le service (protocole non
// confirmé), et un premier essai qui aboutit à un refus n'apprend rien à personne. Un choix explicite est respecté.
function lireSource(): Source {
  try {
    const v = window.localStorage.getItem(CLE_SOURCE)
    return v === 'ecran' || v === 'image' || v === 'lunettes' ? v : 'image'
  } catch {
    return 'image'
  }
}

function lireRetenir(): boolean {
  try {
    return window.localStorage.getItem(CLE_RETENIR) !== 'false'
  } catch {
    return true
  }
}

function ecrireRetenir(v: boolean): void {
  try {
    window.localStorage.setItem(CLE_RETENIR, v ? 'true' : 'false')
  } catch {
    /* stockage indisponible : le choix vaut pour cette visite, et le raccourci ne retient rien */
  }
}

function ecrireSource(v: Source): void {
  try {
    window.localStorage.setItem(CLE_SOURCE, v)
  } catch {
    /* stockage indisponible : le choix vaut pour cette visite */
  }
}

/** « 2,0× » : le débit tel qu'un utilisateur de lecteur d'écran le règle. */
export function formatFacteur(f: number): string {
  return `${f.toFixed(1).replace('.', ',')}×`
}

export function secondes(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return ''
  return `${(ms / 1000).toFixed(1).replace('.', ',')} s`
}

/** Carte de refus de consentement : dit ce qui serait envoyé, et laisse accorder puis réessayer. */
export function CarteConsentement({
  refus,
  onAutoriser,
  onFermer
}: {
  refus: { data_type: string; label: string; message: string }
  onAutoriser: () => void
  onFermer: () => void
}): JSX.Element {
  const { consent } = useStore()
  const description: string = consent?.[refus.data_type]?.description || ''
  return (
    <div className="carte col" style={{ gap: 10 }} role="alert">
      <h3 style={{ margin: 0 }}>Votre accord est nécessaire</h3>
      <div className="desc">{refus.message}</div>
      {description ? <div className="small muted" style={{ lineHeight: 1.45 }}>{description}</div> : null}
      <div className="small muted">Rien n’a été envoyé. Vous pourrez retirer cet accord dans Mon profil › Confidentialité.</div>
      <div className="row wrap" style={{ gap: 8 }}>
        <Holo taille="petit" variante="blanc" onClick={onAutoriser}>Autoriser « {refus.label} » et réessayer</Holo>
        <Holo taille="petit" variante="contour" onClick={onFermer}>Pas maintenant</Holo>
      </div>
    </div>
  )
}

export function AccessibiliteScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { nav, settings, updateSettings, toast, presence, exigerLunettes, setConsent } = useStore()
  const [modes, setModes] = useState<ModeVision[]>([])
  const [erreurModes, setErreurModes] = useState('')
  const [source, setSourceEtat] = useState<Source>(lireSource)
  const [image, setImage] = useState<ImageChoisie | null>(null)
  const [retenir, setRetenirEtat] = useState<boolean>(lireRetenir)
  const [enCours, setEnCours] = useState<string | null>(null)
  const [resultat, setResultat] = useState<ResultatVision | null>(null)
  const [refus, setRefus] = useState<Refus | null>(null)
  const [question, setQuestion] = useState('')
  const [ouEst, setOuEst] = useState<{ reponse: string; souvenirs: { id: string; texte: string; date: string }[]; local: boolean } | null>(null)
  const [ouEstEnCours, setOuEstEnCours] = useState(false)
  const [facteur, setFacteur] = useState<number>(() => (Number(settings?.tts_rate) || TTS_NORMAL) / TTS_NORMAL)
  const zoneResultat = useRef<HTMLDivElement>(null)

  const absentes = presence !== null && !presence.presentes

  useEffect(() => {
    let vivant = true
    api
      .get('/api/accessibilite/modes')
      .then((r) => {
        if (vivant) setModes(Array.isArray(r?.modes) ? r.modes : [])
      })
      .catch((err) => {
        if (vivant) setErreurModes(messageErreur(err))
      })
    return () => {
      vivant = false
    }
  }, [])

  // Le débit peut changer ailleurs (Réglages › Voix, téléphone) : le curseur suit.
  useEffect(() => {
    setFacteur((Number(settings?.tts_rate) || TTS_NORMAL) / TTS_NORMAL)
  }, [settings?.tts_rate])

  const setRetenir = (v: boolean): void => {
    setRetenirEtat(v)
    ecrireRetenir(v)
  }

  const setSource = (v: Source): void => {
    setSourceEtat(v)
    ecrireSource(v)
  }

  const reglage = (patch: Record<string, unknown>): void => {
    updateSettings(patch).catch((err: unknown) => toast(messageErreur(err), 'error'))
  }

  const choisirImage = async (): Promise<ImageChoisie | null> => {
    try {
      const img = await window.iris.pickImage()
      if (img) setImage(img)
      return img
    } catch (err) {
      toast(messageErreur(err), 'error')
      return null
    }
  }

  const decrire = async (m: ModeVision): Promise<void> => {
    if (enCours) return
    if (!exigerLunettes(m.nom)) return
    const src: Source = m.id === 'ecran' ? 'ecran' : source
    let img = image
    if (src === 'image' && !img) {
      img = await choisirImage()
      if (!img) return
    }
    setEnCours(m.id)
    setRefus(null)
    try {
      const r: ResultatVision = await api.post('/api/accessibilite/decrire', {
        mode: m.id,
        source: src,
        image: src === 'image' && img ? { media_type: img.media_type, data: img.data } : null,
        parler: true,
        memoriser: retenir
      })
      setResultat(r)
      window.setTimeout(() => zoneResultat.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
    } catch (err) {
      // 428 : la feuille « lunettes requises » s'ouvre d'elle-même (App.tsx).
      if (estLunettesRequises(err)) return
      const c = refusConsentement(err)
      setRefus({ message: c ? c.message : messageErreur(err), consentement: c, mode: m, camera: src === 'lunettes' && estCameraNonConfirmee(err) })
    } finally {
      setEnCours(null)
    }
  }

  const repeter = (): void => {
    if (!resultat?.texte) return
    if (!exigerLunettes('Répéter la description')) return
    api.post('/api/voice/say', { text: resultat.texte }).catch((err) => {
      if (!estLunettesRequises(err)) toast(messageErreur(err), 'error')
    })
  }
  const arreter = (): void => {
    // Arrêter la voix ne dépend jamais des lunettes : couper le son doit toujours marcher.
    api.post('/api/voice/stop_speaking').catch((err) => toast(messageErreur(err), 'error'))
  }

  const chercher = async (): Promise<void> => {
    const q = question.trim()
    if (!q || ouEstEnCours) return
    setOuEstEnCours(true)
    try {
      setOuEst(await api.post('/api/accessibilite/ou-est', { question: q }))
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      setOuEstEnCours(false)
    }
  }

  const engagerDebit = (): void => {
    const rate = Math.min(TTS_MAX, Math.max(TTS_MIN, Math.round(TTS_NORMAL * facteur)))
    if (rate !== Number(settings?.tts_rate)) reglage({ tts_rate: rate })
  }
  const ecouterDebit = (): void => {
    api.post('/api/voice/say', { text: 'Voici la vitesse de ma voix. Réglez-la jusqu’à ce qu’elle vous convienne.' }).catch((err) => {
      if (!estLunettesRequises(err)) toast(messageErreur(err), 'error')
    })
  }

  const verbosite: 'concis' | 'normal' | 'descriptif' = settings?.verbosite === 'concis' || settings?.verbosite === 'descriptif' ? settings.verbosite : 'normal'

  return (
    <div className="ecran">
      <TopBar titre="Accessibilité" />
      <div className="contenu">
        {absentes ? <CarteLunettesRequises fonction="Décrire ce qui vous entoure" /> : null}

        {/* ------------------------------------------------------------ source */}
        <h2 className="section-sous">Que décrire ?</h2>
        <div className="carte col" style={{ gap: 12 }}>
          <div className="segmente-souple">
            <Segmente options={SOURCES} valeur={source} onChange={setSource} />
          </div>
          <div className="small muted" style={{ lineHeight: 1.45 }}>{NOTE_SOURCE[source]}</div>
          {source === 'image' ? (
            <div className="row wrap" style={{ gap: 10 }}>
              <span className="small" style={{ fontWeight: 700 }}>{image ? `Image : ${image.name}` : 'Aucune image choisie.'}</span>
              <Holo taille="mini" variante="sombre" onClick={() => { choisirImage() }}>{image ? 'Changer d’image' : 'Choisir une image'}</Holo>
            </div>
          ) : null}
          <div className="row between" style={{ gap: 12 }}>
            <span style={{ fontWeight: 600 }}>Retenir la description dans ma mémoire</span>
            <Toggle on={retenir} onChange={setRetenir} titre="Retenir la description dans ma mémoire" />
          </div>
          <div className="small muted" style={{ lineHeight: 1.45 }}>
            Retenue, la description sert ensuite à « Où ai-je posé… ? ». Rien n’est retenu en mode invité ou dans une zone sans mémoire.{' '}
            {presence?.camera_lunettes_active === true
              ? 'Le raccourci Ctrl+Maj+D (photo des lunettes) suit ce choix.'
              : 'Le raccourci Ctrl+Maj+D ne décrit rien pour l’instant : la caméra des lunettes n’étant pas encore activée, il le dit et ne prend aucune photo.'}
          </div>
          <div className="row between" style={{ gap: 12 }}>
            <span style={{ fontWeight: 600 }}>Garder les photos décrites</span>
            <Toggle
              on={Boolean(settings?.vision_garder_photos)}
              onChange={(v) => {
                updateSettings({ vision_garder_photos: v }).catch((err: unknown) => toast(messageErreur(err), 'error'))
              }}
              titre="Garder les photos décrites"
            />
          </div>
          <div className="small muted" style={{ lineHeight: 1.45 }}>
            Désactivé : la photo des lunettes est effacée dès qu’elle est décrite, seule la description est retenue. Activé : elle est gardée avec
            la description retenue, sur cet ordinateur, non chiffrée, jusqu’à la durée de conservation ou jusqu’à ce que vous l’effaciez de l’album.
          </div>
        </div>

        {/* ------------------------------------------------------------ modes */}
        {erreurModes ? <div className="bloc-note erreur" role="alert">{erreurModes}</div> : null}
        <div className="modes-grille">
          {modes.map((m) => (
            <button
              key={m.id}
              type="button"
              className={`carte-mode ${enCours === m.id ? 'en-cours' : ''}`}
              disabled={Boolean(enCours) && enCours !== m.id}
              aria-busy={enCours === m.id}
              aria-describedby={`mode-${m.id}-desc`}
              onClick={() => decrire(m)}
            >
              <span className="nom">{enCours === m.id ? 'Un instant…' : m.nom}</span>
              <span id={`mode-${m.id}-desc`} className="description">{m.description}</span>
              {m.limite ? <span className="limite">{m.limite}</span> : null}
              <span className={`etiquette-locale ${m.local ? 'local' : 'moteur'}`}>
                {m.local ? 'Possible sur cet ordinateur' : 'Moteur VELA, avec votre accord'}
              </span>
            </button>
          ))}
        </div>

        {refus?.consentement ? (
          <CarteConsentement
            refus={refus.consentement}
            onFermer={() => setRefus(null)}
            onAutoriser={async () => {
              const m = refus.mode
              try {
                await setConsent(refus.consentement!.data_type, true)
              } catch (err) {
                toast(messageErreur(err), 'error')
                return
              }
              setRefus(null)
              decrire(m)
            }}
          />
        ) : refus ? (
          <div className="bloc-note erreur" role="alert">
            {refus.message}
            {refus.camera ? (
              <div className="row wrap" style={{ gap: 8, marginTop: 10 }}>
                <button type="button" className="btn sm" onClick={() => { setSource('image'); setRefus(null) }}>Utiliser une image importée</button>
                <button type="button" className="btn sm" onClick={() => { setSource('ecran'); setRefus(null) }}>Décrire l’écran du PC</button>
              </div>
            ) : null}
          </div>
        ) : null}

        {/* ------------------------------------------------------------ résultat */}
        <div ref={zoneResultat} aria-live="polite" aria-atomic="true">
          {resultat ? (
            <div className="resultat-vision">
              <div className="texte">{resultat.texte}</div>
              <div className="meta">
                <span className={`etiquette-locale ${resultat.local ? 'local' : 'moteur'}`}>{resultat.local ? 'Traité sur cet ordinateur' : 'Décrit par le moteur VELA'}</span>
                <span>Durée mesurée : {secondes(resultat.duree_ms)}</span>
              </div>
              {resultat.note ? <div className="bloc-note attention" style={{ marginTop: 12 }}>{resultat.note}</div> : null}
            </div>
          ) : null}
        </div>
        {resultat ? (
          <div className="row wrap" style={{ gap: 10 }}>
            <Holo taille="petit" variante="blanc" onClick={repeter}><IcoHautParleur /> Répéter</Holo>
            <Holo taille="petit" variante="sombre" onClick={arreter}><IcoStop /> Arrêter</Holo>
          </div>
        ) : null}

        {/* ------------------------------------------------------------ où ai-je posé */}
        <h2 className="section-sous">Où ai-je posé… ?</h2>
        <div className="carte col" style={{ gap: 12 }}>
          <form
            className="recherche"
            onSubmit={(e) => {
              e.preventDefault()
              chercher()
            }}
          >
            <IcoRecherche />
            <input
              aria-label="Où ai-je posé…"
              placeholder="Où ai-je posé mes clés ?"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />
          </form>
          <Holo taille="petit" variante="sombre" disabled={!question.trim() || ouEstEnCours} onClick={chercher}>
            {ouEstEnCours ? 'Recherche…' : 'Chercher dans mes souvenirs'}
          </Holo>
          <div aria-live="polite">
            {ouEst ? (
              <div className="col" style={{ gap: 10 }}>
                <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.35 }}>{ouEst.reponse}</div>
                {ouEst.souvenirs.length ? (
                  <ul className="liste-limites">
                    {ouEst.souvenirs.map((s) => (
                      <li key={`${s.id}-${s.date}`}>
                        <span className="muted">{s.date ? new Date(s.date).toLocaleString('fr-CA', { dateStyle: 'medium', timeStyle: 'short' }) : ''} — </span>
                        {s.texte}
                      </li>
                    ))}
                  </ul>
                ) : null}
                <span className={`etiquette-locale ${ouEst.local ? 'local' : 'moteur'}`} style={{ alignSelf: 'flex-start' }}>
                  {ouEst.local ? 'Réponse formée sur cet ordinateur' : 'Formulée par le moteur VELA à partir de vos souvenirs'}
                </span>
              </div>
            ) : null}
          </div>
          <div className="small muted" style={{ lineHeight: 1.45 }}>
            IRIS cherche seulement dans ce qu’elle a décrit et retenu, ou dans ce que vous lui avez dit. L’objet a pu être déplacé depuis.
          </div>
        </div>

        {/* ------------------------------------------------------------ réglages rapides */}
        <h2 className="section-sous">Réglages rapides</h2>
        <div className="carte col" style={{ gap: 16 }}>
          <div className="curseur">
            <div className="entete">
              <label htmlFor="debit-voix">Débit de la voix</label>
              <output htmlFor="debit-voix">{formatFacteur(facteur)}</output>
            </div>
            <input
              id="debit-voix"
              type="range"
              min={0.5}
              max={3}
              step={0.1}
              value={Math.min(3, Math.max(0.5, facteur))}
              aria-valuetext={formatFacteur(facteur)}
              onChange={(e) => setFacteur(Number(e.target.value))}
              onMouseUp={engagerDebit}
              onKeyUp={engagerDebit}
              onTouchEnd={engagerDebit}
              onBlur={engagerDebit}
            />
            <div className="aide">La voix Windows avance par crans ; au-delà de 2×, la voix reste intelligible mais moins naturelle.</div>
            <Holo taille="mini" variante="sombre" style={{ alignSelf: 'flex-start' }} onClick={ecouterDebit}>
              <IcoHautParleur /> Écouter
            </Holo>
          </div>

          <div className="col" style={{ gap: 8 }}>
            <div style={{ fontWeight: 700, fontSize: 17 }}>Longueur des réponses</div>
            <div className="segmente-souple">
              <Segmente
                options={[
                  { id: 'concis', label: 'Concis' },
                  { id: 'normal', label: 'Normal' },
                  { id: 'descriptif', label: 'Descriptif' }
                ]}
                valeur={verbosite}
                onChange={(v) => reglage({ verbosite: v })}
              />
            </div>
            <div className="aide small muted">« Concis » va à l’essentiel ; « Descriptif » donne tous les détails utiles, plus longs à écouter.</div>
          </div>
        </div>
        <CarteReglage
          titre="Grand texte"
          desc="Agrandit tout le texte et les boutons de l’application."
          on={Boolean(settings?.interface_grand_texte)}
          onChange={(v) => reglage({ interface_grand_texte: v })}
        />
        <CarteReglage
          titre="Annonce de capture"
          desc="Un signal vocal court à chaque photo ou enregistrement (« Photo. »), pour savoir quand IRIS capte."
          on={settings?.annonce_capture !== false}
          onChange={(v) => reglage({ annonce_capture: v })}
        />

        {/* ------------------------------------------------------------ autres fonctions */}
        <h2 className="section-sous">Entendre et suivre</h2>
        <Liste>
          <Rangee icone={<IcoTraduire />} titre="Sous-titres en direct" sous="Ce qui se dit autour, en très grand texte, reconnu sur l’ordinateur." onClick={() => nav.ouvrir('sous-titres')} />
          <Rangee icone={<IcoAvertissement />} titre="Alertes sonores" sous="Alarme, sirène, klaxon, sonnette, coups à la porte, votre prénom." onClick={() => nav.ouvrir('alertes-sonores')} />
          <Rangee icone={<IcoOreille />} titre="Écoute assistée" sous="Expérimental : le son ambiant amplifié dans les lunettes." onClick={() => nav.ouvrir('ecoute-assistee')} />
          <Rangee icone={<IcoLunettes />} titre="Bouton des lunettes" sous="Décrire devant soi sans toucher au téléphone, si le bouton le permet." onClick={() => nav.ouvrir('bouton-lunettes')} />
          <Rangee icone={<IcoJournal />} titre="Journal de la journée" sous="Retrouver ce qui a été dit, effacer une plage." onClick={() => nav.ouvrir('journal')} />
          <Rangee icone={<IcoTelephone />} titre="Mode dehors" sous="Téléphone et lunettes, ordinateur resté à la maison." onClick={() => nav.ouvrir('mode-dehors')} />
        </Liste>

        {/* ------------------------------------------------------------ limites */}
        <h2 className="section-sous">Limites</h2>
        <div className="carte">
          <ul className="liste-limites">
            {LIMITES_ACCESSIBILITE.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
