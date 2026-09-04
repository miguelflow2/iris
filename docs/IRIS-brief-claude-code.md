> **Document d'archive — ne pas utiliser tel quel.**
> Écrit avant la construction d'IRIS, il décrit une intention, pas le produit livré. Deux écarts
> importants : il présente IRIS comme un « orchestrateur d'agents », ce qui est le positionnement
> d'un concurrent direct et ne doit jamais être employé (voir `docs/CONCURRENCE.md`) ; et il
> désigne une plateforme matérielle (K900 / SmartXY) qui n'est pas celle réellement en main
> (modèle `AM01C`, voir `docs/LUNETTES-DIAGNOSTIC.md`).
> Le positionnement en vigueur est celui de `docs/DIFFERENCIATION.md` : confidentialité prouvable,
> puis contrôle de l'ordinateur, puis mémoire de la vie.

# IRIS — Brief technique pour développement (Claude Code)

*Ce document sert de contexte de référence pour le développement d'IRIS, la couche logicielle de la marque VELA (lunettes intelligentes, plateforme hardware K900/SmartXY). À placer à la racine du repo (ex. `CLAUDE.md` ou `docs/IRIS-ARCHITECTURE.md`) pour donner le contexte complet avant toute session de code.*

---

## 1. Résumé produit (contexte, pas à coder directement)

IRIS est la couche logicielle qui tourne sur une paire de lunettes connectées K900 (caméra, micros, audio, sans écran) et sur des applications compagnon mobile/desktop. Elle orchestre plusieurs agents IA externes (Claude, GPT, Gemini, agents perso), maintient une mémoire contextuelle partagée entre eux, et permet de contrôler un ordinateur et un téléphone à la voix — le tout avec une politique de confidentialité "traitement local par défaut".

Différenciateur de marque : la confiance est construite dans l'architecture elle-même (traitement local, consentement granulaire, registre de transparence), pas ajoutée après coup.

**Contrainte hardware clé à respecter dans toute décision de design** : pas d'écran (retour uniquement vocal), 8-10h d'autonomie audio, 55 min max de vidéo continue (donc jamais de flux vidéo permanent, seulement des captures ponctuelles).

---

## 2. Objectifs et périmètre du MVP

### Dans le périmètre MVP
1. Connecteur universel d'agents IA (Claude, GPT, Gemini au minimum) avec routage automatique
2. Contrôle vocal de l'ordinateur (réutilisation du prototype JARVIS existant)
3. Indicateur logiciel de capture non désactivable (en attendant le voyant physique OEM)
4. Traitement local par défaut + consentement explicite avant tout envoi à un agent externe
5. Mot d'activation personnalisable par l'utilisateur

