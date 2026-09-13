import React from 'react'
import { Failure, Splash } from './components/Boot'
import { IcoAlbum, IcoMaison, IcoProfil, IcoRobot } from './components/icons'
import { Modal } from './components/ui'
import { useStore, type Onglet } from './lib/store'
import { ECRANS, ONGLETS } from './screens'
import { Onboarding } from './screens/Onboarding'

/* =========================================================================
   Coquille de l'application : une colonne façon téléphone, quatre onglets en
   bas, et une pile d'écrans qui s'ouvrent par-dessus l'onglet courant.
   L'onglet « Album » n'apparaît que lorsque des lunettes sont connues.
   ========================================================================= */

const ONGLETS_BARRE: { id: Onglet; label: string; Icone: (p: { plein?: boolean }) => JSX.Element }[] = [
  { id: 'accueil', label: 'Accueil', Icone: IcoMaison },
  { id: 'ia', label: 'IA', Icone: IcoRobot },
  { id: 'album', label: 'Album', Icone: IcoAlbum },
  { id: 'profil', label: 'Mon profil', Icone: IcoProfil }
]

function BarreOnglets(): JSX.Element {
  const { nav, lunettes } = useStore()
  const albumVisible = Boolean(lunettes?.connected || lunettes?.remembered?.address)
  return (
    <nav className="barre-onglets" aria-label="Navigation principale">
      {ONGLETS_BARRE.filter((o) => o.id !== 'album' || albumVisible).map((o) => {
        const actif = nav.onglet === o.id
        return (
          <button key={o.id} type="button" className={`onglet ${actif ? 'actif' : ''}`} aria-current={actif ? 'page' : undefined} onClick={() => nav.allerOnglet(o.id)}>
            <o.Icone plein={actif} />
            <span>{o.label}</span>
          </button>
        )
      })}
    </nav>
  )
}

export default function App(): JSX.Element {
  const store = useStore()
  const { backendState, settings, nav, toasts, dismissToast, confirmRequest, answerConfirm, consentRequest, closeConsentRequest, setConsent, appInfo } = store

  // Écrans de démarrage et de panne (components/Boot.tsx) : avant tout le reste.
  if (backendState === 'starting' || (backendState === 'ready' && !settings)) {
    return <Splash logPath={appInfo?.logPath} />
  }
  if (backendState === 'failed' || backendState === 'down') {
    return <Failure down={backendState === 'down'} message={store.backendMessage} logPath={appInfo?.logPath} />
  }

  // L'album disparaît de la barre quand aucune lunette n'est connue : on retombe sur l'accueil.
  const albumVisible = Boolean(store.lunettes?.connected || store.lunettes?.remembered?.address)
  const ongletCourant: Onglet = nav.onglet === 'album' && !albumVisible ? 'accueil' : nav.onglet
  const page = nav.pile[nav.pile.length - 1]
  const Ecran = page ? ECRANS[page.ecran] : null
  const Racine = ONGLETS[ongletCourant]

  return (
    <div className="app">
      <div className="colonne">
        {Ecran ? <Ecran key={`${page!.ecran}-${nav.pile.length}`} params={page!.params} /> : <Racine key={ongletCourant} />}
        {!Ecran ? <BarreOnglets /> : null}

        {settings && !settings.onboarded ? <Onboarding /> : null}
        {/* Installation antérieure à l'étape « compte » : on la réclame quand même, une fois. */}
        {settings?.onboarded ? <Onboarding seulementCompte /> : null}

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
            <pre className="mono">{confirmRequest.detail}</pre>
            <p className="small muted">Vous pouvez régler le niveau de confirmation dans Mon profil › Réglages › Contrôle de l’ordinateur.</p>
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
            <p className="small muted">Vous pourrez retirer ce consentement à tout moment dans Mon profil › Confidentialité.</p>
          </Modal>
        ) : null}

        <div className="toasts" aria-live="polite">
          {toasts.map((t) => (
            <div key={t.id} className={`toast ${t.kind}`} onClick={() => dismissToast(t.id)}>{t.text}</div>
          ))}
        </div>
      </div>
    </div>
  )
}
