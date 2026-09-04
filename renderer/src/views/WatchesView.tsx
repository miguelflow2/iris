import React, { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useStore } from '../lib/store'

type Watch = {
  id: string
  name: string
  url: string
  site: string
  criteria: string
  interval_min: number
  active: boolean
  last_check: string | null
  checks: number
  alerts: number
  last_error: string | null
}

type Event = {
  id: string
  watch_id: string
  created_at: string
  verdict: string
  summary: string
  excerpt: string
}

const VERDICT_LABEL: Record<string, string> = {
  correspond: 'Correspond à vos critères',
  attention: 'À regarder de près',
  info: 'Information',
  rien: 'Rien à signaler'
}

function formatDate(iso: string | null): string {
  if (!iso) return 'jamais'
  return new Date(iso).toLocaleString('fr-CA', { dateStyle: 'short', timeStyle: 'short' })
}

export function WatchesView(): JSX.Element {
  const { toast } = useStore()
  const [items, setItems] = useState<Watch[]>([])
  const [events, setEvents] = useState<Event[]>([])
  const [form, setForm] = useState({ name: '', url: '', criteria: '', interval_min: 15, site: '' })
  const [busy, setBusy] = useState('')

  const load = async (): Promise<void> => {
    const r = await api.get('/api/watches')
    setItems(r.items || [])
    setEvents(r.events || [])
  }

  useEffect(() => {
    load().catch(() => undefined)
    const t = setInterval(() => load().catch(() => undefined), 20000)
    return () => clearInterval(t)
  }, [])

  const creer = async (): Promise<void> => {
    try {
      await api.post('/api/watches', form)
      setForm({ name: '', url: '', criteria: '', interval_min: 15, site: '' })
      toast('Surveillance lancée.', 'success')
      await load()
    } catch (e: any) {
      toast(e.message, 'error')
    }
  }

  const agir = async (id: string, action: string): Promise<void> => {
    setBusy(id)
    try {
      const r = action === 'delete' ? await api.delete(`/api/watches/${id}`) : await api.post(`/api/watches/${id}/${action}`, {})
      if (action === 'check') toast(r.message || r.state, r.state === 'correspond' ? 'success' : 'info')
      await load()
    } catch (e: any) {
      toast(e.message, 'error')
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="page">
      <h1>Surveillances</h1>
      <p className="lead">
        IRIS relit une page ou une conversation à intervalle régulier, compare les nouveautés à vos critères, et vous
        prévient à la voix dès qu’ils sont remplis. Vous pouvez aussi la lancer en parlant : « Dis-moi Iris, surveille
        ma conversation avec ce fournisseur et préviens-moi si le prix descend sous 2,50 $ l’unité. »
      </p>

      <div className="card col">
        <strong>Ce qu’IRIS fait, et ce qu’elle ne fait pas</strong>
        <div className="small muted">
          Elle lit, analyse, tranche selon vos critères et prépare la décision. Elle ne conclut jamais un achat et
          n’écrit jamais au fournisseur toute seule : elle vous réveille avec l’offre et vous confirmez. Ce que le
          fournisseur écrit est traité comme du texte à analyser, jamais comme une instruction à suivre.
        </div>
      </div>

      <h2>Nouvelle surveillance</h2>
      <div className="card col">
        <div className="grid-2">
          <label className="field">
            Nom
            <input className="input" placeholder="fournisseur Alibaba" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </label>
          <label className="field">
            Adresse de la page
            <input className="input" placeholder="https://message.alibaba.com/…" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
          </label>
        </div>
        <label className="field">
          Vos critères
          <textarea
            className="textarea"
            style={{ minHeight: 70 }}
            placeholder="Préviens-moi si le prix descend sous 2,50 $ l’unité pour 500 pièces, ou si le délai de livraison dépasse 30 jours."
            value={form.criteria}
            onChange={(e) => setForm({ ...form, criteria: e.target.value })}
          />
          <span className="hint">Soyez précis et donnez les chiffres : c’est sur eux qu’IRIS tranche.</span>
        </label>
        <div className="grid-2">
          <label className="field">
            Vérifier toutes les
            <input className="input" type="number" min={2} value={form.interval_min} onChange={(e) => setForm({ ...form, interval_min: Number(e.target.value) })} />
            <span className="hint">minutes (2 au minimum)</span>
          </label>
          <label className="field">
            Compte web à ouvrir d’abord
            <input className="input" placeholder="facultatif : nom du compte enregistré" value={form.site} onChange={(e) => setForm({ ...form, site: e.target.value })} />
            <span className="hint">Utile si la page exige d’être connecté.</span>
          </label>
        </div>
        <div className="row">
          <button className="btn primary" disabled={!form.name.trim() || !form.url.trim() || !form.criteria.trim()} onClick={creer}>
            Lancer la surveillance
          </button>
        </div>
      </div>

      <h2>En cours</h2>
      {items.length === 0 ? (
        <div className="empty">Aucune surveillance. Créez-en une ci-dessus, ou demandez-le à la voix.</div>
      ) : (
        <div className="list">
          {items.map((w) => (
            <div className="list-item" key={w.id}>
              <div className="grow">
                <div className="row wrap" style={{ gap: 8 }}>
                  <strong>{w.name}</strong>
                  <span className={`pill ${w.active ? 'ok' : ''}`}>{w.active ? 'active' : 'arrêtée'}</span>
                  {w.alerts > 0 ? <span className="pill">{w.alerts} alerte{w.alerts > 1 ? 's' : ''}</span> : null}
                  {w.last_error ? <span className="pill err">erreur de lecture</span> : null}
                </div>
                <div className="small" style={{ color: 'var(--text-2)' }}>{w.criteria}</div>
                <div className="small muted">
                  Toutes les {w.interval_min} min · {w.checks} vérification{w.checks > 1 ? 's' : ''} · dernière : {formatDate(w.last_check)}
                </div>
                {w.last_error ? <div className="small" style={{ color: 'var(--warn)' }}>{w.last_error}</div> : null}
              </div>
              <div className="row" style={{ gap: 6 }}>
                <button className="btn sm" disabled={busy === w.id} onClick={() => agir(w.id, 'check')}>
                  {busy === w.id ? '…' : 'Vérifier maintenant'}
                </button>
                <button className="btn sm" onClick={() => agir(w.id, w.active ? 'stop' : 'resume')}>{w.active ? 'Arrêter' : 'Reprendre'}</button>
                <button className="btn danger sm" onClick={() => agir(w.id, 'delete')}>Supprimer</button>
              </div>
            </div>
          ))}
        </div>
      )}

      <h2>Dernières alertes</h2>
      {events.length === 0 ? (
        <div className="empty">
          <div style={{ fontSize: 16, color: 'var(--text)' }}>Aucune alerte pour l’instant.</div>
          <div className="small" style={{ marginTop: 8 }}>Dès qu’une page surveillée remplit vos critères, IRIS vous le dit à voix haute et l’inscrit ici.</div>
        </div>
      ) : (
        <div className="list">
          {events.map((e) => (
            <div className="list-item" key={e.id}>
              <div className="grow">
                <div className="row" style={{ gap: 8 }}>
                  <span className={`pill ${e.verdict === 'correspond' ? 'ok' : e.verdict === 'attention' ? 'warn' : ''}`}>
                    {VERDICT_LABEL[e.verdict] || e.verdict}
                  </span>
                  <span className="small muted">{formatDate(e.created_at)}</span>
                </div>
                <div style={{ marginTop: 4 }}>{e.summary}</div>
                {e.excerpt ? <div className="origin">{e.excerpt.slice(0, 300)}</div> : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
