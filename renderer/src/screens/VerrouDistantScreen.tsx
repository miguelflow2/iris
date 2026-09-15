import React, { useCallback, useEffect, useState } from 'react'
import { CarteReglage, Field, Holo, Modal, TopBar } from '../components/ui'
import { IcoBouclier, IcoCopier, IcoGlobe } from '../components/icons'
import { api, messageErreur, type IrisEvent } from '../lib/api'
import { useStore } from '../lib/store'
import './AccessibiliteScreen.css'
import './VerrouDistantScreen.css'

/* =========================================================================
   « Verrouillage à distance » : ordinateur perdu ou volé, IRIS se verrouille
   (ou efface ses données) depuis une page web publique du relais VELA.

   Ce que l'écran montre est ce que le service fait (backend/iris/verrou.py,
   telecommande.py, serveur/verrou_distant.py) : la commande ne passe que si
   le réglage est actif, qu'un code de secours existe, que l'ordinateur est
   allumé et relié au relais. L'écran affiche chacune de ces conditions telle
   que le service la voit, au lieu d'un « protégé » global qui pourrait mentir.

   L'effacement a des limites réelles (disque non chiffré, fichiers exportés,
   mémoire interne des lunettes) : elles sont écrites ici, avant qu'on en ait
   besoin. Toujours accessible sans lunettes : il sert justement quand on les
   a perdues avec le reste.
   ========================================================================= */

interface EtatVerrou {
  verrouille: boolean
  depuis: string | null
  raison: string | null
  actif_distance: boolean
  code_defini: boolean
  mot_de_passe_defini?: boolean
  courriel_defini?: boolean
  relais_connecte?: boolean
  /** Code défini avant la preuve à usage unique (2026-09-14) : il doit être choisi de nouveau. */
  code_a_redefinir?: boolean
  /** Liaison de cet ordinateur au courriel sur le relais, confirmée par courriel (telecommande.py). */
  liaison_relais?: { etat: string; message: string } | null
  /** Code de 6 caractères de la clé de cet ordinateur, à recopier sur la page du courriel de liaison. */
  empreinte_liaison?: string | null
  /** IRIS démarre verrouillée et attend le mot de passe du propriétaire (choix de l'utilisateur). */
  ouverture_verrouillee?: boolean
  limite?: string
}

const CODE_MIN = 6
const CODE_MAX = 64

function Condition({ ok, titre, detail, action }: { ok: boolean | null; titre: string; detail: React.ReactNode; action?: React.ReactNode }): JSX.Element {
  return (
    <li className={`vd-condition ${ok === true ? 'ok' : ok === false ? 'manque' : ''}`}>
      <span className="marque" aria-hidden="true">{ok === true ? '✓' : ok === false ? '!' : '·'}</span>
      <span className="corps">
        <span className="titre">
          {titre}
          <span className="sr-etat">{ok === true ? ' : prêt' : ok === false ? ' : à faire' : ''}</span>
        </span>
        <span className="detail">{detail}</span>
      </span>
      {action ? <span className="action">{action}</span> : null}
    </li>
  )
}

