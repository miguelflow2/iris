# IRIS partout — l'architecture pour parler à IRIS depuis n'importe où

Établi le 2026-09-04, à partir de l'objectif énoncé par Miguel : *« je laisse mon ordinateur à la
maison, je sors, je suis dans ma voiture, je dis : Iris, fais telle chose sur mon ordinateur — et
elle le fait. »*

---

## 1. Le problème à régler d'abord : la portée

Les lunettes sont un appareil **Bluetooth**. La portée du Bluetooth est d'environ **dix mètres**.

Cela veut dire une chose simple et incontournable : **les lunettes ne peuvent pas atteindre la
maison depuis la voiture.** Aucun logiciel ne change cela. Ce n'est pas une limite d'IRIS, c'est
une limite de l'onde radio.

Transformer l'ordinateur B en serveur ne règle donc pas la mobilité. Le serveur B résout un autre
problème, réel et utile : il donne aux lunettes un hôte toujours allumé, et il permet d'éteindre ou
de déplacer l'ordinateur A sans rien perdre. Mais tant que les lunettes parlent en Bluetooth, il
faut être **à dix mètres de ce à quoi elles parlent**.

## 2. La seule solution : le téléphone est le pont

Ce qui est toujours sur vous et toujours connecté à Internet, c'est votre téléphone.

```
   VOUS, DEHORS                              CHEZ VOUS
   ┌───────────┐   Bluetooth   ┌──────────┐              ┌─────────────┐
   │ Lunettes  │──── 10 m ────▶│ TÉLÉPHONE│═══Internet══▶│ Serveur B   │
   │ micro/son │               │ (le pont)│              │ toujours ON │
   └───────────┘               └──────────┘              └──────┬──────┘
                                                                │ réseau local
                                                                ▼
                                                         ┌─────────────┐
                                                         │ Ordinateur A│
                                                         │ IRIS exécute│
                                                         └─────────────┘
```

Vous parlez. Les lunettes envoient le son au téléphone, à dix centimètres de votre poche. Le
téléphone l'envoie par Internet au serveur B. B transmet à A, qui exécute et renvoie la réponse par
le même chemin. Vous l'entendez dans les lunettes.

**Il n'y a pas d'autre chemin.** Les lunettes n'ont ni WiFi ni carte SIM : elles ne savent parler
qu'en Bluetooth, à l'appareil le plus proche.

## 3. À quoi sert vraiment l'ordinateur B

Il ne sert pas à porter le Bluetooth. Il sert à être le **point d'entrée fixe et toujours joignable**
de votre installation :

- il a une adresse stable, il ne dort jamais, il ne redémarre pas au milieu d'une demande ;
- il reçoit ce qui vient du téléphone et le distribue ;
- il exécute les veilles, les tâches longues et les rappels même quand A est éteint ;
- il garde la mémoire et le registre au même endroit, quel que soit l'appareil utilisé.

Sur cette machine précise, un point matériel à connaître : sa radio Bluetooth est une **Broadcom
4.0**, ancienne. Pour un serveur qui doit tenir la connexion en permanence, une clé Bluetooth 5 à
une quinzaine de dollars ferait plus de différence que le nouvel ordinateur.

## 4. La feuille de route, du plus rapide au plus long

### Étape 1 — Parler à IRIS depuis le téléphone, chez soi (1 à 2 jours)
Le backend accepte déjà l'option `--host` et protège tout par jeton. Il suffit de l'ouvrir au
réseau local et l'interface s'affiche dans le navigateur du téléphone. Les lunettes se connectent
au téléphone. **Vous testez tout le principe le jour même, sans rien acheter.**

### Étape 2 — Depuis n'importe où (2 à 3 jours)
Un tunnel privé chiffré entre le téléphone et la maison. **Tailscale** est le bon choix : réseau
privé, chiffré de bout en bout, gratuit pour un usage personnel, aucun port ouvert sur Internet.

