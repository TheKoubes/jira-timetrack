# Sestavi samostatny TimeTrack.exe pres PyInstaller (nepotrebuje Python na cili).
# Prvni spusteni s -Install doinstaluje PyInstaller:
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Install
# Dalsi buildy:
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1

[CmdletBinding()]
param([switch]$Install)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if ($Install) {
    & py -m pip install --user --upgrade pyinstaller
}

& py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name TimeTrack `
    --icon "assets\timetrack.ico" `
    --add-data "assets\timetrack.ico;assets" `
    run_timetrack.py

$exe = Join-Path $PSScriptRoot 'dist\TimeTrack.exe'
if (Test-Path $exe) {
    Write-Host "Hotovo: $exe ($([math]::Round((Get-Item $exe).Length/1MB,1)) MB)"
} else {
    Write-Error "Build se nezdaril - TimeTrack.exe nevznikl."
}
