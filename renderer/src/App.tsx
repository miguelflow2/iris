import React, { useEffect, useRef, useState } from 'react'
import { Failure, Splash } from './components/Boot'
import { IcoAlbum, IcoAvertissement, IcoBouclier, IcoMaison, IcoProfil, IcoRobot } from './components/icons'
import { LunettesRequises } from './components/LunettesRequises'
import { Field, Holo, Modal } from './components/ui'
import { messageErreur } from './lib/api'
import { useStore, type AlerteSonore, type EtatVerrou, type Onglet } from './lib/store'
import { ECRANS, ONGLETS } from './screens'
import { Onboarding } from './screens/Onboarding'
// Styles de l'accessibilité ET des éléments de coquille qu'elle ajoute (grand texte, alerte plein
// écran, écran de verrouillage, bandeaux) : styles.css appartient à une autre équipe.
import './screens/AccessibiliteScreen.css'

/* =========================================================================
   Coquille de l'application : une colonne façon téléphone, quatre onglets en
   bas, et une pile d'écrans qui s'ouvrent par-dessus l'onglet courant.
   L'onglet « Album » n'apparaît que lorsque des lunettes sont connues.

   Par-dessus tout le reste, dans cet ordre de priorité :
   - l'écran de verrouillage (IRIS verrouillée sur place ou à distance) ;
   - l'alerte sonore en plein écran (10 s, fermable) ;
   - la feuille « Cette fonction marche avec les lunettes VELA » (refus 428) ;
   - les bandeaux « Mode invité » et « Zone sans mémoire », tant qu'ils durent.
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

function heureDe(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('fr-CA', { hour: '2-digit', minute: '2-digit' })
}

/* ------------------------------------------------------------------ écran de verrouillage */
function EcranVerrou({ verrou }: { verrou: EtatVerrou }): JSX.Element {
  const { deverrouiller } = useStore()
  const [motDePasse, setMotDePasse] = useState('')
  const [occupe, setOccupe] = useState(false)
  const [erreur, setErreur] = useState('')
  const champ = useRef<HTMLInputElement>(null)

  useEffect(() => {
    champ.current?.focus()
  }, [])

  const envoyer = async (): Promise<void> => {
    if (!motDePasse || occupe) return
    setOccupe(true)
    setErreur('')
    try {
      await deverrouiller(motDePasse)
      setMotDePasse('')
    } catch (err) {
      // 403 mot de passe incorrect, 429 trop de tentatives, 409 aucun mot de passe : la phrase du service.
      setErreur(messageErreur(err))
    } finally {
      setOccupe(false)
    }
  }

  const aDistance = verrou.raison === 'distance'
  const depuis = heureDe(verrou.depuis)
  return (
    <div className="ecran-verrou" role="dialog" aria-modal="true" aria-labelledby="verrou-titre">
      <div className="verrou-corps">
        <span className="verrou-icone" aria-hidden="true"><IcoBouclier /></span>
        <h1 id="verrou-titre">{aDistance ? 'IRIS est verrouillée à distance' : 'IRIS est verrouillée'}</h1>
        <p className="verrou-texte">
          {depuis ? `Depuis ${depuis}. ` : ''}
          L’écoute, les captures et les commandes sont arrêtées. Entrez le mot de passe du propriétaire pour la déverrouiller.
        </p>
        <form
          className="col"
          style={{ gap: 12, width: '100%' }}
          onSubmit={(e) => {
            e.preventDefault()
            envoyer()
          }}
        >
          <Field label="Mot de passe du propriétaire">
            <input
              ref={champ}
              className="input"
              type="password"
              autoComplete="current-password"
              value={motDePasse}
              onChange={(e) => setMotDePasse(e.target.value)}
              aria-invalid={erreur ? true : undefined}
              aria-describedby={erreur ? 'verrou-erreur' : undefined}
            />
          </Field>
          {erreur ? (
            <div id="verrou-erreur" className="verrou-erreur" role="alert">{erreur}</div>
          ) : null}
          <Holo type="submit" variante="blanc" disabled={!motDePasse || occupe}>
            {occupe ? 'Vérification…' : 'Déverrouiller'}
          </Holo>
        </form>
        <p className="small muted" style={{ lineHeight: 1.45 }}>
          Le mot de passe n’est stocké nulle part en clair. Un déverrouillage fait depuis le téléphone est détecté ici en quelques secondes.
        </p>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ alerte sonore plein écran */
function AlertePleinEcran({ alerte, onClose }: { alerte: AlerteSonore; onClose: () => void }): JSX.Element {
  const bouton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    bouton.current?.focus()
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [alerte.id, onClose])
  const heure = new Date(alerte.ts * 1000).toLocaleTimeString('fr-CA', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  return (
    <div className={`alerte-plein-ecran ${alerte.test ? 'essai' : ''}`} role="alertdialog" aria-modal="true" aria-labelledby="alerte-titre" aria-describedby="alerte-detail">
      <span className="alerte-icone" aria-hidden="true"><IcoAvertissement /></span>
      {alerte.test ? <div className="alerte-essai">Essai</div> : null}
      <h1 id="alerte-titre" aria-live="assertive">{alerte.libelle}</h1>
      <p id="alerte-detail" className="alerte-detail">
        {alerte.test ? `Son d’essai synthétique, ${heure}` : `Entendu à ${heure}`} · confiance {Math.round(alerte.confiance * 100)} %
      </p>
      <p className="alerte-note">Vérifiez autour de vous : IRIS peut se tromper ou manquer un son.</p>
      <button ref={bouton} type="button" className="alerte-fermer" onClick={onClose}>Fermer</button>
    </div>
  )
}

/* ------------------------------------------------------------------ bandeaux de mémoire suspendue */
function Bandeaux(): JSX.Element | null {
  const { invite, zone, nav } = useStore()
  const inviteActif = Boolean(invite?.actif)
  const dansZone = Boolean(zone?.dans_zone)
  if (!inviteActif && !dansZone) return null
  const jusqua = heureDe(invite?.jusqua)
  return (
    <div className="bandeaux" role="status" aria-live="polite">
      {inviteActif ? (
        <button type="button" className="bandeau invite" onClick={() => nav.ouvrir('mode-invite')}>
          Mode invité : mémoire suspendue{jusqua ? ` (jusqu’à ${jusqua})` : ''}
        </button>
      ) : null}
      {dansZone ? (
        <button type="button" className="bandeau zone" onClick={() => nav.ouvrir('zones')}>
          Zone sans mémoire{zone?.zone_nom ? ` : ${zone.zone_nom}` : ''}
        </button>
      ) : null}
    </div>
  )
}

export default function App(): JSX.Element {
  const store = useStore()
  const { backendState, settings, nav, toasts, dismissToast, confirmRequest, answerConfirm, consentRequest, closeConsentRequest, setConsent, appInfo } = store
  const classeApp = `app ${settings?.interface_grand_texte ? 'grand-texte' : ''}`.trim()

  // Le verrou passe avant tout : pendant qu'IRIS est verrouillée, le service refuse les autres
  // routes, et aucun écran ne doit rester lisible derrière.
  if (store.verrou?.verrouille && backendState !== 'failed' && backendState !== 'down') {
    return (
      <div className={classeApp}>
        <div className="colonne">
          <EcranVerrou verrou={store.verrou} />
        </div>
      </div>
    )
  }

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
    <div className={classeApp}>
      <div className="colonne">
        <Bandeaux />
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

        {store.lunettesRequises ? <LunettesRequises demande={store.lunettesRequises} onClose={store.fermerLunettesRequises} /> : null}

        {store.alerte ? <AlertePleinEcran alerte={store.alerte} onClose={store.fermerAlerte} /> : null}

        <div className="toasts" aria-live="polite">
          {toasts.map((t) => (
            <div key={t.id} className={`toast ${t.kind}`} onClick={() => dismissToast(t.id)}>{t.text}</div>
          ))}
        </div>
      </div>
    </div>
  )
}
