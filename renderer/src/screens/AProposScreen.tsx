import React, { useRef, useState } from 'react'
import { BtnIcone, Field, Liste, Modal, Rangee, TopBar } from '../components/ui'
import { IcoBouclier, IcoCourriel, IcoDossier, IcoGlobe, IcoJournal } from '../components/icons'
import { Voile } from '../components/Voile'
import { api, messageErreur } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   « À propos » : la marque, les versions (application et service), la
   plateforme, le dossier de données et le journal (ouvrables), la présence
   d'IRIS sur cet ordinateur, l'abonnement, et les liens VELA.

   Accès propriétaire CACHÉ (décision de Miguel du 2026-09-13) : sept touches
   en moins de trois secondes sur la ligne « Version de l'application » ouvrent
   une modale qui active le mode de présentation sans lunettes
   (POST /api/demo/activer, mot de passe du propriétaire) ou le désactive.
   Rien d'autre ne le signale : pas de rôle de bouton, pas d'infobulle, pas de
   curseur, et l'état actif n'est visible que dans cette modale.
   ========================================================================= */

const SITE_VELA = 'https://velaglass.ca'
const POLITIQUE = 'https://velaglass.ca/confidentialite.html'
const TOUCHES_REQUISES = 7
const FENETRE_MS = 3000

