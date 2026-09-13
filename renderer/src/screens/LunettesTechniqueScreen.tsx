import React, { useEffect, useState } from 'react'
import { BtnIcone, TopBar } from '../components/ui'
import { IcoActualiser } from '../components/icons'
import { api, formatTime, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   Détails techniques des lunettes : compteur de paquets, dump hexadécimal des 20 derniers
   paquets reçus sur le canal BLE, et table des services GATT. Vit en direct grâce aux
   événements glasses.packet et glasses.state.
   ========================================================================= */

interface Paquet {
  ts: string
  uuid: string
  hex: string
  len?: number
}

interface Caracteristique {
  uuid: string
  description?: string
  properties: string[]
}

interface Service {
  uuid: string
  description?: string
  characteristics: Caracteristique[]
}

function listePaquets(source: unknown): Paquet[] {
  return Array.isArray(source) ? (source as Paquet[]).slice(-20) : []
}

export function LunettesTechniqueScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  void params
  const { lunettes, rafraichirLunettes } = useStore()
  const [paquets, setPaquets] = useState<Paquet[]>(() => listePaquets(lunettes?.packets))
  const [total, setTotal] = useState<number>(Number(lunettes?.packet_count) || 0)

  // L'état du store (statut complet relu) fait foi dès qu'il change.
  useEffect(() => {
    setPaquets(listePaquets(lunettes?.packets))
    setTotal(Number(lunettes?.packet_count) || 0)
  }, [lunettes?.packets, lunettes?.packet_count])

  // Chaque notification BLE arrive en direct : on l'ajoute sans attendre un rafraîchissement.
  useEffect(() => {
    const off = api.on((e: IrisEvent) => {
      if (e.type === 'glasses.packet') {
        setPaquets((p) => [...p.slice(-19), { ts: String(e.ts || ''), uuid: String(e.uuid || ''), hex: String(e.hex || ''), len: Number(e.len) || undefined }])
        setTotal((n) => n + 1)
      }
      if (e.type === 'glasses.state') {
        setPaquets(listePaquets(e.packets))
        setTotal(Number(e.packet_count) || 0)
      }
    })
    return off
  }, [])

  const connected = Boolean(lunettes?.connected)
  const services: Service[] = Array.isArray(lunettes?.services) ? lunettes.services : []
  const nbCaracteristiques = services.reduce((n, s) => n + (Array.isArray(s.characteristics) ? s.characteristics.length : 0), 0)

  return (
    <div className="ecran">
      <TopBar
        titre="Détails techniques"
        droite={
          <BtnIcone aria-label="Actualiser" title="Actualiser" onClick={() => rafraichirLunettes().catch(() => undefined)}>
            <IcoActualiser />
          </BtnIcone>
        }
      />
      <div className="contenu">
        <div className="carte serree">
          <div className="row between wrap" style={{ gap: 10 }}>
            <div>
              <div style={{ fontWeight: 700, fontSize: 18 }}>Canal BLE</div>
              <div className="small muted" style={{ marginTop: 2 }}>
                {connected ? 'Connecté' : 'Déconnecté'}
                {lunettes?.device?.address ? ` · ${lunettes.device.address}` : ''}
              </div>
            </div>
            <div className="row" style={{ gap: 8 }}>
              <span className="pill">{total} paquet{total > 1 ? 's' : ''} reçu{total > 1 ? 's' : ''}</span>
              <span className="pill">{services.length} service{services.length > 1 ? 's' : ''}</span>
            </div>
          </div>
          {lunettes?.error ? (
            <div style={{ marginTop: 10 }}>
              <span className="pill err">{String(lunettes.error)}</span>
            </div>
          ) : null}
        </div>

        <h2 className="section-sous">Derniers paquets</h2>
        <div className="carte serree mono" style={{ overflow: 'auto' }}>
          <div className="small muted" style={{ fontFamily: 'var(--font)', marginBottom: 8, lineHeight: 1.45 }}>
            Notifications brutes des caractéristiques GATT (20 dernières). Le protocole exact des lunettes est décodé avec le SDK du fabricant.
          </div>
          <pre className="mono" style={{ margin: 0, maxHeight: 320, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            {paquets.length
              ? paquets.map((p) => `${formatTime(p.ts)}  ${(p.uuid || '').slice(0, 8)}…  ${p.hex}`).join('\n')
              : connected
                ? '(aucun paquet pour l’instant)'
                : '(connectez les lunettes pour voir les paquets)'}
          </pre>
        </div>

        <details className="carte serree">
          <summary style={{ cursor: 'pointer', fontWeight: 700, fontSize: 18 }}>
            Services GATT ({services.length}, {nbCaracteristiques} caractéristique{nbCaracteristiques > 1 ? 's' : ''})
          </summary>
          {services.length ? (
            <div style={{ overflowX: 'auto', marginTop: 10 }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Service</th>
                    <th>Caractéristique</th>
                    <th>Propriétés</th>
                  </tr>
                </thead>
                <tbody>
                  {services.flatMap((s) =>
                    (Array.isArray(s.characteristics) ? s.characteristics : []).map((c) => (
                      <tr key={s.uuid + c.uuid}>
                        <td className="mono small">{s.description || s.uuid}</td>
                        <td className="mono small">{c.description || c.uuid}</td>
                        <td className="small">{(c.properties || []).join(', ')}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="small muted" style={{ marginTop: 10 }}>Aucun service découvert : les lunettes ne sont pas connectées.</div>
          )}
        </details>

        <button type="button" className="btn" onClick={() => rafraichirLunettes().catch(() => undefined)}>
          <IcoActualiser /> Actualiser
        </button>
      </div>
    </div>
  )
}
