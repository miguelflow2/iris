# Autorise le téléphone à joindre IRIS sur le WiFi de la maison.
#
# À exécuter EN ADMINISTRATEUR une seule fois. Windows bloque par défaut toute connexion
# entrante ; sans cette règle, la page mobile est injoignable depuis le téléphone même si
# IRIS écoute correctement.
#
# Portée volontairement étroite : un seul port, protocole TCP, et uniquement sur les réseaux
# marqués « privé » (votre maison). Sur un WiFi public, la règle ne s'applique pas.
#
# Pour tout annuler : .\autoriser-telephone.ps1 -Retirer

param([switch]$Retirer)

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

Get-NetFirewallRule -DisplayName $NOM -ErrorAction SilentlyContinue | Remove-NetFirewallRule

New-NetFirewallRule -DisplayName $NOM -Direction Inbound -Action Allow -Protocol TCP `
    -LocalPort $PORT -Profile Private `
    -Description "Permet au telephone de joindre IRIS sur le reseau local. Reseau prive uniquement." | Out-Null

Write-Host "Regle creee : port $PORT autorise, reseau prive uniquement." -ForegroundColor Green

# Le profil du WiFi doit etre « prive », sinon la regle ne s'applique pas.
$publics = Get-NetConnectionProfile | Where-Object { $_.NetworkCategory -eq 'Public' }
if ($publics) {
    Write-Host ""
    Write-Host "ATTENTION : votre reseau est classe PUBLIC, la regle ne s'appliquera pas." -ForegroundColor Yellow
    foreach ($p in $publics) { Write-Host "   - $($p.Name)" }
    Write-Host "Pour le passer en prive (a ne faire que chez vous) :"
    foreach ($p in $publics) {
        Write-Host "   Set-NetConnectionProfile -InterfaceIndex $($p.InterfaceIndex) -NetworkCategory Private"
    }
}

Write-Host ""
Write-Host "Adresse a ouvrir sur le telephone :" -ForegroundColor Cyan
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
        $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*'
      } | Select-Object -First 1).IPAddress
$jeton = (Get-Content "$env:APPDATA\IRIS\iris-data\remote-token" -Raw -ErrorAction SilentlyContinue)
if ($jeton) {
    Write-Host ("   http://{0}:{1}/m?token={2}" -f $ip, $PORT, $jeton.Trim())
} else {
    Write-Host "   Activez d'abord l'acces telephone dans IRIS (Parametres > Telephone)."
}
