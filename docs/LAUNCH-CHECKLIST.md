# IRIS — préparation au lancement et à la démo (interview)

## État vérifié le 2026-09-03
- Installeur Windows : `release/IRIS-Setup-0.1.0.exe` (aucun prérequis sur la machine cible ; backend Python, OCR et pilote de navigateur embarqués).
- Tests backend : **106 automatisés au vert** ; TypeScript sans erreur.
- **Autotest des bibliothèques natives** intégré à la construction (`iris-backend.exe --selftest`) : winrt, bleak, OCR, Vosk, audio, num2words, Playwright. Une DLL cassée fait désormais échouer la construction au lieu de passer inaperçue.
- Vérifiés en réel sur l'app empaquetée : mot d'activation reconnu au micro, commandes locales instantanées (heure 1 s, date 1 s, ouvrir une application 2 s), question au modèle 5 s, registre de transparence intact (223 entrées), voix ElevenLabs, écoute sans retard ni perte audio.

## Ce qui a changé le 2026-09-03 (fiabilité vocale)
- **Mot d'activation** : décodage par grammaire restreinte au lieu du vocabulaire complet. Mesuré sur le modèle français : « Dis-moi Iris » devenait « dis-moi » et « Iris » devenait « arès » en 2 à 4 s ; c'est reconnu sans erreur en 0,05 s. C'était la cause principale de « elle écoute mal ».
- **Commande dite d'un seul souffle** : « Dis-moi Iris, ouvre mon navigateur » n'est plus coupé en deux.
- **« Oui ? »** ne jette plus le début de votre phrase.
- **Fin de phrase** détectée au silence ; « Je n'ai rien entendu » arrive en 4 s au lieu de 12.
- **Renfort de reconnaissance cloud** sur la commande seulement, si le consentement « audio brut » est donné. L'activation reste toujours hors ligne.
- **Mots d'arrêt** par grammaire : IRIS ne s'interrompt plus en entendant sa propre voix.
- **Journal vocal** dans `backend.log` (`stt vosk: …` avec durée, niveau, retard) et **niveau de micro en direct** dans la barre vocale.
- **Commandes locales sans modèle** : heure, date, ouvrir un site ou une application, lancer une vidéo ou une musique. Instantanées, sans réseau, sans quota.
- **Anti-boucle** : IRIS ne peut plus enchaîner clics et captures d'écran en rond ; elle le dit et s'arrête.

## À faire par Miguel avant l'interview (30 minutes)
1. Installer `IRIS-Setup-0.1.0.exe` sur le PC de démo et refaire l'assistant de démarrage (clé OpenRouter, consentements, micro = **micro du PC**, sortie = lunettes en stéréo).
2. Paramètres › Comptes web › Omnivox : saisir le mot de passe une fois (puis « Tester la connexion » ; résoudre le contrôle de sécurité si demandé).
3. **Prendre le forfait ElevenLabs Starter (≈ 5 $ US/mois)** avant la démo : le palier gratuit n'autorise que les voix anglophones (« Sarah » avec un accent en français) et 10 000 caractères/mois. Dès que le forfait est actif, IRIS bascule seule sur la voix française native « Adina ».
4. Répéter le scénario 10 fois et surveiller la barre vocale : le **niveau de micro** doit bouger quand vous parlez. S'il reste bas, changez de micro dans Paramètres › Voix.
5. Autoriser « Audio brut du micro » dans Confidentialité : la reconnaissance de la commande devient nettement meilleure en français québécois.

## Mémoire vivante (nouveau, 2026-09-03)
IRIS ne fabrique aucun souvenir. Elle retient ce que vous avez réellement dit, garde la phrase d'origine sous chaque ligne, et quand elle n'a pas l'information elle le dit au lieu de l'inventer. Vérifié en démonstration :
- « Dis-moi Iris, souviens-toi que mon interview VELA est le 9 septembre à 10 h » → retenu, avec la phrase exacte visible dans Mémoire.
- « C'est quand mon interview VELA ? » → réponse juste.
- Une question dont elle n'a pas la réponse → « Je ne l'ai pas dans ma mémoire. Tu veux me la dire pour que je la retienne ? »

Elle vit sur l'appareil : elle connaît la machine, sa date d'installation, son numéro de démarrage, son temps d'absence et votre dernier échange (barre latérale, en bas). Elle démarre avec la session Windows.

## Scénario de démo conseillé (6 minutes)
1. « Dis-moi Iris, quelle heure est-il ? » (réponse immédiate, sans réseau).
2. « Dis-moi Iris, ouvre YouTube et mets du lofi » (action réelle).
3. « Dis-moi Iris, souviens-toi que… » puis lui redemander l'information : montrer la provenance dans Mémoire.
4. **Confidentialité › Vérifier maintenant** : la chaîne SHA-256 se vérifie devant le jury. C'est l'argument que personne d'autre n'a.
5. « Dis-moi Iris, crée un jeu de morpion » (fichier créé et ouvert).
6. « Dis-moi Iris, regarde mon écran et dis-moi ce que tu vois » (vision).
7. « Dis-moi Iris, mode travail » (routine enregistrée à l'avance).
8. « stop » puis « muet » : montrer que l'utilisateur reprend la main à la voix.
9. Abonnement : plans, quota, offre groupée lunettes + Pro.

## Points de vigilance connus
- Le bouton « ⏸ Pause 10 min » arrête l'écoute temporairement : elle **reprend seule** après 10 minutes. Pour couper le micro durablement : « Muet » (bouton, Ctrl+Maj+M ou le mot « muet ») ou le mode confidentiel.
- IRIS ne lit plus une phrase en anglais : si le modèle gratuit glisse vers l'anglais, elle est traduite avant d'être dite. Les nombres, heures et unités sont écrits en toutes lettres pour être prononcés en français.
- Si IRIS parle anglais : c'est la voix Windows « Zira » qui a pris le relais d'ElevenLabs. Installer la voix Windows « Hortense » comme filet de sécurité.
- Ne jamais sélectionner le micro « Hands-Free » des lunettes (qualité téléphone et son des lunettes coupé par Windows).
- Les modèles gratuits peuvent être saturés : IRIS réessaie puis change de modèle, une pause de quelques secondes est possible.
- Bluetooth : première connexion aux lunettes 5 à 30 s ; activer « Reconnexion automatique ».
- Ne jamais présenter IRIS comme un « orchestrateur d'agents » : c'est le positionnement d'un concurrent, et c'est l'angle le plus faible. Le titre est la confidentialité prouvable, puis le contrôle de l'ordinateur, puis la mémoire. Voir `docs/DIFFERENCIATION.md` et `docs/CONCURRENCE.md`.
- **Si l'on vous parle de Relay** (249 $, sans abonnement, code ouvert, déjà en vente) : la réponse préparée est dans `docs/CONCURRENCE.md`. Ne vous comparez ni sur le prix du matériel, ni sur l'ouverture du code.
- Aucune caméra, ni chez VELA ni chez le concurrent examiné : ne rien promettre de ce côté, et ne pas s'en excuser.
