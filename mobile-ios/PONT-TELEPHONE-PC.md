# Le pont téléphone ↔ PC — le protocole, réutilisé tel quel

Écrit le 2026-09-06. Décrit **comment l'app iPhone parle au backend IRIS resté à la maison.** Bonne
nouvelle d'entrée de jeu : **ce protocole existe déjà et il est testé.** La page web `/m`
(`backend/iris/mobile.py`) s'en sert tous les jours. L'app native ne l'invente pas — elle le
**porte** de JavaScript à Swift, à l'identique. Ce document est donc autant une **spécification à
copier** qu'un plan.

Tout ce qui suit est vérifié dans le code actuel (`mobile.py`, `main.py`,
`routes_communications.py`, `telephonie.py`), pas supposé.

---

## Le chemin réseau

```
  App iPhone ──HTTPS──▶ Tailscale (tunnel privé chiffré) ──▶ backend FastAPI (PC maison)
             ◀─────────  https://<nom>.ts.net             ◀──  127.0.0.1:8765
```

- **Le transport** est déjà décidé et documenté : **Tailscale** (`docs/ACCES-DISTANT.md`, partie A).
  Il donne au téléphone une adresse `https://…ts.net` **stable** (même à la maison et dehors),
  chiffrée de bout en bout, **sans ouvrir un seul port** sur la box. L'app native utilise cette
  adresse comme base d'URL, exactement comme la page web utilise `location.origin`.
- **Le `https://` n'est pas un luxe :** c'est lui qui débloque le micro sur l'iPhone et l'accès
  depuis l'extérieur. Sans le tunnel, l'app ne joint pas le PC de la voiture.

---

## La serrure : jeton maître ou session par mot de passe

Toutes les routes `/api/*` sont protégées par la **même** dépendance (`require_token` dans
`main.py`). L'app envoie un en-tête :

```
Authorization: Bearer <JETON>
```

où `<JETON>` est, par ordre de préséance (repris du JS de `mobile.py`) :

1. **Une session ouverte avec le mot de passe** (`iris_session`) — la bonne, depuis l'extérieur.
2. **Le jeton d'adresse** (`?token=…`) — valable **seulement depuis la machine elle-même** dès
   qu'un mot de passe existe (corrigé le 5 sept. 2026 ; cf. `ACCES-DISTANT.md` §A.3). L'app ne doit
   **pas** compter dessus pour l'usage à distance.

**Le flux d'ouverture de session, tel qu'il existe :**

| Étape | Appel | Réponse |
|---|---|---|
| 1. Un mot de passe est-il posé ? | `GET /api/compte` | `{ "configure": true\|false }` |
| 2. Se connecter | `POST /api/compte/connexion` `{ "mot_de_passe": "…" }` | `{ "session": "<jeton>" }` |
| 3. Vérifier la session | `GET /api/status` (avec Bearer) | `200` + `{ "platform": "…" }` ou `401` |

L'app **retient la session** (dans le trousseau *Keychain* d'iOS, plus sûr que le `localStorage` du
web) et la rejoue dans `Authorization`. Sur `401`, elle redemande le mot de passe. La session dure
30 jours. **Ne jamais mettre le jeton dans une URL** (il finirait dans un journal, un historique) —
toujours dans l'en-tête.

> Règle de sécurité déjà inscrite dans le projet : **l'adresse seule ne doit jamais suffire à
> commander l'ordinateur.** Le mot de passe est la vraie serrure ; le tunnel ne remplace que le
> trajet.

---

## Parler à IRIS : le même aller-retour que la page web

C'est le cœur, et c'est un copier-coller conceptuel du JS de `mobile.py` :

1. **Ouvrir une conversation** (une fois, puis réutiliser l'`id`) :
   `POST /api/conversations` `{ "title": "…", "agent": "auto" }` → `{ "id": "…" }`
2. **Envoyer le message** :
   `POST /api/conversations/{id}/messages` `{ "text": "…", "agent": "auto", "images": [] }`
3. **Attendre la réponse** — aujourd'hui par **sondage** :
   `GET /api/conversations/{id}` → `{ "messages": [ { "role": "assistant", "text": "…", "meta": {…} } … ] }`
   On lit le dernier message `assistant` porteur d'un `text` (ou d'une `meta.error`), puis on le lit
   à voix haute.

