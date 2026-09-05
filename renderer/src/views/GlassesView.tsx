import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { SettingRow, Toggle } from '../components/ui'
import { api, formatDate, formatTime, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

interface Device {
  address: string
  name: string
  rssi: number | null
  likely_glasses: boolean
  paired?: boolean
}

/** Les deux profils audio d’un même casque Bluetooth, réunis sous un seul appareil pour l’utilisateur. */
interface ProfilsCasque {
  base: string // préfixe commun aux deux profils, ex. « Casque (M01 Pro_F444 »
  etiquette: string // nom lisible, ex. « M01 Pro_F444 »
  micro: string // nom du micro à enregistrer
  sortieMainsLibres: string // sortie utilisable pendant que ce micro est ouvert
  sortieStereo: string | null // sortie haute qualité, muette dès que le micro du casque sert
}

const MAINS_LIBRES = /hands-free|mains libres|hfp/i

function signalBars(rssi: number | null): string {
  if (rssi === null || rssi === undefined) return '⌁'
  if (rssi > -60) return '▮▮▮▮'
  if (rssi > -70) return '▮▮▮▯'
  if (rssi > -80) return '▮▮▯▯'
  return '▮▯▯▯'
}

/**
 * Windows expose aussi les périphériques sous leur chaîne de ressource de pilote
 * (« Casque (@System32\drivers\bthhfenum.sys,#2;%1 Hands-Free AG Audio%0… »). Elle est illisible,
 * contient un retour à la ligne, et le serveur ne sait pas la faire correspondre à une sortie :
 * on ne la propose jamais, ni dans les boutons ni dans les listes.
 */
function estNomLisible(nom: string): boolean {
  return Boolean(nom) && !/@|\.sys|[\r\n]/.test(nom)
}

/** Préfixe commun aux deux profils d’un casque : c’est la seule chose qui les relie entre eux. */
function nomDeBase(nom: string): string {
  return nom.split(/ hands-free/i)[0].split(/ stereo\)?/i)[0].trim()
}

/** « Casque (M01 Pro_F444 » → « M01 Pro_F444 » : ce que l’utilisateur reconnaît sur sa boîte. */
function etiquetteCasque(base: string): string {
  const i = base.indexOf('(')
  const brut = (i >= 0 ? base.slice(i + 1) : base).trim()
  return brut || base
}

function uniques(noms: string[]): string[] {
  return Array.from(new Set(noms))
}

/**
 * Regroupe les lignes brutes de /api/voice/devices par casque physique.
 *
 * Nécessaire parce que PortAudio énumère le MÊME casque jusqu’à onze fois (MME, DirectSound,
 * WASAPI, WDM-KS), sous deux profils qui s’excluent, avec des noms tantôt complets tantôt
 * tronqués. L’utilisateur, lui, n’a qu’un seul objet sur le nez.
 */
function regrouperCasques(micros: string[], sorties: string[]): ProfilsCasque[] {
  const groupes = new Map<string, ProfilsCasque>()
  for (const nom of micros.filter(estNomLisible)) {
    // Un casque n’est éligible que s’il expose un micro : sans lui, « parler ET écouter » est impossible.
    if (!MAINS_LIBRES.test(nom)) continue
    const base = nomDeBase(nom)
    const g = groupes.get(base) ?? { base, etiquette: etiquetteCasque(base), micro: nom, sortieMainsLibres: '', sortieStereo: null }
    // Micro : on garde le nom le PLUS LONG. MME tronque à 31 caractères ; le nom complet, lui,
    // est reconnu par toutes les interfaces et permet au backend de voir que ce micro est de
    // qualité téléphone (il cherche « Hands-Free » dans le nom enregistré).
    if (nom.length > g.micro.length) g.micro = nom
    groupes.set(base, g)
  }
  for (const nom of sorties.filter(estNomLisible)) {
    const g = groupes.get(nomDeBase(nom))
    if (!g) continue
    if (MAINS_LIBRES.test(nom)) {
      // Sortie mains libres : on garde le nom le PLUS COURT. La forme tronquée par MME est
      // contenue dans toutes les autres, donc elle les retrouve toutes ; le nom long, lui, ne
      // retrouverait jamais l’entrée MME et la sortie resterait silencieusement sur le PC.
      if (!g.sortieMainsLibres || nom.length < g.sortieMainsLibres.length) g.sortieMainsLibres = nom
    } else if (!g.sortieStereo || nom.length > g.sortieStereo.length) {
      g.sortieStereo = nom
    }
  }
  for (const g of groupes.values()) {
    // Aucun profil mains libres listé en sortie (arrive quand le casque vient de se connecter) :
    // le micro porte le même nom, il fera correspondance côté serveur.
    if (!g.sortieMainsLibres) g.sortieMainsLibres = g.micro
  }
  return Array.from(groupes.values())
}

