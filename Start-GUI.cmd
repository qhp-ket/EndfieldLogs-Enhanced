@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0_internal\dotnet\Start.ps1" %*
if errorlevel 1 pause
