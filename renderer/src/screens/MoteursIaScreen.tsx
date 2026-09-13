import React, { useEffect, useState } from 'react'
import { CarteReglage, Field, Holo, Segmente, SettingRow, Toggle, TopBar } from '../components/ui'
import { api } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   « Moteurs IA » (ancienne vue Agents, portée en entier). Masque de marque :
   par défaut, on ne montre que le cerveau VELA inclus et l'IA locale/perso.
   Les moteurs tiers (clé personnelle, nom de fournisseur) ne s'affichent que
   si l'utilisateur active délibérément « Moteurs avancés » — c'est un écran
   avancé BYOK, les noms de fournisseurs y sont permis.
   ========================================================================= */

const MOTEURS_DE_BASE = ['vela', 'custom']
type ChoixDemo = 'auto' | 'claude' | 'openrouter' | ''

function messageErreur(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

export function MoteursIaScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { agents, settings, refreshAgents, refreshStatus, updateSettings, toast, status } = useStore()
  const [avance, setAvance] = useState(false)

  const set = (patch: Record<string, unknown>): void => {
    updateSettings(patch).catch((err: Error) => toast(String(err.message), 'error'))
  }

  const visibles = avance ? agents : agents.filter((a) => MOTEURS_DE_BASE.includes(a.name))
  // Le menu « moteur par défaut » ne doit jamais être vide ni cacher la sélection courante.
  const optionsDefaut = visibles.some((a) => a.name === settings?.default_agent)
    ? visibles
    : [...visibles, ...agents.filter((a) => a.name === settings?.default_agent)]

  const choixDemo: ChoixDemo =
    settings?.routing_mode === 'auto' ? 'auto' : settings?.default_agent === 'claude' ? 'claude' : settings?.default_agent === 'openrouter' ? 'openrouter' : ''
  const changerDemo = (v: ChoixDemo): void => {
    if (v === 'auto') set({ routing_mode: 'auto' })
    else if (v) set({ routing_mode: 'manual', default_agent: v })
  }

  const apresChangement = async (): Promise<void> => {
    await refreshAgents()
    await refreshStatus()
  }

  return (
    <div className="ecran">
      <TopBar titre="Moteurs IA" />
      <div className="contenu">
        <p className="small muted" style={{ lineHeight: 1.45, padding: '0 4px' }}>
          Par défaut, IRIS utilise le <strong>cerveau VELA inclus</strong> dans votre abonnement — rien à configurer. Vous pouvez aussi brancher une IA qui tourne
          sur votre propre ordinateur. Les clés éventuelles sont stockées dans le coffre du système (
          {status?.secrets_backend === 'keyring' ? 'Gestionnaire d’identifiants' : 'fichier chiffré AES-256'}) et ne quittent jamais votre ordinateur.
        </p>

        <CarteReglage
          titre="Moteurs avancés"
          desc="Réservé à un usage développeur : brancher un accès IA tiers avec votre propre clé. Laissez éteint pour l’usage normal — le cerveau VELA suffit."
          on={avance}
          onChange={setAvance}
        />

        {avance ? (
          <div className="carte col" style={{ gap: 12, border: '1px solid var(--accent-line)' }}>
            <div>
              <h3 style={{ fontSize: 20 }}>Cerveau (démonstration)</h3>
              <div className="small muted" style={{ lineHeight: 1.4 }}>Bascule rapide pendant les essais ; force le moteur choisi pour toutes les demandes. Usage développeur.</div>
            </div>
            <Segmente<ChoixDemo>
              options={[
                { id: 'auto', label: 'Auto' },
                { id: 'claude', label: 'Avancé A' },
                { id: 'openrouter', label: 'Avancé B' }
              ]}
              valeur={choixDemo}
              onChange={changerDemo}
            />
          </div>
        ) : null}

        <div className="carte">
          <SettingRow title="Moteur IA par défaut" desc="Utilisé quand aucune règle de routage ne s’applique.">
            <select className="select" aria-label="Moteur IA par défaut" style={{ width: 200 }} value={settings?.default_agent || ''} onChange={(e) => set({ default_agent: e.target.value })}>
              {optionsDefaut.map((a) => (
                <option key={a.name} value={a.name}>{a.label}</option>
              ))}
            </select>
          </SettingRow>
          <SettingRow title="Routage" desc="Automatique : IRIS choisit le moteur adapté à chaque demande (actions PC, code, images, recherche).">
            <select className="select" aria-label="Routage" style={{ width: 200 }} value={settings?.routing_mode || 'auto'} onChange={(e) => set({ routing_mode: e.target.value })}>
              <option value="auto">Automatique</option>
              <option value="manual">Toujours le moteur par défaut</option>
            </select>
          </SettingRow>
        </div>

        {visibles.map((a) => (
          <AgentCard key={a.name} agent={a} onChanged={apresChangement} />
        ))}
      </div>
    </div>
  )
}