function normaliser(nom: string): string {
  return nom.toLowerCase().replace(/[^a-z0-9]/g, '')
}

/** Le casque qui porte le nom des lunettes connectées ou mémorisées, sinon le premier trouvé. */
function casqueDesLunettes(casques: ProfilsCasque[], nomLunettes: string): ProfilsCasque | null {
  if (!casques.length) return null
  const cible = normaliser(nomLunettes || '')
  if (cible.length >= 3) {
    const trouve = casques.find((c) => {
      const e = normaliser(c.etiquette)
      return e.includes(cible) || cible.includes(e)
    })
    if (trouve) return trouve
  }
  return casques[0]
}

function CarteChoix({ titre, detail, actif, disabled, onClick }: { titre: string; detail: string; actif: boolean; disabled?: boolean; onClick: () => void }): JSX.Element {
  return (
    <button
      type="button"
      className="btn"
      disabled={disabled}
      onClick={onClick}
      style={{
        flex: '1 1 240px',
        minWidth: 0,
        flexDirection: 'column',
        alignItems: 'flex-start',
        gap: 5,
        textAlign: 'left',
        whiteSpace: 'normal',
        padding: '12px 14px',
        borderColor: actif ? 'var(--accent-2)' : undefined,
        background: actif ? 'var(--accent-soft)' : undefined
      }}
    >
      <span className="row" style={{ gap: 8 }}>
        <span className={`dot ${actif ? 'on' : ''}`} />
        <span style={{ fontWeight: 600 }}>{titre}</span>
      </span>
      <span className="small muted" style={{ lineHeight: 1.45 }}>{detail}</span>
    </button>
  )
}

