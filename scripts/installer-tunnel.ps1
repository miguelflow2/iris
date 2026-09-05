# Rend IRIS joignable depuis l'extérieur, sans ouvrir un seul port sur la box.
#
# Le choix retenu est Tailscale : un réseau privé entre VOS appareils, chiffré de bout en bout,
# gratuit, qui ne publie rien sur Internet. Le raisonnement complet — et pourquoi ce n'est PAS la
# solution pour le relais commercial — est dans docs\ACCES-DISTANT.md. Lisez-le avant.
#
# Deux choses que ce script ne fera jamais, et c'est voulu :
#   - il n'ouvre aucun port et ne touche pas au pare-feu (c'est le rôle d'autoriser-telephone.ps1,
#     qui devient d'ailleurs inutile une fois le tunnel en place) ;
#   - il refuse de publier IRIS tant qu'aucun mot de passe n'est posé. Le jeton d'adresse seul
#     autorise `POST /api/compte`, c'est-à-dire poser le premier mot de passe : publier avant,
#     ce serait laisser un inconnu verrouiller la maison de l'intérieur.
#
#   .\scripts\installer-tunnel.ps1              # ne change RIEN : vérifie et explique
#   .\scripts\installer-tunnel.ps1 -Installer   # installe Tailscale (à lancer en administrateur)
#   .\scripts\installer-tunnel.ps1 -Servir      # publie IRIS en HTTPS sur votre nom .ts.net
#   .\scripts\installer-tunnel.ps1 -Retirer     # dépublie IRIS (Tailscale reste installé)