export function AProposScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { nav, appInfo, status, toast, settings, presence: presenceLunettes, rafraichirPresence, refreshSettings } = useStore()
  const touches = useRef<number[]>([])
  const [acces, setAcces] = useState(false)
  const [motDePasse, setMotDePasse] = useState('')
  const [erreurAcces, setErreurAcces] = useState<string | null>(null)
  const [occupeAcces, setOccupeAcces] = useState(false)

  // Sept touches dans une fenêtre glissante de trois secondes.
  const toucherVersion = (): void => {
    const maintenant = Date.now()
    touches.current = [...touches.current.filter((t) => maintenant - t < FENETRE_MS), maintenant]
    if (touches.current.length >= TOUCHES_REQUISES) {
      touches.current = []
      setMotDePasse('')
      setErreurAcces(null)
      setAcces(true)
    }
  }

  const modeActif = Boolean(settings?.demo_sans_lunettes) || presenceLunettes?.source === 'demo'

  const fermerAcces = (): void => {
    if (occupeAcces) return
    setAcces(false)
    setMotDePasse('')
    setErreurAcces(null)
  }

  const activer = async (): Promise<void> => {
    if (!motDePasse || occupeAcces) return
    setOccupeAcces(true)
    setErreurAcces(null)
    try {
      await api.post('/api/demo/activer', { mot_de_passe: motDePasse })
      await Promise.all([refreshSettings().catch(() => undefined), rafraichirPresence()])
      setMotDePasse('')
      setAcces(false)
    } catch (err) {
      setErreurAcces(messageErreur(err))
    } finally {
      setOccupeAcces(false)
    }
  }

  const desactiver = async (): Promise<void> => {
    if (occupeAcces) return
    setOccupeAcces(true)
    setErreurAcces(null)
    try {
      await api.post('/api/demo/desactiver')
      await Promise.all([refreshSettings().catch(() => undefined), rafraichirPresence()])
      setAcces(false)
    } catch (err) {
      setErreurAcces(messageErreur(err))
    } finally {
      setOccupeAcces(false)
    }
  }

  const presence = status?.presence
  const surCetOrdinateur: string = presence
    ? `${presence.installed_days >= 1 ? `depuis ${presence.installed_days} jour${presence.installed_days > 1 ? 's' : ''}` : 'depuis aujourd’hui'} · démarrage n° ${presence.sessions} · ${presence.device_name}${presence.last_interaction_ago ? ` · dernier échange ${presence.last_interaction_ago}` : ''}`
    : '—'

  // Le vrai dossier de données du service (userData/iris-data), pas le dossier parent d'Electron :
  // userData n'est qu'un repli tant que le service n'a pas répondu.
  const dossierDonnees: string | undefined = status?.data_dir || api.info?.data_dir || appInfo?.userData || undefined

  const ouvrir = async (chemin: string | undefined): Promise<void> => {
    if (!chemin) return
    const erreur = await window.iris.openPath(chemin)
    if (erreur) toast(erreur, 'error')
  }

  return (
    <div className="ecran">
      <TopBar titre="À propos" />
      <div className="contenu">
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, padding: '22px 0 10px' }}>
          <Voile taille={64} variante="clair" className="voile lueur" titre="VELA" />
          <div style={{ fontSize: 30, fontWeight: 800, letterSpacing: '0.08em', marginTop: 8 }}>IRIS</div>
          <div className="muted">par VELA · entreprise canadienne</div>
        </div>

        <Liste>
          {/* Même balisage que <Rangee compacte> sans action : la ligne ne se distingue en rien des autres. */}
          <div className="rangee compacte" onClick={toucherVersion}>
            <span className="corps">
              <span style={{ display: 'block' }}>Version de l’application</span>
            </span>
            <span className="valeur">{appInfo?.version || '—'}</span>
          </div>
          <Rangee compacte titre="Version du service" valeur={status?.version || '—'} />
          <Rangee compacte titre="Plateforme" valeur={status?.platform || appInfo?.platform || '—'} />
          <Rangee
            compacte
            titre="Dossier de données"
            sous={dossierDonnees}
            droite={
              <BtnIcone title="Ouvrir le dossier" aria-label="Ouvrir le dossier de données" disabled={!dossierDonnees} onClick={() => ouvrir(dossierDonnees)}>
                <IcoDossier />
              </BtnIcone>
            }
          />
          <Rangee
            compacte
            titre="Journal"
            sous={appInfo?.logPath}
            droite={
              <BtnIcone title="Ouvrir le journal" aria-label="Ouvrir le journal" disabled={!appInfo?.logPath} onClick={() => ouvrir(appInfo?.logPath)}>
                <IcoJournal />
              </BtnIcone>
            }
          />
          <Rangee compacte titre="Sur cet ordinateur" sous={surCetOrdinateur} />
          <Rangee compacte titre="Abonnement" valeur={status?.plan?.label} onClick={() => nav.ouvrir('abonnement')} />
        </Liste>

        <Liste>
          <Rangee icone={<IcoGlobe />} titre="Site VELA" onClick={() => window.iris.openExternal(SITE_VELA)} />
          <Rangee icone={<IcoBouclier />} titre="Politique de confidentialité" onClick={() => window.iris.openExternal(POLITIQUE)} />
          <Rangee icone={<IcoCourriel />} titre="Support" onClick={() => nav.ouvrir('commentaire')} />
        </Liste>

        <div className="small muted" style={{ textAlign: 'center', lineHeight: 1.5, padding: '8px 12px 0' }}>
          © VELA, entreprise canadienne — IRIS est la technologie des lunettes VELA. Rien ne part sans votre accord.
        </div>
      </div>

      {acces ? (
        <Modal
          title="Accès propriétaire"
          onClose={fermerAcces}
          actions={
            modeActif ? (
              <>
                <button type="button" className="btn ghost" disabled={occupeAcces} onClick={fermerAcces}>Fermer</button>
                <button type="button" className="btn danger" disabled={occupeAcces} onClick={desactiver}>
                  {occupeAcces ? 'Un instant…' : 'Désactiver'}
                </button>
              </>
            ) : (
              <>
                <button type="button" className="btn ghost" disabled={occupeAcces} onClick={fermerAcces}>Annuler</button>
                <button type="button" className="btn primary" disabled={occupeAcces || !motDePasse} onClick={activer}>
                  {occupeAcces ? 'Vérification…' : 'Activer'}
                </button>
              </>
            )
          }
        >
          {modeActif ? (
            <p className="desc" style={{ lineHeight: 1.45 }}>
              Le mode de présentation est actif : IRIS fonctionne sans lunettes sur cet ordinateur. Désactivez-le après la présentation.
            </p>
          ) : (
            <>
              <p className="desc" style={{ lineHeight: 1.45, marginBottom: 12 }}>
                Mode de présentation sans lunettes, réservé au propriétaire de cet IRIS. Entrez le mot de passe du propriétaire.
              </p>
              <Field label="Mot de passe du propriétaire">
                <input
                  className="input"
                  type="password"
                  autoComplete="current-password"
                  autoFocus
                  value={motDePasse}
                  onChange={(e) => setMotDePasse(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void activer()
                  }}
                />
              </Field>
            </>
          )}
          {erreurAcces ? <div className="bloc-note erreur" role="alert" style={{ marginTop: 10 }}>{erreurAcces}</div> : null}
        </Modal>
      ) : null}
    </div>
  )
}
