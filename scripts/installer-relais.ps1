# Installe le relais IA de VELA en service Windows, pour qu'il tourne en permanence.
#
# Ce que ça règle : aujourd'hui le relais ne tourne que dans une fenêtre PowerShell ouverte. On
# ferme la session, il s'arrête ; le courant saute, il ne revient pas ; il plante, personne ne le
# relance. Un service Windows survit à la fermeture de session, redémarre avec la machine et se
# fait relancer tout seul s'il meurt.
#
# Le superviseur est WinSW : un petit exécutable qui sait présenter n'importe quel programme au
# Gestionnaire de contrôle des services. Il est choisi plutôt que NSSM parce que toute sa
# configuration tient dans UN fichier XML posé à côté de relais.py, donc lisible et versionnable ;
# celle de NSSM vit dans le registre, invisible pour qui lit le dépôt.
#
# LES SECRETS NE SONT NULLE PART DANS LA DÉFINITION DU SERVICE. Ni dans le XML, ni dans les
# arguments, ni dans le registre : tout cela se lit en clair. Ils vivent dans serveur/.env, dont
# les droits sont refermés sur SYSTEM + les administrateurs + vous, et c'est ce script — relancé
# par le service avec -Executer — qui les charge dans le seul processus enfant.
#
# Le service tourne sous LocalSystem, PAS sous votre compte. C'est un écart assumé : faire tourner
# un service « même si l'utilisateur n'est pas connecté » sous un compte Microsoft oblige à
# STOCKER le mot de passe du compte Microsoft dans la définition du service, et ce service casse
# alors en silence au prochain changement de ce mot de passe. Comme relais.py ne lit que des
# variables d'environnement (jamais le Gestionnaire d'identification, jamais %APPDATA%),
# LocalSystem lui suffit, et il n'y a plus aucun mot de passe à stocker nulle part.
#
#   Installer :        .\scripts\installer-relais.ps1
#   Première fois :    .\scripts\installer-relais.ps1 -Telecharger      (récupère WinSW)
#   Arrêter :          .\scripts\installer-relais.ps1 -Arreter
#   Relancer :         .\scripts\installer-relais.ps1 -Relancer
#   Voir le journal :  .\scripts\installer-relais.ps1 -Journal
#   Journal en direct: .\scripts\installer-relais.ps1 -Journal -Suivre
#   Tout enlever :     .\scripts\installer-relais.ps1 -Desinstaller
#
# À exécuter EN ADMINISTRATEUR (sauf -Journal). Enregistrer un service demande une élévation :
# il n'existe aucun chemin sans elle.

