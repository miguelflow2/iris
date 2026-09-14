import React, { useEffect, useState } from 'react'
import { BtnIcone, CarteReglage, Liste, Rangee, TopBar } from '../components/ui'
import { IcoBouclier, IcoCamera, IcoCarte, IcoCopier, IcoGlobe, IcoTraduire, IcoUtilisateur } from '../components/icons'
import { api, messageErreur } from '../lib/api'
import { useStore } from '../lib/store'
import './AccessibiliteScreen.css'

/* =========================================================================
   « Mode dehors » : téléphone et lunettes dehors, ordinateur resté à la maison.

   Cet écran explique ce qui marche vraiment dehors, à quelles conditions, et
   comment le mettre en place pas à pas (docs/MODE-DEHORS.md,
   docs/ACCES-DISTANT.md). Il ne capte rien : il reste accessible sans lunettes
   (réglages, sécurité, appairage).

   Le réseau privé nommé ici (Tailscale) est un outil réseau que l'utilisateur
   installe lui-même ; ce n'est pas un fournisseur d'IA ou de voix.
   ========================================================================= */

interface Remote {
  enabled: boolean
  port: number
  urls: { ip: string; url: string }[]
  note?: string
}

interface EtatVerrou {
  actif_distance?: boolean
  code_defini?: boolean
  mot_de_passe_defini?: boolean
  courriel_defini?: boolean
  relais_connecte?: boolean
  limite?: string
}

function Commande({ texte, onCopier }: { texte: string; onCopier: (t: string) => void }): JSX.Element {
  return (
    <div className="commande">
      <code>{texte}</code>
      <BtnIcone title="Copier" aria-label={`Copier : ${texte}`} onClick={() => onCopier(texte)}>
        <IcoCopier />
      </BtnIcone>
    </div>
  )
}

