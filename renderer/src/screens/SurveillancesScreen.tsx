import React, { useCallback, useEffect, useRef, useState } from 'react'
import { BtnIcone, Field, Holo, TopBar } from '../components/ui'
import { IcoPoubelle } from '../components/icons'
import { api } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   Surveillances (porte l'ancienne WatchesView) : IRIS relit une page à intervalle
   régulier, compare aux critères et prévient. Formulaire, liste des veilles
   (vérifier / arrêter / reprendre / supprimer) et dernières alertes.
   Sondage toutes les 20 s comme l'original (pas d'événement dédié côté service).
   ========================================================================= */

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

type Alerte = {
  id: string
  watch_id: string
  created_at: string
  verdict: string
  summary: string
  excerpt: string
}

type Site = { name: string; label?: string; url?: string }

const VERDICT_LABEL: Record<string, string> = {
  correspond: 'Correspond à vos critères',
  attention: 'À regarder de près',
  info: 'Information',
  rien: 'Rien à signaler'
}

const FORM_VIDE = { name: '', url: '', criteria: '', interval_min: 15, site: '' }

function messageErreur(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

function dateOuJamais(iso: string | null | undefined): string {
  if (!iso) return 'jamais'
  return new Date(iso).toLocaleString('fr-CA', { dateStyle: 'short', timeStyle: 'short' })
}

export function SurveillancesScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  void params
  const { toast, settings, nav } = useStore()
  const [items, setItems] = useState<Watch[]>([])
  const [erreurChargement, setErreurChargement] = useState('')
  const [events, setEvents] = useState<Alerte[]>([])
  const [sites, setSites] = useState<Site[]>([])
  const [form, setForm] = useState({ ...FORM_VIDE })
  const [busy, setBusy] = useState('')
  const monte = useRef(true)
  useEffect(() => {
    monte.current = true
    return () => {
      monte.current = false
    }
  }, [])

  const load = useCallback(async (): Promise<void> => {
    try {
      const r = await api.get('/api/watches')
      if (!monte.current) return
      setItems(Array.isArray(r?.items) ? r.items : [])
      setEvents(Array.isArray(r?.events) ? r.events : [])
      setErreurChargement('')
    } catch (err) {
      // mémorisée pour la pastille « service injoignable » ; l'appelant décide s'il toaste
      if (monte.current) setErreurChargement(messageErreur(err))
      throw err
    }
  }, [])

  useEffect(() => {
    // premier chargement : on dit l'erreur ; le sondage, lui, reste silencieux (pastille seulement)
    load().catch((err) => {
      if (monte.current) toast(messageErreur(err), 'error')
    })
    api
      .get('/api/sites')
      .then((r) => {
        if (monte.current) setSites(Array.isArray(r?.sites) ? r.sites : [])
      })
      .catch(() => undefined)
    const t = window.setInterval(() => load().catch(() => undefined), 20000)
    return () => window.clearInterval(t)
  }, [load, toast])

  const motReveil: string = settings?.wake_word || 'Dis-moi Iris'
  const formulaireValide = Boolean(form.name.trim() && form.url.trim() && form.criteria.trim())

  const creer = async (): Promise<void> => {
    if (!formulaireValide || busy === 'creer') return
    const interval = Number(form.interval_min)
    if (!Number.isFinite(interval) || interval < 2) {
      toast('L’intervalle doit être d’au moins 2 minutes.', 'error')
      return
    }
    setBusy('creer')
    try {
      await api.post('/api/watches', {
        name: form.name.trim(),
        url: form.url.trim(),
        criteria: form.criteria.trim(),
        interval_min: Math.round(interval),
        site: form.site
      })
      setForm({ ...FORM_VIDE })
      toast('Surveillance lancée.', 'success')
      await load()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setBusy('')
    }
  }

  const agir = async (id: string, action: 'check' | 'stop' | 'resume' | 'delete'): Promise<void> => {
    if (action === 'delete' && !window.confirm('Supprimer cette surveillance ? Ses alertes passées resteront dans la liste jusqu’au prochain nettoyage.')) return
    setBusy(id)
    try {
      const r = action === 'delete' ? await api.delete(`/api/watches/${id}`) : await api.post(`/api/watches/${id}/${action}`, {})
      if (action === 'check') toast(r?.message || r?.state || 'Vérification faite.', r?.state === 'correspond' ? 'success' : 'info')
      await load()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setBusy('')
    }
  }

  return (
    <div className="ecran">
      <TopBar titre="Surveillances" />
      <div className="contenu">
        <div className="carte">
          <h3>Ce qu’IRIS fait, et ce qu’elle ne fait pas</h3>
          <div className="desc">
            IRIS relit une page ou une conversation à intervalle régulier, compare les nouveautés à vos critères, et vous prévient à la voix dès qu’ils sont remplis.
          </div>
          <div className="small muted" style={{ marginTop: 10, lineHeight: 1.45 }}>
            Elle lit, analyse, tranche selon vos critères et prépare la décision. Elle ne conclut jamais un achat et n’écrit jamais au fournisseur toute seule : elle
            vous réveille avec l’offre et vous confirmez. Ce que le fournisseur écrit est traité comme du texte à analyser, jamais comme une instruction à suivre.
          </div>
          <div className="small muted" style={{ marginTop: 8, lineHeight: 1.45 }}>
            À la voix : « {motReveil}, surveille ma conversation avec ce fournisseur et préviens-moi si le prix descend sous 2,50 $ l’unité. »
          </div>
        </div>

        <div className="carte">
          <h3>Nouvelle surveillance</h3>
          <div className="col" style={{ marginTop: 10, gap: 12 }}>
            <Field label="Nom">
              <input className="input" placeholder="ex. fournisseur Alibaba" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </Field>
            <Field label="Adresse de la page">
              <input className="input" placeholder="https://…" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
            </Field>
            <Field label="Vos critères" hint="Soyez précis et donnez les chiffres : c’est sur eux qu’IRIS tranche.">
              <textarea
                className="textarea"
                style={{ minHeight: 70 }}
                placeholder="Préviens-moi si le prix descend sous 2,50 $ l’unité pour 500 pièces, ou si le délai de livraison dépasse 30 jours."
                value={form.criteria}
                onChange={(e) => setForm({ ...form, criteria: e.target.value })}
              />
            </Field>
            <Field label="Vérifier toutes les (minutes)" hint="2 minutes au minimum.">
              <input
                className="input"
                type="number"
                min={2}
                step={1}
                value={form.interval_min}
                onChange={(e) => setForm({ ...form, interval_min: Number(e.target.value) })}
              />
            </Field>
            <Field label="Compte web à ouvrir d’abord" hint="Facultatif. Utile si la page exige d’être connecté (comptes enregistrés dans Mon profil › Réglages › Comptes web).">
              <select className="select" value={form.site} onChange={(e) => setForm({ ...form, site: e.target.value })}>
                <option value="">Aucun</option>
                {sites.map((s) => (
                  <option key={s.name} value={s.name}>{s.label || s.name}</option>
                ))}
              </select>
            </Field>
            {/* hors du <label> de Field : un bouton ne peut pas vivre dans le libellé d'un autre contrôle */}
            <div className="row" style={{ marginTop: -4 }}>
              <button type="button" className="btn sm" onClick={() => nav.ouvrir('comptes-web')}>
                Gérer les comptes web
              </button>
            </div>
            <Holo disabled={!formulaireValide || busy === 'creer'} onClick={creer}>
              {busy === 'creer' ? 'Lancement…' : 'Lancer la surveillance'}
            </Holo>
          </div>
        </div>

        <h3 className="section-sous">En cours</h3>
        {erreurChargement ? (
          <div className="row wrap" style={{ gap: 8, marginBottom: 8 }}>
            <span className="pill err" title={erreurChargement}>service injoignable</span>
            <span className="small muted" style={{ wordBreak: 'break-word' }}>La liste ci-dessous n’est peut-être pas à jour.</span>
          </div>
        ) : null}
        {items.length === 0 ? (
          <div className="empty">
            {erreurChargement
              ? 'Impossible de lire la liste des surveillances pour l’instant : le service ne répond pas.'
              : 'Aucune surveillance. Créez-en une ci-dessus, ou demandez-le à la voix.'}
          </div>
        ) : (
          <div className="col" style={{ gap: 10 }}>
            {items.map((w) => (
              <div className="carte serree" key={w.id}>
                <div className="row wrap" style={{ gap: 8 }}>
                  <span style={{ fontWeight: 700, fontSize: 17, wordBreak: 'break-word' }}>{w.name}</span>
                  <span className={`pill ${w.active ? 'ok' : ''}`}>{w.active ? 'active' : 'arrêtée'}</span>
                  {w.alerts > 0 ? <span className="pill">{w.alerts} alerte{w.alerts > 1 ? 's' : ''}</span> : null}
                  {w.last_error ? <span className="pill err">erreur de lecture</span> : null}
                </div>
                {w.url ? <div className="small muted mono" style={{ marginTop: 4, wordBreak: 'break-all' }}>{w.url}</div> : null}
                <div className="small" style={{ color: 'var(--text-2)', marginTop: 6, lineHeight: 1.4 }}>{w.criteria}</div>
                <div className="small muted" style={{ marginTop: 4 }}>
                  Toutes les {w.interval_min} min · {w.checks} vérification{w.checks > 1 ? 's' : ''} · dernière : {dateOuJamais(w.last_check)}
                  {w.site ? ` · compte : ${w.site}` : ''}
                </div>
                {w.last_error ? <div className="small" style={{ color: 'var(--warn)', marginTop: 4, wordBreak: 'break-word' }}>{w.last_error}</div> : null}
                <div className="row wrap" style={{ gap: 6, marginTop: 10 }}>
                  <button type="button" className="btn sm" disabled={busy === w.id} onClick={() => agir(w.id, 'check')}>
                    {busy === w.id ? '…' : 'Vérifier maintenant'}
                  </button>
                  <button type="button" className="btn sm" disabled={busy === w.id} onClick={() => agir(w.id, w.active ? 'stop' : 'resume')}>
                    {w.active ? 'Arrêter' : 'Reprendre'}
                  </button>
                  <span style={{ flex: 1 }} />
                  <BtnIcone aria-label="Supprimer la surveillance" title="Supprimer" disabled={busy === w.id} onClick={() => agir(w.id, 'delete')}>
                    <IcoPoubelle />
                  </BtnIcone>
                </div>
              </div>
            ))}
          </div>
        )}

        <h3 className="section-sous">Dernières alertes</h3>
        {events.length === 0 ? (
          <div className="empty">
            <div style={{ fontSize: 16, color: 'var(--text)' }}>Aucune alerte pour l’instant.</div>
            <div className="small" style={{ marginTop: 8, lineHeight: 1.4 }}>
              Dès qu’une page surveillée remplit vos critères, IRIS vous le dit à voix haute et l’inscrit ici.
            </div>
          </div>
        ) : (
          <div className="col" style={{ gap: 10 }}>
            {events.map((e) => (
              <div className="carte serree" key={e.id}>
                <div className="row wrap" style={{ gap: 8 }}>
                  <span className={`pill ${e.verdict === 'correspond' ? 'ok' : e.verdict === 'attention' ? 'warn' : ''}`}>{VERDICT_LABEL[e.verdict] || e.verdict}</span>
                  <span className="small muted">{dateOuJamais(e.created_at)}</span>
                  {items.find((w) => w.id === e.watch_id)?.name ? <span className="small muted">· {items.find((w) => w.id === e.watch_id)?.name}</span> : null}
                </div>
                <div style={{ marginTop: 6, lineHeight: 1.4, wordBreak: 'break-word' }}>{e.summary}</div>
                {e.excerpt ? <div className="origin">{e.excerpt.slice(0, 300)}</div> : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
