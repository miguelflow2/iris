# Le suivi des commandes de lunettes

**Document d'architecture. Rien de ce qui est décrit ici n'est codé côté serveur.** Ce qui existe
aujourd'hui, ce sont deux pages de site (`site/suivi.html`, `site/merci.html`) écrites pour
*recevoir* ce suivi, et le serveur de licences (`server/licences/`) qui reçoit déjà les paiements.

Objectif de Miguel, dans ses mots : « je veux juste que tout soit automatisé — l'abonnement, le
suivi de commande, le compte de la personne. » Ce document dit ce qui peut l'être, dans quel ordre,
et — c'est la partie la plus utile — **ce qui ne le sera pas avant longtemps**.

Ce n'est pas urgent. C'est écrit maintenant pour que le jour où ça devient urgent, la décision soit
déjà prise et qu'il ne reste qu'à taper.

---

## 1. La règle qui gouverne tout le reste

> **On n'affiche que des faits datés. Ce qu'on ignore, on l'écrit « inconnu ».**

Un faux « livraison prévue le 12 » rassure une journée et fâche la semaine suivante. Une ligne qui
dit « date d'expédition : inconnue — nous vous écrivons dès l'envoi » est moins jolie et vaut
infiniment mieux. C'est la même règle que le registre chaîné d'IRIS et que le tableau de
caractéristiques de `lunettes.html` (« non mesuré par VELA ») : **rien qui ne se vérifie**.

Conséquence concrète, à ne jamais contourner :

- aucune date de livraison n'est **calculée** (pas de « paiement + 21 jours ») ;
- aucun délai moyen n'est affiché ;
- aucun transporteur n'est nommé avant qu'il y en ait un ;
- une barre de progression décorative est interdite : chaque étape franchie correspond à un
  enregistrement daté en base, ou elle ne s'affiche pas.

---

## 2. D'où viennent les données

### 2.1 Le seul signal réel aujourd'hui : le webhook PayPal

`server/licences/paypal.py` existe et fonctionne. C'est le seul endroit du système où une
information sur une commande arrive **toute seule**, sans que personne ne la saisisse.

Ce qu'il sait faire, vérifié dans le code :

| Fonction | Ce qu'elle donne |
|---|---|
| `ClientPaypal.verifier_signature()` | Renvoie les cinq en-têtes de signature à PayPal et confirme que l'événement vient bien de lui. Sans ça, n'importe qui pourrait s'inventer une commande payée. |
| `courriel_du_payeur()` | L'adresse du payeur, cherchée dans cinq emplacements selon le type d'événement, avec un repli sur `custom_id`. |
| `montant_de()` | Le couple (montant, devise). |
| `identifiant_transaction()` | L'identifiant de la capture — la clé d'idempotence : un même paiement ne peut pas créditer deux fois. |

Et `server/licences/app.py` refuse tout webhook non authentifié (400), ou répond 503 si PayPal est
injoignable pour que l'événement soit relancé plus tard. Cette partie-là est solide ; le suivi de
commande doit s'y brancher, pas la refaire.

### 2.2 Ce que le webhook donne — et ce qu'il ne donne pas

Un `PAYMENT.CAPTURE.COMPLETED` de 250,00 CAD apporte :

- ✅ le **courriel du payeur** ;
- ✅ le **montant et la devise** ;
- ✅ l'**identifiant de transaction** (idempotence) ;
- ✅ la **date du paiement** (celle de l'événement).

Il n'apporte pas, et c'est le nœud du problème :

- ❌ l'**adresse de livraison** ;
- ❌ la **monture voulue** (verres transparents ou teintés) ;
- ❌ un **numéro de téléphone** pour le transporteur ;
- ❌ évidemment, aucune information d'expédition.

**Pourquoi :** les quatre boutons d'achat du site sont des liens `paypal.me`
(`https://paypal.me/irisvela461/250.00CAD`). Un lien `paypal.me` est un versement de personne à
personne : il ne collecte pas d'adresse de livraison, il ne porte pas de `custom_id`, et **il ne
ramène pas l'acheteur sur une page de retour**. C'est pour cette raison que `merci.html` n'est pas
atteinte par une redirection automatique mais par les liens posés sur l'accueil et sur
`lunettes.html`.

> **Décision de Miguel, la plus structurante de ce document.** Remplacer les liens `paypal.me` par
> un vrai bouton de paiement PayPal (compte Business) changerait tout : PayPal collecterait
> l'adresse de livraison, accepterait un `custom_id` (que `courriel_du_payeur()` sait déjà lire, voir
> le repli en bas de la fonction) et redirigerait vers `merci.html`. Sans ça, **l'échange de
> courriels reste obligatoire pour chaque commande**, et aucune automatisation ne l'éliminera.

### 2.3 Ce qui existe déjà et qu'on n'a pas remarqué

Aujourd'hui, un paiement de 250 $ **ne se perd pas**. Voici ce qui se passe réellement dans
`server/licences/service.py` :

