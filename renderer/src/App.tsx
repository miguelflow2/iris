import React from 'react'
import { Failure, Splash } from './components/Boot'
import { Voile } from './components/Voile'
import { Modal } from './components/ui'
import { useStore, type View } from './lib/store'
import { AgentsView } from './views/AgentsView'
import { ChatView } from './views/ChatView'
import { GlassesView } from './views/GlassesView'
import { MemoryView } from './views/MemoryView'
import { Onboarding } from './views/Onboarding'
import { PlanView } from './views/PlanView'
import { PrivacyView } from './views/PrivacyView'
import { RoutinesView } from './views/RoutinesView'
import { SettingsView } from './views/SettingsView'
import { TasksView } from './views/TasksView'
import { WatchesView } from './views/WatchesView'

// Navigation : cinq entrées, pas dix. Une barre latérale qui énumère « Routines », « Tâches »,
// « Surveillances », « Confidentialité », « Mémoire », « Moteurs IA », « Abonnement » et
// « Paramètres » demande à l'utilisateur de deviner où chercher avant même d'avoir parlé. Ce qui
// va ensemble se regroupe, et les pages secondaires deviennent des onglets à l'intérieur.
// Les identifiants de vue ne changent jamais : seul l'emballage bouge.
type Entree = { id: View; label: string; icon: string; onglets?: { id: View; label: string }[] }

const NAV: Entree[] = [
  { id: 'chat', label: 'Conversation', icon: '◎' },
  { id: 'glasses', label: 'Lunettes', icon: '◠' },
  { id: 'memory', label: 'Mémoire', icon: '◫' },
  {
    id: 'routines',
    label: 'Elle travaille seule',
    icon: '⟳',
    onglets: [
      { id: 'routines', label: 'Routines et rappels' },
      { id: 'tasks', label: 'Tâches' },
      { id: 'watches', label: 'Surveillances' }
    ]
  },
  {
    id: 'settings',
    label: 'Réglages',
    icon: '⚙',
    onglets: [
      { id: 'settings', label: 'Paramètres' },
      { id: 'privacy', label: 'Confidentialité' },
      { id: 'plan', label: 'Abonnement' },
      { id: 'agents', label: 'Moteurs IA' }
    ]
  }
]

/** L'entrée de la barre latérale à laquelle appartient la vue ouverte. */
function entreeDe(view: View): Entree | undefined {
  return NAV.find((e) => e.id === view || (e.onglets || []).some((o) => o.id === view))
}

