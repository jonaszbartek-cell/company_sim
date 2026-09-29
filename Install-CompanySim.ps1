#Requires -Version 5.1
<#
.SYNOPSIS
  One-shot Windows install + launch for company_sim (game + Ollama LLM rivals).

.DESCRIPTION
  - Locates this repo, or clones it to %LOCALAPPDATA%\company_sim
  - Ensures Python 3.11+ (winget)
  - Ensures Ollama (winget, else downloads OllamaSetup.exe)
  - Starts Ollama and pulls qwen2.5:3b-instruct
  - Creates .venv and installs requirements
  - Writes Launch-CompanySim.bat for later double-click runs
  - Starts the game with COMPANY_SIM_LLM=1 and opens the browser

  Run via Install-CompanySim.bat (double-click) or:
    powershell -ExecutionPolicy Bypass -File Install-CompanySim.ps1
#>
[CmdletBinding()]
param(
  [switch]$SkipLaunch,
  [switch]$SkipOllama,
  [string]$Model = "qwen2.5:3b-instruct",
  [string]$RepoUrl = "https://github.com/jonaszbartek-cell/company_sim.git",
  [string]$InstallRoot = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Step([string]$Message) {
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
  Write-Host "    OK: $Message" -ForegroundColor Green
}

function Write-Warn([string]$Message) {
  Write-Host "    WARN: $Message" -ForegroundColor Yellow
}

function Test-Command([string]$Name) {
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-PythonCandidate {
  $cmds = @("py", "python", "python3")
  foreach ($cmd in $cmds) {
    if (-not (Test-Command $cmd)) { continue }
    try {
      if ($cmd -eq "py") {
        $verText = & py -3 -c "import sys; print('%d.%d'%sys.version_info[:2])" 2>$null
        $exe = & py -3 -c "import sys; print(sys.executable)" 2>$null
      } else {
        $verText = & $cmd -c "import sys; print('%d.%d'%sys.version_info[:2])" 2>$null
        $exe = & $cmd -c "import sys; print(sys.executable)" 2>$null
      }
      if (-not $verText -or -not $exe) { continue }
      # Reject Windows Store python stubs that print an install tip and exit oddly
      if ($exe -match "WindowsApps") { continue }
      $parts = $verText.Trim().Split(".")
      if ($parts.Count -lt 2) { continue }
      $major = [int]$parts[0]; $minor = [int]$parts[1]
      if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) {
        return [pscustomobject]@{ Cmd = $cmd; Exe = $exe.Trim(); Version = $verText.Trim() }
      }
    } catch {
      continue
    }
  }
  return $null
}

function Install-Python311 {
  Write-Step "Installing Python 3.12 (winget)"
  if (-not (Test-Command "winget")) {
    throw "Python 3.11+ not found and winget is unavailable. Install Python from https://www.python.org/downloads/ (check 'Add python.exe to PATH'), then re-run this script."
  }
  & winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements --disable-interactivity
  if ($LASTEXITCODE -ne 0) {
    throw "winget failed to install Python (exit $LASTEXITCODE). Install Python 3.11+ manually, then re-run."
  }
  # Refresh PATH for this session
  $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = "$machinePath;$userPath"
  $py = Get-PythonCandidate
  if (-not $py) {
    throw "Python was installed but is not on PATH yet. Close this window, open a new one, and re-run Install-CompanySim.bat."
  }
  return $py
}

function Get-OllamaExe {
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
    (Join-Path $env:ProgramFiles "Ollama\ollama.exe"),
    "ollama"
  )
  foreach ($c in $candidates) {
    if ($c -eq "ollama") {
      if (Test-Command "ollama") { return (Get-Command ollama).Source }
      continue
    }
    if (Test-Path $c) { return $c }
  }
  return $null
}

function Install-OllamaApp {
  Write-Step "Installing Ollama"
  if (Test-Command "winget") {
    Write-Host "    Trying winget Ollama.Ollama ..."
    & winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -eq 0) {
      $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
      $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
      $env:Path = "$machinePath;$userPath"
      $exe = Get-OllamaExe
      if ($exe) { return $exe }
    } else {
      Write-Warn "winget Ollama install returned $LASTEXITCODE — falling back to direct download"
    }
  }

  $setup = Join-Path $env:TEMP "OllamaSetup.exe"
  Write-Host "    Downloading OllamaSetup.exe ..."
  Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $setup -UseBasicParsing
  Write-Host "    Running Ollama installer (may show a GUI) ..."
  $p = Start-Process -FilePath $setup -ArgumentList "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES" -PassThru -Wait
  if ($p.ExitCode -ne 0 -and $p.ExitCode -ne $null) {
    Write-Warn "Silent install exit $($p.ExitCode); retrying interactive installer"
    Start-Process -FilePath $setup -Wait
  }
  $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = "$machinePath;$userPath"
  Start-Sleep -Seconds 2
  $exe = Get-OllamaExe
  if (-not $exe) {
    throw "Ollama installed but ollama.exe not found. Reboot or open a new terminal, then re-run this script."
  }
  return $exe
}

function Wait-OllamaReady([string]$OllamaExe, [int]$Seconds = 90) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $resp = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 2
      if ($resp.StatusCode -eq 200) { return $true }
    } catch {
      # start serve if needed
    }
    # Ensure a serve process exists (Windows app usually auto-serves; this is a safety net)
    $running = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
    if (-not $running) {
      Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden
    }
    Start-Sleep -Seconds 2
  }
  return $false
}

