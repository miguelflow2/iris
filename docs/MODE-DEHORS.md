# Mode dehors — IRIS sur l'iPhone, l'ordinateur resté à la maison

Écrit le 2026-09-13 pour Miguel. Pas à pas, sans supposer qu'on est administrateur système.
Complète `docs/ACCES-DISTANT.md` (le pourquoi du réseau privé) : ici, le comment, de bout en bout.

**Le montage en une phrase.** L'ordinateur de la maison fait tourner IRIS (le cerveau, la mémoire,
les consentements) ; l'iPhone ouvre la page `https://<machine>.ts.net/m` à travers le réseau privé
Tailscale ; les lunettes sont appairées à l'iPhone comme écouteurs Bluetooth. Rien n'est publié sur
Internet et aucun port n'est ouvert sur la box.

```
lunettes ──Bluetooth audio──> iPhone (Safari, page /m) ──Tailscale──> ordinateur (IRIS)
   micro et haut-parleur          voix du téléphone,             mémoire, vision, moteur,
   (mains libres)                 photo du téléphone              brouillons, alertes
```

---

## 1. Sur l'ordinateur, une seule fois

1. **Ouvrez IRIS** et laissez-la ouverte. Si l'ordinateur se met en veille, IRIS ne répond plus :
   réglez la mise en veille de Windows sur « Jamais » quand il est branché (Paramètres › Système ›
   Alimentation).
2. **Posez un mot de passe** : IRIS › Profil › Compte et sécurité. C'est la serrure de tout le reste ;
   le script de l'étape 4 refuse de publier sans lui.
3. **Activez l'accès téléphone** au même endroit. Ce réglage fige le port (8765) et garde le même
   jeton d'un démarrage à l'autre ; sans lui, le tunnel pointerait dans le vide après un redémarrage.
