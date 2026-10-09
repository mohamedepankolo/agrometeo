# sanitize_incoming.ps1 — copie les fichiers wrfout depuis un support (cle USB, disque...) vers
# wrf_incoming_dir. Les ':' du nommage WRF standard sont refuses par Windows a l'OUVERTURE d'un
# fichier, pas seulement a la creation : aucun outil normal (Python, PowerShell, cmd, robocopy)
# ne peut meme les COPIER. Seul 7-Zip, en lisant le volume en brut (comme une archive), y arrive.
# 7-Zip remplace lui-meme automatiquement ':' par '_' en ecrivant la copie (Windows l'exige aussi
# en ecriture) : pas besoin de renommer nous-memes derriere.
#
# Usage :
#   .\sanitize_incoming.ps1 -Volume D: -Destination ..\wrf_incoming

param(
    [Parameter(Mandatory = $true)][string]$Volume,      # ex: D:
    [Parameter(Mandatory = $true)][string]$Destination  # ex: ..\wrf_incoming
)

$sevenZip = "C:\Program Files\7-Zip\7z.exe"
if (-not (Test-Path $sevenZip)) {
    Write-Error "7-Zip introuvable a $sevenZip. Installer 7-Zip (https://www.7-zip.org/) et reessayer."
    exit 1
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$destFull = (Resolve-Path $Destination).Path

Write-Host "Liste des fichiers sur $Volume (format technique -slt, le seul fiable a analyser)..."
$listing = & $sevenZip l -slt "\\.\$Volume" 2>&1

# Format -slt : un bloc par entree, une ligne "Path = ..." puis "Size = ..." puis
# "Attributes = ..." (parmi d'autres champs), separes par une ligne vide. On ignore les
# dossiers (Attributes contient 'D') et les dossiers systeme Windows.
$files = @()
$path = $null
foreach ($line in $listing) {
    if ($line -match '^Path = (.+)$') {
        $path = $Matches[1]
    } elseif ($line -match '^Attributes = (.*)$') {
        $attrs = $Matches[1]
        if ($path -and $attrs -notmatch 'D' -and $path -notmatch '^\[SYSTEM\]' -and $path -ne 'System Volume Information' -and $path -notlike 'System Volume Information\*') {
            $files += $path
        }
        $path = $null
    }
}

if (-not $files) {
    Write-Warning "Aucun fichier trouve (ou format de sortie 7-Zip different de celui attendu : verifier manuellement avec '7z l -slt \\.\$Volume')."
    exit 0
}

Write-Host "$($files.Count) fichier(s) a copier :"
$files | ForEach-Object { Write-Host "  $_" }

foreach ($name in $files) {
    Write-Host "`nExtraction : $name"
    & $sevenZip x "\\.\$Volume" "-o$destFull" "$name" -y
}

Write-Host "`nTermine. Fichiers dans $destFull :"
Get-ChildItem $destFull | Select-Object Name, Length
