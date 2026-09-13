# Héberger le relais IA de VELA sur Render (gratuit, sans carte)

But : mettre **le relais** (le cerveau que l'app des clients appelle pour l'IA) en ligne 24/7, sans
carte de crédit ni pièce d'identité. Render déploie **depuis GitHub** ; on garde le domaine
`relais.velaglass.ca`, on change juste vers quoi il pointe.

Ce qu'on déploie : **le relais seulement**. Il répond aussi à `/api/licence` en repli, donc les
vérifications de licence marchent. Le serveur de licences séparé (webhooks de paiement) n'est utile
qu'une fois les paiements ouverts, et un 2ᵉ service dépasserait les 750 h/mois gratuites.

---

## Phase 0 — Pousser le code à jour sur GitHub

Render sert **ce qui est sur GitHub**. Les correctifs récents du relais sont commités localement ;
il faut les pousser (l'action est déjà préparée, il reste à envoyer) :
```bash
git push
```

---

## Phase 1 — Créer le service sur Render

1. Va sur <https://render.com> › **Get Started** › connecte-toi **avec GitHub** (gratuit, pas de carte).
2. Autorise Render à voir le dépôt `miguelflow2/iris`.
3. **New › Blueprint** › choisis `miguelflow2/iris`. Render lit `render.yaml` et propose le service
   `vela-relais`.
4. Il te demande de **coller les clés** (marquées `sync:false`) — utilise des clés **fraîches** :
   - `VELA_ANTHROPIC_KEY`
   - `VELA_OPENROUTER_KEY`
   - `VELA_SECRET` (un secret long au hasard)
   - `VELA_ELEVENLABS_KEY` (facultatif)
5. **Apply / Create**. Render installe et démarre. Quand c'est vert, teste l'URL fournie
   (`https://vela-relais-XXXX.onrender.com/sante`) → doit répondre `{ok, amont, voix}`.

> Pas de Blueprint ? Fais **New › Web Service** › dépôt iris, puis à la main :
> **Root Directory** = `serveur` · **Build** = `pip install -r requirements.txt` ·
> **Start** = `uvicorn relais:app --host 0.0.0.0 --port $PORT` · **Plan** = Free, puis ajoute les
> variables ci-dessus.

---

## Phase 2 — Faire pointer relais.velaglass.ca vers Render

1. Dans Render : le service › **Settings › Custom Domains › Add** › `relais.velaglass.ca`.
   Render affiche une **cible CNAME** (ex. `vela-relais-XXXX.onrender.com`). Copie-la exactement.
2. Dans **Cloudflare** (DNS de velaglass.ca) : ouvre l'enregistrement `relais`.
   - Type **CNAME**, cible = la valeur donnée par Render.
   - ⚠️ **Nuage GRIS (DNS only)**, pas orange — pour que Render vérifie le domaine et émette son
     certificat proprement.
   - Enregistre. Render passe le domaine en « Verified » puis « Certificate issued » (quelques min).
3. **Coupe le tunnel du PC pour le relais** (il n'est plus la source) — sur le PC (PowerShell) :
   ```powershell
   Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
   Remove-Item "$HOME\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\lancer-tunnel.vbs" -ErrorAction SilentlyContinue
   ```

L'app des clients pointe déjà vers `relais.velaglass.ca` : **aucun changement dans l'app**, le
backend a juste déménagé.

---

## Phase 3 — Vérifier + garder le service éveillé

1. **Depuis ton téléphone / un autre réseau** :
   ```
   https://relais.velaglass.ca/sante
   ```
   Doit répondre `{ok:true, ...}` en HTTPS.
2. **Garder éveillé** : le niveau gratuit de Render **endort** le service après 15 min d'inactivité
   (1er appel suivant ~40 s). Crée un moniteur gratuit [UptimeRobot](https://uptimerobot.com) (HTTP,
   sans carte) qui frappe `https://relais.velaglass.ca/sante` **toutes les 5 min** → il reste chaud,
   et tu es alerté si le brain tombe.

---

## À savoir (honnête)

- **Réveil à froid** : malgré le ping, si Render endort quand même, le tout premier appel après une
  longue pause peut prendre ~40 s. Acceptable pour le pilote.
- **750 h/mois gratuites** : suffisant pour UN service 24/7 (le relais). C'est pourquoi on ne met pas
  le serveur de licences ici pour l'instant.
- **Disque éphémère** : Render remet le disque à zéro à chaque redéploiement → les compteurs de quota
  du relais repartent de zéro. Sans conséquence pour le pilote (les quotas se re-remplissent).
- **Ça ne débloque pas l'encaissement** : recevoir l'argent reste soumis au KYC (pièce d'identité) ;
  c'est indépendant de l'hébergement du cerveau.

Fichiers liés : `render.yaml` (racine du dépôt).
