import React, { useCallback, useEffect, useRef, useState } from 'react'
import { CarteReglage, Holo, TopBar } from '../components/ui'
import { api, formatDate, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import { labelMoteurPublic } from './ia/commun'

/* =========================================================================
   Confidentialité (porte l'ancienne PrivacyView) : registre de transparence
   chaîné (SHA-256) et sa vérification, mode confidentiel, mode 100 % local,
   indicateur de capture, chiffrement, consentements par type de donnée,
   rétention et purge, export / effacement du registre, et le tableau des
   événements consignés.
   ========================================================================= */

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
  daily_summary: 'Résumé de journée',
  // événements consignés par le service mais absents de l'ancien dictionnaire
  mic_muted: 'Micro coupé',
  mic_unmuted: 'Micro réactivé',
  plan_activated: 'Abonnement activé',
  plan_demo: 'Forfait de démonstration',
  site_credentials_updated: 'Compte web enregistré',
  site_credentials_removed: 'Compte web supprimé',
  web_login: 'Connexion à un site web',
  web_navigation: 'Navigation web',
  lunettes_photo: 'Photo prise par les lunettes',
  courriel_envoye: 'Courriel envoyé',
  identifiants_importes: 'Identifiants importés'
}

/** Colonne « IA » du registre — masque de marque : jamais le nom brut d'un fournisseur à l'écran.
 *  La valeur exacte reste dans l'attribut title (survol) et dans l'export JSON/CSV, pour l'audit.
 *  « local » et « routine » ne sont pas des moteurs externes : on les nomme tels quels plutôt que « VELA ». */
function libelleIaRegistre(agent?: string | null): string {
  if (!agent) return ''
  if (agent === 'local') return 'Local'
  if (agent === 'routine') return 'Routine'
  return labelMoteurPublic(agent)
}