export function GlassesView(): JSX.Element {
  const { toast, settings, voice } = useStore()
  const [status, setStatus] = useState<any>(null)
  const [devices, setDevices] = useState<Device[]>([])
  const [scanning, setScanning] = useState(false)
  const [connectingTo, setConnectingTo] = useState<string | null>(null)
  const [mics, setMics] = useState<string[]>([])
  const [outputs, setOutputs] = useState<string[]>([])
  const [showServices, setShowServices] = useState(false)
  const [manuel, setManuel] = useState(false)
  const [applique, setApplique] = useState(false)

  const load = useCallback(async () => {
    const s = await api.get('/api/glasses/status')
    setStatus(s)
    if (s.last_scan?.length) setDevices(s.last_scan)
  }, [])

  const chargerPeripheriques = useCallback(async () => {
    try {
      const r = await api.get('/api/voice/devices')
      setMics(r.devices || [])
      setOutputs(r.outputs || [])
    } catch {
      /* liste indisponible : l’écran le dit plus bas */
    }
  }, [])

  useEffect(() => {
    load()
    chargerPeripheriques()
    return api.on((e: IrisEvent) => {
      if (e.type === 'glasses.state') setStatus(e)
      if (e.type === 'glasses.connected') {
        toast(`Lunettes connectées : ${e.device?.name}`, 'success')
        // Le casque audio apparaît dans Windows au moment de la connexion : la liste change.
        chargerPeripheriques()
      }
      if (e.type === 'glasses.disconnected') {
        toast('Lunettes déconnectées', 'info')
        chargerPeripheriques()
      }
      if (e.type === 'glasses.connecting') toast(`Connexion aux lunettes… tentative ${e.attempt}/${e.attempts} (jusqu’à 30 s)`, 'info')
      if (e.type === 'glasses.packet') setStatus((s: any) => (s ? { ...s, packets: [...(s.packets || []).slice(-19), e], packet_count: (s.packet_count || 0) + 1 } : s))
    })
  }, [load, chargerPeripheriques, toast])

  const scan = async () => {
    setScanning(true)
    try {
      const res = await api.post('/api/glasses/scan', { seconds: 6 })
      setDevices(res.devices)
      if (res.error) toast(res.error, 'error')
      else if (!res.devices.length) toast('Aucun appareil Bluetooth LE détecté. Allumez les lunettes et rapprochez-les.', 'info')
    } catch (err) {
      toast(String((err as Error).message), 'error')
    } finally {
      setScanning(false)
    }
  }

  const connect = async (d: { address: string; name?: string }) => {
    setConnectingTo(d.address)
    try {
      await api.post('/api/glasses/connect', { address: d.address, name: d.name })
    } catch (err) {
      toast(String((err as Error).message), 'error')
    } finally {
      setConnectingTo(null)
    }
  }

  const remembered = status?.remembered
  const connected = Boolean(status?.connected)

  const entree: string = settings?.audio_input_device || ''
  const sortie: string = settings?.audio_output_device || ''

  const casques = useMemo(() => regrouperCasques(mics, outputs), [mics, outputs])
  const casque = useMemo(
    () => casqueDesLunettes(casques, status?.device?.name || remembered?.name || ''),
    [casques, status?.device?.name, remembered?.name]
  )

  /**
   * Un seul appel pose les DEUX périphériques. Séparer les deux réglages laisserait l’utilisateur,
   * l’espace d’un clic, avec le micro du casque ouvert et la voix d’IRIS restée sur le PC — ou pire,
   * dirigée vers une sortie stéréo que Windows vient d’éteindre en ouvrant ce micro.
   */
  const appliquer = async (nouvelleEntree: string, nouvelleSortie: string, message: string) => {
    setApplique(true)
    try {
      const res = await api.patch('/api/glasses/prefs', { audio_input_device: nouvelleEntree, audio_output_device: nouvelleSortie })
      if (res?.remembered) setStatus(res)
      toast(message, 'success')
    } catch (err) {
      toast(String((err as Error).message), 'error')
    } finally {
      setApplique(false)
    }
  }

  const microDesLunettes = Boolean(casque) && entree === casque!.micro
  const microEstMainsLibres = MAINS_LIBRES.test(entree)
  const sortieDansLesLunettes = Boolean(casque) && (sortie === casque!.sortieMainsLibres || (casque!.sortieStereo !== null && sortie === casque!.sortieStereo))
  const modeToutLunettes = microDesLunettes && sortie === casque?.sortieMainsLibres
  const modeVoixSeule = !entree && Boolean(casque?.sortieStereo) && sortie === casque?.sortieStereo
  const modeToutPC = !entree && !sortie

  // Combinaison impossible : le micro du casque est ouvert, donc Windows a éteint sa stéréo.
  // IRIS entendrait parfaitement et parlerait dans une sortie muette.
  const combinaisonImpossible = microEstMainsLibres && Boolean(sortie) && !MAINS_LIBRES.test(sortie)
  // Micro dans les lunettes mais voix restée sur le PC : audible pour toute la pièce, pas pour vous.
  const voixResteeSurLePC = microEstMainsLibres && !sortie

  const nomLisible = (valeur: string, vide: string): string => {
    if (!valeur) return vide
    if (casque && (valeur === casque.micro || valeur === casque.sortieMainsLibres)) return `vos lunettes (${casque.etiquette})`
    if (casque && valeur === casque.sortieStereo) return `vos lunettes (${casque.etiquette}), en haute qualité`
    return valeur
  }

  // Vérité de terrain : le micro réellement ouvert, tel que le backend l’a résolu. Le réglage
  // enregistré ne dit que l’intention ; ces deux choses ont divergé assez souvent pour qu’on
  // affiche celle qui compte.
  const microOuvert: string = voice?.running ? voice?.device || '' : ''

  const microsListe = useMemo(() => {
    const liste = uniques(mics.filter(estNomLisible))
    if (entree && !liste.includes(entree)) liste.unshift(entree)
    return liste
  }, [mics, entree])
  const sortiesListe = useMemo(() => {
    const liste = uniques(outputs.filter(estNomLisible))
    if (sortie && !liste.includes(sortie)) liste.unshift(sortie)
    return liste
  }, [outputs, sortie])

  return (
    <div className="page">
      <h1>Lunettes</h1>
      <p className="lead">
        Détectez et connectez vos lunettes VELA (ou un M01 Pro en développement) en Bluetooth LE. Les appareils déjà appairés dans Windows apparaissent même s’ils
        n’émettent pas. Le son, lui, passe par l’appairage casque de Windows : une fois les lunettes appairées, un seul bouton ci-dessous suffit pour qu’IRIS vous
        écoute et vous réponde dedans.
      </p>

      <div className="card">
        <div className="row between">
          <div className="row">
            <span className={`dot ${connected ? 'on' : ''}`} />
            <div>
              <div>{connected ? status.device?.name || status.device?.address : remembered?.address ? `${remembered.name || remembered.address} — non connectées` : 'Aucune lunette connectée'}</div>
              <div className="small muted">
                {connected ? `Connectées depuis ${formatTime(status.connected_at)} · ${status.services?.length || 0} services · ${status.packet_count || 0} paquets reçus` : remembered?.address ? `Adresse mémorisée : ${remembered.address}` : 'Appuyez sur « Détecter les lunettes » pour lancer la recherche.'}
                {status?.battery !== null && status?.battery !== undefined ? ` · batterie ${status.battery} %` : ''}
              </div>
            </div>
          </div>
          <div className="row">
            {connected ? (
              <>
                <button className="btn sm" onClick={() => api.post('/api/glasses/battery').then(load)}>Batterie</button>
                <button className="btn danger sm" onClick={() => api.post('/api/glasses/disconnect').then(load)}>Déconnecter</button>
              </>
            ) : remembered?.address ? (
              <>
                <button className="btn primary sm" disabled={connectingTo !== null} onClick={() => connect({ address: remembered.address, name: remembered.name })}>{connectingTo ? 'Connexion…' : 'Reconnecter'}</button>
                <button className="btn ghost sm" onClick={() => api.post('/api/glasses/forget').then(load)}>Oublier</button>
              </>
            ) : null}
            <button className="btn primary sm" disabled={scanning} onClick={scan}>{scanning ? 'Recherche… (6 s)' : 'Détecter les lunettes'}</button>
          </div>
        </div>
        {status?.error ? <div className="small" style={{ color: 'var(--danger)', marginTop: 8 }}>{status.error}</div> : null}
        <SettingRow title="Reconnexion automatique" desc="IRIS se reconnecte aux lunettes mémorisées au démarrage et après une coupure.">
          <Toggle on={Boolean(remembered?.auto_connect)} disabled={!remembered?.address} onChange={(v) => api.patch('/api/glasses/prefs', { auto_connect: v }).then(load)} />
        </SettingRow>
      </div>

      <h2>Le son</h2>
      <div className="card">
        <div style={{ marginBottom: 14 }}>
          <div>
            En ce moment, IRIS vous écoute par <strong>{nomLisible(microOuvert || entree, 'le micro de votre ordinateur')}</strong> et vous répond par{' '}
            <strong>{nomLisible(sortie, 'la sortie audio habituelle de votre ordinateur')}</strong>.
          </div>
          {microOuvert && entree && microOuvert !== entree ? (
            <div className="small muted" style={{ marginTop: 4 }}>Micro réellement ouvert : {microOuvert}.</div>
          ) : null}
          {!microOuvert && entree ? (
            <div className="small muted" style={{ marginTop: 4 }}>Réglage enregistré ; il s’appliquera au prochain démarrage de l’écoute.</div>
          ) : null}
        </div>

        {combinaisonImpossible ? (
          <div className="small" style={{ color: 'var(--warn)', marginBottom: 12 }}>
            Ces deux réglages ne peuvent pas marcher ensemble : quand IRIS utilise le micro de vos lunettes, votre ordinateur coupe leur son de bonne qualité. Vous
            ne l’entendriez pas répondre.{' '}
            {casque ? (
              <button className="btn ghost sm" disabled={applique} onClick={() => appliquer(casque.micro, casque.sortieMainsLibres, 'Corrigé : tout passe par vos lunettes.')}>
                Corriger
              </button>
            ) : null}
          </div>
        ) : voixResteeSurLePC ? (
          <div className="small" style={{ color: 'var(--warn)', marginBottom: 12 }}>
            IRIS vous écoute par vos lunettes mais vous répond par votre ordinateur : toute la pièce l’entend, sauf vous si vous vous éloignez.{' '}
            {casque ? (
              <button className="btn ghost sm" disabled={applique} onClick={() => appliquer(casque.micro, casque.sortieMainsLibres, 'Corrigé : tout passe par vos lunettes.')}>
                Tout mettre dans mes lunettes
              </button>
            ) : null}
          </div>
        ) : null}

        {casque ? (
          <>
            <div className="row wrap" style={{ alignItems: 'stretch', gap: 10 }}>
              <CarteChoix
                titre="Utiliser mes lunettes pour parler et écouter"
                detail="Mains totalement libres, où que vous soyez dans la pièce. Le son est de qualité téléphone, des deux côtés."
                actif={modeToutLunettes}
                disabled={applique}
                onClick={() => appliquer(casque.micro, casque.sortieMainsLibres, `IRIS parle et écoute dans vos lunettes (${casque.etiquette}).`)}
              />
              {casque.sortieStereo ? (
                <CarteChoix
                  titre="Répondre dans mes lunettes, m’écouter par l’ordinateur"
                  detail="La voix d’IRIS garde toute sa qualité. Il faut rester à portée du micro de l’ordinateur pour lui parler."
                  actif={modeVoixSeule}
                  disabled={applique}
                  onClick={() => appliquer('', casque.sortieStereo as string, `IRIS répond dans vos lunettes (${casque.etiquette}), et vous écoute par l’ordinateur.`)}
                />
              ) : null}
              <CarteChoix
                titre="Tout par l’ordinateur"
                detail="À choisir quand vous retirez vos lunettes : IRIS reprend le micro et les haut-parleurs habituels."
                actif={modeToutPC}
                disabled={applique}
                onClick={() => appliquer('', '', 'IRIS utilise de nouveau le micro et les haut-parleurs de l’ordinateur.')}
              />
            </div>
          </>
        ) : (
          <div className="small muted" style={{ lineHeight: 1.5 }}>
            Windows ne voit pas encore vos lunettes comme un casque audio, donc IRIS ne peut pas encore parler dedans. Appairez-les dans les réglages Bluetooth de
            Windows (elles apparaissent sous leur nom d’appareil, par exemple « M01 Pro »), puis revenez ici.{' '}
            <button className="btn ghost sm" onClick={chargerPeripheriques}>Chercher à nouveau</button>
          </div>
        )}

        {/* Avertissement affiché dès que le micro choisi est celui d’un casque, même si le
            regroupement n’a rien trouvé : c’est une conséquence physique du sans-fil, pas un réglage. */}
        {microEstMainsLibres ? (
          <div className="small muted" style={{ marginTop: 12, lineHeight: 1.5 }}>
            Tant qu’IRIS écoute par vos lunettes, le son est de qualité téléphone : elle comprend un peu moins bien qu’avec le micro de l’ordinateur, et sa propre
            voix perd en finesse. C’est ainsi que fonctionne un casque sans fil, aucun réglage n’y change quelque chose. Si vous l’avez autorisé dans
            Confidentialité, IRIS s’appuie alors sur la reconnaissance en ligne pour mieux vous comprendre.
          </div>
        ) : null}

        <div style={{ marginTop: 14 }}>
          <button className="btn ghost sm" onClick={() => setManuel((v) => !v)}>{manuel ? 'Masquer' : 'Afficher'} le réglage manuel</button>
          {manuel ? (
            <>
              <SettingRow title="Micro utilisé par IRIS" desc="Le périphérique d’entrée que l’écoute ouvrira. Vide = le micro habituel de l’ordinateur.">
                <select className="select" style={{ width: 280 }} value={entree} onChange={(e) => api.patch('/api/glasses/prefs', { audio_input_device: e.target.value })}>
                  <option value="">Micro par défaut du système</option>
                  {microsListe.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </SettingRow>
              <SettingRow title="Sortie audio d’IRIS" desc="Où sa voix est jouée. Vide = la sortie habituelle de l’ordinateur.">
                <select className="select" style={{ width: 280 }} value={sortie} onChange={(e) => api.patch('/api/glasses/prefs', { audio_output_device: e.target.value })}>
                  <option value="">Sortie par défaut du système</option>
                  {sortiesListe.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </SettingRow>
              <div className="small muted" style={{ marginTop: 8 }}>
                Ces deux listes se règlent séparément : elles peuvent donc produire une combinaison qu’IRIS vous signalera plus haut. Les boutons du dessus, eux,
                posent toujours les deux ensemble.{' '}
                <button className="btn ghost sm" onClick={chargerPeripheriques}>Actualiser la liste</button>
              </div>
            </>
          ) : null}
        </div>
        {casques.length > 1 && casque ? (
          <div className="small muted" style={{ marginTop: 10 }}>
            Plusieurs casques sont appairés. Les boutons ci-dessus visent « {casque.etiquette} » ; pour un autre appareil, passez par le réglage manuel.
          </div>
        ) : null}
        {sortieDansLesLunettes && !connected ? (
          <div className="small muted" style={{ marginTop: 10 }}>
            IRIS parlera dans vos lunettes dès que Windows les aura reconnectées ; si elles sont éteintes, sa voix repartira dans l’ordinateur.
          </div>
        ) : null}
      </div>

      <h2>Appareils détectés</h2>
      <div className="list">
        {devices.length === 0 ? <div className="empty">{scanning ? 'Recherche en cours…' : 'Aucun appareil listé. Allumez les lunettes et gardez-les près du PC avant de lancer la détection.'}</div> : null}
        {devices.map((d) => (
          <div className="list-item" key={d.address} style={{ alignItems: 'center' }}>
            <span className="mono muted" title={`RSSI ${d.rssi ?? '?'} dBm`}>{signalBars(d.rssi)}</span>
            <div className="grow">
              <div className="row">
                <span>{d.name}</span>
                {d.likely_glasses ? <span className="pill ok">lunettes ?</span> : null}
                {d.paired ? <span className="pill" title="Appairé dans Windows : connexion directe possible sans annonce Bluetooth">appairé Windows</span> : null}
                {remembered?.address === d.address ? <span className="pill">mémorisées</span> : null}
              </div>
              <div className="small muted mono">{d.address}</div>
            </div>
            <button className="btn sm" disabled={connectingTo !== null || (connected && status?.device?.address === d.address)} onClick={() => connect(d)}>
              {connectingTo === d.address ? 'Connexion… (jusqu’à 90 s)' : connected && status?.device?.address === d.address ? 'Connectées' : 'Connecter'}
            </button>
          </div>
        ))}
      </div>

      {connected ? (
        <>
          <h2>Données reçues (canal BLE)</h2>
          <div className="card">
            <div className="small muted" style={{ marginBottom: 8 }}>Notifications brutes des caractéristiques GATT. Le protocole exact des lunettes sera décodé avec le SDK du fournisseur.</div>
            <pre className="mono" style={{ margin: 0, maxHeight: 220, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
              {(status.packets || []).length ? (status.packets || []).map((p: any) => `${formatTime(p.ts)}  ${p.uuid.slice(0, 8)}…  ${p.hex}`).join('\n') : '(aucun paquet pour l’instant)'}
            </pre>
            <button className="btn ghost sm" style={{ marginTop: 8 }} onClick={() => setShowServices((v) => !v)}>{showServices ? 'Masquer' : 'Afficher'} les services GATT ({status.services?.length || 0})</button>
            {showServices ? (
              <table className="table" style={{ marginTop: 8 }}>
                <thead><tr><th>Service</th><th>Caractéristique</th><th>Propriétés</th></tr></thead>
                <tbody>
                  {(status.services || []).flatMap((s: any) => s.characteristics.map((c: any) => (
                    <tr key={s.uuid + c.uuid}><td className="mono small">{s.description || s.uuid}</td><td className="mono small">{c.description || c.uuid}</td><td className="small">{c.properties.join(', ')}</td></tr>
                  )))}
                </tbody>
              </table>
            ) : null}
          </div>
        </>
      ) : null}
      {remembered?.address && status?.connected_at ? <p className="small muted">Dernière connexion : {formatDate(status.connected_at)}</p> : null}
    </div>
  )
}
