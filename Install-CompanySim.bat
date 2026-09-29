@echo off
setlocal EnableExtensions
title company_sim - Windows install and launch

:: Double-click this file once. It will:
::   1) Find or clone this repo
::   2) Install Python 3.11+ if missing (winget)
::   3) Install Ollama if missing (winget / download)
::   4) Start Ollama and pull qwen2.5:3b-instruct
::   5) Create a venv and install Python deps
::   6) Write Launch-CompanySim.bat for next time
::   7) Start the game with LLM rivals enabled
::
:: Re-run anytime; steps already done are skipped.

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-CompanySim.ps1" %*
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo.
  echo Install failed with exit code %ERR%.
  pause
  exit /b %ERR%
)
endlocal
exit /b 0
