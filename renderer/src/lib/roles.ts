/** Rôles (personnalités) de l'assistante, choisis dans l'onglet IA.
 *  La liste de référence est servie par le backend (`GET /api/personas`) ; celle-ci est le
 *  repli si le service ne la connaît pas encore. Les identifiants doivent rester identiques
 *  des deux côtés : c'est `settings.persona` qui est enregistré. */
export interface Persona {
  id: string
  nom: string
  description: string
}

export const PERSONA_DEFAUT = 'defaut'

export const PERSONAS_DEFAUT: Persona[] = [
  { id: 'defaut', nom: 'Assistante IRIS (défaut)', description: 'Réponses équilibrées, claires et neutres' },
  { id: 'pro', nom: 'Assistante professionnelle', description: 'Concise, structurée, orientée résultats' },
  { id: 'ami', nom: 'Ami décontracté', description: 'Chaleureux, tutoiement, un brin d’humour' },
  { id: 'coach', nom: 'Coach motivant', description: 'Encourage, pose des questions, fixe des objectifs' },
  { id: 'prof', nom: 'Professeur patient', description: 'Explique pas à pas et vérifie la compréhension' },
  { id: 'humour', nom: 'Expert de la comédie', description: 'Une machine à blagues qui vous fait rire' },
  { id: 'guide', nom: 'Guide de voyage', description: 'Curieux du monde, conseils pratiques et culture' },
  { id: 'chef', nom: 'Chef cuisinier', description: 'Recettes, substitutions et astuces en cuisine' },
  { id: 'tech', nom: 'Expert technique', description: 'Précis, va au fond des choses, nomme ses limites' },
  { id: 'confident', nom: 'Confident calme', description: 'Écoute, reformule, apaise' }
]
