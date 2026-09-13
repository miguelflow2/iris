# =============================================================================
# Fabrique le paquet de code à envoyer sur la VM Oracle : vela-vm-bundle.zip
#
# Il contient serveur/ + server/ + deploy/ MAIS PAS :
#   - les .venv (binaires Windows, inutilisables sur Linux ARM)
#   - les .env (SECRETS — transférés à part, avec des clés fraîches)
#   - les bases *.db, les dossiers sortie/ journaux/ donnees/, les caches
#
# À lancer dans PowerShell sur le PC :
#   powershell -ExecutionPolicy Bypass -File C:\Users\migue\Downloads\startup\iris\deploy\oracle\faire-bundle.ps1
# =============================================================================
$ErrorActionPreference = "Stop"

$src   = "C:\Users\migue\Downloads\startup\iris"
$stage = Join-Path $env:TEMP "vela-vm-bundle"
$zip   = Join-Path $env:USERPROFILE "Downloads\vela-vm-bundle.zip"

$excludeDirs  = @(".venv","__pycache__",".pytest_cache","sortie","journaux","donnees",
                  "node_modules",".gradle",".idea","build",".git")
$excludeFiles = @(".env","*.db","*.db-shm","*.db-wal","*.sqlite","*.sqlite3","*.pyc")

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
if (Test-Path $zip)   { Remove-Item $zip -Force }
New-Item -ItemType Directory -Path $stage | Out-Null

foreach ($f in @("serveur","server","deploy")) {
  $from = Join-Path $src $f
  $to   = Join-Path $stage $f
  # robocopy : /E = sous-dossiers (même vides sauf exclus), /XD = dossiers exclus, /XF = fichiers exclus
  robocopy $from $to /E /XD $excludeDirs /XF $excludeFiles /NFL /NDL /NJH /NJS /NP | Out-Null
}

Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
Remove-Item $stage -Recurse -Force

$mo = [math]::Round((Get-Item $zip).Length / 1MB, 2)
Write-Host ""
Write-Host "Bundle pret : $zip  ($mo Mo)" -ForegroundColor Green
Write-Host "Envoie-le sur la VM (remplace IP_PUBLIQUE et le chemin de ta cle) :"
Write-Host "  scp -i `$HOME\.ssh\id_ed25519 `"$zip`" ubuntu@IP_PUBLIQUE:/tmp/" -ForegroundColor Cyan
