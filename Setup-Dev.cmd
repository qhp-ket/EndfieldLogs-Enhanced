@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0_development\tools\setup_dev.ps1" %*
exit /b %ERRORLEVEL%
