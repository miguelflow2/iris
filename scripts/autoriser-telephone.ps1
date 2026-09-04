# Autorise le téléphone à joindre IRIS sur le WiFi de la maison.
#
# À exécuter EN ADMINISTRATEUR. Deux choses peuvent bloquer, et il faut souvent traiter les deux :
#
#   1. Aucune règle de pare-feu n'ouvre le port : Windows refuse toute connexion entrante.
#   2. Le réseau est classé « public » : même avec la règle, elle ne s'applique pas, parce qu'une
#      règle de profil privé est ignorée sur un réseau public.
#
# Le point 2 demande votre accord explicite, parce que classer un réseau « privé » rend votre
# ordinateur visible aux autres appareils qui s'y trouvent. C'est ce qu'on veut chez soi. Ce n'est
# PAS ce qu'on veut sur le WiFi d'une école, d'un café ou d'un aéroport.
#
#   Chez vous :   .\autoriser-telephone.ps1 -ReseauPrive
#   Ailleurs :    .\autoriser-telephone.ps1              (la règle est créée, sans toucher au réseau)
#   Tout annuler : .\autoriser-telephone.ps1 -Retirer

param(
    [switch]$Retirer,
    [switch]$ReseauPrive
)

$NOM = "IRIS - acces telephone (reseau prive)"
$PORT = 8765

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "Il faut lancer ce script en administrateur." -ForegroundColor Red
    Write-Host "Menu Demarrer > tapez 'powershell' > clic droit > 'Executer en tant qu'administrateur'."
    exit 1
}

if ($Retirer) {
    Get-NetFirewallRule -DisplayName $NOM -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Write-Host "Regle retiree. Le telephone ne peut plus joindre IRIS." -ForegroundColor Yellow
    exit 0
}

# ---------------------------------------------------------------- 1. la regle de pare-feu
Get-NetFirewallRule -DisplayName $NOM -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $NOM -Direction Inbound -Action Allow -Protocol TCP `
    -LocalPort $PORT -Profile Private `
    -Description "Permet au telephone de joindre IRIS sur le reseau local. Reseau prive uniquement." | Out-Null
Write-Host "1. Regle de pare-feu creee : port $PORT, reseau prive uniquement." -ForegroundColor Green

# ---------------------------------------------------------------- 2. le profil du reseau
$publics = @(Get-NetConnectionProfile | Where-Object { $_.NetworkCategory -eq 'Public' })
if ($publics.Count -eq 0) {
    Write-Host "2. Le reseau est deja classe prive : la regle s'applique." -ForegroundColor Green
}
elseif ($ReseauPrive) {
    foreach ($p in $publics) {
        Set-NetConnectionProfile -InterfaceIndex $p.InterfaceIndex -NetworkCategory Private
        Write-Host "2. Reseau '$($p.Name)' passe en PRIVE." -ForegroundColor Green
    }
    Write-Host "   (pour revenir en arriere : Set-NetConnectionProfile -InterfaceIndex <n> -NetworkCategory Public)"
}
else {
    Write-Host ""
    Write-Host "2. BLOQUANT : votre reseau est classe PUBLIC, la regle ne s'appliquera pas." -ForegroundColor Yellow
    foreach ($p in $publics) { Write-Host "      - $($p.Name)" }
    Write-Host "   Si c'est votre reseau a la maison, relancez avec -ReseauPrive :" -ForegroundColor Yellow
    Write-Host "      .\scripts\autoriser-telephone.ps1 -ReseauPrive"
    Write-Host "   Ne le faites PAS sur le WiFi d'une ecole, d'un cafe ou d'un aeroport." -ForegroundColor Yellow
}

# ---------------------------------------------------------------- 3. verification et adresse
Write-Host ""
$regle = Get-NetFirewallPortFilter -ErrorAction SilentlyContinue |
         Where-Object { $_.LocalPort -eq $PORT } |
         ForEach-Object { $_ | Get-NetFirewallRule -ErrorAction SilentlyContinue } |
         Where-Object { $_.Enabled -eq 'True' -and $_.Direction -eq 'Inbound' }
$prive = @(Get-NetConnectionProfile | Where-Object { $_.NetworkCategory -eq 'Private' }).Count -gt 0
if ($regle -and $prive) { Write-Host "Tout est en place." -ForegroundColor Green }
else { Write-Host "Il manque encore quelque chose (regle: $([bool]$regle), reseau prive: $prive)." -ForegroundColor Yellow }

$ecoute = (netstat -ano | Select-String ":$PORT.*LISTENING").Count -gt 0
if (-not $ecoute) { Write-Host "IRIS n'ecoute pas sur le port $PORT : lancez-la, et activez l'acces telephone." -ForegroundColor Yellow }

Write-Host ""
Write-Host "Adresse a ouvrir dans SAFARI sur l'iPhone :" -ForegroundColor Cyan
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
        $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*'
      } | Select-Object -First 1).IPAddress

# En mode administrateur, $env:APPDATA peut viser un autre profil que celui de l'utilisateur.
$chemin = "$env:APPDATA\IRIS\iris-data\remote-token"
if (-not (Test-Path $chemin)) {
    $trouve = Get-ChildItem "C:\Users" -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $c = Join-Path $_.FullName "AppData\Roaming\IRIS\iris-data\remote-token"
        if (Test-Path $c) { $c }
    } | Select-Object -First 1
    if ($trouve) { $chemin = $trouve }
}
$jeton = (Get-Content $chemin -Raw -ErrorAction SilentlyContinue)
if ($jeton) { Write-Host ("   http://{0}:{1}/m?token={2}" -f $ip, $PORT, $jeton.Trim()) }
else { Write-Host "   Activez d'abord l'acces telephone dans IRIS (Parametres > Telephone)." }
