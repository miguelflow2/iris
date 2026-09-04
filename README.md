# IRIS — application desktop VELA

> *Vois. Souviens-toi. Fais.* — Une IA. Toute ta vie. Rien à taper.

IRIS contrôle votre ordinateur à la voix, retient ce qui compte dans votre journée, et vous laisse **vérifier vous-même** ce qu'elle a capté et envoyé : registre de transparence chaîné en SHA-256, consentement par type de donnée, chiffrement AES-256, indicateur de capture impossible à masquer, mode 100 % local. Elle s'appuie sur plusieurs agents IA au choix (OpenRouter et ses modèles gratuits par défaut ; Claude, GPT, Gemini ou un agent local en option), avec vos propres clés si vous en avez.

## Installation (utilisateur)
1. Téléchargez `IRIS-Setup-<version>.exe` (dossier `release/` après `npm run dist:full`).
2. Installez, lancez IRIS : l'assistant de démarrage vous demande votre prénom, votre clé OpenRouter (modèles gratuits par défaut), vos consentements et votre mot d'activation.
3. Dites **« Dis-moi Iris, … »** — ou tapez dans la conversation. Raccourcis : `Ctrl+Maj+Espace` (parler), `Ctrl+Maj+I` (afficher IRIS).

Aucun Python ni Node n'est requis sur la machine cible : le service IRIS est embarqué dans l'installeur.

## Développement
Prérequis : Node ≥ 20, Python 3.11+ (3.13 testé), Windows 10/11.

```bash
cd backend && python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt && cd ..
npm install
npm run dev
```

Tests backend : `cd backend && .venv/Scripts/python -m pytest tests -q`
Installeur complet : `npm run dist:full`

## Voix d'IRIS (ElevenLabs)
Copiez `backend/.env.example` en `backend/.env` (développement) ou créez `%APPDATA%\IRIS\iris-data\.env` (application installée) avec `ELEVENLABS_API_KEY=...`, ou saisissez la clé dans Paramètres › Voix (elle est écrite dans ce `.env`, jamais dans le code). Voix française par défaut : Mélanie. Sans clé ou quota épuisé, IRIS utilise la voix Windows.

## Reconnaissance vocale
- **Hors-ligne (recommandé)** : Paramètres › Voix › « Télécharger le modèle » (Vosk français, 41 Mo). Tout reste sur l'appareil.
- **Cloud (repli)** : nécessite le consentement « Audio brut du micro » dans Confidentialité.
- Voix française pour la lecture : installez « Microsoft Hortense » (Windows › Heure et langue › Voix), puis choisissez-la dans Paramètres.

## Structure
Voir `CLAUDE.md` pour l'architecture détaillée et les conventions.