function AgentCard({ agent, onChanged }: { agent: any; onChanged: () => Promise<void> }): JSX.Element {
  const { toast } = useStore()
  const [key, setKey] = useState('')
  const [model, setModel] = useState<string>(agent.model || '')
  const [baseUrl, setBaseUrl] = useState<string>(agent.base_url || '')
  const [label, setLabel] = useState<string>(agent.label || '')
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; message: string; latency_ms?: number } | null>(null)
  const [saving, setSaving] = useState(false)

  // Le service renvoie le moteur mis à jour (agent.updated) : on réaligne les champs.
  useEffect(() => setModel(agent.model || ''), [agent.model])
  useEffect(() => setBaseUrl(agent.base_url || ''), [agent.base_url])
  useEffect(() => setLabel(agent.label || ''), [agent.label])

  const save = async (extra: Record<string, unknown> = {}): Promise<void> => {
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
      toast(messageErreur(err), 'error')
    } finally {
      setSaving(false)
    }
  }

  const test = async (): Promise<void> => {
    setTesting(true)
    setResult(null)
    try {
      if (key.trim() || model !== (agent.model || '') || baseUrl !== (agent.base_url || '')) await save()
      const res = await api.post(`/api/agents/${agent.name}/test`)
      setResult(res)
    } catch (err) {
      setResult({ ok: false, message: messageErreur(err) })
    } finally {
      setTesting(false)
    }
  }

  const activer = (v: boolean): void => {
    api
      .put(`/api/agents/${agent.name}`, { active: v })
      .then(onChanged)
      .catch((err) => toast(messageErreur(err), 'error'))
  }

  const supprimerCle = (): void => {
    if (!window.confirm(`Supprimer la clé du moteur « ${agent.label} » ?`)) return
    api
      .delete(`/api/agents/${agent.name}/key`)
      .then(onChanged)
      .catch((err) => toast(messageErreur(err), 'error'))
  }

  const modeles: any[] = Array.isArray(agent.models) ? agent.models : []

  return (
    <div className="carte col" style={{ gap: 12 }}>
      <div className="row between" style={{ alignItems: 'flex-start', gap: 12 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="row wrap" style={{ gap: 8 }}>
            <strong style={{ fontSize: 19 }}>{agent.label}</strong>
            {agent.vendor ? <span className="small muted">{agent.vendor}</span> : null}
          </div>
          <div className="row wrap" style={{ gap: 6, marginTop: 6 }}>
            {agent.ready ? <span className="pill ok">prêt</span> : agent.active ? <span className="pill warn">clé manquante</span> : <span className="pill">inactif</span>}
            {agent.supports_tools ? <span className="pill" title="Peut agir sur l’ordinateur">outils PC</span> : null}
            {agent.local ? <span className="pill ok">local</span> : null}
          </div>
        </div>
        <div className="row" style={{ gap: 8, flex: 'none' }}>
          <span className="small muted">Activer</span>
          <Toggle on={Boolean(agent.active)} onChange={activer} titre={`Activer ${agent.label}`} />
        </div>
      </div>
      {agent.description ? <p className="small muted" style={{ lineHeight: 1.45 }}>{agent.description}</p> : null}

      {agent.name === 'custom' ? (
        <>
          <Field label="Nom affiché">
            <input className="input" value={label} onChange={(e) => setLabel(e.target.value)} />
          </Field>
          <Field label="URL du serveur (API compatible)" hint="Ollama : http://127.0.0.1:11434/v1 · LM Studio : http://127.0.0.1:1234/v1">
            <input className="input mono" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          </Field>
        </>
      ) : null}
      <Field label="Modèle">
        {modeles.length ? (
          <select className="select" value={model} onChange={(e) => setModel(e.target.value)}>
            {modeles.map((m) => (
              <option key={m.id} value={m.id}>{m.label}</option>
            ))}
            {model && !modeles.some((m) => m.id === model) ? <option value={model}>{model}</option> : null}
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
      <Field
        label={agent.needs_key ? 'Clé API' : 'Clé API (optionnelle)'}
        hint={agent.has_key ? `Clé enregistrée : ${agent.key_masked}` : agent.key_url ? 'Obtenez une clé sur le site du fournisseur.' : undefined}
      >
        <input
          className="input mono"
          type="password"
          autoComplete="off"
          placeholder={agent.has_key ? '•••••••• (laisser vide pour conserver)' : agent.key_hint || ''}
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
      </Field>

      <div className="row wrap" style={{ gap: 8 }}>
        <Holo taille="mini" variante="blanc" disabled={saving} onClick={() => save({ active: true })}>
          {saving ? 'Enregistrement…' : 'Enregistrer et activer'}
        </Holo>
        <button type="button" className="btn sm" disabled={testing || saving} onClick={test}>{testing ? 'Test…' : 'Tester la connexion'}</button>
        {agent.has_key ? <button type="button" className="btn danger sm" onClick={supprimerCle}>Supprimer la clé</button> : null}
        {agent.key_url ? <button type="button" className="btn ghost sm" onClick={() => window.iris.openExternal(agent.key_url)}>Obtenir une clé ↗</button> : null}
      </div>
      {result ? (
        <div>
          <span className={`pill ${result.ok ? 'ok' : 'err'}`}>
            {result.message}
            {result.ok && result.latency_ms ? ` · ${result.latency_ms} ms` : ''}
          </span>
        </div>
      ) : null}
    </div>
  )
}
