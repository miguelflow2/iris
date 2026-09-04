> **Document d'archive — ne pas utiliser tel quel.**
> Écrit avant la construction d'IRIS, il décrit une intention, pas le produit livré. Deux écarts
> importants : il présente IRIS comme un « orchestrateur d'agents », ce qui est le positionnement
> d'un concurrent direct et ne doit jamais être employé (voir `docs/CONCURRENCE.md`) ; et il
> désigne une plateforme matérielle (K900 / SmartXY) qui n'est pas celle réellement en main
> (modèle `AM01C`, voir `docs/LUNETTES-DIAGNOSTIC.md`).
> Le positionnement en vigueur est celui de `docs/DIFFERENCIATION.md` : confidentialité prouvable,
> puis contrôle de l'ordinateur, puis mémoire de la vie.

# Cahier des charges complet — VELA / IRIS

*Marque : VELA. Produit logiciel (couche 3) : IRIS. Plateforme hardware : K900 (SmartXY). Version consolidée — Septembre 2026.*

---

# Partie 1 — Vision et positionnement de marque

## 1.1 Concept fondateur

Une IA continue qui voit ce que l'utilisateur voit, se souvient de tout, et peut agir sur son ordinateur, son téléphone et le monde autour de lui — construite avec la confiance comme fondation matérielle, pas comme correctif logiciel après coup.