> **Ne jamais ouvrir de port sur la box.** IRIS peut exécuter des commandes et écrire des fichiers
> sur l'ordinateur. Exposer son interface directement sur Internet reviendrait à laisser la porte
> de la maison ouverte. Un tunnel privé, jamais une redirection de port.

### Étape 3 — Une vraie application téléphone (1 à 2 semaines)
D'abord une application web installable : elle se met sur l'écran d'accueil, garde la session,
reçoit les notifications, et capte le micro. Cela suffit pour l'usage visé et fonctionne sur
Android comme sur iPhone.

### Étape 4 — Android natif (2 à 4 semaines)
Nécessaire seulement pour ce que le navigateur ne peut pas faire : passer un appel, envoyer un SMS,
et écouter le mot d'activation en arrière-plan, écran éteint.

---

## 5. Les trois demandes qui ne sont pas de la mobilité

### Le courriel — faisable, et proche
Le parcours voulu est exactement celui qu'IRIS applique déjà partout : elle rédige, elle vous lit
le texte, vous dites « envoie », elle envoie. La confirmation avant l'envoi n'est pas une
précaution facultative : un courriel parti ne se rattrape pas.

Techniquement : l'interface de programmation de Gmail, avec une autorisation que vous accordez une
fois. **Ce que Miguel doit faire :** créer un projet Google Cloud, activer Gmail, et obtenir les
identifiants. Une heure, gratuit. Ensuite le développement est de deux à trois jours.

### Les appels — possible, mais pas depuis l'ordinateur
Un ordinateur ne passe pas d'appel téléphonique. Deux chemins réels :

1. **Par votre téléphone** (le bon chemin) : l'application Android compose le numéro, l'appel part
   de votre ligne, avec votre numéro. Nécessite l'étape 4.
2. Par un service de téléphonie sur Internet : l'appel partirait d'un numéro inconnu du
   destinataire, et serait facturé à la minute. Mauvaise expérience, à écarter.

### Les messages — même réponse
SMS par l'application Android. Messages internet (WhatsApp, etc.) : leurs conditions d'utilisation
interdisent l'automatisation par un logiciel tiers, et les comptes qui le font se font bloquer.

---

## 6. Sur « la seule limite d'IRIS, c'est qu'elle n'a pas de limite »

Sur les **capacités**, l'ambition est la bonne, et rien de ce qui est demandé ici n'est hors de
portée. C'est du travail, pas de l'impossible.

Sur les **garde-fous**, il faut distinguer. Trois limites resteront, et ce sont elles qui rendent
le produit vendable plutôt que dangereux :

- **elle ne dépense pas votre argent sans votre accord** ;
- **elle n'envoie rien en votre nom sans votre accord** — courriel, message, appel ;
- **elle inscrit ce qu'elle fait dans un registre que vous vérifiez.**

Ce ne sont pas des faiblesses. C'est précisément ce que vous vendez, et c'est ce qui vous distingue
d'un assistant à qui il faut faire confiance sur parole. Un assistant sans aucune limite n'est pas
plus puissant : il est simplement impossible à confier à quelqu'un d'autre.

Tout le reste — agir, chercher, surveiller, se souvenir, décider — n'a pas de plafond.

---

## 7. Ce qu'il faut acheter, et dans quel ordre

| Priorité | Quoi | Pourquoi |
|---|---|---|
| 1 | Rien | L'étape 1 se fait avec ce que vous avez déjà |
| 2 | Clé Bluetooth 5 (~15 $) | Change plus que le nouvel ordinateur pour la stabilité du lien |
| 3 | Un disque, ou du vide | Le disque actuel est saturé ; c'est déjà la cause de plusieurs pannes |
| 4 | L'ordinateur A | Utile, mais il ne débloque pas la mobilité à lui seul |

**Ne transformez pas l'ordinateur B en serveur avant d'avoir validé l'étape 1.** Il vaut mieux
prouver le principe en une journée, avec le matériel actuel, que d'effacer une machine sur un plan
non testé.
