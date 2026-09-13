/* =========================================================================
   Onglet IA — types, constantes et utilitaires partagés entre IaScreen,
   DiscussionsScreen et les composants d'appui (Bulle, BarreVoix, Minuteur…).
   Tout ce qui vient de l'ancienne ChatView et qui sert à plus d'un écran vit ici.
   ========================================================================= */

export interface Conversation {
  id: string
  title: string
  agent: string
  kind: string
  updated_at: string
  busy: boolean
  archived?: boolean
}

export interface ToolEvent {
  id: string
  name: string
  input: Record<string, unknown>
  status: 'running' | 'done' | 'error'
  result?: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
  images: { media_type: string; data: string }[]
  agent?: string | null
  model?: string | null
  meta: any
  created_at: string
  streaming?: boolean
  thinking?: string
  tools?: ToolEvent[]
  infos?: string[]
}

export interface PieceJointe {
  name: string
  media_type: string
  data: string
}

/** Clé de sessionStorage lue par IaScreen au montage : identifiant de conversation à ouvrir,
 *  ou l'une des valeurs spéciales ci-dessous. Posée par DiscussionsScreen et par l'onglet Favoris. */
export const CLE_OUVRIR = 'iris.ouvrirConversation'
/** Valeur spéciale : ouvrir le fil « Échanges vocaux ». */
export const OUVRIR_VOIX = 'voice'
/** Valeur spéciale : démarrer un brouillon de conversation neuve (rien n'est écrit en base). */
export const OUVRIR_NOUVELLE = 'nouvelle'

/** Libellé PUBLIC d'un moteur — masque de marque : l'utilisateur ne voit JAMAIS le nom d'un
 *  fournisseur ni un identifiant de modèle sur les surfaces courantes (fil, liste des discussions,
 *  barre du composeur). Les vrais noms restent réservés à l'écran avancé « Moteurs IA ».
 *  Tout moteur nommé, comme l'IA incluse, s'affiche « VELA ». */
export function labelMoteurPublic(agent?: string | null): string {
  if (agent === 'custom') return 'IA perso'
  if (agent === 'auto') return 'Auto'
  return 'VELA'
}

/** Exemples proposés sur un fil vide : ce que l'on peut demander à IRIS, en une phrase exacte.
 *  `local: true` = commande exécutée par le service sans réseau ni clé d'API : un clic l'envoie
 *  tout de suite. Les autres remplissent seulement la zone d'écriture, pour que personne n'envoie
 *  une demande par inadvertance pendant une démonstration. */
export const SUGGESTIONS: { verbe: string; phrase: string; local: boolean }[] = [
  { verbe: 'Répondre tout de suite', phrase: 'Quelle heure est-il ?', local: true },
  { verbe: 'Ouvrir une application', phrase: 'Ouvre la calculatrice', local: true },
  { verbe: 'Lancer de la musique', phrase: 'Mets de la musique jazz', local: true },
  { verbe: 'Prendre une note', phrase: 'Prends une note : rappeler le fournisseur demain', local: false },
  { verbe: 'Lire votre écran', phrase: 'Que vois-tu à l’écran ?', local: false },
  { verbe: 'Écrire du code', phrase: 'Crée un jeu de morpion dans un fichier HTML', local: false }
]

/** Conversation ouverte pendant cette session de l'application. Survit au démontage de l'onglet IA
 *  (quand on ouvre la liste des discussions ou un autre onglet puis qu'on revient), mais pas au
 *  lancement : IRIS s'ouvre toujours sur un fil neuf plutôt que sur la dernière conversation. */
export const session: { lastOpened: string | null; lastOpenedVoice: boolean } = { lastOpened: null, lastOpenedVoice: false }

/** Nombre de jours civils écoulés (0 = aujourd'hui, 1 = hier). -1 si la date est illisible. */
export function joursEcoules(d: Date): number {
  if (Number.isNaN(d.getTime())) return -1
  const jour = (x: Date): number => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  return Math.round((jour(new Date()) - jour(d)) / 86400000)
}

/** Horodatage d'une conversation dans la liste : l'heure aujourd'hui, « hier », le jour de la
 *  semaine dans les sept derniers jours, la date ensuite. */
export function formatQuand(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const n = joursEcoules(d)
  if (n <= 0) return d.toLocaleTimeString('fr-CA', { hour: '2-digit', minute: '2-digit' })
  if (n === 1) return 'hier'
  if (n < 7) return d.toLocaleDateString('fr-CA', { weekday: 'long' })
  const memeAnnee = d.getFullYear() === new Date().getFullYear()
  return d.toLocaleDateString('fr-CA', memeAnnee ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' })
}

/** Titre de section de la liste de conversations. */
export function seauDe(iso: string | null | undefined): string {
  if (!iso) return 'Plus tôt'
  const n = joursEcoules(new Date(iso))
  if (n < 0) return 'Plus tôt'
  if (n === 0) return 'Aujourd’hui'
  if (n === 1) return 'Hier'
  if (n < 7) return '7 derniers jours'
  return 'Plus tôt'
}

/** Résumé d'une entrée d'outil (bloc .tool d'une bulle). */
export function summarizeInput(input: Record<string, unknown>): string {
  if (!input) return ''
  const entries = Object.entries(input)
  if (!entries.length) return ''
  return entries
    .map(([k, v]) => {
      const s = typeof v === 'string' ? v : JSON.stringify(v)
      return `${k}: ${s.length > 80 ? s.slice(0, 80) + '…' : s}`
    })
    .join(' · ')
}

export function messageErreur(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}