1. `_crediter()` appelle `montants.reconnaitre(250.0, "CAD")` ;
2. `server/licences/montants.py` exclut **volontairement** 250,00 de `TARIFS` — pour qu'un achat de
   matériel n'offre pas un mois d'abonnement ;
3. `reconnaitre()` renvoie donc `None`, et `_crediter()` bascule sur `_vers_manuel()` ;
4. une ligne apparaît dans la table `manuel` avec la raison « Montant non reconnu : 250.0 CAD.
   Aucun plan activé. », et `Facteur.alerter()` envoie un courriel à Miguel.

**C'est exactement le point de branchement du suivi de commande.** Il ne faut pas construire à
côté : il faut transformer ce « à traiter manuellement » en « commande créée ».

### 2.4 Ce qui ne peut venir que de Miguel, à la main

| Donnée | Qui la connaît | Comment elle entre dans le système |
|---|---|---|
| Monture choisie | Le client, par courriel | Saisie à la main |
| Adresse de livraison | Le client, par courriel | Saisie à la main (ou par PayPal, si bouton Business) |
| Date de commande à l'atelier | Miguel | Saisie à la main |
| Référence de commande chez le fournisseur | Le fournisseur | Recopiée à la main |
| Date d'expédition | Le fournisseur | Recopiée à la main |
| Transporteur + numéro de suivi | Le fournisseur | Recopié à la main **une seule fois** |
| Position du colis, date estimée | Le transporteur | Automatisable, *si* un numéro de suivi existe |
| Livraison confirmée | Le transporteur, ou le client | Automatisable ou saisie à la main |
| Annulation, remboursement | PayPal + Miguel | Webhook partiel, décision à la main |

### 2.5 « Des délais en temps réel, du jour de la commande au jour de livraison »

Il faut être précis sur ce que « temps réel » peut vouloir dire, segment par segment :

| Segment | Temps réel possible ? |
|---|---|
| Paiement → commande créée | **Oui, tout de suite.** Le webhook arrive en quelques secondes. |
| Commande créée → passée au fournisseur | **Non.** Dépend du moment où Miguel la passe. |
| Passée → expédiée | **Non**, sauf si le fournisseur pousse l'information (voir §7). |
| Expédiée → livrée | **Oui, dès qu'un numéro de suivi existe** et qu'un service de suivi transporteur est branché. |

Autrement dit : le « temps réel » est réel aux deux extrémités, et humain au milieu. Une page qui
prétendrait le contraire mentirait. `suivi.html` est écrite pour dire ce milieu-là honnêtement.

---

## 3. Les états d'une commande

Cinq états dans l'ordre, deux voies de traverse. Ce vocabulaire est déjà affiché tel quel sur
`site/suivi.html` : **si un identifiant change ici, il faut le changer là-bas aussi**, ainsi que
dans `ETIQUETTES_ETAT` en haut du bloc « suivi de commande » de `site/assets/site.js`.

| Identifiant | Libellé affiché | Qui le déclenche |
|---|---|---|
| `paiement_recu` | Paiement reçu | Webhook PayPal — **automatique** |
| `commandee_fournisseur` | Commande passée au fournisseur | Miguel, à la main |
| `expediee` | Expédiée | Miguel, à la main (ou fournisseur, plus tard) |
| `en_transit` | En transit | Transporteur, si branché ; sinon à la main |
| `livree` | Livrée | Transporteur, si branché ; sinon à la main |
| `annulee` | Annulée | Miguel, à la main ; le remboursement se fait chez PayPal |
| `probleme` | Problème | Miguel, à la main — dit explicitement qu'un humain s'en occupe |

Règles de transition :

- une commande **n'avance jamais toute seule** au-delà de `paiement_recu` ;
- elle ne recule pas : pour revenir en arrière on passe par `probleme`, qui est un état visible et
  assumé, pas une correction silencieuse ;
- `annulee` et `probleme` sont atteignables depuis n'importe quel état ;
- chaque passage écrit **une ligne d'historique datée** (table `commande_etats`), jamais un simple
  écrasement du champ `etat`. On veut pouvoir dire *quand* c'est arrivé, pas seulement *que* c'est
  arrivé.

---

## 4. Les tables

Elles s'ajoutent à `SCHEMA` dans `server/licences/base.py`, à la suite des trois existantes
(`abonnements`, `evenements`, `manuel`). **Aucun script de migration n'est nécessaire :** `SCHEMA`
est exécuté à chaque ouverture par `cx.executescript()` et toutes les instructions sont en
`IF NOT EXISTS`. La base se met à jour toute seule au prochain démarrage.

Conventions reprises telles quelles de l'existant, à ne pas changer : dates en texte ISO
(`base.maintenant()` pour un horodatage UTC, `AAAA-MM-JJ` pour une date de calendrier), courriels
normalisés par `base.normaliser()`, contraintes `UNIQUE` pour l'idempotence, colonnes `cree_le` /
`maj_le`.

