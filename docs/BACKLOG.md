# Backlog d'améliorations — IRIS (état au 2026-09-02, soir)

Légende : ✅ fait · 🔧 partiel · ⏳ à faire · 🧭 décision produit à prendre

## A. Voix et audio
| # | Sujet | État | Notes |
|---|---|---|---|
| A1 | Voix française Windows (Hortense) en repli | ⏳ | Installation d'une fonctionnalité Windows (Paramètres › Heure et langue › Voix › Ajouter « Français »), droits admin requis : à faire par l'utilisateur. IRIS la sélectionne automatiquement dès qu'une voix « fr » est présente. |
| A2 | Voix ElevenLabs premium (Mélanie) / meilleures voix gratuites | 🧭 | Palier payant requis pour les voix de bibliothèque via l'API. Sarah (premade, fr vérifié) par défaut. Comparer Starter (~5 $/mois) vs qualité. |
| A3 | Alerte proactive de quota ElevenLabs | ✅ | Notification à 80 %, 95 % et 100 % (`tts.quota`), quota affiché dans Paramètres › Voix. |
| A4 | Sélection guidée du micro au premier lancement | ✅ | Étape « Audio » de l'assistant de démarrage (micro + sortie, mise en garde Hands-Free). |
| A5 | Latence du premier son | 🔧 | Pré-connexion HTTPS au démarrage + premier fragment lu dès la première virgule. |
| A5b | (ancien) |  | Session HTTP réutilisée (0,2 s sur les phrases suivantes). Pistes : WebSocket ElevenLabs, pré-connexion au démarrage, phrases plus courtes. |
| A7 | Mot d'activation appris sur la voix de l'utilisateur | ✅ | Paramètres › « Calibrer » : 3 répétitions → variantes réellement entendues ajoutées aux alias. |
| A8 | Mot « stop », état muet, activation « Dis Iris » / « Iris » | ✅ | IRIS écoute pendant qu'elle parle (« stop », « arrête », « tais-toi » coupent la voix) ; muet par bouton, Ctrl+Maj+M, barre système ou commande vocale « muet » (réactivation explicite) ; alias « dis iris », « iris ». |
| A6 | Détection automatique de la langue parlée | ⏳ | Vosk est monolingue par modèle ; passer par un modèle multilingue (Whisper local) ou par le STT cloud avec détection. |

## B. Lunettes / Bluetooth
| # | Sujet | État | Notes |
|---|---|---|---|
| B1 | Reconnexion automatique en cours d'usage | ✅ | `disconnected_callback` → reconnexion après 5 s si « Reconnexion automatique » est activée. |
| B2 | Détection « appairé » sur macOS / Linux | ⏳ | Windows : `Get-PnpDevice`. macOS : `system_profiler SPBluetoothDataType` ; Linux : `bluetoothctl paired-devices`. |
| B5 | Index des applications installées | ✅ | Menu Démarrer + Store (Get-StartApps) + Steam ; `open_application` par nom approximatif, outil `list_applications`. |
| B3 | Bascule intelligente du micro | 🔧 | Micro Hands-Free détecté → STT cloud automatique + avertissement. À faire : proposer explicitement le micro PC. |
| B4 | Bluetooth multipoint des lunettes | ⏳ | Dépend des échantillons matériels et du SDK du fournisseur. |

