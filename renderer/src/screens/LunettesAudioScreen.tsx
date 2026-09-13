import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { TopBar } from '../components/ui'
import { api, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import './LunettesAudioScreen.css'

/* =========================================================================
   Enregistrement audio : par où IRIS écoute et par où elle répond.
   Porte intégralement la section « Le son » de l'ancienne vue Lunettes : regroupement des
   profils Bluetooth d'un même casque, trois modes en un clic, avertissements auto-réparables,
   micro réellement ouvert, et réglage manuel des deux périphériques.
   ========================================================================= */

/** Les deux profils audio d’un même casque Bluetooth, réunis sous un seul appareil pour l’utilisateur. */
interface ProfilsCasque {
  base: string // préfixe commun aux deux profils, ex. « Casque (M01 Pro_F444 »
  etiquette: string // nom lisible, ex. « M01 Pro_F444 »
  micro: string // nom du micro à enregistrer
  sortieMainsLibres: string // sortie utilisable pendant que ce micro est ouvert
  sortieStereo: string | null // sortie haute qualité, muette dès que le micro du casque sert
}

const MAINS_LIBRES = /hands-free|mains libres|hfp/i

/**
 * Windows expose aussi les périphériques sous leur chaîne de ressource de pilote
 * (« Casque (@System32\drivers\bthhfenum.sys,#2;%1 Hands-Free AG Audio%0… »). Elle est illisible,
 * contient un retour à la ligne, et le serveur ne sait pas la faire correspondre à une sortie :
 * on ne la propose jamais, ni dans les boutons ni dans les listes.
 */
function estNomLisible(nom: string): boolean {
  return Boolean(nom) && !/@|\.sys|[\r\n]/.test(nom)
}

/** Préfixe commun aux deux profils d’un casque : c’est la seule chose qui les relie entre eux. */
function nomDeBase(nom: string): string {
  return nom.split(/ hands-free/i)[0].split(/ stereo\)?/i)[0].trim()
}

/** « Casque (M01 Pro_F444 » → « M01 Pro_F444 » : ce que l’utilisateur reconnaît sur sa boîte. */
function etiquetteCasque(base: string): string {
  const i = base.indexOf('(')
  const brut = (i >= 0 ? base.slice(i + 1) : base).trim()
  return brut || base
}

function uniques(noms: string[]): string[] {
  return Array.from(new Set(noms))
}

/**
 * Regroupe les lignes brutes de /api/voice/devices par casque physique.
 *
 * Nécessaire parce que PortAudio énumère le MÊME casque jusqu’à onze fois (MME, DirectSound,
 * WASAPI, WDM-KS), sous deux profils qui s’excluent, avec des noms tantôt complets tantôt
 * tronqués. L’utilisateur, lui, n’a qu’un seul objet sur le nez.
 */
function regrouperCasques(micros: string[], sorties: string[]): ProfilsCasque[] {
  const groupes = new Map<string, ProfilsCasque>()
  for (const nom of micros.filter(estNomLisible)) {
    // Un casque n’est éligible que s’il expose un micro : sans lui, « parler ET écouter » est impossible.
    if (!MAINS_LIBRES.test(nom)) continue
    const base = nomDeBase(nom)
    const g = groupes.get(base) ?? { base, etiquette: etiquetteCasque(base), micro: nom, sortieMainsLibres: '', sortieStereo: null }
    // Micro : on garde le nom le PLUS LONG. MME tronque à 31 caractères ; le nom complet, lui,
    // est reconnu par toutes les interfaces et permet au backend de voir que ce micro est de
    // qualité téléphone (il cherche « Hands-Free » dans le nom enregistré).
    if (nom.length > g.micro.length) g.micro = nom
    groupes.set(base, g)
  }
  for (const nom of sorties.filter(estNomLisible)) {
    const g = groupes.get(nomDeBase(nom))
    if (!g) continue
    if (MAINS_LIBRES.test(nom)) {
      // Sortie mains libres : on garde le nom le PLUS COURT. La forme tronquée par MME est
      // contenue dans toutes les autres, donc elle les retrouve toutes ; le nom long, lui, ne
      // retrouverait jamais l’entrée MME et la sortie resterait silencieusement sur le PC.
      if (!g.sortieMainsLibres || nom.length < g.sortieMainsLibres.length) g.sortieMainsLibres = nom
    } else if (!g.sortieStereo || nom.length > g.sortieStereo.length) {
      g.sortieStereo = nom
    }
  }
  for (const g of groupes.values()) {
    // Aucun profil mains libres listé en sortie (arrive quand le casque vient de se connecter) :
    // le micro porte le même nom, il fera correspondance côté serveur.
    if (!g.sortieMainsLibres) g.sortieMainsLibres = g.micro
  }
  return Array.from(groupes.values())
}

