import React, { useState } from 'react'
import { Field, Toggle } from '../components/ui'
import { api } from '../lib/api'
import { useStore } from '../lib/store'

export function AgentsView(): JSX.Element {
  const { agents, settings, refreshAgents, refreshStatus, updateSettings, toast, status } = useStore()
  return (
    <div className="page">
      <h1>Moteurs IA</h1>
      <p className="lead">
        IRIS choisit le moteur IA adapté à chaque demande. Connectez vos propres comptes si vous en avez : les clés sont stockées dans le coffre du système
        ({status?.secrets_backend === 'keyring' ? 'Gestionnaire d’identifiants' : 'fichier chiffré AES-256'}) et ne quittent jamais votre ordinateur.
      </p>
      <div className="card row between">
        <div>
          <div>Moteur IA par défaut</div>
          <div className="small muted">Utilisé quand aucune règle de routage ne s’applique.</div>
        </div>
        <select className="select" style={{ width: 200 }} value={settings?.default_agent} onChange={(e) => updateSettings({ default_agent: e.target.value })}>
          {agents.map((a) => (
            <option key={a.name} value={a.name}>{a.label}</option>
          ))}
        </select>
      </div>
      <div className="card row between">
        <div>
          <div>Routage</div>
          <div className="small muted">Automatique : OpenRouter en priorité (actions PC, code, images, recherche) ; sinon Claude, GPT ou Gemini selon la demande.</div>
        </div>
        <select className="select" style={{ width: 200 }} value={settings?.routing_mode} onChange={(e) => updateSettings({ routing_mode: e.target.value })}>
          <option value="auto">Automatique</option>
          <option value="manual">Toujours le moteur par défaut</option>
        </select>
      </div>
      {agents.map((a) => (
        <AgentCard key={a.name} agent={a} onChanged={async () => { await refreshAgents(); await refreshStatus() }} toast={toast} />
      ))}
    </div>
  )
}

function AgentCard({ agent, onChanged, toast }: { agent: any; onChanged: () => Promise<void>; toast: (t: string, k?: any) => void }): JSX.Element {
  const [key, setKey] = useState('')
  const [model, setModel] = useState(agent.model || '')
  const [baseUrl, setBaseUrl] = useState(agent.base_url || '')
  const [label, setLabel] = useState(agent.label || '')
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; message: string; latency_ms?: number } | null>(null)
  const [saving, setSaving] = useState(false)

  const save = async (extra: Record<string, unknown> = {}) => {
    setSaving(true)
    try {
      const body: Record<string, unknown> = { model, ...extra }
      if (agent.name === 'custom') {
        body.base_url = baseUrl
        body.label = label
      }
      if (key.trim()) body.api_key = key.trim()
      await api.put(`/api/agents/${agent.name}`, body)
      setKey('')
      await onChanged()
      toast('Moteur IA enregistré.', 'success')
    } catch (err) {
      toast(String((err as Error).message), 'error')
    } finally {
      setSaving(false)
    }
  }

  const test = async () => {
    setTesting(true)
    setResult(null)
    try {
      if (key.trim() || model !== agent.model || baseUrl !== agent.base_url) await save()
      const res = await api.post(`/api/agents/${agent.name}/test`)
      setResult(res)
    } catch (err) {
      setResult({ ok: false, message: String((err as Error).message) })
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="card">
      <div className="row between" style={{ marginBottom: 10 }}>
        <div className="row">
          <strong style={{ fontSize: 15 }}>{agent.label}</strong>
          <span className="small muted">{agent.vendor}</span>
          {agent.ready ? <span className="pill ok">prêt</span> : agent.active ? <span className="pill warn">clé manquante</span> : <span className="pill">inactif</span>}
          {agent.supports_tools ? <span className="pill" title="Peut agir sur l’ordinateur">outils PC</span> : null}
          {agent.local ? <span className="pill ok">local</span> : null}
        </div>
        <div className="row">
          <span className="small muted">Activer</span>
          <Toggle on={agent.active} onChange={(v) => api.put(`/api/agents/${agent.name}`, { active: v }).then(onChanged)} />
        </div>
      </div>
      <p className="small muted" style={{ marginTop: 0 }}>{agent.description}</p>
      <div className="grid-2">
        {agent.name === 'custom' ? (
          <>
            <Field label="Nom affiché"><input className="input" value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
            <Field label="URL du serveur (OpenAI-compatible)" hint="Ollama : http://127.0.0.1:11434/v1 · LM Studio : http://127.0.0.1:1234/v1">
              <input className="input mono" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
            </Field>
          </>
        ) : null}
        <Field label="Modèle">
          {agent.models?.length ? (
            <select className="select" value={model} onChange={(e) => setModel(e.target.value)}>
              {agent.models.map((m: any) => (
                <option key={m.id} value={m.id}>{m.label}</option>
              ))}
              {!agent.models.some((m: any) => m.id === model) && model ? <option value={model}>{model}</option> : null}
            </select>
          ) : (
            <input className="input mono" value={model} onChange={(e) => setModel(e.target.value)} placeholder="ex. llama3.2" />
          )}
        </Field>
        {agent.name === 'openrouter' ? (
          <Field label="Ou un identifiant de modèle OpenRouter" hint="ex. mistralai/mistral-small-3.2-24b-instruct:free — les modèles « :free » ne coûtent rien.">
            <input className="input mono" value={model} onChange={(e) => setModel(e.target.value)} />
          </Field>
        ) : null}
        <Field label={agent.needs_key ? 'Clé API' : 'Clé API (optionnelle)'} hint={agent.has_key ? `Clé enregistrée : ${agent.key_masked}` : agent.key_url ? 'Obtenez une clé sur le site du fournisseur.' : undefined}>
          <input className="input mono" type="password" autoComplete="off" placeholder={agent.has_key ? '•••••••• (laisser vide pour conserver)' : agent.key_hint} value={key} onChange={(e) => setKey(e.target.value)} />
        </Field>
      </div>
      <div className="row wrap" style={{ marginTop: 12 }}>
        <button className="btn primary sm" disabled={saving} onClick={() => save({ active: true })}>Enregistrer et activer</button>
        <button className="btn sm" disabled={testing} onClick={test}>{testing ? 'Test…' : 'Tester la connexion'}</button>
        {agent.has_key ? <button className="btn danger sm" onClick={() => api.delete(`/api/agents/${agent.name}/key`).then(onChanged)}>Supprimer la clé</button> : null}
        {agent.key_url ? <button className="btn ghost sm" onClick={() => window.iris.openExternal(agent.key_url)}>Obtenir une clé ↗</button> : null}
        {result ? <span className={`pill ${result.ok ? 'ok' : 'err'}`}>{result.message}{result.ok && result.latency_ms ? ` · ${result.latency_ms} ms` : ''}</span> : null}
      </div>
    </div>
  )
}
