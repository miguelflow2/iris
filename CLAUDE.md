# IRIS — application desktop (VELA)

IRIS est la couche logicielle de VELA (lunettes connectées sans écran). Ce dépôt contient **l'application desktop installable** (Windows d'abord, Mac/Linux possibles) : confidentialité prouvable (registre chaîné), mémoire continue, contrôle vocal de l'ordinateur. Ne jamais la présenter comme un « orchestrateur d'agents » : c'est le positionnement d'un concurrent (`docs/DIFFERENCIATION.md`).

Spécifications produit : `docs/IRIS-brief-claude-code.md` et `docs/VELA-IRIS-cahier-des-charges-complet.md` (copies des documents de référence). Périmètre = MVP du brief + interface Claude complète. Ne pas coder les fonctionnalités Phase 2/3 (mémoire partagée avancée, registre exportable complet, contrôle du téléphone, floutage) sans décision explicite.

## Exigences clés (décisions du 2026-09-02)
- **IA de base = OpenRouter** avec des **modèles gratuits** (défaut `minimax/minimax-m3:free`, bascule automatique vers le gratuit suivant si saturé). Claude, GPT, Gemini et un agent local restent des options. Le contrôle du PC passe par l'appel d'outils OpenAI-compatible (`connectors/openai_compat.py`).
- Mot d'activation par défaut : **« Dis-moi Iris »** (personnalisable).
- **Réponse vocale en moins de 5 s** : détection du mot sur résultats partiels Vosk, effort `low` pour la voix, lecture TTS phrase par phrase pendant le streaming, dialogue de suivi sans mot d'activation quand IRIS pose une question.
- IRIS **contrôle l'ordinateur uniquement sur commande** de l'utilisateur, via les outils Claude (`backend/iris/tools.py`). Exemple : « ouvre mon navigateur et mets de la musique » → ouvre le navigateur, demande quelle musique, `play_youtube`.
- Voix : « stop » (et `stop_words`) interrompt la parole d'IRIS (écoute pendant la synthèse, `VoiceListener._wait_speech`) ; « muet » (`mute_words`), bouton, Ctrl+Maj+M ou tray coupent le micro (`muted`, réactivation explicite) ; activation par « Dis-moi Iris », « Dis Iris » ou « Iris ».
- Confirmation demandée seulement pour les **commandes dangereuses** (réglable : toujours / dangereuses / jamais).
- **Voix de sortie = ElevenLabs** (voix française « Mélanie », modèle `eleven_flash_v2_5`, streaming PCM joué dès les premiers octets, phrase par phrase). Clé **uniquement dans un fichier `.env`** (`backend/.env` en dev, `<data_dir>/.env` dans l'app ; `.env.example` fourni), chargée par `config.load_env_files`. Repli automatique sur la voix Windows si clé absente ou quota épuisé (palier gratuit : 10 000 caractères/mois).
- Rien ne quitte l'ordinateur sans **consentement explicite par type de donnée** (`consent.py`). Chiffrement AES-256-GCM au repos, clés API dans le coffre système.

## Architecture
```
electron/main/      process principal : sidecar Python (backend.ts), liaison WS (link.ts),
                    pastille de capture non désactivable (indicator.ts), tray, raccourcis globaux
electron/preload/   pont contextBridge → window.iris
renderer/           React + Vite (vues : Chat, Agents, Mémoire, Tâches, Confidentialité, Paramètres, Onboarding)
backend/iris/       FastAPI local (REST + WebSocket /ws), port libre + jeton de session annoncé sur stdout (IRIS_READY)
  config.py         settings.json (UserSettings)          db.py         SQLite (WAL)
  security/         crypto (AES-256-GCM), secrets (keyring)  consent.py    porte de consentement + journal
  connectors/       openai_compat (OpenRouter = base, GPT, Ollama/LM Studio ; streaming + function calling),
                    claude (SDK Anthropic : streaming, thinking adaptatif, outils, web_search, fallbacks), gemini
  router.py         choix d'agent explicable     chat.py       conversations, streaming, SentenceSpeaker
  tools.py + pc/    outils PC (apps, URL, YouTube, fichiers, commandes, clavier, capture, état système)
  voice/            tts (façade : elevenlabs.py streaming + pyttsx3 en repli), stt (Vosk hors-ligne / Google avec consentement), listener (wake word + alias, VAD,
                    dialogue de suivi, micro sélectionnable = lunettes appairées en casque BT)
  glasses.py        lunettes VELA : scan BLE (Bleak), connexion, notifications GATT, batterie, reconnexion auto
  plans.py          plans d'abonnement (Gratuit/Essentiel/Pro/Ultra) : quotas mensuels, fonctionnalités, modèles inclus, clés HMAC, mode démo
  tasks.py          tâches asynchrones (plan → exécution → vérification → rapport) + annonce vocale
  routines.py       routines vocales (phrase déclencheur → séquence d'outils, enregistrement, rejeu sans modèle)
  reminders.py      rappels annoncés à l'heure dite
  pc/apps.py        index des applications (menu Démarrer, Store via Get-StartApps, Steam)
  web.py            navigateur piloté (Playwright + Chrome installé, profil persistant) : web_* + connexion aux sites enregistrés
```

Comptes web : `settings.sites[name] = {url, username}` + mot de passe dans le coffre (`SecretStore.set_site`). `web_login` remplit le formulaire lui-même (profil `SITE_PROFILES['omnivox']` : `#Identifiant`, `#Password`) ; captcha → événement `web.captcha`, l'utilisateur le résout. Ne jamais écrire un mot de passe utilisateur dans le code, les tests réels ou les docs.

Contrôle complet de l'écran (`computer_use`) : outils `screen_info`, `mouse_move/click/drag`, `scroll`, `find_on_screen` (OCR RapidOCR hors-ligne), `click_text` ; boucle capture → action → capture dictée par le prompt quand la demande contient un mot-clé d'écran (`SCREEN_KEYWORDS`). Niveaux de modèles : `voice_model` (rapide), `reasoning_model` (création/tâches), `vision_model` (écran, doit accepter les images). Registre de transparence : `privacy_events` chaîné SHA-256 (`ConsentGate.verify/export`). Résumé quotidien : `ChatService.summarize_day` planifié à `daily_summary_time`.

Vue « Lunettes » dans le renderer (`GlassesView.tsx`) : détecter, connecter, mémoriser, choisir le micro. Le protocole exact des lunettes (flux caméra/audio) dépend du SDK du fournisseur, non confirmé : IRIS journalise les paquets bruts en attendant.

## Commandes
```bash
# backend (Python 3.13, venv dans backend/.venv)
cd backend && .venv/Scripts/python -m pytest tests -q
cd backend && .venv/Scripts/python -m iris --data-dir ./dev-data --no-token   # API seule

# app (Node 24)
npm run dev          # Electron + Vite avec rechargement, lance le backend depuis backend/.venv
npm run build        # compile electron/ et renderer/ dans out/
npm run backend:build   # PyInstaller → backend/dist/iris-backend (tests inclus)
npm run dist:full    # backend + installeur Windows dans release/IRIS-Setup-<version>.exe
```

## Conventions
- Modèle Claude par défaut `claude-opus-5`, `thinking: adaptive`, `output_config.effort`, repli serveur `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`). Ne pas réintroduire `budget_tokens` ni de prefill.
- Le renderer ne voit jamais une clé API : seulement `has_key` / `key_masked`.
- Toute nouvelle sortie réseau passe par `ConsentGate.check(data_type, agent)` et `consent.log("external_send", …)`.
- Toute capture (micro, écran, caméra) passe par `CaptureIndicator` (pastille Electron).
- Textes UI en français ; code et identifiants en anglais.


Plans : voir `docs/PLANS.md` (tarifs, quotas, ce qu'il manque avant la vente réelle : compte OpenRouter/ElevenLabs d'entreprise, serveur de licences). Préparation démo : `docs/LAUNCH-CHECKLIST.md`.
