import React, { useCallback, useEffect, useState } from 'react'
import { api, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

export function PlanView(): JSX.Element {
  const { toast, updateSettings } = useStore()
  const [info, setInfo] = useState<any | null>(null)
  const [key, setKey] = useState('')
  const [email, setEmail] = useState('')
  const [licence, setLicence] = useState<any>(null)
  const [syncing, setSyncing] = useState(false)
  const load = useCallback(() => api.get('/api/plan').then(setInfo).catch(() => undefined), [])
  useEffect(() => {
    api.get('/api/plan/licence').then((r) => { setLicence(r); if (r.email) setEmail(r.email) }).catch(() => undefined)
    load()
    return api.on((e: IrisEvent) => {
      if (['plan.changed', 'plan.quota', 'chat.done', 'settings.updated'].includes(e.type)) load()
    })
  }, [load])
  if (!info) return <div className="page" />
  const u = info.usage
  const pct = Math.min(100, Math.round((u.requests_ratio || 0) * 100))
  return (
    <div className="page">
      <h1>Abonnement</h1>
      <p className="lead">Plan actuel : <strong>{info.label}</strong>{info.demo ? ' (mode démonstration)' : ''}{info.expires ? ` · valable jusqu’au ${info.expires}` : ''}. Le quota se renouvelle chaque mois ; IRIS vous prévient à 80 % et 95 %.</p>
      {(info.byok?.models || info.byok?.tts) && <p className="muted">Clés personnelles détectées ({[info.byok?.models && 'OpenRouter', info.byok?.tts && 'ElevenLabs'].filter(Boolean).join(' + ')}) : ce que vos clés paient n’est pas bridé par le plan (voix ElevenLabs, écran, mémoire, tâches, web, quota). Le plan s’applique aux ressources fournies par VELA.</p>}

      <div className="card col">
        <div className="row between"><strong>Utilisation ce mois-ci ({u.month})</strong><span className="small muted">{u.requests} / {u.requests_limit} requêtes</span></div>
        <div className="progress"><div style={{ width: `${pct}%`, background: pct >= 95 ? 'var(--danger)' : pct >= 80 ? 'var(--warn)' : 'var(--accent-2)' }} /></div>
        {u.tts_chars_limit ? <div className="small muted">Voix ElevenLabs : {u.tts_chars} / {u.tts_chars_limit} caractères</div> : <div className="small muted">Voix Windows incluse (ElevenLabs à partir du plan Essentiel).</div>}
      </div>

      <div className="grid-2" style={{ marginTop: 16 }}>
        {info.plans.map((p: any) => (
          <div className="card" key={p.name} style={{ borderColor: p.name === info.plan ? 'var(--accent)' : undefined }}>
            <div className="row between"><strong style={{ fontSize: 16 }}>{p.label}</strong><span>{p.price === 0 ? 'Gratuit' : `${p.price.toFixed(2)} $ / mois`}</span></div>
            <ul className="small" style={{ paddingLeft: 18, margin: '8px 0' }}>{p.contents.map((c: string) => <li key={c}>{c}</li>)}</ul>
            <div className="small muted">{p.quota_requests} requêtes / mois</div>
            <div className="row wrap" style={{ marginTop: 10 }}>
              {p.name === info.plan ? <span className="pill ok">plan actuel</span> : null}
              {p.pay_url ? (
                <button
                  className="btn primary sm"
                  title={`Ouvre PayPal avec ${p.price.toFixed(2)} $ déjà rempli`}
                  onClick={() => window.iris.openExternal(p.pay_url)}
                >
                  S’abonner · {p.price.toFixed(2)} $
                </button>
              ) : null}
              {p.name === info.plan ? null : (
                <button className="btn sm" onClick={() => api.post('/api/plan/demo', { plan: p.name }).then(() => toast(`Plan ${p.label} activé en mode démonstration.`, 'success')).then(load).catch((e) => toast(e.message, 'error'))}>Essayer (démo)</button>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="card col" style={{ marginTop: 16 }}>
        <strong>Activer une clé d’abonnement</strong>
        <div className="row">
          <input className="input mono" placeholder="IRIS-…" value={key} onChange={(e) => setKey(e.target.value)} />
          <button className="btn primary sm" disabled={!key.trim()} onClick={() => api.post('/api/plan/activate', { key: key.trim() }).then((r) => { setKey(''); toast(`Plan ${r.label} activé.`, 'success'); load() }).catch((e) => toast(e.message, 'error'))}>Activer</button>
        </div>
        <div className="small muted">
          Le mode démonstration sert aux essais et aux présentations ; il ne remplace pas une clé.
        </div>
      </div>

      <div className="card col" style={{ marginTop: 16 }}>
        <div className="row between wrap">
          <strong>Activation automatique</strong>
          {licence?.last_result ? <span className="pill">{licence.last_result}</span> : null}
        </div>
        <div className="small muted">
          Indiquez le courriel utilisé pour payer : IRIS récupère votre abonnement toute seule et le renouvelle
          sans que vous ayez à coller quoi que ce soit. Elle revérifie une fois par jour.
        </div>
        <div className="row wrap">
          <input
            className="input"
            style={{ maxWidth: 320 }}
            type="email"
            placeholder="courriel utilisé pour le paiement"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <button
            className="btn sm"
            disabled={!email.trim() || syncing}
            onClick={async () => {
              setSyncing(true)
              try {
                await updateSettings({ licence_email: email.trim(), licence_auto: true })
                const r = await api.post('/api/plan/sync', {})
                toast(r.message, r.state === 'activé' || r.state === 'à jour' ? 'success' : 'error')
                await load()
                setLicence(await api.get('/api/plan/licence'))
              } catch (e: any) {
                toast(e.message, 'error')
              } finally {
                setSyncing(false)
              }
            }}
          >
            {syncing ? 'Vérification…' : 'Vérifier mon abonnement'}
          </button>
        </div>
        {licence?.last_check ? <div className="small muted">Dernière vérification : {new Date(licence.last_check).toLocaleString('fr-CA')}</div> : null}
      </div>

      <div className="card col" style={{ marginTop: 16 }}>
        <strong>Comment ça se passe</strong>
        <ol className="small" style={{ paddingLeft: 20, margin: '4px 0 0', color: 'var(--text-2)' }}>
          <li>Vous cliquez sur « S’abonner », PayPal s’ouvre avec le montant déjà rempli.</li>
          <li>Vous envoyez la confirmation de paiement à {info.payment?.support_email}.</li>
          <li>Votre abonnement s’active tout seul dès que vous indiquez ce courriel ci-dessus. La clé reçue
            par courriel reste utilisable si vous préférez la coller à la main.</li>
        </ol>
        <div className="small muted">
          Le paiement PayPal est un versement unique : il ne se renouvelle pas tout seul et n’active rien
          automatiquement. Vous serez prévenu avant l’échéance de votre clé.
        </div>
      </div>

      <div className="card col" style={{ marginTop: 16 }}>
        <div className="row between wrap">
          <div>
            <strong>{info.lunettes.label}</strong>
            <div className="small muted">Les lunettes VELA avec douze mois du plan Pro inclus.</div>
          </div>
          <div className="row">
            <strong style={{ fontSize: 17 }}>{info.lunettes.price.toFixed(2)} $</strong>
            {info.lunettes.pay_url ? (
              <button className="btn primary" onClick={() => window.iris.openExternal(info.lunettes.pay_url)}>
                Acheter les lunettes
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}
