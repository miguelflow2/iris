# Installe l'outil en ligne de commande OpenCode sur cet ordinateur, et verifie qu'IRIS le trouve.
#
# POURQUOI CE SCRIPT EXISTE
# --------------------------
# IRIS sait deleguer la programmation a OpenCode (backend/iris/opencode.py). Elle refuse de le faire
# tant qu'aucun binaire `opencode` n'existe sur le disque, et elle n'installe RIEN a la place de
# Miguel : poser un programme qui a le droit de modifier des fichiers, c'est une decision qui se
# prend sciemment. Ce script est la façon de la prendre, une fois, en la voyant.
#
# CE QUI EST DEJA LA, ET QUI NE SUFFIT PAS (constate le 5 septembre 2026)
# -----------------------------------------------------------------------
#   - L'application de bureau OpenCode 1.18.25 (Electron, 231 Mo), installee le 28 aout dans
#     %LOCALAPPDATA%\Programs\@opencode-aidesktop. Elle n'apporte AUCUN binaire en ligne de commande.
#   - Le kit de greffons @opencode-ai/plugin + @opencode-ai/sdk 1.18.23 dans ~/.config/opencode.
#     Ce sont des bibliotheques, pas un programme.
#   - 313 Mo de sessions passees dans ~/.local/share/opencode (opencode.db).
# Rien de tout cela ne repond a `opencode` dans un terminal, et c'est exactement ce dont IRIS a
# besoin. D'ou l'installation separee.
#
# POURQUOI npm, ET PAS AUTRE CHOSE
# ---------------------------------
# Ce n'est pas une preference, c'est ce que la machine permet :
#   - npm 11.17.0 et Node 24.19.0 sont installes (C:\Program Files\nodejs).
#   - bun, scoop et chocolatey sont ABSENTS. Les voies qui passent par eux sont hors sujet ici.
#   - le prefixe global de npm est %APPDATA%\npm, deja present dans le PATH utilisateur : aucune
#     modification d'environnement n'est necessaire.
#   - et surtout : %APPDATA%\npm est l'un des emplacements ou IRIS cherche le binaire
#     (`_candidats_binaire` dans backend/iris/opencode.py). Une installation npm globale tombe donc
#     pile ou IRIS regarde, meme si le PATH etait casse.
#   - une installation npm globale se defait par `npm uninstall -g`. C'est reversible, sans
#     desinstalleur, sans registre, sans droits administrateur.
#
# LE NOM DU PAQUET N'EST PAS UNE CERTITUDE, ET LE SCRIPT NE FAIT PAS SEMBLANT
# ---------------------------------------------------------------------------
# Les seuls paquets prouves sur ce disque sont @opencode-ai/plugin et @opencode-ai/sdk, qui ne sont
# pas le programme. Le nom du paquet qui fournit la commande `opencode` n'a pas ete verifie contre
# le registre npm. Le script part donc d'une HYPOTHESE (-Paquet, defaut « opencode-ai »), la
# CONFIRME aupres du registre avant d'installer quoi que ce soit, et s'arrete net si le paquet
# n'existe pas ou ne declare pas de commande `opencode`. Il n'affirme rien qu'il n'ait verifie.
#
# CE SCRIPT NE DEMANDE PAS LES DROITS ADMINISTRATEUR. S'il vous les demande, ce n'est pas lui.
#
#   Voir l'etat sans rien toucher :  .\installer-opencode.ps1 -Simulation
#   Installer :                      .\installer-opencode.ps1
#   Avec un autre nom de paquet :    .\installer-opencode.ps1 -Paquet <nom>
#   Retirer ce que le script a pose : .\installer-opencode.ps1 -Desinstaller
#   Retirer AUSSI les 313 Mo de sessions : .\installer-opencode.ps1 -Desinstaller -EffacerDonnees
#
# Le document qui explique tout ceci a quelqu'un qui n'est pas administrateur systeme :
# docs/OPENCODE.md, a cote de ce script.

param(
    [switch]$Desinstaller,
    [switch]$Simulation,
    [switch]$EffacerDonnees,
    [switch]$ForcerInstallation,
    [string]$Paquet = "opencode-ai"
)

