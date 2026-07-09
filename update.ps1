# TimeTrack — kontrola a instalace aktualizace z GitHub Releases.
#
# Spusteni (dvojklik na "Aktualizovat TimeTrack.cmd", nebo rucne):
#   powershell -ExecutionPolicy Bypass -File update.ps1
#
# Co skript udela:
#   1) zjisti nejnovejsi release na GitHubu (API /releases/latest),
#   2) porovna ho s nainstalovanou verzi (__version__),
#   3) kdyz je novejsi: stahne instalacni ZIP a overi jeho SHA-256 dle
#      checksums.txt z release (poskozeny/podvrzeny soubor se neinstaluje),
#   4) rozbali do %TEMP% a odtud spusti setup.ps1 -NoPrompt (tichy update —
#      instalator sam ukonci a po instalaci znovu spusti bezici aplikaci).
#
# Instalator bezi z %TEMP%, takze prepis souboru v instalacni slozce (vcetne
# tohoto skriptu) nekolimuje s bezicim updatem. Vyzaduje Python (jako ZIP
# instalace) — pro .exe distribuci stahni novou verzi rucne z Releases.
#
# Parametry:
#   -Repo <owner/name>  GitHub repo (vychozi TheKoubes/jira-timetrack)
#   -Force              nainstaluje i kdyz neni novejsi (reinstalace)
#   -CheckOnly          jen zjisti a vypise dostupnou verzi, nic nestahuje

[CmdletBinding()]
param(
    [string]$Repo = 'TheKoubes/jira-timetrack',
    [switch]$Force,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
# GitHub vyzaduje TLS 1.2+; na Windows PowerShell 5.1 nemusi byt vychozi.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$installDir = $PSScriptRoot

function Write-Step($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Write-Ok($text) { Write-Host "  OK  $text" -ForegroundColor Green }
function Write-Warn2($text) { Write-Host "  !!  $text" -ForegroundColor Yellow }

function Get-LocalVersion {
    $initPath = Join-Path $installDir 'timetrack\__init__.py'
    if (Test-Path $initPath) {
        $m = [regex]::Match((Get-Content $initPath -Raw), '__version__\s*=\s*"([^"]+)"')
        if ($m.Success) { return $m.Groups[1].Value }
    }
    return $null
}

$headers = @{ 'User-Agent' = 'TimeTrack-updater'; 'Accept' = 'application/vnd.github+json' }

Write-Host "TimeTrack - aktualizace" -ForegroundColor White

# --- 1) Nejnovejsi release -------------------------------------------------
Write-Step "Kontrola nejnovejsi verze"
try {
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -Headers $headers
} catch {
    $status = $null
    if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
    if ($status -eq 404) {
        Write-Warn2 "Repo $Repo zatim nema zadny release - neni co aktualizovat."
        return
    }
    throw "Nepodarilo se zjistit nejnovejsi verzi z GitHubu ($Repo): $($_.Exception.Message)"
}
$tag = "$($release.tag_name)"
$latest = $tag.TrimStart('v', 'V')
$local = Get-LocalVersion
Write-Host "  Nainstalovano: $(if ($local) { $local } else { '(nezname)' })"
Write-Host "  Na GitHubu:    $latest ($tag)"

$isNewer = $false
try {
    $isNewer = [bool]$local -and ([version]$latest -gt [version]$local)
} catch {
    # nenumericke verze: ber za novejsi jakoukoli odlisnou
    $isNewer = [bool]$local -and ($latest -ne $local)
}

if ($CheckOnly) {
    if ($isNewer) { Write-Ok "Je dostupna novejsi verze $latest." }
    else { Write-Ok "Mas nejnovejsi verzi." }
    return
}
if (-not $isNewer -and -not $Force) {
    Write-Ok "Mas nejnovejsi verzi ($local) - neni co aktualizovat."
    return
}

# --- 2) Stazeni ZIPu + checksums ------------------------------------------
Write-Step "Stazeni verze $latest"
$zipAsset = $release.assets |
    Where-Object { $_.name -like '*instalace*.zip' } | Select-Object -First 1
if (-not $zipAsset) {
    $zipAsset = $release.assets | Where-Object { $_.name -like '*.zip' } | Select-Object -First 1
}
if (-not $zipAsset) { throw "Release $tag nema instalacni ZIP." }
$sumAsset = $release.assets | Where-Object { $_.name -eq 'checksums.txt' } | Select-Object -First 1

$work = Join-Path $env:TEMP ("tt_update_" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $work | Out-Null
try {
    $zipPath = Join-Path $work $zipAsset.name
    Invoke-WebRequest -Uri $zipAsset.browser_download_url -OutFile $zipPath -Headers $headers
    Write-Ok "Stazeno: $($zipAsset.name)"

    # --- 3) Overeni SHA-256 -----------------------------------------------
    if ($sumAsset) {
        Write-Step "Overeni kontrolniho souctu"
        $sumPath = Join-Path $work 'checksums.txt'
        Invoke-WebRequest -Uri $sumAsset.browser_download_url -OutFile $sumPath -Headers $headers
        $expected = $null
        foreach ($line in Get-Content $sumPath) {
            $parts = $line -split '\s+', 2
            if ($parts.Count -eq 2 -and $parts[1].Trim() -eq $zipAsset.name) {
                $expected = $parts[0].Trim().ToLower()
            }
        }
        if (-not $expected) { throw "V checksums.txt chybi radek pro $($zipAsset.name)." }
        $actual = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $expected) {
            throw "SHA-256 nesouhlasi (ocekavano $expected, spocteno $actual) - aktualizace zrusena."
        }
        Write-Ok "SHA-256 sedi."
    } else {
        Write-Warn2 "Release nema checksums.txt - preskakuji overeni souctu."
    }

    # --- 4) Rozbaleni + spusteni setup.ps1 --------------------------------
    Write-Step "Rozbaleni a instalace"
    $extract = Join-Path $work 'extract'
    Expand-Archive -Path $zipPath -DestinationPath $extract -Force
    $setup = Get-ChildItem $extract -Recurse -Filter 'setup.ps1' | Select-Object -First 1
    if (-not $setup) { throw "V ZIPu neni setup.ps1." }
    Write-Ok "Rozbaleno."

    Write-Host "  Spoustim instalator (ukonci a po instalaci znovu spusti aplikaci)..."
    $setupArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $setup.FullName,
                   '-NoPrompt', '-InstallDir', $installDir, '-Launch')
    $proc = Start-Process -FilePath 'powershell' -ArgumentList $setupArgs -Wait -PassThru -NoNewWindow
    if ($proc.ExitCode -ne 0) { throw "Instalator skoncil s kodem $($proc.ExitCode)." }
    Write-Ok "Aktualizace na $latest hotova."
} finally {
    Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
}
