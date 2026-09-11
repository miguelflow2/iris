# Démo VELA — runbook du pitch (mardi 8 septembre)

> Objectif : **vendre les lunettes**. Sur scène, tu parles dans les lunettes, IRIS entend, agit, répond. Discipline > improvisation.

## Verdict

Oui, la démo est vendeuse ET raisonnablement sûre pour mardi, à condition d'appliquer les 5 réglages ci-dessous et de tenir la discipline physique — surtout : lunettes = MICRO seulement, voix qui sort dans la SALLE (pas dans les lunettes, sinon les juges n'entendent rien), téléphone Bluetooth ÉTEINT, et présentation sur TON portable avec la fenêtre IRIS visible comme plan B universel. Les quatre temps forts sont solides parce qu'ils s'appuient sur du local/hors-ligne (batterie, mémoire, YouTube à outil unique) ; seul le login est un flourish fragile, à tenter une seule fois. Les vrais tueurs de pitch (voix dans le portable, IRIS muselée par le verrou lunettes, 4 s de timeout cloud par commande) sont TOUS neutralisés par réglage. Ce n'est pas zéro risque : la transcription des commandes longues (Vosk petit fr-CA, retard jusqu'à 67 s) et la latence du cerveau (~14 s) restent réels, mais couverts par des commandes COURTES et la saisie clavier dans la fenêtre. Verdict : ça peut gagner si tu joues serré et n'improvises jamais SMS/courriel/appel ni les promesses non tenables.

## ✅ Réglages APPLIQUÉS (déjà faits par moi — il te reste à relancer)

Les 5 réglages ci-dessous sont **déjà écrits** dans les paramètres de ton IRIS (sauvegarde : `settings.json.bak-avant-demo`). **Pour qu'ils prennent effet : quitte COMPLÈTEMENT IRIS (pas juste fermer la fenêtre — quitte l'application), puis relance-la. Ne change aucun réglage dans l'interface avant de relancer.**

- APPLIQUE-LES MAINTENANT dans C:/Users/migue/AppData/Roaming/IRIS/iris-data/settings.json, puis REDÉMARRE l'app (aucune reconstruction). Ne touche à RIEN d'autre.
- 1) stt_engine : "auto" -> "vosk" (ligne 54). Supprime les ~4 s de renfort cloud Google qui expirent à CHAQUE commande (145x dans le journal) et n'apportent jamais rien ; tout reste hors ligne, zéro perte de qualité. Gain de latence énorme.
- 2) audio_output_device : "Casque (M01 Pro_F444 Stereo)" -> "" (vide, ligne 10). Court-circuite le choix par index périmé = plus JAMAIS de PaErrorCode -9999 ni de repli imprévisible : IRIS parle toujours par la sortie Windows par défaut à 24 kHz propre. À COMBINER avec le réglage physique de la sortie par défaut (voir checklist).
- 3) glasses.auto_connect : true -> false (ligne 6). Coupe la tempête de reconnexions BLE toutes les 5 s qui vole la radio à l'audio pendant le pitch. Tu te connecteras au BLE UNE seule fois à la main, au tout début, pour lire la batterie.
- 4) demo_sans_lunettes : false -> true (ligne 69). ÉCHAPPATOIRE ÉCRITE EXPRÈS POUR LA SCÈNE. Vérifié dans le code (listener.py l.410-424) : si les lunettes décrochent une seconde et que ce réglage est FALSE, non seulement la voix se tait (« Connecte tes lunettes VELA ») mais le CHAT ÉCRIT est verrouillé au même endroit — donc ton plan B « taper dans la fenêtre » ne marcherait PLUS. À TRUE, la voix ET le clavier survivent à tout hoquet Bluetooth. Laisse require_glasses=true.
- 5) remote_access : true -> false (ligne 60) SI le réseau est partagé. Ferme l'accès distant /ws (sans mot de passe) qui laisserait un tiers piloter le PC. La démo se pilote en local à la voix, tu n'en as pas besoin. Combiné au partage de connexion du téléphone, risque à zéro.
- NE CHANGE PAS : audio_input_device (déjà bon, forme MME tronquée attendue), language fr-CA, wake_aliases, local_only, require_glasses, le modèle du cerveau (claude, vérifié 200 OK). Les modifier introduirait un risque inutile la veille.

## 📋 Checklist physique (ordre STRICT)

