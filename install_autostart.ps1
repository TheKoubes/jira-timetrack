# Vytvori zastupce ve slozce Po spusteni (shell:startup), aby TimeTrack
# nabehl po prihlaseni do Windows — na pozadi, bez okna konzole.
# Spusteni:  powershell -ExecutionPolicy Bypass -File install_autostart.ps1

$ErrorActionPreference = 'Stop'

# Radeji vlastni launcher (proces se pak ve Spravci uloh jmenuje TimeTrack.exe),
# kdyz neexistuje, pythonw z PATH.
$launcher = Join-Path $PSScriptRoot '.venv\Scripts\TimeTrack.exe'
$pythonw = if (Test-Path $launcher) { $launcher } else { (Get-Command pythonw -ErrorAction SilentlyContinue).Source }
if (-not $pythonw) {
    Write-Error "pythonw.exe nenalezen v PATH. Nainstaluj Python z python.org."
}

$startup = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startup 'TimeTrack.lnk'

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '-m timetrack'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = 'TimeTrack - evidence odpracovaneho casu'
$shortcut.Save()

Write-Output "Hotovo. Zastupce vytvoren: $shortcutPath"
Write-Output "TimeTrack se spusti automaticky po dalsim prihlaseni."
Write-Output "Pro okamzite spusteni: pythonw -m timetrack (ve slozce projektu)"
