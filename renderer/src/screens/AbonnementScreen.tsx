import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Field, Holo, Toggle, TopBar } from '../components/ui'
import { api, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   Abonnement (porte l'ancienne PlanView) : forfait courant et usage du mois,
   grille des forfaits (paiement externe + essai démo), clé d'activation,
   activation automatique par courriel d'achat, marche à suivre, et l'achat des
   lunettes / du forfait. Tout vient de GET /api/plan et GET /api/plan/licence.
   ========================================================================= */

function messageErreur(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

function prix(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return ''
  return `${n.toFixed(2)} $`
}

export function AbonnementScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  void params
  const { toast, settings, updateSettings } = useStore()
  const [info, setInfo] = useState<any | null>(null)
  const [erreur, setErreur] = useState('')
  const [key, setKey] = useState('')
  const [email, setEmail] = useState('')
  const [licence, setLicence] = useState<any>(null)
  const [occupe, setOccupe] = useState<string | null>(null)
  const monte = useRef(true)
  useEffect(() => {
    monte.current = true
    return () => {
      monte.current = false
    }
  }, [])

  const load = useCallback(async () => {
    try {
      const r = await api.get('/api/plan')
      if (monte.current) {
        setInfo(r)
        setErreur('')
      }
    } catch (err) {
      if (monte.current) setErreur(messageErreur(err))
    }
  }, [])

  const chargerLicence = useCallback(async () => {
    try {
      const r = await api.get('/api/plan/licence')
      if (!monte.current) return
      setLicence(r)
      if (r?.email) setEmail((e) => e || String(r.email))
    } catch {
      /* activation automatique non configurée : on continue */
    }
  }, [])

  useEffect(() => {
    load()
    chargerLicence()
    return api.on((e: IrisEvent) => {
      if (['plan.changed', 'plan.quota', 'chat.done', 'settings.updated'].includes(e.type)) load()
    })
  }, [load, chargerLicence])

  // le courriel d'achat enregistré dans les réglages a priorité sur un champ vide
  useEffect(() => {
    if (settings?.licence_email) setEmail((e) => e || String(settings.licence_email))
  }, [settings?.licence_email])

  const activerCle = async (): Promise<void> => {
    const k = key.trim()
    if (!k || occupe) return
    setOccupe('cle')
    try {
      const r = await api.post('/api/plan/activate', { key: k })
      setKey('')
      toast(`Plan ${r?.label || ''} activé.`.replace('  ', ' '), 'success')
      await load()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const essayerDemo = async (p: any): Promise<void> => {
    if (occupe) return
    setOccupe(`demo-${p.name}`)
    try {
      await api.post('/api/plan/demo', { plan: p.name })
      toast(`Plan ${p.label} activé en mode démonstration.`, 'success')
      await load()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const verifierAbonnement = async (): Promise<void> => {
    const e = email.trim()
    if (!e || occupe) return
    setOccupe('sync')
    try {
      await updateSettings({ licence_email: e, licence_auto: true })
      const r = await api.post('/api/plan/sync', {})
      toast(r?.message || 'Vérification faite.', r?.state === 'activé' || r?.state === 'à jour' ? 'success' : 'error')
      await load()
      await chargerLicence()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const changerAuto = (v: boolean): void => {
    updateSettings({ licence_auto: v })
      .then(() => chargerLicence())
      .catch((err: unknown) => toast(messageErreur(err), 'error'))
  }

  const ouvrir = (url: string | undefined): void => {
    if (url) window.iris.openExternal(url)
    else toast('Lien de paiement indisponible pour l’instant.', 'info')
  }

  if (!info) {
    return (
      <div className="ecran">
        <TopBar titre="Abonnement" />
        <div className="contenu">
          {erreur ? (
            <div className="carte">
              <h3>Abonnement indisponible</h3>
              <div className="desc">{erreur}</div>
              <div style={{ marginTop: 12 }}>
                <button type="button" className="btn sm" onClick={load}>Réessayer</button>
              </div>
            </div>
          ) : (
            <div className="empty">Chargement de l’abonnement…</div>
          )}
        </div>
      </div>
    )
  }

  const u = info.usage || {}
  const pct = Math.min(100, Math.round((Number(u.requests_ratio) || 0) * 100))
  const couleur = pct >= 95 ? 'var(--red)' : pct >= 80 ? 'var(--orange)' : undefined
  const ttsLimite = Number(u.tts_chars_limit) || 0
  const ttsPct = ttsLimite ? Math.min(100, Math.round(((Number(u.tts_chars) || 0) / ttsLimite) * 100)) : 0
  const ttsCouleur = ttsPct >= 95 ? 'var(--red)' : ttsPct >= 80 ? 'var(--orange)' : undefined
  const byokModels = Boolean(info.byok?.models)
  const byokTts = Boolean(info.byok?.tts)
  const plans: any[] = Array.isArray(info.plans) ? info.plans : []
  const supportEmail: string = info.payment?.support_email || ''
  const licenceAuto = Boolean(settings?.licence_auto ?? licence?.auto)

  return (
    <div className="ecran">
      <TopBar titre="Abonnement" />
      <div className="contenu">
        {/* forfait courant */}
        <div className="carte">
          <div className="row between wrap" style={{ gap: 8 }}>
            <h3 style={{ margin: 0 }}>Votre forfait</h3>
            <div className="row wrap" style={{ gap: 6 }}>
              {info.demo ? <span className="pill warn">démonstration</span> : null}
              {info.expires ? <span className="pill">valable jusqu’au {info.expires}</span> : null}
            </div>
          </div>
          <div style={{ fontSize: 26, fontWeight: 800, marginTop: 8, letterSpacing: '-0.01em' }}>{info.label}</div>
          <div className="desc">{Number(info.price) === 0 ? 'Gratuit' : `${prix(info.price)} / mois`}</div>
          <div className="small muted" style={{ marginTop: 8, lineHeight: 1.45 }}>
            Le quota se renouvelle chaque mois ; IRIS vous prévient à 80 % et 95 %.
          </div>
          {byokModels || byokTts ? (
            <div className="small muted" style={{ marginTop: 8, lineHeight: 1.45 }}>
              Clés personnelles détectées ({[byokModels && 'modèles', byokTts && 'voix'].filter(Boolean).join(' + ')}) : ce que vos clés paient n’est pas bridé par le
              plan (voix, écran, mémoire, tâches, web, quota). Le plan s’applique aux ressources fournies par VELA.
            </div>
          ) : null}

          <div style={{ marginTop: 16 }}>
            <div className="row between" style={{ marginBottom: 6 }}>
              <span style={{ fontWeight: 600 }}>Utilisation ce mois-ci{u.month ? ` (${u.month})` : ''}</span>
              <span className="small muted">
                {Number(u.requests) || 0} / {Number(u.requests_limit) || 0} requêtes
              </span>
            </div>
            <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
              <div style={{ width: `${pct}%`, background: couleur }} />
            </div>
          </div>
          {ttsLimite ? (
            <div style={{ marginTop: 12 }}>
              <div className="row between" style={{ marginBottom: 6 }}>
                <span style={{ fontWeight: 600 }}>Voix naturelle</span>
                <span className="small muted">
                  {Number(u.tts_chars) || 0} / {ttsLimite} caractères{typeof u.tts_chars_left === 'number' ? ` · ${u.tts_chars_left} restants` : ''}
                </span>
              </div>
              <div className="progress" role="progressbar" aria-valuenow={ttsPct} aria-valuemin={0} aria-valuemax={100}>
                <div style={{ width: `${ttsPct}%`, background: ttsCouleur }} />
              </div>
            </div>
          ) : (
            <div className="small muted" style={{ marginTop: 10 }}>Voix de l’ordinateur incluse (voix naturelle à partir d’un forfait payant).</div>
          )}
        </div>

        {/* grille des forfaits */}
        <h3 className="section-sous">Forfaits</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 12 }}>
          {plans.map((p: any) => {
            const courant = p.name === info.plan
            const contents: string[] = Array.isArray(p.contents) ? p.contents : []
            return (
              <div className="carte" key={p.name} style={{ display: 'flex', flexDirection: 'column', gap: 8, outline: courant ? '1.5px solid var(--blue)' : undefined }}>
                <div className="row between wrap" style={{ gap: 6 }}>
                  <span style={{ fontWeight: 800, fontSize: 19 }}>{p.label}</span>
                  {courant ? <span className="pill ok">plan actuel</span> : null}
                </div>
                <div style={{ fontSize: 22, fontWeight: 700 }}>{Number(p.price) === 0 ? 'Gratuit' : `${prix(p.price)} / mois`}</div>
                {contents.length ? (
                  <ul className="small" style={{ paddingLeft: 18, margin: '2px 0', color: 'var(--text-2)', lineHeight: 1.45 }}>
                    {contents.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                ) : null}
                {typeof p.quota_requests === 'number' ? <div className="small muted">{p.quota_requests} requêtes / mois</div> : null}
                <div className="col" style={{ marginTop: 'auto', paddingTop: 6, gap: 8 }}>
                  {p.pay_url ? (
                    <Holo taille="petit" style={{ width: '100%' }} title={`Ouvre la page de paiement avec ${prix(p.price)} déjà rempli`} onClick={() => ouvrir(p.pay_url)}>
                      Choisir · {prix(p.price)}
                    </Holo>
                  ) : null}
                  {!courant ? (
                    <button type="button" className="btn sm" disabled={occupe === `demo-${p.name}`} onClick={() => essayerDemo(p)}>
                      {occupe === `demo-${p.name}` ? '…' : 'Essayer (démo)'}
                    </button>
                  ) : null}
                </div>
              </div>
            )
          })}
        </div>

        {/* clé d'activation */}
        <div className="carte">
          <h3>Clé d’activation</h3>
          <div className="desc">Collez la clé reçue par courriel après votre paiement.</div>
          <div className="row" style={{ marginTop: 12, gap: 10 }}>
            <input
              className="input mono"
              style={{ fontSize: 15 }}
              placeholder="IRIS-…"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') activerCle()
              }}
              aria-label="Clé d’activation"
            />
            <Holo taille="petit" disabled={!key.trim() || occupe === 'cle'} onClick={activerCle}>
              {occupe === 'cle' ? 'Activation…' : 'Activer'}
            </Holo>
          </div>
          <div className="small muted" style={{ marginTop: 8, lineHeight: 1.4 }}>Le mode démonstration sert aux essais et aux présentations ; il ne remplace pas une clé.</div>
        </div>

        {/* activation automatique */}
        <div className="carte">
          <div className="row between wrap" style={{ gap: 8 }}>
            <h3 style={{ margin: 0 }}>Activation automatique</h3>
            {licence?.last_result ? <span className="pill">{String(licence.last_result)}</span> : null}
          </div>
          <div className="desc" style={{ marginTop: 6 }}>
            Indiquez le courriel utilisé pour payer : IRIS récupère votre abonnement toute seule et le renouvelle sans que vous ayez à coller quoi que ce soit. Elle
            revérifie une fois par jour.
          </div>
          <div className="col" style={{ marginTop: 12, gap: 12 }}>
            <Field label="Courriel d’achat">
              <input className="input" type="email" placeholder="courriel utilisé pour le paiement" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <div className="row between" style={{ gap: 12 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600 }}>Vérification quotidienne</div>
                <div className="small muted">IRIS interroge le serveur de licences une fois par jour.</div>
              </div>
              <Toggle on={licenceAuto} onChange={changerAuto} titre="Vérification quotidienne" />
            </div>
            <div className="row wrap" style={{ gap: 8 }}>
              <button type="button" className="btn" disabled={!email.trim() || occupe === 'sync'} onClick={verifierAbonnement}>
                {occupe === 'sync' ? 'Vérification…' : 'Vérifier mon abonnement'}
              </button>
              {licence?.last_check ? <span className="small muted">Dernière vérification : {new Date(licence.last_check).toLocaleString('fr-CA')}</span> : null}
            </div>
            {licence && !licence.server ? (
              <div className="small muted">Aucun serveur de licences n’est configuré : l’activation automatique ne peut pas encore fonctionner.</div>
            ) : null}
          </div>
        </div>

        {/* marche à suivre */}
        <div className="carte">
          <h3>Comment ça se passe</h3>
          <ol className="small" style={{ paddingLeft: 20, margin: '4px 0 0', color: 'var(--text-2)', lineHeight: 1.5 }}>
            <li>Vous cliquez sur « Choisir », la page de paiement s’ouvre avec le montant déjà rempli.</li>
            <li>Vous envoyez la confirmation de paiement{supportEmail ? ` à ${supportEmail}` : ''}.</li>
            <li>
              Votre abonnement s’active tout seul dès que vous indiquez ce courriel ci-dessus. La clé reçue par courriel reste utilisable si vous préférez la coller à la
              main.
            </li>
          </ol>
          <div className="small muted" style={{ marginTop: 8, lineHeight: 1.45 }}>
            Le paiement est un versement unique : il ne se renouvelle pas tout seul et n’active rien automatiquement. Vous serez prévenu avant l’échéance de votre clé.
          </div>
        </div>

        {/* lunettes */}
        {info.lunettes ? (
          <div className="carte">
            <div className="row between wrap" style={{ gap: 8 }}>
              <h3 style={{ margin: 0 }}>{info.lunettes.label}</h3>
              <span style={{ fontSize: 20, fontWeight: 800 }}>{prix(info.lunettes.price)}</span>
            </div>
            <div className="desc" style={{ marginTop: 6 }}>Paiement unique. Aucun abonnement forcé : elles fonctionnent dès le forfait gratuit d’IRIS.</div>
            <div style={{ marginTop: 14 }}>
              <Holo onClick={() => ouvrir(info.lunettes.pay_url)}>Acheter les lunettes</Holo>
            </div>
          </div>
        ) : null}
        {info.lunettes_forfait ? (
          <div className="carte" style={{ outline: '1.5px solid var(--blue-2)' }}>
            <div className="row between wrap" style={{ gap: 8 }}>
              <h3 style={{ margin: 0 }}>{info.lunettes_forfait.label}</h3>
              <span style={{ fontSize: 20, fontWeight: 800 }}>{prix(info.lunettes_forfait.price)}</span>
            </div>
            <div className="desc" style={{ marginTop: 6 }}>
              {info.lunettes_forfait.note ? `${info.lunettes_forfait.note} ` : ''}Offre supplémentaire.
            </div>
            <div style={{ marginTop: 14 }}>
              <Holo variante="contour" onClick={() => ouvrir(info.lunettes_forfait.pay_url)}>Choisir le forfait</Holo>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