# ============================================================================ reperes sur le disque
$RACINE_IRIS      = Split-Path -Parent $PSScriptRoot
$DOSSIER_CONFIG   = Join-Path $HOME ".config\opencode"
$DOSSIER_DONNEES  = Join-Path $HOME ".local\share\opencode"
$DOSSIER_CACHE    = Join-Path $HOME ".cache\opencode"
$APP_BUREAU       = Join-Path $env:LOCALAPPDATA "Programs\@opencode-aidesktop"
$REGLAGES_IRIS    = Join-Path $env:APPDATA "IRIS\iris-data\settings.json"
$PREFIXE_NPM      = Join-Path $env:APPDATA "npm"

$global:BILAN_OK      = New-Object System.Collections.ArrayList
$global:BILAN_MANQUE  = New-Object System.Collections.ArrayList

# ============================================================================ affichage
function Titre($texte) {
    Write-Host ""
    Write-Host $texte -ForegroundColor Cyan
    Write-Host ("-" * $texte.Length) -ForegroundColor DarkGray
}
function Etape($numero, $texte) { Write-Host "$numero. $texte" }
function Bien($texte)      { Write-Host "   $texte" -ForegroundColor Green;  [void]$global:BILAN_OK.Add($texte) }
function Manque($texte)    { Write-Host "   $texte" -ForegroundColor Yellow; [void]$global:BILAN_MANQUE.Add($texte) }
function Souci($texte)     { Write-Host "   $texte" -ForegroundColor Red;    [void]$global:BILAN_MANQUE.Add($texte) }
function Detail($texte)    { Write-Host "   $texte" -ForegroundColor DarkGray }

function Taille-Lisible($octets) {
    if ($null -eq $octets) { return "0 o" }
    if ($octets -ge 1GB) { return ("{0:N1} Go" -f ($octets / 1GB)) }
    if ($octets -ge 1MB) { return ("{0:N0} Mo" -f ($octets / 1MB)) }
    if ($octets -ge 1KB) { return ("{0:N0} Ko" -f ($octets / 1KB)) }
    return "$octets o"
}

function Poids-Dossier($chemin) {
    # Sert a annoncer ce qu'une suppression detruirait AVANT de la proposer. Un « 313 Mo » affiche
    # a l'ecran arrete la main ; un « le dossier de donnees » ne l'arrete pas.
    if (-not (Test-Path -LiteralPath $chemin)) { return $null }
    try {
        $m = Get-ChildItem -LiteralPath $chemin -Recurse -Force -File -ErrorAction SilentlyContinue |
             Measure-Object -Property Length -Sum
        return [pscustomobject]@{ Fichiers = $m.Count; Octets = [long]$m.Sum }
    } catch { return $null }
}

# ============================================================================ npm
function Trouver-Npm {
    # On vise npm.cmd et pas npm tout court : `Get-Command npm` rend npm.ps1 sur cette machine, et
    # un wrapper PowerShell brouille le code de retour des qu'on le lance depuis un autre script.
    # C'est le code de retour qui decide ici si une installation a reussi ou non.
    $cmd = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $classique = "C:\Program Files\nodejs\npm.cmd"
    if (Test-Path -LiteralPath $classique) { return $classique }
    $cmd = Get-Command "npm" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return ""
}

function Npm-Silencieux($npm, $arguments) {
    # Rend @{ Code; Sortie }. La sortie est capturee pour etre analysee, pas pour etre jetee : quand
    # npm echoue, sa premiere ligne dit pourquoi, et c'est cette ligne qu'il faut montrer.
    $sortie = & $npm @arguments
    return [pscustomobject]@{ Code = $LASTEXITCODE; Sortie = ($sortie -join "`n") }
}

# ============================================================================ ou est OpenCode
function Chemins-Candidats {
    # LA MEME LISTE que `_candidats_binaire()` dans backend/iris/opencode.py, dans le meme ordre.
    # Si les deux divergent un jour, le script dira « installe » la ou IRIS dira « absent », et
    # personne ne comprendra pourquoi. Toute modification ici doit etre repercutee la-bas.
    $noms = @("opencode.cmd", "opencode.exe", "opencode")
    $dossiers = @(
        (Join-Path $HOME ".opencode\bin"),
        (Join-Path $HOME ".bun\bin"),
        (Join-Path $HOME ".local\bin"),
        $PREFIXE_NPM,
        (Join-Path $env:LOCALAPPDATA "Programs\opencode")
    )
    $liste = New-Object System.Collections.ArrayList
    foreach ($d in $dossiers) {
        if ([string]::IsNullOrWhiteSpace($d)) { continue }
        foreach ($n in $noms) { [void]$liste.Add((Join-Path $d $n)) }
    }
    return $liste
}