function messageErreur(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

export function ConfidentialiteScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  void params
  const { consent, setConsent, settings, updateSettings, capture, status, toast } = useStore()
  const [events, setEvents] = useState<any[]>([])
  const [check, setCheck] = useState<any | null>(null)
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
      const r = await api.get('/api/privacy/events')
      if (monte.current) setEvents(Array.isArray(r?.events) ? r.events : [])
    } catch (err) {
      if (monte.current) toast(messageErreur(err), 'error')
    }
  }, [toast])

  useEffect(() => {
    load()
    return api.on((e: IrisEvent) => {
      if (['consent.updated', 'chat.done', 'settings.updated', 'privacy.purged', 'agent.updated'].includes(e.type)) load()
    })
  }, [load])

  const verifier = async (): Promise<void> => {
    if (occupe) return
    setOccupe('verifier')
    try {
      const r = await api.get('/api/privacy/verify')
      if (!monte.current) return
      setCheck(r)
      toast(r?.ok ? `Registre intact (${r.count} entrées).` : `Altération détectée à l’entrée ${r?.first_bad_id}.`, r?.ok ? 'success' : 'error')
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const exporter = async (format: 'json' | 'csv'): Promise<void> => {
    if (occupe) return
    if (!api.info) {
      toast('Service IRIS non démarré.', 'error')
      return
    }
    setOccupe(`export-${format}`)
    try {
      const res = await fetch(`${api.info.baseUrl}/api/privacy/export?format=${format}`, { headers: { Authorization: `Bearer ${api.info.token}` } })
      if (!res.ok) throw new Error(`Export impossible (${res.status})`)
      const p = await window.iris.saveFile(`iris-registre.${format}`, await res.text())
      if (p) toast(`Registre exporté : ${p}`, 'success')
      await load()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const effacerRegistre = async (): Promise<void> => {
    if (occupe) return
    if (!window.confirm('Effacer définitivement le registre de transparence ? La chaîne SHA-256 repart à zéro et l’historique est irrécupérable.')) return
    setOccupe('effacer')
    try {
      await api.delete('/api/privacy/events')
      setCheck(null)
      toast('Registre effacé.', 'info')
      await load()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const purger = async (): Promise<void> => {
    if (occupe) return
    if (!window.confirm('Appliquer la purge maintenant ? Les souvenirs, messages et événements plus vieux que la durée de conservation seront supprimés définitivement.')) return
    setOccupe('purger')
    try {
      const r = await api.post('/api/privacy/purge')
      toast(`Purge : ${r?.memories ?? 0} souvenirs, ${r?.messages ?? 0} messages, ${r?.events ?? 0} événements supprimés.`, 'success')
      await load()
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      if (monte.current) setOccupe(null)
    }
  }

  const changerReglage = (patch: Record<string, unknown>): void => {
    updateSettings(patch).catch((err: unknown) => toast(messageErreur(err), 'error'))
  }
  const changerConsentement = (cle: string, v: boolean): void => {
    setConsent(cle, v).catch((err: unknown) => toast(messageErreur(err), 'error'))
  }

  const localOnly = Boolean(settings?.local_only)
  const captureTexte = capture.mic ? 'micro actif' : capture.screen ? 'capture d’écran' : capture.camera ? 'caméra active' : 'aucune capture'
  const captureActive = Boolean(capture.mic || capture.screen || capture.camera)
  const cleMaitresse = status?.key_source === 'keyring' ? 'coffre du système' : 'fichier local protégé'
  const clesApi = status?.secrets_backend === 'keyring' ? 'coffre du système' : 'fichier chiffré'
  const consentements = Object.entries(consent || {}) as [string, any][]

  return (
    <div className="ecran">
      <TopBar titre="Confidentialité" />
      <div className="contenu">
        <div className="small muted" style={{ padding: '0 4px', lineHeight: 1.45 }}>
          Les autres assistants vous demandent de les croire. IRIS vous laisse <strong style={{ color: 'var(--text)' }}>vérifier</strong> : chaque capture et chaque envoi
          est inscrit dans un registre chaîné, que vous pouvez contrôler et exporter vous-même.
        </div>

        {/* bandeau de preuve */}
        <div className="proof">
          <div className="proof-main">
            <div className="proof-label">Registre de transparence</div>
            <div className="proof-state">
              {check
                ? check.ok
                  ? `Intact — ${check.count} entrée${check.count > 1 ? 's' : ''} vérifiée${check.count > 1 ? 's' : ''}`
                  : `Altération détectée à l’entrée ${check.first_bad_id}`
                : 'Chaîne SHA-256 — non vérifiée pour l’instant'}
            </div>
            <div className="proof-hint">Chaque entrée contient l’empreinte de la précédente. Modifier ou retirer une ligne casse la chaîne, et la vérification le montre.</div>
          </div>
          <Holo taille="petit" variante="blanc" disabled={occupe === 'verifier'} onClick={verifier}>
            {occupe === 'verifier' ? 'Vérification…' : 'Vérifier maintenant'}
          </Holo>
        </div>

        <CarteReglage
          titre="Mode confidentiel"
          desc="Coupe le micro et empêche toute écoute ou capture."
          on={Boolean(settings?.privacy_mode)}
          onChange={(v) => changerReglage({ privacy_mode: v })}
        />
        <CarteReglage
          titre="Mode 100 % local"
          desc="Aucun moteur externe : tout est traité sur cet ordinateur."
          on={localOnly}
          onChange={(v) => changerReglage({ local_only: v })}
        />

        <div className="carte reglage">
          <div className="corps">
            <h3>Indicateur de capture</h3>
            <div className="desc">Pastille flottante affichée dès que le micro, l’écran ou la caméra sont utilisés. Elle ne peut pas être désactivée.</div>
          </div>
          <span className={`pill ${captureActive ? 'err' : 'ok'}`}>
            <span className={`dot ${captureActive ? 'rec' : 'on'}`} /> {captureTexte}
          </span>
        </div>

        <div className="carte reglage">
          <div className="corps">
            <h3>Chiffrement au repos</h3>
            <div className="desc">
              AES-256-GCM. Clé maîtresse : {cleMaitresse} · clés API : {clesApi}.
            </div>
          </div>
          <span className="pill ok">actif</span>
        </div>

        <h3 className="section-sous">Consentements</h3>
        {consentements.length === 0 ? (
          <div className="empty">Aucun type de donnée à autoriser pour l’instant.</div>
        ) : (
          consentements.map(([cle, c]) => (
            <CarteReglage
              key={cle}
              titre={String(c?.label || cle)}
              desc={`${c?.description || ''}${c?.updated_at ? ` (modifié le ${formatDate(c.updated_at)})` : ''}`.trim()}
              on={Boolean(c?.granted)}
              disabled={localOnly}
              onChange={(v) => changerConsentement(cle, v)}
            />
          ))
        )}
        {localOnly ? (
          <div className="small muted" style={{ padding: '0 4px', marginTop: -6, lineHeight: 1.4 }}>
            En mode 100 % local, aucune donnée ne sort de l’ordinateur : les consentements sont sans effet tant qu’il est actif.
          </div>
        ) : null}

        <div className="carte">
          <h3>Rétention</h3>
          <div className="desc">Souvenirs, messages et journal sont supprimés physiquement (purge vérifiable) après ce délai.</div>
          <div className="row wrap" style={{ marginTop: 12, gap: 10 }}>
            <select
              className="select"
              style={{ width: 'auto', minWidth: 180 }}
              value={Number(settings?.retention_days ?? 0)}
              onChange={(e) => changerReglage({ retention_days: Number(e.target.value) })}
              aria-label="Durée de conservation"
            >
              <option value={0}>Illimitée</option>
              <option value={1}>24 heures</option>
              <option value={7}>7 jours</option>
              <option value={30}>30 jours</option>
              <option value={90}>90 jours</option>
            </select>
            <button
              type="button"
              className="btn danger"
              title="Supprime immédiatement tout ce qui dépasse la durée de conservation choisie."
              disabled={occupe === 'purger'}
              onClick={purger}
            >
              {occupe === 'purger' ? 'Purge…' : 'Purger maintenant'}
            </button>
          </div>
        </div>

        <h3 className="section-sous">Registre</h3>
        <div className="carte">
          <div className="small muted" style={{ lineHeight: 1.45 }}>
            Chaque capture, envoi externe, commande et consentement est consigné localement et chaîné par empreinte SHA-256 : toute modification a posteriori est
            détectable.
          </div>
          <div className="row wrap" style={{ gap: 8, marginTop: 12 }}>
            <button type="button" className="btn sm" disabled={occupe !== null} onClick={verifier}>Vérifier</button>
            <button type="button" className="btn sm" disabled={occupe !== null} onClick={() => exporter('json')}>Exporter JSON</button>
            <button type="button" className="btn sm" disabled={occupe !== null} onClick={() => exporter('csv')}>Exporter CSV</button>
            <button type="button" className="btn sm danger" disabled={occupe !== null} title="L’historique est supprimé définitivement ; la chaîne SHA-256 repart à zéro." onClick={effacerRegistre}>
              Effacer le registre
            </button>
          </div>
          {check ? (
            <div className="small" style={{ marginTop: 10, color: check.ok ? 'var(--accent-3)' : 'var(--danger)' }}>
              {check.ok
                ? `Intégrité vérifiée : ${check.count} entrées, empreinte finale ${String(check.last_hash || '').slice(0, 16)}…`
                : `Altération détectée à l’entrée n° ${check.first_bad_id}`}
            </div>
          ) : null}
          <div style={{ overflowX: 'auto', marginTop: 12 }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Événement</th>
                  <th>Donnée</th>
                  <th>IA</th>
                  <th>Détail</th>
                </tr>
              </thead>
              <tbody>
                {events.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="muted">
                      Aucun événement consigné pour l’instant. La première capture ou le premier envoi externe s’inscrira ici automatiquement.
                    </td>
                  </tr>
                ) : null}
                {events.map((e) => (
                  <tr key={e.id}>
                    <td className="small muted" style={{ whiteSpace: 'nowrap' }}>{formatDate(e.created_at)}</td>
                    <td>{EVENT_LABEL[e.event_type] || e.event_type}</td>
                    <td className="small">{e.data_type || ''}</td>
                    <td className="small" title={e.agent || undefined}>{libelleIaRegistre(e.agent)}</td>
                    <td className="small muted" style={{ wordBreak: 'break-word', minWidth: 160 }}>{e.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
