# Architecture de l'app iPhone IRIS — ce qui tourne où

Écrit le 2026-09-06. À lire après `REALITE-IOS.md`, qui établit ce qu'iOS permet. Ce document-ci
décide **comment** monter l'app à partir de ces permissions, et surtout **quoi met-on sur le
téléphone, quoi laisse-t-on sur le PC**. Chaque cadre Apple est expliqué en une phrase à sa
première apparition.

---

## Le principe directeur, en une image

```
   IRIS SUR IPHONE                                    IRIS SUR LE PC (déjà construit)
   ┌────────────────────────┐                         ┌──────────────────────────────┐
   │ App SwiftUI            │   Tailscale (tunnel     │ backend/ (FastAPI)           │
   │  · voix (écoute/parle)│    privé chiffré,       │  · voit l'écran (capture.py) │
   │  · pont vers le PC    │═══ déjà documenté ══════▶│  · pilote les apps (tools.py)│
   │  · SMS/appels bridés  │    docs/ACCES-DISTANT)  │  · mémoire, veilles, courriel│
   │  · CallKit (VoIP)     │                         │  · telephonie.py (brouillons)│
   │  · App Shortcut Siri  │◀══ notifications ═══════│  · /m, /api/*, jeton         │
   └────────────────────────┘                         └──────────────────────────────┘
        LA VOIX ET L'OREILLE                                LE CERVEAU ET LES MAINS
```

**La règle de partage.** Ce que le *sandbox* iOS interdit sur le téléphone (voir l'écran, piloter
les apps) **existe déjà sur le PC**. L'app iPhone ne le refait donc pas : elle **capte la parole,
la lit, et renvoie le travail au PC**. Tout ce qui est « pilotage » descend le tunnel vers la
maison ; seul ce qui est proprement téléphone (SMS, appels, notifications, VoIP) vit sur l'iPhone.

Ce n'est pas un pis-aller : c'est la seule architecture cohérente avec ce qu'iOS autorise, et elle
a l'avantage de **réutiliser presque tout le backend existant**.

---

## Ce qui tourne SUR le téléphone

Une application **SwiftUI** — une phrase : *SwiftUI est le cadre d'interface d'Apple, la façon
moderne d'écrire l'écran d'une app iPhone en Swift.* Elle porte cinq choses, et rien de plus.

1. **La voix (écouter et parler).** Reconnaissance de la parole (*Speech framework* d'Apple, ou
   la reconnaissance déjà utilisée dans la page web) et synthèse vocale (*AVSpeechSynthesizer*)
   pour lire les réponses — donc entendues dans les lunettes, qui sont la sortie audio du
   téléphone. C'est la fonction n°1, celle qui doit marcher en premier.

2. **Le pont vers le PC.** Un client réseau qui parle au backend exactement comme le fait
   aujourd'hui la page `/m` : même jeton, mêmes routes `/api/*`, même session par mot de passe. Voir
   `PONT-TELEPHONE-PC.md`. C'est *le* réutilisable : le protocole existe déjà et il est testé.

3. **Les brouillons SMS / appel (bridés).** L'app affiche les brouillons qu'IRIS a préparés
   (sondage de `/api/telephonie/en_attente`, déjà en place) et propose de les ouvrir : SMS via
   `MFMessageComposeViewController` (*l'écran de rédaction SMS d'Apple, pré-rempli*), appel via un
   lien `tel:`. **L'utilisateur touche Envoyer / Appeler.** Rien ne part seul (cf. REALITE-IOS.md,
   points 4-5).

4. **CallKit, pour les appels VoIP d'IRIS (phase ultérieure).** *CallKit est le cadre qui laisse
   une app de voix-par-Internet afficher l'écran d'appel du système.* Utilisé **uniquement** si/quand
   VELA offre un vrai numéro IRIS (VoIP) : à ce moment, un appel entrant sur ce numéro s'annonce
   avec l'écran d'appel natif, et IRIS peut le décrocher/raccrocher. Ce n'est **pas** le décrochage
   de la ligne cellulaire personnelle (impossible, cf. points 2-3). À ne pas mettre dans la v1.

5. **L'activation vocale par Siri (App Shortcut).** *Un App Shortcut est une phrase qu'une app
   déclare à Siri pour qu'on puisse lancer une de ses actions à la voix.* IRIS publie « **Parle à
   IRIS** » : l'utilisateur dit « **Dis Siri, parle à IRIS** », Siri ouvre l'app IRIS prête à
   écouter. C'est le **substitut** au mot maison « Dis-moi Iris » : l'écoute permanente d'un mot
   d'activation personnalisé en tâche de fond est réservée à Siri (cf. REALITE-IOS.md, point 8).

Ce que l'app **ne porte pas**, volontairement : la vision d'écran, le pilotage d'apps, la mémoire,
les veilles, l'envoi de courriel. Tout cela est déjà sur le PC et n'a aucune raison d'être
réécrit — ni aucun moyen de l'être sur iOS.

---

## Ce qui reste SUR le PC (backend existant, inchangé)

Le backend `backend/iris/` fait déjà tout le travail lourd, et il est **déjà joignable par le
téléphone** :

- **Voir l'écran** (`capture.py`) et **piloter les applications** (`tools.py`, `opencode.py`) — la
  capacité centrale d'IRIS, celle qu'iOS interdit sur le téléphone. Elle vit ici, un point c'est
  tout.
- **La mémoire, les veilles, les rappels, le courriel** (`memory.py`, `watch.py`, `reminders.py`,
  `courriel.py`) : indépendants de l'appareil, ils tournent à la maison.
