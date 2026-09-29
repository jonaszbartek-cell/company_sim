#Requires -Version 5.1
<#
.SYNOPSIS
  Fully automatic Windows install for company_sim + Ollama AI.

.DESCRIPTION
  Installs everything needed (Python, Ollama, AI model, game runtime).
  Double-click Install-CompanySim.bat — no manual steps.

  After install, double-click Launch-CompanySim.bat to play.
  Launch starts Ollama with the game and stops it when the game closes.
#>
[CmdletBinding()]
param(
  [switch]$SkipLaunch,
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
  Write-Host "    $Message" -ForegroundColor Green
}

function Write-Warn([string]$Message) {
  Write-Host "    $Message" -ForegroundColor Yellow
}

function Test-Command([string]$Name) {
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Refresh-Path {
  $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = "$machinePath;$userPath"
}

function Test-OllamaApi {
  try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 2
    return ($resp.StatusCode -eq 200)
  } catch {
    return $false
  }
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

function Install-PythonRuntime {
  Write-Step "Installing game engine (Python)"
  if (-not (Test-Command "winget")) {
    throw "Python is missing and Windows Package Manager (winget) is unavailable. Install Python 3.12 from https://www.python.org/downloads/ (enable 'Add python.exe to PATH'), then run Install again."
  }
  & winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements --disable-interactivity
  if ($LASTEXITCODE -ne 0) {
    throw "Could not install Python automatically (winget exit $LASTEXITCODE)."
  }
  Refresh-Path
  $py = Get-PythonCandidate
  if (-not $py) {
    throw "Python was installed but is not available yet. Close this window, open it again, and re-run Install-CompanySim.bat."
  }
  return $py
}

function Get-OllamaExe {
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
    (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
  )
  foreach ($c in $candidates) {
    if (Test-Path $c) { return $c }
  }
  $cmd = Get-Command "ollama" -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}

function Install-OllamaApp {
  Write-Step "Installing Ollama (local AI)"
  if (Test-Command "winget") {
    & winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements --disable-interactivity
    Refresh-Path
    $exe = Get-OllamaExe
    if ($exe) { return $exe }
    Write-Warn "winget did not place Ollama on PATH — downloading installer..."
  }

  $setup = Join-Path $env:TEMP "OllamaSetup.exe"
  Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $setup -UseBasicParsing
  $p = Start-Process -FilePath $setup -ArgumentList "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES" -PassThru -Wait
  if ($null -ne $p.ExitCode -and $p.ExitCode -ne 0) {
    Write-Warn "Silent install returned $($p.ExitCode); opening installer window..."
    Start-Process -FilePath $setup -Wait
  }
  Refresh-Path
  Start-Sleep -Seconds 2
  $exe = Get-OllamaExe
  if (-not $exe) {
    throw "Ollama install finished but ollama.exe was not found. Reboot once, then re-run Install."
  }
  return $exe
}

function Start-OllamaForInstall([string]$OllamaExe) {
  $already = Test-OllamaApi
  if ($already) {
    return [pscustomobject]@{ StartedByUs = $false; Process = $null }
  }
  $proc = Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden -PassThru
  $deadline = (Get-Date).AddSeconds(90)
  while ((Get-Date) -lt $deadline) {
    if (Test-OllamaApi) {
      return [pscustomobject]@{ StartedByUs = $true; Process = $proc }
    }
    Start-Sleep -Seconds 1
  }
  throw "Ollama did not become ready after install."
}

function Stop-OllamaIfOurs($Handle) {
  if (-not $Handle -or -not $Handle.StartedByUs -or -not $Handle.Process) { return }
  try {
    if (-not $Handle.Process.HasExited) {
      & taskkill.exe /PID $Handle.Process.Id /T /F 2>$null | Out-Null
    }
  } catch { }
}

function Resolve-RepoRoot {
  $here = $PSScriptRoot
  if (-not $here) { $here = (Get-Location).Path }

  $marker = Join-Path $here "src\company_sim\__main__.py"
  if (Test-Path $marker) { return $here }

  $parent = Split-Path $here -Parent
  if (Test-Path (Join-Path $parent "src\company_sim\__main__.py")) { return $parent }

  $root = if ($InstallRoot) { $InstallRoot } else { Join-Path $env:LOCALAPPDATA "company_sim" }
  Write-Step "Downloading game files to $root"
  if (-not (Test-Command "git")) {
    if (Test-Command "winget") {
      & winget install -e --id Git.Git --accept-package-agreements --accept-source-agreements --disable-interactivity
      Refresh-Path
    }
    if (-not (Test-Command "git")) {
      throw "Git is required to download the game automatically."
    }
  }
  if (Test-Path (Join-Path $root "src\company_sim\__main__.py")) {
    Write-Ok "Game files already present."
    return $root
  }
  if (Test-Path $root) { Remove-Item -Recurse -Force $root }
  & git clone --depth 1 $RepoUrl $root
  if ($LASTEXITCODE -ne 0) { throw "Could not download game files." }
  return $root
}

function Install-GameRuntime([object]$Python, [string]$RepoRoot) {
  Write-Step "Installing game runtime"
  $runtimeDir = Join-Path $RepoRoot ".venv"
  $runtimePy = Join-Path $runtimeDir "Scripts\python.exe"
  if (-not (Test-Path $runtimePy)) {
    if ($Python.Cmd -eq "py") {
      & py -3 -m venv $runtimeDir
    } else {
      & $Python.Exe -m venv $runtimeDir
    }
    if ($LASTEXITCODE -ne 0) { throw "Could not create game runtime." }
  }
  & $runtimePy -m pip install --upgrade pip --disable-pip-version-check | Out-Null
  & $runtimePy -m pip install -r (Join-Path $RepoRoot "requirements.txt") --disable-pip-version-check
  if ($LASTEXITCODE -ne 0) { throw "Could not install game packages." }
  Write-Ok "Game runtime ready."
  return $runtimePy
}

function Save-InstallConfig([string]$RepoRoot, [string]$ModelName) {
  $cfg = Join-Path $RepoRoot "company_sim.windows.json"
  @{
    model = $ModelName
    installed_at = (Get-Date).ToString("o")
  } | ConvertTo-Json | Set-Content -Path $cfg -Encoding UTF8
}

# ---- main ----
$ollamaHandle = $null
try {
  Write-Host "company_sim installer" -ForegroundColor White
  Write-Host "This installs everything. Then use Launch-CompanySim.bat to play."
  Write-Host ""

  $repo = Resolve-RepoRoot
  Set-Location $repo
  Write-Ok "Game folder: $repo"

  Write-Step "Checking game engine (Python)"
  $py = Get-PythonCandidate
  if (-not $py) { $py = Install-PythonRuntime }
  Write-Ok "Python $($py.Version) ready."

  Write-Step "Checking Ollama (local AI)"
  $ollama = Get-OllamaExe
  if (-not $ollama) { $ollama = Install-OllamaApp }
  Write-Ok "Ollama ready."

  Write-Step "Preparing AI model $Model"
  $ollamaHandle = Start-OllamaForInstall $ollama
  & $ollama pull $Model
  if ($LASTEXITCODE -ne 0) { throw "Could not download AI model $Model." }
  Write-Ok "AI model ready: $Model"
  # Install should not leave Ollama running — Launch starts/stops it with the game.
  Stop-OllamaIfOurs $ollamaHandle
  $ollamaHandle = $null

  $null = Install-GameRuntime -Python $py -RepoRoot $repo
  Save-InstallConfig -RepoRoot $repo -ModelName $Model

  # Ensure Launch scripts exist in the install folder (already in repo; rewrite bat title only if missing)
  $launchBat = Join-Path $repo "Launch-CompanySim.bat"
  $launchPs1 = Join-Path $repo "Launch-CompanySim.ps1"
  if (-not (Test-Path $launchBat) -or -not (Test-Path $launchPs1)) {
    throw "Launch-CompanySim.bat / .ps1 missing from the game folder. Re-download the repo."
  }

  Write-Host ""
  Write-Host "========================================" -ForegroundColor Green
  Write-Host " Install complete." -ForegroundColor Green
  Write-Host " Double-click Launch-CompanySim.bat to play." -ForegroundColor Green
  Write-Host " (Launch starts Ollama + game, then stops Ollama when you quit.)" -ForegroundColor Green
  Write-Host "========================================" -ForegroundColor Green

  if (-not $SkipLaunch) {
    Write-Step "Starting game now"
    $launchScript = Join-Path $repo "Launch-CompanySim.ps1"
    & powershell -NoProfile -ExecutionPolicy Bypass -File $launchScript -Model $Model
    exit $LASTEXITCODE
  }
  exit 0
}
catch {
  Write-Host ""
  Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}
finally {
  Stop-OllamaIfOurs $ollamaHandle
}
