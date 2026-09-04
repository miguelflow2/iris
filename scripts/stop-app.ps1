# Arrête uniquement les processus de l'application IRIS (fenêtre Electron + service embarqué),
# sans toucher aux shells, éditeurs ou autres apps Electron (leçon : un filtre sur la ligne de commande
# a déjà tué le terminal qui l'exécutait).
$targets = Get-Process -Name IRIS, iris-backend -ErrorAction SilentlyContinue
foreach ($p in $targets) {
  Write-Host "arrêt $($p.ProcessName) (pid $($p.Id))"
  Stop-Process -Id $p.Id -Force -Confirm:$false -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
$left = (Get-Process -Name IRIS, iris-backend -ErrorAction SilentlyContinue).Count
Write-Host "processus IRIS restants : $left"
