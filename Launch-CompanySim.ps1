#Requires -Version 5.1
<#
.SYNOPSIS
  Launch company_sim with Ollama: start AI with the game, stop AI when the game exits.
#>
[CmdletBinding()]
param(
  [string]$Model = "qwen2.5:3b-instruct"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoRoot = $PSScriptRoot
if (-not $RepoRoot) { $RepoRoot = (Get-Location).Path }
Set-Location $RepoRoot

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Marker = Join-Path $RepoRoot "src\company_sim\__main__.py"
$ConfigPath = Join-Path $RepoRoot "company_sim.windows.json"
if (Test-Path $ConfigPath) {
  try {
    $cfg = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    if ($cfg.model) { $Model = [string]$cfg.model }
  } catch { }
}

function Test-OllamaApi {
  try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 2
    return ($resp.StatusCode -eq 200)
  } catch {
    return $false
  }
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

function Wait-OllamaReady([int]$Seconds = 90) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-OllamaApi) { return $true }
    Start-Sleep -Seconds 1
  }
  return $false
}

function Stop-OllamaTree([System.Diagnostics.Process]$ServeProcess) {
  if ($null -eq $ServeProcess) { return }
  try {
    if (-not $ServeProcess.HasExited) {
      # Kill serve and children (Windows often spawns helper processes)
      & taskkill.exe /PID $ServeProcess.Id /T /F 2>$null | Out-Null
    }
  } catch { }
  try { $ServeProcess.Dispose() } catch { }
}

if (-not (Test-Path $Marker)) {
  Write-Host "ERROR: Game files not found in $RepoRoot" -ForegroundColor Red
  exit 1
}
if (-not (Test-Path $VenvPython)) {
  Write-Host "ERROR: Game is not installed. Run Install-CompanySim.bat first." -ForegroundColor Red
  exit 1
}

$ollamaExe = Get-OllamaExe
if (-not $ollamaExe) {
  Write-Host "ERROR: Ollama is not installed. Run Install-CompanySim.bat first." -ForegroundColor Red
  exit 1
}

$startedByUs = $false
$serveProc = $null
$wasAlreadyUp = Test-OllamaApi

try {
  if (-not $wasAlreadyUp) {
    Write-Host "Starting Ollama (AI)..." -ForegroundColor Cyan
    $serveProc = Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden -PassThru
    $startedByUs = $true
    if (-not (Wait-OllamaReady)) {
      throw "Ollama did not start. Try opening the Ollama app once, then launch again."
    }
    Write-Host "Ollama is ready." -ForegroundColor Green
  } else {
    Write-Host "Ollama already running — reusing it." -ForegroundColor Green
  }

  # Ensure model exists (quiet no-op if already pulled during install)
  Write-Host "Checking AI model $Model ..." -ForegroundColor Cyan
  & $ollamaExe show $Model 2>$null | Out-Null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Downloading AI model $Model (first time can take a few minutes)..." -ForegroundColor Cyan
    & $ollamaExe pull $Model
    if ($LASTEXITCODE -ne 0) { throw "Failed to download AI model $Model" }
  }

  Write-Host "Starting game (browser should open http://127.0.0.1:8765/)..." -ForegroundColor Cyan
  Write-Host "Close this window or press Ctrl+C to stop the game." -ForegroundColor DarkGray
  Write-Host ""

  $env:COMPANY_SIM_LLM = "1"
  $env:COMPANY_SIM_LLM_MODEL = $Model
  $env:COMPANY_SIM_LLM_URL = "http://127.0.0.1:11434"
  $env:PYTHONPATH = "src"

  $game = Start-Process -FilePath $VenvPython -ArgumentList "-m", "company_sim" -WorkingDirectory $RepoRoot -NoNewWindow -PassThru
  Wait-Process -Id $game.Id
  exit $game.ExitCode
}
catch {
  Write-Host ""
  Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}
finally {
  if ($startedByUs) {
    Write-Host "Stopping Ollama (started with the game)..." -ForegroundColor Cyan
    Stop-OllamaTree $serveProc
  }
}