export function VerrouDistantScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { nav, settings, toast, rafraichirVerrou } = useStore()
  const [etat, setEtat] = useState<EtatVerrou | null>(null)
  const [erreurEtat, setErreurEtat] = useState('')
  const [code, setCode] = useState('')
  const [code2, setCode2] = useState('')
  const [motDePasse, setMotDePasse] = useState('')
  const [occupe, setOccupe] = useState<'code' | 'verrouiller' | 'reglage' | null>(null)
  const [erreurCode, setErreurCode] = useState('')
  const [codeOk, setCodeOk] = useState('')
  const [erreurVerrou, setErreurVerrou] = useState('')
  const [confirmer, setConfirmer] = useState(false)
  const [retraitOuverture, setRetraitOuverture] = useState(false)
  const [motDePasseOuverture, setMotDePasseOuverture] = useState('')
  const [erreurOuverture, setErreurOuverture] = useState('')
  const [retraitDistant, setRetraitDistant] = useState(false)
  const [motDePasseDistant, setMotDePasseDistant] = useState('')
  const [erreurDistant, setErreurDistant] = useState('')

  const charger = useCallback(async (): Promise<void> => {
    try {
      setEtat(await api.get<EtatVerrou>('/api/confiance/verrou/etat'))
      setErreurEtat('')
    } catch (err) {
      setErreurEtat(messageErreur(err))
    }
  }, [])

  useEffect(() => {
    charger().catch(() => undefined)
    const off = api.on((e: IrisEvent) => {
      if (e.type === 'settings.updated' || e.type === 'verrou.etat' || e.type === 'verrou.distant' || e.type === 'ws.open') charger().catch(() => undefined)
    })
    // La liaison au relais s'ouvre quelques secondes après l'activation (et se rouvre seule après une
    // coupure) : l'écran relit l'état toutes les 5 s pour afficher ce qui est vrai maintenant.
    const t = window.setInterval(() => charger().catch(() => undefined), 5000)
    return () => {
      off()
      window.clearInterval(t)
    }
  }, [charger])

  const relais = String(settings?.relay_server || '').trim().replace(/\/+$/, '')
  const adressePage = relais ? `${relais}/verrou` : ''
  const courriel = String(settings?.licence_email || '').trim()
  const localOnly = Boolean(settings?.local_only)
  const actif = Boolean(etat?.actif_distance ?? settings?.verrou_distant_actif)
  const motDePasseDefini = etat?.mot_de_passe_defini
  const remplacement = Boolean(etat?.code_defini)
  // Contre-vérification du 2026-09-14 : « activé » ne veut pas dire « utilisable ». Tant que cet ordinateur n'est
  // pas lié à votre compte sur le relais (courriel confirmé), la page /verrou ne peut pas l'atteindre.
  const lie = etat?.liaison_relais?.etat === 'confirmee'

  const problemesCode: string[] = []
  if (code.length > 0 && (code.trim().length < CODE_MIN || code.trim().length > CODE_MAX)) problemesCode.push(`de ${CODE_MIN} à ${CODE_MAX} caractères`)
  if (code2.length > 0 && code !== code2) problemesCode.push('les deux saisies diffèrent')
  const codePret = code.trim().length >= CODE_MIN && code.trim().length <= CODE_MAX && code === code2 && (!remplacement || !motDePasseDefini || motDePasse.length > 0)

  /* Activer : permis. Désactiver : le service exige le mot de passe du propriétaire (403 sinon). On le demande
     AVANT, par la route dédiée : l'écran n'annonce « désactivé » que si le service l'a vraiment fait. */
  const changerDistant = async (on: boolean, motDePasseSaisi: string | null): Promise<boolean> => {
    setOccupe('reglage')
    setErreurDistant('')
    try {
      setEtat(await api.post<EtatVerrou>('/api/confiance/verrou/distant', { actif: on, mot_de_passe: motDePasseSaisi }))
      toast(
        on
          ? lie
            ? 'Verrouillage à distance activé.'
            : 'Verrouillage à distance activé, mais pas encore utilisable : cet ordinateur doit d’abord être lié à votre compte (courriel de confirmation).'
          : 'Verrouillage à distance désactivé.',
        'success'
      )
      return true
    } catch (err) {
      setErreurDistant(messageErreur(err))
      if (on) toast(messageErreur(err), 'error')
      return false
    } finally {
      setOccupe(null)
    }
  }

  const basculer = (on: boolean): void => {
    if (!on && motDePasseDefini !== false) {
      setRetraitDistant(true)
      return
    }
    changerDistant(on, null).catch(() => undefined)
  }

  /* Constat du 2026-09-14 : sur cet ordinateur, IRIS s'ouvre sans mot de passe. Choisi, elle démarre verrouillée. */
  const changerOuverture = async (on: boolean, motDePasseSaisi: string | null): Promise<boolean> => {
    setOccupe('reglage')
    setErreurOuverture('')
    try {
      setEtat(await api.post<EtatVerrou>('/api/confiance/verrou/ouverture', { actif: on, mot_de_passe: motDePasseSaisi }))
      toast(on ? 'IRIS demandera le mot de passe à chaque ouverture.' : 'Le mot de passe n’est plus demandé à l’ouverture.', 'success')
      return true
    } catch (err) {
      setErreurOuverture(messageErreur(err))
      return false
    } finally {
      setOccupe(null)
    }
  }

  const enregistrerCode = async (): Promise<void> => {
    if (!codePret) return
    setOccupe('code')
    setErreurCode('')
    setCodeOk('')
    try {
      setEtat(
        await api.post<EtatVerrou>('/api/confiance/verrou/code', {
          code: code.trim(),
          mot_de_passe: remplacement ? motDePasse : null
        })
      )
      setCode('')
      setCode2('')
      setMotDePasse('')
      setCodeOk(remplacement ? 'Nouveau code de secours enregistré. L’ancien ne fonctionne plus.' : 'Code de secours enregistré.')
    } catch (err) {
      setErreurCode(messageErreur(err))
    } finally {
      setOccupe(null)
    }
  }

  const verrouiller = async (): Promise<void> => {
    setConfirmer(false)
    setOccupe('verrouiller')
    setErreurVerrou('')
    try {
      await api.post('/api/confiance/verrouiller', {})
      // L'écran de verrouillage de la coquille prend le relais (verrou.etat, ou relecture ici si la liaison est coupée).
      await rafraichirVerrou()
    } catch (err) {
      setErreurVerrou(messageErreur(err))
    } finally {
      setOccupe(null)
    }
  }

  const copier = (texte: string): void => {
    navigator.clipboard
      .writeText(texte)
      .then(() => toast('Adresse copiée.', 'success'))
      .catch(() => toast('Impossible de copier : sélectionnez l’adresse à la main.', 'error'))
  }

  return (
    <div className="ecran">
      <TopBar titre="Verrouillage à distance" />
      <div className="contenu">
        <div className="vd-hero">
          <div className="icone" aria-hidden="true">
            <IcoBouclier />
          </div>
          <div>
            <h2>Ordinateur perdu ou volé ?</h2>
            <p>
              Depuis n’importe quel navigateur, une page du relais VELA demande à cet ordinateur de verrouiller IRIS, ou d’effacer ses données. Il faut votre
              courriel VELA et un code de secours choisi ici.
            </p>
          </div>
        </div>

        {erreurEtat ? <div className="bloc-note erreur" role="alert">{erreurEtat}</div> : null}
        {etat?.limite ? (
          <div className="bloc-note attention">
            <strong>Limite : </strong>
            {etat.limite}
          </div>
        ) : null}

        {/* ------------------------------------------------------------ conditions */}
        <div className="carte col" style={{ gap: 8 }}>
          <h3 style={{ margin: 0 }}>Pour que ça marche</h3>
          <ul className="vd-conditions" aria-live="polite">
            <Condition
              ok={motDePasseDefini ?? null}
              titre="Mot de passe du propriétaire"
              detail={motDePasseDefini ? 'Défini : c’est lui qui déverrouille IRIS.' : 'Sans lui, IRIS refuse de se verrouiller : personne ne pourrait la rouvrir.'}
              action={
                motDePasseDefini === false ? (
                  <button type="button" className="btn sm" onClick={() => nav.ouvrir('compte-securite')}>Définir</button>
                ) : undefined
              }
            />
            <Condition
              ok={etat ? Boolean(etat.courriel_defini) : null}
              titre="Courriel du compte VELA"
              detail={courriel ? `${courriel} : c’est lui qu’on donne sur la page.` : 'Aucun courriel : le relais ne saurait pas quel ordinateur joindre.'}
              action={
                etat && !etat.courriel_defini ? (
                  <button type="button" className="btn sm" onClick={() => nav.ouvrir('abonnement')}>Ajouter</button>
                ) : undefined
              }
            />
            <Condition
              ok={etat ? etat.code_defini && !etat.code_a_redefinir : null}
              titre="Code de secours"
              detail={
                etat?.code_a_redefinir
                  ? 'À choisir de nouveau : le code défini avant la mise à jour de sécurité du 14 septembre 2026 ne sert plus à distance.'
                  : etat?.code_defini
                    ? 'Défini (vous seul le connaissez ; IRIS n’en garde qu’une empreinte et une clé chiffrée).'
                    : 'À choisir plus bas.'
              }
            />
            <Condition
              ok={etat ? actif : null}
              titre="Verrouillage à distance activé"
              detail={
                !actif
                  ? 'Désactivé : la page ne peut rien faire sur cet ordinateur.'
                  : lie
                    ? 'Cet ordinateur accepte les commandes de la page, avec le bon code.'
                    : 'Activé, mais pas encore utilisable : tant que cet ordinateur n’est pas lié à votre compte (ligne « Ordinateur lié » plus bas), la page ne peut pas l’atteindre.'
              }
            />
            <Condition
              ok={etat ? Boolean(etat.relais_connecte) : null}
              titre="Liaison avec le relais"
              detail={
                etat?.relais_connecte
                  ? localOnly
                    ? 'Connectée, en mode « verrouillage seulement » : le mode 100 % local ne laisse passer que les commandes de verrouillage.'
                    : 'Connectée en ce moment.'
                  : actif
                    ? 'Pas connectée pour le moment. Elle s’ouvre seule quand Internet et l’accès au relais VELA sont disponibles.'
                    : 'Elle s’ouvre quand le verrouillage à distance est activé.'
              }
            />
            <Condition
              ok={etat ? etat.liaison_relais?.etat === 'confirmee' : null}
              titre="Ordinateur lié à votre compte"
              detail={
                <>
                  {etat?.liaison_relais?.message ||
                    (actif
                      ? 'Vérifiée à la connexion au relais. Un courriel de confirmation est envoyé à l’adresse du compte : ouvrez son lien pour lier cet ordinateur.'
                      : 'Quand le verrouillage à distance est activé, un courriel de confirmation lie cet ordinateur à votre compte. Sans ce lien, la page ne peut pas l’atteindre.')}
                  {actif && !lie && etat?.empreinte_liaison ? (
                    <span style={{ display: 'block', marginTop: 6 }}>
                      Code à recopier sur la page du courriel :{' '}
                      <strong style={{ fontFamily: 'ui-monospace, Consolas, monospace', letterSpacing: '0.2em', fontSize: '1.15em' }}>
                        {etat.empreinte_liaison}
                      </strong>
                      . Il désigne cet ordinateur : ne confirmez jamais un courriel de liaison sans ce code.
                    </span>
                  ) : null}
                </>
              }
            />
          </ul>
        </div>

        {/* ------------------------------------------------------------ réglage */}
        <CarteReglage
          titre="Verrouillage à distance"
          desc="Cet ordinateur garde une connexion sortante vers le relais VELA pour recevoir la commande. Si la télécommande du téléphone est désactivée, cette connexion ne sert qu’au verrouillage et à l’effacement."
          on={actif}
          disabled={occupe !== null || !settings}
          onChange={basculer}
        />
        <CarteReglage
          titre="Demander le mot de passe à l’ouverture d’IRIS"
          desc="Sur cet ordinateur, IRIS s’ouvre sans mot de passe. Activé, elle démarre verrouillée à chaque lancement et attend le mot de passe du propriétaire : un portable volé avec la session Windows ouverte ne donne plus accès à vos données dans IRIS. Le retirer exige ce mot de passe."
          on={Boolean(etat?.ouverture_verrouillee)}
          disabled={occupe !== null || !etat || motDePasseDefini === false}
          onChange={(v) => {
            if (v) changerOuverture(true, null).catch(() => undefined)
            else setRetraitOuverture(true)
          }}
        />
        {erreurOuverture && !retraitOuverture ? <div className="bloc-note erreur" role="alert">{erreurOuverture}</div> : null}
        {localOnly ? (
          <div className="bloc-note attention">
            Le mode 100 % local est actif : si le verrouillage à distance l’est aussi, IRIS garde seulement ce canal ouvert. Il ne transporte aucune donnée,
            et aucune commande du téléphone : seulement un bonjour signé et les commandes de verrouillage ou d’effacement.
          </div>
        ) : null}

        {/* ------------------------------------------------------------ code de secours */}
        <div className="carte col" style={{ gap: 12 }}>
          <h3 style={{ margin: 0 }}>{remplacement ? 'Changer le code de secours' : 'Choisir le code de secours'}</h3>
          <div className="desc">
            De {CODE_MIN} à {CODE_MAX} caractères, différent de votre mot de passe. Notez-le ailleurs que sur cet ordinateur.
          </div>
          <Field label="Code de secours">
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              value={code}
              maxLength={CODE_MAX}
              onChange={(e) => {
                setCode(e.target.value)
                setCodeOk('')
              }}
            />
          </Field>
          <Field label="Le même code, une seconde fois">
            <input className="input" type="password" autoComplete="new-password" value={code2} maxLength={CODE_MAX} onChange={(e) => setCode2(e.target.value)} />
          </Field>
          {remplacement && motDePasseDefini ? (
            <Field label="Mot de passe du propriétaire" hint="Exigé pour remplacer un code existant : quelqu’un qui trouve la session ouverte ne doit pas pouvoir vous priver du verrouillage à distance.">
              <input className="input" type="password" autoComplete="current-password" value={motDePasse} onChange={(e) => setMotDePasse(e.target.value)} />
            </Field>
          ) : null}
          {problemesCode.length ? <div className="small muted">À corriger : {problemesCode.join(' ; ')}.</div> : null}
          <Holo taille="petit" disabled={!codePret || occupe !== null} onClick={enregistrerCode}>
            {occupe === 'code' ? 'Enregistrement…' : remplacement ? 'Remplacer le code' : 'Enregistrer le code'}
          </Holo>
          {erreurCode ? <div className="bloc-note erreur" role="alert">{erreurCode}</div> : null}
          {codeOk ? <div className="bloc-note ok" aria-live="polite">{codeOk}</div> : null}
          <div className="small muted" style={{ lineHeight: 1.45 }}>
            Le code ne quitte jamais le navigateur de la page : elle en tire une preuve à usage unique que cet ordinateur vérifie. Le relais voit passer la
            preuve, pas le code. Une preuve permet toutefois d’essayer des codes hors ligne : choisissez un code long (12 caractères ou plus). Après 5 codes
            erronés, l’ordinateur refuse pendant 15 minutes, même après un redémarrage.
          </div>
        </div>

        {/* ------------------------------------------------------------ adresse de la page */}
        <div className="carte col" style={{ gap: 12 }}>
          <h3 style={{ margin: 0 }}>L’adresse à noter</h3>
          {adressePage ? (
            <>
              <div className="vd-adresse" lang="en">{adressePage}</div>
              <div className="row wrap" style={{ gap: 8 }}>
                <Holo taille="petit" variante="blanc" onClick={() => copier(adressePage)}>
                  <IcoCopier /> Copier
                </Holo>
                <Holo taille="petit" variante="contour" onClick={() => window.iris.openExternal(adressePage)}>
                  <IcoGlobe /> Ouvrir la page
                </Holo>
              </div>
              <div className="small muted" style={{ lineHeight: 1.45 }}>
                Notez-la sur papier ou dans votre téléphone : vous en aurez besoin justement quand vous n’aurez plus cet ordinateur. Sur la page : votre
                courriel VELA{courriel ? ` (${courriel})` : ''}, le code de secours, puis « Verrouiller » ou « Effacer ».
              </div>
            </>
          ) : (
            <div className="bloc-note attention">Aucun relais VELA n’est configuré sur cet ordinateur : la page à distance n’a pas d’adresse.</div>
          )}
        </div>

        {/* ------------------------------------------------------------ essayer */}
        <div className="carte col" style={{ gap: 12 }}>
          <h3 style={{ margin: 0 }}>Essayer le verrou</h3>
          <div className="desc">
            IRIS se verrouille ici, tout de suite, et vous la rouvrez avec le mot de passe du propriétaire. Pour essayer la page à distance, utilisez un autre
            appareil et choisissez « Verrouiller », jamais « Effacer ».
          </div>
          <Holo variante="sombre" disabled={occupe !== null || motDePasseDefini === false} onClick={() => setConfirmer(true)}>
            {occupe === 'verrouiller' ? 'Verrouillage…' : 'Verrouiller maintenant'}
          </Holo>
          {motDePasseDefini === false ? <div className="small muted">Définissez d’abord le mot de passe du propriétaire.</div> : null}
          {erreurVerrou ? <div className="bloc-note erreur" role="alert">{erreurVerrou}</div> : null}
        </div>

        {/* ------------------------------------------------------------ effacement */}
        <div className="carte">
          <h3>Ce que « Effacer » supprime sur cet ordinateur</h3>
          <ul className="liste-limites">
            <li>La mémoire, le journal d’écoute, les cours, les reçus, les rappels liés aux personnes, les conversations, les tâches, les rappels et les veilles.</li>
            <li>Les photos et enregistrements audio d’IRIS, l’empreinte vocale, les zones sans mémoire et l’état du mode invité.</li>
            <li>Les copies de secours des réglages, les clés d’API enregistrées et le journal technique d’IRIS.</li>
            <li>Les accès enregistrés : sessions des téléphones (ils devront se reconnecter), code d’appairage, clés et identifiants de services, profil du navigateur piloté par IRIS. Les lunettes associées sont oubliées.</li>
            <li>La base est ensuite compactée. Puis IRIS se verrouille, si un mot de passe existe.</li>
          </ul>
          <h3 style={{ marginTop: 16 }}>Ce qui reste, exprès</h3>
          <ul className="liste-limites">
            <li>Le compte et le mot de passe du propriétaire, pour pouvoir déverrouiller.</li>
            <li>L’accès de l’ordinateur au relais VELA et sa clé de liaison, pour qu’il reste verrouillable à distance.</li>
          </ul>
          <h3 style={{ marginTop: 16 }}>Ce que la commande ne peut pas faire</h3>
          <ul className="liste-limites">
            <li>Agir sur un ordinateur éteint ou hors ligne : la commande attend sa reconnexion dans la mémoire du relais, 72 heures au plus, et elle est perdue si le relais redémarre.</li>
            <li>
              Effacer la mémoire interne des lunettes (photos ou sons qu’elles auraient gardés) : le fabricant ne documente aucune commande pour le faire.
            </li>
            <li>Effacer les fichiers exportés hors d’IRIS (dossier Images, par exemple) ou ce qui a déjà été copié ou envoyé ailleurs.</li>
            <li>Effacer ce que le téléphone garde de son côté : sa session est révoquée, mais son contenu reste sur le téléphone.</li>
            <li>
              Garantir qu’un outil de récupération ne retrouve rien sur un disque non chiffré. Contre le vol, le chiffrement du disque de Windows (BitLocker)
              reste la vraie protection.
            </li>
            <li>Verrouiller Windows : le verrou s’applique à l’application IRIS, pas au reste de l’ordinateur.</li>
          </ul>
        </div>
      </div>

      {retraitDistant ? (
        <Modal
          title="Désactiver le verrouillage à distance ?"
          onClose={() => {
            setRetraitDistant(false)
            setMotDePasseDistant('')
            setErreurDistant('')
          }}
          actions={
            <>
              <button
                type="button"
                className="btn ghost"
                onClick={() => {
                  setRetraitDistant(false)
                  setMotDePasseDistant('')
                  setErreurDistant('')
                }}
              >
                Annuler
              </button>
              <button
                type="button"
                className="btn primary"
                disabled={!motDePasseDistant || occupe !== null}
                onClick={async () => {
                  const saisi = motDePasseDistant
                  setMotDePasseDistant('')
                  if (await changerDistant(false, saisi)) setRetraitDistant(false)
                }}
              >
                Désactiver
              </button>
            </>
          }
        >
          <div className="desc">
            Sans verrouillage à distance, la page du relais ne pourra plus verrouiller ni effacer IRIS si cet ordinateur est perdu ou volé. Confirmez avec le mot
            de passe du propriétaire.
          </div>
          <Field label="Mot de passe du propriétaire">
            <input className="input" type="password" autoComplete="current-password" value={motDePasseDistant} onChange={(e) => setMotDePasseDistant(e.target.value)} />
          </Field>
          {erreurDistant ? <div className="bloc-note erreur" role="alert">{erreurDistant}</div> : null}
        </Modal>
      ) : null}

      {retraitOuverture ? (
        <Modal
          title="Ne plus demander le mot de passe à l’ouverture ?"
          onClose={() => {
            setRetraitOuverture(false)
            setMotDePasseOuverture('')
            setErreurOuverture('')
          }}
          actions={
            <>
              <button
                type="button"
                className="btn ghost"
                onClick={() => {
                  setRetraitOuverture(false)
                  setMotDePasseOuverture('')
                  setErreurOuverture('')
                }}
              >
                Annuler
              </button>
              <button
                type="button"
                className="btn primary"
                disabled={!motDePasseOuverture || occupe !== null}
                onClick={async () => {
                  const saisi = motDePasseOuverture
                  setMotDePasseOuverture('')
                  if (await changerOuverture(false, saisi)) setRetraitOuverture(false)
                }}
              >
                Confirmer
              </button>
            </>
          }
        >
          <Field label="Mot de passe du propriétaire">
            <input className="input" type="password" autoComplete="current-password" value={motDePasseOuverture} onChange={(e) => setMotDePasseOuverture(e.target.value)} />
          </Field>
          {erreurOuverture ? <div className="bloc-note erreur" role="alert">{erreurOuverture}</div> : null}
        </Modal>
      ) : null}

      {confirmer ? (
        <Modal
          title="Verrouiller IRIS maintenant ?"
          onClose={() => setConfirmer(false)}
          actions={
            <>
              <button type="button" className="btn ghost" onClick={() => setConfirmer(false)}>Annuler</button>
              <button type="button" className="btn primary" onClick={() => verrouiller()}>Verrouiller</button>
            </>
          }
        >
          <p>
            L’écoute s’arrête, les lunettes sont déconnectées et les fonctions en cours (sous-titres, interprète, partage…) s’arrêtent. IRIS reste verrouillée
            même après un redémarrage, jusqu’à ce que vous saisissiez le mot de passe du propriétaire.
          </p>
        </Modal>
      ) : null}
    </div>
  )
}