param(
    [switch]$Arreter,
    [switch]$Relancer,
    [switch]$Journal,
    [switch]$Suivre,
    [switch]$Desinstaller,
    [switch]$Telecharger,
    [switch]$IgnorerEspaceDisque,
    [switch]$Executer,
    [int]$Lignes = 60
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------- les chemins, tous absolus
$racine    = Split-Path -Parent $PSScriptRoot
$serveur   = Join-Path $racine "serveur"
$venv      = Join-Path $serveur ".venv"
$python    = Join-Path $venv "Scripts\python.exe"
$fichierEnv = Join-Path $serveur ".env"
$journaux  = Join-Path $serveur "journaux"
$donnees   = Join-Path $serveur "donnees"
$exigences = Join-Path $serveur "requirements.txt"
# WinSW exige que le XML porte le MÊME nom de base que l'exe : relais-service.exe / .xml.
$superviseur = Join-Path $serveur "relais-service.exe"
$config      = Join-Path $serveur "relais-service.xml"
$moiMeme     = Join-Path $PSScriptRoot "installer-relais.ps1"

$SERVICE = "VelaRelais"
$PORT    = 8100
$SANTE   = "http://127.0.0.1:$PORT/sante"

# Espace disque. Ce n'est pas une précaution de style : le relais réécrit intégralement
# donnees/quotas.json DEUX FOIS par requête (une fois avant l'appel, une fois après), via un .tmp
# puis un remplacement. Sur un disque plein, _ecrire lève, chaque appel d'IRIS répond 500 — et
# /sante continue de répondre {"ok": true} parce qu'il ne fait que LIRE et que _lire avale toutes
# les exceptions. Autrement dit : la panne est totale et le point de santé dit que tout va bien.
$DISQUE_MINIMUM = 2      # en Go : en dessous, on refuse d'installer
$DISQUE_CONFORT = 5      # en Go : en dessous, on installe mais on prévient fort

# WinSW n'est pas dans le dépôt (5 Mo de binaire tiers). Ces adresses sont essayées dans l'ordre.
# Elles peuvent avoir changé : si aucune ne répond, le script dit où aller le chercher à la main.
$SOURCES_WINSW = @(
    "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe",
    "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW.NET461.exe",
    "https://github.com/winsw/winsw/releases/download/v2.11.0/WinSW.NET461.exe"
)
$PAGE_WINSW = "https://github.com/winsw/winsw/releases"

$CLES_CONNUES = @(
    "VELA_OPENROUTER_KEY", "VELA_ANTHROPIC_KEY", "VELA_SECRET", "VELA_LICENCES_URL",
    "VELA_ELEVENLABS_KEY", "VELA_LICENCE_SECRET", "VELA_DONNEES"
)


# ================================================================ petits utilitaires

function Lire-FichierEnv([string]$chemin) {
    $table = @{}
    if (-not (Test-Path $chemin)) { return $table }
    foreach ($ligne in (Get-Content -Path $chemin -Encoding UTF8)) {
        $t = $ligne.Trim()
        if ($t -eq "" -or $t.StartsWith("#")) { continue }
        $i = $t.IndexOf("=")
        if ($i -lt 1) { continue }
        $cle = $t.Substring(0, $i).Trim()
        $valeur = $t.Substring($i + 1).Trim()
        if ($valeur.Length -ge 2) {
            if (($valeur.StartsWith('"') -and $valeur.EndsWith('"')) -or
                ($valeur.StartsWith("'") -and $valeur.EndsWith("'"))) {
                $valeur = $valeur.Substring(1, $valeur.Length - 2)
            }
        }
        $table[$cle] = $valeur
    }
    return $table
}

function Ecrire-FichierEnv([string]$chemin, $table) {
    $lignes = New-Object System.Collections.Generic.List[string]
    $lignes.Add("# Secrets du relais IA de VELA. Ecrit par scripts\installer-relais.ps1.")
    $lignes.Add("# Ce fichier n'est JAMAIS versionne et n'est lisible que par SYSTEM, les")
    $lignes.Add("# administrateurs et vous. Le service le charge au demarrage : c'est la raison")
    $lignes.Add("# pour laquelle la cle OpenRouter n'apparait ni dans le XML ni dans le registre.")
    $lignes.Add("")
    foreach ($cle in $CLES_CONNUES) {
        if ($table.ContainsKey($cle) -and $table[$cle]) {
            $lignes.Add(("{0}={1}" -f $cle, $table[$cle]))
        }
    }
    # Écrit en UTF-8 SANS marque d'ordre des octets. `Set-Content -Encoding UTF8` de PowerShell 5.1
    # en ajoute une, et cette marque invisible se retrouverait collée devant la première ligne pour
    # tout autre lecteur que celui d'ici.
    [System.IO.File]::WriteAllLines($chemin, $lignes.ToArray(), (New-Object System.Text.UTF8Encoding($false)))
}

function Proteger-Fichier([string]$chemin) {
    # On coupe l'héritage AVANT de poser les règles. Sans cela, les droits « Utilisateurs » hérités
    # du dossier parent restent en place et n'importe quel compte du poste lit la clé OpenRouter.
    # Les identités sont désignées par leur SID et non par leur nom : sur un Windows français ils
    # s'appellent « Système » et « Administrateurs », et un script qui code les noms en dur casse.
    $moi     = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $systeme = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-18")
    $admins  = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-32-544")

    $acl = Get-Acl -Path $chemin
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($regle in @($acl.Access)) {
        if (-not $regle.IsInherited) { [void]$acl.RemoveAccessRuleSpecific($regle) }
    }
    foreach ($sid in @($moi, $systeme, $admins)) {
        $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid, "FullControl", "None", "None", "Allow")))
    }
    Set-Acl -Path $chemin -AclObject $acl
}

