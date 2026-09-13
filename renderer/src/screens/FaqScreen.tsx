import React from 'react'
import { TopBar } from '../components/ui'
import { api } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   « FAQ » : douze questions vraies sur IRIS, dépliables. Les textes reprennent
   le mot d'activation réglé et le dossier de données réel ; aucun nom de
   fournisseur n'apparaît.
   ========================================================================= */

export function FaqScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { settings, status, appInfo } = useStore()
  const mot: string = settings?.wake_word || 'Dis-moi Iris'
  // Même chemin que « À propos › Dossier de données » : le dossier réel du service, userData en repli.
  const dossier: string | undefined = status?.data_dir || api.info?.data_dir || appInfo?.userData || undefined

  const questions: { q: string; r: React.ReactNode }[] = [
    {
      q: 'Comment réveiller IRIS ?',
      r: (
        <>
          Dites « {mot} » suivi de votre demande, par exemple « {mot}, ouvre mon navigateur ». IRIS répond en quelques secondes et vous pose une question si elle
          a besoin d’une précision. Vous pouvez changer cette phrase dans Mon profil › Modifier mon profil.
        </>
      )
    },
    {
      q: 'Pourquoi la voix exige-t-elle les lunettes ?',
      r: (
        <>
          IRIS est ce qu’il y a dans vos lunettes VELA : par défaut, la voix ne fonctionne que lorsqu’elles sont connectées. Le chat écrit de l’onglet IA, lui,
          reste utilisable sans les lunettes.
        </>
      )
    },
    {
      q: 'Qu’est-ce que le mode 100 % local ?',
      r: (
        <>
          Quand il est activé (Mon profil › Confidentialité), rien ne quitte cet ordinateur : aucun moteur externe, aucune recherche web, aucun courriel. IRIS
          s’appuie alors uniquement sur ce qui est installé sur la machine.
        </>
      )
    },
    {
      q: 'Qu’est-ce que le mode confidentiel ?',
      r: (
        <>
          Un interrupteur d’urgence : le micro est coupé, aucune écoute ni capture tant qu’il est actif. Il se trouve au bas de Mon profil, et vous êtes prévenu
          quand il s’active ou se désactive.
        </>
      )
    },
    {
      q: 'Où sont mes données ?',
      r: (
        <>
          Sur cet ordinateur, dans {dossier ? <>le dossier <span className="mono">{dossier}</span></> : 'le dossier de données d’IRIS'} : réglages, mémoire,
          photos des lunettes et journal. Vous pouvez l’ouvrir depuis Mon profil › À propos.
        </>
      )
    },
    {
      q: 'Que sont les consentements ?',
      r: (
        <>
          Pour qu’un moteur externe réponde, il doit recevoir le texte de vos demandes, parfois une image de l’écran ou de l’audio. Vous décidez, type par type,
          ce qui peut partir ; rien n’est envoyé sans ce oui, et vous pouvez changer d’avis à tout moment dans Confidentialité.
        </>
      )
    },
    {
      q: 'Quels sont les raccourcis clavier ?',
      r: (
        <>
          <kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>Espace</kbd> pour parler, <kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>M</kbd> pour couper le micro,{' '}
          <kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>S</kbd> pour arrêter la lecture, <kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>I</kbd> pour afficher IRIS. Ils fonctionnent même
          quand IRIS est en arrière-plan.
        </>
      )
    },
    {
      q: 'Comment prendre une photo ?',
      r: (
        <>
          Avec le bouton avant des lunettes, depuis l’accueil, depuis l’album, ou à la voix (« {mot}, prends une photo »). L’image est rapatriée sur cet
          ordinateur et n’est envoyée à personne.
        </>
      )
    },
    {
      q: 'Comment reconnaître une image ?',
      r: (
        <>
          Dans l’onglet IA, joignez une image à votre message (ou une photo des lunettes) et posez votre question. Si un moteur externe doit la voir, IRIS vous
          demande d’abord votre accord.
        </>
      )
    },
    {
      q: 'Comment utiliser IRIS depuis mon téléphone ?',
      r: (
        <>
          Dans Mon profil › Compte et sécurité, posez un mot de passe puis activez « Autoriser l’accès depuis le téléphone ». Ouvrez ensuite l’adresse affichée dans
          le navigateur de votre téléphone, sur le même réseau WiFi. N’ouvrez jamais de port sur votre routeur.
        </>
      )
    },
    {
      q: 'Comment fonctionne l’abonnement ?',
      r: (
        <>
          Les lunettes s’achètent une fois ; IRIS a un plan gratuit et des plans payants avec un quota mensuel de requêtes. Le détail, l’utilisation du mois et
          l’activation se trouvent dans Mon profil › Abonnement. IRIS vous prévient à 80 % et 95 % du quota.
        </>
      )
    },
    {
      q: 'Que retient la mémoire d’IRIS ?',
      r: (
        <>
          Les mots réellement dits ou écrits : décisions, promesses, chiffres, préférences. Elle n’invente rien, vous pouvez la relire et effacer n’importe quel
          souvenir dans Mon profil › Mémoire.
        </>
      )
    }
  ]

  return (
    <div className="ecran">
      <TopBar titre="FAQ" />
      <div className="contenu serre">
        {questions.map((item) => (
          <details key={item.q} className="carte" style={{ padding: '14px 18px' }}>
            <summary style={{ fontSize: 19, fontWeight: 700, cursor: 'pointer', listStyle: 'none' }}>{item.q}</summary>
            <p className="desc" style={{ marginTop: 10 }}>{item.r}</p>
          </details>
        ))}
      </div>
    </div>
  )
}
