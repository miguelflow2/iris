/* ---------------------------------------------------------------------------
   « Décrire devant moi » (Ctrl+Maj+D et barre système) : la décision, sans Electron.

   Gardée à part pour être testée par Node seul (backend/tests/test_raccourci_decrire.py) : aucun import,
   seulement de la syntaxe TypeScript effaçable. Le raccourci ne doit JAMAIS laisser croire qu'il marche :
   tant que le service dit camera_lunettes_active=false (protocole de la caméra non confirmé sur le vrai
   matériel), aucune photo n'est demandée et la notification dit la limite telle quelle. On ne se rabat pas
   en silence sur une capture d'écran : un raccourci global qui enverrait l'écran (peut-être un mot de passe
   affiché) au moteur alors qu'on a demandé « devant moi » serait une surprise, pas une aide.
   --------------------------------------------------------------------------- */

export const URL_ACHAT_LUNETTES = 'https://velaglass.ca/lunettes.html'
export const MESSAGE_LUNETTES_REQUISES = 'Cette fonction marche avec les lunettes VELA. Connecte tes lunettes pour l’utiliser.'

/** Même phrase que le service (backend/iris/lunettes_camera.py, MESSAGE_CAMERA_NON_CONFIRMEE) : un test le vérifie. */
export const MESSAGE_CAMERA_NON_CONFIRMEE =
  'La caméra des lunettes n’est pas encore activée dans IRIS (son protocole est en cours de confirmation) : ' +
  'aucune photo n’a été prise. En attendant, utilisez une photo prise avec votre téléphone, ou l’écran de ' +
  'l’ordinateur.'

/** Où le faire aujourd'hui : l'écran Accessibilité propose l'image importée et l'écran du PC, choisis par l'utilisateur. */
export const OU_LE_FAIRE = 'Ouvrez IRIS › Accessibilité et choisissez « Image importée » ou « Écran du PC ».'

export interface ReponseService {
  ok: boolean
  status: number
  data: any
}

export interface Avis {
  titre: string
  corps: string
}

export type Decision = { notifier: Avis } | { decrire: { mode: 'scene'; source: 'lunettes' } }

/**
 * Jargon interne connu du service, remplacé par une phrase client (même règle que renderer/src/lib/api.ts,
 * phraseClient) : le refus du module caméra cite la charge utile en hexadécimal, un document interne et un
 * réglage d'exploration qui écrirait des octets non prouvés dans la puce des lunettes.
 */
export function phraseClient(texte: string): string {
  if (/lunettes_exploration|LUNETTES-CAMERA-PROTOCOLE|en-tête exact de la trame/i.test(texte)) return MESSAGE_CAMERA_NON_CONFIRMEE
  if (/service ae00|caractéristiques ae01/i.test(texte)) return 'Ces lunettes n’exposent pas de caméra utilisable par IRIS : aucune photo n’a été prise.'
  return texte
}

/** La phrase du service pour un refus, jamais du JSON brut. */
export function phraseRefus(data: any, repli: string): string {
  const detail = data?.detail
  if (typeof detail === 'string' && detail) return phraseClient(detail)
  if (detail && typeof detail === 'object' && typeof detail.message === 'string') return phraseClient(detail.message)
  return repli
}

/** La caméra des lunettes est-elle activée selon le service ? Seul un « true » explicite compte : un service
 *  qui ne le dit pas (ancienne version) refuserait la photo de toute façon. */
export function cameraActive(presence: any): boolean {
  return Boolean(presence && presence.camera_lunettes_active === true)
}

/**
 * Ce qu'on fait après GET /api/lunettes/presence : notifier (et ne rien capter) ou demander la description.
 * Ordre : verrou, lunettes absentes, présence invérifiable, caméra non activée ; seulement ensuite, la photo.
 */
export function decisionDecrire(presence: ReponseService): Decision {
  if (presence.status === 401) return { notifier: { titre: 'IRIS', corps: phraseRefus(presence.data, 'IRIS est verrouillée.') } }
  if (presence.ok && presence.data && presence.data.presentes === false) {
    return { notifier: { titre: 'IRIS — lunettes requises', corps: `${MESSAGE_LUNETTES_REQUISES} ${presence.data.acheter_url || URL_ACHAT_LUNETTES}` } }
  }
  if (!presence.ok) {
    // Présence invérifiable (service injoignable, version sans cette route) : on ne capte rien.
    return { notifier: { titre: 'IRIS', corps: phraseRefus(presence.data, 'La présence des lunettes n’a pas pu être vérifiée.') } }
  }
  if (!cameraActive(presence.data)) {
    return { notifier: { titre: 'IRIS — caméra des lunettes', corps: `${MESSAGE_CAMERA_NON_CONFIRMEE} ${OU_LE_FAIRE}` } }
  }
  return { decrire: { mode: 'scene', source: 'lunettes' } }
}

/** Libellé de l'entrée de la barre système : il ne présente pas comme prête une photo que le service refuserait. */
export function libelleMenuDecrire(cameraLunettesActive: boolean): string {
  return cameraLunettesActive ? 'Décrire devant moi (Ctrl+Maj+D)' : 'Décrire devant moi (caméra des lunettes pas encore activée)'
}