Trois piliers : **Vision** (contexte caméra/micro) — **Mémoire** (second cerveau) — **Action** (contrôle réel, orchestration d'agents, génération de contenu).

Positionnement : *Une IA. Toute ta vie. Rien à taper.*
Slogan : *Vois. Souviens-toi. Fais.*

## 1.2 Positionnement face à Meta (différenciateur central)

Meta a un problème que sa propre technologie ne peut pas résoudre : la caméra elle-même est perçue comme la menace. Des régulateurs (CNIL en France, DPA allemande/néerlandaise/irlandaise) ont jugé que la LED des Ray-Ban Meta ne suffit pas comme mécanisme d'avertissement ; des tribunaux américains ont déjà restreint l'usage de lunettes connectées dans certains lieux ; en interne, Meta a évoqué l'idée d'une version sans caméra.

VELA construit la confiance directement dans le matériel plutôt que d'ajouter une rustine logicielle après coup : voyant physique non désactivable, signal sonore de capture, traitement local par défaut, registre de transparence consultable.

## 1.3 Identité de marque

- **Nom** : VELA
- **Produit logiciel** : IRIS (couche 3 — orchestration IA, mémoire, confidentialité)
- **Logo** : symbole en trait unique (comète/brushstroke) qui se courbe en un anneau volontairement laissé ouvert — symbolise la continuité (vision → mémoire → action) et l'ouverture/transparence (jamais complètement fermé, à l'opposé d'un système opaque)
- **Couleur** *(périmé — identité refaite le 2026-09-04)* : la marque est désormais une **voile**, palette encre `#1B140E`, crème `#F8F0E7`, terracotta `#B36B3B`. Source : `renderer/src/components/Voile.tsx`.
- **Règle de style** : pas de dégradé, pas d'effet "IA générique" (pas de circuits, pas de neurones, pas de paillettes)

---

# Partie 2 — Architecture produit générale (3 couches)

| Couche | Contenu | Rôle |
|---|---|---|
| **1 — Hardware** | K900 (SmartXY) : caméra Sony 13MP + EIS, micros, HP oreille ouverte, Bluetooth + WiFi, contrôle app, sans écran AR | Support physique, remplaçable sans perdre la valeur du produit |
| **2 — Firmware OEM** | Modifications bas niveau impossibles en logiciel seul : voyant physique câblé, déclic sonore non désactivable, bascule confidentielle physique | Négocié directement avec SmartXY, conditionne l'argument de confiance le plus fort |
| **3 — Logiciel (IRIS)** | Orchestration IA multi-agents, mémoire, confidentialité, intégrations, apps mobile/desktop | **Le vrai produit** — ce que VELA vend réellement |

La couche 3 est conçue pour être portable : si le fournisseur hardware change un jour, IRIS et toute la valeur logicielle/marque survivent.

---

# Partie 3 — Fonctionnalités détaillées par domaine

## A. Confiance et confidentialité (différenciateur face à Meta)

| Fonctionnalité | Couche | Description | Faisabilité |
|---|---|---|---|
| Voyant physique non désactivable | Firmware/Hardware | LED câblée directement à l'alimentation du capteur caméra, pas pilotée par un registre logiciel | À négocier en OEM — modification du circuit d'alimentation ; fallback logiciel en MVP |
| Signal sonore de capture | Firmware | Déclic audible non désactivable à chaque photo/vidéo | Faisable en firmware, à spécifier dans la RFQ OEM |
| Traitement local par défaut | Logiciel | Rien n'est envoyé au cloud sans action explicite ; si agent externe connecté, envoi sur consentement par type de donnée | Développement logiciel pur |
| Floutage de visages en temps réel | Logiciel | Détection on-device, floutage avant tout stockage sauf consentement actif | Modèle léger embarqué, à valider selon le chipset réel du K900 |
| Registre de transparence | Logiciel | Journal horodaté et exportable de toutes les captures effectuées | Développement logiciel pur, stockage local chiffré |
| Mode confidentiel à bascule physique | Hardware/Firmware | Interrupteur/geste coupant matériellement micro/caméra | À négocier en OEM |

## B. Orchestration IA — connecter n'importe quel agent

| Fonctionnalité | Description | Faisabilité |
|---|---|---|
| Connecteur universel d'agents | Plugins/API vers Claude, GPT, Gemini, agents perso selon les comptes de l'utilisateur | Cœur du produit — priorité #1 |
| Sélecteur automatique d'agent | Route la demande vers le meilleur agent, reformate le prompt dans son format propre | Logique de routage + prompt engineering par agent |
| Mémoire partagée entre agents | Contexte de la journée accessible à tous les agents connectés, pas cloisonné par app | Base de données contextuelle centrale + résumé automatique |
| Mode tâche asynchrone | Lance une tâche longue (build, recherche, génération), notifie par audio à la fin | Gestion de tâches en arrière-plan |

## C. Second cerveau / mémoire augmentée

| Fonctionnalité | Description | Faisabilité |
|---|---|---|
| Capture contextuelle audio-first | Audio continu (8-10h) + vidéo ponctuelle à la demande (55 min max) — pas de vidéo continue | Design imposé par la contrainte batterie |
| Recherche dans les souvenirs | Recherche sémantique dans l'historique capturé | Index vectoriel local ou cloud selon le mode de confidentialité |
| Résumé de journée | Synthèse des décisions, promesses, chiffres mentionnés | Traitement en fin de journée, léger |

## D. Copilote visuel du quotidien

| Fonctionnalité | Description | Faisabilité |
|---|---|---|
| Guidage visuel en temps réel | Identification d'objet/tâche, guidage vocal étape par étape (pas d'écran) | Modèle de vision + agent capable de raisonnement visuel |
| Reconnaissance d'objets/texte | Traduction, identification de produits, lecture de texte à voix haute | Standard sur la plupart des plateformes caméra IA — bas risque |

## E. Coach de concentration / productivité

| Fonctionnalité | Description | Faisabilité |
|---|---|---|
| Détection de distraction | Alerte douce si déviation d'une tâche déclarée | Nécessite un accès sensible au téléphone/ordinateur — consentement explicite requis |
| Rappels contextuels | Déclenchés par lieu/moment plutôt que par heure fixe | Géolocalisation + logique de déclenchement |

## F. Contrôle ordinateur et téléphone

| Fonctionnalité | Description | Faisabilité |
|---|---|---|
| Contrôle vocal de l'ordinateur | Navigation fichiers, changement d'application, commandes système | Déjà validé dans le prototype JARVIS existant |
| Contrôle vocal du téléphone | Actions via API d'accessibilité | Android complet, iOS plus limité (restrictions Apple) |
| Continuité multi-appareil | Commencer une tâche via les lunettes, continuer sur l'ordinateur | Synchronisation d'état entre app desktop et lunettes |

## G. Création de contenu

