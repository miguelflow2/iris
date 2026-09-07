# Deploie le RELAIS VELA et l'expose sur Internet, pour qu'un client installe ait un cerveau sans
# coller sa propre cle.
#
# Ce script orchestre trois choses :
#   1. Le relais tourne en service permanent (via installer-relais.ps1, deja complet).
#   2. Un tunnel Cloudflare l'expose en HTTPS, SANS ouvrir aucun port du routeur.
#   3. Il verifie que le relais repond a travers le tunnel, et donne l'adresse a mettre dans IRIS.
#
# DEUX MODES DE TUNNEL, et il faut comprendre la difference :
#
#   RAPIDE (par defaut) : « cloudflared tunnel --url ... ». Aucun compte, aucun domaine, une adresse
#   HTTPS en trente secondes (https://qqch.trycloudflare.com). PARFAIT pour essayer ce week-end.
#   MAIS l'adresse CHANGE a chaque redemarrage du tunnel : inutilisable comme adresse figee dans une
#   app installee chez des clients. C'est un banc d'essai, pas une mise en production.
#
#   NOMME (-Domaine mondomaine.com -Jeton <jeton>) : une adresse STABLE (https://relais.mondomaine.com)
#   qui survit aux redemarrages. C'est ce qu'il faut pour un vrai produit. Exige un domaine et un
#   compte Cloudflare (gratuit) : ce sont les deux seules choses que le script ne peut pas fabriquer.
#
# Usage :
#   .\scripts\deployer-serveur.ps1 -Telecharger        (recupere cloudflared la premiere fois)
#   .\scripts\deployer-serveur.ps1                      (mode rapide : adresse d'essai)
#   .\scripts\deployer-serveur.ps1 -Domaine vela.app -Jeton eyJ...   (adresse stable)
#   .\scripts\deployer-serveur.ps1 -Arreter            (coupe le tunnel, laisse le relais)
#   .\scripts\deployer-serveur.ps1 -Etat               (ou en est-on ?)

param(
    [switch]$Telecharger,
    [switch]$Arreter,
    [switch]$Etat,
    [string]$Domaine = "",
    [string]$Jeton = "",
    [switch]$IgnorerEspaceDisque
)

$ErrorActionPreference = "Stop"

$racine       = Split-Path -Parent $PSScriptRoot
$installRelais = Join-Path $PSScriptRoot "installer-relais.ps1"
$outils       = Join-Path $racine "serveur\outils"
$cloudflared  = Join-Path $outils "cloudflared.exe"
$journalTunnel = Join-Path $racine "serveur\journaux\tunnel.log"
$adresseFichier = Join-Path $racine "serveur\donnees\adresse-publique.txt"
$PORT_RELAIS  = 8100
$SANTE_LOCALE = "http://127.0.0.1:$PORT_RELAIS/sante"
$TACHE_TUNNEL = "VelaTunnel"

function Titre($t)     { Write-Host ""; Write-Host $t -ForegroundColor Cyan }
function Ok($t)        { Write-Host "  [ok] $t" -ForegroundColor Green }
function Attention($t) { Write-Host "  [!]  $t" -ForegroundColor Yellow }
function Bloquant($t)  { Write-Host "  [X]  $t" -ForegroundColor Red }

