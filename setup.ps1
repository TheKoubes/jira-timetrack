# TimeTrack — pruvodce instalaci na novem pocítaci (Windows).
#
# Spusteni (staci dvojklik na "Nainstalovat TimeTrack.cmd", nebo rucne):
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#
# Co skript udela:
#   1) overi Python 3.11+ (vcetne tkinter),
#   2) ukonci bezici instanci TimeTrack (po instalaci ji zase spusti),
#   3) zkopiruje aplikaci do %LOCALAPPDATA%\TimeTrack,
#   4) vyrobi spoustec TimeTrack.exe (vlastni jmeno procesu),
#   5) zalozi konfiguraci a pomuze ulozit Jira/Tempo tokeny — pta se jen
#      na hodnoty, ktere jeste nejsou vyplnene (aktualizace = zadne otazky),
#   6) nabidne automaticky start po prihlaseni a hned aplikaci spusti.
#
# Parametry (pro neinteraktivni/skriptovane nasazeni):
#   -InstallDir <cesta>  kam nainstalovat (vychozi %LOCALAPPDATA%\TimeTrack)
#   -Email <adresa>      Atlassian e-mail do configu
#   -JiraUrl <url>       adresa Jira instance (napr. https://firma.atlassian.net)
#   -NoPrompt            nic se nepta (preskoci tokeny, neotevira prohlizec)
#   -Autostart           rovnou vytvori zastupce do Po spusteni
#   -Launch              po instalaci aplikaci spusti

[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'TimeTrack'),
    [string]$Email = '',
    [string]$JiraUrl = '',
    [switch]$NoPrompt,
    [switch]$Autostart,
    [switch]$Launch
)

$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot

function Write-Step($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Write-Ok($text) { Write-Host "  OK  $text" -ForegroundColor Green }
function Write-Warn2($text) { Write-Host "  !!  $text" -ForegroundColor Yellow }

function Invoke-Exe($exe, $arguments, $workDir) {
    # Spusti proces a pocka na nej pres handle (ne pres pipe) — neuvazne ani
    # bez konzole, na rozdil od zachytavani stdout pres '& exe ... 2>$null'.
    $params = @{
        FilePath = $exe; ArgumentList = $arguments; WindowStyle = 'Hidden'
        Wait = $true; PassThru = $true; ErrorAction = 'Stop'
    }
    if ($workDir) { $params['WorkingDirectory'] = $workDir }
    $proc = Start-Process @params
    return $proc.ExitCode
}

function Get-TTVersion($dir) {
    # Precte __version__ z timetrack\__init__.py (nainstalovane ci nove verze).
    $initPath = Join-Path $dir 'timetrack\__init__.py'
    if (Test-Path $initPath) {
        $m = [regex]::Match((Get-Content $initPath -Raw), '__version__\s*=\s*"([^"]+)"')
        if ($m.Success) { return $m.Groups[1].Value }
    }
    return $null
}

function Find-Python {
    # Vrati pole [exe, args...] pro Python 3.11+ s tkinter, jinak $null.
    # Verzi i dostupnost tkinter zapise probe do souboru — zadne ctení pipe.
    $probePy = Join-Path ([IO.Path]::GetTempPath()) 'tt_probe.py'
    @'
import sys, pathlib
try:
    import tkinter  # GUI knihovna musi byt k dispozici
    out = "%d.%d" % sys.version_info[:2]
except Exception:
    out = "notk"
pathlib.Path(sys.argv[1]).write_text(out, encoding="utf-8")
'@ | Set-Content -Path $probePy -Encoding UTF8
    try {
        foreach ($spec in @('py -3', 'python', 'python3')) {
            $parts = $spec.Split(' ')
            $exe = $parts[0]
            if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
            $rest = if ($parts.Length -gt 1) { $parts[1..($parts.Length - 1)] } else { @() }
            $marker = Join-Path ([IO.Path]::GetTempPath()) ("tt_probe_{0}.txt" -f [Guid]::NewGuid().ToString('N'))
            $argList = @($rest) + @("`"$probePy`"", "`"$marker`"")
            try { $code = Invoke-Exe $exe $argList } catch { continue }
            $out = ''
            if (Test-Path $marker) {
                $out = (Get-Content $marker -Raw).Trim()
                Remove-Item $marker -ErrorAction SilentlyContinue
            }
            if ($code -eq 0 -and $out -match '^(\d+)\.(\d+)$') {
                if ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 11)) {
                    return , (@($exe) + $rest)  # carka brani rozbaleni jednoprvkoveho pole
                }
            }
        }
    } finally {
        Remove-Item $probePy -ErrorAction SilentlyContinue
    }
    return $null
}