| Fonctionnalité | Description | Faisabilité |
|---|---|---|
| Capture POV + montage automatique | Enregistrement à la première personne, montage assisté par IA pour réseaux sociaux | Fonctionnalité déjà présente chez plusieurs concurrents — bas risque |

## H. Personnalisation

| Fonctionnalité | Description | Faisabilité |
|---|---|---|
| Nom d'activation personnalisable | Mot de réveil choisi par l'utilisateur, pas imposé | Déjà prototypé dans JARVIS, faible risque |
| Retour vocal développeur | État d'un agent, résultat de test, branche git — via synthèse vocale | Cohérent avec une plateforme sans écran |

---

# Partie 4 — IRIS : capacités, limites et pistes d'amélioration

## 4.1 Ce qu'IRIS peut faire

Voir le détail complet des capacités en Partie 3 (sections A à H) — IRIS est la couche qui exécute l'ensemble de ces fonctionnalités. En résumé, IRIS orchestre plusieurs agents IA externes, maintient une mémoire contextuelle partagée, contrôle l'ordinateur et le téléphone à la voix, agit comme copilote visuel et coach de concentration, et applique une politique de confidentialité "local par défaut" à toutes les données capturées.

## 4.2 Points de limite honnêtes

| Limite | Impact concret |
|---|---|
| Pas d'écran (K900) | Tout retour d'info passe par la voix — aucun aperçu visuel de ce que capte la caméra |
| 55 min de vidéo continue max | Pas de "mémoire visuelle" permanente — seulement audio en continu + vidéo ponctuelle |
| Contrôle iOS limité | Fonctionnalité de second rang côté iPhone au lancement, à cause des restrictions Apple |
| Chipset et capacité on-device inconnus | Le floutage de visages et la transcription locale dépendent d'un chipset assez puissant — non confirmé pour le K900 |
| Latence agent externe non mesurée | L'expérience "copilote temps réel" dépend d'un facteur non encore testé sur échantillon |
| Voyant physique encore à négocier | En MVP, l'indicateur n'est que logiciel — donc théoriquement désactivable, ce qui affaiblit temporairement l'argument de confidentialité vérifiable |
| Dépendance à des agents tiers | La qualité des réponses dépend de la disponibilité et des limites de Claude/GPT/Gemini, pas seulement d'IRIS |
| Détection de distraction sensible | Nécessite un accès profond à l'état des appareils — risque de perception intrusive si le consentement n'est pas clair |
| Pas de mode 100% hors-ligne | La recherche sémantique et l'orchestration multi-agents dépendent largement d'un accès réseau |

## 4.3 Pistes d'amélioration

