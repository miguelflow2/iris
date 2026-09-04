import React, { useCallback, useEffect, useState } from 'react'
import { api, formatDate, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

export function MemoryView(): JSX.Element {
  const { toast, settings, consent } = useStore()
  const [items, setItems] = useState<any[]>([])
  const [count, setCount] = useState(0)
  const [query, setQuery] = useState('')
  const [text, setText] = useState('')

  const load = useCallback(async (q?: string) => {
    const res = await api.get(q ? `/api/memory?q=${encodeURIComponent(q)}` : '/api/memory')
    setItems(res.items)
    if (!q) setCount(res.count)
  }, [])

  useEffect(() => {
    load()
    return api.on((e: IrisEvent) => {
      if (e.type === 'memory.updated') load(query || undefined)
    })
  }, [load, query])

  const add = async () => {
    if (!text.trim()) return
    await api.post('/api/memory', { text: text.trim() })
    setText('')
    load()
  }

  const exportAll = async () => {
    const res = await api.get('/api/memory/export')
    const path = await window.iris.saveFile('iris-memoire.json', typeof res === 'string' ? res : JSON.stringify(res, null, 2))
    if (path) toast(`Mémoire exportée : ${path}`, 'success')
  }

  return (
    <div className="page">
      <h1>Mémoire</h1>
      <p className="lead">
        IRIS ne fabrique aucun souvenir : elle retient ce que vous avez réellement dit, et garde la phrase
        d’origine sous chaque ligne. Si elle n’a pas l’information, elle le dit au lieu de l’inventer.
      </p>
      <p className="lead">
        {count} souvenir{count > 1 ? 's' : ''}, chiffré{count > 1 ? 's' : ''} sur cet ordinateur. Rétention :{' '}
        {settings?.retention_days ? `${settings.retention_days} jour${settings.retention_days > 1 ? 's' : ''}` : 'illimitée'}.
        {consent.memory?.granted ? ' Les souvenirs pertinents sont ajoutés au contexte de l’IA.' : ' Les souvenirs ne sont pas partagés avec l’IA (consentement « mémoire » non accordé).'}
      </p>
      <div className="card col">
        <textarea className="textarea" placeholder="Ajouter un souvenir : une préférence, un fait, une décision…" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) add() }} />
        <div className="row between">
          <span className="small muted">Ctrl+Entrée pour enregistrer. IRIS peut aussi mémoriser à la voix : « Dis-moi Iris, souviens-toi que… »</span>
          <button className="btn primary sm" onClick={add} disabled={!text.trim()}>Mémoriser</button>
        </div>
      </div>
      <div className="row" style={{ margin: '18px 0 10px' }}>
        <input className="input" placeholder="Rechercher dans la mémoire…" value={query} onChange={(e) => { setQuery(e.target.value); load(e.target.value || undefined) }} />
        <button className="btn sm" onClick={() => api.post('/api/memory/summarize-day', {}).then((r) => toast(r.stored ? 'Résumé de la journée enregistré.' : 'Rien à résumer aujourd’hui.', r.stored ? 'success' : 'info')).then(() => load()).catch((e) => toast(e.message, 'error'))}>Résumer la journée</button>
        <button className="btn sm" onClick={exportAll}>Exporter (JSON)</button>
        <button className="btn danger sm" onClick={async () => { if (window.confirm('Effacer toute la mémoire ? Cette action est définitive.')) { await api.delete('/api/memory'); load() } }}>Tout effacer</button>
      </div>
      <div className="list">
        {/* État vide : la branche « recherche » reste sur une seule ligne ; la branche « vide » révèle que la mémoire se remplit aussi toute seule. */}
        {items.length === 0 ? (
          <div className="empty">
            {query ? (
              <div style={{ fontSize: 16, color: 'var(--text)' }}>Aucun souvenir ne correspond à « {query} ».</div>
            ) : (
              <>
                <div style={{ fontSize: 16, color: 'var(--text)' }}>Aucun souvenir pour l’instant.</div>
                <div className="small" style={{ marginTop: 8 }}>Écrivez-en un ci-dessus, ou laissez IRIS le faire : elle retient ce qui compte au fil de vos conversations, en gardant votre phrase d’origine.</div>
              </>
            )}
          </div>
        ) : null}
        {items.map((m) => (
          <div className="list-item" key={m.id}>
            <div className="grow">
              <div style={{ whiteSpace: 'pre-wrap' }}>{m.text}</div>
              {m.source_text ? (
                <div className="origin" title="Phrase exacte dont vient ce souvenir">« {m.source_text} »</div>
              ) : null}
              <div className="small muted">
                {formatDate(m.created_at)} · {m.source === 'user' ? 'vous' : m.source === 'conversation' ? 'retenu de vos mots' : m.source}
                {m.uses ? ` · utilisé ${m.uses} fois` : ''}
                {m.pinned ? ' · épinglé' : ''}
                {m.score ? ` · pertinence ${Math.round(m.score * 100)} %` : ''}
                {m.retained_until ? ` · expire ${formatDate(m.retained_until)}` : ''}
              </div>
            </div>
            <button className="btn ghost sm" title="Supprimer" onClick={() => api.delete(`/api/memory/${m.id}`).then(() => load(query || undefined))}>×</button>
          </div>
        ))}
      </div>
    </div>
  )
}