```sql
CREATE TABLE IF NOT EXISTS commandes (
    numero          TEXT PRIMARY KEY,      -- VELA-XXXXXXXXXX, aléatoire (voir §6.1)
    courriel        TEXT NOT NULL,         -- normalisé, comme dans abonnements
    produit         TEXT NOT NULL DEFAULT 'lunettes',
    quantite        INTEGER NOT NULL DEFAULT 1,
    monture         TEXT,                  -- 'transparents' | 'teintes' | NULL tant qu'inconnue
    montant         REAL,
    devise          TEXT,
    transaction_id  TEXT UNIQUE,           -- capture PayPal : une capture = une commande, jamais deux
    etat            TEXT NOT NULL,         -- vocabulaire du §3
    transporteur    TEXT,                  -- NULL tant qu'il n'y en a pas. Jamais deviné.
    suivi_numero    TEXT,                  -- NULL tant qu'il n'y en a pas
    suivi_url       TEXT,                  -- fournie par le transporteur, jamais construite à la main
    livraison_estimee TEXT,                -- AAAA-MM-JJ, UNIQUEMENT si le transporteur l'annonce
    reference_fournisseur TEXT,            -- n° de commande chez l'atelier, recopié à la main
    cree_le         TEXT NOT NULL,
    maj_le          TEXT NOT NULL,
    note_client     TEXT DEFAULT '',       -- lisible par le client
    note_interne    TEXT DEFAULT ''        -- JAMAIS renvoyé par l'API publique
);

-- L'historique : une ligne par changement d'état. C'est lui qui permet de dire
-- « expédiée le 12 » plutôt que seulement « expédiée ».
CREATE TABLE IF NOT EXISTS commande_etats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    numero      TEXT NOT NULL,
    etat        TEXT NOT NULL,
    survenu_le  TEXT NOT NULL,   -- la date du FAIT, qui n'est pas celle de la saisie
    saisi_le    TEXT NOT NULL,   -- base.maintenant()
    source      TEXT NOT NULL,   -- paypal | manuel | fournisseur | transporteur
    detail      TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_commandes_courriel    ON commandes(courriel);
CREATE INDEX IF NOT EXISTS idx_commande_etats_numero ON commande_etats(numero);
```

### Ce qui n'est volontairement pas dans ces tables

**L'adresse de livraison et le numéro de téléphone.** Aujourd'hui ils vivent dans la boîte de
courriels de Miguel, et c'est très bien ainsi : ne pas stocker une donnée, c'est la seule façon
certaine de ne pas la perdre. Le jour où PayPal les fournira (bouton Business) ou où il faudra les
garder, ils vont dans **une table séparée** — jamais renvoyée par l'API publique, jamais affichée
sur `suivi.html`, et il faudra alors mettre à jour `site/politique-confidentialite.html`, qui décrit
aujourd'hui un logiciel qui ne conserve rien côté serveur.

`monture` figure dans `commandes` parce que le client peut légitimement vouloir vérifier ce qu'il a
commandé, et parce que ce n'est pas une donnée sensible.

---

## 5. Les points d'entrée

### 5.1 Ce que le site appelle

Un seul appel public, et **il est en POST**.

```
POST /api/commande/suivi
Content-Type: application/json

{ "numero": "VELA-7QK2M4XZP3", "courriel": "client@exemple.ca" }
```

Pourquoi POST et pas GET : un GET mettrait le numéro de commande et le courriel dans l'URL. Ils se
retrouveraient dans les journaux du serveur, dans l'historique du navigateur, dans l'en-tête
`Referer` de tout lien sortant, et dans le presse-papier de qui copie l'adresse pour la partager.
**Un numéro de commande dans un lien partageable est déjà une fuite.**

Réponse, commande trouvée :

```json
{
  "trouvee": true,
  "numero": "VELA-7QK2M4XZP3",
  "etat": "expediee",
  "dates": {
    "paiement_recu": "2026-09-04",
    "commandee_fournisseur": "2026-09-06",
    "expediee": "2026-09-19",
    "livree": null
  },
  "transporteur": null,
  "suivi_numero": null,
  "suivi_url": null,
  "livraison_estimee": null,
  "message": ""
}
```

Réponse, commande introuvable **ou** couple qui ne correspond pas — la même dans les deux cas :

```json
{ "trouvee": false }
```

Trois règles sur cette réponse :

1. **`null` veut dire « on ne sait pas », et le site l'écrit « inconnue ».** Il ne faut jamais
   remplacer un `null` par une valeur par défaut « pour faire propre ».
2. **`livraison_estimee` ne vient que du transporteur.** Si le serveur la calcule un jour à partir
   d'une moyenne, il ment, et la page ment avec lui.
