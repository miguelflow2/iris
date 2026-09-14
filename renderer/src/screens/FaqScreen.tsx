import React from 'react'
import { TopBar } from '../components/ui'
import { api } from '../lib/api'
import { useStore } from '../lib/store'

/* =========================================================================
   « FAQ » : questions vraies sur IRIS, dépliables, rangées par thème.

   Chaque réponse décrit ce que le code fait VRAIMENT (backend/iris/*.py), dans
   quelles conditions et avec quelles limites — règle du fondateur du
   2026-09-13 : jamais « tout », « toujours » ni « instantané » ; une latence se
   mesure et s'affiche, elle ne se promet pas. Les textes reprennent le mot
   d'activation réglé, le dossier de données réel et la taille réelle de
   l'aperçu sans lunettes. Aucun nom de fournisseur d'IA ou de voix.
   ========================================================================= */

interface Question {
  q: string
  r: React.ReactNode
}

export function FaqScreen({ params: _params }: { params?: Record<string, any> }): JSX.Element {
  const { settings, status, appInfo, presence } = useStore()
  const mot: string = settings?.wake_word || 'Dis-moi Iris'
  // Même chemin que « À propos › Dossier de données » : le dossier réel du service, userData en repli.
  const dossier: string | undefined = status?.data_dir || api.info?.data_dir || appInfo?.userData || undefined
  const apercu: number = presence?.apercu_total ?? 10

  const sections: { titre: string; questions: Question[] }[] = [
    {
      titre: 'Démarrer',
      questions: [
        {
          q: 'Comment réveiller IRIS ?',
          r: (
            <>
              Dites « {mot} » suivi de votre demande, par exemple « {mot}, ouvre mon navigateur ». Le temps de chaque réponse est mesuré et affiché dans l’onglet
              IA : quelques secondes pour une commande courte, davantage quand IRIS doit chercher, réfléchir ou agir sur l’ordinateur. Elle vous pose une question
              si elle a besoin d’une précision. Vous pouvez changer cette phrase dans Mon profil › Modifier mon profil.
            </>
          )
        },
        {
          q: 'Pourquoi IRIS demande-t-elle les lunettes VELA ?',
          r: (
            <>
              IRIS est la technologie de vos lunettes VELA. La voix, la vision, l’écoute, les enregistrements et les fonctions qui agissent demandent des lunettes
              présentes : connectées à cet ordinateur, ou signalées par l’app IRIS du téléphone qui leur est appairé. Sans lunettes, l’onglet IA offre un aperçu de{' '}
              {apercu} messages écrits. Vos données (consulter, exporter, effacer), vos réglages, la confidentialité, le mode invité, les zones sans mémoire et le
              verrouillage à distance restent accessibles sans lunettes.
            </>
          )
        },
        {
          q: 'Qu’est-ce que le mode 100 % local ?',
          r: (
            <>
              Quand il est activé (Mon profil › Confidentialité), rien ne quitte cet ordinateur : aucun moteur externe, aucune recherche web, aucun courriel. IRIS
              s’appuie alors seulement sur ce qui est installé sur la machine ; les fonctions qui exigent le moteur VELA (traduction, fiches de cours, comparaison
              de prix…) le disent et refusent.
            </>
          )
        },
        {
          q: 'Qu’est-ce que le mode confidentiel ?',
          r: (
            <>
              Un interrupteur d’urgence : le micro est coupé, et ce qui capte (sous-titres, alertes, enregistrement, écoute assistée, partage) s’arrête et refuse de
              redémarrer tant qu’il est actif. Il se trouve au bas de Mon profil, et vous êtes prévenu quand il s’active ou se désactive.
            </>
          )
        },
        {
          q: 'Où sont mes données, et sont-elles chiffrées ?',
          r: (
            <>
              Sur cet ordinateur, dans {dossier ? <>le dossier <span className="mono">{dossier}</span></> : 'le dossier de données d’IRIS'}. Les souvenirs, le
              journal d’écoute, les transcriptions de cours, les reçus et l’empreinte vocale sont chiffrés, avec une clé gardée sur la même machine. Les photos, les
              images Lumière BD et les enregistrements audio (fichiers WAV) sont stockés sans chiffrement. Le chiffrement du disque de Windows (BitLocker) reste la
              protection contre le vol de l’ordinateur.
            </>
          )
        },
        {
          q: 'Que sont les consentements ?',
          r: (
            <>
              Pour qu’un moteur externe réponde, il doit recevoir le texte de vos demandes, parfois une image ou de l’audio. Vous décidez, type par type, ce qui peut
              partir ; rien n’est envoyé sans ce oui, chaque envoi est inscrit au registre de confidentialité, et vous pouvez changer d’avis dans Confidentialité.
            </>
          )
        },
        {
          q: 'Quels sont les raccourcis clavier ?',
          r: (
            <>
              <kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>Espace</kbd> pour parler, <kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>M</kbd> pour couper le micro,{' '}
              <kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>S</kbd> pour arrêter la lecture, <kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>I</kbd> pour afficher IRIS. Ils
              fonctionnent quand IRIS est en arrière-plan.
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
              Les mots réellement dits ou écrits : décisions, promesses, chiffres, préférences. Elle n’invente rien et garde la phrase d’origine. Dans Mon profil ›
              Mémoire, vous pouvez la relire, l’exporter, effacer un souvenir, une période ou tout.
            </>
          )
        }
      ]
    },
    {
      titre: 'Lunettes, photos et album',
      questions: [
        {
          q: 'Comment prendre une photo ?',
          r: (
            <>
              Le bouton avant des lunettes prend la photo dans la mémoire des lunettes ; IRIS ne la récupère pas. Depuis IRIS (accueil, album, ou « {mot}, prends
              une photo »), la photo est demandée par Bluetooth : cette commande n’est pas encore confirmée sur les lunettes vendues, et tant qu’elle ne l’est pas,
              IRIS refuse et le dit. En attendant, les fonctions de vision acceptent une photo du téléphone ou l’écran de l’ordinateur.
            </>
          )
        },
        {
          q: 'Et les vidéos ?',
          r: (
            <>
              Les lunettes enregistrent la vidéo elles-mêmes (deux clics sur le bouton avant). Le fabricant ne documente pas leur transfert : IRIS ne récupère pas
              les vidéos. Pour la même raison, IRIS ne peut ni mettre à jour le micrologiciel, ni redémarrer les lunettes, ni effacer leur mémoire interne.
            </>
          )
        },
        {
          q: 'Qu’est-ce que Lumière BD ?',
          r: (
            <>
              Une copie d’une photo de l’album avec des aplats de couleur et des contours encrés, calculée sur cet ordinateur en quelques secondes, sans envoi.
              C’est un effet graphique, pas un dessin : sur une photo floue, sombre ou très texturée, des traits peuvent manquer ou déborder.
            </>
          )
        },
        {
          q: 'Le bouton des lunettes peut-il demander une description ?',
          r: (
            <>
              Peut-être : IRIS apprend le bouton en observant ce que les lunettes envoient quand vous appuyez (Mon profil › Bouton des lunettes). Beaucoup de
              lunettes traitent leurs boutons en interne sans rien envoyer ; dans ce cas l’apprentissage échoue et IRIS le dit.
            </>
          )
        }
      ]
    },
    {
      titre: 'Accessibilité',
      questions: [
        {
          q: 'Que peut décrire IRIS ?',
          r: (
            <>
              Ce qu’il y a devant vous ; un texte, lu mot pour mot et d’abord sur l’ordinateur ; un objet ou un produit (marque, prix affiché) ; une couleur ; des
              billets et pièces canadiens ; des personnes, en description seulement (nombre, position, vêtements, gestes : jamais d’identité, d’âge, d’origine ni
              d’état de santé) ; un affichage (numéro de bus, panneau) ; l’écran de l’ordinateur. Une description peut se tromper : IRIS est tenue de dire quand
              elle n’est pas sûre.
            </>
          )
        },
        {
          q: 'IRIS peut-elle m’avertir d’un obstacle ?',
          r: (
            <>
              Non. Les lunettes n’envoient pas de vidéo en direct : une photo prend quelques secondes à arriver. Une alerte d’obstacle en temps réel exigerait un
              traitement dans les lunettes elles-mêmes. Ne vous fiez pas à IRIS pour vous déplacer en sécurité.
            </>
          )
        },
        {
          q: 'Comment régler le débit et la longueur des réponses ?',
          r: (
            <>
              Dans Mon profil › Réglages › Voix et écoute, ou dans Accessibilité : le débit va de 0,5× à 3×. La voix Windows avance par crans ; au-delà de 2×, la
              voix reste intelligible mais moins naturelle. La longueur se règle en « Concis », « Normal » ou « Descriptif ».
            </>
          )
        },
        {
          q: 'Qu’est-ce qui n’est pas livré ?',
          r: (
            <>
              L’alerte d’obstacle en temps réel ; la reconnaissance des personnes par leur nom (donnée biométrique : consentement exprès et déclaration préalable à
              la Commission d’accès à l’information du Québec) ; la langue des signes ; la récupération des vidéos, la mise à jour du micrologiciel et
              l’effacement de la mémoire interne des lunettes (protocole non documenté par le fabricant).
            </>
          )
        }
      ]
    },
    {
      titre: 'Écoute, journal et cours',
      questions: [
        {
          q: 'Comment marchent les sous-titres en direct ?',
          r: (
            <>
              Le micro est transcrit sur cet ordinateur par un petit modèle hors ligne : aucun son ni texte ne part. La transcription est approximative (noms
              propres, accents, bruit, plusieurs voix), sans ponctuation, et ne sait pas qui parle. Le résumé (procès-verbal) est la seule action qui envoie le texte
              au moteur VELA, sur demande et avec votre accord.
            </>
          )
        },
        {
          q: 'Qu’est-ce que le journal d’écoute ?',
          r: (
            <>
              Désactivé par défaut. Activé, il garde mot pour mot, chiffrées, les phrases entendues par les sous-titres, pour retrouver « ce qui a été dit mardi ».
              La recherche se fait sur l’ordinateur, la durée de conservation s’applique, rien n’est écrit quand la mémoire est suspendue, et vous effacez une plage
              de dates ou tout le journal.
            </>
          )
        },
        {
          q: 'Les alertes sonores sont-elles fiables ?',
          r: (
            <>
              Elles aident, sans garantie. Un détecteur local cherche l’alarme, la sirène, le klaxon, la sonnette, les coups à la porte et votre prénom. Il rate des
              sons (micro éloigné, bruit fort, timbre inhabituel) et se trompe parfois ; le délai de détection va d’environ une demi-seconde à trois secondes selon
              le son. Il ne remplace ni un avertisseur de fumée ou de monoxyde de carbone, ni un avertisseur lumineux ou à vibration.
            </>
          )
        },
        {
          q: 'L’écoute assistée est-elle une aide auditive ?',
          r: (
            <>
              Non. C’est une fonction expérimentale : le son du micro, débruité et amplifié, rejoué dans les lunettes, avec un retard audible. Aucun réglage selon un
              audiogramme, aucune homologation. Elle refuse de jouer vers les haut-parleurs de l’ordinateur, pour éviter l’effet Larsen.
            </>
          )
        },
        {
          q: 'Comment marche le mode cours ?',
          r: (
            <>
              IRIS enregistre le cours (fichier WAV stocké sur cet ordinateur) et le transcrit sur place ; la transcription est chiffrée et approximative. Sur
              demande et avec votre accord, le moteur VELA en tire des fiches et des questions de révision, qui peuvent contenir des erreurs : vérifiez-les avec vos
              notes. L’import accepte les fichiers WAV seulement.
            </>
          )
        }
      ]
    },
    {
      titre: 'Au quotidien',
      questions: [
        {
          q: 'Comment marche le mode interprète ?',
          r: (
            <>
              Chacun parle sa langue ; IRIS traduit après chaque phrase, pas pendant : la traduction arrive quelques secondes plus tard, et ce délai est mesuré et
              affiché à chaque tour. La voix de votre interlocuteur est transcrite en ligne, alors qu’il n’a rien consenti : prévenez-le. Impossible en mode 100 %
              local. Dehors, le téléphone passe par la traduction de texte, sans ouvrir le micro de l’ordinateur resté à la maison.
            </>
          )
        },
        {
          q: 'Qu’est-ce que la vision partagée ?',
          r: (
            <>
              Un proche ouvre un lien temporaire et voit l’écran de l’ordinateur (quelques images par seconde) ou la caméra de votre téléphone ; il peut vous écrire,
              et IRIS vous lit ses messages. Depuis les lunettes, ce sont des photos espacées de quelques secondes, quand leur caméra est prise en charge. Trois
              personnes au plus, 30 minutes que vous prolongez vous-même, rien n’est conservé. Il faut Internet : les images passent par le relais VELA.
            </>
          )
        },
        {
          q: 'Comment IRIS lit-elle mes reçus ?',
          r: (
            <>
              Le texte du reçu est lu sur l’ordinateur ; l’image ne part au moteur VELA qu’avec l’accord « Images jointes ». IRIS vérifie que sous-total et taxes
              font le total et que les taux correspondent (TPS 5 %, TVQ 9,975 %, TVH 13, 14 ou 15 %). Un champ illisible reste vide, à corriger. Reçus et images sont
              chiffrés et s’exportent en CSV. Un reçu froissé, pâli ou manuscrit est mal lu ; ce n’est ni un avis comptable ni un avis fiscal.
            </>
          )
        },
        {
          q: 'Qu’est-ce que le mode mains occupées ?',
          r: (
            <>
              IRIS lit une recette, un montage ou une réparation étape par étape ; vous dites « suivant », « répète », « précédent ». Un minuteur n’existe que si
              l’étape dit une durée, ou si vous en demandez un. Des étapes rédigées par le moteur VELA sont annoncées comme telles : suivez la notice du fabricant, et
              un professionnel pour le gaz ou l’électricité.
            </>
          )
        },
        {
          q: 'IRIS compte-t-elle mes répétitions à l’entraînement ?',
          r: (
            <>
              Non : les lunettes ne donnent accès à aucun capteur de mouvement. Vous dites « série terminée » ; IRIS compte les séries et chronomètre le repos sur
              l’ordinateur (une mise en veille retarde l’annonce). L’historique est chiffré.
            </>
          )
        },
        {
          q: 'Comment IRIS compare-t-elle les prix ?',
          r: (
            <>
              Elle identifie le produit (photo ou nom tapé), puis cherche des prix en ligne au Canada à partir d’extraits de résultats de recherche. Ces extraits
              peuvent dater de quelques jours, et le prix comme le stock en magasin peuvent différer : la réponse le rappelle. Il faut une clé de recherche web ;
              impossible en mode 100 % local ou confidentiel.
            </>
          )
        },
        {
          q: 'Comment se déclenche un rappel lié à une personne ?',
          r: (
            <>
              Seulement sur des indices qu’IRIS constate : le prénom entendu dans les sous-titres ou dans une commande vocale, « je suis avec Marc », ou un message,
              un texto ou un courriel qui nomme la personne. Aucune reconnaissance faciale. Un nom mal transcrit ne déclenche rien ; un prénom qui est aussi un mot
              courant (Pierre, Rose) peut déclencher à tort.
            </>
          )
        },
        {
          q: 'D’où vient le résumé de la journée ?',
          r: (
            <>
              De ce qu’IRIS a réellement noté : tâches, routines, conversations, souvenirs, journal, cours, reçus, rappels. Avec votre accord, le moteur VELA le
              rédige sans rien inventer ; sinon une version plus simple est rédigée sur l’ordinateur. Ce qui s’est passé sans IRIS n’y figure pas.
            </>
          )
        }
      ]
    },
    {
      titre: 'Dehors, avec le téléphone',
      questions: [
        {
          q: 'Comment utiliser IRIS dehors ?',
          r: (
            <>
              L’ordinateur reste le cerveau d’IRIS : il doit rester allumé, hors veille, IRIS ouverte. Le téléphone le joint par un réseau privé que vous installez
              (Tailscale), sans ouvrir de port sur votre routeur ; la page IRIS doit rester affichée à l’écran du téléphone, car une page en arrière-plan ne reçoit
              plus rien. La marche à suivre est dans Mon profil › Mode dehors. Ce montage n’a pas encore été vérifié de bout en bout avec les vraies lunettes.
            </>
          )
        },
        {
          q: 'Et sur iPhone ?',
          r: (
            <>
              Safari n’a pas de Bluetooth : la page web ne peut pas signaler vos lunettes. Dehors, sur iPhone, il faut l’app IRIS, qui appaire les lunettes et les
              signale à l’ordinateur toutes les 60 secondes. Son code est écrit mais n’a pas encore été compilé ni essayé sur un iPhone. Sur Android, Chrome peut
              signaler les lunettes depuis la page IRIS.
            </>
          )
        },
        {
          q: 'IRIS répond-elle aussi vite dehors ?',
          r: (
            <>
              Non, rien n’est garanti : la demande passe par le réseau cellulaire, le réseau privé, l’ordinateur et parfois le moteur VELA. Le délai de chaque
              réponse est mesuré et affiché.
            </>
          )
        }
      ]
    },
    {
      titre: 'Confiance et sécurité',
      questions: [
        {
          q: 'Qu’est-ce que l’empreinte vocale ?',
          r: (
            <>
              Une vérification de base qui ne laisse passer que votre voix pour les commandes vocales, calculée et chiffrée sur cet ordinateur ; aucun son n’est
              gardé. Une voix proche ou un enregistrement peuvent la tromper : le mot de passe reste la vraie protection. C’est une donnée biométrique : la fonction
              est livrée désactivée, exige votre consentement exprès, et sa mise en marché demande une déclaration à la Commission d’accès à l’information du Québec.
              Enregistrez-la avec le micro que vous utilisez.
            </>
          )
        },
        {
          q: 'Comment marchent les zones sans mémoire ?',
          r: (
            <>
              Dans un lieu que vous choisissez (clinique, bureau d’un client), IRIS ne retient rien : ni souvenir, ni journal, ni cours, ni reçu. Le téléphone
              compare lui-même sa position à vos zones et n’envoie que l’identifiant de la zone. Rien ne tourne en arrière-plan : tant que l’appareil n’a pas signalé
              la sortie, la mémoire reste suspendue, et après un redémarrage d’IRIS il doit signaler la zone de nouveau.
            </>
          )
        },
        {
          q: 'Que fait le mode invité ?',
          r: (
            <>
              Il suspend la mémoire pendant qu’une autre personne utilise IRIS, puis efface à la sortie les conversations et les messages de la session. Il ne cache
              pas vos souvenirs existants dans l’application, et n’efface ni les rappels ni les tâches créés pendant la session. Il se termine seul après le délai
              choisi.
            </>
          )
        },
        {
          q: 'Que fait le verrouillage à distance ?',
          r: (
            <>
              Depuis la page de verrouillage du relais VELA, avec votre courriel et votre code de secours : « Verrouiller » arrête l’écoute, coupe les lunettes et les fonctions qui captent, et
              IRIS reste verrouillée jusqu’à votre mot de passe, même après un redémarrage. « Effacer » supprime la mémoire, le journal, les cours, les reçus, les
              conversations, les tâches, rappels et surveillances, les photos et l’audio, l’empreinte vocale, les zones et les accès enregistrés. Restent : votre compte et votre
              mot de passe, l’accès de l’ordinateur au relais, les fichiers exportés hors d’IRIS, ce que le téléphone garde, et la mémoire interne des lunettes.
              Rien ne se passe si l’ordinateur est éteint ou hors ligne, et un outil de récupération peut retrouver des données sur un disque non chiffré. Le verrou
              s’applique à l’application IRIS, pas à Windows.
            </>
          )
        }
      ]
    }
  ]

  return (
    <div className="ecran">
      <TopBar titre="FAQ" />
      <div className="contenu serre">
        {sections.map((section) => (
          <section key={section.titre} className="col" style={{ gap: 10 }} aria-label={section.titre}>
            <h3 className="section-sous" style={{ margin: '10px 0 0' }}>{section.titre}</h3>
            {section.questions.map((item) => (
              <details key={item.q} className="carte" style={{ padding: '14px 18px' }}>
                <summary style={{ fontSize: 19, fontWeight: 700, cursor: 'pointer', listStyle: 'none' }}>{item.q}</summary>
                <p className="desc" style={{ marginTop: 10 }}>{item.r}</p>
              </details>
            ))}
          </section>
        ))}
      </div>
    </div>
  )
}
