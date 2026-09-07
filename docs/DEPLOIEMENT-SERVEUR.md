# Déployer le relais VELA — donner un cerveau à un client installé

**Écrit le 6 septembre 2026.** Ce document explique comment un inconnu qui installe IRIS peut avoir
une IA **sans coller sa propre clé** — la différence entre « ça marche chez Miguel » et « c'est un
produit ». Pour quelqu'un qui n'est pas administrateur système.

---

## Le problème que ça résout

Aujourd'hui, IRIS répond grâce à la clé personnelle de Miguel, dans son trousseau Windows. Sur la
machine d'un client, il n'y a pas cette clé : IRIS dit « Aucune IA n'est prête ».

Le **relais** est le serveur qui règle ça. Il tourne quelque part (l'ordinateur de Miguel, l'ordi B,
un hébergeur), il porte **une seule clé** — celle de VELA — et il sert l'IA à toutes les IRIS
installées. Le client ne colle rien. Son application se contente de connaître **l'adresse** du
relais.

## Ce que le relais sert, et à qui — l'économie

Décision de Miguel : **Claude aux payants, gratuit aux gratuits.** Chaque abonnement finance son
propre cerveau, et c'est ce qui rend l'affaire viable.

| Forfait | Cerveau par défaut | Ce que ça coûte à VELA |
|---|---|---|
| Gratuit | un modèle gratuit d'OpenRouter | **0 $** |
| Pro | Claude Sonnet 5 | facturé à la clé de VELA |
| Premium | Claude Sonnet 5 | facturé |
| Entreprise | Claude Opus 5 (le plus puissant) | facturé |

Un compte gratuit **ne peut jamais** atteindre Claude, même en le demandant : sa facture serait à la
charge de VELA. C'est vérifié par des tests (`serveur/test_relais.py`).

Trois filets protègent la carte de VELA, tous réglables : un plafond de jetons par abonné, un plafond
global tous abonnés confondus, et un plafond de caractères pour la voix. **Ce sont des filets, pas
des prévisions** — à ajuster sur la vraie facture dès les premiers clients.

---

## Le déploiement en trois commandes

Depuis le dossier du projet, dans PowerShell.

```
.\scripts\deployer-serveur.ps1 -Telecharger     # la première fois : récupère cloudflared
.\scripts\deployer-serveur.ps1                  # met le relais en service + ouvre le tunnel
.\scripts\deployer-serveur.ps1 -Etat            # où en est-on ?
```

Le script :
1. met le relais en **service permanent** (via `installer-relais.ps1`, qui gère les secrets et
   redémarre après une coupure de courant) ;
2. l'expose sur Internet par un **tunnel Cloudflare** — une connexion *sortante*, **aucun port du
   routeur n'est ouvert** ;
3. vérifie que le relais répond **à travers Internet**, et affiche l'adresse à mettre dans IRIS.

---

## Les deux tunnels, et pourquoi le choix compte

**Rapide (par défaut) — pour essayer ce week-end.** Aucun compte, aucun domaine. Une adresse HTTPS
en trente secondes, du genre `https://quelquechose.trycloudflare.com`. **Mais elle change à chaque
redémarrage du tunnel.** Parfaite pour se prouver que tout marche de bout en bout ; **inutilisable**
comme adresse figée dans une application livrée à des clients — le jour où le tunnel redémarre, tous
les clients perdent le contact.

**Nommé — pour un vrai produit.** Une adresse **stable** (`https://relais.tondomaine.com`) qui
survit aux redémarrages.

```
.\scripts\deployer-serveur.ps1 -Domaine tondomaine.com -Jeton <ton-jeton-cloudflare>
```

Il faut pour cela **un nom de domaine** et **un compte Cloudflare** (gratuit). Ce sont les deux
seules choses que le script ne peut pas fabriquer à ta place.

---

## Deux façons de servir Claude, selon la clé donnée

Le relais a besoin d'**au moins une** clé d'IA. Le choix décide d'où vient Claude et qui paie :

| Clé fournie | Ce que le relais sert | Qui paie Claude |
|---|---|---|
| **Anthropic** (`sk-ant-…`) | Claude **en direct** chez Anthropic (préfixe `anthropic/` retiré) | le compte Anthropic (celui que Miguel a rechargé) |
| **OpenRouter** (`sk-or-v1-…`) | les modèles gratuits **et** Claude par revente | le compte OpenRouter |
| **les deux** | Claude part chez Anthropic, le gratuit chez OpenRouter | chacun son compte |

**En test, donne la clé Anthropic seule** : Claude tourne, et tu ne paies que le compte que tu as
déjà rechargé. Le forfait gratuit ne pourra pas être servi (pas de clé OpenRouter) — sans
importance pour un essai où l'on teste un client payant. Prouvé le 6 septembre : un client premium
a reçu Claude Sonnet à travers le relais, sans coller aucune clé, servi directement par Anthropic.

## Ce que toi seul peux fournir

1. **Une clé d'IA** (au moins une). Le relais la demande au premier lancement (`installer-relais.ps1`)
   et la range dans `serveur/.env`, jamais affichée. Pour du test avec Claude : ta clé Anthropic.
   Pour le forfait gratuit et la vente : ta clé OpenRouter. **Sans aucune des deux, le relais répond
   503 à tout le monde.**
2. **La clé ElevenLabs**, si la voix des forfaits doit marcher.
3. **Un domaine + un compte Cloudflare**, pour l'adresse stable (le mode nommé).
4. **Le choix de la machine.** Pour l'entrevue, ton portable suffit. Pour de vrais clients qui
   paient, il faut une machine qui ne s'éteint jamais — l'ordinateur B, ou un hébergeur. Une machine
   résidentielle tient pour commencer ; au-delà de quelques dizaines de clients actifs, il faudra un
   hébergeur (IP fixe, redémarrages, montée en charge).

## Après le déploiement

Sur une machine cliente, mettre l'adresse publique dans **Réglages › Moteurs IA** (le champ
`relay_server`). L'IRIS installée pointe déjà par défaut sur le moteur « VELA » : dès qu'elle a la
bonne adresse et son jeton d'appareil (obtenu automatiquement au premier contact), le cerveau vient
de VELA, réglé selon l'abonnement — sans une seule clé à coller côté client.

## Vérifier que le bon modèle part

Avant d'ouvrir à des clients, lancer une fois `serveur/verifier_modeles.py` : il confronte chaque
identifiant de modèle à la liste réelle d'OpenRouter et refuse un modèle fantôme (il en a déjà
attrapé un le 6 septembre). OpenRouter renomme et retire des modèles sans prévenir.

```
serveur\.venv\Scripts\python serveur\verifier_modeles.py
```

---

## Ce qui reste, honnêtement

- **L'adresse stable exige un domaine.** Le mode rapide dépanne, il ne remplace pas un domaine.
- **Le serveur de licences** (activation automatique après paiement) est un second service, non
  couvert ici : tant qu'il n'est pas déployé, le relais s'appuie sur `serveur/donnees/abonnes.json`,
  édité à la main, pour savoir qui est abonné. Suffisant pour une poignée de clients, pas au-delà.
- **La clé personnelle de Miguel reste le cerveau de SA machine** (le moteur « Claude » en direct) ;
  le relais, lui, sert les autres. Les deux peuvent coexister.
