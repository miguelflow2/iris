# VELA / IRIS — du problème à la fonctionnalité, et au plan

Fil conducteur : **la fragmentation** (outils, contextes, mémoire). Une seule interface vocale continue, gouvernance et confidentialité en fondation.
Légende : ✅ livré dans IRIS · 🔧 partiel · ⏳ à construire (dépendance indiquée).

## 1. Développeurs

| Problème documenté | Réponse IRIS | État | Plan |
|---|---|---|---|
| ~1 200 changements de contexte/jour, 15–30 min perdues à chaque bascule | Une seule interface vocale : « Dis-moi Iris, lance les tests », « ouvre le projet », « crée un jeu » ; IRIS choisit l'IA la mieux placée et parle sa syntaxe (OpenRouter, Claude, GPT, Gemini, IA locale) | ✅ routage, outils PC, fichiers, commandes, création de code | Gratuit (modèles gratuits) → Pro (Claude Sonnet 5) |
| Gestion des outils devenue un travail (GitHub, Slack, Jira, Notion…) | Navigation web pilotée + comptes enregistrés (connexion sans les mains), routines (« mode travail » ouvre VS Code, Slack, le dossier projet) | ✅ web_* + routines | Essentiel (web) · Gratuit (routines) |
| Déboguer le code IA prend plus de temps que l'écrire ; fatigue « créateur ↔ auditeur » | Tâches asynchrones : plan → exécution → vérification → rapport vocal ; le développeur revient seulement quand il y a quelque chose à réviser | ✅ tâches de fond, annonce vocale | Pro |
| Cycle de revue de code 2,1 → 5,8 jours | Retour vocal développeur : « état de la branche, tests rouges, build terminé » ; rappels contextuels sur les PR en attente | 🔧 via run_command + rappels ; outils dédiés `git_status`/`run_tests`/`watch_ci` à ajouter | Pro |
| Connecteurs d'agents de code (Claude Code, Codex) | Agents « outils » lancés en tâche de fond depuis la voix, résultat lu à la fin | ⏳ (E1) | Ultra |

## 2. Vie courante / individus

| Problème documenté | Réponse IRIS | État | Plan |
|---|---|---|---|
| Charge mentale : idées, promesses, décisions non capturées | Mémoire IRIS (« souviens-toi que… »), résumé quotidien automatique (décisions, promesses, chiffres, idées), rappels contextuels | ✅ | Gratuit (mémoire manuelle, rappels) · Pro (résumé quotidien, mémoire injectée à tous les agents) |
| Méfiance envers les objets connectés qui filment (CNIL, DPA) | Traitement local par défaut, consentement par type de donnée, indicateur de capture non désactivable, mode confidentiel, registre chaîné SHA-256 vérifiable et exportable | ✅ | Tous les plans (fondation, jamais payante) |
| Surcharge de notifications, réflexe de sortir le téléphone | Contrôle vocal du PC (apps, musique, sites, fichiers), lunettes = micro/haut-parleur, muet et stop vocaux | ✅ PC · ⏳ téléphone (E3, Android d'abord) | Gratuit (PC) · Essentiel (voix naturelle) · Pro (écran) · téléphone à venir |

## 3. Entreprises (PME)

| Problème documenté | Réponse IRIS | État | Plan |
|---|---|---|---|
| Le temps est la contrainte n°1 (46,5 %) | Déléguer à la voix pendant qu'on fait autre chose : tâches longues, routines, rappels, résumé de journée | ✅ | Pro |
| 5 à 10 outils déconnectés (facturation, projets, courriels) | Connecteur universel d'agents + navigation web avec comptes enregistrés (portails, CRM, banque en lecture) + routines multi-outils | ✅ base · ⏳ connecteurs natifs (courriel, calendrier, facturation) | Essentiel (web) · Ultra (connecteurs natifs, à venir) |
| ~~Réseaux sociaux : capture POV + montage assisté~~ | **Retiré le 5 septembre 2026.** Cette promesse supposait une caméra. Les lunettes VELA n'en ont pas, et sept pages du site en font un argument de vente — « des lunettes qui vous écoutent, sans jamais vous regarder ». Vendre l'un et promettre l'autre était intenable. | — | — |
| Usage non gouverné de l'IA = risque de sécurité | Gouvernance intégrée : aucune action sans demande explicite, confirmation des commandes dangereuses, registre exportable (audit), mode 100 % local, clés dans le coffre système | ✅ · ⏳ politique d'entreprise (liste d'agents autorisés, export centralisé, multi-comptes) | Tous (gouvernance) · Ultra (politique d'entreprise, à venir) |

## Répartition finale par plan (ce que le code applique aujourd'hui)

| | Gratuit 0 $ | Essentiel 19,99 $ | Pro 29,99 $ | Ultra 99,99 $ |
|---|---|---|---|---|
| Interface vocale, contrôle du PC, routines, rappels, mémoire manuelle | ✅ | ✅ | ✅ | ✅ |
| Gouvernance et confidentialité (consentements, registre, mode confidentiel, indicateur) | ✅ | ✅ | ✅ | ✅ |
| Modèles | gratuits (OpenRouter) | Gemini 2.5 Flash + GPT-5 mini | + Claude Sonnet 5 | + Claude Opus 5 |
| Voix | Windows | ElevenLabs 60 k car. | ElevenLabs 120 k car. | ElevenLabs 250 k car. |
| Navigation web et comptes enregistrés (Omnivox, portails, outils) | – | ✅ | ✅ | ✅ |
| Contrôle complet de l'écran (vision, OCR, souris) | – | – | ✅ | ✅ |
| Tâches asynchrones, résumé quotidien, mémoire partagée entre agents | – | – | ✅ | ✅ |
| Retour vocal développeur (git, tests, build) | – | – | ✅ (via commandes) | ✅ |
| Connecteurs d'agents de code, connecteurs natifs PME, création de contenu, politique d'entreprise | – | – | – | ⏳ (feuille de route) |
| Quota requêtes / mois | 300 | 600 | 1 000 | 1 500 |

Offre groupée : lunettes VELA + 12 mois Pro = 839 $.

## Argument de vente unique (à dire en interview)
« Une seule interface vocale continue qui élimine la fragmentation, outils, contextes, mémoire, conçue avec la gouvernance et la confidentialité comme fondation. » Preuve concrète dans IRIS : registre vérifiable, consentement par donnée, indicateur non désactivable, et une démo où l'utilisateur ne touche ni clavier ni souris.