function Resolve-RepoRoot {
  $here = $PSScriptRoot
  if (-not $here) { $here = (Get-Location).Path }

  $marker = Join-Path $here "src\company_sim\__main__.py"
  if (Test-Path $marker) { return $here }

  $parentMarker = Join-Path (Split-Path $here -Parent) "src\company_sim\__main__.py"
  if (Test-Path $parentMarker) { return (Split-Path $here -Parent) }

  $root = if ($InstallRoot) { $InstallRoot } else { Join-Path $env:LOCALAPPDATA "company_sim" }
  Write-Step "Game sources not found next to this script — cloning into $root"
  if (-not (Test-Command "git")) {
    if (Test-Command "winget") {
      Write-Host "    Installing Git via winget ..."
      & winget install -e --id Git.Git --accept-package-agreements --accept-source-agreements --disable-interactivity
      $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
      $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
      $env:Path = "$machinePath;$userPath"
    }
    if (-not (Test-Command "git")) {
      throw "Git is required to download the game. Install Git for Windows, then re-run."
    }
  }
  if (Test-Path (Join-Path $root "src\company_sim\__main__.py")) {
    Write-Ok "Already cloned at $root"
    return $root
  }
  if (Test-Path $root) {
    Remove-Item -Recurse -Force $root
  }
  & git clone --depth 1 $RepoUrl $root
  if ($LASTEXITCODE -ne 0) { throw "git clone failed (exit $LASTEXITCODE)" }
  return $root
}

function New-LaunchBat([string]$RepoRoot, [string]$ModelName) {
  $launchPath = Join-Path $RepoRoot "Launch-CompanySim.bat"
  # Prefer venv python relative to repo so the launcher stays portable.
  $relPy = ".venv\Scripts\python.exe"
  $content = @"
@echo off
setlocal
cd /d "%~dp0"
title company_sim

set "COMPANY_SIM_LLM=1"
set "COMPANY_SIM_LLM_MODEL=$ModelName"
set "COMPANY_SIM_LLM_URL=http://127.0.0.1:11434"
set "PYTHONPATH=src"

if not exist "$relPy" (
  echo Missing $relPy — run Install-CompanySim.bat first.
  pause
  exit /b 1
)

where ollama >nul 2>&1
if %ERRORLEVEL%==0 (
  start "" /MIN ollama serve
) else if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
  start "" /MIN "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" serve
)

echo Starting company_sim with LLM model %COMPANY_SIM_LLM_MODEL% ...
echo Open http://127.0.0.1:8765/ if the browser does not open.
echo.
"$relPy" -m company_sim
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo.
  echo Game exited with code %ERR%.
  pause
)
endlocal
exit /b %ERR%
"@
  Set-Content -Path $launchPath -Value $content -Encoding ASCII
  return $launchPath
}

# ---- main ----
try {
  Write-Host "company_sim Windows installer" -ForegroundColor White
  Write-Host "Model: $Model"

  $repo = Resolve-RepoRoot
  Set-Location $repo
  Write-Ok "Repo root: $repo"

  Write-Step "Checking Python 3.11+"
  $py = Get-PythonCandidate
  if (-not $py) { $py = Install-Python311 }
  Write-Ok "Python $($py.Version) at $($py.Exe)"

  if (-not $SkipOllama) {
    Write-Step "Checking Ollama"
    $ollama = Get-OllamaExe
    if (-not $ollama) { $ollama = Install-OllamaApp }
    Write-Ok "Ollama at $ollama"

    Write-Step "Waiting for Ollama API on 127.0.0.1:11434"
    if (-not (Wait-OllamaReady $ollama)) {
      throw "Ollama did not become ready on http://127.0.0.1:11434. Start the Ollama app from the Start menu, then re-run."
    }
    Write-Ok "Ollama API is up"

    Write-Step "Pulling model $Model (first time can take several minutes)"
    & $ollama pull $Model
    if ($LASTEXITCODE -ne 0) {
      throw "ollama pull $Model failed (exit $LASTEXITCODE)"
    }
    Write-Ok "Model ready: $Model"
  } else {
    Write-Warn "Skipping Ollama (-SkipOllama). Game will use heuristic AI unless Ollama is already running."
  }

  Write-Step "Creating virtualenv and installing Python packages"
  $venvDir = Join-Path $repo ".venv"
  $venvPy = Join-Path $venvDir "Scripts\python.exe"
  if (-not (Test-Path $venvPy)) {
    if ($py.Cmd -eq "py") {
      & py -3 -m venv $venvDir
    } else {
      & $py.Exe -m venv $venvDir
    }
    if ($LASTEXITCODE -ne 0) { throw "python -m venv failed" }
  }
  & $venvPy -m pip install --upgrade pip
  & $venvPy -m pip install -r (Join-Path $repo "requirements.txt")
  if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
  Write-Ok "Dependencies installed in .venv"

  Write-Step "Writing Launch-CompanySim.bat"
  $launch = New-LaunchBat -RepoRoot $repo -ModelName $Model
  Write-Ok "Next time double-click: $launch"

  if ($SkipLaunch) {
    Write-Host ""
    Write-Host "Install complete. Launch skipped (-SkipLaunch)." -ForegroundColor Green
    exit 0
  }

  Write-Step "Starting company_sim (LLM enabled)"
  $env:COMPANY_SIM_LLM = "1"
  $env:COMPANY_SIM_LLM_MODEL = $Model
  $env:COMPANY_SIM_LLM_URL = "http://127.0.0.1:11434"
  $env:PYTHONPATH = "src"
  Write-Host "    Browser should open http://127.0.0.1:8765/"
  Write-Host "    Press Ctrl+C in this window to stop the server."
  Write-Host ""
  & $venvPy -m company_sim
  exit $LASTEXITCODE
}
catch {
  Write-Host ""
  Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host $_.ScriptStackTrace -ForegroundColor DarkRed
  exit 1
}