function normaliser(nom: string): string {
  return nom.toLowerCase().replace(/[^a-z0-9]/g, '')
}

/** Le casque qui porte le nom des lunettes connectées ou mémorisées, sinon le premier trouvé. */
function casqueDesLunettes(casques: ProfilsCasque[], nomLunettes: string): ProfilsCasque | null {
  if (!casques.length) return null
  const cible = normaliser(nomLunettes || '')
  if (cible.length >= 3) {
    const trouve = casques.find((c) => {
      const e = normaliser(c.etiquette)
      return e.includes(cible) || cible.includes(e)
    })
    if (trouve) return trouve
  }
  return casques[0]
}

function messageErreur(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

function CarteChoix({ titre, detail, actif, disabled, onClick }: { titre: string; detail: string; actif: boolean; disabled?: boolean; onClick: () => void }): JSX.Element {
  return (
    <button type="button" className={`carte carte-choix ${actif ? 'actif' : ''}`} disabled={disabled} onClick={onClick} aria-pressed={actif}>
      <span className="titre">
        <span className={`dot ${actif ? 'on' : ''}`} />
        <span>{titre}</span>
      </span>
      <span className="detail">{detail}</span>
    </button>
  )
}

export function LunettesAudioScreen({ params }: { params?: Record<string, any> }): JSX.Element {
  void params
  const { settings, voice, lunettes, toast } = useStore()
  const [mics, setMics] = useState<string[]>([])
  const [outputs, setOutputs] = useState<string[]>([])
  const [charge, setCharge] = useState(false)
  const [applique, setApplique] = useState(false)

  const chargerPeripheriques = useCallback(async () => {
    setCharge(true)
    try {
      const r = await api.get('/api/voice/devices')
      setMics(Array.isArray(r.devices) ? r.devices : [])
      setOutputs(Array.isArray(r.outputs) ? r.outputs : [])
    } catch {
      /* liste indisponible : l’écran le dit plus bas */
    } finally {
      setCharge(false)
    }
  }, [])

  useEffect(() => {
    chargerPeripheriques()
    // Le casque audio apparaît (ou disparaît) dans Windows au moment de la connexion : la liste change.
    return api.on((e: IrisEvent) => {
      if (e.type === 'glasses.connected' || e.type === 'glasses.disconnected') chargerPeripheriques()
    })
  }, [chargerPeripheriques])

  const connected = Boolean(lunettes?.connected)
  const remembered = lunettes?.remembered
  const entree: string = settings?.audio_input_device || ''
  const sortie: string = settings?.audio_output_device || ''

  const casques = useMemo(() => regrouperCasques(mics, outputs), [mics, outputs])
  const casque = useMemo(
    () => casqueDesLunettes(casques, lunettes?.device?.name || remembered?.name || ''),
    [casques, lunettes?.device?.name, remembered?.name]
  )

  /**
   * Un seul appel pose les DEUX périphériques. Séparer les deux réglages laisserait l’utilisateur,
   * l’espace d’un clic, avec le micro du casque ouvert et la voix d’IRIS restée sur le PC — ou pire,
   * dirigée vers une sortie stéréo que Windows vient d’éteindre en ouvrant ce micro.
   */
  const appliquer = async (nouvelleEntree: string, nouvelleSortie: string, message: string): Promise<void> => {
    setApplique(true)
    try {
      await api.patch('/api/glasses/prefs', { audio_input_device: nouvelleEntree, audio_output_device: nouvelleSortie })
      toast(message, 'success')
    } catch (err) {
      toast(messageErreur(err), 'error')
    } finally {
      setApplique(false)
    }
  }

  /** Réglage manuel : un seul périphérique à la fois (les réglages s'enregistrent via settings.updated). */
  const reglerManuel = (patch: { audio_input_device?: string; audio_output_device?: string }): void => {
    api.patch('/api/glasses/prefs', patch).catch((err: unknown) => toast(messageErreur(err), 'error'))
  }

  const microDesLunettes = Boolean(casque) && entree === casque!.micro
  const microEstMainsLibres = MAINS_LIBRES.test(entree)
  const sortieDansLesLunettes = Boolean(casque) && (sortie === casque!.sortieMainsLibres || (casque!.sortieStereo !== null && sortie === casque!.sortieStereo))
  const modeToutLunettes = microDesLunettes && sortie === casque?.sortieMainsLibres
  const modeVoixSeule = !entree && Boolean(casque?.sortieStereo) && sortie === casque?.sortieStereo
  const modeToutPC = !entree && !sortie

  // Combinaison impossible : le micro du casque est ouvert, donc Windows a éteint sa stéréo.
  // IRIS entendrait parfaitement et parlerait dans une sortie muette.
  const combinaisonImpossible = microEstMainsLibres && Boolean(sortie) && !MAINS_LIBRES.test(sortie)
  // Micro dans les lunettes mais voix restée sur le PC : audible pour toute la pièce, pas pour vous.
  const voixResteeSurLePC = microEstMainsLibres && !sortie

  const nomLisible = (valeur: string, vide: string): string => {
    if (!valeur) return vide
    if (casque && (valeur === casque.micro || valeur === casque.sortieMainsLibres)) return `vos lunettes (${casque.etiquette})`
    if (casque && valeur === casque.sortieStereo) return `vos lunettes (${casque.etiquette}), en haute qualité`
    return valeur
  }

  // Vérité de terrain : le micro réellement ouvert, tel que le backend l’a résolu. Le réglage
  // enregistré ne dit que l’intention ; ces deux choses ont divergé assez souvent pour qu’on
  // affiche celle qui compte.
  const microOuvert: string = voice?.running ? voice?.device || '' : ''

  const microsListe = useMemo(() => {
    const liste = uniques(mics.filter(estNomLisible))
    if (entree && !liste.includes(entree)) liste.unshift(entree)
    return liste
  }, [mics, entree])
  const sortiesListe = useMemo(() => {
    const liste = uniques(outputs.filter(estNomLisible))
    if (sortie && !liste.includes(sortie)) liste.unshift(sortie)
    return liste
  }, [outputs, sortie])

  return (
    <div className="ecran">
      <TopBar titre="Enregistrement audio" />
      <div className="contenu">
        {/* état actuel */}
        <div className="carte">
          <div style={{ fontSize: 17, lineHeight: 1.45 }}>
            En ce moment, IRIS vous écoute par <strong>{nomLisible(microOuvert || entree, 'le micro de votre ordinateur')}</strong> et vous répond par{' '}
            <strong>{nomLisible(sortie, 'la sortie audio habituelle de votre ordinateur')}</strong>.
          </div>
          {microOuvert && entree && microOuvert !== entree ? (
            <div className="small muted" style={{ marginTop: 6 }}>Micro réellement ouvert : {microOuvert}.</div>
          ) : null}
          {!microOuvert && entree ? (
            <div className="small muted" style={{ marginTop: 6 }}>Réglage enregistré ; il s’appliquera au prochain démarrage de l’écoute.</div>
          ) : null}
        </div>

        {/* avertissements auto-réparables */}
        {combinaisonImpossible ? (
          <div className="avert-audio">
            <span>
              Ces deux réglages ne peuvent pas marcher ensemble : quand IRIS utilise le micro de vos lunettes, votre ordinateur coupe leur son de bonne qualité. Vous
              ne l’entendriez pas répondre.
            </span>
            {casque ? (
              <button type="button" className="btn sm" disabled={applique} onClick={() => appliquer(casque.micro, casque.sortieMainsLibres, 'Corrigé : tout passe par vos lunettes.')}>
                Corriger
              </button>
            ) : null}
          </div>
        ) : voixResteeSurLePC ? (
          <div className="avert-audio">
            <span>IRIS vous écoute par vos lunettes mais vous répond par votre ordinateur : toute la pièce l’entend, sauf vous si vous vous éloignez.</span>
            {casque ? (
              <button type="button" className="btn sm" disabled={applique} onClick={() => appliquer(casque.micro, casque.sortieMainsLibres, 'Corrigé : tout passe par vos lunettes.')}>
                Corriger : tout mettre dans mes lunettes
              </button>
            ) : null}
          </div>
        ) : null}

        {/* les trois modes */}
        {casque ? (
          <>
            <h2 className="section-sous">Où IRIS parle et écoute</h2>
            <CarteChoix
              titre="Utiliser mes lunettes pour parler et écouter"
              detail="Mains totalement libres, où que vous soyez dans la pièce. Le son est de qualité téléphone, des deux côtés."
              actif={modeToutLunettes}
              disabled={applique}
              onClick={() => appliquer(casque.micro, casque.sortieMainsLibres, `IRIS parle et écoute dans vos lunettes (${casque.etiquette}).`)}
            />
            {casque.sortieStereo ? (
              <CarteChoix
                titre="Répondre dans mes lunettes, m’écouter par l’ordinateur"
                detail="La voix d’IRIS garde toute sa qualité. Il faut rester à portée du micro de l’ordinateur pour lui parler."
                actif={modeVoixSeule}
                disabled={applique}
                onClick={() => appliquer('', casque.sortieStereo as string, `IRIS répond dans vos lunettes (${casque.etiquette}), et vous écoute par l’ordinateur.`)}
              />
            ) : null}
            <CarteChoix
              titre="Tout par l’ordinateur"
              detail="À choisir quand vous retirez vos lunettes : IRIS reprend le micro et les haut-parleurs habituels."
              actif={modeToutPC}
              disabled={applique}
              onClick={() => appliquer('', '', 'IRIS utilise de nouveau le micro et les haut-parleurs de l’ordinateur.')}
            />
          </>
        ) : (
          <div className="carte douce">
            <div className="desc" style={{ fontSize: 15, lineHeight: 1.5 }}>
              Windows ne voit pas encore vos lunettes comme un casque audio, donc IRIS ne peut pas encore parler dedans. Appairez-les dans les réglages Bluetooth de
              Windows (elles apparaissent sous leur nom d’appareil, par exemple « M01 Pro »), puis revenez ici.
            </div>
            <button type="button" className="btn sm" style={{ marginTop: 12 }} disabled={charge} onClick={chargerPeripheriques}>
              {charge ? 'Recherche…' : 'Chercher à nouveau'}
            </button>
          </div>
        )}

        {/* Avertissement affiché dès que le micro choisi est celui d’un casque, même si le
            regroupement n’a rien trouvé : c’est une conséquence physique du sans-fil, pas un réglage. */}
        {microEstMainsLibres ? (
          <p className="small muted" style={{ lineHeight: 1.5, padding: '0 4px' }}>
            Tant qu’IRIS écoute par vos lunettes, le son est de qualité téléphone : elle comprend un peu moins bien qu’avec le micro de l’ordinateur, et sa propre
            voix perd en finesse. C’est ainsi que fonctionne un casque sans fil, aucun réglage n’y change quelque chose. Si vous l’avez autorisé dans
            Confidentialité, IRIS s’appuie alors sur la reconnaissance en ligne pour mieux vous comprendre.
          </p>
        ) : null}

        {casques.length > 1 && casque ? (
          <p className="small muted" style={{ lineHeight: 1.5, padding: '0 4px' }}>
            Plusieurs casques sont appairés. Les choix ci-dessus visent « {casque.etiquette} » ; pour un autre appareil, passez par le réglage manuel.
          </p>
        ) : null}
        {sortieDansLesLunettes && !connected ? (
          <p className="small muted" style={{ lineHeight: 1.5, padding: '0 4px' }}>
            IRIS parlera dans vos lunettes dès que Windows les aura reconnectées ; si elles sont éteintes, sa voix repartira dans l’ordinateur.
          </p>
        ) : null}

        {/* réglage manuel */}
        <details className="manuel-audio">
          <summary>Réglage manuel</summary>
          <div className="champ">
            <label htmlFor="audio-micro">Micro utilisé par IRIS</label>
            <select id="audio-micro" className="select" value={entree} onChange={(e) => reglerManuel({ audio_input_device: e.target.value })}>
              <option value="">Micro par défaut du système</option>
              {microsListe.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            <span className="aide">Le périphérique d’entrée que l’écoute ouvrira. Vide = le micro habituel de l’ordinateur.</span>
          </div>
          <div className="champ">
            <label htmlFor="audio-sortie">Sortie audio d’IRIS</label>
            <select id="audio-sortie" className="select" value={sortie} onChange={(e) => reglerManuel({ audio_output_device: e.target.value })}>
              <option value="">Sortie par défaut du système</option>
              {sortiesListe.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            <span className="aide">Où sa voix est jouée. Vide = la sortie habituelle de l’ordinateur.</span>
          </div>
          <div className="small muted" style={{ lineHeight: 1.45, marginTop: 6 }}>
            Ces deux listes se règlent séparément : elles peuvent donc produire une combinaison qu’IRIS vous signalera plus haut. Les choix du dessus, eux,
            posent toujours les deux ensemble.
          </div>
          <button type="button" className="btn sm" style={{ marginTop: 12 }} disabled={charge} onClick={chargerPeripheriques}>
            {charge ? 'Actualisation…' : 'Actualiser la liste'}
          </button>
        </details>
      </div>
    </div>
  )
}
