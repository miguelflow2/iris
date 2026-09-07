# Plan de construction — l'app iPhone IRIS, du réalisable au reste

Écrit le 2026-09-06. À lire après `REALITE-IOS.md` et `ARCHITECTURE.md`. Ce document dit **par quoi
commencer, dans quel ordre, avec quel matériel et quel budget** — et, tout aussi important, **ce
qui doit rester une page web (PWA) en attendant** plutôt que d'attendre l'app native.

---

## Le préalable qu'on ne contourne pas : on ne compile pas iOS depuis Windows

À dire franchement, avant tout budget de temps : **une application iPhone se compile avec Xcode, et
Xcode n'existe que sur macOS.** Il n'y a pas de version Windows, et les montages « iOS depuis
Windows » (machines virtuelles, services de compilation en ligne) sont fragiles, contre les
conditions d'Apple, et inutilisables pour signer/tester sur un vrai iPhone au quotidien.

La machine actuelle de Miguel est un **Windows 10**. Conséquence nette : **la construction de l'app
native ne peut pas commencer sur cette machine.** Il faut l'un de :

- un **Mac** (même un Mac mini d'entrée de gamme, ou un Mac d'occasion récent) ;
- à défaut, un **Mac loué à l'heure dans le nuage** (services de « Mac cloud ») — dépannage
  acceptable pour apprendre, pénible pour un développement suivi.

Tant que ce Mac n'existe pas, **tout le travail « app native » est bloqué au niveau outillage** —
pas au niveau des idées. D'où la stratégie : **avancer d'abord sur ce qui ne demande pas de Mac**
(la PWA, le backend, le pont), et n'engager le Mac que quand l'app native apporte vraiment quelque
chose que la page web ne peut pas.

---

## Ce qu'il faut réunir (matériel, comptes, argent)

| Quoi | Pourquoi | Coût | Bloquant pour… |
|---|---|---|---|
| **Un Mac avec Xcode** | Seul moyen de compiler/signer une app iOS | Mac mini neuf ~ 600 $ ; d'occasion moins ; « Mac cloud » ~ 1 $/h | Tout le natif |
| **Compte Apple Developer** | Signer, tester sur un vrai iPhone, TestFlight, publier | **99 $ US/an** | Installer sur l'iPhone, entitlements |
| **L'iPhone de Miguel** | Cible de test | déjà là | — |
| **Tailscale** | Tunnel téléphone ↔ PC (déjà documenté) | 0 $ (usage perso) | Le pont depuis l'extérieur |
| **(Plus tard) Numéro VoIP + opérateur Internet** | Vrai numéro IRIS pour CallKit/appels menés | à la minute + abonnement | Points 2-3 et « appel mené » |

**Note sur le compte à 99 $/an.** Il n'est **pas** nécessaire pour construire et tester la PWA :
celle-ci se sert dans un navigateur, sans Apple. Il devient nécessaire dès qu'on veut poser une
**app** sur l'iPhone (même signée par soi, même sans App Store, l'installation sur un appareil
physique passe par ce compte au-delà de la fenêtre de test gratuite de 7 jours).

---

## Les entitlements (droits spéciaux) à demander, et quand

*Un entitlement est une permission inscrite dans l'app qu'Apple doit accorder pour toucher une
capacité sensible.* Pour IRIS, dans l'ordre où ils deviennent utiles :

1. **Aucun, pour la v1.** Voix, pont vers le PC, brouillons SMS/appel, App Shortcut Siri : **rien
   de tout cela n'exige d'entitlement à approuver.** C'est une bonne nouvelle — la v1 ne dépend
   d'aucune validation d'Apple au-delà du compte développeur.
2. **VoIP / PushKit**, le jour où un vrai numéro IRIS existe (appels entrants annoncés par CallKit).
   Se déclare dans le projet ; l'app doit réellement être une app d'appel pour passer la revue si
   un jour on publie.
