import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Holo, TopBar } from '../components/ui'
import { api, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   Connecter les lunettes : détection Bluetooth LE et connexion à un appareil.
   Porte la section « Appareils détectés » de l'ancienne vue Lunettes.
   ========================================================================= */

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

function messageErreur(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

export function ConnecterScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  void params
  const { nav, lunettes, rafraichirLunettes, toast } = useStore()
  const [devices, setDevices] = useState<Device[]>(() => (Array.isArray(lunettes?.last_scan) ? lunettes.last_scan : []))
  const [scanning, setScanning] = useState(false)
  const [connectingTo, setConnectingTo] = useState<string | null>(null)
  const [tentative, setTentative] = useState<{ attempt: number; attempts: number } | null>(null)
  const monte = useRef(true)

  const connected = Boolean(lunettes?.connected)
  const remembered = lunettes?.remembered
  const adresseConnectee: string | undefined = lunettes?.device?.address

  /* ---------------------------------------------------------------- détection */
  const scan = useCallback(async () => {
    setScanning(true)
    try {
      const res = await api.post('/api/glasses/scan', { seconds: 6 })
      if (!monte.current) return
      setDevices(Array.isArray(res.devices) ? res.devices : [])
      if (res.error) toast(res.error, 'error')
      else if (!res.devices?.length) toast('Aucun appareil Bluetooth LE détecté. Allumez les lunettes et rapprochez-les.', 'info')
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setScanning(false)
    }
  }, [toast])

  /* ---------------------------------------------------------------- connexion (jusqu'à 3 × 30 s) */
  const connect = useCallback(
    async (d: { address: string; name?: string }) => {
      setConnectingTo(d.address)
      setTentative(null)
      try {
        await api.post('/api/glasses/connect', { address: d.address, name: d.name })
        await rafraichirLunettes()
      } catch (err) {
        toast(messageErreur(err), 'error')
      } finally {
        if (monte.current) {
          setConnectingTo(null)
          setTentative(null)
        }
      }
    },
    [rafraichirLunettes, toast]
  )

  // Détection lancée d'elle-même à l'ouverture ; événements de connexion pour suivre les tentatives.
  useEffect(() => {
    monte.current = true
    scan()
    const off = api.on((e: IrisEvent) => {
      if (e.type === 'glasses.connecting') setTentative({ attempt: Number(e.attempt) || 1, attempts: Number(e.attempts) || 3 })
      if (e.type === 'glasses.connected' || e.type === 'glasses.state') rafraichirLunettes().catch(() => undefined)
    })
    return () => {
      monte.current = false
      off()
    }
  }, [scan, rafraichirLunettes])

  // Dès que les lunettes sont connectées, on revient à l'accueil (qui affiche alors l'état connecté).
  // Le toast de succès « Lunettes connectées. » est émis une seule fois, par le store, sur
  // l'événement glasses.connected : on ne le double pas ici.
  const etaitConnecte = useRef(connected)
  useEffect(() => {
    if (connected && !etaitConnecte.current) nav.viderPile()
    etaitConnecte.current = connected
  }, [connected, nav])

  const libelleConnexion = (d: Device): string => {
    if (connectingTo === d.address) {
      return tentative ? `Connexion… tentative ${tentative.attempt}/${tentative.attempts}` : 'Connexion… (jusqu’à 90 s)'
    }
    if (connected && adresseConnectee === d.address) return 'Connectées'
    return 'Connecter'
  }

  return (
    <div className="ecran">
      <TopBar titre="Connecter les lunettes" />
      <div className="contenu">
        <p className="muted" style={{ fontSize: 16, fontWeight: 600, lineHeight: 1.4 }}>
          Allumez vos lunettes VELA et gardez-les près de l’ordinateur.
        </p>
        <p className="small muted" style={{ lineHeight: 1.45, marginTop: -6 }}>
          Les appareils déjà appairés dans Windows apparaissent même s’ils n’émettent pas.
        </p>

        <Holo disabled={scanning} onClick={scan}>
          {scanning ? 'Recherche… (6 s)' : 'Détecter les lunettes'}
        </Holo>

        {lunettes?.error ? (
          <div>
            <span className="pill err">{String(lunettes.error)}</span>
          </div>
        ) : null}

        {devices.length === 0 ? (
          <div className="empty">
            {scanning ? 'Recherche en cours…' : 'Aucun appareil listé. Allumez les lunettes et gardez-les près de l’ordinateur avant de relancer la détection.'}
          </div>
        ) : null}

        {devices.map((d) => {
          const dejaConnecte = connected && adresseConnectee === d.address
          return (
            <div className="carte serree" key={d.address}>
              <div className="row" style={{ alignItems: 'center', gap: 12 }}>
                <span className="mono muted" style={{ fontSize: 14 }} title={`RSSI ${d.rssi ?? '?'} dBm`}>
                  {signalBars(d.rssi)}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="row wrap" style={{ gap: 8 }}>
                    <span style={{ fontWeight: 700, fontSize: 18 }}>{d.name}</span>
                    {d.likely_glasses ? <span className="pill ok">lunettes ?</span> : null}
                    {d.paired ? (
                      <span className="pill" title="Appairé dans Windows : connexion directe possible sans annonce Bluetooth">appairé Windows</span>
                    ) : null}
                    {remembered?.address === d.address ? <span className="pill">mémorisées</span> : null}
                  </div>
                  <div className="small muted mono" style={{ marginTop: 3 }}>{d.address}</div>
                </div>
                <button type="button" className="btn primary sm" disabled={connectingTo !== null || dejaConnecte} onClick={() => connect(d)}>
                  {libelleConnexion(d)}
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