function Lire-SecretCache([string]$invite) {
    # -AsSecureString pour que la clé n'apparaisse pas à l'écran ni dans l'historique de la console.
    $secure = Read-Host -Prompt $invite -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Test-Elevation {
    return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Exiger-Elevation {
    if (Test-Elevation) { return }
    Write-Host "Il faut lancer ce script en administrateur." -ForegroundColor Red
    Write-Host "Menu Demarrer > tapez 'powershell' > clic droit > 'Executer en tant qu'administrateur'."
    Write-Host "Puis relancez la meme ligne. Seul -Journal n'a pas besoin d'elevation."
    exit 1
}

function Attendre-Sante([int]$secondes) {
    $fin = (Get-Date).AddSeconds($secondes)
    while ((Get-Date) -lt $fin) {
        try { return Invoke-RestMethod -Uri $SANTE -TimeoutSec 3 }
        catch { Start-Sleep -Seconds 1 }
    }
    return $null
}

function Afficher-Sante {
    Write-Host ""
    Write-Host "Verification de $SANTE ..." -ForegroundColor Cyan
    $sante = Attendre-Sante 40
    if (-not $sante) {
        Write-Host "LE RELAIS NE REPOND PAS sur $SANTE." -ForegroundColor Red
        Write-Host "   Regardez le journal, c'est la qu'est la raison :" -ForegroundColor Yellow
        Write-Host "      .\scripts\installer-relais.ps1 -Journal"
        return $false
    }
    # ATTENTION : /sante repond TOUJOURS {"ok": true}. Il ne teste ni la cle, ni le disque.
    # Le seul champ qui dit quelque chose ici est 'amont'. Un service « demarre » avec amont=false
    # accepte les connexions et repond 503 a chaque demande d'IRIS : cote client, l'IA est morte.
    if (-not $sante.amont) {
        Write-Host "Le service repond, mais SANS CLE IA (amont = false)." -ForegroundColor Red
        Write-Host "   VELA_OPENROUTER_KEY n'a pas ete lue. Toutes les demandes d'IRIS auront un 503." -ForegroundColor Yellow
        Write-Host "   Verifiez la ligne VELA_OPENROUTER_KEY dans $fichierEnv, puis -Relancer."
        return $false
    }
    Write-Host "Le relais repond et sa cle IA est chargee." -ForegroundColor Green
    $voix = "non"
    if ($sante.voix) { $voix = "oui" }
    Write-Host ("   voix ElevenLabs : {0}   plafond global : {1} jetons   consomme ce mois : {2}" -f `
        $voix, $sante.plafond_global, $sante.consomme)
    return $true
}

function Afficher-Etat {
    $svc = Get-Service -Name $SERVICE -ErrorAction SilentlyContinue
    if (-not $svc) {
        Write-Host "Service '$SERVICE' : pas installe." -ForegroundColor Yellow
        return
    }
    $couleur = "Yellow"
    if ($svc.Status -eq "Running") { $couleur = "Green" }
    Write-Host ("Service '{0}' : {1} (demarrage {2})" -f $SERVICE, $svc.Status, $svc.StartType) -ForegroundColor $couleur
}


# ================================================================ -Executer : le service lui-même
# Ce n'est pas un mode pour un humain. C'est la ligne que WinSW lance, et c'est ici — et nulle part
# ailleurs — que les secrets entrent en mémoire.
if ($Executer) {
    if (-not (Test-Path $fichierEnv)) {
        Write-Host "ARRET : $fichierEnv est introuvable. Relancez l'installateur."
        exit 2
    }
    if (-not (Test-Path $python)) {
        Write-Host "ARRET : $python est introuvable. Relancez l'installateur."
        exit 2
    }

    $variables = Lire-FichierEnv $fichierEnv
    foreach ($cle in @($variables.Keys)) {
        # Une valeur vide n'est pas posée : relais.py fait .strip() puis retombe sur son défaut,
        # et une variable vide masquerait ce défaut au lieu de le laisser jouer.
        if ($variables[$cle]) { Set-Item -Path ("Env:" + $cle) -Value $variables[$cle] }
    }

    # Sans PYTHONUNBUFFERED, la sortie de Python reste en tampon derrière un tuyau : le journal du
    # service paraît vide pendant plusieurs minutes et on croit que rien ne démarre.
    # Sans PYTHONIOENCODING, un service sans console encode en cp1252 et le journaliseur plante dès
    # qu'un accent traverse une ligne de journal.
    $env:PYTHONUNBUFFERED = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONPATH = $serveur

    Set-Location -Path $serveur
    # --workers 1 n'est pas un réglage de performance, c'est une obligation. Le verrou du relais
    # (`_verrou = Lock()`, relais.py) est un threading.Lock : il ne sérialise que les fils d'UN
    # processus. Deux workers font du lire-modifier-écrire concurrent sur quotas.json et perdent
    # leurs incréments mutuels — à commencer par "tous|jetons", le compteur qui porte le plafond
    # global de 30 M jetons, c'est-à-dire le seul garde-fou entre un bogue et un compte OpenRouter vidé.
    & $python -m uvicorn relais:app --host 127.0.0.1 --port $PORT --workers 1
    $code = $LASTEXITCODE

    # Un uvicorn qui se termine tout seul est une panne, même quand il sort avec 0. Or le
    # Gestionnaire de services ne relance QUE sur un code non nul : rendre 0 tel quel produirait un
    # service « arrêté proprement » que plus rien ne redémarre. Quand c'est nous qui arrêtons le
    # service, WinSW tue ce processus et cette ligne n'est jamais atteinte.
    if ($code -eq 0) { exit 1 }
    exit $code
}


# ================================================================ -Journal
if ($Journal) {
    Write-Host "Les journaux du relais sont dans :" -ForegroundColor Cyan
    Write-Host "   $journaux"
    Write-Host ""
    if (-not (Test-Path $journaux)) {
        Write-Host "Ce dossier n'existe pas encore : le service n'a jamais demarre." -ForegroundColor Yellow
        exit 0
    }
    Get-ChildItem $journaux -Filter "*.log" | ForEach-Object {
        Write-Host ("   {0}  {1} Ko  {2}" -f $_.Name, [math]::Round($_.Length / 1KB, 1), $_.LastWriteTime)
    }
    # uvicorn ecrit TOUTES ses lignes sur la sortie d'erreur, y compris « application startup
    # complete ». Un .err.log volumineux est donc normal et ne signale aucune panne : c'est le
    # journal principal. Le .out.log, lui, reste souvent vide.
    Write-Host ""
    Write-Host "uvicorn ecrit son journal sur la sortie d'ERREUR : le fichier .err.log est le" -ForegroundColor Yellow
    Write-Host "journal normal du service, pas une liste de pannes." -ForegroundColor Yellow
    Write-Host ""

    $principal = Join-Path $journaux "$SERVICE.err.log"
    if (-not (Test-Path $principal)) { $principal = Join-Path $journaux "$SERVICE.out.log" }
    if (-not (Test-Path $principal)) {
        Write-Host "Aucun fichier de journal a lire pour l'instant." -ForegroundColor Yellow
        exit 0
    }
    Write-Host ("--- $principal (dernieres $Lignes lignes) ---") -ForegroundColor Cyan
    if ($Suivre) { Get-Content -Path $principal -Tail $Lignes -Wait }
    else         { Get-Content -Path $principal -Tail $Lignes }
    exit 0
}


# ================================================================ -Arreter / -Relancer
if ($Arreter -or $Relancer) {
    Exiger-Elevation
    $svc = Get-Service -Name $SERVICE -ErrorAction SilentlyContinue
    if (-not $svc) {
        Write-Host "Le service '$SERVICE' n'est pas installe : il n'y a rien a arreter." -ForegroundColor Yellow
        exit 1
    }
    if ($Arreter) {
        Stop-Service -Name $SERVICE -Force
        Write-Host "Relais arrete. Il repartira au prochain demarrage de la machine." -ForegroundColor Yellow
        Write-Host "   Pour l'empecher de repartir : .\scripts\installer-relais.ps1 -Desinstaller"
        Afficher-Etat
        exit 0
    }
    Restart-Service -Name $SERVICE -Force
    Write-Host "Relais relance." -ForegroundColor Green
    Afficher-Etat
    if (Afficher-Sante) { exit 0 } else { exit 1 }
}


# ================================================================ -Desinstaller
if ($Desinstaller) {
    Exiger-Elevation
    $svc = Get-Service -Name $SERVICE -ErrorAction SilentlyContinue
    if ($svc) {
        if ($svc.Status -ne "Stopped") { Stop-Service -Name $SERVICE -Force }
        if (Test-Path $superviseur) { & $superviseur uninstall | Out-Null }
        else { & sc.exe delete $SERVICE | Out-Null }
        Start-Sleep -Seconds 2
        Write-Host "Service '$SERVICE' retire. Le relais ne redemarrera plus tout seul." -ForegroundColor Yellow
    }
    else {
        Write-Host "Le service '$SERVICE' n'etait pas installe." -ForegroundColor Yellow
    }
    # On ne supprime NI les secrets NI les compteurs. Un .env perdu, c'est une cle a regenerer ;
    # un quotas.json perdu, c'est un mois de consommation qui repart de zero et un plafond global
    # qui ne protege plus rien. Une desinstallation ne doit jamais couter cela.
    Write-Host ""
    Write-Host "Conserves volontairement (a supprimer a la main si vous le voulez vraiment) :"
    Write-Host "   $fichierEnv    (vos cles)"
    Write-Host "   $donnees       (les compteurs de quota du mois en cours)"
    Write-Host "   $journaux      (les journaux)"
    exit 0
}


# ================================================================ installation
Exiger-Elevation

Write-Host ""
Write-Host "=== Installation du relais IA de VELA en service permanent ===" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------- 0. ce qui doit etre vrai avant
Write-Host "0. Verifications prealables" -ForegroundColor Cyan

if (-not (Test-Path (Join-Path $serveur "relais.py"))) {
    Write-Host "   Introuvable : $serveur\relais.py. Ce script doit rester dans iris\scripts\." -ForegroundColor Red
    exit 1
}

$libre = [math]::Round((Get-PSDrive C).Free / 1GB, 2)
Write-Host "   Espace libre sur C: : $libre Go"
if ($libre -lt $DISQUE_MINIMUM -and -not $IgnorerEspaceDisque) {
    Write-Host ""
    Write-Host "   ARRET : il reste $libre Go sur C:, c'est trop peu pour un serveur permanent." -ForegroundColor Red
    Write-Host "   Ce n'est pas une precaution de principe. Le relais reecrit entierement" -ForegroundColor Yellow
    Write-Host "   donnees\quotas.json DEUX FOIS par requete, et le service ecrit des journaux." -ForegroundColor Yellow
    Write-Host "   Sur un disque plein, chaque appel d'IRIS repond 500 pendant que /sante continue" -ForegroundColor Yellow
    Write-Host "   d'afficher ok:true : la panne est totale et invisible." -ForegroundColor Yellow
    Write-Host "   Liberez au moins $DISQUE_MINIMUM Go (Parametres > Systeme > Stockage), puis relancez."
    Write-Host "   Pour passer outre en connaissance de cause : -IgnorerEspaceDisque" -ForegroundColor Yellow
    exit 1
}
if ($libre -lt $DISQUE_CONFORT) {
    Write-Host "   AVERTISSEMENT : moins de $DISQUE_CONFORT Go libres. Surveillez le disque." -ForegroundColor Yellow
}

# Le depot vit dans Downloads, et l'Assistant Stockage de Windows sait vider ce dossier tout seul.
# Un seul interrupteur dans Parametres separe ce serveur d'un nettoyage automatique.
if ($racine -like "*\Downloads\*") {
    Write-Host "   AVERTISSEMENT : le code est dans Downloads." -ForegroundColor Yellow
    Write-Host "     L'Assistant Stockage de Windows peut vider ce dossier automatiquement." -ForegroundColor Yellow
    Write-Host "     Verifiez Parametres > Systeme > Stockage > Assistant Stockage, ou deplacez" -ForegroundColor Yellow
    Write-Host "     le dossier iris ailleurs (par exemple C:\VELA) avant de compter sur ce service." -ForegroundColor Yellow
}

# Une seule instance, toujours : voir le commentaire sur --workers 1 dans le bloc -Executer.
$svcExistant = Get-Service -Name $SERVICE -ErrorAction SilentlyContinue
if ($svcExistant -and $svcExistant.Status -ne "Stopped") {
    Write-Host "   Le service existe deja et tourne : on l'arrete pour le reinstaller." -ForegroundColor Yellow
    Stop-Service -Name $SERVICE -Force
    Start-Sleep -Seconds 2
}
$occupe = @(Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue)
if ($occupe.Count -gt 0) {
    $pids = ($occupe | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique) -join ", "
    Write-Host ""
    Write-Host "   ARRET : quelque chose ecoute deja sur le port $PORT (pid $pids)." -ForegroundColor Red
    Write-Host "   Deux relais qui partagent donnees\quotas.json se volent leurs compteurs :" -ForegroundColor Yellow
    Write-Host "   le verrou du code ne protege qu'un seul processus. Fermez la fenetre uvicorn" -ForegroundColor Yellow
    Write-Host "   restee ouverte, puis relancez."
    exit 1
}
Write-Host "   Port $PORT libre." -ForegroundColor Green

# ---------------------------------------------------------------- 1. interpreteur et dependances
Write-Host ""
Write-Host "1. Interpreteur Python et dependances" -ForegroundColor Cyan

if (-not (Test-Path $python)) {
    # On prefere l'interpreteur du backend comme BASE de creation : il est deja installe, on sait
    # qu'il fait tourner ce code, et cela evite de tomber sur le faux python.exe du Microsoft Store
    # (un raccourci de 0 octet qui ouvre le Store au lieu de lancer Python).
    $base = Join-Path $racine "backend\.venv\Scripts\python.exe"
    $arguments = @("-m", "venv", $venv)
    if (-not (Test-Path $base)) {
        $trouve = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($trouve) { $base = $trouve.Source }
        else {
            $trouve = Get-Command py.exe -ErrorAction SilentlyContinue
            if (-not $trouve) {
                Write-Host "   Aucun Python trouve. Installez Python 3.11 ou plus recent, puis relancez." -ForegroundColor Red
                exit 1
            }
            $base = $trouve.Source
            $arguments = @("-3", "-m", "venv", $venv)
        }
    }
    Write-Host "   Creation de serveur\.venv a partir de $base ..."
    & $base $arguments
    if (-not (Test-Path $python)) {
        Write-Host "   Echec de la creation de l'environnement." -ForegroundColor Red
        exit 1
    }
    Write-Host "   Environnement cree." -ForegroundColor Green
}
else {
    Write-Host "   serveur\.venv existe deja." -ForegroundColor Green
}

Write-Host "   Installation des dependances (serveur\requirements.txt) ..."
& $python -m pip install --disable-pip-version-check --quiet --requirement $exigences
if ($LASTEXITCODE -ne 0) {
    Write-Host "   Echec de l'installation des dependances." -ForegroundColor Red
    exit 1
}
$version = (& $python --version)
Write-Host "   $version, dependances a jour." -ForegroundColor Green

# On verifie que relais.py s'IMPORTE avant d'en faire un service. Un service qui refuse de demarrer
# a cause d'une faute de frappe se diagnostique dix fois plus mal qu'une erreur affichee ici.
Push-Location $serveur
# On ne redirige RIEN ici. Si l'import échoue, Python écrit lui-même sa trace à l'écran, et c'est
# exactement ce qu'on veut lire. Une redirection `2>&1` serait pire qu'inutile : sous
# $ErrorActionPreference = "Stop", PowerShell 5.1 emballe chaque ligne d'erreur d'un programme
# externe dans un ErrorRecord, ce qui interromprait le script avant qu'il ait pu expliquer.
& $python -c "import relais"
$importOk = ($LASTEXITCODE -eq 0)
Pop-Location
if (-not $importOk) {
    Write-Host "   relais.py ne s'importe pas avec cet interpreteur (trace ci-dessus)." -ForegroundColor Red
    exit 1
}
Write-Host "   relais.py s'importe correctement." -ForegroundColor Green

# ---------------------------------------------------------------- 2. les secrets
Write-Host ""
Write-Host "2. Les secrets (serveur\.env)" -ForegroundColor Cyan

$variables = Lire-FichierEnv $fichierEnv
if (Test-Path $fichierEnv) { Write-Host "   Fichier existant relu : on ne redemande que ce qui manque." }
else { Write-Host "   Aucun fichier .env : creation." }

# Le relais a besoin d'AU MOINS UNE cle amont. Deux choix, selon ce qu'on veut servir :
#   - Anthropic (VELA_ANTHROPIC_KEY, sk-ant-...) : Claude en direct. En test, on ne paie que ce
#     compte-la. Le forfait gratuit, lui, ne pourra pas etre servi sans cle OpenRouter.
#   - OpenRouter (VELA_OPENROUTER_KEY, sk-or-v1-...) : les modeles gratuits ET Claude (via revente).
# On peut donner les deux : Claude part alors chez Anthropic, le gratuit chez OpenRouter.
if (-not $variables["VELA_ANTHROPIC_KEY"] -and -not $variables["VELA_OPENROUTER_KEY"]) {
    Write-Host ""
    Write-Host "   Le relais a besoin d'au moins une cle IA." -ForegroundColor Yellow
    Write-Host "   - Pour du TEST avec Claude en direct : ta cle Anthropic (sk-ant-..., console.anthropic.com)."
    Write-Host "   - Pour le forfait gratuit et/ou Claude via revente : ta cle OpenRouter (sk-or-v1-..., openrouter.ai > Keys)."
    Write-Host "   Laisse vide et appuie sur Entree pour sauter celle que tu ne veux pas. Rien ne s'affiche en tapant."
    $variables["VELA_ANTHROPIC_KEY"] = Lire-SecretCache "   Cle Anthropic (Claude), ou Entree"
    $variables["VELA_OPENROUTER_KEY"] = Lire-SecretCache "   Cle OpenRouter, ou Entree"
    if (-not $variables["VELA_ANTHROPIC_KEY"] -and -not $variables["VELA_OPENROUTER_KEY"]) {
        Write-Host "   Aucune des deux : le relais ne pourrait rien servir. Arret." -ForegroundColor Red
        exit 1
    }
}
else {
    if ($variables["VELA_ANTHROPIC_KEY"])  { Write-Host "   VELA_ANTHROPIC_KEY : deja renseignee (Claude en direct)." -ForegroundColor Green }
    if ($variables["VELA_OPENROUTER_KEY"]) { Write-Host "   VELA_OPENROUTER_KEY : deja renseignee." -ForegroundColor Green }
}

if (-not $variables["VELA_SECRET"]) {
    # Elle signe les jetons d'appareil. Sans elle, relais.py retombe sur une valeur par defaut
    # ECRITE DANS LE CODE, donc publique : n'importe qui fabriquerait un jeton valide et
    # consommerait la cle OpenRouter de Miguel.
    $genere = (& $python -c "import secrets; print(secrets.token_urlsafe(32))")
    $variables["VELA_SECRET"] = $genere.Trim()
    Write-Host "   VELA_SECRET generee automatiquement et enregistree. Elle n'est pas affichee." -ForegroundColor Green
    Write-Host "     (elle signe les jetons d'appareil : la changer invalide tous les jetons deja emis)"
}
else { Write-Host "   VELA_SECRET : deja presente." -ForegroundColor Green }

if (-not $variables["VELA_LICENCES_URL"]) {
    Write-Host ""
    Write-Host "   VELA_LICENCES_URL - l'adresse du serveur de licences, qui sait qui est abonne." -ForegroundColor Yellow
    Write-Host "   Sans elle, le relais retombe sur donnees\abonnes.json et tout le monde est 'gratuit'."
    Write-Host "   En local, le serveur de licences ecoute sur http://127.0.0.1:8080"
    Write-Host "   Laissez vide pour vous en passer pour l'instant."
    $reponse = Read-Host "   Adresse du serveur de licences"
    if ($reponse) { $variables["VELA_LICENCES_URL"] = $reponse.Trim() }
}
else { Write-Host "   VELA_LICENCES_URL : $($variables['VELA_LICENCES_URL'])" -ForegroundColor Green }

if (-not $variables["VELA_ELEVENLABS_KEY"]) {
    Write-Host ""
    Write-Host "   VELA_ELEVENLABS_KEY - la voix des forfaits payants." -ForegroundColor Yellow
    Write-Host "   Sans elle, un abonne Pro paie une voix qu'il n'entendra jamais."
    Write-Host "   Laissez vide si la voix n'est pas encore vendue. Elle ne s'affichera pas."
    $variables["VELA_ELEVENLABS_KEY"] = Lire-SecretCache "   Cle ElevenLabs (vide = passer)"
}
else { Write-Host "   VELA_ELEVENLABS_KEY : deja renseignee." -ForegroundColor Green }

Ecrire-FichierEnv $fichierEnv $variables
Proteger-Fichier $fichierEnv
Write-Host ""
Write-Host "   Ecrit : $fichierEnv" -ForegroundColor Green
Write-Host "   Droits refermes sur :" -ForegroundColor Green
foreach ($regle in (Get-Acl $fichierEnv).Access) {
    Write-Host ("      {0} : {1}" -f $regle.IdentityReference, $regle.FileSystemRights)
}

# Le .env est deja couvert par la ligne « .env » a la racine du .gitignore, mais donnees\ ne l'est
# pas — et abonnes.json contient des courriels de clients. Le binaire du superviseur non plus.
$gitignore = Join-Path $racine ".gitignore"
$aAjouter = @("serveur/donnees/", "serveur/journaux/", "serveur/relais-service.exe", "serveur/.venv/")
if (Test-Path $gitignore) {
    $contenu = @(Get-Content $gitignore)
    $manquants = @($aAjouter | Where-Object { $contenu -notcontains $_ })
    if ($manquants.Count -gt 0) {
        # Ajout en octets bruts plutôt qu'avec Add-Content : en PowerShell 5.1, `-Encoding UTF8`
        # peut insérer une marque d'ordre des octets AU MILIEU du fichier, et git lirait alors ces
        # octets invisibles comme faisant partie du motif — la règle serait silencieusement morte.
        $texte = [Environment]::NewLine +
                 "# relais en service : compteurs, journaux, binaire du superviseur" + [Environment]::NewLine +
                 (($manquants -join [Environment]::NewLine)) + [Environment]::NewLine
        [System.IO.File]::AppendAllText($gitignore, $texte, (New-Object System.Text.UTF8Encoding($false)))
        Write-Host "   .gitignore complete : $($manquants -join ', ')" -ForegroundColor Green
    }
    else { Write-Host "   .gitignore : rien a ajouter." -ForegroundColor Green }
}
else {
    Write-Host "   Pas de .gitignore a la racine : rien verifie." -ForegroundColor Yellow
}

# Creees ici, et non par le service, pour qu'elles heritent des droits de ce dossier : ainsi vous
# gardez la lecture des compteurs et des journaux ecrits par SYSTEM.
foreach ($dossier in @($donnees, $journaux)) {
    if (-not (Test-Path $dossier)) { New-Item -ItemType Directory -Path $dossier | Out-Null }
}

# ---------------------------------------------------------------- 3. le service
Write-Host ""
Write-Host "3. Enregistrement du demarrage automatique (WinSW)" -ForegroundColor Cyan

if (-not (Test-Path $superviseur)) {
    if (-not $Telecharger) {
        Write-Host ""
        Write-Host "   Il manque le superviseur : $superviseur" -ForegroundColor Yellow
        Write-Host "   C'est un binaire tiers d'environ 5 Mo (WinSW), non signe par une autorite"
        Write-Host "   connue : SmartScreen protestera, et c'est normal. Il n'est pas dans le depot."
        Write-Host ""
        Write-Host "   Deux facons de l'obtenir :"
        Write-Host "     - relancer avec -Telecharger :" -ForegroundColor Cyan
        Write-Host "         .\scripts\installer-relais.ps1 -Telecharger"
        Write-Host "     - ou le prendre a la main sur $PAGE_WINSW"
        Write-Host "       (version .NET Framework, x64) et l'enregistrer sous le nom exact :"
        Write-Host "         $superviseur"
        exit 1
    }
    Write-Host "   Telechargement de WinSW ..."
    # PowerShell 5.1 negocie encore TLS 1.0 par defaut ; GitHub le refuse depuis longtemps.
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $obtenu = $false
    foreach ($source in $SOURCES_WINSW) {
        try {
            Write-Host "      essai : $source"
            Invoke-WebRequest -Uri $source -OutFile $superviseur -UseBasicParsing -TimeoutSec 60
            # On verifie que c'est bien un executable Windows : un lien mort renvoie une page HTML
            # avec un code 200, qui s'installerait comme un service qui ne demarre jamais.
            $entete = [System.IO.File]::ReadAllBytes($superviseur)[0..1]
            if ($entete[0] -eq 0x4D -and $entete[1] -eq 0x5A -and (Get-Item $superviseur).Length -gt 100KB) {
                $obtenu = $true
                break
            }
            Write-Host "      ce n'est pas un executable, on essaie l'adresse suivante." -ForegroundColor Yellow
            Remove-Item $superviseur -Force
        }
        catch { Write-Host "      indisponible." -ForegroundColor Yellow }
    }
    if (-not $obtenu) {
        Write-Host "   Aucune adresse n'a fonctionne. Prenez-le a la main sur :" -ForegroundColor Red
        Write-Host "      $PAGE_WINSW"
        Write-Host "   et enregistrez-le sous le nom exact : $superviseur"
        exit 1
    }
    $empreinte = (Get-FileHash -Path $superviseur -Algorithm SHA256).Hash
    Write-Host "   WinSW recupere." -ForegroundColor Green
    Write-Host "   Empreinte SHA-256 : $empreinte" -ForegroundColor Cyan
    Write-Host "   Comparez-la avec celle publiee sur la page de la version avant de faire" -ForegroundColor Yellow
    Write-Host "   confiance a ce binaire : $PAGE_WINSW" -ForegroundColor Yellow
}
else {
    Write-Host "   Superviseur deja present : $superviseur" -ForegroundColor Green
}

# Le XML ne contient AUCUN secret : c'est le seul endroit du dispositif qui se lit en clair, et la
# raison pour laquelle le chargement des cles passe par -Executer et par le .env.
function Echapper-Xml([string]$texte) {
    return $texte.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;")
}
$xmlArguments = Echapper-Xml ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $moiMeme + '" -Executer')
$xmlPowershell = Echapper-Xml (Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe")
$xmlServeur = Echapper-Xml $serveur
$xmlJournaux = Echapper-Xml $journaux

$contenuXml = @"
<?xml version="1.0" encoding="utf-8"?>
<!--
  Configuration du service du relais IA de VELA, lue par WinSW (relais-service.exe).
  Regeneree a chaque passage de scripts\installer-relais.ps1 : ne la modifiez pas a la main.

  Aucun secret ici, volontairement. Ce fichier, les arguments du service et le registre se lisent
  tous en clair : les cles sont dans serveur\.env, charge par -Executer dans le seul processus fils.
-->
<service>
  <id>$SERVICE</id>
  <name>VELA - relais IA</name>
  <description>Donne a IRIS son acces a l'intelligence artificielle, avec la cle de VELA. Ecoute sur 127.0.0.1:$PORT.</description>

  <executable>$xmlPowershell</executable>
  <arguments>$xmlArguments</arguments>
  <workingdirectory>$xmlServeur</workingdirectory>

  <startmode>Automatic</startmode>

  <!-- Relance apres une chute. Le delai evite qu'une panne permanente (disque plein, cle
       illisible) ne se transforme en boucle de redemarrage qui remplit le journal. -->
  <onfailure action="restart" delay="15 sec"/>
  <resetfailure>1 hour</resetfailure>

  <!-- Journal borne. Avec le peu d'espace libre sur ce disque, un journal qui grossit sans limite
       n'est pas un risque theorique : c'est la prochaine panne. 5 Mo x 4 fichiers = 20 Mo au plus,
       par flux. -->
  <logpath>$xmlJournaux</logpath>
  <log mode="roll-by-size">
    <sizeThreshold>5120</sizeThreshold>
    <keepFiles>4</keepFiles>
  </log>

  <!-- On tue d'abord Python, ensuite le PowerShell qui le porte : dans l'autre sens, uvicorn
       resterait orphelin en gardant le port $PORT, et le service suivant ne demarrerait pas. -->
  <stopparentprocessfirst>false</stopparentprocessfirst>
  <stoptimeout>15 sec</stoptimeout>
</service>
"@
# Sans marque d'ordre des octets : le fichier annonce son encodage dans sa déclaration XML, et
# une marque en tête ferait mentir cette déclaration auprès d'un analyseur strict.
[System.IO.File]::WriteAllText($config, $contenuXml, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "   Configuration ecrite : $config" -ForegroundColor Green

if ($svcExistant) {
    Write-Host "   Le service existait : on le retire avant de le reposer proprement."
    & $superviseur uninstall | Out-Null
    Start-Sleep -Seconds 2
}
& $superviseur install
if ($LASTEXITCODE -ne 0) {
    Write-Host "   Echec de l'enregistrement du service." -ForegroundColor Red
    exit 1
}
# Le service tourne sous LocalSystem : c'est le compte par defaut de WinSW, et c'est voulu.
# Voir l'en-tete de ce fichier : sous le compte de Miguel il faudrait stocker le mot de passe du
# compte Microsoft, qui casse le service en silence au prochain changement de mot de passe.
Write-Host "   Service '$SERVICE' enregistre, demarrage automatique, compte LocalSystem." -ForegroundColor Green

Start-Service -Name $SERVICE
Write-Host "   Service demarre." -ForegroundColor Green

# ---------------------------------------------------------------- 4. verification
Write-Host ""
Write-Host "4. Verification" -ForegroundColor Cyan
Afficher-Etat
$vivant = Afficher-Sante

# ---------------------------------------------------------------- 5. ce qu'il faut retenir
Write-Host ""
Write-Host "=== Ou est quoi ===" -ForegroundColor Cyan
Write-Host "   Journaux   : $journaux"
Write-Host "                ($SERVICE.err.log est le journal normal d'uvicorn, .wrapper.log celui du service)"
Write-Host "   Secrets    : $fichierEnv   (lisible par vous et SYSTEM uniquement)"
Write-Host "   Compteurs  : $donnees"
Write-Host "   Config     : $config"
Write-Host "   Ecoute sur : http://127.0.0.1:$PORT"
Write-Host ""
Write-Host "=== Les commandes ===" -ForegroundColor Cyan
Write-Host "   .\scripts\installer-relais.ps1 -Journal            voir les dernieres lignes"
Write-Host "   .\scripts\installer-relais.ps1 -Journal -Suivre    suivre en direct"
Write-Host "   .\scripts\installer-relais.ps1 -Relancer           relancer apres un changement de cle"
Write-Host "   .\scripts\installer-relais.ps1 -Arreter            arreter (repart au prochain demarrage)"
Write-Host "   .\scripts\installer-relais.ps1 -Desinstaller       retirer le service, garder les donnees"
Write-Host ""
Write-Host "=== Ce que ce script ne fait PAS ===" -ForegroundColor Yellow
Write-Host "   - Il n'expose rien a l'exterieur. Le relais n'ecoute que sur 127.0.0.1 : aucun client"
Write-Host "     ne peut l'atteindre tant qu'un tunnel sortant n'est pas en place. Le dossier ne doit"
Write-Host "     JAMAIS etre expose en ouvrant un port du routeur."
Write-Host "   - Il ne fait pas rallumer la machine apres une coupure de courant. Cela se regle dans"
Write-Host "     le BIOS/UEFI ('Restore on AC Power Loss' = Power On), et nulle part dans Windows."
Write-Host "   - Il ne change pas backend\iris\config.py : sa valeur par defaut reste"
Write-Host "     https://relais.vela.app. Tant que le tunnel n'a pas de nom stable, les IRIS"
Write-Host "     installees continueront de s'adresser a une adresse qui ne repond pas."
Write-Host ""

if ($vivant) {
    Write-Host "Le relais tourne et repartira tout seul au demarrage de la machine." -ForegroundColor Green
    exit 0
}
Write-Host "Le service est installe mais ne repond pas correctement : voir plus haut." -ForegroundColor Red
exit 1
