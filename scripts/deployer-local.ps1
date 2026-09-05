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

if (-not (Test-Path (Join-Path $source "resources\app.asar"))) {
    Write-Host "Rien a deployer : $source ne contient pas d'application construite." -ForegroundColor Red
    exit 1
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

Write-Host "Copie de resources vers $cible ..."
$journal = robocopy (Join-Path $source "resources") (Join-Path $cible "resources") /MIR /NFL /NDL /NJH /NJS /NP
$code = $LASTEXITCODE
if ($code -ge 8) {
    Write-Host "Echec de la copie (robocopy $code)." -ForegroundColor Red
    $journal | Select-Object -Last 20
    exit 1
}

$version = (Get-Content (Join-Path $racine "package.json") -Raw | ConvertFrom-Json).version
Write-Host "Deploye : IRIS $version" -ForegroundColor Green

if (-not $SansRelance) {
    Start-Process (Join-Path $cible "IRIS.exe")
    Write-Host "IRIS relancee."
}