4. **Installez et publiez le réseau privé.** PowerShell *en administrateur* (menu Démarrer, tapez
   `powershell`, clic droit, « Exécuter en tant qu'administrateur »), dans le dossier d'IRIS :
   ```powershell
   .\scripts\installer-tunnel.ps1 -Installer
   ```
   Fermez la console, ouvrez-en une nouvelle, puis :
   ```powershell
   tailscale up
   ```
   Le navigateur s'ouvre : connectez-vous ou créez le compte Tailscale. **C'est vous qui choisissez
   ce compte** ; mettez-y la double authentification.
5. **Deux interrupteurs dans la console Tailscale** (https://login.tailscale.com/admin/dns) :
   *MagicDNS*, puis *HTTPS Certificates*. Sans le second, pas de `https://`, donc pas de micro dans
   Safari.
6. **Publiez IRIS sur le réseau privé :**
   ```powershell
   .\scripts\installer-tunnel.ps1 -Servir
   ```
   Le script affiche l'adresse finale, du genre `https://bureau.tail1234.ts.net/m`. Notez-la.
   `.\scripts\installer-tunnel.ps1` sans option ne change rien : il vérifie et dit ce qui bloque.

## 2. Sur l'iPhone, une seule fois

1. **Installez l'application Tailscale** (App Store), connectez-vous avec **le même compte**, et
   laissez l'interrupteur activé. iOS affiche alors « VPN » dans la barre d'état.
2. **Ouvrez Safari** (pas Chrome : sur iPhone, seul Safari sait poser une page sur l'écran d'accueil)
   et tapez l'adresse notée : `https://<machine>.ts.net/m`. N'ajoutez **jamais** `?token=…` :
   une adresse finit dans l'historique et dans les captures d'écran ; le mot de passe suffit.
3. **Entrez le mot de passe d'IRIS.** La session dure 30 jours sur ce téléphone.
4. **Posez IRIS sur l'écran d'accueil** : bouton Partager (le carré avec une flèche, en bas de
   Safari) › « Sur l'écran d'accueil » › Ajouter. Attention : l'icône de l'écran d'accueil a sa
   propre mémoire, séparée de Safari — **il faudra entrer le mot de passe une seconde fois** en
   l'ouvrant la première fois.
5. **Autorisez le micro et la reconnaissance vocale** à la première pression sur « Appuyez pour
   parler ». Si vous avez refusé : Réglages › Safari › Micro (et Réglages › Confidentialité et
   sécurité › Reconnaissance vocale).
6. **Autorisez l'appareil photo** à la première photo (« Décrire une photo »), et la position
   seulement si vous utilisez le guidage ou les zones sans mémoire.

## 3. Appairer les lunettes à l'iPhone (audio Bluetooth)

1. **Si les lunettes sont connectées à l'ordinateur, déconnectez-les d'abord** (IRIS › Lunettes, ou
   Bluetooth de Windows). Des écouteurs Bluetooth ne se relient en général qu'à un appareil à la fois
   pour l'audio ; la connexion simultanée à deux appareils (« multipoint ») n'est **pas confirmée**
   pour ces lunettes.
2. Mettez les lunettes en mode appairage (geste décrit par la notice du fabricant ; il n'est pas
   documenté ici).
3. iPhone › Réglages › Bluetooth › touchez les lunettes dans « Autres appareils ».
4. Vérifiez la sortie audio : dans le Centre de contrôle, le carré Musique › icône AirPlay › les
   lunettes. La voix d'IRIS (synthèse du téléphone) sort alors dans les lunettes.
5. Le micro des lunettes sert à la dictée **si iOS le choisit** comme entrée (il le fait en général
   pour des écouteurs mains libres ; non vérifié avec ces lunettes).

**Ce que l'appairage à l'iPhone ne donne PAS :** la caméra et les boutons des lunettes. Ils passent
par Bluetooth basse énergie, pilotés par IRIS sur l'ordinateur ; Safari sur iPhone ne sait pas parler
Bluetooth basse énergie, et l'ordinateur est hors de portée (une dizaine de mètres). Dehors, la photo
à décrire vient donc de l'appareil photo du **téléphone**.

## 4. À chaque sortie

- **Tailscale activé** sur l'iPhone (il se met parfois en veille : rouvrez l'application).
- **Ouvrez IRIS** depuis l'écran d'accueil et **gardez-la à l'écran**. Réglages de la page ›
  « Garder l'écran allumé » (voir la section 6 pour le pourquoi).
- Regardez la pastille en haut à droite : « Connectée au PC · 240 ms » (aller-retour mesuré à
  l'instant) ou « Hors ligne », avec la raison possible écrite en clair.

## 5. Ce qui marche dehors, ce qui ne marche pas

**Marche** (tant que l'ordinateur répond) :
- Parler à IRIS ou lui écrire ; la réponse s'affiche et est lue par le téléphone. Le délai affiché
  sous chaque réponse est **mesuré sur le téléphone**, jamais promis.
- Décrire une photo prise avec le téléphone : devant moi, lire un texte, billets et pièces, objet,
  couleur, personnes (description sans identification), affichage (numéro de bus, panneau). La photo
  est réduite à 1 280 px sur le téléphone avant l'envoi et n'est pas gardée par IRIS ; la description
  l'est si « Retenir » est coché et que la mémoire n'est pas suspendue.
- « Où ai-je posé ? » dans les souvenirs datés de l'ordinateur.
- Les textos et appels préparés par IRIS : Messages ou le composeur s'ouvre déjà rempli, c'est vous
  qui envoyez.
- Les alertes sonores détectées **à la maison** par l'ordinateur (alarme de fumée, sonnette…),
  affichées en plein écran si la page est ouverte.
- Réglages : débit de la voix, longueur des réponses, grand texte.
- Modules de l'équipe mobile-dehors, quand ils sont livrés : guidage à pied, zones sans mémoire,
  vision partagée (passe par le relais VELA), achats, mode invité, interprète.

**Exige** : l'ordinateur allumé et hors veille, IRIS ouverte, Internet des deux côtés, Tailscale actif
sur l'iPhone, la page IRIS à l'écran.

**Ne marche pas dehors :**
- La caméra et les boutons des lunettes (section 3).
- Les **sous-titres de votre conversation** : les sous-titres transcrivent le micro de l'ordinateur,
  donc la pièce où il se trouve. La page le dit.
- Recevoir quoi que ce soit page fermée, en arrière-plan ou écran verrouillé ; aucune notification.
- La vibration des alertes : Safari sur iPhone ne permet pas aux pages web de vibrer.
- Une réponse garantie en moins de cinq secondes : le trajet est iPhone › réseau cellulaire ›
  Tailscale (parfois par un serveur relais de Tailscale quand la liaison directe échoue) › ordinateur ›
  parfois le moteur VELA › retour.

## 6. Pourquoi l'écran doit rester allumé sur l'iPhone

iOS suspend une page web quelques secondes après qu'elle quitte l'écran (autre application, écran
verrouillé). Concrètement :
- la liaison en direct avec l'ordinateur (WebSocket) est coupée : **les alertes sonores, les
  sous-titres, les rappels et les messages de vision partagée n'arrivent plus** ;
- la voix du téléphone s'interrompt, et une réponse arrivée pendant ce temps ne sera lue qu'au retour ;
- il n'existe pas de notification pour prendre le relais : les notifications web sur iPhone exigent
  un service d'envoi côté VELA qui **n'est pas construit**.

Au retour à l'écran, la page se reconnecte d'elle-même et vérifie les brouillons en attente. D'où le
réglage « Garder l'écran allumé » (verrou d'écran du navigateur). Il coûte de la batterie. S'il est
refusé par le téléphone, la page le dit : réglez alors Réglages › Luminosité et affichage ›
Verrouillage automatique sur « Jamais » pendant l'usage.

## 7. Vérifier que tout marche vraiment (trois essais)

1. **À la maison, en WiFi** : ouvrez l'adresse ; le cadenas apparaît dans Safari ; le mot de passe
   est demandé ; la pastille dit « Connectée au PC ».
2. **WiFi coupé** (données cellulaires seulement) : rouvrez la page. Si la pastille reste verte, le
   trajet par Internet fonctionne sans port ouvert. C'est le seul essai qui prouve le mode dehors.
3. **Parlez** : « Quelle heure est-il ? ». La réponse doit sortir dans les lunettes, avec son délai
   mesuré affiché sous la bulle.

## 8. Dépannage

| La page affiche | Cause probable | Quoi faire |
|---|---|---|
| « Hors ligne » | ordinateur éteint ou en veille, IRIS fermée, pas d'Internet, Tailscale désactivé sur l'iPhone | vérifier dans cet ordre ; « Réessayer » |
| « Voix indisponible — écrivez » | micro ou reconnaissance refusés ; adresse en `http://` ; iOS qui ne propose pas la reconnaissance dans une page posée sur l'écran d'accueil (non vérifié) | autoriser dans Réglages ; utiliser l'adresse `https://` ; essayer la même adresse dans Safari |
| « Session expirée » | 30 jours passés, ou mot de passe changé (révoque tout) | entrer le mot de passe |
| « IRIS est verrouillée » | verrouillage sur place ou à distance | mot de passe du propriétaire, sur l'écran affiché |
| « Liaison en direct coupée » | le tunnel a fermé le WebSocket | rien : nouvel essai automatique ; les demandes marchent encore |
| Pas de son dans les lunettes | sortie audio restée sur l'iPhone | Centre de contrôle › AirPlay › lunettes |

## 9. Confidentialité, dit franchement

- **La dictée** utilise la reconnaissance vocale intégrée à l'iPhone : selon les réglages d'iOS, vos
  phrases peuvent être envoyées aux serveurs d'Apple pour être reconnues. La page le dit (sans nommer
  de fournisseur). Pour l'éviter, écrivez.
- **Les photos** sont réduites sur le téléphone, envoyées à votre ordinateur, et décrites localement
  quand le mode le permet (lecture, couleur, affichage), sinon par le moteur VELA **seulement avec
  votre consentement** « Images » (Confidentialité, sur l'ordinateur). IRIS ne garde pas la photo.
- **Tailscale** chiffre le trajet entre l'iPhone et l'ordinateur ; il voit quels appareils se
  parlent, pas ce qu'ils se disent. Le nom de la machine (`bureau.tail1234.ts.net`) figure dans les
  registres publics de certificats.
- **Un iPhone perdu** garde sa session 30 jours : retirez-le dans la console Tailscale et changez le
  mot de passe d'IRIS (cela déconnecte tous les appareils), ou verrouillez IRIS à distance.

## 10. Ce qui n'a pas été vérifié

Au 2026-09-13, rien de ce guide n'a été essayé sur un vrai iPhone avec les vraies lunettes. Prouvé
seulement par tests automatiques et dans un navigateur de bureau simulant un téléphone : la page, la
connexion, les panneaux, les alertes plein écran, le verrouillage, les en-têtes de sécurité. Restent à
constater sur place :
- la dictée Safari dans une page posée sur l'écran d'accueil ;
- le verrou d'écran dans une page posée sur l'écran d'accueil (il a longtemps été ignoré par iOS
  dans ce mode) ;
- le WebSocket à travers `tailscale serve` sur réseau cellulaire ;
- l'agent de service (coquille hors ligne) sur iPhone ;
- le choix du micro des lunettes comme entrée par iOS, et le multipoint Bluetooth.
