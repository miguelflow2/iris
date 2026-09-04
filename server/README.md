# Serveur de licences VELA

Le service en ligne qui reçoit les paiements PayPal et active tout seul l'abonnement du client
dans IRIS. Il remplace le parcours actuel — le client paie sur `paypal.me`, envoie son reçu par
courriel, Miguel génère une clé à la main et la renvoie.

**Ce qui marche aujourd'hui, sans compte PayPal Business :** tout, sauf recevoir de vrais
paiements. Le service tourne, traite des webhooks, crée des abonnements, génère des clés valides,
les envoie par courriel, et répond à IRIS. On peut le prouver : `55 tests passent`.

**Ce qui ne peut pas marcher tant que le compte PayPal Business n'existe pas :** PayPal n'envoie
aucun webhook pour un paiement `paypal.me`. Il n'y a aucun contournement — pas d'API, pas de
notification, rien à interroger. Le service est prêt à recevoir, mais personne n'envoie encore.
La partie « ce que Miguel doit faire » plus bas est la seule voie.

---

## Table des matières

1. [Démarrer en cinq minutes](#1-démarrer-en-cinq-minutes)
2. [Les points d'entrée](#2-les-points-dentrée)
3. [Ce que Miguel doit faire chez PayPal](#3-ce-que-miguel-doit-faire-chez-paypal)
4. [Héberger le service](#4-héberger-le-service)
5. [Tester avec le bac à sable PayPal](#5-tester-avec-le-bac-à-sable-paypal)
6. [Le secret HMAC](#6-le-secret-hmac)
7. [Passer du manuel à l'automatique sans casser les clés déjà émises](#7-passer-du-manuel-à-lautomatique-sans-casser-les-clés-déjà-émises)
8. [Sécurité](#8-sécurité)
9. [Ce que le service ne fait pas](#9-ce-que-le-service-ne-fait-pas)
10. [Dépannage](#10-dépannage)

---

## 1. Démarrer en cinq minutes

Depuis `iris\server\` (PowerShell) :

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.exemple .env
```

Ouvrez `.env` et mettez, pour un essai local :

```
IRIS_ENV=developpement
IRIS_WEBHOOK_SANS_VERIFICATION=1
IRIS_JETON_ADMIN=un-jeton-au-hasard-que-vous-choisissez
```

Puis lancez :

```powershell
.venv\Scripts\python -m licences --port 8099
```

Envoyez-vous un faux paiement (PowerShell) :

```powershell
$corps = '{"id":"WH-ESSAI-1","event_type":"PAYMENT.CAPTURE.COMPLETED","resource":{"id":"CAP-1","amount":{"currency_code":"CAD","value":"29.99"},"payer":{"email_address":"vous@exemple.com"}}}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8099/paypal/webhook -Body $corps -ContentType application/json
Invoke-RestMethod -Uri "http://127.0.0.1:8099/api/licence?email=vous@exemple.com"
```

Vous obtenez une clé `IRIS-…`. Collez-la dans IRIS › Abonnement : elle s'active.
Le courriel qui contient cette clé est déposé dans `server\sortie\` (SMTP n'est pas configuré).
La page d'administration est sur `http://127.0.0.1:8099/admin?jeton=votre-jeton`.

**`IRIS_WEBHOOK_SANS_VERIFICATION=1` sert uniquement à cet essai.** Le service refuse de démarrer
si vous le laissez à 1 avec `IRIS_ENV=production`.

Lancer les tests :

```powershell
.venv\Scripts\python -m pytest
```

---

## 2. Les points d'entrée

| Route | Rôle |
|---|---|
| `POST /paypal/webhook` | Reçoit les événements PayPal. Vérifie la signature auprès de PayPal, puis crée ou prolonge l'abonnement, génère la clé et l'envoie. Signature invalide → `400`, rien en base. PayPal injoignable → `503`, pour que PayPal relance. |
| `GET /api/licence?email=…` | Ce qu'IRIS interroge pour s'activer toute seule. Renvoie `{actif, plan, expire_le, cle}`. Limité en débit par IP ; réponse identique pour un courriel inconnu, expiré ou résilié. |
| `POST /api/licence/verifier` | `{"cle": "IRIS-…"}` → `{valide, plan, expire_le}` ou `{valide: false, raison}`. Vérification purement cryptographique. |
| `GET /sante` | État du service : PayPal configuré ou non, signature vérifiée ou non, mode d'envoi des courriels, nombre d'abonnements actifs, dossiers à traiter. Aucun secret. |
| `GET /admin` | Page d'administration (jeton obligatoire) : abonnements, dossiers à traiter, 50 derniers événements. |
| `POST /admin/emettre` | Émet une clé à la main : virement, comptant, geste commercial, clé perdue. **Le filet de sécurité indispensable.** |
| `POST /admin/resoudre` | Marque un dossier « à traiter manuellement » comme réglé. |

### Événements PayPal traités

| Événement | Effet |
|---|---|
| `PAYMENT.CAPTURE.COMPLETED` | Versement unique : plan activé ou prolongé, clé envoyée. |
| `BILLING.SUBSCRIPTION.ACTIVATED` | Abonnement récurrent démarré ou reconduit : idem, plus l'identifiant `I-…` enregistré. |
| `BILLING.SUBSCRIPTION.CANCELLED` | Statut → `annule`. **Le client garde ce qu'il a payé** : sa clé reste valable jusqu'à son échéance, mais rien ne sera renouvelé. |
| `BILLING.SUBSCRIPTION.EXPIRED` | Statut → `expire`. `/api/licence` répond « aucun abonnement ». |
| `BILLING.SUBSCRIPTION.PAYMENT.FAILED` | Statut → `paiement_echoue`. L'accès reste ouvert jusqu'à l'échéance déjà payée. |

Tout autre type est journalisé puis ignoré.

### Montants reconnus

| Montant (CAD) | Plan | Durée |
|---|---|---|
| 19,99 | Essentiel | 1 mois |
| 29,99 | Pro | 1 mois |
| 99,99 | Ultra | 1 mois |
| 839,00 | Pro (offre groupée lunettes VELA) | 12 mois |

Tolérance de 5 ¢ (réglable). **Un montant inconnu n'active jamais rien** : il crée un dossier
« à traiter manuellement », visible dans `/admin`, et une alerte part par courriel. Une devise
absente de `IRIS_DEVISES` (CAD par défaut) fait la même chose : 19,99 USD n'est pas 19,99 CAD, et
le service ne devine pas.

### Idempotence

PayPal relance un webhook s'il n'obtient pas de réponse claire — c'est normal et fréquent.
Chaque événement est **posé en base avant tout crédit**, avec deux contraintes d'unicité
(identifiant d'événement et identifiant de transaction). Le même paiement reçu deux fois ne
crédite jamais deux mois. C'est une écriture atomique, pas une lecture suivie d'une écriture :
deux webhooks arrivant en même temps ne peuvent pas passer tous les deux.

---

## 3. Ce que Miguel doit faire chez PayPal

Rien de tout cela ne peut être fait à votre place : il faut votre identité, vos coordonnées
bancaires et votre acceptation des conditions de PayPal.

### 3.1 Ouvrir un compte PayPal Business

1. Allez sur <https://www.paypal.com/ca/business> et cliquez sur **Ouvrir un compte Business**.
   Si vous avez déjà un compte personnel, vous pouvez le convertir ou en créer un second.
2. Fournissez : nom légal de l'entreprise (ou votre nom si vous êtes travailleur autonome),
   adresse, numéro de téléphone, secteur d'activité, site web.
3. Reliez votre compte bancaire et confirmez-le (PayPal fait deux petits dépôts à vérifier :
   comptez deux à trois jours ouvrables).
4. Confirmez votre adresse courriel.

Sans compte confirmé, PayPal plafonne les retraits. Faites-le en premier, l'attente bancaire est
le seul délai incompressible.

### 3.2 Créer l'application (identifiant et secret)

1. Allez sur <https://developer.paypal.com/dashboard/> et connectez-vous avec le compte Business.
2. **Apps & Credentials**, bascule **Sandbox** (bac à sable) en haut à droite pour commencer.
3. **Create App** → nom : `IRIS Licences` → type **Merchant** → **Create App**.
4. Notez le **Client ID** et, en cliquant sur **Show**, le **Secret**.
   → ce sont `PAYPAL_CLIENT_ID` et `PAYPAL_SECRET` dans votre `.env`.
5. Plus tard, refaites exactement la même chose en bascule **Live** : les identifiants Live sont
   **différents** de ceux du bac à sable.

**Le secret ne se réaffiche pas toujours.** Copiez-le tout de suite dans un gestionnaire de mots
de passe. Ne l'envoyez jamais par courriel ni par message.

### 3.3 Créer les produits et les plans d'abonnement

C'est ce qui rend le renouvellement automatique. Un paiement `paypal.me` ne se renouvelle pas ;
un abonnement PayPal, oui.

1. Toujours dans le tableau de bord développeur, section **Subscriptions** (ou depuis le compte
   Business : **Payer et être payé** › **Abonnements**).
2. Créez un **produit** : nom `IRIS`, type **Service**, catégorie **Software**.
3. Créez **trois plans** rattachés à ce produit :

   | Nom du plan | Prix | Cycle | Devise |
   |---|---|---|---|
   | IRIS Essentiel | 19,99 | mensuel, sans fin | CAD |
   | IRIS Pro | 29,99 | mensuel, sans fin | CAD |
   | IRIS Ultra | 99,99 | mensuel, sans fin | CAD |

4. Notez les identifiants de plan (`P-…`). Ils serviront aux boutons d'abonnement du site.
5. L'offre groupée à 839 $ (lunettes + 12 mois Pro) n'est **pas** un abonnement : c'est un
   paiement unique. Le service la reconnaît par son montant et crédite 12 mois de Pro.

### 3.4 Créer le webhook

C'est le lien entre PayPal et votre service.

1. Tableau de bord développeur › **Apps & Credentials** › votre application `IRIS Licences`.
2. Descendez à **Webhooks** → **Add Webhook**.
3. **Webhook URL** : l'adresse publique HTTPS de votre service, suivie de `/paypal/webhook`.
   Exemple : `https://licences-vela.onrender.com/paypal/webhook`.
   PayPal **exige** HTTPS et refuse `localhost` (voir §4 pour obtenir une adresse publique).
4. Cochez exactement ces cinq événements :
   - `PAYMENT.CAPTURE.COMPLETED`
   - `BILLING.SUBSCRIPTION.ACTIVATED`
   - `BILLING.SUBSCRIPTION.CANCELLED`
   - `BILLING.SUBSCRIPTION.EXPIRED`
   - `BILLING.SUBSCRIPTION.PAYMENT.FAILED`
5. **Save**. PayPal affiche un **Webhook ID** de la forme `WH-…`.
   → c'est `PAYPAL_WEBHOOK_ID` dans votre `.env`.

**Sans ce Webhook ID, aucune signature ne peut être vérifiée**, et le service refusera tous les
webhooks. Ce n'est pas un détail optionnel : c'est ce qui empêche n'importe qui de s'offrir un
abonnement Ultra en envoyant un faux paiement à votre adresse publique.

### 3.5 Transmettre le courriel du client

Pour un **abonnement**, PayPal envoie l'adresse du client dans `subscriber.email_address` : rien
à faire.

Pour un **paiement unique**, PayPal ne la transmet pas toujours. Quand vous créerez le bouton de
paiement sur le site VELA, remplissez le champ `custom_id` avec l'adresse courriel saisie par le
client. Le service la lit à cet endroit. Sans elle, le paiement part en traitement manuel — rien
n'est perdu, mais il faut intervenir.

---

## 4. Héberger le service

Le service a besoin d'une adresse publique en HTTPS, et d'un disque qui survit aux
redéploiements (la base contient les abonnements de vos clients).

### Option recommandée : Render

Gratuit pour commencer, HTTPS automatique, pas de carte requise pour le palier gratuit.
**Attention au palier gratuit** : l'instance s'endort après 15 minutes d'inactivité et met ~30 s à
se réveiller. PayPal relance ses webhooks, donc rien n'est perdu, mais un client qui vient de payer
attendra sa clé. Le palier payant (7 $ US/mois) supprime la mise en veille et donne un disque
persistant : **c'est ce qu'il faut dès le premier vrai client.**

1. Poussez le dépôt sur GitHub (le `.gitignore` exclut déjà `.env`, la base et `sortie/`).
2. Sur <https://render.com>, **New** → **Web Service** → reliez le dépôt.
3. Réglages :
   - **Root Directory** : `server`
   - **Runtime** : Python 3
   - **Build Command** : `pip install -r requirements.txt`
   - **Start Command** : `uvicorn licences.app:creer_app --factory --host 0.0.0.0 --port $PORT`
4. **Environment** : ajoutez une à une les variables de `.env.exemple`. **Ne téléversez pas le
   fichier `.env`** : ces valeurs se saisissent dans l'interface de Render.
5. **Disks** : ajoutez un disque de 1 Go monté sur `/var/data`, puis mettez
   `IRIS_BASE=/var/data/licences.db` et `IRIS_SORTIE=/var/data/sortie`.
   **Sans disque, la base est effacée à chaque redéploiement** — tous les abonnements avec.
6. Déployez. Votre adresse est `https://<nom>.onrender.com`. Vérifiez `https://<nom>.onrender.com/sante`.
7. Reportez cette adresse dans le webhook PayPal (§3.4).

### Autres options

- **Fly.io** — un peu plus technique (`fly launch`, `fly volumes create`), pas de mise en veille,
  environ 2 $ US/mois pour la plus petite machine. Le meilleur rapport qualité-prix si vous êtes
  à l'aise en ligne de commande.
- **Railway** — le plus simple des trois, environ 5 $ US/mois, volume persistant en deux clics.

Dans tous les cas : `IRIS_ENV=production`, `IRIS_WEBHOOK_SANS_VERIFICATION` absent ou à `0`, et
les trois variables PayPal remplies. Le service **refuse de démarrer** sinon — c'est voulu.

### Courriels

Sans SMTP, les clés sont écrites dans `sortie/` et il faut les envoyer à la main : ça marche, mais
ça ne tient pas la charge. Pour Gmail :

```
IRIS_SMTP_HOTE=smtp.gmail.com
IRIS_SMTP_PORT=587
IRIS_SMTP_UTILISATEUR=miguelfreddy65@gmail.com
IRIS_SMTP_MOTDEPASSE=<mot de passe d'application, 16 caractères>
```

Le mot de passe d'application se crée dans <https://myaccount.google.com/apppasswords> (la
validation en deux étapes doit être active). **Ce n'est pas le mot de passe de votre compte** :
Google refuse celui-ci depuis 2022. Au-delà d'une centaine de courriels par jour, passez à un
service d'envoi (Brevo, Resend, Postmark), Gmail limitant les envois automatisés.

---

## 5. Tester avec le bac à sable PayPal

Le bac à sable rejoue tout le parcours avec de faux comptes et de faux dollars.

1. <https://developer.paypal.com/dashboard/accounts> : PayPal a déjà créé un compte marchand et un
   compte acheteur. Notez le courriel et le mot de passe du compte **Personal** (l'acheteur).
2. Déployez le service avec `PAYPAL_ENV=sandbox` et les identifiants **Sandbox** (§3.2).
3. Créez le webhook (§3.4) en bascule **Sandbox**, pointant sur votre adresse publique.
4. Dans **Apps & Credentials** › votre application › **Webhooks** › **Webhook simulator** :
   choisissez `PAYMENT.CAPTURE.COMPLETED` et envoyez. Le simulateur signe vraiment l'événement :
   c'est le test qui prouve que la vérification de signature fonctionne.
5. Vérifiez `/admin` : l'événement doit apparaître. Le montant du simulateur ne correspondra
   probablement à aucun plan, donc il partira en « à traiter manuellement » — c'est le
   comportement correct, et cela prouve qu'un montant inconnu n'offre rien.
6. Pour un test complet, créez un bouton d'abonnement avec un plan sandbox, payez avec le compte
   acheteur du bac à sable, et regardez la clé arriver.
7. Quand tout marche : rebasculez en **Live**, recréez l'application et le webhook côté Live,
   remplacez les trois variables, mettez `PAYPAL_ENV=live` et `IRIS_ENV=production`, redéployez.
   **Faites un vrai achat à 19,99 $ avec votre propre carte** avant d'annoncer quoi que ce soit.

---

## 6. Le secret HMAC

Les clés `IRIS-…` sont signées avec un secret partagé. Aujourd'hui, ce secret est **écrit en dur
dans le code de l'application** :

```python
# backend/iris/plans.py, ligne 36
LICENSE_SECRET = b"VELA-IRIS-2026-license-v1"
```

Le serveur de licences reprend cette valeur par défaut, pour que les clés qu'il émet soient
reconnues par toutes les installations déjà distribuées.

**Le problème.** Ce secret est dans l'application installée chez chaque client. Quiconque ouvre
le fichier peut fabriquer ses propres clés Ultra. Tant que la distribution est contrôlée, c'est
un risque accepté ; à grande échelle, non.

**La transition, sans invalider une seule clé déjà émise :**

1. Choisissez un nouveau secret : `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
2. Dans `backend/iris/plans.py`, remplacez la ligne en dur par une lecture d'environnement **avec
   repli sur l'ancienne valeur** :
   ```python
   LICENSE_SECRET = (os.environ.get("IRIS_LICENSE_SECRET") or "VELA-IRIS-2026-license-v1").encode()
   ```
   Tant que la variable n'est pas définie chez le client, ses clés actuelles continuent de
   fonctionner. Rien ne casse.
3. Mettez le nouveau secret dans `IRIS_LICENSE_SECRET` **sur le serveur** — et nulle part ailleurs
   pour l'instant. Les nouvelles clés seront signées avec lui.
4. Pour que l'application les accepte, il faut qu'elle connaisse aussi le nouveau secret. Deux
   voies :
   - **La bonne** : l'application cesse de vérifier les clés elle-même et interroge
     `GET /api/licence`. Le secret ne quitte alors jamais le serveur. C'est l'objectif.
   - **La transitoire** : `verify_key()` essaie les deux secrets, l'ancien et le nouveau, et le
     nouveau part avec la prochaine mise à jour de l'application. Les clés restent falsifiables,
     mais la rotation est possible.
5. Ne changez le secret du serveur **qu'après** que les clients aient la version qui l'accepte.
   Sinon, toutes les clés émises entre-temps seront rejetées.

**En résumé :** ne touchez à rien tant qu'IRIS n'interroge pas `/api/licence`. Le repli sur le
secret historique est ce qui vous permet de déployer le serveur aujourd'hui sans rien casser.

---

## 7. Passer du manuel à l'automatique sans casser les clés déjà émises

Les clés déjà distribuées restent valides : **le serveur utilise le même secret et le même format,
octet pour octet** (deux tests le vérifient contre le vrai `plans.py`). Vous ne devez rien
reprendre, rien réémettre, ne prévenir personne.

Ordre conseillé :

1. **Déployez le service** (§4) avec le secret historique. Il ne reçoit encore aucun paiement :
   il ne peut rien casser.
2. **Recopiez vos clients actuels** dans `/admin` › « Émettre une clé à la main », avec leur plan
   et le nombre de mois restants. Ils reçoivent une clé identique à celle qu'ils ont déjà — ou
   vous décochez l'envoi si vous préférez ne pas les déranger. À partir de là, `/api/licence`
   les connaît.
3. **Branchez PayPal** (§3) en bac à sable, puis en Live. Les nouveaux paiements deviennent
   automatiques. Les anciens clients continuent avec leur clé collée à la main.
4. **Faites appeler `/api/licence` par IRIS** au démarrage : l'application s'active alors toute
   seule à partir du courriel du client, et un renouvellement n'exige plus aucun copier-coller.
   *(Cette partie est dans l'application, pas dans ce dossier.)*
5. **Gardez `paypal.me` en parallèle** quelques semaines. Un client qui paie par l'ancien lien
   n'active rien tout seul — vous le voyez dans vos courriels et vous émettez sa clé dans
   `/admin` en dix secondes. Retirez le lien du site quand les boutons d'abonnement marchent.

La page d'administration reste utile après la transition : virements Interac, paiements comptant,
gestes commerciaux, clé perdue. **Ne la supprimez pas.**

---

## 8. Sécurité

- **Aucun secret en dur.** Identifiants PayPal, secret HMAC, jeton d'administration et réglages
  SMTP viennent tous de variables d'environnement. `.gitignore` exclut `.env`, `*.db` et `sortie/`.
- **Signature vérifiée auprès de PayPal** à chaque webhook. Le mode qui saute cette vérification
  est explicite, désactivé par défaut, et le service **refuse de démarrer** s'il est activé en
  production. Sans identifiants PayPal, les webhooks sont refusés plutôt que crus sur parole.
- **Panne réseau ≠ signature invalide.** Une signature refusée donne `400` (PayPal abandonne) ;
  une API injoignable donne `503` (PayPal relance). Confondre les deux ferait perdre des paiements.
- **Anti-énumération** sur `/api/licence` : limite de débit par IP, et réponse strictement
  identique pour un courriel inconnu, expiré ou résilié. La réponse ne contient que
  `{actif, plan, expire_le, cle}` — ni identifiant PayPal, ni montant, ni historique.
- **Administration** protégée par un jeton comparé en temps constant, désactivée si le jeton n'est
  pas configuré, et la page porte `noindex`.
  *Réserve à connaître* : ouvrir `/admin?jeton=…` met le jeton dans l'URL, donc potentiellement
  dans les journaux d'accès de l'hébergeur et dans votre historique de navigation. Le jeton est
  aussi accepté dans l'en-tête `X-Jeton-Admin`, ce qui ne laisse aucune trace ; utilisez-le si vous
  scriptez l'accès. Pour un usage au navigateur, l'URL reste le seul moyen pratique — traitez ce
  jeton comme un mot de passe et changez-le si vous le partagez par erreur.
- **Journalisation** : aucun jeton, aucune signature, aucune donnée de carte n'est écrite dans les
  journaux. PayPal ne transmet d'ailleurs aucun numéro de carte dans ses webhooks. La clé n'est
  jamais renvoyée à PayPal dans la réponse au webhook.
- **Le dossier `sortie/` contient des clés valides.** Il est exclu de git ; ne le partagez pas.

À savoir : la limite de débit vit en mémoire dans le processus. Avec plusieurs instances, chacune
a son compteur. C'est suffisant à l'échelle visée ; au-delà, il faudra un magasin partagé.

---

## 9. Ce que le service ne fait pas

- **Il ne reçoit rien de `paypal.me`.** Aucun webhook, aucune API. Le compte Business est
  obligatoire, et c'est la raison d'être de toute la section 3.
- **Il ne crée pas les plans d'abonnement chez PayPal.** À faire à la main dans le tableau de bord
  (§3.3).
- **Il ne fait pas de remboursement**, ne traite pas les litiges, ne gère pas les
  `PAYMENT.CAPTURE.REFUNDED` ni les rétrofacturations. Un remboursement laisse l'abonnement actif :
  à corriger à la main dans `/admin`.
- **Il ne facture rien, n'émet aucun reçu**, ne calcule aucune taxe (TPS/TVQ). Pour vendre au
  Québec, ce point est à régler séparément — parlez-en à un comptable.
- **Il n'empêche pas le partage de clé.** Une clé peut être collée sur plusieurs machines : le
  format ne porte aucun identifiant d'appareil. Le compter exigerait une activation en ligne.
- **Il ne compte pas l'usage** (quotas de requêtes, caractères de voix). Ces compteurs restent
  locaux dans IRIS et sont remis à zéro par une réinstallation.
- **Il n'a pas d'authentification client.** `/api/licence` ne demande qu'un courriel : qui connaît
  l'adresse d'un client peut obtenir sa clé. Les limites de débit gênent l'énumération, elles ne
  remplacent pas un mot de passe. Pour aller plus loin, il faudra un vrai compte client.
- **Il n'envoie pas de rappel avant l'échéance.** Un client dont l'abonnement se termine n'est
  prévenu par rien. Pour les abonnements récurrents, PayPal reconduit tout seul ; pour les
  paiements uniques, surveillez la colonne « Expire le » dans `/admin`.
- **Il ne sauvegarde pas la base.** Copiez `licences.db` régulièrement : elle contient tous vos
  clients.

---

## 10. Dépannage

| Symptôme | Cause probable |
|---|---|
| Le service refuse de démarrer, « Configuration refusée » | `IRIS_ENV=production` avec `IRIS_WEBHOOK_SANS_VERIFICATION=1`, ou variables PayPal manquantes. C'est le garde-fou. |
| Tous les webhooks reçoivent `400` | `PAYPAL_WEBHOOK_ID` absent ou faux, ou identifiants Sandbox utilisés en Live (ou l'inverse). Vérifiez `/sante`. |
| Webhooks en `503` | PayPal injoignable, ou `PAYPAL_ENV` ne correspond pas aux identifiants. PayPal relancera. |
| Le client paie, rien ne se passe | Regardez `/admin` : si l'événement est en « à traiter manuellement », c'est un montant, une devise ou un courriel manquant. Si l'événement n'apparaît pas du tout, PayPal n'a rien envoyé : vérifiez l'adresse du webhook. |
| La clé est refusée par IRIS | Le secret du serveur diffère de celui de l'application. Videz `IRIS_LICENSE_SECRET` pour revenir au secret historique (§6). |
| Les abonnements disparaissent après un déploiement | La base n'est pas sur un disque persistant. Voir §4, étape 5. |
| Aucun courriel n'arrive | SMTP non configuré : les messages sont dans `sortie/`. Avec Gmail, vérifiez que c'est bien un *mot de passe d'application*. |
| `429` sur `/api/licence` | Limite de débit atteinte. Ajustez `IRIS_LIMITE_LICENCE`, mais ne la supprimez pas. |