param(
    [switch]$Installer,
    [switch]$Servir,
    [switch]$Retirer,
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"

function Dire-Ok        { param([string]$t) Write-Host "  [ok] $t" -ForegroundColor Green }
function Dire-Attention { param([string]$t) Write-Host "  [!]  $t" -ForegroundColor Yellow }
function Dire-Bloquant  { param([string]$t) Write-Host "  [X]  $t" -ForegroundColor Red }
function Dire-Titre     { param([string]$t) Write-Host ""; Write-Host $t -ForegroundColor Cyan }

function Test-Administrateur {
    return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Trouver-Tailscale {
    # winget n'ajoute pas Tailscale au PATH de la session DEJA ouverte : sans ce repli, le script
    # annoncerait « pas installe » juste apres l'avoir installe, et on tournerait en rond.
    $cmd = Get-Command tailscale.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $racines = @($env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ }
    foreach ($r in $racines) {
        $c = Join-Path $r "Tailscale\tailscale.exe"
        if (Test-Path $c) { return $c }
    }
    return $null
}

function Lire-Etat {
    param([string]$exe)
    # `status --json` est la seule source stable : l'affichage texte de Tailscale change d'une
    # version a l'autre, le JSON beaucoup moins.
    try {
        $brut = & $exe status --json
        if ($LASTEXITCODE -ne 0) { return $null }
        return ($brut | Out-String | ConvertFrom-Json)
    }
    catch { return $null }
}

function Lire-NomMachine {
    param($etat)
    if (-not $etat) { return $null }
    if (-not $etat.Self) { return $null }
    $nom = [string]$etat.Self.DNSName
    if (-not $nom) { return $null }
    return $nom.TrimEnd('.')   # Tailscale renvoie un nom absolu, avec le point final
}

function Test-HttpsActif {
    param($etat, [string]$nom)
    # CertDomains n'est rempli que si « HTTPS Certificates » est active dans la console Tailscale.
    # Sans lui, `tailscale serve` ne peut pas obtenir de certificat, donc pas de https, donc pas
    # de microphone sur l'iPhone : c'est le point qui decide de tout.
    if (-not $etat) { return $false }
    if (-not $etat.CertDomains) { return $false }
    foreach ($d in $etat.CertDomains) {
        if ($d -eq $nom) { return $true }
    }
    return $false
}

function Trouver-DonneesIris {
    $chemin = Join-Path $env:APPDATA "IRIS\iris-data"
    if (Test-Path $chemin) { return $chemin }
    # En administrateur, $env:APPDATA vise le profil de l'administrateur, pas celui de Miguel.
    $trouve = Get-ChildItem "C:\Users" -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $c = Join-Path $_.FullName "AppData\Roaming\IRIS\iris-data"
        if (Test-Path $c) { $c }
    } | Select-Object -First 1
    return $trouve
}

function Test-MotDePasse {
    param($donnees)
    if (-not $donnees) { return $false }
    $f = Join-Path $donnees "compte.json"
    if (-not (Test-Path $f)) { return $false }
    try {
        $c = Get-Content $f -Raw -Encoding UTF8 | ConvertFrom-Json
        # On ne lit que la PRESENCE de l'empreinte. Sa valeur ne sort jamais de cette fonction :
        # un secret qui passe par Write-Host finit dans l'historique de la console.
        return [bool]$c.hash
    }
    catch { return $false }
}

function Test-AccesDistant {
    param($donnees)
    if (-not $donnees) { return $false }
    $f = Join-Path $donnees "settings.json"
    if (-not (Test-Path $f)) { return $false }
    try {
        $c = Get-Content $f -Raw -Encoding UTF8 | ConvertFrom-Json
        return [bool]$c.remote_access
    }
    catch { return $false }
}

function Test-Ecoute {
    param([int]$p)
    return ((netstat -ano | Select-String ":$p\s.*LISTENING").Count -gt 0)
}

$exe = Trouver-Tailscale
$donnees = Trouver-DonneesIris

# ============================================================================ -Installer
if ($Installer) {
    Dire-Titre "Installation de Tailscale"
    if ($exe) {
        Dire-Ok "Deja installe : $exe"
        Write-Host "  Relancez le script sans option pour verifier le reste."
        exit 0
    }
    if (-not (Test-Administrateur)) {
        Dire-Bloquant "Il faut lancer ce script en administrateur pour installer un logiciel."
        Write-Host "  Menu Demarrer > tapez 'powershell' > clic droit > 'Executer en tant qu'administrateur'."
        exit 1
    }
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        Dire-Bloquant "winget est absent de cette machine."
        Write-Host "  Telechargez l'installateur officiel a la main : https://tailscale.com/download/windows"
        Write-Host "  Puis relancez ce script sans option."
        exit 1
    }
    Write-Host "  Commande executee : winget install --exact --id Tailscale.Tailscale"
    Write-Host "  winget peut demander d'accepter les conditions de Tailscale : c'est VOTRE acceptation,"
    Write-Host "  le script ne repond pas a votre place. Conditions : https://tailscale.com/terms"
    Write-Host ""
    & winget install --exact --id Tailscale.Tailscale --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        Dire-Bloquant "winget a echoue (code $LASTEXITCODE). Rien n'a ete installe a moitie : reessayez, ou passez par l'installateur officiel."
        exit 1
    }
    Dire-Ok "Tailscale installe."
    Write-Host ""
    Write-Host "ETAPE SUIVANTE, a faire vous-meme :" -ForegroundColor Cyan
    Write-Host "  1. Fermez cette console et ouvrez-en une nouvelle (le PATH n'est pas encore a jour)."
    Write-Host "  2. Tapez :  tailscale up"
    Write-Host "     Votre navigateur s'ouvre : connectez-vous, ou creez le compte. C'est vous qui"
    Write-Host "     choisissez le compte et le mot de passe, ce script n'y touche pas."
    Write-Host "  3. Installez l'application Tailscale sur l'iPhone, avec LE MEME compte."
    Write-Host "  4. Dans la console https://login.tailscale.com/admin/dns : activez MagicDNS,"
    Write-Host "     puis 'HTTPS Certificates'. Sans ce dernier, pas de https, donc pas de micro sur l'iPhone."
    Write-Host "  5. Relancez :  .\scripts\installer-tunnel.ps1"
    exit 0
}

