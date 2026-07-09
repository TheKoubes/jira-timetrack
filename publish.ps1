# TimeTrack — publikace release na GitHub (gh CLI).
#
# Spusteni z korene repa:
#   powershell -ExecutionPolicy Bypass -File publish.ps1              # ostry release
#   powershell -ExecutionPolicy Bypass -File publish.ps1 -DryRun     # jen postavit artefakty
#
# Co skript udela:
#   1) overi cisty pracovni strom a spusti testy (py -m pytest),
#   2) precte __version__ a odvodi tag vX.Y (predany -Tag musi souhlasit),
#   3) postavi dist\TimeTrack.exe (build_exe.ps1) a dist\TimeTrack-instalace.zip,
#   4) spocita SHA-256 do dist\checksums.txt,
#   5) vytvori a pushne git tag a zalozi GitHub release s artefakty.
#
# Parametry:
#   -Tag <vX.Y>     ocekavany tag (kontrola proti __version__; vychozi se odvodi)
#   -Notes <text>   poznamky k release (vychozi: automaticky generovane z commitu)
#   -Prerelease     oznaci release jako pre-release (staged rollout — /latest ho ignoruje)
#   -DryRun         postavi artefakty a skonci pred tagem/releasem (bez gh)

[CmdletBinding()]
param(
    [string]$Tag = '',
    [string]$Notes = '',
    [switch]$Prerelease,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

function Write-Step($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Write-Ok($text) { Write-Host "  OK  $text" -ForegroundColor Green }

# Soubory instalacniho ZIPu (slozka TimeTrack\ uvnitr archivu). Pri pridani
# noveho souboru do distribuce rozsirit i tenhle seznam.
$zipItems = @(
    'timetrack', 'assets', 'README.md', 'INSTALL.md', 'LICENSE',
    'setup.ps1', 'install_autostart.ps1', 'Nainstalovat TimeTrack.cmd',
    'update.ps1', 'Aktualizovat TimeTrack.cmd'
)

# --- 1) Cisty strom + testy ------------------------------------------------
Write-Step "Kontroly"
$dirty = git -C $root status --porcelain
if ($dirty) { throw "Pracovni strom neni cisty - release jde jen z commitnuteho stavu:`n$dirty" }
Write-Ok "Pracovni strom cisty."

Push-Location $root
try {
    py -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Testy neprosly (kod $LASTEXITCODE) - release se rusi." }
} finally { Pop-Location }
Write-Ok "Testy prosly."

# --- 2) Verze vs. tag --------------------------------------------------------
$initRaw = Get-Content (Join-Path $root 'timetrack\__init__.py') -Raw
$m = [regex]::Match($initRaw, '__version__\s*=\s*"([^"]+)"')
if (-not $m.Success) { throw "V timetrack\__init__.py chybi __version__." }
$version = $m.Groups[1].Value
$expectedTag = "v$version"
if ($Tag -and $Tag -ne $expectedTag) {
    throw "Tag '$Tag' nesouhlasi s __version__ '$version' (cekal jsem '$expectedTag')."
}
$Tag = $expectedTag
$existing = git -C $root tag -l $Tag
if ($existing) { throw "Tag $Tag uz existuje - nejdriv zvednout __version__." }
Write-Ok "Verze $version -> tag $Tag"

# --- 3) Artefakty ------------------------------------------------------------
Write-Step "Build TimeTrack.exe (PyInstaller - chvili trva)"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'build_exe.ps1')
if ($LASTEXITCODE -ne 0) { throw "build_exe.ps1 selhal (kod $LASTEXITCODE)." }
$exePath = Join-Path $root 'dist\TimeTrack.exe'
if (-not (Test-Path $exePath)) { throw "Nevznikl $exePath." }
Write-Ok "Exe: $exePath"

Write-Step "Instalacni ZIP"
$stage = Join-Path $env:TEMP ("tt_release_" + [Guid]::NewGuid().ToString('N'))
$stageApp = Join-Path $stage 'TimeTrack'
New-Item -ItemType Directory -Force -Path $stageApp | Out-Null
foreach ($item in $zipItems) {
    $src = Join-Path $root $item
    if (-not (Test-Path $src)) { throw "Do ZIPu chybi '$item'." }
    Copy-Item $src (Join-Path $stageApp $item) -Recurse -Force
}
Get-ChildItem $stageApp -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force
$zipPath = Join-Path $root 'dist\TimeTrack-instalace.zip'
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path (Join-Path $stage 'TimeTrack') -DestinationPath $zipPath
Remove-Item $stage -Recurse -Force
Write-Ok "ZIP: $zipPath"

Write-Step "Kontrolni soucty"
$checksums = Join-Path $root 'dist\checksums.txt'
$lines = foreach ($file in @($zipPath, $exePath)) {
    $hash = (Get-FileHash $file -Algorithm SHA256).Hash.ToLower()
    "$hash  $([IO.Path]::GetFileName($file))"
}
[IO.File]::WriteAllText($checksums, ($lines -join "`n") + "`n", (New-Object Text.UTF8Encoding $false))
Write-Ok "checksums.txt zapsan."

if ($DryRun) {
    Write-Host "`n-DryRun: artefakty jsou v dist\, tag ani release se nezaklada." -ForegroundColor Yellow
    return
}

# --- 4) Tag + GitHub release -------------------------------------------------
Write-Step "GitHub release $Tag"
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "Chybi gh CLI - nainstaluj 'winget install GitHub.cli' a prihlas se 'gh auth login'."
}
git -C $root tag -a $Tag -m "TimeTrack $version"
git -C $root push origin $Tag
$ghArgs = @('release', 'create', $Tag, $zipPath, $exePath, $checksums,
            '--title', "TimeTrack $version", '--verify-tag')
if ($Notes) { $ghArgs += @('--notes', $Notes) } else { $ghArgs += '--generate-notes' }
if ($Prerelease) { $ghArgs += '--prerelease' }
& gh @ghArgs
if ($LASTEXITCODE -ne 0) { throw "gh release create selhal (kod $LASTEXITCODE)." }
Write-Ok "Release $Tag zalozen."
