# Joindre IRIS de l'extérieur — et le relais pour les clients

Écrit le 2026-09-04. Se lit sans être administrateur système : chaque terme est expliqué à sa
première apparition.

Il y a **deux besoins ici, et ils n'ont pas la même réponse.** C'est le seul piège de tout ce
document. Chercher un outil unique qui règle les deux mène à une mauvaise décision dans les deux cas.

| Le besoin | La réponse | Ce que ça coûte | Ce que ça expose |
|---|---|---|---|
| **A.** Vous, depuis votre iPhone, voulez parler à VOTRE IRIS restée à la maison | Tailscale + `tailscale serve` | 0 $ | Rien. Aucune adresse publique. |
| **B.** Le relais IA doit répondre à de VRAIS CLIENTS qui paient | Un serveur loué, pas cette maison | ~6 $/mois + un domaine ~18 $/an | Un service public, ce qui est le but |

Dans les deux cas, une règle ne bouge pas : **on n'ouvre jamais un port sur la box.** Un « port
ouvert » veut dire qu'on demande au routeur de laisser entrer les connexions venues d'Internet vers
cet ordinateur. Comme IRIS exécute des commandes et écrit des fichiers, ce serait laisser la porte
de la maison entrouverte en permanence. Toutes les solutions ci-dessous fonctionnent avec une
connexion **sortante** : c'est votre ordinateur qui appelle dehors, jamais l'inverse.

---

# PARTIE A — Votre téléphone, votre IRIS

## A.1 Pourquoi ça ne marche pas aujourd'hui

Quand vous activez l'accès téléphone, IRIS affiche une adresse du genre
`http://192.168.1.42:8765/m`. Les adresses qui commencent par `192.168.` sont des **adresses de
maison** : elles n'ont de sens qu'à l'intérieur de votre WiFi. Depuis la voiture, elles ne désignent
rien du tout — ce n'est pas une panne, c'est ainsi que fonctionne Internet.

Et il y a un second problème, celui-là **déjà présent à la maison** : cette adresse est en `http://`,
pas en `https://`. Safari sur iPhone refuse le microphone à toute page qui n'est pas en `https://`.
Si le bouton « Parler » bascule sur « Voix indisponible — écrivez », c'est cela, et rien d'autre.
La solution ci-dessous répare aussi ce point-là. **Vérifiez-le en trente secondes avant de commencer** :
ouvrez l'adresse actuelle sur l'iPhone, appuyez sur « Parler ». Si la voix est indisponible, vous
savez que le chantier sert autant à la maison qu'à l'extérieur.

## A.2 Ce qu'on installe, exactement

**Tailscale.** Deux morceaux, rien d'autre :

1. un petit logiciel sur le PC, qui s'installe comme un service Windows — c'est-à-dire qu'il démarre
   tout seul avec l'ordinateur et repart tout seul après une coupure de courant ;
2. l'application gratuite Tailscale sur l'iPhone, prise sur l'App Store.

Les deux avec **le même compte**. À partir de là, vos deux appareils se voient exactement comme
s'ils étaient sur le même WiFi, où qu'ils soient. C'est un câble réseau invisible entre vos
appareils à vous, et à personne d'autre.

Ce que Tailscale **n'est pas** : ce n'est pas un « VPN » du genre qu'on achète pour cacher son
adresse ou regarder la télévision d'un autre pays. Ce n'est pas non plus un hébergeur : rien de ce
qui est chez vous ne devient consultable par le public.

Le plan Personal est gratuit (6 utilisateurs, appareils illimités). Aucune carte bancaire.

## A.3 Ce que ça change concrètement

- **L'adresse devient stable et unique.** Au lieu de `192.168.1.42`, un nom du genre
  `bureau.tail1234.ts.net`. **Le même à la maison et sur la route.** Un seul favori sur l'iPhone,
  qui ne meurt plus au prochain redémarrage.
- **L'adresse passe en `https://`.** Tailscale obtient et renouvelle un vrai certificat, gratuitement.
  C'est ce qui **débloque le microphone de Safari**, et ce qui permet d'installer IRIS sur l'écran
  d'accueil de l'iPhone comme une vraie application.
