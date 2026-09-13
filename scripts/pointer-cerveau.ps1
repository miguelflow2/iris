# Fait pointer IRIS vers l'adresse STABLE du cerveau (le relais VELA).
#
# Une IRIS installee cherche son cerveau a l'adresse `relay_server`. Par defaut, cette adresse est
# ecrite EN DUR dans le code (backend\iris\config.py) : c'est elle que porteront toutes les copies
# livrees. Ce script remplace proprement cette valeur par defaut le jour ou le vrai domaine existe,
# et met aussi a jour les reglages LIVE de cette machine (le dossier de donnees).
#
# Il NE deploie rien, n'ouvre aucun tunnel, ne touche AUCUNE cle secrete, et ne touche PAS a l'agent
# vocal ElevenLabs (ce repointage-la se fait a part, avec la cle de gestion ElevenLabs, hors de ce
# script). Voir docs\DOMAINE-CERVEAU.md pour la marche complete.
#
# Usage :
#   .\scripts\pointer-cerveau.ps1 -Adresse https://relais.mondomaine.com
#   .\scripts\pointer-cerveau.ps1 -Adresse https://relais.mondomaine.com -DryRun   (montre sans ecrire)
#
# Options avancees (tests / cas particuliers) :
#   -Fichier <chemin>   cible un autre config.py que celui du depot (utilise par les tests)
#   -SansLive           n'ecrit QUE le defaut du code, sans toucher aux reglages LIVE de la machine

param(
    [Parameter(Mandatory = $true)][string]$Adresse,
    [switch]$DryRun,
    [string]$Fichier = "",
    [switch]$SansLive
)

$ErrorActionPreference = "Stop"

$racine       = Split-Path -Parent $PSScriptRoot
$cheminConfig = if ($Fichier) { $Fichier } else { Join-Path $racine "backend\iris\config.py" }

function Titre($t)     { Write-Host ""; Write-Host $t -ForegroundColor Cyan }
function Ok($t)        { Write-Host "  [ok] $t" -ForegroundColor Green }
function Attention($t) { Write-Host "  [!]  $t" -ForegroundColor Yellow }
function Bloquant($t)  { Write-Host "  [X]  $t" -ForegroundColor Red }

# ---------------------------------------------------------------- 0. l'adresse
$Adresse = $Adresse.Trim().TrimEnd('/')
if ($Adresse -notmatch '^(?i)https?://[^\s"]+$') {
    Bloquant "Adresse invalide : « $Adresse »."
    Write-Host "  Attendu : une URL complete, p.ex. https://relais.mondomaine.com"
    exit 1
}
if ($Adresse -notmatch '^(?i)https://') {
    Attention "Adresse en http:// (non chiffre). En production, une adresse https:// est attendue."
}
if ($Adresse -match '(?i)trycloudflare\.com') {
    Attention "Cette adresse est un tunnel Cloudflare EPHEMERE : elle change a chaque redemarrage."
    Write-Host "  La figer dans le code livre fera perdre le cerveau a tous les clients au prochain redemarrage."
    Write-Host "  A n'utiliser que pour un test jetable, jamais pour une version distribuee."
}

Titre "1. Valeur par defaut dans le code (backend\iris\config.py)"
Write-Host "  Fichier : $cheminConfig" -ForegroundColor DarkGray
if (-not (Test-Path $cheminConfig)) {
    Bloquant "Introuvable : $cheminConfig"
    exit 1
}

# Lecture/ecriture en UTF-8 SANS BOM : config.py contient des accents, et un BOM injecte casserait
# l'import Python. WriteAllText avec UTF8Encoding($false) garantit l'absence de marque d'octets.
$utf8 = New-Object System.Text.UTF8Encoding($false)
$contenu = [System.IO.File]::ReadAllText($cheminConfig, $utf8)

# On ne remplace QUE la chaine entre guillemets de la ligne `relay_server: str = "..."`.
# - (?m) : ^ et $ collent aux debuts/fins de ligne, pas du fichier.
# - le groupe <url> ne peut contenir ni guillemet ni fin de ligne : on ne deborde jamais.
# - <pre> garde l'indentation et le guillemet ouvrant, <post> garde le guillemet fermant et la
#   suite eventuelle (commentaire, virgule) : le reste de la ligne est preserve tel quel.
$motif = '(?m)^(?<pre>[ \t]*relay_server\s*:\s*str\s*=\s*")(?<url>[^"\r\n]*)(?<post>".*)$'
$rx = [regex]$motif
$occurrences = $rx.Matches($contenu)
if ($occurrences.Count -eq 0) {
    Bloquant "Ligne `relay_server: str = \"...\"` introuvable : le format de config.py a change."
    Write-Host "  Rien n'a ete modifie. Verifiez le fichier a la main avant de reessayer."
    exit 1
}
if ($occurrences.Count -gt 1) {
    Bloquant "Plusieurs lignes `relay_server` trouvees ($($occurrences.Count)) : cas ambigu, rien modifie."
    exit 1
}

$ancienne = $occurrences[0].Groups['url'].Value
$nouveau  = $rx.Replace($contenu, { param($m) $m.Groups['pre'].Value + $Adresse + $m.Groups['post'].Value })