function Test-Administrateur {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-SanteLocale {
    try {
        $r = Invoke-WebRequest $SANTE_LOCALE -UseBasicParsing -TimeoutSec 5
        return ($r.Content -match '"ok"\s*:\s*true')
    } catch { return $false }
}

# ---------------------------------------------------------------- etat
if ($Etat) {
    Titre "Etat du serveur VELA"
    if (Test-SanteLocale) { Ok "Le relais repond en local sur le port $PORT_RELAIS." }
    else { Attention "Le relais ne repond PAS en local. Lancez d'abord .\scripts\installer-relais.ps1" }
    $tache = Get-ScheduledTask -TaskName $TACHE_TUNNEL -ErrorAction SilentlyContinue
    if ($tache) {
        $info = Get-ScheduledTaskInfo -TaskName $TACHE_TUNNEL -ErrorAction SilentlyContinue
        Ok "Tunnel enregistre (etat : $($tache.State), derniere execution : $($info.LastRunTime))."
    } else { Attention "Aucun tunnel enregistre." }
    if (Test-Path $adresseFichier) {
        Write-Host ""
        Write-Host "  Adresse publique connue :" -ForegroundColor Cyan
        Write-Host "     $(Get-Content $adresseFichier -Raw)".Trim()
        Write-Host "  A mettre dans IRIS : Reglages > Moteurs IA > relais, ou le champ relay_server."
    }
    return
}

# ---------------------------------------------------------------- arreter
if ($Arreter) {
    Titre "Arret du tunnel"
    Get-ScheduledTask -TaskName $TACHE_TUNNEL -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false -ErrorAction SilentlyContinue
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Ok "Tunnel coupe. Le relais, lui, continue de tourner en local (voir installer-relais.ps1 -Arreter pour l'arreter aussi)."
    return
}

# ---------------------------------------------------------------- telecharger cloudflared
if ($Telecharger) {
    Titre "Telechargement de cloudflared"
    if (Test-Path $cloudflared) {
        Ok "cloudflared est deja la ($cloudflared)."
    } else {
        New-Item -ItemType Directory -Force -Path $outils | Out-Null
        $url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
        Write-Host "  Depuis $url" -ForegroundColor DarkGray
        Write-Host "  cloudflared est le logiciel officiel de Cloudflare (gratuit, source ouverte) qui ouvre un" -ForegroundColor DarkGray
        Write-Host "  tunnel SORTANT : votre ordinateur se connecte a Cloudflare, jamais l'inverse. Aucun port ouvert." -ForegroundColor DarkGray
        try {
            Invoke-WebRequest $url -OutFile $cloudflared -UseBasicParsing
            Ok "cloudflared installe."
        } catch {
            Bloquant "Telechargement impossible : $($_.Exception.Message)"
            Write-Host "  Recuperez-le a la main sur github.com/cloudflare/cloudflared/releases et placez cloudflared.exe dans $outils"
            exit 1
        }
    }
    Write-Host ""
    Write-Host "  Relancez maintenant sans -Telecharger pour deployer." -ForegroundColor Cyan
    return
}

# ---------------------------------------------------------------- 1. le relais tourne
Titre "1. Le relais VELA"
if (Test-SanteLocale) {
    Ok "Le relais repond deja en local sur le port $PORT_RELAIS."
} else {
    Attention "Le relais ne repond pas encore : je lance installer-relais.ps1."
    if (-not (Test-Path $installRelais)) { Bloquant "installer-relais.ps1 introuvable."; exit 1 }
    $args = @()
    if ($IgnorerEspaceDisque) { $args += "-IgnorerEspaceDisque" }
    & powershell -ExecutionPolicy Bypass -File $installRelais @args
    Start-Sleep -Seconds 4
    if (-not (Test-SanteLocale)) {
        Bloquant "Le relais ne repond toujours pas. Corrigez avec installer-relais.ps1 avant d'exposer quoi que ce soit."
        Write-Host "  (Un relais qui ne repond pas en local ne repondra pas non plus a travers le tunnel.)"
        exit 1
    }
    Ok "Relais en service."
}

# ---------------------------------------------------------------- 2. cloudflared present ?
Titre "2. Le tunnel"
if (-not (Test-Path $cloudflared)) {
    Bloquant "cloudflared n'est pas installe."
    Write-Host "  Lancez d'abord : .\scripts\deployer-serveur.ps1 -Telecharger"
    exit 1
}
New-Item -ItemType Directory -Force -Path (Split-Path $journalTunnel) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $adresseFichier) | Out-Null

