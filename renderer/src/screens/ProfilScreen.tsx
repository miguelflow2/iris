import React from 'react'
import { Avatar, Holo, Liste, Rangee, TopBar } from '../components/ui'
import {
  IcoAvertissement,
  IcoBouclier,
  IcoCamera,
  IcoCarte,
  IcoCommentaire,
  IcoCopier,
  IcoCrayon,
  IcoGlobe,
  IcoHautParleur,
  IcoHorloge,
  IcoInfo,
  IcoJournal,
  IcoListeChat,
  IcoLunettes,
  IcoMemoire,
  IcoOeil,
  IcoOnde,
  IcoOreille,
  IcoProfil,
  IcoQuestion,
  IcoRecherche,
  IcoReglages,
  IcoRoutine,
  IcoTache,
  IcoTelephoneEcran,
  IcoTraduire,
  IcoUtilisateur
} from '../components/icons'
import { useStore } from '../lib/store'

/* =========================================================================
   Onglet « Mon profil » (maquette IMG_0695) : avatar, prénom, « Modifier mon
   profil », puis les listes Compte et sécurité / Commentaire / FAQ / À propos.
   En dessous, au-delà de la maquette, tout ce que l'ancienne barre latérale
   donnait : mémoire, routines, tâches, surveillances, abonnement,
   confidentialité, réglages, lunettes, le mode confidentiel et l'état du micro.
   Puis les trois familles du chantier de lancement : Accessibilité, Au
   quotidien, Confiance. Chaque rangée ouvre son écran ; les écrans qui captent
   disent eux-mêmes quand les lunettes manquent. Les valeurs affichées à droite
   ne sont que des états réellement connus du service (écoute, invité, zone).
   ========================================================================= */