- **La téléphonie côté préparation** (`telephonie.py`) : IRIS **rédige** le SMS/appel sur le PC et
  dépose un brouillon ; c'est le téléphone qui l'**ouvre**. Cette division est déjà codée et testée.
- **Les routes et la serrure** (`main.py`, `mobile.py`, `routes_communications.py`) : le jeton
  maître, la session par mot de passe, `/api/status`, `/api/conversations`, `/api/telephonie/*`.
  L'app native tape **les mêmes routes** que la page web.

**Le tunnel entre les deux existe déjà sur le papier :** `docs/ACCES-DISTANT.md` (Tailscale) donne
au téléphone une adresse `https://…ts.net` stable, chiffrée de bout en bout, sans ouvrir un seul
port sur la box. L'app native l'emprunte tel quel. Rien à réinventer côté réseau.

---

## Le montage des « morceaux téléphone », un par un

### La voix mains-libres : « Dis Siri, parle à IRIS »

Le mot maison « Dis-moi Iris » écran éteint est **impossible** pour un tiers (point 8). Le chemin
réel :

1. L'app déclare un **App Shortcut** « Parle à IRIS » (App Intents).
2. L'utilisateur dit « **Dis Siri, parle à IRIS** » (dans les lunettes, via le micro du téléphone).
3. Siri ouvre l'app IRIS, déjà en écoute ; la conversation continue dans l'app (voix → PC → voix).

C'est une phrase de plus (« Dis Siri » avant « parle à IRIS »), mais c'est la **seule** activation
mains-libres qu'Apple autorise sans ouvrir l'app à la main. *À vérifier au moment de construire :
le confort exact de l'enchaînement Siri → écoute continue selon la version d'iOS.*

### L'appel entrant annoncé (« Untel vous appelle »)

- **Pour un appel cellulaire (ligne SIM) : impossible** de l'annoncer/décrocher via l'app (point 2).
  On ne le promet pas.
- **Pour un appel VoIP d'IRIS (si/quand VELA a un numéro) :** l'appel arrive par une **notification
  VoIP** (*PushKit*, le canal de notification prioritaire réservé aux apps d'appel), CallKit affiche
  l'écran natif, et IRIS peut présenter/décrocher/raccrocher. Phase ultérieure, pas v1.

### Les notifications (l'appel/le message préparé est prêt)

*Les notifications « push » d'Apple (APNs)* permettent au PC de réveiller l'app : « un texto est
prêt », « une veille a trouvé quelque chose ». Aujourd'hui la page web **sonde** le backend toutes
les 5 secondes (elle ne peut pas recevoir de push fiable en tant que page). **Une app native, elle,
peut recevoir de vraies notifications** — c'est un des gains concrets du passage à l'app : IRIS peut
prévenir sans que l'app soit ouverte. Cela demande un petit relais APNs (le PC envoie à Apple, Apple
pousse au téléphone) — *à concevoir au moment de la construction ; sans lui, on garde le sondage,
qui marche déjà.*

### Les SMS / appels bridés

Inchangé par rapport à la page web, en plus propre : brouillon déposé par le PC → l'app l'affiche →
`MFMessageComposeViewController` (SMS) ou `tel:` (appel) → geste de l'utilisateur → l'app marque
« envoyé »/« annulé » via `/api/telephonie/{id}/envoye|annule` (routes déjà existantes).

---

## Pourquoi une app native plutôt que rester sur la PWA — et ce que ça coûte

La page web installable (PWA) **existe et marche déjà**. Passer à une app native n'a de sens que
pour ce que la page web ne sait pas faire :

| Une app native apporte | La PWA ne peut pas |
|---|---|
| Vraies notifications push (appel/texto prêt) sans app ouverte | Les push web sur iOS sont fragiles et limités |
| SMS via l'écran natif `MFMessageComposeViewController` | Se limite au lien `sms:` (ouvre Messages, sort de l'app) |
| Activation « Dis Siri, parle à IRIS » (App Shortcut) | Aucune intégration Siri |
| CallKit / VoIP (phase ultérieure) | Aucun accès aux appels |
| Micro plus fiable, exécution en fond limitée mais réelle | Reconnaissance vocale capricieuse, page mise en veille |

Le **coût** est réel et il faut le dire (détaillé dans `PLAN-CONSTRUCTION.md`) : un **Mac avec
Xcode** (on ne compile pas une app iOS depuis Windows), un **compte développeur Apple à 99 $/an**,
et le temps d'apprendre Swift. Tant que ce coût n'est pas engagé, **la PWA reste la bonne réponse**
pour tout ce qui est voix + pont vers le PC — c'est-à-dire l'essentiel.

---

## Ce qui est décidé, ce qui reste à vérifier

**Décidé (cohérent avec REALITE-IOS.md) :**
- L'app iPhone est **la voix et l'oreille** ; le pilotage et la vision restent sur le PC.
- Le réseau réutilise **Tailscale** (`docs/ACCES-DISTANT.md`) et les **routes existantes**.
- Les SMS/appels restent **bridés** (geste humain), comme déjà codé dans `telephonie.py`.
- L'activation vocale passe par **« Dis Siri, parle à IRIS »**, pas par un mot maison en fond.

**À vérifier au moment de construire (ne pas prendre pour acquis) :**
- Le confort réel de l'enchaînement Siri → écoute continue selon la version d'iOS.
- La mise en place exacte du relais **APNs** (sinon, le **sondage** actuel suffit pour commencer).
- Les capacités précises de l'« app d'appel par défaut » (iOS 18.2+) — sans compter dessus pour
  décrocher un appel cellulaire, ce qui reste hors de portée.
- Le détail des entitlements VoIP le jour où un vrai numéro IRIS existera.