if ($Domaine -and $Jeton) {
    # ---- mode NOMME : adresse stable ----
    Titre "   Mode nomme (adresse stable) : $Domaine"
    Write-Host "  Le jeton fourni fait tourner un tunnel Cloudflare deja configure dans votre compte." -ForegroundColor DarkGray
    $action = New-ScheduledTaskAction -Execute $cloudflared -Argument "tunnel run --token $Jeton"
    $decl   = New-ScheduledTaskTrigger -AtStartup
    $princ  = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
    if (-not (Test-Administrateur)) {
        Attention "Enregistrer un demarrage automatique demande les droits administrateur. Je lance le tunnel pour CETTE session seulement."
        Start-Process $cloudflared -ArgumentList "tunnel run --token $Jeton" -WindowStyle Hidden
    } else {
        Get-ScheduledTask -TaskName $TACHE_TUNNEL -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false -ErrorAction SilentlyContinue
        Register-ScheduledTask -TaskName $TACHE_TUNNEL -Action $action -Trigger $decl -Principal $princ -Description "Tunnel Cloudflare du relais VELA" | Out-Null
        Start-ScheduledTask -TaskName $TACHE_TUNNEL
        Ok "Tunnel nomme enregistre au demarrage."
    }
    $adresse = "https://$Domaine"
    Set-Content -Path $adresseFichier -Value $adresse -Encoding utf8
    Start-Sleep -Seconds 6
} else {
    # ---- mode RAPIDE : adresse d'essai, ephemere ----
    Titre "   Mode rapide (adresse d'essai)"
    Attention "Cette adresse CHANGERA a chaque redemarrage du tunnel : parfaite pour essayer, a NE PAS figer dans une app livree a des clients. Pour une adresse stable, relancez avec -Domaine et -Jeton."
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    if (Test-Path $journalTunnel) { Remove-Item $journalTunnel -Force -ErrorAction SilentlyContinue }
    Start-Process $cloudflared -ArgumentList "tunnel --url $SANTE_LOCALE --logfile `"$journalTunnel`" --loglevel info" -WindowStyle Hidden
    Write-Host "  Ouverture du tunnel..." -ForegroundColor DarkGray
    $adresse = ""
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 2
        if (Test-Path $journalTunnel) {
            $m = Select-String -Path $journalTunnel -Pattern "https://[-a-z0-9]+\.trycloudflare\.com" -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($m) { $adresse = ($m.Matches[0].Value); break }
        }
    }
    if (-not $adresse) {
        Bloquant "Le tunnel ne s'est pas ouvert (aucune adresse dans $journalTunnel). Verifiez la connexion Internet."
        exit 1
    }
    Set-Content -Path $adresseFichier -Value $adresse -Encoding utf8
    Ok "Tunnel ouvert."
}

# ---------------------------------------------------------------- 3. verification a travers le tunnel
Titre "3. Verification"
$adresse = (Get-Content $adresseFichier -Raw).Trim()
$ok = $false
for ($i = 0; $i -lt 10; $i++) {
    try {
        $r = Invoke-WebRequest "$adresse/sante" -UseBasicParsing -TimeoutSec 8
        if ($r.Content -match '"ok"\s*:\s*true') { $ok = $true; break }
    } catch { Start-Sleep -Seconds 3 }
}
if ($ok) { Ok "Le relais repond a travers Internet : $adresse/sante" }
else { Attention "Le tunnel est ouvert mais /sante ne repond pas encore a travers lui. Reessayez -Etat dans une minute." }

Write-Host ""
Write-Host "====================================================================" -ForegroundColor Green
Write-Host "  ADRESSE PUBLIQUE DU RELAIS :" -ForegroundColor Green
Write-Host "     $adresse" -ForegroundColor White
Write-Host ""
Write-Host "  A METTRE DANS IRIS pour que le cerveau vienne de VELA (et non de la cle" -ForegroundColor Cyan
Write-Host "  personnelle du client) : le champ relay_server, ou Reglages > Moteurs IA." -ForegroundColor Cyan
Write-Host "  Sur une machine cliente, c'est cette adresse qui donne acces a Claude selon" -ForegroundColor Cyan
Write-Host "  l'abonnement, sans qu'il ait la moindre cle a coller." -ForegroundColor Cyan
Write-Host "====================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Verifier plus tard : .\scripts\deployer-serveur.ps1 -Etat"
Write-Host "  Couper le tunnel   : .\scripts\deployer-serveur.ps1 -Arreter"
