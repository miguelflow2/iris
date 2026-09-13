#!/usr/bin/env bash
# =============================================================================
# Installateur VELA pour la VM Oracle (Ubuntu ARM64 ou AMD).
#
# À LANCER SUR LA VM, connecté en tant qu'utilisateur ADMIN « ubuntu » (celui qui a sudo).
# Il suppose que le code est déjà dans /home/vela/iris (dézippé depuis vela-vm-bundle.zip)
# et que l'utilisateur de service « vela » existe (voir le guide, phase 2).
#
# CE QU'IL FAIT (sans jamais toucher à tes secrets) :
#   0. remet la propriété du code à l'utilisateur vela
#   A. paquets système (python venv/pip, curl)
#   B. crée les 2 environnements Python (relais + licences) EN TANT QUE vela
#   C. installe cloudflared (dépôt officiel Cloudflare)
#   D. copie les 3 services systemd et recharge systemd
#
# CE QU'IL NE FAIT PAS (secrets — à faire à la main, voir le guide) :
#   - déposer serveur/.env et server/.env  (avec des clés FRAÎCHES)
#   - déposer l'identifiant du tunnel  /home/vela/.cloudflared/<id>.json + config.yml
#   - démarrer les services
#
# UTILISATION :
#   chmod +x /home/vela/iris/deploy/oracle/installer.sh
#   /home/vela/iris/deploy/oracle/installer.sh
# =============================================================================
set -euo pipefail

VELA_USER=vela
BASE=/home/vela/iris
ORACLE="$BASE/deploy/oracle"

id "$VELA_USER" >/dev/null 2>&1 || { echo "ERREUR : l'utilisateur '$VELA_USER' n'existe pas encore (voir le guide, phase 2)."; exit 1; }

echo "==> Disque disponible (leçon du projet : vérifier AVANT d'installer) :"
df -h / | tail -1

echo "==> Vérification de la présence du code…"
for d in "$BASE/serveur" "$BASE/server/licences" "$ORACLE"; do
  [ -d "$d" ] || { echo "ERREUR : dossier manquant : $d — dézippe d'abord le bundle dans $BASE."; exit 1; }
done

echo "==> 0. Propriété du code à l'utilisateur $VELA_USER"
sudo chown -R "$VELA_USER":"$VELA_USER" "$BASE"

echo "==> A. Paquets système"
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip curl

echo "==> B. Environnement Python du RELAIS (en tant que $VELA_USER)"
sudo -u "$VELA_USER" python3 -m venv "$BASE/serveur/.venv"
sudo -u "$VELA_USER" "$BASE/serveur/.venv/bin/pip" install --upgrade pip wheel
sudo -u "$VELA_USER" "$BASE/serveur/.venv/bin/pip" install -r "$BASE/serveur/requirements.txt"

echo "==> B. Environnement Python des LICENCES (en tant que $VELA_USER)"
sudo -u "$VELA_USER" python3 -m venv "$BASE/server/.venv"
sudo -u "$VELA_USER" "$BASE/server/.venv/bin/pip" install --upgrade pip wheel
sudo -u "$VELA_USER" "$BASE/server/.venv/bin/pip" install -r "$BASE/server/requirements.txt"

echo "==> C. cloudflared (dépôt officiel Cloudflare)"
if ! command -v cloudflared >/dev/null 2>&1; then
  sudo mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
    | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
    | sudo tee /etc/apt/sources.list.d/cloudflared.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y cloudflared
else
  echo "    cloudflared déjà présent : $(command -v cloudflared)"
fi

echo "==> D. Services systemd"
sudo cp "$ORACLE/vela-relais.service"   /etc/systemd/system/vela-relais.service
sudo cp "$ORACLE/vela-licences.service" /etc/systemd/system/vela-licences.service
sudo cp "$ORACLE/cloudflared.service"   /etc/systemd/system/cloudflared.service
sudo systemctl daemon-reload

echo
echo "============================================================"
echo "  INSTALLATION TERMINÉE (partie automatique)."
echo
echo "  IL RESTE À FAIRE À LA MAIN (secrets — voir le guide) :"
echo "   1) Déposer les .env avec des clés FRAÎCHES :"
echo "        /home/vela/iris/serveur/.env   (clés IA)"
echo "        /home/vela/iris/server/.env    (PayPal/Stripe)"
echo "   2) Déposer l'identité du tunnel (SANS cert.pem) :"
echo "        /home/vela/.cloudflared/config.yml"
echo "        /home/vela/.cloudflared/3b543fb7-c1cc-4967-a9c4-a76b9afb246b.json"
echo "   3) Verrouiller les secrets :"
echo "        sudo chown -R vela:vela /home/vela/.cloudflared /home/vela/iris/serveur/.env /home/vela/iris/server/.env"
echo "        sudo chmod 600 /home/vela/.cloudflared/* /home/vela/iris/serveur/.env /home/vela/iris/server/.env"
echo "   4) COUPER le tunnel du PC Windows (un seul réplica actif !), puis :"
echo "        sudo systemctl enable --now vela-relais vela-licences cloudflared"
echo "   5) Vérifier :"
echo "        systemctl status vela-relais vela-licences cloudflared --no-pager"
echo "        curl -s http://127.0.0.1:8100/sante ; echo"
echo "        curl -s https://relais.velaglass.ca/sante ; echo   # depuis un AUTRE réseau"
echo "============================================================"