3. **Rien d'autre ne sort.** Ni `note_interne`, ni `reference_fournisseur`, ni le montant, ni
   l'adresse. Le client sait déjà ce qu'il a payé ; le reste ne sert à personne sur cette page.

### 5.2 Ce que le site fait déjà de son côté

`site/assets/site.js` contient le bloc « suivi de commande », avec en tête :

```js
var ADRESSE_SUIVI = '';
```

Tant que cette constante est vide, **aucune requête réseau n'est émise** : le formulaire redit à la
personne le numéro qu'elle a saisi et l'oriente vers le courriel. Le jour où le service existe, il y
a exactement **trois** choses à faire :

1. y mettre l'adresse complète du service (ex. `https://licences.vela.app/api/commande/suivi`) ;
2. ajouter cette origine à `connect-src` dans `site/_headers` — sinon la politique de sécurité du
   contenu bloque l'appel **sans aucun message visible** ;
3. autoriser l'origine du site en CORS côté serveur, pour ce seul point d'entrée.

L'avertissement jaune « le suivi automatique n'est pas encore branché » de `suivi.html` disparaît
tout seul dès que `ADRESSE_SUIVI` est renseignée : il n'y a pas deux textes à tenir d'accord.

### 5.3 Comment un état se met à jour

**Automatiquement**, une seule fois par commande : à la réception du webhook. Dans
`service._crediter()`, avant de basculer vers `_vers_manuel()`, on reconnaît le montant du matériel
et on crée la commande.

Ça demande un ajout à `montants.py`, à côté de `TARIFS` et **surtout pas dedans** — le commentaire
du fichier explique pourquoi 250,00 en est exclu, et cette raison reste valable :

```python
# Le matériel : reconnu séparément des abonnements. Un paiement de matériel crée une
# COMMANDE et n'active AUCUN plan — c'est pour cela que 250,00 n'est pas dans TARIFS.
MATERIEL: tuple[tuple[float, str, str], ...] = (
    (250.00, "lunettes", "Lunettes VELA"),
)
```

Nouvelle branche dans `_crediter()` :

```
montant reconnu comme abonnement ? → comportement actuel, inchangé
sinon, reconnu comme matériel ?    → créer la commande, envoyer le numéro par courriel,
                                     conclure_evenement(resultat="commande")
sinon                              → _vers_manuel(), comportement actuel
```

`resultat="commande"` est une valeur à ajouter à la liste des résultats documentée en tête de
`base.py` (`active | prolonge | annule | expire | echec_paiement | manuel | ignore`).

**À la main**, pour tout le reste, depuis la page `/admin` qui existe déjà :

```
POST /admin/commande/etat   (jeton d'administration obligatoire, comme /admin/emettre)
  numero, etat, survenu_le, transporteur?, suivi_numero?, suivi_url?,
  livraison_estimee?, reference_fournisseur?, note_client?
```

et un tableau « Commandes » à ajouter dans `_page_admin()`, à côté d'« Abonnements » et de « À
traiter manuellement ». Même protection : `hmac.compare_digest` sur le jeton, `html.escape()` sur
tout ce qui s'affiche.

Chaque appel écrit une ligne dans `commande_etats` **et** envoie un courriel au client. C'est le
seul geste que Miguel a à faire : changer l'état, le client est prévenu.

`Facteur` (`server/licences/courriel.py`) sait déjà envoyer une clé de licence ; il suffit de lui
ajouter les gabarits « votre numéro de commande » et « votre commande a changé d'état ».

---

## 6. Comment un client voit sa commande, et pas celle d'un autre

**C'est le point de sécurité central de ce document.** Une page de suivi est, par nature, accessible
sans mot de passe : c'est tout l'intérêt, et c'est tout le danger.

### 6.1 Le numéro de commande doit être imprévisible

`VELA-000001`, `VELA-000002` : catastrophe. N'importe qui compte jusqu'à 200 et lit toutes les
commandes de l'année.

```python
import secrets
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # ni O/0, ni I/1/L : on doit pouvoir le dicter au téléphone
def nouveau_numero() -> str:
    return "VELA-" + "".join(secrets.choice(ALPHABET) for _ in range(10))
```

31 caractères puissance 10, soit environ **50 bits** : impossible à deviner, et court assez pour
être lu à voix haute. Le gabarit `VELA-XXXXXXXX` est déjà affiché comme exemple dans le champ de
`suivi.html` — si le format change, corriger le `placeholder`.

### 6.2 Le numéro seul ne suffit jamais

Il faut **le couple** (numéro, courriel du paiement). Le numéro est le secret, le courriel est la
preuve que la personne est bien la bonne. Un numéro qui traîne sur une capture d'écran, dans un
courriel transféré ou dans une conversation ne donne rien à lui seul.

Comparaison du courriel : **après normalisation par `base.normaliser()`**, avec
`hmac.compare_digest` — la même fonction que `jeton_valide()` dans `app.py`, pour la même raison.

### 6.3 La réponse est identique dans tous les cas d'échec