function Trouver-OpenCode {
    $cmd = Get-Command "opencode" -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    foreach ($candidat in (Chemins-Candidats)) {
        if (Test-Path -LiteralPath $candidat -PathType Leaf) { return $candidat }
    }
    return ""
}

function Executer-Avec-Delai($chemin, $arguments, $secondes) {
    # Pourquoi un delai, et pourquoi passer par cmd.exe :
    #   - le binaire pose par npm est un .cmd, que Start-Process ne sait pas lancer directement ;
    #   - `opencode --help` est CENSE afficher puis rendre la main, mais on n'a jamais vu ce binaire
    #     tourner sur cette machine. S'il ouvrait une interface plein ecran, un script sans delai
    #     resterait bloque pour toujours. On l'arrete, et on le dit.
    $tmpOut = [System.IO.Path]::GetTempFileName()
    $tmpErr = [System.IO.Path]::GetTempFileName()
    $ligne = '"' + $chemin + '" ' + $arguments
    try {
        $p = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $ligne) -NoNewWindow -PassThru `
             -RedirectStandardOutput $tmpOut -RedirectStandardError $tmpErr -ErrorAction Stop
    } catch {
        Remove-Item $tmpOut, $tmpErr -Force -ErrorAction SilentlyContinue
        return [pscustomobject]@{ Code = -1; Sortie = $_.Exception.Message; Expire = $false }
    }
    $fini = $true
    try { Wait-Process -Id $p.Id -Timeout $secondes -ErrorAction Stop } catch { $fini = $false }
    if (-not $fini) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 200
    $texte = ""
    foreach ($f in @($tmpOut, $tmpErr)) {
        $c = Get-Content -LiteralPath $f -Raw -ErrorAction SilentlyContinue
        if ($c) { $texte += $c }
    }
    Remove-Item $tmpOut, $tmpErr -Force -ErrorAction SilentlyContinue
    $code = -1
    if ($fini) { try { $code = $p.ExitCode } catch { $code = -1 } }
    return [pscustomobject]@{ Code = $code; Sortie = $texte.Trim(); Expire = (-not $fini) }
}

# ============================================================================ etat des lieux
function Etat-Des-Lieux {
    Titre "Etat de la machine"

    $noeud = Get-Command "node" -ErrorAction SilentlyContinue
    if ($noeud) {
        $v = (& node --version)
        Detail "Node    : $v ($($noeud.Source))"
    } else {
        Souci "Node n'est pas installe. OpenCode ne peut pas etre pose par cette voie."
    }

    $npm = Trouver-Npm
    if ($npm) {
        $vnpm = (& $npm --version)
        Detail "npm     : $vnpm ($npm)"
        Detail "prefixe : $PREFIXE_NPM"
    } else {
        Souci "npm est introuvable. Sans lui, ce script ne peut rien installer."
    }

    $cheminPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    $dansPath = $false
    # Le @() n'est pas decoratif : quand un seul element sort de Where-Object, PowerShell rend
    # l'objet nu et non un tableau, et le .Count d'un objet nu n'est pas le nombre de resultats.
    if ($cheminPath) { $dansPath = @($cheminPath -split ";" | Where-Object { $_.TrimEnd("\") -ieq $PREFIXE_NPM.TrimEnd("\") }).Count -gt 0 }
    if ($dansPath) { Detail "Le prefixe npm est dans le PATH utilisateur." }
    else { Detail "Le prefixe npm n'est PAS dans le PATH utilisateur (IRIS le trouvera quand meme)." }

    $binaire = Trouver-OpenCode
    if ($binaire) { Detail "opencode: $binaire" }
    else { Detail "opencode: absent (ni dans le PATH, ni dans les emplacements connus)" }

    if (Test-Path -LiteralPath $APP_BUREAU) {
        $exe = Join-Path $APP_BUREAU "OpenCode.exe"
        $ver = "?"
        if (Test-Path -LiteralPath $exe) { $ver = (Get-Item -LiteralPath $exe).VersionInfo.FileVersion }
        Detail "Application de bureau OpenCode $ver : presente. Elle n'apporte pas la ligne de commande."
    }

    foreach ($paire in @(
        @{ Nom = "Reglages OpenCode (les votres)"; Chemin = $DOSSIER_CONFIG },
        @{ Nom = "Sessions et base OpenCode";      Chemin = $DOSSIER_DONNEES },
        @{ Nom = "Cache OpenCode";                 Chemin = $DOSSIER_CACHE }
    )) {
        $poids = Poids-Dossier $paire.Chemin
        if ($poids) { Detail ("{0} : {1} ({2} fichiers, {3})" -f $paire.Nom, $paire.Chemin, $poids.Fichiers, (Taille-Lisible $poids.Octets)) }
    }
    return $binaire
}

# ============================================================================ verification du paquet
function Verifier-Le-Paquet($npm, $nom) {
    # Interrogation du registre, PAS une installation : `npm view` lit des metadonnees, il n'ecrit
    # rien sur le disque et ne pose aucun programme. C'est la seule façon honnete de repondre a
    # « ce paquet existe-t-il, et fournit-il bien la commande opencode ? » sans l'installer d'abord.
    Etape 2 "Verification du paquet « $nom » aupres du registre npm (aucune installation)."
    $r = Npm-Silencieux $npm @("view", $nom, "version", "bin", "--json")
    if ($r.Code -ne 0 -or [string]::IsNullOrWhiteSpace($r.Sortie)) {
        Souci "Le paquet « $nom » est introuvable sur le registre npm."
        Detail "Reponse de npm : $(($r.Sortie -split "`n" | Select-Object -First 2) -join ' / ')"
        Detail "Le nom du paquet qui fournit « opencode » n'a jamais ete verifie pour ce projet."
        Detail "Relisez la page d'installation officielle d'OpenCode, puis relancez avec le bon nom :"
        Detail "   .\installer-opencode.ps1 -Paquet <nom-exact>"
        return $null
    }
    $info = $null
    try { $info = $r.Sortie | ConvertFrom-Json } catch { $info = $null }
    if ($null -eq $info) {
        Manque "npm a repondu quelque chose que je ne sais pas lire. Sortie brute :"
        Detail $r.Sortie
        if (-not $ForcerInstallation) {
            Detail "Je m'arrete la. Pour installer malgre tout : -ForcerInstallation"
            return $null
        }
        return [pscustomobject]@{ Version = "?"; Commandes = @() }
    }

    $version = "$($info.version)"
    $commandes = @()
    if ($info.bin) {
        if ($info.bin -is [string]) { $commandes = @($nom) }
        else { $commandes = @($info.bin.PSObject.Properties.Name) }
    }
    Bien "Paquet trouve : $nom $version"
    if ($commandes.Count -gt 0) { Detail ("Commandes declarees : " + ($commandes -join ", ")) }
    else { Detail "Ce paquet ne declare aucune commande." }

    if ($commandes -notcontains "opencode") {
        Souci "Ce paquet ne fournit PAS de commande nommee « opencode »."
        Detail "C'est peut-etre une bibliotheque (comme @opencode-ai/sdk, deja presente ici) et pas le programme."
        if (-not $ForcerInstallation) {
            Detail "Je n'installe pas. Pour passer outre : -ForcerInstallation"
            return $null
        }
        Manque "Installation forcee malgre l'absence de commande « opencode »."
    }
    return [pscustomobject]@{ Version = $version; Commandes = $commandes }
}

