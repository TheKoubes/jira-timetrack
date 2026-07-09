@echo off
REM Dvojklik = zkontroluje GitHub a nainstaluje novejsi verzi, pokud vysla.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1"
echo.
pause
