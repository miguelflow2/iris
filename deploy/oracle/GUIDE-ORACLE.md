# Déployer le cerveau de VELA sur une VM Oracle (gratuit, 24/7)

But : faire tourner **le relais IA** (et le serveur de licences) en permanence sur une machine
Oracle Cloud « Always Free », et y **déménager le tunnel Cloudflare existant** — sans rien
recréer côté DNS. Le tunnel tiendra enfin, parce que le réseau de la VM n'est pas filtré comme
ton WiFi actuel.

Principe clé : **aucun port entrant n'est ouvert**. `cloudflared` sort de la VM vers Cloudflare
(connexion sortante), et route vers `localhost:8100` (relais) et `localhost:8110` (licences).

---

## Phase 0 — Avant de commencer (sur ton PC)

1. **Une carte** (crédit ou débit). Oracle fait une **empreinte temporaire de ~1 $** pour vérifier
   l'identité ; **rien n'est débité** tant que tu ne passes pas volontairement en payant.
   *(Réf. [docs Oracle Free Tier](https://docs.oracle.com/iaas/Content/FreeTier/freetier.htm).)*

2. **Secrets à rafraîchir.** Si une clé a déjà circulé dans une conversation (ex. la clé Stripe
   `sk_live`), considère-la **compromise** : va dans Stripe › Développeurs › Clés API, **révoque-la**
   (« Roll key ») et crée-en une neuve (idéalement une **clé restreinte** `rk_live`). Idem pour toute
   clé fournisseur (Anthropic / OpenRouter) qui aurait pu fuiter. **Seules des clés fraîches iront
   sur la VM.** Je ne peux pas faire ça à ta place (c'est ton compte).

3. **Génère une clé SSH** (dans PowerShell) :
   ```powershell
   ssh-keygen -t ed25519 -C "iris-vm"
   ```
   Appuie sur Entrée à chaque question (pas de phrase de passe nécessaire). Ta clé **publique** est
   dans `C:\Users\migue\.ssh\id_ed25519.pub`. Affiche-la pour la copier :
   ```powershell
   Get-Content $HOME\.ssh\id_ed25519.pub
   ```

4. **Fabrique le paquet de code** à envoyer (sans secrets ni venvs) :
   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\Users\migue\Downloads\startup\iris\deploy\oracle\faire-bundle.ps1
   ```
   Ça crée `C:\Users\migue\Downloads\vela-vm-bundle.zip`.

---

## Phase 1 — Créer le compte Oracle + la VM

1. Va sur <https://www.oracle.com/cloud/free/> › **Start for free**. Courriel, vérification, carte
   (empreinte ~1 $).
2. **Région d'accueil** : choisis une région **canadienne** — *Canada Southeast (Montreal)* ou
   *Canada Central (Toronto)*. ⚠️ **Ce choix est définitif** (région d'accueil du compte).
3. Une fois dans la console : menu ☰ › **Compute** › **Instances** › **Create instance**.
   - **Image** : Canonical **Ubuntu 24.04** (ou 22.04).
   - **Shape** : clique *Change shape* › **Ampere (ARM)** › `VM.Standard.A1.Flex` ›
     **1 OCPU / 6 Go** *(recommandé)*. Suffisant pour tes deux serveurs, et une petite VfM est
     **moins susceptible d'être jugée « inactive »** (voir l'encadré ci-dessous). Max gratuit
     aujourd'hui = 2 OCPU / 12 Go.
   - **Clé SSH** : *Paste public keys* › colle le contenu de `id_ed25519.pub` (Phase 0.3).
   - Laisse le réseau par défaut (un VCN public est créé). **Create**.
4. Note l'**IP publique** affichée sur la page de l'instance.

> ### ⚠️ Deux pièges Oracle « Always Free » à connaître
> - **« Out of host capacity »** : l'ARM gratuit est souvent indisponible. Si ça bloque : réessaie
>   plus tard, change de *Availability Domain* (AD-1/2/3), ou prends en secours une **micro AMD**
>   `VM.Standard.E2.1.Micro` (x86, 1 Go — ça marche aussi pour ces deux apps).
>   *([Hacker News](https://news.ycombinator.com/item?id=49183750), [orendra](https://orendra.com/blog/how-to-get-free-lifetime-servers-4-core-arm-24gb-ram-more/)).*
> - **Récupération des instances inactives** : Oracle peut **arrêter** une instance ARM dont
>   l'usage CPU/réseau/mémoire reste < 20 % sur 7 jours. Deux parades : garder une **petite VM**
>   (1 OCPU/6 Go, ratio d'usage plus élevé) **+** le ping de surveillance de la Phase 5 (il génère
>   du trafic réseau). Si malgré tout elle se fait récupérer, tu pourras passer le compte en
>   **Pay As You Go** (reste gratuit dans les limites Always Free, plus aucune récupération) — mais
>   mets alors une **alerte de budget** pour éviter toute surprise.
>   *([docs Oracle : ressources Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)).*

---

## Phase 2 — Première connexion + utilisateur de service + durcissement

Depuis PowerShell (remplace `IP_PUBLIQUE`). L'utilisateur par défaut des images Ubuntu Oracle est
`ubuntu` :
```powershell
ssh -i $HOME\.ssh\id_ed25519 ubuntu@IP_PUBLIQUE
```

Sur la VM :
```bash
# Mises à jour + outils
sudo apt update && sudo apt -y upgrade
sudo apt -y install python3-venv python3-pip curl unattended-upgrades fail2ban

# Utilisateur de service NON-root qui fera tourner les serveurs (pas de mot de passe de login)
sudo adduser --system --group --home /home/vela --shell /bin/bash vela

# Mises à jour de sécurité automatiques + anti-force-brute SSH
sudo dpkg-reconfigure --priority=low unattended-upgrades   # répondre « Oui »
sudo systemctl enable --now fail2ban
```

**Durcir SSH** (par clé seulement). ⚠️ **Garde cette fenêtre SSH ouverte** et teste une 2e connexion
avant de la fermer, sinon tu risques de te verrouiller dehors. Sur Ubuntu 24.04 il faut modifier
**deux** fichiers (le second réactive sournoisement le mot de passe) :
```bash
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config.d/50-cloud-init.conf 2>/dev/null || true
sudo sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sshd -t && sudo systemctl restart ssh
```
**On n'ouvre AUCUN port entrant** (ni 80/443, ni 8100/8110) : le tunnel sort de la VM. On ne touche
donc ni les *Security Lists* du VCN, ni `iptables`. **N'installe pas UFW** (il entre en conflit avec
l'iptables d'Oracle et peut couper SSH).

---

## Phase 3 — Envoyer le code + les secrets

**Le code** (depuis PowerShell sur le PC) :
```powershell
scp -i $HOME\.ssh\id_ed25519 "$HOME\Downloads\vela-vm-bundle.zip" ubuntu@IP_PUBLIQUE:/tmp/
```
Sur la VM :
```bash
sudo mkdir -p /home/vela/iris
sudo unzip /tmp/vela-vm-bundle.zip -d /home/vela/iris
sudo chown -R vela:vela /home/vela/iris
```

**Les secrets** — avec des **clés fraîches** (voir Phase 0.2). Deux fichiers à créer :

`/home/vela/iris/serveur/.env` (clés IA du relais) — format strict `CLE=valeur`, sans guillemets,
sans espace autour du `=`, pas de commentaire en bout de ligne :
```bash
sudo -u vela nano /home/vela/iris/serveur/.env
```
```
VELA_OPENROUTER_KEY=sk-or-...            # ta clé (fraîche si elle a fuité)
VELA_ANTHROPIC_KEY=sk-ant-...            # idem
VELA_SECRET=...                          # un secret long au hasard
VELA_ELEVENLABS_KEY=...                  # facultatif
VELA_LICENCES_URL=http://127.0.0.1:8110
```

`/home/vela/iris/server/.env` (licences) : repars de `server/.env.exemple`, avec la clé Stripe
**restreinte fraîche** et/ou PayPal. **Ne colle jamais l'ancienne clé compromise.**

Verrouille :
```bash
sudo chown vela:vela /home/vela/iris/serveur/.env /home/vela/iris/server/.env
sudo chmod 600      /home/vela/iris/serveur/.env /home/vela/iris/server/.env
```

> Le relais lit ses clés **uniquement** via l'environnement → le service les charge par
> `EnvironmentFile`. Le serveur de licences charge lui-même `server/.env`. C'est déjà réglé dans les
> unités systemd fournies.

---

## Phase 4 — Installer (automatique) + l'identité du tunnel

**Lance l'installateur** (en tant que `ubuntu`, il a `sudo`) :
```bash
chmod +x /home/vela/iris/deploy/oracle/installer.sh
/home/vela/iris/deploy/oracle/installer.sh
```
Il installe Python/venvs, `cloudflared`, et copie les 3 services systemd.

**Dépose l'identité du tunnel** — depuis le PC, envoie **seulement** le fichier `<id>.json`
(⚠️ **PAS `cert.pem`** : il contrôle *tous* tes tunnels, il reste sur ton PC) :
```powershell
scp -i $HOME\.ssh\id_ed25519 "$HOME\.cloudflared\3b543fb7-c1cc-4967-a9c4-a76b9afb246b.json" ubuntu@IP_PUBLIQUE:/tmp/
```
Sur la VM :
```bash
sudo -u vela mkdir -p /home/vela/.cloudflared
sudo cp /home/vela/iris/deploy/oracle/config.yml /home/vela/.cloudflared/config.yml
sudo mv /tmp/3b543fb7-c1cc-4967-a9c4-a76b9afb246b.json /home/vela/.cloudflared/
sudo chown -R vela:vela /home/vela/.cloudflared
sudo chmod 600 /home/vela/.cloudflared/*
```

---

## Phase 5 — Bascule, démarrage, vérification

1. **COUPE le tunnel du PC** (indispensable : un seul réplica actif, sinon Cloudflare répartit le
   trafic au hasard entre PC et VM). Sur le PC :
   ```powershell
   Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
   Remove-Item "$HOME\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\lancer-tunnel.vbs" -ErrorAction SilentlyContinue
   ```

2. **Démarre tout sur la VM** :
   ```bash
   sudo systemctl enable --now vela-relais vela-licences cloudflared
   ```

3. **Vérifie POUR DE VRAI** (leçon « déploiement menteur » : `localhost` qui répond ne prouve pas
   que le public marche) :
   ```bash
   systemctl status vela-relais vela-licences cloudflared --no-pager
   curl -s http://127.0.0.1:8100/sante ; echo      # local
   journalctl -u cloudflared -e --no-pager | tail  # doit montrer « Registered tunnel connection » x4
   ```
   Puis, **depuis ton téléphone / un autre réseau** :
   ```
   https://relais.velaglass.ca/sante
   https://licences.velaglass.ca/sante
   ```
   Si erreur DNS/502 sur les sous-domaines alors que le local répond : les routes du tunnel ne
   pointent pas encore. Depuis le **PC** (il a `cert.pem`) :
   ```powershell
   cloudflared tunnel route dns vela-relais relais.velaglass.ca
   cloudflared tunnel route dns vela-relais licences.velaglass.ca
   ```

4. **Preuve du 24/7** : redémarre la VM et reconstate que tout remonte seul :
   ```bash
   sudo reboot
   # (reconnecte-toi ~1 min plus tard)
   systemctl is-active vela-relais vela-licences cloudflared   # → active x3
   ```

5. **Garde la VM éveillée** (anti-récupération) : crée un moniteur gratuit
   [UptimeRobot](https://uptimerobot.com) qui frappe `https://relais.velaglass.ca/sante` toutes les
   5 min. Bonus : ça confirme aussi que le brain est vivant.

---

## Notes importantes

- **Priorité = le relais.** C'est lui que l'app des clients appelle pour l'IA. Le serveur de
  licences n'est utile qu'à l'achat : tu peux le laisser tourner, mais il ne sert vraiment qu'une
  fois les paiements configurés.
- **Licences en production** : quand tu activeras les paiements, mets `IRIS_ENV=production` dans
  `server/.env`. ⚠️ En production, le serveur **exige PayPal configuré** pour démarrer (garde-fou) ;
  Stripe n'est requis que si tu renseignes au moins une variable `STRIPE_*`.
- **Sécurité des fichiers du tunnel** : `cert.pem` ne va **jamais** sur la VM. Sauvegarde le
  `<id>.json` (chiffré) hors de la VM ; s'il fuite, quelqu'un peut faire tourner ton tunnel.
- **Ne lance jamais `cloudflared tunnel create` sur la VM** : ça créerait un NOUVEAU tunnel et
  casserait les CNAME existants. On réutilise l'id `3b543fb7-c1cc-4967-a9c4-a76b9afb246b`.

Fichiers de ce dossier : `installer.sh`, `faire-bundle.ps1`, `config.yml`,
`vela-relais.service`, `vela-licences.service`, `cloudflared.service`.