# ============================================================================ installation
function Installer {
    Titre "Installation d'OpenCode"

    $npm = Trouver-Npm
    if (-not $npm) {
        Souci "npm est introuvable : je ne peux rien installer. Installez Node.js, puis relancez."
        return
    }

    Etape 1 "Recherche d'un binaire deja pose."
    $existant = Trouver-OpenCode
    if ($existant) {
        Bien "OpenCode est deja la : $existant"
        Detail "Rien a installer. Je passe directement a la verification."
        Verifier-Installation $existant
        return
    }
    Detail "Aucun binaire « opencode » sur ce disque. Installation necessaire."

    $paquetInfo = Verifier-Le-Paquet $npm $Paquet
    if ($null -eq $paquetInfo) { return }

    Write-Host ""
    Etape 3 "Ce que je vais faire, exactement."
    Detail "Commande      : npm install -g $Paquet"
    Detail "Ecrit dans    : $PREFIXE_NPM  (et $PREFIXE_NPM\node_modules)"
    Detail "N'ecrit pas dans : $DOSSIER_CONFIG (vos reglages), $DOSSIER_DONNEES (vos sessions)"
    Detail "Droits admin  : non requis. Registre Windows : pas touche. PATH : pas modifie."
    Detail "Reversible    : oui, par .\installer-opencode.ps1 -Desinstaller"

    if ($Simulation) {
        Write-Host ""
        Manque "Mode simulation : je m'arrete ici, rien n'a ete installe."
        Detail "Relancez sans -Simulation pour installer pour de vrai."
        return
    }

    Write-Host ""
    Etape 4 "Installation en cours (npm telecharge, cela peut prendre une minute)."
    & $npm install -g $Paquet
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        Souci "npm s'est arrete sur une erreur (code $code). Rien n'est garanti installe."
        Detail "Les lignes ci-dessus, ecrites par npm, disent pourquoi."
        return
    }
    Bien "npm a termine sans erreur."

    $binaire = Trouver-OpenCode
    if (-not $binaire) {
        Souci "npm dit avoir reussi, mais aucun binaire « opencode » n'apparait sur le disque."
        Detail "Cherche dans le PATH, puis dans :"
        foreach ($c in (Chemins-Candidats)) { Detail "   $c" }
        Detail "Le paquet « $Paquet » n'etait probablement pas le bon. Retirez-le avec -Desinstaller."
        return
    }
    Bien "Binaire pose : $binaire"
    Verifier-Installation $binaire
}

