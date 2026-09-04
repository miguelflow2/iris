# Écrit l'icône VELA dans les exécutables produits.
#
# Pourquoi ce script existe : electron-builder confie ce travail à `rcedit`, qu'il livre dans le
# paquet `winCodeSign`. Or l'extraction de ce paquet crée des liens symboliques (des bibliothèques
# macOS dont Windows n'a que faire), et Windows refuse les liens symboliques sans droits
# particuliers. L'extraction échoue donc à moitié, en silence, et l'application garde l'icône
# grise d'Electron sans qu'aucune erreur ne le dise clairement.
#
# On applique donc l'icône nous-mêmes, après la construction. Aucun droit spécial requis.

param([string]$Cible = "release\win-unpacked\IRIS.exe")

$racine = Split-Path -Parent $PSScriptRoot
$ico = Join-Path $racine "build\icon.ico"
if (-not (Test-Path $ico)) { Write-Host "icon.ico introuvable : lancez d'abord scripts\make-icon.py" -ForegroundColor Red; exit 1 }

$rcedit = Get-ChildItem "$env:LOCALAPPDATA\electron-builder\Cache\winCodeSign" -Recurse -Filter "rcedit-x64.exe" -ErrorAction SilentlyContinue |
          Select-Object -First 1 -ExpandProperty FullName
if (-not $rcedit) { Write-Host "rcedit introuvable : construisez une fois avec electron-builder pour le telecharger." -ForegroundColor Red; exit 1 }

$exe = if ([System.IO.Path]::IsPathRooted($Cible)) { $Cible } else { Join-Path $racine $Cible }
if (-not (Test-Path $exe)) { Write-Host "executable introuvable : $exe" -ForegroundColor Red; exit 1 }

& $rcedit $exe --set-icon $ico
if ($LASTEXITCODE -ne 0) { Write-Host "rcedit a echoue ($LASTEXITCODE)" -ForegroundColor Red; exit 1 }

# Verification : l'icone doit etre l'encre du logo, pas le gris d'Electron.
Add-Type -AssemblyName System.Drawing
$bmp = [System.Drawing.Icon]::ExtractAssociatedIcon($exe).ToBitmap()
$encre = 0
for ($x = 0; $x -lt $bmp.Width; $x += 2) { for ($y = 0; $y -lt $bmp.Height; $y += 2) {
    $p = $bmp.GetPixel($x, $y)
    if ([Math]::Abs($p.R - 27) -lt 24 -and [Math]::Abs($p.G - 20) -lt 24 -and [Math]::Abs($p.B - 14) -lt 24) { $encre++ }
} }
if ($encre -lt 40) { Write-Host "L'icone ne semble pas etre la voile ($encre px d'encre)." -ForegroundColor Yellow; exit 1 }
Write-Host "Icone VELA appliquee et verifiee : $exe" -ForegroundColor Green