## C. Fiabilité des commandes
| # | Sujet | État | Notes |
|---|---|---|---|
| C1 | Test anti-régression « c'est fait » sans outil | ✅ | `test_action_guard_never_reports_fake_success`, `test_build_request_forces_tools`. |
| C2 | Mots-clés d'action élargis | 🔧 | Listes `STRICT_ACTION` + `STRICT_BUILD` (création de jeu/site/app/script). À enrichir avec les formulations observées dans le journal. |
| C3 | Ambiguïté réelle vs hésitation du modèle | ⏳ | Aujourd'hui : confirmation seulement pour les commandes dangereuses ; le modèle ne doit pas demander de confirmation pour une action simple. Affiner par catégorie d'outil. |
| C5 | Contrôle complet de l'écran (« computer use ») | ✅ | Souris, défilement, glisser, capture + OCR hors-ligne (`find_on_screen`, `click_text`), boucle capture → action → vérification. Modèle vision configurable (gratuits : MiniMax M3, Gemma 4). |
| C6 | Routines vocales | ✅ | Enregistrement/rejeu, déclencheur tolérant, exécution sans modèle, vue « Routines ». |
| C7 | Tâches longues autonomes | ✅ | Plan → exécution → vérification → rapport, 40 tours d'outils, annonce vocale. |
| C8 | Navigation web et connexion aux sites (Omnivox…) | ✅ | Chrome installé piloté par Playwright (fenêtre visible, session persistante) : `web_open/read/click/fill/login`. Identifiants dans le coffre Windows, saisis par l'utilisateur ; le modèle ne voit jamais le mot de passe ; captcha jamais contourné (l'utilisateur le résout). |
| C4 | Modèle payant (Claude) pour le raisonnement | 🔧 | Réglages « modèle de raisonnement / vision » (mélange gratuit/payant par type de demande). Reste : mesurer sur 50 commandes. | Connecteur Claude prêt (compte Anthropic à recharger). Comparer sur 50 commandes réelles : taux d'appel d'outil correct, latence, coût. |

## D. Confidentialité et sécurité
| # | Sujet | État | Notes |
|---|---|---|---|
| D1 | Aucune clé API en clair dans les logs | ✅ | Vérifié : les journaux ne contiennent que le jeton de session local (aléatoire, par lancement) ; clés masquées côté API (`key_masked`). |
| D2 | Registre de transparence | ✅ | Chaîne SHA-256, vérification d'intégrité, export JSON/CSV depuis Confidentialité. |
| D2b | (ancien) | Journal des accès existant (envois externes, captures, commandes, consentements) ; export et signature à faire (Phase 2 de la spec). |
| D3 | Mode confidentiel à bascule explicite | ✅ | Bouton barre latérale + Confidentialité + icône barre système : micro coupé, aucune relance, journalisé. |
| D4 | Chiffrement du `.env` et des données locales | 🧭 | Base, mémoire, messages : déjà AES-256-GCM. Le `.env` est en clair par choix (exigence « clé dans un .env ») ; alternative : coffre Windows comme pour les autres clés. |

## E. Fonctionnalités produit
| # | Sujet | État | Notes |
|---|---|---|---|
| E1 | Connecteur universel multi-agents | 🔧 | OpenRouter (centaines de modèles), Claude, GPT, Gemini, agent local. Claude Code / Codex en tant qu'agents « outils » : à concevoir. |
| E2 | Mémoire partagée / résumé quotidien | ✅ | Résumé automatique à l'heure choisie (+ bouton), rappels contextuels (`set_reminder`), souvenirs injectés à tous les agents. |
| E2b | (ancien) | Mémoire manuelle + outil `remember` en place ; résumé de journée à planifier (tâche de fond). |
| E3 | Contrôle du téléphone | ⏳ | Phase 2 (Android d'abord). |
| E4 | Génération d'images (Gemini) | ⏳ | Outil `generate_image` via Gemini à ajouter au registre d'outils. |

## F. Robustesse
| # | Sujet | État | Notes |
|---|---|---|---|
| F1 | Chien de garde ElevenLabs | ✅ | Réessai automatique toutes les 20 s après une erreur (sauf quota réellement épuisé). |
| F2 | Isolation des process dans l'outillage | ✅ | `scripts/stop-app.ps1` cible uniquement `IRIS.exe` et `iris-backend.exe`. |
| F5 | Bluetooth isolé de l'audio | ✅ | Bleak tourne dans un thread dédié (boucle asyncio propre, COM en MTA) : PortAudio/SAPI initialisent COM en STA sur le thread principal, ce qui cassait le scan (« Thread is configured for Windows GUI… »). |
| F6 | Création de code (jeu, site, app) | ✅ | Verbes de création couverts par le forçage d'outil + consignes de construction (dossier `Documents\IRIS\<projet>`, `write_file`, `open_path`). Vérifié : morpion HTML créé et ouvert. |
| F3 | Couverture de tests ElevenLabs / lunettes | ✅ | 25 tests : repli 402 → voix gratuite, alertes quota, analyse des appareils appairés, mode confidentiel. |
| F4 | Alerte avant épuisement du quota | ✅ | Voir A3. |