- ORDRE STRICT le jour J — ne pas improviser l'ordre.
- La veille : charger les lunettes à 100 %. Importer les identifiants du site de démo dans le coffre IRIS et tester web_login UNE fois pour de vrai (c'est le beat le plus fragile). Préparer un fichier vidéo/musique LOCAL comme plan B YouTube. Tester le partage de connexion du téléphone.
- Batterie : lunettes chargées à 100 % le matin même (mortes = plus de micro ni de son).
- Téléphone : Bluetooth ÉTEINT, ou « oublier » les lunettes sur le téléphone. Le Bluetooth classique ne porte qu'UN lien : le téléphone vole les lunettes = « délai dépassé » = beat batterie mort.
- Distance : rester à MOINS de 2 m du portable pendant tout le pitch. Ne jamais s'éloigner.
- SÉQUENCE audio (capital) : (a) appairer + CONNECTER l'audio des lunettes dans Windows AVANT de lancer IRIS, pour que le micro « Casque (M01 Pro_F444 Hands-Free) » soit dans l'énumération de départ. (b) Dans Windows > Son, définir la SORTIE PAR DÉFAUT sur un haut-parleur que la SALLE entend (haut-parleurs du portable ou sono de la salle) — PAS les lunettes, sinon les juges n'entendent pas IRIS — et cocher « toujours utiliser ce périphérique ». (c) SEULEMENT ENSUITE lancer / redémarrer IRIS. Micro = lunettes, voix = salle : les deux sont indépendants (vérifié listener.py l.916).
- Ne JAMAIS appairer/reconnecter les lunettes une fois IRIS lancée (ré-énumération à chaud = index périmés = -9999).
- BLE batterie : cliquer « Connecter » UNE fois au tout début, lunettes fraîchement allumées, pour afficher la charge. Accepter que l'indicateur batterie FIGE dès que le micro s'ouvre — c'est normal, pas une panne ; l'audio de la démo ne dépend pas du BLE.
- Présenter EXCLUSIVEMENT sur le portable de Miguel (il a les clés) — jamais l'installateur public. Garder la fenêtre IRIS OUVERTE et VISIBLE = plan B universel de chaque beat (retaper la même phrase donne le même résultat).
- Réseau : utiliser le PARTAGE DE CONNEXION du téléphone, pas le WiFi de la salle (pas de portail captif, débit maîtrisé).
- Vérifier dans Paramètres > Voix : micro affiché = « Casque (M01 Pro_F444 Hands-Free) » et le niveau monte (pic ~6000+) quand tu parles.
- Rodage T-2 min en coulisse : dire « Dis-moi Iris, batterie ? » une fois pour établir le profil HFP et confirmer que tout répond, voix dans la salle.

## 🎬 Scénario de démo (temps par temps + plan B)

- DISCIPLINE PERMANENTE : commandes COURTES (3-6 mots), UNE à la fois, articulées, attendre qu'IRIS ait fini de parler. Ne pas utiliser le bouton muet. Ne jamais prononcer un mot d'arrêt (arrête, stop, chut, ça suffit, silence) pendant qu'elle parle. Ne jamais dire « envoie un texto/courriel » ni « appelle » (échec silencieux). Sur chaque beat, si ça rate : retaper la phrase dans la fenêtre IRIS visible.
- T-2 min (coulisse) : rodage « Dis-moi Iris, batterie ? » — confirme micro + voix dans la salle.
- 0:00 ACCROCHE (parlé, zéro tech, plan B aucun) : « Vous portez tous un téléphone. Moi, je porte mes yeux. Ces lunettes m'écoutent, agissent sur mon ordinateur, se souviennent de moi — sans que je touche à rien, sans sortir d'écran. Je vais vous montrer. »
- 0:30 TEMPS FORT 1 — BATTERIE (le plus solide, hors ligne, UNIQUE) : « Dis-moi Iris, combien de batterie il reste dans mes lunettes ? » -> elle annonce le %. Vente : « Aucune autre lunette au monde ne sait vous dire sa charge — nous oui, on a écrit le protocole. » PLAN B : lire le % dans la fenêtre IRIS et le dire à voix haute. Commencer PAR ça : ni internet ni aller-retour modèle.
- 1:30 TEMPS FORT 3a — MÉMOIRE (planter la graine tôt, local) : « Dis-moi Iris, souviens-toi que je pitche à L'Œil du dragon mardi. » PLAN B : taper la phrase.
- 2:30 TEMPS FORT 2 — YOUTUBE (visuel, outil local unique) : « Dis-moi Iris, mets [titre connu] sur YouTube. » -> la vidéo démarre. « Les mains sur la table, pas de téléphone, pas de clavier. » PLAN B : répéter UNE fois lentement ; sinon taper ; si WiFi faible : « Dis-moi Iris, ouvre [fichier local] ».
- 4:00 TEMPS FORT 3b — RAPPEL MÉMOIRE : « Dis-moi Iris, qu'est-ce que j'ai d'important cette semaine ? » -> elle ressort le pitch. « Elle ne m'oublie pas entre deux phrases. Ma mémoire, sur MON appareil, pas dans un nuage. » PLAN B : taper.
- 5:00 TEMPS FORT 4 — LOGIN SANS MOT DE PASSE (le wow, mais le plus fragile : multi-outils + net) : « Dis-moi Iris, connecte-moi à [site]. » -> elle ouvre et connecte. « Les mains libres, et je n'ai jamais dit mon mot de passe à voix haute. » PLAN B FORT : au moindre captcha/hésitation, enchaîner IMMÉDIATEMENT sur un beat sûr — « Dis-moi Iris, rappelle-moi d'appeler mon fournisseur dans 10 minutes » (set_reminder, local) — et clore là-dessus. NE JAMAIS réessayer le login deux fois devant la salle.
- 6:30 CLÔTURE (parlé, plan B aucun) : « Vous venez de voir des lunettes qui écoutent, agissent, et se souviennent — sans écran, sans les mains. Le cerveau est là aujourd'hui. Ce que je viens chercher, c'est mettre ces yeux sur tous les visages du Québec. »

## ⚠️ Risques résiduels & parades

- RISQUE N°1 (non corrigeable sans reconstruction) : transcription des commandes LONGUES par le petit Vosk fr-CA — charabia et retard jusqu'à 67 s (journal 14:22:33). Parade MARDI : commandes courtes + une pause nette entre deux + saisie clavier dans la fenêtre en secours. À FAIRE APRÈS : modèle Vosk plus gros ou Scribe sur la commande, décodage streaming, plafonner la file audio à quelques secondes + drain au démarrage.
- Latence du cerveau ~14 s et dépendance réseau : le « moins de 5 s » N'EST PAS garantissable avec un modèle throttlé sur un réseau de salle. Parade : partage de connexion du téléphone, questions courtes, préchauffage en coulisse. Ne PAS promettre « moins de 5 secondes ».
- -9999 (sortie audio) : neutralisé par audio_output_device="" + sortie Windows par défaut = haut-parleur de salle. Reste un angle mort : si Windows rebascule tout seul sa sortie par défaut après une bascule de profil, revérifier la sortie par défaut juste avant de monter. Reconstruction après mardi : rafraîchir les périphériques puis réessayer une fois avant le repli, et ne pas ouvrir à 44100 Hz sur le canal mains-libres.
- demo_sans_lunettes=true : en cas de décrochage réel, l'écoute retombe sur le micro du PORTABLE (capte la salle, risque de faux réveil/faux arrêt par la voix des juges). Parade : à tout décrochage, ARRÊTER de parler et passer au clavier — ne pas continuer à parler au micro de la pièce. Le vrai levier reste la stabilité physique (lunettes chargées, < 2 m, non appairées au téléphone).
- Login = beat le plus fragile (multi-outils + internet) : une seule tentative, puis pivot immédiat vers le rappel. Ne jamais insister.
- Ne jamais démontrer SMS / appel / courriel : la jambe de livraison n'est branchée nulle part, IRIS confirme un faux succès (pire qu'une erreur). Si un juge le demande : « la messagerie arrive après le lancement. »
- Ne pas promettre : voix dans l'oreille, commande des lunettes par geste, « IA fournie par VELA » (relais mort). Assumer « la voix sort dans la salle » comme un choix de scène.
- À reconstruire APRÈS mardi (ne PAS toucher avant) : garde self.connecting dans connect(), suppression du rescan BLE pour appareil appairé, timeout Bleak abaissé (8-10 s, 2 tentatives), drain de la file audio au démarrage, fermeture propre de l'authentification /ws.
