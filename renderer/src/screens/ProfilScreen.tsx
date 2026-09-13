import React from 'react'
import { Avatar, Holo, Liste, Rangee, TopBar } from '../components/ui'
import {
  IcoBouclier,
  IcoCarte,
  IcoCommentaire,
  IcoInfo,
  IcoLunettes,
  IcoMemoire,
  IcoOeil,
  IcoQuestion,
  IcoReglages,
  IcoRoutine,
  IcoTache,
  IcoUtilisateur
} from '../components/icons'
import { useStore } from '../lib/store'

/* =========================================================================
   Onglet « Mon profil » (maquette IMG_0695) : avatar, prénom, « Modifier mon
   profil », puis les listes Compte et sécurité / Commentaire / FAQ / À propos.
   En dessous, au-delà de la maquette, tout ce que l'ancienne barre latérale
   donnait : mémoire, routines, tâches, surveillances, abonnement,
   confidentialité, réglages, lunettes, le mode confidentiel et l'état du micro.
   ========================================================================= */

export function ProfilScreen(): JSX.Element {
  const { nav, settings, updateSettings, status, lunettes, capture, voice, appInfo, toast } = useStore()

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
            <span>{settings?.local_only ? 'Rien ne sort de cet ordinateur' : 'Rien ne part sans votre accord'}</span>
          </div>
        </div>

        <div className="small muted" style={{ textAlign: 'center', paddingTop: 8 }}>
          « {motActivation} » · IRIS {appInfo?.version || ''}
        </div>
      </div>
    </div>
  )
}