# ============================================================================ -Retirer
if ($Retirer) {
    Dire-Titre "Depublication d'IRIS"
    if (-not $exe) {
        Dire-Attention "Tailscale n'est pas installe : il n'y a rien a depublier."
        exit 0
    }
    & $exe serve reset
    if ($LASTEXITCODE -ne 0) {
        # La syntaxe de `serve` a change entre les versions ; on donne l'ancienne plutot que de
        # laisser croire que la depublication a eu lieu.
        Dire-Attention "'serve reset' a echoue. Sur une version plus ancienne, essayez :"
        Write-Host "     tailscale serve --https=443 off"
        exit 1
    }
    Dire-Ok "IRIS n'est plus publiee sur le nom .ts.net."
    Write-Host ""
    Write-Host "Tailscale reste installe et votre reseau prive continue de fonctionner."
    Write-Host "Pour aller plus loin, dans l'ordre du plus doux au plus radical :"
    Write-Host "  - deconnecter cette machine du reseau prive :  tailscale down"
    Write-Host "  - retirer l'appareil du compte : console https://login.tailscale.com/admin/machines"
    Write-Host "  - desinstaller (administrateur) :  winget uninstall --exact --id Tailscale.Tailscale"
    Write-Host "  - la regle de pare-feu du port $Port n'a plus lieu d'etre :"
    Write-Host "      .\scripts\autoriser-telephone.ps1 -Retirer"
    exit 0
}

# ============================================================================ diagnostic commun
Dire-Titre "Etat de l'acces distant"

$etat = $null
$nom = $null
$https = $false

if (-not $exe) {
    Dire-Bloquant "1. Tailscale n'est pas installe."
}
else {
    Dire-Ok "1. Tailscale installe : $exe"
    $service = Get-Service -Name Tailscale -ErrorAction SilentlyContinue
    if ($service -and $service.Status -eq 'Running') {
        Dire-Ok "2. Service Windows demarre : le tunnel repart tout seul apres une coupure de courant."
    }
    else {
        Dire-Attention "2. Le service Tailscale ne tourne pas : demarrez l'application Tailscale une fois."
    }

    $etat = Lire-Etat $exe
    $nom = Lire-NomMachine $etat
    if (-not $etat) {
        Dire-Bloquant "3. Impossible de lire l'etat de Tailscale."
    }
    elseif ($etat.BackendState -ne 'Running') {
        Dire-Bloquant "3. Machine non connectee au reseau prive (etat : $($etat.BackendState)). Tapez : tailscale up"
    }
    elseif (-not $nom) {
        Dire-Attention "3. Connecte, mais aucun nom MagicDNS. Activez MagicDNS : https://login.tailscale.com/admin/dns"
    }
    else {
        Dire-Ok "3. Connecte au reseau prive, nom stable : $nom"
        $https = Test-HttpsActif $etat $nom
        if ($https) {
            Dire-Ok "4. Certificats HTTPS actifs : le microphone de Safari sera autorise."
        }
        else {
            Dire-Bloquant "4. HTTPS non active. Console > DNS > 'HTTPS Certificates' > Enable."
            Write-Host "      Sans cela l'adresse reste en http://, et Safari refuse le micro : la voix"
            Write-Host "      basculera sur 'Voix indisponible - ecrivez', dehors comme a la maison."
        }
    }
}

$motDePasse = Test-MotDePasse $donnees
if ($motDePasse) {
    Dire-Ok "5. Mot de passe IRIS pose : l'adresse seule ne commande pas votre ordinateur."
}
else {
    Dire-Bloquant "5. AUCUN mot de passe IRIS. Ouvrez IRIS > Parametres > Telephone, et posez-en un."
    Write-Host "      Tant qu'il n'y en a pas, quiconque atteint l'adresse peut poser LE PREMIER"
    Write-Host "      mot de passe, et vous enfermer dehors de votre propre machine."
}