# ============================================================================ verification
function Verifier-Installation($binaire) {
    Write-Host ""
    Etape 5 "Verification : est-ce que ce programme repond ?"
    $v = Executer-Avec-Delai $binaire "--version" 30
    if ($v.Expire) {
        Souci "« opencode --version » ne rend pas la main au bout de 30 secondes. Je l'ai arrete."
        Detail "Un programme qui ne repond pas a --version n'est pas pilotable par IRIS."
    } elseif ($v.Code -ne 0) {
        Souci "« opencode --version » s'est arrete sur une erreur (code $($v.Code))."
        if ($v.Sortie) { Detail (($v.Sortie -split "`n" | Select-Object -First 3) -join " / ") }
    } else {
        $ligne = ($v.Sortie -split "`n" | Where-Object { $_.Trim() } | Select-Object -First 1)
        Bien "OpenCode repond : $ligne"
    }

    # ------------------------------------------------------------------ la surface d'appel
    # IRIS lance aujourd'hui `opencode run "<consigne>"`, le dossier etant epingle par le repertoire
    # courant du processus (voir `_argv` dans backend/iris/opencode.py). Ce choix a ete fait SANS
    # jamais avoir vu le binaire : l'enquete sur la ligne de commande reelle n'a pas abouti. Le
    # premier ordinateur ou OpenCode existe est donc le premier endroit ou on peut enfin verifier.
    # On capture l'aide dans un fichier plutot que de la faire defiler : elle se relit, elle se
    # compare a `_argv`, et elle ne se perd pas dans l'historique du terminal.
    Write-Host ""
    Etape 6 "Capture de la ligne de commande reelle (pour comparer a ce qu'IRIS appelle)."
    $sortieAide = Join-Path $env:TEMP ("opencode-surface-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".txt")
    $blocs = New-Object System.Collections.ArrayList
    [void]$blocs.Add("Capture faite le " + (Get-Date -Format "yyyy-MM-dd HH:mm") + " depuis " + $binaire)
    foreach ($jeu in @("--version", "--help", "run --help", "serve --help")) {
        $r = Executer-Avec-Delai $binaire $jeu 30
        $etat = "code $($r.Code)"
        if ($r.Expire) { $etat = "ARRETE apres 30 s" }
        [void]$blocs.Add("")
        [void]$blocs.Add("========== opencode $jeu   ($etat)")
        [void]$blocs.Add($r.Sortie)
        Detail ("opencode $jeu -> $etat")
    }
    try {
        ($blocs -join "`r`n") | Out-File -FilePath $sortieAide -Encoding utf8
        Bien "Aide capturee : $sortieAide"
        Detail "A comparer avec la methode « _argv » de backend/iris/opencode.py, qui appelle"
        Detail "   opencode run `"<consigne>`"   dans le dossier de travail."
        Detail "Si l'aide ne connait pas la sous-commande « run », IRIS ne lancera rien qui marche."
    } catch {
        Manque "Aide non ecrite ($($_.Exception.Message)). Ce n'est pas bloquant."
    }

    # ------------------------------------------------------------------ le point de vue d'IRIS
    Write-Host ""
    Etape 7 "Est-ce qu'IRIS, elle, va le trouver ?"
    $vuParIris = $false
    foreach ($c in (Chemins-Candidats)) {
        if (Test-Path -LiteralPath $c -PathType Leaf) { $vuParIris = $true; Detail "IRIS regardera ici : $c" }
    }
    $dansPath = (Get-Command "opencode" -ErrorAction SilentlyContinue) -ne $null
    if ($dansPath) { Detail "Et « opencode » repond aussi depuis le PATH." }
    if ($vuParIris -or $dansPath) {
        Bien "IRIS trouvera OpenCode au prochain demarrage (elle recherche le binaire a chaque appel)."
    } else {
        Manque "IRIS ne le trouvera PAS : le binaire n'est ni dans le PATH ni dans ses emplacements connus."
    }

    # Le binaire ne suffit pas : sans dossier autorise, `Contremaitre.pourquoi_pas_pret()` repond
    # « tu ne m'as autorise aucun dossier de travail » et l'outil n'est meme pas offert au modele.
    # Autant le dire ici plutot que de laisser Miguel croire a une panne.
    Write-Host ""
    Etape 8 "Le dernier verrou : les dossiers qu'IRIS a le droit de confier."
    if (Test-Path -LiteralPath $REGLAGES_IRIS) {
        $brut = Get-Content -LiteralPath $REGLAGES_IRIS -Raw -ErrorAction SilentlyContinue
        if ($brut -and $brut -match "opencode") {
            Detail "Une section « opencode » existe dans $REGLAGES_IRIS."
        } else {
            Manque "Aucun dossier de travail autorise dans les reglages d'IRIS."
            Detail "Tant que vous ne lui en nommez aucun, IRIS n'enverra OpenCode nulle part, meme installe."
            Detail "Fichier concerne : $REGLAGES_IRIS"
        }
    } else {
        Detail "Reglages d'IRIS pas encore crees ($REGLAGES_IRIS). Lancez IRIS une fois."
        Manque "Aucun dossier de travail autorise pour l'instant."
    }
}

# ============================================================================ desinstallation
function Desinstallation {
    Titre "Retrait d'OpenCode"

    Write-Host "Ce que ce script retire :" -ForegroundColor White
    Detail "le paquet npm global « $Paquet » et la commande « opencode » qu'il a posee."
    Write-Host "Ce que ce script NE TOUCHE PAS :" -ForegroundColor White
    Detail "l'application de bureau OpenCode (elle a son propre desinstalleur, voir plus bas) ;"
    Detail "vos reglages : $DOSSIER_CONFIG ;"
    $poidsDonnees = Poids-Dossier $DOSSIER_DONNEES
    if ($poidsDonnees) {
        Detail ("vos sessions passees : $DOSSIER_DONNEES (" + (Taille-Lisible $poidsDonnees.Octets) + ").")
    } else {
        Detail "vos sessions passees : $DOSSIER_DONNEES (absent)."
    }
    Write-Host ""

    $npm = Trouver-Npm
    if (-not $npm) {
        Souci "npm est introuvable : je ne peux pas retirer le paquet."
    } else {
        Etape 1 "Retrait du paquet npm global."
        if ($Simulation) {
            Manque "Mode simulation : je m'arrete. La commande aurait ete : npm uninstall -g $Paquet"
        } else {
            & $npm uninstall -g $Paquet
            $code = $LASTEXITCODE
            if ($code -eq 0) { Bien "npm a retire « $Paquet »." }
            else { Manque "npm s'est arrete sur le code $code. Le paquet n'etait peut-etre pas installe." }
        }
    }

    Write-Host ""
    Etape 2 "Verification : le binaire a-t-il vraiment disparu ?"
    $reste = Trouver-OpenCode
    if ($reste) {
        Manque "Un binaire « opencode » repond encore : $reste"
        Detail "Il vient d'ailleurs que du paquet « $Paquet » : autre paquet npm, autre installateur."
        Detail "Ce script ne supprime pas un fichier qu'il n'a pas pose. A vous de voir d'ou il vient."
    } else {
        Bien "Plus aucun binaire « opencode » sur ce disque. IRIS redeviendra muette sur la delegation."
    }

    # ------------------------------------------------------------------ les donnees, a part
    # Separe du reste, et jamais fait par defaut : ce dossier contient l'historique complet des
    # sessions OpenCode. Le retrait du programme est reversible en une commande ; l'effacement de
    # ces donnees ne l'est pas. Les deux ne doivent pas se declencher du meme geste.
    Write-Host ""
    Etape 3 "Les donnees des sessions passees."
    if (-not $poidsDonnees) {
        Detail "Rien a effacer : $DOSSIER_DONNEES n'existe pas."
    } elseif (-not $EffacerDonnees) {
        Detail ("Conservees : " + (Taille-Lisible $poidsDonnees.Octets) + " dans $DOSSIER_DONNEES")
        Detail "Pour les effacer aussi : .\installer-opencode.ps1 -Desinstaller -EffacerDonnees"
    } else {
        Write-Host ""
        Write-Host "   ATTENTION : ceci est IRREVERSIBLE." -ForegroundColor Red
        Write-Host ("   A supprimer : " + $DOSSIER_DONNEES) -ForegroundColor Red
        Write-Host ("                 " + $poidsDonnees.Fichiers + " fichiers, " + (Taille-Lisible $poidsDonnees.Octets)) -ForegroundColor Red
        Write-Host "   C'est l'historique de toutes vos conversations avec OpenCode. Aucune corbeille." -ForegroundColor Red
        if ($Simulation) {
            Manque "Mode simulation : rien n'a ete supprime."
        } else {
            $reponse = Read-Host "   Tapez EFFACER (en majuscules) pour confirmer, ou Entree pour renoncer"
            if ($reponse -ceq "EFFACER") {
                try {
                    Remove-Item -LiteralPath $DOSSIER_DONNEES -Recurse -Force -Confirm:$false -ErrorAction Stop
                    Bien "Donnees supprimees."
                } catch {
                    Souci "Suppression impossible : $($_.Exception.Message)"
                    Detail "L'application de bureau OpenCode est peut-etre ouverte. Fermez-la et reessayez."
                }
            } else {
                Detail "Renonce. Rien n'a ete supprime."
            }
        }
    }

    Write-Host ""
    Etape 4 "L'application de bureau, si vous voulez aussi vous en debarrasser."
    $desinstalleur = Join-Path $APP_BUREAU "Uninstall OpenCode.exe"
    if (Test-Path -LiteralPath $desinstalleur) {
        Detail "Elle est installee, et elle n'a rien a voir avec ce script."
        Detail "Son desinstalleur, a lancer vous-meme : $desinstalleur"
        Detail "Ou : Parametres Windows > Applications > OpenCode."
    } else {
        Detail "Pas d'application de bureau OpenCode installee."
    }
}

# ============================================================================ bilan
function Bilan {
    Titre "Bilan"
    if ($global:BILAN_OK.Count -gt 0) {
        Write-Host "En place :" -ForegroundColor Green
        foreach ($l in $global:BILAN_OK) { Write-Host "   - $l" -ForegroundColor Green }
    }
    if ($global:BILAN_MANQUE.Count -gt 0) {
        Write-Host "Il manque encore :" -ForegroundColor Yellow
        foreach ($l in $global:BILAN_MANQUE) { Write-Host "   - $l" -ForegroundColor Yellow }
    }
    if ($global:BILAN_OK.Count -eq 0 -and $global:BILAN_MANQUE.Count -eq 0) {
        Write-Host "   Rien a signaler." -ForegroundColor DarkGray
    }
    Write-Host ""
    Write-Host "Ce qu'OpenCode peut faire, ce qu'IRIS l'empeche de faire, et ce que ca coute :" -ForegroundColor Cyan
    Write-Host ("   " + (Join-Path $RACINE_IRIS "docs\OPENCODE.md"))
    Write-Host ""
}

# ============================================================================ deroule
Write-Host ""
Write-Host "IRIS - installation de l'agent de programmation OpenCode" -ForegroundColor White
if ($Simulation) { Write-Host "MODE SIMULATION : rien ne sera installe ni supprime." -ForegroundColor Yellow }

if ($Desinstaller) {
    [void](Etat-Des-Lieux)
    Desinstallation
} else {
    [void](Etat-Des-Lieux)
    Installer
}
Bilan
