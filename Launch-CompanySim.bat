@echo off
setlocal EnableExtensions
title company_sim

:: LAUNCH
:: Starts Ollama + the game together.
:: When you close the game (or this window), Ollama started by us is stopped.

cd /d "%~dp0"

if not exist "%~dp0Install-CompanySim.ps1" (
  echo Installer scripts missing. Re-download the game folder.
  pause
  exit /b 1
)

if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Game is not installed yet.
  echo Running installer first...
  echo.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-CompanySim.ps1" -SkipLaunch
  if errorlevel 1 (
    echo Install failed.
    pause
    exit /b 1
  )
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launch-CompanySim.ps1" %*
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo.
  echo Game stopped with an error.
  pause
)
endlocal
exit /b %ERR%