3. **Family Controls** (Temps d'écran) **seulement si** on veut un jour *surveiller ou limiter*
   des apps — pas les piloter. Mode **développement** : local, sans approbation, utilisable tout de
   suite sur l'iPhone de Miguel. Mode **distribution** : demande à Apple, accordée « au cas par
   cas » (quelques jours à quelques semaines), réservée aux vrais usages de contrôle parental /
   bien-être numérique. **À ne pas demander tant qu'on n'a pas un usage précis** : ce cadre ne
   débloque **pas** le pilotage d'apps (cf. REALITE-IOS.md, point 6).

**Règle simple :** on ne demande un entitlement que lorsqu'une fonction concrète en dépend. La v1
n'en demande aucun.

---

## L'ordre de construction — commencer par ce qui marche

### Phase 0 — Maintenant, sans Mac, sans 99 $ : durcir la PWA

Tout ce qui suit se fait **sur la machine Windows actuelle**, améliore l'usage **tout de suite**, et
ne sera pas perdu quand l'app native arrivera (le backend est partagé).

- **Finir le tunnel Tailscale** (`docs/ACCES-DISTANT.md`) : c'est lui qui débloque `https://` donc
  le micro de Safari, et l'accès depuis l'extérieur. **C'est le vrai déblocage à court terme**, plus
  que n'importe quel code d'app.
- **Boucher le trou connu de `telephonie.py`** : la page `/m` n'écoute pas « chat.confirm », donc
  une confirmation demandée par IRIS est invisible depuis le téléphone (documenté en tête de
  `telephonie.py`). Tant que ce n'est pas réglé, ne pas proposer les outils de téléphonie depuis le
  téléphone.
- **Vérifier la voix sur l'iPhone en `https://`** (test de 30 s de `ACCES-DISTANT.md` §A.5).

À la fin de la phase 0, Miguel **parle déjà à IRIS depuis son iPhone, dehors, et IRIS agit sur le
PC.** C'est l'usage n°1, livré sans écrire une ligne de Swift.

### Phase 1 — L'app native, socle (dès qu'un Mac est là)

Objectif : **la même chose que la PWA, mais en app**, pour gagner les notifications et une voix plus
fiable. Rien de risqué, rien qui dépende d'une approbation Apple.

1. Projet **SwiftUI** vierge, écran unique : bouton parler, fil de conversation, état de connexion.
2. **Client réseau** vers le backend : réutiliser les routes de `PONT-TELEPHONE-PC.md` (jeton,
   session mot de passe, `/api/conversations`, `/api/status`). C'est un portage direct de ce que
   fait déjà le JavaScript de `mobile.py`.
3. **Voix** : reconnaissance (*Speech*) + synthèse (*AVSpeechSynthesizer*).
4. **App Shortcut** « Parle à IRIS » (App Intents) → activation « Dis Siri, parle à IRIS ».
5. Installer sur l'iPhone de Miguel via **TestFlight** (pas d'App Store, pas de revue publique).

### Phase 2 — Les gains propres à l'app

6. **Notifications push (APNs)** : le PC prévient « un texto est prêt », « la veille a trouvé
   quelque chose », sans que l'app soit ouverte. Remplace le sondage à 5 s. *À concevoir ; sans lui
   on garde le sondage, qui marche.*
7. **Brouillons SMS/appel natifs** : `MFMessageComposeViewController` pour le SMS, `tel:` pour
   l'appel ; marquage « envoyé »/« annulé » via les routes existantes. **Geste humain conservé.**

### Phase 3 — Le vrai numéro IRIS (VoIP), plus tard et séparément

8. **CallKit + PushKit** sur un numéro loué : appel entrant sur le numéro IRIS annoncé par l'écran
   d'appel natif, décroché/raccroché par IRIS. **C'est un produit à part** (numéro loué, facturé),
   à ne lancer que quand le reste tourne. Ne pas le vendre comme « IRIS décroche ta ligne » : c'est
   « IRIS répond sur son propre numéro ».

**On ne construit jamais la phase suivante avant que la précédente tourne pour de vrai.** C'est la
même discipline que `docs/ARCHITECTURE-MOBILITE.md` §4 : prouver l'étape 1 avant d'acheter l'étape 2.

---

## Ce qui doit RESTER une PWA en attendant (et peut-être pour toujours)

L'app native n'est utile que pour les quatre gains du tableau d'`ARCHITECTURE.md` (push, SMS natif,
Siri, VoIP). **Pour tout le reste, la PWA est suffisante et sans coût** :

- **parler à IRIS et l'entendre agir sur le PC** — cœur de l'usage, déjà en place ;
- **afficher et ouvrir les brouillons SMS/appel** — déjà en place via `sms:`/`tel:` ;
- **installer sur l'écran d'accueil** — déjà en place (« Sur l'écran d'accueil »).

Donc : **tant que le Mac et le compte développeur ne sont pas engagés, on n'attend pas l'app pour
livrer de la valeur.** La PWA porte l'usage principal aujourd'hui. L'app native est une
amélioration, pas un prérequis — et c'est exactement pour ça qu'elle ne doit pas retarder le reste.

---

## Le rappel honnête, en une ligne chacun

- **On ne compile pas iOS depuis Windows.** Il faut un Mac. C'est le premier obstacle, pas un détail.
- **99 $/an** pour poser une app sur l'iPhone, même sans App Store.
- **La v1 ne demande aucun entitlement à approuver** — elle est faisable dès qu'un Mac est là.
- **La moitié impossible de la demande** (voir l'écran, piloter les apps, décrocher le cellulaire)
  **ne se construit pas** : elle vit sur le PC, ou pas du tout.
- **La PWA existe et suffit à l'essentiel** : elle porte l'usage pendant que le reste se met en place.
