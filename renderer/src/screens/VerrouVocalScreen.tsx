import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Holo, Modal, Toggle, TopBar } from '../components/ui'
import { IcoAvertissement, IcoMicro, IcoPoubelle } from '../components/icons'
import { CarteLunettesRequises } from '../components/LunettesRequises'
import { api, estLunettesRequises, messageErreur, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import './AccessibiliteScreen.css'
import './VerrouVocalScreen.css'

/* =========================================================================
   « Empreinte vocale » : seules les commandes dites d'une voix proche de la
   vôtre déclenchent IRIS, quand le verrou est actif.

   Ce que l'écran montre est ce que le service fait (backend/iris/verrou_vocal.py) :
   une vérification DE BASE, calculée et gardée sur cet ordinateur. Les textes
   de consentement, la limite et la note légale viennent du service et sont
   affichés tels quels : l'écran ne les reformule pas en promesse plus forte.

   Donnée biométrique : rien ne s'enregistre sans consentement exprès (case à
   cocher + bouton), retirer le consentement efface l'empreinte, et effacer
   reste possible sans lunettes (Loi 25). Enregistrer et tester, eux, captent
   la voix : ils exigent les lunettes, comme toute fonction qui écoute.
   ========================================================================= */

interface EtatVoix {
  enregistree: boolean
  echantillons: number
  echantillons_requis: number
  actif: boolean
  reglage_actif: boolean
  seuil: number
  consentement_biometrique: boolean
  limite: string
  texte_consentement: string
  note_legale: string
  phrase_suggeree: string
}

interface ResultatTest {
  score: number
  admis: boolean
  seuil: number
}

type Action = 'consentement' | 'echantillon' | 'test' | 'effacer' | 'retirer' | 'activer'

/** Durées d'écoute demandées au service (il les borne de 2 à 10 s). La phrase proposée se lit en 5 s environ. */
const SECONDES_ECHANTILLON = 6
const SECONDES_TEST = 4
/** On en suggère jusqu'à cinq ; le service en garde huit au plus (les plus récents). */
const ECHANTILLONS_SUGGERES = 5

export function VerrouVocalScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { updateSettings, toast, presence, exigerLunettes } = useStore()
  const [etat, setEtat] = useState<EtatVoix | null>(null)
  const [erreurEtat, setErreurEtat] = useState('')
  const [accepte, setAccepte] = useState(false)
  const [occupe, setOccupe] = useState<Action | null>(null)
  const [compte, setCompte] = useState<number | null>(null)
  const [erreur, setErreur] = useState<{ action: Action; texte: string } | null>(null)
  const [succes, setSucces] = useState('')
  const [test, setTest] = useState<ResultatTest | null>(null)
  const [seuil, setSeuil] = useState<number>(70)
  const [confirmer, setConfirmer] = useState<'effacer' | 'retirer' | null>(null)
  const [dernierRefus, setDernierRefus] = useState<{ raison: string; quand: number } | null>(null)
  const minuterieSeuil = useRef<number | null>(null)
  const minuterieCompte = useRef<number | null>(null)

  const absentes = presence !== null && !presence.presentes

  const charger = useCallback(async (): Promise<void> => {
    try {
      const e = await api.get<EtatVoix>('/api/confiance/voix')
      setEtat(e)
      setSeuil(Number(e.seuil) || 70)
      setErreurEtat('')
    } catch (err) {
      setErreurEtat(messageErreur(err))
    }
  }, [])

  useEffect(() => {
    charger().catch(() => undefined)
    let relecture: number | null = null
    const off = api.on((e: IrisEvent) => {
      if (e.type === 'settings.updated') {
        // Le service installe ou retire le verrou APRÈS avoir reçu les réglages : on relit un peu plus tard.
        if (relecture) window.clearTimeout(relecture)
        relecture = window.setTimeout(() => charger().catch(() => undefined), 400)
      } else if (e.type === 'voice.locuteur_refuse') {
        setDernierRefus({ raison: String(e.raison || ''), quand: Date.now() })
      }
    })
    return () => {
      off()
      if (relecture) window.clearTimeout(relecture)
      // La minuterie du seuil n'est PAS annulée : un seuil changé juste avant de quitter l'écran doit être enregistré.
      if (minuterieCompte.current) window.clearInterval(minuterieCompte.current)
    }
  }, [charger])

  /** Décompte affiché pendant que le service écoute (la requête bloque le temps de l'enregistrement). */
  const lancerCompte = (secondes: number): void => {
    if (minuterieCompte.current) window.clearInterval(minuterieCompte.current)
    setCompte(secondes)
    const fin = Date.now() + secondes * 1000
    minuterieCompte.current = window.setInterval(() => {
      const reste = Math.ceil((fin - Date.now()) / 1000)
      setCompte(Math.max(0, reste))
      if (reste <= 0 && minuterieCompte.current) {
        window.clearInterval(minuterieCompte.current)
        minuterieCompte.current = null
      }
    }, 250)
  }
  const arreterCompte = (): void => {
    if (minuterieCompte.current) window.clearInterval(minuterieCompte.current)
    minuterieCompte.current = null
    setCompte(null)
  }

  const donnerConsentement = async (): Promise<void> => {
    if (!accepte) return
    setOccupe('consentement')
    setErreur(null)
    try {
      setEtat(await api.post<EtatVoix>('/api/confiance/voix/consentement', { accepte: true }))
      setSucces('Consentement enregistré. Vous pouvez maintenant enregistrer votre voix.')
    } catch (err) {
      setErreur({ action: 'consentement', texte: messageErreur(err) })
    } finally {
      setOccupe(null)
    }
  }

  const enregistrerEchantillon = async (): Promise<void> => {
    if (!exigerLunettes('Empreinte vocale')) return
    setOccupe('echantillon')
    setErreur(null)
    setSucces('')
    setTest(null)
    lancerCompte(SECONDES_ECHANTILLON)
    try {
      const r = await api.post<{ echantillons: number; pret: boolean }>('/api/confiance/voix/echantillon', { secondes: SECONDES_ECHANTILLON })
      setSucces(
        r.pret
          ? `Échantillon ${r.echantillons} enregistré. L’empreinte est prête : testez-la, puis activez le verrou.`
          : `Échantillon ${r.echantillons} enregistré. Encore ${Math.max(0, (etat?.echantillons_requis || 3) - r.echantillons)} pour une empreinte utilisable.`
      )
      await charger()
    } catch (err) {
      if (!estLunettesRequises(err)) setErreur({ action: 'echantillon', texte: messageErreur(err) })
    } finally {
      arreterCompte()
      setOccupe(null)
    }
  }

  const tester = async (): Promise<void> => {
    if (!exigerLunettes('Empreinte vocale')) return
    setOccupe('test')
    setErreur(null)
    setSucces('')
    setTest(null)
    lancerCompte(SECONDES_TEST)
    try {
      setTest(await api.post<ResultatTest>('/api/confiance/voix/tester', { secondes: SECONDES_TEST }))
    } catch (err) {
      if (!estLunettesRequises(err)) setErreur({ action: 'test', texte: messageErreur(err) })
    } finally {
      arreterCompte()
      setOccupe(null)
    }
  }

  const basculer = (on: boolean): void => {
    setOccupe('activer')
    setErreur(null)
    updateSettings({ verrou_vocal_actif: on })
      .then(() => charger())
      .catch((err: unknown) => setErreur({ action: 'activer', texte: messageErreur(err) }))
      .finally(() => setOccupe(null))
  }

  const changerSeuil = (valeur: number): void => {
    setSeuil(valeur)
    if (minuterieSeuil.current) window.clearTimeout(minuterieSeuil.current)
    minuterieSeuil.current = window.setTimeout(() => {
      updateSettings({ verrou_vocal_seuil: valeur }).catch((err: unknown) => toast(messageErreur(err), 'error'))
    }, 500)
  }

  const effacer = async (quoi: 'effacer' | 'retirer'): Promise<void> => {
    setConfirmer(null)
    setOccupe(quoi)
    setErreur(null)
    setSucces('')
    setTest(null)
    try {
      const e =
        quoi === 'retirer'
          ? await api.post<EtatVoix>('/api/confiance/voix/consentement', { accepte: false })
          : await api.delete<EtatVoix>('/api/confiance/voix')
      setEtat(e)
      setAccepte(false)
      setSucces(quoi === 'retirer' ? 'Consentement retiré : l’empreinte vocale est effacée de cet ordinateur.' : 'Empreinte vocale effacée de cet ordinateur.')
    } catch (err) {
      setErreur({ action: quoi, texte: messageErreur(err) })
    } finally {
      setOccupe(null)
    }
  }

  const consenti = Boolean(etat?.consentement_biometrique)
  const requis = etat?.echantillons_requis || 3
  const nb = etat?.echantillons || 0
  const pret = Boolean(etat?.enregistree)
  const enEcoute = occupe === 'echantillon' || occupe === 'test'

  const erreurDe = (action: Action | Action[]): JSX.Element | null => {
    const liste = Array.isArray(action) ? action : [action]
    return erreur && liste.includes(erreur.action) ? (
      <div className="bloc-note erreur" role="alert">{erreur.texte}</div>
    ) : null
  }

  return (
    <div className="ecran">
      <TopBar titre="Empreinte vocale" />
      <div className="contenu">
        <div className="vv-hero">
          <h2>Des commandes réservées à votre voix</h2>
          <p>
            Quand le verrou vocal est actif, IRIS compare la voix de chaque commande à votre empreinte et ignore celles qui ne lui ressemblent pas assez. Le
            calcul se fait sur cet ordinateur ; votre voix n’est pas envoyée.
          </p>
        </div>

        {erreurEtat ? <div className="bloc-note erreur" role="alert">{erreurEtat}</div> : null}
        {etat?.limite ? (
          <div className="bloc-note attention">
            <strong>Limite : </strong>
            {etat.limite}
          </div>
        ) : null}

        {etat ? (
          <div className="vv-etat" aria-live="polite">
            <span className={`pill ${consenti ? 'ok' : ''}`}>{consenti ? 'Consentement donné' : 'Consentement non donné'}</span>
            <span className={`pill ${pret ? 'ok' : ''}`}>
              Empreinte : {nb} échantillon{nb > 1 ? 's' : ''}
              {pret ? ' (prête)' : ` sur ${requis} requis`}
            </span>
            <span className={`pill ${etat.actif ? 'ok' : ''}`}>{etat.actif ? 'Verrou actif' : 'Verrou inactif'}</span>
          </div>
        ) : null}

        {succes ? <div className="bloc-note ok" aria-live="polite">{succes}</div> : null}

        {/* ------------------------------------------------------------ 1. consentement exprès */}
        {etat && !consenti ? (
          <div className="carte col vv-consentement" style={{ gap: 12 }}>
            <h3 style={{ margin: 0 }}>1. Votre consentement exprès</h3>
            <p className="vv-texte-legal">{etat.texte_consentement}</p>
            <ul className="liste-limites">
              <li>Ce qu’IRIS garde : des mesures de votre voix (jamais l’enregistrement lui-même), chiffrées, sur cet ordinateur seulement.</li>
              <li>À quoi elles servent : décider si une commande vocale vient de vous, quand le verrou est actif. À rien d’autre.</li>
              <li>Le consentement est daté et noté dans le registre de confidentialité. Vous pouvez le retirer ici à tout moment.</li>
            </ul>
            <label className="vv-case">
              <input type="checkbox" checked={accepte} onChange={(e) => setAccepte(e.target.checked)} />
              <span>J’ai lu ce texte et j’accepte qu’IRIS calcule et conserve mon empreinte vocale sur cet ordinateur.</span>
            </label>
            <Holo disabled={!accepte || occupe !== null} onClick={donnerConsentement}>
              {occupe === 'consentement' ? 'Enregistrement…' : 'Donner mon consentement'}
            </Holo>
            {erreurDe('consentement')}
          </div>
        ) : null}

        {/* ------------------------------------------------------------ 2. échantillons */}
        {etat && consenti ? (
          <>
            {absentes ? <CarteLunettesRequises fonction="Enregistrer ou tester votre empreinte vocale" /> : null}

            <div className="carte col" style={{ gap: 12 }}>
              <h3 style={{ margin: 0 }}>2. Enregistrer votre voix</h3>
              <div className="desc">
                Au moins {requis} échantillons ; jusqu’à {ECHANTILLONS_SUGGERES} donnent à IRIS plus d’exemples de votre voix. Chaque clic écoute{' '}
                {SECONDES_ECHANTILLON} secondes.
              </div>
              <div className="vv-points" role="img" aria-label={`${nb} échantillon${nb > 1 ? 's' : ''} enregistré${nb > 1 ? 's' : ''}`}>
                {Array.from({ length: Math.max(ECHANTILLONS_SUGGERES, nb) }, (_, i) => (
                  <span key={i} className={`${i < nb ? 'fait' : ''} ${i === requis - 1 ? 'seuil' : ''}`.trim()} />
                ))}
              </div>

              <div className="vv-phrase">
                <span className="consigne">Lisez à voix haute, d’une voix normale :</span>
                <span className="texte">« {etat.phrase_suggeree} »</span>
              </div>

              {enEcoute && compte !== null ? (
                <div className="vv-compte" role="status" aria-live="assertive">
                  <span className="dot rec" aria-hidden="true" />
                  {compte > 0 ? (
                    <span>
                      {occupe === 'test' ? 'Parlez maintenant' : 'Lisez la phrase maintenant'} : {compte} s
                    </span>
                  ) : (
                    <span>Analyse sur cet ordinateur…</span>
                  )}
                </div>
              ) : null}

              <Holo disabled={occupe !== null} onClick={enregistrerEchantillon}>
                <IcoMicro /> {occupe === 'echantillon' ? 'Écoute en cours…' : nb === 0 ? 'Enregistrer le premier échantillon' : 'Enregistrer un autre échantillon'}
              </Holo>
              {erreurDe('echantillon')}
              <div className="small muted" style={{ lineHeight: 1.45 }}>
                Utilisez le micro avec lequel vous parlez à IRIS (celui des lunettes) : l’empreinte dépend aussi du micro, et un autre micro fait baisser le
                score. Si l’écoute était arrêtée, IRIS la démarre ; le décompte peut alors finir avant la fin réelle de l’enregistrement.
              </div>
            </div>

            {/* ------------------------------------------------------------ 3. tester */}
            <div className="carte col" style={{ gap: 12 }}>
              <h3 style={{ margin: 0 }}>3. Tester</h3>
              <div className="desc">
                Dites une phrase de quelques secondes, sans le mot d’activation (sinon IRIS y répondrait), par exemple « Quelle heure est-il, et quel temps
                fera-t-il demain ? ». IRIS calcule un score sur 100 et le compare au seuil.
              </div>
              <Holo variante="sombre" disabled={!pret || occupe !== null} onClick={tester}>
                <IcoMicro /> {occupe === 'test' ? 'Écoute en cours…' : `Tester ma voix (${SECONDES_TEST} s)`}
              </Holo>
              {!pret ? <div className="small muted">Disponible après {requis} échantillons.</div> : null}
              {test ? (
                <div className={`vv-resultat ${test.admis ? 'admis' : 'refuse'}`} aria-live="polite">
                  <span className="score">
                    {test.score}
                    <small> / 100</small>
                  </span>
                  <span className="verdict">
                    {test.admis ? `Commande acceptée (seuil ${test.seuil})` : `Commande refusée (seuil ${test.seuil})`}
                  </span>
                </div>
              ) : null}
              {erreurDe('test')}
            </div>

            {/* ------------------------------------------------------------ 4. activer */}
            <div className="carte col" style={{ gap: 14 }}>
              <div className="reglage">
                <div className="corps">
                  <h3>4. Activer le verrou vocal</h3>
                  <div className="desc">
                    {pret
                      ? 'Les commandes vocales dont la voix ne ressemble pas assez à votre empreinte sont ignorées.'
                      : `Enregistrez d’abord ${requis} échantillons.`}
                  </div>
                </div>
                <Toggle
                  on={Boolean(etat.reglage_actif)}
                  disabled={occupe !== null || (!pret && !etat.reglage_actif)}
                  titre="Verrou vocal"
                  onChange={basculer}
                />
              </div>
              {etat.reglage_actif && !etat.actif ? (
                <div className="bloc-note attention">
                  Le réglage est activé, mais le verrou n’est pas installé dans l’écoute pour le moment : les commandes ne sont pas filtrées. Il s’installe dès que
                  l’empreinte est complète et que l’écoute d’IRIS est disponible.
                </div>
              ) : null}
              {erreurDe('activer')}

              <div className="col" style={{ gap: 6 }}>
                <label className="vv-seuil" htmlFor="vv-seuil">
                  <span>Seuil</span>
                  <strong>{seuil} / 100</strong>
                </label>
                <input
                  id="vv-seuil"
                  type="range"
                  min={0}
                  max={100}
                  step={1}
                  value={seuil}
                  aria-valuetext={`${seuil} sur 100`}
                  onChange={(e) => changerSeuil(Number(e.target.value))}
                />
                <div className="small muted" style={{ lineHeight: 1.45 }}>
                  Plus le seuil est haut, plus IRIS refuse les voix différentes de la vôtre, et plus elle risque aussi de refuser la vôtre (voix enrouée, bruit,
                  autre micro). Testez après chaque changement.
                </div>
              </div>

              {dernierRefus ? (
                <div className="bloc-note" aria-live="polite">
                  Dernière commande ignorée par le verrou, à {new Date(dernierRefus.quand).toLocaleTimeString('fr-CA', { hour: '2-digit', minute: '2-digit' })}
                  {dernierRefus.raison ? ` : ${dernierRefus.raison}` : ''}.
                </div>
              ) : null}
            </div>

            {/* ------------------------------------------------------------ effacer */}
            <div className="carte col" style={{ gap: 10 }}>
              <h3 style={{ margin: 0 }}>Effacer</h3>
              <div className="desc">Possible avec ou sans lunettes. Le verrou vocal se désactive avec l’empreinte.</div>
              <div className="row wrap" style={{ gap: 8 }}>
                <Holo taille="petit" variante="contour" disabled={occupe !== null || nb === 0} onClick={() => setConfirmer('effacer')}>
                  <IcoPoubelle /> Effacer mon empreinte
                </Holo>
                <Holo taille="petit" variante="contour" disabled={occupe !== null} onClick={() => setConfirmer('retirer')}>
                  Retirer mon consentement
                </Holo>
              </div>
              {erreurDe(['effacer', 'retirer'])}
            </div>
          </>
        ) : null}

        {/* ------------------------------------------------------------ limites */}
        <div className="carte">
          <h3>Ce qu’il faut savoir</h3>
          <ul className="liste-limites">
            <li>C’est une vérification de base, pas une serrure : une voix proche ou un enregistrement de votre voix peuvent la tromper. Le mot de passe du propriétaire reste la vraie protection.</li>
            <li>Une commande trop courte ne peut pas être jugée : quand le verrou est actif, elle est ignorée. Parlez un peu plus longuement.</li>
            <li>Si la vérification elle-même tombe en panne, la commande est acceptée : une panne du verrou ne rend pas IRIS sourde.</li>
            <li>Le verrou filtre les commandes vocales seulement ; le chat écrit et le téléphone ne sont pas concernés.</li>
          </ul>
        </div>

        {etat?.note_legale ? (
          <div className="carte col vv-legal" style={{ gap: 8 }}>
            <div className="row" style={{ gap: 10 }}>
              <IcoAvertissement width={22} height={22} />
              <h3 style={{ margin: 0 }}>Note légale</h3>
            </div>
            <p className="vv-texte-legal">{etat.note_legale}</p>
          </div>
        ) : null}
      </div>

      {confirmer ? (
        <Modal
          title={confirmer === 'retirer' ? 'Retirer votre consentement ?' : 'Effacer votre empreinte vocale ?'}
          onClose={() => setConfirmer(null)}
          actions={
            <>
              <button type="button" className="btn ghost" onClick={() => setConfirmer(null)}>Annuler</button>
              <button type="button" className="btn danger" onClick={() => effacer(confirmer)}>
                {confirmer === 'retirer' ? 'Retirer et effacer' : 'Effacer'}
              </button>
            </>
          }
        >
          <p>
            {confirmer === 'retirer'
              ? 'Votre empreinte vocale sera effacée de cet ordinateur et le verrou vocal désactivé. Pour le réactiver, il faudra redonner votre consentement et réenregistrer votre voix.'
              : 'Vos échantillons seront effacés de cet ordinateur et le verrou vocal désactivé. Votre consentement reste enregistré.'}
          </p>
        </Modal>
      ) : null}
    </div>
  )
}