export default function App(): JSX.Element {
  const store = useStore()
  const { backendState, view, setView, capture, voice, settings, status, toasts, dismissToast, confirmRequest, answerConfirm, consentRequest, closeConsentRequest, setConsent, appInfo } = store

  // Écrans de démarrage et de panne : extraits dans components/Boot.tsx, parce qu'ils ont
  // leur propre état (temps écoulé, relance en cours) et que les hooks ne peuvent pas
  // vivre ici, avant les retours anticipés.
  if (backendState === 'starting' || (backendState === 'ready' && !settings)) {
    return <Splash logPath={appInfo?.logPath} />
  }
  if (backendState === 'failed' || backendState === 'down') {
    return <Failure down={backendState === 'down'} message={store.backendMessage} logPath={appInfo?.logPath} />
  }

  const content = {
    chat: <ChatView />,
    agents: <AgentsView />,
    glasses: <GlassesView />,
    routines: <RoutinesView />,
    watches: <WatchesView />,
    memory: <MemoryView />,
    tasks: <TasksView />,
    privacy: <PrivacyView />,
    plan: <PlanView />,
    settings: <SettingsView />
  }[view]

  const agentsReady: string[] = status?.agents_available || []
  const voiceState = voice?.state || 'off'

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          {/* Variante claire : l'application est sur fond encre, la grand-voile y est crème. */}
          <Voile taille={30} variante="clair" className="voile lueur" titre="VELA" />
          <div>
            <div className="name">IRIS</div>
            <div className="sub">VELA</div>
          </div>
        </div>
        {/* Une phrase, sous la marque : quelqu'un qui découvre l'application en direct doit
            savoir ce qu'elle est avant de lire la navigation. */}
        <div className="brand-claim">Assistante vocale qui agit sur votre ordinateur.</div>
        <div className="nav-scroll">
        {NAV.map((item) => {
          const actif = entreeDe(view)?.id === item.id
          return (
            <button key={item.id} className={`nav-btn ${actif ? 'active' : ''}`} onClick={() => setView(item.id)}>
              <span style={{ width: 16, textAlign: 'center', color: 'var(--muted)' }}>{item.icon}</span>
              {item.label}
              {item.id === 'glasses' && status?.glasses?.connected ? <span className="badge" style={{ color: 'var(--accent-2)' }}>●</span> : null}
              {item.id === 'settings' && settings?.local_only ? <span className="badge">local</span> : null}
              {item.id === 'settings' && status?.plan ? <span className="badge">{status.plan.label}</span> : null}
            </button>
          )
        })}
        </div>
        <button className={`btn sm ${settings?.privacy_mode ? 'danger' : ''}`} style={{ margin: '0 10px 10px', justifyContent: 'center' }} title="Coupe le micro et empêche toute écoute ou capture tant qu’il est actif" onClick={() => store.updateSettings({ privacy_mode: !settings?.privacy_mode })}>
          {settings?.privacy_mode ? '🔴 Mode confidentiel : micro coupé' : '🎙 Passer en mode confidentiel'}
        </button>
        {/* Deux lignes d'état permanentes : ce que le micro fait, et ce qui sort (ou non)
            de l'ordinateur. Elles doivent se lire d'un coup d'œil, sans mot d'ingénieur. */}
        <div className="col" style={{ padding: '8px 10px', gap: 6 }}>
          <div className="row small" style={{ alignItems: 'flex-start' }}>
            <span className={`dot ${capture.mic ? 'rec' : voiceState !== 'off' ? 'on' : ''}`} style={{ marginTop: 5 }} />
            <span className="muted">
              {capture.mic
                ? 'Micro actif'
                : voiceState !== 'off'
                  ? 'Écoute active'
                  : voice?.muted
                    ? 'Micro coupé (muet)'
                    : voice?.paused_until
                      ? 'Écoute en pause (reprise auto.)'
                      : 'Écoute arrêtée'}
            </span>
          </div>
          <div className="row small" style={{ alignItems: 'flex-start' }}>
            <span className={`dot ${settings?.local_only ? 'on' : ''}`} style={{ marginTop: 5 }} />
            <span
              className="muted"
              title={
                settings?.local_only
                  ? 'Aucun moteur externe n’est appelé : tout est traité sur cet ordinateur.'
                  : 'Chaque envoi vers un moteur externe demande votre accord, par type de donnée (voir Confidentialité).'
              }
            >
              {settings?.local_only ? 'Rien ne sort de cet ordinateur' : 'Rien ne part sans votre accord'}
            </span>
          </div>
        </div>
        {/* Pied de barre : le mot d'activation d'abord, c'est la seule chose que quelqu'un
            qui découvre IRIS doit retenir. Le détail de présence reste dans l'infobulle. */}
        <div
          className="foot"
          title={
            status?.presence
              ? `${
                  status.presence.installed_days >= 1
                    ? `Sur cet ordinateur depuis ${status.presence.installed_days} jour${status.presence.installed_days > 1 ? 's' : ''}`
                    : 'Installée sur cet ordinateur aujourd’hui'
                } · démarrage n° ${status.presence.sessions} sur ${status.presence.device_name}${
                  status.presence.last_interaction_ago ? ` · dernier échange ${status.presence.last_interaction_ago}` : ''
                }`
              : undefined
          }
        >
          <div className="wake">« {settings?.wake_word || 'Dis-moi Iris'} »</div>
          <div className="ver">IRIS {appInfo?.version || ''}</div>
        </div>
      </aside>
      <main className="main">
        {(() => {
          const onglets = entreeDe(view)?.onglets
          if (!onglets) return content
          return (
            <>
              <div className="row" style={{ gap: 6, padding: '10px 16px 0', flexWrap: 'wrap' }}>
                {onglets.map((o) => (
                  <button key={o.id} className={`btn sm ${view === o.id ? 'primary' : 'ghost'}`} onClick={() => setView(o.id)}>{o.label}</button>
                ))}
              </div>
              {content}
            </>
          )
        })()}
      </main>

      {settings && !settings.onboarded ? <Onboarding /> : null}

      {confirmRequest ? (
        <Modal
          title="IRIS demande votre confirmation"
          actions={
            <>
              <button className="btn" onClick={() => answerConfirm(false)}>Refuser</button>
              <button className="btn primary" onClick={() => answerConfirm(true)}>Autoriser</button>
            </>
          }
        >
          <p>{confirmRequest.title}</p>
          <pre className="mono" style={{ background: 'var(--bg)', padding: '10px 12px', borderRadius: 8, whiteSpace: 'pre-wrap' }}>{confirmRequest.detail}</pre>
          <p className="small muted">Vous pouvez régler le niveau de confirmation dans Paramètres › Contrôle de l’ordinateur.</p>
        </Modal>
      ) : null}

      {consentRequest ? (
        <Modal
          title="Consentement requis"
          onClose={closeConsentRequest}
          actions={
            <>
              <button className="btn" onClick={closeConsentRequest}>Pas maintenant</button>
              <button
                className="btn primary"
                onClick={async () => {
                  await setConsent(consentRequest.data_type, true)
                  closeConsentRequest()
                  // On nomme ce qui vient d'être autorisé : « consentement enregistré » ne
                  // disait ni ce qui a marché, ni pourquoi il faut renvoyer le message.
                  store.toast(`« ${consentRequest.label} » autorisé. Renvoyez votre message.`, 'success')
                }}
              >
                Autoriser « {consentRequest.label} »
              </button>
            </>
          }
        >
          <p>
            Pour traiter cette demande, IRIS doit envoyer <strong>{consentRequest.label.toLowerCase()}</strong> au moteur IA{' '}
            {consentRequest.agent ? <strong>{consentRequest.agent}</strong> : 'externe'}. Rien n’a été envoyé.
          </p>
          <p className="small muted">{consentRequest.description}</p>
          <p className="small muted">Vous pourrez retirer ce consentement à tout moment dans Confidentialité.</p>
        </Modal>
      ) : null}

      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`} onClick={() => dismissToast(t.id)}>{t.text}</div>
        ))}
      </div>
    </div>
  )
}
