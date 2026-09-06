# Installe la version construite par-dessus l'IRIS déjà installée sur cette machine.
#
# Sert à essayer une correction sans refaire tout l'installateur. On remplace le contenu de
# `resources` (le backend et l'application), rien d'autre : les données de l'utilisateur vivent
# dans %APPDATA%\IRIS et ne sont jamais touchées.
#
#   .\scripts\deployer-local.ps1            # ferme IRIS, remplace, relance
#   .\scripts\deployer-local.ps1 -SansRelance
#
# Prérequis : avoir construit (npm run backend:build ; npm run build ; npx electron-builder --win --dir).

param([switch]$SansRelance)

$ErrorActionPreference = "Stop"
$racine = Split-Path -Parent $PSScriptRoot
$source = Join-Path $racine "release\win-unpacked"
$cible = Join-Path $env:LOCALAPPDATA "Programs\IRIS"

# Deux facons de deployer. Complete quand electron-builder a produit release/win-unpacked ;
# backend seul quand on n'a reconstruit que le sidecar Python — le cas le plus frequent, et le
# seul possible quand release a ete supprime pour liberer du disque.
$backendSeul = Join-Path $racine "backend\dist\iris-backend"
$complet = Test-Path (Join-Path $source "resources\app.asar")
$backendPret = Test-Path (Join-Path $backendSeul "iris-backend.exe")
if (-not $complet -and -not $backendPret) {
    Write-Host "Rien a deployer : aucune construction dans release ni dans backend/dist." -ForegroundColor Red
    Write-Host "Construisez d abord : npm run backend:build"
    exit 1
}
if (-not $complet) {
    Write-Host "Interface absente de release : deploiement du BACKEND SEUL." -ForegroundColor Yellow
}
if (-not (Test-Path $cible)) {
    Write-Host "IRIS n'est pas installee dans $cible." -ForegroundColor Red
    Write-Host "Lancez l'installateur une premiere fois : release\IRIS-Setup-<version>.exe"
    exit 1
}

# On ne remplace jamais des fichiers en cours d'utilisation : la copie echouerait a moitie,
# et l'application resterait dans un etat batard.
$ouverte = Get-Process IRIS -ErrorAction SilentlyContinue
if ($ouverte) {
    Write-Host "Fermeture d'IRIS..." -ForegroundColor Yellow
    $ouverte | Stop-Process -Force
    Start-Sleep -Seconds 2
}

if ($complet) {
    Write-Host "Copie de resources vers $cible ..."
    $journal = robocopy (Join-Path $source "resources") (Join-Path $cible "resources") /MIR /NFL /NDL /NJH /NJS /NP
} else {
    Write-Host "Copie du backend seul vers $cible ..."
    $journal = robocopy $backendSeul (Join-Path $cible "resources\backend") /MIR /NFL /NDL /NJH /NJS /NP
}
# Le backend fraichement construit passe TOUJOURS en dernier, par-dessus tout le reste.
#
# Bogue du 5 septembre 2026, et il a coute une soiree entiere. release/win-unpacked existait,
# construit le matin ; le script le prenait donc comme source complete et recopiait CE backend-la.
# Resultat : plusieurs heures de travail construites, commitees, annoncees deployees — et jamais
# executees. Le binaire installe datait de 7h55 alors que la construction datait de 21h17.
if ($backendPret) {
    Write-Host "Recouvrement par le backend fraichement construit..."
    $recouvrement = robocopy $backendSeul (Join-Path $cible "resources\backend") /MIR /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) {
        Write-Host "Echec du recouvrement du backend (robocopy $LASTEXITCODE)." -ForegroundColor Red
        $recouvrement | Select-Object -Last 10
        exit 1
    }
}
$code = $LASTEXITCODE
if ($code -ge 8) {
    Write-Host "Echec de la copie (robocopy $code)." -ForegroundColor Red
    $journal | Select-Object -Last 20
    exit 1
}

# VERIFICATION, avant d'annoncer quoi que ce soit.
#
# Le 5 septembre 2026, ce script a annonce "Deploye" pendant des heures alors qu'il recopiait un
# backend construit le matin meme. Le travail etait construit, teste, commite — et jamais execute.
# Une annonce fausse coute plus cher qu'un echec franc : on cherche le bogue dans le code neuf
# pendant que la machine fait tourner l'ancien.
if ($backendPret) {
    $source_exe = Join-Path $backendSeul "iris-backend.exe"
    $cible_exe = Join-Path $cible "resources\backend\iris-backend.exe"
    if (-not (Test-Path $cible_exe)) {
        Write-Host "Le backend n'est pas arrive a destination." -ForegroundColor Red
        exit 1
    }
    $a = (Get-FileHash $source_exe -Algorithm SHA256).Hash
    $b = (Get-FileHash $cible_exe -Algorithm SHA256).Hash
    if ($a -ne $b) {
        Write-Host "LE BINAIRE INSTALLE N'EST PAS CELUI QU'ON VIENT DE CONSTRUIRE." -ForegroundColor Red
        Write-Host ("  construit : {0}  {1}" -f (Get-Item $source_exe).LastWriteTime, $a.Substring(0,16))
        Write-Host ("  installe  : {0}  {1}" -f (Get-Item $cible_exe).LastWriteTime, $b.Substring(0,16))
        exit 1
    }
    Write-Host ("Binaire verifie : {0} ({1}...)" -f (Get-Item $cible_exe).LastWriteTime, $a.Substring(0,12)) -ForegroundColor Green
}

$version = (Get-Content (Join-Path $racine "package.json") -Raw | ConvertFrom-Json).version
Write-Host "Deploye : IRIS $version" -ForegroundColor Green

if (-not $SansRelance) {
    Start-Process (Join-Path $cible "IRIS.exe")
    Write-Host "IRIS relancee."
}
