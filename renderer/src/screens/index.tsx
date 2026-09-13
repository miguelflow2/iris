import React from 'react'
import type { Ecran, Onglet } from '../lib/store'
import { AccueilScreen } from './AccueilScreen'
import { IaScreen } from './IaScreen'
import { AlbumScreen } from './AlbumScreen'
import { ProfilScreen } from './ProfilScreen'
import { ConnecterScreen } from './ConnecterScreen'
import { LunettesScreen } from './LunettesScreen'
import { LunettesAudioScreen } from './LunettesAudioScreen'
import { LunettesTechniqueScreen } from './LunettesTechniqueScreen'
import { TutoCameraScreen } from './TutoCameraScreen'
import { TutoTouchpadScreen } from './TutoTouchpadScreen'
import { AssistantIntroScreen } from './AssistantIntroScreen'
import { TraductionScreen } from './TraductionScreen'
import { LumiereBDScreen } from './LumiereBDScreen'
import { AlbumParametresScreen } from './AlbumParametresScreen'
import { DiscussionsScreen } from './DiscussionsScreen'
import { LangueIaScreen } from './LangueIaScreen'
import { ProfilModifierScreen } from './ProfilModifierScreen'
import { CompteSecuriteScreen } from './CompteSecuriteScreen'
import { CommentaireScreen } from './CommentaireScreen'
import { FaqScreen } from './FaqScreen'
import { AProposScreen } from './AProposScreen'
import { MemoireScreen } from './MemoireScreen'
import { RoutinesScreen } from './RoutinesScreen'
import { TachesScreen } from './TachesScreen'
import { SurveillancesScreen } from './SurveillancesScreen'
import { AbonnementScreen } from './AbonnementScreen'
import { ReglagesScreen } from './ReglagesScreen'
import { ReglagesVoixScreen } from './ReglagesVoixScreen'
import { ReglagesPcScreen } from './ReglagesPcScreen'
import { CommunicationsScreen } from './CommunicationsScreen'
import { ComptesWebScreen } from './ComptesWebScreen'
import { MoteursIaScreen } from './MoteursIaScreen'
import { ConfidentialiteScreen } from './ConfidentialiteScreen'

/** Props reçues par tout écran empilé : les paramètres passés à `nav.ouvrir(ecran, params)`. */
export type EcranProps = { params?: Record<string, any> }

/** Écrans racines des quatre onglets (la barre du bas est affichée par-dessus). */
export const ONGLETS: Record<Onglet, React.ComponentType> = {
  accueil: AccueilScreen,
  ia: IaScreen,
  album: AlbumScreen,
  profil: ProfilScreen
}

/** Écrans secondaires, ouverts par `nav.ouvrir(...)` (avec flèche de retour, sans barre d'onglets). */
export const ECRANS: Record<Ecran, React.ComponentType<EcranProps>> = {
  connecter: ConnecterScreen,
  lunettes: LunettesScreen,
  'lunettes-audio': LunettesAudioScreen,
  'lunettes-technique': LunettesTechniqueScreen,
  'tuto-camera': TutoCameraScreen,
  'tuto-touchpad': TutoTouchpadScreen,
  'assistant-intro': AssistantIntroScreen,
  traduction: TraductionScreen,
  'lumiere-bd': LumiereBDScreen,
  'album-parametres': AlbumParametresScreen,
  discussions: DiscussionsScreen,
  'langue-ia': LangueIaScreen,
  'profil-modifier': ProfilModifierScreen,
  'compte-securite': CompteSecuriteScreen,
  commentaire: CommentaireScreen,
  faq: FaqScreen,
  'a-propos': AProposScreen,
  memoire: MemoireScreen,
  routines: RoutinesScreen,
  taches: TachesScreen,
  surveillances: SurveillancesScreen,
  abonnement: AbonnementScreen,
  reglages: ReglagesScreen,
  'reglages-voix': ReglagesVoixScreen,
  'reglages-pc': ReglagesPcScreen,
  communications: CommunicationsScreen,
  'comptes-web': ComptesWebScreen,
  'moteurs-ia': MoteursIaScreen,
  confidentialite: ConfidentialiteScreen
}
