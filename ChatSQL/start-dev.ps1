$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Runtime = Join-Path $Root ".runtime"
$DataRoot = Join-Path (Split-Path -Parent $Root) "ChatSQLData"
$env:BANKNL2SQL_LITE_DATA_ROOT = $DataRoot
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null

$Python = Join-Path $Backend ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  py -3 -m venv (Join-Path $Backend ".venv")
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to create backend virtual environment."
  }
}

$Requirements = Join-Path $Backend "requirements.txt"
$InstalledPackages = @{}
& $Python -m pip list --format json --disable-pip-version-check | ConvertFrom-Json | ForEach-Object {
  $InstalledPackages[$_.name.ToLowerInvariant().Replace("_", "-")] = $_.version
}
$MissingRequirements = @()
foreach ($Line in Get-Content $Requirements) {
  if ($Line -match '^([^=\[]+)(?:\[[^\]]+\])?==(.+)$') {
    $PackageName = $Matches[1].Trim().ToLowerInvariant().Replace("_", "-")
    $RequiredVersion = $Matches[2].Trim()
    if ($InstalledPackages[$PackageName] -ne $RequiredVersion) {
      $MissingRequirements += "$PackageName==$RequiredVersion"
    }
  }
}
if ($MissingRequirements.Count -gt 0) {
  Write-Host "Installing missing backend dependencies: $($MissingRequirements -join ', ')"
  & $Python -m pip install --disable-pip-version-check -r $Requirements
  if ($LASTEXITCODE -ne 0) {
    throw "Backend dependency installation failed. Fix the network/proxy configuration, then run start-dev.ps1 again."
  }
} else {
  Write-Host "Backend dependencies already satisfied; skipping installation."
}

Push-Location $Frontend
if (-not (Test-Path "node_modules")) {
  npm install
}
Pop-Location

$Npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $Npm) {
  $Npm = (Get-Command npm -ErrorAction Stop).Source
}

foreach ($Port in @(8000, 5173)) {
  if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use. Run .\stop-dev.ps1 before starting ChatSQL again."
  }
}

$BackendOutLog = Join-Path $Runtime "backend.out.log"
$BackendErrLog = Join-Path $Runtime "backend.err.log"
$FrontendOutLog = Join-Path $Runtime "frontend.out.log"
$FrontendErrLog = Join-Path $Runtime "frontend.err.log"

$BackendProcess = Start-Process -FilePath $Python -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload") -WorkingDirectory $Backend -RedirectStandardOutput $BackendOutLog -RedirectStandardError $BackendErrLog -PassThru -WindowStyle Hidden
$FrontendProcess = Start-Process -FilePath $Npm -ArgumentList @("run", "dev", "--", "--port", "5173") -WorkingDirectory $Frontend -RedirectStandardOutput $FrontendOutLog -RedirectStandardError $FrontendErrLog -PassThru -WindowStyle Hidden

@{
  backend = $BackendProcess.Id
  frontend = $FrontendProcess.Id
  backend_url = "http://127.0.0.1:8000/api/health"
  frontend_url = "http://127.0.0.1:5173"
} | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $Runtime "dev-processes.json")

$BackendReady = $false
for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
  Start-Sleep -Milliseconds 500
  try {
    $Health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2
    if ($Health.status -eq "ok") {
      $BackendReady = $true
      break
    }
  } catch {
  }
}
if (-not $BackendReady) {
  & (Join-Path $Root "stop-dev.ps1") | Out-Null
  throw "Backend health check failed. See $BackendErrLog"
}

Write-Host "Backend:  http://127.0.0.1:8000/api/health"
Write-Host "Frontend: http://127.0.0.1:5173"