**Ce que l'app native peut améliorer ici (mais pas obligée pour la v1) :**
- Le web **sonde** parce qu'une page mise en veille par iOS perd sa connexion, et que la session par
  mot de passe n'ouvre pas le WebSocket. Une app native peut, elle, tenir une connexion plus
  proprement et surtout recevoir des **notifications push** (voir plus bas). *Le sondage reste une
  base parfaitement fonctionnelle pour commencer.*

**Ajouté le 2026-09-14 (demandes de l'équipe iOS), côté service — l'app ne les utilise pas encore :**
- `POST /api/voix/commande` `{ "texte", "source": "iphone", "conversation_id": null }` → `{ "texte", "intercepte",
  "duree_ms", "conversation_id"?, "message_id"?, "refus"?, "lunettes_requises"?, "consentement_requis"? }`.
  Une phrase dite dans les lunettes reliées à l'iPhone, transcrite par l'iPhone : interceptions du service d'abord
  (mode invité, pas à pas, vision, résumé…), puis le chat avec la règle de la voix (lunettes exigées, 428 sinon ;
  pas d'aperçu écrit ; réponse orale courte). L'ordinateur ne lit rien à voix haute : l'iPhone lit `texte`.
  Mode traduction et interprète refusés (`refus: "micro_de_la_maison"`), car ils ouvriraient le micro de la maison.
  Remplacera `/messages` + `CommandesLocales.swift` pour la voix. Limite : une demande d'accord d'un outil
  s'affiche comme `chat.confirm` (événement), jamais à voix haute sur l'ordinateur.
- `GET /api/conversations/{id}?depuis=<id du dernier message lu>` (ou `?limit=N`, les N derniers) : seulement la
  suite. `depuis_trouve: false` = message inconnu, recharger toute la conversation.

---

## Les brouillons SMS / appel : la route qui manquait, déjà rebouchée

Depuis l'incident du 6 septembre 2026 (`routes_communications.py`), le PC **dépose** un brouillon et
le téléphone le **sonde** :

- **Lire les brouillons en attente** :
  `GET /api/telephonie/en_attente` → `{ "brouillons": [ … ], "voie": "iphone" }`

  Chaque brouillon a exactement cette forme (`Brouillon.en_dict`, vérifiée dans `telephonie.py`) :
  ```json
  {
    "id": "…",
    "genre": "sms" | "appel",
    "numero": "+1819…",
    "numero_lisible": "819 …",
    "texte": "…",              // vide pour un appel
    "segments": 1,
    "titre": "…",
    "lien_ios": "sms:+1819…&body=…" | "tel:+1819…",
    "lien_android": "sms:+1819…?body=…" | "tel:+1819…",
    "depose_a": "2026-09-06T…"
  }
  ```
  Sur iPhone, l'app prend **`lien_ios`** (iOS attend `sms:…&body=`, cf. commentaire dans le code).

- **Ouvrir le brouillon** : app native → `MFMessageComposeViewController` pré-rempli (SMS) ou
  `tel:` (appel). **L'utilisateur touche Envoyer / Appeler.** Rien ne part seul (cf. REALITE-IOS.md
  points 4-5).

- **Marquer le résultat** :
  `POST /api/telephonie/{id}/envoye` → `{ "message": "C'est noté, le message est parti…" }`
  `POST /api/telephonie/{id}/annule` → `{ "message": "D'accord, je l'oublie." }`

Les brouillons **expirent au bout de quinze minutes** côté PC ; l'app n'a rien à gérer là-dessus.

> **Trou connu à boucher avant d'activer la téléphonie depuis le téléphone** (documenté en tête de
> `telephonie.py`) : la page `/m` — et donc, à reproduire, l'app — **n'écoute pas encore
> « chat.confirm »**. Une confirmation demandée par IRIS (« j'envoie ce texto ? ») est aujourd'hui
> **invisible** côté téléphone : le tour tournerait 180 s puis renverrait « refusé » sans rien
> afficher. Tant que ce n'est pas réglé, ne pas proposer les outils de téléphonie depuis l'app.

---

## Les événements du PC : sondage aujourd'hui, push demain

Le backend publie déjà des événements sur un hub interne (`events.py`) — p. ex.
`telephone.brouillon`, `telephone.brouillon_ferme`, et la future `chat.confirm`. Deux façons de les
faire arriver au téléphone :

- **Aujourd'hui (web et app v1) : le sondage.** L'app interroge `/api/telephonie/en_attente` et
  `/api/conversations/{id}` à intervalle régulier. Simple, robuste, résiste à la mise en veille. La
  page web sonde toutes les 5 s ; l'app peut faire pareil.
- **Demain (gain propre à l'app) : les notifications push (APNs).** Le PC pousse « un texto est
  prêt » / « confirme cet envoi » vers Apple, qui réveille l'app même fermée. C'est **le** vrai
  gain de l'app sur la PWA côté événements. *À concevoir au moment de la construction (petit relais
  APNs côté PC) ; tant qu'il n'existe pas, le sondage tient le rôle.*

**Point important pour la téléphonie depuis le téléphone :** exposer `chat.confirm` au téléphone
(par sondage d'une route `/api/…/confirmations` à ajouter, ou par push) est **le préalable** pour
qu'IRIS puisse préparer un SMS/appel demandé **en voiture**. Sans lui, on peut parler à IRIS et lui
faire agir sur le PC, mais pas lui faire préparer un texto en mobilité. À prioriser dès qu'on veut
la téléphonie hors de la maison.

---

## L'atout que ce pont rend possible : l'appel qui PASSE par le PC

C'est le point le plus intéressant pour Miguel, et il découle directement de l'architecture.

Sur l'iPhone seul, IRIS ne peut ni décrocher un appel cellulaire, ni le mener (cf. REALITE-IOS.md
points 2-3-5 : le *sandbox* interdit de toucher l'audio d'un appel de la ligne SIM). **Mais le PC,
lui, n'a pas ces limites.** Le pont ouvre donc une voie que le téléphone seul n'a pas :

- **Un appel monté côté PC/serveur.** IRIS, sur le PC, relie un opérateur de téléphonie Internet
  (type Twilio, la voie « twilio » **déjà écrite mais dormante** dans `telephonie.py`) à sa propre
  voix : elle compose le numéro, parle à la réception, écoute la réponse — **parce que l'appel ne
  passe jamais par la ligne cellulaire de l'iPhone.** Le téléphone n'est là que pour **déclencher**
  la demande à la voix (« Iris, réserve une table pour deux à 19 h ») et **entendre** le
  compte-rendu.
- **Ce que ça coûte et ce que ça vaut.** L'appel part alors d'un **numéro loué**, pas du numéro
  personnel, et il est **facturé à la minute** — c'est la limite honnête (déjà notée dans
  `telephonie.py` et `docs/ARCHITECTURE-MOBILITE.md` §5). Mais c'est la **seule** façon réelle de
  faire « IRIS appelle à ma place et mène la conversation », et **le pont la rend atteignable** sans
  rien demander d'impossible à l'iPhone.

