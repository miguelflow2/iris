import React, { useCallback, useEffect, useState } from 'react'
import { SettingRow, Toggle } from '../components/ui'
import { api, formatDate, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

const EVENT_LABEL: Record<string, string> = {
  external_send: 'Envoi à une IA externe',
  consent_granted: 'Consentement accordé',
  consent_revoked: 'Consentement retiré',
  command_executed: 'Commande exécutée',
  file_written: 'Fichier écrit',
  screen_captured: 'Capture d’écran locale',
  api_key_updated: 'Clé API enregistrée',
  api_key_removed: 'Clé API supprimée',
  agent_test: 'Test de connexion',
  local_only_enabled: 'Mode 100 % local activé',
  local_only_disabled: 'Mode 100 % local désactivé',
  memory_cleared: 'Mémoire effacée',
  purge_manual: 'Purge manuelle',
  privacy_mode_enabled: 'Mode confidentiel activé',
  privacy_mode_disabled: 'Mode confidentiel désactivé',
  glasses_connected: 'Lunettes connectées',
  register_exported: 'Registre exporté',
  daily_summary: 'Résumé de journée'
}

export function PrivacyView(): JSX.Element {
  const { consent, setConsent, settings, updateSettings, capture, status, toast } = useStore()
  const [events, setEvents] = useState<any[]>([])
  const [check, setCheck] = useState<any | null>(null)
  const load = useCallback(async () => setEvents((await api.get('/api/privacy/events')).events), [])
  useEffect(() => {
    load()
    return api.on((e: IrisEvent) => {
      if (['consent.updated', 'chat.done', 'settings.updated', 'privacy.purged', 'agent.updated'].includes(e.type)) load()
    })
  }, [load])

  return (
    <div className="page">
      <h1>Confidentialité</h1>
      <p className="lead">
        Les autres assistants vous demandent de les croire. IRIS vous laisse <strong>vérifier</strong> : chaque capture et chaque
        envoi est inscrit dans un registre chaîné, que vous pouvez contrôler et exporter vous-même.
      </p>

      <div className="proof">
        <div className="proof-main">
          <div className="proof-label">Registre de transparence</div>
          <div className="proof-state">
            {check ? (check.ok ? `Intact — ${check.count} entrée${check.count > 1 ? 's' : ''} vérifiée${check.count > 1 ? 's' : ''}` : `Altération détectée à l’entrée ${check.first_bad_id}`) : 'Chaîne SHA-256 — non vérifiée pour l’instant'}
          </div>
          <div className="proof-hint">
            Chaque entrée contient l’empreinte de la précédente. Modifier ou retirer une ligne casse la chaîne, et la vérification le montre.
          </div>
        </div>
        <button
          className="btn primary"
          onClick={async () => {
            const r = await api.get('/api/privacy/verify')
            setCheck(r)
            toast(r.ok ? `Registre intact (${r.count} entrées).` : `Altération détectée à l’entrée ${r.first_bad_id}.`, r.ok ? 'success' : 'error')
          }}
        >
          Vérifier maintenant
        </button>
      </div>

      <div className="card">
        <SettingRow title="Mode confidentiel" desc="Coupe le micro immédiatement et empêche toute écoute, capture ou relance automatique tant qu’il est actif. Aussi accessible depuis la barre latérale et l’icône de la barre système.">
          <Toggle on={Boolean(settings?.privacy_mode)} onChange={(v) => updateSettings({ privacy_mode: v })} />
        </SettingRow>
        <SettingRow title="Mode 100 % local" desc="Aucune donnée n’est envoyée à une IA externe. Seule une IA locale (Ollama, LM Studio…) peut répondre.">
          <Toggle on={Boolean(settings?.local_only)} onChange={(v) => updateSettings({ local_only: v })} />
        </SettingRow>
        <SettingRow title="Indicateur de capture" desc="Pastille flottante affichée dès que le micro, l’écran ou la caméra sont utilisés. Elle ne peut pas être désactivée.">
          <span className={`pill ${capture.mic || capture.screen ? 'err' : 'ok'}`}>{capture.mic ? 'micro actif' : capture.screen ? 'capture d’écran' : 'aucune capture'}</span>
        </SettingRow>
        <SettingRow title="Chiffrement au repos" desc={`AES-256-GCM. Clé maîtresse : ${status?.key_source === 'keyring' ? 'coffre du système' : 'fichier local protégé'} · clés API : ${status?.secrets_backend === 'keyring' ? 'coffre du système' : 'fichier chiffré'}.`}>
          <span className="pill ok">actif</span>
        </SettingRow>
      </div>

      <h2>Consentements par type de donnée</h2>
      <div className="card">
        {Object.entries(consent).map(([key, c]: [string, any]) => (
          <SettingRow key={key} title={c.label} desc={c.description}>
            {c.updated_at ? <span className="small muted">{formatDate(c.updated_at)}</span> : null}
            <Toggle on={Boolean(c.granted)} onChange={(v) => setConsent(key, v)} disabled={Boolean(settings?.local_only)} />
          </SettingRow>
        ))}
      </div>

      <h2>Rétention</h2>
      <div className="card">
        <SettingRow title="Durée de conservation" desc="Souvenirs, messages et journal sont supprimés physiquement (purge vérifiable) après ce délai.">
          <select className="select" style={{ width: 180 }} value={settings?.retention_days ?? 0} onChange={(e) => updateSettings({ retention_days: Number(e.target.value) })}>
            <option value={0}>Illimitée</option>
            <option value={1}>24 heures</option>
            <option value={7}>7 jours</option>
            <option value={30}>30 jours</option>
            <option value={90}>90 jours</option>
          </select>
          {/* Action destructrice (souvenirs, messages, journal) : même confirmation que « Effacer le registre ». */}
          <button
            className="btn sm"
            title="Supprime immédiatement tout ce qui dépasse la durée de conservation choisie."
            onClick={async () => {
              if (!window.confirm('Appliquer la purge maintenant ? Les souvenirs, messages et événements plus vieux que la durée de conservation seront supprimés définitivement.')) return
              const r = await api.post('/api/privacy/purge')
              toast(`Purge : ${r.memories} souvenirs, ${r.messages} messages, ${r.events} événements supprimés.`, 'success')
            }}
          >
            Purger maintenant
          </button>
        </SettingRow>
      </div>

      <h2>Registre de transparence</h2>
      <div className="card">
        <div className="row between wrap" style={{ marginBottom: 8 }}>
          <span className="small muted">Chaque capture, envoi externe, commande et consentement est consigné localement et chaîné par empreinte SHA-256 : toute modification a posteriori est détectable.</span>
          <div className="row">
            <button className="btn sm" onClick={async () => { const r = await api.get('/api/privacy/verify'); setCheck(r); toast(r.ok ? `Registre intact (${r.count} entrées).` : `Altération détectée à l’entrée ${r.first_bad_id}.`, r.ok ? 'success' : 'error') }}>Vérifier maintenant</button>
            <button className="btn sm" onClick={async () => { const res = await fetch(`${api.info?.baseUrl}/api/privacy/export?format=json`, { headers: { Authorization: `Bearer ${api.info?.token}` } }); const p = await window.iris.saveFile('iris-registre.json', await res.text()); if (p) toast(`Registre exporté : ${p}`, 'success') }}>Exporter JSON</button>
            <button className="btn sm" onClick={async () => { const res = await fetch(`${api.info?.baseUrl}/api/privacy/export?format=csv`, { headers: { Authorization: `Bearer ${api.info?.token}` } }); const p = await window.iris.saveFile('iris-registre.csv', await res.text()); if (p) toast(`Registre exporté : ${p}`, 'success') }}>Exporter CSV</button>
            {/* Action destructrice : libellé explicite + confirmation (même patron que MemoryView). setCheck(null) évite d’afficher une vérification périmée au-dessus d’un tableau vide. */}
            <button
              className="btn ghost sm"
              title="L’historique est supprimé définitivement ; la chaîne SHA-256 repart à zéro."
              onClick={async () => {
                if (!window.confirm('Effacer définitivement le registre de transparence ? La chaîne SHA-256 repart à zéro et l’historique est irrécupérable.')) return
                await api.delete('/api/privacy/events')
                setCheck(null)
                load()
              }}
            >
              Effacer le registre
            </button>
          </div>
        </div>
        {check ? <div className={`small ${check.ok ? '' : ''}`} style={{ marginBottom: 8, color: check.ok ? '#4cc9a6' : 'var(--danger)' }}>{check.ok ? `Intégrité vérifiée : ${check.count} entrées, empreinte finale ${(check.last_hash || '').slice(0, 16)}…` : `Altération détectée à l’entrée n° ${check.first_bad_id}`}</div> : null}
        <table className="table">
          <thead>
            <tr><th>Date</th><th>Événement</th><th>Donnée</th><th>IA</th><th>Détail</th></tr>
          </thead>
          <tbody>
            {/* Formulation qui reste vraie même après « Effacer le registre » ou « Purger maintenant ». */}
            {events.length === 0 ? <tr><td colSpan={5} className="muted">Aucun événement consigné pour l’instant. La première capture ou le premier envoi externe s’inscrira ici automatiquement.</td></tr> : null}
            {events.map((e) => (
              <tr key={e.id}>
                <td className="small muted" style={{ whiteSpace: 'nowrap' }}>{formatDate(e.created_at)}</td>
                <td>{EVENT_LABEL[e.event_type] || e.event_type}</td>
                <td className="small">{e.data_type || ''}</td>
                <td className="small">{e.agent || ''}</td>
                <td className="small muted" style={{ wordBreak: 'break-word' }}>{e.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
