import React from 'react'
import { BtnIcone, Liste, Rangee, TopBar } from '../components/ui'
import { IcoBouclier, IcoCourriel, IcoDossier, IcoGlobe, IcoJournal } from '../components/icons'
import { Voile } from '../components/Voile'
import { api } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   « À propos » : la marque, les versions (application et service), la
   plateforme, le dossier de données et le journal (ouvrables), la présence
   d'IRIS sur cet ordinateur, l'abonnement, et les liens VELA.
   ========================================================================= */

const SITE_VELA = 'https://velaglass.ca'
const POLITIQUE = 'https://velaglass.ca/confidentialite.html'

export function AProposScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { nav, appInfo, status, toast } = useStore()

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
          <Rangee compacte titre="Version de l’application" valeur={appInfo?.version || '—'} />
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
          © VELA — IRIS est une assistante vocale qui agit sur votre ordinateur. Rien ne part sans votre accord.
        </div>
      </div>
    </div>
  )
}