Autrement dit : le mur du point 5 (« IRIS mène l'appel ») n'est pas franchi *sur le téléphone*, il
est **contourné par le PC**. C'est exactement pourquoi l'architecture « le téléphone est la voix,
le PC est le cerveau » n'est pas un compromis : elle débloque des choses que le téléphone seul
n'atteindrait jamais.

---

## Récapitulatif des routes (toutes déjà existantes)

| But | Route | Corps / Réponse |
|---|---|---|
| Mot de passe posé ? | `GET /api/compte` | `{ configure }` |
| Se connecter | `POST /api/compte/connexion` | `{ mot_de_passe }` → `{ session }` |
| Vérifier session / plateforme | `GET /api/status` | `{ platform }` (ou 401) |
| Ouvrir une conversation | `POST /api/conversations` | `{ title, agent }` → `{ id }` |
| Envoyer un message | `POST /api/conversations/{id}/messages` | `{ text, agent, images }` |
| Lire les réponses | `GET /api/conversations/{id}` | `{ messages: [...] }` |
| Brouillons en attente | `GET /api/telephonie/en_attente` | `{ brouillons, voie }` |
| Brouillon envoyé | `POST /api/telephonie/{id}/envoye` | `{ message }` |
| Brouillon annulé | `POST /api/telephonie/{id}/annule` | `{ message }` |

**À ajouter côté backend pour la mobilité complète** (pas encore là) : une route pour lire/répondre
aux **confirmations** `chat.confirm` depuis le téléphone, et (plus tard) le **relais APNs**. Tout le
reste, l'app native le réutilise à l'identique.
