# Empaquette le backend Python en dossier autonome (backend\dist\iris-backend) via PyInstaller.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\backend"

if (-not (Test-Path ".venv")) {
  Write-Host "[backend] création du venv..."
  python -m venv .venv
}
Write-Host "[backend] installation des dépendances..."
& .\.venv\Scripts\python -m pip install -q -r requirements-dev.txt

Write-Host "[backend] tests..."
& .\.venv\Scripts\python -m pytest tests -q
if ($LASTEXITCODE -ne 0) { throw "Les tests backend échouent, build annulé." }

Write-Host "[backend] PyInstaller..."
& .\.venv\Scripts\python -m PyInstaller --noconfirm --clean iris-backend.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller a échoué." }

Write-Host "[backend] vérification de l'exécutable..."
$exe = Join-Path "dist\iris-backend" "iris-backend.exe"
$proc = Start-Process -FilePath $exe -ArgumentList "--help" -NoNewWindow -PassThru -Wait
if ($proc.ExitCode -ne 0) { throw "L'exécutable ne démarre pas (code $($proc.ExitCode))." }

# Autotest : charge réellement les bibliothèques natives (winrt, OCR, vosk, audio) dans l'ordre de l'app.
# Sans lui, une DLL incompatible (ex. msvcp140 de winrt) passe inaperçue jusqu'à l'usage.
Write-Host "[backend] autotest des bibliotheques natives..."
$proc = Start-Process -FilePath $exe -ArgumentList "--selftest" -NoNewWindow -PassThru -Wait
if ($proc.ExitCode -ne 0) { throw "Autotest en echec (code $($proc.ExitCode)) : une bibliotheque native ne se charge pas." }
Write-Host "[backend] OK -> backend\dist\iris-backend"
