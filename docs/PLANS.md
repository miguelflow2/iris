# Plans d'abonnement IRIS — implémentation

Source de vérité du code : `backend/iris/plans.py` (`PLANS`, quotas, modèles inclus, clés).

| Plan | Prix / mois | Contenu | Quota requêtes / mois | Voix | Coût API estimé / abonné | Marge |
|---|---|---|---|---|---|---|
| GRATUIT | 0 $ | OpenRouter gratuit, voix Windows, Vosk | 300 | Windows | 0 $ | – |
| ESSENTIEL | 19,99 $ | Voix ElevenLabs, Gemini 2.5 Flash + GPT-5 mini, navigation web | 600 | ElevenLabs (60 k car.) | 13 $ | 31 % |
| PRO | 29,99 $ | + Claude Sonnet 5, contrôle d'écran (vision), mémoire, tâches | 1 000 | ElevenLabs (120 k car.) | 16 $ | 43 % |
| ULTRA | 99,99 $ | + Claude Opus 5 | 1 500 | ElevenLabs (250 k car.) | 62 $ | 35 % |

Offre groupée : **lunettes VELA + 12 mois Pro : 839 $** (`BUNDLE`).

## Ce que le plan change dans IRIS
- **Quota** : chaque requête à un agent est comptée (`plan_usage`, par mois). À 80 % et 95 % : notification ; au-delà : message clair et aucune requête envoyée.
- **Fonctionnalités** : `elevenlabs` (Essentiel+), `web` (Essentiel+), `screen` (Pro+), `memory` (Pro+), `tasks` (Pro+), `opus` (Ultra).
- **Modèles inclus** (via OpenRouter) : Essentiel → `google/gemini-2.5-flash` (rapide/vision) + `openai/gpt-5-mini` (raisonnement) ; Pro → + `anthropic/claude-sonnet-5` ; Ultra → `anthropic/claude-opus-5`. Les réglages personnels de modèles ont priorité.
- **Clés** : `IRIS-<payload>-<signature>` (HMAC-SHA256, plan + date d'expiration + email). Générées avec `scripts/make-license-key.py`. Plan expiré → retour automatique au Gratuit.
- **Mode démonstration** : vue Abonnement › « Essayer (démo) » active un plan localement sans clé (présentations, tests).

## Clés personnelles (BYOK)
Quand l'utilisateur apporte sa propre clé (OpenRouter dans le coffre Windows, `ELEVENLABS_API_KEY` dans `.env`), ce que sa clé paie n'est pas bridé par le plan : voix ElevenLabs, écran, mémoire, tâches, web et quota de requêtes restent disponibles même en Gratuit (`PlanService.byok_models/byok_tts`). Les paliers s'appliquent aux ressources fournies par VELA (modèles inclus, voix, quotas). Sans cette règle, la machine de Miguel (plan Gratuit) retombait sur la voix Windows « Zira », anglaise.

## Avant la vente réelle
1. **Compte OpenRouter d'entreprise** avec crédits : les modèles payants inclus dans les plans sont facturés à VELA, pas à l'abonné. Aujourd'hui le compte est en palier gratuit : un abonné Pro obtiendrait des erreurs « crédits insuffisants » sur Claude Sonnet 5 tant que le compte n'est pas rechargé (IRIS retombe alors sur les modèles gratuits).
2. **Compte ElevenLabs Creator/Pro** pour les quotas de caractères des plans.
3. **Serveur de licences** (Stripe + API) : le secret HMAC est dans l'application, suffisant pour un lancement contrôlé, pas pour une distribution massive. Remplacer par des clés signées côté serveur et une vérification en ligne.
4. **Comptabilité de l'usage** côté serveur si l'on veut empêcher la remise à zéro locale.

## Paiement (branché le 2026-09-03)

Compte PayPal de l'entreprise : `https://paypal.me/irisvela461`. Les liens sont générés par `plans.payment_link()` avec le montant et la devise (CAD) pré-remplis, et exposés dans `/api/plan` (`plans[].pay_url`, `bundle.pay_url`, `payment`).

**Ce que ce lien fait, et ce qu'il ne fait pas.** C'est un versement unique. Il ne crée aucun abonnement récurrent, il n'envoie aucune notification à IRIS, et il n'active aucun plan automatiquement.

Parcours réel, affiché à l'identique dans l'application et sur le site :
1. Le client paie ; le montant est déjà rempli.
2. Il envoie sa confirmation à miguelfreddy65@gmail.com.
3. VELA génère une clé avec `backend\.venv\Scripts\python scripts\make-license-key.py <plan> <AAAA-MM-JJ> <courriel>` et l'envoie ; le client la colle dans Abonnement.

**Pour automatiser plus tard.** Il faut un compte PayPal Business avec les abonnements et les notifications instantanées de paiement, ou Stripe Billing, plus un petit service en ligne qui reçoit la notification, génère la clé et l'envoie. Tant que ce service n'existe pas, le renouvellement est manuel et il faut prévenir le client avant l'échéance de sa clé.