Numéro inexistant, numéro existant avec le mauvais courriel, commande annulée : **la même réponse,
`{"trouvee": false}`**, et si possible dans le même temps de réponse.

C'est exactement ce que fait déjà `/api/licence` : « réponse identique pour un courriel inconnu, un
abonnement expiré ou un abonnement résilié ». On applique la même discipline. Sinon, l'écart entre
deux réponses devient un outil : on apprend qu'un numéro existe, puis on cherche le courriel.

### 6.4 Limite de débit

`server/licences/limite.py` fournit déjà `Limiteur` et `adresse_client()`. Il en faut **deux**, et
les deux comptent :

- par **adresse IP**, comme `limiteur_licence` — contre le balayage large ;
- par **numéro de commande**, quelques essais par heure — contre l'attaque ciblée sur un numéro
  connu dont on cherche le courriel.

Au-delà : `429` avec `Retry-After`, comme le fait déjà `/api/licence`.

### 6.5 Ce qui ne doit jamais apparaître dans une URL

- Pas de `suivi.html?commande=VELA-…`. Jamais. Ni maintenant, ni « juste pour le courriel de
  confirmation ».
- Pas de `GET /api/commande/VELA-…`.
- Le courriel de confirmation contient le numéro **en texte**, avec un lien nu vers `suivi.html`.
  La personne recopie ou colle son numéro. C'est un geste de plus ; c'est le prix d'un lien qui ne
  fuit pas quand le courriel est transféré.
- `site/_headers` envoie déjà `Referrer-Policy: strict-origin-when-cross-origin` : rien du chemin ne
  part vers un site tiers. Ça ne dispense pas de la règle ci-dessus, ça la double.

Le JavaScript de `suivi.html` respecte déjà tout ça : il n'écrit ni dans `location`, ni dans
`history`. **À vérifier à chaque modification du bloc.**

### 6.6 Si un jour ça ne suffit plus

Le couple (numéro, courriel) est le bon compromis pour vendre des lunettes à 250 $ : pas de compte à
créer, pas de mot de passe à oublier. Le jour où la page afficherait davantage — une adresse, une
facture, un bouton d'annulation — il faut passer à un cran au-dessus :

1. la personne entre **seulement son courriel** ;
2. le serveur envoie un code à six chiffres **à l'adresse enregistrée**, jamais à celle qui vient
   d'être tapée — c'est là toute la sécurité : taper l'adresse de quelqu'un d'autre ne donne rien,
   le code part chez lui ;
3. le code est stocké **haché** (SHA-256), valable 30 minutes, à usage unique ;
4. une fois validé, un témoin de session `HttpOnly` + `Secure` + `SameSite=Lax`, court.

Table correspondante, à n'ajouter que ce jour-là :

```sql
CREATE TABLE IF NOT EXISTS commande_acces (
    code_hache  TEXT PRIMARY KEY,   -- SHA-256 du code. Le code en clair n'est jamais écrit.
    numero      TEXT NOT NULL,
    courriel    TEXT NOT NULL,
    expire_le   TEXT NOT NULL,
    utilise_le  TEXT,
    cree_le     TEXT NOT NULL
);
```

### 6.7 Conséquence juridique, à ne pas oublier

Le jour où ces tables existent, **VELA conserve des données personnelles sur un serveur** : des
courriels, des états de commande, éventuellement des adresses. `politique-confidentialite.html`
décrit aujourd'hui un logiciel qui garde tout sur l'appareil du client. Ce document devra dire ce
que le serveur de commandes garde, combien de temps, et comment on demande sa suppression. C'est à
ajouter à la liste des points à faire relire par un juriste, à côté du sujet du relais d'IA déjà
signalé dans `site/README.md`.

---

## 7. Alibaba : ce qui est réellement possible

Recherche faite le 4 septembre 2026, dans la documentation publique. Ce qui suit distingue
strictement **ce qui a été lu sur une page**, **ce qui reste incertain**, et **ce qui n'a pas été
trouvé**. Rien n'a été deviné.

### 7.1 Ce qui est confirmé

**Une plateforme développeur existe pour alibaba.com International**, à `openapi.alibaba.com`
(documentation : `openapi.alibaba.com/doc/api.htm` et `/doc/doc.htm`). Elle est **distincte** de
celle d'AliExpress (`openservice.aliexpress.com`) : les deux arbres de documentation ne se
recouvrent pas. La documentation d'AliExpress ne s'applique pas au B2B — c'est une confusion
courante, et elle coûterait des jours de travail.

**Les API de commande ne sont pas réservées aux vendeurs.** La référence sépare explicitement des
groupes « Buyer » et « Seller ». Le groupe **« Buyer — Transaction & Fulfillment »** contient une
seizaine d'opérations, dont quatre nous intéressent directement :