export function ProfilScreen(): JSX.Element {
  const { nav, settings, updateSettings, status, lunettes, capture, voice, appInfo, toast, ecoute: etatEcoute, invite, zone } = useStore()

  const prenom: string = settings?.user_name || ''
  const motActivation: string = settings?.wake_word || 'Dis-moi Iris'

  // État du micro, repris de l'ancienne barre latérale : la vérité vient du service (voice.state,
  // voice.muted, voice.paused_until) et de l'indicateur de capture (capture.mic).
  const ecoute = Boolean(voice?.state && voice.state !== 'off')
  const libelleMicro: string = voice?.muted
    ? 'Micro coupé (muet)'
    : voice?.paused_until
      ? 'Écoute en pause (reprise auto.)'
      : capture.mic
        ? 'Micro actif'
        : ecoute
          ? 'Écoute active'
          : 'Écoute arrêtée'
  const microActif = !voice?.muted && !voice?.paused_until && (capture.mic || ecoute)

  const basculerConfidentiel = (): void => {
    updateSettings({ privacy_mode: !settings?.privacy_mode }).catch((err: Error) => toast(String(err.message), 'error'))
  }

  return (
    <div className="ecran avec-onglets">
      <TopBar titre="Mon profil" retour={false} />
      <div className="contenu">
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16, padding: '26px 0 12px' }}>
          <Avatar taille="grand" nom={prenom} />
          <div style={{ fontSize: 30, fontWeight: 700, lineHeight: 1.15, textAlign: 'center', wordBreak: 'break-word' }}>{prenom || 'Vous'}</div>
          <Holo taille="petit" onClick={() => nav.ouvrir('profil-modifier')}>Modifier mon profil</Holo>
        </div>

        <Liste>
          <Rangee icone={<IcoUtilisateur />} titre="Compte et sécurité" onClick={() => nav.ouvrir('compte-securite')} />
        </Liste>

        <Liste>
          <Rangee icone={<IcoCommentaire />} titre="Commentaire" onClick={() => nav.ouvrir('commentaire')} />
          <Rangee icone={<IcoQuestion />} titre="FAQ" onClick={() => nav.ouvrir('faq')} />
          <Rangee icone={<IcoInfo />} titre="À propos" onClick={() => nav.ouvrir('a-propos')} />
        </Liste>

        <h3 className="section-sous">IRIS</h3>
        <Liste>
          <Rangee icone={<IcoMemoire />} titre="Mémoire" onClick={() => nav.ouvrir('memoire')} />
          <Rangee icone={<IcoRoutine />} titre="Routines" onClick={() => nav.ouvrir('routines')} />
          <Rangee icone={<IcoTache />} titre="Tâches" onClick={() => nav.ouvrir('taches')} />
          <Rangee icone={<IcoOeil />} titre="Surveillances" onClick={() => nav.ouvrir('surveillances')} />
          <Rangee icone={<IcoCarte />} titre="Abonnement" valeur={status?.plan?.label} onClick={() => nav.ouvrir('abonnement')} />
          <Rangee icone={<IcoBouclier />} titre="Confidentialité" valeur={settings?.local_only ? '100 % local' : undefined} onClick={() => nav.ouvrir('confidentialite')} />
          <Rangee icone={<IcoReglages />} titre="Réglages" onClick={() => nav.ouvrir('reglages')} />
          <Rangee icone={<IcoLunettes />} titre="Mes lunettes" valeur={lunettes?.connected ? 'Connectées' : undefined} onClick={() => nav.ouvrir('lunettes')} />
        </Liste>

        <h3 className="section-sous">Accessibilité</h3>
        <Liste>
          <Rangee icone={<IcoOeil />} titre="Accessibilité" sous="Décrire, lire, billets, couleurs ; réglages et limites" onClick={() => nav.ouvrir('accessibilite')} />
          <Rangee icone={<IcoListeChat />} titre="Sous-titres" valeur={etatEcoute?.sous_titres ? 'En cours' : undefined} onClick={() => nav.ouvrir('sous-titres')} />
          <Rangee icone={<IcoAvertissement />} titre="Alertes sonores" valeur={etatEcoute?.alertes ? 'Actives' : undefined} onClick={() => nav.ouvrir('alertes-sonores')} />
          <Rangee icone={<IcoOreille />} titre="Écoute assistée" valeur={etatEcoute?.assistee?.actif ? 'En cours' : undefined} onClick={() => nav.ouvrir('ecoute-assistee')} />
          <Rangee icone={<IcoJournal />} titre="Journal" valeur={etatEcoute?.journal ? 'Actif' : undefined} onClick={() => nav.ouvrir('journal')} />
          <Rangee icone={<IcoLunettes />} titre="Bouton des lunettes" onClick={() => nav.ouvrir('bouton-lunettes')} />
          <Rangee icone={<IcoTelephoneEcran />} titre="Mode dehors" onClick={() => nav.ouvrir('mode-dehors')} />
        </Liste>

        <h3 className="section-sous">Au quotidien</h3>
        <Liste>
          <Rangee icone={<IcoTraduire />} titre="Mode interprète" onClick={() => nav.ouvrir('interprete')} />
          <Rangee icone={<IcoCrayon />} titre="Mode cours" valeur={etatEcoute?.cours ? 'En cours' : undefined} onClick={() => nav.ouvrir('cours')} />
          <Rangee icone={<IcoCamera />} titre="Vision partagée" onClick={() => nav.ouvrir('vision-partagee')} />
          <Rangee icone={<IcoCopier />} titre="Reçus" onClick={() => nav.ouvrir('recus')} />
          <Rangee icone={<IcoTache />} titre="Mains occupées" sous="Recette, montage ou réparation, étape par étape" onClick={() => nav.ouvrir('pas-a-pas')} />
          <Rangee icone={<IcoHorloge />} titre="Entraînement" onClick={() => nav.ouvrir('entrainement')} />
          <Rangee icone={<IcoRecherche />} titre="Comparer les prix" onClick={() => nav.ouvrir('prix')} />
          <Rangee icone={<IcoHautParleur />} titre="Résumé de la journée" onClick={() => nav.ouvrir('resume-journee')} />
          <Rangee icone={<IcoUtilisateur />} titre="Rappels contextuels" sous="« La prochaine fois que je vois Marc… »" onClick={() => nav.ouvrir('rappels-contexte')} />
        </Liste>

        <h3 className="section-sous">Confiance</h3>
        <Liste>
          <Rangee icone={<IcoOnde />} titre="Empreinte vocale" valeur={settings?.verrou_vocal_actif ? 'Active' : undefined} onClick={() => nav.ouvrir('verrou-vocal')} />
          <Rangee icone={<IcoGlobe />} titre="Zones sans mémoire" valeur={zone?.dans_zone ? zone.zone_nom || 'Dans une zone' : undefined} onClick={() => nav.ouvrir('zones')} />
          <Rangee icone={<IcoProfil />} titre="Mode invité" valeur={invite?.actif ? 'Actif' : undefined} onClick={() => nav.ouvrir('mode-invite')} />
          <Rangee icone={<IcoBouclier />} titre="Verrouillage à distance" onClick={() => nav.ouvrir('verrou-distant')} />
        </Liste>

        <button type="button" className={'btn' + (settings?.privacy_mode ? ' danger' : '')} style={{ width: '100%' }} onClick={basculerConfidentiel}>
          {settings?.privacy_mode ? 'Mode confidentiel : micro coupé' : 'Passer en mode confidentiel'}
        </button>

        <div className="col" style={{ gap: 6, padding: '0 6px' }}>
          <div className="row small muted" style={{ gap: 8 }}>
            <span className={`dot ${microActif ? 'on' : ''}`} />
            <span>{libelleMicro}</span>
          </div>
          <div className="row small muted" style={{ gap: 8 }}>
            <span className="dot on" />
            <span>
              {settings?.local_only
                ? settings?.verrou_distant_actif
                  ? 'Rien ne sort de cet ordinateur, sauf le canal du verrouillage à distance'
                  : 'Rien ne sort de cet ordinateur'
                : 'Rien ne part sans votre accord'}
            </span>
          </div>
        </div>

        <div className="small muted" style={{ textAlign: 'center', paddingTop: 8 }}>
          « {motActivation} » · IRIS {appInfo?.version || ''}
        </div>
      </div>
    </div>
  )
}