if ($ancienne -eq $Adresse) {
    Ok "Deja a jour : la valeur par defaut est deja « $Adresse »."
} elseif ($DryRun) {
    Attention "DryRun : AUCUNE ecriture."
    Write-Host "     avant : relay_server = `"$ancienne`"" -ForegroundColor DarkGray
    Write-Host "     apres : relay_server = `"$Adresse`"" -ForegroundColor White
} else {
    [System.IO.File]::WriteAllText($cheminConfig, $nouveau, $utf8)
    Ok "Valeur par defaut mise a jour : « $ancienne » -> « $Adresse »."
}

# ---------------------------------------------------------------- 2. reglages LIVE de cette machine
if ($SansLive) {
    Titre "2. Reglages LIVE"
    Attention "Ignores (-SansLive) : seule la valeur par defaut du code a ete traitee."
} elseif ($DryRun) {
    Titre "2. Reglages LIVE (dossier de donnees de cette machine)"
    Attention "DryRun : la commande suivante SERAIT lancee (aucune ecriture) :"
    Write-Host "     Settings(default_data_dir()).update({ 'relay_server': '$Adresse' })" -ForegroundColor DarkGray
} else {
    Titre "2. Reglages LIVE (dossier de donnees de cette machine)"
    $py = Join-Path $racine "backend\.venv\Scripts\python.exe"
    if (-not (Test-Path $py)) {
        Attention "venv backend introuvable ($py) : reglages LIVE non modifies."
        Write-Host "  Sans importance sur une machine qui n'execute pas le client IRIS : la valeur par"
        Write-Host "  defaut reecrite ci-dessus suffit pour toutes les copies installees a partir de"
        Write-Host "  maintenant. Sur une machine de dev, cree le venv puis relance."
    } else {
        # Applique la valeur au settings.json vivant, via l'API reelle des reglages (aucune cle en jeu).
        # Guillemets SIMPLES a l'interieur : PowerShell 5.1 mange les guillemets doubles quand il passe
        # un argument a un .exe natif, et « "relay_server" » arriverait a python en « relay_server »
        # (NameError). Les apostrophes, elles, sont transmises telles quelles.
        $code = @'
import sys
from iris.config import Settings, default_data_dir
s = Settings(default_data_dir())
s.update({'relay_server': sys.argv[1]})
print(s.settings_path)
print(s.user.relay_server)
'@
        Push-Location (Join-Path $racine "backend")
        # ErrorActionPreference=Stop ferait d'une SEULE ligne de stderr de python une erreur
        # terminante (NativeCommandError) qui couperait le script avant qu'on lise le code de retour.
        # On repasse donc en Continue le temps de l'appel pour capturer sortie ET erreurs, puis on
        # decide sur le code de retour. La valeur par defaut du code, elle, est deja ecrite.
        $eapAvant = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $sortie = & $py -c $code $Adresse 2>&1
            $codeRetour = $LASTEXITCODE
        } catch {
            $sortie = $_.Exception.Message
            $codeRetour = 1
        } finally {
            $ErrorActionPreference = $eapAvant
            Pop-Location
        }
        if ($codeRetour -eq 0) {
            Ok "Reglages LIVE mis a jour."
            foreach ($ligne in $sortie) { Write-Host "     $ligne" -ForegroundColor DarkGray }
        } else {
            Attention "Reglages LIVE non modifies (python a renvoye le code $codeRetour) :"
            foreach ($ligne in $sortie) { Write-Host "     $ligne" -ForegroundColor DarkGray }
            Write-Host "  La valeur par defaut du code, elle, a bien ete mise a jour ci-dessus." -ForegroundColor DarkGray
        }
    }
}

# ---------------------------------------------------------------- 3. ce qui reste a faire
$adresseV1 = "$Adresse/v1"
Write-Host ""
Write-Host "====================================================================" -ForegroundColor Green
Write-Host "  IL RESTE, HORS DE CE SCRIPT :" -ForegroundColor Green
Write-Host ""
Write-Host "  1. Verifier que le relais repond bien a travers ce domaine :" -ForegroundColor Cyan
Write-Host "        .\scripts\deployer-serveur.ps1 -Etat"
Write-Host "     (le relais doit tourner sur l'ordi B, avec le tunnel NOMME du meme domaine)."
Write-Host ""
Write-Host "  2. RE-BATIR l'installateur pour que les copies livrees portent la bonne adresse :" -ForegroundColor Cyan
Write-Host "        npm run dist:full"
Write-Host "     puis remplacer site\telechargement\IRIS-Setup.exe par le nouvel .exe."
Write-Host "     (Sans cette etape, l'installateur en ligne garde l'ANCIENNE adresse par defaut.)"
Write-Host ""
Write-Host "  3. Repointer l'agent vocal ElevenLabs (fait a part, avec la cle de gestion" -ForegroundColor Cyan
Write-Host "     ElevenLabs -- ce script n'y touche pas) :"
Write-Host "        Custom LLM > Server URL = $adresseV1"
Write-Host "     Voir docs\AGENT-VOCAL-ELEVENLABS.md (verifier le suffixe .../v1/chat/completions,"
Write-Host "     et le secret OPENAI_API_KEY = jeton d'appareil via POST $Adresse/api/appareil)."
Write-Host ""
Write-Host "  Marche complete : docs\DOMAINE-CERVEAU.md" -ForegroundColor DarkGray
Write-Host "====================================================================" -ForegroundColor Green