### Hors périmètre MVP (Phase 2/3 — ne pas développer maintenant)
- Mémoire partagée complète entre agents (Phase 2)
- Registre de transparence exportable (Phase 2)
- Contrôle vocal du téléphone (Phase 2, Android d'abord)
- Floutage de visages en temps réel (Phase 3 — dépend du chipset K900, non confirmé)
- Guidage visuel avancé, coach de concentration, capture/montage de contenu (Phase 3)

### Non-objectifs explicites
- IRIS n'est PAS un modèle IA propriétaire — c'est un orchestrateur qui appelle des agents externes via API
- IRIS ne fait PAS d'enregistrement vidéo continu (contrainte batterie K900 : 55 min max)
- Pas de mode 100% hors-ligne complet au MVP (l'orchestration dépend du réseau pour appeler les agents externes)

---

## 3. Architecture système

```
[K900 — hardware/firmware]
        │  Bluetooth LE (contrôle) + WiFi direct (flux audio/vidéo)
        ▼
[Client local — App mobile / App desktop]
   ├── Capture audio/vidéo brute
   ├── Détection du mot d'activation (on-device, hors-ligne)
   ├── Voice Activity Detection (VAD)
   ├── Chiffrement local avant tout envoi
   └── File d'attente locale (mode dégradé si perte réseau)
        │  TLS 1.3
        ▼
[Backend IRIS — orchestrateur]
   ├── Service d'authentification & consentement (OAuth par agent)
   ├── Routeur d'agents (sélection + formatage de prompt)
   ├── Mémoire contextuelle (vectorielle + relationnelle)
   ├── Gestionnaire de tâches asynchrones (queue)
   └── Connecteurs d'agents externes (Claude / GPT / Gemini / perso)
        │
        ▼
[Agents IA externes] → réponse → synthèse vocale → client → K900 (audio)
```

### Composants et responsabilités

| Composant | Responsabilité | Où il tourne |
|---|---|---|
| Firmware K900 | Capture brute audio/vidéo, gestion alimentation caméra | Sur les lunettes |
| Wake word detector | Détection du mot d'activation, doit fonctionner hors-ligne | Client (mobile/desktop), on-device |
| VAD | Ne transmettre que les segments audio pertinents | Client, on-device |
| Consent gate | Vérifie le consentement par type de donnée avant tout envoi réseau | Client, avant chaque appel réseau |
| Auth service | Gère les comptes utilisateurs + tokens OAuth vers chaque agent | Backend |
| Agent router | Sélectionne l'agent, formate le prompt selon ses conventions | Backend |
| Memory service | Stocke et indexe le contexte (vectoriel + relationnel) | Backend |
| Task manager | Gère les tâches longues asynchrones + notification à la fin | Backend |
| Agent connectors | Un module par agent externe (Claude, GPT, Gemini, custom) | Backend |
| Transparency log | Journal append-only de toutes les captures et envois | Backend (Phase 2) |

---

## 4. Stack technique (décisions de départ)

| Composant | Choix | Justification |
|---|---|---|
| App mobile | Kotlin (Android natif) + Swift (iOS) | Accès complet aux API d'accessibilité côté Android ; iOS aura des fonctionnalités réduites (restrictions Apple documentées) |
| App desktop | Electron ou Tauri | Multi-plateforme Win/Mac/Linux, réutilisation de la logique JARVIS existante |
| Backend orchestrateur | Python (FastAPI) | Écosystème riche pour l'intégration d'API IA (SDK Anthropic/OpenAI/Google officiels en Python) |
| Base vectorielle | pgvector (extension PostgreSQL) | Limite le nombre de systèmes à opérer au MVP ; migrable vers Pinecone/Weaviate si besoin de scalabilité dédiée plus tard |
| Base relationnelle | PostgreSQL | Métadonnées structurées (horodatage, type d'événement, agent utilisé, statut de consentement) |
| File de tâches | Redis Streams | Léger, suffisant pour le volume attendu au MVP |
| Stockage objet | Compatible S3 (ex. AWS S3, Cloudflare R2) | Segments audio/vidéo temporaires, purge automatique selon rétention |
| Streaming temps réel | WebSocket | Flux audio client ↔ backend, latence critique |
| Authentification | OAuth 2.0 par agent, sessions via JWT | Standard, évite de stocker des identifiants en clair |
| Chiffrement | AES-256 (repos) / TLS 1.3 (transit) | Minimum requis pour la promesse de confidentialité de la marque |
| Modèle wake word / floutage on-device | TensorFlow Lite ou ONNX Runtime Mobile | Format léger compatible mobile — **à valider selon le chipset K900 réel, non confirmé à ce jour** |

**⚠️ Point bloquant connu** : le chipset exact du K900 n'est pas confirmé. Toute fonctionnalité on-device (wake word local, floutage, transcription locale) doit être développée avec un fallback cloud tant que la capacité de calcul embarquée n'est pas validée sur échantillon réel.

---

## 5. Structure de repo proposée

```
iris/
├── apps/
│   ├── mobile/           # App Android (Kotlin) + iOS (Swift)
│   └── desktop/          # App Electron/Tauri
├── backend/
│   ├── auth/             # Service d'authentification & consentement
│   ├── router/           # Routeur d'agents
│   ├── memory/           # Service de mémoire contextuelle
│   ├── tasks/            # Gestionnaire de tâches asynchrones
│   └── connectors/       # Un module par agent externe
│       ├── claude/
│       ├── gpt/
│       ├── gemini/
│       └── custom/
├── shared/
│   ├── models/           # Schémas de données partagés (Pydantic/TypeScript)
│   └── proto/            # Contrats API (OpenAPI/WebSocket)
├── firmware-bridge/       # Couche d'intégration avec le SDK K900
└── docs/
    └── IRIS-ARCHITECTURE.md   # ce document
```

---

## 6. Modèles de données (schéma de départ)

### `users`
- `id`, `email`, `created_at`, `retention_policy` (24h / 7j / illimité), `wake_word` (custom)

### `agent_connections`
- `id`, `user_id`, `agent_type` (claude/gpt/gemini/custom), `oauth_token` (chiffré), `is_active`

### `consent_flags`
- `id`, `user_id`, `data_type` (audio_raw / transcript / image / location), `granted` (bool), `updated_at`

### `memory_entries`
- `id`, `user_id`, `timestamp`, `content_text`, `embedding` (vector), `source_agent`, `data_type`, `retained_until`

### `transparency_log` (Phase 2)
- `id`, `user_id`, `timestamp`, `capture_type`, `sent_to_agent` (bool), `agent_type`, `local_only` (bool)

### `tasks`
- `id`, `user_id`, `status` (pending/running/done/failed), `agent_type`, `created_at`, `completed_at`, `result_summary`

---

## 7. Contrats API (esquisse à formaliser en OpenAPI)

### REST
- `POST /auth/connect-agent` — connecter un compte agent (OAuth)
- `GET /consent` / `PATCH /consent` — lire/modifier les flags de consentement
- `POST /memory/search` — recherche sémantique dans l'historique
- `GET /tasks/{id}` — statut d'une tâche asynchrone
- `GET /transparency-log` — journal exportable (Phase 2)

### WebSocket
- `/stream/audio` — flux audio temps réel client → backend → agent → réponse
- Événements : `wake_word_detected`, `agent_selected`, `agent_response_chunk`, `task_started`, `task_completed`

---

## 8. Exigences de sécurité et confidentialité (non négociables)

1. Aucune donnée audio/vidéo brute ne quitte le client sans vérification préalable du flag de consentement correspondant au type de donnée
2. Chiffrement AES-256 au repos pour toute donnée stockée (client ET backend)
3. TLS 1.3 obligatoire pour tout appel réseau
4. Les tokens OAuth des agents externes ne sont jamais exposés côté client — uniquement gérés côté backend
5. Isolation stricte des données par utilisateur (aucune requête cross-utilisateur possible, même en cas de bug applicatif — à valider par tests)
6. Toute purge de données (fin de rétention) doit être vérifiable, pas seulement une suppression logique
7. Les clés de chiffrement côté client doivent être dérivées via l'enclave sécurisée du device quand disponible (Secure Enclave iOS / Android Keystore)

---

## 9. Découpage en tâches de développement (ordre suggéré)

1. Mise en place du backend de base (FastAPI + PostgreSQL + auth OAuth par agent)
2. Connecteur Claude (premier agent, API Anthropic) + routeur minimal (un seul agent au départ)
3. Client desktop : contrôle vocal de l'ordinateur (portage du prototype JARVIS)
4. Ajout des connecteurs GPT et Gemini + logique de sélection automatique d'agent
5. Service de consentement + indicateur logiciel de capture (MVP de l'argument confiance)
6. Client mobile minimal : appairage K900, wake word custom, envoi audio au backend
7. Mémoire contextuelle basique (stockage + recherche simple, sans encore la recherche sémantique avancée)
8. Tests de bout en bout : lunettes → wake word → agent → réponse vocale

---

## 10. Points ouverts à traiter avant/pendant le développement

- Chipset exact du K900 et capacité on-device réelle → conditionne si le wake word et le floutage peuvent tourner localement ou doivent temporairement passer par le cloud
- Accès SDK bas niveau du K900 (flux caméra/audio brut) → à confirmer avec SmartXY avant de coder l'intégration firmware-bridge
- Latence réelle mesurée entre capture et réponse d'un agent externe → critique pour la conception du feedback UX vocal ("Claude réfléchit encore")
- Restrictions iOS sur le contrôle d'accessibilité → prévoir dès le départ une UX dégradée cohérente côté iPhone plutôt qu'un correctif après coup

---

## 11. Comment utiliser ce document avec Claude Code

- Placer ce fichier à la racine du repo sous le nom `CLAUDE.md` (ou le référencer depuis un `CLAUDE.md` existant) pour que le contexte produit et architecture soit chargé automatiquement en début de session
- Pour une tâche de dev précise, référencer la section pertinente (ex. "implémente le connecteur Claude selon la section 3 et le schéma `agent_connections` de la section 6")
- Ne pas développer au-delà du périmètre MVP (section 2) sans decision explicite — les fonctionnalités Phase 2/3 ne doivent pas être codées en premier
