# IRIS face à Relay et à Ray-Ban Meta — ce qui nous sépare, et ce qui doit nous séparer davantage

*Rédigé le 2026-09-03 à partir des pages publiques de relay.glass et des specs internes VELA. Ce document sert à deux choses : ne jamais empiéter sur le terrain de Relay, et savoir précisément sur quoi IRIS gagne.*

## 1. Ce que Relay annonce publiquement

| | Relay |
|---|---|
| Promesse | « It prompts your agents better than you do. » |
| Cœur du produit | Faire tourner des **agents de code** (Claude Code, Codex, OpenCode, Hermes, OpenClaw) sur l'ordinateur de l'utilisateur, et rédiger leurs prompts à sa place |
| Matériel | 2 caméras, 1 micro, 2 haut-parleurs, 4 Go, aucun écran, USB-C magnétique, **aucune IA dans les lunettes** |
| Prix | 249 $ à l'achat, sans abonnement ; option hébergée 519 $ la 1re année puis 279 $/an ; 29 $/mois seul |
| Modèle | Open source (MIT), protocole ouvert de 92 commandes |
| Confidentialité | Audio traité localement puis **supprimé** après transcription, clés API de l'utilisateur |
| Comparaison affichée | Tableau frontal contre Ray-Ban Meta |

## 2. Le terrain de Relay, où IRIS ne va pas

Ces angles sont ceux de Relay. IRIS ne les reprend ni dans son discours, ni dans sa hiérarchie de fonctionnalités.

- **« Mieux configurer vos agents que vous »** : l'écriture automatique de prompts n'est pas une promesse d'IRIS.
- **La télécommande d'agents de code** comme produit principal. IRIS sait lancer des commandes et écrire du code, mais ce n'est ni son titre ni sa raison d'être.
- **Le tableau comparatif frontal contre Ray-Ban Meta** comme argument central de vente.
- **L'open source comme argument de confiance.** Notre preuve de confiance est différente et vérifiable par l'utilisateur lui-même, voir plus bas.

Ce qui reste commun aux deux relève du standard de la catégorie, pas d'une reprise : commande vocale, mot d'activation, absence d'écran, mémoire, clés personnelles. Prétendre le contraire serait malhonnête et indéfendable.

## 3. Les trois axes propres à IRIS

### A. La confidentialité **prouvable**, pas seulement promise
Relay dit jeter l'audio. Meta affiche une diode. Dans les deux cas, l'utilisateur doit croire sur parole.

IRIS produit une **preuve vérifiable** :
- un registre de transparence **chaîné en SHA-256** : chaque capture, chaque envoi externe y est inscrit, et toute modification a posteriori casse la chaîne ;
- un bouton « Vérifier » qui recalcule la chaîne devant l'utilisateur, et un export complet ;
- un consentement **par type de donnée** (transcription, audio brut, image, mémoire), révocable ;
- un indicateur de capture **non fermable**, et un mode confidentiel qui coupe tout envoi externe.

C'est le seul argument de la catégorie qui ne demande aucune confiance. Il doit être le titre d'IRIS.

### B. Le contrôle **complet** de l'ordinateur, pas seulement des agents
Relay pilote des agents. IRIS pilote la machine : applications par leur vrai nom via un index du menu Démarrer, du Store et de Steam, adresses web, fichiers, commandes, clavier, souris, lecture de l'écran par vision et OCR, et **navigation web avec comptes enregistrés** (portails scolaires, outils métier) où l'utilisateur ne touche pas au clavier.

### C. La mémoire de la vie, pas du contexte de code
Routines vocales, rappels contextuels, résumé quotidien automatique des décisions, promesses, chiffres et idées. IRIS s'adresse à quelqu'un qui vit sa journée, pas seulement à un développeur devant son terminal.

## 4. Où Relay est devant, et ce qu'il faut construire pour passer devant

| Écart réel | État IRIS | À faire |
|---|---|---|
| **Accès à distance par téléphone** | Absent. IRIS exige un PC allumé à portée Bluetooth. | Priorité n° 1 après la démo : API locale exposée sur le réseau domestique avec appairage par code, puis application Android relais. C'est aussi la demande directe de l'utilisateur. |
| Travail qui continue après le départ | Tâches asynchrones avec rapport vocal (plan Pro) | Rendre visible dans la démo ; ajouter la reprise après veille. |
| Connecteurs d'agents de code | Annoncé au plan Ultra, non livré | Ne pas en faire un argument tant que ce n'est pas réel. |
| Commandes tactiles sur la branche | Dépend du matériel | À inscrire dans la demande de prix au fournisseur. |
| Achat unique sans abonnement | IRIS est un abonnement | Assumer : la valeur d'IRIS est logicielle et continue. Le plan Gratuit reste réellement utilisable, clés personnelles non bridées. |

## 5. Face à Ray-Ban Meta

Meta a le matériel, la distribution et la marque. IRIS n'a aucun intérêt à s'y comparer fonction par fonction. Le seul axe où Meta ne peut pas suivre est structurel : leur modèle économique repose sur la donnée, le nôtre sur l'abonnement. D'où la formulation à utiliser, sans citer Meta comme repoussoir :

> « Une IA que vous portez et dont vous pouvez vérifier vous-même, ligne par ligne, ce qu'elle a capté et ce qu'elle a envoyé. »

## 6. Décisions à appliquer dans le produit

1. La description publique d'IRIS mène par la confidentialité et la mémoire, l'orchestration d'agents arrive après. **Fait** (`package.json`, `README.md`).
2. Aucun nom de fournisseur matériel ni de projet tiers dans l'application livrée. **Fait**.
3. La vue Confidentialité doit être la deuxième étape de toute démonstration, juste après une commande vocale réussie.
4. Ne jamais annoncer une fonctionnalité non livrée sans la marquer « à venir ».
