import React, { useCallback, useEffect, useState } from 'react'
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

function signalBars(rssi: number | null): string {
  if (rssi === null || rssi === undefined) return '⌁'
  if (rssi > -60) return '▮▮▮▮'
  if (rssi > -70) return '▮▮▮▯'
  if (rssi > -80) return '▮▮▯▯'
  return '▮▯▯▯'
}

export function GlassesView(): JSX.Element {
  const { toast, settings } = useStore()
  const [status, setStatus] = useState<any>(null)
  const [devices, setDevices] = useState<Device[]>([])
  const [scanning, setScanning] = useState(false)
  const [connectingTo, setConnectingTo] = useState<string | null>(null)
  const [mics, setMics] = useState<string[]>([])
  const [outputs, setOutputs] = useState<string[]>([])
  const [showServices, setShowServices] = useState(false)

  const load = useCallback(async () => {
    const s = await api.get('/api/glasses/status')
    setStatus(s)
    if (s.last_scan?.length) setDevices(s.last_scan)
  }, [])

  useEffect(() => {
    load()
    api.get('/api/voice/devices').then((r) => { setMics(r.devices); setOutputs(r.outputs || []) }).catch(() => undefined)
    return api.on((e: IrisEvent) => {
      if (e.type === 'glasses.state') setStatus(e)
      if (e.type === 'glasses.connected') toast(`Lunettes connectées : ${e.device?.name}`, 'success')
      if (e.type === 'glasses.disconnected') toast('Lunettes déconnectées', 'info')
      if (e.type === 'glasses.connecting') toast(`Connexion aux lunettes… tentative ${e.attempt}/${e.attempts} (jusqu’à 30 s)`, 'info')
      if (e.type === 'glasses.packet') setStatus((s: any) => (s ? { ...s, packets: [...(s.packets || []).slice(-19), e], packet_count: (s.packet_count || 0) + 1 } : s))
    })
  }, [load, toast])

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

  return (
    <div className="page">
      <h1>Lunettes</h1>
      <p className="lead">Détectez et connectez vos lunettes VELA (ou un M01 Pro en développement) en Bluetooth LE. Les appareils déjà appairés dans Windows apparaissent même s’ils n’émettent pas. L’audio des lunettes passe par l’appairage casque de Windows : une fois appairées, choisissez-les comme micro d’IRIS ci-dessous.</p>

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
        <SettingRow title="Sortie audio d’IRIS" desc="Où IRIS parle (voix ElevenLabs). Choisissez la sortie « Stereo » des lunettes pour la meilleure qualité ; si vous utilisez aussi leur micro Hands-Free, Windows coupe la stéréo et il faut choisir la sortie « Hands-Free ».">
          <select className="select" style={{ width: 280 }} value={settings?.audio_output_device || ''} onChange={(e) => api.patch('/api/glasses/prefs', { audio_output_device: e.target.value })}>
            <option value="">Sortie par défaut du système</option>
            {outputs.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </SettingRow>
        <SettingRow title="Reconnexion automatique" desc="IRIS se reconnecte aux lunettes mémorisées au démarrage et après une coupure.">
          <Toggle on={Boolean(remembered?.auto_connect)} disabled={!remembered?.address} onChange={(v) => api.patch('/api/glasses/prefs', { auto_connect: v }).then(load)} />
        </SettingRow>
        <SettingRow title="Micro utilisé par IRIS" desc="Le micro « Hands-Free » des lunettes est en qualité téléphone (8 kHz) : IRIS passe alors automatiquement en reconnaissance cloud (consentement « audio brut » requis). Pour la meilleure précision, gardez le micro du PC et utilisez les lunettes pour la sortie.">
          <select className="select" style={{ width: 280 }} value={settings?.audio_input_device || ''} onChange={(e) => api.patch('/api/glasses/prefs', { audio_input_device: e.target.value })}>
            <option value="">Micro par défaut du système</option>
            {mics.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </SettingRow>
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