function Save-TextFile($path, $value) {
    # Zapis bez BOM (config i tokeny cte Python jako utf-8; BOM by prekazel).
    [IO.File]::WriteAllText($path, $value, (New-Object Text.UTF8Encoding $false))
}

Write-Host "TimeTrack - instalace" -ForegroundColor White

# --- 1) Python -------------------------------------------------------------
Write-Step "Kontrola Pythonu"
$python = Find-Python
if (-not $python) {
    Write-Warn2 "Nenasel jsem Python 3.11+ s podporou tkinter."
    Write-Host  "  Nainstaluj ho z https://www.python.org/downloads/ (zaskrtni"
    Write-Host  "  'Add python.exe to PATH') a spust setup.ps1 znovu."
    if (-not $NoPrompt) {
        if ((Read-Host "  Otevrit stranku ke stazeni Pythonu? [a/N]") -match '^[aAyY]') {
            Start-Process "https://www.python.org/downloads/"
        }
    }
    throw "Chybi Python 3.11+."
}
$pyExe = $python[0]
$pyArgs = @($python | Select-Object -Skip 1)
Write-Ok "Python nalezen: $pyExe $($pyArgs -join ' ')"

# --- 1b) Ukonceni bezici aplikace ------------------------------------------
# Bezici instance drzi zamek na spousteci .venv\Scripts\TimeTrack.exe a po
# aktualizaci by stejne bezela stara verze z pameti. Data jsou append-only
# na disku, ukoncenim se nic neztrati.
$wasRunning = $false
$quitCode = Invoke-Exe $pyExe (@($pyArgs) + @('-m', 'timetrack', 'quit')) $source
if ($quitCode -eq 0) {
    $wasRunning = $true
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Process TimeTrack -ErrorAction SilentlyContinue) -and ((Get-Date) -lt $deadline)) {
        Start-Sleep -Milliseconds 300
    }
    $leftover = Get-Process TimeTrack -ErrorAction SilentlyContinue
    if ($leftover) { $leftover | Stop-Process -Force }
    Write-Ok "Bezici TimeTrack ukoncen (po instalaci ho zase spustim)."
}

# --- 2) Kopie aplikace -----------------------------------------------------
Write-Step "Kopie aplikace do $InstallDir"
$oldVer = Get-TTVersion $InstallDir
$newVer = Get-TTVersion $source
$resolvedInstall = (Resolve-Path -LiteralPath $InstallDir -ErrorAction SilentlyContinue).Path
$same = $resolvedInstall -and ((Resolve-Path $source).Path -eq $resolvedInstall)
if ($same) {
    Write-Ok "Instaluji primo ve zdrojove slozce."
} else {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    foreach ($item in @('timetrack', 'assets', 'README.md', 'install_autostart.ps1')) {
        $src = Join-Path $source $item
        if (Test-Path $src) {
            Copy-Item $src (Join-Path $InstallDir $item) -Recurse -Force
        }
    }
    Get-ChildItem $InstallDir -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force
    Write-Ok "Soubory zkopirovany."
}
if ($oldVer -and $newVer -and $oldVer -ne $newVer) {
    Write-Ok "Aktualizace $oldVer -> $newVer"
} elseif ($newVer) {
    Write-Ok "Verze $newVer"
}