export function ModeDehorsScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { nav, settings, updateSettings, toast } = useStore()
  const [remote, setRemote] = useState<Remote | null>(null)
  const [verrou, setVerrou] = useState<EtatVerrou | null>(null)
  const [compteConfigure, setCompteConfigure] = useState<boolean | null>(null)

  useEffect(() => {
    api.get('/api/remote').then(setRemote).catch(() => setRemote(null))
  }, [settings?.remote_access])

  useEffect(() => {
    api.get('/api/confiance/verrou/etat').then(setVerrou).catch(() => setVerrou(null))
    api
      .get('/api/compte')
      .then((c) => setCompteConfigure(Boolean(c?.configure)))
      .catch(() => setCompteConfigure(null))
  }, [settings?.verrou_distant_actif, settings?.telecommande])

  const copier = (texte: string): void => {
    navigator.clipboard
      .writeText(texte)
      .then(() => toast('Copié.', 'success'))
      .catch(() => toast('Impossible de copier.', 'error'))
  }

  const reglage = (patch: Record<string, unknown>, message?: string): void => {
    updateSettings(patch)
      .then(() => {
        if (message) toast(message, 'success')
      })
      .catch((err: unknown) => toast(messageErreur(err), 'error'))
  }

  return (
    <div className="ecran">
      <TopBar titre="Mode dehors" />
      <div className="contenu">
        <div className="carte col" style={{ gap: 10 }}>
          <h3 style={{ margin: 0 }}>Comment ça marche</h3>
          <div className="desc">
            Dehors, votre ordinateur reste le cerveau d’IRIS : mémoire, vision, consentements. Le téléphone le joint par un réseau privé que vous installez
            (Tailscale), sans rien publier sur Internet ni ouvrir de port sur votre routeur. Les lunettes se connectent au téléphone.
          </div>
          <div className="bloc-note attention">
            Ce montage n’a pas encore été vérifié de bout en bout sur un vrai téléphone avec les vraies lunettes.
          </div>
        </div>

        {/* ------------------------------------------------------------ ce qui marche */}
        <div className="carte colonnes-dehors">
          <div>
            <h4>Marche dehors, tant que l’ordinateur répond</h4>
            <ul>
              <li>Parler à IRIS ou lui écrire ; la réponse est lue par le téléphone. Le délai est mesuré et affiché, jamais garanti.</li>
              <li>Décrire une photo prise avec le téléphone : devant moi, lire, billets, objet, couleur, personnes (sans identification), affichage.</li>
              <li>« Où ai-je posé… ? » dans vos souvenirs.</li>
              <li>Les textos et appels préparés par IRIS : c’est vous qui envoyez.</li>
              <li>Les alertes sonores détectées à la maison par l’ordinateur, si la page IRIS est ouverte.</li>
              <li>Interprète par le téléphone, zones sans mémoire, mode invité, vision partagée (par le relais VELA).</li>
            </ul>
          </div>
          <div>
            <h4>Exige</h4>
            <ul>
              <li>L’ordinateur allumé, hors veille, IRIS ouverte.</li>
              <li>Internet des deux côtés, et le réseau privé actif sur le téléphone.</li>
              <li>La page IRIS à l’écran du téléphone : une page en arrière-plan ne reçoit plus rien, et il n’y a pas de notification.</li>
              <li>Les lunettes VELA pour tout ce qui capte ou agit. Sur Android (Chrome), la page IRIS peut les signaler par Bluetooth. Sur iPhone, Safari n’a pas de Bluetooth : dehors, sur iPhone, il faut l’app IRIS (voir plus bas).</li>
            </ul>
          </div>
          <div>
            <h4>Ne marche pas dehors</h4>
            <ul>
              <li>La caméra et les boutons des lunettes depuis la page web du téléphone.</li>
              <li>Les sous-titres de votre conversation : ils transcrivent le micro de l’ordinateur, donc la pièce où il se trouve.</li>
              <li>Les notifications quand la page est fermée, et la vibration des alertes sur iPhone.</li>
              <li>Une réponse garantie en moins de cinq secondes : le trajet passe par le réseau cellulaire, le réseau privé, l’ordinateur et parfois le moteur VELA.</li>
            </ul>
          </div>
        </div>

        {/* ------------------------------------------------------------ 1. accès */}
        <h2 className="section-sous">1. Autoriser le téléphone</h2>
        {compteConfigure === false ? (
          <div className="bloc-note attention">
            Posez d’abord le mot de passe du propriétaire : c’est la serrure de l’accès à distance.{' '}
            <button type="button" className="btn sm" onClick={() => nav.ouvrir('compte-securite')}>Compte et sécurité</button>
          </div>
        ) : null}
        <CarteReglage
          titre="Accès depuis le téléphone"
          desc="Ouvre IRIS aux appareils de votre réseau, protégé par le mot de passe. Ce réglage fixe aussi le port, pour que l’adresse reste la même d’un démarrage à l’autre."
          on={Boolean(settings?.remote_access)}
          onChange={(v) => reglage({ remote_access: v }, v ? 'Accès activé. Redémarrez IRIS pour qu’il prenne effet.' : 'Accès désactivé.')}
        />
        {settings?.remote_access ? (
          <div className="carte col" style={{ gap: 10 }}>
            {remote?.urls?.length ? (
              <>
                <div className="small muted">À la maison, sur le même WiFi, ouvrez l’une de ces adresses sur le téléphone :</div>
                {remote.urls.map((u) => (
                  <div className="row between" key={u.ip} style={{ gap: 8 }}>
                    <code className="mono" style={{ wordBreak: 'break-all', flex: 1, minWidth: 0 }}>{u.url}</code>
                    <BtnIcone title="Copier" aria-label="Copier l’adresse" onClick={() => copier(u.url)}>
                      <IcoCopier />
                    </BtnIcone>
                  </div>
                ))}
                <div className="small muted" style={{ lineHeight: 1.45 }}>
                  {remote.note || ''} Ces adresses contiennent votre jeton : ne les partagez pas. Dès qu’un mot de passe existe, ce jeton ne vaut plus depuis un autre
                  appareil ; le téléphone demande alors le mot de passe.
                </div>
              </>
            ) : (
              <div className="small muted">Redémarrez IRIS pour que l’accès réseau prenne effet ; les adresses apparaîtront ici.</div>
            )}
          </div>
        ) : null}

        {/* ------------------------------------------------------------ 2. réseau privé */}
        <h2 className="section-sous">2. Le réseau privé, pas à pas</h2>
        <div className="carte col" style={{ gap: 12 }}>
          <div className="desc">Environ trente minutes la première fois. Gratuit pour un usage personnel. C’est vous qui créez et gardez le compte du réseau privé.</div>
          <ol className="etapes">
            <li>
              Ouvrez PowerShell en administrateur (menu Démarrer, tapez « powershell », clic droit, « Exécuter en tant qu’administrateur »), dans le dossier d’IRIS :
              <Commande texte=".\scripts\installer-tunnel.ps1 -Installer" onCopier={copier} />
            </li>
            <li>
              Fermez la console, ouvrez-en une nouvelle, puis connectez la machine ; le navigateur s’ouvre pour créer ou ouvrir le compte :
              <Commande texte="tailscale up" onCopier={copier} />
            </li>
            <li>Sur le téléphone, installez l’application Tailscale depuis la boutique d’applications, connectez-vous avec le même compte et laissez-la activée.</li>
            <li>
              Dans la console d’administration du réseau privé, réglages DNS, activez « MagicDNS » puis « HTTPS Certificates ». Sans le second, pas d’adresse
              https://, donc pas de micro dans le navigateur du téléphone.
              <Commande texte="https://login.tailscale.com/admin/dns" onCopier={copier} />
            </li>
            <li>
              Publiez IRIS sur le réseau privé ; le script refuse s’il n’y a pas de mot de passe ou pas de https, et affiche l’adresse finale (du genre
              https://bureau.tail1234.ts.net/m) :
              <Commande texte=".\scripts\installer-tunnel.ps1 -Servir" onCopier={copier} />
            </li>
            <li>
              Pour vérifier sans rien changer :
              <Commande texte=".\scripts\installer-tunnel.ps1" onCopier={copier} />
            </li>
            <li>Essai qui prouve le mode dehors : coupez le WiFi du téléphone et ouvrez l’adresse en données cellulaires. N’ajoutez jamais « ?token=… » à cette adresse.</li>
          </ol>
          <div className="small muted" style={{ lineHeight: 1.45 }}>
            Ces scripts sont fournis avec le code source d’IRIS (dossier « scripts ») ; ils ne sont pas encore inclus dans l’installeur. Guide complet :
            docs/MODE-DEHORS.md.
          </div>
        </div>

        {/* ------------------------------------------------------------ 3. lunettes et téléphone */}
        <h2 className="section-sous">3. Appairer les lunettes au téléphone</h2>
        <div className="carte col" style={{ gap: 10 }}>
          <ol className="etapes">
            <li>Si les lunettes sont connectées à l’ordinateur, déconnectez-les d’abord : la connexion simultanée à deux appareils n’est pas confirmée pour ces lunettes.</li>
            <li>Mettez les lunettes en mode appairage, puis choisissez-les dans les réglages Bluetooth du téléphone.</li>
            <li>Vérifiez que la sortie audio du téléphone est bien les lunettes : la voix d’IRIS y sortira.</li>
            <li>Android (Chrome) : dans la page IRIS, tuile « Mes lunettes », touchez « Connecter mes lunettes » : le téléphone signale alors leur présence à IRIS. iPhone : l’app IRIS s’en charge ; la page web ne le peut pas.</li>
          </ol>
          <div className="small muted" style={{ lineHeight: 1.45 }}>
            Que le téléphone choisisse le micro des lunettes comme entrée n’a pas été vérifié avec ces lunettes.
          </div>
          <Liste>
            <Rangee icone={<IcoGlobe />} titre="Connecter les lunettes à cet ordinateur" onClick={() => nav.ouvrir('connecter')} compacte />
          </Liste>
        </div>

        {/* ------------------------------------------------------------ 4. écran d'accueil */}
        <h2 className="section-sous">4. IRIS sur l’écran d’accueil du téléphone</h2>
        <div className="carte col" style={{ gap: 10 }}>
          <ol className="etapes">
            <li>iPhone : ouvrez l’adresse dans Safari, bouton Partager, « Sur l’écran d’accueil », Ajouter. L’icône a sa propre session : le mot de passe est demandé une seconde fois.</li>
            <li>Android : ouvrez l’adresse dans Chrome, menu (trois points), « Ajouter à l’écran d’accueil » ou « Installer l’application ».</li>
            <li>Autorisez le micro et l’appareil photo à la première utilisation ; la position seulement si vous utilisez le guidage ou les zones sans mémoire.</li>
            <li>Gardez la page à l’écran pendant l’usage : elle coûte de la batterie, mais une page en arrière-plan ne reçoit plus les alertes.</li>
          </ol>
        </div>

        {/* ------------------------------------------------------------ 5. sécurité à distance */}
        <h2 className="section-sous">5. Si le téléphone ou les lunettes sont perdus</h2>
        <CarteReglage
          titre="Verrouillage à distance"
          desc="Permet de verrouiller IRIS, ou d’effacer ses données, depuis la page de verrouillage du relais VELA avec votre code de secours."
          on={Boolean(settings?.verrou_distant_actif)}
          onChange={(v) => reglage({ verrou_distant_actif: v })}
        />
        {settings?.verrou_distant_actif && verrou ? (
          <div className="carte col" style={{ gap: 6 }}>
            <div className="small">Mot de passe du propriétaire : {verrou.mot_de_passe_defini ? 'défini' : 'à définir'}</div>
            <div className="small">Code de secours : {verrou.code_defini ? 'défini' : 'à définir'}</div>
            <div className="small">Courriel du compte : {verrou.courriel_defini ? 'défini' : 'à définir'}</div>
            <div className="small">Liaison au relais : {verrou.relais_connecte ? 'connectée' : 'non connectée en ce moment'}</div>
            {verrou.limite ? <div className="small muted" style={{ lineHeight: 1.45 }}>{verrou.limite}</div> : null}
          </div>
        ) : null}
        <CarteReglage
          titre="Télécommande par le relais"
          desc="Autorise votre téléphone à piloter cet ordinateur à distance, par le relais VELA. Désactivée par défaut. Les actions sensibles (courriel, texto, appel, suppression) attendent votre accord sur le téléphone avant de s’exécuter."
          on={Boolean(settings?.telecommande)}
          onChange={(v) => reglage({ telecommande: v })}
        />

        {/* ------------------------------------------------------------ app iPhone */}
        <h2 className="section-sous">App IRIS pour iPhone</h2>
        <div className="carte col" style={{ gap: 8 }}>
          <span className="pill warn" style={{ alignSelf: 'flex-start' }}>Code prêt, compilation sur Mac requise</span>
          <div className="desc">
            L’app iPhone appaire les lunettes, les signale à IRIS toutes les 60 secondes et envoie à l’ordinateur les commandes dites dans les lunettes. Son code est
            écrit mais n’a encore jamais été compilé ni essayé sur un iPhone : il faut un Mac avec Xcode, et un compte développeur Apple (99 $ US par an) pour
            l’installer au-delà de 7 jours.
          </div>
        </div>

        {/* ------------------------------------------------------------ liens */}
        <h2 className="section-sous">Fonctions utiles dehors</h2>
        <Liste>
          <Rangee icone={<IcoCarte />} titre="Zones sans mémoire" onClick={() => nav.ouvrir('zones')} />
          <Rangee icone={<IcoUtilisateur />} titre="Mode invité" onClick={() => nav.ouvrir('mode-invite')} />
          <Rangee icone={<IcoTraduire />} titre="Interprète" onClick={() => nav.ouvrir('interprete')} />
          <Rangee icone={<IcoCamera />} titre="Vision partagée" onClick={() => nav.ouvrir('vision-partagee')} />
          <Rangee icone={<IcoBouclier />} titre="Verrouillage à distance" onClick={() => nav.ouvrir('verrou-distant')} />
        </Liste>
      </div>
    </div>
  )
}