- Mode dégradé hors-ligne clairement défini (ce qu'IRIS peut faire sans réseau vs ce qui nécessite le cloud)
- Score de confiance affiché par capture dans le registre de transparence (locale vs envoyée à un agent externe)
- Personnalisation du niveau de rétention de la mémoire (24h / 7 jours / illimité)
- Correction vocale contextuelle rapide en cas de mauvaise interprétation d'une commande
- Alertes de latence honnêtes ("Claude réfléchit encore") plutôt qu'un silence ambigu
- Export/portabilité complète de la mémoire dans un format standard, pour éviter l'enfermement propriétaire

---

# Partie 5 — Applications compagnon

## 5.1 Application mobile

**Rôle** : pont entre les lunettes et le téléphone, point de contrôle du téléphone via les API d'accessibilité.

- Appairage Bluetooth/WiFi avec le K900, gestion de la batterie et des mises à jour firmware (OTA)
- Sélection et connexion des comptes d'agents IA (Claude, GPT, Gemini, agent perso)
- Configuration du mot d'activation personnalisé
- Consultation et recherche dans la mémoire/second cerveau
- Registre de transparence consultable et exportable
- Réglages de confidentialité : bascule local/cloud, consentement par type de donnée, durée de rétention
- Contrôle du téléphone à la voix (Android complet, iOS restreint)
- Notifications des tâches asynchrones lancées depuis les lunettes

## 5.2 Application desktop (Windows/Mac/Linux)

**Rôle** : extension du contrôle vocal sur l'ordinateur, continuité avec les lunettes — basée sur le prototype JARVIS existant.

- Contrôle vocal complet : fichiers, applications, commandes système
- Continuité multi-appareil : reprendre à l'écran une tâche commencée à la voix
- Retour vocal développeur : état d'un agent, résultat de tests, branche git
- Interface de gestion des agents connectés
- Journal des tâches asynchrones en cours et terminées
- Paramètres avancés de confidentialité et de stockage local (chiffrement, emplacement des données)

---

# Partie 6 — Architecture technique complète d'IRIS

*Cette section détaille comment IRIS est construit techniquement — les composants, les flux de données, la stack recommandée, la sécurité et le pipeline de déploiement.*

## 6.1 Vue d'ensemble du système

```
[K900 — hardware/firmware]
        │  (Bluetooth LE + WiFi direct)
        ▼
[Client local — App mobile / App desktop]
   ├── Capture audio/vidéo brute
   ├── Détection du mot d'activation (on-device)
   ├── Traitement on-device léger (floutage, VAD)
   └── Chiffrement local
        │  (connexion réseau, si non-local)
        ▼
[Backend IRIS — orchestrateur cloud]
   ├── Service d'authentification & consentement
   ├── Routeur d'agents (sélection + formatage de prompt)
   ├── Mémoire contextuelle (base vectorielle + base relationnelle)
   ├── Gestionnaire de tâches asynchrones
   └── Connecteurs d'agents externes (API Claude, GPT, Gemini, agents perso)
        │
        ▼
[Agents IA externes] → réponse → synthèse vocale → retour au client → K900 (audio)
```

## 6.2 Couche client (edge)

- **Firmware K900** : capture audio/vidéo brute, gestion de l'alimentation caméra, transmission au client via Bluetooth LE (contrôle) et WiFi direct (flux de données, plus rapide pour l'audio/vidéo)
- **App mobile / desktop (client local)** :
  - Détection du mot d'activation en local (modèle léger de type keyword-spotting, ne nécessite pas de réseau)
  - Voice Activity Detection (VAD) pour ne transmettre que les segments audio pertinents
  - Floutage de visages on-device si le chipset le permet (modèle type MediaPipe/BlazeFace ou équivalent compact)
  - Chiffrement local des données avant tout envoi (AES-256 au repos, TLS 1.3 en transit)
  - File d'attente locale en cas de perte de connexion (les commandes/captures sont mises en tampon puis synchronisées)

## 6.3 Couche orchestration (backend IRIS)

