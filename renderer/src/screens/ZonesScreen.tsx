import React, { useCallback, useEffect, useState } from 'react'
import { Field, Holo, Modal, Puces, TopBar, Vide } from '../components/ui'
import { IcoCarte, IcoPlus, IcoPoubelle } from '../components/icons'
import { api, messageErreur, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import './AccessibiliteScreen.css'
import './ZonesScreen.css'

/* =========================================================================
   « Zones sans mémoire » : dans un lieu choisi, la mémoire d'IRIS est suspendue.

   Ce que l'écran montre est ce que le service fait (backend/iris/zones.py) :
   des cercles (centre + rayon) gardés dans les réglages ; un appareil signale
   la zone où il se trouve, et la mémoire est suspendue tant qu'il n'a pas
   signalé sa sortie. La limite du service est affichée telle quelle.

   La position est une donnée sensible : l'écran ne la garde pas. Celle de
   l'ordinateur n'est lue que sur un clic (et le service n'écrit que le fait
   qu'elle a été lue) ; pour « vérifier maintenant », elle est envoyée au
   service qui la compare puis l'oublie, et l'écran ne l'affiche pas.

   Toujours accessible sans lunettes : c'est une protection de la vie privée.
   ========================================================================= */

interface Zone {
  id: string
  nom: string
  lat: number
  lon: number
  rayon_m: number
}

interface EtatZones {
  zones: Zone[]
  zone_active: { id: string; nom: string } | null
  limite?: string
}

interface PositionPc {
  lat: number
  lon: number
  precision_m: number
}

type Rayon = '50' | '150' | '300' | '500' | '1000' | 'autre'

const RAYON_MIN = 30
const RAYON_MAX = 5000
const NOM_MAX = 60
const RAYONS: { id: Rayon; label: string }[] = [
  { id: '50', label: '50 m' },
  { id: '150', label: '150 m' },
  { id: '300', label: '300 m' },
  { id: '500', label: '500 m' },
  { id: '1000', label: '1 km' },
  { id: 'autre', label: 'Autre' }
]

function nombre(n: number, decimales: number): string {
  return n.toLocaleString('fr-CA', { minimumFractionDigits: decimales, maximumFractionDigits: decimales })
}

function distance(m: number): string {
  return m >= 1000 ? `${nombre(m / 1000, m % 1000 === 0 ? 0 : 1)} km` : `${Math.round(m)} m`
}

/** Un nombre écrit à la française (virgule) ou à l'anglaise (point). */
function lireNombre(texte: string): number | null {
  // Le signe moins typographique (U+2212) arrive parfois d'un copier-coller : Number() ne le lit pas.
  const propre = texte.trim().replace(/\s/g, '').replace(/−/g, '-').replace(',', '.')
  if (!propre) return null
  const n = Number(propre)
  return Number.isFinite(n) ? n : null
}

/** « 45.5017, -73.5673 » ou « 45,5017 ; -73,5673 » collé d'un coup : on sépare latitude et longitude.
 *  Seulement au COLLAGE : pendant la frappe, « 45,5 » est une latitude à virgule décimale, pas une paire.
 *  Le séparateur doit donc être net : point-virgule, espace, virgule suivie d'une espace, ou virgule
 *  entre deux nombres à point décimal. */
function separerCoordonnees(texte: string): { lat: string; lon: string } | null {
  const propre = texte.trim()
  const m =
    propre.match(/^(-?\d{1,2}(?:[.,]\d+)?)\s*(?:;|,\s+|\s+)\s*(-?\d{1,3}(?:[.,]\d+)?)$/) ||
    propre.match(/^(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)$/)
  return m ? { lat: m[1], lon: m[2] } : null
}

export function ZonesScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { toast, invite } = useStore()
  const [etat, setEtat] = useState<EtatZones | null>(null)
  const [erreurEtat, setErreurEtat] = useState('')
  const [nom, setNom] = useState('')
  const [rayonChoix, setRayonChoix] = useState<Rayon>('150')
  const [rayonAutre, setRayonAutre] = useState('')
  const [lat, setLat] = useState('')
  const [lon, setLon] = useState('')
  const [precisionPc, setPrecisionPc] = useState<number | null>(null)
  const [occupe, setOccupe] = useState<'position' | 'ajout' | 'verifier' | 'sortie' | string | null>(null)
  const [erreurAjout, setErreurAjout] = useState('')
  const [erreurVerif, setErreurVerif] = useState('')
  const [verif, setVerif] = useState<string>('')
  const [aSupprimer, setASupprimer] = useState<Zone | null>(null)

  const charger = useCallback(async (): Promise<void> => {
    try {
      setEtat(await api.get<EtatZones>('/api/confiance/zones'))
      setErreurEtat('')
    } catch (err) {
      setErreurEtat(messageErreur(err))
    }
  }, [])

  useEffect(() => {
    charger().catch(() => undefined)
    return api.on((e: IrisEvent) => {
      // La liste vit dans les réglages ; la zone active change par zone.etat (téléphone ou ordinateur).
      if (e.type === 'zone.etat' || e.type === 'settings.updated' || e.type === 'ws.open') charger().catch(() => undefined)
    })
  }, [charger])

  const rayon = rayonChoix === 'autre' ? lireNombre(rayonAutre) : Number(rayonChoix)
  const latN = lireNombre(lat)
  const lonN = lireNombre(lon)
  const problemes: string[] = []
  if (!nom.trim()) problemes.push('donnez un nom à la zone')
  if (latN === null || latN < -90 || latN > 90) problemes.push('latitude entre -90 et 90')
  if (lonN === null || lonN < -180 || lonN > 180) problemes.push('longitude entre -180 et 180')
  if (rayon === null || rayon < RAYON_MIN || rayon > RAYON_MAX) problemes.push(`rayon de ${RAYON_MIN} à ${RAYON_MAX} m`)

  const utiliserPositionPc = async (): Promise<void> => {
    setOccupe('position')
    setErreurAjout('')
    try {
      const p = await api.get<PositionPc>('/api/confiance/position/pc')
      setLat(nombre(p.lat, 6))
      setLon(nombre(p.lon, 6))
      setPrecisionPc(Number(p.precision_m) || null)
    } catch (err) {
      setErreurAjout(messageErreur(err))
    } finally {
      setOccupe(null)
    }
  }

  const collerCoordonnees = (e: React.ClipboardEvent<HTMLInputElement>): void => {
    const paire = separerCoordonnees(e.clipboardData.getData('text'))
    if (!paire) return
    e.preventDefault()
    setLat(paire.lat)
    setLon(paire.lon)
    setPrecisionPc(null)
  }

  const ajouter = async (): Promise<void> => {
    if (problemes.length) return
    setOccupe('ajout')
    setErreurAjout('')
    try {
      const z = await api.post<Zone>('/api/confiance/zones', { nom: nom.trim(), lat: latN, lon: lonN, rayon_m: rayon })
      toast(`Zone « ${z.nom} » ajoutée.`, 'success')
      setNom('')
      setLat('')
      setLon('')
      setPrecisionPc(null)
      await charger()
    } catch (err) {
      setErreurAjout(messageErreur(err))
    } finally {
      setOccupe(null)
    }
  }

  const supprimer = async (z: Zone): Promise<void> => {
    setASupprimer(null)
    setOccupe(`suppr:${z.id}`)
    try {
      const r = await api.delete<EtatZones>(`/api/confiance/zones/${encodeURIComponent(z.id)}`)
      setEtat({ zones: r.zones, zone_active: r.zone_active, limite: r.limite })
      toast(`Zone « ${z.nom} » supprimée.`, 'success')
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      setOccupe(null)
    }
  }

  /** L'ordinateur signale lui-même la zone où il est (identifiant seulement), ou « aucune ». */
  const signalerPc = async (zone: Zone | null): Promise<void> => {
    setOccupe(zone ? `ici:${zone.id}` : 'sortie')
    setErreurVerif('')
    setVerif('')
    try {
      const r = await api.post<EtatZones>('/api/confiance/zone', { zone_id: zone ? zone.id : null, source: 'pc' })
      setEtat((prec) => ({ zones: r.zones, zone_active: r.zone_active, limite: r.limite ?? prec?.limite }))
      if (zone) setVerif(`Cet ordinateur est signalé dans « ${zone.nom} » : la mémoire est suspendue.`)
      else if (r.zone_active) setVerif(`Sortie signalée pour cet ordinateur, mais un autre appareil signale encore « ${r.zone_active.nom} » : la mémoire reste suspendue jusqu’à ce qu’il signale sa sortie.`)
      else setVerif('Sortie signalée : IRIS retient de nouveau.')
    } catch (err) {
      setErreurVerif(messageErreur(err))
    } finally {
      setOccupe(null)
    }
  }

  /** Lit la position de l'ordinateur, la fait comparer par le service, et ne la garde nulle part ici. */
  const verifierMaintenant = async (): Promise<void> => {
    setOccupe('verifier')
    setErreurVerif('')
    setVerif('')
    try {
      const p = await api.get<PositionPc>('/api/confiance/position/pc')
      const r = await api.post<EtatZones & { dans_zone: boolean }>('/api/confiance/position', {
        lat: p.lat,
        lon: p.lon,
        precision_m: p.precision_m,
        source: 'pc'
      })
      setEtat((prec) => ({ zones: r.zones, zone_active: r.zone_active, limite: r.limite ?? prec?.limite }))
      if (r.zone_active) setVerif(`Cet ordinateur est dans « ${r.zone_active.nom} » (précision de la position : environ ${distance(p.precision_m || 0)}) : la mémoire est suspendue.`)
      else setVerif('Cet ordinateur n’est dans aucune de vos zones. Si un autre appareil en signale une, la mémoire reste suspendue.')
    } catch (err) {
      setErreurVerif(messageErreur(err))
    } finally {
      setOccupe(null)
    }
  }

  const zones = etat?.zones || []
  const active = etat?.zone_active || null

  return (
    <div className="ecran">
      <TopBar titre="Zones sans mémoire" />
      <div className="contenu">
        <div className="zn-hero">
          <h2>Des lieux où IRIS suspend sa mémoire</h2>
          <p>
            Clinique, bureau d’un client, domicile d’un proche : dans une zone que vous choisissez, IRIS n’enregistre ni souvenirs, ni journal d’écoute, ni
            cours, ni photos décrites, ni reçus. À la sortie, elle retient de nouveau.
          </p>
        </div>

        {erreurEtat ? <div className="bloc-note erreur" role="alert">{erreurEtat}</div> : null}

        {/* ------------------------------------------------------------ zone active */}
        <div className={`carte col zn-active ${active ? 'dedans' : ''}`} style={{ gap: 10 }} aria-live="polite">
          <div className="row" style={{ gap: 10 }}>
            <span className={`dot ${active ? 'on' : ''}`} aria-hidden="true" />
            <h3 style={{ margin: 0 }}>{active ? `Dans la zone « ${active.nom} »` : 'Aucune zone active'}</h3>
          </div>
          <div className="desc">
            {active ? 'La mémoire d’IRIS est suspendue tant que la sortie n’est pas signalée.' : 'IRIS retient normalement, sauf si une autre protection est active.'}
          </div>
          {!active && invite?.actif ? <div className="small muted">Le mode invité est actif : la mémoire est suspendue pour cette raison.</div> : null}
          <div className="row wrap" style={{ gap: 8 }}>
            <Holo taille="petit" variante="sombre" disabled={occupe !== null || zones.length === 0} onClick={verifierMaintenant}>
              {occupe === 'verifier' ? 'Lecture de la position…' : 'Vérifier avec la position de cet ordinateur'}
            </Holo>
            {active ? (
              <Holo taille="petit" variante="contour" disabled={occupe !== null} onClick={() => signalerPc(null)}>
                {occupe === 'sortie' ? 'Envoi…' : 'Cet ordinateur est sorti de la zone'}
              </Holo>
            ) : null}
          </div>
          {verif ? <div className="bloc-note ok">{verif}</div> : null}
          {erreurVerif ? <div className="bloc-note erreur" role="alert">{erreurVerif}</div> : null}
          <div className="small muted" style={{ lineHeight: 1.45 }}>
            « Vérifier » lit la position de Windows une seule fois ; le service la compare à vos zones puis l’oublie, sans l’écrire ni la journaliser.
          </div>
        </div>

        {/* ------------------------------------------------------------ liste */}
        <h2 className="section-sous">Vos zones</h2>
        {etat && zones.length === 0 ? (
          <div className="carte">
            <Vide icone={<IcoCarte />} texte="Aucune zone pour l’instant" petit="Ajoutez un lieu ci-dessous : son nom, un rayon et sa position." />
          </div>
        ) : (
          <ul className="zn-liste" aria-label="Zones sans mémoire">
            {zones.map((z) => {
              const estActive = active?.id === z.id
              return (
                <li key={z.id} className={`zn-zone ${estActive ? 'active' : ''}`}>
                  <div className="corps">
                    <span className="nom">
                      {z.nom}
                      {estActive ? <span className="pill ok">active</span> : null}
                    </span>
                    <span className="sous">
                      Rayon {distance(z.rayon_m)} · {nombre(z.lat, 5)}, {nombre(z.lon, 5)}
                    </span>
                  </div>
                  <div className="actions">
                    {!estActive ? (
                      <button type="button" className="btn sm" disabled={occupe !== null} onClick={() => signalerPc(z)}>
                        {occupe === `ici:${z.id}` ? 'Envoi…' : 'J’y suis'}
                      </button>
                    ) : null}
                    <button type="button" className="btn-icone" aria-label={`Supprimer la zone ${z.nom}`} disabled={occupe !== null} onClick={() => setASupprimer(z)}>
                      <IcoPoubelle />
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
        {zones.length > 0 ? (
          <div className="small muted" style={{ lineHeight: 1.45, marginTop: -6 }}>
            « J’y suis » signale la zone depuis cet ordinateur, sans lire sa position : utile quand la localisation de Windows est coupée.
          </div>
        ) : null}

        {/* ------------------------------------------------------------ ajouter */}
        <div className="carte col" style={{ gap: 14 }}>
          <h3 style={{ margin: 0 }}>Ajouter une zone</h3>
          <Field label="Nom" hint={`${NOM_MAX} caractères au plus. Il s’affiche dans IRIS quand vous êtes dans la zone.`}>
            <input className="input" value={nom} maxLength={NOM_MAX} placeholder="Ex. : Clinique" onChange={(e) => setNom(e.target.value)} />
          </Field>

          <div className="col" style={{ gap: 8 }}>
            <span className="zn-etiquette" id="zn-rayon">Rayon</span>
            <div role="group" aria-labelledby="zn-rayon">
              <Puces<Rayon> options={RAYONS} valeur={rayonChoix} onChange={setRayonChoix} />
            </div>
            {rayonChoix === 'autre' ? (
              <Field label={`Rayon en mètres (${RAYON_MIN} à ${RAYON_MAX})`}>
                <input className="input" inputMode="numeric" value={rayonAutre} placeholder="200" onChange={(e) => setRayonAutre(e.target.value)} />
              </Field>
            ) : null}
          </div>

          <div className="col" style={{ gap: 10 }}>
            <span className="zn-etiquette">Position du centre</span>
            <Holo taille="petit" variante="sombre" disabled={occupe !== null} onClick={utiliserPositionPc}>
              {occupe === 'position' ? 'Lecture de la position…' : 'Utiliser la position de cet ordinateur'}
            </Holo>
            <div className="grid-2">
              <Field label="Latitude">
                <input
                  className="input"
                  inputMode="decimal"
                  value={lat}
                  placeholder="45,50170"
                  onPaste={collerCoordonnees}
                  onChange={(e) => {
                    setLat(e.target.value)
                    setPrecisionPc(null)
                  }}
                />
              </Field>
              <Field label="Longitude">
                <input
                  className="input"
                  inputMode="decimal"
                  value={lon}
                  placeholder="-73,56730"
                  onPaste={collerCoordonnees}
                  onChange={(e) => {
                    setLon(e.target.value)
                    setPrecisionPc(null)
                  }}
                />
              </Field>
            </div>
            {precisionPc !== null ? (
              <div className={`bloc-note ${rayon !== null && precisionPc > rayon ? 'attention' : ''}`}>
                Position de Windows, précise à environ {distance(precisionPc)}.
                {rayon !== null && precisionPc > rayon ? ' C’est plus que le rayon choisi : le centre de la zone peut être décalé. Vérifiez les coordonnées ou agrandissez le rayon.' : ''}
              </div>
            ) : null}
            <div className="small muted" style={{ lineHeight: 1.45 }}>
              Vous pouvez aussi coller « latitude, longitude » d’un coup dans l’un des deux champs. Pour trouver les coordonnées d’un lieu : sur le site
              OpenStreetMap, dans votre navigateur, clic droit sur le lieu puis « Afficher l’adresse ». Données cartographiques © contributeurs
              OpenStreetMap.
            </div>
          </div>

          <Holo disabled={occupe !== null || problemes.length > 0} onClick={ajouter}>
            <IcoPlus /> {occupe === 'ajout' ? 'Ajout…' : 'Ajouter la zone'}
          </Holo>
          {problemes.length > 0 && (nom || lat || lon) ? <div className="small muted">À compléter : {problemes.join(' ; ')}.</div> : null}
          {erreurAjout ? <div className="bloc-note erreur" role="alert">{erreurAjout}</div> : null}
        </div>

        {/* ------------------------------------------------------------ comment ça marche */}
        <div className="carte">
          <h3>Comment IRIS sait où vous êtes</h3>
          <ul className="liste-limites">
            <li>
              Rien ne suit votre position en arrière-plan. C’est un appareil qui signale l’entrée et la sortie : le téléphone (IRIS sur le téléphone compare
              lui-même sa position à vos zones et n’envoie que l’identifiant de la zone), ou cet ordinateur, quand vous le demandez ici.
            </li>
            <li>Quand un appareil envoie sa position au lieu de la zone, le service la compare puis l’oublie aussitôt : elle n’est ni écrite, ni journalisée, ni publiée.</li>
            <li>Une position imprécise compte comme « peut-être dans la zone » : IRIS préfère suspendre la mémoire à tort que retenir à tort.</li>
            <li>La liste des zones (noms, centres et rayons) est gardée dans les réglages de cet ordinateur.</li>
            <li>
              Dans une zone, vos échanges avec IRIS restent dans l’historique des discussions, et IRIS peut encore s’appuyer sur vos souvenirs existants pour
              répondre. Pour une session qui ne laisse aucune conversation, utilisez le mode invité.
            </li>
          </ul>
          {etat?.limite ? (
            <div className="bloc-note attention" style={{ marginTop: 12 }}>
              <strong>Limite : </strong>
              {etat.limite}
            </div>
          ) : null}
        </div>
      </div>

      {aSupprimer ? (
        <Modal
          title="Supprimer cette zone ?"
          onClose={() => setASupprimer(null)}
          actions={
            <>
              <button type="button" className="btn ghost" onClick={() => setASupprimer(null)}>Annuler</button>
              <button type="button" className="btn danger" onClick={() => supprimer(aSupprimer)}>Supprimer</button>
            </>
          }
        >
          <p>
            « {aSupprimer.nom} » ne sera plus une zone sans mémoire.
            {active?.id === aSupprimer.id ? ' Vous y êtes en ce moment : IRIS retiendra de nouveau dès la suppression.' : ''}
          </p>
        </Modal>
      ) : null}
    </div>
  )
}