if (Test-AccesDistant $donnees) {
    Dire-Ok "6. Acces telephone actif dans IRIS : port fixe $Port et jeton conserve."
}
else {
    Dire-Attention "6. Acces telephone inactif dans IRIS : le port change a chaque demarrage."
    Write-Host "      Activez-le (Parametres > Telephone) : c'est ce reglage qui fige le port $Port,"
    Write-Host "      et sans port fixe le tunnel pointe un jour sur deux dans le vide."
}

if (Test-Ecoute $Port) {
    Dire-Ok "7. Quelque chose ecoute sur le port $Port."
}
else {
    Dire-Attention "7. Rien n'ecoute sur le port $Port : lancez IRIS avant de tester depuis le telephone."
}

# ============================================================================ -Servir
if ($Servir) {
    Dire-Titre "Publication d'IRIS sur votre reseau prive"
    if (-not $exe -or -not $nom -or ($etat.BackendState -ne 'Running')) {
        Dire-Bloquant "Impossible : Tailscale n'est pas pret (voir les points 1 a 3 ci-dessus)."
        exit 1
    }
    if (-not $https) {
        Dire-Bloquant "Impossible : les certificats HTTPS ne sont pas actives (point 4)."
        Write-Host "  On pourrait publier en http, mais ce serait publier une voix qui ne marche pas."
        exit 1
    }
    if (-not $motDePasse) {
        # Refus deliberé, et non un avertissement : c'est la seule barriere qui reste entre un
        # appareil egare et une machine ou IRIS execute des commandes.
        Dire-Bloquant "Refus : aucun mot de passe IRIS n'est pose (point 5)."
        Write-Host "  Posez-le d'abord dans IRIS, puis relancez avec -Servir."
        exit 1
    }

    & $exe serve --bg $Port
    if ($LASTEXITCODE -ne 0) {
        # La syntaxe de `serve` a change plusieurs fois : on donne les deux formes plutot que de
        # laisser croire que la publication a eu lieu.
        Dire-Attention "La commande a echoue. Deux pistes, dans cet ordre :"
        Write-Host "     1. si le refus parle de droits, relancez cette console en administrateur ;"
        Write-Host "     2. sur une version plus ancienne de Tailscale, la syntaxe est l'une de :"
        Write-Host "          tailscale serve https / http://localhost:$Port"
        Write-Host "          tailscale serve https:443 / http://127.0.0.1:$Port"
        exit 1
    }
    Dire-Ok "IRIS est publiee sur votre reseau prive, en https."
}

# ============================================================================ l'adresse finale
Dire-Titre "L'adresse a ouvrir dans Safari sur l'iPhone"
if ($nom -and $https) {
    Write-Host "   https://$nom/m" -ForegroundColor Green
    Write-Host ""
    Write-Host "   La meme a la maison et dans la voiture : c'est tout l'interet. Mettez-la en favori,"
    Write-Host "   puis 'Partager > Sur l'ecran d'accueil' pour l'installer comme une application."
    Write-Host "   Le mot de passe est demande a la premiere ouverture ; la session dure 30 jours."
    Write-Host ""
    Write-Host "   N'ajoutez PAS ?token=... a cette adresse : une adresse se retrouve dans l'historique"
    Write-Host "   et dans les captures d'ecran. Le mot de passe suffit, c'est fait pour ca."
}
else {
    Write-Host "   Pas encore d'adresse : reglez les points marques [X] ci-dessus." -ForegroundColor Yellow
}

if (-not $Servir) {
    Write-Host ""
    Write-Host "Ce script n'a rien modifie. Pour publier IRIS :  .\scripts\installer-tunnel.ps1 -Servir"
}
Write-Host ""
Write-Host "Ce que ce tunnel n'expose pas, et jusqu'ou il va : docs\ACCES-DISTANT.md"