- **Service d'authentification & consentement** : gère les comptes utilisateurs, les tokens OAuth vers chaque agent externe (Claude, GPT, Gemini), et le registre de consentement par type de donnée (audio, vidéo, localisation, historique)
- **Routeur d'agents** : logique de sélection (règles + classification légère) qui détermine quel agent traiter une requête, puis formate le prompt selon les conventions propres à cet agent (system prompt, structure d'appel API, format de sortie attendu)
- **Mémoire contextuelle** :
  - Base vectorielle (embeddings) pour la recherche sémantique dans l'historique
  - Base relationnelle classique pour les métadonnées structurées (horodatage, type d'événement, agent utilisé, statut de consentement)
  - Politique de rétention configurable par l'utilisateur (Partie 4.3)
- **Gestionnaire de tâches asynchrones** : file de tâches (queue) pour les opérations longues (génération de code, recherche approfondie), avec système de notification push/audio à la complétion
- **Connecteurs d'agents externes** : modules d'intégration individuels par agent (Claude via API Anthropic, GPT via API OpenAI, Gemini via API Google, agents perso via un connecteur générique documenté/SDK ouvert)

## 6.4 Sécurité et confidentialité — architecture technique

- **Chiffrement** : AES-256 au repos (stockage local et cloud), TLS 1.3 en transit pour tout appel réseau
- **Isolation des données par utilisateur** : chaque compte a un espace de stockage cloisonné, aucune donnée partagée entre utilisateurs
- **Consentement granulaire au niveau technique** : chaque type de donnée (audio brut, transcription, image, localisation) a son propre flag de consentement, vérifié avant tout envoi à un agent externe
- **Registre de transparence** : table d'audit immuable (append-only) journalisant chaque capture, chaque envoi à un agent externe, et le résultat — consultable et exportable par l'utilisateur
- **Traitement local par défaut** : toute donnée reste sur l'appareil sauf déclenchement explicite d'un appel à un agent externe nécessitant cette donnée précise
- **Gestion des clés** : clés de chiffrement dérivées d'un secret stocké dans l'enclave sécurisée du téléphone (Secure Enclave iOS / Keystore Android) quand disponible

## 6.5 Infrastructure cloud et scalabilité

- **Architecture** : microservices conteneurisés (ex. Docker/Kubernetes) pour permettre de faire évoluer indépendamment le routeur d'agents, la mémoire contextuelle et le gestionnaire de tâches
- **Base vectorielle** : solution dédiée (ex. Pinecone, Weaviate, ou pgvector si on préfère rester sur PostgreSQL pour limiter le nombre de systèmes)
- **File de messages** : système de queue (ex. Redis Streams ou équivalent léger) pour les tâches asynchrones, afin de découpler la demande et le traitement
- **Stockage objet** : pour les segments audio/vidéo temporaires (ex. S3-compatible), avec politique de purge automatique selon la rétention choisie par l'utilisateur
- **Streaming temps réel** : connexion WebSocket entre le client et le backend pour le flux audio en direct (latence critique pour l'expérience copilote temps réel)

## 6.6 Pipeline de développement et déploiement

- **Firmware K900** : cycle de mise à jour OTA négocié avec SmartXY — permet de pousser les correctifs bas niveau (voyant physique, déclic sonore) sans rappel matériel
- **Apps mobile/desktop** : intégration continue (CI/CD) avec tests automatisés sur les fonctions critiques (détection du mot d'activation, chiffrement, consentement) avant chaque publication
- **Backend** : déploiement progressif (canary/blue-green) pour éviter qu'une mise à jour de l'orchestrateur ne casse le service pour tous les utilisateurs en même temps
- **Environnements** : séparation stricte dev / staging / production, avec données de test synthétiques uniquement en dev (jamais de vraies données utilisateur hors production)

## 6.7 Stack technique recommandée (proposition, à valider techniquement)

| Composant | Technologie proposée |
|---|---|
| App mobile | Kotlin (Android natif pour l'accès complet API d'accessibilité) + Swift (iOS, fonctionnalités réduites) |
| App desktop | Electron ou Tauri (multi-plateforme Windows/Mac/Linux), réutilisation de la logique JARVIS existante |
| Backend orchestrateur | Python (FastAPI) ou Node.js — écosystème riche pour l'intégration d'API IA |
| Base vectorielle | pgvector (PostgreSQL) pour limiter le nombre de systèmes, ou Pinecone si besoin de scalabilité dédiée |
| Base relationnelle | PostgreSQL |
| File de tâches | Redis Streams ou équivalent léger |
| Stockage objet | Solution compatible S3 |
| Authentification | OAuth 2.0 standard pour chaque agent externe, gestion de session via JWT |
| Chiffrement | AES-256 (repos), TLS 1.3 (transit) |
| Modèle on-device (floutage/wake word) | Format léger type TensorFlow Lite ou ONNX, selon ce que permet le chipset K900 confirmé |

*Cette stack est une proposition de départ — à ajuster une fois le chipset exact du K900 et les capacités du SDK confirmés par SmartXY.*

---

# Partie 7 — Spécifications hardware K900

- Caméra Sony 13MP avec stabilisation électronique (EIS)
- Micros (5), haut-parleurs à oreille ouverte
- Bluetooth + WiFi, contrôle par application
- Pas d'écran AR (pas de waveguide)
- Autonomie : 8-10h en usage audio, 55 min en vidéo continue
- LED de confidentialité déjà câblée matériellement en standard sur le K900 (bonne nouvelle confirmée — pas besoin de la négocier en modification OEM)
- À confirmer avec SmartXY : chipset exact, RAM/ROM, capacité de stockage et extensibilité, batterie remplaçable ou non, poids

---

# Partie 8 — Priorisation

## MVP (à valider sur 2-3 échantillons avant tout OEM)
1. Connecteur universel d'agents (B) — cœur du produit
2. Contrôle vocal ordinateur (F) — déjà en grande partie fait (JARVIS)
3. Indicateur logiciel non désactivable — fallback en attendant le voyant physique OEM
4. Traitement local par défaut (A) — avec consentement pour agents externes
5. Nom d'activation personnalisable (H)

## Phase 2 (une fois le MVP validé)
6. Mémoire partagée entre agents (B)
7. Registre de transparence (A)
8. Contrôle vocal téléphone Android (F)
9. Reconnaissance d'objets/texte basique (D)

## Phase 3 (différenciation avancée, après premiers retours clients)
10. Floutage de visages en temps réel (A) — selon chipset confirmé
11. Guidage visuel avancé (D)
12. Coach de concentration (E) — consentement uniquement
13. Capture + montage de contenu (G)
14. Extension du retour vocal développeur (H)

---

# Partie 9 — Ce qu'il faut vérifier avant de commander en volume (tests bloquants)

- SDK K900 : accès bas niveau au flux caméra/audio pour traitement personnalisé (pas seulement les scénarios prédéfinis du fabricant) ?
- Latence réelle capture micro/caméra → réponse agent externe (Claude/GPT) — critique pour le copilote temps réel
- Autonomie réelle mesurée en conditions réelles (usage mixte audio + vidéo ponctuelle)
- Capacité de stockage réelle et extensibilité
- Chipset exact et capacité de traitement on-device (floutage + transcription locale possibles ?)
- Accès bas niveau à l'alimentation de la caméra — possible sans redesign de carte électronique pour le voyant physique ?

---

# Partie 10 — Ce qu'il faut inclure dans la RFQ à SmartXY

- Confirmation de l'accès SDK complet (flux caméra, micro, HP, Bluetooth/WiFi depuis l'app propriétaire) — pas juste l'app de démo
- Faisabilité et coût de la modification firmware bas niveau : voyant physique + déclic sonore non désactivables
- Spécifications complètes manquantes : chipset, RAM/ROM, stockage, autonomie détaillée, batterie remplaçable, poids
- MOQ et prix OEM par palier de volume : 100 / 500 / 1 000 / 5 000 / 10 000, + prix et délai pour 2-5 échantillons
- Latence caméra → traitement mesurable sur échantillon + conditions OTA (firmware custom)
- Conditions OEM/ODM : personnalisation châssis, logo, packaging, firmware custom, OTA

**Stratégie d'achat recommandée** : commander 5-10 modèles concurrents (1-2 exemplaires chacun) → tests comparatifs → choix hardware final → pilote OEM → commande en masse. Ne pas commander 500+ unités avant validation complète du MVP sur échantillons. Le bon fournisseur est celui qui offre le plus de contrôle logiciel (SDK/API ouvert).

---

# Partie 11 — Identité de marque et logo

- Concept de logo retenu : trait unique (comète/brushstroke) qui se courbe en anneau volontairement laissé ouvert
- Contraintes de style : couleur unique, pas de dégradé, pas de double-contour, doit rester lisible à très petite taille (icône d'app, gravure sur branche de lunettes)
- *(périmé)* Le symbole est aujourd'hui la voile, en deux variantes : grand-voile encre sur fond clair, grand-voile crème sur fond sombre. Le foc reste terracotta. Ancien texte : version noire, accent teal, version avec le nom "VELA"
- Prompt Gemini verrouillé disponible pour itérer sur le symbole si besoin d'affiner davantage

---

# Partie 12 — Points ouverts / prochaines étapes

- Décider si on regarde d'autres alternatives hardware (Confident, Audio 01) avant de s'engager sur le K900
- Envoyer la RFQ complète à SmartXY (Partie 10)
- Valider le chipset réel du K900 pour confirmer la faisabilité du floutage on-device et de la transcription locale
- Prototyper le connecteur universel d'agents (priorité #1 du MVP) en s'appuyant sur le prototype interne de connecteur d'agents
- Définir précisément le flux d'onboarding de confidentialité (consentement par type de donnée) avant tout développement de l'app mobile
