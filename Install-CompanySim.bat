@echo off
setlocal EnableExtensions
title company_sim - Install

:: INSTALL ONLY
:: Double-click once. Automatically installs everything needed:
::   - Python (game engine)
::   - Ollama (local AI)
::   - AI model qwen2.5:3b-instruct
::   - Game runtime files
:: Then use Launch-CompanySim.bat to play.
::
:: Safe to re-run; already-installed pieces are skipped.

cd /d "%~dp0"
echo.
echo Installing company_sim - please wait...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-CompanySim.ps1" -SkipLaunch %*
set "ERR=%ERRORLEVEL%"
echo.
if not "%ERR%"=="0" (
  echo Install FAILED.
  pause
  exit /b %ERR%
)
echo Install finished.
echo Double-click Launch-CompanySim.bat to play.
echo.
pause
endlocal
exit /b 0