- **La règle de pare-feu devient inutile.** `scripts\autoriser-telephone.ps1` avait ouvert le port
  8765 aux autres appareils du WiFi de la maison. Avec le tunnel, plus besoin : retirez-la
  (`.\scripts\autoriser-telephone.ps1 -Retirer`). Une porte de moins.
- **Le mot de passe et la session ne changent pas.** L'écran de connexion d'IRIS reste exactement le
  même, la session dure toujours 30 jours. Le tunnel remplace le trajet, pas la serrure.

## A.4 Les étapes, dans l'ordre

Comptez trente minutes la première fois, dont vingt d'attente et de téléchargement.

1. **Posez un mot de passe dans IRIS** (Paramètres > Téléphone), si ce n'est pas déjà fait.
   C'est le préalable, pas une formalité : voir A.9.
2. **Activez l'accès téléphone dans IRIS.** C'est ce réglage qui fige le port sur 8765 et conserve
   le jeton d'un démarrage à l'autre. Sans lui, le port change à chaque lancement et le tunnel
   pointerait un jour sur deux dans le vide.
3. **Installez Tailscale.** Ouvrez PowerShell **en administrateur** (menu Démarrer, tapez
   `powershell`, clic droit, « Exécuter en tant qu'administrateur ») :
   ```powershell
   .\scripts\installer-tunnel.ps1 -Installer
   ```
4. **Connectez la machine** : fermez la console, ouvrez-en une nouvelle, tapez `tailscale up`.
   Votre navigateur s'ouvre pour la connexion ou la création du compte. **C'est vous qui choisissez
   ce compte et ce mot de passe** — aucun script ne le fait à votre place.
5. **Installez l'application sur l'iPhone**, même compte, et laissez-la activée.
6. **Dans la console Tailscale** (https://login.tailscale.com/admin/dns) : activez **MagicDNS**,
   puis **HTTPS Certificates**. Deux interrupteurs. Sans le second, pas de `https://`, donc pas de
   microphone : c'est l'étape qu'il ne faut pas sauter.
7. **Publiez IRIS** :
   ```powershell
   .\scripts\installer-tunnel.ps1 -Servir
   ```
   Le script affiche l'adresse finale. Il **refuse** de publier si aucun mot de passe n'est posé,
   ou si le `https` n'est pas actif.

À tout moment, `.\scripts\installer-tunnel.ps1` **sans aucune option** ne modifie rien : il vérifie
les sept points et dit lequel bloque.

## A.5 Comment vérifier que ça marche vraiment

Trois essais, dans cet ordre. Le second est le seul qui prouve quelque chose.

1. **À la maison**, sur l'iPhone en WiFi : ouvrez `https://votre-nom.ts.net/m`. Le cadenas doit
   apparaître dans Safari, et le mot de passe être demandé.
2. **Coupez le WiFi de l'iPhone** (données mobiles seulement, ou sortez dans la rue) et rouvrez la
   même adresse. Si elle répond, c'est gagné : vous êtes passé par Internet sans qu'aucun port ne
   soit ouvert.
3. **Appuyez sur « Parler ».** Si iOS demande l'autorisation du micro, le problème du `http://` est
   réglé. Ensuite : « Partager > Sur l'écran d'accueil » installe IRIS comme une application.

Si le point 2 échoue : vérifiez que l'application Tailscale est bien active sur l'iPhone (elle se
met parfois en veille), puis relancez le script sans option.

## A.6 CE QUE CE TUNNEL N'EXPOSE PAS

C'est la partie qui compte. Après cette installation :

- **Aucun port n'est ouvert sur votre box.** Quelqu'un qui scanne votre adresse IP publique ne
  trouve strictement rien de plus qu'avant. Rien n'a changé côté routeur, et rien n'a été demandé
  au routeur.
- **L'adresse `.ts.net` ne répond à personne d'autre que vous.** Même en la connaissant par cœur,
  un inconnu n'obtient rien : il n'est pas dans votre réseau privé. Ce n'est pas un mot de passe à
  deviner, c'est une porte qui n'existe pas pour lui.
- **Rien n'est publié sur Internet, rien n'est indexable.** Google ne trouvera pas cette page ; les
  robots qui balaient Internet à la recherche de machines mal protégées ne la verront jamais.
- **Tailscale ne voit pas ce que vous dites à IRIS.** Le contenu est chiffré directement entre
  l'iPhone et le PC (WireGuard). L'entreprise sert d'annuaire pour que vos appareils se trouvent ;
  elle ne peut pas lire ce qui passe.
- **Seul le port 8765 est publié, et uniquement vers vos appareils.** Vos dossiers partagés, le
  bureau à distance, vos imprimantes, le reste de la machine : rien de tout cela n'est joignable
  parce que rien de tout cela n'a été demandé.
- **IRIS ne devient pas accessible aux autres appareils du WiFi.** Au contraire : c'est l'occasion
  de retirer la règle de pare-feu qui, elle, l'exposait à tout ce qui se branchait chez vous
  (y compris à un invité, ou à un objet connecté douteux).
- **Ce n'est pas un accès à votre écran.** Personne ne voit ce que vous faites sur l'ordinateur ;
  seule l'interface d'IRIS est atteignable, et seulement après le mot de passe.

## A.7 Ce qu'il expose, en revanche — dit franchement

- **Le nom de votre machine et celui de votre réseau devient public**, sous la forme
  `bureau.tail1234.ts.net`. C'est la contrepartie du certificat `https` : tous les certificats du
  monde sont inscrits dans un registre public consultable. Un nom, rien d'autre — pas votre adresse
  IP, pas l'accès. Si ce nom vous ennuie, il se change dans la console avant de commencer.
- **Votre compte Tailscale devient une clé.** Quelqu'un qui prend ce compte peut ajouter un appareil
  à votre réseau privé. Mettez-y un vrai mot de passe et la double authentification, comme pour
  votre boîte mail.
- **Tous vos appareils Tailscale se voient entre eux.** Si vous ajoutez un jour l'ordinateur d'un
  proche « pour dépanner », il entre dans le même réseau que la machine où vit IRIS. N'ajoutez que
  vos appareils.
- **Le mot de passe d'IRIS devient la vraie serrure.** Un iPhone perdu et déverrouillé garde une
  session ouverte 30 jours. En cas de perte : retirez l'appareil dans la console Tailscale, et
  changez le mot de passe dans IRIS (cela révoque toutes les sessions).

## A.8 Comment tout retirer

Du plus doux au plus radical. Chaque niveau est réversible et prend moins d'une minute.

| Ce que vous voulez | La commande |
|---|---|
| Ne plus publier IRIS, garder le réseau privé | `.\scripts\installer-tunnel.ps1 -Retirer` |
| Débrancher cette machine du réseau privé | `tailscale down` |
| Retirer l'appareil du compte | console > Machines > Remove |
| Désinstaller complètement (administrateur) | `winget uninstall --exact --id Tailscale.Tailscale` |
| Supprimer le compte Tailscale | console > Settings > Delete account |

Rien de tout cela ne touche à IRIS ni à vos données : elles vivent dans `%APPDATA%\IRIS`, que le
tunnel n'a jamais approchées.

## A.9 À corriger dans IRIS avant de sortir de la maison

Trois points connus, indépendants du tunnel. Les deux premiers sont bloquants.

1. **Exiger le mot de passe pour activer l'accès distant.** Aujourd'hui, tant qu'aucun mot de passe
   n'est posé, le seul jeton contenu dans l'adresse permet d'appeler `POST /api/compte`, c'est-à-dire
   de **poser le premier mot de passe**. Un inconnu qui obtiendrait l'adresse pourrait donc vous
   enfermer dehors de votre propre machine. Sur le WiFi de la maison c'était tolérable ; ce ne l'est
   plus dès qu'on parle d'extérieur. Le script `installer-tunnel.ps1` refuse déjà de publier dans ce
   cas, mais la vérification doit aussi exister dans IRIS elle-même.
2. **Cesser d'écrire le jeton dans l'adresse.** `urls_locales` produit encore `/m?token=…`. Le
   module `comptes.py` explique précisément pourquoi on a ajouté un mot de passe : « une adresse se
   retrouve dans l'historique du navigateur, dans une capture d'écran ». Une fois le mot de passe
   posé, l'adresse doit être `…/m` tout court — la page sait déjà demander le mot de passe seule.
3. **Ne plus écouter sur tout le réseau quand le tunnel suffit.** Activer l'accès téléphone fait
   aujourd'hui passer l'écoute de `127.0.0.1` à `0.0.0.0`, c'est-à-dire à toutes les cartes réseau.
   Avec `tailscale serve`, ce n'est plus nécessaire : le tunnel parle à `localhost`. Il faudrait
   pouvoir garder le port fixe et le jeton persistant **sans** ouvrir l'écoute au WiFi.

---

# PARTIE B — Le relais IA, pour de vrais clients

## B.1 Pourquoi ce n'est pas le même problème

Tailscale règle la partie A parce que Miguel n'a pas besoin d'être joignable par le monde : il a
besoin d'être joignable **par lui-même**.

Le relais, c'est l'inverse. Il doit répondre à des gens qui ne vous connaissent pas, sur une adresse
qu'ils n'ont pas choisie, sans rien installer.

**Tailscale ne pourra jamais faire ça**, et ce n'est pas une limite de la version gratuite : pour
joindre votre relais, chaque client devrait installer Tailscale et **rejoindre votre réseau privé** —
celui où se trouve aussi votre ordinateur personnel. Personne n'achètera ça, et personne ne devrait
vous le demander. (Tailscale Funnel publie bien un service sur Internet, mais seulement sur un nom
`*.ts.net`, jamais sur `relais.vela.app`, avec des limites non configurables et un usage prévu pour
« partager un service », pas pour porter un produit payant.)

## B.2 Ce que vaut vraiment cet ordinateur comme serveur commercial

Franchement : il peut le faire, et c'est une mauvaise idée. Non pas pour la raison qu'on entend
d'habitude — « l'adresse IP change » est ici un faux problème, puisqu'avec un tunnel sortant l'IP
publique n'a plus aucune importance. Les vrais motifs sont ailleurs, et ils sont plus sérieux.

- **Les coupures.** Une panne de courant, un redémarrage Windows Update à 3 h du matin, un couvercle
  de portable rabattu, un déménagement : le service que des clients ont payé s'éteint. Sans
  redondance, sans alerte, sans personne pour le voir avant le lendemain matin.
- **La puissance.** Cette machine a deux cœurs. IRIS y limite déjà les bibliothèques de calcul à un
  seul fil d'exécution pour économiser de la mémoire, tout en faisant tourner la reconnaissance
  vocale, la lecture de l'écran et l'index des applications. Le relais serait en concurrence avec le
  produit qu'il alimente : un client qui demande une transcription ralentirait votre propre
  conversation avec IRIS, et réciproquement.
- **Les conditions d'utilisation.** Les conditions de Cloudflare réservent aux offres payantes la
  diffusion de vidéo « ou d'un pourcentage disproportionné d'images, de fichiers audio et d'autres
  contenus non-HTML ». Or la route `/v1/voix/` diffuse précisément de l'audio, en continu, pour
  chaque abonné Pro. À l'échelle d'un essai personne ne le remarque ; à l'échelle d'un produit qui
  marche, c'est un service qu'on peut vous couper sans préavis — au pire moment, celui où vous avez
  enfin des clients.
- **La clé qui dépense de l'argent.** `VELA_OPENROUTER_KEY` coûte réellement à chaque requête. Elle
  vivrait sur la machine personnelle qui sert aussi à naviguer, à essayer des logiciels et à faire
  tourner du code d'agent. Ce n'est pas l'endroit où poser la carte bancaire de l'entreprise.
- **Le contrat Internet.** La plupart des abonnements résidentiels interdisent l'exploitation d'un
  service commercial. Un tunnel le rend invisible ; il ne le rend pas conforme.
- **Le certificat**, en revanche, n'est pas un problème : Cloudflare le fournit et le renouvelle.
  C'est le seul point de cette liste qui se règle tout seul.

## B.3 Le seuil : à partir de quand il faut déménager

**Le seuil est une date, pas un chiffre : le jour où quelqu'un paie.** À partir du premier euro
encaissé, l'extinction de votre portable devient une panne facturable, et éventuellement
remboursable. Avant ce jour, la maison suffit. Après, non.

| Situation | La maison suffit ? | Pourquoi |
|---|---|---|
| Vous seul, vos essais, vos démonstrations | **Oui** | Personne ne perd rien si ça tombe |
| 2 ou 3 testeurs qui vous connaissent et savent que ça peut tomber | **Oui**, adresse jetable | Aucune promesse n'a été faite |
| Le premier client payant | **Non** | Déménagez **avant** d'encaisser, pas après |
| Plus de 3 conversations en même temps | **Non** | Deux cœurs partagés avec IRIS : tout ralentit |
| Le relais diffuse de l'audio à longueur de journée | **Non** | Conditions d'utilisation de Cloudflare |
| Vous n'osez plus redémarrer votre PC | **Non** | Le signal le plus fiable de tous |

Ce dernier signal est le meilleur juge : le jour où vous hésitez à éteindre votre propre ordinateur
parce que quelqu'un pourrait en avoir besoin, c'est que ce n'est plus votre ordinateur.

## B.4 Ce que coûte la bonne solution

- **Un serveur loué : 5 à 7 $ par mois.** N'importe quel hébergeur Python convient (Fly.io, Railway,
  Hetzner). Deux exigences réelles, déjà écrites dans `serveur\README.md` §6 : un disque qui survit
  aux redémarrages, sinon les compteurs de quota repartent de zéro et le quota mensuel ne veut plus
  rien dire ; et `https`, puisque le jeton d'appareil circule dans l'en-tête `Authorization`.
- **Un nom de domaine : 15 à 20 $ par an.** Celui-là est nécessaire de toute façon :
  `backend\iris\config.py` promet `https://relais.vela.app` à chaque installation vendue, et
  **cette adresse n'existe pas aujourd'hui** (elle ne résout pas). C'est la vraie tâche bloquante du
  dossier, bien avant le choix d'un tunnel.

Sept dollars par mois, c'est le prix de ne plus y penser. C'est moins cher qu'un seul remboursement
et qu'une seule soirée à chercher pourquoi le service est tombé.

## B.5 Si vous voulez quand même essayer depuis la maison, pour vingt minutes

C'est légitime pour une démonstration. Téléchargez `cloudflared.exe`, puis une seule commande :

```powershell
cloudflared tunnel --url http://localhost:8100
```

(8100 est le port du relais en local, celui de `serveur\README.md` §4. Ne pointez jamais cette
commande sur le port 8765 : c'est celui d'IRIS, et cela publierait votre ordinateur.)

Vous obtenez immédiatement une adresse `https://…trycloudflare.com` joignable du monde entier, sans
compte, sans domaine, sans port ouvert. Trois choses à savoir avant de vous en servir :

- **l'adresse change à chaque redémarrage** du processus ;
- **le flux continu (SSE) n'est pas supporté** sur ce mode gratuit. Or le relais envoie la réponse de
  l'IA au fur et à mesure : sans flux, on perd exactement ce qui fait qu'IRIS répond en moins de cinq
  secondes, et la voix ne peut plus être diffusée en continu ;
- **il n'y a aucun contrôle d'accès.** Tout le monde peut entrer. Cloudflare écrit noir sur blanc que
  ce mode est destiné aux essais et au développement.

Utilisable pour montrer quelque chose à quelqu'un pendant vingt minutes. Jamais à demeure, et jamais
pour la machine où tourne IRIS.

---

# Ce qui n'a pas été vérifié

Par honnêteté, et pour que personne ne prenne ces points pour acquis :

- **Que la voix échoue effectivement sur l'iPhone en `http://`.** C'est déduit de la règle des
  navigateurs (le microphone exige un contexte sécurisé), pas observé. Le test de A.1 tranche en
  trente secondes.
- **Que le domaine `vela.app` vous appartienne.** Il résout aujourd'hui vers des serveurs Wix et
  répond 404 : il est enregistré par quelqu'un, et rien ne prouve que c'est vous. À trancher avant
  toute décision sur une adresse publique — c'est le seul prérequis payant du dossier.
- **Le détail exact des plans Tailscale au 4 septembre 2026** (6 utilisateurs, appareils illimités,
  d'après des sources secondaires plutôt que la grille officielle).
- **Le comportement des WebSockets à travers un tunnel Cloudflare nommé.** Sans importance
  aujourd'hui — la page téléphone interroge IRIS à intervalles réguliers au lieu d'écouter en
  permanence — mais à revérifier le jour où l'on branchera `/ws` sur le téléphone.
- **Ce que votre contrat Internet autorise réellement.**