| Opération, telle qu'elle est nommée dans la documentation | Ce qu'elle donne |
|---|---|
| `/alibaba/order/list` | La liste des commandes. Le paramètre `role` est documenté « seller/buyer, default buyer ». Renvoie `trade_id`, `trade_status`, dates de création et de modification. |
| `/alibaba/order/get` | Le détail d'une commande : `trade_status`, `carrier {code, name}`, `shipment_method`, `shipment_date`, pièces jointes portant un `waybill_number`, adresse d'expédition, produits. |
| `/order/logistics/tracking/get` | « Allows partners to track shipment and logistics updates for placed orders. » Renvoie `carrier`, `tracking_number`, une liste d'événements horodatés (`event_name`, `event_location`, `event_time`) et un `tracking_url`. |
| `/order/logistics/query` | Le statut logistique et le numéro de suivi, avec `data_select=logistic_order`. |

**Un webhook existe.** La documentation décrit un message « Order Status Change Notification »
(titre `ICBU ORDER SYNC MESSAGE`), déclenché à la création, au paiement, à l'expédition, à
l'achèvement ou à l'annulation d'une commande. Signature `HMAC-SHA256`, réponse attendue en moins de
500 ms, distribution « au moins une fois » — donc **idempotence obligatoire**, exactement comme pour
les webhooks PayPal, où `base.reserver_evenement()` fait déjà ce travail.

**Le vocabulaire de statuts est documenté** et compte une quinzaine de valeurs (`unpay`, `paid`,
`undeliver`, `delivering`, `wait_confirm_receipt`, `trade_success`, `trade_close`, `charge_back`…).
Il ne correspond pas à nos sept états : il faudra une table de correspondance, écrite à la main, et
tout statut inconnu doit tomber sur `probleme` plutôt que d'être interprété au jugé.

**L'accès passe par une autorisation de l'acheteur (OAuth).** La documentation décrit un parcours où
l'acheteur se connecte avec son compte Alibaba et autorise l'application. Ce serait Miguel qui
autoriserait sa propre application à lire ses propres commandes.

### 7.2 Ce qui n'a pas été trouvé — et c'est précisément ce qu'on cherchait

> **Aucune date de livraison estimée.** Elle n'apparaît dans aucun des exemples de réponse des trois
> opérations de suivi. Ce qui existe, c'est une date d'**expédition** et des **événements
> transporteur horodatés**. La demande de Miguel — « quand il pourrait être livré » — **n'a pas de
> réponse dans cette API**.

Le centre d'aide acheteur d'Alibaba ne fait pas mieux : à la question « When will I receive my
order? », il renvoie l'acheteur vers **le suivi du transporteur** pour l'express, et **vers le
fournisseur lui-même** pour le maritime, le routier et l'aérien. Autrement dit, Alibaba non plus
n'a pas cette date.

N'ont pas non plus été trouvés :

- **un export CSV des commandes** côté acheteur sur la place de marché B2B. ⚠ Attention à un faux
  positif fréquent : les résultats de recherche qui parlent d'« export to CSV » concernent
  **Alibaba Cloud**, un produit totalement différent ;
- **un accès sans application approuvée** : pas de clé personnelle, pas de jeton « lecture seule mes
  commandes ». Tout passe par une application, OAuth et une permission de groupe ;
- **aucune mention de « Trade Assurance » comme condition d'accès à l'API** : le terme ne ressort pas
  du moteur de recherche de la documentation développeur. En revanche les articles d'aide sur le
  suivi de commande parlent de commandes « Trade Assurance », ce qui laisse penser que seul ce qui
  est commandé **sur** la plateforme est suivi — c'est une déduction, pas une phrase lue.

### 7.3 Ce qui reste incertain, et qui décide de tout

**On ne sait pas si un simple acheteur peut obtenir ces permissions.** Le vocabulaire de la
documentation est celui du partenaire d'intégration : « allows **partners** to track… », « sourcing
partners », « channel partners ». Les deux seules catégories d'application documentées —
« Commercial Developer » et « Individual Developer » — sont rédigées du point de vue de **vendeurs**.
Aucune page ne dit qu'un acheteur peut créer une application pour suivre ses propres commandes ; **et
aucune ne dit le contraire.**

Les conditions d'accès, elles, sont documentées, et elles sont lourdes :

1. créer un compte développeur et accepter l'entente de la plateforme ;
2. **remplir un profil et téléverser des documents**, revus et approuvés par une équipe d'Alibaba —
   c'est exigé pour mettre une application en ligne ;
3. **enregistrer une application dans une catégorie**, avec une justification métier écrite, soumise
   à approbation (une seule application par catégorie) ;
4. **demander la permission du groupe d'API** voulu, avec justification. Sans permission, la
   passerelle refuse les appels. La documentation ne dit pas quels groupes sont accordés d'office.

**Ni les délais ni le taux d'approbation ne sont documentés.** C'est donc un dossier administratif
au résultat inconnu, pas une clé qu'on récupère en dix minutes.

