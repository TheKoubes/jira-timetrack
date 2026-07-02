@echo off
REM Dvojklik = spusti pruvodce instalaci (obejde ExecutionPolicy bezpecne).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
echo.
pause