# --- 3) Spoustec TimeTrack.exe --------------------------------------------
Write-Step "Vytvoreni spoustece"
$venv = Join-Path $InstallDir '.venv'
if (-not (Test-Path (Join-Path $venv 'Scripts\pythonw.exe'))) {
    $code = Invoke-Exe $pyExe (@($pyArgs) + @('-m', 'venv', '--without-pip', "`"$venv`""))
    if ($code -ne 0) { throw "Vytvoreni venv selhalo (kod $code)." }
}
$launcher = Join-Path $venv 'Scripts\TimeTrack.exe'
Copy-Item (Join-Path $venv 'Scripts\pythonw.exe') $launcher -Force
Write-Ok "Spoustec: $launcher"

# --- 4) Konfigurace + tokeny ----------------------------------------------
Write-Step "Konfigurace"
$tokenDir = Join-Path $env:USERPROFILE '.timetrack'
New-Item -ItemType Directory -Force -Path $tokenDir | Out-Null
$cfgPath = Join-Path $tokenDir 'config.json'
$cfg = [ordered]@{}
if (Test-Path $cfgPath) {
    (Get-Content $cfgPath -Raw | ConvertFrom-Json).PSObject.Properties |
        ForEach-Object { $cfg[$_.Name] = $_.Value }
}
# Na e-mail a adresu Jiry se ptame jen kdyz jeste nejsou v configu
# (aktualizace = bez otazek). Account pole si aplikace najde sama.
if (-not $NoPrompt -and -not $Email -and -not $cfg['jira_email']) {
    $Email = Read-Host "  Tvuj Atlassian e-mail (napr. jmeno@firma.cz)"
}
if (-not $NoPrompt -and -not $JiraUrl -and -not $cfg['jira_base_url']) {
    $JiraUrl = Read-Host "  Adresa vasi Jiry (napr. https://firma.atlassian.net; Enter = doplnis pozdeji)"
}
if ($JiraUrl) {
    $JiraUrl = $JiraUrl.Trim().TrimEnd('/')
    if ($JiraUrl -notmatch '^https?://') { $JiraUrl = "https://$JiraUrl" }
    $cfg['jira_base_url'] = "$JiraUrl/browse/"
}
if ($Email) { $cfg['jira_email'] = $Email }
if ($null -eq $cfg['jira_email']) { $cfg['jira_email'] = '' }
if ($null -eq $cfg['jira_base_url']) { $cfg['jira_base_url'] = '' }
Save-TextFile $cfgPath (($cfg | ConvertTo-Json))
$emailUsed = if ($cfg['jira_email']) { $cfg['jira_email'] } else { '(zatim nevyplnen)' }
Write-Ok "Config: $cfgPath (e-mail: $emailUsed)"

# Tokeny: ptame se jen na ty, ktere jeste nejsou ulozene. Zmenu existujiciho
# tokenu udela uzivatel v aplikaci (Nastaveni -> Integrace).
if (-not $NoPrompt) {
    $needJira = -not (Test-Path (Join-Path $tokenDir 'jira_token'))
    $needTempo = -not (Test-Path (Join-Path $tokenDir 'tempo_token'))
    if ($needJira -or $needTempo) {
        Write-Host "  Ted budes potrebovat tokeny (zdarma). Stranku ti otevru."
    } else {
        Write-Ok "Tokeny uz jsou ulozene - preskakuji."
    }
    if ($needJira) {
        if ((Read-Host "  Otevrit stranku pro Jira token? [A/n]") -notmatch '^[nN]') {
            Start-Process "https://id.atlassian.com/manage-profile/security/api-tokens"
        }
        $jira = Read-Host "  Vloz Jira API token (Enter = doplnim pozdeji)"
        if ($jira) { Save-TextFile (Join-Path $tokenDir 'jira_token') $jira.Trim(); Write-Ok "jira_token ulozen." }
    }
    if ($needTempo) {
        # Stranka Tempo tokenu zije primo v Jire -> odvodi se z jira_base_url.
        $site = ''
        if ("$($cfg['jira_base_url'])" -match '^(https?://[^/]+)') { $site = $Matches[1] }
        if ($site -and (Read-Host "  Otevrit stranku pro Tempo token? [A/n]") -notmatch '^[nN]') {
            Start-Process "$site/plugins/servlet/ac/io.tempo.jira/tempo-app#!/configuration/api-integration"
        }
        $tempo = Read-Host "  Vloz Tempo API token (jen s pluginem Tempo; Enter = preskocit)"
        if ($tempo) { Save-TextFile (Join-Path $tokenDir 'tempo_token') $tempo.Trim(); Write-Ok "tempo_token ulozen." }
    }
}

# --- 5) Autostart + spusteni ----------------------------------------------
$installAutostart = $Autostart
$lnkPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'TimeTrack.lnk'
if (Test-Path $lnkPath) {
    $installAutostart = $true   # uz nastaveno drive -> jen mlcky obnovit zastupce
} elseif (-not $NoPrompt -and -not $Autostart) {
    $installAutostart = (Read-Host "`n  Spoustet TimeTrack automaticky po prihlaseni? [A/n]") -notmatch '^[nN]'
}
if ($installAutostart) {
    Write-Step "Automaticky start"
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $InstallDir 'install_autostart.ps1')
}

# Kdyz jsme na zacatku ukoncili bezici instanci, spustime ji zase bez ptani.
$doLaunch = $Launch -or $wasRunning
if (-not $NoPrompt -and -not $doLaunch) {
    $doLaunch = (Read-Host "`n  Spustit TimeTrack hned ted? [A/n]") -notmatch '^[nN]'
}
if ($doLaunch) {
    Start-Process -FilePath $launcher -ArgumentList '-m', 'timetrack' -WorkingDirectory $InstallDir
    Write-Ok "TimeTrack bezi - hledej ikonu v systemove liste (Ctrl+Alt+T)."
}

Write-Host "`nHotovo. Aplikace je v: $InstallDir" -ForegroundColor White
if ($emailUsed -eq '(zatim nevyplnen)' -or -not (Test-Path (Join-Path $tokenDir 'jira_token'))) {
    Write-Warn2 "Nez zacnes posilat do Jiry, doplň e-mail a tokeny - viz INSTALL.md."
}