### 7.4 Le repli, qui est aussi la recommandation

**Commencer par le repli, pas par l'API.** Il donne l'essentiel du résultat pour un coût presque nul,
et il reste utile même si l'API finit par être accordée.

1. **Miguel recopie le numéro de suivi une seule fois**, dans la page d'administration, le jour de
   l'expédition. Une saisie par commande. C'est le point de bascule de tout le système : avant, on ne
   sait rien ; après, tout devient automatique.
2. **À partir de ce numéro, le suivi transporteur peut être automatisé.** Il existe des services
   agrégateurs multi-transporteurs — **17TRACK** est celui qu'Alibaba recommande lui-même dans son
   centre d'aide pour les envois express ; **AfterShip**, **TrackingMore**, **Ship24** et
   **EasyPost/ShipEngine** existent aussi dans cette catégorie. ⚠ Les nombres de transporteurs pris
   en charge que ces services affichent les uns sur les autres n'ont **pas** été vérifiés à la
   source : ne pas les citer comme des faits, et comparer les tarifs et les conditions au moment du
   choix.
3. **Tant qu'aucun agrégateur n'est branché**, la page affiche le transporteur et le numéro, et c'est
   déjà énorme : le client va voir lui-même sur le site du transporteur. Le champ `suivi_url` de la
   table `commandes` sert exactement à ça.

### 7.5 « De façon invisible pour le client » — la contrainte à ne jamais relâcher

Miguel veut que la plateforme soit reliée à Alibaba **sans que le client le voie**. Ce n'est pas
seulement une question de discrétion commerciale : c'est déjà une règle du site (« Le nom du
fournisseur du matériel n'apparaît nulle part », `site/README.md`), et les photos du produit sont
sous la même réserve.

Trois pièges concrets, le jour où une intégration existera :

- **`reference_fournisseur` ne sort jamais de l'API publique.** Elle est dans la table pour Miguel,
  pas pour le client. Le §5.1 le dit déjà : rien d'autre que l'état, les dates, le transporteur et
  le numéro de suivi ne franchit la frontière.
- **Les événements transporteur sont du texte écrit par quelqu'un d'autre.** Ils peuvent contenir le
  nom de l'expéditeur, une ville d'origine, un nom d'entrepôt. Il faut donc **ne reprendre que les
  champs qu'on a décidé d'afficher** — un état, une date, une ville — et jamais recopier une chaîne
  libre telle quelle sur la page. C'est aussi une règle d'affichage : `site/assets/site.js`
  construit toute la fiche avec `textContent`, jamais avec `innerHTML`.
- **`tracking_url` peut mener à une page qui identifie le fournisseur.** Ne pas la relayer sans
  l'avoir ouverte une fois pour vérifier ce qu'elle montre.

### 7.6 Conclusion pratique

L'API existe, elle est côté acheteur, et elle donnerait le statut, le transporteur, le numéro de
suivi et les événements. Elle ne donnerait **pas** la date de livraison estimée. Son coût n'est pas
technique, il est administratif, et son ouverture à un acheteur ordinaire n'est pas établie.

**Décision proposée :** construire les étapes 1 à 3 du §9 sans Alibaba, avec la saisie manuelle du
numéro de suivi. Puis, quand le volume de commandes le justifiera, créer un compte développeur
Alibaba et **regarder dans la console si le groupe « Buyer — Transaction & Fulfillment » est
accessible** — c'est probablement le seul moyen d'avoir la réponse. Tant que cette vérification n'est
pas faite, ne rien promettre à personne sur cette intégration.

---

## 8. Ce qui restera manuel, honnêtement

« Tout automatisé » est le bon objectif. Voici ce qui, en toute honnêteté, dépendra d'un humain
pendant longtemps. Aucune de ces lignes n'est un oubli : ce sont des endroits où l'information
n'existe nulle part sous forme lisible par une machine.

| Ce qui reste manuel | Pourquoi | Peut-on l'éliminer ? |
|---|---|---|
| Demander la monture et l'adresse | `paypal.me` ne les collecte pas | **Oui** — bouton PayPal Business avec adresse de livraison. C'est le seul changement qui supprime un aller-retour de courriels par commande. |
| Passer la commande à l'atelier | Quelqu'un doit commander | Non, à court terme |
| Saisir « commande passée au fournisseur » | Personne d'autre ne le sait | Non |
| Recopier le numéro de suivi | Il arrive par courriel ou dans une interface | Partiellement (§7) — mais c'est **une seule saisie par commande**, et elle débloque tout le reste |
| Décider qu'il y a un problème | C'est un jugement | Non, et c'est très bien |
| Annuler et rembourser | Se fait chez PayPal | Non |
| Faire correspondre commande VELA ↔ commande fournisseur | Deux systèmes qui ne se connaissent pas | Non, sans intégration |
| Douanes, taxes, retours | Cas par cas | Non |

En face, ce qui **peut être automatisé dès le premier jour**, sans dépendre de personne :

- créer la commande et attribuer son numéro à la réception du webhook ;
- envoyer au client le courriel qui porte ce numéro (`Facteur` sait déjà envoyer) ;
- afficher l'état sur `suivi.html` ;
- prévenir le client par courriel à chaque changement d'état ;
- prévenir Miguel quand un paiement arrive sans commande possible (déjà fait par `Facteur.alerter()`).

Ce n'est pas rien : c'est la moitié du travail de correspondance qui disparaît, et le client cesse
d'être dans le noir.

---

## 9. L'ordre dans lequel construire

**Étape 0 — le prérequis absolu.** Sans **compte PayPal Business** et sans webhook configuré,
**aucun événement n'arrive**, et tout le reste de ce document est décoratif. `server/README.md` le
dit déjà pour les abonnements ; c'est identique pour les commandes. Rien ne sert de coder avant.

**Étape 1 — la commande naît toute seule.** Tables dans `base.py`, `MATERIEL` dans `montants.py`,
branche « matériel » dans `_crediter()`, gabarit de courriel dans `courriel.py`. À la fin de cette
étape, un client qui paie reçoit un numéro de commande sans que personne ne fasse rien.

**Étape 2 — le client peut regarder.** `POST /api/commande/suivi`, la limite de débit, la réponse
neutre. Puis, côté site : `ADRESSE_SUIVI`, `connect-src`, CORS. `suivi.html` n'a pas besoin d'être
retouchée.

**Étape 3 — Miguel peut mettre à jour.** `POST /admin/commande/etat` et le tableau « Commandes »
dans `_page_admin()`. À la fin de cette étape, le système fait tout ce qu'il peut honnêtement faire
sans intégration extérieure.

**Étape 4 — plus tard, si le volume le justifie.** Suivi transporteur automatique, intégration
fournisseur, code par courriel du §6.6.

Les étapes 1 à 3 sont petites. Le vrai travail, c'est l'étape 0, et elle ne se code pas.

---

## 10. Ce que Miguel doit décider ou fournir

1. **Ouvrir un compte PayPal Business et configurer le webhook.** Sans ça, rien. Bloque tout.
2. **Remplacer les liens `paypal.me` par un vrai bouton de paiement**, ou accepter que l'adresse de
   livraison continue d'arriver par courriel. C'est la décision la plus structurante : elle
   détermine si le parcours peut être automatisé ou s'il restera à moitié humain.
3. **Le délai à annoncer.** `merci.html` n'affiche aucun délai de réponse, parce qu'aucun n'a été
   fixé. Si Miguel s'engage sur « une réponse sous 24 h ouvrables », il faut l'écrire ; sinon il
   vaut mieux continuer à ne rien promettre.
4. **La politique de retour et le délai de livraison** — déjà dans la liste de `site/README.md`, et
   le droit québécois de la consommation en impose une part.
5. **L'adresse du service de licences** (`licences.vela.app` ou autre), pour `ADRESSE_SUIVI`,
   `connect-src` et CORS.
6. **Combien de temps garder une commande** après livraison, et ce que dit la politique de
   confidentialité à ce sujet.
7. **Le format du numéro de commande**, s'il n'aime pas `VELA-XXXXXXXXXX`. Il doit rester
   imprévisible et dictable au téléphone.
8. **Ce qu'il veut voir sur la page de suivi**, au-delà de l'état : ce document propose le minimum
   (état, dates, transporteur, numéro de suivi). Tout ajout demande de reprendre le §6.
9. **La seule question qui reste ouverte sur Alibaba** (§7.3) : un acheteur peut-il obtenir la
   permission du groupe « Buyer — Transaction & Fulfillment » ? La documentation ne le dit ni dans un
   sens ni dans l'autre. Y répondre demande de créer un compte développeur sur `openapi.alibaba.com`
   et de regarder la console. **À faire quand le volume le justifiera, pas avant** — et ne rien
   promettre entre-temps.

---

## 11. Ce que le site fait aujourd'hui, exactement

Pour qu'on ne se trompe pas sur l'état réel des choses en relisant ce document dans six mois :

- `site/suivi.html` existe, est reliée depuis l'accueil, la fiche produit et le pied de page de
  toutes les pages. Elle **n'appelle aucun serveur** et n'affiche **aucune commande**. Elle explique
  les états et renvoie vers le courriel.
- `site/merci.html` existe et explique la suite du paiement. Elle **n'est pas atteinte par une
  redirection** : `paypal.me` ne redirige pas. On y arrive par les liens posés sur l'accueil et sur
  `lunettes.html`.
- `site/assets/site.js` porte le bloc « suivi de commande », inerte tant que `ADRESSE_SUIVI` est
  vide.
- Le serveur de licences **ne connaît pas la notion de commande**. Un paiement de 250 $ y produit
  une ligne dans la table `manuel` et une alerte par courriel.
